import './_group.css';
import { Heart, X, Eye, Info, Star, Sparkles, Search, SlidersHorizontal, TrendingUp, Calendar, MapPin, Bell, ChevronLeft, ChevronRight, Users, Compass } from "lucide-react";

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

      {/* Info button - top right, always visible, glass style */}
      <button className="absolute top-4 right-4 z-20 h-10 w-10 rounded-full glass grid place-items-center hover:bg-white/[0.08] transition-colors active:scale-95">
        <Info className="w-4 h-4 text-zinc-200" strokeWidth={2} />
      </button>

      {/* NO recommendation banner here - removed per spec */}

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

function NavArrow({ direction, onClick }: { direction: "left" | "right"; onClick?: () => void }) {
  const Icon = direction === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      onClick={onClick}
      className="h-12 w-12 rounded-full glass grid place-items-center hover:bg-white/[0.08] transition-colors active:scale-95"
      aria-label={direction === "left" ? "Previous card" : "Next card"}
    >
      <Icon className="w-5 h-5 text-zinc-300" strokeWidth={2} />
    </button>
  );
}

export function Refreshed() {
  return (
    <div className="min-h-screen bg-[#060608] text-[#f8f8f8] font-['Satoshi'] max-w-[390px] mx-auto relative pb-28">
      {/* Header - refined spacing, more premium */}
      <header className="flex items-center justify-between mb-4 gap-3 px-5 pt-5">
        <div className="min-w-0 flex items-center gap-2">
          {/* Logo */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] uppercase tracking-[0.3em] text-amber font-heading">WS</span>
          </div>
          <div className="w-px h-4 bg-white/10" />
          <div>
            <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-500">Hi {MOCK_USER.name.split(" ")[0]}</p>
            <h1 className="font-display text-xl leading-tight truncate">For you tonight</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className="h-10 w-10 rounded-full glass grid place-items-center hover:bg-white/[0.06]">
            <Search className="w-4 h-4 text-zinc-200" strokeWidth={1.7} />
          </button>
          <button className="h-10 w-10 rounded-full glass grid place-items-center hover:bg-white/[0.06] relative">
            <Bell className="w-4 h-4 text-zinc-200" strokeWidth={1.7} />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-amber" />
          </button>
          <button className="h-10 w-10 rounded-full bg-amber flex items-center justify-center text-[#060608] font-display text-sm hover:scale-105 active:scale-95 transition-transform amber-glow">
            {initial}
          </button>
        </div>
      </header>

      {/* Filter Tabs - improved: softer borders, better spacing, premium glow */}
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar -mx-1 px-5 mb-3">
        {TABS.map((t) => {
          const I = t.icon;
          const active = t.id === "for-you";
          return (
            <button
              key={t.id}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-full text-sm whitespace-nowrap transition-all border ${
                active
                  ? "bg-amber border-amber text-[#060608] font-heading shadow-[0_0_12px_rgba(245,158,11,0.25)]"
                  : "border-white/[0.06] text-zinc-300 hover:bg-white/[0.04] hover:border-white/10"
              }`}
            >
              <I className="w-3.5 h-3.5" strokeWidth={1.8} />
              {t.label}
            </button>
          );
        })}
        <button className="ml-1 h-9 w-9 rounded-full grid place-items-center border border-white/[0.06] text-zinc-300 hover:bg-white/[0.04] hover:border-white/10 transition-all">
          <SlidersHorizontal className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Card area + Navigation arrows */}
      <div className="flex items-center gap-2 px-3">
        {/* Previous arrow - only visible when applicable (shown here for demo) */}
        <NavArrow direction="left" />

        {/* Card stack */}
        <div className="relative flex-1" style={{ height: "58vh" }}>
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

        {/* Next arrow */}
        <NavArrow direction="right" onClick={() => {}} />
      </div>

      {/* Action Buttons */}
      <div className="mt-5 flex items-center justify-center gap-3">
        <ActionBtn icon={X} label="Skip" ring="border-white/10" color="text-zinc-300" />
        <ActionBtn icon={Eye} label="Watched" ring="border-white/10" color="text-zinc-300" small />
        <ActionBtn icon={Heart} label="Save" ring="border-amber" color="text-amber" glow />
      </div>

      {/* Bottom Nav - improved glassmorphism, new tabs: Discover/Watchlist/Savings/Friends */}
      <nav
        className="fixed bottom-0 inset-x-0 z-40"
        style={{
          paddingBottom: "env(safe-area-inset-bottom, 0)",
          background: "linear-gradient(to top, rgba(6,6,8,0.92) 0%, rgba(6,6,8,0.75) 60%, rgba(6,6,8,0) 100%)",
          backdropFilter: "blur(32px) saturate(160%)",
          WebkitBackdropFilter: "blur(32px) saturate(160%)",
          maskImage: "linear-gradient(to top, black 0%, black 75%, transparent 100%)",
          WebkitMaskImage: "linear-gradient(to top, black 0%, black 75%, transparent 100%)",
        }}
      >
        <ul className="max-w-md mx-auto flex justify-around items-stretch px-2 py-2">
          {[
            { label: "Discover", icon: Compass, active: true },
            { label: "Watchlist", icon: Heart, active: false },
            { label: "Savings", icon: Info, active: false },
            { label: "Friends", icon: Users, active: false },
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
