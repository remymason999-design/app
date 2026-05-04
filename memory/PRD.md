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

## What's been implemented (Feb 2026 — MVP)
- Authentication: register / login / logout / me, Emergent Google session exchange
- Onboarding: streaming services picker (8 services with prices) + genre picker (14 genres)
- Discover: Framer Motion swipe stack — drag right to save, left to skip; action buttons for skip/watched/info/save
- Movie Detail: poster, rating, runtime, where-to-watch affiliate links, YouTube trailer modal, AI "why you'll love this" via GPT-5.2
- Watchlist (saved) and Profile (toggle services/genres, stats, logout)
- Savings dashboard: monthly + yearly total, per-service activity, overlap count, AI-style cancel/rotate suggestions
- Dark cinematic theme: Cabinet Grotesk + Satoshi fonts, Obsidian #060608 + Amber #F59E0B, glass morphism, grain texture
- Bottom tab navigation (Discover / Watchlist / Savings / Profile), data-testid coverage on all interactive elements

## Tested (iteration 1: 2026-02-04)
Backend: 15/15 pytest passing — auth, services, genres, preferences, discover filtering, movie detail, action transitions, watchlist, watched, savings, GPT-5.2 explain.
Frontend: full Playwright flow — landing → register → onboarding → discover → swipe + buttons → detail → trailer/explain → watchlist → savings → profile → logout.

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
