---
name: Quality gate must not hard-reject unknown runtime
description: Why catalog_quality_gate gives runtime=None films benefit of the doubt instead of excluding them
---

# Movie runtime gate

`catalog_quality_gate` (backend/core.py) must only reject movies with an
**explicit non-positive** runtime (==0, a TMDB placeholder/unreleased stub).
A `runtime is None` movie has simply not been runtime-backfilled and must
**pass** (subject to the other gates).

**Why:** the catalog is overwhelmingly un-backfilled for runtime (almost all
movies had `runtime=None`). A gate that rejected `None` silently excluded the
entire films half of the catalog from Discover/recommendations, so feeds were
100% TV. Users reported "never see a single film, just terrible serious TV."
This is a silent pool-collapse failure mode: one missing-field check on a
sparsely-populated field can wipe out a whole content type.

**How to apply:** the quality gate's stated philosophy is "unknown fields get
the benefit of the doubt." Any per-field check added here must honour that —
gate on *explicit bad values*, never on *missing/None*. Watchability is already
guaranteed by the poster + overview + status + junk-floor + region-provider
gates, so a None-runtime film that clears those is genuinely showable. Runtime
backfill is data hygiene, not a correctness dependency for the gate. If you ever
see a feed dominated by one `type` (all-TV or all-movie), check the quality gate
for a field-presence reject before assuming catalog exhaustion.
