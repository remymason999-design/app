---
name: Async list history restoration
description: Rules for reliable back-navigation restoration on asynchronously loaded lists.
---

When a list opens a detail screen, save its scroll offset together with active
tabs/filters and the current router history-entry key. Restore only when a POP
navigation returns to that same key, and consume the saved state after the
async list content is mounted.

**Why:** Browser-native restoration is inconsistent when a route first renders
a loading state. Saving only an offset can also return users to different
content when tabs or filters reset, while an unscoped session value can affect
a later unrelated visit.

**How to apply:** Use this pattern for list → detail → back journeys whose list
data loads asynchronously. Include all controls that determine which items are
rendered, and test a non-default view as well as the default view.