import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Heart, Eye, Star, Sparkles, Play, ExternalLink } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

export default function MovieDetail() {
    const { id } = useParams();
    const navigate = useNavigate();
    const { user, refresh } = useAuth();
    const [movie, setMovie] = useState(null);
    const [services, setServices] = useState([]);
    const [explanation, setExplanation] = useState("");
    const [explainLoading, setExplainLoading] = useState(false);
    const [trailerOpen, setTrailerOpen] = useState(false);

    useEffect(() => {
        apiGet(`/movies/${id}`).then(setMovie).catch(() => navigate("/discover"));
        apiGet("/services").then(setServices);
    }, [id, navigate]);

    const isSaved = user?.saved?.includes(id);
    const isWatched = user?.watched?.includes(id);

    const act = async (action) => {
        try {
            await apiPost("/user/action", { movie_id: id, action });
            await refresh();
            toast.success(
                action === "save" ? "Saved to watchlist" :
                action === "watched" ? "Marked watched" : "Removed"
            );
        } catch {
            toast.error("Couldn't update");
        }
    };

    const explain = async () => {
        setExplainLoading(true);
        try {
            const r = await apiPost("/recommendations/explain", { movie_id: id });
            setExplanation(r.explanation);
        } catch {
            toast.error("Couldn't generate insight");
        } finally {
            setExplainLoading(false);
        }
    };

    if (!movie) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }

    const servicesById = Object.fromEntries(services.map((s) => [s.id, s]));

    return (
        <div className="min-h-screen pb-28" data-testid="movie-detail-page">
            <div className="relative aspect-[3/4] max-h-[70vh]">
                <img
                    src={movie.backdrop_url || movie.poster_url}
                    alt={movie.title}
                    className="absolute inset-0 w-full h-full object-cover"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/60 to-obsidian/20" />
                <button
                    onClick={() => navigate(-1)}
                    data-testid="back-btn"
                    className="absolute top-6 left-5 h-10 w-10 grid place-items-center rounded-full glass-strong"
                    aria-label="back"
                >
                    <ArrowLeft className="h-5 w-5" />
                </button>

                {movie.trailer_youtube_id && (
                    <button
                        onClick={() => setTrailerOpen(true)}
                        data-testid="play-trailer-btn"
                        className="absolute right-5 top-6 h-12 w-12 rounded-full glass-strong grid place-items-center text-amber hover:scale-105 transition-transform"
                        aria-label="play trailer"
                    >
                        <Play className="h-5 w-5 fill-amber" />
                    </button>
                )}
            </div>

            <div className="px-5 -mt-24 relative max-w-md mx-auto">
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                    <div className="flex flex-wrap gap-1.5 mb-3">
                        {movie.genres.map((g) => (
                            <span key={g} className="text-[10px] uppercase tracking-wider bg-white/10 backdrop-blur px-2.5 py-1 rounded-full">
                                {g}
                            </span>
                        ))}
                    </div>
                    <h1 className="font-display text-4xl leading-[1.05]">{movie.title}</h1>
                    <div className="flex items-center gap-3 text-sm text-zinc-300 mt-2">
                        <span className="flex items-center gap-1">
                            <Star className="w-4 h-4 fill-amber text-amber" />
                            {movie.rating?.toFixed(1)}
                        </span>
                        <span>•</span>
                        <span>{movie.year}</span>
                        <span>•</span>
                        <span>{movie.runtime} min</span>
                        <span>•</span>
                        <span className="capitalize">{movie.type}</span>
                    </div>

                    <p className="text-base text-zinc-300 leading-relaxed mt-5">{movie.overview}</p>

                    <div className="grid grid-cols-2 gap-3 mt-6">
                        <button
                            onClick={() => act(isSaved ? "unsave" : "save")}
                            data-testid="detail-save-btn"
                            className={`py-3.5 rounded-2xl font-heading flex items-center justify-center gap-2 transition-colors ${
                                isSaved
                                    ? "bg-amber text-obsidian amber-glow"
                                    : "border border-white/12 hover:bg-white/5"
                            }`}
                        >
                            <Heart className={`w-4 h-4 ${isSaved ? "fill-obsidian" : ""}`} />
                            {isSaved ? "Saved" : "Save"}
                        </button>
                        <button
                            onClick={() => act("watched")}
                            data-testid="detail-watched-btn"
                            className={`py-3.5 rounded-2xl font-heading flex items-center justify-center gap-2 transition-colors ${
                                isWatched
                                    ? "bg-white/10 border border-white/15"
                                    : "border border-white/12 hover:bg-white/5"
                            }`}
                        >
                            <Eye className="w-4 h-4" /> {isWatched ? "Watched" : "Mark watched"}
                        </button>
                    </div>

                    <button
                        onClick={explain}
                        disabled={explainLoading || !!explanation}
                        data-testid="explain-btn"
                        className="mt-3 w-full glass rounded-2xl p-4 flex items-start gap-3 text-left disabled:opacity-100"
                    >
                        <div className="h-9 w-9 rounded-xl bg-amber/15 grid place-items-center shrink-0">
                            <Sparkles className="w-4 h-4 text-amber" />
                        </div>
                        <div className="flex-1">
                            <div className="font-heading text-sm mb-1">Why you'll love this</div>
                            <p className="text-sm text-zinc-400 leading-relaxed">
                                {explainLoading
                                    ? "Thinking…"
                                    : explanation || "Tap to get a personal take based on your taste."}
                            </p>
                        </div>
                    </button>

                    <h3 className="font-heading text-base mt-8 mb-3">Where to watch</h3>
                    <div className="space-y-2">
                        {(movie.available_on || []).map((sid) => {
                            const s = servicesById[sid];
                            if (!s) return null;
                            return (
                                <a
                                    key={sid}
                                    href={s.affiliate_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    data-testid={`watch-on-${sid}`}
                                    className="flex items-center justify-between glass rounded-xl px-4 py-3 hover:bg-white/[0.06] transition-colors"
                                >
                                    <div className="flex items-center gap-3">
                                        <div className="w-9 h-9 rounded-lg" style={{ backgroundColor: s.logo_color }} />
                                        <div>
                                            <div className="font-heading text-sm">{s.name}</div>
                                            <div className="text-[10px] text-zinc-500">${s.price_monthly}/mo</div>
                                        </div>
                                    </div>
                                    <ExternalLink className="h-4 w-4 text-zinc-400" />
                                </a>
                            );
                        })}
                    </div>
                </motion.div>
            </div>

            <Dialog open={trailerOpen} onOpenChange={setTrailerOpen}>
                <DialogContent className="bg-obsidian border-white/10 max-w-3xl p-0 overflow-hidden">
                    <DialogTitle className="sr-only">{movie.title} trailer</DialogTitle>
                    {trailerOpen && (
                        <div className="aspect-video">
                            <iframe
                                title="trailer"
                                width="100%"
                                height="100%"
                                src={`https://www.youtube.com/embed/${movie.trailer_youtube_id}?autoplay=1`}
                                frameBorder="0"
                                allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
                                allowFullScreen
                            />
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}
