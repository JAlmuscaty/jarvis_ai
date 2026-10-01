"""High-level connector operations used by the HUD API and Hermes tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import catalog_by_id, get_link, is_linked, set_link, snapshot
from . import google_oauth
from . import sync as sync_mod
from . import vault


def link_connector(app_id: str, *, vault_path: str | None = None) -> dict[str, Any]:
    """Establish a real data link (not merely open-in-browser)."""
    meta = catalog_by_id().get(app_id)
    if not meta:
        return {"ok": False, "error": f"Unknown connector '{app_id}'"}

    mode = meta["mode"]

    if app_id == "second_brain":
        set_link(app_id, linked=True, meta={"auth": "local"})
        return {"ok": True, **snapshot(), "message": "Second Brain is linked locally."}

    if mode == "api" and app_id in ("gmail", "google_calendar", "google_drive", "google_docs"):
        # Link the whole Google suite scopes together for one consent
        if not google_oauth.oauth_configured():
            return {
                "ok": False,
                "needs_setup": True,
                "error": (
                    "Google API link needs a one-time OAuth client (same idea as Claude connectors). "
                    "1) Open Google Cloud Console → APIs & Services → Credentials → Create OAuth client (Desktop). "
                    "2) Enable Gmail API, Calendar API, Drive API. "
                    "3) Save the JSON as connectors/google_oauth_client.json under JARVIS_DATA_DIR "
                    "or set GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET in ~/.hermes/.env. "
                    "Then tap CONNECT again — Jarvis will read Gmail/Calendar/Drive without opening them. "
                    "Calendar also needs write access so new Jarvis events remind you on your phone."
                ),
                "setup_url": "https://console.cloud.google.com/apis/credentials",
                "client_json_path": str(google_oauth._CLIENT_JSON),
            }
        return google_oauth.start_oauth_link(["gmail", "google_calendar", "google_drive", "google_docs"])

    if mode == "vault" and app_id == "obsidian":
        if not vault_path:
            return {
                "ok": False,
                "error": "Provide your Obsidian vault folder path to link (like Claude ↔ Obsidian).",
                "needs_path": True,
            }
        return vault.link_obsidian(vault_path)

    if mode == "synced":
        set_link(app_id, linked=True, meta={"auth": "synced_index"})
        if app_id == "notebooklm":
            synced = sync_mod.sync_notebooklm()
            snap = snapshot()
            return {"ok": bool(synced.get("ok")), **snap, "sync": synced, "message": synced.get("message") or synced.get("error")}
        if app_id == "classroom":
            synced = sync_mod.sync_classroom()
            snap = snapshot()
            return {"ok": bool(synced.get("ok")), **snap, "sync": synced, "message": synced.get("message") or synced.get("error")}
        return {"ok": True, **snapshot()}

    return {"ok": False, "error": f"Connector mode '{mode}' not implemented for {app_id}"}


def unlink_connector(app_id: str) -> dict[str, Any]:
    if app_id == "second_brain":
        # Keep always-on; ignore
        return {"ok": True, **snapshot(), "message": "Second Brain stays available locally."}
    # Google suite shares one token — unlinking one can clear google token if none remain
    set_link(app_id, linked=False)
    if app_id in ("gmail", "google_calendar", "google_drive", "google_docs"):
        still = any(is_linked(a) for a in ("gmail", "google_calendar", "google_drive", "google_docs"))
        if not still:
            try:
                from . import token_path
                p = token_path("google")
                if p.is_file():
                    p.unlink()
            except Exception:
                pass
    return {"ok": True, **snapshot()}


def sync_connector(app_id: str) -> dict[str, Any]:
    if app_id == "notebooklm":
        return sync_mod.sync_notebooklm()
    if app_id == "classroom":
        return sync_mod.sync_classroom()
    if app_id == "obsidian":
        return vault.reindex_obsidian()
    if app_id in ("gmail", "google_calendar", "google_drive", "google_docs"):
        # API connectors are live — "sync" = health check
        if app_id == "gmail":
            return google_oauth.gmail_list(max_results=3)
        if app_id == "google_calendar":
            return google_oauth.calendar_list(max_results=5)
        if app_id in ("google_drive", "google_docs"):
            return google_oauth.drive_search("", max_results=5)
    return {"ok": False, "error": f"No sync for {app_id}"}


def query_connector(app_id: str, query: str, *, brain_path: Path | None = None) -> dict[str, Any]:
    """Read/search a linked connector without opening its UI."""
    meta = catalog_by_id().get(app_id)
    if not meta:
        return {"ok": False, "error": f"Unknown connector '{app_id}'"}
    if app_id != "second_brain" and not is_linked(app_id) and meta["mode"] != "vault":
        # second brain always on; obsidian checked inside
        if app_id != "obsidian":
            return {"ok": False, "error": f"{meta['label']} is not linked. Connect it in the HUD first."}

    if app_id == "gmail":
        return google_oauth.gmail_list(query=query or "in:inbox", max_results=10)
    if app_id == "google_calendar":
        return google_oauth.calendar_list(max_results=15)
    if app_id in ("google_drive", "google_docs"):
        return google_oauth.drive_search(query or "document", max_results=10)
    if app_id == "obsidian":
        return vault.obsidian_search(query)
    if app_id == "second_brain":
        if not brain_path:
            return {"ok": False, "error": "brain_path required"}
        return vault.second_brain_search(query, brain_path)
    if app_id == "notebooklm":
        return sync_mod.query_notebooklm_index(query)
    if app_id == "classroom":
        from . import load_index
        idx = load_index("classroom")
        items = idx.get("items") or []
        q = (query or "").lower()
        hits = [i for i in items if not q or q in json_blob(i)]
        return {"ok": True, "count": len(hits), "items": hits[:20], "source": "classroom_index"}

    return {"ok": False, "error": f"No query handler for {app_id}"}


def json_blob(obj: Any) -> str:
    import json as _json
    try:
        return _json.dumps(obj, ensure_ascii=False).lower()
    except Exception:
        return str(obj).lower()


def read_connector_item(app_id: str, item_id: str, *, brain_path: Path | None = None) -> dict[str, Any]:
    if app_id == "gmail":
        return google_oauth.gmail_read(item_id)
    if app_id in ("google_drive", "google_docs"):
        return google_oauth.drive_read_text(item_id)
    if app_id == "obsidian":
        return vault.obsidian_read(item_id)
    if app_id == "second_brain" and brain_path:
        try:
            from brain_store import load as brain_load
        except ImportError:
            from server.brain_store import load as brain_load  # type: ignore
        data = brain_load(brain_path)
        idea = next((i for i in data.get("ideas") or [] if i.get("id") == item_id), None)
        if not idea:
            return {"ok": False, "error": "idea not found"}
        return {"ok": True, "idea": idea, "source": "second_brain"}
    return {"ok": False, "error": f"No read handler for {app_id}"}
