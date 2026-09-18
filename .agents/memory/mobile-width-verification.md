---
name: Mobile-width layout verification harness
description: How to verify layouts at real phone widths (375–430px) despite fixed-width (1280px) screenshot tooling
---
Screenshot tooling captures at a fixed 1280px viewport, so responsive phone layouts cannot be checked directly.

**Technique:** serve a same-origin harness page (`frontend/public/viewport-test.html`) that renders the app in four iframes sized to real device viewports (375×667, 390×844, 412×915, 430×932), CSS `transform: scale(0.72)` so all four + the tallest frame's bottom nav fit inside one 1280×720 screenshot. Iframes get their own layout viewport, so media queries/vw behave exactly as on-device.

**Why:** transform scaling changes rendered size only, not the layout viewport — the iframe still lays out at true device width.

**How to apply:**
- Auth: append `?dev_token=<JWT>` to the iframe src — the frontend has a dev-only bootstrap that stores it in localStorage (no-op in production builds).
- Expo web (port 8080) has the same dev-only `?dev_token=` bootstrap in `loadTokens()`, and the root layout skips the launch animation when `dev_token=` is in the URL — otherwise screenshots always catch the splash. First bundle after a Metro restart takes ~30s; warm it with curl to `/node_modules/expo-router/entry.bundle?platform=web&dev=true` before screenshotting, and make sure the backend on 5000 is up or auth CORS-fails.
- Mint a token server-side: `create_access_token(user_id, email)` from `backend/core.py` for any existing user (pick one with data, e.g. saved titles via `user_actions` where `action=='save'`; watchlist is NOT an array on the user doc).
- Harness accepts `?path=/discover&token=…`; screenshot `/viewport-test.html?path=…`.
- Scale >0.72 clips the 932px-tall frame's bottom nav in a 720px screenshot.
