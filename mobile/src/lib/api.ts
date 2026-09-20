/**
 * WatchSmart API client for the native app.
 *
 * Talks to the existing FastAPI backend (same endpoints as the web app).
 * Tokens are kept in expo-secure-store (hardware-backed keychain/keystore on
 * device) instead of the web app's localStorage, with an in-memory cache so
 * interceptors stay synchronous-fast.
 */
import axios, { AxiosError, AxiosRequestConfig } from "axios";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { analytics } from "@/lib/analytics";

// expo-secure-store is unavailable on web (used only for the Expo web dev
// preview); fall back to localStorage there. Native builds always use the
// hardware-backed keychain/keystore.
const storage = {
  async get(key: string): Promise<string | null> {
    if (Platform.OS === "web") {
      try {
        return globalThis.localStorage?.getItem(key) ?? null;
      } catch {
        return null;
      }
    }
    return SecureStore.getItemAsync(key);
  },
  async set(key: string, value: string | null): Promise<void> {
    if (Platform.OS === "web") {
      try {
        if (value === null) globalThis.localStorage?.removeItem(key);
        else globalThis.localStorage?.setItem(key, value);
      } catch {
        // ignore — web preview only
      }
      return;
    }
    if (value === null) await SecureStore.deleteItemAsync(key);
    else await SecureStore.setItemAsync(key, value);
  },
};

const TOKEN_KEY = "ws_access_token";
const REFRESH_KEY = "ws_refresh_token";

export function getApiBaseUrl(): string {
  const base = process.env.EXPO_PUBLIC_API_URL;
  if (!base) {
    throw new Error(
      "EXPO_PUBLIC_API_URL is not set — the mobile app cannot reach the WatchSmart backend."
    );
  }
  return base.replace(/\/+$/, "");
}

/**
 * Resolve a possibly-relative image URL (e.g. "/api/avatar/<uid>?v=1") against
 * the backend origin. Absolute URLs (Google avatars, TMDB) pass through
 * untouched. The mobile app runs on a different origin than the API, so
 * relative paths from the backend must be prefixed to load at all.
 */
export function resolveImageUrl(url?: string | null): string | null {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  return `${getApiBaseUrl()}${url.startsWith("/") ? "" : "/"}${url}`;
}

// ---------------------------------------------------------------------------
// Token storage (secure, async) with in-memory mirror
// ---------------------------------------------------------------------------
let accessToken: string | null = null;
let refreshToken: string | null = null;
let tokensLoaded = false;

export async function loadTokens(): Promise<void> {
  if (tokensLoaded) return;
  // Dev-only web bootstrap: `?dev_token=<JWT>` on the Expo web preview stores
  // the token so screenshot tooling can view authed screens. No-op on native
  // and in production builds.
  if (__DEV__ && Platform.OS === "web") {
    try {
      const params = new URLSearchParams(globalThis.location?.search || "");
      const t = params.get("dev_token");
      if (t) await storage.set(TOKEN_KEY, t);
    } catch {
      // ignore — dev preview only
    }
  }
  try {
    accessToken = await storage.get(TOKEN_KEY);
    refreshToken = await storage.get(REFRESH_KEY);
  } catch {
    accessToken = null;
    refreshToken = null;
  }
  tokensLoaded = true;
}

export async function setTokens(access: string | null, refresh?: string | null) {
  accessToken = access;
  await storage.set(TOKEN_KEY, access);
  if (refresh !== undefined) {
    refreshToken = refresh;
    await storage.set(REFRESH_KEY, refresh);
  }
}

export async function clearTokens() {
  await setTokens(null, null);
}

export function hasSession(): boolean {
  return !!accessToken || !!refreshToken;
}

// ---------------------------------------------------------------------------
// Axios instance with bearer auth + 401 refresh-and-retry (mirrors web app)
// ---------------------------------------------------------------------------
export const api = axios.create({ timeout: 20000 });

api.interceptors.request.use(async (config) => {
  await loadTokens();
  config.baseURL = `${getApiBaseUrl()}/api`;
  if (accessToken) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>)["Authorization"] = `Bearer ${accessToken}`;
  }
  return config;
});

type RefreshResult = "refreshed" | "invalid" | "transient";
let refreshing: Promise<RefreshResult> | null = null;

async function tryRefresh(): Promise<RefreshResult> {
  if (!refreshToken) return "invalid";
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await axios.post(
          `${getApiBaseUrl()}/api/auth/refresh`,
          {},
          { headers: { Authorization: `Bearer ${refreshToken}` }, timeout: 15000 }
        );
        const data = r.data || {};
        if (data.access_token) {
          await setTokens(data.access_token, data.refresh_token ?? undefined);
          return "refreshed";
        }
        return "invalid";
      } catch (error) {
        const status = (error as AxiosError)?.response?.status;
        return status === 400 || status === 401 || status === 403
          ? "invalid"
          : "transient";
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined;
    if (error.response?.status === 401 && original && !original._retried) {
      const refreshResult = await tryRefresh();
      if (refreshResult === "refreshed") {
        original._retried = true;
        return api.request(original);
      }
      if (refreshResult === "invalid") {
        analytics.sessionExpired();
        analytics.reset();
        await clearTokens();
      }
    }
    return Promise.reject(error);
  }
);

// ---------------------------------------------------------------------------
// Friendly error messages (mirrors web app behaviour)
// ---------------------------------------------------------------------------
export function getFriendlyMessage(err: unknown): string {
  const e = err as AxiosError<{ detail?: unknown }>;
  if (e?.code === "ECONNABORTED") return "The request timed out. Please try again.";
  if (!e?.response) return "Can't reach WatchSmart right now. Check your connection.";
  const detail = e.response.data?.detail;
  if (typeof detail === "string" && detail.length < 200) return detail;
  switch (e.response.status) {
    case 401:
      return "Incorrect email or password.";
    case 409:
      return "That email is already registered.";
    case 429:
      return "Too many attempts — please wait a minute and try again.";
    default:
      return "Something went wrong. Please try again.";
  }
}

// ---------------------------------------------------------------------------
// Auth API
// ---------------------------------------------------------------------------
export interface WsUser {
  user_id: string;
  email: string;
  name?: string;
  picture?: string | null;
  onboarding_completed?: boolean;
  watchlist_unseen?: number;
  subscriptions?: string[];
  subscription_plans?: Record<string, unknown>;
  tutorial_completed_at?: string | null;
  [key: string]: unknown;
}

interface AuthResponse {
  user: WsUser;
  access_token: string;
  refresh_token: string;
}

export interface AppleLoginPayload {
  identity_token: string;
  authorization_code?: string | null;
  apple_user?: string | null;
  full_name?: string | null;
  email?: string | null;
}

export async function loginRequest(email: string, password: string): Promise<WsUser> {
  const r = await api.post<AuthResponse>("/auth/login", { email, password });
  await setTokens(r.data.access_token, r.data.refresh_token);
  return r.data.user;
}

export async function appleLoginRequest(payload: AppleLoginPayload): Promise<WsUser> {
  const r = await api.post<AuthResponse>("/auth/apple", payload);
  await setTokens(r.data.access_token, r.data.refresh_token);
  return r.data.user;
}

export async function linkAppleRequest(payload: AppleLoginPayload): Promise<void> {
  await api.post("/auth/apple/link", payload);
}

export async function registerRequest(
  name: string,
  email: string,
  password: string
): Promise<WsUser> {
  const r = await api.post<AuthResponse>("/auth/register", { name, email, password });
  await setTokens(r.data.access_token, r.data.refresh_token);
  return r.data.user;
}

export async function fetchMe(): Promise<WsUser> {
  const r = await api.get<WsUser>("/auth/me");
  return r.data;
}

export async function logoutRequest(): Promise<void> {
  try {
    await api.post("/auth/logout");
  } catch {
    // best-effort — clearing local tokens is what actually logs us out
  }
  await clearTokens();
}

// ---------------------------------------------------------------------------
// Profile photo (avatar) — multipart upload / delete
// ---------------------------------------------------------------------------
export interface AvatarResponse {
  picture: string;
}

/**
 * Upload a profile photo. `uri` is a local file URI from expo-image-picker.
 *
 * On native we can pass the file descriptor object straight to FormData; on
 * web the Expo FormData polyfill needs a real Blob, so we fetch the (data or
 * blob) URI into a Blob first.
 */
export async function uploadAvatar(uri: string): Promise<AvatarResponse> {
  const form = new FormData();
  if (Platform.OS === "web") {
    const blob = await (await fetch(uri)).blob();
    form.append("file", blob, "avatar.jpg");
  } else {
    // React Native FormData accepts this shape for file uploads.
    form.append("file", {
      uri,
      name: "avatar.jpg",
      type: "image/jpeg",
    } as unknown as Blob);
  }
  const r = await api.post<AvatarResponse>("/user/avatar", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data;
}

/** Remove the current profile photo. */
export async function removeAvatar(): Promise<void> {
  await api.delete("/user/avatar");
}
