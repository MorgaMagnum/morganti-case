import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import engine, init_db
from app.main import app
from app.models import GeocodeCache, Listing, ListingImage, ScrapeRun
from pipeline import geocode as geocode_mod
from pipeline.geo import CascinaGeo
from pipeline.geocode import NominatimGeocoder
from pipeline.runner import crawl_one
from pipeline.store import ListingStore
from scrapers.base import ParsedPage, RawListing, Scraper, ScraperError
from scrapers.fetchers import FetchError


@pytest.fixture
def session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng, expire_on_commit=False) as s:
        yield s


# ---------------- runner ----------------

def raw(i: int) -> RawListing:
    return RawListing(
        source="fake", external_id=str(i), url=f"https://fake/{i}", contract="vendita",
        title=f"Casa {i}", property_type_raw="Casa indipendente", price=100000 + i * 20000,
        surface_m2=80 + i * 15, city="Cascina", lat=43.6847, lng=10.48912 + i * 0.01, coords_exact=True,
        address=f"Via Numero {i}",
    )


class FakeScraper(Scraper):
    name = "fake"
    label = "Fake"
    fetch_mode = "http"

    def __init__(self, pages: dict[int, list[RawListing]], fail_on: int | None = None):
        self.pages = pages
        self.fail_on = fail_on

    def page_url(self, contract, page):
        return f"https://fake/{contract}?p={page}"

    def parse(self, html, contract):
        page = int(html)
        if page == self.fail_on:
            raise ScraperError("markup changed")
        return ParsedPage(listings=tuple(self.pages.get(page, [])), total_pages=len(self.pages))


class FakeFetcher:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return url.rsplit("=", 1)[1]


class NoImages:
    def fetch(self, url):
        return None

    def fetch_many(self, urls):
        return {u: None for u in urls}


class NoGeocoder:
    def geocode(self, address):
        return None


@pytest.fixture
def store(session):
    return ListingStore(session, CascinaGeo.from_config(), NoGeocoder(), NoImages())


def test_crawl_walks_all_pages_and_records_run(session, store):
    scraper = FakeScraper({1: [raw(1), raw(2)], 2: [raw(3)]})
    fetcher = FakeFetcher()
    run = crawl_one(scraper, "vendita", fetcher, store, session, max_pages=10)
    assert run.status == "ok"
    assert (run.pages, run.found, run.new) == (2, 3, 3)
    assert fetcher.urls == ["https://fake/vendita?p=1", "https://fake/vendita?p=2"]
    assert len(session.exec(select(Listing)).all()) == 3


def test_crawl_stops_when_site_repeats_the_same_page(session, store):
    scraper = FakeScraper({1: [raw(1), raw(2)], 2: [raw(1), raw(2)], 3: [raw(1), raw(2)]})
    fetcher = FakeFetcher()
    run = crawl_one(scraper, "vendita", fetcher, store, session, max_pages=10)
    assert len(fetcher.urls) == 2
    assert run.found == 2 and run.status == "ok"


def test_repeated_pages_do_not_deactivate_unseen_ads(session, store):
    crawl_one(FakeScraper({1: [raw(1)], 2: [raw(2)]}), "vendita", FakeFetcher(), store, session, 10)
    broken = FakeScraper({1: [raw(1)], 2: [raw(1)]})  # pagination parameter ignored by the site
    for _ in range(3):
        crawl_one(broken, "vendita", FakeFetcher(), store, session, 10)
    assert all(l.is_active for l in session.exec(select(Listing)).all())


def test_crawl_stops_at_max_pages_and_skips_removal_check(session, store):
    crawl_one(FakeScraper({1: [raw(1)], 2: [raw(2)]}), "vendita", FakeFetcher(), store, session, 10)
    # Next runs only see page 1 because of max_pages: raw(2) must NOT be deactivated.
    for _ in range(3):
        crawl_one(FakeScraper({1: [raw(1)], 2: [raw(2)]}), "vendita", FakeFetcher(), store, session, 1)
    assert all(l.is_active for l in session.exec(select(Listing)).all())


def test_crawl_complete_run_deactivates_missing_ads(session, store):
    crawl_one(FakeScraper({1: [raw(1), raw(2)]}), "vendita", FakeFetcher(), store, session, 10)
    for _ in range(2):
        crawl_one(FakeScraper({1: [raw(1)]}), "vendita", FakeFetcher(), store, session, 10)
    active = {l.title: l.is_active for l in session.exec(select(Listing)).all()}
    assert active == {"Casa 1": True, "Casa 2": False}


def test_crawl_records_parse_errors_without_raising(session, store):
    run = crawl_one(FakeScraper({1: [raw(1)], 2: [raw(2)]}, fail_on=2), "vendita", FakeFetcher(), store, session, 10)
    assert run.status == "error"
    assert "markup changed" in run.error
    assert run.found == 1  # page 1 was stored
    assert session.exec(select(ScrapeRun)).one().finished_at is not None


def test_crawl_records_fetch_errors(session, store):
    class Broken(FakeFetcher):
        def get(self, url):
            raise FetchError("HTTP 403")

    run = crawl_one(FakeScraper({1: [raw(1)]}), "vendita", Broken(), store, session, 10)
    assert (run.status, run.error) == ("error", "HTTP 403")


# ---------------- geocoder ----------------

@pytest.fixture
def geocoder(session, monkeypatch):
    monkeypatch.setattr(geocode_mod, "MIN_INTERVAL_S", 0)
    calls = []

    def handler(request: httpx.Request):
        q = request.url.params["q"]
        calls.append(q)
        if q == "Via Giuntini":
            return httpx.Response(200, json=[{"lat": "43.6847", "lon": "10.48912"}])
        if q == "Via Occupata":
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json=[])

    coder = NominatimGeocoder(CascinaGeo.from_config().bounds, session)
    coder._client = httpx.Client(transport=httpx.MockTransport(handler))
    coder.calls = calls
    return coder


def test_geocoder_falls_back_to_street_and_caches(geocoder, session):
    assert geocoder.geocode("Via Giuntini 65") == (43.6847, 10.48912)
    assert geocoder.calls == ["Via Giuntini 65", "Via Giuntini"]
    assert geocoder.geocode("Via Giuntini 65") == (43.6847, 10.48912)
    assert len(geocoder.calls) == 2  # served from cache
    assert session.get(GeocodeCache, "Via Giuntini 65").lat == 43.6847


def test_geocoder_caches_misses(geocoder):
    assert geocoder.geocode("Via Inesistente") is None
    assert geocoder.geocode("Via Inesistente") is None
    assert geocoder.calls == ["Via Inesistente"]
    assert geocoder.geocode("   ") is None


def test_geocoder_does_not_cache_rate_limit_errors(geocoder):
    assert geocoder.geocode("Via Occupata") is None
    assert geocoder.geocode("Via Occupata") is None
    assert geocoder.calls == ["Via Occupata", "Via Occupata"]


# ---------------- image endpoint ----------------

def jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (50, 40), "red").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def image_row():
    init_db()
    with Session(engine) as s:
        listing = Listing(contract="vendita", property_type="villa", title="Villa")
        s.add(listing)
        s.flush()
        img = ListingImage(listing_id=listing.id, source_url="https://cdn.example.org/a.jpg")
        s.add(img)
        s.commit()
        return img.id


def test_image_is_downloaded_once_then_served_from_disk(image_row, monkeypatch):
    from app.api import images as images_api

    calls = []

    class FakeClient:
        def fetch(self, url):
            calls.append(url)
            return jpeg_bytes()

    monkeypatch.setattr(images_api, "_image_client", lambda: FakeClient())
    client = TestClient(app)
    first = client.get(f"/api/images/{image_row}")
    second = client.get(f"/api/images/{image_row}")
    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert calls == ["https://cdn.example.org/a.jpg"]


def test_image_download_failure_redirects_to_source(image_row, monkeypatch):
    from app.api import images as images_api

    monkeypatch.setattr(images_api, "_image_client", lambda: type("C", (), {"fetch": lambda self, u: None})())
    resp = TestClient(app).get(f"/api/images/{image_row}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://cdn.example.org/a.jpg"


def test_unknown_image_404():
    init_db()
    assert TestClient(app).get("/api/images/987654").status_code == 404
