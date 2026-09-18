import { plusInterestView, reconcilePlusInterest } from "./plus-state";

describe("WatchSmart+ preview state", () => {
    test.each([
        [{ loading: true, error: false, interest: null, enabled: true }, "loading"],
        [{ loading: false, error: true, interest: null, enabled: true }, "error"],
        [{ loading: false, error: false, interest: { interested: true }, enabled: true }, "interested"],
        [{ loading: false, error: false, interest: { interested: false }, enabled: false }, "disabled"],
        [{ loading: false, error: false, interest: { interested: false }, enabled: true }, "available"],
    ])("derives %s as %s", (input, expected) => {
        expect(plusInterestView(input)).toBe(expected);
    });

    test("reconciles preview mutations with the Profile interest snapshot", () => {
        const joined = reconcilePlusInterest({ enabled: true, source_screen: "profile" }, true);
        expect(joined).toEqual({ enabled: true, source_screen: "profile", interested: true });
        expect(reconcilePlusInterest(joined, false).interested).toBe(false);
    });
});