from pipeline.dedup import Candidate, is_same_property, phash_distance


def cand(**kw):
    base = dict(
        contract="vendita",
        property_type="appartamento",
        price=200000,
        surface_m2=90,
        rooms=4,
        lat=43.6851,
        lng=10.4836,
        geo_precision="esatta",
        address_norm="sirio moggi 82",
        frazione="Navacchio",
        phash=None,
    )
    base.update(kw)
    return Candidate(**base)


def test_same_listing_on_two_portals():
    assert is_same_property(cand(), cand(price=203000, surface_m2=92, lat=43.6855))


def test_different_contract_never_matches():
    assert not is_same_property(cand(), cand(contract="affitto"))


def test_price_too_different():
    assert not is_same_property(cand(), cand(price=240000))


def test_surface_too_different():
    assert not is_same_property(cand(), cand(surface_m2=120))


def test_far_apart_precise_locations():
    assert not is_same_property(cand(), cand(lat=43.70, address_norm="altra via 1"))


def test_same_address_without_precise_coords():
    assert is_same_property(cand(geo_precision="via"), cand(geo_precision="frazione", lat=None, lng=None))


def test_same_frazione_needs_exact_numbers():
    a = cand(geo_precision="frazione", address_norm=None)
    assert is_same_property(a, cand(geo_precision="frazione", address_norm=None, lat=43.69))
    assert not is_same_property(a, cand(geo_precision="frazione", address_norm=None, lat=43.69, rooms=3))
    assert not is_same_property(a, cand(geo_precision="frazione", address_norm=None, frazione="Latignano"))


def test_missing_price_and_surface_cannot_match_on_location_alone():
    assert not is_same_property(cand(price=None, surface_m2=None), cand(price=None, surface_m2=None))


def test_matching_photo_hash_wins():
    h = "f0e0c0a0b0d0e0f0"
    vague = cand(phash=h, surface_m2=None, lat=43.70, geo_precision="frazione", address_norm=None)
    assert is_same_property(cand(phash=h, price=None), vague)


def test_matching_photo_hash_still_respects_contract():
    h = "f0e0c0a0b0d0e0f0"
    assert not is_same_property(cand(phash=h), cand(phash=h, contract="affitto"))


def test_matching_photo_hash_with_very_different_price_is_a_placeholder():
    h = "f0e0c0a0b0d0e0f0"
    assert not is_same_property(cand(phash=h), cand(phash=h, price=450000))


def test_matching_photo_hash_but_different_surface_is_another_unit():
    h = "f0e0c0a0b0d0e0f0"
    assert not is_same_property(cand(phash=h), cand(phash=h, surface_m2=140))


def test_matching_photo_hash_far_apart_with_loose_price_is_a_shared_logo():
    h = "f0e0c0a0b0d0e0f0"
    assert not is_same_property(cand(phash=h), cand(phash=h, price=220000, lat=43.70, lng=10.52))


def test_same_photo_price_and_size_wins_over_wrong_pin_and_type():
    h = "f0e0c0a0b0d0e0f0"
    other = cand(phash=h, lat=43.70, lng=10.52, property_type="casa indipendente", address_norm="altra")
    assert is_same_property(cand(phash=h), other)


def test_recompressed_photo_with_identical_numbers_matches():
    # wikicasa serves re-encoded webp covers: hash distance ~8-10 for the same photo
    a = cand(phash="f0e0c0a0b0d0e0f0", address_norm=None, geo_precision="comune")
    b = cand(phash="f0e0c0a0b0d3e3ff", address_norm=None, geo_precision="via", lat=43.70)
    assert 6 < phash_distance(a.phash, b.phash) <= 10
    assert is_same_property(a, b)
    assert not is_same_property(a, cand(phash=b.phash, price=205000, geo_precision="via", lat=43.70, address_norm=None))


def test_same_street_when_one_side_has_no_civic_number():
    a = cand(address_norm="b genovesi sud 73", geo_precision="comune", lat=None, lng=None)
    assert is_same_property(a, cand(address_norm="b genovesi sud", geo_precision="via", lat=43.70))
    assert not is_same_property(a, cand(address_norm="b genovesi sud 12", geo_precision="via", lat=43.70))


def test_rooms_counted_differently_do_not_block_same_address():
    assert is_same_property(cand(rooms=4), cand(rooms=7))


def test_same_full_address_and_numbers_tolerate_flat_vs_house_label():
    assert is_same_property(cand(), cand(property_type="casa indipendente", geo_precision="via", lat=43.70))


def test_different_types_do_not_match():
    assert not is_same_property(cand(), cand(property_type="villa", address_norm=None, lat=43.6852))
