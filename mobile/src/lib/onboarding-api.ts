/**
 * Onboarding + preferences + notifications API helpers for the native app.
 *
 * Mirrors the web app's onboarding flow (see frontend/src/pages/Onboarding*.jsx)
 * against the real FastAPI backend:
 *   GET  /services            → streaming services (id, name, price_monthly, …)
 *   GET  /genres              → list of genre strings
 *   PUT  /user/preferences    → persist services / genres / country / age → returns user
 *   GET  /onboarding/titles   → taste-check title cards
 *   POST /onboarding/rate     → { movie_id, rating } → { ok, user }
 *   POST /onboarding/complete → marks onboarding_completed=true → returns user
 *   GET  /notifications       → { items, unread }
 *   POST /notifications/read-all
 *   DELETE /notifications/clear-all
 *   DELETE /auth/account
 */
import { api, WsUser } from "@/lib/api";
import { SubscriptionPlansMap } from "@/lib/pricing-api";

export interface StreamingService {
  id: string;
  name: string;
  price_monthly: number;
  logo_color?: string;
  logo_path?: string;
}

export interface OnboardingTitle {
  id: string;
  title: string;
  type?: "movie" | "tv";
  year?: number;
  overview?: string;
  poster_url?: string;
  backdrop_url?: string;
  rating?: number;
  genres?: string[];
}

export type RateValue = "like" | "dislike" | "skip";

export interface OnboardingProgress {
  interactions: number;
  minimum_interactions: number;
  maximum_interactions: number;
  remaining: number;
  can_finish: boolean;
  is_complete: boolean;
}

export interface WsNotification {
  title?: string;
  body?: string;
  kind?: string;
  read?: boolean;
  created_at?: string;
  notification_id?: string;
}

export interface NotificationsResponse {
  items: WsNotification[];
  unread: number;
}

export async function fetchServices(): Promise<StreamingService[]> {
  const r = await api.get<StreamingService[]>("/services");
  return r.data;
}

export async function fetchGenres(): Promise<string[]> {
  const r = await api.get<string[]>("/genres");
  return r.data;
}

export type ContentType = "both" | "movie" | "tv";

/**
 * Mood options — mirrors the web onboarding step 2 mood list
 * (frontend/src/pages/Onboarding.jsx MOODS).
 */
export const MOODS: { id: string; label: string }[] = [
  { id: "funny", label: "Funny" },
  { id: "dark", label: "Dark" },
  { id: "easy-watch", label: "Easy watch" },
  { id: "thought-provoking", label: "Thought-provoking" },
  { id: "feel-good", label: "Feel-good" },
  { id: "edge-of-seat", label: "Edge of seat" },
  { id: "romantic", label: "Romantic" },
  { id: "epic", label: "Epic" },
];

/**
 * Exclusion categories — must match the web's excluded_categories ids sent to
 * the API (frontend/src/pages/Onboarding.jsx step 3): "family", "anime",
 * "bollywood".
 */
export const EXCLUDE_CATEGORIES: { id: string; label: string; description: string }[] = [
  {
    id: "family",
    label: "Family & Kids",
    description: "Hides content aimed at children and families.",
  },
  {
    id: "anime",
    label: "Anime",
    description: "Hides Japanese animation strictly — Pixar/Western animation stays.",
  },
  {
    id: "bollywood",
    label: "Bollywood",
    description: "Hides South-Asian cinema (Hindi, Telugu, Tamil, and more).",
  },
];

export interface PreferencesPatch {
  services?: string[];
  genres?: string[];
  moods?: string[];
  content_type?: ContentType;
  excluded_categories?: string[];
  excluded_genres?: string[];
  country?: string;
  age?: number;
  /** ISO date string "YYYY-MM-DD". */
  dob?: string;
  /** Per-service chosen plan detail, keyed by service_id. */
  subscription_plans?: SubscriptionPlansMap;
  /** ISO timestamp set when the first-open tutorial is dismissed / completed. */
  tutorial_completed_at?: string;
}

export async function updatePreferences(patch: PreferencesPatch): Promise<WsUser> {
  const r = await api.put<WsUser>("/user/preferences", patch);
  return r.data;
}

export async function fetchOnboardingTitles(limit = 10): Promise<OnboardingTitle[]> {
  const r = await api.get<OnboardingTitle[]>("/onboarding/titles", { params: { limit } });
  return r.data;
}

export async function fetchOnboardingProgress(): Promise<OnboardingProgress> {
  const r = await api.get<OnboardingProgress>("/onboarding/progress");
  return r.data;
}

export async function rateTitle(
  movieId: string,
  rating: RateValue
): Promise<{ ok: boolean; user?: WsUser }> {
  const r = await api.post<{ ok: boolean; user?: WsUser }>("/onboarding/rate", {
    movie_id: movieId,
    rating,
  });
  return r.data;
}

export async function completeOnboarding(): Promise<WsUser> {
  const r = await api.post<WsUser>("/onboarding/complete");
  return r.data;
}

export async function fetchNotifications(): Promise<NotificationsResponse> {
  const r = await api.get<NotificationsResponse>("/notifications");
  return r.data;
}

export async function markAllNotificationsRead(): Promise<void> {
  await api.post("/notifications/read-all");
}

export async function clearAllNotifications(): Promise<void> {
  await api.delete("/notifications/clear-all");
}

export async function deleteAccount(): Promise<void> {
  await api.delete("/auth/account");
}
