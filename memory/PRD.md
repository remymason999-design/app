# Reelm — Product Requirements Document

## Original Problem Statement
Build a modern mobile-first app that helps users discover what to watch across their streaming
subscriptions while saving money. Users sign up/log in, select streaming services they pay
for, and get personalized movie/TV recommendations as a swipeable card stack with save/skip/
watched actions. Each title shows a poster, title, rating, genre, description, trailer, and
"where to watch" links. The app tracks subscription overlap and highlights savings by
suggesting cancellations or rotation. Personalized to user activity. Dark, cinematic,
top-tier UX. Affiliate links + future monetization.

## Architecture
- **Backend**: FastAPI + MongoDB (motor), single `server.py` (+ `movies_seed.py` data file)
- **Frontend**: React 19 + react-router v7 + Framer Motion + Tailwind + Shadcn/UI
- **Auth**: Custom email/password JWT (httpOnly cookies + Bearer) AND Emergent Google OAuth
- **AI**: GPT-5.2 (primary) + Claude Sonnet 4.5 (fallback) via `emergentintegrations` + Emergent LLM key
- **Movie data**: Curated seed of 24 popular titles with TMDB CDN posters/backdrops + YouTube trailer IDs

## User Personas
1. **Subscription-overloaded streamer** — pays for 3-5 services, never watches half the titles, wants to save money.
2. **Indecisive Friday-night browser** — opens 3 apps, scrolls 20 minutes, gives up.
3. **Curious explorer** — wants something genuinely tailored, not algorithmic noise.

## What's been implemented (Feb 2026)

### MVP (iteration 1)
- Authentication: register / login / logout / me, Emergent Google session exchange
- Onboarding: streaming services picker (8 services with prices) + genre picker (14 genres)
- Discover: Framer Motion swipe stack — drag right to save, left to skip; action buttons for skip/watched/info/save
- Movie Detail: poster, rating, runtime, where-to-watch affiliate links, YouTube trailer modal, AI "why you'll love this" via GPT-5.2
- Watchlist (saved) and Profile (toggle services/genres, stats, logout)
- Savings dashboard: monthly + yearly total, per-service activity, overlap count, AI-style cancel/rotate suggestions

### Iteration 2 (Feb 2026, post-MVP)
- **Rebrand:** Reelm → **WatchSmart** (logo, copy, admin email, AI persona)
- **Auth bug fix:** added `Authorization: Bearer` token from localStorage as primary, cookies as secondary — works on Safari / private mode / cookie-blocked browsers
- **CORS:** removed wildcard origin, switched to `allow_origin_regex` to allow credentialed cross-origin
- **Affiliate tracking:**
  - `POST /api/affiliate/click` logs click + returns URL with `utm_source/medium/campaign/content + ref + sub_id`
  - `GET /api/affiliate/me` per-user totals (shown on Profile)
  - `GET /api/affiliate/stats` admin aggregate (total/unique/per-service)
  - `GET /api/affiliate/export.csv` admin CSV download (Content-Disposition attachment) — ready for partnership pitches
- **Custom landing:** poster-fan hero, BETA badge, ambient gradient spotlight, services rail
- **First-run tutorial:** 4-step coachmark overlay with animated gesture demo cards on Discover; replayable from Profile; localStorage persistence
- **Self-learning recommendations:**
  - `user.genre_weights` MongoDB dotted-path `$inc` on every action (save +2, watched +3, skip −1)
  - Discover scoring blends rating + learned weights + onboarding prefs + jitter
  - Each Discover card shows a personal "reason" pill (e.g., "Because you've been loving Sci-Fi")
  - Profile shows weighted genre bars under "What we've learned about you"
- **Trailer fix:** custom fullscreen modal (replaces shadcn Dialog), `youtube-nocookie.com` embed with `playsinline=1&autoplay=1&mute=1` for mobile autoplay compliance

## Tested
- **Iteration 1:** 15/15 backend pytest, full Playwright flow — 100%/100%
- **Iteration 2:** 19/19 backend pytest, full Playwright flow including new features — 100%/100%
- **Iteration 3:** 31/31 backend pytest, full Playwright flow — 100%/100%
- **Iteration 4:** 56/56 backend pytest, full Playwright flow — 100%/~92% (1 critical OnboardingGenres useState bug fixed during testing)

### Iteration 4 (Feb 2026 — biggest pack)
- **Search** by title/genre (local fast path) with TMDB fallback for actors/missing titles
- **Filters sheet:** anime / Bollywood toggles, country picker (14 countries), genre chips
- **TV detail:** seasons rail with poster + episode counts, total runtime estimate, **per-user progress** ("Up to S2 E5") with progress modal
- **Full-screen immersive movie banner** with backdrop, gradient overlay, hero title + actions
- **Stream + Rent + Buy listings** (TMDB watch providers for the user's country)
- **Reviews:** user-generated (1-10 + text) + TMDB community feed; avg rating cards
- **Discover tabs:** For you / Trending / Upcoming / Popular in <country>
- **In-app notification bell** with unread badge + welcome notifications seeded for new users
- **Watchlist Value** section in Savings — best-value services for user's saved+watched titles, ranked
- **Swipe-down → Watched** action with visual overlay during drag
- **Onboarding** now collects country (default UK) + optional age
- **Backend:** 10-min TTL cache on TMDB section calls; excluded_categories filter applied to all section endpoints; CORS verified locked-down
- **Catalog:** 363 UK-localised titles

### Iteration 3 (Feb 2026)
- **Real TMDB integration** — 265 titles (up from 24 seed) loaded from popular + top_rated + trending across movies & TV; concurrent enrichment with provider mapping & YouTube trailers; cached in `db.movies_cache`
- **Admin Control Room** at `/admin` (role-gated): catalog/users/clicks stats, per-service click bars, "Export CSV" download, "Refresh from TMDB" button, recent clicks feed
- **`/api/auth/refresh`** + axios interceptor that auto-refreshes once on 401
- **CORS lockdown:** explicit `ALLOWED_ORIGINS` env list + preview-domain regex; no wildcard
- **100k-user scaling tweaks:** Mongo connection pool maxPoolSize=200; `/discover` capped to top-500 candidates by popularity to bound latency; indexes on `movies_cache.id` and `affiliate_clicks.created_at`

### Iteration 6 (Feb 2026)
- **P0 — Admin dashboard crash fix**: defined missing `MiniStat` component in `Admin.jsx`, added optional chaining (`analytics?.dau ?? 0`) so engagement card no longer crashes while analytics fetch is pending.
- **P1 — Subscription Value Insights** (new):
  - **Backend** `GET /api/insights/subscriptions` — aggregates `db.user_actions` where `action='watched'` for the **current calendar month**, computes per-platform titles_watched + cost_per_watch + tone (low/ok/great) + headline/message + top_titles. Sorts unused services first. Returns `{currency: '£', month_label, total_monthly_cost, total_watched, services[], unused_services[], potential_savings, cached_at}`. In-memory per-user cache, 1-hour TTL, invalidated on every new `watched` action.
  - **Frontend** Savings page now shows a "Subscription insights" section with potential savings, per-service cards (logo, watched count, cost-per-watch, top titles thumbnails) and tone-coded verdict messages.
  - **Tests:** `/app/backend/tests/test_insights_and_admin.py` — 5/5 passing. Frontend smoke verified `[data-testid=subscription-insights]` + `[data-testid=engagement-card]` + all `mini-stat-*` cards.

### Iteration 7 (Feb 2026)
- **Password reset** (P1, no email yet by user choice):
  - `POST /api/auth/forgot-password` issues a single-use 1-hour token; returns `{token, reset_url, expires_at, delivery:"inline"}` for known emails (always 200 to prevent enumeration). When email is wired (Resend/SendGrid) the inline token MUST be removed from the response.
  - `POST /api/auth/reset-password` consumes token, rotates `password_hash`. Old password rejected after; token is single-use.
  - Frontend: `/forgot-password` (email + copyable inline link) and `/reset-password?token=…` (new password + confirm); `Forgot password?` link added to Login page.
- **Watchlist sharing — mutual opt-in + live compare** (P1):
  - Each user gets a unique 6-char `share_code` (no I/O/0/1) generated lazily on `GET /api/share/me`. Share URL `<frontend>/share/<code>`.
  - Friend-request flow: `POST /share/request` (by code) → recipient sees in `GET /share/requests` → `POST /share/requests/{id}/{accept|reject}`. Mutual auto-accept if reverse pending request exists. Both directions bonded in `users.watchlist_friends`. `DELETE /share/friends/{id}` unfriends both sides.
  - In-app notification fired on incoming request and on accept.
  - `GET /share/compare/{friend_id}` returns `{you, them, overlap_count, overlap[], only_me[], only_them[], recommendations[], pick_tonight, synced_at}`. Recommendations exclude any movie either user touched and prefer titles on shared subscriptions.
  - **Frontend**: `/friends` (manage code, requests, friends), `/compare/:friendId` (3-column tabbed compare with "Pick tonight" hero, polls every 3s — pulses live indicator on change), `/share/:code` (deep link → auto-applies code, prompts sign-in if needed via `sessionStorage.pending_share_code`).
  - **AccountMenu**: "Friends & compare" entry added.
- **Tests:** `/app/backend/tests/test_password_reset_and_sharing.py` — 12/12 passing. Frontend smoke: all required test ids render on /forgot-password, /reset-password (with & without token), /friends, /compare, /share/:code.

### Iteration 8 (Feb 2026)
- **Personalised 4-step Onboarding** (P0):
  - **Step 1 — Taste**: genre chips + mood chips (Funny, Dark, Easy watch, Thought-provoking, Feel-good, Edge of seat, Romantic, Epic). Skippable.
  - **Step 2 — Rate**: `GET /api/onboarding/titles` returns 18 diverse popular titles (greedy diversification, max 2 per genre+type bucket). Tap 👍 / 👎 / ⏭ on each — `POST /api/onboarding/rate` updates `genre_weights` (+3 like, −2 dislike, 0 skip) and `type_weights` live + adds movie to `user.onboarding_rated`. Idempotent on re-submit.
  - **Step 3 — Filters**: anime toggle (strict), Bollywood toggle, Films/TV/Both segmented control, optional excluded-genre chips, country picker.
  - **Step 4 — Streaming services**: existing service picker, prices in £.
  - `POST /api/onboarding/complete` flips `onboarding_completed=true` and routes to /discover.
- **Strict server-side filter enforcement** across `/discover`, `/sections/{trending,upcoming,popular-locally}`, `/search`, `/search/suggest`:
  - `content_type` ('movie' | 'tv' | 'both') drops mismatched items.
  - `excluded_categories` (anime, bollywood) and `excluded_genres` drop matched items.
  - `/discover` additionally excludes anything in `user.onboarding_rated` so onboarding titles never reappear.
- **Backfill migration**: existing users (admin etc.) auto-marked `onboarding_completed=true` on backend startup so they're not trapped in the new flow.
- **Routing**: legacy `/onboarding/services` and `/onboarding/genres` redirect to `/onboarding`. ProtectedRoute now checks `onboarding_completed`.
- **Tests:** `/app/backend/tests/test_onboarding_and_filters.py` — 12/12 passing. Frontend Playwright walk-through confirmed full 4-step flow lands on /discover with personalised picks and all filters enforced.

## Backlog
### P0 — Next priorities
- (none currently)

### P1
- Wire actual email delivery (Resend or SendGrid) for password reset — and remove inline `token` field from /forgot-password response
- Currency consistency: legacy `/api/savings` summary uses `$`; align UK locale to `£` across the whole Savings page
- "Tonight's pick" weekly digest email (depends on email provider above)
- "Popular among similar users" / "Trending near you" recommendations powered by shared watchlists
- Subscription price editing (let user override defaults)

### P2
- Real-time WebSocket compare (currently 3s polling — equivalent UX, lower complexity)
- WatchSmart Plus Stripe subscription tier
- Web push notifications, PWA install, native wrappers
- Affiliate analytics deep-dive dashboard

## Test credentials
See `/app/memory/test_credentials.md`.
