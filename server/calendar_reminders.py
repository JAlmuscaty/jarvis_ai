"""Push Jarvis calendar events to phone reminders.

Primary path: Google Calendar API with popup reminders (iPhone Calendar alerts
when the same Google account is enabled under Settings → Calendar).

Optional path: Apple Reminders via an iOS Shortcut named "Jarvis Reminder"
when the phone HUD is connected (Shortcuts cannot be written silently otherwise).
"""
from __future__ import annotations

import os
import urllib.parse
from pathlib import Path
from typing import Any

from calendar_store import load as cal_load, upsert_event as cal_upsert
from connectors import is_linked
from connectors import google_oauth

# Minutes before event for timed items (also fire at event time = 0)
DEFAULT_REMINDER_MINUTES = [30, 0]
# All-day: noon the day before (Google: minutes before midnight of the event day)
DEFAULT_ALLDAY_REMINDER_MINUTES = [12 * 60]
SHORTCUT_NAME = os.environ.get("JARVIS_REMINDER_SHORTCUT", "Jarvis Reminder").strip() or "Jarvis Reminder"


def _reminder_minutes_for(event: dict) -> list[int]:
    kind = (event.get("kind") or "").lower()
    if kind == "holiday":
        # Day before (noon-ish) + morning of the holiday start
        if event.get("time"):
            return [24 * 60, 60]
        return [24 * 60, 12 * 60]
    if event.get("time"):
        return list(DEFAULT_REMINDER_MINUTES)
    return list(DEFAULT_ALLDAY_REMINDER_MINUTES)


def _holiday_end_companion(event: dict) -> dict | None:
    """Synthetic all-day item on end_date so phone warns that the holiday is ending."""
    if (event.get("kind") or "").lower() != "holiday":
        return None
    end = str(event.get("end_date") or "").strip()[:10]
    start = str(event.get("date") or "").strip()[:10]
    if not end or end == start:
        return None
    title = str(event.get("title") or "Holiday").strip()
    return {
        "id": f"{event.get('id') or 'hol'}_end",
        "title": f"{title} ends",
        "date": end,
        "kind": "holiday",
        "notes": f"Last day of {title}. School/break ending.",
        "source": "holiday_end_reminder",
        "google_event_id": event.get("google_end_event_id"),
    }


def push_event_to_phone(path: Path, event: dict) -> dict[str, Any]:
    """Sync one Jarvis event to Google Calendar (+ optional Apple Reminders shortcut)."""
    out: dict[str, Any] = {"ok": True, "google": None, "apple_reminders": None, "end_reminder": None}
    if not is_linked("google_calendar"):
        out["ok"] = False
        out["google"] = {
            "ok": False,
            "skipped": True,
            "error": "Google Calendar not linked — Connect it in the HUD so phone alerts work.",
            "needs_link": True,
        }
        return out

    g = google_oauth.calendar_upsert_event(event, reminder_minutes=_reminder_minutes_for(event))
    out["google"] = g
    updated = dict(event)
    if g.get("ok") and g.get("google_event_id"):
        updated["google_event_id"] = g["google_event_id"]
        if g.get("html_link"):
            updated["google_html_link"] = g["html_link"]
    else:
        out["ok"] = False

    companion = _holiday_end_companion(event)
    if companion:
        eg = google_oauth.calendar_upsert_event(
            companion,
            reminder_minutes=[24 * 60, 12 * 60],
        )
        out["end_reminder"] = eg
        if eg.get("ok") and eg.get("google_event_id"):
            updated["google_end_event_id"] = eg["google_event_id"]

    if g.get("ok") or (companion and (out.get("end_reminder") or {}).get("ok")):
        try:
            cal_upsert(path, updated)
            out["event"] = updated
        except Exception as exc:
            out["event"] = event
            out["persist_error"] = str(exc)
    else:
        out["event"] = event

    # Optional Apple Reminders via Shortcut (only if explicitly enabled + phone HUD listening)
    if os.environ.get("JARVIS_APPLE_REMINDERS", "").strip().lower() in ("1", "true", "yes", "on"):
        out["apple_reminders"] = _queue_apple_reminders_shortcut(event)
    else:
        out["apple_reminders"] = {
            "ok": False,
            "skipped": True,
            "note": "Set JARVIS_APPLE_REMINDERS=1 and create Shortcut “Jarvis Reminder” for Apple Reminders.app",
        }
    return out


def push_events_to_phone(path: Path, events: list[dict]) -> dict[str, Any]:
    results = []
    ok_n = 0
    for ev in events:
        r = push_event_to_phone(path, ev)
        results.append(r)
        if r.get("ok"):
            ok_n += 1
    return {"ok": ok_n == len(events), "synced": ok_n, "total": len(events), "results": results}


def delete_remote_for_event(event: dict | None) -> dict[str, Any]:
    if not event:
        return {"ok": True, "skipped": True}
    gid = str(event.get("google_event_id") or "").strip()
    if not gid:
        return {"ok": True, "skipped": True, "note": "no google_event_id"}
    if not is_linked("google_calendar"):
        return {"ok": False, "error": "Google Calendar not linked", "skipped": True}
    return google_oauth.calendar_delete_remote(gid)


def find_event(path: Path, event_id: str) -> dict | None:
    data = cal_load(path)
    return next((e for e in (data.get("events") or []) if e.get("id") == event_id), None)


def _queue_apple_reminders_shortcut(event: dict) -> dict[str, Any]:
    """Open Shortcuts on a connected phone HUD to create an Apple Reminder.

    Requires a Shortcut named JARVIS_REMINDER_SHORTCUT (default: Jarvis Reminder)
    that accepts Text input and runs “Add New Reminder”.
    """
    try:
        import phone_commands
    except ImportError:
        return {"ok": False, "skipped": True, "error": "phone_commands unavailable"}

    title = str(event.get("title") or "Reminder").strip()
    date = str(event.get("date") or "").strip()
    time_s = str(event.get("time") or "").strip()
    bits = [title]
    if date:
        bits.append(f"on {date}")
    if time_s:
        bits.append(f"at {time_s}")
    text = " ".join(bits)
    name_q = urllib.parse.quote(SHORTCUT_NAME)
    text_q = urllib.parse.quote(text)
    scheme = f"shortcuts://run-shortcut?name={name_q}&input=text&text={text_q}"
    try:
        cmd = phone_commands.create_command(
            app="shortcuts",
            label=f"Reminder: {title[:40]}",
            scheme=scheme,
            url=None,
        )
        return {
            "ok": True,
            "queued": True,
            "command_id": cmd.get("command_id"),
            "app": "shortcuts",
            "label": cmd.get("label"),
            "scheme": scheme,
            "shortcut": SHORTCUT_NAME,
            "note": (
                "If the phone HUD is open, Shortcuts will run. "
                f"Create an iOS Shortcut named “{SHORTCUT_NAME}” that adds a Reminder from text input."
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
