"""Read whatever the user currently has open in debug Chrome (Classroom, YouTube, etc.)."""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import browser_actions as ba
from . import tab_registry
from . import tools as base

SHOT_DIR = Path(os.environ.get("JARVIS_SCREENSHOT_DIR", r"D:\jarvis_kokoro\screenshots"))
MAX_TEXT = 14000

_SITE_NEEDLES = {
    "youtube": ("youtube.com", "youtu.be"),
    "classroom": ("classroom.google.com",),
    "whatsapp": ("web.whatsapp.com", "whatsapp"),
    "chatgpt": ("chatgpt.com", "chat.openai.com"),
    "vidbox": ("vidbox.cc", "vidbox.vc", "vidbox.to"),
    "movies": ("vidbox.cc", "vidbox.vc", "vidbox.to"),
    "notebooklm": ("notebooklm.google.com", "notebooklm"),
    "gmail": ("mail.google.com", "inbox"),
    "google": ("google.com",),
}

_READ_PAGE_JS = r"""
(() => {
  const maxLen = %d;
  const url = location.href;
  const title = document.title || '';
  const root = document.querySelector('main')
    || document.querySelector('[role="main"]')
    || document.querySelector('#content')
    || document.body;
  let text = (root && (root.innerText || root.textContent) || '')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const truncated = text.length > maxLen;
  if (truncated) text = text.slice(0, maxLen);
  return {
    url,
    title,
    text,
    truncated,
    text_length: text.length,
    focused: !!document.hasFocus(),
  };
})()
"""

_YOUTUBE_INFO_JS = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const out = {
    is_watch: /youtube\.com\/watch/i.test(location.href) || /youtu\.be\//i.test(location.href),
    video_id: null,
    title: null,
    channel: null,
    description: null,
    transcript: null,
    transcript_note: null,
  };
  try {
    const u = new URL(location.href);
    out.video_id = u.searchParams.get('v');
  } catch (e) {}

  const titleEl = document.querySelector('h1.ytd-watch-metadata yt-formatted-string')
    || document.querySelector('h1 yt-formatted-string')
    || document.querySelector('h1.title')
    || document.querySelector('h1');
  out.title = (titleEl && (titleEl.textContent || '')).trim() || document.title || null;

  const ch = document.querySelector('#channel-name a')
    || document.querySelector('ytd-channel-name a')
    || document.querySelector('#owner #text a');
  out.channel = (ch && (ch.textContent || '')).trim() || null;

  // Expand description if collapsed
  const more = document.querySelector('#expand')
    || document.querySelector('tp-yt-paper-button#expand')
    || document.querySelector('#description-inline-expander #expand');
  if (more) { try { more.click(); await sleep(400); } catch (e) {} }

  const desc = document.querySelector('#description-inline-expander')
    || document.querySelector('#description')
    || document.querySelector('ytd-text-inline-expander');
  if (desc) {
    out.description = (desc.innerText || '').replace(/\s+\n/g, '\n').trim().slice(0, 4000);
  }

  // Try captionTracks from ytInitialPlayerResponse embedded in page
  let captionUrl = null;
  try {
    const html = document.documentElement.innerHTML;
    const m = html.match(/"captionTracks":\s*(\[.*?\])/);
    if (m) {
      const tracks = JSON.parse(m[1]);
      const en = tracks.find(t => (t.languageCode || '').startsWith('en')) || tracks[0];
      if (en && en.baseUrl) captionUrl = en.baseUrl;
    }
  } catch (e) {}

  if (captionUrl) {
    try {
      const resp = await fetch(captionUrl);
      const xml = await resp.text();
      const texts = [...xml.matchAll(/<text[^>]*>([\s\S]*?)<\/text>/g)].map(x => {
        let s = x[1].replace(/<[^>]+>/g, ' ');
        s = s.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'");
        return s.replace(/\s+/g, ' ').trim();
      }).filter(Boolean);
      const joined = texts.join(' ').replace(/\s+/g, ' ').trim();
      out.transcript = joined.slice(0, 12000);
      out.transcript_note = texts.length
        ? ('Extracted ' + texts.length + ' caption segments from YouTube timedtext.')
        : 'Caption track empty.';
    } catch (e) {
      out.transcript_note = 'Caption fetch failed: ' + String(e);
    }
  }

  // Fallback: open transcript panel in UI
  if (!out.transcript) {
    try {
      const buttons = Array.from(document.querySelectorAll('button, yt-button-shape button'));
      const eng = buttons.find(b => /show transcript|transcript/i.test((b.getAttribute('aria-label')||'') + ' ' + (b.textContent||'')));
      if (eng) {
        eng.click();
        await sleep(900);
      } else {
        // menu under description "..." 
        const menuBtn = document.querySelector('ytd-video-description-transcript-section-renderer button')
          || document.querySelector('#primary-button button')
          || Array.from(document.querySelectorAll('button')).find(b => /transcript/i.test(b.textContent||''));
        if (menuBtn) { menuBtn.click(); await sleep(900); }
      }
      const panel = document.querySelector('ytd-transcript-segment-list-renderer')
        || document.querySelector('#segments-container')
        || document.querySelector('ytd-transcript-renderer');
      if (panel) {
        const segs = Array.from(panel.querySelectorAll('yt-formatted-string, .segment-text, ytd-transcript-segment-renderer'))
          .map(el => (el.innerText || el.textContent || '').trim())
          .filter(s => s && s.length > 1);
        const joined = segs.join(' ').replace(/\s+/g, ' ').trim();
        if (joined.length > 40) {
          out.transcript = joined.slice(0, 12000);
          out.transcript_note = 'Scraped from YouTube transcript panel.';
        }
      }
    } catch (e) {
      out.transcript_note = (out.transcript_note || '') + ' UI transcript failed: ' + String(e);
    }
  }

  if (!out.transcript) {
    out.transcript_note = out.transcript_note || 'No captions/transcript available for this video.';
  }
  return out;
})()
"""


def _http_pages() -> list[dict]:
    pages = []
    for p in ba._pages():
        if (p.get("type") or "page") not in ("page", "iframe"):
            # skip workers; keep page
            pass
        if p.get("type") and p.get("type") != "page":
            continue
        url = p.get("url") or ""
        if not url.startswith(("http://", "https://")):
            continue
        if not p.get("webSocketDebuggerUrl"):
            continue
        pages.append(p)
    return pages


def _site_from_url(url: str) -> str:
    u = (url or "").lower()
    if "classroom.google.com" in u:
        return "classroom"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "whatsapp" in u:
        return "whatsapp"
    if "chatgpt.com" in u or "chat.openai.com" in u:
        return "chatgpt"
    if "vidbox." in u:
        return "vidbox"
    return "web"


def _pick_page(site: str | None) -> dict | str:
    err = base._ensure_cdp()
    if err:
        return err
    pages = _http_pages()
    if not pages:
        return "No open http(s) tabs in debug Chrome. Open Classroom/YouTube (or ask Jarvis to open them), then try again."

    site = (site or "active").strip().lower()
    aliases = {
        "yt": "youtube",
        "google classroom": "classroom",
        "gc": "classroom",
        "movies": "vidbox",
        "movie": "vidbox",
        "notebook": "notebooklm",
        "notebook lm": "notebooklm",
        "mail": "gmail",
        "email": "gmail",
        "current": "active",
        "this": "active",
        "focused": "active",
        "tab": "active",
    }
    site = aliases.get(site, site)

    if site in _SITE_NEEDLES:
        needles = _SITE_NEEDLES[site]
        for p in pages:
            blob = f"{p.get('url','')} {p.get('title','')}".lower()
            if any(n in blob for n in needles):
                return p
        return f"No open tab matching '{site}'. Open it in debug Chrome first (or ask Jarvis to open it)."

    # active: prefer document.hasFocus()
    for p in pages:
        try:
            if ba._eval(p["webSocketDebuggerUrl"], "document.hasFocus()"):
                return p
        except Exception:
            continue

    # Prefer watch pages / classroom assignment pages over blank google home
    ranked = sorted(
        pages,
        key=lambda p: (
            0 if "watch" in (p.get("url") or "") else 1,
            0 if "classroom.google.com" in (p.get("url") or "") else 1,
            0 if "youtube.com" in (p.get("url") or "") else 1,
            len(p.get("title") or ""),
        ),
    )
    return ranked[0]


def _screenshot(ws: str) -> str | None:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"look_{int(time.time())}.png"
    try:
        try:
            ba._cdp_call(ws, "Page.enable", {}, timeout=5.0)
        except Exception:
            pass
        result = ba._cdp_call(
            ws,
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
            timeout=15.0,
        )
        data = (result or {}).get("data")
        if not data:
            return None
        path.write_bytes(base64.b64decode(data))
        return str(path)
    except Exception:
        return None


def list_browser_tabs(args: dict, **kwargs) -> str:
    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})
    live = ba._pages()
    tab_registry.reconcile_with_live(live)
    jarvis_ids = tab_registry.jarvis_target_ids()
    tabs = []
    for p in _http_pages():
        focused = False
        try:
            focused = bool(ba._eval(p["webSocketDebuggerUrl"], "document.hasFocus()"))
        except Exception:
            pass
        tid = p.get("id")
        tabs.append({
            "target_id": tid,
            "title": (p.get("title") or "")[:120],
            "url": p.get("url"),
            "site": _site_from_url(p.get("url") or ""),
            "focused": focused,
            "jarvis_opened": bool(tid and tid in jarvis_ids),
        })
    jarvis_only = tab_registry.list_jarvis_tabs(live)
    return json.dumps({
        "ok": True,
        "count": len(tabs),
        "tabs": tabs,
        "jarvis_open_count": len(jarvis_only),
        "jarvis_tabs": jarvis_only,
        "note": (
            "jarvis_opened=true means Jarvis opened that tab and close_jarvis_tabs may close it. "
            "User-opened tabs are never closed by Jarvis."
        ),
    })


def look_at_browser(args: dict, **kwargs) -> str:
    """Read the open PC Chrome tab the user is looking at (no third-party OAuth)."""
    site = (args.get("site") or args.get("app") or "active")
    want_shot = args.get("screenshot")
    if want_shot is None:
        want_shot = True
    want_shot = bool(want_shot)
    max_chars = int(args.get("max_chars") or MAX_TEXT)
    max_chars = max(2000, min(max_chars, 24000))

    page = _pick_page(str(site) if site else "active")
    if isinstance(page, str):
        return json.dumps({"ok": False, "error": page})

    ws = page["webSocketDebuggerUrl"]
    ba._activate_page(page)
    time.sleep(0.35)

    try:
        info = ba._eval(ws, _READ_PAGE_JS % max_chars) or {}
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Could not read page: {e}"})

    url = info.get("url") or page.get("url") or ""
    detected = _site_from_url(url)
    extras: dict[str, Any] = {}

    if detected == "youtube":
        try:
            extras["youtube"] = ba._eval(ws, _YOUTUBE_INFO_JS) or {}
        except Exception as e:
            extras["youtube_error"] = str(e)

    shot_path = _screenshot(ws) if want_shot else None

    how_to = (
        "Use visible_text (and youtube.transcript when present) to help the user. "
        "For diagrams, worksheets, or on-screen questions that are hard to read as text, "
        "call vision_analyze with image_url set to screenshot_path (local file path). "
        "Do not navigate away from the user's page unless they ask."
    )
    if detected == "youtube" and not (extras.get("youtube") or {}).get("transcript"):
        how_to += (
            " No transcript found — explain from title/description, or use vision_analyze "
            "on screenshot_path for the current video frame (limited). Ask the user to turn on captions if needed."
        )
    if detected == "classroom":
        how_to += (
            " This is Classroom content the user opened. Help them understand and work through "
            "questions using the page text/screenshot; follow their preference (hints vs full answers)."
        )

    out = {
        "ok": True,
        "action": "look_at_browser",
        "site": detected,
        "url": url,
        "title": info.get("title") or page.get("title"),
        "visible_text": info.get("text") or "",
        "text_truncated": bool(info.get("truncated")),
        "screenshot_path": shot_path,
        "extras": extras,
        "how_to_help": how_to,
    }
    return json.dumps(out)
