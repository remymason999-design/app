import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, ArrowRight } from "lucide-react";
import { apiPost, apiGet, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function ShareLink() {
    const { code } = useParams();
    const navigate = useNavigate();
    const { user, loading } = useAuth();
    const [target, setTarget] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);

    // Stash code for after-login redirect
    useEffect(() => {
        if (code) {
            try { sessionStorage.setItem("pending_share_code", code.toUpperCase()); } catch {}
        }
    }, [code]);

    // Once authed, look up the code preview
    useEffect(() => {
        if (loading) return;
        if (!user) return;
        apiPost("/share/lookup", { code: code.toUpperCase() })
            .then(setTarget)
            .catch((err) => setError(formatApiError(err.response?.data?.detail) || "Code not found"));
    }, [user, loading, code]);

    if (loading) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }

    if (!user) {
        // Send to login; AuthContext will redirect to /share/auto-link after sign-in
        return (
            <div className="min-h-screen px-6 py-12 max-w-md mx-auto" data-testid="share-link-signin">
                <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">WatchSmart</p>
                <h1 className="font-display text-3xl mt-3">A friend wants to compare watchlists</h1>
                <p className="text-zinc-400 mt-3 text-sm">
                    Sign in to send them a request. Code <span className="font-mono text-amber tracking-widest">{code?.toUpperCase()}</span> will be auto-applied.
                </p>
                <div className="mt-8 space-y-3">
                    <Link
                        to="/login"
                        className="block bg-amber hover:bg-amber-600 text-obsidian font-heading text-base text-center py-4 rounded-2xl amber-glow"
                        data-testid="share-signin-btn"
                    >
                        Sign in
                    </Link>
                    <Link
                        to="/register"
                        className="block glass text-center py-4 rounded-2xl hover:bg-white/5 font-medium"
                    >
                        Create account
                    </Link>
                </div>
            </div>
        );
    }

    const accept = async () => {
        setBusy(true);
        try {
            const r = await apiPost("/share/request", { code: code.toUpperCase() });
            try { sessionStorage.removeItem("pending_share_code"); } catch {}
            if (r.status === "accepted") {
                toast.success(`You're now sharing with ${r.friend?.name || target?.name}`);
                navigate(`/compare/${r.friend?.user_id || target?.user_id}`, { replace: true });
            } else if (r.status === "already_friends") {
                toast.info("Already sharing");
                navigate(`/compare/${target?.user_id}`, { replace: true });
            } else if (r.status === "already_requested") {
                toast.info("Request already pending");
                navigate("/friends", { replace: true });
            } else {
                toast.success("Request sent — they'll see it in their inbox");
                navigate("/friends", { replace: true });
            }
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't send request");
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="min-h-screen px-6 py-12 max-w-md mx-auto" data-testid="share-link-page">
            <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">WatchSmart</p>
            <h1 className="font-display text-3xl mt-3 mb-1">Share watchlists?</h1>

            {error ? (
                <div className="glass rounded-2xl p-5 mt-6">
                    <p className="text-sm text-zinc-300">{error}</p>
                    <Link to="/friends" className="block text-amber text-sm hover:underline mt-3">
                        Manage friends →
                    </Link>
                </div>
            ) : target ? (
                <motion.div
                    initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                    className="glass rounded-3xl p-6 mt-8" data-testid="share-target-card"
                >
                    <div className="flex items-center gap-4 mb-4">
                        {target.picture ? (
                            <img src={target.picture} alt={target.name} className="w-14 h-14 rounded-full object-cover" />
                        ) : (
                            <div className="w-14 h-14 rounded-full bg-amber/20 border border-amber/30 grid place-items-center font-heading text-amber text-xl">
                                {(target.name || "?").slice(0, 1).toUpperCase()}
                            </div>
                        )}
                        <div className="min-w-0">
                            <div className="font-heading text-lg truncate">{target.name}</div>
                            <div className="text-[11px] text-zinc-500">{target.watchlist_size} saved title{target.watchlist_size === 1 ? "" : "s"}</div>
                        </div>
                    </div>
                    <p className="text-sm text-zinc-400 mb-5">
                        Send a request — once they accept, you'll both see each other's watchlists update live.
                    </p>
                    <button
                        onClick={accept}
                        disabled={busy}
                        className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading text-base py-3.5 rounded-2xl flex items-center justify-center gap-2 amber-glow"
                        data-testid="share-accept-btn"
                    >
                        <Sparkles className="w-4 h-4" /> Send request
                        <ArrowRight className="w-4 h-4" />
                    </button>
                </motion.div>
            ) : (
                <div className="mt-8 grid place-items-center">
                    <div className="h-8 w-8 rounded-full border-2 border-amber border-t-transparent animate-spin" />
                </div>
            )}
        </div>
    );
}
