// Error tracking (Sentry) + product analytics (PostHog).
// Both are no-ops unless their keys are provided via env, so the app runs
// fine locally and only reports once the secrets are configured.
import * as Sentry from "@sentry/react";
import { initAnalytics, capture, identify, reset } from "@/lib/analytics";

const SENTRY_DSN = process.env.REACT_APP_SENTRY_DSN;
let _posthogReady = false;

export function initObservability() {
    if (SENTRY_DSN) {
        Sentry.init({
            dsn: SENTRY_DSN,
            environment: process.env.NODE_ENV || "production",
            tracesSampleRate: 0.1,
            // Don't capture session replays by default (privacy + bundle size).
            replaysSessionSampleRate: 0,
            replaysOnErrorSampleRate: 0,
        });
    }

    _posthogReady = initAnalytics();
}

export const analytics = {
    capture,
    identify,
    reset,
};

export function isPosthogReady() {
    return _posthogReady;
}

export { Sentry };
