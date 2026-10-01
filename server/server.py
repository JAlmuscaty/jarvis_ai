#!/usr/bin/env python3
"""Hermes LAN voice pipeline server (v3 — sessions, stop, approvals, partials).

WebSocket protocol (client → server):
  {"type":"start", "sample_rate":16000, "format":"pcm_s16le", "channels":1,
   "conversation": "jarvis-main"?}          begin a turn (mid-turn = barge-in)
  <binary int16 16 kHz mono PCM chunks>
  {"type":"stop"}                            end of speech, process turn
  {"type":"stop_run"}                        halt the running agent turn
  {"type":"approval_decision", "run_id":..., "approval_id":..., "decision":"allow"|"deny"}

Server → client JSON events:
  status, transcript, partial_transcript, agent_status{thinking|tool_use|speaking},
  run_started{run_id}, approval_request{...}, error, done{timing}
plus binary 16 kHz mono int16 PCM TTS audio.

Brain: Hermes Agent API server via the Sessions API (/api/sessions/{id}/chat/stream),
which provides persistent conversation memory, run ids (stoppable), tool events,
and approval events. Falls back to direct Anthropic ("basic mode") if unreachable.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, Iterator
import sys
import pathlib as _pathlib

# NVIDIA CUDA DLLs for faster-whisper / ctranslate2 (GPU STT) — before Whisper loads
_nv = _pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for _sub in ("cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"):
    _p = _nv / _sub
    if _p.exists():
        try:
            os.add_dll_directory(str(_p))
        except Exception:
            pass
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")

import requests
import uvicorn
import yaml
import numpy as np
from anthropic import Anthropic
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from RealtimeSTT import AudioToTextRecorder

try:
    import psutil
except ImportError:  # machines panel degrades gracefully
    psutil = None

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "server.yaml"
LOG_DIR = Path(os.environ.get("JARVIS_LOGS_DIR", str(ROOT / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "latency.jsonl"
STATE_PATH = LOG_DIR / "hermes_sessions.json"
USAGE_PATH = LOG_DIR / "usage_stats.json"
CALENDAR_PATH = LOG_DIR / "calendar.json"
BRAIN_PATH = LOG_DIR / "brain.json"
MEMORY_PATH = LOG_DIR / "memory.json"
CONNECTIONS_PATH = LOG_DIR / "connections.json"
CHAT_UPLOAD_DIR = Path(os.environ.get("JARVIS_CHAT_UPLOAD_DIR", str(LOG_DIR / "chat_uploads")))
_USAGE_LOCK = threading.Lock()


def _save_chat_image(data_url: str) -> str | None:
    """Persist a data: URL image for Hermes vision_analyze fallback. Returns absolute path."""
    import base64
    import re as _re

    m = _re.match(r"^data:(image/[\w.+-]+);base64,(.+)$", (data_url or "").strip(), _re.DOTALL)
    if not m:
        return None
    mime, b64 = m.group(1), m.group(2)
    ext = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".jpg")
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return None
    if len(raw) < 64 or len(raw) > 12_000_000:
        return None
    CHAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = CHAT_UPLOAD_DIR / f"hw_{int(time.time())}_{os.getpid()}{ext}"
    path.write_bytes(raw)
    return str(path.resolve())

import pc_approvals  # noqa: E402
import chatgpt_login  # noqa: E402
import phone_commands  # noqa: E402
from brain_store import (  # noqa: E402
    add_genre as brain_add_genre,
    add_idea_smart as brain_add_idea_smart,
    add_link as brain_add_link,
    delete_genre as brain_delete_genre,
    delete_idea as brain_delete_idea,
    clear_all_ideas as brain_clear_all_ideas,
    delete_link as brain_delete_link,
    ensure_default_purposes as brain_ensure_default_purposes,
    snapshot as brain_snapshot,
    upsert_idea as brain_upsert_idea,
)
from memory_store import (  # noqa: E402
    delete_fact as mem_delete_fact,
    find_contact as mem_find_contact,
    format_for_prompt as mem_format_for_prompt,
    phone_digits as mem_phone_digits,
    snapshot as mem_snapshot,
    upsert_fact as mem_upsert_fact,
)
from connections_store import (  # noqa: E402
    app_meta as conn_app_meta,
    is_connected as conn_is_connected,
    mark_opened as conn_mark_opened,
    set_connected as conn_set_connected,
    snapshot as conn_snapshot,
)
from auto_memory import auto_save_from_text  # noqa: E402
from movie_commands import hermes_movies_hint, try_handle_movie_rating, try_handle_movies  # noqa: E402
from youtube_commands import try_handle_youtube  # noqa: E402
from call_commands import hermes_call_hint, try_handle_call  # noqa: E402
from email_commands import hermes_email_hint, try_handle_email  # noqa: E402
from whatsapp_commands import try_handle_whatsapp  # noqa: E402
from notes_photo import ingest_notes_photo, wants_notes_to_brain  # noqa: E402
from school_calendar_photo import (  # noqa: E402
    classify_calendar_photo,
    ingest_school_calendar_photo,
    looks_like_calendar_caption,
    wants_school_calendar_photo,
)
from handwriting_photo import ingest_handwriting_photo, wants_handwriting_memorize  # noqa: E402
from handwriting_write import wants_handwriting_write, write_handwritten_document  # noqa: E402
from handwriting_store import status as handwriting_status  # noqa: E402
from google_workspace import try_handle_google_workspace  # noqa: E402
from google_workspace import create_google_doc_essay, create_google_slides  # noqa: E402
from docs_chrome_commands import try_handle_docs_chrome, open_docs_and_type, pending_ack as docs_pending_ack  # noqa: E402
from classroom_commands import try_handle_classroom  # noqa: E402
from site_commands import try_handle_site_browse  # noqa: E402
from task_followup import try_resolve_pending, try_start_followup  # noqa: E402
from connectors import composio_bridge  # noqa: E402
from dual_brain import DUAL_BRAIN, is_complex_question, needs_hermes_tools  # noqa: E402
from study_engine import STUDY_ENGINE  # noqa: E402
from schedule_commands import try_handle_schedule  # noqa: E402
from calendar_commands import try_handle_calendar  # noqa: E402
from brain_commands import try_handle_brain_idea  # noqa: E402
from reminder_watcher import format_reminder_message, pop_due_reminders  # noqa: E402
from listen_do import process_listen_do, reset_session as listen_do_reset  # noqa: E402
from briefing_engine import (  # noqa: E402
    build_briefing_data,
    generate_briefing_audio,
    play_audio_file,
    try_handle_briefing,
)
from model_prefs import (  # noqa: E402
    get_current as model_get_current,
    set_model as model_set_current,
)
from voice_clarity import (  # noqa: E402
    assess_transcript,
    clarify_message,
)
from language_prefs import language_hint_for_prompt, parse_lang_slash  # noqa: E402
from reply_prefs import (  # noqa: E402
    parse_slash as parse_reply_slash,
    style_hint_for_prompt,
    want_simple,
)
from map_commands import hermes_maps_hint, try_handle_maps  # noqa: E402
from maps_eta import eta_between  # noqa: E402
from kuwait_places import list_kuwait_places  # noqa: E402
from arabic_commands import hermes_arabic_hint, translate_command  # noqa: E402
from broken_english import normalize_command, try_handle_clock  # noqa: E402
from open_commands import try_handle_open  # noqa: E402
from connectors import snapshot as connector_snapshot  # noqa: E402
from connectors.service import (  # noqa: E402
    link_connector,
    query_connector,
    read_connector_item,
    sync_connector,
    unlink_connector,
)
from calendar_store import (  # noqa: E402

    add_schedule_item as cal_add_schedule,
    delete_event as cal_delete_event,
    delete_schedule_item as cal_delete_schedule,
    import_events as cal_import_events,
    load as cal_load,
    replace_schedule as cal_replace_schedule,
    upsert_event as cal_upsert_event,
)
from calendar_reminders import (  # noqa: E402
    delete_remote_for_event as cal_delete_remote,
    push_event_to_phone as cal_push_phone,
    push_events_to_phone as cal_push_phone_many,
)


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def record_usage(llm_in: int = 0, llm_out: int = 0, turns: int = 0, tts_chars: int = 0) -> None:
    """Accumulate token/character usage into logs/usage_stats.json (total + per-day)."""
    with _USAGE_LOCK:
        try:
            data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"total": {}, "days": {}}
        day = data["days"].setdefault(_today(), {})
        for bucket in (data["total"], day):
            bucket["llm_in"] = bucket.get("llm_in", 0) + llm_in
            bucket["llm_out"] = bucket.get("llm_out", 0) + llm_out
            bucket["turns"] = bucket.get("turns", 0) + turns
            bucket["tts_chars"] = bucket.get("tts_chars", 0) + tts_chars
        # keep last 60 days
        for k in sorted(data["days"])[:-60]:
            del data["days"][k]
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        USAGE_PATH.write_text(json.dumps(data), encoding="utf-8")


def read_usage() -> dict:
    with _USAGE_LOCK:
        try:
            data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"total": {}, "days": {}}
    return {"total": data.get("total", {}), "today": data.get("days", {}).get(_today(), {})}
ENV_PATHS = [Path.home() / ".hermes" / ".env", ROOT / ".env"]
SENTENCE_RE = re.compile(r"(.+?[.!?])(?=\s|$)", re.DOTALL)
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
CODEBLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
# Secret-shaped strings are never sent to TTS (privacy filter):
SECRET_RES = [
    re.compile(r"\b(?:api[_-]?key|secret|password|passwd|token|bearer|authorization)\b\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk|key|tok|ghp|xox[abp])[-_][A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b[A-Za-z0-9+/_\-]{36,}\b"),          # long opaque blobs (keys, JWT segments)
    re.compile(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", re.DOTALL),
]


def resample_pcm16(data: bytes, from_rate: int, to_rate: int) -> bytes:
    if from_rate == to_rate or not data:
        return data
    samples = np.frombuffer(data, dtype=np.int16)
    n_out = max(1, int(len(samples) * to_rate / from_rate))
    x_in = np.arange(len(samples), dtype=np.float32)
    x_out = np.linspace(0, len(samples) - 1, n_out, dtype=np.float32)
    out = np.interp(x_out, x_in, samples.astype(np.float32))
    return out.astype(np.int16).tobytes()


def load_env() -> None:
    for path in ENV_PATHS:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


@dataclass
class TurnTiming:
    turn_id: int
    audio_start_monotonic: float | None = None
    end_of_speech_monotonic: float | None = None
    stt_start_monotonic: float | None = None
    stt_final_monotonic: float | None = None
    llm_start_monotonic: float | None = None
    llm_first_token_monotonic: float | None = None
    first_sentence_monotonic: float | None = None
    tts_request_start_monotonic: float | None = None
    first_tts_audio_byte_monotonic: float | None = None
    total_done_monotonic: float | None = None
    transcript: str = ""
    response_text: str = ""
    stt_model: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    tts_model: str = ""
    voice_id: str = ""
    run_id: str = ""
    interrupted: bool = False
    tools_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        eos = self.end_of_speech_monotonic
        return {
            "turn_id": self.turn_id,
            "transcript": self.transcript,
            "response_text": self.response_text,
            "stt_model": self.stt_model,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "tts_model": self.tts_model,
            "voice_id": self.voice_id,
            "run_id": self.run_id,
            "interrupted": self.interrupted,
            "tools_used": self.tools_used,
            "stt_finalize_seconds": self._delta(self.stt_start_monotonic, self.stt_final_monotonic),
            "llm_time_to_first_token_seconds": self._delta(self.llm_start_monotonic, self.llm_first_token_monotonic),
            "time_to_first_tts_audio_byte_seconds": self._delta(self.tts_request_start_monotonic, self.first_tts_audio_byte_monotonic),
            "end_of_speech_to_first_audio_seconds": self._delta(eos, self.first_tts_audio_byte_monotonic),
            "total_turn_seconds": self._delta(eos, self.total_done_monotonic),
            "errors": self.errors,
        }

    @staticmethod
    def _delta(start: float | None, end: float | None) -> float | None:
        if start is None or end is None:
            return None
        return round(end - start, 4)


# ===================================================================== Hermes


class HermesAPI:
    """Thin client for the Hermes Agent API server (sessions, runs, approvals)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg.get("hermes") or {}

    @property
    def base(self) -> str:
        return (self.cfg.get("base_url") or "http://127.0.0.1:8642").rstrip("/")

    def headers(self) -> dict:
        key = os.environ.get(self.cfg.get("api_key_env", "API_SERVER_KEY"), "")
        if not key:
            raise RuntimeError("Hermes API key not found in environment")
        h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if self.cfg.get("session_key"):
            h["X-Hermes-Session-Key"] = self.cfg["session_key"]
        return h

    # ---- persistent named sessions ----
    def _load_state(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: dict) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state), encoding="utf-8")

    def get_session_id(self, name: str, force_new: bool = False) -> str:
        state = self._load_state()
        sid = state.get(name)
        if sid and not force_new:
            return sid
        # Hermes titles must be unique; one-shot sessions reuse the same logical name.
        title = f"{name}-{uuid.uuid4().hex[:8]}" if force_new else name
        r = requests.post(f"{self.base}/api/sessions", headers=self.headers(),
                          json={"title": title}, timeout=15)
        if not r.ok:
            # Stale/locked Hermes state sometimes 400s — clear cache and retry once
            detail = (r.text or "")[:240]
            print(f"Hermes create session '{name}' failed {r.status_code}: {detail}", flush=True)
            if not force_new and sid:
                state.pop(name, None)
                self._save_state(state)
            if r.status_code in (400, 404, 409, 422):
                r2 = requests.post(
                    f"{self.base}/api/sessions",
                    headers=self.headers(),
                    json={"title": f"{name}-{uuid.uuid4().hex[:12]}"},
                    timeout=15,
                )
                if r2.ok:
                    r = r2
                else:
                    r.raise_for_status()
            else:
                r.raise_for_status()
        data = r.json()
        sid = (data.get("session") or data).get("id")
        state[name] = sid
        self._save_state(state)
        print(f"Created Hermes session '{name}' -> {sid}", flush=True)
        return sid

    def stop_run(self, run_id: str) -> dict:
        r = requests.post(f"{self.base}/v1/runs/{run_id}/stop", headers=self.headers(), timeout=15)
        return {"status_code": r.status_code, "body": r.text[:300]}

    def post_approval(self, run_id: str, body: dict) -> dict:
        r = requests.post(f"{self.base}/v1/runs/{run_id}/approval", headers=self.headers(),
                          json=body, timeout=15)
        return {"status_code": r.status_code, "body": r.text[:300]}

    def chat_stream_events(
        self,
        session_id: str,
        input_text: str,
        timeout: float,
        *,
        image_data_url: str | None = None,
        force_simple: bool | None = None,
        lean: bool | None = None,
    ) -> Iterator[tuple[str, str]]:
        """Yield ("run"|"text"|"tool"|"approval"|"final", value) from a session turn."""
        # Kuwaiti Arabic understanding + English reply default (sticky switch)
        try:
            lang_hint = language_hint_for_prompt(input_text)
        except Exception as exc:
            print(f"language prefs: {exc}", flush=True)
            lang_hint = ""
        try:
            style_hint = style_hint_for_prompt(force_simple=force_simple)
        except Exception as exc:
            print(f"reply prefs: {exc}", flush=True)
            style_hint = ""

        # Lean = ChatGPT-like speed: answer directly, skip tool/memory bloat unless needed
        if lean is None:
            lean = not (image_data_url or is_complex_question(input_text) or needs_hermes_tools(input_text))

        if lean:
            # Minimal wrappers — no email/maps/call/movies prompt injection
            try:
                input_text = hermes_arabic_hint(input_text)
            except Exception:
                pass
            mem_max = 4
        else:
            input_text = hermes_email_hint(
                hermes_maps_hint(
                    hermes_call_hint(hermes_movies_hint(hermes_arabic_hint(input_text)))
                )
            )
            mem_max = int((self.cfg.get("hermes") or {}).get("memory_max_facts") or 12)

        mem = mem_format_for_prompt(MEMORY_PATH, max_facts=mem_max)
        parts: list[str] = []
        if lean:
            parts.append(
                "[SPEED] Answer like ChatGPT in chat: direct and fast. "
                "Do NOT call tools unless the user clearly needs a PC action, email, maps, Docs/Slides typing, "
                "coding/project work, live research, choosing/playing a YouTube video, or Classroom class/PDF. "
                "When they ask you to choose or pick something actionable, decide and use the tool — do not ask which one. "
                "Prefer a normal reply with no tool calls when no action is needed."
            )
        else:
            parts.append(
                "[AUTONOMY] Intent clear → act. Fuzzy-match names (english 9s = ENGLISH 9S). "
                "Choose/pick/play a video → youtube_pick_video. Class PDF → classroom_find_material. "
                "Ask only if garbled nonsense or nothing matches."
            )
            # Coding / project sessions — unlock Hermes file+terminal tools
            try:
                prefs = model_get_current()
                coding_model = bool(prefs.get("coding_preferred"))
            except Exception:
                coding_model = False
            if coding_model or needs_hermes_tools(input_text):
                if re.search(
                    r"(?is)\b(code|coding|program|script|repo|github|refactor|debug|implement|"
                    r"scaffold|build\s+(?:an?\s+)?(?:app|project|website|api|bot)|"
                    r"write\s+(?:python|javascript|typescript|html|css|code)|"
                    r"create\s+(?:an?\s+)?(?:app|project|website|api|bot)|fix|bug)\b",
                    input_text,
                ) or coding_model:
                    parts.append(
                        "[CODING] The user wants software work. Use Hermes coding tools "
                        "(terminal, read_file, search_files, patch, execute_code) to create/edit files. "
                        "Prefer a dedicated folder they name, or D:\\jarvis_kokoro\\projects\\<name>. "
                        "Speak short status updates; put the real code in files — do not dump huge code blocks in voice."
                    )
        if lang_hint:
            parts.append(lang_hint.rstrip())
        if style_hint:
            parts.append(style_hint.rstrip())
        if mem:
            parts.append(
                "[LONG-TERM MEMORY — never forget these facts; use them when relevant]\n"
                f"{mem}\n"
                "[END MEMORY]"
            )
        if not lean:
            parts.append(
                "[AUTO-MEMORY] When the user shares anything new and durable about their life "
                "(school habits, weekly homework, shows/anime they are watching, preferences, "
                "friends, routines), silently call remember_fact AND second_brain_add_idea. "
                "Do NOT ask whether it helps, whether to save, or for permission — just save, "
                "then briefly confirm. If they say they finished school / graduated / are done "
                "with classes, forget school facts (forget_memory) and remove study notes from "
                "Second Brain; the server also auto-clears school calendar/schedule. "
                "If they send a handwriting photo to memorize, the server saves it forever. "
                "To write in Google Docs or Slides, call google_docs_create / google_slides_create / google_slides_build_deck "
                "(Chrome typing — no Google API / CONNECT). For full essays or N-slide decks, just do it — pick design yourself; "
                "only ask for the topic if missing; only discuss design if the user asked for design suggestions. "
                "For handwriting-style local PDF pages, call handwriting_write. "
                "Never say Docs/Slides tools are unavailable."
            )
        if image_data_url:
            parts.append(
                "[PHOTO ATTACHED] The user sent a photo with the message below. "
                "Follow their description/instructions. Do NOT assume it is homework unless they say so. "
                "If the photo is a yearly school calendar, academic calendar, or holiday/break list: "
                "save items with calendar_add kind=holiday (and end_date when it spans days). "
                "NEVER add homework from a holiday/year-calendar photo. "
                "If they asked to add notes to Second Brain, extract notes and call second_brain_add_idea for each. "
                "If they ask you to solve a problem or worksheet, then solve it. "
                "If SIMPLE MODE is on and they want an answer, give the final answer only. "
                "If vision tools are needed, use vision_analyze on the attached image."
            )
        parts.append(input_text)
        text_payload = "\n\n".join(parts)

        # Multimodal when a photo is present; fall back to text-only if Hermes rejects it.
        if image_data_url:
            body: dict = {
                "input": [
                    {"type": "text", "text": text_payload},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]
            }
        else:
            body = {"input": text_payload}
        try:
            prefs = model_get_current()
            model_id = (prefs.get("model") or "").strip()
            provider = (prefs.get("provider") or "").strip()
            if model_id:
                body["model"] = model_id
            if provider:
                body["provider"] = provider
        except Exception as exc:
            print(f"model prefs load: {exc}", flush=True)

        # Shorter read timeout for lean turns (still enough for ChatGPT-class replies)
        if lean and timeout > 90:
            timeout = float((self.cfg.get("hermes") or {}).get("lean_timeout") or 90)

        def _post(payload: dict):
            return requests.post(
                f"{self.base}/api/sessions/{session_id}/chat/stream",
                headers={**self.headers(), "Accept": "text/event-stream"},
                json=payload, stream=True, timeout=(10, timeout),
            )

        resp = _post(body)
        if resp.status_code >= 400 and image_data_url:
            # Some Hermes builds only accept string input — save file + ask vision_analyze
            detail = (resp.text or "")[:200]
            print(f"Hermes multimodal rejected ({resp.status_code}): {detail} — falling back", flush=True)
            resp.close()
            saved = _save_chat_image(image_data_url)
            fallback_text = text_payload
            if saved:
                fallback_text += (
                    f"\n\n[Image saved at: {saved}]\n"
                    "Call vision_analyze with image_url set to that path, then follow the user's message."
                )
            body = {"input": fallback_text}
            try:
                prefs = model_get_current()
                if (prefs.get("model") or "").strip():
                    body["model"] = prefs["model"].strip()
                if (prefs.get("provider") or "").strip():
                    body["provider"] = prefs["provider"].strip()
            except Exception:
                pass
            resp = _post(body)
        if resp.status_code >= 400:
            resp.close()
            raise RuntimeError(f"Hermes session chat HTTP {resp.status_code}: {resp.text[:300]}")
        resp.encoding = "utf-8"  # SSE has no charset header; requests would assume latin-1 (mojibake)
        try:
            for kind, value in self._parse_sse(resp):
                if kind in ("text", "final") and _HERMES_AUTH_ERR.search(value or ""):
                    print(f"Hermes auth failure: {value[:200]}", flush=True)
                    yield from _hermes_auth_events()
                    return
                yield (kind, value)
        finally:
            resp.close()  # leaked FDs killed the server once (launchd limit is tiny)

    @staticmethod
    def _parse_sse(resp) -> Iterator[tuple[str, str]]:
        event_name = ""
        for raw in resp.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            if raw.startswith("event: "):
                event_name = raw[7:].strip()
                continue
            if not raw.startswith("data: "):
                continue
            data_text = raw[6:].strip()
            try:
                data = json.loads(data_text)
            except json.JSONDecodeError:
                continue
            ev = event_name or data.get("event", "")
            if ev == "run.started":
                yield ("run", data.get("run_id") or "")
            elif ev == "assistant.delta":
                d = data.get("delta") or ""
                if d:
                    yield ("text", d)
            elif ev == "tool.started":
                name = data.get("tool_name") or "tool"
                if name.startswith("_"):
                    continue  # internal pseudo-tools like _thinking
                yield ("tool", json.dumps({"name": name, "preview": (data.get("preview") or "")[:200]}))
            elif "approval" in ev:
                yield ("approval", json.dumps(data)[:2000])
            elif ev == "assistant.completed":
                yield ("final", json.dumps({
                    "content": data.get("content") or "",
                    "interrupted": bool(data.get("interrupted")),
                }))
            elif ev in ("run.failed", "error"):
                raise RuntimeError(f"Hermes stream error: {data_text[:300]}")
            elif ev == "run.completed":
                usage = data.get("usage") or {}
                if usage:
                    record_usage(
                        llm_in=int(usage.get("input_tokens") or 0),
                        llm_out=int(usage.get("output_tokens") or 0),
                        turns=1,
                    )
            elif ev == "done":
                pass  # stream closes after this


# ==================================================================== Pipeline


class VoicePipelineServer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.turn_counter = 0
        self.hermes = HermesAPI(cfg)
        self.stt_lock = asyncio.Lock()
        stt = cfg.get("stt") or {}
        # Multilingual model required for Arabic (never *.en). language=None/auto → detect.
        raw_lang = stt.get("language", "auto")
        if raw_lang in (None, "", "auto"):
            stt_language = None
        else:
            stt_language = str(raw_lang)
        recorder_kwargs = dict(
            model=stt["model"],
            use_microphone=False,
            spinner=False,
            device=stt.get("device", "cpu"),
            compute_type=stt.get("compute_type", "int8"),
            sample_rate=int(stt.get("sample_rate", 16000)),
            beam_size=int(stt.get("beam_size", 1)),
            faster_whisper_vad_filter=False,
            no_log_file=True,
        )
        # RealtimeSTT / faster-whisper: "" = auto language detect (en + ar)
        if stt_language:
            recorder_kwargs["language"] = stt_language
        else:
            recorder_kwargs["language"] = ""
        initial = stt.get("initial_prompt")
        if initial:
            recorder_kwargs["initial_prompt"] = str(initial)
        try:
            self.recorder = AudioToTextRecorder(**recorder_kwargs)
            print(
                f"STT ready: model={stt.get('model')} device={stt.get('device')} "
                f"compute={stt.get('compute_type')}",
                flush=True,
            )
        except TypeError:
            # Older RealtimeSTT without initial_prompt
            recorder_kwargs.pop("initial_prompt", None)
            self.recorder = AudioToTextRecorder(**recorder_kwargs)
        except Exception as exc:
            # CUDA missing / OOM → fall back to CPU tiny so voice still works
            if str(stt.get("device", "")).lower().startswith("cuda"):
                print(f"STT CUDA failed ({exc}); falling back to CPU tiny/int8", flush=True)
                recorder_kwargs["device"] = "cpu"
                recorder_kwargs["compute_type"] = "int8"
                recorder_kwargs["model"] = "tiny"
                try:
                    self.recorder = AudioToTextRecorder(**recorder_kwargs)
                except TypeError:
                    recorder_kwargs.pop("initial_prompt", None)
                    self.recorder = AudioToTextRecorder(**recorder_kwargs)
            else:
                raise

    def next_turn_id(self) -> int:
        self.turn_counter += 1
        return self.turn_counter

    async def transcribe(self, audio: bytes, timing: TurnTiming | None = None) -> str:
        if timing:
            timing.stt_start_monotonic = time.perf_counter()
        # 1) GPU worker (if configured and reachable) — big model, ~0.3s
        remote = self.cfg["stt"].get("remote") or {}
        if remote.get("url"):
            text = await asyncio.to_thread(self._remote_stt, audio, remote)
            if text is not None:
                if timing:
                    timing.stt_model = f"remote:{remote.get('name', 'gpu')}"
                    timing.stt_final_monotonic = time.perf_counter()
                return text
        # 2) local Whisper — chunk long audio so Engage Voice doesn't cut off mid-sentence
        sample_rate = int(self.cfg["stt"].get("sample_rate", 16000))
        samples = (np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0).copy()
        text = await self._local_transcribe_samples(samples, sample_rate)
        if timing:
            timing.stt_final_monotonic = time.perf_counter()
        return (text or "").strip()

    async def _local_transcribe_samples(
        self, samples: "np.ndarray", sample_rate: int, *, blocking: bool = True
    ) -> str:
        """Transcribe PCM float32 mono; for long clips, stitch overlapping windows."""
        if samples.size == 0:
            return ""
        # ~28s windows with 4s overlap — Whisper tiny drops the tail of very long clips
        window = int(sample_rate * 28)
        hop = int(sample_rate * 24)
        if samples.size <= int(sample_rate * 32):
            return await self._local_transcribe_once(samples, sample_rate, blocking=blocking)

        parts: list[str] = []
        start = 0
        while start < samples.size:
            chunk = samples[start : start + window]
            if chunk.size < int(sample_rate * 0.35):
                break
            piece = await self._local_transcribe_once(chunk, sample_rate, blocking=blocking)
            if piece:
                parts.append(piece)
            elif not blocking:
                break  # STT busy — return what we have
            if start + window >= samples.size:
                break
            start += hop
        return self._stitch_transcript_parts(parts)

    async def _local_transcribe_samples_partial(self, audio: bytes) -> str:
        """Live partial STT — never blocks the final Engage transcription."""
        sample_rate = int(self.cfg["stt"].get("sample_rate", 16000))
        if len(audio) < sample_rate:  # <0.5s
            return ""
        samples = (np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0).copy()
        return await self._local_transcribe_samples(samples, sample_rate, blocking=False)

    async def _local_transcribe_once(
        self, samples: "np.ndarray", sample_rate: int, *, blocking: bool = True
    ) -> str:
        if samples.size < int(sample_rate * 0.2):
            return ""
        try:
            if not blocking:
                if self.stt_lock.locked():
                    return ""
                try:
                    await asyncio.wait_for(self.stt_lock.acquire(), timeout=0.05)
                except asyncio.TimeoutError:
                    return ""
            else:
                await self.stt_lock.acquire()
            try:
                self.recorder.feed_audio(samples, original_sample_rate=sample_rate)
                text = await asyncio.to_thread(self.recorder.perform_final_transcription, samples, True)
                self.recorder.clear_audio_queue()
            finally:
                self.stt_lock.release()
        except Exception as exc:
            # near-silent audio can make whisper raise ("No clip timestamps found");
            # treat as empty transcript instead of failing the turn
            print(f"local STT error treated as empty transcript: {exc}", flush=True)
            text = ""
        return (text or "").strip()

    @staticmethod
    def _stitch_transcript_parts(parts: list[str]) -> str:
        """Join overlapping Whisper windows without duplicating the overlap phrase."""
        out = ""
        for part in parts:
            p = (part or "").strip()
            if not p:
                continue
            if not out:
                out = p
                continue
            # Find longest suffix of out that is a prefix of p (word-aware)
            out_words = out.split()
            p_words = p.split()
            max_k = min(12, len(out_words), len(p_words))
            overlap = 0
            for k in range(max_k, 0, -1):
                if out_words[-k:] == p_words[:k]:
                    overlap = k
                    break
            merged = p_words[overlap:]
            if merged:
                out = (out + " " + " ".join(merged)).strip()
        return out

    def _remote_stt(self, audio: bytes, remote: dict) -> str | None:
        """POST raw PCM to the GPU STT worker. None = unavailable (use fallback)."""
        headers = {"Content-Type": "application/octet-stream"}
        token = os.environ.get(remote.get("token_env", "JARVIS_HUD_TOKEN"), "")
        if token:
            headers["X-Jarvis-Token"] = token
        try:
            r = requests.post(remote["url"], data=audio, headers=headers,
                              timeout=float(remote.get("timeout", 6)))
            if r.ok:
                return (r.json().get("text") or "").strip()
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ LLM

    def stream_llm_events_sync(
        self, transcript: str, timing: TurnTiming, conversation: str,
    ) -> Iterator[tuple[str, str]]:
        llm = self.cfg["llm"]
        provider = llm["provider"]
        timing.llm_start_monotonic = time.perf_counter()
        if provider == "hermes":
            try:
                h = self.cfg.get("hermes") or {}
                session_id = self.hermes.get_session_id(conversation)
                gen = self._hermes_turn(session_id, transcript, timing, h, conversation)
                first = next(gen)
            except StopIteration:
                return
            except Exception as exc:
                if _HERMES_AUTH_ERR.search(str(exc)):
                    print(f"Hermes auth failure: {exc}", flush=True)
                    timing.errors.append(f"hermes_auth: {exc}")
                    yield from _hermes_auth_events()
                    return
                fb = (self.cfg.get("hermes") or {}).get("fallback_provider", "anthropic")
                print(f"Hermes unavailable ({type(exc).__name__}: {exc}); fallback={fb}", flush=True)
                timing.errors.append(f"hermes_fallback: {exc}")
                if not fb:
                    raise
                yield ("text", "Agent backend offline. Running in basic mode. ")
                provider = fb
            else:
                yield first
                yield from gen
                return
        timing.llm_provider = provider
        timing.llm_model = llm["model"]
        if provider == "anthropic":
            key = os.environ.get(llm.get("api_key_env", "ANTHROPIC_API_KEY"))
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY not found")
            client = Anthropic(api_key=key)
            with client.messages.stream(
                model=llm["model"],
                max_tokens=int(llm.get("max_tokens", 220)),
                temperature=float(llm.get("temperature", 0.3)),
                system=self.cfg["persona"]["system_prompt"],
                messages=[{"role": "user", "content": transcript}],
            ) as stream:
                for text in stream.text_stream:
                    if text and timing.llm_first_token_monotonic is None:
                        timing.llm_first_token_monotonic = time.perf_counter()
                    yield ("text", text)
        else:
            raise RuntimeError(f"Unsupported LLM provider: {provider}")

    def _hermes_turn(
        self, session_id: str, transcript: str, timing: TurnTiming, h: dict, conversation: str,
    ) -> Iterator[tuple[str, str]]:
        timing.llm_provider = "hermes"
        timing.llm_model = "hermes-agent"
        timeout = float(h.get("timeout", 240))
        try:
            it = self.hermes.chat_stream_events(session_id, transcript, timeout)
            for kind, value in it:
                if kind == "text" and timing.llm_first_token_monotonic is None:
                    timing.llm_first_token_monotonic = time.perf_counter()
                yield (kind, value)
        except RuntimeError as exc:
            # stale session id (e.g. Hermes DB reset) -> recreate once
            if "404" in str(exc):
                session_id = self.hermes.get_session_id(conversation, force_new=True)
                for kind, value in self.hermes.chat_stream_events(session_id, transcript, timeout):
                    if kind == "text" and timing.llm_first_token_monotonic is None:
                        timing.llm_first_token_monotonic = time.perf_counter()
                    yield (kind, value)
            else:
                raise

    # ------------------------------------------------------------------ TTS

    def tts_chunks_sync(self, text: str, timing: TurnTiming) -> Iterator[bytes]:
        voice = self.cfg["voice"]
        base_url = voice["base_url"].rstrip("/")
        from_rate = int(voice.get("source_sample_rate", 24000))
        to_rate = int(voice.get("output_sample_rate", 16000))
        timeout = voice.get("timeout", 30)
        # (connect, read) — don't hang Engage for minutes when Kokoro is down
        if isinstance(timeout, (int, float)):
            req_timeout: float | tuple[float, float] = (3.0, float(timeout))
        else:
            req_timeout = timeout
        timing.tts_model = voice.get("model", "kokoro")
        timing.voice_id = voice.get("voice", "af_heart")
        timing.tts_request_start_monotonic = timing.tts_request_start_monotonic or time.perf_counter()
        record_usage(tts_chars=len(text))
        url = f"{base_url}/audio/speech"
        payload = {
            "model": voice.get("model", "kokoro"),
            "input": text,
            "voice": voice.get("voice", "af_heart"),
            "response_format": "pcm",
            "stream": True,
            "speed": float(voice.get("speed", 1.0)),
        }
        response = requests.post(
            url,
            headers={"Accept": "application/octet-stream", "Content-Type": "application/json"},
            json=payload,
            stream=True,
            timeout=req_timeout,
        )
        if response.status_code >= 400:
            response.close()
            raise RuntimeError(f"Kokoro HTTP {response.status_code}: {response.text[:1000]}")
        try:
            for chunk in response.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                pcm = resample_pcm16(chunk, from_rate, to_rate)
                if timing.first_tts_audio_byte_monotonic is None and pcm:
                    timing.first_tts_audio_byte_monotonic = time.perf_counter()
                yield pcm
        finally:
            response.close()  # barge-in cancels mid-stream; don't leak the connection

    # ------------------------------------------------------------- Turn flow

    async def stream_response_audio(
        self, ws: WebSocket, transcript: str, timing: TurnTiming, conn: "ConnState",
    ) -> None:
        pending = ""
        full_response: list[str] = []
        spoken = False
        await ws.send_json({"type": "agent_status", "state": "thinking"})

        q: asyncio.Queue = asyncio.Queue()
        turn_gen = conn.turn_gen
        ack_after = float((self.cfg.get("hermes") or {}).get("ack_after_seconds") or 0)
        ack_texts = list((self.cfg.get("hermes") or {}).get("ack_texts") or ["On it."])
        if re.search(r"\b(notebooklm|notebook\s*lm|notes?|sources?|audio\s*overview|deep\s*dive)\b", transcript, re.I):
            ack_texts = ["Checking your notebook.", "Consulting NotebookLM.", "Looking through your notes."]
        ack_task: asyncio.Task | None = None

        async def forward() -> None:
            try:
                async for item in self._async_llm_events(transcript, timing, conn.conversation):
                    await q.put(item)
                await q.put(None)
            except Exception as exc:
                await q.put(exc)

        async def maybe_ack() -> None:
            """Speak a short filler while Hermes/tools are still working — feels faster."""
            try:
                await asyncio.sleep(max(0.35, ack_after))
                if spoken or conn.cancel_requested or conn.turn_gen != turn_gen:
                    return
                phrase = random.choice(ack_texts) if ack_texts else "On it."
                clean = self._clean_for_tts(phrase)
                if not clean:
                    return
                await ws.send_json({"type": "agent_status", "state": "speaking"})
                conn.spoken_sentences.append(clean)
                await self._send_tts_sentence(ws, clean, timing, conn, turn_gen)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                print(f"ack speak failed: {exc}", flush=True)

        forward_task = asyncio.create_task(forward())
        if ack_after > 0:
            ack_task = asyncio.create_task(maybe_ack())
        try:
            while True:
                if conn.cancel_requested or conn.turn_gen != turn_gen:
                    raise asyncio.CancelledError()
                item = await q.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                kind, value = item
                if kind == "run":
                    timing.run_id = value
                    conn.current_run_id = value
                    await ws.send_json({"type": "run_started", "run_id": value})
                    continue
                if kind == "tool":
                    info = json.loads(value)
                    timing.tools_used.append(info.get("name", "tool"))
                    await ws.send_json({"type": "agent_status", "state": "tool_use",
                                        "tool": info.get("name"), "preview": info.get("preview", "")})
                    continue
                if kind == "approval":
                    await ws.send_json({"type": "approval_request", "data": json.loads(value),
                                        "run_id": conn.current_run_id})
                    continue
                if kind == "final":
                    info = json.loads(value)
                    timing.interrupted = info.get("interrupted", False)
                    continue
                # kind == "text"
                if conn.cancel_requested or conn.turn_gen != turn_gen:
                    raise asyncio.CancelledError()
                # Real reply started — cancel filler ack if still pending
                if ack_task and not ack_task.done():
                    ack_task.cancel()
                full_response.append(value)
                pending += value
                sentences, pending = self._extract_complete_sentences(pending)
                for sentence in sentences:
                    if conn.cancel_requested or conn.turn_gen != turn_gen:
                        raise asyncio.CancelledError()
                    clean = self._clean_for_tts(sentence)
                    if not clean:
                        continue
                    if timing.first_sentence_monotonic is None:
                        timing.first_sentence_monotonic = time.perf_counter()
                    if not spoken:
                        await ws.send_json({"type": "agent_status", "state": "speaking"})
                        spoken = True
                    # Show text as soon as each sentence is ready (don't wait for full TTS / done).
                    partial = "".join(full_response).strip()
                    if partial:
                        await ws.send_json({"type": "reply", "text": partial, "partial": True})
                    conn.spoken_sentences.append(clean)
                    await self._send_tts_sentence(ws, clean, timing, conn, turn_gen)
            if not (conn.cancel_requested or conn.turn_gen != turn_gen):
                tail = self._clean_for_tts(pending.strip())
                if tail:
                    partial = ("".join(full_response) + pending).strip()
                    if partial:
                        await ws.send_json({"type": "reply", "text": partial, "partial": False})
                    conn.spoken_sentences.append(tail)
                    await self._send_tts_sentence(ws, tail, timing, conn, turn_gen)
        finally:
            if ack_task and not ack_task.done():
                ack_task.cancel()
            if not forward_task.done():
                forward_task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(forward_task), timeout=0.2)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass
        timing.response_text = "".join(full_response).strip()

    async def _async_llm_events(
        self, transcript: str, timing: TurnTiming, conversation: str,
    ) -> AsyncIterator[tuple[str, str]]:
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                for item in self.stream_llm_events_sync(transcript, timing, conversation):
                    loop.call_soon_threadsafe(q.put_nowait, item)
                loop.call_soon_threadsafe(q.put_nowait, None)
            except Exception as exc:
                loop.call_soon_threadsafe(q.put_nowait, exc)

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        while True:
            item = await q.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item
        await worker_task

    async def _send_tts_sentence(
        self,
        ws: WebSocket,
        sentence: str,
        timing: TurnTiming,
        conn: "ConnState | None" = None,
        turn_gen: int | None = None,
    ) -> None:
        if not sentence or getattr(ws, "closed", False):
            return
        if conn is not None and (conn.cancel_requested or (turn_gen is not None and conn.turn_gen != turn_gen)):
            raise asyncio.CancelledError()
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop_worker = threading.Event()

        def worker() -> None:
            try:
                for chunk in self.tts_chunks_sync(sentence, timing):
                    if stop_worker.is_set():
                        break
                    loop.call_soon_threadsafe(q.put_nowait, chunk)
                loop.call_soon_threadsafe(q.put_nowait, None)
            except Exception as exc:
                loop.call_soon_threadsafe(q.put_nowait, exc)

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                if conn is not None and (conn.cancel_requested or (turn_gen is not None and conn.turn_gen != turn_gen)):
                    stop_worker.set()
                    raise asyncio.CancelledError()
                try:
                    item = await asyncio.wait_for(q.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    if conn is not None and (conn.cancel_requested or (turn_gen is not None and conn.turn_gen != turn_gen)):
                        stop_worker.set()
                        raise asyncio.CancelledError()
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    # Never kill the whole Engage turn if TTS/Kokoro is down —
                    # HUD still gets transcript + text reply; audio is best-effort.
                    print(f"TTS failed (continuing without audio): {item}", flush=True)
                    timing.errors.append(f"tts: {type(item).__name__}: {item}")
                    try:
                        await ws.send_json({
                            "type": "status",
                            "message": "Voice synthesis offline — showing text reply.",
                        })
                    except Exception:
                        pass
                    return
                if conn is not None and (conn.cancel_requested or (turn_gen is not None and conn.turn_gen != turn_gen)):
                    stop_worker.set()
                    raise asyncio.CancelledError()
                await ws.send_bytes(item)
        finally:
            stop_worker.set()
            if not worker_task.done():
                worker_task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(worker_task), timeout=0.3)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

    @staticmethod
    def _extract_complete_sentences(text: str) -> tuple[list[str], str]:
        sentences = []
        last_end = 0
        for match in SENTENCE_RE.finditer(text):
            sentences.append(match.group(1).strip())
            last_end = match.end()
        rest = text[last_end:]
        # Speak sooner: flush a long first clause before the period arrives
        if not sentences and len(rest) >= 42:
            for sep in (", ", "; ", " — ", " - "):
                idx = rest.find(sep)
                if 18 <= idx <= 100:
                    chunk = rest[: idx + len(sep)].strip()
                    if chunk:
                        return [chunk], rest[idx + len(sep) :]
        return sentences, rest

    def _short_speak(self, text: str, *, max_chars: int = 280) -> str:
        """Keep spoken replies short so the user hears the answer right after the work finishes."""
        clean = self._clean_for_tts(text or "")
        if not clean:
            return ""
        if len(clean) <= max_chars:
            return clean
        parts = re.split(r"(?<=[.!?])\s+", clean)
        out: list[str] = []
        for p in parts:
            p = (p or "").strip()
            if not p:
                continue
            nxt = (" ".join(out + [p])).strip()
            if out and len(nxt) > max_chars:
                break
            out.append(p)
            if len(out) >= 2:
                break
        spoken = " ".join(out).strip()
        if spoken:
            return spoken
        cut = clean[:max_chars].rsplit(" ", 1)[0].strip()
        return cut or clean[:max_chars]

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        if not text:
            return ""
        text = THINK_RE.sub("", text)
        for pattern in SECRET_RES:                  # privacy: never speak secrets
            text = pattern.sub(" redacted ", text)
        text = CODEBLOCK_RE.sub(" code omitted. ", text)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"^[\s>*#-]+", "", text)
        text = re.sub(r"[*_#]{1,3}([^*_#]+)[*_#]{1,3}", r"\1", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def log_turn(self, timing: TurnTiming) -> None:
        timing.total_done_monotonic = timing.total_done_monotonic or time.perf_counter()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        summary = timing.summary()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        print("TURN TIMING", json.dumps(summary, ensure_ascii=False), flush=True)


load_env()
CFG = load_config()
HERMES = HermesAPI(CFG)   # lightweight API client - independent of the STT pipeline


_HERMES_AUTH_ERR = re.compile(
    r"(?i)HTTP 40[13]\b.*(?:oauth token|api key|token_revoked|not licensed|unauthori[sz]ed)|"
    r"invalidated oauth token|Incorrect API key provided|token_revoked"
)
def _hermes_auth_message() -> str:
    st = chatgpt_login.start(wait_for_code=10.0)
    if st.get("code"):
        return (
            "My ChatGPT sign-in expired, so Layer 2 and photos are paused. "
            f"I opened the OpenAI sign-in page on your PC with the code {st['code']} filled in "
            "(it's also copied) — just press Continue and approve, and I'll reconnect myself."
        )
    return (
        "My ChatGPT sign-in expired, so Layer 2 and photos are paused. "
        f"I tried to reconnect but couldn't: {st.get('error') or 'the sign-in page did not start'}. "
        "Ask me again in a minute and I'll retry."
    )


def _hermes_auth_events() -> Iterator[tuple[str, str]]:
    msg = _hermes_auth_message()
    yield ("text", msg)
    yield ("final", json.dumps({"content": msg, "interrupted": False}))


def _layer_switch_route(text: str) -> dict | None:
    reply = DUAL_BRAIN.try_layer_switch(text)
    if not reply:
        return None
    return {"text": reply, "speak": reply, "tools": [{"name": "layer_switch"}], "run_id": "layer_switch"}


def _hermes_complete(prompt: str, timeout: float = 120.0) -> str | None:
    """One-shot text generation on the main model (Docs/Slides content)."""
    sid = HERMES.get_session_id("jarvis-content-gen", force_new=True)
    parts: list[str] = []
    for kind, value in HERMES.chat_stream_events(sid, prompt, timeout, force_simple=False, lean=True):
        if kind == "text":
            parts.append(value)
        elif kind == "final":
            try:
                info = json.loads(value)
                if info.get("content"):
                    parts = [info["content"]]
            except Exception:
                pass
    return "".join(parts).strip() or None


import workspace_content  # noqa: E402
workspace_content.LLM_COMPLETE = _hermes_complete
PIPELINE: VoicePipelineServer | None = None


_PIPELINE_LOCK = threading.Lock()


def get_pipeline() -> VoicePipelineServer:
    """Lock prevents the four uvicorn listeners' startup hooks from racing
    into concurrent recorder inits (which crashed three of the four lifespans
    and silently killed the TLS ports)."""
    global PIPELINE
    if PIPELINE is None:
        with _PIPELINE_LOCK:
            if PIPELINE is None:
                PIPELINE = VoicePipelineServer(CFG)
    return PIPELINE


app = FastAPI(title="Hermes Voice Pipeline")


def _reap_orphan_stt_workers() -> int:
    """A hard-killed server leaves its RealtimeSTT worker (~450 MB) running forever on Windows."""
    if psutil is None:
        return 0
    here = str(ROOT).lower()
    killed = 0
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() not in ("python.exe", "pythonw.exe"):
                continue
            cmd = " ".join(p.info["cmdline"] or [])
            m = re.search(r"spawn_main\(parent_pid=(\d+)", cmd)
            if not m or psutil.pid_exists(int(m.group(1))):
                continue
            if not p.cwd().lower().startswith(here):
                continue
            p.kill()
            killed += 1
        except (psutil.Error, OSError):
            continue
    return killed


async def _announce_chatgpt_login(evt: dict) -> None:
    kind = evt.get("event")
    if kind == "code":
        title = "ChatGPT sign-in needed"
        text = (
            f"My ChatGPT sign-in expired. I opened the OpenAI page on your PC with code {evt.get('code')} "
            "filled in (also copied) — press Continue and approve, and Layer 2 and photos come back."
        )
    elif kind == "done":
        title = "ChatGPT reconnected"
        text = "ChatGPT is reconnected — Layer 2 and photos are working again."
        if not evt.get("gateway_restarted"):
            text += " (Hermes didn't restart cleanly; if Layer 2 still fails, restart Jarvis.)"
    elif kind == "error":
        title = "ChatGPT sign-in failed"
        text = f"ChatGPT sign-in didn't finish: {evt.get('message')}. Ask me something on Layer 2 to retry."
    else:
        return
    await _broadcast_json({"type": "hud_notify", "title": title, "body": text[:240], "level": "reminder"})
    await _broadcast_json({"type": "reply", "text": text, "partial": False, "reminder": True})


@app.get("/api/chatgpt_login")
async def chatgpt_login_status(request: Request) -> JSONResponse:
    if not _request_authed(request):
        return JSONResponse({"ok": False, "error": "auth required"}, status_code=401)
    st = chatgpt_login.status()
    return JSONResponse({"ok": True, "signed_in": chatgpt_login.auth_ok(), **st})


@app.post("/api/chatgpt_login")
async def chatgpt_login_start(request: Request) -> JSONResponse:
    if not _request_authed(request):
        return JSONResponse({"ok": False, "error": "auth required"}, status_code=401)
    st = await asyncio.to_thread(chatgpt_login.start, 10.0)
    return JSONResponse({"ok": True, **st})


@app.on_event("startup")
async def warm_pipeline() -> None:
    """Warm the local Whisper fallback in the BACKGROUND, exactly once (this
    hook fires once per uvicorn listener — there are four), and never let a
    warm failure take a listener down."""
    global _WARM_STARTED
    if _WARM_STARTED:
        return
    _WARM_STARTED = True
    try:
        reaped = await asyncio.to_thread(_reap_orphan_stt_workers)
        if reaped:
            print(f"Stopped {reaped} orphaned STT worker process(es) from a previous run.", flush=True)
    except Exception as exc:
        print(f"orphan reap: {exc}", flush=True)

    async def warm() -> None:
        try:
            pipe = await asyncio.to_thread(get_pipeline)
            print("STT pipeline warmed.", flush=True)
        except Exception as exc:
            print(f"STT warm failed (remote STT still available): {exc}", flush=True)
            pipe = None

        # Warm Kokoro so the first spoken reply isn't a cold-start stall
        try:
            voice = (CFG.get("voice") or {})
            if voice.get("warm_on_start", True) and pipe is not None:
                timing = TurnTiming(turn_id=0)
                await asyncio.to_thread(
                    lambda: list(pipe.tts_chunks_sync("Ready.", timing))
                )
                print("Kokoro TTS warmed.", flush=True)
        except Exception as exc:
            print(f"Kokoro warm skipped: {exc}", flush=True)

        # Launch Jarvis autonomous study engine in background
        try:
            await asyncio.to_thread(STUDY_ENGINE.start_studying)
            print("Autonomous study engine started.", flush=True)
        except Exception as exc:
            print(f"Study engine start failed: {exc}", flush=True)

        # Layer 2 + photos need Hermes signed in to ChatGPT; re-sign-in without a terminal
        loop = asyncio.get_running_loop()
        chatgpt_login.on_event(
            lambda evt: asyncio.run_coroutine_threadsafe(_announce_chatgpt_login(evt), loop)
        )
        try:
            if not await asyncio.to_thread(chatgpt_login.auth_ok):
                print("ChatGPT sign-in expired — starting automatic re-sign-in.", flush=True)
                await asyncio.to_thread(chatgpt_login.start)
        except Exception as exc:
            print(f"ChatGPT sign-in check failed: {exc}", flush=True)

        # Poll timed "remind me" nudges and push to open HUDs
        async def _reminder_loop() -> None:
            while True:
                try:
                    due = await asyncio.to_thread(pop_due_reminders, CALENDAR_PATH)
                    for ev in due:
                        msg = format_reminder_message(ev)
                        title = str(ev.get("title") or "Reminder")
                        try:
                            await _broadcast_json({
                                "type": "hud_notify",
                                "title": "Reminder",
                                "body": title[:240],
                                "level": "reminder",
                            })
                        except Exception:
                            pass
                        try:
                            await _broadcast_json({
                                "type": "reply",
                                "text": msg,
                                "partial": False,
                                "reminder": True,
                            })
                        except Exception:
                            pass
                        # Speak on warm TTS if any voice clients are connected
                        try:
                            pipe = PIPELINE
                            if pipe is not None and WS_CLIENTS:
                                timing = TurnTiming(turn_id=0)
                                pcm_chunks = await asyncio.to_thread(
                                    lambda: list(pipe.tts_chunks_sync(msg, timing))
                                )
                                for client in list(WS_CLIENTS):
                                    try:
                                        await client.send_json({"type": "agent_status", "state": "speaking"})
                                        for chunk in pcm_chunks:
                                            await client.send_bytes(chunk)
                                        await client.send_json({"type": "agent_status", "state": "idle"})
                                    except Exception:
                                        WS_CLIENTS.discard(client)
                        except Exception as exc:
                            print(f"reminder speak: {exc}", flush=True)
                        print(f"reminder fired: {title}", flush=True)
                except Exception as exc:
                    print(f"reminder loop: {exc}", flush=True)
                await asyncio.sleep(20)

        asyncio.get_running_loop().create_task(_reminder_loop())
        print("Reminder watcher started.", flush=True)

    asyncio.get_running_loop().create_task(warm())


_WARM_STARTED = False


# ------------------------------------------------------------------ Auth

ALLOWED_ORIGIN_HOSTS = {"jarvis.local", "jarvis", "localhost", "127.0.0.1"}
ALLOWED_ORIGIN_HOSTS |= set((CFG.get("security") or {}).get("extra_origin_hosts") or [])
# Suffixes so daily-changing tunnels keep working without editing yaml every reboot
ALLOWED_ORIGIN_SUFFIXES = {
    str(s).lower().lstrip(".")
    for s in ((CFG.get("security") or {}).get("extra_origin_suffixes") or [])
    if s
}
# Always allow Cloudflare quick tunnels + common free stable tunnel providers
ALLOWED_ORIGIN_SUFFIXES |= {
    "trycloudflare.com",
    "ngrok-free.app",
    "ngrok-free.dev",
    "ngrok.app",
    "ngrok.io",
}


def _origin_host_allowed(host: str) -> bool:
    h = (host or "").lower().strip(".")
    if not h:
        return False
    if h in ALLOWED_ORIGIN_HOSTS:
        return True
    return any(h == suf or h.endswith("." + suf) for suf in ALLOWED_ORIGIN_SUFFIXES)


def hud_token() -> str | None:
    env_name = (CFG.get("security") or {}).get("hud_token_env", "JARVIS_HUD_TOKEN")
    return os.environ.get(env_name) or None


def _request_authed(request: Request) -> bool:
    token = hud_token()
    if not token:
        return True
    supplied = request.headers.get("x-jarvis-token") or request.cookies.get("jarvis_token")
    return supplied == token


@app.middleware("http")
async def api_auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and not _request_authed(request):
        return Response(status_code=401, content="jarvis auth required")
    return await call_next(request)


def _ws_allowed(ws: WebSocket) -> bool:
    """Browsers send Origin (+cookie); native clients (PTT, tests) send neither."""
    origin = ws.headers.get("origin")
    if not origin:
        return True  # non-browser client on the LAN (Python PTT, e2e tests)
    from urllib.parse import urlparse
    host = (urlparse(origin).hostname or "").lower()
    if not _origin_host_allowed(host):
        return False
    token = hud_token()
    if not token:
        return True
    return ws.cookies.get("jarvis_token") == token or ws.query_params.get("token") == token


# --------------------------------------------------------------- HUD + proxy

HUD_DIR = ROOT / "hud"
ALLOWED_GET_PATHS = {
    "/health", "/health/detailed", "/v1/capabilities",
    "/v1/skills", "/v1/toolsets", "/api/jobs", "/api/sessions",
}


def _proxy_allowed(method: str, path: str) -> bool:
    if method == "GET":
        return path in ALLOWED_GET_PATHS or (
            path.startswith("/api/sessions/") and path.endswith("/messages")
        )
    if method == "POST":
        return path == "/v1/responses"
    return False


@app.api_route("/api/hermes/{path:path}", methods=["GET", "POST"])
async def hermes_proxy(path: str, request: Request) -> Response:
    target = "/" + path
    if not _proxy_allowed(request.method, target):
        return Response(status_code=403, content="path not allowed")
    hermes = HERMES
    body = await request.body()
    params = dict(request.query_params)

    def do_request() -> requests.Response:
        return requests.request(
            request.method, hermes.base + target, params=params,
            headers=hermes.headers(), data=body if body else None, timeout=300,
        )

    try:
        resp = await asyncio.to_thread(do_request)
    except requests.RequestException as exc:
        return JSONResponse({"ok": False, "error": "Hermes is offline", "detail": str(exc)[:200]},
                            status_code=503)
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type=resp.headers.get("Content-Type", "application/json"))


@app.post("/api/chat")
async def hud_chat(request: Request) -> JSONResponse:
    """Typed chat from the HUD — same Hermes session as voice. Optional photo attachment."""
    body = await request.json()
    text = (body.get("text") or body.get("input") or "").strip()
    conversation = body.get("conversation") or (CFG.get("hermes") or {}).get("conversation", "jarvis-main")
    image = body.get("image") or body.get("image_data_url") or body.get("image_base64")
    mime = (body.get("mime") or body.get("image_mime") or "image/jpeg").strip()
    image_data_url = None
    if image:
        img = str(image).strip()
        if img.startswith("data:"):
            image_data_url = img
        else:
            # raw base64
            image_data_url = f"data:{mime};base64,{img}"
        if not text:
            # Neutral — never assume homework; user may send any photo
            text = (
                "Look at this photo and respond helpfully based on what you see. "
                "Follow any caption or instructions from the user if present."
            )
    if not text and not image_data_url:
        return JSONResponse({"error": "empty input"}, status_code=400)
    pc_task_id = str(body.get("pc_task_id") or "").strip()
    device = str(body.get("device") or "").strip().lower()
    pc_match = PC_TASK_RE.match(text) if not pc_task_id and not image_data_url else None
    if pc_match:
        task = pc_match.group(1).strip()
        if device != "pc":
            try:
                return JSONResponse(await _run_pc_task(task, conversation))
            except Exception as exc:
                return JSONResponse({"error": str(exc)}, status_code=502)
        text = task or text
    try:
        out = await _run_hud_chat(text, conversation, image_data_url=image_data_url)
        if pc_task_id:
            _finish_pc_task(pc_task_id, out)
        return JSONResponse(out)
    except Exception as exc:
        if pc_task_id:
            _finish_pc_task(pc_task_id, error=str(exc))
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/chat/voice")
async def hud_chat_voice(request: Request) -> JSONResponse:
    """WhatsApp-style voice note for HUD chat: raw PCM s16le 16kHz mono → same as typed chat."""
    audio = await request.body()
    if not audio or len(audio) < 1600:  # < ~50ms
        return JSONResponse({
            "ok": True,
            "unclear": True,
            "error": "Voice note too short — hold MIC a bit longer.",
            "transcript": "",
            "text": "That voice note was too short. Hold the MIC button and speak, then release.",
            "tools": [],
            "run_id": None,
        })
    conversation = (
        request.query_params.get("conversation")
        or (CFG.get("hermes") or {}).get("conversation", "jarvis-main")
    )
    try:
        raw = await get_pipeline().transcribe(audio)
        clarity = assess_transcript(
            raw,
            audio_bytes=len(audio),
            sample_rate=int((CFG.get("stt") or {}).get("sample_rate", 16000)),
            pcm=audio,
        )
        if not clarity.proceed:
            msg = clarify_message(clarity)
            return JSONResponse({
                "ok": True,
                "unclear": True,
                "clarity": clarity.status,
                "reason": clarity.reason,
                "transcript": clarity.cleaned or (raw or "").strip(),
                "text": msg,
                "tools": [],
                "run_id": None,
            })
        out = await _run_hud_chat(
            clarity.cleaned,
            conversation,
            brain_text=clarity.brain_text,
            skip_hard_routes=(clarity.status == "uncertain"),
        )
        out["transcript"] = clarity.cleaned
        out["clarity"] = clarity.status
        out["reason"] = clarity.reason
        out["ok"] = True
        if out.get("translated_to"):
            out["translated_to"] = out["translated_to"]
        return JSONResponse(out)
    except Exception as exc:
        print(f"hud_chat_voice error: {exc}", flush=True)
        return JSONResponse({
            "ok": False,
            "unclear": False,
            "error": str(exc),
            "transcript": "",
            "text": "Voice note failed on my end — try once more.",
            "tools": [],
            "run_id": None,
        }, status_code=200)


async def _run_hud_chat(
    text: str,
    conversation: str,
    *,
    brain_text: str | None = None,
    skip_hard_routes: bool = False,
    image_data_url: str | None = None,
) -> dict:
    """Shared typed + voice-note chat path (no TTS — text reply only).

    brain_text: optional enriched prompt for Hermes (voice clarity prefix).
    skip_hard_routes: when STT is uncertain, only ask Hermes to clarify.
    image_data_url: optional data:image/...;base64,... for homework photos.
    """
    STUDY_ENGINE.notify_busy()
    try:
        STUDY_ENGINE.note_interest(text)
        return await _run_hud_chat_inner(
            text,
            conversation,
            brain_text=brain_text,
            skip_hard_routes=skip_hard_routes,
            image_data_url=image_data_url,
        )
    finally:
        STUDY_ENGINE.notify_idle()


async def _run_hud_chat_inner(
    text: str,
    conversation: str,
    *,
    brain_text: str | None = None,
    skip_hard_routes: bool = False,
    image_data_url: str | None = None,
) -> dict:
    out: dict = {"text": "", "tools": [], "run_id": None, "memories_saved": []}
    force_simple: bool | None = None

    # Slash commands handled locally (don't send bare /new to Hermes)
    raw = (text or "").strip()
    if re.match(r"(?is)^\s*/(?:new|reset|clear)\s*$", raw):
        try:
            HERMES.get_session_id(conversation, force_new=True)
        except Exception as exc:
            return {"text": f"Could not reset conversation: {exc}", "tools": [], "run_id": None, "error": str(exc)}
        return {"text": "Conversation reset. Fresh start.", "tools": [], "run_id": None, "reset": True}

    if re.match(r"(?is)^\s*/help\s*$", raw):
        return {
            "text": (
                "Commands:\n"
                "/simple - answers only (no fluff)\n"
                "/full - normal explanations\n"
                "/english - reply in English (default)\n"
                "/arabic - reply in Arabic\n"
                "/new - reset conversation\n"
                "CAM - attach a photo (type a description in the box first if you want)\n"
            ),
            "tools": [],
            "run_id": None,
        }

    lang_slash = parse_lang_slash(raw)
    if lang_slash and lang_slash.get("ack"):
        return {"text": lang_slash["ack"], "tools": [], "run_id": None, "reply_lang": lang_slash}

    reply_slash = parse_reply_slash(raw)
    if reply_slash and reply_slash.get("ack"):
        return {
            "text": reply_slash["ack"],
            "tools": [],
            "run_id": None,
            "simple": reply_slash.get("simple"),
        }
    if reply_slash and reply_slash.get("text"):
        text = reply_slash["text"]
        force_simple = True if reply_slash.get("force_simple") else force_simple

    # Kuwaiti/Arabic commands → English for hard-routes
    tr = translate_command(text)
    route_text = normalize_command(tr.translated or text) or tr.translated or text
    if tr.changed:
        out["translated_from"] = tr.original
        out["translated_to"] = route_text
        STUDY_ENGINE.note_interest(route_text)
    # Hermes still sees Arabic (with translation hint applied in chat_stream_events)
    hermes_input = (brain_text or text).strip() or text
    force_brain: str | None = None
    if tr.changed:
        hermes_input = hermes_arabic_hint(text)

    # Photo of handwriting → memorize forever (also if they ask to write with a sample photo)
    if image_data_url and (
        wants_handwriting_memorize(route_text)
        or (wants_handwriting_write(route_text) and not handwriting_status().get("configured"))
    ):
        out["has_image"] = True

        def _extract_hw(prompt: str, img: str) -> str:
            timeout = float((CFG.get("hermes") or {}).get("timeout", 240))
            sid = HERMES.get_session_id("jarvis-handwriting-ocr", force_new=True)
            parts: list[str] = []
            for kind, value in HERMES.chat_stream_events(
                sid,
                prompt,
                timeout,
                image_data_url=img,
                force_simple=True,
            ):
                if kind == "text":
                    parts.append(value)
                elif kind == "final":
                    try:
                        info = json.loads(value)
                        if info.get("content"):
                            parts = [info["content"]]
                    except Exception:
                        pass
            return "".join(parts).strip()

        try:
            result = await asyncio.to_thread(
                ingest_handwriting_photo,
                image_data_url=image_data_url,
                user_text=route_text or "memorize my handwriting",
                memory_path=MEMORY_PATH,
                extract_fn=_extract_hw,
            )
            # If they also asked to write, continue into write below (don't return yet)
            if wants_handwriting_write(route_text):
                out["handwriting_memorized"] = True
                out["memorize_text"] = result.get("text")
            else:
                out.update(result)
                return out
        except Exception as exc:
            print(f"handwriting memorize: {exc}", flush=True)
            if not wants_handwriting_write(route_text):
                out["text"] = f"I couldn't memorize that handwriting photo just now. ({exc})"
                out["error"] = str(exc)
                return out

    # Write in memorized handwriting → for Google Docs, type in Chrome (no API)
    if wants_handwriting_write(route_text):
        out["has_image"] = bool(image_data_url)
        try:
            # Prefer Chrome Docs typing whenever they mention Google Docs
            if re.search(r"(?is)\b(?:google\s+)?docs?\b", route_text):
                routed = await asyncio.to_thread(open_docs_and_type, route_text)
            else:
                routed = await asyncio.to_thread(write_handwritten_document, route_text, upload=False)
            if routed:
                text_out = routed.get("text") or ""
                if out.get("memorize_text"):
                    text_out = f"{out['memorize_text']}\n\n{text_out}"
                out["text"] = text_out
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                if routed.get("webViewLink"):
                    out["hud_url"] = routed.get("webViewLink")
                out["ok"] = routed.get("ok", True)
                return out
        except Exception as exc:
            print(f"handwriting/docs write chat(photo): {exc}", flush=True)

    # Photo of notes → Second Brain (before generic photo skip)
    if image_data_url and wants_notes_to_brain(route_text):
        out["has_image"] = True

        def _extract(prompt: str, img: str) -> str:
            timeout = float((CFG.get("hermes") or {}).get("timeout", 240))
            sid = HERMES.get_session_id("jarvis-notes-ocr", force_new=True)
            parts: list[str] = []
            for kind, value in HERMES.chat_stream_events(
                sid,
                prompt,
                timeout,
                image_data_url=img,
                force_simple=True,
            ):
                if kind == "text":
                    parts.append(value)
                elif kind == "final":
                    try:
                        info = json.loads(value)
                        if info.get("content"):
                            parts = [info["content"]]
                    except Exception:
                        pass
            return "".join(parts).strip()

        try:
            result = await asyncio.to_thread(
                ingest_notes_photo,
                image_data_url=image_data_url,
                user_text=route_text,
                brain_path=BRAIN_PATH,
                extract_fn=_extract,
            )
            out.update(result)
            return out
        except Exception as exc:
            print(f"notes photo ingest: {exc}", flush=True)
            out["text"] = (
                "I couldn't read those notes into Second Brain just now. "
                f"({exc})"
            )
            out["error"] = str(exc)
            return out

    # Photo of yearly schedule / holidays → calendar holidays (never homework)
    if image_data_url and (
        wants_school_calendar_photo(route_text)
        or looks_like_calendar_caption(route_text)
    ):
        out["has_image"] = True

        def _extract_cal(prompt: str, img: str) -> str:
            timeout = float((CFG.get("hermes") or {}).get("timeout", 240))
            sid = HERMES.get_session_id("jarvis-year-cal-ocr", force_new=True)
            parts: list[str] = []
            for kind, value in HERMES.chat_stream_events(
                sid,
                prompt,
                timeout,
                image_data_url=img,
                force_simple=True,
            ):
                if kind == "text":
                    parts.append(value)
                elif kind == "final":
                    try:
                        info = json.loads(value)
                        if info.get("content"):
                            parts = [info["content"]]
                    except Exception:
                        pass
            return "".join(parts).strip()

        try:
            proceed = wants_school_calendar_photo(route_text)
            if not proceed:
                proceed = await asyncio.to_thread(
                    classify_calendar_photo,
                    image_data_url=image_data_url,
                    extract_fn=_extract_cal,
                )
            if proceed:
                result = await asyncio.to_thread(
                    ingest_school_calendar_photo,
                    image_data_url=image_data_url,
                    user_text=route_text,
                    calendar_path=CALENDAR_PATH,
                    extract_fn=_extract_cal,
                    push_fn=cal_push_phone,
                )
                out.update(result)
                try:
                    await _broadcast_json({
                        "type": "calendar_updated",
                        "count": result.get("count") or 0,
                    })
                except Exception:
                    pass
                return out
        except Exception as exc:
            print(f"school calendar photo ingest: {exc}", flush=True)
            # Fall through to generic Hermes photo handling

    # Photos skip hard-routes / Layer 1 (they can't see the image)
    if image_data_url:
        skip_hard_routes = True
        out["has_image"] = True

    if not skip_hard_routes:
        try:
            saved = await asyncio.to_thread(auto_save_from_text, MEMORY_PATH, route_text, BRAIN_PATH)
            out["memories_saved"] = saved
            if saved:
                await _broadcast_json({
                    "type": "memory_saved",
                    "facts": saved,
                    "count": len(saved),
                })
                if any(f.get("brain_idea_id") for f in saved):
                    try:
                        await _broadcast_json({"type": "brain_updated"})
                    except Exception:
                        pass
        except Exception as exc:
            print(f"auto_memory chat: {exc}", flush=True)

    if not skip_hard_routes:
        clock = try_handle_clock(route_text) or _layer_switch_route(route_text)
        if clock:
            out["text"] = clock["text"]
            out["tools"] = clock["tools"]
            out["run_id"] = clock["run_id"]
            return out
        try:
            routed = await asyncio.to_thread(
                try_resolve_pending, route_text, CALENDAR_PATH, BRAIN_PATH, MEMORY_PATH
            )
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                try:
                    await _broadcast_json({"type": "calendar_updated", "count": routed.get("count") or 0})
                except Exception:
                    pass
                if routed.get("run_id") in ("school_life_done", "brain_ideas_cleared"):
                    try:
                        await _broadcast_json({"type": "brain_updated"})
                        await _broadcast_json({"type": "memory_saved", "facts": [], "count": 0})
                    except Exception:
                        pass
                return out
        except Exception as exc:
            print(f"pending followup: {exc}", flush=True)
        try:
            routed = await asyncio.to_thread(
                try_start_followup, route_text, CALENDAR_PATH, MEMORY_PATH, BRAIN_PATH
            )
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                if routed.get("run_id") == "school_life_done":
                    try:
                        await _broadcast_json({"type": "calendar_updated", "count": routed.get("count") or 0})
                        await _broadcast_json({"type": "brain_updated"})
                    except Exception:
                        pass
                return out
        except Exception as exc:
            print(f"start followup: {exc}", flush=True)
        if wants_handwriting_write(route_text):
            try:
                if re.search(r"(?is)\b(?:google\s+)?docs?\b", route_text):
                    routed = await asyncio.to_thread(open_docs_and_type, route_text)
                else:
                    routed = await asyncio.to_thread(write_handwritten_document, route_text, upload=False)
                if routed:
                    out["text"] = routed.get("text") or ""
                    out["tools"] = routed.get("tools") or []
                    out["run_id"] = routed.get("run_id")
                    if routed.get("webViewLink"):
                        out["hud_url"] = routed.get("webViewLink")
                    return out
            except Exception as exc:
                print(f"handwriting write chat: {exc}", flush=True)
        try:
            routed = await asyncio.to_thread(try_handle_docs_chrome, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                if routed.get("webViewLink"):
                    out["hud_url"] = routed.get("webViewLink")
                return out
        except Exception as exc:
            print(f"docs chrome chat: {exc}", flush=True)
        try:
            routed = await asyncio.to_thread(try_handle_google_workspace, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                if routed.get("webViewLink"):
                    out["hud_url"] = routed.get("webViewLink")
                return out
        except Exception as exc:
            print(f"google workspace chat: {exc}", flush=True)
        try:
            routed = await asyncio.to_thread(
                try_handle_classroom, route_text, simple=want_simple(force_simple=force_simple)
            )
            if routed:
                if routed.get("needs_calendar_refresh"):
                    try:
                        await _broadcast_json({"type": "calendar_updated", "count": routed.get("count") or 1})
                    except Exception:
                        pass
                if routed.get("brain_followup"):
                    force_brain = str(routed["brain_followup"])
                    hermes_input = force_brain
                    out["tools"] = routed.get("tools") or []
                    out["layer"] = 2
                    shot = routed.get("attachment_image")
                    if shot and not image_data_url:
                        try:
                            raw_img = Path(shot).read_bytes()
                            if raw_img and len(raw_img) < 1_800_000:
                                import base64 as _b64
                                image_data_url = "data:image/jpeg;base64," + _b64.b64encode(raw_img).decode("ascii")
                        except Exception as exc:
                            print(f"classroom image attach: {exc}", flush=True)
                else:
                    out["text"] = routed.get("text") or ""
                    out["tools"] = routed.get("tools") or []
                    out["run_id"] = routed.get("run_id")
                    return out
        except Exception as exc:
            print(f"classroom route: {exc}", flush=True)

        # Browse a user-given website (read several pages) then answer with Hermes
        if not force_brain:
            try:
                routed = await asyncio.to_thread(try_handle_site_browse, route_text)
                if routed:
                    out["tools"] = routed.get("tools") or []
                    if routed.get("brain_followup"):
                        force_brain = str(routed["brain_followup"])
                        hermes_input = force_brain
                        out["layer"] = 2
                        if routed.get("speak"):
                            out["speak"] = routed["speak"]
                    else:
                        out["text"] = routed.get("text") or ""
                        out["run_id"] = routed.get("run_id")
                        return out
            except Exception as exc:
                print(f"site browse route: {exc}", flush=True)

    # Hard-route movies/Vidbox so Hermes cannot open YouTube by mistake
    if not skip_hard_routes and not force_brain:
        try:
            routed = await asyncio.to_thread(try_handle_movie_rating, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"movie rating route: {exc}", flush=True)

        try:
            routed = await asyncio.to_thread(try_handle_youtube, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                if routed.get("speak"):
                    out["speak"] = routed["speak"]
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"youtube route: {exc}", flush=True)

        try:
            routed = await asyncio.to_thread(try_handle_movies, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"movies route: {exc}", flush=True)

        # Hard-route map ETA (Kuwait atlas + free OSRM)
        try:
            routed = await asyncio.to_thread(try_handle_maps, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                if routed.get("maps_url"):
                    out["maps_url"] = routed["maps_url"]
                return out
        except Exception as exc:
            print(f"maps route: {exc}", flush=True)

        # Hard-route phone calls to Skills/Memory contacts only
        try:
            routed = await asyncio.to_thread(try_handle_call, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"call route: {exc}", flush=True)

        # WhatsApp type / type+send (saved phone contacts only; send needs phone ALLOW)
        try:
            routed = await asyncio.to_thread(try_handle_whatsapp, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                if routed.get("speak"):
                    out["speak"] = routed["speak"]
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"whatsapp route: {exc}", flush=True)

        # Hard-route email read + chat drafts (never send)
        try:
            routed = await asyncio.to_thread(try_handle_email, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"email route: {exc}", flush=True)

        # Hard-route open <app> (after Arabic→English translation)
        try:
            routed = await asyncio.to_thread(try_handle_open, route_text)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"open route: {exc}", flush=True)

        # Hard-route daily briefing request
        try:
            routed = await asyncio.to_thread(try_handle_briefing, route_text, CALENDAR_PATH, BRAIN_PATH)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                return out
        except Exception as exc:
            print(f"briefing route: {exc}", flush=True)

        # Hard-route fast calendar add (homework / remind / single class) — no Hermes wait
        try:
            routed = await asyncio.to_thread(try_handle_calendar, route_text, CALENDAR_PATH)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                try:
                    await _broadcast_json({"type": "calendar_updated", "count": routed.get("count") or 1})
                except Exception:
                    pass
                if routed.get("brain_idea"):
                    try:
                        await _broadcast_json({"type": "brain_updated", "idea": routed.get("brain_idea")})
                    except Exception:
                        pass
                # Optional Google phone sync in background (don't block the reply)
                if routed.get("push_phone") and routed.get("event"):
                    async def _bg_push(ev=routed["event"]):
                        try:
                            await asyncio.to_thread(cal_push_phone, CALENDAR_PATH, ev)
                        except Exception as exc:
                            print(f"calendar push bg: {exc}", flush=True)
                    asyncio.create_task(_bg_push())
                return out
        except Exception as exc:
            print(f"calendar route: {exc}", flush=True)

        # Hard-route schedule ingestion to calendar
        try:
            routed = await asyncio.to_thread(try_handle_schedule, route_text, CALENDAR_PATH)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                try:
                    await _broadcast_json({"type": "calendar_updated", "count": routed.get("count")})
                except Exception:
                    pass
                return out
        except Exception as exc:
            print(f"schedule route: {exc}", flush=True)

        # Hard-route second brain ideas & notes
        try:
            routed = await asyncio.to_thread(try_handle_brain_idea, route_text, BRAIN_PATH)
            if routed:
                out["text"] = routed.get("text") or ""
                out["tools"] = routed.get("tools") or []
                out["run_id"] = routed.get("run_id")
                try:
                    await _broadcast_json({"type": "brain_updated", "idea": routed.get("idea")})
                except Exception:
                    pass
                return out
        except Exception as exc:
            print(f"brain idea route: {exc}", flush=True)

        # Dual-Brain Layer 1 (Local Autonomous Mind) check — skip when a hard-route already packed Hermes context
        if not force_brain:
          try:
            db_cfg = CFG.get("dual_brain") or {}
            l1_timeout = float(db_cfg.get("chat_layer1_timeout") or 10.0)
            l1_res = await asyncio.to_thread(
                DUAL_BRAIN.route, route_text, layer1_timeout=l1_timeout, skip_layer1=False
            )
            if l1_res.get("can_answer"):
                src = l1_res.get("source") or "local_mind"
                reply = (l1_res.get("text") or "").strip()
                if src == "router":
                    out["text"] = reply
                    out["layer"] = l1_res.get("layer") or 1
                    out["model"] = "router"
                    out["tools"] = [{"name": "dual_brain_router", "preview": f"mode={l1_res.get('force_layer') or 'auto'}"}]
                else:
                    # Never announce the layer — just reply / act.
                    out["text"] = reply
                    out["layer"] = 1
                    out["model"] = l1_res.get("model")
                    out["latency_ms"] = l1_res.get("latency_ms")
                    out["tools"] = [{"name": "layer1_local_mind", "preview": f"{l1_res.get('model')} ({l1_res.get('latency_ms')}ms)"}]
                return out
            # Layer 1 cannot / user forced Layer 2 → Hermes
            cleaned = (l1_res.get("cleaned_text") or "").strip()
            if cleaned:
                hermes_input = cleaned
            out["layer"] = 2
            out["escalate_reason"] = l1_res.get("reason")
          except Exception as exc:
            print(f"dual_brain chat route: {exc}", flush=True)

    def run_sync() -> None:
        timeout = float((CFG.get("hermes") or {}).get("timeout", 240))

        def consume(sid: str) -> list[str]:
            parts: list[str] = []
            for kind, value in HERMES.chat_stream_events(
                sid,
                hermes_input,
                timeout,
                image_data_url=image_data_url,
                force_simple=force_simple,
                lean=(
                    False
                    if image_data_url
                    else not is_complex_question(hermes_input)
                ),
            ):
                if kind == "text":
                    parts.append(value)
                elif kind == "tool":
                    out["tools"].append(json.loads(value))
                elif kind == "run":
                    out["run_id"] = value
                elif kind == "final":
                    info = json.loads(value)
                    if info.get("content"):
                        parts = [info["content"]]
            return parts

        try:
            parts = consume(HERMES.get_session_id(conversation))
        except Exception as exc:
            msg = str(exc)
            # Session gone / create failed / stream 404 — recreate once
            if not any(code in msg for code in ("404", "400", "409", "422", "Not Found", "Bad Request")):
                raise
            print(f"Hermes chat session retry ({type(exc).__name__}: {exc})", flush=True)
            out["tools"].clear()
            parts = consume(HERMES.get_session_id(conversation, force_new=True))
        out["text"] = "".join(parts).strip()

    try:
        await asyncio.to_thread(run_sync)
    except Exception as exc:
        print(f"hud chat hermes error: {exc}", flush=True)
        out["text"] = (
            out.get("text")
            or "I hit a brain connection glitch. Try that again in a moment."
        )
        out["error"] = str(exc)
    return out


def _kokoro_health() -> dict:
    voice = CFG.get("voice") or {}
    base_url = voice.get("base_url", "http://127.0.0.1:8880/v1").rstrip("/")
    health_url = base_url.rsplit("/v1", 1)[0] + "/health"
    online = False
    try:
        r = requests.get(health_url, timeout=5)
        online = r.ok
    except Exception:
        pass
    return {
        "online": online,
        "voice": voice.get("voice", "af_heart"),
        "voice_name": voice.get("voice_name", ""),
        "base_url": base_url,
    }


@app.get("/api/usage")
async def usage() -> JSONResponse:
    """LLM token usage (local tally) + Kokoro TTS health."""
    u = read_usage()
    cost_cfg = CFG.get("usage") or {}
    cin = float(cost_cfg.get("llm_cost_per_mtok_input", 0) or 0)
    cout = float(cost_cfg.get("llm_cost_per_mtok_output", 0) or 0)

    def est(b: dict) -> float | None:
        if not (cin or cout):
            return None
        return round(b.get("llm_in", 0) / 1e6 * cin + b.get("llm_out", 0) / 1e6 * cout, 4)

    out = {
        "llm": {
            "today": u["today"], "total": u["total"],
            "today_cost": est(u["today"]), "total_cost": est(u["total"]),
        },
        "kokoro": await asyncio.to_thread(_kokoro_health),
    }
    return JSONResponse(out)


@app.get("/api/calendar")
async def calendar_get() -> JSONResponse:
    """Homework/due events + weekly schedule for the HUD calendar page."""
    data = cal_load(CALENDAR_PATH)
    events = sorted(
        data.get("events") or [],
        key=lambda e: (e.get("date") or "", e.get("time") or ""),
    )
    day_order = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    schedule = sorted(
        data.get("schedule") or [],
        key=lambda s: (day_order.get(s.get("day"), 9), s.get("start") or "", s.get("title") or ""),
    )
    return JSONResponse({
        "events": events,
        "schedule": schedule,
        "updated_at": data.get("updated_at"),
    })


@app.get("/api/calendar/today")
async def calendar_today(day: str = "") -> JSONResponse:
    """School/university classes + dated events for one weekday (default: today)."""
    data = cal_load(CALENDAR_PATH)
    day_order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    labels = {
        "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
        "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
    }
    code = (day or "").strip().lower()[:3]
    if code not in day_order:
        # Python: Mon=0 .. Sun=6 → our keys
        code = day_order[datetime.now().weekday()]
    classes = sorted(
        [s for s in (data.get("schedule") or []) if s.get("day") == code],
        key=lambda s: (s.get("start") or "99:99", s.get("title") or ""),
    )
    # Map weekday code to a concrete date for this week (for homework overlay)
    today = datetime.now().date()
    delta = day_order.index(code) - today.weekday()
    target = today + timedelta(days=delta)
    ymd = target.isoformat()
    events = sorted(
        [e for e in (data.get("events") or []) if e.get("date") == ymd],
        key=lambda e: (e.get("time") or "", e.get("title") or ""),
    )
    return JSONResponse({
        "ok": True,
        "day": code,
        "day_name": labels.get(code, code),
        "date": ymd,
        "is_today": code == day_order[today.weekday()],
        "classes": classes,
        "events": events,
        "updated_at": data.get("updated_at"),
    })


@app.post("/api/calendar/events")
async def calendar_add_event(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        ev = cal_upsert_event(CALENDAR_PATH, body if isinstance(body, dict) else {})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    sync = await asyncio.to_thread(cal_push_phone, CALENDAR_PATH, ev)
    ev = sync.get("event") or ev
    apple = sync.get("apple_reminders") or {}
    if apple.get("queued") and apple.get("scheme"):
        await _broadcast_json({
            "type": "phone_open",
            "command_id": apple.get("command_id"),
            "app": apple.get("app") or "shortcuts",
            "label": apple.get("label") or "Jarvis Reminder",
            "url": None,
            "scheme": apple.get("scheme"),
        })
    await _broadcast_json({"type": "calendar_updated", "event": ev})
    return JSONResponse({
        "ok": True,
        "event": ev,
        "phone_sync": sync,
        "message": (
            "Saved to Jarvis calendar"
            + (" and Google Calendar with phone alerts." if (sync.get("google") or {}).get("ok")
               else ". Link Google Calendar in Connect for phone reminders.")
        ),
    })


@app.delete("/api/calendar/events/{event_id}")
async def calendar_delete_event(event_id: str) -> JSONResponse:
    removed = cal_delete_event(CALENDAR_PATH, event_id)
    if not removed:
        return JSONResponse({"ok": False, "error": "event not found"}, status_code=404)
    remote = await asyncio.to_thread(cal_delete_remote, removed)
    await _broadcast_json({"type": "calendar_updated", "deleted": event_id})
    return JSONResponse({"ok": True, "deleted": event_id, "google": remote})


@app.post("/api/calendar/events/import")
async def calendar_import_events(request: Request) -> JSONResponse:
    body = await request.json()
    items = body.get("events") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return JSONResponse({"ok": False, "error": "events must be a list"}, status_code=400)
    result = cal_import_events(CALENDAR_PATH, items)
    sync = await asyncio.to_thread(cal_push_phone_many, CALENDAR_PATH, result.get("events") or [])
    await _broadcast_json({"type": "calendar_updated", "imported": result.get("added")})
    return JSONResponse({"ok": True, **result, "phone_sync": sync})


@app.post("/api/calendar/schedule")
async def calendar_set_schedule(request: Request) -> JSONResponse:
    """Replace or merge weekly schedule items. Body: {items:[...], merge?:bool} or a bare list."""
    body = await request.json()
    if isinstance(body, list):
        items, merge = body, False
    elif isinstance(body, dict):
        items = body.get("items") or body.get("schedule") or []
        merge = bool(body.get("merge"))
        if body.get("title") and body.get("day"):
            items = [body]
    else:
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    if not isinstance(items, list) or not items:
        return JSONResponse({"ok": False, "error": "items required"}, status_code=400)
    try:
        if len(items) == 1 and merge:
            item = cal_add_schedule(CALENDAR_PATH, items[0])
            return JSONResponse({"ok": True, "item": item})
        schedule = cal_replace_schedule(CALENDAR_PATH, items, merge=merge)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "schedule": schedule})


@app.delete("/api/calendar/schedule/{item_id}")
async def calendar_delete_schedule(item_id: str) -> JSONResponse:
    ok = cal_delete_schedule(CALENDAR_PATH, item_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "schedule item not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": item_id})


@app.get("/api/brain")
async def brain_get() -> JSONResponse:
    """Second Brain graph — genres, ideas, and links for the HUD brain page."""
    return JSONResponse(brain_snapshot(BRAIN_PATH))


@app.post("/api/brain/genres")
async def brain_add_genre_route(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        genre = brain_add_genre(BRAIN_PATH, body if isinstance(body, dict) else {})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "genre": genre})


@app.delete("/api/brain/genres/{genre_id}")
async def brain_delete_genre_route(genre_id: str) -> JSONResponse:
    ok = brain_delete_genre(BRAIN_PATH, genre_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "genre not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": genre_id})


@app.post("/api/brain/ideas")
async def brain_add_idea_route(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    link_ids = body.pop("link_ids", None) or body.pop("links", None)
    sync_links = bool(body.pop("sync_links", False))
    if link_ids is not None and not isinstance(link_ids, list):
        return JSONResponse({"ok": False, "error": "link_ids must be a list"}, status_code=400)
    try:
        idea = brain_upsert_idea(BRAIN_PATH, body, link_ids=link_ids, sync_links=sync_links)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "idea": idea})


@app.post("/api/brain/ideas/smart")
async def brain_add_idea_smart_route(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    title = str(body.get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "title is required"}, status_code=400)
    desc = str(body.get("description") or "").strip() or None
    purpose = str(body.get("purpose") or "").strip().lower() or None
    link_ids = body.get("link_ids")
    try:
        idea = brain_add_idea_smart(BRAIN_PATH, title=title, description=desc, purpose=purpose, link_ids=link_ids)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "idea": idea})


@app.get("/api/model")
async def model_get_route() -> JSONResponse:
    """Current ChatGPT / Hermes brain model + available picker list."""
    return JSONResponse(model_get_current())


@app.get("/api/maps/places")
async def maps_places_route() -> JSONResponse:
    """List known Kuwait areas (fast local atlas)."""
    return JSONResponse({"ok": True, "places": list_kuwait_places()})


@app.post("/api/maps/eta")
async def maps_eta_route(request: Request) -> JSONResponse:
    """Travel time between two places — Kuwait atlas + free OSRM (no API key)."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    origin = str(body.get("origin") or body.get("from") or "").strip()
    dest = str(body.get("destination") or body.get("to") or "").strip()
    profile = str(body.get("profile") or body.get("mode") or "driving").strip().lower()
    if profile not in {"driving", "walking"}:
        profile = "driving"
    if not origin or not dest:
        return JSONResponse({"ok": False, "error": "origin and destination required"}, status_code=400)
    result = await asyncio.to_thread(eta_between, origin, dest, profile=profile)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@app.post("/api/model")
async def model_set_route(request: Request) -> JSONResponse:
    """Switch ChatGPT / Hermes brain model from the HUD picker."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    model_id = str(body.get("model") or body.get("id") or "").strip()
    provider = body.get("provider")
    if not model_id:
        return JSONResponse({"ok": False, "error": "model is required"}, status_code=400)
    try:
        result = model_set_current(model_id, provider=str(provider) if provider else None)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse(result)


@app.get("/api/briefing")
async def briefing_get_route() -> JSONResponse:
    """Get the synthesized daily briefing data and spoken text."""
    data = build_briefing_data(CALENDAR_PATH, BRAIN_PATH)
    return JSONResponse({"ok": True, **data})


@app.post("/api/briefing/speak")
async def briefing_speak_route() -> JSONResponse:
    """Generate TTS audio for the daily briefing and speak it aloud through PC speakers."""
    data = build_briefing_data(CALENDAR_PATH, BRAIN_PATH)
    audio_path = Path(__file__).resolve().parent / "hud" / "audio" / "boot_briefing.mp3"
    generated = generate_briefing_audio(data["spoken_text"], audio_path, timeout=45.0)
    if generated:
        play_audio_file(generated)
        return JSONResponse({"ok": True, "played": True, "text": data["spoken_text"]})
    return JSONResponse({"ok": False, "error": "Audio generation failed", "text": data["spoken_text"]}, status_code=500)


@app.get("/api/composio/status")
async def composio_status_route() -> JSONResponse:
    return JSONResponse(composio_bridge.status())


@app.post("/api/composio/connect")
async def composio_connect_route(request: Request) -> JSONResponse:
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not isinstance(body, dict):
        body = {}
    toolkit = (body.get("toolkit") or body.get("app") or "").strip()
    return JSONResponse(composio_bridge.connect_toolkit(toolkit))


@app.get("/api/composio/setup")
async def composio_setup_route() -> JSONResponse:
    return JSONResponse({"ok": True, "steps": composio_bridge.setup_hint(), **composio_bridge.status()})


@app.post("/api/brain/ideas/clear")
async def brain_clear_ideas_route(request: Request) -> JSONResponse:
    """Delete all Second Brain ideas (and their links). Requires confirm=true."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if not body.get("confirm"):
        return JSONResponse(
            {"ok": False, "error": "Pass confirm=true to delete all ideas."},
            status_code=400,
        )
    result = brain_clear_all_ideas(BRAIN_PATH)
    return JSONResponse({"ok": True, **result})


@app.delete("/api/brain/ideas/{idea_id}")
async def brain_delete_idea_route(idea_id: str) -> JSONResponse:
    ok = brain_delete_idea(BRAIN_PATH, idea_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "idea not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": idea_id})


@app.post("/api/brain/links")
async def brain_add_link_route(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        link = brain_add_link(BRAIN_PATH, body if isinstance(body, dict) else {})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "link": link})


@app.delete("/api/brain/links/{link_id}")
async def brain_delete_link_route(link_id: str) -> JSONResponse:
    ok = brain_delete_link(BRAIN_PATH, link_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "link not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": link_id})


@app.get("/api/memory")
async def memory_get() -> JSONResponse:
    """Long-term personal facts Jarvis must never forget (Skills HUD)."""
    return JSONResponse(mem_snapshot(MEMORY_PATH))


@app.get("/api/handwriting/status")
async def handwriting_status_route() -> JSONResponse:
    return JSONResponse(handwriting_status())


@app.post("/api/handwriting/write")
async def handwriting_write_route(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    text = str(body.get("text") or body.get("prompt") or "").strip()
    content = str(body.get("body") or body.get("content") or "").strip() or None
    title = str(body.get("title") or "").strip() or None
    language = str(body.get("language") or "").strip() or None
    medium = str(body.get("medium") or "").strip() or None
    upload = body.get("upload", True)
    if not text and not content:
        return JSONResponse({"ok": False, "error": "text or body required"}, status_code=400)
    result = await asyncio.to_thread(
        write_handwritten_document,
        text or (content or ""),
        body=content,
        title=title,
        language=language,
        medium=medium,
        upload=bool(upload),
    )
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@app.post("/api/google/docs/create")
async def google_docs_create_route(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    text = str(body.get("text") or body.get("topic") or "").strip()
    content = str(body.get("body") or body.get("content") or "").strip() or None
    title = str(body.get("title") or "").strip() or None
    if not text and not content:
        return JSONResponse({"ok": False, "error": "text/topic or body required"}, status_code=400)
    result = await asyncio.to_thread(
        create_google_doc_essay,
        text or (content or ""),
        title=title,
        body=content,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.post("/api/google/slides/create")
async def google_slides_create_route(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    text = str(body.get("text") or body.get("topic") or "").strip()
    title = str(body.get("title") or "").strip() or None
    slides = body.get("slides") if isinstance(body.get("slides"), list) else None
    if not text and not slides:
        return JSONResponse({"ok": False, "error": "text/topic or slides required"}, status_code=400)
    result = await asyncio.to_thread(
        create_google_slides,
        text or title or "Presentation",
        title=title,
        slides=slides,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.get("/api/connections")
async def connections_get() -> JSONResponse:
    """Data connectors (API / vault / synced index) — not mere website openers."""
    return JSONResponse(connector_snapshot())


@app.post("/api/connections/connect")
async def connections_connect(request: Request) -> JSONResponse:
    """Link an app's data to Jarvis (OAuth / vault path / sync index)."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    app_id = str(body.get("app") or body.get("app_id") or "").strip().lower()
    vault_path = str(body.get("vault_path") or body.get("path") or "").strip() or None
    if not app_id:
        return JSONResponse({"ok": False, "error": "app is required"}, status_code=400)
    result = await asyncio.to_thread(link_connector, app_id, vault_path=vault_path)
    status = 200 if result.get("ok") or result.get("needs_setup") or result.get("needs_path") else 400
    return JSONResponse(result, status_code=status)


@app.post("/api/connections/disconnect")
async def connections_disconnect(request: Request) -> JSONResponse:
    body = await request.json()
    app_id = str((body or {}).get("app") or (body or {}).get("app_id") or "").strip().lower()
    if not app_id:
        return JSONResponse({"ok": False, "error": "app is required"}, status_code=400)
    result = await asyncio.to_thread(unlink_connector, app_id)
    return JSONResponse(result)


@app.post("/api/connections/sync")
async def connections_sync(request: Request) -> JSONResponse:
    """Refresh a synced/vault index, or health-check an API connector."""
    body = await request.json()
    app_id = str((body or {}).get("app") or (body or {}).get("app_id") or "").strip().lower()
    if not app_id:
        return JSONResponse({"ok": False, "error": "app is required"}, status_code=400)
    result = await asyncio.to_thread(sync_connector, app_id)
    return JSONResponse(result)


@app.post("/api/connections/query")
async def connections_query(request: Request) -> JSONResponse:
    """Query a linked connector's data WITHOUT opening the app/website."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    app_id = str(body.get("app") or body.get("app_id") or "").strip().lower()
    query = str(body.get("query") or body.get("q") or "").strip()
    if not app_id:
        return JSONResponse({"ok": False, "error": "app is required"}, status_code=400)
    result = await asyncio.to_thread(query_connector, app_id, query, brain_path=BRAIN_PATH)
    return JSONResponse(result)


@app.post("/api/connections/read")
async def connections_read(request: Request) -> JSONResponse:
    """Read one item from a linked connector (mail id, note path, drive file id)."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    app_id = str(body.get("app") or body.get("app_id") or "").strip().lower()
    item_id = str(body.get("id") or body.get("item_id") or body.get("path") or "").strip()
    if not app_id or not item_id:
        return JSONResponse({"ok": False, "error": "app and id are required"}, status_code=400)
    result = await asyncio.to_thread(read_connector_item, app_id, item_id, brain_path=BRAIN_PATH)
    return JSONResponse(result)


def _open_pc_app_id(app_id: str) -> dict:
    """Open an allowlisted PC app via the Hermes pc_apps plugin."""
    import sys

    roots = [
        Path.home() / "AppData" / "Local" / "hermes" / "plugins",
        ROOT.parent / "hermes-plugin",
    ]
    last_err: Exception | None = None
    for root in roots:
        if not (root / "pc_apps").is_dir():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from pc_apps import tools  # type: ignore

            raw = tools.open_pc_app({"app": app_id})
            try:
                return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception:
                return {"ok": False, "error": str(raw)[:300]}
        except Exception as exc:
            last_err = exc
            continue
    return {"ok": False, "error": f"Could not open app: {last_err or 'plugin missing'}"}


@app.post("/api/connections/open")
async def connections_open(request: Request) -> JSONResponse:
    """Optional UI open — separate from data linking."""
    body = await request.json()
    app_id = str((body or {}).get("app") or (body or {}).get("app_id") or "").strip().lower()
    # Map connector ids that share open aliases
    open_id = {
        "google_calendar": "google_calendar",
        "google_docs": "google_docs",
        "google_drive": "google_drive",
        "second_brain": None,
        "obsidian": None,
    }.get(app_id, app_id)
    if not open_id:
        return JSONResponse({"ok": False, "error": f"{app_id} is a local data connector — nothing to open in Chrome."}, status_code=400)
    open_result = await asyncio.to_thread(_open_pc_app_id, open_id)
    return JSONResponse({
        "ok": bool(open_result.get("ok")),
        **connector_snapshot(),
        "open_result": open_result,
        "error": None if open_result.get("ok") else (open_result.get("error") or "open failed"),
    })


@app.get("/api/connections/status/{app_id}")
async def connections_status(app_id: str) -> JSONResponse:
    snap = connector_snapshot()
    app = next((a for a in snap.get("apps") or [] if a.get("id") == app_id), None)
    if not app:
        return JSONResponse({"ok": False, "error": "unknown connector"}, status_code=404)
    return JSONResponse({"ok": True, "app": app_id, "connected": app.get("linked"), "meta": app})


# ------------------------------------------------------------------ Dual Brain & Study

@app.get("/api/study/status")
async def study_status() -> JSONResponse:
    res = await asyncio.to_thread(STUDY_ENGINE.status)
    return JSONResponse(res)


@app.post("/api/study/start")
async def study_start() -> JSONResponse:
    res = await asyncio.to_thread(STUDY_ENGINE.start_studying)
    return JSONResponse(res)


@app.post("/api/study/pause")
async def study_pause() -> JSONResponse:
    res = await asyncio.to_thread(STUDY_ENGINE.pause_studying)
    return JSONResponse(res)


@app.post("/api/dual_brain/mode")
async def dual_brain_set_mode(request: Request) -> JSONResponse:
    """Set routing mode: auto | layer2."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = str((body or {}).get("mode") or "auto").strip().lower()
    if mode in ("auto", "layer1", "l1", "local"):
        DUAL_BRAIN.set_force_layer(None)
    elif mode in ("layer2", "l2", "chatgpt", "brain"):
        DUAL_BRAIN.set_force_layer(2)
    else:
        return JSONResponse({"ok": False, "error": "mode must be auto or layer2"}, status_code=400)
    res = await asyncio.to_thread(DUAL_BRAIN.get_stats)
    return JSONResponse({"ok": True, **res})


@app.get("/api/ratings")
async def ratings_lookup(title: str = "", prefer: str = "") -> JSONResponse:
    from movie_ratings import format_ratings_reply, lookup_ratings

    if not (title or "").strip():
        return JSONResponse({"ok": False, "error": "title query param required"}, status_code=400)
    data = await asyncio.to_thread(
        lambda: lookup_ratings(title.strip(), prefer=(prefer or None) or None)
    )
    return JSONResponse({**data, "text": format_ratings_reply(data)})


@app.get("/api/dual_brain/stats")
async def dual_brain_stats() -> JSONResponse:
    res = await asyncio.to_thread(DUAL_BRAIN.get_stats)
    return JSONResponse(res)


@app.post("/api/dual_brain/ask")
async def dual_brain_ask(request: Request) -> JSONResponse:
    body = await request.json()
    text = str((body or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text is required"}, status_code=400)
    res = await asyncio.to_thread(DUAL_BRAIN.route, text)
    return JSONResponse(res)


@app.get("/api/memory/contact")
async def memory_contact(q: str = "") -> JSONResponse:
    """Resolve a contact from memory by name, WhatsApp name, or phone."""
    fact = mem_find_contact(MEMORY_PATH, q)
    if not fact:
        return JSONResponse({"ok": False, "error": f"No contact matched '{q}'"}, status_code=404)
    digits = mem_phone_digits(fact.get("phone"))
    email = (fact.get("email") or "").strip() or None
    return JSONResponse({
        "ok": True,
        "contact": fact,
        "phone_digits": digits,
        "has_phone": bool(digits),
        "email": email,
        "has_email": bool(email),
        "whatsapp_name": fact.get("whatsapp_name") or fact.get("value") or fact.get("title"),
    })


@app.post("/api/memory")
async def memory_add(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        fact = mem_upsert_fact(MEMORY_PATH, body if isinstance(body, dict) else {})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "fact": fact})


@app.delete("/api/memory/{fact_id}")
async def memory_delete(fact_id: str) -> JSONResponse:
    ok = mem_delete_fact(MEMORY_PATH, fact_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "fact not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": fact_id})


WS_CLIENTS: set = set()
PENDING_REPLIES: list[dict] = []  # replies finished after their client disconnected

# "/pc <task>" typed on the phone runs inside the Jarvis window on the PC.
WS_DEVICE: dict = {}  # raw websocket -> "pc" | "phone", most recent hello last
PC_TASKS: dict[str, asyncio.Future] = {}
PC_TASK_RE = re.compile(r"(?is)^\s*/pc(?:\s+|$)(.*)$")
PC_HUD_LAUNCHER = Path(os.environ.get("JARVIS_ROOT") or r"D:\jarvis_kokoro") / "open-jarvis-hud.ps1"
# Cloudflare quick tunnels drop requests after ~100s, so the phone gets an early reply.
PC_TASK_PHONE_WAIT = 85.0
_pc_launch_at = 0.0


def _pc_clients() -> list:
    return [c for c, dev in list(WS_DEVICE.items()) if dev == "pc" and c in WS_CLIENTS]


def _pc_hud_url() -> str:
    """Same pick order as open-jarvis-hud.ps1: changing Cloudflare link, then ngrok, then LAN."""
    token = hud_token() or "jarvis-9f2517"
    changing, stable, lan = [], [], []
    try:
        lines = (PC_HUD_LAUNCHER.parent / "CURRENT_HUD_URL.txt").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        u = line.strip()
        if not u.startswith("http"):
            continue
        if "trycloudflare.com" in u:
            changing.append(u)
        elif "ngrok" in u:
            stable.append(u)
        elif u.startswith(("https://192.168.", "https://10.")):
            lan.append(u)
    pick = changing or stable or lan or ["https://127.0.0.1/hud/"]
    url = next((u for u in pick if "token=" in u), pick[0])
    if "token=" not in url:
        url += ("&" if "?" in url else "?") + f"token={token}"
    return url


def _launch_pc_hud() -> None:
    import subprocess
    import urllib.parse
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:9222/json/new?" + urllib.parse.quote(_pc_hud_url(), safe=":/?&="),
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        return
    except Exception as exc:
        print(f"pc_task: debug Chrome unavailable ({exc}); using launcher script", flush=True)
    launcher = PC_HUD_LAUNCHER
    if not launcher.exists():
        launcher = Path(__file__).resolve().parent / "scripts" / "open-jarvis-hud.ps1"
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
         "-File", str(launcher)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


async def _ensure_pc_window(timeout: float = 30.0) -> list:
    global _pc_launch_at
    clients = _pc_clients()
    if clients:
        return clients
    if time.time() - _pc_launch_at > 45:
        _pc_launch_at = time.time()
        try:
            await asyncio.to_thread(_launch_pc_hud)
            print("pc_task: no PC Jarvis window connected — opening one", flush=True)
        except Exception as exc:
            print(f"pc_task: could not launch PC HUD: {exc}", flush=True)
            return []
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        clients = _pc_clients()
        if clients:
            await asyncio.sleep(1.5)  # let the freshly opened HUD finish loading
            return _pc_clients()
    return []


async def _send_to_phones(payload: dict) -> int:
    sent = 0
    for client, dev in list(WS_DEVICE.items()):
        if dev != "phone" or client not in WS_CLIENTS:
            continue
        try:
            await client.send_json(payload)
            sent += 1
        except Exception:
            WS_CLIENTS.discard(client)
    return sent


async def _relay_pc_result(task_id: str, fut: asyncio.Future, task: str) -> None:
    try:
        out = await asyncio.wait_for(fut, timeout=900)
        text = "Done on your PC:\n" + (out.get("text") or "")
    except asyncio.TimeoutError:
        text = "Your PC task is taking a long time — check the Jarvis window on the PC."
    except Exception as exc:
        text = f"Your PC task failed: {exc}"
    finally:
        PC_TASKS.pop(task_id, None)
    payload = {"type": "pc_task_result", "task_id": task_id, "task": task, "text": text}
    if not await _send_to_phones(payload):
        PENDING_REPLIES.append({"ts": time.time(), "text": text, "transcript": f"/pc {task}"})


async def _run_pc_task(task: str, conversation: str) -> dict:
    if not task:
        return {"text": "Type /pc followed by what you want me to do on the PC — for example: /pc open YouTube.",
                "tools": [], "run_id": "pc_task"}
    started = time.time()
    clients = await _ensure_pc_window()
    target = clients[-1] if clients else None
    if target is None:
        out = await _run_hud_chat(task, conversation)
        out["text"] = ("I couldn't open the Jarvis window on your PC, so I did it on the PC directly.\n"
                       + (out.get("text") or ""))
        return out
    task_id = uuid.uuid4().hex[:12]
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    PC_TASKS[task_id] = fut
    try:
        await target.send_json({"type": "pc_task", "task_id": task_id, "text": task})
    except Exception:
        PC_TASKS.pop(task_id, None)
        WS_CLIENTS.discard(target)
        out = await _run_hud_chat(task, conversation)
        out["text"] = "The PC Jarvis window didn't answer, so I did it on the PC directly.\n" + (out.get("text") or "")
        return out
    wait = max(5.0, PC_TASK_PHONE_WAIT - (time.time() - started))
    done, _ = await asyncio.wait({fut}, timeout=wait)
    if done:
        PC_TASKS.pop(task_id, None)
        try:
            out = dict(fut.result())
        except Exception as exc:
            return {"text": f"Your PC task failed: {exc}", "tools": [], "run_id": task_id}
        out["text"] = "Done on your PC:\n" + (out.get("text") or "")
        return out
    asyncio.create_task(_relay_pc_result(task_id, fut, task))
    return {"text": "Working on it in the Jarvis window on your PC — I'll send the result here when it's done.",
            "tools": [{"name": "pc_task", "preview": "running"}], "run_id": task_id}


def _finish_pc_task(task_id: str, out: dict | None = None, error: str | None = None) -> None:
    fut = PC_TASKS.get(task_id)
    if not fut or fut.done():
        return
    if error is not None:
        fut.set_exception(RuntimeError(error))
    else:
        fut.set_result(out or {})


async def _broadcast_json(payload: dict) -> int:
    sent = 0
    for client in list(WS_CLIENTS):
        try:
            await client.send_json(payload)
            sent += 1
        except Exception:
            WS_CLIENTS.discard(client)
    return sent


@app.post("/api/pc_approval")
async def pc_approval_create(request: Request) -> JSONResponse:
    """Create a phone HUD approval card (e.g. ChatGPT send)."""
    body = await request.json()
    approval_id = (body.get("approval_id") or "").strip()
    if not approval_id:
        return JSONResponse({"ok": False, "error": "approval_id required"}, status_code=400)
    item = pc_approvals.create_approval(
        approval_id,
        kind=str(body.get("kind") or "pc_action"),
        title=str(body.get("title") or "APPROVAL REQUIRED"),
        preview=str(body.get("preview") or ""),
        description=str(body.get("description") or ""),
    )
    # Also mirror decision channel into LOCALAPPDATA pending for chatgpt plugin
    try:
        pending_path = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "jarvis_chatgpt_pending.json"
        if pending_path.is_file():
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            if isinstance(pending, dict) and pending.get("approval_id") == approval_id:
                pending.setdefault("decision", None)
                pending_path.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    except Exception:
        pass
    n = await _broadcast_json({
        "type": "pc_approval_request",
        "approval_id": approval_id,
        "kind": item.get("kind"),
        "title": item.get("title"),
        "preview": item.get("preview"),
        "description": item.get("description"),
    })
    # Also nudge phone Notification API / toast while HUD is open
    await _broadcast_json({
        "type": "hud_notify",
        "title": item.get("title") or "Approval needed",
        "body": (item.get("preview") or item.get("description") or "")[:240],
        "level": "approval",
    })
    return JSONResponse({"ok": True, "approval": item, "sent_to_hud": n})


@app.post("/api/notify")
async def hud_notify(request: Request) -> JSONResponse:
    """Push a toast / OS notification to open HUD clients (phone or PC)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = str((body or {}).get("title") or "Jarvis").strip()[:120]
    text = str((body or {}).get("body") or (body or {}).get("message") or "").strip()[:500]
    level = str((body or {}).get("level") or "info").strip().lower()[:32]
    if not text and not title:
        return JSONResponse({"ok": False, "error": "title or body required"}, status_code=400)
    n = await _broadcast_json({
        "type": "hud_notify",
        "title": title or "Jarvis",
        "body": text,
        "level": level or "info",
    })
    return JSONResponse({"ok": True, "sent_to_hud": n})


@app.post("/api/listen_do")
async def listen_do_route(request: Request) -> JSONResponse:
    """Silent eager-action endpoint for Listen & Do mode (partial or final transcript)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = str((body or {}).get("text") or (body or {}).get("transcript") or "").strip()
    session_id = str((body or {}).get("session_id") or "").strip() or None
    final = bool((body or {}).get("final"))
    reset = bool((body or {}).get("reset"))
    if reset:
        sess = listen_do_reset(session_id)
        return JSONResponse({"ok": True, "session_id": sess.id, "reset": True, "actions": []})
    if not text:
        return JSONResponse({"ok": True, "actions": [], "session_id": session_id or ""})
    result = await asyncio.to_thread(process_listen_do, text, session_id=session_id, final=final)
    # Surface tool activity on HUD without speaking
    for act in result.get("actions") or []:
        try:
            await _broadcast_json({
                "type": "agent_status",
                "state": "tool_use",
                "tool": act.get("action") or "listen_do",
                "preview": (act.get("message") or act.get("app") or "")[:80],
            })
        except Exception:
            pass
        try:
            await _broadcast_json({
                "type": "hud_notify",
                "title": "Doing",
                "body": str(act.get("message") or act.get("action") or "")[:200],
                "level": "success" if act.get("ok") else "info",
            })
        except Exception:
            pass
    return JSONResponse(result)


@app.get("/api/pc_approval/{approval_id}")
async def pc_approval_get(approval_id: str) -> JSONResponse:
    item = pc_approvals.get_approval(approval_id)
    if not item:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, **item})


@app.post("/api/pc_approval/{approval_id}")
async def pc_approval_decide(approval_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    decision = body.get("decision") or body.get("choice") or ""
    item = pc_approvals.decide(approval_id, str(decision))
    if not item:
        return JSONResponse({"ok": False, "error": "not found or invalid decision"}, status_code=404)
    # Mirror onto chatgpt / whatsapp pending files so plugin polls see it immediately
    try:
        for name in ("jarvis_chatgpt_pending.json", "jarvis_whatsapp_pending.json"):
            pending_path = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / name
            if pending_path.is_file():
                pending = json.loads(pending_path.read_text(encoding="utf-8"))
                if isinstance(pending, dict) and pending.get("approval_id") == approval_id:
                    pending["decision"] = item.get("decision")
                    pending_path.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    except Exception:
        pass
    await _broadcast_json({
        "type": "pc_approval_resolved",
        "approval_id": approval_id,
        "decision": item.get("decision"),
    })
    return JSONResponse({"ok": True, "approval": item})


@app.post("/api/pc_approval/{approval_id}/consume")
async def pc_approval_consume(approval_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    item = pc_approvals.consume(approval_id, str(body.get("status") or "consumed"))
    if not item:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "approval": item})


@app.post("/api/phone/open")
async def phone_open(request: Request) -> JSONResponse:
    """Queue + broadcast an open-app command to connected phone HUDs."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    app = str(body.get("app") or "").strip().lower()
    if not app:
        return JSONResponse({"ok": False, "error": "app is required"}, status_code=400)
    url = body.get("url")
    scheme = body.get("scheme")
    if url is not None:
        url = str(url).strip() or None
    if scheme is not None:
        scheme = str(scheme).strip() or None
    if not url and not scheme:
        return JSONResponse({"ok": False, "error": "url or scheme required"}, status_code=400)
    cmd = phone_commands.create_command(
        app=app,
        label=str(body.get("label") or app),
        url=url,
        scheme=scheme,
    )
    n = await _broadcast_json({
        "type": "phone_open",
        "command_id": cmd["command_id"],
        "app": cmd["app"],
        "label": cmd["label"],
        "url": cmd.get("url"),
        "scheme": cmd.get("scheme"),
    })
    return JSONResponse({
        "ok": True,
        "command_id": cmd["command_id"],
        "command": cmd,
        "sent_to_hud": n,
    })


@app.get("/api/phone/pending")
async def phone_pending() -> JSONResponse:
    return JSONResponse({"ok": True, "pending": phone_commands.list_pending()})


@app.post("/api/phone/ack/{command_id}")
async def phone_ack(command_id: str) -> JSONResponse:
    item = phone_commands.ack(command_id)
    if not item:
        return JSONResponse({"ok": False, "error": "command not found"}, status_code=404)
    return JSONResponse({"ok": True, "command": item})


@app.post("/api/summon")
async def summon(request: Request) -> JSONResponse:
    """Broadcast a holographic media panel to all connected HUD clients.

    Body: {"media": "video"|"iframe"|"image", "src": "...", "title": "...",
           "position": "center"|"left"|"right"}  or  {"action": "dismiss"}
    Hermes can call this (curl with X-Jarvis-Token) to display media on the HUD.
    """
    body = await request.json()
    if body.get("action") == "dismiss":
        payload = {"type": "dismiss_panels"}
    else:
        payload = {"type": "summon_panel",
                   "media": body.get("media") or body.get("type") or "iframe",
                   "src": body.get("src", ""),
                   "title": body.get("title", "INCOMING FEED"),
                   "position": body.get("position", "center")}
    sent = 0
    for client in list(WS_CLIENTS):
        try:
            await client.send_json(payload)
            sent += 1
        except Exception:
            WS_CLIENTS.discard(client)
    return JSONResponse({"sent_to": sent})


_WORKER_CACHE: dict = {"ts": 0.0, "data": [], "refreshing": False}


@app.get("/api/machines")
async def machines() -> JSONResponse:
    """Local (Mac) stats + configured remote workers.

    Worker polls can take seconds when a worker is offline, so they run in a
    background refresh; the endpoint always answers instantly from cache.
    """
    result: list[dict] = []
    mac: dict = {"name": "MAC MINI · HERMES", "online": True}
    if psutil:
        mac.update({
            "cpu": psutil.cpu_percent(interval=0.1),
            "mem": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage(str(ROOT)).percent,
        })
    result.append(mac)

    def poll_worker(w: dict) -> dict:
        info = {"name": w.get("name", w.get("host", "worker")), "online": False}
        url = w.get("stats_url")
        if url:
            try:
                r = requests.get(url, timeout=2)
                if r.ok:
                    info.update(r.json())
                    info["online"] = True
                    return info
            except Exception:
                pass
        import socket
        try:
            with socket.create_connection((w.get("host"), int(w.get("ping_port", 445))), timeout=1.5):
                info["online"] = True
                info["note"] = "online (no stats agent)"
        except Exception:
            pass
        return info

    workers = CFG.get("machines") or []
    now = time.time()
    if workers and now - _WORKER_CACHE["ts"] > 10 and not _WORKER_CACHE["refreshing"]:
        _WORKER_CACHE["refreshing"] = True

        async def refresh() -> None:
            try:
                data = [await asyncio.to_thread(poll_worker, w) for w in workers]
                _WORKER_CACHE.update(ts=time.time(), data=data)
            finally:
                _WORKER_CACHE["refreshing"] = False

        asyncio.get_running_loop().create_task(refresh())
    result.extend(_WORKER_CACHE["data"] or
                  [{"name": w.get("name", "worker"), "online": False, "note": "checking..."} for w in workers])
    return JSONResponse({"machines": result})


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/hud/")


class _HudStatic(StaticFiles):
    """Browsers must revalidate the HUD so an open window never runs stale code after an update."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path in ("", ".") or path.endswith((".html", ".js", ".json")):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


if HUD_DIR.exists():
    app.mount("/hud", _HudStatic(directory=str(HUD_DIR), html=True), name="hud")


# ----------------------------------------------- Hermes dashboard TLS proxy
# The HUD (https) cannot iframe the plain-http dashboard (mixed content), so
# this second app reverse-proxies the entire dashboard over TLS, stripping
# frame-blocking headers. Served on its own port (see server.dashboard_proxy).

dash_app = FastAPI(title="Hermes Dashboard TLS Proxy")
_STRIP_HEADERS = {"x-frame-options", "content-security-policy", "content-length",
                  "transfer-encoding", "connection", "content-encoding"}


@dash_app.middleware("http")
async def dash_auth_middleware(request: Request, call_next):
    if not _request_authed(request):
        return Response(status_code=401, content="jarvis auth required")
    return await call_next(request)


def _dash_target() -> str:
    return ((CFG.get("server") or {}).get("dashboard_proxy") or {}).get(
        "target", "http://127.0.0.1:9119").rstrip("/")


@dash_app.websocket("/{path:path}")
async def dash_ws_proxy(ws: WebSocket, path: str) -> None:
    import websockets as wslib
    token = hud_token()
    if token and ws.cookies.get("jarvis_token") != token:
        await ws.close(code=4401)
        return
    await ws.accept()
    target = _dash_target().replace("http://", "ws://").replace("https://", "wss://")
    uri = f"{target}/{path}" + (f"?{ws.url.query}" if ws.url.query else "")
    try:
        async with wslib.connect(uri, max_size=None) as backend:
            async def client_to_backend() -> None:
                while True:
                    m = await ws.receive()
                    if m.get("text") is not None:
                        await backend.send(m["text"])
                    elif m.get("bytes") is not None:
                        await backend.send(m["bytes"])
                    elif m.get("type") == "websocket.disconnect":
                        break

            async def backend_to_client() -> None:
                async for m in backend:
                    if isinstance(m, str):
                        await ws.send_text(m)
                    else:
                        await ws.send_bytes(m)

            done, pending_t = await asyncio.wait(
                [asyncio.create_task(client_to_backend()),
                 asyncio.create_task(backend_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending_t:
                t.cancel()
    except Exception:
        pass


@dash_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def dash_http_proxy(path: str, request: Request) -> Response:
    body = await request.body()
    fwd_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "accept-encoding", "connection")}

    def do_request() -> requests.Response:
        return requests.request(
            request.method, f"{_dash_target()}/{path}",
            params=dict(request.query_params), headers=fwd_headers,
            data=body if body else None, timeout=60, allow_redirects=False,
        )

    resp = await asyncio.to_thread(do_request)
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _STRIP_HEADERS}
    return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)


# ------------------------------------------------------------------ WebSocket


@dataclass
class ConnState:
    audio_chunks: list = field(default_factory=list)
    recording: bool = False
    timing: TurnTiming | None = None
    turn_task: asyncio.Task | None = None
    current_run_id: str | None = None
    conversation: str = "jarvis-main"
    spoken_sentences: list = field(default_factory=list)
    interrupt_note: str | None = None
    partial_task: asyncio.Task | None = None
    last_partial_bytes: int = 0
    cancel_requested: bool = False
    turn_gen: int = 0
    listen_do: bool = False
    listen_do_session: str | None = None
    auto_turn: bool = False  # started by HUD voice-activity detection, not a button tap


class _TolerantWS:
    """WebSocket wrapper whose sends become no-ops once the client is gone,
    so a turn (PC actions, reminders) can finish after a phone drops the link."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self.closed = False

    def __getattr__(self, name: str):
        return getattr(self._ws, name)

    async def _send(self, method: str, data) -> None:
        if self.closed:
            return
        try:
            await getattr(self._ws, method)(data)
        except Exception:
            self.closed = True

    async def send_json(self, data) -> None:
        await self._send("send_json", data)

    async def send_bytes(self, data) -> None:
        await self._send("send_bytes", data)

    async def send_text(self, data) -> None:
        await self._send("send_text", data)


async def _run_turn(ws: WebSocket, pipeline: VoicePipelineServer, conn: ConnState) -> None:
    timing = conn.timing
    assert timing is not None
    audio = b"".join(conn.audio_chunks)
    conn.audio_chunks = []
    STUDY_ENGINE.notify_busy()
    try:
        await _run_turn_inner(ws, pipeline, conn, timing, audio)
    finally:
        STUDY_ENGINE.notify_idle()
        reply = (timing.response_text or "").strip()
        if getattr(ws, "closed", False) and reply and not conn.listen_do:
            # Phone locked / switched apps mid-turn — deliver the answer when it reconnects.
            PENDING_REPLIES.append({"text": reply, "transcript": timing.transcript or "", "ts": time.time()})
            del PENDING_REPLIES[:-5]
            try:
                await _broadcast_json({"type": "hud_notify", "title": "Jarvis", "body": reply[:240], "level": "success"})
            except Exception:
                pass


async def _run_turn_inner(
    ws: WebSocket,
    pipeline: VoicePipelineServer,
    conn: ConnState,
    timing: TurnTiming,
    audio: bytes,
) -> None:
    try:
        # Too-short Engage taps → clarify without hitting Whisper ("No audio data…")
        if not audio or len(audio) < 3200:  # < ~0.1s
            timing.transcript = ""
            timing.errors.append("audio too short")
            if conn.listen_do or conn.auto_turn:
                timing.response_text = ""
                timing.total_done_monotonic = time.perf_counter()
                await ws.send_json({"type": "done", "turn_id": timing.turn_id, "timing": timing.summary(), "listen_do": True})
                return
            reply = "I didn't catch that — hold ENGAGE a bit longer and speak, then stop."
            timing.response_text = reply
            await ws.send_json({"type": "transcript", "text": "", "clarity": "unclear", "reason": "too_short_audio"})
            await ws.send_json({"type": "reply", "text": reply})
            await ws.send_json({"type": "agent_status", "state": "speaking"})
            clean = pipeline._clean_for_tts(reply)
            if clean:
                conn.spoken_sentences.append(clean)
                await pipeline._send_tts_sentence(ws, clean, timing, conn, conn.turn_gen)
            timing.total_done_monotonic = time.perf_counter()
            await ws.send_json({"type": "done", "turn_id": timing.turn_id, "timing": timing.summary()})
            return

        raw = await pipeline.transcribe(audio, timing)
        clarity = assess_transcript(
            raw,
            audio_bytes=len(audio),
            sample_rate=int(pipeline.cfg["stt"].get("sample_rate", 16000)),
            pcm=audio,
        )
        transcript = clarity.cleaned
        timing.transcript = transcript
        await ws.send_json({
            "type": "transcript",
            "text": transcript or (raw or "").strip(),
            "clarity": clarity.status,
            "reason": clarity.reason,
        })
        if not clarity.proceed:
            # Noise-triggered hands-free turns must stay silent: a spoken "didn't catch that"
            # is picked up by the phone mic and starts another bogus turn.
            if conn.listen_do or (conn.auto_turn and clarity.reason in (
                "near_silent", "empty_or_punct", "no_words", "likely_hallucination",
                "youtube_hallucination", "youtube_hallucination_ar", "too_short_audio",
            )):
                timing.response_text = ""
                timing.total_done_monotonic = time.perf_counter()
                await ws.send_json({"type": "done", "turn_id": timing.turn_id, "timing": timing.summary(), "listen_do": True})
                return
            reply = clarify_message(clarity)
            timing.response_text = reply
            await ws.send_json({"type": "reply", "text": reply})
            await ws.send_json({"type": "agent_status", "state": "speaking"})
            clean = pipeline._clean_for_tts(reply)
            if clean:
                conn.spoken_sentences.append(clean)
                await pipeline._send_tts_sentence(ws, clean, timing, conn, conn.turn_gen)
            timing.total_done_monotonic = time.perf_counter()
            await ws.send_json({"type": "done", "turn_id": timing.turn_id, "timing": timing.summary()})
            return

        # Listen & Do: silent final pass (eager partials already ran via /api/listen_do)
        if conn.listen_do and transcript:
            result = await asyncio.to_thread(
                process_listen_do,
                transcript,
                session_id=conn.listen_do_session,
                final=True,
            )
            conn.listen_do_session = result.get("session_id") or conn.listen_do_session
            for act in result.get("actions") or []:
                try:
                    await ws.send_json({
                        "type": "agent_status",
                        "state": "tool_use",
                        "tool": act.get("action") or "listen_do",
                        "preview": (act.get("message") or "")[:80],
                    })
                except Exception:
                    pass
            note = ""
            if result.get("corrected"):
                note = result["corrected"]
            if result.get("actions"):
                bits = [a.get("message") for a in result["actions"] if a.get("message")]
                note = " · ".join(bits) if bits else note
            if note:
                await ws.send_json({"type": "status", "message": f"Did: {note[:200]}"})
            timing.response_text = note
            timing.total_done_monotonic = time.perf_counter()
            await ws.send_json({
                "type": "done",
                "turn_id": timing.turn_id,
                "timing": timing.summary(),
                "listen_do": True,
                "stop_listen": bool(result.get("stop_listen")),
                "actions": result.get("actions") or [],
            })
            return

        skip_routes = clarity.status == "uncertain"
        routed = None
        tr = translate_command(transcript)
        route_text = normalize_command(tr.translated or transcript) or tr.translated or transcript
        hermes_payload = None  # set when escalating to Layer 2 with cleaned text
        if transcript:
            STUDY_ENGINE.note_interest(route_text)
        if tr.changed:
            await ws.send_json({
                "type": "translated",
                "from": tr.original,
                "to": route_text,
                "kind": tr.kind,
            })
        if not skip_routes:
            try:
                saved = await asyncio.to_thread(auto_save_from_text, MEMORY_PATH, route_text, BRAIN_PATH)
                if saved:
                    await ws.send_json({
                        "type": "memory_saved",
                        "facts": saved,
                        "count": len(saved),
                    })
                    await _broadcast_json({
                        "type": "memory_saved",
                        "facts": saved,
                        "count": len(saved),
                    })
                    if any(f.get("brain_idea_id") for f in saved):
                        await _broadcast_json({"type": "brain_updated"})
            except Exception as exc:
                print(f"auto_memory voice: {exc}", flush=True)

            routed = try_handle_clock(route_text) or _layer_switch_route(route_text)
            if not routed:
                try:
                    routed = await asyncio.to_thread(
                        try_resolve_pending, route_text, CALENDAR_PATH, BRAIN_PATH, MEMORY_PATH
                    )
                except Exception as exc:
                    print(f"pending followup voice: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(
                        try_start_followup, route_text, CALENDAR_PATH, MEMORY_PATH, BRAIN_PATH
                    )
                except Exception as exc:
                    print(f"start followup voice: {exc}", flush=True)
                    routed = None
            if routed and routed.get("run_id") == "school_life_done":
                try:
                    await ws.send_json({"type": "calendar_updated", "count": routed.get("count") or 0})
                    await _broadcast_json({"type": "calendar_updated", "count": routed.get("count") or 0})
                    await _broadcast_json({"type": "brain_updated"})
                except Exception:
                    pass
            if not routed and wants_handwriting_write(route_text):
                try:
                    if re.search(r"(?is)\b(?:google\s+)?docs?\b", route_text):
                        routed = await asyncio.to_thread(open_docs_and_type, route_text)
                    else:
                        routed = await asyncio.to_thread(write_handwritten_document, route_text, upload=False)
                except Exception as exc:
                    print(f"handwriting write voice: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    ack = docs_pending_ack(route_text)
                    if ack:
                        await ws.send_json({"type": "reply", "text": ack, "partial": True})
                        await ws.send_json({"type": "agent_status", "state": "speaking"})
                        clean = pipeline._clean_for_tts(ack)
                        if clean:
                            await pipeline._send_tts_sentence(ws, clean, timing, conn, conn.turn_gen)
                        await ws.send_json({"type": "agent_status", "state": "tool_use", "tool": "google_workspace", "preview": ack[:60]})
                    routed = await asyncio.to_thread(try_handle_docs_chrome, route_text)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f"docs chrome voice: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_google_workspace, route_text)
                except Exception as exc:
                    print(f"google workspace voice: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    cre = await asyncio.to_thread(
                        try_handle_classroom, route_text, simple=want_simple()
                    )
                    if cre and cre.get("brain_followup"):
                        hermes_payload = str(cre["brain_followup"])
                        routed = None
                    elif cre:
                        routed = cre
                except Exception as exc:
                    print(f"classroom voice route: {exc}", flush=True)
                    routed = None
            if not routed and not hermes_payload:
                try:
                    site = await asyncio.to_thread(try_handle_site_browse, route_text)
                    if site and site.get("brain_followup"):
                        hermes_payload = str(site["brain_followup"])
                        # Speak a short status before Layer 2 answers from the pages.
                        if site.get("speak"):
                            await ws.send_json({"type": "reply", "text": site.get("text") or site["speak"]})
                            await ws.send_json({"type": "agent_status", "state": "speaking"})
                            clean = pipeline._clean_for_tts(str(site["speak"]))
                            if clean:
                                conn.spoken_sentences.append(clean)
                                await pipeline._send_tts_sentence(ws, clean, timing, conn, conn.turn_gen)
                        routed = None
                    elif site:
                        routed = site
                except Exception as exc:
                    print(f"site browse voice route: {exc}", flush=True)
            if not routed and not hermes_payload:
                try:
                    routed = await asyncio.to_thread(try_handle_movie_rating, route_text)
                except Exception as exc:
                    print(f"movie rating voice route: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_youtube, route_text)
                except Exception as exc:
                    print(f"youtube voice route: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_movies, route_text)
                except Exception as exc:
                    print(f"movies voice route: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_maps, route_text)
                except Exception as exc:
                    print(f"maps voice route: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_call, route_text)
                except Exception as exc:
                    print(f"call voice route: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_whatsapp, route_text)
                except Exception as exc:
                    print(f"whatsapp voice route: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_email, route_text)
                except Exception as exc:
                    print(f"email voice route: {exc}", flush=True)
                    routed = None
            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_open, route_text)
                except Exception as exc:
                    print(f"open voice route: {exc}", flush=True)
                    routed = None

            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_briefing, route_text, CALENDAR_PATH, BRAIN_PATH)
                except Exception as exc:
                    print(f"briefing voice route: {exc}", flush=True)
                    routed = None

            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_calendar, route_text, CALENDAR_PATH)
                    if routed:
                        try:
                            await ws.send_json({"type": "calendar_updated", "count": routed.get("count") or 1})
                            await _broadcast_json({"type": "calendar_updated", "count": routed.get("count") or 1})
                        except Exception:
                            pass
                        if routed.get("brain_idea"):
                            try:
                                await _broadcast_json({"type": "brain_updated", "idea": routed.get("brain_idea")})
                            except Exception:
                                pass
                        if routed.get("push_phone") and routed.get("event"):
                            async def _bg_push_v(ev=routed["event"]):
                                try:
                                    await asyncio.to_thread(cal_push_phone, CALENDAR_PATH, ev)
                                except Exception as exc:
                                    print(f"calendar push bg voice: {exc}", flush=True)
                            asyncio.create_task(_bg_push_v())
                except Exception as exc:
                    print(f"calendar voice route: {exc}", flush=True)
                    routed = None

            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_schedule, route_text, CALENDAR_PATH)
                except Exception as exc:
                    print(f"schedule voice route: {exc}", flush=True)
                    routed = None

            if not routed:
                try:
                    routed = await asyncio.to_thread(try_handle_brain_idea, route_text, BRAIN_PATH)
                except Exception as exc:
                    print(f"brain idea voice route: {exc}", flush=True)
                    routed = None

            if not routed and not hermes_payload:
                try:
                    db_cfg = CFG.get("dual_brain") or {}
                    skip_l1 = bool(db_cfg.get("voice_skip_layer1", False))
                    l1_timeout = float(db_cfg.get("voice_layer1_timeout") or 8.0)
                    l1_res = await asyncio.to_thread(
                        DUAL_BRAIN.route,
                        route_text,
                        layer1_timeout=l1_timeout,
                        skip_layer1=skip_l1,
                    )
                    if l1_res.get("can_answer"):
                        routed = {
                            "text": l1_res.get("text") or "",
                            "tools": [{
                                "name": "dual_brain_router" if l1_res.get("source") == "router" else "layer1_local_mind",
                                "preview": (
                                    f"mode={l1_res.get('force_layer') or 'auto'}"
                                    if l1_res.get("source") == "router"
                                    else f"Llama 3.2 ({l1_res.get('latency_ms')}ms)"
                                ),
                            }],
                            "run_id": "l1_local",
                        }
                    else:
                        cleaned = (l1_res.get("cleaned_text") or "").strip()
                        if cleaned:
                            route_text = cleaned
                        # Layer 2 payload (prefer cleaned question)
                        q = cleaned or route_text
                        hermes_payload = hermes_email_hint(
                            hermes_arabic_hint(q) if tr.changed else (clarity.brain_text if not cleaned else q)
                        )
                        if l1_res.get("reason") and l1_res.get("reason") != "voice_fast_path":
                            await ws.send_json({
                                "type": "status",
                                "message": f"Escalating to Layer 2 ({l1_res.get('reason')})",
                            })
                except Exception as exc:
                    print(f"dual_brain voice route: {exc}", flush=True)

        if routed:
            for t in routed.get("tools") or []:
                timing.tools_used.append(t.get("name") or "tool")
                await ws.send_json({
                    "type": "agent_status",
                    "state": "tool_use",
                    "tool": t.get("name"),
                    "preview": t.get("preview", ""),
                })
            reply = (routed.get("text") or "Done.").strip()
            timing.response_text = reply
            # Show the full reply immediately — don't wait for TTS.
            await ws.send_json({"type": "reply", "text": reply})
            speak = (routed.get("speak") or "").strip() or pipeline._short_speak(reply)
            await ws.send_json({"type": "agent_status", "state": "speaking"})
            clean = pipeline._clean_for_tts(speak)
            if clean:
                conn.spoken_sentences.append(clean)
                await pipeline._send_tts_sentence(ws, clean, timing, conn, conn.turn_gen)
            timing.total_done_monotonic = time.perf_counter()
            await ws.send_json({"type": "done", "turn_id": timing.turn_id, "timing": timing.summary()})
            return

        brain_text = hermes_payload or clarity.brain_text or transcript
        if not hermes_payload and tr.changed:
            brain_text = hermes_arabic_hint(transcript)
        if conn.interrupt_note:
            transcript_sent = (
                "[note: your previous spoken reply was cut off by the user after you said: "
                f'"{conn.interrupt_note}"]\n'
                f"{brain_text}"
            )
            conn.interrupt_note = None
        else:
            transcript_sent = brain_text
        conn.spoken_sentences = []
        await pipeline.stream_response_audio(ws, transcript_sent, timing, conn)
        timing.total_done_monotonic = time.perf_counter()
        await ws.send_json({"type": "done", "turn_id": timing.turn_id, "timing": timing.summary()})
        return
    except asyncio.CancelledError:
        timing.errors.append("turn cancelled (barge-in or stop)")
        raise
    except Exception as exc:
        timing.errors.append(f"{type(exc).__name__}: {exc}")
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
        # Always close the turn — wake client / Always-on hang forever without done
        try:
            timing.total_done_monotonic = time.perf_counter()
            await ws.send_json({"type": "done", "turn_id": timing.turn_id, "timing": timing.summary()})
        except Exception:
            pass
    finally:
        timing.total_done_monotonic = timing.total_done_monotonic or time.perf_counter()
        pipeline.log_turn(timing)
        conn.timing = None
        conn.current_run_id = None


async def _cancel_active_turn(ws: WebSocket, pipeline: VoicePipelineServer, conn: ConnState,
                              stop_remote: bool = True) -> None:
    conn.cancel_requested = True
    conn.turn_gen += 1  # invalidate in-flight TTS/LLM of the previous turn
    run_id = conn.current_run_id  # capture BEFORE cancel: turn cleanup clears it
    turn_was_active = conn.turn_task is not None and not conn.turn_task.done()
    old_task = conn.turn_task
    if turn_was_active and old_task is not None:
        if conn.spoken_sentences:
            conn.interrupt_note = conn.spoken_sentences[-1]
        old_task.cancel()
        try:
            # Don't block forever on TTS/Kokoro — stop must feel instant
            await asyncio.wait_for(asyncio.shield(old_task), timeout=1.2)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        if conn.turn_task is old_task:
            conn.turn_task = None
    if stop_remote and run_id and turn_was_active:
        conn.current_run_id = None
        try:
            res = await asyncio.to_thread(pipeline.hermes.stop_run, run_id)
            msg = "Run halted." if res["status_code"] in (200, 202, 404) else f"Stop returned {res['status_code']}."
            await ws.send_json({"type": "status", "message": msg})
        except Exception as exc:
            await ws.send_json({"type": "status", "message": f"Stop failed: {exc}"})


def _maybe_schedule_partial(ws: WebSocket, pipeline: VoicePipelineServer, conn: ConnState) -> None:
    stt_cfg = CFG.get("stt") or {}
    if not stt_cfg.get("partials", True) or not conn.recording:
        return
    if conn.partial_task and not conn.partial_task.done():
        return
    buf = b"".join(conn.audio_chunks)
    sample_rate = int(stt_cfg.get("sample_rate", 16000))
    bytes_per_sec = sample_rate * 2
    # Listen & Do: snappier partials so mid-phrase opens fire sooner
    interval = float(stt_cfg.get("partial_interval", 1.2))
    if conn.listen_do:
        interval = min(interval, 0.55)
    min_new = int(bytes_per_sec * interval)
    max_partial_bytes = int(bytes_per_sec * float(stt_cfg.get("partial_window_seconds", 28)))
    if len(buf) < bytes_per_sec * (0.25 if conn.listen_do else 0.35):
        return
    if len(buf) - conn.last_partial_bytes < min_new:
        return
    conn.last_partial_bytes = len(buf)
    window = buf[-max_partial_bytes:] if len(buf) > max_partial_bytes else buf

    async def run() -> None:
        try:
            text = await pipeline._local_transcribe_samples_partial(window)
            if text and conn.recording:
                if len(buf) > max_partial_bytes:
                    text = "… " + text
                await ws.send_json({"type": "partial_transcript", "text": text})
        except Exception:
            pass

    conn.partial_task = asyncio.create_task(run())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    if not _ws_allowed(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    WS_CLIENTS.add(ws)
    raw_ws = ws
    ws = _TolerantWS(raw_ws)
    pipeline = get_pipeline()
    conn = ConnState(conversation=(CFG.get("hermes") or {}).get("conversation", "jarvis-main"))
    await ws.send_json({"type": "status", "message": "Hermes voice server connected."})
    fresh = [r for r in PENDING_REPLIES if time.time() - r["ts"] < 900]
    PENDING_REPLIES.clear()
    for r in fresh:
        await ws.send_json({"type": "missed_reply", "text": r["text"], "transcript": r["transcript"]})
    try:
        while True:
            message = await ws.receive()
            if "text" in message and message["text"] is not None:
                event = json.loads(message["text"])
                etype = event.get("type")
                if etype == "start":
                    await _cancel_active_turn(ws, pipeline, conn)  # barge-in
                    conn.cancel_requested = False
                    if event.get("conversation"):
                        conn.conversation = str(event["conversation"])
                    conn.listen_do = bool(event.get("listen_do") or event.get("silent"))
                    conn.auto_turn = bool(event.get("auto"))
                    if event.get("listen_do_session"):
                        conn.listen_do_session = str(event.get("listen_do_session"))
                    conn.audio_chunks = []
                    conn.last_partial_bytes = 0
                    conn.recording = True
                    conn.timing = TurnTiming(turn_id=pipeline.next_turn_id())
                    conn.timing.audio_start_monotonic = time.perf_counter()
                    conn.timing.stt_model = CFG["stt"]["model"]
                    mode = "listen-do" if conn.listen_do else "record"
                    await ws.send_json({"type": "status", "message": f"Turn {conn.timing.turn_id} {mode} started."})
                elif etype == "stop":
                    if conn.timing is None:
                        await ws.send_json({"type": "error", "message": "Received stop before start."})
                        continue
                    conn.recording = False
                    conn.cancel_requested = False
                    conn.timing.end_of_speech_monotonic = time.perf_counter()
                    # Cancel in-flight partial STT so final transcription can take the lock immediately
                    if conn.partial_task and not conn.partial_task.done():
                        conn.partial_task.cancel()
                        try:
                            await conn.partial_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        conn.partial_task = None
                    conn.turn_task = asyncio.create_task(_run_turn(ws, pipeline, conn))
                    await ws.send_json({"type": "agent_status", "state": "thinking"})
                elif etype == "ping":
                    await ws.send_json({"type": "pong"})
                elif etype == "hello":
                    WS_DEVICE.pop(raw_ws, None)
                    WS_DEVICE[raw_ws] = "phone" if str(event.get("device")).lower() == "phone" else "pc"
                    print(f"HUD connected: {WS_DEVICE[raw_ws]}", flush=True)
                elif etype == "stop_run":
                    await _cancel_active_turn(ws, pipeline, conn)
                    # Always ack stop so HUD clears even if no turn was active
                    try:
                        await ws.send_json({"type": "agent_status", "state": "stopped"})
                    except Exception:
                        pass
                elif etype == "approval_decision":
                    run_id = event.get("run_id") or conn.current_run_id
                    if not run_id:
                        await ws.send_json({"type": "error", "message": "No run for approval."})
                        continue
                    decision = event.get("decision", "deny")
                    body = {
                        "decision": decision,
                        "approved": decision == "allow",
                        "approval_id": event.get("approval_id"),
                    }
                    res = await asyncio.to_thread(pipeline.hermes.post_approval, run_id, body)
                    await ws.send_json({"type": "status", "message": f"Approval sent ({res['status_code']})."})
                elif etype == "pc_approval_decision":
                    approval_id = (event.get("approval_id") or "").strip()
                    decision = event.get("decision", "deny")
                    if not approval_id:
                        await ws.send_json({"type": "error", "message": "approval_id required"})
                        continue
                    item = await asyncio.to_thread(pc_approvals.decide, approval_id, str(decision))
                    if not item:
                        await ws.send_json({"type": "error", "message": "PC approval not found."})
                        continue
                    # Mirror onto chatgpt pending file
                    try:
                        pending_path = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "jarvis_chatgpt_pending.json"
                        if pending_path.is_file():
                            pending = json.loads(pending_path.read_text(encoding="utf-8"))
                            if isinstance(pending, dict) and pending.get("approval_id") == approval_id:
                                pending["decision"] = item.get("decision")
                                pending_path.write_text(json.dumps(pending, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    await _broadcast_json({
                        "type": "pc_approval_resolved",
                        "approval_id": approval_id,
                        "decision": item.get("decision"),
                    })
                    await ws.send_json({
                        "type": "status",
                        "message": f"PC approval {item.get('decision')}.",
                    })
                else:
                    await ws.send_json({"type": "error", "message": f"Unknown event type: {etype}"})
            elif "bytes" in message and message["bytes"] is not None:
                if conn.recording:
                    conn.audio_chunks.append(message["bytes"])
                    _maybe_schedule_partial(ws, pipeline, conn)
    except WebSocketDisconnect:
        ws.closed = True  # let an in-flight turn finish; its reply is queued for reconnect
        print("Client disconnected", flush=True)
    except RuntimeError as exc:
        # Starlette raises if receive() is called after disconnect
        if "disconnect" in str(exc).lower():
            ws.closed = True
            print("Client disconnected (late receive)", flush=True)
        else:
            raise
    finally:
        ws.closed = True
        WS_CLIENTS.discard(raw_ws)
        WS_DEVICE.pop(raw_ws, None)


def main() -> int:
    server = CFG["server"]
    host = server.get("host", "0.0.0.0")
    port = int(server.get("port", 8765))
    tls_ports = server.get("tls_ports") or ([server["tls_port"]] if server.get("tls_port") else [])
    cert = server.get("tls_cert")
    key = server.get("tls_key")
    print(f"Starting Hermes voice server on ws://{host}:{port}/ws", flush=True)
    if tls_ports and cert and key and (ROOT / cert).exists() and (ROOT / key).exists():
        servers = [uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))]
        for tp in tls_ports:
            print(f"HUD available on https://{host}:{tp}/hud/", flush=True)
            servers.append(uvicorn.Server(uvicorn.Config(
                app, host=host, port=int(tp), log_level="info",
                ssl_certfile=str(ROOT / cert), ssl_keyfile=str(ROOT / key),
            )))

        dp = server.get("dashboard_proxy") or {}
        if dp.get("port"):
            print(f"Dashboard proxy on https://{host}:{dp['port']}/", flush=True)
            servers.append(uvicorn.Server(uvicorn.Config(
                dash_app, host=host, port=int(dp["port"]), log_level="warning",
                ssl_certfile=str(ROOT / cert), ssl_keyfile=str(ROOT / key),
            )))

        async def serve_all() -> None:
            await asyncio.gather(*[s.serve() for s in servers])

        asyncio.run(serve_all())
    else:
        uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
