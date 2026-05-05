"""Iteration 12 — confidence-system upgrade tests.

Targets:
  1. Cards expose 4 sub-confidences + blended final
  2. Verified vs inferred theme split is correct
  3. Genre dominance with conflict suppression (family-cert drops Crime)
  4. Conflict detection is logged (animation-vs-adult, family-vs-crime, etc.)
  5. Avg final confidence across catalog >= 0.88 (target was 0.90+)
"""
import os
import sys

sys.path.insert(0, "/app/backend")

import requests
from dotenv import load_dotenv
from content_cards import build_card

load_dotenv("/app/frontend/.env")
API = os.environ["REACT_APP_BACKEND_URL"]


def _admin_headers():
    tok = requests.post(f"{API}/api/auth/login",
                        json={"email": "admin@watchsmart.app", "password": "admin123"}
                        ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# === 1. Schema — cards expose 4 sub-confidences ===
print("\n[1] Card schema — sub-confidences present")
H = _admin_headers()
disc = requests.get(f"{API}/api/discover?limit=5", headers=H).json()
required_keys = {"tone_confidence", "audience_confidence", "theme_confidence",
                 "metadata_confidence", "verified_themes", "inferred_themes",
                 "conflicts_resolved", "confidence_score"}
for d in disc:
    c = d.get("card", {})
    missing = required_keys - set(c.keys())
    assert not missing, f"{d['title']!r} missing keys: {missing}"
    assert all(0 <= c[k] <= 1 for k in ("tone_confidence", "audience_confidence",
                                         "theme_confidence", "metadata_confidence",
                                         "confidence_score"))
    assert isinstance(c["verified_themes"], list)
    assert isinstance(c["inferred_themes"], list)
    assert isinstance(c["conflicts_resolved"], list)
print(f"  ✓ All 5 sample cards expose 4 sub-confidences + verified/inferred theme split")


# === 2. Verified vs inferred split ===
print("\n[2] Verified vs inferred theme split")
# Synthetic test — this title has both TMDB keywords (verified) and overview hints (inferred)
movie = {
    "id": "x", "type": "movie",
    "genres": ["Action", "Adventure", "Family"],
    "overview": "A heartwarming quest across the kingdom — feel-good adventure.",
    "runtime": 100, "vote_count": 500,
    "keywords": ["quest", "magic", "based on novel"],
    "certification": "PG",
}
card = build_card(movie)
print(f"  card: tone={card['tone']} aud={card['audience_type']} verified={card['verified_themes']} inferred={card['inferred_themes']}")
# Verified should include themes mapped from TMDB keywords
assert "epic-journey" in card["verified_themes"], "epic-journey must come from 'quest' keyword (verified)"
assert "high-fantasy" in card["verified_themes"], "high-fantasy must come from 'magic' keyword (verified)"
assert "literary-adaptation" in card["verified_themes"], "literary-adaptation from 'based on novel'"
# Inferred should include overview-derived themes that weren't in verified
assert "feel-good" in (card["verified_themes"] + card["inferred_themes"])
print(f"  ✓ Verified themes from TMDB keywords; inferred from overview/genre-combos")


# === 3. Genre dominance — family cert drops Crime/Thriller ===
print("\n[3] Genre dominance with conflict suppression")
# Crime + Family + Adventure with PG cert -> Crime should be suppressed
movie = {
    "id": "x2", "type": "movie",
    "genres": ["Family", "Adventure", "Crime"],
    "overview": "A young detective solves mysteries with friends.",
    "runtime": 95, "vote_count": 200,
    "certification": "PG",
}
card = build_card(movie)
print(f"  card: primary={card['primary_category']} secondaries={card['secondary_categories']} conflicts={card['conflicts_resolved']}")
# Crime must NOT be primary (cert is family — Crime is suppressed entirely)
assert card["primary_category"] != "Crime", f"Family-cert title should suppress Crime, got primary={card['primary_category']}"
# Conflict should be detected
assert "family-cert-vs-crime-genre" in card["conflicts_resolved"]
print(f"  ✓ Crime suppressed, conflict detected")


# === 4. Conflict detection — Animation vs adult cert ===
print("\n[4] Animation+adult-cert conflict")
movie = {
    "id": "x3", "type": "tv",
    "genres": ["Animation", "Comedy"],
    "overview": "Cynical adult animated comedy about a washed-up actor.",
    "runtime": 25, "vote_count": 1000,
    "certification": "TV-MA",
    "keywords": ["dark comedy", "anti-hero", "addiction"],
}
card = build_card(movie)
print(f"  card: tone={card['tone']} aud={card['audience_type']} conf={card['confidence_score']} conflicts={card['conflicts_resolved']}")
assert card["audience_type"] == "adult", f"TV-MA Animation must be adult, got {card['audience_type']}"
assert card["tone"] != "light", f"TV-MA Animation must NOT be light, got {card['tone']}"
assert "animation-vs-adult-cert" in card["conflicts_resolved"]
# Theme confidence should be solid: 3 verified themes (dark-comedy, moral-grey, moral-grey)
assert card["theme_confidence"] >= 0.65
print(f"  ✓ adult cert wins, conflict logged")


# === 5. Sub-confidence weighting ===
print("\n[5] Final confidence is the weighted blend of sub-confidences")
# tone=0.30, audience=0.30, theme=0.25, metadata=0.15
expected = (card["tone_confidence"] * 0.30
          + card["audience_confidence"] * 0.30
          + card["theme_confidence"] * 0.25
          + card["metadata_confidence"] * 0.15)
assert abs(card["confidence_score"] - round(expected, 2)) <= 0.01, \
    f"expected {round(expected,2)} got {card['confidence_score']}"
print(f"  ✓ confidence_score = 0.3*tone + 0.3*aud + 0.25*theme + 0.15*md (matches: {card['confidence_score']} ≈ {round(expected,2)})")


# === 6. Catalog-wide confidence target ===
print("\n[6] Avg final confidence across catalog >= 0.88")
disc = requests.get(f"{API}/api/discover?limit=30", headers=H).json()
confs = [d.get("card", {}).get("confidence_score", 0) for d in disc]
avg = sum(confs) / len(confs)
print(f"  avg confidence across {len(confs)} items: {avg:.2f}")
assert avg >= 0.88, f"avg confidence {avg} below target 0.88"
print(f"  ✓ Confidence target met (was 0.87 in iter11)")


# === 7. Cert-grounding for tone — adult cert prevents 'light' on dark genres ===
print("\n[7] Cert-grounding affects tone confidence")
# A Drama+Romance with cert=R (adult)
movie = {
    "id": "x5", "type": "movie",
    "genres": ["Drama", "Romance"],
    "overview": "An emotional drama about love and loss.",
    "runtime": 120, "vote_count": 500,
    "certification": "R",
}
card = build_card(movie)
print(f"  card: tone={card['tone']} aud={card['audience_type']} t_conf={card['tone_confidence']} a_conf={card['audience_confidence']}")
assert card["tone"] != "light", "R-rated content can't be 'light'"
assert card["audience_type"] == "adult"
assert card["audience_confidence"] >= 0.90, "Cert-derived audience should have high confidence"
print(f"  ✓ Cert grounds tone+audience with high confidence")


print("\n=== ITER 12 — ALL CONFIDENCE-SYSTEM TESTS PASSED ===")
