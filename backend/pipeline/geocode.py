"""Nominatim geocoder restricted to the comune, cached in the database."""

import logging
import re
import threading
import time
from typing import Optional

import httpx
from sqlmodel import Session

from app import config
from app.models import GeocodeCache

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MIN_INTERVAL_S = 1.1  # Nominatim usage policy: max 1 request/second


class GeocoderUnavailable(Exception):
    """Transient failure (HTTP error, rate limit, bad response): must not be cached."""


class NominatimGeocoder:
    """Cache rows are written through the caller's session (SQLite allows one writer)."""

    # Shared by every instance: crawler threads each own a geocoder, but Nominatim's
    # 1 request/second limit applies to this whole machine.
    _rate_lock = threading.Lock()
    _last_request = 0.0

    def __init__(self, bounds: tuple[float, float, float, float], session: Session) -> None:
        min_lng, min_lat, max_lng, max_lat = bounds
        self._viewbox = f"{min_lng},{max_lat},{max_lng},{min_lat}"
        self._session = session
        self._client = httpx.Client(headers={"User-Agent": config.GEOCODER_USER_AGENT}, timeout=20)

    def geocode(self, address: str) -> Optional[tuple[float, float]]:
        query = address.strip()
        if not query:
            return None
        cached = self._session.get(GeocodeCache, query)
        if cached is not None:
            return (cached.lat, cached.lng) if cached.lat is not None else None
        try:
            result = self._lookup(query)
            if result is None:
                # "Via Roma 12/A" not found? The street alone is still useful.
                street_only = re.sub(r"[\s,]+\d+\s*[a-zA-Z/]*\s*$", "", query)
                if street_only and street_only != query:
                    result = self._lookup(street_only)
        except GeocoderUnavailable as exc:
            # Rate limited / network down: don't cache, the next run will retry.
            log.warning("geocoding unavailable for %r: %s", query, exc)
            return None
        self._session.add(
            GeocodeCache(query=query, lat=result[0] if result else None, lng=result[1] if result else None)
        )
        self._session.flush()
        return result

    def _lookup(self, query: str) -> Optional[tuple[float, float]]:
        cls = type(self)
        with cls._rate_lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - cls._last_request)
            if wait > 0:
                time.sleep(wait)
            cls._last_request = time.monotonic()
            try:
                resp = self._client.get(
                    NOMINATIM_URL,
                    params={
                        "q": query,
                        "format": "jsonv2",
                        "limit": 1,
                        "countrycodes": "it",
                        "viewbox": self._viewbox,
                        "bounded": 1,
                    },
                )
                resp.raise_for_status()
                hits = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise GeocoderUnavailable(str(exc)) from exc
        if not hits:
            return None
        return float(hits[0]["lat"]), float(hits[0]["lon"])

    def close(self) -> None:
        self._client.close()
