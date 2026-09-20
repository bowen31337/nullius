"""Feature 90's directive: the opaque ``charges_budget`` bit a trial row carries.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 90: *System
stamps every trial row with charges_budget supplied by the null oracle as
an opaque directive, never as a derived label.*  docs/nullius-tech-
architecture.md §8 fixes the column — ``charges_budget BOOLEAN NOT NULL`` —
and §7.2 fixes what it *means*: it is the one bit the null oracle lets cross
the barrier, returned alongside the target series, and it crosses as a
*directive*, never a *label*.  The caller learns *whether* to debit
statistical budget without learning *why* — without ever seeing ``is_null`` —
so the ledger's whole contract on this column is to *carry the bit it is
handed*, and never to compute it.

**The value is supplied, never derived.**  This is the clause the feature
turns on, and it shapes every seam.  ``charges_budget`` enters the member as
a value the caller holds — the evaluator's step-5 gate carries it through
untouched from the oracle's response — and the ledger records exactly that
value.  It is not inferred from ``node_id`` (a null node is indistinguishable
here from a real one — that is the whole point of the barrier), not from the
``outcome`` (a failed evaluation still charged budget if its targets were
real), not from anything else on the row.  The write seam therefore refuses a
value that is not a genuine :class:`bool`: a truthy ``1`` or a falsy ``0`` or
an absent ``None`` is not the oracle's directive, and coercing one would be
the first step toward the ledger deciding the answer itself.  The refusal
names the four outcomes' sibling fact — a row that cannot say whether it
charged budget is a row ``K_effective`` (feature 93) cannot classify.

**The storage spelling is 0-or-1, and a stored value that is neither is
corruption.**  SQLite has no ``BOOLEAN`` type, so the column stores the bit
as the integer ``0`` or ``1`` (the same spelling the evaluator's own cost
store uses for §7.2's directive).  A row read back therefore arrives as an
``int`` and is coerced to a :class:`bool`; a stored value that is neither
``0`` nor ``1`` is a hand that reached past the append — a mangled directive —
and is refused rather than served, exactly as a hand-edited ``ts`` or an
outcome that wandered outside the four is.  The read path revalidates through
this same check, so the refusal meets a corrupted row the same way it meets a
bad write.

**A pre-directive database is upgraded in place, with the honest
presumption.**  A table written before feature 90 recorded no directive, so
the upgrade adds the column with ``DEFAULT TRUE``.  That is not a derivation
and not the forbidden label: it is the one honest statement a row that
predates the null oracle can make.  The null oracle (features 109 on) did not
yet exist when those rows were written, so no null node was ever among them —
every one was a real trial that consumed statistical degrees of freedom, and
``TRUE`` asserts exactly that and nothing more.  It is also the safe
direction for the honest counter: counting a legacy row as budget-charging
can only ever understate the deflation the null nodes introduce, never
overstate it.  The ``ALTER`` is neither an ``UPDATE`` nor a ``DELETE`` — it
adds no charge and spends no sequence number — so it passes feature 92's wall.

Stdlib-only, like the rest of the member, and imported by every layer that
touches the column — the record (:mod:`ledger.record`), the store
(:mod:`ledger.store`), the debit endpoint (:mod:`ledger.debit`) — so the row,
the write and the wire cannot drift apart on what the directive may be.
"""

from __future__ import annotations

from typing import Any

from .errors import TrialRecordError

__all__ = ["validated_charges_budget"]


def validated_charges_budget(value: Any, *, strict: bool = False) -> bool:
    """Validate the opaque budget directive, returning it as a :class:`bool`.

    The one spelling the record, the store and the debit endpoint share, so a
    row's directive is validated identically wherever it enters the member.

    A genuine :class:`bool` — the form the live write carries, handed through
    from the null oracle's response — is returned as-is: the directive is
    already canonical, so there is nothing to normalise.  When ``strict`` is
    set (the write seams: the append, the debit, the debit request), anything
    that is not a bool is refused with
    :class:`~ledger.errors.TrialRecordError`, naming the value: a ``1`` or a
    ``0`` or an absent ``None`` is not the oracle's directive, and accepting
    one would be the ledger beginning to derive the bit it is only meant to
    carry.  Without ``strict`` (the read path, where a row arrives as the
    ``0``/``1`` the SQLite ``BOOLEAN`` column stores), a ``0`` or ``1`` integer
    is coerced to its bool, and only any other value — a ``2``, text, ``None``
    — is refused, because a stored directive that is neither bit is a hand that
    reached past the append, and a row that cannot say whether it charged
    budget is a row ``K_effective`` (feature 93) cannot classify.
    """
    if isinstance(value, bool):
        return value
    if not strict and isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise TrialRecordError(
        f"charges_budget must be a bool — §7.2's opaque budget directive from "
        f"the null oracle (True when the trial consumed statistical budget, "
        f"False when it did not), supplied by the caller and never a value the "
        f"ledger derives; got {value!r} ({type(value).__name__}). Every "
        f"appended trial row persists its directive (feature 90) because "
        f"K_effective counts only the budget-charging trials — a charge that "
        f"cannot say whether it charged budget is a charge no audit can "
        f"classify, and it is refused here, before the ledger is touched."
    )
