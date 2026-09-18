"""Persona simulation harness for the recommendation engine.

Runs N personas through M swipes each, replicating the production learning
pipeline (routers/user.py:user_action) IN-MEMORY so no DB writes happen.  It
disables background refill + recently-shown DB persistence and instead drives
the recently_shown LRU directly on the in-memory user dict, exactly as the
real /discover → /user/action loop would over a session.

Usage:  python sim_personas.py
"""
import asyncio
import os
from datetime import datetime, timezone

import core
import engine
import global_learning
from engine import ADJACENT_GENRES
from core import ACTION_WEIGHTS
from taste import taste_learning_inc, build_taste_profile

# ── Neutralise side-effecting background work for the sim ──────────────────────
engine._schedule_refill = lambda *a, **k: None          # no TMDB top-ups
engine._schedule_record_shown = lambda *a, **k: None     # no DB writes
engine._schedule_log_impressions = lambda *a, **k: "simulation"
engine._schedule_taste_backfill = lambda *a, **k: None


async def _empty_set(*_args, **_kwargs):
    return set()


async def _empty_map(*_args, **_kwargs):
    return {}


# Persona comparisons should isolate the engine and must not query/write
# production user-history tables.
engine._collaborative_boost_set = _empty_set
engine._eligible_skip_reintros = _empty_set
global_learning.compute_new_user_boost = _empty_map
global_learning.get_community_quality_scores = _empty_map
global_learning.get_discovery_scores = _empty_map
global_learning.get_self_cleaning_flags = _empty_set

SWIPES = 100
LIMIT = 60
NOW = datetime.now(timezone.utc).isoformat()


# ── In-memory replica of routers/user.py learning ─────────────────────────────
def apply_action(user: dict, movie: dict, action: str) -> str:
    """Mutate `user` weights exactly like user_action() would for save/skip/watched.
    Returns the effective action."""
    saved   = user.setdefault("saved", [])
    skipped = user.setdefault("skipped", [])
    watched = user.setdefault("watched", [])
    mid = movie["id"]

    if action == "watched":
        if mid in saved:
            effective = "watched_liked"
        elif mid in skipped:
            effective = "watched_disliked"
        else:
            effective = "watched"
    else:
        effective = action

    # move id into the right list (mimic $addToSet + $pull of the others)
    for lst in (saved, skipped, watched):
        if mid in lst:
            lst.remove(mid)
    {"save": saved, "skip": skipped, "watched": watched}[action].append(mid)

    delta = ACTION_WEIGHTS.get(effective, 0)
    if delta:
        genres = movie.get("genres") or []
        gc = max(1, len(genres))
        dpg = round(delta / gc, 4)
        gw = user.setdefault("genre_weights", {})
        for g in genres:
            gw[g] = gw.get(g, 0) + dpg
        tw = user.setdefault("type_weights", {})
        t = movie.get("type", "movie")
        tw[t] = tw.get(t, 0) + round(delta * 0.6, 4)

        card = movie.get("card") or {}
        tone = card.get("tone")
        if tone and tone != "neutral":
            tnw = user.setdefault("tone_weights", {})
            tnw[tone] = tnw.get(tone, 0) + round(delta * 0.45, 4)
        pacing = card.get("pacing")
        if pacing and pacing != "medium":
            pw = user.setdefault("pacing_weights", {})
            pw[pacing] = pw.get(pacing, 0) + round(delta * 0.30, 4)
        thw = user.setdefault("theme_weights", {})
        for theme in (card.get("verified_themes") or card.get("themes") or [])[:3]:
            thw[theme] = thw.get(theme, 0) + round(delta * 0.25, 4)

        lang = movie.get("original_language")
        if lang:
            lw = user.setdefault("language_weights", {})
            lw[lang] = lw.get(lang, 0) + round(delta * 1.0, 4)
        year = movie.get("year")
        if year:
            dec = f"{(year // 10) * 10}s"
            dw = user.setdefault("decade_weights", {})
            dw[dec] = dw.get(dec, 0) + round(delta * 0.8, 4)

        # Soft taste signals (Task #23 + #37) — mirror user_action's $inc in-memory so
        # cast/director/writer weights build and the taste_profile reflects them.
        for k, v in taste_learning_inc(movie, delta).items():
            field, key = k.split(".", 1)
            d = user.setdefault(field, {})
            d[key] = round(d.get(key, 0) + v, 4)

    # exploration weight drift
    onboard = set(user.get("genres") or [])
    if onboard and action in ("save", "watched", "skip"):
        mg = set(movie.get("genres") or [])
        adjacent: set = set()
        for g in onboard:
            adjacent |= set(ADJACENT_GENRES.get(g, []))
        adjacent -= onboard
        slot = "core" if mg & onboard else "adjacent" if mg & adjacent else "wildcard"
        if slot in ("adjacent", "wildcard"):
            if effective in ("save", "watched_liked"):
                step = 0.020
            elif effective in ("skip", "watched_disliked"):
                step = -0.008
            else:
                step = 0.0
            if step:
                cur = float(user.get("exploration_weight") or 0.5)
                user["exploration_weight"] = round(max(0.1, min(0.9, cur + step)), 4)
    return effective


def persona_decision(persona: dict, card: dict) -> str:
    """Decide save / skip / watched based on persona genre affinity.
    Deterministic-ish policy keyed off genre overlap + rating."""
    liked = set(persona["likes"])
    genres = set(card.get("genres") or [])
    rating = float(card.get("rating") or 0)
    overlap = bool(genres & liked)
    if overlap and rating >= 6.5:
        return "save"
    if overlap:
        return "watched" if rating >= 5.5 else "skip"
    # off-affinity: mostly skip, occasionally watch a very strong title
    if rating >= 8.0:
        return "watched"
    return "skip"


def theoretical_pool_ceiling(user: dict) -> int:
    """How many catalogue titles match all of this user's HARD filters,
    ignoring cooldown — the most the pool could ever be."""
    catalog = core.get_catalog()
    reality_ok = engine._reality_allowed(user)
    n = 0
    for m in catalog:
        if not reality_ok and engine._is_reality(m):
            continue
        if core.movie_matches(m, user):
            n += 1
    return n


PERSONAS = [
    {"name": "Horror purist",       "genres": ["Horror"],            "subscriptions": ["netflix"],                 "likes": ["Horror", "Thriller"]},
    {"name": "Cosy comedy",         "genres": ["Comedy"],            "subscriptions": ["netflix", "disney_plus"],  "likes": ["Comedy", "Romance"]},
    {"name": "Prestige drama",      "genres": ["Drama"],             "subscriptions": ["netflix", "prime_video"],  "likes": ["Drama", "History"]},
    {"name": "Sci-fi explorer",     "genres": ["Sci-Fi"],            "subscriptions": ["netflix", "disney_plus"],  "likes": ["Sci-Fi", "Adventure"]},
    {"name": "Doc lover",           "genres": ["Documentary"],       "subscriptions": ["netflix"],                 "likes": ["Documentary", "History"]},
    {"name": "Action junkie",       "genres": ["Action"],            "subscriptions": ["prime_video"],             "likes": ["Action", "Thriller"]},
    {"name": "Combo crime+drama",   "genres": ["Crime", "Drama"],    "subscriptions": ["netflix"],                 "likes": ["Crime", "Drama"]},
    {"name": "Family animation",    "genres": ["Animation", "Family"], "subscriptions": ["disney_plus"],           "likes": ["Animation", "Family"]},
    {"name": "Open-minded (no subs)", "genres": ["Thriller"],        "subscriptions": [],                          "likes": ["Thriller", "Mystery", "Drama"]},
    {"name": "Reality fan",         "genres": ["Reality"],           "subscriptions": ["netflix"],                 "likes": ["Reality"]},
]


async def run_persona(p: dict) -> dict:
    user = {
        "user_id": f"sim_{p['name'].replace(' ', '_')}",
        "genres": list(p["genres"]),
        "subscriptions": list(p["subscriptions"]),
        "country": "GB",
        "saved": [], "watched": [], "skipped": [], "onboarding_rated": [],
        "recently_shown": [],
        "exploration_weight": 0.5,
        "genre_weights": {}, "type_weights": {}, "tone_weights": {},
        "pacing_weights": {}, "theme_weights": {}, "language_weights": {},
        "decade_weights": {},
    }
    ceiling = theoretical_pool_ceiling(user)

    swipes = 0
    caught_up_after = None
    min_pool = None
    first30 = []
    reality_seen = 0
    lowvote_seen = 0
    low_conf_seen = 0
    total_seen = 0
    first_meta = None

    reality_persona = bool(set(p["genres"]) & engine.REALITY_GENRES)

    while swipes < SWIPES:
        feed = await engine.build_feed(user, limit=LIMIT)
        if not feed:
            caught_up_after = swipes
            break
        meta = feed[0].get("_signals", {}).get("feed_meta", {})
        if first_meta is None:
            first_meta = meta
        pool_now = meta.get("pool_after_broadening", meta.get("eligible_pool_size"))
        if pool_now is not None:
            min_pool = pool_now if min_pool is None else min(min_pool, pool_now)

        shown_ids = []
        for card in feed:
            if swipes >= SWIPES:
                break
            sig = card.get("_signals", {})
            if len(first30) < 30:
                first30.append({
                    "slot": sig.get("intent_slot"),
                    "is_wildcard": sig.get("is_wildcard"),
                    "genres": card.get("genres"),
                    "prov": sig.get("provider_confidence"),
                })
            total_seen += 1
            if engine._is_reality(card):
                reality_seen += 1
            if int(card.get("vote_count") or 0) < 30:
                lowvote_seen += 1
            if sig.get("provider_confidence") == "low":
                low_conf_seen += 1

            action = persona_decision(p, card)
            apply_action(user, card, action)
            shown_ids.append(card["id"])
            swipes += 1

        # update the in-memory recently_shown LRU (what _schedule_record_shown
        # would have persisted), newest first
        existing = user["recently_shown"]
        new_entries = [{"id": i, "at": NOW} for i in shown_ids]
        new_ids = {i for i in shown_ids}
        user["recently_shown"] = (
            new_entries + [e for e in existing if e.get("id") not in new_ids]
        )[:engine.RECENTLY_SHOWN_MAX]

    onboard = set(p["genres"])
    adj: set = set()
    for g in onboard:
        adj |= set(ADJACENT_GENRES.get(g, []))
    first30_wild = sum(1 for c in first30 if c["is_wildcard"])
    first30_relevant = sum(
        1 for c in first30
        if set(c["genres"] or []) & onboard or set(c["genres"] or []) & adj
    )

    # ── "After 100 swipes" snapshot — does the feed now feel personal, not
    # genre-trapped?  Build one more feed against the matured user and read the
    # variety floor / discovery band / diversity diagnostics from feed_meta.
    final_feed = await engine.build_feed(user, limit=LIMIT)
    final_meta = (final_feed[0].get("_signals", {}).get("feed_meta", {})
                  if final_feed else {})
    fc = final_meta.get("core_slots") or 0
    fa = final_meta.get("adjacent_slots") or 0
    fw = final_meta.get("wildcard_slots") or 0
    ftot = fc + fa + fw
    diversity = final_meta.get("diversity", {}) or {}
    adj_supply = final_meta.get("adjacent_pool_count") or 0
    wild_supply = final_meta.get("wildcard_pool_count") or 0

    # ── Persistent taste profile (Task #23 Step 3) ───────────────────────────
    # After onboarding + 100 swipes the consolidated profile must reflect what
    # we learned: top genres, accumulated cast affinity, and a quality pref.
    taste_profile = build_taste_profile(user)

    # ── Onboarding-genre persistence (Task #23 Step 11) ──────────────────────
    # After onboarding + 100 swipes the *matured* feed must still clearly surface
    # the genres the user onboarded with (e.g. Crime/Thriller/Mystery), proving
    # live learning never drifts away from the declared cold-start preferences.
    final_onboard_hits = sum(
        1 for c in final_feed if set(c.get("genres") or []) & onboard
    )
    final_feed_len = len(final_feed)
    final_onboard_frac = (
        round(final_onboard_hits / final_feed_len, 3) if final_feed_len else None
    )

    return {
        "name": p["name"],
        "subs": p["subscriptions"],
        "limit": LIMIT,
        "ceiling": ceiling,
        "swipes": swipes,
        "caught_up_after": caught_up_after,
        "min_pool": min_pool,
        "first_pool_before": (first_meta or {}).get("pool_before_filters"),
        "first_pool_after_filters": (first_meta or {}).get("pool_after_filters"),
        "first_pool_after_broadening": (first_meta or {}).get("pool_after_broadening"),
        "reality_suppressed": (first_meta or {}).get("reality_suppressed_count"),
        "low_vote_suppressed": (first_meta or {}).get("low_vote_suppressed_count"),
        "genre_match_mode": (first_meta or {}).get("genre_match_mode"),
        "prov_dist": (first_meta or {}).get("provider_confidence_distribution"),
        "reality_persona": reality_persona,
        "reality_seen": reality_seen,
        "lowvote_frac": round(lowvote_seen / max(1, total_seen), 3),
        "low_conf_seen": low_conf_seen,
        "first30_wild": first30_wild,
        "first30_relevant": first30_relevant,
        "total_seen": total_seen,
        # ── matured-feed diagnostics ──────────────────────────────────────────
        "final_tier": engine._confidence_tier(user),
        "final_ratios": final_meta.get("exploration_ratios", {}),
        "final_core_frac": round(fc / ftot, 3) if ftot else None,
        "final_adj_frac": round(fa / ftot, 3) if ftot else None,
        "final_wild_frac": round(fw / ftot, 3) if ftot else None,
        "adj_supply": adj_supply,
        "wild_supply": wild_supply,
        "dominant_genre_frac": diversity.get("dominant_genre_frac"),
        "distinct_genres": diversity.get("distinct_genres"),
        "distinct_themes": diversity.get("distinct_themes"),
        "distinct_tones": diversity.get("distinct_tones"),
        "repetition_score": diversity.get("repetition_score"),
        "max_feel_streak": diversity.get("max_same_feeling_streak"),
        "dominant_tone_frac": diversity.get("dominant_tone_frac"),
        "tail_streak": diversity.get("max_same_feeling_streak_after_head"),
        "tail_streak_floor": diversity.get("min_achievable_streak_after_head"),
        # ── persistent taste profile ──────────────────────────────────────────
        "tp_genres": taste_profile.get("genres"),
        "tp_cast": taste_profile.get("cast_affinity"),
        "tp_quality_pref": taste_profile.get("quality_pref"),
        "tp_updated_at": taste_profile.get("updated_at"),
        # ── onboarding-genre persistence ──────────────────────────────────────
        "onboard_genres": sorted(onboard),
        "final_feed_len": final_feed_len,
        "final_onboard_frac": final_onboard_frac,
    }


def evaluate(r: dict) -> list[str]:
    fails = []
    # 1. not caught-up before 40 swipes (where catalogue clearly allows)
    if r["caught_up_after"] is not None and r["caught_up_after"] < 40 and r["ceiling"] >= 100:
        fails.append(f"caught_up_after={r['caught_up_after']} (<40, ceiling={r['ceiling']})")
    # 2. pool floor: stays >=100 where catalogue allows
    if r["ceiling"] >= 100 and r["min_pool"] is not None and r["min_pool"] < 100:
        fails.append(f"min_pool={r['min_pool']} <100 (ceiling={r['ceiling']})")
    # 3. trust head: no wildcard in first 30
    if r["first30_wild"] > 0:
        fails.append(f"first30_wild={r['first30_wild']}")
    # 4. first-30 relevance (core+adjacent) high
    if r["first30_relevant"] < 24:  # >=80% of 30
        fails.append(f"first30_relevant={r['first30_relevant']}/30")
    # 5. reality suppressed for non-reality personas
    if not r["reality_persona"] and r["reality_seen"] > 0:
        fails.append(f"reality_seen={r['reality_seen']} (non-reality persona)")
    # 6. low-vote filler not dominant
    if r["lowvote_frac"] >= 0.2:
        fails.append(f"lowvote_frac={r['lowvote_frac']} (>=0.2)")
    # 7. no low-confidence provider in strict mode (subs set)
    if r["subs"] and r["low_conf_seen"] > 0:
        fails.append(f"low_conf_seen={r['low_conf_seen']} in strict mode")

    # ── "After 100 swipes" acceptance: understands me, not genre-trapped ──────
    # These only fire when the catalogue clearly has the variety supply to honour
    # them (thin/niche genres are exempt — they can't be diversified).
    variety_supply = (r["adj_supply"] or 0) + (r["wild_supply"] or 0)
    has_variety = variety_supply >= r["limit"] and r["ceiling"] >= 150

    # 8. variety floor: matured feed must not be >55% one core genre
    if has_variety and r["final_core_frac"] is not None and r["final_core_frac"] > 0.55:
        fails.append(f"final_core_frac={r['final_core_frac']} >0.55 (variety floor)")
    # 9. discovery band: keep healthy wildcard discovery once confident
    if (has_variety and (r["wild_supply"] or 0) >= r["limit"] * 0.2
            and r["final_wild_frac"] is not None and r["final_wild_frac"] < 0.12):
        fails.append(f"final_wild_frac={r['final_wild_frac']} <0.12 (discovery band)")
    # 10. anti-repetition: past the intent-led trust head, the breaker must space
    #     the dominant feeling as evenly as the non-dominant tone supply allows.
    #     We compare the achieved tail streak to the supply-aware achievable
    #     minimum (ceil(dominant / (separators + 1))) rather than a flat number,
    #     so genuinely mono-feeling feeds aren't falsely flagged while a real
    #     packing failure (achieved ≫ achievable) is caught.  Slack of +2 absorbs
    #     boundary effects from de-streaking head and tail separately.
    if has_variety and (r["distinct_tones"] or 0) >= 2:
        floor = r["tail_streak_floor"] or 1
        allowed = max(3, floor) + 2
        if (r["tail_streak"] or 0) > allowed:
            fails.append(
                f"tail_streak={r['tail_streak']} > allowed={allowed} "
                f"(achievable_floor={floor}; anti-repetition packing failure)"
            )

    # 11. persistent taste profile: after onboarding + 100 swipes the
    #     consolidated profile must reflect the learned signal — populated top
    #     genres, a derived quality preference, and a timestamp.  (cast_affinity
    #     is exercised too but only populates when the catalogue carries cast
    #     metadata, which the current corpus does not — so it stays informational
    #     rather than a hard gate.)
    if not r.get("tp_genres"):
        fails.append("taste_profile.genres empty after 100 swipes")
    if not r.get("tp_quality_pref"):
        fails.append("taste_profile.quality_pref missing after 100 swipes")
    if not r.get("tp_updated_at"):
        fails.append("taste_profile.updated_at missing")

    # 12. onboarding-genre persistence (Step 11): a long swipe session must never
    #     drift the user's learned preferences away from the genres they
    #     onboarded with.  The authoritative, supply-independent check is that
    #     every onboarding genre still ranks within the learned top genres after
    #     100 swipes (e.g. Crime/Thriller/Mystery stay represented).
    onboard_genres = r.get("onboard_genres") or []
    tp = set(r.get("tp_genres") or [])
    dropped = [g for g in onboard_genres if g not in tp]
    if onboard_genres and dropped:
        fails.append(
            f"onboarding genres {dropped} dropped out of learned top genres "
            f"{sorted(tp)} after 100 swipes (preference drift)"
        )
    # Secondary: where the matured feed still carries fresh top-preference (core)
    # supply, those onboarding genres must also remain visible in the served
    # feed.  Mono-niche genres whose fresh supply is exhausted (core_frac == 0)
    # are exempt — that reflects catalogue depth, not preference drift.
    if (r.get("final_feed_len") and r.get("final_core_frac")
            and r.get("final_onboard_frac") is not None
            and r["final_onboard_frac"] < 0.30):
        fails.append(
            f"final_onboard_frac={r['final_onboard_frac']} <0.30 with core supply "
            f"present (onboarding genres {onboard_genres} faded after 100 swipes)"
        )
    return fails


async def main():
    # Read-only counterpart to load_catalog_from_db.  The production loader may
    # persist newly generated card fields, which a simulation must never do.
    docs = await core.db.movies_cache.find({}, {"_id": 0}).to_list(length=10000)
    if docs:
        doc_keys = {(m.get("title", "").lower().strip(), m.get("year")) for m in docs}
        core.CATALOG = docs + [
            m for m in core.SEED_MOVIES
            if (m.get("title", "").lower().strip(), m.get("year")) not in doc_keys
        ]
    from content_cards import attach_cards
    attach_cards(core.CATALOG)
    print(f"Catalog loaded: {len(core.get_catalog())} titles\n")
    results = []
    for p in PERSONAS:
        r = await run_persona(p)
        r["fails"] = evaluate(r)
        results.append(r)

    hdr = (f"{'Persona':<22}{'ceil':>5}{'swipes':>7}{'caught':>7}"
           f"{'minPool':>8}{'pBefore':>8}{'pFiltr':>7}{'pBroad':>7}"
           f"{'real':>5}{'lvFrac':>7}{'lowCf':>6}{'f30W':>5}{'f30Rel':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(
            f"{r['name']:<22}{r['ceiling']:>5}{r['swipes']:>7}"
            f"{str(r['caught_up_after']):>7}{str(r['min_pool']):>8}"
            f"{str(r['first_pool_before']):>8}{str(r['first_pool_after_filters']):>7}"
            f"{str(r['first_pool_after_broadening']):>7}"
            f"{r['reality_seen']:>5}{r['lowvote_frac']:>7}{r['low_conf_seen']:>6}"
            f"{r['first30_wild']:>5}{r['first30_relevant']:>7}"
        )

    print("\nProvider-confidence distribution (first build) + genre mode:")
    for r in results:
        print(f"  {r['name']:<22} mode={str(r['genre_match_mode']):<10} "
              f"prov={r['prov_dist']} reality_suppressed={r['reality_suppressed']} "
              f"low_vote_suppressed={r['low_vote_suppressed']}")

    print("\nMatured feed (after 100 swipes) — variety floor / discovery / diversity:")
    dh = (f"  {'Persona':<22}{'tier':>22}{'core%':>7}{'adj%':>6}{'wild%':>7}"
          f"{'domGen%':>8}{'#gen':>5}{'#thm':>5}{'#tone':>6}{'rep':>6}"
          f"{'maxStrk':>8}{'tailStrk':>9}{'floor':>6}")
    print(dh)
    for r in results:
        def _pct(x):
            return f"{x:.0%}" if isinstance(x, (int, float)) else "n/a"
        print(
            f"  {r['name']:<22}{str(r['final_tier']):>22}"
            f"{_pct(r['final_core_frac']):>7}{_pct(r['final_adj_frac']):>6}"
            f"{_pct(r['final_wild_frac']):>7}{_pct(r['dominant_genre_frac']):>8}"
            f"{str(r['distinct_genres']):>5}{str(r['distinct_themes']):>5}"
            f"{str(r['distinct_tones']):>6}{str(r['repetition_score']):>6}"
            f"{str(r['max_feel_streak']):>8}{str(r['tail_streak']):>9}"
            f"{str(r['tail_streak_floor']):>6}"
        )

    print("\nAcceptance evaluation:")
    any_fail = False
    for r in results:
        if r["fails"]:
            any_fail = True
            print(f"  ✗ {r['name']}: " + "; ".join(r["fails"]))
        else:
            print(f"  ✓ {r['name']}: all checks passed")
    print("\n" + ("SOME CHECKS FAILED" if any_fail else "ALL PERSONAS PASSED"))


if __name__ == "__main__":
    asyncio.run(main())
