"""Global recommendation learning system (Task #38).

Computes cross-user aggregate metrics from impression + action logs and
surfaces them as soft ranking nudges (never hard pool filters).

Key principles from task spec:
  - Community is a supporting signal, never the main driver.
  - Sample thresholds gate every adjustment (<20 = none; 20-100 = small;
    100+ = stronger; 500+ = high confidence).
  - For existing users (>20 interactions) personal taste dominates.
  - For new users (<20 interactions) community/cluster data may matter more.
  - Catalog self-cleaning flags weak titles but does NOT hard-remove them.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pymongo import UpdateOne
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from core import db, get_catalog

logger = logging.getLogger("watchsmart.global_learning")

# ---------------------------------------------------------------------------
# Sample-threshold gating
# ---------------------------------------------------------------------------
THRESHOLD_NONE   = 20
THRESHOLD_SMALL  = 100
THRESHOLD_STRONG = 500


def _confidence_from_n(n: int) -> float:
    """Return a 0..1 confidence multiplier based on impression count."""
    if n < THRESHOLD_NONE:
        return 0.0
    if n < THRESHOLD_SMALL:
        return 0.35
    if n < THRESHOLD_STRONG:
        return 0.65
    return 1.0


# ---------------------------------------------------------------------------
# Title-level metric computation
# ---------------------------------------------------------------------------

async def compute_title_metrics(limit: int = 5000) -> dict:
    """Recompute per-title aggregate metrics from the full impression + action
    logs.  Designed for periodic batch runs (admin-triggered or scheduled).
    Returns a summary dict with counts so callers can report what happened.

    Actions are ONLY counted when they carry an impression_id, ensuring we
    never mix non-recommendation interactions into community scores.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

    # ── Impressions: load with their impression_id for exact linkage ───────────
    impressions_map: dict[str, list[dict]] = defaultdict(list)
    impression_ids: set[str] = set()
    # impression_id → set(movie_ids) — for action verification at ingest time
    impression_items_map: dict[str, set[str]] = {}
    try:
        cursor = db.impressions.find(
            {"at": {"$gte": cutoff}},
            {"_id": 0, "user_id": 1, "at": 1, "items": 1, "impression_id": 1},
        ).sort("at", -1).limit(limit)
        async for doc in cursor:
            iid = doc.get("impression_id")
            if iid:
                impression_ids.add(iid)
            else:
                # Skip impressions without an impression_id — they cannot be
                # linked to actions, so counting them would skew denominators.
                continue
            items = doc.get("items") or []
            impression_items_map[iid] = {it.get("id") for it in items if it.get("id")}
            for it in items:
                mid = it.get("id")
                if mid:
                    impressions_map[mid].append({
                        "user_id": doc.get("user_id"),
                        "at": doc.get("at"),
                        "rank": it.get("rank"),
                        "slot": it.get("slot"),
                        "reason_code": it.get("reason_code"),
                        "title": it.get("title"),
                        "impression_id": iid,
                    })
    except Exception as exc:
        logger.warning(f"compute_title_metrics impressions fetch failed: {exc}")
        return {"status": "error", "stage": "impressions_fetch", "error": str(exc)}

    # ── Actions: ONLY count actions that have an impression_id ───────────────────
    # This prevents non-recommendation interactions (search, browse, direct
    # links) from distorting community_quality_score and discovery scores.
    # We also build an (impression_id, movie_id)-level action map for EXACT
    # discovery scoring — each impression contains multiple movies, so we
    # must key by the pair to prevent actions on one title from leaking into
    # another title's discovery score.
    action_counts: dict[str, Counter] = defaultdict(Counter)
    actions_by_impression_movie: dict[tuple[str, str], Counter] = defaultdict(Counter)
    try:
        cursor = db.user_actions.find(
            {"created_at": {"$gte": cutoff}, "impression_id": {"$in": list(impression_ids)}},
            {"_id": 0, "movie_id": 1, "action": 1, "impression_id": 1},
        ).sort("created_at", -1).limit(limit * 3)
        async for doc in cursor:
            mid = doc.get("movie_id")
            act = doc.get("action")
            iid = doc.get("impression_id")
            # Verify that the impression ACTUALLY served this movie_id
            # before counting the action toward any title-level metric.
            # This prevents mismatched client payloads from poisoning
            # community scores.
            pair_valid = bool(
                iid and mid
                and iid in impression_items_map
                and mid in impression_items_map[iid]
            )
            if mid and act and pair_valid:
                action_counts[mid][act] += 1
            if iid and mid and act and pair_valid:
                actions_by_impression_movie[(iid, mid)][act] += 1
    except Exception as exc:
        logger.warning(f"compute_title_metrics actions fetch failed: {exc}")

    # Build metric docs
    catalog_by_id = {m["id"]: m for m in get_catalog()}
    now_iso = datetime.now(timezone.utc).isoformat()
    ops = []
    computed = 0
    for mid, imp_rows in impressions_map.items():
        n_imp = len(imp_rows)
        conf = _confidence_from_n(n_imp)
        if conf == 0.0:
            continue  # below threshold — skip entirely

        acts = action_counts.get(mid, Counter())
        saves   = acts.get("save", 0)
        watches = acts.get("watched", 0) + acts.get("watched_liked", 0)
        skips   = acts.get("skip", 0)
        detail_views = acts.get("detail_view", 0)
        trailer_opens = acts.get("trailer_open", 0)

        # Core engagement rate (save + watch as % of impressions seen)
        denom = max(1, n_imp)
        save_rate   = round(saves / denom, 4)
        watch_rate  = round(watches / denom, 4)
        skip_rate   = round(skips / denom, 4)

        # Title success score: weighted engagement composite
        # Saves = 1.0, watches = 0.8, detail_view = 0.2, trailer_open = 0.1
        # Skips = -0.4 (penalise but not as harshly as saves reward)
        title_success_score = round(
            (saves * 1.0 + watches * 0.8 + detail_views * 0.2 + trailer_opens * 0.1 - skips * 0.4)
            / denom,
            4,
        )
        title_success_score = max(-1.0, min(1.0, title_success_score))

        # Discovery-specific score — only for adjacent/wildcard slots
        # EXACT action-to-impression linkage: count actions whose impression_id
        # matches a discovery-slot impression for this movie_id.
        disc_imp = [r for r in imp_rows if r.get("slot") in ("adjacent", "wildcard")]
        disc_n = len(disc_imp)
        discovery_success_score = None
        if disc_n >= THRESHOLD_NONE:
            disc_denom = max(1, disc_n)
            disc_saves = 0
            disc_skips = 0
            for r in disc_imp:
                iid = r.get("impression_id")
                if iid:
                    acts = actions_by_impression_movie.get((iid, mid))
                    if acts:
                        disc_saves += acts.get("save", 0) + acts.get("watched", 0) + acts.get("watched_liked", 0)
                        disc_skips += acts.get("skip", 0)
            disc_save_rate = round(disc_saves / disc_denom, 4)
            disc_skip_rate = round(disc_skips / disc_denom, 4)
            discovery_success_score = round(
                (disc_save_rate * 1.0 - disc_skip_rate * 0.4), 4
            )
            discovery_success_score = max(-1.0, min(1.0, discovery_success_score))

        # Community quality score: how does WatchSmart engagement compare to
        # what TMDB rating would predict?
        movie = catalog_by_id.get(mid)
        tmdb_rating = float(movie.get("rating") or 0) if movie else 0.0
        vote_count  = int(movie.get("vote_count") or 0) if movie else 0
        community_quality_score = None
        if tmdb_rating > 0 and n_imp >= THRESHOLD_NONE:
            # Expected save rate from TMDB: a well-rated title (8+) should
            # have positive community engagement. Normalise rating to -1..1
            # around 7.0 (TMDB average), then compare with actual save_rate.
            expected = (tmdb_rating - 7.0) / 3.0  # ~ -0.33 to +1.0
            # More votes = more trust in TMDB rating, so less room for community
            # to diverge. Fewer votes = community signal can dominate.
            tmdb_trust = math.tanh(vote_count / 500.0)
            # Community quality = how much actual engagement exceeds TMDB-predicted
            # When TMDB is untrustworthy (low votes), community can swing wider.
            community_quality_score = round(
                (save_rate + watch_rate * 0.8 - expected) * (1.0 - 0.5 * tmdb_trust),
                4,
            )
            community_quality_score = max(-1.0, min(1.0, community_quality_score))

        # Catalog self-cleaning flag
        # High impressions + low engagement = candidate for deprioritisation
        self_cleaning_flag = False
        if n_imp >= THRESHOLD_SMALL and (save_rate + watch_rate) < 0.05 and skip_rate > 0.40:
            self_cleaning_flag = True

        doc = {
            "movie_id": mid,
            "title":    (imp_rows[0].get("title") or (movie.get("title") if movie else None)),
            "impressions": n_imp,
            "saves":       saves,
            "watches":     watches,
            "skips":       skips,
            "detail_views": detail_views,
            "trailer_opens": trailer_opens,
            "save_rate":   save_rate,
            "watch_rate":  watch_rate,
            "skip_rate":   skip_rate,
            "title_success_score":   title_success_score,
            "discovery_success_score": discovery_success_score,
            "community_quality_score": community_quality_score,
            "self_cleaning_flag":     self_cleaning_flag,
            "confidence": conf,
            "computed_at": now_iso,
        }
        ops.append(UpdateOne(
            {"movie_id": mid},
            {"$set": doc},
            upsert=True,
        ))
        computed += 1

    if ops:
        try:
            await db.title_metrics.bulk_write(ops, ordered=False)
        except Exception as exc:
            logger.warning(f"title_metrics bulk_write failed: {exc}")
            return {"status": "error", "stage": "bulk_write", "error": str(exc)}

    return {
        "status": "ok",
        "computed": computed,
        "impressions_processed": sum(len(v) for v in impressions_map.values()),
        "actions_processed": sum(sum(c.values()) for c in action_counts.values()),
        "at": now_iso,
    }


# ---------------------------------------------------------------------------
# Lightweight incremental update (called after each user action)
# ---------------------------------------------------------------------------

async def update_title_metrics(movie_id: str) -> None:
    """Lightweight incremental refresh for a single title after a user action.

    Pulls the last 90 days of data for just this title, recomputes its metrics,
    and writes a single upsert.  Only counts actions that carry an impression_id
    that matches a verified impression doc containing this movie_id.
    Non-recommendation interactions (missing impression_id or mismatched pair)
    never distort community scores.
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        n_imp = 0
        # impression_id → set(movie_ids) — verified from DB, never client-trusted
        impression_items_map: dict[str, set[str]] = {}
        imp_cursor = db.impressions.find(
            {"at": {"$gte": cutoff}, "items.id": movie_id},
            {"_id": 0, "items": 1, "impression_id": 1},
        )
        imp_rows: list[dict] = []
        async for doc in imp_cursor:
            iid = doc.get("impression_id")
            if not iid:
                continue
            impression_items_map[iid] = {it.get("id") for it in (doc.get("items") or [])}
            for it in (doc.get("items") or []):
                if it.get("id") == movie_id:
                    n_imp += 1
                    imp_rows.append({
                        "id": it.get("id"),
                        "rank": it.get("rank"),
                        "slot": it.get("slot"),
                        "reason_code": it.get("reason_code"),
                        "title": it.get("title"),
                        "impression_id": iid,
                    })

        conf = _confidence_from_n(n_imp)
        if conf == 0.0:
            await db.title_metrics.delete_one({"movie_id": movie_id})
            return

        # Use ONLY DB-verified impression IDs — never accept a client-provided
        # impression_id without a matching DB impression doc.
        valid_impression_ids = set(impression_items_map.keys())

        # Fetch actions with exact impression linkage.
        # Only count actions whose impression_id is in the verified set AND
        # whose impression doc actually contains this movie_id.
        acts = Counter()
        actions_by_impression: dict[str, Counter] = defaultdict(Counter)
        act_cursor = db.user_actions.find(
            {
                "created_at": {"$gte": cutoff},
                "movie_id": movie_id,
                "impression_id": {"$in": list(valid_impression_ids)},
            },
            {"_id": 0, "action": 1, "impression_id": 1},
        )
        async for doc in act_cursor:
            a = doc.get("action")
            iid = doc.get("impression_id")
            if a and iid and iid in valid_impression_ids:
                # Verify impression served this movie_id (strict DB-only guard)
                if movie_id in impression_items_map.get(iid, set()):
                    acts[a] += 1
                    actions_by_impression[iid][a] += 1

        saves   = acts.get("save", 0)
        watches = acts.get("watched", 0) + acts.get("watched_liked", 0)
        skips   = acts.get("skip", 0)
        detail_views  = acts.get("detail_view", 0)
        trailer_opens = acts.get("trailer_open", 0)

        denom = max(1, n_imp)
        save_rate  = round(saves / denom, 4)
        watch_rate = round(watches / denom, 4)
        skip_rate  = round(skips / denom, 4)

        title_success_score = round(
            (saves * 1.0 + watches * 0.8 + detail_views * 0.2 + trailer_opens * 0.1 - skips * 0.4)
            / denom,
            4,
        )
        title_success_score = max(-1.0, min(1.0, title_success_score))

        # Discovery score — exact impression-level action linkage
        # We count only actions whose impression_id matches a discovery-slot
        # impression for this movie.  No proportional approximation.
        disc_imp = [r for r in imp_rows if r.get("slot") in ("adjacent", "wildcard")]
        disc_n = len(disc_imp)
        discovery_success_score = None
        if disc_n >= THRESHOLD_NONE:
            disc_denom = max(1, disc_n)
            disc_saves = 0
            disc_skips = 0
            for r in disc_imp:
                iid = r.get("impression_id")
                if iid and iid in actions_by_impression:
                    a = actions_by_impression[iid]
                    disc_saves += a.get("save", 0) + a.get("watched", 0) + a.get("watched_liked", 0)
                    disc_skips += a.get("skip", 0)
            disc_save_rate = round(disc_saves / disc_denom, 4)
            disc_skip_rate = round(disc_skips / disc_denom, 4)
            discovery_success_score = round(
                (disc_save_rate * 1.0 - disc_skip_rate * 0.4), 4
            )
            discovery_success_score = max(-1.0, min(1.0, discovery_success_score))

        # Community quality
        catalog_by_id = {m["id"]: m for m in get_catalog()}
        movie = catalog_by_id.get(movie_id)
        tmdb_rating = float(movie.get("rating") or 0) if movie else 0.0
        vote_count = int(movie.get("vote_count") or 0) if movie else 0
        community_quality_score = None
        if tmdb_rating > 0 and n_imp >= THRESHOLD_NONE:
            expected = (tmdb_rating - 7.0) / 3.0
            tmdb_trust = math.tanh(vote_count / 500.0)
            community_quality_score = round(
                (save_rate + watch_rate * 0.8 - expected) * (1.0 - 0.5 * tmdb_trust),
                4,
            )
            community_quality_score = max(-1.0, min(1.0, community_quality_score))

        self_cleaning_flag = (
            n_imp >= THRESHOLD_SMALL and (save_rate + watch_rate) < 0.05 and skip_rate > 0.40
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        await db.title_metrics.update_one(
            {"movie_id": movie_id},
            {"$set": {
                "movie_id": movie_id,
                "title": (imp_rows[0].get("title") if imp_rows else (movie.get("title") if movie else None)),
                "impressions": n_imp,
                "saves": saves,
                "watches": watches,
                "skips": skips,
                "detail_views": detail_views,
                "trailer_opens": trailer_opens,
                "save_rate": save_rate,
                "watch_rate": watch_rate,
                "skip_rate": skip_rate,
                "title_success_score": title_success_score,
                "discovery_success_score": discovery_success_score,
                "community_quality_score": community_quality_score,
                "self_cleaning_flag": self_cleaning_flag,
                "confidence": conf,
                "computed_at": now_iso,
            }},
            upsert=True,
        )
    except Exception as exc:
        logger.debug(f"update_title_metrics({movie_id}) failed: {exc}")


def schedule_update_title_metrics(movie_id: str) -> None:
    """Fire-and-forget wrapper for update_title_metrics."""
    if not movie_id:
        return
    try:
        asyncio.create_task(update_title_metrics(movie_id))
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Taste clusters
# ---------------------------------------------------------------------------

async def build_taste_clusters() -> dict:
    """Assign users to anonymous taste clusters and compute cluster-level success.

    Clusters are defined by dominant genre patterns (e.g. crime/thriller/prestige,
    action/blockbuster, drama/awards, sci-fi/mystery).  Assignment is probabilistic
    based on the user's top 3 genre weights.

    Returns a summary dict.
    """
    # Cluster definitions — named by their expected genre fingerprint
    CLUSTER_DEFS = {
        "crime_thriller_prestige": {"Crime", "Thriller", "Mystery"},
        "action_blockbuster":      {"Action", "Adventure", "Sci-Fi"},
        "drama_awards":            {"Drama", "Biography", "History"},
        "scifi_mystery":           {"Sci-Fi", "Mystery", "Fantasy"},
        "comedy_light":            {"Comedy", "Romance", "Family"},
        "horror_dark":             {"Horror", "Thriller", "War"},
        "documentary_niche":       {"Documentary", "Music", "Sport"},
    }

    # Gather all users with genre_weights
    user_genres: dict[str, dict[str, float]] = {}
    try:
        cursor = db.users.find(
            {"genre_weights": {"$exists": True, "$ne": {}}},
            {"_id": 0, "user_id": 1, "genre_weights": 1, "saved": 1},
        )
        async for u in cursor:
            gw = u.get("genre_weights") or {}
            if gw:
                user_genres[u["user_id"]] = gw
    except Exception as exc:
        logger.warning(f"build_taste_clusters user fetch failed: {exc}")
        return {"status": "error", "stage": "user_fetch", "error": str(exc)}

    # Probabilistic cluster assignment: users can have partial membership
    # across multiple clusters based on genre-overlap similarity.  We draw
    # one primary cluster per user using weighted probability (softmax over
    # overlaps) so edge cases get natural blending rather than hard cutoffs.
    cluster_assignments: dict[str, list[str]] = {k: [] for k in CLUSTER_DEFS}
    for uid, gw in user_genres.items():
        top3 = sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_genres = {g for g, _ in top3}
        # Compute overlap scores for every cluster
        overlaps = []
        for cname, cgenres in CLUSTER_DEFS.items():
            score = len(top_genres & cgenres)
            if score > 0:
                overlaps.append((cname, score))
        if not overlaps:
            continue
        # Softmax sampling: higher overlap = higher probability
        max_score = max(s for _, s in overlaps)
        exp_scores = [(c, math.exp(s - max_score)) for c, s in overlaps]
        total = sum(e for _, e in exp_scores)
        probs = [(c, e / total) for c, e in exp_scores]
        # Deterministic draw using a stable SHA-256 digest of the user_id
        # (never Python's randomized hash) so cluster assignments survive
        # restarts, deploys, and interpreter process changes.
        _seed_hex = hashlib.sha256(uid.encode()).hexdigest()[:8]
        _draw = int(_seed_hex, 16) / 0xFFFFFFFF  # normalised to 0..1
        _cum = 0.0
        chosen = probs[0][0]
        for c, p in probs:
            _cum += p
            if _draw <= _cum:
                chosen = c
                break
        cluster_assignments[chosen].append(uid)

    # Per-cluster top saved titles (the titles this cluster likes)
    # Only count recommendation-linked actions (have impression_id) to avoid
    # conflating browse/search clicks with feed-driven engagement.
    now_iso = datetime.now(timezone.utc).isoformat()
    cluster_docs = []
    for cname, uids in cluster_assignments.items():
        if not uids:
            continue
        title_counter: Counter = Counter()
        cursor = db.user_actions.find(
            {
                "user_id": {"$in": uids},
                "action": {"$in": ["save", "watched"]},
                "impression_id": {"$exists": True},
            },
            {"_id": 0, "movie_id": 1},
        )
        async for doc in cursor:
            mid = doc.get("movie_id")
            if mid:
                title_counter[mid] += 1

        top_titles = [
            {"movie_id": mid, "wins": cnt}
            for mid, cnt in title_counter.most_common(20)
        ]

        cluster_docs.append({
            "cluster_id": cname,
            "user_count": len(uids),
            "top_titles": top_titles,
            "updated_at": now_iso,
        })

    if cluster_docs:
        ops = [
            UpdateOne(
                {"cluster_id": d["cluster_id"]},
                {"$set": d},
                upsert=True,
            )
            for d in cluster_docs
        ]
        try:
            await db.taste_clusters.bulk_write(ops, ordered=False)
        except Exception as exc:
            logger.warning(f"taste_clusters bulk_write failed: {exc}")

    return {
        "status": "ok",
        "clusters": {k: len(v) for k, v in cluster_assignments.items()},
        "total_users": len(user_genres),
        "at": now_iso,
    }


# ---------------------------------------------------------------------------
# New-user success boost
# ---------------------------------------------------------------------------

async def new_user_community_boost(
    movie_id: str,
    user: dict,
    *,
    base_score: float = 0.0,
) -> float:
    """Return a community-derived score bonus for a title when recommending
    to a user with little personal history (<20 interactions).

    The bonus blends:
      - overall community success for this title
      - cluster-level success if the user can be assigned to a cluster
    """
    interactions = (
        len(user.get("saved") or [])
        + len(user.get("watched") or [])
        + len(user.get("skipped") or [])
        + len(user.get("onboarding_rated") or [])
    )
    if interactions >= 20:
        return 0.0  # personal taste dominates — no community override

    # Fetch title metrics
    metrics = await db.title_metrics.find_one({"movie_id": movie_id})
    if not metrics:
        return 0.0

    conf = metrics.get("confidence") or 0.0
    if conf == 0.0:
        return 0.0

    tss = metrics.get("title_success_score") or 0.0
    # Scale community score down for users with some history (10-19 interactions)
    # so the transition from community → personal is gradual.
    fade = max(0.0, 1.0 - interactions / 20.0)

    # Cluster-specific bonus
    cluster_bonus = 0.0
    gw = user.get("genre_weights") or {}
    if gw:
        top3 = sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_genres = {g for g, _ in top3}
        # Find which cluster this user's top genres map to
        CLUSTER_DEFS = {
            "crime_thriller_prestige": {"Crime", "Thriller", "Mystery"},
            "action_blockbuster":      {"Action", "Adventure", "Sci-Fi"},
            "drama_awards":            {"Drama", "Biography", "History"},
            "scifi_mystery":           {"Sci-Fi", "Mystery", "Fantasy"},
            "comedy_light":            {"Comedy", "Romance", "Family"},
            "horror_dark":             {"Horror", "Thriller", "War"},
            "documentary_niche":       {"Documentary", "Music", "Sport"},
        }
        best_cluster = None
        best_overlap = 0
        for cname, cgenres in CLUSTER_DEFS.items():
            overlap = len(top_genres & cgenres)
            if overlap > best_overlap:
                best_overlap = overlap
                best_cluster = cname
        if best_cluster:
            cluster_doc = await db.taste_clusters.find_one({"cluster_id": best_cluster})
            if cluster_doc:
                top_titles = cluster_doc.get("top_titles") or []
                # If this title is in the cluster's top 20, give a small extra nudge
                if any(t.get("movie_id") == movie_id for t in top_titles):
                    cluster_bonus = 0.15

    # Total bonus: community success scaled by confidence and fade,
    # plus a small cluster alignment nudge.
    community_term = tss * conf * fade * 2.0  # max ~2.0 when tss=1.0, conf=1.0, fade=1.0
    return community_term + cluster_bonus * conf * fade


# ---------------------------------------------------------------------------
# Engine-side helpers (called once per feed build)
# ---------------------------------------------------------------------------

async def compute_new_user_boost(
    user: dict,
    catalog: list[dict],
    db_ref,
) -> dict[str, float]:
    """Build a movie_id → boost mapping for users with <20 interactions.

    Bulk-fetches title_metrics for all catalog items in a SINGLE query
    (avoids N+1 per-title DB reads) and also pre-loads the user's cluster
    assignment once per request.  Result is a lightweight dict consumed by
    `_post_score_adjust` in O(1) per title.
    """
    interactions = (
        len(user.get("saved") or [])
        + len(user.get("watched") or [])
        + len(user.get("skipped") or [])
        + len(user.get("onboarding_rated") or [])
    )
    if interactions >= 20:
        return {}

    fade = max(0.0, 1.0 - interactions / 20.0)

    # ── Bulk-fetch title_metrics for every item in the filtered catalog ─────────
    catalog_ids = {m.get("id") for m in catalog if m.get("id")}
    if not catalog_ids:
        return {}

    metrics_map: dict[str, dict] = {}
    try:
        cursor = db_ref.title_metrics.find(
            {"movie_id": {"$in": list(catalog_ids)}},
            {"_id": 0, "movie_id": 1, "title_success_score": 1, "confidence": 1},
        )
        async for doc in cursor:
            metrics_map[doc["movie_id"]] = doc
    except Exception:
        pass

    # ── Pre-compute user's cluster assignment once ─────────────────────────────
    cluster_top_titles: set[str] = set()
    gw = user.get("genre_weights") or {}
    if gw:
        top3 = sorted(gw.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_genres = {g for g, _ in top3}
        best_cluster = None
        best_overlap = 0
        CLUSTER_DEFS = {
            "crime_thriller_prestige": {"Crime", "Thriller", "Mystery"},
            "action_blockbuster":      {"Action", "Adventure", "Sci-Fi"},
            "drama_awards":            {"Drama", "Biography", "History"},
            "scifi_mystery":           {"Sci-Fi", "Mystery", "Fantasy"},
            "comedy_light":            {"Comedy", "Romance", "Family"},
            "horror_dark":             {"Horror", "Thriller", "War"},
            "documentary_niche":       {"Documentary", "Music", "Sport"},
        }
        for cname, cgenres in CLUSTER_DEFS.items():
            overlap = len(top_genres & cgenres)
            if overlap > best_overlap:
                best_overlap = overlap
                best_cluster = cname
        if best_cluster:
            try:
                cluster_doc = await db_ref.taste_clusters.find_one(
                    {"cluster_id": best_cluster},
                    {"_id": 0, "top_titles": 1},
                )
                if cluster_doc:
                    for t in (cluster_doc.get("top_titles") or []):
                        cluster_top_titles.add(t.get("movie_id"))
            except Exception:
                pass

    # ── Build boost map in-memory (no further DB calls) ─────────────────────────────
    boosts: dict[str, float] = {}
    for movie in catalog:
        mid = movie.get("id")
        if not mid:
            continue
        metrics = metrics_map.get(mid)
        if not metrics:
            continue
        conf = metrics.get("confidence") or 0.0
        if conf == 0.0:
            continue
        tss = metrics.get("title_success_score") or 0.0
        cluster_bonus = 0.15 if mid in cluster_top_titles else 0.0
        bonus = (tss * conf * fade * 2.0) + (cluster_bonus * conf * fade)
        if bonus:
            boosts[mid] = bonus
    return boosts


async def get_community_quality_scores(
    db_ref,
) -> dict[str, float]:
    """Fetch all title-level community_quality_score values into a dict.

    Light cache for `_hybrid_score`; runs once per feed build.
    """
    cache: dict[str, float] = {}
    try:
        cursor = db_ref.title_metrics.find(
            {"community_quality_score": {"$ne": None}},
            {"_id": 0, "movie_id": 1, "community_quality_score": 1},
        )
        async for doc in cursor:
            cqs = doc.get("community_quality_score")
            if cqs is not None:
                cache[doc["movie_id"]] = cqs
    except Exception:
        logger.warning("get_community_quality_scores fetch failed; running without community nudge")
    return cache


async def get_discovery_scores(
    db_ref,
) -> dict[str, float]:
    """Fetch title-level discovery_success_score values into a dict.

    Applied as a soft nudge to adjacent/wildcard pool items during ranking.
    """
    cache: dict[str, float] = {}
    try:
        cursor = db_ref.title_metrics.find(
            {"discovery_success_score": {"$ne": None}},
            {"_id": 0, "movie_id": 1, "discovery_success_score": 1, "confidence": 1},
        )
        async for doc in cursor:
            dss = doc.get("discovery_success_score")
            conf = doc.get("confidence") or 0.0
            # Only apply when we have enough confidence (same thresholds)
            if dss is not None and conf > 0.0:
                cache[doc["movie_id"]] = dss * conf  # scale by confidence
    except Exception:
        logger.warning("get_discovery_scores fetch failed; running without discovery nudge")
    return cache


async def get_self_cleaning_flags(
    db_ref,
) -> set[str]:
    """Fetch movie_ids with self_cleaning_flag=True.

    Used as a soft penalty in ranking (weak titles get a small demotion,
    never hard removal).  Only flags with sufficient confidence are returned.
    """
    flagged: set[str] = set()
    try:
        cursor = db_ref.title_metrics.find(
            {"self_cleaning_flag": True, "confidence": {"$gte": 0.3}},
            {"_id": 0, "movie_id": 1},
        )
        async for doc in cursor:
            mid = doc.get("movie_id")
            if mid:
                flagged.add(mid)
    except Exception:
        logger.warning("get_self_cleaning_flags fetch failed; running without self-cleaning penalty")
    return flagged


# ---------------------------------------------------------------------------
# Admin diagnostics helpers
# ---------------------------------------------------------------------------

async def community_health_snapshot() -> dict:
    """Return a read-only snapshot of aggregate community health for the admin
    dashboard.  Metric-by-metric guarded so one failure never kills the response.
    """
    result: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # Total titles with metrics
    try:
        result["titles_with_metrics"] = await db.title_metrics.count_documents({})
    except Exception:
        result["titles_with_metrics"] = None

    # Average rates across all tracked titles
    try:
        total_saves = total_watches = total_skips = total_impressions = 0
        cursor = db.title_metrics.find(
            {}, {"_id": 0, "saves": 1, "watches": 1, "skips": 1, "impressions": 1}
        )
        async for doc in cursor:
            total_saves += doc.get("saves", 0)
            total_watches += doc.get("watches", 0)
            total_skips += doc.get("skips", 0)
            total_impressions += doc.get("impressions", 0)
        denom = max(1, total_impressions)
        result["average_save_rate"]  = round(total_saves / denom, 4)
        result["average_watch_rate"] = round(total_watches / denom, 4)
        result["average_skip_rate"]  = round(total_skips / denom, 4)
    except Exception:
        result["average_save_rate"] = result["average_watch_rate"] = result["average_skip_rate"] = None

    # Top / bottom performers (by title_success_score with >=100 impressions)
    try:
        top_cursor = db.title_metrics.find(
            {"impressions": {"$gte": 100}},
            {"_id": 0, "movie_id": 1, "title": 1, "title_success_score": 1, "impressions": 1}
        ).sort("title_success_score", -1).limit(10)
        result["top_performers"] = [
            {
                "movie_id": d.get("movie_id"),
                "title":    d.get("title"),
                "score":    d.get("title_success_score"),
                "n":        d.get("impressions"),
            }
            async for d in top_cursor
        ]
    except Exception:
        result["top_performers"] = None

    try:
        bottom_cursor = db.title_metrics.find(
            {"impressions": {"$gte": 100}},
            {"_id": 0, "movie_id": 1, "title": 1, "title_success_score": 1, "impressions": 1}
        ).sort("title_success_score", 1).limit(10)
        result["bottom_performers"] = [
            {
                "movie_id": d.get("movie_id"),
                "title":    d.get("title"),
                "score":    d.get("title_success_score"),
                "n":        d.get("impressions"),
            }
            async for d in bottom_cursor
        ]
    except Exception:
        result["bottom_performers"] = None

    # Self-cleaning candidates
    try:
        sc_cursor = db.title_metrics.find(
            {"self_cleaning_flag": True},
            {"_id": 0, "movie_id": 1, "title": 1, "impressions": 1, "save_rate": 1, "skip_rate": 1}
        ).sort("impressions", -1).limit(20)
        result["self_cleaning_candidates"] = [
            {
                "movie_id": d.get("movie_id"),
                "title":    d.get("title"),
                "impressions": d.get("impressions"),
                "save_rate": d.get("save_rate"),
                "skip_rate": d.get("skip_rate"),
            }
            async for d in sc_cursor
        ]
    except Exception:
        result["self_cleaning_candidates"] = None

    # Cluster distribution
    try:
        cluster_cursor = db.taste_clusters.find({}, {"_id": 0, "cluster_id": 1, "user_count": 1})
        result["clusters"] = [
            {"cluster_id": d.get("cluster_id"), "user_count": d.get("user_count")}
            async for d in cluster_cursor
        ]
    except Exception:
        result["clusters"] = None

    return result
