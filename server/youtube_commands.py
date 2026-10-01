"""Hard-route YouTube choose / play / search so Jarvis picks a video without asking."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_PLUGIN_DIRS = [
    Path.home() / "AppData" / "Local" / "hermes" / "plugins",
    Path(__file__).resolve().parents[1] / "hermes-plugin",
]

_YT_ONLY = re.compile(r"(?is)\b(youtube|yt)\b")
_MOVIE_BLOCK = re.compile(r"(?is)\b(vidbox|movies?|films?|cinema)\b")
_CHOOSE_VIDEO = re.compile(
    r"(?is)\b(?:choose|pick|select|find|play|open)\b.{0,50}\b(?:youtube\s+)?(?:video|vid|clip)\b|"
    r"\b(?:youtube|yt)\b.{0,40}\b(?:video|search|play|choose|pick)\b|"
    r"\b(?:search|play|watch)\b.{0,30}\b(?:on\s+)?(?:youtube|yt)\b"
)


def _plugin_ba():
    last = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import browser_actions  # type: ignore
            return browser_actions
        except Exception as exc:
            last = exc
    raise RuntimeError(f"pc_apps unavailable: {last}")


def build_youtube_query(text: str) -> str:
    """Turn 'choose a video explaining one piece' → 'one piece explanation'."""
    t = (text or "").strip()
    # Intent: explanation / tutorial / review / etc.
    want_explain = bool(re.search(r"(?is)\b(explain(?:ing|ed)?|explanation|breakdown|summary|recap)\b", t))
    want_tutorial = bool(re.search(r"(?is)\b(tutorial|how\s+to|guide|walkthrough)\b", t))
    want_review = bool(re.search(r"(?is)\b(review|trailer|ost|soundtrack|amv|edit)\b", t))

    topic = t
    # Prefer topic after explaining/about/on/for
    m = re.search(
        r"(?is)\b(?:explaining|explained|explain|explanation\s+of|about|on|for|of)\s+(.+)$",
        t,
    )
    if m:
        topic = m.group(1)
    else:
        # After "video …"
        m2 = re.search(r"(?is)\b(?:video|vid|clip)\s+(.+)$", t)
        if m2:
            topic = m2.group(1)

    topic = re.sub(
        r"(?is)\b("
        r"please|for me|on (?:my )?pc|on youtube|youtube|yt|"
        r"choose|pick|select|find|play|open|and|a|an|the|"
        r"video|vid|clip|search|"
        r"explaining|explained|explain|explanation|about|on the topic of"
        r")\b",
        " ",
        topic,
    )
    topic = re.sub(r"\s+", " ", topic).strip(" .,!?;:\"'")
    if not topic:
        return ""

    # Enrich so search finds explainers, not just the bare title
    low = topic.lower()
    if want_explain and not re.search(r"(?is)\b(explain|explanation|breakdown|summary|recap)\b", low):
        topic = f"{topic} explanation"
    elif want_tutorial and not re.search(r"(?is)\b(tutorial|guide|how to)\b", low):
        topic = f"{topic} tutorial"
    elif want_review and not re.search(r"(?is)\b(review|trailer)\b", low):
        # keep user's review/trailer word if already in original; else leave topic
        pass
    return topic[:120]


def try_handle_youtube(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t or _MOVIE_BLOCK.search(t):
        return None
    if not _CHOOSE_VIDEO.search(t) and not _YT_ONLY.search(t):
        return None
    # Bare "open youtube" with no topic → let open_commands handle
    if re.match(r"(?is)^\s*(?:please\s+)?(?:open|launch|start)\s+(?:youtube|yt)\s*$", t):
        return None

    query = build_youtube_query(t)
    if not query or len(query) < 2:
        return None

    search_only = bool(re.search(r"(?is)\bsearch\b", t)) and not re.search(
        r"(?is)\b(choose|pick|play|open|watch)\b", t
    )
    try:
        ba = _plugin_ba()
        if search_only:
            raw = ba.youtube_type_search({"query": query, "pick": False})
        else:
            raw = ba.youtube_pick_video({"query": query})
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception as exc:
        return {
            "text": f"Couldn't open YouTube ({exc}).",
            "tools": [{"name": "youtube_pick_video", "preview": "error"}],
            "run_id": "youtube",
        }

    if not data.get("ok"):
        return {
            "text": data.get("error") or f"Couldn't find a video for {query}.",
            "tools": [{"name": "youtube_pick_video", "preview": "miss"}],
            "run_id": "youtube",
        }
    title = data.get("title") or query
    if search_only:
        msg = f"YouTube search: {query}."
    else:
        msg = f"Playing: {title}."
    return {
        "text": msg,
        "speak": msg,
        "tools": [{"name": data.get("action") or "youtube_pick_video", "preview": query[:40]}],
        "run_id": "youtube",
        "query": query,
    }
