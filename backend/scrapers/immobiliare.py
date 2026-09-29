"""immobiliare.it: results live in the Next.js `__NEXT_DATA__` react-query cache."""

from scrapers.base import Contract, ParsedPage, RawListing, Scraper, ScraperError
from scrapers.parsing import clean_text, clean_title, dig, script_json, to_float, to_int

BASE = "https://www.immobiliare.it"
_PATHS = {"vendita": "vendita-case", "affitto": "affitto-case"}
_PHOTO_URL = "https://pwm.im-cdn.it/image/{id}/xxl.jpg"


class ImmobiliareScraper(Scraper):
    name = "immobiliare"
    label = "Immobiliare.it"
    fetch_mode = "browser"

    def page_url(self, contract: Contract, page: int) -> str:
        url = f"{BASE}/{_PATHS[contract]}/cascina/"
        return url if page <= 1 else f"{url}?pag={page}"

    def parse(self, html: str, contract: Contract) -> ParsedPage:
        data = self._results_data(html)
        listings = []
        for result in data.get("results") or []:
            item = self._parse_result(result, contract)
            if item is not None:
                listings.append(item)
        return ParsedPage(listings=tuple(listings), total_pages=int(data.get("maxPages") or 1))

    @staticmethod
    def _results_data(html: str) -> dict:
        next_data = script_json(html, "__NEXT_DATA__")
        queries = dig(next_data, "props", "pageProps", "dehydratedState", "queries", default=[])
        for query in queries:
            data = dig(query, "state", "data")
            if isinstance(data, dict) and "results" in data:
                return data
        raise ScraperError("immobiliare: results not found in __NEXT_DATA__")

    def _parse_result(self, result: dict, contract: Contract) -> RawListing | None:
        estate = result.get("realEstate") or {}
        if not estate.get("id"):
            return None
        props = (estate.get("properties") or [{}])[0]
        location = props.get("location") or {}
        price = estate.get("price") or props.get("price") or {}
        photos = dig(props, "multimedia", "photos", default=[])
        agency = dig(estate, "advertiser", "agency", "displayName") or dig(
            estate, "advertiser", "supervisor", "displayName"
        )
        return RawListing(
            source=self.name,
            external_id=str(estate["id"]),
            url=dig(result, "seo", "url") or f"{BASE}/annunci/{estate['id']}/",
            contract=contract,
            title=clean_title(estate.get("title")) or clean_text(props.get("caption")) or "Immobile",
            property_type_raw=dig(props, "typology", "name") or dig(estate, "typology", "name"),
            description=clean_text(props.get("description")),
            price=to_int(price.get("value")) if price.get("visible", True) else None,
            surface_m2=to_int(props.get("surface")),
            rooms=to_int(props.get("rooms")),
            bathrooms=to_int(props.get("bathrooms")),
            floor=dig(props, "floor", "value"),
            address=clean_text(location.get("address")),
            zone=location.get("macrozone"),
            city=location.get("city"),
            lat=to_float(location.get("latitude")),
            lng=to_float(location.get("longitude")),
            coords_exact=location.get("marker") == "marker" and bool(location.get("address")),
            agency_name=agency or "Privato",
            image_urls=tuple(_PHOTO_URL.format(id=p["id"]) for p in photos if p.get("id")),
        )
