---
name: Analytics query privacy
description: Privacy boundary between prohibited search text and safe derived search metrics.
---

Analytics must reject full search queries and other free-text search fields, but it may retain derived, non-reversible metrics such as query-length buckets and result counts.

**Why:** A broad key matcher for `query` also removed canonical `query_length_bucket`, degrading analytics without improving privacy. Raw text is sensitive; coarse aggregates are the intended contract.

**How to apply:** When adding or changing analytics sanitizers, block `query`, `search_query`, `search_text`, and `search_term` specifically. Add safe derived metrics explicitly and keep cross-client contract tests for them.