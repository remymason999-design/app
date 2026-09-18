---
name: Compare Friends refresh
description: Why Compare Friends uses bounded pages and return-triggered refresh instead of live full-snapshot polling.
---

Compare Friends should request one bounded page at a time, replace the current result set, and refresh only when the user returns to the page.

**Why:** Full-snapshot polling caused avoidable API traffic and whole-grid rerenders; a changing sync timestamp made identical content look new, contributing to scroll instability and worsening performance on long lists.

**How to apply:** Keep tab, friend, filter, and page in client state; deduplicate by stable title ID; cancel superseded requests; refresh on focus or visibility return rather than on an idle timer.