/**
 * Format a duration in minutes as "Xh Ym" (e.g. "1h 42m", "45m", "2h").
 * Returns null when minutes is falsy/zero.
 */
export function formatRuntime(minutes) {
    if (!minutes || minutes <= 0) return null;
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h === 0) return `${m}m`;
    if (m === 0) return `${h}h`;
    return `${h}h ${m}m`;
}

/**
 * Calculate total TV show runtime in minutes.
 * Prefers movie.total_runtime; falls back to summing season episode counts × per-ep runtime.
 */
export function calcTvTotalMinutes(movie) {
    if (movie.total_runtime && movie.total_runtime > 0) return movie.total_runtime;
    if (!movie.seasons?.length || !movie.runtime) return null;
    const totalEp = movie.seasons.reduce((s, season) => s + (season.episode_count || 0), 0);
    return totalEp > 0 ? totalEp * movie.runtime : null;
}

/**
 * Count total episodes across all seasons.
 */
export function totalEpisodes(seasons) {
    if (!seasons?.length) return null;
    const count = seasons.reduce((s, season) => s + (season.episode_count || 0), 0);
    return count > 0 ? count : null;
}
