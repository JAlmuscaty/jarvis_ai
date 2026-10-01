"""Keep Hermes signed in to ChatGPT (Layer 2 + photos) without a terminal.

OpenAI requires a human to approve each new sign-in, so when the token is revoked
Jarvis starts Hermes' device sign-in itself, opens the approval page with the code
filled in, and restarts the Hermes gateway once it is approved.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path(os.environ.get("LOCALAPPDATA", "")) / "hermes")
HERMES_AGENT = HERMES_HOME / "hermes-agent"
HERMES_PY = HERMES_AGENT / "venv" / "Scripts" / "python.exe"
HERMES_EXE = HERMES_AGENT / "bin" / "hermes.exe"
HELPER = Path(__file__).resolve().parent / "scripts" / "chatgpt_login.py"
CDP = "http://127.0.0.1:9222"
CODE_TTL = 14 * 60  # OpenAI device codes expire after 15 minutes
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_lock = threading.Lock()
_state: dict = {"status": "idle", "code": None, "url": None, "error": None, "started": 0.0, "finished": 0.0}
_listeners: list[Callable[[dict], None]] = []

_FILL_JS = r"""
(() => {
  if (!/device/i.test(location.pathname)) return false;
  const code = %s;
  const ins = [...document.querySelectorAll('input')].filter(i =>
    i.offsetParent !== null && !['hidden','checkbox','radio','submit','button','email','password'].includes(i.type));
  if (!ins.length) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  const put = (el, v) => { setter.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true}));
                           el.dispatchEvent(new Event('change', {bubbles: true})); };
  if (ins.length >= 6 && ins.every(i => i.maxLength === 1)) {
    const ch = code.replace(/[^A-Za-z0-9]/g, '').split('');
    ins.forEach((el, k) => put(el, ch[k] || ''));
  } else {
    put(ins[0], code);
  }
  ins[0].focus();
  return true;
})()
"""


def on_event(callback: Callable[[dict], None]) -> None:
    _listeners.append(callback)


def _notify(evt: dict) -> None:
    for cb in list(_listeners):
        try:
            cb(dict(evt))
        except Exception as exc:
            print(f"chatgpt_login listener: {exc}", flush=True)


def auth_ok() -> bool:
    """False only when Hermes uses ChatGPT and every saved ChatGPT credential is dead."""
    try:
        data = json.loads((HERMES_HOME / "auth.json").read_text(encoding="utf-8"))
    except Exception:
        return True
    active = data.get("active_provider")
    if active and active != "openai-codex":
        return True
    pool = (data.get("credential_pool") or {}).get("openai-codex")
    if isinstance(pool, list) and pool:
        return any(
            isinstance(e, dict) and e.get("access_token") and e.get("last_status") != "dead"
            for e in pool
        )
    tokens = ((data.get("providers") or {}).get("openai-codex") or {}).get("tokens") or {}
    return bool(tokens.get("access_token"))


def status() -> dict:
    with _lock:
        return dict(_state)


def start(wait_for_code: float = 0.0) -> dict:
    """Begin a sign-in (or reuse the one in progress); optionally wait for its code."""
    with _lock:
        busy = _state["status"] in ("starting", "waiting") and time.time() - _state["started"] < CODE_TTL
        if not busy:
            _state.update(status="starting", code=None, url=None, error=None, started=time.time())
            threading.Thread(target=_run, daemon=True, name="ChatGPTLogin").start()
    deadline = time.time() + wait_for_code
    while time.time() < deadline and status()["status"] == "starting":
        time.sleep(0.2)
    return status()


def _run() -> None:
    if not HERMES_PY.is_file() or not HELPER.is_file():
        _fail("Hermes isn't installed where I expected, so I can't start the ChatGPT sign-in.")
        return
    try:
        proc = subprocess.Popen(
            [str(HERMES_PY), "-u", str(HELPER)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        _fail(f"Couldn't start the ChatGPT sign-in: {exc}")
        return
    assert proc.stdout is not None
    for line in proc.stdout:
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        kind = evt.get("event")
        if kind == "code":
            code, url = str(evt.get("code") or ""), str(evt.get("url") or "")
            with _lock:
                _state.update(status="waiting", code=code, url=url)
            _copy_to_clipboard(code)
            _open_sign_in(url, code)
            print(f"ChatGPT sign-in waiting for approval (code {code}).", flush=True)
            _notify({"event": "code", "code": code, "url": url})
        elif kind == "done":
            restarted = _restart_gateway()
            with _lock:
                _state.update(status="done", code=None, finished=time.time())
            print(f"ChatGPT sign-in complete; gateway restarted={restarted}.", flush=True)
            _notify({"event": "done", "gateway_restarted": restarted})
        elif kind == "error":
            _fail(str(evt.get("message") or "ChatGPT sign-in failed."))
    proc.wait()
    if status()["status"] in ("starting", "waiting"):
        _fail("The ChatGPT sign-in stopped before it was approved.")


def _fail(message: str) -> None:
    with _lock:
        _state.update(status="error", error=message, code=None, finished=time.time())
    print(f"ChatGPT sign-in: {message}", flush=True)
    _notify({"event": "error", "message": message})


def _copy_to_clipboard(text: str) -> None:
    try:
        subprocess.run(["clip"], input=text.encode("utf-8"), timeout=5, creationflags=_NO_WINDOW)
    except Exception:
        pass


def _open_sign_in(url: str, code: str) -> None:
    """Prefer the debug Chrome (its ChatGPT login is reused and the code can be filled in)."""
    try:
        req = urllib.request.Request(f"{CDP}/json/new?" + urllib.parse.quote(url, safe=":/?&="), method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:
            target = json.loads(r.read())
        ws_url = target.get("webSocketDebuggerUrl")
        if ws_url:
            threading.Thread(target=_autofill, args=(ws_url, code), daemon=True).start()
        return
    except Exception:
        pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _autofill(ws_url: str, code: str) -> None:
    try:
        import websocket
    except ImportError:
        return
    expr = _FILL_JS % json.dumps(code)
    deadline = time.time() + 45
    while time.time() < deadline:
        time.sleep(1.5)
        try:
            ws = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
            try:
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "returnByValue": True}}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == 1:
                        break
            finally:
                ws.close()
        except Exception:
            continue
        if ((msg.get("result") or {}).get("result") or {}).get("value") is True:
            return


def _restart_gateway() -> bool:
    exe = str(HERMES_EXE) if HERMES_EXE.is_file() else "hermes"
    try:
        r = subprocess.run([exe, "gateway", "restart"], capture_output=True, timeout=180, creationflags=_NO_WINDOW)
        return r.returncode == 0
    except Exception as exc:
        print(f"gateway restart after sign-in failed: {exc}", flush=True)
        return False
