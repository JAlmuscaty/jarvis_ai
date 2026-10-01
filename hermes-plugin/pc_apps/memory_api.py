"""Long-term memory tools — remember personal facts forever."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

MEM_BASE = (
    os.environ.get("JARVIS_MEMORY_URL")
    or (os.environ.get("JARVIS_BASE_URL") or "http://127.0.0.1:8765").rstrip("/") + "/api/memory"
).rstrip("/")
TOKEN = os.environ.get("JARVIS_HUD_TOKEN") or "jarvis-9f2517"


def _req(method: str, path: str = "", body: dict | None = None) -> dict:
    url = MEM_BASE + path
    data = None
    headers = {"Accept": "application/json", "X-Jarvis-Token": TOKEN}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err)
        except Exception:
            parsed = {"error": err or str(e)}
        return {"ok": False, "http_status": e.code, **(parsed if isinstance(parsed, dict) else {"error": parsed})}
    except Exception as e:
        return {"ok": False, "error": f"Memory API unreachable: {e}"}


def remember_fact(args: dict, **kwargs) -> str:
    """Save a lasting personal fact (names, prefs, relationships, school, etc.)."""
    value = (args.get("value") or args.get("fact") or "").strip()
    title = (args.get("title") or args.get("key") or "").strip()
    if not value:
        return json.dumps({"ok": False, "error": "value is required"})
    phone = (args.get("phone") or args.get("number") or "").strip() or None
    email = (args.get("email") or args.get("gmail") or "").strip() or None
    wa_name = (args.get("whatsapp_name") or args.get("wa_name") or "").strip() or None
    category = (args.get("category") or ("people" if phone or wa_name or email else "personal"))
    payload = {
        "title": title or value.split(".", 1)[0][:80],
        "key": (args.get("key") or title or value)[:80],
        "value": value,
        "category": category,
        "phone": phone,
        "email": email,
        "whatsapp_name": wa_name,
        "source": "voice",
    }
    res = _req("POST", "", payload)
    if res.get("ok"):
        bits = ["Saved to long-term memory (Skills page)."]
        if phone:
            bits.append(f"Phone saved — you can call them with call_contact: {phone}.")
        if email:
            bits.append(f"Email saved — you can gmail_send to them: {email}.")
        if wa_name:
            bits.append(f"WhatsApp display name: {wa_name}.")
        bits.append("You will remember this forever across sessions.")
        res["message"] = " ".join(bits)
    return json.dumps(res)


def digits_only(raw: str | None) -> str | None:
    import re
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("00"):
        s = s[2:]
    d = re.sub(r"\D", "", s)
    return d if len(d) >= 7 else None


def resolve_contact(query: str) -> dict:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}
    from urllib.parse import quote
    return _req("GET", f"/contact?q={quote(q)}")


def list_memories(args: dict, **kwargs) -> str:
    res = _req("GET", "")
    if res.get("ok") is False and "error" in res:
        return json.dumps(res)
    facts = res.get("facts") or []
    return json.dumps({
        "ok": True,
        "count": len(facts),
        "facts": facts,
        "hud_page": "/hud/skills.html",
        "note": "These facts are injected into every voice turn so you never forget them.",
    })


def forget_memory(args: dict, **kwargs) -> str:
    fact_id = (args.get("id") or args.get("fact_id") or args.get("key") or "").strip()
    if not fact_id:
        return json.dumps({"ok": False, "error": "id or key is required"})
    res = _req("DELETE", f"/{fact_id}")
    return json.dumps(res)
