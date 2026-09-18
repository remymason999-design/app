import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Heart, Star, Eye, Play, Check, Clock3, Tv2, X } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { toast } from "sonner";
import AccountMenu from "@/components/AccountMenu";
import { useAuth } from "@/context/AuthContext";
import { ProviderLogo } from "@/components/ProviderLogo";
import { formatRuntime, totalEpisodes } from "@/lib/format";
import { capture, EVENTS } from "@/lib/analytics";

const SORT_OPTIONS = [
    { value: "recent", label: "Recently added" }, { value: "title", label: "Title (A–Z)" },
    { value: "rating", label: "Highest rated" }, { value: "year", label: "Newest released" },
];
const LIBRARY_RETURN_KEY = "ws_library_return";

function readLibraryReturn(locationKey) {
    try {
        const value = JSON.parse(sessionStorage.getItem(LIBRARY_RETURN_KEY) || "null");
        return value?.locationKey === locationKey ? value : null;
    } catch { return null; }
}

function normalizeLibrary(payload, watched = []) {
    if (Array.isArray(payload)) return { saved: payload, watched };
    return {
        saved: payload?.saved || payload?.watchlist || payload?.items || [],
        watched: payload?.watched || watched || [],
        continueWatching: payload?.continue_watching || payload?.continueWatching || [],
        stats: payload?.stats || {},
    };
}

function formatWatchTime(totalHours) {
    if (!totalHours) return "—";
    const h = Math.floor(totalHours);
    const m = Math.round((totalHours - h) * 60);
    if (h === 0) return `${m}m`;
    if (m === 0) return `${h}h`;
    return `${h}h ${m}m`;
}

function getCompletionPercent(movie, p) {
    const completion = movie.completion || {};
    const watched = completion.watched_released_episode_count ?? completion.watched_episode_count;
    const eligible = completion.eligible_episode_count;
    if (Number.isFinite(watched) && Number.isFinite(eligible) && eligible > 0) {
        return Math.min(100, Math.round((watched / eligible) * 100));
    }
    if (!p) p = movie.progress || movie.user_progress;
    if (!p || !movie.seasons) return null;
    const totalEps = totalEpisodes(movie.seasons);
    if (!totalEps) return null;
    let count = 0;
    for (const s of movie.seasons) {
        if (s.season_number < p.season) {
            count += s.episode_count || 0;
        } else if (s.season_number === p.season) {
            count += p.episode;
            break;
        }
    }
    return Math.min(100, Math.round((count / totalEps) * 100));
}

function isTvCompleted(movie) {
    return movie.completion?.completed === true || movie.watched_completed === true;
}

const REACTION_LABELS = {
    loved: "Loved",
    liked: "Liked",
    neutral: "Okay",
    disliked: "Didn't Like",
};

function formatReaction(value) {
    return REACTION_LABELS[String(value || "").toLowerCase()] || "";
}

export default function Watchlist() {
    const location = useLocation();
    const pendingReturn = useMemo(() => readLibraryReturn(location.key), [location.key]);
    const { user, setUser } = useAuth();
    const [library, setLibrary] = useState({ saved: [], watched: [], continueWatching: [], stats: {} });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [primary, setPrimary] = useState(pendingReturn?.primary || "saved");
    const [typeTab, setTypeTab] = useState(pendingReturn?.typeTab || "all");
    const [sort, setSort] = useState(() => pendingReturn?.sort || localStorage.getItem("ws_library_sort") || "recent");
    const [progressMovie, setProgressMovie] = useState(null);
    const userSubs = user?.subscriptions || [];

    const load = async () => {
        setError(null);
        try {
            let payload;
            try { payload = await apiGet("/library"); }
            catch { payload = await apiGet("/watchlist"); }
            let next = normalizeLibrary(payload);
            if (!next.watched.length) {
                try { next = normalizeLibrary(payload, await apiGet("/watched")); } catch {}
            }
            setLibrary((old) => JSON.stringify(old) === JSON.stringify(next) ? old : next);
        } catch (err) {
            setError(err?.response?.status === 401 ? "Please sign in again." : "Couldn't load your library. Check your connection.");
        } finally { setLoading(false); }
    };

    useEffect(() => {
        load();
        apiPost("/user/watchlist-seen").catch(() => {});
        capture(EVENTS.WATCHLIST_VIEWED, {}, { user });
        setUser?.((u) => (u ? { ...u, watchlist_unseen: 0 } : u));
        const refresh = () => { if (document.visibilityState === "visible") load(); };
        document.addEventListener("visibilitychange", refresh); window.addEventListener("focus", refresh);
        return () => { document.removeEventListener("visibilitychange", refresh); window.removeEventListener("focus", refresh); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const saved = Number(pendingReturn?.scrollY);
        if (loading || !Number.isFinite(saved) || saved <= 0) return;
        const frame = requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                window.scrollTo({ top: saved, behavior: "auto" });
                try { sessionStorage.removeItem(LIBRARY_RETURN_KEY); } catch {}
            });
        });
        return () => cancelAnimationFrame(frame);
    }, [loading, pendingReturn]);

    const rememberReturn = () => {
        try {
            sessionStorage.setItem(LIBRARY_RETURN_KEY, JSON.stringify({
                locationKey: location.key, primary, typeTab, sort, scrollY: window.scrollY,
            }));
        } catch {}
    };

    const source = primary === "saved" ? library.saved : library.watched;
    const activeCw = useMemo(
        () => library.continueWatching.filter((m) => m.type === "tv" && !isTvCompleted(m)),
        [library.continueWatching]
    );
    const activeCwIds = useMemo(() => new Set(activeCw.map((m) => m.id)), [activeCw]);
    const needsProgress = useMemo(
        () => library.watched.filter((m) => m.type === "tv" && !activeCwIds.has(m.id) && !isTvCompleted(m)),
        [activeCwIds, library.watched]
    );
    const items = useMemo(() => {
        let arr = primary === "saved"
            ? [...source]
            : source.filter((m) => m.type !== "tv" || isTvCompleted(m));
        if (typeTab === "movie") arr = arr.filter((m) => m.type !== "tv");
        if (typeTab === "tv") arr = arr.filter((m) => m.type === "tv");
        if (sort === "title") arr.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
        if (sort === "rating") arr.sort((a, b) => (b.rating || 0) - (a.rating || 0));
        if (sort === "year") arr.sort((a, b) => (b.year || 0) - (a.year || 0));
        return arr;
    }, [primary, source, typeTab, sort]);

    const remove = async (id) => {
        const key = primary === "saved" ? "saved" : "watched";
        const old = library;
        setLibrary((v) => ({ ...v, [key]: v[key].filter((m) => m.id !== id) }));
        try {
            const action = primary === "saved" ? "unsave" : "unwatched";
            await apiPost("/user/action", { movie_id: id, action });
            if (action === "unsave") capture(EVENTS.WATCHLIST_ITEM_REMOVED, { content_id: id, source: "watchlist", watchlist_size: source.length - 1 }, { user, dedupeKey: `library:${primary}:${id}:${action}` });
            toast(primary === "saved" ? "Removed from watchlist" : "Marked unwatched");
        }
        catch { setLibrary(old); toast.error("Couldn't update. Try again."); }
    };

    return <div className="min-h-[100dvh] px-5 pt-10 pb-36 max-w-md mx-auto" data-testid="library-page">
        <div className="flex items-start justify-between mb-6"><div><p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Your collection</p><h1 className="font-display text-4xl mt-2">Library</h1><p className="text-sm text-zinc-400 mt-1">{source.length} {primary === "saved" ? "saved" : "watched"}</p></div><AccountMenu /></div>
        <div className="grid grid-cols-2 gap-1.5 p-1 mb-6 bg-white/4 rounded-2xl border border-white/5" data-testid="library-primary-tabs">
            {[["saved", "Watchlist", Heart], ["watched", "Watched", Eye]].map(([id, label, Icon]) => <button key={id} onClick={() => setPrimary(id)} data-testid={`library-tab-${id}`} className={`py-3 rounded-xl text-sm font-heading flex items-center justify-center gap-2 transition-colors ${primary === id ? "bg-amber text-obsidian shadow-lg" : "text-zinc-400 hover:text-white"}`}><Icon className="w-4 h-4" />{label}</button>)}
        </div>

        {!loading && !error && primary === "watched" && (
            <LibraryStats stats={library.stats} watchedCount={library.watched.length} />
        )}

        {primary === "watched" && typeTab !== "movie" && (
            <>
                {activeCw.length > 0 && <section className="mb-8" data-testid="continue-watching"><div className="flex items-end justify-between mb-3"><div><p className="text-[10px] uppercase tracking-[0.2em] text-amber">In progress</p><h2 className="font-display text-2xl flex items-center gap-2"><Play className="w-4 h-4 text-amber fill-amber" />Continue watching</h2></div><span className="text-xs text-zinc-500">{activeCw.length} show{activeCw.length === 1 ? "" : "s"}</span></div><ul className="flex gap-4 overflow-x-auto no-scrollbar pb-2 -mx-5 px-5">{activeCw.map((m) => <LibraryCard key={m.id} movie={m} userSubs={userSubs} watched onRemove={remove} onOpen={rememberReturn} onTrack={setProgressMovie} compact />)}</ul></section>}
                {needsProgress.length > 0 && <section className="mb-8" data-testid="watched-needs-progress"><h2 className="font-heading text-sm mb-1 flex items-center gap-2"><Tv2 className="w-4 h-4 text-amber" />Start tracking TV</h2><p className="text-xs text-zinc-500 mb-3">Tell WatchSmart where you are to track episodes and watch time.</p><ul className="flex gap-4 overflow-x-auto no-scrollbar pb-2 -mx-5 px-5">{needsProgress.map((m) => <LibraryCard key={m.id} movie={m} userSubs={userSubs} watched onRemove={remove} onOpen={rememberReturn} onTrack={setProgressMovie} compact />)}</ul></section>}
            </>
        )}

        {!loading && !error && (source.length > 0 || library.continueWatching?.length > 0) && <div className="flex items-center justify-between gap-2 mb-6"><div className="flex gap-1.5" data-testid="library-type-tabs">{[["all", "All"], ["movie", "Movies"], ["tv", "TV"]].map(([id, label]) => <button key={id} onClick={() => setTypeTab(id)} data-testid={`library-filter-${id}`} className={`px-4 py-2 rounded-full text-xs font-medium border transition-colors ${typeTab === id ? "bg-amber border-amber text-obsidian" : "border-white/10 text-zinc-400 hover:text-white hover:bg-white/5"}`}>{label}</button>)}</div><select value={sort} onChange={(e) => { setSort(e.target.value); localStorage.setItem("ws_library_sort", e.target.value); }} data-testid="library-sort" aria-label="Sort" className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs hover:bg-white/10 transition-colors">{SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></div>}

        {error && !loading ? <div className="text-center py-20" data-testid="library-error"><h3 className="font-heading text-xl mb-2">Something went wrong</h3><p className="text-sm text-zinc-400 mb-6">{error}</p><button onClick={load} className="px-5 py-3 rounded-xl bg-amber text-obsidian font-heading hover:bg-amber-600 transition-colors" data-testid="library-retry">Try again</button></div>
            : loading ? <div className="grid grid-cols-2 gap-4">{[1,2,3,4].map(i => <div key={i} className="animate-pulse"><div className="aspect-[2/3] rounded-2xl bg-white/8" /><div className="h-3 w-3/4 rounded mt-3 bg-white/6" /></div>)}</div>
            : items.length === 0 ? <div className="text-center py-20"><div className="w-20 h-20 rounded-2xl bg-amber/15 grid place-items-center mx-auto mb-5">{primary === "saved" ? <Heart className="w-8 h-8 text-amber" /> : <Eye className="w-8 h-8 text-amber" />}</div><h3 className="font-display text-2xl mb-3">{primary === "saved" ? "Nothing saved yet" : "Nothing marked watched yet"}</h3><p className="text-sm text-zinc-400 mb-8 leading-relaxed max-w-[260px] mx-auto">{primary === "saved" ? "Save titles from Discover to keep them here." : "Mark titles watched to build your viewing history."}</p><Link to="/discover" className="inline-block px-6 py-3.5 rounded-xl bg-amber text-obsidian font-heading hover:bg-amber-600 transition-colors shadow-lg">Browse Discover</Link></div>
            : <>{primary === "watched" && <div className="mb-3"><p className="text-[10px] uppercase tracking-[0.2em] text-amber">Finished</p><h2 className="font-display text-2xl flex items-center gap-2" data-testid="completed-heading"><Check className="w-5 h-5 text-amber" />Completed</h2></div>}<ul className="grid grid-cols-2 gap-4 items-start">{items.map((m) => <LibraryCard key={m.id} movie={m} userSubs={userSubs} watched={primary === "watched"} onRemove={remove} onOpen={rememberReturn} onTrack={setProgressMovie} />)}</ul></>}

        <ProgressPicker
            movie={progressMovie}
            onClose={() => setProgressMovie(null)}
            onSaved={async () => {
                setProgressMovie(null);
                await load();
            }}
        />
    </div>;
}

function LibraryStats({ stats, watchedCount }) {
    const estimated = stats.estimated || stats.provenance === "mixed" || stats.total_hours_estimated;
    const cards = [
        { label: "Titles watched", value: stats.titles_watched ?? stats.watched ?? watchedCount, Icon: Eye },
        { label: "Total watch time", value: formatWatchTime(stats.total_hours || stats.hours || stats.estimated_hours || 0), Icon: Clock3, estimated },
        { label: "Episodes watched", value: stats.watched_episodes ?? 0, Icon: Play, estimated: stats.estimated || stats.provenance === "mixed" },
    ];
    return (
        <section className="mb-8" aria-label="Viewing statistics">
            <h2 className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">Your viewing</h2>
            <div className="grid grid-cols-3 gap-2" data-testid="library-stats">
                {cards.map(({ label, value, Icon, estimated: isEstimated }) => (
                    <div key={label} className="rounded-2xl p-3 min-h-28 bg-gradient-to-b from-white/[0.07] to-white/[0.025] border border-white/10 flex flex-col">
                        <Icon className="w-4 h-4 text-amber mb-auto" />
                        <div className="font-display text-xl leading-none text-white mt-3">{value}</div>
                        <div className="text-[9px] text-zinc-400 mt-2 uppercase tracking-wider leading-tight">{label}</div>
                        {isEstimated && <div className="text-[8px] text-amber/70 mt-1 uppercase tracking-widest">estimated</div>}
                    </div>
                ))}
            </div>
        </section>
    );
}

function ProgressLabel({ movie, compact = false, watched = false }) {
    if (movie.type !== "tv") return null;
    const p = movie.progress || movie.user_progress;
    const pct = getCompletionPercent(movie, p);
    const visiblePct = pct !== null ? Math.max(4, pct) : 24;
    const season = movie.seasons?.find?.((item) => Number(item?.season_number) === Number(p?.season));

    return (
        <div className="mt-1">
            <div className="text-[10px] text-amber">
                {p ? `S${p.season} E${p.episode}${season?.episode_count ? ` of ${season.episode_count}` : ""}` : (compact ? "Not started" : (watched ? "Set progress" : "Start tracking"))}
            </div>
            {p && (
                <div
                    className="h-1.5 bg-white/15 rounded-full mt-2 overflow-hidden ring-1 ring-black/20"
                    role="progressbar"
                    aria-label={`${movie.title} viewing progress`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={pct ?? undefined}
                    aria-valuetext={pct !== null ? `${pct}% watched` : "Progress recorded; total episode count unavailable"}
                    data-testid={`progress-bar-${movie.id}`}
                >
                    <div
                        className={`h-full bg-amber rounded-full ${pct === null ? "opacity-70" : ""}`}
                        style={{ width: `${visiblePct}%` }}
                    />
                </div>
            )}
        </div>
    );
}

function LibraryCard({ movie: m, userSubs, watched, onRemove, onOpen, onTrack, compact = false }) {
    const providers = (m.available_on || []).slice(0, 2);
    const progress = m.progress || m.user_progress || null;
    const reaction = watched ? formatReaction(m.you_reaction) : "";

    return <li data-testid={`${watched ? "watched" : "watchlist"}-item-${m.id}`} className={`flex flex-col h-full ${compact ? "shrink-0 w-36" : ""}`}>
        <Link to={`/movie/${m.id}`} onClick={() => { onOpen(); capture(EVENTS.WATCHLIST_ITEM_OPENED, { content_id: m.id, media_type: m.type || "movie", source: watched ? "watched" : "watchlist" }, { dedupeKey: `watchlist-open:${m.id}` }); }} className="block relative aspect-[2/3] rounded-2xl overflow-hidden card-shadow bg-white/8 group">
            {m.poster_url && <img loading="lazy" src={m.poster_url} alt={m.title} className="absolute inset-0 w-full h-full object-cover transition-transform duration-500 group-hover:scale-105" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
            <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/30 to-transparent" />
            {providers.length > 0 && <div className="absolute top-2 right-2 flex gap-1">{providers.map(sid => <ProviderLogo key={sid} sid={sid} size={22} shape="rounded-md" subscribed={userSubs.includes(sid)} />)}</div>}
            <div className="absolute bottom-0 inset-x-0 p-3">
                <div className="font-heading text-sm leading-tight line-clamp-2">{m.title}</div>
                <div className="flex items-center justify-between mt-1.5 text-[10px] text-zinc-300">
                    <span className="flex items-center gap-1">
                        <Star className="w-3 h-3 fill-amber text-amber" />
                        {m.rating?.toFixed?.(1) || "—"}
                    </span>
                    <span>{m.type === "tv" ? `${m.seasons?.length || 1}S` : (formatRuntime(m.runtime) || "—")}</span>
                </div>
                <ProgressLabel movie={{ ...m, progress }} watched={watched} />
            </div>
        </Link>
        {reaction && (
            <div className="mt-2 inline-flex self-start items-center gap-1.5 rounded-full bg-amber/10 border border-amber/25 px-2.5 py-1 text-[10px] font-heading text-amber" data-testid={`reaction-${m.id}`}>
                <Heart className="w-3 h-3" /> {reaction}
            </div>
        )}
        <div className="flex-1" />
        {m.type === "tv" && (
            <button
                className="mt-3 w-full min-h-11 py-2.5 rounded-xl text-xs font-heading text-obsidian bg-amber hover:bg-amber-600 transition-colors flex items-center justify-center gap-2"
                onClick={() => onTrack(m)}
                data-testid={`${progress ? "update-progress" : "start-tracking"}-${m.id}`}
            >
                <Play className="w-3.5 h-3.5" />
                {progress ? "Update progress" : (watched ? "Update progress" : "Start tracking")}
            </button>
        )}
        <button onClick={() => onRemove(m.id)} className="mt-3 w-full py-2 text-[10px] uppercase tracking-widest text-zinc-500 hover:text-amber transition-colors" data-testid={`${watched ? "watched-unmark" : "watchlist-remove"}-${m.id}`}>
            {watched ? "Mark unwatched" : "Remove"}
        </button>
    </li>;
}

function ProgressPicker({ movie, onClose, onSaved }) {
    const current = movie?.progress || movie?.user_progress;
    const availableSeasons = useMemo(
        () => (movie?.seasons || []).filter((s) => Number(s?.season_number) > 0),
        [movie]
    );
    const firstSeason = availableSeasons[0]?.season_number || 1;
    const [season, setSeason] = useState(Number(current?.season || firstSeason));
    const [episode, setEpisode] = useState(Number(current?.episode || 1));
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!movie) return;
        const seasons = (movie.seasons || []).filter((s) => Number(s?.season_number) > 0);
        setSeason(Number(current?.season || seasons[0]?.season_number || 1));
        setEpisode(Number(current?.episode || 1));
    }, [movie, current?.season, current?.episode]);

    const selectedSeason = availableSeasons.find((s) => Number(s.season_number) === Number(season));
    const episodeCount = Math.max(1, Number(selectedSeason?.episode_count || episode || 1));
    const selectedEpisode = Math.min(episode, episodeCount);
    const save = async (endpoint = "/user/progress/watched-through") => {
        setBusy(true);
        try {
            await apiPost(endpoint, { movie_id: movie.id, season: Number(season), episode: Number(selectedEpisode) });
            toast.success(endpoint.endsWith("/series") ? "Show marked complete" : "Progress updated");
            await onSaved();
        } catch {
            toast.error("Couldn't update progress");
        } finally {
            setBusy(false);
        }
    };

    if (!movie) return null;
    return (
        <div className="fixed inset-0 z-[90] bg-black/75 backdrop-blur-sm flex items-end sm:items-center justify-center" data-testid="progress-modal">
            <button className="absolute inset-0" onClick={onClose} aria-label="Close progress picker" />
            <div className="relative w-full max-w-md rounded-t-3xl sm:rounded-3xl bg-[#101722] border border-white/10 p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-2xl">
                <button onClick={onClose} className="absolute top-4 right-4 h-9 w-9 rounded-full bg-white/5 grid place-items-center text-zinc-300" aria-label="Close">
                    <X className="w-4 h-4" />
                </button>
                <p className="text-[10px] uppercase tracking-[0.2em] text-amber">Track every episode</p>
                <h2 className="font-display text-2xl mt-1 pr-12">Update progress</h2>
                <p className="text-sm text-zinc-400 mt-1 truncate">{movie.title}</p>

                <div className="grid grid-cols-2 gap-3 mt-6">
                    <label className="text-[10px] uppercase tracking-wider text-zinc-400">Season
                        <select
                            value={season}
                            onChange={(e) => { setSeason(Number(e.target.value)); setEpisode(1); }}
                            className="mt-2 w-full min-h-12 rounded-xl bg-white/[0.06] border border-white/15 px-3 text-base text-white outline-none focus:border-amber"
                            data-testid="progress-season"
                        >
                            {(availableSeasons.length ? availableSeasons : [{ season_number: season }]).map((s) => (
                                <option key={s.season_number} value={s.season_number}>Season {s.season_number}</option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[10px] uppercase tracking-wider text-zinc-400">Episode
                        <select
                            value={selectedEpisode}
                            onChange={(e) => setEpisode(Number(e.target.value))}
                            className="mt-2 w-full min-h-12 rounded-xl bg-white/[0.06] border border-white/15 px-3 text-base text-white outline-none focus:border-amber"
                            data-testid="progress-episode"
                        >
                            {Array.from({ length: episodeCount }, (_, index) => index + 1).map((value) => (
                                <option key={value} value={value}>Episode {value}</option>
                            ))}
                        </select>
                    </label>
                </div>

                <div className="mt-5 rounded-2xl bg-amber/10 border border-amber/20 p-4">
                    <div className="text-sm font-heading text-white">Watched through S{season} E{selectedEpisode}</div>
                    <p className="text-xs text-zinc-400 mt-1">This updates your Continue Watching position, episode total and watch-time estimate.</p>
                </div>

                <button disabled={busy} onClick={() => save()} className="mt-4 w-full min-h-12 rounded-2xl bg-amber text-obsidian font-heading disabled:opacity-50" data-testid="progress-save">
                    {busy ? "Updating…" : "Save progress"}
                </button>
                <button disabled={busy} onClick={() => save("/user/progress/series")} className="mt-2 w-full min-h-11 rounded-2xl bg-white/5 border border-white/10 text-sm text-zinc-200 disabled:opacity-50">
                    Mark currently available episodes watched
                </button>
            </div>
        </div>
    );
}