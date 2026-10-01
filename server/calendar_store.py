"""Compact calendar + weekly schedule store for the Jarvis HUD."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _empty() -> dict:
    return {"events": [], "schedule": [], "updated_at": None}


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
        data.setdefault("events", [])
        data.setdefault("schedule", [])
        return data


def save(path: Path, data: dict) -> None:
    with _LOCK:
        data = dict(data)
        data["updated_at"] = _now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_event(raw: dict, *, defaults: dict | None = None) -> dict:
    d = dict(defaults or {})
    d.update({k: v for k, v in (raw or {}).items() if v is not None})
    title = str(d.get("title") or "").strip()
    date = str(d.get("date") or "").strip()  # YYYY-MM-DD
    if not title:
        raise ValueError("title is required")
    if not date:
        raise ValueError("date is required (YYYY-MM-DD)")
    kind = str(d.get("kind") or "homework").strip().lower()
    if kind not in ("homework", "due", "schedule", "holiday", "other"):
        kind = "other"
    end_date = str(d.get("end_date") or "").strip()[:10] or None
    if end_date and end_date < date:
        end_date = date
    ev = {
        "id": str(d.get("id") or _new_id()),
        "title": title[:160],
        "date": date[:10],
        "end_date": end_date,
        "time": (str(d.get("time") or "").strip() or None),
        "end_time": (str(d.get("end_time") or "").strip() or None),
        "kind": kind,
        "class_name": (str(d.get("class_name") or d.get("class") or "").strip() or None),
        "notes": (str(d.get("notes") or "").strip() or None),
        "source": str(d.get("source") or "jarvis")[:40],
        "created_at": d.get("created_at") or _now(),
    }
    # Timed Jarvis nudge ("remind me to …")
    if d.get("jarvis_remind"):
        ev["jarvis_remind"] = True
    if d.get("remind_at"):
        ev["remind_at"] = str(d.get("remind_at"))[:32]
    if d.get("reminded_at"):
        ev["reminded_at"] = str(d.get("reminded_at"))[:32]
    if d.get("brain_idea_id"):
        ev["brain_idea_id"] = str(d.get("brain_idea_id"))[:24]
    # Preserve Google Calendar sync ids when re-saving
    if d.get("google_event_id"):
        ev["google_event_id"] = str(d.get("google_event_id"))
    if d.get("google_html_link"):
        ev["google_html_link"] = str(d.get("google_html_link"))
    if d.get("google_end_event_id"):
        ev["google_end_event_id"] = str(d.get("google_end_event_id"))
    return ev


def normalize_schedule_item(raw: dict) -> dict:
    title = str((raw or {}).get("title") or "").strip()
    full = str((raw or {}).get("day") or "").strip().lower()
    aliases = {
        "mon": "mon", "monday": "mon",
        "tue": "tue", "tues": "tue", "tuesday": "tue",
        "wed": "wed", "wednesday": "wed",
        "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu",
        "fri": "fri", "friday": "fri",
        "sat": "sat", "saturday": "sat",
        "sun": "sun", "sunday": "sun",
    }
    day = aliases.get(full) or aliases.get(full[:3], "")
    if day not in aliases.values():
        raise ValueError("day must be mon..sun (or Monday..Sunday)")
    if not title:
        raise ValueError("title is required")
    start = str((raw or {}).get("start") or raw.get("time") or "").strip() or None
    end = str((raw or {}).get("end") or raw.get("end_time") or "").strip() or None
    return {
        "id": str((raw or {}).get("id") or _new_id()),
        "title": title[:160],
        "day": day,
        "start": start,
        "end": end,
        "notes": (str((raw or {}).get("notes") or "").strip() or None),
        "source": str((raw or {}).get("source") or "jarvis")[:40],
        "created_at": (raw or {}).get("created_at") or _now(),
    }


def upsert_event(path: Path, raw: dict) -> dict:
    data = load(path)
    ev = normalize_event(raw)
    events = [e for e in data["events"] if e.get("id") != ev["id"]]
    # de-dupe classroom imports by title+date+class
    if ev.get("source") == "classroom":
        events = [
            e for e in events
            if not (
                e.get("source") == "classroom"
                and e.get("title") == ev["title"]
                and e.get("date") == ev["date"]
                and (e.get("class_name") or "") == (ev.get("class_name") or "")
            )
        ]
    # de-dupe holiday / year-calendar photo imports
    if ev.get("kind") == "holiday" or (ev.get("source") or "").startswith("photo_"):
        events = [
            e for e in events
            if not (
                e.get("kind") == "holiday"
                and e.get("title") == ev["title"]
                and e.get("date") == ev["date"]
            )
        ]
    events.append(ev)
    data["events"] = events
    save(path, data)
    return ev


def delete_event(path: Path, event_id: str) -> dict | None:
    """Remove an event; return the deleted event dict, or None if missing."""
    data = load(path)
    removed = None
    kept = []
    for e in data["events"]:
        if e.get("id") == event_id and removed is None:
            removed = e
        else:
            kept.append(e)
    if removed is None:
        return None
    data["events"] = kept
    save(path, data)
    return removed


def replace_schedule(path: Path, items: list[dict], *, merge: bool = False) -> list[dict]:
    data = load(path)
    normalized = [normalize_schedule_item(x) for x in items]
    if merge:
        existing_list = list(data.get("schedule") or [])
        for item in normalized:
            # Check for existing match on day + title + start
            matched = False
            for idx, ex in enumerate(existing_list):
                if (
                    ex.get("day") == item.get("day")
                    and (ex.get("title") or "").strip().lower() == (item.get("title") or "").strip().lower()
                    and ex.get("start") == item.get("start")
                ):
                    item["id"] = ex.get("id") or item["id"]
                    existing_list[idx] = item
                    matched = True
                    break
            if not matched:
                existing_list.append(item)
        data["schedule"] = existing_list
    else:
        data["schedule"] = normalized
    save(path, data)
    return data["schedule"]


def add_schedule_item(path: Path, raw: dict) -> dict:
    data = load(path)
    item = normalize_schedule_item(raw)
    data["schedule"] = [s for s in data.get("schedule") or [] if s.get("id") != item["id"]]
    data["schedule"].append(item)
    save(path, data)
    return item


def delete_schedule_item(path: Path, item_id: str) -> bool:
    data = load(path)
    before = len(data.get("schedule") or [])
    data["schedule"] = [s for s in data.get("schedule") or [] if s.get("id") != item_id]
    if len(data["schedule"]) == before:
        return False
    save(path, data)
    return True


def import_events(path: Path, items: list[dict]) -> dict[str, Any]:
    added = []
    errors = []
    for raw in items:
        try:
            raw = dict(raw)
            raw.setdefault("source", "classroom")
            raw.setdefault("kind", "due")
            added.append(upsert_event(path, raw))
        except Exception as e:
            errors.append(str(e))
    return {"added": len(added), "events": added, "errors": errors}
