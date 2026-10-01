"""Durable handwriting profiles — sample photos + style metadata.

Stored under JARVIS_DATA_DIR/handwriting/ so samples are never forgotten.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

DATA_ROOT = Path(
    os.environ.get("JARVIS_DATA_DIR")
    or os.environ.get("JARVIS_ROOT")
    or str(Path(__file__).resolve().parent / "data")
)
HW_ROOT = DATA_ROOT / "handwriting"
PROFILES_PATH = HW_ROOT / "profiles.json"
SAMPLES_DIR = HW_ROOT / "samples"
OUTPUT_DIR = HW_ROOT / "output"
FONTS_DIR = HW_ROOT / "fonts"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _empty() -> dict:
    return {"profiles": [], "default_id": None, "updated_at": None}


def ensure_dirs() -> None:
    HW_ROOT.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FONTS_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    ensure_dirs()
    with _LOCK:
        try:
            data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = _empty()
        if not isinstance(data, dict):
            data = _empty()
        data.setdefault("profiles", [])
        data.setdefault("default_id", None)
        return data


def save(data: dict) -> None:
    ensure_dirs()
    with _LOCK:
        data = dict(data)
        data["updated_at"] = _now()
        PROFILES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_profiles() -> list[dict]:
    return list(load().get("profiles") or [])


def get_profile(profile_id: str | None = None) -> dict | None:
    data = load()
    pid = (profile_id or data.get("default_id") or "").strip()
    profiles = data.get("profiles") or []
    if pid:
        for p in profiles:
            if p.get("id") == pid:
                return p
    return profiles[0] if profiles else None


def has_handwriting() -> bool:
    p = get_profile()
    return bool(p and (p.get("samples") or []))


def status() -> dict[str, Any]:
    data = load()
    profiles = data.get("profiles") or []
    default = get_profile()
    return {
        "ok": True,
        "configured": bool(default and default.get("samples")),
        "default_id": data.get("default_id"),
        "profile_count": len(profiles),
        "sample_count": sum(len(p.get("samples") or []) for p in profiles),
        "default": {
            "id": (default or {}).get("id"),
            "name": (default or {}).get("name"),
            "languages": (default or {}).get("languages") or [],
            "mediums": (default or {}).get("mediums") or [],
            "samples": len((default or {}).get("samples") or []),
            "style": (default or {}).get("style") or {},
        } if default else None,
        "message": (
            "Handwriting memorized — I can write pages in your style."
            if default and default.get("samples")
            else "No handwriting saved yet. Send a photo and say: memorize my handwriting."
        ),
    }


def upsert_profile(
    *,
    name: str = "My handwriting",
    languages: list[str] | None = None,
    mediums: list[str] | None = None,
    style: dict | None = None,
    profile_id: str | None = None,
) -> dict:
    data = load()
    profiles = list(data.get("profiles") or [])
    pid = (profile_id or data.get("default_id") or "").strip()
    existing = next((p for p in profiles if p.get("id") == pid), None) if pid else None
    if not existing and profiles:
        existing = profiles[0]
    if existing:
        if languages:
            existing["languages"] = sorted(set((existing.get("languages") or []) + languages))
        if mediums:
            existing["mediums"] = sorted(set((existing.get("mediums") or []) + mediums))
        if style:
            merged = dict(existing.get("style") or {})
            merged.update({k: v for k, v in style.items() if v is not None})
            existing["style"] = merged
        if name:
            existing["name"] = name[:80]
        existing["updated_at"] = _now()
        data["profiles"] = [existing if p.get("id") == existing.get("id") else p for p in profiles]
        data["default_id"] = existing.get("id")
        save(data)
        return existing

    profile = {
        "id": uuid.uuid4().hex[:12],
        "name": (name or "My handwriting")[:80],
        "languages": languages or [],
        "mediums": mediums or [],
        "style": style or {},
        "samples": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    profiles.append(profile)
    data["profiles"] = profiles
    data["default_id"] = profile["id"]
    save(data)
    return profile


def add_sample_bytes(
    image_bytes: bytes,
    *,
    ext: str = ".jpg",
    languages: list[str] | None = None,
    medium: str | None = None,
    style: dict | None = None,
    note: str | None = None,
) -> dict:
    """Persist a handwriting photo forever and attach it to the default profile."""
    ensure_dirs()
    profile = upsert_profile(
        languages=languages,
        mediums=[medium] if medium else None,
        style=style,
    )
    sid = uuid.uuid4().hex[:12]
    ext = ext if ext.startswith(".") else f".{ext}"
    if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    sample_dir = SAMPLES_DIR / profile["id"]
    sample_dir.mkdir(parents=True, exist_ok=True)
    path = sample_dir / f"{sid}{ext.lower()}"
    path.write_bytes(image_bytes)

    sample = {
        "id": sid,
        "path": str(path),
        "relative": f"samples/{profile['id']}/{path.name}",
        "medium": (medium or "unknown")[:40],
        "languages": languages or [],
        "note": (note or "")[:200] or None,
        "created_at": _now(),
    }
    data = load()
    for p in data["profiles"]:
        if p.get("id") == profile["id"]:
            samples = list(p.get("samples") or [])
            samples.append(sample)
            p["samples"] = samples[-40:]  # keep last 40
            if languages:
                p["languages"] = sorted(set((p.get("languages") or []) + languages))
            if medium:
                p["mediums"] = sorted(set((p.get("mediums") or []) + [medium]))
            if style:
                merged = dict(p.get("style") or {})
                merged.update({k: v for k, v in style.items() if v is not None})
                p["style"] = merged
            p["updated_at"] = _now()
            profile = p
            break
    data["default_id"] = profile["id"]
    save(data)
    return {"profile": profile, "sample": sample}


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """Return (bytes, ext) from a data:image/...;base64,... URL."""
    import base64

    m = re.match(r"^data:(image/[\w+.-]+);base64,(.+)$", (data_url or "").strip(), re.I | re.S)
    if not m:
        raise ValueError("Expected a data:image/...;base64 image")
    mime = m.group(1).lower()
    raw = base64.b64decode(m.group(2))
    ext = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, ".jpg")
    return raw, ext


def font_path_for(language: str, medium: str | None = None) -> Path | None:
    ensure_dirs()
    lang = (language or "en").lower()
    # Prefer fonts we shipped under data; fall back to repo-adjacent copies
    candidates: list[str] = []
    if lang.startswith("ar") or lang == "arabic":
        candidates = ["ArefRuqaa-Regular.ttf", "Amiri-Regular.ttf"]
    else:
        candidates = ["PatrickHand-Regular.ttf", "Caveat-Regular.ttf"]
    for name in candidates:
        p = FONTS_DIR / name
        if p.is_file() and p.stat().st_size > 1000:
            # Skip broken variable-font Caveat if PIL can't load — caller handles
            return p
    return None
