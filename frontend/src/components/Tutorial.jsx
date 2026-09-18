import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, Heart, Eye, Sparkles, X, Play } from "lucide-react";
import { capture, EVENTS } from "@/lib/analytics";

const KEY = "ws_tutorial_v2_seen";

const STEPS = [
    {
        title: "Swipe right to save",
        body: "Like a poster? Drag it to the right or tap the amber heart. We'll add it to your Watchlist.",
        icon: Heart,
        color: "text-amber",
        accent: "bg-amber/20 border-amber/40",
        gesture: "right",
    },
    {
        title: "Swipe left to skip",
        body: "Not your vibe? Drag left or tap the X. We'll learn from every swipe and tune your picks.",
        icon: X,
        color: "text-zinc-300",
        accent: "bg-white/5 border-white/15",
        gesture: "left",
    },
    {
        title: "Eye for already watched",
        body: "Seen it? Tap the eye to log it as watched — that helps us boost the genres you actually finish.",
        icon: Eye,
        color: "text-zinc-300",
        accent: "bg-white/5 border-white/15",
        gesture: "down",
    },
    {
        title: "Track every episode",
        body: "Open Library and tap Update progress to choose your season and episode. WatchSmart will build Continue Watching, episode totals and watch-time stats as you go.",
        icon: Play,
        color: "text-amber",
        accent: "bg-amber/20 border-amber/40",
        gesture: "progress",
    },
    {
        title: "AI that knows your taste",
        body: "Tap any card for full details, the YouTube trailer, and a personal 'why you'll love this' from our AI.",
        icon: Sparkles,
        color: "text-amber",
        accent: "bg-amber/20 border-amber/40",
        gesture: "tap",
    },
];

export default function Tutorial({ open, onClose }) {
    const [step, setStep] = useState(0);

    useEffect(() => {
        if (!open) setStep(0);
    }, [open]);

    if (!open) return null;
    const s = STEPS[step];
    const Icon = s.icon;
    const last = step === STEPS.length - 1;

    const finish = () => {
        try { localStorage.setItem(KEY, "1"); } catch {}
        capture(EVENTS.TUTORIAL_COMPLETED, { completed: last }, { allowDuplicate: false });
        onClose();
    };

    return (
        <AnimatePresence>
            <motion.div
                className="fixed inset-0 z-[70] bg-obsidian/85 backdrop-blur-md flex items-end sm:items-center justify-center px-5 pb-8"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                data-testid="tutorial-overlay"
            >
                <motion.div
                    key={step}
                    initial={{ y: 24, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    exit={{ y: -12, opacity: 0 }}
                    transition={{ type: "spring", stiffness: 260, damping: 26 }}
                    className="w-full max-w-md glass-strong rounded-3xl p-6 relative overflow-hidden"
                >
                    <button
                        onClick={finish}
                        data-testid="tutorial-skip"
                        className="absolute top-4 right-4 text-xs text-zinc-500 hover:text-zinc-200 uppercase tracking-wider"
                    >
                        Skip
                    </button>

                    {/* Demo gesture preview */}
                    <div className="h-32 mb-5 flex items-center justify-center relative">
                        <DemoCard gesture={s.gesture} />
                    </div>

                    <div className="flex items-center gap-3 mb-3">
                        <div className={`h-10 w-10 rounded-xl border ${s.accent} grid place-items-center`}>
                            <Icon className={`w-5 h-5 ${s.color}`} strokeWidth={1.7} />
                        </div>
                        <div className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">
                            Step {step + 1} of {STEPS.length}
                        </div>
                    </div>

                    <h3 className="font-display text-2xl leading-tight mb-2">{s.title}</h3>
                    <p className="text-sm text-zinc-400 leading-relaxed mb-6">{s.body}</p>

                    {/* Progress dots */}
                    <div className="flex gap-1.5 mb-5">
                        {STEPS.map((_, i) => (
                            <div
                                key={i}
                                className={`h-1 rounded-full transition-all ${
                                    i === step ? "bg-amber w-8" : "bg-white/15 w-4"
                                }`}
                            />
                        ))}
                    </div>

                    <div className="flex items-center gap-3">
                        {step > 0 && (
                            <button
                                onClick={() => setStep((s) => s - 1)}
                                data-testid="tutorial-back"
                                className="h-12 w-12 rounded-2xl border border-white/10 grid place-items-center text-zinc-300 hover:bg-white/5"
                                aria-label="back"
                            >
                                <ArrowLeft className="w-4 h-4" />
                            </button>
                        )}
                        <button
                            onClick={last ? finish : () => setStep((s) => s + 1)}
                            data-testid={last ? "tutorial-done" : "tutorial-next"}
                            className="flex-1 h-12 bg-amber hover:bg-amber-600 text-obsidian font-heading rounded-2xl flex items-center justify-center gap-2 amber-glow"
                        >
                            {last ? "Start watching smarter" : "Next"}
                            {!last && <ArrowRight className="w-4 h-4" />}
                        </button>
                    </div>
                </motion.div>
            </motion.div>
        </AnimatePresence>
    );
}

export function shouldShowTutorial() {
    try {
        return !localStorage.getItem(KEY);
    } catch {
        return true;
    }
}

export function resetTutorial() {
    try { localStorage.removeItem(KEY); } catch {}
}

function DemoCard({ gesture }) {
    if (gesture === "progress") {
        return (
            <div className="relative">
                <motion.div
                    className="w-40 h-16 rounded-xl bg-gradient-to-br from-zinc-700 to-zinc-900 border border-white/10 shadow-[0_0_20px_rgba(245,158,11,0.2)] flex flex-col justify-end p-2.5 gap-2"
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: [0.95, 1, 1, 0.95], opacity: [0, 1, 1, 0] }}
                    transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                >
                    <div className="flex items-end justify-between w-full">
                        <div className="flex gap-1.5 flex-col flex-1">
                            <div className="h-1.5 w-3/4 bg-white/20 rounded-full" />
                            <div className="h-1 w-1/2 bg-white/10 rounded-full" />
                        </div>
                        <div className="text-[9px] font-heading text-amber">S1 E6</div>
                    </div>
                    <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
                        <motion.div
                            className="h-full bg-amber rounded-full"
                            initial={{ width: "30%" }}
                            animate={{ width: ["30%", "70%", "70%", "30%"] }}
                            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                        />
                    </div>
                    <div className="flex justify-between text-[8px] text-zinc-300">
                        <span>Update progress</span><span>39h watched</span>
                    </div>
                </motion.div>
            </div>
        );
    }

    const variants = {
        right: { x: [0, 90, 90, 0], rotate: [0, 12, 12, 0], opacity: [1, 1, 0, 1] },
        left:  { x: [0, -90, -90, 0], rotate: [0, -12, -12, 0], opacity: [1, 1, 0, 1] },
        down:  { y: [0, 50, 50, 0], opacity: [1, 0.7, 0, 1] },
        tap:   { scale: [1, 0.92, 1, 1], opacity: [1, 1, 1, 1] },
    };
    const tint = {
        right: "ring-2 ring-amber/70 shadow-[0_0_24px_rgba(245,158,11,0.4)]",
        left: "ring-2 ring-red-400/60",
        down: "ring-2 ring-zinc-300/40",
        tap: "ring-2 ring-amber/50",
    }[gesture];

    return (
        <div className="relative">
            <motion.div
                className={`w-24 h-32 rounded-2xl bg-gradient-to-br from-zinc-700 to-zinc-900 ${tint}`}
                animate={variants[gesture]}
                transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut", times: [0, 0.4, 0.7, 1] }}
            >
                <div className="h-full w-full rounded-2xl flex items-end p-2">
                    <div className="w-full h-1 rounded-full bg-white/20" />
                </div>
            </motion.div>
        </div>
    );
}
