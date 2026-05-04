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

## Backlog
### P0 — Next priorities
- Real TMDB API integration (replace seed data) — drop in TMDB API key in `.env`, add fetch+cache layer
- /api/auth/forgot-password & reset-password (basic flows)
- Push title coverage 24 → 200+ via TMDB

### P1
- Sharing: share-a-pick deep links (great for organic growth)
- Streak / weekly digest email of new arrivals on user's services (SendGrid/Resend)
- Subscription price editing (let user override defaults to local currency)
- Rate limiting / brute-force lockout on auth

### P2
- Web push notifications for new arrivals matching pinned tastes
- Friends/social: see what friends saved
- Affiliate analytics dashboard (track click-throughs)
- PWA install + offline cache for last 50 cards
- Native iOS / Android wrapper

## Test credentials
See `/app/memory/test_credentials.md`.
