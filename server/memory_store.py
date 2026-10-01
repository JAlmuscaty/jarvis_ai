"""Long-term personal memory for Jarvis — facts that should never be forgotten."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _empty() -> dict:
    return {"facts": [], "updated_at": None}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _slug_key(raw: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (raw or "").strip().lower()).strip("_")
    return (s or "fact")[:80]


def load(path: Path) -> dict:
    with _LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = _empty()
        if not isinstance(data, dict):
            data = _empty()
        data.setdefault("facts", [])
        return data


def save(path: Path, data: dict) -> None:
    with _LOCK:
        data = dict(data)
        data["updated_at"] = _now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def normalize_fact(raw: dict) -> dict:
    key = str((raw or {}).get("key") or "").strip()
    value = str((raw or {}).get("value") or "").strip()
    if not value:
        raise ValueError("value is required")
    if not key:
        # derive a short key from value / title
        title = str((raw or {}).get("title") or "").strip()
        key = _slug_key(title or value.split(".", 1)[0][:60])
    category = str((raw or {}).get("category") or "personal").strip().lower() or "personal"
    phone = str((raw or {}).get("phone") or "").strip() or None
    whatsapp_name = str((raw or {}).get("whatsapp_name") or (raw or {}).get("wa_name") or "").strip() or None
    email_raw = str((raw or {}).get("email") or (raw or {}).get("gmail") or "").strip().lower() or None
    email = None
    if email_raw:
        email_raw = email_raw.replace(" ", "")
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_raw):
            email = email_raw[:120]
    if phone:
        # keep + and digits only for storage display; digits extracted at open-time
        phone = re.sub(r"[^\d+]", "", phone)[:24] or None
    return {
        "id": str((raw or {}).get("id") or _new_id()),
        "key": _slug_key(key),
        "title": (str((raw or {}).get("title") or key).strip() or key)[:120],
        "value": value[:800],
        "category": category[:40],
        "phone": phone,
        "email": email,
        "whatsapp_name": whatsapp_name[:120] if whatsapp_name else None,
        "source": str((raw or {}).get("source") or "jarvis")[:40],
        "created_at": (raw or {}).get("created_at") or _now(),
        "updated_at": _now(),
    }


def upsert_fact(path: Path, raw: dict) -> dict:
    data = load(path)
    fact = normalize_fact(raw)
    existing = None
    for f in data["facts"]:
        if f.get("id") == fact["id"] or f.get("key") == fact["key"]:
            existing = f
            break
    if existing:
        fact["id"] = existing["id"]
        fact["created_at"] = existing.get("created_at") or fact["created_at"]
        data["facts"] = [f for f in data["facts"] if f.get("id") != fact["id"]]
    data["facts"].append(fact)
    save(path, data)
    return fact


def delete_fact(path: Path, fact_id: str) -> bool:
    data = load(path)
    before = len(data["facts"])
    fid = (fact_id or "").strip()
    data["facts"] = [
        f for f in data["facts"]
        if f.get("id") != fid and f.get("key") != fid
    ]
    if len(data["facts"]) == before:
        return False
    save(path, data)
    return True


def delete_facts_matching(
    path: Path,
    *,
    categories: set[str] | None = None,
    keys: set[str] | None = None,
    text_re: re.Pattern[str] | None = None,
) -> list[dict]:
    """Remove facts by category, key, and/or title/value regex. Returns deleted facts."""
    data = load(path)
    cats = {c.strip().lower() for c in (categories or set()) if c}
    keyset = {_slug_key(k) for k in (keys or set()) if k}
    kept: list[dict] = []
    deleted: list[dict] = []
    for f in data.get("facts") or []:
        cat = (f.get("category") or "").strip().lower()
        key = (f.get("key") or "").strip().lower()
        blob = f"{f.get('title') or ''} {f.get('value') or ''}"
        hit = False
        if cats and cat in cats:
            hit = True
        if keyset and key in keyset:
            hit = True
        if text_re is not None and text_re.search(blob):
            hit = True
        if hit:
            deleted.append(f)
        else:
            kept.append(f)
    if deleted:
        data["facts"] = kept
        save(path, data)
    return deleted


def snapshot(path: Path) -> dict[str, Any]:
    data = load(path)
    facts = sorted(
        data.get("facts") or [],
        key=lambda f: ((f.get("category") or ""), (f.get("title") or "").lower()),
    )
    return {"facts": facts, "count": len(facts), "updated_at": data.get("updated_at")}


def format_for_prompt(path: Path, *, max_facts: int = 80) -> str:
    """Compact bullet list injected into every voice turn."""
    facts = snapshot(path).get("facts") or []
    if not facts:
        return ""
    lines = []
    for f in facts[:max_facts]:
        title = (f.get("title") or f.get("key") or "fact").strip()
        value = (f.get("value") or "").strip()
        if not value:
            continue
        extra = []
        if f.get("phone"):
            extra.append(f"phone {f['phone']} (callable)")
        if f.get("email"):
            extra.append(f"email {f['email']} (gmail)")
        if f.get("whatsapp_name"):
            extra.append(f"WhatsApp name '{f['whatsapp_name']}'")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        lines.append(f"- {title}: {value}{suffix}")
    return "\n".join(lines)


def find_contact(path: Path, query: str) -> dict | None:
    """Match a person/contact memory by title, value, WhatsApp name, phone, or key."""
    q = (query or "").strip().lower()
    if not q:
        return None
    q_digits = re.sub(r"\D", "", q)
    facts = snapshot(path).get("facts") or []
    # Prefer people/contact categories, but search all
    scored: list[tuple[int, dict]] = []
    for f in facts:
        title = (f.get("title") or "").lower()
        value = (f.get("value") or "").lower()
        wa = (f.get("whatsapp_name") or "").lower()
        key = (f.get("key") or "").lower()
        email = (f.get("email") or "").lower()
        phone = re.sub(r"\D", "", f.get("phone") or "")
        # also dig phone out of value
        value_digits = re.sub(r"\D", "", f.get("value") or "")
        score = 0
        if q == title or q == value or q == wa or q == key or (email and q == email):
            score = 100
        elif q in title or title in q:
            score = 80
        elif q in wa or (wa and wa in q):
            score = 75
        elif email and (q in email or email in q):
            score = 85
        elif q in value:
            score = 60
        elif q_digits and len(q_digits) >= 7 and (
            q_digits in phone or q_digits in value_digits or phone.endswith(q_digits[-8:])
        ):
            score = 90
        if score:
            if (f.get("category") or "") in ("people", "contact", "contacts", "friends"):
                score += 5
            scored.append((score, f))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def phone_digits(raw: str | None) -> str | None:
    """Normalize to WhatsApp send digits (country code, no +)."""
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("00"):
        s = s[2:]
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7:
        return None
    return digits
