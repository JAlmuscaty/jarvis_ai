"""Hard-route WhatsApp type / type+send to Skills/Memory contacts with phone numbers."""
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

# type/text/message/whatsapp to NAME MESSAGE [and send]
_WA_RE = re.compile(
    r"(?is)^\s*(?:please\s+|can\s+you\s+)?"
    r"(?:"
    r"(?:type|text|message|msg|dm|whatsapp|wa)\s+(?:to\s+|for\s+)?"
    r"|"
    r"(?:send\s+(?:a\s+)?(?:whatsapp\s+|wa\s+)?(?:message|text|msg)\s+(?:to\s+))"
    r")"
    r"(.+)$"
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


def _split_who_message(rest: str) -> tuple[str, str, bool]:
    """Return (contact, message, want_send)."""
    rest = (rest or "").strip(" .,!?;:\"'")
    want_send = bool(re.search(r"(?is)\b(?:and\s+send|then\s+send|send\s+it)\b", rest))
    # Strip send tail from message
    rest_clean = re.sub(r"(?is)\s*(?:,?\s*)?(?:and\s+send|then\s+send|send\s+it)\s*$", "", rest).strip()

    # "hussain hi" / "hussain: hi" / "hussain saying hi" / "hussain that hi"
    m = re.match(
        r"(?is)^([A-Za-z][\w .'-]{0,40}?)\s*(?::|,|saying|that|-)?\s+(.+)$",
        rest_clean,
    )
    if m:
        who = m.group(1).strip(" .,!?;:\"'")
        msg = m.group(2).strip(" .,!?;:\"'")
        who = re.sub(r"(?is)\b(on\s+whatsapp|please)\b", "", who).strip()
        return who[:80], msg[:2000], want_send

    # Bare "send to hussain" without body — not enough
    return rest_clean[:80], "", want_send


def try_handle_whatsapp(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None
    # Don't steal bare "open whatsapp"
    if re.match(r"(?is)^\s*(?:open|launch|start)\s+whatsapp\b", t):
        return None
    m = _WA_RE.match(t)
    if not m:
        if not re.search(
            r"(?is)\b(whatsapp|type\s+to|text\s+to|text\s+\w+|message\s+to|msg\s+to|dm\s+|send\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|text))\b",
            t,
        ):
            return None
        m2 = re.search(
            r"(?is)\b(?:type|text|message|msg|dm|whatsapp|send)\s+(?:a\s+)?(?:whatsapp\s+)?(?:message\s+|text\s+)?(?:to\s+)?(.+)$",
            t,
        )
        if not m2:
            return None
        rest = m2.group(1)
    else:
        rest = m.group(1)

    who, message, want_send = _split_who_message(rest)
    if not message and re.search(r"(?is)\bsend\b", t):
        want_send = True
        m3 = re.search(
            r"(?is)\bsend\s+(?:a\s+)?(?:whatsapp\s+)?(?:message\s+|text\s+)?(?:to\s+)?(\w+)\s+(.+)$",
            t,
        )
        if m3:
            who, message = m3.group(1), m3.group(2)
            message = re.sub(r"(?is)\s*(?:and\s+send|send\s+it)\s*$", "", message).strip()

    if not who or not message:
        return None

    try:
        ba = _plugin_ba()
        raw = ba.whatsapp_draft_to_contact({
            "contact": who,
            "message": message,
            "send": want_send,
            "wait_seconds": 120 if want_send else 5,
        })
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception as exc:
        return {
            "text": f"Couldn't open WhatsApp on the PC ({exc}).",
            "tools": [{"name": "whatsapp_draft_to_contact", "preview": who}],
            "run_id": "whatsapp",
        }

    if not data.get("ok"):
        err = data.get("error") or data.get("message") or f"Couldn't message {who} on WhatsApp."
        return {
            "text": err,
            "speak": err,
            "tools": [{"name": "whatsapp_draft_to_contact", "preview": "fail"}],
            "run_id": "whatsapp",
            "sent": False,
        }

    msg = data.get("message") or (
        f"Sent to {who}." if data.get("sent") else f"Typed to {who} on WhatsApp (not sent)."
    )
    return {
        "text": msg,
        "speak": msg,
        "tools": [{
            "name": "whatsapp_send" if data.get("sent") else "whatsapp_draft_to_contact",
            "preview": who[:40],
        }],
        "run_id": "whatsapp",
        "sent": bool(data.get("sent")),
    }
