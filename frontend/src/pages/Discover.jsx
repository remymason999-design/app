import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence, useMotionValue, useTransform } from "framer-motion";
import { Heart, X, Eye, Info, Star } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function Discover() {
    const navigate = useNavigate();
    const { user, refresh } = useAuth();
    const [stack, setStack] = useState([]);
    const [services, setServices] = useState([]);
    const [loading, setLoading] = useState(true);
    const [exiting, setExiting] = useState(null); // { id, dir }

    const loadStack = async () => {
        setLoading(true);
        try {
            const [movies, svcs] = await Promise.all([apiGet("/discover"), apiGet("/services")]);
            setStack(movies);
            setServices(svcs);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadStack();
    }, []);

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

    const servicesById = useMemo(
        () => Object.fromEntries(services.map((s) => [s.id, s])),
        [services]
    );

    return (
        <div className="min-h-screen pb-28 pt-6 px-5 max-w-md mx-auto" data-testid="discover-page">
            <header className="flex items-center justify-between mb-4">
                <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Hi {user?.name?.split(" ")[0]}</p>
                    <h1 className="font-display text-3xl leading-tight">For you tonight</h1>
                </div>
                <div className="h-11 w-11 rounded-full bg-amber flex items-center justify-center text-obsidian font-display">
                    {(user?.name || "?").slice(0, 1).toUpperCase()}
                </div>
            </header>

            <div className="relative" style={{ height: "70vh", maxHeight: 620 }}>
                {loading ? (
                    <div className="h-full grid place-items-center">
                        <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
                    </div>
                ) : stack.length === 0 ? (
                    <EmptyState onReload={loadStack} />
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
                                        handleAction(dir === "right" ? "save" : "skip", dir)
                                    }
                                    onTap={() => isTop && navigate(`/movie/${m.id}`)}
                                />
                            );
                        })}
                    </AnimatePresence>
                )}
            </div>

            {!loading && stack.length > 0 && (
                <div className="mt-6 flex items-center justify-center gap-4" data-testid="action-buttons">
                    <ActionBtn
                        icon={X}
                        onClick={() => handleAction("skip", "left")}
                        ring="border-white/10"
                        color="text-zinc-300"
                        testId="btn-skip"
                        label="Skip"
                    />
                    <ActionBtn
                        icon={Eye}
                        onClick={() => handleAction("watched", "down")}
                        ring="border-white/10"
                        color="text-zinc-300"
                        testId="btn-watched"
                        label="Watched"
                        small
                    />
                    <ActionBtn
                        icon={Info}
                        onClick={() => top && navigate(`/movie/${top.id}`)}
                        ring="border-white/10"
                        color="text-zinc-300"
                        testId="btn-info"
                        label="Info"
                        small
                    />
                    <ActionBtn
                        icon={Heart}
                        onClick={() => handleAction("save", "right")}
                        ring="border-amber"
                        color="text-amber"
                        glow
                        testId="btn-save"
                        label="Save"
                    />
                </div>
            )}
        </div>
    );
}

function Card({ movie, services, isTop, stackPos, isExiting, exitDir, onSwipe, onTap }) {
    const x = useMotionValue(0);
    const rotate = useTransform(x, [-200, 0, 200], [-12, 0, 12]);
    const likeOp = useTransform(x, [40, 140], [0, 1]);
    const nopeOp = useTransform(x, [-140, -40], [1, 0]);
    const offset = stackPos * 12;
    const scale = 1 - stackPos * 0.04;

    return (
        <motion.div
            className="absolute inset-0 rounded-3xl overflow-hidden card-shadow"
            data-testid={isTop ? "discover-card-top" : `discover-card-${stackPos}`}
            style={isTop ? { x, rotate, zIndex: 10 } : { y: offset, scale, zIndex: 10 - stackPos, opacity: 1 - stackPos * 0.15 }}
            drag={isTop ? "x" : false}
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={0.6}
            onDragEnd={(_, info) => {
                if (info.offset.x > 110) onSwipe("right");
                else if (info.offset.x < -110) onSwipe("left");
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
            <img
                src={movie.poster_url}
                alt={movie.title}
                className="absolute inset-0 w-full h-full object-cover"
                draggable={false}
                onError={(e) => {
                    e.currentTarget.style.display = "none";
                }}
            />
            <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/65 to-transparent" />

            {isTop && (
                <>
                    <motion.div
                        style={{ opacity: likeOp }}
                        className="absolute top-8 right-6 px-4 py-2 border-2 border-amber text-amber font-heading text-2xl rotate-12 rounded-lg"
                    >
                        SAVE
                    </motion.div>
                    <motion.div
                        style={{ opacity: nopeOp }}
                        className="absolute top-8 left-6 px-4 py-2 border-2 border-red-400 text-red-400 font-heading text-2xl -rotate-12 rounded-lg"
                    >
                        SKIP
                    </motion.div>
                </>
            )}

            <div className="absolute bottom-0 inset-x-0 p-6">
                <div className="flex flex-wrap gap-1.5 mb-3">
                    {(movie.genres || []).slice(0, 3).map((g) => (
                        <span
                            key={g}
                            className="text-[10px] uppercase tracking-wider bg-white/10 backdrop-blur px-2.5 py-1 rounded-full text-zinc-200"
                        >
                            {g}
                        </span>
                    ))}
                </div>
                <h2 className="font-display text-3xl leading-tight mb-2">{movie.title}</h2>
                <div className="flex items-center gap-3 text-sm text-zinc-300 mb-3">
                    <span className="flex items-center gap-1">
                        <Star className="w-4 h-4 fill-amber text-amber" />
                        {movie.rating?.toFixed(1)}
                    </span>
                    <span>•</span>
                    <span>{movie.year}</span>
                    <span>•</span>
                    <span className="capitalize">{movie.type}</span>
                </div>
                <p className="text-sm text-zinc-300/90 line-clamp-2 mb-3">{movie.overview}</p>
                <div className="flex items-center gap-1.5">
                    {(movie.available_on || []).map((sid) => {
                        const s = services[sid];
                        if (!s) return null;
                        return (
                            <span
                                key={sid}
                                className="text-[10px] font-medium px-2 py-1 rounded text-white"
                                style={{ backgroundColor: s.logo_color }}
                            >
                                {s.name}
                            </span>
                        );
                    })}
                </div>
            </div>
        </motion.div>
    );
}

function ActionBtn({ icon: Icon, onClick, ring, color, glow, small, testId, label }) {
    return (
        <button
            onClick={onClick}
            data-testid={testId}
            aria-label={label}
            className={`relative ${small ? "h-12 w-12" : "h-16 w-16"} rounded-full border-2 ${ring} ${color} bg-velvet/80 backdrop-blur grid place-items-center hover:scale-105 active:scale-95 transition-transform ${glow ? "amber-glow" : ""}`}
        >
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
                <p className="text-sm text-zinc-400 mb-6">
                    We've shown everything that matches your services. Update your preferences or check your watchlist.
                </p>
                <button
                    onClick={onReload}
                    className="px-5 py-3 rounded-xl border border-white/10 hover:bg-white/5"
                >
                    Reload
                </button>
            </div>
        </div>
    );
}
