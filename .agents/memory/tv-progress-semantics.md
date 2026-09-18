---
name: TV progress semantics
description: Durable compatibility and truthfulness rules for episode-level viewing progress
---

Episode progress is additive state alongside saved membership, legacy watched state, and watched sentiment. Recording or correcting episodes must not remove a saved show or retrain taste.

**Why:** Existing clients treat saved, watched, completion, and sentiment differently. Conflating them loses watchlist membership or double-applies recommendation learning.

**How to apply:** Keep the legacy season/episode cursor readable, but derive episode counts and completion from stable episode identities. Bulk “through,” season, and currently-available operations may infer episodes only from known non-special season counts. When release-dated episode metadata exists, exclude future episodes; if lazy hydration fails or is partial, completion becomes unknown rather than falling back to future-inclusive season totals. Preserve explicit tick/untick corrections over later bulk writes. If counts are unknown, return an explicit unavailable result rather than manufacturing a percentage, completion, date, or runtime. For Library grouping, an explicit watched-feedback `completed` choice is also authoritative: expose it separately and treat `true` as Completed, while `false` or absence must never manufacture episode progress.