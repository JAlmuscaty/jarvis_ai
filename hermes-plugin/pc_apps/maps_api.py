"""Maps ETA tool — calls Jarvis free OSRM + Kuwait atlas (no Google API key)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


MAPS_BASE = (
    os.environ.get("JARVIS_MAPS_URL")
    or (os.environ.get("JARVIS_BASE_URL") or "http://127.0.0.1:8765").rstrip("/") + "/api/maps"
).rstrip("/")
TOKEN = os.environ.get("JARVIS_HUD_TOKEN") or "jarvis-9f2517"


def _post(path: str, body: dict) -> dict:
    url = MAPS_BASE + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Jarvis-Token": TOKEN,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": False, "error": "empty"}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(err)
        except Exception:
            return {"ok": False, "error": err[:300] or str(e)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def maps_eta(args: dict, **kwargs) -> str:
    """Return driving/walking minutes between two places."""
    origin = str((args or {}).get("origin") or (args or {}).get("from") or "").strip()
    dest = str((args or {}).get("destination") or (args or {}).get("to") or "").strip()
    profile = str((args or {}).get("profile") or (args or {}).get("mode") or "driving").strip()
    if not origin or not dest:
        return json.dumps({"ok": False, "error": "origin and destination are required"})
    result = _post("/eta", {"origin": origin, "destination": dest, "profile": profile})
    return json.dumps(result, ensure_ascii=False)
