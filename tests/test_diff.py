"""Ground-truth tests against the real example files.

These assertions encode the verified diff between Example_1 and
Example_2. If any of them flip, either the data changed or the engine
regressed — both are things we want to fail loudly.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from core.loader import load_rate_sheet, _to_date
from core.differ import diff_rate_sheets


DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def diff():
    old = load_rate_sheet(DATA / "Example_1.xlsx")
    new = load_rate_sheet(DATA / "Example_2.xlsx")
    return diff_rate_sheets(old, new)


def test_raw_counts(diff):
    assert diff.counts_raw() == {"new": 1, "deleted": 1, "updated": 4}


def test_reconciled_counts(diff):
    assert diff.counts_reconciled() == {"new": 0, "deleted": 0, "updated": 4, "redated": 1}


def test_updated_field_breakdown(diff):
    fields = sorted(d.field for u in diff.updated for d in u.deltas)
    # Two Rate changes, two Expiration Date changes — verified ground truth.
    assert fields == ["expiration_date", "expiration_date", "rate", "rate"]


def test_redated_lane_is_customer_115_han_az(diff):
    assert len(diff.redated) == 1
    p = diff.redated[0]
    assert (p.deleted.customer, p.deleted.origin, p.deleted.destination) == (115, "HAN", "AZ")
    assert p.old_effective == date(2026, 6, 1)
    assert p.new_effective == date(2026, 7, 1)


def test_date_normalization_string():
    assert _to_date("05/31/2027") == date(2027, 5, 31)


def test_date_normalization_datetime():
    assert _to_date(datetime(2026, 6, 1, 12, 0, 0)) == date(2026, 6, 1)


def test_date_normalization_date_passthrough():
    assert _to_date(date(2026, 6, 1)) == date(2026, 6, 1)


def test_date_normalization_iso_string():
    assert _to_date("2026-06-01") == date(2026, 6, 1)
