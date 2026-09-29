import io
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, delete, select

from app import config
from app.db import crawler_engine, engine, init_db
from app.main import app
from app.models import GeocodeCache, Listing, ListingImage, ScrapeRun, SourceLink
from pipeline import geocode as geocode_mod
from pipeline import runner as runner_mod
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
        surface_m2=80 + i * 15, city="Cascina", lat=43.6847, lng=10.48912 + (i % 10) * 0.004, coords_exact=True,
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


def test_quick_mode_stops_at_first_page_without_news(session, store):
    crawl_one(FakeScraper({1: [raw(1), raw(2)]}), "vendita", FakeFetcher(), store, session, 10)
    # Page 1 has one new ad, page 2 only known ones -> page 3 must not be fetched.
    scraper = FakeScraper({1: [raw(9), raw(1)], 2: [raw(2)], 3: [raw(10)]})
    fetcher = FakeFetcher()
    run = crawl_one(scraper, "vendita", fetcher, store, session, 10, quick=True)
    assert len(fetcher.urls) == 2
    assert (run.mode, run.status, run.new) == ("rapido", "ok", 1)


def test_quick_mode_asks_for_newest_first_and_never_deactivates(session, store):
    class Sorted(FakeScraper):
        newest_first_query = "sort=new"

    crawl_one(FakeScraper({1: [raw(1), raw(2)]}), "vendita", FakeFetcher(), store, session, 10)
    fetcher = FakeFetcher()
    for _ in range(3):
        crawl_one(Sorted({1: [raw(1)]}), "vendita", fetcher, store, session, 10, quick=True)
    assert fetcher.urls[0].endswith("?p=1&sort=new")
    assert all(l.is_active for l in session.exec(select(Listing)).all())


def test_quick_mode_respects_its_own_page_cap(session, store):
    pages = {i: [raw(100 + i)] for i in range(1, 20)}  # every page has news
    fetcher = FakeFetcher()
    crawl_one(FakeScraper(pages), "vendita", fetcher, store, session, 60, quick=True)
    assert len(fetcher.urls) == runner_mod.QUICK_MAX_PAGES


# ---------------- parallel run ----------------

def test_run_all_crawls_sources_in_parallel_without_duplicates(monkeypatch):
    init_db()
    with Session(engine) as s:
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.exec(delete(table))
        s.commit()

    class NamedFake(FakeScraper):
        def __init__(self, name, pages):
            super().__init__(pages)
            self.name = name

    # The same property is listed on both portals: it must end up as one listing.
    def listing_for(source, i):
        return RawListing(**{**raw(i).__dict__, "source": source})

    a = NamedFake("alpha", {1: [listing_for("alpha", i) for i in (1, 2, 3)]})
    b = NamedFake("beta", {1: [listing_for("beta", i) for i in (1, 2, 3)]})
    threads = set()

    class RecordingFetcher(FakeFetcher):
        def get(self, url):
            threads.add(threading.get_ident())
            time.sleep(0.05)
            return super().get(url)

        def close(self):
            pass

    runs = runner_mod.run_all([a, b], contracts=("vendita",), fetcher_factory=lambda _s: RecordingFetcher())
    assert sorted((r.source, r.status, r.found) for r in runs) == [("alpha", "ok", 3), ("beta", "ok", 3)]
    assert len(threads) == 2
    with Session(engine) as s:
        assert len(s.exec(select(Listing)).all()) == 3
        assert {l.source for l in s.exec(select(SourceLink)).all()} == {"alpha", "beta"}


def test_page_processing_releases_the_database_during_cover_downloads():
    # Regression: the crawler's dirty ScrapeRun was autoflushed by the first query of
    # process_page, so the thread held SQLite's write lock through the (slow) cover
    # downloads and every other crawler thread failed with "database is locked".
    init_db()
    with Session(engine) as s:
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.exec(delete(table))
        s.commit()
    downloading, release = threading.Event(), threading.Event()

    class SlowImages(NoImages):
        def fetch_many(self, urls):
            downloading.set()
            release.wait(timeout=10)
            return super().fetch_many(urls)

    def crawler_thread():
        with Session(crawler_engine, expire_on_commit=False) as s:
            run = ScrapeRun(source="fake", contract="vendita")
            s.add(run)
            s.commit()
            run.pages = 1  # pending change, as in crawl_one
            store = ListingStore(s, CascinaGeo.from_config(), NoGeocoder(), SlowImages())
            store.process_page([RawListing(**{**raw(1).__dict__, "image_urls": ("https://img/1.jpg",)})])

    worker = threading.Thread(target=crawler_thread)
    worker.start()
    try:
        assert downloading.wait(timeout=10)
        impatient = create_engine(config.DATABASE_URL, connect_args={"timeout": 1})
        with Session(impatient) as s:
            s.add(GeocodeCache(query="written during downloads", lat=None, lng=None))
            s.commit()  # raised "database is locked" before the fix
        impatient.dispose()
    finally:
        release.set()
        worker.join(timeout=30)

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
