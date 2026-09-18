import { useEffect, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Heart, Eye, Star, Sparkles, Play, ExternalLink, X, Tv2, Clock, Users } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { ProviderLogo, RentBuyLogo } from "@/components/ProviderLogo";
import WatchedFeedbackDialog from "@/components/WatchedFeedbackDialog";
import { formatRuntime, calcTvTotalMinutes } from "@/lib/format";
import { capture, EVENTS } from "@/lib/analytics";
export default function MovieDetail() {
    const { id } = useParams();
    const navigate = useNavigate();
    const { state } = useLocation();
    const { user, refresh } = useAuth();
    const impressionId = state?.impression_id || null;
    const [movie, setMovie] = useState(null);
    const [services, setServices] = useState([]);
    const [explanation, setExplanation] = useState("");
    const [explainLoading, setExplainLoading] = useState(false);
    const [trailerOpen, setTrailerOpen] = useState(false);
    const [reviews, setReviews] = useState({ summary: {}, user: [], tmdb: [] });
    const [similar, setSimilar] = useState([]);
    const [progressOpen, setProgressOpen] = useState(false);
    const [loadError, setLoadError] = useState(null);
    const [actionBusy, setActionBusy] = useState(false);
    const [feedbackOpen, setFeedbackOpen] = useState(false);
    const [reportOpen, setReportOpen] = useState(false);
    const [reportReason, setReportReason] = useState("wrong_provider");
    const [reportDetail, setReportDetail] = useState("");
    const [reportHp, setReportHp] = useState(""); // honeypot — must stay empty
    const [reportBusy, setReportBusy] = useState(false);
    const [refreshBusy, setRefreshBusy] = useState(false);

    const loadAll = (signal) => {
        setLoadError(null);
        (async () => {
            try {
                const m = await apiGet(`/movies/${id}`, { signal });
                if (signal?.aborted) return;
                setMovie(m);
                capture(EVENTS.TITLE_DETAILS_VIEWED, {
                    content_id: id,
                    media_type: m.type || "movie",
                    impression_id: impressionId || undefined,
                }, { user, dedupeKey: `detail:${id}:${impressionId || ""}` });
                apiPost("/user/engage", { movie_id: id, action: "detail_view", impression_id: impressionId }).catch(() => {});
            } catch (err) {
                if (signal?.aborted) return;
                setLoadError(err?.response?.status === 404 ? "We couldn't find that title." : "Couldn't load this title. Check your connection.");
            }
        })();
        apiGet("/services", { signal }).then((s) => { if (!signal?.aborted) setServices(s); }).catch(() => {});
        apiGet(`/movies/${id}/reviews`, { signal }).then((r) => { if (!signal?.aborted) setReviews(r); }).catch(() => {});
        apiGet(`/movies/${id}/similar`, { signal }).then((s) => { if (!signal?.aborted) setSimilar(s); }).catch(() => {});
    };

    useEffect(() => {
        // Reset state + scroll to top when navigating between titles
        setMovie(null);
        setExplanation("");
        setReviews({ summary: {}, user: [], tmdb: [] });
        setSimilar([]);
        window.scrollTo(0, 0);

        const ctrl = new AbortController();
        loadAll(ctrl.signal);
        return () => ctrl.abort();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    const isSaved = user?.saved?.includes(id);
    const isWatched = user?.watched?.includes(id);
    const isTv = movie?.type === "tv";
    const progress = movie?.progress;

    const act = async (action, watchedMeta = null) => {
        if (actionBusy) return;
        setActionBusy(true);
        try {
            await apiPost("/user/action", { movie_id: id, action, impression_id: impressionId, ...(watchedMeta || {}) });
            if (action === "save" || action === "unsave") {
                capture(action === "save" ? EVENTS.WATCHLIST_ITEM_ADDED : EVENTS.WATCHLIST_ITEM_REMOVED, {
                    content_id: id,
                    media_type: movie?.type || "movie",
                    source: "detail",
                }, { user, dedupeKey: `detail-action:${id}:${action}` });
            }
            await refresh();
            toast.success(action === "save" ? "Saved" : action === "watched" ? (watchedMeta?.completed === false ? "Saved as not finished" : "Reaction saved") : "Removed");
        } catch { toast.error("Couldn't update"); }
        finally { setActionBusy(false); }
    };

    const explain = async () => {
        setExplainLoading(true);
        try {
            const r = await apiPost("/recommendations/explain", { movie_id: id });
            setExplanation(r.explanation);
        } catch { toast.error("Couldn't generate insight"); }
        finally { setExplainLoading(false); }
    };

    const submitReport = async () => {
        if (reportBusy) return;
        setReportBusy(true);
        try {
            await apiPost(`/movies/${id}/report`, {
                reason: reportReason,
                detail: reportDetail.trim() || null,
                website: reportHp || undefined,
            });
            toast.success("Thanks — we'll review this");
            setReportOpen(false);
            setReportDetail("");
            setReportHp("");
            setReportReason("wrong_provider");
        } catch { toast.error("Couldn't send report"); }
        finally { setReportBusy(false); }
    };

    const refreshAvailability = async () => {
        if (refreshBusy) return;
        setRefreshBusy(true);
        try {
            const r = await apiPost(`/movies/${id}/refresh-providers`, {});
            setMovie((prev) => prev ? {
                ...prev,
                available_on: r.available_on,
                rent_on: r.rent_on,
                buy_on: r.buy_on,
                provider_region: r.provider_region,
                provider_confidence: r.provider_confidence,
                availability_region_matched: r.availability_region_matched,
            } : prev);
            toast.success("Availability refreshed");
        } catch { toast.error("Couldn't refresh"); }
        finally { setRefreshBusy(false); }
    };

    if (loadError) {
        return (
            <div className="min-h-screen bg-obsidian flex flex-col items-center justify-center px-6 text-center" data-testid="movie-detail-error">
                <h1 className="font-display text-3xl mb-3">Couldn't load</h1>
                <p className="text-sm text-zinc-400 mb-8 max-w-xs">{loadError}</p>
                <div className="flex gap-3">
                    <button onClick={() => { const c = new AbortController(); loadAll(c.signal); }}
                        className="px-5 py-3 rounded-xl bg-amber text-obsidian font-heading"
                        data-testid="movie-retry">
                        Try again
                    </button>
                    <button onClick={() => navigate(-1)}
                        className="px-5 py-3 rounded-xl glass-strong font-heading"
                        data-testid="movie-back">
                        Go back
                    </button>
                </div>
            </div>
        );
    }

    if (!movie) {
        return (
            <div className="min-h-screen bg-obsidian animate-pulse" data-testid="movie-detail-skeleton">
                <div className="h-[55vh] bg-gradient-to-t from-obsidian via-velvet/40 to-velvet/20" />
                <div className="px-5 pt-8 max-w-md mx-auto space-y-4">
                    <div className="flex gap-2 mb-2">
                        <div className="h-5 w-16 bg-white/8 rounded-full" />
                        <div className="h-5 w-12 bg-white/8 rounded-full" />
                    </div>
                    <div className="h-10 w-3/4 bg-white/10 rounded-xl" />
                    <div className="h-4 w-full bg-white/6 rounded-xl" />
                    <div className="h-4 w-5/6 bg-white/6 rounded-xl" />
                    <div className="h-4 w-4/5 bg-white/6 rounded-xl" />
                    <div className="flex gap-3 mt-6">
                        <div className="flex-1 h-12 bg-amber/20 rounded-2xl" />
                        <div className="flex-1 h-12 bg-white/8 rounded-2xl" />
                    </div>
                </div>
            </div>
        );
    }

    const servicesById = Object.fromEntries(services.map((s) => [s.id, s]));
    const tvTotalMinutes = isTv ? calcTvTotalMinutes(movie) : null;
    const myProviders = (movie.available_on || []).filter((sid) => (user?.subscriptions || []).includes(sid));
    const otherProviders = (movie.available_on || []).filter((sid) => !(user?.subscriptions || []).includes(sid));

    return (
        <div className="min-h-screen pb-28 bg-obsidian" data-testid="movie-detail-page">
            {/* Full-screen immersive banner */}
            <div className="relative h-screen max-h-[100svh] -mt-1">
                {(movie.backdrop_url || movie.poster_url) ? (
                    <img
                        loading="lazy"
                        src={movie.backdrop_url || movie.poster_url}
                        alt={movie.title}
                        className="absolute inset-0 w-full h-full object-cover"
                        onError={(e) => { e.target.style.display = "none"; }}
                    />
                ) : (
                    <div className="absolute inset-0 bg-gradient-to-br from-velvet to-obsidian" />
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/40 to-obsidian/30" />
                <div className="absolute inset-0 bg-gradient-to-r from-obsidian/40 to-transparent" />

                {/* Top bar */}
                <div className="absolute top-0 inset-x-0 px-5 pt-5 flex items-center justify-between z-10" style={{ paddingTop: "max(20px, env(safe-area-inset-top))" }}>
                    <button onClick={() => navigate(-1)} data-testid="back-btn" className="h-11 w-11 grid place-items-center rounded-full glass-strong" aria-label="back">
                        <ArrowLeft className="h-5 w-5" />
                    </button>
                    {movie.trailer_youtube_id && (
                        <button onClick={() => {
                            setTrailerOpen(true);
                            capture(EVENTS.TITLE_TRAILER_OPENED, {
                                content_id: id,
                                media_type: movie.type || "movie",
                                impression_id: impressionId || undefined,
                            }, { user, dedupeKey: `trailer:${id}:${impressionId || ""}` });
                            apiPost("/user/engage", { movie_id: id, action: "trailer_open", impression_id: impressionId }).catch(() => {});
                        }} data-testid="play-trailer-btn" className="h-11 px-4 flex items-center gap-2 rounded-full glass-strong text-amber font-heading hover:scale-105 transition-transform">
                            <Play className="h-4 w-4 fill-amber" /> Trailer
                        </button>
                    )}
                </div>

                {/* Hero content at bottom */}
                <div className="absolute bottom-0 inset-x-0 px-5 pb-8">
                    <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                        <DetailSignals card={movie.card} />
                        <div className="flex flex-wrap gap-1.5 mb-3">
                            {(movie.genres || []).slice(0, 4).map((g) => (
                                <span key={g} className="text-[10px] uppercase tracking-wider bg-white/12 backdrop-blur px-2.5 py-1 rounded-full">{g}</span>
                            ))}
                        </div>
                        <h1 className="font-display text-5xl leading-[0.95] mb-3">{movie.title || "Untitled"}</h1>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-300 mb-4">
                            {movie.rating > 0 && (
                                <><span className="flex items-center gap-1"><Star className="w-4 h-4 fill-amber text-amber" />{movie.rating.toFixed(1)}</span><Bullet /></>
                            )}
                            {movie.year && <><span>{movie.year}</span><Bullet /></>}
                            {isTv ? (
                                <span className="flex items-center gap-1">
                                    <Tv2 className="w-3.5 h-3.5" />
                                    {movie.seasons?.length || 1} season{(movie.seasons?.length || 1) !== 1 ? "s" : ""}
                                    {(() => { const total = (movie.seasons || []).reduce((s, se) => s + (se.episode_count || 0), 0); return total > 0 ? ` · ${total} ep` : ""; })()}
                                </span>
                            ) : (
                                <span className="flex items-center gap-1">
                                    <Clock className="w-3.5 h-3.5" />
                                    {formatRuntime(movie.runtime) || "—"}
                                </span>
                            )}
                            {isTv && movie.runtime > 0 && (<><Bullet /><span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" />{formatRuntime(movie.runtime)}/ep</span></>)}
                            {isTv && tvTotalMinutes > 0 && (<><Bullet /><span>~{formatRuntime(tvTotalMinutes)} binge</span></>)}
                        </div>
                        <div className="flex gap-3">
                            <button
                                onClick={() => act(isSaved ? "unsave" : "save")}
                                disabled={actionBusy}
                                data-testid="detail-save-btn"
                                className={`flex-1 py-3.5 rounded-2xl font-heading flex items-center justify-center gap-2 disabled:opacity-60 ${
                                    isSaved ? "bg-amber text-obsidian amber-glow" : "glass-strong text-white"
                                }`}
                            >
                                <Heart className={`w-4 h-4 ${isSaved ? "fill-obsidian" : ""}`} />
                                {isSaved ? "Saved" : "Save"}
                            </button>
                            <button
                                onClick={() => setFeedbackOpen(true)}
                                disabled={actionBusy}
                                data-testid="detail-watched-btn"
                                className={`flex-1 py-3.5 rounded-2xl font-heading flex items-center justify-center gap-2 disabled:opacity-60 ${
                                    isWatched ? "bg-white/12 border border-white/20" : "glass-strong"
                                }`}
                            >
                                <Eye className="w-4 h-4" /> {isWatched ? "Watched" : "Watched"}
                            </button>
                        </div>
                    </motion.div>
                </div>
            </div>

            {/* Content */}
            <div className="px-5 max-w-md mx-auto pt-8">
                <p className="text-base text-zinc-300 leading-relaxed">{movie.overview || "No description available."}</p>

                {/* AI explanation */}
                <button onClick={explain} disabled={explainLoading || !!explanation} data-testid="explain-btn"
                    className="mt-5 w-full glass rounded-2xl p-4 flex items-start gap-3 text-left disabled:opacity-100">
                    <div className="h-9 w-9 rounded-xl bg-amber/15 grid place-items-center shrink-0">
                        <Sparkles className="w-4 h-4 text-amber" />
                    </div>
                    <div className="flex-1">
                        <div className="font-heading text-sm mb-1">Why you'll love this</div>
                        <p className="text-sm text-zinc-400 leading-relaxed">
                            {explainLoading ? "Thinking…" : explanation || "Tap to get a personal take based on your taste."}
                        </p>
                    </div>
                </button>

                {/* TV: Seasons + progress */}
                {isTv && movie.seasons && movie.seasons.length > 0 && (
                    <div className="mt-8" data-testid="tv-seasons">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="font-heading text-base">Seasons</h3>
                            <button onClick={() => setProgressOpen(true)} data-testid="set-progress-btn"
                                className="text-xs text-amber hover:text-amber-600">
                                {progress ? `Up to S${progress.season} E${progress.episode}` : "Set progress"}
                            </button>
                        </div>
                        <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-1 px-1">
                            {movie.seasons.map((s) => (
                                <div key={s.season_number} data-testid={`season-${s.season_number}`}
                                    className="shrink-0 w-28 glass rounded-xl p-2">
                                    <div className="aspect-[2/3] rounded-lg overflow-hidden bg-velvet mb-2">
                                        {s.poster_path && <img loading="lazy" src={s.poster_path} alt={s.name} className="w-full h-full object-cover" />}
                                    </div>
                                    <div className="font-heading text-xs leading-tight truncate">{s.name}</div>
                                    <div className="text-[10px] text-zinc-500">{s.episode_count} ep{s.episode_count === 1 ? "" : "s"}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Where to watch */}
                <h3 className="font-heading text-base mt-8 mb-3">Stream</h3>
                {(() => {
                    const hasFlatrate = (movie.available_on || []).length > 0;
                    const hasRentBuy  = (movie.rent_on || []).length > 0 || (movie.buy_on || []).length > 0;

                    if (!hasFlatrate && !hasRentBuy) {
                        return (
                            <div data-testid="no-providers-msg">
                                <p className="text-sm text-zinc-500">
                                    {movie.availability_region_matched === false
                                        ? "We don't have confirmed availability for your region yet."
                                        : "Not currently streaming in your region."}
                                </p>
                                <button
                                    onClick={refreshAvailability}
                                    disabled={refreshBusy}
                                    className="mt-2 text-xs text-amber underline disabled:opacity-50"
                                    data-testid="refresh-availability"
                                >
                                    {refreshBusy ? "Checking…" : "Check availability now"}
                                </button>
                            </div>
                        );
                    }

                    if (!hasFlatrate) {
                        return (
                            <p className="text-sm text-zinc-500 italic" data-testid="rent-only-msg">
                                Not included in any subscription — available to rent or buy below.
                            </p>
                        );
                    }

                    return (
                        <div className="space-y-4" data-testid="streaming-sections">
                            {myProviders.length > 0 && (
                                <div>
                                    <p className="text-[10px] uppercase tracking-[0.2em] text-emerald-400 mb-2">Included with your plan</p>
                                    <div className="space-y-2">
                                        {myProviders.map((sid) => (
                                            <ProviderRow key={sid} sid={sid} s={servicesById[sid]} id={id} included />
                                        ))}
                                    </div>
                                </div>
                            )}
                            {otherProviders.length > 0 && (
                                <div>
                                    {myProviders.length > 0 && (
                                        <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-2">Also available on</p>
                                    )}
                                    <div className="space-y-2">
                                        {otherProviders.map((sid) => (
                                            <ProviderRow key={sid} sid={sid} s={servicesById[sid]} id={id} />
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    );
                })()}

                {((movie.rent_on || []).length + (movie.buy_on || []).length) > 0 && (() => {
                    const groups = {};
                    (movie.rent_on || []).forEach((p) => { groups[p] = { ...(groups[p] || {}), rent: true }; });
                    (movie.buy_on  || []).forEach((p) => { groups[p] = { ...(groups[p] || {}), buy:  true }; });
                    return (
                        <>
                            <h3 className="font-heading text-base mt-6 mb-3">Rent or buy</h3>
                            <div className="space-y-2">
                                {Object.entries(groups).map(([provider, { rent, buy }]) => (
                                    <div
                                        key={provider}
                                        className="flex items-center justify-between glass rounded-xl px-4 py-3"
                                        data-testid={`rentbuy-${provider.replace(/\s+/g, "-").toLowerCase()}`}
                                    >
                                        <div className="flex items-center gap-3">
                                            <RentBuyLogo name={provider} size={40} shape="rounded-xl" />
                                            <span className="font-heading text-sm">{provider}</span>
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                            {rent && (
                                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber/15 text-amber border border-amber/25"
                                                    data-testid={`rent-${provider}`}>Rent</span>
                                            )}
                                            {buy && (
                                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/10 text-zinc-300 border border-white/15"
                                                    data-testid={`buy-${provider}`}>Buy</span>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    );
                })()}

                {/* Availability trust actions */}
                <div className="mt-4 flex items-center gap-4 text-xs text-zinc-500">
                    {movie.provider_region && (
                        <span data-testid="provider-region">Region: {movie.provider_region}</span>
                    )}
                    <button
                        onClick={() => setReportOpen(true)}
                        className="underline hover:text-zinc-300"
                        data-testid="report-issue-btn"
                    >
                        Report an issue
                    </button>
                </div>

                {/* Reviews */}
                <ReviewsBlock movieId={id} reviews={reviews} onPosted={(r) => setReviews(r)} />

                {/* Similar */}
                {similar.length > 0 && (
                    <div className="mt-10" data-testid="similar-rail">
                        <h3 className="font-heading text-base mb-3">More like this</h3>
                        <div className="flex gap-3 overflow-x-auto no-scrollbar -mx-1 px-1">
                            {similar.map((m) => (
                                <button key={m.id} onClick={() => {
                                    capture(EVENTS.SIMILAR_TITLE_SELECTED, { content_id: m.id, media_type: m.type || "movie", source: "similar" }, { user, dedupeKey: `similar:${id}:${m.id}` });
                                    navigate(`/movie/${m.id}`);
                                }}
                                     className="shrink-0 w-32 text-left">
                                    <div className="aspect-[2/3] rounded-xl overflow-hidden bg-velvet mb-2">
                                        {m.poster_url && <img loading="lazy" src={m.poster_url} alt={m.title} className="w-full h-full object-cover" />}
                                    </div>
                                    <div className="font-heading text-xs leading-tight truncate">{m.title}</div>
                                    <div className="text-[10px] text-zinc-500 flex items-center gap-1">
                                        <Star className="w-2.5 h-2.5 fill-amber text-amber" />
                                        {m.rating?.toFixed(1)}
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Trailer modal */}
            <AnimatePresence>
                {trailerOpen && movie.trailer_youtube_id && (
                    <motion.div className="fixed inset-0 z-[60] bg-black/95 flex items-center justify-center"
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                        onClick={() => setTrailerOpen(false)} data-testid="trailer-modal">
                        <button onClick={() => setTrailerOpen(false)} data-testid="trailer-close"
                            className="absolute top-4 right-4 h-11 w-11 rounded-full bg-white/10 hover:bg-white/20 backdrop-blur grid place-items-center z-10">
                            <X className="h-5 w-5 text-white" />
                        </button>
                        <div className="w-full aspect-video max-w-5xl" onClick={(e) => e.stopPropagation()}>
                            <iframe title="trailer" width="100%" height="100%"
                                src={`https://www.youtube-nocookie.com/embed/${movie.trailer_youtube_id}?playsinline=1&rel=0&modestbranding=1&autoplay=1&mute=1`}
                                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                                allowFullScreen style={{ border: 0, background: "#000" }} />
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Report-issue modal */}
            <AnimatePresence>
                {reportOpen && (
                    <motion.div
                        className="fixed inset-0 z-[60] bg-obsidian/85 backdrop-blur-sm grid place-items-center px-5"
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                        onClick={() => setReportOpen(false)} data-testid="report-modal"
                    >
                        <motion.div initial={{ y: 30 }} animate={{ y: 0 }} onClick={(e) => e.stopPropagation()}
                            className="w-full max-w-sm glass-strong rounded-3xl p-6">
                            <h3 className="font-display text-2xl mb-1">Report an issue</h3>
                            <p className="text-xs text-zinc-500 mb-4">Help us keep availability accurate.</p>
                            <label className="block mb-4">
                                <span className="text-[10px] uppercase tracking-wider text-zinc-500">What's wrong?</span>
                                <select value={reportReason} onChange={(e) => setReportReason(e.target.value)}
                                    data-testid="report-reason"
                                    className="w-full mt-1 bg-velvet border border-white/10 rounded-xl p-3 text-sm text-foreground">
                                    <option value="wrong_provider" className="bg-velvet">Wrong streaming service listed</option>
                                    <option value="not_available" className="bg-velvet">Says available but it isn't</option>
                                    <option value="missing_title" className="bg-velvet">Title or info is missing</option>
                                    <option value="bad_metadata" className="bg-velvet">Wrong details (year, poster, etc.)</option>
                                    <option value="duplicate" className="bg-velvet">Duplicate entry</option>
                                    <option value="other" className="bg-velvet">Something else</option>
                                </select>
                            </label>
                            <label className="block mb-6">
                                <span className="text-[10px] uppercase tracking-wider text-zinc-500">Details (optional)</span>
                                <textarea value={reportDetail} onChange={(e) => setReportDetail(e.target.value.slice(0, 1000))}
                                    rows={3} data-testid="report-detail"
                                    className="w-full mt-1 bg-white/5 border border-white/10 rounded-xl p-3 text-sm resize-none"
                                    placeholder="Tell us more…" />
                            </label>
                            {/* Honeypot — hidden from humans; bots that fill it are dropped server-side. */}
                            <input
                                type="text"
                                name="website"
                                value={reportHp}
                                onChange={(e) => setReportHp(e.target.value)}
                                tabIndex={-1}
                                autoComplete="off"
                                aria-hidden="true"
                                style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }}
                            />
                            <div className="flex gap-3">
                                <button onClick={() => setReportOpen(false)} className="flex-1 py-3 rounded-2xl border border-white/10">Cancel</button>
                                <button onClick={submitReport} disabled={reportBusy} data-testid="report-submit"
                                    className="flex-1 py-3 bg-amber text-obsidian rounded-2xl font-heading disabled:opacity-50">
                                    {reportBusy ? "Sending…" : "Send report"}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Progress modal */}
            <ProgressModal
                open={progressOpen}
                onClose={() => setProgressOpen(false)}
                movie={movie}
                onSaved={async () => {
                    setProgressOpen(false);
                    await refresh();
                    const m = await apiGet(`/movies/${id}`);
                    setMovie(m);
                }}
            />
            <WatchedFeedbackDialog
                open={feedbackOpen}
                title={movie?.title}
                busy={actionBusy}
                onCancel={() => setFeedbackOpen(false)}
                onSelect={async (meta) => {
                    setFeedbackOpen(false);
                    await act("watched", meta);
                }}
            />
        </div>
    );
}

function ProviderRow({ sid, s, id, included = false }) {
    const { user } = useAuth();
    if (!s) return null;
    return (
        <button
            onClick={async () => {
                try {
                    const { url } = await apiPost("/affiliate/click", { movie_id: id, service_id: sid });
                    capture(EVENTS.PROVIDER_SELECTED, { provider: sid, content_id: id, media_type: "movie", source: "title_details" }, { user, dedupeKey: `provider-selected:${id}:${sid}` });
                    window.open(url, "_blank", "noopener,noreferrer");
                } catch {
                    capture(EVENTS.PROVIDER_SELECTED, { provider: sid, content_id: id, media_type: "movie", source: "title_details" }, { user, dedupeKey: `provider-selected:${id}:${sid}` });
                    window.open(s.affiliate_url, "_blank", "noopener,noreferrer");
                }
            }}
            data-testid={`watch-on-${sid}`}
            className="w-full flex items-center justify-between glass rounded-xl px-4 py-3 hover:bg-white/[0.06] active:scale-[0.98] transition-transform text-left"
        >
            <div className="flex items-center gap-3">
                <ProviderLogo sid={sid} size={44} shape="rounded-xl" />
                <div>
                    <div className="font-heading text-sm">{s.name}</div>
                    <div className="text-[10px] text-zinc-500">
                        {included ? `Included · £${s.price_monthly}/mo` : `£${s.price_monthly}/mo`}
                    </div>
                </div>
            </div>
            <ExternalLink className="h-4 w-4 text-zinc-400 shrink-0" />
        </button>
    );
}

function Bullet() { return <span className="text-zinc-600">·</span>; }

function ReviewsBlock({ movieId, reviews, onPosted }) {
    const [text, setText] = useState("");
    const [rating, setRating] = useState(8);
    const [posting, setPosting] = useState(false);

    const submit = async () => {
        if (text.trim().length < 5) { toast.error("Review needs at least 5 characters"); return; }
        setPosting(true);
        try {
            await apiPost(`/movies/${movieId}/reviews`, { movie_id: movieId, rating, text });
            const fresh = await apiGet(`/movies/${movieId}/reviews`);
            onPosted(fresh);
            setText("");
            toast.success("Review posted");
        } catch { toast.error("Couldn't post"); }
        finally { setPosting(false); }
    };

    const sum = reviews.summary || {};

    return (
        <div className="mt-10" data-testid="reviews-block">
            <h3 className="font-heading text-base mb-3 flex items-center gap-2">
                <Users className="w-4 h-4" /> Reviews
            </h3>
            <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="glass rounded-2xl p-4">
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">Community</div>
                    <div className="font-display text-2xl mt-1">{sum.tmdb_rating?.toFixed(1) || "—"}</div>
                    <div className="text-xs text-zinc-500">{sum.tmdb_vote_count?.toLocaleString() || 0} votes (TMDB)</div>
                </div>
                <div className="glass rounded-2xl p-4">
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">WatchSmart</div>
                    <div className="font-display text-2xl mt-1">{sum.user_avg ?? "—"}</div>
                    <div className="text-xs text-zinc-500">{sum.user_count || 0} reviews</div>
                </div>
            </div>

            {/* Add review */}
            <div className="glass rounded-2xl p-4 mb-4" data-testid="review-form">
                <div className="flex items-center gap-1 mb-3">
                    {[...Array(10)].map((_, i) => (
                        <button key={i} onClick={() => setRating(i + 1)} aria-label={`rate ${i + 1}`}
                            data-testid={`star-${i + 1}`}
                            className={`h-7 w-7 grid place-items-center ${i < rating ? "text-amber" : "text-zinc-600"}`}>
                            <Star className={`w-5 h-5 ${i < rating ? "fill-amber" : ""}`} />
                        </button>
                    ))}
                    <span className="ml-2 text-sm font-heading text-zinc-300">{rating}/10</span>
                </div>
                <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Share what you thought…"
                    data-testid="review-text"
                    className="w-full bg-white/5 border border-white/10 rounded-xl p-3 text-sm focus:border-amber/60 outline-none resize-none"
                    rows={3}
                />
                <button onClick={submit} disabled={posting} data-testid="review-submit"
                    className="mt-3 px-4 py-2.5 bg-amber text-obsidian font-heading rounded-xl text-sm hover:bg-amber-600 disabled:opacity-60">
                    {posting ? "Posting…" : "Post review"}
                </button>
            </div>

            {/* User reviews */}
            <ul className="space-y-2">
                {(reviews.user || []).map((r, i) => (
                    <li key={i} className="glass rounded-2xl p-4" data-testid={`user-review-${i}`}>
                        <div className="flex items-center justify-between mb-1">
                            <div className="font-heading text-sm">{r.user_name}</div>
                            <div className="flex items-center gap-1 text-xs text-amber">
                                <Star className="w-3 h-3 fill-amber" /> {r.rating}/10
                            </div>
                        </div>
                        <p className="text-sm text-zinc-300 leading-relaxed">{r.text}</p>
                    </li>
                ))}
                {(reviews.tmdb || []).map((r, i) => (
                    <li key={`t-${i}`} className="glass rounded-2xl p-4 border border-white/8" data-testid={`tmdb-review-${i}`}>
                        <div className="flex items-center justify-between mb-1">
                            <div className="font-heading text-sm">{r.author} <span className="text-[10px] text-zinc-500 uppercase tracking-wider ml-1">via TMDB</span></div>
                            {r.rating && <div className="flex items-center gap-1 text-xs text-amber"><Star className="w-3 h-3 fill-amber" /> {r.rating}/10</div>}
                        </div>
                        <p className="text-sm text-zinc-300 leading-relaxed line-clamp-6">{r.content}</p>
                    </li>
                ))}
            </ul>
        </div>
    );
}

function ProgressModal({ open, onClose, movie, onSaved }) {
    const [season, setSeason] = useState(movie?.progress?.season || 1);
    const [episode, setEpisode] = useState(movie?.progress?.episode || 1);
    const [saving, setSaving] = useState(false);
    const seasons = movie?.seasons || [];
    const currentSeason = seasons.find((s) => s.season_number === season);
    const maxEp = currentSeason?.episode_count || 99;

    useEffect(() => {
        if (open) {
            setSeason(movie?.progress?.season || 1);
            setEpisode(movie?.progress?.episode || 1);
        }
    }, [open, movie]);

    const save = async () => {
        setSaving(true);
        try {
            await apiPost("/user/progress", { movie_id: movie.id, season, episode });
            toast.success(`Up to S${season} E${episode}`);
            onSaved();
        } catch { toast.error("Couldn't save"); }
        finally { setSaving(false); }
    };

    return (
        <AnimatePresence>
            {open && (
                <motion.div
                    className="fixed inset-0 z-[60] bg-obsidian/85 backdrop-blur-sm grid place-items-center px-5"
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    onClick={onClose} data-testid="progress-modal"
                >
                    <motion.div initial={{ y: 30 }} animate={{ y: 0 }} onClick={(e) => e.stopPropagation()}
                        className="w-full max-w-sm glass-strong rounded-3xl p-6">
                        <h3 className="font-display text-2xl mb-4">Where are you up to?</h3>
                        <label className="block mb-4">
                            <span className="text-[10px] uppercase tracking-wider text-zinc-500">Season</span>
                            <select value={season} onChange={(e) => { setSeason(+e.target.value); setEpisode(1); }}
                                data-testid="progress-season"
                                className="w-full mt-1 bg-velvet border border-white/10 rounded-xl p-3 text-sm text-foreground">
                                {seasons.map((s) => (
                                    <option key={s.season_number} value={s.season_number} className="bg-velvet text-foreground">
                                        {s.name} ({s.episode_count} ep)
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="block mb-6">
                            <span className="text-[10px] uppercase tracking-wider text-zinc-500">Episode</span>
                            <input type="number" min={1} max={maxEp} value={episode}
                                onChange={(e) => setEpisode(Math.max(1, Math.min(maxEp, +e.target.value)))}
                                data-testid="progress-episode"
                                className="w-full mt-1 bg-white/5 border border-white/10 rounded-xl p-3 text-sm" />
                        </label>
                        <div className="flex gap-3">
                            <button onClick={onClose} className="flex-1 py-3 rounded-2xl border border-white/10">Cancel</button>
                            <button onClick={save} disabled={saving} data-testid="progress-save"
                                className="flex-1 py-3 bg-amber text-obsidian rounded-2xl font-heading">
                                {saving ? "Saving…" : "Save"}
                            </button>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}

// =====================================================================
// DetailSignals — same minimal exposure as Discover (tone + audience pill +
// optional verified tick). Hides neutral tone; collapses teen→Adult.
// Never exposes conflict_logs / sub-confidences / raw genre mixes.
// =====================================================================
const DETAIL_TONE_PILL = {
    light: { label: "Light", className: "bg-amber/15 text-amber border-amber/30" },
    dark:  { label: "Dark",  className: "bg-red-500/15 text-red-300 border-red-500/30" },
};
const DETAIL_AUDIENCE_PILL = {
    kids:   "Kids",
    family: "Family",
    teen:   "Adult",
    adult:  "Adult",
};

function DetailSignals({ card }) {
    if (!card) return null;
    const tone = DETAIL_TONE_PILL[card.tone];
    const audLabel = DETAIL_AUDIENCE_PILL[card.audience_type];
    const verified = (card.confidence_score ?? 0) >= 0.85;
    if (!tone && !audLabel && !verified) return null;
    return (
        <div className="flex items-center gap-1.5 mb-3" data-testid="detail-card-signals">
            {tone && (
                <span
                    data-testid={`detail-tone-pill-${card.tone}`}
                    className={`text-[10px] uppercase tracking-[0.18em] px-2 py-0.5 rounded-full border ${tone.className}`}
                >
                    {tone.label}
                </span>
            )}
            {audLabel && (
                <span
                    data-testid={`detail-audience-pill-${card.audience_type}`}
                    className="text-[10px] uppercase tracking-[0.18em] px-2 py-0.5 rounded-full border border-white/15 text-zinc-200 bg-white/5"
                >
                    {audLabel}
                </span>
            )}
            {verified && (
                <span
                    data-testid="detail-verified-badge"
                    aria-label="Classification verified"
                    className="text-[10px] tracking-wider px-1.5 py-0.5 rounded-full text-emerald-300/90 bg-emerald-500/8 border border-emerald-500/20"
                >
                    ✓
                </span>
            )}
        </div>
    );
}

