"""Free maps ETA via local Kuwait atlas + public OSRM (no API key).

Geocode fallback: OpenStreetMap Nominatim (rate-limited, cached).
Routing: router.project-osrm.org driving/walking.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from kuwait_places import resolve_kuwait_place

_LOCK = threading.Lock()
_GEO_CACHE: dict[str, dict[str, Any]] = {}
_ROUTE_CACHE: dict[str, dict[str, Any]] = {}

_UA = "JarvisAI-KuwaitMaps/1.0 (personal assistant; contact: local)"
_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_OSRM = os.environ.get("JARVIS_OSRM_URL", "https://router.project-osrm.org")
_LAST_NOMINATIM = 0.0


def _cache_path() -> Path:
    logs = Path(os.environ.get("JARVIS_LOGS_DIR", str(Path(__file__).resolve().parent / "logs")))
    return logs / "maps_geo_cache.json"


def _load_disk_cache() -> None:
    p = _cache_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _GEO_CACHE.update(data)
    except Exception:
        pass


def _save_disk_cache() -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Keep cache bounded
        items = list(_GEO_CACHE.items())[-400:]
        p.write_text(json.dumps(dict(items), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_load_disk_cache()


def _http_json(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _nominatim_geocode(query: str, *, kuwait_bias: bool = True) -> dict[str, Any] | None:
    global _LAST_NOMINATIM
    q = (query or "").strip()
    if not q:
        return None
    cache_key = f"{'kw' if kuwait_bias else 'world'}:{q.lower()}"
    with _LOCK:
        if cache_key in _GEO_CACHE:
            return dict(_GEO_CACHE[cache_key])

    params: dict[str, str] = {
        "q": q if not kuwait_bias else f"{q}, Kuwait",
        "format": "json",
        "limit": "1",
    }
    if kuwait_bias:
        params["countrycodes"] = "kw"
    # Nominatim: max ~1 req/sec
    with _LOCK:
        wait = 1.05 - (time.time() - _LAST_NOMINATIM)
        if wait > 0:
            time.sleep(wait)
        _LAST_NOMINATIM = time.time()

    try:
        url = _NOMINATIM + "?" + urllib.parse.urlencode(params)
        data = _http_json(url, timeout=10.0)
    except Exception:
        if kuwait_bias:
            return _nominatim_geocode(query, kuwait_bias=False)
        return None

    if not data:
        if kuwait_bias:
            return _nominatim_geocode(query, kuwait_bias=False)
        return None
    hit = data[0]
    out = {
        "id": None,
        "kind": "geocode",
        "label": hit.get("display_name") or q,
        "label_ar": None,
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "source": "nominatim",
        "query": q,
    }
    with _LOCK:
        _GEO_CACHE[cache_key] = out
        _save_disk_cache()
    return dict(out)


def resolve_place(name: str) -> dict[str, Any] | None:
    """Resolve place: Kuwait atlas first (instant), then Nominatim."""
    local = resolve_kuwait_place(name)
    if local:
        return local
    return _nominatim_geocode(name, kuwait_bias=True)


def _osrm_route(
    origin: dict[str, Any],
    dest: dict[str, Any],
    *,
    profile: str = "driving",
) -> dict[str, Any]:
    profile = "walking" if profile == "walking" else "driving"
    key = f"{profile}:{origin['lat']:.5f},{origin['lon']:.5f}->{dest['lat']:.5f},{dest['lon']:.5f}"
    with _LOCK:
        if key in _ROUTE_CACHE:
            return dict(_ROUTE_CACHE[key])

    coords = f"{origin['lon']},{origin['lat']};{dest['lon']},{dest['lat']}"
    url = (
        f"{_OSRM.rstrip('/')}/route/v1/{profile}/{coords}"
        f"?overview=false&alternatives=false&steps=false"
    )
    try:
        data = _http_json(url, timeout=8.0)
    except Exception as exc:
        return {"ok": False, "error": f"routing unavailable: {exc}"}

    routes = data.get("routes") or []
    if not routes:
        return {"ok": False, "error": "no route found"}
    r0 = routes[0]
    seconds = float(r0.get("duration") or 0)
    meters = float(r0.get("distance") or 0)
    minutes = max(1, int(round(seconds / 60.0))) if seconds >= 30 else max(1, int(round(seconds / 60.0)) or 1)
    km = round(meters / 1000.0, 1)
    out = {
        "ok": True,
        "profile": profile,
        "duration_seconds": seconds,
        "duration_minutes": minutes,
        "distance_meters": meters,
        "distance_km": km,
        "provider": "osrm",
    }
    with _LOCK:
        _ROUTE_CACHE[key] = out
    return dict(out)


def google_maps_dir_url(origin_label: str, dest_label: str) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1&"
        + urllib.parse.urlencode({"origin": origin_label, "destination": dest_label, "travelmode": "driving"})
    )


def eta_between(
    origin_name: str,
    dest_name: str,
    *,
    profile: str = "driving",
) -> dict[str, Any]:
    """Return travel time between two places. Fast for known Kuwait areas."""
    o = resolve_place(origin_name)
    d = resolve_place(dest_name)
    if not o:
        return {"ok": False, "error": f"Could not find starting place: {origin_name}"}
    if not d:
        return {"ok": False, "error": f"Could not find destination: {dest_name}"}

    route = _osrm_route(o, d, profile=profile)
    if not route.get("ok"):
        return {
            "ok": False,
            "error": route.get("error") or "routing failed",
            "origin": o,
            "destination": d,
            "maps_url": google_maps_dir_url(o["label"], d["label"]),
        }

    mins = int(route["duration_minutes"])
    km = route["distance_km"]
    mode = "drive" if profile != "walking" else "walk"
    o_label = o["label"]
    d_label = d["label"]
    spoken = (
        f"About {mins} minute{'s' if mins != 1 else ''} to {mode} from {o_label} to {d_label}, "
        f"roughly {km} kilometers."
    )
    return {
        "ok": True,
        "origin": o,
        "destination": d,
        "duration_minutes": mins,
        "distance_km": km,
        "profile": route["profile"],
        "provider": "osrm+kuwait_atlas" if o.get("source") == "kuwait_atlas" and d.get("source") == "kuwait_atlas" else "osrm",
        "maps_url": google_maps_dir_url(o_label, d_label),
        "text": spoken,
    }
