import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { apiGet, apiPut, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function OnboardingServices() {
    const navigate = useNavigate();
    const { user, setUser } = useAuth();
    const [services, setServices] = useState([]);
    const [selected, setSelected] = useState(new Set(user?.subscriptions || []));
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        apiGet("/services").then(setServices);
    }, []);

    const toggle = (id) => {
        setSelected((s) => {
            const next = new Set(s);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };

    const monthlyTotal = services
        .filter((s) => selected.has(s.id))
        .reduce((sum, s) => sum + s.price_monthly, 0);

    const onContinue = async () => {
        setSaving(true);
        try {
            const updated = await apiPut("/user/preferences", {
                services: Array.from(selected),
            });
            setUser(updated);
            navigate("/onboarding/genres");
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="min-h-screen px-6 pt-12 pb-32 max-w-md mx-auto" data-testid="onboarding-services">
            <p className="text-xs uppercase tracking-[0.25em] text-amber">Step 1 of 2</p>
            <h1 className="font-display text-4xl mt-3 leading-[1]">What do you currently pay for?</h1>
            <p className="text-zinc-400 mt-3 mb-8">We'll only show titles you can watch right now.</p>

            <div className="grid grid-cols-2 gap-3">
                {services.map((s, i) => {
                    const on = selected.has(s.id);
                    return (
                        <motion.button
                            key={s.id}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.04 }}
                            onClick={() => toggle(s.id)}
                            data-testid={`service-${s.id}`}
                            className={`relative text-left rounded-2xl p-4 border transition-all ${
                                on ? "border-amber bg-amber/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"
                            }`}
                        >
                            <div
                                className="w-9 h-9 rounded-xl mb-3 flex items-center justify-center text-sm font-heading text-white"
                                style={{ backgroundColor: s.logo_color }}
                            >
                                {s.name.slice(0, 1)}
                            </div>
                            <div className="font-heading text-base">{s.name}</div>
                            <div className="text-xs text-zinc-400 mt-1">${s.price_monthly.toFixed(2)}/mo</div>
                            {on && (
                                <div className="absolute top-3 right-3 w-6 h-6 rounded-full bg-amber flex items-center justify-center">
                                    <Check className="w-3.5 h-3.5 text-obsidian" strokeWidth={3} />
                                </div>
                            )}
                        </motion.button>
                    );
                })}
            </div>

            <div className="fixed inset-x-0 bottom-0 glass-strong px-6 py-5 z-30" style={{ paddingBottom: "max(20px, env(safe-area-inset-bottom))" }}>
                <div className="max-w-md mx-auto flex items-center justify-between gap-4">
                    <div>
                        <div className="text-xs text-zinc-500 uppercase tracking-wider">You spend</div>
                        <div className="font-display text-2xl">${monthlyTotal.toFixed(2)}<span className="text-sm text-zinc-500">/mo</span></div>
                    </div>
                    <button
                        onClick={onContinue}
                        disabled={saving}
                        data-testid="services-continue"
                        className="bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading px-6 py-3.5 rounded-2xl amber-glow"
                    >
                        {saving ? "Saving…" : selected.size === 0 ? "Skip" : "Continue"}
                    </button>
                </div>
            </div>
        </div>
    );
}
