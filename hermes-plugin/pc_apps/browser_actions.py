"""CDP helpers + YouTube/WhatsApp typing actions for the pc_apps plugin."""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import tools as base


def _fuzzy_norm(s: str) -> str:
    """Normalize labels for fuzzy match: ENGLISH 9S ≈ english 9s."""
    t = (s or "").lower().replace("ـ", "")
    t = re.sub(r"[^\w\s]+", " ", t, flags=re.U)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fuzzy_score(query: str, candidate: str) -> float:
    """0..100 similarity. Exact / containment preferred; else SequenceMatcher."""
    from difflib import SequenceMatcher

    q, c = _fuzzy_norm(query), _fuzzy_norm(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 100.0
    if q in c or c in q:
        return 92.0 - 2.0 * abs(len(q) - len(c)) / max(len(q), len(c), 1)
    qt, ct = set(q.split()), set(c.split())
    if qt and ct and qt <= ct:
        return 88.0
    if qt and ct:
        overlap = len(qt & ct) / len(qt | ct)
        if overlap >= 0.6:
            return 70.0 + 25.0 * overlap
    return 100.0 * SequenceMatcher(None, q, c).ratio()


def _fuzzy_best(query: str, items: list[dict], *, key: str = "name", min_score: float = 55.0) -> dict | None:
    """Pick best matching item; None if nothing is close enough."""
    best, best_s = None, -1.0
    for it in items:
        s = _fuzzy_score(query, str(it.get(key) or ""))
        if s > best_s:
            best, best_s = it, s
    if best is None or best_s < min_score:
        return None
    out = dict(best)
    out["_match_score"] = round(best_s, 1)
    return out


def _pages() -> list[dict]:
    try:
        _, body = base._cdp_get("/json/list")
        data = json.loads(body)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _find_page(*needles: str) -> dict | None:
    pages = _pages()
    # Prefer visible pages matching URL/title
    for p in pages:
        if p.get("type") and p.get("type") != "page":
            continue
        blob = f"{p.get('url','')} {p.get('title','')}".lower()
        if all(n.lower() in blob for n in needles):
            return p
    for p in pages:
        blob = f"{p.get('url','')} {p.get('title','')}".lower()
        if any(n.lower() in blob for n in needles):
            return p
    return None


def _ensure_page(url: str, *needles: str) -> dict | str:
    """Return page dict or error string."""
    err = base._ensure_cdp()
    if err:
        return err
    page = _find_page(*needles)
    if page and page.get("webSocketDebuggerUrl"):
        base._focus_chrome_window()
        return page
    opened = base._open_url_in_chrome(url, source="ensure_page")
    if not opened.get("ok"):
        return opened.get("error") or "Could not open page"
    time.sleep(0.45)
    page = _find_page(*needles)
    if not page or not page.get("webSocketDebuggerUrl"):
        # newly opened target may be in opened['target']
        t = opened.get("target") or {}
        if isinstance(t, dict) and t.get("webSocketDebuggerUrl"):
            return t
        return "Page opened but CDP target not found yet; wait a moment and retry."
    base._focus_chrome_window()
    return page


def _cdp_call(ws_url: str, method: str, params: dict | None = None, timeout: float = 12.0) -> Any:
    from websockets.sync.client import connect

    msg_id = int(time.time() * 1000) % 1_000_000_000
    payload = {"id": msg_id, "method": method, "params": params or {}}
    with connect(ws_url, open_timeout=timeout, close_timeout=3) as ws:
        ws.send(json.dumps(payload))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(str(data["error"]))
                return data.get("result")
    raise TimeoutError(f"CDP timeout for {method}")


def _eval(ws_url: str, expression: str) -> Any:
    result = _cdp_call(
        ws_url,
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            "userGesture": True,
        },
    )
    if not result:
        return None
    if result.get("exceptionDetails"):
        details = result["exceptionDetails"]
        text = details.get("text") or details.get("exception", {}).get("description") or str(details)
        raise RuntimeError(text)
    return (result.get("result") or {}).get("value")


def _activate_page(page: dict) -> None:
    ws = page.get("webSocketDebuggerUrl")
    if not ws:
        return
    try:
        _cdp_call(ws, "Page.bringToFront", {})
    except Exception:
        pass
    base._focus_chrome_window()


# ---- YouTube ----

_YT_SEARCH_JS = r"""
(async (query) => {
  const q = String(query || '');
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  // Focus search
  let input = document.querySelector('input#search') 
    || document.querySelector('input[name="search_query"]')
    || document.querySelector('input[aria-label*="Search" i]');
  if (!input) {
    const btn = document.querySelector('button#search-icon-legacy') 
      || document.querySelector('yt-icon-button#search-button')
      || document.querySelector('[aria-label*="Search" i]');
    if (btn) btn.click();
    await sleep(400);
    input = document.querySelector('input#search') 
      || document.querySelector('input[name="search_query"]');
  }
  if (!input) return {ok:false, error:'YouTube search box not found'};
  input.focus();
  input.value = '';
  input.dispatchEvent(new Event('input', {bubbles:true}));
  // native setter so React/YouTube picks it up
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  if (setter) setter.call(input, q); else input.value = q;
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.dispatchEvent(new Event('change', {bubbles:true}));
  await sleep(200);
  // Submit search (Enter)
  input.form?.requestSubmit?.();
  const kb = new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true});
  input.dispatchEvent(kb);
  const searchBtn = document.querySelector('button#search-icon-legacy') || document.querySelector('button.ytSearchboxComponentSearchButton');
  if (searchBtn) searchBtn.click();
  return {ok:true, typed:q};
})(%s)
"""


def youtube_type_search(args: dict, **kwargs) -> str:
    query = (args.get("query") or args.get("text") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})
    # Explicit pick/play → open a video; otherwise search only
    if args.get("pick") or args.get("play") or args.get("choose"):
        return youtube_pick_video({"query": query})
    page = _ensure_page("https://www.youtube.com/", "youtube.com")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    _activate_page(page)
    time.sleep(0.45)
    try:
        expr = _YT_SEARCH_JS % json.dumps(query)
        result = _eval(page["webSocketDebuggerUrl"], expr)
        return json.dumps({"ok": True, "app": "youtube", "action": "search", "result": result})
    except Exception as e:
        return json.dumps({"ok": False, "error": f"YouTube typing failed: {e}"})


_YT_SCRAPE_RESULTS_JS = r"""
(() => {
  const out = [];
  const seen = new Set();
  const nodes = document.querySelectorAll(
    'ytd-video-renderer a#video-title, ytd-video-renderer a#video-title-link, a#video-title, a.yt-lockup-metadata-view-model__title, ytd-rich-item-renderer a#video-title-link'
  );
  for (const a of nodes) {
    const href = a.href || '';
    if (!/watch\?v=|\/shorts\//i.test(href)) continue;
    const title = (a.getAttribute('title') || a.innerText || '').replace(/\s+/g, ' ').trim();
    if (!title || title.length < 2 || seen.has(href)) continue;
    seen.add(href);
    out.push({ title, href });
    if (out.length >= 12) break;
  }
  const loading = !!(
    document.querySelector('ytd-page-manager[loading], yt-page-navigation-progress:not([hidden])')
    || document.querySelector('tp-yt-paper-spinner, .ytp-spinner')
    || (out.length === 0 && /\/results/.test(location.href))
  );
  return { items: out, loading, href: location.href, ready: out.length > 0 };
})()
"""


def _yt_wait_for_results(ws: str, *, timeout: float = 18.0) -> list[dict]:
    """Poll until video result links appear (YouTube first load can be slow)."""
    deadline = time.time() + max(4.0, timeout)
    last: list[dict] = []
    while time.time() < deadline:
        try:
            got = _eval(ws, _YT_SCRAPE_RESULTS_JS) or {}
        except Exception:
            got = {}
        if isinstance(got, list):
            items = got
            ready = bool(items)
        else:
            items = got.get("items") if isinstance(got, dict) else []
            items = items if isinstance(items, list) else []
            ready = bool(got.get("ready")) if isinstance(got, dict) else bool(items)
        last = [x for x in items if isinstance(x, dict)]
        if ready and last:
            # Extra beat so thumbnails/titles finish hydrating
            time.sleep(0.45)
            try:
                got2 = _eval(ws, _YT_SCRAPE_RESULTS_JS) or {}
                items2 = got2.get("items") if isinstance(got2, dict) else got2
                if isinstance(items2, list) and len(items2) >= len(last):
                    last = [x for x in items2 if isinstance(x, dict)]
            except Exception:
                pass
            return last
        time.sleep(0.55)
    return last


def youtube_pick_video(args: dict, **kwargs) -> str:
    """Search YouTube, wait for results to load, then open the best-fitting video."""
    query = (args.get("query") or args.get("text") or args.get("topic") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    page = _ensure_page(url, "youtube.com")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    _activate_page(page)
    ws = page["webSocketDebuggerUrl"]
    try:
        _cdp_call(ws, "Page.navigate", {"url": url})
    except Exception:
        pass
    # First YouTube open is often cold — wait for result tiles, not a fixed short sleep
    time.sleep(0.8)
    results = _yt_wait_for_results(ws, timeout=20.0)
    if not results:
        # One retry navigate (cold start / consent interstitial)
        try:
            _cdp_call(ws, "Page.navigate", {"url": url})
        except Exception:
            pass
        time.sleep(1.0)
        results = _yt_wait_for_results(ws, timeout=16.0)
    if not results:
        return json.dumps({
            "ok": False,
            "error": f"YouTube results did not finish loading for '{query}'. Try again in a moment.",
            "query": query,
        })
    scored = []
    for it in results:
        title = str(it.get("title") or "")
        href = it.get("href")
        if not href:
            continue
        # Prefer normal watch videos over Shorts for "explaining / explanation"
        bonus = 0.0
        if re.search(r"(?i)\b(explain|explanation|breakdown|summary|recap|guide)\b", query):
            if "/shorts/" in str(href):
                bonus -= 15.0
            if re.search(r"(?i)\b(explain|explained|explanation|breakdown|summary|recap)\b", title):
                bonus += 18.0
        scored.append({
            "title": title,
            "href": href,
            "score": _fuzzy_score(query, title) + bonus,
        })
    if not scored:
        return json.dumps({
            "ok": False,
            "error": f"No playable YouTube videos for '{query}'.",
            "query": query,
        })
    scored.sort(key=lambda x: -float(x["score"]))
    pick = scored[0]
    href = pick.get("href")
    try:
        _cdp_call(ws, "Page.navigate", {"url": href})
        time.sleep(0.8)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Could not open video: {e}", "picked": pick})
    # Confirm we landed on a watch page
    try:
        cur = str(_eval(ws, "location.href") or "")
    except Exception:
        cur = str(href)
    if "watch" not in cur and "/shorts/" not in cur:
        return json.dumps({
            "ok": False,
            "error": "Opened search but could not open a video. Try again.",
            "query": query,
            "picked": pick,
        })
    return json.dumps({
        "ok": True,
        "app": "youtube",
        "action": "pick_and_play",
        "query": query,
        "title": pick.get("title"),
        "url": cur or href,
        "score": pick.get("score"),
        "message": f"Opened: {pick.get('title')}",
    })


# ---- Vidbox (movies) ----

_VIDBOX_HOME = "https://vidbox.cc/"
_VIDBOX_NEEDLES = ("vidbox.cc", "vidbox.vc", "vidbox.to", "vidbox")

_VIDBOX_SEARCH_JS = r"""
(async (query) => {
  const q = String(query || '');
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  let input = document.querySelector('input[type="search"]')
    || document.querySelector('input[placeholder*="Search" i]')
    || document.querySelector('[role="searchbox"]')
    || document.querySelector('input[aria-label*="Search" i]');
  if (!input) return {ok:false, error:'Vidbox search box not found'};
  input.focus();
  input.click();
  await sleep(80);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  if (setter) setter.call(input, ''); else input.value = '';
  input.dispatchEvent(new Event('input', {bubbles:true}));
  if (setter) setter.call(input, q); else input.value = q;
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.dispatchEvent(new Event('change', {bubbles:true}));
  await sleep(120);
  // Prefer Enter (site routes to /search?q=...)
  input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
  input.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
  const form = input.closest('form');
  if (form?.requestSubmit) form.requestSubmit();
  // Magnifying-glass search button near the input
  const wrap = input.parentElement;
  const btn = wrap?.querySelector('button')
    || [...document.querySelectorAll('button')].find(b => /search/i.test(b.getAttribute('aria-label')||b.textContent||''));
  if (btn) btn.click();
  await sleep(250);
  return {ok:true, typed:q, href: location.href};
})(%s)
"""


def vidbox_type_search(args: dict, **kwargs) -> str:
    """Open Vidbox and search movies (types the site search bar, URL fallback)."""
    query = (args.get("query") or args.get("text") or args.get("movie") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    page = _ensure_page(_VIDBOX_HOME, *_VIDBOX_NEEDLES)
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    _activate_page(page)
    time.sleep(0.55)

    typed_ok = False
    typed_result = None
    try:
        expr = _VIDBOX_SEARCH_JS % json.dumps(query)
        typed_result = _eval(page["webSocketDebuggerUrl"], expr)
        typed_ok = bool(isinstance(typed_result, dict) and typed_result.get("ok"))
    except Exception as e:
        typed_result = {"ok": False, "error": str(e)}

    # Reliable fallback: navigate to search results URL
    if not typed_ok or "search?q=" not in str((typed_result or {}).get("href") or ""):
        search_url = f"{_VIDBOX_HOME.rstrip('/')}/search?q={urllib.parse.quote(query)}"
        try:
            _cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": search_url}, timeout=15.0)
            time.sleep(0.8)
            return json.dumps({
                "ok": True,
                "app": "vidbox",
                "action": "search",
                "query": query,
                "url": search_url,
                "via": "navigate",
                "typed": typed_result,
                "note": f"Opened Vidbox search for {query}.",
            })
        except Exception as e:
            if typed_ok:
                return json.dumps({
                    "ok": True,
                    "app": "vidbox",
                    "action": "search",
                    "query": query,
                    "result": typed_result,
                    "nav_error": str(e),
                })
            return json.dumps({"ok": False, "error": f"Vidbox search failed: {e}", "typed": typed_result})

    return json.dumps({
        "ok": True,
        "app": "vidbox",
        "action": "search",
        "query": query,
        "result": typed_result,
        "via": "type",
        "note": f"Searched Vidbox for {query}.",
    })


# ---- WhatsApp ----

_WA_STATUS_JS = r"""
(() => {
  const side = document.querySelector('#pane-side') || document.querySelector('[data-testid="chat-list"]');
  const qr = document.querySelector('[data-testid="qrcode"]') || (
    document.querySelector('canvas') && /scan|qr code/i.test((document.body && document.body.innerText) || '')
  );
  const body = ((document.body && document.body.innerText) || '').slice(0, 800);
  const downloading = /don'?t close this window|messages are downloading|loading your chats|progress/i.test(body)
    && !side;
  const loggedIn = !!(side && !document.querySelector('[data-testid="qrcode"]'));
  return {
    logged_in: loggedIn,
    has_chat_list: !!side,
    looks_like_qr: !!qr && !side,
    downloading: !!downloading,
    href: location.href,
    title: document.title,
    snippet: body.slice(0, 160),
  };
})()
"""

_WA_WAIT_READY_JS = r"""
(() => {
  const side = document.querySelector('#pane-side') || document.querySelector('[data-testid="chat-list"]');
  const main = document.querySelector('#main');
  const box = document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]');
  const qr = document.querySelector('[data-testid="qrcode"]');
  const body = ((document.body && document.body.innerText) || '');
  const downloading = /don'?t close this window|messages are downloading|loading your chats/i.test(body) && !side;
  return {
    ready: !!(side || box) && !qr && !downloading,
    downloading,
    qr: !!qr,
    has_side: !!side,
    has_box: !!box,
    has_main: !!main,
    href: location.href,
  };
})()
"""

_WA_DRAFT_JS = r"""
(async (n, message) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const side = document.querySelector('#pane-side') || document.querySelector('[data-testid="chat-list"]');
  if (!side) return {ok:false, error:'WhatsApp chat list not found — are you logged in?'};
  if (document.querySelector('[data-testid="qrcode"]')) {
    return {ok:false, error:'WhatsApp shows a QR code — log in on the PC first.'};
  }
  // Recent chats: prefer listitems in the left pane
  let items = Array.from(side.querySelectorAll('[data-testid="cell-frame-container"]'));
  if (!items.length) items = Array.from(side.querySelectorAll('div[role="listitem"]'));
  if (!items.length) items = Array.from(side.querySelectorAll('div[tabindex="-1"][aria-selected]'));
  // Fallback: clickable rows with role row
  if (!items.length) items = Array.from(side.querySelectorAll('[role="row"]'));
  const idx = Math.max(1, Number(n) || 1) - 1;
  if (idx < 0 || idx >= items.length) {
    return {ok:false, error:`Only ${items.length} recent chats visible; asked for #${idx+1}` , count: items.length};
  }
  items[idx].click();
  await sleep(700);
  // Message compose box — never press Enter / never click send
  let box = document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('div[contenteditable="true"][data-tab="10"]')
    || document.querySelector('div[contenteditable="true"][data-tab="1"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]')
    || document.querySelector('div[role="textbox"][contenteditable="true"]');
  if (!box) return {ok:false, error:'Message box not found after opening chat'};
  box.focus();
  // Clear existing draft
  box.textContent = '';
  box.innerHTML = '';
  box.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
  await sleep(100);
  const text = String(message || '');
  // Prefer execCommand / insert text without sending
  try {
    document.execCommand('selectAll', false);
    document.execCommand('insertText', false, text);
  } catch (e) {}
  if (!(box.innerText || box.textContent || '').includes(text.slice(0, Math.min(12, text.length)))) {
    box.textContent = text;
    box.dispatchEvent(new InputEvent('input', {bubbles:true, data:text, inputType:'insertText'}));
  }
  await sleep(150);
  const typed = (box.innerText || box.textContent || '').trim();
  return {
    ok: true,
    chat_index: idx + 1,
    chats_visible: items.length,
    typed,
    sent: false,
    note: 'Draft only — message was NOT sent (no Enter / no Send click).'
  };
})(%s, %s)
"""


def whatsapp_status(args: dict, **kwargs) -> str:
    page = _ensure_page("https://web.whatsapp.com/", "web.whatsapp.com", "whatsapp")
    if isinstance(page, str):
        # softer: try whatsapp.com needle only
        page = _ensure_page("https://web.whatsapp.com/", "whatsapp")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    _activate_page(page)
    time.sleep(0.55)
    try:
        status = _eval(page["webSocketDebuggerUrl"], _WA_STATUS_JS)
        return json.dumps({"ok": True, "whatsapp": status})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def whatsapp_draft_to_recent(args: dict, **kwargs) -> str:
    """Open Nth recent chat and type a message WITHOUT sending."""
    try:
        n = int(args.get("chat_index") or args.get("n") or 1)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "chat_index must be a number starting at 1"})
    message = (args.get("message") or args.get("text") or "").strip()
    if not message:
        return json.dumps({"ok": False, "error": "message is required"})
    if n < 1 or n > 30:
        return json.dumps({"ok": False, "error": "chat_index must be between 1 and 30"})

    page = _ensure_page("https://web.whatsapp.com/", "whatsapp")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    _activate_page(page)
    time.sleep(0.65)

    try:
        status = _eval(page["webSocketDebuggerUrl"], _WA_STATUS_JS) or {}
        if not status.get("logged_in"):
            return json.dumps({
                "ok": False,
                "error": (
                    "WhatsApp Web is not logged in on the PC Chrome. "
                    "Scan the QR code once in the debug Chrome window, then ask again."
                ),
                "whatsapp": status,
            })
        expr = _WA_DRAFT_JS % (json.dumps(n), json.dumps(message))
        result = _eval(page["webSocketDebuggerUrl"], expr)
        if isinstance(result, dict) and not result.get("ok"):
            return json.dumps(result)
        return json.dumps({"ok": True, "action": "whatsapp_draft", "result": result, "sent": False})
    except Exception as e:
        return json.dumps({"ok": False, "error": f"WhatsApp draft failed: {e}"})


_WA_OPEN_BY_NAME_JS = r"""
(async (name) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const n = String(name || '').trim();
  if (!n) return {ok:false, error:'name required'};
  if (document.querySelector('[data-testid="qrcode"]')) {
    return {ok:false, error:'WhatsApp shows a QR code — log in on the PC first.'};
  }
  // Open search
  let searchBtn = document.querySelector('[data-testid="chat-list-search"]')
    || document.querySelector('button[aria-label*="Search" i]')
    || document.querySelector('[data-testid="search"]');
  if (searchBtn) searchBtn.click();
  await sleep(400);
  let input = document.querySelector('[data-testid="chat-list-search"]')
    || document.querySelector('div[contenteditable="true"][data-tab="3"]')
    || document.querySelector('#side div[contenteditable="true"]')
    || document.querySelector('div[role="textbox"][contenteditable="true"]');
  // Prefer the search box in the side panel
  const side = document.querySelector('#side') || document.querySelector('#pane-side');
  if (side) {
    const cand = side.querySelector('div[contenteditable="true"]');
    if (cand) input = cand;
  }
  if (!input) return {ok:false, error:'WhatsApp search box not found'};
  input.focus();
  try {
    document.execCommand('selectAll', false);
    document.execCommand('insertText', false, n);
  } catch (e) {
    input.textContent = n;
    input.dispatchEvent(new InputEvent('input', {bubbles:true, data:n, inputType:'insertText'}));
  }
  await sleep(900);
  // Click first search result / chat row
  const list = document.querySelector('#pane-side') || document.querySelector('[data-testid="chat-list"]') || side;
  let items = list ? Array.from(list.querySelectorAll('[data-testid="cell-frame-container"]')) : [];
  if (!items.length && list) items = Array.from(list.querySelectorAll('div[role="listitem"]'));
  if (!items.length && list) items = Array.from(list.querySelectorAll('[role="row"]'));
  // Filter out the search box itself; prefer rows that include the name text
  const lower = n.toLowerCase();
  let target = items.find(el => (el.innerText || '').toLowerCase().includes(lower)) || items[0];
  if (!target) return {ok:false, error:`No WhatsApp chat found for "${n}"`};
  target.click();
  await sleep(500);
  return {ok:true, opened_by:'name_search', name:n, preview:(target.innerText||'').split('\\n')[0]};
})(%s)
"""


def whatsapp_open_chat(args: dict, **kwargs) -> str:
    """Open a WhatsApp chat on PC or phone using memory contact / phone / WhatsApp name."""
    from . import memory_api
    from . import phone_apps

    contact_q = (
        args.get("contact")
        or args.get("name")
        or args.get("friend")
        or args.get("who")
        or ""
    ).strip()
    phone_raw = (args.get("phone") or args.get("number") or "").strip()
    wa_name = (args.get("whatsapp_name") or args.get("wa_name") or "").strip()
    device = (args.get("device") or "pc").strip().lower()
    if device in ("iphone", "mobile", "ios"):
        device = "phone"
    if device not in ("pc", "phone"):
        device = "pc"

    resolved = None
    phone_digits = None
    display = contact_q or wa_name or phone_raw

    if contact_q and not phone_raw:
        resolved = memory_api.resolve_contact(contact_q)
        if resolved.get("ok"):
            phone_digits = resolved.get("phone_digits")
            wa_name = wa_name or resolved.get("whatsapp_name") or ""
            c = resolved.get("contact") or {}
            display = c.get("title") or c.get("value") or display
            if not phone_digits and c.get("phone"):
                phone_digits = memory_api.digits_only(c.get("phone"))
        elif not wa_name:
            # treat contact string itself as WhatsApp display name
            wa_name = contact_q

    if phone_raw:
        phone_digits = memory_api.digits_only(phone_raw) or phone_digits

    if device == "phone":
        if phone_digits:
            # Prefer wa.me https (opens without confirm when HUD navigates same-tab)
            url = f"https://wa.me/{phone_digits}"
            scheme = f"whatsapp://send?phone={phone_digits}"
            res = phone_apps._jarvis_request(
                "POST",
                "/api/phone/open",
                {
                    "app": "whatsapp",
                    "label": f"WhatsApp · {display or phone_digits}",
                    "url": url,
                    "scheme": None,  # https only — avoids iOS confirm dialog
                },
            )
            if not res.get("ok"):
                return json.dumps({"ok": False, "error": res.get("error") or "phone open failed", "detail": res})
            return json.dumps({
                "ok": True,
                "device": "phone",
                "action": "whatsapp_open",
                "contact": display,
                "phone": phone_digits,
                "sent_to_hud": res.get("sent_to_hud"),
                "note": "Opening WhatsApp chat on your phone. Keep Jarvis HUD open there.",
            })
        # Name-only on phone: open WhatsApp app (cannot deep-link by contact name reliably)
        res = phone_apps.open_phone_app({"app": "whatsapp"})
        try:
            parsed = json.loads(res)
        except Exception:
            parsed = {"ok": False, "error": res}
        parsed["note"] = (
            (parsed.get("note") or "")
            + " Opened WhatsApp on phone, but no phone number was saved for this contact — "
            "add their number in Skills / Memory so Jarvis can open the exact chat next time."
        )
        parsed["contact"] = display
        return json.dumps(parsed)

    # ---- PC path ----
    if phone_digits:
        url = f"https://web.whatsapp.com/send?phone={phone_digits}"
        page = _ensure_page(url, "web.whatsapp.com", "whatsapp")
        if isinstance(page, str):
            return json.dumps({"ok": False, "error": page})
        _activate_page(page)
        time.sleep(1.0)
        try:
            status = _eval(page["webSocketDebuggerUrl"], _WA_STATUS_JS) or {}
            if status.get("looks_like_qr") and not status.get("logged_in"):
                return json.dumps({
                    "ok": False,
                    "error": "WhatsApp Web is not logged in. Scan the QR on the PC Chrome window.",
                    "whatsapp": status,
                })
        except Exception:
            pass
        return json.dumps({
            "ok": True,
            "device": "pc",
            "action": "whatsapp_open",
            "contact": display,
            "phone": phone_digits,
            "url": url,
            "note": f"Opened WhatsApp chat with {display or phone_digits} on PC.",
        })

    # Name search on WhatsApp Web
    name = wa_name or contact_q
    if not name:
        return json.dumps({
            "ok": False,
            "error": (
                "Need a contact name or phone number. "
                "Save friends in Skills / Memory with a phone or WhatsApp name first."
            ),
        })

    page = _ensure_page("https://web.whatsapp.com/", "whatsapp")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    _activate_page(page)
    time.sleep(0.65)
    try:
        status = _eval(page["webSocketDebuggerUrl"], _WA_STATUS_JS) or {}
        if not status.get("logged_in"):
            return json.dumps({
                "ok": False,
                "error": "WhatsApp Web is not logged in. Scan the QR on the PC Chrome window.",
                "whatsapp": status,
            })
        expr = _WA_OPEN_BY_NAME_JS % json.dumps(name)
        result = _eval(page["webSocketDebuggerUrl"], expr)
        if isinstance(result, dict) and not result.get("ok"):
            return json.dumps(result)
        return json.dumps({
            "ok": True,
            "device": "pc",
            "action": "whatsapp_open",
            "contact": display or name,
            "whatsapp_name": name,
            "result": result,
            "note": f"Opened WhatsApp chat matching '{name}' on PC.",
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": f"WhatsApp open failed: {e}"})


_WA_TYPE_IN_CHAT_JS = r"""
(async (message) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const text = String(message || '');
  if (!text) return {ok:false, error:'empty message'};

  const findBox = () => (
    document.querySelector('footer div[contenteditable="true"][data-tab="10"]')
    || document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]')
    || document.querySelector('div[contenteditable="true"][data-tab="10"]')
    || document.querySelector('footer div[role="textbox"]')
    || document.querySelector('#main footer div[contenteditable="true"]')
  );

  let box = null;
  for (let i = 0; i < 40; i++) {
    box = findBox();
    if (box) break;
    await sleep(500);
  }
  if (!box) return {ok:false, error:'WhatsApp message box not found — chat may still be loading'};

  const read = () => (box.innerText || box.textContent || '').replace(/\u00a0/g, ' ').trim();
  // URL ?text= often prefills already — don't double-type
  let cur = read();
  if (cur === text || cur === text + text) {
    if (cur === text + text) {
      // fix accidental duplicate from a previous attempt
      box.focus();
      try { document.execCommand('selectAll', false, null); document.execCommand('insertText', false, text); } catch (e) {}
      cur = read();
    }
    return {ok:true, typed: read(), sent:false, note:'Draft ready (prefilled).'};
  }

  box.focus();
  await sleep(100);
  try {
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
  } catch (e) {}
  // Also clear via Selection API
  try {
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(box);
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand('delete', false, null);
  } catch (e) {}
  box.textContent = '';
  box.innerHTML = '';
  box.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
  await sleep(80);

  let ok = false;
  try {
    ok = document.execCommand('insertText', false, text);
  } catch (e) { ok = false; }
  if (!ok || !read().includes(text.slice(0, Math.min(8, text.length)))) {
    box.focus();
    const dt = new DataTransfer();
    dt.setData('text/plain', text);
    box.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
    await sleep(80);
  }
  await sleep(200);
  let typed = read();
  // Collapse accidental duplicates like "hihi"
  if (text && typed === text + text) {
    try {
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, text);
    } catch (e) {}
    typed = read();
  }
  if (!typed || !typed.includes(text.slice(0, Math.min(12, text.length)))) {
    return {ok:false, error:'Could not type into WhatsApp compose box', typed};
  }
  return {ok:true, typed, sent:false, note:'Draft only — NOT sent.'};
})(%s)
"""

_WA_CLICK_SEND_JS = r"""
(async (expected) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const want = String(expected || '').trim();
  const findBox = () => (
    document.querySelector('footer div[contenteditable="true"][data-tab="10"]')
    || document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]')
    || document.querySelector('#main footer div[contenteditable="true"]')
  );
  const findSend = () => (
    document.querySelector('button[data-testid="compose-btn-send"]')
    || document.querySelector('[data-testid="compose-btn-send"]')
    || document.querySelector('button[aria-label="Send"]')
    || document.querySelector('button[aria-label*="Send" i]')
    || document.querySelector('span[data-icon="send"]')?.closest('button')
    || document.querySelector('footer button[aria-label*="Send" i]')
  );

  let box = findBox();
  if (!box) return {ok:false, error:'Message box gone before send'};
  const before = (box.innerText || box.textContent || '').replace(/\u00a0/g, ' ').trim();
  if (want && before && !before.includes(want.slice(0, Math.min(12, want.length)))) {
    return {ok:false, error:'Compose box does not contain the draft — refusing to send', typed: before};
  }
  if (!before) return {ok:false, error:'Compose box is empty — nothing to send'};

  box.focus();
  await sleep(80);
  let method = null;
  const btn = findSend();
  if (btn) {
    btn.click();
    method = 'button';
  } else {
    // Enter key as last resort (WhatsApp send, not newline, when send button would show)
    box.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true, cancelable:true}));
    box.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true, cancelable:true}));
    method = 'enter';
  }

  // Verify: compose cleared OR last outgoing bubble matches
  for (let i = 0; i < 20; i++) {
    await sleep(250);
    box = findBox();
    const after = box ? (box.innerText || box.textContent || '').replace(/\u00a0/g, ' ').trim() : '';
    if (!after || after.length < Math.min(3, before.length)) {
      return {ok:true, sent:true, method, verified:'compose_cleared'};
    }
    // Check last message in chat for our text
    const bubbles = Array.from(document.querySelectorAll('[data-testid="msg-container"], .message-out, div.message-out'));
    const last = bubbles[bubbles.length - 1];
    const lastTxt = (last && (last.innerText || '')) || '';
    if (want && lastTxt.includes(want.slice(0, Math.min(20, want.length)))) {
      return {ok:true, sent:true, method, verified:'bubble'};
    }
  }
  box = findBox();
  const still = box ? (box.innerText || '').trim() : '';
  return {
    ok:false,
    sent:false,
    error:'Clicked send but message still in the box — not confirmed sent',
    typed: still,
    method
  };
})(%s)
"""

_WA_PENDING_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / "jarvis_whatsapp_pending.json"


def _wa_pending() -> dict:
    try:
        if _WA_PENDING_PATH.is_file():
            data = json.loads(_WA_PENDING_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _wa_set_pending(data: dict) -> None:
    _WA_PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WA_PENDING_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _wa_clear_pending() -> None:
    try:
        if _WA_PENDING_PATH.is_file():
            _WA_PENDING_PATH.unlink()
    except Exception:
        pass


def _wa_jarvis_request(method: str, path: str, body: dict | None = None) -> dict:
    base = (os.environ.get("JARVIS_BASE_URL") or "http://127.0.0.1:8765").rstrip("/")
    token = os.environ.get("JARVIS_HUD_TOKEN") or "jarvis-9f2517"
    url = base + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Jarvis-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _wa_notify(title: str, body: str, *, level: str = "info") -> None:
    try:
        _wa_jarvis_request("POST", "/api/notify", {
            "title": title,
            "body": body,
            "level": level,
        })
    except Exception:
        pass


def _wa_request_approval(approval_id: str, contact: str, message: str) -> dict:
    return _wa_jarvis_request("POST", "/api/pc_approval", {
        "approval_id": approval_id,
        "kind": "whatsapp_send",
        "title": "SEND WHATSAPP?",
        "preview": f"To: {contact}\n\n{message[:800]}{'…' if len(message) > 800 else ''}",
        "description": (
            "Jarvis drafted a WhatsApp message on your PC. "
            "ALLOW = send it. DENY = leave it unsent."
        ),
    })


def _wa_poll_approval(approval_id: str, wait_seconds: float = 120.0) -> str:
    deadline = time.time() + max(5.0, wait_seconds)
    while time.time() < deadline:
        local = _wa_pending()
        if local.get("approval_id") == approval_id and local.get("decision") in ("allow", "deny"):
            return str(local["decision"])
        res = _wa_jarvis_request("GET", f"/api/pc_approval/{approval_id}")
        dec = (res.get("decision") or "").lower()
        if dec in ("allow", "deny"):
            local = _wa_pending()
            if local.get("approval_id") == approval_id:
                local["decision"] = dec
                _wa_set_pending(local)
            return dec
        time.sleep(0.8)
    return "timeout"


def _wa_normalize_phone(digits: str | None) -> str | None:
    """Ensure WhatsApp-ready digits (Kuwait local 8-digit → 965…)."""
    d = re.sub(r"\D", "", str(digits or ""))
    if len(d) < 7:
        return None
    # Kuwait mobile often saved as 9/5/6xxxxxxx (8 digits)
    if len(d) == 8 and d[0] in "9654":
        d = "965" + d
    return d


def _wa_resolve_saved_phone(contact_q: str) -> dict[str, Any]:
    """Only contacts with a phone saved in Skills/Memory (or raw digits)."""
    from . import memory_api

    q = (contact_q or "").strip()
    if not q:
        return {"ok": False, "error": "contact name is required"}

    # Allow raw phone if user typed digits
    raw_digits = _wa_normalize_phone(memory_api.digits_only(q) if re.search(r"\d{7,}", q) else None)
    if raw_digits and re.fullmatch(r"[\d\s+\-()]+", q):
        return {"ok": True, "contact": raw_digits, "phone": raw_digits, "resolved": None}

    resolved = memory_api.resolve_contact(q)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": (
                f"No saved contact matching '{q}' in Skills / Memory. "
                "Save their name and phone number first."
            ),
        }
    c = resolved.get("contact") or {}
    phone_digits = _wa_normalize_phone(
        resolved.get("phone_digits") or memory_api.digits_only(c.get("phone"))
    )
    display = c.get("title") or c.get("value") or q
    if not phone_digits:
        return {
            "ok": False,
            "error": (
                f"{display} is in Skills / Memory but has no phone number. "
                "Add their number on the Skills page, then try again."
            ),
            "contact": display,
        }
    return {"ok": True, "contact": display, "phone": phone_digits, "resolved": resolved}


def _wa_cdp_insert_text(ws: str, text: str) -> None:
    """Type via CDP Input — more reliable than DOM hacks on WhatsApp React."""
    try:
        _cdp_call(ws, "Input.insertText", {"text": text})
    except Exception:
        # Older Chrome: dispatch key events char by char (slow but works)
        for ch in text[:500]:
            try:
                _cdp_call(ws, "Input.dispatchKeyEvent", {
                    "type": "keyDown", "text": ch, "unmodifiedText": ch,
                    "key": ch, "code": f"Key{ch.upper()}" if ch.isalpha() else "",
                }, timeout=4.0)
                _cdp_call(ws, "Input.dispatchKeyEvent", {
                    "type": "keyUp", "key": ch,
                }, timeout=4.0)
            except Exception:
                break


def _wa_wait_until_ready(ws: str, *, timeout: float = 90.0) -> dict:
    """WhatsApp Web often syncs for a long time on first open — wait for chat UI."""
    deadline = time.time() + max(15.0, timeout)
    last: dict = {}
    while time.time() < deadline:
        try:
            last = _eval(ws, _WA_WAIT_READY_JS) or {}
        except Exception as e:
            last = {"ready": False, "error": str(e)}
        if last.get("qr"):
            return {"ready": False, "qr": True, "error": "WhatsApp shows a QR code — scan it on the PC Chrome window."}
        if last.get("ready"):
            time.sleep(0.4)
            return {"ready": True, **last}
        time.sleep(0.9)
    return {
        "ready": False,
        "error": "WhatsApp is still loading/syncing on the PC. Keep that Chrome window open and try again in a moment.",
        **(last if isinstance(last, dict) else {}),
    }


def _wa_open_chat_and_prepare(phone_digits: str, message: str) -> tuple[dict | str, dict]:
    """Open WhatsApp Web on PC, wait until synced, open chat, put message in compose."""
    from . import tools as app_tools

    # 1) Ensure debug Chrome + open WhatsApp (visible)
    err = app_tools._ensure_cdp()
    if err:
        return err, {"ok": False, "error": err}
    try:
        app_tools.open_pc_app({"app": "whatsapp"})
    except Exception:
        pass

    home = "https://web.whatsapp.com/"
    page = _ensure_page(home, "web.whatsapp.com", "whatsapp")
    if isinstance(page, str):
        # Force a fresh tab
        opened = app_tools._open_url_in_chrome(home, source="whatsapp_open")
        if not opened.get("ok"):
            return opened.get("error") or "Could not open WhatsApp", {"ok": False, "error": "Could not open WhatsApp on PC Chrome."}
        time.sleep(1.0)
        page = _find_page("web.whatsapp.com", "whatsapp") or opened.get("target")
        if not page or not isinstance(page, dict) or not page.get("webSocketDebuggerUrl"):
            return "WhatsApp tab not found", {"ok": False, "error": "WhatsApp tab not found after open."}
    _activate_page(page)
    ws = page["webSocketDebuggerUrl"]
    try:
        _cdp_call(ws, "Page.navigate", {"url": home})
    except Exception:
        pass
    time.sleep(1.0)

    # 2) Wait out "messages are downloading" / chat sync
    ready = _wa_wait_until_ready(ws, timeout=100.0)
    if not ready.get("ready"):
        return page, {"ok": False, "error": ready.get("error") or "WhatsApp not ready on PC.", "whatsapp": ready}

    # 3) Open the specific chat (phone + optional prefilled text)
    text_q = urllib.parse.quote(message, safe="")
    url = f"https://web.whatsapp.com/send?phone={phone_digits}&text={text_q}"
    try:
        _cdp_call(ws, "Page.navigate", {"url": url})
    except Exception as e:
        return page, {"ok": False, "error": f"Could not open chat URL: {e}"}
    time.sleep(1.5)

    # Chat open can bounce while still hydrating — wait for compose again
    box_deadline = time.time() + 45.0
    typed: dict = {"ok": False}
    while time.time() < box_deadline:
        try:
            st = _eval(ws, _WA_WAIT_READY_JS) or {}
        except Exception:
            st = {}
        if st.get("qr"):
            return page, {"ok": False, "error": "WhatsApp shows a QR code — scan it on the PC Chrome window."}
        if st.get("has_box") or st.get("has_main"):
            break
        # If redirected home while syncing, wait then re-hit send URL
        if st.get("downloading") or (st.get("has_side") and not st.get("has_box")):
            time.sleep(1.0)
            if st.get("downloading"):
                continue
            try:
                _cdp_call(ws, "Page.navigate", {"url": url})
            except Exception:
                pass
            time.sleep(1.2)
            continue
        time.sleep(0.8)
    else:
        return page, {
            "ok": False,
            "error": "Opened WhatsApp but the chat/message box did not appear. Is the number valid?",
        }

    # 4) Type / verify message in compose
    try:
        typed = _eval(ws, _WA_TYPE_IN_CHAT_JS % json.dumps(message)) or {"ok": False}
    except Exception as e:
        typed = {"ok": False, "error": str(e)}

    if not (isinstance(typed, dict) and typed.get("ok")):
        try:
            _eval(ws, r"""
(() => {
  const box = document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]');
  if (box) { box.focus(); return true; }
  return false;
})()
""")
            time.sleep(0.2)
            _wa_cdp_insert_text(ws, message)
            time.sleep(0.4)
            typed = _eval(ws, r"""
(() => {
  const box = document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]');
  const typed = box ? (box.innerText || box.textContent || '').trim() : '';
  return {ok: !!typed, typed, sent:false};
})()
""") or typed
        except Exception as e:
            typed = {"ok": False, "error": f"Typing failed: {e}"}

    # Prefill from URL may already be enough
    if not (isinstance(typed, dict) and typed.get("ok")):
        try:
            check = _eval(ws, r"""
(() => {
  const box = document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]');
  return box ? (box.innerText || box.textContent || '').trim() : '';
})()
""") or ""
            if message[:8] in str(check):
                typed = {"ok": True, "typed": check, "sent": False}
        except Exception:
            pass

    return page, typed if isinstance(typed, dict) else {"ok": False, "error": str(typed)}


def whatsapp_draft_to_contact(args: dict, **kwargs) -> str:
    """Type a WhatsApp message on PC Web to a Skills/Memory contact. Send only after phone ALLOW."""
    import uuid

    contact_q = (args.get("contact") or args.get("name") or args.get("to") or "").strip()
    message = (args.get("message") or args.get("text") or "").strip()
    want_send = bool(args.get("send") or args.get("and_send"))
    try:
        wait_seconds = float(args.get("wait_seconds") if args.get("wait_seconds") is not None else 120)
    except (TypeError, ValueError):
        wait_seconds = 120.0

    if not message:
        return json.dumps({"ok": False, "error": "message is required"})
    who = _wa_resolve_saved_phone(contact_q)
    if not who.get("ok"):
        return json.dumps(who)

    display = who["contact"]
    phone_digits = who["phone"]
    page, typed = _wa_open_chat_and_prepare(phone_digits, message)
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    if not typed.get("ok"):
        return json.dumps({
            "ok": False,
            "sent": False,
            "error": typed.get("error") or f"Could not type message to {display} on WhatsApp PC.",
            "contact": display,
            "phone": phone_digits,
        })

    _wa_notify("WhatsApp draft", f"To {display}: {message[:120]}", level="info")

    if not want_send:
        _wa_clear_pending()
        return json.dumps({
            "ok": True,
            "action": "whatsapp_draft_to_contact",
            "sent": False,
            "contact": display,
            "phone": phone_digits,
            "typed": typed.get("typed") or message,
            "message": f"Typed to {display} on WhatsApp on your PC (not sent).",
        })

    approval_id = f"wa-{uuid.uuid4().hex[:12]}"
    pending = {
        "approval_id": approval_id,
        "contact": display,
        "phone": phone_digits,
        "message": message,
        "target_id": page.get("id"),
        "decision": None,
        "sent": False,
    }
    _wa_set_pending(pending)
    phone_appr = _wa_request_approval(approval_id, display, message)
    _wa_notify("Send WhatsApp?", f"ALLOW to send to {display}", level="approval")

    decision = _wa_poll_approval(approval_id, wait_seconds)
    if decision == "deny":
        _wa_clear_pending()
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": "deny",
            "contact": display,
            "message": f"Denied — message to {display} was not sent (draft left on PC WhatsApp).",
        })
    if decision != "allow":
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": decision,
            "approval_id": approval_id,
            "contact": display,
            "phone_approval": phone_appr,
            "message": (
                f"Draft to {display} is on PC WhatsApp (not sent). "
                "Open the Jarvis HUD on your phone and tap ALLOW, then say 'send the whatsapp' — "
                "or I timed out waiting."
            ),
        })

    return whatsapp_send({"wait_seconds": 5, "approval_id": approval_id})


def whatsapp_send(args: dict, **kwargs) -> str:
    """Send the pending WhatsApp draft on PC ONLY after phone ALLOW. Verifies compose cleared."""
    try:
        wait_seconds = float(args.get("wait_seconds") if args.get("wait_seconds") is not None else 120)
    except (TypeError, ValueError):
        wait_seconds = 120.0

    pending = _wa_pending()
    approval_id = (args.get("approval_id") or pending.get("approval_id") or "").strip()
    if not approval_id or pending.get("sent"):
        return json.dumps({
            "ok": False,
            "sent": False,
            "error": "No pending WhatsApp draft. Ask me to type to someone and send first.",
        })

    decision = (pending.get("decision") or "").lower()
    if decision not in ("allow", "deny"):
        decision = _wa_poll_approval(approval_id, wait_seconds)

    if decision == "deny":
        _wa_clear_pending()
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": "deny",
            "message": "You denied the WhatsApp send. Draft was not sent.",
        })
    if decision != "allow":
        return json.dumps({
            "ok": False,
            "sent": False,
            "decision": decision,
            "approval_id": approval_id,
            "message": "Still waiting for phone ALLOW. Open Jarvis HUD and tap ALLOW.",
        })

    message = str(pending.get("message") or "")
    phone_digits = str(pending.get("phone") or "")
    contact = pending.get("contact") or "contact"

    page = _find_page("web.whatsapp.com", "whatsapp")
    if (not page or not page.get("webSocketDebuggerUrl")) and phone_digits:
        page, typed = _wa_open_chat_and_prepare(phone_digits, message)
        if isinstance(page, str) or not typed.get("ok"):
            return json.dumps({
                "ok": False,
                "sent": False,
                "error": "WhatsApp tab missing and could not reopen the chat to send.",
            })
    if not page or not page.get("webSocketDebuggerUrl"):
        return json.dumps({"ok": False, "sent": False, "error": "WhatsApp tab is gone. Draft was not sent."})

    ws = page["webSocketDebuggerUrl"]
    _activate_page(page)
    time.sleep(0.35)

    # Ensure draft is still in the box before clicking send
    try:
        check = _eval(ws, r"""
(() => {
  const box = document.querySelector('footer div[contenteditable="true"]')
    || document.querySelector('[data-testid="conversation-compose-box-input"]');
  return box ? (box.innerText || box.textContent || '').trim() : '';
})()
""") or ""
    except Exception:
        check = ""
    if message and (not check or message[:12] not in str(check)):
        # Re-type then send
        page2, typed = _wa_open_chat_and_prepare(phone_digits, message)
        if isinstance(page2, dict):
            page = page2
            ws = page["webSocketDebuggerUrl"]
        if not (isinstance(typed, dict) and typed.get("ok")):
            return json.dumps({
                "ok": False,
                "sent": False,
                "error": "Could not put the message back in WhatsApp before sending.",
            })

    try:
        result = _eval(ws, _WA_CLICK_SEND_JS % json.dumps(message))
    except Exception as e:
        return json.dumps({"ok": False, "sent": False, "error": f"Send failed: {e}"})

    if not isinstance(result, dict) or not result.get("ok") or not result.get("sent"):
        return json.dumps({
            "ok": False,
            "sent": False,
            "error": (result or {}).get("error") if isinstance(result, dict) else str(result),
            "detail": result,
            "message": f"Did NOT send to {contact} — WhatsApp did not confirm the send.",
        })

    _wa_clear_pending()
    _wa_jarvis_request("POST", f"/api/pc_approval/{approval_id}/consume", {"status": "sent"})
    _wa_notify("WhatsApp sent", f"Sent to {contact}", level="success")
    return json.dumps({
        "ok": True,
        "action": "whatsapp_send",
        "sent": True,
        "contact": contact,
        "phone": phone_digits,
        "decision": "allow",
        "verified": result.get("verified"),
        "message": f"Sent to {contact} on WhatsApp from your PC.",
    })


# ---- Google Classroom ----

_CLASSROOM_TODO_URL = "https://classroom.google.com/u/0/a/not-turned-in/all"

_CLASSROOM_SCRAPE_JS = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  await sleep(800);

  const text = (document.body && (document.body.innerText || '')) || '';
  const lower = text.toLowerCase();
  if (lower.includes('sign in') && (lower.includes('google') || document.querySelector('input[type="email"]'))) {
    return {ok:false, error:'Google Classroom is not signed in on this Chrome profile. Sign in once in the debug Chrome window, then ask again.'};
  }

  const items = [];
  const seen = new Set();

  // Prefer structured assignment rows / list items
  const candidates = Array.from(document.querySelectorAll(
    '[data-stream-item-id], [jsname], li, div[role="listitem"], a[href*="/c/"]'
  ));

  const push = (title, className, dueRaw, postedRaw, href) => {
    title = (title || '').replace(/\s+/g, ' ').trim();
    if (!title || title.length < 2 || title.length > 160) return;
    const key = (title + '|' + (dueRaw||'') + '|' + (postedRaw||'') + '|' + (className||'')).toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    items.push({
      title,
      class_name: (className || '').replace(/\s+/g, ' ').trim() || null,
      due_raw: (dueRaw || '').replace(/\s+/g, ' ').trim() || null,
      posted_raw: (postedRaw || '').replace(/\s+/g, ' ').trim() || null,
      href: href || null,
    });
  };

  // Assignment detail links (real homework, not the class sidebar)
  document.querySelectorAll('a[href*="/a/"][href*="/details"]').forEach(a => {
    const href = a.href || '';
    let blob = (a.innerText || '').replace(/\s+/g, ' ').trim();
    blob = blob.replace(/^assignment\s*/i, '');
    if (!blob) return;
    const dueM = blob.match(/(?<!Posted\s)\b(?:Due\s+)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?:,\s*\d{1,2}:\d{2}\s*(?:AM|PM))?/i)
      || blob.match(/\bDue\s+(?:today|tomorrow|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s*\d{4})?|\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)/i);
    const postedM = blob.match(/\bPosted\s+(?:today|yesterday|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s*\d{4})?|\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)/i);
    let title = blob;
    let className = null;
    let dueRaw = dueM ? dueM[0] : null;
    let postedRaw = postedM ? postedM[0] : null;
    if (dueRaw) title = blob.slice(0, blob.toLowerCase().indexOf(dueRaw.toLowerCase())).trim();
    else if (postedRaw) title = blob.slice(0, blob.toLowerCase().indexOf(postedRaw.toLowerCase())).trim();
    // trailing class name is usually the last short token before due, or before Posted
    const classM = title.match(/\b([A-Z0-9][A-Z0-9 .\/\-]{1,40}\d{2}\/\d{2}|G9S(?:-[A-Za-z. ]+)?)\s*$/);
    if (classM) {
      className = classM[1].trim();
      title = title.slice(0, classM.index).trim();
    }
    push(title || blob.slice(0, 120), className, dueRaw, postedRaw, href);
  });

  // Strategy A: walk likely card-like nodes only if no assignment links
  if (items.length) {
    return {
      ok: true,
      count: items.length,
      items,
      url: location.href,
      note: 'Parsed assignment links from Classroom To-do.',
    };
  }
  for (const el of candidates.slice(0, 400)) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 500) continue;
    const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
    if (lines.length < 1) continue;
    const blob = t.toLowerCase();
    if (!(blob.includes('due') || blob.includes('assigned') || /jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}\/\d{1,2}/i.test(t))) {
      continue;
    }
    const title = lines[0];
    let className = null;
    let dueRaw = null;
    let postedRaw = null;
    for (const line of lines.slice(1, 8)) {
      if (/^due\b/i.test(line) || /\bdue\b/i.test(line)) dueRaw = dueRaw || line;
      else if (/^posted\b/i.test(line) || /\bposted\b/i.test(line)) postedRaw = postedRaw || line;
      else if (!className && line.length < 80) className = line;
    }
    const a = el.closest('a') || el.querySelector('a') || (el.tagName === 'A' ? el : null);
    push(title, className, dueRaw, postedRaw, a && a.href);
    if (items.length >= 40) break;
  }

  // Strategy B: regex over visible text blocks if still empty
  if (!items.length) {
    const blocks = text.split(/\n+/).map(s => s.trim()).filter(s => s.length > 2 && s.length < 120);
    for (let i = 0; i < blocks.length; i++) {
      const line = blocks[i];
      const next = blocks[i+1] || '';
      const next2 = blocks[i+2] || '';
      if (/^due\b/i.test(next) || /^due\b/i.test(next2) || /\bdue\b/i.test(line)) {
        const title = /^due\b/i.test(line) ? (blocks[i-1] || line) : line;
        const dueRaw = /^due\b/i.test(next) ? next : (/^due\b/i.test(next2) ? next2 : line);
        push(title, null, dueRaw, null, null);
      } else if (/^posted\b/i.test(next) || /^posted\b/i.test(next2) || /\bposted\b/i.test(line)) {
        const title = /^posted\b/i.test(line) ? (blocks[i-1] || line) : line;
        const postedRaw = /^posted\b/i.test(next) ? next : (/^posted\b/i.test(next2) ? next2 : line);
        push(title, null, null, postedRaw, null);
      }
      if (items.length >= 40) break;
    }
  }

  return {
    ok: true,
    count: items.length,
    items,
    url: location.href,
    note: items.length
      ? 'Parsed from signed-in Classroom To-do / page content.'
      : 'No due items found on the page. Open To-do manually or enter a class, then retry.',
  };
})()
"""


def _parse_classroom_due(due_raw: str | None) -> str | None:
    """Best-effort -> YYYY-MM-DD. Returns None if unparseable."""
    from datetime import datetime, timedelta

    if not due_raw:
        return None
    s = due_raw.strip()
    # Never treat a Posted line as a due date.
    if re.search(r"(?i)^\s*posted\b", s):
        return None
    today = datetime.now().date()

    low = s.lower()
    if "today" in low:
        return today.isoformat()
    if "tomorrow" in low:
        return (today + timedelta(days=1)).isoformat()

    week = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    m = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
    if m:
        target = week[m.group(1)]
        delta = (target - today.weekday()) % 7
        return (today + timedelta(days=delta)).isoformat()

    # Due Apr 3 or Due Apr 3, 2026 or Apr 3
    m = re.search(
        r"(?:due\s*)?(?:on\s*)?"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?",
        s,
        re.I,
    )
    if m:
        mon_s, day_s, year_s = m.group(1), m.group(2), m.group(3)
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        mon = months[mon_s[:3].lower()]
        year = int(year_s) if year_s else today.year
        try:
            d = datetime(year, mon, int(day_s)).date()
            if not year_s and d < today - timedelta(days=180):
                d = datetime(year + 1, mon, int(day_s)).date()
            return d.isoformat()
        except ValueError:
            pass

    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        year = today.year if not y else (2000 + int(y) if len(y) == 2 else int(y))
        # assume M/D
        try:
            return datetime(year, a, b).date().isoformat()
        except ValueError:
            try:
                return datetime(year, b, a).date().isoformat()
            except ValueError:
                pass
    return None


# Undated To-do items are kept only if Classroom shows they were posted this recently.
_UNDATED_POSTED_MAX_DAYS = 3


def _parse_classroom_posted(*blobs: str | None) -> tuple[str | None, str | None]:
    """Parse Classroom 'Posted …' → (YYYY-MM-DD, raw match). Past weekday = last occurrence."""
    from datetime import datetime, timedelta

    text = " ".join(str(b) for b in blobs if b).strip()
    if not text:
        return None, None
    m = re.search(
        r"(?i)\bposted\s+"
        r"(today|yesterday|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+\d{1,2}(?:,?\s*\d{4})?|"
        r"\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
        text,
    )
    if not m:
        return None, None
    raw = m.group(0).strip()
    rest = m.group(1).strip()
    today = datetime.now().date()
    low = rest.lower()

    if low == "today":
        return today.isoformat(), raw
    if low == "yesterday":
        return (today - timedelta(days=1)).isoformat(), raw

    week = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    if low in week:
        # Posted weekday is in the past (Classroom never means "next Monday" for Posted).
        delta = (today.weekday() - week[low]) % 7
        if delta == 0:
            delta = 7
        return (today - timedelta(days=delta)).isoformat(), raw

    # Reuse due-date month/day parser on the posted fragment.
    parsed = _parse_classroom_due(rest)
    if parsed:
        # Posted dates should not jump forward a year; prefer last occurrence.
        from datetime import date as date_cls
        try:
            d = date_cls.fromisoformat(parsed)
            if d > today:
                try:
                    d = d.replace(year=d.year - 1)
                except ValueError:
                    pass
            return d.isoformat(), raw
        except ValueError:
            return parsed, raw
    return None, raw


def _score_assignment(
    title: str,
    class_name: str | None,
    raw_title: str,
    due_raw: str | None,
    date: str | None,
    posted_date: str | None = None,
) -> dict:
    """Keep dated dues. Undated work only if posted within the last 3 days."""
    from datetime import date as date_cls

    blob = " ".join(x for x in (title, class_name, raw_title, due_raw) if x)
    low = blob.lower()
    old_year = bool(re.search(r"\b(2019|2020|2021|2022|2023|2024)\b", blob))
    old_class = bool(re.search(r"\b(4ku|8s|archived|2022-2023|2021-2022)\b", low))
    if old_year or old_class:
        return {"score": 0, "important": False, "why": "older class or posted year, skipped"}
    if date:
        return {"score": 90, "important": True, "why": "has a due date"}

    # No due date → only keep if posted recently (default: last 3 days).
    if posted_date:
        try:
            posted = date_cls.fromisoformat(posted_date)
            age = (date_cls.today() - posted).days
        except ValueError:
            age = None
        if age is not None and age < 0:
            age = 0
        if age is not None and age <= _UNDATED_POSTED_MAX_DAYS:
            return {
                "score": 70,
                "important": True,
                "why": f"no due date, posted {age} day(s) ago (within {_UNDATED_POSTED_MAX_DAYS})",
            }
        if age is not None:
            return {
                "score": 5,
                "important": False,
                "why": f"no due date, posted {age} day(s) ago (older than {_UNDATED_POSTED_MAX_DAYS})",
            }
    return {
        "score": 10,
        "important": False,
        "why": "no due date and no recent posted date (need Posted within 3 days)",
    }


def classroom_pull_dues(args: dict, **kwargs) -> str:
    """Open Classroom To-do in signed-in Chrome, scrape dues, optionally import to calendar."""
    from . import calendar_api

    import_to_cal = args.get("import_to_calendar")
    if import_to_cal is None:
        import_to_cal = False
    import_to_cal = bool(import_to_cal)

    page = _ensure_page(_CLASSROOM_TODO_URL, "classroom.google.com")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    _activate_page(page)
    time.sleep(0.3)
    # Navigate to to-do if we landed on home
    try:
        cur = _eval(page["webSocketDebuggerUrl"], "location.href") or ""
        if "not-turned-in" not in str(cur):
            _cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": _CLASSROOM_TODO_URL})
            time.sleep(1.1)
    except Exception:
        pass

    try:
        scraped = _eval(page["webSocketDebuggerUrl"], _CLASSROOM_SCRAPE_JS) or {}
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Classroom scrape failed: {e}"})

    if not scraped.get("ok"):
        return json.dumps(scraped if isinstance(scraped, dict) else {"ok": False, "error": str(scraped)})

    parsed = []
    junk = {"assigned", "missing", "done", "to-do", "home", "calendar", "classroom"}
    for it in scraped.get("items") or []:
        raw_title = (it.get("title") or "").strip()
        title = re.sub(r"Posted.*$", "", raw_title, flags=re.I).strip(" -")
        title = re.sub(r"\bDue\b.*$", "", title, flags=re.I).strip(" -")
        if title.lower() in junk or len(title) < 2:
            continue
        due_raw = it.get("due_raw")
        posted_raw_field = it.get("posted_raw")
        # Legacy scrapes stuffed Posted into due_raw — peel that off.
        if due_raw and re.search(r"(?i)^\s*posted\b", str(due_raw)):
            if not posted_raw_field:
                posted_raw_field = due_raw
            due_raw = None
        posted_date, posted_raw = _parse_classroom_posted(
            posted_raw_field, due_raw, raw_title, it.get("notes")
        )
        date = _parse_classroom_due(due_raw)
        scored = _score_assignment(
            title, it.get("class_name"), raw_title, due_raw, date, posted_date=posted_date
        )
        parsed.append({
            "title": title,
            "class_name": it.get("class_name"),
            "due_raw": due_raw,
            "posted_raw": posted_raw or posted_raw_field,
            "posted_date": posted_date,
            "date": date,
            "href": it.get("href"),
            "kind": "due" if date else "undated",
            "source": "classroom",
            "notes": due_raw or posted_raw or posted_raw_field,
            "important": scored["important"],
            "importance": scored["score"],
            "why": scored["why"],
        })

    import_result = None
    if import_to_cal:
        importable = [p for p in parsed if p.get("date") and p.get("title")]
        skipped = [p for p in parsed if not p.get("date")]
        if importable:
            import_result = calendar_api.calendar_import_events(importable)
        else:
            import_result = {"ok": True, "added": 0, "note": "No parseable dates to import", "skipped": skipped}

    return json.dumps({
        "ok": True,
        "action": "classroom_pull_dues",
        "found": len(parsed),
        "items": parsed,
        "imported": import_result,
        "hud_page": "/hud/calendar.html",
        "message": (
            f"Found {len(parsed)} Classroom item(s). "
            + ("Imported dated items into the calendar." if import_to_cal else "Not imported (import_to_calendar=false).")
            + " Undated work is kept only if posted within the last 3 days."
            + " Open Calendar / Schedule on the HUD to review or delete."
        ),
    })


_SUBMIT_RE_JS = r"turn in|hand in|submit|mark as done|entregar|تسليم"


def classroom_account_probe() -> dict[str, Any]:
    """Open Classroom and report whether the signed-in Chrome profile can use it.

    Does not click Turn in / Submit. Returns signed_in, account hint, and blockers.
    """
    page = _ensure_page(_CLASSROOM_TODO_URL, "classroom.google.com")
    if isinstance(page, str):
        # maybe still on accounts.google.com
        page = _find_page("accounts.google.com", "classroom") or _find_page("classroom.google.com")
        if not page:
            return {"ok": False, "signed_in": False, "error": str(page) if isinstance(page, str) else "Chrome debug not connected. Start Jarvis Chrome debug and sign in once."}
    _activate_page(page)
    time.sleep(0.25)
    js = r"""
(() => {
  const url = location.href || '';
  const title = document.title || '';
  const text = ((document.body && document.body.innerText) || '').slice(0, 2500);
  const low = text.toLowerCase();
  const signIn = /accounts\.google\.com/.test(url) || /sign in/i.test(title)
    || (low.includes('sign in') && (low.includes('email') || low.includes('phone')));
  const blocked = /only available to school|isn't available|not available for your account|request access/i.test(text);
  const emails = (text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi) || []).slice(0, 4);
  const edu = emails.find(e => /\.edu(\.[a-z]{2})?$/i.test(e) || /@([a-z0-9-]+\.)*edu\b/i.test(e));
  return {
    url, title, sign_in: signIn, blocked, emails, edu_email: edu || null,
    snippet: text.slice(0, 400),
  };
})()
"""
    try:
        info = _eval(page.get("webSocketDebuggerUrl"), js) or {}
    except Exception as exc:
        return {"ok": False, "signed_in": False, "error": f"Could not read Classroom: {exc}"}
    signed = not info.get("sign_in") and "classroom.google.com" in str(info.get("url") or "")
    return {
        "ok": True,
        "signed_in": bool(signed),
        "blocked": bool(info.get("blocked")),
        "edu_email": info.get("edu_email"),
        "emails_seen": info.get("emails") or [],
        "url": info.get("url"),
        "title": info.get("title"),
        "note": (
            "Classroom is not signed in on the Jarvis Chrome profile."
            if info.get("sign_in") else
            "This account page says Classroom is not available."
            if info.get("blocked") else
            "Classroom page is open."
        ),
    }


def _doc_readonly_url(href: str) -> str | None:
    import re
    m = re.search(r"docs\.google\.com/document/d/([A-Za-z0-9_-]+)", href or "")
    if not m:
        return None
    return f"https://docs.google.com/document/d/{m.group(1)}/mobilebasic"


def _drive_preview_url(href: str) -> str | None:
    import re
    m = re.search(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)", href or "")
    if not m:
        return None
    return f"https://drive.google.com/file/d/{m.group(1)}/preview"


def _clean_attachment_text(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\u00a0", " ")
    return t.strip()


def _is_image_attachment(title: str, href: str) -> bool:
    blob = f"{title} {href}".lower()
    return bool(re.search(r"\.(png|jpe?g|gif|webp|bmp)\b", blob)) or " image" in f" {blob}"


def _shot_dir() -> Path:
    root = Path(os.environ.get("JARVIS_LOGS_DIR", r"D:\jarvis_kokoro\server-logs"))
    path = root / "classroom_shots"
    path.mkdir(parents=True, exist_ok=True)
    shots = sorted(path.glob("att_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in shots[6:]:
        try:
            old.unlink()
        except Exception:
            pass
    return path


def _screenshot_jpeg(ws: str) -> str | None:
    """Small JPEG of the open attachment. Does not click anything."""
    clip = None
    try:
        box = _eval(ws, r"""
(() => {
  const imgs = Array.from(document.querySelectorAll('img')).filter(img => {
    const r = img.getBoundingClientRect();
    return r.width > 80 && r.height > 80 && img.naturalWidth > 20;
  });
  const img = imgs.sort((a, b) => (b.width * b.height) - (a.width * a.height))[0];
  if (!img) return null;
  const c = document.createElement('canvas');
  c.width = 8; c.height = 8;
  let blank = false;
  try {
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0, 8, 8);
    const d = ctx.getImageData(0, 0, 8, 8).data;
    let dark = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] + d[i+1] + d[i+2] < 700) dark++;
    }
    blank = dark < 2;
  } catch (e) { blank = false; }
  if (blank) return null;
  const r = img.getBoundingClientRect();
  return { x: r.x, y: r.y, width: r.width, height: r.height, scale: 1 };
})()
""") or None
        if isinstance(box, dict) and box.get("width", 0) > 80:
            clip = box
    except Exception:
        clip = None
    params: dict[str, Any] = {"format": "jpeg", "quality": 42, "fromSurface": True}
    if clip:
        params["clip"] = clip
    try:
        _cdp_call(ws, "Page.enable", {}, timeout=5.0)
    except Exception:
        pass
    result = _cdp_call(ws, "Page.captureScreenshot", params, timeout=15.0)
    raw = base64.b64decode((result or {}).get("data") or "")
    # A clipped photo can be a small file. A blank full-page shot is also small, so reject only those.
    if len(raw) < (2500 if clip else 18000):
        return None
    path = _shot_dir() / f"att_{int(time.time())}.jpg"
    path.write_bytes(raw)
    return str(path)


def _assignment_snap_js() -> str:
    return r"""
(() => {
  const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
    .map(b => (b.innerText || b.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim())
    .filter(Boolean);
  const submitish = buttons.filter(t => /turn in|hand in|submit|mark as done/i.test(t));
  const seen = new Set();
  const attachments = [];
  for (const a of Array.from(document.querySelectorAll('a[href]'))) {
    const href = a.href || '';
    const title = (a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim().slice(0, 120);
    const blob = (href + ' ' + title).toLowerCase();
    const file = /docs\.google\.com\/(document|presentation|spreadsheets)|drive\.google\.com\/file|googleusercontent\.com/.test(href)
      || /\.(png|jpe?g|gif|webp|pdf)\b/.test(blob);
    if (!file || seen.has(href)) continue;
    seen.add(href);
    attachments.push({ title: title || 'file', href });
    if (attachments.length >= 6) break;
  }
  const text = ((document.body && document.body.innerText) || '').replace(/\n{3,}/g, '\n\n').slice(0, 2500);
  const ready = attachments.length > 0;
  return { title: document.title, url: location.href, text, submitish, attachments, ready, clicked_submit: false };
})()
"""


def _click_classroom_refresh(ws: str) -> bool:
    """Classroom's own Refresh button, not Mark as done / Turn in."""
    try:
        clicked = _eval(ws, r"""
(() => {
  const b = Array.from(document.querySelectorAll('button, [role="button"]'))
    .find(el => /^refresh$/i.test((el.innerText || el.getAttribute('aria-label') || '').trim()));
  if (!b) return 'none';
  b.click();
  return 'refresh';
})()
""")
    except Exception:
        return False
    return clicked == "refresh"


def _read_assignment_readonly(ws: str, href: str) -> dict[str, Any]:
    """Open an assignment, its Google Docs, and attached images. Never submits."""
    # Stay on the signed-in Classroom tab. A new tab often never loads the card.
    _cdp_call(ws, "Page.navigate", {"url": href})
    detail: dict[str, Any] = {}
    for _ in range(8):
        time.sleep(1.0)
        try:
            detail = _eval(ws, _assignment_snap_js()) or {}
        except Exception:
            detail = {}
        if detail.get("ready"):
            break
    if not detail.get("ready"):
        for attempt in range(2):
            if not _click_classroom_refresh(ws):
                time.sleep(1.2)
                continue
            for _ in range(10):
                time.sleep(1.0)
                try:
                    detail = _eval(ws, _assignment_snap_js()) or {}
                except Exception:
                    detail = {}
                if detail.get("ready"):
                    break
            if detail.get("ready"):
                break
            time.sleep(1.5)
    card = str(detail.get("text") or "")
    cut = card.lower().rfind("\nassignment")
    if cut < 0:
        cut = card.lower().rfind("assignment")
    if cut > 40:
        card = card[cut:]
    parts = [card[:900]]
    images: list[dict[str, str]] = []
    seen = set()
    docs = []
    pics = []
    for att in detail.get("attachments") or []:
        href_att = att.get("href") or ""
        title = att.get("title") or "file"
        if _is_image_attachment(title, href_att):
            pics.append(att)
        elif _doc_readonly_url(href_att) or _drive_preview_url(href_att):
            docs.append(att)
    for att in docs[:2] + pics[:2]:
        href_att = att.get("href") or ""
        title = att.get("title") or "file"
        is_image = _is_image_attachment(title, href_att)
        target = (_drive_preview_url(href_att) if is_image else None) or _doc_readonly_url(href_att) or _drive_preview_url(href_att)
        if not target or target in seen:
            continue
        seen.add(target)
        try:
            _cdp_call(ws, "Page.navigate", {"url": target})
            time.sleep(6.5 if is_image else 5.5)
            if is_image:
                shot = None
                for _ in range(3):
                    shot = _screenshot_jpeg(ws)
                    if shot:
                        break
                    time.sleep(2.0)
                if shot:
                    images.append({"title": title, "path": shot})
                    parts.append(f"Image attachment opened (not submitted): {title}. Saved a small copy for me to look at.")
                else:
                    parts.append(f"Opened image {title} but could not capture it.")
                continue
            doc_text = _eval(ws, r"""
(() => ((document.body && document.body.innerText) || '').replace(/\n{3,}/g,'\n\n').slice(0, 5000))()
""") or ""
            doc_text = _clean_attachment_text(doc_text)
            if doc_text:
                parts.append(f"Google Doc / file {title} (read-only, not submitted):\n{doc_text}")
        except Exception as exc:
            parts.append(f"Could not read attachment: {exc}")
    return {
        "title": detail.get("title"),
        "url": href,
        "text": _clean_attachment_text("\n\n".join(p for p in parts if p))[:7000],
        "attachments": detail.get("attachments") or [],
        "images": images,
        "submit_buttons_present": detail.get("submitish") or [],
        "submitted": False,
    }


_CLASSROOM_HOME = "https://classroom.google.com/u/0/h"

_CLASSROOM_LIST_CLASSES_JS = r"""
(() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/c/"]').forEach(a => {
    const href = a.href || '';
    if (!/\/c\/[a-zA-Z0-9_-]+/.test(href)) return;
    if (/\/a\//.test(href) && !/\/c\/[^/]+\/?$/.test(href.replace(/\?.*$/,''))) {
      // allow class home links; skip deep assignment links for the class list
    }
    let name = (a.getAttribute('aria-label') || a.innerText || '').replace(/\s+/g,' ').trim();
    name = name.replace(/^([A-Za-z0-9])\s+(?=\1)/, '');
    if (!name || name.length > 100) return;
    if (/to-do|calendar|settings|archived|classwork|stream|people/i.test(name)) return;
    const key = name.toLowerCase() + '|' + href.split('?')[0];
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ name, href: href.split('?')[0] });
  });
  return out.slice(0, 40);
})()
"""

_CLASSROOM_FIND_MATERIAL_JS = r"""
(needle) => {
  const q = String(needle || '').toLowerCase();
  const wantPdf = /\bpdf\b|book|textbook|workbook/.test(q);
  const out = [];
  const seen = new Set();
  const push = (title, href, kind) => {
    title = (title || '').replace(/\s+/g,' ').trim();
    href = href || '';
    if (!title || !href || seen.has(href)) return;
    seen.add(href);
    out.push({ title, href, kind });
  };
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.href || '';
    const blob = ((a.innerText || '') + ' ' + (a.getAttribute('aria-label') || '') + ' ' + href).replace(/\s+/g,' ').trim();
    const low = blob.toLowerCase();
    const isPdf = /\.pdf\b/i.test(href) || /\bpdf\b/i.test(low)
      || /drive\.google\.com\/file\//i.test(href)
      || /docs\.google\.com\/file\//i.test(href);
    const isMat = isPdf || /drive\.google\.com|docs\.google\.com|\/file\/d\//i.test(href);
    if (!isMat) return;
    if (wantPdf && !isPdf && !/file\/d\//i.test(href)) return;
    push(blob.slice(0, 160) || 'Material', href, isPdf ? 'pdf' : 'file');
  });
  // Also assignment / material cards on Classwork
  document.querySelectorAll('[data-stream-item-id], li, div[role="listitem"]').forEach(el => {
    const t = (el.innerText || '').replace(/\s+/g,' ').trim();
    if (!t || t.length > 300) return;
    const a = el.querySelector('a[href]') || (el.closest && el.closest('a'));
    if (!a || !a.href) return;
    const low = t.toLowerCase();
    if (q && !(low.includes(q) || q.split(/\s+/).filter(w => w.length>2).some(w => low.includes(w)))) {
      if (!/\bpdf\b|book|english/.test(low)) return;
    }
    push(t.slice(0, 160), a.href, /\bpdf\b|\.pdf\b/i.test(low + a.href) ? 'pdf' : 'item');
  });
  return out.slice(0, 30);
}
"""


def classroom_list_classes() -> list[dict]:
    page = _ensure_page(_CLASSROOM_HOME, "classroom.google.com")
    if isinstance(page, str):
        return []
    _activate_page(page)
    try:
        cur = _eval(page["webSocketDebuggerUrl"], "location.href") or ""
        if "/h" not in str(cur) and "/u/" in str(cur):
            _cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": _CLASSROOM_HOME})
            time.sleep(1.0)
        elif "classroom.google.com" not in str(cur):
            _cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": _CLASSROOM_HOME})
            time.sleep(1.0)
        else:
            # Refresh home for a clean class grid
            _cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": _CLASSROOM_HOME})
            time.sleep(0.9)
    except Exception:
        pass
    try:
        got = _eval(page["webSocketDebuggerUrl"], _CLASSROOM_LIST_CLASSES_JS) or []
        return got if isinstance(got, list) else []
    except Exception:
        return []


def _class_name_tokens(name: str) -> set[str]:
    """Tokens that mark a school year / grade cohort (e.g. g9s, 9s, 2025-2026)."""
    n = _fuzzy_norm(name)
    toks: set[str] = set()
    for m in re.finditer(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b", n):
        toks.add(f"{m.group(1)}-{m.group(2)}")
    for m in re.finditer(r"\bg?\s*([6-9]|1[0-2])\s*s?\b", n):
        toks.add(f"g{m.group(1)}s")
    for m in re.finditer(r"\b(20(?:24|25|26|27))\b", n):
        toks.add(m.group(1))
    return toks


def _is_obviously_old_class(name: str) -> bool:
    low = _fuzzy_norm(name)
    if re.search(r"\b(archived|archive|old|previous|last year)\b", low):
        return True
    # Explicit past school years (not current 2025-2026 / 2026)
    if re.search(r"\b(2019|2020|2021|2022|2023)\b", low):
        return True
    if re.search(r"\b2022\s*[-/]\s*2023\b|\b2023\s*[-/]\s*2024\b|\b2021\s*[-/]\s*2022\b|\b2024\s*[-/]\s*2025\b", low):
        return True
    # Legacy school codes that never match current naming
    if re.search(r"\b4ku\b", low):
        return True
    return False


def _split_current_old_classes(classes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep current-year classes; skip old ones with different naming."""
    if not classes:
        return [], []
    old: list[dict] = []
    candidates: list[dict] = []
    for c in classes:
        name = str(c.get("name") or "")
        if _is_obviously_old_class(name):
            oc = dict(c)
            oc["skip_reason"] = "old naming / archived year"
            old.append(oc)
        else:
            candidates.append(c)
    # Majority cohort token (e.g. most classes say g9s / 2025-2026)
    from collections import Counter
    token_counts: Counter[str] = Counter()
    for c in candidates:
        token_counts.update(_class_name_tokens(str(c.get("name") or "")))
    majority = None
    if token_counts:
        top, n = token_counts.most_common(1)[0]
        if n >= max(2, (len(candidates) + 1) // 2):
            majority = top
    current: list[dict] = []
    for c in candidates:
        name = str(c.get("name") or "")
        toks = _class_name_tokens(name)
        if majority and toks and majority not in toks:
            oc = dict(c)
            oc["skip_reason"] = f"different from current group ({majority})"
            old.append(oc)
            continue
        # Keep electives with no grade/year token — only skip when they clearly conflict.
        current.append(c)
    return current, old


def _difficulty_score(title: str) -> tuple[int, str]:
    """Higher = harder. Used with due-date urgency for priority order."""
    t = (title or "").lower()
    if re.search(r"\b(exam|test|midterm|final|presentation|essay|project|research|lab report)\b", t):
        return 90, "hard"
    if re.search(r"\b(quiz|assessment|workbook|chapter|assignment|homework|واجب)\b", t):
        return 60, "medium"
    if re.search(r"\b(worksheet|practice|warmup|exit ticket|short|reading)\b", t):
        return 30, "easy"
    return 45, "medium"


def _priority_sort_key(it: dict) -> tuple:
    """Most important first: overdue → soon due → harder → recent post."""
    from datetime import date as date_cls, timedelta

    today = date_cls.today()
    due = None
    if it.get("date"):
        try:
            due = date_cls.fromisoformat(str(it["date"]))
        except ValueError:
            due = None
    if due is None:
        # undated → treat as mid priority by posted age
        days_until = 14
    else:
        days_until = (due - today).days
    # urgency: overdue first (negative days), then nearer dues
    urgency = days_until if days_until >= 0 else -1000 + days_until
    diff, _ = _difficulty_score(str(it.get("title") or ""))
    posted_age = 99
    if it.get("posted_date"):
        try:
            posted_age = (today - date_cls.fromisoformat(str(it["posted_date"]))).days
        except ValueError:
            pass
    return (urgency, -diff, posted_age)


_CLASSROOM_CLASS_ITEMS_JS = r"""
(() => {
  const out = [];
  const seen = new Set();
  const push = (title, dueRaw, postedRaw, href, kind) => {
    title = (title || '').replace(/\s+/g, ' ').trim();
    if (!title || title.length < 2 || title.length > 180) return;
    const key = (title + '|' + (dueRaw||'') + '|' + (href||'')).toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push({
      title,
      due_raw: (dueRaw || '').replace(/\s+/g, ' ').trim() || null,
      posted_raw: (postedRaw || '').replace(/\s+/g, ' ').trim() || null,
      href: href || null,
      kind: kind || 'work',
    });
  };

  // Classwork / stream assignment cards
  document.querySelectorAll('a[href*="/a/"][href*="/details"], a[href*="/c/"][href*="/a/"]').forEach(a => {
    const href = a.href || '';
    let blob = ((a.innerText || a.getAttribute('aria-label') || '') + '').replace(/\s+/g, ' ').trim();
    if (!blob || blob.length < 3) return;
    blob = blob.replace(/^assignment\s*/i, '');
    const dueM = blob.match(/\bDue\s+[^·|]+/i)
      || blob.match(/\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?:,\s*\d{1,2}:\d{2}\s*(?:AM|PM))?/i);
    const postedM = blob.match(/\bPosted\s+(?:today|yesterday|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s*\d{4})?|\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)/i);
    let title = blob;
    const dueRaw = dueM ? dueM[0] : null;
    const postedRaw = postedM ? postedM[0] : null;
    if (dueRaw) title = blob.slice(0, blob.toLowerCase().indexOf(dueRaw.toLowerCase())).trim();
    else if (postedRaw) title = blob.slice(0, blob.toLowerCase().indexOf(postedRaw.toLowerCase())).trim();
    // Skip pure announcements if no assignment-ish words and no due
    const low = blob.toLowerCase();
    const looksWork = /\b(assignment|homework|quiz|exam|test|project|essay|worksheet|due|واجب)\b/.test(low)
      || !!dueRaw || /\/details/.test(href);
    if (!looksWork) return;
    push(title || blob.slice(0, 120), dueRaw, postedRaw, href, dueRaw ? 'due' : 'work');
  });

  // Fallback: list items / stream cards
  if (!out.length) {
    document.querySelectorAll('[data-stream-item-id], li, div[role="listitem"]').forEach(el => {
      const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
      if (!t || t.length > 400) return;
      const low = t.toLowerCase();
      if (!(low.includes('due') || low.includes('posted') || low.includes('assigned') || low.includes('homework'))) return;
      const a = el.querySelector('a[href]') || el.closest('a');
      const dueM = t.match(/\bDue\s+[^·|]+/i);
      const postedM = t.match(/\bPosted\s+[^·|]+/i);
      push(t.split(/\bDue\b|\bPosted\b/i)[0].trim().slice(0, 120), dueM && dueM[0], postedM && postedM[0], a && a.href, 'work');
    });
  }
  return out.slice(0, 40);
})()
"""


def _item_in_recap_window(posted_date: str | None, due_date: str | None, *, weeks: int = 2) -> bool:
    """Keep work posted this/last week, or due soon / overdue."""
    from datetime import date as date_cls, timedelta

    today = date_cls.today()
    oldest_post = today - timedelta(days=7 * weeks)
    if posted_date:
        try:
            p = date_cls.fromisoformat(posted_date)
            if oldest_post <= p <= today + timedelta(days=1):
                return True
        except ValueError:
            pass
    if due_date:
        try:
            d = date_cls.fromisoformat(due_date)
            # overdue within 3 weeks or due within 2 weeks
            if (today - timedelta(days=21)) <= d <= (today + timedelta(days=14)):
                return True
        except ValueError:
            pass
    return False


def classroom_recap_all_classes(args: dict | None = None, **kwargs) -> str:
    """Visit each current class; recap this/last week's to-dos. Skip old-named classes."""
    args = dict(args or {})
    weeks = int(args.get("weeks") or 2)
    weeks = max(1, min(weeks, 3))

    probe = classroom_account_probe()
    if not probe.get("ok") or not probe.get("signed_in"):
        return json.dumps({
            "ok": False,
            "error": probe.get("error") or "Classroom not signed in on Jarvis Chrome.",
            "probe": probe,
        })

    classes = classroom_list_classes()
    if not classes:
        return json.dumps({"ok": False, "error": "Couldn't list your Classroom classes."})

    current, old = _split_current_old_classes(classes)
    page = _find_page("classroom.google.com")
    if not page or not page.get("webSocketDebuggerUrl"):
        return json.dumps({"ok": False, "error": "Classroom tab not found."})
    ws = page["webSocketDebuggerUrl"]

    all_items: list[dict] = []
    per_class: list[dict] = []

    for cls in current[:16]:
        name = str(cls.get("name") or "Class")
        href = str(cls.get("href") or "")
        if not href:
            continue
        try:
            # Classwork tab when possible
            m = re.search(r"(https://classroom\.google\.com/[^?#]*?/c/[a-zA-Z0-9_-]+)", href)
            target = (m.group(1).rstrip("/") + "/t/all") if m else href
            _cdp_call(ws, "Page.navigate", {"url": target})
            time.sleep(1.15)
            try:
                _eval(ws, r"""
(() => {
  const tabs = Array.from(document.querySelectorAll('a, button, div[role="tab"]'));
  const hit = tabs.find(el => /classwork|العمل/i.test((el.innerText||el.getAttribute('aria-label')||'')));
  if (hit) hit.click();
  return !!hit;
})()
""")
                time.sleep(0.7)
            except Exception:
                pass
            raw_items = _eval(ws, _CLASSROOM_CLASS_ITEMS_JS) or []
        except Exception as e:
            per_class.append({"class_name": name, "ok": False, "error": str(e), "items": []})
            continue

        kept = []
        for it in (raw_items if isinstance(raw_items, list) else []):
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            due_raw = it.get("due_raw")
            posted_raw = it.get("posted_raw")
            if due_raw and re.search(r"(?i)^\s*posted\b", str(due_raw)):
                posted_raw = posted_raw or due_raw
                due_raw = None
            posted_date, posted_show = _parse_classroom_posted(posted_raw, title)
            due_date = _parse_classroom_due(due_raw)
            if not _item_in_recap_window(posted_date, due_date, weeks=weeks):
                continue
            diff_n, diff_label = _difficulty_score(title)
            row = {
                "title": title,
                "class_name": name,
                "due_raw": due_raw,
                "date": due_date,
                "posted_raw": posted_show or posted_raw,
                "posted_date": posted_date,
                "href": it.get("href"),
                "difficulty": diff_label,
                "difficulty_score": diff_n,
                "important": True,
                "kind": "due" if due_date else "undated",
                "source": "classroom_class",
            }
            kept.append(row)
            all_items.append(row)
        per_class.append({"class_name": name, "ok": True, "count": len(kept), "items": kept})

    all_items.sort(key=_priority_sort_key)

    # Rank for display
    for i, it in enumerate(all_items, 1):
        it["priority_rank"] = i
        urg = _priority_sort_key(it)[0]
        if urg < 0:
            it["urgency"] = "overdue"
        elif urg == 0:
            it["urgency"] = "due today"
        elif urg == 1:
            it["urgency"] = "due tomorrow"
        elif urg <= 7:
            it["urgency"] = "due this week"
        else:
            it["urgency"] = "later / recent post"

    try:
        _cdp_call(ws, "Page.navigate", {"url": _CLASSROOM_HOME})
    except Exception:
        pass

    return json.dumps({
        "ok": True,
        "mode": "all_classes",
        "submitted": False,
        "weeks": weeks,
        "classes_current": [c.get("name") for c in current],
        "classes_skipped_old": [
            {"name": c.get("name"), "reason": c.get("skip_reason")} for c in old
        ],
        "per_class": per_class,
        "dues": all_items,
        "found": len(all_items),
        "message": (
            f"Recap of {len(current)} current class(es); skipped {len(old)} old. "
            f"{len(all_items)} to-do item(s) from this/last week, ordered most→least important."
        ),
    })


def classroom_open_class(args: dict, **kwargs) -> str:
    """Open the Classroom class that best matches the name (fuzzy, case-insensitive)."""
    query = (args.get("class_name") or args.get("query") or args.get("name") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "class_name is required"})
    probe = classroom_account_probe()
    if not probe.get("signed_in"):
        return json.dumps({"ok": False, "error": probe.get("error") or "Classroom not signed in."})
    classes = classroom_list_classes()
    if not classes:
        return json.dumps({"ok": False, "error": "Couldn't list your Classroom classes.", "classes": []})
    match = _fuzzy_best(query, classes, key="name", min_score=50.0)
    if not match:
        names = [c.get("name") for c in classes[:12]]
        return json.dumps({
            "ok": False,
            "error": f"No class close to '{query}'.",
            "classes": names,
        })
    page = _find_page("classroom.google.com") or _ensure_page(match["href"], "classroom.google.com")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})
    try:
        _cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": match["href"]})
        time.sleep(1.0)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Could not open class: {e}"})
    return json.dumps({
        "ok": True,
        "action": "classroom_open_class",
        "query": query,
        "class_name": match.get("name"),
        "url": match.get("href"),
        "score": match.get("_match_score"),
        "message": f"Opened {match.get('name')}",
    })


def classroom_find_material(args: dict, **kwargs) -> str:
    """Open a fuzzy-matched class and open the best PDF/material match. Tell user if missing."""
    class_q = (args.get("class_name") or args.get("class") or "").strip()
    material_q = (
        args.get("material") or args.get("query") or args.get("pdf") or args.get("title") or ""
    ).strip()
    if not material_q and not class_q:
        return json.dumps({"ok": False, "error": "Need a class and/or material name."})
    if not material_q:
        material_q = "pdf"

    opened = None
    if class_q:
        raw = classroom_open_class({"class_name": class_q})
        try:
            opened = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            opened = {"ok": False, "error": str(raw)[:200]}
        if not opened.get("ok"):
            return json.dumps(opened)

    page = _find_page("classroom.google.com")
    if not page or not page.get("webSocketDebuggerUrl"):
        return json.dumps({"ok": False, "error": "Classroom tab not found."})
    ws = page["webSocketDebuggerUrl"]
    # Prefer Classwork tab for materials/PDFs
    try:
        cur = str(_eval(ws, "location.href") or "")
        # /c/CLASS_ID → try classwork
        m = re.search(r"(https://classroom\.google\.com/[^?#]*?/c/[a-zA-Z0-9_-]+)", cur)
        if m:
            base_c = m.group(1).rstrip("/")
            if "/t/" not in cur and "classwork" not in cur.lower():
                _cdp_call(ws, "Page.navigate", {"url": base_c + "/t/all"})
                time.sleep(1.1)
    except Exception:
        pass

    try:
        # Click Classwork if visible
        _eval(ws, r"""
(() => {
  const tabs = Array.from(document.querySelectorAll('a, button, div[role="tab"]'));
  const hit = tabs.find(el => /classwork|العمل/i.test((el.innerText||el.getAttribute('aria-label')||'')));
  if (hit) hit.click();
  return !!hit;
})()
""")
        time.sleep(0.8)
    except Exception:
        pass

    try:
        items = _eval(ws, f"({_CLASSROOM_FIND_MATERIAL_JS})({json.dumps(material_q)})") or []
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Could not scan class materials: {e}", "opened_class": opened})

    if not isinstance(items, list) or not items:
        return json.dumps({
            "ok": False,
            "error": f"Couldn't find '{material_q}'"
            + (f" in {opened.get('class_name')}" if opened else "")
            + ".",
            "opened_class": opened,
        })

    # Score by material query
    scored = []
    for it in items:
        title = str(it.get("title") or "")
        kind_bonus = 15.0 if it.get("kind") == "pdf" and re.search(r"pdf|book", material_q, re.I) else 0.0
        scored.append({
            **it,
            "score": _fuzzy_score(material_q, title) + kind_bonus,
        })
    scored.sort(key=lambda x: -float(x["score"]))
    pick = scored[0]
    if float(pick["score"]) < 30.0:
        return json.dumps({
            "ok": False,
            "error": f"Couldn't find '{material_q}'"
            + (f" in {opened.get('class_name')}" if opened else "")
            + ".",
            "candidates": [{"title": s.get("title"), "score": s.get("score")} for s in scored[:5]],
            "opened_class": opened,
        })

    href = str(pick.get("href") or "")
    preview = _drive_preview_url(href) or href
    try:
        _cdp_call(ws, "Page.navigate", {"url": preview})
        time.sleep(0.7)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Found it but couldn't open: {e}", "picked": pick})

    return json.dumps({
        "ok": True,
        "action": "classroom_find_material",
        "class_name": (opened or {}).get("class_name"),
        "material": pick.get("title"),
        "kind": pick.get("kind"),
        "url": preview,
        "score": pick.get("score"),
        "message": f"Opened {(opened or {}).get('class_name') or 'class'} → {pick.get('title')}",
    })


def classroom_check(args: dict | None = None, **kwargs) -> str:
    """Read Classroom classes and due work. Never submits or clicks Turn in.

    mode everything / todo: To-do list only.
    mode all_classes: visit each current class for this/last week recap.
    mode solve: also open a few assignment pages and extract questions (read-only).
    import_to_calendar: only if explicitly true.
    """
    args = dict(args or {})
    mode = str(args.get("mode") or "everything").lower()
    if mode in ("all_classes", "classes", "recap", "each_class"):
        return classroom_recap_all_classes(args)
    if mode in ("todo", "to-do", "to_do"):
        mode = "everything"
    import_to_cal = bool(args.get("import_to_calendar"))
    max_open = int(args.get("max_assignments") or 4)
    max_open = max(0, min(max_open, 5))

    probe = classroom_account_probe()
    if not probe.get("ok"):
        return json.dumps(probe)
    if not probe.get("signed_in"):
        return json.dumps({
            "ok": False,
            "signed_in": False,
            "needs_signin": True,
            "error": (
                "Google Classroom is not signed in on the Jarvis Chrome window I just opened. "
                "Sign in once with your .edu account in that window (I will not type your password), then ask again. "
                "I will never submit work."
            ),
            "probe": probe,
        })
    if probe.get("blocked"):
        return json.dumps({
            "ok": False,
            "signed_in": True,
            "blocked": True,
            "error": "This Google account does not allow Google Classroom. I will not try to read assignments.",
            "probe": probe,
        })

    # Pull dues without importing unless asked
    raw = classroom_pull_dues({"import_to_calendar": import_to_cal})
    try:
        dues = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        dues = {"ok": False, "error": str(raw)[:300]}

    classes: list[str] = []
    questions: list[dict] = []
    page = _find_page("classroom.google.com")
    if page and page.get("webSocketDebuggerUrl") and mode in ("everything", "solve", "questions"):
        try:
            class_js = r"""
(() => {
  const names = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/c/"]').forEach(a => {
    let t = (a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim();
    t = t.replace(/^([A-Za-z0-9])\s+(?=\1)/, '');
    if (!t || t.length > 80 || seen.has(t.toLowerCase())) return;
    if (/to-do|calendar|settings|archived/i.test(t)) return;
    seen.add(t.toLowerCase());
    names.push(t);
  });
  return names.slice(0, 24);
})()
"""
            got = _eval(page["webSocketDebuggerUrl"], class_js) or []
            if isinstance(got, list):
                classes = [str(x) for x in got if x][:24]
        except Exception:
            pass

    if mode == "solve" and page and page.get("webSocketDebuggerUrl"):
        picked = []
        for it in dues.get("items") or []:
            href = it.get("href")
            if not href or "/a/" not in str(href) or not it.get("important"):
                continue
            picked.append(it)
        picked.sort(key=lambda it: (-(int(it.get("importance") or 0)), 0 if it.get("date") else 1))
        hrefs = [it["href"] for it in picked[:max_open]]
        # no hrefs: don't invent clicks on submit
        for href in hrefs[:max_open]:
            try:
                questions.append(_read_assignment_readonly(page["webSocketDebuggerUrl"], href))
            except Exception as exc:
                questions.append({"url": href, "error": str(exc), "submitted": False})
        try:
            _cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": _CLASSROOM_TODO_URL})
        except Exception:
            pass

    return json.dumps({
        "ok": True,
        "mode": mode,
        "signed_in": True,
        "submitted": False,
        "probe": {k: probe.get(k) for k in ("edu_email", "url", "note")},
        "classes": classes,
        "dues": dues.get("items") or [],
        "found": dues.get("found"),
        "imported": dues.get("imported") if import_to_cal else None,
        "questions": questions,
        "message": "Read-only Classroom check. Nothing was submitted.",
    })


def _quit_jarvis_chrome() -> dict[str, Any]:
    """Quit only the Chrome window Jarvis started. Never the user's own Chrome."""
    try:
        _, body = base._cdp_get("/json/version")
        info = json.loads(body) if body else {}
        ws = (info or {}).get("webSocketDebuggerUrl")
        if ws:
            try:
                _cdp_call(ws, "Browser.close", {}, timeout=4.0)
            except Exception:
                # Chrome often drops the socket as it exits. That still counts.
                pass
            time.sleep(0.6)
            if not base._cdp_alive():
                return {"ok": True, "method": "browser.close"}
    except Exception:
        pass

    killed = _kill_debug_chrome_processes()
    time.sleep(0.4)
    if not base._cdp_alive():
        return {"ok": True, "method": "process" if killed else "already_closed", "killed": killed}
    return {"ok": False, "error": "The Chrome window I opened stayed open.", "killed": killed}


def _kill_debug_chrome_processes() -> int:
    """Kill only the debug Chrome profile Jarvis uses, including its child processes."""
    if os.name != "nt":
        return 0
    import subprocess

    marker = str(base.DEBUG_PROFILE)
    ps = (
        "$marker = $env:JARVIS_CHROME_MARKER; "
        "$roots = @(Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -like ('*' + $marker + '*') }); "
        "$n = 0; "
        "foreach ($p in $roots) { "
        "  & taskkill /PID $p.ProcessId /T /F 2>$null | Out-Null; "
        "  $n++ "
        "}; "
        "Write-Output $n"
    )
    try:
        env = os.environ.copy()
        env["JARVIS_CHROME_MARKER"] = marker
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            env=env,
        )
        text = (out.stdout or "").strip().splitlines()
        return int(text[-1]) if text and text[-1].strip().isdigit() else 0
    except Exception:
        return 0


def close_jarvis_tabs(args: dict, **kwargs) -> str:
    """Close tabs Jarvis opened. Close-all also quits the Chrome window Jarvis started."""
    from . import tab_registry

    # Do not launch Chrome just to close it.
    if not base._cdp_alive():
        tab_registry.clear_registry()
        return json.dumps({
            "ok": True,
            "closed_count": 0,
            "chrome_closed": True,
            "message": "The Chrome window I opened is already closed. Your own Chrome was not touched.",
        })

    live = _pages()
    tab_registry.reconcile_with_live(live)

    target_ids = args.get("target_ids")
    if target_ids is not None and not isinstance(target_ids, list):
        target_ids = [target_ids]

    # Accept common agent arg shapes
    close_all = args.get("close_all")
    if close_all is None:
        close_all = bool(args.get("all"))
    site = (args.get("site") or args.get("app") or args.get("filter") or "").strip().lower() or None
    site_norm = site or ""
    quit_window = not target_ids and (
        bool(close_all)
        or not site_norm
        or site_norm in ("chrome", "all", "any", "browser")
    )

    result = tab_registry.close_tabs(
        close_all=bool(close_all),
        site=site,
        target_ids=target_ids,
        live_pages_list=live,
    )
    if quit_window:
        quit_info = _quit_jarvis_chrome()
        result["chrome_closed"] = bool(quit_info.get("ok"))
        if quit_info.get("ok"):
            tab_registry.clear_registry()
            result["ok"] = True
            result["message"] = (
                f"Closed {result.get('closed_count') or 0} tab(s) I opened and quit the Chrome window I started. "
                "Your own Chrome was not closed."
            )
        else:
            result["chrome_error"] = quit_info.get("error")
            result["message"] = (
                f"Closed {result.get('closed_count') or 0} tab(s) I opened, but the Chrome window stayed open. "
                "Your own Chrome was not closed."
            )
    return json.dumps(result)
