---
name: Mobile launch readiness
description: Durable facts/decisions from the iOS App Store prep of the Expo app
---
- Production web/API origin is **https://watchsmart.uk** (VM deploy, public). Legal pages: /privacy, /terms — mobile links live in `mobile/src/constants/links.ts`.
- expo-secure-store throws on web: token storage has a Platform.OS==="web" localStorage fallback (Expo web preview/testing only; native uses keychain). Don't remove it or web e2e breaks.
- Backend CORS defaults include localhost:8080 for the Expo dev server — additive, dev-only; native builds don't need CORS.
- Discover deck delayed setTimeout state mutations must be gen-guarded (genRef) or tab switches corrupt stack/rewind history. **Why:** review found stale timers slicing the new tab's stack.
- On web preview, nested Pressables render nested <button> hydration errors — keep overlay buttons as siblings of the card Pressable, absolutely positioned.
- Project pinned to **Expo SDK 54** because the public App Store Expo Go (check via iTunes lookup of host.exp.Exponent) only runs SDK 54 — do NOT bump expo/RN without confirming Expo Go supports it. SDK 54 quirks: expo-image/expo-status-bar have no config plugin (keep them out of app.json plugins); spread `StyleSheet.absoluteFillObject`, not `absoluteFill`.
- App Store pack lives at mobile/docs/app-store-submission.md; bundle id com.watchsmart.app, v1.0.0 build 1, ITSAppUsesNonExemptEncryption=false. No analytics/crash SDK bundled in v1 (PostHog task was cancelled) — privacy disclosures reflect that.
