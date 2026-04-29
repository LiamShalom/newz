"""Reverse-geocode cluster centroid (lat, lng) → "City, ST" string.

Uses OpenStreetMap Nominatim (free, no API key). Required by Nominatim's
usage policy: a unique User-Agent and a cache to avoid repeat lookups.

Cache key is rounded to 3 decimals (~110m precision) so two clips at the
same intersection share one lookup. Bounded to 512 entries (LRU-ish via
dict insertion order in Py3.7+); on overflow we drop the oldest.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "Newz/1.0 (hyperlocal-news-demo)"
_DEFAULT = "Pasadena, CA"
_CACHE_MAX = 512

_cache: dict[tuple[float, float], str] = {}

_US_STATE_ABBREV = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}


def _format(addr: dict) -> str | None:
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("suburb")
        or addr.get("county")
    )
    state = addr.get("state")
    country_code = (addr.get("country_code") or "").upper()
    if city and state and country_code == "US":
        return f"{city}, {_US_STATE_ABBREV.get(state, state)}"
    if city and state:
        return f"{city}, {state}"
    if city:
        return city
    return None


async def reverse_geocode(lat: float | None, lng: float | None) -> str:
    if lat is None or lng is None:
        return _DEFAULT
    key = (round(lat, 3), round(lng, 3))
    if key in _cache:
        return _cache[key]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "zoom": 10,
                    "addressdetails": 1,
                },
                headers={"User-Agent": _USER_AGENT},
            )
        if resp.status_code != 200:
            log.warning("nominatim status=%d for lat=%s lng=%s", resp.status_code, lat, lng)
            return _DEFAULT
        label = _format(resp.json().get("address", {})) or _DEFAULT
    except Exception as exc:
        log.warning("reverse_geocode failed lat=%s lng=%s: %s", lat, lng, exc)
        return _DEFAULT

    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = label
    return label
