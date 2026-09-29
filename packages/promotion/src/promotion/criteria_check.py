"""A promotion is judged against the hash it was pre-registered under — feature 292.

app_spec.xml, "Promotion & Epoch Governance", feature 292: *System rejects a
promotion whose recorded criteria hash differs from the pre-registered value,
which returns a criteria_mismatch error message.*  Its declared parent is
feature 291 — the pre-registration — and docs/alpha-engine-prd.md §13 item 7 is
the law the sentence serves, quoted here as it is written, because the refusal
is the sentence's own:

.. code-block:: text

    7. Promotion criteria are pre-registered and hashed before the evaluation
       that decides them.

§13 item 7 fixes the criteria as a hash *before* the deciding evaluation runs;
feature 291 writes that hash onto the row.  But a hash written down is only
evidence if it is the hash the promotion is *actually judged against*, and the
whole point of fixing the criteria in advance is defeated the moment the
evaluation clears a bar that the pre-registered criteria would not have.  This
feature is the enforcement of that promise at decision time: given the criteria
the evaluation *claims* it ran, it recomputes their hash and compares it to the
one the row carries, and refuses the promotion when the two differ.  The word
doing the work is *differs*: a promotion whose recomputed hash does not match
the recorded one was judged against criteria that were not the ones fixed, which
is precisely the post-hoc bar §13 item 7 exists to make impossible.

**The comparison is the whole feature, and it is a comparison rather than a
write.**  Feature 291 records the hash; feature 293 closes the row with its
stamp; this feature reads the recorded hash and weighs it against the criteria
the promotion is being decided on.  Nothing here writes a row, stamps a column
or advances a ledger — the act is a judgement, and the judgement is a single
equality between two 64-hex-character digests.  The recorded hash is the row's
own, read through feature 291's store so there is one reading of
``promotion_registry.criteria_hash`` in the tree; the recomputed hash is
:func:`promotion.criteria.criteria_hash` taken over the criteria the caller
supplies — the same digest function feature 291 hashed with, so a match is a
match of *values*, not of spellings.  The two are compared for exact equality,
and nothing is normalised: two different criteria sets hash to two different
digests by :func:`criteria_hash`'s own property (every one of the six terms
moves the hash), so a mismatch is unambiguous and a near-miss is not a thing
this comparison could see.

**What "the pre-registered value" is, and why the recorded hash is the
authority.**  The feature's sentence names two things — *the recorded criteria
hash* and *the pre-registered value* — and they are the same column seen from
the two sides of the decision.  The recorded hash is what feature 291 wrote
before the evaluation, the digest as it sits on the row.  The pre-registered
value is that same digest's meaning: the criteria as they were fixed.  This
feature does not hold the pre-registered criteria document — ``promotion_registry``
carries the hash, not the document, and sha256 is one-way — so it cannot compare
document to document.  Instead it takes the criteria the promotion is being
decided under *now*, recomputes their digest, and asks whether that digest equals
the one recorded *then*.  Equality answers the only question §13 item 7 cares
about: *are the criteria this promotion is being decided on the criteria that
were fixed for it?*  A "yes" lets the promotion proceed to its real verdict; a
"no" is the refusal, and the refusal is the feature.

**The recorded hash is read through feature 291's store, not re-probed.**
:class:`~promotion.pre_register.PreRegistrations` already answers *this node's
row, open or closed*, and already refuses the two-row and the corrupt-row cases
in the registry's vocabulary.  A second ``SELECT`` against ``promotion_registry``
here would be a second reading of one table — the discipline every store in this
member states — and would put two answers to *what does this node's row carry?*
in the tree.  So the gate is constructed **over** a :class:`PreRegistrations`
and owns no connection, no bootstrap and no statement: every fact it reads comes
from the registry store's read, and every refusal that read raises arrives
already phrased for a registry row.  Duck-typed rather than ``isinstance``-
guarded, the seam every component in this member states — the factory's scan
imports this member under a synthetic module name, so the *composed* store is
structurally a ``PreRegistrations`` and never the same class object a direct
import yields.

**An absent or open row is refused by name, and the refusal is not the mismatch.**
A node that holds no registry row was never pre-registered, so there is no hash
to compare against — the repair is feature 291's act, and answering *criteria
mismatch* to it would tell the caller its criteria were wrong when the truth is
that it never registered them.  A node whose row is still open — ``decided_at``
NULL — is a promotion whose deciding evaluation has not been recorded, so there
is no promotion to reject yet; the comparison this feature makes is a comparison
of a *decided* promotion against its criteria, and an open row is not one.  Both
absences are refused in this feature's own class rather than in the registry's,
for the reason every wrapper in this member exists: a caller whose single
``except`` guards its promotion path must read *this promotion was refused on its
criteria* and not *the registry could not be read*, because the two send the
operator to two different repairs.

**The verdict is the promotion's, and the refusal is this feature's — and they
are not the same act.**  This module compares the criteria against the hash and
nothing else.  It never reads a pool, a score, a coverage ledger or a forward
record, and it never decides whether the promotion *stands* — whether the ΔIR
cleared its bar and the FDR held is the deciding evaluation's verdict, and that
verdict is the caller's to bring.  A match does not mean the promotion passes;
it means the promotion was judged on the criteria it was supposed to be judged
on, which is the precondition every merit verdict is checked against.  The
distinction is the one :mod:`promotion.blocking` and :mod:`promotion.calibration`
both draw for their own refusals: this feature judges the *form* of the decision
— *was it made against the fixed criteria?* — and not its *merit*.

**The refusal raises, and that is the point.**  A promotion whose recomputed
hash matches returns its recorded hash; one whose hash differs **raises**
:class:`~promotion.errors.CriteriaMismatchError`, the shape feature 285 takes in
the regime member and for the same reason: the caller calls this on its last
line, so the stop has to be the function's own act rather than a boolean every
caller must remember to branch on — and the caller that forgets is precisely a
promotion decided against criteria that were never the fixed ones, which is the
outcome §13 item 7's *before* exists to stop.

**No component, no seat, no router, no second builder.**  The member's
registered surface stays feature 291's one store, for the reason every sibling
states: a builder takes no arguments and is built on every ``create_app()`` call,
while *which criteria a promotion was decided against* is a fact about a row and
a caller's document that no composition can supply.  The composed
``promotion`` component is untouched and still answers one question.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``os``, ``contextlib`` and this
member's own modules at module scope and nothing else: no third-party import and
no import of another workspace member, so the factory's scan imports this package
for the near-nothing it always did and a refused promotion costs its caller only
the connection it already had.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from .criteria import criteria_hash
from .errors import (
    CRITERIA_MISMATCH_ERROR_CODE,
    CriteriaMismatchError,
    PromotionError,
    PromotionStoreError,
)
from .pre_register import (
    DECIDED_AT_COLUMN,
    NODE_ID_COLUMN,
    PROMOTION_REGISTRY_TABLE,
    PreRegistrations,
    PromotionRecord,
    _sqlite_path,
    _validated_criteria_hash,
    _validated_uuid,
)
from .schema import bootstrap_decision_schema

__all__ = [
    "CriteriaChecks",
    "matches_recorded_criteria",
    "rejects_mismatched_criteria",
]

#: The node's registry row, read back through feature 291's store.  Spelled as
#: a constant here rather than inlined so the read and the two absences it
#: refuses cannot drift apart on which column was asked — the node is the key
#: the store reads by, and the same key feature 291 recorded under.
_NODE_ID_COLUMN = NODE_ID_COLUMN

#: The environment variable the module-level spellings resolve their database
#: from.  Restated here rather than imported from :data:`promotion.pre_register.
#: DATABASE_URL_ENV` — this member names no other member's constants across the
#: seam — but it is the same name, so a deployment that set it for the
#: pre-registration reaches this gate from the same variable.
DATABASE_URL_ENV = "DATABASE_URL"


# -- The verdict -------------------------------------------------------------------


def matches_recorded_criteria(
    node_id: Any, criteria: Any, recorded_hash: Any
) -> str:
    """Compare a promotion's criteria against its recorded hash — feature 292's judgment.

    Takes the node being promoted, the criteria the promotion is being decided
    under, and the hash the row carries, and either the promotion's criteria are
    confirmed to match what was pre-registered or they are refused.  This is the
    whole of the feature's sentence — *"System rejects a promotion whose recorded
    criteria hash differs from the pre-registered value"* — as one comparison, and
    it is the seam for the caller that **already holds both hashes**: the promotion
    path that read the row itself, a test judging a carrier, a later feature that
    reached the recorded digest its own way.  The caller that holds only the node
    being promoted asks :meth:`CriteriaChecks.rejects_mismatched_criteria` instead,
    which performs this module's one read and then delegates here, so there is one
    comparison in the member and not two.

    **It raises** :class:`~promotion.errors.CriteriaMismatchError` when the
    recomputed hash differs from the recorded one, and returns the recorded hash
    otherwise.  Raising rather than answering a boolean is feature 285's argument,
    and it binds harder here: a caller that forgets to branch on a boolean promotes
    a hypothesis decided against criteria that were never the fixed ones, which is
    the post-hoc bar §13 item 7 exists to prevent.  The stop is the function's own
    act.

    **The comparison is exact.**  The recorded hash is feature 291's 64 lowercase
    hex characters, validated on the way in; the recomputed hash is
    :func:`promotion.criteria.criteria_hash` over the supplied criteria, the same
    digest function feature 291 hashed with.  Two criteria sets that state the same
    terms hash identically however they were spelled — ``0.3`` and ``0.30`` are one
    bar — so a match is a match of *values*; and two sets that differ in any one
    term hash differently, so a mismatch is unambiguous.  What is deliberately *not*
    done: no case-folding, no truncation, no fuzzy match.  A digest that is one
    character off is a criteria set that is one term off, and a near-miss is not a
    thing a sha256 comparison can see.

    **What it returns when it does not raise** is the recorded hash, so the caller
    that wants to log or carry it does not read the row twice.  It is the value it
    compared and not a derived one.

    Refuses, in this order, each naming what it is about:

    1. a ``node_id`` that is not a UUID — the refusal it raises must name *which*
       promotion was refused, and an identity that names no row names no promotion
       an operator could go and read;
    2. a ``criteria`` carrier with no callable ``canonical`` — the recomputed hash
       is taken over the criteria's canonical document, and a carrier of something
       else has no digest to compare; the refusal names the criteria, because a
       hash of *something else* compared against the recorded one would refuse a
       promotion for a reason nobody decided;
    3. a ``recorded_hash`` that is not 64 lowercase hex characters — the column is
       ``CHAR(64)`` and SQLite's affinity is not a width, so a corrupt recorded
       value is refused by name rather than compared against, which would refuse a
       promotion for a corruption it never mentions.
    """
    node = _check_node_id(node_id)
    recomputed = _recomputed_hash(criteria)
    recorded = _recorded_hash(node, recorded_hash)
    if recomputed == recorded:
        return recorded
    raise CriteriaMismatchError(
        f"{CRITERIA_MISMATCH_ERROR_CODE}: node {node} was pre-registered with "
        f"criteria hash {recorded} and this promotion is being decided under "
        f"criteria hashing to {recomputed}. docs/alpha-engine-prd.md §13 item 7 "
        "fixes a promotion's criteria — the paired ΔIR advantage, the significance "
        "level, the deployment FDR ceiling and the three quantities of evidence — "
        "and hashes them before the evaluation that decides them, so the promotion "
        "must be judged against the criteria as they were fixed, not against a bar "
        "moved after the result was known. These two hashes differ, which means the "
        "criteria this promotion is being decided on are not the criteria that were "
        "pre-registered for it: a promotion cleared a bar the fixed criteria did not "
        "set, which is exactly the post-hoc bar §13 item 7 exists to make "
        "impossible. Re-run the deciding evaluation against the pre-registered "
        "criteria (the six terms feature 291 records — theta, alpha, "
        "max_fdr_deploy, min_worlds, min_coverage_strata, min_forward_days), or "
        "pre-register the criteria this promotion was actually judged under against "
        "the hypothesis it is really about, in its own node (feature 292)"
    )


# -- Validation --------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> CriteriaMismatchError:
    """Re-raise a sibling's refusal in this feature's vocabulary.

    The seam rule this workspace states at every member boundary, applied
    *inside* one member — the shape :func:`promotion.blocking._translated` and
    :func:`promotion.calibration._translated` take toward the same validators.
    Feature 291's calendar of refusals raises ``PromotionError`` for a malformed
    identity and ``PromotionStoreError`` for a path it cannot speak, and a caller
    whose single ``except CriteriaMismatchError`` guards its promotion path must
    not be defeated by a refusal phrased for a pre-registration: it would read
    *the body was malformed* where the truth is *this promotion was refused on its
    criteria* — and would go on to promote a hypothesis decided against criteria
    that were never the fixed ones, the silence this feature exists to prevent.
    The inner message is carried through, so nothing an operator needs is lost;
    only re-framed, with the frame naming which act was being performed.

    ``type(exc)(...)`` is deliberately **not** used: here the class itself is the
    thing being corrected, exactly as in the two siblings.
    """
    return CriteriaMismatchError(
        f"{CRITERIA_MISMATCH_ERROR_CODE}: the {what} could not be reached to "
        f"judge this promotion: {exc}"
    )


def _check_node_id(value: Any) -> str:
    """Return ``value`` as a node identity, or refuse it in *this* vocabulary.

    Feature 291's identity validator is the one spelling this member has for *an
    id that joins the tree*, and the promotion being judged is keyed by exactly
    that value — so the rule is *used* rather than restated, the move every
    sibling makes.  What it raises is ``PromotionError``, the member's ask face,
    and that is what the wrapper is for: the refusal has to arrive as a *criteria
    mismatch* refusal, or a caller's single ``except CriteriaMismatchError`` walks
    through it and the promotion proceeds.
    """
    try:
        return _validated_uuid(value, _NODE_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "node identity") from exc


def _recomputed_hash(criteria: Any) -> str:
    """The digest of the criteria the promotion is being decided under.

    :func:`promotion.criteria.criteria_hash` — the same digest function feature
    291 hashed the pre-registered criteria with — so a match is a match of values
    and not of spellings.  Duck-reads the carrier's ``canonical()`` rather than
    taking an ``isinstance``: the factory's scan imports this member under a
    synthetic module name, so the *composed* criteria value is structurally a
    criteria carrier but never the same class object a direct import yields — an
    isinstance here would refuse the very value composition produced.  A carrier
    with no callable ``canonical`` is refused in this feature's class and naming
    the criteria, because a hash of *something else* compared against the recorded
    one would refuse a promotion for a reason nobody decided.
    """
    try:
        return criteria_hash(criteria)
    except PromotionError as exc:
        raise CriteriaMismatchError(
            f"{CRITERIA_MISMATCH_ERROR_CODE}: the criteria this promotion is being "
            f"decided under have no canonical document to hash — got {criteria!r} "
            f"({type(criteria).__name__}). Feature 292 compares the promotion's "
            "criteria against the hash they were pre-registered under, and a hash "
            "taken over anything but the criteria's own canonical document would "
            "compare a digest of a document no reader could reproduce against the "
            "recorded one. State the criteria as the six-term document feature 291 "
            "registers (theta, alpha, max_fdr_deploy, min_worlds, "
            "min_coverage_strata, min_forward_days) (feature 292)"
        ) from exc


def _recorded_hash(node: str, recorded_hash: Any) -> str:
    """The recorded hash, validated as the column spells it.

    The shape check is feature 291's own
    (:func:`~promotion.pre_register._validated_criteria_hash`, 64 lowercase hex
    characters) *used* rather than restated, and the re-framing is the seam every
    wrapper here takes — it raises ``PromotionStoreError``, the member's *a row
    could not be read* face, which is exactly what a corrupt hash on a row is.  It
    earns its place at this act specifically: the hash is what the promotion is
    compared against, so a corrupt one handed on unexamined would refuse or admit a
    promotion on a digest no criteria could ever equal.
    """
    try:
        return _validated_criteria_hash(recorded_hash)
    except PromotionStoreError as exc:
        raise _translated(exc, "recorded hash") from exc


# -- The gate ----------------------------------------------------------------------


class CriteriaChecks:
    """The gate that refuses a promotion decided against the wrong criteria — 292's act.

    Constructed with the database URL the registry rows live in;
    :meth:`rejects_mismatched_criteria` is the feature's act — the node being
    promoted in, the criteria it is being decided under, the verdict out, or a
    refusal — :meth:`matches_criteria` is the same comparison *without* the raise,
    for a caller that wants the figure rather than the decision.  The class
    resolves its path lazily, so constructing one performs no I/O: composition-time
    work must not touch the disk, the contract every store in this workspace
    states.

    **It reads through feature 291's store, and owns no read of its own.**  A
    caller promoting a hypothesis holds feature 291's node identity; the recorded
    hash is one column away on that node's ``promotion_registry`` row, and
    :class:`PreRegistrations` already answers *this node's row*.  A second registry
    read here would be a second reading of one table — the discipline
    :meth:`~promotion.pre_register.PreRegistrations._node_records` states when it
    reuses :data:`~promotion.pre_register._READ_SQL` rather than restating it — and
    would put two answers to *what does this node's row carry?* in the tree.  So
    this gate is constructed **over** a :class:`PreRegistrations` and owns no
    connection, no bootstrap and no statement: every fact it reads comes from the
    registry store's read, and every refusal that read raises arrives already
    phrased for a registry row.  Duck-typed rather than ``isinstance``-guarded, the
    seam every component in this member states.

    **It holds no cache.**  A memo of recorded hashes would make *was this
    promotion decided against its fixed criteria?* a question about this process's
    history — and the answer moves: the criteria are fixed once, but the promotion
    being judged is the caller's to bring, and a gate that remembered a hash across
    a long-lived process would admit a promotion re-decided under moved criteria.
    The row is the only record and the only thing an answer is drawn from, which is
    the same stance :class:`~promotion.pre_register.PreRegistrations` and
    :class:`~promotion.blocking.PromotionBlocks` take toward theirs.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the gate to the database the registry rows live in.

        The URL is validated here, before any call, because it is a fact about the
        *gate* rather than about any one promotion: a URL that is not a non-empty
        string names no table, and a gate that accepted one would fail identically
        on every judgment — the wrong place for a deployment to discover a wiring
        fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise CriteriaMismatchError(
                f"{CRITERIA_MISMATCH_ERROR_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL. A promotion's recorded criteria hash is a "
                "column on the registry row feature 291 wrote, and a gate pointed at "
                "nothing has no row to read — so it could neither confirm nor refuse "
                "a promotion, which is the refusal a promotion path must never "
                "receive silently (feature 292)"
            )
        self._database_url = database_url.strip()
        # The gate reads through feature 291's store, and owns no read of its
        # own: every fact it reads comes from this store's read of one table.
        self._registry: PreRegistrations = PreRegistrations(self._database_url)
        # Resolved on first use rather than at construction: building the gate
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> CriteriaChecks | None:
        """The gate ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the way every store in
        this workspace treats its configuration.  Absent is not an error: it is a
        deployment without a relational store, and the caller that must judge a
        promotion's criteria is the caller that must not find itself in it — §13
        item 7 leaves nothing to fall back on, so a caller that treats this ``None``
        as *criteria confirmed* would promote a hypothesis whose criteria were never
        checked.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this gate reads from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the registry rows, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL this
        member cannot speak is refused by name, in *this* feature's vocabulary) the
        first time an operation needs it.
        """
        if self._path is None:
            try:
                self._path = _sqlite_path(self._database_url)
            except PromotionStoreError as exc:
                raise _translated(exc, "database address") from exc
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the gate's database, bringing the one table it reads up.

        One statement of intent.  :func:`promotion.schema.bootstrap_decision_schema`
        runs the *migrations'* own ``statements("sqlite")`` for the one table this
        act reads — ``promotion_registry`` (``0108``) — so this gate authors no DDL,
        spells no column and cannot drift from the schema's owner.  The statement is
        ``CREATE TABLE IF NOT EXISTS``, so a fresh database, a fully migrated one
        and one a store in this member created earlier all take the same path.

        **The one table and not the pre-registration's three.**  This act reads
        ``promotion_registry`` alone — the recorded hash is on the node's registry
        row — so bringing ``node`` and ``epoch_ledger`` up would create tables this
        read has no business filling.  The pre-registration's ``INSERT`` needs the
        two parents because SQLite resolves a foreign key's parent when a row is
        written through the child table; this act writes nothing and resolves no
        parent, so ``node`` and ``epoch_ledger`` are tables no statement of this act
        names.  A deployment that has already run the chain holds all of them; a
        deployment that has run nothing gets exactly what this gate needs to answer.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — this member's other
        stores set it, and this one keeps it for the same reason: it makes the
        constraint hold against a hand that reaches past this store with a raw
        connection.  No parent probe is needed here because no parent is written:
        the row this gate reads was checked against its parents by the feature that
        inserted it.

        The caller owns the connection; use it as a context manager to commit —
        though nothing here writes.
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
            raise CriteriaMismatchError(
                f"{CRITERIA_MISMATCH_ERROR_CODE}: the database at {path} could not "
                f"be brought to the revision a criteria judgement needs: {exc}. The "
                f"{PROMOTION_REGISTRY_TABLE} table is created by "
                "migrations/versions/0108_forward_and_universe_tables.py; this gate "
                "runs that file's own statements and authors none of its own "
                "(feature 292)"
            ) from exc
        return connection

    # -- Feature 292: the judgement -----------------------------------------

    def rejects_mismatched_criteria(self, node_id: Any, criteria: Any) -> str:
        """Judge one promotion's criteria against its recorded hash — feature 292's act.

        The steps, in the order they must happen:

        1. **Validate the node** before anything is opened, so a malformed identity
           is refused without touching a database and a refused call leaves no file
           behind.
        2. **Read the node's registry row** through feature 291's store.  An absent
           row is refused by name — there is no recorded hash to compare against,
           and the repair is feature 291's act, not a criteria fix.  An open row —
           ``decided_at`` still NULL — is refused by name — the deciding evaluation
           has not been recorded, so there is no promotion to reject.  Both
           refusals are this feature's own class, not the registry's, because the
           repair differs.
        3. **Delegate the comparison** to :func:`matches_recorded_criteria`, so the
           member has one spelling of §13 item 7's test and this method cannot
           disagree with the pure judgment a caller may use directly.

        Returns the recorded hash it confirmed — the digest the promotion was
        pre-registered under — for every promotion whose criteria match.  Raises
        :class:`~promotion.errors.CriteriaMismatchError` when they differ, for the
        reasons :func:`matches_recorded_criteria` states.

        **It writes nothing.**  The recorded hash is already on the registry row
        this read — that row *is* the record — so a refusal here leaves the database
        exactly as it was.  The verdict is the deciding evaluation's; this gate only
        confirms the promotion was judged against the criteria it was fixed with.
        """
        node = _check_node_id(node_id)
        with closing(self._connect()) as connection:
            record = self._registry_of(connection, node)
        recorded = record.criteria_hash
        recomputed = _recomputed_hash(criteria)
        if recomputed == recorded:
            return recorded
        return matches_recorded_criteria(node, criteria, recorded)

    def matches_criteria(self, node_id: Any, criteria: Any) -> str:
        """The recorded hash of the criteria a node was pre-registered under — the read.

        The feature's read *without* its verdict, for a caller that wants the figure
        rather than the decision: an operator asking what hash a node was registered
        under, a report enumerating promotions by their recorded criteria, a later
        feature that reached the row its own way.  Deliberately a separate verb
        rather than a ``judge=False`` flag on :meth:`rejects_mismatched_criteria` —
        one question, one spelling — and deliberately not a second ``SELECT``
        either: the read lives in :meth:`_registry_of` and both verbs go through it,
        so the read a refusal was made on and the read a caller is handed cannot
        diverge.

        Refuses exactly what :meth:`rejects_mismatched_criteria` refuses on its way
        to the comparison — a malformed node, an absent node, a node still open — and
        answers no verdict of its own: a mismatched promotion's hash is *returned*,
        not raised, because this is the reading and not the judgment.
        """
        node = _check_node_id(node_id)
        with closing(self._connect()) as connection:
            record = self._registry_of(connection, node)
        return record.criteria_hash

    # -- The read, spelled once ---------------------------------------------

    def _registry_of(
        self, connection: sqlite3.Connection, node: str
    ) -> PromotionRecord:
        """The node's registry row, or a refusal naming which absence.

        Feature 291's own read spelling — :meth:`~promotion.pre_register.
        PreRegistrations._node_records` — used rather than restated, so the row
        this gate judges against and the row the pre-registration answered with
        cannot be two readings of one table.  The store answers at most one row per
        node and refuses the two-row case in its own vocabulary, so this gate reads
        exactly one record or a refusal.

        **An absent row is refused by name, and the refusal is not the mismatch.**
        A node that holds no registry row was never pre-registered, so there is no
        recorded hash to compare against; answering *criteria mismatch* would tell
        the caller its criteria were wrong when the truth is that it never recorded
        them.  The repair is feature 291's act, and the message says so.

        **An open row is refused by name, and the refusal is not the mismatch
        either.**  A row whose ``decided_at`` is still NULL is a promotion whose
        deciding evaluation has not been recorded — there is no promotion to reject,
        only a pre-registration waiting for its decision.  This comparison is of a
        *decided* promotion against its criteria, and an open row is not one.

        **The store's own refusal is translated, not carried.**  A corrupt hash on
        the row is refused by feature 291's store in the registry's vocabulary, and
        the gate re-frames it here — a promotion path must not receive a
        *registry-unwritable* refusal where the truth is *this promotion's recorded
        criteria could not be read*.  The single failure surface is the point: one
        ``except CriteriaMismatchError`` guards the whole judgment.
        """
        try:
            standing = self._registry._node_records(connection, node)
        except PromotionError as exc:
            raise _translated(exc, "recorded criteria") from exc
        if not standing:
            raise CriteriaMismatchError(
                f"{CRITERIA_MISMATCH_ERROR_CODE}: {PROMOTION_REGISTRY_TABLE} holds "
                f"no row for {_NODE_ID_COLUMN} {node}, so this promotion was never "
                "pre-registered and there is no recorded criteria hash to compare "
                "against. docs/alpha-engine-prd.md §13 item 7 fixes a promotion's "
                "criteria and hashes them before the evaluation that decides them, "
                "and feature 292's comparison is against that recorded hash — a "
                "promotion with no recorded hash was never pre-registered, which is "
                "a different failure from one decided against the wrong criteria. "
                "Pre-register the promotion (feature 291) before judging it against "
                "its criteria (feature 292)"
            )
        record = standing[0]
        if record.open:
            raise CriteriaMismatchError(
                f"{CRITERIA_MISMATCH_ERROR_CODE}: the promotion for node {node} has "
                f"a {PROMOTION_REGISTRY_TABLE} row whose {DECIDED_AT_COLUMN} is still "
                "NULL, so its deciding evaluation has not been recorded and there is "
                "no decided promotion to reject. docs/alpha-engine-prd.md §13 item 7 "
                "fixes the criteria before the evaluation, and feature 292 compares a "
                "*decided* promotion against the criteria it was fixed with — a row "
                "still open is a pre-registration waiting for its decision, not a "
                "promotion that has been decided. Record the decision (feature 293) "
                "before judging the promotion against its criteria (feature 292)"
            )
        return record

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- The module-level spellings -----------------------------------------------------


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spellings act on, or a refusal naming the gap.

    The same seam :func:`promotion.blocking.record_block` and
    :func:`promotion.calibration.rejects_void_promotion` resolve, restated in this
    feature's vocabulary: an explicit URL wins, else ``DATABASE_URL``, and a
    deployment that names neither is refused *by name* rather than silently doing
    nothing.  The silence is the dangerous failure here and not the refusal, and it
    is more dangerous than at the block store: a judgment that quietly did not
    happen leaves a promotion **proceeding on criteria that were never the fixed
    ones**, which is the state §13 item 7's *before* exists to make impossible.  A
    caller that must judge a promotion has to treat this refusal as a stop.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise CriteriaMismatchError(
            f"{CRITERIA_MISMATCH_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), so "
            "there is no registry row to read this promotion's recorded criteria "
            "hash from. docs/alpha-engine-prd.md §13 item 7 fixes a promotion's "
            "criteria and hashes them before the evaluation that decides them, and "
            "feature 292's comparison is against that recorded hash — a gate "
            "resolved from nothing is a refusal rather than a silent no-op, because "
            "an unjudged promotion is not a correctly-judged one (feature 292)"
        )
    return url


def rejects_mismatched_criteria(
    node_id: Any,
    criteria: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Judge one promotion's criteria — the module-level spelling of 292's act.

    The feature's sentence as one call, for the caller that wants the act without
    holding a gate — the promotion path's last line before a hypothesis is decided.
    The gate is resolved from ``database_url``, else from ``DATABASE_URL``, exactly
    as :func:`promotion.pre_register.PreRegistrations.resolve` and
    :func:`promotion.blocking.blocked_promotion` resolve theirs.

    A :class:`~promotion.errors.CriteriaMismatchError` from the gate or the
    resolution propagates unwrapped: the refusal already names the node, the two
    hashes and the repair, and re-wrapping it here would put a second message in
    front of the one an operator needs.
    """
    url = _resolved_url(database_url, env)
    return CriteriaChecks(url).rejects_mismatched_criteria(node_id, criteria)


def matches_criteria(
    node_id: Any,
    criteria: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Read one promotion's recorded criteria hash — the module-level spelling of the read.

    For the caller that holds a URL rather than a gate: an operator asking what hash
    a node was registered under, a report enumerating promotions by their recorded
    criteria.  Resolved the same way :func:`rejects_mismatched_criteria` resolves
    its gate, so the caller that judges through one spelling and reads through the
    other is reading the row the judgment was made on.

    Answers no verdict: a mismatched promotion's hash is returned as the digest it
    is, because this is the reading and not the decision.
    """
    url = _resolved_url(database_url, env)
    return CriteriaChecks(url).matches_criteria(node_id, criteria)
