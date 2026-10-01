"""Smoke-test Jarvis speak paths (no mic required — synthetic PCM).

Covers:
  1) /api/chat/voice  (HUD MIC voice note)
  2) WebSocket engage start/stop with audio (ENGAGE / ALWAYS ON / HEY path)
  3) /api/chat typed
  4) Kokoro + Hermes health
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
import time
import urllib.error
import urllib.request

try:
    import websockets
except ImportError:
    websockets = None

TOKEN = "jarvis-9f2517"
BASE = "http://127.0.0.1:8765"
WS = "ws://127.0.0.1:8765/ws"
SR = 16000


def _pcm_tone(seconds: float = 1.2, freq: float = 440.0, amp: int = 6000) -> bytes:
    n = int(SR * seconds)
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / SR)))
        for i in range(n)
    )


def _pcm_silence(seconds: float = 0.5) -> bytes:
    return b"\x00\x00" * int(SR * seconds)


def http_json(method: str, path: str, body: bytes | None = None, timeout: float = 60) -> tuple[int, dict | str]:
    headers = {"X-Jarvis-Token": TOKEN}
    if body is not None and method == "POST" and path.endswith("/voice"):
        headers["Content-Type"] = "application/octet-stream"
    elif body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    detail = (detail or "").replace("\u2192", "->").encode("ascii", "replace").decode("ascii")
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def test_health() -> bool:
    ok = True
    try:
        with urllib.request.urlopen("http://127.0.0.1:8642/health", timeout=5) as r:
            ok &= check("Hermes health", r.status == 200, r.read()[:80].decode())
    except Exception as e:
        ok &= check("Hermes health", False, str(e))
    try:
        with urllib.request.urlopen("http://127.0.0.1:8880/health", timeout=5) as r:
            ok &= check("Kokoro TTS", r.status == 200, r.read()[:80].decode())
    except Exception as e:
        ok &= check("Kokoro TTS", False, str(e))
    code, data = http_json("GET", "/api/study/status", timeout=10)
    slim = isinstance(data, dict) and "subjects" in data
    huge = False
    if slim:
        # subjects should be slim (no nested concepts lists of long strings)
        for sub in (data.get("subjects") or {}).values():
            topics = sub.get("topics") or []
            if topics and isinstance(topics[0], dict) and "concepts" in topics[0]:
                huge = True
                break
    ok &= check("Study status slim", code == 200 and slim and not huge, f"cards={data.get('total_cards') if isinstance(data, dict) else '?'}")
    return ok


def test_chat() -> bool:
    body = json.dumps({"input": "Reply with exactly one word: pong", "conversation": "jarvis-voice-test"}).encode()
    code, data = http_json("POST", "/api/chat", body, timeout=90)
    text = (data.get("text") if isinstance(data, dict) else "") or ""
    return check("Typed chat", code == 200 and bool(text), text[:80])


def test_voice_note_silence() -> bool:
    code, data = http_json("POST", "/api/chat/voice?conversation=jarvis-voice-test", _pcm_silence(0.6), timeout=45)
    unclear = isinstance(data, dict) and (data.get("unclear") or data.get("clarity") == "unclear")
    return check("Voice note silence → clarify", code == 200 and unclear, str(data.get("reason") if isinstance(data, dict) else data)[:60])


def test_voice_note_too_short() -> bool:
    code, data = http_json("POST", "/api/chat/voice?conversation=jarvis-voice-test", b"\x00\x00" * 100, timeout=20)
    ok_shape = isinstance(data, dict) and (data.get("unclear") or data.get("error"))
    return check("Voice note too short", code == 200 and ok_shape, str(data)[:80])


async def test_engage_ws() -> bool:
    if websockets is None:
        return check("Engage WebSocket", False, "websockets not installed")
    pcm = _pcm_tone(1.5)
    chunk = 2560  # 80ms
    events: list[dict] = []
    try:
        async with websockets.connect(WS, open_timeout=8, close_timeout=5, max_size=8_000_000) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            await ws.send(json.dumps({
                "type": "start", "sample_rate": 16000, "format": "pcm_s16le",
                "channels": 1, "conversation": "jarvis-voice-test",
            }))
            for i in range(0, len(pcm), chunk):
                await ws.send(pcm[i : i + chunk])
                await asyncio.sleep(0.01)
            await ws.send(json.dumps({"type": "stop"}))
            deadline = time.time() + 90
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=8)
                except asyncio.TimeoutError:
                    continue  # Hermes/tools can pause between events
                if isinstance(raw, bytes):
                    events.append({"type": "audio_bytes", "n": len(raw)})
                    continue
                msg = json.loads(raw)
                events.append(msg)
                if msg.get("type") in ("done", "error"):
                    break
    except Exception as e:
        return check("Engage WebSocket", False, str(e))

    types = [e.get("type") for e in events if isinstance(e, dict)]
    has_transcript = "transcript" in types
    has_done = "done" in types
    audio_n = sum(1 for e in events if e.get("type") == "audio_bytes")
    # Tone may be unclear — still must complete the turn cleanly
    detail = f"events={types[:12]} audio_chunks={audio_n}"
    return check(
        "Engage WebSocket turn",
        has_transcript and has_done,
        detail,
    )


async def test_engage_empty() -> bool:
    if websockets is None:
        return check("Engage empty audio", False, "websockets not installed")
    events: list[str] = []
    try:
        async with websockets.connect(WS, open_timeout=8, close_timeout=5) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
            await ws.send(json.dumps({
                "type": "start", "sample_rate": 16000, "format": "pcm_s16le",
                "channels": 1, "conversation": "jarvis-voice-test",
            }))
            await asyncio.sleep(0.05)
            await ws.send(json.dumps({"type": "stop"}))
            deadline = time.time() + 45
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                if isinstance(raw, bytes):
                    events.append("audio")
                    continue
                msg = json.loads(raw)
                events.append(msg.get("type") or "")
                if msg.get("type") in ("done", "error"):
                    break
    except Exception as e:
        return check("Engage empty audio", False, str(e))
    return check("Engage empty audio → done", "done" in events, str(events))


def main() -> int:
    print("=== Jarvis speak-path smoke tests ===")
    results = []
    results.append(test_health())
    results.append(test_chat())
    results.append(test_voice_note_too_short())
    results.append(test_voice_note_silence())
    results.append(asyncio.run(test_engage_empty()))
    results.append(asyncio.run(test_engage_ws()))
    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} passed")
    # Kokoro is required for spoken replies but not for transcription paths
    return 0 if results[2] and results[3] and results[4] and results[5] and results[1] else 1


if __name__ == "__main__":
    sys.exit(main())
