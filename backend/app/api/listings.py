import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, col, select

from app import config
from app.api.filters import ListingFilters, SortKey, order_clause, private_listing_ids
from app.db import get_session
from app.models import Listing, ListingImage, ScrapeRun, SourceLink
from pipeline.geo import CERTAIN_PRECISIONS
from app.schemas import (
    Envelope,
    FacetCount,
    Facets,
    ImageRef,
    ListingDetail,
    ListingSummary,
    Marker,
    Meta,
    SourceRef,
)
from scrapers.registry import SOURCE_LABELS

router = APIRouter(prefix="/api", tags=["listings"])
SessionDep = Annotated[Session, Depends(get_session)]
FiltersDep = Annotated[ListingFilters, Depends()]

MAX_PAGE_SIZE = 100


def image_url(image_id: int) -> str:
    return f"/api/images/{image_id}"


def _covers(session: Session, listings: list[Listing]) -> dict[int, str]:
    covers = {l.id: f"/media/{l.cover_path}" for l in listings if l.cover_path}
    missing = [l.id for l in listings if l.id not in covers]
    if missing:
        rows = session.exec(
            select(ListingImage.listing_id, func.min(ListingImage.id))
            .where(col(ListingImage.listing_id).in_(missing))
            .group_by(ListingImage.listing_id)
        ).all()
        covers.update({listing_id: image_url(img_id) for listing_id, img_id in rows})
    return covers


def _sources(session: Session, ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    if not ids:
        return out
    rows = session.exec(
        select(SourceLink.listing_id, SourceLink.source)
        .where(col(SourceLink.listing_id).in_(ids), SourceLink.is_active == True)  # noqa: E712
        .distinct()
    ).all()
    for listing_id, source in rows:
        out.setdefault(listing_id, []).append(source)
    return out


def _private(session: Session, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return set(session.exec(private_listing_ids().where(col(SourceLink.listing_id).in_(ids))).all())


def _summary(listing: Listing, cover: Optional[str], sources: list[str], has_private: bool) -> dict:
    price_m2 = round(listing.price / listing.surface_m2) if listing.price and listing.surface_m2 else None
    return dict(
        id=listing.id,
        contract=listing.contract,
        property_type=listing.property_type,
        title=listing.title,
        price=listing.price,
        price_per_m2=price_m2,
        surface_m2=listing.surface_m2,
        rooms=listing.rooms,
        bathrooms=listing.bathrooms,
        address=listing.address,
        frazione=listing.frazione,
        lat=listing.lat,
        lng=listing.lng,
        geo_precision=listing.geo_precision,
        position_certain=listing.geo_precision in CERTAIN_PRECISIONS,
        agency_name=listing.agency_name,
        has_private=has_private,
        cover_url=cover,
        sources=sorted(sources),
        published_at=listing.published_at or listing.first_seen_at,
        published_is_estimate=listing.published_at is None,
        is_active=listing.is_active,
    )


@router.get("/listings", response_model=Envelope[list[ListingSummary]])
def list_listings(
    session: SessionDep,
    filters: FiltersDep,
    sort: SortKey = "published_desc",
    page: int = Query(1, ge=1),
    size: int = Query(24, ge=1, le=MAX_PAGE_SIZE),
):
    base = filters.apply(select(Listing))
    total = session.exec(select(func.count()).select_from(base.subquery())).one()
    rows = session.exec(base.order_by(*order_clause(sort)).offset((page - 1) * size).limit(size)).all()
    covers = _covers(session, rows)
    ids = [r.id for r in rows]
    sources, private = _sources(session, ids), _private(session, ids)
    data = [ListingSummary(**_summary(r, covers.get(r.id), sources.get(r.id, []), r.id in private)) for r in rows]
    return Envelope(data=data, meta=Meta(total=total, page=page, size=size))


@router.get("/listings/markers", response_model=Envelope[list[Marker]])
def list_markers(session: SessionDep, filters: FiltersDep):
    query = filters.apply(
        select(
            Listing.id, Listing.lat, Listing.lng, Listing.contract,
            Listing.property_type, Listing.price, Listing.geo_precision,
        )
    ).where(col(Listing.lat).is_not(None))
    markers = [
        Marker(**row._asdict(), position_certain=row.geo_precision in CERTAIN_PRECISIONS)
        for row in session.exec(query).all()
    ]
    return Envelope(data=markers, meta=Meta(total=len(markers), page=1, size=len(markers)))


@router.get("/listings/{listing_id}", response_model=Envelope[ListingDetail])
def get_listing(listing_id: int, session: SessionDep):
    listing = session.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Annuncio non trovato")
    images = session.exec(
        select(ListingImage).where(ListingImage.listing_id == listing_id).order_by(ListingImage.position)
    ).all()
    links = session.exec(
        select(SourceLink).where(SourceLink.listing_id == listing_id).order_by(SourceLink.first_seen_at)
    ).all()
    cover = _covers(session, [listing]).get(listing.id)
    detail = ListingDetail(
        **_summary(
            listing, cover, [l.source for l in links if l.is_active], any(l.is_private and l.is_active for l in links)
        ),
        description=listing.description,
        floor=listing.floor,
        first_seen_at=listing.first_seen_at,
        last_seen_at=listing.last_seen_at,
        images=[ImageRef(id=i.id, url=image_url(i.id), caption=i.caption) for i in images],
        links=[
            SourceRef(
                source=l.source,
                label=SOURCE_LABELS.get(l.source, l.source),
                url=l.url,
                price=l.price,
                agency_name=l.agency_name,
                is_private=l.is_private,
                last_seen_at=l.last_seen_at,
                is_active=l.is_active,
            )
            for l in links
        ],
    )
    return Envelope(data=detail)


@router.get("/boundary")
def boundary():
    """GeoJSON outline of the comune, drawn on the map."""
    return json.loads(config.BOUNDARY_FILE.read_text(encoding="utf-8"))


def _facet(session: Session, column, where=None) -> list[FacetCount]:
    query = select(column, func.count()).where(Listing.is_active == True)  # noqa: E712
    if where is not None:
        query = query.where(where)
    rows = session.exec(query.group_by(column).order_by(func.count().desc())).all()
    return [FacetCount(value=v, count=c) for v, c in rows if v]


@router.get("/facets", response_model=Envelope[Facets])
def facets(session: SessionDep):
    source_rows = session.exec(
        select(SourceLink.source, func.count(func.distinct(SourceLink.listing_id)))
        .join(Listing, Listing.id == SourceLink.listing_id)
        .where(Listing.is_active == True, SourceLink.is_active == True)  # noqa: E712
        .group_by(SourceLink.source)
    ).all()
    last_update = session.exec(
        select(func.max(ScrapeRun.finished_at)).where(ScrapeRun.status == "ok")
    ).one()
    total = session.exec(select(func.count()).where(Listing.is_active == True)).one()  # noqa: E712
    certain = session.exec(
        select(func.count()).where(
            Listing.is_active == True, col(Listing.geo_precision).in_(CERTAIN_PRECISIONS)  # noqa: E712
        )
    ).one()
    private = session.exec(
        select(func.count()).where(
            Listing.is_active == True, col(Listing.id).in_(private_listing_ids())  # noqa: E712
        )
    ).one()
    return Envelope(
        data=Facets(
            property_types=_facet(session, Listing.property_type),
            frazioni=_facet(session, Listing.frazione),
            contracts=_facet(session, Listing.contract),
            positions=[
                FacetCount(value="certa", count=certain),
                FacetCount(value="incerta", count=total - certain),
            ],
            advertisers=[
                FacetCount(value="privato", count=private),
                FacetCount(value="agenzia", count=total - private),
            ],
            sources=[FacetCount(value=s, count=c) for s, c in sorted(source_rows, key=lambda r: -r[1])],
            total_active=total,
            last_update=last_update,
        )
    )
