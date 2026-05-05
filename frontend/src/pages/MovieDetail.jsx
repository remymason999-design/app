import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Heart, Eye, Star, Sparkles, Play, ExternalLink, X, Tv2, Clock, Users } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
export default function MovieDetail() {
    const { id } = useParams();
    const navigate = useNavigate();
    const { user, refresh } = useAuth();
    const [movie, setMovie] = useState(null);
    const [services, setServices] = useState([]);
    const [explanation, setExplanation] = useState("");
    const [explainLoading, setExplainLoading] = useState(false);
    const [trailerOpen, setTrailerOpen] = useState(false);
    const [reviews, setReviews] = useState({ summary: {}, user: [], tmdb: [] });
    const [similar, setSimilar] = useState([]);
    const [progressOpen, setProgressOpen] = useState(false);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const m = await apiGet(`/movies/${id}`);
                if (!cancelled) setMovie(m);
            } catch {
                navigate("/discover");
            }
        })();
        apiGet("/services").then(setServices);
        apiGet(`/movies/${id}/reviews`).then(setReviews).catch(() => {});
        apiGet(`/movies/${id}/similar`).then(setSimilar).catch(() => {});
        return () => { cancelled = true; };
    }, [id, navigate]);

    const isSaved = user?.saved?.includes(id);
    const isWatched = user?.watched?.includes(id);
    const isTv = movie?.type === "tv";
    const progress = movie?.progress;

    const act = async (action) => {
        try {
            await apiPost("/user/action", { movie_id: id, action });
            await refresh();
            toast.success(action === "save" ? "Saved" : action === "watched" ? "Marked watched" : "Removed");
        } catch { toast.error("Couldn't update"); }
    };

    const explain = async () => {
        setExplainLoading(true);
        try {
            const r = await apiPost("/recommendations/explain", { movie_id: id });
            setExplanation(r.explanation);
        } catch { toast.error("Couldn't generate insight"); }
        finally { setExplainLoading(false); }
    };

    if (!movie) {
        return <div className="min-h-screen grid place-items-center"><div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" /></div>;
    }

    const servicesById = Object.fromEntries(services.map((s) => [s.id, s]));
    const totalHours = movie.total_runtime ? Math.round(movie.total_runtime / 60) : null;

    return (
        <div className="min-h-screen pb-28 bg-obsidian" data-testid="movie-detail-page">
            {/* Full-screen immersive banner */}
            <div className="relative h-screen max-h-[100svh] -mt-1">
                <img loading="lazy" src={movie.backdrop_url || movie.poster_url} alt={movie.title} className="absolute inset-0 w-full h-full object-cover" />
                <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/40 to-obsidian/30" />
                <div className="absolute inset-0 bg-gradient-to-r from-obsidian/40 to-transparent" />

                {/* Top bar */}
                <div className="absolute top-0 inset-x-0 px-5 pt-5 flex items-center justify-between z-10" style={{ paddingTop: "max(20px, env(safe-area-inset-top))" }}>
                    <button onClick={() => navigate(-1)} data-testid="back-btn" className="h-11 w-11 grid place-items-center rounded-full glass-strong" aria-label="back">
                        <ArrowLeft className="h-5 w-5" />
                    </button>
                    {movie.trailer_youtube_id && (
                        <button onClick={() => setTrailerOpen(true)} data-testid="play-trailer-btn" className="h-11 px-4 flex items-center gap-2 rounded-full glass-strong text-amber font-heading hover:scale-105 transition-transform">
                            <Play className="h-4 w-4 fill-amber" /> Trailer
                        </button>
                    )}
                </div>

                {/* Hero content at bottom */}
                <div className="absolute bottom-0 inset-x-0 px-5 pb-8">
                    <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                        <DetailSignals card={movie.card} />
                        <div className="flex flex-wrap gap-1.5 mb-3">
                            {movie.genres.slice(0, 4).map((g) => (
                                <span key={g} className="text-[10px] uppercase tracking-wider bg-white/12 backdrop-blur px-2.5 py-1 rounded-full">{g}</span>
                            ))}
                        </div>
                        <h1 className="font-display text-5xl leading-[0.95] mb-3">{movie.title}</h1>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-300 mb-4">
                            <span className="flex items-center gap-1"><Star className="w-4 h-4 fill-amber text-amber" />{movie.rating?.toFixed(1)}</span>
                            <Bullet />
                            <span>{movie.year}</span>
                            <Bullet />
                            {isTv ? (
                                <span className="flex items-center gap-1"><Tv2 className="w-3.5 h-3.5" /> {movie.seasons?.length || 1} seasons</span>
                            ) : (
                                <span>{movie.runtime} min</span>
                            )}
                            {totalHours && isTv && (<><Bullet /><span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> ~{totalHours}h total</span></>)}
                        </div>
                        <div className="flex gap-3">
                            <button
                                onClick={() => act(isSaved ? "unsave" : "save")}
                                data-testid="detail-save-btn"
                                className={`flex-1 py-3.5 rounded-2xl font-heading flex items-center justify-center gap-2 ${
                                    isSaved ? "bg-amber text-obsidian amber-glow" : "glass-strong text-white"
                                }`}
                            >
                                <Heart className={`w-4 h-4 ${isSaved ? "fill-obsidian" : ""}`} />
                                {isSaved ? "Saved" : "Save"}
                            </button>
                            <button
                                onClick={() => act("watched")}
                                data-testid="detail-watched-btn"
                                className={`flex-1 py-3.5 rounded-2xl font-heading flex items-center justify-center gap-2 ${
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
                <p className="text-base text-zinc-300 leading-relaxed">{movie.overview}</p>

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
                {(movie.available_on || []).length === 0 ? (
                    <p className="text-sm text-zinc-500">Not currently streaming in your region.</p>
                ) : (
                    <div className="space-y-2">
                        {movie.available_on.map((sid) => {
                            const s = servicesById[sid];
                            if (!s) return null;
                            return (
                                <button key={sid}
                                    onClick={async () => {
                                        try {
                                            const { url } = await apiPost("/affiliate/click", { movie_id: id, service_id: sid });
                                            window.open(url, "_blank", "noopener,noreferrer");
                                        } catch {
                                            window.open(s.affiliate_url, "_blank", "noopener,noreferrer");
                                        }
                                    }}
                                    data-testid={`watch-on-${sid}`}
                                    className="w-full flex items-center justify-between glass rounded-xl px-4 py-3 hover:bg-white/[0.06] text-left">
                                    <div className="flex items-center gap-3">
                                        <div className="w-9 h-9 rounded-lg" style={{ backgroundColor: s.logo_color }} />
                                        <div>
                                            <div className="font-heading text-sm">{s.name}</div>
                                            <div className="text-[10px] text-zinc-500">${s.price_monthly}/mo</div>
                                        </div>
                                    </div>
                                    <ExternalLink className="h-4 w-4 text-zinc-400" />
                                </button>
                            );
                        })}
                    </div>
                )}

                {((movie.rent_on || []).length + (movie.buy_on || []).length) > 0 && (
                    <>
                        <h3 className="font-heading text-base mt-6 mb-3">Rent or buy</h3>
                        <div className="flex flex-wrap gap-2">
                            {(movie.rent_on || []).map((p) => (
                                <span key={`r-${p}`} className="text-xs px-3 py-1.5 rounded-full glass" data-testid={`rent-${p}`}>Rent · {p}</span>
                            ))}
                            {(movie.buy_on || []).map((p) => (
                                <span key={`b-${p}`} className="text-xs px-3 py-1.5 rounded-full glass" data-testid={`buy-${p}`}>Buy · {p}</span>
                            ))}
                        </div>
                    </>
                )}

                {/* Reviews */}
                <ReviewsBlock movieId={id} reviews={reviews} onPosted={(r) => setReviews(r)} />

                {/* Similar */}
                {similar.length > 0 && (
                    <div className="mt-10" data-testid="similar-rail">
                        <h3 className="font-heading text-base mb-3">More like this</h3>
                        <div className="flex gap-3 overflow-x-auto no-scrollbar -mx-1 px-1">
                            {similar.map((m) => (
                                <button key={m.id} onClick={() => navigate(`/movie/${m.id}`)}
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
        </div>
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

