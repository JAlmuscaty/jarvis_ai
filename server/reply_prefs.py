"""Sticky reply style prefs — simple (answer-only) vs normal."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

_SIMPLE_ON = re.compile(r"(?is)^\s*/(?:simple|brief|answer)\s*$")
_SIMPLE_PREFIX = re.compile(r"(?is)^\s*/(?:simple|brief|answer)\s+(.+)$")
_FULL_ON = re.compile(r"(?is)^\s*/(?:full|normal|detailed|explain)\s*$")


def _prefs_path() -> Path:
    logs = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
    return logs / "reply_prefs.json"


def _empty() -> dict[str, Any]:
    return {"simple": False, "updated_at": None}


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or _prefs_path()
    with _LOCK:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = _empty()
        if not isinstance(data, dict):
            data = _empty()
        data["simple"] = bool(data.get("simple"))
        return data


def save(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or _prefs_path()
    with _LOCK:
        out = dict(data)
        out["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2), encoding="utf-8")


def is_simple() -> bool:
    return bool(load().get("simple"))


def set_simple(on: bool) -> dict[str, Any]:
    prefs = load()
    prefs["simple"] = bool(on)
    save(prefs)
    return prefs


def parse_slash(text: str | None) -> dict[str, Any] | None:
    """Handle /simple and /full style commands.

    Returns a dict when the server should short-circuit or rewrite the turn:
      {"ack": "..."} — reply only, no Hermes
      {"text": "...", "force_simple": True} — rewritten user text for this turn
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if _SIMPLE_ON.match(raw):
        set_simple(True)
        return {
            "ack": "Simple mode on - I'll give answers only. Type /full for normal replies.",
            "simple": True,
        }
    if _FULL_ON.match(raw):
        set_simple(False)
        return {
            "ack": "Full mode on - normal explanations again.",
            "simple": False,
        }
    m = _SIMPLE_PREFIX.match(raw)
    if m:
        set_simple(True)
        return {"text": m.group(1).strip(), "force_simple": True}
    return None


def style_hint_for_prompt(*, force_simple: bool | None = None) -> str:
    simple = is_simple() if force_simple is None else bool(force_simple)
    if not simple:
        return ""
    return (
        "[SIMPLE MODE — MANDATORY]\n"
        "Reply with ONLY what the user needs: the final answer.\n"
        "- No greetings, no fluff, no 'sure', no steps unless they ask for steps.\n"
        "- Homework / math / multiple choice: give the answer only (e.g. '42' or 'B').\n"
        "- Classroom / assignments: list homework titles only (add due date if there is one). "
        "Never class names, course codes, headers, or 'read-only' notes.\n"
        "- Never add extra context, labels, or narration the user did not ask for.\n"
        "- If a short unit is required, include it (e.g. '3.5 m/s').\n"
        "- English only unless they asked for Arabic.\n"
        "[END SIMPLE MODE]\n"
    )


def want_simple(*, force_simple: bool | None = None) -> bool:
    """True when sticky /simple is on, or this turn forced it via /simple …"""
    if force_simple is not None:
        return bool(force_simple)
    return is_simple()

