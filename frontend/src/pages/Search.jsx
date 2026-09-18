import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Search as SearchIcon, ArrowLeft, Sparkles, Star, X, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { apiGet, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { ProviderLogo } from "@/components/ProviderLogo";
import { capture, EVENTS } from "@/lib/analytics";

const PAGE_SIZE = 20;
const MAX_QUERY_LEN = 200;
const SHOW_DEBUG = typeof window !== "undefined" && /[?&]debug=1/.test(window.location.search);

const LABELS = {
    included:    { text: "Included with your subscriptions", cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
    elsewhere:   { text: "Available elsewhere",              cls: "text-sky-300 bg-sky-500/10 border-sky-500/20" },
    rent_or_buy: { text: "Rent or buy",                      cls: "text-amber bg-amber/10 border-amber/30" },
    unavailable: { text: "Unavailable",                      cls: "text-zinc-400 bg-white/5 border-white/10" },
};

export default function Search() {
    const navigate = useNavigate();
    const { user } = useAuth();
    const userSubs = user?.subscriptions || [];

    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [fallback, setFallback] = useState(false);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [errored, setErrored] = useState(false);
    const [offset, setOffset] = useState(0);
    const [total, setTotal] = useState(0);
    const [debug, setDebug] = useState(null);

    // Optional filter chips. None of these hide results by default —
    // they only narrow the catalogue once the user opts in.
    const [onlyMySubs, setOnlyMySubs]       = useState(false);
    const [hideUnavailable, setHideUnav]    = useState(false);
    const [typeFilter, setTypeFilter]       = useState(null);   // "movie" | "tv" | null
    const [genreFilter, setGenreFilter]     = useState("");
    const [yearFilter, setYearFilter]       = useState("");
    const [providerFilter, setProviderFilter] = useState("");
    const [showMoreFilters, setShowMoreFilters] = useState(false);

    // Genre & service options for the filter dropdowns — fetched once.
    const [genreOptions, setGenreOptions]   = useState([]);
    const [serviceOptions, setServiceOptions] = useState([]);
    useEffect(() => {
        Promise.all([apiGet("/genres"), apiGet("/services")])
            .then(([g, s]) => {
                setGenreOptions(Array.isArray(g) ? g : []);
                setServiceOptions(Array.isArray(s) ? s : []);
            })
            .catch(() => {});
    }, []);

    const buildQuery = useCallback((off) => {
        const p = new URLSearchParams();
        p.set("q", q.trim().slice(0, MAX_QUERY_LEN));
        p.set("limit", String(PAGE_SIZE));
        p.set("offset", String(off));
        if (onlyMySubs)      p.set("only_my_subscriptions", "true");
        if (hideUnavailable) p.set("hide_unavailable", "true");
        if (typeFilter)      p.set("content_type", typeFilter);
        if (genreFilter)     p.set("genre", genreFilter);
        if (yearFilter)      p.set("year", yearFilter);
        if (providerFilter)  p.set("provider", providerFilter);
        if (SHOW_DEBUG)      p.set("debug", "true");
        return p.toString();
    }, [q, onlyMySubs, hideUnavailable, typeFilter, genreFilter, yearFilter, providerFilter]);

    const clearFilters = () => {
        setOnlyMySubs(false); setHideUnav(false); setTypeFilter(null);
        setGenreFilter(""); setYearFilter(""); setProviderFilter("");
    };
    const anyFilterActive = onlyMySubs || hideUnavailable || typeFilter || genreFilter || yearFilter || providerFilter;
    const inputRef = useRef(null);
    const debounce = useRef(null);
    const lastQ = useRef("");
    // AbortController for in-flight search — cancel stale requests so a slow
    // earlier response cannot overwrite the current results.
    const inFlight = useRef(null);
    // Generation token: only the latest search effect may write to results.
    const searchGen = useRef(0);

    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    // Esc clears the input; Enter forces an immediate search (skip debounce).
    const handleKeyDown = (e) => {
        if (e.key === "Escape") {
            e.preventDefault();
            setQ("");
            inputRef.current?.blur();
        }
    };

    useEffect(() => {
        if (debounce.current) clearTimeout(debounce.current);
        // Cancel any in-flight request as soon as the query changes.
        if (inFlight.current) {
            try { inFlight.current.abort(); } catch {}
            inFlight.current = null;
        }
        const trimmed = q.trim();
        if (!trimmed) {
            setResults([]);
            setFallback(false);
            setHasMore(false);
            setOffset(0);
            setErrored(false);
            return;
        }
        debounce.current = setTimeout(async () => {
            const myGen = ++searchGen.current;
            const controller = new AbortController();
            inFlight.current = controller;
            setLoading(true);
            setErrored(false);
            setOffset(0);
            lastQ.current = trimmed;
            try {
                const r = await apiGet(
                    `/search?${buildQuery(0)}`,
                    { signal: controller.signal }
                );
                if (myGen !== searchGen.current) return; // stale — ignore
                setResults(r.results || []);
                setFallback(Boolean(r.fallback));
                setHasMore(Boolean(r.has_more));
                setOffset(PAGE_SIZE);
                setTotal(Number.isFinite(r.total) ? r.total : (r.results?.length || 0));
                const searchProps = {
                    query_length: trimmed.length,
                    result_count: (r.results || []).length,
                    has_results: (r.results || []).length > 0,
                    fallback: Boolean(r.fallback),
                    filter_count: [onlyMySubs, hideUnavailable, typeFilter, genreFilter, yearFilter, providerFilter].filter(Boolean).length,
                };
                capture(EVENTS.SEARCH_PERFORMED, searchProps, { user, dedupeKey: `search:${trimmed.length}:${JSON.stringify(buildQuery(0))}` });
                if (!(r.results || []).length) capture(EVENTS.SEARCH_NO_RESULTS, searchProps, { user, dedupeKey: `search-empty:${trimmed.length}:${JSON.stringify(buildQuery(0))}` });
                if (SHOW_DEBUG) setDebug(r.debug || null);
            } catch (err) {
                if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") return;
                if (myGen !== searchGen.current) return;
                setResults([]);
                setHasMore(false);
                setErrored(true);
                toast.error(err?.friendlyMessage || formatApiError(err?.response?.data?.detail));
            } finally {
                if (myGen === searchGen.current) setLoading(false);
                if (inFlight.current === controller) inFlight.current = null;
            }
        }, 350);
        return () => clearTimeout(debounce.current);
    }, [q, buildQuery]);

    const loadMore = useCallback(async () => {
        if (loadingMore || !hasMore) return;
        // Capture the generation at start; if the user changes the query while
        // this paginated request is in flight, discard the response so older
        // pages cannot append into the new query's results.
        const myGen = searchGen.current;
        const controller = new AbortController();
        // Replace any prior in-flight request — only one search call at a time.
        if (inFlight.current) { try { inFlight.current.abort(); } catch {} }
        inFlight.current = controller;
        setLoadingMore(true);
        try {
            const r = await apiGet(
                `/search?${buildQuery(offset)}`,
                { signal: controller.signal }
            );
            if (myGen !== searchGen.current) return;
            const newItems = r.results || [];
            setResults(prev => {
                const existingIds = new Set(prev.map(m => m.id));
                return [...prev, ...newItems.filter(m => !existingIds.has(m.id))];
            });
            setHasMore(Boolean(r.has_more));
            setOffset(prev => prev + PAGE_SIZE);
            if (Number.isFinite(r.total)) setTotal(r.total);
        } catch (err) {
            if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") return;
            if (myGen !== searchGen.current) return;
            toast.error(err?.friendlyMessage || formatApiError(err?.response?.data?.detail));
        } finally {
            if (myGen === searchGen.current) setLoadingMore(false);
            if (inFlight.current === controller) inFlight.current = null;
        }
    }, [loadingMore, hasMore, offset, buildQuery]);

    return (
        <div className="min-h-screen pb-28 max-w-md mx-auto" data-testid="search-page">
            <div className="sticky top-0 z-10 glass-strong px-4 py-3 flex items-center gap-3" style={{ paddingTop: "max(0.75rem, env(safe-area-inset-top))" }}>
                <button
                    onClick={() => navigate(-1)}
                    className="h-10 w-10 grid place-items-center rounded-full hover:bg-white/5"
                    data-testid="search-back"
                    aria-label="back"
                >
                    <ArrowLeft className="h-5 w-5" />
                </button>
                <div className="flex-1 relative">
                    <SearchIcon className="h-4 w-4 text-zinc-500 absolute left-4 top-1/2 -translate-y-1/2" />
                    <label htmlFor="search-input" className="sr-only">Search titles, actors, or genres</label>
                    <input
                        id="search-input"
                        ref={inputRef}
                        value={q}
                        onChange={(e) => setQ(e.target.value.slice(0, MAX_QUERY_LEN))}
                        onKeyDown={handleKeyDown}
                        maxLength={MAX_QUERY_LEN}
                        placeholder="Title, actor, or genre…"
                        data-testid="search-input"
                        aria-label="Search titles, actors, or genres"
                        type="search"
                        autoComplete="off"
                        className="w-full bg-white/5 border border-white/10 rounded-full pl-11 pr-10 py-3 text-sm focus:border-amber/60 outline-none"
                        enterKeyHint="search"
                    />
                    {q && (
                        <button
                            onClick={() => setQ("")}
                            className="absolute right-3 top-1/2 -translate-y-1/2 h-6 w-6 grid place-items-center rounded-full hover:bg-white/10 text-zinc-400 transition-colors"
                            aria-label="clear search"
                            data-testid="search-clear"
                        >
                            <X className="w-3.5 h-3.5" />
                        </button>
                    )}
                </div>
            </div>

            {/* ── Filter chips ─────────────────────────────────────────── */}
            {q.trim() && (
                <div className="px-4 pt-3 pb-1" data-testid="search-filters">
                    <div className="flex flex-wrap gap-1.5 items-center">
                        <FilterChip active={onlyMySubs}      onClick={() => setOnlyMySubs(v => !v)}        testId="filter-mysubs">My subscriptions</FilterChip>
                        <FilterChip active={hideUnavailable} onClick={() => setHideUnav(v => !v)}          testId="filter-hideunav">Hide unavailable</FilterChip>
                        <FilterChip active={typeFilter === "movie"} onClick={() => setTypeFilter(t => t === "movie" ? null : "movie")} testId="filter-movies">Movies</FilterChip>
                        <FilterChip active={typeFilter === "tv"}    onClick={() => setTypeFilter(t => t === "tv" ? null : "tv")}       testId="filter-tv">TV</FilterChip>
                        <button
                            onClick={() => setShowMoreFilters(v => !v)}
                            className="text-[11px] px-3 py-1.5 rounded-full border border-white/10 bg-white/5 hover:bg-white/10 transition-colors flex items-center gap-1"
                            data-testid="filter-more-toggle"
                        >
                            More
                            <ChevronDown className={`w-3 h-3 transition-transform ${showMoreFilters ? "rotate-180" : ""}`} />
                        </button>
                        {anyFilterActive && (
                            <button
                                onClick={clearFilters}
                                className="text-[11px] px-3 py-1.5 rounded-full text-amber hover:bg-amber/10 transition-colors"
                                data-testid="filter-clear"
                            >
                                Clear
                            </button>
                        )}
                    </div>
                    {showMoreFilters && (
                        <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
                            <select
                                value={genreFilter}
                                onChange={(e) => setGenreFilter(e.target.value)}
                                className="bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 outline-none focus:border-amber/60"
                                data-testid="filter-genre"
                            >
                                <option value="">All genres</option>
                                {genreOptions.map(g => <option key={g} value={g}>{g}</option>)}
                            </select>
                            <input
                                type="number"
                                inputMode="numeric"
                                placeholder="Year"
                                min="1900"
                                max="2100"
                                value={yearFilter}
                                onChange={(e) => setYearFilter(e.target.value.slice(0, 4))}
                                className="bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 outline-none focus:border-amber/60"
                                data-testid="filter-year"
                            />
                            <select
                                value={providerFilter}
                                onChange={(e) => setProviderFilter(e.target.value)}
                                className="bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 outline-none focus:border-amber/60"
                                data-testid="filter-provider"
                            >
                                <option value="">All providers</option>
                                {serviceOptions.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                            </select>
                        </div>
                    )}
                </div>
            )}

            <div className="px-5 pt-4">
                {/* Result count — visible whenever a search returned results. */}
                {!loading && !errored && results.length > 0 && (
                    <div className="text-[11px] text-zinc-500 mb-3" data-testid="search-total">
                        {total > 0 ? (
                            <>
                                <span className="text-zinc-300">{total.toLocaleString()}</span>{" "}
                                result{total === 1 ? "" : "s"} for "{q.trim()}"
                            </>
                        ) : (
                            <>Showing {results.length} result{results.length === 1 ? "" : "s"}</>
                        )}
                    </div>
                )}
                {loading && (
                    <div className="space-y-3">
                        {[1, 2, 3].map(i => (
                            <div key={i} className="flex gap-3 glass rounded-2xl p-3 animate-pulse">
                                <div className="w-16 h-24 rounded-lg bg-white/8 shrink-0" />
                                <div className="flex-1 space-y-2 pt-1">
                                    <div className="h-4 w-3/4 rounded bg-white/10" />
                                    <div className="h-3 w-1/3 rounded bg-white/8" />
                                    <div className="h-3 w-full rounded bg-white/6" />
                                    <div className="h-3 w-2/3 rounded bg-white/6" />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
                {!loading && q && results.length === 0 && !errored && (
                    <div className="text-center py-12">
                        <div className="w-14 h-14 rounded-2xl bg-white/5 grid place-items-center mx-auto mb-4">
                            <SearchIcon className="w-6 h-6 text-zinc-600" strokeWidth={1.5} />
                        </div>
                        <p className="font-heading text-base mb-1">No results for "{q}"</p>
                        <p className="text-sm text-zinc-500">Try a different title, actor, or genre.</p>
                    </div>
                )}
                {!loading && errored && (
                    <div className="text-center py-12" data-testid="search-error">
                        <div className="w-14 h-14 rounded-2xl bg-red-500/10 grid place-items-center mx-auto mb-4">
                            <X className="w-6 h-6 text-red-400" strokeWidth={1.5} />
                        </div>
                        <p className="font-heading text-base mb-1">Search couldn't load</p>
                        <p className="text-sm text-zinc-500 mb-4">Check your connection and try again.</p>
                        <button
                            onClick={() => { const v = q; setQ(""); setTimeout(() => setQ(v), 0); }}
                            className="inline-flex items-center gap-2 glass rounded-2xl px-5 py-2.5 text-sm font-heading hover:bg-white/8"
                        >
                            Try again
                        </button>
                    </div>
                )}
                {fallback && results.length > 0 && (
                    <div className="glass rounded-2xl p-4 mb-4 flex items-start gap-3" data-testid="search-fallback">
                        <Sparkles className="w-4 h-4 text-amber shrink-0 mt-0.5" />
                        <p className="text-sm text-zinc-300">
                            We couldn't find an exact match. Here are similar titles you might love instead.
                        </p>
                    </div>
                )}

                <ul className="space-y-3">
                    {results.map((m, i) => {
                        const onSub = m.on_subscription;
                        const providers = m.available_on || [];
                        const sortedProviders = [
                            ...providers.filter(sid => userSubs.includes(sid)),
                            ...providers.filter(sid => !userSubs.includes(sid)),
                        ].slice(0, 4);
                        const runtime = (m.runtime && m.runtime > 0)
                            ? (() => {
                                const h = Math.floor(m.runtime / 60);
                                const mn = m.runtime % 60;
                                return h > 0 ? (mn > 0 ? `${h}h ${mn}m` : `${h}h`) : `${mn}m`;
                              })()
                            : null;
                        return (
                            <motion.li
                                key={m.id}
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: Math.min(i, 10) * 0.03 }}
                                data-testid={`search-result-${m.id}`}
                            >
                                <button
                                     onClick={() => {
                                         capture(EVENTS.SEARCH_RESULT_SELECTED, { selected_content_id: m.id, selected_position: i }, { user, dedupeKey: `search-result:${m.id}:${i}` });
                                         navigate(`/movie/${m.id}`);
                                     }}
                                    className="w-full flex gap-3 glass rounded-2xl p-3 hover:bg-white/[0.05] active:bg-white/[0.08] text-left transition-colors"
                                >
                                    <div className="w-16 h-24 rounded-lg overflow-hidden bg-velvet shrink-0">
                                        {m.poster_url && (
                                            <img
                                                loading="lazy"
                                                src={m.poster_url}
                                                alt={m.title}
                                                className="w-full h-full object-cover"
                                                style={{ opacity: 0, transition: "opacity 0.3s" }}
                                                onLoad={(e) => { e.target.style.opacity = 1; }}
                                                onError={(e) => { e.target.style.display = "none"; }}
                                            />
                                        )}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="font-heading text-base leading-tight truncate">{m.title}</div>
                                        <div className="flex items-center gap-2 text-xs text-zinc-400 mt-1">
                                            <Star className="w-3 h-3 fill-amber text-amber" />
                                            {m.rating?.toFixed(1)} · {m.year} · {m.type === "tv"
                                                ? `TV · ${m.seasons?.length || 1} season${(m.seasons?.length || 1) > 1 ? "s" : ""}`
                                                : runtime || "Movie"}
                                        </div>
                                        {/* Provider logos with subscribed highlighting */}
                                        {sortedProviders.length > 0 && (
                                            <div
                                                className="flex items-center gap-1.5 mt-1.5"
                                                data-testid={onSub ? `sub-badge-${m.id}` : `nosub-badge-${m.id}`}
                                            >
                                                {sortedProviders.map(sid => (
                                                    <ProviderLogo
                                                        key={sid}
                                                        sid={sid}
                                                        size={20}
                                                        shape="rounded-md"
                                                        subscribed={userSubs.includes(sid)}
                                                    />
                                                ))}
                                                {onSub && (
                                                    <span className="text-[10px] text-emerald-400">Included</span>
                                                )}
                                            </div>
                                        )}
                                        <div className="text-xs text-zinc-500 line-clamp-2 mt-1">{m.overview}</div>
                                        <div className="flex flex-wrap gap-1 mt-2">
                                            {(m.genres || []).slice(0, 3).map((g) => (
                                                <span key={g} className="text-[10px] uppercase tracking-wider bg-white/8 px-2 py-0.5 rounded-full">
                                                    {g}
                                                </span>
                                            ))}
                                        </div>
                                        {/* Availability label — every result is shown,
                                            labelled so the user instantly sees if it's
                                            on their subs vs rent-only vs unavailable. */}
                                        {m.availability_label && LABELS[m.availability_label] && (
                                            <div className={`mt-2 inline-flex text-[10px] px-2 py-0.5 rounded-full border ${LABELS[m.availability_label].cls}`}>
                                                {LABELS[m.availability_label].text}
                                            </div>
                                        )}
                                    </div>
                                </button>
                            </motion.li>
                        );
                    })}
                </ul>
                {SHOW_DEBUG && debug && (
                    <div className="mt-6 text-[10px] font-mono leading-tight bg-black/80 text-amber p-3 rounded-md border border-amber/40">
                        <div className="font-bold mb-1">SEARCH DEBUG</div>
                        <div>collection: {debug.collection}</div>
                        <div>total_matches: {debug.total_matches}</div>
                        <div>returned: {debug.returned}</div>
                        <div>offset: {debug.offset} / limit: {debug.limit}</div>
                        <div>query_types: {(debug.query_types_detected || []).join(", ")}</div>
                        <div>provider_matches: {(debug.provider_matches || []).join(", ") || "—"}</div>
                        <div>filters_applied: {(debug.filters_applied || []).join(", ")}</div>
                        <div>sub_filter_applied: {String(debug.subscription_filter_applied)}</div>
                        <div>tmdb_fallback: {String(debug.fallback_to_tmdb)}</div>
                        <div>db_query_ms: {debug.db_query_ms}</div>
                        <div>total_ms: {debug.total_ms}</div>
                    </div>
                )}

                {/* Load more button */}
                {!loading && hasMore && results.length > 0 && (
                    <div className="mt-5 text-center">
                        <button
                            onClick={loadMore}
                            disabled={loadingMore}
                            className="inline-flex items-center gap-2 glass rounded-2xl px-6 py-3 text-sm font-heading hover:bg-white/8 disabled:opacity-50 transition-colors"
                        >
                            {loadingMore ? (
                                <span className="animate-spin h-4 w-4 border-2 border-white/30 border-t-white rounded-full" />
                            ) : (
                                <ChevronDown className="w-4 h-4" />
                            )}
                            {loadingMore ? "Loading…" : "Load more"}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}

function FilterChip({ active, onClick, testId, children }) {
    return (
        <button
            onClick={onClick}
            data-testid={testId}
            aria-pressed={active}
            className={
                "text-[11px] px-3 py-1.5 rounded-full border transition-colors " +
                (active
                    ? "bg-amber/20 border-amber/50 text-amber"
                    : "bg-white/5 border-white/10 text-zinc-300 hover:bg-white/10")
            }
        >
            {children}
        </button>
    );
}
