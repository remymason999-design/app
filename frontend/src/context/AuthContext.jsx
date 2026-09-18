import { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
import { apiGet, apiPost, setToken, setRefreshToken } from "@/lib/api";
import { analytics, switchIdentity, reset } from "@/lib/analytics";
import { captureLogoutAndReset } from "@/lib/analytics-flow";

const AuthCtx = createContext(null);

// Keys that hold per-user data and MUST be cleared on logout / user-switch
// to prevent the previous user's recommendations or state from leaking.
const PER_USER_SESSION_KEYS = ["ws_stack_v2"];

function clearPerUserSession() {
    try {
        for (const k of PER_USER_SESSION_KEYS) sessionStorage.removeItem(k);
    } catch {}
}

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    // `undefined` (not null) marks "we have not yet observed a user_id"; this
    // lets us distinguish initial mount from a real null→user transition so
    // we can wipe session data even on the very first login of a new browser
    // session that may still hold stale cache from a prior tab.
    const lastUserId = useRef(undefined);

    // When the active user changes (login as a different account, OR first
    // login of a fresh session), wipe per-user session caches so stale data
    // never bleeds across accounts/sessions.
    useEffect(() => {
        const uid = user?.user_id || null;
        const prev = lastUserId.current;
        if (prev !== undefined && prev !== uid) {
            // Real transition (login, logout, account switch).
            clearPerUserSession();
        } else if (prev === undefined && uid) {
            // First observed user on this mount — defensively clear any cache
            // left over from a previous browser session that wasn't logged out.
            clearPerUserSession();
        }
        lastUserId.current = uid;
        // Never identify a new account under the previous account's identity.
        // Reset exactly once for real account switches and logout transitions.
        if (uid) switchIdentity(user);
        else if (prev) reset();
    }, [user?.user_id]);

    const refresh = useCallback(async () => {
        try {
            const u = await apiGet("/auth/me");
            setUser(u);
            return u;
        } catch (err) {
            // Only treat 401/403 as "logged out" — network blips shouldn't sign the user out.
            const status = err?.response?.status;
            if (status === 401 || status === 403) {
                // /auth/me is authoritative: clear any persisted SDK identity
                // even when this is the first auth observation in this tab.
                if (lastUserId.current === undefined) reset();
                setUser(null);
            } else if (status) {
                // Surface server errors so they don't disappear silently.
                console.error("[AuthContext.refresh] unexpected status", status, err?.response?.data);
            }
            return null;
        }
    }, []);

    useEffect(() => {
        refresh().finally(() => setLoading(false));
    }, [refresh]);

    const logout = async () => {
        try {
            await apiPost("/auth/logout");
        } catch (e) {
            // Network failure shouldn't trap the user — clear local state anyway.
            console.error("[AuthContext.logout] server logout failed", e);
        }
        setToken(null);
        setRefreshToken(null);
        clearPerUserSession();
        captureLogoutAndReset(analytics, user);
        lastUserId.current = null;
        setUser(null);
    };

    return (
        <AuthCtx.Provider value={{ user, setUser, loading, refresh, logout }}>
            {children}
        </AuthCtx.Provider>
    );
}

export const useAuth = () => useContext(AuthCtx);
