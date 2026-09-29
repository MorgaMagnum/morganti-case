"""Persist scraped listings: insert, update, cross-portal merge, deactivation."""

import logging
from collections import Counter
from datetime import datetime
from typing import Iterable, Optional, Protocol

from sqlalchemy import func
from sqlmodel import Session, col, select

from app import config
from app.models import Listing, ListingImage, SourceLink, utcnow
from pipeline.dedup import PRICE_TOLERANCE, Candidate, is_same_property
from pipeline.geo import CascinaGeo, Geocoder, Location, resolve_location
from pipeline.images import COVER_MAX_WIDTH, cover_relpath, open_image, phash_hex, save_jpeg
from pipeline.normalize import canonical_property_type, normalize_address
from scrapers.base import RawListing

log = logging.getLogger(__name__)

PRECISION_RANK = {"esatta": 4, "via": 3, "approssimativa": 2, "frazione": 1, "comune": 0}


class ImageFetcher(Protocol):
    def fetch(self, url: str) -> Optional[bytes]: ...
    def fetch_many(self, urls: Iterable[str]) -> dict[str, Optional[bytes]]: ...


def _candidate(listing: Listing) -> Candidate:
    return Candidate(
        contract=listing.contract,
        property_type=listing.property_type,
        price=listing.price,
        surface_m2=listing.surface_m2,
        rooms=listing.rooms,
        lat=listing.lat,
        lng=listing.lng,
        geo_precision=listing.geo_precision,
        address_norm=normalize_address(listing.address),
        frazione=listing.frazione,
        phash=listing.cover_phash,
    )


def _near_identical(a: Candidate, b: Candidate) -> bool:
    """Two ads on the *same* portal are merged only when they are clearly the same
    property re-listed by different agencies: same price and practically same size."""
    return (
        bool(a.price and b.price and abs(a.price - b.price) / max(a.price, b.price) <= 0.01)
        and bool(a.surface_m2 and b.surface_m2 and abs(a.surface_m2 - b.surface_m2) <= 3)
        and (not (a.rooms and b.rooms) or a.rooms == b.rooms)
    )


class ListingStore:
    def __init__(self, session: Session, geo: CascinaGeo, geocoder: Geocoder, images: ImageFetcher) -> None:
        self._s = session
        self._geo = geo
        self._geocoder = geocoder
        self._images = images

    # ---- public API -------------------------------------------------------

    def process_page(self, raws: Iterable[RawListing]) -> Counter:
        # The same ad can appear twice on a page (e.g. a sponsored slot): keep the first.
        raws = list({(r.source, r.external_id): r for r in reversed(list(raws))}.values())[::-1]
        known = self._known_links(raws)
        covers = self._images.fetch_many(
            r.image_urls[0] for r in raws if r.image_urls and (r.source, r.external_id) not in known
        )
        counts: Counter = Counter()
        for raw in raws:
            # Commit per listing: keeps SQLite write locks short (the API may be writing
            # image cache rows) and isolates failures to a single ad.
            try:
                outcome = self.upsert(raw, known.get((raw.source, raw.external_id)), covers)
                self._s.commit()
            except Exception:
                log.exception("failed to store %s/%s", raw.source, raw.external_id)
                self._s.rollback()
                outcome = "errors"
            counts[outcome] += 1
        return counts

    def active_link_count(self, source: str, contract: str) -> int:
        return self._s.exec(
            select(func.count())
            .select_from(SourceLink)
            .join(Listing, Listing.id == SourceLink.listing_id)
            .where(SourceLink.source == source, Listing.contract == contract, SourceLink.is_active == True)  # noqa: E712
        ).one()

    def upsert(
        self,
        raw: RawListing,
        link: Optional[SourceLink],
        covers: dict[str, Optional[bytes]],
    ) -> str:
        now = utcnow()
        if link is not None:
            self._update_existing(link, raw, now)
            return "updated"

        location = resolve_location(raw, self._geo, self._geocoder)
        if location is None:
            return "skipped"

        ptype = canonical_property_type(raw.property_type_raw, raw.title)
        cover_img = None
        if raw.image_urls and covers.get(raw.image_urls[0]):
            cover_img = open_image(covers[raw.image_urls[0]])
        phash = phash_hex(cover_img) if cover_img is not None else None

        match = self._find_match(raw, location, ptype, phash)
        if match is not None:
            self._merge_into(match, raw, location, now, cover_img, phash)
            return "merged"

        self._create(raw, location, ptype, now, cover_img, phash)
        return "new"

    def finalize_missing(self, source: str, contract: str, seen: set[str]) -> int:
        """Called after a complete crawl: ads not seen accumulate misses and eventually go inactive."""
        rows = self._s.exec(
            select(SourceLink)
            .join(Listing, Listing.id == SourceLink.listing_id)
            .where(SourceLink.source == source, Listing.contract == contract, SourceLink.is_active == True)  # noqa: E712
        ).all()
        touched: set[int] = set()
        deactivated = 0
        for link in rows:
            if link.external_id in seen:
                continue
            link.missed_runs += 1
            if link.missed_runs >= config.MISSED_RUNS_BEFORE_INACTIVE:
                link.is_active = False
                deactivated += 1
                touched.add(link.listing_id)
            self._s.add(link)
        self._s.flush()
        for listing_id in touched:
            listing = self._s.get(Listing, listing_id)
            if listing is not None:
                self._refresh_from_links(listing)
        self._s.commit()
        return deactivated

    # ---- internals --------------------------------------------------------

    def _known_links(self, raws: list[RawListing]) -> dict[tuple[str, str], SourceLink]:
        known: dict[tuple[str, str], SourceLink] = {}
        by_source: dict[str, list[str]] = {}
        for r in raws:
            by_source.setdefault(r.source, []).append(r.external_id)
        for source, ids in by_source.items():
            for link in self._s.exec(
                select(SourceLink).where(SourceLink.source == source, col(SourceLink.external_id).in_(ids))
            ):
                known[(link.source, link.external_id)] = link
        return known

    def _update_existing(self, link: SourceLink, raw: RawListing, now: datetime) -> None:
        link.url = raw.url
        if raw.price is not None:  # a missing price is more often a glitch than a change
            link.price = raw.price
        link.agency_name = raw.agency_name or link.agency_name
        link.last_seen_at = now
        link.missed_runs = 0
        link.is_active = True
        self._s.add(link)
        listing = self._s.get(Listing, link.listing_id)
        if listing is None:
            return
        listing.last_seen_at = now
        if raw.description and len(raw.description) > len(listing.description or ""):
            listing.description = raw.description
        self._s.flush()
        self._refresh_from_links(listing)
        if len(raw.image_urls) > self._image_count(listing.id):
            self._replace_images(listing.id, raw.image_urls)

    def _find_match(
        self, raw: RawListing, location: Location, ptype: str, phash: Optional[str]
    ) -> Optional[Listing]:
        me = Candidate(
            contract=raw.contract,
            property_type=ptype,
            price=raw.price,
            surface_m2=raw.surface_m2,
            rooms=raw.rooms,
            lat=location.lat,
            lng=location.lng,
            geo_precision=location.precision,
            address_norm=normalize_address(raw.address),
            frazione=location.frazione,
            phash=phash,
        )
        query = select(Listing).where(Listing.contract == raw.contract)
        if phash is None and raw.price:
            low, high = raw.price * (1 - PRICE_TOLERANCE), raw.price * (1 + PRICE_TOLERANCE)
            query = query.where(col(Listing.price).between(low, high))
        elif phash is None:
            query = query.where(col(Listing.surface_m2).is_not(None))
        candidates = [l for l in self._s.exec(query) if is_same_property(me, _candidate(l))]
        if not candidates:
            return None
        same_source = self._listings_with_active_source([l.id for l in candidates], raw.source)
        for listing in candidates:
            if listing.id not in same_source or _near_identical(me, _candidate(listing)):
                return listing
        return None

    def _listings_with_active_source(self, listing_ids: list[int], source: str) -> set[int]:
        rows = self._s.exec(
            select(SourceLink.listing_id).where(
                col(SourceLink.listing_id).in_(listing_ids),
                SourceLink.source == source,
                SourceLink.is_active == True,  # noqa: E712
            )
        ).all()
        return set(rows)

    def _create(
        self, raw: RawListing, loc: Location, ptype: str, now: datetime, cover_img, phash: Optional[str]
    ) -> Listing:
        listing = Listing(
            contract=raw.contract,
            property_type=ptype,
            title=raw.title,
            description=raw.description,
            price=raw.price,
            surface_m2=raw.surface_m2,
            rooms=raw.rooms,
            bathrooms=raw.bathrooms,
            floor=raw.floor,
            address=raw.address,
            frazione=loc.frazione,
            lat=loc.lat,
            lng=loc.lng,
            geo_precision=loc.precision,
            agency_name=raw.agency_name,
            cover_phash=phash,
            published_at=raw.published_at,
            first_seen_at=now,
            last_seen_at=now,
        )
        self._s.add(listing)
        self._s.flush()
        self._add_link(listing.id, raw, now)
        self._replace_images(listing.id, raw.image_urls)
        if cover_img is not None:
            self._save_cover(listing, cover_img)
        return listing

    def _merge_into(
        self, listing: Listing, raw: RawListing, loc: Location, now: datetime, cover_img, phash: Optional[str]
    ) -> None:
        self._add_link(listing.id, raw, now)
        for field in ("surface_m2", "rooms", "bathrooms", "floor", "address"):
            if getattr(listing, field) is None and getattr(raw, field) is not None:
                setattr(listing, field, getattr(raw, field))
        if raw.description and len(raw.description) > len(listing.description or ""):
            listing.description = raw.description
        if PRECISION_RANK.get(loc.precision, 0) > PRECISION_RANK.get(listing.geo_precision, 0):
            listing.lat, listing.lng, listing.geo_precision = loc.lat, loc.lng, loc.precision
            listing.frazione = loc.frazione or listing.frazione
        if raw.published_at and (listing.published_at is None or raw.published_at < listing.published_at):
            listing.published_at = raw.published_at
        listing.last_seen_at = now
        if listing.cover_phash is None and phash:
            listing.cover_phash = phash
        if listing.cover_path is None and cover_img is not None:
            self._save_cover(listing, cover_img)
        self._s.flush()
        self._refresh_from_links(listing)
        if len(raw.image_urls) > self._image_count(listing.id):
            self._replace_images(listing.id, raw.image_urls)

    def _add_link(self, listing_id: int, raw: RawListing, now: datetime) -> None:
        self._s.add(
            SourceLink(
                listing_id=listing_id,
                source=raw.source,
                external_id=raw.external_id,
                url=raw.url,
                agency_name=raw.agency_name,
                price=raw.price,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        self._s.flush()

    def _refresh_from_links(self, listing: Listing) -> None:
        links = self._s.exec(select(SourceLink).where(SourceLink.listing_id == listing.id)).all()
        active = [l for l in links if l.is_active]
        listing.is_active = bool(active)
        prices = [l.price for l in (active or links) if l.price]
        listing.price = min(prices) if prices else None
        self._s.add(listing)

    def _image_count(self, listing_id: int) -> int:
        return len(self._s.exec(select(ListingImage.id).where(ListingImage.listing_id == listing_id)).all())

    def _replace_images(self, listing_id: int, urls: tuple[str, ...]) -> None:
        """Make the gallery match `urls`, keeping rows (ids and cached files) that stay."""
        wanted = list(dict.fromkeys(urls))
        existing = {
            img.source_url: img
            for img in self._s.exec(select(ListingImage).where(ListingImage.listing_id == listing_id)).all()
        }
        stale_files = []
        for url, img in existing.items():
            if url not in wanted:
                if img.local_path:
                    stale_files.append(config.MEDIA_DIR / img.local_path)
                self._s.delete(img)
        for pos, url in enumerate(wanted):
            img = existing.get(url) or ListingImage(listing_id=listing_id, source_url=url)
            img.position = pos
            self._s.add(img)
        self._s.flush()
        # Files are removed only after the rows are gone, and a failure here is harmless.
        for path in stale_files:
            path.unlink(missing_ok=True)

    def _save_cover(self, listing: Listing, img) -> None:
        rel = cover_relpath(listing.id)
        try:
            save_jpeg(img, config.MEDIA_DIR / rel, max_width=COVER_MAX_WIDTH)
        except OSError as exc:
            log.warning("cannot save cover for listing %s: %s", listing.id, exc)
            return
        listing.cover_path = rel
        self._s.add(listing)
