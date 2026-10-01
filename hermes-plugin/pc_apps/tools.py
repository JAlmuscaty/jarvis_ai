"""Open allowlisted sites/apps in the CDP-connected Chrome on the PC screen."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import tab_registry

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

CDP_BASE = os.environ.get("BROWSER_CDP_URL", "").strip().rstrip("/")
if not CDP_BASE:
    CDP_BASE = "http://127.0.0.1:9222"
if CDP_BASE.startswith("ws://"):
    CDP_BASE = "http://" + CDP_BASE[len("ws://") :].split("/", 1)[0]
elif CDP_BASE.startswith("wss://"):
    CDP_BASE = "https://" + CDP_BASE[len("wss://") :].split("/", 1)[0]

CHROME_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google"
    / "Chrome"
    / "Application"
    / "chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google"
    / "Chrome"
    / "Application"
    / "chrome.exe",
]
DEBUG_PROFILE = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "chrome-debug"
ENABLE_FLAG = Path(r"D:\jarvis_kokoro\BROWSER_CONTROL_ENABLED")

ALLOWLIST_PATHS = [
    Path(os.environ.get("JARVIS_PC_APPS_ALLOWLIST", "")),
    Path(r"D:\jarvis_kokoro\pc_apps_allowlist.yaml"),
    Path(__file__).resolve().parent / "allowlist.yaml",
]


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
    return {
        "chrome": {"kind": "focus", "label": "Google Chrome"},
        "youtube": {"kind": "url", "url": "https://www.youtube.com/", "label": "YouTube"},
        "whatsapp": {"kind": "url", "url": "https://web.whatsapp.com/", "label": "WhatsApp Web"},
        "vidbox": {"kind": "url", "url": "https://vidbox.cc/", "label": "Vidbox"},
        "movies": {"kind": "url", "url": "https://vidbox.cc/", "label": "Vidbox Movies"},
        "notebooklm": {"kind": "url", "url": "https://notebooklm.google.com/", "label": "Google NotebookLM"},
        "gmail": {"kind": "url", "url": "https://mail.google.com/", "label": "Gmail"},
    }


def _cdp_get(path: str, timeout: float = 3.0) -> tuple[int, str]:
    url = CDP_BASE.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def _cdp_put(path: str, timeout: float = 8.0) -> tuple[int, str]:
    url = CDP_BASE.rstrip("/") + path
    req = urllib.request.Request(url, method="PUT")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def _cdp_alive() -> bool:
    try:
        status, body = _cdp_get("/json/version")
        return status == 200 and "webSocketDebuggerUrl" in body
    except Exception:
        return False


def _find_chrome() -> Path | None:
    for p in CHROME_CANDIDATES:
        if p.is_file():
            return p
    return None


def _start_debug_chrome() -> str | None:
    """Launch Chrome with --remote-debugging-port=9222 on a dedicated profile."""
    chrome = _find_chrome()
    if not chrome:
        return "Google Chrome executable not found."
    DEBUG_PROFILE.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(
            [
                str(chrome),
                "--remote-debugging-port=9222",
                f"--user-data-dir={DEBUG_PROFILE}",
                "--no-first-run",
                "--no-default-browser-check",
                "https://www.google.com/",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return f"Failed to start debug Chrome: {e}"
    return None


def _ensure_cdp(wait_seconds: float = 40.0) -> str | None:
    """Make sure CDP is live; auto-start debug Chrome if needed."""
    if _cdp_alive():
        return None
    err = _start_debug_chrome()
    if err:
        return err
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _cdp_alive():
            try:
                ENABLE_FLAG.parent.mkdir(parents=True, exist_ok=True)
                ENABLE_FLAG.write_text(
                    f"enabled {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8"
                )
            except Exception:
                pass
            return None
        time.sleep(0.5)
    return (
        "Could not start Chrome debug port 9222. Close extra Chrome windows, "
        "run D:\\jarvis_kokoro\\start-chrome-debug.bat, then ask again."
    )


def _focus_chrome_window() -> None:
    if os.name != "nt":
        return
    ps = (
        "$p = Get-Process chrome -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1; "
        "if ($p) { "
        "Add-Type -Name Win -Namespace Native -MemberDefinition '"
        "[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h);"
        "[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int n);"
        "'; "
        "[Native.Win]::ShowWindow($p.MainWindowHandle, 9) | Out-Null; "
        "[Native.Win]::SetForegroundWindow($p.MainWindowHandle) | Out-Null "
        "}"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except Exception:
        pass


def _open_url_in_chrome(url: str, *, source: str = "open_url") -> dict:
    encoded = urllib.parse.quote(url, safe=":/?&=%#")
    last_err = ""
    before_ids = {p.get("id") for p in tab_registry.live_pages() if p.get("id")}

    def _finish(info: dict, note: str | None = None) -> dict:
        out: dict = {"ok": True, "action": "opened_tab", "url": url, "target": info}
        if note:
            out["note"] = note
        tid = tab_registry.register_from_open_result(out, source, before_ids=before_ids)
        if tid:
            out["jarvis_target_id"] = tid
        else:
            out["warn"] = "Tab opened but could not register target id for later close"
        _focus_chrome_window()
        return out

    try:
        status, body = _cdp_put(f"/json/new?{encoded}")
        if status == 200:
            try:
                info = json.loads(body)
            except json.JSONDecodeError:
                info = {"raw": body[:200], "url": url}
            if isinstance(info, dict):
                return _finish(info)
            last_err = "json/new returned non-object"
        else:
            last_err = f"json/new status {status}"
    except Exception as e:
        last_err = str(e)

    try:
        status, body = _cdp_get(f"/json/new?{encoded}")
        if status == 200:
            try:
                info = json.loads(body)
            except json.JSONDecodeError:
                info = {"url": url, "raw": body[:200]}
            if not isinstance(info, dict):
                info = {"url": url}
            return _finish(info, "get_fallback")
    except Exception as e:
        last_err = f"{last_err}; get_fallback: {e}"

    return {
        "ok": False,
        "error": f"Could not open tab via CDP: {last_err}",
    }


def list_pc_apps(args: dict, **kwargs) -> str:
    apps = _load_allowlist()
    items = [
        {
            "id": key,
            "label": (meta or {}).get("label") or key,
            "kind": (meta or {}).get("kind"),
            "url": (meta or {}).get("url"),
        }
        for key, meta in sorted(apps.items())
    ]
    return json.dumps(
        {
            "allowed_apps": items,
            "cdp_alive": _cdp_alive(),
            "note": (
                "Hermes /browser status can say connected from config alone. "
                "Jarvis uses a real Chrome debug window on port 9222 and will "
                "auto-start it when you call open_pc_app."
            ),
            "how_to_add_more": (
                "Edit D:\\jarvis_kokoro\\pc_apps_allowlist.yaml, then restart Hermes gateway."
            ),
        }
    )


def open_pc_app(args: dict, **kwargs) -> str:
    gate = _ensure_cdp()
    if gate:
        return json.dumps({"ok": False, "error": gate})

    app_id = (args.get("app") or "").strip().lower()
    # Fuzzy normalize common phrasings Hermes may pass
    app_id = re.sub(r"[_\-]+", " ", app_id).strip()
    aliases = {
        "google chrome": "chrome",
        "google": "chrome",
        "yt": "youtube",
        "you tube": "youtube",
        "whatsapp web": "whatsapp",
        "wa": "whatsapp",
        "chatgpt": "chatgpt",
        "chat gpt": "chatgpt",
        "chat.gpt": "chatgpt",
        "openai": "chatgpt",
        "google classroom": "classroom",
        "classroom": "classroom",
        "gc": "classroom",
        "movies": "movies",
        "movie": "movies",
        "the movies": "movies",
        "movie site": "movies",
        "movies site": "movies",
        "film": "movies",
        "films": "movies",
        "cinema": "movies",
        "streaming": "movies",
        "vidbox": "vidbox",
        "vid box": "vidbox",
        "vidbox.cc": "vidbox",
        "vidbox.vc": "vidbox",
        "gmail": "gmail",
        "google mail": "gmail",
        "google slides": "google_slides",
        "slides": "google_slides",
        "google docs": "google_docs",
        "google doc": "google_docs",
        "docs": "google_docs",
        "doc": "google_docs",
        "document": "google_docs",
        "blank page": "google_docs",
        "blank doc": "google_docs",
        "a blank page": "google_docs",
        "google sheets": "google_sheets",
        "sheets": "google_sheets",
        "google drive": "google_drive",
        "drive": "google_drive",
        "google calendar": "google_calendar",
        "maps": "maps",
        "google maps": "maps",
        "notebooklm": "notebooklm",
        "notebook lm": "notebooklm",
        "notebook": "notebooklm",
        "google notebook": "notebooklm",
        "google notebooklm": "notebooklm",
    }
    app_id = aliases.get(app_id, app_id)
    # If Hermes stuffed a sentence into app=, detect movies words
    if app_id not in ("movies", "vidbox", "youtube", "chrome", "whatsapp", "classroom", "chatgpt"):
        if re.search(r"\b(movies?|vidbox|films?|cinema)\b", app_id):
            app_id = "movies"
        elif re.search(r"\byou\s*tube\b|\byt\b", app_id):
            app_id = "youtube"

    apps = _load_allowlist()
    if app_id not in apps:
        return json.dumps(
            {
                "ok": False,
                "error": f"'{app_id}' is not allowlisted.",
                "allowed": sorted(apps.keys()),
            }
        )

    meta = apps[app_id] or {}
    kind = (meta.get("kind") or "").lower()

    if kind == "focus" or app_id == "chrome":
        _focus_chrome_window()
        return json.dumps(
            {
                "ok": True,
                "app": app_id,
                "action": "focused_chrome",
                "message": "Chrome is on screen. Use browser tools to type or navigate.",
            }
        )

    if kind == "url":
        url = (meta.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return json.dumps(
                {"ok": False, "error": f"Allowlist entry '{app_id}' has invalid url."}
            )
        result = _open_url_in_chrome(url, source=f"open_pc_app:{app_id}")
        result["app"] = app_id
        result["label"] = meta.get("label") or app_id
        if result.get("ok"):
            if app_id in ("chatgpt", "chat_gpt", "openai"):
                tid = result.get("jarvis_target_id")
                if tid:
                    try:
                        from . import chatgpt_actions as ca
                        ca._set_session(str(tid), url)
                    except Exception:
                        pass
                result["message"] = (
                    f"Opened {result['label']} in a Jarvis-owned tab. "
                    "Use chatgpt_draft to type (never clicks old chats). "
                    "Send only after phone ALLOW via chatgpt_send."
                )
            else:
                result["message"] = (
                    f"Opened {result['label']} on the PC. "
                    "Use browser tools to interact."
                )
        return json.dumps(result)

    return json.dumps(
        {
            "ok": False,
            "error": f"Unsupported allowlist kind '{kind}' for '{app_id}'.",
        }
    )
