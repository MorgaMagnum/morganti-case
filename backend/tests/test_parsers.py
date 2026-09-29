"""Parser tests against real result pages saved from each site."""

from pathlib import Path

import pytest

from scrapers.base import ScraperError
from scrapers.casa_it import CasaItScraper
from scrapers.idealista import IdealistaScraper
from scrapers.immobiliare import ImmobiliareScraper
from scrapers.subito import SubitoScraper
from scrapers.wikicasa import WikicasaScraper

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def assert_common(listings, source):
    assert listings, "no listings parsed"
    ids = [x.external_id for x in listings]
    assert len(ids) == len(set(ids)), "duplicate external ids"
    for x in listings:
        assert x.source == source
        assert x.contract == "vendita"
        assert x.url.startswith("https://")
        assert x.title
        assert all(u.startswith("https://") for u in x.image_urls)
    assert sum(1 for x in listings if x.price) >= len(listings) * 0.8
    assert sum(1 for x in listings if x.image_urls) >= len(listings) * 0.8


@pytest.mark.parametrize(
    "scraper, page, expected",
    [
        # Sort parameters verified against the live sites (Sept 2026).
        (ImmobiliareScraper(), 2, "https://www.immobiliare.it/vendita-case/cascina/?pag=2&criterio=data&ordine=desc"),
        (CasaItScraper(), 1, "https://www.casa.it/vendita/residenziale/cascina/?sortType=date-desc"),
        (IdealistaScraper(), 2, "https://www.idealista.it/vendita-case/cascina-pisa/lista-2.htm?ordine=pubblicazione-desc"),
        (SubitoScraper(), 1, "https://www.subito.it/annunci-toscana/vendita/immobili/pisa/cascina/"),  # newest by default
        (WikicasaScraper(), 1, "https://www.wikicasa.it/vendita-case/cascina/"),  # newest by default
    ],
)
def test_newest_first_urls(scraper, page, expected):
    assert scraper.search_url("vendita", page, newest_first=True) == expected
    assert scraper.search_url("vendita", page) == scraper.page_url("vendita", page)


class TestImmobiliare:
    def test_parses_results_with_coordinates_and_photos(self):
        page = ImmobiliareScraper().parse(load("immobiliare_vendita.html"), "vendita")
        assert page.total_pages == 30
        assert len(page.listings) == 25
        assert_common(page.listings, "immobiliare")
        first = page.listings[0]
        assert first.external_id == "131443688"
        assert first.url == "https://www.immobiliare.it/annunci/131443688/"
        assert first.price == 209000
        assert first.surface_m2 == 144
        assert first.rooms == 4
        assert first.bathrooms == 2
        assert first.address == "Via Sirio Moggi 82"
        assert first.zone == "Navacchio"
        assert first.city == "Cascina"
        assert (first.lat, first.lng) == (43.6851, 10.4836)
        assert first.property_type_raw == "Terratetto unifamiliare"
        assert first.agency_name == "Casavo"
        assert first.image_urls[0] == "https://pwm.im-cdn.it/image/1981223370/xxl.jpg"

    def test_page_urls(self):
        s = ImmobiliareScraper()
        assert s.page_url("vendita", 1) == "https://www.immobiliare.it/vendita-case/cascina/"
        assert s.page_url("affitto", 3) == "https://www.immobiliare.it/affitto-case/cascina/?pag=3"

    def test_rejects_non_results_page(self):
        with pytest.raises(ScraperError):
            ImmobiliareScraper().parse("<html><title>blocked</title></html>", "vendita")


class TestCasaIt:
    def test_parses_results(self):
        page = CasaItScraper().parse(load("casa_vendita.html"), "vendita")
        assert page.total_pages == 41
        assert len(page.listings) == 20
        assert_common(page.listings, "casa_it")
        first = page.listings[0]
        assert first.external_id == "51700423"
        assert first.url == "https://www.casa.it/immobili/51700423/"
        assert first.price == 519000
        assert first.surface_m2 == 180
        assert first.rooms == 7
        assert first.address == "Via T. Meliani Est 31"
        assert first.zone == "Titignano-Visignano"
        assert (first.lat, first.lng) == (43.690019, 10.46319)
        assert first.agency_name == "Centrocasa Pisa"
        assert first.property_type_raw == "villa"
        assert first.image_urls[0].startswith("https://images-1.casa.it/")
        assert first.image_urls[0].endswith("/listing/0/67/27/c6/699796260.jpg")

    def test_page_urls(self):
        s = CasaItScraper()
        assert s.page_url("vendita", 1) == "https://www.casa.it/vendita/residenziale/cascina/"
        assert s.page_url("affitto", 2) == "https://www.casa.it/affitto/residenziale/cascina/?page=2"


class TestSubito:
    def test_parses_results(self):
        page = SubitoScraper().parse(load("subito_vendita.html"), "vendita")
        assert page.total_pages == 2
        assert_common(page.listings, "subito")
        first = page.listings[0]
        assert first.external_id == "662505550"
        assert first.price == 178420
        assert first.surface_m2 == 177
        assert first.city == "Cascina"
        assert first.published_at is not None and first.published_at.year == 2026
        assert first.coords_exact is False
        assert first.agency_name == "Aste Florio"
        assert first.image_urls[0].endswith("?rule=gallery-desktop-2x-auto")

    def test_uses_http_and_paginates_with_o(self):
        s = SubitoScraper()
        assert s.fetch_mode == "http"
        assert s.page_url("affitto", 2).endswith("/affitto/immobili/pisa/cascina/?o=2")


class TestWikicasa:
    def test_parses_nuxt_payload(self):
        page = WikicasaScraper().parse(load("wikicasa_vendita.html"), "vendita")
        assert page.total_pages == 37  # 907 results / 25 per page
        assert len(page.listings) == 25
        assert_common(page.listings, "wikicasa")
        first = page.listings[0]
        assert first.external_id == "30722430"
        assert first.url == "https://www.wikicasa.it/annuncio/30722430"
        assert first.price == 210000
        assert first.surface_m2 == 79
        assert first.address == "Via Mario Giuntini 65"
        assert first.property_type_raw == "Trilocale"
        assert first.lat is None  # only the city centre is exposed
        assert first.published_at is not None

    def test_page_urls_match_site_pagination_links(self):
        s = WikicasaScraper()
        html = load("wikicasa_vendita.html")
        assert s.page_url("vendita", 1) == "https://www.wikicasa.it/vendita-case/cascina/"
        assert s.page_url("vendita", 2).removeprefix("https://www.wikicasa.it") in html


class TestIdealista:
    def test_parses_html_cards(self):
        page = IdealistaScraper().parse(load("idealista_vendita.html"), "vendita")
        assert page.total_pages == 28  # 831 results / 30 per page
        assert len(page.listings) == 30
        assert_common(page.listings, "idealista")
        first = page.listings[0]
        assert first.external_id == "36423989"
        assert first.url == "https://www.idealista.it/immobile/36423989/"
        assert first.price == 235000
        assert first.rooms == 5
        assert first.surface_m2 == 100
        assert first.property_type_raw == "Casa indipendente"
        assert first.address == "Via 8 Marzo, 42"
        assert first.zone == "Casciavola - Zambra - Laiano"
        assert first.city == "Cascina"
        assert first.agency_name == "Tirrena immobiliare"
        assert "blur/480_360_mq" not in first.image_urls[0]

    def test_page_urls(self):
        s = IdealistaScraper()
        assert s.page_url("vendita", 1) == "https://www.idealista.it/vendita-case/cascina-pisa/"
        assert s.page_url("affitto", 4) == "https://www.idealista.it/affitto-case/cascina-pisa/lista-4.htm"
