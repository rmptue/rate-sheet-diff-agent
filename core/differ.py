"""Deterministic diff engine for rate sheets.

Why this is *not* an LLM call:
    Rate and effective-date comparisons must be auditable, reproducible,
    and bit-exact. An LLM can hallucinate a number changed when it didn't,
    or vice versa, and there is no acceptable error rate for that on
    pricing data. So the engine is pure Python set/dict logic — the AI
    layer only ever narrates the *output* of this module.

Two views produced:
    1. Raw view — naive row-level: New / Updated / Deleted.
    2. Reconciled view — runs a pass that pairs a Deleted record with a
       New record when they share Customer + Origin + Destination and
       differ only in Effective Date. Those pairs are pulled into a
       ``RE-DATED`` bucket. Without this pass, a single lane whose start
       date shifted shows up as two unrelated changes and obscures the
       real signal in the diff.
"""
from __future__ import annotations

from .models import (
    Record,
    UpdatedRecord,
    FieldDelta,
    RedatedPair,
    DiffResult,
)


def _index(records: list[Record]) -> dict[tuple, Record]:
    out: dict[tuple, Record] = {}
    for r in records:
        out[r.key()] = r
    return out


def diff_rate_sheets(old: list[Record], new: list[Record]) -> DiffResult:
    a = _index(old)
    b = _index(new)

    a_keys = set(a)
    b_keys = set(b)

    result = DiffResult()

    # --- Raw classification ---------------------------------------------
    for k in b_keys - a_keys:
        result.new.append(b[k])
    for k in a_keys - b_keys:
        result.deleted.append(a[k])

    for k in a_keys & b_keys:
        ra, rb = a[k], b[k]
        deltas: list[FieldDelta] = []
        if ra.expiration_date != rb.expiration_date:
            deltas.append(FieldDelta("expiration_date", ra.expiration_date, rb.expiration_date))
        if ra.rate != rb.rate:
            deltas.append(FieldDelta("rate", ra.rate, rb.rate))
        if deltas:
            result.updated.append(UpdatedRecord(key=k, old=ra, new=rb, deltas=deltas))

    # --- Reconciliation pass: detect re-dated lanes ---------------------
    # A re-dated lane is the same (Customer, Origin, Destination) showing
    # up exactly once in `deleted` and exactly once in `new` with a
    # different Effective Date. We're conservative: if there are multiple
    # candidates on either side, we leave them alone rather than guess.
    deleted_by_lane: dict[tuple, list[Record]] = {}
    new_by_lane: dict[tuple, list[Record]] = {}
    for r in result.deleted:
        deleted_by_lane.setdefault(r.lane(), []).append(r)
    for r in result.new:
        new_by_lane.setdefault(r.lane(), []).append(r)

    paired_deleted: set[tuple] = set()
    paired_new: set[tuple] = set()
    for lane, dels in deleted_by_lane.items():
        news = new_by_lane.get(lane, [])
        if len(dels) == 1 and len(news) == 1:
            d, n = dels[0], news[0]
            result.redated.append(
                RedatedPair(
                    deleted=d,
                    new=n,
                    old_effective=d.effective_date,
                    new_effective=n.effective_date,
                )
            )
            paired_deleted.add(d.key())
            paired_new.add(n.key())

    result.new_after_reconcile = [r for r in result.new if r.key() not in paired_new]
    result.deleted_after_reconcile = [r for r in result.deleted if r.key() not in paired_deleted]

    return result
