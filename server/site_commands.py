"""Hard-route: user gives a website URL → browse same-host pages (read-only) → answer."""
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

_URL_RE = re.compile(
    r"(?i)\b((?:https?://|www\.)[^\s<>\"']+|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:/[^\s<>\"']*)?)"
)

_BROWSE_INTENT = re.compile(
    r"(?is)\b("
    r"look\s+at|check|review|browse|read|open|visit|analyze|analyse|"
    r"tell\s+me\s+about|what\s+(?:is|does)|summarize|summarise|"
    r"go\s+(?:to|through)|inspect|scan"
    r")\b|"
    r"\b(website|site|webpage|web\s*page|link|url)\b"
)


def _extract_url(text: str) -> str | None:
    for m in _URL_RE.finditer(text or ""):
        raw = m.group(1).rstrip(".,);]")
        # Skip bare email-looking hosts without path if it's clearly not a site ask
        if "@" in raw:
            continue
        if raw.lower().startswith("www."):
            return "https://" + raw
        if re.match(r"(?i)^https?://", raw):
            return raw
        # domain.tld/... only when browse intent is present (caller checks)
        if "/" in raw or raw.count(".") >= 1:
            return "https://" + raw
    return None


def _plugin_browse():
    last = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import site_browse  # type: ignore
            return site_browse
        except Exception as exc:
            last = exc
    raise RuntimeError(f"site_browse unavailable: {last}")


def _format_pages(data: dict[str, Any], *, focus: str) -> str:
    pages = data.get("pages_read") or []
    lines = [
        f"I opened {data.get('host') or 'the site'} and read {len(pages)} page(s) (read-only, nothing submitted).",
    ]
    for i, p in enumerate(pages[:8], 1):
        title = (p.get("title") or "Untitled").strip()
        url = (p.get("url") or "").strip()
        lines.append(f"{i}. {title} — {url}")
    if focus:
        lines.append(f"Your ask: {focus}")
    lines.append("Using what I read to answer next.")
    return "\n".join(lines)


def _brain_pack(data: dict[str, Any], *, focus: str, user_text: str) -> str:
    pages = data.get("pages_read") or []
    chunks = [
        "[Website browse — read-only. Do NOT submit forms, sign in, checkout, or pay.]",
        f"Start URL: {data.get('start_url')}",
        f"Host: {data.get('host')}",
        f"User request: {user_text}",
    ]
    if focus:
        chunks.append(f"Focus: {focus}")
    for i, p in enumerate(pages[:6], 1):
        title = (p.get("title") or "Untitled").strip()
        url = (p.get("url") or "").strip()
        text = (p.get("text") or p.get("error") or "").strip()
        if len(text) > 3500:
            text = text[:3500] + "…"
        chunks.append(f"\n--- Page {i}: {title} ---\nURL: {url}\n{text}")
    chunks.append(
        "\nAnswer the user using only this site content when possible. "
        "If something is missing, say what you couldn't find. Be concrete."
    )
    return "\n".join(chunks)


def try_handle_site_browse(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t or len(t) > 2000:
        return None
    url = _extract_url(t)
    if not url:
        return None
    # Require browse intent OR a bare URL with a question/task around it
    has_intent = bool(_BROWSE_INTENT.search(t))
    has_question = "?" in t or bool(
        re.search(r"(?i)\b(review|check|look|tell|what|how|summarize|about|friend|business)\b", t)
    )
    if not (has_intent or has_question):
        # Bare "https://x.com" still OK — treat as look at this site
        if not re.match(r"(?is)^\s*(?:please\s+)?(?:https?://|www\.)\S+\s*$", t):
            return None

    focus = _URL_RE.sub(" ", t)
    focus = re.sub(r"\s+", " ", focus).strip(" .,;:-")
    if len(focus) < 3:
        focus = "Review this website and summarize what it is and what it offers."

    try:
        sb = _plugin_browse()
        raw = sb.browse_website({"url": url, "focus": focus, "max_pages": 5})
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception as exc:
        return {
            "text": f"I couldn't open that website ({exc}).",
            "tools": [{"name": "browse_website", "preview": url}],
            "run_id": "browse_website",
        }

    if not data.get("ok"):
        return {
            "text": data.get("error") or "Couldn't read that website.",
            "tools": [{"name": "browse_website", "preview": url}],
            "run_id": "browse_website",
        }

    reply = _format_pages(data, focus=focus)
    return {
        "text": reply,
        "speak": (
            f"I read {data.get('page_count') or 0} pages on {data.get('host') or 'the site'}. "
            "Answering from what I found."
        ),
        "tools": [{"name": "browse_website", "preview": data.get("host") or url}],
        "run_id": "browse_website",
        "brain_followup": _brain_pack(data, focus=focus, user_text=t),
        "count": data.get("page_count") or 0,
    }
