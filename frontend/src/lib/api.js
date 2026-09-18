import axios from "axios";
import { capture, reset, EVENTS } from "@/lib/analytics";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const TOKEN_KEY = "ws_access_token";
const REFRESH_KEY = "ws_refresh_token";

// Dev-only helper: allow bootstrapping a session token via ?dev_token=…
// (used for automated preview/screenshot verification; no-op in production).
try {
    if (process.env.NODE_ENV === "development" && typeof window !== "undefined") {
        const t = new URLSearchParams(window.location.search).get("dev_token");
        if (t) {
            localStorage.setItem(TOKEN_KEY, t);
            // Skip first-run overlays so automated previews show the page itself.
            localStorage.setItem("ws_tutorial_v1_seen", "1");
        }
    }
} catch {}

export const getToken = () => {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
};
export const setToken = (token) => {
    try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); } catch {}
};

export const getRefreshToken = () => {
    try { return localStorage.getItem(REFRESH_KEY); } catch { return null; }
};
export const setRefreshToken = (token) => {
    try { token ? localStorage.setItem(REFRESH_KEY, token) : localStorage.removeItem(REFRESH_KEY); } catch {}
};

const api = axios.create({ baseURL: API, withCredentials: true });

api.interceptors.request.use((config) => {
    const t = getToken();
    if (t) {
        config.headers = config.headers || {};
        config.headers.Authorization = `Bearer ${t}`;
    }
    return config;
});

let refreshing = null;
let sessionExpiredHandled = false;

function handleSessionExpired() {
    if (sessionExpiredHandled) return;
    sessionExpiredHandled = true;
    capture(EVENTS.SESSION_EXPIRED);
    reset();
    try {
        setToken(null);
        setRefreshToken(null);
        // Clear any per-user cached state.
        sessionStorage.removeItem("ws_stack_v2");
    } catch {}
    const path = window.location.pathname;
    const isPublic = ["/", "/login", "/register", "/forgot-password", "/reset-password"]
        .some((p) => path === p || path.startsWith(p + "/"));
    if (!isPublic) {
        // Friendly toast (sonner is globally mounted) + redirect to login.
        import("sonner").then(({ toast }) => {
            toast.error("Your session expired — please sign in again.");
        }).catch(() => {});
        setTimeout(() => {
            window.location.assign("/login");
            sessionExpiredHandled = false;
        }, 250);
    } else {
        sessionExpiredHandled = false;
    }
}

api.interceptors.response.use(
    (r) => {
        if (r.data?.refresh_token) setRefreshToken(r.data.refresh_token);
        return r;
    },
    async (error) => {
        const original = error.config || {};
        const status = error.response?.status;
        // Skip refresh for auth endpoints themselves (login/register/me on boot, etc.)
        const isAuthEndpoint = original.url?.includes("/auth/");
        if (status === 401 && !original._retry && !isAuthEndpoint) {
            original._retry = true;
            try {
                refreshing = refreshing || (async () => {
                    const rt = getRefreshToken();
                    const headers = { "Content-Type": "application/json" };
                    if (rt) headers["Authorization"] = `Bearer ${rt}`;
                    const resp = await fetch(`${API}/auth/refresh`, {
                        method: "POST",
                        headers,
                        credentials: "include",
                    });
                    if (!resp.ok) throw new Error("refresh failed");
                    const data = await resp.json();
                    const tok = data?.access_token;
                    if (tok) setToken(tok);
                    if (data?.refresh_token) setRefreshToken(data.refresh_token);
                    return tok;
                })().finally(() => { refreshing = null; });
                const tok = await refreshing;
                if (tok) {
                    original.headers = original.headers || {};
                    original.headers.Authorization = `Bearer ${tok}`;
                    return api(original);
                }
                handleSessionExpired();
            } catch {
                handleSessionExpired();
            }
        }
        // Attach a user-friendly message to EVERY rejected request so callers
        // never have to surface a raw Axios error object / stack to the user.
        try { error.friendlyMessage = getFriendlyMessage(error); } catch {}
        return Promise.reject(error);
    }
);

export const apiGet = (url, config) => api.get(url, config).then((r) => r.data);
export const apiPost = (url, data, config) => api.post(url, data, config).then((r) => r.data);
export const apiPut = (url, data, config) => api.put(url, data, config).then((r) => r.data);
export const apiDelete = (url, config) => api.delete(url, config).then((r) => r.data);

const FALLBACK_ERROR = "Something went wrong. Please try again.";
const NETWORK_ERROR = "Can't reach the server. Check your connection and try again.";
const SERVER_ERROR = "Something went wrong on our end. Please try again in a moment.";

/**
 * Turn any Axios error into a friendly, user-safe message. Handles the three
 * cases components shouldn't have to reason about individually:
 *   - no response (network failure / backend restart / timeout)
 *   - 5xx server errors
 *   - 4xx errors carrying a `detail` payload
 * Never returns a raw error object, stack, or JSON.
 */
export function getFriendlyMessage(error) {
    if (!error) return FALLBACK_ERROR;
    const status = error.response?.status;
    if (status == null) {
        // No HTTP response at all → network / connectivity / server down.
        return NETWORK_ERROR;
    }
    if (status >= 500) return SERVER_ERROR;
    const detail = error.response?.data?.detail ?? error.response?.data;
    return formatApiError(detail);
}

/**
 * Convert any backend error payload into a friendly user-facing string.
 * Guarantees: never returns "[object Object]", "undefined", raw JSON,
 * or empty strings. Always returns a non-empty user-friendly message.
 */
export function formatApiError(detail) {
    if (detail == null) return FALLBACK_ERROR;
    if (typeof detail === "string") {
        const s = detail.trim();
        return s || FALLBACK_ERROR;
    }
    if (Array.isArray(detail)) {
        const msgs = detail
            .map((e) => (typeof e === "string" ? e : e?.msg))
            .filter((m) => typeof m === "string" && m.trim());
        return msgs.length ? msgs.join(" ") : FALLBACK_ERROR;
    }
    if (typeof detail === "object") {
        if (typeof detail.msg === "string" && detail.msg.trim()) return detail.msg;
        if (typeof detail.message === "string" && detail.message.trim()) return detail.message;
        if (typeof detail.error === "string" && detail.error.trim()) return detail.error;
        return FALLBACK_ERROR;
    }
    return FALLBACK_ERROR;
}

export default api;
