"""Gmail read + chat drafts (+ optional phone-approved send).

Default for Jarvis: read inbox and draft email text IN CHAT.
Never put drafts into the Gmail compose UI unless the user explicitly asks to send.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from . import browser_actions as ba
from . import tools as base

JARVIS_BASE = (
    __import__("os").environ.get("JARVIS_BASE_URL")
    or __import__("os").environ.get("JARVIS_HUD_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")
JARVIS_TOKEN = __import__("os").environ.get("JARVIS_HUD_TOKEN") or "jarvis-9f2517"

_PENDING_PATH = Path(__import__("os").environ.get("LOCALAPPDATA", "")) / "hermes" / "jarvis_gmail_pending.json"

_INBOX_SCRAPE_JS = r"""
(() => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  return (async () => {
    await sleep(300);
    const rows = [
      ...document.querySelectorAll('tr.zA'),
      ...document.querySelectorAll('div[role="main"] div[role="row"]'),
    ];
    const seen = new Set();
    const messages = [];
    for (const row of rows) {
      if (messages.length >= 12) break;
      const sender =
        clean(row.querySelector('.yW span[email]')?.getAttribute('email'))
        || clean(row.querySelector('.yW .zF')?.getAttribute('name'))
        || clean(row.querySelector('.yW span')?.textContent)
        || clean(row.querySelector('[email]')?.getAttribute('email'))
        || clean(row.querySelector('span[name]')?.getAttribute('name'));
      const subject =
        clean(row.querySelector('.y6 span.bog')?.textContent)
        || clean(row.querySelector('span.bqe')?.textContent)
        || clean(row.querySelector('[data-thread-id] span')?.textContent);
      const snippet =
        clean(row.querySelector('.y2')?.textContent)
        || clean(row.querySelector('.y6 .y2')?.textContent)
        || '';
      const date =
        clean(row.querySelector('.xW span')?.getAttribute('title'))
        || clean(row.querySelector('.xW span')?.textContent)
        || clean(row.querySelector('span[title*=":"]')?.getAttribute('title'))
        || '';
      const unread = row.classList.contains('zE') || row.getAttribute('aria-label')?.toLowerCase().includes('unread');
      if (!sender && !subject) continue;
      const key = (sender + '|' + subject + '|' + snippet).slice(0, 180);
      if (seen.has(key)) continue;
      seen.add(key);
      messages.push({
        from: sender || '(unknown)',
        subject: subject || '(no subject)',
        snippet: snippet.replace(/^[\-–—]\s*/, '').slice(0, 220),
        date,
        unread: !!unread,
        source: 'gmail_browser',
      });
    }
    return {
      ok: messages.length > 0,
      count: messages.length,
      messages,
      url: location.href,
      title: document.title || '',
      error: messages.length ? null : 'No inbox rows found — open Gmail and sign in on PC Chrome.',
    };
  })();
})()
"""

_OPEN_THREAD_JS = r"""
((want) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const needle = clean(want || '');
  return (async () => {
    await sleep(200);
    const rows = [...document.querySelectorAll('tr.zA')];
    let hit = null;
    for (const row of rows) {
      const blob = clean(row.innerText || '');
      if (needle && blob.includes(needle)) { hit = row; break; }
    }
    if (!hit && rows[0]) hit = rows[0];
    if (!hit) return {ok:false, error:'No matching email row to open'};
    hit.click();
    await sleep(900);
    const main = document.querySelector('[role="main"]') || document.body;
    const text = clean(main.innerText || '').slice(0, 6000);
    const subject = clean(document.querySelector('h2.hP')?.textContent)
      || clean(document.querySelector('h2')?.textContent)
      || '';
    const from = clean(document.querySelector('span.gD')?.getAttribute('email'))
      || clean(document.querySelector('span.gD')?.textContent)
      || '';
    return {ok:true, from, subject, body: text, source:'gmail_browser'};
  })();
})(%s)
"""

_GMAIL_SEND_JS = r"""
(() => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const findSend = () => {
    const candidates = [
      ...document.querySelectorAll('[role="button"]'),
      ...document.querySelectorAll('div[data-tooltip]'),
      ...document.querySelectorAll('button'),
    ];
    for (const el of candidates) {
      const t = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('data-tooltip') || '') + ' ' + (el.textContent || '')).toLowerCase();
      if (/\bsend\b/.test(t) && !/schedule|send later|undo/.test(t)) return el;
    }
    // Gmail shortcut: Ctrl/Cmd+Enter is handled separately; DOM fallback
    return document.querySelector('div.T-I.J-J5-Ji.aoO.v7.T-I-atl.L3')
      || document.querySelector('[data-tooltip*="Send" i]');
  };
  return (async () => {
    await sleep(400);
    const btn = findSend();
    if (!btn) return {ok:false, error:'Gmail Send button not found — is compose open and signed in?'};
    btn.click();
    await sleep(600);
    return {ok:true, clicked:true};
  })();
})()
"""


def _jarvis_request(method: str, path: str, body: dict | None = None) -> dict:
    url = JARVIS_BASE + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Jarvis-Token": JARVIS_TOKEN,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _pending() -> dict:
    try:
        return json.loads(_PENDING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _set_pending(data: dict) -> None:
    _PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PENDING_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clear_pending() -> None:
    try:
        if _PENDING_PATH.is_file():
            _PENDING_PATH.unlink()
    except Exception:
        pass


def _require_gmail_connected() -> dict | None:
    """Return error dict if Gmail is not connected in the Connect HUD."""
    res = _jarvis_request("GET", "/api/connections/status/gmail")
    if not res.get("connected"):
        return {
            "ok": False,
            "error": (
                "Gmail is not connected. Open CONNECT APPS in the Jarvis HUD, "
                "tap CONNECT on Gmail, sign in on the PC Chrome window, then try again."
            ),
        }
    return None


def _emails_from_memory() -> list[dict]:
    from . import memory_api

    res = memory_api._req("GET", "")
    out = []
    for f in res.get("facts") or []:
        if not isinstance(f, dict):
            continue
        email = (f.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        out.append({
            "title": f.get("title") or f.get("value") or email,
            "email": email,
            "id": f.get("id"),
        })
    return out


def _resolve_recipient(contact_q: str, email_arg: str | None) -> dict:
    """Only allow emails that exist on a Skills/Memory contact."""
    from . import memory_api

    allowed = _emails_from_memory()
    allowed_map = {c["email"]: c for c in allowed}

    if email_arg:
        em = email_arg.strip().lower()
        if em not in allowed_map:
            return {
                "ok": False,
                "error": (
                    f"'{em}' is not saved in Skills / Memory. "
                    "I only email addresses you gave me. Add it under Skills first."
                ),
                "allowed_emails": [c["email"] for c in allowed],
            }
        return {"ok": True, "email": em, "display": allowed_map[em].get("title") or em}

    q = (contact_q or "").strip()
    if not q:
        return {
            "ok": False,
            "error": "Say who to email (a name saved with an email in Skills / Memory).",
            "allowed_emails": [
                {"name": c["title"], "email": c["email"]} for c in allowed
            ],
        }

    # Direct email typed as contact — still must be in memory
    if "@" in q:
        em = q.lower().replace(" ", "")
        if em not in allowed_map:
            return {
                "ok": False,
                "error": f"'{em}' is not a saved email in Skills / Memory.",
                "allowed_emails": [c["email"] for c in allowed],
            }
        return {"ok": True, "email": em, "display": allowed_map[em].get("title") or em}

    resolved = memory_api.resolve_contact(q)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": f"No Skills / Memory contact matched '{q}'.",
            "allowed_emails": [
                {"name": c["title"], "email": c["email"]} for c in allowed
            ],
        }
    contact = resolved.get("contact") or {}
    email = (contact.get("email") or "").strip().lower()
    display = contact.get("title") or contact.get("value") or q
    if not email or email not in allowed_map:
        return {
            "ok": False,
            "error": (
                f"I know {display}, but no email is saved for them in Skills / Memory. "
                "Add their Gmail/email there first."
            ),
            "contact": display,
        }
    return {"ok": True, "email": email, "display": display}


def _compose_url(to: str, subject: str, body: str) -> str:
    q = urllib.parse.urlencode({
        "view": "cm",
        "fs": "1",
        "to": to,
        "su": subject or "",
        "body": body or "",
    })
    return f"https://mail.google.com/mail/?{q}"


def _poll_phone_approval(approval_id: str, wait_seconds: float = 120.0) -> str:
    deadline = time.time() + max(5.0, wait_seconds)
    while time.time() < deadline:
        local = _pending()
        if local.get("approval_id") == approval_id and local.get("decision") in ("allow", "deny"):
            return str(local["decision"])
        res = _jarvis_request("GET", f"/api/pc_approval/{approval_id}")
        dec = (res.get("decision") or "").lower()
        if dec in ("allow", "deny"):
            local = _pending()
            if local.get("approval_id") == approval_id:
                local["decision"] = dec
                _set_pending(local)
            return dec
        time.sleep(0.8)
    return "timeout"


def _format_inbox_chat(messages: list[dict], source: str) -> str:
    if not messages:
        return "I couldn't find any emails to show."
    lines = [f"Here are your latest emails ({source}):", ""]
    for i, m in enumerate(messages, 1):
        unread = " · unread" if m.get("unread") else ""
        from_ = (m.get("from") or "?").strip()
        subj = (m.get("subject") or "(no subject)").strip()
        snip = (m.get("snippet") or "").strip()
        date = (m.get("date") or "").strip()
        bit = f"{i}. {from_} — {subj}"
        if date:
            bit += f" ({date})"
        bit += unread
        lines.append(bit)
        if snip:
            lines.append(f"   {snip[:160]}")
    lines.append("")
    lines.append("Say which one to open (number or subject) and I'll read it in chat.")
    return "\n".join(lines)


def _inbox_via_api(query: str, max_results: int) -> dict:
    body: dict[str, Any] = {"app": "gmail", "query": query or "in:inbox"}
    res = _jarvis_request("POST", "/api/connections/query", body)
    if not res.get("ok"):
        return res
    # Normalize shapes from connector service
    messages = res.get("messages") or res.get("items") or res.get("results") or []
    if isinstance(messages, dict):
        messages = messages.get("messages") or []
    out = []
    for m in messages[:max_results]:
        if not isinstance(m, dict):
            continue
        out.append({
            "id": m.get("id"),
            "from": m.get("from") or m.get("sender"),
            "subject": m.get("subject") or m.get("title"),
            "snippet": m.get("snippet") or m.get("preview") or "",
            "date": m.get("date"),
            "unread": m.get("unread"),
            "source": "gmail_api",
        })
    return {"ok": True, "messages": out, "source": "gmail_api", "raw": res}


def _inbox_via_browser() -> dict:
    page = ba._ensure_page("https://mail.google.com/mail/u/0/#inbox", "mail.google.com")
    if isinstance(page, str):
        return {"ok": False, "error": page}
    ba._activate_page(page)
    time.sleep(1.0)
    try:
        result = ba._eval(page["webSocketDebuggerUrl"], _INBOX_SCRAPE_JS)
    except Exception as exc:
        return {"ok": False, "error": f"Could not read Gmail tab: {exc}"}
    if not isinstance(result, dict):
        return {"ok": False, "error": "Gmail scrape returned nothing"}
    return result


def gmail_inbox(args: dict, **kwargs) -> str:
    """List recent emails for chat — API if linked, else open Gmail in Chrome and scrape."""
    max_results = 8
    try:
        max_results = max(1, min(int(args.get("max") or args.get("limit") or 8), 15))
    except (TypeError, ValueError):
        max_results = 8
    query = (args.get("query") or args.get("search") or "in:inbox").strip() or "in:inbox"

    api = _inbox_via_api(query, max_results)
    messages = api.get("messages") if api.get("ok") else []
    source = "Gmail API"
    if not messages:
        browser = _inbox_via_browser()
        if browser.get("ok") and browser.get("messages"):
            messages = browser["messages"][:max_results]
            source = "Gmail in Chrome"
        elif not api.get("ok"):
            err = browser.get("error") or api.get("error") or "Could not read email."
            hint = (
                " Open Gmail in the debug Chrome window and sign in, "
                "or connect Gmail in the Jarvis CONNECT page."
            )
            return json.dumps({"ok": False, "error": err + hint, "api": api, "browser": browser})

    chat = _format_inbox_chat(messages, source)
    return json.dumps({
        "ok": True,
        "sent": False,
        "source": source,
        "count": len(messages),
        "messages": messages,
        "chat_text": chat,
        "message": chat,
    })


def gmail_read_mail(args: dict, **kwargs) -> str:
    """Read one email into chat (API by id, or open matching thread in Chrome)."""
    mid = (args.get("id") or args.get("message_id") or "").strip()
    needle = (args.get("subject") or args.get("query") or args.get("search") or "").strip()
    index = args.get("index") or args.get("number")

    if mid:
        res = _jarvis_request("POST", "/api/connections/read", {"app": "gmail", "id": mid})
        if res.get("ok"):
            from_ = res.get("from") or "?"
            subj = res.get("subject") or "(no subject)"
            body = (res.get("body") or res.get("snippet") or "").strip()
            chat = (
                f"Email from {from_}\n"
                f"Subject: {subj}\n\n"
                f"{body[:3500]}"
            )
            return json.dumps({
                "ok": True,
                "sent": False,
                "source": "gmail_api",
                "from": from_,
                "subject": subj,
                "body": body[:8000],
                "chat_text": chat,
                "message": chat,
            })

    # Browser path: open inbox and click matching / Nth row
    page = ba._ensure_page("https://mail.google.com/mail/u/0/#inbox", "mail.google.com")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    ba._activate_page(page)
    time.sleep(0.8)

    if index is not None and not needle:
        try:
            n = int(index)
            scrape = ba._eval(page["webSocketDebuggerUrl"], _INBOX_SCRAPE_JS)
            msgs = (scrape or {}).get("messages") or []
            if 1 <= n <= len(msgs):
                needle = msgs[n - 1].get("subject") or msgs[n - 1].get("from") or ""
        except Exception:
            pass

    want = json.dumps(needle or "")
    try:
        result = ba._eval(page["webSocketDebuggerUrl"], _OPEN_THREAD_JS % want)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Could not open email: {exc}"})
    if not (isinstance(result, dict) and result.get("ok")):
        return json.dumps({
            "ok": False,
            "error": (result or {}).get("error") if isinstance(result, dict) else "Read failed",
        })

    from_ = result.get("from") or "?"
    subj = result.get("subject") or "(no subject)"
    body = (result.get("body") or "").strip()
    # Trim Gmail chrome noise a bit
    body = re.sub(r"\b(Inbox|Starred|Sent|Drafts|Search mail)\b", " ", body, flags=re.I)
    body = re.sub(r"\s{2,}", " ", body).strip()[:3500]
    chat = f"Email from {from_}\nSubject: {subj}\n\n{body}"
    return json.dumps({
        "ok": True,
        "sent": False,
        "source": "gmail_browser",
        "from": from_,
        "subject": subj,
        "body": body,
        "chat_text": chat,
        "message": chat,
    })


def _humanize_body(display: str, intent: str, tone: str) -> str:
    """Turn short intent into a natural email body (never auto-sends)."""
    text = (intent or "").strip()
    if not text:
        return ""
    # Already looks like a full email
    if "\n" in text or re.search(r"^(hi|hello|dear|hey)\b", text, re.I):
        return text
    if text[0].islower():
        text = text[0].upper() + text[1:]
    core = text.rstrip(".!?") + "."
    name = (display or "there").split()[0]
    tone_l = (tone or "friendly").lower()
    if tone_l in ("formal", "professional"):
        return (
            f"Dear {name},\n\n"
            f"{core}\n\n"
            f"Please let me know if you have any questions.\n\n"
            f"Best regards"
        )
    if tone_l in ("short", "brief", "concise"):
        return f"Hi {name},\n\n{core}\n\nThanks"
    return (
        f"Hi {name},\n\n"
        f"Hope you're doing well. {core}\n\n"
        f"Thanks,\n"
        f"(draft — not sent)"
    )


def gmail_draft(args: dict, **kwargs) -> str:
    """Write a human email draft in chat only. Does NOT open Gmail and does NOT send."""
    contact_q = (
        args.get("contact")
        or args.get("to")
        or args.get("name")
        or args.get("friend")
        or ""
    ).strip()
    email_arg = (args.get("email") or "").strip() or None
    subject = (args.get("subject") or args.get("title") or "").strip()
    intent = (
        args.get("body")
        or args.get("message")
        or args.get("text")
        or args.get("about")
        or args.get("intent")
        or ""
    ).strip()
    tone = (args.get("tone") or "friendly").strip() or "friendly"

    if not intent:
        return json.dumps({
            "ok": False,
            "error": "Tell me what the email should say (topic or full message).",
        })

    display = contact_q or "there"
    to_email = email_arg
    who = None
    if contact_q or email_arg:
        who = _resolve_recipient(contact_q, email_arg)
        if who.get("ok"):
            display = who["display"]
            to_email = who["email"]
        # If contact unknown, still draft to the spoken name — chat-only, no send

    body = _humanize_body(display, intent, tone)
    if not subject:
        # Short subject from first clause
        subj_src = re.split(r"[.!?\n]", intent)[0].strip()
        subject = (subj_src[:72] or "Quick note").rstrip(" ,;")
        if subject and subject[0].islower():
            subject = subject[0].upper() + subject[1:]

    to_line = f"{display} <{to_email}>" if to_email else display
    chat = (
        "Here's a draft (not sent — copy/edit as you like):\n\n"
        f"To: {to_line}\n"
        f"Subject: {subject}\n\n"
        f"{body}"
    )
    return json.dumps({
        "ok": True,
        "sent": False,
        "draft_only": True,
        "to": to_email,
        "contact": display,
        "subject": subject,
        "body": body,
        "chat_text": chat,
        "message": chat,
        "note": "Draft shown in chat only. I did not open Gmail and did not send.",
    })


def gmail_send(args: dict, **kwargs) -> str:
    """
    Send ONLY when the user explicitly asks to send.
    Prefer gmail_draft for normal 'write/email saying…' requests.
    """
    contact_q = (
        args.get("contact")
        or args.get("to")
        or args.get("name")
        or args.get("friend")
        or ""
    ).strip()
    email_arg = (args.get("email") or "").strip() or None
    subject = (args.get("subject") or args.get("title") or "").strip()
    body = (args.get("body") or args.get("message") or args.get("text") or "").strip()
    if not body:
        return json.dumps({"ok": False, "error": "message/body is required"})
    if not subject:
        subject = "Message from Jarvis"

    who = _resolve_recipient(contact_q, email_arg)
    if not who.get("ok"):
        return json.dumps(who)

    to_email = who["email"]
    display = who["display"]

    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})

    url = _compose_url(to_email, subject, body)
    opened = base._open_url_in_chrome(url, source="gmail_compose")
    if not opened.get("ok"):
        return json.dumps({"ok": False, "error": opened.get("error") or "Could not open Gmail compose"})

    time.sleep(1.6)
    page = None
    tid = opened.get("jarvis_target_id")
    if tid:
        for p in ba._pages():
            if p.get("id") == tid and p.get("webSocketDebuggerUrl"):
                page = p
                break
    if not page:
        page = ba._find_page("mail.google.com")
    if not page or not page.get("webSocketDebuggerUrl"):
        return json.dumps({
            "ok": False,
            "error": "Gmail compose opened but CDP target not ready — sign in to Gmail in that Chrome window.",
        })

    ba._activate_page(page)
    time.sleep(0.8)

    approval_id = "gmail_" + uuid.uuid4().hex[:10]
    preview = f"To: {display} <{to_email}>\nSubject: {subject}\n\n{body[:800]}"
    phone = _jarvis_request("POST", "/api/pc_approval", {
        "approval_id": approval_id,
        "kind": "gmail_send",
        "title": "SEND GMAIL?",
        "preview": preview,
        "description": (
            f"Jarvis drafted a Gmail to {display} ({to_email}) on your PC. "
            "ALLOW = send it. DENY = leave it unsent."
        ),
    })

    _set_pending({
        "approval_id": approval_id,
        "target_id": page.get("id"),
        "to": to_email,
        "display": display,
        "subject": subject,
        "body": body,
        "decision": None,
        "sent": False,
    })

    wait = args.get("wait_seconds")
    try:
        wait_seconds = float(wait if wait is not None else 120)
    except (TypeError, ValueError):
        wait_seconds = 120.0

    decision = _poll_phone_approval(approval_id, wait_seconds)
    if decision == "deny":
        _clear_pending()
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": "deny",
            "message": "You denied the Gmail send on your phone. Not sent.",
        })
    if decision != "allow":
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": decision,
            "approval_id": approval_id,
            "message": (
                "Still waiting for phone ALLOW (or timed out). "
                "Compose is open on PC — approve on your phone HUD, then ask again to send."
            ),
            "phone_approval": phone,
        })

    page2 = None
    if tid:
        for p in ba._pages():
            if p.get("id") == tid and p.get("webSocketDebuggerUrl"):
                page2 = p
                break
    page2 = page2 or ba._find_page("mail.google.com") or page
    try:
        result = ba._eval(page2["webSocketDebuggerUrl"], _GMAIL_SEND_JS)
    except Exception as e:
        return json.dumps({"ok": False, "sent": False, "error": f"Send click failed: {e}"})

    if not (isinstance(result, dict) and result.get("ok")):
        return json.dumps({
            "ok": False,
            "sent": False,
            "error": (result or {}).get("error") if isinstance(result, dict) else "Send failed",
            "result": result,
        })

    _clear_pending()
    try:
        _jarvis_request("POST", f"/api/pc_approval/{approval_id}/consume", {"status": "sent"})
    except Exception:
        pass

    return json.dumps({
        "ok": True,
        "sent": True,
        "to": to_email,
        "contact": display,
        "subject": subject,
        "message": f"Sent Gmail to {display} ({to_email}).",
    })


def gmail_status(args: dict, **kwargs) -> str:
    conn = _jarvis_request("GET", "/api/connections/status/gmail")
    emails = _emails_from_memory()
    return json.dumps({
        "ok": True,
        "connected": bool(conn.get("connected")),
        "connection": conn,
        "emailable_contacts": emails,
        "note": (
            "Prefer gmail_inbox / gmail_read_mail to read, and gmail_draft to write in chat "
            "(never sends). Use gmail_send ONLY if the user explicitly says send. "
            "API link optional — inbox can also be read from signed-in Gmail in Chrome."
        ),
    })
