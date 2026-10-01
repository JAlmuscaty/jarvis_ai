"""Hard-route: Google Docs/Slides in PC Chrome — essays, N-slide decks, plain typing (no OAuth)."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_PLUGIN_DIRS = [
    Path.home() / "AppData" / "Local" / "hermes" / "plugins",
    Path(__file__).resolve().parents[1] / "hermes-plugin",
]

_ESSAY = re.compile(
    r"(?is)\b(?:"
    r"(?:write|create|make|draft|type)\s+(?:(?:a|an|my|full(?:\s+on)?)\s+)?"
    r"(?:essay|article|report|paper)"
    r"(?:\s+(?:in|on|with|using)\s+(?:google\s+)?docs?)?"
    r"|(?:write|create|make|draft)\s+(?:(?:a|an|my)\s+)?"
    r"(?:google\s+)?docs?\s+(?:essay|article|report|paper|document|about|on)"
    r"|(?:write|create)\s+(?:(?:a|an)\s+)?(?:google\s+)?doc(?:ument)?\s+(?:about|on|titled)"
    r")\b"
)
_SLIDES = re.compile(
    r"(?is)\b(?:"
    r"(?:create|make|build|write|do)\s+(?:(?:a|an|my|full(?:\s+on)?)\s+)?"
    r"(?:google\s+)?(?:slides?|presentation|powerpoint|deck)"
    r"|(?:google\s+)?slides?\s+(?:about|on|for|presentation|with)"
    r"|\d+\s*-?\s*slides?\b"
    r")\b"
)
_DOCS_TYPE = re.compile(
    r"(?is)\b(?:"
    r"(?:write|type|put|make|create|draft)\b.{0,80}\b(?:google\s+)?docs?\b|"
    r"(?:open|new)\b.{0,30}\b(?:google\s+)?docs?\b.{0,40}\b(?:write|type|say|says)\b|"
    r"(?:write|type)\b.{0,40}\bin\b.{0,24}\b(?:google\s+)?docs?\b|"
    r"(?:write|type)\b.{0,40}\bin\b.{0,24}\b(?:a\s+)?(?:blank\s+)?(?:page|document)\b"
    r")\b"
)
_SLIDES_TYPE = re.compile(
    r"(?is)\b(?:"
    r"(?:write|type|put)\b.{0,60}\b(?:google\s+)?slides?\b|"
    r"(?:write|type)\b.{0,40}\bin\b.{0,20}\b(?:google\s+)?slides?\b"
    r")\b"
)
_HANDWRITING = re.compile(r"(?is)\bhand\s*-?\s*writing\b|\bبخط|\bخط[يى]\b")
_QUOTED = re.compile(r"[\"“](.+?)[\"”]", re.S)


def _docs_actions():
    last = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import docs_actions  # type: ignore
            return docs_actions
        except Exception as exc:
            last = exc
    raise RuntimeError(f"docs_actions unavailable: {last}")


def _wc():
    import workspace_content as wc
    return wc


def _extract_literal_text(text: str) -> tuple[str, str | None]:
    t = (text or "").strip()
    title = None
    m_title = re.search(r"(?is)\btitled?\s+[\"']?([^\"'\n]+)[\"']?", t)
    if m_title:
        title = m_title.group(1).strip()[:80]
    qm = _QUOTED.search(t)
    if qm and len(qm.group(1).strip()) > 1:
        return qm.group(1).strip()[:8000], title

    # write/type X in/into/on [the opened/blank] google doc(s) / page / document
    m = re.search(
        r"(?is)\b(?:write|type|put)\s+(.+?)\s+(?:in|into|on|to)\s+"
        r"(?:(?:a|an|my|the)\s+)?"
        r"(?:opened\s+|open\s+|new\s+|blank\s+|current\s+|this\s+)*"
        r"(?:google\s+)?(?:docs?|document|page)\b",
        t,
    )
    if m and len(m.group(1).strip()) >= 1:
        body = m.group(1).strip(" .:-\"'")
        body = re.sub(r"(?is)^(the\s+words?\s+|the\s+text\s+|something\s+like\s+)", "", body).strip()
        # Drop trailing location phrases if capture was greedy
        body = re.sub(
            r"(?is)\s+(?:in|into|on|to)\s+(?:(?:a|an|my|the)\s+)?(?:opened\s+|open\s+|new\s+|blank\s+)*(?:google\s+)?(?:docs?|document|page)\s*$",
            "",
            body,
        ).strip(" .:-\"'")
        if body and not re.search(r"(?is)^(?:google\s+)?(?:docs?|document|page)$", body):
            return body[:8000], title

    # write/type in google docs: X  /  write in docs X
    m = re.search(
        r"(?is)\b(?:write|type|put)\s+(?:it\s+)?"
        r"(?:in|into|on|to)\s+(?:(?:a|an|my|the)\s+)?"
        r"(?:opened\s+|open\s+|new\s+|blank\s+|current\s+|this\s+)*"
        r"(?:google\s+)?(?:docs?|document|page)\s*[:\-]?\s*(.+)$",
        t,
    )
    if m and len(m.group(1).strip()) >= 1:
        return m.group(1).strip(" .:-\"'")[:8000], title

    body = re.sub(
        r"(?is)^(?:please\s+|can you\s+|jarvis\s*,?\s*)?"
        r"(?:write|type|put|make|create|draft)\s+"
        r"(?:(?:a|an|my|in|into)\s+)?"
        r"(?:new\s+)?"
        r"(?:blank\s+)?"
        r"(?:google\s+)?(?:doc|docs|document|slides?|presentation|page)?\s*"
        r"(?:in\s+)?"
        r"(?:my\s+)?(?:hand\s*-?\s*writing\s*)?"
        r"(?:(?:with\s+)?(?:a\s+)?(?:pen|pencil)\s*)?"
        r"(?:in\s+(?:arabic|english)\s*)?"
        r"(?:that\s+says|saying|with(?:\s+the)?\s*(?:text|words)?|:\s*)?",
        "",
        t,
        count=1,
    ).strip(" .:-")
    body = re.sub(r"(?is)\s+in\s+(arabic|english|عربي)\s*$", "", body).strip()
    body = re.sub(
        r"(?is)\s+(?:in|into|on|to)\s+(?:(?:a|an|my|the)\s+)?"
        r"(?:opened\s+|open\s+|new\s+|blank\s+|current\s+|this\s+)*"
        r"(?:google\s+)?(?:docs?|document|page)\s*$",
        "",
        body,
    ).strip(" .:-")
    if re.search(r"(?is)\b(?:google\s+)?(?:docs?|slides?|document|page)\b", body) or len(body) < 1:
        m = re.search(r"(?is)\b(?:google\s+)?(?:docs?|slides?|presentation|document|page)\b\s*(.+)$", t)
        if m:
            body = re.sub(r"(?is)\s+in\s+(arabic|english|عربي)\s*$", "", m.group(1)).strip(" .:-")
    body = re.sub(r"(?is)^(?:s|doc|docs|slide|slides|page)\s+", "", body).strip()
    # Final cleanup: "hello in the opened google doc"
    body = re.sub(
        r"(?is)\s+(?:in|into|on|to)\s+(?:(?:a|an|my|the)\s+)?"
        r"(?:opened\s+|open\s+|new\s+|blank\s+|current\s+|this\s+)*"
        r"(?:google\s+)?(?:docs?|document|page)\s*$",
        "",
        body,
    ).strip(" .:-\"'")
    return (body or t)[:8000], title


_BLANK_DOC = re.compile(
    r"(?is)\b(?:"
    r"(?:open|create|make|start|new)\b.{0,40}\bblank\b.{0,24}\b(?:page|doc|docs?|document)\b"
    r"|\b(?:open|create|make)\b.{0,24}\b(?:a\s+|an\s+)?new\s+(?:blank\s+)?(?:google\s+)?docs?\b"
    r"|\bblank\s+(?:google\s+)?docs?\b"
    r"|\bnew\s+blank\s+(?:page|doc|docs?|document)\b"
    r")\b"
)


def open_blank_google_doc() -> dict[str, Any]:
    """Open a brand-new blank Google Doc in Chrome (create URL)."""
    da = _docs_actions()
    raw = da.google_docs_open_and_type({"text": "", "open_only": True})
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {"ok": False, "error": str(raw)}
    if data.get("ok"):
        url = data.get("url") or ""
        return {
            "ok": True,
            "text": "Opened a blank Google Doc." + (f"\n{url}" if url else ""),
            "tools": [{"name": "google_docs_blank", "preview": "blank"}],
            "run_id": "google_docs_blank",
            "webViewLink": url,
            "hud_url": url,
            "chrome": data,
        }
    return {
        "ok": False,
        "text": data.get("error") or "Could not open a blank Google Doc.",
        "tools": [{"name": "google_docs_blank", "preview": "failed"}],
        "run_id": "google_docs_blank",
        "chrome": data,
    }


_GEN_KIND = re.compile(
    r"(?is)^(?:(?:a|an|the|some|my|me|one)\s+)?"
    r"(?:(?:short|long|full|brief|quick|nice|good|detailed|simple|small|big|funny|sad|scary|formal|"
    r"informal|creative|cool|\d+\s*-?\s*(?:word|sentence|paragraph|line|page)s?|one\s*-?\s*page)\s+)*"
    r"(essay|story|paragraph|poem|letter|email|e-mail|summary|report|article|speech|list|notes|outline|"
    r"introduction|intro|conclusion|description|biography|bio|review|script|plan|explanation|definition|"
    r"song|joke|jokes|message|research|overview|facts?|information|info|text|something|stuff|lesson)"
    r"(?:\s+(?:about|on|of|for|explaining|describing|regarding|to|that|where|in\s+which|saying|comparing)\s+(.+))?$"
)


def classify_body(body: str) -> tuple[str, str, str]:
    """('generate', kind, topic) when they describe what to write; ('literal', text, '') to type verbatim."""
    b = (body or "").strip().strip("\"'“”")
    if not b or _QUOTED.search(body or ""):
        return "literal", b, ""
    m = re.match(r"(?is)^about\s+(.+)$", b)
    if m:
        return "generate", "paragraph", m.group(1).strip(" .")
    m = _GEN_KIND.match(b.rstrip(" .!?"))
    if m:
        kind = m.group(1).lower()
        topic = (m.group(2) or "").strip(" .")
        if kind in ("text", "something", "stuff", "information", "info", "fact", "facts"):
            if not topic:
                return "literal", b, ""
            kind = "short informative text"
        if kind in ("to", "that") and not topic:
            return "literal", b, ""
        return "generate", kind, topic or "a topic of your choice"
    return "literal", b, ""


def open_docs_and_type(text: str, *, body: str | None = None, title: str | None = None) -> dict[str, Any]:
    content, auto_title = _extract_literal_text(text) if not body else (body, None)
    title = title or auto_title
    mode, kind_or_text, topic = classify_body(content)
    generated = None
    if mode == "generate":
        generated = _wc().generate_writing(kind_or_text, topic, text)
        if not generated.get("text"):
            return {"ok": False, "text": f"I couldn't write the {kind_or_text} just now — try again.",
                    "run_id": "google_docs_chrome"}
        content = generated["text"]
        title = title or f"{kind_or_text.capitalize()} - {topic}"[:90]
    da = _docs_actions()
    raw = da.google_docs_open_and_type({"text": content, "title": title})
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {"ok": False, "error": str(raw)}
    if data.get("ok"):
        url = data.get("url") or ""
        lead = (
            f"Opened a new Google Doc and wrote a {kind_or_text} about {topic} ({len(content)} characters)."
            if generated else
            f"Opened a new Google Doc and typed: {content[:120]}" + ("…" if len(content) > 120 else "")
        )
        return {
            "ok": True,
            "speak": lead.split(" (")[0] if generated else "Done — typed it into a new Google Doc.",
            "text": lead + (f"\n{url}" if url else ""),
            "tools": [{"name": "google_docs_chrome_type", "preview": content[:40]}],
            "run_id": "google_docs_chrome",
            "webViewLink": url,
            "hud_url": url,
            "chrome": data,
        }
    return {
        "ok": False,
        "text": data.get("error") or data.get("message") or "Could not type into Google Docs in Chrome.",
        "tools": [{"name": "google_docs_chrome_type", "preview": "failed"}],
        "run_id": "google_docs_chrome",
        "chrome": data,
    }


def open_slides_and_type(text: str, *, body: str | None = None, title: str | None = None) -> dict[str, Any]:
    content, auto_title = _extract_literal_text(text) if not body else (body, None)
    title = title or auto_title
    da = _docs_actions()
    raw = da.google_slides_open_and_type({"text": content, "title": title})
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {"ok": False, "error": str(raw)}
    if data.get("ok"):
        url = data.get("url") or ""
        return {
            "ok": True,
            "text": (
                "Opened a new Google Slides deck in Chrome and typed your text."
                + (f"\n{url}" if url else "")
            ),
            "tools": [{"name": "google_slides_chrome_type", "preview": content[:40]}],
            "run_id": "google_slides_chrome",
            "webViewLink": url,
            "hud_url": url,
            "chrome": data,
        }
    return {
        "ok": False,
        "text": data.get("error") or data.get("message") or "Could not type into Google Slides in Chrome.",
        "tools": [{"name": "google_slides_chrome_type", "preview": "failed"}],
        "run_id": "google_slides_chrome",
        "chrome": data,
    }


def create_essay_in_docs(text: str) -> dict[str, Any]:
    """Generate a full essay from a description and type it into a new Google Doc."""
    wc = _wc()
    topic = wc.extract_topic(text)
    if not topic or len(topic) < 2:
        return {
            "ok": True,
            "text": "What should the essay be about?",
            "tools": [{"name": "google_docs_essay", "preview": "ask_topic"}],
            "run_id": "google_docs_essay_ask",
            "awaiting": "essay_topic",
        }
    t0 = time.perf_counter()
    essay = wc.generate_essay(topic, text)
    body = str(essay.get("body") or "").strip()
    title = str(essay.get("title") or topic)[:100]
    if not body:
        return {"ok": False, "text": "Could not generate the essay.", "run_id": "google_docs_essay"}
    # Prefer title + body in the Doc
    content = body if body.lstrip().startswith(title) else f"{title}\n\n{body}"
    da = _docs_actions()
    raw = da.google_docs_open_and_type({"text": content, "title": title})
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {"ok": False, "error": str(raw)}
    elapsed = round(time.perf_counter() - t0, 1)
    gen_ms = essay.get("latency_ms")
    if data.get("ok"):
        url = data.get("url") or ""
        return {
            "ok": True,
            "text": (
                f"Wrote a full essay on “{title}” into a new Google Doc in Chrome "
                f"({len(content)} chars, {elapsed}s total"
                + (f", gen {gen_ms}ms" if gen_ms is not None else "")
                + f", source={essay.get('source')})."
                + (f"\n{url}" if url else "")
            ),
            "tools": [{"name": "google_docs_essay", "preview": title[:40]}],
            "run_id": "google_docs_essay",
            "webViewLink": url,
            "hud_url": url,
            "essay": {"title": title, "source": essay.get("source"), "latency_ms": gen_ms},
            "chrome": data,
            "elapsed_sec": elapsed,
        }
    return {
        "ok": False,
        "text": data.get("error") or data.get("message") or "Essay ready but Docs typing failed.",
        "tools": [{"name": "google_docs_essay", "preview": "failed"}],
        "run_id": "google_docs_essay",
        "chrome": data,
        "essay": essay,
    }


def create_slides_deck(text: str) -> dict[str, Any]:
    """Build an exact-N slide deck in Chrome with Jarvis design + images. Ask only if topic missing."""
    wc = _wc()
    # Design-suggestions-only: do not open Slides
    if wc.wants_design_suggestions(text) and not re.search(
        r"(?is)\b(?:create|make|build|write|do)\b.{0,40}\b(?:slides?|presentation|deck)\b",
        text,
    ):
        topic = wc.extract_topic(text) or "your topic"
        n = wc.extract_slide_count(text, 8)
        return {
            "ok": True,
            "text": wc.design_suggestions_text(topic, text, n),
            "tools": [{"name": "google_slides_design_suggest", "preview": topic[:40]}],
            "run_id": "google_slides_design_suggest",
        }

    if wc.topic_missing_for_presentation(text):
        return {
            "ok": True,
            "text": "What should the presentation be about? (Optional: how many slides — default 8.)",
            "tools": [{"name": "google_slides_deck", "preview": "ask_topic"}],
            "run_id": "google_slides_ask_topic",
            "awaiting": "slides_topic",
        }

    topic = wc.extract_topic(text)
    n = wc.extract_slide_count(text, 8)
    t0 = time.perf_counter()
    gen = wc.generate_slides(topic, text, slide_count=n)
    slides = gen.get("slides") or []
    design = gen.get("design") or {}
    # Cap images for speed (still add some visuals)
    add_images = True
    if re.search(r"(?is)\bno\s+images?\b|\bwithout\s+images?\b", text):
        add_images = False

    da = _docs_actions()
    raw = da.google_slides_build_deck({
        "slides": slides,
        "design": design,
        "images": add_images,
        "title": gen.get("deck_title") or topic,
        "image_topic": topic,
    })
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {"ok": False, "error": str(raw)}
    elapsed = round(time.perf_counter() - t0, 1)
    if data.get("ok"):
        url = data.get("url") or ""
        filled = data.get("slides_filled") or len(slides)
        imgs = data.get("images_inserted") or 0
        return {
            "ok": True,
            "speak": f"Done — your {filled}-slide presentation on {topic} is ready in Google Slides.",
            "text": (
                f"Made a new Google Slides presentation on “{topic}”: {filled} slides"
                + (f" + a picture slide" if imgs else "")
                + f" ({elapsed}s, content: {gen.get('source')})."
                + (f"\n{url}" if url else "")
            ),
            "tools": [{"name": "google_slides_build_deck", "preview": f"{filled} slides"}],
            "run_id": "google_slides_deck",
            "webViewLink": url,
            "hud_url": url,
            "design": design,
            "chrome": data,
            "elapsed_sec": elapsed,
            "gen_ms": gen.get("latency_ms"),
        }
    return {
        "ok": False,
        "text": data.get("error") or data.get("message") or "Could not build the Slides deck in Chrome.",
        "tools": [{"name": "google_slides_build_deck", "preview": "failed"}],
        "run_id": "google_slides_deck",
        "chrome": data,
        "design": design,
        "slides": slides,
    }


_OPEN_AND = re.compile(
    r"(?is)\b(?:open|create|start|make|new|go\s+to)\b.{0,40}?\b(?:(?:google\s+)?(docs?|document)|(?:google\s+)?(slides?|presentation|slideshow|deck))\b"
    r"\s*(?:,|\band\b|\bthen\b|&|:)+\s*(?:then\s+)?"
    r"(?:(?:please\s+)?(type|write|put|add|make|create|do|build|say)\s+(?:(?:in|inside|on)\s+(?:it|there)\s+)?)?(.+)$"
)
_TRAIL_WHERE = re.compile(
    r"(?is)\s+(?:in|inside|into|on)\s+(?:it|there|that|the\s+(?:new\s+|blank\s+)?(?:doc|docs|document|page|slides?|presentation|deck|one))\s*[.!?]*$"
)
_DECK_REQ = re.compile(
    r"(?is)\b(?:presentation|slides?|slideshow|deck|powerpoint)\b|\b(?:about|on)\s+\S"
)
_FOLLOW_TYPE = re.compile(r"(?is)^(?:now\s+|then\s+|also\s+|and\s+|ok(?:ay)?\s+)?(?:type|write|put)\s+(.+)$")
_ADD_TO = re.compile(
    r"(?is)^(?:now\s+|then\s+|also\s+|and\s+)?add\s+(.+?)\s+(?:to|in|into|on)\s+(?:it|there|the\s+(?:doc|document|page|slides?|presentation|deck))\s*[.!?]*$"
)
_ADD_SLIDE = re.compile(
    r"(?is)\b(?:add|make|create|insert|put)\s+(?:a\s+|an\s+|another\s+|one\s+more\s+|(\d+|two|three|four|five)\s+(?:more\s+|new\s+)?)?"
    r"(?:new\s+|more\s+)?slides?\b(?:\s+(?:about|on|for|with|explaining|of|that)\s+(.+))?"
)
_NUMS = {"two": 2, "three": 3, "four": 4, "five": 5}


def _recent_target() -> tuple[str, dict] | None:
    """Most recent doc/deck Jarvis created that is still open (within 30 min)."""
    try:
        da = _docs_actions()
        recs = [(k, da.last_created(k, 1800)) for k in ("docs", "slides")]
    except Exception:
        return None
    recs = [(k, r) for k, r in recs if r]
    if not recs:
        return None
    return max(recs, key=lambda kr: float(kr[1].get("ts") or 0))


def plan_docs_action(text: str) -> dict[str, Any] | None:
    """Decide what they want done in Docs/Slides (no side effects)."""
    t = (text or "").strip()
    if not t:
        return None

    # "open google docs/slides and <do something>"
    m = _OPEN_AND.search(t)
    if m:
        is_slides = bool(m.group(2))
        verb = (m.group(3) or "").lower()
        body = _TRAIL_WHERE.sub("", m.group(4) or "").strip(" .:,-")
        if is_slides:
            asks_deck = bool(re.match(
                r"(?is)^(?:(?:a|an|the|some|my|me)\s+)?(?:\d{1,2}\s*-?\s*|new\s+|full\s+|short\s+|good\s+|nice\s+)*"
                r"(?:presentation|slides?|slideshow|deck|powerpoint)\b",
                body,
            )) or bool(re.match(r"(?is)^(?:about|on)\s+\S", body))
            if verb in ("make", "create", "build", "do") or asks_deck or not body:
                return {"action": "deck", "text": t}
            mode, kind, topic = classify_body(body)
            if mode == "generate":
                return {"action": "deck", "text": f"make a presentation about {topic}. {t}"}
            return {"action": "slides_type", "body": body}
        if body:
            if _ESSAY.search(f"write {body}") and re.search(r"(?is)\bessay\b", body):
                return {"action": "essay", "text": t}
            return {"action": "docs_type", "body": body, "text": t}

    # Follow-ups into the doc/deck Jarvis just created
    recent = _recent_target()
    if recent:
        kind, rec = recent
        ma = _ADD_SLIDE.search(t)
        if ma and (kind == "slides" or rec):
            n = ma.group(1)
            count = int(n) if n and n.isdigit() else _NUMS.get((n or "").lower(), 1)
            return {"action": "slides_add", "request": t, "count": max(1, min(5, count)),
                    "deck": rec.get("title") or ""}
        mf = _ADD_TO.match(t) or (
            _FOLLOW_TYPE.match(t) if not re.search(r"(?is)\b(?:docs?|document|slides?|presentation|email|gmail|message)\b", t) else None
        )
        if mf:
            body = _TRAIL_WHERE.sub("", mf.group(1)).strip(" .:,-")
            if kind == "slides":
                return {"action": "slides_add", "request": t, "count": 1, "deck": rec.get("title") or "", "body": body}
            return {"action": "docs_append", "body": body, "text": t}
    return None


def pending_ack(text: str) -> str | None:
    """Short line to speak right away before a slow Docs/Slides build."""
    try:
        plan = plan_docs_action(text)
    except Exception:
        plan = None
    t = text or ""
    if not plan:
        if _ESSAY.search(t) and not _HANDWRITING.search(t):
            return "On it — writing that essay in a new Google Doc."
        if re.search(r"(?is)\b(?:create|make|build)\b.{0,60}\b(?:slides?|presentation|deck)\b", t):
            return None if _wc().topic_missing_for_presentation(t) else "On it — making a new Google Slides presentation."
        if _DOCS_TYPE.search(t) and classify_body(_extract_literal_text(t)[0])[0] == "generate":
            return "On it — writing that in a new Google Doc."
        return None
    a = plan["action"]
    if a == "deck":
        wc = _wc()
        if wc.topic_missing_for_presentation(plan["text"]):
            return None
        return f"On it — making a new presentation about {wc.extract_topic(plan['text'])}."
    if a == "essay":
        return "On it — writing that essay in a new Google Doc."
    if a in ("docs_type", "docs_append"):
        mode, kind, _topic = classify_body(plan.get("body") or "")
        if mode == "generate":
            where = "a new Google Doc" if a == "docs_type" else "your document"
            return f"On it — writing that {kind} in {where}."
    if a == "slides_add":
        return "On it — adding that to your presentation."
    return None


def _docs_append(body: str, text: str) -> dict[str, Any]:
    mode, kind, topic = classify_body(body)
    content = body
    if mode == "generate":
        gen = _wc().generate_writing(kind, topic, text)
        content = gen.get("text") or ""
        if not content:
            return {"ok": False, "text": f"I couldn't write the {kind} just now.", "run_id": "google_docs_append"}
    da = _docs_actions()
    raw = da.google_docs_type_active({"text": "\n" + content if mode == "generate" else " " + content})
    data = json.loads(raw) if isinstance(raw, str) else raw
    ok = bool(data.get("ok"))
    return {
        "ok": ok,
        "text": (f"Added a {kind} about {topic} to your Google Doc." if mode == "generate"
                 else f"Typed into your Google Doc: {content[:120]}") if ok else (data.get("message") or "Typing failed."),
        "tools": [{"name": "google_docs_append", "preview": content[:40]}],
        "run_id": "google_docs_append",
    }


def _slides_add(plan: dict[str, Any]) -> dict[str, Any]:
    wc = _wc()
    deck = plan.get("deck") or "the presentation"
    body = plan.get("body")
    if body and classify_body(body)[0] == "literal":
        lines = [ln for ln in re.split(r"\n|(?<=[.!?])\s+", body) if ln.strip()]
        slides = [{"title": lines[0][:80], "body": "\n".join(lines[1:])}]
    else:
        slides = wc.generate_extra_slides(deck, plan["request"], plan.get("count", 1))
    if not slides:
        return {"ok": False, "text": "I couldn't write that slide just now.", "run_id": "google_slides_add"}
    raw = _docs_actions().google_slides_add_slides({"slides": slides})
    data = json.loads(raw) if isinstance(raw, str) else raw
    ok = bool(data.get("ok"))
    titles = ", ".join(s["title"] for s in slides if s.get("title"))
    return {
        "ok": ok,
        "text": f"Added {data.get('added') or 0} slide(s) to your presentation: {titles}." if ok
        else (data.get("error") or "Couldn't add the slide."),
        "tools": [{"name": "google_slides_add", "preview": titles[:40]}],
        "run_id": "google_slides_add",
    }


def try_handle_docs_chrome(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None

    plan = plan_docs_action(t)
    if plan:
        a = plan["action"]
        if a == "deck":
            return create_slides_deck(plan["text"])
        if a == "essay":
            return create_essay_in_docs(plan["text"])
        if a == "docs_type":
            return open_docs_and_type(t, body=plan["body"])
        if a == "slides_type":
            return open_slides_and_type(t, body=plan["body"])
        if a == "docs_append":
            return _docs_append(plan["body"], t)
        if a == "slides_add":
            return _slides_add(plan)

    # Blank Google Doc page (after "open google docs", or standalone)
    if _BLANK_DOC.search(t) and not re.search(r"(?is)\b(write|type|put|essay|slides?|presentation)\b", t):
        return open_blank_google_doc()

    creating_deck = bool(
        re.search(
            r"(?is)\b(?:create|make|build|write|do)\b.{0,60}\b(?:slides?|presentation|powerpoint|deck)\b"
            r"|\b\d+\s*-?\s*slides?\b",
            t,
        )
    )

    # Design suggestions only — never open Slides unless they also asked to create
    try:
        wc = _wc()
        if wc.wants_design_suggestions(t) and not creating_deck and not _ESSAY.search(t):
            topic = wc.extract_topic(t) or "your topic"
            n = wc.extract_slide_count(t, 8)
            return {
                "ok": True,
                "text": wc.design_suggestions_text(topic, t, n),
                "tools": [{"name": "google_slides_design_suggest", "preview": topic[:40]}],
                "run_id": "google_slides_design_suggest",
            }
    except Exception:
        pass

    # Full essay → Docs
    if _ESSAY.search(t) and not _HANDWRITING.search(t):
        return create_essay_in_docs(t)

    # Full presentation / N-slide deck (exact slide count, design chosen by Jarvis)
    if creating_deck or (_SLIDES.search(t) and not _QUOTED.search(t)):
        return create_slides_deck(t)

    # Literal type into Docs (incl. handwriting phrasing → still type in Chrome)
    # Match singular "doc" as well as "docs"
    if _DOCS_TYPE.search(t) or (_HANDWRITING.search(t) and re.search(r"(?is)\bdocs?\b", t)):
        return open_docs_and_type(t)

    # Literal type into Slides
    if _SLIDES_TYPE.search(t):
        return open_slides_and_type(t)

    return None
