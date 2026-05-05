import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Heart, Star } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { motion } from "framer-motion";
import { toast } from "sonner";
import AccountMenu from "@/components/AccountMenu";

export default function Watchlist() {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        setLoading(true);
        try {
            setItems(await apiGet("/watchlist"));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
    }, []);

    const remove = async (movie_id) => {
        await apiPost("/user/action", { movie_id, action: "unsave" });
        setItems((it) => it.filter((m) => m.id !== movie_id));
        toast("Removed from watchlist");
    };

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="watchlist-page">
            <div className="flex items-start justify-between mb-8">
                <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Saved for later</p>
                    <h1 className="font-display text-4xl mt-2">Your Watchlist</h1>
                </div>
                <AccountMenu />
            </div>

            {loading ? (
                <div className="grid place-items-center py-20">
                    <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
                </div>
            ) : items.length === 0 ? (
                <div className="text-center py-20">
                    <div className="w-16 h-16 rounded-2xl bg-amber/15 grid place-items-center mx-auto mb-4">
                        <Heart className="w-7 h-7 text-amber" strokeWidth={1.6} />
                    </div>
                    <h3 className="font-heading text-xl mb-2">Nothing saved yet</h3>
                    <p className="text-sm text-zinc-400 mb-6">Swipe right on Discover to save titles for later.</p>
                    <Link to="/discover" className="inline-block px-5 py-3 rounded-xl bg-amber text-obsidian font-heading">
                        Start swiping
                    </Link>
                </div>
            ) : (
                <ul className="grid grid-cols-2 gap-3">
                    {items.map((m, i) => (
                        <motion.li
                            key={m.id}
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.04 }}
                            data-testid={`watchlist-item-${m.id}`}
                        >
                            <Link to={`/movie/${m.id}`} className="block relative aspect-[2/3] rounded-2xl overflow-hidden card-shadow">
                                <img loading="lazy" src={m.poster_url} alt={m.title} className="absolute inset-0 w-full h-full object-cover" />
                                <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/30 to-transparent" />
                                <div className="absolute bottom-0 inset-x-0 p-3">
                                    <div className="font-heading text-sm leading-tight line-clamp-2">{m.title}</div>
                                    <div className="flex items-center gap-1 text-xs text-zinc-300 mt-1">
                                        <Star className="w-3 h-3 fill-amber text-amber" />
                                        {m.rating?.toFixed(1)}
                                    </div>
                                </div>
                            </Link>
                            <button
                                onClick={() => remove(m.id)}
                                className="mt-2 w-full text-xs text-zinc-500 hover:text-amber"
                                data-testid={`watchlist-remove-${m.id}`}
                            >
                                Remove
                            </button>
                        </motion.li>
                    ))}
                </ul>
            )}
        </div>
    );
}
