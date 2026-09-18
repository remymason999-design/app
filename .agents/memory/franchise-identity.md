---
name: Franchise identity
description: How recommendation cards represent and compare TMDB movie collections.
---

Represent a movie franchise with both its stable TMDB collection ID and its display name. Use the ID for grouping, similarity, and spacing; use the name for user-facing copy. Continue accepting legacy name-only franchise values.

**Why:** Collection names can differ by locale or change over time, while the TMDB collection ID remains stable. Name-based grouping can fail to recognize sequels in the same collection.

**How to apply:** Any new collection-aware feature should compare normalized stable IDs first, fall back to normalized names only when an ID is unavailable, and avoid using the display name as the canonical identity.