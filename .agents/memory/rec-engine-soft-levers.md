---
name: Rec-engine quality levers must stay soft
description: How to improve recommendation quality without shrinking the candidate pool or breaking the feed.
---

# Rec-engine quality levers must stay SOFT

**Rule:** Every recommendation-quality improvement must be a *soft* signal —
scoring nudge, ranking re-order, or additive metadata/label — never a new HARD
filter on `build_feed`'s candidate pool.

**Why:** The hard constraint on this engine is "don't break the recommender OR
the candidate pool size." `sim_personas.py` pools (currently 111–800 across the
10 personas) are the safety net: after any change they must stay byte-identical.
A new exclusion silently shrinks pools and can empty niche feeds (anime/doc/family).

**How to apply:**
- Tune ranking in `engine._hybrid_score` (quality/lang/genre/tone terms), not the
  filter loop. Examples that are safe: maturity denominator (40 = reaches 1.0 at
  ~40 swipes, slower so the feed doesn't overfit by swipe 25); permanent
  popularity floor `max(0.12, 1-maturity)` so recognisable titles never vanish at
  high maturity; soft low-vote penalties (<50 votes −0.5 cold/−0.25 mature, <150
  −0.1) to derank obscure without removing.
- UK-first **English prior** is a re-rank scaled by `_eng_prior = max(0, 1 -
  tanh(foreign_appetite/3))` (decays to 0 once the user positively rates any
  non-en language, so foreign fans are unaffected). English: `lang_score =
  max(lang_score, 0) + 1.5*_eng_prior`; unwarmed foreign: `-= 2.5*_eng_prior`.
  Never filters. **Why the English floor:** a skip is the default reject, so a
  heavy skipper in an English-dominant catalogue drives their OWN
  `language_weights["en"]` strongly negative (seen −56 in prod) purely from skip
  volume. With `lang_score = tanh(w/2)*5`, English saturated at −5 while
  less-skipped foreign (e.g. ja ≈ −3) scored HIGHER — so Japanese/foreign floated
  to the top of UK users' feeds. Never let English go net-negative from learned
  weight (mirrors the hard auto-block's dominance protection). Tiny ±0.5/0.6
  nudges were useless against a ±5 lang scale — a corrective term's magnitude
  must match the term it corrects.
- Per-card `availability` label (on_subscription/rent_buy/other_service/
  no_subs_selected) is additive metadata; compute it from
  `providers_util.resolve_region_providers(m, user_region)` (region-resolved),
  NOT the flat `available_on` mirror, or it mislabels outside the default region.
- After ANY rec change, re-run `cd backend && python3 sim_personas.py` and confirm
  all 10 pass and minPool sizes are unchanged.

## Auto-block is already safe — do NOT "fix" it
`routers/user.py` language/decade auto-block is rate-based and reversible: needs
≥12 negatives with ZERO positives (`MIN_NEG=12`, `MIN_TOTAL_POS=3`), can never
block the user's dominant language/decade, and self-heals (pulls blocks when the
bar stops being met). An earlier audit wrongly flagged it as a dangerous
volume/skip-count block — it is not. Leave it alone.

## More-Like-This similarity
`content_cards.card_similarity` bonuses (franchise +0.35, cast Jaccard ×0.15,
language +0.05, era proximity) are additive on top of the base (which sums to 1.0)
then clamped to 1.0, and only affect `/movies/{id}/similar` — never the feed pool.
The fields (franchise/cast/language/year) live on the card via `build_card`;
adding card fields requires bumping `CARD_SCHEMA_VERSION` to force an in-memory
rebuild on next catalog load.
