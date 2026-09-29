import pytest

from scrapers.parsing import clean_title, parse_datetime, to_int


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Villa a schiera via Tosco Romagnola,, Navacchio Nord, Cascina", "Villa a schiera via Tosco Romagnola, Navacchio Nord, Cascina"),
        ("Rustico/casale in Via Santa Maria, ", "Rustico/casale in Via Santa Maria"),
        ("  ", None),
        (None, None),
    ],
)
def test_clean_title(value, expected):
    assert clean_title(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("€ 209.000", 209000), ("144 m²", 144), ("5+", 5), (3, 3), (0, None), ("", None), (None, None), (True, None)],
)
def test_to_int(value, expected):
    assert to_int(value) == expected


def test_parse_datetime_treats_naive_values_as_italian_time():
    dt = parse_datetime("2026-09-28 18:30:26")
    assert dt.utcoffset().total_seconds() == 0
    assert dt.hour == 16  # CEST is UTC+2


def test_parse_datetime_invalid():
    assert parse_datetime("ieri") is None
