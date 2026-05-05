import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Sparkles, Heart, Star, Activity, Wand2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import { toast } from "sonner";

const POLL_MS = 3000;

export default function Compare() {
    const { friendId } = useParams();
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [tab, setTab] = useState("overlap"); // overlap | only_me | only_them | recs
    const [pulse, setPulse] = useState(false);
    const lastSync = useRef(null);

    useEffect(() => {
        let alive = true;
        const fetchOnce = async () => {
            try {
                const r = await apiGet(`/share/compare/${friendId}`);
                if (!alive) return;
                // Pulse only when data actually changed
                const sig = JSON.stringify([r.overlap_count, r.only_me?.length, r.only_them?.length]);
                if (lastSync.current && lastSync.current !== sig) {
                    setPulse(true);
                    setTimeout(() => alive && setPulse(false), 900);
                }
                lastSync.current = sig;
                setData(r);
            } catch (e) {
                if (e.response?.status === 403) {
                    toast.error("You're not sharing watchlists with this user");
                    navigate("/friends", { replace: true });
                }
            } finally {
                if (alive) setLoading(false);
            }
        };
        fetchOnce();
        const t = setInterval(fetchOnce, POLL_MS);
        return () => { alive = false; clearInterval(t); };
    }, [friendId, navigate]);

    if (loading || !data) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }

    const tabs = [
        { id: "overlap", label: "Both", count: data.overlap.length, testid: "tab-overlap" },
        { id: "only_me", label: "You", count: data.only_me.length, testid: "tab-only-me" },
        { id: "only_them", label: data.them.name.split(" ")[0], count: data.only_them.length, testid: "tab-only-them" },
        { id: "recs", label: "For you both", count: data.recommendations.length, testid: "tab-recs" },
    ];

    const list =
        tab === "overlap" ? data.overlap :
        tab === "only_me" ? data.only_me :
        tab === "only_them" ? data.only_them :
        data.recommendations;

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="compare-page">
            <button
                onClick={() => navigate("/friends")}
                className="flex items-center gap-2 text-zinc-400 hover:text-zinc-100 mb-6 text-sm"
                data-testid="compare-back"
            >
                <ArrowLeft className="w-4 h-4" /> Friends
            </button>

            {/* Header with both avatars */}
            <div className="flex items-center justify-between mb-5">
                <div className="flex items-center -space-x-3">
                    <Avatar user={data.you} ring />
                    <Avatar user={data.them} ring />
                </div>
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500" data-testid="live-indicator">
                    <span className={`w-1.5 h-1.5 rounded-full bg-amber transition-all ${pulse ? "scale-150 shadow-[0_0_10px_rgba(245,158,11,0.8)]" : ""}`} />
                    Live
                </div>
            </div>

            <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">You & {data.them.name}</p>
            <h1 className="font-display text-3xl mt-1 leading-tight">
                {data.overlap.length > 0 ? (
                    <>You both saved <span className="text-amber" data-testid="overlap-count">{data.overlap.length}</span> title{data.overlap.length === 1 ? "" : "s"}.</>
                ) : (
                    <>No overlap — yet.</>
                )}
            </h1>

            {/* Pick tonight */}
            {data.pick_tonight && (
                <motion.div
                    initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                    className="mt-6 glass rounded-3xl p-5 border border-amber/20"
                    data-testid="pick-tonight"
                >
                    <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-amber" />
                        <span className="text-[10px] uppercase tracking-[0.22em] text-amber font-heading">
                            {data.overlap.length > 0 ? "Pick tonight" : "What you'll both love"}
                        </span>
                    </div>
                    <button
                        onClick={() => navigate(`/movie/${data.pick_tonight.id}`)}
                        className="flex items-center gap-4 w-full text-left group"
                        data-testid="pick-tonight-cta"
                    >
                        <div className="w-20 h-28 rounded-xl bg-velvet overflow-hidden shrink-0 ring-1 ring-white/10">
                            {data.pick_tonight.poster_url && (
                                <img
                                    loading="lazy"
                                    src={data.pick_tonight.poster_url}
                                    alt={data.pick_tonight.title}
                                    className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                                />
                            )}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="font-heading text-base leading-tight mb-1 truncate">{data.pick_tonight.title}</div>
                            <div className="flex items-center gap-2 text-[11px] text-zinc-400 mb-2">
                                {data.pick_tonight.rating != null && (
                                    <span className="flex items-center gap-1">
                                        <Star className="w-3 h-3 fill-amber text-amber" /> {data.pick_tonight.rating}
                                    </span>
                                )}
                                <span className="text-zinc-600">·</span>
                                <span className="truncate">{(data.pick_tonight.genres || []).join(" · ")}</span>
                            </div>
                            <div className="text-xs text-zinc-300">Open details →</div>
                        </div>
                    </button>
                </motion.div>
            )}

            {/* Tabs */}
            <div className="grid grid-cols-4 gap-1.5 mt-6 p-1 bg-white/4 rounded-2xl border border-white/5" data-testid="compare-tabs">
                {tabs.map((t) => (
                    <button
                        key={t.id}
                        onClick={() => setTab(t.id)}
                        data-testid={t.testid}
                        className={`relative px-2 py-2.5 rounded-xl text-[11px] font-heading transition-colors ${
                            tab === t.id ? "bg-amber text-obsidian" : "text-zinc-400 hover:text-zinc-100"
                        }`}
                    >
                        <div className="truncate">{t.label}</div>
                        <div className={`text-[10px] mt-0.5 ${tab === t.id ? "text-obsidian/70" : "text-zinc-500"}`}>{t.count}</div>
                    </button>
                ))}
            </div>

            {/* List */}
            <div className="mt-5" data-testid={`compare-list-${tab}`}>
                {list.length === 0 ? (
                    <EmptyState tab={tab} themName={data.them.name} />
                ) : (
                    <ul className="grid grid-cols-3 gap-2.5">
                        <AnimatePresence initial={false}>
                            {list.map((m) => (
                                <motion.li
                                    key={m.id}
                                    initial={{ opacity: 0, scale: 0.96 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    exit={{ opacity: 0, scale: 0.96 }}
                                    transition={{ duration: 0.18 }}
                                    onClick={() => navigate(`/movie/${m.id}`)}
                                    className="cursor-pointer group"
                                    data-testid={`compare-card-${m.id}`}
                                >
                                    <div className="aspect-[2/3] rounded-xl bg-velvet overflow-hidden ring-1 ring-white/5 group-hover:ring-amber/30 transition-shadow">
                                        {m.poster_url ? (
                                            <img loading="lazy" src={m.poster_url} alt={m.title} className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform" />
                                        ) : (
                                            <div className="w-full h-full grid place-items-center text-zinc-600 text-[10px] p-1 text-center">{m.title}</div>
                                        )}
                                    </div>
                                    <div className="text-[10px] mt-1.5 text-zinc-300 line-clamp-1">{m.title}</div>
                                    {m.rating != null && (
                                        <div className="text-[10px] text-zinc-500 flex items-center gap-1">
                                            <Star className="w-2.5 h-2.5 fill-amber text-amber" /> {m.rating}
                                        </div>
                                    )}
                                </motion.li>
                            ))}
                        </AnimatePresence>
                    </ul>
                )}
            </div>

            <div className="mt-8 flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-600">
                <Activity className="w-3 h-3" /> Updates every 3s · synced {timeAgo(data.synced_at)}
            </div>
        </div>
    );
}

function EmptyState({ tab, themName }) {
    const messages = {
        overlap: { icon: Heart, title: "No shared picks yet", body: "Keep swiping — overlap appears the moment you both save the same title." },
        only_me: { icon: Heart, title: "You haven't saved anything yet", body: "Open Discover and start swiping right." },
        only_them: { icon: Heart, title: `${themName} hasn't saved anything`, body: "Once they start swiping, their picks will appear here." },
        recs: { icon: Wand2, title: "Building recommendations", body: "Keep using the app — once we learn both your tastes, smart picks land here." },
    };
    const m = messages[tab];
    const Icon = m.icon;
    return (
        <div className="glass rounded-2xl p-6 text-center">
            <Icon className="w-5 h-5 text-amber mx-auto mb-2" />
            <div className="font-heading text-sm mb-1">{m.title}</div>
            <p className="text-xs text-zinc-500">{m.body}</p>
        </div>
    );
}

function Avatar({ user, ring }) {
    const initial = (user?.name || "?").slice(0, 1).toUpperCase();
    if (user?.picture) {
        return (
            <img
                src={user.picture}
                alt={user.name}
                className={`w-10 h-10 rounded-full object-cover ${ring ? "ring-2 ring-obsidian" : ""}`}
            />
        );
    }
    return (
        <div className={`w-10 h-10 rounded-full bg-amber/20 border border-amber/40 grid place-items-center font-heading text-amber ${ring ? "ring-2 ring-obsidian" : ""}`}>
            {initial}
        </div>
    );
}

function timeAgo(iso) {
    if (!iso) return "just now";
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 5) return "just now";
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    return `${Math.floor(diff / 60)}m ago`;
}
