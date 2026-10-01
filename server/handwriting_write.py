"""Write documents in memorized handwriting and upload to Google Drive/Docs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from handwriting_render import pages_to_pdf, render_handwritten_pages
    from handwriting_store import has_handwriting, status as hw_status
except ImportError:
    from .handwriting_render import pages_to_pdf, render_handwritten_pages  # type: ignore
    from .handwriting_store import has_handwriting, status as hw_status  # type: ignore

_WRITE_RE = re.compile(
    r"(?is)\b(?:"
    r"(?:write|make|create|draft)\s+(?:(?:a|an|my)\s+)?"
    r"(?:google\s+)?(?:doc|docs|document|pdf|note|letter|page|pages?)"
    r".{0,60}(?:in\s+)?(?:my\s+)?hand\s*-?\s*writing"
    r"|(?:in\s+my\s+hand\s*-?\s*writing)\b.{0,80}"
    r"|(?:write|اكتب).{0,60}(?:بخط[يى]|خط[يى]|hand\s*-?\s*writing)"
    # Common short forms when handwriting is already memorized
    r"|(?:write|make|create|draft)\s+(?:(?:it|this|that)\s+)?(?:in\s+)?(?:google\s+)?docs?"
    r".{0,40}(?:hand\s*-?\s*writing|بخط|خط[يى])"
    r"|(?:write|make|create)\s+in\s+(?:google\s+)?docs?.{0,80}(?:hand\s*-?\s*writing|arabic|english|بخط)"
    r")\b"
)

_DOC_WRITE_LOOSE = re.compile(
    r"(?is)\b(?:write|make|create|draft)\b.{0,40}\b(?:google\s+)?docs?\b"
)


def wants_handwriting_write(text: str) -> bool:
    t = text or ""
    if _WRITE_RE.search(t):
        return True
    # If handwriting is already memorized and they ask to write a Google Doc with
    # a short phrase / language, treat it as handwriting write (not typed essay).
    if _DOC_WRITE_LOOSE.search(t) and has_handwriting():
        if re.search(r"(?is)\b(hand\s*-?\s*writing|arabic|english|pencil|pen|بخط|خط[يى]|عربي)\b", t):
            return True
        # Photo+short "write ... docs ... hi i love" after memorizing
        if len(t) < 160 and not re.search(r"(?is)\b(essay|article|report|presentation|slides?)\b", t):
            return True
    return False


def _extract_body(text: str) -> tuple[str, str | None, str | None, str | None]:
    """Return (body, title, language, medium) from a user utterance."""
    t = (text or "").strip()
    medium = None
    if re.search(r"\bpencil\b", t, re.I):
        medium = "pencil"
    elif re.search(r"\bpen\b", t, re.I):
        medium = "pen"
    language = None
    if re.search(r"\barabic\b|\bعربي", t, re.I):
        language = "ar"
    elif re.search(r"\benglish\b|\beng\b", t, re.I):
        language = "en"

    title = None
    m_title = re.search(r"(?is)\btitled?\s+[\"']?([^\"'\n]+)[\"']?", t)
    if m_title:
        title = m_title.group(1).strip()[:80]

    body = t
    qm = re.search(r"[\"“](.+?)[\"”]", t, re.S)
    if qm and len(qm.group(1).strip()) > 3:
        body = qm.group(1).strip()
    else:
        body = re.sub(
            r"(?is)^(?:please\s+|can you\s+|jarvis\s*,?\s*)?"
            r"(?:write|make|create|draft)\s+"
            r"(?:(?:a|an|my|in)\s+)?"
            r"(?:google\s+)?(?:doc|docs|document|pdf|note|letter|page|pages?)?\s*"
            r"(?:in\s+)?"
            r"(?:my\s+)?(?:hand\s*-?\s*writing\s*)?"
            r"(?:(?:with\s+)?(?:a\s+)?(?:pen|pencil)\s*)?"
            r"(?:in\s+(?:arabic|english)\s*)?"
            r"(?:that\s+says|saying|with(?:\s+the)?\s*(?:text|words)?|:\s*)?",
            "",
            t,
            count=1,
        ).strip(" .:-")
        # Strip trailing language tags like "in arabic"
        body2 = re.sub(r"(?is)\s+in\s+(arabic|english|عربي)\s*$", "", body).strip()
        if body2:
            body = body2
        if len(body) < 2:
            body = t
        # If body still looks like the full command, try to pull words after "docs"
    if re.search(r"(?is)\b(?:google\s+)?docs?\b", body) or body.startswith("s "):
        m = re.search(
            r"(?is)\b(?:google\s+)?docs?\s+(?:in\s+my\s+hand\s*-?\s*writing\s+)?"
            r"(?:that\s+says\s+|saying\s+|:\s*)?(.+)$",
            t,
        )
        if m:
            body = re.sub(r"(?is)\s+in\s+(arabic|english|عربي)\s*$", "", m.group(1)).strip(" .:-")
        else:
            m2 = re.search(r"(?is)\bdocs?\b\s*(.+)$", t)
            if m2:
                body = re.sub(r"(?is)\s+in\s+(arabic|english|عربي)\s*$", "", m2.group(1)).strip(" .:-")
    # Drop leading junk like lone "s" from "docs"
    body = re.sub(r"(?is)^(?:s|doc|docs)\s+", "", body).strip()
    if len(body) < 2:
        body = t
    return body[:8000], title, language, medium


def write_handwritten_document(
    text: str,
    *,
    body: str | None = None,
    title: str | None = None,
    language: str | None = None,
    medium: str | None = None,
    upload: bool = True,
) -> dict[str, Any]:
    if not has_handwriting():
        return {
            "ok": False,
            "text": (
                "I don't have your handwriting memorized yet. "
                "Send a clear photo of your handwriting and say: memorize my handwriting."
            ),
            "tools": [{"name": "handwriting_write", "preview": "missing profile"}],
            "run_id": "handwriting_write",
        }

    if body:
        content, lang, med = body, language, medium
        doc_title = title
    else:
        content, doc_title, lang, med = _extract_body(text)
        lang = language or lang
        med = medium or med
        if title:
            doc_title = title

    rendered = render_handwritten_pages(
        content,
        language=lang,
        medium=med,
        title=doc_title,
    )
    if not rendered.get("ok"):
        return {
            "ok": False,
            "text": rendered.get("error") or "Couldn't render handwriting pages.",
            "tools": [{"name": "handwriting_write", "preview": "render fail"}],
            "run_id": "handwriting_write",
        }

    pages = rendered.get("pages") or []
    pdf_path = None
    try:
        pdf_path = pages_to_pdf(pages)
    except Exception as exc:
        return {
            "ok": False,
            "text": f"Rendered pages but PDF failed: {exc}",
            "pages": pages,
            "run_id": "handwriting_write",
        }

    out: dict[str, Any] = {
        "ok": True,
        "pages": pages,
        "page_count": len(pages),
        "pdf_path": str(pdf_path),
        "language": rendered.get("language"),
        "medium": rendered.get("medium"),
        "run_id": "handwriting_write",
        "tools": [{"name": "handwriting_write", "preview": f"{len(pages)} page(s)"}],
    }

    drive = None
    docs = None
    if upload:
        try:
            from connectors import google_oauth
        except ImportError:
            from .connectors import google_oauth  # type: ignore
        drive = google_oauth.drive_upload_file(
            pdf_path,
            name=f"{(doc_title or 'Handwritten note')[:80]}.pdf",
            mime_type="application/pdf",
        )
        out["drive"] = drive
        # Also try a Google Doc with page images (best-effort)
        docs = google_oauth.docs_create_with_images(
            doc_title or "Handwritten note",
            pages,
        )
        out["docs"] = docs

    link = (docs or {}).get("webViewLink") or (drive or {}).get("webViewLink")
    bits = [
        f"Wrote {len(pages)} handwritten page(s) "
        f"({rendered.get('medium')}, {rendered.get('language')})."
    ]
    if link:
        bits.append(f"Open it here: {link}")
    elif (drive or {}).get("needs_reauth") or (docs or {}).get("needs_reauth") or (drive or {}).get("needs_link"):
        bits.append(
            "Pages are saved on this PC. Reconnect Google Drive/Docs in the CONNECT HUD "
            "(write access) so I can put them in your Google account."
        )
        bits.append(f"Local PDF: {pdf_path}")
    else:
        bits.append(f"Saved locally as PDF: {pdf_path}")
        if (drive or {}).get("error"):
            bits.append(f"Drive upload: {drive.get('error')}")

    out["text"] = " ".join(bits)
    out["webViewLink"] = link
    out["hud_url"] = link
    return out
