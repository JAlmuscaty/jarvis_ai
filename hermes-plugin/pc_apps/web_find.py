"""Headless web research for Jarvis — returns results as text, never opens Chrome."""
from __future__ import annotations

import html as html_lib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_RESULTS = 12


def _fetch(url: str, timeout: float = 12.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _unwrap_ddg_href(href: str) -> str:
    href = html_lib.unescape((href or "").strip())
    if "uddg=" in href:
        try:
            q = urllib.parse.urlparse(href).query
            uddg = urllib.parse.parse_qs(q).get("uddg", [""])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
        except Exception:
            pass
    return href


def _clean_text(s: str) -> str:
    t = html_lib.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _parse_ddg_html(page: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    # DuckDuckGo HTML lite results
    for m in re.finditer(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        page,
        re.I | re.S,
    ):
        url = _unwrap_ddg_href(m.group(1))
        title = _clean_text(m.group(2))
        if not url.startswith("http") or not title:
            continue
        # snippet often follows in result__snippet
        snip = ""
        tail = page[m.end() : m.end() + 800]
        sm = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)', tail, re.I | re.S)
        if sm:
            snip = _clean_text(sm.group(1))
        results.append({"title": title[:160], "url": url[:500], "snippet": snip[:280]})
        if len(results) >= limit:
            break
    return results


def _parse_bing_html(page: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for m in re.finditer(
        r'<li class="b_algo".*?<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>.*?'
        r'(?:<p>|class="b_caption"[^>]*>.*?<p[^>]*>)(.*?)</p>',
        page,
        re.I | re.S,
    ):
        url = html_lib.unescape(m.group(1)).strip()
        title = _clean_text(m.group(2))
        snip = _clean_text(m.group(3))
        if not title:
            continue
        results.append({"title": title[:160], "url": url[:500], "snippet": snip[:280]})
        if len(results) >= limit:
            break
    if results:
        return results
    # Fallback: simpler title+url only
    for m in re.finditer(
        r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        page,
        re.I | re.S,
    ):
        url = html_lib.unescape(m.group(1)).strip()
        title = _clean_text(m.group(2))
        if "bing.com" in url or not title:
            continue
        results.append({"title": title[:160], "url": url[:500], "snippet": ""})
        if len(results) >= limit:
            break
    return results


def web_find(args: dict, **kwargs) -> str:
    """Search the web headlessly and return findings for chat — does NOT open the PC browser."""
    query = (args.get("query") or args.get("q") or args.get("topic") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    fast = bool(args.get("fast"))
    try:
        count = int(args.get("count") or args.get("limit") or (4 if fast else 8))
    except (TypeError, ValueError):
        count = 4 if fast else 8
    count = max(2, min(MAX_RESULTS, count))
    try:
        fetch_timeout = float(args.get("timeout") or (5.0 if fast else 12.0))
    except (TypeError, ValueError):
        fetch_timeout = 5.0 if fast else 12.0
    fetch_timeout = max(2.0, min(20.0, fetch_timeout))

    errors: list[str] = []
    results: list[dict[str, str]] = []

    ddg_url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    try:
        page = _fetch(ddg_url, timeout=fetch_timeout)
        results = _parse_ddg_html(page, count)
    except Exception as exc:
        errors.append(f"duckduckgo: {exc}")

    # Bing only if DDG thin — skip on fast path when we already have something
    need_bing = len(results) < (1 if fast else 3)
    if need_bing:
        bing_url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
        try:
            page = _fetch(bing_url, timeout=min(fetch_timeout, 6.0))
            more = _parse_bing_html(page, count)
            seen = {r["url"] for r in results}
            for r in more:
                if r["url"] not in seen:
                    results.append(r)
                    seen.add(r["url"])
                if len(results) >= count:
                    break
        except Exception as exc:
            errors.append(f"bing: {exc}")

    if not results:
        return json.dumps({
            "ok": False,
            "error": "No web results returned. " + ("; ".join(errors) if errors else "Try a simpler query."),
            "query": query,
            "opened_browser": False,
        })

    return json.dumps({
        "ok": True,
        "action": "web_find",
        "query": query,
        "count": len(results),
        "results": results[:count],
        "opened_browser": False,
        "fast": fast,
        "note": (
            "Headless search only — nothing was opened on the user's PC. "
            "Summarize the best matches in chat. Do NOT call chrome_google_search or "
            "chrome_open_research_tabs unless the user explicitly asks to open them."
        ),
    })
