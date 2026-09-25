"""System rejects the merge when promotion criteria are recorded after the
deciding evaluation.

app_spec.xml feature 360 — the "System Invariant CI Gates" category's
promotion gate — is the merge-time form of a law the Promotion & Epoch
Governance category states twice at run time. Feature 291: *"System exposes
POST /promotion/pre-register, which returns a criteria hash recorded before
the deciding evaluation runs."* Feature 293: *"System persists each promotion
decision into the promotion_registry with its timestamp and criteria hash."*
The schema those two acts share has carried the ordering since ``0108`` wrote
it: *"``criteria_hash`` and ``pre_registered_at`` are written before the
deciding evaluation, and ``decided_at`` after. The two-timestamp shape is the
whole point — an auditor reads the row and sees that the criteria preceded
the decision, which is the claim a promotion has to make to be more than a
fitted number."* docs/alpha-engine-prd.md §13 states the law itself, as item
7 among the invariants that *"violating any of these silently invalidates the
system"*: *"Promotion criteria are pre-registered and hashed before the
evaluation that decides them"* — and §13's preamble names this gate's venue:
*"Enforce in CI, not in code review."* §M4 states the deployment it was
written for: *"Pre-register success criteria in a hashed file **before** the
shadow run starts."*

**The subject is the row's own two columns, not the prose.** The finding,
stated exactly: a decided ``promotion_registry`` row whose
``pre_registered_at`` is strictly later than its ``decided_at`` — the row
itself stating that the criteria were recorded after the deciding evaluation.
The gate reads the row, because that is where the ordering ends up:
``promotion.pre_register``'s own words for the shape are *"the deciding
evaluation runs in another process entirely, and feature 360's invariant
reads the row after both have finished."* A merge carries writers and a
schema, not rows — the rows arrive when the writers run — so the gate judges
a merge on the three faces it can see. First the **shapes** the merge
carries: the insert that records the criteria cannot name ``decided_at`` (a
row born closed is how one statement could record criteria and stamp a
decision before them), the update that closes the row names exactly
``decided_at`` (the closing act cannot re-record criteria), and the owning
DDL keeps ``decided_at`` nullable with no ``DEFAULT`` — ``0108``'s own
comment: *"``decided_at`` is nullable because the row is written while the
decision is still open, which is the only ordering under which
pre-registration means anything."* Second the **writers, exercised once**:
CI runs the shipped stores end-to-end on a throwaway registry and audits the
rows they leave — a merge whose writers order every decision stands by
construction, and a merge whose writers *would* author the finding is caught
by the same run (feature 293's store refuses a decision stamped before the
criteria, *"authored there rather than caught there"* — the write-side face
this gate is the audit side of). Third the **audit itself**: over any
registry — one the writers left, one a backfill or a restored backup or a
raw connection wrote — every decided row carrying the finding refuses the
merge, deterministically, naming the node and both stamps. The member's own
store describes that last author with its own words: a row no writer of this
member produced is *"a hand that reached past it."*

**The boundary is shared with the runtime face, and it is 293's own.**
Feature 293's store refuses ``decided_at < pre_registered_at`` and honours
equality — *"the boundary is 360's own: this store refuses ``decided_at <
pre_registered_at`` and honours equality, because the row holds the instant
the decision was recorded and not the span the evaluation ran over — a stamp
equal to the criteria's is neither before them nor a finding 360 names."*
This gate refuses the same strict inequality from the audit side:
``pre_registered_at > decided_at`` is the finding, and equality is not. The
two faces are complements over one line — the store declines to *author* the
row that lies, the gate declines to *merge* past the row that lies — and a
row whose two stamps are equal stands on both sides of that line, pinned
here from the audit side exactly as the member's suite pins it from the
write side.

**Why CI, and not only the store.** The store's guard is a check the writer
performs; the shapes are how the ordering is created; and every one of the
three ships in a merge. §13's preamble says to enforce its invariants in CI,
so a merge that weakened any face — the insert naming ``decided_at``, the
update growing a second column in its ``SET``, the store dropping its
refusal, the DDL growing a ``DEFAULT`` on the deciding stamp — fails this
gate before any row is authored anywhere. And the audit face catches the
finding whatever authored it, which is the half no writer-side test can
promise: a pre-registration record that lies is worse than no record,
because §M4's exit criterion (*"90 days of shadow meeting pre-registered,
hashed criteria"*) would be read back as met by criteria that were written
after the result was known — *"a criterion written down after the result is
known is not a criterion; it is a description of the result."*

**What this gate is not, asserted as hard as what it is.** It is not
feature 292's ``criteria_mismatch`` — that is a *verdict about evidence*, a
promotion refused at decision time because its recorded hash differs from
the pre-registered value; this gate orders two timestamps on one row and
never reads the hash's value, so a decided row with a well-ordered pair and
a malformed hash is not this gate's refusal (that is 291's read-back
refusal, ``promotion_registry_unwritable``) — the scope is the pair, exactly
as the spec sentence's is. It is not the member suite's writer tests: those
pin each act's own behaviour from inside the member; this gate reads what a
merge carries and what the rows state, from outside it. It is not a
judgement on any promotion's merits — a refused row says *the record lies*,
not *the promotion fails*; whether a promotion stands is the deciding
evaluation's question and feature 292's comparison, never this sentence's.
And it does not refuse open rows: a row with no ``decided_at`` states no
deciding evaluation, so there is nothing on it for the criteria's instant to
contradict — the audit's one statement reads decided rows only, the
predicate being feature 293's own noun (*"a decided row is a persisted
decision"*).

**The dialect.** There is no dialect split to this finding the way the
ledger gate's grants have one: ``0108`` writes the same two-timestamp shape
on both its branches (pinned below over both), and the stamps compare as
instants — an aware stamp in another offset names the same instant and is
normalised rather than string-compared, the same rule ``pre_register``'s
validator states. The audit reads SQLite registries because that is the one
dialect this workspace's stores speak (the spec's single-machine allowance);
on Postgres the same two columns exist and the same comparison reads them,
the finding being a property of the columns and not of the engine.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import inspect
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from promotion import PreRegistrations, PromotionDecisions

# The two shipped write statements, read where they live.  A store has no
# public ``statements()`` seam the way a migration does — these private
# constants ARE the statements — and they are the merge-carried artifact the
# shape face below judges.  Restating their SQL in this file would let the
# gate agree with itself and pass anything, the same failure mode a re-typed
# DDL would give the ledger gate.
from promotion.decision import _UPDATE_SQL
from promotion.errors import PromotionDecisionError
from promotion.pre_register import _INSERT_SQL

# ── The schema's owners, loaded the way their runner loads them ───────────────

#: tests/invariants/test_promotion_preregistration_ordering.py →
#: tests/invariants → tests → the repository root, whose migrations/ tree
#: holds the DDL this gate judges.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The migration tree's versions directory — the one place a merge's DDL
#: lives. The gate reads it rather than a restatement, so DDL edited in a
#: candidate merge is judged as it will ship, not as this file remembers it.
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The revision that owns the registry: 0108 is the file that declares
#: ``promotion_registry`` and its two timestamps — the columns an auditor
#: compares, and the finding's whole subject.
REGISTRY_REVISION = "0108_forward_and_universe_tables"

#: The revisions that own the registry's two foreign-key parents, in the
#: chain's order — the set a registry needs before any row can be written
#: through the child table, the same order :data:`promotion.schema.
#: MIGRATION_ORDER` states. Restated as data here rather than imported: a
#: gate that imported the member's order would agree with the member by
#: construction and pin nothing.
PARENT_REVISIONS: tuple[str, ...] = (
    "0118_node_table",
    "0110_epoch_ledger",
)


def _load_migration(revision: str) -> ModuleType:
    """Load ``revision`` from the versions directory, by path.

    ``migrations/`` is not a package and is not on ``sys.path``; a runner
    loads a migration by path the same way, so loading it by path here is the
    shape a migration is *built* to be used in rather than a workaround. A
    missing file fails with the path in the message, because the one failure
    a gate should never have to guess at is "the schema's owner moved" — a
    gate that silently skipped the DDL would pass for a merge that shipped
    anything.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this gate judges the migration "
            "that owns promotion_registry's two timestamps, so it needs the "
            "schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_invariants_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The schema's owners, loaded once at collection — reading them is a
#: precondition of every judgement below, not a behaviour any one test
#: chooses.
MIGRATIONS: dict[str, ModuleType] = {
    revision: _load_migration(revision)
    for revision in (*PARENT_REVISIONS, REGISTRY_REVISION)
}

#: The migration that owns the registry — the one whose DDL the shape face
#: judges.
MIGRATION = MIGRATIONS[REGISTRY_REVISION]


# ── The columns and the row the finding lives on ──────────────────────────────

#: The table and its columns, restated as data rather than imported from the
#: member — the discipline the member's own conftest states for its
#: constants: a suite that imported them would agree with the member by
#: construction and pin nothing. These spellings are ``0108``'s own, and the
#: spec's schema block's.
PROMOTION_REGISTRY_TABLE = "promotion_registry"
NODE_ID_COLUMN = "node_id"
EPOCH_ID_COLUMN = "epoch_id"
CRITERIA_HASH_COLUMN = "criteria_hash"
PRE_REGISTERED_AT_COLUMN = "pre_registered_at"
DECIDED_AT_COLUMN = "decided_at"

#: The one statement the audit runs: the decided rows, in the table's key
#: order. ``decided_at IS NOT NULL`` is feature 293's own noun as a predicate
#: — *"a decided row is a persisted decision"* — and it is the audit's scope:
#: an open row states no deciding evaluation, so there is nothing on it for
#: the criteria's instant to contradict. A bare ``SELECT``, spelled once so
#: the gate that reads the record is never the hand that writes one.
AUDIT_SQL = (
    f"SELECT {NODE_ID_COLUMN}, {PRE_REGISTERED_AT_COLUMN}, {DECIDED_AT_COLUMN} "
    f"FROM {PROMOTION_REGISTRY_TABLE} "
    f"WHERE {DECIDED_AT_COLUMN} IS NOT NULL "
    f"ORDER BY {NODE_ID_COLUMN}"
)

#: The criteria document the gate registers, restated from the PRD's own
#: milestones rather than the member's constant — the six terms as §12's M3
#: exit and §11's figures read them. The gate never reads the hash back; the
#: store computes it, and a well-formed body is all the writers need here.
CRITERIA_DOCUMENT: dict[str, Any] = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": 90,
}

#: A criteria hash a hand-written row can carry. 64 lowercase hex characters,
#: the spelling the CHAR(64) column holds — the audit never compares it, but
#: the row must be writable, and a hash that was not one would make the test
#: about 291's read-back refusal instead of this gate's ordering.
HAND_CRITERIA_HASH = "ab" * 32

#: The gate's node identities — one per role a row plays, all seated as
#: parents so a hand past the store writes a row that is *about* the finding
#: and not about a foreign key.
REGISTERED_NODE = "33333333-3333-4333-8333-333333333333"
OPEN_NODE = "44444444-4444-4444-8444-444444444444"
HOSTILE_NODE = "55555555-5555-4555-8555-555555555555"
SECOND_HOSTILE_NODE = "66666666-6666-4666-8666-666666666666"
GATE_NODES = (REGISTERED_NODE, OPEN_NODE, HOSTILE_NODE, SECOND_HOSTILE_NODE)

#: The parents' own columns: a campaign the nodes belong to (the ``node``
#: table's plain NOT NULL column — no reference, so no campaign row needed)
#: and one sequestered epoch every registration books.
GATE_CAMPAIGN_ID = "22222222-2222-4222-8222-222222222222"
GATE_EPOCH_ID = "epoch-2026-03"
EPOCH_SEALED_AT = "2026-02-01T00:00:00+00:00"

#: The two instants the stands cases order: criteria fixed on the first,
#: decided a week later — the ordinary shape of a genuine promotion, the
#: evaluation running on data the criteria preceded.
FIXED_AT = dt.datetime(2026, 3, 1, 12, 0, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 8, 9, 30, tzinfo=dt.UTC)


# ── The finding: the row's own two columns, compared as instants ─────────────


def _instant(value: Any) -> dt.datetime:
    """One stamp as an aware-UTC instant — the comparable form of a column value.

    Accepts the datetime a store hands back or the ISO-8601 text the table
    holds, the form both writers write. An aware instant in another offset
    names the same instant and is normalised rather than rejected — the rule
    :func:`promotion.pre_register._validated_instant` states, and the reason
    the comparison below is over instants and not over text: two stamps that
    name one moment in two offsets must order as one moment. A naive stamp is
    read as UTC because the column declares TIMESTAMPTZ — the zone is the
    column's own statement, and the audit does not invent a second one.
    """
    instant = (
        value
        if isinstance(value, dt.datetime)
        else dt.datetime.fromisoformat(str(value))
    )
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        return instant.replace(tzinfo=dt.UTC)
    return instant.astimezone(dt.UTC)


def _spelling(value: Any) -> str:
    """The stamp as the row spelled it — datetimes rendered, text kept.

    The refusal names both instants in the row's own spelling so the operator
    reads the finding off the table it came from, not re-rendered into a
    second format the table never held.
    """
    return value.isoformat() if isinstance(value, dt.datetime) else str(value)


def criteria_recorded_after(
    rows: Iterable[tuple[str, Any, Any]],
) -> tuple[tuple[str, str, str], ...]:
    """Every decided row whose criteria were recorded after its deciding evaluation.

    The finding §13 item 7 refuses, evaluated over ``(node_id,
    pre_registered_at, decided_at)`` triples exactly as the audit read them:
    a row is a finding when its first stamp is *strictly* later than its
    second — the criteria recorded after the deciding evaluation. Open rows
    are skipped, not resolved: no ``decided_at`` means no deciding evaluation
    is recorded, and there is nothing on the row for the criteria's instant
    to contradict. Equality is not a finding, for the reason feature 293's
    own boundary states — the row holds the instant the decision was
    *recorded*, not the span the evaluation ran over, and a stamp equal to
    the criteria's is neither before them nor *after* them.

    Returns one ``(node_id, pre_registered_at, decided_at)`` triple per
    finding, each stamp in the row's own spelling, sorted by node — the
    deterministic, operator-facing form of the refusal, the way the ledger
    gate names each colliding role beside the verb it holds. Empty means no
    decided row on the registry contradicts the law; the merge stands.
    """
    findings: list[tuple[str, str, str]] = []
    for node, pre_registered_at, decided_at in rows:
        if decided_at is None:
            continue
        if _instant(pre_registered_at) > _instant(decided_at):
            findings.append(
                (node, _spelling(pre_registered_at), _spelling(decided_at))
            )
    return tuple(sorted(findings))


def audit_rows(connection: sqlite3.Connection) -> tuple[tuple[str, Any, Any], ...]:
    """The registry's decided rows, as triples — the audit's one read.

    ``AUDIT_SQL`` and nothing else: a bare ``SELECT`` over the two columns
    the finding lives on, decided rows only, in the table's key order. The
    gate reads the table raw rather than through the member's own listing so
    the code under judgement cannot confirm itself — the same discipline the
    member's own conftest states for its raw-row fixture — and it is the
    reason the listing cross-check below exists: a merge that hid decided
    rows from the listing auditors are told to read would defeat every
    reader but this one.
    """
    cursor = connection.execute(AUDIT_SQL)
    try:
        return tuple(cursor.fetchall())
    finally:
        cursor.close()


def merge_refusal(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str], ...]:
    """The gate itself: findings that refuse the merge over ``connection``'s registry.

    The merge-time form of §13 item 7's ordering and of features 291 and
    293's two writes. Empty means the merge stands — no decided row on the
    registry carries its criteria recorded after its deciding evaluation.
    Computed from the rows as they were left, never by writing one: the
    record is the thing being judged, and a gate that could add to it would
    be able to forge the subject of its own audit.
    """
    return criteria_recorded_after(audit_rows(connection))


# ── The shape face: the DDL and the two statements a merge carries ───────────


def _registry_ddl(dialect: str) -> str:
    """The ``CREATE TABLE`` the owning migration declares, for ``dialect``.

    Read from the migration's own ``statements()`` — the property that makes
    a migration reviewable at all — never retyped here, so the shape the
    gate judges is the shape that ships. Fails by name if the revision
    stopped declaring the registry, because a gate that silently judged an
    absent table would pass for a merge that dropped its own subject.
    """
    for statement in MIGRATION.statements(dialect):
        if f"CREATE TABLE IF NOT EXISTS {PROMOTION_REGISTRY_TABLE}" in statement:
            return statement
    raise AssertionError(
        f"{REGISTRY_REVISION} declares no {PROMOTION_REGISTRY_TABLE} table "
        f"for dialect {dialect!r}; this gate judges the two-timestamp shape "
        "that file owns, so it needs the table to be where its owner keeps it"
    )


def column_definitions(ddl: str) -> dict[str, str]:
    """The ``CREATE TABLE`` body as a column → definition mapping.

    The DDL this workspace's migrations write is one column per line inside
    the parentheses — the spelling ``0108`` uses for every table it creates
    — so the body is read line by line and each line's first word is the
    column. Definitions are kept whole (type, NOT NULL, DEFAULT and all,
    uppercased by the caller when compared) because the two properties the
    shape face judges — nullability and the absence of a ``DEFAULT`` — live
    in the definition and not in the name.
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


def insert_columns(statement: str) -> tuple[str, ...]:
    """The column list of an ``INSERT`` — the columns the statement records.

    Parsed into the exact list rather than substring-matched: the two
    columns this gate is about are spelled as *parts* of other columns'
    names (``id`` inside ``node_id``), and a substring check would read the
    wrong answer — the same discipline the member's own suite applies to
    this same statement.
    """
    return tuple(
        column.strip()
        for column in statement.split("(", 1)[1].split(")", 1)[0].split(",")
    )


def set_columns(statement: str) -> tuple[str, ...]:
    """The column names an ``UPDATE``'s ``SET`` clause writes.

    The closing act's whole boundary, as data: the columns whose values this
    statement can change. A ``SET`` clause that named a criteria column
    beside the deciding stamp would be the one act that re-records criteria
    at the instant it stamps a decision — the finding authored in a single
    statement — and this parse is how the gate sees that before any row
    exists.
    """
    set_clause = statement.split("SET", 1)[1].split("WHERE", 1)[0]
    return tuple(
        assignment.split("=", 1)[0].strip() for assignment in set_clause.split(",")
    )


# ── The registry a merge's writers leave, brought up the chain's way ─────────


def _connection(path: Path) -> sqlite3.Connection:
    """Open the registry's database with its foreign keys enforced.

    The pragma is SQLite's own honest default-flip every store in this member
    performs: a hand past the store writes through the same constraint the
    store writes through, so a hand-written row is a row about the finding
    and not about a foreign key nobody checked.
    """
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _seat_parents(connection: sqlite3.Connection) -> None:
    """Seat the two parent rows the registry's foreign keys name.

    The store checks both parents rather than manufacturing them — a node's
    row is the discovery loop's write and an epoch's row is the sealing
    process's — so the gate seats them the way the member's own conftest
    does, in the columns the owning migrations declare. ``node``'s
    ``campaign_id`` is a plain NOT NULL column with no reference (0118
    declares none), so no campaign row is needed for a node to exist.
    """
    for node in GATE_NODES:
        connection.execute(
            "INSERT INTO node (id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?)",
            (node, GATE_CAMPAIGN_ID, "macro", 1),
        )
    connection.execute(
        "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
        (GATE_EPOCH_ID, EPOCH_SEALED_AT),
    )


def _hand_written_row(
    connection: sqlite3.Connection,
    node: str,
    pre_registered_at: str,
    decided_at: str | None,
    *,
    criteria_hash: str = HAND_CRITERIA_HASH,
) -> None:
    """Write one registry row past the stores — the hand that reached past them.

    The only way the finding can exist: nothing the shipped writers leave
    can carry it (the insert cannot name ``decided_at``, the store refuses
    the early stamp, the once-only close cannot be re-stamped), so a row
    that carries it arrived by a backfill, a restored backup or a raw
    connection — *"a hand that reached past it,"* in the member's own words.
    The audit face exists for exactly that author, and this helper is its
    witness.
    """
    connection.execute(
        f"INSERT INTO {PROMOTION_REGISTRY_TABLE} "
        f"({NODE_ID_COLUMN}, {EPOCH_ID_COLUMN}, {CRITERIA_HASH_COLUMN}, "
        f"{PRE_REGISTERED_AT_COLUMN}, {DECIDED_AT_COLUMN}) "
        "VALUES (?, ?, ?, ?, ?)",
        (node, GATE_EPOCH_ID, criteria_hash, pre_registered_at, decided_at),
    )


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    """A registry database the versioned tree brought up, parents seated.

    The deployment shape where the migrations got there first: the schema is
    the owners', run as their own ``statements("sqlite")`` in the chain's
    order — the same order :data:`promotion.schema.MIGRATION_ORDER` states,
    restated here as data so the gate asserts *that* order rather than
    importing it. The stores' own bootstraps are all ``IF NOT EXISTS``, so a
    store opening this database converges on it and changes nothing.
    """
    path = tmp_path / "promotion-registry.db"
    with closing(_connection(path)) as connection, connection:
        for revision in (*PARENT_REVISIONS, REGISTRY_REVISION):
            for statement in MIGRATIONS[revision].statements("sqlite"):
                connection.execute(statement)
        _seat_parents(connection)
    return path


@pytest.fixture
def registry_url(registry_path: Path) -> str:
    """The store-facing URL of the fixture's registry — the same file, by name.

    The URL spelling the member's own suite uses: ``sqlite:///`` plus the
    absolute path, which the store's translator resolves back to that same
    absolute file — the one spelling that makes the writers' database and
    the audit's raw read the same registry.
    """
    return f"sqlite:///{registry_path}"


# ── The gate reads the ordering the merge carries ─────────────────────────────


class TestTheGateReadsTheOrderingTheMergeCarries:
    """The gate judges the schema and the two statements a merge ships, as
    data, without running them."""

    def test_the_gate_reads_the_migration_that_owns_the_registry(self) -> None:
        # The gate reads the registry's own owner — the revision that declares
        # the two timestamps — loaded by path the way a runner loads it, never
        # a restatement typed into this file. A gate that re-typed the DDL it
        # judged could agree with itself and pass anything; this one fails the
        # moment the owner moves or changes.
        assert MIGRATION.REVISION == REGISTRY_REVISION
        assert PROMOTION_REGISTRY_TABLE in MIGRATION.TABLES

    @pytest.mark.parametrize("dialect", ["sqlite", "other"])
    def test_the_registry_the_merge_ships_carries_the_two_timestamps(
        self, dialect: str
    ) -> None:
        # The shape that makes the ordering auditable at all, on both of the
        # file's dialect branches: ``pre_registered_at`` NOT NULL (the first
        # stamp always states an instant — a row without one could not be
        # ordered, and the finding would be undecidable rather than absent),
        # and ``decided_at`` nullable with no DEFAULT — the door that keeps
        # the row born open. A DEFAULT on the deciding stamp would let one
        # INSERT record criteria and stamp a decision in the same statement,
        # an ordering created by nobody, which is 0108's own stated reason
        # the column is bare: "the row is written while the decision is still
        # open, which is the only ordering under which pre-registration means
        # anything."
        definitions = column_definitions(_registry_ddl(dialect))
        pre_registered = definitions[PRE_REGISTERED_AT_COLUMN].upper()
        decided = definitions[DECIDED_AT_COLUMN].upper()
        assert "TIMESTAMPTZ" in pre_registered
        assert "NOT NULL" in pre_registered
        assert "TIMESTAMPTZ" in decided
        assert "NOT NULL" not in decided
        assert "DEFAULT" not in decided

    def test_the_recording_statement_names_the_criteria_and_not_the_decision(
        self,
    ) -> None:
        # The insert that records the criteria — feature 291's one statement,
        # read here as merge-carried data. It names both criteria columns (it
        # is the recording act: the hash and the instant it was fixed at) and
        # does not name ``decided_at``: a column list that carried it would
        # give this one statement the ability to record criteria at and stamp
        # a decision before them — the row born closed, and born lying. The
        # member's suite pins this shape from the writer's side; the gate
        # pins it because §13 says the invariant is enforced in CI, where a
        # merge that weakened it fails even if the member's own run was
        # skipped.
        columns = insert_columns(_INSERT_SQL)
        assert CRITERIA_HASH_COLUMN in columns
        assert PRE_REGISTERED_AT_COLUMN in columns
        assert DECIDED_AT_COLUMN not in columns

    def test_the_closing_statement_names_the_decision_only_and_cannot_re_stamp(
        self,
    ) -> None:
        # The update that closes the row — feature 293's one statement, the
        # mirror of the insert's law. Its SET names exactly ``decided_at``, so
        # the criteria hash, the epoch and the first instant are values this
        # statement cannot touch and the closing act cannot re-record the
        # criteria at the instant it stamps. And its WHERE carries the
        # openness it closes (``decided_at IS NULL``), so a second decision —
        # another process, a raw connection, a re-run — matches no row and
        # moves no stamp: the standing ordering cannot be re-stamped into the
        # finding by deciding twice.
        assert set_columns(_UPDATE_SQL) == (DECIDED_AT_COLUMN,)
        where = _UPDATE_SQL.split("WHERE", 1)[1].upper()
        assert f"{DECIDED_AT_COLUMN.upper()} IS NULL" in where

    def test_the_finding_is_decidable_from_the_row_alone(self) -> None:
        # The evaluator's input is the row and nothing else — the same static
        # discipline the ledger gate applies to its grant evaluator: the
        # source of the judgement touches nothing that could open, drive or
        # settle a connection. A gate that had to write to judge would be
        # able to forge the subject of its own audit, and one that had to
        # drive the writers would be judging the writers rather than the
        # record they leave.
        tree = ast.parse(inspect.getsource(criteria_recorded_after))
        database_names = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr
            in {"connect", "cursor", "execute", "executescript", "commit", "rollback"}
        ]
        assert database_names == []


# ── A merge whose registry orders every decision stands ───────────────────────


class TestAMergeWhoseRegistryOrdersEveryDecisionStands:
    """The shipped writers, exercised once, leave a registry the audit
    passes — the merge stands by construction, and the member ships the
    listing this audit cross-checks."""

    def test_the_registry_the_shipped_writers_leave_passes_the_audit(
        self, registry_url: str, registry_path: Path
    ) -> None:
        # The stands case stated end-to-end: the merge's own writers, run
        # once over the migrated registry — pre-register, then decide — and
        # audited after both have finished, which is the moment this gate's
        # invariant reads (feature 291's own words for it). A second node is
        # left open beside the decided one, because the registry a merge
        # leaves is mixed, and the audit's read is pinned non-vacuous: it saw
        # the decided row, and found nothing on it.
        registered, created = PreRegistrations(registry_url).pre_register(
            REGISTERED_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        assert created is True
        assert registered.open is True
        PromotionDecisions(registry_url).record_decision(
            REGISTERED_NODE, decided_at=DECIDED_AT
        )
        PreRegistrations(registry_url).pre_register(
            OPEN_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        with closing(_connection(registry_path)) as connection:
            rows = audit_rows(connection)
            refusal = merge_refusal(connection)
        assert [row[0] for row in rows] == [REGISTERED_NODE]
        assert refusal == ()

    def test_a_decision_at_the_instant_of_registration_stands(
        self, registry_url: str, registry_path: Path
    ) -> None:
        # The boundary shared with the runtime face, pinned from the audit
        # side: feature 293's store honours equality — the row holds the
        # instant the decision was *recorded*, not the span the evaluation
        # ran over — and this gate's finding is *recorded after*, which
        # equality is not. A row whose two stamps are one instant stands on
        # both sides of the shared line, and the member's suite pins the
        # same boundary from the write side: the two are complements.
        PreRegistrations(registry_url).pre_register(
            REGISTERED_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        record, created = PromotionDecisions(registry_url).record_decision(
            REGISTERED_NODE, decided_at=FIXED_AT
        )
        assert created is True
        assert record.decided_at == FIXED_AT
        with closing(_connection(registry_path)) as connection:
            assert merge_refusal(connection) == ()

    def test_the_listing_the_member_ships_for_this_audit_enumerates_the_same_rows(
        self, registry_url: str, registry_path: Path
    ) -> None:
        # Feature 293 ships ``decisions()`` as "the listing an auditor reads
        # … checking the two-timestamp law (feature 360)". The gate reads the
        # table raw — the code under judgement must not confirm itself — and
        # this cross-check is what keeps the two readings honest with each
        # other: on a registry the shipped writers left, the listing and the
        # raw audit enumerate the same decided rows with the same stamps. A
        # merge that hid decided rows from the listing would defeat every
        # auditor who trusted it, and would be caught here.
        PreRegistrations(registry_url).pre_register(
            REGISTERED_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        PromotionDecisions(registry_url).record_decision(
            REGISTERED_NODE, decided_at=DECIDED_AT
        )
        listing = PromotionDecisions(registry_url).decisions()
        with closing(_connection(registry_path)) as connection:
            rows = audit_rows(connection)
        assert [record.node_id for record in listing] == [row[0] for row in rows]
        assert [
            (record.pre_registered_at, record.decided_at) for record in listing
        ] == [(_instant(row[1]), _instant(row[2])) for row in rows]


# ── A merge that records criteria after the deciding evaluation is refused ────


class TestAMergeThatRecordsCriteriaAfterTheDecidingEvaluationIsRefused:
    """Any decided row carrying the finding refuses the merge, whatever
    authored it — and the shipped writers refuse to author it at all."""

    def test_a_row_whose_criteria_were_recorded_after_the_decision_is_refused(
        self, registry_path: Path
    ) -> None:
        # The finding itself: criteria recorded a day after the deciding
        # evaluation stamped, written past the stores because nothing they
        # leave can carry it — the hand that reached past. The refusal names
        # the node and both stamps in the row's own spelling, so the operator
        # reads the lie straight off the table: this row says the promotion
        # was decided before its criteria existed.
        with closing(_connection(registry_path)) as connection:
            with connection:
                _hand_written_row(
                    connection,
                    HOSTILE_NODE,
                    "2027-01-05T00:00:00+00:00",
                    "2027-01-04T23:59:59+00:00",
                )
            refusal = merge_refusal(connection)
        assert refusal == (
            (
                HOSTILE_NODE,
                "2027-01-05T00:00:00+00:00",
                "2027-01-04T23:59:59+00:00",
            ),
        )

    def test_the_smallest_lie_one_instant_after_is_refused(
        self, registry_path: Path
    ) -> None:
        # The comparison is strict and the finding is any instant after, not
        # a margin: criteria recorded one second after the deciding stamp are
        # recorded after it, §M4's word is "before", and a gate that forgave
        # a second would forgive a minute for being only sixty of them.
        one_second = dt.timedelta(seconds=1)
        with closing(_connection(registry_path)) as connection:
            with connection:
                _hand_written_row(
                    connection,
                    HOSTILE_NODE,
                    (FIXED_AT + one_second).isoformat(),
                    FIXED_AT.isoformat(),
                )
            refusal = merge_refusal(connection)
        assert refusal == (
            (
                HOSTILE_NODE,
                (FIXED_AT + one_second).isoformat(),
                FIXED_AT.isoformat(),
            ),
        )

    def test_the_finding_beside_well_ordered_rows_names_only_the_lying_row(
        self, registry_url: str, registry_path: Path
    ) -> None:
        # The load-bearing regression shape: the registry a merge's writers
        # left in good order, plus one row that arrived past them. The
        # refusal names exactly the lying row — the audit does not refuse the
        # merge wholesale and make the operator hunt for which row broke it,
        # and it does not wave the lying row through for standing beside
        # honest ones. Sorted deterministically, the operator-facing form of
        # the finding.
        PreRegistrations(registry_url).pre_register(
            REGISTERED_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        PromotionDecisions(registry_url).record_decision(
            REGISTERED_NODE, decided_at=DECIDED_AT
        )
        PreRegistrations(registry_url).pre_register(
            OPEN_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        with closing(_connection(registry_path)) as connection:
            with connection:
                _hand_written_row(
                    connection,
                    HOSTILE_NODE,
                    "2027-01-05T00:00:00+00:00",
                    "2027-01-04T23:59:59+00:00",
                )
            refusal = merge_refusal(connection)
        assert refusal == (
            (
                HOSTILE_NODE,
                "2027-01-05T00:00:00+00:00",
                "2027-01-04T23:59:59+00:00",
            ),
        )

    def test_two_findings_are_both_named_in_the_rows_own_order(
        self, registry_path: Path
    ) -> None:
        # Every finding, not the first: a registry holding two lying rows
        # refuses the merge naming both, in the table's key order — the
        # operator sees the whole shape of the break, the way the ledger
        # gate's refusal names each colliding role beside its verb.
        with closing(_connection(registry_path)) as connection:
            with connection:
                _hand_written_row(
                    connection,
                    SECOND_HOSTILE_NODE,
                    "2027-02-05T00:00:00+00:00",
                    "2027-02-01T00:00:00+00:00",
                )
                _hand_written_row(
                    connection,
                    HOSTILE_NODE,
                    "2027-01-05T00:00:00+00:00",
                    "2027-01-04T23:59:59+00:00",
                )
            refusal = merge_refusal(connection)
        assert [finding[0] for finding in refusal] == [
            HOSTILE_NODE,
            SECOND_HOSTILE_NODE,
        ]

    def test_a_finding_that_only_the_instants_see_is_refused(
        self, registry_path: Path
    ) -> None:
        # Why the comparison is over instants and not over text: a stamp
        # written in another offset names the same moment spelled later —
        # 23:30 at −02:00 *is* 01:30 UTC the next calendar day. This row's
        # text sorts its first stamp *before* its second ("2026-…" before
        # "2027-…"), so a string comparison would pass the merge, while the
        # instants order the criteria a full hour after the deciding
        # evaluation. The normalisation is the rule the member's own
        # validator states — an aware instant in another offset names the
        # same instant — and the refusal keeps the row's spelling so the
        # operator can find it.
        with closing(_connection(registry_path)) as connection:
            with connection:
                _hand_written_row(
                    connection,
                    HOSTILE_NODE,
                    "2026-12-31T23:30:00-02:00",
                    "2027-01-01T00:30:00+00:00",
                )
            refusal = merge_refusal(connection)
        assert refusal == (
            (
                HOSTILE_NODE,
                "2026-12-31T23:30:00-02:00",
                "2027-01-01T00:30:00+00:00",
            ),
        )

    def test_the_shipped_store_refuses_to_author_the_finding(
        self, registry_url: str, registry_path: Path
    ) -> None:
        # The write-side face of the same line, exercised as the gate's
        # complement: a decision stamped *before* the criteria were fixed is
        # refused by the shipped store ("authored there rather than caught
        # there" — feature 293's own words for the division), and the refused
        # call leaves the row exactly as it was, still open. So the registry
        # the merge's writers leave cannot carry the finding by their own
        # hand; the audit face below catches whatever ships past them.
        PreRegistrations(registry_url).pre_register(
            REGISTERED_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        with pytest.raises(PromotionDecisionError) as excinfo:
            PromotionDecisions(registry_url).record_decision(
                REGISTERED_NODE,
                decided_at=FIXED_AT - dt.timedelta(days=1),
            )
        assert "§13 item 7" in str(excinfo.value)
        with closing(_connection(registry_path)) as connection:
            cursor = connection.execute(
                f"SELECT {DECIDED_AT_COLUMN} FROM {PROMOTION_REGISTRY_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (REGISTERED_NODE,),
            )
            try:
                decided_at = cursor.fetchone()[0]
            finally:
                cursor.close()
            assert decided_at is None
            assert merge_refusal(connection) == ()

    def test_a_closed_row_cannot_be_re_stamped_into_the_finding(
        self, registry_url: str, registry_path: Path
    ) -> None:
        # The once-only close, from the data side: after a genuine decision,
        # a second decision stamped before the criteria matches no row (the
        # update's WHERE carries the openness it closes) and is answered by
        # the standing row untouched. The standing ordering cannot be
        # re-stamped into the finding by deciding twice, which is the engine
        # half of the store's guard — a property of the statement, not of
        # the flow that happens to read first.
        PreRegistrations(registry_url).pre_register(
            REGISTERED_NODE,
            GATE_EPOCH_ID,
            CRITERIA_DOCUMENT,
            pre_registered_at=FIXED_AT,
        )
        PromotionDecisions(registry_url).record_decision(
            REGISTERED_NODE, decided_at=DECIDED_AT
        )
        standing, created = PromotionDecisions(registry_url).record_decision(
            REGISTERED_NODE,
            decided_at=FIXED_AT - dt.timedelta(days=1),
        )
        assert created is False
        assert standing.decided_at == DECIDED_AT
        with closing(_connection(registry_path)) as connection:
            assert merge_refusal(connection) == ()


# ── The finding is exactly the recorded-after pair and nothing else ───────────


class TestTheFindingIsExactlyTheRecordedAfterPairAndNothingElse:
    """The gate refuses exactly the sentence's finding: the strict
    recorded-after pair on a decided row — never an equal pair, an honest
    span, an open row, or a hash this sentence is not about."""

    def test_the_honest_ordering_is_not_the_finding(self) -> None:
        # The ordinary shape of a genuine promotion, stated at the evaluator:
        # criteria fixed, the evaluation running a week on data the criteria
        # preceded, the decision stamped after. Nothing on this pair
        # contradicts §13 item 7, and a gate that refused it would be
        # refusing every promotion that took time to decide — which is the
        # only kind §M4's 90-day window describes.
        assert criteria_recorded_after(
            ((REGISTERED_NODE, FIXED_AT, DECIDED_AT),)
        ) == ()

    def test_an_open_row_is_not_a_finding(self) -> None:
        # A row with no ``decided_at`` states no deciding evaluation, so
        # there is nothing on it for the criteria's instant to contradict —
        # the audit's scope is decided rows, the predicate being feature
        # 293's own noun. The one statement the audit runs is pinned to that
        # scope: a bare SELECT over the registry, decided rows only, so the
        # gate that reads the record never writes one and never invents a
        # decision a row never stated.
        assert criteria_recorded_after(((OPEN_NODE, FIXED_AT, None),)) == ()
        assert AUDIT_SQL.lstrip().upper().startswith("SELECT")
        assert f"WHERE {DECIDED_AT_COLUMN} IS NOT NULL" in AUDIT_SQL

    def test_a_malformed_hash_is_not_this_gates_finding(
        self, registry_path: Path
    ) -> None:
        # The scope is the pair, exactly as the spec sentence's is. This
        # decided row is well ordered and carries a ``criteria_hash`` no hash
        # function ever produced — a corruption, and a real refusal, but
        # 291's: the read-back validator's, in the store's own vocabulary.
        # The value the hash holds is feature 292's comparison's. A gate that
        # refused here would be refusing merges for a sentence that is not
        # this one's, and the operator would go hunting a clock fault that
        # is not there.
        with closing(_connection(registry_path)) as connection:
            with connection:
                _hand_written_row(
                    connection,
                    HOSTILE_NODE,
                    FIXED_AT.isoformat(),
                    DECIDED_AT.isoformat(),
                    criteria_hash="not-a-hash",
                )
            assert merge_refusal(connection) == ()
