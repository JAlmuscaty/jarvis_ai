#!/usr/bin/env python3
"""Jarvis GPU STT server — run on any machine with an NVIDIA GPU.

Gives the voice pipeline big-model transcription (~0.2s for a sentence on a
modern GPU) while the host machine keeps a small local model as fallback.

Setup (Windows or Linux, NVIDIA driver installed):
    python -m venv .venv
    .venv/Scripts/pip install faster-whisper fastapi uvicorn nvidia-cublas-cu12 nvidia-cudnn-cu12
    set JARVIS_STT_TOKEN=<same value as JARVIS_HUD_TOKEN on the server>
    .venv/Scripts/python stt_server.py

Then point the voice server's `stt.remote.url` at http://this-machine:8768/stt

API:
    POST /stt    body: raw int16 16 kHz mono PCM, header X-Jarvis-Token
                 -> {"text": "..."}
    GET  /health -> {"status":"ok", ...}
"""
import os
import pathlib
import sys
import time

# Make the pip-installed NVIDIA cuBLAS/cuDNN DLLs loadable for ctranslate2.
# NOTE: use sys.prefix — site.getsitepackages() misses the venv on Windows.
_nv = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in ("cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"):
    p = _nv / sub
    if p.exists():
        os.add_dll_directory(str(p))
        os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")

import numpy as np
import uvicorn
from fastapi import FastAPI, Request, Response
from faster_whisper import WhisperModel

MODEL_NAME = os.environ.get("JARVIS_STT_MODEL", "medium")
# auto | en | ar — auto detects English or Arabic (Kuwaiti dialect speech)
STT_LANGUAGE = os.environ.get("JARVIS_STT_LANGUAGE", "auto").strip().lower()
TOKEN = os.environ.get("JARVIS_STT_TOKEN", "")
PORT = int(os.environ.get("JARVIS_STT_PORT", "8768"))
# RTX 20-series: prefer int8 (float16 sometimes fails in worker processes)
COMPUTE = os.environ.get("JARVIS_STT_COMPUTE", "int8").strip() or "int8"
DEVICE = os.environ.get("JARVIS_STT_DEVICE", "cuda").strip() or "cuda"
BEAM = int(os.environ.get("JARVIS_STT_BEAM", "5") or "5")

print(f"Loading {MODEL_NAME} on {DEVICE}/{COMPUTE} (language={STT_LANGUAGE})...", flush=True)
t0 = time.time()
try:
    model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE)
except Exception as exc:
    print(f"GPU STT failed ({exc}); falling back to CPU int8", flush=True)
    DEVICE, COMPUTE = "cpu", "int8"
    model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE)
print(f"Model ready in {time.time()-t0:.1f}s ({DEVICE}/{COMPUTE})", flush=True)

app = FastAPI(title="Jarvis GPU STT")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME, "device": DEVICE, "compute_type": COMPUTE}


@app.post("/stt")
async def stt(request: Request):
    if TOKEN and request.headers.get("x-jarvis-token") != TOKEN:
        return Response(status_code=401, content="auth required")
    body = await request.body()
    if len(body) < 3200:  # <0.1s of audio
        return {"text": ""}
    audio = np.frombuffer(body[: len(body) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    t0 = time.time()
    try:
        lang = None if STT_LANGUAGE in ("", "auto", "none") else STT_LANGUAGE
        segments, _info = model.transcribe(
            audio,
            language=lang,
            beam_size=BEAM,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            initial_prompt=(
                "Transcribe the user's speech fully and verbatim in English or Kuwaiti Arabic. "
                "Keep every word; do not shorten. Mixed Arabic-English is normal."
            ),
        )
        text = " ".join(s.text.strip() for s in segments).strip()
    except Exception as exc:  # silence/garbage audio -> empty transcript, not a 500
        print(f"transcribe error -> empty: {exc}", flush=True)
        text = ""
    print(f"{len(audio)/16000:.1f}s audio -> {time.time()-t0:.2f}s : {text[:80]}", flush=True)
    return {"text": text}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
