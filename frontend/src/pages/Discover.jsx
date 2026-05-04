import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence, useMotionValue, useTransform } from "framer-motion";
import { Heart, X, Eye, Info, Star, Sparkles, Search, SlidersHorizontal, TrendingUp, Calendar, MapPin } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import Tutorial, { shouldShowTutorial } from "@/components/Tutorial";
import AccountMenu from "@/components/AccountMenu";
import NotificationBell from "@/components/NotificationBell";
import FiltersSheet from "@/components/FiltersSheet";

const TABS = [
    { id: "for-you", label: "For you", endpoint: "/discover", icon: Sparkles },
    { id: "trending", label: "Trending", endpoint: "/sections/trending", icon: TrendingUp },
    { id: "upcoming", label: "Upcoming", endpoint: "/sections/upcoming", icon: Calendar },
    { id: "local", label: "Popular near you", endpoint: "/sections/popular-locally", icon: MapPin },
];

export default function Discover() {
    const navigate = useNavigate();
    const { user, refresh } = useAuth();
    const [tab, setTab] = useState("for-you");
    const [stack, setStack] = useState([]);
    const [services, setServices] = useState([]);
    const [loading, setLoading] = useState(true);
    const [exiting, setExiting] = useState(null);
    const [tutorial, setTutorial] = useState(false);
    const [filtersOpen, setFiltersOpen] = useState(false);

    useEffect(() => {
        if (shouldShowTutorial()) {
            const t = setTimeout(() => setTutorial(true), 600);
            return () => clearTimeout(t);
        }
    }, []);

    const loadStack = async (tabId = tab) => {
        setLoading(true);
        try {
            const ep = TABS.find((t) => t.id === tabId)?.endpoint || "/discover";
            const [movies, svcs] = await Promise.all([apiGet(ep), apiGet("/services")]);
            setStack(movies);
            setServices(svcs);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { loadStack(tab); /* eslint-disable-next-line */ }, [tab]);

    const top = stack[0];

    const handleAction = async (action, dir) => {
        if (!top) return;
        setExiting({ id: top.id, dir });
        try {
            await apiPost("/user/action", { movie_id: top.id, action });
            if (action === "save") toast("Saved to Watchlist", { icon: "❤" });
            else if (action === "watched") toast("Marked as watched", { icon: "✓" });
        } catch {}
        setTimeout(() => {
            setStack((s) => s.slice(1));
            setExiting(null);
            refresh();
        }, 220);
    };

    const servicesById = useMemo(() => Object.fromEntries(services.map((s) => [s.id, s])), [services]);
    const userCountry = user?.country || "GB";

    return (
        <div className="min-h-screen pb-28 pt-5 px-5 max-w-md mx-auto" data-testid="discover-page">
            <header className="flex items-start justify-between mb-3 gap-3">
                <div className="min-w-0">
                    <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Hi {user?.name?.split(" ")[0]}</p>
                    <h1 className="font-display text-3xl leading-tight truncate">For you tonight</h1>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => navigate("/search")}
                        data-testid="open-search"
                        aria-label="search"
                        className="h-11 w-11 rounded-full glass grid place-items-center hover:bg-white/[0.06]"
                    >
                        <Search className="w-5 h-5 text-zinc-200" strokeWidth={1.7} />
                    </button>
                    <NotificationBell />
                    <AccountMenu />
                </div>
            </header>

            {/* Tab rail */}
            <div className="flex items-center gap-2 overflow-x-auto no-scrollbar -mx-1 px-1 mb-3" data-testid="tabs">
                {TABS.map((t) => {
                    const I = t.icon;
                    const active = tab === t.id;
                    return (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id)}
                            data-testid={`tab-${t.id}`}
                            className={`flex items-center gap-1.5 px-3.5 py-2 rounded-full text-sm whitespace-nowrap transition-colors border ${
                                active
                                    ? "bg-amber border-amber text-obsidian font-heading"
                                    : "border-white/10 text-zinc-300 hover:bg-white/5"
                            }`}
                        >
                            <I className="w-3.5 h-3.5" strokeWidth={1.8} />
                            {t.id === "local" ? `Popular in ${userCountry}` : t.label}
                        </button>
                    );
                })}
                <button
                    onClick={() => setFiltersOpen(true)}
                    data-testid="open-filters"
                    className="ml-1 h-9 w-9 rounded-full grid place-items-center border border-white/10 text-zinc-300 hover:bg-white/5"
                    aria-label="filters"
                >
                    <SlidersHorizontal className="w-3.5 h-3.5" />
                </button>
            </div>

            <Tutorial open={tutorial} onClose={() => setTutorial(false)} />
            <FiltersSheet
                open={filtersOpen}
                onClose={() => setFiltersOpen(false)}
                onSaved={() => { setFiltersOpen(false); refresh(); loadStack(tab); }}
            />

            <div className="relative" style={{ height: "62vh", maxHeight: 580 }}>
                {loading ? (
                    <div className="h-full grid place-items-center">
                        <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
                    </div>
                ) : stack.length === 0 ? (
                    <EmptyState onReload={() => loadStack(tab)} />
                ) : (
                    <AnimatePresence>
                        {stack.slice(0, 3).reverse().map((m, idx, arr) => {
                            const isTop = idx === arr.length - 1;
                            const stackPos = arr.length - 1 - idx;
                            return (
                                <Card
                                    key={m.id}
                                    movie={m}
                                    services={servicesById}
                                    isTop={isTop}
                                    stackPos={stackPos}
                                    isExiting={exiting?.id === m.id}
                                    exitDir={exiting?.dir}
                                    onSwipe={(dir) =>
                                        handleAction(
                                            dir === "right" ? "save" : dir === "down" ? "watched" : "skip",
                                            dir
                                        )
                                    }
                                    onTap={() => isTop && navigate(`/movie/${m.id}`)}
                                />
                            );
                        })}
                    </AnimatePresence>
                )}
            </div>

            {!loading && stack.length > 0 && (
                <div className="mt-5 flex items-center justify-center gap-3" data-testid="action-buttons">
                    <ActionBtn icon={X} onClick={() => handleAction("skip", "left")} ring="border-white/10" color="text-zinc-300" testId="btn-skip" label="Skip" />
                    <ActionBtn icon={Eye} onClick={() => handleAction("watched", "down")} ring="border-white/10" color="text-zinc-300" testId="btn-watched" label="Watched" small />
                    <ActionBtn icon={Info} onClick={() => top && navigate(`/movie/${top.id}`)} ring="border-white/10" color="text-zinc-300" testId="btn-info" label="Info" small />
                    <ActionBtn icon={Heart} onClick={() => handleAction("save", "right")} ring="border-amber" color="text-amber" glow testId="btn-save" label="Save" />
                </div>
            )}
        </div>
    );
}

function Card({ movie, services, isTop, stackPos, isExiting, exitDir, onSwipe, onTap }) {
    const x = useMotionValue(0);
    const y = useMotionValue(0);
    const rotate = useTransform(x, [-200, 0, 200], [-12, 0, 12]);
    const likeOp = useTransform(x, [40, 140], [0, 1]);
    const nopeOp = useTransform(x, [-140, -40], [1, 0]);
    const watchedOp = useTransform(y, [40, 140], [0, 1]);
    const offset = stackPos * 12;
    const scale = 1 - stackPos * 0.04;

    return (
        <motion.div
            className="absolute inset-0 rounded-3xl overflow-hidden card-shadow"
            data-testid={isTop ? "discover-card-top" : `discover-card-${stackPos}`}
            style={isTop ? { x, y, rotate, zIndex: 10 } : { y: offset, scale, zIndex: 10 - stackPos, opacity: 1 - stackPos * 0.15 }}
            drag={isTop ? true : false}
            dragConstraints={{ left: 0, right: 0, top: 0, bottom: 0 }}
            dragElastic={0.55}
            onDragEnd={(_, info) => {
                const { x: dx, y: dy } = info.offset;
                if (Math.abs(dy) > Math.abs(dx) && dy > 110) onSwipe("down");
                else if (dx > 110) onSwipe("right");
                else if (dx < -110) onSwipe("left");
            }}
            onClick={isTop ? onTap : undefined}
            initial={false}
            animate={
                isExiting
                    ? {
                          x: exitDir === "right" ? 600 : exitDir === "left" ? -600 : 0,
                          y: exitDir === "down" ? 600 : 0,
                          opacity: 0,
                          rotate: exitDir === "right" ? 20 : exitDir === "left" ? -20 : 0,
                      }
                    : {}
            }
            transition={{ type: "spring", stiffness: 260, damping: 28 }}
        >
            <img src={movie.poster_url} alt={movie.title} className="absolute inset-0 w-full h-full object-cover" draggable={false} />
            <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/65 to-transparent" />
            {isTop && (
                <>
                    <motion.div style={{ opacity: likeOp }} className="absolute top-8 right-6 px-4 py-2 border-2 border-amber text-amber font-heading text-2xl rotate-12 rounded-lg">SAVE</motion.div>
                    <motion.div style={{ opacity: nopeOp }} className="absolute top-8 left-6 px-4 py-2 border-2 border-red-400 text-red-400 font-heading text-2xl -rotate-12 rounded-lg">SKIP</motion.div>
                    <motion.div style={{ opacity: watchedOp }} className="absolute top-8 left-1/2 -translate-x-1/2 px-4 py-2 border-2 border-white text-white font-heading text-xl rounded-lg">WATCHED</motion.div>
                </>
            )}

            {isTop && movie.reason && (
                <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
                    className="absolute top-5 left-5 right-5 flex items-center gap-2 glass-strong rounded-full pl-3 pr-4 py-1.5 max-w-fit">
                    <Sparkles className="w-3.5 h-3.5 text-amber shrink-0" strokeWidth={2} />
                    <span className="text-[11px] tracking-wide text-zinc-200 truncate">{movie.reason}</span>
                </motion.div>
            )}

            <div className="absolute bottom-0 inset-x-0 p-6">
                <div className="flex flex-wrap gap-1.5 mb-3">
                    {(movie.genres || []).slice(0, 3).map((g) => (
                        <span key={g} className="text-[10px] uppercase tracking-wider bg-white/10 backdrop-blur px-2.5 py-1 rounded-full text-zinc-200">{g}</span>
                    ))}
                </div>
                <h2 className="font-display text-3xl leading-tight mb-2">{movie.title}</h2>
                <div className="flex items-center gap-3 text-sm text-zinc-300 mb-3">
                    <span className="flex items-center gap-1"><Star className="w-4 h-4 fill-amber text-amber" />{movie.rating?.toFixed(1)}</span>
                    <span>•</span><span>{movie.year}</span>
                    <span>•</span>
                    <span className="capitalize">{movie.type === "tv" ? `${movie.seasons?.length || 1} season${(movie.seasons?.length || 1) > 1 ? "s" : ""}` : `${movie.runtime || 0} min`}</span>
                </div>
                <p className="text-sm text-zinc-300/90 line-clamp-2 mb-3">{movie.overview}</p>
                <div className="flex items-center gap-1.5 flex-wrap">
                    {(movie.available_on || []).map((sid) => {
                        const s = services[sid];
                        if (!s) return null;
                        return <span key={sid} className="text-[10px] font-medium px-2 py-1 rounded text-white" style={{ backgroundColor: s.logo_color }}>{s.name}</span>;
                    })}
                </div>
            </div>
        </motion.div>
    );
}

function ActionBtn({ icon: Icon, onClick, ring, color, glow, small, testId, label }) {
    return (
        <button onClick={onClick} data-testid={testId} aria-label={label}
            className={`relative ${small ? "h-12 w-12" : "h-16 w-16"} rounded-full border-2 ${ring} ${color} bg-velvet/80 backdrop-blur grid place-items-center hover:scale-105 active:scale-95 transition-transform ${glow ? "amber-glow" : ""}`}>
            <Icon className={small ? "h-5 w-5" : "h-6 w-6"} strokeWidth={1.8} />
        </button>
    );
}

function EmptyState({ onReload }) {
    return (
        <div className="h-full grid place-items-center">
            <div className="text-center max-w-xs">
                <div className="w-16 h-16 rounded-2xl bg-amber/15 grid place-items-center mx-auto mb-4">
                    <Heart className="w-7 h-7 text-amber" strokeWidth={1.6} />
                </div>
                <h3 className="font-heading text-xl mb-2">You're all caught up</h3>
                <p className="text-sm text-zinc-400 mb-6">Try a different tab or update your filters.</p>
                <button onClick={onReload} className="px-5 py-3 rounded-xl border border-white/10 hover:bg-white/5">Reload</button>
            </div>
        </div>
    );
}
