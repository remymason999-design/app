---
name: Push notification safety
description: Durable privacy and reliability constraints for WatchSmart remote notifications.
---

Push permission is requested only from an explicit Profile control. Consent is
stored per WatchSmart user, not inferred from the operating-system permission,
so logout, opt-out, or a different account on the same device cannot silently
re-enable delivery.

**Why:** OS notification permission survives app logout. Treating that permission
as app-level consent can deliver one account's social or security events after a
shared device signs into another account.

**How to apply:** Bind each Expo token to a stable installation ID and authenticated
user. Keep an installation-only revocation secret so failed logout deregistration
can be retried without a session. Never delete the local revocation state until
the server confirms removal.

Push is supplementary to the authenticated in-app inbox. Payloads contain
generic text and allowlisted route identifiers only; private names and details
remain in the inbox.

**Why:** Lock-screen notifications are visible outside the authenticated app, and
Expo/APNs delivery failures must not break social or account actions.

**How to apply:** Persist the in-app notification first, enqueue push best-effort,
and keep provider calls in a durable outbox worker. Fence queue claims and
account deletion with claim IDs and per-user delivery locks, track per-token
outcomes, bound retries, and reconcile interrupted social transitions
idempotently.