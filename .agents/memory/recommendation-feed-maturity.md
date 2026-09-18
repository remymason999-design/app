---
name: Recommendation feed maturity (anti-genre-trap)
description: Durable decisions for the matured-user feed — variety floor, discovery band, anti-repetition
---
# Matured-user feed: avoid "trapped in one genre"

As a user matures (saturates after ~25 interactions; tiers exploratory<20,
semi_confident 20-49, confident 50-99, strongly_personalised 100+), the feed must
shift from hard-genre matching toward *feeling* (tone/pacing/themes) and broaden.

## Trust head is deliberately allowed to be one feeling
The feed opens on the user's explicit intent (the "trust head" — first cards are
pure core genre, no wildcard). For a mono-tone taste (a thriller fan whose whole
pool is dark) that head is unavoidably a single-feeling run, and that is correct
product behaviour — do NOT try to break it with off-feeling discovery in the
opening.
**Why:** breaking the opening with light comedy for a dark-loving user destroys
the "this gets me" feel.
**How to apply:** measure anti-repetition streaks only on the region *after* the
head. Assert achieved tail streak against the supply-aware achievable minimum
`ceil(dominant_tone / (separators + 1))`, NOT a flat max. A flat "max streak ≤ N"
either false-fails mono-tone feeds or vacuously passes — the supply-aware floor
is the honest bar.

## Anti-repetition must spread the dominant feeling EVENLY
A greedy "swap a different card forward only when the run exceeds max_run"
front-loads the dominant feeling and dumps all leftovers into one long tail run.
Instead chunk the dominant group into even buckets and spread minority cards into
the gaps (recursively de-streak minorities so you don't trade one streak for
another).

## Variety floor: thin-pool "use all core" rescue must skip confident users
The niche-genre rescue that fills the feed with *every* remaining core title is
only for users still establishing intent. For a confident user a depleted core
pool means cooldown has rightly exhausted the genre — dumping the last same-genre
titles re-traps them. Confident users take the proportional path: cap core at its
ratio, fill the rest with adjacent (same-feeling) first, keep a wildcard reserve
for the 15-25% discovery band.
**Why:** after 100 swipes a documentary lover was landing at 62% documentary
purely because cooldown shrank the pool below the thin-pool threshold.

## Validation
`backend/sim_personas.py` builds a matured (100-swipe) feed per persona and reads
`feed_meta.diversity`; assertions are gated on catalogue supply so thin/niche
genres aren't penalised for variety they can't provide.
