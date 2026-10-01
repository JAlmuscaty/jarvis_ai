"""Regression checks for voice-note STT clarity (silence / hallucinations)."""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "server"
sys.path.insert(0, str(ROOT))

from voice_clarity import assess_transcript, pcm_mean_abs  # noqa: E402


def _silence(seconds: float = 0.8, sr: int = 16000) -> bytes:
    return b"\x00\x00" * int(sr * seconds)


def _tone(seconds: float = 1.0, sr: int = 16000, amp: int = 4000) -> bytes:
    n = int(sr * seconds)
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * 440 * i / sr)))
        for i in range(n)
    )


def main() -> None:
    silent = _silence()
    r = assess_transcript("English.", pcm=silent)
    assert r.status == "unclear" and r.reason == "near_silent", r

    r2 = assess_transcript("English.")
    assert r2.status == "unclear" and r2.reason == "likely_hallucination", r2

    r3 = assess_transcript(
        "If you want to know more, please subscribe to our channel.",
        pcm=_tone(),
    )
    assert r3.status == "unclear", r3

    tone = _tone()
    assert pcm_mean_abs(tone) > 500
    r4 = assess_transcript("open youtube please", pcm=tone)
    assert r4.status == "ok" and r4.proceed, r4

    print("voice_clarity regression OK")


if __name__ == "__main__":
    main()
