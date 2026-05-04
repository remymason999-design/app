import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { TrendingDown, ArrowUpRight, Sparkles } from "lucide-react";
import { apiGet } from "@/lib/api";
import AccountMenu from "@/components/AccountMenu";

export default function Savings() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        apiGet("/savings")
            .then(setData)
            .finally(() => setLoading(false));
    }, []);

    if (loading) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }

    const totalSavings = data.suggestions.reduce((s, x) => s + (x.monthly_savings || 0), 0);

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="savings-page">
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Your subscriptions</p>
                    <h1 className="font-display text-4xl mt-2 leading-tight">Spend less.<br />Watch more.</h1>
                </div>
                <AccountMenu />
            </div>

            <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="glass rounded-3xl p-6 mt-8"
                data-testid="savings-summary"
            >
                <div className="flex items-end justify-between gap-4">
                    <div>
                        <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">Monthly</div>
                        <div className="font-display text-4xl">${data.total_monthly.toFixed(2)}</div>
                        <div className="text-xs text-zinc-500 mt-1">{data.subscription_count} services</div>
                    </div>
                    <div className="text-right">
                        <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">Yearly</div>
                        <div className="font-heading text-2xl">${data.total_yearly.toFixed(0)}</div>
                    </div>
                </div>
                {totalSavings > 0 && (
                    <div className="mt-5 pt-5 border-t border-white/10 flex items-center gap-3">
                        <div className="h-10 w-10 rounded-xl bg-amber/15 grid place-items-center">
                            <TrendingDown className="w-5 h-5 text-amber" strokeWidth={1.6} />
                        </div>
                        <div>
                            <div className="font-heading text-base">
                                Save ${totalSavings.toFixed(2)}/mo
                            </div>
                            <div className="text-xs text-zinc-400">
                                That's ${(totalSavings * 12).toFixed(0)} a year back in your pocket.
                            </div>
                        </div>
                    </div>
                )}
            </motion.div>

            <h2 className="font-heading text-lg mt-10 mb-3">Smart suggestions</h2>
            {data.suggestions.length === 0 ? (
                <div className="glass rounded-2xl p-5">
                    <div className="flex gap-3 items-start">
                        <Sparkles className="w-5 h-5 text-amber shrink-0 mt-1" strokeWidth={1.6} />
                        <p className="text-sm text-zinc-300">
                            Your stack looks balanced. Keep swiping and we'll watch for ways to trim spend.
                        </p>
                    </div>
                </div>
            ) : (
                <ul className="space-y-3">
                    {data.suggestions.map((s, i) => (
                        <motion.li
                            key={i}
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.06 }}
                            className="glass rounded-2xl p-5"
                            data-testid={`suggestion-${i}`}
                        >
                            <div className="flex items-start gap-3">
                                <div className="h-9 w-9 rounded-xl bg-amber/15 grid place-items-center shrink-0">
                                    {s.type === "cancel" ? (
                                        <TrendingDown className="w-4 h-4 text-amber" />
                                    ) : (
                                        <Sparkles className="w-4 h-4 text-amber" />
                                    )}
                                </div>
                                <div className="flex-1">
                                    <div className="font-heading text-base mb-1">{s.headline}</div>
                                    <p className="text-sm text-zinc-400">{s.reason}</p>
                                </div>
                            </div>
                        </motion.li>
                    ))}
                </ul>
            )}

            <h2 className="font-heading text-lg mt-10 mb-3">Activity per service</h2>
            <ul className="space-y-2">
                {data.usage.map((u) => (
                    <li
                        key={u.service_id}
                        className="flex items-center justify-between glass rounded-xl px-4 py-3"
                        data-testid={`usage-${u.service_id}`}
                    >
                        <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg" style={{ backgroundColor: u.logo_color }} />
                            <div>
                                <div className="font-heading text-sm">{u.name}</div>
                                <div className="text-[11px] text-zinc-500">
                                    ${u.price_monthly.toFixed(2)}/mo · {u.available_unseen} new for you
                                </div>
                            </div>
                        </div>
                        <div className="text-right">
                            <div className="font-heading text-base">{u.activity_count}</div>
                            <div className="text-[10px] uppercase tracking-wider text-zinc-500">titles</div>
                        </div>
                    </li>
                ))}
            </ul>

            <div className="mt-10 text-xs text-zinc-500 flex items-center gap-2">
                <ArrowUpRight className="w-3 h-3" />
                Overlap detected on {data.overlap_titles} titles across your services.
            </div>
        </div>
    );
}
