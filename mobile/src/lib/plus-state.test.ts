import assert from "node:assert/strict";
import test from "node:test";

import { plusInterestView, reconcilePlusInterest } from "./plus-state";

test("represents loading, error, retry-ready, disabled and interested states", () => {
  assert.equal(plusInterestView({ loading: true, error: false, enabled: true }), "loading");
  assert.equal(plusInterestView({ loading: false, error: true, enabled: true }), "error");
  assert.equal(plusInterestView({ loading: false, error: false, enabled: true }), "available");
  assert.equal(plusInterestView({ loading: false, error: false, enabled: false }), "disabled");
  assert.equal(
    plusInterestView({
      loading: false,
      error: false,
      enabled: true,
      interest: { enabled: true, interested: true },
    }),
    "interested"
  );
});

test("preview writes reconcile the Profile query cache in both directions", () => {
  const joined = reconcilePlusInterest(
    { enabled: true, interested: false, source_screen: "profile" },
    true
  );
  assert.deepEqual(joined, {
    enabled: true,
    interested: true,
    source_screen: "profile",
  });
  assert.equal(reconcilePlusInterest(joined, false).interested, false);
});