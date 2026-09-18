import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { apiGet, apiPut, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { capture, EVENTS } from "@/lib/analytics";

export default function OnboardingGenres() {
    const navigate = useNavigate();
    const { user, setUser } = useAuth();
    const [genres, setGenres] = useState([]);
    const [selected, setSelected] = useState(new Set(user?.genres || []));
    const [country, setCountry] = useState(user?.country || "GB");
    const [age, setAge] = useState(user?.age || "");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        apiGet("/genres").then(setGenres);
    }, []);

    const toggle = (g) => {
        setSelected((s) => {
            const next = new Set(s);
            next.has(g) ? next.delete(g) : next.add(g);
            return next;
        });
    };

    const onContinue = async () => {
        setSaving(true);
        try {
            const updated = await apiPut("/user/preferences", {
                genres: Array.from(selected.size ? selected : new Set(["Drama"])),
                country,
                age: age ? Number(age) : undefined,
            });
            setUser(updated);
            capture(EVENTS.ONBOARDING_STEP_COMPLETED, { step: "genres", selected_count: selected.size, country }, { user: updated });
            capture(EVENTS.ONBOARDING_COMPLETED, {}, { user: updated });
            toast.success("All set — let's find something to watch");
            navigate("/discover");
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="min-h-screen px-6 pt-12 pb-32 max-w-md mx-auto" data-testid="onboarding-genres">
            <p className="text-xs uppercase tracking-[0.25em] text-amber">Step 2 of 2</p>
            <h1 className="font-display text-4xl mt-3 leading-[1]">What do you love watching?</h1>
            <p className="text-zinc-400 mt-3 mb-6">Pick a few — we'll learn the rest from your swipes.</p>

            <div className="flex flex-wrap gap-2 mb-8">
                {genres.map((g, i) => {
                    const on = selected.has(g);
                    return (
                        <motion.button
                            key={g}
                            initial={{ opacity: 0, scale: 0.9 }}
                            animate={{ opacity: 1, scale: 1 }}
                            transition={{ delay: i * 0.025 }}
                            onClick={() => toggle(g)}
                            data-testid={`genre-${g}`}
                            className={`px-4 py-2.5 rounded-full text-sm font-medium border transition-colors ${
                                on
                                    ? "bg-amber text-obsidian border-amber"
                                    : "border-white/12 text-zinc-300 hover:bg-white/5"
                            }`}
                        >
                            {g}
                        </motion.button>
                    );
                })}
            </div>

            <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-500 mb-2">Country (for streaming availability)</p>
            <select
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                data-testid="onboarding-country"
                className="w-full bg-white/5 border border-white/10 rounded-2xl p-3 text-sm mb-5 focus:border-amber/60 outline-none"
            >
                {COUNTRY_LIST.map((c) => (
                    <option key={c.code} value={c.code}>{c.name}</option>
                ))}
            </select>

            <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-500 mb-2">Age (optional — used for content rating)</p>
            <input
                type="number"
                min={1}
                max={120}
                value={age}
                onChange={(e) => setAge(e.target.value)}
                placeholder="e.g. 28"
                data-testid="onboarding-age"
                className="w-full bg-white/5 border border-white/10 rounded-2xl p-3 text-sm focus:border-amber/60 outline-none"
            />

            <div className="fixed inset-x-0 bottom-0 glass-strong px-6 py-5 z-30" style={{ paddingBottom: "max(20px, env(safe-area-inset-bottom))" }}>
                <div className="max-w-md mx-auto flex items-center justify-between gap-4">
                    <div className="text-sm text-zinc-400">
                        {selected.size} selected
                    </div>
                    <button
                        onClick={onContinue}
                        disabled={saving}
                        data-testid="genres-continue"
                        className="bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading px-6 py-3.5 rounded-2xl amber-glow"
                    >
                        {saving ? "Saving…" : "Start discovering"}
                    </button>
                </div>
            </div>
        </div>
    );
}

const COUNTRY_LIST = [
    { code: "GB", name: "🇬🇧 United Kingdom" },
    { code: "US", name: "🇺🇸 United States" },
    { code: "CA", name: "🇨🇦 Canada" },
    { code: "AU", name: "🇦🇺 Australia" },
    { code: "IE", name: "🇮🇪 Ireland" },
    { code: "IN", name: "🇮🇳 India" },
    { code: "DE", name: "🇩🇪 Germany" },
    { code: "FR", name: "🇫🇷 France" },
    { code: "ES", name: "🇪🇸 Spain" },
    { code: "IT", name: "🇮🇹 Italy" },
    { code: "NL", name: "🇳🇱 Netherlands" },
    { code: "BR", name: "🇧🇷 Brazil" },
    { code: "MX", name: "🇲🇽 Mexico" },
    { code: "JP", name: "🇯🇵 Japan" },
];
