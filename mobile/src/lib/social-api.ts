/**
 * Social / sharing + savings API helpers for the native app.
 *
 * Thin typed wrappers over the shared axios `api` client. Request/response
 * shapes mirror backend/routers/sharing.py, savings.py and user.py exactly —
 * do not invent fields.
 */
import { api } from "@/lib/api";

export interface LibraryData {
  watchlist: WatchlistItem[];
  watched: WatchlistItem[];
  continue_watching?: WatchlistItem[];
  progress?: WatchlistItem[];
  stats?: {
    saved?: number;
    watched?: number;
    in_progress?: number;
    watched_movies?: number;
    watched_episodes?: number;
    tv_shows_completed?: number;
    total_hours?: number;
    total_hours_estimated?: boolean;
  };
}

/** The consolidated library endpoint is preferred, with legacy lists retained
 * for older API deployments. No synthetic entries are created here. */
export async function fetchLibrary(): Promise<LibraryData> {
  try {
    const r = await api.get<LibraryData | WatchlistItem[]>("/library");
    const value = r.data;
    if (Array.isArray(value)) return { watchlist: value, watched: [] };
    return {
      watchlist: Array.isArray(value?.watchlist) ? value.watchlist : [],
      watched: Array.isArray(value?.watched) ? value.watched : [],
      continue_watching: Array.isArray(value?.continue_watching) ? value.continue_watching : [],
      progress: Array.isArray(value?.progress) ? value.progress : [],
      stats: value?.stats,
    };
  } catch (error) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status !== 404 && status !== 405) throw error;
    const [saved, watched] = await Promise.all([
      api.get<WatchlistItem[]>("/watchlist"),
      api.get<WatchlistItem[]>("/watched"),
    ]);
    return { watchlist: Array.isArray(saved.data) ? saved.data : [], watched: Array.isArray(watched.data) ? watched.data : [] };
  }
}

export async function setUserProgress(movieId: string, season: number, episode: number): Promise<void> {
  await api.post("/user/progress", { movie_id: movieId, season, episode });
}

export interface EpisodeProgressInput { movie_id: string; season: number; episode: number; watched?: boolean; provenance?: string }
export async function setEpisodeProgress(input: EpisodeProgressInput) {
  await api.post("/user/progress/episode", { ...input, watched: input.watched ?? true, provenance: input.provenance ?? "explicit" });
}
export async function markWatchedThrough(movie_id: string, season: number, episode: number) {
  await api.post("/user/progress/watched-through", { movie_id, season, episode });
}
export async function markSeasonProgress(movie_id: string, season: number, episode: number) {
  await api.post("/user/progress/season", { movie_id, season, episode });
}
export async function markSeriesProgress(movie_id: string, season: number, episode: number) {
  await api.post("/user/progress/series", { movie_id, season, episode });
}
export async function toggleEpisodeProgress(input: Omit<EpisodeProgressInput, "watched">) {
  await api.post("/user/progress/toggle", input);
}

// ---------------------------------------------------------------------------
// Watchlist / actions
// ---------------------------------------------------------------------------
export interface WatchlistItem {
  id: string;
  title: string;
  type?: "movie" | "tv" | string;
  poster_url?: string | null;
  rating?: number | null;
  year?: number | null;
  runtime?: number | null;
  seasons?: unknown[];
  available_on?: string[];
  progress?: { season?: number; episode?: number };
  you_reaction?: string | null;
  watched_completed?: boolean;
  completion?: {
    completed?: boolean;
    watched_episode_count?: number;
    eligible_episode_count?: number | null;
    watched_released_episode_count?: number | null;
    progress_pct?: number;
  };
}

export type UserAction =
  | "save"
  | "skip"
  | "watched"
  | "unsave"
  | "unskip"
  | "unwatched";

export async function postUserAction(movie_id: string, action: UserAction): Promise<void> {
  await api.post("/user/action", { movie_id, action });
}

/** Clears the unseen-watchlist badge counter server-side. */
export async function markWatchlistSeen(): Promise<void> {
  await api.post("/user/watchlist-seen");
}

// ---------------------------------------------------------------------------
// Sharing / friends (backend/routers/sharing.py)
// ---------------------------------------------------------------------------
export interface ShareMe {
  share_code: string;
  share_url: string;
  watchlist_size: number;
}

export interface PublicUser {
  user_id: string;
  name: string;
  picture?: string | null;
  share_code?: string | null;
  watchlist_size?: number;
}

export interface IncomingRequest {
  request_id: string;
  from: PublicUser;
  created_at: string;
}

export interface OutgoingRequest {
  request_id: string;
  to: PublicUser;
  created_at: string;
}

export interface ShareRequests {
  incoming: IncomingRequest[];
  outgoing: OutgoingRequest[];
}

export interface Friend extends PublicUser {}

export interface SendRequestResult {
  ok: boolean;
  status: "sent" | "accepted" | "already_friends" | "already_requested";
  friend?: PublicUser;
  request_id?: string;
}

export async function fetchShareMe(): Promise<ShareMe> {
  const r = await api.get<ShareMe>("/share/me");
  return r.data;
}

export async function fetchFriends(): Promise<Friend[]> {
  const r = await api.get<Friend[]>("/share/friends");
  return r.data;
}

export async function fetchShareRequests(): Promise<ShareRequests> {
  const r = await api.get<ShareRequests>("/share/requests");
  return r.data;
}

export async function sendFriendRequest(code: string): Promise<SendRequestResult> {
  const r = await api.post<SendRequestResult>("/share/request", { code });
  return r.data;
}

export async function acceptFriendRequest(requestId: string): Promise<void> {
  await api.post(`/share/requests/${requestId}/accept`);
}

export async function rejectFriendRequest(requestId: string): Promise<void> {
  await api.post(`/share/requests/${requestId}/reject`);
}

export async function removeFriend(friendId: string): Promise<void> {
  await api.delete(`/share/friends/${friendId}`);
}

// ---------------------------------------------------------------------------
// Compare (backend/routers/sharing.py GET /share/compare/{friend_id})
// ---------------------------------------------------------------------------
export interface CompareMovie {
  id: string;
  title: string;
  type?: "movie" | "tv" | string;
  poster_url?: string | null;
  rating?: number | null;
  genres?: string[];
  available_on?: string[];
  /** "For you both" items carry a short reason explaining the joint pick. */
  reason?: string | null;
  /** Optional joint-scoring debug fields (ignored by the UI). */
  joint_score?: number | null;
  joint_debug?: Record<string, unknown> | null;
}

export interface CompareData {
  you: PublicUser;
  them: PublicUser;
  overlap_count: number;
  overlap: CompareMovie[];
  only_me: CompareMovie[];
  only_them: CompareMovie[];
  /** Titles both of you have marked watched. */
  watched_both?: CompareMovie[];
  /** Titles both of you rated "loved". */
  both_loved?: CompareMovie[];
  /** Titles your friend loved that you haven't watched yet. */
  loved_by_them?: CompareMovie[];
  recommendations: CompareMovie[];
  saved?: { both?: CompareMovie[]; you?: CompareMovie[]; friend?: CompareMovie[] };
  watched?: { both?: CompareMovie[]; you?: CompareMovie[]; friend?: CompareMovie[] };
  pick_tonight: CompareMovie | null;
  sentiment?: { you?: Record<string, string>; friend?: Record<string, string> };
  progress?: {
    you?: Record<string, { season?: number; episode?: number }>;
    friend?: Record<string, { season?: number; episode?: number }>;
  };
  synced_at: string;
  /** Query-mode pagination response used by the native compare screen. */
  items?: CompareMovie[];
  pagination?: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
  };
  counts?: {
    saved?: { both?: number; you?: number; friend?: number };
    watched?: { both?: number; you?: number; friend?: number };
    recommendations?: number;
  };
}

export type CompareView = "watchlists" | "watched" | "recs";
export type CompareScope = "overlap" | "only_me" | "only_them";

export async function fetchCompare(
  friendId: string,
  params?: { view?: CompareView; scope?: CompareScope; page?: number; page_size?: number },
): Promise<CompareData> {
  const r = await api.get<CompareData>(`/share/compare/${friendId}`, { params });
  return r.data;
}

// ---------------------------------------------------------------------------
// Savings (backend/routers/savings.py)
// ---------------------------------------------------------------------------
export interface UsageRow {
  service_id: string;
  name: string;
  logo_color?: string;
  price_monthly: number;
  activity_count: number;
  available_unseen: number;
  /** The user's chosen plan name for this service, if confirmed. */
  plan_name?: string | null;
  /** Effective monthly cost of the chosen plan. */
  monthly_cost?: number | null;
  /** Billing cycle of the chosen plan. */
  billing_cycle?: "monthly" | "annual" | null;
  /** True when the service is subscribed but no plan has been confirmed yet. */
  needs_plan?: boolean;
}

export interface Suggestion {
  type: "cancel" | "rotate" | string;
  service_id?: string;
  headline: string;
  reason: string;
  monthly_savings?: number;
}

export interface SavingsData {
  total_monthly: number;
  total_yearly: number;
  subscription_count: number;
  usage: UsageRow[];
  suggestions: Suggestion[];
  overlap_titles: number;
}

export interface ValueTitle {
  id: string;
  title: string;
  poster_url?: string | null;
}

export interface ValueRow {
  service_id: string;
  name: string;
  logo_color?: string;
  price_monthly: number;
  subscribed: boolean;
  titles_count: number;
  value_score: number;
  cost_per_title: number | null;
  top_titles: ValueTitle[];
}

export interface WatchlistValue {
  services: ValueRow[];
  watchlist_size: number;
}

export interface InsightService {
  service_id: string;
  name: string;
  price_monthly: number;
  titles_watched: number;
  cost_per_watch: number | null;
  headline: string;
  message: string;
  tone: "great" | "neutral" | "low" | string;
  top_titles: ValueTitle[];
}

export interface SubscriptionsInsights {
  month_label: string;
  currency: string;
  total_watched: number;
  potential_savings: number;
  services: InsightService[];
}

export async function fetchSavings(): Promise<SavingsData> {
  const r = await api.get<SavingsData>("/savings");
  return r.data;
}

export async function fetchWatchlistValue(): Promise<WatchlistValue> {
  const r = await api.get<WatchlistValue>("/watchlist/value");
  return r.data;
}

export async function fetchSubscriptionsInsights(): Promise<SubscriptionsInsights> {
  const r = await api.get<SubscriptionsInsights>("/insights/subscriptions");
  return r.data;
}
