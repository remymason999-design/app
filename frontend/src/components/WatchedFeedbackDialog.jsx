import { AnimatePresence, motion } from "framer-motion";
import { Clock3, Heart, MinusCircle, ThumbsDown, ThumbsUp, X } from "lucide-react";

const OPTIONS = [
    { key: "loved", label: "Loved it", Icon: Heart, className: "text-amber border-amber/40", meta: { watched_sentiment: "loved", completed: true } },
    { key: "liked", label: "Liked it", Icon: ThumbsUp, className: "text-emerald-300 border-emerald-400/40", meta: { watched_sentiment: "liked", completed: true } },
    { key: "neutral", label: "It was okay", Icon: MinusCircle, className: "text-zinc-200 border-white/20", meta: { watched_sentiment: "neutral", completed: true } },
    { key: "disliked", label: "Didn't like it", Icon: ThumbsDown, className: "text-red-300 border-red-400/35", meta: { watched_sentiment: "disliked", completed: true } },
    { key: "unfinished", label: "Haven't finished it", Icon: Clock3, className: "text-zinc-300 border-white/15", meta: { completed: false } },
];

export default function WatchedFeedbackDialog({ open, title, onSelect, onCancel, busy = false }) {
    return (
        <AnimatePresence>
            {open && (
                <motion.div
                    className="fixed inset-0 z-[80] bg-black/75 backdrop-blur-sm flex items-end sm:items-center justify-center"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    data-testid="watched-feedback-dialog"
                >
                    <button className="absolute inset-0" onClick={onCancel} aria-label="Close reaction choices" />
                    <motion.div
                        initial={{ y: 28, opacity: 0 }}
                        animate={{ y: 0, opacity: 1 }}
                        exit={{ y: 20, opacity: 0 }}
                        className="relative w-full max-w-md rounded-t-3xl sm:rounded-3xl bg-velvet border border-white/10 p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-2xl"
                    >
                        <button onClick={onCancel} className="absolute right-4 top-4 h-9 w-9 grid place-items-center rounded-full bg-white/5 text-zinc-300" aria-label="Cancel">
                            <X className="w-4 h-4" />
                        </button>
                        <h2 className="font-display text-2xl pr-12">What did you think?</h2>
                        {title && <p className="text-sm text-zinc-400 mt-1 truncate">{title}</p>}
                        <div className="mt-5 space-y-2">
                            {OPTIONS.map(({ key, label, Icon, className, meta }) => (
                                <button
                                    key={key}
                                    onClick={() => onSelect(meta)}
                                    disabled={busy}
                                    className="w-full min-h-12 flex items-center gap-3 rounded-2xl bg-white/[0.04] border border-white/10 p-3 text-left hover:bg-white/[0.08] disabled:opacity-50"
                                    data-testid={`watched-option-${key}`}
                                >
                                    <span className={`h-9 w-9 rounded-full border grid place-items-center ${className}`}><Icon className="w-4 h-4" /></span>
                                    <span className="font-heading text-sm text-white">{label}</span>
                                </button>
                            ))}
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}