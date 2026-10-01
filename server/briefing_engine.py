"""Daily Briefing Engine for Jarvis.

Synthesizes today's schedule, calendar dues, Second Brain notes/ideas, and system
readiness into a professional spoken briefing delivered on-demand or on PC boot/restart.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from calendar_store import load as load_calendar
from brain_store import load as load_brain, PURPOSE_DEFINITIONS

KOKORO_BASE = os.environ.get("JARVIS_VOICE_URL", "http://127.0.0.1:8880/v1").rstrip("/")
KOKORO_VOICE = os.environ.get("JARVIS_VOICE", "bm_george")

_BRIEFING_TRIGGERS = [
    r"\b(?:give\s+me\s+(?:a\s+|my\s+)?|what\s+is\s+my\s+|my\s+)?(?:daily\s+|morning\s+|today'?s\s+)?briefing\b",
    r"\b(?:what\s+do\s+i\s+have(?:\s+for|\s+on|\s+today|\s+scheduled)?|what'?s\s+(?:on\s+)?my\s+schedule\s+today|what'?s\s+my\s+schedule)\b",
    r"\b(?:brief\s+me(?:\s+on\s+today|\s+on\s+my\s+day)?)\b",
    r"\b(?:how\s+does\s+my\s+day\s+look|how\s+is\s+my\s+day\s+looking)\b",
    r"\b(?:schedule\s+for\s+today|today'?s\s+schedule|today'?s\s+agenda)\b",
    r"\b(?:any\s+)?(?:upcoming\s+)?holidays?\b",
    r"\b(?:when\s+(?:is|does)\s+(?:my\s+)?(?:next\s+)?holiday|when\s+does\s+(?:the\s+)?(?:holiday|break)\s+end)\b",
]

DAY_MAP_REV = {
    0: "mon",
    1: "tue",
    2: "wed",
    3: "thu",
    4: "fri",
    5: "sat",
    6: "sun",
}

DAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def is_briefing_intent(text: str) -> bool:
    """Check if the user is asking for their daily briefing or schedule."""
    t = (text or "").lower().strip()
    return any(re.search(pat, t, re.I) for pat in _BRIEFING_TRIGGERS)


def format_time_spoken(time_str: str | None) -> str:
    """Format HH:MM into spoken time, e.g. 09:00 -> 9:00 AM, 14:30 -> 2:30 PM."""
    if not time_str:
        return ""
    m = re.match(r"^(\d{1,2}):(\d{2})$", time_str.strip())
    if not m:
        return time_str
    h = int(m.group(1))
    minute = m.group(2)
    meridiem = "AM" if h < 12 else "PM"
    h12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
    return f"{h12}:{minute} {meridiem}" if minute != "00" else f"{h12} {meridiem}"


def build_briefing_data(
    calendar_path: Path,
    brain_path: Path,
    now_dt: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Gather all components needed for the briefing."""
    now = now_dt or datetime.datetime.now()
    hour = now.hour
    day_code = DAY_MAP_REV.get(now.weekday(), "mon")
    day_name = DAY_NAMES.get(day_code, "Today")
    date_str = now.strftime("%B %d, %Y")

    if hour < 12:
        greeting = "Good morning, sir."
    elif hour < 17:
        greeting = "Good afternoon, sir."
    else:
        greeting = "Good evening, sir."

    # 1. Today's Weekly Schedule
    cal_data = load_calendar(calendar_path)
    all_schedule = cal_data.get("schedule") or []
    today_schedule = [s for s in all_schedule if s.get("day") == day_code]

    # Sort by start time
    today_schedule.sort(key=lambda s: str(s.get("start") or "99:99"))

    # 2. Upcoming Dated Events / Dues (non-holiday)
    all_events = cal_data.get("events") or []
    today_iso = now.strftime("%Y-%m-%d")
    tomorrow_iso = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    upcoming_events = [
        e for e in all_events
        if e.get("date") in (today_iso, tomorrow_iso)
        and (e.get("kind") or "").lower() != "holiday"
    ]

    # 2b. Holidays: starting soon OR currently ongoing and ending soon
    holidays = [e for e in all_events if (e.get("kind") or "").lower() == "holiday"]
    horizon_start = (now + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
    upcoming_holidays = []
    ending_holidays = []
    for h in holidays:
        start = str(h.get("date") or "")
        end = str(h.get("end_date") or h.get("date") or "")
        if today_iso <= start <= horizon_start:
            upcoming_holidays.append(h)
        # Ongoing break whose last day is within 3 days
        if start <= today_iso <= end:
            try:
                end_dt = datetime.datetime.strptime(end, "%Y-%m-%d").date()
                days_left = (end_dt - now.date()).days
                if 0 <= days_left <= 3:
                    ending_holidays.append((h, days_left))
            except Exception:
                pass
        elif today_iso < start:
            pass
        else:
            # end date approaching even if we missed start tracking
            try:
                end_dt = datetime.datetime.strptime(end, "%Y-%m-%d").date()
                days_left = (end_dt - now.date()).days
                if 0 <= days_left <= 3 and start <= today_iso:
                    ending_holidays.append((h, days_left))
            except Exception:
                pass

    upcoming_holidays.sort(key=lambda e: str(e.get("date") or ""))
    ending_holidays.sort(key=lambda pair: pair[1])

    # 3. Second Brain Ideas / Notes
    brain_data = load_brain(brain_path)
    ideas = brain_data.get("ideas") or []
    genres = {g["id"]: g for g in brain_data.get("genres") or []}

    urgent_ideas = []
    recent_ideas = []
    for idea in reversed(ideas):
        g = genres.get(idea.get("genre_id")) or {}
        p = (idea.get("purpose") or g.get("purpose") or "").lower()
        if p == "urgent" or "urgent" in (idea.get("title") or "").lower():
            urgent_ideas.append(idea)
        elif len(recent_ideas) < 3:
            recent_ideas.append(idea)

    # 4. Synthesize spoken prose
    spoken_parts = [f"{greeting} Today is {day_name}, {now.strftime('%B %d')}."]

    # Schedule report
    if today_schedule:
        count = len(today_schedule)
        items_spoken = []
        for s in today_schedule:
            t = format_time_spoken(s.get("start"))
            title = s.get("title")
            if t:
                items_spoken.append(f"{title} at {t}")
            else:
                items_spoken.append(title)
        spoken_parts.append(
            f"On your schedule today, you have {count} item{'s' if count > 1 else ''}: "
            f"{', then '.join(items_spoken)}."
        )
    else:
        spoken_parts.append("You have no scheduled classes or timetable blocks for today. It is a clear day.")

    # Events / dues report (never call holidays "homework")
    if upcoming_events:
        event_titles = [e.get("title") for e in upcoming_events[:3]]
        spoken_parts.append(
            f"In your calendar, you have {len(upcoming_events)} dated item{'s' if len(upcoming_events) != 1 else ''} soon: "
            f"{', '.join(event_titles)}."
        )

    # Holiday reminders
    if upcoming_holidays:
        bits = []
        for h in upcoming_holidays[:4]:
            title = h.get("title") or "holiday"
            start = h.get("date")
            end = h.get("end_date")
            if end and end != start:
                bits.append(f"{title} from {start} to {end}")
            else:
                bits.append(f"{title} on {start}")
        spoken_parts.append(
            f"Holiday reminder: {', '.join(bits)}."
        )
    if ending_holidays:
        bits = []
        for h, days_left in ending_holidays[:3]:
            title = h.get("title") or "holiday"
            if days_left == 0:
                bits.append(f"{title} ends today")
            elif days_left == 1:
                bits.append(f"{title} ends tomorrow")
            else:
                bits.append(f"{title} ends in {days_left} days")
        spoken_parts.append(
            f"Heads up — your break is almost over: {', '.join(bits)}."
        )

    # Notes / Second brain report
    if urgent_ideas:
        spoken_parts.append(
            f"Attention on urgent notes in your second brain: {urgent_ideas[0].get('title')}."
        )
    elif recent_ideas:
        first_idea = recent_ideas[0]
        spoken_parts.append(
            f"You have {len(ideas)} active notes in your second brain, including '{first_idea.get('title')}'."
        )

    spoken_parts.append("All system connections, your local autonomous mind, and NotebookLM are online and standing by.")

    spoken_text = " ".join(spoken_parts)

    return {
        "greeting": greeting,
        "day_name": day_name,
        "date_str": date_str,
        "today_schedule": today_schedule,
        "upcoming_events": upcoming_events,
        "upcoming_holidays": upcoming_holidays,
        "ending_holidays": [{"event": h, "days_left": d} for h, d in ending_holidays],
        "ideas_count": len(ideas),
        "urgent_ideas": urgent_ideas,
        "recent_ideas": recent_ideas,
        "spoken_text": spoken_text,
    }


def generate_briefing_audio(
    text: str,
    output_path: Path | None = None,
    timeout: float = 30.0,
) -> Path | None:
    """Generate TTS audio via Kokoro and optionally save to file."""
    url = f"{KOKORO_BASE}/audio/speech"
    payload = json.dumps({
        "model": "kokoro",
        "input": text,
        "voice": KOKORO_VOICE,
        "response_format": "mp3",
        "speed": 1.12,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            audio_bytes = resp.read()
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(audio_bytes)
                return output_path
    except Exception as exc:
        print(f"generate_briefing_audio error: {exc}", flush=True)

    return None


def play_audio_file(audio_path: Path) -> bool:
    """Play an audio file directly through PC speakers on Windows."""
    try:
        # PowerShell SoundPlayer for .wav or Windows Media Player for .mp3
        p = str(audio_path.resolve())
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"""
            Add-Type -AssemblyName presentationCore;
            $mediaPlayer = New-Object system.windows.media.mediaplayer;
            $mediaPlayer.open([System.Uri]'{p}');
            $mediaPlayer.Play();
            Start-Sleep -Seconds 1;
            while ($mediaPlayer.NaturalDuration.HasTimeSpan -eq $false -or $mediaPlayer.Position -lt $mediaPlayer.NaturalDuration.TimeSpan) {{
                Start-Sleep -Milliseconds 250;
            }}
            """,
        ]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        print(f"play_audio_file error: {exc}", flush=True)
        return False


def try_handle_briefing(
    text: str,
    calendar_path: Path,
    brain_path: Path,
) -> dict[str, Any] | None:
    """Handle on-demand briefing queries from voice or chat."""
    if not is_briefing_intent(text):
        return None

    data = build_briefing_data(calendar_path, brain_path)
    spoken_text = data["spoken_text"]

    # Pre-render boot audio file in background thread so file is ready for boot/HUD
    boot_audio_path = Path(__file__).resolve().parent / "hud" / "audio" / "boot_briefing.mp3"
    import threading
    threading.Thread(
        target=generate_briefing_audio,
        args=(spoken_text, boot_audio_path, 40.0),
        daemon=True,
    ).start()

    return {
        "ok": True,
        "text": spoken_text,
        "spoken": spoken_text,
        "data": {
            "day": data["day_name"],
            "schedule": data["today_schedule"],
            "events": data["upcoming_events"],
            "ideas_count": data["ideas_count"],
        },
        "tools": [{
            "name": "daily_briefing",
            "preview": f"Daily Briefing ({data['day_name']}): {len(data['today_schedule'])} classes, {data['ideas_count']} notes",
        }],
        "run_id": "daily_briefing",
        "hud_url": "/hud/calendar.html",
    }
