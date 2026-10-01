"""Ask before destructive or ambiguous tasks, then finish on the next reply.

Example: "I finished my grade" → ask which school classes to remove → yes clears them.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

try:
    from .calendar_store import delete_schedule_item, load as cal_load, replace_schedule, save as cal_save
except ImportError:
    from calendar_store import delete_schedule_item, load as cal_load, replace_schedule, save as cal_save

_LOGS = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
_PENDING = _LOGS / "pending_actions.json"
_TTL_SEC = 20 * 60


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_PENDING.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(data: dict[str, Any] | None) -> None:
    _PENDING.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        try:
            _PENDING.unlink(missing_ok=True)
        except Exception:
            pass
        return
    _PENDING.write_text(json.dumps(data, indent=2), encoding="utf-8")


def peek_pending() -> dict[str, Any] | None:
    data = _load()
    if not data or not data.get("kind"):
        return None
    created = float(data.get("created_at") or 0)
    if created and (time.time() - created) > _TTL_SEC:
        _save(None)
        return None
    return data


def clear_pending() -> None:
    _save(None)


def _set(kind: str, payload: dict[str, Any], question: str) -> dict[str, Any]:
    data = {
        "kind": kind,
        "payload": payload,
        "question": question,
        "created_at": time.time(),
    }
    _save(data)
    return {
        "text": question,
        "tools": [{"name": "ask_followup", "preview": kind}],
        "run_id": "followup",
        "awaiting": kind,
    }


_YES = re.compile(r"(?is)^\s*(?:yes|yeah|yep|yup|ok|okay|confirm|do it|go ahead|sure|please do|remove them|clear them|نعم|اي|ايه|زين|تمام)\s*[.!]?\s*$")
_NO = re.compile(r"(?is)^\s*(?:no|nope|cancel|stop|never mind|don't|dont|لا|خلاص)\s*[.!]?\s*$")

_FINISH_GRADE = re.compile(
    r"(?is)\b("
    r"finished?\s+(?:my\s+)?(?:grade|semester|term|year|school|university|uni|college|classes)|"
    r"done\s+with\s+(?:my\s+)?(?:grade|semester|term|school|university|uni|classes)|"
    r"graduated|dropped?\s+(?:all\s+)?(?:my\s+)?classes|"
    r"semester\s+(?:is\s+)?over|school\s+year\s+(?:is\s+)?over"
    r")\b"
)
_CLEAR_SCHOOL = re.compile(
    r"(?is)\b(?:clear|delete|remove|wipe)\b.{0,40}\b(?:school|university|uni|class(?:es)?|timetable|weekly schedule)\b"
)
_CLEAR_EVENTS = re.compile(
    r"(?is)\b(?:clear|delete|wipe|empty)\b.{0,40}\b(?:all\s+)?(?:my\s+)?(?:calendar(?:\s+events)?|events|dues|reminders)\b"
)
_CLEAR_BOTH = re.compile(
    r"(?is)\b(?:clear|delete|wipe)\b.{0,50}\b(?:everything on my calendar|calendar and (?:my )?school|school and (?:my )?calendar|all of my calendar)\b"
)
_CLEAR_BRAIN = re.compile(
    r"(?is)^\s*(?:please\s+|can you\s+)?"
    r"(?:"
    r"(?:delete|remove|clear|wipe|erase)\s+(?:all\s+)?(?:(?:my|the)\s+)?ideas?"
    r"(?:\s+from\s+(?:(?:my\s+)?(?:second\s+brain|brain|notes)))?"
    r"|(?:clear|wipe|empty|reset)\s+(?:(?:my|the)\s+)?(?:second\s+brain|brain\s+ideas?)"
    r"|delete\s+everything\s+(?:from\s+)?(?:(?:my\s+)?(?:second\s+brain|brain|notes))"
    r")\s*[.!]?\s*$"
)
_SUBMIT = re.compile(
    r"(?is)\b(?:submit|turn in|hand in|mark as done)\b.{0,40}\b(?:homework|assignment|classroom|the work|my work|it)\b"
)
_AMBIGUOUS = re.compile(
    r"(?is)^\s*(?:please\s+)?(?:delete|remove|cancel|change|move|update|open)\s+(?:it|that|those|them)\s*[.!]?\s*$"
)
_REMIND_BARE = re.compile(r"(?is)^\s*(?:please\s+)?remind\s+me\s*[.!]?\s*$")
_EMAIL_BARE = re.compile(r"(?is)^\s*(?:please\s+)?(?:send|write|draft)\s+(?:an?\s+)?e-?mail\s*[.!]?\s*$")
_TIMETABLE = re.compile(
    r"(?is)\b(?:(?:my\s+)?(?:timetable|class schedule|school schedule)\s+(?:changed|is different|updated)|"
    r"(?:i\s+)?have\s+a\s+new\s+(?:timetable|class schedule)|"
    r"update\s+my\s+(?:classes|timetable|school schedule))\b"
)
_DROP_CLASS = re.compile(
    r"(?is)\b(?:i\s+)?(?:dropped|finished|done\s+with)\s+(?:my\s+)?([A-Za-z][A-Za-z0-9 .'-]{1,40})\b|"
    r"\bremove\s+([A-Za-z][A-Za-z0-9 .'-]{1,40})\s+from\s+(?:my\s+)?(?:school|calendar|schedule|timetable)\b"
)
_NOT_SUBJECT = {
    "grade", "semester", "term", "year", "school", "university", "uni", "college",
    "classes", "class", "homework", "assignment", "work", "this", "that", "it", "them",
}


def _apply_clear_school(calendar_path: Path, titles: list[str] | None) -> dict[str, Any]:
    data = cal_load(calendar_path)
    schedule = list(data.get("schedule") or [])
    if not titles:
        replace_schedule(calendar_path, [], merge=False)
        return {
            "text": f"Removed all {len(schedule)} school schedule block(s). Calendar dues were left alone.",
            "tools": [{"name": "school_schedule_clear", "preview": "all"}],
            "run_id": "school_schedule_clear",
            "count": len(schedule),
        }
    want = {t.strip().lower() for t in titles if t.strip()}
    removed = 0
    for item in schedule:
        title = (item.get("title") or "").strip().lower()
        if title in want or any(w in title for w in want):
            if delete_schedule_item(calendar_path, item.get("id")):
                removed += 1
    return {
        "text": f"Removed {removed} matching class block(s). Say if you meant different subjects.",
        "tools": [{"name": "school_schedule_clear", "preview": ", ".join(titles)[:60]}],
        "run_id": "school_schedule_clear",
        "count": removed,
    }


def _apply_clear_events(calendar_path: Path) -> dict[str, Any]:
    data = cal_load(calendar_path)
    n = len(data.get("events") or [])
    data["events"] = []
    cal_save(calendar_path, data)
    return {
        "text": f"Removed {n} dated calendar item(s). School classes were left alone.",
        "tools": [{"name": "calendar_clear_events", "preview": "all events"}],
        "run_id": "calendar_clear_events",
        "count": n,
    }


def _apply_clear_brain(brain_path: Path) -> dict[str, Any]:
    try:
        from brain_store import clear_all_ideas, load as brain_load
    except ImportError:
        from .brain_store import clear_all_ideas, load as brain_load
    before = len((brain_load(brain_path).get("ideas") or []))
    result = clear_all_ideas(brain_path)
    n = result.get("deleted_ideas", before)
    return {
        "text": (
            f"Cleared your Second Brain — deleted {n} idea(s). Genres were kept."
            if n else "Your Second Brain had no ideas to delete."
        ),
        "tools": [{"name": "second_brain_clear_ideas", "preview": f"cleared {n}"}],
        "run_id": "brain_ideas_cleared",
        "count": n,
    }


_SCHOOL_TEXT = re.compile(
    r"(?is)\b("
    r"school|homework|assignment|classroom|timetable|semester|grade|university|college|"
    r"class(?:es)?|exam|quiz|lecture|subject|teacher|curriculum"
    r")\b"
)


def _apply_school_life_done(
    calendar_path: Path,
    memory_path: Path | None = None,
    brain_path: Path | None = None,
) -> dict[str, Any]:
    """Finished school / graduated — wipe school schedule, dues, memory, and study notes. No ask."""
    bits: list[str] = []
    total = 0

    # 1) Weekly school schedule
    data = cal_load(calendar_path)
    n_sched = len(data.get("schedule") or [])
    if n_sched:
        replace_schedule(calendar_path, [], merge=False)
        bits.append(f"cleared {n_sched} school schedule block(s)")
        total += n_sched
    else:
        bits.append("school schedule already empty")

    # 2) Homework / classroom dated events
    data = cal_load(calendar_path)
    events = list(data.get("events") or [])
    keep_events = []
    removed_events = 0
    for ev in events:
        source = (ev.get("source") or "").lower()
        kind = (ev.get("kind") or "").lower()
        blob = f"{ev.get('title') or ''} {ev.get('notes') or ''} {ev.get('class_name') or ''}"
        if (
            source == "classroom"
            or source.startswith("photo_")
            or kind in ("homework", "due", "holiday")
            or _SCHOOL_TEXT.search(blob)
        ):
            removed_events += 1
        else:
            keep_events.append(ev)
    if removed_events:
        data["events"] = keep_events
        cal_save(calendar_path, data)
        bits.append(f"removed {removed_events} school/homework calendar item(s)")
        total += removed_events

    # 3) Long-term memory school facts + recurring homework notes
    if memory_path is not None:
        try:
            from memory_store import delete_facts_matching, load as mem_load, save as mem_save
        except ImportError:
            from .memory_store import delete_facts_matching, load as mem_load, save as mem_save
        deleted = delete_facts_matching(
            memory_path,
            categories={"school"},
            keys={"school", "grade"},
        )
        mem = mem_load(memory_path)
        before = len(mem.get("facts") or [])
        mem["facts"] = [
            f for f in (mem.get("facts") or [])
            if not str(f.get("key") or "").startswith("homework_")
        ]
        extra = before - len(mem["facts"])
        if extra:
            mem_save(memory_path, mem)
        n_mem = len(deleted) + extra
        if n_mem:
            bits.append(f"forgot {n_mem} school memory note(s)")
            total += n_mem

    # 4) Second Brain study / school ideas
    if brain_path is not None:
        try:
            from brain_store import delete_ideas_matching
        except ImportError:
            from .brain_store import delete_ideas_matching
        ideas = delete_ideas_matching(
            brain_path,
            purposes={"study"},
            text_re=_SCHOOL_TEXT,
        )
        if ideas:
            bits.append(f"removed {len(ideas)} school note(s) from Second Brain")
            total += len(ideas)

    summary = "; ".join(bits) if bits else "nothing school-related left to clear"
    return {
        "text": (
            f"Got it — you're done with school. I cleaned that up automatically: {summary}."
        ),
        "tools": [{"name": "school_life_done", "preview": summary[:80]}],
        "run_id": "school_life_done",
        "count": total,
    }


def _match_subjects(titles: list[str], name: str) -> list[str]:
    want = (name or "").strip().lower()
    if not want or want in _NOT_SUBJECT:
        return []
    hits = []
    for title in titles:
        low = title.lower()
        if want == low or want in low or low in want:
            hits.append(title)
    return hits


def try_resolve_pending(
    text: str,
    calendar_path: Path | None = None,
    brain_path: Path | None = None,
    memory_path: Path | None = None,
) -> dict[str, Any] | None:
    pending = peek_pending()
    if not pending:
        return None
    t = (text or "").strip()
    if not t:
        return None
    if _NO.match(t):
        clear_pending()
        return {
            "text": "Okay — I left it as it is.",
            "tools": [{"name": "ask_followup", "preview": "cancelled"}],
            "run_id": "followup",
        }
    kind = pending.get("kind")
    cp = calendar_path or Path(__file__).resolve().parent / "logs" / "calendar.json"
    bp = brain_path or (_LOGS / "brain.json")

    if kind in ("clarify_add", "clarify_detail"):
        if _NO.match(t):
            clear_pending()
            return {
                "text": "Okay — I won't change anything.",
                "tools": [{"name": "ask_followup", "preview": "cancelled"}],
                "run_id": "followup",
            }
        clear_pending()
        return None

    if kind == "offer_solve":
        if _YES.match(t):
            clear_pending()
            try:
                from classroom_commands import try_handle_classroom
            except ImportError:
                from .classroom_commands import try_handle_classroom
            return try_handle_classroom("solve what I have due")
        return {
            "text": pending.get("question") or "I will not submit. Say yes if you want help with the questions instead.",
            "tools": [{"name": "ask_followup", "preview": "still_waiting"}],
            "run_id": "followup",
        }

    if kind == "clear_events":
        if _YES.match(t):
            clear_pending()
            return _apply_clear_events(cp)
        return {
            "text": pending.get("question") or "Should I clear the dated calendar items?",
            "tools": [{"name": "ask_followup", "preview": "still_waiting"}],
            "run_id": "followup",
        }

    if kind == "clear_both":
        if _YES.match(t):
            clear_pending()
            events = _apply_clear_events(cp)
            school = _apply_clear_school(cp, None)
            return {
                "text": f"{events['text']} {school['text']}",
                "tools": [{"name": "calendar_clear_both", "preview": "events+school"}],
                "run_id": "calendar_clear_both",
                "count": (events.get("count") or 0) + (school.get("count") or 0),
            }
        return {
            "text": pending.get("question") or "Should I clear both dated items and school classes?",
            "tools": [{"name": "ask_followup", "preview": "still_waiting"}],
            "run_id": "followup",
        }

    if kind == "clear_brain":
        if _YES.match(t):
            clear_pending()
            return _apply_clear_brain(bp)
        return {
            "text": pending.get("question") or "Should I clear the Second Brain ideas?",
            "tools": [{"name": "ask_followup", "preview": "still_waiting"}],
            "run_id": "followup",
        }

    if kind == "drop_class":
        if _YES.match(t):
            clear_pending()
            return _apply_clear_school(cp, list((pending.get("payload") or {}).get("titles") or []))
        if len(t) > 1 and not _YES.match(t):
            clear_pending()
            return None
        return {
            "text": pending.get("question") or "Should I remove that class?",
            "tools": [{"name": "ask_followup", "preview": "still_waiting"}],
            "run_id": "followup",
        }

    if kind == "clear_school_schedule":
        if _YES.match(t):
            clear_pending()
            # If this pending came from a life-change ("finished school"), do the full wipe
            if (pending.get("payload") or {}).get("life_change"):
                mp = memory_path or (_LOGS / "memory.json")
                return _apply_school_life_done(cp, mp, bp)
            return _apply_clear_school(cp, None)
        # named classes
        if len(t) > 1 and not _FINISH_GRADE.search(t):
            clear_pending()
            parts = [p.strip() for p in re.split(r",| and ", t) if p.strip()]
            return _apply_clear_school(cp, parts)
        return {
            "text": pending.get("question") or "Should I clear the school schedule?",
            "tools": [{"name": "ask_followup", "preview": "still_waiting"}],
            "run_id": "followup",
        }
    return None


def try_start_followup(
    text: str,
    calendar_path: Path | None = None,
    memory_path: Path | None = None,
    brain_path: Path | None = None,
) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None
    cp = calendar_path or Path(__file__).resolve().parent / "logs" / "calendar.json"
    mp = memory_path or (_LOGS / "memory.json")
    bp = brain_path or (_LOGS / "brain.json")
    data = cal_load(cp)
    schedule = data.get("schedule") or []
    titles = sorted({(s.get("title") or "").strip() for s in schedule if (s.get("title") or "").strip()})

    if _SUBMIT.search(t):
        return _set(
            "offer_solve",
            {},
            "I will not submit or turn in anything. Want me to open the due work, read the questions, and help you answer them instead? Say yes or no.",
        )

    if _CLEAR_BRAIN.match(t):
        ideas = 0
        try:
            raw = json.loads((_LOGS / "brain.json").read_text(encoding="utf-8"))
            ideas = len(raw.get("ideas") or [])
        except Exception:
            ideas = 0
        if not ideas:
            return {
                "text": "Your Second Brain has no ideas to delete.",
                "tools": [{"name": "ask_followup", "preview": "empty"}],
                "run_id": "followup",
            }
        return _set(
            "clear_brain",
            {},
            f"You have {ideas} idea(s) in the Second Brain. Should I delete all of them? Genres stay. Reply yes or no.",
        )

    if _CLEAR_BOTH.search(t):
        events_n = len(data.get("events") or [])
        return _set(
            "clear_both",
            {},
            f"Clear both — {events_n} dated item(s) and {len(titles)} school class(es)? Reply yes or no.",
        )

    dropped = _DROP_CLASS.search(t)
    if dropped and not _FINISH_GRADE.search(t):
        name = (dropped.group(1) or dropped.group(2) or "").strip(" .")
        hits = _match_subjects(titles, name)
        if hits:
            listed = ", ".join(hits[:6])
            return _set(
                "drop_class",
                {"titles": hits},
                f"Remove {listed} from the school calendar? Other classes stay. Reply yes or no.",
            )

    # Life change: finished school / graduated → auto-purge (no confirmation)
    if _FINISH_GRADE.search(t):
        return _apply_school_life_done(cp, mp, bp)

    # Explicit "clear my school schedule" still confirms
    if _CLEAR_SCHOOL.search(t):
        if not titles:
            return {
                "text": "Your school schedule is already empty — nothing to remove.",
                "tools": [{"name": "ask_followup", "preview": "empty"}],
                "run_id": "followup",
            }
        listed = ", ".join(titles[:12])
        q = (
            f"You have {len(titles)} subject(s) on the school calendar: {listed}. "
            "Should I remove all of them? Reply yes, no, or name the ones to remove."
        )
        return _set("clear_school_schedule", {"titles": titles}, q)

    if _CLEAR_EVENTS.search(t) and not _CLEAR_SCHOOL.search(t):
        events_n = len(data.get("events") or [])
        if not events_n:
            return {
                "text": "There are no dated calendar items to remove. School classes were left alone.",
                "tools": [{"name": "ask_followup", "preview": "empty"}],
                "run_id": "followup",
            }
        return _set(
            "clear_events",
            {},
            f"Remove all {events_n} dated calendar item(s)? School classes stay. Reply yes or no.",
        )

    if _TIMETABLE.search(t) and len(t) < 180:
        listed = ", ".join(titles[:8]) or "none yet"
        return _set(
            "clarify_detail",
            {},
            f"Your school calendar currently has: {listed}. What changed — which classes to add, remove, or replace? You can paste the new week.",
        )

    if _AMBIGUOUS.match(t):
        return _set(
            "clarify_detail",
            {},
            "Which one — a school class, a dated calendar item, a Classroom assignment, or something else? Say the name.",
        )
    if _REMIND_BARE.match(t):
        return _set(
            "clarify_detail",
            {},
            "Remind you about what, and when? For example: remind me Friday at 4 about math homework.",
        )
    if _EMAIL_BARE.match(t):
        return _set(
            "clarify_detail",
            {},
            "Who should the email be to, and what should it say? I will draft it in chat and will not send it.",
        )

    # Ambiguous "add it" without an object — ask, don't guess
    if re.fullmatch(r"(?is)\s*(?:please\s+)?add\s+(?:it|that|those|them)(?:\s+to\s+(?:my\s+)?(?:calendar|schedule))?\s*[.!]?\s*", t):
        return _set(
            "clarify_add",
            {},
            "Add what — a homework due date, a class on the school timetable, or the Classroom items I last saw? Tell me which.",
        )
    return None
