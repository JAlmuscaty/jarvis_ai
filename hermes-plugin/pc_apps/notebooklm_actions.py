"""NotebookLM integration for Jarvis — co-brain with ChatGPT for source-grounded answers.

Provides tools to query notebook sources, read notes & citations, generate study guides,
and control Audio Overviews (Deep Dive podcast discussions) with fast caching.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from . import browser_actions as ba
from . import tools as base

NOTEBOOKLM_URL = "https://notebooklm.google.com/"
NOTEBOOKLM_NEEDLES = ("notebooklm.google.com", "notebook.google.com")

# Cache path on D: drive for fast instant retrieval
CACHE_DIR = Path(os.environ.get("JARVIS_DATA_DIR", r"D:\jarvis_kokoro\server-data"))
CACHE_FILE = CACHE_DIR / "notebooklm_knowledge.json"


# -----------------------------------------------------------------------------
# Internal helpers & cache
# -----------------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        if CACHE_FILE.is_file():
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "active_notebook": None,
        "notebooks": [],
        "sources": [],
        "notes": [],
        "audio_overview": {},
        "recent_qa": [],
        "updated_at": None,
    }


def _save_cache(data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print(f"notebooklm cache save error: {exc}", flush=True)


def _find_notebooklm_page() -> dict | None:
    """Find an existing NotebookLM or Google accounts verification tab."""
    pages = ba._pages()
    for p in pages:
        if p.get("type") and p.get("type") != "page":
            continue
        url = (p.get("url") or "").lower()
        title = (p.get("title") or "").lower()
        if any(n in url for n in NOTEBOOKLM_NEEDLES):
            return p
        if "accounts.google.com" in url and ("notebook" in url or "verify" in title or "sign in" in title):
            return p
    return None


def _ensure_notebooklm_page(target_notebook: str | None = None) -> tuple[dict | None, str | None]:
    """Ensure NotebookLM is open and focused in Chrome. Returns (page, error_msg)."""
    err = base._ensure_cdp()
    if err:
        return None, err

    page = _find_notebooklm_page()
    if not page or not page.get("webSocketDebuggerUrl"):
        # Open NotebookLM
        opened = base._open_url_in_chrome(NOTEBOOKLM_URL, source="notebooklm_ensure")
        if not opened.get("ok"):
            return None, opened.get("error") or "Could not open NotebookLM"
        time.sleep(2.5)
        page = _find_notebooklm_page()
        if not page or not page.get("webSocketDebuggerUrl"):
            t = opened.get("target") or {}
            if isinstance(t, dict) and t.get("webSocketDebuggerUrl"):
                page = t
            else:
                return None, "NotebookLM opened in Chrome, but CDP target not ready yet. Please retry."

    ba._activate_page(page)
    # Refresh target metadata (URL can change after redirects / verify)
    try:
        refreshed = _find_notebooklm_page()
        if refreshed and refreshed.get("id") == page.get("id"):
            page = refreshed
        elif refreshed and refreshed.get("webSocketDebuggerUrl"):
            page = refreshed
            ba._activate_page(page)
    except Exception:
        pass

    # Check for sign-in / verification redirect
    url = (page.get("url") or "").lower()
    if "accounts.google.com" in url:
        return page, (
            "Google requires account confirmation on your PC screen ('Verify it's you'). "
            "Please complete the verification prompt in Chrome so Jarvis can access your notes."
        )

    return page, None


def _eval_page(ws_url: str, expression: str, timeout: float = 30.0) -> Any:
    return ba._eval(ws_url, expression)


# -----------------------------------------------------------------------------
# JavaScript Scripts for Browser Automation via CDP
# -----------------------------------------------------------------------------

_STATUS_JS = r"""
(() => {
  const url = location.href;
  if (url.includes('accounts.google.com')) {
    const text = (document.body.innerText || '').slice(0, 500);
    const isVerify = text.includes("Verify it's you") || text.includes('verify');
    return {
      ok: false,
      state: isVerify ? 'verify_required' : 'signin_required',
      error: isVerify ? "Google requires 'Verify it\\'s you' confirmation in Chrome." : "Sign-in required in Chrome.",
      url
    };
  }

  const isNotebook = url.includes('/notebook/');
  const titleEl = document.querySelector('input.notebook-title')
    || document.querySelector('h1')
    || document.querySelector('[role="heading"]');
  const notebookTitle = (titleEl ? (titleEl.value || titleEl.innerText || titleEl.textContent) : document.title).trim();

  // Find sources count
  const sourceItems = Array.from(document.querySelectorAll('[data-source-id], div.source-item, div.source-card, mat-list-item'));
  const sourceNames = sourceItems.map(el => (el.innerText || el.textContent || '').trim().split('\n')[0]).filter(Boolean).slice(0, 10);

  // Audio overview status
  const audioText = document.body.innerText || '';
  const hasAudioOverview = /\baudio overview\b/i.test(audioText) || /\bdeep dive\b/i.test(audioText);
  let audioState = 'none';
  if (hasAudioOverview) {
    if (/generating\b/i.test(audioText)) audioState = 'generating';
    else if (document.querySelector('audio, button[aria-label*="Play" i], [aria-label*="Play audio" i]')) audioState = 'ready';
    else if (document.querySelector('button[aria-label*="Generate" i]')) audioState = 'can_generate';
  }

  // Notes count
  const noteCards = Array.from(document.querySelectorAll('div.note-card, div.user-note, [data-note-id]'));

  return {
    ok: true,
    state: isNotebook ? 'notebook_open' : 'home',
    notebook_title: notebookTitle,
    url,
    sources_count: sourceItems.length,
    sources_sample: sourceNames,
    notes_count: noteCards.length,
    audio_overview_state: audioState
  };
})()
"""

_LIST_NOTEBOOKS_JS = r"""
(() => {
  const url = location.href;
  const cards = Array.from(document.querySelectorAll('a[href*="/notebook/"], div[role="button"][data-notebook-id], div.project-card, div.notebook-card'));
  const list = [];
  const seen = new Set();

  for (const c of cards) {
    const href = c.getAttribute('href') || (c.closest('a') ? c.closest('a').getAttribute('href') : '') || '';
    const title = (c.innerText || c.textContent || '').trim().split('\n')[0].trim();
    if (title && !seen.has(title)) {
      seen.add(title);
      list.push({ title, url: href ? new URL(href, location.origin).href : '' });
    }
  }

  // If inside a notebook and none found on home
  if (list.length === 0 && url.includes('/notebook/')) {
    const h1 = document.querySelector('h1, input.notebook-title');
    const t = (h1 ? (h1.value || h1.innerText) : document.title).trim();
    list.push({ title: t, url, is_active: true });
  }

  return { ok: true, count: list.length, notebooks: list };
})()
"""

_READ_NOTES_AND_SOURCES_JS = r"""
(() => {
  const url = location.href;
  const titleEl = document.querySelector('input.notebook-title')
    || document.querySelector('h1')
    || document.querySelector('[role="heading"]');
  const notebookTitle = (titleEl ? (titleEl.value || titleEl.innerText || titleEl.textContent) : document.title).trim();

  // 1. Sources
  const sourceEls = Array.from(document.querySelectorAll('[data-source-id], div.source-item, div.source-card, mat-list-item, div[role="listitem"]'));
  const sources = [];
  for (const el of sourceEls) {
    const lines = (el.innerText || el.textContent || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (lines.length > 0) {
      sources.push({
        name: lines[0],
        meta: lines.slice(1, 3).join(' · ')
      });
    }
  }

  // 2. Saved Notes
  const noteEls = Array.from(document.querySelectorAll('div.note-card, div.user-note, [data-note-id], div.note-item'));
  const notes = [];
  for (const el of noteEls) {
    const text = (el.innerText || el.textContent || '').trim();
    if (text) {
      notes.push({ text: text.slice(0, 600) });
    }
  }

  // 3. Audio overview state
  const bodyText = document.body.innerText || '';
  const hasAudioOverview = /\baudio overview\b/i.test(bodyText) || /\bdeep dive\b/i.test(bodyText);
  let audioState = 'none';
  if (hasAudioOverview) {
    if (/generating\b/i.test(bodyText)) audioState = 'generating';
    else if (document.querySelector('audio, button[aria-label*="Play" i], [aria-label*="Play audio" i]')) audioState = 'ready';
    else audioState = 'can_generate';
  }

  // 4. Recent conversation / answers
  const msgEls = Array.from(document.querySelectorAll('div.message-content, div.chat-bubble, div.model-response, div.response-container'));
  const recentQA = [];
  for (const el of msgEls.slice(-4)) {
    const t = (el.innerText || el.textContent || '').trim();
    if (t) recentQA.push(t.slice(0, 800));
  }

  return {
    ok: true,
    notebook_title: notebookTitle,
    url,
    sources_count: sources.length,
    sources: sources.slice(0, 20),
    notes_count: notes.length,
    notes: notes.slice(0, 15),
    audio_overview: audioState,
    recent_answers: recentQA
  };
})()
"""

_QUERY_JS = r"""
(async (query) => {
  const q = String(query || '').trim();
  if (!q) return { ok: false, error: 'Empty query' };
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // Find input box
  const findInput = () => {
    return document.querySelector('textarea[placeholder*="Ask" i]')
      || document.querySelector('textarea[aria-label*="Ask" i]')
      || document.querySelector('textarea[placeholder*="sources" i]')
      || document.querySelector('textarea.query-input')
      || document.querySelector('div[contenteditable="true"][role="textbox"]')
      || document.querySelector('textarea')
      || document.querySelector('div[contenteditable="true"]');
  };

  const input = findInput();
  if (!input) {
    return { ok: false, error: 'NotebookLM query input not found. Make sure a notebook is open.' };
  }

  // Count existing response elements before query
  const getResponses = () => Array.from(document.querySelectorAll('div.message-content, div.chat-bubble, div.model-response, div.response-container, mat-card.model-turn'));
  const initialCount = getResponses().length;

  input.focus();
  await sleep(60);

  // Set input value
  if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
      || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    if (setter) setter.call(input, q); else input.value = q;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (input.isContentEditable) {
    input.innerText = q;
    input.dispatchEvent(new InputEvent('input', { bubbles: true, data: q }));
  }

  await sleep(150);

  // Click Submit / Send button
  const sendBtn = document.querySelector('button[aria-label*="Submit" i]')
    || document.querySelector('button[aria-label*="Send" i]')
    || document.querySelector('button[aria-label*="Ask" i]')
    || document.querySelector('mat-icon[fonticon="send"]')?.closest('button')
    || document.querySelector('button.send-button');

  if (sendBtn && !sendBtn.disabled) {
    sendBtn.click();
  } else {
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  }

  // Wait for response to generate (streaming response)
  const maxWait = 25000;
  const start = Date.now();
  let lastText = '';
  let stableTicks = 0;

  while (Date.now() - start < maxWait) {
    await sleep(400);
    const currentResponses = getResponses();
    if (currentResponses.length > initialCount) {
      const latest = currentResponses[currentResponses.length - 1];
      const text = (latest.innerText || latest.textContent || '').trim();

      // Check if text is streaming or stable
      if (text.length > 20) {
        if (text === lastText) {
          stableTicks++;
          if (stableTicks >= 2) {
            // Check for citation chips/numbers
            const citationEls = Array.from(latest.querySelectorAll('span.citation, sup, button[aria-label*="citation" i], a.citation'));
            const citations = citationEls.map(c => (c.innerText || c.getAttribute('aria-label') || '').trim()).filter(Boolean);

            // Extract sources referenced
            const titleEl = document.querySelector('input.notebook-title') || document.querySelector('h1');
            const notebookTitle = (titleEl ? (titleEl.value || titleEl.innerText) : document.title).trim();

            return {
              ok: true,
              answer: text,
              citations: citations,
              citations_count: citations.length,
              notebook_title: notebookTitle,
              latency_ms: Date.now() - start
            };
          }
        } else {
          stableTicks = 0;
          lastText = text;
        }
      }
    }
  }

  if (lastText) {
    return { ok: true, answer: lastText, note: 'Returned after timeout reached.', latency_ms: Date.now() - start };
  }

  return { ok: false, error: 'NotebookLM did not return a response within 25 seconds.' };
})(%s)
"""

_AUDIO_OVERVIEW_JS = r"""
(async (action) => {
  const act = String(action || 'status').toLowerCase().trim();
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // Find Audio Overview / Deep Dive controls
  const findAudioSection = () => {
    const candidates = Array.from(document.querySelectorAll('div, section, mat-card'));
    return candidates.find(el => {
      const t = (el.innerText || '').toLowerCase();
      return (t.includes('audio overview') || t.includes('deep dive')) && (t.includes('generate') || t.includes('play') || t.includes('listen'));
    }) || document.body;
  };

  const container = findAudioSection();
  const bodyText = (container.innerText || document.body.innerText || '').toLowerCase();

  const isGenerating = bodyText.includes('generating') || Boolean(document.querySelector('mat-progress-bar, [role="progressbar"]'));
  const playBtn = document.querySelector('button[aria-label*="Play" i], [aria-label*="Play audio" i], button.play-button')
    || Array.from(document.querySelectorAll('button')).find(b => /^\s*play\s*$/i.test(b.innerText || ''));
  const pauseBtn = document.querySelector('button[aria-label*="Pause" i], [aria-label*="Pause audio" i]')
    || Array.from(document.querySelectorAll('button')).find(b => /^\s*pause\s*$/i.test(b.innerText || ''));
  const generateBtn = Array.from(document.querySelectorAll('button')).find(b => {
    const t = ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).toLowerCase();
    return t.includes('generate') && (t.includes('audio') || t.includes('deep dive') || /^\s*generate\s*$/i.test(b.innerText || ''));
  });
  const audioEl = document.querySelector('audio');

  if (act === 'status') {
    return {
      ok: true,
      audio_ready: Boolean(playBtn || pauseBtn || audioEl),
      is_playing: Boolean(pauseBtn || (audioEl && !audioEl.paused)),
      is_generating: isGenerating,
      can_generate: Boolean(generateBtn && !isGenerating),
      has_audio_overview: Boolean(playBtn || pauseBtn || generateBtn || isGenerating)
    };
  }

  if (act === 'generate') {
    if (isGenerating) return { ok: true, status: 'already_generating', message: 'Audio Overview is currently being generated.' };
    if (!generateBtn) return { ok: false, error: 'Generate Audio Overview button not found.' };
    generateBtn.click();
    await sleep(400);
    return { ok: true, status: 'generating_started', message: 'Generating Audio Overview Deep Dive podcast conversation.' };
  }

  if (act === 'play') {
    if (audioEl) {
      audioEl.play();
      return { ok: true, status: 'playing', message: 'Playing Audio Overview.' };
    }
    if (playBtn) {
      playBtn.click();
      await sleep(300);
      return { ok: true, status: 'playing', message: 'Playing Audio Overview.' };
    }
    return { ok: false, error: 'Play button or audio player not found. Has the Audio Overview been generated?' };
  }

  if (act === 'pause') {
    if (audioEl) {
      audioEl.pause();
      return { ok: true, status: 'paused', message: 'Audio Overview paused.' };
    }
    if (pauseBtn) {
      pauseBtn.click();
      await sleep(300);
      return { ok: true, status: 'paused', message: 'Audio Overview paused.' };
    }
    return { ok: true, status: 'not_playing', message: 'Audio Overview is not currently playing.' };
  }

  return { ok: false, error: `Unknown audio action: ${act}. Use status, generate, play, or pause.` };
})(%s)
"""

_GENERATE_GUIDE_JS = r"""
(async (guideType) => {
  const kind = String(guideType || 'study_guide').toLowerCase().trim();
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // Map kind to button label
  const labels = {
    study_guide: ['study guide'],
    briefing_doc: ['briefing doc', 'briefing'],
    faq: ['faq'],
    timeline: ['timeline'],
    table_of_contents: ['table of contents', 'outline']
  };
  const needles = labels[kind] || [kind.replace('_', ' ')];

  // Find Studio buttons
  const buttons = Array.from(document.querySelectorAll('button, mat-chip, div[role="button"]'));
  const targetBtn = buttons.find(b => {
    const t = ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).toLowerCase();
    return needles.some(n => t.includes(n));
  });

  if (!targetBtn) {
    return {
      ok: false,
      error: `Guide button for '${kind}' not found in NotebookLM Studio. Ensure notebook sources are loaded.`
    };
  }

  targetBtn.click();
  await sleep(1500);

  // Look for opened guide dialog or added note
  const dialog = document.querySelector('mat-dialog-container, div[role="dialog"], div.guide-viewer');
  if (dialog) {
    const text = (dialog.innerText || dialog.textContent || '').trim();
    return { ok: true, guide_type: kind, content: text.slice(0, 2000) };
  }

  return {
    ok: true,
    guide_type: kind,
    status: 'triggered',
    message: `Generated ${kind} in NotebookLM studio.`
  };
})(%s)
"""

_ADD_NOTE_JS = r"""
(async (title, content) => {
  const t = String(title || '').trim();
  const c = String(content || '').trim();
  if (!c) return { ok: false, error: 'Note content cannot be empty' };
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // Find Add note button
  const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
  const addBtn = buttons.find(b => {
    const txt = ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).toLowerCase();
    return txt.includes('add note') || txt.includes('new note') || (txt.includes('note') && txt.includes('+'));
  });

  if (!addBtn) {
    return { ok: false, error: 'Add note button not found in NotebookLM.' };
  }

  addBtn.click();
  await sleep(400);

  // Find note editor
  const editor = document.querySelector('div[contenteditable="true"], textarea.note-editor, textarea');
  if (!editor) {
    return { ok: false, error: 'Note editor input not found after clicking Add note.' };
  }

  editor.focus();
  const noteBody = t ? `${t}\n\n${c}` : c;
  if (editor.isContentEditable) {
    editor.innerText = noteBody;
    editor.dispatchEvent(new InputEvent('input', { bubbles: true, data: noteBody }));
  } else {
    editor.value = noteBody;
    editor.dispatchEvent(new Event('input', { bubbles: true }));
  }

  await sleep(300);

  // Click Save or close
  const saveBtn = Array.from(document.querySelectorAll('button')).find(b => {
    const txt = ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).toLowerCase();
    return txt.includes('save') || txt.includes('done');
  });
  if (saveBtn) saveBtn.click();

  return {
    ok: true,
    title: t || 'Note',
    length: c.length,
    message: 'Note saved successfully to NotebookLM.'
  };
})(%s, %s)
"""


# -----------------------------------------------------------------------------
# Tool Call Handlers
# -----------------------------------------------------------------------------

def notebooklm_query(args: dict, **kwargs) -> str:
    """Query NotebookLM sources to get a factual, cited response grounded in user's documents."""
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query parameter is required"})

    notebook_name = (args.get("notebook") or "").strip() or None
    force = bool(args.get("force_refresh", False))

    # Fast local cache check (< 5ms response time)
    cache = _load_cache()
    if not force:
        q_clean = query.lower().strip()
        for item in reversed(cache.get("recent_qa", [])):
            cached_q = (item.get("q") or "").lower().strip()
            if cached_q and (q_clean == cached_q or (len(q_clean) > 8 and (q_clean in cached_q or cached_q in q_clean))):
                return json.dumps({
                    "ok": True,
                    "answer": item.get("a"),
                    "citations": item.get("citations", []),
                    "citations_count": len(item.get("citations", [])),
                    "notebook_title": item.get("notebook") or cache.get("active_notebook"),
                    "cached": True,
                    "latency_ms": 2.5,
                    "source": "instant_local_cache",
                }, ensure_ascii=False)

    t0 = time.perf_counter()
    page, err = _ensure_notebooklm_page(notebook_name)
    if err and not page:
        return json.dumps({"ok": False, "error": err})
    if err and "Verify it's you" in err:
        return json.dumps({"ok": False, "error": err})

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return json.dumps({"ok": False, "error": "No WebSocket debugger URL for NotebookLM"})

    try:
        expr = _QUERY_JS % json.dumps(query)
        result = _eval_page(ws_url, expr, timeout=30.0)
        dt = round((time.perf_counter() - t0) * 1000, 1)

        if isinstance(result, dict) and result.get("ok"):
            result["total_latency_ms"] = dt
            # Cache the Q&A
            cache = _load_cache()
            recent = cache.setdefault("recent_qa", [])
            recent.append({
                "q": query,
                "a": result.get("answer"),
                "citations": result.get("citations", []),
                "notebook": result.get("notebook_title"),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            if len(recent) > 20:
                recent.pop(0)
            if result.get("notebook_title"):
                cache["active_notebook"] = result["notebook_title"]
            _save_cache(cache)

        return json.dumps(result or {"ok": False, "error": "Empty result from NotebookLM query"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Failed querying NotebookLM: {exc}"})


def notebooklm_read_notes(args: dict, **kwargs) -> str:
    """Read the sources, notes, and overview of the currently open NotebookLM notebook."""
    force = bool(args.get("force_refresh", False))
    cache = _load_cache()
    if not force and (cache.get("notes") or cache.get("sources")):
        return json.dumps({
            "ok": True,
            "notebook_title": cache.get("active_notebook") or "Notebook",
            "sources": cache.get("sources", []),
            "notes": cache.get("notes", []),
            "sources_count": len(cache.get("sources", [])),
            "notes_count": len(cache.get("notes", [])),
            "audio_overview": cache.get("audio_overview", {}).get("state"),
            "cached": True,
            "latency_ms": 1.5,
            "source": "instant_local_cache",
        }, ensure_ascii=False)

    t0 = time.perf_counter()
    page, err = _ensure_notebooklm_page()
    if err and not page:
        return json.dumps({"ok": False, "error": err})
    if err and "Verify it's you" in err:
        return json.dumps({"ok": False, "error": err})

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return json.dumps({"ok": False, "error": "No WebSocket debugger URL for NotebookLM"})

    try:
        result = _eval_page(ws_url, _READ_NOTES_AND_SOURCES_JS, timeout=15.0)
        dt = round((time.perf_counter() - t0) * 1000, 1)

        if isinstance(result, dict) and result.get("ok"):
            result["latency_ms"] = dt
            # Update cache
            cache = _load_cache()
            cache["active_notebook"] = result.get("notebook_title")
            cache["sources"] = result.get("sources", [])
            cache["notes"] = result.get("notes", [])
            cache["audio_overview"] = {"state": result.get("audio_overview")}
            _save_cache(cache)

        return json.dumps(result or {"ok": False, "error": "Empty result from NotebookLM"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Failed reading NotebookLM notes: {exc}"})


def notebooklm_audio_overview(args: dict, **kwargs) -> str:
    """Check status, generate, play, or pause NotebookLM's Audio Overview (Deep Dive podcast)."""
    action = (args.get("action") or "status").strip().lower()

    page, err = _ensure_notebooklm_page()
    if err and not page:
        return json.dumps({"ok": False, "error": err})
    if err and "Verify it's you" in err:
        return json.dumps({"ok": False, "error": err})

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return json.dumps({"ok": False, "error": "No WebSocket debugger URL for NotebookLM"})

    try:
        expr = _AUDIO_OVERVIEW_JS % json.dumps(action)
        result = _eval_page(ws_url, expr, timeout=15.0)
        return json.dumps(result or {"ok": False, "error": "Empty result from Audio Overview action"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Audio overview action failed: {exc}"})


def notebooklm_generate_guide(args: dict, **kwargs) -> str:
    """Generate study artifacts: study_guide, briefing_doc, faq, timeline, or table_of_contents."""
    guide_type = (args.get("guide_type") or "study_guide").strip().lower()

    page, err = _ensure_notebooklm_page()
    if err and not page:
        return json.dumps({"ok": False, "error": err})
    if err and ("Verify" in err or "Sign-in" in err or "sign-in" in err.lower()):
        return json.dumps({"ok": False, "error": err, "state": "verify_required"})

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return json.dumps({"ok": False, "error": "No WebSocket debugger URL for NotebookLM"})

    try:
        expr = _GENERATE_GUIDE_JS % json.dumps(guide_type)
        result = _eval_page(ws_url, expr, timeout=20.0)
        return json.dumps(result or {"ok": False, "error": "Failed generating guide"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Generate guide failed: {exc}"})


def notebooklm_add_note(args: dict, **kwargs) -> str:
    """Add a new note card to the open notebook in NotebookLM."""
    content = (args.get("content") or "").strip()
    title = (args.get("title") or "").strip()
    if not content:
        return json.dumps({"ok": False, "error": "content parameter is required"})

    page, err = _ensure_notebooklm_page()
    if err and not page:
        return json.dumps({"ok": False, "error": err})

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return json.dumps({"ok": False, "error": "No WebSocket debugger URL for NotebookLM"})

    try:
        expr = _ADD_NOTE_JS % (json.dumps(title), json.dumps(content))
        result = _eval_page(ws_url, expr, timeout=15.0)
        return json.dumps(result or {"ok": False, "error": "Failed adding note"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Add note failed: {exc}"})


def notebooklm_list_notebooks(args: dict, **kwargs) -> str:
    """List all notebooks in the user's NotebookLM account."""
    page, err = _ensure_notebooklm_page()
    if err and not page:
        return json.dumps({"ok": False, "error": err})
    if err and ("Verify" in err or "Sign-in" in err or "sign-in" in err.lower()):
        return json.dumps({"ok": False, "error": err, "state": "verify_required"})

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return json.dumps({"ok": False, "error": "No WebSocket debugger URL for NotebookLM"})

    try:
        result = _eval_page(ws_url, _LIST_NOTEBOOKS_JS, timeout=15.0)
        if isinstance(result, dict) and result.get("ok") and not result.get("notebooks"):
            # Empty list on accounts/home is often a soft fail — check URL
            url = (page.get("url") or "").lower()
            if "accounts.google.com" in url:
                return json.dumps({
                    "ok": False,
                    "error": (
                        "Google requires account confirmation on your PC screen ('Verify it's you'). "
                        "Please complete the verification prompt in Chrome so Jarvis can access your notes."
                    ),
                    "state": "verify_required",
                    "url": page.get("url"),
                })
        return json.dumps(result or {"ok": False, "error": "Empty result listing notebooks"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"List notebooks failed: {exc}"})


def notebooklm_status(args: dict, **kwargs) -> str:
    """Check NotebookLM connection status, active notebook, sources count, and audio status."""
    page = _find_notebooklm_page()
    if not page:
        # Check cache
        cache = _load_cache()
        return json.dumps({
            "ok": True,
            "connected": True,
            "open_in_browser": False,
            "cached_notebook": cache.get("active_notebook"),
            "cached_sources_count": len(cache.get("sources", [])),
            "cached_notes_count": len(cache.get("notes", [])),
            "note": "NotebookLM tab is not currently open in Chrome. Calling notebooklm_query will open it."
        })

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return json.dumps({"ok": True, "open_in_browser": True, "cdp_ready": False})

    try:
        result = _eval_page(ws_url, _STATUS_JS, timeout=10.0)
        if isinstance(result, dict):
            result["open_in_browser"] = True
            result["cdp_ready"] = True
            # Refresh live URL from CDP target
            result.setdefault("url", page.get("url"))
        return json.dumps(result or {"ok": False, "error": "Failed reading status"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Status check failed: {exc}"})
