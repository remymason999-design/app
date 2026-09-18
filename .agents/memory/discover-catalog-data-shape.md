---
name: Discover catalog data shape (provider & genre strings)
description: Non-obvious provider slug + genre naming conventions in movies_cache, needed when constructing users/personas for the recommendation engine.
---

# Discover catalog data shape

When building users/personas or test fixtures for the recommendation engine,
the string values must match the catalogue exactly or `movie_matches` silently
returns an empty pool (no error). These are data conventions, not in code.

- **Provider slugs in `available_on`/`rent_on`/`buy_on` are lowercase snake_case**,
  not display names: `netflix`, `prime_video`, `disney_plus`, `hbo_max`,
  `paramount`, `apple_tv`. A `user.subscriptions` of `["Netflix"]` matches nothing.
- **Genre is `Sci-Fi`, not `Science Fiction`** (TMDB display name is collapsed).
  Other genres present: Drama, Comedy, Action, Animation, Crime, Family,
  Documentary, Mystery, Adventure, Thriller, War, Romance, Fantasy, Western,
  Horror, History, Music, Kids, Reality, Talk.
- All catalogue providers are region `GB` (`providers_region: "GB"`).

**Why:** persona-sim runs returned empty pools twice before discovering both the
slug casing and the `Sci-Fi` naming — neither is visible from engine code, only
from querying `movies_cache`.

**How to apply:** quick check —
`db.movies_cache.aggregate([{$unwind:"$genres"},{$group:{_id:"$genres",n:{$sum:1}}}])`
and the same for `$available_on` — before assuming any genre/provider string.

# Persona simulation harness

`backend/sim_personas.py` drives `engine.build_feed` in-process for N personas ×
M swipes. It must monkeypatch `engine._schedule_refill` and
`engine._schedule_record_shown` to no-ops (avoid DB writes + heavy TMDB refill
when the pool is thin) and instead maintain `user["recently_shown"]` manually,
replicating the `routers/user.py` learning ($inc weights) in-memory.
**Why:** without the no-ops a sim either writes to the real DB or blocks on TMDB
network refills triggered when pool < LOW_WATER.
