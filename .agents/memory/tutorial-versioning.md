---
name: Tutorial versioning
description: Ensures required tutorial additions reach users who completed an older tutorial.
---

When adding a required web tutorial card, increment the local seen-key version instead of reusing the previous key.

**Why:** Reusing an old completion key silently hides newly added cards from every user who completed the earlier tutorial.

**How to apply:** Version the key only for meaningful onboarding changes, so existing users see the updated tutorial once without being prompted on every release.