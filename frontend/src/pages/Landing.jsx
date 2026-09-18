import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useEffect } from "react";
import { PROVIDERS, ProviderLogo } from "@/components/ProviderLogo";
import { Mark } from "@/components/Logo";

const CHECKLIST = [
    "Pick your streaming services",
    "Swipe to discover",
    "Save what you'll watch",
    "Get better picks over time",
];

export default function Landing() {
    const { user, loading } = useAuth();
    const navigate = useNavigate();
    useEffect(() => {
        if (!loading && user) navigate("/discover", { replace: true });
    }, [user, loading, navigate]);

    return (
        <div className="relative min-h-screen overflow-hidden">
            {/* Ambient gradient + orange spotlight */}
            <div
                className="absolute inset-0 -z-10"
                style={{
                    background:
                        "radial-gradient(ellipse 60% 50% at 75% 0%, rgba(255,122,24,0.20), transparent 60%), radial-gradient(ellipse 50% 80% at 0% 100%, rgba(255,77,0,0.12), transparent 70%), #05070A",
                }}
            />

            <div className="max-w-md mx-auto px-6 pt-16 pb-24">
                {/* Brand — stacked mark + wordmark */}
                <motion.div
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                    className="flex flex-col items-start gap-3 mb-10"
                >
                    <Mark size={96} />
                    <div className="flex flex-col gap-1.5">
                        <span className="font-display tracking-tight leading-none text-4xl">
                            <span className="text-white">Watch</span>
                            <span className="text-amber">Smart</span>
                        </span>
                        <span className="uppercase tracking-[0.26em] text-zinc-500 text-[10px]">
                            Find what&apos;s worth your time
                        </span>
                    </div>
                </motion.div>

                {/* Tagline */}
                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.15, duration: 0.5 }}
                >
                    <h1 className="font-display text-[40px] sm:text-5xl leading-[0.98] mb-7">
                        Less browsing.
                        <br />
                        <span className="text-amber">More watching.</span>
                    </h1>

                    {/* Checklist */}
                    <ul className="space-y-3.5 mb-9">
                        {CHECKLIST.map((item, i) => (
                            <motion.li
                                key={item}
                                initial={{ opacity: 0, x: -8 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: 0.25 + i * 0.07 }}
                                className="flex items-center gap-3"
                            >
                                <span className="h-6 w-6 rounded-full bg-amber/15 grid place-items-center shrink-0">
                                    <Check className="h-3.5 w-3.5 text-amber" strokeWidth={3} />
                                </span>
                                <span className="text-[15px] text-zinc-200">{item}</span>
                            </motion.li>
                        ))}
                    </ul>

                    <div className="flex flex-col gap-3 mb-10">
                        <Link
                            to="/register"
                            data-testid="cta-get-started"
                            className="group flex items-center justify-center gap-2 bg-amber hover:bg-amber-600 text-obsidian font-heading text-base px-6 py-4 rounded-2xl transition-colors amber-glow"
                        >
                            <span>Let's Get Started</span>
                            <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
                        </Link>
                        <Link
                            to="/login"
                            data-testid="cta-login"
                            className="text-center text-zinc-400 hover:text-white py-2 text-sm"
                        >
                            Already have an account? <span className="text-amber">Log in</span>
                        </Link>
                    </div>

                    {/* Streaming platform showcase */}
                    <div className="mt-6 pt-6 border-t border-white/8">
                        <div className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-4">
                            Works across all major platforms
                        </div>
                        <div className="grid grid-cols-4 gap-x-3 gap-y-4">
                            {Object.entries(PROVIDERS).map(([sid, p]) => (
                                <div key={sid} className="flex flex-col items-center gap-1.5">
                                    <div style={{ filter: `drop-shadow(0 0 8px ${p.bg}55)` }}>
                                        <ProviderLogo sid={sid} size={56} shape="rounded-2xl" />
                                    </div>
                                    <span className="text-[9px] text-zinc-500 text-center leading-tight w-full truncate px-0.5">
                                        {p.name}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Legal footer */}
                    <div className="mt-10 pt-6 border-t border-white/8 flex flex-wrap justify-center gap-x-6 gap-y-2">
                        <a href="/privacy" className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors">Privacy Policy</a>
                        <a href="/terms" className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors">Terms &amp; Conditions</a>
                        <a href="mailto:support@watchsmart.uk" className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors">Contact</a>
                    </div>
                </motion.div>
            </div>
        </div>
    );
}
