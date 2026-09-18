import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost, setToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function AuthCallback() {
    const navigate = useNavigate();
    const { setUser, refresh } = useAuth();
    const processed = useRef(false);

    useEffect(() => {
        if (processed.current) return;
        processed.current = true;

        const params = new URLSearchParams(window.location.search);
        const code = params.get("code");
        const provider = params.get("provider") || "google";
        const error = params.get("error");

        (async () => {
            try {
                if (error) throw new Error(`OAuth error: ${error}`);
                if (!code) throw new Error("No authorisation code received");

                const redirectUri = window.location.origin + "/auth/callback";
                const data = await apiPost(`/auth/${provider}/callback`, {
                    code,
                    redirect_uri: redirectUri,
                });
                if (data.access_token) setToken(data.access_token);
                setUser(data.user);
                window.history.replaceState({}, "", "/");
                const next = data.user.onboarding_completed ? "/discover" : "/onboarding";
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
