/**
 * LaunchAnimation — premium in-app opening / splash animation.
 *
 * Sequence (≤ ~2s): dark navy backdrop + orange glow → two abstract card
 * backs slide in from opposite sides and snap together in the centre (the
 * "swipe → match" idea) → the orange WatchSmart "W" mark forms on top → the
 * WATCHSMART wordmark fades in → the tagline fades in → the whole splash
 * fades out and calls onDone().
 *
 * Respects prefers-reduced-motion (skips card movement, gentle fades only).
 * Intended to be shown once per session by the caller.
 */
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Mark } from "@/components/Logo";

function CardBack() {
    return (
        <div
            className="relative w-full h-full rounded-2xl border border-white/10 overflow-hidden shadow-[0_24px_70px_-12px_rgba(0,0,0,0.85)]"
            style={{ background: "linear-gradient(160deg, #141d2a 0%, #0b111a 55%, #06090f 100%)" }}
        >
            <div className="absolute inset-0 grid place-items-center opacity-[0.07]">
                <Mark size={88} />
            </div>
            <div
                className="absolute inset-0"
                style={{ background: "linear-gradient(120deg, transparent 38%, rgba(255,122,24,0.12) 50%, transparent 62%)" }}
            />
        </div>
    );
}

export default function LaunchAnimation({ onDone }) {
    const reduce = useReducedMotion();
    const [exiting, setExiting] = useState(false);

    useEffect(() => {
        const hold = reduce ? 1250 : 1650;
        const fade = 300;
        const t1 = setTimeout(() => setExiting(true), hold);
        const t2 = setTimeout(() => onDone?.(), hold + fade);
        return () => {
            clearTimeout(t1);
            clearTimeout(t2);
        };
    }, [reduce, onDone]);

    return (
        <motion.div
            className="fixed inset-0 z-[100] overflow-hidden grid place-items-center"
            data-testid="launch-animation"
            style={{ background: "#05070A", pointerEvents: exiting ? "none" : "auto" }}
            initial={{ opacity: 1 }}
            animate={{ opacity: exiting ? 0 : 1 }}
            transition={{ duration: 0.35, ease: "easeInOut" }}
            aria-hidden="true"
        >
            {/* Centre orange glow */}
            <motion.div
                className="absolute rounded-full"
                style={{
                    width: 540,
                    height: 540,
                    background:
                        "radial-gradient(circle, rgba(255,122,24,0.30), rgba(255,77,0,0.07) 45%, transparent 70%)",
                    filter: "blur(8px)",
                }}
                initial={{ opacity: 0.3, scale: 0.85 }}
                animate={
                    reduce
                        ? { opacity: 0.5, scale: 1 }
                        : { opacity: [0.3, 0.5, 0.42, 0.6], scale: [0.85, 1, 0.96, 1.06] }
                }
                transition={{ duration: 1.6, ease: "easeInOut" }}
            />

            {/* Two abstract card backs sliding in + meeting (skipped on reduced motion) */}
            {!reduce && (
                <>
                    <motion.div
                        className="absolute"
                        style={{ width: 150, height: 212 }}
                        initial={{ x: "-130%", rotate: -16, opacity: 0 }}
                        animate={{
                            x: ["-130%", "-56%", "-52%", "-52%"],
                            rotate: [-16, -6, -3, -3],
                            opacity: [0, 1, 1, 0.1],
                            scale: [1, 1, 1.05, 0.96],
                        }}
                        transition={{ duration: 1.0, times: [0, 0.45, 0.62, 0.9], ease: "easeOut" }}
                    >
                        <CardBack />
                    </motion.div>
                    <motion.div
                        className="absolute"
                        style={{ width: 150, height: 212 }}
                        initial={{ x: "130%", rotate: 16, opacity: 0 }}
                        animate={{
                            x: ["130%", "56%", "52%", "52%"],
                            rotate: [16, 6, 3, 3],
                            opacity: [0, 1, 1, 0.1],
                            scale: [1, 1, 1.05, 0.96],
                        }}
                        transition={{ duration: 1.0, times: [0, 0.45, 0.62, 0.9], ease: "easeOut" }}
                    >
                        <CardBack />
                    </motion.div>

                    {/* Snap / match glow pulse when the cards meet */}
                    <motion.div
                        className="absolute rounded-full"
                        style={{
                            width: 180,
                            height: 180,
                            background: "radial-gradient(circle, rgba(255,140,40,0.55), transparent 60%)",
                        }}
                        initial={{ opacity: 0, scale: 0.4 }}
                        animate={{ opacity: [0, 0.8, 0], scale: [0.4, 1.3, 1.7] }}
                        transition={{ delay: 0.58, duration: 0.55, ease: "easeOut" }}
                    />
                </>
            )}

            {/* The W mark — the hero */}
            <motion.div
                className="absolute grid place-items-center"
                initial={{ scale: 0.85, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: reduce ? 0.1 : 0.66, duration: reduce ? 0.5 : 0.42, ease: "easeOut" }}
            >
                <motion.div
                    className="absolute rounded-full"
                    style={{
                        width: 260,
                        height: 260,
                        background: "radial-gradient(circle, rgba(255,122,24,0.45), transparent 65%)",
                        filter: "blur(6px)",
                    }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: reduce ? 0.6 : [0, 0.9, 0.55] }}
                    transition={{ delay: reduce ? 0.1 : 0.66, duration: 0.6, ease: "easeOut" }}
                />
                <Mark size={104} className="relative drop-shadow-[0_0_26px_rgba(255,122,24,0.55)]" />
            </motion.div>

            {/* Wordmark + tagline */}
            <div className="absolute left-1/2 -translate-x-1/2 text-center" style={{ top: "calc(50% + 86px)" }}>
                <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: reduce ? 0.45 : 0.92, duration: 0.38, ease: "easeOut" }}
                >
                    <span className="font-display text-3xl tracking-tight leading-none">
                        <span className="text-white">WATCH</span>
                        <span className="text-amber">SMART</span>
                    </span>
                </motion.div>
                <motion.p
                    className="mt-2.5 text-sm"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: reduce ? 0.65 : 1.16, duration: 0.38, ease: "easeOut" }}
                >
                    <span className="text-zinc-400">Less browsing. </span>
                    <span className="text-amber">More watching.</span>
                </motion.p>
            </div>
        </motion.div>
    );
}
