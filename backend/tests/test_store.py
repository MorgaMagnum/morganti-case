import io

import pytest
from PIL import Image, ImageDraw
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import config
from app.models import Listing, ListingImage, SourceLink
from pipeline.geo import CascinaGeo
from pipeline.store import ListingStore
from scrapers.base import RawListing


def make_image(seed: int) -> bytes:
    img = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(img)
    for i in range(8):
        x = (seed * 37 + i * 53) % 360
        y = (seed * 91 + i * 29) % 260
        draw.rectangle([x, y, x + 40, y + 40], fill=((seed * 50) % 255, (i * 30) % 255, 90))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


class FakeImages:
    def __init__(self):
        self.by_url = {}

    def fetch(self, url):
        return self.by_url.get(url)

    def fetch_many(self, urls):
        return {u: self.fetch(u) for u in urls}


class FakeGeocoder:
    def geocode(self, address):
        return (43.6847, 10.48912)  # Navacchio


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture(scope="module")
def geo():
    return CascinaGeo.from_config()


@pytest.fixture
def images():
    return FakeImages()


@pytest.fixture
def store(session, geo, images):
    return ListingStore(session, geo, FakeGeocoder(), images)


def raw(**kw):
    base = dict(
        source="immobiliare",
        external_id="100",
        url="https://www.immobiliare.it/annunci/100/",
        contract="vendita",
        title="Trilocale in Via Mario Giuntini 65, Cascina",
        property_type_raw="Trilocale",
        price=210000,
        surface_m2=79,
        rooms=3,
        address="Via Mario Giuntini 65",
        city="Cascina",
        lat=43.6847,
        lng=10.48912,
        coords_exact=True,
        agency_name="Casavo",
        image_urls=("https://img/a1.jpg", "https://img/a2.jpg"),
    )
    base.update(kw)
    return RawListing(**base)


def test_new_listing_is_created_with_cover_and_images(store, session, images):
    images.by_url["https://img/a1.jpg"] = make_image(1)
    counts = store.process_page([raw()])
    session.commit()

    assert counts["new"] == 1
    listing = session.exec(select(Listing)).one()
    assert listing.property_type == "appartamento"
    assert listing.frazione == "Navacchio"
    assert listing.geo_precision == "esatta"
    assert listing.cover_phash
    assert (config.MEDIA_DIR / listing.cover_path).exists()
    imgs = session.exec(select(ListingImage).order_by(ListingImage.position)).all()
    assert [i.source_url for i in imgs] == ["https://img/a1.jpg", "https://img/a2.jpg"]


def test_seeing_the_same_ad_again_updates_it(store, session):
    store.process_page([raw()])
    counts = store.process_page([raw(price=205000)])
    session.commit()

    assert counts["updated"] == 1
    listing = session.exec(select(Listing)).one()
    assert listing.price == 205000


def test_same_property_on_another_portal_is_merged(store, session):
    store.process_page([raw()])
    other = raw(
        source="wikicasa",
        external_id="w1",
        url="https://www.wikicasa.it/annuncio/w1",
        price=208000,
        lat=None,
        lng=None,
        coords_exact=False,
        image_urls=("https://img/b1.jpg", "https://img/b2.jpg", "https://img/b3.jpg"),
    )
    counts = store.process_page([other])
    session.commit()

    assert counts["merged"] == 1
    listing = session.exec(select(Listing)).one()
    links = session.exec(select(SourceLink)).all()
    assert {l.source for l in links} == {"immobiliare", "wikicasa"}
    assert listing.price == 208000  # best price across portals
    assert listing.geo_precision == "esatta"  # keeps the better location
    # the portal with more photos wins the gallery
    assert len(session.exec(select(ListingImage)).all()) == 3


def test_same_photos_merge_even_with_vague_location(store, session, images):
    images.by_url["https://img/a1.jpg"] = make_image(7)
    images.by_url["https://img/c1.jpg"] = make_image(7)
    store.process_page([raw()])
    other = raw(
        source="idealista",
        external_id="i1",
        url="https://www.idealista.it/immobile/i1/",
        address=None,
        lat=None,
        lng=None,
        coords_exact=False,
        surface_m2=None,
        price=215000,
        image_urls=("https://img/c1.jpg",),
    )
    counts = store.process_page([other])
    assert counts["merged"] == 1


def test_missing_price_does_not_erase_known_price(store, session):
    store.process_page([raw()])
    store.process_page([raw(price=None)])
    assert session.exec(select(Listing)).one().price == 210000


def test_gallery_update_keeps_existing_image_ids(store, session):
    store.process_page([raw()])
    before = {i.source_url: i.id for i in session.exec(select(ListingImage)).all()}
    store.process_page([raw(image_urls=("https://img/a1.jpg", "https://img/a2.jpg", "https://img/a3.jpg"))])
    after = {i.source_url: i.id for i in session.exec(select(ListingImage)).all()}
    assert after["https://img/a1.jpg"] == before["https://img/a1.jpg"]
    assert len(after) == 3


def test_similar_ads_on_same_portal_stay_separate(store, session):
    store.process_page([raw()])
    sibling = raw(external_id="101", url="https://x/101", price=214000, surface_m2=84)
    counts = store.process_page([sibling])
    assert counts["new"] == 1


def test_same_property_relisted_by_another_agency_on_same_portal_is_merged(store, session):
    store.process_page([raw()])
    counts = store.process_page([raw(external_id="102", url="https://x/102", agency_name="Tecnocasa")])
    assert counts["merged"] == 1


def test_duplicate_ad_in_one_page_is_stored_once(store, session):
    counts = store.process_page([raw(), raw()])
    assert counts == {"new": 1}


def test_listing_outside_cascina_is_skipped(store, session):
    counts = store.process_page([raw(city="Pisa")])
    assert counts["skipped"] == 1
    assert session.exec(select(Listing)).all() == []


def test_ads_missing_for_two_runs_become_inactive(store, session):
    store.process_page([raw(), raw(external_id="200", url="https://x/200", address="Via Tosco Romagnola 1", price=99000, lat=43.68, lng=10.55)])
    store.finalize_missing("immobiliare", "vendita", seen={"100"})
    gone = session.exec(select(Listing).where(Listing.price == 99000)).one()
    assert gone.is_active  # one miss is tolerated

    store.finalize_missing("immobiliare", "vendita", seen={"100"})
    session.refresh(gone)
    assert not gone.is_active
    still = session.exec(select(Listing).where(Listing.price == 210000)).one()
    assert still.is_active


def test_reappearing_ad_is_reactivated(store, session):
    store.process_page([raw()])
    store.finalize_missing("immobiliare", "vendita", seen=set())
    store.finalize_missing("immobiliare", "vendita", seen=set())
    store.process_page([raw()])
    assert session.exec(select(Listing)).one().is_active


def test_advertiser_type_is_stored_on_the_link(store, session):
    store.process_page([raw(agency_name="Privato", is_private=True)])
    link = session.exec(select(SourceLink)).one()
    assert link.is_private is True


def test_known_advertiser_type_corrects_an_old_private_label(store, session):
    # Older runs called every logo-less agency "Privato".
    store.process_page([raw(agency_name="Privato")])
    store.process_page([raw(agency_name=None, is_private=False)])
    link = session.exec(select(SourceLink)).one()
    listing = session.exec(select(Listing)).one()
    assert (link.is_private, link.agency_name, listing.agency_name) == (False, None, None)


def test_unknown_advertiser_type_keeps_what_we_knew(store, session):
    store.process_page([raw(agency_name="Privato", is_private=True)])
    store.process_page([raw(agency_name=None, is_private=None)])
    link = session.exec(select(SourceLink)).one()
    assert (link.is_private, link.agency_name) == (True, "Privato")