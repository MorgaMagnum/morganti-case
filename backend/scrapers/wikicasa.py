"""wikicasa.it: Nuxt 3 app, results in the pinia store of the SSR payload."""

import json
import math
import re

from scrapers.base import Contract, ParsedPage, RawListing, Scraper, ScraperError
from scrapers.devalue import unflatten
from scrapers.parsing import clean_text, clean_title, dig, parse_datetime, to_int

BASE = "https://www.wikicasa.it"
PAGE_SIZE = 25
_PAYLOAD_RE = re.compile(r'<script[^>]*data-nuxt-data="nuxt-app"[^>]*>(.*?)</script>', re.S)
_PATHS = {"vendita": "vendita-case", "affitto": "affitto-case"}


def _best_image(image: dict) -> str | None:
    variants = image.get("images") or []
    by_format = {v.get("format"): v.get("storagePath") for v in variants if v.get("storagePath")}
    # format 1 = 640x480 webp; format 0 = original upload (can be several MB)
    return by_format.get(1) or by_format.get(0) or next(iter(by_format.values()), None)


class WikicasaScraper(Scraper):
    name = "wikicasa"
    label = "Wikicasa"
    fetch_mode = "browser"
    newest_first_query = ""  # already sorted by date; sort params are ignored

    def page_url(self, contract: Contract, page: int) -> str:
        url = f"{BASE}/{_PATHS[contract]}/cascina/"
        return url if page <= 1 else f"{url}?p={page}"

    def parse(self, html: str, contract: Contract) -> ParsedPage:
        store = self._listing_store(html)
        listings = tuple(
            item for item in (self._parse_item(raw, contract) for raw in store.get("realEstateList") or []) if item
        )
        count = int(store.get("listingCount") or 0)
        return ParsedPage(listings=listings, total_pages=max(1, math.ceil(count / PAGE_SIZE)))

    @staticmethod
    def _listing_store(html: str) -> dict:
        m = _PAYLOAD_RE.search(html)
        if not m:
            raise ScraperError("wikicasa: nuxt payload not found")
        try:
            payload = unflatten(json.loads(m.group(1)))
        except (json.JSONDecodeError, IndexError, TypeError) as exc:
            raise ScraperError(f"wikicasa: cannot decode payload: {exc}") from exc
        store = dig(payload, "pinia", "realEstateListingStoreId")
        if not isinstance(store, dict) or "realEstateList" not in store:
            raise ScraperError("wikicasa: listing store missing")
        return store

    def _parse_item(self, raw: dict, contract: Contract) -> RawListing | None:
        if not raw.get("realEstateID"):
            return None
        title = clean_title(raw.get("title")) or "Immobile"
        price = raw.get("price") or (raw.get("priceSale") if contract == "vendita" else raw.get("priceRent"))
        agency = raw.get("agency") or {}
        images = sorted(raw.get("reImages") or [], key=lambda i: i.get("position") or 0)
        return RawListing(
            source=self.name,
            external_id=str(raw["realEstateID"]),
            url=BASE + (raw.get("url") or f"/annuncio/{raw['realEstateID']}"),
            contract=contract,
            title=title,
            property_type_raw=title.split(" in ")[0] if " in " in title else None,
            description=clean_text(raw.get("description")),
            price=None if raw.get("reservedPrice") else to_int(price),
            surface_m2=to_int(raw.get("sqm") or raw.get("buildingSqM")),
            rooms=to_int(raw.get("rooms")),
            bathrooms=to_int(raw.get("bathrooms")),
            address=clean_text(raw.get("address")),
            city=raw.get("cityName"),
            published_at=parse_datetime(raw.get("date")),
            agency_name=agency.get("franchiseName") or agency.get("name") or "Privato",
            image_urls=tuple(url for url in (_best_image(i) for i in images) if url),
        )
