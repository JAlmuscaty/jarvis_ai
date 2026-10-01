"""Render lined-paper pages in a memorized handwriting style (EN/AR, pen/pencil)."""
from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

try:
    from handwriting_store import OUTPUT_DIR, font_path_for, get_profile, has_handwriting
except ImportError:
    from .handwriting_store import OUTPUT_DIR, font_path_for, get_profile, has_handwriting  # type: ignore


def _has_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _ink_rgba(medium: str, style: dict | None = None) -> tuple[int, int, int, int]:
    style = style or {}
    color = str(style.get("ink_color") or "").lower()
    med = (medium or "pen").lower()
    if med == "pencil" or color in ("gray", "grey", "graphite"):
        return (90, 90, 95, 200)
    if color == "blue" or med == "pen":
        return (25, 55, 140, 230)
    if color == "black":
        return (20, 20, 25, 235)
    if med == "marker":
        return (10, 10, 10, 245)
    return (25, 55, 140, 230)


def _load_font(path: Path | None, size: int):
    from PIL import ImageFont

    if path and path.is_file():
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_lines(draw, text: str, font, max_width: int) -> list[str]:
    paragraphs = (text or "").replace("\r\n", "\n").split("\n")
    lines: list[str] = []
    for para in paragraphs:
        if not para.strip():
            lines.append("")
            continue
        # Arabic: wrap by spaces when present; otherwise chunk
        words = para.split(" ") if " " in para else list(para)
        cur = ""
        for w in words:
            piece = w if cur == "" else (cur + (" " if " " in para else "") + w)
            bbox = draw.textbbox((0, 0), piece, font=font)
            if bbox[2] - bbox[0] <= max_width or not cur:
                cur = piece
            else:
                lines.append(cur)
                cur = w
        if cur != "":
            lines.append(cur)
    return lines


def render_handwritten_pages(
    text: str,
    *,
    language: str | None = None,
    medium: str | None = None,
    title: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Create PNG page images that look handwritten. Returns paths + metadata."""
    from PIL import Image, ImageDraw, ImageFilter

    if not has_handwriting():
        return {
            "ok": False,
            "error": "No handwriting memorized yet. Send a photo and say: memorize my handwriting.",
        }

    profile = get_profile(profile_id)
    style = dict((profile or {}).get("style") or {})
    langs = list((profile or {}).get("languages") or [])
    mediums = list((profile or {}).get("mediums") or [])

    lang = (language or "").lower().strip()
    if not lang:
        lang = "ar" if _has_arabic(text) else ("ar" if "ar" in langs and "en" not in langs else "en")
    med = (medium or "").lower().strip()
    if med not in ("pen", "pencil", "marker"):
        med = mediums[0] if mediums and mediums[0] in ("pen", "pencil", "marker") else "pen"

    size_label = str(style.get("size") or "medium").lower()
    base_size = {"small": 36, "medium": 46, "large": 56}.get(size_label, 46)
    if lang.startswith("ar"):
        base_size = int(base_size * 1.05)

    font_path = font_path_for(lang, med)
    font = _load_font(font_path, base_size)
    title_font = _load_font(font_path, max(28, base_size - 6))

    # A4-ish at 150 dpi
    W, H = 1240, 1754
    margin_x, margin_top = 100, 120
    line_gap = int(base_size * 1.75)
    max_w = W - 2 * margin_x
    ink = _ink_rgba(med, style)
    slant = str(style.get("slant") or "upright").lower()
    wobble = 1.6 if str(style.get("pressure") or "") == "light" else 2.4

    # Measure wrap with a throwaway image
    probe = Image.new("RGB", (W, H), (252, 248, 235))
    probe_draw = ImageDraw.Draw(probe)
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "text is required"}
    lines = _wrap_lines(probe_draw, body, font, max_w)
    title_lines = _wrap_lines(probe_draw, title, title_font, max_w) if title else []

    usable_h = H - margin_top - 100
    lines_per_page = max(8, usable_h // line_gap - (2 if title_lines else 0))
    chunks: list[list[str]] = []
    remaining = list(lines)
    first = True
    while remaining or (first and title_lines):
        take = lines_per_page - (len(title_lines) + 1 if first and title_lines else 0)
        take = max(1, take)
        chunk = remaining[:take]
        remaining = remaining[take:]
        chunks.append(chunk)
        first = False
        if not remaining:
            break
    if not chunks:
        chunks = [[]]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_paths: list[str] = []
    rng = random.Random(hash((body[:40], med, lang)) & 0xFFFFFFFF)

    for page_i, chunk in enumerate(chunks):
        img = Image.new("RGB", (W, H), (252, 248, 235))
        draw = ImageDraw.Draw(img)
        # Lined paper
        for y in range(margin_top, H - 60, line_gap):
            draw.line([(margin_x - 20, y), (W - margin_x + 20, y)], fill=(190, 205, 220), width=1)
        # Left margin rule
        draw.line([(margin_x - 30, margin_top - 40), (margin_x - 30, H - 50)], fill=(220, 160, 160), width=2)

        y = margin_top - int(base_size * 0.85)
        if page_i == 0 and title_lines:
            for tl in title_lines:
                _draw_wobbly_line(draw, tl, margin_x, y, title_font, ink, rng, slant, wobble * 0.7, lang)
                y += line_gap
            y += int(line_gap * 0.3)

        for line in chunk:
            if line == "":
                y += line_gap
                continue
            _draw_wobbly_line(draw, line, margin_x, y, font, ink, rng, slant, wobble, lang)
            y += line_gap

        # Slight paper texture
        img = img.filter(ImageFilter.SMOOTH_MORE)
        path = OUTPUT_DIR / f"hw_{profile.get('id') if profile else 'x'}_{page_i+1:02d}.png"
        img.save(path, format="PNG")
        out_paths.append(str(path))

    return {
        "ok": True,
        "pages": out_paths,
        "page_count": len(out_paths),
        "language": lang,
        "medium": med,
        "font": str(font_path) if font_path else None,
        "profile_id": (profile or {}).get("id"),
        "output_dir": str(OUTPUT_DIR),
    }


def _prepare_text(text: str, lang: str) -> str:
    """Shape Arabic for Pillow without libraqm."""
    if not (lang.startswith("ar") or _has_arabic(text)):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _draw_wobbly_line(draw, text, x, y, font, ink, rng, slant, wobble, lang):
    text = _prepare_text(text, lang)
    # Character-ish jitter for Latin; milder for Arabic (connected script)
    if lang.startswith("ar") or _has_arabic(text):
        dx = rng.uniform(-wobble * 0.4, wobble * 0.4)
        dy = rng.uniform(-wobble * 0.5, wobble * 0.5)
        draw.text((x + dx, y + dy), text, font=font, fill=ink)
        return

    cursor = x
    for ch in text:
        dx = rng.uniform(-wobble, wobble)
        dy = rng.uniform(-wobble, wobble)
        if slant == "right":
            dx += 0.8
        elif slant == "left":
            dx -= 0.8
        draw.text((cursor + dx, y + dy), ch, font=font, fill=ink)
        bbox = draw.textbbox((0, 0), ch, font=font)
        cursor += max(1, bbox[2] - bbox[0]) + rng.uniform(-0.4, 0.8)


def pages_to_pdf(page_paths: list[str], pdf_path: Path | None = None) -> Path:
    from PIL import Image

    if not page_paths:
        raise ValueError("no pages")
    images = [Image.open(p).convert("RGB") for p in page_paths]
    out = Path(pdf_path) if pdf_path else (OUTPUT_DIR / "handwriting_doc.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    first, rest = images[0], images[1:]
    first.save(out, "PDF", save_all=True, append_images=rest)
    for im in images:
        im.close()
    return out
