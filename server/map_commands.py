"""Hard-route map ETA commands (Kuwaiti + English)."""
from __future__ import annotations

import re
from typing import Any

from maps_eta import eta_between

# English: "how long from Hiteen to Mishrif", "ETA from A to B", "minutes from X to Y"
_EN_FROM_TO = re.compile(
    r"(?is)(?:how\s+long|how\s+many\s+minutes?|how\s+far|eta|travel\s+time|drive\s+time|"
    r"time|minutes?|distance)\s+"
    r"(?:(?:is\s+it|does\s+it\s+take|will\s+it\s+take)\s+)?"
    r"(?:from\s+)(.+?)\s+to\s+(.+?)\s*[.?!]*\s*$"
)
_EN_FROM_TO_SIMPLE = re.compile(
    r"(?is)^\s*(?:from\s+)(.+?)\s+to\s+(.+?)\s*$"
)
# Only accept bare "from A to B" when the utterance also smells like travel time
_TRAVEL_INTENT = re.compile(
    r"(?is)\b(how\s+long|how\s+far|minutes?|eta|drive|driving|route|directions|navigate|"
    r"travel|distance|take|takes|taking)\b|من\s+.+\s+(?:ل|إلى|الى)|كم\s*"
)
_EN_BETWEEN = re.compile(
    r"(?is)(?:how\s+long|eta|minutes?|time|distance)\s+(?:between\s+)(.+?)\s+and\s+(.+?)\s*[.?!]*\s*$"
)
_EN_DIRECTIONS = re.compile(
    r"(?is)(?:directions|route|navigate)\s+(?:from\s+)?(.+?)\s+to\s+(.+?)\s*[.?!]*\s*$"
)

# Arabic / Kuwaiti: من حطين لمشرف ، كم تاخذ من X لـ Y ، مسافة من ... إلى
_AR_FROM_TO = re.compile(
    r"(?is)(?:كم\s*(?:تاخذ|تأخذ|ياخذ|يأخذ|دقيقة|دقائق|وقت|المسافة|تبعد)|مسافة|وقت|دقايق)?\s*"
    r"من\s+(.+?)\s+(?:إلى|الى|إلي|لـ|ل)\s*(.+?)\s*[.؟!]*\s*$"
)
_AR_BETWEEN = re.compile(
    r"(?is)(?:كم|مسافة|وقت).{0,12}بين\s+(.+?)\s+و\s+(.+?)\s*[.؟!]*\s*$"
)

_WALK_RE = re.compile(r"(?is)\b(walk|walking|على\s*رجلي|مشي)\b")


def extract_eta_pair(text: str) -> tuple[str, str] | None:
    t = (text or "").strip()
    if not t:
        return None
    # Strip voice prefix noise
    t = re.sub(r"^\[.*?\]\s*", "", t, flags=re.S).strip()

    patterns = (_EN_FROM_TO, _EN_BETWEEN, _EN_DIRECTIONS, _AR_FROM_TO, _AR_BETWEEN)
    # Bare "from A to B" only with travel intent
    if _TRAVEL_INTENT.search(t):
        patterns = patterns + (_EN_FROM_TO_SIMPLE,)

    for pat in patterns:
        m = pat.search(t)
        if not m:
            continue
        a = m.group(1).strip(" .,!?;:\"'،")
        b = m.group(2).strip(" .,!?;:\"'،")
        a = re.sub(r"\s+", " ", a)
        b = re.sub(r"\s+", " ", b)
        a = re.sub(r"\b(please|thanks|thank you|for me|by car|driving|walking)\b.*$", "", a, flags=re.I).strip()
        b = re.sub(r"\b(please|thanks|thank you|for me|by car|driving|walking)\b.*$", "", b, flags=re.I).strip()
        if len(a) >= 2 and len(b) >= 2 and a.lower() != b.lower():
            return a[:80], b[:80]
    return None


def hermes_maps_hint(text: str) -> str:
    if extract_eta_pair(text):
        return (
            "[MAPS ETA — use maps_eta tool with origin and destination. "
            "Kuwait area names like Hiteen/Hitteen/حطين and Mishrif/Mishref/مشرف are known. "
            "Reply with minutes in English unless asked for Arabic.]\n"
            f"{text}"
        )
    return text


def try_handle_maps(text: str) -> dict[str, Any] | None:
    pair = extract_eta_pair(text)
    if not pair:
        return None
    origin, dest = pair
    profile = "walking" if _WALK_RE.search(text or "") else "driving"
    result = eta_between(origin, dest, profile=profile)
    if not result.get("ok"):
        err = result.get("error") or "Could not get ETA"
        url = result.get("maps_url")
        msg = err
        if url:
            msg += f" You can open this route: {url}"
        return {
            "text": msg,
            "tools": [{"name": "maps_eta", "preview": f"{origin} → {dest} (failed)"}],
            "run_id": "maps_eta",
            "maps": result,
        }
    spoken = result["text"]
    return {
        "text": spoken,
        "tools": [{
            "name": "maps_eta",
            "preview": f"{result['origin']['label']} → {result['destination']['label']} · {result['duration_minutes']} min",
        }],
        "run_id": "maps_eta",
        "maps": result,
        "maps_url": result.get("maps_url"),
    }
