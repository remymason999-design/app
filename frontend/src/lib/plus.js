import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { analytics, isPosthogReady } from "@/observability";

export const PLUS_DEFAULT_CONFIG = {
    flags: {
        plus_visible: true,
        plus_interest_enabled: true,
        subscriptions_enabled: false,
        ads_enabled: false,
        affiliate_tracking_enabled: false,
        sponsored_content_enabled: false,
    },
    entitlements: [
        "advanced_recommendations",
        "advanced_taste_insights",
        "advanced_savings",
        "advanced_friend_matching",
        "smart_alerts",
        "ad_free",
        "family_profiles",
    ],
};

export const PLUS_BENEFITS = [
    ["SMARTER DISCOVERY", "More control and insight into your personalised recommendations."],
    ["SMART SAVINGS", "Deeper insights into which streaming subscriptions you're actually using and where you could save."],
    ["WATCH TOGETHER", "Advanced matching for couples, friends and households."],
    ["TASTE INSIGHTS", "Learn more about your favourite genres, actors, directors, themes and viewing habits."],
    ["SMART ALERTS", "Get useful alerts when titles you'll probably like become available."],
    ["AD-FREE", "Future WatchSmart+ users can receive an ad-free experience if advertising is introduced to the free tier."],
];

let configCache = null;
let configCacheAt = 0;
let configRequest = null;

export async function fetchPlusConfig({ force = false } = {}) {
    const fresh = configCache && Date.now() - configCacheAt < 5 * 60 * 1000;
    if (!force && fresh) return configCache;
    if (!force && configRequest) return configRequest;
    configRequest = apiGet("/monetization/config").then((config) => {
        configCache = config;
        configCacheAt = Date.now();
        return config;
    }).finally(() => {
        configRequest = null;
    });
    return configRequest;
}

export async function fetchPlusInterest() {
    return apiGet("/monetization/plus/interest");
}

export async function addPlusInterest(source_screen = "plus_preview") {
    return apiPut("/monetization/plus/interest", { source_screen });
}

export async function removePlusInterest() {
    return apiDelete("/monetization/plus/interest");
}

export function sanitizePlusSource(source) {
    const value = String(source || "").trim().toLowerCase();
    return ["profile", "profile_card", "plus_preview", "unknown"].includes(value)
        ? value
        : "unknown";
}

function eventId() {
    try {
        if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    } catch {}
    return `plus_${Date.now()}_${Math.random().toString(36).slice(2, 18)}`;
}

/** Best-effort event delivery. Navigation and primary actions never depend on it. */
export function trackPlusEvent(event_name, source_screen = "unknown", user_id = null) {
    const props = { source_screen: sanitizePlusSource(source_screen), platform: "web" };
    if (typeof user_id === "string" && user_id) props.user_id = user_id;
    if (isPosthogReady()) {
        analytics.capture(event_name, props);
        return;
    }
    apiPost("/monetization/events", {
        event_name,
        event_id: eventId(),
        ...props,
    }).catch(() => {});
}