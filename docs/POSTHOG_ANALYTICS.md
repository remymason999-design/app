# WatchSmart product analytics

This document describes the current client-side implementation. Canonical
events below are implemented across the available web and native flows; events
whose product surface exists only on one client are marked accordingly.
Properties are allowlisted, bounded, and omitted when unavailable.

## Architecture

There is one analytics boundary per client:

- Web: `frontend/src/lib/analytics.js`, initialized by
  `frontend/src/observability.js`.
- Native: `mobile/src/lib/analytics.ts`, initialized in
  `mobile/src/app/_layout.tsx`.

Screens call the boundary rather than configuring PostHog directly. Both
boundaries no-op without a key, swallow SDK/network errors, avoid awaiting
analytics on product-critical paths, disable automatic capture, add
`platform`, `environment`, `app_version`, and `build_number`, bound payload
depth/size, recursively strip sensitive and free-text keys through a central
sanitizer, and deduplicate rapid retries. Existing backend impression/action
and community-learning records are unchanged.

## Configuration

Configure these through Replit Secrets/environment configuration; do not commit
them:

| Client | Project key | Host | Environment |
| --- | --- | --- | --- |
| Web | `REACT_APP_POSTHOG_KEY` | `REACT_APP_POSTHOG_HOST` | `REACT_APP_ANALYTICS_ENV` |
| Expo | `EXPO_PUBLIC_POSTHOG_KEY` | `EXPO_PUBLIC_POSTHOG_HOST` | `EXPO_PUBLIC_ANALYTICS_ENV` |

The public project ingestion key is appropriate for a client SDK. Never use a
personal, private, or admin API key. The WatchSmart project uses EU PostHog,
and both analytics wrappers default to `https://eu.i.posthog.com`; deployments
should still set both host variables explicitly. Environment is otherwise
derived from `NODE_ENV` on web and `__DEV__` on native. Use `development`,
`preview`, or `production` deliberately.

## Event dictionary

All events carry `platform`, `environment`, `app_version`, and `build_number`.
Identified events also carry `internal_or_test`, derived from the backend
`analytics_internal` marker. The stable internal WatchSmart ID is used for
identity; email is never sent.

### Lifecycle and onboarding

| Event | Properties | Trigger |
| --- | --- | --- |
| `app_opened` | none | Web app mount or native app layout |
| `screen_viewed` | `screen_name`, `previous_screen`, `source` | Navigation route change |
| `onboarding_started` | `source` where available | Onboarding flow opens |
| `onboarding_step_completed` | `step`, aggregate selection counts, `country` where available | Successful onboarding step |
| `onboarding_title_feedback` | `content_id`, `media_type`, `feedback`, `position` | Onboarding title feedback submitted |
| `onboarding_completed` | aggregate counts where available | Successful completion |

### Recommendations

| Event | Properties | Trigger |
| --- | --- | --- |
| `recommendation_impression` | `content_id`, `impression_id`, `media_type`, available `genres` and `provider`, `feed_type`, structured `recommendation_source` from `_signals.source`, separate `reason`, `session_impression_number`, `user_interaction_count`, `interaction_bucket` | Active visible Discover card |
| `recommendation_saved` | Recommendation context and `time_visible_ms` where available | Successful save |
| `recommendation_skipped` | Recommendation context and `time_visible_ms` where available | Successful skip |
| `recommendation_watched` | Recommendation context and `time_visible_ms` where available | Successful watched action |
| `recommendation_rewound` | Recommendation context and reverse-action timing where available | Successful rewind |
| `watched_feedback_submitted` | `content_id`, `impression_id` where available, `media_type`, `feedback`, `interaction_bucket`, recommendation context | Submitted watched feedback (native Discover and native title details) |

`interaction_bucket` is `0-5`, `6-10`, `11-25`, `26-50`, `51-100`,
`101-200`, or `200+`. Impressions are emitted only after a card is active and
visible, never when fetched, cached, or prefetched. Native impressions require
the focused Discover route and an active AppState. Hidden state resets the
presentation marker, so returning focus records one new event for the genuine
presentation without duplicating rerenders. Native also records the
visibility-start timestamp; it is operational timing context, not location.
`recommendation_source` and `reason` remain separate properties; neither is
derived from title text. On native, the interaction stage comes from the
authoritative backend `post_onboarding_interactions` user field. A rewind
returns to a visible card and creates a fresh impression for that presentation.

### Titles, search, and watchlist

| Event | Properties | Trigger |
| --- | --- | --- |
| `title_details_viewed` | `content_id`, `media_type`, `impression_id`, `source` | Detail loaded |
| `similar_title_selected` | `content_id`, `media_type`, `source` | Similar title selected |
| `provider_selected` | `provider`, `content_id`, `media_type`, `source` | Provider opened from web title details |
| `share_started` | `content_id`, `media_type`, `source` | Share flow starts |
| `search_performed` | `result_count`, aggregate filters | Search returns results |
| `search_no_results` | `result_count`, aggregate filters | Search returns no results |
| `search_result_selected` | `selected_content_id`, `selected_position` | Result opened |
| `watchlist_viewed` | none | Watchlist becomes visible |
| `watchlist_item_added` | `content_id`, `media_type` where available, `source`, `watchlist_size` | Successful add (not watched-history mutation) |
| `watchlist_item_removed` | `content_id`, `media_type` where available, `source`, `watchlist_size` | Successful removal (not watched-history mutation) |
| `watchlist_item_opened` | `content_id`, `media_type`, `source`, `watchlist_size` | Item opened |

Raw search text, share-sheet contents, and title text are not sent.

### Friends, compare, savings, and providers

| Event | Properties | Trigger |
| --- | --- | --- |
| `friends_screen_viewed` | none | Friends screen opens (web and native) |
| `friend_code_shared` | `source`, safe result/status | Friend code share starts |
| `friend_request_sent` | safe result/status | Request succeeds |
| `friend_request_accepted` | safe result/status | Acceptance succeeds |
| `friend_compare_opened` | `compare_mode` | Compare opens |
| `friend_compare_tab_viewed` | tab | Compare tab changes |
| `friend_overlap_item_opened` | `content_id` | Overlap item opens (web and native compare) |
| `savings_screen_viewed` | none | Savings screen mounts/opens |
| `savings_recommendation_viewed` | position where available | Savings recommendation reaches the visible viewport (native) |
| `savings_action_started` | source | Savings action starts (native) |
| `provider_preferences_viewed` | source | Provider preferences opens (native) |
| `provider_added` | provider, provider_count, source | Provider added (native) |
| `provider_removed` | provider, provider_count, source | Provider removed (native) |

Savings visibility events are based on viewport visibility, not API load,
response, or cache completion.

Compare may include aggregate counts (`overlap_count`,
`shared_watchlist_count`, `recommended_for_both_count`) but never the other
person's name, email, messages, or unnecessary identifier.

### Supplemental operational events

The implementation also emits `account_created`, `login`, `logout`,
`session_expired`, `account_deleted`, `tutorial_completed`, `feed_loaded`,
`filter_changed`, `first_discover_action`, `title_trailer_opened` (web),
`watchlist_progress_updated` (native), and `friend_removed` (native). These
are supplemental operational events. Deprecated generic wire events are not
emitted.

## Identity, privacy, and exclusion

`identify()` uses `user_id`/`id`; email is never a distinct ID or event
property. On web, initial identification compares the authenticated ID with
PostHog's persisted distinct ID and resets before switching when they differ.
Native `switchIdentity` compares both the SDK's persisted `getDistinctId()`
and its in-memory identity, resets before identifying when either differs, and
is used by every login/register and recovery flow before its auth event is
captured. Native `AuthContext` records the identity ref before `setUser`, so
the resulting user-state effect does not reset and re-identify the same
transition. Account switching resets before identifying the new account.
Logout, deletion, and authoritative expiry reset PostHog identity. Internal/test
accounts carry `internal_or_test=true`; anonymous events omit that property.

Never send passwords, access/refresh tokens, auth headers, names, email
addresses, private messages, review text, raw search text, precise location,
or share-sheet payloads. Movie titles are intentionally omitted even where an
upstream measurement brief listed `title` as optional.

## Session replay

Web disables PostHog autocapture and session recording. Sentry's web replay
sample and error-replay rates are both zero. Native PostHog replay is not
enabled. Enabling native replay requires compatibility and privacy validation
with the installed Expo/RN versions, an EAS development build, and
device/TestFlight validation.

## Error tracking

Web continues to use Sentry through `frontend/src/observability.js`; PostHog is
not a duplicate web crash-reporting pipeline. Native PostHog captures uncaught
JavaScript exceptions and unhandled promise rejections. Its `before_send` hook
removes messages, stack details, and nonessential properties, retaining only
exception type plus SDK/session and non-sensitive app context. Console capture,
exception breadcrumbs, and native crash capture are disabled. Native crash
capture would require validating the optional native plugin and shipping a new
EAS/TestFlight build; it is not enabled by this change. Analytics failures are
swallowed. Any future error
context must be limited to screen, operation, platform, and version.

## Feature flags and experiment readiness

Both boundaries expose safe `isFeatureEnabled`, `getFeatureFlag`, reload, and
subscription helpers. No production behavior or experiment is currently
controlled by a PostHog flag. Candidate future flags include
`new_onboarding`, `recommendation_experiment`, `friends_compare_v2`,
`watchsmart_plus`, and `new_discover_ui`; do not activate them in this task.
Monetization event names remain future architecture only; payments are not
implemented.

## Trigger locations

- Auth/lifecycle: `AuthContext`, app/layout lifecycle, deletion, and API expiry.
- Discover: `frontend/src/pages/Discover.jsx` and
  `mobile/src/app/(tabs)/discover.tsx`.
- Details: `frontend/src/pages/MovieDetail.jsx` and
  `mobile/src/app/title/[id].tsx`.
- Onboarding/tutorial: web onboarding pages/components and native onboarding
  routes/tutorial.
- Search/library: web `Search.jsx`/`Watchlist.jsx` and native tabs.
- Friends/compare: web `Friends.jsx`/`Compare.jsx` and native friends/compare.
- Savings/providers: `Savings.jsx`, native savings, profile, and filter sheets.

## Unavailable or unimplemented properties/events

The current feed payload does not reliably expose `quality_tier`,
`quality_score`, `recommendation_score`, `personalisation_score`, `confidence`,
TMDB numeric ID, original language, rank, or position. These are omitted rather
than invented. Movie titles are omitted for privacy; search terms and friend
identity details are unavailable by design. `session_impression_number` and
`user_interaction_count` are included when the active client/user context
provides them, while some `time_visible_ms` values are omitted on flows where
the UI cannot provide them.

`watched_feedback_cancelled` is not emitted because cancellation is not
submitted sentiment. The canonical taxonomy is implemented; savings
recommendation/action and provider add/remove are emitted on native where
those flows exist; native provider rows are passive and do not emit
`provider_selected`. Provider selection is emitted by web title details.
Compare-overlap is emitted by both web and native Compare screens. This is
platform coverage, not an unimplemented wire event.
If a future API exposes an unavailable field, add it to both clients' allowlist
together.

## Safe event additions

1. Add the snake_case event to both `EVENTS` dictionaries.
2. Define allowlisted, privacy-reviewed properties here.
3. Emit only after the product operation succeeds.
4. Add dedupe and reversal semantics where applicable.
5. Add web and native trigger coverage together.
6. Run the focused web analytics contract tests (presentation dedupe and
   re-presentation, bucket boundaries, persisted identity reset, and privacy
   stripping), web build, native TypeScript checks, existing tests, and
   `git diff --check`.
7. Verify with synthetic internal development data in the EU project only.

## Build and verification notes

The PostHog client is a runtime dependency. Web changes ship with the web
build/OTA equivalent. Native package or replay changes require an EAS
development build and likely a new TestFlight build, but not automatically an
App Store resubmission. Confirm with `expo-doctor` and repository export checks.

To verify in PostHog:

1. Select the EU project and open **Activity → Live events**.
2. Set the environment filter to `development` and ensure internal/test events
   are visible only for validation.
3. In a clean web session, observe `app_opened` and `screen_viewed`.
4. Sign in with a test account and confirm the distinct ID is the internal
   WatchSmart ID, not email.
5. Open Discover and wait for a card; confirm one
   `recommendation_impression`, then save or skip and confirm the matching
   action event with content/impression context and no title/query.
6. Log out, sign in as a second test account, and confirm a new distinct ID
   with no preceding account's events attributed to it.
7. Repeat representative checks in an Expo/TestFlight build for native.
8. Confirm PostHog accepts events without a key by running the app with the key
   unset; navigation and mutations must still work.