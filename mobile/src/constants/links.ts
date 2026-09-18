/**
 * External links used by the native app.
 * WEB_BASE is the production web app origin (legal pages, support).
 * NOTE: verified/updated during launch prep — do not hardcode elsewhere.
 */
export const WEB_BASE = "https://watchsmart.uk";

export const Links = {
  privacy: `${WEB_BASE}/privacy`,
  terms: `${WEB_BASE}/terms`,
  support: `${WEB_BASE}/privacy`,
  tmdb: "https://www.themoviedb.org",
} as const;
