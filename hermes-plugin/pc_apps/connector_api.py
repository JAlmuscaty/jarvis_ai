"""Hermes tools for Jarvis data connectors (read without opening apps)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("JARVIS_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.environ.get("JARVIS_HUD_TOKEN", "jarvis-9f2517")


def _req(method: str, path: str, body: dict | None = None) -> dict:
    url = BASE + path
    data = None
    headers = {"Accept": "application/json", "X-Jarvis-Token": TOKEN}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(err)
        except Exception:
            return {"ok": False, "error": err or str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def connector_list(args: dict, **kwargs) -> str:
    res = _req("GET", "/api/connections")
    apps = res.get("apps") or []
    linked = [
        {
            "id": a.get("id"),
            "label": a.get("label"),
            "mode": a.get("mode"),
            "status": a.get("status"),
            "capabilities": a.get("capabilities"),
            "item_count": a.get("item_count"),
        }
        for a in apps
        if a.get("linked")
    ]
    return json.dumps({
        "ok": True,
        "linked_count": len(linked),
        "linked": linked,
        "hint": "Use connector_query to read linked app data WITHOUT opening the website.",
    }, indent=2)


def connector_query(args: dict, **kwargs) -> str:
    app = (args.get("app") or args.get("connector") or "").strip().lower()
    query = (args.get("query") or args.get("q") or "").strip()
    if not app:
        return json.dumps({"ok": False, "error": "app is required (gmail, google_calendar, google_drive, obsidian, notebooklm, second_brain, ...)"})
    res = _req("POST", "/api/connections/query", {"app": app, "query": query})
    if res.get("ok"):
        res["message"] = (
            f"Read from linked connector '{app}' without opening its UI. "
            f"source={res.get('source')}"
        )
    return json.dumps(res, ensure_ascii=False, indent=2)


def connector_read(args: dict, **kwargs) -> str:
    app = (args.get("app") or "").strip().lower()
    item_id = (args.get("id") or args.get("path") or args.get("item_id") or "").strip()
    if not app or not item_id:
        return json.dumps({"ok": False, "error": "app and id/path required"})
    res = _req("POST", "/api/connections/read", {"app": app, "id": item_id})
    return json.dumps(res, ensure_ascii=False, indent=2)


def connector_sync(args: dict, **kwargs) -> str:
    app = (args.get("app") or "").strip().lower()
    if not app:
        return json.dumps({"ok": False, "error": "app is required"})
    res = _req("POST", "/api/connections/sync", {"app": app})
    return json.dumps(res, ensure_ascii=False, indent=2)
