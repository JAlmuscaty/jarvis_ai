#!/usr/bin/env python3
"""Windows LAN voice client for the Hermes voice pipeline.

Captures 16 kHz mono PCM, runs openWakeWord locally unless push-to-talk is used,
streams audio to the Jarvis voice server, and plays returned audio.

Wake mode (default): always listens for "hey_jarvis" — no browser tab needed.
After wake, keeps conversing until you say "stop" (detected in transcript).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import queue
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
import websockets

try:
    from openwakeword.model import Model as WakeWordModel
except Exception:
    WakeWordModel = None

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
CHUNK_MS = 80
CHUNK_FRAMES = int(SAMPLE_RATE * CHUNK_MS / 1000)
DEFAULT_SERVER = "ws://127.0.0.1:8765/ws"
DEFAULT_WAKE_WORD = "hey_jarvis"
STOP_RE = re.compile(r"^\s*(?:jarvis\s+)?stop\s*\.?\s*$", re.I)


@dataclass
class TurnState:
    turn_complete: asyncio.Event = field(default_factory=asyncio.Event)
    last_transcript: str = ""


def list_devices() -> None:
    print(sd.query_devices())


def make_beep(sample_rate: int = SAMPLE_RATE, duration: float = 0.18, freq: float = 880.0) -> np.ndarray:
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    wave = 0.20 * np.sin(2 * math.pi * freq * t)
    envelope = np.linspace(0.0, 1.0, min(400, len(wave)))
    wave[: len(envelope)] *= envelope
    wave[-len(envelope) :] *= envelope[::-1]
    return wave.astype(np.float32)


def play_beep(output_device: int | None) -> None:
    try:
        sd.play(make_beep(), samplerate=SAMPLE_RATE, device=output_device, blocking=True)
    except Exception as exc:
        print(f"Warning: could not play wake beep: {exc}")


def chunk_rms(chunk: bytes) -> float:
    if len(chunk) < 2:
        return 0.0
    samples = np.frombuffer(chunk, dtype=np.int16)
    if not samples.size:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))


def audio_callback_factory(audio_q: queue.Queue[bytes]):
    def callback(indata, frames, time_info, status):
        if status:
            print(f"Audio input warning: {status}", file=sys.stderr)
        audio_q.put(bytes(indata))

    return callback


async def playback_worker(
    ws,
    output_device: int | None,
    stop_event: asyncio.Event,
    turn_state: TurnState,
) -> None:
    pcm_buffer = bytearray()
    play_q: queue.Queue[bytes | None] = queue.Queue()

    def _player() -> None:
        while True:
            data = play_q.get()
            if data is None:
                return
            usable = len(data) - (len(data) % 2)
            if not usable:
                continue
            audio = np.frombuffer(data[:usable], dtype=np.int16)
            if not audio.size:
                continue
            peak = int(np.max(np.abs(audio)))
            print(f"[audio] playing {audio.size} samples (~{audio.size / SAMPLE_RATE:.2f}s) peak={peak}")
            sd.play(audio, samplerate=SAMPLE_RATE, device=output_device, blocking=True)

    player_thread = threading.Thread(target=_player, name="audio-out", daemon=True)
    player_thread.start()
    min_chunk = SAMPLE_RATE * 2 // 2  # ~0.5s

    def _play_buffer(data: bytes) -> None:
        if data:
            play_q.put(bytes(data))

    try:
        async for message in ws:
            if isinstance(message, str):
                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    print(f"Server: {message}")
                    continue
                event_type = event.get("type")
                if event_type == "error":
                    print(f"Server error: {event.get('message', 'unknown error')}")
                    # Don't hang wake/PTT if the server errors without a done event
                    pcm_buffer.clear()
                    turn_state.turn_complete.set()
                elif event_type == "status":
                    print(f"Server: {event.get('message', '')}")
                elif event_type == "transcript":
                    text = (event.get("text") or "").strip()
                    turn_state.last_transcript = text
                    print(f"Transcript: {text}")
                elif event_type == "reply":
                    text = (event.get("text") or "").strip()
                    if text:
                        print(f"Jarvis: {text}")
                elif event_type == "done":
                    if pcm_buffer:
                        _play_buffer(bytes(pcm_buffer))
                        pcm_buffer.clear()
                    play_q.put(None)
                    player_thread.join(timeout=120)
                    print("Turn complete.")
                    turn_state.turn_complete.set()
                continue
            pcm_buffer.extend(message)
            # Start speaking as soon as we have half a second of audio.
            while len(pcm_buffer) >= min_chunk:
                chunk = bytes(pcm_buffer[:min_chunk])
                del pcm_buffer[:min_chunk]
                _play_buffer(chunk)
    except websockets.ConnectionClosed:
        if not stop_event.is_set():
            print("Server connection closed.")
    finally:
        if pcm_buffer:
            _play_buffer(bytes(pcm_buffer))
            pcm_buffer.clear()
        play_q.put(None)
        try:
            player_thread.join(timeout=5)
        except Exception:
            pass
        stop_event.set()


def start_stdin_reader(loop: asyncio.AbstractEventLoop, enter_q: "asyncio.Queue") -> threading.Thread:
    def _run() -> None:
        while True:
            line = sys.stdin.readline()
            if line == "":
                loop.call_soon_threadsafe(enter_q.put_nowait, None)
                return
            loop.call_soon_threadsafe(enter_q.put_nowait, line.rstrip("\r\n"))

    thread = threading.Thread(target=_run, name="stdin-reader", daemon=True)
    thread.start()
    return thread


async def record_until_silence(
    ws,
    audio_q: queue.Queue[bytes],
    stop_event: asyncio.Event,
    *,
    max_seconds: float,
    silence_seconds: float,
    speech_threshold: float,
    min_speech_seconds: float,
) -> None:
    """Stream mic audio until silence after speech, or max duration."""
    await ws.send(json.dumps({
        "type": "start",
        "sample_rate": SAMPLE_RATE,
        "format": "pcm_s16le",
        "channels": CHANNELS,
        "conversation": "jarvis-main",
    }))
    start = time.perf_counter()
    speech_started = False
    speech_start = 0.0
    last_loud = 0.0

    while time.perf_counter() - start < max_seconds and not stop_event.is_set():
        try:
            chunk = await asyncio.to_thread(audio_q.get, True, 0.15)
        except queue.Empty:
            continue
        await ws.send(chunk)
        rms = chunk_rms(chunk)
        now = time.perf_counter()
        if rms >= speech_threshold:
            if not speech_started:
                speech_started = True
                speech_start = now
            last_loud = now
        elif speech_started and (now - last_loud) >= silence_seconds:
            if (last_loud - speech_start) >= min_speech_seconds:
                break

    await ws.send(json.dumps({"type": "stop"}))


async def push_to_talk_loop(
    ws,
    audio_q: queue.Queue[bytes],
    stop_event: asyncio.Event,
    turn_state: TurnState,
    enter_q: "asyncio.Queue",
    output_device: int | None,
) -> None:
    print("Push-to-talk mode. Press Enter to start a turn, press Enter again to stop.")
    print("While Hermes is speaking, press Enter to interrupt and take your next turn.")
    print("Type 'q' then Enter (or press Ctrl+C) to quit.")

    auto_start = False
    while not stop_event.is_set():
        if not auto_start:
            print("\nReady. Press Enter to start talking (or 'q' to quit)...")
            command = await enter_q.get()
            if command is None or command.strip().lower() in ("q", "quit", "exit"):
                break
            if stop_event.is_set():
                break
        auto_start = False

        turn_state.turn_complete.clear()
        turn_state.last_transcript = ""
        while True:
            try:
                audio_q.get_nowait()
            except queue.Empty:
                break

        print("Streaming. Press Enter to stop.")
        play_beep(output_device)
        await ws.send(json.dumps({
            "type": "start",
            "sample_rate": SAMPLE_RATE,
            "format": "pcm_s16le",
            "channels": CHANNELS,
            "conversation": "jarvis-main",
        }))

        stop_command = None
        while not stop_event.is_set():
            try:
                stop_command = enter_q.get_nowait()
                break
            except asyncio.QueueEmpty:
                pass
            try:
                chunk = await asyncio.to_thread(audio_q.get, True, 0.2)
            except queue.Empty:
                continue
            await ws.send(chunk)

        await ws.send(json.dumps({"type": "stop"}))
        print("Stopped streaming. Waiting for response (press Enter to interrupt)...")

        if stop_command is not None and stop_command.strip().lower() in ("q", "quit", "exit"):
            break

        complete_task = asyncio.create_task(turn_state.turn_complete.wait())
        interrupt_task = asyncio.create_task(enter_q.get())
        done, _ = await asyncio.wait({complete_task, interrupt_task}, return_when=asyncio.FIRST_COMPLETED)

        if interrupt_task in done:
            sd.stop()
            complete_task.cancel()
            command = interrupt_task.result()
            if command is None or command.strip().lower() in ("q", "quit", "exit"):
                break
            try:
                await asyncio.wait_for(turn_state.turn_complete.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            print("(interrupted) go ahead.")
            auto_start = True
        else:
            interrupt_task.cancel()

    print("Exiting push-to-talk.")


async def wake_word_loop(
    ws,
    audio_q: queue.Queue[bytes],
    stop_event: asyncio.Event,
    turn_state: TurnState,
    output_device: int | None,
    wake_word: str,
    threshold: float,
    max_record_seconds: float,
    silence_seconds: float,
    speech_threshold: float,
    continuous: bool,
) -> None:
    if WakeWordModel is None:
        print("openWakeWord could not be imported. pip install openwakeword")
        stop_event.set()
        return

    print(f"Loading wake word model: {wake_word}")
    model = WakeWordModel(wakeword_models=[wake_word])
    print("Listening for 'Hey Jarvis' — no browser needed. Say 'stop' to end a session. Ctrl+C to quit.")

    in_session = False

    while not stop_event.is_set():
        if not in_session:
            try:
                chunk = await asyncio.to_thread(audio_q.get, True, 0.2)
            except queue.Empty:
                continue
            frame = np.frombuffer(chunk, dtype=np.int16)
            prediction = model.predict(frame)
            score = float(prediction.get(wake_word, 0.0))
            if score < threshold:
                continue
            print(f"Wake word detected ({wake_word}, score {score:.2f}).")
            play_beep(output_device)
            in_session = continuous

        turn_state.turn_complete.clear()
        turn_state.last_transcript = ""
        while True:
            try:
                audio_q.get_nowait()
            except queue.Empty:
                break

        await record_until_silence(
            ws, audio_q, stop_event,
            max_seconds=max_record_seconds,
            silence_seconds=silence_seconds,
            speech_threshold=speech_threshold,
            min_speech_seconds=0.35,
        )
        print("Waiting for Jarvis…")
        await turn_state.turn_complete.wait()

        transcript = turn_state.last_transcript
        if STOP_RE.match(transcript):
            print("Stop command heard — ending session.")
            in_session = False
            continue

        if not continuous or not in_session:
            in_session = False
        else:
            print("Still listening — speak your next question (say 'stop' to end).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jarvis wake-word voice client (Windows)")
    parser.add_argument("--server", default=DEFAULT_SERVER, help=f"WebSocket URL (default {DEFAULT_SERVER})")
    parser.add_argument("--input-device", type=int, default=None)
    parser.add_argument("--output-device", type=int, default=None)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--push-to-talk", action="store_true")
    parser.add_argument("--wake-word", default=DEFAULT_WAKE_WORD)
    parser.add_argument("--wake-threshold", type=float, default=0.55)
    parser.add_argument("--max-record-seconds", type=float, default=30.0)
    parser.add_argument("--silence-seconds", type=float, default=0.85, help="silence after speech to end turn")
    parser.add_argument("--speech-threshold", type=float, default=450.0, help="RMS threshold for speech detection")
    parser.add_argument("--no-continuous", action="store_true", help="single turn per wake word only")
    return parser.parse_args()


async def main_async() -> int:
    args = parse_args()
    if args.list_devices:
        list_devices()
        return 0

    audio_q: queue.Queue[bytes] = queue.Queue(maxsize=400)
    stop_event = asyncio.Event()
    turn_state = TurnState()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

    try:
        input_stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_FRAMES,
            dtype=DTYPE,
            channels=CHANNELS,
            device=args.input_device,
            callback=audio_callback_factory(audio_q),
        )
    except Exception as exc:
        print(f"Could not open microphone: {exc}")
        print("Run: python client.py --list-devices")
        return 2

    continuous = not args.no_continuous

    try:
        async with websockets.connect(args.server, max_size=None, ping_interval=20, ping_timeout=20) as ws:
            print(f"Connected to {args.server}")
            with input_stream:
                player = asyncio.create_task(
                    playback_worker(ws, args.output_device, stop_event, turn_state)
                )
                if args.push_to_talk:
                    enter_q: asyncio.Queue = asyncio.Queue()
                    start_stdin_reader(loop, enter_q)
                    await push_to_talk_loop(
                        ws, audio_q, stop_event, turn_state, enter_q, args.output_device
                    )
                    stop_event.set()
                    player.cancel()
                    try:
                        await player
                    except asyncio.CancelledError:
                        pass
                else:
                    await wake_word_loop(
                        ws, audio_q, stop_event, turn_state, args.output_device,
                        args.wake_word, args.wake_threshold, args.max_record_seconds,
                        args.silence_seconds, args.speech_threshold, continuous,
                    )
                    await player
    except OSError as exc:
        print(f"Could not connect to {args.server}: {exc}")
        print("Make sure Jarvis server.py is running on port 8765.")
        return 3
    except websockets.ConnectionClosed:
        print("Connection closed — Jarvis may have restarted.")
        return 3
    except KeyboardInterrupt:
        print("Exiting.")
        return 0
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
