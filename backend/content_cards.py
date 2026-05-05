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

# Theme keywords (matched against overview text + TMDB keyword tags)
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

# Direct mapping from TMDB canonical keyword names → theme
KEYWORD_THEME_MAP = {
    "coming of age": "coming-of-age",
    "teenager": "coming-of-age",
    "high school": "coming-of-age",
    "school": "coming-of-age",
    "based on novel or book": "literary-adaptation",
    "based on novel": "literary-adaptation",
    "based on manga": "literary-adaptation",
    "based on comic": "literary-adaptation",
    "based on comic book": "literary-adaptation",
    "based on true story": "biographical",
    "based on real person": "biographical",
    "biography": "biographical",
    "biopic": "biographical",
    "heist": "heist",
    "robbery": "heist",
    "post-apocalyptic future": "post-apocalyptic",
    "post-apocalyptic": "post-apocalyptic",
    "dystopia": "dystopian",
    "dystopian future": "dystopian",
    "space opera": "space-opera",
    "space travel": "space-opera",
    "spacecraft": "space-opera",
    "interstellar travel": "space-opera",
    "epic": "epic-journey",
    "quest": "epic-journey",
    "journey": "epic-journey",
    "magic": "high-fantasy",
    "wizard": "high-fantasy",
    "dragon": "high-fantasy",
    "kingdom": "high-fantasy",
    "fantasy world": "high-fantasy",
    "supernatural": "supernatural",
    "psychological thriller": "psychological",
    "psychological horror": "psychological",
    "psychological drama": "psychological",
    "psychological": "psychological",
    "obsession": "psychological",
    "complex": "psychological",
    "philosophical": "psychological",
    "true crime": "true-crime",
    "serial killer": "true-crime",
    "fbi": "true-crime",
    "detective": "true-crime",
    "investigation": "true-crime",
    "murder": "true-crime",
    "murder mystery": "mind-bending",
    "twist ending": "mind-bending",
    "mind game": "mind-bending",
    "anthology": "mind-bending",
    "redemption": "redemption",
    "found family": "found-family",
    "friendship": "found-family",
    "spy": "espionage",
    "secret agent": "espionage",
    "espionage": "espionage",
    "world war ii": "war-drama",
    "world war i": "war-drama",
    "battlefield": "war-drama",
    "survival": "survival",
    "stranded": "survival",
    "wilderness": "survival",
    "feel good": "feel-good",
    "heartwarming": "feel-good",
    "nostalgic": "nostalgic",
    "romance": "romance",
    "love": "romance",
    "lgbt": "lgbt",
    "anime": "anime",
    "miniseries": "limited-series",
    "limited series": "limited-series",
    "prison": "prison-drama",
    "anti-hero": "moral-grey",
    "morally gray": "moral-grey",
    "addiction": "moral-grey",
    "dark comedy": "dark-comedy",
    "satire": "dark-comedy",
    "doctor": "medical-drama",
    "hospital": "medical-drama",
    "lawyer": "courtroom",
    "courtroom": "courtroom",
    "orphan": "found-family",
    "dramatic": "drama-heavy",
    "suspenseful": "suspense",
}

# Audience by certification (region-specific). Includes UK BBFC + US MPA + TV ratings.
ADULT_CERTS = {"R", "NC-17", "TV-MA", "18", "MA15+", "X"}
TEEN_CERTS = {"PG-13", "TV-14", "12", "12A", "15", "M"}
FAMILY_CERTS = {"PG", "TV-PG", "TV-Y7", "TV-Y7-FV", "U"}
KIDS_CERTS = {"G", "TV-Y", "TV-G", "Uc"}


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


def _extract_themes_split(movie: dict) -> tuple[list[str], list[str]]:
    """Returns (verified_themes, inferred_themes).

      verified  = TMDB curated keyword taxonomy mapped via KEYWORD_THEME_MAP
      inferred  = overview lexical hints + genre-combo derived themes
    """
    verified: list[str] = []
    inferred: list[str] = []

    # 1. Verified — TMDB canonical keywords
    for kw in (movie.get("keywords") or []):
        mapped = KEYWORD_THEME_MAP.get(kw.lower().strip())
        if mapped and mapped not in verified:
            verified.append(mapped)

    # 2. Inferred — overview lexical hints
    overview = (movie.get("overview") or "").lower()
    for theme, needles in THEME_KEYWORDS.items():
        if theme in verified:
            continue
        if any(n in overview for n in needles):
            inferred.append(theme)

    # 3. Inferred — genre-combo rules
    genres = set(movie.get("genres") or [])
    combo_themes = []
    if "Adventure" in genres and ("Family" in genres or "Animation" in genres):
        combo_themes.append("epic-journey")
    if "Crime" in genres and "Drama" in genres:
        combo_themes.append("moral-grey")
    if "Sci-Fi" in genres and ("Mystery" in genres or "Thriller" in genres):
        combo_themes.append("mind-bending")
    if "Horror" in genres and "Mystery" in genres:
        combo_themes.append("dread")
    if "Fantasy" in genres and ("Adventure" in genres or "Action" in genres):
        combo_themes.append("high-fantasy")
    if "Sci-Fi" in genres and "Action" in genres:
        combo_themes.append("space-opera")
    if "Documentary" in genres and "Crime" in genres:
        combo_themes.append("true-crime")
    if "War" in genres:
        combo_themes.append("war-drama")
    if "Animation" in genres and "Family" in genres:
        combo_themes.append("feel-good")
    for t in combo_themes:
        if t not in verified and t not in inferred:
            inferred.append(t)

    return verified[:8], inferred[:8]


def _extract_themes(movie: dict) -> list[str]:
    """Backwards-compat helper — combined verified + inferred capped at 8."""
    verified, inferred = _extract_themes_split(movie)
    out = list(verified)
    for t in inferred:
        if t not in out:
            out.append(t)
    return out[:8]


def _classify_tone(movie: dict, *, cert_audience_tier: Optional[str] = None) -> str:
    """light / neutral / dark — overrides genre misclassification.

    Precedence (cert is strongest signal):
      1. Family/Kids cert -> tone is at most "neutral" (never dark unless Horror)
      2. Adult cert -> tone is at least "neutral" (never light)
      3. Horror or War -> dark
      4. Crime+Drama or Thriller+Crime -> dark
      5. Animation/Family without Horror/Crime/Thriller -> light
      6. lexical hints + light/dark genre fallback
    """
    g = set(movie.get("genres") or [])
    overview = (movie.get("overview") or "").lower()
    cert = (movie.get("certification") or movie.get("content_rating") or "").upper().strip()
    is_adult_rated = cert in ADULT_CERTS

    # Hard genre signals
    if "Horror" in g or "War" in g:
        return "dark"
    if ("Crime" in g and "Drama" in g) or ("Thriller" in g and "Crime" in g):
        # CONFLICT: family-cert + crime/thriller — cert wins, treat as neutral
        if cert_audience_tier in ("kids", "family"):
            return "neutral"
        return "dark"

    # Family/Animation override — but only when content is NOT adult-rated
    if g & {"Animation", "Family"} and not (g & {"Horror", "Crime", "Thriller"}) and not is_adult_rated:
        return "light"

    # Lexical hints (only override if no adult cert)
    dark_words = ("murder", "death", "abuse", "trauma", "war", "torture", "tragedy", "killing")
    has_dark = any(w in overview for w in dark_words)
    if has_dark:
        # CONFLICT: family-cert + dark overview lexicon — cert wins
        if cert_audience_tier in ("kids", "family"):
            return "neutral"
        return "dark"
    if not is_adult_rated:
        light_words = ("hilarious", "comedy", "romantic", "heartwarming", "feel-good", "joyful")
        if any(w in overview for w in light_words):
            return "light"

    if g & LIGHT_GENRES and not (g & DARK_GENRES) and not is_adult_rated:
        return "light"
    if g & DARK_GENRES:
        # Adult cert reinforces, family cert reduces to neutral
        if cert_audience_tier in ("kids", "family"):
            return "neutral"
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


def _sub_confidences(
    movie: dict,
    *,
    verified_themes: list[str],
    inferred_themes: list[str],
    audience_from_cert: bool,
    cert_audience_tier: Optional[str],
    tone: str,
    genres: list[str],
) -> dict:
    """Returns dict of sub-confidences in [0,1].

    tone_confidence:
      - 1.0 when adult cert + dark genre/lexical agree, OR family cert + light
        genre agree (mutually reinforcing signals)
      - 0.85 when cert exists but doesn't directly imply this tone
      - 0.7  when only genre evidence supports the tone
      - 0.5  when only overview lexical hints support it (no cert, no genre)

    audience_confidence:
      - 0.95 when derived from certification (cert tier matches our audience)
      - 0.65 when derived from genre heuristic alone (no cert)
      - 0.45 when overview-only signals were used

    theme_confidence:
      - blend: 0.5 base if any themes exist, +0.05 per verified theme,
        +0.02 per inferred theme. Caps at 1.0.

    metadata_confidence:
      - completeness: genres + overview + runtime + vote_count >= 50.
    """
    g = set(genres)
    cert_present = bool(movie.get("certification") or movie.get("content_rating"))

    # Tone confidence
    if cert_present:
        # Adult cert + dark/neutral aligns; family cert + light aligns
        if cert_audience_tier in ("adult",) and tone in ("dark", "neutral"):
            tone_conf = 1.0
        elif cert_audience_tier in ("family", "kids") and tone == "light":
            tone_conf = 1.0
        elif cert_audience_tier in ("teen",) and tone != "light":
            tone_conf = 0.9
        else:
            tone_conf = 0.85
    elif g & (DARK_GENRES | LIGHT_GENRES):
        tone_conf = 0.7
    elif (movie.get("overview") or ""):
        tone_conf = 0.5
    else:
        tone_conf = 0.3

    # Audience confidence
    if audience_from_cert:
        audience_conf = 0.95
    elif g & {"Animation", "Family", "Horror", "War"}:
        audience_conf = 0.65
    elif movie.get("overview"):
        audience_conf = 0.45
    else:
        audience_conf = 0.30

    # Theme confidence — calibrated so that:
    #   - 3+ themes with at least 1 verified -> 0.95 (we know what this is about)
    #   - 2 themes -> 0.80
    #   - 1 theme -> 0.65
    #   - 0 themes BUT keywords array is non-empty -> 0.60 (TMDB-tagged but
    #     none of our taxonomy hit — confidence we have nothing wrong)
    #   - 0 themes + keywords absent BUT overview/genres present -> 0.50
    #   - sparse (no overview, no keywords) -> 0.30
    has_keywords = bool(movie.get("keywords"))
    has_overview = bool(movie.get("overview"))
    if len(verified_themes) + len(inferred_themes) >= 3 and verified_themes:
        theme_conf = 0.95
    elif len(verified_themes) + len(inferred_themes) >= 2:
        theme_conf = 0.80
    elif len(verified_themes) + len(inferred_themes) >= 1:
        theme_conf = 0.65
    elif has_keywords:
        theme_conf = 0.60
    elif has_overview:
        theme_conf = 0.50
    else:
        theme_conf = 0.30

    # Metadata completeness
    md_score = 0.0
    if movie.get("genres"):
        md_score += 0.30
    if movie.get("overview"):
        md_score += 0.20
    if movie.get("runtime"):
        md_score += 0.15
    if (movie.get("vote_count") or 0) >= 50:
        md_score += 0.15
    if movie.get("keywords"):
        md_score += 0.20
    md_conf = min(1.0, md_score)

    return {
        "tone_confidence": round(tone_conf, 2),
        "audience_confidence": round(audience_conf, 2),
        "theme_confidence": round(theme_conf, 2),
        "metadata_confidence": round(md_conf, 2),
    }


# Sub-confidence weights for the final blended confidence_score
W_CONF_TONE = 0.30
W_CONF_AUDIENCE = 0.30
W_CONF_THEME = 0.25
W_CONF_METADATA = 0.15
assert abs(W_CONF_TONE + W_CONF_AUDIENCE + W_CONF_THEME + W_CONF_METADATA - 1.0) < 1e-9


def _detect_conflicts(
    *,
    cert_audience_tier: Optional[str],
    genres: set,
    tone: str,
    overview: str,
) -> list[str]:
    """Return human-readable list of conflicts detected for transparency."""
    conflicts: list[str] = []
    # 1. Family vs Crime/Thriller: family-rated content with crime genre is suspicious
    if cert_audience_tier in ("kids", "family") and (genres & {"Crime", "Thriller"}):
        conflicts.append("family-cert-vs-crime-genre")
    # 2. Animation alone (no Family) but adult cert -> dark/adult animation
    if "Animation" in genres and "Family" not in genres and cert_audience_tier == "adult":
        conflicts.append("animation-vs-adult-cert")
    # 3. Family/Animation but tone heuristic landed on dark from overview
    if (genres & {"Family", "Animation"}) and tone == "dark" and cert_audience_tier in ("kids", "family"):
        conflicts.append("family-cert-vs-dark-tone")
    # 4. Horror genre but family cert (TMDB occasionally mis-tags) — cert wins
    if "Horror" in genres and cert_audience_tier in ("kids", "family"):
        conflicts.append("horror-genre-vs-family-cert")
    return conflicts


def _resolve_genre_conflicts(genres: list[str], cert_audience_tier: Optional[str]) -> list[str]:
    """Drop conflicting genres before primary/secondary selection.

    Family-certified titles drop Crime/Thriller from the genre list — these are
    almost always production-coding artefacts (e.g. a kids' detective show
    flagged "Crime"). Adult-certified Animation titles keep all genres because
    Crime+Animation together is genuine signal (BoJack, Invincible).
    """
    if cert_audience_tier in ("kids", "family"):
        return [g for g in genres if g not in {"Crime", "Thriller", "Horror"}]
    return list(genres)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def build_card(movie: dict) -> dict:
    """Build and attach a content card to a movie dict (returns the card).

    Pipeline:
      1. Determine cert-driven audience tier (strongest signal)
      2. Resolve genre conflicts based on cert tier (e.g. drop Crime from family)
      3. Pick primary/secondary from the resolved genre list
      4. Classify tone using cert-aware precedence
      5. Classify audience (cert wins, fallback to genre)
      6. Classify pacing
      7. Extract themes split into verified (TMDB keywords) + inferred
      8. Compute four sub-confidences + weighted blend
      9. Detect & log any unresolved conflicts for transparency
    """
    raw_genres = list(movie.get("genres") or [])
    cert = movie.get("certification") or movie.get("content_rating")
    cert_tier = _certification_audience(cert)

    # Resolve conflicts BEFORE genre selection (cert overrides production-coding artefacts)
    resolved_genres = _resolve_genre_conflicts(raw_genres, cert_tier)
    genre_set = set(resolved_genres)

    # ---- Primary / secondary -----------------------------------------------
    primary = next((g for g in PRIMARY_GENRES if g in genre_set), None)
    if not primary:
        primary = next((g for g in SECONDARY_GENRES if g in genre_set), None)
    if not primary and resolved_genres:
        primary = resolved_genres[0]
    if not primary:
        primary = "Uncategorized"

    secondaries = [g for g in resolved_genres if g in SECONDARY_GENRES and g != primary]
    for g in resolved_genres:
        if g != primary and g in PRIMARY_GENRES and g not in secondaries:
            secondaries.append(g)
    secondaries = secondaries[:3]

    # ---- Tone / audience / pacing ------------------------------------------
    # Pass resolved genres into a temporary copy so classifiers see the cleaned list
    tone_input = dict(movie)
    tone_input["genres"] = resolved_genres
    tone = _classify_tone(tone_input, cert_audience_tier=cert_tier)
    audience, audience_from_cert = _classify_audience(tone_input)
    pacing = _classify_pacing(tone_input)

    # ---- Themes (split) ----------------------------------------------------
    verified_themes, inferred_themes = _extract_themes_split(tone_input)
    themes = list(verified_themes)
    for t in inferred_themes:
        if t not in themes:
            themes.append(t)
    themes = themes[:8]

    # ---- Sub-confidences + blended final -----------------------------------
    subs = _sub_confidences(
        movie,
        verified_themes=verified_themes,
        inferred_themes=inferred_themes,
        audience_from_cert=audience_from_cert,
        cert_audience_tier=cert_tier,
        tone=tone,
        genres=resolved_genres,
    )
    final = (
        subs["tone_confidence"] * W_CONF_TONE
        + subs["audience_confidence"] * W_CONF_AUDIENCE
        + subs["theme_confidence"] * W_CONF_THEME
        + subs["metadata_confidence"] * W_CONF_METADATA
    )

    conflicts = _detect_conflicts(
        cert_audience_tier=cert_tier,
        genres=set(raw_genres),
        tone=tone,
        overview=(movie.get("overview") or ""),
    )

    return {
        "primary_category": primary,
        "secondary_categories": secondaries,
        "tone": tone,
        "audience_type": audience,
        "pacing": pacing,
        "themes": themes,
        "verified_themes": verified_themes,
        "inferred_themes": inferred_themes,
        "tone_confidence": subs["tone_confidence"],
        "audience_confidence": subs["audience_confidence"],
        "theme_confidence": subs["theme_confidence"],
        "metadata_confidence": subs["metadata_confidence"],
        "confidence_score": round(min(1.0, final), 2),
        "conflicts_resolved": conflicts,
    }


def attach_cards(catalog: list[dict]) -> None:
    """Mutate every catalog item in place — adds/refreshes a `card` field.

    Cards are rebuilt when they're missing OR when they predate the iter-12
    schema (no `tone_confidence` field).
    """
    for m in catalog:
        existing = m.get("card") or {}
        if not existing or "tone_confidence" not in existing:
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
