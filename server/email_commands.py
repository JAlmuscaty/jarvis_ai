"""Hard-route email read + chat-only drafts (never send)."""
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

# Read / check inbox
_INBOX_RE = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?"
    r"(?:"
    r"(?:check|read|show|list|open)\s+(?:my\s+)?(?:emails?|e-?mails?|inbox|mail|gmail)"
    r"|(?:what(?:'s|s| is)|any)\s+(?:new\s+)?(?:(?:in\s+)?(?:my\s+)?(?:emails?|inbox|mail|gmail))"
    r"|any\s+(?:new\s+)?(?:emails?|mail)\b"
    r"|inbox\s*(?:please)?\s*"
    r")\s*[.!]?\s*$",
    re.I,
)

# Read one: "read email 2" / "open the email about invoice"
_READ_ONE_RE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:read|open|show)\s+(?:the\s+)?(?:email|e-?mail|mail|message)\s+"
    r"(?:(?:number\s+|#)?(\d+)|(?:about|from|with subject)\s+(.+?))"
    r"\s*[.!]?\s*$",
    re.I,
)

# Draft / write in chat — NOT send
_DRAFT_RE = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?"
    r"(?:"
    r"(?:write|draft|compose)\s+(?:(?:me\s+)?(?:an?\s+)?)?(?:email|e-?mail|mail|gmail)"
    r"|(?:email|e-?mail|mail)\s+(?!send\b)"
    r")\s*(?:to\s+)?(.+?)\s*$",
    re.I,
)

_SEND_BLOCK = re.compile(
    r"\b(send|deliver|actually\s+send|send\s+it|fire\s+it\s+off)\b",
    re.I,
)


def _call_gmail(fn_name: str, args: dict[str, Any]) -> dict[str, Any]:
    last_err: Exception | None = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import gmail_actions  # type: ignore

            fn = getattr(gmail_actions, fn_name)
            raw = fn(args)
            try:
                return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception:
                return {"ok": False, "error": str(raw)[:300]}
        except Exception as exc:
            last_err = exc
            continue
    return {"ok": False, "error": f"gmail plugin unavailable: {last_err or 'not found'}"}


def _parse_draft(text: str) -> dict[str, str] | None:
    """Extract contact + intent from draft/write/email phrases."""
    t = (text or "").strip()
    if not t or _SEND_BLOCK.search(t):
        return None
    # Explicit send requests should not hard-route to draft
    if re.search(r"^\s*(?:please\s+)?send\s+(?:an?\s+)?(?:email|e-?mail|gmail|mail)\b", t, re.I):
        return None

    m = _DRAFT_RE.match(t)
    if not m:
        # "write Ali an email saying…"
        m2 = re.match(
            r"^\s*(?:please\s+)?(?:write|draft|compose)\s+(\w[\w\s]{0,40}?)\s+"
            r"(?:an?\s+)?(?:email|e-?mail|mail)\s+(?:saying|about|that|:)\s*(.+)$",
            t,
            re.I,
        )
        if m2:
            return {"contact": m2.group(1).strip(" .,!"), "body": m2.group(2).strip()}
        return None

    rest = m.group(1).strip(" .,!;:")
    contact = ""
    body = rest

    # Patterns: "to Ali saying X" / "Ali saying X" / "Ali about X" / "Ali: X"
    m_to = re.match(
        r"^(?:to\s+)?(.+?)\s+(?:saying|about|that|:)\s*(.+)$",
        rest,
        re.I,
    )
    if m_to:
        contact = m_to.group(1).strip(" .,!")
        body = m_to.group(2).strip()
    else:
        # "to Ali I'll be late"
        m_to2 = re.match(r"^to\s+(\w[\w\s]{0,40}?)\s+(.+)$", rest, re.I)
        if m_to2:
            contact = m_to2.group(1).strip(" .,!")
            body = m_to2.group(2).strip()
        elif re.match(r"^(?:about|regarding)\s+", rest, re.I):
            contact = ""
            body = rest

    contact = re.sub(
        r"\b(please|thanks|thank you|for me|in chat|in the chat)\b",
        "",
        contact,
        flags=re.I,
    ).strip(" .,!")
    if not body:
        return None
    return {"contact": contact, "body": body}


def try_handle_email(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None

    # Inbox list
    if _INBOX_RE.match(t):
        result = _call_gmail("gmail_inbox", {"query": "in:inbox", "max": 8})
        tools = [{"name": "gmail_inbox", "preview": "inbox"}]
        msg = result.get("chat_text") or result.get("message") or result.get("error") or "Could not read email."
        return {
            "text": msg,
            "tools": tools,
            "run_id": None,
            "memories_saved": [],
            "email_routed": True,
            "email_result": result,
        }

    # Read one
    m_one = _READ_ONE_RE.match(t)
    if m_one:
        args: dict[str, Any] = {}
        if m_one.group(1):
            args["index"] = int(m_one.group(1))
        elif m_one.group(2):
            args["query"] = m_one.group(2).strip(" .,!")
        result = _call_gmail("gmail_read_mail", args)
        tools = [{"name": "gmail_read_mail", "preview": str(args)}]
        msg = result.get("chat_text") or result.get("message") or result.get("error") or "Could not read that email."
        return {
            "text": msg,
            "tools": tools,
            "run_id": None,
            "memories_saved": [],
            "email_routed": True,
            "email_result": result,
        }

    # Draft in chat
    draft = _parse_draft(t)
    if draft:
        result = _call_gmail("gmail_draft", {
            "contact": draft.get("contact") or "",
            "body": draft["body"],
            "tone": "friendly",
        })
        tools = [{"name": "gmail_draft", "preview": (draft.get("contact") or "draft")[:40]}]
        msg = result.get("chat_text") or result.get("message") or result.get("error") or "Could not draft."
        return {
            "text": msg,
            "tools": tools,
            "run_id": None,
            "memories_saved": [],
            "email_routed": True,
            "email_result": result,
        }

    return None


def hermes_email_hint(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return text
    low = t.lower()
    if not re.search(r"\b(email|e-?mail|gmail|inbox|mail)\b", low):
        return text
    if _SEND_BLOCK.search(t) and re.search(r"\b(email|gmail|mail)\b", low):
        return (
            "[HARD RULE] User wants to SEND email. Use gmail_send only after a clear send request, "
            "recipient must be in Skills/Memory, phone ALLOW required. "
            "Otherwise prefer gmail_draft (chat only).\n\n"
            f"{t}"
        )
    if re.search(r"\b(check|read|inbox|any (?:new )?mail|emails?\b)", low):
        return (
            "[HARD RULE] User wants to READ email. Call gmail_inbox (list) or gmail_read_mail (one). "
            "Summarize in chat. Do not open compose. Do not send.\n\n"
            f"{t}"
        )
    if re.search(r"\b(write|draft|compose|email .+ saying|mail .+ that)\b", low):
        return (
            "[HARD RULE] User wants an email DRAFT in chat. Call gmail_draft with a polished human body. "
            "Show To/Subject/Body in chat. NEVER gmail_send. NEVER type into Gmail UI.\n\n"
            f"{t}"
        )
    return (
        "[HINT] For email: gmail_inbox / gmail_read_mail to read; gmail_draft to write in chat (never sends).\n\n"
        f"{t}"
    )
