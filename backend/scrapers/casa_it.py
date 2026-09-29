"""casa.it: results are in `window.__INITIAL_STATE__ = JSON.parse("...")`."""

import json
import re

from scrapers.base import Contract, ParsedPage, RawListing, Scraper, ScraperError
from scrapers.parsing import clean_text, clean_title, dig, to_float, to_int

BASE = "https://www.casa.it"
IMAGE_BASE = "https://images-1.casa.it/1280x960"
_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*JSON\.parse\((\".*?\")\);?\s*</script>", re.S)


class CasaItScraper(Scraper):
    name = "casa_it"
    label = "Casa.it"
    fetch_mode = "browser"
    newest_first_query = "sortType=date-desc"

    def page_url(self, contract: Contract, page: int) -> str:
        url = f"{BASE}/{contract}/residenziale/cascina/"
        return url if page <= 1 else f"{url}?page={page}"

    def parse(self, html: str, contract: Contract) -> ParsedPage:
        search = self._search_state(html)
        listings = tuple(
            item for item in (self._parse_item(raw, contract) for raw in search.get("list") or []) if item
        )
        total_pages = int(dig(search, "paginator", "totalPages", default=1) or 1)
        return ParsedPage(listings=listings, total_pages=total_pages)

    @staticmethod
    def _search_state(html: str) -> dict:
        m = _STATE_RE.search(html)
        if not m:
            raise ScraperError("casa.it: __INITIAL_STATE__ not found")
        try:
            state = json.loads(json.loads(m.group(1)))
        except json.JSONDecodeError as exc:
            raise ScraperError(f"casa.it: invalid state JSON: {exc}") from exc
        search = state.get("search")
        if not isinstance(search, dict) or "list" not in search:
            raise ScraperError("casa.it: search results missing")
        return search

    def _parse_item(self, raw: dict, contract: Contract) -> RawListing | None:
        if not raw.get("id"):
            return None
        features = raw.get("features") or {}
        geo = raw.get("geoInfos") or {}
        price = features.get("price") or {}
        title = dig(raw, "title", "main") or "Immobile"
        extra = dig(raw, "title", "additional", default=[])
        media = dig(raw, "media", "items", default=[])
        return RawListing(
            source=self.name,
            external_id=str(raw["id"]),
            url=BASE + raw.get("uri", f"/immobili/{raw['id']}/"),
            contract=contract,
            title=clean_title(", ".join([title, *extra])),
            property_type_raw=raw.get("propertyType"),
            description=clean_text(raw.get("description")),
            price=to_int(price.get("value")) if price.get("show", True) else None,
            surface_m2=to_int(features.get("mq")),
            rooms=to_int(features.get("rooms")),
            bathrooms=to_int(features.get("bathrooms")),
            floor=clean_text(features.get("level")),
            address=clean_text(geo.get("street")) if geo.get("has_street") else None,
            zone=geo.get("district_name"),
            city=geo.get("city"),
            lat=to_float(geo.get("lat")),
            lng=to_float(geo.get("lon")),
            coords_exact=geo.get("geo_visibility_level") == 1 and bool(geo.get("has_street")),
            agency_name=dig(raw, "publisher", "publisherName") or "Privato",
            image_urls=tuple(IMAGE_BASE + m["uri"] for m in media if m.get("uri")),
        )
