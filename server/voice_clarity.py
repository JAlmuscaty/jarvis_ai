"""Clean speech transcripts and flag unclear / weird STT results for Jarvis."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Status = Literal["ok", "uncertain", "unclear"]

# Whisper often invents these on silence / noise / music
_HALLUCINATIONS = frozenset({
    "thank you",
    "thanks",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "subscribe",
    "like and subscribe",
    "see you next time",
    "bye",
    "goodbye",
    "you",
    "the",
    "a",
    "uh",
    "um",
    "hmm",
    "mm",
    "mhm",
    "huh",
    ".",
    "..",
    "...",
    "?",
    "!",
    # Multilingual tiny model often invents these on silence / short notes
    "english",
    "english translation",
    "translation",
    "subtitle",
    "subtitles",
    "music",
    "applause",
    "silence",
    "foreign",
    "speaking",
    # Arabic / YouTube-style STT hallucinations
    "شكرا",
    "شكراً",
    "شكرا للمشاهدة",
    "شكراً للمشاهدة",
    "اشتركوا",
    "اشترك في القناة",
    "إلى اللقاء",
    "ترجمة",
    "ترجمة انجليزي",
})

_OK_SHORT = frozenset({
    "ok", "okay", "yes", "no", "yeah", "yep", "nope", "hi", "hey", "hello",
    "go", "stop", "wait", "cancel", "sure", "thanks",
    # Kuwaiti / Gulf short replies
    "اي", "ايه", "أي", "نعم", "لا", "زين", "تمام", "يلا", "يالله", "خلاص", "هلو", "هلا",
})

_PUNCT_ONLY = re.compile(r"^[\s\.\,\!\?\-\—\–\:\;\'\"…·•]+$")
_MULTI_SPACE = re.compile(r"\s+")
_REPEAT_CHAR = re.compile(r"(.)\1{5,}")
_REPEAT_WORD = re.compile(r"\b(\w+)(?:\s+\1){3,}\b", re.I)
_ARABIC_CHAR = re.compile(r"[\u0600-\u06FF]")
# Latin words OR Arabic words
_WORD = re.compile(r"[A-Za-z']+|[\u0600-\u06FF]+")

_VOICE_PREFIX = (
    "[Voice transcript — clean up filler if needed and follow the user's intent. "
    "Input may be English or Kuwaiti Arabic dialect. The user is not a native English speaker: "
    "grammar may be broken (e.g. 'you open for me youtube', 'remind me drink water after 5 minute') — "
    "infer the obvious intent and act on it; don't correct their English. "
    "If this text looks weird, garbled, or incomplete, say so briefly and ask me to repeat "
    "instead of guessing or using tools.]\n"
)

_UNCERTAIN_PREFIX = (
    "[VOICE UNCERTAIN — this transcription may be wrong. "
    "Tell me what you think you heard in one short sentence, "
    "and ask me to confirm before doing anything.]\n"
)

_CLARIFY = (
    "I didn't catch that clearly. Could you say that again?"
)
_WEIRD = (
    "That came through garbled on my end. What did you want me to do?"
)


@dataclass
class ClarityResult:
    status: Status
    cleaned: str
    reason: str | None = None
    speak: str | None = None
    brain_text: str = ""

    @property
    def proceed(self) -> bool:
        return self.status in ("ok", "uncertain") and bool(self.cleaned)


def pcm_mean_abs(audio_bytes: bytes | None) -> float:
    """Mean absolute amplitude of s16le PCM (0..32768)."""
    if not audio_bytes or len(audio_bytes) < 2:
        return 0.0
    n = len(audio_bytes) // 2
    if n <= 0:
        return 0.0
    total = 0
    # Sample every 4th sample for speed on long clips
    step = 4 if n > 4000 else 1
    count = 0
    for i in range(0, n, step):
        lo = audio_bytes[2 * i]
        hi = audio_bytes[2 * i + 1]
        val = lo | (hi << 8)
        if val >= 0x8000:
            val -= 0x10000
        total += abs(val)
        count += 1
    return (total / count) if count else 0.0


def clean_transcript(text: str | None) -> str:
    if not text:
        return ""
    t = text.replace("\u0000", " ").strip()
    t = t.replace("…", "...")
    # Drop leading/trailing filler tokens Whisper sometimes sticks on (EN + AR)
    t = re.sub(r"^(uh+|um+|ah+|er+|hmm+|يعني|اه+|ام+)\b[\s,.-]*", "", t, flags=re.I)
    t = re.sub(r"[\s,.-]*(uh+|um+|ah+|er+|hmm+|يعني|اه+|ام+)$", "", t, flags=re.I)
    t = _MULTI_SPACE.sub(" ", t).strip(" \t\n\r\"'")
    t = re.sub(r"([.!?]){3,}", "...", t)
    t = re.sub(r"[,]{2,}", ",", t)
    return t.strip()


def _has_arabic(text: str) -> bool:
    return bool(_ARABIC_CHAR.search(text))


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = sum(1 for c in text if c.isalpha())
    return letters / max(1, len(text.replace(" ", "")))


def assess_transcript(
    text: str | None,
    *,
    audio_bytes: int | bytes | None = None,
    sample_rate: int = 16000,
    pcm: bytes | None = None,
) -> ClarityResult:
    cleaned = clean_transcript(text)
    duration = None
    pcm_buf = pcm if isinstance(pcm, (bytes, bytearray)) else None
    byte_len = None
    if isinstance(audio_bytes, (bytes, bytearray)):
        pcm_buf = pcm_buf or bytes(audio_bytes)
        byte_len = len(audio_bytes)
    elif isinstance(audio_bytes, int):
        byte_len = audio_bytes
    if byte_len is None and pcm_buf is not None:
        byte_len = len(pcm_buf)
    if byte_len is not None and sample_rate > 0:
        duration = max(0.0, byte_len / (sample_rate * 2))

    # Near-silent clips → Whisper invents "English." / YouTube lines
    if pcm_buf is not None:
        energy = pcm_mean_abs(pcm_buf)
        if energy < 180.0:
            return ClarityResult(
                status="unclear",
                cleaned="",
                reason="near_silent",
                speak=_CLARIFY,
            )

    if not cleaned or _PUNCT_ONLY.match(cleaned):
        return ClarityResult(
            status="unclear",
            cleaned="",
            reason="empty_or_punct",
            speak=_CLARIFY,
        )

    lower = cleaned.lower().strip(" .!?")
    # Normalize Arabic alef variants for short-match checks
    ar_norm = cleaned.strip(" .!?،؛")
    words = _WORD.findall(cleaned)
    word_count = len(words)
    arabic = _has_arabic(cleaned)

    if word_count == 0:
        return ClarityResult(
            status="unclear",
            cleaned=cleaned,
            reason="no_words",
            speak=_CLARIFY,
        )

    if lower in _HALLUCINATIONS or ar_norm in _HALLUCINATIONS:
        return ClarityResult(
            status="unclear",
            cleaned=cleaned,
            reason="likely_hallucination",
            speak=_CLARIFY,
        )

    if any(x in lower for x in (
        "thanks for watching",
        "please subscribe",
        "like and subscribe",
        "subscribe to our channel",
        "english translation",
    )):
        return ClarityResult(
            status="unclear",
            cleaned=cleaned,
            reason="youtube_hallucination",
            speak=_CLARIFY,
        )
    if "للمشاهدة" in cleaned or "اشترك في القناة" in cleaned:
        return ClarityResult(
            status="unclear",
            cleaned=cleaned,
            reason="youtube_hallucination_ar",
            speak=_CLARIFY,
        )

    if (
        duration is not None
        and duration < 0.35
        and word_count <= 2
        and lower not in _OK_SHORT
        and ar_norm not in _OK_SHORT
    ):
        return ClarityResult(
            status="unclear",
            cleaned=cleaned,
            reason="too_short_audio",
            speak=_CLARIFY,
        )

    if _REPEAT_CHAR.search(cleaned) or _REPEAT_WORD.search(cleaned):
        return ClarityResult(
            status="unclear",
            cleaned=cleaned,
            reason="repetition_glitch",
            speak=_WEIRD,
        )

    alpha = _alpha_ratio(cleaned)
    if alpha < 0.35 and word_count < 3:
        return ClarityResult(
            status="unclear",
            cleaned=cleaned,
            reason="low_alpha",
            speak=_WEIRD,
        )

    # Arabic script is expected (Kuwaiti) — do NOT treat as unexpected_script

    # Long single Latin "word" with almost no vowels — classic garbage (skip for Arabic)
    if not arabic and word_count == 1 and len(words[0]) >= 10:
        vowels = sum(1 for c in words[0].lower() if c in "aeiou")
        if vowels <= 1:
            return ClarityResult(
                status="unclear",
                cleaned=cleaned,
                reason="gibberish_token",
                speak=_WEIRD,
            )

    unfinished = bool(re.search(
        r"(?i)\b(and|to|the|a|my|for|with|open|call|search|play|send|tell)\s*$",
        cleaned,
    )) or cleaned.endswith(",")
    # Arabic unfinished particles
    unfinished_ar = bool(re.search(r"(فتح|اتصل|ابحث|شغل|ارسل|قول)\s*$", cleaned))
    if (unfinished or unfinished_ar) and lower not in _OK_SHORT and ar_norm not in _OK_SHORT:
        return ClarityResult(
            status="uncertain",
            cleaned=cleaned,
            reason="incomplete",
            speak=None,
            brain_text=_UNCERTAIN_PREFIX + cleaned,
        )

    return ClarityResult(
        status="ok",
        cleaned=cleaned,
        brain_text=_VOICE_PREFIX + cleaned,
    )


def clarify_message(result: ClarityResult) -> str:
    return result.speak or _CLARIFY
