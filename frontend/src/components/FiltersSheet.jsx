import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { apiGet, apiPut, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

const COUNTRIES = [
    { code: "GB", name: "United Kingdom" },
    { code: "US", name: "United States" },
    { code: "CA", name: "Canada" },
    { code: "AU", name: "Australia" },
    { code: "IE", name: "Ireland" },
    { code: "IN", name: "India" },
    { code: "DE", name: "Germany" },
    { code: "FR", name: "France" },
    { code: "ES", name: "Spain" },
    { code: "IT", name: "Italy" },
    { code: "NL", name: "Netherlands" },
    { code: "BR", name: "Brazil" },
    { code: "MX", name: "Mexico" },
    { code: "JP", name: "Japan" },
];

const CATEGORY_TOGGLES = [
    { id: "anime", label: "Anime", body: "Hide animation from Japan" },
    { id: "bollywood", label: "Bollywood", body: "Hide Hindi-language films & TV" },
];

export default function FiltersSheet({ open, onClose, onSaved }) {
    const { user, setUser } = useAuth();
    const [excluded, setExcluded] = useState(new Set(user?.excluded_categories || []));
    const [country, setCountry] = useState(user?.country || "GB");
    const [allGenres, setAllGenres] = useState([]);
    const [genres, setGenres] = useState(new Set(user?.genres || []));
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!open) return;
        setExcluded(new Set(user?.excluded_categories || []));
        setCountry(user?.country || "GB");
        setGenres(new Set(user?.genres || []));
        apiGet("/genres").then(setAllGenres).catch(() => {});
    }, [open, user]);

    const toggleSet = (set, setter, val) => {
        const next = new Set(set);
        next.has(val) ? next.delete(val) : next.add(val);
        setter(next);
    };

    const save = async () => {
        setSaving(true);
        try {
            const updated = await apiPut("/user/preferences", {
                excluded_categories: Array.from(excluded),
                country,
                genres: Array.from(genres),
            });
            setUser(updated);
            toast.success("Filters updated");
            onSaved?.();
        } catch (e) {
            toast.error(formatApiError(e.response?.data?.detail));
        } finally {
            setSaving(false);
        }
    };

    return (
        <AnimatePresence>
            {open && (
                <motion.div
                    className="fixed inset-0 z-[55] bg-obsidian/85 backdrop-blur-sm flex items-end justify-center"
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    onClick={onClose}
                    data-testid="filters-sheet"
                >
                    <motion.div
                        initial={{ y: 60 }} animate={{ y: 0 }} exit={{ y: 60 }}
                        transition={{ type: "spring", stiffness: 280, damping: 28 }}
                        onClick={(e) => e.stopPropagation()}
                        className="w-full max-w-md glass-strong rounded-t-3xl p-6 max-h-[88vh] overflow-auto"
                    >
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="font-heading text-xl">Filters</h2>
                            <button onClick={onClose} className="h-9 w-9 grid place-items-center rounded-full hover:bg-white/5" aria-label="close">
                                <X className="w-4 h-4" />
                            </button>
                        </div>

                        <SectionLabel>Hide categories</SectionLabel>
                        <div className="space-y-2 mb-6">
                            {CATEGORY_TOGGLES.map((c) => {
                                const on = excluded.has(c.id);
                                return (
                                    <button
                                        key={c.id}
                                        onClick={() => toggleSet(excluded, setExcluded, c.id)}
                                        data-testid={`filter-cat-${c.id}`}
                                        className={`w-full text-left flex items-center justify-between rounded-2xl p-4 border ${
                                            on ? "border-amber bg-amber/10" : "border-white/10 hover:bg-white/[0.04]"
                                        }`}
                                    >
                                        <div>
                                            <div className="font-heading text-sm">{c.label}</div>
                                            <div className="text-xs text-zinc-400">{c.body}</div>
                                        </div>
                                        <div className={`h-5 w-9 rounded-full p-0.5 transition-colors ${on ? "bg-amber" : "bg-white/15"}`}>
                                            <div className={`h-4 w-4 rounded-full bg-obsidian transition-transform ${on ? "translate-x-4" : ""}`} />
                                        </div>
                                    </button>
                                );
                            })}
                        </div>

                        <SectionLabel>Country</SectionLabel>
                        <div className="grid grid-cols-2 gap-2 mb-6">
                            {COUNTRIES.map((c) => (
                                <button
                                    key={c.code}
                                    onClick={() => setCountry(c.code)}
                                    data-testid={`filter-country-${c.code}`}
                                    className={`px-3 py-2.5 rounded-xl border text-sm text-left ${
                                        country === c.code ? "bg-amber text-obsidian border-amber" : "border-white/10 text-zinc-300"
                                    }`}
                                >
                                    <span className="text-xs uppercase tracking-wider opacity-60">{c.code}</span>
                                    <div className="font-heading text-sm leading-tight">{c.name}</div>
                                </button>
                            ))}
                        </div>

                        <SectionLabel>Favourite genres</SectionLabel>
                        <div className="flex flex-wrap gap-2 mb-8">
                            {allGenres.map((g) => {
                                const on = genres.has(g);
                                return (
                                    <button
                                        key={g}
                                        onClick={() => toggleSet(genres, setGenres, g)}
                                        data-testid={`filter-genre-${g}`}
                                        className={`px-3 py-1.5 rounded-full text-sm border ${
                                            on ? "bg-amber text-obsidian border-amber" : "border-white/12 text-zinc-300"
                                        }`}
                                    >
                                        {g}
                                    </button>
                                );
                            })}
                        </div>

                        <button
                            onClick={save}
                            disabled={saving}
                            data-testid="filters-save"
                            className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading py-4 rounded-2xl amber-glow"
                        >
                            {saving ? "Saving…" : "Apply filters"}
                        </button>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}

function SectionLabel({ children }) {
    return <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-500 mb-2">{children}</p>;
}
