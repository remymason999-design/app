---
name: WatchSmart brand & Discover controls
description: User-approved brand conventions and Discover swipe-control rules — keep consistent; don't "fix" them back.
---

# Brand
- Palette: bg #05070A, surfaces #0B111A/#111827, primary orange #FF7A18, deep #FF4D00, green #22C55E, text-2 #9CA3AF, border #243041. Font: Inter.
- The Tailwind `amber` token is intentionally repointed to the primary orange (#FF7A18 / 600=#FF4D00) so the many existing `bg-amber`/`text-amber` usages adopt the brand without per-file churn.
  **Why:** lets a global retheme cascade through legacy classes. Do NOT revert `amber` to yellow; `saving` (#F59E0B) is the separate amber-ish token.
- Brand mark is the "two overlapping glossy orange cards forming a W" duotone (light orange top → deep orange bottom). Uses official rendered PNG assets in `frontend/public/brand/` (mark/logo/icon/favicons), NOT SVG; Logo.jsx renders `<img>`. attached_assets/ is not web-served — copy into public/.

# Discover controls (user-approved — do not revert to old layout)
- Bottom action row is exactly four: **Rewind · Skip · Watched · Save**. There is deliberately NO separate Undo button — Rewind *is* the undo. (Mockup shows "Undo"; the approved decision replaces it with Watched.)
- Swipe directions: left = skip, right = save, **up = watched** (not down).
- **Rewind** must both restore the last card to the top AND reverse the backend action, else the title stays stuck saved/skipped/watched. Reverse mapping: save→unsave, skip→unskip, watched→unwatched (a dedicated `unskip` backend action mirrors the existing unsave/unwatched).

**Why:** user explicitly chose Rewind-over-Undo and up=watched during the brand redesign.
