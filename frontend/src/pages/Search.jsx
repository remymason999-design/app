import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Search as SearchIcon, ArrowLeft, Sparkles, Star } from "lucide-react";
import { apiGet } from "@/lib/api";

export default function Search() {
    const navigate = useNavigate();
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [fallback, setFallback] = useState(false);
    const [loading, setLoading] = useState(false);
    const inputRef = useRef(null);
    const debounce = useRef(null);

    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    useEffect(() => {
        if (debounce.current) clearTimeout(debounce.current);
        if (!q.trim()) { setResults([]); setFallback(false); return; }
        debounce.current = setTimeout(async () => {
            setLoading(true);
            try {
                const r = await apiGet(`/search?q=${encodeURIComponent(q)}`);
                setResults(r.results || []);
                setFallback(Boolean(r.fallback));
            } finally {
                setLoading(false);
            }
        }, 350);
        return () => clearTimeout(debounce.current);
    }, [q]);

    return (
        <div className="min-h-screen pb-28 max-w-md mx-auto" data-testid="search-page">
            <div className="sticky top-0 z-10 glass-strong px-4 py-3 flex items-center gap-3">
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
                    <input
                        ref={inputRef}
                        value={q}
                        onChange={(e) => setQ(e.target.value)}
                        placeholder="Title, actor, or genre…"
                        data-testid="search-input"
                        className="w-full bg-white/5 border border-white/10 rounded-full pl-11 pr-4 py-3 text-sm focus:border-amber/60 outline-none"
                    />
                </div>
            </div>

            <div className="px-5 pt-6">
                {loading && (
                    <div className="flex items-center gap-2 text-zinc-400 text-sm">
                        <div className="h-3 w-3 rounded-full border border-amber border-t-transparent animate-spin" /> Searching…
                    </div>
                )}
                {!loading && q && results.length === 0 && (
                    <p className="text-sm text-zinc-400">No results — try a different search.</p>
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
                    {results.map((m, i) => (
                        <motion.li
                            key={m.id}
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.03 }}
                            data-testid={`search-result-${m.id}`}
                        >
                            <button
                                onClick={() => navigate(`/movie/${m.id}`)}
                                className="w-full flex gap-3 glass rounded-2xl p-3 hover:bg-white/[0.05] text-left"
                            >
                                <div className="w-16 h-24 rounded-lg overflow-hidden bg-velvet shrink-0">
                                    {m.poster_url && <img src={m.poster_url} alt={m.title} className="w-full h-full object-cover" />}
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="font-heading text-base leading-tight truncate">{m.title}</div>
                                    <div className="flex items-center gap-2 text-xs text-zinc-400 mt-1">
                                        <Star className="w-3 h-3 fill-amber text-amber" />
                                        {m.rating?.toFixed(1)} · {m.year} · {m.type === "tv" ? "TV" : "Movie"}
                                    </div>
                                    <div className="text-xs text-zinc-500 line-clamp-2 mt-1">{m.overview}</div>
                                    <div className="flex flex-wrap gap-1 mt-2">
                                        {(m.genres || []).slice(0, 3).map((g) => (
                                            <span key={g} className="text-[10px] uppercase tracking-wider bg-white/8 px-2 py-0.5 rounded-full">
                                                {g}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            </button>
                        </motion.li>
                    ))}
                </ul>
            </div>
        </div>
    );
}
