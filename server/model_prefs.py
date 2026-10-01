"""Persisted ChatGPT / Hermes model preference for the Jarvis HUD picker."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

# Curated openai-codex (ChatGPT OAuth) catalog — GPT-5.6 family is the current Codex brain
AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol (Codex)", "tier": "flagship"},
    {"id": "gpt-5.6-sol-pro", "label": "GPT-5.6 Sol Pro", "tier": "pro"},
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra (Codex)", "tier": "flagship"},
    {"id": "gpt-5.6-terra-pro", "label": "GPT-5.6 Terra Pro", "tier": "pro"},
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna (Codex)", "tier": "flagship"},
    {"id": "gpt-5.6-luna-pro", "label": "GPT-5.6 Luna Pro", "tier": "pro"},
    {"id": "gpt-5.5", "label": "GPT-5.5", "tier": "standard"},
    {"id": "gpt-5.5-pro", "label": "GPT-5.5 Pro", "tier": "pro"},
    {"id": "gpt-5.4", "label": "GPT-5.4", "tier": "standard"},
    {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini", "tier": "fast"},
    {"id": "gpt-5.3-codex", "label": "GPT-5.3 Codex", "tier": "coding"},
    {"id": "gpt-5.3-codex-spark", "label": "GPT-5.3 Spark (Pro)", "tier": "coding"},
]

DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_PROVIDER = "openai-codex"

# Models that should prefer Hermes coding/terminal tools when the user asks to build software
CODING_PREFERRED_MODELS = {
    "gpt-5.6-sol",
    "gpt-5.6-sol-pro",
    "gpt-5.6-terra",
    "gpt-5.6-terra-pro",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
}

_HERMES_CONFIG = Path(os.environ.get("HERMES_HOME", str(Path.home() / "AppData" / "Local" / "hermes"))) / "config.yaml"
_MODEL_ID_RE = re.compile(r"^[\w.\-/:+]+$")


def _prefs_path() -> Path:
    logs = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
    return logs / "model_prefs.json"


def _empty() -> dict[str, Any]:
    return {
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
        "updated_at": None,
    }


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or _prefs_path()
    with _LOCK:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = _empty()
        if not isinstance(data, dict):
            data = _empty()
        data.setdefault("model", DEFAULT_MODEL)
        data.setdefault("provider", DEFAULT_PROVIDER)
        return data


def save(data: dict[str, Any], path: Path | None = None) -> None:
    import time

    p = path or _prefs_path()
    with _LOCK:
        out = dict(data)
        out["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2), encoding="utf-8")


def read_hermes_default() -> str | None:
    """Read model.default from Hermes config.yaml if present."""
    try:
        text = _HERMES_CONFIG.read_text(encoding="utf-8")
    except Exception:
        return None
    m = re.search(r"(?m)^model:\s*\n(?:[ \t]+.+\n)*?[ \t]+default:\s*([^\s#]+)", text)
    if m:
        return m.group(1).strip().strip("\"'")
    m = re.search(r"(?m)^[ \t]*default:\s*([^\s#]+)", text)
    if m:
        return m.group(1).strip().strip("\"'")
    return None


def write_hermes_default(model_id: str, provider: str = DEFAULT_PROVIDER) -> bool:
    """Update model.default (and provider) in Hermes config.yaml."""
    if not _MODEL_ID_RE.match(model_id):
        return False
    try:
        text = _HERMES_CONFIG.read_text(encoding="utf-8")
    except Exception:
        return False

    # Replace model.default under the top-level model: block
    new_text, n = re.subn(
        r"(?m)^(model:\s*\n(?:[ \t]+.+\n)*?[ \t]+default:\s*)([^\s#]+)",
        rf"\g<1>{model_id}",
        text,
        count=1,
    )
    if n == 0:
        # Insert / replace simpler form
        if re.search(r"(?m)^model:\s*$", text) or re.search(r"(?m)^model:\s*\n", text):
            new_text, n = re.subn(
                r"(?m)^(model:\s*\n)",
                rf"\1  default: {model_id}\n",
                text,
                count=1,
            )
        else:
            new_text = f"model:\n  default: {model_id}\n  provider: {provider}\n" + text
            n = 1

    # Keep provider in sync when present
    if provider:
        new_text2, pn = re.subn(
            r"(?m)^(model:\s*\n(?:[ \t]+.+\n)*?[ \t]+provider:\s*)([^\s#]+)",
            rf"\g<1>{provider}",
            new_text,
            count=1,
        )
        if pn:
            new_text = new_text2

    if n == 0:
        return False
    try:
        _HERMES_CONFIG.write_text(new_text, encoding="utf-8")
        return True
    except Exception:
        return False


def get_current() -> dict[str, Any]:
    prefs = load()
    model = str(prefs.get("model") or "").strip() or DEFAULT_MODEL
    # Prefer live Hermes config if prefs file missing/stale first load
    if prefs.get("updated_at") is None:
        hermes_model = read_hermes_default()
        if hermes_model:
            model = hermes_model
            prefs["model"] = model
            save(prefs)
    meta = next((m for m in AVAILABLE_MODELS if m["id"] == model), None)
    label = (meta or {}).get("label") or model
    tier = (meta or {}).get("tier") or ""
    return {
        "ok": True,
        "model": model,
        "provider": prefs.get("provider") or DEFAULT_PROVIDER,
        "label": label,
        "tier": tier,
        "coding_preferred": model in CODING_PREFERRED_MODELS or tier == "coding",
        "models": AVAILABLE_MODELS,
        "updated_at": prefs.get("updated_at"),
    }


def set_model(model_id: str, provider: str | None = None) -> dict[str, Any]:
    model_id = (model_id or "").strip()
    if not model_id or not _MODEL_ID_RE.match(model_id):
        raise ValueError("invalid model id")
    known = {m["id"] for m in AVAILABLE_MODELS}
    if model_id not in known:
        # Allow forward-compat ids that look like gpt-*
        if not model_id.startswith("gpt-"):
            raise ValueError(f"unknown model: {model_id}")

    prov = (provider or DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER
    prefs = load()
    prefs["model"] = model_id
    prefs["provider"] = prov
    save(prefs)
    hermes_ok = write_hermes_default(model_id, prov)
    label = next((m["label"] for m in AVAILABLE_MODELS if m["id"] == model_id), model_id)
    return {
        "ok": True,
        "model": model_id,
        "provider": prov,
        "label": label,
        "hermes_config_updated": hermes_ok,
        "models": AVAILABLE_MODELS,
    }
