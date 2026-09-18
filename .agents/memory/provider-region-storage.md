---
name: Provider region-keyed availability
description: How streaming availability is stored/served per region, the trust rules, and why Discover refuses cross-region data
---

# Region-keyed provider availability

Streaming availability is region-specific and stored two ways that must stay
consistent: `providers_by_region.{REGION}` is canonical; the legacy flat fields
(`available_on/rent_on/buy_on`, `providers_region/fetched/fetched_at/...`) are a
mirror of **DEFAULT_REGION only** (env `TMDB_REGION`, default GB).

**Rule:** a write for `region == DEFAULT_REGION` updates BOTH stores; a write for
any other region updates ONLY `providers_by_region`.

**Why:** the in-memory CATALOG + recommendation engine assume a single consistent
region in the flat fields. Mirroring non-default regions there would flip-flop the
engine and corrupt Discover. Keep flat = GB; serve other regions from the
region-keyed store.

**How to apply:** never read provider arrays directly for ranking/filtering. Always
go through `resolve_region_providers(movie, region)` — it prefers the region entry,
falls back to flat fields only when they truly represent that region, else returns
`region_matched=False` (caller offers on-demand refresh).

# Discover trust rules (non-obvious)
- Subscription matching and the quality gate are **region-resolved**, not flat. A
  title on Netflix GB is NOT counted as watchable for a US user unless we hold US
  data showing it. Consequence: for a non-default region with no pre-loaded data,
  Discover is intentionally near-empty until that region is enriched — this is the
  desired trust tradeoff, not a bug.
- The gate's "has this been fetched?" check must be **region-scoped**, not the
  global flat `providers_fetched` flag. On-demand enrichment for a non-default
  region sets only `providers_by_region.<REGION>`; trusting the global flag would
  wrongly reject those valid region-keyed records.

# Fetch integrity
A failed/rate-limited fetch must NEVER be recorded as fetched or empty_confirmed —
only a genuine TMDB response with zero providers is a real "confirmed empty".
`fetch_providers` returns an `ok` flag so callers can tell these apart.

# Alias normalization
`normalize_provider` collapses service variants (Max/HBO→hbo_max, Amazon
Video→prime_video, Apple TV(+)→apple_tv, …). **Flatrate keeps only known
subscription services** — unknown flatrate storefronts (e.g. "YouTube TV") are
dropped so they can't pollute subscription matching. Rent/buy keep the normalized
raw name (Google Play, Sky Store, etc. are legitimate there).

# TV seasons
TMDB has no per-season watch-providers feed; seasons inherit show-level
availability, marked so it's never mistaken for fetched per-season data.
