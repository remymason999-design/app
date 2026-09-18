# WatchSmart — App Store Submission Pack (v1.0.0)

Draft launch information for the first iOS TestFlight / App Store release.
Placeholders are marked `TODO(owner)`. **Never commit real passwords to this file.**

---

## App identity

| Field | Value |
| --- | --- |
| App display name | WatchSmart |
| Expo project name | WatchSmart |
| Expo slug | `watchsmart` |
| iOS bundle identifier | `com.watchsmart.app` |
| Version | 1.0.0 |
| iOS build number | 3 |
| Production API | `https://watchsmart.uk` (HTTPS, set via `EXPO_PUBLIC_API_URL` at build time) |
| Deep-link scheme | `watchsmart://` |

## App Store listing

- **App name:** WatchSmart
- **Subtitle (30 chars):** Swipe. Watch. Save money.
- **Promotional text (170 chars):** Swipe through films and TV shows picked for your taste, see exactly which of your streaming services include them, and track what your subscriptions really earn.
- **Full description:**

  WatchSmart learns your taste in films and television, then shows you one great recommendation at a time — swipe right to save it, left to skip, up to mark it watched. Every card tells you which of your streaming services already include the title, so you never pay twice to watch.

  • Personalised Discover feed that learns from every swipe
  • "Included with…" badges for your UK streaming services
  • Watchlist that syncs with the WatchSmart web app
  • Compare taste and watchlists with friends
  • Savings view showing what your subscriptions deliver
  • Search films, TV programmes and people

  Film and TV data provided by TMDB. WatchSmart is not endorsed or certified by TMDB, and is not affiliated with any streaming service.

- **Keywords (100 chars):** movies,tv,streaming,watchlist,recommendations,netflix guide,what to watch,swipe,film,uk
- **Primary category:** Entertainment
- **Secondary category:** Lifestyle
- **Copyright:** © 2026 WatchSmart. TODO(owner): legal entity name if different.

## URLs

- **Support URL:** https://watchsmart.uk/privacy (TODO(owner): dedicated support/contact page if preferred)
- **Marketing URL:** https://watchsmart.uk
- **Privacy Policy URL:** https://watchsmart.uk/privacy
- **Terms of Use URL:** https://watchsmart.uk/terms

## Age rating considerations

- App shows film/TV artwork and metadata (incl. certifications up to 18/R) but no playable video content.
- Suggested answers: infrequent/mild mature or suggestive themes (film artwork/synopses); no gambling, no user-generated public content (friends are private connections), no unrestricted web access.
- Expected rating: 12+.

## App Review information

- **Contact first name / last name:** TODO(owner)
- **Phone:** TODO(owner)
- **Email:** TODO(owner)
- **Sign-in required:** Yes.
- **Demo account:** TODO(owner) — create a dedicated reviewer account in production (complete onboarding once so the reviewer sees a populated feed). Username: `TODO` Password: supply in App Store Connect only — never in this repo.

### App Review notes (draft)

> WatchSmart is a personalised film/TV recommendation app. After signing in with the demo account:
> • **Discover** (first tab): swipe cards right to save, left to skip, up to mark watched; the arrow button reverses the last action. Tap a card for full details, UK streaming availability and similar titles.
> • **Watchlist** (second tab): saved titles; tap to open, remove or mark watched.
> • **Friends** (third tab): send/accept friend requests and compare watchlists.
> • **Savings** (fourth tab): shows the user's selected streaming subscriptions and value derived from watched content. Figures are informational only — nothing is sold in-app and there are no in-app purchases.
> • **Profile** (avatar, top-right): streaming service preferences, notifications, Privacy Policy/Terms, account deletion, sign out.
> Streaming availability data and artwork are provided by TMDB/JustWatch metadata; WatchSmart has no affiliation with the streaming services shown.

## Data collection disclosure worksheet (App Privacy)

| Data type | Collected? | Linked to identity | Tracking | Purpose |
| --- | --- | --- | --- | --- |
| Email address | Yes | Yes | No | Account creation, auth |
| Name | Yes (optional) | Yes | No | Personalisation |
| User content (swipes, ratings, watchlist) | Yes | Yes | No | App functionality, personalised recommendations |
| Usage data (recommendation impressions/actions) | Yes | Yes | No | App functionality, analytics (first-party) |
| Coarse location | No | — | — | Region is fixed to UK, not derived from device location |
| Contacts, photos, precise location, health, financial data | No | — | — | Not collected |
| Device identifiers (push token) | Yes (if enabled) | Yes | No | Deliver requested account and social notifications |
| Advertising identifier (IDFA) | No | — | — | No ad SDKs; no tracking across apps |

Third-party SDKs: Expo (framework, including `expo-notifications` for optional
push delivery), axios, React Query — none collect data independently. No
PostHog/Sentry SDK is currently bundled in the iOS app (add to this table if
enabled later).

## Permissions

The app requests notification permission only when the user enables push
notifications in Profile. Push is used for friend requests, accepted requests,
and important account updates. Camera/photo permission is requested only if the
user chooses to change their profile photo. The app does not request location
or tracking permission.

## Export compliance

- Uses only standard HTTPS/TLS (exempt). `ITSAppUsesNonExemptEncryption=false` is set in app.json.

## Screenshot checklist (6.9" and 6.5" iPhone required)

1. Discover card with provider pill and action row
2. Title details with UK availability
3. Watchlist
4. Onboarding taste selection
5. Savings screen
6. Friends / compare

## Release notes — 1.0.0

> Welcome to WatchSmart for iPhone!
> • Swipe-to-discover films and TV shows picked for your taste
> • See which of your streaming services include each title
> • Watchlist, friends comparison, and subscription savings
> • Syncs with your WatchSmart web account

## Compliance reminders

- TMDB attribution is displayed in-app (title details + profile) as required by TMDB terms.
- Streaming provider info is metadata only — no partnership claimed.
- Account deletion is available in-app (Profile → Delete account), satisfying Apple's account-deletion requirement.
- No rating prompt in v1.0.0. A later release may add `expo-store-review` after a positive milestone (e.g. 20th save), respecting Apple's 3-prompts-per-year limit.
