#!/usr/bin/env python3
"""
WatchSmart Personalization Stress-Test Suite
============================================
Simulates 5 deterministic user personas (150 swipes each by default) and
measures how aggressively the recommendation engine adapts over time.

Usage:
    python3 backend/tests/test_personalization_stress.py          # 150 swipes
    python3 backend/tests/test_personalization_stress.py --quick  # 50 swipes
"""

import asyncio
import os
import random
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
os.chdir(os.path.join(_HERE, ".."))

from core import db, get_catalog, load_catalog_from_db          # noqa: E402
from engine import build_feed, ADJACENT_GENRES                  # noqa: E402

# ── Run-time settings ─────────────────────────────────────────────────────────
QUICK          = "--quick" in sys.argv
TARGETED       = "--targeted" in sys.argv   # run fast 25/50/100-swipe checks only
SWIPES         = 50  if QUICK else 150
CHECKPOINT_N   = 25           # measure every N swipes
FEED_LIMIT     = 20           # cards per checkpoint build
SEED           = 42

# Hard-failure thresholds (enforced after this many swipes)
FAIL_AFTER     = 75 if QUICK else 100
FAIL_DISLIKED  = 0.20   # disliked content must be < 20 %
FAIL_BAD_LANG  = 0.15   # disliked-language titles must be < 15 %
FAIL_BAD_DECADE= 0.25   # rejected-decade titles must be < 25 %

ACTION_WEIGHTS = {"save": 1.0, "watched": 1.5, "skip": -0.8}

# Delta values must stay in sync with routers/user.py
_LANG_DELTA   = 1.0    # per skip (was 0.7)
_DECADE_DELTA = 0.8    # per skip (was 0.5)
_TONE_DELTA   = 0.60   # per skip (was 0.45)
_THEME_DELTA  = 0.25   # per skip (was 0.18)

# Auto-blocklist thresholds (must match routers/user.py)
_LANG_BLOCK_THRESHOLD   = -8.0
_DECADE_BLOCK_THRESHOLD = -6.0

# ── Persona definitions ───────────────────────────────────────────────────────
PERSONAS = [
    {
        "id": "horror_fan",
        "name": "Modern Horror Fan",
        "description": "Loves modern English horror/thrillers. Hates international films, old movies, light content.",
        "onboard_genres": ["Horror"],
        "subscriptions": ["Netflix", "Amazon Prime"],
        "liked": {
            "genres":    ["Horror", "Thriller"],
            "tones":     {"dark"},
            "languages": {"en"},
            "year_min":  2015,
            "themes":    {"psychological", "survival", "dread"},
        },
        "disliked": {
            "genres":    ["Comedy", "Family", "Animation", "Music", "Romance"],
            "languages": {"ja", "ko", "fr", "zh", "es", "de", "it"},
            "year_max":  2000,   # skip anything older than 2000
            "themes":    {"feel-good", "found-family"},
        },
        "thresholds": {"liked_genre_pct": 0.45, "explorer": False},
    },
    {
        "id": "doc_binger",
        "name": "Documentary Binger",
        "description": "True crime / biography docs only. Rejects music docs, reality TV, old content.",
        "onboard_genres": ["Documentary"],
        "subscriptions": ["Netflix", "Disney+"],
        "liked": {
            "genres":    ["Documentary"],
            "tones":     {"dark", "neutral"},
            "languages": {"en"},
            "year_min":  2005,
            "themes":    {"true-crime", "biographical", "survival", "war-drama"},
        },
        "disliked": {
            "genres":    ["Reality", "Talk", "Music", "Animation", "Comedy"],
            "languages": {"ja", "ko"},
            "year_max":  1995,
            "themes":    {"feel-good", "romance"},
        },
        "thresholds": {"liked_genre_pct": 0.45, "explorer": False},
    },
    {
        "id": "mainstream",
        "name": "Casual Mainstream User",
        "description": "Popular English action/comedy. Rejects niche docs, slow arthouse, subtitles.",
        "onboard_genres": ["Action", "Comedy"],
        "subscriptions": ["Netflix", "Amazon Prime"],
        "liked": {
            "genres":    ["Action", "Comedy", "Adventure"],
            "tones":     {"light", "neutral"},
            "languages": {"en"},
            "year_min":  2010,
            "themes":    {"feel-good", "heist", "survival"},
        },
        "disliked": {
            "genres":    ["Documentary", "War", "History", "Biography"],
            "languages": {"ja", "ko", "fr", "es", "de", "zh"},
            "year_max":  2005,
            "themes":    {"war-drama", "psychological", "dread"},
        },
        "thresholds": {"liked_genre_pct": 0.45, "explorer": False},
    },
    {
        "id": "classic_fan",
        "name": "Classic Film Lover",
        "description": "70s/80s/90s crime, war, westerns. Rejects modern family/animation content.",
        "onboard_genres": ["Crime", "War"],
        "subscriptions": ["Amazon Prime", "Disney+"],
        "liked": {
            "genres":    ["Crime", "War", "Western", "Drama", "History"],
            "tones":     {"dark", "neutral"},
            "languages": {"en"},
            "year_max":  1999,   # saves classics
            "themes":    {"war-drama", "moral-grey", "redemption"},
        },
        "disliked": {
            "genres":    ["Animation", "Family", "Kids", "Reality", "Talk"],
            "languages": {"ja", "ko"},
            "year_min":  2015,   # skips very recent content
            "themes":    {"feel-good", "found-family"},
        },
        "thresholds": {"liked_genre_pct": 0.35, "explorer": False},
    },
    {
        "id": "explorer",
        "name": "Variety Explorer",
        "description": "Saves adjacent/wildcard content. Accepts international films. Exploration weight should rise.",
        "onboard_genres": ["Drama", "Sci-Fi"],
        "subscriptions": ["Netflix", "Amazon Prime"],
        "liked": {
            "genres":    ["Drama", "Sci-Fi", "Mystery", "Thriller", "Crime", "History", "Action"],
            "tones":     {"dark", "neutral", "light"},
            "languages": {"en", "ja", "ko", "fr", "es", "de"},
            "year_min":  1970,
            "themes":    {"psychological", "mind-bending", "dystopian", "espionage", "moral-grey"},
        },
        "disliked": {   # Explorer barely dislikes anything
            "genres":    [],
            "languages": set(),
            "themes":    set(),
        },
        "thresholds": {"liked_genre_pct": 0.30, "explorer": True},
    },
]


# ── Catalog helpers ───────────────────────────────────────────────────────────

def _pick_pool(catalog, liked: dict, disliked: dict, kind: str, n: int, rng: random.Random) -> list:
    """Select up to n movies from catalog that best match liked/disliked patterns."""
    d = liked if kind == "liked" else disliked
    genres      = set(d.get("genres") or [])
    languages   = set(d.get("languages") or set())
    year_min    = d.get("year_min")
    year_max    = d.get("year_max")
    themes      = set(d.get("themes") or set())
    tones       = set(d.get("tones") or set())

    candidates = []
    for m in catalog:
        mg   = set(m.get("genres") or [])
        lang = m.get("original_language") or "en"
        year = m.get("year") or 0
        card = m.get("card") or {}
        tone = card.get("tone", "neutral")
        mthemes = set(card.get("themes") or [])

        score = 0
        if genres   and mg & genres:       score += 3
        if languages and lang in languages: score += 2
        if tones    and tone in tones:     score += 1
        if themes   and mthemes & themes:  score += 1
        if year_min and year and year >= year_min: score += 1
        if year_max and year and year <= year_max: score += 1
        # Year filter for disliked_year_min (classic_fan)
        if kind == "disliked" and d.get("year_min") and year and year >= d["year_min"]: score += 2

        min_score = 3 if kind == "liked" else 2
        if score >= min_score:
            candidates.append((score, m))

    candidates.sort(key=lambda x: x[0], reverse=True)
    pool = [m for _, m in candidates[:n * 4]]
    rng.shuffle(pool)
    return pool[:n]


# ── Swipe simulation ──────────────────────────────────────────────────────────

async def _simulate_swipe(uid: str, movie: dict, action: str):
    """Mirror the weight-update logic from routers/user.py."""
    delta = ACTION_WEIGHTS.get(action, 0)
    if delta == 0:
        return

    genres      = movie.get("genres") or []
    genre_count = max(1, len(genres))
    dpg         = round(delta / genre_count, 4)

    inc = {f"genre_weights.{g}": dpg for g in genres}
    inc[f"type_weights.{movie.get('type', 'movie')}"] = round(delta * 0.6, 4)

    card   = movie.get("card") or {}
    tone   = card.get("tone")
    pacing = card.get("pacing")
    if tone and tone != "neutral":
        inc[f"tone_weights.{tone}"] = round(delta * _TONE_DELTA, 4)
    if pacing and pacing != "medium":
        inc[f"pacing_weights.{pacing}"] = round(delta * 0.30, 4)
    for t in (card.get("verified_themes") or card.get("themes") or [])[:3]:
        inc[f"theme_weights.{t}"] = round(delta * _THEME_DELTA, 4)

    lang = movie.get("original_language")
    if lang:
        inc[f"language_weights.{lang}"] = round(delta * _LANG_DELTA, 4)
    year = movie.get("year")
    if year:
        inc[f"decade_weights.{(year // 10) * 10}s"] = round(delta * _DECADE_DELTA, 4)

    fld = {"save": "saved", "skip": "skipped", "watched": "watched"}.get(action)
    upd: dict = {"$inc": inc}
    if fld:
        upd["$addToSet"] = {fld: movie["id"]}
        upd["$set"] = {"last_action_at": datetime.now(timezone.utc).isoformat()}

    await db.users.update_one({"user_id": uid}, upd)
    await db.user_actions.insert_one({
        "user_id": uid, "movie_id": movie["id"],
        "action": action, "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Auto-blocklist: mirrors routers/user.py threshold logic
    if lang or year:
        _fresh = await db.users.find_one(
            {"user_id": uid},
            {"language_weights": 1, "decade_weights": 1, "auto_blocked_languages": 1,
             "auto_blocked_decades": 1, "_id": 0}
        ) or {}
        _aa: dict = {}
        if lang:
            _lw = (_fresh.get("language_weights") or {}).get(lang, 0)
            _bl = set(_fresh.get("auto_blocked_languages") or [])
            if _lw < _LANG_BLOCK_THRESHOLD and lang not in _bl:
                _aa["auto_blocked_languages"] = lang
        if year:
            _dec = f"{(year // 10) * 10}s"
            _dw = (_fresh.get("decade_weights") or {}).get(_dec, 0)
            _bd = set(_fresh.get("auto_blocked_decades") or [])
            if _dw < _DECADE_BLOCK_THRESHOLD and _dec not in _bd:
                _aa["auto_blocked_decades"] = _dec
        if _aa:
            await db.users.update_one({"user_id": uid}, {"$addToSet": _aa})


# ── Metrics ───────────────────────────────────────────────────────────────────

def _measure(feed: list, persona: dict) -> dict:
    """Return alignment metrics for one feed snapshot."""
    liked    = persona["liked"]
    disliked = persona["disliked"]

    lg     = set(liked.get("genres") or [])
    ll     = set(liked.get("languages") or set())
    ly_min = liked.get("year_min") or 0
    ly_max = liked.get("year_max")

    dg     = set(disliked.get("genres") or [])
    dl     = set(disliked.get("languages") or set())
    dy_max = disliked.get("year_max")   # year < dy_max → disliked
    dy_min = disliked.get("year_min")   # year >= dy_min → disliked
    dthm   = set(disliked.get("themes") or set())

    n = len(feed)
    if n == 0:
        return {"n": 0, "error": "empty_feed"}

    liked_genre = disliked_hit = bad_lang = liked_lang = liked_decade = 0
    lang_ctr: Counter = Counter()
    genre_ctr: Counter = Counter()
    decade_ctr: Counter = Counter()
    uid_set: set = set()

    for m in feed:
        uid_set.add(m.get("id"))
        mg     = set(m.get("genres") or [])
        lang   = m.get("original_language") or "en"
        year   = m.get("year") or 0
        decade = f"{(year // 10) * 10}s" if year else "unknown"
        card   = m.get("card") or {}
        mthm   = set(card.get("themes") or [])

        lang_ctr[lang] += 1
        decade_ctr[decade] += 1
        for g in mg:
            genre_ctr[g] += 1

        if lg and mg & lg:
            liked_genre += 1
        if ll and lang in ll:
            liked_lang += 1
        if dl and lang in dl:
            bad_lang += 1

        # Liked-decade alignment
        ok_decade = True
        if ly_min and year and year < ly_min:
            ok_decade = False
        if ly_max and year and year > ly_max:
            ok_decade = False
        if ok_decade:
            liked_decade += 1

        # Disliked hit (any disliked signal)
        is_bad = False
        if dg and mg & dg:           is_bad = True
        if dl and lang in dl:        is_bad = True
        if dy_max and year and year < dy_max: is_bad = True
        if dy_min and year and year >= dy_min: is_bad = True
        if dthm and mthm & dthm:     is_bad = True
        if is_bad:
            disliked_hit += 1

    return {
        "n":              n,
        "unique":         len(uid_set),
        "liked_genre_pct":  round(liked_genre  / n, 3),
        "disliked_pct":     round(disliked_hit / n, 3),
        "bad_lang_pct":     round(bad_lang     / n, 3),
        "liked_lang_pct":   round(liked_lang   / n, 3) if ll else None,
        "liked_decade_pct": round(liked_decade / n, 3),
        "top_genres":   genre_ctr.most_common(5),
        "top_langs":    lang_ctr.most_common(5),
        "top_decades":  decade_ctr.most_common(4),
        "titles":       [m.get("title", "?") for m in feed[:5]],
    }


def _detect_failures(checkpoints: list, persona: dict) -> list:
    fails = []
    for cp in checkpoints:
        if cp["swipes"] < FAIL_AFTER:
            continue
        m = cp["metrics"]
        s = cp["swipes"]
        if m.get("disliked_pct", 0) > FAIL_DISLIKED:
            fails.append(f"@{s:>3} swipes — disliked content {m['disliked_pct']:.0%} > {FAIL_DISLIKED:.0%} threshold")
        if m.get("bad_lang_pct", 0) > FAIL_BAD_LANG:
            fails.append(f"@{s:>3} swipes — bad-language exposure {m['bad_lang_pct']:.0%} > {FAIL_BAD_LANG:.0%} threshold")
        if m.get("n", FEED_LIMIT) < FEED_LIMIT // 2:
            fails.append(f"@{s:>3} swipes — feed collapsed: only {m['n']} cards returned")
        liked_pct = persona["thresholds"].get("liked_genre_pct", 0)
        if liked_pct and m.get("liked_genre_pct", 1) < liked_pct * 0.5:
            fails.append(f"@{s:>3} swipes — liked genre {m['liked_genre_pct']:.0%} far below expected {liked_pct:.0%}")
    return fails


def _score_persona(checkpoints: list, persona: dict, failures: list) -> int:
    """Return a 0–20 score for this persona."""
    pts = 20
    pts -= min(15, len(failures) * 4)

    if len(checkpoints) >= 3:
        early = checkpoints[1]["metrics"]
        late  = checkpoints[-1]["metrics"]
        # Improvement in liked genre %
        delta_liked = late["liked_genre_pct"] - early["liked_genre_pct"]
        if delta_liked < -0.10:
            pts -= 2   # regressed significantly
        # Reduction in disliked content %
        delta_bad = late["disliked_pct"] - early["disliked_pct"]
        if delta_bad > 0.05:
            pts -= 2   # disliked content grew
        # Explorer: exploration_weight should rise
        if persona["thresholds"].get("explorer"):
            ew_start = checkpoints[0].get("exploration_weight", 0.5)
            ew_end   = checkpoints[-1].get("exploration_weight", 0.5)
            if ew_end < ew_start:
                pts -= 2

    return max(0, pts)


# ── Persona runner ────────────────────────────────────────────────────────────

async def run_persona(persona: dict, catalog: list) -> dict:
    uid = f"stress_{persona['id']}_{uuid.uuid4().hex[:8]}"
    rng = random.Random(SEED)

    print(f"\n  Creating user {uid}")
    await db.users.insert_one({
        "user_id": uid,
        "email": f"{uid}@stress.test",
        "name": persona["name"],
        "genres": persona["onboard_genres"],
        "subscriptions": persona.get("subscriptions", []),
        "excluded_categories": [],
        "excluded_genres": [],
        "content_type": "both",
        "country": "GB",
        "genre_weights": {}, "tone_weights": {}, "pacing_weights": {},
        "theme_weights": {}, "language_weights": {}, "decade_weights": {},
        "type_weights": {},
        "saved": [], "watched": [], "skipped": [],
        "onboarding_rated": [], "recently_shown": [],
        "exploration_weight": 0.5,
        "role": "user",
    })

    liked_pool    = _pick_pool(catalog, persona["liked"], persona["disliked"], "liked",    300, rng)
    disliked_pool = _pick_pool(catalog, persona["liked"], persona["disliked"], "disliked", 200, rng)

    print(f"  Liked pool: {len(liked_pool)} | Disliked pool: {len(disliked_pool)}")

    # Build swipe sequence: 15 saves + 10 skips per 25-swipe batch, shuffled
    seq: list = []
    li = di = 0
    for _ in range(SWIPES // CHECKPOINT_N):
        batch = []
        for _ in range(15):
            if li < len(liked_pool):
                batch.append(("save", liked_pool[li])); li += 1
        for _ in range(10):
            if di < len(disliked_pool):
                batch.append(("skip", disliked_pool[di])); di += 1
        rng.shuffle(batch)
        seq.extend(batch)

    checkpoints = []

    async def _snapshot(swipes: int):
        fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
        feed  = await build_feed(fresh, limit=FEED_LIMIT, include_other_services=True)
        await asyncio.sleep(0.05)   # let recently_shown task complete
        checkpoints.append({
            "swipes":           swipes,
            "feed":             feed,
            "metrics":          _measure(feed, persona),
            "exploration_weight": fresh.get("exploration_weight", 0.5),
            "lang_weights":     {k: round(v, 1) for k, v in (fresh.get("language_weights") or {}).items()},
            "decade_weights":   {k: round(v, 1) for k, v in (fresh.get("decade_weights") or {}).items()},
            "genre_weights_top": sorted(
                ((k, round(v, 1)) for k, v in (fresh.get("genre_weights") or {}).items()),
                key=lambda x: x[1], reverse=True
            )[:8],
        })

    # Checkpoint 0 — before any swipes
    await _snapshot(0)

    for i, (action, movie) in enumerate(seq):
        await _simulate_swipe(uid, movie, action)
        n = i + 1
        if n % CHECKPOINT_N == 0:
            print(f"    swipes={n:>3} ...", end=" ", flush=True)
            await _snapshot(n)
            cp = checkpoints[-1]["metrics"]
            print(f"liked={cp['liked_genre_pct']:.0%} disliked={cp['disliked_pct']:.0%} bad_lang={cp['bad_lang_pct']:.0%}")

    failures = _detect_failures(checkpoints, persona)
    score    = _score_persona(checkpoints, persona, failures)

    # Cleanup
    await db.users.delete_one({"user_id": uid})
    await db.user_actions.delete_many({"user_id": uid})

    return {"persona": persona, "checkpoints": checkpoints, "failures": failures, "score": score}


# ── Reporting ─────────────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 20) -> str:
    filled = round(pct * width)
    return "█" * filled + "░" * (width - filled)


def _print_persona_report(result: dict):
    p   = result["persona"]
    cps = result["checkpoints"]
    fls = result["failures"]
    sc  = result["score"]

    print(f"\n{'═'*68}")
    print(f"  {p['name']}  —  {sc}/20 pts")
    print(f"  {p['description']}")
    print(f"{'─'*68}")

    # Progress table
    print(f"  {'Swipes':>6}  {'Liked':>6}  {'Disliked':>8}  {'Bad lang':>8}  {'Decade ok':>9}  {'Unique':>6}")
    print(f"  {'------':>6}  {'-----':>6}  {'--------':>8}  {'--------':>8}  {'---------':>9}  {'------':>6}")
    for cp in cps:
        m  = cp["metrics"]
        ew = cp.get("exploration_weight", 0.5)
        print(f"  {cp['swipes']:>6}  {m['liked_genre_pct']:>5.0%}  {m['disliked_pct']:>8.0%}  "
              f"{m['bad_lang_pct']:>8.0%}  {m['liked_decade_pct']:>9.0%}  {m['unique']:>6}")

    # Feed composition charts
    if len(cps) >= 2:
        first, last = cps[0], cps[-1]
        print(f"\n  Feed composition — first vs final {FEED_LIMIT} cards:")
        print(f"  Liked genre %:  {_bar(first['metrics']['liked_genre_pct'])} {first['metrics']['liked_genre_pct']:.0%}"
              f"  →  {_bar(last['metrics']['liked_genre_pct'])} {last['metrics']['liked_genre_pct']:.0%}")
        print(f"  Disliked %:     {_bar(first['metrics']['disliked_pct'])} {first['metrics']['disliked_pct']:.0%}"
              f"  →  {_bar(last['metrics']['disliked_pct'])} {last['metrics']['disliked_pct']:.0%}")

    # First/final titles
    if cps:
        first_titles = cps[0]["metrics"].get("titles", [])
        final_titles = cps[-1]["metrics"].get("titles", [])
        if first_titles:
            print(f"\n  First feed (top 5): {', '.join(first_titles)}")
        if final_titles:
            print(f"  Final feed (top 5): {', '.join(final_titles)}")

    # Learned weights summary
    last_cp = cps[-1] if cps else {}
    gw_top = last_cp.get("genre_weights_top") or []
    if gw_top:
        liked_gw   = [(g, w) for g, w in gw_top if w > 0]
        disliked_gw = [(g, w) for g, w in reversed(gw_top) if w < 0]
        parts = []
        if liked_gw:
            parts.append("Liked: " + ", ".join(f"{g}({w:+.1f})" for g, w in liked_gw[:4]))
        if disliked_gw:
            parts.append("Disliked: " + ", ".join(f"{g}({w:+.1f})" for g, w in disliked_gw[:4]))
        if parts:
            print(f"\n  Genre weights: {' | '.join(parts)}")

    lw = last_cp.get("lang_weights") or {}
    if lw:
        lw_sorted = sorted(lw.items(), key=lambda x: x[1])
        neg_langs = [(k, v) for k, v in lw_sorted if v < 0]
        pos_langs = [(k, v) for k, v in reversed(lw_sorted) if v > 0]
        parts = []
        if pos_langs:
            parts.append("Liked: " + ", ".join(f"{k}({v:+.1f})" for k, v in pos_langs[:3]))
        if neg_langs:
            parts.append("Disliked: " + ", ".join(f"{k}({v:+.1f})" for k, v in neg_langs[:4]))
        if parts:
            print(f"  Language weights: {' | '.join(parts)}")

    dw = last_cp.get("decade_weights") or {}
    if dw:
        dw_sorted = sorted(dw.items(), key=lambda x: x[1])
        neg_dec = [(k, v) for k, v in dw_sorted if v < 0]
        pos_dec = [(k, v) for k, v in reversed(dw_sorted) if v > 0]
        parts = []
        if pos_dec:
            parts.append("Liked: " + ", ".join(f"{k}({v:+.1f})" for k, v in pos_dec[:3]))
        if neg_dec:
            parts.append("Disliked: " + ", ".join(f"{k}({v:+.1f})" for k, v in neg_dec[:3]))
        if parts:
            print(f"  Decade weights:   {' | '.join(parts)}")

    # Exploration weight for explorer persona
    if p["thresholds"].get("explorer") and len(cps) >= 2:
        ew_start = cps[0].get("exploration_weight", 0.5)
        ew_end   = cps[-1].get("exploration_weight", 0.5)
        arrow = "↑" if ew_end > ew_start else ("↓" if ew_end < ew_start else "→")
        print(f"\n  Exploration weight: {ew_start:.3f} → {ew_end:.3f} {arrow}")

    # Failures
    if fls:
        print(f"\n  ⚠  FAILURES ({len(fls)}):")
        for f in fls:
            print(f"      FAIL: {f}")
    else:
        print(f"\n  ✓  No failures detected.")

    print(f"  Score: {sc}/20")


def _print_final_summary(results: list, total: int):
    print(f"\n\n{'═'*68}")
    print(f"  FINAL ENGINE SCORE")
    print(f"{'─'*68}")
    for r in results:
        bar  = _bar(r["score"] / 20)
        flag = "✓" if not r["failures"] else "✗"
        print(f"  {flag} {r['persona']['name']:<28} {bar} {r['score']:>2}/20")

    print(f"{'─'*68}")
    pct = round(total / (len(results) * 20) * 100)
    print(f"  TOTAL:                           {total:>3}/{len(results)*20}  ({pct}%)")
    print(f"{'═'*68}\n")

    # Tuning recommendations
    all_failures = [f for r in results for f in r["failures"]]
    if not all_failures:
        print("  Engine recommendation: No tuning needed — all personas passed.\n")
        return
    print("  Tuning recommendations:")
    if any("disliked content" in f for f in all_failures):
        print("  → Increase negative signal strength: reduce tanh denominator in learned genre score.")
    if any("bad-language" in f for f in all_failures):
        print("  → Increase language_weight delta (currently 1.0×) or lower auto-block threshold (-8.0).")
    if any("collapsed" in f for f in all_failures):
        print("  → Review subscription filter + pool-thin bypass logic.")
    print()


# ── Targeted fast-adaptation tests ────────────────────────────────────────────

async def run_targeted_tests(catalog: list):
    """Run 25 / 50 / 100-swipe adaptation checks on the Modern Horror Fan persona.

    Goal: prove the engine feels adaptive EARLY.
    Each check uses an independent fresh user, so there is no cross-contamination.
    """
    persona = PERSONAS[0]   # Modern Horror Fan — clearest pass/fail criteria
    # Pass/fail uses liked_genre_pct and bad_lang_pct only.
    # disliked_pct is shown as informational: it conflates year + genre + lang
    # signals so pre-2000 horror classics (Silence of the Lambs, The Shining)
    # trigger it even when the engine is correctly serving the persona.
    TARGETS = [
        {
            "swipes":       25,
            "liked_min":    0.55,   # ≥55% liked genre after 25 swipes
            "bad_lang_max": 0.22,   # ≤22% disliked language (early, few skips)
        },
        {
            "swipes":       50,
            "liked_min":    0.65,
            "bad_lang_max": 0.12,   # ≤12% after 20+ language skips
        },
        {
            # 40 skips spread across 6 disliked languages → ~6-7 skips each
            # weight ≈ -5.9 (strong soft-block); hard auto-block needs 8 skips.
            "swipes":       100,
            "liked_min":    0.75,
            "bad_lang_max": 0.12,
        },
    ]

    rng     = random.Random(SEED + 99)
    lp      = _pick_pool(catalog, persona["liked"], persona["disliked"], "liked",    300, rng)
    dp      = _pick_pool(catalog, persona["liked"], persona["disliked"], "disliked", 200, rng)

    print(f"\n{'═'*68}")
    print(f"  TARGETED FAST-ADAPTATION TESTS  (persona: {persona['name']})")
    print(f"{'─'*68}")
    print(f"  {'Target':>7}  {'Liked%':>7}  {'Bad lang%':>9}  {'Disliked%':>9}  {'Result':>7}")
    print(f"  {'-------':>7}  {'------':>7}  {'---------':>9}  {'---------':>9}  {'------':>7}")

    all_pass = True
    for t in TARGETS:
        n_swipes = t["swipes"]
        uid = f"targeted_{persona['id']}_{n_swipes}sw_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "user_id": uid, "email": f"{uid}@stress.test",
            "name": f"targeted_{n_swipes}",
            "genres": persona["onboard_genres"],
            "subscriptions": persona.get("subscriptions", []),
            "excluded_categories": [], "excluded_genres": [],
            "content_type": "both", "country": "GB",
            "genre_weights": {}, "tone_weights": {}, "pacing_weights": {},
            "theme_weights": {}, "language_weights": {}, "decade_weights": {},
            "type_weights": {}, "auto_blocked_languages": [], "auto_blocked_decades": [],
            "saved": [], "watched": [], "skipped": [],
            "onboarding_rated": [], "recently_shown": [],
            "exploration_weight": 0.5, "role": "user",
        })

        # Build swipe sequence proportional to target count (15 saves + 10 skips per 25)
        li = di = 0
        for batch_i in range(n_swipes // 25):
            batch = []
            for _ in range(15):
                if li < len(lp): batch.append(("save", lp[li])); li += 1
            for _ in range(10):
                if di < len(dp): batch.append(("skip", dp[di])); di += 1
            rng.shuffle(batch)
            for action, movie in batch:
                await _simulate_swipe(uid, movie, action)

        # Clear recently_shown before measurement so the engine isn't forced
        # into fallback pools by an exhausted recently-seen list.
        await db.users.update_one({"user_id": uid}, {"$set": {"recently_shown": []}})
        fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
        feed  = await build_feed(fresh, limit=FEED_LIMIT, include_other_services=True)
        await asyncio.sleep(0.05)
        m = _measure(feed, persona)

        # Only liked_genre and bad_lang are hard gates.
        # disliked_pct is informational (year filter conflates old classics with bad content).
        passed = (
            m["liked_genre_pct"] >= t["liked_min"]   and
            m["bad_lang_pct"]    <= t["bad_lang_max"]
        )
        flag = "PASS ✓" if passed else "FAIL ✗"
        if not passed: all_pass = False

        print(f"  {n_swipes:>6}sw  {m['liked_genre_pct']:>6.0%}  {m['bad_lang_pct']:>9.0%}  "
              f"{m['disliked_pct']:>9.0%}(i)  {flag}")
        if not passed:
            if m["liked_genre_pct"] < t["liked_min"]:
                print(f"           ↳ liked genre {m['liked_genre_pct']:.0%} below target {t['liked_min']:.0%}")
            if m["bad_lang_pct"] > t["bad_lang_max"]:
                print(f"           ↳ bad lang {m['bad_lang_pct']:.0%} above target {t['bad_lang_max']:.0%}")

        auto_langs = fresh.get("auto_blocked_languages") or []
        if auto_langs:
            print(f"           ↳ auto-blocked langs: {auto_langs}")

        await db.users.delete_one({"user_id": uid})
        await db.user_actions.delete_many({"user_id": uid})

    verdict = "ALL PASSED ✓" if all_pass else "SOME FAILED ✗"
    print(f"\n  Targeted result: {verdict}")
    print(f"{'═'*68}")
    return all_pass


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    if TARGETED:
        print(f"\n{'═'*68}")
        print(f"  WatchSmart Fast-Adaptation Test  [--targeted]")
        print(f"{'═'*68}")
        print("\nLoading catalog from DB...")
        await load_catalog_from_db()
        catalog = get_catalog()
        print(f"Catalog loaded: {len(catalog)} titles")
        ok = await run_targeted_tests(catalog)
        sys.exit(0 if ok else 1)

    mode = "QUICK (50 swipes)" if QUICK else "FULL (150 swipes)"
    print(f"\n{'═'*68}")
    print(f"  WatchSmart Personalization Stress-Test Suite  [{mode}]")
    print(f"  {len(PERSONAS)} personas · checkpoint every {CHECKPOINT_N} swipes · {FEED_LIMIT} cards/checkpoint")
    print(f"  Hard-fail thresholds: disliked>{FAIL_DISLIKED:.0%} | bad-lang>{FAIL_BAD_LANG:.0%} (after {FAIL_AFTER} swipes)")
    print(f"{'═'*68}")

    print("\nLoading catalog from DB...")
    await load_catalog_from_db()
    catalog = get_catalog()
    print(f"Catalog loaded: {len(catalog)} titles\n")

    results    = []
    total_pts  = 0

    for persona in PERSONAS:
        print(f"\n{'─'*68}")
        print(f"  Running persona: {persona['name']}")
        print(f"{'─'*68}")
        result = await run_persona(persona, catalog)
        results.append(result)
        total_pts += result["score"]
        _print_persona_report(result)

    _print_final_summary(results, total_pts)

    # Also run targeted fast-adaptation checks at the end
    print("\nRunning targeted fast-adaptation checks...")
    await run_targeted_tests(catalog)

    # Exit code: non-zero if any hard failures exist
    any_fail = any(r["failures"] for r in results)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
