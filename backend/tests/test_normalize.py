import pytest

from pipeline.normalize import canonical_property_type, normalize_address, street_key


@pytest.mark.parametrize(
    "raw, title, expected",
    [
        ("Terratetto unifamiliare", None, "casa indipendente"),
        ("Casa indipendente", None, "casa indipendente"),
        ("villa", None, "villa"),
        ("Villa bifamiliare", None, "villa"),
        ("Villetta a schiera", None, "villetta a schiera"),
        ("Trilocale", None, "appartamento"),
        ("appartamenti", None, "appartamento"),
        ("Attico", None, "attico / mansarda"),
        ("loft-mansarde", None, "attico / mansarda"),
        ("camere-posti-letto", None, "stanza"),
        ("Rustico", None, "rustico / casale"),
        ("Casale", None, "rustico / casale"),
        ("terreni-e-rustici", "Terreno agricolo di 5000 mq", "terreno"),
        ("terreni-e-rustici", "Rustico da ristrutturare", "rustico / casale"),
        ("ville-singole-e-a-schiera", "Villetta a schiera con giardino", "villetta a schiera"),
        ("ville-singole-e-a-schiera", "Villa singola", "villa"),
        (None, "Bilocale in Via Tosco Romagnola", "appartamento"),
        (None, None, "altro"),
    ],
)
def test_canonical_property_type(raw, title, expected):
    assert canonical_property_type(raw, title) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Via Sirio Moggi 82", "sirio moggi 82"),
        ("Via 8 Marzo, 42", "8 marzo 42"),
        ("V.le Italia", "italia"),
        ("Piazza dei Caduti 3/A", "dei caduti 3a"),
        ("Via Macerata, 145, 56021 Cascina Pi, Italia 145", "macerata 145"),
        ("Via B.Genovesi Sud 73", "b genovesi sud 73"),
        ("Via B. Genovesi sud", "b genovesi sud"),
        (None, None),
        ("", None),
    ],
)
def test_normalize_address(value, expected):
    assert normalize_address(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("b genovesi sud 73", "b genovesi sud"), ("8 marzo 42", "8 marzo"), ("roma", "roma"), (None, None)],
)
def test_street_key(value, expected):
    assert street_key(value) == expected
