"""Ingest handwriting sample photos into a durable profile."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

try:
    from handwriting_store import add_sample_bytes, decode_data_url, status as hw_status
    from memory_store import upsert_fact
except ImportError:
    from .handwriting_store import add_sample_bytes, decode_data_url, status as hw_status  # type: ignore
    from .memory_store import upsert_fact  # type: ignore

_MEMORIZE_RE = re.compile(
    r"(?is)\b(?:"
    r"(?:memorize|remember|learn|save|store|capture)\s+(?:my\s+)?hand\s*-?\s*writing"
    r"|hand\s*-?\s*writing\s+(?:sample|style|profile)"
    r"|(?:this\s+is\s+)?my\s+hand\s*-?\s*writing"
    r"|learn\s+(?:how\s+)?i\s+write"
    r"|حفظ\s*(?:خط[يى]|الخط)"
    r"|هذا\s*خط[يى]"
    r")\b"
)

_ANALYZE_PROMPT = """Analyze this PHOTO of someone's HANDWRITING (not printed text).

Reply with ONLY JSON (no markdown):
{"languages":["en"|"ar",...],"medium":"pen"|"pencil"|"marker"|"unknown","style":{"slant":"left|right|upright","size":"small|medium|large","pressure":"light|medium|heavy","ink_color":"blue|black|gray|other","lined_paper":true|false,"notes":"short description of distinctive traits"}}

Rules:
- Detect Arabic and/or English script.
- medium: pen vs pencil vs marker from stroke look (graphite = pencil).
- If not handwriting, still guess best-effort and set notes accordingly.
"""


def wants_handwriting_memorize(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_MEMORIZE_RE.search(t))


def _parse_analysis(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if m:
        s = m.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start : end + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    langs = data.get("languages") or []
    if isinstance(langs, str):
        langs = [langs]
    langs = [str(x).lower()[:8] for x in langs if str(x).strip()]
    medium = str(data.get("medium") or "unknown").lower().strip()
    if medium not in ("pen", "pencil", "marker", "unknown"):
        medium = "unknown"
    style = data.get("style") if isinstance(data.get("style"), dict) else {}
    return {"languages": langs or ["en"], "medium": medium, "style": style}


def ingest_handwriting_photo(
    *,
    image_data_url: str,
    user_text: str,
    memory_path: Path,
    extract_fn: Callable[[str, str], str],
) -> dict[str, Any]:
    prompt = f"{_ANALYZE_PROMPT}\nUser said: {(user_text or '')[:200]}"
    raw = ""
    try:
        raw = extract_fn(prompt, image_data_url)
    except Exception as exc:
        raw = ""
        analysis = {"languages": ["en"], "medium": "unknown", "style": {"notes": f"analyze failed: {exc}"}}
    else:
        analysis = _parse_analysis(raw)

    try:
        blob, ext = decode_data_url(image_data_url)
    except Exception as exc:
        return {
            "text": f"I couldn't save that handwriting photo ({exc}). Try sending the image again.",
            "tools": [{"name": "handwriting_memorize", "preview": "error"}],
            "run_id": "handwriting_memorize",
            "ok": False,
        }

    result = add_sample_bytes(
        blob,
        ext=ext,
        languages=analysis.get("languages"),
        medium=analysis.get("medium"),
        style=analysis.get("style"),
        note=(user_text or "")[:200],
    )
    profile = result["profile"]
    sample = result["sample"]

    # Never-forget pointer in long-term memory
    try:
        upsert_fact(memory_path, {
            "title": "My handwriting",
            "key": "handwriting_profile",
            "value": (
                f"Handwriting profile '{profile.get('name')}' saved "
                f"({len(profile.get('samples') or [])} samples). "
                f"Languages: {', '.join(profile.get('languages') or []) or 'unknown'}. "
                f"Mediums: {', '.join(profile.get('mediums') or []) or 'unknown'}. "
                "Jarvis can write Google Doc / pages in this handwriting."
            ),
            "category": "personal",
            "source": "handwriting",
        })
    except Exception:
        pass

    langs = ", ".join(analysis.get("languages") or []) or "unknown"
    medium = analysis.get("medium") or "unknown"
    st = hw_status()
    return {
        "ok": True,
        "text": (
            f"Memorized your handwriting forever ({medium}, {langs}). "
            f"I now have {st.get('sample_count', 0)} sample(s) saved. "
            "Say something like: write a Google Doc in my handwriting that says … "
            "You can send more samples (Arabic and English, pen or pencil) to improve the match."
        ),
        "tools": [{"name": "handwriting_memorize", "preview": f"{medium}/{langs}"}],
        "run_id": "handwriting_memorize",
        "profile": profile,
        "sample": sample,
        "analysis": analysis,
        "raw_extract": (raw or "")[:400],
    }
