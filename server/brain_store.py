"""Second Brain graph store — genres, ideas (nodes), and links for the HUD.

Features rich purpose-based color coding (Work, Study, Creative, Health, Urgent, Tech, etc.),
smart idea intake, and relational node links.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

# Distinct purpose palettes and categories
PURPOSE_DEFINITIONS: dict[str, dict[str, str]] = {
    "work": {
        "name": "Work & Business",
        "color": "#2979ff",
        "icon": "💼",
        "description": "Professional projects, business tasks, client deliverables",
    },
    "study": {
        "name": "Study & Learning",
        "color": "#b388ff",
        "icon": "📚",
        "description": "Courses, exams, subjects, research, revisions, study guides",
    },
    "creative": {
        "name": "Creative & Projects",
        "color": "#ffd600",
        "icon": "💡",
        "description": "New innovations, designs, startups, videos, creative concepts",
    },
    "personal": {
        "name": "Personal & Health",
        "color": "#00e676",
        "icon": "🌱",
        "description": "Fitness, habits, wellness, daily life, home, family",
    },
    "urgent": {
        "name": "Urgent & Deadlines",
        "color": "#ff1744",
        "icon": "🔥",
        "description": "Critical action items, fast deadlines, high priority tasks",
    },
    "tech": {
        "name": "Tech & Engineering",
        "color": "#00e5ff",
        "icon": "⚡",
        "description": "Software, AI, coding, infrastructure, hardware, automation",
    },
    "finance": {
        "name": "Finance & Wealth",
        "color": "#76ff03",
        "icon": "💰",
        "description": "Budgeting, savings, investments, expense tracking",
    },
    "notes": {
        "name": "Sparks & Thoughts",
        "color": "#ff4081",
        "icon": "✨",
        "description": "Quick brainstorms, random sparks, spontaneous notes",
    },
    "media": {
        "name": "Media & Entertainment",
        "color": "#ff9100",
        "icon": "🎬",
        "description": "Anime, manga, movies, shows, books, games",
    },
}

JARVIS_COLORS = tuple(p["color"] for p in PURPOSE_DEFINITIONS.values()) + (
    "#18ffff",
    "#00b0ff",
    "#651fff",
    "#f50057",
    "#ff6d00",
)


def _empty() -> dict:
    return {"genres": [], "ideas": [], "links": [], "updated_at": None}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def load(path: Path) -> dict:
    with _LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = _empty()
        if not isinstance(data, dict):
            data = _empty()
        data.setdefault("genres", [])
        data.setdefault("ideas", [])
        data.setdefault("links", [])
        return data


def save(path: Path, data: dict) -> None:
    with _LOCK:
        data = dict(data)
        data["updated_at"] = _now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def ensure_default_purposes(path: Path) -> list[dict]:
    """Ensure standard purpose genres exist in the store with their distinct colors."""
    data = load(path)
    existing_genres = data.get("genres") or []
    existing_names = {g.get("name", "").strip().lower() for g in existing_genres}

    added = False
    for pid, meta in PURPOSE_DEFINITIONS.items():
        name_lower = meta["name"].lower()
        if not any(name_lower in gname or pid in gname for gname in existing_names):
            new_g = {
                "id": _new_id(),
                "name": meta["name"],
                "color": meta["color"],
                "purpose": pid,
                "icon": meta.get("icon", ""),
                "description": meta.get("description", ""),
                "created_at": _now(),
            }
            existing_genres.append(new_g)
            existing_names.add(new_g["name"].lower())
            added = True

    # Also make sure existing genres have a color and optional purpose
    for g in existing_genres:
        if not g.get("color"):
            g["color"] = _pick_color(data)
        if not g.get("purpose"):
            # Try to map to standard purpose
            g_low = g.get("name", "").lower()
            for pid, meta in PURPOSE_DEFINITIONS.items():
                if pid in g_low or meta["name"].lower() in g_low:
                    g["purpose"] = pid
                    break

    if added:
        data["genres"] = existing_genres
        save(path, data)
    return existing_genres


def detect_purpose(text: str) -> str:
    """Analyze an idea's title and description to detect its purpose."""
    t = (text or "").lower()
    if re.search(r"\b(urgent|asap|deadline|critical|priority|due today|immediately|must do)\b", t):
        return "urgent"
    if re.search(r"\b(study|exam|homework|school|university|class|lecture|chapter|test|quiz|math|science|physics|chemistry|biology|history|reading|course)\b", t):
        return "study"
    if re.search(r"\b(work|client|business|job|meeting|office|proposal|company|contract|boss|career)\b", t):
        return "work"
    if re.search(r"\b(code|coding|python|javascript|api|app|software|server|ai|model|llm|bug|feature|github|database|docker)\b", t):
        return "tech"
    if re.search(r"\b(creative|art|design|video|youtube|script|story|song|music|logo|draw|animation|sketch|invention|startup)\b", t):
        return "creative"
    if re.search(r"\b(gym|workout|health|diet|sleep|habit|routine|walk|run|water|doctor|medicine|weight|fitness)\b", t):
        return "personal"
    if re.search(r"\b(money|finance|budget|cost|dollar|invest|stock|crypto|crypto|expense|save|bank|price)\b", t):
        return "finance"
    if re.search(r"\b(anime|manga|movie|film|episode|series|game|gaming|watch|show|comic)\b", t):
        return "media"
    return "notes"


def _pick_color(data: dict) -> str:
    used = {g.get("color") for g in data.get("genres") or []}
    for c in JARVIS_COLORS:
        if c not in used:
            return c
    return JARVIS_COLORS[len(data.get("genres") or []) % len(JARVIS_COLORS)]


def normalize_genre(raw: dict, *, data: dict | None = None) -> dict:
    name = str((raw or {}).get("name") or "").strip()
    if not name:
        raise ValueError("genre name is required")
    purpose = str((raw or {}).get("purpose") or "").strip().lower()
    color = str((raw or {}).get("color") or "").strip()

    if not color and purpose and purpose in PURPOSE_DEFINITIONS:
        color = PURPOSE_DEFINITIONS[purpose]["color"]
    if not color and data is not None:
        color = _pick_color(data)
    if not color:
        color = JARVIS_COLORS[0]

    return {
        "id": str((raw or {}).get("id") or _new_id()),
        "name": name[:120],
        "color": color[:32],
        "purpose": purpose[:32] if purpose else None,
        "icon": str((raw or {}).get("icon") or (PURPOSE_DEFINITIONS.get(purpose, {}).get("icon", "")))[:16],
        "created_at": (raw or {}).get("created_at") or _now(),
    }


def normalize_idea(raw: dict, *, genres: list[dict]) -> dict:
    title = str((raw or {}).get("title") or "").strip()
    if not title:
        raise ValueError("idea title is required")
    description = (str((raw or {}).get("description") or "").strip() or None)
    genre_id = (raw or {}).get("genre_id")
    purpose = (raw or {}).get("purpose")
    color = str((raw or {}).get("color") or "").strip()

    if genre_id is not None:
        genre_id = str(genre_id).strip() or None
        if genre_id and not any(g.get("id") == genre_id for g in genres):
            raise ValueError("genre not found")

    # If purpose not specified, auto-detect it from title and description
    if not purpose:
        purpose = detect_purpose(f"{title} {description or ''}")

    purpose_clean = str(purpose).strip().lower() if purpose else "notes"
    if purpose_clean not in PURPOSE_DEFINITIONS:
        purpose_clean = detect_purpose(purpose_clean)

    # Match genre by id or purpose
    if not genre_id:
        match = next((g for g in genres if (g.get("purpose") == purpose_clean or purpose_clean in g.get("name", "").lower())), None)
        if match:
            genre_id = match["id"]

    # Match or determine color
    if not color:
        if purpose_clean in PURPOSE_DEFINITIONS:
            color = PURPOSE_DEFINITIONS[purpose_clean]["color"]
        elif genre_id:
            g = next((x for x in genres if x.get("id") == genre_id), None)
            if g and g.get("color"):
                color = g["color"]
    if not color:
        color = JARVIS_COLORS[0]

    icon = (raw or {}).get("icon") or PURPOSE_DEFINITIONS.get(purpose_clean, {}).get("icon", "💡")

    return {
        "id": str((raw or {}).get("id") or _new_id()),
        "title": title[:160],
        "description": description,
        "genre_id": genre_id,
        "purpose": purpose_clean,
        "purpose_name": PURPOSE_DEFINITIONS.get(purpose_clean, {}).get("name", purpose_clean.capitalize()),
        "color": color[:32],
        "icon": str(icon)[:16],
        "created_at": (raw or {}).get("created_at") or _now(),
    }


def normalize_link(raw: dict, *, ideas: list[dict]) -> dict:
    from_id = str((raw or {}).get("from_id") or (raw or {}).get("from") or "").strip()
    to_id = str((raw or {}).get("to_id") or (raw or {}).get("to") or "").strip()
    if not from_id or not to_id:
        raise ValueError("from_id and to_id are required")
    if from_id == to_id:
        raise ValueError("cannot link an idea to itself")
    ids = {i.get("id") for i in ideas}
    if from_id not in ids or to_id not in ids:
        raise ValueError("both ideas must exist")
    return {
        "id": str((raw or {}).get("id") or _new_id()),
        "from_id": from_id,
        "to_id": to_id,
        "created_at": (raw or {}).get("created_at") or _now(),
    }


def add_genre(path: Path, raw: dict) -> dict:
    data = load(path)
    genre = normalize_genre(raw, data=data)
    data["genres"] = [g for g in data["genres"] if g.get("id") != genre["id"]]
    data["genres"].append(genre)
    save(path, data)
    return genre


def delete_genre(path: Path, genre_id: str) -> bool:
    data = load(path)
    before = len(data["genres"])
    data["genres"] = [g for g in data["genres"] if g.get("id") != genre_id]
    if len(data["genres"]) == before:
        return False
    for idea in data["ideas"]:
        if idea.get("genre_id") == genre_id:
            idea["genre_id"] = None
    save(path, data)
    return True


def upsert_idea(
    path: Path,
    raw: dict,
    *,
    link_ids: list[str] | None = None,
    sync_links: bool = False,
) -> dict:
    data = load(path)
    idea = normalize_idea(raw, genres=data["genres"])
    existing = next((i for i in data["ideas"] if i.get("id") == idea["id"]), None)
    if existing:
        idea["created_at"] = existing.get("created_at") or idea["created_at"]
    data["ideas"] = [i for i in data["ideas"] if i.get("id") != idea["id"]]
    data["ideas"].append(idea)
    if sync_links and link_ids is not None:
        data["links"] = [
            l for l in data["links"]
            if l.get("from_id") != idea["id"] and l.get("to_id") != idea["id"]
        ]
        for other_id in link_ids:
            other_id = str(other_id).strip()
            if not other_id or other_id == idea["id"]:
                continue
            try:
                link = normalize_link({"from_id": idea["id"], "to_id": other_id}, ideas=data["ideas"])
            except ValueError:
                continue
            data["links"].append(link)
    elif link_ids:
        for other_id in link_ids:
            other_id = str(other_id).strip()
            if not other_id or other_id == idea["id"]:
                continue
            try:
                link = normalize_link({"from_id": idea["id"], "to_id": other_id}, ideas=data["ideas"])
            except ValueError:
                continue
            data["links"] = [
                l for l in data["links"]
                if not (
                    (l.get("from_id") == link["from_id"] and l.get("to_id") == link["to_id"])
                    or (l.get("from_id") == link["to_id"] and l.get("to_id") == link["from_id"])
                )
            ]
            data["links"].append(link)
    save(path, data)
    return idea


def add_idea_smart(
    path: Path,
    title: str,
    description: str | None = None,
    purpose: str | None = None,
    *,
    link_ids: list[str] | None = None,
) -> dict:
    """Add an idea to the Second Brain, resolving or auto-detecting the purpose & color."""
    ensure_default_purposes(path)
    data = load(path)
    genres = data.get("genres") or []

    # Detect purpose if not explicitly provided
    clean_purpose = (purpose or "").strip().lower()
    if not clean_purpose or clean_purpose not in PURPOSE_DEFINITIONS:
        clean_purpose = detect_purpose(f"{title} {description or ''}")

    # Find or create matching genre
    target_genre = next(
        (g for g in genres if g.get("purpose") == clean_purpose or clean_purpose in g.get("name", "").lower()),
        None,
    )
    if not target_genre and clean_purpose in PURPOSE_DEFINITIONS:
        meta = PURPOSE_DEFINITIONS[clean_purpose]
        target_genre = add_genre(path, {
            "name": meta["name"],
            "color": meta["color"],
            "purpose": clean_purpose,
            "icon": meta.get("icon", ""),
        })

    genre_id = target_genre["id"] if target_genre else None
    idea_raw = {
        "title": title,
        "description": description,
        "genre_id": genre_id,
        "purpose": clean_purpose,
    }
    idea = upsert_idea(path, idea_raw, link_ids=link_ids)
    idea["genre_name"] = target_genre.get("name") if target_genre else "General"
    idea["color"] = target_genre.get("color") if target_genre else "#00e5ff"
    idea["icon"] = target_genre.get("icon") if target_genre else "💡"
    return idea


def delete_idea(path: Path, idea_id: str) -> bool:
    data = load(path)
    before = len(data["ideas"])
    data["ideas"] = [i for i in data["ideas"] if i.get("id") != idea_id]
    if len(data["ideas"]) == before:
        return False
    data["links"] = [
        l for l in data["links"]
        if l.get("from_id") != idea_id and l.get("to_id") != idea_id
    ]
    save(path, data)
    return True


def clear_all_ideas(path: Path) -> dict[str, int]:
    """Delete every idea and all idea↔idea links. Genres are kept."""
    data = load(path)
    n_ideas = len(data.get("ideas") or [])
    n_links = len(data.get("links") or [])
    data["ideas"] = []
    data["links"] = []
    save(path, data)
    return {"deleted_ideas": n_ideas, "deleted_links": n_links}


def delete_ideas_matching(
    path: Path,
    *,
    purposes: set[str] | None = None,
    text_re: re.Pattern[str] | None = None,
) -> list[dict]:
    """Delete ideas by purpose and/or title/description regex. Cleans dangling links."""
    data = load(path)
    purposes = {p.strip().lower() for p in (purposes or set()) if p}
    if text_re is None and not purposes:
        return []
    kept: list[dict] = []
    deleted: list[dict] = []
    deleted_ids: set[str] = set()
    for idea in data.get("ideas") or []:
        purpose = (idea.get("purpose") or "").strip().lower()
        blob = f"{idea.get('title') or ''} {idea.get('description') or ''}"
        hit = False
        if purposes and purpose in purposes:
            hit = True
        if text_re is not None and text_re.search(blob):
            hit = True
        if hit:
            deleted.append(idea)
            iid = idea.get("id")
            if iid:
                deleted_ids.add(str(iid))
        else:
            kept.append(idea)
    if not deleted:
        return []
    data["ideas"] = kept
    data["links"] = [
        link for link in (data.get("links") or [])
        if str(link.get("from_id") or "") not in deleted_ids
        and str(link.get("to_id") or "") not in deleted_ids
    ]
    save(path, data)
    return deleted


def add_link(path: Path, raw: dict) -> dict:
    data = load(path)
    link = normalize_link(raw, ideas=data["ideas"])
    data["links"] = [
        l for l in data["links"]
        if not (
            (l.get("from_id") == link["from_id"] and l.get("to_id") == link["to_id"])
            or (l.get("from_id") == link["to_id"] and l.get("to_id") == link["from_id"])
        )
    ]
    data["links"].append(link)
    save(path, data)
    return link


def delete_link(path: Path, link_id: str) -> bool:
    data = load(path)
    before = len(data["links"])
    data["links"] = [l for l in data["links"] if l.get("id") != link_id]
    if len(data["links"]) == before:
        return False
    save(path, data)
    return True


def snapshot(path: Path) -> dict:
    ensure_default_purposes(path)
    data = load(path)
    return {
        "genres": data.get("genres") or [],
        "ideas": data.get("ideas") or [],
        "links": data.get("links") or [],
        "purposes": PURPOSE_DEFINITIONS,
        "updated_at": data.get("updated_at"),
    }
