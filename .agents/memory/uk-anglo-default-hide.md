---
name: UK Anglo default hide
description: WatchSmart hides anime + Asian-language drama from the default candidate pool; show_anime_asian is the authoritative opt-in.
---

# UK Anglo-service default hide

WatchSmart is positioned as a mainstream Anglo UK service. Anime + Asian-language
drama are kept OUT of the default candidate pool and only surfaced when a user
opts in via the `show_anime_asian` user flag (default falsey = hidden).

**Why:** Every real UK user's skip history was dominated by Korean/Asian/anime
content, and a brand-new cold-start UK feed was ~27% non-English (mostly anime:
Naruto, Pokémon, My Hero Academia, etc.) before the engine could learn to
suppress it — so new users' first impression was "this app doesn't get me". The
owner explicitly chose to hide this content by default rather than rely on the
post-~5-skip language/theme aversion learning. This deliberately overrides the
older "never shrink the candidate pool" guardrail — it is an intentional product
stance, not a regression.

**How to apply:**
- The hide lives in a single helper that BOTH filter paths (strict + no-subs)
  call. `show_anime_asian` truthy disables the hide entirely.
- `show_anime_asian` is AUTHORITATIVE and subsumes the legacy per-category
  `anime`/`bollywood` values in `excluded_categories`. Do NOT re-add separate
  anime/bollywood exclusion checks in the filters — when opted out everything is
  hidden anyway, and when opted in a stale `excluded_categories=['anime']` must
  NOT block the user. The old granular hide toggles were removed from the UI and
  replaced by one opt-in toggle.
- Scope of "Asian-language": East/SE/South Asian original languages
  (ja/ko/zh/cn/th/id/tl/vi/ms + Bollywood langs) plus anime detection. European
  languages (es/fr/it/de) intentionally stay in the default pool.
- "Opting in fetches the content" is satisfied by revealing existing catalog
  rows — there is no separate on-demand TMDB fetch pipeline for toggled content.
- When growing the mainstream pool, the existing import engine
  (`catalog_import.bulk_import_catalog`) can be pointed at English-only
  `/discover/movie` endpoints by overriding its module-level `GENERAL_ENDPOINTS`
  and passing `pages_genre=0, pages_provider=0`; then run `enrich_providers_top`
  so the new films get `available_on` data and can actually surface.
