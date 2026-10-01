"""PC action approvals stored for phone HUD (ChatGPT send, etc.)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

STORE_PATH = Path.home() / ".hermes" / "jarvis_pc_approvals.json"
_LOCK = threading.Lock()


def _load() -> dict[str, Any]:
    try:
        if STORE_PATH.is_file():
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), dict):
                return data
    except Exception:
        pass
    return {"items": {}}


def _save(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def create_approval(
    approval_id: str,
    *,
    kind: str,
    title: str,
    preview: str,
    description: str = "",
) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        item = {
            "approval_id": approval_id,
            "kind": kind,
            "title": title or "APPROVAL REQUIRED",
            "preview": (preview or "")[:2000],
            "description": description or "",
            "decision": None,
            "created_at": time.time(),
            "decided_at": None,
        }
        data.setdefault("items", {})[approval_id] = item
        # prune old (>24h)
        cutoff = time.time() - 86400
        data["items"] = {
            k: v for k, v in data["items"].items()
            if float(v.get("created_at") or 0) >= cutoff
        }
        data["items"][approval_id] = item
        _save(data)
        return item


def get_approval(approval_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return (_load().get("items") or {}).get(approval_id)


def decide(approval_id: str, decision: str) -> dict[str, Any] | None:
    dec = (decision or "").strip().lower()
    if dec not in ("allow", "deny"):
        return None
    with _LOCK:
        data = _load()
        item = (data.get("items") or {}).get(approval_id)
        if not item:
            return None
        item["decision"] = dec
        item["decided_at"] = time.time()
        data["items"][approval_id] = item
        _save(data)
        return item


def consume(approval_id: str, status: str = "consumed") -> dict[str, Any] | None:
    with _LOCK:
        data = _load()
        item = (data.get("items") or {}).get(approval_id)
        if not item:
            return None
        item["consumed"] = True
        item["consume_status"] = status
        data["items"][approval_id] = item
        _save(data)
        return item
