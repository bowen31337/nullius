"""System rejects the merge when an epoch exceeding three promotion decisions
remains selectable.

app_spec.xml feature 356 — the "System Invariant CI Gates" category's epoch
gate — is the merge-time form of the law §13 item 4 of docs/alpha-engine-prd.md
states, quoted whole because every clause of it is load-bearing somewhere in
this file::

    Sequestered epochs are retired permanently after **3 promotion
    decisions**. Track in a ledger. When clean epochs run out, the system
    stops. That is a legitimate terminal state.

The law is enforced four times over in the Promotion & Epoch Governance
category, at four moments: ``0110_epoch_ledger`` creates the ledger the spend is
counted in (feature 105), feature 294 persists the running count against the
serving epoch, feature 295 *refuses further selection* of an epoch once it has
served the budget, and features 296 and 297 read the same boundary from the
whole-table side — the terminal stop and the depleting gauge. This sentence is
none of those. It is §13's preamble taken at its word — *"Enforce in CI, not in
code review"* — and it asks the question a merge gate can ask before any of that
machinery has run: **does this merge leave an epoch that has exceeded three
promotion decisions still selectable?**

**The subject, stated exactly.** The clause has two terms and both are judged
here. The first is the ledger's own figure: an epoch whose ``epoch_ledger`` row
states more promotion decisions served than §13 item 4's budget of
:data:`~promotion.selection.SEQUESTERED_EPOCH_BUDGET`. The second is
*selectable*, and it is the operative one: an epoch is selectable when the
merge's own judgment —
:func:`promotion.selection.rejects_further_selection`, the comparison feature
295's gate is built on — still admits its selection. The finding is the
conjunction, and the whole of what this gate refuses.

**Why the operative clause is selectability, and not the ledger's figure
alone.** This matters enough to state as a proof from the shipped code, because
the other reading — *any row stating more than three is a finding* — refuses
merges for a state the runtime already survives. The member's writers do **not**
enforce the budget:
:meth:`~promotion.pre_register.PreRegistrations.pre_register` books a node
against an epoch, :meth:`~promotion.decision.PromotionDecisions.record_decision`
closes the row, :meth:`~promotion.epoch.EpochCharges.charge` re-supplies the
count — and none of the three consults
:class:`~promotion.selection.EpochSelections`. The gate is the *caller's* step,
the one the promotion path runs before it books. So a ledger holding an epoch
that has served four, or nine, decisions is reachable through nothing but the
shipped writers, by a caller that skipped the gate; the gate's own docstring
calls that caller *"precisely a fourth promotion judged on a holdout that had
already served three."* Such a ledger is a *fact about the past*, and the epoch
on it is nonetheless **not selectable**, because feature 295 refuses
``served >= 3`` on the same row. A merge carrying that ledger ships code under
which no epoch past the budget can be selected again — which is the whole of
what this sentence asks a merge to guarantee. Refusing it would be refusing the
merge for data, and there is no datum a merge can carry that makes a correct
judgment wrong. What *can* make it wrong is the judgment: a candidate merge that
widened the budget, that weakened ``>=`` to ``>`` or ``==``, or that dropped the
raise in favour of a returned boolean, ships an epoch past the budget that
remains selectable — and that is the finding this file is built to catch. It is
caught by asking the member's own gate, per row, rather than by re-spelling its
comparison, so a merge cannot weaken both the judgment and this audit in step.

**The boundary is shared with the venue, and the two sentences meet at
equality.** Feature 295 refuses the epoch that has *reached* the budget — its
comparison is ``>=``, so the equality case is that gate's own refusal, and an
epoch at exactly three is unselectable because of it. This sentence asks about
an epoch *exceeding* three, so its first term is strict: ``served > budget``, and
the equality case is not this gate's finding. The two faces are complements over
one line, and the audit below is sound against the venue by construction:
whenever the merge's judgment refuses an epoch, no matter how far past the
budget it stands, this gate names nothing — and the epochs it *can* name are
exactly the ones the merge's judgment stopped refusing. Both halves are pinned
over the counts zero through nine, so neither boundary can drift a step without
a test going red.

**The four faces of a merge this gate judges.** A merge carries no rows, so each
face is a thing a merge *can* carry:

1. **The ledger's schema**, read from ``0110``'s own ``statements()`` and never
   retyped here — the primary key that makes one epoch one row (``0110``'s own
   words: a doubled row *"would split its served count in half, letting feature
   295's three-decision threshold read a 'clean' epoch that had already served
   its budget"*), the count column's ``NOT NULL DEFAULT 0`` that keeps *freshly
   sealed* and *never sealed* two different answers, and the flag column whose
   reader is feature 296 rather than this sentence.
2. **The charging statement**, feature 294's one ``UPDATE``, read from
   :data:`promotion.epoch._UPDATE_SQL`: the count is one column in a ``SET``
   clause and it is *re-supplied*, never incremented — ``SET served = served +
   1`` would make the ledger a second source of truth about one fact, free to
   drift from the rows it counts. A merge that made the charge a tally could
   land a figure the registry contradicts, which is a ledger this gate's audit
   would then have to trust.
3. **The judgment's boundary**, exercised through the member's own acts rather
   than read: the shipped writers spend a holdout to the budget and past it, and
   the merge's judgment is asked about each count from zero through nine. A
   merge whose comparison moved fails here even if every member test was edited
   in the same commit.
4. **The audit**, over any ledger — one the shipped writers left, one a backfill
   or a restored backup or a raw connection wrote — every epoch past the budget
   that is still selectable refuses the merge, deterministically, naming the
   epoch and its figure. The member's own store describes that author with its
   own words: a row no writer of this member produced is *"a hand that reached
   past it."*

**A count that is not a count fails closed.** SQLite's columns are dynamically
typed, so a ``promotion_decisions_served`` holding text, a fraction, an absence
or a flag is reachable through a raw connection; and the clause's first term
*is* that figure, so a row that states no count leaves the clause undecidable.
The alternative — silence — is precisely the failure these gates exist to
prevent: the operator would read *no epoch past the budget* off a ledger this
gate could not compare, and the merge would be certified on a figure nobody
derived. So an unreadable count is a finding of its own, distinct in the report
from the sentence's finding, with the repair in the ledger rather than in the
code.

**The audit writes nothing, and the refusal is the act.** There is no
"violation" row to record, no ledger column for a verdict, and the figure the
gate refused on is the figure the row already carries. A gate that could write
would be able to forge the subject of its own audit — the discipline feature
360's gate states for its own registry, and the reason the statelessness of the
judgment here is asserted statically rather than only behaviourally.

**What this gate is not, asserted as hard as what it is.** It is not feature
294's charge — the count's persistence is that act's, and this gate never
derives a count from the registry, only reads the figure the ledger holds. It is
not feature 296's terminal state: the empty ledger, and the ledger whose every
epoch is spent, are that verdict's refusals, and this sentence names an *epoch*
— one the merge left selectable — so a ledger holding no row is not this gate's
finding. It is not feature 297's depleting count either, though the gate pins
that the gauge reaches zero at exactly this boundary: the gauge reports, this
gate refuses, and they must not disagree about *when*. It is not feature 292's
``criteria_mismatch`` and reads no criteria hash; not feature 293's decision,
whose stamp it never inspects; and nothing here judges any promotion's merits —
a finding says *this merge would let a spent holdout be spent again*, never
*the promotion fails*.

**The dialect.** ``0110`` mints no id and defaults no timestamp, so its single
spelling is valid on SQLite and Postgres alike and its two branches in
``statements()`` are pinned equal below — the shape face cannot drift by
dialect. The audit reads SQLite ledgers because that is the one dialect this
workspace's stores speak (the spec's single-machine allowance); on Postgres the
same columns exist and the same comparison reads them, the finding being a
property of the columns and the judgment, not of the engine.

**Stdlib and the member's own packages, and nothing else.** The gate reads
``promotion`` — the judgment, the value, the store and the one statement — plus
``promotion.remaining`` and ``promotion.terminal`` for the two exhaustion faces
it must not disagree with, and it loads ``0110`` (and its two parents) by path
the way their runner does. It opens no connection of its own outside the
fixtures below, and never from inside a judgment.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import inspect
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import promotion as member
import pytest
from promotion import (
    EPOCH_ID_COLUMN,
    EPOCH_LEDGER_TABLE,
    PROMOTION_DECISIONS_SERVED_COLUMN,
    RETIRED_COLUMN,
    SEALED_AT_COLUMN,
    SEQUESTERED_EPOCH_BUDGET,
    EpochCharges,
    EpochSelectionError,
    EpochSelections,
    PreRegistrations,
    PromotionDecisions,
    ServingEpoch,
    rejects_further_selection,
    select_epoch,
)

# The one statement a merge carries that this gate reads as data — feature 294's
# charging ``UPDATE``, read where it lives rather than retyped here, the same
# discipline the registry gate applies to ``pre_register._INSERT_SQL`` and
# ``decision._UPDATE_SQL``. A store has no public ``statements()`` seam the way
# a migration does: these module constants ARE the statements, and a restatement
# of their SQL in this file would let the gate agree with itself and pass
# anything.
from promotion.epoch import _UPDATE_SQL as CHARGE_UPDATE_SQL

# The exhaustion clause's two readers, held to *this* boundary below — §13 item
# 4's "when clean epochs run out, the system stops" and its depleting gauge.
# Imported rather than restated for the reason the whole-table verdict itself
# states about the charge store: a gate that re-derived the count would be a
# second reading of one fact, free to disagree with the one the runtime reports.
from promotion.remaining import clean_epochs_remaining
from promotion.terminal import blocks_when_no_clean_epoch_remains

# ── The schema's owners, loaded the way their runner loads them ──────────────

#: tests/invariants/test_epoch_selection_budget.py → tests/invariants → tests →
#: the repository root, whose migrations/ tree holds the DDL this gate judges.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The migration tree's versions directory — the one place a merge's DDL lives.
#: The gate reads it rather than a restatement, so DDL edited in a candidate
#: merge is judged as it will ship, not as this file remembers it.
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: ``0110`` is the file that declares ``epoch_ledger`` — the columns the finding
#: is read off, and the primary key that keeps one epoch to one row. The id is
#: the file's position in the assembled chain and not its spec feature index
#: (``0110``'s own docstring records the discrepancy: the feature is 105, the
#: revision is where the file landed), which is why the gate loads it by the id
#: the tree actually keeps it under rather than by an index.
LEDGER_REVISION = "0110_epoch_ledger"

#: The registry and the node table — the two foreign-key parents this gate's
#: writers need before a promotion decision can be recorded at all. ``node``'s
#: owner is loaded for its DDL's own columns (``campaign_id`` is plain ``NOT
#: NULL`` with no reference, so seating a node needs no campaign row);
#: ``promotion_registry``'s owner is loaded because the writers below need a
#: registry to record decisions into.
NODE_REVISION = "0118_node_table"
REGISTRY_REVISION = "0108_forward_and_universe_tables"

#: The chain, in the order the migrations must run: ``0108`` declares both
#: parents in its ``REQUIRES_TABLES``, so it lands last. On SQLite the order is
#: a tolerance rather than a hard requirement (the parent is resolved when a row
#: is written, not at ``CREATE TABLE``), which is exactly why the gate runs the
#: real order instead of trusting the engine to complain.
CHAIN: tuple[str, ...] = (NODE_REVISION, LEDGER_REVISION, REGISTRY_REVISION)


def _load_migration(revision: str) -> ModuleType:
    """Load ``revision`` from the versions directory, by path.

    ``migrations/`` is not a package and is not on ``sys.path``; a runner loads
    a migration by path the same way, so loading it by path here is the shape a
    migration is *built* to be used in rather than a workaround. A missing file
    fails with the path in the message, because the one failure a gate should
    never have to guess at is "the schema's owner moved" — a gate that silently
    skipped the DDL would pass for a merge that shipped anything.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this gate judges the migration that "
            "owns epoch_ledger and the trees the writers walk, so it needs the "
            "schema's owners to be where the tree keeps them"
        )
    spec = importlib.util.spec_from_file_location(f"_invariants_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The schema's owners, loaded once at collection — reading them is a
#: precondition of every judgement below, not a behaviour any one test chooses.
MIGRATIONS: dict[str, ModuleType] = {
    revision: _load_migration(revision) for revision in CHAIN
}

#: The migration that owns the ledger — the one whose DDL the shape face judges.
LEDGER_MIGRATION = MIGRATIONS[LEDGER_REVISION]


# ── The columns and the row the finding lives on ─────────────────────────────

#: The four columns the spec's schema block states for this table, in its order,
#: restated as data rather than imported from the member: the discipline the
#: member's own conftest states for its constants — a suite that imported them
#: would agree with the member by construction and pin nothing. A fifth column
#: would be a second place the spend is recorded; a missing one would drop the
#: clause's first term.
LEDGER_COLUMNS: tuple[str, ...] = (
    EPOCH_ID_COLUMN,
    SEALED_AT_COLUMN,
    PROMOTION_DECISIONS_SERVED_COLUMN,
    RETIRED_COLUMN,
)

#: The one statement the audit runs: the whole ledger, in the table's key order.
#: A bare ``SELECT`` over the two columns the clause is read off — spelled once
#: so the gate that reads the record is never the hand that writes one, and
#: ordered by the epoch's own name so two audits of one ledger are comparable.
AUDIT_SQL = (
    f"SELECT {EPOCH_ID_COLUMN}, {PROMOTION_DECISIONS_SERVED_COLUMN} "
    f"FROM {EPOCH_LEDGER_TABLE} ORDER BY {EPOCH_ID_COLUMN}"
)

#: The two kinds of finding this gate reports, as data, so a refusal names what
#: it is about rather than leaving an operator to infer it from a tuple's shape.
#: The first is the sentence's own finding — an epoch past the budget that the
#: merge's judgment still admits; the second is the undecidable case above, a
#: row whose served figure is not a count of decisions at all.
STILL_SELECTABLE = "still-selectable"
UNREADABLE_COUNT = "served-count-unreadable"

#: A finding: the epoch's name, the served figure in the row's own spelling, and
#: which of the two kinds above it is. The figure is carried so the operator
#: reads the break off the table rather than re-deriving it.
Finding = tuple[str, str, str]

#: The whole-table audit's own boundary data — the counts the two-sided law
#: below is pinned over: zero through the budget itself, then figures past it
#: (the smallest overshoot, the next two, and a hand's edit far beyond anything
#: the writers could derive).
AUDITED_COUNTS: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 9)

#: The gate's epochs and nodes. Every node is seated as a framework row so a
#: hand past the store writes a row that is *about* the finding and not about a
#: foreign key; every epoch is seated as the sealing process's row, because the
#: remaining clean-epoch gauge below judges exactly those rows.
GATE_CAMPAIGN_ID = "22222222-2222-4222-8222-222222222222"
GATE_EPOCH_ID = "epoch-2026-03"
OTHER_EPOCH_ID = "epoch-2026-04"
THIRD_EPOCH_ID = "epoch-2026-05"
EPOCH_SEALED_AT = "2026-02-01T00:00:00+00:00"

#: The instants the shipped writers work over — sealing's row is the fixture's,
#: these two are the registration and the decision, named so an assertion reads
#: as a statement about stamps rather than about literals buried in a call.
REGISTERED_AT = dt.datetime(2026, 3, 1, 12, 0, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, 9, 30, tzinfo=dt.UTC)

#: The six-term criteria document the shipped pre-registration records — §12's
#: M3 exit figures as the member's own suite reads them. This gate never looks
#: at the hash; a well-formed body is all the writers below need.
CRITERIA_DOCUMENT: dict[str, Any] = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": 90,
}


def _node(index: int) -> str:
    """A distinct, well-formed node identity — one per promotion decision spent.

    Deterministic rather than random so a failure names the same node on every
    run, and UUID-shaped because that is what the column holds and what feature
    291's validator reads.
    """
    return f"{index:08d}-1111-4111-8111-111111111111"


# ── The finding: a pure function of the rows and the merge's own judgment ────


def _count_of(value: Any) -> int | None:
    """``value`` as a count of promotion decisions, or ``None`` when it is not one.

    The member's own rule, taken as a *question* rather than as a refusal so the
    audit can report the row instead of dying on it: a non-negative ``int``,
    with ``bool`` refused first — ``True`` is ``1`` in Python, and a flag where a
    count belongs would silently answer one decision nobody recorded. ``None``
    is the caller's signal that the clause's first term is undecidable, which is
    a finding of its own rather than a clean row.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _spelling(value: Any) -> str:
    """A served figure as the row spelled it, for the refusal to name.

    ``repr`` rather than ``str``: the values this renders are the ones that are
    *not* counts, and a text ``'three'`` must not read as a figure in a report
    an operator is matching against the table.
    """
    return repr(value)


def refuses_selection(epoch_id: Any, promotion_decisions_served: Any) -> bool:
    """Does the merge's own judgment refuse this epoch's selection?

    Feature 295's test, asked as a question and answered as a boolean: ``True``
    exactly when :func:`promotion.selection.rejects_further_selection` raises its
    :class:`~promotion.errors.EpochSelectionError`, ``False`` when it returns.
    The *judgment* is used rather than restated — a gate that spelled its own
    ``served >= budget`` would agree with itself and could pass a merge whose
    gate had been weakened, which is the whole subject of this file — and the
    raise is the thing being read, so a merge that turned the refusal into a
    returned boolean is caught by the same call.

    This is the second term of the sentence's clause, and it is what makes the
    audit sound against the venue: an epoch this returns ``True`` for is an
    epoch feature 295 will not let a caller book, so it does not *remain
    selectable* however far past the budget it stands.
    """
    try:
        rejects_further_selection(epoch_id, promotion_decisions_served)
    except EpochSelectionError:
        return True
    return False


def admits_everything(epoch_id: Any, promotion_decisions_served: Any) -> bool:
    """A judgment that refuses nothing — the merge this gate exists to catch.

    The stand-in the non-vacuity cases below run against: a merge whose gate had
    stopped refusing would ship this judgment, and the epochs this file's audit
    names under it are the sentence's finding *as data*. Spelling it as a
    function rather than monkeypatching the member's keeps the mutation in plain
    sight — the argument for what a weakened merge does to a ledger, stated
    where a reader can check it rather than hidden in a fixture.
    """
    return False


def selectable_past_budget(
    rows: Iterable[tuple[Any, Any]],
    *,
    refuses: Callable[[Any, Any], bool] = refuses_selection,
) -> tuple[Finding, ...]:
    """Every epoch past the budget that remains selectable — the gate's finding.

    The sentence's clause, evaluated over ``(epoch_id, served)`` pairs exactly as
    the audit read them: a row is a finding when its served figure **exceeds**
    §13 item 4's budget *and* the merge's judgment does not refuse the epoch's
    selection. Both terms are the sentence's: the first is *"an epoch exceeding
    three promotion decisions"*, the second is *"remains selectable"*, and
    dropping either would answer a different question — the figure alone is a
    fact about the past that the shipped writers can produce with nothing but
    their own hands, and the refusal alone is feature 295's runtime verdict,
    which is exactly what a merge could weaken without any ledger changing.

    ``refuses`` is the merge's judgment, injectable so the *audit itself* can be
    shown non-vacuous: with the shipped judgment no finding is reachable on a
    correctly-gated merge, so a suite that could only ever call the real judgment
    would be pinning silence. The weakened-judgment cases below drive this
    argument with a stand-in that admits everything, which is what a merge whose
    comparison had moved *is* from the ledger's side — and the epochs it then
    names are exactly the ones past the budget, no more and no fewer.

    Refuses nothing and writes nothing: the answer is the tuple of findings, each
    ``(epoch_id, served-as-spelled, kind)``, sorted by the epoch's name — the
    deterministic, operator-facing form of the refusal, the way the registry
    gate names each lying row beside both stamps. Empty means no epoch on the
    ledger exceeds the budget and remains selectable; the merge stands.

    A row whose served figure is not a count of decisions is a finding of its own
    (:data:`UNREADABLE_COUNT`), judged **before** the comparison, because the
    figure *is* the clause's first term and a row that states none leaves the
    clause undecidable rather than clean. SQLite's dynamic typing makes the state
    reachable through a raw connection, and reading it as clear would be the
    silence these gates exist to prevent: the operator would be told *no epoch
    past the budget* about a ledger nobody could compare.
    """
    findings: list[Finding] = []
    for epoch_id, served in rows:
        epoch = epoch_id if isinstance(epoch_id, str) else _spelling(epoch_id)
        count = _count_of(served)
        if count is None:
            findings.append((epoch, _spelling(served), UNREADABLE_COUNT))
            continue
        if count <= SEQUESTERED_EPOCH_BUDGET:
            continue
        if refuses(epoch, count):
            continue
        findings.append((epoch, str(count), STILL_SELECTABLE))
    return tuple(sorted(findings))


def audit_rows(connection: sqlite3.Connection) -> tuple[tuple[Any, Any], ...]:
    """The ledger's rows, as ``(epoch_id, served)`` pairs — the audit's one read.

    :data:`AUDIT_SQL` and nothing else: a bare ``SELECT`` over the two columns
    the clause is read off, in the table's key order. The gate reads the table
    raw rather than through the member's own ``epochs`` listing so the code under
    judgement cannot confirm itself — the same discipline the registry gate
    states for its own raw read — and the listing cross-check below is what keeps
    the two readings honest with each other: a merge that hid a spent epoch from
    the listing auditors are told to read would defeat every reader but this one.
    """
    cursor = connection.execute(AUDIT_SQL)
    try:
        return tuple(cursor.fetchall())
    finally:
        cursor.close()


def merge_refusal(
    connection: sqlite3.Connection,
    *,
    refuses: Callable[[Any, Any], bool] = refuses_selection,
) -> tuple[Finding, ...]:
    """The gate itself: findings that refuse the merge over ``connection``'s ledger.

    The merge-time form of feature 356's sentence and of §13 item 4's budget,
    computed from the rows as they were left and never by writing one — the
    record is the thing being judged, and a gate that could add to it would be
    able to forge the subject of its own audit.
    """
    return selectable_past_budget(audit_rows(connection), refuses=refuses)


# ── The shape face: the DDL and the one statement a merge carries ────────────


def _ledger_ddl(dialect: str) -> str:
    """The ``CREATE TABLE`` the owning migration declares, for ``dialect``.

    Read from the migration's own ``statements()`` — the property that makes a
    migration reviewable at all — never retyped here, so the shape the gate
    judges is the shape that ships. Fails by name if the revision stopped
    declaring the ledger, because a gate that silently judged an absent table
    would pass for a merge that dropped its own subject.
    """
    for statement in LEDGER_MIGRATION.statements(dialect):
        if f"CREATE TABLE IF NOT EXISTS {EPOCH_LEDGER_TABLE}" in statement:
            return statement
    raise AssertionError(
        f"{LEDGER_REVISION} declares no {EPOCH_LEDGER_TABLE} table for dialect "
        f"{dialect!r}; this gate judges the columns the spend is counted in, so "
        "it needs the table to be where its owner keeps it"
    )


def column_definitions(ddl: str) -> dict[str, str]:
    """The ``CREATE TABLE`` body as a column → definition mapping.

    The DDL this workspace's migrations write is one column per line inside the
    parentheses — the spelling ``0110`` uses — so the body is read line by line
    and each line's first word is the column. Definitions are kept whole (type,
    ``NOT NULL``, ``DEFAULT`` and all, uppercased by the caller when compared)
    because the properties the shape face judges live in the definition and not
    in the name, exactly as the registry gate reads the same file family.
    """
    body = ddl.split("(", 1)[1].rsplit(")", 1)[0]
    definitions: dict[str, str] = {}
    for line in body.splitlines():
        stripped = line.strip().rstrip(",").strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        definitions[parts[0].lower()] = parts[1].strip() if len(parts) > 1 else ""
    return definitions


def set_clause(statement: str) -> str:
    """The ``SET`` clause of an ``UPDATE``, as text — the write's whole boundary.

    The spans this file parses: the columns a charge can change, and the value it
    changes them to. Both are read from the clause rather than from the whole
    statement, because ``epoch_id`` appears in the ``WHERE`` of every write here
    and a whole-statement substring check would read the key for the value.
    """
    return statement.split("SET", 1)[1].split("WHERE", 1)[0]


def set_columns(statement: str) -> tuple[str, ...]:
    """The column names an ``UPDATE``'s ``SET`` clause writes."""
    return tuple(
        assignment.split("=", 1)[0].strip()
        for assignment in set_clause(statement).split(",")
    )


def assignment_value(statement: str, column: str) -> str:
    """The right-hand side one ``SET`` assignment writes to ``column``.

    Read as text so the gate can judge *what shape of value* the charge writes: a
    bound placeholder is the derivation arriving from the caller, while the
    column's own name on the right-hand side would be the increment feature 294's
    docstring refuses — *"``SET served = served + 1`` would make the ledger a
    second source of truth about one fact, free to drift from the rows it
    counts."*
    """
    for assignment in set_clause(statement).split(","):
        name, _, value = assignment.partition("=")
        if name.strip() == column:
            return value.strip()
    raise AssertionError(f"{statement} writes no {column} in its SET clause")


# ── The ledger a merge's writers leave, brought up the chain's way ───────────


def _connection(path: Path) -> sqlite3.Connection:
    """Open the ledger's database with its foreign keys enforced.

    The pragma is SQLite's own honest default-flip every store in this member
    performs: a hand past the store writes through the same constraint the store
    writes through, so a hand-written row is a row about the finding and not
    about a foreign key nobody checked.
    """
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _seat(
    connection: sqlite3.Connection,
    *,
    epochs: Iterable[str] = (),
    nodes: Iterable[str] = (),
) -> None:
    """Seat the parent rows the promotion member refuses to manufacture.

    A node's row is the discovery loop's write and an epoch's row is the sealing
    process's — neither is the promotion member's to invent, and the member's own
    suite seats them the same way. ``node``'s ``campaign_id`` is a plain ``NOT
    NULL`` column with no reference (``0118`` declares none), so no campaign row
    is needed for a node to exist; ``sealed_at`` has no default because
    ``0110``'s own words say *the row is the sealing event*.
    """
    for epoch in epochs:
        connection.execute(
            "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
            (epoch, EPOCH_SEALED_AT),
        )
    for node in nodes:
        connection.execute(
            "INSERT INTO node (id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?)",
            (node, GATE_CAMPAIGN_ID, "macro", 1),
        )


def _path_of(url: str) -> Path:
    """The file behind a ``sqlite:///`` store URL — the path the audit reads.

    The member's own URL spelling, unspelled: ``sqlite:///`` plus the absolute
    path. The gate needs it because a node's row has to be seated through the
    *same* database the stores write to, and the stores speak URLs while
    ``sqlite3`` speaks paths — the translation the member's own translator
    performs, done here for the fixture's seating rather than for a read.
    """
    prefix = "sqlite:///"
    assert url.startswith(prefix), url
    return Path(url[len(prefix) :])


def _seat_nodes(url: str, indices: Iterable[int]) -> None:
    """Seat the node rows the decisions about to be recorded will hang off.

    A node's row is the discovery loop's write, not this member's — the same
    stance the member's own suite takes when it inserts the two parents its
    writers check before either will proceed. Without the row the pre-registration
    refuses by name (``promotion_registry.node_id`` is a foreign key), so the
    seating is a precondition of the spend rather than a convenience.
    """
    with closing(_connection(_path_of(url))) as connection, connection:
        _seat(connection, nodes=(_node(index) for index in indices))


def _spend_decisions(
    url: str, epoch_id: str, decisions: int, *, first: int = 0
) -> None:
    """Spend ``decisions`` promotion decisions against one epoch — the real acts.

    Three acts per decision, and none of them consults the selection gate:
    feature 291 books the node against the epoch (the sealing process's row is
    the fixture's, before either), feature 293 stamps the decision, and feature
    294 re-supplies the count. That the *writers* do not enforce §13 item 4's
    budget is not a hole in this fixture but the fact the whole file turns on:
    the gate is the caller's step, so a ledger past the budget is a state the
    shipped code can produce — and the epoch on it is still unselectable,
    because the judgment refuses it.

    ``first`` offsets the node indices so one ledger can hold several epochs'
    worth of decisions without two rows sharing an identity.
    """
    registrations = PreRegistrations(url)
    decisions_store = PromotionDecisions(url)
    charges = EpochCharges(url)
    _seat_nodes(url, range(first, first + decisions))
    for index in range(first, first + decisions):
        node = _node(index)
        registrations.pre_register(
            node, epoch_id, CRITERIA_DOCUMENT, pre_registered_at=REGISTERED_AT
        )
        decisions_store.record_decision(node, decided_at=DECIDED_AT)
        charges.charge(node)


def _hand_written_count(
    connection: sqlite3.Connection, epoch: str, value: Any
) -> None:
    """Set one epoch's served figure past the stores — the hand that reached past.

    ``0110`` declares the column ``INT NOT NULL DEFAULT 0`` and this member only
    ever writes a derived integer into it, so the values this helper lands are
    the ones no writer here could produce: a figure the charge did not derive, in
    a column SQLite's dynamic typing accepts anyway. The same update spells every
    audited count below, so the law can be pinned over the whole range without
    paying for a promotion per step.
    """
    connection.execute(
        f"UPDATE {EPOCH_LEDGER_TABLE} "
        f"SET {PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
        f"WHERE {EPOCH_ID_COLUMN} = ?",
        (value, epoch),
    )


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    """A ledger database the versioned tree brought up, in the chain's order.

    The deployment shape where the migrations got there first: the schema is the
    owners', run as their own ``statements("sqlite")`` in :data:`CHAIN`'s order —
    the order :data:`promotion.schema.MIGRATION_ORDER` states, restated here as
    data so the gate asserts *that* order rather than importing it. The stores'
    own bootstraps are all ``IF NOT EXISTS``, so a store opening this database
    converges on it and changes nothing.
    """
    path = tmp_path / "epoch-ledger.db"
    with closing(_connection(path)) as connection, connection:
        for revision in CHAIN:
            for statement in MIGRATIONS[revision].statements("sqlite"):
                connection.execute(statement)
        _seat(connection, epochs=(GATE_EPOCH_ID, OTHER_EPOCH_ID, THIRD_EPOCH_ID))
    return path


@pytest.fixture
def ledger_url(ledger_path: Path) -> str:
    """The store-facing URL of the fixture's ledger — the same file, by name.

    The URL spelling the member's own suite uses: ``sqlite:///`` plus the
    absolute path, which the store's translator resolves back to that same
    absolute file — the one spelling that makes the writers' database and the
    audit's raw read the same ledger.
    """
    return f"sqlite:///{ledger_path}"


def _raw_row(path: Path, epoch: str) -> dict[str, Any]:
    """One epoch's raw ledger row, as the table holds it — never the store's word.

    A refusal that left a column moved would be invisible to an assertion made
    against the store's own testimony, so every "nothing moved" claim below is
    made here, on the file the writers wrote.
    """
    with closing(_connection(path)) as connection:
        cursor = connection.execute(
            f"SELECT {', '.join(LEDGER_COLUMNS)} FROM {EPOCH_LEDGER_TABLE} "
            f"WHERE {EPOCH_ID_COLUMN} = ?",
            (epoch,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    assert row is not None, f"{EPOCH_LEDGER_TABLE} holds no row for {epoch}"
    return dict(zip(LEDGER_COLUMNS, row, strict=True))


def _refuse_to_select(url: str, epoch: str) -> None:
    """Book nothing: assert the venue's judgment refuses this epoch's selection.

    The composed store — the one the factory hands out, over the charge store the
    same URL wires — asked the same question the pure judgment answers, so the
    two spellings of feature 295 cannot disagree about which epochs are
    selectable. A silent return here is a failure of this file's own premise, so
    the assertion is the call itself.
    """
    with pytest.raises(EpochSelectionError):
        EpochSelections(EpochCharges(url)).select(epoch)


# ── The gate reads the budget the merge carries ──────────────────────────────


class TestTheGateReadsTheBudgetTheMergeCarries:
    """The gate judges the schema, the charging statement and the judgment's own
    boundary — as data, without trusting a member suite a candidate merge might
    have edited in the same commit."""

    def test_the_gate_reads_the_migration_that_owns_the_ledger(self) -> None:
        # The ledger's own owner — the revision that declares the columns the
        # spend is counted in — loaded by path the way a runner loads it, never a
        # restatement typed into this file. A gate that re-typed the DDL it
        # judged could agree with itself and pass anything; this one fails the
        # moment the owner moves or changes.
        assert LEDGER_MIGRATION.REVISION == LEDGER_REVISION
        assert EPOCH_LEDGER_TABLE in LEDGER_MIGRATION.TABLES

    @pytest.mark.parametrize("dialect", ["sqlite", "other"])
    def test_the_ledger_the_merge_ships_carries_the_four_columns(
        self, dialect: str
    ) -> None:
        # The spec's schema block, as the DDL spells it: exactly these four
        # columns, in this order. A fifth column would be a second place the
        # spend is recorded; a missing one would drop the clause's first term —
        # and the order is the block's, so a reader diffing the file against
        # app_spec.xml reads the same list twice.
        assert tuple(column_definitions(_ledger_ddl(dialect))) == LEDGER_COLUMNS

    @pytest.mark.parametrize("dialect", ["sqlite", "other"])
    def test_the_one_row_per_epoch_key_holds_on_the_database_tests_run_on(
        self, dialect: str
    ) -> None:
        # ``0110``'s own argument, pinned as the shape that carries it: the
        # feature's "unique constraint on epoch_id" is the primary key, and the
        # column spells ``NOT NULL`` where the spec's block writes the bare key
        # because SQLite's rowid tables accept NULL keys — and several of them,
        # NULLs comparing distinct. A duplicate epoch row would split its served
        # count, and this sentence's clause reads exactly that count: a gate that
        # let the key weaken would be judging a figure two rows each held half
        # of.
        key = column_definitions(_ledger_ddl(dialect))[EPOCH_ID_COLUMN].upper()
        assert "TEXT" in key
        assert "NOT NULL" in key
        assert "PRIMARY KEY" in key

    @pytest.mark.parametrize("dialect", ["sqlite", "other"])
    def test_the_count_column_states_a_figure_and_keeps_fresh_apart_from_absent(
        self, dialect: str
    ) -> None:
        # The clause's first term, as the column declares it: an integer, never
        # null, defaulting to zero. ``0110``'s own words for the default are the
        # invariant — *"a freshly sealed epoch has served zero decisions (a 0 to
        # record, not an absence — feature 295 budgets on exactly this column)"*
        # — and a ``NULL``-able count would let this gate's audit read an epoch
        # nobody can budget as an epoch that is clean.
        count = column_definitions(_ledger_ddl(dialect))[
            PROMOTION_DECISIONS_SERVED_COLUMN
        ].upper()
        assert "INT" in count
        assert "NOT NULL" in count
        assert "DEFAULT 0" in count

    def test_the_two_dialect_branches_declare_one_ledger(self) -> None:
        # ``0110`` mints no id and defaults no timestamp, so its single spelling
        # is valid on SQLite and Postgres alike and the argument selects nothing.
        # The gate pins the parity rather than assuming it: a merge that forked
        # the ledger's shape by dialect would ship one audit's worth of columns
        # on production and another under CI.
        assert _ledger_ddl("sqlite") == _ledger_ddl("other")

    def test_the_charging_statement_writes_the_count_and_nothing_else(self) -> None:
        # Feature 294's one statement, read as merge-carried data: the ``SET``
        # names exactly the count. ``sealed_at`` and ``retired`` are values this
        # write has no clause for — a charge that could mint a sequestration
        # instant or pronounce a retirement would be fabricating the one fact
        # this member must never mint, and would make the ledger's own testimony
        # about *when* an epoch was sealed a function of the last promotion.
        assert set_columns(CHARGE_UPDATE_SQL) == (PROMOTION_DECISIONS_SERVED_COLUMN,)
        assert SEALED_AT_COLUMN not in set_clause(CHARGE_UPDATE_SQL)
        assert RETIRED_COLUMN not in set_clause(CHARGE_UPDATE_SQL)

    def test_the_charging_statement_re_supplies_a_derived_figure(self) -> None:
        # Why the charge is not an increment, as the statement's shape states it:
        # the assignment's right-hand side is the caller's bound value — the
        # count feature 294 derived from the closed registry rows — and not the
        # column's own name. ``SET served = served + 1`` would make the ledger a
        # second source of truth about one fact, free to drift from the rows it
        # counts, and a retried charge would double-count a decision that
        # happened once; this sentence's audit would then be reading figures
        # nobody could reproduce.
        value = assignment_value(CHARGE_UPDATE_SQL, PROMOTION_DECISIONS_SERVED_COLUMN)
        assert value == "?"
        assert PROMOTION_DECISIONS_SERVED_COLUMN not in value

    def test_the_charging_statement_names_the_ledger_and_keys_by_the_epoch(
        self,
    ) -> None:
        # The statement's subject and its key: the write lands on the ledger the
        # audit reads, and its ``WHERE`` names the epoch's own name — the primary
        # key — rather than a rowid or a range. A charge that wrote several rows
        # would not be this sentence's subject at all; one that keyed on
        # something else could bill an epoch nobody booked.
        assert EPOCH_LEDGER_TABLE in CHARGE_UPDATE_SQL
        assert EPOCH_ID_COLUMN in CHARGE_UPDATE_SQL.split("WHERE", 1)[1]

    def test_the_budget_is_the_prds_own_number_read_from_its_one_home(self) -> None:
        # §13 item 4's "3 promotion decisions", and the member's one home for it.
        # The gate reads the constant rather than spelling the number, so a merge
        # that moved the budget to four moves every witness below with it — and
        # the witnesses are stated against the constant for exactly that reason,
        # so this suite cannot pass by agreeing with itself about "three".
        assert SEQUESTERED_EPOCH_BUDGET == 3
        assert member.SEQUESTERED_EPOCH_BUDGET is SEQUESTERED_EPOCH_BUDGET

    def test_the_judgment_the_audit_reads_is_the_members_own(self) -> None:
        # The gate does not restate feature 295's comparison — it *asks* it, so
        # the judgment the audit reads and the judgment the venue refuses on
        # cannot be two spellings of one line, free to disagree. Structural
        # rather than behavioural, because a merge could otherwise weaken both in
        # step and leave this file's behaviour unchanged: the audit would agree
        # with whatever comparison shipped.
        assert member.rejects_further_selection is rejects_further_selection
        assert member.EpochSelectionError is EpochSelectionError
        source = inspect.getsource(refuses_selection)
        assert "rejects_further_selection" in source
        assert "SEQUESTERED_EPOCH_BUDGET" not in source

    def test_the_finding_is_decidable_from_the_rows_and_the_judgment(self) -> None:
        # The evaluator's input is the rows and the judgment and nothing else —
        # the same static discipline the registry gate applies to its own
        # evaluator: the source of the judgement touches nothing that could open,
        # drive or settle a connection. A gate that had to write to judge would
        # be able to forge the subject of its own audit, and one that had to
        # drive the writers would be judging the writers rather than the record
        # they leave.
        for judgement in (selectable_past_budget, refuses_selection, _count_of):
            tree = ast.parse(inspect.getsource(judgement))
            database_names = [
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr
                in {
                    "connect",
                    "cursor",
                    "execute",
                    "executescript",
                    "commit",
                    "rollback",
                }
            ]
            assert database_names == [], judgement.__name__

    def test_the_audits_boundary_is_the_members_number_and_not_a_literal(self) -> None:
        # The comparison reads §13 item 4's budget from its one home; a literal
        # would be a second place the number lives, free to disagree with the
        # constant the venue refuses on. Asserted on the syntax tree rather than
        # on the text, so the prose above cannot satisfy it.
        tree = ast.parse(inspect.getsource(selectable_past_budget))
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        ]
        assert literals == []
        assert "SEQUESTERED_EPOCH_BUDGET" in inspect.getsource(selectable_past_budget)


# ── A merge whose epochs stop at the budget stands ───────────────────────────


class TestAMergeWhoseEpochsStopAtTheBudgetStands:
    """The shipped writers, exercised once, leave a ledger on which nothing past
    the budget remains selectable — so the merge stands by construction."""

    def test_a_ledger_of_clean_epochs_is_not_refused(self, ledger_path: Path) -> None:
        # The ordinary deployment: epochs sealed and never spent. Nothing on
        # these rows exceeds the budget, and a gate that refused them would be
        # refusing every merge before its first promotion. The audit is pinned
        # non-vacuous — it saw three rows and found nothing on them — because a
        # gate that read an empty ledger would answer this the same way.
        with closing(_connection(ledger_path)) as connection:
            assert audit_rows(connection) == (
                (GATE_EPOCH_ID, 0),
                (OTHER_EPOCH_ID, 0),
                (THIRD_EPOCH_ID, 0),
            )
            assert merge_refusal(connection) == ()

    def test_an_epoch_that_has_served_the_budget_is_not_the_finding(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The boundary, from the ledger's side: the writers spend the epoch's
        # whole budget — three bookings, three decisions, three charges — and the
        # count lands at three, read raw. The merge is *not* refused, and the
        # reason is the sentence's own second term: feature 295 refuses this
        # epoch's further selection (``>=``, its own boundary), so it does not
        # remain selectable however exactly it meets the budget. The equality
        # case is the venue's refusal and not this gate's finding — the two
        # sentences meeting at one line, pinned from both sides in this file.
        _spend_decisions(ledger_url, GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET)
        assert (
            _raw_row(ledger_path, GATE_EPOCH_ID)[PROMOTION_DECISIONS_SERVED_COLUMN]
            == SEQUESTERED_EPOCH_BUDGET
        )
        _refuse_to_select(ledger_url, GATE_EPOCH_ID)
        assert refuses_selection(GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET) is True
        with closing(_connection(ledger_path)) as connection:
            assert merge_refusal(connection) == ()

    def test_an_epoch_past_the_budget_is_not_refused_while_the_gate_refuses_it(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The load-bearing case of the whole file, and the one that decides what
        # this sentence means. The writers spend a fourth decision — reachable,
        # because none of them consults the selection gate: the gate is the
        # *caller's* step, and a caller that skipped it is exactly the fourth
        # promotion feature 295's docstring describes. So a ledger past the
        # budget is a state the shipped code produces, and the epoch on it is
        # nonetheless unselectable — the judgment refuses four on the same ``>=``
        # it refuses three on. The merge is not refused, because a merge cannot
        # be refused for data its own judgment already handles.
        past = SEQUESTERED_EPOCH_BUDGET + 1
        _spend_decisions(ledger_url, GATE_EPOCH_ID, past)
        with closing(_connection(ledger_path)) as connection:
            rows = audit_rows(connection)
            refusal = merge_refusal(connection)
        assert rows == (
            (GATE_EPOCH_ID, past),
            (OTHER_EPOCH_ID, 0),
            (THIRD_EPOCH_ID, 0),
        )
        assert refusal == ()
        _refuse_to_select(ledger_url, GATE_EPOCH_ID)

    def test_the_spend_the_audit_walks_is_reachable_through_the_shipped_writers(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # Why the case above is not a hand's edit: the writers *derive* the count
        # from the closed registry rows, so the raw ledger figure and the
        # registry's own tally agree — the fourth decision is recorded, and
        # feature 294's charge re-supplied the figure that counted it. A gate that
        # treated every figure past the budget as a backfill would be accusing the
        # member's own writers of forging their own ledger.
        past = SEQUESTERED_EPOCH_BUDGET + 1
        _spend_decisions(ledger_url, GATE_EPOCH_ID, past)
        # The last node's charge is asked again, so the answer is the *standing*
        # row rather than a fresh advance: the derivation recomputes the same
        # figure the registry already states.
        standing, advanced = EpochCharges(ledger_url).charge(_node(past - 1))
        assert advanced is False  # a re-charge: the figure is already derived
        assert standing.promotion_decisions_served == past
        assert (
            _raw_row(ledger_path, GATE_EPOCH_ID)[PROMOTION_DECISIONS_SERVED_COLUMN]
            == standing.promotion_decisions_served
        )
        with closing(_connection(ledger_path)) as connection:
            assert merge_refusal(connection) == ()

    def test_the_listing_the_member_ships_for_this_audit_enumerates_the_same_rows(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # Feature 294 ships ``epochs()`` as the whole-table read every consumer of
        # §13 item 4 judges through. The gate reads the table raw — the code under
        # judgement must not confirm itself — and this cross-check keeps the two
        # readings honest with each other: on a ledger the shipped writers left,
        # the listing and the raw audit enumerate the same epochs with the same
        # counts. A merge that hid a spent epoch from the listing would defeat
        # every reader who trusted it, and would be caught here.
        _spend_decisions(ledger_url, GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET + 1)
        _spend_decisions(ledger_url, OTHER_EPOCH_ID, 1, first=100)
        listing = EpochCharges(ledger_url).epochs()
        with closing(_connection(ledger_path)) as connection:
            rows = audit_rows(connection)
        assert [
            (record.epoch_id, record.promotion_decisions_served)
            for record in listing
        ] == [(row[0], row[1]) for row in rows]
        assert len(rows) == 3

    def test_the_clean_remainder_falls_by_one_per_epoch_spent(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The gauge the sentence's second clause leans on, read over the ledger
        # the writers left rather than over constructed values: three sealed
        # epochs are three clean ones, and spending one to its budget leaves two —
        # so a ledger this gate passes is one where exhaustion is still visible as
        # a falling count, which is the whole reason the budget is a *ledger* fact
        # and not a per-call argument.
        assert clean_epochs_remaining(EpochCharges(ledger_url).epochs()) == 3
        _spend_decisions(ledger_url, GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET)
        assert clean_epochs_remaining(EpochCharges(ledger_url).epochs()) == 2
        with closing(_connection(ledger_path)) as connection:
            assert merge_refusal(connection) == ()


# ── A merge whose epoch past the budget is still selectable is refused ───────


class TestAMergeWhoseEpochPastTheBudgetIsStillSelectableIsRefused:
    """Any epoch past the budget that the merge's own judgment still admits
    refuses the merge, whatever authored the ledger — and the shipped judgment
    admits none of them, which is why the shipped merge stands."""

    @pytest.mark.parametrize("served", [c for c in AUDITED_COUNTS if c > 3])
    def test_a_past_budget_epoch_a_weakened_judgment_admits_is_refused(
        self, served: int
    ) -> None:
        # The sentence's finding, stated over data: an epoch whose row exceeds
        # the budget and whose selection the merge's judgment does not refuse. The
        # judgment here is the *weakened* one — a merge whose comparison had
        # moved, or whose budget had been widened, ships exactly this — and the
        # finding is then the row itself, named with its figure so the operator
        # reads the break off the ledger rather than re-deriving it.
        assert selectable_past_budget(
            ((GATE_EPOCH_ID, served),), refuses=admits_everything
        ) == ((GATE_EPOCH_ID, str(served), STILL_SELECTABLE),)

    @pytest.mark.parametrize("served", list(AUDITED_COUNTS))
    def test_the_shipped_judgment_admits_no_epoch_at_or_past_the_budget(
        self, served: int
    ) -> None:
        # The other half of the two-sided law, and the reason the shipped merge
        # stands: feature 295 refuses every epoch that has *reached* the budget,
        # so no figure above it can be selectable either. Pinned over the whole
        # audited range rather than at the boundary alone, because the audit's
        # soundness is a claim about the judgment's monotonicity — a merge that
        # refused three but admitted four would be a ledger with a hole in it.
        assert refuses_selection(GATE_EPOCH_ID, served) is (
            served >= SEQUESTERED_EPOCH_BUDGET
        )
        assert selectable_past_budget(((GATE_EPOCH_ID, served),)) == ()

    def test_the_weakened_judgment_names_only_the_epochs_past_the_budget(self) -> None:
        # The conjunction's first term, isolated: with a judgment that refuses
        # nothing, the findings are exactly the counts strictly above the budget.
        # Three is admitted by this judgment and is still not a finding — the
        # sentence says *exceeding* three — and two is not either; so the file
        # pins its own boundary as hard as it pins the venue's.
        findings = selectable_past_budget(
            tuple((f"epoch-{count:02d}", count) for count in AUDITED_COUNTS),
            refuses=admits_everything,
        )
        assert findings == tuple(
            (f"epoch-{count:02d}", str(count), STILL_SELECTABLE)
            for count in AUDITED_COUNTS
            if count > SEQUESTERED_EPOCH_BUDGET
        )

    def test_the_finding_beside_clean_rows_names_only_the_spent_epoch(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The load-bearing regression shape: a ledger the writers left in good
        # order — one epoch clean, one spent to its budget — plus one epoch past
        # the budget. Under the shipped judgment nothing is named; under a
        # weakened one exactly the past-budget epoch is, so the gate neither
        # refuses a merge wholesale and makes the operator hunt for the row, nor
        # waves the spent epoch through for standing beside clean ones.
        _spend_decisions(ledger_url, OTHER_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET)
        _spend_decisions(
            ledger_url, THIRD_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET + 1, first=100
        )
        with closing(_connection(ledger_path)) as connection:
            assert merge_refusal(connection) == ()
            refusal = merge_refusal(connection, refuses=admits_everything)
        assert refusal == ((THIRD_EPOCH_ID, "4", STILL_SELECTABLE),)

    def test_two_findings_are_both_named_in_the_epochs_own_order(self) -> None:
        # Every finding, not the first: a ledger holding two epochs past the
        # budget with a judgment that admits them refuses the merge naming both,
        # in the table's key order — the operator sees the whole shape of the
        # break, the way the registry gate's refusal names each lying row. The
        # epoch spent to its budget is in the input and is not named, so the
        # ordering assertion cannot pass by naming everything.
        findings = selectable_past_budget(
            (
                ("epoch-2026-09", 7),
                ("epoch-2026-03", 4),
                ("epoch-2026-04", 3),
            ),
            refuses=admits_everything,
        )
        assert findings == (
            ("epoch-2026-03", "4", STILL_SELECTABLE),
            ("epoch-2026-09", "7", STILL_SELECTABLE),
        )

    def test_a_past_budget_epoch_reaches_the_audits_finding_through_the_ledger(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The same finding, driven end-to-end from the table rather than from a
        # constructed pair: the shipped writers spend a fourth decision, the raw
        # audit reads the row, and the merge is refused naming the epoch and its
        # figure *as the row spells them*. This is the half a member suite cannot
        # promise — it is the merge-time reading of a ledger nobody audited at
        # write time.
        past = SEQUESTERED_EPOCH_BUDGET + 1
        _spend_decisions(ledger_url, GATE_EPOCH_ID, past)
        with closing(_connection(ledger_path)) as connection:
            raw = dict(audit_rows(connection))
            refusal = merge_refusal(connection, refuses=admits_everything)
        assert raw[GATE_EPOCH_ID] == past
        assert refusal == ((GATE_EPOCH_ID, str(past), STILL_SELECTABLE),)

    @pytest.mark.parametrize("value", ["three", 2.5, None, True, -1])
    def test_a_served_figure_that_is_not_a_count_refuses_the_merge_at_all(
        self, value: Any
    ) -> None:
        # The clause's first term, failing closed. SQLite's columns are
        # dynamically typed, so a figure that is text, a fraction, an absence or a
        # flag is reachable through a raw connection — and none of these is a
        # count of decisions, so the comparison cannot be made at all. The gate
        # refuses the merge rather than reporting *nothing past the budget*,
        # because silence here is indistinguishable from a clean ledger and the
        # operator is about to certify a figure nobody derived. ``True`` is
        # refused although it equals ``1``: a flag read as a count is exactly the
        # one-decision-nobody-recorded failure the member's own validator names
        # first.
        assert _count_of(value) is None
        assert selectable_past_budget(((GATE_EPOCH_ID, value),)) == (
            (GATE_EPOCH_ID, repr(value), UNREADABLE_COUNT),
        )

    def test_an_unreadable_count_is_refused_through_the_ledger_itself(
        self, ledger_path: Path
    ) -> None:
        # The same case from the table's side: a hand past the writers lands a
        # figure the charge would never have derived, in a column the DDL declares
        # ``INT NOT NULL`` and SQLite accepts anyway. The audit reads it raw and
        # names the epoch with the row's own spelling of the value — so the
        # operator greps the ledger for what the refusal printed, and a text
        # ``'three'`` cannot be read as the figure three.
        with closing(_connection(ledger_path)) as connection, connection:
            _hand_written_count(connection, THIRD_EPOCH_ID, "three")
            refusal = merge_refusal(connection)
        assert refusal == ((THIRD_EPOCH_ID, "'three'", UNREADABLE_COUNT),)

    def test_an_unreadable_count_beside_a_real_finding_names_both_kinds(
        self, ledger_path: Path
    ) -> None:
        # The two kinds are not exclusive and are not collapsed into one: a
        # ledger can hold an epoch a weakened judgment admits *and* an epoch
        # nobody can budget, and the refusal reports both, each with its own kind
        # so the repair is not guessed at. The row that is merely clean is in the
        # input and is named by neither.
        with closing(_connection(ledger_path)) as connection:
            with connection:
                _hand_written_count(connection, GATE_EPOCH_ID, "half")
                _hand_written_count(connection, OTHER_EPOCH_ID, 6)
            refusal = merge_refusal(connection, refuses=admits_everything)
        assert refusal == (
            (GATE_EPOCH_ID, "'half'", UNREADABLE_COUNT),
            (OTHER_EPOCH_ID, "6", STILL_SELECTABLE),
        )

    def test_the_shipped_writers_cannot_land_a_past_budget_admission(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The write-side face of the same line, exercised as the gate's
        # complement: however far the writers spend a holdout, the venue's
        # judgment refuses it — so the ledger a merge's writers leave cannot carry
        # the finding by their own hand, and the audit face above catches
        # whatever ships past them (a hand, a backfill, a weakened gate). The
        # module-level spelling is exercised too, so the refusal a caller without
        # stores meets is the same one.
        _spend_decisions(ledger_url, GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET + 2)
        with pytest.raises(EpochSelectionError):
            select_epoch(GATE_EPOCH_ID, database_url=ledger_url)
        with closing(_connection(ledger_path)) as connection:
            assert merge_refusal(connection) == ()

    def test_both_boundaries_are_pinned_against_the_venues_own_comparison(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The soundness theorem this gate certifies, stated as one assertion over
        # the ledger: *the epochs this gate can name are exactly the ones the
        # venue stopped refusing*. For every audited count, the composed store and
        # the pure judgment agree about whether the epoch may be selected — and
        # once the judgment refuses (from the budget upward) the merge can name
        # nothing however far past the budget the figure stands, while below the
        # budget the count is not this sentence's finding either. A merge that
        # moved either boundary fails here even if no ledger in the suite ever
        # spent a fourth decision through the real acts.
        charges = EpochCharges(ledger_url)
        gate = EpochSelections(charges)
        for count in AUDITED_COUNTS:
            with closing(_connection(ledger_path)) as connection, connection:
                _hand_written_count(connection, GATE_EPOCH_ID, count)
            refused_by_the_venue = False
            try:
                gate.select(GATE_EPOCH_ID)
            except EpochSelectionError:
                refused_by_the_venue = True
            assert refused_by_the_venue is (count >= SEQUESTERED_EPOCH_BUDGET)
            assert refuses_selection(GATE_EPOCH_ID, count) is refused_by_the_venue
            with closing(_connection(ledger_path)) as connection:
                named = merge_refusal(connection, refuses=admits_everything)
            assert [finding[1] for finding in named] == (
                [str(count)] if count > SEQUESTERED_EPOCH_BUDGET else []
            )


# ── The finding is exactly the selectable epoch past the budget ──────────────


class TestTheFindingIsExactlyTheSelectableEpochPastTheBudget:
    """The gate refuses exactly the sentence's finding: an epoch strictly past
    the budget whose selection the merge's judgment still admits — never the
    equality case, never a clean row, never an absence, never another sentence's
    refusal."""

    def test_the_boundary_is_the_venues_refusal_and_not_this_gates(self) -> None:
        # §13 item 4's two sentences, meeting at one line. ``>=`` is feature
        # 295's: three served is refused *selection* by the venue, which is why a
        # merge carrying it has nothing left selectable. *Exceeding* three is this
        # sentence's first term, so the equality case is admitted here — and the
        # case just past it is named. The two faces are complements over one line,
        # pinned from the merge side.
        assert refuses_selection(GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET - 1) is False
        assert refuses_selection(GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET) is True
        for served in range(SEQUESTERED_EPOCH_BUDGET + 1):
            assert (
                selectable_past_budget(
                    ((GATE_EPOCH_ID, served),), refuses=admits_everything
                )
                == ()
            )
        assert selectable_past_budget(
            ((GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET + 1),),
            refuses=admits_everything,
        ) == ((GATE_EPOCH_ID, str(SEQUESTERED_EPOCH_BUDGET + 1), STILL_SELECTABLE),)

    def test_a_clean_epoch_is_not_the_finding(self) -> None:
        # The ordinary shape of a deployment mid-campaign: an epoch that has
        # served part of its budget. Nothing on it exceeds three, and a gate that
        # refused it would refuse every merge made while promotions are running —
        # which is every merge §M4's ninety-day window describes.
        assert (
            selectable_past_budget(((GATE_EPOCH_ID, 2),), refuses=admits_everything)
            == ()
        )

    def test_an_epoch_nobody_sealed_is_not_this_gates_finding(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # An absent row states no spend, so there is nothing on it to exceed the
        # budget — and the epoch is nonetheless unselectable, because feature 295
        # refuses the absence by name rather than reading it as a clean zero
        # (*"a never-sealed name selected is sequestration bypassed by a typo"*).
        # The two facts stay apart: this gate names epochs the ledger states, and
        # the sealing process's absence is the venue's refusal, not a spend this
        # sentence could exceed. A gate that read the absence as a row would be
        # the typo feature 295's refusal exists to catch.
        with closing(_connection(ledger_path)) as connection:
            assert audit_rows(connection) == (
                (GATE_EPOCH_ID, 0),
                (OTHER_EPOCH_ID, 0),
                (THIRD_EPOCH_ID, 0),
            )
            assert merge_refusal(connection) == ()
            assert merge_refusal(connection, refuses=admits_everything) == ()
        _refuse_to_select(ledger_url, "epoch-nobody-sealed")

    def test_the_retirement_flag_moves_nothing_here(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # ``retired`` is feature 296's flag — the exhaustion machinery's
        # persistence of its own verdict — and this sentence is the count's.
        # Setting it changes neither the venue's judgment nor this gate's finding,
        # and that is the correct division: a gate that read the flag would be
        # judging feature 296's clause under feature 356's name, and would report
        # *what was retired* rather than *what remains selectable*. The flag is
        # absent until the very end of §13 item 4's ledger, so a gate that leaned
        # on it would answer *nothing spent* for every ledger short of exhaustion.
        _spend_decisions(ledger_url, GATE_EPOCH_ID, 2)
        with closing(_connection(ledger_path)) as connection:
            before = merge_refusal(connection, refuses=admits_everything)
            with connection:
                connection.execute(
                    f"UPDATE {EPOCH_LEDGER_TABLE} SET {RETIRED_COLUMN} = 1 "
                    f"WHERE {EPOCH_ID_COLUMN} = ?",
                    (GATE_EPOCH_ID,),
                )
            after = merge_refusal(connection, refuses=admits_everything)
            flag = _raw_row(ledger_path, GATE_EPOCH_ID)[RETIRED_COLUMN]
        assert before == after == ()
        assert flag == 1
        assert refuses_selection(GATE_EPOCH_ID, 2) is False

    def test_the_audit_is_a_bare_read_over_the_two_columns_it_judges(self) -> None:
        # The gate that reads the record never writes one, and never invents a
        # spend a row never stated: one ``SELECT``, over the epoch and its count,
        # keyed by nothing — the whole table is the subject — so the audit cannot
        # confirm itself with a predicate the code under judgement chose.
        assert AUDIT_SQL.lstrip().upper().startswith("SELECT")
        assert EPOCH_LEDGER_TABLE in AUDIT_SQL
        assert EPOCH_ID_COLUMN in AUDIT_SQL
        assert PROMOTION_DECISIONS_SERVED_COLUMN in AUDIT_SQL
        for forbidden in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "WHERE"):
            assert forbidden not in AUDIT_SQL.upper()

    def test_the_audit_moves_no_column_of_the_ledger_it_judges(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # Nothing moves, on either side of the verdict — asserted on the table,
        # not on the store's testimony. The count is feature 294's to persist and
        # the flag feature 296's to set, so a refused merge leaves the ledger
        # byte-identical: there is no "violation" row to record, and the figure
        # the gate refused on is the figure the row already carries.
        _spend_decisions(ledger_url, GATE_EPOCH_ID, SEQUESTERED_EPOCH_BUDGET + 1)
        before = _raw_row(ledger_path, GATE_EPOCH_ID)
        with closing(_connection(ledger_path)) as connection:
            merge_refusal(connection)
            merge_refusal(connection, refuses=admits_everything)
        assert _raw_row(ledger_path, GATE_EPOCH_ID) == before


# ── The exhaustion clause is the same boundary ───────────────────────────────


class TestTheExhaustionClauseIsTheSameBoundary:
    """§13 item 4's second sentence — *"When clean epochs run out, the system
    stops"* — read through features 296 and 297, which must reach zero at exactly
    the budget this gate's clause is stated against."""

    def test_the_gauge_depletes_at_the_budget_this_gate_reads(self) -> None:
        # Feature 297's depleting count, over rows the charge would have built,
        # for every count this gate audits: an epoch is clean until it has served
        # the budget, and spent from there on. A gauge that reached zero a step
        # later than this gate's boundary would report headroom the venue has
        # already closed; one that reached it a step earlier would announce
        # exhaustion while an epoch may still be selected.
        records = {
            count: ServingEpoch(
                epoch_id=f"epoch-{count:02d}",
                sealed_at=EPOCH_SEALED_AT,
                promotion_decisions_served=count,
                retired=False,
            )
            for count in AUDITED_COUNTS
        }
        for count in AUDITED_COUNTS:
            assert clean_epochs_remaining((records[count],)) == (
                0 if count >= SEQUESTERED_EPOCH_BUDGET else 1
            )

    def test_the_terminal_verdict_stops_exactly_where_the_budget_ends(self) -> None:
        # Feature 296's stop on one epoch, at the boundary: at the budget the
        # system has no clean epoch to run on — §13 item 4's *legitimate terminal
        # state* — and one step short it may continue. The stop's boundary and
        # this gate's clause are the same figure, which is the whole point of
        # reading them from one constant rather than three spellings of "three".
        at_budget = ServingEpoch(
            epoch_id=GATE_EPOCH_ID,
            sealed_at=EPOCH_SEALED_AT,
            promotion_decisions_served=SEQUESTERED_EPOCH_BUDGET,
            retired=False,
        )
        one_short = ServingEpoch(
            epoch_id=GATE_EPOCH_ID,
            sealed_at=EPOCH_SEALED_AT,
            promotion_decisions_served=SEQUESTERED_EPOCH_BUDGET - 1,
            retired=False,
        )
        assert clean_epochs_remaining((one_short,)) == 1
        assert blocks_when_no_clean_epoch_remains((one_short,)) == 1
        assert clean_epochs_remaining((at_budget,)) == 0
        with pytest.raises(member.PromotionError) as raised:
            blocks_when_no_clean_epoch_remains((at_budget,))
        assert "legitimate terminal state" in str(raised.value)

    def test_the_three_acts_agree_about_the_boundary_over_the_ledgers_own_rows(
        self, ledger_url: str, ledger_path: Path
    ) -> None:
        # The identity the whole file rests on, read off the ledger's own rows
        # rather than off constructed values: whatever figure the ledger states,
        # the merge's judgment refuses it exactly when the figure has reached the
        # budget, the gauge counts it clean exactly when it has not, and the
        # terminal stop fires exactly at the end. So the only epochs this gate can
        # ever name are ones the judgment stopped refusing — and a merge carrying
        # a correctly-gated promotion therefore ships no finding at all, no matter
        # how far past the budget the writers actually spent it.
        charges = EpochCharges(ledger_url)
        for count in AUDITED_COUNTS:
            with closing(_connection(ledger_path)) as connection, connection:
                _hand_written_count(connection, GATE_EPOCH_ID, count)
            standing = charges.epoch(GATE_EPOCH_ID)
            assert standing is not None
            assert standing.promotion_decisions_served == count
            spent = count >= SEQUESTERED_EPOCH_BUDGET
            assert refuses_selection(GATE_EPOCH_ID, count) is spent
            assert clean_epochs_remaining((standing,)) == (0 if spent else 1)
            with closing(_connection(ledger_path)) as connection:
                assert merge_refusal(connection) == ()
