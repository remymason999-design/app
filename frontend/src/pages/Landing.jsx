import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Sparkles, PiggyBank, Compass, Star } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useEffect } from "react";

const HERO_POSTERS = [
    { url: "https://image.tmdb.org/t/p/w500/uKvVjHNqB5VmOrdxqAt2F7J78ED.jpg", title: "The Last of Us", rating: 8.7 },
    { url: "https://image.tmdb.org/t/p/w500/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg", title: "Dune: Part Two", rating: 8.3 },
    { url: "https://image.tmdb.org/t/p/w500/lFf6LLrQjYldcZItzOkGmMMigP7.jpg", title: "Severance", rating: 8.7 },
    { url: "https://image.tmdb.org/t/p/w500/7QMsOTMUswlwxJP0rTTZfmz2tX2.jpg", title: "House of the Dragon", rating: 8.4 },
    { url: "https://image.tmdb.org/t/p/w500/8Vt6mWEReuy4Of61Lnj5Xj704m8.jpg", title: "Across the Spider-Verse", rating: 8.4 },
];

export default function Landing() {
    const { user, loading } = useAuth();
    const navigate = useNavigate();
    useEffect(() => {
        if (!loading && user) navigate("/discover", { replace: true });
    }, [user, loading, navigate]);

    return (
        <div className="relative min-h-screen overflow-hidden">
            {/* Ambient gradient + amber spotlight */}
            <div
                className="absolute inset-0 -z-10"
                style={{
                    background:
                        "radial-gradient(ellipse 60% 60% at 80% 0%, rgba(245,158,11,0.18), transparent 60%), radial-gradient(ellipse 50% 80% at 0% 100%, rgba(217,119,6,0.10), transparent 70%), #060608",
                }}
            />

            <div className="max-w-md mx-auto px-6 pt-12 pb-24">
                {/* Brand */}
                <motion.div
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                    className="flex items-center gap-2 mb-10"
                >
                    <div className="h-9 w-9 rounded-2xl bg-amber flex items-center justify-center text-obsidian font-display text-xl">
                        W
                    </div>
                    <span className="font-heading text-xl tracking-tight">WatchSmart</span>
                    <span className="ml-auto text-[10px] uppercase tracking-[0.2em] text-zinc-500 border border-white/10 rounded-full px-2.5 py-1">
                        Beta
                    </span>
                </motion.div>

                {/* Hero poster fan */}
                <div className="relative h-[280px] mb-10">
                    {HERO_POSTERS.map((p, i) => {
                        const total = HERO_POSTERS.length;
                        const center = (total - 1) / 2;
                        const offset = i - center;
                        return (
                            <motion.div
                                key={p.url}
                                initial={{ opacity: 0, y: 30, rotate: 0 }}
                                animate={{ opacity: 1, y: 0, rotate: offset * 6 }}
                                transition={{ delay: 0.1 + i * 0.08, duration: 0.6, ease: "easeOut" }}
                                style={{
                                    left: `calc(50% + ${offset * 38}px - 70px)`,
                                    zIndex: total - Math.abs(offset),
                                }}
                                className="absolute top-2 w-[140px] h-[210px] rounded-2xl overflow-hidden card-shadow"
                            >
                                <img
                                    src={p.url}
                                    alt={p.title}
                                    className="absolute inset-0 w-full h-full object-cover"
                                    draggable={false}
                                />
                                <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
                                <div className="absolute bottom-2 left-2 right-2">
                                    <div className="flex items-center gap-1 text-[10px] text-amber font-medium">
                                        <Star className="w-2.5 h-2.5 fill-amber" />
                                        {p.rating}
                                    </div>
                                </div>
                            </motion.div>
                        );
                    })}
                </div>

                {/* Headline */}
                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.5, duration: 0.5 }}
                >
                    <h1 className="font-display text-[44px] sm:text-5xl leading-[0.95]">
                        Stop scrolling.
                        <br />
                        <span className="text-amber">Start watching.</span>
                    </h1>
                    <p className="text-zinc-400 text-base leading-relaxed mt-5 mb-8 max-w-sm">
                        WatchSmart finds what's actually worth your time across every streaming
                        service you pay for — and helps you cancel the ones you don't need.
                    </p>

                    <div className="flex flex-col gap-3 mb-10">
                        <Link
                            to="/register"
                            data-testid="cta-get-started"
                            className="group flex items-center justify-between bg-amber hover:bg-amber-600 text-obsidian font-heading text-base px-6 py-4 rounded-2xl transition-colors amber-glow"
                        >
                            <span>Get started — it's free</span>
                            <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
                        </Link>
                        <Link
                            to="/login"
                            data-testid="cta-login"
                            className="text-center text-zinc-300 hover:text-white py-3 text-sm tracking-wide"
                        >
                            I already have an account
                        </Link>
                    </div>

                    <div className="grid grid-cols-1 gap-3">
                        <Feature icon={Compass} title="Swipe to discover" body="One title at a time. No more endless rows." />
                        <Feature icon={Sparkles} title="AI that learns your taste" body="Every swipe tunes tomorrow's picks." />
                        <Feature icon={PiggyBank} title="Save real money" body="Cancel or rotate the services you barely use." />
                    </div>

                    {/* Bottom marquee */}
                    <div className="mt-10 pt-6 border-t border-white/8">
                        <div className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-3">Find titles across</div>
                        <div className="flex flex-wrap gap-2">
                            {["Netflix", "Disney+", "Max", "Prime Video", "Apple TV+", "Hulu", "Paramount+", "Peacock"].map((s) => (
                                <span key={s} className="text-xs text-zinc-400 border border-white/10 rounded-full px-3 py-1">
                                    {s}
                                </span>
                            ))}
                        </div>
                    </div>
                </motion.div>
            </div>
        </div>
    );
}

function Feature({ icon: Icon, title, body }) {
    return (
        <div className="glass rounded-2xl p-4 flex items-start gap-4">
            <div className="h-10 w-10 rounded-xl bg-amber/15 flex items-center justify-center shrink-0">
                <Icon className="h-5 w-5 text-amber" strokeWidth={1.6} />
            </div>
            <div>
                <div className="font-heading text-base mb-1">{title}</div>
                <div className="text-sm text-zinc-400 leading-snug">{body}</div>
            </div>
        </div>
    );
}
