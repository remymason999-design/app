import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, RefreshCw, Download, Users, MousePointerClick, Database, Loader2, ChevronDown, ChevronUp, Activity } from "lucide-react";
import { apiGet, apiPost, API } from "@/lib/api";
import { getToken } from "@/lib/api";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function Admin() {
    const { user, loading } = useAuth();
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [analytics, setAnalytics] = useState(null);
    const [users, setUsers] = useState(null);
    const [usersOpen, setUsersOpen] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const [lookupEmail, setLookupEmail] = useState("");
    const [lookupResult, setLookupResult] = useState(null);
    const [lookupLoading, setLookupLoading] = useState(false);
    const [providerHealth, setProviderHealth] = useState(null);
    const [diagnostics, setDiagnostics] = useState(null);
    const [impressionConversions, setImpressionConversions] = useState(null);
    const [tab, setTab] = useState("dashboard");
    const [pricing, setPricing] = useState(null);

    const loadPricing = () =>
        apiGet("/pricing/services").then(setPricing).catch(() => toast.error("Couldn't load pricing"));

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
        apiGet("/admin/users").then(setUsers).catch(() => {});
        apiGet("/admin/provider-health").then(setProviderHealth).catch(() => {});
        apiGet("/admin/diagnostics/recommendations").then(setDiagnostics).catch(() => {});
        apiGet("/admin/diagnostics/impression-conversions").then(setImpressionConversions).catch(() => {});
    }, [user, loading, navigate]);

    const runLookup = async (e) => {
        e?.preventDefault?.();
        if (!lookupEmail.trim()) return;
        setLookupLoading(true);
        setLookupResult(null);
        try {
            const [u, debug] = await Promise.all([
                apiGet(`/admin/lookup?email=${encodeURIComponent(lookupEmail.trim())}`),
                apiGet(`/admin/recommendation-debug?email=${encodeURIComponent(lookupEmail.trim())}&limit=8`).catch(() => null),
            ]);
            setLookupResult({ ...u, debug });
        } catch (err) {
            toast.error(err?.response?.data?.detail || "User not found");
        } finally {
            setLookupLoading(false);
        }
    };

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
            <p className="text-sm text-zinc-400 mb-6">Real-time analytics + catalog ops + user data.</p>

            {/* Tab bar */}
            <div className="flex items-center gap-2 mb-8" data-testid="admin-tabs">
                {["dashboard", "pricing"].map((t) => (
                    <button
                        key={t}
                        onClick={() => {
                            setTab(t);
                            if (t === "pricing" && !pricing) loadPricing();
                        }}
                        data-testid={`admin-tab-${t}`}
                        className={`px-4 py-2 rounded-xl text-sm font-heading capitalize transition ${
                            tab === t
                                ? "bg-amber text-obsidian"
                                : "border border-white/10 text-zinc-400 hover:bg-white/5"
                        }`}
                    >
                        {t}
                    </button>
                ))}
            </div>

            {tab === "pricing" && (
                <PricingTab pricing={pricing} reload={loadPricing} />
            )}

            {tab === "dashboard" && (
            <>
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
                        <MiniStat label="DAU" value={analytics?.dau ?? 0} />
                        <MiniStat label="WAU" value={analytics?.wau ?? 0} />
                        <MiniStat label="MAU" value={analytics?.mau ?? 0} />
                        <MiniStat label="Save rate" value={`${analytics?.save_rate_pct ?? 0}%`} />
                    </div>
                    {Object.keys(analytics?.swipes_7d || {}).length > 0 && (
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

            {/* User lookup */}
            <div className="glass rounded-2xl p-5 mb-6" data-testid="lookup-card">
                <div className="font-heading text-base mb-1">User lookup</div>
                <div className="text-xs text-zinc-500 mb-3">Find any user by email — full taste + recommendation debug.</div>
                <form onSubmit={runLookup} className="flex gap-2 mb-3">
                    <input
                        type="email"
                        value={lookupEmail}
                        onChange={(e) => setLookupEmail(e.target.value)}
                        placeholder="user@example.com"
                        data-testid="lookup-email"
                        className="flex-1 bg-white/5 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-amber/50"
                    />
                    <button
                        type="submit"
                        disabled={lookupLoading}
                        data-testid="lookup-submit"
                        className="px-4 py-2 rounded-xl bg-amber text-obsidian font-heading text-sm disabled:opacity-60"
                    >
                        {lookupLoading ? "…" : "Look up"}
                    </button>
                </form>
                {lookupResult && (
                    <div className="text-xs text-zinc-300 space-y-2" data-testid="lookup-result">
                        <div className="rounded-xl bg-white/5 border border-white/8 p-3">
                            <div className="flex items-center justify-between">
                                <div className="font-heading text-sm">{lookupResult.user?.name}</div>
                                <span className="text-[10px] text-zinc-500">{lookupResult.user?.auth_provider}</span>
                            </div>
                            <div className="text-zinc-400 mb-2">{lookupResult.user?.email}</div>
                            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
                                <span>Saved <b className="text-zinc-200">{lookupResult.saved_count}</b></span>
                                <span>Watched <b className="text-zinc-200">{lookupResult.watched_count}</b></span>
                                <span>Skipped <b className="text-zinc-200">{lookupResult.skipped_count}</b></span>
                                <span>Actions <b className="text-zinc-200">{lookupResult.action_count}</b></span>
                                <span>Pool <b className="text-zinc-200">{lookupResult.debug?.pool_size ?? "—"}</b></span>
                            </div>
                            {lookupResult.user?.subscriptions?.length > 0 && (
                                <div className="mt-2 text-[10px] text-zinc-500">Subs: {lookupResult.user.subscriptions.join(", ")}</div>
                            )}
                            {lookupResult.user?.terms_accepted_at && (
                                <div className="mt-1 text-[10px] text-zinc-600">T&amp;C: {lookupResult.user.terms_accepted_at.slice(0, 10)}</div>
                            )}
                        </div>
                        {lookupResult.debug?.candidates?.length > 0 && (
                            <div className="rounded-xl bg-white/5 border border-white/8 p-3">
                                <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-2">Top recommendations (debug)</div>
                                <ul className="space-y-1">
                                    {lookupResult.debug.candidates.map((c) => (
                                        <li key={c.id} className="flex items-center justify-between gap-2 text-[11px]">
                                            <span className="truncate"><b className="text-zinc-200">{c.title}</b> <span className="text-zinc-500">({c.year})</span></span>
                                            <span className="text-amber tabular-nums">{c.score.toFixed(2)}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Provider health */}
            {providerHealth && (
                <div className="glass rounded-2xl p-5 mb-6" data-testid="provider-health-card">
                    <div className="flex items-center justify-between mb-3">
                        <div className="font-heading text-base">Provider health</div>
                        <span className="text-[10px] text-amber">{providerHealth.coverage_pct}% coverage</span>
                    </div>
                    <div className="grid grid-cols-3 gap-3 mb-3">
                        <MiniStat label="With any" value={providerHealth.with_any_provider} />
                        <MiniStat label="Enriched" value={providerHealth.providers_enriched} />
                        <MiniStat label="Pending" value={providerHealth.providers_pending} />
                    </div>
                    {Object.keys(providerHealth.by_subscription_service || {}).length > 0 && (
                        <div className="flex flex-wrap gap-2 text-[10px] text-zinc-400">
                            {Object.entries(providerHealth.by_subscription_service).slice(0, 8).map(([k, v]) => (
                                <span key={k} className="bg-white/5 rounded-full px-2 py-0.5">
                                    {k} <b className="text-zinc-200">{v}</b>
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Recommendation diagnostics */}
            {diagnostics && (
                <div className="glass rounded-2xl p-5 mb-6" data-testid="diagnostics-card">
                    <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-2">
                            <Activity className="w-4 h-4 text-amber" strokeWidth={1.8} />
                            <div className="font-heading text-base">Recommendation diagnostics</div>
                        </div>
                        <span className="text-[10px] uppercase tracking-wider text-zinc-500">read-only</span>
                    </div>

                    <DiagGroup title="Catalogue">
                        <DiagMetric label="Total" value={diagnostics.catalogue?.total} />
                        <DiagMetric
                            label="Eligible"
                            value={diagnostics.catalogue?.eligible}
                            status={statusEligible(diagnostics.catalogue?.eligible)}
                        />
                        <DiagMetric
                            label="Tier A+B"
                            value={
                                diagnostics.catalogue?.tier_a == null || diagnostics.catalogue?.tier_b == null
                                    ? null
                                    : diagnostics.catalogue.tier_a + diagnostics.catalogue.tier_b
                            }
                            status={statusTierAB(diagnostics.catalogue?.tier_a, diagnostics.catalogue?.tier_b)}
                        />
                        <DiagMetric label="Tier A" value={diagnostics.catalogue?.tier_a} />
                        <DiagMetric label="Tier B" value={diagnostics.catalogue?.tier_b} />
                        <DiagMetric label="Tier C" value={diagnostics.catalogue?.tier_c} />
                        <DiagMetric label="Tier D" value={diagnostics.catalogue?.tier_d} />
                    </DiagGroup>

                    <DiagGroup title="Freshness">
                        <DiagMetric label="Fresh Eligible" value={diagnostics.freshness?.fresh_eligible} />
                        <DiagMetric
                            label="Repeat Rate"
                            value={diagnostics.freshness?.repeat_rate_pct}
                            suffix="%"
                            status={statusRepeatRate(diagnostics.freshness?.repeat_rate_pct)}
                        />
                    </DiagGroup>

                    <DiagGroup title="Users">
                        <DiagMetric label="Heavy Users" value={diagnostics.users?.heavy_users} />
                    </DiagGroup>

                    <DiagGroup title="Recommendation health" last>
                        <DiagMetric
                            label="Diversity Score"
                            value={diagnostics.recommendation_health?.diversity_score}
                            status={statusDiversity(diagnostics.recommendation_health?.diversity_score)}
                        />
                    </DiagGroup>
                </div>
            )}

            {impressionConversions && (
                <div className="glass rounded-2xl p-5 mb-6" data-testid="impression-conversions-card">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <div className="font-heading text-base">Feed conversion</div>
                            <div className="text-xs text-zinc-500">First linked response to each served card</div>
                        </div>
                        <span className="text-[10px] uppercase tracking-wider text-zinc-500">90 days</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 mb-5">
                        <MiniStat label="Impressions" value={impressionConversions.summary?.impressions} />
                        <MiniStat label="Responses" value={impressionConversions.summary?.responded} />
                        <MiniStat
                            label="Response rate"
                            value={impressionConversions.summary?.response_rate_pct == null
                                ? null
                                : `${impressionConversions.summary.response_rate_pct}%`}
                        />
                    </div>
                    <ConversionTable title="Reason code" rows={impressionConversions.by_reason_code} />
                    <ConversionTable title="Feed slot" rows={impressionConversions.by_slot} />
                    <ConversionTable title="Quality tier" rows={impressionConversions.by_quality_tier} last />
                </div>
            )}

            {/* Users section */}
            <div className="glass rounded-2xl p-5 mb-6" data-testid="users-card">
                <button
                    className="w-full flex items-center justify-between"
                    onClick={() => setUsersOpen(o => !o)}
                >
                    <div>
                        <div className="font-heading text-base text-left">Users</div>
                        <div className="text-xs text-zinc-500 text-left">
                            {users ? `${users.length} accounts` : "Loading…"}
                        </div>
                    </div>
                    {usersOpen ? <ChevronUp className="w-4 h-4 text-zinc-400" /> : <ChevronDown className="w-4 h-4 text-zinc-400" />}
                </button>

                {usersOpen && users && (
                    <div className="mt-4 space-y-3" data-testid="users-list">
                        {users.map((u) => (
                            <div key={u.user_id} className="rounded-xl bg-white/5 border border-white/8 px-4 py-3 text-sm">
                                <div className="flex items-center justify-between mb-1">
                                    <div>
                                        <span className="font-heading text-zinc-100">{u.name}</span>
                                        {u.role === "admin" && (
                                            <span className="ml-2 text-[9px] uppercase tracking-wider text-amber border border-amber/40 rounded-full px-1.5 py-0.5">admin</span>
                                        )}
                                    </div>
                                    <span className="text-[10px] text-zinc-500">{u.auth_provider}</span>
                                </div>
                                <div className="text-xs text-zinc-400 mb-2">{u.email}</div>
                                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
                                    <span>Saved <span className="text-zinc-300 font-heading">{u.saved_count}</span></span>
                                    <span>Watched <span className="text-zinc-300 font-heading">{u.watched_count}</span></span>
                                    <span>Skipped <span className="text-zinc-300 font-heading">{u.skipped_count}</span></span>
                                    <span>Explore <span className="text-zinc-300 font-heading">{u.exploration_weight}</span></span>
                                    <span>Onboarded <span className="text-zinc-300 font-heading">{u.onboarding_completed ? "yes" : "no"}</span></span>
                                </div>
                                {u.genres?.length > 0 && (
                                    <div className="mt-1.5 flex flex-wrap gap-1">
                                        {u.genres.map(g => (
                                            <span key={g} className="text-[10px] bg-white/8 rounded-full px-2 py-0.5 text-zinc-400">{g}</span>
                                        ))}
                                    </div>
                                )}
                                {u.subscriptions?.length > 0 && (
                                    <div className="mt-1 text-[10px] text-zinc-600">
                                        {u.subscriptions.join(", ")}
                                    </div>
                                )}
                                <div className="mt-1 text-[10px] text-zinc-600">
                                    Joined {u.created_at?.slice(0, 10)}
                                    {u.last_action_at && ` · active ${u.last_action_at?.slice(0, 10)}`}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

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
            </>
            )}
        </div>
    );
}

// ── Pricing tab ────────────────────────────────────────────────────────────
const BILLING_TYPES = ["monthly", "annual", "free", "licence_required"];

function PricingTab({ pricing, reload }) {
    if (!pricing) {
        return (
            <div className="grid place-items-center py-16" data-testid="pricing-loading">
                <Loader2 className="w-6 h-6 text-amber animate-spin" />
            </div>
        );
    }
    return (
        <div data-testid="pricing-tab" className="space-y-5">
            <p className="text-xs text-zinc-500">
                UK plans (region GB · GBP). Edits are saved instantly and survive server restarts.
            </p>
            {pricing.services.map((svc) => (
                <ServicePricing key={svc.id} svc={svc} reload={reload} />
            ))}
        </div>
    );
}

function ServicePricing({ svc, reload }) {
    const [adding, setAdding] = useState(false);
    return (
        <div className="glass rounded-2xl p-5" data-testid={`pricing-service-${svc.id}`}>
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full" style={{ background: svc.logo_color || "#888" }} />
                    <div className="font-heading text-base">{svc.name}</div>
                </div>
                <button
                    onClick={() => setAdding((a) => !a)}
                    data-testid={`pricing-add-toggle-${svc.id}`}
                    className="text-xs px-3 py-1.5 rounded-lg border border-white/10 hover:bg-white/5 font-heading"
                >
                    {adding ? "Cancel" : "+ Add plan"}
                </button>
            </div>

            {adding && (
                <AddPlanForm
                    serviceId={svc.id}
                    onDone={() => { setAdding(false); reload(); }}
                />
            )}

            <div className="space-y-2 mt-2">
                {svc.plans.length === 0 ? (
                    <div className="text-xs text-zinc-500">No plans yet.</div>
                ) : (
                    svc.plans.map((p) => <PlanRow key={p.id} plan={p} reload={reload} />)
                )}
            </div>
        </div>
    );
}

function PlanRow({ plan, reload }) {
    const [monthly, setMonthly] = useState(plan.monthly_price ?? 0);
    const [annual, setAnnual] = useState(plan.annual_price ?? "");
    const [hasAds, setHasAds] = useState(!!plan.has_ads);
    const [active, setActive] = useState(!!plan.active);
    const [isPromo, setIsPromo] = useState(!!plan.is_promo);
    const [verified, setVerified] = useState(plan.price_verified_at || "");
    const [saving, setSaving] = useState(false);

    const save = async () => {
        setSaving(true);
        try {
            await api.patch(`/admin/pricing/plans/${plan.id}`, {
                monthly_price: parseFloat(monthly) || 0,
                annual_price: annual === "" ? null : parseFloat(annual),
                has_ads: hasAds,
                active,
                is_promo: isPromo,
                price_verified_at: verified || undefined,
            });
            toast.success(`${plan.name} updated`);
            reload();
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Save failed");
        } finally {
            setSaving(false);
        }
    };

    const deactivate = async () => {
        try {
            await apiPost(`/admin/pricing/plans/${plan.id}/deactivate`);
            toast.success(`${plan.name} deactivated`);
            reload();
        } catch (e) {
            toast.error("Deactivate failed");
        }
    };

    return (
        <div className="rounded-xl bg-white/5 border border-white/8 p-3" data-testid={`plan-row-${plan.id}`}>
            <div className="flex items-center justify-between mb-2">
                <div className="font-heading text-sm">
                    {plan.name}
                    {plan.addon && <span className="ml-2 text-[9px] uppercase text-zinc-500">add-on</span>}
                    {plan.billing_type === "licence_required" && (
                        <span className="ml-2 text-[9px] uppercase text-amber">licence</span>
                    )}
                    {isPromo && <span className="ml-2 text-[9px] uppercase text-emerald-400">promo</span>}
                </div>
                <span className="text-[10px] text-zinc-500">{plan.billing_type}</span>
            </div>
            <div className="grid grid-cols-2 gap-2 mb-2">
                <label className="text-[10px] text-zinc-500">
                    £/mo
                    <input
                        type="number" step="0.01" value={monthly}
                        onChange={(e) => setMonthly(e.target.value)}
                        data-testid={`plan-monthly-${plan.id}`}
                        className="w-full mt-0.5 bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-amber/50"
                    />
                </label>
                <label className="text-[10px] text-zinc-500">
                    £/yr (optional)
                    <input
                        type="number" step="0.01" value={annual}
                        onChange={(e) => setAnnual(e.target.value)}
                        data-testid={`plan-annual-${plan.id}`}
                        className="w-full mt-0.5 bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-amber/50"
                    />
                </label>
            </div>
            <label className="text-[10px] text-zinc-500 block mb-2">
                Verified date
                <input
                    type="date" value={verified?.slice(0, 10) || ""}
                    onChange={(e) => setVerified(e.target.value)}
                    data-testid={`plan-verified-${plan.id}`}
                    className="w-full mt-0.5 bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-amber/50"
                />
            </label>
            <div className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-400 mb-2">
                <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={hasAds} onChange={(e) => setHasAds(e.target.checked)} data-testid={`plan-ads-${plan.id}`} /> Ads
                </label>
                <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} data-testid={`plan-active-${plan.id}`} /> Active
                </label>
                <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={isPromo} onChange={(e) => setIsPromo(e.target.checked)} data-testid={`plan-promo-${plan.id}`} /> Promo
                </label>
            </div>
            <div className="flex items-center gap-2">
                <button
                    onClick={save} disabled={saving}
                    data-testid={`plan-save-${plan.id}`}
                    className="px-3 py-1.5 rounded-lg bg-amber text-obsidian font-heading text-xs disabled:opacity-60"
                >
                    {saving ? "Saving…" : "Save"}
                </button>
                <button
                    onClick={deactivate}
                    data-testid={`plan-deactivate-${plan.id}`}
                    className="px-3 py-1.5 rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 font-heading text-xs"
                >
                    Deactivate
                </button>
            </div>
        </div>
    );
}

function AddPlanForm({ serviceId, onDone }) {
    const [name, setName] = useState("");
    const [monthly, setMonthly] = useState("");
    const [annual, setAnnual] = useState("");
    const [billing, setBilling] = useState("monthly");
    const [hasAds, setHasAds] = useState(false);
    const [isPromo, setIsPromo] = useState(false);
    const [promoEnds, setPromoEnds] = useState("");
    const [saving, setSaving] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        if (!name.trim()) { toast.error("Name required"); return; }
        setSaving(true);
        try {
            await apiPost("/admin/pricing/plans", {
                service_id: serviceId,
                name: name.trim(),
                monthly_price: parseFloat(monthly) || 0,
                annual_price: annual === "" ? null : parseFloat(annual),
                billing_type: billing,
                has_ads: hasAds,
                is_promo: isPromo,
                promo_ends: isPromo && promoEnds ? promoEnds : null,
            });
            toast.success("Plan added");
            onDone();
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Add failed");
        } finally {
            setSaving(false);
        }
    };

    return (
        <form onSubmit={submit} className="rounded-xl bg-white/5 border border-white/8 p-3 mb-3 space-y-2" data-testid={`add-plan-${serviceId}`}>
            <input
                value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Plan name"
                data-testid={`add-plan-name-${serviceId}`}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-amber/50"
            />
            <div className="grid grid-cols-3 gap-2">
                <input type="number" step="0.01" value={monthly} onChange={(e) => setMonthly(e.target.value)} placeholder="£/mo"
                    className="bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-amber/50" />
                <input type="number" step="0.01" value={annual} onChange={(e) => setAnnual(e.target.value)} placeholder="£/yr"
                    className="bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-amber/50" />
                <select value={billing} onChange={(e) => setBilling(e.target.value)}
                    className="bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-amber/50">
                    {BILLING_TYPES.map((b) => <option key={b} value={b} className="bg-obsidian">{b}</option>)}
                </select>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-400">
                <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={hasAds} onChange={(e) => setHasAds(e.target.checked)} /> Ads
                </label>
                <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={isPromo} onChange={(e) => setIsPromo(e.target.checked)} /> Promo
                </label>
                {isPromo && (
                    <input type="date" value={promoEnds} onChange={(e) => setPromoEnds(e.target.value)}
                        className="bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-xs text-zinc-100 outline-none focus:border-amber/50" />
                )}
            </div>
            <button type="submit" disabled={saving}
                data-testid={`add-plan-submit-${serviceId}`}
                className="px-3 py-1.5 rounded-lg bg-amber text-obsidian font-heading text-xs disabled:opacity-60">
                {saving ? "Adding…" : "Add plan"}
            </button>
        </form>
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

function MiniStat({ label, value }) {
    return (
        <div className="rounded-xl bg-white/5 border border-white/8 px-3 py-2.5 text-center" data-testid={`mini-stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
            <div className="font-heading text-xl text-zinc-100">{value ?? "—"}</div>
            <div className="text-[9px] uppercase tracking-[0.18em] text-zinc-500 mt-0.5">{label}</div>
        </div>
    );
}

function ConversionTable({ title, rows = [], last = false }) {
    return (
        <div className={last ? "" : "mb-5"} data-testid={`conversion-${title.toLowerCase().replace(/\s+/g, "-")}`}>
            <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-2">{title}</div>
            {rows.length === 0 ? (
                <div className="text-xs text-zinc-500">Not enough linked data</div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead className="text-zinc-500">
                            <tr>
                                <th className="text-left font-normal pb-2">Group</th>
                                <th className="text-right font-normal pb-2">Shown</th>
                                <th className="text-right font-normal pb-2">Save</th>
                                <th className="text-right font-normal pb-2">Positive</th>
                                <th className="text-right font-normal pb-2">Skip</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row) => (
                                <tr key={String(row.value)} className="border-t border-white/5">
                                    <td className="py-2 pr-2 text-zinc-300">{row.value}</td>
                                    <td className="py-2 text-right tabular-nums text-zinc-400">{row.impressions}</td>
                                    <td className="py-2 text-right tabular-nums text-emerald-400">{row.save_rate_pct}%</td>
                                    <td className="py-2 text-right tabular-nums text-amber">{row.positive_rate_pct}%</td>
                                    <td className="py-2 text-right tabular-nums text-rose-400">{row.skip_rate_pct}%</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

// ── Recommendation diagnostics helpers ────────────────────────────────────
function statusEligible(v) {
    if (v == null) return "nodata";
    if (v < 150) return "critical";
    if (v < 300) return "warning";
    return "ok";
}
function statusTierAB(a, b) {
    if (a == null || b == null) return "nodata";
    const sum = a + b;
    if (sum < 100) return "critical";
    if (sum < 200) return "warning";
    return "ok";
}
function statusRepeatRate(v) {
    if (v == null) return "nodata";
    if (v > 30) return "critical";
    if (v > 15) return "warning";
    return "ok";
}
function statusDiversity(v) {
    if (v == null) return "nodata";
    if (v < 40) return "critical";
    if (v < 60) return "warning";
    return "ok";
}

const STATUS_DOT = {
    ok: "bg-emerald-400",
    warning: "bg-amber-400",
    critical: "bg-rose-500",
    nodata: "bg-zinc-600",
    neutral: "bg-zinc-600",
};

function DiagGroup({ title, last, children }) {
    return (
        <div className={last ? "" : "mb-4"}>
            <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-2">{title}</div>
            <div className="grid grid-cols-2 gap-2">{children}</div>
        </div>
    );
}

function DiagMetric({ label, value, suffix = "", status = "neutral" }) {
    const isNull = value == null;
    const display = isNull ? "Not enough data" : `${value}${suffix}`;
    const dot = STATUS_DOT[isNull ? "nodata" : status] || STATUS_DOT.neutral;
    const showDot = status !== "neutral" || isNull;
    return (
        <div
            className="rounded-xl bg-white/5 border border-white/8 px-3 py-2.5"
            data-testid={`diag-${label.toLowerCase().replace(/\s+/g, "-")}`}
        >
            <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-500">{label}</div>
                {showDot && <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />}
            </div>
            <div className={`font-heading mt-1 ${isNull ? "text-xs text-zinc-500" : "text-xl text-zinc-100 tabular-nums"}`}>
                {display}
            </div>
        </div>
    );
}
