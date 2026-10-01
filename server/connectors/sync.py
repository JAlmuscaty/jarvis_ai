"""Synced connectors — index signed-in web apps into a local cache.

After CONNECT + one sync, Jarvis queries the local index without reopening the site.
Used for services without a clean public API (NotebookLM) or as a bridge.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from . import get_link, load_index, save_index, set_link

_PLUGIN_ROOTS = [
    Path.home() / "AppData" / "Local" / "hermes" / "plugins",
    Path(__file__).resolve().parents[2] / "hermes-plugin",
]


def _ensure_plugin() -> None:
    for root in _PLUGIN_ROOTS:
        if (root / "pc_apps").is_dir() and str(root) not in sys.path:
            sys.path.insert(0, str(root))


def sync_notebooklm() -> dict[str, Any]:
    """Pull NotebookLM notebooks/notes/sources into local index (requires Chrome signed-in once)."""
    _ensure_plugin()
    try:
        from pc_apps import notebooklm_actions as nlm  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"NotebookLM plugin unavailable: {exc}"}

    status_raw = nlm.notebooklm_status({})
    try:
        status = json.loads(status_raw)
    except Exception:
        status = {"ok": False, "error": status_raw[:200]}

    if status.get("state") in ("verify_required", "signin_required") or (
        not status.get("ok") and "Verify" in str(status.get("error") or "")
    ):
        return {
            "ok": False,
            "error": status.get("error") or "Complete Google verify/sign-in in Chrome debug, then Sync again.",
            "state": status.get("state") or "verify_required",
        }

    notebooks = []
    list_raw = nlm.notebooklm_list_notebooks({})
    try:
        listed = json.loads(list_raw)
        if listed.get("ok"):
            notebooks = listed.get("notebooks") or []
        elif listed.get("error"):
            return {"ok": False, "error": listed.get("error"), "state": listed.get("state")}
    except Exception as exc:
        return {"ok": False, "error": f"list failed: {exc}"}

    notes_raw = nlm.notebooklm_read_notes({"force_refresh": True})
    try:
        notes_payload = json.loads(notes_raw)
    except Exception:
        notes_payload = {"ok": False, "error": notes_raw[:200]}

    items = []
    for nb in notebooks:
        items.append({
            "type": "notebook",
            "title": nb.get("title"),
            "url": nb.get("url"),
        })
    if notes_payload.get("ok"):
        for s in notes_payload.get("sources") or []:
            items.append({"type": "source", "title": s if isinstance(s, str) else s.get("title") or str(s)})
        for n in notes_payload.get("notes") or []:
            if isinstance(n, str):
                items.append({"type": "note", "title": n[:80], "text": n})
            elif isinstance(n, dict):
                items.append({
                    "type": "note",
                    "title": n.get("title") or (n.get("text") or "")[:80],
                    "text": n.get("text") or n.get("content") or "",
                })

    # Keep recent Q&A from notebooklm cache too
    try:
        cache = nlm._load_cache()
        for qa in cache.get("recent_qa") or []:
            items.append({
                "type": "qa",
                "title": qa.get("q"),
                "text": qa.get("a"),
                "citations": qa.get("citations") or [],
            })
    except Exception:
        pass

    save_index("notebooklm", {
        "items": items,
        "notebooks": notebooks,
        "active_notebook": notes_payload.get("notebook_title") or status.get("notebook_title"),
        "status": status,
    })
    set_link("notebooklm", linked=True, meta={
        "auth": "synced_index",
        "item_count": len(items),
        "last_sync_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    return {
        "ok": True,
        "item_count": len(items),
        "notebooks": len(notebooks),
        "message": f"Synced {len(items)} NotebookLM items into local index. Jarvis can query without reopening.",
    }


def query_notebooklm_index(query: str, max_results: int = 8) -> dict[str, Any]:
    idx = load_index("notebooklm")
    items = idx.get("items") or []
    if not items:
        # fall through to live tool if linked but empty
        link = get_link("notebooklm") or {}
        if link.get("linked"):
            return {"ok": False, "error": "Index empty — tap Sync on Connect, or ask Jarvis to sync NotebookLM."}
        return {"ok": False, "error": "NotebookLM not linked."}

    q = (query or "").strip().lower()
    hits = []
    for it in items:
        blob = f"{it.get('title','')} {it.get('text') or ''}".lower()
        if q and q not in blob:
            continue
        hits.append(it)
        if len(hits) >= max_results:
            break

    # If no lexical hits but we have QA cache, try live plugin cache query
    if not hits and q:
        _ensure_plugin()
        try:
            from pc_apps import notebooklm_actions as nlm  # type: ignore
            live = json.loads(nlm.notebooklm_query({"query": query, "force_refresh": False}))
            if live.get("ok") and live.get("answer"):
                return {
                    "ok": True,
                    "answer": live.get("answer"),
                    "citations": live.get("citations") or [],
                    "cached": live.get("cached"),
                    "source": "notebooklm_cache_or_live",
                }
        except Exception:
            pass

    return {
        "ok": True,
        "count": len(hits),
        "items": hits,
        "active_notebook": idx.get("active_notebook"),
        "source": "notebooklm_index",
    }


def sync_classroom() -> dict[str, Any]:
    _ensure_plugin()
    try:
        from pc_apps import browser_actions as ba  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    try:
        # classroom_pull_dues lives on browser_actions via registered tool path
        from pc_apps import tools  # type: ignore
        # Prefer direct calendar classroom import if available
        raw = None
        try:
            from pc_apps.browser_actions import classroom_pull_dues  # type: ignore
            raw = classroom_pull_dues({"import_to_calendar": True})
        except Exception:
            raw = None
        if raw is None:
            return {"ok": False, "error": "classroom_pull_dues unavailable"}
        res = json.loads(raw) if isinstance(raw, str) else dict(raw)
        items = res.get("events") or res.get("dues") or []
        save_index("classroom", {"items": items, "raw": {k: res.get(k) for k in ("ok", "message", "count") if k in res}})
        set_link("classroom", linked=True, meta={"auth": "synced_index", "item_count": len(items)})
        return {"ok": bool(res.get("ok", True)), "item_count": len(items), "result": res}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
