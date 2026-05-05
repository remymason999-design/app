import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
    Copy, Check, Users, UserPlus, Inbox, Share2, X,
    ArrowLeft, ArrowRight, Trash2, Sparkles,
} from "lucide-react";
import { apiGet, apiPost, apiDelete, formatApiError } from "@/lib/api";
import { toast } from "sonner";

export default function Friends() {
    const navigate = useNavigate();
    const [me, setMe] = useState(null);
    const [friends, setFriends] = useState([]);
    const [requests, setRequests] = useState({ incoming: [], outgoing: [] });
    const [code, setCode] = useState("");
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [copied, setCopied] = useState(null);

    const refresh = async () => {
        const [m, f, r] = await Promise.all([
            apiGet("/share/me"),
            apiGet("/share/friends"),
            apiGet("/share/requests"),
        ]);
        setMe(m); setFriends(f); setRequests(r);
    };

    useEffect(() => {
        refresh().finally(() => setLoading(false));
        const t = setInterval(() => { refresh().catch(() => {}); }, 5000);
        return () => clearInterval(t);
    }, []);

    const copyTo = async (text, key) => {
        await navigator.clipboard.writeText(text);
        setCopied(key);
        toast.success("Copied");
        setTimeout(() => setCopied(null), 1800);
    };

    const sendRequest = async (e) => {
        e?.preventDefault?.();
        const trimmed = code.trim().toUpperCase();
        if (!trimmed) return;
        setBusy(true);
        try {
            const r = await apiPost("/share/request", { code: trimmed });
            if (r.status === "sent") toast.success("Request sent");
            else if (r.status === "accepted") toast.success(`You're now sharing with ${r.friend?.name || "your friend"}`);
            else if (r.status === "already_friends") toast.info("Already sharing with them");
            else if (r.status === "already_requested") toast.info("Request already pending");
            setCode("");
            refresh();
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't send request");
        } finally {
            setBusy(false);
        }
    };

    const accept = async (id) => {
        setBusy(true);
        try {
            await apiPost(`/share/requests/${id}/accept`);
            toast.success("Accepted");
            refresh();
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't accept");
        } finally {
            setBusy(false);
        }
    };

    const reject = async (id) => {
        setBusy(true);
        try {
            await apiPost(`/share/requests/${id}/reject`);
            refresh();
        } catch {
            toast.error("Couldn't reject");
        } finally {
            setBusy(false);
        }
    };

    const unfriend = async (id) => {
        if (!confirm("Stop sharing watchlists with this person?")) return;
        await apiDelete(`/share/friends/${id}`);
        refresh();
    };

    const nativeShare = async () => {
        if (!me?.share_url) return;
        if (navigator.share) {
            try {
                await navigator.share({
                    title: "Compare watchlists on WatchSmart",
                    text: `Add me on WatchSmart — code ${me.share_code}`,
                    url: me.share_url,
                });
            } catch {/* user cancelled */}
        } else {
            copyTo(me.share_url, "share-url");
        }
    };

    if (loading) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="friends-page">
            <button
                onClick={() => navigate(-1)}
                className="flex items-center gap-2 text-zinc-400 hover:text-zinc-100 mb-6 text-sm"
                data-testid="friends-back"
            >
                <ArrowLeft className="w-4 h-4" /> Back
            </button>

            <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Compare with friends</p>
            <h1 className="font-display text-4xl mt-2 leading-tight">Two heads.<br />Better picks.</h1>

            {/* My code card */}
            <motion.div
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className="glass rounded-3xl p-5 mt-8" data-testid="my-share-card"
            >
                <div className="flex items-start justify-between gap-3 mb-4">
                    <div>
                        <p className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1">Your code</p>
                        <div className="font-display text-4xl tracking-[0.18em]" data-testid="my-share-code">{me?.share_code}</div>
                    </div>
                    <button
                        onClick={() => copyTo(me?.share_code || "", "code")}
                        className="h-10 w-10 grid place-items-center rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
                        aria-label="Copy code"
                        data-testid="copy-code"
                    >
                        {copied === "code" ? <Check className="w-4 h-4 text-amber" /> : <Copy className="w-4 h-4" />}
                    </button>
                </div>
                <div className="flex items-center gap-2 bg-black/30 rounded-xl p-2.5 border border-white/5">
                    <code className="text-[11px] text-zinc-300 break-all flex-1 px-1" data-testid="my-share-url">
                        {me?.share_url}
                    </code>
                    <button
                        onClick={nativeShare}
                        className="shrink-0 px-3 py-1.5 rounded-lg bg-amber text-obsidian text-xs font-heading hover:bg-amber-600 flex items-center gap-1.5"
                        data-testid="share-link-btn"
                    >
                        <Share2 className="w-3.5 h-3.5" /> Share
                    </button>
                </div>
            </motion.div>

            {/* Add by code */}
            <form onSubmit={sendRequest} className="mt-6 space-y-2" data-testid="add-friend-form">
                <p className="text-[11px] uppercase tracking-wider text-zinc-500">Add a friend by code</p>
                <div className="flex gap-2">
                    <input
                        value={code}
                        onChange={(e) => setCode(e.target.value.toUpperCase().slice(0, 12))}
                        placeholder="e.g. K7M3PQ"
                        autoCapitalize="characters"
                        className="flex-1 bg-white/4 border border-white/10 rounded-xl px-4 py-3 font-mono tracking-[0.2em] outline-none focus:border-amber/50"
                        data-testid="friend-code-input"
                    />
                    <button
                        type="submit"
                        disabled={busy || !code.trim()}
                        className="px-5 rounded-xl bg-amber hover:bg-amber-600 disabled:opacity-50 text-obsidian font-heading text-sm flex items-center gap-2"
                        data-testid="send-request-btn"
                    >
                        <UserPlus className="w-4 h-4" /> Send
                    </button>
                </div>
            </form>

            {/* Incoming requests */}
            {requests.incoming.length > 0 && (
                <div className="mt-8" data-testid="incoming-requests">
                    <h2 className="font-heading text-base mb-3 flex items-center gap-2">
                        <Inbox className="w-4 h-4 text-amber" />
                        Incoming requests
                        <span className="ml-auto text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber/20 text-amber">
                            {requests.incoming.length}
                        </span>
                    </h2>
                    <ul className="space-y-2">
                        <AnimatePresence initial={false}>
                            {requests.incoming.map((r) => (
                                <motion.li
                                    key={r.request_id}
                                    initial={{ opacity: 0, y: 8 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, x: -20 }}
                                    className="glass rounded-2xl p-4 flex items-center gap-3"
                                    data-testid={`incoming-${r.request_id}`}
                                >
                                    <Avatar user={r.from} />
                                    <div className="flex-1 min-w-0">
                                        <div className="font-heading text-sm truncate">{r.from?.name || "Someone"}</div>
                                        <div className="text-[11px] text-zinc-500">wants to compare watchlists</div>
                                    </div>
                                    <button
                                        onClick={() => accept(r.request_id)}
                                        disabled={busy}
                                        className="h-9 px-3 rounded-lg bg-amber text-obsidian text-xs font-heading hover:bg-amber-600"
                                        data-testid={`accept-${r.request_id}`}
                                    >
                                        Accept
                                    </button>
                                    <button
                                        onClick={() => reject(r.request_id)}
                                        disabled={busy}
                                        className="h-9 w-9 grid place-items-center rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400"
                                        aria-label="Reject"
                                        data-testid={`reject-${r.request_id}`}
                                    >
                                        <X className="w-4 h-4" />
                                    </button>
                                </motion.li>
                            ))}
                        </AnimatePresence>
                    </ul>
                </div>
            )}

            {/* Outgoing requests */}
            {requests.outgoing.length > 0 && (
                <div className="mt-6" data-testid="outgoing-requests">
                    <h2 className="font-heading text-base mb-3 text-zinc-400">Pending</h2>
                    <ul className="space-y-2">
                        {requests.outgoing.map((r) => (
                            <li key={r.request_id} className="rounded-2xl px-4 py-3 border border-white/5 flex items-center gap-3 bg-white/[0.02]">
                                <Avatar user={r.to} />
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm truncate">{r.to?.name || "Friend"}</div>
                                    <div className="text-[11px] text-zinc-500">Awaiting their response</div>
                                </div>
                                <Sparkles className="w-3.5 h-3.5 text-zinc-600" />
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Friends list */}
            <div className="mt-10" data-testid="friends-list">
                <h2 className="font-heading text-base mb-3 flex items-center gap-2">
                    <Users className="w-4 h-4 text-amber" /> Your watchlist friends
                </h2>
                {friends.length === 0 ? (
                    <p className="text-sm text-zinc-500 glass rounded-2xl p-5">
                        Share your code with someone to start comparing watchlists.
                    </p>
                ) : (
                    <ul className="space-y-2">
                        {friends.map((f) => (
                            <motion.li
                                key={f.user_id}
                                initial={{ opacity: 0, y: 6 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="glass rounded-2xl p-4 flex items-center gap-3"
                                data-testid={`friend-${f.user_id}`}
                            >
                                <Avatar user={f} />
                                <div className="flex-1 min-w-0">
                                    <div className="font-heading text-sm truncate">{f.name}</div>
                                    <div className="text-[11px] text-zinc-500">{f.watchlist_size} saved</div>
                                </div>
                                <button
                                    onClick={() => navigate(`/compare/${f.user_id}`)}
                                    className="h-9 px-3 rounded-lg bg-amber text-obsidian text-xs font-heading hover:bg-amber-600 flex items-center gap-1.5"
                                    data-testid={`compare-${f.user_id}`}
                                >
                                    Compare <ArrowRight className="w-3.5 h-3.5" />
                                </button>
                                <button
                                    onClick={() => unfriend(f.user_id)}
                                    className="h-9 w-9 grid place-items-center rounded-lg hover:bg-red-500/10 text-zinc-500 hover:text-red-300"
                                    aria-label="Unfriend"
                                    data-testid={`unfriend-${f.user_id}`}
                                >
                                    <Trash2 className="w-3.5 h-3.5" />
                                </button>
                            </motion.li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    );
}

function Avatar({ user }) {
    const initial = (user?.name || "?").slice(0, 1).toUpperCase();
    if (user?.picture) {
        return <img src={user.picture} alt={user.name} className="w-10 h-10 rounded-full object-cover shrink-0" />;
    }
    return (
        <div className="w-10 h-10 rounded-full bg-amber/15 border border-amber/30 grid place-items-center font-heading text-amber shrink-0">
            {initial}
        </div>
    );
}
