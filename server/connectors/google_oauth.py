"""Google OAuth API connectors — Gmail, Calendar, Drive/Docs.

Uses installed-app OAuth (localhost redirect). Credentials from env:
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
Optional file: connectors/google_oauth_client.json (Desktop client download from Google Cloud).
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from . import CONNECTORS_DIR, catalog_by_id, set_link, token_path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_PORT = int(os.environ.get("JARVIS_GOOGLE_OAUTH_PORT", "8769"))
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/oauth/google/callback"

_CLIENT_JSON = CONNECTORS_DIR / "google_oauth_client.json"
_pending_code: dict[str, Any] = {"code": None, "error": None}
_server_lock = threading.Lock()


def _client_creds() -> tuple[str, str] | None:
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if cid and secret:
        return cid, secret
    try:
        raw = json.loads(_CLIENT_JSON.read_text(encoding="utf-8"))
        block = raw.get("installed") or raw.get("web") or raw
        cid = str(block.get("client_id") or "").strip()
        secret = str(block.get("client_secret") or "").strip()
        if cid and secret:
            return cid, secret
    except Exception:
        pass
    return None


def oauth_configured() -> bool:
    return _client_creds() is not None


def _load_token(app_id: str = "google") -> dict:
    # Shared Google token file used by all Google API connectors
    p = token_path("google")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_token(data: dict) -> None:
    p = token_path("google")
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _scopes_for(app_ids: list[str]) -> list[str]:
    cat = catalog_by_id()
    scopes: list[str] = []
    for aid in app_ids:
        meta = cat.get(aid) or {}
        for s in meta.get("scopes") or []:
            if s not in scopes:
                scopes.append(s)
    # Always include basic profile email for account label
    if "openid" not in scopes:
        scopes.insert(0, "openid")
    if "https://www.googleapis.com/auth/userinfo.email" not in scopes:
        scopes.append("https://www.googleapis.com/auth/userinfo.email")
    return scopes


class _OAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth/google/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        if qs.get("error"):
            _pending_code["error"] = qs["error"][0]
        else:
            _pending_code["code"] = (qs.get("code") or [None])[0]
        body = (
            b"<html><body style='font-family:sans-serif;background:#050b14;color:#00e5ff;"
            b"display:flex;align-items:center;justify-content:center;height:100vh'>"
            b"<div><h2>Jarvis connected</h2><p>You can close this tab.</p></div></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_oauth_link(app_ids: list[str] | None = None) -> dict[str, Any]:
    """Begin Google OAuth; opens browser; blocks briefly waiting for callback."""
    creds = _client_creds()
    if not creds:
        return {
            "ok": False,
            "error": (
                "Google OAuth not configured. Create a Desktop OAuth client in Google Cloud Console, "
                "then either set GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET in ~/.hermes/.env "
                f"or save the JSON as {_CLIENT_JSON}."
            ),
            "setup_url": "https://console.cloud.google.com/apis/credentials",
            "needs_setup": True,
        }

    client_id, client_secret = creds
    targets = app_ids or ["gmail", "google_calendar", "google_drive", "google_docs"]
    scopes = _scopes_for(targets)

    with _server_lock:
        _pending_code["code"] = None
        _pending_code["error"] = None
        httpd = HTTPServer(("127.0.0.1", REDIRECT_PORT), _OAuthHandler)
        thread = threading.Thread(target=httpd.handle_request, daemon=True)
        thread.start()

        params = {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        url = AUTH_URL + "?" + urllib.parse.urlencode(params)
        try:
            webbrowser.open(url)
        except Exception:
            pass

        thread.join(timeout=180)
        try:
            httpd.server_close()
        except Exception:
            pass

        if _pending_code.get("error"):
            return {"ok": False, "error": f"OAuth error: {_pending_code['error']}"}
        code = _pending_code.get("code")
        if not code:
            return {"ok": False, "error": "OAuth timed out — complete Google sign-in in the browser and retry."}

        token = _exchange_code(code, client_id, client_secret)
        if not token.get("access_token"):
            return {"ok": False, "error": token.get("error") or "Token exchange failed"}

        token["scopes"] = scopes
        token["app_ids"] = targets
        _save_token(token)

        account = _fetch_email(token.get("access_token") or "")
        for aid in targets:
            set_link(aid, linked=True, meta={"account": account, "auth": "google_oauth"})

        return {
            "ok": True,
            "linked": targets,
            "account": account,
            "message": f"Linked Google account {account or ''} for {', '.join(targets)}. Jarvis can now read them without opening the sites.",
        }


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(err)
        except Exception:
            return {"error": err or str(e)}


def _refresh_if_needed(token: dict) -> dict:
    if not token:
        return {}
    # naive: always try refresh if we have refresh_token and access might be old
    saved = token.get("saved_at")
    access = token.get("access_token")
    refresh = token.get("refresh_token")
    if access and refresh:
        # Refresh if older than 45 minutes
        try:
            age = time.time() - time.mktime(time.strptime(saved, "%Y-%m-%dT%H:%M:%S")) if saved else 99999
        except Exception:
            age = 99999
        if age < 2700:
            return token
    if not refresh:
        return token
    creds = _client_creds()
    if not creds:
        return token
    client_id, client_secret = creds
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            fresh = json.loads(r.read().decode())
            token.update({k: v for k, v in fresh.items() if v})
            _save_token(token)
    except Exception:
        pass
    return token


def access_token() -> str | None:
    tok = _refresh_if_needed(_load_token())
    return tok.get("access_token")


def _api_get(url: str, token: str, params: dict | None = None) -> dict:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _api_json(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err)
        except Exception:
            parsed = {"error": {"message": err or str(e)}}
        if isinstance(parsed, dict):
            parsed.setdefault("http_status", e.code)
            return parsed
        return {"ok": False, "http_status": e.code, "error": str(parsed)}


def _fetch_email(token: str) -> str | None:
    try:
        data = _api_get("https://www.googleapis.com/oauth2/v2/userinfo", token)
        return data.get("email")
    except Exception:
        return None


def gmail_list(query: str = "", max_results: int = 10) -> dict:
    token = access_token()
    if not token:
        return {"ok": False, "error": "Gmail not linked. Connect Gmail in the HUD first."}
    params = {"maxResults": max(1, min(max_results, 25))}
    if query:
        params["q"] = query
    try:
        listing = _api_get("https://gmail.googleapis.com/gmail/v1/users/me/messages", token, params)
        messages = []
        for m in (listing.get("messages") or [])[: max_results]:
            mid = m.get("id")
            if not mid:
                continue
            full = _api_get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                token,
                {"format": "metadata", "metadataHeaders": "From,Subject,Date"},
            )
            headers = {h["name"].lower(): h["value"] for h in (full.get("payload") or {}).get("headers") or [] if "name" in h}
            messages.append({
                "id": mid,
                "snippet": full.get("snippet"),
                "from": headers.get("from"),
                "subject": headers.get("subject"),
                "date": headers.get("date"),
            })
        return {"ok": True, "count": len(messages), "messages": messages, "source": "gmail_api"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def gmail_read(message_id: str) -> dict:
    token = access_token()
    if not token:
        return {"ok": False, "error": "Gmail not linked."}
    try:
        full = _api_get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            token,
            {"format": "full"},
        )
        headers = {h["name"].lower(): h["value"] for h in (full.get("payload") or {}).get("headers") or [] if "name" in h}
        body_text = _extract_body(full.get("payload") or {})
        return {
            "ok": True,
            "id": message_id,
            "from": headers.get("from"),
            "to": headers.get("to"),
            "subject": headers.get("subject"),
            "date": headers.get("date"),
            "snippet": full.get("snippet"),
            "body": body_text[:8000],
            "source": "gmail_api",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return _b64(payload["body"]["data"])
    parts = payload.get("parts") or []
    texts = []
    for part in parts:
        mime = part.get("mimeType") or ""
        if mime == "text/plain" and part.get("body", {}).get("data"):
            texts.append(_b64(part["body"]["data"]))
        elif mime.startswith("multipart/"):
            texts.append(_extract_body(part))
    return "\n".join(t for t in texts if t).strip()


def _b64(data: str) -> str:
    raw = base64.urlsafe_b64decode(data + "==")
    return raw.decode("utf-8", errors="replace")


def calendar_list(max_results: int = 15) -> dict:
    token = access_token()
    if not token:
        return {"ok": False, "error": "Google Calendar not linked."}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        data = _api_get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            token,
            {
                "timeMin": now,
                "maxResults": max(1, min(max_results, 40)),
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        events = []
        for ev in data.get("items") or []:
            start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date")
            end = (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date")
            events.append({
                "id": ev.get("id"),
                "title": ev.get("summary"),
                "start": start,
                "end": end,
                "location": ev.get("location"),
                "description": (ev.get("description") or "")[:500] or None,
            })
        return {"ok": True, "count": len(events), "events": events, "source": "google_calendar_api"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _calendar_tz() -> str:
    return (
        os.environ.get("JARVIS_CALENDAR_TZ")
        or os.environ.get("TZ")
        or "Asia/Kuwait"
    ).strip() or "Asia/Kuwait"


def _parse_hhmm(value: str | None) -> tuple[int, int] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h, mi


def jarvis_event_to_google_body(
    event: dict,
    *,
    reminder_minutes: list[int] | None = None,
) -> dict:
    """Map a Jarvis HUD event into a Google Calendar event resource."""
    import datetime as _dt

    title = str(event.get("title") or "Jarvis reminder").strip()[:160]
    date = str(event.get("date") or "").strip()[:10]
    notes_parts = []
    if event.get("class_name"):
        notes_parts.append(f"Class: {event['class_name']}")
    if event.get("notes"):
        notes_parts.append(str(event["notes"]))
    notes_parts.append(f"Jarvis id: {event.get('id') or ''}")
    description = "\n".join(notes_parts).strip()
    tz = _calendar_tz()
    start_hm = _parse_hhmm(event.get("time"))
    end_hm = _parse_hhmm(event.get("end_time"))
    body: dict[str, Any] = {
        "summary": title,
        "description": description,
    }
    if start_hm:
        sh, sm = start_hm
        if end_hm:
            eh, em = end_hm
        else:
            total = sh * 60 + sm + 60
            eh, em = (total // 60) % 24, total % 60
        body["start"] = {"dateTime": f"{date}T{sh:02d}:{sm:02d}:00", "timeZone": tz}
        body["end"] = {"dateTime": f"{date}T{eh:02d}:{em:02d}:00", "timeZone": tz}
        mins = reminder_minutes if reminder_minutes is not None else [30, 0]
    else:
        y, mth, d = [int(x) for x in date.split("-")]
        # Multi-day holidays: Google all-day end is exclusive → day after end_date
        end_raw = str(event.get("end_date") or "").strip()[:10]
        if end_raw and re.match(r"^\d{4}-\d{2}-\d{2}$", end_raw):
            ey, emth, ed = [int(x) for x in end_raw.split("-")]
            end_date = (_dt.date(ey, emth, ed) + _dt.timedelta(days=1)).isoformat()
        else:
            end_date = (_dt.date(y, mth, d) + _dt.timedelta(days=1)).isoformat()
        body["start"] = {"date": date}
        body["end"] = {"date": end_date}
        # All-day: minutes before midnight on the event day (12h ≈ noon day before)
        mins = reminder_minutes if reminder_minutes is not None else [12 * 60]

    body["reminders"] = {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": max(0, int(m))} for m in mins],
    }
    return body


def calendar_upsert_event(event: dict, *, reminder_minutes: list[int] | None = None) -> dict:
    """Create or update a Google Calendar event from a Jarvis calendar item."""
    token = access_token()
    if not token:
        return {
            "ok": False,
            "error": "Google Calendar not linked. Connect it in the HUD (Connect page), then add the event again.",
            "needs_link": True,
        }
    if not str(event.get("date") or "").strip():
        return {"ok": False, "error": "date required"}
    body = jarvis_event_to_google_body(event, reminder_minutes=reminder_minutes)
    google_id = str(event.get("google_event_id") or "").strip()
    base = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    try:
        if google_id:
            data = _api_json("PUT", f"{base}/{urllib.parse.quote(google_id)}", token, body)
        else:
            data = _api_json("POST", base, token, body)
        if data.get("http_status") and data.get("http_status") >= 400:
            msg = ((data.get("error") or {}) if isinstance(data.get("error"), dict) else {}).get("message") or data.get("error") or str(data)
            if data.get("http_status") in (401, 403):
                return {
                    "ok": False,
                    "error": (
                        f"Google Calendar write blocked ({msg}). "
                        "Reconnect Google Calendar in the HUD so Jarvis gets write + reminder permission."
                    ),
                    "needs_reauth": True,
                }
            return {"ok": False, "error": str(msg), "raw": data}
        gid = data.get("id")
        if not gid:
            return {"ok": False, "error": "Google Calendar returned no event id", "raw": data}
        return {
            "ok": True,
            "google_event_id": gid,
            "html_link": data.get("htmlLink"),
            "source": "google_calendar_api",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def calendar_delete_remote(google_event_id: str) -> dict:
    token = access_token()
    if not token:
        return {"ok": False, "error": "Google Calendar not linked."}
    gid = (google_event_id or "").strip()
    if not gid:
        return {"ok": False, "error": "google_event_id required"}
    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{urllib.parse.quote(gid)}"
    try:
        req = urllib.request.Request(url, method="DELETE", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        return {"ok": True, "deleted": gid}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": True, "deleted": gid, "note": "already gone"}
        err = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": err or str(e), "http_status": e.code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def drive_search(query: str, max_results: int = 10) -> dict:
    token = access_token()
    if not token:
        return {"ok": False, "error": "Google Drive not linked."}
    q = query.strip()
    # Prefer name contains; also allow fullText
    gq = f"fullText contains '{q.replace(chr(39), '')}' and trashed=false" if q else "trashed=false"
    try:
        data = _api_get(
            "https://www.googleapis.com/drive/v3/files",
            token,
            {
                "q": gq,
                "pageSize": max(1, min(max_results, 25)),
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
            },
        )
        files = data.get("files") or []
        return {"ok": True, "count": len(files), "files": files, "source": "google_drive_api"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def drive_read_text(file_id: str) -> dict:
    token = access_token()
    if not token:
        return {"ok": False, "error": "Google Drive not linked."}
    try:
        meta = _api_get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            token,
            {"fields": "id,name,mimeType,webViewLink"},
        )
        mime = meta.get("mimeType") or ""
        text = ""
        if mime == "application/vnd.google-apps.document":
            # export as plain text
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType=text/plain"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", errors="replace")
        elif mime.startswith("text/") or mime in ("application/json", "application/javascript"):
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", errors="replace")
        else:
            return {
                "ok": True,
                "id": file_id,
                "name": meta.get("name"),
                "mimeType": mime,
                "webViewLink": meta.get("webViewLink"),
                "note": "Binary/unsupported type for inline read; open link if needed.",
                "source": "google_drive_api",
            }
        return {
            "ok": True,
            "id": file_id,
            "name": meta.get("name"),
            "mimeType": mime,
            "text": text[:12000],
            "webViewLink": meta.get("webViewLink"),
            "source": "google_drive_api",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def drive_upload_file(
    path: str | Path,
    *,
    name: str | None = None,
    mime_type: str | None = None,
) -> dict:
    """Upload a local file to the user's Drive (requires drive.file or drive scope)."""
    token = access_token()
    if not token:
        return {
            "ok": False,
            "error": "Google Drive not linked. Connect Google Drive in the HUD (reconnect for write access).",
            "needs_link": True,
        }
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"File not found: {p}"}
    fname = (name or p.name)[:180]
    mime = mime_type or {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(p.suffix.lower(), "application/octet-stream")
    meta = json.dumps({"name": fname}).encode("utf-8")
    raw = p.read_bytes()
    boundary = f"jarvis_{uuid_like()}"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        b'Content-Type: application/json; charset=UTF-8\r\n\r\n',
        meta,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        raw,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,mimeType,webViewLink"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", f"multipart/related; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        return {
            "ok": True,
            "id": data.get("id"),
            "name": data.get("name"),
            "mimeType": data.get("mimeType"),
            "webViewLink": data.get("webViewLink"),
            "source": "google_drive_upload",
        }
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        msg = err
        try:
            parsed = json.loads(err)
            msg = ((parsed.get("error") or {}) if isinstance(parsed.get("error"), dict) else {}).get("message") or err
        except Exception:
            pass
        needs = e.code in (401, 403)
        return {
            "ok": False,
            "error": str(msg),
            "http_status": e.code,
            "needs_reauth": needs,
            "hint": (
                "Reconnect Google Drive / Docs in the HUD so Jarvis gets write permission "
                "(drive.file + documents)."
                if needs else None
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def docs_create_with_images(
    title: str,
    image_paths: list[str | Path],
) -> dict:
    """Create a Google Doc and insert handwritten page images (Drive upload + Docs API)."""
    token = access_token()
    if not token:
        return {
            "ok": False,
            "error": "Google Docs not linked. Connect Google Docs in the HUD (reconnect for write access).",
            "needs_link": True,
        }
    # 1) Create empty doc
    created = _api_json(
        "POST",
        "https://docs.googleapis.com/v1/documents",
        token,
        {"title": (title or "Handwritten note")[:120]},
    )
    if created.get("http_status") and created.get("http_status") >= 400:
        msg = ((created.get("error") or {}) if isinstance(created.get("error"), dict) else {}).get("message") or created.get("error")
        return {
            "ok": False,
            "error": str(msg or created),
            "needs_reauth": created.get("http_status") in (401, 403),
            "hint": "Reconnect Google Docs in the HUD with write scopes.",
        }
    doc_id = created.get("documentId")
    if not doc_id:
        return {"ok": False, "error": "Docs create returned no documentId", "raw": created}

    inserted = 0
    upload_errors: list[str] = []
    for img_path in image_paths:
        up = drive_upload_file(img_path, mime_type="image/png")
        if not up.get("ok") or not up.get("id"):
            upload_errors.append(str(up.get("error") or up))
            continue
        # Make the image readable by the Doc via drive permissions is not always needed for same user
        reqs = {
            "requests": [
                {
                    "insertInlineImage": {
                        "uri": f"https://drive.google.com/uc?id={up['id']}",
                        "location": {"index": 1},
                        "objectSize": {
                            "height": {"magnitude": 500, "unit": "PT"},
                            "width": {"magnitude": 360, "unit": "PT"},
                        },
                    }
                },
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": "\n",
                    }
                },
            ]
        }
        # Inserting at index 1 repeatedly stacks newest first — reverse order by inserting at end instead
        # Fetch end index
        meta = _api_json("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}", token, None)
        end_index = 1
        try:
            body_content = ((meta.get("body") or {}).get("content") or [])
            if body_content:
                end_index = max(1, int(body_content[-1].get("endIndex") or 2) - 1)
        except Exception:
            end_index = 1
        reqs = {
            "requests": [
                {
                    "insertInlineImage": {
                        "uri": f"https://drive.google.com/uc?id={up['id']}",
                        "location": {"index": end_index},
                        "objectSize": {
                            "height": {"magnitude": 520, "unit": "PT"},
                            "width": {"magnitude": 370, "unit": "PT"},
                        },
                    }
                }
            ]
        }
        upd = _api_json(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            token,
            reqs,
        )
        if upd.get("http_status") and upd.get("http_status") >= 400:
            # Fallback: Docs can't fetch some Drive URIs — keep PDF upload path instead
            upload_errors.append(str(upd.get("error") or upd))
        else:
            inserted += 1

    link = f"https://docs.google.com/document/d/{doc_id}/edit"
    ok = inserted > 0 or not upload_errors
    return {
        "ok": ok or bool(doc_id),
        "documentId": doc_id,
        "webViewLink": link,
        "images_inserted": inserted,
        "upload_errors": upload_errors[:5],
        "note": (
            None if inserted
            else "Doc created; image insert may need Drive images shared. PDF upload is a reliable fallback."
        ),
    }


def uuid_like() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def docs_create_text(title: str, content: str) -> dict:
    """Create a Google Doc filled with plain text (full essays / notes)."""
    token = access_token()
    if not token:
        return {
            "ok": False,
            "error": "Google Docs not linked. Connect Google Docs in the HUD (reconnect for write access).",
            "needs_link": True,
        }
    created = _api_json(
        "POST",
        "https://docs.googleapis.com/v1/documents",
        token,
        {"title": (title or "Document")[:120]},
    )
    if created.get("http_status") and created.get("http_status") >= 400:
        msg = ((created.get("error") or {}) if isinstance(created.get("error"), dict) else {}).get("message") or created.get("error")
        return {
            "ok": False,
            "error": str(msg or created),
            "needs_reauth": created.get("http_status") in (401, 403),
            "hint": "Reconnect Google Docs in CONNECT for write access.",
        }
    doc_id = created.get("documentId")
    if not doc_id:
        return {"ok": False, "error": "Docs create returned no documentId", "raw": created}

    text = (content or "").strip()
    if text:
        # Insert at index 1 (start of body)
        upd = _api_json(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            token,
            {"requests": [{"insertText": {"location": {"index": 1}, "text": text + "\n"}}]},
        )
        if upd.get("http_status") and upd.get("http_status") >= 400:
            msg = ((upd.get("error") or {}) if isinstance(upd.get("error"), dict) else {}).get("message") or upd.get("error")
            return {
                "ok": False,
                "error": f"Doc created but text insert failed: {msg}",
                "documentId": doc_id,
                "webViewLink": f"https://docs.google.com/document/d/{doc_id}/edit",
            }

    link = f"https://docs.google.com/document/d/{doc_id}/edit"
    return {
        "ok": True,
        "documentId": doc_id,
        "webViewLink": link,
        "title": title,
        "chars": len(text),
        "source": "google_docs_create",
    }


def slides_create_presentation(title: str, slides: list[dict]) -> dict:
    """Create a Google Slides deck with title+body text per slide."""
    token = access_token()
    if not token:
        return {
            "ok": False,
            "error": "Google Slides not linked. Connect Google Slides in the HUD (reconnect for write access).",
            "needs_link": True,
        }
    created = _api_json(
        "POST",
        "https://slides.googleapis.com/v1/presentations",
        token,
        {"title": (title or "Presentation")[:120]},
    )
    if created.get("http_status") and created.get("http_status") >= 400:
        msg = ((created.get("error") or {}) if isinstance(created.get("error"), dict) else {}).get("message") or created.get("error")
        return {
            "ok": False,
            "error": str(msg or created),
            "needs_reauth": created.get("http_status") in (401, 403),
            "hint": "Reconnect Google Drive/Docs/Slides in CONNECT for write access (presentations scope).",
        }
    pres_id = created.get("presentationId")
    if not pres_id:
        return {"ok": False, "error": "Slides create returned no presentationId", "raw": created}

    # Default deck has 1 blank slide — reuse it for first content, create the rest
    existing = (created.get("slides") or [])
    first_id = (existing[0] or {}).get("objectId") if existing else None

    requests: list[dict] = []
    # Create additional slides first (so we know object ids after one batch)
    # Simpler approach: create N-1 blank slides, then write text to all via a follow-up get
    extra = max(0, len(slides) - (1 if first_id else 0))
    for i in range(extra):
        requests.append({"createSlide": {"insertionIndex": 1 + i}})

    if requests:
        batch = _api_json(
            "POST",
            f"https://slides.googleapis.com/v1/presentations/{pres_id}:batchUpdate",
            token,
            {"requests": requests},
        )
        if batch.get("http_status") and batch.get("http_status") >= 400:
            msg = ((batch.get("error") or {}) if isinstance(batch.get("error"), dict) else {}).get("message") or batch.get("error")
            return {
                "ok": False,
                "error": f"Created presentation but failed adding slides: {msg}",
                "presentationId": pres_id,
                "webViewLink": f"https://docs.google.com/presentation/d/{pres_id}/edit",
            }

    meta = _api_json("GET", f"https://slides.googleapis.com/v1/presentations/{pres_id}", token, None)
    slide_objs = meta.get("slides") or []
    text_reqs: list[dict] = []
    for i, spec in enumerate(slides):
        if i >= len(slide_objs):
            break
        slide = slide_objs[i]
        slide_id = slide.get("objectId")
        title_s = str(spec.get("title") or f"Slide {i+1}")[:120]
        body_s = str(spec.get("body") or spec.get("text") or "")[:4500]
        # Find title + body shape ids from page elements
        title_shape = None
        body_shape = None
        for el in slide.get("pageElements") or []:
            shape = el.get("shape") or {}
            placeholder = ((shape.get("placeholder") or {}).get("type") or "").upper()
            oid = el.get("objectId")
            if not oid:
                continue
            if placeholder in ("TITLE", "CENTERED_TITLE") and not title_shape:
                title_shape = oid
            elif placeholder in ("BODY", "SUBTITLE") and not body_shape:
                body_shape = oid
        if title_shape and body_shape:
            text_reqs.append({"insertText": {"objectId": title_shape, "insertionIndex": 0, "text": title_s}})
            if body_s:
                text_reqs.append({"insertText": {"objectId": body_shape, "insertionIndex": 0, "text": body_s}})
        elif title_shape:
            combined = title_s if not body_s else f"{title_s}\n\n{body_s}"
            text_reqs.append({"insertText": {"objectId": title_shape, "insertionIndex": 0, "text": combined}})
        elif body_shape:
            combined = title_s if not body_s else f"{title_s}\n\n{body_s}"
            text_reqs.append({"insertText": {"objectId": body_shape, "insertionIndex": 0, "text": combined}})

    if text_reqs:
        # Clear default empty text boxes by deleting then inserting is complex; insertText on empty works
        upd = _api_json(
            "POST",
            f"https://slides.googleapis.com/v1/presentations/{pres_id}:batchUpdate",
            token,
            {"requests": text_reqs},
        )
        if upd.get("http_status") and upd.get("http_status") >= 400:
            msg = ((upd.get("error") or {}) if isinstance(upd.get("error"), dict) else {}).get("message") or upd.get("error")
            return {
                "ok": False,
                "error": f"Slides created but text fill failed: {msg}",
                "presentationId": pres_id,
                "webViewLink": f"https://docs.google.com/presentation/d/{pres_id}/edit",
                "slide_count": len(slide_objs),
            }

    link = f"https://docs.google.com/presentation/d/{pres_id}/edit"
    return {
        "ok": True,
        "presentationId": pres_id,
        "webViewLink": link,
        "slide_count": len(slide_objs) or len(slides),
        "title": title,
        "source": "google_slides_create",
    }
