import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Eye, Star, Clock } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { motion } from "framer-motion";
import { toast } from "sonner";
import AccountMenu from "@/components/AccountMenu";
import { useAuth } from "@/context/AuthContext";
import { ProviderLogo } from "@/components/ProviderLogo";
import { formatRuntime } from "@/lib/format";

const SORT_OPTIONS = [
    { value: "recent", label: "Recently watched" },
    { value: "title", label: "Title (A–Z)" },
    { value: "rating", label: "Highest rated" },
    { value: "year", label: "Newest released" },
];

export default function Watched() {
    const { user, refresh } = useAuth();
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [sort, setSort] = useState(() => localStorage.getItem("ws_watched_sort") || "recent");
    const userSubs = user?.subscriptions || [];

    const sortedItems = useMemo(() => {
        const arr = [...items];
        if (sort === "title") arr.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
        else if (sort === "rating") arr.sort((a, b) => (b.rating || 0) - (a.rating || 0));
        else if (sort === "year") arr.sort((a, b) => (b.year || 0) - (a.year || 0));
        return arr;
    }, [items, sort]);

    const onSortChange = (v) => {
        setSort(v);
        try { localStorage.setItem("ws_watched_sort", v); } catch {}
    };

    const load = async () => {
        setLoading(true);
        setError(null);
        try {
            setItems(await apiGet("/watched"));
        } catch (err) {
            setError(err?.response?.status === 401 ? "Please sign in again." : "Couldn't load your watched list. Check your connection.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        const onFocus = () => { if (document.visibilityState === "visible") load(); };
        document.addEventListener("visibilitychange", onFocus);
        window.addEventListener("focus", load);
        return () => {
            document.removeEventListener("visibilitychange", onFocus);
            window.removeEventListener("focus", load);
        };
    }, []);

    const unmark = async (movie_id) => {
        const prev = items;
        setItems((it) => it.filter((m) => m.id !== movie_id));
        try {
            await apiPost("/user/action", { movie_id, action: "unwatched" });
            await refresh();
            toast("Marked as unwatched");
        } catch {
            setItems(prev);
            toast.error("Couldn't update. Try again.");
        }
    };

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="watched-page">
            <div className="flex items-start justify-between mb-8">
                <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Already seen</p>
                    <h1 className="font-display text-4xl mt-2">Watched</h1>
                </div>
                <AccountMenu />
            </div>

            {!loading && !error && items.length > 0 && (
                <div className="flex items-center justify-end mb-4">
                    <label className="text-xs text-zinc-500 mr-2" htmlFor="watched-sort">Sort</label>
                    <select
                        id="watched-sort"
                        value={sort}
                        onChange={(e) => onSortChange(e.target.value)}
                        data-testid="watched-sort"
                        className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-amber"
                    >
                        {SORT_OPTIONS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                </div>
            )}

            {error && !loading ? (
                <div className="text-center py-20" data-testid="watched-error">
                    <h3 className="font-heading text-xl mb-2">Something went wrong</h3>
                    <p className="text-sm text-zinc-400 mb-6">{error}</p>
                    <button onClick={load} className="px-5 py-3 rounded-xl bg-amber text-obsidian font-heading" data-testid="watched-retry">
                        Try again
                    </button>
                </div>
            ) : loading ? (
                <div className="grid grid-cols-2 gap-3">
                    {[1, 2, 3, 4].map(i => (
                        <div key={i} className="animate-pulse">
                            <div className="aspect-[2/3] rounded-2xl bg-white/8" />
                            <div className="h-3 w-3/4 rounded mt-2 bg-white/6" />
                            <div className="h-2.5 w-1/2 rounded mt-1 bg-white/5" />
                        </div>
                    ))}
                </div>
            ) : items.length === 0 ? (
                <div className="text-center py-20">
                    <div className="w-16 h-16 rounded-2xl bg-amber/15 grid place-items-center mx-auto mb-4">
                        <Eye className="w-7 h-7 text-amber" strokeWidth={1.6} />
                    </div>
                    <h3 className="font-heading text-xl mb-2">Nothing marked watched yet</h3>
                    <p className="text-sm text-zinc-400 mb-6">Mark titles "watched" to keep them out of your discovery feed.</p>
                    <Link to="/discover" className="inline-block px-5 py-3 rounded-xl bg-amber text-obsidian font-heading">
                        Browse Discover
                    </Link>
                </div>
            ) : (
                <ul className="grid grid-cols-2 gap-3">
                    {sortedItems.map((m, i) => {
                        const runtime = m.type === "tv"
                            ? (m.seasons?.length ? `${m.seasons.length}S` : null)
                            : (formatRuntime(m.runtime) || "—");
                        const providers = (m.available_on || []);
                        const sortedProviders = [
                            ...providers.filter(sid => userSubs.includes(sid)),
                            ...providers.filter(sid => !userSubs.includes(sid)),
                        ].slice(0, 2);

                        return (
                            <motion.li
                                key={m.id}
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: i * 0.04 }}
                                data-testid={`watched-item-${m.id}`}
                            >
                                <Link to={`/movie/${m.id}`} className="block relative aspect-[2/3] rounded-2xl overflow-hidden card-shadow bg-white/8">
                                    {m.poster_url && (
                                        <img
                                            loading="lazy"
                                            src={m.poster_url}
                                            alt={m.title}
                                            className="absolute inset-0 w-full h-full object-cover"
                                            style={{ opacity: 0, transition: "opacity 0.35s" }}
                                            onLoad={(e) => { e.target.style.opacity = 1; }}
                                            onError={(e) => { e.target.style.display = "none"; }}
                                        />
                                    )}
                                    <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/30 to-transparent" />

                                    {sortedProviders.length > 0 && (
                                        <div className="absolute top-2 right-2 flex flex-col gap-1">
                                            {sortedProviders.map(sid => (
                                                <ProviderLogo
                                                    key={sid}
                                                    sid={sid}
                                                    size={22}
                                                    shape="rounded-md"
                                                    subscribed={userSubs.includes(sid)}
                                                />
                                            ))}
                                        </div>
                                    )}

                                    <div className="absolute top-2 left-2 h-6 w-6 rounded-full bg-black/60 backdrop-blur grid place-items-center">
                                        <Eye className="w-3 h-3 text-amber" strokeWidth={2} />
                                    </div>

                                    <div className="absolute bottom-0 inset-x-0 p-3">
                                        <div className="font-heading text-sm leading-tight line-clamp-2">{m.title}</div>
                                        <div className="flex items-center justify-between mt-1">
                                            <div className="flex items-center gap-1 text-xs text-zinc-300">
                                                <Star className="w-3 h-3 fill-amber text-amber" />
                                                {m.rating?.toFixed(1)}
                                            </div>
                                            {runtime && (
                                                <div className="flex items-center gap-0.5 text-[10px] text-zinc-400">
                                                    <Clock className="w-2.5 h-2.5" />
                                                    {runtime}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </Link>
                                <button
                                    onClick={() => unmark(m.id)}
                                    className="mt-2 w-full text-xs text-zinc-500 hover:text-amber transition-colors"
                                    data-testid={`watched-unmark-${m.id}`}
                                >
                                    Mark unwatched
                                </button>
                            </motion.li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}
