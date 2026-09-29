"""Decide whether two listings (usually from different portals) are the same property.

Agencies publish the same property on several portals with slightly different
prices, surfaces and pin positions, and almost always the same photos.
"""

from dataclasses import dataclass
from typing import Optional

import imagehash

from pipeline.geo import distance_m
from pipeline.normalize import street_key

PRICE_TOLERANCE = 0.03
SURFACE_TOLERANCE = 0.08
NEAR_METERS = 150
PHASH_MAX_DISTANCE = 6
PHASH_PRICE_TOLERANCE = 0.15
PHASH_MAX_METERS = 500
PHASH_RECOMPRESSED_MAX_DISTANCE = 10
PRECISE = {"esatta", "via"}

_TYPE_GROUP = {
    "appartamento": "flat",
    "attico / mansarda": "flat",
    "casa indipendente": "house",
    "villa": "house",
    "villetta a schiera": "house",
    "rustico / casale": "house",
    "stanza": "room",
    "terreno": "land",
}


@dataclass(frozen=True)
class Candidate:
    contract: str
    property_type: str
    price: Optional[int]
    surface_m2: Optional[int]
    rooms: Optional[int]
    lat: Optional[float]
    lng: Optional[float]
    geo_precision: str
    address_norm: Optional[str]
    frazione: Optional[str]
    phash: Optional[str] = None


def phash_distance(a: str, b: str) -> int:
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


def _close(a: Optional[int], b: Optional[int], tolerance: float) -> Optional[bool]:
    """None when unknown on either side, else whether they are within tolerance."""
    if not a or not b:
        return None
    return abs(a - b) / max(a, b) <= tolerance


def _types_compatible(a: str, b: str) -> bool:
    ga, gb = _TYPE_GROUP.get(a), _TYPE_GROUP.get(b)
    return ga is None or gb is None or ga == gb


def _far_apart(a: Candidate, b: Candidate, meters: float) -> bool:
    """True only when both positions are precise and further apart than `meters`."""
    if a.geo_precision not in PRECISE or b.geo_precision not in PRECISE or None in (a.lat, a.lng, b.lat, b.lng):
        return False
    return distance_m(a.lat, a.lng, b.lat, b.lng) > meters


def _has_civic_number(address_norm: str) -> bool:
    return street_key(address_norm) != address_norm


def _identical_numbers(a: Candidate, b: Candidate) -> bool:
    return (
        bool(_close(a.price, b.price, 0.01))
        and a.surface_m2 is not None
        and b.surface_m2 is not None
        and abs(a.surface_m2 - b.surface_m2) <= 3
    )


def is_same_property(a: Candidate, b: Candidate) -> bool:
    if a.contract != b.contract:
        return False
    price_ok = _close(a.price, b.price, PRICE_TOLERANCE)
    surface_ok = _close(a.surface_m2, b.surface_m2, SURFACE_TOLERANCE)

    photo_distance = phash_distance(a.phash, b.phash) if a.phash and b.phash else None
    if photo_distance is not None:
        # Same photo + same price and size: the same property, even if one portal
        # pins it in the wrong place or calls a "terratetto" an "appartamento".
        if photo_distance <= PHASH_MAX_DISTANCE and price_ok and surface_ok is not False:
            return True
        # Re-encoded covers (e.g. wikicasa webp) drift a few bits: demand identical numbers.
        if photo_distance <= PHASH_RECOMPRESSED_MAX_DISTANCE and _identical_numbers(a, b):
            return True
        if photo_distance <= PHASH_MAX_DISTANCE:
            # Same photo but looser numbers: guard against shared placeholders / agency
            # logos and sibling units of one building sharing a facade shot.
            return (
                _types_compatible(a.property_type, b.property_type)
                and _close(a.price, b.price, PHASH_PRICE_TOLERANCE) is not False
                and surface_ok is not False
                and not _far_apart(a, b, PHASH_MAX_METERS)
            )

    if price_ok is False or surface_ok is False:
        return False
    if price_ok is None and surface_ok is None:
        return False

    same_address = bool(a.address_norm) and a.address_norm == b.address_norm
    # Portals disagree on flat vs house labels; a full address with a civic number settles it.
    if not _types_compatible(a.property_type, b.property_type) and not (
        same_address and _has_civic_number(a.address_norm)
    ):
        return False
    if same_address:
        return True

    street_a, street_b = street_key(a.address_norm), street_key(b.address_norm)
    if street_a and street_a == street_b:
        if _has_civic_number(a.address_norm) and _has_civic_number(b.address_norm):
            return False  # same street, different civic numbers: different buildings
        return True
    if (
        a.geo_precision in PRECISE
        and b.geo_precision in PRECISE
        and None not in (a.lat, a.lng, b.lat, b.lng)
    ):
        return distance_m(a.lat, a.lng, b.lat, b.lng) <= NEAR_METERS

    # Weak location (only the frazione is known): demand near-identical numbers.
    return (
        a.frazione is not None
        and a.frazione == b.frazione
        and bool(_close(a.price, b.price, 0.01))
        and bool(_close(a.surface_m2, b.surface_m2, 0.05))
        and (not (a.rooms and b.rooms) or a.rooms == b.rooms)
    )
