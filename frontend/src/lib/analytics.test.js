import {
    EVENTS,
    capture,
    identify,
    initAnalytics,
    interactionBucket,
    reset,
    sanitizeAnalyticsProperties,
    shouldCaptureVisiblePresentation,
    shouldResetIdentity,
    switchIdentity,
} from "./analytics";
import {
    afterSuccessfulMutation,
    captureLogoutAndReset,
    deleteAccountWithAnalytics,
} from "./analytics-flow";
import posthog from "posthog-js";
import fs from "fs";
import path from "path";

jest.mock("posthog-js", () => ({
    init: jest.fn(),
    capture: jest.fn(),
    identify: jest.fn(),
    reset: jest.fn(),
    get_distinct_id: jest.fn(() => null),
}));

function mobileEvents() {
    const source = fs.readFileSync(path.resolve(__dirname, "../../../mobile/src/lib/analytics.ts"), "utf8");
    const block = source.match(/export const EVENTS = \{([\s\S]*?)\}\s+as const;/)?.[1] || "";
    return Object.fromEntries([...block.matchAll(/^\s*([A-Z0-9_]+):\s*"([^"]+)"/gm)]
        .map((match) => [match[1], match[2]]));
}

describe("analytics data-quality contracts", () => {
    beforeAll(() => {
        initAnalytics("test-key");
    });

    beforeEach(() => {
        jest.clearAllMocks();
        posthog.get_distinct_id.mockReturnValue(null);
        reset();
        jest.clearAllMocks();
    });

    test("web and mobile expose the same canonical event names", () => {
        const native = mobileEvents();
        expect(new Set(Object.values(native))).toEqual(new Set(Object.values(EVENTS)));
        for (const key of Object.keys(EVENTS)) {
            if (native[key]) expect(native[key]).toBe(EVENTS[key]);
        }
    });

    test("captures only a new visible presentation", () => {
        expect(shouldCaptureVisiblePresentation(null, "card:1", false)).toBe(false);
        // Background tabs and cards obscured by an overlay both supply false.
        expect(shouldCaptureVisiblePresentation("card:0", "card:1", false)).toBe(false);
        expect(shouldCaptureVisiblePresentation(null, "card:1", true)).toBe(true);
        expect(shouldCaptureVisiblePresentation("card:1", "card:1", true)).toBe(false);
        // Losing visibility resets the caller's previous key; focus return is a
        // genuine new presentation of the same card.
        expect(shouldCaptureVisiblePresentation(null, "card:1", true)).toBe(true);
    });

    test.each([
        [0, "0-5"], [5, "0-5"], [6, "6-10"], [10, "6-10"],
        [11, "11-25"], [26, "26-50"], [51, "51-100"],
        [101, "101-200"], [201, "200+"],
    ])("buckets %i interactions as %s", (count, expected) => {
        expect(interactionBucket(count)).toBe(expected);
    });

    test("resets a persisted different account on a fresh runtime", () => {
        expect(shouldResetIdentity(null, "old-user", "new-user")).toBe(true);
        expect(shouldResetIdentity(null, "same-user", "same-user")).toBe(false);
        expect(shouldResetIdentity("old-user", "old-user", "new-user")).toBe(true);
    });

    test("rejects identity, token, title, review, and full-query properties recursively", () => {
        expect(sanitizeAnalyticsProperties({
            content_id: "123",
            email: "person@example.test",
            display_name: "Person",
            title: "A title",
            title_name: "Another title",
            search_query: "the complete search",
            review_text: "free-form opinion",
            nested: {
                access_token: "secret",
                refreshToken: "secret",
                authorization: "Bearer secret",
                media_type: "movie",
            },
        })).toEqual({
            content_id: "123",
            nested: { media_type: "movie" },
        });
    });

    test("uses only canonical analytics property names", () => {
        capture(EVENTS.SEARCH_PERFORMED, {
            query_length_bucket: "11-20",
            result_count: 3,
            search_query: "must not leave the device",
        }, { allowDuplicate: true });
        expect(posthog.capture).toHaveBeenCalledWith(EVENTS.SEARCH_PERFORMED, expect.objectContaining({
            query_length_bucket: "11-20",
            result_count: 3,
            environment: expect.any(String),
            platform: "web",
            app_version: expect.any(String),
            build_number: expect.any(String),
        }));
        expect(posthog.capture.mock.calls[0][1]).not.toHaveProperty("search_query");
    });

    test("resets before identifying a different logged-in account", () => {
        identify({ user_id: "account-a" });
        switchIdentity({ user_id: "account-b" });
        expect(posthog.reset).toHaveBeenCalledTimes(1);
        expect(posthog.reset.mock.invocationCallOrder[0])
            .toBeLessThan(posthog.identify.mock.invocationCallOrder[1]);
        expect(posthog.identify.mock.calls.map(([id]) => id)).toEqual(["account-a", "account-b"]);
    });

    test("resets a persisted account before first login in a fresh runtime", () => {
        posthog.get_distinct_id.mockReturnValue("account-a");
        switchIdentity({ user_id: "account-b" });
        expect(posthog.reset).toHaveBeenCalledTimes(1);
        expect(posthog.identify).toHaveBeenCalledWith("account-b", expect.any(Object));
    });

    test("production logout orchestration captures before identity reset", () => {
        identify({ user_id: "account-a" });
        captureLogoutAndReset({ capture, reset, EVENTS }, { user_id: "account-a" });
        expect(posthog.capture.mock.calls.map(([event]) => event)).toEqual([EVENTS.LOGOUT]);
        expect(posthog.reset).toHaveBeenCalledTimes(1);
        expect(posthog.capture.mock.invocationCallOrder[0])
            .toBeLessThan(posthog.reset.mock.invocationCallOrder[0]);
    });

    test("dedupes concurrent session expiry even after identity reset", () => {
        capture(EVENTS.SESSION_EXPIRED);
        reset();
        capture(EVENTS.SESSION_EXPIRED);
        expect(posthog.capture).toHaveBeenCalledTimes(1);
    });

    test.each([
        ["retry", EVENTS.RECOMMENDATION_SAVED, "save:retry:42"],
        ["rapid tap", EVENTS.RECOMMENDATION_SAVED, "save:rapid:42"],
        ["reversal", EVENTS.RECOMMENDATION_REWOUND, "rewind:42"],
        ["cached feed", EVENTS.RECOMMENDATION_IMPRESSION, "feed-1:42"],
    ])("dedupes %s analytics by operation key", (_case, event, dedupeKey) => {
        capture(event, { content_id: "42" }, { dedupeKey });
        capture(event, { content_id: "42" }, { dedupeKey });
        expect(posthog.capture).toHaveBeenCalledTimes(1);
    });

    test("production mutation orchestration captures only successful optimistic actions", async () => {
        await expect(afterSuccessfulMutation(
            () => Promise.reject(new Error("network")),
            () => capture(EVENTS.RECOMMENDATION_SAVED, { content_id: "42" })
        )).rejects.toThrow("network");
        expect(posthog.capture).not.toHaveBeenCalled();
        await afterSuccessfulMutation(
            () => Promise.resolve(),
            () => capture(EVENTS.RECOMMENDATION_SAVED, { content_id: "42" }, { dedupeKey: "save:optimistic:42" })
        );
        expect(posthog.capture).toHaveBeenCalledTimes(1);
    });

    test("production deletion orchestration reports success before logout", async () => {
        const order = [];
        await expect(deleteAccountWithAnalytics(
            () => Promise.reject(new Error("delete failed")),
            { capture: () => order.push("capture"), EVENTS },
            { user_id: "account-a" },
            async () => order.push("logout")
        )).rejects.toThrow("delete failed");
        expect(order).toEqual([]);

        await deleteAccountWithAnalytics(
            () => Promise.resolve(),
            { capture: () => order.push("capture"), EVENTS },
            { user_id: "account-a" },
            async () => order.push("logout")
        );
        expect(order).toEqual(["capture", "logout"]);
    });
});