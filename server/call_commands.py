"""Hard-route phone-call commands to Skills/Memory contacts only."""
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

# "call Ali", "please dial Mohamed", "phone my dad"
_CALL_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?(?:could\s+you\s+)?"
    r"(?:call|dial|ring|phone)\s+(?:up\s+)?(.+?)\s*[.!]?\s*$",
    re.I,
)
# "make a call to Ali" / "place a call to Mohamed"
_CALL_TO_RE = re.compile(
    r"^\s*(?:please\s+)?(?:make|place|start)\s+(?:a\s+)?call\s+(?:to\s+)(.+?)\s*[.!]?\s*$",
    re.I,
)


def extract_call_target(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    for pat in (_CALL_RE, _CALL_TO_RE):
        m = pat.match(t)
        if m:
            who = m.group(1).strip(" .,!?;:\"'")
            who = re.sub(r"\s+", " ", who)
            # Drop trailing filler / device words
            who = re.sub(
                r"\b(please|thanks|thank you|on my phone|on the phone|for me)\b.*$",
                "",
                who,
                flags=re.I,
            ).strip()
            # Ignore "call me later" / "call back" style
            low = who.lower()
            if low in {"me", "you", "him", "her", "them", "us", "back", "again"}:
                return None
            if re.match(r"^(me|you)\b", low) and re.search(r"\b(later|back|again|tomorrow|tonight)\b", low):
                return None
            if who:
                return who[:80]
    return None


def _call_plugin(contact: str) -> dict[str, Any]:
    last_err: Exception | None = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import phone_apps  # type: ignore

            raw = phone_apps.call_contact({"contact": contact})
            try:
                return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception:
                return {"ok": False, "error": str(raw)[:300]}
        except Exception as exc:
            last_err = exc
            continue
    return {"ok": False, "error": f"call plugin unavailable: {last_err or 'not found'}"}


def try_handle_call(text: str) -> dict[str, Any] | None:
    """If this is a call command, dial via memory and return a chat-style result."""
    who = extract_call_target(text)
    if not who:
        return None

    result = _call_plugin(who)
    tools = [{"name": "call_contact", "preview": who}]
    if result.get("ok"):
        note = result.get("note") or f"Calling {result.get('contact') or who}."
        return {
            "text": note,
            "tools": tools,
            "run_id": None,
            "memories_saved": [],
            "call_routed": True,
            "call_result": result,
        }
    err = result.get("error") or "Could not place that call."
    return {
        "text": err,
        "tools": tools,
        "run_id": None,
        "memories_saved": [],
        "call_routed": True,
        "call_result": result,
    }


def hermes_call_hint(text: str) -> str:
    who = extract_call_target(text)
    if not who:
        return text
    return (
        "[HARD RULE] User wants a phone call. "
        f"Call call_contact with contact={who!r}. "
        "Only dial if Skills/Memory has a phone number for them. "
        "Never invent numbers. Never use YouTube or WhatsApp for this.\n\n"
        f"{text}"
    )
