"""The promotion path consults the tripwires — bug_spec_tripwire_false_positives.xml, bug 2.

bug_spec_tripwire_false_positives.xml's first bug made step 10's leakage
probes advisory: a rejection is persisted, one row per probe, in
``tripwire_verdict`` (:mod:`orchestrator._evaluate`), and no longer fails the
node.  Its own docstring states the trade this member is the other half of:
*"Tripwire rejections are therefore recorded as advisory at discovery time
and gate promotion, where a false positive costs one review, not a
branch."*  Before this module, nothing read that table from the promotion
side, so a node step 10 flagged could be pre-registered and decided exactly
like a clean one — the protection that moved off discovery never arrived at
promotion.  This module is that arrival: :func:`rejects_tripwire_flagged` is
the gate, and :mod:`promotion.decision` calls it before closing a
pre-registration's row.

**The table name is restated, not imported.**  ``tripwire_verdict`` and its
five columns are :mod:`orchestrator._evaluate`'s own spelling
(:data:`orchestrator._evaluate.TRIPWIRE_VERDICT_TABLE`); this module names
the identical string rather than importing it, because no member in this
workspace imports another, and the promotion plugin least of all may import
the orchestrator that runs agent-authored code.  A rename on that side is
this module's to notice by test, the way every restated spelling in this
member is pinned.

**A database with no such table is a deployment this gate does not
apply to, and that is a design choice, not an oversight.**  A database
where ``tripwire_verdict`` does not exist at all means no evaluation ever
ran step 10's sweep against it — most of this member's own test suite
builds exactly such a database, to test the registry and the decision in
isolation from the evaluation pipeline, as every other merit gate in this
member (:mod:`promotion.blocking`, :mod:`promotion.calibration`) already
does for its own table.  Refusing every decision in that database would
make the registry and the decision untestable without the orchestrator
on the path, and would hard-couple this member's schema to one it does
not own.  So the gate reads the table defensively: ``no such table`` is
treated as *not applicable* and never refused, while a table that *does*
exist and holds no row **for this node** is refused by name — the
distinction the bug asks for is about a node nobody probed, not about a
deployment nobody wired the sweep into.

**The override is a second table, and persisting it is the point.**  An
operator who promotes past a flag or an unprobed node must leave a record
of having done so, or the review step 10's advisory rejection bought is
undone by the one act that matters most — :func:`record_tripwire_override`
writes the reason and the probe list into ``promotion_tripwire_override``,
a table this module owns (no migration declares it, the same argument
:mod:`promotion.blocking` makes for ``promotion_block``) and creates
idempotently on first use.

**Stdlib only, and no cross-member import.**  ``sqlite3``, ``datetime`` and
this member's own :mod:`promotion.errors` and :mod:`promotion.pre_register`
— never ``tripwires`` or ``orchestrator``.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from .errors import PromotionError, PromotionStoreError
from .pre_register import (
    NODE_ID_COLUMN,
    _sqlite_path,
    _validated_uuid,
    utc_now,
)

__all__ = [
    "MIN_ACKNOWLEDGEMENT_LENGTH",
    "PROMOTION_TRIPWIRE_OVERRIDE_TABLE",
    "TRIPWIRE_FLAGGED_ERROR_CODE",
    "TRIPWIRE_OVERRIDE_ERROR_CODE",
    "TRIPWIRE_UNMEASURED_ERROR_CODE",
    "TRIPWIRE_VERDICT_TABLE",
    "TripwireFlaggedError",
    "record_tripwire_override",
    "rejects_tripwire_flagged",
]

#: :data:`orchestrator._evaluate.TRIPWIRE_VERDICT_TABLE`, restated — see the
#: module docstring for why this is a restatement and not an import.
TRIPWIRE_VERDICT_TABLE = "tripwire_verdict"

#: This feature's own table, holding one row per node an operator has
#: deliberately promoted past a flag or an absent probe.  Not declared by
#: any migration and therefore this feature's to declare, the same argument
#: :mod:`promotion.blocking` makes for ``promotion_block``.
PROMOTION_TRIPWIRE_OVERRIDE_TABLE = "promotion_tripwire_override"

_REASON_COLUMN = "reason"
_PROBES_COLUMN = "probes"
_RECORDED_AT_COLUMN = "recorded_at"

#: The shortest ``acknowledge_tripwires`` reason this gate accepts.  A
#: promotion past a flag or an unprobed node must never be silent, and a
#: reason too short to say anything is not an acknowledgement an auditor
#: could read back.
MIN_ACKNOWLEDGEMENT_LENGTH = 20

#: The greppable word opening a refusal naming rejected probes.
TRIPWIRE_FLAGGED_ERROR_CODE = "tripwire_flagged"

#: The greppable word opening a refusal of a node this gate cannot vouch
#: for as clean: no ``tripwire_verdict`` rows at all, or every row recorded
#: ``measured = 0``.
TRIPWIRE_UNMEASURED_ERROR_CODE = "tripwire_unmeasured"

#: The greppable word opening a refusal of a malformed
#: ``acknowledge_tripwires`` reason.
TRIPWIRE_OVERRIDE_ERROR_CODE = "tripwire_override_invalid"

_SELECT_VERDICT_SQL = (
    f"SELECT probe, rejected, figure, measured FROM {TRIPWIRE_VERDICT_TABLE} "
    f"WHERE {NODE_ID_COLUMN} = ? ORDER BY probe"
)

_CREATE_OVERRIDE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {PROMOTION_TRIPWIRE_OVERRIDE_TABLE} (
    {NODE_ID_COLUMN}      TEXT NOT NULL PRIMARY KEY,
    {_REASON_COLUMN}      TEXT NOT NULL,
    {_PROBES_COLUMN}      TEXT NOT NULL,
    {_RECORDED_AT_COLUMN} TEXT NOT NULL
)
"""

_UPSERT_OVERRIDE_SQL = (
    f"INSERT INTO {PROMOTION_TRIPWIRE_OVERRIDE_TABLE} "
    f"({NODE_ID_COLUMN}, {_REASON_COLUMN}, {_PROBES_COLUMN}, {_RECORDED_AT_COLUMN}) "
    "VALUES (?, ?, ?, ?) "
    f"ON CONFLICT ({NODE_ID_COLUMN}) DO UPDATE SET "
    f"{_REASON_COLUMN} = excluded.{_REASON_COLUMN}, "
    f"{_PROBES_COLUMN} = excluded.{_PROBES_COLUMN}, "
    f"{_RECORDED_AT_COLUMN} = excluded.{_RECORDED_AT_COLUMN}"
)


class TripwireFlaggedError(PromotionError):
    """A promotion could not be vouched for clean of step 10's tripwires.

    Raised by :func:`rejects_tripwire_flagged` in three faces, each naming
    what it is about:

    * **the flag** (:data:`TRIPWIRE_FLAGGED_ERROR_CODE`) — the node holds at
      least one ``tripwire_verdict`` row with ``measured = 1`` and
      ``rejected = 1``.  The message names every rejected probe and its
      figure.  The repair is review, or an explicit
      ``acknowledge_tripwires`` reason.
    * **the absence** (:data:`TRIPWIRE_UNMEASURED_ERROR_CODE`) — the node
      holds no ``tripwire_verdict`` rows at all, or every row it holds is
      ``measured = 0``.  A node nobody probed cannot be promoted as clean
      any more than one probed and flagged can.  The repair is to evaluate
      the node, or to override.
    * **the override's own ask** (:data:`TRIPWIRE_OVERRIDE_ERROR_CODE`) —
      an ``acknowledge_tripwires`` reason shorter than
      :data:`MIN_ACKNOWLEDGEMENT_LENGTH`.  Nothing was read and nothing was
      written; the repair is to re-send a reason an auditor could read back.

    Gathered in one class rather than split, for the reason every merit gate
    in this member gathers its faces: the caller is :mod:`promotion.decision`'s
    gate, and a gate's one failure mode is silence — a caller whose single
    ``except TripwireFlaggedError`` guards the promotion path must not be
    able to walk through a hole because a flagged node arrived in a
    different class from an unprobed one.
    """


@dataclass(frozen=True, slots=True)
class _TripwireReading:
    """What :data:`TRIPWIRE_VERDICT_TABLE` says about one node — the one read
    both :func:`rejects_tripwire_flagged` and the override path act on.

    ``applicable`` is ``False`` exactly when the table does not exist in
    this database at all (see the module docstring); every other field is
    meaningless in that case and left at its empty default.  ``has_rows``
    and ``any_measured`` are kept apart because a node can hold rows that
    are all ``measured = 0`` — probed for, but unable to measure — which is
    the same "not vouched for clean" finding as holding no rows, stated by
    the bug as one case ("A node whose every probe is unmeasured is refused
    as tripwire_unmeasured").
    """

    applicable: bool = False
    has_rows: bool = False
    any_measured: bool = False
    rejected: tuple[tuple[str, float | None], ...] = ()


# -- Validation ---------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> TripwireFlaggedError:
    """Re-raise a sibling's refusal in this gate's vocabulary.

    The seam every gate in this member states: feature 291's validators
    raise ``PromotionError``/``PromotionStoreError``, and a caller whose
    single ``except TripwireFlaggedError`` guards the promotion path must
    not be defeated by a refusal phrased for the pre-registration store.
    """
    return TripwireFlaggedError(
        f"{TRIPWIRE_FLAGGED_ERROR_CODE}: the {what} could not be reached to "
        f"consult the tripwire gate: {exc}"
    )


def _gate_node_id(value: Any) -> str:
    """Return ``value`` as a node identity, or refuse it in this gate's vocabulary."""
    try:
        return _validated_uuid(value, NODE_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "node identity") from exc


def _validated_reason(value: Any) -> str:
    """Return ``value`` as an acknowledgement reason, or refuse what is too short."""
    if not isinstance(value, str) or len(value.strip()) < MIN_ACKNOWLEDGEMENT_LENGTH:
        raise TripwireFlaggedError(
            f"{TRIPWIRE_OVERRIDE_ERROR_CODE}: acknowledge_tripwires must be "
            f"at least {MIN_ACKNOWLEDGEMENT_LENGTH} characters of reason text "
            f"— got {value!r}. A promotion past a flagged or unprobed node is "
            "never silent, and a reason too short to say anything is not an "
            "acknowledgement an auditor could read back (bug 2)"
        )
    return value.strip()


def _connect(database_url: str) -> sqlite3.Connection:
    """Open ``database_url``'s sqlite file — no bootstrap, no table of its own.

    This gate reads a table it does not own (see the module docstring) and
    writes one it does; neither act needs the pre-registration's three
    tables, so this connection brings none of them up.
    """
    try:
        path = _sqlite_path(database_url)
    except PromotionStoreError as exc:
        raise _translated(exc, "database address") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


# -- The read -------------------------------------------------------------------------


def _verdict_rows(
    node: str, *, database_url: str
) -> tuple[bool, list[tuple[str, int, float | None, int]]]:
    """``(applicable, rows)`` for ``node`` — ``applicable`` is ``False`` iff
    :data:`TRIPWIRE_VERDICT_TABLE` does not exist in this database at all.
    """
    with closing(_connect(database_url)) as connection:
        try:
            cursor = connection.execute(_SELECT_VERDICT_SQL, (node,))
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return False, []
            raise TripwireFlaggedError(
                f"{TRIPWIRE_FLAGGED_ERROR_CODE}: {TRIPWIRE_VERDICT_TABLE} could "
                f"not be read for node {node}: {exc}"
            ) from exc
        try:
            return True, cursor.fetchall()
        finally:
            cursor.close()


def _read_tripwire_reading(node: str, *, database_url: str) -> _TripwireReading:
    """One node's :class:`_TripwireReading` — the single read the gate and
    the override path both act on, so they cannot disagree about what the
    table says.
    """
    applicable, rows = _verdict_rows(node, database_url=database_url)
    if not applicable:
        return _TripwireReading(applicable=False)
    if not rows:
        return _TripwireReading(applicable=True, has_rows=False)
    measured_rows = [row for row in rows if row[3]]
    rejected = tuple((row[0], row[2]) for row in measured_rows if row[1])
    return _TripwireReading(
        applicable=True,
        has_rows=True,
        any_measured=bool(measured_rows),
        rejected=rejected,
    )


def _named_rejections(rejected: tuple[tuple[str, float | None], ...]) -> str:
    return ", ".join(f"{probe}={figure!r}" for probe, figure in rejected)


# -- The gate ---------------------------------------------------------------------


def rejects_tripwire_flagged(node_id: Any, *, database_url: str) -> None:
    """Refuse a promotion step 10's tripwires flagged, or never probed — bug 2's gate.

    Reads :data:`TRIPWIRE_VERDICT_TABLE` for ``node_id`` and raises
    :class:`TripwireFlaggedError` when any probe rejected (``measured = 1``
    and ``rejected = 1``), or when the node cannot be vouched for clean at
    all — no rows, or every row ``measured = 0``.  A probe recorded
    ``measured = 0`` is never counted as a rejection, even if its own
    ``rejected`` column happens to carry a stray ``1``: an unmeasured probe
    measured nothing, so it cannot be the reason a node is flagged.

    A database holding no :data:`TRIPWIRE_VERDICT_TABLE` at all never
    refuses — see the module docstring for why that is a deliberate
    "not applicable" rather than "not probed".

    Writes nothing, and reads this one table only: never ``promotion_registry``,
    a pool, a score or a campaign status.  :mod:`promotion.decision` is the
    caller that holds those other facts and checks them itself.
    """
    node = _gate_node_id(node_id)
    reading = _read_tripwire_reading(node, database_url=database_url)
    if not reading.applicable:
        return
    if not reading.has_rows or not reading.any_measured:
        raise TripwireFlaggedError(
            f"{TRIPWIRE_UNMEASURED_ERROR_CODE}: node {node} holds "
            f"{'no' if not reading.has_rows else 'only unmeasured'} "
            f"{TRIPWIRE_VERDICT_TABLE} rows — it was never probed by step "
            "10's tripwire sweep, and a node that was never probed cannot "
            "be promoted as clean. Evaluate the node so the sweep records "
            "its verdicts, or override with record_decision(..., "
            "acknowledge_tripwires=<reason, at least "
            f"{MIN_ACKNOWLEDGEMENT_LENGTH} characters>) if this promotion "
            "should proceed anyway (bug_spec_tripwire_false_positives.xml, "
            "bug 2)"
        )
    if reading.rejected:
        raise TripwireFlaggedError(
            f"{TRIPWIRE_FLAGGED_ERROR_CODE}: node {node} was flagged by step "
            f"10's tripwires: {_named_rejections(reading.rejected)}. A "
            "rejection is advisory at discovery time and reviewed at "
            "promotion rather than a node failure (bug_spec_tripwire_false_"
            "positives.xml, bug 1) — review the node before promoting it, "
            "or override with record_decision(..., acknowledge_tripwires="
            f"<reason, at least {MIN_ACKNOWLEDGEMENT_LENGTH} characters>) "
            "to record a deliberate promotion past the flag (bug 2)"
        )


# -- The override -------------------------------------------------------------------


def record_tripwire_override(
    node_id: Any,
    *,
    reason: Any,
    probes: tuple[str, ...] = (),
    database_url: str,
    recorded_at: dt.datetime | None = None,
    clock: Callable[[], dt.datetime] | None = None,
) -> None:
    """Persist an operator's deliberate promotion past a tripwire flag.

    Writes one row into :data:`PROMOTION_TRIPWIRE_OVERRIDE_TABLE` — the
    node, the reason, the comma-joined ``probes`` the override is about, and
    when it was recorded — creating the table idempotently on first use (no
    migration declares it; see the module docstring).  A second override for
    a node already holding one re-states the row rather than refusing: an
    operator who overrides again is updating the record of why, not
    contesting an earlier one.

    ``reason`` must be at least :data:`MIN_ACKNOWLEDGEMENT_LENGTH` characters
    once stripped, refused as :class:`TripwireFlaggedError` otherwise, before
    anything is opened — so a malformed override writes nothing.

    This is the one write :mod:`promotion.decision` makes on an operator's
    behalf when ``acknowledge_tripwires`` is supplied; it does not itself
    decide whether a promotion *should* proceed past a flag — that is the
    operator's reason, taken at face value and persisted so the decision it
    accompanies is never silent.
    """
    node = _gate_node_id(node_id)
    text = _validated_reason(reason)
    stamped = recorded_at or (clock or utc_now)()
    try:
        with closing(_connect(database_url)) as connection, connection:
            connection.execute(_CREATE_OVERRIDE_TABLE_SQL)
            connection.execute(
                _UPSERT_OVERRIDE_SQL,
                (node, text, ",".join(probes), stamped.isoformat()),
            )
    except sqlite3.Error as exc:
        raise TripwireFlaggedError(
            f"{TRIPWIRE_FLAGGED_ERROR_CODE}: the tripwire override for node "
            f"{node} could not be recorded: {exc}"
        ) from exc
