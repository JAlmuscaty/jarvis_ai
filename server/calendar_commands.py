"""Fast local calendar + class add (no Hermes wait).

Handles:
- add homework / put on calendar / remind me (dated events)
- "remind me to … at/in …" → timed Jarvis nudge (HUD message at that time)
- add a single recurring class to the weekly school schedule
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .calendar_store import add_schedule_item, upsert_event
except ImportError:
    from calendar_store import add_schedule_item, upsert_event

_DEFAULT_CALENDAR_PATH = Path(__file__).resolve().parent / "logs" / "calendar.json"
_DEFAULT_BRAIN_PATH = Path(__file__).resolve().parent / "logs" / "brain.json"

_DAY_ALIASES = {
    "monday": "mon", "mon": "mon", "mondays": "mon",
    "tuesday": "tue", "tue": "tue", "tues": "tue", "tuesdays": "tue",
    "wednesday": "wed", "wed": "wed", "wednesdays": "wed",
    "thursday": "thu", "thu": "thu", "thur": "thu", "thurs": "thu", "thursdays": "thu",
    "friday": "fri", "fri": "fri", "fridays": "fri",
    "saturday": "sat", "sat": "sat", "saturdays": "sat",
    "sunday": "sun", "sun": "sun", "sundays": "sun",
}
_DAY_NC = r"(?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)"

_CAL_TRIGGER = re.compile(
    r"(?is)\b("
    r"add\s+(?:to\s+)?(?:my\s+)?(?:calendar|schedule)|"
    r"put\s+(?:.+?\s+)?on\s+(?:my\s+)?calendar|"
    r"add\s+(?:a\s+)?(?:homework|assignment|due|exam|test|quiz|meeting|appointment|reminder)|"
    r"remind\s+me|"
    r"calendar\s+(?:add|entry)|"
    r"due\s+(?:on|by|for)|"
    r"schedule\s+(?:a|an|this)"
    r")\b"
)

_CLASS_ADD_TRIGGER = re.compile(
    r"(?is)\b("
    r"add\s+(?:a\s+)?(?:class|lecture|lab|course)|"
    r"i\s+have\s+(?:a\s+)?(?:class|lecture|lab)|"
    r"(?:school|university|uni|college)\s+(?:class|schedule)|"
    r"put\s+(?:a\s+)?(?:class|lecture)\s+on\s+(?:my\s+)?schedule|"
    r"add\s+to\s+(?:my\s+)?(?:school|university|uni|college)\s+schedule"
    r")\b"
)

_REMIND_ME = re.compile(r"(?is)\bremind\s+me\b")


def _norm_time(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if not m:
        return raw.strip()[:5] if re.match(r"^\d{1,2}:\d{2}$", s) else None
    hour = int(m.group(1))
    minute = m.group(2) or "00"
    mer = m.group(3)
    if mer == "pm" and hour < 12:
        hour += 12
    elif mer == "am" and hour == 12:
        hour = 0
    if hour > 23:
        return None
    return f"{hour:02d}:{minute}"


def _next_weekday(from_d: date, weekday: int) -> date:
    """weekday: Mon=0 .. Sun=6"""
    days_ahead = (weekday - from_d.weekday()) % 7
    if days_ahead == 0:
        return from_d
    return from_d + timedelta(days=days_ahead)


def _parse_date(text: str, *, today: date | None = None) -> date | None:
    today = today or date.today()
    t = (text or "").strip().lower()

    if re.search(r"\btoday\b", t):
        return today
    if re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1)

    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    m = re.search(
        r"\b(?:on\s+|due\s+(?:on\s+|by\s+)?)?(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b",
        t,
        re.I,
    )
    if m:
        name = m.group(2).lower()
        code = _DAY_ALIASES.get(name)
        if code:
            idx = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(code)
            d = _next_weekday(today, idx)
            if m.group(1) and d == today:
                d = d + timedelta(days=7)
            elif not m.group(1) and d == today and "due" in t:
                # "due Monday" when today is Monday → today; ok
                pass
            return d

    # Month day: March 15 / 15 March / Mar 15th
    months = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }
    m = re.search(
        r"\b(" + "|".join(months.keys()) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{2}))?\b",
        t,
        re.I,
    )
    if m:
        mo = months[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            d = date(year, mo, day)
            if d < today and not m.group(3):
                d = date(year + 1, mo, day)
            return d
        except ValueError:
            pass
    m = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(months.keys()) + r")(?:\s*,?\s*(20\d{2}))?\b",
        t,
        re.I,
    )
    if m:
        day = int(m.group(1))
        mo = months[m.group(2).lower()]
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            d = date(year, mo, day)
            if d < today and not m.group(3):
                d = date(year + 1, mo, day)
            return d
        except ValueError:
            pass
    return None


def _extract_time(text: str) -> str | None:
    m = re.search(r"\b(?:at|@)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", text, re.I)
    if m:
        return _norm_time(m.group(1))
    m = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if m:
        return _norm_time(m.group(1))
    m = re.search(r"\b(\d{1,2}\s*(?:am|pm))\b", text, re.I)
    if m:
        return _norm_time(m.group(1))
    return None


def _parse_relative_when(text: str, *, now: datetime | None = None) -> datetime | None:
    """Parse 'in 20 minutes', 'in an hour', 'tonight', etc. → local datetime."""
    now = now or datetime.now()
    t = (text or "").strip().lower()

    m = re.search(
        r"\bin\s+(?:about\s+|around\s+)?(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
        t,
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("sec"):
            return now + timedelta(seconds=n)
        if unit.startswith("min"):
            return now + timedelta(minutes=n)
        return now + timedelta(hours=n)

    if re.search(r"\bin\s+(?:about\s+|around\s+)?(?:an?\s+)?half\s+(?:an?\s+)?hour\b", t):
        return now + timedelta(minutes=30)
    if re.search(r"\bin\s+(?:about\s+|around\s+)?(?:an?\s+)?hour\b", t):
        return now + timedelta(hours=1)
    if re.search(r"\bin\s+(?:about\s+|around\s+)?(?:a\s+)?minute\b", t):
        return now + timedelta(minutes=1)

    clock = _extract_time(t)
    day = _parse_date(t, today=now.date())

    if re.search(r"\btonight\b", t) or re.search(r"\bthis\s+evening\b", t):
        day = day or now.date()
        clock = clock or "20:00"
        # If evening default already passed, nudge ~30 min from now
        try:
            probe = datetime(day.year, day.month, day.day, int((clock or "20:00")[:2]), int((clock or "20:00")[3:5]))
            if probe <= now:
                return now + timedelta(minutes=30)
        except ValueError:
            pass
    elif re.search(r"\bthis\s+afternoon\b", t):
        day = day or now.date()
        clock = clock or "15:00"
        try:
            probe = datetime(day.year, day.month, day.day, int((clock or "15:00")[:2]), int((clock or "15:00")[3:5]))
            if probe <= now:
                return now + timedelta(minutes=30)
        except ValueError:
            pass
    elif re.search(r"\bthis\s+morning\b", t):
        day = day or now.date()
        clock = clock or "09:00"
        try:
            probe = datetime(day.year, day.month, day.day, int((clock or "09:00")[:2]), int((clock or "09:00")[3:5]))
            if probe <= now:
                return now + timedelta(minutes=30)
        except ValueError:
            pass
    elif re.search(r"\bthis\s+weekend\b", t) and not day:
        # Saturday 10:00
        days_ahead = (5 - now.weekday()) % 7
        if days_ahead == 0 and now.hour >= 10:
            days_ahead = 7
        day = now.date() + timedelta(days=days_ahead)
        clock = clock or "10:00"

    if clock:
        day = day or now.date()
        try:
            hh, mm = int(clock[:2]), int(clock[3:5])
            dt = datetime(day.year, day.month, day.day, hh, mm)
            # If only a clock today and it's already past, push to tomorrow
            if day == now.date() and dt <= now and not re.search(
                r"\b(today|tonight|this\s+(?:evening|afternoon|morning))\b", t
            ):
                # "at 5pm" without day — if past, tomorrow
                if not _parse_date(t, today=now.date()) or (
                    re.search(r"\btoday\b", t) is None
                    and re.search(r"\btomorrow\b", t) is None
                    and not re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
                ):
                    if dt <= now:
                        dt = dt + timedelta(days=1)
            elif day == now.date() and dt <= now and re.search(r"\btoday\b", t):
                # explicitly today but past — keep (watcher may mark missed) or bump 1 min
                dt = now + timedelta(minutes=1)
            return dt
        except ValueError:
            return None

    if day and not clock:
        # Date-only remind → 09:00 that day
        return datetime(day.year, day.month, day.day, 9, 0)

    return None


def _clean_remind_title(text: str) -> str:
    """Extract the 'what' from remind-me phrasing."""
    t = (text or "").strip()
    t = re.sub(r"(?is)^\s*(?:hey\s+)?jarvis\s*,?\s*", "", t)
    t = re.sub(r"(?is)^\s*(?:please\s+)?(?:can\s+you\s+)?", "", t)

    # remind me [in/at WHEN] to X
    m = re.search(
        r"(?is)\bremind\s+me\b(?:\s+(?:in|at|on|tomorrow|today|tonight|"
        r"this\s+(?:evening|afternoon|morning|weekend)|"
        r"(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))"
        r"[^.]{0,40}?)?\s+to\s+(.+)$",
        t,
    )
    if m:
        t = m.group(1).strip()
    else:
        m = re.search(r"(?is)\bremind\s+me\s+(?:to\s+|about\s+|of\s+)(.+)$", t)
        if m:
            t = m.group(1).strip()
        else:
            m = re.search(r"(?is)\bremind\s+me\s+(.+)$", t)
            if m:
                t = m.group(1).strip()

    # Drop leading when-clauses still stuck on title
    t = re.sub(
        r"(?is)^\s*(?:in\s+(?:about\s+|around\s+)?\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\s+"
        r"|in\s+(?:an?\s+)?(?:half\s+)?(?:an?\s+)?(?:hour|minute)\s+"
        r"|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+"
        r"|tomorrow\s+|today\s+|tonight\s+)\s*(?:to\s+)?",
        "",
        t,
    )
    # Trailing when
    t = t.rstrip(" .,!?;:")
    t = re.sub(
        r"(?is)\s+(?:in\s+(?:about\s+|around\s+)?\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)"
        r"|in\s+(?:an?\s+)?(?:half\s+)?(?:an?\s+)?(?:hour|minute)"
        r"|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
        r"|@\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
        r"|(?:due|on|by|for|tomorrow|today|tonight|next\s+\w+"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
        r"|this\s+(?:evening|afternoon|morning|weekend)).*)$",
        "",
        t,
    )
    t = t.strip(" .,!?;:\"'-")
    return t[:160]


def _clean_title(text: str) -> str:
    if _REMIND_ME.search(text or ""):
        return _clean_remind_title(text)
    t = (text or "").strip()
    t = re.sub(r"(?is)^\s*(?:hey\s+)?jarvis\s*,?\s*", "", t)
    t = re.sub(
        r"(?is)^\s*(?:please\s+)?(?:can\s+you\s+)?"
        r"(?:add|put|schedule|create|make|set)\s+"
        r"(?:(?:a|an|the|my|this)\s+)?"
        r"(?:homework|assignment|due|exam|test|quiz|meeting|appointment|reminder|event|item)?\s*"
        r"(?:to\s+(?:my\s+)?(?:calendar|schedule)\s*)?"
        r"(?:called|titled|named|:)?\s*",
        "",
        t,
    )
    # "put dentist on my calendar tomorrow…" → dentist
    m = re.match(
        r"(?is)^\s*put\s+(.+?)\s+on\s+(?:my\s+)?calendar\b",
        text or "",
    )
    if m:
        t = m.group(1).strip()
    t = re.sub(r"(?is)^\s*remind\s+me\s+to\s+", "", t)
    t = re.sub(r"(?is)^\s*remind\s+me\s+(?:about|of)\s+", "", t)
    # Drop trailing date/time clauses
    t = re.sub(
        r"(?is)\s+(?:due|on|by|at|for|tomorrow|today|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday).*$",
        "",
        t,
    )
    t = t.strip(" .,!?;:\"'-")
    return t[:160]


def _parse_event(text: str) -> dict[str, Any] | None:
    if not _CAL_TRIGGER.search(text or ""):
        return None
    # Don't steal weekly multi-day schedule dumps
    if re.search(r"(?i)\b(entire|weekly|timetable)\s+schedule\b", text or ""):
        return None
    if re.search(r"(?i)\b(my\s+schedule|class\s+schedule)\b", text or "") and not re.search(
        r"(?i)\b(homework|due|remind|calendar|tomorrow|today)\b", text or ""
    ):
        return None

    is_remind = bool(_REMIND_ME.search(text or ""))
    rel = _parse_relative_when(text) if is_remind else None

    if rel:
        d = rel.date()
        time_s = f"{rel.hour:02d}:{rel.minute:02d}"
        remind_at = rel.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        d = _parse_date(text)
        time_s = _extract_time(text)
        remind_at = None
        if not d:
            # "add homework X" / "remind me to X" without date → today
            if is_remind or re.search(
                r"(?i)\b(homework|assignment|exam|test|quiz|reminder)\b", text or ""
            ):
                d = date.today()
            else:
                return None
        if is_remind and time_s:
            try:
                hh, mm = int(time_s[:2]), int(time_s[3:5])
                remind_at = datetime(d.year, d.month, d.day, hh, mm).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                remind_at = f"{d.isoformat()}T{time_s}:00"
        elif is_remind:
            # No clock given → about an hour from now (not a stale 09:00)
            rel_fallback = datetime.now() + timedelta(hours=1)
            d = rel_fallback.date()
            time_s = f"{rel_fallback.hour:02d}:{rel_fallback.minute:02d}"
            remind_at = rel_fallback.strftime("%Y-%m-%dT%H:%M:%S")

    title = _clean_title(text)
    if len(title) < 2:
        # fallback: grab quoted or after "called"
        m = re.search(r"['\"]([^'\"]{2,})['\"]", text or "")
        if m:
            title = m.group(1).strip()[:160]
        else:
            m = re.search(
                r"(?is)(?:homework|assignment|exam|meeting|reminder)\s+(.+?)(?:\s+due|\s+on|\s+by|\s+at|$)",
                text or "",
            )
            if m:
                title = m.group(1).strip(" .,!?;:\"'")[:160]
    if len(title) < 2:
        return None

    kind = "other"
    low = (text or "").lower()
    if re.search(r"\b(homework|assignment)\b", low):
        kind = "homework"
    elif re.search(r"\b(due|deadline)\b", low):
        kind = "due"
    elif re.search(r"\b(exam|test|quiz)\b", low):
        kind = "due"

    out: dict[str, Any] = {
        "title": title,
        "date": d.isoformat(),
        "time": time_s,
        "kind": kind,
        "source": "remind_me" if is_remind else "jarvis_fast",
    }
    if is_remind:
        out["jarvis_remind"] = True
        out["remind_at"] = remind_at
        out["notes"] = f"Jarvis will remind you: {title}"
    return out


def _parse_class_block(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None
    # Explicit class-add, or single-day class phrasing
    triggered = bool(_CLASS_ADD_TRIGGER.search(t))
    day_m = re.search(rf"\b({_DAY_NC})\b", t, re.I)
    has_time = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b|\b\d{1,2}:\d{2}\b", t, re.I))
    if not triggered and not (day_m and has_time and re.search(r"(?i)\b(class|lecture|lab|course)\b", t)):
        return None
    if not day_m:
        return None
    day = _DAY_ALIASES.get(day_m.group(1).lower())
    if not day:
        return None

    start = end = None
    range_m = re.search(
        r"(?:(?:at|from)\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        t,
        re.I,
    )
    if range_m:
        start, end = _norm_time(range_m.group(1)), _norm_time(range_m.group(2))
    else:
        start = _extract_time(t)

    # Title: after day/time or "called X" / "class X"
    title = None
    m = re.search(r"(?is)(?:called|named|titled|:)\s*([A-Za-z0-9][\w\s\-&]{1,80})", t)
    if m:
        title = m.group(1).strip(" .,;:")
    if not title:
        m = re.search(
            r"(?is)(?:class|lecture|lab|course)\s+(?:called\s+|named\s+)?([A-Za-z][\w\s\-&]{1,60}?)(?:\s+on\s+|\s+every\s+|\s+at\s+|\s+from\s+|$)",
            t,
        )
        if m:
            title = m.group(1).strip(" .,;:")
    if not title:
        # "Mondays 9am Math"
        m = re.search(
            rf"(?is){_DAY_NC}\s+(?:(?:at|from)\s+)?(?:\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?(?:\s*(?:to|-)\s*\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?)?\s+)?(.+)$",
            t,
        )
        if m:
            title = m.group(1).strip(" .,;:")
            title = re.sub(r"(?is)\b(please|thanks|thank you)\b.*$", "", title).strip(" .,;:")
            title = re.sub(
                r"(?is)^(?:i\s+have\s+)?(?:a\s+)?(?:class|lecture|lab)?\s*",
                "",
                title,
            ).strip(" .,;:")
    if not title or len(title) < 2:
        return None
    # Strip leftover time words
    title = re.sub(r"(?is)\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", "", title).strip(" .,;:-")
    title = re.sub(r"(?is)\b(on|every|at|from|to)\b", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" .,;:")
    if len(title) < 2:
        return None
    return {
        "title": title[:120],
        "day": day,
        "start": start,
        "end": end,
        "source": "jarvis_fast",
    }


def try_handle_calendar(text: str, calendar_path: Path | None = None) -> dict[str, Any] | None:
    """Local fast-path: dated calendar items OR a single weekly class block."""
    t = (text or "").strip()
    if not t:
        return None
    cp = calendar_path or _DEFAULT_CALENDAR_PATH

    # Prefer single class add when clearly a recurring class
    block = _parse_class_block(t)
    if block and not re.search(r"(?i)\b(homework|due|remind\s+me|tomorrow|today)\b", t):
        item = add_schedule_item(cp, block)
        when = "–".join(x for x in [item.get("start"), item.get("end")] if x) or "all day"
        day = (item.get("day") or "").upper()
        return {
            "text": f"Added {item['title']} to your school schedule · {day} {when}.",
            "tools": [{"name": "calendar_add_class", "preview": f"{item['title']} · {day}"}],
            "run_id": "calendar_add_class",
            "schedule_item": item,
            "count": 1,
        }

    ev_raw = _parse_event(t)
    if not ev_raw:
        # class block with homework-like words already handled above; try class anyway
        if block:
            item = add_schedule_item(cp, block)
            when = "–".join(x for x in [item.get("start"), item.get("end")] if x) or "all day"
            day = (item.get("day") or "").upper()
            return {
                "text": f"Added {item['title']} to your school schedule · {day} {when}.",
                "tools": [{"name": "calendar_add_class", "preview": f"{item['title']} · {day}"}],
                "run_id": "calendar_add_class",
                "schedule_item": item,
                "count": 1,
            }
        return None

    ev = upsert_event(cp, ev_raw)
    when = ev.get("date") or ""
    if ev.get("time"):
        when += f" at {ev['time']}"

    is_remind = bool(ev_raw.get("jarvis_remind")) or bool(_REMIND_ME.search(t))
    brain_note = None
    if is_remind:
        # Keep a Second Brain note so the reminder isn't only a calendar fire-and-forget
        try:
            from brain_store import add_idea_smart  # type: ignore
            idea = add_idea_smart(
                _DEFAULT_BRAIN_PATH,
                title=str(ev.get("title") or "Reminder")[:120],
                description=f"Remind at {when}. Set by Jarvis from: {t[:200]}",
                purpose="urgent",
            )
            brain_note = idea
            if idea and idea.get("id"):
                try:
                    ev = upsert_event(cp, {**ev, "brain_idea_id": idea["id"]})
                except Exception:
                    pass
        except Exception:
            brain_note = None

        speak_when = when
        if ev.get("remind_at"):
            try:
                dt = datetime.fromisoformat(str(ev["remind_at"]))
                delta = dt - datetime.now()
                mins = int(round(delta.total_seconds() / 60))
                if 0 <= mins < 120:
                    speak_when = f"in about {max(1, mins)} minute{'s' if mins != 1 else ''}"
                else:
                    speak_when = dt.strftime("%a %H:%M")
            except ValueError:
                pass
        msg = f"Got it — I'll remind you to {ev['title']} {speak_when}."
        if brain_note:
            msg += " Also noted in your Second Brain."
        return {
            "text": msg,
            "speak": msg,
            "tools": [{"name": "calendar_add", "preview": f"remind · {ev['title'][:40]}"}],
            "run_id": "remind_me",
            "event": ev,
            "push_phone": True,
            "brain_idea": brain_note,
            "count": 1,
        }

    return {
        "text": f"Added to your calendar: {ev['title']} · {when}.",
        "tools": [{"name": "calendar_add", "preview": f"{ev['title'][:40]} · {ev.get('date')}"}],
        "run_id": "calendar_add",
        "event": ev,
        "push_phone": True,  # server may sync Google in background
    }
