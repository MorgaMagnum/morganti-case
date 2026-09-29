"""Query parameters shared by the list and map endpoints."""

from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import HTTPException, Query
from sqlalchemy import func, or_
from sqlmodel import col, select

from app.models import Listing, SourceLink
from pipeline.geo import CERTAIN_PRECISIONS

SortKey = Literal["published_desc", "published_asc", "price_asc", "price_desc", "m2_desc", "price_m2_asc"]

published_expr = func.coalesce(Listing.published_at, Listing.first_seen_at)


def private_listing_ids():
    """Listings with at least one active ad published by the owner."""
    return select(SourceLink.listing_id).where(
        SourceLink.is_private == True, SourceLink.is_active == True  # noqa: E712
    )


def _csv(value: Optional[str]) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


@dataclass
class ListingFilters:
    contract: Optional[Literal["vendita", "affitto"]] = Query(None)
    types: Optional[str] = Query(None, description="tipologie separate da virgola")
    frazioni: Optional[str] = Query(None, description="frazioni separate da virgola")
    sources: Optional[str] = Query(None, description="fonti separate da virgola")
    price_min: Optional[int] = Query(None, ge=0)
    price_max: Optional[int] = Query(None, ge=0)
    m2_min: Optional[int] = Query(None, ge=0)
    m2_max: Optional[int] = Query(None, ge=0)
    rooms_min: Optional[int] = Query(None, ge=0, le=20)
    position: Optional[Literal["certa", "incerta"]] = Query(None, description="certezza della posizione")
    advertiser: Optional[Literal["privato", "agenzia"]] = Query(
        None, description="privato: almeno un annuncio pubblicato dal proprietario; agenzia: nessuno"
    )
    has_price: bool = Query(False)
    include_inactive: bool = Query(False)
    q: Optional[str] = Query(None, max_length=100)
    bbox: Optional[str] = Query(None, description="minLng,minLat,maxLng,maxLat")

    def apply(self, query):
        if not self.include_inactive:
            query = query.where(Listing.is_active == True)  # noqa: E712
        if self.contract:
            query = query.where(Listing.contract == self.contract)
        if types := _csv(self.types):
            query = query.where(col(Listing.property_type).in_(types))
        if frazioni := _csv(self.frazioni):
            query = query.where(col(Listing.frazione).in_(frazioni))
        if sources := _csv(self.sources):
            linked = select(SourceLink.listing_id).where(
                col(SourceLink.source).in_(sources), SourceLink.is_active == True  # noqa: E712
            )
            query = query.where(col(Listing.id).in_(linked))
        if self.advertiser == "privato":
            query = query.where(col(Listing.id).in_(private_listing_ids()))
        elif self.advertiser == "agenzia":
            query = query.where(col(Listing.id).not_in(private_listing_ids()))
        if self.position == "certa":
            query = query.where(col(Listing.geo_precision).in_(CERTAIN_PRECISIONS))
        elif self.position == "incerta":
            query = query.where(col(Listing.geo_precision).not_in(CERTAIN_PRECISIONS))
        if self.price_min is not None:
            query = query.where(Listing.price >= self.price_min)
        if self.price_max is not None:
            query = query.where(Listing.price <= self.price_max)
        if self.m2_min is not None:
            query = query.where(Listing.surface_m2 >= self.m2_min)
        if self.m2_max is not None:
            query = query.where(Listing.surface_m2 <= self.m2_max)
        if self.rooms_min is not None:
            query = query.where(Listing.rooms >= self.rooms_min)
        if self.has_price:
            query = query.where(col(Listing.price).is_not(None))
        if self.q:
            escaped = self.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            query = query.where(
                or_(
                    col(Listing.title).ilike(like, escape="\\"),
                    col(Listing.description).ilike(like, escape="\\"),
                    col(Listing.address).ilike(like, escape="\\"),
                    col(Listing.agency_name).ilike(like, escape="\\"),
                )
            )
        if self.bbox:
            query = query.where(*self._bbox_clauses())
        return query

    def _bbox_clauses(self):
        try:
            min_lng, min_lat, max_lng, max_lat = (float(x) for x in self.bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="bbox deve essere minLng,minLat,maxLng,maxLat") from exc
        return (
            col(Listing.lat).between(min_lat, max_lat),
            col(Listing.lng).between(min_lng, max_lng),
        )


def order_clause(sort: SortKey):
    price_m2 = Listing.price * 1.0 / func.nullif(Listing.surface_m2, 0)
    return {
        "published_desc": (published_expr.desc(), Listing.id.desc()),
        "published_asc": (published_expr.asc(), Listing.id.asc()),
        "price_asc": (col(Listing.price).is_(None), Listing.price.asc(), Listing.id),
        "price_desc": (col(Listing.price).is_(None), Listing.price.desc(), Listing.id),
        "m2_desc": (col(Listing.surface_m2).is_(None), Listing.surface_m2.desc(), Listing.id),
        "price_m2_asc": (price_m2.is_(None), price_m2.asc(), Listing.id),
    }[sort]
