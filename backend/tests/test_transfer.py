import csv
import importlib
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, delete, select

from app import config
from app.db import engine, init_db
from app.models import Listing, ListingImage, SourceLink
from pipeline.transfer import COLUMNS, ImportFileError, export_csv, import_csv

T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)


def wipe():
    with Session(engine) as s:
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.exec(delete(table))
        s.commit()


def add_listing(s: Session, ext="1", source="immobiliare", seen=T0, **kw) -> Listing:
    fields = dict(contract="vendita", property_type="appartamento", title="Trilocale in centro", price=200000,
                  surface_m2=80, rooms=3, frazione="Navacchio", lat=43.68, lng=10.49, geo_precision="esatta",
                  agency_name="Agenzia Uno", description="Luminoso, con balcone", first_seen_at=seen - timedelta(days=3),
                  last_seen_at=seen, cover_path="covers/1.jpg")
    fields.update(kw)
    listing = Listing(**fields)
    s.add(listing)
    s.flush()
    s.add(SourceLink(listing_id=listing.id, source=source, external_id=ext, url=f"https://example.org/{ext}",
                     agency_name=fields["agency_name"], price=fields["price"], first_seen_at=fields["first_seen_at"],
                     last_seen_at=seen))
    for pos, url in enumerate(["https://img.example.org/a.jpg", "https://img.example.org/b.jpg"]):
        s.add(ListingImage(listing_id=listing.id, source_url=url, position=pos))
    return listing


@pytest.fixture
def db():
    init_db()
    wipe()
    with Session(engine) as s:
        add_listing(s)
        private = add_listing(s, ext="p9", source="subito", title="=HYPERLINK(\"x\") villa", agency_name="Privato",
                              contract="affitto", price=900, is_active=False, published_at=T0)
        link = s.exec(select(SourceLink).where(SourceLink.listing_id == private.id)).one()
        link.is_private, link.is_active = True, False
        s.commit()
    yield
    wipe()


def exported() -> str:
    with Session(engine) as s:
        return export_csv(s)


def do_import(text: str):
    with Session(engine) as s:
        return import_csv(s, text)


def snapshot():
    with Session(engine) as s:
        listings = sorted(
            (l.title, l.contract, l.price, l.surface_m2, l.frazione, l.lat, l.geo_precision, l.agency_name,
             l.is_active, l.published_at, l.first_seen_at, l.last_seen_at, l.description)
            for l in s.exec(select(Listing)).all()
        )
        links = sorted((l.source, l.external_id, l.url, l.is_private, l.price, l.is_active, l.last_seen_at)
                       for l in s.exec(select(SourceLink)).all())
        photos = sorted((i.source_url, i.position) for i in s.exec(select(ListingImage)).all())
        return listings, links, photos


def rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def to_csv(data: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, delimiter=";")
    writer.writeheader()
    writer.writerows(data)
    return buf.getvalue()


def test_export_has_one_row_per_listing_with_links_and_photos(db):
    data = rows(exported())
    assert list(data[0].keys()) == COLUMNS
    assert len(data) == 2
    private = next(r for r in data if r["contratto"] == "affitto")
    assert private["privato"] == "no"  # the private ad is no longer online
    assert private["online"] == "no"
    assert json.loads(private["annunci"])[0] == {
        "fonte": "subito", "id": "p9", "url": "https://example.org/p9", "agenzia": "Privato", "privato": True,
        "prezzo": 900, "visto_la_prima_volta": "2026-08-29T08:00:00Z", "visto_l_ultima_volta": "2026-09-01T08:00:00Z",
        "online": False,
    }
    assert json.loads(private["foto"]) == ["https://img.example.org/a.jpg", "https://img.example.org/b.jpg"]


def test_export_neutralises_spreadsheet_formulas_and_import_restores_them(db):
    text = exported()
    assert "'=HYPERLINK" in text
    wipe()
    do_import(text)
    with Session(engine) as s:
        assert s.exec(select(Listing).where(Listing.contract == "affitto")).one().title == '=HYPERLINK("x") villa'


def test_import_into_an_empty_copy_reproduces_everything(db):
    before = snapshot()
    text = exported()
    wipe()
    result = do_import(text)
    assert (result.rows, result.new, result.error_count) == (2, 2, 0)
    assert snapshot() == before
    with Session(engine) as s:
        assert all(l.cover_path is None for l in s.exec(select(Listing)))  # covers are local files: not shipped


def test_importing_the_same_file_twice_changes_nothing(db):
    text = exported()
    before = snapshot()
    result = do_import(text)
    assert (result.new, result.updated, result.unchanged) == (0, 0, 2)
    assert snapshot() == before


def test_newer_rows_update_and_older_rows_are_ignored(db):
    newer, older = (dict(r) for r in rows(exported()))
    newer.update(prezzo="185000", visto_l_ultima_volta="2026-09-10T08:00:00Z")
    older.update(prezzo="1", visto_l_ultima_volta="2026-01-01T08:00:00Z")
    result = do_import(to_csv([newer, older]))
    assert (result.updated, result.unchanged) == (1, 1)
    with Session(engine) as s:
        prices = {l.contract: l.price for l in s.exec(select(Listing))}
    assert prices == {"vendita": 185000, "affitto": 900}


def test_row_matching_a_known_ad_extends_that_listing(db):
    row = dict(rows(exported())[0])
    links = json.loads(row["annunci"]) + [{"fonte": "casa_it", "id": "c1", "url": "https://example.org/c1",
                                           "privato": True, "online": True}]
    row.update(annunci=json.dumps(links), visto_l_ultima_volta="2026-09-10T08:00:00Z")
    result = do_import(to_csv([row]))
    assert result.updated == 1
    with Session(engine) as s:
        assert len(s.exec(select(Listing)).all()) == 2
        assert s.exec(select(SourceLink).where(SourceLink.source == "casa_it")).one().is_private is True


def test_bad_rows_are_skipped_and_reported(db):
    good, bad = (dict(r) for r in rows(exported()))
    bad.update(contratto="baratto")
    unsafe = dict(good, annunci=json.dumps([{"fonte": "x", "id": "9", "url": "javascript:alert(1)"}]))
    wipe()
    result = do_import(to_csv([good, bad, unsafe]))
    assert (result.new, result.error_count) == (1, 2)
    assert result.errors[0].startswith("Riga 3: contratto")
    assert "link valido" in result.errors[1]


def test_non_http_photo_urls_are_dropped(db):
    row = dict(rows(exported())[0], foto=json.dumps(["https://ok.example.org/1.jpg", "file:///etc/passwd"]))
    wipe()
    do_import(to_csv([row]))
    with Session(engine) as s:
        assert [i.source_url for i in s.exec(select(ListingImage))] == ["https://ok.example.org/1.jpg"]


def test_file_that_is_not_an_export_is_rejected(db):
    with pytest.raises(ImportFileError, match="manca la colonna"):
        do_import("nome;cognome\nMario;Rossi\n")


def test_comma_separated_file_is_accepted(db):
    buf = io.StringIO()
    csv.writer(buf).writerows([COLUMNS] + [[r[c] for c in COLUMNS] for r in rows(exported())])
    wipe()
    assert do_import(buf.getvalue()).new == 2


# ---------------- API ----------------

@pytest.fixture
def client(db):
    from app.main import app

    return TestClient(app)


def test_export_endpoint_downloads_a_dated_csv_with_bom(client):
    resp = client.get("/api/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="cerca-case-' in resp.headers["content-disposition"]
    assert resp.content.startswith(b"\xef\xbb\xbf")


def test_import_endpoint_round_trip(client):
    body = client.get("/api/export.csv").content
    wipe()
    resp = client.post("/api/import", content=body, headers={"Content-Type": "text/csv"})
    assert resp.status_code == 200
    assert resp.json()["data"] == {"rows": 2, "new": 2, "updated": 0, "unchanged": 0, "error_count": 0, "errors": []}
    assert client.get("/api/listings").json()["meta"]["total"] == 1  # the other one is not online


def test_import_endpoint_rejects_bad_input(client):
    assert client.post("/api/import", content=b"").status_code == 400
    latin1 = client.post("/api/import", content="città;x\n".encode("latin-1"))
    assert latin1.status_code == 400 and "UTF-8" in latin1.json()["error"]
    wrong = client.post("/api/import", content=b"a;b\n1;2\n")
    assert wrong.status_code == 400 and "manca la colonna" in wrong.json()["error"]


def test_import_endpoint_rejects_oversized_files(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_IMPORT_BYTES", 10)
    assert client.post("/api/import", content=b"x" * 11).status_code == 413


def test_info_reports_full_mode(client):
    assert client.get("/api/info").json()["data"] == {"mode": "completo", "can_scrape": True}


def test_read_only_mode_has_no_crawl_endpoints(monkeypatch, db):
    import app.main as main_mod

    monkeypatch.setattr(config, "APP_MODE", "consultazione")
    monkeypatch.setattr(config, "CAN_SCRAPE", False)
    try:
        client = TestClient(importlib.reload(main_mod).app)
        assert client.get("/api/info").json()["data"] == {"mode": "consultazione", "can_scrape": False}
        assert client.post("/api/scrape").status_code in (404, 405)
        assert client.get("/api/scrape/status").status_code == 404
        assert client.get("/api/export.csv").status_code == 200
    finally:
        monkeypatch.undo()
        importlib.reload(main_mod)
