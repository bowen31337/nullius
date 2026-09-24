"""Persisting the running decision count — feature 294, the epoch's charge.

app_spec.xml, "Promotion & Epoch Governance", feature 294: *System persists
the running promotion decision count against the serving epoch in the
epoch_ledger.*  Its declared parent is feature 293 — the decision — and the
column it writes has been waiting since ``0110`` created the table:
``promotion_decisions_served INT NOT NULL DEFAULT 0``, whose own comment
names this feature as the writer: *"The count is advanced by ``UPDATE``
(feature 294's writer contract), and a default fires only at insert, so the
promotion plugin re-supplies the value on every advance — the same writer
contract 0107 states for its counts."*  This module is that contract's
other half: the sealing process writes the row with the default's zero, and
this act re-supplies the figure every time a promotion decision lands
against the epoch the registration booked.

**§13 item 4 is the law the count serves, and the count is all of it this
module enforces.**  docs/alpha-engine-prd.md: *"Sequestered epochs are
retired permanently after **3 promotion decisions**. Track in a ledger.
When clean epochs run out, the system stops. That is a legitimate terminal
state."*  Every promotion decision spends a little of the holdout it was
judged on — each decision is a chance for information about the epoch to
leak into what gets promoted — so the PRD makes the spend a tracked
quantity, and ``0110``'s own docstring says what the things counted are:
*"events recorded in ``promotion_registry``."*  The threshold is **not**
this module's: feature 295 reads ``promotion_decisions_served >= 3`` and
refuses further selection, feature 296 reads the ``retired`` flag for the
terminal state, feature 297 reads the depleting remainder — and every one
of them reads a figure this act persisted.  So the one column the
``UPDATE``'s ``SET`` clause names is the count, and the sealing instant and
the retirement flag are values the charging write *cannot touch* — the
mirror of :mod:`promotion.decision`'s one-column law, spelled for a table
whose other two columns belong to acts that are not this one's to perform.

**The count is derived, not incremented, and the derivation is the
idempotence.**  An incrementing charge — ``SET served = served + 1`` —
would make the ledger a second source of truth about one fact, free to
drift from the rows it counts, and a retried charge (a response lost, a
worker restarted) would double-count a decision that happened once.  This
act recounts: :func:`decisions_served` reads the closed rows feature 293's
listing holds against the serving epoch and writes *that* figure, so a
retry recomputes the same number, a charge that arrives after another
process advanced the column writes the same total, and the ledger stays a
function of the registry rather than a tally beside it.  ``0110``'s
"re-supplies the value on every advance" read strictly: the value written
is the count the rows state, whatever the standing figure says — with the
one refusal below for a count that would *shrink*.

**"The serving epoch" is read off the row, and the omission is feature
293's own.**  The act takes a node, and the epoch it charges is the
``epoch_id`` that node's pre-registration booked — the sequestered holdout
the deciding evaluation spent, named once before the evaluation by feature
291's act.  :mod:`promotion.decision` refused an ``epoch_id`` argument for
exactly this reason — *"a decision that took an ``epoch_id`` would let a
caller spend a different holdout than the one booked, which is the reuse
§13 item 4 retires epochs to prevent"* — and the charge inherits the
refusal: a caller who could name the epoch to bill would be able to bill a
clean one for a decision that spent a booked one, which is the same leak
moved one act later.  The node's row is the booking; the charge reads it
and bills what it says.

**It counts through feature 293's own seam rather than spelling a second
``SELECT``.**  :meth:`~promotion.decision.PromotionDecisions.decision`
already answers *this node's row, open or closed*, and
:meth:`~promotion.decision.PromotionDecisions.decisions` already enumerates
every closed row with its epoch — *"the listing an auditor reads before
charging epochs (feature 294's precondition)"*, in that module's own words.
A second registry read here would be a second reading of one table, the
discipline :mod:`promotion.forward` states when it reads the same rows for
its window; this module is the first *writer* to take that stance, and the
consequence runs into its bootstrap (below): the registry is the decision
store's dependency, never this act's.

**A row that is absent or still open is refused, and that is the load in
``depends_on="293"``.**  A node nobody pre-registered has no booking to
bill — the repair is feature 291's act, then feature 293's.  A node whose
row is still **open** has a pre-registration whose deciding evaluation has
not been recorded: the epoch has served no decision for it, and charging
one anyway would count a promotion that has not been decided — inflating
the spend §13 item 4 budgets, and retiring clean epochs early, which is
the opposite failure from the reuse the ledger exists to prevent.  Both
are refused by name, in this feature's vocabulary.

**The count never shrinks, and a derivation that would shrink it is
refused rather than authored.**  Decisions this member writes never
reopen — :data:`~promotion.decision._UPDATE_SQL` carries ``AND decided_at
IS NULL``, so a decided row stays decided and the count derived from the
closed rows is monotone.  A recomputed count *below* the standing figure
therefore means decided rows vanished: a hand reached past the member with
a raw connection.  Writing the lower figure would be authoring precisely
the state ``0110``'s own docstring dreads — *"a duplicate epoch row would
split its served count in half, letting feature 295's three-decision
threshold read a 'clean' epoch that had already served its budget"* — the
same failure, arrived at by deletion rather than duplication.  **This is
not this store judging the promotion**, the distinction
:mod:`promotion.decision` makes for its ordering refusal: nothing here
reads evidence, scores anything or decides whether a promotion stands; it
declines to persist a figure that contradicts the rows it is a function
of.  The repair is to the database.

**The ledger row must exist, and its absence names a hand.**  Through this
member's writers the state is unreachable: feature 291 probes
``epoch_ledger`` for the epoch by name *before* the insert, the foreign
key holds on every connection this member opens, and nothing deletes
ledger rows.  A decided registry row whose ledger row is gone is therefore
a write that bypassed the pragma, and the charge refuses it rather than
recreating the parent — ``0110``'s downgrade docstring reserves the
refill-after-drop to the *sealing* process's next write, not to this act,
and a charge that invented a sealed epoch would be fabricating the moment
of sequestration, which is the one fact this module must never mint.

**The bootstrap's one owner, and why it is not the registry's.**
:mod:`promotion.schema` states the rule — *the set is the tables this
act's own statements name* — and this act's two statements (the ledger
read and the one-column ``UPDATE``) name ``epoch_ledger`` and nothing
else.  ``epoch_ledger`` references nothing — ``0110`` declares
``REQUIRES_TABLES = ()``, because epochs are named by the sealing process
rather than looked up from a parent — so the ``UPDATE`` resolves no
foreign key's parent on any dialect; and the count arrives through the
decision store's seam, whose own bootstrap brings ``promotion_registry``
up.  :data:`~promotion.schema.CHARGE_MIGRATION_ORDER` is therefore one
owner, ``0110``, run whole; a charge store that ran the registry's owner
too would be creating ``promotion_registry`` — and ``0108``'s five
neighbours with it — for statements that name none of them, the habit
:mod:`promotion.schema` exists to keep distinguishable from a dependency.

**SQLite reads the flag as an integer, and the record says so.**  The
store's connections enable ``PRAGMA foreign_keys = ON`` like every store
in this member, but no pragma changes what a ``BOOLEAN`` column *returns*
on SQLite: ``0`` and ``1``, the DBAPI affinity trap this workspace states
for its boolean columns.  :func:`_validated_retired` coerces the two legal
integers and refuses anything else, and
:func:`_validated_served_count` holds the count to a non-negative
``int`` with ``bool`` refused first — ``True`` is ``1`` in Python, and a
flag where a served count belongs would silently answer one decision
nobody recorded.

**No component, no seat, no router, no second builder.**  The member's
registered surface stays feature 291's one store, for the reason the
member's own docstring gives this feature: the count is a function of
evidence the factory does not hold — a decision has to have been recorded
somewhere else first — so the store is constructed from a URL by the
caller that has one, exactly as its three writer siblings are.  The seat
(``src/app/modules/promotion``) is untouched and still answers one
question.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``os``,
``collections.abc``, ``contextlib``, ``dataclasses``, ``pathlib`` and
``typing`` at module scope plus this member's own four modules — no
third-party import and no import of another workspace member, so the
factory's scan imports this package for the near-nothing it always did
and a charge costs its caller only the connections it already had.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .decision import PromotionDecisions
from .errors import (
    EPOCH_CHARGE_ERROR_CODE,
    EpochChargeError,
    PromotionError,
    PromotionStoreError,
)
from .pre_register import (
    DATABASE_URL_ENV,
    EPOCH_ID_COLUMN,
    NODE_ID_COLUMN,
    PromotionRecord,
    _sqlite_path,
    _validated_epoch_id,
    _validated_instant,
    _validated_uuid,
)
from .schema import (
    EPOCH_LEDGER_TABLE,
    PROMOTION_REGISTRY_TABLE,
    bootstrap_charge_schema,
)

__all__ = [
    "PROMOTION_DECISIONS_SERVED_COLUMN",
    "RETIRED_COLUMN",
    "SEALED_AT_COLUMN",
    "EpochCharges",
    "ServingEpoch",
    "charge_epoch",
    "decisions_served",
    "epoch_charge",
]

#: When the epoch was sequestered — the sealing process's fact, read here
#: and never written: the row *is* the sealing event, in ``0110``'s own
#: words, and the charge is a later act over the resource that event made.
SEALED_AT_COLUMN = "sealed_at"

#: The running count this feature persists — §13 item 4's tracked quantity,
#: the one column the charge's ``UPDATE`` names, and the figure features
#: 295-297 read.  Spelled exactly as ``0110`` declares it, because the
#: exhaustion machinery greps the schema's spelling, not a shortened one.
PROMOTION_DECISIONS_SERVED_COLUMN = "promotion_decisions_served"

#: Whether the epoch has been retired — feature 296's flag, and a value
#: this act reads onto the record but never writes: retirement is the
#: exhaustion machinery's verdict on the count, not the count's own.
RETIRED_COLUMN = "retired"

#: The ledger read — the four columns the table holds, in the order
#: :func:`_record_from_row` unpacks, keyed by the epoch's own name.  More
#: than one row for a name is unreachable through the owner's DDL (the key
#: *is* the primary key), and the read refuses it anyway, for the reason
#: :meth:`~promotion.decision.PromotionDecisions._registration_of` refuses
#: a second registry row: nothing this member writes can produce the state,
#: so a second row is a hand that reached past it.
_EPOCH_READ_SQL = (
    f"SELECT {EPOCH_ID_COLUMN}, {SEALED_AT_COLUMN}, "
    f"{PROMOTION_DECISIONS_SERVED_COLUMN}, {RETIRED_COLUMN} "
    f"FROM {EPOCH_LEDGER_TABLE} WHERE {EPOCH_ID_COLUMN} = ?"
)

#: The write — one column in the ``SET`` clause, and that is the whole of
#: the boundary this module states for it.  The ``WHERE`` names the key and
#: nothing else, deliberately: unlike feature 293's once-only close, the
#: charge is *repeatable* — the running count is re-supplied on every
#: advance, and a second writer billing the same epoch writes the same
#: derived figure.  ``sealed_at`` and ``retired`` are values this
#: statement has no clause for, so the charging write cannot mint a
#: sequestration instant or pronounce a retirement.
_UPDATE_SQL = (
    f"UPDATE {EPOCH_LEDGER_TABLE} SET {PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
    f"WHERE {EPOCH_ID_COLUMN} = ?"
)


# -- Validation --------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> EpochChargeError:
    """Re-raise a sibling's refusal in this feature's vocabulary.

    The seam rule this workspace states at every member boundary, applied
    *inside* one member — the shape :func:`promotion.decision._translated`,
    :func:`promotion.blocking._translated`,
    :func:`promotion.calibration._translated` and
    :func:`promotion.forward._translated` take toward the same validators.
    Feature 291's calendar of refusals raises ``PromotionError`` for a
    malformed identity and ``PromotionStoreError`` for a path it cannot
    speak, and feature 293's store raises ``PromotionDecisionError`` for a
    registry row it cannot read; a caller whose single ``except
    EpochChargeError`` guards its epoch-governance path must not be
    defeated by a refusal phrased for one of those acts — it would read
    *the pre-registration was malformed* where the truth is *this epoch was
    never charged*, and would go on to let a spent epoch read as clean, the
    silence §13 item 4's ledger exists to make impossible.  The inner
    message is carried through, so nothing an operator needs is lost; only
    re-framed, with the frame naming which act was being performed.

    ``type(exc)(...)`` is deliberately **not** used: here the class itself
    is the thing being corrected, exactly as in the four siblings.
    """
    return EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: the {what} could not be read to "
        f"charge this epoch: {exc}"
    )


def _charge_node_id(value: Any) -> str:
    """Return ``value`` as a node identity, or refuse it in *this* vocabulary.

    Feature 291's identity validator is the one spelling this member has for
    *an id that joins the tree*, and the charge's node is exactly that value
    — the node whose decided row books the epoch being billed — so the rule
    is *used* rather than restated, the move every sibling makes.  What it
    raises is ``PromotionError``, the member's ask face, and that is what
    the wrapper is for: the refusal has to arrive as a *charge* refusal, or
    a caller's single ``except EpochChargeError`` walks through it and the
    epoch stands uncharged.
    """
    try:
        return _validated_uuid(value, NODE_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "node identity") from exc


def _charge_epoch_id(value: Any) -> str:
    """Return ``value`` as an epoch's name, or refuse it in this vocabulary.

    The same seam over feature 291's epoch validator: the *rule* (non-empty
    stripped text, the near-miss a trailing newline would otherwise persist
    as a second name for one epoch) is the member's one spelling and is used
    rather than restated; the *class* is translated, so a blank epoch handed
    to the read is refused as a charge that could not be made rather than as
    a pre-registration that could not be written.
    """
    try:
        return _validated_epoch_id(value)
    except PromotionError as exc:
        raise _translated(exc, EPOCH_ID_COLUMN) from exc


def _sealed_instant(value: Any) -> Any:
    """Return ``value`` as the sealing instant, aware-UTC, or refuse it.

    The row's ``sealed_at``, held to the member's one instant rule (aware,
    normalised to UTC, ISO-8601 text accepted so a row read back
    revalidates) and re-framed in this feature's vocabulary — the same seam
    :func:`promotion.forward._instant_of` takes over the same validator.
    The charge stamps nothing, so the instant is never an argument; this
    wrapper exists for the *read* path, where SQLite's dynamically typed
    columns can hand back anything and a ledger row whose sealing instant
    cannot be read is a row this module cannot vouch for.
    """
    try:
        return _validated_instant(value, SEALED_AT_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, SEALED_AT_COLUMN) from exc


def _validated_served_count(value: Any) -> int:
    """Return ``value`` as a served count, or refuse what is not one.

    A non-negative ``int``, with ``bool`` refused first — ``True`` is ``1``
    in Python, and a flag where a count belongs would silently answer one
    decision nobody recorded.  Negative is refused because no honest count
    of rows is negative: the figure is :func:`decisions_served`'s output or
    the standing column's past, and a negative value on a row is a hand's
    edit this read declines to inherit.  The rule is this module's own
    rather than delegated, for the same reason
    :func:`promotion.forward._validated_window_days` restates its boundary:
    the sibling validator's message speaks of a promotion criterion and
    names feature 291, and a caller who passed a fraction here would be
    told about the wrong act.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise EpochChargeError(
            f"{EPOCH_CHARGE_ERROR_CODE}: {PROMOTION_DECISIONS_SERVED_COLUMN} "
            f"must be a non-negative integer — got {value!r} "
            f"({type(value).__name__}); the column is §13 item 4's tracked "
            "count of the promotion decisions a sequestered epoch has "
            "served, and a figure that is not a count of rows is not a "
            "figure this member could have written (feature 294)"
        )
    if value < 0:
        raise EpochChargeError(
            f"{EPOCH_CHARGE_ERROR_CODE}: {PROMOTION_DECISIONS_SERVED_COLUMN} "
            f"must be a non-negative integer — got {value!r}. The count is "
            "derived from the closed promotion_registry rows "
            ":func:`decisions_served` holds against the epoch, and no count "
            "of rows is negative — a negative value on a row is an edit "
            "this read refuses to inherit, because features 295-297 budget "
            "the epoch's whole lifetime on this column (feature 294)"
        )
    return value


def _validated_retired(value: Any) -> bool:
    """Return ``value`` as the retirement flag, or refuse what is not one.

    SQLite's ``BOOLEAN`` affinity hands the DBAPI ``0`` and ``1`` — the
    trap this workspace states for its boolean columns — so the two legal
    integers are coerced and everything else is refused.  ``2`` is not a
    spelling of *retired* any dialect produces, and a text value is a
    hand's edit; either would make feature 296's terminal state a question
    about a column nobody can read.  The coercion is exact rather than
    truthy because the flag is read for its identity, not its usefulness:
    a caller asking *is this epoch clean?* must not have the answer depend
    on which of two equal spellings the row happens to carry.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: {RETIRED_COLUMN} must be a boolean — "
        f"got {value!r} ({type(value).__name__}). SQLite reads the column "
        "as the integers 0 and 1 and this record answers a real bool, so a "
        "value that is neither spelling is an edit this member could not "
        "have written — and feature 296's terminal state is decided on "
        "exactly this flag (feature 294)"
    )


# -- The derivation ----------------------------------------------------------------


def decisions_served(
    records: Iterable[Any], epoch_id: Any
) -> int:
    """The promotion decisions ``records`` holds against one epoch — the count.

    The pure half of the feature's pair: the running count is a function of
    the closed rows and nothing else, so the derivation is stated once as a
    function any caller (this store's write, feature 295's threshold, a
    report, a test) can hold, and the store's ``UPDATE`` writes this
    figure rather than an increment.  A record is *counted* when its
    ``epoch_id`` equals the named epoch and it is not open — an open row is
    a pre-registration, not a decision, and counting one would bill the
    epoch for a promotion whose deciding evaluation has not run.  The
    records are duck-read (``epoch_id`` and ``open``), so the composed
    listing and a test's stand-ins count identically.

    Deliberately total over its input: the listing feature 293 answers with
    is already validated row by row, so a second validation here would be
    the store confirming itself.  The epoch's own name is validated,
    because it is the one value this function's caller supplies.
    """
    epoch = _charge_epoch_id(epoch_id)
    return sum(
        1
        for record in records
        if record.epoch_id == epoch and not record.open
    )


# -- The record --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServingEpoch:
    """One ``epoch_ledger`` row, as the charge reads it — feature 294's value.

    The four fields are the table's four columns: the epoch's name, the
    moment it was sealed, how many promotion decisions it has served, and
    whether it is retired.  Frozen, because this value is the ledger's
    testimony about a depleting resource — a caller who could edit the
    served count in memory would hold a figure the table contradicts, and
    features 295-297 read this row to decide what the whole system may
    still do.  The discipline every record in this workspace states.

    Validated in :meth:`__post_init__` rather than only through the store,
    for the reason :class:`~promotion.pre_register.PromotionRecord` states:
    ``dataclasses.replace`` and unpickling both rebuild instances past a
    factory's nose, and SQLite's columns are dynamically typed, so a
    hand-edited row is reachable here and a charge rebuilt from one without
    revalidation would certify a count nobody derived — the split served
    count ``0110``'s own docstring calls the failure the primary key
    exists to prevent.
    """

    #: The sequestered epoch's name — the sealing process's own spelling,
    #: and the key the row is read back by.
    epoch_id: Any
    #: When the epoch was sequestered.  Read and never written by this
    #: member: the row is the sealing event, and the charge is a later act
    #: over the resource that event made.
    sealed_at: Any
    #: The running count of promotion decisions the epoch has served —
    #: §13 item 4's tracked quantity, the one column this feature's
    #: ``UPDATE`` names.
    promotion_decisions_served: Any
    #: Whether the epoch has been retired — feature 296's flag, carried
    #: faithfully so this record can answer for the whole row, never
    #: written by this act.
    retired: Any

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline the criteria value, the registry record and every
        # sibling record in this member follow.
        object.__setattr__(self, "epoch_id", _charge_epoch_id(self.epoch_id))
        object.__setattr__(self, "sealed_at", _sealed_instant(self.sealed_at))
        object.__setattr__(
            self,
            "promotion_decisions_served",
            _validated_served_count(self.promotion_decisions_served),
        )
        object.__setattr__(self, "retired", _validated_retired(self.retired))

    # No budget predicate here.  The number §13 item 4 retires epochs at is
    # feature 295's refusal, and a record that carried its own spelling of
    # the boundary would be a second place that number lives: this module's
    # stated law is that it persists the count and stops there, and
    # features 295-297 read the figure off this row through their own
    # stores.

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline every record
        in this workspace follows: a rendered mapping names the same things
        the same way the row does.
        """
        return {
            EPOCH_ID_COLUMN: self.epoch_id,
            SEALED_AT_COLUMN: self.sealed_at,
            PROMOTION_DECISIONS_SERVED_COLUMN: self.promotion_decisions_served,
            RETIRED_COLUMN: self.retired,
        }

    # No ``__repr__`` here: ``@dataclass`` generates one over the four
    # stored fields, which is exactly the rendering a debugging caller
    # wants and is the one the sibling records in this member rely on —
    # hand-writing it would be a second spelling of the same fields, free
    # to fall out of step with them.


def _record_from_row(row: tuple[Any, ...], epoch: str) -> ServingEpoch:
    """Build a :class:`ServingEpoch` from a ledger row, with the epoch named.

    The read path's one constructor, so every read in the store builds the
    value the same way.  A validation refusal raised off the row is
    re-raised with the epoch in front of it — the difference between an
    operator learning *this epoch's ledger row is corrupt* and learning
    only that some row somewhere is not readable as a serving epoch.  The
    inner refusal's own code word is stripped before the re-frame, because
    one refusal carries one code word: the operator greps the word to find
    *the act*, and a doubled one would read as two uncounted epochs.
    """
    try:
        return ServingEpoch(
            epoch_id=row[0],
            sealed_at=row[1],
            promotion_decisions_served=row[2],
            retired=row[3],
        )
    except EpochChargeError as exc:
        detail = str(exc)
        prefix = f"{EPOCH_CHARGE_ERROR_CODE}: "
        detail = detail.removeprefix(prefix)
        raise EpochChargeError(
            f"{EPOCH_CHARGE_ERROR_CODE}: the {EPOCH_LEDGER_TABLE} row for "
            f"{EPOCH_ID_COLUMN} {epoch} could not be read as a serving "
            f"epoch: {detail}"
        ) from exc


# -- The store ---------------------------------------------------------------------


class EpochCharges:
    """The store that persists the running decision count — feature 294's act.

    Constructed with the database URL the ledger lives in;
    :meth:`charge` bills the serving epoch a decided promotion's row books,
    :meth:`epoch` reads one epoch's ledger row back, and the registry facts
    both of those lean on arrive through feature 293's own read seam, which
    the store composes from the same URL — one database by construction,
    never two the caller has to keep consistent.  The class resolves its
    path lazily, so constructing one performs no I/O: composition-time work
    must not touch the disk, the contract every store in this workspace
    states.

    The store holds no cache of the counts it wrote, for the reason
    :class:`~promotion.decision.PromotionDecisions` states for its rows:
    the ledger row is the only record of what an epoch has served, so it is
    the only thing an answer is drawn from — and the readers asking
    (features 295-297's exhaustion machinery, feature 96's usage
    derivation, an operator watching epochs run out) all run somewhere else
    entirely.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the ledger lives in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one charge: a URL that is
        not a non-empty string names no ledger, and a store that accepted
        one would fail identically on every charge — the wrong place for a
        deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise EpochChargeError(
                f"{EPOCH_CHARGE_ERROR_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL. The running decision count is "
                "persisted as a column of the ledger in the database the "
                "deployment names, and a store pointed at nothing has "
                "nowhere to persist one — an uncharged epoch is the silence "
                "§13 item 4's ledger exists to never have to guess about "
                "(feature 294)"
            )
        self._database_url = database_url.strip()
        # The registry reads this act counts with go through feature 293's
        # own store, wired to the same URL here — one database by
        # construction, and the seam this module's docstring argues for
        # rather than a second SELECT over the registry.
        self._decisions = PromotionDecisions(self._database_url)
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> EpochCharges | None:
        """The charge store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the way every
        store in this workspace treats its configuration.  Absent is not an
        error: it is a deployment without a relational store, and the
        caller that must charge an epoch is the caller that must not find
        itself in it — a decision that went uncounted is an epoch features
        295-297 will read as cleaner than it is.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store records into."""
        return self._database_url

    @property
    def decisions(self) -> PromotionDecisions:
        """The decision store this charge counts through — feature 293's seam."""
        return self._decisions

    @property
    def path(self) -> Path:
        """The SQLite file behind the ledger, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name, in *this*
        feature's vocabulary) the first time an operation needs it.
        """
        if self._path is None:
            try:
                self._path = _sqlite_path(self._database_url)
            except PromotionStoreError as exc:
                raise _translated(exc, "database address") from exc
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the ledger's database, bringing the one table it names up.

        One statement of intent.  :func:`promotion.schema.
        bootstrap_charge_schema` runs the *owning migration's* own
        ``statements("sqlite")`` — ``0110``, the file that declares
        ``epoch_ledger`` — so this store authors no DDL, spells no column
        and cannot drift from the schema's owner.  Every statement is
        ``CREATE TABLE IF NOT EXISTS``, so a fresh database, a fully
        migrated one and one a store in this member created earlier all
        take the same path.

        **One owner and not the registry's.**  This act's two statements
        name ``epoch_ledger`` and nothing else: the ``UPDATE`` writes
        through no child key (``epoch_ledger`` references nothing —
        ``0110`` declares ``REQUIRES_TABLES = ()``), and the count arrives
        through the decision store's seam, whose own bootstrap brings
        ``promotion_registry`` up.  A charge store that ran the registry's
        owner would be creating a table no statement of this act names —
        the habit :mod:`promotion.schema` exists to keep distinguishable
        from a dependency.

        **The foreign keys.**  ``PRAGMA foreign_keys = ON`` — SQLite's own
        default is off, and the pragma is what makes the *registry's*
        references to this table hold against a hand that reaches past
        this store with a raw connection, the reason every store in this
        member sets it.  No parent probe is needed here because no parent
        is written: the row this act charges was checked against its
        parents by the feature that sealed it and the feature that booked
        it.

        The caller owns the connection; use it as a context manager to
        commit, which is what the write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_charge_schema(connection)
        except PromotionError as exc:
            connection.close()
            raise _translated(exc, "database") from exc
        except sqlite3.Error as exc:
            connection.close()
            raise EpochChargeError(
                f"{EPOCH_CHARGE_ERROR_CODE}: the database at {path} could "
                f"not be brought to the revision a charge needs: {exc}. The "
                f"{EPOCH_LEDGER_TABLE} table is created by migrations/"
                "versions/0110_epoch_ledger.py; this store runs that file's "
                "own statements and authors none of its own (feature 294)"
            ) from exc
        return connection

    # -- Feature 294: the charge ---------------------------------------------

    def charge(self, node_id: Any) -> tuple[ServingEpoch, bool]:
        """Persist the running decision count — feature 294's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity — before anything
           is opened, so a malformed charge is refused without touching a
           database and a refused call moves no column.
        2. **Read the node's row** through feature 293's own seam.  An
           absent row is refused by name — there is no booking to bill, and
           the repair is feature 291's act first and feature 293's after
           it.  A row that is still **open** is refused too: its deciding
           evaluation has not been recorded, so the epoch has served no
           decision for it, and billing one would count a promotion that
           has not been decided.  Both are the load in this feature's
           ``depends_on="293"``.
        3. **Count the closed rows** the node's epoch has served, through
           :func:`decisions_served` over feature 293's listing — the
           derivation, not an increment, so the figure is a function of the
           registry and a retried charge recomputes it.
        4. **Re-supply the ledger's column and read it back**, inside the
           same transaction, so the count in the answer is the table's own.
           A standing count already equal to the derivation is the retry:
           the standing row is returned untouched and nothing moves.  A
           derivation *below* the standing count is refused — decided rows
           do not reopen, so a shrinking count is rows that vanished, and
           persisting it would let feature 295's threshold read a spent
           epoch as clean.

        **The answer is the epoch as persisted**: a
        :class:`ServingEpoch` whose ``promotion_decisions_served`` is the
        running count the closed rows state.  The ``bool`` says whether
        *this* call advanced the column; ``False`` is a re-charge answered
        by the standing row — including the charge of a later node whose
        decision an earlier charge already counted — the readable spelling
        of a retry.

        **What this act never does.**  It never judges the promotion, the
        epoch or the threshold: the verdict on the evidence is the deciding
        evaluation's, and retirement is features 295-296's machinery.  It
        never touches ``sealed_at`` or ``retired``: the update's ``SET``
        clause names one column.  And it never takes an ``epoch_id``, a
        ``count`` or a ``clock`` — the epoch is read off the row the
        pre-registration booked, the count is derived from the rows
        feature 293 wrote, and nothing here stamps anything.

        Refuses, in this order, each naming what it is about and all in
        :class:`~promotion.errors.EpochChargeError`: a malformed node, then
        — from the stores — a ``DATABASE_URL`` this member cannot speak, a
        node holding no pre-registration, a node whose row is still open, a
        ledger row the booking names but the table does not hold, a
        derivation that would shrink the standing count, and a row that
        did not move or could not be read back.
        """
        node = _charge_node_id(node_id)
        record = self._decision_of(node)
        if record is None:
            raise _absent_registration(node)
        if record.open:
            raise _undecided_promotion(node, record)
        counted = decisions_served(self._decided_rows(), record.epoch_id)
        with closing(self._connect()) as connection, connection:
            standing = self._epoch_of(connection, record.epoch_id)
            if standing is None:
                raise _absent_epoch(record.epoch_id, node)
            if standing.promotion_decisions_served == counted:
                return standing, False
            if counted < standing.promotion_decisions_served:
                raise _shrinking_count(record.epoch_id, counted, standing)
            try:
                cursor = connection.execute(
                    _UPDATE_SQL, (counted, record.epoch_id)
                )
                try:
                    moved = cursor.rowcount == 1
                finally:
                    cursor.close()
            except sqlite3.Error as exc:
                raise _count_unwritable(record.epoch_id, counted, exc) from exc
            written = self._epoch_of(connection, record.epoch_id)
        if not moved or written is None or (
            written.promotion_decisions_served != counted
        ):
            raise _unreadable_charge(record.epoch_id, counted)
        return written, True

    # -- Feature 294: the read ----------------------------------------------

    def epoch(self, epoch_id: Any) -> ServingEpoch | None:
        """One epoch's ledger row — the count as persisted, and the flag.

        The question every reader of §13 item 4's ledger starts from,
        answered from the row: a record whose
        ``promotion_decisions_served`` is the running count this feature
        persists and whose ``retired`` is the flag feature 296 reads.
        ``None`` itself means the ledger holds no row for the epoch —
        there is no sequestered epoch to ask about, a different fact from
        one that has served zero, which is why the zero row is *returned*
        rather than collapsed into the absence: ``0110``'s default exists
        precisely so that *freshly sealed* and *never sealed* stay two
        answers.

        A blank or non-text name is refused rather than answered ``None``:
        a name that states nothing is a malformed ask, not an unsealed
        epoch, and the two must not collapse into one answer.
        """
        epoch = _charge_epoch_id(epoch_id)
        with closing(self._connect()) as connection:
            return self._epoch_of(connection, epoch)

    # -- The words ----------------------------------------------------------

    def _decision_of(self, node: str) -> PromotionRecord | None:
        """One node's registry row, through feature 293's own read.

        Used rather than restated, so the row this act bills and the row
        feature 293 answered with cannot be two readings of one table —
        the discipline :meth:`~promotion.forward.PromotionWindows.
        _decision_of` states toward the same seam.  A refusal the decision
        store raises (a node holding two rows, a corrupt row, an
        unreachable database) arrives in *its* vocabulary, and it is
        translated here so a caller whose single ``except
        EpochChargeError`` guards the charge is not defeated by a refusal
        phrased for a decision it never asked about.

        ``None`` means the node holds no row at all — a different fact
        from a row that is still open, which is why the two are kept apart
        by the caller rather than collapsed here.
        """
        try:
            return self._decisions.decision(node)
        except EpochChargeError:
            raise
        except PromotionError as exc:
            raise _translated(exc, "registry row") from exc

    def _decided_rows(self) -> tuple[PromotionRecord, ...]:
        """Every decided row, through feature 293's own listing.

        The listing that module's own docstring calls *"the listing an
        auditor reads before charging epochs (feature 294's
        precondition)"* — used rather than restated, so the count this act
        persists and the decisions feature 293 reports cannot be two
        readings of one table.  A refusal from the listing is translated
        for the same reason :meth:`_decision_of` translates the one-row
        read.
        """
        try:
            return self._decisions.decisions()
        except EpochChargeError:
            raise
        except PromotionError as exc:
            raise _translated(exc, "decided rows") from exc

    def _epoch_of(
        self, connection: sqlite3.Connection, epoch: str
    ) -> ServingEpoch | None:
        """One epoch's ledger row, or ``None`` when the table holds none.

        The read :meth:`charge` compares against and :meth:`epoch` answers
        with, spelled once so the two cannot differ.  More than one row
        for the epoch is refused rather than resolved: the key is the
        table's primary key, so the state is unreachable through the
        owner's own DDL and a second row is a hand that reached past this
        member — the same stance :meth:`~promotion.decision.
        PromotionDecisions._registration_of` takes toward a second
        registry row.
        """
        cursor = connection.execute(_EPOCH_READ_SQL, (epoch,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if len(rows) > 1:
            raise EpochChargeError(
                f"{EPOCH_CHARGE_ERROR_CODE}: {EPOCH_LEDGER_TABLE} holds "
                f"{len(rows)} rows for {EPOCH_ID_COLUMN} {epoch}. The "
                "epoch's name is the table's primary key — one row per "
                "sequestered epoch is the law the ledger exists on — and a "
                "second row would split the served count and let feature "
                "295's three-decision threshold read a spent epoch as "
                "clean, the failure 0110's own docstring says the key "
                "exists to prevent (feature 294)"
            )
        if not rows:
            return None
        return _record_from_row(rows[0], epoch)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- The refusals ------------------------------------------------------------------


def _absent_registration(node: str) -> EpochChargeError:
    """The absence refusal: there is no booking for this charge to bill.

    The precondition this feature inherits from ``depends_on="293"`` (and,
    before it, ``291``), phrased as a refusal with its repair in it.  A
    charge bills the sequestered epoch a *decided* promotion's row booked,
    so the row has to exist and be closed before there is anything to
    bill; a node nobody pre-registered holds no booking at all, and
    charging an epoch for it would be counting a promotion that never
    entered §13 item 7's record.
    """
    return EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: {PROMOTION_REGISTRY_TABLE} holds no row "
        f"for {NODE_ID_COLUMN} {node}, so there is no epoch for this charge "
        "to bill. The charge persists the running count of promotion "
        "decisions "
        "against the epoch a decided promotion's pre-registration booked — "
        "feature 291's act books the holdout, feature 293's records the "
        "spend, and this feature counts it — so a node nobody "
        "pre-registered has no booking and no spend. Pre-register the "
        "promotion (feature 291), then record its decision once the "
        "deciding evaluation has run (feature 293), then charge (feature "
        "294)"
    )


def _undecided_promotion(node: str, record: PromotionRecord) -> EpochChargeError:
    """The open-row refusal: a pre-registration has served no decision yet.

    The case that makes ``depends_on="293"`` a gate rather than a
    formality.  ``decided_at`` is ``NULL`` exactly while the deciding
    evaluation has not been recorded — ``0108``'s own schema comment says
    the column is nullable because the row is written while the decision
    is still open — and §13 item 4 counts *promotion decisions*, which are
    the closed rows, in ``0110``'s own words.  Billing the epoch anyway
    would inflate the spend the ledger budgets: the epoch would reach
    feature 295's three-decision threshold on promotions that were never
    decided, which is the opposite failure from the reuse the ledger
    exists to prevent and the harder one to see, because a ledger that
    over-counts looks cautious.
    """
    return EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: the registry holds an **open** row for "
        f"{NODE_ID_COLUMN} {node} — pre-registered at "
        f"{record.pre_registered_at.isoformat()} under criteria "
        f"{record.criteria_hash} against {EPOCH_ID_COLUMN} "
        f"{record.epoch_id}, with no deciding stamp — so this epoch has "
        "served no decision for it yet. §13 item 4 budgets sequestered "
        "epochs by *promotion decisions*, which are the closed rows "
        "feature 293's stamp completes, and a charge that counted an open "
        "pre-registration would retire clean epochs early on promotions "
        "that were never decided. Record the decision once the deciding "
        "evaluation has run (feature 293), then charge (feature 294)"
    )


def _absent_epoch(epoch: str, node: str) -> EpochChargeError:
    """The missing-ledger-row refusal: the booking names a row the table lacks.

    Unreachable through this member's writers — feature 291 probes the
    ledger for the epoch *before* the insert, every connection this member
    opens enforces the foreign key, and nothing here deletes ledger rows —
    so a decided registry row whose ledger row is gone is a write that
    bypassed them all.  Refused rather than repaired, because the repair
    this act could offer is the one it must never make: recreating the
    parent would mean minting a ``sealed_at``, and the sequestration
    instant is the sealing process's fact, not a figure the charging write
    is free to invent.  The repair is to the database.
    """
    return EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: {EPOCH_LEDGER_TABLE} holds no row for "
        f"{EPOCH_ID_COLUMN} {epoch}, which {NODE_ID_COLUMN} {node}'s decided "
        "row books. The pre-registration probes the ledger before it writes "
        "and every connection this member opens enforces the foreign key, so "
        "a booking whose ledger row is gone is a write that reached past "
        "them — and the one repair this store must not offer is recreating "
        "the row, because ``sealed_at`` is the sealing process's fact and a "
        "charge that minted one would fabricate the moment of sequestration. "
        "The repair is to the database: restore the ledger row the sealing "
        "process wrote (feature 294)"
    )


def _shrinking_count(
    epoch: str, counted: int, standing: ServingEpoch
) -> EpochChargeError:
    """The shrinking-count refusal: rows vanished, and the count will not follow.

    The derivation is monotone by construction — a decided row never
    reopens, because feature 293's own ``UPDATE`` carries ``AND decided_at
    IS NULL`` and nothing in this member writes the column back — so a
    count *below* the standing figure can only mean closed rows were
    deleted past the member.  Persisting it would author exactly the state
    ``0110``'s docstring dreads: a served count split lower than the
    epoch's history, letting feature 295's three-decision threshold read
    an epoch that had already served its budget as clean.  **This is not
    this store judging the promotion** — the distinction
    :mod:`promotion.decision` makes for its ordering refusal: nothing
    here reads evidence or decides anything; it declines to persist a
    figure that contradicts the rows it is a function of.  The repair is
    to the database.
    """
    return EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: the closed registry rows hold "
        f"{counted} promotion decision{'s' if counted != 1 else ''} against "
        f"{EPOCH_ID_COLUMN} {epoch}, whose {EPOCH_LEDGER_TABLE} row already "
        f"records {standing.promotion_decisions_served}. A decided row "
        "never reopens — feature 293's own update carries "
        "``AND decided_at IS NULL`` — so a derivation below the standing "
        "count means rows were deleted past this member, and persisting it "
        "would let feature 295's three-decision threshold read an epoch "
        "that had already served its budget as clean, the failure 0110's "
        "own docstring says the ledger exists to prevent. This store does "
        "not judge the promotion; it declines to persist a figure that "
        "contradicts the rows it is a function of. The repair is to the "
        "database (feature 294)"
    )


def _count_unwritable(
    epoch: str, counted: int, exc: sqlite3.Error
) -> EpochChargeError:
    """The write refusal: the ledger's column could not be re-supplied."""
    return EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: the running decision count for "
        f"{EPOCH_ID_COLUMN} {epoch} could not be persisted as {counted}: "
        f"{exc}. The update names one column on one row this store read as "
        f"standing — so a failure here is a database that could not take "
        f"the write, and an epoch whose count did not land is an epoch "
        f"features 295-297 will read as cleaner than it is (feature 294)"
    )


def _unreadable_charge(epoch: str, counted: int) -> EpochChargeError:
    """The read-back refusal: a count this store cannot vouch for."""
    return EpochChargeError(
        f"{EPOCH_CHARGE_ERROR_CODE}: the running decision count for "
        f"{EPOCH_ID_COLUMN} {epoch} could not be read back as {counted} "
        f"after the write. A charge has to be accounted for — §13 item 4 "
        f"budgets sequestered epochs by exactly this column, and a count "
        f"the table does not confirm is a figure this store cannot vouch "
        f"for (feature 294)"
    )


# -- The module-level spellings -----------------------------------------------------


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spellings act on, or a refusal naming the gap.

    The same seam :func:`promotion.decision._resolved_url` and
    :func:`promotion.forward._resolved_decisions` resolve, restated in
    this feature's vocabulary: an explicit URL wins, else
    ``DATABASE_URL``, and a deployment that names neither is refused *by
    name* rather than silently doing nothing.  The silence is the
    dangerous failure here and not the refusal: a count that quietly went
    unpersisted leaves the epoch reading cleaner than it is, which is the
    state §13 item 4's ledger exists to make impossible.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise EpochChargeError(
            f"{EPOCH_CHARGE_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so there is nowhere to persist the running "
            "decision count. §13 item 4 tracks every promotion decision a "
            "sequestered epoch serves, and features 295-297 budget the "
            "system's continuation on this column — a store resolved from "
            "nothing is a refusal rather than a silent no-op (feature 294)"
        )
    return url


def charge_epoch(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[ServingEpoch, bool]:
    """Persist the running decision count — the module-level spelling of 294's act.

    The feature's sentence as one call, for the caller that wants the act
    without holding a store — the epoch-governance path's line after
    feature 293's stamp has landed.  The store is resolved from
    ``database_url``, else from ``DATABASE_URL``, exactly as
    :func:`promotion.decision.record_decision` and
    :func:`promotion.blocking.record_block` resolve theirs.

    An :class:`~promotion.errors.EpochChargeError` from the store or the
    resolution propagates unwrapped: the refusal already names the node
    and the fact, and re-wrapping it here would put a second message in
    front of the one an operator needs.
    """
    url = _resolved_url(database_url, env)
    return EpochCharges(url).charge(node_id)


def epoch_charge(
    epoch_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ServingEpoch | None:
    """Read one epoch's ledger row back — the module-level spelling of the read.

    For the caller that holds a URL rather than a store: feature 297's
    depleting count asking what remains, an operator watching an epoch
    approach §13 item 4's budget, a report.  Resolved the same way
    :func:`charge_epoch` resolves its store, so the caller that charges
    through one spelling and reads through the other is reading the row it
    advanced.

    ``None`` means the ledger holds no row for the epoch — no sequestered
    epoch, a different fact from one that has served zero.
    """
    url = _resolved_url(database_url, env)
    return EpochCharges(url).epoch(epoch_id)
