# WatchSmart+ Coming Soon foundation

WatchSmart+ is a preview only. The server-owned configuration currently
returns:

```text
plus_visible=true
plus_interest_enabled=true
subscriptions_enabled=false
ads_enabled=false
affiliate_tracking_enabled=false
sponsored_content_enabled=false
```

## Interest

`plus_interest` stores one sparse record per authenticated `user_id` with
`interested`, `first_interested_at`, `latest_interested_at`,
`latest_removed_at`, `source_screen`, and `updated_at`. A unique `user_id`
index makes the record cross-device and prevents ownership collisions.

PUT is idempotent: a repeated opt-in does not create another conversion or
change the first timestamp. DELETE is idempotent: a repeated removal does not
create another removal event. The server derives user identity and timestamps.
Account deletion removes both the interest record and its event records. The
interest state remains authoritative if analytics delivery fails.

## Analytics contract

The allowed events are `plus_card_viewed`, `plus_card_clicked`,
`plus_preview_viewed`, `plus_interest_clicked`, and
`plus_interest_removed`.

- `plus_card_viewed` means at least 50% of the Profile card was visible during
  a visit; it is emitted once per mounted visit.
- `plus_preview_viewed` means the authenticated preview route was entered once.
- `plus_interest_clicked` and `plus_interest_removed` are emitted by the
  server only after a successful state transition.
- Event IDs are unique and retries are deduplicated.

Events contain only internal `user_id`, server time, platform, source screen,
optional app version, environment, a test marker, and coarse signup-period and
onboarding cohorts. DOB, email, names, URLs, IP addresses, user agents,
search text, and tokens are not collected. On web, configured PostHog is used
through the existing observability wrapper; when it is not configured, the
same calls use the authenticated first-party envelope endpoint. Mobile uses
that endpoint. A caller never sends the same event to both sinks.

The denominator for card view rate is unique users (or visits when counting
repeat mounted Profile visits) who viewed the card; the preview denominator is
unique preview visitors. Interest conversion is unique users with a successful
interest event divided by unique preview visitors. Removals are reported
separately and do not erase historical conversion events. Event and interest
records are deleted with the account.

## Reproducible funnel report

`backend/scripts/plus_funnel_report.py` is a read-only bounded Python
aggregation. It uses `find()` rather than a complex Mongo aggregation pipeline
so it also works against managed Mongo deployments:

```bash
python backend/scripts/plus_funnel_report.py --days 90
```

It prints unique view/preview users, successful interest additions and
removals, plus source and signup-period breakdowns. It does not create a
dashboard or mutate data.

## Future safeguards

## Launch notification workflow

Launch delivery is disabled by default. An authenticated administrator must
explicitly approve the fixed `watchsmart-plus-launch` campaign with
`PUT /api/admin/plus-launch/approval` before any dispatch can run. Approval can
be revoked at the same endpoint. Email and push are then dispatched separately
with `POST /api/admin/plus-launch/dispatch`; the request names exactly one
channel and a bounded batch size.

Each channel has its own durable delivery record and idempotency key. Completed
or cancelled deliveries are terminal; failed attempts remain retryable. Email
uses the provider idempotency key, while push uses the existing durable Expo
outbox. The dispatcher rechecks both approval and current interest immediately
before sending. The push worker checks interest once more immediately before
contacting Expo, so removing interest also cancels queued push delivery.

Adding, removing, and deleting launch interest all share one per-user delivery
lock with account deletion, held across the full write-plus-event transaction.
This prevents an interest write racing an in-flight account deletion and
leaving orphaned `plus_interest`/`plus_events` rows after the user document is
gone.

Email retries are deduplicated by Resend using the delivery's idempotency key,
which Resend guarantees for 24 hours. A retried "provider_error" delivery is
only retried while it is within a 20-hour safety margin of its first attempt;
once that margin is exceeded the delivery is marked "failed" with outcome
`idempotency_window_expired` and is never retried again, because retrying past
Resend's 24-hour window would no longer be deduplicated and could send a
second launch email. An expired delivery requires manual review in Resend's
dashboard rather than an automatic resend. Push delivery inherits the
existing Expo outbox's at-least-once guarantee: Expo has no request-level
idempotency, so a crash between Expo accepting a push and the local delivery
record being persisted can cause a duplicate push to the same device on lease
recovery. This is an accepted, pre-existing limitation of the shared push
pipeline, not something specific to the launch campaign.

`GET /api/admin/plus-launch` returns campaign state and aggregate counts by
channel, status, and outcome. It does not return names, email addresses, push
tokens, or individual profiles. Push outbox outcomes are reported separately
from campaign enqueue outcomes, including cancellation, no-device, retry, and
failure states. Account export includes the user's own delivery
records, and account deletion removes them. Users can continue to remove launch
interest with `DELETE /api/monetization/plus/interest` before delivery.

Account tier/status and feature access are resolved centrally with legacy
defaults of `free`/`none`; launch interest grants no entitlement. The
optional sponsorship contract defaults to non-sponsored and is separate from
organic score fields. If sponsorship is ever enabled, the visible label must
be `Sponsored`. No current feature checks these future access fields.

Outbound provider links keep their existing endpoint and destination response.
With affiliate tracking disabled, no click record or new query parameter is
created and the known provider URL opens normally. When enabled in future,
only WatchSmart campaign parameters are added; internal user IDs are never
sent to providers.