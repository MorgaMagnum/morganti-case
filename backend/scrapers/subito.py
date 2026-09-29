"""subito.it: server-rendered Next.js; plain HTTP works."""

from scrapers.base import Contract, ParsedPage, RawListing, Scraper, ScraperError
from scrapers.parsing import clean_text, clean_title, dig, parse_datetime, script_json, to_float, to_int

BASE = "https://www.subito.it"
IMAGE_RULE = "?rule=gallery-desktop-2x-auto"
# Residential categories only (garages and offices are skipped).
RESIDENTIAL = {
    "appartamenti",
    "ville-singole-e-a-schiera",
    "loft-mansarde",
    "camere-posti-letto",
    "terreni-e-rustici",
}


def _feature(features: dict, key: str):
    return dig(features, f"/{key}", "values", 0, "key")


class SubitoScraper(Scraper):
    name = "subito"
    label = "Subito.it"
    fetch_mode = "http"

    def page_url(self, contract: Contract, page: int) -> str:
        url = f"{BASE}/annunci-toscana/{contract}/immobili/pisa/cascina/"
        return url if page <= 1 else f"{url}?o={page}"

    def parse(self, html: str, contract: Contract) -> ParsedPage:
        items = dig(script_json(html, "__NEXT_DATA__"), "props", "pageProps", "initialState", "items")
        if not isinstance(items, dict) or "originalList" not in items:
            raise ScraperError("subito: items not found in __NEXT_DATA__")
        listings = tuple(
            parsed
            for parsed in (self._parse_item(raw, contract) for raw in items["originalList"])
            if parsed is not None
        )
        return ParsedPage(listings=listings, total_pages=int(items.get("totalPages") or 1))

    def _parse_item(self, raw: dict, contract: Contract) -> RawListing | None:
        if raw.get("kind") != "AdItem":
            return None
        category = dig(raw, "category", "friendlyName")
        if category not in RESIDENTIAL:
            return None
        external_id = str(raw.get("urn", "")).rsplit(":", 1)[-1]
        if not external_id:
            return None
        features = raw.get("features") or {}
        advertiser = raw.get("advertiser") or {}
        images = raw.get("images") or []
        return RawListing(
            source=self.name,
            external_id=external_id,
            url=dig(raw, "urls", "default") or f"{BASE}/{external_id}.htm",
            contract=contract,
            title=clean_title(raw.get("subject")) or "Immobile",
            property_type_raw=category,
            description=clean_text(raw.get("body")),
            price=to_int(_feature(features, "price")),
            surface_m2=to_int(_feature(features, "size")),
            rooms=to_int(dig(features, "/room", "values", 0, "value")),
            bathrooms=to_int(dig(features, "/bathrooms", "values", 0, "value")),
            floor=dig(features, "/floor", "values", 0, "value"),
            city=dig(raw, "geo", "town", "value"),
            lat=to_float(dig(raw, "geo", "map", "latitude")),
            lng=to_float(dig(raw, "geo", "map", "longitude")),
            coords_exact=bool(dig(raw, "geo", "map", "showPin")),
            published_at=parse_datetime(raw.get("date")),
            agency_name=(advertiser.get("shopName") or advertiser.get("name")) if advertiser.get("company") else "Privato",
            image_urls=tuple(img["cdnBaseUrl"] + IMAGE_RULE for img in images if img.get("cdnBaseUrl")),
        )
