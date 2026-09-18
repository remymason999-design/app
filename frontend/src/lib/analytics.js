/**
 * Privacy-safe product analytics contract.
 *
 * This is deliberately the only module UI code uses for PostHog.  It keeps
 * event names/properties compatible with the native client and makes analytics
 * completely optional: a blocked/unconfigured analytics SDK can never affect
 * authentication, navigation, or mutations.
 */
import posthog from "posthog-js";

export const EVENTS = Object.freeze({
    APP_OPENED: "app_opened",
    SCREEN_VIEWED: "screen_viewed",
    ACCOUNT_CREATED: "account_created",
    LOGIN: "login",
    LOGOUT: "logout",
    SESSION_EXPIRED: "session_expired",
    ACCOUNT_DELETED: "account_deleted",
    ONBOARDING_STARTED: "onboarding_started",
    ONBOARDING_STEP_COMPLETED: "onboarding_step_completed",
    ONBOARDING_TITLE_FEEDBACK: "onboarding_title_feedback",
    ONBOARDING_PROGRESS: "onboarding_progress",
    PREFERENCES_SELECTED: "preferences_selected",
    ONBOARDING_RATING: "onboarding_rating",
    ONBOARDING_COMPLETED: "onboarding_completed",
    RECOMMENDATION_IMPRESSION: "recommendation_impression",
    RECOMMENDATION_SAVED: "recommendation_saved",
    RECOMMENDATION_SKIPPED: "recommendation_skipped",
    RECOMMENDATION_WATCHED: "recommendation_watched",
    RECOMMENDATION_REWOUND: "recommendation_rewound",
    WATCHED_FEEDBACK_SUBMITTED: "watched_feedback_submitted",
    TUTORIAL_COMPLETED: "tutorial_completed",
    FEED_LOADED: "feed_loaded",
    TITLE_DETAILS_VIEWED: "title_details_viewed",
    TITLE_TRAILER_OPENED: "title_trailer_opened",
    SIMILAR_TITLE_SELECTED: "similar_title_selected",
    PROVIDER_SELECTED: "provider_selected",
    SHARE_STARTED: "share_started",
    SEARCH_PERFORMED: "search_performed",
    SEARCH_RESULT_SELECTED: "search_result_selected",
    SEARCH_NO_RESULTS: "search_no_results",
    WATCHLIST_VIEWED: "watchlist_viewed",
    WATCHLIST_ITEM_ADDED: "watchlist_item_added",
    WATCHLIST_ITEM_REMOVED: "watchlist_item_removed",
    WATCHLIST_ITEM_OPENED: "watchlist_item_opened",
    FRIENDS_SCREEN_VIEWED: "friends_screen_viewed",
    FRIEND_CODE_SHARED: "friend_code_shared",
    FRIEND_REQUEST_SENT: "friend_request_sent",
    FRIEND_REQUEST_ACCEPTED: "friend_request_accepted",
    FRIEND_COMPARE_OPENED: "friend_compare_opened",
    FRIEND_COMPARE_TAB_VIEWED: "friend_compare_tab_viewed",
    FRIEND_OVERLAP_ITEM_OPENED: "friend_overlap_item_opened",
    SAVINGS_SCREEN_VIEWED: "savings_screen_viewed",
    SAVINGS_RECOMMENDATION_VIEWED: "savings_recommendation_viewed",
    SAVINGS_ACTION_STARTED: "savings_action_started",
    PROVIDER_PREFERENCES_VIEWED: "provider_preferences_viewed",
    PROVIDER_ADDED: "provider_added",
    PROVIDER_REMOVED: "provider_removed",
    FILTER_CHANGED: "filter_changed",
    FIRST_DISCOVER_ACTION: "first_discover_action",
    WATCHED_FEEDBACK_CANCELLED: "watched_feedback_cancelled",
    WATCHLIST_PROGRESS_UPDATED: "watchlist_progress_updated",
    DISCOVER_REVERSED: "discover_action_reversed",
    DETAIL_OPENED: "detail_opened",
    TRAILER_OPENED: "trailer_opened",
    SEARCH_SUBMITTED: "search_submitted",
    FRIEND_REMOVED: "friend_removed",
    PROVIDER_CHANGED: "provider_changed",
});

const KEY = process.env.REACT_APP_POSTHOG_KEY;
const ENV = process.env.REACT_APP_ANALYTICS_ENV || process.env.NODE_ENV || "development";
const APP_VERSION = process.env.REACT_APP_VERSION || "web";
const BUILD_NUMBER = process.env.REACT_APP_BUILD_NUMBER || process.env.REACT_APP_BUILD_SHA || "unknown";
let ready = false;
const recent = new Map();
let sessionExpiredSent = false;
const ANON_FIRST_ACTION_KEY = "ws_analytics_first_discover_action_anonymous";
let activeIdentity = null;
const BLOCKED_PROPERTY_KEYS = /^(?:email|.*_email|name|display_name|user_name|full_name|first_name|last_name|title|title_.*|.*_title|query|search_(?:text|term|query)|review|review_text|message|password|.*_password|.*token|authorization)$/i;

function safe(fn) {
    try { return fn(); } catch { return undefined; }
}

function clean(value, depth = 0) {
    if (depth > 2 || value == null) return undefined;
    if (typeof value === "string") return value.slice(0, 120);
    if (typeof value === "number" || typeof value === "boolean") return value;
    if (Array.isArray(value)) return value.slice(0, 20).map((v) => clean(v, depth + 1)).filter((v) => v !== undefined);
    if (typeof value === "object") {
        return Object.fromEntries(Object.entries(value).filter(([key]) => !BLOCKED_PROPERTY_KEYS.test(key)).slice(0, 30)
            .map(([k, v]) => [k, clean(v, depth + 1)])
            .filter(([, v]) => v !== undefined));
    }
    return undefined;
}

export function sanitizeAnalyticsProperties(value) {
    return clean(value);
}

export function shouldCaptureVisiblePresentation(previousKey, nextKey, visible) {
    return Boolean(visible && nextKey && previousKey !== nextKey);
}

export function shouldResetIdentity(activeId, persistedId, nextId) {
    const next = nextId == null ? null : String(nextId);
    return Boolean(next && ((activeId && String(activeId) !== next)
        || (!activeId && persistedId && String(persistedId) !== next)));
}

function base(props, user) {
    return clean({
        ...props,
        environment: ENV,
        platform: "web",
        app_version: APP_VERSION,
        build_number: BUILD_NUMBER,
        // Anonymous events omit this user-scoped property instead of
        // asserting that an unavailable user is definitely non-internal.
        ...(user ? {
            internal_or_test: Boolean(user.is_internal || user.is_test_account || user.analytics_internal),
        } : {}),
    });
}

export function initAnalytics(analyticsKey = KEY) {
    if (!analyticsKey) return false;
    try {
        posthog.init(analyticsKey, {
            api_host: process.env.REACT_APP_POSTHOG_HOST || "https://eu.i.posthog.com",
            person_profiles: "identified_only",
            capture_pageview: false,
            capture_pageleave: false,
            disable_session_recording: true,
            autocapture: false,
        });
        ready = true;
    } catch { ready = false; }
    return ready;
}

export function capture(event, props = {}, options = {}) {
    if (!ready || !event) return;
    if (event === EVENTS.SESSION_EXPIRED && sessionExpiredSent) return;
    const payload = base(props, options.user);
    const dedupeKey = options.dedupeKey || `${event}:${JSON.stringify(payload)}`;
    const now = Date.now();
    if (!options.allowDuplicate && now - (recent.get(dedupeKey) || 0) < (options.windowMs || 1500)) return;
    recent.set(dedupeKey, now);
    safe(() => posthog.capture(event, payload));
    if (event === EVENTS.SESSION_EXPIRED) sessionExpiredSent = true;
}

export function identify(user) {
    const id = user?.user_id || user?.id;
    if (!ready || !id) return;
    sessionExpiredSent = false;
    activeIdentity = String(id);
    safe(() => posthog.identify(String(id), base({
        internal_or_test: Boolean(user?.is_internal || user?.is_test_account || user?.analytics_internal),
    }, user)));
}

export function reset() {
    // Keep the dedupe window across an identity reset so repeated 401s do not
    // inflate session-expiry counts. Per-user first-action markers are never
    // deleted; only the anonymous fallback is safe to clear.
    safe(() => sessionStorage.removeItem(ANON_FIRST_ACTION_KEY));
    activeIdentity = null;
    if (!ready) return;
    safe(() => posthog.reset());
}

/** Switch accounts without ever attributing the new account to the old one. */
export function switchIdentity(user) {
    const id = user?.user_id || user?.id;
    if (!id) return;
    const persistedIdentity = safe(() => posthog.get_distinct_id?.());
    if (shouldResetIdentity(activeIdentity, persistedIdentity, id)) {
        reset();
    }
    identify(user);
}

export function markFirstDiscoverAction(user) {
    let first = false;
    const id = user?.user_id || user?.id;
    const key = id
        ? `ws_analytics_first_discover_action_${String(id)}`
        : ANON_FIRST_ACTION_KEY;
    safe(() => {
        const storage = id ? localStorage : sessionStorage;
        if (!storage.getItem(key)) {
            storage.setItem(key, "1");
            first = true;
        }
    });
    if (first) capture(EVENTS.FIRST_DISCOVER_ACTION, {}, { user, allowDuplicate: true });
}

export function interactionBucket(count) {
    const n = Number(count) || 0;
    if (n <= 5) return "0-5";
    if (n <= 10) return "6-10";
    if (n <= 25) return "11-25";
    if (n <= 50) return "26-50";
    if (n <= 100) return "51-100";
    if (n <= 200) return "101-200";
    return "200+";
}

export function isFeatureEnabled(key, fallback = false) { return ready ? (safe(() => posthog.isFeatureEnabled(key)) ?? fallback) : fallback; }
export function getFeatureFlag(key, fallback = null) { return ready ? (safe(() => posthog.getFeatureFlag(key)) ?? fallback) : fallback; }
export function reloadFeatureFlags() { return ready && posthog.reloadFeatureFlags ? safe(() => posthog.reloadFeatureFlags()) : Promise.resolve(); }
export function onFeatureFlags(callback) {
    if (!ready || typeof callback !== "function") return () => {};
    return safe(() => posthog.onFeatureFlags(callback)) || (() => {});
}

export const analytics = { capture, identify, switchIdentity, reset, init: initAnalytics, EVENTS, interactionBucket, isFeatureEnabled, getFeatureFlag, reloadFeatureFlags, onFeatureFlags };