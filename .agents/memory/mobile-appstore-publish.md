---
name: App Store publish from subdirectory Expo app
description: How Replit App Store publishing finds the Expo project when the app lives in mobile/ under a Python root
---

# App Store publish — Expo app in `mobile/`

- Replit's App Store publish (Launch/EAS) scans for a supported framework at the **artifact root**, not automatically at `mobile/`. With a Python repo root it fails with "no supported framework was found", and if it later runs prebuild from the wrong root, EAS throws `ConfigError: ... module 'expo' is not installed`.
- **Fix:** register the folder as a mobile artifact via `mobile/.replit-artifact/artifact.toml` containing `kind = "mobile"` (+ title). Omit `id` → artifact id resolves to the folder path.
- `verifyAndReplaceArtifactToml` cannot CREATE a new artifact.toml (rejects kind/version changes vs an empty file); writing the file via shell works and the platform picks it up ("Added artifact" update) within ~a minute.
- EAS uploads the git archive: `mobile/package.json`, `app.json`, and `package-lock.json` must be committed.
- `npx expo prebuild` locally mutates `package.json` scripts (`expo start` → `expo run:*`) and creates gitignored `ios/`; revert/remove after a local prebuild test.

- Workspace npm uses `http://package-firewall.replit.local/npm/` as registry → lockfile "resolved" URLs are unreachable from Expo's builders. Regenerate with `rm package-lock.json && npm i --package-lock-only --registry=https://registry.npmjs.org` **with node_modules temporarily moved aside** (otherwise npm reuses local metadata and emits no resolved URLs at all). Commit the lockfile.
- `getExpoLaunchLogs()` returning "no Expo Launch session" while the user sees EXPO_UNAUTHORIZED ⇒ the flow never authenticated with Expo; no build ever started server-side.
- In failed Launch logs, `npm warn exec ... expo@<new SDK>` immediately before `expo is not installed` proves `npx` ran outside the registered app root: from `mobile/`, it resolves the committed SDK-local Expo CLI instead of downloading a newer fallback.
- After any clean npm reinstall, run SDK-local `npx expo install --fix` and `npx expo-doctor`; loose semver ranges can resolve React/React Native patches that do not match the current Expo SDK.
- "Failed to download the file: 404" at publish with NO new Launch session in `getExpoLaunchLogs()` ⇒ the Replit→Expo archive handoff failed (upload failed or signed URL expired) before any EAS build started. Nothing project-side to fix; each Publish-pane retry re-archives and re-uploads with a fresh URL. Persistent recurrence = Replit platform issue (support).
- xcodebuild "exit status 65 / (N failures)": the fastlane tail hides the real errors — scan the full Launch `logs` array for `❌` entries to find the Swift compile errors. A beta native module in dependencies (e.g. `@expo/ui` beta) can fail to compile against the SDK's expo-modules-core even when **never imported** in app code; expo-doctor does not catch this. Remove unused native deps before publishing.

**Why:** publish failures looked like project misconfig but were root-detection; app config itself was complete.
**How to apply:** any future "no supported framework" / "expo not installed" publish error → check artifact registration + committed lockfile first.
