"""Handwriting tools — memorize samples and write Docs/PDFs in that style."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = (os.environ.get("JARVIS_BASE_URL") or "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.environ.get("JARVIS_HUD_TOKEN") or ""


def _req(method: str, path: str, body: dict | None = None) -> dict:
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["X-Jarvis-Token"] = TOKEN
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err)
        except Exception:
            parsed = {"error": err or str(e)}
        return {"ok": False, "http_status": e.code, **(parsed if isinstance(parsed, dict) else {"error": parsed})}
    except Exception as e:
        return {"ok": False, "error": f"Handwriting API unreachable: {e}"}


def handwriting_status(args: dict, **kwargs) -> str:
    return json.dumps(_req("GET", "/api/handwriting/status"))


def handwriting_write(args: dict, **kwargs) -> str:
    payload = {
        "text": args.get("text") or args.get("prompt") or "",
        "body": args.get("body") or args.get("content"),
        "title": args.get("title"),
        "language": args.get("language"),
        "medium": args.get("medium"),
        "upload": args.get("upload", True),
    }
    return json.dumps(_req("POST", "/api/handwriting/write", payload))
