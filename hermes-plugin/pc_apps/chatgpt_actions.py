"""ChatGPT in PC Chrome — Jarvis-owned sessions only; phone approval before send."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from . import browser_actions as ba
from . import tab_registry
from . import tools as base

CHATGPT_URL = "https://chatgpt.com/"
CHATGPT_NEEDLES = ("chatgpt.com", "chat.openai.com")
SESSION_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "jarvis_chatgpt_session.json"
PENDING_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "jarvis_chatgpt_pending.json"

# Jarvis voice server (HUD approvals). Override with JARVIS_BASE_URL if needed.
JARVIS_BASE = (
    os.environ.get("JARVIS_BASE_URL")
    or os.environ.get("JARVIS_HUD_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")
JARVIS_TOKEN = os.environ.get("JARVIS_HUD_TOKEN") or "jarvis-9f2517"


_NEW_CHAT_JS = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  // Never click sidebar history /c/ links — only New chat.
  const byTest = document.querySelector('[data-testid="create-new-chat-button"]')
    || document.querySelector('a[data-testid="create-new-chat-button"]');
  if (byTest) { byTest.click(); await sleep(900); return {ok:true, via:'testid'}; }

  const candidates = Array.from(document.querySelectorAll('a,button,[role="button"]'));
  const neu = candidates.find(el => {
    const t = ((el.getAttribute('aria-label')||'') + ' ' + (el.textContent||'')).trim();
    return /^new chat$/i.test(t) || /\bnew chat\b/i.test(t);
  });
  if (neu) { neu.click(); await sleep(900); return {ok:true, via:'label'}; }

  // Already on a blank compose page?
  const box = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]#prompt-textarea')
    || document.querySelector('textarea[name="prompt-textarea"]')
    || document.querySelector('[data-testid="prompt-textarea"]');
  if (box) return {ok:true, via:'already_blank', note:'composer present'};

  return {ok:false, error:'Could not find New chat control. Stay on ChatGPT home and retry.'};
})()
"""

_DRAFT_JS = r"""
(async (message) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const text = String(message || '');
  if (!text) return {ok:false, error:'empty message'};

  // Refuse if this looks like a history list click context — we only type in composer
  let box = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]#prompt-textarea')
    || document.querySelector('textarea[name="prompt-textarea"]')
    || document.querySelector('[data-testid="prompt-textarea"]')
    || document.querySelector('div.ProseMirror[contenteditable="true"]')
    || document.querySelector('form textarea')
    || document.querySelector('div[contenteditable="true"][role="textbox"]');

  if (!box) return {ok:false, error:'ChatGPT composer not found — are you logged in on the PC?'};

  box.focus();
  await sleep(80);
  // Clear existing draft only in composer (not chat history)
  try {
    if (box.isContentEditable || box.getAttribute('contenteditable') === 'true') {
      box.textContent = '';
      box.innerHTML = '';
      box.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
      await sleep(40);
      // Insert in chunks so long dictation is not truncated by one insertText call
      const CHUNK = 600;
      for (let i = 0; i < text.length; i += CHUNK) {
        const piece = text.slice(i, i + CHUNK);
        try { document.execCommand('insertText', false, piece); } catch (e) {}
        await sleep(20);
      }
      const now = (box.innerText || box.textContent || '').trim();
      if (!now || now.length < Math.min(12, text.length)) {
        box.textContent = text;
        box.dispatchEvent(new InputEvent('input', {bubbles:true, data:text, inputType:'insertText'}));
      }
    } else {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      if (setter) setter.call(box, text); else box.value = text;
      box.dispatchEvent(new Event('input', {bubbles:true}));
      box.dispatchEvent(new Event('change', {bubbles:true}));
    }
  } catch (e) {
    return {ok:false, error: String(e)};
  }
  await sleep(120);
  const typed = (box.innerText || box.textContent || box.value || '').trim();
  return {
    ok: typed.length > 0,
    typed: typed.slice(0, 2000),
    typed_len: typed.length,
    expected_len: text.length,
    complete: typed.length >= Math.floor(text.length * 0.9),
    sent: false,
    url: location.href,
    note: 'Draft only — NOT sent. Waiting for phone ALLOW.'
  };
})(%s)
"""

_SEND_JS = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const sendBtn = document.querySelector('button[data-testid="send-button"]')
    || document.querySelector('button[aria-label="Send message"]')
    || document.querySelector('button[aria-label="Send prompt"]')
    || document.querySelector('form button[type="submit"]');
  if (sendBtn && !sendBtn.disabled) {
    sendBtn.click();
    await sleep(400);
    return {ok:true, via:'button', sent:true};
  }
  // Fallback: Enter in composer (ChatGPT treats Enter as send when not shift)
  const box = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]#prompt-textarea')
    || document.querySelector('textarea[name="prompt-textarea"]')
    || document.querySelector('div.ProseMirror[contenteditable="true"]');
  if (!box) return {ok:false, error:'Composer/send button not found'};
  box.focus();
  box.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
  box.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
  await sleep(400);
  return {ok:true, via:'enter', sent:true};
})()
"""


def _load_json(path: Path, default: dict) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return dict(default)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _session() -> dict:
    return _load_json(SESSION_PATH, {"target_id": None, "url": "", "opened_at": None})


def _set_session(target_id: str, url: str) -> None:
    _save_json(SESSION_PATH, {
        "target_id": target_id,
        "url": url,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


def _clear_session() -> None:
    _save_json(SESSION_PATH, {"target_id": None, "url": "", "opened_at": None})


def _pending() -> dict:
    return _load_json(PENDING_PATH, {})


def _set_pending(data: dict) -> None:
    _save_json(PENDING_PATH, data)


def _clear_pending() -> None:
    if PENDING_PATH.is_file():
        try:
            PENDING_PATH.unlink()
        except Exception:
            _save_json(PENDING_PATH, {})


def _is_chatgpt_page(page: dict) -> bool:
    blob = f"{page.get('url','')} {page.get('title','')}".lower()
    return any(n in blob for n in CHATGPT_NEEDLES)


def _find_jarvis_chatgpt_page() -> dict | None:
    """Return live CDP page only if it is ChatGPT AND Jarvis opened/owns it."""
    sess = _session()
    tid = sess.get("target_id")
    pages = ba._pages()
    tab_registry.reconcile_with_live(pages)
    jarvis_ids = tab_registry.jarvis_target_ids()

    if tid:
        for p in pages:
            if p.get("id") == tid and _is_chatgpt_page(p) and p.get("webSocketDebuggerUrl"):
                # Still treat as Jarvis-owned if we recorded the session (even if
                # tab registry was pruned) — session file is the source of truth.
                return p
        # Stale session id
        _clear_session()

    # Fallback: jarvis-opened chatgpt tab from tab registry
    for p in pages:
        if not _is_chatgpt_page(p):
            continue
        if p.get("id") in jarvis_ids and p.get("webSocketDebuggerUrl"):
            _set_session(p["id"], p.get("url") or CHATGPT_URL)
            return p
    return None


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
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code}: {err[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _request_phone_approval(approval_id: str, preview: str) -> dict:
    return _jarvis_request("POST", "/api/pc_approval", {
        "approval_id": approval_id,
        "kind": "chatgpt_send",
        "title": "SEND TO CHATGPT?",
        "preview": preview,
        "description": (
            "Jarvis drafted a ChatGPT message on your PC. "
            "ALLOW = send it. DENY = leave it unsent."
        ),
    })


def _poll_phone_approval(approval_id: str, wait_seconds: float = 120.0) -> str:
    """Return allow|deny|timeout|error."""
    deadline = time.time() + max(5.0, wait_seconds)
    while time.time() < deadline:
        # Local pending file may be updated by Jarvis server via shared path
        # OR we poll Jarvis API
        local = _pending()
        if local.get("approval_id") == approval_id and local.get("decision") in ("allow", "deny"):
            return str(local["decision"])

        res = _jarvis_request("GET", f"/api/pc_approval/{approval_id}")
        dec = (res.get("decision") or "").lower()
        if dec in ("allow", "deny"):
            # mirror onto local pending
            local = _pending()
            if local.get("approval_id") == approval_id:
                local["decision"] = dec
                _set_pending(local)
            return dec
        if res.get("error") and "not found" in str(res.get("error")).lower():
            # keep waiting — race with create
            pass
        time.sleep(0.8)
    return "timeout"


def _ensure_new_or_jarvis_session(force_new: bool = False) -> dict | str:
    """Get a Jarvis-owned ChatGPT page. Opens new session unless reusing ours."""
    err = base._ensure_cdp()
    if err:
        return err

    if not force_new:
        page = _find_jarvis_chatgpt_page()
        if page:
            ba._activate_page(page)
            return page

    # Always open a NEW tab (never hijack user's existing ChatGPT tab)
    opened = base._open_url_in_chrome(CHATGPT_URL, source="chatgpt_new_session")
    if not opened.get("ok"):
        return opened.get("error") or "Could not open ChatGPT"
    time.sleep(2.2)

    page = None
    tid = opened.get("jarvis_target_id")
    if tid:
        for p in ba._pages():
            if p.get("id") == tid and p.get("webSocketDebuggerUrl"):
                page = p
                break
    if not page:
        # Prefer newly registered jarvis chatgpt tab
        page = _find_jarvis_chatgpt_page()
    if not page:
        # Last resort: page from open result target
        t = opened.get("target") or {}
        if isinstance(t, dict) and t.get("webSocketDebuggerUrl"):
            page = t
            tid = t.get("id")

    if not page or not page.get("webSocketDebuggerUrl"):
        return "ChatGPT tab opened but CDP target not ready — wait and retry."

    if tid:
        _set_session(str(tid), page.get("url") or CHATGPT_URL)
    elif page.get("id"):
        _set_session(str(page["id"]), page.get("url") or CHATGPT_URL)

    ba._activate_page(page)
    time.sleep(0.8)
    try:
        neu = ba._eval(page["webSocketDebuggerUrl"], _NEW_CHAT_JS)
        if isinstance(neu, dict) and not neu.get("ok"):
            # still try to draft — composer may exist
            pass
    except Exception:
        pass
    time.sleep(0.6)
    return page


def chatgpt_open(args: dict, **kwargs) -> str:
    """Open ChatGPT in a Jarvis-owned session (never clicks old chats)."""
    # Reuse Jarvis-owned session if present; otherwise open a brand-new tab.
    # Never attach to a ChatGPT tab the user opened themselves.
    force_new = bool(args.get("force_new") or args.get("new_session"))
    page = _ensure_new_or_jarvis_session(force_new=force_new)
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    return json.dumps({
        "ok": True,
        "action": "chatgpt_open",
        "target_id": page.get("id"),
        "url": page.get("url"),
        "jarvis_owned": True,
        "message": (
            "ChatGPT is open in a Jarvis-owned session. "
            "I will not click previous chats in the sidebar. "
            "Use chatgpt_draft to type; send only after phone ALLOW."
        ),
    })


def chatgpt_draft(args: dict, **kwargs) -> str:
    """Type into ChatGPT composer on a Jarvis-owned session. Never sends."""
    message = (args.get("message") or args.get("text") or args.get("prompt") or "").strip()
    if not message:
        return json.dumps({"ok": False, "error": "message is required"})

    # New session every time unless Jarvis already has one open
    force_new = bool(args.get("force_new"))
    if not _find_jarvis_chatgpt_page():
        force_new = True

    page = _ensure_new_or_jarvis_session(force_new=force_new)
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})

    ba._activate_page(page)
    time.sleep(0.5)
    try:
        result = ba._eval(page["webSocketDebuggerUrl"], _DRAFT_JS % json.dumps(message))
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Draft failed: {e}"})

    if not isinstance(result, dict) or not result.get("ok"):
        return json.dumps(result if isinstance(result, dict) else {"ok": False, "error": str(result)})

    approval_id = "cgpt-" + uuid.uuid4().hex[:12]
    pending = {
        "approval_id": approval_id,
        "target_id": page.get("id"),
        "message": message,
        "typed": result.get("typed"),
        "created_at": time.time(),
        "decision": None,
        "sent": False,
    }
    _set_pending(pending)

    phone = _request_phone_approval(
        approval_id,
        f"ChatGPT draft:\n\n{message[:800]}{'…' if len(message) > 800 else ''}",
    )

    return json.dumps({
        "ok": True,
        "action": "chatgpt_draft",
        "sent": False,
        "approval_id": approval_id,
        "target_id": page.get("id"),
        "typed": result.get("typed"),
        "phone_approval": phone,
        "message": (
            "Draft is on the PC ChatGPT composer (NOT sent). "
            "An ALLOW/DENY card was sent to your phone HUD. "
            "Call chatgpt_send next — it waits for phone ALLOW before sending."
        ),
    })


def chatgpt_send(args: dict, **kwargs) -> str:
    """Send the pending ChatGPT draft ONLY after phone ALLOW."""
    wait = args.get("wait_seconds")
    try:
        wait_seconds = float(wait if wait is not None else 120)
    except (TypeError, ValueError):
        wait_seconds = 120.0

    # Hard gate: agent cannot bypass with a flag unless phone already approved
    pending = _pending()
    if not pending.get("approval_id") or pending.get("sent"):
        return json.dumps({
            "ok": False,
            "error": "No pending ChatGPT draft. Call chatgpt_draft first.",
        })

    approval_id = pending["approval_id"]
    expected_tid = pending.get("target_id")

    # If already decided allow, proceed; else wait for phone
    decision = (pending.get("decision") or "").lower()
    if decision not in ("allow", "deny"):
        decision = _poll_phone_approval(approval_id, wait_seconds)

    if decision == "deny":
        _clear_pending()
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": "deny",
            "message": "You denied the send on your phone. Draft was not sent.",
        })
    if decision != "allow":
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": decision,
            "approval_id": approval_id,
            "message": (
                "Still waiting for phone ALLOW (or timed out). "
                "Open the Jarvis HUD on your phone and tap ALLOW, then call chatgpt_send again."
            ),
        })

    # Verify still on Jarvis-owned ChatGPT tab
    page = _find_jarvis_chatgpt_page()
    if not page:
        return json.dumps({
            "ok": False,
            "error": "Jarvis ChatGPT session tab is gone. Draft was not sent.",
        })
    if expected_tid and page.get("id") != expected_tid:
        return json.dumps({
            "ok": False,
            "error": "ChatGPT tab changed — refusing to send on a different tab.",
        })

    ba._activate_page(page)
    time.sleep(0.3)
    try:
        result = ba._eval(page["webSocketDebuggerUrl"], _SEND_JS)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Send failed: {e}"})

    if not isinstance(result, dict) or not result.get("ok"):
        return json.dumps(result if isinstance(result, dict) else {"ok": False, "error": str(result)})

    pending["sent"] = True
    pending["decision"] = "allow"
    _set_pending(pending)
    # Clear so a second send cannot replay
    _clear_pending()
    _jarvis_request("POST", f"/api/pc_approval/{approval_id}/consume", {"status": "sent"})

    return json.dumps({
        "ok": True,
        "action": "chatgpt_send",
        "sent": True,
        "approval_id": approval_id,
        "result": result,
        "message": "Sent to ChatGPT after phone ALLOW.",
    })


def chatgpt_status(args: dict, **kwargs) -> str:
    page = _find_jarvis_chatgpt_page()
    return json.dumps({
        "ok": True,
        "jarvis_session_open": bool(page),
        "target_id": (page or {}).get("id"),
        "url": (page or {}).get("url"),
        "pending": {
            "approval_id": _pending().get("approval_id"),
            "decision": _pending().get("decision"),
            "has_draft": bool(_pending().get("message")),
            "preview": (_pending().get("message") or "")[:200],
        } if _pending().get("approval_id") else None,
    })
