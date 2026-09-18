---
name: Watched sentiment & UK pricing systems
description: Durable rules from the sentiment-feedback, joint-recs and subscription-plan update
---
- Watched-with-sentiment learning stores the exact applied `$inc` fragment in `user.watched_feedback.<movie_id>.applied_inc`; rewind/re-rate must CLAIM the entry atomically (find_one_and_update $unset, return BEFORE) and merge reverse+new into one $inc. **Why:** snapshot-based reversal double-applies under concurrency.
- Sentiment deltas: loved +2.5 / liked +1.5 / neutral +0.3 / disliked −2.0 / unfinished +0.1; linear-only path (no compounding) so reversal is exact.
- "For you both" (compare surface only) = min(scoreA,scoreB)+mutual bonuses−penalties, hard exclusions allowed there (NOT in main feed pools); pre-cap ~400 candidates + 10-min TTL cache keyed by action counts.
- Subscription cost is server-authoritative: client effective_monthly_cost ignored unless custom_price (clamped 0–100); derive from LIVE streaming_plans docs, not the static seed; plan_id must belong to service_id.
- Pricing seed upsert only overwrites docs with seed_managed && !admin_modified — admin edits survive restarts. Free/licence_required (Channel 4 Free, BBC iPlayer) contribute £0 to savings.
- GET /pricing/services returns {services:[...]} (not a bare array) — mobile fetchPricingServices unwraps it.
- /user/preferences is PUT and the services field is named `services` (stored as `subscriptions`); register returns `access_token`.
- Reserved TLDs (.test) are rejected by backend email validation — e2e accounts need a real-looking domain.
- Avatars: processed 512px JPEGs live in a separate `avatars` collection (never on the user doc); user.picture holds "/api/avatar/<uid>?v=ts" or an absolute Google URL. Mobile MUST resolve relative picture URLs via resolveImageUrl (different origin than the API) or images silently fall back to initials.
- Expo Go ignores app.json splash customization — startup animation must be an in-app JS overlay (LaunchAnimation, once-per-cold-start module flag). Alert.alert multi-button is a no-op on react-native-web; web needs explicit buttons/branch.
- Provider backfills: reuse build_region_entry/normalize_provider from providers_util so results match the importer, and restart the server after — the in-memory catalog doesn't see DB changes.
- Savings UI must take subscription price, cost-per-watch, and possible savings from the plan-aware Savings result; use subscription insights only for the recorded activity window and title evidence. **Why:** the insights endpoint can still carry registry prices, which may differ from the user's selected plan. **How to apply:** join both responses by service ID and recalculate displayed cost-per-watch from the plan-aware monthly cost.
