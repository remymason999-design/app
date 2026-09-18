import Constants from "expo-constants";
import { Platform } from "react-native";

import { api } from "@/lib/api";

export interface PlusConfig {
  flags: {
    plus_visible: boolean;
    plus_interest_enabled: boolean;
    subscriptions_enabled: boolean;
    ads_enabled: boolean;
    affiliate_tracking_enabled: boolean;
    sponsored_content_enabled: boolean;
  };
  entitlements: string[];
  future_revenue_streams?: string[];
}

export interface PlusInterest {
  enabled: boolean;
  interested: boolean;
  source_screen?: string | null;
  first_interested_at?: string | null;
  latest_interested_at?: string | null;
  latest_removed_at?: string | null;
}

export const PLUS_DEFAULT_CONFIG: PlusConfig = {
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

export const PLUS_BENEFITS: readonly [string, string][] = [
  ["SMARTER DISCOVERY", "More control and insight into your personalised recommendations."],
  ["SMART SAVINGS", "Deeper insights into which streaming subscriptions you're actually using and where you could save."],
  ["WATCH TOGETHER", "Advanced matching for couples, friends and households."],
  ["TASTE INSIGHTS", "Learn more about your favourite genres, actors, directors, themes and viewing habits."],
  ["SMART ALERTS", "Get useful alerts when titles you'll probably like become available."],
  ["AD-FREE", "Future WatchSmart+ users can receive an ad-free experience if advertising is introduced to the free tier."],
];

export async function fetchPlusConfig(): Promise<PlusConfig> {
  const r = await api.get<PlusConfig>("/monetization/config");
  return r.data;
}

export async function fetchPlusInterest(): Promise<PlusInterest> {
  const r = await api.get<PlusInterest>("/monetization/plus/interest");
  return r.data;
}

export async function addPlusInterest(source_screen = "plus_preview") {
  const r = await api.put<{ interested: boolean; changed: boolean; message: string }>(
    "/monetization/plus/interest",
    { source_screen }
  );
  return r.data;
}

export async function removePlusInterest() {
  const r = await api.delete<{ interested: boolean; changed: boolean }>(
    "/monetization/plus/interest"
  );
  return r.data;
}

function eventId() {
  return `plus_${Date.now()}_${Math.random().toString(36).slice(2, 18)}`;
}

export function sanitizePlusSource(source: string | undefined) {
  const value = String(source || "").trim().toLowerCase();
  return (["profile", "profile_card", "plus_preview", "unknown"] as const).includes(
    value as "profile" | "profile_card" | "plus_preview" | "unknown"
  )
    ? value
    : "unknown";
}

/** Best effort: analytics failures must not block navigation or interest writes. */
export function trackPlusEvent(event_name: string, source_screen = "unknown") {
  api.post("/monetization/events", {
    event_name,
    event_id: eventId(),
    source_screen: sanitizePlusSource(source_screen),
    platform: Platform.OS === "ios" || Platform.OS === "android" ? Platform.OS : "web",
    app_version: Constants.expoConfig?.version ?? undefined,
  }).catch(() => {});
}