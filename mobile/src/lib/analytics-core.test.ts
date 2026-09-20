import assert from "node:assert/strict";
import test from "node:test";

import {
  AnalyticsIdentityAdapter,
  cleanAnalyticsValue,
  shouldCaptureOperation,
  shouldCaptureSessionExpiry,
  switchAnalyticsIdentity,
} from "./analytics-core";
import {
  afterSuccessfulMutation,
  captureLogoutAndReset,
  deleteAccountWithAnalytics,
} from "./analytics-flow";

test("mobile sanitizer rejects identity, tokens, titles, reviews, and raw queries", () => {
  assert.deepEqual(cleanAnalyticsValue({
    content_id: "42",
    email: "person@example.test",
    display_name: "Person",
    title_name: "Private title",
    review_text: "Private review",
    search_query: "full query",
    query_length_bucket: "6-10",
    nested: { refreshToken: "secret", media_type: "movie" },
  }), {
    content_id: "42",
    query_length_bucket: "6-10",
    nested: { media_type: "movie" },
  });
});

test("mobile account switching resets before identifying the new account", () => {
  const calls: string[] = [];
  const state = { identifiedId: "account-a" };
  const adapter: AnalyticsIdentityAdapter = {
    getDistinctId: () => "account-a",
    reset: () => calls.push("reset"),
    identify: (id) => calls.push(`identify:${id}`),
  };
  switchAnalyticsIdentity(state, adapter, "account-b", {});
  assert.deepEqual(calls, ["reset", "identify:account-b"]);
});

test("mobile first login resets a different persisted account", () => {
  const calls: string[] = [];
  const state = { identifiedId: null };
  const adapter: AnalyticsIdentityAdapter = {
    getDistinctId: () => "account-a",
    reset: () => calls.push("reset"),
    identify: (id) => calls.push(`identify:${id}`),
  };
  switchAnalyticsIdentity(state, adapter, "account-b", {});
  assert.deepEqual(calls, ["reset", "identify:account-b"]);
});

test("mobile operation dedupe covers retries and rapid taps", () => {
  const recent = new Map<string, number>();
  assert.equal(shouldCaptureOperation(recent, "save:42", 10_000, 1_500), true);
  assert.equal(shouldCaptureOperation(recent, "save:42", 10_100, 1_500), false);
  assert.equal(shouldCaptureOperation(recent, "save:42", 11_501, 1_500), true);
});

test("mobile concurrent session expiry reports once per expiry window", () => {
  const state = { sentAt: 0 };
  assert.equal(shouldCaptureSessionExpiry(state, 10_000), true);
  assert.equal(shouldCaptureSessionExpiry(state, 10_001), false);
  assert.equal(shouldCaptureSessionExpiry(state, 40_000), true);
});

test("production success orchestration never reports a failed optimistic mutation", async () => {
  let captures = 0;
  await assert.rejects(afterSuccessfulMutation(
    async () => { throw new Error("network"); },
    () => { captures += 1; }
  ));
  assert.equal(captures, 0);
  await afterSuccessfulMutation(async () => "ok", () => { captures += 1; });
  assert.equal(captures, 1);
});

test("production mobile logout captures before resetting identity", () => {
  const calls: string[] = [];
  captureLogoutAndReset({
    EVENTS: { LOGOUT: "logout" },
    capture: (event) => calls.push(`capture:${event}`),
    reset: () => calls.push("reset"),
  }, { user_id: "account-a" });
  assert.deepEqual(calls, ["capture:logout", "reset"]);
});

test("production account deletion reports only after success and then logs out", async () => {
  const calls: string[] = [];
  const client = {
    EVENTS: { LOGOUT: "logout", ACCOUNT_DELETED: "account_deleted" },
    capture: (event: string) => calls.push(`capture:${event}`),
    reset: () => calls.push("reset"),
  };
  await assert.rejects(deleteAccountWithAnalytics(
    async () => { throw new Error("delete failed"); },
    client,
    { user_id: "account-a" },
    async () => { calls.push("logout"); }
  ));
  assert.equal(calls.length, 0);
  await deleteAccountWithAnalytics(
    async () => undefined,
    client,
    { user_id: "account-a" },
    async () => { calls.push("logout"); }
  );
  assert.deepEqual(calls, ["capture:account_deleted", "logout"]);
});