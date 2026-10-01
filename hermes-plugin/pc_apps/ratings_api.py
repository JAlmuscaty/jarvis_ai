"""IMDb / overall movie & TV ratings tool for Hermes."""
from __future__ import annotations

import json
from typing import Any

from .movie_ratings import (
    extract_episode_rating_query,
    format_episode_ratings_reply,
    format_ratings_reply,
    lookup_ratings,
    lookup_recent_episodes,
)


def _truthy(v: Any) -> bool:
    return v in (True, "true", "True", "1", 1, "yes", "YES")


def movie_ratings_lookup(args: dict | None = None, **kwargs: Any) -> str:
    """
    Look up show/movie ratings OR recent episode ratings.
    Rating backends are always available (OMDb + TVMaze) — never claim 'not configured'.
    """
    args = dict(args or {})
    args.update({k: v for k, v in kwargs.items() if v is not None})
    title = str(args.get("title") or args.get("query") or args.get("show") or "").strip()
    prefer = str(args.get("prefer") or args.get("type") or "").strip() or None
    year = str(args.get("year") or "").strip() or None
    try:
        count_i = int(args.get("count") or args.get("limit") or 6)
    except (TypeError, ValueError):
        count_i = 6

    if not title:
        return json.dumps({
            "ok": False,
            "error": "title is required",
            "text": "Tell me the movie or show title to look up.",
        })

    ep = extract_episode_rating_query(title)
    want_eps = (
        _truthy(args.get("recent_episodes"))
        or _truthy(args.get("last_episodes"))
        or args.get("mode") in ("episodes", "recent_episodes", "last_episodes")
        or ep is not None
    )

    try:
        if want_eps:
            show, n = (ep if ep else (title, count_i))
            data = lookup_recent_episodes(show, count=n if ep else count_i)
            data["text"] = format_episode_ratings_reply(data)
            return json.dumps(data, ensure_ascii=False)

        data = lookup_ratings(title, year=year, prefer=prefer)
        data["text"] = format_ratings_reply(data)
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "ok": False,
            "error": str(exc),
            "text": f"Rating lookup failed temporarily: {exc}",
        })
