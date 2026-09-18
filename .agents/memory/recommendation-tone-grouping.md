---
name: Recommendation tone grouping
description: How adjacent/wildcard tone compatibility is decided in the feed engine
---
# Effective tone group, not raw card.tone

When gating exploration (adjacent/wildcard) candidates for tonal fit, a
candidate's **effective tone group** is derived from `card.tone` PLUS its
themes and audience_type — NOT `card.tone` alone.

**Why:** heuristic `card.tone` frequently lands on "neutral" for emotionally
loud titles (a feel-good Christmas comedy, a war drama). Using raw tone let a
Christmas comedy leak into a Horror feed and a war drama into a Comedy feed,
which destroys trust. Strong themes override raw tone; dark beats light on ties.

**How to apply:** see `LIGHT_TONE_THEMES` / `DARK_TONE_THEMES` /
`_candidate_tone_group()` in `backend/engine.py`. The genre→blocked-tone map is
`GENRE_TONE_GUARDS`. Blocked tones are relaxed per-user when learned signals
show appetite (`_behavior_supports_tone`). Genre conflicts (e.g. Horror+Comedy)
disable the guard. Documentary feeds add subtype continuity.
