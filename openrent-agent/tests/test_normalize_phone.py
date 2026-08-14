"""normalize_uk_phone must return a valid 11-digit UK number or None.

Regression for the stitching edge case where unrelated digits produced a
12-digit result ('+4479048373252' -> '079048373252') that was saved as a lead.
"""
from app.utils.phone import normalize_uk_phone


def test_valid_mobile_passthrough():
    assert normalize_uk_phone("07714436232") == "07714436232"


def test_plus44_converted():
    assert normalize_uk_phone("+447714436232") == "07714436232"


def test_44_prefix_converted():
    assert normalize_uk_phone("447714436232") == "07714436232"


def test_spaces_and_symbols_stripped():
    assert normalize_uk_phone("0771 443-6232") == "07714436232"


def test_landline_kept():
    assert normalize_uk_phone("02012345678") == "02012345678"


def test_foreign_number_kept():
    # A landlord may be based abroad — keep the international form.
    assert normalize_uk_phone("+33649546062") == "+33649546062"
    assert normalize_uk_phone("0033649546062") == "+33649546062"


def test_bare_non_uk_number_rejected():
    # No +/country code and not a valid UK number — ambiguous with garbage.
    assert normalize_uk_phone("14168350892") is None


def test_over_long_rejected():
    assert normalize_uk_phone("079048373252") is None       # 12 digits
    assert normalize_uk_phone("+4479048373252") is None     # 11 digits after +44


def test_too_short_rejected():
    assert normalize_uk_phone("0758545454") is None         # 10 digits


def test_empty_or_none():
    assert normalize_uk_phone("") is None
    assert normalize_uk_phone(None) is None
    assert normalize_uk_phone("(Number Removed)") is None
