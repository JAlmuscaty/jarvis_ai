"""Create typed Google Docs essays and Google Slides presentations."""
from __future__ import annotations

import re
from typing import Any

_ESSAY_RE = re.compile(
    r"(?is)\b(?:"
    r"(?:write|create|make|draft)\s+(?:(?:a|an|my)\s+)?"
    r"(?:full\s+)?(?:essay|article|report|paper|document)"
    r"(?:\s+(?:in|on|with|using)\s+(?:google\s+)?docs?)?"
    r"|(?:write|create|make|draft)\s+(?:(?:a|an|my)\s+)?"
    r"(?:google\s+)?docs?\s+(?:essay|article|report|paper|document|about|on)"
    r"|(?:write|create)\s+(?:(?:a|an)\s+)?(?:google\s+)?doc(?:ument)?\s+(?:about|on|titled)"
    r")\b"
)

_SLIDES_RE = re.compile(
    r"(?is)\b(?:"
    r"(?:create|make|build|write)\s+(?:(?:a|an|my)\s+)?"
    r"(?:full\s+)?(?:google\s+)?(?:slides?|presentation|powerpoint|deck)"
    r"|(?:google\s+)?slides?\s+(?:about|on|for|presentation)"
    r")\b"
)

_HANDWRITING_HINT = re.compile(r"(?is)\bhand\s*-?\s*writing\b|\bبخط|\bخط[يى]\b")


def wants_docs_essay(text: str) -> bool:
    t = text or ""
    if _HANDWRITING_HINT.search(t):
        return False  # handwriting path owns these
    return bool(_ESSAY_RE.search(t))


def wants_slides(text: str) -> bool:
    return bool(_SLIDES_RE.search(t := (text or "")))


def _topic_from(text: str) -> str:
    t = (text or "").strip()
    qm = re.search(r"[\"“](.+?)[\"”]", t, re.S)
    if qm and len(qm.group(1).strip()) > 2:
        return qm.group(1).strip()[:500]
    t2 = re.sub(
        r"(?is)^(?:please\s+|can you\s+|jarvis\s*,?\s*)?"
        r"(?:write|create|make|draft|build)\s+(?:(?:a|an|my)\s+)?"
        r"(?:full\s+)?(?:google\s+)?"
        r"(?:docs?\s+|slides?\s+|presentation\s+|essay\s+|article\s+|report\s+|paper\s+|document\s+|deck\s+)?"
        r"(?:about|on|for|titled)?\s*",
        "",
        t,
        count=1,
    ).strip(" .:-")
    return (t2 or t)[:500]


def create_google_doc_essay(
    text: str,
    *,
    title: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    topic = body or _topic_from(text)
    doc_title = title or (topic.split("\n", 1)[0][:80] if topic else "Essay")
    # If user only gave a topic, expand into a short structured essay scaffold they can edit
    if body:
        content = body.strip()
    elif len(topic) > 400 or "\n" in topic:
        content = topic
    else:
        content = (
            f"{doc_title}\n\n"
            f"Introduction\n"
            f"This essay explores {topic}.\n\n"
            f"Main points\n"
            f"1. Background and context for {topic}.\n"
            f"2. Key arguments and evidence.\n"
            f"3. Analysis and discussion.\n\n"
            f"Conclusion\n"
            f"In summary, {topic} matters because it affects how we understand the topic going forward.\n\n"
            f"(Ask Jarvis to expand any section into a longer full essay.)"
        )

    try:
        from connectors import google_oauth
    except ImportError:
        from .connectors import google_oauth  # type: ignore

    result = google_oauth.docs_create_text(doc_title, content)
    if not result.get("ok"):
        return {
            "ok": False,
            "text": (
                result.get("error")
                or "Could not create the Google Doc. Reconnect Google Docs in CONNECT with write access."
            ),
            "tools": [{"name": "google_docs_create", "preview": "failed"}],
            "run_id": "google_docs_create",
            "docs": result,
        }
    link = result.get("webViewLink")
    return {
        "ok": True,
        "text": f"Created your Google Doc “{doc_title}”. Open it: {link}",
        "tools": [{"name": "google_docs_create", "preview": doc_title[:40]}],
        "run_id": "google_docs_create",
        "webViewLink": link,
        "hud_url": link,
        "docs": result,
    }


def create_google_slides(
    text: str,
    *,
    title: str | None = None,
    slides: list[dict] | None = None,
) -> dict[str, Any]:
    topic = _topic_from(text)
    deck_title = title or (f"Presentation: {topic[:60]}" if topic else "Presentation")

    if slides:
        slide_specs = slides
    else:
        # Sensible default full deck structure from a topic
        slide_specs = [
            {"title": deck_title, "body": topic},
            {"title": "Agenda", "body": "1. Overview\n2. Key points\n3. Details\n4. Summary\n5. Next steps"},
            {"title": "Overview", "body": f"What this presentation covers about {topic}."},
            {"title": "Key point 1", "body": f"Important background on {topic}."},
            {"title": "Key point 2", "body": f"Main argument or finding related to {topic}."},
            {"title": "Key point 3", "body": f"Supporting details and examples for {topic}."},
            {"title": "Summary", "body": f"The main takeaways about {topic}."},
            {"title": "Next steps / Q&A", "body": "Questions, discussion, and follow-up actions."},
        ]

    try:
        from connectors import google_oauth
    except ImportError:
        from .connectors import google_oauth  # type: ignore

    result = google_oauth.slides_create_presentation(deck_title, slide_specs)
    if not result.get("ok"):
        return {
            "ok": False,
            "text": (
                result.get("error")
                or "Could not create Google Slides. Reconnect Google Slides in CONNECT with write access."
            ),
            "tools": [{"name": "google_slides_create", "preview": "failed"}],
            "run_id": "google_slides_create",
            "slides": result,
        }
    link = result.get("webViewLink")
    n = result.get("slide_count") or len(slide_specs)
    return {
        "ok": True,
        "text": f"Created a {n}-slide Google Slides deck “{deck_title}”. Open it: {link}",
        "tools": [{"name": "google_slides_create", "preview": f"{n} slides"}],
        "run_id": "google_slides_create",
        "webViewLink": link,
        "hud_url": link,
        "slides": result,
    }


def try_handle_google_workspace(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None
    if wants_slides(t):
        return create_google_slides(t)
    if wants_docs_essay(t):
        return create_google_doc_essay(t)
    return None
