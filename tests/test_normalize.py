from datetime import date
from decimal import Decimal

import pytest

from co_extract.normalize import parse_date, parse_days, parse_money, parse_reason, parse_status
from co_extract.schema import Reason, Status


@pytest.mark.parametrize("raw,expected", [
    ("$12,450.00", Decimal("12450.00")),
    ("(4,200.00)", Decimal("-4200.00")),
    ("($4,950.00)", Decimal("-4950.00")),
    ("-$300", Decimal("-300.00")),
    ("1.234,56", Decimal("1234.56")),
    ("USD 2,662.30", Decimal("2662.30")),
    ("$1,820.50 so the total", Decimal("1820.50")),
])
def test_parse_money(raw, expected):
    """Money strings in many formats parse to the right amount."""
    assert parse_money(raw)[0] == expected


def test_parse_money_repairs_ocr_and_flags_it():
    """OCR-damaged money is repaired and flagged."""
    value, flags = parse_money("6,4OO,OOO.OO")
    assert value == Decimal("6400000.00")
    assert "ocr_corrected" in flags


@pytest.mark.parametrize("raw,expected", [
    ("increased by three (3) calendar days", 3),
    ("decreased by 5 calendar days", -5),
    ("2 weeks", 14),
    ("No schedule impact", 0),
    ("unchanged", None),
])
def test_parse_days(raw, expected):
    """Schedule wording parses to the right number of days."""
    assert parse_days(raw)[0] == expected


def test_parse_date_formats_and_ambiguity():
    """Dates parse in many formats; ambiguity and OCR repairs are flagged."""
    assert parse_date("September 3, 2025")[0] == date(2025, 9, 3)
    assert parse_date("Wed, 2 Apr 2025 09:41:12 -0700")[0] == date(2025, 4, 2)
    d, flags = parse_date("06/09/2025")
    assert d == date(2025, 6, 9) and "ambiguous_day_month" in flags
    d, flags = parse_date("O6/O9/2025")
    assert d == date(2025, 6, 9) and "ocr_corrected" in flags


def test_enums():
    """Reason and status wording maps to the right categories."""
    assert parse_reason("Fire Marshal / code requirement")[0] == Reason.REGULATORY
    assert parse_reason("value_engineering")[0] == Reason.VALUE_ENGINEERING
    assert parse_status("APPR0VED")[0] == Status.APPROVED
    assert parse_status("Awaiting Owner approval")[0] == Status.PENDING
    assert parse_status("Rejected")[0] == Status.REJECTED
