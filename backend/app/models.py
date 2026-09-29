from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Listing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    contract: str = Field(index=True)  # vendita | affitto
    property_type: str = Field(index=True)
    title: str
    description: Optional[str] = None
    price: Optional[int] = Field(default=None, index=True)
    surface_m2: Optional[int] = Field(default=None, index=True)
    rooms: Optional[int] = None
    bathrooms: Optional[int] = None
    floor: Optional[str] = None
    address: Optional[str] = None
    frazione: Optional[str] = Field(default=None, index=True)
    lat: Optional[float] = None
    lng: Optional[float] = None
    geo_precision: str = "comune"  # esatta | via | frazione | comune
    agency_name: Optional[str] = None
    cover_path: Optional[str] = None  # relative to MEDIA_DIR
    cover_phash: Optional[str] = None
    published_at: Optional[datetime] = None
    first_seen_at: datetime = Field(default_factory=utcnow, index=True)
    last_seen_at: datetime = Field(default_factory=utcnow)
    is_active: bool = Field(default=True, index=True)


class SourceLink(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    listing_id: int = Field(foreign_key="listing.id", index=True)
    source: str = Field(index=True)
    external_id: str
    url: str
    agency_name: Optional[str] = None
    is_private: Optional[bool] = None  # owner advertising directly; None = the site does not say
    price: Optional[int] = None
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    missed_runs: int = 0
    is_active: bool = True


class ListingImage(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("listing_id", "source_url"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    listing_id: int = Field(foreign_key="listing.id", index=True)
    source_url: str
    local_path: Optional[str] = None  # relative to MEDIA_DIR
    position: int = 0
    caption: Optional[str] = None


class GeocodeCache(SQLModel, table=True):
    query: str = Field(primary_key=True)
    lat: Optional[float] = None
    lng: Optional[float] = None
    created_at: datetime = Field(default_factory=utcnow)


class ScrapeRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    contract: str
    mode: str = "completo"  # completo | rapido
    status: str = "running"  # running | ok | error
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    pages: int = 0
    found: int = 0
    new: int = 0
    updated: int = 0
    skipped: int = 0
    error: Optional[str] = None
