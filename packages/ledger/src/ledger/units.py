"""Feature 89's stamp: the ``charge_units`` a trial row costs.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 89: *System
stamps every trial row with charge_units defaulting to 1.0, so a
cross-validated evaluation can cost more than one unit.*  docs/nullius-
tech-architecture.md §8 declares the column — ``charge_units REAL NOT NULL
DEFAULT 1.0`` — with its reason in the comment beside it: ``-- 1.0
default; CV folds may cost more``.

**The unit is what a trial *cost*, not what it *counted*.**  §8's column
exists because the honest counter's arithmetic is not one-row-one-unit:
an ordinary evaluation prices one hypothesis, while a cross-validated one
runs its signal over several folds and so compares several fits against
the same forward returns.  The default of ``1.0`` is therefore the
*ordinary* trial's honest weight — an append or a debit that says nothing
about units is charged exactly one — and a caller whose evaluation ran
more folds states a larger number.  This is the same shape feature 90's
directive takes and the opposite of its stance on defaults: §8 gives
``charge_units`` a default because one unit is a real trial's honest
weight, and gives ``charges_budget`` none because a null node's directive
is the oracle's to state.  The two are *different resources* — 89 prices
the evaluation, 90 says whether it spent statistical degrees of freedom —
and this module owns only the first.

**The unit is a positive, finite real.**  Three refusals, each a caller
bug rather than a runtime condition:

* a non-number — text, ``None``, a :class:`bool`.  ``bool`` is refused
  explicitly because ``isinstance(True, int)`` and a unit of ``True`` is a
  flag that wandered into a numeric column, the same discipline the
  ``seq`` check applies to the sequence number;
* a non-finite number — ``NaN``, ``inf``.  A NaN is the worse of the two
  and refused on its own ground: SQLite stores a NaN as ``NULL`` (verified
  against the dialect), so a NaN that got past this check would land as
  the *absence* of a unit on an append-only row that can never be
  corrected — the one failure mode a ledger cannot walk back.  Infinity
  survives the round trip intact and would poison every later sum of the
  column just as thoroughly;
* a value at or below zero — a trial that cost nothing or less than
  nothing is not a charge.  ``0.0`` is the sharp case: it is the spelling
  of "this evaluation was free", and §6.1's step 11 debits *even when the
  node fails*, so no trial this ledger records is free.  A caller that
  wants a trial not to count has a different and already-existing seam —
  ``charges_budget=False`` (feature 90), which is what ``K_effective``
  filters on — and should not be spelling it as a zero-cost charge here.

  Refusing rather than clamping is deliberate: clamping a negative to
  ``1.0`` would be the ledger *deriving* a unit the caller never stated,
  and the direction it would derive in (a charge silently becoming a full
  unit) is the direction that inflates ``K``.

**The storage spelling is a real, and the read coerces honestly.**  The
SQLite ``REAL`` column has REAL affinity, so an ``int`` written as ``5``
lands as ``5.0``, a genuine ``bool`` lands as ``1.0``/``0.0``, and text
lands as **text** — SQLite does not coerce a non-numeric string on
affinity alone, and a ``REAL`` column is not declared with ``STRICT``.
That last fact is why the read path revalidates through this same
function rather than trusting the column: a row whose unit wandered off
the real line — a hand-edit, a corruption, a writer from outside this
package — is refused by its ``seq`` rather than served as though a unit
had been stated.  A stored ``1.0`` reads back as the ``1.0`` an ordinary
trial carries, whether it was written as ``1.0`` or as the ``1`` an
integer caller passed.

Stdlib-only, like the rest of the member, and imported by every layer
that touches the column — the record (:mod:`ledger.record`), the store
(:mod:`ledger.store`), the debit endpoint (:mod:`ledger.debit`) — so the
row, the write and the wire cannot drift apart on what a unit may be.
"""

from __future__ import annotations

import math
from typing import Any

from .errors import TrialRecordError

__all__ = ["DEFAULT_CHARGE_UNITS", "validated_charge_units"]

#: The unit an ordinary evaluation costs — §8's own default for the
#: column, ``charge_units REAL NOT NULL DEFAULT 1.0``.  Spelled as a
#: constant here so the record's default, the store's insert and the
#: table's DDL cannot drift apart on the one number a plain trial is
#: worth.  A cross-validated evaluation states its folds' count instead.
DEFAULT_CHARGE_UNITS: float = 1.0


def validated_charge_units(value: Any) -> float:
    """Validate a charge unit, returning it as a positive finite :class:`float`.

    The one spelling the record, the store and the debit endpoint share,
    so a row's unit is validated identically wherever it enters the
    member.  An ``int`` or a ``float`` — the two forms a caller states a
    cost in — is normalised to a ``float`` (the form the ``REAL`` column
    holds, so a unit of ``5`` and a unit of ``5.0`` are one value and one
    row), provided it is finite, positive and not a :class:`bool`.

    Anything else is refused with :class:`~ledger.errors.TrialRecordError`
    naming the value, *before* the database is touched, so a refused
    charge spends no sequence number: a row whose unit cannot be believed
    is a row whose cost is fiction, and fiction in this column is exactly
    what feature 89's stamp exists to keep out.  See the module docstring
    for why each refusal is in the direction it is — in particular why a
    ``NaN`` cannot be allowed to reach a column that stores it as
    ``NULL`` on a table that can never be corrected.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrialRecordError(
            f"charge_units must be a real number — §8's cost of one trial, "
            f"1.0 for an ordinary evaluation and more for a cross-validated "
            f"one whose folds each compare a fit against the same forward "
            f"returns (feature 89); got {value!r} "
            f"({type(value).__name__}). Every appended trial row is stamped "
            f"with its unit, and a unit that is not a number is a cost no "
            f"audit can sum."
        )
    units = float(value)
    if math.isnan(units) or math.isinf(units):
        raise TrialRecordError(
            f"charge_units must be finite; got {value!r}. A non-finite unit "
            f"is refused rather than stored: SQLite persists a NaN as NULL, "
            f"so a NaN that reached the append would land as the *absence* "
            f"of a unit on a row this ledger can never correct, and an "
            f"infinity would poison every later sum of the column."
        )
    if units <= 0.0:
        raise TrialRecordError(
            f"charge_units must be greater than zero; got {value!r}. A "
            f"trial that cost nothing is not a charge — §6.1's step 11 "
            f"debits even when the node fails — and 0.0 is the spelling of "
            f"'this evaluation was free', which no row this ledger records "
            f"is. A trial that should not count against K_effective states "
            f"charges_budget=False (feature 90), not a zero-cost charge; "
            f"and a unit below zero is refused rather than clamped, because "
            f"clamping would derive a weight the caller never stated."
        )
    return units
