"""Track Chrome tabs opened by Jarvis; close only those (never user-opened tabs)."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

CDP_BASE = os.environ.get("BROWSER_CDP_URL", "").strip().rstrip("/")
if not CDP_BASE:
    CDP_BASE = "http://127.0.0.1:9222"
if CDP_BASE.startswith("ws://"):
    CDP_BASE = "http://" + CDP_BASE[len("ws://") :].split("/", 1)[0]
elif CDP_BASE.startswith("wss://"):
    CDP_BASE = "https://" + CDP_BASE[len("wss://") :].split("/", 1)[0]

REGISTRY_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "jarvis_open_tabs.json"

SITE_PATTERNS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube.com", "youtu.be"),
    "whatsapp": ("web.whatsapp.com",),
    "classroom": ("classroom.google.com",),
    "chatgpt": ("chatgpt.com", "chat.openai.com"),
    "vidbox": ("vidbox.cc", "vidbox.vc", "vidbox.to"),
    "movies": ("vidbox.cc", "vidbox.vc", "vidbox.to"),
    "notebooklm": ("notebooklm.google.com",),
    "gmail": ("mail.google.com",),
    "google": ("google.com",),
    "chrome": (),
}


def _cdp_get(path: str, timeout: float = 5.0) -> tuple[int, str]:
    url = CDP_BASE.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def _cdp_put(path: str, timeout: float = 5.0) -> tuple[int, str]:
    url = CDP_BASE.rstrip("/") + path
    req = urllib.request.Request(url, method="PUT")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def live_pages() -> list[dict]:
    try:
        _, body = _cdp_get("/json/list")
        data = json.loads(body)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _load() -> dict[str, Any]:
    try:
        if REGISTRY_PATH.is_file():
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                tabs = data.get("tabs")
                if isinstance(tabs, dict):
                    return data
    except Exception:
        pass
    return {"tabs": {}}


def _save(data: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY_PATH)


def register_tab(target_id: str, url: str, source: str, title: str = "") -> None:
    tid = (target_id or "").strip()
    if not tid:
        return
    data = _load()
    tabs: dict[str, Any] = data.setdefault("tabs", {})
    tabs[tid] = {
        "target_id": tid,
        "url": url or "",
        "title": (title or "")[:200],
        "source": source,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "opened_at_ts": time.time(),
    }
    _save(data)


def resolve_target_id(preferred: dict | None, url: str, before_ids: set[str] | None = None) -> str | None:
    """Find the CDP target id after opening a tab (Chrome sometimes omits id in /json/new)."""
    if isinstance(preferred, dict):
        tid = (preferred.get("id") or "").strip()
        if tid:
            return tid

    before = before_ids or set()
    deadline = time.time() + 3.0
    while time.time() < deadline:
        pages = live_pages()
        # Prefer brand-new targets not in before_ids
        fresh = [
            p for p in pages
            if (p.get("type") or "page") == "page"
            and p.get("id")
            and p.get("id") not in before
            and (p.get("url") or "").startswith(("http://", "https://", "about:"))
        ]
        if fresh:
            # newest first if possible — Chrome list is usually newest first
            return str(fresh[0]["id"])

        # Fallback: match by URL prefix
        u = (url or "").rstrip("/")
        for p in pages:
            if (p.get("type") or "page") != "page":
                continue
            pu = (p.get("url") or "").rstrip("/")
            if u and (pu == u or pu.startswith(u) or u.startswith(pu[: max(12, len(pu) // 2)])):
                if p.get("id") and p.get("id") not in before:
                    return str(p["id"])
        time.sleep(0.2)
    return None


def register_from_open_result(
    result: dict[str, Any],
    source: str,
    before_ids: set[str] | None = None,
) -> str | None:
    """Register a tab from _open_url_in_chrome() result. Returns target_id."""
    if not result.get("ok"):
        return None
    target = result.get("target") if isinstance(result.get("target"), dict) else {}
    url = str(result.get("url") or (target or {}).get("url") or "")
    tid = resolve_target_id(target, url, before_ids)
    if not tid:
        return None
    register_tab(tid, url, source, str((target or {}).get("title") or ""))
    result["jarvis_target_id"] = tid
    if isinstance(result.get("target"), dict):
        result["target"]["id"] = tid
    return tid


def jarvis_target_ids() -> set[str]:
    return set(_load().get("tabs", {}).keys())


def is_jarvis_tab(target_id: str | None) -> bool:
    if not target_id:
        return False
    return target_id in jarvis_target_ids()


def reconcile_with_live(pages: list[dict] | None = None) -> None:
    """Drop registry entries for tabs the user already closed."""
    pages = pages if pages is not None else live_pages()
    live_ids = {p.get("id") for p in pages if p.get("id")}
    data = _load()
    tabs: dict[str, Any] = data.get("tabs") or {}
    stale = [tid for tid in tabs if tid not in live_ids]
    if not stale:
        return
    for tid in stale:
        tabs.pop(tid, None)
    _save(data)


def list_jarvis_tabs(pages: list[dict] | None = None) -> list[dict[str, Any]]:
    """Registry entries intersected with currently open Chrome tabs."""
    pages = pages if pages is not None else live_pages()
    reconcile_with_live(pages)
    by_id = {p.get("id"): p for p in pages if p.get("id")}
    out: list[dict[str, Any]] = []
    for tid, meta in (_load().get("tabs") or {}).items():
        live = by_id.get(tid)
        if not live:
            continue
        url = live.get("url") or meta.get("url") or ""
        out.append({
            "target_id": tid,
            "url": url,
            "title": (live.get("title") or meta.get("title") or "")[:120],
            "source": meta.get("source"),
            "opened_at": meta.get("opened_at"),
            "jarvis_opened": True,
            "site": _site_from_url(url),
        })
    return out


def _site_from_url(url: str) -> str:
    u = (url or "").lower()
    for name, needles in SITE_PATTERNS.items():
        if name == "chrome":
            continue
        if any(n in u for n in needles):
            return name
    return "other"


def _matches_site(url: str, site: str) -> bool:
    s = (site or "").strip().lower()
    if not s or s in ("chrome", "all", "any", "browser"):
        return True
    needles = SITE_PATTERNS.get(s)
    if not needles:
        # treat unknown site string as substring match
        return s in (url or "").lower()
    u = (url or "").lower()
    return any(n in u for n in needles)


def _close_via_ws(target_id: str, ws_url: str | None) -> tuple[bool, str]:
    if not ws_url:
        return False, "no websocket"
    try:
        from websockets.sync.client import connect

        msg_id = int(time.time() * 1000) % 1_000_000_000
        payload = {
            "id": msg_id,
            "method": "Target.closeTarget",
            "params": {"targetId": target_id},
        }
        with connect(ws_url, open_timeout=5.0, close_timeout=2) as ws:
            ws.send(json.dumps(payload))
            deadline = time.time() + 5.0
            while time.time() < deadline:
                raw = ws.recv()
                data = json.loads(raw)
                if data.get("id") == msg_id:
                    if "error" in data:
                        return False, str(data["error"])
                    result = data.get("result") or {}
                    if result.get("success") is False:
                        return False, "Target.closeTarget success=false"
                    return True, "ws"
    except Exception as e:
        return False, f"ws:{e}"
    return False, "ws timeout"


def _close_target(target_id: str, ws_url: str | None = None) -> tuple[bool, str]:
    ok, detail = _close_via_ws(target_id, ws_url)
    if ok:
        return True, detail

    # HTTP fallbacks used by Chrome DevTools
    for method_path in (f"/json/close/{target_id}",):
        try:
            status, body = _cdp_get(method_path)
            if status == 200:
                return True, f"get:{body[:120]}"
        except Exception as e:
            detail = f"{detail}; get:{e}"
        try:
            status, body = _cdp_put(method_path)
            if status == 200:
                return True, f"put:{body[:120]}"
        except Exception as e:
            detail = f"{detail}; put:{e}"
    return False, detail


def clear_registry() -> None:
    """Forget tracked tabs after the Jarvis Chrome window is gone."""
    _save({"tabs": {}})


def close_tabs(
    *,
    close_all: bool = False,
    site: str | None = None,
    target_ids: list[str] | None = None,
    live_pages_list: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Close only Jarvis-owned tabs. Never touches tabs not in the registry.
    """
    pages = live_pages_list if live_pages_list is not None else live_pages()
    if not pages:
        # distinguish empty chrome vs CDP down
        try:
            _cdp_get("/json/version")
        except Exception as e:
            return {"ok": False, "error": f"Chrome debug (CDP :9222) is not running: {e}"}

    reconcile_with_live(pages)
    registered = list_jarvis_tabs(pages)

    site_norm = (site or "").strip().lower() or None
    if site_norm in ("chrome", "all", "any", "browser"):
        close_all = True
        site_norm = None

    if not registered:
        return {
            "ok": True,
            "closed": [],
            "closed_count": 0,
            "skipped_user_tabs": True,
            "message": (
                "No Jarvis-opened tabs are registered as open. "
                "Only tabs Jarvis opens AFTER this fix are closeable. "
                "Your existing tabs were not touched."
            ),
        }

    ids_filter: set[str] | None = None
    if target_ids:
        ids_filter = {str(x).strip() for x in target_ids if str(x).strip()}

    # Default: if agent forgot args but there are jarvis tabs, close all of them
    if not close_all and not site_norm and not ids_filter:
        close_all = True

    by_id = {p.get("id"): p for p in pages if p.get("id")}
    to_close: list[dict[str, Any]] = []
    for tab in registered:
        tid = tab["target_id"]
        if ids_filter is not None and tid not in ids_filter:
            continue
        if site_norm and not _matches_site(tab.get("url") or "", site_norm):
            continue
        to_close.append(tab)

    if not to_close:
        return {
            "ok": True,
            "closed": [],
            "closed_count": 0,
            "message": "No matching Jarvis-opened tabs to close. User tabs were not touched.",
            "jarvis_tabs_open": registered,
        }

    closed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    data = _load()
    tabs_map: dict[str, Any] = data.get("tabs") or {}

    for tab in to_close:
        tid = tab["target_id"]
        live = by_id.get(tid) or {}
        ok, detail = _close_target(tid, live.get("webSocketDebuggerUrl"))
        if ok:
            tabs_map.pop(tid, None)
            closed.append({"target_id": tid, "url": tab.get("url"), "title": tab.get("title")})
        else:
            failed.append({"target_id": tid, "url": tab.get("url"), "error": detail})

    data["tabs"] = tabs_map
    _save(data)

    return {
        "ok": len(failed) == 0,
        "closed_count": len(closed),
        "closed": closed,
        "failed": failed,
        "remaining_jarvis_tabs": list_jarvis_tabs(),
        "message": (
            f"Closed {len(closed)} tab(s) that Jarvis opened. "
            "Tabs you opened yourself were not closed."
        ),
    }
