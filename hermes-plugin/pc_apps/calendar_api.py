"""Talk to the Jarvis voice server calendar API."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

CAL_BASE = os.environ.get("JARVIS_CALENDAR_URL", "http://127.0.0.1:8765/api/calendar").rstrip("/")
TOKEN = os.environ.get("JARVIS_HUD_TOKEN", "")


def _req(method: str, path: str = "", body: dict | list | None = None) -> dict:
    url = CAL_BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["X-Jarvis-Token"] = TOKEN
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body)
        except Exception:
            parsed = {"error": err_body or str(e)}
        return {"ok": False, "http_status": e.code, **(parsed if isinstance(parsed, dict) else {"error": parsed})}
    except Exception as e:
        return {"ok": False, "error": f"Calendar API unreachable: {e}"}


def calendar_list(args: dict, **kwargs) -> str:
    res = _req("GET", "")
    if res.get("ok") is False and "error" in res:
        return json.dumps(res)
    events = res.get("events") or []
    schedule = res.get("schedule") or []
    return json.dumps({
        "ok": True,
        "event_count": len(events),
        "schedule_count": len(schedule),
        "events": events,
        "schedule": schedule,
        "updated_at": res.get("updated_at"),
        "hud_page": "/hud/calendar.html",
        "note": "Show these on the Calendar / Schedule HUD page. User can delete items there too.",
    })


def calendar_add(args: dict, **kwargs) -> str:
    kind = (args.get("kind") or "").strip().lower() or "other"
    if kind not in ("homework", "due", "holiday", "schedule", "other"):
        kind = "other"
    payload = {
        "title": args.get("title"),
        "date": args.get("date"),
        "end_date": args.get("end_date"),
        "time": args.get("time"),
        "end_time": args.get("end_time"),
        "kind": kind,
        "class_name": args.get("class_name") or args.get("class"),
        "notes": args.get("notes"),
        "source": args.get("source") or "jarvis",
    }
    res = _req("POST", "/events", payload)
    if res.get("ok"):
        sync = res.get("phone_sync") or {}
        g = (sync.get("google") or {})
        if g.get("ok"):
            res["message"] = (
                "Added to calendar and synced to Google Calendar with phone alerts "
                "(30 min before + at time). Enable this Google account in iPhone "
                "Settings → Calendar for notifications."
            )
        elif g.get("needs_link") or g.get("needs_reauth"):
            res["message"] = (
                "Added to Jarvis calendar. Connect/reconnect Google Calendar in the HUD "
                "Connect page so new items remind you on your phone."
            )
        else:
            res["message"] = "Added to calendar. User can open Calendar / Schedule on the HUD."
    return json.dumps(res)


def calendar_delete(args: dict, **kwargs) -> str:
    event_id = (args.get("id") or args.get("event_id") or "").strip()
    if not event_id:
        return json.dumps({"ok": False, "error": "id is required"})
    res = _req("DELETE", f"/events/{event_id}")
    return json.dumps(res)


def calendar_set_schedule(args: dict, **kwargs) -> str:
    """Build/replace weekly schedule from user-described blocks."""
    items = args.get("items") or args.get("schedule")
    merge = bool(args.get("merge", True))
    if not items and args.get("title") and args.get("day"):
        items = [{
            "title": args.get("title"),
            "day": args.get("day"),
            "start": args.get("start") or args.get("time"),
            "end": args.get("end") or args.get("end_time"),
            "notes": args.get("notes"),
        }]
    if not items:
        return json.dumps({
            "ok": False,
            "error": "Provide items: [{title, day, start?, end?, notes?}, ...] or a single title+day.",
        })
    res = _req("POST", "/schedule", {"items": items, "merge": merge})
    if res.get("ok"):
        res["message"] = (
            "Schedule updated on the HUD Schedule tab. "
            "User can delete blocks there. merge=" + str(merge)
        )
    return json.dumps(res)


def calendar_delete_schedule(args: dict, **kwargs) -> str:
    item_id = (args.get("id") or args.get("item_id") or "").strip()
    if not item_id:
        return json.dumps({"ok": False, "error": "id is required"})
    res = _req("DELETE", f"/schedule/{item_id}")
    return json.dumps(res)


def calendar_import_events(items: list[dict]) -> dict:
    return _req("POST", "/events/import", {"events": items})
