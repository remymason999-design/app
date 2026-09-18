---
name: Feed anti-repetition passes (feeling vs cluster/franchise)
description: Why feeling spacing must win over genre-cluster/franchise spacing when de-streaking the Discover feed.
---

# Feed de-streak ordering: feeling wins, cluster/franchise is best-effort

The Discover feed is de-streaked with TWO passes in a fixed order:

1. Feeling spacing first — even-distributes the dominant *feeling* (effective tone
   group, not raw card.tone). This is the **hard, sim-critical guarantee**: the
   persona sim asserts the tail feeling-streak stays within a supply-aware floor.
2. Cluster/franchise spacing second — caps consecutive genre-cluster and franchise
   runs at 2, but ONLY by swapping cards that share the SAME feeling, so the
   feeling sequence is provably unchanged.

**Why this order / same-feeling-only swaps:**
A single unified greedy that weights all three caps together was tried and
REGRESSED a near-mono-feeling persona (it ballooned the feeling tail streak far
past the allowed bound). Even-distribution of the dominant feeling is genuinely
better than a one-pass greedy on skewed-feeling supply, so feeling spacing must be
computed first and never disturbed.

**How to apply:**
- Cluster/franchise spacing is BEST-EFFORT, not guaranteed. When a cluster run can
  only be broken by a differently-felt card (which would regress feeling), leave it.
  On diverse feeds the cap is fully met; on mono-feeling feeds feeling wins.
- Never let the cluster pass swap across different feelings — that breaks the
  invariant that keeps the persona sim green.
- All passes are pure permutations (no filtering) so candidate pools stay
  byte-identical — required by the soft-levers-only rule.
- Catalogue currently has no franchise/collection metadata and no cast metadata, so
  franchise spacing and cast-affinity scoring are largely inert until ingested. None
  keys are treated as unconstrained (benefit-of-doubt).

# Onboarding-preference persistence is checked on learned taste, not the feed

To prove a long swipe session never drifts away from the genres a user onboarded
with, assert on the **learned top genres** (taste snapshot), which is
supply-independent. Do NOT gate persistence solely on the matured feed's genre mix:
a mono-niche genre (e.g. Horror, Reality) can show 0% of that genre in the matured
feed purely because fresh unseen supply is exhausted after many swipes — that is
catalogue depth, not preference drift. Any feed-level representation check must be
exempted when the matured feed has no fresh core (top-preference) supply left.
