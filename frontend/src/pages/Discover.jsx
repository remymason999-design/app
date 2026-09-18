import { useEffect, useState, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence, useMotionValue, useTransform } from "framer-motion";
import { Heart, X, Info, Star, Sparkles, Search, SlidersHorizontal, RotateCcw, Eye } from "lucide-react";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { afterSuccessfulMutation } from "@/lib/analytics-flow";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import Tutorial, { shouldShowTutorial } from "@/components/Tutorial";
import FiltersSheet from "@/components/FiltersSheet";
import WatchedFeedbackDialog from "@/components/WatchedFeedbackDialog";
import { ProviderLogo } from "@/components/ProviderLogo";
import { formatRuntime } from "@/lib/format";
import { capture, markFirstDiscoverAction, interactionBucket, shouldCaptureVisiblePresentation, EVENTS } from "@/lib/analytics";

const STACK_CACHE_KEY = "ws_stack_v2";
const STACK_CACHE_TTL = 30 * 60 * 1000; // 30 minutes — larger batches stay fresh longer
const INITIAL_LIMIT = 180;               // deep initial queue so swipes never wait on backend

const TABS = [
    { id: "for-you", label: "For You", endpoint: `/discover?limit=${INITIAL_LIMIT}` },
    { id: "movies", label: "Movies", endpoint: `/discover?limit=${INITIAL_LIMIT}&content_type=movie` },
    { id: "tv", label: "TV Shows", endpoint: `/discover?limit=${INITIAL_LIMIT}&content_type=tv` },
    { id: "new", label: "New", endpoint: "/sections/upcoming" },
];
// Personalised /discover-backed tabs: they share refill + feed-meta banners.
const PERSONAL_TABS = ["for-you", "movies", "tv"];
const TAB_CONTENT_TYPE = { movies: "movie", tv: "tv" };
const FEED_CONTENT_TYPE = { "for-you": "mixed", movies: "movie", tv: "tv", new: "mixed" };
const TAB_PREF_KEY = "ws_discover_tab_v1";
const REFILL_THRESHOLD = 55;             // trigger background refill when stack drops to ~55
const REFILL_BATCH = "/discover?limit=120"; // background refill batch size (100–150)
const PRELOAD_AHEAD = 14;                // how many upcoming poster/backdrop images to prefetch
const PRELOAD_CAP = 400;                 // LRU cap on preloaded URL set (long-session memory bound)
const USER_REFRESH_EVERY_N_SWIPES = 10;  // debounce: only refresh user object every 10 swipes
const USER_REFRESH_INTERVAL_MS = 45_000; // …or every 45s, whichever comes first
const SHOW_DEBUG = typeof window !== "undefined" && /[?&]debug=1/.test(window.location.search);

export default function Discover() {
    const navigate = useNavigate();
    const { user, refresh, setUser } = useAuth();
    const userSubs = useMemo(() => user?.subscriptions || [], [user]);
    // Restore the last-viewed tab synchronously so returning from MovieDetail
    // lands on the same tab the user was on (Task #3 — full state persistence).
    const [tab, setTab] = useState(() => {
        try {
            const t = sessionStorage.getItem(TAB_PREF_KEY);
            if (t && TABS.some((x) => x.id === t)) return t;
        } catch {}
        return "for-you";
    });
    const [stack, setStack] = useState([]);
    const [history, setHistory] = useState([]);
    const [services, setServices] = useState([]);
    const [loading, setLoading] = useState(true);
    const [exiting, setExiting] = useState(null);
    const [entering, setEntering] = useState(null);
    const [tutorial, setTutorial] = useState(false);
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [watchedPrompt, setWatchedPrompt] = useState(null);
    const [pageVisible, setPageVisible] = useState(false);
    const [cardInViewport, setCardInViewport] = useState(false);
    const cardViewportRef = useRef(null);
    const [feedMeta, setFeedMeta] = useState(null);
    const [subBannerDismissed, setSubBannerDismissed] = useState(false);
    // Toggles are now persisted on the user document so opt-in survives reloads.
    const [includeOtherServices, _setIncludeOtherServices] = useState(!!user?.include_other_services);
    const [includeRentBuy, _setIncludeRentBuy] = useState(!!user?.include_rent_buy);

    // Sync local state when user doc changes (e.g. after login or refresh).
    useEffect(() => {
        _setIncludeOtherServices(!!user?.include_other_services);
        _setIncludeRentBuy(!!user?.include_rent_buy);
    }, [user?.include_other_services, user?.include_rent_buy]);

    const setIncludeOtherServices = (val) => {
        const v = typeof val === "function" ? val(includeOtherServices) : val;
        _setIncludeOtherServices(v);
        // Optimistic local user update + persist to backend.
        setUser?.((u) => (u ? { ...u, include_other_services: v } : u));
        apiPut("/user/preferences", { include_other_services: v }).catch(() => {});
    };
    const setIncludeRentBuy = (val) => {
        const v = typeof val === "function" ? val(includeRentBuy) : val;
        _setIncludeRentBuy(v);
        setUser?.((u) => (u ? { ...u, include_rent_buy: v } : u));
        apiPut("/user/preferences", { include_rent_buy: v }).catch(() => {});
    };

    useEffect(() => {
        if (shouldShowTutorial()) {
            const t = setTimeout(() => setTutorial(true), 600);
            return () => clearTimeout(t);
        }
    }, []);

    useEffect(() => {
        const updateVisibility = () => {
            setPageVisible(document.visibilityState === "visible" && document.hasFocus());
        };
        updateVisibility();
        document.addEventListener("visibilitychange", updateVisibility);
        window.addEventListener("focus", updateVisibility);
        window.addEventListener("blur", updateVisibility);
        return () => {
            document.removeEventListener("visibilitychange", updateVisibility);
            window.removeEventListener("focus", updateVisibility);
            window.removeEventListener("blur", updateVisibility);
        };
    }, []);

    useEffect(() => {
        const node = cardViewportRef.current;
        if (!node || typeof IntersectionObserver === "undefined") return;
        const observer = new IntersectionObserver(([entry]) => {
            setCardInViewport(Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.5));
        }, { threshold: 0.5 });
        observer.observe(node);
        return () => observer.disconnect();
    }, []);

    const loadStack = async (tabId = tab, forceReload = false) => {
        // Restore cached stack if returning from MovieDetail (no forceReload).
        // Cache hit requires tab AND filter toggles to match — otherwise the
        // cached results were generated under different parameters and must
        // be refetched.
        if (!forceReload) {
            try {
                const raw = sessionStorage.getItem(STACK_CACHE_KEY);
                if (raw) {
                    const cached = JSON.parse(raw);
                    if (cached.tab === tabId
                        && !!cached.includeOtherServices === !!includeOtherServices
                        && !!cached.includeRentBuy === !!includeRentBuy
                        && Date.now() - cached.ts < STACK_CACHE_TTL
                        && cached.stack?.length > 0) {
                        setStack(cached.stack);
                        setServices(cached.services || []);
                        setFeedMeta(cached.stack?.[0]?._signals?.feed_meta || null);
                        capture(EVENTS.FEED_LOADED, {
                            selected_tab: tabId,
                            card_count: cached.stack.length,
                            source: "cache",
                            content_type: FEED_CONTENT_TYPE[tabId] || "mixed",
                        }, { user, dedupeKey: `feed:${tabId}:cache:${cached.ts || ""}` });
                        if (typeof cached.subBannerDismissed === "boolean") {
                            setSubBannerDismissed(cached.subBannerDismissed);
                        }
                        setLoading(false);
                        return;
                    }
                }
            } catch {}
        }
        setLoading(true);
        setSubBannerDismissed(false);
        try {
            let ep = TABS.find((t) => t.id === tabId)?.endpoint || "/discover";
            // Apply toggles to ALL tabs — sections honor the same flags as /discover.
            if (includeOtherServices || includeRentBuy) {
                const sep = ep.includes("?") ? "&" : "?";
                const params = [
                    includeOtherServices ? "include_other_services=true" : null,
                    includeRentBuy ? "include_rent_buy=true" : null,
                ].filter(Boolean).join("&");
                ep += sep + params;
            }
            const _t0 = performance.now();
            const [movies, svcs] = await Promise.all([apiGet(ep), apiGet("/services")]);
            const _apiMs = Math.round(performance.now() - _t0);
            setPerf(p => ({ ...p, apiMs: _apiMs }));
            setStack(movies);
            setServices(svcs);
            setFeedMeta(movies?.[0]?._signals?.feed_meta || null);
            capture(EVENTS.FEED_LOADED, {
                selected_tab: tabId,
                card_count: Array.isArray(movies) ? movies.length : 0,
                source: "network",
                duration_ms: _apiMs,
                content_type: FEED_CONTENT_TYPE[tabId] || "mixed",
            }, { user });
            // Cache so the stack survives a trip to MovieDetail and back.
            // Include filter values so a stale-filter cache can't be served.
            try {
                sessionStorage.setItem(STACK_CACHE_KEY, JSON.stringify({
                    tab: tabId, stack: movies, services: svcs,
                    includeOtherServices, includeRentBuy,
                    subBannerDismissed: false, ts: Date.now(),
                }));
            } catch {}
        } finally {
            setLoading(false);
        }
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => { loadStack(tab); }, [tab]);

    // Persist the active tab so a remount (e.g. returning from MovieDetail)
    // restores the same tab rather than snapping back to "for-you".
    useEffect(() => {
        try { sessionStorage.setItem(TAB_PREF_KEY, tab); } catch {}
    }, [tab]);

    // Keep the persisted banner-dismissed flag in sync so dismissing the
    // sub-limit banner sticks across a MovieDetail round-trip.
    useEffect(() => {
        try {
            const raw = sessionStorage.getItem(STACK_CACHE_KEY);
            if (!raw) return;
            const cached = JSON.parse(raw);
            if (cached.subBannerDismissed === subBannerDismissed) return;
            sessionStorage.setItem(STACK_CACHE_KEY, JSON.stringify({
                ...cached, subBannerDismissed, ts: cached.ts || Date.now(),
            }));
        } catch {}
    }, [subBannerDismissed]);

    const [refilling, setRefilling] = useState(false);
    const refillFailures = useRef(0);
    const [perf, setPerf] = useState({
        apiMs: 0,
        preloaded: 0,
        lastSwipeMs: 0,
        renderMs: 0,
        refillReturned: 0,
        refillRejected: 0,
    });
    // Debounce counters for user refresh after swipe (Task 2 step 3).
    const swipesSinceRefresh = useRef(0);
    const lastUserRefresh = useRef(Date.now());
    // Track image URLs we've already kicked off a preload for so we don't
    // spam the browser with duplicate <img> requests.
    const preloadedUrls = useRef(new Set());
    // Generation token bumped whenever filters/tab change — refills tagged
    // with an older generation drop their results so they cannot contaminate
    // a stack rebuilt against new filters.
    const stackGen = useRef(0);
    useEffect(() => {
        if (!PERSONAL_TABS.includes(tab) || loading || refilling || stack.length === 0) return;
        // Stop retrying after 3 consecutive refills that yielded no new cards —
        // prevents an infinite fetch loop when the catalog is exhausted for this user.
        if (refillFailures.current >= 3) return;
        if (stack.length < REFILL_THRESHOLD) {
            setRefilling(true);
            const refillGen = stackGen.current;
            const _ct = TAB_CONTENT_TYPE[tab];
            const _refillUrl = REFILL_BATCH +
                (_ct ? `&content_type=${_ct}` : "") +
                (includeOtherServices ? "&include_other_services=true" : "") +
                (includeRentBuy ? "&include_rent_buy=true" : "");
            apiGet(_refillUrl).then(more => {
                // Filters or tab changed mid-flight — discard stale results.
                if (refillGen !== stackGen.current) return;
                const returned = more?.length || 0;
                if (!returned) {
                    refillFailures.current += 1;
                    setPerf(p => ({ ...p, refillReturned: 0, refillRejected: 0 }));
                    return;
                }
                setStack(prev => {
                    const ids = new Set(prev.map(m => m.id));
                    const fresh = more.filter(m => !ids.has(m.id));
                    const rejected = returned - fresh.length;
                    setPerf(p => ({ ...p, refillReturned: returned, refillRejected: rejected }));
                    if (!fresh.length) {
                        refillFailures.current += 1;
                        return prev;
                    }
                    refillFailures.current = 0;
                    // Update cache with the extended stack
                    try {
                        sessionStorage.setItem(STACK_CACHE_KEY, JSON.stringify({
                            tab, stack: [...prev, ...fresh], services,
                            includeOtherServices, includeRentBuy,
                            subBannerDismissed, ts: Date.now(),
                        }));
                    } catch {}
                    return [...prev, ...fresh];
                });
            }).catch(() => { refillFailures.current += 1; })
              .finally(() => { if (refillGen === stackGen.current) setRefilling(false); });
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [stack.length, tab, loading, refilling]);

    // ── Image preloader ─────────────────────────────────────────────────────
    // Decode the next N posters + backdrops in advance so each new top card
    // appears with its image already painted (the root cause of the "blank
    // screen" between swipes was the next card's <img> only mounting AFTER
    // the previous card finished its 220ms exit animation).
    useEffect(() => {
        if (!stack.length) return;
        const upcoming = stack.slice(0, PRELOAD_AHEAD);
        const set = preloadedUrls.current;
        let added = 0;
        upcoming.forEach((m) => {
            for (const url of [m?.poster_url, m?.backdrop_url]) {
                if (url && !set.has(url)) {
                    set.add(url);
                    const img = new Image();
                    img.decoding = "async";
                    img.src = url;
                    added += 1;
                }
            }
        });
        // LRU cap — evict oldest insertions so the Set can't grow unbounded
        // across long swipe sessions (Set preserves insertion order).
        while (set.size > PRELOAD_CAP) {
            const first = set.values().next().value;
            set.delete(first);
        }
        if (added) setPerf(p => ({ ...p, preloaded: set.size }));
    }, [stack]);

    // Bump generation on tab/filter changes so any in-flight refill is invalidated.
    // Also force-reset `refilling` so the new generation is never permanently
    // locked out by an abandoned in-flight request that skipped its cleanup.
    useEffect(() => {
        stackGen.current += 1;
        refillFailures.current = 0;
        setRefilling(false);
    }, [tab, includeOtherServices, includeRentBuy]);

    // When filter toggles change, refresh the stack. We use a ref to skip the
    // initial mount run — otherwise returning from MovieDetail (which remounts
    // Discover with the same toggle values) would force a fetch and bypass
    // the sessionStorage cache, losing the user's place. On a real toggle
    // change, loadStack() will see filter mismatch in the cache and refetch.
    const filtersInitDone = useRef(false);
    useEffect(() => {
        if (!filtersInitDone.current) { filtersInitDone.current = true; return; }
        loadStack(tab, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [includeOtherServices, includeRentBuy]);

    const top = stack[0];
    const visibleAt = useRef(Date.now());
    const presentationKey = useRef(null);
    const visibleDurations = useRef(new Map());
    const sessionImpressionNumber = useRef(0);
    const interactionCountRef = useRef(Number(user?.post_onboarding_interactions || 0));
    useEffect(() => {
        interactionCountRef.current = Math.max(
            interactionCountRef.current,
            Number(user?.post_onboarding_interactions || 0),
        );
    }, [user?.post_onboarding_interactions]);
    useEffect(() => {
        const visible = Boolean(top && !loading && pageVisible && cardInViewport && !tutorial && !filtersOpen);
        if (!visible || !top) {
            presentationKey.current = null;
            return;
        }
        const key = `${top.id}:${top.impression_id || ""}:${tab}`;
        if (!shouldCaptureVisiblePresentation(presentationKey.current, key, visible)) return;
        presentationKey.current = key;
        visibleAt.current = Date.now();
        sessionImpressionNumber.current += 1;
        const interactionCount = interactionCountRef.current;
        capture(EVENTS.RECOMMENDATION_IMPRESSION, {
            content_id: top.id,
            impression_id: top.impression_id || undefined,
            media_type: top.type || "movie",
            feed_type: tab,
            recommendation_source: top?._signals?.source || undefined,
            reason: top?._signals?.reason || undefined,
            genres: Array.isArray(top.genres) ? top.genres.slice(0, 20) : undefined,
            provider: top.provider_id || top.provider || undefined,
            user_interaction_count: interactionCount,
            session_impression_number: sessionImpressionNumber.current,
            interaction_bucket: interactionBucket(interactionCount),
        }, { user, dedupeKey: `impression:${key}`, allowDuplicate: true });
    }, [top?.id, top?.impression_id, tab, loading, pageVisible, cardInViewport, tutorial, filtersOpen, user]);

    const handleAction = async (action, dir, watchedMeta = null) => {
        if (!top) return;
        const _swipeT0 = performance.now();
        setExiting({ id: top.id, dir });
        // Fire user-action POST in the background — DO NOT await; the next
        // card must be ready immediately, never gated on backend round-trip.
        //
        // Debounced user refresh (Task 2 step 3): refresh() rehydrates the
        // entire user document and was previously running after EVERY swipe,
        // adding a backend round-trip + React re-render on the swipe path.
        // We now batch refreshes to every N swipes or every ~45s, whichever
        // comes first, so the swipe pipeline stays purely local.
        const priorVisibleMs = Math.max(0, Date.now() - visibleAt.current);
        visibleDurations.current.set(String(top.id), priorVisibleMs);
        afterSuccessfulMutation(() => apiPost("/user/action", {
            movie_id: top.id,
            action,
            impression_id: top.impression_id,
            ...(watchedMeta || {}),
        }), () => {
            const event = action === "save" ? EVENTS.RECOMMENDATION_SAVED
                : action === "watched" ? EVENTS.RECOMMENDATION_WATCHED : EVENTS.RECOMMENDATION_SKIPPED;
            capture(event, {
                content_id: top.id,
                media_type: top.type || "movie",
                genres: Array.isArray(top.genres) ? top.genres.slice(0, 20) : undefined,
                provider: top.provider_id || top.provider || undefined,
                feed_type: tab,
                recommendation_source: top?._signals?.source || undefined,
                time_visible_ms: priorVisibleMs,
                interaction_bucket: interactionBucket(interactionCountRef.current),
            }, { user, dedupeKey: `discover:${top.id}:${action}:${top.impression_id || ""}` });
            interactionCountRef.current += 1;
            markFirstDiscoverAction(user);
            // Saved titles are signalled via the Watchlist tab badge (no toast).
            if (action === "save") {
                setUser?.((u) => (u ? { ...u, watchlist_unseen: (Number(u.watchlist_unseen) || 0) + 1 } : u));
            } else if (action === "watched") {
                toast(watchedMeta?.completed === false ? "Saved as not finished" : "Reaction saved", { icon: "✓" });
            }
        }).catch(() => {}).finally(() => {
            swipesSinceRefresh.current += 1;
            const dueByCount = swipesSinceRefresh.current >= USER_REFRESH_EVERY_N_SWIPES;
            const dueByTime  = Date.now() - lastUserRefresh.current >= USER_REFRESH_INTERVAL_MS;
            if (dueByCount || dueByTime) {
                swipesSinceRefresh.current = 0;
                lastUserRefresh.current = Date.now();
                refresh();
            }
        });
        setTimeout(() => {
            const _renderT0 = performance.now();
            setStack((s) => {
                const next = s.slice(1);
                // Push the dismissed card + the action taken so Rewind can
                // both restore the card AND reverse the backend action.
                setHistory((h) => [...h, { card: top, action }].slice(-20));
                try {
                    sessionStorage.setItem(STACK_CACHE_KEY, JSON.stringify({
                        tab, stack: next, services,
                        includeOtherServices, includeRentBuy,
                        subBannerDismissed, ts: Date.now(),
                    }));
                } catch {}
                return next;
            });
            setExiting(null);
            // Schedule the render-time measurement after React commits the
            // new top card (rAF fires after layout/paint).
            if (typeof window !== "undefined" && window.requestAnimationFrame) {
                requestAnimationFrame(() => {
                    const renderMs = Math.round(performance.now() - _renderT0);
                    setPerf(p => ({
                        ...p,
                        lastSwipeMs: Math.round(performance.now() - _swipeT0),
                        renderMs,
                    }));
                });
            } else {
                setPerf(p => ({ ...p, lastSwipeMs: Math.round(performance.now() - _swipeT0) }));
            }
        }, 220);
    };

    // Rewind — one-step reverse of the last skip / save / watched. Restores the
    // card to the top of the stack AND reverses the backend action so the title
    // is no longer left in saved/skipped/watched.
    const REVERSE_ACTION = { save: "unsave", skip: "unskip", watched: "unwatched" };
    const handleRewind = () => {
        if (history.length === 0) return;
        const last = history[history.length - 1];
        // Backward-compat: older history entries were the raw card object.
        const card = last?.card || last;
        const action = last?.action;
        if (!card) return;
        setEntering({ id: card.id, dir: "left" });
        setHistory((h) => h.slice(0, -1));
        setStack((s) => {
            const next = [card, ...s];
            try {
                sessionStorage.setItem(STACK_CACHE_KEY, JSON.stringify({
                    tab, stack: next, services,
                    includeOtherServices, includeRentBuy,
                    subBannerDismissed, ts: Date.now(),
                }));
            } catch {}
            return next;
        });
        const reverse = REVERSE_ACTION[action];
        if (reverse) {
            if (reverse === "unsave") {
                // Keep the Watchlist badge in sync with the reversed save.
                setUser?.((u) => (u ? { ...u, watchlist_unseen: Math.max(0, (Number(u.watchlist_unseen) || 0) - 1) } : u));
            }
            afterSuccessfulMutation(
                () => apiPost("/user/action", { movie_id: card.id, action: reverse, impression_id: card.impression_id }),
                () => {
                    capture(EVENTS.RECOMMENDATION_REWOUND, {
                        content_id: card.id,
                        media_type: card.type || "movie",
                        genres: Array.isArray(card.genres) ? card.genres.slice(0, 20) : undefined,
                        provider: card.provider_id || card.provider || undefined,
                        feed_type: tab,
                        time_visible_ms: visibleDurations.current.get(String(card.id)),
                        interaction_bucket: interactionBucket(interactionCountRef.current),
                    }, { user, dedupeKey: `reverse:${card.id}:${action}:${card.impression_id || ""}` });
                    toast("Rewound", { icon: "↩" });
                }
            )
                .catch(() => {})
                .finally(() => refresh());
        }
        setTimeout(() => setEntering(null), 220);
    };

    const servicesById = useMemo(() => Object.fromEntries(services.map((s) => [s.id, s])), [services]);
    return (
        <div className="flex flex-col overflow-hidden px-3 max-w-md sm:max-w-lg mx-auto" data-testid="discover-page" style={{ height: "100dvh", paddingTop: "max(0.5rem, env(safe-area-inset-top))" }}>
            <header className="flex items-center justify-between px-1 mb-2 shrink-0">
                <h1 className="font-display text-2xl font-bold tracking-tight text-white">Discover</h1>
                <div className="flex items-center gap-2 shrink-0">
                    <button
                        onClick={() => navigate("/search")}
                        data-testid="open-search"
                        aria-label="Search"
                        className="h-11 w-11 -m-1.5 grid place-items-center focus-visible:ring-2 focus-visible:ring-amber/70 rounded-full outline-none"
                    >
                        <span className="h-8 w-8 rounded-full border border-white/10 bg-white/[0.03] grid place-items-center text-zinc-300 hover:text-amber hover:border-amber/40 transition-colors">
                            <Search className="w-4 h-4" strokeWidth={1.8} />
                        </span>
                    </button>
                    <button
                        onClick={() => setFiltersOpen(true)}
                        data-testid="open-filters"
                        aria-label="Filters"
                        className="h-11 w-11 -m-1.5 grid place-items-center focus-visible:ring-2 focus-visible:ring-amber/70 rounded-full outline-none"
                    >
                        <span className="h-8 w-8 rounded-full border border-white/10 bg-white/[0.03] grid place-items-center text-zinc-300 hover:text-amber hover:border-amber/40 transition-colors">
                            <SlidersHorizontal className="w-4 h-4" strokeWidth={1.8} />
                        </span>
                    </button>
                </div>
            </header>

            {/* Tab rail */}
            <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar px-1 mb-2 shrink-0" data-testid="tabs">
                {TABS.map((t) => {
                    const active = tab === t.id;
                    return (
                        <button
                            key={t.id}
                            onClick={() => {
                                setTab(t.id);
                                capture(EVENTS.FILTER_CHANGED, {
                                    filter_name: "discover_tab",
                                    selected: true,
                                    selected_count: 1,
                                    source: "discover",
                                }, { user });
                            }}
                            data-testid={`tab-${t.id}`}
                            aria-pressed={active}
                            className={`px-3 py-1 min-h-[30px] rounded-full text-xs whitespace-nowrap transition-colors border outline-none focus-visible:ring-2 focus-visible:ring-amber/70 ${
                                active
                                    ? "bg-amber border-amber/40 text-obsidian font-heading"
                                    : "border-white/[0.06] bg-white/[0.03] text-zinc-400 hover:bg-white/[0.05] hover:border-white/10 hover:text-zinc-200"
                            }`}
                        >
                            {t.label}
                        </button>
                    );
                })}
            </div>

            <Tutorial open={tutorial} onClose={() => setTutorial(false)} />
            <FiltersSheet
                open={filtersOpen}
                onClose={() => setFiltersOpen(false)}
                onSaved={() => { setFiltersOpen(false); refresh(); loadStack(tab, true); }}
            />
            <WatchedFeedbackDialog
                open={!!watchedPrompt}
                title={watchedPrompt?.title}
                onCancel={() => setWatchedPrompt(null)}
                onSelect={(meta) => {
                    const dir = watchedPrompt?.dir || "up";
                    setWatchedPrompt(null);
                    handleAction("watched", dir, meta);
                }}
            />

            {/* Opt-in bypass active banner */}
            {PERSONAL_TABS.includes(tab) && !loading && feedMeta?.provider_bypass_triggered && (
                <div className="mb-3 flex items-center gap-2 rounded-xl bg-white/5 border border-white/10 px-3 py-2.5">
                    <p className="text-xs text-zinc-400 flex-1">
                        {includeOtherServices && "Showing titles from all streaming services."}
                        {includeRentBuy && " Including rent & buy titles."}
                        {" "}
                        <button
                            onClick={() => { setIncludeOtherServices(false); setIncludeRentBuy(false); setSubBannerDismissed(false); }}
                            className="underline text-zinc-300 hover:text-white"
                        >
                            Back to strict mode
                        </button>
                    </p>
                </div>
            )}
            {/* Thin-pool / exhausted pool banner — shown in strict mode only */}
            {PERSONAL_TABS.includes(tab) && !loading && !feedMeta?.provider_bypass_triggered &&
             feedMeta?.empty_state_reason && feedMeta.empty_state_reason !== "cooldown_exhausted" && !subBannerDismissed && (
                <div className="mb-3 flex items-start gap-2 rounded-xl bg-amber/8 border border-amber/20 px-3 py-2.5">
                    <span className="text-amber mt-0.5 shrink-0 text-xs">!</span>
                    <p className="text-xs text-zinc-300 leading-snug flex-1">
                        {feedMeta.empty_state_reason === "subscription_exhausted"
                            ? `You've seen all ${feedMeta.selected_genres?.join(" & ") || "titles"} on your subscriptions.`
                            : `Limited ${feedMeta.selected_genres?.join(" & ") || "titles"} on your subscriptions (${feedMeta.provider_match_count ?? "?"} available).`
                        }
                        {feedMeta.fallback_reason === "adjacent_same_subs" && " Showing related titles from the same services."}
                    </p>
                    <button
                        onClick={() => setSubBannerDismissed(true)}
                        aria-label="Dismiss"
                        className="text-zinc-500 hover:text-zinc-300 shrink-0 mt-0.5"
                    >
                        <X className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}

            <div ref={cardViewportRef} className="relative flex-1 min-h-0">
                {loading ? (
                    <CardSkeleton />
                ) : stack.length === 0 ? (
                    <EmptyState
                        onReload={() => loadStack(tab, true)}
                        feedMeta={feedMeta}
                        onOpenFilters={() => setFiltersOpen(true)}
                        onIncludeOtherServices={() => { setIncludeOtherServices(true); setSubBannerDismissed(false); }}
                        onIncludeRentBuy={() => { setIncludeRentBuy(true); setSubBannerDismissed(false); }}
                        includeOtherServices={includeOtherServices}
                        includeRentBuy={includeRentBuy}
                    />
                ) : (
                    <AnimatePresence>
                        {/* Render the next two cards BEHIND the top card (in reverse
                            so the top is on top in the DOM). They are non-interactive
                            placeholders whose <img> elements are already mounted and
                            decoded — when the top card animates out, the next one is
                            instantly visible with no blank gap. */}
                        {stack.slice(0, 3).slice().reverse().map((m, idx, arr) => {
                            const stackPos = arr.length - 1 - idx; // 2,1,0
                            const isTopCard = stackPos === 0;
                            return (
                                <Card
                                    key={m.id}
                                    movie={m}
                                    services={servicesById}
                                    isTop={isTopCard}
                                    stackPos={stackPos}
                                    isExiting={isTopCard && exiting?.id === m.id}
                                    isEntering={isTopCard && entering?.id === m.id}
                                    enterDir={entering?.dir}
                                    exitDir={exiting?.dir}
                                    userSubs={userSubs}
                                    onSwipe={(dir) => {
                                        if (dir === "up") setWatchedPrompt({ title: top.title, dir });
                                        else handleAction(dir === "right" ? "save" : "skip", dir);
                                    }}
                                    onTap={() => navigate(`/movie/${top.id}`, { state: { impression_id: top.impression_id } })}
                                />
                            );
                        })}
                    </AnimatePresence>
                )}
            </div>

            {/* Action row — its own layer below the card, above the bottom nav */}
            <div
                className="shrink-0 flex items-start justify-center gap-5 sm:gap-7 px-4 pt-3.5"
                style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 4.25rem)" }}
                data-testid="action-buttons"
            >
                <ActionBtn icon={RotateCcw} label="Rewind" onClick={handleRewind} disabled={history.length === 0} ring="border-white/25" color="text-zinc-200" bg="bg-[#141B26]" testId="btn-rewind" small />
                <ActionBtn icon={X} label="Skip" onClick={() => handleAction("skip", "left")} ring="border-white/15" color="text-zinc-200" bg="bg-[#1A2230]" testId="btn-skip" />
                <ActionBtn icon={Eye} label="Watched" onClick={() => top && setWatchedPrompt({ title: top.title, dir: "up" })} ring="border-emerald-500/50" color="text-emerald-400" bg="bg-[#0E141C]" testId="btn-watched" />
                <ActionBtn icon={Heart} label="Save" onClick={() => handleAction("save", "right")} ring="border-amber/50" color="text-amber" bg="bg-[#0E141C]" testId="btn-save" />
            </div>

            {SHOW_DEBUG && (
                <div className="fixed top-2 left-2 z-50 text-[10px] font-mono leading-tight bg-black/80 text-amber p-2 rounded-md border border-amber/40 pointer-events-none">
                    <div>stack: {stack.length}</div>
                    <div>queue_size (feed): {feedMeta?.queue_size ?? "—"}</div>
                    <div>refill_thresh: {REFILL_THRESHOLD}</div>
                    <div>refill_in_progress: {refilling ? "yes" : "no"}</div>
                    <div>refill_returned: {perf.refillReturned}</div>
                    <div>refill_rejected: {perf.refillRejected}</div>
                    <div>preloaded_imgs: {perf.preloaded}</div>
                    <div>api_ms: {perf.apiMs}</div>
                    <div>render_ms: {perf.renderMs}</div>
                    <div>swipe→render_ms: {perf.lastSwipeMs}</div>
                    <div>fail_count: {refillFailures.current}</div>
                </div>
            )}

        </div>
    );
}

function Card({ movie, services, isTop, stackPos, isExiting, isEntering, enterDir, exitDir, onSwipe, onTap, userSubs }) {
    const x = useMotionValue(0);
    const y = useMotionValue(0);
    const rotate = useTransform(x, [-200, 0, 200], [-12, 0, 12]);
    const likeOp = useTransform(x, [40, 140], [0, 1]);
    const nopeOp = useTransform(x, [-140, -40], [1, 0]);
    const watchedOp = useTransform(y, [-140, -40], [1, 0]);
    const dragOccurred = useRef(false);

    const offset = stackPos * 8;
    const scale = 1 - stackPos * 0.05;

    return (
        <motion.div
            className="absolute inset-0 rounded-3xl overflow-hidden card-shadow"
            data-testid={isTop ? "discover-card-top" : `discover-card-${stackPos}`}
            style={isTop ? { x, y, rotate, zIndex: 10 } : { y: offset, scale, zIndex: 10 - stackPos, opacity: 1 - stackPos * 0.22 }}
            drag={isTop ? true : false}
            dragConstraints={{ left: 0, right: 0, top: 0, bottom: 0 }}
            dragElastic={0.55}
            onDragEnd={(_, info) => {
                const { x: dx, y: dy } = info.offset;
                if (Math.abs(dx) > 8 || Math.abs(dy) > 8) {
                    dragOccurred.current = true;
                }
                if (Math.abs(dy) > Math.abs(dx) && dy < -110) onSwipe("up");
                else if (dx > 110) onSwipe("right");
                else if (dx < -110) onSwipe("left");
            }}
            onClick={isTop ? (e) => {
                if (dragOccurred.current) { dragOccurred.current = false; return; }
                onTap();
            } : undefined}
            initial={isEntering ? { x: -600, opacity: 0, rotate: -20 } : false}
            animate={
                isExiting
                    ? {
                          x: exitDir === "right" ? 600 : exitDir === "left" ? -600 : 0,
                          y: exitDir === "up" ? -600 : exitDir === "down" ? 600 : 0,
                          opacity: 0,
                          rotate: exitDir === "right" ? 20 : exitDir === "left" ? -20 : 0,
                      }
                    : isEntering
                    ? { x: 0, y: 0, opacity: 1, rotate: 0 }
                    : {}
            }
            transition={{ type: "spring", stiffness: 260, damping: 28 }}
        >

            {movie.backdrop_url || movie.poster_url ? (
                <img
                    loading="eager"
                    decoding="async"
                    src={movie.backdrop_url || movie.poster_url}
                    alt={movie.title}
                    className="absolute inset-0 w-full h-full object-cover"
                    draggable={false}
                />
            ) : (
                <div className="absolute inset-0 bg-gradient-to-br from-zinc-900 to-black grid place-items-center text-zinc-500 text-sm px-6 text-center">
                    No artwork available
                </div>
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/70 to-obsidian/10" />
            {isTop && (
                <>
                    <motion.div style={{ opacity: likeOp }} className="absolute top-8 right-6 px-4 py-2 border-2 border-amber text-amber font-heading text-2xl rotate-12 rounded-lg">SAVE</motion.div>
                    <motion.div style={{ opacity: nopeOp }} className="absolute top-8 left-6 px-4 py-2 border-2 border-zinc-300 text-zinc-300 font-heading text-2xl -rotate-12 rounded-lg">SKIP</motion.div>
                    <motion.div style={{ opacity: watchedOp }} className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 px-4 py-2 border-2 border-emerald-400 text-emerald-400 font-heading text-2xl rounded-lg">WATCHED</motion.div>
                </>
            )}

            {/* Match badge — top-left, mirrors the brand design */}
            {typeof movie.match === "number" && (
                <div className="absolute top-4 left-4 z-20 flex items-center gap-1.5 rounded-full bg-black/55 backdrop-blur px-2.5 py-1 border border-emerald-500/30">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    <span className="text-[12px] font-heading text-emerald-400 leading-none">{movie.match}% Match</span>
                </div>
            )}

            {/* Info button — always visible on top-right of card */}
            <button
                onClick={(e) => { e.stopPropagation(); onTap(); }}
                className="absolute top-4 right-4 z-20 h-10 w-10 rounded-full glass grid place-items-center hover:bg-white/[0.08] transition-colors active:scale-95"
                aria-label="View details"
            >
                <Info className="w-4 h-4 text-zinc-200" strokeWidth={2} />
            </button>

            <div className="absolute bottom-0 inset-x-0 p-5">
                {(movie._signals?.why_shown || movie.reason) && (
                    <p className="flex items-center gap-1.5 text-[10px] font-medium text-amber/80 mb-1.5">
                        <Sparkles className="w-3 h-3 shrink-0" strokeWidth={2} />
                        <span className="line-clamp-1">{movie._signals?.why_shown || movie.reason}</span>
                    </p>
                )}
                <h2 className="font-display text-2xl sm:text-3xl font-bold leading-tight mb-1.5 line-clamp-2">{movie.title}</h2>
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-zinc-300 mb-1.5">
                    <span className="flex items-center gap-1"><Star className="w-3.5 h-3.5 fill-amber text-amber" />{movie.rating?.toFixed(1)}</span>
                    <span className="text-zinc-600">•</span><span>{movie.year}</span>
                    <span className="text-zinc-600">•</span>
                    <span className="capitalize">{movie.type === "tv" ? `${movie.seasons?.length || 1} season${(movie.seasons?.length || 1) > 1 ? "s" : ""}` : (formatRuntime(movie.runtime) || "—")}</span>
                    {(movie.genres || []).slice(0, 2).map((g) => (
                        <span key={g} className="text-[10px] uppercase tracking-wider bg-white/10 backdrop-blur px-2 py-0.5 rounded-full text-zinc-300">{g}</span>
                    ))}
                </div>
                {Array.isArray(movie.cast_names) && movie.cast_names.length > 0 && (
                    <p className="text-[12px] text-zinc-300 line-clamp-1 mb-1.5" data-testid="discover-lead-cast">
                        <span className="text-zinc-500">Starring </span>
                        {movie.cast_names.slice(0, 3).join(", ")}
                    </p>
                )}
                <p className="text-[13px] text-zinc-400 line-clamp-2 mb-3">{movie.overview}</p>
                {/* Provider strip — "Included with X" when on a user sub, else logo row */}
                {(movie.available_on || []).length > 0 && (() => {
                    const subs = userSubs || [];
                    const onSub = (movie.available_on || []).filter((sid) => subs.includes(sid));
                    if (onSub.length > 0) {
                        const first = onSub[0];
                        const name = services?.[first]?.name || first;
                        return (
                            <div className="flex items-center gap-1.5" data-testid="provider-included-badge">
                                <span className="flex items-center gap-2 rounded-full bg-black/50 backdrop-blur border border-emerald-500/25 pl-1 pr-3 py-1">
                                    <ProviderLogo sid={first} size={22} shape="rounded-full" subscribed />
                                    <span className="text-xs font-medium text-emerald-300 leading-none">
                                        Included with {name}{onSub.length > 1 ? ` +${onSub.length - 1}` : ""}
                                    </span>
                                </span>
                            </div>
                        );
                    }
                    const sorted = movie.available_on || [];
                    const visible = sorted.slice(0, 3);
                    const overflow = sorted.length - visible.length;
                    return (
                        <div className="flex items-center gap-1.5">
                            {visible.map((sid) => (
                                <ProviderLogo key={sid} sid={sid} size={28} shape="rounded-lg" subscribed={false} />
                            ))}
                            {overflow > 0 && (
                                <span className="text-xs text-zinc-300 bg-white/10 backdrop-blur rounded-lg px-2 py-1 leading-none">
                                    +{overflow}
                                </span>
                            )}
                        </div>
                    );
                })()}
            </div>
        </motion.div>
    );
}

function ActionBtn({ icon: Icon, label, onClick, ring, color, bg, glow, testId, disabled, small }) {
    const size = small ? "h-11 w-11" : "h-14 w-14";
    const icon = small ? "h-5 w-5" : "h-6 w-6";
    return (
        <div className={`flex flex-col items-center gap-1.5 ${disabled ? "opacity-40" : ""}`}>
            <button
                onClick={onClick}
                disabled={disabled}
                data-testid={testId}
                aria-label={label}
                className={`relative ${size} rounded-full border-2 ${ring} ${color} ${bg || "bg-velvet/80"} shadow-lg shadow-black/50 backdrop-blur grid place-items-center hover:scale-105 active:scale-95 transition-transform disabled:cursor-not-allowed disabled:hover:scale-100`}
            >
                <Icon className={icon} strokeWidth={1.8} />
            </button>
            <span className={`text-[10px] uppercase tracking-wider ${color}`}>{label}</span>
        </div>
    );
}

function CardSkeleton() {
    return (
        <div className="absolute inset-0 rounded-3xl overflow-hidden bg-velvet animate-pulse">
            <div className="absolute inset-0 bg-gradient-to-t from-zinc-900/80 to-transparent" />
            <div className="absolute bottom-0 inset-x-0 p-6 space-y-3">
                <div className="flex gap-1.5">
                    <div className="h-5 w-14 rounded-full bg-white/10" />
                    <div className="h-5 w-20 rounded-full bg-white/10" />
                </div>
                <div className="h-8 w-4/5 rounded-lg bg-white/15" />
                <div className="h-4 w-1/2 rounded-lg bg-white/10" />
                <div className="h-3 w-full rounded-lg bg-white/8" />
                <div className="h-3 w-3/4 rounded-lg bg-white/8" />
            </div>
        </div>
    );
}

function EmptyState({ onReload, feedMeta, onOpenFilters, onIncludeOtherServices, onIncludeRentBuy, includeOtherServices, includeRentBuy }) {
    const reason = feedMeta?.empty_state_reason;
    const isSubLimited = reason === "subscription_exhausted" || reason === "subscription_limited" || reason === "thin_pool";
    const genres = feedMeta?.selected_genres?.join(" & ");

    return (
        <div className="h-full grid place-items-center">
            <div className="text-center max-w-xs px-4">
                <div className="w-16 h-16 rounded-2xl bg-amber/15 grid place-items-center mx-auto mb-4 border border-amber/20">
                    <Sparkles className="w-7 h-7 text-amber" strokeWidth={1.6} />
                </div>
                <h3 className="font-heading text-xl mb-2">
                    {reason === "subscription_exhausted" ? "End of your list" : "You're all caught up"}
                </h3>
                {isSubLimited ? (
                    <>
                        <p className="text-sm text-zinc-400 mb-4 leading-relaxed">
                            {reason === "subscription_exhausted"
                                ? <>You've seen all {genres ? <strong className="text-zinc-200">{genres}</strong> : "titles"} on your subscriptions.</>
                                : <>Very few {genres ? <strong className="text-zinc-200">{genres}</strong> : "titles"} on your subscriptions.</>
                            }
                        </p>
                        <div className="flex flex-col gap-2 mb-5">
                            <button
                                onClick={onIncludeOtherServices}
                                disabled={includeOtherServices}
                                className={`px-4 py-2.5 rounded-xl text-sm font-heading border transition-colors ${
                                    includeOtherServices
                                        ? "bg-amber/20 border-amber/30 text-amber/60 cursor-default"
                                        : "border-white/15 text-zinc-200 hover:bg-white/5"
                                }`}
                            >
                                {includeOtherServices ? "✓ Other services included" : "+ Include other services"}
                            </button>
                            <button
                                onClick={onIncludeRentBuy}
                                disabled={includeRentBuy}
                                className={`px-4 py-2.5 rounded-xl text-sm font-heading border transition-colors ${
                                    includeRentBuy
                                        ? "bg-amber/20 border-amber/30 text-amber/60 cursor-default"
                                        : "border-white/15 text-zinc-200 hover:bg-white/5"
                                }`}
                            >
                                {includeRentBuy ? "✓ Rent & buy included" : "+ Include rent & buy"}
                            </button>
                            <button
                                onClick={onOpenFilters}
                                className="px-4 py-2.5 rounded-xl text-sm font-heading border border-white/15 text-zinc-200 hover:bg-white/5 transition-colors"
                            >
                                Broaden genres
                            </button>
                        </div>
                    </>
                ) : (
                    <p className="text-sm text-zinc-400 mb-6 leading-relaxed">
                        You've seen everything in this tab. Try a different one or adjust your filters.
                    </p>
                )}
                <button
                    onClick={onReload}
                    className="px-6 py-3 rounded-2xl bg-amber text-obsidian font-heading hover:bg-amber-600 transition-colors amber-glow"
                >
                    Refresh picks
                </button>
            </div>
        </div>
    );
}
