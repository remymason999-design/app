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

### Iteration 9 (Feb 2026)
- **Continuous self-improving recommendation engine** (`/app/backend/engine.py`):
  - **Pool building**: every `/api/discover` call assembles a per-user candidate pool from the catalog, applying ALL user filters strictly (subscriptions, excluded categories, excluded genres, content type) and de-duping against `saved + watched + onboarding_rated + recently_shown` (6h cooldown LRU on the user doc, last 200 entries).
  - **Hybrid ranking** combines: quality (popularity ↘ as user matures, rating ↗), explicit onboarding genres + moods, learned `genre_weights` / `type_weights`, lightweight **collaborative filtering** (cosine similarity over genre_weights → boost titles saved by 5 nearest neighbours), recency boost (≤2 years), tiny per-id jitter.
  - **Adaptive maturity** (0..1, reaches 1 around 50 interactions): cold-start users see popular content; mature users see niche personalised picks.
  - **Controlled randomness**: 8% of returned slots are random-within-filter for diversity.
  - **Cooldown re-introduction**: skipped >30 days ago AND now overlaps top learned genres → reappears with reason "Worth a second look" and `_signals.is_reintro=true`.
  - **Background refill**: when filtered pool drops below `LOW_WATER=200`, `asyncio.create_task` fires deep TMDB sync (per-user lock to dedupe).
  - **Transparency endpoint** `GET /api/me/engagement` returns maturity, total_interactions, by_action breakdown, top learned genres, type_weights, watchlist/watched counts.
- **Deeper TMDB harvest** (`tmdb.py`): `fetch_catalog` now hits 5 endpoints per kind (popular, top_rated, trending, /discover sorted by release date, /discover sorted by vote_count) × pages=8 → catalog grew **363 → 953 titles** on first deep-sync; idempotent `bulk_write` upserts prevent duplicate-key races between concurrent refreshes.
- **Admin dashboard**: `POST /api/admin/refresh-catalog` now defaults to pages=8 and returns `{ok, count: catalog_total, items_fetched, catalog_total}`.
- **Tests**: 19/21 backend pytest passing in `/app/backend/tests/test_engine_iter9.py`. Two failures are spec-vs-data discrepancies (admin pool 234 vs target 300+ due to sparse `available_on` for hbo_max in TMDB harvest), not engine bugs. Frontend smoke verified Discover still renders cards with reasons and save advances feed.

### Iteration 10 (Feb 2026)
- **Content cards classification system** (`/app/backend/content_cards.py`):
  - Every catalog item now carries a `card` object: `{primary_category, secondary_categories, tone, audience_type, pacing, themes, confidence_score}`.
  - **Genre hierarchy** — Primary (Animation, Family, Action, Horror, Comedy, Sci-Fi, Romance, Documentary, Mystery, Western, Music) → Secondary (Adventure, Fantasy, History, War) → Context-only (Crime, Thriller, Drama). Context genres NEVER become primary if any Primary/Secondary present.
  - **Tone classifier** with overrides — Animation+Family without Horror/Crime/Thriller → `light` even if Drama present; Horror/War → `dark`; Crime+Drama → `dark`. Plus lexical hints from overview text.
  - **Audience** — uses TMDB certifications when present (R/NC-17/MA → adult, PG-13/12/15 → teen, PG/U → family, G/Y → kids); falls back to genre heuristics (Animation+Family → family, Animation → kids, Horror/War → adult).
  - **Pacing** — Action ≤120min → fast; Drama+History/War → slow.
  - **Themes** (semantic tags) — keyword detection in overview + genre-combo rules: `epic-journey` (Adventure+Family/Animation), `moral-grey` (Crime+Drama), `mind-bending` (Sci-Fi+Mystery/Thriller), `space-opera` (Sci-Fi+Action), `true-crime` (Documentary+Crime), `dread`, `high-fantasy`, `feel-good`, etc. (20 themes total).
  - **Confidence score** 0..1 — driven by metadata completeness (genres, overview, runtime, vote_count, certification, themes detected).
- **Card-based "More Like This"** — `/api/movies/{id}/similar` now ranks by `card_similarity` (40% themes Jaccard / 25% tone / 20% audience exact-or-adjacent / 10% pacing / 5% genre primary+secondary), dampened by min confidence. Filter threshold ≥0.15. Falls back to TMDB only if local pool < 8.
- **API surface**: `/api/movies/{id}` returns `card`; `/api/discover` items already include `card` (attached at catalog load).
- **Tests**: 14/14 spec assertions passing in `/app/backend/tests/test_content_cards_iter10.py` — includes unit fixtures (Animation+Family→light/family, Horror→dark/adult, Crime+Drama→moral-grey, Sci-Fi+Action→space-opera, Drama+History→slow), API integration (Horror similar has 0 kids audience, similarity ranked descending, hierarchy: 0 context-as-primary violations across 30 items), and idempotency.

### Iteration 11 (Feb 2026) — Stabilisation pass
- **TMDB enrichment** (P1.2): `_enrich` now uses `append_to_response=keywords,release_dates,content_ratings` — single TMDB call now returns full classification metadata. Each catalog item carries `certification` (UK BBFC preferred, US MPA fallback) and `keywords` (TMDB curated taxonomy, up to 30 per title).
- **Classifier upgrades** (P1):
  - `_extract_themes` now consumes TMDB keyword tags via `KEYWORD_THEME_MAP` (50+ keyword→theme mappings) layered above the existing overview-text + genre-combo rules.
  - `_classify_tone` now respects adult certification: an Animation+Family title with cert "18"/R/TV-MA/etc. can't be classified `light` (was previously a known false-positive for INVINCIBLE-style adult animated shows).
  - UK certifications (12, 12A, 15, 18, U, Uc) added explicitly to the audience tier sets.
  - `_confidence` formula rebalanced: keywords now contribute up to +0.15, certification +0.25, themes +0.15. Cert+keyword-rich items now reach ~0.93 confidence; pure-genre fallback floors at ~0.40.
  - **Catalog-wide confidence: 0.62 → 0.87** after one full TMDB resync.
- **Strict filter enforcement** (P1.3): `_section()` helper in `routers/discovery.py` now applies `apply_user_filters` BEFORE sorting/ranking on every list endpoint. Sections also dedupe against `saved + watched + skipped + onboarding_rated + recently_shown` — so a saved item disappears from trending on the next refresh.
- **Repetition control** (P1.4): consecutive `/discover` calls now show **0% overlap** in tests (LRU cooldown on user doc + section-side dedup).
- **"More Like This"** (P1.5): card-similarity ONLY. Filters applied before scoring. TMDB augmentation path also classified into cards (no genre-overlap fallback). Each augmentation candidate must score ≥0.10 to be included.
- **Tests**: 14/14 in `test_content_cards_iter10.py` + 5/5 stabilisation tests in `test_stabilisation_iter11.py` (filter strictness, section dedup, repetition control, card-only similarity, confidence ≥0.80).

### Iteration 12 (Feb 2026) — Confidence-system upgrade
- **Sub-confidences**: every card now exposes four 0..1 scores instead of one:
  - `tone_confidence` — high (1.0) when cert + genre + overview agree (e.g. R-rated + dark-genre + "murder" lexicon); 0.7 when only genre signal; 0.5 when only overview hints.
  - `audience_confidence` — 0.95 from certification, 0.65 from genre heuristic, 0.45 from overview.
  - `theme_confidence` — calibrated honestly: 0.95 with 3+ themes incl. ≥1 verified; 0.80 with 2; 0.65 with 1; 0.60 if TMDB keywords present but none mapped (we have data, taxonomy just doesn't hit); 0.50 with overview only; 0.30 sparse.
  - `metadata_confidence` — completeness check (genres+overview+runtime+vote_count+keywords).
  - **Final `confidence_score`** = 0.30·tone + 0.30·audience + 0.25·theme + 0.15·metadata.
- **Verified vs inferred themes** — split into `verified_themes` (from TMDB keyword taxonomy via expanded `KEYWORD_THEME_MAP` of 80+ entries) and `inferred_themes` (from overview lexicon + genre-combo rules). Verified themes weight more heavily in confidence.
- **Genre dominance with suppression** — `_resolve_genre_conflicts()` drops Crime/Thriller/Horror from Family/Kids-certified items BEFORE primary/secondary selection. So a "Family + Adventure + Crime" PG-rated kids' detective show now classifies as primary=Family (not Crime) and the conflict is logged.
- **Conflict resolution rules** detected and logged in `card.conflicts_resolved`:
  - `family-cert-vs-crime-genre` — family rating with Crime/Thriller genre
  - `animation-vs-adult-cert` — adult cert on Animation-only (e.g. BoJack, Invincible)
  - `family-cert-vs-dark-tone` — family cert with dark-coded overview
  - `horror-genre-vs-family-cert` — Horror genre with family rating (cert wins)
- **Catalog-wide confidence: 0.87 → 0.91** (avg across 30 sampled items). p25=0.89, p50=0.93, p75=0.97. Target ≥0.90 met.
- **Tests**: 7/7 in `test_confidence_system_iter12.py` (schema, verified/inferred split, genre dominance, conflict detection, weighting math, catalog avg ≥0.88, cert grounding). 14/14 iter10 + 5/5 iter11 still pass.

## Backlog
### P0 — Next priorities
- (none currently)

### P1
- Surface card signals in UI: tone/audience pills on Discover, "More Like This" carousel using card-similarity scores
- Subscription price editing
- Wire actual email delivery (Resend or SendGrid) for password reset

### P2
- LLM-augmented theme extraction for low-confidence (<0.7) titles
- Real-time WebSocket compare (currently 3s polling)
- Densify `available_on` for hbo_max in TMDB harvest
- WatchSmart Plus Stripe tier
- Web push, PWA, native wrappers

## Test credentials
See `/app/memory/test_credentials.md`.
