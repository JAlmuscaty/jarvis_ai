#!/usr/bin/env python3
"""Minimal local Kokoro TTS OpenAI-compatible server for Jarvis (no Docker)."""
from __future__ import annotations

import io
import struct
from typing import Iterator

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Jarvis Kokoro TTS")
_PIPELINE = None
DEFAULT_VOICE = "af_heart"
SAMPLE_RATE = 24000


def get_pipeline():
    global _PIPELINE
    if _PIPELINE is None:
        from kokoro import KPipeline
        _PIPELINE = KPipeline(lang_code="a")
    return _PIPELINE


class SpeechRequest(BaseModel):
    model: str = "kokoro"
    input: str
    voice: str = DEFAULT_VOICE
    response_format: str = "pcm"
    stream: bool = True
    speed: float = 1.0


def synthesize(text: str, voice: str, speed: float) -> np.ndarray:
    pipe = get_pipeline()
    chunks: list[np.ndarray] = []
    for _, _, audio in pipe(text, voice=voice, speed=speed):
        if audio is None:
            continue
        arr = np.asarray(audio, dtype=np.float32)
        if arr.size:
            chunks.append(arr)
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def float_to_pcm16(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


@app.get("/health")
def health():
    return {"status": "healthy", "engine": "kokoro", "sample_rate": SAMPLE_RATE}


@app.get("/v1/models")
def models():
    return {
        "object": "list",
        "data": [{"id": "kokoro", "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    text = (req.input or "").strip()
    if not text:
        return Response(status_code=400, content=b"empty input")
    voice = req.voice or DEFAULT_VOICE
    audio = synthesize(text, voice, float(req.speed or 1.0))
    fmt = (req.response_format or "pcm").lower()

    if fmt == "pcm":
        body = float_to_pcm16(audio)

        def gen() -> Iterator[bytes]:
            # Sentence-sized chunks for streaming clients
            step = 4096
            for i in range(0, len(body), step):
                yield body[i : i + step]

        return StreamingResponse(gen(), media_type="application/octet-stream")

    if fmt == "mp3":
        # WAV container labeled as mp3 fallback if mp3 encoder missing;
        # boot script prefers mp3 — write wav bytes into .mp3 only if needed.
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="WAV")
        data = buf.getvalue()
        return Response(content=data, media_type="audio/wav")

    # wav default
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav")


if __name__ == "__main__":
    print("Warming Kokoro model...", flush=True)
    get_pipeline()
    print("Listening on http://127.0.0.1:8880", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8880, log_level="info")
