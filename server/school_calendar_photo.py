"""Ingest yearly school calendars / holiday lists from a photo into Jarvis calendar.

Never treats these as homework. Stores dated holiday/break events with optional end_date
so Jarvis can remind when a holiday is coming or ending soon.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

try:
    from calendar_store import upsert_event
except ImportError:
    from .calendar_store import upsert_event  # type: ignore

_YEAR_CAL_RE = re.compile(
    r"(?is)\b(?:"
    r"(?:yearly|year|annual|academic|school)\s+(?:schedule|calendar|timetable|plan)"
    r"|(?:holiday|holidays|break|vacation|اجازة|إجازة|عطلة|العطل)\s*(?:list|calendar|dates|schedule)?"
    r"|(?:term|semester)\s+dates?"
    r"|this\s+is\s+(?:my\s+)?(?:school\s+)?(?:year|holiday|holidays|calendar)"
    r"|(?:add|save|put|import)\s+(?:these\s+)?(?:holidays|breaks|vacation|year\s+calendar)"
    r"|school\s+year\s+(?:calendar|dates|schedule)"
    r")\b"
)

_CLASSIFY_PROMPT = """Look at this PHOTO. Reply with ONLY one word:
HOLIDAY_CALENDAR — if it is a yearly/academic school calendar, term dates, or a list of holidays/breaks/vacations.
OTHER — anything else (homework worksheet, weekly class timetable only, random photo, notes, etc.).
"""

_EXTRACT_PROMPT = """You are extracting SCHOOL HOLIDAYS and academic-year breaks from a PHOTO for Jarvis.

Read the image (printed yearly calendar, holiday list, term dates, school year schedule of breaks).

Reply with ONLY a JSON array (no markdown fences, no commentary). Each item:
{"title":"short name","date":"YYYY-MM-DD","end_date":"YYYY-MM-DD or null","notes":"optional"}

Rules:
- Include holidays, breaks, vacations, public holidays, Eid, mid-year break, summer break, teacher work days OFF, etc.
- date = first day of the holiday/break (or the single day).
- end_date = last day of the break when it spans multiple days; otherwise null.
- Do NOT invent homework, assignments, or class periods.
- Do NOT include weekly Monday–Friday lesson timetable blocks.
- If a year is missing, infer from context or user message; prefer the upcoming/current school year.
- If nothing readable: []
"""


def wants_school_calendar_photo(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_YEAR_CAL_RE.search(t))


def looks_like_calendar_caption(text: str) -> bool:
    """Short captions that often accompany a schedule/holiday photo."""
    t = (text or "").strip().lower()
    if not t:
        return True  # bare photo — allow classify step
    if len(t) > 160:
        return False
    return bool(
        re.search(
            r"(?is)\b(schedule|calendar|holiday|holidays|break|vacation|"
            r"اجازة|إجازة|عطلة|جدول|this|here|look)\b",
            t,
        )
    )


def _parse_items(raw: str) -> list[dict[str, Any]]:
    s = (raw or "").strip()
    if not s:
        return []
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if m:
        s = m.group(1).strip()
    start = s.find("[")
    end = s.rfind("]")
    if start >= 0 and end > start:
        s = s[start : end + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("holidays") or data.get("events") or data.get("items") or []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("name") or item.get("holiday") or "").strip()
        date = (item.get("date") or item.get("start") or item.get("start_date") or "").strip()[:10]
        end_date = (item.get("end_date") or item.get("end") or item.get("finish") or "").strip()[:10] or None
        notes = (item.get("notes") or item.get("description") or "").strip() or None
        if not title or not re.match(r"^\d{4}-\d{2}-\d{2}$", date or ""):
            continue
        if end_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
            end_date = None
        # Reject anything that looks like homework
        blob = f"{title} {notes or ''}".lower()
        if re.search(r"\b(homework|assignment|due|worksheet|hw)\b", blob):
            continue
        out.append({
            "title": title[:160],
            "date": date,
            "end_date": end_date,
            "notes": notes[:400] if notes else None,
            "kind": "holiday",
            "source": "photo_year_calendar",
        })
    return out[:80]


def classify_calendar_photo(
    *,
    image_data_url: str,
    extract_fn: Callable[[str, str], str],
) -> bool:
    raw = (extract_fn(_CLASSIFY_PROMPT, image_data_url) or "").strip().upper()
    return "HOLIDAY_CALENDAR" in raw.replace(" ", "_") or raw.startswith("HOLIDAY")


def ingest_school_calendar_photo(
    *,
    image_data_url: str,
    user_text: str,
    calendar_path: Path,
    extract_fn: Callable[[str, str], str],
    push_fn: Callable[[Path, dict], Any] | None = None,
) -> dict[str, Any]:
    """extract_fn(prompt_text, image_data_url) -> model reply text."""
    prompt = (
        f"{_EXTRACT_PROMPT}\n"
        f"User said: {(user_text or '').strip()[:300] or '(photo of yearly schedule / holidays)'}"
    )
    raw = extract_fn(prompt, image_data_url)
    items = _parse_items(raw)
    if not items:
        return {
            "text": (
                "I looked at the photo but couldn't clearly read holidays or year-calendar dates. "
                "Try a sharper picture, or tell me the holiday names and dates."
            ),
            "tools": [{"name": "school_calendar_photo", "preview": "empty"}],
            "run_id": "school_calendar_photo",
            "events_saved": [],
            "raw_extract": (raw or "")[:500],
        }

    saved: list[dict] = []
    sync_notes: list[str] = []
    for item in items:
        ev = upsert_event(calendar_path, item)
        saved.append(ev)
        if push_fn:
            try:
                sync = push_fn(calendar_path, ev)
                if isinstance(sync, dict) and sync.get("ok"):
                    sync_notes.append(ev.get("title") or "")
            except Exception as exc:
                sync_notes.append(f"sync fail: {exc}")

    lines = [
        f"Saved {len(saved)} holiday/break date{'s' if len(saved) != 1 else ''} from your year calendar. "
        "I did not add any homework."
    ]
    for i, ev in enumerate(saved[:12], 1):
        span = ev.get("date") or "?"
        if ev.get("end_date") and ev.get("end_date") != ev.get("date"):
            span = f"{ev['date']} → {ev['end_date']}"
        lines.append(f"{i}. {ev.get('title')} ({span})")
    if len(saved) > 12:
        lines.append(f"…and {len(saved) - 12} more.")
    lines.append(
        "I'll remind you when a holiday is coming up, and when it's close to ending. "
        "Open Calendar on the HUD to review."
    )
    if sync_notes and any("fail" not in s for s in sync_notes):
        lines.append("Phone/Google reminders were synced where linked.")

    return {
        "text": "\n".join(lines),
        "tools": [{"name": "school_calendar_photo", "preview": f"{len(saved)} holidays"}],
        "run_id": "school_calendar_photo",
        "events_saved": saved,
        "count": len(saved),
    }
