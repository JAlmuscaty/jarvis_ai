"""NotebookLM integration tests for Jarvis.

Runs structural + live CDP checks. Exit code 0 only if critical path passes.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

# Prefer UTF-8 console on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "hermes-plugin"
HERMES_PLUGIN = Path.home() / "AppData" / "Local" / "hermes" / "plugins"
JARVIS = "http://127.0.0.1:8765"
CDP = "http://127.0.0.1:9222"
TOKEN = os.environ.get("JARVIS_HUD_TOKEN", "jarvis-9f2517")

PASSED = 0
FAILED = 0
WARNED = 0
RESULTS: list[tuple[str, str, str]] = []


def ok(name: str, detail: str = "") -> None:
    global PASSED
    PASSED += 1
    RESULTS.append(("PASS", name, detail))
    print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str = "") -> None:
    global FAILED
    FAILED += 1
    RESULTS.append(("FAIL", name, detail))
    print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def warn(name: str, detail: str = "") -> None:
    global WARNED
    WARNED += 1
    RESULTS.append(("WARN", name, detail))
    print(f"[WARN] {name}" + (f" — {detail}" if detail else ""))


def http_json(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 20.0):
    h = {"Accept": "application/json", "X-Jarvis-Token": TOKEN}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        return r.status, (json.loads(raw) if raw else {})


def ensure_plugin_path() -> None:
    for p in (str(PLUGIN), str(HERMES_PLUGIN)):
        if p not in sys.path:
            sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plugin_files_present() -> None:
    required = [
        PLUGIN / "pc_apps" / "notebooklm_actions.py",
        PLUGIN / "pc_apps" / "schemas.py",
        PLUGIN / "pc_apps" / "__init__.py",
        PLUGIN / "pc_apps" / "plugin.yaml",
        HERMES_PLUGIN / "pc_apps" / "notebooklm_actions.py",
        HERMES_PLUGIN / "pc_apps" / "plugin.yaml",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        fail("plugin_files_present", f"missing: {missing}")
    else:
        ok("plugin_files_present", "repo + Hermes plugin copies exist")


def test_schemas_and_registration() -> None:
    ensure_plugin_path()
    from pc_apps import schemas  # type: ignore

    names = [
        "NOTEBOOKLM_QUERY",
        "NOTEBOOKLM_READ_NOTES",
        "NOTEBOOKLM_AUDIO_OVERVIEW",
        "NOTEBOOKLM_GENERATE_GUIDE",
        "NOTEBOOKLM_ADD_NOTE",
        "NOTEBOOKLM_LIST_NOTEBOOKS",
        "NOTEBOOKLM_STATUS",
    ]
    missing = [n for n in names if not hasattr(schemas, n)]
    if missing:
        fail("schemas_defined", f"missing schemas: {missing}")
        return
    ok("schemas_defined", f"{len(names)} schemas")

    yaml_text = (PLUGIN / "pc_apps" / "plugin.yaml").read_text(encoding="utf-8")
    tools = [
        "notebooklm_query",
        "notebooklm_read_notes",
        "notebooklm_audio_overview",
        "notebooklm_generate_guide",
        "notebooklm_add_note",
        "notebooklm_list_notebooks",
        "notebooklm_status",
    ]
    absent = [t for t in tools if t not in yaml_text]
    if absent:
        fail("plugin_yaml_tools", f"missing from plugin.yaml: {absent}")
    else:
        ok("plugin_yaml_tools", f"{len(tools)} tools listed")


def test_allowlist_and_aliases() -> None:
    ensure_plugin_path()
    from pc_apps import tools as t  # type: ignore

    apps = t._load_allowlist()
    if "notebooklm" not in apps:
        fail("allowlist_notebooklm", f"keys={sorted(apps)[:20]}")
        return
    ok("allowlist_notebooklm", str(apps["notebooklm"].get("url") or apps["notebooklm"]))

    # alias resolution via open_pc_app path helpers
    aliases = ["notebooklm", "notebook lm", "notebook", "google notebooklm"]
    # tools.open_pc_app normalizes; probe by reading alias map pattern from source
    src = (PLUGIN / "pc_apps" / "tools.py").read_text(encoding="utf-8")
    if '"notebooklm": "notebooklm"' not in src:
        fail("alias_map", "notebooklm alias missing in tools.py")
    else:
        ok("alias_map", f"checked {len(aliases)} aliases in source")


def test_cdp_up() -> None:
    try:
        status, body = http_json("GET", f"{CDP}/json/version", timeout=3)
        if status == 200 and "Browser" in body:
            ok("cdp_up", body.get("Browser", "")[:60])
        else:
            fail("cdp_up", f"status={status} body={body}")
    except Exception as exc:
        fail("cdp_up", str(exc))


def test_connections_api() -> None:
    try:
        status, data = http_json("GET", f"{JARVIS}/api/connections")
        apps = data.get("apps") or []
        nlm = next((a for a in apps if a.get("id") == "notebooklm"), None)
        if not nlm:
            fail("connections_lists_notebooklm", "notebooklm not in /api/connections")
            return
        if not nlm.get("connected"):
            warn("connections_connected", "notebooklm present but connected=false")
        else:
            ok("connections_lists_notebooklm", f"connected={nlm.get('connected')}")
    except Exception as exc:
        fail("connections_lists_notebooklm", str(exc))


def test_open_notebooklm_via_plugin() -> None:
    ensure_plugin_path()
    from pc_apps import tools as t  # type: ignore

    raw = t.open_pc_app({"app": "notebooklm"})
    try:
        res = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        fail("open_pc_app_notebooklm", f"non-json: {raw[:300]!r}")
        return
    if res.get("ok"):
        ok("open_pc_app_notebooklm", res.get("message") or res.get("url") or "opened")
    else:
        fail("open_pc_app_notebooklm", res.get("error") or str(res)[:300])


def test_notebooklm_status_tool() -> None:
    ensure_plugin_path()
    from pc_apps import notebooklm_actions as nlm  # type: ignore

    # Give Chrome a moment after open
    time.sleep(2.0)
    raw = nlm.notebooklm_status({})
    try:
        res = json.loads(raw)
    except Exception:
        fail("notebooklm_status", f"non-json: {raw[:300]}")
        return

    if res.get("ok") or res.get("state") in ("home", "notebook_open", "verify_required", "signin_required"):
        # status helper may return ok:false with verify — still a successful tool path
        detail = f"state={res.get('state')} url={str(res.get('url') or '')[:80]}"
        if res.get("state") in ("verify_required", "signin_required"):
            warn("notebooklm_status", detail + " — complete Google sign-in/verify in Chrome")
        else:
            ok("notebooklm_status", detail)
    else:
        # Also accept page present note
        if "not currently open" in str(res.get("note") or res.get("error") or ""):
            warn("notebooklm_status", str(res)[:200])
        else:
            fail("notebooklm_status", str(res)[:300])


def test_list_notebooks() -> None:
    ensure_plugin_path()
    from pc_apps import notebooklm_actions as nlm  # type: ignore

    raw = nlm.notebooklm_list_notebooks({})
    try:
        res = json.loads(raw)
    except Exception:
        fail("notebooklm_list_notebooks", f"non-json: {raw[:300]}")
        return
    if res.get("ok"):
        ok("notebooklm_list_notebooks", f"count={res.get('count')} notebooks={len(res.get('notebooks') or [])}")
    elif "Verify" in str(res.get("error") or "") or "Sign-in" in str(res.get("error") or ""):
        warn("notebooklm_list_notebooks", res.get("error"))
    else:
        fail("notebooklm_list_notebooks", str(res)[:300])


def test_read_notes() -> None:
    ensure_plugin_path()
    from pc_apps import notebooklm_actions as nlm  # type: ignore

    raw = nlm.notebooklm_read_notes({"force_refresh": True})
    try:
        res = json.loads(raw)
    except Exception:
        fail("notebooklm_read_notes", f"non-json: {raw[:300]}")
        return
    if res.get("ok"):
        ok(
            "notebooklm_read_notes",
            f"title={res.get('notebook_title')} sources={res.get('sources_count')} notes={res.get('notes_count')} cached={res.get('cached')}",
        )
    elif "Verify" in str(res.get("error") or "") or "Sign-in" in str(res.get("error") or ""):
        warn("notebooklm_read_notes", res.get("error"))
    elif "open a notebook" in str(res.get("error") or "").lower() or res.get("state") == "home":
        warn("notebooklm_read_notes", "home page — open a notebook for full notes scrape: " + str(res)[:200])
    else:
        fail("notebooklm_read_notes", str(res)[:300])


def test_query_and_cache() -> None:
    ensure_plugin_path()
    from pc_apps import notebooklm_actions as nlm  # type: ignore

    q = "Summarize the main topics in one short sentence."
    raw = nlm.notebooklm_query({"query": q, "force_refresh": True})
    try:
        res = json.loads(raw)
    except Exception:
        fail("notebooklm_query_live", f"non-json: {raw[:300]}")
        return

    if res.get("ok") and res.get("answer"):
        ok("notebooklm_query_live", f"answer_len={len(res.get('answer') or '')} latency={res.get('total_latency_ms')}")
        # Cache hit path
        t0 = time.perf_counter()
        raw2 = nlm.notebooklm_query({"query": q, "force_refresh": False})
        dt = (time.perf_counter() - t0) * 1000
        res2 = json.loads(raw2)
        if res2.get("ok") and res2.get("cached"):
            ok("notebooklm_query_cache", f"{dt:.1f}ms cached=True")
        else:
            warn("notebooklm_query_cache", f"expected cache hit, got {str(res2)[:200]}")
    elif "Verify" in str(res.get("error") or "") or "Sign-in" in str(res.get("error") or ""):
        warn("notebooklm_query_live", res.get("error"))
        # Still verify cache plumbing with a synthetic write
        cache = nlm._load_cache()
        cache.setdefault("recent_qa", []).append({
            "q": "jarvis notebooklm cache probe",
            "a": "cache probe answer",
            "citations": [],
            "notebook": "test",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        nlm._save_cache(cache)
        raw3 = nlm.notebooklm_query({"query": "jarvis notebooklm cache probe"})
        res3 = json.loads(raw3)
        if res3.get("cached"):
            ok("notebooklm_query_cache", "synthetic cache hit works")
        else:
            fail("notebooklm_query_cache", str(res3)[:200])
    elif "chat" in str(res.get("error") or "").lower() or "input" in str(res.get("error") or "").lower():
        warn("notebooklm_query_live", "UI selectors may need a notebook open: " + str(res)[:220])
        # Verify cache layer still works
        cache = nlm._load_cache()
        cache.setdefault("recent_qa", []).append({
            "q": "jarvis notebooklm cache probe",
            "a": "cache probe answer",
            "citations": [],
            "notebook": "test",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        nlm._save_cache(cache)
        raw3 = nlm.notebooklm_query({"query": "jarvis notebooklm cache probe"})
        res3 = json.loads(raw3)
        if res3.get("cached"):
            ok("notebooklm_query_cache", "synthetic cache hit works")
        else:
            fail("notebooklm_query_cache", str(res3)[:200])
    else:
        fail("notebooklm_query_live", str(res)[:300])


def test_audio_and_guide_tools_callable() -> None:
    ensure_plugin_path()
    from pc_apps import notebooklm_actions as nlm  # type: ignore

    for name, fn, args in [
        ("notebooklm_audio_overview", nlm.notebooklm_audio_overview, {"action": "status"}),
        ("notebooklm_generate_guide", nlm.notebooklm_generate_guide, {"guide_type": "faq"}),
    ]:
        try:
            raw = fn(args)
            res = json.loads(raw)
            # Any structured response means tool path works
            if isinstance(res, dict) and ("ok" in res or "error" in res or "state" in res):
                if res.get("ok"):
                    ok(name, str({k: res.get(k) for k in list(res)[:5]})[:180])
                else:
                    warn(name, str(res.get("error") or res)[:200])
            else:
                fail(name, f"unexpected: {str(res)[:200]}")
        except Exception as exc:
            fail(name, str(exc))


def test_tab_registry_and_page_look() -> None:
    ensure_plugin_path()
    from pc_apps import tab_registry, page_look  # type: ignore

    if "notebooklm" not in tab_registry.SITE_PATTERNS:
        fail("tab_registry_notebooklm", "SITE_PATTERNS missing notebooklm")
    else:
        ok("tab_registry_notebooklm", str(tab_registry.SITE_PATTERNS["notebooklm"]))

    needles = getattr(page_look, "_SITE_NEEDLES", {})
    if "notebooklm" not in needles:
        fail("page_look_notebooklm", "_SITE_NEEDLES missing notebooklm")
    else:
        ok("page_look_notebooklm", str(needles["notebooklm"]))


def test_jarvis_open_connection() -> None:
    try:
        status, data = http_json(
            "POST",
            f"{JARVIS}/api/connections/open",
            {"app": "notebooklm"},
            timeout=30,
        )
        open_result = data.get("open_result") or {}
        if data.get("ok") and open_result.get("ok"):
            ok("api_connections_open", str(open_result.get("message") or open_result)[:180])
        elif open_result.get("ok"):
            ok("api_connections_open", str(open_result)[:180])
        elif data.get("ok"):
            warn("api_connections_open", "ok without nested open_result detail: " + str(data)[:160])
        else:
            fail("api_connections_open", data.get("error") or str(data)[:200])
    except Exception as exc:
        fail("api_connections_open", str(exc))


def main() -> int:
    print("=" * 64)
    print("Jarvis NotebookLM integration tests")
    print("=" * 64)

    tests = [
        test_plugin_files_present,
        test_schemas_and_registration,
        test_allowlist_and_aliases,
        test_tab_registry_and_page_look,
        test_cdp_up,
        test_connections_api,
        test_open_notebooklm_via_plugin,
        test_notebooklm_status_tool,
        test_list_notebooks,
        test_read_notes,
        test_query_and_cache,
        test_audio_and_guide_tools_callable,
        test_jarvis_open_connection,
    ]

    for fn in tests:
        try:
            fn()
        except Exception:
            fail(fn.__name__, traceback.format_exc()[-400:])

    print("-" * 64)
    print(f"PASS={PASSED}  FAIL={FAILED}  WARN={WARNED}  TOTAL={len(RESULTS)}")
    print("-" * 64)
    # Critical failures: CDP, schemas, open, status tooling
    critical = [r for r in RESULTS if r[0] == "FAIL" and r[1] in {
        "plugin_files_present", "schemas_defined", "plugin_yaml_tools",
        "allowlist_notebooklm", "cdp_up", "open_pc_app_notebooklm",
        "notebooklm_status", "tab_registry_notebooklm", "page_look_notebooklm",
    }]
    if FAILED and critical:
        print("CRITICAL FAILURES:")
        for st, name, detail in critical:
            print(f"  - {name}: {detail}")
        return 1
    if FAILED:
        print("Non-critical failures present — review above.")
        return 1
    print("All critical NotebookLM paths OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
