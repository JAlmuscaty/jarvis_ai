"""Ingest handwritten / printed notes from a photo into Second Brain."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

try:
    from brain_store import PURPOSE_DEFINITIONS, add_idea_smart
except ImportError:
    from .brain_store import PURPOSE_DEFINITIONS, add_idea_smart  # type: ignore

_BRAIN_PHOTO_RE = re.compile(
    r"(?is)\b(?:"
    r"(?:add|save|put|store|send)\s+(?:these|this|my|the)?\s*(?:notes?|ideas?|photo|picture|image|page|pages|handwriting)?"
    r".{0,40}(?:to|into|in)\s+(?:my\s+)?(?:second\s+brain|brain|notes)"
    r"|(?:add|save|put)\s+(?:to|into|in)\s+(?:my\s+)?(?:second\s+brain|brain)"
    r"|second\s+brain\s+(?:these|this|from)\s+(?:notes?|photo|picture|image)"
    r"|scan\s+(?:these\s+)?notes?\s+(?:to|into)\s+(?:my\s+)?(?:second\s+brain|brain)"
    r"|notes?\s+(?:from\s+)?(?:this\s+)?(?:photo|picture|image).{0,30}(?:second\s+brain|brain)"
    r")\b"
)

_EXTRACT_PROMPT = """You are extracting study/personal notes from a PHOTO for Jarvis Second Brain.

Read ALL readable text in the image (handwriting or print). Split into distinct ideas/notes.

Reply with ONLY a JSON array (no markdown fences, no commentary). Each item:
{"title":"short title","description":"full note text","purpose":"study|work|creative|personal|urgent|tech|finance|media|notes"}

Rules:
- One bullet / heading / paragraph ≈ one idea when they are separate topics.
- Keep the user's wording in description; fix only obvious OCR typos.
- purpose must be one of the enum values above (default "notes" or "study" for school notes).
- If nothing readable: []
"""


def wants_notes_to_brain(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_BRAIN_PHOTO_RE.search(t))


def _parse_ideas_payload(raw: str) -> list[dict[str, Any]]:
    s = (raw or "").strip()
    if not s:
        return []
    # Strip markdown fences if model ignored instructions
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if m:
        s = m.group(1).strip()
    # Find first JSON array
    start = s.find("[")
    end = s.rfind("]")
    if start >= 0 and end > start:
        s = s[start : end + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        # Fallback: one idea from plain text
        lines = [ln.strip(" -•\t") for ln in (raw or "").splitlines() if ln.strip()]
        lines = [ln for ln in lines if not ln.startswith("{") and "json" not in ln.lower()]
        if not lines:
            return []
        return [{
            "title": lines[0][:80],
            "description": "\n".join(lines[1:])[:2000] or None,
            "purpose": "notes",
        }]
    if isinstance(data, dict):
        data = data.get("ideas") or data.get("notes") or data.get("items") or [data]
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            out.append({"title": item.strip()[:120], "description": None, "purpose": "notes"})
            continue
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("name") or item.get("heading") or "").strip()
        desc = (item.get("description") or item.get("text") or item.get("body") or item.get("content") or "").strip()
        if not title and desc:
            title = desc.split("\n", 1)[0][:80]
            desc = desc[len(title):].strip() or desc
        if not title:
            continue
        purpose = (item.get("purpose") or item.get("category") or "notes").strip().lower()
        if purpose not in PURPOSE_DEFINITIONS:
            purpose = "study" if re.search(r"\b(chapter|exam|homework|math|biology|lecture)\b", f"{title} {desc}", re.I) else "notes"
        out.append({
            "title": title[:120],
            "description": (desc[:4000] if desc else None),
            "purpose": purpose,
        })
    return out[:40]


def ingest_notes_photo(
    *,
    image_data_url: str,
    user_text: str,
    brain_path: Path,
    extract_fn: Callable[[str, str], str],
) -> dict[str, Any]:
    """extract_fn(prompt_text, image_data_url) -> model reply text."""
    prompt = (
        f"{_EXTRACT_PROMPT}\n"
        f"User said: {user_text.strip()[:300]}"
    )
    raw = extract_fn(prompt, image_data_url)
    ideas = _parse_ideas_payload(raw)
    if not ideas:
        return {
            "text": (
                "I looked at the photo but couldn't pull clear notes. "
                "Try a sharper picture or type the notes and say add to second brain."
            ),
            "tools": [{"name": "notes_photo_to_brain", "preview": "empty"}],
            "run_id": "notes_photo",
            "ideas_saved": [],
            "raw_extract": (raw or "")[:500],
        }

    saved = []
    for idea in ideas:
        row = add_idea_smart(
            brain_path,
            title=idea["title"],
            description=idea.get("description"),
            purpose=idea.get("purpose"),
        )
        saved.append({
            "title": row.get("title"),
            "purpose": row.get("purpose"),
            "purpose_name": row.get("genre_name"),
            "id": row.get("id"),
        })

    lines = [f"Added {len(saved)} note{'s' if len(saved) != 1 else ''} to your Second Brain:"]
    for i, s in enumerate(saved, 1):
        icon = (PURPOSE_DEFINITIONS.get(s.get("purpose") or "notes") or {}).get("icon", "✨")
        lines.append(f"{i}. {icon} {s.get('title')} ({s.get('purpose_name') or s.get('purpose')})")
    lines.append("Open Second Brain on the HUD to see them on the graph.")

    return {
        "text": "\n".join(lines),
        "tools": [{"name": "notes_photo_to_brain", "preview": f"{len(saved)} ideas"}],
        "run_id": "notes_photo",
        "ideas_saved": saved,
    }
