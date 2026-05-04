import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Sparkles, PiggyBank, Compass } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useEffect } from "react";

export default function Landing() {
    const { user, loading } = useAuth();
    const navigate = useNavigate();
    useEffect(() => {
        if (!loading && user) navigate("/discover", { replace: true });
    }, [user, loading, navigate]);

    return (
        <div className="relative min-h-screen overflow-hidden">
            {/* hero backdrop */}
            <div
                className="absolute inset-0 -z-10 opacity-50"
                style={{
                    backgroundImage:
                        "url(https://image.tmdb.org/t/p/w1280/xOMo8BRK7PfcJv9JCnx7s5hj0PX.jpg)",
                    backgroundSize: "cover",
                    backgroundPosition: "center",
                }}
            />
            <div className="absolute inset-0 -z-10 bg-gradient-to-b from-obsidian/60 via-obsidian/85 to-obsidian" />

            <div className="max-w-md mx-auto px-6 pt-16 pb-24">
                <motion.div
                    initial={{ opacity: 0, y: 18 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                >
                    <div className="flex items-center gap-2 mb-12">
                        <div className="h-9 w-9 rounded-2xl bg-amber flex items-center justify-center text-obsidian font-display text-xl">
                            R
                        </div>
                        <span className="font-heading text-xl tracking-tight">Reelm</span>
                    </div>

                    <h1 className="font-display text-5xl sm:text-6xl leading-[0.95] mb-6">
                        Stop scrolling.
                        <br />
                        <span className="text-amber">Start watching.</span>
                    </h1>

                    <p className="text-zinc-400 text-base leading-relaxed mb-10 max-w-sm">
                        Reelm finds what's actually worth your time across every streaming
                        service you pay for — and helps you cancel the ones you don't need.
                    </p>

                    <div className="flex flex-col gap-3 mb-12">
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

                    <div className="grid grid-cols-1 gap-4">
                        <Feature icon={Compass} title="Swipe to discover" body="One title at a time. No more endless rows." />
                        <Feature icon={Sparkles} title="AI that knows your taste" body="Personalized picks across all your services." />
                        <Feature icon={PiggyBank} title="Save real money" body="Cancel or rotate subscriptions you barely use." />
                    </div>
                </motion.div>
            </div>
        </div>
    );
}

function Feature({ icon: Icon, title, body }) {
    return (
        <div className="glass rounded-2xl p-5 flex items-start gap-4">
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
