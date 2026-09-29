"""Persisting each promotion decision — feature 293, the row's second stamp.

app_spec.xml, "Promotion & Epoch Governance", feature 293: *System persists
each promotion decision into the promotion_registry with its timestamp and
criteria hash.*  Its declared parent is feature 291 — the pre-registration —
and the act is the second half of a shape the schema has carried since
``0108`` wrote it: ``promotion_registry`` holds two timestamps, and its own
comment says which feature writes each — *"``criteria_hash`` and
``pre_registered_at`` are written before the deciding evaluation, and
``decided_at`` after."*  Feature 291 opened the row with the first stamp; this
module closes it with the second.  Nothing else in the table moves.

**A promotion decision, as the schema spells it, is the row acquiring
``decided_at``.**  The table has no outcome column and this feature adds none
— the same argument :mod:`promotion.blocking` made for its own table, with the
opposite answer because the question is the other way round: there, the spec's
schema block declares the registry's six columns and no seventh, so a block's
figures needed a table of their own; here the sentence's every noun is
already a column.  *"Each promotion decision"* is one row's closing event;
*"its timestamp"* is ``decided_at``; *"criteria hash"* is the ``CHAR(64)``
column feature 291 wrote.  The decision is persisted **with** its criteria
hash in the strict sense that the row, read back, is the whole record: an
auditor — feature 360's CI invariant, an operator, §13 item 4's epoch
governance — reads the two stamps and the one hash off the row and holds the
decision as a fact.  ``0110``'s own docstring says what counts as the event:
*"the things counted against them are promotion decisions — events recorded
in ``promotion_registry``."*

**The update names one column, and that is the mirror of feature 291's law.**
:data:`_INSERT_SQL` in :mod:`promotion.pre_register` cannot name ``decided_at``
— four columns, the nullable one absent, so a pre-registration is born open by
the *shape* of the statement rather than by a check the writer remembers to
make.  :data:`_UPDATE_SQL` here is the same law from the other side: its
``SET`` clause names ``decided_at`` and nothing else, so the criteria hash,
the epoch, the node and the first stamp are values this statement *cannot
touch*, and the two-timestamp record cannot be edited into a different
promotion by the one act that closes it.  Each half of §13 item 7's ordering
is enforced by the other feature's statement having no clause for it.

**``criteria_hash`` is not an argument, and the refusal to take one is the
feature's boundary.**  A caller offering "the hash to persist" is offering one
of two things.  If the offer is the hash the evaluation *judged against*, then
comparing it to the row's is feature 292's verdict — *"rejects a promotion
whose recorded criteria hash differs from the pre-registered value"* — and
this module does not pronounce it; nothing here spells ``criteria_mismatch``.
If the offer is meant to be *written*, it is a forgery: the recorded hash is
the thing the deciding evaluation is checked against, and a writer that could
move it after the evaluation ran would be exactly the post-hoc edit §13 item 7
exists to make impossible.  So the act takes a node and an instant, and the
hash it answers with is the row's own — read back through the same validator
that checked it on the way in.

**A row is closed once, and the store answers a re-decision with the standing
row.**  The pre-registration is one row per node; the decision is that row's
closing, so there is one of those too.  A second :meth:`record_decision` for a
node the table already holds closed returns the standing row **byte for
byte**, ``decided_at`` included, and writes nothing — the stance a retried
pre-registration takes toward ``pre_registered_at`` and a re-block toward
``blocked_at``: the decided instant is *when the promotion was decided*, and a
caller that walked the path again did not move it.  The once-only close is
also in the *engine*, not only in this flow: :data:`_UPDATE_SQL` carries
``AND decided_at IS NULL``, so a raw second writer — another process racing
this one — matches no row and moves no stamp, which is the ``ON CONFLICT DO
NOTHING`` discipline :mod:`promotion.blocking` states, spelled for a table
whose key was written by another feature.

**The two stamps must not contradict §13 item 7, and the store refuses a pair
that does.**  A decision stamped *before* the criteria were fixed would write
a row whose own two columns state that the promotion was decided before its
criteria existed — the stored row that lies, which is worse than no row at
all, and precisely the finding feature 360's CI invariant refuses a merge
over (*"System rejects the merge when promotion criteria are recorded after
the deciding evaluation"*).  The boundary is 360's own: this store refuses
``decided_at < pre_registered_at`` and honours equality, because the row
holds the instant the decision was *recorded* and not the span the evaluation
ran over — a stamp equal to the criteria's is neither *before* them nor a
finding 360 names, and the table has no column that could distinguish the
sequence.  **This is not this store
judging the promotion** — the move :mod:`promotion.blocking` makes when it
refuses figures that contradict the finding they are persisted as.  Nothing
here reads a pool, a score, a coverage ledger or a campaign status, and
nothing here decides whether the promotion *stands*; it declines to persist
two columns that disagree with the law both exist to serve.  The repair is to
the call: record the decision at or after the instant the criteria were fixed
at, which for a genuine promotion is the instant the evaluation actually ran.

**The epoch is not an argument either, and the omission is forward-looking.**
The sequestered holdout was *booked* by the pre-registration — ``epoch_id`` is
on the row, named once, before the evaluation — and the decision spends that
booking rather than re-naming it.  Feature 294 (*"persists the running
promotion decision count against the serving epoch in the epoch_ledger"*) is
the act that charges the epoch, and it reads the closed rows this module
writes; a decision that took an ``epoch_id`` would let a caller spend a
different holdout than the one booked, which is the reuse §13 item 4 retires
epochs to prevent.

**The absent registration is refused by name, and that is the load in
``depends_on="291"``.**  §13 item 7 fixes the criteria *before* the
evaluation, so the row this act closes has to exist first.  A decision
recorded against a node nobody pre-registered would be a verdict with no
criteria to be checked against — the row §13 item 7 exists to make impossible
— and the repair is specific: pre-register first, then decide.  Refused by
probe rather than left to the engine because there is no constraint to leave
it to (the row's absence *is* the failure) and because SQLite's errors would
name neither the node nor the repair.

**The one-table bootstrap, and why this act's set is smaller than the
insert's.**  :mod:`promotion.schema` states the rule — *the set is the tables
this act's own statements name* — and this act's two statements (the read and
the update) name ``promotion_registry`` and nothing else.  The pre-registration
needs three tables because its ``INSERT`` resolves foreign-key parents at
write time; this act never writes a row through the child keys, and SQLite
does not resolve a parent for an ``UPDATE`` of a non-key column — verified
against SQLite 3.45.1, the workspace's own, on a database holding the registry
and neither parent.  So :data:`~promotion.schema.DECISION_MIGRATION_ORDER` is
one owner, ``0108``, whose whole statement tuple runs (six tables, the
``forward_record`` neighbourhood among them) because a revision contributes
all of its statements or none — the discipline :func:`promotion.schema.
_statements_for` states.  A decision store that ran the three-table set would
be creating ``node`` and ``epoch_ledger`` for statements that name neither: a
habit, not a dependency, and the exact over-creation :mod:`promotion.schema`
was written to keep readable.

**No component, no seat, no router, no second builder.**  The member's
registered surface stays feature 291's one store, for the reason the member's
own docstring states: a decision is evidence the factory does not hold — the
evaluation has run, somewhere else, and its outcome is the caller's to bring —
so the store is constructed from a URL by the caller that has one, exactly as
its two siblings are.  The composed ``promotion`` component is untouched
and still answers one question.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime`` and
``contextlib`` at module scope and nothing else: no third-party import and no
import of another workspace member, so the factory's scan imports this package
for the near-nothing it always did and a decision costs its caller only the
connection it already had.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from .errors import (
    PROMOTION_DECISION_ERROR_CODE,
    PromotionDecisionError,
    PromotionError,
    PromotionStoreError,
)
from .pre_register import (
    _READ_SQL,
    CRITERIA_HASH_COLUMN,
    DATABASE_URL_ENV,
    DECIDED_AT_COLUMN,
    EPOCH_ID_COLUMN,
    NODE_ID_COLUMN,
    PRE_REGISTERED_AT_COLUMN,
    PromotionRecord,
    _record_from_row,
    _sqlite_path,
    _validated_instant,
    _validated_uuid,
    utc_now,
)
from .schema import (
    PROMOTION_REGISTRY_TABLE,
    bootstrap_decision_schema,
)

__all__ = [
    "PromotionDecisions",
    "promotion_decision",
    "record_decision",
]

#: The write — one column in the ``SET`` clause, and that is the whole of the
#: boundary this module states for it.  The ``WHERE`` carries the key *and*
#: the openness it closes (``decided_at IS NULL``), so a second writer —
#: another process, a raw connection — matches no row and moves no stamp:
#: the once-only close is a property of the statement, not of the flow that
#: happens to read first.
_UPDATE_SQL = (
    f"UPDATE {PROMOTION_REGISTRY_TABLE} SET {DECIDED_AT_COLUMN} = ? "
    f"WHERE {NODE_ID_COLUMN} = ? AND {DECIDED_AT_COLUMN} IS NULL"
)

#: Every decided row, in the table's key order — the audit listing.  The
#: column list is :data:`~promotion.pre_register._READ_SQL`'s own order,
#: because :func:`~promotion.pre_register._record_from_row` unpacks by
#: position and a listing that shifted a field would build records out of
#: another row's columns.  ``decided_at IS NOT NULL`` is the feature's noun
#: as a predicate: a decided row *is* a persisted decision.
_LIST_DECIDED_SQL = (
    f"SELECT id, {NODE_ID_COLUMN}, {EPOCH_ID_COLUMN}, {CRITERIA_HASH_COLUMN}, "
    f"{PRE_REGISTERED_AT_COLUMN}, {DECIDED_AT_COLUMN} "
    f"FROM {PROMOTION_REGISTRY_TABLE} "
    f"WHERE {DECIDED_AT_COLUMN} IS NOT NULL "
    f"ORDER BY {NODE_ID_COLUMN}"
)


# -- Validation --------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> PromotionDecisionError:
    """Re-raise a sibling's refusal in this feature's vocabulary.

    The seam rule this workspace states at every member boundary, applied
    *inside* one member — the shape :func:`promotion.blocking._translated` and
    :func:`promotion.calibration._translated` take toward the same validators.
    Feature 291's calendar of refusals raises ``PromotionError`` for a
    malformed identity and ``PromotionStoreError`` for a path it cannot speak,
    and a caller whose single ``except PromotionDecisionError`` guards its
    promotion path must not be defeated by a refusal phrased for a
    pre-registration: it would read *the body was malformed* where the truth
    is *this decision was not recorded* — and would go on to leave a decided
    promotion unrecorded, the silence this feature exists to prevent.  The
    inner message is carried through, so nothing an operator needs is lost;
    only re-framed, with the frame naming which act was being performed.

    ``type(exc)(...)`` is deliberately **not** used: here the class itself is
    the thing being corrected, exactly as in the two siblings.
    """
    return PromotionDecisionError(
        f"{PROMOTION_DECISION_ERROR_CODE}: the {what} could not be reached to "
        f"record this decision: {exc}"
    )


def _decision_node_id(value: Any) -> str:
    """Return ``value`` as a node identity, or refuse it in *this* vocabulary.

    Feature 291's identity validator is the one spelling this member has for
    *an id that joins the tree*, and the decision's row is keyed by exactly
    that value — so the rule is *used* rather than restated, the move both
    siblings make.  What it raises is ``PromotionError``, the member's ask
    face, and that is what the wrapper is for: the refusal has to arrive as a
    *decision* refusal, or a caller's single
    ``except PromotionDecisionError`` walks through it and the promotion
    stands decided and unrecorded.
    """
    try:
        return _validated_uuid(value, NODE_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "node identity") from exc


def _decision_instant(value: Any) -> dt.datetime:
    """Return ``value`` as an aware-UTC instant, or refuse it in this vocabulary.

    The same seam over feature 291's stamp validator: the *rule* (aware,
    normalised to UTC, ISO-8601 text accepted so a row read back revalidates)
    is the member's one spelling and is used rather than restated; the *class*
    is translated, so a naive stamp handed to this store is refused as a
    decision that could not be recorded rather than as a pre-registration
    that could not be written.
    """
    try:
        return _validated_instant(value, DECIDED_AT_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "deciding instant") from exc


def _validated_after_pre_registration(
    node: str, decided: dt.datetime, pre_registered: dt.datetime
) -> None:
    """Refuse a decision that would precede the criteria it was judged against.

    §13 item 7's law is an inequality between this act's stamp and feature
    291's: *"Promotion criteria are pre-registered and hashed **before** the
    evaluation that decides them."*  Both instants are in hand here for the
    first time — at pre-registration the decision had not happened, so there
    was nothing to compare — and a pair with ``decided_at`` strictly earlier
    would write a row whose own two columns state that the promotion was
    decided before its criteria were fixed.  That is the finding feature
    360's CI invariant refuses a merge over, arrived at from the write side
    instead of the audit side, and this store declines to author it.

    **This is not this store judging the promotion**, and the distinction is
    worth being precise about because the two look alike from outside.  The
    store never reads the evaluation's evidence, never scores anything and
    never decides whether the promotion stands; it checks only that the two
    columns it is about to leave behind do not contradict the law both exist
    to serve — the move :mod:`promotion.blocking` makes when it refuses
    figures that contradict the finding they are persisted as.

    The boundary is 360's own, and equality is honoured on purpose.  What the
    row holds is the instant the decision was *recorded*, not the span the
    evaluation ran over — a table with no column for that span cannot state
    that a decision stamped in the same instant the criteria landed was made
    against criteria that did not exist yet, and feature 360's own finding is
    *recorded after*, which equality is not.  Refusing equality would refuse
    a sequence the table has no precision to distinguish.
    """
    if decided < pre_registered:
        raise PromotionDecisionError(
            f"{PROMOTION_DECISION_ERROR_CODE}: the decision for node {node} is "
            f"stamped {decided.isoformat()}, before the criteria were fixed at "
            f"{pre_registered.isoformat()}. §13 item 7's law is an ordering "
            "between exactly these two columns — the criteria are pre-registered "
            "and hashed before the evaluation that decides them — and a row "
            "carrying the reverse order is the finding feature 360's CI "
            "invariant refuses a merge over (*promotion criteria recorded after "
            "the deciding evaluation*), authored here rather than caught there. "
            "This store does not judge the promotion: it declines to persist two "
            "columns that disagree with the law they exist to serve. Record the "
            "decision at or after the instant the criteria were fixed — for a "
            "genuine promotion that is the instant the evaluation actually ran "
            "(feature 293)"
        )


def _absent_registration(node: str) -> PromotionDecisionError:
    """The absence refusal: there is no open promotion for this decision to close.

    The precondition that makes this feature's ``depends_on="291"`` load
    bearing rather than bibliographic, phrased as a refusal with its repair in
    it — the same move :meth:`promotion.blocking.PromotionBlocks.
    _require_decision` makes for the block.  §13 item 7 fixes a promotion's
    criteria *before* the evaluation that decides them, so the row this act
    stamps has to exist before the stamp does; a decision recorded against a
    node nobody pre-registered would be a verdict with no criteria to be
    checked against, which is the row that law exists to make impossible.
    """
    return PromotionDecisionError(
        f"{PROMOTION_DECISION_ERROR_CODE}: {PROMOTION_REGISTRY_TABLE} holds "
        f"no row for {NODE_ID_COLUMN} {node}, so there is no promotion for "
        "this decision to close. §13 item 7 fixes a promotion's criteria "
        "before the evaluation that decides them, and feature 293's stamp "
        "lands on the row feature 291's act opened — a decision recorded "
        "against a node nobody pre-registered would be a verdict with no "
        "criteria to be checked against, the row that law exists to make "
        "impossible. Pre-register the promotion (feature 291) and record "
        "its decision after the evaluation has run (feature 293)"
    )


# -- The store ---------------------------------------------------------------------


class PromotionDecisions:
    """The store that persists promotion decisions — feature 293's act.

    Constructed with the database URL the registry lives in;
    :meth:`record_decision` closes one node's pre-registration with its
    deciding stamp, :meth:`decision` reads one node's row back — open or
    closed — and :meth:`decisions` enumerates every decision the deployment
    has persisted.  The class resolves its path lazily, so constructing one
    performs no I/O: composition-time work must not touch the disk, the
    contract every store in this workspace states.

    The store holds no cache of the rows it closed, for the reason
    :class:`~promotion.pre_register.PreRegistrations` states for its own: the
    row is the only record of the decision, so it is the only thing an answer
    is drawn from.  A memo of decided nodes would make *was this promotion
    decided, and when?* a question about this process's history — and the
    readers asking it (feature 294's epoch charge, feature 300's forward
    window, feature 360's invariant) all run somewhere else entirely.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the decisions live in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one decision: a URL that is
        not a non-empty string names no registry, and a store that accepted
        one would fail identically on every decision — the wrong place for a
        deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise PromotionDecisionError(
                f"{PROMOTION_DECISION_ERROR_CODE}: {DATABASE_URL_ENV} must be "
                "a non-empty database URL. A promotion decision is persisted "
                "as the closing stamp on a row in the database the deployment "
                "names, and a store pointed at nothing has nowhere to record "
                "one — an unrecorded decision is the silence §13 item 4's "
                "epoch ledger and feature 300's forward window are built to "
                "never have to guess about (feature 293)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> PromotionDecisions | None:
        """The decision store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the way every store
        in this workspace treats its configuration.  Absent is not an error:
        it is a deployment without a relational store, and the caller that
        must record a decision is the caller that must not find itself in it
        — a decision that went nowhere is an epoch never charged and a forward
        window never opened, neither of which any later reader can recover.
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
    def path(self) -> Path:
        """The SQLite file behind the registry, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name, in *this* feature's
        vocabulary) the first time an operation needs it.
        """
        if self._path is None:
            try:
                self._path = _sqlite_path(self._database_url)
            except PromotionStoreError as exc:
                raise _translated(exc, "database address") from exc
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the registry's database, bringing the one table it names up.

        One statement of intent.  :func:`promotion.schema.
        bootstrap_decision_schema` runs the *owning migration's* own
        ``statements("sqlite")`` — ``0108``, the file that declares
        ``promotion_registry`` — so this store authors no DDL, spells no
        column and cannot drift from the schema's owner.  Every statement is
        ``CREATE TABLE IF NOT EXISTS``, so a fresh database, a fully migrated
        one and one a store in this member created earlier all take the same
        path.

        **One owner and not the pre-registration's three.**  This act's two
        statements name ``promotion_registry`` and nothing else: the read and
        the update never write a row through the child keys, and SQLite does
        not resolve a foreign key's parent for an ``UPDATE`` of a non-key
        column (verified against SQLite 3.45.1 on a registry-only database),
        so ``node`` and ``epoch_ledger`` would be tables no statement here
        names — the habit :mod:`promotion.schema` exists to keep distinguishable
        from a dependency.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — SQLite's own
        default is off, and the pragma is what makes the row's two references
        hold against a hand that reaches past this store with a raw
        connection, the reason every store in this member sets it.  No parent
        probe is needed here because no parent is written: the row this act
        closes was checked against its parents by the feature that inserted
        it.

        The caller owns the connection; use it as a context manager to commit,
        which is what the write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_decision_schema(connection)
        except PromotionError as exc:
            connection.close()
            raise _translated(exc, "database") from exc
        except sqlite3.Error as exc:
            connection.close()
            raise PromotionDecisionError(
                f"{PROMOTION_DECISION_ERROR_CODE}: the database at {path} could "
                f"not be brought to the revision a decision needs: {exc}. The "
                f"{PROMOTION_REGISTRY_TABLE} table is created by migrations/"
                "versions/0108_forward_and_universe_tables.py; this store runs "
                "that file's own statements and authors none of its own "
                "(feature 293)"
            ) from exc
        return connection

    # -- Feature 293: the decision -------------------------------------------

    def record_decision(
        self,
        node_id: Any,
        *,
        decided_at: dt.datetime | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> tuple[PromotionRecord, bool]:
        """Persist one promotion's decision — feature 293's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity, the stamp as an
           aware-UTC instant — before anything is opened, so a malformed
           decision is refused without touching a database and a refused call
           leaves no row, no stamp and no file behind.
        2. **Read the node's standing row.**  An absent row is refused by
           name — there is no promotion for this decision to close, and the
           repair is feature 291's act first, which is §13 item 7's ordering
           and not an incidental precondition.  A closed row is the standing
           answer: nothing is written and nothing moves, for the reason a
           retried pre-registration returns its standing row — the caller
           that asks again did not move the instant the promotion was
           decided.
        3. **Check the two stamps against §13 item 7.**  A decision stamped
           before the criteria were fixed is refused rather than persisted —
           see :func:`_validated_after_pre_registration`, and the boundary it
           shares with feature 360's CI invariant.
        4. **Close the row and read it back**, inside the same transaction,
           so the stamp, the hash and the first instant in the answer are the
           table's own.

        **The answer is the decision as persisted**: a
        :class:`~promotion.pre_register.PromotionRecord` whose ``decided_at``
        is the deciding stamp and whose ``criteria_hash`` is the hash feature
        291 recorded — the sentence's two nouns, read off the row rather than
        assembled from the arguments.  The ``bool`` says whether *this* call
        closed the row; ``False`` is a re-decision answered by the standing
        row, the readable spelling of a retry.

        **What this act never does.**  It never judges the promotion — the
        verdict on the evidence is the deciding evaluation's, and the mismatch
        refusal is feature 292's.  It never touches ``criteria_hash``,
        ``epoch_id``, ``node_id`` or ``pre_registered_at``: the update's
        ``SET`` clause names one column, the mirror of the insert that could
        not name ``decided_at``.  And it never charges the epoch — feature
        294's act reads the closed rows this one writes.

        Refuses, in this order, each naming what it is about and all in
        :class:`~promotion.errors.PromotionDecisionError`: a malformed node,
        a naive or unparseable stamp, then — from the store — a
        ``DATABASE_URL`` this member cannot speak, a node holding no
        pre-registration, a decision that would precede its criteria, and a
        row that did not close or could not be read back.

        ``decided_at`` states the instant the promotion was decided, and
        ``clock`` supplies the default when it is absent — tests and replays
        route their own time through it, the same seam
        :meth:`~promotion.pre_register.PreRegistrations.pre_register` offers.
        """
        node = _decision_node_id(node_id)
        stamped = (
            _decision_instant(decided_at)
            if decided_at is not None
            else (clock or utc_now)()
        )
        with closing(self._connect()) as connection, connection:
            standing = self._registration_of(connection, node)
            if standing is None:
                raise _absent_registration(node)
            if not standing.open:
                return standing, False
            _validated_after_pre_registration(
                node, stamped, standing.pre_registered_at
            )
            try:
                cursor = connection.execute(
                    _UPDATE_SQL, (stamped.isoformat(), node)
                )
                try:
                    closed_by_this_call = cursor.rowcount == 1
                finally:
                    cursor.close()
            except sqlite3.IntegrityError as exc:
                raise PromotionDecisionError(
                    f"{PROMOTION_DECISION_ERROR_CODE}: the decision for node "
                    f"{node} could not be written: {exc}. The update names one "
                    f"column and one row this store read as open — so a "
                    f"constraint that refused anyway is a database whose "
                    f"tables are not the ones this deployment migrated "
                    "(feature 293)"
                ) from exc
            written = self._registration_of(connection, node)
        if written is None or written.open:
            raise PromotionDecisionError(
                f"{PROMOTION_DECISION_ERROR_CODE}: the decision for node "
                f"{node} could not be read back after the write. A decision "
                "has to be accounted for — §13 item 4's epoch ledger charges "
                "sequestered epochs by the decisions these rows record, and "
                "feature 300's forward measurement window opens at this stamp "
                "— and a row that cannot be re-read as closed is a decision "
                "this store cannot vouch for (feature 293)"
            )
        return written, closed_by_this_call

    # -- Feature 293: the reads ----------------------------------------------

    def decision(self, node_id: Any) -> PromotionRecord | None:
        """One node's row — the decision's record, open or closed.

        The question every reader of §13 item 7's record starts from, answered
        from the row: a record with ``decided_at`` set is the persisted
        decision (its timestamp and its criteria hash, and ``open`` reads
        ``False``); a record with ``decided_at`` ``None`` is a pre-registration
        whose deciding evaluation has not been recorded; and ``None`` itself
        means the node holds no row at all — there is no promotion to ask
        about, a different fact from an undated one, which is why the open row
        is *returned* rather than collapsed into the absence.  The distinction
        mirrors :meth:`~promotion.blocking.PromotionBlocks.blocked`'s: an
        unreachable database raises, so a broken store can never be mistaken
        for an undecided promotion.

        A blank or non-text id is refused rather than answered ``None``: a
        name that states nothing is a malformed ask, not an unregistered
        promotion, and the two must not collapse into one answer.
        """
        node = _decision_node_id(node_id)
        with closing(self._connect()) as connection:
            return self._registration_of(connection, node)

    def decisions(self) -> tuple[PromotionRecord, ...]:
        """Every decision this deployment has persisted, ordered by node.

        The *each* of the feature's sentence made enumerable: one closed row
        per promotion, carrying its deciding stamp and its criteria hash —
        the listing an auditor reads before charging epochs (feature 294's
        precondition), opening forward windows (feature 300) or checking the
        two-timestamp law (feature 360).  A tuple rather than a live cursor,
        because the answer is a value the caller keeps rather than a view
        that changes under it, and ordered by the table's key so two reads of
        one store are comparable.  An open row is deliberately absent from
        the listing: it is a pre-registration, not a decision.
        """
        with closing(self._connect()) as connection:
            cursor = connection.execute(_LIST_DECIDED_SQL)
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return tuple(self._decided_record(row) for row in rows)

    # -- The words ----------------------------------------------------------

    def _registration_of(
        self, connection: sqlite3.Connection, node: str
    ) -> PromotionRecord | None:
        """One node's registry row, or ``None`` when the table holds none.

        Feature 291's own read spelling — :data:`~promotion.pre_register.
        _READ_SQL` and :func:`~promotion.pre_register._record_from_row` — used
        rather than restated, so the row this act closes and the row the
        pre-registration answered with cannot be two readings of one table.
        A validation refusal off the row is translated into this feature's
        vocabulary at the seam, for the reason every wrapper here exists: a
        corrupt row must refuse the *decision*, not masquerade as a
        pre-registration failure.

        More than one row for the node is refused rather than resolved, the
        argument :meth:`~promotion.pre_register.PreRegistrations._node_records`
        states: a node holding two rows holds two answers to *what was this
        promotion decided against?* and closing "the" row would be a choice
        between them.  Nothing this member writes can produce the state, so a
        second row is a hand that reached past it, and the message says so.
        """
        cursor = connection.execute(_READ_SQL, (node,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if len(rows) > 1:
            raise PromotionDecisionError(
                f"{PROMOTION_DECISION_ERROR_CODE}: node {node} holds "
                f"{len(rows)} {PROMOTION_REGISTRY_TABLE} rows. The table must "
                "hold one row per node for there to be one decision to close "
                "— this member's writers keep exactly that law — and a node "
                "holding two would make the decision a choice between rows "
                "nobody decided between (feature 293)"
            )
        if not rows:
            return None
        try:
            return _record_from_row(rows[0], node)
        except PromotionError as exc:
            raise PromotionDecisionError(
                f"{PROMOTION_DECISION_ERROR_CODE}: node {node}'s "
                f"{PROMOTION_REGISTRY_TABLE} row could not be read back "
                f"while recording this decision: {exc}"
            ) from exc

    def _decided_record(self, row: tuple[Any, ...]) -> PromotionRecord:
        """Build a decided row's record — the listing's one constructor.

        So every row :meth:`decisions` returns is built the way the act's own
        read-back builds one.  A refusal raised off the row keeps this
        feature's class and carries the inner message whole — the node is
        already named inside it, because :func:`~promotion.pre_register.
        _record_from_row` puts it there — so an operator reading a corrupt
        listing learns which row, not merely that some row somewhere is not
        readable as a decision.
        """
        try:
            return _record_from_row(row, row[1])
        except PromotionError as exc:
            raise PromotionDecisionError(
                f"{PROMOTION_DECISION_ERROR_CODE}: a decided "
                f"{PROMOTION_REGISTRY_TABLE} row could not be read back: {exc}"
            ) from exc

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- The module-level spellings -----------------------------------------------------


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spellings act on, or a refusal naming the gap.

    The same seam :func:`promotion.blocking.record_block` and
    :func:`promotion.calibration.rejects_void_promotion` resolve, restated in
    this feature's vocabulary: an explicit URL wins, else ``DATABASE_URL``,
    and a deployment that names neither is refused *by name* rather than
    silently doing nothing.  The silence is the dangerous failure here and not
    the refusal: a decision that quietly went unrecorded leaves an epoch
    never charged and a forward window never opened, which is the state
    §13 item 4's ledger exists to make impossible.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise PromotionDecisionError(
            f"{PROMOTION_DECISION_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), "
            "so there is nowhere to persist this decision. A promotion "
            "decision is the closing stamp on a registry row, and §13 item 4 "
            "charges sequestered epochs by the decisions those rows record — "
            "a store resolved from nothing is a refusal rather than a silent "
            "no-op (feature 293)"
        )
    return url


def record_decision(
    node_id: Any,
    *,
    decided_at: dt.datetime | None = None,
    clock: Callable[[], dt.datetime] | None = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[PromotionRecord, bool]:
    """Persist one promotion's decision — the module-level spelling of 293's act.

    The feature's sentence as one call, for the caller that wants the act
    without holding a store — the promotion path's last line, after the
    deciding evaluation has run and after features 292 and 298 have had their
    refusals.  The store is resolved from ``database_url``, else from
    ``DATABASE_URL``, exactly as :func:`promotion.pre_register.PreRegistrations.
    resolve` and :func:`promotion.blocking.record_block` resolve theirs.

    A :class:`~promotion.errors.PromotionDecisionError` from the store or the
    resolution propagates unwrapped: the refusal already names the node and
    the fact, and re-wrapping it here would put a second message in front of
    the one an operator needs.
    """
    url = _resolved_url(database_url, env)
    return PromotionDecisions(url).record_decision(
        node_id, decided_at=decided_at, clock=clock
    )


def promotion_decision(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> PromotionRecord | None:
    """Read one node's row back — the module-level spelling of the read.

    For the caller that holds a URL rather than a store: an operator asking
    whether a promotion was decided and when, a report enumerating the
    registry, feature 294's epoch charge asking after the rows it counts.
    Resolved the same way :func:`record_decision` resolves its store, so the
    caller that records through one spelling and reads through the other is
    reading the row it closed.

    ``None`` means the node holds no pre-registration at all; an open row is
    returned as itself, with the scope :meth:`PromotionDecisions.decision`
    states.
    """
    url = _resolved_url(database_url, env)
    return PromotionDecisions(url).decision(node_id)
