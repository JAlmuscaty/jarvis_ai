"""Open allowlisted apps/sites on the user's phone via the Jarvis HUD.

Requires the phone HUD (Safari / Home Screen app) to be open and connected.
iOS cannot be fully remote-controlled in the background from a website — this
pushes an open command to the connected phone client, which then launches the
app URL / universal link.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

JARVIS_BASE = (
    os.environ.get("JARVIS_BASE_URL")
    or os.environ.get("JARVIS_HUD_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")
JARVIS_TOKEN = os.environ.get("JARVIS_HUD_TOKEN") or "jarvis-9f2517"

ALLOWLIST_PATHS = [
    Path(os.environ.get("JARVIS_PHONE_APPS_ALLOWLIST", "")),
    Path(r"D:\jarvis_kokoro\phone_apps_allowlist.yaml"),
    Path(__file__).resolve().parent / "phone_allowlist.yaml",
]

DEFAULT_APPS = {
    "youtube": {
        "label": "YouTube",
        "url": "https://www.youtube.com/",
        "scheme": "youtube://",
    },
    "whatsapp": {
        "label": "WhatsApp",
        "url": "https://wa.me/",
        "scheme": "whatsapp://",
    },
    "chatgpt": {
        "label": "ChatGPT",
        "url": "https://chatgpt.com/",
        "scheme": None,
    },
    "maps": {
        "label": "Apple Maps",
        "url": "https://maps.apple.com/",
        "scheme": "maps://",
    },
    "safari": {
        "label": "Safari",
        "url": "https://www.google.com/",
        "scheme": None,
    },
    "camera": {
        "label": "Camera",
        "url": None,
        "scheme": "camera://",
    },
    "photos": {
        "label": "Photos",
        "url": None,
        "scheme": "photos-redirect://",
    },
    "settings": {
        "label": "Settings",
        "url": None,
        "scheme": "App-Prefs://",
    },
    "messages": {
        "label": "Messages",
        "url": None,
        "scheme": "sms://",
    },
    "phone": {
        "label": "Phone",
        "url": None,
        "scheme": "tel://",
    },
    "music": {
        "label": "Apple Music",
        "url": "https://music.apple.com/",
        "scheme": "music://",
    },
    "instagram": {
        "label": "Instagram",
        "url": "https://www.instagram.com/",
        "scheme": "instagram://",
    },
    "tiktok": {
        "label": "TikTok",
        "url": "https://www.tiktok.com/",
        "scheme": "tiktok://",
    },
    "twitter": {
        "label": "X / Twitter",
        "url": "https://x.com/",
        "scheme": "twitter://",
    },
    "x": {
        "label": "X / Twitter",
        "url": "https://x.com/",
        "scheme": "twitter://",
    },
    "spotify": {
        "label": "Spotify",
        "url": "https://open.spotify.com/",
        "scheme": "spotify://",
    },
    "netflix": {
        "label": "Netflix",
        "url": "https://www.netflix.com/",
        "scheme": "nflx://",
    },
    "gmail": {
        "label": "Gmail",
        "url": "https://mail.google.com/",
        "scheme": "googlegmail://",
    },
    "classroom": {
        "label": "Google Classroom",
        "url": "https://classroom.google.com/",
        "scheme": None,
    },
}


def _load_allowlist() -> dict:
    for p in ALLOWLIST_PATHS:
        if not p or str(p) in ("", "."):
            continue
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            data = yaml.safe_load(text) if yaml else {}
            apps = (data or {}).get("apps") or {}
            if apps:
                return {str(k).lower(): v for k, v in apps.items()}
    return dict(DEFAULT_APPS)


def _jarvis_request(method: str, path: str, body: dict | None = None) -> dict:
    url = JARVIS_BASE + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Jarvis-Token": JARVIS_TOKEN,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code}: {err[:240]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


ALIASES = {
    "yt": "youtube",
    "you tube": "youtube",
    "whatsapp": "whatsapp",
    "wa": "whatsapp",
    "chat gpt": "chatgpt",
    "openai": "chatgpt",
    "apple maps": "maps",
    "google maps": "maps",
    "ig": "instagram",
    "insta": "instagram",
    "x.com": "x",
    "tweet": "twitter",
    "apple music": "music",
    "google classroom": "classroom",
    "gc": "classroom",
}


def list_phone_apps(args: dict, **kwargs) -> str:
    apps = _load_allowlist()
    items = [
        {
            "id": key,
            "label": (meta or {}).get("label") or key,
            "url": (meta or {}).get("url"),
            "scheme": (meta or {}).get("scheme"),
        }
        for key, meta in sorted(apps.items())
    ]
    return json.dumps(
        {
            "allowed_apps": items,
            "note": (
                "Phone apps open only when the Jarvis HUD is open/connected on the phone. "
                "Say 'on my phone' to route here; otherwise use open_pc_app for the PC."
            ),
            "how_to_add_more": (
                "Edit D:\\jarvis_kokoro\\phone_apps_allowlist.yaml, then restart Hermes gateway."
            ),
        }
    )


def open_phone_app(args: dict, **kwargs) -> str:
    app_id = (args.get("app") or "").strip().lower()
    app_id = ALIASES.get(app_id, app_id)
    apps = _load_allowlist()
    if app_id not in apps:
        return json.dumps(
            {
                "ok": False,
                "error": f"'{app_id}' is not allowlisted for phone.",
                "allowed": sorted(apps.keys()),
            }
        )

    meta = apps[app_id] or {}
    url = meta.get("url")
    scheme = meta.get("scheme")
    label = meta.get("label") or app_id
    if not url and not scheme:
        return json.dumps({"ok": False, "error": f"No open target configured for {app_id}"})

    res = _jarvis_request(
        "POST",
        "/api/phone/open",
        {
            "app": app_id,
            "label": label,
            "url": url,
            "scheme": scheme,
        },
    )
    if not res.get("ok"):
        return json.dumps(
            {
                "ok": False,
                "error": res.get("error") or "Jarvis server did not accept phone open",
                "detail": res,
            }
        )

    sent = int(res.get("sent_to_hud") or 0)
    note = (
        f"Sent open {label} to your phone."
        if sent > 0
        else (
            f"Queued open {label} for your phone. "
            "Keep the Jarvis HUD open on your phone (or reopen it) so it can receive the command."
        )
    )
    return json.dumps(
        {
            "ok": True,
            "device": "phone",
            "app": app_id,
            "label": label,
            "url": url,
            "scheme": scheme,
            "command_id": res.get("command_id"),
            "sent_to_hud": sent,
            "note": note,
        }
    )


def _memory_contacts_with_phones() -> list[dict]:
    """Return Skills/Memory facts that have an explicit phone field."""
    from . import memory_api

    res = memory_api._req("GET", "")
    facts = res.get("facts") or []
    out = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        digits = memory_api.digits_only(f.get("phone"))
        if not digits:
            continue
        out.append({
            "id": f.get("id"),
            "title": f.get("title") or f.get("key") or f.get("value"),
            "value": f.get("value"),
            "phone": f.get("phone"),
            "phone_digits": digits,
            "whatsapp_name": f.get("whatsapp_name"),
        })
    return out


def call_contact(args: dict, **kwargs) -> str:
    """Call a Skills/Memory contact — only if they have a saved phone number."""
    from . import memory_api

    contact_q = (
        args.get("contact")
        or args.get("name")
        or args.get("friend")
        or args.get("who")
        or args.get("person")
        or ""
    ).strip()
    if not contact_q:
        callable_ = _memory_contacts_with_phones()
        return json.dumps({
            "ok": False,
            "error": "Say who to call (a name saved in Skills / Memory).",
            "callable_contacts": [
                {"name": c.get("title") or c.get("value"), "phone": c.get("phone")}
                for c in callable_
            ],
        })

    # Resolve from memory — refuse unknown people
    resolved = memory_api.resolve_contact(contact_q)
    if not resolved.get("ok"):
        callable_ = _memory_contacts_with_phones()
        names = [c.get("title") or c.get("value") for c in callable_]
        return json.dumps({
            "ok": False,
            "error": (
                f"No Skills / Memory contact matched '{contact_q}'. "
                "I only call people you saved with a phone number."
            ),
            "callable_contacts": names,
        })

    contact = resolved.get("contact") or {}
    # STRICT: only the explicit phone field counts (not numbers scraped from other text)
    saved_phone = (contact.get("phone") or "").strip()
    digits = memory_api.digits_only(saved_phone)
    display = (
        contact.get("title")
        or contact.get("value")
        or contact.get("whatsapp_name")
        or contact_q
    )

    if not digits:
        return json.dumps({
            "ok": False,
            "error": (
                f"I know {display}, but no phone number is saved for them in Skills / Memory. "
                "Add their number (with country code) there first, then ask me to call again."
            ),
            "contact": display,
            "phone": None,
        })

    # Double-check this number really exists on a memory contact (no free-dial)
    allowed = {c["phone_digits"] for c in _memory_contacts_with_phones()}
    if digits not in allowed:
        return json.dumps({
            "ok": False,
            "error": "That number is not saved in Skills / Memory — I will not dial it.",
        })

    tel = f"tel:+{digits}"
    label = f"Call {display}"
    res = _jarvis_request(
        "POST",
        "/api/phone/open",
        {
            "app": "phone",
            "label": label,
            "url": None,
            "scheme": tel,
        },
    )
    if not res.get("ok"):
        return json.dumps({
            "ok": False,
            "error": res.get("error") or "Could not send call to phone HUD",
            "detail": res,
        })

    sent = int(res.get("sent_to_hud") or 0)
    note = (
        f"Calling {display} on your phone."
        if sent > 0
        else (
            f"Queued a call to {display}. "
            "Keep the Jarvis HUD open on your phone so it can open the Phone app."
        )
    )
    return json.dumps({
        "ok": True,
        "action": "call",
        "contact": display,
        "phone": saved_phone,
        "phone_digits": digits,
        "scheme": tel,
        "command_id": res.get("command_id"),
        "sent_to_hud": sent,
        "note": note,
    })
