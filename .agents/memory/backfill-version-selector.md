---
name: Backfill version selector traps
description: MongoDB $ne misses absent fields; broad except masks real bugs. Both caused a months-long silent backfill no-op.
---

## Rule 1: `$ne` does NOT match absent fields

When using a version-based backfill selector like `{"metadata_version": {"$ne": 4}}`, documents where the field is **entirely absent** are **not matched**. In a catalog where the field was never set (all 5,538 docs), the selector matched zero documents and the backfill silently no-op'd.

**Correct pattern:**
```python
{
    "tmdb_id": {"$exists": True},
    "$or": [
        {"metadata_version": {"$exists": False}},   # fresh imports
        {"metadata_version": {"$ne": _METADATA_VERSION}},  # stale
    ],
}
```

**Why:** MongoDB's `$ne` only evaluates against documents where the field exists. `$exists: False` is required to catch the first-time case.

## Rule 2: `except Exception: pass` masks real bugs

The backfill update block used a bare `except Exception: pass` around the update logic. When `SEARCH_ENRICH_VERSION` was referenced but never defined, every single update crashed with `AttributeError` — but was silently swallowed. The backfill reported "0 titles updated" with no error, making the bug invisible.

**Correct pattern:**
```python
try:
    ...
except Exception as e:
    logger.warning(f"Backfill update failed for {doc['id']}: {e}")
```

At minimum, log the exception. Even better, narrow the exception type to what you actually expect (e.g., `pymongo.errors.PyMongoError`).

## How to apply

- Any versioned backfill or migration selector must include `$exists: False` in an `$or`
- Any `except` in a data pipeline must log, not swallow silently
- After adding a new field to a backfill payload, verify the variable actually exists before relying on it