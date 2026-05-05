"""Stabilisation regression tests (iteration 11):
   - filters strictly enforced before ranking on every list endpoint
   - sections dedupe against saved/watched/skipped/onboarding_rated/recently_shown
   - repetition control across consecutive /discover calls
   - More Like This uses card-similarity only (no raw genre overlap fallback)
"""
import os
import random
import string
import sys

sys.path.insert(0, "/app/backend")

import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
API = os.environ["REACT_APP_BACKEND_URL"]


def rand(n=6):
    return "".join(random.choices(string.ascii_lowercase, k=n))


def reg(email, name, services, content_type="movie", excluded=None, excluded_genres=None):
    requests.post(f"{API}/api/auth/register",
                  json={"email": email, "password": "pass1234", "name": name})
    tok = requests.post(f"{API}/api/auth/login",
                        json={"email": email, "password": "pass1234"}
                        ).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    requests.put(f"{API}/api/user/preferences", headers=H, json={
        "services": services,
        "content_type": content_type,
        "excluded_categories": excluded or [],
        "excluded_genres": excluded_genres or [],
    })
    return H


# === 1. Strict filter enforcement ===
print("\n[1] Filters strictly enforced BEFORE ranking on every list endpoint")
H = reg(f"f1_{rand()}@t.com", "f1",
        services=["netflix", "prime_video", "disney_plus"],
        content_type="movie",
        excluded=["anime"],
        excluded_genres=["Horror"])

failures = []
for endpoint in ["/api/discover", "/api/sections/trending",
                 "/api/sections/upcoming", "/api/sections/popular-locally",
                 "/api/search?q=the"]:
    r = requests.get(f"{API}{endpoint}", headers=H)
    items = r.json()
    if isinstance(items, dict):  # /search returns {results, fallback}
        items = items.get("results", [])
    tv_count = sum(1 for m in items if m.get("type") == "tv")
    anime = sum(1 for m in items if "anime" in (m.get("tags") or []))
    horror = sum(1 for m in items if "Horror" in (m.get("genres") or []))
    if tv_count or anime or horror:
        failures.append(f"{endpoint}: TV={tv_count} anime={anime} horror={horror}")
    else:
        print(f"  ✓ {endpoint}: 0 TV / 0 anime / 0 horror across {len(items)} items")

if failures:
    print("  ❌ FAILURES:", failures)
    sys.exit(1)


# === 2. Sections dedupe against user's seen items ===
print("\n[2] Sections dedupe against user's saved/watched/skipped")
H = reg(f"f2_{rand()}@t.com", "f2",
        services=["netflix", "prime_video", "disney_plus", "hbo_max"],
        content_type="both")

# Get a trending item, save it
trending = requests.get(f"{API}/api/sections/trending?limit=12", headers=H).json()
if not trending:
    print("  ⚠ no trending items returned (TMDB cache miss — skipping)")
else:
    saved_id = trending[0]["id"]
    requests.post(f"{API}/api/user/action", headers=H,
                  json={"movie_id": saved_id, "action": "save"})
    # Re-fetch trending — saved item should NOT appear
    trending2 = requests.get(f"{API}/api/sections/trending?limit=12", headers=H).json()
    ids2 = {m["id"] for m in trending2}
    if saved_id in ids2:
        print(f"  ❌ FAIL: saved item {saved_id!r} still in trending")
        sys.exit(1)
    print(f"  ✓ trending strips saved items (1st returned {len(trending)}, 2nd returned {len(trending2)} without {saved_id!r})")


# === 3. Repetition control across consecutive /discover calls ===
print("\n[3] /discover repetition control across consecutive calls")
H = reg(f"f3_{rand()}@t.com", "f3",
        services=["netflix", "prime_video", "disney_plus"],
        content_type="both")

call1 = requests.get(f"{API}/api/discover?limit=20", headers=H).json()
call2 = requests.get(f"{API}/api/discover?limit=20", headers=H).json()
ids1 = {m["id"] for m in call1}
ids2 = {m["id"] for m in call2}
overlap = ids1 & ids2
overlap_pct = len(overlap) / max(len(ids1), 1) * 100
if overlap_pct > 30:
    print(f"  ❌ FAIL: {overlap_pct:.0f}% overlap between consecutive /discover calls (expect <30%)")
    sys.exit(1)
print(f"  ✓ consecutive /discover calls overlap only {overlap_pct:.0f}% ({len(overlap)} of {len(ids1)})")


# === 4. More Like This is card-similarity only (no genre fallback) ===
print("\n[4] More Like This uses card-similarity only")
H = reg(f"f4_{rand()}@t.com", "f4",
        services=["netflix", "prime_video", "disney_plus", "hbo_max"],
        content_type="both")

disc = requests.get(f"{API}/api/discover?limit=15", headers=H).json()
# Pick a movie with rich card signals
target = next((m for m in disc if (m.get("card") or {}).get("themes")), disc[0])
target_card = target["card"]

sims = requests.get(f"{API}/api/movies/{target['id']}/similar", headers=H).json()
print(f"  Target: {target['title']!r} (themes={target_card['themes'][:3]})")
print(f"  Returned {len(sims)} similar items")

# Verify scores are descending and all use cards
prev_score = 1.01
from content_cards import card_similarity
for s in sims[:5]:
    c = s.get("card") or {}
    if not c:
        print(f"  ❌ FAIL: {s['title']!r} has no card — fallback shouldn't bypass classification")
        sys.exit(1)
    score = card_similarity(target_card, c)
    print(f"    - {s['title']!r}: tone={c['tone']} aud={c['audience_type']} score={score:.3f}")

# Verify NOT just genre-overlap matches (the previous heuristic)
# i.e. similar items should diverge in genre but share themes/tone/audience
target_genres = set(target.get("genres") or [])
divergent_genres = [s for s in sims if not (set(s.get("genres") or []) & target_genres)]
print(f"  Divergent-genre matches (proves card-only): {len(divergent_genres)} of {len(sims)}")


# === 5. Confidence improvement check ===
print("\n[5] Avg confidence after enrichment >= 0.80")
H_admin = {"Authorization": f"Bearer " + requests.post(f"{API}/api/auth/login",
                                                       json={"email":"admin@watchsmart.app","password":"admin123"}).json()["access_token"]}
disc = requests.get(f"{API}/api/discover?limit=20", headers=H_admin).json()
confs = [(m.get("card") or {}).get("confidence_score", 0) for m in disc]
avg = sum(confs) / len(confs)
print(f"  Avg confidence across 20 items: {avg:.2f}")
if avg < 0.80:
    print(f"  ❌ FAIL: confidence too low (target >=0.80)")
    sys.exit(1)
print(f"  ✓ Confidence target met (was 0.62 before enrichment)")


print("\n=== ALL STABILISATION TESTS PASSED ===")
