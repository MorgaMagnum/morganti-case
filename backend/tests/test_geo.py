import pytest

from pipeline.geo import CascinaGeo, resolve_location
from scrapers.base import RawListing


@pytest.fixture(scope="module")
def geo():
    return CascinaGeo.from_config()


class FakeGeocoder:
    def __init__(self, result=None):
        self.result = result
        self.queries = []

    def geocode(self, address):
        self.queries.append(address)
        return self.result


def raw(**kw):
    base = dict(source="t", external_id="1", url="https://x", contract="vendita", title="Casa")
    base.update(kw)
    return RawListing(**base)


class TestCascinaGeo:
    def test_contains_points_inside_the_comune(self, geo):
        assert geo.contains(43.6851, 10.4836)  # Navacchio
        assert not geo.contains(43.7167, 10.4017)  # Pisa centro
        assert not geo.contains(43.6626, 10.6327)  # Pontedera

    def test_frazione_from_text(self, geo):
        assert geo.frazione_from_text("Navacchio Sud") == "Navacchio"
        assert geo.frazione_from_text("Titignano-Visignano") == "Titignano"
        assert geo.frazione_from_text("Casciavola - Zambra - Laiano") == "Casciavola"
        assert geo.frazione_from_text("San Frediano a Settimo, Cascina") == "San Frediano a Settimo"
        assert geo.frazione_from_text("Via Roma") is None

    def test_nearest_frazione(self, geo):
        assert geo.nearest_frazione(43.6847, 10.48912) == "Navacchio"  # Via Giuntini


class TestResolveLocation:
    def test_exact_site_coordinates(self, geo):
        loc = resolve_location(raw(lat=43.6851, lng=10.4836, coords_exact=True, zone="Navacchio Sud"), geo, FakeGeocoder())
        assert loc.precision == "esatta"
        assert loc.frazione == "Navacchio"

    def test_rejects_other_city(self, geo):
        assert resolve_location(raw(city="Pisa"), geo, FakeGeocoder()) is None

    def test_rejects_exact_coordinates_outside_comune(self, geo):
        assert resolve_location(raw(lat=43.7167, lng=10.4017, coords_exact=True), geo, FakeGeocoder()) is None

    def test_geocodes_address_when_no_coordinates(self, geo):
        coder = FakeGeocoder((43.6847, 10.48912))
        loc = resolve_location(raw(address="Via Mario Giuntini 65", city="Cascina"), geo, coder)
        assert coder.queries == ["Via Mario Giuntini 65"]
        assert loc.precision == "via"
        assert loc.frazione == "Navacchio"

    def test_ignores_geocode_result_outside_comune(self, geo):
        coder = FakeGeocoder((43.7167, 10.4017))
        loc = resolve_location(raw(address="Via Roma 1", zone="Latignano"), geo, coder)
        assert loc.precision == "frazione"
        assert loc.frazione == "Latignano"

    def test_falls_back_to_comune_centre(self, geo):
        loc = resolve_location(raw(), geo, FakeGeocoder())
        assert loc.precision == "comune"
        assert geo.contains(loc.lat, loc.lng)
