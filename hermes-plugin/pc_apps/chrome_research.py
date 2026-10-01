"""Google search + user-controlled research tab opening in debug Chrome."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Any

from . import browser_actions as ba
from . import tools as base

MAX_RESEARCH_TABS = 5

_GOOGLE_SEARCH_JS = r"""
(async (query) => {
  const q = String(query || '').trim();
  if (!q) return {ok:false, error:'query is required'};
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  let input = document.querySelector('textarea[name="q"]')
    || document.querySelector('input[name="q"]')
    || document.querySelector('input[title="Search"]')
    || document.querySelector('input[aria-label="Search"]')
    || document.querySelector('input[type="search"]');

  if (!input && !/google\./i.test(location.hostname)) {
    location.href = 'https://www.google.com/';
    await sleep(1800);
    input = document.querySelector('textarea[name="q"]')
      || document.querySelector('input[name="q"]');
  }

  if (!input) return {ok:false, error:'Google search box not found'};

  input.focus();
  input.value = '';
  input.dispatchEvent(new Event('input', {bubbles:true}));
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  if (setter) setter.call(input, q); else input.value = q;
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.dispatchEvent(new Event('change', {bubbles:true}));
  await sleep(150);

  const form = input.closest('form');
  if (form && form.requestSubmit) form.requestSubmit();
  else {
    input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, bubbles:true}));
    input.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, bubbles:true}));
  }
  await sleep(400);
  return {ok:true, query:q, url: location.href};
})(%s)
"""

_TYPE_IN_PAGE_JS = r"""
(async (text, submit) => {
  const t = String(text || '');
  const doSubmit = !!submit;
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  let el = document.activeElement;
  const isEditable = (node) => node && (
    node.tagName === 'INPUT' || node.tagName === 'TEXTAREA'
    || node.isContentEditable
  );
  if (!isEditable(el)) {
    el = document.querySelector('textarea[name="q"]')
      || document.querySelector('input[name="q"]')
      || document.querySelector('input[type="search"]')
      || document.querySelector('textarea:not([disabled])')
      || document.querySelector('input[type="text"]:not([disabled])')
      || document.querySelector('[contenteditable="true"]');
  }
  if (!el) return {ok:false, error:'No editable field found on this page'};

  el.focus();
  if (el.isContentEditable) {
    el.textContent = t;
    el.dispatchEvent(new InputEvent('input', {bubbles:true, data:t, inputType:'insertText'}));
  } else {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    if (setter) setter.call(el, t); else el.value = t;
    el.dispatchEvent(new Event('input', {bubbles:true}));
    el.dispatchEvent(new Event('change', {bubbles:true}));
  }
  await sleep(120);
  if (doSubmit) {
    const form = el.closest('form');
    if (form && form.requestSubmit) form.requestSubmit();
    else el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, bubbles:true}));
  }
  return {ok:true, typed:t.slice(0,120), submitted:doSubmit, tag: el.tagName};
})(%s, %s)
"""


def _active_page() -> dict | str:
    err = base._ensure_cdp()
    if err:
        return err
    pages = [
        p for p in ba._pages()
        if (p.get("type") or "page") == "page"
        and (p.get("url") or "").startswith(("http://", "https://"))
        and p.get("webSocketDebuggerUrl")
    ]
    if not pages:
        opened = base._open_url_in_chrome("https://www.google.com/", source="active_page_fallback")
        if not opened.get("ok"):
            return opened.get("error") or "Could not open Chrome"
        time.sleep(2.0)
        pages = [
            p for p in ba._pages()
            if (p.get("type") or "page") == "page" and p.get("webSocketDebuggerUrl")
        ]
    for p in pages:
        try:
            if ba._eval(p["webSocketDebuggerUrl"], "document.hasFocus()"):
                return p
        except Exception:
            continue
    return pages[0]


def _valid_https_url(url: str) -> bool:
    u = (url or "").strip()
    if not u.startswith("https://"):
        return False
    if len(u) > 2048:
        return False
    # block javascript/data etc.
    if re.match(r"^https://[^\s/]+", u) is None:
        return False
    return True


def chrome_google_search(args: dict, **kwargs) -> str:
    """Type a query into Google search in the current tab (does not open extra tabs).

    Prefer web_find for chat-only research. This tool is for when the user wants
    the search visible on their PC Chrome.
    """
    query = (args.get("query") or args.get("q") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    # Soft gate: refuse unless explicitly marked as on-screen PC search
    on_screen = args.get("on_user_screen")
    if on_screen is not True and not args.get("user_wants_visible_chrome_search"):
        return json.dumps({
            "ok": False,
            "error": (
                "Refused: chrome_google_search opens/uses the user's PC Chrome. "
                "For 'find me / look up / research / list' requests call web_find instead "
                "and answer in chat. Only retry chrome_google_search with on_user_screen=true "
                "when the user explicitly asks to search on their PC / in Chrome."
            ),
            "hint": "Use tool web_find",
        })

    page = ba._ensure_page("https://www.google.com/", "google")
    if isinstance(page, str):
        page = _active_page()
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})

    ba._activate_page(page)
    time.sleep(0.6)
    try:
        result = ba._eval(page["webSocketDebuggerUrl"], _GOOGLE_SEARCH_JS % json.dumps(query))
        return json.dumps({
            "ok": True,
            "action": "chrome_google_search",
            "query": query,
            "result": result,
            "note": "Searched in the current tab only — no extra tabs opened.",
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Google search failed: {e}"})


def chrome_type_in_page(args: dict, **kwargs) -> str:
    """Type text into the active page field (search box, input, etc.). Does not open tabs."""
    text = (args.get("text") or args.get("query") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "text is required"})
    submit = bool(args.get("submit", False))

    page = _active_page()
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})

    ba._activate_page(page)
    time.sleep(0.4)
    try:
        expr = _TYPE_IN_PAGE_JS % (json.dumps(text), "true" if submit else "false")
        result = ba._eval(page["webSocketDebuggerUrl"], expr)
        return json.dumps({
            "ok": True,
            "action": "chrome_type_in_page",
            "result": result,
            "note": "Typed in the active tab only — did not open new tabs.",
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Typing failed: {e}"})


def chrome_navigate_active_tab(args: dict, **kwargs) -> str:
    """Navigate the current tab to a URL without opening a new tab."""
    if args.get("on_user_screen") is not True:
        return json.dumps({
            "ok": False,
            "error": (
                "Refused: chrome_navigate_active_tab changes the user's PC Chrome. "
                "For find/research use web_find or web_search and answer in chat. "
                "Retry with on_user_screen=true only if they asked to open/go to a page on their PC."
            ),
        })
    url = (args.get("url") or "").strip()
    if not _valid_https_url(url):
        return json.dumps({"ok": False, "error": "url must be a valid https:// URL"})

    page = _active_page()
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})

    ws = page["webSocketDebuggerUrl"]
    ba._activate_page(page)
    try:
        ba._cdp_call(ws, "Page.navigate", {"url": url}, timeout=15.0)
        time.sleep(1.2)
        cur = ba._eval(ws, "location.href") or url
        return json.dumps({
            "ok": True,
            "action": "chrome_navigate_active_tab",
            "url": cur,
            "note": "Navigated the active tab only — no new tab opened.",
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Navigation failed: {e}"})


def _user_asked_to_open_on_pc(quote: str) -> bool:
    q = (quote or "").lower()
    if not q.strip():
        return False
    if re.search(r"\bopen\b.{0,50}\b(tab|tabs|chrome|browser|google|link|links|page|pages)\b", q):
        return True
    if re.search(r"\b(show|open)\b.{0,40}\b(on my (pc|screen|computer)|in chrome|in (the )?browser)\b", q):
        return True
    if re.search(r"\bsearch\b.{0,30}\b(on my (pc|screen)|in chrome|on (the )?pc)\b", q):
        return True
    return False


def chrome_open_research_tabs(args: dict, **kwargs) -> str:
    """Open research tabs ONLY when the user explicitly asked, with an exact tab count."""
    explicit = args.get("user_explicitly_asked_to_open_tabs")
    quote = (args.get("user_quote_asking_to_open") or args.get("user_quote") or "").strip()
    if explicit is not True or not _user_asked_to_open_on_pc(quote):
        return json.dumps({
            "ok": False,
            "error": (
                "Refused: opening Chrome tabs is blocked for find/research chat requests. "
                "Use web_find or web_search and answer in chat. "
                "Only call this when the user clearly said to open tab(s)/Chrome on their PC, "
                "with user_explicitly_asked_to_open_tabs=true AND user_quote_asking_to_open "
                "set to their exact words (must include open+tab/chrome/on my PC)."
            ),
        })

    try:
        tab_count = int(args.get("tab_count") or 0)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "tab_count must be an integer"})

    if tab_count < 1 or tab_count > MAX_RESEARCH_TABS:
        return json.dumps({
            "ok": False,
            "error": f"tab_count must be between 1 and {MAX_RESEARCH_TABS}",
        })

    topic = (args.get("research_topic") or args.get("topic") or "").strip()
    urls = args.get("urls") or args.get("tabs") or []

    # Allow model to pass topic only for single-tab google overview
    if not urls and topic and tab_count == 1:
        q = urllib.parse.quote_plus(topic)
        urls = [f"https://www.google.com/search?q={q}"]

    if not isinstance(urls, list) or not urls:
        return json.dumps({
            "ok": False,
            "error": "Provide urls (https list) matching tab_count, or topic with tab_count=1.",
        })

    if len(urls) != tab_count:
        return json.dumps({
            "ok": False,
            "error": (
                f"Refused: user asked for {tab_count} tab(s) but {len(urls)} URL(s) were provided. "
                "The urls list length MUST exactly match tab_count — no more, no less."
            ),
        })

    cleaned: list[str] = []
    for u in urls:
        s = str(u).strip()
        if not _valid_https_url(s):
            return json.dumps({"ok": False, "error": f"Invalid https URL: {s[:120]}"})
        cleaned.append(s)

    gate = base._ensure_cdp()
    if gate:
        return json.dumps({"ok": False, "error": gate})

    opened: list[dict[str, Any]] = []
    for i, url in enumerate(cleaned):
        if i == 0:
            # First URL: can navigate active tab if it's blank/google, else new tab
            page = _active_page()
            if isinstance(page, str):
                res = base._open_url_in_chrome(url, source="chrome_open_research_tabs")
            else:
                cur = ""
                try:
                    cur = str(ba._eval(page["webSocketDebuggerUrl"], "location.href") or "")
                except Exception:
                    pass
                if cur in ("", "about:blank") or "google.com" in cur:
                    try:
                        ba._cdp_call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": url})
                        res = {"ok": True, "action": "navigated_active", "url": url}
                    except Exception:
                        res = base._open_url_in_chrome(url, source="chrome_open_research_tabs")
                else:
                    res = base._open_url_in_chrome(url, source="chrome_open_research_tabs")
        else:
            res = base._open_url_in_chrome(url, source="chrome_open_research_tabs")

        opened.append({"index": i + 1, "url": url, **res})
        if i < len(cleaned) - 1:
            time.sleep(0.35)

    base._focus_chrome_window()
    ok_count = sum(1 for o in opened if o.get("ok"))
    return json.dumps({
        "ok": ok_count == tab_count,
        "action": "chrome_open_research_tabs",
        "research_topic": topic or None,
        "tab_count": tab_count,
        "opened": opened,
        "message": (
            f"Opened {ok_count}/{tab_count} research tab(s) as the user requested. "
            "Use look_at_browser to read a tab and summarize for them."
        ),
    })
