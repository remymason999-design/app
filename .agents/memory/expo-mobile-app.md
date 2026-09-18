---
name: Expo mobile app (mobile/)
description: How the native WatchSmart Expo app is wired to the existing backend and run on Replit
---

- Run via workflow "Start Mobile": `cd mobile && EXPO_PUBLIC_API_URL="https://$REPLIT_DEV_DOMAIN" npx expo start --port 8080`. Replit workflows don't allow port 8081 — use 8080, console output type. Never run `npx expo` as a one-off shell command.
- Backend needs no changes: it already returns `{user, access_token, refresh_token}` from login/register and accepts Bearer auth; refresh = POST /api/auth/refresh with the *refresh* token as Bearer. Mobile stores tokens in expo-secure-store (`ws_access_token`/`ws_refresh_token`), axios interceptor does dedup'd 401 refresh-and-retry using raw axios (not the intercepted instance).
- Route gating: every layout that assumes a user must short-circuit on `loading` (spinner) before redirecting — direct deep links can render tabs before session restore, so no non-null assertions on `user`. Auth group redirects logged-in users to tabs.
- Brand assets: `watchsmart-logo.png`/`watchsmart-mark.png` in frontend/public/brand are portrait 1179x2556 (screenshot-shaped) — unusable for headers. Use `watchsmart-mark-trim.png` (732x594) for splash/login/header marks; header wordmark is text ("Watch" white + "Smart" amber).
- Expo Launch publishing is iOS-only on Replit; Google Play is unsupported — user must build/submit Android via EAS outside Replit.
