"""Translate Kuwaiti/Arabic (and common Arabizi) Jarvis commands into English.

Runs before hard-routes and Hermes so e.g. «افتح الافلام» → «open movies».
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

_AR_CHAR = re.compile(r"[\u0600-\u06FF]")

# Verb → English
_OPEN_VERBS = (
    r"(?:افتح|أفتح|شغل|شغّل|شغلي|افتحلي|افتح\s*لي|ودني|ودّني|روح|روّح|شوف|"
    r"aftah|aft7|ifta7|shaghel|shaghil)"
)
_CALL_VERBS = r"(?:اتصل|اتّصل|كلم|كلّم|رن|رنّ)"
_SEARCH_VERBS = r"(?:دور|دوّر|ابحث|لقّط|لقط)"
_STOP_VERBS = r"(?:وقف|أوقف|اوقف|سكّت|سكت|وقفّ)"

# Arabic / Kuwaiti app names → English allowlist ids / phrases
_APP_PATTERNS: list[tuple[str, str]] = [
    (r"(?:ال)?افلام|(?:ال)?أفلام|(?:ال)?افلام|(?:ال)?فيلم|(?:ال)?افلامات|فيدبوكس|فيد\s*بوكس|السينما|سينما|vidbox|movies?", "movies"),
    (r"(?:ال)?يوتيوب|يو\s*تيوب|youtu\s*be|\byt\b", "youtube"),
    (r"(?:ال)?واتساب|واتس\s*اب|واتس|whats?app|\bwa\b", "whatsapp"),
    (r"(?:ال)?كروم|قوقل\s*كروم|جوجل\s*كروم|chrome|google\s*chrome", "chrome"),
    (r"(?:ال)?جيميل|قوقل\s*ميل|جوجل\s*ميل|gmail|google\s*mail", "gmail"),
    (r"(?:ال)?خرائط|(?:ال)?ماب|قوقل\s*ماب|جوجل\s*ماب|maps?|google\s*maps?", "maps"),
    (r"تشات\s*جي\s*بي\s*تي|شات\s*جي\s*بي\s*تي|شات\s*جبت|chatgpt|chat\s*gpt", "chatgpt"),
    (r"(?:ال)?كلاس\s*روم|قوقل\s*كلاس|classroom|google\s*classroom", "classroom"),
    (r"نوت\s*بوك(?:\s*ال\s*ام)?|نوتبوك|notebook\s*lm|notebooklm", "notebooklm"),
    (r"(?:ال)?سلايدز|قوقل\s*سلايدز|slides|google\s*slides", "google_slides"),
    (r"(?:ال)?دوكس|قوقل\s*دوكس|docs?|google\s*docs?", "google_docs"),
    (r"(?:ال)?شيتس|قوقل\s*شيتس|sheets|google\s*sheets", "google_sheets"),
    (r"(?:ال)?درايف|قوقل\s*درايف|drive|google\s*drive", "google_drive"),
    (r"(?:ال)?كالندر|قوقل\s*كالندر|calendar|google\s*calendar", "google_calendar"),
    (r"(?:ال)?انستغرام|(?:ال)?انستقرام|instagram|\big\b", "instagram"),
]


@dataclass
class TranslateResult:
    original: str
    translated: str
    changed: bool
    kind: str | None = None
    meta: dict[str, Any] | None = None


def _fold_ar(text: str) -> str:
    t = (text or "").strip()
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
    # Keep ى as-is so «على» does not become «علي» (the name Ali)
    t = t.replace("ؤ", "و").replace("ئ", "ي").replace("ء", "")
    t = re.sub(r"[\u064B-\u065F\u0670]", "", t)  # harakat
    t = re.sub(r"[ـ]+", "", t)  # tatweel
    t = re.sub(r"\s+", " ", t).strip()
    return t


def has_arabic(text: str | None) -> bool:
    return bool(text and _AR_CHAR.search(text))


def _match_app(chunk: str) -> str | None:
    c = _fold_ar(chunk).lower()
    c = re.sub(r"^(ال)", "", c)
    for pat, app_id in _APP_PATTERNS:
        if re.search(pat, c, flags=re.I):
            return app_id
    return None


def _english_app_phrase(app_id: str) -> str:
    # Prefer phrases hard-routes / open_pc_app aliases already understand
    return {
        "movies": "movies",
        "youtube": "youtube",
        "whatsapp": "whatsapp",
        "chrome": "chrome",
        "gmail": "gmail",
        "maps": "maps",
        "chatgpt": "chatgpt",
        "classroom": "classroom",
        "notebooklm": "notebooklm",
        "google_slides": "google slides",
        "google_docs": "google docs",
        "google_sheets": "google sheets",
        "google_drive": "google drive",
        "google_calendar": "google calendar",
        "instagram": "instagram",
    }.get(app_id, app_id.replace("_", " "))


def translate_command(text: str | None) -> TranslateResult:
    """
    If the utterance is (or contains) an Arabic Jarvis command, return an English
    equivalent the existing hard-routes / tools understand. Otherwise return unchanged.
    """
    original = (text or "").strip()
    if not original:
        return TranslateResult(original="", translated="", changed=False)

    # Strip voice/brain prefixes for matching, keep them out of translation input
    bare = re.sub(r"^\[.*?\]\s*", "", original, flags=re.S).strip()
    folded = _fold_ar(bare)
    low = folded.lower()

    # --- dual-brain layer switch ---
    if re.search(
        r"(?:استخدم|روح)\s*(?:ال)?طبقة\s*الثانية|استخدم\s*شات\s*جي\s*بي\s*تي|اسأل\s*شات",
        folded,
        flags=re.I,
    ):
        rest = re.sub(
            r"^(?:استخدم|روح)\s*(?:ال)?طبقة\s*الثانية\s*(?:و|علشان|:)?\s*|^استخدم\s*شات\s*جي\s*بي\s*تي\s*(?:و|:)?\s*",
            "",
            folded,
            flags=re.I,
        ).strip()
        en = "use layer 2" + (f" {rest}" if rest and rest != folded else "")
        return TranslateResult(original, en, True, "layer2")

    if re.search(
        r"(?:استخدم|روح)\s*(?:ال)?طبقة\s*(?:الاولى|الأولى)|وضع\s*تلقائي",
        folded,
        flags=re.I,
    ):
        return TranslateResult(original, "use layer 1", True, "layer1")

    # --- stop ---
    if re.fullmatch(rf"{_STOP_VERBS}\s*[.!]?", folded, flags=re.I):
        return TranslateResult(original, "stop", True, "stop")

    # --- briefing ---
    if re.search(
        r"(?:بريفنق|بريڤنق|الملخص|ملخص\s*اليوم|وش\s*عندي\s*اليوم|شو\s*عندي\s*اليوم|"
        r"جدول\s*اليوم|كيف\s*يومي)",
        folded,
        flags=re.I,
    ):
        return TranslateResult(original, "give me a briefing", True, "briefing")

    # --- maps ETA: من X ل Y / كم تاخذ من X ل Y ---
    m = re.search(
        rf"(?:كم\s*(?:تاخذ|تااخذ|ياخذ|وقت|دقايق|دقائق)\s*)?من\s+(.+?)\s+(?:إلى|الى|إلي|لـ|ل)\s*(.+?)\s*$",
        folded,
        flags=re.I,
    )
    if m and (has_arabic(bare) or re.search(r"كم\s*تاخذ", folded)):
        a, b = m.group(1).strip(), m.group(2).strip()
        if a and b and a != b:
            en = f"how long from {a} to {b}"
            return TranslateResult(original, en, True, "maps", {"origin": a, "destination": b})

    # --- call: اتصل علي / كلم محمد ---
    m = re.search(rf"^{_CALL_VERBS}\s+(?:على\s+|ب\s+)?(.+?)\s*$", folded, flags=re.I)
    if m:
        who = m.group(1).strip(" .،!")
        who = re.sub(r"^(ال)", "", who)
        # Ignore "call me" style, but allow the name Ali / علي
        if who and who not in {"فيني", "لي", "مني", "me", "myself"}:
            en = f"call {who}"
            return TranslateResult(original, en, en.lower() != bare.lower(), "call", {"contact": who})

    # --- remember / second brain ---
    m = re.search(r"^(?:احفظ|تذكر|خل\s*بالك)\s+(.+)$", folded, flags=re.I)
    if m:
        return TranslateResult(original, f"remember {m.group(1).strip()}", True, "memory")

    m = re.search(
        r"^(?:اضف|أضف|سجل|حط)\s+(?:فكره|فكرة|نوت|ملاحظة|idea)\s*(?:في\s*(?:ال)?سكند\s*برين|في\s*ملاحظاتي)?\s*[:\-]?\s*(.+)$",
        folded,
        flags=re.I,
    )
    if m:
        return TranslateResult(original, f"add idea {m.group(1).strip()}", True, "brain")

    # --- open APP and search QUERY ---
    m = re.search(
        rf"^{_OPEN_VERBS}\s+(.+?)\s+(?:و)?\s*{_SEARCH_VERBS}\s+(?:على\s+|عن\s+)?(.+?)\s*$",
        folded,
        flags=re.I,
    )
    if m:
        app_chunk, query = m.group(1).strip(), m.group(2).strip()
        query = re.sub(r"^(?:على|عن|علي)\s+", "", query).strip()
        app_id = _match_app(app_chunk)
        if app_id == "movies" and query:
            en = f"open movies and search {query}"
            return TranslateResult(original, en, True, "movies_search", {"query": query})
        if app_id == "youtube" and query:
            en = f"open youtube and search {query}"
            return TranslateResult(original, en, True, "youtube_search", {"query": query})
        if app_id and query:
            en = f"open { _english_app_phrase(app_id) } and search {query}"
            return TranslateResult(original, en, True, "open_search", {"app": app_id, "query": query})

    # --- search QUERY on APP ---
    m = re.search(
        rf"^{_SEARCH_VERBS}\s+(?:على\s+|عن\s+)?(.+?)\s+(?:على|في)\s+(.+?)\s*$",
        folded,
        flags=re.I,
    )
    if m:
        query, app_chunk = m.group(1).strip(), m.group(2).strip()
        app_id = _match_app(app_chunk)
        if app_id == "movies" and query:
            return TranslateResult(
                original, f"open movies and search {query}", True, "movies_search", {"query": query}
            )
        if app_id == "youtube" and query:
            return TranslateResult(
                original, f"search {query} on youtube", True, "youtube_search", {"query": query}
            )

    # --- open APP only ---
    m = re.search(rf"^{_OPEN_VERBS}\s+(.+?)\s*$", folded, flags=re.I)
    if m:
        app_chunk = m.group(1).strip(" .،!")
        app_id = _match_app(app_chunk)
        if app_id:
            en = f"open {_english_app_phrase(app_id)}"
            return TranslateResult(original, en, True, "open", {"app": app_id})

    # Bare app name in Arabic (e.g. just «الافلام»)
    if has_arabic(bare) or re.search(r"(?:ال)?افلام|فيدبوكس", low):
        app_id = _match_app(folded)
        if app_id and len(folded) < 40 and not re.search(r"\s{2,}", folded):
            # Only if the whole phrase is basically the app
            if _match_app(folded) and not re.search(r"من |كم |اتصل|كلم", folded):
                # ensure no extra verbs
                if not re.search(_OPEN_VERBS, folded, flags=re.I):
                    # "الافلام" alone → open movies
                    if re.fullmatch(
                        r"(?:ال)?(?:افلام|أفلام|يوتيوب|واتساب|فيدبوكس|خرائط|جيميل|كروم).*",
                        folded,
                        flags=re.I,
                    ):
                        return TranslateResult(
                            original,
                            f"open {_english_app_phrase(app_id)}",
                            True,
                            "open",
                            {"app": app_id},
                        )

    # No translation needed
    return TranslateResult(original, original, False)


def hermes_arabic_hint(text: str) -> str:
    """If we translated Arabic → English, tell Hermes both forms."""
    tr = translate_command(text)
    if not tr.changed:
        return text
    return (
        f"[ARABIC COMMAND TRANSLATED — user said: «{tr.original}» → treat as: «{tr.translated}». "
        f"Execute that English command with tools. Reply in English unless asked for Arabic.]\n"
        f"{tr.translated}"
    )
