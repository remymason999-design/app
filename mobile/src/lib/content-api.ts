/**
 * Content API helpers for the native app (title details + search).
 *
 * Mirrors the web app's data usage against the FastAPI backend
 * (backend/routers/content.py). The backend keys everything by a single
 * `movie_id` and returns both movies and TV shows from the same endpoints;
 * `type` ("movie" | "tv") distinguishes them.
 */
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types (only the fields the mobile screens read — everything is optional so
// missing metadata never crashes the UI)
// ---------------------------------------------------------------------------
export interface Season {
  season_number?: number;
  name?: string;
  episode_count?: number;
  poster_path?: string | null;
}

export interface MovieDetail {
  id: string;
  title?: string;
  year?: number;
  rating?: number;
  runtime?: number;
  type?: "movie" | "tv";
  certification?: string | null;
  content_rating?: string | null;
  overview?: string | null;
  poster_url?: string | null;
  backdrop_url?: string | null;
  genres?: string[];
  cast_names?: string[];
  available_on?: string[];
  rent_on?: string[];
  buy_on?: string[];
  seasons?: Season[];
  provider_region?: string | null;
  availability_region_matched?: boolean;
  [key: string]: unknown;
}

export interface SimilarItem {
  id: string;
  title?: string;
  year?: number;
  rating?: number;
  type?: "movie" | "tv";
  poster_url?: string | null;
}

export interface StreamingService {
  id: string;
  name: string;
  logo_path?: string | null;
  logo_color?: string | null;
}

export interface SearchResult {
  id: string;
  title?: string;
  year?: number;
  rating?: number;
  type?: "movie" | "tv";
  runtime?: number;
  overview?: string | null;
  poster_url?: string | null;
  genres?: string[];
  available_on?: string[];
  on_subscription?: boolean;
  availability_label?: string | null;
  seasons?: Season[];
}

export interface SearchResponse {
  results: SearchResult[];
  fallback: boolean;
  has_more: boolean;
  total?: number;
}

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------
export async function fetchMovie(id: string, signal?: AbortSignal): Promise<MovieDetail> {
  const r = await api.get<MovieDetail>(`/movies/${encodeURIComponent(id)}`, { signal });
  return r.data;
}

export async function fetchSimilar(id: string, signal?: AbortSignal): Promise<SimilarItem[]> {
  const r = await api.get<SimilarItem[]>(`/movies/${encodeURIComponent(id)}/similar`, { signal });
  return Array.isArray(r.data) ? r.data : [];
}

export async function fetchServices(signal?: AbortSignal): Promise<StreamingService[]> {
  const r = await api.get<StreamingService[]>("/services", { signal });
  return Array.isArray(r.data) ? r.data : [];
}

export type ContentAction = "save" | "skip" | "watched" | "unsave" | "unskip" | "unwatched";

export async function postAction(movieId: string, action: ContentAction): Promise<void> {
  await api.post("/user/action", { movie_id: movieId, action });
}

/** Fire-and-forget engagement signal (never blocks the UI). */
export function engage(movieId: string, action: string): void {
  api.post("/user/engage", { movie_id: movieId, action }).catch(() => {});
}

export async function searchTitles(
  q: string,
  opts: { limit?: number; offset?: number; signal?: AbortSignal } = {}
): Promise<SearchResponse> {
  const params: Record<string, string | number> = {
    q,
    limit: opts.limit ?? 20,
    offset: opts.offset ?? 0,
  };
  const r = await api.get<SearchResponse>("/search", { params, signal: opts.signal });
  const data = r.data || ({} as SearchResponse);
  return {
    results: Array.isArray(data.results) ? data.results : [],
    fallback: Boolean(data.fallback),
    has_more: Boolean(data.has_more),
    total: typeof data.total === "number" ? data.total : undefined,
  };
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
export function formatRuntime(mins?: number | null): string | null {
  if (!mins || mins <= 0) return null;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  return `${m}m`;
}

export function getCertification(m: { certification?: string | null; content_rating?: string | null }): string | null {
  const c = (m.certification || m.content_rating || "").toString().trim();
  return c ? c : null;
}
