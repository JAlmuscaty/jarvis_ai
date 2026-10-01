"""Dual-Brain Architecture for Jarvis.

Layer 1: Autonomous Local Mind (Llama 3.2 on GPU + Study Knowledge Base + Memory
         + live Jarvis calendar/schedule/brain/skills + optional screen look)
Layer 2: The Brain / ChatGPT (Hermes Agent API with tools and cloud reasoning)

Routing:
- PC *actions* (open/close/send/call/research) → Layer 2
- User says use Layer 2 / ChatGPT → Layer 2 (sticky until they switch back)
- Layer 1 tries first with full read-only Jarvis context; escalate when unsure → Layer 2
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from brain_store import load as load_brain
from calendar_store import load as load_calendar
from connections_store import snapshot as connections_snapshot
from memory_store import format_for_prompt as mem_format
from ollama_gate import ollama_exclusive
from study_engine import STUDY_ENGINE

OLLAMA_API = os.environ.get("OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
_LOGS = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
MEMORY_PATH = Path(os.environ.get("JARVIS_MEMORY_PATH") or (_LOGS / "memory.json"))
CALENDAR_PATH = Path(os.environ.get("JARVIS_CALENDAR_PATH") or (_LOGS / "calendar.json"))
BRAIN_PATH = Path(os.environ.get("JARVIS_BRAIN_PATH") or (_LOGS / "brain.json"))
CONNECTIONS_PATH = Path(os.environ.get("JARVIS_CONNECTIONS_PATH") or (_LOGS / "connections.json"))

_PLUGIN_DIRS = [
    Path.home() / "AppData" / "Local" / "hermes" / "plugins",
    Path(__file__).resolve().parents[1] / "hermes-plugin",
]

_LOCK = threading.Lock()

_DAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}

# Instant answers — no Ollama / Hermes (kills 45s waits on trivial asks)
_PERCENT_RE = re.compile(
    r"(?is)^\s*(?:what(?:'s|s| is)|whats|calculate|compute)?\s*"
    r"(?:the\s+)?(\d+(?:\.\d+)?)\s*%\s*(?:of|off)\s*(\d+(?:\.\d+)?)\s*\??\s*$"
)
_ARITH_RE = re.compile(
    r"(?is)^\s*(?:what(?:'s|s| is)|whats|calculate|compute)?\s*"
    r"(\d+(?:\.\d+)?)\s*([+\-*/x×÷])\s*(\d+(?:\.\d+)?)\s*\??\s*$"
)
_PING_RE = re.compile(r"(?is)^\s*(?:hey\s+)?(?:jarvis[,!]?\s+)?(?:ping|hi|hello|hey|say\s+ok|test)\s*[.!?]?\s*$")

# Read-only screen questions — Layer 1 fetches the page; do not force Layer 2.
_SCREEN_INTENT = re.compile(
    r"(?is)\b("
    r"look\s+at\s+(?:the\s+|my\s+)?(?:screen|browser|tab|page)|"
    r"what(?:'s| is)\s+on\s+(?:my\s+)?(?:screen|browser|tab|page)|"
    r"read\s+(?:my\s+|the\s+)?(?:screen|page|tab)|"
    r"see\s+(?:my\s+|the\s+)?(?:screen|page)|"
    r"what\s+(?:am\s+i|do\s+i\s+have)\s+(?:looking\s+at|open)"
    r")\b"
)

# Calendar / schedule / Jarvis-page questions — keep on Layer 1 with injected data.
_JARVIS_DATA_INTENT = re.compile(
    r"(?is)\b("
    r"calendar|schedule|timetable|homework|due|class(?:es)?|"
    r"second\s+brain|brain\s+(?:idea|note)|skills?|memory|"
    r"what(?:'s| is)\s+(?:on\s+)?my\s+(?:calendar|schedule)|"
    r"what\s+do\s+i\s+have"
    r")\b"
)


def _instant_answer(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    if _PING_RE.match(t):
        return "OK — I'm here."
    m = _PERCENT_RE.match(t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        val = a * b / 100.0
        if val == int(val):
            return f"{int(a)}% of {int(b) if b == int(b) else b} is {int(val)}."
        return f"{a}% of {b} is {val:g}."
    m = _ARITH_RE.match(t)
    if m:
        a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
        try:
            if op in ("+",):
                val = a + b
            elif op in ("-",):
                val = a - b
            elif op in ("*", "x", "×"):
                val = a * b
            elif op in ("/", "÷"):
                if b == 0:
                    return "Can't divide by zero."
                val = a / b
            else:
                return None
        except Exception:
            return None
        if isinstance(val, float) and val == int(val):
            val = int(val)
        return f"{val}."
    return None


# Indicators that a request requires PC *actions* (Layer 2). Headless web research stays on Layer 1.
_TOOL_INTENT_PATTERNS = [
    r"\b(open|launch|start|close)\b.*\b(chrome|youtube|whatsapp|vidbox|movies?|chatgpt|notebooklm|notebook|slides|docs?|sheets|drive|calendar|maps|gmail|tab|browser|app)\b",
    r"\b(open|create|make|new|start)\b.{0,40}\bblank\b.{0,24}\b(page|doc|docs?|document|slide|slides?)\b",
    r"\bblank\s+(page|doc|docs?|document)\b",
    r"\b(write|type|put|draft)\b.{0,80}\b(?:google\s+)?docs?\b",
    r"\b(write|type)\b.{0,40}\bin\b.{0,24}\b(?:google\s+)?docs?\b",
    r"\b(search\s+on\s+youtube|type\s+in\s+search)\b",
    # Social / multi-step research that needs deeper tools — still Layer 2
    r"\b(find|look\s*up|research)\b.{0,60}\b(followers|instagram|tiktok)\b",
    r"\b(call|dial|phone|ring)\s+[A-Za-z]+",
    r"\b(email|send\s+an?\s+email|send\s+gmail|gmail\s+to|check\s+my\s+email|draft\s+(an?\s+)?email|write\s+(an?\s+)?email|inbox)\b",
    r"\b(whatsapp\s+message|draft\s+a\s+message|text\s+[A-Za-z]+)\b",
    r"\b(notebooklm|notebook\s*lm)\b",
    r"\b(composio|mcp)\b",
    r"\bconnect\s+(?:my\s+)?(notion|github|slack|linear|gmail|google\s*calendar|outlook|spotify|discord|trello|jira|hubspot)\b",
    r"\b(https?://|www\.)\S+",
    r"\b(look\s+at|check|review|browse)\b.{0,40}\b(website|site|webpage|link|url)\b",
    r"\b(ask|query|check|read|play|generate|summarize)\b.*\b(notebook|notes|audio\s*overview|deep\s*dive|study\s*guide)\b",
    r"\bwhat (do|are) my (notes|documents|sources) say\b",
    r"\baccording to (my )?(notes|notebooklm|documents)\b",
    r"\b(how\s+long|eta|directions|navigate)\b.*\b(from|to)\b",
    r"من\s+.+\s+(?:ل|إلى|الى)",
    r"(?:افتح|شغل|اتصل|كلم)\b",
]

# Headless web lookup for Layer 1 (no Chrome)
_WEB_INTENT = re.compile(
    r"(?is)\b(?:"
    r"find|look\s*up|research|search(?:\s+for)?|google|"
    r"who\s+is|what\s+is|what\s+are|what\s+was|when\s+(?:is|was|did|does)|"
    r"where\s+(?:is|are|was)|how\s+(?:do|does|did|to|many|much|long)|"
    r"tell\s+me\s+about|latest|news|current|define|meaning\s+of|price\s+of|weather"
    r")\b"
)


def _calendar_context(now: datetime.datetime | None = None) -> str:
    """Compact calendar + weekly schedule for Layer 1."""
    now = now or datetime.datetime.now()
    day_code = _DAY_CODES[now.weekday()]
    day_name = _DAY_NAMES[day_code]
    today = now.strftime("%Y-%m-%d")
    horizon = (now + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
    try:
        data = load_calendar(CALENDAR_PATH)
    except Exception:
        return ""
    lines = [f"Today is {day_name} {today}."]
    schedule = [s for s in (data.get("schedule") or []) if str(s.get("day") or "").lower() == day_code]
    schedule.sort(key=lambda s: str(s.get("start") or "99:99"))
    if schedule:
        bits = []
        for s in schedule[:12]:
            title = (s.get("title") or "class").strip()
            start = s.get("start") or "?"
            end = s.get("end") or ""
            bits.append(f"{title} {start}" + (f"-{end}" if end else ""))
        lines.append("TODAY'S TIMETABLE (recurring school classes): " + "; ".join(bits) + ".")
    else:
        lines.append("TODAY'S TIMETABLE: none.")
    # Whole-week summary (short)
    by_day: dict[str, int] = {}
    for s in data.get("schedule") or []:
        d = str(s.get("day") or "").lower()
        if d in _DAY_NAMES:
            by_day[d] = by_day.get(d, 0) + 1
    if by_day:
        week = ", ".join(f"{_DAY_NAMES[d][:3]}:{by_day[d]}" for d in _DAY_CODES if d in by_day)
        lines.append(f"Weekly timetable block counts: {week}.")
    events = [
        e for e in (data.get("events") or [])
        if today <= str(e.get("date") or "") <= horizon
    ]
    events.sort(key=lambda e: (str(e.get("date") or ""), str(e.get("time") or "")))
    if events:
        bits = []
        for e in events[:14]:
            title = (e.get("title") or "item").strip()[:80]
            date = e.get("date") or "?"
            time_s = e.get("time") or ""
            kind = e.get("kind") or ""
            cls = e.get("class_name") or ""
            bit = f"{date}"
            if time_s:
                bit += f" {time_s}"
            bit += f" {title}"
            if cls:
                bit += f" ({cls})"
            if kind:
                bit += f" [{kind}]"
            bits.append(bit)
        lines.append("DATED EVENTS / HOLIDAYS (one-off calendar items): " + " | ".join(bits) + ".")
    else:
        lines.append("DATED EVENTS / HOLIDAYS: none in the next 14 days.")
    return "\n".join(lines)


def _brain_context() -> str:
    try:
        data = load_brain(BRAIN_PATH)
    except Exception:
        return ""
    ideas = list(data.get("ideas") or [])
    genres = {g.get("id"): g for g in (data.get("genres") or []) if isinstance(g, dict)}
    if not ideas and not genres:
        return "Second Brain is empty."
    lines = [f"Second Brain: {len(ideas)} idea(s), {len(genres)} genre(s)."]
    for idea in reversed(ideas[-6:]):
        title = (idea.get("title") or "untitled").strip()[:70]
        purpose = (idea.get("purpose") or "").strip()
        g = genres.get(idea.get("genre_id")) or {}
        gname = (g.get("name") or "").strip()
        extra = purpose or gname
        lines.append(f"- {title}" + (f" ({extra})" if extra else ""))
    return "\n".join(lines)


def _connections_context() -> str:
    try:
        snap = connections_snapshot(CONNECTIONS_PATH)
    except Exception:
        return ""
    apps = snap.get("apps") or []
    connected = [a.get("name") or a.get("id") for a in apps if a.get("connected")]
    try:
        from connectors.composio_bridge import status as composio_status
        composio = composio_status()
        composio_line = (
            " Composio: connected and online through Hermes."
            if composio.get("online") else
            (" Composio: set up but not reachable right now." if composio.get("configured") else "")
        )
    except Exception:
        composio_line = ""
    if connected:
        return "Connected Jarvis apps: " + ", ".join(str(x) for x in connected[:12]) + "." + composio_line
    return "No external apps connected on the Connect page yet." + composio_line


def _fetch_screen_text() -> str:
    """Read the active Chrome tab for Layer 1. No screenshot. Never navigates."""
    last_err = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import page_look  # type: ignore

            raw = page_look.look_at_browser({"site": "active", "screenshot": False, "max_chars": 2800})
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            if not data.get("ok"):
                return f"Screen unavailable: {data.get('error') or 'not readable'}."
            title = (data.get("title") or "").strip()
            url = (data.get("url") or "").strip()
            text = (data.get("visible_text") or "").strip().replace("\n\n", "\n")
            text = re.sub(r"[ \t]+", " ", text)
            if len(text) > 2200:
                text = text[:2200] + "…"
            return f"Title: {title}\nURL: {url}\nVisible text:\n{text or '(empty)'}"
        except Exception as exc:
            last_err = exc
            continue
    return f"Screen unavailable: {last_err or 'plugin missing'}."


def needs_web_lookup(text: str) -> bool:
    """True when Layer 1 should fetch headless web snippets (no Chrome)."""
    t = (text or "").strip()
    if not t:
        return False
    if _SCREEN_INTENT.search(t) or _JARVIS_DATA_INTENT.search(t):
        return False
    if _instant_answer(t):
        return False
    return bool(_WEB_INTENT.search(t))


def _fetch_web_context(text: str, *, count: int = 4) -> str:
    """Fast headless web_find for Layer 1 — never opens Chrome."""
    query = re.sub(r"(?is)^\s*(?:please\s+|can you\s+|jarvis\s*,?\s*)?", "", (text or "").strip())
    query = re.sub(
        r"(?is)^\s*(?:find|look\s*up|research|search(?:\s+for)?|google|tell\s+me(?:\s+about)?)\s+",
        "",
        query,
    ).strip() or (text or "").strip()
    query = query[:160]
    last_err = None
    for root in _PLUGIN_DIRS:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import web_find as wf  # type: ignore

            raw = wf.web_find({"query": query, "count": count, "fast": True, "timeout": 5.0})
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            if not data.get("ok"):
                return f"Web search unavailable: {data.get('error') or 'no results'}."
            lines = [f"Query: {data.get('query') or query}"]
            for i, r in enumerate((data.get("results") or [])[:count], 1):
                title = (r.get("title") or "").strip()
                snip = (r.get("snippet") or "").strip()
                url = (r.get("url") or "").strip()
                bit = f"{i}. {title}"
                if snip:
                    bit += f" — {snip}"
                if url:
                    bit += f" ({url})"
                lines.append(bit)
            return "\n".join(lines)
        except Exception as exc:
            last_err = exc
            continue
    return f"Web search unavailable: {last_err or 'plugin missing'}."


def _layer1_world_context(text: str) -> tuple[str, dict[str, bool]]:
    """Build read-only Jarvis world context for Layer 1 (lean by default for speed)."""
    flags = {
        "calendar": False,
        "brain": False,
        "memory": False,
        "connections": False,
        "screen": bool(_SCREEN_INTENT.search(text or "")),
        "jarvis_focus": bool(_JARVIS_DATA_INTENT.search(text or "")),
        "web": needs_web_lookup(text or ""),
    }
    # Full personal context only when talking about Jarvis data / screen
    load_personal = flags["jarvis_focus"] or flags["screen"]
    if load_personal:
        flags["calendar"] = flags["brain"] = flags["memory"] = flags["connections"] = True

    parts: list[str] = []
    if flags["calendar"]:
        cal = _calendar_context()
        if cal:
            parts.append("[CALENDAR & SCHEDULE]\n" + cal)
    if flags["brain"]:
        brain = _brain_context()
        if brain:
            parts.append("[SECOND BRAIN]\n" + brain)
    if flags["memory"]:
        try:
            mem = mem_format(MEMORY_PATH, max_facts=8)
        except Exception:
            mem = ""
        if mem:
            parts.append("[SKILLS / MEMORY]\n" + mem)
    if flags["connections"]:
        conn = _connections_context()
        if conn:
            parts.append("[CONNECT]\n" + conn)
    if flags["screen"]:
        parts.append("[SCREEN]\n" + _fetch_screen_text())
    if flags["web"]:
        parts.append("[WEB]\n" + _fetch_web_context(text or ""))
    return "\n\n".join(parts), flags


# Explicit: user wants Layer 2 / ChatGPT / Hermes
_FORCE_L2 = re.compile(
    r"(?is)(?:"
    r"\b(?:use|switch\s+to|go\s+to|ask|talk\s+to)\s+(?:the\s+)?"
    r"(?:layer\s*2|layer\s*two|chatgpt|chat\s*gpt|hermes|cloud\s*brain|the\s*brain)\b|"
    r"\b(?:layer\s*2|chatgpt|chat\s*gpt|hermes)\s+(?:please|mode)?\b|"
    r"\b(?:escalate|hand\s+off|pass)\s+(?:this\s+)?(?:to\s+)?(?:layer\s*2|chatgpt|the\s*brain)\b|"
    r"\b(?:deeper|smarter|better)\s+answer\b|"
    r"\bask\s+(?:chatgpt|the\s+brain)\b|"
    r"استخدم\s*(?:ال)?طبقة\s*الثانية|روح\s*(?:ل|على)?(?:ال)?شات|استخدم\s*شات\s*جي\s*بي\s*تي|"
    r"استخدم\s*(?:ال)?برين|اسأل\s*شات\s*جي\s*بي\s*تي"
    r")"
)

# Explicit: back to Layer 1 / auto
_FORCE_L1 = re.compile(
    r"(?is)(?:"
    r"\b(?:use|switch\s+to|go\s+to|stay\s+on)\s+(?:the\s+)?"
    r"(?:layer\s*1|layer\s*one|local\s*mind|local\s*brain|llama)\b|"
    r"\b(?:layer\s*1|local\s*mind)\s+(?:please|mode)?\b|"
    r"\b(?:auto(?:matic)?\s+(?:mode|routing)|normal\s+mode)\b|"
    r"استخدم\s*(?:ال)?طبقة\s*الاولى|استخدم\s*(?:ال)?مايند\s*المحلي|وضع\s*تلقائي"
    r")"
)

# Strip these wrappers so the remaining question goes to the chosen layer
_STRIP_L2_PREFIX = re.compile(
    r"(?is)^\s*(?:"
    r"(?:please\s+)?(?:use|ask|switch\s+to|go\s+to)\s+(?:the\s+)?"
    r"(?:layer\s*2|layer\s*two|chatgpt|chat\s*gpt|hermes|the\s*brain)\s*"
    r"(?:and|to|for|:|,|-)?\s*|"
    r"استخدم\s*(?:ال)?طبقة\s*الثانية\s*(?:و|علشان|:)?\s*"
    r")"
)

_NON_ANSWER = [
    r"\[?\s*ESCALATE_TO_BRAIN\s*\]?",
    r"\bi don'?t know\b",
    r"\bi do not know\b",
    r"\bi'?m not sure\b",
    r"\bi am not sure\b",
    r"\bi'?m unsure\b",
    r"\bi cannot (answer|help|tell|say)\b",
    r"\bi can'?t (answer|help|tell|say)\b",
    r"\bi'?m unable\b",
    r"\bi am unable\b",
    r"\bno idea\b",
    r"\bnot (enough|sufficient) (info|information|context|data)\b",
    r"\bi don'?t have (enough |the )?(info|information|access|data)\b",
    r"\bout(side)? of my (knowledge|expertise|training)\b",
    r"\bbeyond my (knowledge|capabilities)\b",
    r"\bi need (more|additional) (info|information|context|details)\b",
    r"\bas an ai\b",
    r"\bi shouldn'?t guess\b",
    r"\bi would be guessing\b",
    r"\blet me (ask|check) (chatgpt|the brain|layer\s*2)\b",
    # Confused / clarity hedges must escalate — never leave user with this while tools run elsewhere
    r"\bi didn'?t (catch|understand|get|hear)\b",
    r"\bi did not (catch|understand|get|hear)\b",
    r"\bi do not understand\b",
    r"\bi'?m not sure what you mean\b",
    # Generic idle fluff — escalate / act instead of saying this
    r"\bi'?m ready to assist\b",
    r"\bi am ready to assist\b",
    r"\bready to assist( you)?\b",
    r"\bhow can i (help|assist)( you)?\b",
    r"\bwhat can i (do|help)( for you)?\b",
    r"\bat your service\b",
    r"\bstanding by\b",
    r"\bhow may i help\b",
    r"\bcould you (say|repeat|clarify|rephrase)\b",
    r"\bwhat did you (mean|want|say)\b",
    r"\bcan you (repeat|clarify|say that again)\b",
    r"\bthat (came through )?garbled\b",
]


def _prefs_path() -> Path:
    logs = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
    return logs / "dual_brain_prefs.json"


_FORCE_L2_TTL_SEC = float(os.environ.get("JARVIS_FORCE_L2_TTL", "900"))  # 15 min sticky max


def _load_prefs() -> dict[str, Any]:
    try:
        data = json.loads(_prefs_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"force_layer": None, "force_layer_set_at": None}


def _save_prefs(data: dict[str, Any]) -> None:
    p = _prefs_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


class DualBrainRouter:
    """Routes queries between Layer 1 (Local Autonomous Mind) and Layer 2 (The Brain/ChatGPT)."""

    def __init__(self):
        self.stats = {
            "total_queries": 0,
            "layer1_answered": 0,
            "layer2_escalated": 0,
            "last_layer_used": None,
            "avg_layer1_latency_ms": 0.0,
            "queries": [],
        }
        self._prefs = _load_prefs()

    @property
    def force_layer(self) -> int | None:
        fl = self._prefs.get("force_layer")
        if fl in (1, 2, "1", "2"):
            # Auto-expire sticky Layer 2 so the system doesn't stay slow forever
            if int(fl) == 2:
                set_at = self._prefs.get("force_layer_set_at")
                try:
                    set_at_f = float(set_at) if set_at is not None else 0.0
                except (TypeError, ValueError):
                    set_at_f = 0.0
                if set_at_f and (time.time() - set_at_f) > _FORCE_L2_TTL_SEC:
                    self.set_force_layer(None)
                    return None
            return int(fl)
        return None

    def set_force_layer(self, layer: int | None) -> None:
        self._prefs["force_layer"] = layer
        self._prefs["force_layer_set_at"] = time.time() if layer == 2 else None
        _save_prefs(self._prefs)

    def is_tool_intent(self, text: str) -> bool:
        t = text.strip().lower()
        return any(re.search(pat, t) for pat in _TOOL_INTENT_PATTERNS)

    def wants_layer2(self, text: str) -> bool:
        return bool(_FORCE_L2.search(text or ""))

    def wants_layer1(self, text: str) -> bool:
        return bool(_FORCE_L1.search(text or ""))

    def strip_layer_directive(self, text: str) -> str:
        t = (text or "").strip()
        t = _STRIP_L2_PREFIX.sub("", t).strip()
        t = re.sub(
            r"(?is)^\s*(?:please\s+)?(?:use|switch\s+to)\s+(?:the\s+)?(?:layer\s*1|local\s*mind)\s*(?:and|to|:|,)?\s*",
            "",
            t,
        ).strip()
        return t or text.strip()

    def _looks_like_non_answer(self, reply: str) -> bool:
        r = (reply or "").strip()
        if not r:
            return True
        if "[ESCALATE_TO_BRAIN]" in r:
            return True
        low = r.lower()
        if any(re.search(p, low) for p in _NON_ANSWER):
            return True
        # Very short hedge-only replies
        if len(r) < 12 and re.search(r"(?i)^(sorry|no|idk|dunno)\.?$", r):
            return True
        return False

    def _query_layer1(self, text: str, timeout: float = 8.0) -> dict[str, Any]:
        """Ask the local Llama 3.2 model with full read-only Jarvis context."""
        t0 = time.perf_counter()

        instant = _instant_answer(text)
        if instant:
            return {"text": instant, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "cards_used": 0}

        # Keep Layer-1 prompts lean — skip huge card scans for short trivia
        relevant_cards = []
        if len((text or "").split()) >= 4:
            relevant_cards = STUDY_ENGINE.find_relevant_cards(text, limit=2)
        knowledge_context = ""
        if relevant_cards:
            knowledge_context = "\n".join(
                f"- {c.get('question')} -> {c.get('answer')}"
                for c in relevant_cards
            )

        world_context, flags = _layer1_world_context(text)

        system_prompt = (
            "You are Jarvis (local, fast). Never say you are Layer 1, local mind, or 'ready to assist'. "
            "Never announce which brain you are using. Just answer.\n"
            "You may receive [WEB] search snippets (headless — nothing opened on the PC). "
            "Use [WEB] for facts/news/definitions when present. Prefer [CALENDAR], [SECOND BRAIN], "
            "[SKILLS / MEMORY], [CONNECT], and [SCREEN] for personal Jarvis data.\n"
            "Reply in 1-3 short English sentences. Be direct.\n"
            "Escalate ONLY with exactly [ESCALATE_TO_BRAIN] when the user wants PC actions "
            "(open/close apps, type in Docs/Slides, send messages, call, email, pick a YouTube video, "
            "open Classroom / find a PDF) or you truly cannot answer "
            "even with [WEB]. Do NOT escalate just to search the web — [WEB] is already search.\n"
            "When giving advice or a choice (recommend a video topic, pick an option, decide), "
            "just choose — do not ask which one unless the request is nonsense.\n"
            "Do not invent calendar items, dues, or screen text that are not listed.\n"
        )
        if knowledge_context:
            system_prompt += f"\n[KNOWLEDGE]\n{knowledge_context}\n"
        if world_context:
            system_prompt += f"\n{world_context}\n"

        full_prompt = f"{system_prompt}\nUser: {text}\nJarvis:"

        # Longer answers when answering from calendar/screen/web
        rich = bool(world_context) and (
            flags.get("screen") or flags.get("jarvis_focus") or flags.get("web") or bool(knowledge_context)
        )
        num_predict = 220 if flags.get("jarvis_focus") else (180 if flags.get("web") else (160 if rich else 80))
        # Lean context window when not loading personal/world blobs
        num_ctx = 4096 if (flags.get("jarvis_focus") or flags.get("screen")) else (3072 if flags.get("web") else 2048)
        # layer1_timeout is for Ollama only — web/screen fetch already finished above
        ollama_timeout = float(timeout)
        if flags.get("screen"):
            ollama_timeout = max(ollama_timeout, 10.0)
        elif flags.get("web"):
            ollama_timeout = max(ollama_timeout, 8.0)

        url = f"{OLLAMA_API}/api/generate"
        payload = json.dumps({
            "model": os.environ.get("JARVIS_LAYER1_MODEL", "llama3.2:3b"),
            "prompt": full_prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "temperature": 0.2,
                "num_predict": num_predict,
                "num_ctx": num_ctx,
            }
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with ollama_exclusive(for_user=True, wait=max(2.0, ollama_timeout)) as got:
            if not got:
                raise TimeoutError("Ollama busy")
            with urllib.request.urlopen(req, timeout=ollama_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = str(data.get("response") or "").strip()

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "text": reply,
            "latency_ms": latency_ms,
            "cards_used": len(relevant_cards),
            "context_flags": flags,
        }

    def _mark_l2(self, reason: str, **extra: Any) -> dict[str, Any]:
        with _LOCK:
            self.stats["layer2_escalated"] += 1
            self.stats["last_layer_used"] = 2
        return {"can_answer": False, "layer": 2, "reason": reason, **extra}

    def _mark_l1(self, text: str, clean_reply: str, latency_ms: float, cards_used: int) -> dict[str, Any]:
        with _LOCK:
            self.stats["layer1_answered"] += 1
            self.stats["last_layer_used"] = 1
            prev_avg = self.stats["avg_layer1_latency_ms"]
            cnt = self.stats["layer1_answered"]
            self.stats["avg_layer1_latency_ms"] = round(((prev_avg * (cnt - 1)) + latency_ms) / cnt, 1)
            self.stats["queries"].append({
                "time": time.strftime("%H:%M:%S"),
                "text": text[:60],
                "layer": 1,
                "latency_ms": latency_ms,
            })
            if len(self.stats["queries"]) > 30:
                self.stats["queries"].pop(0)
        return {
            "can_answer": True,
            "layer": 1,
            "text": clean_reply,
            "model": "llama3.2:3b (local)",
            "latency_ms": latency_ms,
            "cards_used": cards_used,
            "source": "local_mind",
        }

    def try_layer_switch(self, text: str) -> str | None:
        """Reply text for a pure 'switch layer' command (no question attached), else None."""
        raw = (text or "").strip().rstrip(".!")
        if not raw or len(raw) > 60:
            return None
        pure = {"", "please", "now", "mode", "jarvis", raw.lower()}
        if self.wants_layer1(raw):
            if self.strip_layer_directive(raw).strip(" .!").lower() in pure:
                self.set_force_layer(None)
                return "Back to auto mode — I'll use the local mind first, and ChatGPT when needed."
        if self.wants_layer2(raw) and "?" not in raw:
            if self.strip_layer_directive(raw).strip(" .!").lower() in pure:
                self.set_force_layer(2)
                return "Switched to Layer 2 — ChatGPT brain. Ask your question."
        return None

    def route(
        self,
        text: str,
        *,
        layer1_timeout: float | None = None,
        skip_layer1: bool = False,
    ) -> dict[str, Any]:
        """Decide whether Layer 1 can answer or if it needs to escalate to Layer 2."""
        with _LOCK:
            self.stats["total_queries"] += 1

        raw = (text or "").strip()
        if not raw:
            return self._mark_l2("empty")

        # Track what the user asks most → bias idle study
        try:
            STUDY_ENGINE.note_interest(raw)
        except Exception:
            pass

        # Sticky / explicit layer switches
        if self.wants_layer1(raw):
            self.set_force_layer(None)  # auto (prefer L1 when possible)
            leftover = self.strip_layer_directive(raw)
            if leftover.lower() in {"", "please", "now", "mode"} or leftover == raw and len(raw) < 40:
                # Pure switch command
                return {
                    "can_answer": True,
                    "layer": 1,
                    "text": "Back to auto mode — I'll use the local mind first, and ChatGPT when needed.",
                    "model": "router",
                    "latency_ms": 0,
                    "cards_used": 0,
                    "source": "router",
                    "force_layer": None,
                }
            raw = leftover
            skip_layer1 = False  # user asked for local mind — honor it

        if self.wants_layer2(raw):
            # Sticky Layer 2 until user switches back
            self.set_force_layer(2)
            leftover = self.strip_layer_directive(raw)
            if not leftover or leftover.lower() in {"please", "now", "mode"} or (
                leftover == raw and len(raw) < 48 and not re.search(r"\?", raw)
            ):
                return {
                    "can_answer": True,
                    "layer": 2,
                    "text": "Switched to Layer 2 — ChatGPT brain. Ask your question.",
                    "model": "router",
                    "latency_ms": 0,
                    "cards_used": 0,
                    "source": "router",
                    "force_layer": 2,
                    # Still escalate empty follow-up handling: treat as ack only
                    "ack_only": True,
                }
            # Has a real question after the switch phrase → Layer 2
            return self._mark_l2("user_requested_layer2", cleaned_text=leftover)

        # Instant local answers (math / ping) even in sticky Layer 2 — avoid 45s Hermes waits
        instant = _instant_answer(raw)
        if instant:
            return self._mark_l1(raw, instant, 0.0, 0)

        # Sticky force Layer 2
        if self.force_layer == 2:
            return self._mark_l2("force_layer2", cleaned_text=raw)

        # Tool / PC *actions* → Layer 2 (read-only calendar/screen stay on Layer 1)
        if self.is_tool_intent(raw) and not _SCREEN_INTENT.search(raw):
            return self._mark_l2("tool_intent", message="Tool command requiring Layer 2 / PC execution.")

        # Voice fast-path: skip local Llama (can add multi-second wait) → Hermes now
        if skip_layer1:
            return self._mark_l2("voice_fast_path", cleaned_text=raw)

        # Try Layer 1
        try:
            t_out = 8.0 if layer1_timeout is None else float(layer1_timeout)
            res = self._query_layer1(raw, timeout=t_out)
            reply = res["text"]
            latency_ms = res["latency_ms"]

            if self._looks_like_non_answer(reply):
                return self._mark_l2("layer1_uncertain", latency_ms=latency_ms)

            clean_reply = re.sub(r"^(Jarvis:|AI:)\s*", "", reply, flags=re.IGNORECASE).strip()
            # Strip any accidental layer labels the model may emit
            clean_reply = re.sub(
                r"(?is)^\s*\[?\s*layer\s*1\s*:\s*local\s*mind\s*\]?\s*",
                "",
                clean_reply,
            ).strip()
            # Action-ish user turns must never get idle fluff — escalate to Layer 2
            if re.search(r"(?is)\b(open|write|type|create|make|send|call|close|launch|draft)\b", raw):
                if self._looks_like_non_answer(clean_reply) or re.search(
                    r"(?is)\b(ready to assist|how can i help|at your service)\b",
                    clean_reply,
                ):
                    return self._mark_l2("layer1_action_fluff", latency_ms=latency_ms, cleaned_text=raw)
            return self._mark_l1(raw, clean_reply, latency_ms, res["cards_used"])

        except Exception as exc:
            return self._mark_l2(f"layer1_error: {exc}")

    def get_stats(self) -> dict[str, Any]:
        with _LOCK:
            t = self.stats["total_queries"]
            l1 = self.stats["layer1_answered"]
            ratio = round((l1 / max(1, t)) * 100, 1)
            return {
                "ok": True,
                **self.stats,
                "layer1_resolution_rate": ratio,
                "force_layer": self.force_layer,
                "mode": "layer2" if self.force_layer == 2 else "auto",
            }


# Global singleton
DUAL_BRAIN = DualBrainRouter()


def needs_hermes_tools(text: str) -> bool:
    """True when Layer 2 should be allowed to use tools (PC/email/maps/coding/complex)."""
    t = (text or "").strip()
    if not t:
        return False
    if DUAL_BRAIN.is_tool_intent(t):
        return True
    # Coding / project builds need Hermes terminal+file tools
    if re.search(
        r"(?is)\b(code|coding|program|script|repo|github|refactor|debug|implement|"
        r"scaffold|build\s+(?:an?\s+)?(?:app|project|website|api|bot)|"
        r"write\s+(?:python|javascript|typescript|html|css|code)|"
        r"create\s+(?:an?\s+)?(?:app|project|website|api|bot))\b",
        t,
    ):
        return True
    # Long / multi-step instructions
    if len(t.split()) >= 45:
        return True
    if re.search(r"(?is)\b(step by step|then |after that|and also|make sure to)\b", t):
        return True
    if re.search(r"(?is)\b(essay|presentation|slides?|deck|homework|worksheet)\b", t):
        return True
    if re.search(
        r"(?is)\b(choose|pick|play|select)\b.{0,40}\b(video|youtube|yt)\b|"
        r"\b(youtube|classroom)\b|"
        r"\b(pdf|textbook|classwork)\b|"
        r"\benglish\s*\d",
        t,
    ):
        return True
    return False


def is_complex_question(text: str) -> bool:
    """Very complex turns — keep full Hermes hints/tools."""
    t = (text or "").strip()
    if needs_hermes_tools(t):
        return True
    if len(t.split()) >= 60:
        return True
    if re.search(r"(?is)\b(compare|analyze|deep\s*dive|plan\s+my|strategy|detailed)\b", t):
        return True
    return False
