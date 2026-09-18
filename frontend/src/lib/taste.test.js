import { deriveTasteRows } from "./taste";

describe("deriveTasteRows", () => {
    test("accumulates signed evidence before filtering rows", () => {
        const rows = deriveTasteRows({
            genreWeights: { Drama: 3, Horror: -3, Comedy: -4 },
            onboardingGenreWeights: { Drama: -3, Horror: 4 },
            selectedGenres: ["Drama", "Horror", "Comedy"],
        });
        const byGenre = Object.fromEntries(rows.map((row) => [row.genre, row]));

        // Drama cancels to zero and Horror combines to +1 instead of allowing
        // an intermediate positive/negative value to disappear.
        expect(byGenre.Drama).toMatchObject({
            strength: "Exploring",
            barPercent: 28,
            relative: 0,
        });
        expect(byGenre.Horror).toMatchObject({
            strength: "Strong match",
            barPercent: 100,
            relative: 1,
        });
        expect(byGenre.Comedy).toMatchObject({
            strength: "Exploring",
            barPercent: 28,
            relative: 0,
        });
    });

    test("keeps a single extreme outlier from flattening other positive rows", () => {
        const rows = deriveTasteRows({
            genreWeights: { Niche: 1, Middle: 4, Blockbuster: 1000000 },
        });
        const byGenre = Object.fromEntries(rows.map((row) => [row.genre, row]));

        expect(byGenre.Blockbuster).toMatchObject({
            barPercent: 100,
            strength: "Strong match",
        });
        expect(byGenre.Niche.barPercent).toBeGreaterThanOrEqual(28);
        expect(byGenre.Niche.barPercent).toBeLessThan(byGenre.Blockbuster.barPercent);
        expect(byGenre.Middle.barPercent).toBeGreaterThan(byGenre.Niche.barPercent);
    });

    test("ignores non-finite weights while retaining selected genres", () => {
        const rows = deriveTasteRows({
            genreWeights: {
                Drama: NaN,
                Comedy: Infinity,
                Thriller: "not-a-number",
                Action: 2,
            },
            selectedGenres: ["Drama"],
        });

        expect(rows.map((row) => row.genre)).toEqual(["Action", "Drama"]);
        expect(rows.find((row) => row.genre === "Drama")).toMatchObject({
            strength: "Exploring",
            barPercent: 28,
        });
    });

    test("shows selected genres as Exploring without saved or watched evidence", () => {
        expect(deriveTasteRows({ selectedGenres: ["Sci-Fi"] })).toEqual([
            {
                genre: "Sci-Fi",
                barPercent: 28,
                strength: "Exploring",
                relative: 0,
            },
        ]);
    });
});