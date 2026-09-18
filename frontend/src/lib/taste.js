/**
 * Presentation helpers for learned taste.
 *
 * Recommendation affinities stay private to the engine. These helpers turn
 * them into deliberately coarse, relative UI values so profile screens never
 * expose raw scores or misleading precision.
 */
export function onboardingAffinityDecay(postOnboardingInteractions = 0) {
    const count = Math.max(0, Number(postOnboardingInteractions) || 0);
    if (count <= 20) return 1;
    if (count >= 100) return 0.25;
    return Number((1 - 0.75 * ((count - 20) / 80)).toFixed(4));
}

export function deriveTasteRows({
    genreWeights = {},
    onboardingGenreWeights = {},
    onboardingDecay = 1,
    selectedGenres = [],
    maxRows = 8,
} = {}) {
    const byGenre = new Map();

    const addWeights = (weights, multiplier) => {
        if (!weights || typeof weights !== "object" || Array.isArray(weights)) return;
        Object.entries(weights).forEach(([genre, value]) => {
            const label = String(genre || "").trim();
            const score = Number(value) * multiplier;
            if (!label || !Number.isFinite(score)) return;
            const key = label.toLowerCase();
            const previous = byGenre.get(key);
            const combined = (previous?.score || 0) + score;
            if (!Number.isFinite(combined)) return;
            // Preserve signed totals until row selection. A negative later
            // signal must be able to cancel an earlier positive one; dropping
            // non-positive intermediates makes the result order-dependent.
            byGenre.set(key, {
                genre: previous?.genre || label,
                score: combined,
                selected: previous?.selected || false,
            });
        });
    };
    addWeights(genreWeights, 1);
    addWeights(onboardingGenreWeights, Number.isFinite(Number(onboardingDecay)) ? Number(onboardingDecay) : 1);

    if (Array.isArray(selectedGenres)) {
        selectedGenres.forEach((value) => {
            const label = String(value || "").trim();
            if (!label) return;
            const key = label.toLowerCase();
            if (!byGenre.has(key)) {
                byGenre.set(key, { genre: label, score: 0, selected: true });
            } else {
                byGenre.get(key).selected = true;
            }
        });
    }

    const rows = [...byGenre.values()].sort((a, b) => b.score - a.score || a.genre.localeCompare(b.genre));
    // Keep every deliberately selected genre visible, including a selected
    // genre whose evidence is currently neutral/negative. Unselected
    // non-positive evidence is not a current recommendation signal.
    const selectedRows = rows.filter((row) => row.selected);
    const otherPositiveRows = rows.filter((row) => !row.selected && row.score > 0);
    const visible = [...selectedRows, ...otherPositiveRows]
        .slice(0, Math.max(maxRows, selectedRows.length))
        .sort((a, b) => b.score - a.score || a.genre.localeCompare(b.genre));
    const maxTransformed = Math.max(...visible.map((row) => Math.log1p(Math.max(0, row.score))), 0);

    return visible.map((row) => {
        const transformed = Math.log1p(Math.max(0, row.score));
        const relative = maxTransformed > 0 ? transformed / maxTransformed : 0;
        // Log scaling plus a floor keeps a single large affinity from making
        // every other legitimate preference look empty.
        const barPercent = maxTransformed > 0
            ? Math.round(28 + relative * 72)
            : 28;
        const strength = relative >= 0.78
            ? "Strong match"
            : relative >= 0.56
                ? "Good match"
                : relative >= 0.34
                    ? "Moderate match"
                    : "Exploring";

        return {
            genre: row.genre,
            barPercent,
            strength,
            // Useful for deterministic tests without exposing engine scores.
            relative: Number(relative.toFixed(3)),
        };
    });
}