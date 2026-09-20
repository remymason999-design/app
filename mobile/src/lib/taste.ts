/**
 * Presentation-only learned taste helpers.
 *
 * Affinity values are intentionally never returned to the screen. We use
 * log-scaled relative bars so a single extreme signal cannot flatten every
 * other preference, and broad labels avoid false precision.
 */
export interface TasteRow {
  genre: string;
  barPercent: number;
  strength: "Strong match" | "Good match" | "Moderate match" | "Exploring";
  relative: number;
}

interface TasteEntry {
  genre: string;
  score: number;
  selected: boolean;
}

export function onboardingAffinityDecay(postOnboardingInteractions = 0): number {
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
}: {
  genreWeights?: unknown;
  onboardingGenreWeights?: unknown;
  onboardingDecay?: number;
  selectedGenres?: unknown;
  maxRows?: number;
} = {}): TasteRow[] {
  const byGenre = new Map<string, TasteEntry>();
  const addWeights = (input: unknown, multiplier: number) => {
    const weights =
      input && typeof input === "object" && !Array.isArray(input)
        ? (input as Record<string, unknown>)
        : {};
    Object.entries(weights).forEach(([genre, value]) => {
      const label = String(genre || "").trim();
      const score = Number(value) * multiplier;
      if (!label || !Number.isFinite(score)) return;
      const key = label.toLowerCase();
      const previous = byGenre.get(key);
      const combined = (previous?.score ?? 0) + score;
      if (!Number.isFinite(combined)) return;
      // Preserve signed totals until row selection. A negative later signal
      // must cancel an earlier positive one rather than being dropped.
      byGenre.set(key, {
        genre: previous?.genre ?? label,
        score: combined,
        selected: previous?.selected ?? false,
      });
    });
  };
  addWeights(genreWeights, 1);
  addWeights(
    onboardingGenreWeights,
    Number.isFinite(onboardingDecay) ? onboardingDecay : 1
  );

  const picked = Array.isArray(selectedGenres) ? selectedGenres : [];
  picked.forEach((value) => {
    const label = String(value || "").trim();
    if (!label) return;
    const key = label.toLowerCase();
    const existing = byGenre.get(key);
    if (existing) existing.selected = true;
    else byGenre.set(key, { genre: label, score: 0, selected: true });
  });

  const rows = [...byGenre.values()].sort(
    (a, b) => b.score - a.score || a.genre.localeCompare(b.genre)
  );
  const selectedRows = rows.filter((row) => row.selected);
  const otherPositiveRows = rows.filter(
    (row) => !row.selected && row.score > 0
  );
  const visible = [...selectedRows, ...otherPositiveRows].slice(
    0,
    Math.max(maxRows, selectedRows.length)
  ).sort((a, b) => b.score - a.score || a.genre.localeCompare(b.genre));
  const maxTransformed = Math.max(
    ...visible.map((row) => Math.log1p(Math.max(0, row.score))),
    0
  );

  return visible.map((row) => {
    const transformed = Math.log1p(Math.max(0, row.score));
    const relative = maxTransformed > 0 ? transformed / maxTransformed : 0;
    const strength: TasteRow["strength"] =
      relative >= 0.78
        ? "Strong match"
        : relative >= 0.56
          ? "Good match"
          : relative >= 0.34
            ? "Moderate match"
            : "Exploring";

    return {
      genre: row.genre,
      barPercent: maxTransformed > 0 ? Math.round(28 + relative * 72) : 28,
      strength,
      relative: Number(relative.toFixed(3)),
    };
  });
}