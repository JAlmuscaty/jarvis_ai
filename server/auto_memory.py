"""Auto-extract lasting personal facts from user chat/voice and save to memory.

Also mirrors notable life facts into the Second Brain (ideas graph) silently —
never ask whether it "helps"; just save and briefly acknowledge when relevant.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from memory_store import phone_digits, upsert_fact

# Skip obvious commands — not autobiographical facts
_CMD = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"open|close|launch|start|stop|play|pause|search|google|navigate|go to|"
    r"show|hide|delete|remove|send|type|click|scroll|look|check|status|"
    r"whatsapp|youtube|chatgpt|calendar|schedule|summon|dismiss|"
    r"clear|wipe|forget|connect|disconnect"
    r")\b",
    re.I,
)

_NAME = r"([A-Za-z][a-zA-Z]{1,24}(?:\s+[A-Za-z][a-zA-Z]{1,24})?)"
_PHONE = r"(\+?\d[\d\s\-()]{6,22}\d)"

# (compiled pattern, handler) — handler(m) -> dict for upsert_fact or None
_RULES: list[tuple[re.Pattern[str], Any]] = []

# Facts with these flags also get a Second Brain idea
_MIRROR_CATEGORIES = {"school", "preferences", "media", "habits"}


def _add(pattern: str, handler, flags: int = re.I) -> None:
    _RULES.append((re.compile(pattern, flags), handler))


_NOT_NAME = {
    "watching", "going", "doing", "reading", "playing", "listening", "studying",
    "working", "having", "getting", "feeling", "thinking", "looking", "waiting",
    "trying", "using", "making", "taking", "coming", "leaving", "finished", "done",
    "into", "the", "a", "an", "my", "your", "his", "her", "their", "watching the",
    "watching anime", "watching show", "currently", "actually", "just", "also",
}


def _clean_name(s: str) -> str:
    s = (s or "").strip(" .,!?;:'\"")
    # Drop trailing filler words STT sometimes glues on
    s = re.sub(r"\s+(number|phone|whatsapp|is|named)$", "", s, flags=re.I).strip()
    if s and " " not in s:
        s = s[:1].upper() + s[1:].lower()
    return s[:80]


def _is_plausible_person_name(s: str) -> bool:
    low = (s or "").strip().lower()
    if not low or low in _NOT_NAME:
        return False
    first = low.split()[0]
    if first in _NOT_NAME:
        return False
    if re.match(
        r"^(watch|go|do|read|play|listen|study|work|have|get|feel|think|look|"
        r"wait|try|use|make|take|come|leave|finish|start|stop|open|close)(ing|ed)?$",
        first,
    ):
        return False
    return True


def _person_name_fact(title: str, name: str, key: str) -> dict | None:
    name = _clean_name(name)
    if not _is_plausible_person_name(name):
        return None
    return {
        "title": title,
        "value": name,
        "key": key,
        "category": "people" if key != "my_name" else "personal",
        "whatsapp_name": name if key != "my_name" else None,
        "source": "auto",
    }


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:50] or "fact"


def _phone_fact(who: str, number: str) -> dict | None:
    digits = phone_digits(number)
    if not digits:
        return None
    who = _clean_name(who)
    if not who or who.lower() in ("number", "phone", "the", "a"):
        return None
    display = "+" + digits if not str(number).strip().startswith("+") else str(number).strip()
    display = display if display.startswith("+") else ("+" + digits)
    return {
        "title": who,
        "value": who,
        "key": f"contact_{who.lower().replace(' ', '_')}",
        "category": "people",
        "phone": display,
        "whatsapp_name": who,
        "source": "auto",
    }


def _media_fact(kind: str, title: str) -> dict | None:
    title = (title or "").strip(" .,!?;:'\"")
    title = re.sub(r"\s+(right now|currently|these days|lately)$", "", title, flags=re.I).strip()
    if len(title) < 2 or len(title) > 120:
        return None
    kind = (kind or "show").strip().lower()
    return {
        "title": f"Watching ({kind})",
        "value": title[:200],
        "key": f"watching_{_slug(kind)}",
        "category": "media",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "media",
        "brain_title": f"Watching: {title[:80]}",
    }


def _habit_fact(subject: str, cadence: str) -> dict | None:
    subject = (subject or "").strip(" .,!?;:'\"")
    subject = re.sub(r"\s+(homework|assignment|hw)\s*$", "", subject, flags=re.I).strip()
    if len(subject) < 2:
        return None
    cadence = (cadence or "week").strip().lower()
    value = f"{subject} homework every {cadence}"
    return {
        "title": f"Recurring: {subject[:40]}",
        "value": value[:200],
        "key": f"homework_{_slug(subject)}",
        "category": "school",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "study",
        "brain_title": value[:80],
    }


# Friend / relationship names  (friends / friend's / friend)
_add(
    rf"\bmy\s+(?:best\s+)?friends?'?\s*name\s+is\s+{_NAME}\b",
    lambda m: _person_name_fact("Best friend", m.group(1), "best_friend"),
)
_add(
    rf"\bmy\s+(?:best\s+)?friend(?:'s)?\s+name\s+is\s+{_NAME}\b",
    lambda m: _person_name_fact("Best friend", m.group(1), "best_friend"),
)
_add(
    rf"\bmy\s+(?:best\s+)?friend\s+is\s+{_NAME}\b",
    lambda m: _person_name_fact("Best friend", m.group(1), "best_friend"),
)
_add(
    rf"\b{_NAME}\s+is\s+my\s+(?:best\s+)?friend\b",
    lambda m: _person_name_fact("Best friend", m.group(1), "best_friend"),
)
_add(
    rf"\bmy\s+(mom|dad|mother|father|brother|sister|girlfriend|boyfriend|wife|husband|"
    rf"cousin|uncle|aunt|roommate|classmate)(?:'s)?\s+name\s+is\s+{_NAME}\b",
    lambda m: _person_name_fact(m.group(1).capitalize(), m.group(2), m.group(1).lower()),
)
_add(
    rf"\bmy\s+(mom|dad|mother|father|brother|sister|girlfriend|boyfriend|wife|husband)\s+is\s+{_NAME}\b",
    lambda m: _person_name_fact(m.group(1).capitalize(), m.group(2), m.group(1).lower()),
)

# User identity
_add(
    rf"\b(?:my\s+name\s+is|i\s+am|i'm|call\s+me)\s+{_NAME}\b",
    lambda m: _person_name_fact("My name", m.group(1), "my_name"),
)

# Phone numbers for a person
_add(
    rf"\b{_NAME}(?:'s)?\s+(?:phone\s+)?number\s+is\s+{_PHONE}",
    lambda m: _phone_fact(m.group(1), m.group(2)),
)
_add(
    rf"\b(?:the\s+)?(?:phone\s+)?number\s+(?:for|of)\s+{_NAME}\s+is\s+{_PHONE}",
    lambda m: _phone_fact(m.group(1), m.group(2)),
)
_add(
    rf"\b{_NAME}\s*(?:'|’)?s\s+(?:phone\s+)?number\s*(?:is|=|:)?\s*{_PHONE}",
    lambda m: _phone_fact(m.group(1), m.group(2)),
)

# Explicit remember
_add(
    r"\b(?:please\s+)?remember(?:\s+that)?\s+(.+?)(?:[.!]|$)",
    lambda m: {
        "title": m.group(1).strip()[:60],
        "value": m.group(1).strip()[:800],
        "key": None,
        "category": "personal",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "notes",
        "brain_title": m.group(1).strip()[:80],
    },
)

# School / place / preference
_add(
    r"\bi\s+(?:go\s+to|attend|study\s+at)\s+(.+?)(?:[.!]|$)",
    lambda m: {
        "title": "School",
        "value": m.group(1).strip()[:200],
        "key": "school",
        "category": "school",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "study",
        "brain_title": f"School: {m.group(1).strip()[:60]}",
    },
)
_add(
    r"\bmy\s+(?:school|university|uni|college)\s+is\s+(.+?)(?:[.!]|$)",
    lambda m: {
        "title": "School",
        "value": m.group(1).strip()[:200],
        "key": "school",
        "category": "school",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "study",
        "brain_title": f"School: {m.group(1).strip()[:60]}",
    },
)
_add(
    r"\bi(?:'m| am)\s+in\s+(?:grade|year|class)\s+([0-9A-Za-z]{1,12})\b",
    lambda m: {
        "title": "Grade",
        "value": m.group(1).strip()[:40],
        "key": "grade",
        "category": "school",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "study",
        "brain_title": f"Grade {m.group(1).strip()[:20]}",
    },
)
_add(
    r"\bi\s+live\s+(?:in|at)\s+(.+?)(?:[.!]|$)",
    lambda m: {
        "title": "Home",
        "value": m.group(1).strip()[:200],
        "key": "home",
        "category": "personal",
        "source": "auto",
    },
)
_add(
    r"\bmy\s+favorite\s+(.+?)\s+is\s+(.+?)(?:[.!]|$)",
    lambda m: {
        "title": f"Favorite {m.group(1).strip()[:40]}",
        "value": m.group(2).strip()[:200],
        "key": f"favorite_{_slug(m.group(1))}",
        "category": "preferences",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "personal",
        "brain_title": f"Favorite {m.group(1).strip()[:30]}: {m.group(2).strip()[:40]}",
    },
)
_add(
    r"\bi\s+prefer\s+(.+?)(?:[.!]|$)",
    lambda m: {
        "title": "Preference",
        "value": m.group(1).strip()[:200],
        "key": f"prefer_{_slug(m.group(1))}",
        "category": "preferences",
        "source": "auto",
        "mirror_brain": True,
        "brain_purpose": "personal",
        "brain_title": f"Preference: {m.group(1).strip()[:60]}",
    },
)

# Watching anime / TV / shows (user example)
_add(
    r"\bi(?:'m| am)\s+(?:currently\s+)?watching\s+(?:the\s+)?(?:anime|show|series|tv\s*show)?\s*(.+?)(?:[.!]|$)",
    lambda m: _media_fact("show", m.group(1)),
)
_add(
    r"\bi\s+watch\s+(?:the\s+)?(anime|show|series|tv\s*show)\s+(.+?)(?:[.!]|$)",
    lambda m: _media_fact(m.group(1), m.group(2)),
)
_add(
    r"\bmy\s+(?:current\s+)?(anime|show|series|tv\s*show)\s+(?:is|i(?:'m| am)\s+watching)\s+(.+?)(?:[.!]|$)",
    lambda m: _media_fact(m.group(1), m.group(2)),
)
_add(
    r"\bi(?:'m| am)\s+into\s+(?:the\s+)?(anime|show|series)\s+(.+?)(?:[.!]|$)",
    lambda m: _media_fact(m.group(1), m.group(2)),
)

# Recurring homework (user example: every week Arabic homework)
_add(
    r"\bevery\s+(week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|day)\s+"
    r"i\s+have\s+(?:an?\s+)?(.+?)\s+(?:homework|assignment|hw)\b",
    lambda m: _habit_fact(m.group(2), m.group(1)),
)
_add(
    r"\bi\s+have\s+(?:an?\s+)?(.+?)\s+(?:homework|assignment|hw)\s+every\s+"
    r"(week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|day)\b",
    lambda m: _habit_fact(m.group(1), m.group(2)),
)
_add(
    r"\bi\s+(?:always|usually)\s+have\s+(?:an?\s+)?(.+?)\s+(?:homework|assignment|hw)\b",
    lambda m: _habit_fact(m.group(1), "week"),
)

# WhatsApp display name
_add(
    rf"\b{_NAME}(?:'s)?\s+whatsapp\s+name\s+is\s+(.+?)(?:[.!]|$)",
    lambda m: {
        "title": _clean_name(m.group(1)),
        "value": _clean_name(m.group(1)),
        "key": f"contact_{_clean_name(m.group(1)).lower().replace(' ', '_')}",
        "category": "people",
        "whatsapp_name": m.group(2).strip()[:120],
        "source": "auto",
    },
)


def extract_candidates(text: str) -> list[dict]:
    t = (text or "").strip()
    if not t or len(t) < 8:
        return []
    if _CMD.search(t):
        return []
    # Ignore slash commands / life-change wipe phrases (handled elsewhere)
    if t.startswith("/"):
        return []
    if re.search(
        r"(?is)\b(?:finished?\s+(?:my\s+)?(?:grade|school|semester)|graduated|done\s+with\s+(?:my\s+)?school)\b",
        t,
    ):
        return []
    found: list[dict] = []
    seen_keys: set[str] = set()
    seen_phones: set[str] = set()
    for rx, handler in _RULES:
        for m in rx.finditer(t):
            try:
                fact = handler(m)
            except Exception:
                continue
            if not fact or not fact.get("value"):
                continue
            if fact.get("key") is None:
                fact.pop("key", None)
            key = (fact.get("key") or fact.get("title") or fact["value"]).lower()
            phone = phone_digits(fact.get("phone"))
            if key in seen_keys:
                continue
            if phone and phone in seen_phones:
                continue
            seen_keys.add(key)
            if phone:
                seen_phones.add(phone)
            found.append(fact)
    return found


def _mirror_to_brain(brain_path: Path, raw: dict, saved: dict) -> dict | None:
    """Quietly upsert a matching Second Brain idea for notable life facts."""
    if not brain_path:
        return None
    should = bool(raw.get("mirror_brain")) or (saved.get("category") or "") in _MIRROR_CATEGORIES
    if not should:
        return None
    try:
        from brain_store import add_idea_smart, load as brain_load, upsert_idea
    except ImportError:
        from .brain_store import add_idea_smart, load as brain_load, upsert_idea

    title = (raw.get("brain_title") or saved.get("title") or saved.get("value") or "Note").strip()[:120]
    desc = (saved.get("value") or title).strip()[:800]
    purpose = (raw.get("brain_purpose") or (
        "study" if saved.get("category") == "school"
        else "media" if saved.get("category") == "media"
        else "personal" if saved.get("category") in ("preferences", "habits")
        else "notes"
    ))
    # Update existing idea with same title (case-insensitive) instead of duplicating
    data = brain_load(brain_path)
    existing = next(
        (i for i in (data.get("ideas") or []) if (i.get("title") or "").strip().lower() == title.lower()),
        None,
    )
    if existing:
        return upsert_idea(
            brain_path,
            {
                "id": existing.get("id"),
                "title": title,
                "description": desc,
                "purpose": purpose,
                "genre_id": existing.get("genre_id"),
            },
        )
    return add_idea_smart(brain_path, title=title, description=desc, purpose=purpose)


def auto_save_from_text(
    path: Path,
    text: str,
    brain_path: Path | None = None,
) -> list[dict]:
    """Parse user utterance, upsert memory facts, and mirror to Second Brain when useful."""
    saved: list[dict] = []
    for raw in extract_candidates(text):
        try:
            # Strip helper flags before normalize (unknown fields are ignored anyway,
            # but keep a clean copy for mirroring)
            mirror_meta = {
                "mirror_brain": raw.get("mirror_brain"),
                "brain_purpose": raw.get("brain_purpose"),
                "brain_title": raw.get("brain_title"),
                "category": raw.get("category"),
            }
            fact = upsert_fact(path, raw)
            saved.append(fact)
            if brain_path is not None:
                try:
                    idea = _mirror_to_brain(brain_path, {**raw, **mirror_meta}, fact)
                    if idea:
                        fact = dict(fact)
                        fact["brain_idea_id"] = idea.get("id")
                        saved[-1] = fact
                except Exception:
                    pass
        except Exception:
            continue
    return saved
