"""Listen & Do — silent, eager action mode for Jarvis.

User speaks continuously; Jarvis executes commands as soon as a clause is
clear (open / call / type / …) without speaking back. Research waits until
a clause finishes. Dictation streams into Docs / Slides / Gmail when focused.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

try:
    from voice_clarity import assess_transcript, clean_transcript
except ImportError:
    from .voice_clarity import assess_transcript, clean_transcript  # type: ignore

# ── session state ────────────────────────────────────────────────────

_LOCK = threading.Lock()
_SESSIONS: dict[str, "ListenDoSession"] = {}


@dataclass
class ListenDoSession:
    id: str
    created_at: float = field(default_factory=time.time)
    # Fingerprints of actions already fired (avoid re-open)
    done: set[str] = field(default_factory=set)
    # How much of the transcript prefix has been "consumed" by actions
    consumed_len: int = 0
    # After open docs/slides/gmail — next prose is typed
    dictate_target: str | None = None  # docs | slides | gmail | None
    last_typed: str = ""
    last_text: str = ""
    stop_listen: bool = False


def get_session(session_id: str | None = None) -> ListenDoSession:
    with _LOCK:
        sid = (session_id or "").strip() or uuid.uuid4().hex[:12]
        if sid not in _SESSIONS:
            _SESSIONS[sid] = ListenDoSession(id=sid)
        # Drop stale sessions (>2h)
        now = time.time()
        dead = [k for k, s in _SESSIONS.items() if now - s.created_at > 7200]
        for k in dead:
            _SESSIONS.pop(k, None)
        return _SESSIONS[sid]


def reset_session(session_id: str | None = None) -> ListenDoSession:
    with _LOCK:
        sid = (session_id or "").strip() or uuid.uuid4().hex[:12]
        _SESSIONS[sid] = ListenDoSession(id=sid)
        return _SESSIONS[sid]


# ── autocorrect / clarity ────────────────────────────────────────────

_ODD_FIXES = [
    (re.compile(r"(?i)\bgoogle\s+dogs\b"), "google docs"),
    (re.compile(r"(?i)\bgoogle\s+dock\b"), "google docs"),
    (re.compile(r"(?i)\bgoogle\s+docks\b"), "google docs"),
    (re.compile(r"(?i)\bgoogle\s+slides?\s+please\b"), "google slides"),
    (re.compile(r"(?i)\bg\s*mail\b"), "gmail"),
    (re.compile(r"(?i)\byou\s+tube\b"), "youtube"),
    (re.compile(r"(?i)\bwhat'?s?\s+app\b"), "whatsapp"),
    (re.compile(r"(?i)\bopen\s+the\s+docs\b"), "open google docs"),
    (re.compile(r"(?i)\bopen\s+docs\b"), "open google docs"),
    (re.compile(r"(?i)\bopen\s+slides\b"), "open google slides"),
    (re.compile(r"(?i)\bcall\s+my\s+(\w+)\b"), r"call \1"),
]


def autocorrect_heard(text: str) -> str:
    t = clean_transcript(text or "")
    for pat, repl in _ODD_FIXES:
        t = pat.sub(repl, t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ── clause helpers ───────────────────────────────────────────────────

_APP_NAMES = (
    r"google\s+docs?|google\s+doc|docs?|document|"
    r"google\s+slides?|slides?|presentation|"
    r"gmail|google\s+mail|"
    r"youtube|yt|"
    r"whatsapp|chrome|maps|google\s+maps|"
    r"chatgpt|chat\s*gpt|"
    r"classroom|google\s+classroom|"
    r"notebooklm|sheets|google\s+sheets|"
    r"drive|google\s+drive|calendar|google\s+calendar"
)

_EAGER_OPEN = re.compile(
    rf"(?is)\b(?:open|launch|go\s+to|pull\s+up)\s+(?:the\s+|my\s+|a\s+|an\s+|new\s+|blank\s+)*"
    rf"({_APP_NAMES})\b"
)

_EAGER_CALL = re.compile(
    r"(?is)\b(?:call|dial|ring|phone)\s+(?:up\s+)?"
    r"(?:(?:my\s+)?(?:friend|buddy|mate|bro|sis|dad|mom|mum|brother|sister)\s+)?"
    r"(?:my\s+)?"
    r"([A-Za-z][A-Za-z0-9 .'-]{0,40}?)"
    r"(?=\s+(?:and|then|,|\.|$)|$)"
)

_TYPE_INTO = re.compile(
    r"(?is)\b(?:type|write|put|dictate)\s+(.+?)\s+"
    r"(?:in|into|on|to)\s+(?:(?:the|a|an|my|this|opened|open|current|blank)\s+)*"
    r"(?:google\s+)?(?:docs?|document|slides?|presentation|gmail|email|compose|page)\b"
)

_TYPE_AFTER_OPEN = re.compile(
    r"(?is)\b(?:and\s+)?(?:then\s+)?(?:type|write|put|say)\s+(.+)$"
)

_RESEARCH = re.compile(
    r"(?is)\b(?:research|look\s+up|search\s+(?:for|up)|find\s+out|(?:please\s+)?google)\s+"
    r"(.+?)"
    r"(?=\s*[.!?…]|\s+and\s+(?:then\s+)?|\s*,\s*|$)"
)

_CLAUSE_END = re.compile(r"(?is)(?:[.!?…]|,\s+|and\s+then\b|after\s+that\b)\s*$")


def clause_finished(text: str, *, final: bool = False) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if final:
        return True
    return bool(_CLAUSE_END.search(t)) or bool(re.search(r"(?is)\b(?:please|thanks|thank you)\s*$", t))


# ── app id map ───────────────────────────────────────────────────────

def _app_id_from_name(name: str) -> str | None:
    try:
        from open_commands import _normalize_app
    except ImportError:
        from .open_commands import _normalize_app  # type: ignore
    return _normalize_app(name)


def _dictation_target_for_app(app_id: str | None) -> str | None:
    if app_id in ("google_docs",):
        return "docs"
    if app_id in ("google_slides",):
        return "slides"
    if app_id in ("gmail",):
        return "gmail"
    return None


# ── executors ────────────────────────────────────────────────────────

def _exec_open(app_id: str) -> dict[str, Any]:
    try:
        from open_commands import _call_open
    except ImportError:
        from .open_commands import _call_open  # type: ignore
    result = _call_open(app_id)
    return {
        "ok": bool(result.get("ok")),
        "action": "open",
        "app": app_id,
        "message": f"Opened {app_id.replace('_', ' ')}." if result.get("ok") else (result.get("error") or "open failed"),
        "raw": result,
    }


def _exec_call(who: str) -> dict[str, Any]:
    try:
        from call_commands import try_handle_call
    except ImportError:
        from .call_commands import try_handle_call  # type: ignore
    routed = try_handle_call(f"call {who}")
    if not routed:
        return {"ok": False, "action": "call", "message": f"Couldn't call {who}."}
    return {
        "ok": True,
        "action": "call",
        "contact": who,
        "message": routed.get("text") or f"Calling {who}.",
        "stop_listen": True,
        "raw": routed,
    }


def _exec_type(target: str, text: str, *, append: bool = True) -> dict[str, Any]:
    """Type into Docs / Slides / Gmail via Chrome CDP."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "action": "type", "message": "Nothing to type."}
    last_err = None
    for root_hint in (
        __import__("pathlib").Path.home() / "AppData" / "Local" / "hermes" / "plugins",
        __import__("pathlib").Path(__file__).resolve().parents[1] / "hermes-plugin",
    ):
        import sys
        if not (root_hint / "pc_apps").is_dir():
            continue
        if str(root_hint) not in sys.path:
            sys.path.insert(0, str(root_hint))
        try:
            from pc_apps import docs_actions  # type: ignore
            if target == "docs":
                # Prefer type into already-open doc; else open+type
                raw = docs_actions.google_docs_type_active({"text": text, "append": append})
            elif target == "slides":
                raw = docs_actions.google_slides_type_active({"text": text, "append": append})
            else:
                raw = docs_actions.gmail_type_active({"text": text, "append": append})
            import json
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            return {
                "ok": bool(data.get("ok")),
                "action": "type",
                "target": target,
                "message": data.get("message") or ("Typed." if data.get("ok") else data.get("error") or "type failed"),
                "raw": data,
            }
        except Exception as exc:
            last_err = exc
            continue
    return {"ok": False, "action": "type", "message": f"Type unavailable: {last_err}"}


def _exec_research(query: str) -> dict[str, Any]:
    q = (query or "").strip().strip(" .,!?;:\"'")
    if len(q) < 2:
        return {"ok": False, "action": "research", "message": "No research query."}
    # Open Chrome search — fast, silent
    try:
        from open_commands import _call_open
    except ImportError:
        from .open_commands import _call_open  # type: ignore
    # Prefer youtube/search via browser if available
    import sys
    from pathlib import Path
    last = None
    for root in (
        Path.home() / "AppData" / "Local" / "hermes" / "plugins",
        Path(__file__).resolve().parents[1] / "hermes-plugin",
    ):
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import browser_actions as ba  # type: ignore
            import json
            import urllib.parse
            url = "https://www.google.com/search?q=" + urllib.parse.quote(q)
            raw = ba.open_url({"url": url}) if hasattr(ba, "open_url") else None
            if raw is None:
                opened = ba._open_url_in_chrome(url, source="listen_do_research")  # type: ignore
                data = opened if isinstance(opened, dict) else {"ok": True}
            else:
                data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            return {
                "ok": bool(data.get("ok", True)),
                "action": "research",
                "query": q,
                "message": f"Researching: {q}",
                "raw": data,
            }
        except Exception as exc:
            last = exc
            continue
    # Fallback: open chrome then user sees nothing — still report
    _call_open("chrome")
    return {"ok": False, "action": "research", "message": f"Research failed: {last}", "query": q}


# ── main process ─────────────────────────────────────────────────────

def process_listen_do(
    text: str,
    *,
    session_id: str | None = None,
    final: bool = False,
) -> dict[str, Any]:
    """Process (partial or final) transcript; fire new eager actions only."""
    sess = get_session(session_id)
    raw = (text or "").strip()
    if not raw:
        return {
            "ok": True,
            "session_id": sess.id,
            "actions": [],
            "text": "",
            "corrected": "",
            "silent": True,
            "stop_listen": sess.stop_listen,
            "dictate_target": sess.dictate_target,
        }

    clarity = assess_transcript(raw)
    if clarity.status == "unclear" and not final:
        return {
            "ok": True,
            "session_id": sess.id,
            "actions": [],
            "text": raw,
            "corrected": raw,
            "skipped": "unclear_partial",
            "silent": True,
            "stop_listen": False,
            "dictate_target": sess.dictate_target,
        }

    corrected = autocorrect_heard(clarity.cleaned or raw)
    sess.last_text = corrected
    actions: list[dict[str, Any]] = []

    # 1) Eager OPEN — fire as soon as app name is heard
    for m in _EAGER_OPEN.finditer(corrected):
        name = m.group(1)
        app_id = _app_id_from_name(name)
        if not app_id:
            continue
        fp = f"open:{app_id}"
        if fp in sess.done:
            continue
        # Need enough trailing context OR final OR boundary after match
        after = corrected[m.end():].lstrip()
        boundary_ok = (
            final
            or not after
            or after.lower().startswith(("and", "then", "to", "type", "write", ",", "."))
            or len(after) >= 1  # "open google docs and …" — docs name complete
        )
        if not boundary_ok:
            continue
        sess.done.add(fp)
        result = _exec_open(app_id)
        actions.append(result)
        dt = _dictation_target_for_app(app_id)
        if dt:
            sess.dictate_target = dt
        sess.consumed_len = max(sess.consumed_len, m.end())

    # 2) Eager CALL — complete contact name; stop listening on success
    for m in _EAGER_CALL.finditer(corrected):
        who = m.group(1).strip(" .,!?;:\"'")
        who = re.sub(r"(?is)\b(please|thanks|thank you|for me)\b.*$", "", who).strip()
        if len(who) < 2:
            continue
        # Don't fire while name still being spoken (no boundary yet) unless final
        after = corrected[m.end():].lstrip()
        if not final and after and not re.match(r"(?i)^(and|then|,|\.|please)\b", after):
            # If match used lookahead to end/$ we're ok; if trailing speech continues name, skip
            if not re.search(r"(?i)\b(and|then|,|\.)\b", corrected[m.start():]):
                if len(after.split()) <= 1 and not final:
                    # might still be extending the name
                    continue
        fp = f"call:{who.lower()}"
        if fp in sess.done:
            continue
        sess.done.add(fp)
        result = _exec_call(who)
        actions.append(result)
        if result.get("stop_listen") or result.get("ok"):
            sess.stop_listen = True
        sess.consumed_len = max(sess.consumed_len, m.end())

    # 3) Explicit type … into docs/slides/gmail
    for m in _TYPE_INTO.finditer(corrected):
        body = m.group(1).strip(" .,!?;:\"'")
        body = re.sub(r"(?is)^(the\s+words?\s+|the\s+text\s+)", "", body).strip()
        low = corrected[m.start():m.end()].lower()
        if "slide" in low:
            target = "slides"
        elif "gmail" in low or "email" in low or "compose" in low:
            target = "gmail"
        else:
            target = "docs"
        fp = f"type:{target}:{body[:80].lower()}"
        if fp in sess.done or len(body) < 1:
            continue
        # Wait for clause end unless final
        if not clause_finished(corrected[: m.end()], final=final) and not final:
            # If "type hello in google docs" fully matched, body is complete
            if not re.search(r"(?i)\b(?:docs?|slides?|gmail|document|page)\b\s*$", corrected[: m.end()]):
                continue
        sess.done.add(fp)
        sess.dictate_target = target
        result = _exec_type(target, body, append=True)
        actions.append(result)
        sess.last_typed = body
        sess.consumed_len = max(sess.consumed_len, m.end())

    # 4) "open docs and type hello world" — type after open once clause-ready
    if sess.dictate_target:
        m = _TYPE_AFTER_OPEN.search(corrected)
        if m:
            body = m.group(1).strip(" .,!?;:\"'")
            body = re.sub(
                r"(?is)\s+(?:in|into|on)\s+(?:(?:the|a|my)\s+)?(?:google\s+)?(?:docs?|slides?|gmail|document|page).*$",
                "",
                body,
            ).strip()
            ready = final or clause_finished(corrected, final=False) or len(body.split()) >= 2
            if body and ready and body.lower() != sess.last_typed.lower():
                to_type = body
                if sess.last_typed and body.lower().startswith(sess.last_typed.lower()):
                    to_type = body[len(sess.last_typed) :].lstrip()
                fp = f"type_after:{sess.dictate_target}:{body[:80].lower()}"
                if to_type and fp not in sess.done:
                    sess.done.add(fp)
                    result = _exec_type(sess.dictate_target, to_type, append=True)
                    actions.append(result)
                    sess.last_typed = body

    # 5) Continuous dictation: final leftover prose after open, no command verbs
    if final and sess.dictate_target and not sess.stop_listen:
        leftover = corrected[sess.consumed_len:].strip()
        leftover = re.sub(
            r"(?is)^\s*(?:and\s+)?(?:then\s+)?(?:please\s+)?(?:type|write|put|say)\s+",
            "",
            leftover,
        ).strip()
        leftover = re.sub(
            r"(?is)\b(?:open|launch|call|dial|research|search|look\s+up)\b.*$",
            "",
            leftover,
        ).strip(" .,!?;:\"'")
        if leftover and leftover.lower() not in {sess.last_typed.lower(), ""}:
            if not re.search(r"(?i)\b(open|call|research|search)\b", leftover):
                fp = f"dictate:{sess.dictate_target}:{leftover[:80].lower()}"
                if fp not in sess.done:
                    sess.done.add(fp)
                    # append only new part
                    to_type = leftover
                    if sess.last_typed and leftover.lower().startswith(sess.last_typed.lower()):
                        to_type = leftover[len(sess.last_typed):].lstrip()
                    if to_type:
                        result = _exec_type(sess.dictate_target, to_type, append=True)
                        actions.append(result)
                        sess.last_typed = leftover

    # 6) Research — only when that clause itself is finished (not whole utterance)
    for m in _RESEARCH.finditer(corrected):
        q = m.group(1).strip(" .,!?;:\"'")
        q = re.sub(r"(?is)\s+(?:and\s+then|please|thanks).*$", "", q).strip()
        # Don't treat "google docs/slides/…" app opens as research
        if re.match(
            r"(?i)^(docs?|slides?|sheets?|drive|maps|classroom|mail|gmail)\b",
            q,
        ):
            continue
        if len(q) < 2:
            continue
        # Need end-of-clause signal after the query (punct / and / final)
        after = corrected[m.end() : m.end() + 12]
        ready = final or bool(re.match(r"\s*[.!?…]|\s+and\b|\s*,", after)) or bool(
            re.search(r"[.!?…]\s*$", corrected[: m.end() + 1])
        )
        if not ready:
            continue
        fp = f"research:{q[:80].lower()}"
        if fp in sess.done:
            continue
        sess.done.add(fp)
        result = _exec_research(q)
        actions.append(result)
        sess.consumed_len = max(sess.consumed_len, m.end())

    return {
        "ok": True,
        "session_id": sess.id,
        "actions": actions,
        "text": raw,
        "corrected": corrected,
        "clarity": clarity.status,
        "silent": True,
        "stop_listen": sess.stop_listen,
        "dictate_target": sess.dictate_target,
        "done": sorted(sess.done),
    }
