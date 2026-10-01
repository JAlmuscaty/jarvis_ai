"""Fast local essay + slide-deck content for Chrome Docs/Slides (no cloud APIs required).

Uses Ollama when free/fast; otherwise a strong structured template so Jarvis never stalls.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any, Callable

OLLAMA_API = os.environ.get("OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("JARVIS_LAYER1_MODEL", "llama3.2:3b")

# Set by server.py to the main (Layer 2) model: fn(prompt, timeout) -> text | None.
# The small local model is only a fallback — it often times out and writes generic filler.
LLM_COMPLETE: Callable[[str, float], str | None] | None = None


def _llm_json(prompt: str, *, timeout: float = 90.0, num_predict: int = 900) -> dict | None:
    if LLM_COMPLETE is not None:
        try:
            data = _parse_json_obj(LLM_COMPLETE(prompt, timeout))
            if data:
                return data
        except Exception as exc:
            print(f"workspace_content LLM: {exc}", flush=True)
    return _parse_json_obj(_ollama_json(prompt, num_predict=num_predict, timeout=12.0))


def _llm_text(prompt: str, *, timeout: float = 90.0) -> str | None:
    if LLM_COMPLETE is not None:
        try:
            out = (LLM_COMPLETE(prompt, timeout) or "").strip()
            if out:
                return out
        except Exception as exc:
            print(f"workspace_content LLM: {exc}", flush=True)
    return None


def _has_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def extract_slide_count(text: str, default: int = 8) -> int:
    t = text or ""
    m = re.search(r"(?is)\b(\d{1,2})\s*-?\s*slides?\b", t)
    if m:
        n = int(m.group(1))
        return max(3, min(20, n))
    m = re.search(r"(?is)\b(?:exactly|just|only)\s+(\d{1,2})\b", t)
    if m:
        return max(3, min(20, int(m.group(1))))
    return default


def wants_design_suggestions(text: str) -> bool:
    return bool(
        re.search(
            r"(?is)\b("
            r"suggest(?:ions?)?\s+(?:(?:on|for|about|a|an|the|me)\s+)*(?:design|look|style|layout|theme|colors?)|"
            r"(?:design|look|style|theme)\s+suggest|"
            r"what\s+(?:design|look|style|theme)|"
            r"how\s+should\s+(?:it|the\s+(?:slides?|deck|powerpoint))\s+look|"
            r"ideas?\s+for\s+(?:the\s+)?(?:design|look|style)"
            r")\b",
            text or "",
        )
    )


def topic_missing_for_presentation(text: str) -> bool:
    """True when they ask for a deck but give no subject."""
    t = (text or "").strip()
    if not re.search(r"(?is)\b(?:slides?|presentation|powerpoint|deck)\b", t):
        return False
    # Strip command words — if almost nothing remains, topic is missing
    stripped = re.sub(
        r"(?is)\b("
        r"please|can you|jarvis|create|make|build|write|do|a|an|my|the|full|open|new|blank|and|then|"
        r"in|it|there|inside|me|for|one|type|start|"
        r"google|slides?|presentation|powerpoint|deck|on|with|exactly|just|only|"
        r"\d+|slides?|images?|design|look|style|theme|perfect|good"
        r")\b",
        " ",
        t,
    )
    stripped = re.sub(r"\s+", " ", stripped).strip(" .,-:")
    return len(stripped) < 3


def clean_topic(topic: str) -> str:
    """'the character Naruto with 5 slides for my class' -> 'Naruto'."""
    t = (topic or "").strip()
    t = re.sub(r"(?is)\s*\b(?:with|in|using|of)\s+(?:about\s+)?\d{1,2}\s*-?\s*slides?\b", "", t)
    t = re.sub(r"(?is)\s*\b\d{1,2}\s*-?\s*slides?\b", "", t)
    t = re.sub(r"(?is)\s*\b(?:with|and)\s+(?:no|some)?\s*(?:images?|pictures?|photos?)\b", "", t)
    t = re.sub(r"(?is)\s*\b(?:for\s+(?:my|the|a)\s+(?:class|school|teacher|project|homework|presentation))\b.*$", "", t)
    t = re.sub(r"(?is)\s*\b(?:in|inside)\s+(?:it|there|the\s+(?:new|blank)\s+\w+)\s*$", "", t)
    t = re.sub(
        r"(?is)^(?:a|an|the)?\s*(?:specific\s+|famous\s+|fictional\s+|anime\s+|cartoon\s+|movie\s+|game\s+|video\s+game\s+)?"
        r"(?:character|person|superhero|hero|villain|celebrity|player|singer|actor)\s+(?:called|named)?\s*",
        "",
        t,
    )
    return re.sub(r"\s+", " ", t).strip(" .,:-\"'")[:200]


def extract_topic(text: str) -> str:
    return clean_topic(_extract_topic_raw(text)) or _extract_topic_raw(text)


def _extract_topic_raw(text: str) -> str:
    t = (text or "").strip()
    qm = re.search(r"[\"“](.+?)[\"”]", t, re.S)
    if qm and len(qm.group(1).strip()) > 2:
        return qm.group(1).strip()[:300]
    # "presentation for my class about X" — "about/on" names the subject, "for" usually doesn't
    m = re.search(
        r"(?is)\b(?:presentation|slides?|slideshow|deck|powerpoint|essay|article|report)\b.{0,50}?\b(?:about|regarding|on\s+(?!it\b|there\b|google\b))\s+(.+)$",
        t,
    )
    if m and len(m.group(1).strip()) > 1:
        return re.sub(r"\s+", " ", m.group(1)).strip(" .:-")[:300]
    # "suggest a design for a presentation about X"
    m = re.search(
        r"(?is)\b(?:design|look|style|theme)\b.{0,40}\b(?:for|about|on)\b\s+"
        r"(?:(?:a|an|the)\s+)?(?:(?:google\s+)?(?:slides?|presentation|deck|powerpoint)\s+)?"
        r"(?:about|on|for)?\s*(.+)$",
        t,
    )
    if m and len(m.group(1).strip()) > 2:
        return re.sub(r"\s+", " ", m.group(1)).strip(" .:-")[:300]
    m = re.search(
        r"(?is)\b(?:presentation|slides?|deck|essay|article|report)\s+(?:about|on|for|regarding)\s+(.+)$",
        t,
    )
    if m and len(m.group(1).strip()) > 2:
        return re.sub(r"\s+", " ", m.group(1)).strip(" .:-")[:300]
    t2 = re.sub(
        r"(?is)^(?:please\s+|can you\s+|jarvis\s*,?\s*)?"
        r"(?:write|create|make|build|draft|type|suggest(?:ions?)?)\s+"
        r"(?:(?:a|an|my|full(?:\s+on)?)\s+)?"
        r"(?:design|look|style|theme)\s+(?:for\s+)?"
        r"(?:(?:a|an|the)\s+)?"
        r"(?:google\s+)?"
        r"(?:docs?\s+|document\s+|essay\s+|article\s+|report\s+|slides?\s+|presentation\s+|powerpoint\s+|deck\s+)?"
        r"(?:with\s+\d+\s+slides?\s+)?"
        r"(?:about|on|for|regarding|titled)?\s*",
        "",
        t,
        count=1,
    )
    t2 = re.sub(r"(?is)\bwith\s+\d+\s+slides?\b", "", t2)
    t2 = re.sub(r"(?is)\bin\s+(arabic|english)\b", "", t2)
    return re.sub(r"\s+", " ", t2).strip(" .:-")[:300] or t[:300]


def _ollama_json(prompt: str, *, num_predict: int = 700, timeout: float = 12.0) -> str | None:
    try:
        from ollama_gate import ollama_exclusive
    except Exception:
        ollama_exclusive = None  # type: ignore
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "10m",
        "format": "json",
        "options": {"temperature": 0.45, "num_predict": num_predict, "num_ctx": 2048},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_API}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        if ollama_exclusive:
            with ollama_exclusive(for_user=True, wait=min(4.0, timeout)) as got:
                if not got:
                    return None
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return str(data.get("response") or "").strip() or None
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("response") or "").strip() or None
    except Exception:
        return None


def _parse_json_obj(raw: str | None) -> dict | None:
    if not raw:
        return None
    s = raw.strip()
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        s = m.group(0)
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def pick_design(topic: str, user_text: str = "") -> dict[str, str]:
    """Jarvis's design opinion — used when user does not specify looks."""
    blob = f"{topic} {user_text}".lower()
    if re.search(r"\b(tech|ai|code|software|robot|space|cyber)\b", blob):
        return {
            "theme": "Modern Tech",
            "palette": "deep navy backgrounds, electric cyan accents, white text",
            "fonts": "bold sans titles, clean body",
            "layout": "title left / visual right on content slides; full-bleed title slide",
            "image_style": "abstract tech, circuits, futuristic city",
        }
    if re.search(r"\b(school|educat|history|science|biology|math|classroom)\b", blob):
        return {
            "theme": "Academic Clean",
            "palette": "white cards, soft blue headers, charcoal text",
            "fonts": "clear serif-friendly titles, readable body",
            "layout": "title + 3–5 bullets; diagrams where helpful",
            "image_style": "educational diagrams, books, labs, maps",
        }
    if re.search(r"\b(health|nature|environment|green|ocean|climate)\b", blob):
        return {
            "theme": "Nature Calm",
            "palette": "sage green, sand, deep forest accents",
            "fonts": "friendly rounded titles",
            "layout": "airy spacing, one big idea per slide",
            "image_style": "nature photography, ecosystems, water",
        }
    if re.search(r"\b(business|market|money|startup|finance)\b", blob):
        return {
            "theme": "Executive Brief",
            "palette": "charcoal, white, gold accent",
            "fonts": "sharp geometric titles",
            "layout": "metric callouts + short bullets",
            "image_style": "office, charts, city skylines",
        }
    if _has_arabic(topic) or re.search(r"(?is)\barabic\b|\bعربي", user_text):
        return {
            "theme": "Bilingual Classic",
            "palette": "cream paper feel, teal accents, dark ink text",
            "fonts": "clear titles suitable for Arabic + English",
            "layout": "generous line spacing; short bullets",
            "image_style": "culture, calligraphy-adjacent patterns, architecture",
        }
    return {
        "theme": "Story Spotlight",
        "palette": "warm white, coral accent, slate text",
        "fonts": "expressive title, simple body",
        "layout": "hook → points → takeaway; one image per content slide",
        "image_style": "people, moments, symbolic metaphors",
    }


def design_suggestions_text(topic: str, user_text: str = "", slide_count: int = 8) -> str:
    d = pick_design(topic or "your topic", user_text)
    topic_l = topic or "your topic"
    return (
        f"Here is my design opinion for a {slide_count}-slide deck on “{topic_l}”:\n"
        f"• Theme: {d['theme']}\n"
        f"• Colors: {d['palette']}\n"
        f"• Typography: {d['fonts']}\n"
        f"• Layout: {d['layout']}\n"
        f"• Images: {d['image_style']}\n"
        f"• Structure: title → agenda → 4–5 content beats → summary → Q&A\n"
        "Say the topic (and slide count if you want) and I will build it in Google Slides without asking again about the look."
    )


def _essay_fallback(topic: str, *, arabic: bool = False) -> dict[str, str]:
    title = topic.strip()[:80] or ("Essay" if not arabic else "مقال")
    if arabic:
        body = (
            f"{title}\n\n"
            f"مقدمة\n"
            f"يتناول هذا المقال موضوع {topic} وأهميته في حياتنا اليومية، مع نظرة واضحة على الأسباب والنتائج.\n\n"
            f"الخلفية\n"
            f"لفهم {topic} يجب أن نبدأ من السياق العام: لماذا يظهر هذا الموضوع الآن، ومن يتأثر به، وما الذي تغيّر مؤخراً.\n\n"
            f"النقاط الرئيسية\n"
            f"أولاً، {topic} يؤثر على القرارات الفردية والمجتمعية.\n"
            f"ثانياً، توجد تحديات عملية يمكن معالجتها بخطوات بسيطة ومنظمة.\n"
            f"ثالثاً، الوعي والمعرفة هما أساس أي حل مستدام.\n\n"
            f"التحليل\n"
            f"من وجهة نظري، أفضل مقاربة لـ{topic} هي الجمع بين الفهم العميق والتنفيذ التدريجي، بدل الحلول السريعة غير المدروسة.\n\n"
            f"الخاتمة\n"
            f"في الختام، {topic} يستحق اهتماماً جاداً. إذا بدأنا بخطوات واضحة اليوم، سنحقق نتائج أفضل غداً.\n"
        )
    else:
        body = (
            f"{title}\n\n"
            f"Introduction\n"
            f"{topic} matters because it shapes how people decide, learn, and act. "
            f"This essay explains what it is, why it matters, and what a practical path forward looks like.\n\n"
            f"Background\n"
            f"To understand {topic}, start with context: who is affected, what changed recently, and which old assumptions no longer hold. "
            f"Clear definitions prevent confusion later.\n\n"
            f"Key arguments\n"
            f"1) {topic} influences everyday choices more than it first appears.\n"
            f"2) The hardest problems are usually process problems — unclear goals, weak feedback, and delayed action.\n"
            f"3) Progress comes from small, repeatable improvements rather than one dramatic fix.\n\n"
            f"Analysis\n"
            f"In my view, the strongest approach to {topic} is evidence first, then opinion. "
            f"Map the facts, name the trade-offs, and only then choose a direction. "
            f"That keeps the essay honest and useful.\n\n"
            f"Conclusion\n"
            f"{topic} is not just an abstract idea — it is a practical challenge. "
            f"If we stay curious, measure what works, and adjust quickly, we can turn understanding into real results.\n"
        )
    return {"title": title, "body": body, "source": "template"}


def generate_essay(topic: str, user_text: str = "") -> dict[str, Any]:
    t0 = time.perf_counter()
    arabic = _has_arabic(topic) or bool(re.search(r"(?is)\barabic\b|\bعربي", user_text))
    prompt = (
        "Do not use any tools. Reply with ONLY a JSON object {\"title\": \"...\", \"body\": \"...\"}.\n"
        f"Write a complete, well-structured essay. Topic: {topic}.\n"
        f"The user's exact request (follow any length/tone/format details in it): {user_text}\n"
        "Use accurate, specific facts about the topic — never generic filler. "
        "body: plain text paragraphs separated by blank lines (intro, 3+ body paragraphs, conclusion); "
        "no markdown, no headings with #. "
        + ("Write the entire essay in Arabic." if arabic else "Write in clear English.")
    )
    data = _llm_json(prompt, timeout=120.0)
    if data and (data.get("body") or data.get("essay")):
        body = str(data.get("body") or data.get("essay")).strip()
        title = str(data.get("title") or topic)[:100]
        return {
            "ok": True,
            "title": title,
            "body": body,
            "source": "ollama",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    fb = _essay_fallback(topic, arabic=arabic)
    fb["ok"] = True
    fb["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    return fb


def _slides_fallback(topic: str, n: int, design: dict[str, str]) -> list[dict[str, str]]:
    beats = [
        ("Agenda", f"What we will cover about {topic}\n1. Context\n2. Why it matters\n3. Key ideas\n4. Practical steps\n5. Takeaways"),
        ("Why it matters", f"{topic} affects real people and real decisions. Ignoring it costs time and clarity."),
        ("Core idea 1", f"Define {topic} clearly so everyone shares the same starting point."),
        ("Core idea 2", f"The main challenge around {topic} is usually execution, not information."),
        ("Core idea 3", f"A simple system beats a perfect plan: small steps, fast feedback, honest review."),
        ("Practical moves", f"1) Name the goal\n2) Pick one metric\n3) Run a 7-day experiment\n4) Keep what works"),
        ("Common pitfalls", f"Overcomplicating {topic}, copying others blindly, and waiting for perfect conditions."),
        ("Summary", f"{topic} rewards clarity and action. Start small, learn fast, improve weekly."),
        ("Q&A / Next steps", "Questions, discussion, and one commitment to try this week."),
    ]
    slides = [{"title": topic[:80] or "Presentation", "body": f"A clear take on {topic}\nTheme: {design['theme']}", "image_query": topic.split()[:2] and " ".join(topic.split()[:2]) or "idea"}]
    # Fill to n slides using beats (wrap/cycle if needed)
    i = 0
    while len(slides) < n:
        title, body = beats[i % len(beats)]
        if i >= len(beats):
            title = f"{title} ({i // len(beats) + 1})"
        slides.append({
            "title": title,
            "body": body,
            "image_query": re.sub(r"[^a-zA-Z0-9 ]", "", f"{topic} {title}")[:40] or "presentation",
        })
        i += 1
    return slides[:n]


def generate_slides(topic: str, user_text: str = "", slide_count: int | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    n = slide_count or extract_slide_count(user_text, 8)
    design = pick_design(topic, user_text)
    prompt = (
        "Do not use any tools. Reply with ONLY a JSON object:\n"
        '{"title":"deck title","slides":[{"title":"...","body":"line 1\\nline 2\\nline 3"}]}\n'
        f"Make a {n}-slide presentation. Topic: {topic}.\n"
        f"The user's exact request (follow any details in it): {user_text}\n"
        "Think about what kind of topic this is and pick the structure that fits it logically, e.g.\n"
        "- a character/person: who they are, origin/background, personality, abilities or skills, "
        "key relationships, famous moments/achievements, why they matter, conclusion\n"
        "- an event/war/period: background, causes, key moments/timeline, people involved, outcome, impact\n"
        "- a place: location, history, culture, landmarks, fun facts\n"
        "- a concept/science topic: definition, how it works, examples, importance, summary\n"
        f"Slide 1 is the title slide (title = topic, body = one short subtitle). Exactly {n} slides. "
        "Each other slide: a clear title and 3-5 short, specific, factually accurate bullet lines "
        "(no bullet symbols, one fact per line, max ~12 words each). No markdown."
    )
    data = _llm_json(prompt, timeout=120.0)
    slides = []
    if data:
        items = data.get("slides") or data.get("deck") or []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = str(it.get("title") or "").strip()
                body = str(it.get("body") or it.get("content") or "").strip()
                iq = str(it.get("image_query") or it.get("image") or title or topic).strip()
                if isinstance(it.get("body"), list):
                    body = "\n".join(str(x) for x in it["body"])
                body = "\n".join(re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", ln) for ln in body.splitlines() if ln.strip())
                if title or body:
                    slides.append({
                        "title": (title or f"Slide {len(slides)+1}")[:80],
                        "body": body[:800],
                        "image_query": re.sub(r"[^a-zA-Z0-9 ]", " ", iq)[:40].strip() or "concept",
                    })
    if len(slides) < max(3, n - 2):
        slides = _slides_fallback(topic, n, design)
    else:
        slides = slides[:n]

    return {
        "ok": True,
        "topic": topic,
        "deck_title": str((data or {}).get("title") or topic)[:90],
        "slide_count": n,
        "design": design,
        "slides": slides,
        "source": "llm" if data and data.get("slides") else "template",
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    }


def generate_writing(kind: str, topic: str, user_text: str = "") -> dict[str, Any]:
    """Write the piece they asked for (paragraph, story, poem, letter, email, summary…)."""
    t0 = time.perf_counter()
    arabic = _has_arabic(topic) or bool(re.search(r"(?is)\barabic\b|\bعربي", user_text))
    prompt = (
        "Do not use any tools. Output ONLY the finished text that will be typed into a document — "
        "no preamble like 'Here is', no markdown symbols (#, **, -), no quotes around it.\n"
        f"Write a {kind} about: {topic}.\n"
        f"The user's exact request (follow any length/tone/audience details in it): {user_text}\n"
        "Use accurate, specific details. Match the natural length of that kind of writing unless a length is given."
        + (" Write it in Arabic." if arabic else "")
    )
    text = _llm_text(prompt, timeout=120.0)
    source = "llm"
    if not text:
        raw = _ollama_json(
            f'Reply as JSON {{"text": "..."}}. Write a {kind} about {topic}. Request: {user_text}',
            num_predict=700, timeout=12.0,
        )
        text = str((_parse_json_obj(raw) or {}).get("text") or "").strip()
        source = "ollama"
    text = re.sub(r"(?im)^\s*(?:here(?:'s| is)[^\n]*:\s*)", "", text or "").strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^#+\s*", "", text)
    return {
        "ok": bool(text),
        "text": text,
        "title": topic[:80],
        "source": source,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    }


def generate_extra_slides(deck_topic: str, request: str, count: int = 1) -> list[dict[str, str]]:
    """Slides to append to an existing deck ('add a slide about his powers')."""
    prompt = (
        "Do not use any tools. Reply with ONLY a JSON object "
        '{"slides":[{"title":"...","body":"line 1\\nline 2\\nline 3"}]}.\n'
        f"An existing presentation is about: {deck_topic}.\n"
        f"The user now asks: {request}\n"
        "Resolve pronouns (he/she/it/they/his) to the presentation topic. "
        f"Create exactly {count} new slide(s): clear title, 3-5 short factual lines each, no bullet symbols."
    )
    data = _llm_json(prompt, timeout=90.0) or {}
    out = []
    for it in data.get("slides") or []:
        if isinstance(it, dict) and (it.get("title") or it.get("body")):
            body = it.get("body")
            if isinstance(body, list):
                body = "\n".join(str(x) for x in body)
            out.append({"title": str(it.get("title") or "")[:80], "body": str(body or "")[:800]})
    return out[:max(1, count)]
