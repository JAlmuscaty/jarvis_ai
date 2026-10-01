"""Movie / TV ratings lookup (IMDb + overall scores).

Sources (in order):
1) OMDb if OMDB_API_KEY is set (best IMDb + Rotten Tomatoes + Metacritic)
2) IMDb suggestion API + title page JSON-LD (no key)
3) TVMaze for TV shows (no key)
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
OMDB_KEY = (os.environ.get("OMDB_API_KEY") or "").strip() or "trilogy"  # public demo fallback


def _omdb_key() -> str:
    return (os.environ.get("OMDB_API_KEY") or "").strip() or OMDB_KEY or "trilogy"


def _http_json(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _http_text(url: str, timeout: float = 8.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _from_omdb(title: str, year: str | None = None) -> dict[str, Any] | None:
    key = _omdb_key()
    if not key:
        return None
    q = {"apikey": key, "t": title, "plot": "short"}
    if year:
        q["y"] = year
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(q)
    try:
        data = _http_json(url, timeout=6.0)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("Response") == "False":
        return None
    ratings = {}
    for row in data.get("Ratings") or []:
        src = (row.get("Source") or "").strip()
        val = (row.get("Value") or "").strip()
        if src and val:
            ratings[src] = val
    imdb = data.get("imdbRating")
    if imdb and imdb != "N/A":
        ratings["Internet Movie Database"] = f"{imdb}/10"
    return {
        "ok": True,
        "source": "omdb",
        "title": data.get("Title") or title,
        "year": data.get("Year"),
        "type": data.get("Type"),
        "imdb_id": data.get("imdbID"),
        "imdb_rating": None if imdb in (None, "N/A") else imdb,
        "metascore": None if data.get("Metascore") in (None, "N/A") else data.get("Metascore"),
        "ratings": ratings,
        "plot": data.get("Plot") if data.get("Plot") != "N/A" else None,
        "url": f"https://www.imdb.com/title/{data.get('imdbID')}/" if data.get("imdbID") else None,
    }


def _imdb_suggest(title: str) -> dict[str, Any] | None:
    q = re.sub(r"\s+", " ", (title or "").strip())
    if not q:
        return None
    letter = re.sub(r"[^a-z0-9]", "", q.lower()[:1]) or "x"
    enc = urllib.parse.quote(q)
    url = f"https://v3.sg.media-imdb.com/suggestion/{letter}/{enc}.json"
    try:
        data = _http_json(url, timeout=5.0)
    except Exception:
        return None
    items = data.get("d") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    # Prefer movie/TV titles (tt…)
    for it in items:
        if not isinstance(it, dict):
            continue
        tid = it.get("id") or ""
        if not str(tid).startswith("tt"):
            continue
        qid = (it.get("qid") or it.get("q") or "").lower()
        if qid and qid not in ("movie", "tvSeries", "tvMiniSeries", "tvMovie", "feature", "TV series", "video"):
            # still allow unknowns with year
            if not it.get("y"):
                continue
        return {
            "imdb_id": tid,
            "title": it.get("l") or title,
            "year": it.get("y"),
            "type": it.get("qid") or it.get("q"),
            "cast": it.get("s"),
        }
    return None


def _imdb_title_ratings(imdb_id: str) -> dict[str, Any] | None:
    url = f"https://www.imdb.com/title/{imdb_id}/"
    try:
        html = _http_text(url, timeout=8.0)
    except Exception:
        return None
    # JSON-LD aggregateRating
    m = re.search(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )
    rating = None
    rating_count = None
    name = None
    typ = None
    date = None
    if m:
        try:
            blob = json.loads(m.group(1))
            if isinstance(blob, list):
                blob = next((b for b in blob if isinstance(b, dict) and b.get("@type")), blob[0] if blob else {})
            if isinstance(blob, dict):
                name = blob.get("name")
                typ = blob.get("@type")
                date = blob.get("datePublished")
                agg = blob.get("aggregateRating") or {}
                if isinstance(agg, dict):
                    rating = agg.get("ratingValue")
                    rating_count = agg.get("ratingCount")
        except Exception:
            pass
    if rating is None:
        m2 = re.search(r'"aggregateRating"\s*:\s*\{[^}]*"ratingValue"\s*:\s*"?([0-9.]+)"?', html)
        if m2:
            rating = m2.group(1)
    if rating is None:
        return None
    return {
        "ok": True,
        "source": "imdb",
        "title": name,
        "year": (str(date)[:4] if date else None),
        "type": typ,
        "imdb_id": imdb_id,
        "imdb_rating": str(rating),
        "imdb_votes": rating_count,
        "ratings": {"Internet Movie Database": f"{rating}/10"},
        "url": url,
    }


def _from_imdb(title: str) -> dict[str, Any] | None:
    hit = _imdb_suggest(title)
    if not hit:
        return None
    detail = _imdb_title_ratings(hit["imdb_id"])
    if not detail:
        return {
            "ok": False,
            "error": "Found the title on IMDb but could not read the rating page.",
            "imdb_id": hit["imdb_id"],
            "title": hit.get("title"),
            "url": f"https://www.imdb.com/title/{hit['imdb_id']}/",
        }
    detail["title"] = detail.get("title") or hit.get("title")
    detail["year"] = detail.get("year") or hit.get("year")
    detail["type"] = detail.get("type") or hit.get("type")
    return detail


def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _tvmaze_search_shows(title: str) -> list[dict[str, Any]]:
    url = "https://api.tvmaze.com/search/shows?" + urllib.parse.urlencode({"q": title})
    try:
        data = _http_json(url, timeout=8.0)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, dict) and isinstance(row.get("show"), dict):
            out.append(row["show"])
    return out


def _tvmaze_pick_show(title: str) -> dict[str, Any] | None:
    """Pick best TVMaze show — prefer anime/Animation over live-action remakes."""
    shows = _tvmaze_search_shows(title)
    if not shows:
        return None
    want = _norm_title(title)
    exact = [s for s in shows if _norm_title(str(s.get("name") or "")) == want]
    pool = exact or [
        s for s in shows
        if want and (want in _norm_title(str(s.get("name") or "")) or _norm_title(str(s.get("name") or "")) in want)
    ]
    if not pool:
        pool = shows[:1]
    anim = [s for s in pool if str(s.get("type") or "").lower() == "animation"]
    if anim:
        pool = anim
    # Prefer longest-running / earliest premiere among remaining
    pool.sort(key=lambda s: (s.get("premiered") or "9999-99-99", -(s.get("weight") or 0)))
    return pool[0]


def _from_tvmaze(title: str) -> dict[str, Any] | None:
    show = _tvmaze_pick_show(title)
    if not show:
        return None
    rating = (show.get("rating") or {}).get("average")
    if rating is None:
        return None
    externals = show.get("externals") or {}
    imdb_id = externals.get("imdb")
    return {
        "ok": True,
        "source": "tvmaze",
        "title": show.get("name") or title,
        "year": (show.get("premiered") or "")[:4] or None,
        "type": "tv",
        "imdb_id": imdb_id,
        "imdb_rating": None,
        "tvmaze_rating": rating,
        "ratings": {"TVMaze": f"{rating}/10"},
        "url": f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else show.get("url"),
        "plot": re.sub(r"<[^>]+>", "", show.get("summary") or "")[:280] or None,
    }


def _episode_abs_number(ep: dict[str, Any]) -> int | None:
    """Absolute episode # from name like 'Episode 1177' when season numbering is weird."""
    name = str(ep.get("name") or "")
    m = re.search(r"(?i)\bepisode\s+(\d+)\b", name)
    if m:
        return int(m.group(1))
    return None


def lookup_recent_episodes(title: str, *, count: int = 6) -> dict[str, Any]:
    """Last N aired episodes + ratings (TVMaze; show IMDb via OMDb when possible)."""
    title = re.sub(r"\s+", " ", (title or "").strip())
    count = max(1, min(int(count or 6), 20))
    if not title:
        return {"ok": False, "error": "Missing show title."}

    show = _tvmaze_pick_show(title)
    if not show or not show.get("id"):
        return {"ok": False, "error": f"Couldn't find a TV show matching {title!r}."}

    show_id = show["id"]
    try:
        eps = _http_json(f"https://api.tvmaze.com/shows/{show_id}/episodes", timeout=15.0)
    except Exception as exc:
        return {"ok": False, "error": f"Couldn't load episodes ({exc})."}
    if not isinstance(eps, list) or not eps:
        return {"ok": False, "error": "No episode list found for that show."}

    from datetime import date

    today = date.today().isoformat()
    past = [e for e in eps if isinstance(e, dict) and (e.get("airdate") or "") and e["airdate"] <= today]
    past.sort(key=lambda e: (e.get("airdate") or "", e.get("season") or 0, e.get("number") or 0))
    if not past:
        return {"ok": False, "error": "No aired episodes found yet."}

    # Absolute episode index (1-based in aired order) — critical for anime with year-seasons
    for i, e in enumerate(past):
        e["_abs_index"] = i + 1

    def _pack(chosen: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for e in chosen:
            rating = (e.get("rating") or {}).get("average")
            abs_n = _episode_abs_number(e) or e.get("_abs_index")
            ep_no = e.get("number")
            season = e.get("season")
            if abs_n is not None:
                label = f"Ep {abs_n}"
            elif season and ep_no and int(season or 0) < 1900:
                label = f"S{season}E{ep_no}"
            else:
                label = f"Ep {ep_no}" if ep_no is not None else "Episode"
            rows.append({
                "season": season,
                "number": ep_no,
                "absolute": abs_n,
                "label": label,
                "name": e.get("name") or "Untitled",
                "airdate": e.get("airdate"),
                "rating": rating,
                "url": e.get("url"),
            })
        return rows

    chosen = past[-count:]
    episodes = _pack(chosen)
    missing = sum(1 for e in episodes if e.get("rating") is None)
    note_extra = ""
    # If user asked for ratings and newest aren't scored yet, prefer last N that have scores
    if missing >= max(1, count // 2):
        scored = [e for e in past if (e.get("rating") or {}).get("average") is not None]
        if len(scored) >= count:
            unscored_newer = len(past) - (past.index(scored[-1]) + 1) if scored[-1] in past else missing
            episodes = _pack(scored[-count:])
            missing = 0
            note_extra = (
                f" The newest {unscored_newer} aired episode(s) aren't scored yet, "
                f"so these are the latest {count} with public ratings."
            )

    imdb_id = (show.get("externals") or {}).get("imdb")
    show_imdb = None
    omdb = _from_omdb(show.get("name") or title)
    if omdb and omdb.get("ok"):
        show_imdb = omdb.get("imdb_rating")
        imdb_id = imdb_id or omdb.get("imdb_id")

    missing = sum(1 for e in episodes if e.get("rating") is None)
    return {
        "ok": True,
        "source": "tvmaze_episodes",
        "title": show.get("name") or title,
        "year": (show.get("premiered") or "")[:4] or None,
        "type": show.get("type") or "tv",
        "imdb_id": imdb_id,
        "imdb_rating": show_imdb,
        "tvmaze_rating": (show.get("rating") or {}).get("average"),
        "count": len(episodes),
        "episodes": episodes,
        "missing_episode_ratings": missing,
        "note_extra": note_extra,
        "url": f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else show.get("url"),
    }


def format_episode_ratings_reply(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("error") or "Couldn't find those episodes."
    title = data.get("title") or "That show"
    show_bits: list[str] = []
    if data.get("imdb_rating"):
        show_bits.append(f"show IMDb {data['imdb_rating']}/10")
    elif data.get("tvmaze_rating") is not None:
        show_bits.append(f"show overall {data['tvmaze_rating']}/10")
    head = f"Last {data.get('count') or len(data.get('episodes') or [])} aired episodes of {title}"
    if show_bits:
        head += f" ({'; '.join(show_bits)})"
    lines: list[str] = []
    for e in data.get("episodes") or []:
        rating = e.get("rating")
        score = f"{rating}/10" if rating is not None else "not scored yet"
        name = e.get("name") or "Untitled"
        # Avoid "Episode 1177 — Episode 1177"
        if re.fullmatch(r"(?i)episode\s+\d+", name.strip()) and e.get("label"):
            disp = e["label"]
        else:
            disp = f"{e.get('label')}: {name}" if e.get("label") else name
        air = e.get("airdate") or ""
        lines.append(f"{disp} ({air}) — {score}" if air else f"{disp} — {score}")
    note = ""
    if data.get("note_extra"):
        note = str(data["note_extra"])
    elif data.get("missing_episode_ratings"):
        note = " Newest episodes sometimes aren't scored yet."
    return head + ":\n" + "\n".join(lines) + note


def lookup_ratings(title: str, *, year: str | None = None, prefer: str | None = None) -> dict[str, Any]:
    title = re.sub(r"\s+", " ", (title or "").strip())
    if not title:
        return {"ok": False, "error": "Missing movie/TV title."}

    prefer = (prefer or "").lower().strip()
    errors: list[str] = []

    if prefer != "tv":
        omdb = _from_omdb(title, year)
        if omdb and omdb.get("ok"):
            return omdb
        imdb = _from_imdb(title)
        if imdb and imdb.get("ok"):
            return imdb
        if imdb and imdb.get("error"):
            errors.append(str(imdb.get("error")))

    tv = _from_tvmaze(title)
    if tv and tv.get("ok"):
        # Enrich with OMDb IMDb when possible
        omdb = _from_omdb(tv.get("title") or title, year)
        if omdb and omdb.get("ok") and omdb.get("imdb_rating"):
            tv["imdb_rating"] = omdb["imdb_rating"]
            tv["ratings"] = {**(tv.get("ratings") or {}), **(omdb.get("ratings") or {})}
            tv["source"] = "tvmaze+omdb"
        return tv

    if prefer == "tv":
        omdb = _from_omdb(title, year)
        if omdb and omdb.get("ok"):
            return omdb
        imdb = _from_imdb(title)
        if imdb and imdb.get("ok"):
            return imdb

    return {
        "ok": False,
        "error": "Couldn't find ratings for that title.",
        "details": errors[:3],
        "hint": "Try the exact English title.",
    }


def format_ratings_reply(data: dict[str, Any]) -> str:
    if data.get("episodes"):
        return format_episode_ratings_reply(data)
    if not data.get("ok"):
        return data.get("error") or "Couldn't find that rating."
    title = data.get("title") or "That title"
    year = data.get("year")
    head = f"{title}" + (f" ({year})" if year else "")
    bits: list[str] = []
    if data.get("imdb_rating"):
        votes = data.get("imdb_votes")
        extra = f" from {votes:,} votes" if isinstance(votes, int) else ""
        bits.append(f"IMDb {data['imdb_rating']}/10{extra}")
    if data.get("tvmaze_rating") is not None and not data.get("imdb_rating"):
        bits.append(f"overall {data['tvmaze_rating']}/10 (TVMaze)")
    for src, val in (data.get("ratings") or {}).items():
        low = src.lower()
        if "internet movie" in low or "imdb" in low:
            continue
        if "tvmaze" in low:
            continue
        bits.append(f"{src} {val}")
    if not bits:
        return f"I found {head}, but no public rating was available."
    body = "; ".join(bits[:4])
    return f"{head}: {body}."


# Spoken / chat hard-route patterns
_RATING_RE = re.compile(
    r"(?is)^\s*(?:please\s+|can\s+you\s+)?"
    r"(?:"
    r"(?:what(?:'s|s| is)|whats)\s+(?:the\s+)?(?:imdb\s+)?(?:rating|score)\s+(?:of|for|on)\s+(.+?)"
    r"|imdb\s+(?:rating|score)\s+(?:of|for|on)\s+(.+?)"
    r"|(?:imdb|rating|score)\s+(?:of|for|on)\s+(.+?)"
    r"|(?:how\s+(?:good|rated)\s+is)\s+(.+?)"
    r"|(?:rate|rating)\s+(?:for\s+)?(.+?)"
    r")\s*[.?]?\s*$"
)

# "last 6 episodes of One Piece and their ratings"
_EPISODE_RE = re.compile(
    r"(?is)"
    r"(?:"
    r"(?:give\s+me|get|list|show|tell\s+me|what\s+(?:are|were)|whats)\s+"
    r"(?:the\s+)?"
    r"(?:last|latest|recent)\s+(\d{1,2})\s+"
    r"(?:eps?|episodes?)\s+(?:of|for|from)\s+(.+?)"
    r"|"
    r"(?:last|latest|recent)\s+(\d{1,2})\s+(?:eps?|episodes?)\s+(?:of|for|from)\s+(.+?)"
    r"|"
    r"(.+?)\s+(?:last|latest|recent)\s+(\d{1,2})\s+(?:eps?|episodes?)"
    r")"
    r"(?:\s+and\s+(?:their\s+)?(?:imdb\s+)?(?:ratings?|scores?))?"
    r"(?:\s+with\s+(?:their\s+)?(?:imdb\s+)?(?:ratings?|scores?))?"
    r"(?:\s+(?:and\s+)?(?:their\s+)?(?:imdb\s+)?(?:ratings?|scores?))?"
    r"\s*[.?!]?\s*$"
)


def extract_episode_rating_query(text: str) -> tuple[str, int] | None:
    """Return (show_title, count) for recent-episode rating asks."""
    t = (text or "").strip()
    if not t:
        return None
    if not re.search(r"(?i)\b(eps?|episodes?)\b", t):
        return None
    if not re.search(r"(?i)\b(last|latest|recent|rating|score|imdb)\b", t):
        return None
    m = _EPISODE_RE.search(t)
    if not m:
        # looser: "one piece last 6 episodes ratings"
        m2 = re.search(
            r"(?is)(.+?)\s+(?:last|latest|recent)\s+(\d{1,2})\s+(?:eps?|episodes?)",
            t,
        )
        if not m2:
            m3 = re.search(
                r"(?is)(?:last|latest|recent)\s+(\d{1,2})\s+(?:eps?|episodes?)\s+(?:of|for|from)\s+(.+)",
                t,
            )
            if not m3:
                return None
            count = int(m3.group(1))
            title = m3.group(2)
        else:
            title, count = m2.group(1), int(m2.group(2))
    else:
        g = m.groups()
        if g[0] and g[1]:
            count, title = int(g[0]), g[1]
        elif g[2] and g[3]:
            count, title = int(g[2]), g[3]
        elif g[4] and g[5]:
            title, count = g[4], int(g[5])
        else:
            return None
    title = title.strip(" .,!?;:\"'")
    title = re.sub(
        r"(?is)\s+(?:and\s+)?(?:their\s+)?(?:imdb\s+)?(?:ratings?|scores?)\s*$",
        "",
        title,
    ).strip(" .,!?;:\"'")
    title = re.sub(r"(?is)^\s*(?:the\s+)?(?:anime|show|series)\s+", "", title).strip()
    if len(title) < 2:
        return None
    return title, max(1, min(count, 20))


def extract_rating_query(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    # Episode queries handled separately
    if extract_episode_rating_query(t):
        return None
    m = _RATING_RE.match(t)
    if not m:
        m2 = re.match(
            r"(?is)^\s*(.+?)\s+(?:imdb(?:\s+rating)?|rating|score)\s*[.?]?\s*$",
            t,
        )
        if m2 and not re.search(r"\b(open|play|search|vidbox|youtube|episode|eps?)\b", m2.group(1), re.I):
            title = m2.group(1).strip(" .,!?;:\"'")
            if len(title) >= 2:
                return title
        return None
    title = next((g for g in m.groups() if g), "")
    title = title.strip(" .,!?;:\"'")
    title = re.sub(
        r"\b(the\s+movie|the\s+show|the\s+series|tv\s+show|movie|film|series)\b$",
        "",
        title,
        flags=re.I,
    ).strip(" .,!?;:\"'")
    return title or None
