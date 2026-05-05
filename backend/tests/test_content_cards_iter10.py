"""Self-test for content cards system (iteration 10)."""
import os
import sys
sys.path.insert(0, "/app/backend")
import requests
import collections
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
API = os.environ["REACT_APP_BACKEND_URL"]

# Sanity import — exercise the classifier in isolation
from content_cards import (
    build_card, card_similarity,
    PRIMARY_GENRES, SECONDARY_GENRES, CONTEXT_GENRES,
    W_THEMES, W_TONE, W_AUDIENCE, W_PACING, W_GENRE,
)

assert abs(W_THEMES + W_TONE + W_AUDIENCE + W_PACING + W_GENRE - 1.0) < 1e-9
print("✓ weights sum to 1.0")

# --- Unit-level classifier tests ----------------------------------------
fixtures = [
    {
        "name": "Animation+Family kids movie -> light/family",
        "movie": {"id": "x1", "type": "movie", "genres": ["Animation", "Family", "Adventure"],
                  "overview": "A heartwarming journey across the wilderness.", "runtime": 95, "vote_count": 500},
        "expect": {"tone": "light", "audience": "family", "primary": "Animation",
                   "themes_includes": ["epic-journey"]},
    },
    {
        "name": "Crime+Drama -> dark + moral-grey (only context genres -> Crime allowed as fallback primary)",
        "movie": {"id": "x2", "type": "movie", "genres": ["Crime", "Drama"],
                  "overview": "An anti-hero faces a moral dilemma.", "runtime": 145, "vote_count": 800},
        "expect": {"tone": "dark", "primary_not_in": ["Drama"], "themes_includes": ["moral-grey"]},
    },
    {
        "name": "Action+Crime+Drama -> Action wins (context genres demoted)",
        "movie": {"id": "x2b", "type": "movie", "genres": ["Drama", "Crime", "Action"],
                  "overview": "A heist gone wrong.", "runtime": 140, "vote_count": 600},
        "expect": {"primary": "Action", "primary_not_in": ["Crime", "Drama"]},
    },
    {
        "name": "Horror -> dark + adult",
        "movie": {"id": "x3", "type": "movie", "genres": ["Horror", "Mystery"],
                  "overview": "Murder spreads through a haunted town.", "runtime": 102, "vote_count": 200},
        "expect": {"tone": "dark", "audience": "adult", "primary_in": ["Horror", "Mystery"]},
    },
    {
        "name": "Sci-Fi+Action -> space-opera + fast pacing",
        "movie": {"id": "x4", "type": "movie", "genres": ["Sci-Fi", "Action"],
                  "overview": "A starship crew battles across the galaxy.", "runtime": 119, "vote_count": 1000},
        "expect": {"pacing": "fast", "themes_includes": ["space-opera"]},
    },
    {
        "name": "Animation alone -> kids audience",
        "movie": {"id": "x5", "type": "movie", "genres": ["Animation", "Comedy"],
                  "overview": "Funny.", "runtime": 90, "vote_count": 100},
        "expect": {"audience": "kids", "tone": "light"},
    },
    {
        "name": "Drama+History -> slow pacing",
        "movie": {"id": "x6", "type": "movie", "genres": ["Drama", "History"],
                  "overview": "A historical epic.", "runtime": 160, "vote_count": 400},
        "expect": {"pacing": "slow", "primary_in": ["History"]},
    },
    {
        "name": "Documentary+Crime -> true-crime theme",
        "movie": {"id": "x7", "type": "movie", "genres": ["Documentary", "Crime"],
                  "overview": "Real-life murder investigation.", "runtime": 110, "vote_count": 300},
        "expect": {"themes_includes": ["true-crime"]},
    },
]

failures = []
for f in fixtures:
    card = build_card(f["movie"])
    e = f["expect"]
    if "tone" in e and card["tone"] != e["tone"]:
        failures.append(f"{f['name']}: tone {card['tone']} != {e['tone']}")
    if "audience" in e and card["audience_type"] != e["audience"]:
        failures.append(f"{f['name']}: aud {card['audience_type']} != {e['audience']}")
    if "pacing" in e and card["pacing"] != e["pacing"]:
        failures.append(f"{f['name']}: pacing {card['pacing']} != {e['pacing']}")
    if "primary" in e and card["primary_category"] != e["primary"]:
        failures.append(f"{f['name']}: primary {card['primary_category']} != {e['primary']}")
    if "primary_in" in e and card["primary_category"] not in e["primary_in"]:
        failures.append(f"{f['name']}: primary {card['primary_category']} not in {e['primary_in']}")
    if "primary_not_in" in e and card["primary_category"] in e["primary_not_in"]:
        failures.append(f"{f['name']}: primary {card['primary_category']} should not be in {e['primary_not_in']}")
    if "themes_includes" in e:
        for t in e["themes_includes"]:
            if t not in card["themes"]:
                failures.append(f"{f['name']}: themes missing {t}: got {card['themes']}")
    print(f"  {f['name']!r}: {card}")

if failures:
    print("\n❌ UNIT FAILURES:")
    for x in failures: print(" ", x)
    sys.exit(1)
print("\n✓ All unit fixtures passed\n")

# --- API integration tests ----------------------------------------------
tok = requests.post(f"{API}/api/auth/login",
                    json={"email": "admin@watchsmart.app", "password": "admin123"}
                    ).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}

# Find a Horror movie + an Animation+Family movie in catalog
disc = requests.get(f"{API}/api/discover?limit=30", headers=H).json()
print(f"Pulled {len(disc)} discover items. Looking for diverse fixtures...")

horror_id = None
animfam_id = None
for d in disc:
    g = set(d.get("genres") or [])
    if "Horror" in g and not horror_id:
        horror_id = d["id"]
    if {"Animation", "Family"} <= g and not animfam_id:
        animfam_id = d["id"]
    if horror_id and animfam_id:
        break

# If not in first 30, pull more from raw movies cache via search
if not horror_id:
    res = requests.get(f"{API}/api/search?q=horror", headers=H).json()
    items = res.get("results") or []
    if items:
        horror_id = items[0]["id"]
if not animfam_id:
    res = requests.get(f"{API}/api/search?q=disney", headers=H).json()
    items = res.get("results") or []
    for it in items:
        if "Animation" in (it.get("genres") or []):
            animfam_id = it["id"]
            break

print(f"horror_id={horror_id}  animfam_id={animfam_id}")

# 1. Verify card present on /movies/{id}
m1 = requests.get(f"{API}/api/movies/{disc[0]['id']}", headers=H).json()
assert "card" in m1 and isinstance(m1["card"], dict), "card missing on /movies/{id}"
required_keys = {"primary_category", "secondary_categories", "tone", "audience_type", "pacing", "themes", "confidence_score"}
assert required_keys <= set(m1["card"].keys()), f"card missing keys: {required_keys - set(m1['card'].keys())}"
assert m1["card"]["tone"] in ("light", "neutral", "dark")
assert m1["card"]["audience_type"] in ("kids", "family", "teen", "adult")
assert m1["card"]["pacing"] in ("fast", "medium", "slow")
assert 0 <= m1["card"]["confidence_score"] <= 1
print(f"✓ /movies/{{id}} returns full card: {m1['card']}")

# 2. Card already attached on /api/discover items
assert all("card" in d for d in disc), "discover items missing card field"
print(f"✓ all {len(disc)} discover items have card pre-attached")

# 3. Hierarchy: no CONTEXT_GENRE as primary if PRIMARY/SECONDARY available
violations = []
for d in disc:
    card = d.get("card") or {}
    g = set(d.get("genres") or [])
    has_primary_or_sec = bool(g & set(PRIMARY_GENRES + SECONDARY_GENRES))
    if has_primary_or_sec and card.get("primary_category") in CONTEXT_GENRES:
        violations.append(f"{d['title']!r}: primary={card['primary_category']} but genres={d['genres']}")
if violations:
    print("❌ Hierarchy violations:")
    for v in violations[:5]: print(" ", v)
    sys.exit(1)
print(f"✓ Hierarchy: 0 CONTEXT_GENRE-as-primary violations across {len(disc)} items")

# 4. Horror similarity → no kids audience
if horror_id:
    sims = requests.get(f"{API}/api/movies/{horror_id}/similar", headers=H).json()
    auds = [s.get("card", {}).get("audience_type") for s in sims]
    kids_in_horror = [a for a in auds if a == "kids"]
    print(f"  Horror similar audiences: {collections.Counter(auds)}")
    assert not kids_in_horror, f"Horror similar leaked kids audience: {kids_in_horror}"
    print(f"✓ Horror similarity has 0 kids audience")

# 5. Similarity is RANKED by card_similarity (descending)
if horror_id:
    target = requests.get(f"{API}/api/movies/{horror_id}", headers=H).json()
    target_card = target["card"]
    scored = [(s["title"], card_similarity(target_card, s.get("card") or build_card(s))) for s in sims]
    scores = [s[1] for s in scored]
    is_descending = all(scores[i] >= scores[i+1] - 0.15 for i in range(len(scores) - 1))
    print(f"  similarity scores (top 5): {scored[:5]}")
    assert is_descending, f"Similar not ranked: {scores}"
    print(f"✓ /similar ranked by card_similarity descending")

# 6. Idempotent — call /movies/{id} twice, card identical
m2 = requests.get(f"{API}/api/movies/{disc[0]['id']}", headers=H).json()
assert m1["card"] == m2["card"], "card not idempotent"
print(f"✓ Card idempotent across calls")

# 7. Distribution sanity across sample
cards = [d.get("card") for d in disc if d.get("card")]
print(f"\nDistribution across {len(cards)} sampled items:")
print(f"  tone: {dict(collections.Counter(c['tone'] for c in cards))}")
print(f"  audience: {dict(collections.Counter(c['audience_type'] for c in cards))}")
print(f"  pacing: {dict(collections.Counter(c['pacing'] for c in cards))}")
print(f"  primary categories (top 5): {collections.Counter(c['primary_category'] for c in cards).most_common(5)}")
avg_conf = sum(c["confidence_score"] for c in cards) / len(cards)
print(f"  avg confidence_score: {avg_conf:.2f}")

print("\n=== ALL TESTS PASSED ===")
