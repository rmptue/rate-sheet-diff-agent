"""Generate a small, demo-friendly pair of test rate sheets.

The bundled Example_1 / Example_2 files have 783 rows but only 6 changes,
which buries the signal during a live demo. This generator writes a
20-row pair with one of every change type so a reviewer can immediately
*see* all the things the engine catches:

    - 1 Rate decrease  (margin-relevant)
    - 1 Rate increase
    - 1 Expiration Date extension
    - 1 Expiration Date shortening
    - 1 Genuinely new lane
    - 1 Genuinely deleted lane
    - 1 RE-DATED lane (deleted at old effective date + new at new effective date,
                       same Customer + Origin + Destination — the showcase case)

Run from repo root:    python scripts/generate_test_data.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


COLS = [
    "Customer",
    "Origin Port Code",
    "Destination Port Code",
    "Effective Date",
    "Expiration Date",
    "Rate",
]


def _fmt(d: date) -> str:
    # Match the M/D/Y string format that Example_1 / Example_2 use.
    return d.strftime("%m/%d/%Y")


# Stable rows that appear identically in both files — context for the diff.
STABLE = [
    (201, "SIN", "CA", date(2026, 1, 1), date(2026, 12, 31), 3.10),
    (201, "SIN", "CA", date(2027, 1, 1), date(2027, 12, 31), 3.15),
    (201, "BKK", "NY", date(2026, 1, 1), date(2026, 12, 31), 4.20),
    (202, "HKG", "TX", date(2026, 1, 1), date(2026, 12, 31), 2.85),
    (202, "HKG", "TX", date(2027, 1, 1), date(2027, 12, 31), 2.90),
    (202, "SHA", "IL", date(2026, 1, 1), date(2026, 12, 31), 3.45),
    (203, "DEL", "GA", date(2026, 1, 1), date(2026, 12, 31), 5.10),
    (203, "MAA", "FL", date(2026, 1, 1), date(2026, 12, 31), 5.25),
]

# Lanes whose Rate or Expiration Date changes between OLD and NEW.
# Format: (key, old_exp, old_rate, new_exp, new_rate, change_label)
UPDATED = [
    # Rate decrease — flagged in summary as margin-relevant
    ((204, "PNH", "OH", date(2026, 3, 1)), date(2026, 8, 31), 4.50, date(2026, 8, 31), 4.20, "rate_down"),
    # Rate increase
    ((204, "PNH", "OH", date(2026, 9, 1)), date(2027, 2, 28), 4.50, date(2027, 2, 28), 4.75, "rate_up"),
    # Expiration extension (contract renewal)
    ((205, "JKT", "AZ", date(2026, 1, 1)), date(2026, 12, 31), 3.95, date(2027, 12, 31), 3.95, "exp_extended"),
    # Expiration shortening (early termination window)
    ((205, "SGN", "PA", date(2026, 1, 1)), date(2026, 12, 31), 3.60, date(2026, 9, 30), 3.60, "exp_shortened"),
]

# Lane that exists only in OLD
DELETED = [
    (206, "CMB", "MI", date(2026, 1, 1), date(2026, 12, 31), 6.10),
]

# Lane that exists only in NEW
NEW = [
    (207, "DAC", "WA", date(2026, 4, 1), date(2027, 3, 31), 4.85),
]

# The headline case: same Customer + Origin + Destination, different
# Effective Date. Appears as 1 Deleted + 1 New in a naive diff; the
# reconciliation pass pairs them into a single RE-DATED entry.
REDATED_OLD = (208, "HAN", "AZ", date(2026, 6, 1), date(2027, 5, 31), 3.76)
REDATED_NEW = (208, "HAN", "AZ", date(2026, 7, 15), date(2027, 5, 31), 3.76)


def _rows_old() -> list[tuple]:
    rows: list[tuple] = list(STABLE)
    for (cust, o, d, eff), old_exp, old_rate, _, _, _ in UPDATED:
        rows.append((cust, o, d, eff, old_exp, old_rate))
    rows.extend(DELETED)
    rows.append(REDATED_OLD)
    return rows


def _rows_new() -> list[tuple]:
    rows: list[tuple] = list(STABLE)
    for (cust, o, d, eff), _, _, new_exp, new_rate, _ in UPDATED:
        rows.append((cust, o, d, eff, new_exp, new_rate))
    rows.extend(NEW)
    rows.append(REDATED_NEW)
    return rows


def _to_df(rows: list[tuple]) -> pd.DataFrame:
    out = []
    for r in rows:
        cust, o, d, eff, exp, rate = r
        out.append({
            "Customer": cust,
            "Origin Port Code": o,
            "Destination Port Code": d,
            "Effective Date": _fmt(eff),
            "Expiration Date": _fmt(exp),
            "Rate": rate,
        })
    return pd.DataFrame(out, columns=COLS)


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    df_old = _to_df(_rows_old())
    df_new = _to_df(_rows_new())

    old_path = out_dir / "Test_OLD.xlsx"
    new_path = out_dir / "Test_NEW.xlsx"

    df_old.to_excel(old_path, index=False)
    df_new.to_excel(new_path, index=False)

    print(f"Wrote {old_path}  ({len(df_old)} rows)")
    print(f"Wrote {new_path}  ({len(df_new)} rows)")
    print()
    print("Expected diff (reconciled view):")
    print("  Updated:   4   (1 rate down, 1 rate up, 1 exp extended, 1 exp shortened)")
    print("  New:       1   (Customer 207, DAC -> WA)")
    print("  Deleted:   1   (Customer 206, CMB -> MI)")
    print("  Re-dated:  1   (Customer 208, HAN -> AZ: 2026-06-01 -> 2026-07-15)")


if __name__ == "__main__":
    main()
