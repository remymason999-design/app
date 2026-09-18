# Mobile-width layout verification — Discover & Watchlist

Date: 2026-07-13 · Task: Verify the new Discover layout on real phone screen sizes

## Method

Screenshot tooling captures at a fixed 1280px viewport, so responsive behaviour was
verified via a same-origin harness (`frontend/public/viewport-test.html`) that renders
the app in four iframes sized to real device viewports — 375×667 (iPhone SE),
390×844 (iPhone 14), 412×915 (Pixel 7), 430×932 (iPhone 15 Pro Max) — scaled 0.72×
so all four fit in one capture. Iframes have their own layout viewport, so media
queries, `vw` units, and flex wrapping behave exactly as on-device. Sessions were
bootstrapped with the existing dev-only `?dev_token=` localStorage helper (no-op in
production builds).

## Results

### Discover (`discover-375-390-412-430.jpg` + live captures)

| Check | 375 | 390 | 412 | 430 |
|---|---|---|---|---|
| Action row (Rewind / Skip / Watched / Save) fully visible, no clipping | PASS | PASS | PASS | PASS |
| Bottom nav full-width, all 5 tabs + labels visible, no overlap with action row | PASS | PASS | PASS | PASS |
| Tab bar (For You / Movies / TV Shows / New) fits on one row | PASS | PASS | PASS | PASS |
| Card title, metadata, description readable; "Included with X" pill intact | PASS | PASS | PASS* | PASS* |

\* At 412/430 the saved artifact caught the card mid-load (skeleton), but the layout
chrome under test (action row, nav, tab bar, card frame) is fully rendered and
unclipped; loaded-card state at these widths was confirmed in live captures during
the session (identical layout, content fills the same card frame).

### Watchlist (`watchlist-populated-375-390-412-430.jpg`)

| Check | 375 | 390 | 412 | 430 |
|---|---|---|---|---|
| Header + count + filter chips + sort dropdown fit without clipping | PASS | PASS | PASS | PASS |
| Two-column poster grid intact, titles/ratings readable | PASS | PASS | PASS† | PASS |
| Bottom nav renders full-width, correct active state | PASS | PASS | PASS | PASS |
| Empty state ("Nothing saved yet" + CTA) centred and unclipped | PASS | PASS | PASS | PASS |

† 412 frame caught mid-load in the saved artifact; grid layout confirmed loaded at
412 in a live capture during the session.

### Nav-covers-content check (code-level)

A top-of-page screenshot cannot show scrolled-to-bottom overlap, so this was
verified in code: both pages reserve clearance below their content for the fixed nav
(~52px + safe area) — `Watchlist.jsx` uses `pb-28` (7rem) and `Discover.jsx` pads by
`calc(env(safe-area-inset-bottom) + 4.25rem)`.

## Conclusion

No clipping, overlap, or readability issues at any target width. No changes to
`frontend/src/pages/Discover.jsx` or `frontend/src/components/BottomNav.jsx` were
required.
