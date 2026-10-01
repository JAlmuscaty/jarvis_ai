"""Pending phone open commands for connected HUD clients."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
STORE_PATH = Path.home() / ".hermes" / "jarvis_phone_commands.json"
MAX_AGE_SEC = 120


def _now() -> float:
    return time.time()


def _empty() -> dict:
    return {"pending": []}


def _load() -> dict:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("pending", [])
        return data
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _prune(data: dict) -> dict:
    cutoff = _now() - MAX_AGE_SEC
    data["pending"] = [
        c for c in (data.get("pending") or [])
        if float(c.get("created_at") or 0) >= cutoff and not c.get("acked")
    ]
    return data


def create_command(
    *,
    app: str,
    label: str | None = None,
    url: str | None = None,
    scheme: str | None = None,
) -> dict[str, Any]:
    with _LOCK:
        data = _prune(_load())
        cmd = {
            "command_id": uuid.uuid4().hex[:12],
            "app": str(app or "").strip().lower(),
            "label": (label or app or "app").strip(),
            "url": url,
            "scheme": scheme,
            "created_at": _now(),
            "acked": False,
        }
        data["pending"].append(cmd)
        _save(data)
        return cmd


def list_pending() -> list[dict]:
    with _LOCK:
        data = _prune(_load())
        _save(data)
        return list(data.get("pending") or [])


def ack(command_id: str) -> dict | None:
    with _LOCK:
        data = _load()
        found = None
        kept = []
        for c in data.get("pending") or []:
            if c.get("command_id") == command_id:
                found = dict(c)
                found["acked"] = True
            else:
                kept.append(c)
        data["pending"] = kept
        data = _prune(data)
        _save(data)
        return found
