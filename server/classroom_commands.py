"""Hard-route Classroom / screen checks so they don't wait on Hermes guessing.

- "only look at my screen" → read the current tab, nothing else
- "check everything" / "check Google Classroom" → To-do list only (read-only)
- "check all classes" → each current class, this/last week recap (skip old classes)
- "solve what I have due" → open assignment pages, extract questions, never submit
- "add what you saw to my calendar" → import last Classroom snapshot only if asked
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_PLUGIN_DIRS = [
    Path.home() / "AppData" / "Local" / "hermes" / "plugins",
    Path(__file__).resolve().parents[1] / "hermes-plugin",
]
_LOGS = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
_SNAPSHOT = _LOGS / "classroom_last.json"

_LOOK_ONLY = re.compile(
    r"(?is)\b("
    r"only\s+look(?:\s+at)?(?:\s+my)?\s+screen|"
    r"just\s+look(?:\s+at)?(?:\s+the\s+)?(?:my\s+)?screen|"
    r"look\s+at\s+(?:my\s+)?screen(?:\s+only)?|"
    r"what(?:'s| is)\s+on\s+my\s+screen|"
    r"read\s+(?:my\s+)?screen"
    r")\b"
)
# To-do list only (not per-class)
_CHECK_TODO = re.compile(
    r"(?is)\b("
    r"check\s+everything|"
    r"check\s+(?:my\s+)?(?:google\s+)?classroom|"
    r"open\s+(?:google\s+)?classroom|"
    r"look\s+at\s+(?:my\s+)?(?:google\s+)?classroom|"
    r"what(?:'s| is)\s+due(?:\s+in\s+classroom)?|"
    r"my\s+(?:to[\s-]?do|dues?|homework)\b"
    r")\b"
)
# Visit each current class for this/last week recap
_CHECK_CLASSES = re.compile(
    r"(?is)\b("
    r"check\s+all\s+(?:my\s+)?classes|"
    r"check\s+(?:each|every)\s+class|"
    r"recap\s+(?:all\s+)?(?:my\s+)?classes|"
    r"check\s+(?:my\s+)?classes\s+(?:one\s+by\s+one|individually)|"
    r"go\s+(?:through|into)\s+(?:all\s+)?(?:my\s+)?classes|"
    r"class\s+by\s+class|"
    r"what\s+(?:was\s+)?posted\s+(?:this|last)\s+week"
    r")\b"
)
_SOLVE = re.compile(
    r"(?is)(?:"
    r"\b(solve|help\s+me(?:\s+with)?|answer|do)\b.{0,40}\b(due|homework|assignment|questions?)\b|"
    r"\b(homework|assignment|what i have due)\b.{0,30}\b(solve|help|answer)\b"
    r")"
)
_ADD_SEEN = re.compile(
    r"(?is)(?:"
    r"\b(?:add|put|save)\b.{0,50}\b(?:saw|seen|classroom|those|them|dues?|homework)\b.{0,30}\b(?:calendar|schedule)\b|"
    r"\b(?:add|put)\b.{0,20}\b(?:to\s+)?(?:my\s+)?calendar\b.{0,40}\b(?:classroom|homework|dues?|what you (?:saw|found))\b"
    r")"
)
# open class X / find PDF in english 9s
_OPEN_CLASS = re.compile(
    r"(?is)\b(?:open|go\s+to|enter)\s+(?:(?:my|the)\s+)?(?:google\s+)?classroom\s+"
    r"(?:class\s+)?(?:called\s+|named\s+)?(.+?)$|"
    r"\b(?:open|go\s+to|enter)\s+(?:(?:my|the)\s+)?(.+?)\s+(?:class|classroom)\b|"
    r"\b(?:open|go\s+to)\s+(?:class\s+)?([A-Za-z0-9][A-Za-z0-9 ._-]{1,40})\b"
)
_FIND_MATERIAL = re.compile(
    r"(?is)\b(?:"
    r"(?:open|check|find|look\s+for|get|show)\b.{0,80}\b(pdf|book|textbook|workbook|file|document|material)s?\b|"
    r"\b(pdf|book|textbook)\b.{0,60}\b(?:in|from|for)\b"
    r")"
)


def _plugin():
    last = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import browser_actions, page_look  # type: ignore
            return browser_actions, page_look
        except Exception as exc:
            last = exc
    raise RuntimeError(f"pc_apps unavailable: {last}")


def _save_snapshot(data: dict[str, Any]) -> None:
    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _SNAPSHOT.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_snapshot() -> dict[str, Any]:
    try:
        data = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _format_check(data: dict[str, Any], *, solve: bool, simple: bool = False) -> str:
    if not data.get("ok"):
        return data.get("error") or (
            "Couldn't check Classroom." if simple else "I couldn't check Google Classroom."
        )
    dues = data.get("dues") or []
    dated = [it for it in dues if it.get("date") and it.get("important", True)]
    undated = [it for it in dues if not it.get("date") and it.get("important")]
    skipped = [it for it in dues if not it.get("important")]

    if simple:
        # Titles (+ due date only). No classes, headers, or skip notes.
        lines: list[str] = []
        for it in dated[:12]:
            title = str(it.get("title") or "Untitled").strip()
            when = (it.get("due_raw") or it.get("date") or "").strip()
            lines.append(f"{title} — {when}" if when else title)
        for it in undated[:8]:
            title = str(it.get("title") or "Untitled").strip()
            if title:
                lines.append(title)
        if not lines:
            lines.append("None")
        if solve:
            qs = data.get("questions") or []
            for q in qs[:4]:
                title = str(q.get("title") or "Assignment").strip()
                text = (q.get("text") or q.get("error") or "").strip()
                if text:
                    lines.append(f"{title}: {text[:4500]}")
        return "\n".join(lines)

    lines = ["Classroom check (read-only — I did not submit anything)."]
    classes = data.get("classes") or []
    if classes:
        lines.append("Classes: " + "; ".join(classes[:12]) + ".")
    if dated:
        lines.append("Due:")
        for it in dated[:8]:
            bit = it.get("title") or "Untitled"
            if it.get("class_name"):
                bit += f" ({it['class_name']})"
            bit += f" — {it.get('due_raw') or it.get('date')}"
            lines.append("- " + bit)
    if undated:
        lines.append("No due date, posted within the last 3 days:")
        for it in undated[:6]:
            bit = it.get("title") or "Untitled"
            if it.get("class_name"):
                bit += f" ({it['class_name']})"
            if it.get("posted_raw") or it.get("posted_date"):
                bit += f" — {it.get('posted_raw') or ('posted ' + str(it.get('posted_date')))}"
            lines.append("- " + bit)
    if not dated and not undated:
        lines.append("I didn't see current homework on the To-do page.")
    if skipped:
        undated_old = sum(
            1 for it in skipped
            if not it.get("date") and "older than" in str(it.get("why") or "")
        )
        other = len(skipped) - undated_old
        if undated_old:
            lines.append(
                f"Skipped {undated_old} undated leftover(s) posted more than 3 days ago."
            )
        if other > 0:
            lines.append(f"Skipped {other} older leftover(s) that are not this year's work.")
    if solve:
        qs = data.get("questions") or []
        if qs:
            lines.append("Assignment text (not submitted):")
            for q in qs[:4]:
                title = q.get("title") or "Assignment"
                text = (q.get("text") or q.get("error") or "")[:4500]
                lines.append(f"{title}: {text}")
        else:
            lines.append("I could list dues but couldn't open assignment question pages.")
        images = []
        for q in qs:
            images.extend(q.get("images") or [])
        if images:
            lines.append(f"Opened {len(images)} attached image(s) so I can look at them. I did not submit.")
    if data.get("imported"):
        lines.append("Also added dated items to your calendar.")
    return "\n".join(lines)


def _speak_check(data: dict[str, Any], *, solve: bool, simple: bool = False) -> str:
    """Short spoken summary — full details stay in text."""
    if not data.get("ok"):
        return data.get("error") or (
            "Couldn't check Classroom." if simple else "I couldn't check Google Classroom."
        )
    dues = data.get("dues") or []
    dated = [it for it in dues if it.get("date") and it.get("important", True)]
    undated = [it for it in dues if not it.get("date") and it.get("important")]
    if simple:
        titles = [str(it.get("title") or "").strip() for it in (dated + undated)[:6]]
        titles = [t for t in titles if t]
        return "; ".join(titles) if titles else "None"
    if dated:
        titles = [str(it.get("title") or "item") for it in dated[:3]]
        more = len(dated) - len(titles)
        spoken = "You have " + str(len(dated)) + " due: " + "; ".join(titles)
        if more > 0:
            spoken += f"; and {more} more"
        spoken += ". Full list is on screen."
        return spoken
    if undated:
        return (
            f"No dated dues. I kept {len(undated)} undated assignment(s) "
            f"posted within the last 3 days. Details are on screen."
        )
    if solve:
        return "I opened the assignments. Details are on screen. I did not submit anything."
    return "No current homework on the To-do page."


def _format_classes_recap(data: dict[str, Any], *, simple: bool = False) -> str:
    """Most→least important recap across current classes (this/last week)."""
    if not data.get("ok"):
        return data.get("error") or (
            "Couldn't check classes." if simple else "I couldn't check your classes."
        )
    dues = data.get("dues") or []
    skipped = data.get("classes_skipped_old") or []
    current = data.get("classes_current") or []

    if simple:
        lines: list[str] = []
        for it in dues[:14]:
            title = str(it.get("title") or "Untitled").strip()
            cls = str(it.get("class_name") or "").strip()
            when = (it.get("due_raw") or it.get("date") or it.get("urgency") or "").strip()
            bit = f"{title}"
            if cls:
                bit += f" ({cls})"
            if when:
                bit += f" — {when}"
            lines.append(bit)
        if not lines:
            lines.append("None this/last week")
        return "\n".join(lines)

    lines = [
        "Class recap (this/last week, most important first). Read-only — I did not submit.",
    ]
    if current:
        lines.append(f"Checked {len(current)} current class(es): " + "; ".join(str(c) for c in current[:12]) + ".")
    if skipped:
        bits = []
        for s in skipped[:6]:
            if isinstance(s, dict):
                bits.append(f"{s.get('name')} ({s.get('reason') or 'old'})")
            else:
                bits.append(str(s))
        lines.append("Skipped old class(es): " + "; ".join(bits) + ".")
    if not dues:
        lines.append("Nothing posted this/last week that looks like work you still need to do.")
        return "\n".join(lines)

    lines.append("Priority order (due date + difficulty):")
    for it in dues[:14]:
        rank = it.get("priority_rank") or ""
        title = it.get("title") or "Untitled"
        cls = it.get("class_name") or ""
        when = it.get("due_raw") or it.get("date") or it.get("urgency") or "no due date"
        diff = it.get("difficulty") or "medium"
        urg = it.get("urgency") or ""
        bit = f"{rank}. {title}"
        if cls:
            bit += f" — {cls}"
        bit += f" — {when}"
        if urg and urg not in str(when):
            bit += f" ({urg})"
        bit += f" [{diff}]"
        lines.append(bit)
    if len(dues) > 14:
        lines.append(f"…and {len(dues) - 14} more.")
    return "\n".join(lines)


def _speak_classes_recap(data: dict[str, Any], *, simple: bool = False) -> str:
    if not data.get("ok"):
        return data.get("error") or "Couldn't check classes."
    dues = data.get("dues") or []
    skipped = data.get("classes_skipped_old") or []
    if simple:
        titles = [str(it.get("title") or "").strip() for it in dues[:5]]
        titles = [t for t in titles if t]
        return "; ".join(titles) if titles else "None"
    if not dues:
        msg = "No work posted this or last week in your current classes."
        if skipped:
            msg += f" I skipped {len(skipped)} old class(es)."
        return msg
    top = dues[:3]
    parts = []
    for it in top:
        title = it.get("title") or "item"
        cls = it.get("class_name") or ""
        when = it.get("due_raw") or it.get("urgency") or ""
        part = title
        if cls:
            part += f" in {cls}"
        if when:
            part += f", {when}"
        parts.append(part)
    spoken = (
        f"Checked your current classes. Top priority: " + "; ".join(parts) + "."
    )
    if len(dues) > 3:
        spoken += f" {len(dues) - 3} more on screen."
    if skipped:
        spoken += f" Skipped {len(skipped)} old class(es)."
    return spoken



def _extract_class_and_material(t: str) -> tuple[str, str]:
    """Best-effort parse: 'english book pdf in english 9s' → (english 9s, english book pdf)."""
    raw = (t or "").strip()
    class_name = ""
    material = ""

    # Prefer: … in/from <class> …
    m_in = re.search(
        r"(?is)\b(?:in|from|inside)\s+(?:(?:my|the)\s+)?(.+?)(?:\s+class)?(?:\s+for\b|\s*$)",
        raw,
    )
    if m_in:
        class_name = m_in.group(1).strip(" .,!?;:\"'")
        class_name = re.sub(r"(?is)\b(google\s+)?classroom\b", "", class_name).strip()
        # Peel trailing "for the english book pdf" if captured
        class_name = re.split(r"(?is)\s+for\s+", class_name)[0].strip()

    # Material after "for the …" or before "in …"
    m_for = re.search(r"(?is)\bfor\s+(?:(?:the|my|an?)\s+)?(.+?)\s*$", raw)
    if m_for:
        material = m_for.group(1).strip(" .,!?;:\"'")
    if not material:
        m_mat = re.search(
            r"(?is)\b(?:open|check|find|look\s+for|get|show)\s+(?:(?:the|my|an?)\s+)?(.+?)"
            r"(?:\s+(?:in|from|inside)\b)",
            raw,
        )
        if m_mat:
            material = m_mat.group(1).strip(" .,!?;:\"'")

    # Class-like token: english 9s / ENGLISH 9S / G9S English
    if not class_name:
        m_cls = re.search(
            r"(?is)\b([A-Za-z][A-Za-z ._-]{0,24}?\d\s*[A-Za-z]?)\b",
            raw,
        )
        if m_cls:
            class_name = m_cls.group(1).strip()

    def _clean(s: str, *, keep_pdf: bool = False) -> str:
        drop = r"please|the|my|a|an|file|document|check|open|find|look\s+for|get|show|and|google|classroom|pdfs?"
        if keep_pdf:
            drop = r"please|the|my|a|an|file|document|check|open|find|look\s+for|get|show|and|google|classroom"
        s = re.sub(rf"(?is)\b({drop})\b", " ", s)
        return re.sub(r"\s+", " ", s).strip(" .,!?;:\"'")

    class_name = _clean(class_name)
    material = _clean(material, keep_pdf=True)
    if class_name and material and class_name.lower() in material.lower():
        material = re.sub(re.escape(class_name), "", material, flags=re.I).strip(" -–|,")
    if not material:
        if re.search(r"(?i)\bbook\b", raw):
            material = "english book pdf" if re.search(r"(?i)\benglish\b", raw) else "book pdf"
        elif re.search(r"(?i)\bpdf\b", raw):
            material = "pdf"
        else:
            material = "book"
    return class_name, material


def try_handle_classroom(text: str, *, simple: bool | None = None) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None

    if simple is None:
        try:
            from reply_prefs import is_simple
            simple = is_simple()
        except Exception:
            simple = False
    simple = bool(simple)

    look_only = bool(_LOOK_ONLY.search(t)) and not _CHECK_TODO.search(t) and not _CHECK_CLASSES.search(t)
    check_classes = bool(_CHECK_CLASSES.search(t)) and not look_only
    check_todo = bool(_CHECK_TODO.search(t)) and not look_only and not check_classes
    solve = bool(_SOLVE.search(t))
    add_seen = bool(_ADD_SEEN.search(t))
    find_mat = bool(_FIND_MATERIAL.search(t)) and (
        bool(re.search(r"(?is)\bclassroom\b", t))
        or bool(re.search(r"(?is)\b(?:class|english|math|arabic|science)\b", t))
    )
    open_class_only = (
        bool(_OPEN_CLASS.search(t))
        and not find_mat
        and not check_todo
        and not check_classes
        and not solve
    )
    if open_class_only:
        # Don't steal "open youtube / chrome / …" — need classroom or a class-like name (e.g. english 9s)
        if re.search(r"(?is)\b(youtube|chrome|whatsapp|vidbox|movies?|gmail|maps|chatgpt)\b", t):
            open_class_only = False
        elif not re.search(r"(?is)\bclassroom\b", t) and not re.search(r"(?is)\b[a-z]+\s*\d", t):
            open_class_only = False

    if not (look_only or check_todo or check_classes or solve or add_seen or find_mat or open_class_only):
        return None

    try:
        ba, page_look = _plugin()
    except Exception as exc:
        return {
            "text": f"Can't reach Chrome ({exc})." if simple else f"I can't reach Chrome right now ({exc}).",
            "tools": [{"name": "classroom_check", "preview": "plugin"}],
            "run_id": "classroom_check",
        }

    # Fuzzy open class + find PDF/material (decisive)
    if find_mat or (open_class_only and re.search(r"(?is)\b(pdf|book|file|material)\b", t)):
        class_name, material = _extract_class_and_material(t)
        if not class_name and open_class_only:
            m = _OPEN_CLASS.search(t)
            class_name = next((g for g in (m.groups() if m else ()) if g), "") or ""
            class_name = re.sub(r"(?is)\b(google\s+)?classroom\b", "", class_name).strip()
        raw = ba.classroom_find_material({"class_name": class_name, "material": material})
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            data = {"ok": False, "error": str(raw)[:240]}
        if data.get("ok"):
            msg = data.get("message") or f"Opened {data.get('material')}"
            if simple:
                msg = str(data.get("material") or msg)
            return {
                "text": msg,
                "speak": msg,
                "tools": [{"name": "classroom_find_material", "preview": material[:40]}],
                "run_id": "classroom_find",
            }
        err = data.get("error") or "Couldn't find that."
        if data.get("classes"):
            err += " Classes I see: " + "; ".join(str(x) for x in data["classes"][:8])
        return {
            "text": err,
            "speak": err,
            "tools": [{"name": "classroom_find_material", "preview": "miss"}],
            "run_id": "classroom_find",
        }

    if open_class_only:
        m = _OPEN_CLASS.search(t)
        class_name = next((g for g in (m.groups() if m else ()) if g), "") or ""
        class_name = re.sub(r"(?is)\b(google\s+)?classroom\b", "", class_name).strip(" .,!?;:\"'")
        if not class_name:
            return None
        raw = ba.classroom_open_class({"class_name": class_name})
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            data = {"ok": False, "error": str(raw)[:240]}
        if data.get("ok"):
            msg = data.get("message") or f"Opened {data.get('class_name')}"
            return {
                "text": msg if not simple else str(data.get("class_name") or msg),
                "speak": msg,
                "tools": [{"name": "classroom_open_class", "preview": class_name[:40]}],
                "run_id": "classroom_open",
            }
        err = data.get("error") or f"No class like '{class_name}'."
        if data.get("classes"):
            err += " I see: " + "; ".join(str(x) for x in data["classes"][:8])
        return {
            "text": err,
            "tools": [{"name": "classroom_open_class", "preview": "miss"}],
            "run_id": "classroom_open",
        }

    if look_only and not check_todo and not check_classes and not solve:
        raw = page_look.look_at_browser({"site": "active", "screenshot": False, "max_chars": 4000})
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            data = {"ok": False, "error": str(raw)[:300]}
        if not data.get("ok"):
            msg = data.get("error") or "Couldn't read the screen."
        else:
            body = (data.get("text") or "").strip()
            if simple:
                msg = body[:700] or (data.get("title") or "Empty")
            else:
                title = data.get("title") or "the open tab"
                url = data.get("url") or ""
                msg = f"Looking at the current tab only ({title}). I did not open assignments or other pages.\n{url}\n{body[:700]}".strip()
        return {
            "text": msg,
            "tools": [{"name": "look_at_browser", "preview": "screen-only"}],
            "run_id": "look_screen",
        }

    if add_seen and not check_todo and not check_classes and not solve:
        snap = _load_snapshot()
        items = snap.get("dues") or []
        if not items:
            return {
                "text": (
                    "No Classroom snapshot yet."
                    if simple
                    else "I don't have a Classroom snapshot yet. Ask me to check everything first, then say add those to my calendar."
                ),
                "tools": [{"name": "classroom_check", "preview": "no snapshot"}],
                "run_id": "classroom_check",
            }
        raw = ba.classroom_check({"mode": "everything", "import_to_calendar": True, "max_assignments": 0})
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            data = {"ok": False, "error": str(raw)[:240]}
        if not data.get("ok"):
            return {
                "text": data.get("error") or (
                    "Couldn't add — sign in first."
                    if simple
                    else "Couldn't add Classroom items — sign in on the Jarvis Chrome window first."
                ),
                "tools": [{"name": "classroom_check", "preview": "import"}],
                "run_id": "classroom_check",
                "needs_calendar_refresh": False,
            }
        _save_snapshot(data)
        return {
            "text": "Added." if simple else "Added the dated Classroom items I can see to your calendar. I did not submit anything.",
            "tools": [{"name": "classroom_check", "preview": "import"}],
            "run_id": "classroom_check",
            "needs_calendar_refresh": True,
            "count": data.get("found") or 0,
        }

    if check_classes and not solve:
        raw = ba.classroom_check({"mode": "all_classes", "weeks": 2})
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            data = {"ok": False, "error": str(raw)[:300]}
        if data.get("ok"):
            _save_snapshot(data)
        return {
            "text": _format_classes_recap(data, simple=simple),
            "speak": _speak_classes_recap(data, simple=simple),
            "tools": [{"name": "classroom_check", "preview": "all_classes"}],
            "run_id": "classroom_check",
            "count": data.get("found") or 0,
        }

    mode = "solve" if solve else "everything"
    raw = ba.classroom_check({
        "mode": mode,
        "import_to_calendar": bool(add_seen),
        "max_assignments": 4 if solve else 0,
    })
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        data = {"ok": False, "error": str(raw)[:300]}

    if data.get("ok"):
        _save_snapshot(data)

    reply = _format_check(data, solve=solve, simple=simple)
    out: dict[str, Any] = {
        "text": reply,
        "speak": _speak_check(data, solve=solve, simple=simple),
        "tools": [{"name": "classroom_check", "preview": mode}],
        "run_id": "classroom_check",
        "needs_calendar_refresh": bool(add_seen and data.get("ok")),
        "count": data.get("found") or 0,
    }
    # If they asked for answers, hand the extracted questions to the brain — still no submit.
    if solve and data.get("ok") and (data.get("questions") or data.get("dues")):
        images = []
        for q in data.get("questions") or []:
            images.extend(q.get("images") or [])
        image_note = ""
        if images:
            paths = "; ".join(str(im.get("path") or "") for im in images[:2] if im.get("path"))
            image_note = (
                "\n[Attached classroom images are included. Look at the photo. "
                f"Extra copies if needed: {paths}. Do not submit.]\n"
            )
            first = next((im.get("path") for im in images if im.get("path")), None)
            if first:
                out["attachment_image"] = first
        simple_brain = (
            "[SIMPLE MODE] Answer the homework only — no class names, no fluff, no submit.\n"
            if simple
            else ""
        )
        out["brain_followup"] = (
            "[Classroom read-only. Do NOT submit, turn in, mark as done, or click Hand in. "
            "Open Google Docs text is below. If an image is attached, use what you see in it. "
            "Help with the questions. If something is unclear, ask one follow-up.]\n"
            + simple_brain
            + image_note
            + reply
        )
    return out
