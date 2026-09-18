---
name: Discover layout + bottom nav
description: Current Discover card/action-row/nav layout decisions after the July 2026 polish (backdrop card, action row below card, full-width fixed nav, watchlist badge).
---

# Discover layout (swipe-first, card is hero)

- Header is intentionally minimal: bold "Discover" left, Search + Filters icon buttons right. No greeting/logo/avatar/notification/full-search-bar. Filters live ONLY in the header (removed from the tab rail).
- Profile is a 5th BottomNav item (Discover/Watchlist/Friends/Savings/Profile → /profile). Sign Out lives at the bottom of the Profile page (red, low-emphasis text), NOT in the nav.

## Card (July 2026 redesign)
- Backdrop image (`backdrop_url`) is the primary card art; poster is the fallback. Hierarchy: small explanation line → dominant title → metadata row (rating/year/runtime + ≤2 genre tags inline) → 2-line description clamp.
- "Included with {Provider}" emerald pill (data-testid `provider-included-badge`) shows when the title is on one of the user's subscriptions — a key differentiator, keep visible.

## Action row (Rewind/Skip/Watched/Save)
- Sits in normal flow BELOW the card, not overlapping it (the old straddle-the-edge design was replaced). Rewind is styled slightly more prominent (border) than before; all targets ≥44px.
- Content column carries bottom padding (~4.25rem) so the row clears the fixed nav. Up-swipe = watched; Rewind reverses the last action via unskip/unsave/unwatched.

## BottomNav
- Full-width fixed bottom bar (border-t, safe-area padding), active tab = amber + top indicator line. The old floating glass pill (and its pointer-events wrapper gotcha) is gone.
- Watchlist tab shows an unseen-saves badge (99+ cap). Backend: per-user `watchlist_unseen` counter — $inc only on NEW saves, decrement floor-0 on unsave, cleared by POST /user/watchlist-seen when Watchlist mounts. Frontend updates optimistically via setUser; save toast removed (badge is the feedback).

## Swipe deck depth
- Background cards (stackPos 1,2) are offset down a few px, scaled slightly smaller, and faded. Keep subtle.
