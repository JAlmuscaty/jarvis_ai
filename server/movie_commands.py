"""Hard-route movies / Vidbox commands so Hermes never opens YouTube by mistake."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from movie_ratings import (
    extract_episode_rating_query,
    extract_rating_query,
    format_episode_ratings_reply,
    format_ratings_reply,
    lookup_ratings,
    lookup_recent_episodes,
)

# Plugin live copy (Hermes) + repo copy as fallback
_PLUGIN_DIRS = [
    Path.home() / "AppData" / "Local" / "hermes" / "plugins",
    Path(__file__).resolve().parents[1] / "hermes-plugin",
]

_MOVIE_WORD = r"(?:movies?|vidbox|vid\s*box|film(?:s)?|cinema|(?:ال)?افلام|(?:ال)?أفلام|فيدبوكس)"


def _looks_like_movies(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    # Explicit YouTube wins only when movies words are absent
    if re.search(rf"\b{_MOVIE_WORD}\b", t, flags=re.I) or re.search(
        r"(?:ال)?افلام|(?:ال)?أفلام|فيدبوكس", t
    ):
        return True
    # Bare "movies" / "open movie site"
    if re.fullmatch(r"(?:please\s+)?(?:open\s+)?(?:the\s+)?movies?(?:\s+site)?[.!]?", t):
        return True
    return False


def _extract_query(text: str) -> str | None:
    """Pull a search title out of common phrasings; None = open only."""
    t = (text or "").strip()
    if not t:
        return None
    patterns = [
        # open movies and search spider man / open movies search spider man
        rf"(?:open\s+)?{_MOVIE_WORD}\s+(?:and\s+)?(?:search|find|look\s*up)\s+(?:for\s+)?(.+)$",
        # search spider man on movies / find spider man on vidbox
        rf"(?:search|find|look\s*up)\s+(?:for\s+)?(.+?)\s+on\s+{_MOVIE_WORD}\b",
        # movies: spider man / vidbox spider man
        rf"^{_MOVIE_WORD}\s*[:\-]\s*(.+)$",
        # search movies for spider man
        rf"(?:search|find)\s+{_MOVIE_WORD}\s+(?:for\s+)?(.+)$",
        # on movies search spider man
        rf"on\s+{_MOVIE_WORD}\s+(?:search|find)\s+(?:for\s+)?(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, t, flags=re.I)
        if m:
            q = m.group(1).strip(" .,!?;:\"'")
            q = re.sub(r"\s+", " ", q)
            # Drop trailing filler
            q = re.sub(r"\b(please|thanks|thank you)\b.*$", "", q, flags=re.I).strip()
            if q and q.lower() not in {"it", "that", "this", "something"}:
                return q[:120]
    return None


def _is_open_only(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(
        re.fullmatch(
            rf"(?:please\s+)?(?:open|launch|go\s+to|start)?\s*(?:the\s+)?{_MOVIE_WORD}(?:\s+site|\s+page|\s+website)?[.!]?",
            t,
        )
    )


def _call_plugin(fn_name: str, args: dict) -> dict[str, Any]:
    last_err: Exception | None = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import browser_actions, tools  # type: ignore

            if fn_name == "open":
                raw = tools.open_pc_app({"app": "movies"})
            else:
                raw = browser_actions.vidbox_type_search(args)
            try:
                return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception:
                return {"ok": False, "error": str(raw)[:300]}
        except Exception as exc:
            last_err = exc
            continue
    return {"ok": False, "error": f"Vidbox plugin unavailable: {last_err or 'not found'}"}


def try_handle_movie_rating(text: str) -> dict[str, Any] | None:
    """Answer IMDb / overall / episode ratings in chat without opening Vidbox."""
    if re.search(r"\b(open|play|vidbox|youtube|launch)\b", text or "", re.I):
        return None

    ep = extract_episode_rating_query(text)
    if ep:
        title, count = ep
        data = lookup_recent_episodes(title, count=count)
        reply = format_episode_ratings_reply(data)
        return {
            "text": reply,
            "tools": [{"name": "movie_episode_ratings", "preview": f"{title[:40]} x{count}"}],
            "run_id": "movie_episode_ratings",
            "rating": data,
        }

    title = extract_rating_query(text)
    if not title:
        return None
    prefer = "tv" if re.search(r"\b(tv|series|show|anime)\b", text or "", re.I) else None
    data = lookup_ratings(title, prefer=prefer)
    reply = format_ratings_reply(data)
    return {
        "text": reply,
        "tools": [{"name": "movie_ratings", "preview": title[:60]}],
        "run_id": "movie_ratings",
        "rating": data,
    }


def try_handle_movies(text: str) -> dict[str, Any] | None:
    """
    If the user meant Vidbox/movies, run the action here and return a chat-style
    result dict. Returns None when this is not a movies command.
    """
    if not _looks_like_movies(text):
        return None
    # If they clearly said YouTube *and* movies, still prefer movies for "movies" word
    # (user already complained YouTube was wrong).

    query = _extract_query(text)
    tools_used: list[dict] = []

    if query:
        result = _call_plugin("search", {"query": query})
        tools_used.append({
            "name": "vidbox_type_search",
            "preview": query,
        })
        if result.get("ok"):
            return {
                "text": f"Opened Vidbox and searched for {query}.",
                "tools": tools_used,
                "run_id": None,
                "memories_saved": [],
                "movies_routed": True,
                "movies_result": result,
            }
        err = result.get("error") or "unknown error"
        return {
            "text": f"Tried to search Vidbox for {query}, but hit: {err}",
            "tools": tools_used,
            "run_id": None,
            "memories_saved": [],
            "movies_routed": True,
            "movies_result": result,
        }

    if _is_open_only(text) or re.search(rf"\bopen\b.*\b{_MOVIE_WORD}\b", text or "", re.I):
        result = _call_plugin("open", {})
        tools_used.append({"name": "open_pc_app", "preview": "movies"})
        if result.get("ok"):
            return {
                "text": "Opened Vidbox.",
                "tools": tools_used,
                "run_id": None,
                "memories_saved": [],
                "movies_routed": True,
                "movies_result": result,
            }
        err = result.get("error") or "unknown error"
        return {
            "text": f"Tried to open Vidbox, but hit: {err}",
            "tools": tools_used,
            "run_id": None,
            "memories_saved": [],
            "movies_routed": True,
            "movies_result": result,
        }

    # Movies mentioned but no clear open/search — still force Hermes away from YouTube
    return None


def hermes_movies_hint(text: str) -> str:
    """Prefix Hermes input so it cannot pick YouTube for movies phrasing."""
    if not _looks_like_movies(text):
        return text
    query = _extract_query(text)
    if query:
        return (
            "[HARD RULE] User said movies/Vidbox — NOT YouTube. "
            f"Call vidbox_type_search with query={query!r} only. "
            "Never call youtube_type_search or open_pc_app app=youtube for this.\n\n"
            f"{text}"
        )
    return (
        "[HARD RULE] User said movies/Vidbox — NOT YouTube. "
        'Call open_pc_app with app="movies" (or app="vidbox") only. '
        "Never call youtube_type_search for this.\n\n"
        f"{text}"
    )
