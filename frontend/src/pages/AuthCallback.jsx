import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function AuthCallback() {
    const navigate = useNavigate();
    const { setUser, refresh } = useAuth();
    const processed = useRef(false);

    useEffect(() => {
        if (processed.current) return;
        processed.current = true;
        const hash = window.location.hash || "";
        const match = hash.match(/session_id=([^&]+)/);
        const sessionId = match?.[1];
        (async () => {
            try {
                if (!sessionId) throw new Error("No session id");
                const data = await apiPost("/auth/google/session", null, {
                    headers: { "X-Session-ID": sessionId },
                });
                setUser(data.user);
                window.history.replaceState({}, "", "/discover");
                const next = data.user.subscriptions?.length ? "/discover" : "/onboarding/services";
                navigate(next, { replace: true });
            } catch {
                await refresh();
                navigate("/login", { replace: true });
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        <div className="min-h-screen flex items-center justify-center bg-obsidian">
            <div className="flex flex-col items-center gap-4" data-testid="auth-callback">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
                <p className="text-zinc-400 text-sm">Signing you in…</p>
            </div>
        </div>
    );
}
