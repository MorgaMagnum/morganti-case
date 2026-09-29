from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    total: int
    page: int
    size: int


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    error: Optional[str] = None
    meta: Optional[Meta] = None


class SourceRef(BaseModel):
    source: str
    label: str
    url: str
    price: Optional[int]
    agency_name: Optional[str]
    last_seen_at: datetime
    is_active: bool


class ListingSummary(BaseModel):
    id: int
    contract: str
    property_type: str
    title: str
    price: Optional[int]
    price_per_m2: Optional[int]
    surface_m2: Optional[int]
    rooms: Optional[int]
    bathrooms: Optional[int]
    address: Optional[str]
    frazione: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    geo_precision: str
    position_certain: bool
    agency_name: Optional[str]
    cover_url: Optional[str]
    sources: list[str]
    published_at: datetime  # site date if known, else first time we saw it
    published_is_estimate: bool
    is_active: bool


class ImageRef(BaseModel):
    id: int
    url: str
    caption: Optional[str]


class ListingDetail(ListingSummary):
    description: Optional[str]
    floor: Optional[str]
    first_seen_at: datetime
    last_seen_at: datetime
    images: list[ImageRef]
    links: list[SourceRef]


class Marker(BaseModel):
    id: int
    lat: float
    lng: float
    contract: str
    property_type: str
    price: Optional[int]
    geo_precision: str
    position_certain: bool


class FacetCount(BaseModel):
    value: str
    count: int


class Facets(BaseModel):
    property_types: list[FacetCount]
    frazioni: list[FacetCount]
    sources: list[FacetCount]
    contracts: list[FacetCount]
    positions: list[FacetCount]
    total_active: int
    last_update: Optional[datetime]


class RunInfo(BaseModel):
    source: str
    label: str
    contract: str
    mode: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    pages: int
    found: int
    new: int
    updated: int
    skipped: int
    error: Optional[str]


class ScrapeStatus(BaseModel):
    running: bool
    runs: list[RunInfo]
    last_full_update: Optional[datetime] = None  # removals/price changes are only checked here
