/**
 * Discover feed API + shared types for the native Discover screen.
 *
 * Mirrors the web app (frontend/src/pages/Discover.jsx):
 *   - GET /discover?limit=&content_type= feeds the swipe deck.
 *   - POST /user/action { movie_id, action, impression_id } records swipes.
 * The backend threads an `impression_id` into every card so the client can
 * echo it back on each action (see backend/engine.py). We do NOT hit any
 * separate impression endpoint — logging happens server-side during /discover.
 */
import { api } from "@/lib/api";

// ── Feed limits (mirror the web app's constants) ────────────────────────────
export const INITIAL_LIMIT = 60; // deep initial queue so swipes never wait on the network
export const REFILL_LIMIT = 40; // background refill batch size
export const REFILL_THRESHOLD = 20; // trigger a background refill when the stack drops to ~20
export const PRELOAD_AHEAD = 3; // how many upcoming poster/backdrop images to prefetch

export type DiscoverTabId = "for-you" | "movies" | "tv";
export type MediaType = "movie" | "tv";
export type SwipeAction = "save" | "skip" | "watched";
export type ReverseAction = "unsave" | "unskip" | "unwatched";

/** Sentiment captured when a user marks a title as watched. */
export type WatchedSentiment = "loved" | "liked" | "neutral" | "disliked";

/** Extra metadata that accompanies a "watched" action. */
export interface WatchedMeta {
  /** Omitted entirely for the "haven't finished it" case. */
  watched_sentiment?: WatchedSentiment;
  /** false for "haven't finished it", true otherwise. */
  completed: boolean;
}

export const REVERSE_ACTION: Record<SwipeAction, ReverseAction> = {
  save: "unsave",
  skip: "unskip",
  watched: "unwatched",
};

export const TAB_CONTENT_TYPE: Record<DiscoverTabId, MediaType | undefined> = {
  "for-you": undefined,
  movies: "movie",
  tv: "tv",
};

export const DISCOVER_TABS: { id: DiscoverTabId; label: string }[] = [
  { id: "for-you", label: "For You" },
  { id: "movies", label: "Movies" },
  { id: "tv", label: "TV Shows" },
];

export interface Season {
  season_number?: number;
  episode_count?: number;
}

/** A single Discover card. Field shapes come from backend/engine.py build_feed. */
export interface DiscoverCard {
  id: string;
  title: string;
  type: MediaType;
  year?: number;
  rating?: number;
  runtime?: number;
  overview?: string;
  genres?: string[];
  poster_url?: string | null;
  backdrop_url?: string | null;
  available_on?: string[];
  seasons?: Season[];
  match?: number;
  reason?: string;
  impression_id?: string;
  _signals?: { why_shown?: string; [k: string]: unknown };
}

export interface StreamingService {
  logo_path?: string | null;
  id: string;
  name: string;
  [k: string]: unknown;
}

/** Build the /discover request path for a given tab + limit. */
function discoverPath(tab: DiscoverTabId, limit: number): string {
  const ct = TAB_CONTENT_TYPE[tab];
  const params = new URLSearchParams({ limit: String(limit) });
  if (ct) params.set("content_type", ct);
  return `/discover?${params.toString()}`;
}

export async function fetchDiscover(
  tab: DiscoverTabId,
  limit: number = INITIAL_LIMIT
): Promise<DiscoverCard[]> {
  const r = await api.get<DiscoverCard[]>(discoverPath(tab, limit));
  return Array.isArray(r.data) ? r.data : [];
}

export async function fetchServices(): Promise<StreamingService[]> {
  const r = await api.get<StreamingService[]>("/services");
  return Array.isArray(r.data) ? r.data : [];
}

/**
 * Record a swipe / rewind action. Fire-and-forget from the caller's point of
 * view; the deck advances locally without waiting on this round-trip.
 */
export async function postAction(
  movieId: string,
  action: SwipeAction | ReverseAction,
  impressionId?: string,
  meta?: WatchedMeta
): Promise<void> {
  await api.post("/user/action", {
    movie_id: movieId,
    action,
    impression_id: impressionId,
    // Only attach watched metadata when provided (i.e. on a "watched" action).
    ...(meta
      ? {
          completed: meta.completed,
          ...(meta.watched_sentiment ? { watched_sentiment: meta.watched_sentiment } : {}),
        }
      : {}),
  });
}

/**
 * Update the sentiment/completion for an already-watched title (e.g. from the
 * title details screen's "Your rating" row). The endpoint is expected to exist
 * on the backend — we code against this contract.
 */
export async function postWatchedFeedback(
  movieId: string,
  watchedSentiment: WatchedSentiment,
  completed: boolean
): Promise<void> {
  await api.post("/user/watched-feedback", {
    movie_id: movieId,
    watched_sentiment: watchedSentiment,
    completed,
  });
}

/** Format a runtime in minutes as "1h 42m" (mirrors frontend/src/lib/format.js). */
export function formatRuntime(minutes?: number): string | null {
  if (!minutes || minutes <= 0) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}
