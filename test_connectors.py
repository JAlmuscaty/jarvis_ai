"""Quick connector API smoke tests."""
from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

H = {"Content-Type": "application/json", "X-Jarvis-Token": "jarvis-9f2517"}
BASE = "http://127.0.0.1:8765"


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=H, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def main() -> int:
    fails = 0
    print("=== GET /api/connections ===")
    st, data = call("GET", "/api/connections")
    print("status", st, "linked", data.get("linked_count"), "apps", len(data.get("apps") or []))
    if st != 200 or not data.get("apps"):
        fails += 1
    for a in data.get("apps") or []:
        print(f"  - {a['id']:16} mode={a['mode']:6} linked={a['linked']} status={a['status']}")

    print("=== LINK second_brain ===")
    st, data = call("POST", "/api/connections/connect", {"app": "second_brain"})
    print(st, data.get("message"), "ok", data.get("ok"))
    if not data.get("ok"):
        fails += 1

    print("=== QUERY second_brain ===")
    st, data = call("POST", "/api/connections/query", {"app": "second_brain", "query": "math"})
    print(st, "ok", data.get("ok"), "count", data.get("count"), "source", data.get("source"))
    if not data.get("ok"):
        fails += 1

    vault = Path(tempfile.mkdtemp(prefix="jarvis_vault_"))
    (vault / ".obsidian").mkdir()
    (vault / "Welcome.md").write_text(
        "# Welcome\nJarvis connector test note about quantum physics.\n", encoding="utf-8"
    )
    (vault / "Projects").mkdir()
    (vault / "Projects" / "Ideas.md").write_text(
        "Startup idea: drone search and rescue.\n", encoding="utf-8"
    )
    print("=== LINK obsidian ===", vault)
    st, data = call("POST", "/api/connections/connect", {"app": "obsidian", "vault_path": str(vault)})
    print(st, data.get("ok"), data.get("message") or data.get("error"))
    if not data.get("ok"):
        fails += 1

    print("=== QUERY obsidian ===")
    st, data = call("POST", "/api/connections/query", {"app": "obsidian", "query": "quantum"})
    notes = data.get("notes") or []
    print(st, "ok", data.get("ok"), "count", data.get("count"), "notes", [(n.get("title"), n.get("path")) for n in notes])
    if not data.get("ok") or not notes:
        fails += 1

    print("=== READ obsidian ===")
    st, data = call("POST", "/api/connections/read", {"app": "obsidian", "id": "Welcome.md"})
    print(st, "ok", data.get("ok"), "title", data.get("title"), "chars", len(data.get("text") or ""))
    if not data.get("ok"):
        fails += 1

    print("=== CONNECT gmail (expect setup guidance) ===")
    st, data = call("POST", "/api/connections/connect", {"app": "gmail"})
    print(st, "needs_setup", data.get("needs_setup"), "ok", data.get("ok"))
    print((data.get("error") or "")[:180])
    if not data.get("needs_setup"):
        # If somehow configured, ok must be true or oauth flow
        if not data.get("ok"):
            fails += 1

    print("-" * 40)
    print("FAILS", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
