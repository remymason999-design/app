import './_group.css';
import { Heart, X, Eye, Info, Star, Sparkles, Search, SlidersHorizontal, TrendingUp, Calendar, MapPin, Bell, ChevronLeft, ChevronRight } from "lucide-react";

const MOCK_USER = { name: "George", subscriptions: ["netflix","prime_video"], country: "GB" };

const MOCK_MOVIE = {
  id: "tmdb_movie_123",
  title: "The Dark Knight",
  poster_url: "https://image.tmdb.org/t/p/w780/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
  rating: 9.0,
  year: 2008,
  runtime: 152,
  type: "movie",
  genres: ["Action", "Crime", "Drama"],
  overview: "When the menace known as the Joker wreaks havoc and chaos on the people of Gotham, Batman must accept one of the greatest psychological and physical tests of his ability to fight injustice.",
  available_on: ["netflix","prime_video"],
  card: { tone: "dark", audience_type: "adult", confidence_score: 0.95 },
  reason: "Dark Thriller — similar tone to The Batman"
};

const MOCK_MOVIE2 = {
  id: "tmdb_movie_456",
  title: "Blade Runner 2049",
  poster_url: "https://image.tmdb.org/t/p/w780/gajva2L0rPYkEWjzgFlBXCAVBE5.jpg",
  rating: 8.0,
  year: 2017,
  runtime: 164,
  type: "movie",
  genres: ["Sci-Fi", "Drama", "Action"],
  overview: "Young Blade Runner K's discovery of a long-buried secret leads him to track down former Blade Runner Rick Deckard, who's been missing for thirty years.",
  available_on: ["netflix"],
  card: { tone: "dark", audience_type: "adult", confidence_score: 0.91 },
  reason: "Matches your interest in epic fantasy stories"
};

const TABS = [
  { id: "for-you", label: "For you", icon: Sparkles },
  { id: "trending", label: "Trending", icon: TrendingUp },
  { id: "upcoming", label: "Upcoming", icon: Calendar },
  { id: "local", label: "Popular in GB", icon: MapPin },
];

const initial = (MOCK_USER.name || "?").slice(0, 1).toUpperCase();

function ProviderBadge({ name }: { name: string }) {
  const colors: Record<string, string> = {
    netflix: "#E50914",
    prime_video: "#00A8E1",
    disney_plus: "#113CCF",
    hbo_max: "#991BF5",
    apple_tv: "#000000",
  };
  return (
    <span className="h-7 w-7 rounded-lg flex items-center justify-center text-[8px] font-bold text-white"
      style={{ background: colors[name] || "#555" }}>
      {name.slice(0,2).toUpperCase()}
    </span>
  );
}

function Card({ movie }: { movie: typeof MOCK_MOVIE }) {
  return (
    <div className="absolute inset-0 rounded-3xl overflow-hidden card-shadow">
      <img src={movie.poster_url} alt={movie.title} className="absolute inset-0 w-full h-full object-cover" draggable={false} />
      <div className="absolute inset-0 bg-gradient-to-t from-[#060608] via-[#060608]/65 to-transparent" />

      {/* Recommendation Banner */}
      {movie.reason && (
        <div className="absolute top-5 left-5 right-5 flex items-center gap-2 glass-strong rounded-full pl-3 pr-4 py-1.5 max-w-fit">
          <Sparkles className="w-3.5 h-3.5 text-amber shrink-0" strokeWidth={2} />
          <span className="text-[11px] tracking-wide text-zinc-200 truncate">{movie.reason}</span>
        </div>
      )}

      <div className="absolute bottom-0 inset-x-0 p-6">
        {/* Card signals */}
        <div className="flex items-center gap-1.5 mb-2.5">
          <span className="text-[10px] uppercase tracking-[0.18em] px-2 py-0.5 rounded-full border bg-red-500/15 text-red-300 border-red-500/30">Dark</span>
          <span className="text-[10px] uppercase tracking-[0.18em] px-2 py-0.5 rounded-full border border-white/15 text-zinc-200 bg-white/5">Adult</span>
          <span className="text-[10px] tracking-wider px-1.5 py-0.5 rounded-full text-emerald-300/90 bg-emerald-500/8 border border-emerald-500/20">✓</span>
        </div>

        {/* Genres */}
        <div className="flex flex-wrap gap-1.5 mb-3">
          {movie.genres.slice(0, 3).map((g) => (
            <span key={g} className="text-[10px] uppercase tracking-wider bg-white/10 backdrop-blur px-2.5 py-1 rounded-full text-zinc-200">{g}</span>
          ))}
        </div>

        {/* Title */}
        <h2 className="font-display text-3xl leading-tight mb-2">{movie.title}</h2>

        {/* Meta */}
        <div className="flex items-center gap-3 text-sm text-zinc-300 mb-3">
          <span className="flex items-center gap-1"><Star className="w-4 h-4 fill-amber text-amber" />{movie.rating.toFixed(1)}</span>
          <span>•</span><span>{movie.year}</span>
          <span>•</span><span className="capitalize">{movie.runtime} min</span>
        </div>

        {/* Overview */}
        <p className="text-sm text-zinc-300/90 line-clamp-2 mb-3">{movie.overview}</p>

        {/* Providers */}
        <div className="flex items-center gap-1.5">
          {movie.available_on.map((sid) => (
            <ProviderBadge key={sid} name={sid} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ActionBtn({ icon: Icon, label, ring, color, glow, small }: { icon: any; label: string; ring: string; color: string; glow?: boolean; small?: boolean }) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <button className={`relative ${small ? "h-12 w-12" : "h-16 w-16"} rounded-full border-2 ${ring} ${color} bg-[#08080a]/80 backdrop-blur grid place-items-center hover:scale-105 active:scale-95 transition-transform ${glow ? "amber-glow" : ""}`}>
        <Icon className={small ? "h-5 w-5" : "h-6 w-6"} strokeWidth={1.8} />
      </button>
      <span className={`text-[10px] uppercase tracking-wider ${color === "text-amber" ? "text-amber" : "text-zinc-500"}`}>{label}</span>
    </div>
  );
}

export function Current() {
  return (
    <div className="min-h-screen bg-[#060608] text-[#f8f8f8] font-['Satoshi'] max-w-[390px] mx-auto relative pb-28">
      {/* Header */}
      <header className="flex items-start justify-between mb-3 gap-3 px-5 pt-5">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Hi {MOCK_USER.name.split(" ")[0]}</p>
          <h1 className="font-display text-3xl leading-tight truncate">For you tonight</h1>
        </div>
        <div className="flex items-center gap-2">
          <button className="h-11 w-11 rounded-full glass grid place-items-center hover:bg-white/[0.06]">
            <Search className="w-5 h-5 text-zinc-200" strokeWidth={1.7} />
          </button>
          <button className="h-11 w-11 rounded-full glass grid place-items-center hover:bg-white/[0.06] relative">
            <Bell className="w-5 h-5 text-zinc-200" strokeWidth={1.7} />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-amber" />
          </button>
          <button className="h-11 w-11 rounded-full bg-amber flex items-center justify-center text-obsidian font-display text-lg hover:scale-105 active:scale-95 transition-transform amber-glow">
            {initial}
          </button>
        </div>
      </header>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar -mx-1 px-5 mb-3">
        {TABS.map((t) => {
          const I = t.icon;
          const active = t.id === "for-you";
          return (
            <button key={t.id} className={`flex items-center gap-1.5 px-3.5 py-2 rounded-full text-sm whitespace-nowrap transition-colors border ${active ? "bg-amber border-amber text-[#060608] font-heading" : "border-white/10 text-zinc-300 hover:bg-white/5"}`}>
              <I className="w-3.5 h-3.5" strokeWidth={1.8} />
              {t.label}
            </button>
          );
        })}
        <button className="ml-1 h-9 w-9 rounded-full grid place-items-center border border-white/10 text-zinc-300 hover:bg-white/5">
          <SlidersHorizontal className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Card area */}
      <div className="relative mx-5" style={{ height: "58vh" }}>
        {/* Background card */}
        <div className="absolute inset-0 rounded-3xl overflow-hidden card-shadow" style={{ transform: "translateY(12px) scale(0.96)", opacity: 0.85, zIndex: 8 }}>
          <img src={MOCK_MOVIE2.poster_url} alt="" className="absolute inset-0 w-full h-full object-cover" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#060608] via-[#060608]/65 to-transparent" />
        </div>
        {/* Top card */}
        <div className="absolute inset-0 z-10" style={{ transform: "translateY(0px) scale(1)", opacity: 1 }}>
          <Card movie={MOCK_MOVIE} />
        </div>
      </div>

      {/* Action Buttons */}
      <div className="mt-5 flex items-center justify-center gap-3">
        <ActionBtn icon={X} label="Skip" ring="border-white/10" color="text-zinc-300" />
        <ActionBtn icon={Eye} label="Watched" ring="border-white/10" color="text-zinc-300" small />
        <ActionBtn icon={Info} label="Info" ring="border-white/10" color="text-zinc-300" small />
        <ActionBtn icon={Heart} label="Save" ring="border-amber" color="text-amber" glow />
      </div>

      {/* Bottom Nav */}
      <nav className="fixed bottom-0 inset-x-0 z-40 glass-strong" style={{ paddingBottom: "env(safe-area-inset-bottom, 0)" }}>
        <ul className="max-w-md mx-auto flex justify-around items-stretch px-2 py-2">
          {[
            { label: "Discover", icon: Search, active: true },
            { label: "Watchlist", icon: Heart, active: false },
            { label: "Savings", icon: Info, active: false },
            { label: "Profile", icon: Info, active: false },
          ].map(({ label, icon: Icon, active }) => (
            <li key={label} className="flex-1">
              <button className={`flex flex-col items-center justify-center gap-1 py-2 rounded-xl transition-colors w-full ${active ? "text-amber" : "text-zinc-500 hover:text-zinc-200"}`}>
                <Icon strokeWidth={1.6} className="h-5 w-5" />
                <span className="text-[10px] tracking-wide uppercase font-medium">{label}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
