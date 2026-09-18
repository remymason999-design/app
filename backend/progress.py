"""Pure helpers for canonical TV episode progress.

These helpers deliberately have no database/provider dependencies.  The wire
format is additive: legacy ``progress.<id> = {season, episode}`` records remain
valid while new records carry an episode map and provenance.
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Iterable


def episode_key(season: int, episode: int) -> str:
    """Return the stable, zero-padded key used in progress episode maps."""
    if int(season) < 1 or int(episode) < 1:
        raise ValueError("season and episode must be positive")
    return f"s{int(season):02d}e{int(episode):03d}"


def parse_episode_key(key: str) -> tuple[int, int]:
    import re
    match = re.fullmatch(r"s(\d{2,})e(\d{3,})", str(key).lower())
    if not match:
        raise ValueError("invalid episode key")
    return int(match.group(1)), int(match.group(2))


def normalize_progress(record: dict | None) -> dict:
    """Normalize legacy/coarse and canonical records without inventing data."""
    record = dict(record or {})
    episodes = dict(record.get("episodes") or {})
    # Accept a list as a convenience for imports, but only valid keys.
    if isinstance(record.get("watched_episodes"), (list, tuple, set)):
        episodes.update({str(k): {"watched": True, "provenance": "explicit"}
                         for k in record["watched_episodes"]})
    clean = {}
    for key, value in episodes.items():
        try:
            parse_episode_key(key)
        except ValueError:
            continue
        clean[key] = dict(value) if isinstance(value, dict) else {
            "watched": bool(value), "provenance": "explicit"
        }
    record["episodes"] = clean
    if record.get("season") is not None and record.get("episode") is not None:
        record["season"] = int(record["season"])
        record["episode"] = int(record["episode"])
    record.setdefault("provenance", "legacy" if record.get("season") else "explicit")
    return record


def progress_fingerprint(user: dict) -> str:
    """Stable cache component covering progress, feedback and preferences."""
    fields = {
        "progress": user.get("progress") or {},
        "watched": sorted(user.get("watched") or []),
        "watched_feedback": user.get("watched_feedback") or {},
        "preferences": {k: user.get(k) for k in (
            "subscriptions", "genres", "moods", "content_type", "country",
            "excluded_genres", "excluded_categories", "show_international",
            "show_anime_asian", "include_other_services", "include_rent_buy",
        )},
    }
    import json
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()[:20]


def episode_watch_state(record: dict | None) -> dict[str, dict]:
    return normalize_progress(record).get("episodes", {})


def watched_episode_count(record: dict | None) -> int:
    return sum(1 for value in episode_watch_state(record).values()
               if isinstance(value, dict) and value.get("watched"))


def inferred_episode_count(record: dict | None) -> int:
    r = normalize_progress(record)
    if r.get("episodes"):
        return sum(1 for v in r["episodes"].values()
                   if isinstance(v, dict) and v.get("provenance") in {"inferred", "bulk_inferred"}
                   and v.get("watched"))
    return 0


def completion_metadata(record: dict | None, seasons: list | None = None,
                        runtime: int | float | None = None) -> dict:
    """Return honest completion state; unknown catalog counts stay ``None``."""
    r = normalize_progress(record)
    watched = watched_episode_count(r)
    known = [s for s in (seasons or []) if isinstance(s, dict)
             and int(s.get("season_number") or 0) > 0
             and int(s.get("episode_count") or 0) > 0]
    detailed = [e for s in known for e in (s.get("episodes") or [])
                if isinstance(e, dict)]
    hydration_incomplete = any(
        s.get("metadata_provenance") == "tmdb_season_unavailable" for s in known
    )
    hydration_present = any(
        s.get("metadata_provenance") == "tmdb_season" for s in known
    )
    today = date.today().isoformat()
    eligible_episodes = [
        e for e in detailed
        if e.get("episode_key") and e.get("air_date") and e["air_date"] <= today
    ]
    # Detailed metadata is authoritative only when every listed episode has an
    # air date; otherwise retain the season-count fallback rather than silently
    # treating unknown dates as released.
    dates_complete = bool(detailed) and all(e.get("air_date") for e in detailed)
    eligible = (
        None if hydration_incomplete or (hydration_present and not dates_complete)
        else (len(eligible_episodes) if dates_complete
              else (sum(int(s["episode_count"]) for s in known) if known else None))
    )
    episode_states = r.get("episodes", {})

    def watched_for_release(episode: dict) -> bool:
        state = episode_states.get(episode.get("episode_key")) or {}
        if not isinstance(state, dict) or not state.get("watched"):
            return False
        # Old bulk operations could infer catalogue-listed episodes before they
        # aired. Keep the record untouched, but do not let it pre-complete a
        # release later. Explicit corrections always remain authoritative.
        if state.get("provenance") in {"inferred", "bulk_inferred"}:
            updated = str(state.get("updated_at") or "")[:10]
            if updated and episode.get("air_date") and updated < episode["air_date"]:
                return False
        return True

    watched_released = (
        sum(1 for episode in eligible_episodes if watched_for_release(episode))
        if dates_complete else None
    )
    if dates_complete:
        completed = bool(eligible_episodes) and watched_released == len(eligible_episodes)
    else:
        completed = eligible is not None and watched >= eligible
    measured_runtime = sum(
        float(e["runtime"]) for e in detailed
        if e.get("runtime") and e.get("episode_key") in r.get("episodes", {})
        and r["episodes"][e["episode_key"]].get("watched")
    )
    measured_count = sum(
        1 for e in detailed
        if e.get("runtime") and e.get("episode_key") in r.get("episodes", {})
        and r["episodes"][e["episode_key"]].get("watched")
    )
    return {
        "started": bool(watched or r.get("season") or r.get("episode")),
        "watched_episode_count": watched,
        "eligible_episode_count": eligible,
        "watched_released_episode_count": watched_released,
        "completed": completed if eligible is not None else None,
        "provenance": "inferred" if inferred_episode_count(r) else "explicit",
        "eligible_count_provenance": (
            "unknown" if hydration_incomplete or (hydration_present and not dates_complete) else
            ("tmdb_release_dates" if dates_complete else
             ("season_counts" if known else "unknown"))
        ),
        "measured_runtime_minutes": measured_runtime,
        "measured_runtime_episode_count": measured_count,
        "estimated_runtime": bool(runtime and measured_count < watched),
    }
