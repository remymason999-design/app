import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LogOut, Settings, Tv2, Tag, Eye, TrendingUp, HelpCircle, Shield } from "lucide-react";
import { apiGet, apiPut, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { motion } from "framer-motion";
import Tutorial, { resetTutorial } from "@/components/Tutorial";

export default function Profile() {
    const { user, setUser, logout } = useAuth();
    const navigate = useNavigate();
    const [services, setServices] = useState([]);
    const [genres, setGenres] = useState([]);
    const [watchedCount, setWatchedCount] = useState(0);
    const [affiliate, setAffiliate] = useState({ total: 0, per_service: [] });
    const [tutorial, setTutorial] = useState(false);

    useEffect(() => {
        apiGet("/services").then(setServices);
        apiGet("/genres").then(setGenres);
        apiGet("/watched").then((m) => setWatchedCount(m.length));
        apiGet("/affiliate/me").then(setAffiliate).catch(() => {});
    }, []);

    const toggleService = async (id) => {
        const next = user.subscriptions.includes(id)
            ? user.subscriptions.filter((s) => s !== id)
            : [...user.subscriptions, id];
        try {
            const updated = await apiPut("/user/preferences", { services: next });
            setUser(updated);
        } catch (e) {
            toast.error(formatApiError(e.response?.data?.detail));
        }
    };

    const toggleGenre = async (g) => {
        const next = user.genres.includes(g)
            ? user.genres.filter((x) => x !== g)
            : [...user.genres, g];
        try {
            const updated = await apiPut("/user/preferences", { genres: next });
            setUser(updated);
        } catch (e) {
            toast.error(formatApiError(e.response?.data?.detail));
        }
    };

    const onLogout = async () => {
        await logout();
        navigate("/");
    };

    if (!user) return null;

    const topLearned = Object.entries(user.genre_weights || {})
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5);

    const replayTutorial = () => {
        resetTutorial();
        setTutorial(true);
    };

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="profile-page">
            <Tutorial open={tutorial} onClose={() => setTutorial(false)} />
            <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-4"
            >
                <div className="h-16 w-16 rounded-2xl bg-amber grid place-items-center text-obsidian font-display text-2xl">
                    {user.name?.slice(0, 1)?.toUpperCase()}
                </div>
                <div>
                    <h1 className="font-heading text-2xl">{user.name}</h1>
                    <p className="text-sm text-zinc-400">{user.email}</p>
                </div>
            </motion.div>

            <div className="grid grid-cols-3 gap-3 mt-6" data-testid="profile-stats">
                <Stat label="Saved" value={user.saved?.length || 0} icon={Tag} />
                <Stat label="Watched" value={watchedCount} icon={Eye} />
                <Stat label="Services" value={user.subscriptions?.length || 0} icon={Tv2} />
            </div>

            <Section title="What we've learned about you">
                <div className="glass rounded-2xl p-5" data-testid="learning-card">
                    {topLearned.length === 0 ? (
                        <p className="text-sm text-zinc-400 leading-relaxed">
                            Keep swiping, saving and marking watched — we'll start tuning your discovery feed within a few picks.
                        </p>
                    ) : (
                        <>
                            <p className="text-xs uppercase tracking-wider text-zinc-500 mb-3">Genres you actually engage with</p>
                            <ul className="space-y-2">
                                {topLearned.map(([g, w]) => {
                                    const max = topLearned[0][1];
                                    const pct = Math.max(8, Math.min(100, Math.round((w / max) * 100)));
                                    return (
                                        <li key={g} className="flex items-center gap-3" data-testid={`learned-${g}`}>
                                            <span className="font-heading text-sm w-24 shrink-0">{g}</span>
                                            <div className="flex-1 h-1.5 rounded-full bg-white/8 overflow-hidden">
                                                <div className="h-full bg-amber" style={{ width: `${pct}%` }} />
                                            </div>
                                            <span className="text-xs text-zinc-500 w-6 text-right">{w}</span>
                                        </li>
                                    );
                                })}
                            </ul>
                        </>
                    )}
                </div>
            </Section>

            <Section title="Streaming services">
                <div className="grid grid-cols-2 gap-2">
                    {services.map((s) => {
                        const on = user.subscriptions.includes(s.id);
                        return (
                            <button
                                key={s.id}
                                onClick={() => toggleService(s.id)}
                                data-testid={`profile-service-${s.id}`}
                                className={`flex items-center gap-2 p-3 rounded-xl border transition-colors text-left ${
                                    on ? "border-amber bg-amber/10" : "border-white/10 bg-white/[0.03]"
                                }`}
                            >
                                <div className="w-7 h-7 rounded-lg shrink-0" style={{ backgroundColor: s.logo_color }} />
                                <div>
                                    <div className="text-sm font-medium">{s.name}</div>
                                    <div className="text-[10px] text-zinc-500">${s.price_monthly}/mo</div>
                                </div>
                            </button>
                        );
                    })}
                </div>
            </Section>

            <Section title="Favorite genres">
                <div className="flex flex-wrap gap-2">
                    {genres.map((g) => {
                        const on = user.genres.includes(g);
                        return (
                            <button
                                key={g}
                                onClick={() => toggleGenre(g)}
                                data-testid={`profile-genre-${g}`}
                                className={`px-3.5 py-2 rounded-full text-sm border ${
                                    on ? "bg-amber text-obsidian border-amber" : "border-white/10 text-zinc-300"
                                }`}
                            >
                                {g}
                            </button>
                        );
                    })}
                </div>
            </Section>

            <Section title="Supporting WatchSmart">
                <div className="glass rounded-2xl p-5" data-testid="affiliate-card">
                    <div className="flex items-start gap-3">
                        <div className="h-10 w-10 rounded-xl bg-amber/15 grid place-items-center shrink-0">
                            <TrendingUp className="h-5 w-5 text-amber" strokeWidth={1.6} />
                        </div>
                        <div className="flex-1">
                            <div className="font-heading text-base">
                                {affiliate.total} click{affiliate.total === 1 ? "" : "s"} to streaming partners
                            </div>
                            <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                                Every time you tap "Where to watch", we pass a referral tag. That helps keep WatchSmart free.
                            </p>
                            {affiliate.per_service.length > 0 && (
                                <ul className="mt-3 space-y-1.5">
                                    {affiliate.per_service.slice(0, 4).map((row) => (
                                        <li key={row.service_id} className="flex items-center justify-between text-xs text-zinc-400">
                                            <span>{row.service_name}</span>
                                            <span className="font-heading text-zinc-200">{row.count}</span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            </Section>

            <button
                onClick={replayTutorial}
                data-testid="replay-tutorial-btn"
                className="mt-8 w-full flex items-center justify-center gap-2 py-4 rounded-2xl border border-white/10 text-zinc-300 hover:bg-white/5"
            >
                <HelpCircle className="w-4 h-4" />
                Replay quick tour
            </button>

            {user.role === "admin" && (
                <Link
                    to="/admin"
                    data-testid="admin-link"
                    className="mt-3 w-full flex items-center justify-center gap-2 py-4 rounded-2xl border border-amber/40 bg-amber/10 text-amber hover:bg-amber/15 font-heading"
                >
                    <Shield className="w-4 h-4" />
                    Admin control room
                </Link>
            )}


            <button
                onClick={onLogout}
                data-testid="logout-btn"
                className="mt-3 w-full flex items-center justify-center gap-2 py-4 rounded-2xl border border-white/10 text-zinc-300 hover:bg-white/5"
            >
                <LogOut className="w-4 h-4" />
                Sign out
            </button>
        </div>
    );
}

function Stat({ label, value, icon: Icon }) {
    return (
        <div className="glass rounded-2xl p-4 text-center">
            <Icon className="w-4 h-4 text-amber mx-auto mb-2" strokeWidth={1.6} />
            <div className="font-display text-2xl">{value}</div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 mt-1">{label}</div>
        </div>
    );
}

function Section({ title, children }) {
    return (
        <section className="mt-8">
            <h2 className="font-heading text-base mb-3 flex items-center gap-2">
                <Settings className="w-3.5 h-3.5 text-zinc-500" /> {title}
            </h2>
            {children}
        </section>
    );
}
