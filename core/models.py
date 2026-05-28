"""Typed data containers for the rate-sheet diff pipeline.

Design note: every piece of data the agent reasons about flows through these
dataclasses. We keep the LLM strictly downstream of these objects — the
deterministic engine (Layer 1) produces them, and the AI layer (Layer 2) is
only allowed to *narrate* them. Numbers and classifications never originate
in the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any


# Composite business key. Two rows are "the same lane on the same start date"
# iff these four fields match. Expiration Date and Rate are the comparable
# (i.e. mutable) attributes.
KEY_FIELDS = ("customer", "origin", "destination", "effective_date")
COMPARE_FIELDS = ("expiration_date", "rate")


@dataclass(frozen=True)
class Record:
    customer: int | str
    origin: str
    destination: str
    effective_date: date
    expiration_date: date
    rate: float

    def key(self) -> tuple:
        return (self.customer, self.origin, self.destination, self.effective_date)

    def lane(self) -> tuple:
        # Lane identity ignoring Effective Date — used for re-dated reconciliation.
        return (self.customer, self.origin, self.destination)


@dataclass
class FieldDelta:
    field: str
    old: Any
    new: Any


@dataclass
class UpdatedRecord:
    key: tuple
    old: Record
    new: Record
    deltas: list[FieldDelta]


@dataclass
class RedatedPair:
    """A Deleted+New pair that share Customer/Origin/Destination and differ
    only in Effective Date. Almost certainly the same logical lane being
    re-issued on a new start date, not two unrelated changes."""
    deleted: Record
    new: Record
    old_effective: date
    new_effective: date


@dataclass
class DiffResult:
    # Raw, row-level view.
    new: list[Record] = field(default_factory=list)
    deleted: list[Record] = field(default_factory=list)
    updated: list[UpdatedRecord] = field(default_factory=list)
    # Reconciled view: re-dated lanes pulled out of new+deleted into their
    # own bucket so a human reading the summary doesn't get misled.
    redated: list[RedatedPair] = field(default_factory=list)
    new_after_reconcile: list[Record] = field(default_factory=list)
    deleted_after_reconcile: list[Record] = field(default_factory=list)

    def counts_raw(self) -> dict:
        return {"new": len(self.new), "deleted": len(self.deleted), "updated": len(self.updated)}

    def counts_reconciled(self) -> dict:
        return {
            "new": len(self.new_after_reconcile),
            "deleted": len(self.deleted_after_reconcile),
            "updated": len(self.updated),
            "redated": len(self.redated),
        }

    def to_json_dict(self) -> dict:
        """Stable JSON-safe shape for handing to the LLM."""
        def rec(r: Record) -> dict:
            return {
                "customer": r.customer,
                "origin": r.origin,
                "destination": r.destination,
                "effective_date": r.effective_date.isoformat(),
                "expiration_date": r.expiration_date.isoformat(),
                "rate": r.rate,
            }
        def fd(d: FieldDelta) -> dict:
            o, n = d.old, d.new
            return {
                "field": d.field,
                "old": o.isoformat() if isinstance(o, date) else o,
                "new": n.isoformat() if isinstance(n, date) else n,
            }
        return {
            "counts_raw": self.counts_raw(),
            "counts_reconciled": self.counts_reconciled(),
            "new": [rec(r) for r in self.new_after_reconcile],
            "deleted": [rec(r) for r in self.deleted_after_reconcile],
            "updated": [
                {"key": list(u.key), "old": rec(u.old), "new": rec(u.new),
                 "deltas": [fd(d) for d in u.deltas]}
                for u in self.updated
            ],
            "redated": [
                {
                    "customer": p.deleted.customer,
                    "origin": p.deleted.origin,
                    "destination": p.deleted.destination,
                    "old_effective": p.old_effective.isoformat(),
                    "new_effective": p.new_effective.isoformat(),
                    "expiration_date": p.new.expiration_date.isoformat(),
                    "rate": p.new.rate,
                }
                for p in self.redated
            ],
        }
