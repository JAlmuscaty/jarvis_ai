"""Kuwait areas, governorates, and Kuwaiti-accent name aliases (EN + AR).

Coords are area centroids for fast local ETA (no geocoder round-trip).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# Governorates (محافظات)
GOVERNORATES: dict[str, dict[str, Any]] = {
    "capital": {
        "label": "Capital Governorate",
        "label_ar": "محافظة العاصمة",
        "lat": 29.3759,
        "lon": 47.9774,
        "aliases": ["capital", "al asimah", "asimah", "kuwait city", "العاصمة", "مدينة الكويت"],
    },
    "hawalli": {
        "label": "Hawalli Governorate",
        "label_ar": "محافظة حولي",
        "lat": 29.3328,
        "lon": 48.0281,
        "aliases": ["hawalli", "hawally", "حولي"],
    },
    "farwaniya": {
        "label": "Farwaniya Governorate",
        "label_ar": "محافظة الفروانية",
        "lat": 29.2775,
        "lon": 47.9586,
        "aliases": ["farwaniya", "farwaniyah", "الفروانية", "فروانية"],
    },
    "ahmadi": {
        "label": "Ahmadi Governorate",
        "label_ar": "محافظة الأحمدي",
        "lat": 29.0769,
        "lon": 48.0839,
        "aliases": ["ahmadi", "al ahmadi", "الأحمدي", "احمدي"],
    },
    "jahra": {
        "label": "Jahra Governorate",
        "label_ar": "محافظة الجهراء",
        "lat": 29.3375,
        "lon": 47.6581,
        "aliases": ["jahra", "al jahra", "الجهراء", "جهراء"],
    },
    "mubarak_al_kabeer": {
        "label": "Mubarak Al-Kabeer Governorate",
        "label_ar": "محافظة مبارك الكبير",
        "lat": 29.2000,
        "lon": 48.0889,
        "aliases": [
            "mubarak al kabeer", "mubarak al-kabeer", "mubarak kabir",
            "مبارك الكبير", "مبارك كبير",
        ],
    },
}

# Areas / districts — aliases include common Kuwaiti English spellings + Arabic
# Format: id -> label, label_ar, gov, lat, lon, aliases
AREAS: dict[str, dict[str, Any]] = {
    # Hawalli
    "hiteen": {
        "label": "Hiteen", "label_ar": "حطين", "gov": "hawalli",
        "lat": 29.3035, "lon": 48.0155,
        "aliases": ["hiteen", "hitteen", "hitin", "hateen", "hattein", "حطين"],
    },
    "mishrif": {
        "label": "Mishrif", "label_ar": "مشرف", "gov": "hawalli",
        "lat": 29.2678, "lon": 48.0694,
        "aliases": ["mishrif", "mishref", "mashref", "meshref", "مشرف"],
    },
    "salmiya": {
        "label": "Salmiya", "label_ar": "السالمية", "gov": "hawalli",
        "lat": 29.3339, "lon": 48.0761,
        "aliases": ["salmiya", "salmiyah", "salmia", "alsalmiya", "السالمية", "سالمية"],
    },
    "hawalli_area": {
        "label": "Hawalli", "label_ar": "حولي", "gov": "hawalli",
        "lat": 29.3328, "lon": 48.0281,
        "aliases": ["hawalli", "hawally", "حولي"],
    },
    "jabriya": {
        "label": "Jabriya", "label_ar": "الجابرية", "gov": "hawalli",
        "lat": 29.3156, "lon": 48.0367,
        "aliases": ["jabriya", "jabria", "jabriyah", "الجابرية", "جابرية"],
    },
    "bayan": {
        "label": "Bayan", "label_ar": "بيان", "gov": "hawalli",
        "lat": 29.3033, "lon": 48.0489,
        "aliases": ["bayan", "بيان"],
    },
    "salwa": {
        "label": "Salwa", "label_ar": "سلوى", "gov": "hawalli",
        "lat": 29.2867, "lon": 48.0700,
        "aliases": ["salwa", "سلوى"],
    },
    "shaab": {
        "label": "Shaab", "label_ar": "الشعب", "gov": "hawalli",
        "lat": 29.3550, "lon": 48.0200,
        "aliases": ["shaab", "al shaab", "الشعب", "شعب"],
    },
    "surra": {
        "label": "Surra", "label_ar": "السرة", "gov": "hawalli",
        "lat": 29.3122, "lon": 47.9989,
        "aliases": ["surra", "alsurra", "السرة", "سرة"],
    },
    "maidan_hawalli": {
        "label": "Maidan Hawalli", "label_ar": "ميدان حولي", "gov": "hawalli",
        "lat": 29.3370, "lon": 48.0350,
        "aliases": ["maidan hawalli", "maidan hawally", "ميدان حولي"],
    },
    "rumaithiya": {
        "label": "Rumaithiya", "label_ar": "الرميثية", "gov": "hawalli",
        "lat": 29.3144, "lon": 48.0756,
        "aliases": ["rumaithiya", "rumaithiyah", "rumaithia", "الرميثية", "رميثية"],
    },
    "bneid_al_gar": {
        "label": "Bneid Al-Gar", "label_ar": "بنيد القار", "gov": "hawalli",
        "lat": 29.3689, "lon": 48.0000,
        "aliases": ["bneid al gar", "bneid al-gar", "bnaid al qar", "بنيد القار", "بنيدقار"],
    },
    "nuzha": {
        "label": "Nuzha", "label_ar": "النزهة", "gov": "hawalli",
        "lat": 29.3456, "lon": 47.9856,
        "aliases": ["nuzha", "al nuzha", "النزهة", "نزهة"],
    },
    "siddiq": {
        "label": "Al-Siddiq", "label_ar": "الصديق", "gov": "hawalli",
        "lat": 29.2900, "lon": 48.0450,
        "aliases": ["siddiq", "al siddiq", "alsiddiq", "الصديق", "صديق"],
    },
    "salam": {
        "label": "Salam", "label_ar": "السلام", "gov": "hawalli",
        "lat": 29.2950, "lon": 48.0300,
        "aliases": ["salam", "al salam", "السلام"],
    },
    "mubarak_al_abdullah": {
        "label": "Mubarak Al-Abdullah (West Mishref)", "label_ar": "مبارك العبدالله", "gov": "hawalli",
        "lat": 29.2700, "lon": 48.0550,
        "aliases": [
            "mubarak al abdullah", "west mishref", "west mishrif",
            "مبارك العبدالله", "غرب مشرف",
        ],
    },
    # Capital
    "sharq": {
        "label": "Sharq", "label_ar": "الشرق", "gov": "capital",
        "lat": 29.3750, "lon": 47.9900,
        "aliases": ["sharq", "al sharq", "الشرق"],
    },
    "qibla": {
        "label": "Qibla", "label_ar": "القبلة", "gov": "capital",
        "lat": 29.3720, "lon": 47.9700,
        "aliases": ["qibla", "qiblah", "القبلة", "قبلة"],
    },
    "mirqab": {
        "label": "Mirqab", "label_ar": "المرقاب", "gov": "capital",
        "lat": 29.3680, "lon": 47.9780,
        "aliases": ["mirqab", "al mirqab", "المرقاب", "مرقاب"],
    },
    "dasman": {
        "label": "Dasman", "label_ar": "دسمان", "gov": "capital",
        "lat": 29.3850, "lon": 47.9950,
        "aliases": ["dasman", "دسمان"],
    },
    "dasma": {
        "label": "Dasma", "label_ar": "الدسمة", "gov": "capital",
        "lat": 29.3650, "lon": 48.0050,
        "aliases": ["dasma", "الدسمة", "دسمة"],
    },
    "shaikh_saud": {
        "label": "Shaikh Saud Al-Sabah", "label_ar": "الشيخ سعود", "gov": "capital",
        "lat": 29.3500, "lon": 47.9600,
        "aliases": ["shaikh saud", "sheikh saud", "الشيخ سعود"],
    },
    "kaifan": {
        "label": "Kaifan", "label_ar": "كيفان", "gov": "capital",
        "lat": 29.3400, "lon": 47.9600,
        "aliases": ["kaifan", "كيفان"],
    },
    "khaldiya": {
        "label": "Khaldiya", "label_ar": "الخالدية", "gov": "capital",
        "lat": 29.3300, "lon": 47.9550,
        "aliases": ["khaldiya", "khaldiyah", "الخالدية", "خالدية"],
    },
    "shamiya": {
        "label": "Shamiya", "label_ar": "الشامية", "gov": "capital",
        "lat": 29.3500, "lon": 47.9400,
        "aliases": ["shamiya", "shamiyah", "الشامية", "شامية"],
    },
    "shuwaikh": {
        "label": "Shuwaikh", "label_ar": "الشويخ", "gov": "capital",
        "lat": 29.3400, "lon": 47.9200,
        "aliases": ["shuwaikh", "shwaikh", "الشويخ", "شويخ"],
    },
    "sulaibikhat": {
        "label": "Sulaibikhat", "label_ar": "الصليبخات", "gov": "capital",
        "lat": 29.3200, "lon": 47.8500,
        "aliases": ["sulaibikhat", "sulaibikhat", "الصليبخات", "صليبخات"],
    },
    "qortuba": {
        "label": "Qortuba", "label_ar": "قرطبة", "gov": "capital",
        "lat": 29.3050, "lon": 47.9800,
        "aliases": ["qortuba", "qurtuba", "cordoba", "قرطبة"],
    },
    "yarmouk": {
        "label": "Yarmouk", "label_ar": "اليرموك", "gov": "capital",
        "lat": 29.3100, "lon": 47.9700,
        "aliases": ["yarmouk", "yarmuk", "اليرموك", "يرموك"],
    },
    "rawda": {
        "label": "Rawda", "label_ar": "الروضة", "gov": "capital",
        "lat": 29.3250, "lon": 47.9900,
        "aliases": ["rawda", "al rawda", "الروضة", "روضة"],
    },
    "udailiya": {
        "label": "Adailiya", "label_ar": "العديلية", "gov": "capital",
        "lat": 29.3150, "lon": 47.9850,
        "aliases": ["adailiya", "udailiya", "adeiliya", "العديلية", "عديلية"],
    },
    "faiha": {
        "label": "Faiha", "label_ar": "الفيحاء", "gov": "capital",
        "lat": 29.3350, "lon": 47.9700,
        "aliases": ["faiha", "faihaa", "الفيحاء", "فيحاء"],
    },
    "nuzha_capital": {
        "label": "Nuzha (Capital)", "label_ar": "النزهة", "gov": "capital",
        "lat": 29.3456, "lon": 47.9856,
        "aliases": [],  # covered by nuzha
    },
    "abdullah_al_salem": {
        "label": "Abdullah Al-Salem", "label_ar": "عبدالله السالم", "gov": "capital",
        "lat": 29.3350, "lon": 47.9500,
        "aliases": ["abdullah al salem", "abdulla al salem", "عبدالله السالم"],
    },
    "kuwait_airport": {
        "label": "Kuwait International Airport", "label_ar": "مطار الكويت", "gov": "farwaniya",
        "lat": 29.2267, "lon": 47.9689,
        "aliases": [
            "kuwait airport", "airport", "kwi", "kuwait international airport",
            "مطار الكويت", "المطار", "مطار",
        ],
    },
    "the_avenues": {
        "label": "The Avenues Mall", "label_ar": "الأفنيوز", "gov": "farwaniya",
        "lat": 29.2750, "lon": 47.9200,
        "aliases": ["avenues", "the avenues", "avenues mall", "الأفنيوز", "افنيوز"],
    },
    # Farwaniya
    "farwaniya_area": {
        "label": "Farwaniya", "label_ar": "الفروانية", "gov": "farwaniya",
        "lat": 29.2775, "lon": 47.9586,
        "aliases": ["farwaniya", "farwaniyah", "الفروانية", "فروانية"],
    },
    "khaitan": {
        "label": "Khaitan", "label_ar": "خيطان", "gov": "farwaniya",
        "lat": 29.2700, "lon": 47.9700,
        "aliases": ["khaitan", "kaitan", "خيطان"],
    },
    "jleeb": {
        "label": "Jleeb Al-Shuyoukh", "label_ar": "جليب الشيوخ", "gov": "farwaniya",
        "lat": 29.2500, "lon": 47.9200,
        "aliases": ["jleeb", "jleeb al shuyoukh", "jleeb shuyukh", "جليب الشيوخ", "جليب"],
    },
    "riggae": {
        "label": "Riggae", "label_ar": "الرقعي", "gov": "farwaniya",
        "lat": 29.2900, "lon": 47.9400,
        "aliases": ["riggae", "riqai", "الرقعي", "رقعي"],
    },
    "omariya": {
        "label": "Omariya", "label_ar": "العمرية", "gov": "farwaniya",
        "lat": 29.2800, "lon": 47.9500,
        "aliases": ["omariya", "omariah", "العمرية", "عمرية"],
    },
    "abbiya": {
        "label": "Ardiya", "label_ar": "العارضية", "gov": "farwaniya",
        "lat": 29.2700, "lon": 47.9000,
        "aliases": ["ardiya", "ardiyah", "abbiya", "العارضية", "عارضية"],
    },
    "firdous": {
        "label": "Firdous", "label_ar": "الفردوس", "gov": "farwaniya",
        "lat": 29.2600, "lon": 47.9300,
        "aliases": ["firdous", "ferdous", "الفردوس", "فردوس"],
    },
    "andalus": {
        "label": "Andalus", "label_ar": "الأندلس", "gov": "farwaniya",
        "lat": 29.2850, "lon": 47.9100,
        "aliases": ["andalus", "al andalus", "الأندلس", "اندلس"],
    },
    # Ahmadi
    "ahmadi_area": {
        "label": "Ahmadi", "label_ar": "الأحمدي", "gov": "ahmadi",
        "lat": 29.0769, "lon": 48.0839,
        "aliases": ["ahmadi", "al ahmadi", "الأحمدي", "احمدي"],
    },
    "fahaheel": {
        "label": "Fahaheel", "label_ar": "الفحيحيل", "gov": "ahmadi",
        "lat": 29.0820, "lon": 48.1300,
        "aliases": ["fahaheel", "fahameel", "الفحيحيل", "فحيحيل"],
    },
    "mangaf": {
        "label": "Mangaf", "label_ar": "المنقف", "gov": "ahmadi",
        "lat": 29.1000, "lon": 48.1200,
        "aliases": ["mangaf", "المنقف", "منقف"],
    },
    "mahboula": {
        "label": "Mahboula", "label_ar": "المهبولة", "gov": "ahmadi",
        "lat": 29.1450, "lon": 48.1200,
        "aliases": ["mahboula", "mahbola", "المهبولة", "مهبولة"],
    },
    "abu_halifa": {
        "label": "Abu Halifa", "label_ar": "أبو حليفة", "gov": "ahmadi",
        "lat": 29.1300, "lon": 48.1100,
        "aliases": ["abu halifa", "abu haleefa", "أبو حليفة", "ابو حليفة"],
    },
    "eqaila": {
        "label": "Eqaila", "label_ar": "العقيلة", "gov": "ahmadi",
        "lat": 29.1600, "lon": 48.1000,
        "aliases": ["eqaila", "aqaila", "العقيلة", "عقيلة"],
    },
    "fahad_al_ahmad": {
        "label": "Fahad Al-Ahmad", "label_ar": "فهد الأحمد", "gov": "ahmadi",
        "lat": 29.0500, "lon": 48.1000,
        "aliases": ["fahad al ahmad", "fahad ahmad", "فهد الأحمد"],
    },
    "sabahiya": {
        "label": "Sabahiya", "label_ar": "الصباحية", "gov": "ahmadi",
        "lat": 29.1100, "lon": 48.0900,
        "aliases": ["sabahiya", "sabahiyah", "الصباحية", "صباحية"],
    },
    "riqqah": {
        "label": "Riqqah", "label_ar": "الرقة", "gov": "ahmadi",
        "lat": 29.0900, "lon": 48.0700,
        "aliases": ["riqqah", "riqa", "الرقة", "رقة"],
    },
    "hadiya": {
        "label": "Hadiya", "label_ar": "هدية", "gov": "ahmadi",
        "lat": 29.0700, "lon": 48.0600,
        "aliases": ["hadiya", "hadiyah", "هدية"],
    },
    # Jahra
    "jahra_area": {
        "label": "Jahra", "label_ar": "الجهراء", "gov": "jahra",
        "lat": 29.3375, "lon": 47.6581,
        "aliases": ["jahra", "al jahra", "الجهراء", "جهراء"],
    },
    "sulaibiya": {
        "label": "Sulaibiya", "label_ar": "الصليبية", "gov": "jahra",
        "lat": 29.2800, "lon": 47.7500,
        "aliases": ["sulaibiya", "sulaibiyah", "الصليبية", "صليبية"],
    },
    "qasr": {
        "label": "Qasr", "label_ar": "القصر", "gov": "jahra",
        "lat": 29.3500, "lon": 47.6800,
        "aliases": ["qasr", "al qasr", "القصر"],
    },
    "oyoun": {
        "label": "Oyoun", "label_ar": "العيون", "gov": "jahra",
        "lat": 29.3600, "lon": 47.7000,
        "aliases": ["oyoun", "al oyoun", "العيون", "عيون"],
    },
    "nasseem": {
        "label": "Nasseem", "label_ar": "النسيم", "gov": "jahra",
        "lat": 29.3200, "lon": 47.7000,
        "aliases": ["nasseem", "naseem", "النسيم", "نسيم"],
    },
    # Mubarak Al-Kabeer
    "mubarak_al_kabeer_area": {
        "label": "Mubarak Al-Kabeer", "label_ar": "مبارك الكبير", "gov": "mubarak_al_kabeer",
        "lat": 29.2000, "lon": 48.0889,
        "aliases": ["mubarak al kabeer", "mubarak kabir", "مبارك الكبير"],
    },
    "sabah_al_salem": {
        "label": "Sabah Al-Salem", "label_ar": "صباح السالم", "gov": "mubarak_al_kabeer",
        "lat": 29.2500, "lon": 48.0800,
        "aliases": ["sabah al salem", "sabah salem", "صباح السالم"],
    },
    "adnani": {
        "label": "Adan", "label_ar": "العدان", "gov": "mubarak_al_kabeer",
        "lat": 29.2200, "lon": 48.0700,
        "aliases": ["adan", "al adan", "العدان", "عدان"],
    },
    "qusour": {
        "label": "Al-Qusour", "label_ar": "القصور", "gov": "mubarak_al_kabeer",
        "lat": 29.2100, "lon": 48.1000,
        "aliases": ["qusour", "al qusour", "القصور", "قصور"],
    },
    "messila": {
        "label": "Messila", "label_ar": "المسيلة", "gov": "mubarak_al_kabeer",
        "lat": 29.2400, "lon": 48.0900,
        "aliases": ["messila", "masila", "المسيلة", "مسيلة"],
    },
    "abu_futaira": {
        "label": "Abu Futaira", "label_ar": "أبو فطيرة", "gov": "mubarak_al_kabeer",
        "lat": 29.1900, "lon": 48.1100,
        "aliases": ["abu futaira", "abu fteira", "أبو فطيرة", "ابو فطيرة"],
    },
    "sabah_al_ahmad": {
        "label": "Sabah Al-Ahmad", "label_ar": "صباح الأحمد", "gov": "ahmadi",
        "lat": 28.7800, "lon": 48.2000,
        "aliases": ["sabah al ahmad", "sabah ahmad city", "صباح الأحمد"],
    },
    # Landmarks
    "kuwait_towers": {
        "label": "Kuwait Towers", "label_ar": "أبراج الكويت", "gov": "capital",
        "lat": 29.3892, "lon": 48.0039,
        "aliases": ["kuwait towers", "towers", "أبراج الكويت", "الابراج"],
    },
    "marina_mall": {
        "label": "Marina Mall", "label_ar": "مارينا مول", "gov": "hawalli",
        "lat": 29.3390, "lon": 48.0700,
        "aliases": ["marina", "marina mall", "مارينا", "مارينا مول"],
    },
    "360_mall": {
        "label": "360 Mall", "label_ar": "٣٦٠ مول", "gov": "hawalli",
        "lat": 29.2800, "lon": 48.0400,
        "aliases": ["360", "360 mall", "three sixty", "مول 360"],
    },
    "assima": {
        "label": "The Assima Mall", "label_ar": "الأسيمة", "gov": "capital",
        "lat": 29.3750, "lon": 47.9850,
        "aliases": ["assima", "al assima", "the assima", "assima mall", "الأسيمة", "اسيمة"],
    },
}

_ALIAS_INDEX: dict[str, str] | None = None


def _fold(text: str) -> str:
    """Normalize for matching: lowercase, strip diacritics, collapse spaces/hyphens."""
    t = (text or "").strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    t = re.sub(r"[_\-–—/\\]+", " ", t)
    t = re.sub(r"[^\w\s\u0600-\u06FF]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    # Drop leading al- / ال
    t = re.sub(r"^(al|el)\s+", "", t)
    t = re.sub(r"^ال", "", t)
    return t


def _build_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for aid, meta in AREAS.items():
        keys = [aid, meta.get("label", ""), meta.get("label_ar", "")] + list(meta.get("aliases") or [])
        for k in keys:
            f = _fold(str(k))
            if f and f not in idx:
                idx[f] = aid
    for gid, meta in GOVERNORATES.items():
        keys = [gid, meta.get("label", ""), meta.get("label_ar", "")] + list(meta.get("aliases") or [])
        for k in keys:
            f = _fold(str(k))
            if f and f not in idx:
                # store as gov:id
                idx[f] = f"gov:{gid}"
    return idx


def alias_index() -> dict[str, str]:
    global _ALIAS_INDEX
    if _ALIAS_INDEX is None:
        _ALIAS_INDEX = _build_index()
    return _ALIAS_INDEX


def resolve_kuwait_place(name: str) -> dict[str, Any] | None:
    """Resolve a spoken/typed Kuwait place to coords. Fast local lookup only."""
    raw = (name or "").strip()
    if not raw:
        return None
    folded = _fold(raw)
    if not folded:
        return None
    idx = alias_index()

    # Exact
    hit = idx.get(folded)
    # Fuzzy: startswith / contains for short Kuwaiti nicknames
    if not hit:
        for key, aid in idx.items():
            if len(folded) >= 3 and (folded in key or key in folded):
                hit = aid
                break
    if not hit:
        return None

    if hit.startswith("gov:"):
        gid = hit[4:]
        g = GOVERNORATES[gid]
        return {
            "id": gid,
            "kind": "governorate",
            "label": g["label"],
            "label_ar": g["label_ar"],
            "lat": g["lat"],
            "lon": g["lon"],
            "source": "kuwait_atlas",
            "query": raw,
        }

    a = AREAS[hit]
    return {
        "id": hit,
        "kind": "area",
        "label": a["label"],
        "label_ar": a["label_ar"],
        "gov": a.get("gov"),
        "lat": a["lat"],
        "lon": a["lon"],
        "source": "kuwait_atlas",
        "query": raw,
    }


def list_kuwait_places() -> list[dict[str, Any]]:
    out = []
    for aid, a in AREAS.items():
        out.append({
            "id": aid,
            "label": a["label"],
            "label_ar": a["label_ar"],
            "gov": a.get("gov"),
            "aliases": a.get("aliases") or [],
        })
    return out
