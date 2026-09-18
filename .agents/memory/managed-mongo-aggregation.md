---
name: Managed Mongo aggregation limits
description: When to use DB aggregation vs in-Python aggregation for analytics/diagnostics endpoints
---

# Managed Mongo aggregation limits

For new analytics/diagnostics endpoints, prefer simple `find().sort().limit()` queries
plus in-Python aggregation over `db.collection.aggregate([...])` pipelines.

**Why:** the managed Mongo deployment rejects complex aggregation pipelines. Some
legacy admin endpoints get away with light `$unwind`/`$group` passes, but anything
beyond that fails in production. The personalisation/diagnostics specs explicitly
called this out, so the safe default for anything new is: pull rows, aggregate in
Python.

**How to apply:** when building a metrics/reporting endpoint, fetch the minimal
projected fields with a bounded `find(...).limit(N)` and compute counts/rates/scores
in Python. Reserve DB aggregation only for trivial single-stage `$unwind`+`$group`
that already exists and is known to work. Guard each metric section in try/except so
one failure returns null instead of crashing the whole endpoint.
