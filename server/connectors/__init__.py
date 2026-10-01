"""Jarvis Connectors — Claude/Obsidian-style data links.

CONNECT means: grant Jarvis persistent read/query access to an app's data.
It does NOT mean "open this website in Chrome."

Modes:
  api    — OAuth / REST (Gmail, Calendar, Drive)
  vault  — local filesystem (Obsidian markdown vault, Second Brain)
  synced — signed-in browser session indexed once into a local cache
           so Jarvis can query without reopening the app
  open   — launcher-only (no data link); clearly labeled in the HUD
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.Lock()

DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data")))
CONNECTORS_DIR = DATA_DIR / "connectors"
STATE_PATH = CONNECTORS_DIR / "state.json"

# Catalog of connectable apps with real data-link semantics
CONNECTOR_CATALOG: list[dict[str, Any]] = [
    {
        "id": "gmail",
        "label": "Gmail",
        "category": "google",
        "mode": "api",
        "blurb": "Read inbox & threads via Google API — no browser open required after link.",
        "capabilities": ["list_mail", "read_mail", "search_mail", "send_mail"],
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        "url": "https://mail.google.com/",
    },
    {
        "id": "google_calendar",
        "label": "Google Calendar",
        "category": "google",
        "mode": "api",
        "blurb": (
            "Read & write events. Jarvis pushes HUD calendar items here with phone alerts "
            "(iPhone Calendar notifications when this Google account is on the phone)."
        ),
        "capabilities": ["list_events", "search_events", "create_events", "reminders"],
        "scopes": ["https://www.googleapis.com/auth/calendar"],
        "url": "https://calendar.google.com/",
    },
    {
        "id": "google_drive",
        "label": "Google Drive",
        "category": "google",
        "mode": "api",
        "blurb": "Search, read, and upload files (including handwritten PDFs) via Drive API.",
        "capabilities": ["search_files", "read_file", "upload_file"],
        "scopes": [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "url": "https://drive.google.com/",
    },
    {
        "id": "google_docs",
        "label": "Google Docs",
        "category": "google",
        "mode": "api",
        "blurb": "Read Docs and create essays / handwritten Docs via Docs + Drive.",
        "capabilities": ["search_docs", "read_doc", "create_doc", "write_essay"],
        "scopes": [
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/documents.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "url": "https://docs.google.com/document/",
    },
    {
        "id": "google_slides",
        "label": "Google Slides",
        "category": "google",
        "mode": "api",
        "blurb": "Create full Google Slides presentations (multi-slide decks) via API.",
        "capabilities": ["create_presentation", "write_slides"],
        "scopes": [
            "https://www.googleapis.com/auth/presentations",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/presentations.readonly",
        ],
        "url": "https://docs.google.com/presentation/",
    },
    {
        "id": "obsidian",
        "label": "Obsidian Vault",
        "category": "notes",
        "mode": "vault",
        "blurb": "Claude-style link: Jarvis reads your Markdown vault directly (app can stay closed).",
        "capabilities": ["search_notes", "read_note", "list_notes"],
        "url": None,
    },
    {
        "id": "second_brain",
        "label": "Second Brain (Jarvis Notes)",
        "category": "notes",
        "mode": "vault",
        "blurb": "Your Jarvis idea graph — always available as a local data connector.",
        "capabilities": ["search_ideas", "read_idea", "list_ideas"],
        "url": "/hud/brain.html",
    },
    {
        "id": "notebooklm",
        "label": "NotebookLM",
        "category": "ai",
        "mode": "synced",
        "blurb": "Index notebooks/notes/sources once, then Jarvis queries the local index without opening NotebookLM.",
        "capabilities": ["query_index", "list_notebooks", "read_notes"],
        "url": "https://notebooklm.google.com/",
    },
    {
        "id": "classroom",
        "label": "Google Classroom",
        "category": "google",
        "mode": "synced",
        "blurb": "Sync dues into Jarvis calendar index — then ask what's due without opening Classroom.",
        "capabilities": ["list_dues"],
        "url": "https://classroom.google.com/",
    },
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _empty_state() -> dict:
    return {"links": {}, "updated_at": None}


def load_state() -> dict:
    CONNECTORS_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = _empty_state()
        if not isinstance(data, dict):
            data = _empty_state()
        data.setdefault("links", {})
        return data


def save_state(data: dict) -> None:
    CONNECTORS_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        out = dict(data)
        out["updated_at"] = _now()
        STATE_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")


def catalog_by_id() -> dict[str, dict]:
    return {c["id"]: c for c in CONNECTOR_CATALOG}


def token_path(app_id: str) -> Path:
    return CONNECTORS_DIR / f"{app_id}_token.json"


def index_path(app_id: str) -> Path:
    return CONNECTORS_DIR / f"{app_id}_index.json"


def get_link(app_id: str) -> dict | None:
    st = load_state()
    link = (st.get("links") or {}).get(app_id)
    return link if isinstance(link, dict) else None


def is_linked(app_id: str) -> bool:
    link = get_link(app_id)
    return bool(link and link.get("linked"))


def set_link(app_id: str, *, linked: bool, meta: dict | None = None) -> dict:
    if app_id not in catalog_by_id():
        raise ValueError(f"Unknown connector '{app_id}'")
    st = load_state()
    entry = dict((st.get("links") or {}).get(app_id) or {})
    entry["linked"] = bool(linked)
    entry["updated_at"] = _now()
    if linked:
        entry["linked_at"] = entry.get("linked_at") or _now()
        if meta:
            entry.update({k: v for k, v in meta.items() if v is not None})
    else:
        entry["linked_at"] = None
        # wipe secrets/indexes on disconnect
        for p in (token_path(app_id), index_path(app_id)):
            try:
                if p.is_file():
                    p.unlink()
            except Exception:
                pass
        for k in ("vault_path", "account", "last_sync_at", "item_count", "error"):
            entry.pop(k, None)
    st.setdefault("links", {})[app_id] = entry
    save_state(st)
    return snapshot()


def snapshot() -> dict:
    """HUD-facing catalog merged with live link status."""
    st = load_state()
    links = st.get("links") or {}
    apps = []
    for meta in CONNECTOR_CATALOG:
        aid = meta["id"]
        link = links.get(aid) or {}
        linked = bool(link.get("linked"))
        # Second Brain is always available locally
        if aid == "second_brain" and not linked:
            linked = True
            link = {**link, "linked": True, "linked_at": link.get("linked_at") or _now()}
        mode = meta["mode"]
        status = "linked" if linked else "not_linked"
        if linked and mode == "api" and not token_path(aid).is_file() and aid != "second_brain":
            # vaults don't need oauth tokens
            if mode == "api":
                status = "needs_auth"
        if linked and mode == "vault" and aid == "obsidian" and not link.get("vault_path"):
            status = "needs_path"
        if linked and mode == "synced" and not index_path(aid).is_file() and aid != "second_brain":
            status = "needs_sync"

        apps.append({
            **meta,
            "linked": linked,
            "status": status,
            "linked_at": link.get("linked_at"),
            "last_sync_at": link.get("last_sync_at"),
            "item_count": link.get("item_count"),
            "vault_path": link.get("vault_path"),
            "account": link.get("account"),
            "error": link.get("error"),
            # back-compat for old Connect UI field names
            "connected": linked,
            "connected_at": link.get("linked_at"),
        })
    return {
        "ok": True,
        "apps": apps,
        "linked_count": sum(1 for a in apps if a["linked"]),
        "connected_count": sum(1 for a in apps if a["linked"]),
        "updated_at": st.get("updated_at"),
        "hint": (
            "CONNECT links Jarvis to the app's data (API / vault / sync index). "
            "After linking, Jarvis can read and search it without opening the website."
        ),
    }


def save_index(app_id: str, payload: dict) -> Path:
    p = index_path(app_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = _now()
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # update link meta
    st = load_state()
    entry = dict((st.get("links") or {}).get(app_id) or {})
    entry["linked"] = True
    entry["last_sync_at"] = payload["updated_at"]
    items = payload.get("items") or payload.get("notes") or payload.get("messages") or payload.get("events") or []
    if isinstance(items, list):
        entry["item_count"] = len(items)
    entry["error"] = None
    st.setdefault("links", {})[app_id] = entry
    save_state(st)
    return p


def load_index(app_id: str) -> dict:
    p = index_path(app_id)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
