import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { TrendingDown, ArrowUpRight, Sparkles, Trophy, Gauge, Tv2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import AccountMenu from "@/components/AccountMenu";

export default function Savings() {
    const [data, setData] = useState(null);
    const [value, setValue] = useState(null);
    const [insights, setInsights] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        Promise.all([
            apiGet("/savings"),
            apiGet("/watchlist/value").catch(() => null),
            apiGet("/insights/subscriptions").catch(() => null),
        ])
            .then(([s, v, i]) => { setData(s); setValue(v); setInsights(i); })
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

            {insights && insights.services && insights.services.length > 0 && (
                <div className="mt-10" data-testid="subscription-insights">
                    <div className="flex items-end justify-between mb-3">
                        <div>
                            <h2 className="font-heading text-lg flex items-center gap-2">
                                <Gauge className="w-4 h-4 text-amber" /> Subscription insights
                            </h2>
                            <p className="text-xs text-zinc-500 mt-0.5">{insights.month_label} · {insights.total_watched} title{insights.total_watched === 1 ? "" : "s"} watched</p>
                        </div>
                        {insights.potential_savings > 0 && (
                            <div className="text-right">
                                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Could save</div>
                                <div className="font-display text-xl text-amber" data-testid="insights-potential-savings">
                                    {insights.currency}{insights.potential_savings.toFixed(2)}
                                </div>
                            </div>
                        )}
                    </div>
                    <ul className="space-y-2.5">
                        {insights.services.map((s, i) => (
                            <motion.li
                                key={s.service_id}
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: i * 0.05 }}
                                className="glass rounded-2xl p-4"
                                data-testid={`insight-${s.service_id}`}
                            >
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-3 min-w-0">
                                        <div className="w-9 h-9 rounded-lg shrink-0" style={{ backgroundColor: s.logo_color }} />
                                        <div className="min-w-0">
                                            <div className="font-heading text-sm truncate">{s.name}</div>
                                            <div className="text-[11px] text-zinc-500">
                                                {insights.currency}{s.price_monthly.toFixed(2)}/mo
                                                {s.cost_per_watch != null && (
                                                    <> · {insights.currency}{s.cost_per_watch.toFixed(2)} per watch</>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="text-right shrink-0 pl-3">
                                        <div className="font-display text-2xl leading-none">{s.titles_watched}</div>
                                        <div className="text-[9px] uppercase tracking-wider text-zinc-500 mt-1">watched</div>
                                    </div>
                                </div>
                                <div className={`flex items-start gap-2 mt-2 pt-2.5 border-t border-white/5 text-xs ${s.tone === "great" ? "text-emerald-300" : s.tone === "low" ? "text-amber" : "text-zinc-300"}`}>
                                    {s.tone === "great" ? (
                                        <Sparkles className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                                    ) : s.tone === "low" ? (
                                        <TrendingDown className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                                    ) : (
                                        <Tv2 className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                                    )}
                                    <div>
                                        <span className="font-heading mr-1.5">{s.headline}.</span>
                                        <span className="text-zinc-400">{s.message}</span>
                                    </div>
                                </div>
                                {s.top_titles.length > 0 && (
                                    <div className="flex gap-1.5 mt-3 overflow-hidden">
                                        {s.top_titles.map((t) => (
                                            <div key={t.id} className="w-9 h-12 rounded bg-velvet overflow-hidden">
                                                {t.poster_url && <img loading="lazy" src={t.poster_url} alt={t.title} className="w-full h-full object-cover" />}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </motion.li>
                        ))}
                    </ul>
                </div>
            )}

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

            {value && value.services && value.watchlist_size > 0 && (
                <div className="mt-10" data-testid="watchlist-value-section">
                    <h2 className="font-heading text-lg mb-1 flex items-center gap-2">
                        <Trophy className="w-4 h-4 text-amber" /> Best value for your watchlist
                    </h2>
                    <p className="text-xs text-zinc-500 mb-4">
                        Across the {value.watchlist_size} title{value.watchlist_size === 1 ? "" : "s"} you've saved or watched, here's where you'd get the most for your money:
                    </p>
                    <ul className="space-y-2">
                        {value.services.filter((s) => s.titles_count > 0).slice(0, 5).map((s) => (
                            <li key={s.service_id} className="glass rounded-2xl p-4" data-testid={`value-${s.service_id}`}>
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 rounded-lg" style={{ backgroundColor: s.logo_color }} />
                                        <div>
                                            <div className="font-heading text-sm">{s.name}</div>
                                            <div className="text-[11px] text-zinc-500">
                                                {s.subscribed ? "Subscribed" : "Not subscribed"} · ${s.price_monthly}/mo
                                            </div>
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <div className="font-heading text-base">{s.titles_count}</div>
                                        <div className="text-[10px] uppercase text-zinc-500 tracking-wider">titles</div>
                                    </div>
                                </div>
                                {s.cost_per_title && (
                                    <div className="text-xs text-zinc-400">
                                        ~${s.cost_per_title} per title in your list
                                    </div>
                                )}
                                {s.top_titles.length > 0 && (
                                    <div className="flex gap-1.5 mt-3 overflow-hidden">
                                        {s.top_titles.map((t) => (
                                            <div key={t.id} className="w-10 h-14 rounded bg-velvet overflow-hidden">
                                                {t.poster_url && <img loading="lazy" src={t.poster_url} alt={t.title} className="w-full h-full object-cover" />}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}
