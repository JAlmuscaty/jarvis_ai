"""Hard-route Second Brain idea & notes commands so Jarvis saves ideas instantly."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from .brain_store import PURPOSE_DEFINITIONS, add_idea_smart, detect_purpose
except ImportError:
    from brain_store import PURPOSE_DEFINITIONS, add_idea_smart, detect_purpose

# Path to brain.json in server logs
_DEFAULT_BRAIN_PATH = Path(__file__).resolve().parent / "logs" / "brain.json"

# Patterns indicating an idea or note command
_IDEA_PATTERNS = [
    # "i have an idea: ...", "i got an idea ..."
    r"^\s*(?:hey\s+)?(?:jarvis\s*,?\s*)?(?:i\s+have|i've\s+got|here\s+is|got)\s+(?:(?:this|a\s+new|an|a)\s+)?(?:[a-z]+\s+)?(?:idea|note)\s*[:\-,\s]\s*(.+)$",
    # "add an idea ...", "add an urgent idea to my second brain ..."
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?add\s+(?:(?:this|a\s+new|an|a)\s+)?(?:[a-z]+\s+)?(?:idea|note)(?:\s+to\s+(?:my\s+)?(?:notes|second\s+brain|brain))?\s*[:\-,\s]\s*(.+)$",
    # "add to my second brain: ...", "add to second brain: ..."
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?add\s+(?:this\s+)?to\s+(?:my\s+)?(?:second\s+brain|brain|notes)\s*[:\-,\s]\s*(.+)$",
    # "save this idea ...", "save idea ..."
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?save\s+(?:(?:this|a\s+new|an|a)\s+)?(?:[a-z]+\s+)?(?:idea|note)(?:\s+to\s+(?:my\s+)?(?:notes|second\s+brain|brain))?\s*[:\-,\s]\s*(.+)$",
    # "note down this idea ...", "note down an idea ..."
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?(?:note|write)\s+down\s+(?:(?:this|a\s+new|an|a)\s+)?(?:[a-z]+\s+)?(?:idea|note)(?:\s+to\s+(?:my\s+)?(?:notes|second\s+brain|brain))?\s*[:\-,\s]\s*(.+)$",
    # "put this in my second brain ..."
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?put\s+(?:this\s+)?(?:in|into)\s+(?:my\s+)?(?:second\s+brain|brain|notes)\s*[:\-,\s]\s*(.+)$",
    # "second brain: ..." / "notes: ..."
    r"^\s*(?:second\s+brain|notes|idea)\s*[:\-]\s*(.+)$",
]


def _extract_idea(text: str) -> tuple[str, str | None, str | None] | None:
    """Extract (title, description, explicit_purpose) from user phrasing."""
    t = (text or "").strip()
    if not t:
        return None

    raw_content = None
    for pat in _IDEA_PATTERNS:
        m = re.match(pat, t, re.I)
        if m:
            raw_content = m.group(1).strip()
            break

    if not raw_content:
        # Check if text contains explicit "add idea <X>"
        m2 = re.search(r"\b(?:add|save|note\s+down)\s+(?:this\s+|the\s+)?idea\s+([A-Za-z0-9].+)$", t, re.I)
        if m2:
            raw_content = m2.group(1).strip()

    if not raw_content:
        return None

    # Drop trailing conversational filler
    raw_content = re.sub(r"\b(please|thank you|thanks)\b[.!]?$", "", raw_content, flags=re.I).strip(" .,!?;:\"'")
    if not raw_content:
        return None

    # Check for explicit purpose tag in content, e.g. "for study: ...", "project: ..."
    explicit_purpose = None
    for pid, meta in PURPOSE_DEFINITIONS.items():
        if re.search(rf"\b(?:for|under|category)\s+{pid}\b", raw_content, re.I) or re.search(rf"\b{pid}\s+idea\b", raw_content, re.I):
            explicit_purpose = pid
            raw_content = re.sub(rf"\b(?:for|under|category)\s+{pid}\b", "", raw_content, flags=re.I).strip()
            raw_content = re.sub(rf"\b{pid}\s+idea\b", "", raw_content, flags=re.I).strip()
            break

    # Split title vs description if there's a delimiter like " - " or ": " or " details: "
    title = raw_content
    desc = None
    for delim in (" - ", " : ", ": ", " — ", " details: ", " note: ", " because "):
        if delim in raw_content:
            parts = raw_content.split(delim, 1)
            title = parts[0].strip()
            desc = parts[1].strip()
            break

    if not title:
        title = raw_content[:80]

    return title[:120], desc, explicit_purpose


_CLEAR_ALL_RE = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+)?"
    r"(?:"
    r"(?:delete|remove|clear|wipe|erase)\s+(?:all\s+)?(?:(?:my|the)\s+)?ideas?"
    r"(?:\s+from\s+(?:(?:my\s+)?(?:second\s+brain|brain|notes)))?"
    r"|(?:clear|wipe|empty|reset)\s+(?:(?:my|the)\s+)?(?:second\s+brain|brain\s+ideas?)"
    r"|delete\s+everything\s+(?:from\s+)?(?:(?:my\s+)?(?:second\s+brain|brain|notes))"
    r")\s*[.!]?\s*$",
    re.I,
)


def try_handle_brain_clear(text: str, brain_path: Path | None = None) -> dict[str, Any] | None:
    """Hard-route 'delete all ideas' / 'clear second brain'."""
    t = (text or "").strip()
    if not t or not _CLEAR_ALL_RE.match(t):
        return None
    try:
        from brain_store import clear_all_ideas, load
    except ImportError:
        from .brain_store import clear_all_ideas, load  # type: ignore

    bp = brain_path or _DEFAULT_BRAIN_PATH
    before = len((load(bp).get("ideas") or []))
    result = clear_all_ideas(bp)
    n = result.get("deleted_ideas", before)
    return {
        "text": (
            f"Cleared your Second Brain — deleted {n} idea{'s' if n != 1 else ''} "
            f"and {result.get('deleted_links', 0)} link(s). Genres were kept."
            if n
            else "Your Second Brain had no ideas to delete."
        ),
        "tools": [{"name": "second_brain_clear_ideas", "preview": f"cleared {n}"}],
        "run_id": "brain_ideas_cleared",
        "cleared": result,
    }


def try_handle_brain_idea(text: str, brain_path: Path | None = None) -> dict[str, Any] | None:
    """If text is an idea note command, save it directly to brain.json and return a routed response."""
    # Prefer clear-all over add-idea when the phrasing matches
    cleared = try_handle_brain_clear(text, brain_path)
    if cleared:
        return cleared

    extracted = _extract_idea(text)
    if not extracted:
        return None

    title, desc, explicit_purpose = extracted
    bp = brain_path or _DEFAULT_BRAIN_PATH

    # Detect purpose if not explicitly indicated
    purpose = explicit_purpose or detect_purpose(f"{text} {title} {desc or ''}")
    idea = add_idea_smart(bp, title=title, description=desc, purpose=purpose)

    p_info = PURPOSE_DEFINITIONS.get(idea.get("purpose") or "notes") or PURPOSE_DEFINITIONS["notes"]
    color = idea.get("color") or p_info["color"]
    icon = idea.get("icon") or p_info.get("icon", "💡")
    genre_name = idea.get("genre_name") or p_info["name"]

    reply_text = (
        f"Added your idea '{idea['title']}' to your Second Brain under {icon} {genre_name} "
        f"with {p_info['name']} color coding ({color})."
    )

    return {
        "text": reply_text,
        "tools": [
            {
                "name": "second_brain_add_idea",
                "preview": f"{icon} {idea['title']} · {genre_name}",
            }
        ],
        "run_id": "brain_idea_saved",
        "idea": idea,
    }


def hermes_brain_hint(text: str) -> str | None:
    extracted = _extract_idea(text)
    if not extracted:
        return None
    title, desc, purpose = extracted
    return f"User is sharing an idea: '{title}'. Save it to the Second Brain using second_brain_add_idea."
