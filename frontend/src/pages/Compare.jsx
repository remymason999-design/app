import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Sparkles, Heart, Star, Activity, Wand2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import { toast } from "sonner";
import { capture, EVENTS } from "@/lib/analytics";

const COMPARE_RETURN_KEY = "ws_compare_return";
const MOBILE_BREAKPOINT = 640;
const REACTION_META = {
    loved: { symbol: "❤️", label: "loved it" },
    liked: { symbol: "👍", label: "liked it" },
    neutral: { symbol: "😐", label: "thought it was okay" },
    disliked: { symbol: "👎", label: "didn't like it" },
};

function reactionMeta(value) {
    return REACTION_META[String(value || "").toLowerCase()] || null;
}

function uniqueTitles(items) {
    const seen = new Set();
    return (items || []).filter((item) => {
        if (!item?.id || seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
    });
}

function stableResponseSignature(response) {
    const { synced_at: _syncedAt, ...content } = response || {};
    return JSON.stringify(content);
}

function initialPageSize() {
    if (typeof window === "undefined") return 20;
    return window.innerWidth <= MOBILE_BREAKPOINT ? 12 : 20;
}

function readCompareReturn(locationKey, friendId) {
    try {
        const value = JSON.parse(sessionStorage.getItem(COMPARE_RETURN_KEY) || "null");
        return value?.locationKey === locationKey && value?.friendId === friendId ? value : null;
    } catch { return null; }
}

export default function Compare() {
    const { friendId } = useParams();
    const location = useLocation();
    const pendingReturn = useRef(readCompareReturn(location.key, friendId));
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [pageLoading, setPageLoading] = useState(false);
    const [loadError, setLoadError] = useState(false);
    const [retryKey, setRetryKey] = useState(0);
    const [tab, setTab] = useState(pendingReturn.current?.tab || "watchlists");
    const [secondary, setSecondary] = useState(pendingReturn.current?.secondary || "overlap");
    const [page, setPage] = useState(pendingReturn.current?.page || 1);
    const [pageSize, setPageSize] = useState(initialPageSize);
    const lastSync = useRef(null);
    const resultsRef = useRef(null);
    useEffect(() => { capture(EVENTS.FRIEND_COMPARE_OPENED, { compare_mode: "watchlists" }, { dedupeKey: `compare:${friendId}` }); }, [friendId]);

    useEffect(() => {
        let alive = true;
        let inFlight = false;
        const controller = new AbortController();
        const fetchOnce = async () => {
            if (inFlight) return;
            inFlight = true;
            setLoadError(false);
            try {
                const params = new URLSearchParams({
                    view: tab,
                    scope: secondary,
                    page: String(page),
                    page_size: String(pageSize),
                });
                const r = await apiGet(`/share/compare/${friendId}?${params}`, { signal: controller.signal });
                if (!alive) return;
                const sig = stableResponseSignature(r);
                if (lastSync.current === sig) return;
                lastSync.current = sig;
                setData(Array.isArray(r.items) ? { ...r, items: uniqueTitles(r.items) } : r);
                if (r.pagination?.page && r.pagination.page !== page) setPage(r.pagination.page);
            } catch (e) {
                if (e.code === "ERR_CANCELED") return;
                if (e.response?.status === 403) {
                    toast.error("You're not sharing watchlists with this user");
                    navigate("/friends", { replace: true });
                } else {
                    setLoadError(true);
                }
            } finally {
                inFlight = false;
                if (alive) setLoading(false);
                if (alive) setPageLoading(false);
            }
        };
        fetchOnce();
        const refresh = () => {
            if (document.visibilityState === "visible") fetchOnce();
        };
        window.addEventListener("focus", refresh);
        document.addEventListener("visibilitychange", refresh);
        return () => {
            alive = false;
            controller.abort();
            window.removeEventListener("focus", refresh);
            document.removeEventListener("visibilitychange", refresh);
        };
    }, [friendId, navigate, tab, secondary, page, pageSize, retryKey]);

    useEffect(() => {
        const onResize = () => {
            const next = initialPageSize();
            setPageSize((current) => {
                if (current === next) return current;
                setPage(1);
                return next;
            });
        };
        window.addEventListener("resize", onResize);
        return () => window.removeEventListener("resize", onResize);
    }, []);

    useEffect(() => { capture(EVENTS.FRIEND_COMPARE_TAB_VIEWED, { tab }, { dedupeKey: `compare-tab:${friendId}:${tab}` }); }, [friendId, tab]);
    const hasData = !!data;
    useEffect(() => {
        const saved = Number(pendingReturn.current?.scrollY);
        if (loading || !hasData || !Number.isFinite(saved) || saved <= 0) return;
        const frame = requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                pendingReturn.current = null;
                window.scrollTo({ top: saved, behavior: "auto" });
                try { sessionStorage.removeItem(COMPARE_RETURN_KEY); } catch {}
            });
        });
        return () => cancelAnimationFrame(frame);
    }, [hasData, loading]);

    const openTitle = (id) => {
        try {
            sessionStorage.setItem(COMPARE_RETURN_KEY, JSON.stringify({
                locationKey: location.key, friendId, tab, secondary, scrollY: window.scrollY,
                page,
            }));
        } catch {}
        navigate(`/movie/${id}`);
    };

    if (loading) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }
    if (loadError && !data) {
        return (
            <div className="min-h-screen px-5 grid place-items-center max-w-md mx-auto">
                <div className="glass rounded-3xl p-6 text-center w-full">
                    <h1 className="font-display text-2xl">Comparison couldn't load</h1>
                    <p className="text-sm text-zinc-400 mt-2">Please try again. Your Friends list is still available.</p>
                    <div className="flex gap-3 mt-5">
                        <button onClick={() => navigate("/friends")} className="min-h-11 flex-1 rounded-xl border border-white/10">Back</button>
                        <button onClick={() => { setLoading(true); setRetryKey((key) => key + 1); }} className="min-h-11 flex-1 rounded-xl bg-amber text-obsidian font-heading">Try again</button>
                    </div>
                </div>
            </div>
        );
    }

    const fallbackList = tab === "recs"
        ? (data.recommendations || data.for_you || [])
        : tab === "watched"
            ? ((data.watched && data.watched[secondary === "overlap" ? "both" : secondary === "only_me" ? "you" : "friend"]) || data.watched_both || [])
            : ((data.saved && data.saved[secondary === "overlap" ? "both" : secondary === "only_me" ? "you" : "friend"]) || (secondary === "only_me" ? data.only_me || [] : secondary === "only_them" ? data.only_them || [] : data.overlap || []));
    const canonicalFallback = uniqueTitles(fallbackList);
    const list = data.items || canonicalFallback.slice((page - 1) * pageSize, page * pageSize);
    const totalItems = data.pagination?.total_items ?? canonicalFallback.length;
    const totalPages = data.pagination?.total_pages ?? Math.max(1, Math.ceil(totalItems / pageSize));
    const overlapCount = data.overlap_count ?? data.overlap?.length ?? 0;

    const changePage = (nextPage) => {
        const bounded = Math.max(1, Math.min(nextPage, totalPages));
        if (bounded === page) return;
        setPageLoading(true);
        setPage(bounded);
        requestAnimationFrame(() => {
            const top = Math.max(0, (resultsRef.current?.offsetTop || 0) - 16);
            window.scrollTo({ top, behavior: "auto" });
        });
    };

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="compare-page">
            <button
                onClick={() => navigate("/friends")}
                className="flex items-center gap-2 text-zinc-400 hover:text-zinc-100 mb-6 text-sm"
                data-testid="compare-back"
            >
                <ArrowLeft className="w-4 h-4" /> Friends
            </button>

            {/* Header with both avatars */}
            <div className="flex items-center justify-between mb-5">
                <div className="flex items-center -space-x-3">
                    <Avatar user={data.you} ring />
                    <Avatar user={data.them} ring />
                </div>
            </div>

            <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">You & {data.them.name}</p>
            <h1 className="font-display text-3xl mt-1 leading-tight">
                {overlapCount > 0 ? (
                    <>You both saved <span className="text-amber" data-testid="overlap-count">{overlapCount}</span> title{overlapCount === 1 ? "" : "s"}.</>
                ) : (
                    <>No overlap — yet.</>
                )}
            </h1>

            {/* Pick tonight */}
            {data.pick_tonight && (
                <div
                    className="mt-6 glass rounded-3xl p-5 border border-amber/20"
                    data-testid="pick-tonight"
                >
                    <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-amber" />
                        <span className="text-[10px] uppercase tracking-[0.22em] text-amber font-heading">
                            {overlapCount > 0 ? "Pick tonight" : "What you'll both love"}
                        </span>
                    </div>
                    <button
                        onClick={() => {
                            capture(EVENTS.FRIEND_OVERLAP_ITEM_OPENED, {
                                content_id: data.pick_tonight.id,
                                compare_mode: "pick_tonight",
                                overlap_count: overlapCount,
                            }, { dedupeKey: `compare-overlap:pick:${data.pick_tonight.id}` });
                            openTitle(data.pick_tonight.id);
                        }}
                        className="flex items-center gap-4 w-full text-left group"
                        data-testid="pick-tonight-cta"
                    >
                        <div className="w-20 h-28 rounded-xl bg-velvet overflow-hidden shrink-0 ring-1 ring-white/10">
                            {data.pick_tonight.poster_url && (
                                <img
                                    loading="lazy"
                                    src={data.pick_tonight.poster_url}
                                    alt={data.pick_tonight.title}
                                    className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                                />
                            )}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="font-heading text-base leading-tight mb-1 truncate">{data.pick_tonight.title}</div>
                            <div className="flex items-center gap-2 text-[11px] text-zinc-400 mb-2">
                                {data.pick_tonight.rating != null && (
                                    <span className="flex items-center gap-1">
                                        <Star className="w-3 h-3 fill-amber text-amber" /> {data.pick_tonight.rating}
                                    </span>
                                )}
                                <span className="text-zinc-600">·</span>
                                <span className="truncate">{(data.pick_tonight.genres || []).join(" · ")}</span>
                            </div>
                            <div className="text-xs text-zinc-300">Open details →</div>
                        </div>
                    </button>
                </div>
            )}

            {/* Tabs */}
            <div className="grid grid-cols-3 gap-1.5 mt-6 p-1 bg-white/4 rounded-2xl border border-white/5" data-testid="compare-tabs">
                {[{ id: "watchlists", label: "Watchlists" }, { id: "watched", label: "Watched" }, { id: "recs", label: "For You Both" }].map((t) => (
                    <button
                        key={t.id}
                        onClick={() => { setPageLoading(true); setTab(t.id); setPage(1); }}
                        data-testid={`compare-primary-${t.id}`}
                        className={`relative px-2 py-2.5 rounded-xl text-[11px] font-heading transition-colors ${
                            tab === t.id ? "bg-amber text-obsidian" : "text-zinc-400 hover:text-zinc-100"
                        }`}
                    >
                        <div className="truncate">{t.label}</div>
                    </button>
                ))}
            </div>
            {(tab === "watchlists" || tab === "watched") && <div className="grid grid-cols-3 gap-1.5 mt-2 p-1 bg-white/3 rounded-xl" data-testid="compare-secondary-tabs">
                {[["overlap", "Both"], ["only_me", "You"], ["only_them", data.them.name.split(" ")[0]]].map(([id, label]) => (
                    <button key={id} onClick={() => { setPageLoading(true); setSecondary(id); setPage(1); }} data-testid={`compare-secondary-${id}`} className={`py-2 rounded-lg text-[11px] ${secondary === id ? "bg-white/10 text-amber" : "text-zinc-500"}`}>{label}</button>
                ))}
            </div>}

            {/* List */}
            <div ref={resultsRef} className="mt-5 scroll-mt-4" data-testid={`compare-list-${tab}`}>
                {pageLoading ? (
                    <PageSkeleton count={pageSize} />
                ) : list.length === 0 ? (
                    <EmptyState tab={tab === "watchlists" || tab === "watched" ? secondary : tab} themName={data.them.name} />
                ) : (
                    <ul className="grid grid-cols-3 gap-2.5">
                            {list.map((m) => {
                                const friendReaction = reactionMeta(data.sentiment?.friend?.[m.id]);
                                const yourReaction = reactionMeta(data.sentiment?.you?.[m.id] || m.you_reaction);
                                const banner = friendReaction
                                    ? { ...friendReaction, who: data.them.name.split(" ")[0] }
                                    : yourReaction
                                        ? { ...yourReaction, who: "You" }
                                        : null;
                                return (
                                <li
                                    key={m.id}
                                    onClick={() => {
                                        capture(EVENTS.FRIEND_OVERLAP_ITEM_OPENED, {
                                            content_id: m.id,
                                            compare_mode: tab,
                                            overlap_count: overlapCount,
                                            shared_watchlist_count: tab === "watchlists" ? totalItems : 0,
                                            recommended_for_both_count: tab === "recs" ? totalItems : 0,
                                        }, { dedupeKey: `compare-overlap:${tab}:${m.id}` });
                                        openTitle(m.id);
                                    }}
                                    className="cursor-pointer group"
                                    data-testid={`compare-card-${m.id}`}
                                >
                                    <div className="relative aspect-[2/3] rounded-xl bg-velvet overflow-hidden ring-1 ring-white/5 group-hover:ring-amber/30 transition-shadow">
                                        {m.poster_url ? (
                                            <img loading="lazy" width="240" height="360" src={m.poster_url} alt={m.title} className="absolute inset-0 w-full h-full object-cover group-hover:scale-[1.03] transition-transform" />
                                        ) : (
                                            <div className="w-full h-full grid place-items-center text-zinc-600 text-[10px] p-1 text-center">{m.title}</div>
                                        )}
                                        {banner && (
                                            <div className="absolute inset-x-0 bottom-0 bg-black/85 backdrop-blur-sm border-t border-white/15 px-2 py-2 text-[9px] leading-tight text-white font-medium" data-testid={`reaction-banner-${m.id}`}>
                                                <span className="mr-1" aria-hidden="true">{banner.symbol}</span>
                                                {banner.who} {banner.label}
                                            </div>
                                        )}
                                    </div>
                                    <div className="text-[10px] mt-1.5 text-zinc-300 line-clamp-1">{m.title}</div>
                                    {m.rating != null && (
                                        <div className="text-[10px] text-zinc-500 flex items-center gap-1">
                                            <Star className="w-2.5 h-2.5 fill-amber text-amber" /> {m.rating}
                                        </div>
                                    )}
                                    {(data.progress?.you?.[m.id] || data.progress?.friend?.[m.id]) && <div className="text-[9px] text-zinc-400 mt-1">{data.progress?.you?.[m.id] ? `You S${data.progress.you[m.id].season} E${data.progress.you[m.id].episode}` : ""}{data.progress?.friend?.[m.id] ? ` · ${data.them.name.split(" ")[0]} S${data.progress.friend[m.id].season} E${data.progress.friend[m.id].episode}` : ""}</div>}
                                </li>
                                );
                            })}
                    </ul>
                )}
                {!pageLoading && totalItems > 0 && (
                    <Pagination page={page} totalPages={totalPages} onChange={changePage} />
                )}
            </div>

            <div className="mt-8 flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-600">
                <Activity className="w-3 h-3" /> Refreshes when you return
            </div>
        </div>
    );
}

function EmptyState({ tab, themName }) {
    const messages = {
        overlap: { icon: Heart, title: "No shared picks yet", body: "Keep swiping — overlap appears the moment you both save the same title." },
        only_me: { icon: Heart, title: "Nothing here yet", body: "Your titles will appear here as you save or watch them." },
        only_them: { icon: Heart, title: `${themName} has no titles here yet`, body: "Their picks will appear here as they save or watch." },
        watched: { icon: EyeIcon, title: "No watched overlap yet", body: "Titles you have both watched will appear here." },
        recs: { icon: Wand2, title: "Building recommendations", body: "Keep using the app — once we learn both your tastes, smart picks land here." },
    };
    const m = messages[tab];
    const Icon = m.icon;
    return (
        <div className="glass rounded-2xl p-6 text-center">
            <Icon className="w-5 h-5 text-amber mx-auto mb-2" />
            <div className="font-heading text-sm mb-1">{m.title}</div>
            <p className="text-xs text-zinc-500">{m.body}</p>
        </div>
    );
}

function PageSkeleton({ count }) {
    return (
        <ul className="grid grid-cols-3 gap-2.5" aria-label="Loading page">
            {Array.from({ length: Math.min(count, 12) }, (_, index) => (
                <li key={index} className="animate-pulse">
                    <div className="aspect-[2/3] rounded-xl bg-white/8 ring-1 ring-white/5" />
                    <div className="h-2.5 w-4/5 rounded bg-white/8 mt-2" />
                </li>
            ))}
        </ul>
    );
}

function Pagination({ page, totalPages, onChange }) {
    return (
        <nav className="mt-7 flex items-center justify-between gap-3" aria-label="Compare pages" data-testid="compare-pagination">
            <button disabled={page <= 1} onClick={() => onChange(page - 1)} className="min-h-11 px-4 rounded-xl border border-white/10 text-sm disabled:opacity-35 hover:bg-white/5">Previous</button>
            <span className="text-xs text-zinc-400" data-testid="compare-page-indicator">Page {page} of {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => onChange(page + 1)} className="min-h-11 px-4 rounded-xl bg-amber text-obsidian text-sm font-heading disabled:opacity-35">Next</button>
        </nav>
    );
}

function EyeIcon(props) {
    return <span {...props}>◉</span>;
}

function Avatar({ user, ring }) {
    const initial = (user?.name || "?").slice(0, 1).toUpperCase();
    if (user?.picture) {
        return (
            <img
                src={user.picture}
                alt={user.name}
                className={`w-10 h-10 rounded-full object-cover ${ring ? "ring-2 ring-obsidian" : ""}`}
            />
        );
    }
    return (
        <div className={`w-10 h-10 rounded-full bg-amber/20 border border-amber/40 grid place-items-center font-heading text-amber ${ring ? "ring-2 ring-obsidian" : ""}`}>
            {initial}
        </div>
    );
}
