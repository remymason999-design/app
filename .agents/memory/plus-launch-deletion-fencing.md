---
name: Per-user delivery locking: liveness re-check and idempotency windows
description: Two durable pitfalls in consent-gated notification/delivery workflows built on a shared per-user lock — deletion races and provider idempotency-key expiry.
---

## A lock only serializes; it doesn't re-check liveness
A per-user lock (acquire-then-release around a write) only stops two operations from *interleaving*. It does not stop a write that acquires the lock *after* another operation (e.g. account deletion) released it from still creating/upserting a row for a user or state that's no longer valid.

**Why:** an account-deletion race let an interest/opt-in write, or a notification dispatch step, land after deletion had already removed the same rows, resurrecting "deleted" data.

**How to apply:** any write that touches data also owned by a destructive per-user operation (like account deletion) must, after acquiring the shared lock: re-check the record/user is still in the expected state, THEN write, holding the lock across both the write and any linked audit/event write — not just the primary write.

## Bound retries to inside the provider's idempotency-key window, not "however long owner reruns it"
An external provider's idempotency key (e.g. email API dedup) has a finite retention window. If a delivery is left in an ambiguous "retry" state on error, retrying it must be bounded to a safety margin strictly inside that provider window. Retrying after the provider's window has elapsed is no longer deduplicated and can send a duplicate.

**Why:** "retry-safe" delivery isn't achieved just by using an idempotency key — an indefinitely-retryable ambiguous delivery becomes unsafe once the key's retention expires.

**How to apply:** anchor the deadline to the delivery's original creation time (not last-attempt time), and once past the safety margin, mark the delivery terminal (e.g. "failed") instead of retrying, requiring manual reconciliation via the provider's dashboard.
