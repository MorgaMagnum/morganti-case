"""idealista.it: classic server-rendered HTML cards."""

import math
import re

from selectolax.parser import HTMLParser, Node

from scrapers.base import Contract, ParsedPage, RawListing, Scraper, ScraperError, advertiser_name
from scrapers.parsing import clean_text, clean_title, to_int

BASE = "https://www.idealista.it"
PAGE_SIZE = 30
_PATHS = {"vendita": "vendita-case", "affitto": "affitto-case"}
_THUMB_SIZE_RE = re.compile(r"/blur/[^/]+/")
_COUNT_RE = re.compile(r"([\d.]+)\s+(?:case|immobili|appartamenti)")


def _split_title(title: str) -> tuple[str | None, str | None, str | None, str | None]:
    """'Casa indipendente in Via 8 Marzo, 42, Casciavola - Zambra - Laiano, Cascina'
    -> (type, address, zone, city)."""
    if " in " not in title:
        return None, None, None, None
    ptype, rest = title.split(" in ", 1)
    parts = [p.strip() for p in rest.split(",")]
    city = parts.pop() if parts else None
    zone = None
    if len(parts) >= 2 and not parts[-1][:1].isdigit():
        zone = parts.pop()
    address = ", ".join(parts) or None
    return ptype.strip(), address, zone, city


class IdealistaScraper(Scraper):
    name = "idealista"
    label = "Idealista"
    fetch_mode = "browser"
    newest_first_query = "ordine=pubblicazione-desc"

    def page_url(self, contract: Contract, page: int) -> str:
        url = f"{BASE}/{_PATHS[contract]}/cascina-pisa/"
        return url if page <= 1 else f"{url}lista-{page}.htm"

    def parse(self, html: str, contract: Contract) -> ParsedPage:
        tree = HTMLParser(html)
        cards = tree.css("article.item[data-element-id]")
        h1 = tree.css_first("h1")
        if not cards and not (h1 and _COUNT_RE.search(h1.text())):
            raise ScraperError("idealista: no result cards on page")
        listings = tuple(item for item in (self._parse_card(c, contract) for c in cards) if item)
        return ParsedPage(listings=listings, total_pages=self._total_pages(h1))

    @staticmethod
    def _total_pages(h1: Node | None) -> int:
        m = _COUNT_RE.search(h1.text()) if h1 else None
        count = int(m.group(1).replace(".", "")) if m else 0
        return max(1, math.ceil(count / PAGE_SIZE))

    def _parse_card(self, card: Node, contract: Contract) -> RawListing | None:
        ext_id = card.attributes.get("data-element-id")
        link = card.css_first("a.item-link")
        if not ext_id or link is None:
            return None
        title = clean_title(link.attributes.get("title") or link.text()) or "Immobile"
        ptype, address, zone, city = _split_title(title)
        rooms = surface = None
        floor = None
        for detail in card.css(".item-detail-char .item-detail"):
            text = detail.text(strip=True).lower()
            if "local" in text:
                rooms = to_int(text)
            elif "m²" in text or "m2" in text:
                surface = to_int(text)
            elif "piano" in text:
                floor = detail.text(strip=True)
        price_node = card.css_first(".item-price")
        description = card.css_first(".item-description")
        logo = card.css_first(".logo-branding img")
        # An agency without a logo is still an agency: the flag is the reliable signal.
        professional = card.attributes.get("data-is-professional-ad")
        is_private = None if professional is None else professional == "false"
        images = []
        for img in card.css(".item-gallery img"):
            src = img.attributes.get("src") or ""
            if "id.pro" in src or "idealista.it/blur" in src:
                images.append(_THUMB_SIZE_RE.sub("/blur/WEB_DETAIL-L-L/", src))
        return RawListing(
            source=self.name,
            external_id=ext_id,
            url=BASE + (link.attributes.get("href") or f"/immobile/{ext_id}/"),
            contract=contract,
            title=title,
            property_type_raw=ptype,
            description=clean_text(description.text()) if description else None,
            price=to_int(price_node.text()) if price_node else None,
            surface_m2=surface,
            rooms=rooms,
            floor=floor,
            address=address,
            zone=zone,
            city=city,
            agency_name=advertiser_name(logo.attributes.get("alt") if logo else None, is_private),
            is_private=is_private,
            image_urls=tuple(dict.fromkeys(images)),
        )
