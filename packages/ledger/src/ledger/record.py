"""Feature 86's row layer: one trial_ledger row, as a value.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 86: *System
persists one trial_ledger row per evaluation under a monotonically
increasing sequence number.*  docs/nullius-tech-architecture.md §8 fixes
the row's first four columns — ``seq``, ``ts``, ``node_id``,
``campaign_id`` — and leaves the rest to the features that own them:
the charges_budget directive of 90 has landed on this row
(:mod:`ledger.budget`), the outcome of 91 (:mod:`ledger.outcome`), and
feature 89's charge unit (:mod:`ledger.units`) — how much the trial
*cost*, which a cross-validated evaluation states as more than the
ordinary one unit — and feature 88's epoch (:mod:`ledger.epoch`) —
*which sequestered epoch* it charged, the depleting holdout the spend
is booked against — while the provenance triple of 87 is still to
arrive.  This module is the row those columns make: the
value a debit writes, and the value a read hands back.  A record read from the ledger equals the record
the append returned — the row is a statement about a past charge, and a
re-read must not restate it.

**The sequence number is the table's to assign, and the record's to
carry.**  ``seq`` is assigned by the store's append
(:mod:`ledger.store`), never chosen by a caller; the record layer's only
job on it is to refuse a value the ledger could not have assigned — a
non-int, a bool (``bool`` is an ``int`` subclass, and ``True`` is not a
sequence number), anything below 1, where SQLite's ``AUTOINCREMENT``
counting starts.  The positive check is not decoration: construction
revalidates rows read back from disk, so it is the seam that refuses a
hand-mangled row whose ``seq`` was zeroed.

**The stamp is timezone-aware UTC, and a naive instant is refused.**  The
same rule the feature store's row layer states (feature 51): a ledger is
ordered and ranged by its stamp — "how many trials before ``t``" is a
question later features ask — and comparing a naive datetime against an
aware one raises :class:`TypeError` deep inside that query, far from the
write that could have named its offset.  Refusing the naive instant at
construction puts the failure on the writer.  An aware instant in another
offset names an unambiguous instant, so it is normalised to UTC rather
than rejected.  The default clock (:func:`utc_now`) stamps at second
resolution with microseconds *dropped* rather than rounded — the result
is never after the instant observed, and two debits that are "the same
second" for every practical purpose carry the same second.

**The identity columns are UUIDs, canonically spelled.**  A trial row
names the node that was evaluated and the campaign it belongs to — the
two identities §8 pins ``NOT NULL`` — and both are accepted as a
:class:`~uuid.UUID` or as text, then normalised to the canonical
hyphenated lowercase spelling so the row joins against the tree store's
``node.id`` / ``node.campaign_id`` however the caller came by the value.
A value that is not a UUID at all is refused at the write: a charge that
cannot be joined to the node that incurred it is a charge no audit can
attribute, and spending a sequence number on it would make the ledger's
count honest and its contents useless.

**The outcome is one of the four ways a trial ends (feature 91).**  The
column §8 declares ``outcome TEXT NOT NULL`` with the vocabulary fixed
in its own comment — ``ok | timeout | error | tripwire_fail`` — is a
required stamp on this record, validated through
:func:`ledger.outcome.validated_outcome` exactly as the identities and
the stamp are: a value outside the four is refused at the write, and a
row read back whose outcome has wandered outside them (a hand-edit, a
corruption) is refused rather than served.  The outcome is what the
count is *of* — a failed evaluation still consumed a hypothesis (§6.1,
step 11 debits even then) — so a row that cannot say how its trial
ended is a charge no audit can classify, and this layer does not build
one.

**The budget directive is a bit supplied, never derived (feature 90).**
The column §8 declares ``charges_budget BOOLEAN NOT NULL`` carries the
opaque directive the null oracle returns alongside the target series —
``True`` when the trial consumed statistical budget, ``False`` when it
did not (a null node).  It is a required stamp on this record,
validated through :func:`ledger.budget.validated_charges_budget`: a
genuine :class:`bool` is carried through untouched (the directive is
canonical, so there is nothing to normalise), and anything that is not
a bool is refused at the write — a ``1`` or a ``0`` or an absent
``None`` is not the oracle's directive, and accepting one would be the
ledger beginning to *derive* the bit it is only meant to *carry*.  A
row read back arrives as the ``0``/``1`` the SQLite column stores and
is coerced to its bool; a stored value that is neither bit (a hand-edit,
a corruption) is refused rather than served.  The directive is what
``K_effective`` (feature 93) filters on, so a row that cannot say
whether it charged budget is a charge no audit can classify, and this
layer does not build one.

**The epoch names the holdout the trial spent, and is required at the
write (feature 88).**  The column §8 declares ``epoch_id TEXT NOT NULL``
carries *which sequestered epoch was charged* — §8's own comment on the
column — and the write seams refuse a charge whose epoch is absent,
because the epoch is a depleting resource counted in ``epoch_ledger``
and ``K_effective`` is derived *per epoch* (feature 93), so a charge
that cannot name its holdout is a charge no audit can place.  The
validation runs through :func:`ledger.epoch.validated_epoch_id`: a
non-empty, non-blank :class:`str` is carried in its own spelling (the
epoch namespace is the sealing process's, shared with the epoch
ledger's primary key — this layer holds the name to being a name, it
coins none), and an absent, empty or non-string value is refused.  The
record layer itself accepts ``None`` for it, and deliberately: the
record is also the read, and a row written before the stamp landed —
on a table the store's legacy upgrade brings forward — honestly names
no epoch.  ``None`` reads back as the un-named epoch
(:data:`ledger.keffective.UNNAMED_EPOCH`), a statement about the
ledger's history rather than an epoch a caller named; the write's
``required`` refusal lives at the store's seams, exactly where the
feature's sentence puts it.

Instances are frozen: this is append-only accounting, and editing a
persisted charge in place would rewrite the account rather than
superseding it.  Supersession, where the category needs it, is a new row.

Stdlib-only, like the rest of the member: the row representation must
stay import-safe everywhere — the factory's scan, test sandboxes, the
deterministic replay path.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Union

from .budget import validated_charges_budget
from .epoch import validated_epoch_id
from .errors import TrialRecordError
from .outcome import validated_outcome
from .units import DEFAULT_CHARGE_UNITS, validated_charge_units

__all__ = ["TrialLedgerRecord", "utc_now"]


def utc_now() -> dt.datetime:
    """The current instant, timezone-aware UTC — the append's default clock.

    Second resolution, microseconds dropped rather than rounded: the stamp
    orders debits against one another and the sequence already does that
    exactly, so sub-second precision buys nothing a reader needs while
    making two debits that are "the same instant" for every practical
    purpose compare as different.  Dropping — not rounding — keeps the
    stamp never *after* the instant observed.
    """
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _validated_uuid(value: Any, field_name: str) -> str:
    """Validate an identity column, returning its canonical UUID spelling.

    Accepts a :class:`~uuid.UUID` or any text :func:`uuid.UUID` parses
    (hyphenated or not, any case), and returns the one spelling the table
    stores: hyphenated lowercase.  Anything else is a caller bug at the
    write — a charge that cannot be joined is a charge that cannot be
    audited — so it is refused here, naming the value.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError) as exc:
            raise TrialRecordError(
                f"{field_name} must be a UUID; got {value!r}: {exc}"
            ) from exc
    raise TrialRecordError(
        f"{field_name} must be a UUID or its text spelling; got "
        f"{type(value).__name__}"
    )


def _validated_instant(value: Any, field_name: str) -> dt.datetime:
    """Validate a stamp, returning it aware-UTC.

    Accepts a timezone-aware :class:`~datetime.datetime` (any offset — an
    aware instant in another offset names the same instant, so it is
    normalised rather than rejected) or its ISO-8601 text (the form the
    table stores, so a row read back revalidates through this same check).
    A naive datetime is refused: the ledger is ranged by its stamp, and a
    naive/aware comparison raises :class:`TypeError` far from the write
    that omitted the offset.
    """
    instant: dt.datetime
    if isinstance(value, dt.datetime):
        instant = value
    elif isinstance(value, str):
        try:
            instant = dt.datetime.fromisoformat(value)
        except ValueError as exc:
            raise TrialRecordError(
                f"{field_name} must be an ISO-8601 datetime or a datetime; "
                f"got {value!r}: {exc}"
            ) from exc
    else:
        raise TrialRecordError(
            f"{field_name} must be a timezone-aware datetime; got "
            f"{type(value).__name__}"
        )
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise TrialRecordError(
            f"{field_name} must be timezone-aware; got the naive datetime "
            f"{instant.isoformat()!r}. A ledger stamp is compared and ranged "
            "against other instants, and a naive one has no offset to "
            "compare with — pass an aware UTC instant (see utc_now())"
        )
    return instant.astimezone(dt.timezone.utc)


def _validated_seq(value: Any) -> int:
    """Validate a sequence number the ledger could have assigned.

    An ``int`` of 1 or more, and not a ``bool``: ``True`` is an ``int``
    subclass equal to 1, and a sequence number that arrived as a truth
    value is a caller bug wearing a valid number.  Anything else — a
    float, numeric text — is refused rather than coerced, because a
    coerced sequence is a row the ledger never appended.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrialRecordError(
            f"seq must be an integer assigned by the ledger's append; got "
            f"{type(value).__name__}"
        )
    if value < 1:
        raise TrialRecordError(
            f"seq must be 1 or greater (the ledger counts from 1); got "
            f"{value!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class TrialLedgerRecord:
    """One persisted ``trial_ledger`` row: a charge, as a value.

    ``seq`` is the monotonically increasing sequence number the table
    assigned at the append — the row's order in the log, and the number
    feature 86's whole sentence turns on.  ``ts`` is when the charge was
    debited, aware-UTC, fixed at write time and never restated by a read.
    ``node_id`` and ``campaign_id`` name the evaluation that was charged:
    the node the evaluator ran and the campaign it belongs to, both in
    canonical UUID spelling so the row joins against the tree store.
    ``outcome`` is how that evaluation ended — one of the four
    :data:`~ledger.outcome.OUTCOMES` — carried on every row because the
    honest count is a count of *outcomes*, and a failed trial is as
    chargeable a fact as a successful one.  ``charges_budget`` is whether
    the trial consumed statistical budget — ``True`` for a real trial,
    ``False`` for a null node — the opaque directive §7.2's null oracle
    returns alongside the target series, carried on every row because
    ``K_effective`` (feature 93) is a count of *budget-charging* trials,
    and a null node must never inflate it.  Supplied by the caller, never
    derived by the ledger.  ``charge_units`` is what the trial cost —
    ``1.0`` for an ordinary evaluation, more for a cross-validated one
    whose folds each compare a fit against the same forward returns
    (§8's own comment on the column: *"1.0 default; CV folds may cost
    more"*) — validated as a positive finite real and defaulted to
    :data:`~ledger.units.DEFAULT_CHARGE_UNITS`, mirroring the column's
    own ``DEFAULT``.  It prices the evaluation; it is a different fact
    from ``charges_budget``, which says whether the evaluation spent
    statistical degrees of freedom at all.  ``epoch_id`` is the
    sequestered epoch the trial charged (§8: ``epoch_id TEXT NOT NULL``
    with the comment *"which sequestered epoch was charged"*; feature
    88's stamp) — the holdout the spend is booked against, in the
    sealing process's own spelling.  The write seams refuse a charge
    whose epoch is absent (see :func:`ledger.epoch.validated_epoch_id`);
    the record accepts ``None`` for it because the record is also the
    read, and a row that predates the stamp honestly names no epoch.

    Construction validates and canonicalises, so an instance is
    trustworthy by construction: the store's append builds its return
    value through this constructor, and the read path rebuilds rows
    through it, which is how a malformed row on disk is refused rather
    than served.  Frozen, because this is the append-only half of the
    accounting: a record of a past charge is a fact, and facts are
    superseded by new rows, never edited.
    """

    #: The sequence number the append assigned — 1, 2, 3, … strictly
    #: increasing for the life of the table, never reused.
    seq: int
    #: When the charge was debited, aware-UTC; the default clock stamps at
    #: second resolution.
    ts: dt.datetime
    #: The evaluated node, canonical UUID spelling (§8: ``node_id UUID``).
    node_id: str
    #: The campaign the node belongs to, canonical UUID spelling.
    campaign_id: str
    #: How the evaluation ended — one of 'ok', 'timeout', 'error',
    #: 'tripwire_fail' (§8's vocabulary; feature 91's stamp).
    outcome: str
    #: Whether the trial consumed statistical budget — ``True`` for a real
    #: trial, ``False`` for a null node (§7.2's opaque directive; feature
    #: 90's stamp).  Supplied by the caller, never derived by the ledger.
    charges_budget: bool
    #: What the trial cost, in units (§8: ``charge_units REAL NOT NULL
    #: DEFAULT 1.0``; feature 89's stamp).  ``1.0`` — the default, which
    #: mirrors the column's own ``DEFAULT`` — is what an ordinary
    #: evaluation is worth; a cross-validated one whose folds each compare
    #: a fit against the same forward returns states the folds' count
    #: instead.  Validated as a positive finite real.
    charge_units: float = DEFAULT_CHARGE_UNITS
    #: The sequestered epoch the trial charged (§8: ``epoch_id TEXT NOT
    #: NULL`` — *"which sequestered epoch was charged"*; feature 88's
    #: stamp), in the sealing process's own spelling.  ``None`` is the
    #: read's spelling for a row that predates the stamp — the un-named
    #: epoch — and is refused at the write seams, never here.
    epoch_id: Optional[str] = None

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction.  After
        # this the instance is sealed.
        object.__setattr__(self, "seq", _validated_seq(self.seq))
        object.__setattr__(self, "ts", _validated_instant(self.ts, "ts"))
        object.__setattr__(
            self, "node_id", _validated_uuid(self.node_id, "node_id")
        )
        object.__setattr__(
            self, "campaign_id", _validated_uuid(self.campaign_id, "campaign_id")
        )
        object.__setattr__(
            self, "outcome", validated_outcome(self.outcome)
        )
        # A bool is carried through untouched; a 0/1 read back from disk is
        # coerced to its bool.  A value that is neither is refused — the
        # read path revalidates through this same check.
        object.__setattr__(
            self, "charges_budget", validated_charges_budget(self.charges_budget)
        )
        # Normalised to the float the REAL column holds, so a unit of 5
        # and a unit of 5.0 are one value and one row.  A non-finite or
        # non-positive unit is refused — the read path revalidates through
        # this same check, which is how a row whose unit wandered off the
        # real line is refused rather than served.
        object.__setattr__(
            self, "charge_units", validated_charge_units(self.charge_units)
        )
        # Carried in the sealing process's own spelling, or None for a row
        # that predates the stamp — the write's required-epoch refusal is
        # the store's and the endpoint's, not the read's.  A blank or
        # non-string value is refused here too: the read revalidates
        # through this same check, which is how a row whose epoch wandered
        # into a name that names no epoch is refused rather than served.
        object.__setattr__(
            self, "epoch_id", validated_epoch_id(self.epoch_id)
        )

    def row(self) -> tuple[Union[int, float, str, None], ...]:
        """The record as the store's column tuple, in table order.

        ``seq, ts, node_id, campaign_id, outcome, charges_budget,
        charge_units, epoch_id`` — the order the table's columns are
        declared in and the order the read path unpacks, kept in one
        method so the two cannot drift apart and silently swap an
        identity for a stamp.  ``ts`` serialises as canonical ISO-8601
        UTC with an explicit offset, the exact text the table stores;
        ``charges_budget`` serialises as the ``0``/``1`` the SQLite
        ``BOOLEAN`` column stores; ``charge_units`` serialises as the
        ``float`` the ``REAL`` column holds; ``epoch_id`` serialises as
        the text the sealing process coined, or ``None`` for a row that
        predates the stamp (the NULL a brought-forward table's upgrade
        column holds).
        """
        return (
            self.seq,
            self.ts.astimezone(dt.timezone.utc).isoformat(),
            self.node_id,
            self.campaign_id,
            self.outcome,
            1 if self.charges_budget else 0,
            self.charge_units,
            self.epoch_id,
        )
