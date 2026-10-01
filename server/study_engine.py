"""Autonomous Study Engine — continuous deep learning while Jarvis is idle.

Expands across foundational + advanced curriculum and open-world domains.
Biases toward what the user asks most, but keeps exploring everything.

Reality check: a local 3B model + knowledge cards will NOT equal ChatGPT/Claude
weights. This maximizes Layer-1 breadth; Hermes remains the frontier brain.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from study_curriculum import OPEN_WORLD_DOMAINS, SUBJECTS, all_sample_qa
from ollama_gate import (
    begin_user_turn,
    clear_study_abort,
    end_user_turn,
    ollama_exclusive,
    study_must_abort,
)

DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", str(Path(__file__).resolve().parent / "data")))
STORE_PATH = DATA_DIR / "study_brain.json"
# Small separate file: study time/cards only ever go up, even if the big store is lost
PROGRESS_PATH = DATA_DIR / "study_progress.json"
BACKUP_EVERY_SECONDS = 600

OLLAMA_API = os.environ.get("OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
STUDY_MODEL = os.environ.get("JARVIS_STUDY_MODEL", "llama3.2:3b")
# Idle study cadence (user turns still preempt immediately)
STUDY_CARD_INTERVAL = int(os.environ.get("JARVIS_STUDY_INTERVAL", "120"))
STUDY_IDLE_GRACE_SECONDS = float(os.environ.get("JARVIS_STUDY_IDLE_GRACE", "5.0"))
# Soft cap — prune oldest low-value cards when exceeded
MAX_CARDS = int(os.environ.get("JARVIS_STUDY_MAX_CARDS", "25000"))

_LOCK = threading.Lock()
_study_http: dict[str, Any] = {"resp": None}

_SUBJECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "daily_life": ("routine", "habit", "morning", "sleep", "cook", "kitchen", "home", "organize", "procrastinat", "etiquette", "polite"),
    "mathematics": ("math", "calculate", "percent", "fraction", "algebra", "geometry", "number", "equation", "multiply", "divide", "sum", "calculus", "proof", "matrix"),
    "science": ("science", "physics", "chemistry", "biology", "atom", "gravity", "energy", "cell", "planet", "molecule"),
    "technology": ("computer", "code", "software", "ai", "gpu", "cpu", "internet", "app", "phone", "wifi", "program", "python"),
    "world_history_geography": ("history", "war", "empire", "country", "capital", "geography", "map", "continent", "ancient", "civilization"),
    "language_communication": ("write", "grammar", "speak", "word", "sentence", "communicate", "persuade", "summary", "english", "arabic"),
    "health_wellness": ("health", "fitness", "exercise", "diet", "nutrition", "stress", "mental", "doctor", "sleep", "workout"),
    "how_things_work": ("engine", "electric", "circuit", "machine", "how does", "mechanism", "gps", "touchscreen", "airplane"),
    "kuwait_local": (
        "kuwait", "hiteen", "hitteen", "mishrif", "mishref", "salmiya", "jahra", "hawalli", "farwaniya",
        "ahmadi", "vidbox", "avenues", "حطين", "مشرف", "السالمية", "الجهراء", "كويت", "خليج", "dialect", "kuwaiti",
        "maps", "eta", "minutes from", "من ", "لـ",
    ),
    "computer_science": ("algorithm", "complexity", "big-o", "hash", "graph", "database", "tcp", "os", "thread", "compiler", "data structure"),
    "artificial_intelligence": ("neural", "transformer", "llm", "machine learning", "gradient", "token", "embedding", "training", "inference", "alignment"),
    "physics_advanced": ("relativity", "quantum", "momentum", "newton", "electromagnet", "thermodynamic", "wave", "photon"),
    "chemistry_advanced": ("mole", "equilibrium", "acid", "base", "organic", "bond", "reaction", "stoichiometr"),
    "biology_advanced": ("dna", "rna", "gene", "evolution", "cell", "protein", "mitosis", "ecosystem"),
    "economics_finance": ("inflation", "market", "invest", "interest", "supply", "demand", "opportunity cost", "portfolio"),
    "philosophy_logic": ("fallacy", "ethics", "logic", "argument", "utilitarian", "epistemolog", "moral"),
    "psychology_sociology": ("bias", "memory", "cognitive", "behavior", "motivation", "social", "placebo"),
    "engineering_design": ("tradeoff", "system", "feedback", "fermi", "reliability", "design", "estimate"),
    "law_civics": ("contract", "court", "civil", "criminal", "constitution", "patent", "copyright", "rights"),
    "literature_arts": ("metaphor", "narrative", "theme", "irony", "novel", "poetry", "story"),
    "medicine_first_aid": ("cpr", "stroke", "symptom", "antibiotic", "first aid", "anatomy", "vaccine"),
    "earth_environment": ("climate", "carbon", "tectonic", "weather", "biodiversity", "greenhouse", "ocean"),
    "world_religions_culture": ("islam", "christian", "jewish", "hindu", "buddhist", "religion", "culture", "pilgrim"),
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class StudyEngine:
    """Continuous background study while Jarvis is on and idle."""

    def __init__(self, path: Path = STORE_PATH):
        self.path = path
        self.backup_path = path.with_suffix(path.suffix + ".bak")
        self.progress_path = PROGRESS_PATH if path == STORE_PATH else path.with_name(path.stem + "_progress.json")
        self._last_backup = 0.0
        self._progress = self._read_progress()
        self.worker_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.paused = False
        self._busy_depth = 0
        self._idle_since = time.time()
        self._ensure_initialized()

    def _empty(self) -> dict[str, Any]:
        return {
            "version": "3.0",
            "created_at": _now(),
            "updated_at": _now(),
            "status": "standby",
            "study_start_time": None,
            "elapsed_seconds": 0,
            "target_duration_seconds": None,
            "active_subject": "daily_life",
            "active_topic": None,
            "total_cards": 0,
            "mastery_by_subject": {sid: {"cards": 0, "mastered_pct": 0.0} for sid in SUBJECTS},
            "interest": {sid: 0.0 for sid in SUBJECTS},
            "interest_queries": [],
            "recent_activity": [],
            "cards": [],
            "mode": "continuous_deep",
            "ambition": "broad_general_knowledge",
            "open_world_cards": 0,
            "complex_cards": 0,
        }

    def _ensure_initialized(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file() and not self.backup_path.is_file():
            data = self._empty()
            seeds = all_sample_qa()
            for s in seeds:
                data["cards"].append({
                    "id": f"seed_{len(data['cards']) + 1:04d}",
                    "subject": s["subject_id"],
                    "subject_title": s["subject_title"],
                    "topic": s["topic"],
                    "question": s["question"],
                    "answer": s["answer"],
                    "difficulty": s["difficulty"],
                    "source": "curriculum_foundational",
                    "learned_at": _now(),
                })
            data["total_cards"] = len(data["cards"])
            self._recalculate_stats(data)
            self._save(data)
            print(
                f"[StudyEngine] Initialized with {len(data['cards'])} foundational cards "
                f"across {len(SUBJECTS)} subjects (deep-study mode).",
                flush=True,
            )
        else:
            data = self._load()
            data.setdefault("interest", {})
            data.setdefault("interest_queries", [])
            data.setdefault("mastery_by_subject", {})
            data.setdefault("open_world_cards", 0)
            data.setdefault("complex_cards", 0)
            data["target_duration_seconds"] = None
            data["mode"] = "continuous_deep"
            data["ambition"] = "broad_general_knowledge"
            data["version"] = "3.0"
            for sid in SUBJECTS:
                data["interest"].setdefault(sid, 0.0)
                data["mastery_by_subject"].setdefault(sid, {"cards": 0, "mastered_pct": 0.0})
            # One-time: inject any missing curriculum seed Q&A for new subjects
            existing_q = {(c.get("question") or "").strip().lower() for c in data.get("cards") or []}
            added = 0
            for s in all_sample_qa():
                q = (s.get("question") or "").strip()
                if not q or q.lower() in existing_q:
                    continue
                if s["subject_id"] not in SUBJECTS:
                    continue
                # Only auto-add seeds for brand-new advanced subjects with few cards
                mastered = (data["mastery_by_subject"].get(s["subject_id"]) or {}).get("cards", 0)
                if mastered > 3 and s["subject_id"] in (
                    "daily_life", "mathematics", "science", "technology",
                    "world_history_geography", "language_communication",
                    "health_wellness", "how_things_work", "kuwait_local",
                ):
                    continue
                data["cards"].append({
                    "id": f"seed_{len(data['cards']) + 1:04d}",
                    "subject": s["subject_id"],
                    "subject_title": s["subject_title"],
                    "topic": s["topic"],
                    "question": q,
                    "answer": s.get("answer"),
                    "difficulty": s.get("difficulty", "simple"),
                    "source": "curriculum_expansion",
                    "learned_at": _now(),
                })
                existing_q.add(q.lower())
                added += 1
            if added:
                print(f"[StudyEngine] Injected {added} new curriculum seeds.", flush=True)
            self._recalculate_stats(data)
            self._save(data)

    def _read_progress(self) -> dict[str, Any]:
        try:
            data = json.loads(self.progress_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"elapsed_seconds": 0, "max_cards": 0, "created_at": None}

    def _load(self) -> dict[str, Any]:
        with _LOCK:
            for p in (self.path, self.backup_path):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, dict) and isinstance(data.get("cards"), list):
                    if p is self.backup_path:
                        print("[StudyEngine] Main study file unreadable — restored from backup.", flush=True)
                    data["elapsed_seconds"] = max(
                        int(data.get("elapsed_seconds", 0) or 0),
                        int(self._progress.get("elapsed_seconds", 0) or 0),
                    )
                    return data
            if self.path.is_file():
                # Never overwrite an unreadable store; keep it for manual recovery
                aside = self.path.with_name(f"{self.path.stem}.corrupt-{int(time.time())}.json")
                try:
                    os.replace(self.path, aside)
                    print(f"[StudyEngine] Study file unreadable — kept as {aside.name}.", flush=True)
                except OSError:
                    pass
            return self._empty()

    def _save(self, data: dict[str, Any]) -> None:
        with _LOCK:
            data = dict(data)
            prog = self._progress
            cards_n = len(data.get("cards") or [])
            max_cards = int(prog.get("max_cards", 0) or 0)
            if max_cards > 200 and cards_n < max_cards * 0.5 and self.path.is_file():
                print(
                    f"[StudyEngine] Refusing to save {cards_n} cards over {max_cards} — would lose progress.",
                    flush=True,
                )
                return
            elapsed = max(int(data.get("elapsed_seconds", 0) or 0), int(prog.get("elapsed_seconds", 0) or 0))
            data["elapsed_seconds"] = elapsed
            if prog.get("created_at") and (not data.get("created_at") or prog["created_at"] < data["created_at"]):
                data["created_at"] = prog["created_at"]
            data["updated_at"] = _now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self.path)

            self._progress = {
                "elapsed_seconds": elapsed,
                "max_cards": max(max_cards, cards_n),
                "created_at": data.get("created_at"),
                "updated_at": data["updated_at"],
            }
            ptmp = self.progress_path.with_suffix(".tmp")
            ptmp.write_text(json.dumps(self._progress), encoding="utf-8")
            os.replace(ptmp, self.progress_path)

            if time.time() - self._last_backup >= BACKUP_EVERY_SECONDS:
                btmp = self.backup_path.with_suffix(".bak.tmp")
                shutil.copyfile(self.path, btmp)
                os.replace(btmp, self.backup_path)
                self._last_backup = time.time()

    def _recalculate_stats(self, data: dict[str, Any]) -> None:
        cards = data.get("cards") or []
        data["total_cards"] = len(cards)
        by_sub: dict[str, int] = {sid: 0 for sid in SUBJECTS}
        complex_n = 0
        open_n = 0
        for c in cards:
            sid = c.get("subject") or "daily_life"
            if sid in by_sub:
                by_sub[sid] += 1
            diff = (c.get("difficulty") or "").lower()
            if diff in ("complex", "advanced", "expert"):
                complex_n += 1
            if (c.get("source") or "").startswith("open_world"):
                open_n += 1
        data["complex_cards"] = complex_n
        data["open_world_cards"] = open_n
        mastery = data.setdefault("mastery_by_subject", {})
        for sid, n in by_sub.items():
            # Soft mastery curve — never claims 100% of human knowledge
            pct = round(min(95.0, (n / 80.0) * 100.0), 1) if n else 0.0
            mastery[sid] = {"cards": n, "mastered_pct": pct}
        # Prune if oversized
        if len(cards) > MAX_CARDS:
            # Keep recent + complex + curriculum seeds preferentially
            def score(c: dict) -> float:
                s = 0.0
                src = c.get("source") or ""
                if "seed" in src or "curriculum" in src:
                    s += 5
                if (c.get("difficulty") or "") in ("complex", "advanced", "expert"):
                    s += 3
                if "open_world" in src:
                    s += 1
                return s
            cards_sorted = sorted(cards, key=score, reverse=True)
            data["cards"] = cards_sorted[:MAX_CARDS]
            data["total_cards"] = len(data["cards"])

    def _subjects_summary(self) -> dict[str, Any]:
        out = {}
        for sid, sub in SUBJECTS.items():
            out[sid] = {
                "id": sid,
                "title": sub.get("title"),
                "description": (sub.get("description") or "")[:160],
                "topic_count": len(sub.get("topics") or []),
            }
        return out

    def notify_busy(self) -> None:
        with _LOCK:
            self._busy_depth += 1
        begin_user_turn()
        # Close in-flight study HTTP so Ollama frees the GPU for Layer 1
        resp = _study_http.get("resp")
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def notify_idle(self) -> None:
        with _LOCK:
            self._busy_depth = max(0, self._busy_depth - 1)
            if self._busy_depth == 0:
                self._idle_since = time.time()
                end_user_turn()
                clear_study_abort()

    def is_user_busy(self) -> bool:
        with _LOCK:
            return self._busy_depth > 0

    def should_study_now(self) -> bool:
        with _LOCK:
            if self.paused or self.stop_event.is_set() or self._busy_depth > 0:
                return False
            return (time.time() - self._idle_since) >= STUDY_IDLE_GRACE_SECONDS

    def note_interest(self, text: str) -> None:
        raw = (text or "").strip().lower()
        if not raw or raw.startswith("/"):
            return
        data = self._load()
        interest = data.setdefault("interest", {sid: 0.0 for sid in SUBJECTS})
        hits = []
        for sid, kws in _SUBJECT_KEYWORDS.items():
            if any(k in raw for k in kws):
                interest[sid] = float(interest.get(sid, 0.0)) + 1.0
                hits.append(sid)
        if not hits:
            # Default bump: language / daily when conversational
            hits = ["daily_life"] if len(raw.split()) <= 6 else ["language_communication"]
            for sid in hits:
                interest[sid] = float(interest.get(sid, 0.0)) + 0.35
        # Decay so old interests don't dominate forever
        for sid in list(interest.keys()):
            interest[sid] = float(interest.get(sid, 0.0)) * 0.995
        qlog = data.setdefault("interest_queries", [])
        qlog.append({"t": _now(), "q": raw[:120], "subjects": hits})
        data["interest_queries"] = qlog[-80:]
        self._save(data)

    def top_interests(self, n: int = 5) -> list[dict[str, Any]]:
        data = self._load()
        interest = data.get("interest") or {}
        ranked = sorted(interest.items(), key=lambda kv: kv[1], reverse=True)
        out = []
        for sid, score in ranked[:n]:
            if score <= 0:
                continue
            out.append({
                "id": sid,
                "title": (SUBJECTS.get(sid) or {}).get("title") or sid,
                "score": round(float(score), 2),
            })
        return out

    def _pick_subject_and_topic(self, data: dict) -> tuple[str, dict | None]:
        interest = data.get("interest") or {}
        keys = list(SUBJECTS.keys())
        weights = []
        for sid in keys:
            w = 1.0 + float(interest.get(sid, 0.0)) * 2.5
            cards = (data.get("mastery_by_subject") or {}).get(sid, {}).get("cards", 0)
            # Explore weak subjects harder (path toward "know everything")
            w += max(0.0, (40 - min(40, cards)) * 0.08)
            weights.append(max(0.15, w))
        sub_id = random.choices(keys, weights=weights, k=1)[0]
        topics = (SUBJECTS.get(sub_id) or {}).get("topics") or []
        topic = random.choice(topics) if topics else None
        return sub_id, topic

    def _target_difficulty(self, data: dict, subject_id: str) -> str:
        """Ramp difficulty as subject gains cards — push into complex/expert."""
        n = (data.get("mastery_by_subject") or {}).get(subject_id, {}).get("cards", 0)
        # Mix: still revisit basics, but bias hard
        roll = random.random()
        if n < 8:
            return random.choice(["simple", "moderate", "moderate"])
        if n < 25:
            return "complex" if roll < 0.55 else "moderate"
        if roll < 0.15:
            return "moderate"
        if roll < 0.55:
            return "complex"
        return "expert"

    def status(self) -> dict[str, Any]:
        data = self._load()
        elapsed = int(data.get("elapsed_seconds", 0) or 0)
        studying = self.worker_thread is not None and self.worker_thread.is_alive() and self.should_study_now()
        waiting = self.worker_thread is not None and self.worker_thread.is_alive() and self.is_user_busy()
        status = data.get("status", "standby")
        if self.paused:
            status = "paused"
        elif waiting:
            status = "idle_waiting"
        elif studying:
            status = "studying"
        elif self.worker_thread and self.worker_thread.is_alive():
            status = "studying"
        return {
            "ok": True,
            "status": status,
            "mode": "continuous_deep",
            "ambition": "broad_general_knowledge",
            "note": (
                "Studying foundational + advanced domains forever while idle. "
                "Local cards help Layer 1; Hermes/ChatGPT-class models remain the deep brain — "
                "a 3B local model cannot literally match Claude/ChatGPT weights."
            ),
            "elapsed_seconds": elapsed,
            "elapsed_formatted": self._format_seconds(elapsed),
            "target_duration_seconds": None,
            "target_formatted": "unlimited",
            "remaining_seconds": None,
            "remaining_formatted": "∞",
            "progress_pct": None,
            "active_subject": data.get("active_subject"),
            "active_topic": data.get("active_topic"),
            "total_cards": data.get("total_cards", 0),
            "complex_cards": data.get("complex_cards", 0),
            "open_world_cards": data.get("open_world_cards", 0),
            "subject_count": len(SUBJECTS),
            "subjects": self._subjects_summary(),
            "mastery": data.get("mastery_by_subject", {}),
            "interest": data.get("interest", {}),
            "top_interests": self.top_interests(),
            "recent_activity": (data.get("recent_activity") or [])[-12:],
            "is_studying": studying,
            "is_waiting_for_idle": waiting,
            "user_busy": self.is_user_busy(),
        }

    @staticmethod
    def _format_seconds(secs: int) -> str:
        m, s = divmod(int(secs), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m {s}s"

    def find_relevant_cards(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        data = self._load()
        cards = data.get("cards", [])
        if not cards:
            return []

        tokens = set(re.findall(r"\w{3,}", query.lower()))
        if not tokens:
            return cards[:limit]

        # Cap scan — full 25k linear scan adds avoidable latency on every turn
        scan = cards[-2500:] if len(cards) > 2500 else cards
        scored: list[tuple[float, dict[str, Any]]] = []
        for c in scan:
            score = 0.0
            blob = f"{c.get('question','')} {c.get('topic','')} {c.get('subject','')} {c.get('answer','')}".lower()
            for t in tokens:
                if t in blob:
                    score += 2.0
                    if t in (c.get("question") or "").lower():
                        score += 3.0
            if (c.get("difficulty") or "") in ("complex", "expert", "advanced"):
                score *= 1.15
            if score > 0:
                scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def add_card(self, card: dict[str, Any]) -> None:
        data = self._load()
        card_id = f"card_{len(data['cards']) + 1:04d}"
        entry = {
            "id": card_id,
            "subject": card.get("subject", "daily_life"),
            "subject_title": (SUBJECTS.get(card.get("subject", "")) or {}).get("title", card.get("subject")),
            "topic": card.get("topic", "General"),
            "question": card.get("question", "").strip(),
            "answer": card.get("answer", "").strip(),
            "difficulty": card.get("difficulty", "moderate"),
            "source": card.get("source") or "autonomous_study",
            "learned_at": _now(),
        }
        if not entry["question"] or not entry["answer"]:
            return
        # Light de-dupe
        q_low = entry["question"].lower()
        for c in data["cards"][-400:]:
            if (c.get("question") or "").lower() == q_low:
                return
        data["cards"].append(entry)
        data.setdefault("recent_activity", []).append({
            "time": _now(),
            "action": f"Learned ({entry['difficulty']}): {entry['topic']}",
            "question": entry["question"][:90],
            "subject": entry["subject"],
        })
        data["recent_activity"] = data["recent_activity"][-40:]
        self._recalculate_stats(data)
        self._save(data)

    def start_studying(self) -> dict[str, Any]:
        if self.worker_thread and self.worker_thread.is_alive():
            self.paused = False
            data = self._load()
            data["status"] = "studying"
            self._save(data)
            return {"ok": True, "message": "Deep continuous study already running (idle-only)."}

        self.stop_event.clear()
        self.paused = False
        data = self._load()
        data["status"] = "studying"
        data["mode"] = "continuous_deep"
        data["ambition"] = "broad_general_knowledge"
        data["target_duration_seconds"] = None
        if not data.get("study_start_time"):
            data["study_start_time"] = _now()
        self._save(data)

        self.worker_thread = threading.Thread(target=self._study_loop, daemon=True, name="JarvisStudyWorker")
        self.worker_thread.start()
        print(
            f"[StudyEngine] Deep study started — {len(SUBJECTS)} subjects + open-world domains.",
            flush=True,
        )
        return {"ok": True, "message": "Deep continuous study started (unlimited while Jarvis is on)."}

    def pause_studying(self) -> dict[str, Any]:
        self.paused = True
        data = self._load()
        data["status"] = "paused"
        self._save(data)
        return {"ok": True, "message": "Study session paused."}

    def _query_local_llm(self, prompt: str, timeout: float = 18.0, num_predict: int = 160) -> str:
        """Stream study tokens so a user turn can abort mid-generation."""
        if study_must_abort() or self.is_user_busy() or self.paused:
            return ""
        url = f"{OLLAMA_API}/api/generate"
        payload = json.dumps({
            "model": STUDY_MODEL,
            "prompt": prompt,
            "stream": True,
            "keep_alive": "30m",
            "options": {
                "temperature": 0.45,
                "num_predict": num_predict,
                "num_ctx": 2048,
            },
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        parts: list[str] = []
        with ollama_exclusive(for_user=False, wait=0.05) as got:
            if not got:
                return ""
            if study_must_abort() or self.is_user_busy():
                return ""
            resp = urllib.request.urlopen(req, timeout=timeout)
            _study_http["resp"] = resp
            try:
                while True:
                    if study_must_abort() or self.is_user_busy() or self.paused:
                        try:
                            resp.close()
                        except Exception:
                            pass
                        return ""
                    line = resp.readline()
                    if not line:
                        break
                    try:
                        data = json.loads(line.decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    parts.append(str(data.get("response") or ""))
                    if data.get("done"):
                        break
            finally:
                _study_http["resp"] = None
                try:
                    resp.close()
                except Exception:
                    pass
        return "".join(parts).strip()

    def _wait_idle_slice(self, seconds: int) -> None:
        for _ in range(max(1, seconds)):
            if self.stop_event.is_set():
                return
            if self.paused or self.is_user_busy():
                return
            time.sleep(1)

    def _parse_qa(self, reply: str) -> tuple[str, str, str] | None:
        q_match = re.search(r"Q:\s*(.+)", reply, re.IGNORECASE)
        a_match = re.search(r"A:\s*(.+?)(?:\nDIFFICULTY:|$)", reply, re.IGNORECASE | re.DOTALL)
        diff_match = re.search(
            r"DIFFICULTY:\s*(simple|moderate|complex|advanced|expert)",
            reply,
            re.IGNORECASE,
        )
        if not q_match or not a_match:
            return None
        diff = (diff_match.group(1).lower() if diff_match else "moderate")
        if diff == "advanced":
            diff = "complex"
        return q_match.group(1).strip(), a_match.group(1).strip(), diff

    def _study_curriculum_card(self, data: dict, sub_id: str, topic: dict) -> None:
        sub = SUBJECTS.get(sub_id) or {}
        concepts = topic.get("concepts") or ["Essential principles"]
        concept = random.choice(concepts)
        difficulty = self._target_difficulty(data, sub_id)
        tops = self.top_interests(3)
        interest_hint = ""
        if tops:
            interest_hint = (
                "User recent interests: "
                + ", ".join(t["title"] for t in tops)
                + ". Tie in if natural.\n"
            )
        depth = {
            "simple": "one clear fact a beginner needs",
            "moderate": "a solid explanation with one why/how",
            "complex": "a multi-step or nuanced explanation a strong student should know",
            "expert": "a hard conceptual question with precise reasoning (still 2-5 sentences)",
        }.get(difficulty, "a clear accurate answer")
        prompt = (
            f"You are Jarvis building a world-class personal knowledge base.\n"
            f"Subject: '{sub.get('title')}' · Topic: '{topic.get('name')}'\n"
            f"Focus concept: {concept}\n"
            f"Target difficulty: {difficulty} — {depth}.\n"
            f"{interest_hint}"
            "Generate ONE high-quality study card.\n"
            "Answer in clear English, accurate, no fluff.\n"
            "Format strictly as:\n"
            "Q: [question]\n"
            "A: [answer]\n"
            f"DIFFICULTY: {difficulty}"
        )
        if not self.should_study_now():
            return
        reply = self._query_local_llm(prompt, timeout=18.0, num_predict=180)
        if not self.should_study_now():
            return
        parsed = self._parse_qa(reply)
        if not parsed:
            return
        q, a, diff = parsed
        self.add_card({
            "subject": sub_id,
            "topic": topic.get("name"),
            "question": q,
            "answer": a,
            "difficulty": diff,
            "source": "deep_curriculum_study",
        })

    def _study_open_world_card(self, data: dict) -> None:
        domain = random.choice(OPEN_WORLD_DOMAINS)
        # Map loosely to a subject bucket for stats
        sub_id = "artificial_intelligence"
        for sid, kws in _SUBJECT_KEYWORDS.items():
            if any(k in domain.lower() for k in kws):
                sub_id = sid
                break
        difficulty = self._target_difficulty(data, sub_id)
        if difficulty == "simple":
            difficulty = "complex"
        prompt = (
            "You are Jarvis doing open-world deep study to approach broad expert literacy "
            "(not trivia).\n"
            f"Domain: {domain}\n"
            f"Difficulty: {difficulty}\n"
            "Invent ONE non-trivial question someone might ask a very knowledgeable assistant, "
            "and a precise answer (2-6 sentences). Prefer mechanisms, tradeoffs, definitions, "
            "and reasoned comparisons — not yes/no trivia.\n"
            "Format strictly as:\n"
            "Q: [question]\n"
            "A: [answer]\n"
            f"DIFFICULTY: {difficulty}"
        )
        if not self.should_study_now():
            return
        reply = self._query_local_llm(prompt, timeout=18.0, num_predict=180)
        if not self.should_study_now():
            return
        parsed = self._parse_qa(reply)
        if not parsed:
            return
        q, a, diff = parsed
        self.add_card({
            "subject": sub_id,
            "topic": domain[:80],
            "question": q,
            "answer": a,
            "difficulty": diff,
            "source": "open_world_deep_study",
        })

    def _study_loop(self) -> None:
        """Forever: curriculum + open-world deep study while idle."""
        marked_waiting = False
        while not self.stop_event.is_set():
            if self.paused:
                time.sleep(1)
                continue

            if self.is_user_busy():
                if not marked_waiting:
                    data = self._load()
                    if data.get("status") != "idle_waiting":
                        data["status"] = "idle_waiting"
                        self._save(data)
                    marked_waiting = True
                time.sleep(0.5)
                continue
            marked_waiting = False

            data = self._load()
            # ~40% open-world advanced, ~60% curriculum (including new advanced subjects)
            mode = "open_world" if random.random() < 0.40 else "curriculum"

            if mode == "open_world":
                data["status"] = "studying"
                data["active_subject"] = "open_world"
                data["active_topic"] = "Deep open-world study"
                data["elapsed_seconds"] = int(data.get("elapsed_seconds", 0) or 0) + STUDY_CARD_INTERVAL
                data["target_duration_seconds"] = None
                self._save(data)
                if self.should_study_now():
                    try:
                        self._study_open_world_card(data)
                    except Exception:
                        pass
            else:
                sub_id, topic = self._pick_subject_and_topic(data)
                sub = SUBJECTS.get(sub_id) or {}
                data["status"] = "studying"
                data["active_subject"] = sub_id
                data["active_topic"] = topic.get("name") if topic else sub.get("title")
                data["elapsed_seconds"] = int(data.get("elapsed_seconds", 0) or 0) + STUDY_CARD_INTERVAL
                data["target_duration_seconds"] = None
                self._save(data)
                if topic and self.should_study_now():
                    try:
                        self._study_curriculum_card(data, sub_id, topic)
                    except Exception:
                        pass

            self._wait_idle_slice(STUDY_CARD_INTERVAL)


STUDY_ENGINE = StudyEngine()
