"""Connected apps/websites catalog for the Jarvis Connect HUD."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

# Recommended apps shown in Connect — user can connect/open any of these
RECOMMENDED: list[dict[str, Any]] = [
    {
        "id": "gmail",
        "label": "Gmail",
        "category": "google",
        "url": "https://mail.google.com/",
        "blurb": "Read & send email (only to addresses you saved).",
        "capabilities": ["open", "send_email"],
    },
    {
        "id": "google_slides",
        "label": "Google Slides",
        "category": "google",
        "url": "https://slides.google.com/",
        "blurb": "Open presentations in Chrome.",
        "capabilities": ["open"],
    },
    {
        "id": "google_docs",
        "label": "Google Docs",
        "category": "google",
        "url": "https://docs.google.com/document/",
        "blurb": "Open documents in Chrome.",
        "capabilities": ["open"],
    },
    {
        "id": "google_sheets",
        "label": "Google Sheets",
        "category": "google",
        "url": "https://sheets.google.com/",
        "blurb": "Open spreadsheets in Chrome.",
        "capabilities": ["open"],
    },
    {
        "id": "google_drive",
        "label": "Google Drive",
        "category": "google",
        "url": "https://drive.google.com/",
        "blurb": "Open Drive files in Chrome.",
        "capabilities": ["open"],
    },
    {
        "id": "google_calendar",
        "label": "Google Calendar",
        "category": "google",
        "url": "https://calendar.google.com/",
        "blurb": "Open your calendar in Chrome.",
        "capabilities": ["open"],
    },
    {
        "id": "classroom",
        "label": "Google Classroom",
        "category": "google",
        "url": "https://classroom.google.com/",
        "blurb": "Open Classroom / pull dues.",
        "capabilities": ["open"],
    },
    {
        "id": "youtube",
        "label": "YouTube",
        "category": "media",
        "url": "https://www.youtube.com/",
        "blurb": "Open and search YouTube.",
        "capabilities": ["open", "search"],
    },
    {
        "id": "whatsapp",
        "label": "WhatsApp Web",
        "category": "chat",
        "url": "https://web.whatsapp.com/",
        "blurb": "Open chats (draft never auto-sends).",
        "capabilities": ["open"],
    },
    {
        "id": "chatgpt",
        "label": "ChatGPT",
        "category": "ai",
        "url": "https://chatgpt.com/",
        "blurb": "Draft & send with phone ALLOW.",
        "capabilities": ["open"],
    },
    {
        "id": "notebooklm",
        "label": "NotebookLM (Co-Brain)",
        "category": "ai",
        "url": "https://notebooklm.google.com/",
        "blurb": "Grounded AI co-brain: query documents, notes, citations, study guides & audio overviews.",
        "capabilities": ["open", "query", "notes", "audio_overview", "study_guide"],
    },
    {
        "id": "vidbox",
        "label": "Vidbox (Movies)",
        "category": "media",
        "url": "https://vidbox.cc/",
        "blurb": "Search and watch movies.",
        "capabilities": ["open", "search"],
    },
    {
        "id": "maps",
        "label": "Google Maps",
        "category": "google",
        "url": "https://maps.google.com/",
        "blurb": "Open Maps in Chrome.",
        "capabilities": ["open"],
    },
]


def _empty() -> dict:
    return {"connected": {}, "updated_at": None}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load(path: Path) -> dict:
    with _LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = _empty()
        if not isinstance(data, dict):
            data = _empty()
        data.setdefault("connected", {})
        return data


def save(path: Path, data: dict) -> None:
    with _LOCK:
        data = dict(data)
        data["updated_at"] = _now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def catalog_by_id() -> dict[str, dict]:
    return {a["id"]: a for a in RECOMMENDED}


def snapshot(path: Path) -> dict:
    data = load(path)
    connected = data.get("connected") or {}
    apps = []
    for meta in RECOMMENDED:
        aid = meta["id"]
        st = connected.get(aid) or {}
        apps.append({
            **meta,
            "connected": bool(st.get("connected")),
            "connected_at": st.get("connected_at"),
            "last_opened_at": st.get("last_opened_at"),
        })
    return {
        "apps": apps,
        "connected_count": sum(1 for a in apps if a["connected"]),
        "updated_at": data.get("updated_at"),
    }


def set_connected(path: Path, app_id: str, connected: bool = True) -> dict:
    catalog = catalog_by_id()
    if app_id not in catalog:
        raise ValueError(f"Unknown app '{app_id}'")
    data = load(path)
    entry = dict((data.get("connected") or {}).get(app_id) or {})
    entry["connected"] = bool(connected)
    if connected:
        entry["connected_at"] = _now()
    else:
        entry["connected_at"] = None
    data.setdefault("connected", {})[app_id] = entry
    save(path, data)
    return snapshot(path)


def mark_opened(path: Path, app_id: str) -> dict:
    catalog = catalog_by_id()
    if app_id not in catalog:
        raise ValueError(f"Unknown app '{app_id}'")
    data = load(path)
    entry = dict((data.get("connected") or {}).get(app_id) or {})
    entry["last_opened_at"] = _now()
    # Opening from Connect also counts as connected
    if not entry.get("connected"):
        entry["connected"] = True
        entry["connected_at"] = _now()
    data.setdefault("connected", {})[app_id] = entry
    save(path, data)
    return snapshot(path)


def is_connected(path: Path, app_id: str) -> bool:
    data = load(path)
    st = (data.get("connected") or {}).get(app_id) or {}
    return bool(st.get("connected"))


def app_meta(app_id: str) -> dict | None:
    return catalog_by_id().get(app_id)
