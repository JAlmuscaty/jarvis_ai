"""Local vault connectors — Obsidian-style Markdown + Jarvis Second Brain."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import get_link, load_index, save_index, set_link


def link_obsidian(vault_path: str) -> dict[str, Any]:
    path = Path(vault_path).expanduser().resolve()
    if not path.is_dir():
        return {"ok": False, "error": f"Vault path not found: {path}"}
    # Sanity: look for at least one md file or .obsidian folder
    has_md = any(path.rglob("*.md"))
    has_obs = (path / ".obsidian").is_dir()
    if not has_md and not has_obs:
        return {"ok": False, "error": "Folder does not look like an Obsidian vault (no .md files or .obsidian/)."}

    set_link("obsidian", linked=True, meta={"vault_path": str(path), "auth": "local_vault"})
    indexed = reindex_obsidian()
    return {
        "ok": True,
        "vault_path": str(path),
        "item_count": indexed.get("count", 0),
        "message": (
            f"Linked Obsidian vault at {path}. Jarvis can search and read notes without opening Obsidian."
        ),
    }


def reindex_obsidian(limit: int = 2000) -> dict[str, Any]:
    link = get_link("obsidian") or {}
    vault = Path(str(link.get("vault_path") or ""))
    if not vault.is_dir():
        return {"ok": False, "error": "Obsidian vault not linked or path missing."}

    notes = []
    for p in vault.rglob("*.md"):
        if any(part.startswith(".") for part in p.parts):
            # skip .obsidian and other dot dirs, but allow files
            if ".obsidian" in p.parts or ".trash" in p.parts or ".git" in p.parts:
                continue
        try:
            rel = str(p.relative_to(vault)).replace("\\", "/")
            text = p.read_text(encoding="utf-8", errors="replace")
            title = p.stem
            # YAML frontmatter title
            fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
            if fm:
                m = re.search(r"(?m)^title:\s*[\"']?(.*?)[\"']?\s*$", fm.group(1))
                if m:
                    title = m.group(1).strip() or title
            notes.append({
                "id": rel,
                "title": title,
                "path": rel,
                "preview": re.sub(r"\s+", " ", text)[:240],
                "chars": len(text),
            })
            if len(notes) >= limit:
                break
        except Exception:
            continue

    save_index("obsidian", {"items": notes, "vault_path": str(vault)})
    set_link("obsidian", linked=True, meta={"vault_path": str(vault), "item_count": len(notes)})
    return {"ok": True, "count": len(notes), "vault_path": str(vault)}


def obsidian_search(query: str, max_results: int = 12) -> dict[str, Any]:
    link = get_link("obsidian") or {}
    vault = Path(str(link.get("vault_path") or ""))
    if not vault.is_dir():
        return {"ok": False, "error": "Obsidian not linked. Connect your vault path first."}

    q = (query or "").strip().lower()
    if not q:
        return {"ok": False, "error": "query required"}

    # Prefer live scan for accuracy (vault can change without reindex)
    hits = []
    for p in vault.rglob("*.md"):
        if ".obsidian" in p.parts or ".trash" in p.parts or ".git" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            rel = str(p.relative_to(vault)).replace("\\", "/")
            blob = (rel + "\n" + text).lower()
            if q not in blob:
                continue
            # score: title match > path > body count
            score = 0
            if q in p.stem.lower():
                score += 10
            if q in rel.lower():
                score += 4
            score += min(blob.count(q), 20)
            # excerpt around first hit
            idx = text.lower().find(q)
            if idx < 0:
                excerpt = text[:200]
            else:
                start = max(0, idx - 60)
                excerpt = text[start: start + 220]
            hits.append({
                "id": rel,
                "title": p.stem,
                "path": rel,
                "score": score,
                "excerpt": re.sub(r"\s+", " ", excerpt).strip(),
            })
        except Exception:
            continue

    hits.sort(key=lambda h: -h["score"])
    hits = hits[: max(1, min(max_results, 30))]
    return {"ok": True, "count": len(hits), "notes": hits, "source": "obsidian_vault"}


def obsidian_read(note_path: str) -> dict[str, Any]:
    link = get_link("obsidian") or {}
    vault = Path(str(link.get("vault_path") or ""))
    if not vault.is_dir():
        return {"ok": False, "error": "Obsidian not linked."}

    rel = note_path.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return {"ok": False, "error": "Invalid path"}
    path = (vault / rel).resolve()
    try:
        path.relative_to(vault.resolve())
    except Exception:
        return {"ok": False, "error": "Path escapes vault"}
    if not path.is_file():
        # try adding .md
        if not rel.endswith(".md"):
            path = (vault / (rel + ".md")).resolve()
    if not path.is_file():
        return {"ok": False, "error": f"Note not found: {rel}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "id": str(path.relative_to(vault)).replace("\\", "/"),
        "title": path.stem,
        "text": text[:20000],
        "source": "obsidian_vault",
    }


def second_brain_search(query: str, brain_path: Path, max_results: int = 15) -> dict[str, Any]:
    try:
        from brain_store import load as brain_load
    except ImportError:
        from server.brain_store import load as brain_load  # type: ignore

    data = brain_load(brain_path)
    ideas = data.get("ideas") or []
    genres = {g["id"]: g for g in data.get("genres") or []}
    q = (query or "").strip().lower()
    hits = []
    for idea in ideas:
        blob = f"{idea.get('title','')} {idea.get('description') or ''} {idea.get('purpose') or ''}".lower()
        if q and q not in blob:
            continue
        g = genres.get(idea.get("genre_id")) or {}
        hits.append({
            "id": idea.get("id"),
            "title": idea.get("title"),
            "description": idea.get("description"),
            "purpose": idea.get("purpose") or g.get("purpose"),
            "genre": g.get("name"),
            "color": g.get("color"),
        })
        if len(hits) >= max_results:
            break
    # ensure second_brain always linked
    set_link("second_brain", linked=True, meta={"item_count": len(ideas), "auth": "local"})
    return {"ok": True, "count": len(hits), "ideas": hits, "source": "second_brain"}
