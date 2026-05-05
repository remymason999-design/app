import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, RefreshCw, Download, Users, MousePointerClick, Database, Loader2 } from "lucide-react";
import { apiGet, apiPost, API } from "@/lib/api";
import { getToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function Admin() {
    const { user, loading } = useAuth();
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [analytics, setAnalytics] = useState(null);
    const [refreshing, setRefreshing] = useState(false);

    useEffect(() => {
        if (loading) return;
        if (!user || user.role !== "admin") {
            navigate("/discover", { replace: true });
            return;
        }
        apiGet("/admin/dashboard").then(setData).catch(() => {
            toast.error("Couldn't load admin dashboard");
            navigate("/discover");
        });
        apiGet("/admin/analytics").then(setAnalytics).catch(() => {});
    }, [user, loading, navigate]);

    const refreshCatalog = async () => {
        setRefreshing(true);
        try {
            const r = await apiPost("/admin/refresh-catalog?pages=5");
            toast.success(`Catalog refreshed: ${r.count} titles`);
            const fresh = await apiGet("/admin/dashboard");
            setData(fresh);
        } catch (e) {
            toast.error("Refresh failed");
        } finally {
            setRefreshing(false);
        }
    };

    const downloadCsv = async () => {
        const token = getToken();
        const res = await fetch(`${API}/affiliate/export.csv`, {
            credentials: "include",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) {
            toast.error("CSV export failed");
            return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "watchsmart_affiliate_clicks.csv";
        a.click();
        URL.revokeObjectURL(url);
    };

    if (!data) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-2xl mx-auto" data-testid="admin-page">
            <div className="flex items-center justify-between mb-6">
                <button
                    onClick={() => navigate("/profile")}
                    className="flex items-center gap-2 text-zinc-400 hover:text-zinc-100"
                    data-testid="admin-back"
                >
                    <ArrowLeft className="w-4 h-4" />
                    <span className="text-sm">Back</span>
                </button>
                <span className="text-[10px] uppercase tracking-[0.25em] text-amber border border-amber/40 rounded-full px-2.5 py-1">
                    Admin
                </span>
            </div>

            <h1 className="font-display text-4xl leading-tight mb-2">Control room</h1>
            <p className="text-sm text-zinc-400 mb-8">Real-time affiliate analytics + catalog ops.</p>

            <div className="grid grid-cols-3 gap-3 mb-6" data-testid="admin-stats">
                <Stat icon={Database} label="Catalog" value={data.catalog_size} />
                <Stat icon={Users} label="Users" value={data.total_users} />
                <Stat icon={MousePointerClick} label="Clicks" value={data.total_clicks} />
            </div>

            {analytics && (
                <div className="glass rounded-2xl p-5 mb-6" data-testid="engagement-card">
                    <div className="flex items-center justify-between mb-3">
                        <div className="font-heading text-base">Engagement</div>
                        <span className="text-[10px] uppercase tracking-wider text-zinc-500">7-day window</span>
                    </div>
                    <div className="grid grid-cols-4 gap-3 mb-4">
                        <MiniStat label="DAU" value={analytics.dau} />
                        <MiniStat label="WAU" value={analytics.wau} />
                        <MiniStat label="MAU" value={analytics.mau} />
                        <MiniStat label="Save rate" value={`${analytics.save_rate_pct}%`} />
                    </div>
                    {Object.keys(analytics.swipes_7d || {}).length > 0 && (
                        <div className="flex items-center gap-3 text-xs text-zinc-400">
                            {Object.entries(analytics.swipes_7d).map(([action, count]) => (
                                <span key={action} className="flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-amber" />
                                    {action} <span className="font-heading text-zinc-200">{count}</span>
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            )}

            <div className="glass rounded-2xl p-5 mb-6">
                <div className="flex items-center justify-between mb-3">
                    <div>
                        <div className="font-heading text-base">Affiliate clicks</div>
                        <div className="text-xs text-zinc-500">{data.unique_click_users} unique users · per-service breakdown</div>
                    </div>
                    <button
                        onClick={downloadCsv}
                        data-testid="export-csv-btn"
                        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber hover:bg-amber-600 text-obsidian font-heading text-sm amber-glow"
                    >
                        <Download className="w-4 h-4" /> Export CSV
                    </button>
                </div>
                {data.by_service.length === 0 ? (
                    <p className="text-sm text-zinc-500 mt-2">No clicks yet. Tap "Where to watch" on a movie to log one.</p>
                ) : (
                    <ul className="space-y-1.5 mt-3">
                        {data.by_service.map((s) => {
                            const max = data.by_service[0].count;
                            const pct = Math.max(8, Math.round((s.count / max) * 100));
                            return (
                                <li key={s.service_id} className="flex items-center gap-3" data-testid={`bys-${s.service_id}`}>
                                    <span className="font-heading text-sm w-28 shrink-0">{s.service_name}</span>
                                    <div className="flex-1 h-1.5 rounded-full bg-white/8 overflow-hidden">
                                        <div className="h-full bg-amber" style={{ width: `${pct}%` }} />
                                    </div>
                                    <span className="text-sm font-heading text-zinc-200 w-8 text-right">{s.count}</span>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </div>

            <div className="glass rounded-2xl p-5 mb-6">
                <div className="flex items-center justify-between mb-3">
                    <div>
                        <div className="font-heading text-base">Catalog</div>
                        <div className="text-xs text-zinc-500">{data.catalog_size} titles · powered by TMDB</div>
                    </div>
                    <button
                        onClick={refreshCatalog}
                        disabled={refreshing}
                        data-testid="refresh-catalog-btn"
                        className="flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 hover:bg-white/5 text-sm font-heading"
                    >
                        {refreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                        {refreshing ? "Refreshing…" : "Refresh from TMDB"}
                    </button>
                </div>
                <p className="text-xs text-zinc-500 leading-relaxed">
                    Pulls 5 pages of popular movies + TV shows, enriches with streaming providers and YouTube trailers, drops anything without availability or trailer.
                </p>
            </div>

            <h2 className="font-heading text-base mb-3">Recent clicks</h2>
            <ul className="space-y-2" data-testid="recent-clicks">
                {data.recent.length === 0 ? (
                    <li className="text-sm text-zinc-500">No clicks yet.</li>
                ) : (
                    data.recent.map((r, i) => (
                        <motion.li
                            key={i}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.02 }}
                            className="flex items-center justify-between glass rounded-xl px-4 py-3"
                        >
                            <div>
                                <div className="font-heading text-sm">{r.movie_title}</div>
                                <div className="text-[11px] text-zinc-500">{r.user_id} · {r.service_name}</div>
                            </div>
                            <div className="text-[10px] text-zinc-500">{r.created_at?.slice(11, 16)}</div>
                        </motion.li>
                    ))
                )}
            </ul>
        </div>
    );
}

function Stat({ icon: Icon, label, value }) {
    return (
        <div className="glass rounded-2xl p-4 text-center">
            <Icon className="w-4 h-4 text-amber mx-auto mb-2" strokeWidth={1.6} />
            <div className="font-display text-2xl">{value}</div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 mt-1">{label}</div>
        </div>
    );
}
