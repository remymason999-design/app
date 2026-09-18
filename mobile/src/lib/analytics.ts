/**
 * Privacy-safe product analytics contract shared with the web client.
 * Analytics is optional and deliberately fire-and-forget: a missing key,
 * unavailable SDK, or network failure must never affect product behavior.
 */
import PostHog from "posthog-react-native";
import * as SecureStore from "expo-secure-store";
import Constants from "expo-constants";
import { Platform } from "react-native";
import {
  cleanAnalyticsValue,
  identifyAnalyticsUser,
  resetAnalyticsIdentity,
  shouldCaptureOperation,
  shouldCaptureSessionExpiry,
  switchAnalyticsIdentity,
} from "./analytics-core";

export const EVENTS = {
  ACCOUNT_CREATED: "account_created",
  LOGIN: "login",
  LOGOUT: "logout",
  SESSION_EXPIRED: "session_expired",
  ACCOUNT_DELETED: "account_deleted",
  APP_OPENED: "app_opened",
  SCREEN_VIEWED: "screen_viewed",
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
  WATCHED_FEEDBACK_CANCELLED: "watched_feedback_cancelled",
  TITLE_DETAILS_VIEWED: "title_details_viewed",
  SIMILAR_TITLE_SELECTED: "similar_title_selected",
  PROVIDER_SELECTED: "provider_selected",
  SHARE_STARTED: "share_started",
  SEARCH_PERFORMED: "search_performed",
  SEARCH_RESULT_SELECTED: "search_result_selected",
  SEARCH_NO_RESULTS: "search_no_results",
  WATCHLIST_ITEM_ADDED: "watchlist_item_added",
  WATCHLIST_ITEM_REMOVED: "watchlist_item_removed",
  WATCHLIST_ITEM_OPENED: "watchlist_item_opened",
  WATCHLIST_PROGRESS_UPDATED: "watchlist_progress_updated",
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
  FIRST_DISCOVER_ACTION: "first_discover_action",
  TUTORIAL_COMPLETED: "tutorial_completed",
  FEED_LOADED: "feed_loaded",
  DISCOVER_REVERSED: "discover_action_reversed",
  DETAIL_OPENED: "detail_opened",
  TRAILER_OPENED: "trailer_opened",
  SEARCH_SUBMITTED: "search_submitted",
  WATCHLIST_VIEWED: "watchlist_viewed",
  FRIEND_REMOVED: "friend_removed",
  PROVIDER_CHANGED: "provider_changed",
  FILTER_CHANGED: "filter_changed",
  TITLE_TRAILER_OPENED: "title_trailer_opened",
} as const;

type User = { user_id?: string; id?: string; is_internal?: boolean; is_test_account?: boolean; analytics_internal?: boolean } | null | undefined;
type Props = Record<string, unknown>;

const key = process.env.EXPO_PUBLIC_POSTHOG_KEY;
const host = process.env.EXPO_PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com";
const environment = process.env.EXPO_PUBLIC_ANALYTICS_ENV || (__DEV__ ? "development" : "production");
let client: PostHog | null = null;
const identityState = { identifiedId: null as string | null };
const recent = new Map<string, number>();
const firstActionInFlight = new Set<string>();
const firstActionMemory = new Set<string>();
const sessionExpiryState = { sentAt: 0 };

function safe(fn: () => unknown): void {
  try { void fn(); } catch { /* analytics must never affect the app */ }
}

function props(input: Props, user?: User): Props {
  const base: Record<string, unknown> = {
    ...input,
    environment,
    platform: "mobile",
    app_version: Constants.expoConfig?.version,
    build_number: Constants.expoConfig?.ios?.buildNumber,
  };
  if (user) {
    base.internal_or_test = Boolean(user.is_internal || user.is_test_account || user.analytics_internal);
  }
  return cleanAnalyticsValue(base) as Props;
}

export function sanitizeAnalyticsProperties(value: unknown): unknown {
  return cleanAnalyticsValue(value);
}

export function privacySafeBeforeSend(event: any): any {
  if (!event || event.event !== "$exception") return event;
  const original = event.properties || {};
  const exceptionList = Array.isArray(original.$exception_list)
    ? original.$exception_list.slice(0, 5).map((item: any) => ({
        type: typeof item?.type === "string" ? item.type.slice(0, 120) : "Error",
        value: "[redacted]",
        mechanism: cleanAnalyticsValue(item?.mechanism),
      }))
    : [{ type: "Error", value: "[redacted]" }];
  // Preserve only ingestion/session metadata plus non-sensitive app context.
  const allowedKeys = [
    "token", "distinct_id", "$device_id", "$session_id", "$window_id",
    "$lib", "$lib_version", "$os_name", "$os_version", "$app_version",
    "$app_build", "$app_namespace",
  ];
  const properties: Record<string, unknown> = {};
  for (const propertyKey of allowedKeys) {
    if (original[propertyKey] !== undefined) properties[propertyKey] = original[propertyKey];
  }
  properties.$exception_list = exceptionList;
  properties.environment = environment;
  properties.platform = "mobile";
  properties.app_version = Constants.expoConfig?.version;
  properties.build_number = Constants.expoConfig?.ios?.buildNumber;
  return { ...event, properties };
}

export function initAnalytics(): boolean {
  if (!key || client) return Boolean(client);
  try {
    client = new PostHog(key, {
      host,
      // Explicitly disable automatic collection; only our safe taxonomy is sent.
      captureAppLifecycleEvents: false,
      before_send: privacySafeBeforeSend,
      errorTracking: {
        autocapture: {
          uncaughtExceptions: true,
          unhandledRejections: true,
          console: false,
          nativeCrashes: false,
        },
        exceptionSteps: { enabled: false },
      },
    });
    return true;
  } catch {
    client = null;
    return false;
  }
}

export function interactionBucket(count: number): string {
  if (count <= 5) return "0-5";
  if (count <= 10) return "6-10";
  if (count <= 25) return "11-25";
  if (count <= 50) return "26-50";
  if (count <= 100) return "51-100";
  if (count <= 200) return "101-200";
  return "200+";
}

export function appOpened(user?: User): void {
  capture(EVENTS.APP_OPENED, {}, { user, dedupeKey: "app_opened", allowDuplicate: true });
}

export function isFeatureEnabled(flag: string, fallback = false): boolean {
  if (!client) return fallback;
  try { return client.isFeatureEnabled(flag) ?? fallback; } catch { return fallback; }
}
export function getFeatureFlag(flag: string, fallback?: unknown): unknown {
  if (!client) return fallback;
  try { return client.getFeatureFlag(flag) ?? fallback; } catch { return fallback; }
}
export function reloadFeatureFlags(): void { safe(() => client?.reloadFeatureFlags()); }
export function onFeatureFlags(callback: () => void): () => void {
  if (!client) return () => {};
  try { return client.onFeatureFlags(callback); } catch { return () => {}; }
}

export function capture(event: string, input: Props = {}, options: { user?: User; dedupeKey?: string; allowDuplicate?: boolean; windowMs?: number } = {}): void {
  if (!client || !event) return;
  const payload = props(input, options.user);
  const dedupeKey = options.dedupeKey || `${event}:${JSON.stringify(payload)}`;
  const now = Date.now();
  if (!shouldCaptureOperation(recent, dedupeKey, now, options.windowMs || 1500, options.allowDuplicate)) return;
  safe(() => client?.capture(event, payload as any));
}

export function identify(user: User): void {
  const id = user?.user_id || user?.id;
  if (!client || !id) return;
  const stableId = String(id);
  safe(() => identifyAnalyticsUser(identityState, {
    identify: (nextId, properties) => client?.identify(nextId, properties as any),
    reset: () => client?.reset(),
  }, stableId, props({}, user)));
}

/** Reset any persisted/in-memory prior identity before identifying this account. */
export function switchIdentity(user: User): void {
  const id = user?.user_id || user?.id;
  if (!client || !id) return;
  const stableId = String(id);
  safe(() => switchAnalyticsIdentity(identityState, {
    getDistinctId: () => client?.getDistinctId() || null,
    identify: (nextId, properties) => client?.identify(nextId, properties as any),
    reset: () => client?.reset(),
  }, stableId, props({}, user)));
}

export function reset(): void {
  recent.clear();
  if (!client) return;
  safe(() => resetAnalyticsIdentity(identityState, { reset: () => client?.reset() }));
}

export function sessionExpired(user?: User): void {
  const now = Date.now();
  if (!shouldCaptureSessionExpiry(sessionExpiryState, now)) return;
  capture(EVENTS.SESSION_EXPIRED, {}, { user, allowDuplicate: true });
}

export function markFirstDiscoverAction(user?: User): void {
  const id = String(user?.user_id || user?.id || "anonymous");
  if (firstActionMemory.has(id) || firstActionInFlight.has(id)) return;
  firstActionInFlight.add(id);
  // SecureStore keys are restricted to [A-Za-z0-9._-]; hash the stable ID
  // rather than persisting any raw identifier in a storage key.
  let hash = 2166136261;
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const marker = `ws_analytics_first_discover_action_${(hash >>> 0).toString(16)}`;
  void (async () => {
    let already = firstActionMemory.has(id);
    try {
      if (!already) already = (await SecureStore.getItemAsync(marker)) === "1";
      if (already) {
        firstActionMemory.add(id);
        return;
      }
      await SecureStore.setItemAsync(marker, "1");
      firstActionMemory.add(id);
      capture(EVENTS.FIRST_DISCOVER_ACTION, {}, { user, allowDuplicate: true });
    } catch {
      // Fall back to a process-local marker if secure storage is unavailable.
      if (!firstActionMemory.has(id)) {
        firstActionMemory.add(id);
        capture(EVENTS.FIRST_DISCOVER_ACTION, {}, { user, allowDuplicate: true });
      }
    } finally {
      firstActionInFlight.delete(id);
    }
  })();
}

export const analytics = {
  capture,
  identify,
  switchIdentity,
  reset,
  sessionExpired,
  appOpened,
  isFeatureEnabled,
  getFeatureFlag,
  reloadFeatureFlags,
  onFeatureFlags,
  interactionBucket,
  init: initAnalytics,
  markFirstDiscoverAction,
  EVENTS,
  platform: Platform.OS,
};