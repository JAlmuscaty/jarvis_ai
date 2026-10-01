"""Hermes tools for Composio status / connect links."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

JARVIS_BASE = (
    os.environ.get("JARVIS_BASE_URL")
    or os.environ.get("JARVIS_HUD_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")
TOKEN = os.environ.get("JARVIS_HUD_TOKEN", "")


def _req(method: str, path: str, body: dict | None = None) -> dict:
    url = JARVIS_BASE + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if TOKEN:
        headers["X-Jarvis-Token"] = TOKEN
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
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


def composio_status(args: dict, **kwargs) -> str:
    return json.dumps(_req("GET", "/api/composio/status"), ensure_ascii=False)


def composio_connect(args: dict, **kwargs) -> str:
    toolkit = (args.get("toolkit") or args.get("app") or args.get("name") or "").strip()
    if not toolkit:
        return json.dumps({"ok": False, "error": "toolkit required, e.g. gmail, notion, github, slack"})
    return json.dumps(_req("POST", "/api/composio/connect", {"toolkit": toolkit}), ensure_ascii=False)


def composio_setup(args: dict, **kwargs) -> str:
    return json.dumps(_req("GET", "/api/composio/setup"), ensure_ascii=False)
