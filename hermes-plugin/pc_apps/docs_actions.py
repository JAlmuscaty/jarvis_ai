"""Open Google Docs / Slides in PC Chrome and type — no Google API / OAuth needed.

Uses the same CDP Chrome profile (port 9222) where the user is already signed in.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import browser_actions as ba
from . import tools as base

DOCS_CREATE = "https://docs.google.com/document/create"
SLIDES_CREATE = "https://docs.google.com/presentation/create"


_WAIT_DOCS_JS = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 40; i++) {
    const href = String(location.href || '');
    const iframe = document.querySelector('iframe.docs-texteventtarget-iframe');
    const editor = document.querySelector('.kix-appview-editor, .docs-editor, .kix-page-paginated');
    if (/\/document\/d\/[\w-]+/.test(href) && (iframe || editor)) {
      return {ok:true, url: href, has_iframe: !!iframe, has_editor: !!editor};
    }
    // Still on create / about blank redirect
    await sleep(400);
  }
  return {ok:false, error:'Google Docs editor did not load. Are you signed into Google in this Chrome?', url: location.href};
})()
"""

_TYPE_DOCS_JS = r"""
(async (message) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const text = String(message || '');
  if (!text) return {ok:false, error:'empty text'};

  // Click the visible editor so Docs focuses the hidden typing iframe
  const canvas = document.querySelector('.kix-appview-editor')
    || document.querySelector('.docs-editor')
    || document.querySelector('.kix-page');
  if (canvas) {
    try {
      const r = canvas.getBoundingClientRect();
      const x = r.left + Math.min(120, r.width/3);
      const y = r.top + Math.min(120, r.height/4);
      const el = document.elementFromPoint(x, y) || canvas;
      el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
      el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
      el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
    } catch (e) {}
  }
  await sleep(200);

  const iframe = document.querySelector('iframe.docs-texteventtarget-iframe');
  let typed_via = '';
  if (iframe && iframe.contentDocument) {
    const idoc = iframe.contentDocument;
    const body = idoc.querySelector('[contenteditable="true"]') || idoc.body;
    if (body) {
      body.focus();
      await sleep(80);
      // Select-all wipe of empty doc is fine; avoid destroying existing long docs accidentally
      try { idoc.execCommand('selectAll'); } catch (e) {}
      const CHUNK = 400;
      let okChunks = 0;
      for (let i = 0; i < text.length; i += CHUNK) {
        const piece = text.slice(i, i + CHUNK);
        try {
          if (idoc.execCommand('insertText', false, piece)) okChunks++;
        } catch (e) {}
        await sleep(15);
      }
      typed_via = 'iframe_execCommand';
      return {
        ok: okChunks > 0,
        via: typed_via,
        expected_len: text.length,
        chunks: okChunks,
        url: location.href,
        note: 'Typed into Google Docs editor (Chrome). No API used.'
      };
    }
  }

  // Fallback: active element
  const ae = document.activeElement;
  if (ae && (ae.isContentEditable || ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT')) {
    ae.focus();
    try { document.execCommand('selectAll'); } catch (e) {}
    try { document.execCommand('insertText', false, text); } catch (e) {
      if (ae.isContentEditable) ae.textContent = text;
      else ae.value = text;
    }
    return {ok:true, via:'activeElement', expected_len: text.length, url: location.href};
  }

  return {
    ok: false,
    error: 'Could not find Docs typing target. Click inside the document once and ask again.',
    url: location.href
  };
})(%s)
"""

_WAIT_SLIDES_JS = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 40; i++) {
    const href = String(location.href || '');
    const editor = document.querySelector('.punch-viewer-content, .filmstrip, [aria-label*="Slide"], .sketchy-text-contenteditable');
    if (/\/presentation\/d\/[\w-]+/.test(href) && (editor || document.body)) {
      return {ok:true, url: href};
    }
    await sleep(400);
  }
  return {ok:false, error:'Google Slides editor did not load. Sign into Google in this Chrome.', url: location.href};
})()
"""

_TYPE_SLIDES_JS = r"""
(async (message) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const text = String(message || '');
  if (!text) return {ok:false, error:'empty text'};

  // Prefer title shape, else any text box, else click canvas center
  let box = document.querySelector('[aria-label*="Title"] [contenteditable="true"]')
    || document.querySelector('.sketchy-text-contenteditable[contenteditable="true"]')
    || document.querySelector('[contenteditable="true"]');

  if (!box) {
    const canvas = document.querySelector('.punch-viewer-content') || document.body;
    const r = canvas.getBoundingClientRect();
    const x = r.left + r.width/2, y = r.top + r.height/3;
    const el = document.elementFromPoint(x, y) || canvas;
    el.dispatchEvent(new MouseEvent('dblclick', {bubbles:true, clientX:x, clientY:y}));
    await sleep(300);
    box = document.querySelector('[contenteditable="true"]');
  }

  if (!box) {
    return {ok:false, error:'No Slides text box found. Double-click a text box once and ask again.', url: location.href};
  }

  box.focus();
  await sleep(80);
  try { document.execCommand('selectAll'); } catch (e) {}
  const CHUNK = 400;
  let okChunks = 0;
  for (let i = 0; i < text.length; i += CHUNK) {
    const piece = text.slice(i, i + CHUNK);
    try { if (document.execCommand('insertText', false, piece)) okChunks++; } catch (e) {}
    await sleep(15);
  }
  if (okChunks === 0) {
    try { box.innerText = text; } catch (e) {}
  }
  return {
    ok: true,
    via: 'slides_contenteditable',
    expected_len: text.length,
    url: location.href,
    note: 'Typed into Google Slides (Chrome). No API used.'
  };
})(%s)
"""


_LAST_PATH = None


def _last_path():
    import os
    from pathlib import Path
    global _LAST_PATH
    if _LAST_PATH is None:
        _LAST_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "hermes" / "jarvis_last_workspace.json"
    return _LAST_PATH


def _doc_id(url: str) -> str:
    import re
    m = re.search(r"/(?:document|presentation)/d/([\w-]+)", url or "")
    return m.group(1) if m else ""


def _remember_created(kind: str, target_id: str | None, url: str | None, title: str = "") -> None:
    """Remember the doc/deck Jarvis just created so follow-ups type into *that* one."""
    try:
        p = _last_path()
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        data = {}
    data[kind] = {"target_id": target_id or "", "url": url or "", "doc_id": _doc_id(url or ""),
                  "title": title, "ts": time.time()}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def last_created(kind: str, max_age: float = 3600.0) -> dict | None:
    """kind: 'docs' | 'slides'. Returns the record if that tab is still open."""
    try:
        p = _last_path()
        rec = (json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}).get(kind)
    except Exception:
        return None
    if not isinstance(rec, dict) or time.time() - float(rec.get("ts") or 0) > max_age:
        return None
    ws = _ws_for_record(rec)
    if not ws:
        return None
    return {**rec, "ws": ws}


def _ws_for_record(rec: dict) -> str | None:
    tid, did = rec.get("target_id"), rec.get("doc_id")
    for p in ba._pages():
        if not p.get("webSocketDebuggerUrl"):
            continue
        if (tid and p.get("id") == tid) or (did and did in (p.get("url") or "")):
            return p["webSocketDebuggerUrl"]
    return None


def _open_new_editor(create_url: str, marker: str, source: str, timeout: float = 25.0) -> tuple[dict, str | None, str | None]:
    """Open a brand-new Doc/Deck and return (opened, ws, url) for THAT tab only.

    Never falls back to another already-open document — typing (and the retry's
    select-all/delete) must only ever touch the file we just created.
    """
    before = {p.get("id") for p in ba._pages() if p.get("id")}
    opened = base._open_url_in_chrome(create_url, source=source)
    if not opened.get("ok"):
        return opened, None, None
    tid = (opened.get("target") or {}).get("id") or opened.get("jarvis_target_id")
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in ba._pages():
            pid, u = p.get("id"), p.get("url") or ""
            if marker in u and p.get("webSocketDebuggerUrl") and (
                (tid and pid == tid) or (pid and pid not in before)
            ):
                opened["jarvis_target_id"] = pid
                return opened, p["webSocketDebuggerUrl"], u
        time.sleep(0.4)
    return opened, None, None


def _set_doc_title(ws: str, title: str) -> bool:
    """Rename the Doc/Deck via its title box with real key input."""
    if not title:
        return False
    try:
        box = ba._eval(ws, r"""
        (() => {
          const el = document.querySelector('input.docs-title-input');
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {x: Math.floor(r.left + r.width/2), y: Math.floor(r.top + r.height/2)};
        })()
        """)
        if not isinstance(box, dict):
            return False
        for typ in ("mousePressed", "mouseReleased"):
            ba._cdp_call(ws, "Input.dispatchMouseEvent", {
                "type": typ, "x": box["x"], "y": box["y"], "button": "left", "clickCount": 1,
            }, timeout=5.0)
        time.sleep(0.3)
        _cdp_key(ws, "a", code="KeyA", modifiers=2, vk=65, typ="keyDown")
        _cdp_key(ws, "a", code="KeyA", modifiers=2, vk=65, typ="keyUp")
        ba._cdp_call(ws, "Input.insertText", {"text": title[:90]}, timeout=5.0)
        time.sleep(0.1)
        _cdp_key(ws, "Enter", code="Enter", vk=13, typ="keyDown")
        _cdp_key(ws, "Enter", code="Enter", vk=13, typ="keyUp")
        time.sleep(0.4)
        return True
    except Exception:
        return False


def _page_ws(opened: dict) -> str | None:
    target = opened.get("target") or {}
    ws = target.get("webSocketDebuggerUrl")
    if ws:
        return ws
    # Resolve from list by id/url
    tid = opened.get("jarvis_target_id") or target.get("id")
    url = (target.get("url") or opened.get("url") or "")[:80]
    for p in ba._pages():
        if tid and p.get("id") == tid and p.get("webSocketDebuggerUrl"):
            return p["webSocketDebuggerUrl"]
        if url and url in (p.get("url") or "") and p.get("webSocketDebuggerUrl"):
            return p["webSocketDebuggerUrl"]
    # Newest docs/slides page
    for p in reversed(ba._pages()):
        u = (p.get("url") or "").lower()
        if ("docs.google.com/document" in u or "docs.google.com/presentation" in u or "slides.google.com" in u) and p.get("webSocketDebuggerUrl"):
            return p["webSocketDebuggerUrl"]
    return None


def _wait_ws_for_docs(timeout: float = 20.0) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in ba._pages():
            u = (p.get("url") or "")
            if "/document/d/" in u and "/edit" in u and p.get("webSocketDebuggerUrl"):
                return p["webSocketDebuggerUrl"]
            if "/document/d/" in u and p.get("webSocketDebuggerUrl"):
                return p["webSocketDebuggerUrl"]
        time.sleep(0.4)
    return None


def _wait_ws_for_slides(timeout: float = 20.0) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in ba._pages():
            u = (p.get("url") or "")
            if "/presentation/d/" in u and p.get("webSocketDebuggerUrl"):
                return p["webSocketDebuggerUrl"]
            if "slides.google.com" in u and p.get("webSocketDebuggerUrl"):
                return p["webSocketDebuggerUrl"]
        time.sleep(0.4)
    return None


def _cdp_key(
    ws: str,
    key: str,
    *,
    code: str = "",
    modifiers: int = 0,
    vk: int = 0,
    text: str | None = None,
    typ: str = "keyDown",
) -> None:
    params: dict[str, Any] = {
        "type": typ,
        "key": key,
        "code": code or key,
        "windowsVirtualKeyCode": vk,
        "modifiers": modifiers,
    }
    if text is not None:
        params["text"] = text
        params["unmodifiedText"] = text
    try:
        ba._cdp_call(ws, "Input.dispatchKeyEvent", params, timeout=3.0)
    except Exception:
        pass


def _cdp_insert_text(ws: str, text: str) -> bool:
    """Legacy helper — Google Docs canvas often ignores this; prefer _type_chars_into_docs."""
    if not text:
        return False
    try:
        ba._cdp_call(ws, "Input.insertText", {"text": text}, timeout=20.0)
        return True
    except Exception:
        return False


def _clipboard_set_text(text: str) -> bool:
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value {json.dumps(text)}"],
            capture_output=True,
            timeout=8,
            text=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def _clipboard_get_text() -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True,
            timeout=8,
            text=True,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _mouse_click_docs_editor(ws: str) -> dict:
    """Real CDP mouse click into the Docs canvas (required for typing to land)."""
    try:
        box = ba._eval(ws, r"""
        (() => {
          const c = document.querySelector('.kix-appview-editor')
            || document.querySelector('.docs-editor')
            || document.querySelector('.kix-page');
          if (!c) return null;
          const r = c.getBoundingClientRect();
          return {
            x: Math.floor(r.left + Math.min(180, Math.max(60, r.width * 0.22))),
            y: Math.floor(r.top + Math.min(180, Math.max(60, r.height * 0.22))),
          };
        })()
        """)
    except Exception:
        box = None
    if not isinstance(box, dict) or "x" not in box:
        return {"ok": False}
    x, y = int(box["x"]), int(box["y"])
    try:
        ba._cdp_call(ws, "Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1,
        }, timeout=5.0)
        ba._cdp_call(ws, "Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1,
        }, timeout=5.0)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    time.sleep(0.2)
    try:
        ba._eval(ws, r"""
        (() => {
          const iframe = document.querySelector('iframe.docs-texteventtarget-iframe');
          if (!iframe) return false;
          try { iframe.focus(); } catch (e) {}
          try {
            const box = iframe.contentDocument && iframe.contentDocument.querySelector('[contenteditable="true"]');
            if (box) box.focus();
          } catch (e) {}
          return true;
        })()
        """)
    except Exception:
        pass
    time.sleep(0.15)
    return {"ok": True, "x": x, "y": y}


def _key_events_for(text: str) -> list[dict]:
    events: list[dict] = []
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            for typ in ("keyDown", "keyUp"):
                events.append({"type": typ, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "modifiers": 0})
            continue
        # One insertion per char — do NOT also send type=char (that doubles letters)
        events.append({"type": "keyDown", "key": ch, "code": ch, "windowsVirtualKeyCode": 0,
                       "modifiers": 0, "text": ch, "unmodifiedText": ch})
        events.append({"type": "keyUp", "key": ch, "code": ch, "windowsVirtualKeyCode": 0, "modifiers": 0})
    return events


def _type_fast(ws: str, text: str) -> int:
    """Same key events as _type_chars_into_docs over ONE CDP connection (~20x faster)."""
    from websockets.sync.client import connect

    events = _key_events_for(text)
    if not events:
        return 0
    base_id = int(time.time() * 1000) % 1_000_000_000
    with connect(ws, open_timeout=10, close_timeout=3, max_size=None) as conn:
        pending = 0
        for i, params in enumerate(events):
            conn.send(json.dumps({"id": base_id + i, "method": "Input.dispatchKeyEvent", "params": params}))
            pending += 1
            if pending >= 40:  # keep Chrome's input queue bounded
                while pending:
                    conn.recv(timeout=10)
                    pending -= 1
        while pending:
            conn.recv(timeout=10)
            pending -= 1
    return sum(1 for e in events if e["type"] == "keyDown")


def _type_chars_into_docs(ws: str, text: str) -> int:
    """Type into Docs using keyDown+text (canvas accepts this; insertText/paste often do not)."""
    try:
        return _type_fast(ws, text)
    except Exception:
        pass
    typed = 0
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            _cdp_key(ws, "Enter", code="Enter", vk=13, typ="keyDown")
            _cdp_key(ws, "Enter", code="Enter", vk=13, typ="keyUp")
            typed += 1
            continue
        # One insertion per char — do NOT also send type=char (that doubles letters)
        _cdp_key(ws, ch, text=ch, typ="keyDown")
        _cdp_key(ws, ch, typ="keyUp")
        typed += 1
        if typed % 80 == 0:
            time.sleep(0.02)
    return typed


def _read_docs_via_clipboard(ws: str) -> str:
    """Select-all + copy, then read Windows clipboard (Docs canvas has no reliable DOM text)."""
    _mouse_click_docs_editor(ws)
    _cdp_key(ws, "a", code="KeyA", modifiers=2, vk=65, typ="keyDown")
    _cdp_key(ws, "a", code="KeyA", modifiers=2, vk=65, typ="keyUp")
    time.sleep(0.12)
    _cdp_key(ws, "c", code="KeyC", modifiers=2, vk=67, typ="keyDown")
    _cdp_key(ws, "c", code="KeyC", modifiers=2, vk=67, typ="keyUp")
    time.sleep(0.25)
    return _clipboard_get_text()


def _text_landed(visible: str, expected: str) -> bool:
    if not expected:
        return False
    v = " ".join((visible or "").lower().split())
    e = " ".join((expected or "").lower().split())
    if not e:
        return False
    if e in v:
        return True
    head = e[: min(48, len(e))]
    return bool(head) and head in v


def _type_into_docs(ws: str, text: str) -> dict:
    """Type into Google Docs and VERIFY via Ctrl+A/Ctrl+C clipboard readback."""
    click = _mouse_click_docs_editor(ws)
    if not click.get("ok"):
        return {"ok": False, "error": "Could not click Docs editor", "click": click}

    typed_n = _type_chars_into_docs(ws, text)
    time.sleep(0.45)
    visible = _read_docs_via_clipboard(ws)
    if _text_landed(visible, text):
        return {
            "ok": True,
            "via": "cdp_keydown_text",
            "chars": typed_n,
            "visible": visible[:240],
            "expected_len": len(text),
        }

    # One retry: click again and retype
    _mouse_click_docs_editor(ws)
    # Clear existing
    _cdp_key(ws, "a", code="KeyA", modifiers=2, vk=65, typ="keyDown")
    _cdp_key(ws, "a", code="KeyA", modifiers=2, vk=65, typ="keyUp")
    _cdp_key(ws, "Backspace", code="Backspace", vk=8, typ="keyDown")
    _cdp_key(ws, "Backspace", code="Backspace", vk=8, typ="keyUp")
    time.sleep(0.2)
    _mouse_click_docs_editor(ws)
    typed_n = _type_chars_into_docs(ws, text)
    time.sleep(0.5)
    visible = _read_docs_via_clipboard(ws)
    if _text_landed(visible, text):
        return {
            "ok": True,
            "via": "cdp_keydown_text_retry",
            "chars": typed_n,
            "visible": visible[:240],
            "expected_len": len(text),
        }

    return {
        "ok": False,
        "via": "failed",
        "chars": typed_n,
        "visible": (visible or "")[:240],
        "expected_len": len(text),
        "error": "Typed into Docs but clipboard readback did not contain the text.",
    }


def google_docs_open_and_type(args: dict, **kwargs) -> str:
    """Open a blank Google Doc in Chrome and type the given text (verified)."""
    text = (args.get("text") or args.get("body") or args.get("content") or "").strip()
    title = (args.get("title") or "").strip()
    open_only = bool(args.get("open_only")) or (not text and bool(args.get("blank")))
    if not text and not open_only:
        return json.dumps({"ok": False, "error": "text is required"})

    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})

    opened, ws, url = _open_new_editor(DOCS_CREATE, "/document/d/", "google_docs_type")
    if not opened.get("ok"):
        return json.dumps({"ok": False, "error": opened.get("error") or "Failed to open Docs", "opened": opened})
    if not ws:
        return json.dumps({
            "ok": False,
            "error": "Opened a new Google Doc tab but it never loaded.",
            "hint": "Sign into Google in the Jarvis Chrome window (debug profile), then try again.",
        })

    try:
        ba._cdp_call(ws, "Page.bringToFront", {}, timeout=5.0)
        base._focus_chrome_window()
    except Exception:
        pass

    ready = None
    for _attempt in range(5):
        try:
            ready = ba._eval(ws, _WAIT_DOCS_JS)
            if isinstance(ready, dict) and ready.get("ok"):
                break
        except Exception as exc:
            ready = {"ok": False, "error": str(exc)}
        time.sleep(1.0)
    if not (isinstance(ready, dict) and ready.get("ok")):
        return json.dumps({
            "ok": False,
            "error": (ready or {}).get("error") if isinstance(ready, dict) else "Docs editor not ready",
            "ready": ready,
            "hint": "Sign into Google in the Jarvis Chrome window (debug profile), then try again.",
        })
    url = (ready or {}).get("url") or url
    _remember_created("docs", opened.get("jarvis_target_id"), url, title)

    if open_only:
        return json.dumps({
            "ok": True,
            "action": "google_docs_open_blank",
            "url": url,
            "ready": ready,
            "message": "Opened a blank Google Doc in Chrome.",
            "note": "No Google API / CONNECT required — uses your signed-in Chrome.",
        })

    typed = _type_into_docs(ws, text)
    typed_ok = bool(isinstance(typed, dict) and typed.get("ok"))
    if title:
        _set_doc_title(ws, title)

    return json.dumps({
        "ok": typed_ok,
        "action": "google_docs_open_and_type",
        "url": url,
        "typed": typed,
        "ready": ready,
        "message": (
            f"Opened a new Google Doc in Chrome and typed your text ({len(text)} chars)."
            if typed_ok else
            "Opened Docs but the text did not appear in the page — try again."
        ),
        "note": "No Google API / CONNECT required — uses your signed-in Chrome.",
    })


def _key(ws: str, key: str, *, code: str = "", modifiers: int = 0) -> None:
    """Dispatch a key press (modifiers: 1=Alt, 2=Ctrl, 4=Meta, 8=Shift)."""
    try:
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key, "code": code or key, "windowsVirtualKeyCode": 0,
            "modifiers": modifiers,
        }, timeout=5.0)
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key, "code": code or key, "windowsVirtualKeyCode": 0,
            "modifiers": modifiers,
        }, timeout=5.0)
    except Exception:
        pass


def _ctrl_m_new_slide(ws: str) -> None:
    # Ctrl+M = new slide in Google Slides
    try:
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyDown", "key": "m", "code": "KeyM", "modifiers": 2,
            "windowsVirtualKeyCode": 77,
        }, timeout=5.0)
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyUp", "key": "m", "code": "KeyM", "modifiers": 2,
            "windowsVirtualKeyCode": 77,
        }, timeout=5.0)
    except Exception:
        # JS fallback click "New slide" button if present
        try:
            ba._eval(ws, r"""
            (() => {
              const b = Array.from(document.querySelectorAll('button,[role="button"],div[aria-label]'))
                .find(el => /new slide/i.test((el.getAttribute('aria-label')||'') + (el.textContent||'')));
              if (b) { b.click(); return true; }
              return false;
            })()
            """)
        except Exception:
            pass


_FILL_SLIDE_JS = r"""
(async (title, body) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const t = String(title || '');
  const b = String(body || '');

  const findEditable = () => document.querySelector('.sketchy-text-contenteditable[contenteditable="true"]')
    || document.querySelector('[contenteditable="true"]');

  // Click near top for title
  const canvas = document.querySelector('.punch-viewer-content') || document.body;
  const r = canvas.getBoundingClientRect();
  const clickAt = (x, y) => {
    const el = document.elementFromPoint(x, y) || canvas;
    el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
    el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
    el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
    el.dispatchEvent(new MouseEvent('dblclick', {bubbles:true, clientX:x, clientY:y}));
  };

  clickAt(r.left + r.width*0.5, r.top + r.height*0.28);
  await sleep(220);
  let box = findEditable();
  if (box) {
    box.focus();
    try { document.execCommand('selectAll'); } catch (e) {}
    try { document.execCommand('insertText', false, t); } catch (e) { box.innerText = t; }
  }

  // Body area
  clickAt(r.left + r.width*0.5, r.top + r.height*0.55);
  await sleep(220);
  box = findEditable();
  if (box && b) {
    box.focus();
    try { document.execCommand('selectAll'); } catch (e) {}
    try { document.execCommand('insertText', false, b); } catch (e) { box.innerText = b; }
  }
  return {ok:true, url: location.href};
})(%s, %s)
"""


_PLACEHOLDERS_JS = r"""
(() => {
  // Slides draws each prompt word as its own SVG <text>; classify by the parent group's text
  const kinds = {clicktoaddtitle: 'title', clicktoaddsubtitle: 'subtitle', clicktoaddtext: 'body'};
  const out = {};
  const seen = new Set();
  for (const t of document.querySelectorAll('svg text')) {
    if ((t.textContent || '').trim().toLowerCase() !== 'click') continue;
    let g = t.parentElement;
    for (let i = 0; i < 3 && g && !kinds[(g.textContent || '').replace(/\s+/g, '').toLowerCase()]; i++) g = g.parentElement;
    if (!g || seen.has(g)) continue;
    seen.add(g);
    const k = kinds[(g.textContent || '').replace(/\s+/g, '').toLowerCase()];
    if (!k) continue;
    const r = g.getBoundingClientRect();
    if (r.width < 20 || r.height < 4 || r.bottom < 0 || r.top > innerHeight) continue;
    // The editor canvas copy is the largest; filmstrip thumbnails are tiny
    if (!out[k] || r.width > out[k].w) out[k] = {x: Math.floor(r.left + Math.min(r.width / 2, 60)), y: Math.floor(r.top + r.height / 2), w: r.width};
  }
  return out;
})()
"""


def _slide_placeholders(ws: str) -> dict:
    try:
        res = ba._eval(ws, _PLACEHOLDERS_JS)
        return res if isinstance(res, dict) else {}
    except Exception:
        return {}


def _mouse_dblclick(ws: str, x: int, y: int) -> None:
    for count in (1, 2):
        for typ in ("mousePressed", "mouseReleased"):
            ba._cdp_call(ws, "Input.dispatchMouseEvent", {
                "type": typ, "x": x, "y": y, "button": "left", "clickCount": count,
            }, timeout=5.0)


def _fill_placeholder(ws: str, pt: dict, text: str) -> bool:
    if not text or not pt:
        return False
    try:
        _mouse_dblclick(ws, int(pt["x"]), int(pt["y"]))
    except Exception:
        return False
    time.sleep(0.35)
    n = _type_chars_into_docs(ws, text)
    time.sleep(0.15)
    _press_escape(ws)
    _press_escape(ws)
    time.sleep(0.15)
    return n > 0


def _fill_slide_real(ws: str, title: str, body: str, *, first: bool) -> dict:
    """Type title/body into the current slide's placeholders with real mouse+key input."""
    ph = {}
    for _ in range(6):
        ph = _slide_placeholders(ws)
        if ph.get("title") or ph.get("body") or ph.get("subtitle"):
            break
        time.sleep(0.3)
    body_key = "subtitle" if first and ph.get("subtitle") else "body"
    t_ok = _fill_placeholder(ws, ph.get("title"), title) if title else False
    b_ok = False
    if body:
        # Re-query: typing the title can shift layout
        ph2 = _slide_placeholders(ws) or ph
        b_ok = _fill_placeholder(ws, ph2.get(body_key) or ph2.get("body") or ph2.get("subtitle"), body)
    left = _slide_placeholders(ws)
    return {
        "title": t_ok and "title" not in left,
        "body": (not body) or (b_ok and body_key not in left),
        "found": sorted(ph.keys()),
    }


def _wiki_image_url(topic: str) -> str | None:
    """Lead image of the topic's Wikipedia article (relevant, unlike random stock)."""
    import urllib.parse
    import urllib.request
    q = (topic or "").strip()
    if not q:
        return None
    try:
        search = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": q, "srlimit": 1, "format": "json",
        })
        req = urllib.request.Request(search, headers={"User-Agent": "JarvisSlides/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            hits = json.loads(resp.read().decode("utf-8")).get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"].replace(" ", "_")
        req = urllib.request.Request(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title),
            headers={"User-Agent": "JarvisSlides/1.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        src = (data.get("thumbnail") or {}).get("source") or (data.get("originalimage") or {}).get("source")
        return src or None
    except Exception:
        return None


def _download_url(url: str) -> str | None:
    import os
    import urllib.request
    from pathlib import Path
    out_dir = Path(r"D:\jarvis_kokoro\cache\slides_img")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = ".png" if url.lower().split("?")[0].endswith(".png") else ".jpg"
        path = out_dir / f"wiki-{int(time.time() * 1000) % 1000000}{ext}"
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisSlides/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        if len(data) < 800:
            return None
        path.write_bytes(data)
        return str(path)
    except Exception:
        return None


def _download_image(query: str, dest_dir: str) -> str | None:
    """Download a small royalty-free image to D: cache (not C:). Returns path or None."""
    import os
    import re
    import urllib.request
    from pathlib import Path

    root = Path(os.environ.get("JARVIS_DATA_DIR") or r"D:\jarvis_kokoro\server-data")
    out_dir = Path(dest_dir) if dest_dir else (root.parent / "cache" / "slides_img")
    # Prefer D: jarvis cache
    if str(out_dir).upper().startswith("C:"):
        out_dir = Path(r"D:\jarvis_kokoro\cache\slides_img")
    out_dir.mkdir(parents=True, exist_ok=True)
    q = re.sub(r"[^a-zA-Z0-9]+", "-", (query or "presentation").strip())[:40] or "presentation"
    path = out_dir / f"{q}-{int(time.time()*1000)%100000}.jpg"
    # picsum is tiny/fast; seed by query hash for variety without API keys
    seed = abs(hash(q)) % 10000
    url = f"https://picsum.photos/seed/{seed}/960/540"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisSlides/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        if len(data) < 800:
            return None
        path.write_bytes(data)
        return str(path)
    except Exception:
        return None


def _clipboard_set_image(file_path: str) -> bool:
    """Put an image file on the Windows clipboard for Ctrl+V paste."""
    import subprocess
    from pathlib import Path
    p = Path(file_path)
    if not p.is_file():
        return False
    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Set-Clipboard -Path {json.dumps(str(p.resolve()))}",
            ],
            capture_output=True,
            timeout=6,
            text=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def _ctrl_v(ws: str) -> None:
    try:
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyDown", "key": "v", "code": "KeyV", "modifiers": 2,
            "windowsVirtualKeyCode": 86,
        }, timeout=3.0)
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyUp", "key": "v", "code": "KeyV", "modifiers": 2,
            "windowsVirtualKeyCode": 86,
        }, timeout=3.0)
    except Exception:
        pass


def _press_escape(ws: str) -> None:
    try:
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27,
        }, timeout=2.0)
        ba._cdp_call(ws, "Input.dispatchKeyEvent", {
            "type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27,
        }, timeout=2.0)
    except Exception:
        pass


def _insert_image_file(ws: str, file_path: str) -> dict:
    """Insert image via clipboard paste (avoids native file-chooser hangs)."""
    from pathlib import Path
    p = Path(file_path)
    if not p.is_file():
        return {"ok": False, "error": "image missing"}
    _press_escape(ws)
    time.sleep(0.15)
    try:
        ba._eval(ws, r"""
        (() => {
          const canvas = document.querySelector('.punch-viewer-content') || document.body;
          const r = canvas.getBoundingClientRect();
          const x = r.left + r.width * 0.72, y = r.top + r.height * 0.62;
          const el = document.elementFromPoint(x, y) || canvas;
          el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
          el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
          el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
          return true;
        })()
        """)
    except Exception as exc:
        return {"ok": False, "error": f"click failed: {exc}"}
    if not _clipboard_set_image(str(p)):
        return {"ok": False, "error": "clipboard image failed"}
    time.sleep(0.2)
    _ctrl_v(ws)
    time.sleep(0.55)
    return {"ok": True, "path": str(p), "via": "clipboard_paste"}


def _open_new_slides(source: str) -> tuple[str | None, str | None, dict]:
    """Create a new deck; returns (ws, url, info) for that new tab only."""
    err = base._ensure_cdp()
    if err:
        return None, None, {"ok": False, "error": err}
    opened, ws, url = _open_new_editor(SLIDES_CREATE, "/presentation/d/", source)
    if not opened.get("ok"):
        return None, None, {"ok": False, "error": opened.get("error") or "Failed to open Slides"}
    if not ws:
        return None, None, {"ok": False, "error": "Opened a new Google Slides tab but it never loaded.",
                            "hint": "Sign into Google in the Jarvis Chrome window, then try again."}
    try:
        ba._cdp_call(ws, "Page.bringToFront", {}, timeout=5.0)
        base._focus_chrome_window()
    except Exception:
        pass
    ready = None
    for _ in range(4):
        try:
            ready = ba._eval(ws, _WAIT_SLIDES_JS)
        except Exception as exc:
            ready = {"ok": False, "error": str(exc)}
        if isinstance(ready, dict) and ready.get("ok"):
            break
        time.sleep(1.0)
    if not (isinstance(ready, dict) and ready.get("ok")):
        return None, None, {"ok": False, "error": "Slides editor not ready", "ready": ready}
    # Wait for the first slide's placeholders to render
    for _ in range(20):
        if _slide_placeholders(ws):
            break
        time.sleep(0.4)
    url = (ready or {}).get("url") or url
    _remember_created("slides", opened.get("jarvis_target_id"), url)
    return ws, url, {"ok": True, "target_id": opened.get("jarvis_target_id")}


def google_slides_open_and_type(args: dict, **kwargs) -> str:
    """Open a NEW blank Google Slides deck and type title/text into its first slide."""
    text = (args.get("text") or args.get("body") or args.get("content") or "").strip()
    title = (args.get("title") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "text is required"})
    ws, url, info = _open_new_slides("google_slides_type")
    if not ws:
        return json.dumps(info)
    if title:
        head, rest = title, text
    else:
        parts = text.split("\n", 1)
        head, rest = (parts[0], parts[1].strip()) if len(parts) > 1 else (text, "")
    filled = _fill_slide_real(ws, head, rest, first=True)
    ok = bool(filled.get("title")) and bool(filled.get("body"))
    if not ok:
        # Last resort: whatever box has focus
        _mouse_click_slides_canvas(ws)
        ok = _type_chars_into_docs(ws, text) > 0
    if title:
        _set_doc_title(ws, title)
    return json.dumps({
        "ok": ok,
        "action": "google_slides_open_and_type",
        "url": url,
        "filled": filled,
        "message": (
            f"Opened a new Google Slides deck and typed your text ({len(text)} chars)."
            if ok else "Opened a new Slides deck but typing failed."
        ),
        "note": "No Google API / CONNECT required — uses your signed-in Chrome.",
    })


def _add_slide_to(ws: str, title: str, body: str) -> dict:
    _press_escape(ws)
    _press_escape(ws)
    _ctrl_m_new_slide(ws)
    time.sleep(0.6)
    return _fill_slide_real(ws, title, body, first=False)


def _insert_image_slide(ws: str, img_path: str) -> dict:
    """New slide holding just the topic picture (paste lands centered on an empty slide)."""
    _press_escape(ws)
    _press_escape(ws)
    _ctrl_m_new_slide(ws)
    time.sleep(0.6)
    if not _clipboard_set_image(img_path):
        return {"ok": False, "error": "clipboard image failed"}
    time.sleep(0.2)
    _ctrl_v(ws)
    time.sleep(1.2)
    _press_escape(ws)
    return {"ok": True}


def _close_side_panels(ws: str) -> None:
    """Google pops a Gemini 'Help me visualize' panel over the canvas; close it."""
    try:
        ba._eval(ws, r"""
        (() => {
          let n = 0;
          for (const el of document.querySelectorAll('[role="button"],button')) {
            const label = (el.getAttribute('aria-label') || el.getAttribute('data-tooltip') || '').toLowerCase();
            if (!/^close/.test(label)) continue;
            const panel = el.closest('[role="complementary"],[role="region"],[role="dialog"],.docs-companion-app-container') || el.parentElement;
            if (panel && /help me visualize|gemini/i.test(panel.textContent || '') && el.getBoundingClientRect().width > 0) {
              el.click(); n++;
            }
          }
          return n;
        })()
        """)
    except Exception:
        pass


def google_slides_build_deck(args: dict, **kwargs) -> str:
    """Build a full deck in a NEW presentation: title slide + one slide per spec."""
    slides = args.get("slides")
    if not isinstance(slides, list) or not slides:
        return json.dumps({"ok": False, "error": "slides array required"})
    design = args.get("design") if isinstance(args.get("design"), dict) else {}
    add_images = bool(args.get("images", True))
    deck_title = str(args.get("title") or (slides[0] or {}).get("title") or "").strip()
    image_topic = str(args.get("image_topic") or deck_title or "").strip()

    t0 = time.time()
    ws, url, info = _open_new_slides("google_slides_deck")
    if not ws:
        return json.dumps(info)

    filled = 0
    report = []
    images_ok = 0
    for i, spec in enumerate(slides):
        if not isinstance(spec, dict):
            continue
        title = str(spec.get("title") or f"Slide {i + 1}")
        body = str(spec.get("body") or "")
        if i == 0:
            res = _fill_slide_real(ws, title, body, first=True)
            if add_images and image_topic:
                src = _wiki_image_url(image_topic)
                img = _download_url(src) if src else None
                if img:
                    try:
                        if _insert_image_slide(ws, img).get("ok"):
                            images_ok += 1
                    except Exception:
                        _press_escape(ws)
        else:
            res = _add_slide_to(ws, title, body)
        report.append(res)
        if res.get("title") or res.get("body"):
            filled += 1
    _press_escape(ws)
    _close_side_panels(ws)
    if deck_title:
        _set_doc_title(ws, deck_title)

    try:
        for pg in ba._pages():
            if pg.get("webSocketDebuggerUrl") == ws and "/presentation/d/" in (pg.get("url") or ""):
                url = pg["url"]
                break
    except Exception:
        pass
    _remember_created("slides", info.get("target_id"), url, deck_title)

    elapsed = round(time.time() - t0, 1)
    return json.dumps({
        "ok": filled > 0,
        "action": "google_slides_build_deck",
        "url": url,
        "slides_requested": len(slides),
        "slides_filled": filled,
        "images_inserted": images_ok,
        "fill_report": report,
        "design": design,
        "elapsed_sec": elapsed,
        "message": f"Built a {filled}-slide Google Slides deck in Chrome in {elapsed}s ({images_ok} images).",
        "note": "No Google API — Chrome only.",
    })


def google_slides_add_slides(args: dict, **kwargs) -> str:
    """Append slides to the deck Jarvis created most recently."""
    slides = args.get("slides")
    if not isinstance(slides, list) or not slides:
        return json.dumps({"ok": False, "error": "slides array required"})
    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})
    rec = last_created("slides")
    if not rec:
        return json.dumps({"ok": False, "error": "no recent Jarvis deck open"})
    ws = rec["ws"]
    try:
        ba._cdp_call(ws, "Page.bringToFront", {}, timeout=5.0)
        base._focus_chrome_window()
    except Exception:
        pass
    # Go to the last slide so new ones land at the end
    _press_escape(ws)
    _press_escape(ws)
    _cdp_key(ws, "End", code="End", vk=35, typ="keyDown")
    _cdp_key(ws, "End", code="End", vk=35, typ="keyUp")
    time.sleep(0.3)
    added = 0
    for spec in slides:
        if isinstance(spec, dict):
            res = _add_slide_to(ws, str(spec.get("title") or ""), str(spec.get("body") or ""))
            if res.get("title") or res.get("body"):
                added += 1
    return json.dumps({"ok": added > 0, "action": "google_slides_add_slides", "added": added, "url": rec.get("url")})


def _find_ws_for_url_bits(*bits: str) -> str | None:
    for p in ba._pages():
        u = (p.get("url") or "")
        if any(b in u for b in bits) and p.get("webSocketDebuggerUrl"):
            return p["webSocketDebuggerUrl"]
    return None


def _type_append(ws: str, text: str, *, click_fn) -> dict:
    """Click editor and type without wiping existing content."""
    click_fn(ws)
    time.sleep(0.15)
    # Move to end of doc (Ctrl+End) then type
    _cdp_key(ws, "End", code="End", modifiers=2, vk=35, typ="keyDown")
    _cdp_key(ws, "End", code="End", modifiers=2, vk=35, typ="keyUp")
    time.sleep(0.05)
    n = _type_chars_into_docs(ws, text)
    # Also try insertText as supplement for Gmail-like fields
    if n < max(1, len(text) // 2):
        _cdp_insert_text(ws, text)
    return {"ok": n > 0 or bool(text), "chars": n, "via": "append_keydown"}


def google_docs_type_active(args: dict, **kwargs) -> str:
    """Type into the already-open Google Doc (append). Opens blank doc if none."""
    text = (args.get("text") or args.get("body") or "").strip()
    append = args.get("append", True)
    if not text:
        return json.dumps({"ok": False, "error": "text is required"})
    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})
    rec = last_created("docs")
    ws = rec["ws"] if rec else _find_ws_for_url_bits("/document/d/", "docs.google.com/document")
    if not ws:
        # Open blank then type
        return google_docs_open_and_type({"text": text})
    try:
        ba._cdp_call(ws, "Page.bringToFront", {}, timeout=5.0)
        base._focus_chrome_window()
    except Exception:
        pass
    if append:
        typed = _type_append(ws, text, click_fn=_mouse_click_docs_editor)
    else:
        typed = _type_into_docs(ws, text)
    return json.dumps({
        "ok": bool(typed.get("ok")),
        "action": "google_docs_type_active",
        "typed": typed,
        "message": f"Typed {len(text)} chars into Google Docs." if typed.get("ok") else (typed.get("error") or "Type failed"),
    })


def _mouse_click_slides_canvas(ws: str) -> dict:
    try:
        box = ba._eval(ws, r"""
        (() => {
          const c = document.querySelector('.punch-viewer-content')
            || document.querySelector('.sketchy-text-contenteditable')
            || document.querySelector('[role="textbox"]')
            || document.body;
          const r = c.getBoundingClientRect();
          return {
            x: Math.floor(r.left + Math.min(220, Math.max(80, r.width * 0.35))),
            y: Math.floor(r.top + Math.min(220, Math.max(80, r.height * 0.35))),
          };
        })()
        """)
    except Exception:
        box = None
    if not isinstance(box, dict) or "x" not in box:
        return {"ok": False}
    x, y = int(box["x"]), int(box["y"])
    try:
        ba._cdp_call(ws, "Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1,
        }, timeout=5.0)
        ba._cdp_call(ws, "Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1,
        }, timeout=5.0)
        # Double-click to enter text edit
        ba._cdp_call(ws, "Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 2,
        }, timeout=5.0)
        ba._cdp_call(ws, "Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 2,
        }, timeout=5.0)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    time.sleep(0.25)
    return {"ok": True, "x": x, "y": y}


def google_slides_type_active(args: dict, **kwargs) -> str:
    """Type into the open Google Slides deck (append into focused text box)."""
    text = (args.get("text") or args.get("body") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "text is required"})
    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})
    rec = last_created("slides")
    ws = rec["ws"] if rec else _find_ws_for_url_bits("/presentation/d/", "slides.google.com")
    if not ws:
        return google_slides_open_and_type({"text": text})
    try:
        ba._cdp_call(ws, "Page.bringToFront", {}, timeout=5.0)
        base._focus_chrome_window()
    except Exception:
        pass
    click = _mouse_click_slides_canvas(ws)
    if not click.get("ok"):
        return json.dumps({"ok": False, "error": "Could not focus Slides canvas", "click": click})
    n = _type_chars_into_docs(ws, text)
    if n < 1:
        _cdp_insert_text(ws, text)
        n = len(text)
    return json.dumps({
        "ok": n > 0,
        "action": "google_slides_type_active",
        "chars": n,
        "message": f"Typed {n} chars into Google Slides." if n else "Type into Slides failed",
    })


def gmail_type_active(args: dict, **kwargs) -> str:
    """Type into Gmail compose (open compose if needed)."""
    text = (args.get("text") or args.get("body") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "text is required"})
    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})
    ws = _find_ws_for_url_bits("mail.google.com")
    if not ws:
        opened = base._open_url_in_chrome("https://mail.google.com/", source="gmail_type")
        if not opened.get("ok"):
            return json.dumps({"ok": False, "error": "Could not open Gmail"})
        time.sleep(1.5)
        ws = _find_ws_for_url_bits("mail.google.com")
        if not ws:
            return json.dumps({"ok": False, "error": "Gmail tab not found"})
    try:
        ba._cdp_call(ws, "Page.bringToFront", {}, timeout=5.0)
        base._focus_chrome_window()
    except Exception:
        pass
    # Ensure compose is open
    try:
        ba._eval(ws, r"""
        (() => {
          const body = document.querySelector('div[aria-label="Message Body"]')
            || document.querySelector('div[role="textbox"][aria-label*="Body"]')
            || document.querySelector('div[contenteditable="true"][aria-label*="Message"]')
            || document.querySelector('div.Am.Al.editable');
          if (body) { body.focus(); return {ok:true, compose:true}; }
          const compose = document.querySelector('div[gh="cm"]')
            || document.querySelector('div[role="button"][gh="cm"]')
            || Array.from(document.querySelectorAll('div[role="button"]')).find(el => /compose/i.test(el.innerText||''));
          if (compose) { compose.click(); return {ok:true, clicked:true}; }
          return {ok:false};
        })()
        """)
        time.sleep(0.8)
    except Exception:
        pass
    # Focus body and type
    try:
        ba._eval(ws, r"""
        (() => {
          const body = document.querySelector('div[aria-label="Message Body"]')
            || document.querySelector('div[role="textbox"][aria-label*="Body"]')
            || document.querySelector('div.Am.Al.editable')
            || document.querySelector('div[contenteditable="true"][g_editable="true"]');
          if (body) { body.focus(); return true; }
          return false;
        })()
        """)
    except Exception:
        pass
    time.sleep(0.15)
    ok = _cdp_insert_text(ws, text)
    if not ok:
        n = _type_chars_into_docs(ws, text)
        ok = n > 0
    return json.dumps({
        "ok": bool(ok),
        "action": "gmail_type_active",
        "message": f"Typed into Gmail compose ({len(text)} chars)." if ok else "Could not type into Gmail compose.",
    })
