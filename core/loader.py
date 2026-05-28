"""Rate-sheet loader.

The single most important job of this module is **date normalization**.

Real-world finding from the example files: Effective Date and Expiration
Date columns are *mixed types* — most cells come back from openpyxl as
strings like '05/31/2027', but a handful are real ``datetime`` objects
(Excel stored them as date-typed cells). A diff that compares
``'06/01/2026'`` to ``datetime(2026, 6, 1)`` reports a false positive on
every row where the types disagree. We aggressively coerce both columns
to ``datetime.date`` at load time, before anything else looks at them.
This is the kind of silent data-hygiene bug that derails rate audits in
production; we surface it explicitly because it's the project's headline
"real-world AI automation" story.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .models import Record


EXPECTED_COLUMNS = [
    "Customer",
    "Origin Port Code",
    "Destination Port Code",
    "Effective Date",
    "Expiration Date",
    "Rate",
]


def _to_date(value: Any) -> date:
    """Coerce mixed Excel date representations into ``datetime.date``."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError("Missing date value")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().date()
    if isinstance(value, str):
        s = value.strip()
        # Most common Excel format we saw: MM/DD/YYYY. Fall back to pandas
        # parser for anything more exotic so we don't surprise-fail on an
        # ISO date that someone pasted in.
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return pd.to_datetime(s).date()
    raise TypeError(f"Cannot coerce {value!r} ({type(value).__name__}) to date")


def load_rate_sheet(path: str | Path) -> list[Record]:
    """Load an xlsx rate sheet and return strongly-typed Record objects."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Rate sheet not found: {p}")
    df = pd.read_excel(p)
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns in {p.name}: {missing}")

    records: list[Record] = []
    for _, row in df.iterrows():
        records.append(
            Record(
                customer=row["Customer"],
                origin=str(row["Origin Port Code"]).strip(),
                destination=str(row["Destination Port Code"]).strip(),
                effective_date=_to_date(row["Effective Date"]),
                expiration_date=_to_date(row["Expiration Date"]),
                rate=float(row["Rate"]),
            )
        )
    return records
