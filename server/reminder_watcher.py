"""Fire Jarvis "remind me" nudges at the scheduled time.

Calendar events marked jarvis_remind=True are polled; when due, they are marked
reminded_at and returned so the server can HUD-notify / chat / speak.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .calendar_store import load as cal_load, save as cal_save
except ImportError:
    from calendar_store import load as cal_load, save as cal_save

_DEFAULT_CALENDAR_PATH = Path(__file__).resolve().parent / "logs" / "calendar.json"


def _parse_remind_at(ev: dict) -> datetime | None:
    raw = str(ev.get("remind_at") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    date_s = str(ev.get("date") or "").strip()[:10]
    time_s = str(ev.get("time") or "").strip()
    if not date_s:
        return None
    if not time_s:
        # All-day remind → 09:00 local
        time_s = "09:00"
    try:
        return datetime.fromisoformat(f"{date_s}T{time_s[:5]}:00")
    except ValueError:
        return None


def pop_due_reminders(
    path: Path | None = None,
    *,
    now: datetime | None = None,
    early_seconds: int = 45,
    late_seconds: int = 15 * 60,
) -> list[dict[str, Any]]:
    """Return due jarvis_remind events and mark them reminded_at (once)."""
    cp = path or _DEFAULT_CALENDAR_PATH
    now = now or datetime.now()
    data = cal_load(cp)
    events = list(data.get("events") or [])
    due: list[dict[str, Any]] = []
    changed = False

    for i, ev in enumerate(events):
        if not ev.get("jarvis_remind"):
            continue
        if ev.get("reminded_at"):
            continue
        when = _parse_remind_at(ev)
        if when is None:
            continue
        earliest = when - timedelta(seconds=max(0, early_seconds))
        latest = when + timedelta(seconds=max(60, late_seconds))
        if not (earliest <= now <= latest):
            # Missed beyond late window → mark so we don't spam days later
            if now > latest:
                updated = dict(ev)
                updated["reminded_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                updated["remind_missed"] = True
                events[i] = updated
                changed = True
            continue
        updated = dict(ev)
        updated["reminded_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
        events[i] = updated
        due.append(updated)
        changed = True

    if changed:
        data["events"] = events
        cal_save(cp, data)
    return due


def format_reminder_message(ev: dict) -> str:
    title = str(ev.get("title") or "something").strip()
    return f"Reminder: {title}."
