"""Reply-language preference + Arabic/Kuwaiti input hints for Jarvis."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

# Explicit switches — English reply is default unless user asks otherwise
_SWITCH_TO_AR = re.compile(
    r"(?is)(?:"
    r"^\s*/(?:ar|arabic)\s*$|"
    r"\b(?:speak|reply|answer|respond)\s+(?:in\s+)?arabic\b|"
    r"\b(?:switch|change)\s+to\s+arabic\b|"
    r"\bin\s+arabic\s+please\b|"
    r"بالعربي|بالعربية|رد\s*بالعربي|جاوب\s*بالعربي|تكلم\s*عربي"
    r")"
)
_SWITCH_TO_EN = re.compile(
    r"(?is)(?:"
    r"^\s*/(?:en|english)\s*$|"
    r"\b(?:speak|reply|answer|respond)\s+(?:in\s+)?english\b|"
    r"\b(?:switch|change)\s+to\s+english\b|"
    r"\bin\s+english\s+please\b|"
    r"بالانجليزي|بالإنجليزي|رد\s*انجليزي|جاوب\s*انجليزي|تكلم\s*انجليزي"
    r")"
)


def _prefs_path() -> Path:
    logs = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
    return logs / "language_prefs.json"


def _empty() -> dict[str, Any]:
    return {"reply_lang": "en", "updated_at": None}


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or _prefs_path()
    with _LOCK:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = _empty()
        if not isinstance(data, dict):
            data = _empty()
        lang = str(data.get("reply_lang") or "en").lower()
        data["reply_lang"] = "ar" if lang.startswith("ar") else "en"
        return data


def save(data: dict[str, Any], path: Path | None = None) -> None:
    import time

    p = path or _prefs_path()
    with _LOCK:
        out = dict(data)
        out["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def has_arabic(text: str | None) -> bool:
    return bool(text and _ARABIC_RE.search(text))


def detect_reply_switch(text: str | None) -> str | None:
    """Return 'ar' / 'en' if the user explicitly asks to change reply language."""
    if not text:
        return None
    if _SWITCH_TO_AR.search(text):
        return "ar"
    if _SWITCH_TO_EN.search(text):
        return "en"
    return None


def apply_switch_from_text(text: str | None) -> str:
    """Update sticky reply language if the user asked; return current reply_lang."""
    prefs = load()
    switch = detect_reply_switch(text)
    if switch and switch != prefs.get("reply_lang"):
        prefs["reply_lang"] = switch
        save(prefs)
    return str(prefs.get("reply_lang") or "en")


def language_hint_for_prompt(user_text: str | None) -> str:
    """Prefix Hermes sees every turn: Kuwaiti Arabic in, English out (unless switched)."""
    reply_lang = apply_switch_from_text(user_text)
    arabic_in = has_arabic(user_text)

    if reply_lang == "ar":
        reply_rule = (
            "REPLY LANGUAGE: Arabic (Kuwaiti Gulf dialect is fine). "
            "The user asked for Arabic replies — keep answering in Arabic until they ask for English "
            "(or type /english)."
        )
    else:
        reply_rule = (
            "REPLY LANGUAGE: English ONLY. "
            "Hard rule: every spoken and typed reply must be in clear English. "
            "Even if the user writes or speaks Arabic (including Kuwaiti dialect), reply in English. "
            "Do not mix Arabic into the reply unless they explicitly ask (e.g. /arabic or 'reply in Arabic')."
        )

    understand = (
        "INPUT: The user may use English, Modern Standard Arabic, or Kuwaiti Gulf dialect "
        "(كلمات مثل: زين، شلونك، يالله، ابي، وين، هالحين، بعدين، خلاص، تعال، افتح، اتصل). "
        "Understand Kuwaiti accent/spelling and Arabizi/code-switching; map dialect commands to the same tools "
        "(e.g. افتح يوتيوب → open YouTube, اتصل علي → call Ali)."
    )
    if arabic_in:
        understand += " This turn contains Arabic script — treat it as intentional Kuwaiti/Arabic speech or typing."

    return f"[{understand} {reply_rule}]\n"


def parse_lang_slash(text: str | None) -> dict[str, Any] | None:
    """Bare /english or /arabic → sticky switch + ack (no Hermes)."""
    raw = (text or "").strip()
    if not raw:
        return None
    if re.match(r"(?is)^\s*/(?:en|english)\s*$", raw):
        prefs = load()
        prefs["reply_lang"] = "en"
        save(prefs)
        return {"ack": "Replies set to English."}
    if re.match(r"(?is)^\s*/(?:ar|arabic)\s*$", raw):
        prefs = load()
        prefs["reply_lang"] = "ar"
        save(prefs)
        return {"ack": "Replies set to Arabic until you type /english."}
    return None
