"""Talk to the Jarvis voice server Second Brain (ideas & notes graph) API."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BRAIN_BASE = os.environ.get("JARVIS_BRAIN_URL", "http://127.0.0.1:8765/api/brain").rstrip("/")
TOKEN = os.environ.get("JARVIS_HUD_TOKEN", "")

PURPOSE_PALETTE = {
    "work": {"name": "Work & Business", "color": "#2979ff", "icon": "💼"},
    "study": {"name": "Study & Learning", "color": "#b388ff", "icon": "📚"},
    "creative": {"name": "Creative & Projects", "color": "#ffd600", "icon": "💡"},
    "personal": {"name": "Personal & Health", "color": "#00e676", "icon": "🌱"},
    "urgent": {"name": "Urgent & Deadlines", "color": "#ff1744", "icon": "🔥"},
    "tech": {"name": "Tech & Engineering", "color": "#00e5ff", "icon": "⚡"},
    "finance": {"name": "Finance & Wealth", "color": "#76ff03", "icon": "💰"},
    "notes": {"name": "Sparks & Thoughts", "color": "#ff4081", "icon": "✨"},
    "media": {"name": "Media & Entertainment", "color": "#ff9100", "icon": "🎬"},
}


def _req(method: str, path: str = "", body: dict | list | None = None) -> dict:
    url = BRAIN_BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["X-Jarvis-Token"] = TOKEN
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body)
        except Exception:
            parsed = {"error": err_body or str(e)}
        return {"ok": False, "http_status": e.code, **(parsed if isinstance(parsed, dict) else {"error": parsed})}
    except Exception as e:
        return {"ok": False, "error": f"Second Brain API unreachable: {e}"}


def second_brain_add_idea(args: dict, **kwargs) -> str:
    """Add an idea or note to the user's Second Brain with purpose-based color coding."""
    title = (args.get("title") or "").strip()
    if not title:
        return json.dumps({"ok": False, "error": "title is required"})

    description = (args.get("description") or "").strip() or None
    purpose = (args.get("purpose") or "").strip().lower() or None
    genre_id = (args.get("genre_id") or "").strip() or None

    payload = {
        "title": title,
        "description": description,
        "purpose": purpose,
        "genre_id": genre_id,
    }

    res = _req("POST", "/ideas", payload)
    if isinstance(res, dict) and res.get("ok"):
        idea = res.get("idea") or {}
        p_name = idea.get("purpose_name") or purpose or "Notes"
        color = idea.get("color") or "#00e5ff"
        icon = idea.get("icon") or "💡"
        res["message"] = (
            f"Saved idea '{title}' to Second Brain under {icon} {p_name} ({color} color coding). "
            f"Viewable on the HUD Second Brain graph."
        )
        res["hud_page"] = "/hud/brain.html"
    return json.dumps(res, ensure_ascii=False)


def second_brain_list_ideas(args: dict, **kwargs) -> str:
    """List or search ideas in the user's Second Brain graph."""
    res = _req("GET", "")
    if res.get("ok") is False and "error" in res:
        return json.dumps(res)

    ideas = res.get("ideas") or []
    genres = res.get("genres") or []
    purpose = (args.get("purpose") or "").strip().lower()
    search = (args.get("search") or "").strip().lower()

    if purpose:
        ideas = [i for i in ideas if (i.get("purpose") or "").lower() == purpose]
    if search:
        ideas = [
            i for i in ideas
            if search in (i.get("title") or "").lower()
            or search in (i.get("description") or "").lower()
        ]

    return json.dumps({
        "ok": True,
        "idea_count": len(ideas),
        "total_ideas": len(res.get("ideas") or []),
        "genres_count": len(genres),
        "ideas": ideas[:30],
        "genres": genres,
        "hud_page": "/hud/brain.html",
    }, ensure_ascii=False)


def second_brain_add_genre(args: dict, **kwargs) -> str:
    """Add a new genre/category to the Second Brain graph."""
    name = (args.get("name") or "").strip()
    if not name:
        return json.dumps({"ok": False, "error": "name is required"})
    color = (args.get("color") or "").strip() or None
    res = _req("POST", "/genres", {"name": name, "color": color})
    return json.dumps(res, ensure_ascii=False)


def second_brain_clear_ideas(args: dict, **kwargs) -> str:
    """Delete ALL ideas (and links) from Second Brain. Keeps genres. Requires confirm=true."""
    confirm = args.get("confirm")
    if confirm is True or str(confirm).strip().lower() in ("1", "true", "yes"):
        res = _req("POST", "/ideas/clear", {"confirm": True})
        if isinstance(res, dict) and res.get("ok"):
            n = res.get("deleted_ideas", 0)
            res["message"] = (
                f"Cleared Second Brain: deleted {n} idea(s) and "
                f"{res.get('deleted_links', 0)} link(s). Genres were kept."
            )
        return json.dumps(res, ensure_ascii=False)
    # Preview count without deleting
    snap = _req("GET", "")
    n = len(snap.get("ideas") or []) if isinstance(snap, dict) else 0
    return json.dumps({
        "ok": False,
        "needs_confirm": True,
        "idea_count": n,
        "error": (
            f"There are {n} idea(s). To delete them all, call again with confirm=true. "
            "This cannot be undone."
        ),
    })


brain_add_idea = second_brain_add_idea
brain_list_ideas = second_brain_list_ideas
brain_add_genre = second_brain_add_genre
brain_clear_ideas = second_brain_clear_ideas


def daily_briefing(args: dict, **kwargs) -> str:
    """Fetch synthesized daily briefing from Jarvis server."""
    url = BRAIN_BASE.replace("/api/brain", "/api/briefing")
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["X-Jarvis-Token"] = TOKEN
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return raw or json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Briefing unreachable: {exc}"})

