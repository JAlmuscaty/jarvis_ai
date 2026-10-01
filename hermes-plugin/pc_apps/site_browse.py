"""Browse a user-given website (read-only): open the URL, read same-host pages, return text."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Any
from urllib.parse import urljoin, urlparse

from . import browser_actions as ba
from . import tools as base

MAX_PAGES = 8
DEFAULT_PAGES = 5
MAX_CHARS_PER_PAGE = 9000
NAV_WAIT_SEC = 2.2

_SKIP_PATH = re.compile(
    r"(?i)(logout|sign[-_]?out|log[-_]?out|checkout|cart|payment|pay\b|billing|"
    r"password|reset-password|delete[-_]?account|unsubscribe)"
)
_SKIP_EXT = re.compile(r"(?i)\.(pdf|zip|rar|exe|dmg|pkg|mp4|mp3|mov|avi|wmv|png|jpe?g|gif|webp|svg)(\?|$)")


def _normalize_url(raw: str) -> str | None:
    u = (raw or "").strip().strip("<>\"'")
    if not u:
        return None
    if not re.match(r"^https?://", u, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", u, re.I):
            u = "https://" + u
        else:
            return None
    try:
        p = urlparse(u)
    except Exception:
        return None
    if p.scheme.lower() not in ("http", "https"):
        return None
    if p.username or p.password:
        return None
    if p.scheme.lower() == "javascript" or "javascript:" in u.lower():
        return None
    if not p.netloc:
        return None
    # Prefer https
    if p.scheme.lower() == "http":
        u = "https://" + u[len("http://") :]
    return u.split("#", 1)[0]


def _host_key(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _same_host(a: str, b: str) -> bool:
    return bool(_host_key(a) and _host_key(a) == _host_key(b))


def _score_link(href: str, start: str) -> int:
    """Higher = better candidate for a site overview."""
    try:
        p = urlparse(href)
        sp = urlparse(start)
    except Exception:
        return 0
    path = (p.path or "/").rstrip("/") or "/"
    low = path.lower()
    score = 10
    # Prefer shallow pages
    depth = len([x for x in path.split("/") if x])
    score -= min(depth, 4) * 2
    for kw, pts in (
        ("about", 20),
        ("service", 15),
        ("product", 15),
        ("pricing", 14),
        ("contact", 12),
        ("portfolio", 12),
        ("work", 10),
        ("project", 10),
        ("team", 8),
        ("blog", 6),
        ("faq", 8),
        ("home", 5),
    ):
        if kw in low:
            score += pts
    if path == "/" or path == "":
        score += 25
    if p.netloc and sp.netloc and p.netloc.lower() != sp.netloc.lower():
        # www vs non-www already normalized by same_host; different host = 0
        if _host_key(href) != _host_key(start):
            return 0
    if _SKIP_PATH.search(path) or _SKIP_EXT.search(href):
        return 0
    return score


_HARVEST_JS = r"""
(() => {
  const maxLen = %d;
  const root = document.querySelector('main')
    || document.querySelector('[role="main"]')
    || document.querySelector('article')
    || document.body;
  let text = (root && (root.innerText || root.textContent) || '')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const truncated = text.length > maxLen;
  if (truncated) text = text.slice(0, maxLen);
  const links = [];
  const seen = new Set();
  for (const a of Array.from(document.querySelectorAll('a[href]'))) {
    let href = a.href || '';
    if (!href || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) continue;
    href = href.split('#')[0];
    if (seen.has(href)) continue;
    seen.add(href);
    const label = (a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    links.push({ href, label });
    if (links.length >= 40) break;
  }
  return {
    url: location.href,
    title: document.title || '',
    text,
    truncated,
    links,
  };
})()
"""


def _read_page(ws: str) -> dict[str, Any]:
    try:
        return ba._eval(ws, _HARVEST_JS % MAX_CHARS_PER_PAGE) or {}
    except Exception as exc:
        return {"error": str(exc), "url": "", "title": "", "text": "", "links": []}


def browse_website(args: dict | None = None, **kwargs) -> str:
    """Open a website the user gave, read several same-host pages. Never submits forms."""
    args = dict(args or {})
    args.update({k: v for k, v in kwargs.items() if v is not None})
    start = _normalize_url(str(args.get("url") or args.get("link") or ""))
    if not start:
        return json.dumps({"ok": False, "error": "Need a valid http(s) website URL."})
    focus = str(args.get("focus") or args.get("question") or args.get("task") or "").strip()
    try:
        max_pages = int(args.get("max_pages") or DEFAULT_PAGES)
    except Exception:
        max_pages = DEFAULT_PAGES
    max_pages = max(1, min(max_pages, MAX_PAGES))

    err = base._ensure_cdp()
    if err:
        return json.dumps({"ok": False, "error": err})

    opened = base._open_url_in_chrome(start, source="browse_website")
    if not opened.get("ok"):
        return json.dumps({"ok": False, "error": opened.get("error") or "Could not open the website."})

    target = opened.get("target") if isinstance(opened.get("target"), dict) else {}
    ws = target.get("webSocketDebuggerUrl")
    if not ws:
        # Fall back to any matching page
        host = _host_key(start)
        page = ba._find_page(host) if host else None
        ws = (page or {}).get("webSocketDebuggerUrl")
    if not ws:
        return json.dumps({"ok": False, "error": "Website tab opened but could not connect to read it."})

    time.sleep(NAV_WAIT_SEC)
    pages_read: list[dict[str, Any]] = []
    seen: set[str] = set()
    queue: list[str] = [start]
    skipped: list[str] = []

    while queue and len(pages_read) < max_pages:
        url = queue.pop(0)
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        if not _same_host(url, start):
            skipped.append(url)
            continue
        if _SKIP_PATH.search(urlparse(url).path or "") or _SKIP_EXT.search(url):
            skipped.append(url)
            continue
        seen.add(key)
        try:
            ba._cdp_call(ws, "Page.navigate", {"url": url})
            time.sleep(NAV_WAIT_SEC if len(pages_read) == 0 else 1.6)
            info = _read_page(ws)
        except Exception as exc:
            pages_read.append({"url": url, "title": "", "text": "", "error": str(exc)})
            continue
        text = (info.get("text") or "").strip()
        title = (info.get("title") or "").strip()
        final_url = (info.get("url") or url).strip()
        pages_read.append({
            "url": final_url,
            "title": title,
            "text": text,
            "truncated": bool(info.get("truncated")),
            "chars": len(text),
        })
        # Rank and enqueue same-host links
        candidates: list[tuple[int, str]] = []
        for link in info.get("links") or []:
            href = link.get("href") if isinstance(link, dict) else None
            if not href:
                continue
            abs_url = urljoin(final_url, href).split("#", 1)[0]
            if not _same_host(abs_url, start):
                continue
            if abs_url.rstrip("/").lower() in seen:
                continue
            sc = _score_link(abs_url, start)
            if sc <= 0:
                continue
            candidates.append((sc, abs_url))
        candidates.sort(key=lambda x: (-x[0], x[1]))
        for _, href in candidates:
            if len(queue) + len(pages_read) >= max_pages + 4:
                break
            if href.rstrip("/").lower() not in seen and href not in queue:
                queue.append(href)

    summary_lines = []
    for i, p in enumerate(pages_read, 1):
        bit = f"{i}. {p.get('title') or 'Untitled'} — {p.get('url')}"
        summary_lines.append(bit)

    return json.dumps({
        "ok": True,
        "action": "browse_website",
        "start_url": start,
        "host": _host_key(start),
        "focus": focus or None,
        "pages_read": pages_read,
        "page_count": len(pages_read),
        "pages_index": summary_lines,
        "pages_skipped_count": len(skipped),
        "submitted": False,
        "forms_filled": False,
        "limits": {
            "max_pages": max_pages,
            "same_host_only": True,
            "max_chars_per_page": MAX_CHARS_PER_PAGE,
        },
        "how_to_help": (
            "Use the page texts below to answer the user. Review the site, summarize what it offers, "
            "or do the task they asked. Do not submit forms, sign in, buy, or click pay/checkout."
        ),
        "message": f"Read {len(pages_read)} page(s) on {_host_key(start)} (read-only).",
    })
