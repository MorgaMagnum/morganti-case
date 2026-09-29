"""Where is a listing? Geofence on the comune boundary + frazione assignment."""

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from shapely.geometry import Point, shape
from shapely.prepared import prep

from app import config
from scrapers.base import RawListing

EXACT = "esatta"
STREET = "via"
APPROX = "approssimativa"
FRAZIONE = "frazione"
COMUNE = "comune"
# Positions we trust enough to draw as a real pin; everything else is "incerta".
CERTAIN_PRECISIONS = (EXACT, STREET)

BOUNDARY_TOLERANCE_M = 300  # sites sometimes snap pins to a nearby road


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[\s\-_/]+", " ", text.lower()).strip()


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    k = 111_320
    dx = (lng2 - lng1) * k * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * k
    return math.hypot(dx, dy)


distance_m = _distance_m


@dataclass(frozen=True)
class Location:
    lat: float
    lng: float
    precision: str
    frazione: Optional[str]


class Geocoder(Protocol):
    def geocode(self, address: str) -> Optional[tuple[float, float]]: ...


class CascinaGeo:
    def __init__(self, boundary_geojson: dict, frazioni: list[dict]) -> None:
        geom = shape(boundary_geojson["features"][0]["geometry"])
        self._boundary = geom
        self._prepared = prep(geom)
        self._frazioni = [f for f in frazioni if f.get("name")]
        # Longest names first so "San Lorenzo alle Corti" beats a shorter overlapping name.
        self._patterns = sorted(
            ((re.compile(rf"\b{re.escape(_fold(f['name']))}\b"), f["name"]) for f in self._frazioni),
            key=lambda item: -len(item[1]),
        )
        self.bounds = geom.bounds  # (min_lng, min_lat, max_lng, max_lat)

    @classmethod
    def from_config(cls) -> "CascinaGeo":
        boundary = json.loads(Path(config.BOUNDARY_FILE).read_text(encoding="utf-8"))
        frazioni = json.loads(Path(config.FRAZIONI_FILE).read_text(encoding="utf-8"))
        return cls(boundary, frazioni)

    def contains(self, lat: float, lng: float, tolerance_m: float = 0) -> bool:
        point = Point(lng, lat)
        if self._prepared.contains(point):
            return True
        if tolerance_m <= 0:
            return False
        degrees = tolerance_m / 111_320
        return self._boundary.distance(point) <= degrees

    def frazione_from_text(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        folded = _fold(text)
        best: tuple[int, int, str] | None = None
        for pattern, name in self._patterns:
            m = pattern.search(folded)
            if m:
                key = (m.start(), -len(name), name)
                if best is None or key < best:
                    best = key
        return best[2] if best else None

    def frazione_center(self, name: str) -> Optional[tuple[float, float]]:
        for f in self._frazioni:
            if f["name"] == name:
                return f["lat"], f["lng"]
        return None

    def nearest_frazione(self, lat: float, lng: float) -> Optional[str]:
        if not self._frazioni:
            return None
        return min(self._frazioni, key=lambda f: _distance_m(lat, lng, f["lat"], f["lng"]))["name"]

    def comune_center(self) -> tuple[float, float]:
        return self.frazione_center(config.COMUNE_NAME) or config.COMUNE_CENTER


def resolve_location(raw: RawListing, geo: CascinaGeo, geocoder: Geocoder) -> Optional[Location]:
    """Best known position of a listing, or None if it is not in the comune."""
    if raw.city and _fold(raw.city) != _fold(config.COMUNE_NAME):
        return None

    lat = lng = None
    precision: Optional[str] = None
    if raw.lat is not None and raw.lng is not None:
        if geo.contains(raw.lat, raw.lng, BOUNDARY_TOLERANCE_M):
            lat, lng = raw.lat, raw.lng
            precision = EXACT if raw.coords_exact else APPROX
        elif raw.coords_exact:
            return None

    frazione = geo.frazione_from_text(raw.zone)

    if precision in (None, APPROX) and raw.address:
        hit = geocoder.geocode(raw.address)
        if hit and geo.contains(*hit):
            lat, lng = hit
            precision = STREET

    if lat is None and frazione:
        center = geo.frazione_center(frazione)
        if center:
            lat, lng = center
            precision = FRAZIONE

    if lat is None:
        lat, lng = geo.comune_center()
        precision = COMUNE

    if frazione is None and precision != COMUNE:
        frazione = geo.nearest_frazione(lat, lng)

    return Location(lat=lat, lng=lng, precision=precision, frazione=frazione)
