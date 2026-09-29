"""Common types for all site scrapers.

A scraper is a pure description of a site: which URLs to visit and how to parse
one search-results page into `RawListing`s. Fetching, pagination and storage are
handled by `pipeline.runner`, so parsers can be unit-tested against saved HTML.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

Contract = Literal["vendita", "affitto"]
FetchMode = Literal["http", "browser"]
CONTRACTS: tuple[Contract, ...] = ("vendita", "affitto")


@dataclass(frozen=True)
class RawListing:
    source: str
    external_id: str
    url: str
    contract: Contract
    title: str
    property_type_raw: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    surface_m2: Optional[int] = None
    rooms: Optional[int] = None
    bathrooms: Optional[int] = None
    floor: Optional[str] = None
    address: Optional[str] = None
    zone: Optional[str] = None  # frazione / quartiere as reported by the site
    city: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    coords_exact: bool = False  # True when the site pins the actual address
    published_at: Optional[datetime] = None
    agency_name: Optional[str] = None
    image_urls: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParsedPage:
    listings: tuple[RawListing, ...]
    total_pages: int


class ScraperError(Exception):
    """Raised when a page cannot be parsed (markup changed, blocked, ...)."""


class Scraper(ABC):
    name: str
    label: str
    fetch_mode: FetchMode = "browser"

    @abstractmethod
    def page_url(self, contract: Contract, page: int) -> str:
        """URL of the given (1-based) results page."""

    @abstractmethod
    def parse(self, html: str, contract: Contract) -> ParsedPage:
        """Parse one results page. Must raise ScraperError if the page is not a results page."""
