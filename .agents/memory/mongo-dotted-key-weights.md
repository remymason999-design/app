---
name: Mongo dotted-key weight maps
description: Person names with dots corrupt $inc weight maps into nested dicts — always sanitize keys and harden readers.
---

# Never use raw person names as Mongo $inc keys

**Rule:** any user-taste weight map keyed by free-text names (cast/director/writer) must sanitize the key first (`person_key()` in taste.py: lowercase + strip dots/`$`), and every reader must skip non-numeric values defensively.

**Why:** Mongo interprets dots in `$inc` field paths as nesting. A save on a film with "Samuel L. Jackson" wrote `cast_weights.samuel l. jackson` → created `{"samuel l": {" jackson": 1}}`. Later profile builds hit the nested dict expecting a number and 500'd `/user/action`. The failure surfaces far from the write, on unrelated requests.

**How to apply:**
- Writers AND readers must go through the same sanitizer — a sanitized write with a raw-key read silently loses the signal (lookups in engine.py/core.py were updated too).
- Readers (`_top_keys`, `_argmax`, scoring lookups) filter `isinstance(v, (int, float))` so pre-existing corrupt docs can't crash requests.
- If corruption is suspected: scan user docs for non-numeric values in `cast_weights`/`director_weights`/`writer_weights` and drop those entries (3 dev users were repaired this way).
