import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        try {
            const u = await apiGet("/auth/me");
            setUser(u);
            return u;
        } catch {
            setUser(null);
            return null;
        }
    }, []);

    useEffect(() => {
        // skip if returning from emergent oauth
        if (typeof window !== "undefined" && window.location.hash?.includes("session_id=")) {
            setLoading(false);
            return;
        }
        refresh().finally(() => setLoading(false));
    }, [refresh]);

    const logout = async () => {
        try {
            await apiPost("/auth/logout");
        } catch {}
        setUser(null);
    };

    return (
        <AuthCtx.Provider value={{ user, setUser, loading, refresh, logout }}>
            {children}
        </AuthCtx.Provider>
    );
}

export const useAuth = () => useContext(AuthCtx);
