"""Normalize broken / non-native English commands so hard-routes still match.

Examples:
  "jarvis you open for me the youtube"   -> "open youtube"
  "youtube open please"                  -> "open youtube"
  "remind me drink water after 5 minute" -> "remind me to drink water in 5 minutes"
  "make call to Ali"                     -> "call Ali"
  "what time now"                        -> "what time is it"

Also answers clock / date questions locally (instant, no LLM).
"""
from __future__ import annotations

import re
from datetime import datetime

_ARABIC = re.compile(r"[\u0600-\u06FF]")

_VERBS = (
    r"open|close|call|phone|dial|play|search|find|look\s+up|google|remind|send|text|message|"
    r"write|type|tell|show|check|set|add|make|start|stop|turn|put|read|email|mail|"
    r"translate|navigate|take|give|what|when|where|who|how|go"
)
_VERB_START = re.compile(rf"(?i)^(?:{_VERBS})\b")

_WAKE = re.compile(
    r"(?i)^(?:(?:hey|hi|ok(?:ay)?|yo|ya|oh)\s+)?(?:jarvis|jarvas|jervis|javis|jarvi|jarves|travis)\b[\s,.!?:;-]*"
)
_POLITE = re.compile(
    r"(?i)^(?:please|pls|plz|kindly|can\s+you|could\s+you|would\s+you|will\s+you|can\s+u|"
    r"you\s+can|you\s+could|you\s+will|i\s+want(?:\s+you)?(?:\s+to)?|i\s+need(?:\s+you)?(?:\s+to)?|"
    r"i\s+would\s+like(?:\s+you)?(?:\s+to)?|i\s+wanna|help\s+me(?:\s+to)?|try(?:\s+to)?|"
    r"now|so|okay|ok|and|also|just|quickly|fast|go\s+and|come\s+on)[\s,]+"
)
_SUBJECT_YOU = re.compile(rf"(?i)^(?:you|u)\s+(?=(?:{_VERBS})\b)")

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60,
}
_UNIT = r"(?:seconds?|secs?|sec|minutes?|minuts?|minits?|mins?|min|hours?|hrs?|hr)"


def _unit_word(unit: str, n: int) -> str:
    u = unit.lower()
    if u.startswith("s"):
        base = "second"
    elif u.startswith("h"):
        base = "hour"
    else:
        base = "minute"
    return base if n == 1 else base + "s"


def _fix_durations(s: str) -> str:
    def words_to_num(m: re.Match) -> str:
        key = " ".join(m.group(1).lower().split())
        return f"{_NUM_WORDS[key]} {m.group(2)}"

    s = re.sub(
        rf"(?i)\b(forty\s+five|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        rf"fifteen|twenty|thirty|forty|fifty|sixty)\s+({_UNIT})\b",
        words_to_num,
        s,
    )
    s = re.sub(
        rf"(?i)\b(\d+)\s*({_UNIT})\b",
        lambda m: f"{m.group(1)} {_unit_word(m.group(2), int(m.group(1)))}",
        s,
    )
    # "after 5 minutes" / "within 5 minutes" / "5 minutes later" -> "in 5 minutes"
    s = re.sub(r"(?i)\b(?:after|within|until|till)\s+(\d+\s+(?:seconds?|minutes?|hours?))\b", r"in \1", s)
    s = re.sub(r"(?i)\b(?:after|within)\s+(an?\s+hour|half\s+(?:an?\s+)?hour|a\s+minute)\b", r"in \1", s)
    s = re.sub(r"(?i)(?<!\bin )\b(\d+\s+(?:seconds?|minutes?|hours?))\s+(?:later|from\s+now)\b", r"in \1", s)
    return s


_CLOCK_Q = re.compile(
    r"(?i)^(?:what(?:'s|\s+is)?\s+(?:the\s+)?(?:time|clock|hour)(?:\s+(?:is\s+it|it\s+is|now|right\s+now|in\s+kuwait|here))*"
    r"|what\s+time\s+(?:now\s+)?(?:is\s+it|it\s+is|now)(?:\s+(?:now|right\s+now))?"
    r"|how\s+much\s+(?:is\s+)?(?:the\s+)?(?:time|clock|hour)(?:\s+(?:is\s+it|now))?"
    r"|time\s+(?:now|please|right\s+now)|the\s+time(?:\s+now)?|current\s+time"
    r"|tell\s+me\s+(?:the\s+)?(?:time|clock)(?:\s+now)?|say\s+(?:the\s+)?time"
    r"|what\s+o'?clock\s+is\s+it|what\s+time|time)$"
)
_DATE_Q = re.compile(
    r"(?i)^(?:what(?:'s|\s+is)?\s+(?:the\s+)?(?:date|day)(?:\s+(?:is\s+it|it\s+is|today|now|of\s+today))*"
    r"|what\s+(?:is\s+)?today(?:'s)?(?:\s+(?:date|day))?(?:\s+is\s+it)?"
    r"|what\s+day\s+(?:is\s+)?(?:it|today)(?:\s+today)?|today\s+(?:what\s+)?(?:date|day)(?:\s+is\s+it)?"
    r"|(?:tell\s+me\s+)?(?:the\s+|today's\s+)?date(?:\s+(?:today|now))?"
    r"|which\s+day\s+(?:is\s+)?(?:it|today)(?:\s+today)?)$"
)


def normalize_command(text: str | None) -> str:
    """Rewrite common broken-English command shapes. Arabic is returned unchanged."""
    raw = (text or "").strip()
    if not raw or _ARABIC.search(raw) or len(raw) > 240:
        return raw
    s = re.sub(r"\s+", " ", raw)
    s = _WAKE.sub("", s).strip()

    for _ in range(4):
        m = _POLITE.match(s)
        if not m:
            break
        rest = s[m.end():].strip()
        if not rest or not (_VERB_START.match(rest) or _SUBJECT_YOU.match(rest) or _POLITE.match(rest)):
            break
        s = rest
    s = _SUBJECT_YOU.sub("", s).strip()

    trail = ""
    tm = re.search(r"[.!?]+$", s)
    if tm:
        trail = tm.group(0)[:1]
        s = s[: tm.start()].rstrip()
    s = re.sub(r"(?i)[\s,]+(?:please|pls|plz|now please|for me please|thank you|thanks)$", "", s)

    # "open for me X" / "open me X" / "play to me X"
    s = re.sub(
        r"(?i)^(open|close|play|search|find|look\s+up|write|type|check|show)\s+(?:for\s+me|to\s+me|me)\s+(?!up\b)",
        r"\1 ",
        s,
    )
    s = re.sub(r"(?i)^(call|text|message|email)\s+for\s+me\s+", r"\1 ", s)
    # "open the youtube" -> "open youtube" (apps/sites don't take articles)
    s = re.sub(r"(?i)^(open|close)\s+(?:the|a)\s+(?=\w)", r"\1 ", s)

    # Object-first: "youtube open" / "the youtube open it" / "whatsapp you open"
    m = re.match(r"(?i)^(?:the\s+)?([a-z0-9][\w .'-]{1,30}?)\s+(?:you\s+)?(open|close|play)(?:\s+(?:it|for\s+me|now))?$", s)
    if m and not _VERB_START.match(m.group(1)):
        s = f"{m.group(2).lower()} {m.group(1)}"

    # Calls: "make call to Ali", "make a call for Ali", "give call to Ali", "call to Ali", "do call with Ali"
    s = re.sub(
        r"(?i)^(?:make|do|give|start|put)\s+(?:a\s+|one\s+)?(?:phone\s+)?call\s+(?:to|for|with|on)?\s*",
        "call ",
        s,
    )
    s = re.sub(r"(?i)^call\s+(?:to|for|with|on)\s+", "call ", s)

    # Search: "search about X" / "search on google about X" / "google about X"
    s = re.sub(r"(?i)^(?:search|google|look)\s+(?:on\s+google\s+|in\s+google\s+|google\s+)?(?:about|of|on)\s+", "search for ", s)

    # Messages: "send message for Ali", "send to Ali message hello"
    s = re.sub(r"(?i)^(send\s+(?:a\s+)?(?:whatsapp\s+)?message|message|text)\s+for\s+", r"\1 to ", s)

    # Reminders
    s = re.sub(
        r"(?i)^(?:make|set|put|add|create|do)\s+(?:me\s+|for\s+me\s+)?(?:a\s+)?reminder\s+",
        "remind me ",
        s,
    )
    s = re.sub(r"(?i)^remind\s+(?:for\s+me|to\s+me)\s+", "remind me ", s)
    s = re.sub(r"(?i)^remind\s+me\s+for\s+(?=(?:the|my|a|an)\b)", "remind me about ", s)
    s = re.sub(r"(?i)^remind\s+me\s+for\s+", "remind me to ", s)
    s = re.sub(
        r"(?i)^remind\s+me\s+(?!to\b|that\b|about\b|at\b|in\b|on\b|after\b|tomorrow\b|tonight\b|"
        r"later\b|every\b|before\b|when\b|if\b)",
        "remind me to ",
        s,
    )

    if re.search(r"(?i)\b(?:remind|reminder|alarm|timer|schedule|calendar|event|appointment|meeting)\b", s):
        s = _fix_durations(s)

    # Clock / date questions -> canonical form
    probe = re.sub(r"(?i)\s+(?:please|now)$", "", s).strip()
    probe = re.sub(r"(?i)^(?:tell|say|show|give)\s+(?:me\s+|to\s+me\s+)?(?=what|which|how|the\s+(?:time|date)|today)", "", probe)
    if _CLOCK_Q.match(probe):
        return "what time is it"
    if _DATE_Q.match(probe):
        return "what is the date today"

    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return raw
    return s + trail


def try_handle_clock(text: str | None, *, now: datetime | None = None) -> dict | None:
    """Instant local answer for time / date questions."""
    t = normalize_command(text).lower().strip(" .!?")
    now = now or datetime.now()
    if t == "what time is it":
        hour = now.strftime("%I").lstrip("0") or "12"
        reply = f"It's {hour}:{now.strftime('%M')} {now.strftime('%p')}."
    elif t == "what is the date today":
        reply = f"Today is {now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}."
    else:
        return None
    return {
        "text": reply,
        "speak": reply,
        "tools": [{"name": "local_clock", "preview": now.strftime("%Y-%m-%d %H:%M")}],
        "run_id": "local_clock",
    }
