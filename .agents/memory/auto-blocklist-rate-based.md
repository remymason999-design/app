---
name: Auto-blocklist must be rate-based, not skip-volume-based
description: Why language/decade auto-block uses exposure rate + dominance guard instead of a negative-weight threshold
---

Hard auto-blocking a language/decade (enforced as a hard filter in `movie_matches`)
must be **rate + dominance** based, never raw skip-volume / negative-weight-threshold based.

**Why:** A skip is the default swipe-left action. In an English-dominant, modern UK catalogue
a normal user skips mostly English modern titles simply because that is what the catalogue is
made of. A volume/weight-threshold rule therefore auto-blocks the user's own primary language
and recent decades, removing most of the catalogue. Symptom: feed pool collapses after a few
dozen swipes even though filter prefs (subs/content_type/excluded_*) are unchanged. The block
signal is confounded with catalogue composition, not real preference.

**How to apply:** Block a category only when it is a genuine, singled-out aversion: the user has
positive signal somewhere, the category has a real sample of rejections with ZERO positives, and
it is NOT the user's dominant (most-seen) category — so the region's primary language is
structurally protected. Track per-category positive/negative exposure counters. Self-heal on
every action by pulling any blocked category that no longer qualifies (this also clears bad blocks
left by an older rule). Keep signed language/decade weights for *scoring only*, never for the hard block.
