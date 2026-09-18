export type AnalyticsIdentityState = { identifiedId: string | null };

export type AnalyticsIdentityAdapter = {
  getDistinctId: () => string | null;
  identify: (id: string, properties: Record<string, unknown>) => void;
  reset: () => void;
};

const BLOCKED_PROPERTY_KEYS = /^(?:email|.*_email|name|display_name|user_name|full_name|first_name|last_name|title|title_.*|.*_title|query|search_(?:text|term|query)|review|review_text|message|password|.*_password|.*token|authorization)$/i;

export function cleanAnalyticsValue(value: unknown, depth = 0): unknown {
  if (depth > 2 || value == null) return undefined;
  if (typeof value === "string") return value.slice(0, 120);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) {
    return value.slice(0, 20)
      .map((item) => cleanAnalyticsValue(item, depth + 1))
      .filter((item) => item !== undefined);
  }
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !BLOCKED_PROPERTY_KEYS.test(key))
      .slice(0, 30)
      .map(([key, item]) => [key, cleanAnalyticsValue(item, depth + 1)])
      .filter(([, item]) => item !== undefined));
  }
  return undefined;
}

export function resetAnalyticsIdentity(
  state: AnalyticsIdentityState,
  adapter: Pick<AnalyticsIdentityAdapter, "reset">
): void {
  state.identifiedId = null;
  adapter.reset();
}

export function identifyAnalyticsUser(
  state: AnalyticsIdentityState,
  adapter: Pick<AnalyticsIdentityAdapter, "identify" | "reset">,
  id: string,
  properties: Record<string, unknown>
): void {
  if (state.identifiedId !== id) {
    if (state.identifiedId) adapter.reset();
    state.identifiedId = id;
  }
  adapter.identify(id, properties);
}

export function switchAnalyticsIdentity(
  state: AnalyticsIdentityState,
  adapter: AnalyticsIdentityAdapter,
  id: string,
  properties: Record<string, unknown>
): void {
  const persistedId = adapter.getDistinctId();
  if ((state.identifiedId && state.identifiedId !== id)
    || (!state.identifiedId && persistedId && persistedId !== id)) {
    resetAnalyticsIdentity(state, adapter);
  }
  identifyAnalyticsUser(state, adapter, id, properties);
}

export function shouldCaptureOperation(
  recent: Map<string, number>,
  key: string,
  now: number,
  windowMs: number,
  allowDuplicate = false
): boolean {
  if (!allowDuplicate && now - (recent.get(key) || 0) < windowMs) return false;
  recent.set(key, now);
  return true;
}

export function shouldCaptureSessionExpiry(
  state: { sentAt: number },
  now: number,
  windowMs = 30_000
): boolean {
  if (state.sentAt > 0 && now - state.sentAt < windowMs) return false;
  state.sentAt = now;
  return true;
}