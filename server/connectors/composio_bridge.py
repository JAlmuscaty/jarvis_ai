"""Composio bridge — connect 1000+ apps when COMPOSIO_API_KEY is set.

Keys stay in env (~/.hermes/.env). Never store API keys in Second Brain.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CONNECT_MCP_URL = "https://connect.composio.dev/mcp"
MCP_TOOL_HINT = (
    "Use the Hermes MCP tools mcp__composio__COMPOSIO_MANAGE_CONNECTIONS to connect an app "
    "(it returns a sign-in link), mcp__composio__COMPOSIO_SEARCH_TOOLS to find actions, and "
    "mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL to run them."
)


def _hermes_env_value(name: str) -> str:
    val = (os.environ.get(name) or "").strip()
    if val:
        return val
    local = os.environ.get("LOCALAPPDATA") or ""
    for p in (Path(local) / "hermes" / ".env", Path.home() / ".hermes" / ".env"):
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                k, sep, v = line.partition("=")
                if sep and k.strip() == name:
                    return v.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _consumer_key() -> str:
    return _hermes_env_value("COMPOSIO_CONSUMER_KEY")


_MCP_CACHE: dict[str, Any] = {"at": 0.0, "value": None}


def mcp_status() -> dict[str, Any]:
    """Probe the Composio Connect MCP server that Hermes uses (cached 60s)."""
    now = time.time()
    if _MCP_CACHE["value"] is not None and now - _MCP_CACHE["at"] < 60:
        return _MCP_CACHE["value"]
    value = _probe_mcp()
    _MCP_CACHE.update(at=now, value=value)
    return value


def _probe_mcp() -> dict[str, Any]:
    key = _consumer_key()
    if not key:
        return {"configured": False}
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "jarvis-status", "version": "1"},
        },
    }).encode("utf-8")
    req = urllib.request.Request(CONNECT_MCP_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-consumer-api-key": key,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return {"configured": True, "online": 200 <= r.status < 300, "http": r.status}
    except urllib.error.HTTPError as e:
        return {"configured": True, "online": False, "http": e.code,
                "error": "key rejected" if e.code in (401, 403) else f"HTTP {e.code}"}
    except Exception as e:
        return {"configured": True, "online": False, "error": str(e)[:200]}


def _api_key() -> str:
    # Read at call time — server loads ~/.hermes/.env after this module is imported.
    return (os.environ.get("COMPOSIO_API_KEY") or "").strip()


def _user_id() -> str:
    return (os.environ.get("COMPOSIO_USER_ID") or "jarvis_local").strip() or "jarvis_local"


def configured() -> bool:
    return bool(_api_key())


def _client():
    key = _api_key()
    if not key:
        raise RuntimeError(
            "COMPOSIO_API_KEY is not set. Add it to ~/.hermes/.env "
            "(get a key at https://app.composio.dev → Settings)."
        )
    try:
        from composio import Composio
    except ImportError as exc:
        raise RuntimeError(
            "Python package 'composio' is not installed. "
            "Run: pip install composio"
        ) from exc
    return Composio(api_key=key)


def status() -> dict[str, Any]:
    mcp = mcp_status()
    if mcp.get("configured"):
        if mcp.get("online"):
            return {
                "ok": True,
                "configured": True,
                "online": True,
                "mode": "hermes_mcp",
                "message": "Composio is connected and online through Hermes (Composio Connect MCP). " + MCP_TOOL_HINT,
            }
        return {
            "ok": False,
            "configured": True,
            "online": False,
            "mode": "hermes_mcp",
            "error": mcp.get("error"),
            "message": (
                "Composio Connect is set up in Hermes but not reachable right now "
                f"({mcp.get('error') or 'unknown error'}). If the key was rejected, copy a fresh "
                "ck_ key from connect.composio.dev into COMPOSIO_CONSUMER_KEY in "
                "%LOCALAPPDATA%\\hermes\\.env and run: hermes gateway restart."
            ),
        }
    out: dict[str, Any] = {
        "ok": True,
        "configured": configured(),
        "user_id": _user_id(),
        "dashboard": "https://app.composio.dev",
        "docs": "https://docs.composio.dev/docs/quickstart",
    }
    if not configured():
        out["message"] = (
            "Composio is not connected yet. "
            "1) Create an account at https://app.composio.dev "
            "2) Copy API key from Settings "
            "3) Add COMPOSIO_API_KEY=... to C:\\Users\\Jasem\\.hermes\\.env "
            "4) Restart Jarvis, then connect apps from the CONNECT page or by asking Jarvis."
        )
        return out
    try:
        client = _client()
        accounts = []
        try:
            listed = client.connected_accounts.list(user_ids=[_user_id()])
            items = getattr(listed, "items", None) or getattr(listed, "data", None) or listed
            if isinstance(items, list):
                for a in items[:40]:
                    if isinstance(a, dict):
                        accounts.append({
                            "id": a.get("id"),
                            "toolkit": a.get("toolkit") or a.get("appName") or a.get("slug"),
                            "status": a.get("status"),
                        })
                    else:
                        accounts.append({
                            "id": getattr(a, "id", None),
                            "toolkit": getattr(a, "toolkit", None) or getattr(a, "app_name", None),
                            "status": getattr(a, "status", None),
                        })
        except Exception as exc:
            out["accounts_error"] = str(exc)[:240]
        out["connected_accounts"] = accounts
        out["account_count"] = len(accounts)
        err = (out.get("accounts_error") or "").lower()
        if "invalid api key" in err or "401" in err or "apikey_invalid" in err:
            out["ok"] = False
            out["message"] = (
                "COMPOSIO_API_KEY is set but Composio says it is invalid. "
                "Open https://app.composio.dev → Settings → API Keys, copy a fresh key, "
                "replace COMPOSIO_API_KEY=... in C:\\Users\\Jasem\\.hermes\\.env, "
                "then restart Jarvis."
            )
        else:
            out["message"] = (
                f"Composio ready for user '{_user_id()}'. "
                f"{len(accounts)} connected account(s). "
                "Ask Jarvis to connect Gmail/Notion/etc. or use CONNECT → Composio."
            )
    except Exception as exc:
        out["ok"] = False
        out["configured"] = True
        out["error"] = str(exc)[:400]
        out["message"] = (
            "COMPOSIO_API_KEY is set, but Composio rejected it or the SDK failed. "
            "Open https://app.composio.dev → Settings, copy a fresh API key into "
            "C:\\Users\\Jasem\\.hermes\\.env as COMPOSIO_API_KEY=..., then restart Jarvis."
        )
    return out


def connect_toolkit(toolkit: str) -> dict[str, Any]:
    """Start hosted auth (Connect Link) for a toolkit slug like gmail, notion, github."""
    slug = (toolkit or "").strip().lower().replace(" ", "")
    if not slug:
        return {"ok": False, "error": "toolkit is required (e.g. gmail, notion, github, slack)"}
    if _consumer_key():
        return {
            "ok": True,
            "toolkit": slug,
            "mode": "hermes_mcp",
            "message": (
                f"Composio runs through Hermes MCP. Call mcp__composio__COMPOSIO_MANAGE_CONNECTIONS "
                f"for toolkit '{slug}' to get the sign-in link, then give that link to the user."
            ),
        }
    try:
        client = _client()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "configured": configured()}

    link_err = "link() unavailable"
    try:
        link_fn = getattr(client.connected_accounts, "link", None)
        if callable(link_fn):
            try:
                req = link_fn(user_id=_user_id(), toolkit=slug)
            except TypeError:
                req = link_fn(_user_id(), slug)
            redirect = (
                getattr(req, "redirect_url", None)
                or getattr(req, "redirectUrl", None)
                or (req.get("redirect_url") if isinstance(req, dict) else None)
                or (req.get("redirectUrl") if isinstance(req, dict) else None)
            )
            if redirect:
                return {
                    "ok": True,
                    "toolkit": slug,
                    "redirect_url": redirect,
                    "message": (
                        f"Open this link on your PC, sign in to {slug}, then tell Jarvis to continue:\n{redirect}"
                    ),
                }
    except Exception as exc:
        link_err = str(exc)

    try:
        create = getattr(client, "create", None) or getattr(getattr(client, "sessions", None), "create", None)
        if create:
            try:
                session = create(user_id=_user_id())
            except TypeError:
                session = create(_user_id())
            sid = getattr(session, "session_id", None) or getattr(session, "id", None)
            return {
                "ok": True,
                "toolkit": slug,
                "session_id": sid,
                "message": (
                    f"Composio session ready for '{slug}'. "
                    "Ask Jarvis (via Hermes) to connect that app — you'll get a Connect Link. "
                    f"Or open https://app.composio.dev and connect {slug} for user {_user_id()}."
                ),
                "dashboard": "https://app.composio.dev",
                "link_error": link_err,
            }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{exc}",
            "link_error": link_err,
            "hint": "Connect the app in https://app.composio.dev dashboard, then restart Jarvis.",
        }

    return {
        "ok": False,
        "error": "Could not start Composio connect flow.",
        "link_error": link_err,
        "dashboard": "https://app.composio.dev",
    }


def setup_hint() -> str:
    return (
        "Composio setup:\n"
        "1) Sign up at https://app.composio.dev\n"
        "2) Settings → copy API key\n"
        "3) Add to C:\\Users\\Jasem\\.hermes\\.env :\n"
        "   COMPOSIO_API_KEY=your_key_here\n"
        "   COMPOSIO_USER_ID=jarvis_local\n"
        "4) pip install composio  (in jarvis-venv)\n"
        "5) Restart Hermes gateway + Jarvis\n"
        "6) CONNECT page → Composio, or say: connect Gmail with Composio"
    )
