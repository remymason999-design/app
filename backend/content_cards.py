"""Content-card classification for catalog items.

Every TMDB title is enriched into a "content card" used by the recommendation
and similarity systems. The card represents the *meaning* of the title, not
just its raw genres. Classification is deterministic and heuristic — driven by
existing metadata (genres, tags, runtime, popularity, vote count, language,
overview keywords). No external calls.

Card schema:
  {
    primary_category:    str   -- the dominant lens (e.g. Animation, Action)
    secondary_categories list  -- supporting lenses (Adventure, Comedy)
    tone:                str   -- "light" | "neutral" | "dark"
    audience_type:       str   -- "kids" | "family" | "teen" | "adult"
    pacing:              str   -- "fast" | "medium" | "slow"
    themes:              list  -- semantic tags (kebab-case)
    confidence_score:    float -- 0.0..1.0 metadata completeness signal
  }

Hierarchy:
  PRIMARY_GENRES   — first one present on the title wins as primary_category
  SECONDARY_GENRES — placed in secondary_categories
  CONTEXT_GENRES   — context-only (ignored for primary, allowed to inform tone)
"""
from __future__ import annotations

from typing import Optional

# Genre tiers --------------------------------------------------------------
PRIMARY_GENRES = [
    "Animation", "Family", "Action", "Horror", "Comedy",
    "Sci-Fi", "Romance", "Documentary", "Mystery", "Western", "Music",
]
SECONDARY_GENRES = ["Adventure", "Fantasy", "History", "War"]
CONTEXT_GENRES = ["Crime", "Thriller", "Drama"]

# Tone signals -------------------------------------------------------------
DARK_GENRES = {"Horror", "War", "Crime", "Thriller"}
LIGHT_GENRES = {"Animation", "Family", "Comedy", "Music", "Romance"}

# Theme keyword detection in overview text (case-insensitive)
THEME_KEYWORDS = {
    "coming-of-age": ("coming of age", "teenager", "high school", "growing up"),
    "found-family": ("found family", "ragtag", "misfits", "unlikely team"),
    "redemption": ("redemption", "second chance", "atone", "make amends"),
    "heist": ("heist", "rob the", "stealing", "bank robbery"),
    "post-apocalyptic": ("post-apocalyp", "wasteland", "survivors", "after the fall"),
    "epic-journey": ("quest", "journey", "voyage", "across the"),
    "high-fantasy": ("kingdom", "magic", "wizard", "dragon", "throne"),
    "space-opera": ("galaxy", "starship", "interstellar", "spacefaring"),
    "moral-grey": ("morally", "anti-hero", "shades of grey", "dilemma"),
    "mind-bending": ("reality", "consciousness", "simulation", "twist"),
    "biographical": ("based on the true story", "real life", "biopic"),
    "true-crime": ("true crime", "real-life murder", "investigation"),
    "feel-good": ("feel-good", "heartwarming", "uplift", "joyful"),
    "psychological": ("psychological", "obsession", "unreliable narrator"),
    "survival": ("survive", "stranded", "wilderness", "isolat"),
    "dystopian": ("dystopia", "totalitarian", "oppressive society"),
    "romance-tragic": ("forbidden love", "tragic love", "doomed"),
    "war-drama": ("battlefield", "frontline", "occupation", "resistance"),
    "espionage": ("spy", "agent", "double cross", "intelligence agency"),
}

# Audience by certification (when present, see _certification_audience)
ADULT_CERTS = {"R", "NC-17", "TV-MA", "18", "MA15+", "X"}
TEEN_CERTS = {"PG-13", "TV-14", "12", "15", "12A", "M"}
FAMILY_CERTS = {"PG", "TV-PG", "TV-Y7", "TV-Y7-FV", "U"}
KIDS_CERTS = {"G", "TV-Y", "TV-G"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _certification_audience(cert: Optional[str]) -> Optional[str]:
    if not cert:
        return None
    c = cert.upper().strip()
    if c in KIDS_CERTS:
        return "kids"
    if c in FAMILY_CERTS:
        return "family"
    if c in TEEN_CERTS:
        return "teen"
    if c in ADULT_CERTS:
        return "adult"
    return None


def _extract_themes(movie: dict) -> list[str]:
    overview = (movie.get("overview") or "").lower()
    genres = set(movie.get("genres") or [])
    themes: list[str] = []
    for theme, needles in THEME_KEYWORDS.items():
        if any(n in overview for n in needles):
            themes.append(theme)

    # Genre-combo derived themes (always reliable)
    if "Adventure" in genres and ("Family" in genres or "Animation" in genres):
        themes.append("epic-journey")
    if "Crime" in genres and "Drama" in genres:
        themes.append("moral-grey")
    if "Sci-Fi" in genres and ("Mystery" in genres or "Thriller" in genres):
        themes.append("mind-bending")
    if "Horror" in genres and "Mystery" in genres:
        themes.append("dread")
    if "Fantasy" in genres and ("Adventure" in genres or "Action" in genres):
        themes.append("high-fantasy")
    if "Sci-Fi" in genres and "Action" in genres:
        themes.append("space-opera")
    if "Documentary" in genres and "Crime" in genres:
        themes.append("true-crime")
    if "War" in genres:
        themes.append("war-drama")
    if "Animation" in genres and "Family" in genres:
        themes.append("feel-good")

    # Dedup & cap (keep order)
    seen = set()
    out = []
    for t in themes:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:8]


def _classify_tone(movie: dict) -> str:
    """light / neutral / dark — overrides genre misclassification.

    Heuristic precedence:
      1. Animation/Family without Horror/Crime/Thriller -> light (overrides Drama)
      2. Horror or War or (Crime + Drama) or (Thriller + Crime) -> dark
      3. Comedy/Music/Romance dominant -> light
      4. otherwise neutral
    """
    g = set(movie.get("genres") or [])
    overview = (movie.get("overview") or "").lower()

    # Strong overrides
    if g & {"Animation", "Family"} and not (g & {"Horror", "Crime", "Thriller"}):
        return "light"
    if "Horror" in g or "War" in g:
        return "dark"
    if ("Crime" in g and "Drama" in g) or ("Thriller" in g and "Crime" in g):
        return "dark"

    # Lexical hints
    dark_words = ("murder", "death", "abuse", "trauma", "war", "torture", "tragedy", "killing")
    if any(w in overview for w in dark_words):
        return "dark"
    light_words = ("hilarious", "comedy", "romantic", "heartwarming", "feel-good", "joyful")
    if any(w in overview for w in light_words):
        return "light"

    if g & LIGHT_GENRES and not (g & DARK_GENRES):
        return "light"
    if g & DARK_GENRES:
        return "dark"

    return "neutral"


def _classify_audience(movie: dict) -> tuple[str, bool]:
    """Returns (audience_type, from_certification).

    Prefers TMDB certification when present (movie.certification or
    content_rating). Falls back to genre + tone heuristic.
    """
    cert = movie.get("certification") or movie.get("content_rating")
    audience = _certification_audience(cert)
    if audience:
        return audience, True

    g = set(movie.get("genres") or [])
    if g & {"Horror"} or "War" in g:
        return "adult", False
    if "Animation" in g and "Family" in g:
        return "family", False
    if "Animation" in g:
        return "kids", False
    if "Family" in g:
        return "family", False
    overview = (movie.get("overview") or "").lower()
    if any(w in overview for w in ("graphic violence", "explicit", "drug use")):
        return "adult", False
    if any(w in overview for w in ("teenager", "high school", "young adult")):
        return "teen", False
    return "adult", False


def _classify_pacing(movie: dict) -> str:
    """fast / medium / slow."""
    g = set(movie.get("genres") or [])
    runtime = movie.get("runtime") or 0
    is_tv = movie.get("type") == "tv"

    if not is_tv:
        if g & {"Action", "Thriller", "Horror"} and runtime and runtime <= 120:
            return "fast"
        if "Documentary" in g or ("Drama" in g and runtime and runtime >= 140):
            return "slow"
        if "History" in g or "War" in g:
            return "slow"
        return "medium"
    # TV pacing
    if g & {"Action", "Thriller"}:
        return "fast"
    if g & {"Drama", "Documentary", "History"}:
        return "slow"
    return "medium"


def _confidence(movie: dict, themes: list[str], audience_from_cert: bool) -> float:
    """0.0..1.0 — completeness of signal we used to classify."""
    score = 0.0
    if movie.get("genres"):
        score += 0.25
    if movie.get("overview"):
        score += 0.15
    if movie.get("runtime"):
        score += 0.10
    if (movie.get("vote_count") or 0) >= 50:
        score += 0.10
    if audience_from_cert:
        score += 0.20
    if themes:
        score += min(0.20, 0.05 * len(themes))
    return round(min(1.0, score), 2)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def build_card(movie: dict) -> dict:
    """Build and attach a content card to a movie dict (returns the card)."""
    genres = list(movie.get("genres") or [])

    # Primary: first PRIMARY_GENRE present, fallback to first secondary, else first, else "Uncategorized"
    primary = next((g for g in PRIMARY_GENRES if g in genres), None)
    if not primary:
        primary = next((g for g in SECONDARY_GENRES if g in genres), None)
    if not primary and genres:
        # CONTEXT_GENRES are context-only — used as primary only if nothing else
        primary = genres[0]
    if not primary:
        primary = "Uncategorized"

    # Secondary: SECONDARY_GENRES on this title, in declared order
    secondaries = [g for g in genres if g in SECONDARY_GENRES and g != primary]
    # If there are still genre slots free, allow other PRIMARY_GENRES as secondary
    for g in genres:
        if g != primary and g in PRIMARY_GENRES and g not in secondaries:
            secondaries.append(g)
    secondaries = secondaries[:3]

    tone = _classify_tone(movie)
    audience, audience_from_cert = _classify_audience(movie)
    pacing = _classify_pacing(movie)
    themes = _extract_themes(movie)
    confidence = _confidence(movie, themes, audience_from_cert)

    return {
        "primary_category": primary,
        "secondary_categories": secondaries,
        "tone": tone,
        "audience_type": audience,
        "pacing": pacing,
        "themes": themes,
        "confidence_score": confidence,
    }


def attach_cards(catalog: list[dict]) -> None:
    """Mutate every catalog item in place — adds a `card` field."""
    for m in catalog:
        if "card" not in m or not m["card"]:
            m["card"] = build_card(m)


# ---------------------------------------------------------------------------
# Card-based similarity (replaces raw-genre similarity for /movies/{id}/similar)
# ---------------------------------------------------------------------------

# Weights from the spec (sum to 1.0)
W_THEMES = 0.40
W_TONE = 0.25
W_AUDIENCE = 0.20
W_PACING = 0.10
W_GENRE = 0.05


def card_similarity(target: dict, candidate: dict) -> float:
    """Score 0..1 for how similar two cards are, weighted per spec."""
    if not target or not candidate:
        return 0.0
    score = 0.0

    # Themes — Jaccard
    a = set(target.get("themes") or [])
    b = set(candidate.get("themes") or [])
    if a or b:
        score += W_THEMES * (len(a & b) / max(1, len(a | b)))

    # Tone — exact match
    if target.get("tone") and target.get("tone") == candidate.get("tone"):
        score += W_TONE

    # Audience — exact, with adjacent partial credit (kids<->family, teen<->adult)
    aud_a, aud_b = target.get("audience_type"), candidate.get("audience_type")
    if aud_a and aud_a == aud_b:
        score += W_AUDIENCE
    else:
        adjacent = {
            ("kids", "family"), ("family", "kids"),
            ("family", "teen"), ("teen", "family"),
            ("teen", "adult"), ("adult", "teen"),
        }
        if (aud_a, aud_b) in adjacent:
            score += W_AUDIENCE * 0.5

    # Pacing — exact
    if target.get("pacing") and target.get("pacing") == candidate.get("pacing"):
        score += W_PACING

    # Genre — primary match dominant, secondaries Jaccard
    if target.get("primary_category") and target.get("primary_category") == candidate.get("primary_category"):
        score += W_GENRE * 0.7
    sec_a = set(target.get("secondary_categories") or [])
    sec_b = set(candidate.get("secondary_categories") or [])
    if sec_a or sec_b:
        score += W_GENRE * 0.3 * (len(sec_a & sec_b) / max(1, len(sec_a | sec_b)))

    # Damp by min confidence so half-classified items don't ride high similarity
    conf = min(target.get("confidence_score", 0.6), candidate.get("confidence_score", 0.6))
    return round(score * (0.6 + 0.4 * conf), 4)
