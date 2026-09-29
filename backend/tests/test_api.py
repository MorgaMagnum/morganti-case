from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, delete

from app.db import engine, init_db
from app.main import app
from app.models import Listing, ListingImage, ScrapeRun, SourceLink

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def make_listing(session, **kw) -> Listing:
    base = dict(
        contract="vendita",
        property_type="appartamento",
        title="Trilocale",
        price=200000,
        surface_m2=80,
        rooms=3,
        frazione="Navacchio",
        lat=43.6847,
        lng=10.48912,
        geo_precision="esatta",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    base.update(kw)
    listing = Listing(**base)
    session.add(listing)
    session.flush()
    session.add(SourceLink(listing_id=listing.id, source=kw.pop("_source", "immobiliare"),
                           external_id=str(listing.id), url=f"https://example.org/{listing.id}", price=listing.price))
    return listing


@pytest.fixture
def client():
    init_db()
    with Session(engine) as s:
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.exec(delete(table))
        a = make_listing(s, title="Villa con piscina", property_type="villa", price=500000, surface_m2=200,
                         published_at=NOW - timedelta(days=1), description="Bella villa con giardino")
        make_listing(s, title="Bilocale centro", price=120000, surface_m2=50, frazione="Cascina",
                     geo_precision="comune", published_at=NOW - timedelta(days=5))
        make_listing(s, title="Affitto trilocale", contract="affitto", price=750, surface_m2=70)
        make_listing(s, title="Prezzo su richiesta", price=None, surface_m2=90, published_at=NOW - timedelta(days=3))
        make_listing(s, title="Venduto", price=150000, is_active=False)
        s.add(ListingImage(listing_id=a.id, source_url="https://img.example.org/1.jpg", position=0))
        s.add(ScrapeRun(source="immobiliare", contract="vendita", status="ok", finished_at=NOW))
        s.commit()
    return TestClient(app)


def titles(resp):
    body = resp.json()
    assert body["success"] is True
    return [x["title"] for x in body["data"]]


def test_list_defaults_to_active_newest_first(client):
    resp = client.get("/api/listings")
    assert resp.json()["meta"]["total"] == 4
    assert titles(resp)[:3] == ["Affitto trilocale", "Villa con piscina", "Prezzo su richiesta"]


def test_filter_by_contract_and_price(client):
    resp = client.get("/api/listings", params={"contract": "vendita", "price_max": 200000})
    assert titles(resp) == ["Bilocale centro"]


def test_filter_by_type_frazione_and_text(client):
    assert titles(client.get("/api/listings", params={"types": "villa"})) == ["Villa con piscina"]
    assert titles(client.get("/api/listings", params={"frazioni": "Cascina"})) == ["Bilocale centro"]
    assert titles(client.get("/api/listings", params={"q": "giardino"})) == ["Villa con piscina"]


def test_sort_by_price_puts_unknown_prices_last(client):
    resp = client.get("/api/listings", params={"contract": "vendita", "sort": "price_asc"})
    assert titles(resp) == ["Bilocale centro", "Villa con piscina", "Prezzo su richiesta"]


def test_sort_by_price_per_m2(client):
    resp = client.get("/api/listings", params={"contract": "vendita", "sort": "price_m2_asc", "has_price": True})
    assert titles(resp) == ["Bilocale centro", "Villa con piscina"]


def test_include_inactive(client):
    resp = client.get("/api/listings", params={"include_inactive": True})
    assert resp.json()["meta"]["total"] == 5


def test_pagination(client):
    resp = client.get("/api/listings", params={"size": 2, "page": 2})
    assert resp.json()["meta"] == {"total": 4, "page": 2, "size": 2}
    assert len(resp.json()["data"]) == 2


def test_markers_follow_filters(client):
    resp = client.get("/api/listings/markers", params={"contract": "affitto"})
    data = resp.json()["data"]
    assert len(data) == 1 and data[0]["contract"] == "affitto"


def test_bbox_filter_and_validation(client):
    assert client.get("/api/listings", params={"bbox": "10.0,43.0,10.1,43.1"}).json()["meta"]["total"] == 0
    bad = client.get("/api/listings", params={"bbox": "nonsense"})
    assert bad.status_code == 422 and bad.json()["success"] is False


def test_detail_has_images_and_links(client):
    first = client.get("/api/listings", params={"types": "villa"}).json()["data"][0]
    assert first["cover_url"].startswith("/api/images/")
    detail = client.get(f"/api/listings/{first['id']}").json()["data"]
    assert detail["description"] == "Bella villa con giardino"
    assert len(detail["images"]) == 1
    assert detail["links"][0]["label"] == "Immobiliare.it"


def test_detail_404(client):
    resp = client.get("/api/listings/999999")
    assert resp.status_code == 404
    assert resp.json() == {"success": False, "data": None, "error": "Annuncio non trovato"}


def test_filter_by_position_certainty(client):
    certain = client.get("/api/listings", params={"position": "certa"}).json()["meta"]["total"]
    uncertain = titles(client.get("/api/listings", params={"position": "incerta"}))
    assert certain == 3
    assert uncertain == ["Bilocale centro"]


def test_listing_exposes_position_certainty(client):
    data = client.get("/api/listings", params={"q": "Bilocale"}).json()["data"][0]
    assert data["position_certain"] is False
    marker = client.get("/api/listings/markers", params={"q": "Villa"}).json()["data"][0]
    assert marker["position_certain"] is True


def test_facets_count_position_certainty(client):
    data = client.get("/api/facets").json()["data"]
    assert data["positions"] == [{"value": "certa", "count": 3}, {"value": "incerta", "count": 1}]


def test_search_treats_like_wildcards_literally(client):
    assert client.get("/api/listings", params={"q": "%"}).json()["meta"]["total"] == 0


def test_unknown_api_path_returns_json_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_invalid_sort_is_rejected(client):
    assert client.get("/api/listings", params={"sort": "drop table"}).status_code == 422


def test_facets(client):
    data = client.get("/api/facets").json()["data"]
    assert data["total_active"] == 4
    assert {"value": "villa", "count": 1} in data["property_types"]
    assert data["last_update"] is not None


def test_scrape_status(client):
    data = client.get("/api/scrape/status").json()["data"]
    assert data["runs"][0]["label"] == "Immobiliare.it"
    assert data["runs"][0]["mode"] == "completo"
    assert data["last_full_update"] is not None


def test_scrape_start_passes_quick_mode_to_cli(client, monkeypatch):
    from app.api import scrape as scrape_api

    launched = []

    class FakePopen:
        def __init__(self, args, **_kw):
            launched.append(args)

        def poll(self):
            return 0

    monkeypatch.setattr(scrape_api.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(scrape_api, "_process", None)
    assert client.post("/api/scrape", params={"mode": "rapido"}).json()["success"] is True
    assert client.post("/api/scrape").json()["success"] is True
    assert launched[0][-1] == "--rapido" and launched[1][-1] == "scrape"
    assert client.post("/api/scrape", params={"mode": "turbo"}).status_code == 422


def test_migration_adds_mode_column_to_old_databases(tmp_path):
    from sqlalchemy import create_engine as sa_engine

    from app.db import _migrate

    old = sa_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with old.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE scraperun (id INTEGER PRIMARY KEY, source VARCHAR, contract VARCHAR)")
        conn.exec_driver_sql("INSERT INTO scraperun (source, contract) VALUES ('subito', 'vendita')")
        _migrate(conn)
        _migrate(conn)  # idempotent
        assert conn.exec_driver_sql("SELECT mode FROM scraperun").scalar() == "completo"
