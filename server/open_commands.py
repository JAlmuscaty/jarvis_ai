"""Hard-route simple «open <app>» commands (after Arabic→English translation)."""
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

_OPEN_RE = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?"
    r"(?:open|launch|start|go\s+to)\s+(?:the\s+|my\s+)?"
    r"(.+?)"
    r"(?:\s+please)?\s*$",
    re.I,
)

# Don't steal movie search / multi-step from specialized handlers
_SKIP_IF = re.compile(r"\b(and\s+search|search|find|call|how\s+long|eta)\b", re.I)

_ALIASES = {
    "movies": "movies",
    "movie": "movies",
    "vidbox": "movies",
    "youtube": "youtube",
    "yt": "youtube",
    "whatsapp": "whatsapp",
    "chrome": "chrome",
    "gmail": "gmail",
    "maps": "maps",
    "google maps": "maps",
    "chatgpt": "chatgpt",
    "chat gpt": "chatgpt",
    "classroom": "classroom",
    "google classroom": "classroom",
    "notebooklm": "notebooklm",
    "notebook lm": "notebooklm",
    "google slides": "google_slides",
    "slides": "google_slides",
    "google docs": "google_docs",
    "google doc": "google_docs",
    "docs": "google_docs",
    "doc": "google_docs",
    "document": "google_docs",
    "blank page": "google_docs",
    "blank doc": "google_docs",
    "blank document": "google_docs",
    "a blank page": "google_docs",
    "new doc": "google_docs",
    "new document": "google_docs",
    "google sheets": "google_sheets",
    "sheets": "google_sheets",
    "google drive": "google_drive",
    "drive": "google_drive",
    "google calendar": "google_calendar",
    "calendar": "google_calendar",
}


def _normalize_app(raw: str) -> str | None:
    a = re.sub(r"\s+", " ", (raw or "").strip().lower())
    a = a.strip(" .,!?;:\"'")
    a = re.sub(r"\b(please|thanks|thank you|for me|on (?:my )?pc|on the computer)\b", "", a, flags=re.I).strip()
    if not a:
        return None
    if a in _ALIASES:
        return _ALIASES[a]
    # Whole words only — "yt" must not match inside "everything".
    for key, val in _ALIASES.items():
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", a):
            return val
    return None


def _call_open(app_id: str) -> dict[str, Any]:
    last_err: Exception | None = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import tools  # type: ignore

            raw = tools.open_pc_app({"app": app_id})
            try:
                return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception:
                return {"ok": False, "error": str(raw)[:300]}
        except Exception as exc:
            last_err = exc
            continue
    return {"ok": False, "error": f"open_pc_app unavailable: {last_err or 'not found'}"}


# "close all the tabs" also quits the Chrome window Jarvis started — not the user's Chrome.
_CLOSE_ALL_RE = re.compile(
    r"(?ix)"
    r"\b(?:close|shut)\b.{0,40}\ball\b.{0,24}\btabs?\b"
    r"|\b(?:close|shut)\b.{0,40}\btabs?\b.{0,30}\b(?:opened|you\s+opened)\b"
    r"|\b(?:close|shut)\s+(?:down\s+)?(?:all\s+)?(?:of\s+)?(?:the\s+)?(?:my\s+)?(?:google\s+)?(?:chrome|browser)\b"
)


def _call_close_all() -> dict[str, Any]:
    last_err: Exception | None = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import browser_actions  # type: ignore

            raw = browser_actions.close_jarvis_tabs({"close_all": True})
            try:
                return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception:
                return {"ok": False, "error": str(raw)[:300]}
        except Exception as exc:
            last_err = exc
            continue
    return {"ok": False, "error": f"close_jarvis_tabs unavailable: {last_err or 'not found'}"}


def try_handle_open(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t or _SKIP_IF.search(t):
        return None
    if len(t) <= 160 and not re.search(r"\b(?:don'?t|do not)\s+(?:close|shut)\b", t, re.I) and _CLOSE_ALL_RE.search(t):
        result = _call_close_all()
        text_out = result.get("message") or result.get("error") or "Closed the tabs and the Chrome window I opened."
        return {
            "text": text_out,
            "tools": [{"name": "close_jarvis_tabs", "preview": "close_all"}],
            "run_id": "close_jarvis_tabs",
        }
    m = _OPEN_RE.match(t)
    if not m:
        return None
    app_id = _normalize_app(m.group(1))
    if not app_id:
        return None
    # Movies open-only is also handled by movie_commands; either is fine
    result = _call_open(app_id)
    label = app_id.replace("_", " ")
    if result.get("ok"):
        return {
            "text": f"Opened {label}.",
            "tools": [{"name": "open_pc_app", "preview": app_id}],
            "run_id": "open_pc_app",
        }
    return {
        "text": result.get("error") or f"Could not open {label}.",
        "tools": [{"name": "open_pc_app", "preview": app_id}],
        "run_id": "open_pc_app",
    }
