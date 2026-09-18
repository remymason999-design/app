---
name: Discover tabs & content_type filtering
description: How the Movies/TV Shows/New decision tabs map to feed endpoints and why content_type overrides user preference.
---

The Discover decision tabs are For You / Movies / TV Shows / New.

- **For You** and **Movies/TV Shows** are all `/discover`-backed personalised feeds. Movies/TV pass `content_type=movie|tv`; For You passes nothing.
- **New** maps to `/sections/upcoming` (not personalised).
- Backend `/discover` accepts an optional `content_type` query param. When set it **overrides** the user's stored `content_type` by building `feed_user={**user, "content_type": ct}` — so the tab choice always wins. For You (ct=None) honours the user's saved preference. The cache key must include `ct` to keep per-tab feeds isolated.

**Why:** Trending/Upcoming were recommendation *sources*, not user *decision modes*; the spec wanted browse-intent tabs. Reusing `/discover` with a type override (rather than a new endpoint) keeps all personalisation/ranking logic identical across For You/Movies/TV.

**How to apply:** Any per-tab feed behaviour (refill, feed-meta banners, thin-pool rescue) must gate on the set of personalised tabs (for-you, movies, tv), NOT just "for-you". The refill URL must also carry `content_type` or it will contaminate a typed stack with the other type. `invalidate_discover_cache` matches by `user_id` prefix only, so adding tuple elements to the cache key is safe.
