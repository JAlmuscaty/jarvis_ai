"""Intelligent weekly schedule parser and router for Jarvis.

Understands natural language schedule dictations (e.g., 'Here is my entire schedule:
Monday 9am Math, 11am Physics; Tuesday 10am Chemistry...'), converts them into
structured weekly blocks, and saves them to the Jarvis Calendar & Schedule store.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from .calendar_store import normalize_schedule_item, replace_schedule
except ImportError:
    from calendar_store import normalize_schedule_item, replace_schedule

_DEFAULT_CALENDAR_PATH = Path(__file__).resolve().parent / "logs" / "calendar.json"

DAYS_MAP = {
    "monday": "mon", "mon": "mon", "mondays": "mon",
    "tuesday": "tue", "tue": "tue", "tues": "tue", "tuesdays": "tue",
    "wednesday": "wed", "wed": "wed", "wednesdays": "wed",
    "thursday": "thu", "thu": "thu", "thur": "thu", "thurs": "thu", "thursdays": "thu",
    "friday": "fri", "fri": "fri", "fridays": "fri",
    "saturday": "sat", "sat": "sat", "saturdays": "sat",
    "sunday": "sun", "sun": "sun", "sundays": "sun",
}

_DAY_NAMES = list(DAYS_MAP.keys())
_DAY_NC = r"(?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)"

_SCHEDULE_TRIGGER = re.compile(
    r"\b(my\s+entire\s+schedule|my\s+weekly\s+schedule|my\s+schedule|here\s+is\s+my\s+schedule|"
    r"save\s+(?:my\s+)?schedule|add\s+to\s+(?:my\s+)?schedule|set\s+(?:my\s+)?schedule|"
    r"class\s+schedule|my\s+timetable|my\s+classes|"
    r"(?:school|university|uni|college)\s+schedule|"
    r"here\s+(?:are|is)\s+my\s+(?:classes|lectures))\b",
    re.I,
)


def _normalize_time_str(raw: str | None) -> str | None:
    """Convert natural time like '9am', '9:30 pm', '14:00' to clean standard format."""
    if not raw:
        return None
    s = raw.strip().lower()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if not m:
        return raw.strip()
    hour = int(m.group(1))
    minute = m.group(2) or "00"
    meridiem = m.group(3)

    if meridiem:
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute}"
    if hour <= 24:
        return f"{hour:02d}:{minute}"
    return raw.strip()


def parse_schedule_text(text: str) -> tuple[list[dict], bool]:
    """Parse text into a list of schedule blocks: [{title, day, start, end, notes}, ...].

    Returns (blocks, is_entire_schedule_replace).
    """
    t = (text or "").strip()
    if not t:
        return [], False

    is_entire = bool(re.search(r"\b(entire|all\s+my|replace|whole|full)\s+schedule\b", t, re.I))

    # Strip conversational prefix
    cleaned = re.sub(
        r"^(?:(?:hey\s+)?jarvis\s*,?\s*)?(?:please\s+)?(?:can\s+you\s+)?(?:remember\s+and\s+|here\s+is\s+|save\s+|set\s+|add\s+)?"
        r"(?:my\s+)?(?:entire\s+|weekly\s+)?(?:schedule|timetable|classes)(?:\s+to\s+(?:the\s+)?(?:calendar|schedule))?\s*[:\-,\s]*",
        "",
        t,
        flags=re.I,
    ).strip()

    items: list[dict] = []

    # 1) Multi-day phrases like "Mondays and Wednesdays from 9am to 10:30am CS101"
    multi_re = re.compile(
        rf"({_DAY_NC})\s+(?:and|&)\s+({_DAY_NC})\s+(?:(?:at|from)\s+)?(\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?)\s*(?:to|-)\s*(\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?)\s+(?:i\s+have\s+)?([A-Za-z0-9\s\-_]+?)(?=[.,;]|$)",
        re.I,
    )
    for m in multi_re.finditer(cleaned):
        d1 = DAYS_MAP.get(m.group(1).lower())
        d2 = DAYS_MAP.get(m.group(2).lower())
        s, e = _normalize_time_str(m.group(3)), _normalize_time_str(m.group(4))
        title = m.group(5).strip(" .,;:")
        if d1 and title:
            items.append({"day": d1, "start": s, "end": e, "title": title})
        if d2 and title:
            items.append({"day": d2, "start": s, "end": e, "title": title})

    # 2) Day-chunk segmentation
    day_splits = list(re.finditer(rf"\b({_DAY_NC})\b", cleaned, re.I))
    for i, m in enumerate(day_splits):
        day_str = m.group(1).lower()
        day_code = DAYS_MAP.get(day_str)
        if not day_code:
            continue
        start_idx = m.end()
        end_idx = day_splits[i + 1].start() if i + 1 < len(day_splits) else len(cleaned)
        chunk = cleaned[start_idx:end_idx].strip(" :-\t")

        # Split chunk into comma/semicolon/newline separated segments
        parts = re.split(r"[,;\n]+", chunk)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            # Match range e.g. "9:00 to 10:30 Math" or "9am - 11am Math"
            range_m = re.match(
                r"(?:(?:at|from)\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(.+)",
                p,
                re.I,
            )
            if range_m:
                s, e, title = _normalize_time_str(range_m.group(1)), _normalize_time_str(range_m.group(2)), range_m.group(3)
                title = re.sub(r"^(?:i have|class|is)\s+", "", title.strip(" .,;:"), flags=re.I).strip()
                title = re.sub(r"\b(and|then|please|also)\b.*$", "", title, flags=re.I).strip(" .,;:")
                if title and len(title) > 1:
                    items.append({"day": day_code, "start": s, "end": e, "title": title[:120]})
                continue

            # Match single time e.g. "9am Math", "at 14:00 Lab"
            single_m = re.match(r"(?:(?:at|from)\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(.+)", p, re.I)
            if single_m:
                s, title = _normalize_time_str(single_m.group(1)), single_m.group(2)
                title = re.sub(r"^(?:i have|class|is)\s+", "", title.strip(" .,;:"), flags=re.I).strip()
                title = re.sub(r"\b(and|then|please|also)\b.*$", "", title, flags=re.I).strip(" .,;:")
                if title and len(title) > 1:
                    items.append({"day": day_code, "start": s, "end": None, "title": title[:120]})

    # De-duplicate items
    cleaned_items = []
    seen = set()
    for it in items:
        key = (it["day"], it.get("start"), it["title"].lower())
        if key in seen:
            continue
        seen.add(key)
        cleaned_items.append({
            "title": it["title"],
            "day": it["day"],
            "start": it.get("start"),
            "end": it.get("end"),
            "source": "jarvis_voice",
        })

    return cleaned_items, is_entire


def try_handle_schedule(text: str, calendar_path: Path | None = None) -> dict[str, Any] | None:
    """If the user is giving Jarvis their schedule, parse it, save it, and return a routed response."""
    t = (text or "").strip()
    if not t:
        return None

    # Check if text looks like schedule input
    has_trigger = bool(_SCHEDULE_TRIGGER.search(t))
    # Count day mentions
    day_matches = [d for d in _DAY_NAMES if re.search(rf"\b{d}\b", t, re.I)]
    has_times = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b", t, re.I))

    if not has_trigger and not (len(set(day_matches)) >= 2 and has_times):
        # Single-day school dump: "Monday 9am Math, 11am Physics"
        schoolish = bool(re.search(
            r"(?i)\b(class|lecture|lab|math|physics|chemistry|biology|course|school|university|uni|college)\b",
            t,
        ))
        if not (len(set(day_matches)) >= 1 and has_times and schoolish):
            return None

    items, is_entire = parse_schedule_text(t)
    if not items:
        return None

    cp = calendar_path or _DEFAULT_CALENDAR_PATH

    # If user specifies entire schedule, replace; otherwise merge
    merge = not is_entire
    replace_schedule(cp, items, merge=merge)

    days_found = sorted(list({it["day"].upper() for it in items}))
    summary_days = ", ".join(days_found)

    count = len(items)
    mode_str = "added to" if merge else "set fresh for"

    reply_text = (
        f"I've {mode_str} your weekly calendar: "
        f"{count} class{'es' if count > 1 else ''} across {summary_days}. "
        f"You can view your complete timetable on the HUD Schedule tab."
    )

    return {
        "text": reply_text,
        "tools": [
            {
                "name": "calendar_set_schedule",
                "preview": f"{count} blocks · {summary_days} ({'replaced' if not merge else 'merged'})",
            }
        ],
        "run_id": "schedule_saved",
        "items": items,
        "count": count,
        "days": days_found,
    }
