"""System rejects the merge when a stored score lacks any member of the
provenance triple.

app_spec.xml feature 357 — the "System Invariant CI Gates" category's
provenance gate — is the merge-time form of a law the spec states as one of
the invariants that *"violating any of these silently invalidates the
system."* The sentence itself: *"System rejects the merge when a stored
score lacks any member of the provenance triple."* The triple is defined by
feature 99 and its migration ``0116``: the three ``CHAR(64) NOT NULL``
columns on the ``node`` table — ``evaluator_hash``, ``snapshot_hash`` and
``cost_model_hash`` — and docs/nullius-tech-architecture.md §9.1 declares
the same three on the same table in the same order, because it is one fact
stated twice. §6.2 adds that ``cost_model_hash`` is *"part of every
score's provenance triple,"* and §15.1's failure-mode table makes the
stakes of each axis explicit — *"snapshot extended → new ``snapshot_hash``
→ tree structure survives; scores do not."* A score that cannot name one
of the three is a score no replay can reproduce, and feature 71's refusal
to compare two scores whose hashes differ can only mean what it says when
every stored score names all three.

**The subject is the node row — the stored score — read as data, in the
three places a merge carries it.** A merge carries writers and a schema,
not rows; the rows arrive when the writers run. So the gate judges a merge
on the three faces it can see, and the audit face that catches whatever
ships past them.

First the **column**: ``0116`` returns its DDL as inspectable data — the
property that makes a migration reviewable at all — and the ``ALTER TABLE
... ADD COLUMN`` that adds each of the three spells ``NOT NULL`` on both
dialects with no ``DEFAULT`` anywhere. ``0116``'s own argument for the
bare constraint is the one this gate holds: a row that predates the
columns has no recorded provenance, and no default could assert one
truthfully — a fabricated ``DEFAULT`` would have to name an evaluator, a
snapshot and a cost model, three hashes no feature ever computed for that
row, which is precisely the error direction this category exists to make
impossible. The gate reads the three column names and the three ``NOT
NULL`` spellings as data, separately, because the constraint is a fact of
the spec that feature 357's completeness gate keys on too.

Second the **record**: the node row the orchestrator writes is rendered
from :class:`discovery.AttemptProvenance` — feature 240's deployment-
supplied half, the frozen value whose three hashes land in every node row
the tree holds — and each of the three fields is *required*, with no
default a caller could omit silently, because the module's own stance is
that the triple is *"the deployment's record of the world the attempt ran
in"* and *"a module that defaulted any of them would be fabricating
provenance."* The three are validated identically, through one function
(:func:`discovery.persist._validated_hash`) that folds case, strips
whitespace and refuses a short, non-hex or ``sha256:``-prefixed token —
so the three columns are held to the sha256 hexdigest's own spelling
wherever they enter the member.

Third the **row**: :meth:`discovery.Attempt.row` renders the node record
as a mapping, and the mapping carries all three columns with the values
the provenance stated — one value, one place, so the row cannot disagree
with the record that produced it. And the **belt behind the belt**: on a
table the assembled chain builds, the insert that names no value for one
of the three is refused by the column itself, in the engine's own words
naming the column — the ``NOT NULL`` the DDL declares, doing what it says
ahead of the write. Even a caller that bypassed every record surface
meets the sentence here, one column at a time.

**The no-value spellings fold, because the record is data and every
spelling of nothing is nothing.** ``None`` — SQL NULL, the state a legacy
upgrade's column would read back as. The empty string — a value that
names no digest. Whitespace — the spelling that passes a bare ``IS NULL``
test and lands in a provenance no audit can replay. And the non-string —
no value the ``CHAR(64)`` column holds. The evaluator below folds all
four into one boolean per column, the way the runtime faces do; a gate
that enumerated spellings by grep would miss the fifth, the column no
writer names.

**The finding is per member of the triple, and it is exactly a member
that carries no value.** A node row is a mapping of column to value; the
gate reads the three named columns back and names each one that carries no
value. A row that carries all three is not the finding; a row that carries
a value for two of the three and none for the third names exactly the
third — never the two it holds. And a value that *is* a digest, however
it was cased or spaced, is a value whatever it names — whether it names a
real evaluator truthfully is feature 70's and feature 71's question, not
this one's.

**Why CI, and why the harm is silent.** A score that cannot name its
evaluator, its snapshot and its cost model is a score no replay can
reproduce — the number might as well have come from a different system —
and the whole point of the triple is that the row that was charged and the
node that was evaluated can name the same three terms without drift. A
node carrying no value for one of the three is worse than one carrying a
wrong value: the wrong value at least names a target a comparison can
refuse (feature 71's ``mismatched_provenance``), while the absent one
makes the refusal unreachable, because there is nothing to compare. Those
refusals ship in merges too, so this gate holds them as data: the column
is ``NOT NULL`` and the record refuses the absence, and the gate's own
judgement needs no database — the evaluators are pure functions of stated
data, pinned statically below, because a gate that had to run a write to
judge it would be an audit after the fact.

**What this gate is not, asserted as hard as what it is.** It is not
feature 71's ``mismatched_provenance`` — that is a *comparison* between
two scores whose evaluator hashes differ, a verdict about a pair, while
this gate reads one row and names the member it lacks; a row carrying a
single well-formed hash is not this gate's finding, and two rows that
disagree are feature 71's, never this one's. It is not feature 358's
``agent_model_id`` refusal: that column is the authoring trio, the thing
that *wrote the code*, which the provenance triple deliberately does not
pin (§9.1: the triple pins *"everything except the thing that wrote the
code"*) — the scope is the three provenance columns exactly as the spec
sentence's is, and a node carrying a model but no evaluator hash is this
gate's refusal and feature 358's stands. It is not a judgement on the
value a hash holds: a column carrying a genuine 64-hex digest is a value,
however it was cased or spaced, and the gate does not ask whether it names
a real evaluator — that is feature 70's stamp and feature 71's
comparison. And it is not the member suites' own write-path tests — those
pin the ``INSERT`` and the idempotent refresh from inside; this gate reads
what a merge carries, from outside it, and adds the face no writer-side
test can promise: a record surface that *accepts* a no-value spelling for
one of the three refuses the merge whatever else it does.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib.util
import inspect
import sqlite3
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from discovery import Attempt, AttemptLogError, AttemptProvenance

# ── The column's owner, loaded the way its runner loads it ────────────────────

#: tests/invariants/test_provenance_triple_completeness.py →
#: tests/invariants → tests → the repository root, whose migrations/ tree
#: holds the DDL this gate judges.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The migration tree's versions directory — the one place a merge's DDL
#: lives. The gate reads it rather than a restatement, so DDL edited in a
#: candidate merge is judged as it will ship, not as this file remembers it.
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"


def _load_migration(revision: str) -> ModuleType:
    """Load ``revision`` from the versions directory, by path.

    ``migrations/`` is not a package and is not on ``sys.path``; a runner
    loads a migration by path the same way, so loading it by path here is
    the shape a migration is *built* to be used in rather than a
    workaround. A missing file fails with the path in the message, because
    the one failure a gate should never have to guess at is "the column's
    owner moved" — a gate that silently skipped the DDL would pass for a
    merge that shipped anything.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this gate judges the migration "
            "that owns the provenance triple, so it needs the column's "
            "owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_invariants_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The migration that owns the triple, loaded once at collection — reading
#: it is a precondition of every judgement below, not a behaviour any one
#: test chooses. ``0116`` is feature 99's revision: the ``ALTER TABLE``
#: that adds ``evaluator_hash``, ``snapshot_hash`` and ``cost_model_hash``
#: and spells each ``NOT NULL`` on both dialects.
MIGRATION = _load_migration("0116_provenance_trio")

# ── The law's own spellings, restated as data ────────────────────────────────

#: The three columns this gate is scoped to, in the spelling the spec's
#: schema block, §9.1's table and feature 99 all write — restated as data
#: rather than imported, so the gate pins *those* columns rather than
#: agreeing with whatever a member's constant carries today.
TRIPLE_COLUMNS: tuple[str, ...] = ("evaluator_hash", "snapshot_hash", "cost_model_hash")

#: The one type every member of the triple carries — the spec's own
#: ``CHAR(64)``, the sha256 hexdigest's width, repeated verbatim rather
#: than re-derived. It is the one thing this gate and the column's owner
#: must agree on.
TRIPLE_TYPE = "CHAR(64)"

#: The stands values: three 64-hex digests, the shape the triple validates,
#: none of them this gate's subject. One per column, so every stands case
#: below is non-vacuous and the row the merge renders carries a genuine
#: triple.
GATE_EVALUATOR_HASH = "ab" * 32
GATE_SNAPSHOT_HASH = "cd" * 32
GATE_COST_MODEL_HASH = "ef" * 32

#: The stands record's authoring model — feature 358's column, not this
#: gate's; carried so a stands record is a record the write path accepts,
#: and so the gate can demonstrate that a node carrying the model but no
#: provenance member is this gate's refusal and feature 358's stands.
GATE_MODEL = "anthropic/claude-opus-5/2026-01"

#: The gate's tree identities: a parent whose attempt is logged and the
#: campaign it belongs to — patterned UUIDs, the spelling every column the
#: tree keys on canonicalizes to.
GATE_PARENT = "11111111-1111-4111-8111-111111111111"
GATE_CAMPAIGN = "22222222-2222-4222-8222-222222222222"

#: The attempt the stands record logs: real source text and its true
#: sha256, so the row below is a row the member's own validation accepts,
#: not a fixture shaped around the gate.
GATE_CODE = "def signal(rows):\n    return tuple(0.0 for _ in rows)\n"
GATE_CODE_HASH = hashlib.sha256(GATE_CODE.encode("utf-8")).hexdigest()
GATE_ARTIFACT_URI = "file:///lake/staging/gate/node/"

#: The sentinel for the one spelling no argument can carry: a record whose
#: writer never named the column at all. Absence is a property of the
#: rendered record, so it is judged by the row face, never passed as a
#: value.
MISSING: Any = object()

#: The no-value spellings the gate refuses, in the order the law's own
#: words suggest them. A spelling counts as refused when asking a shipped
#: surface to carry it raises; the per-spelling faces below pin the classes
#: the shipped refusals carry, which is what keeps this aggregate's breadth
#: anchored rather than excused.
NO_VALUE_SPELLINGS: tuple[tuple[str, Any], ...] = (
    ("None — SQL NULL, the state a legacy upgrade reads back as", None),
    ("'' — the empty string, a value that names no digest", ""),
    ("'   ' — whitespace, the spelling a bare IS NULL passes", "   "),
    ("17 — a non-string, no value the CHAR(64) column holds", 17),
)

#: The spellings a carried-value surface can be asked for — every one
#: above. These are what ``merge_refusal`` asks of each record surface.
CARRIED_SPELLINGS: tuple[tuple[str, Any], ...] = NO_VALUE_SPELLINGS


# ── The stands record the gate renders ───────────────────────────────────────


def gate_provenance(**overrides: Any) -> AttemptProvenance:
    """One deployment record of the world an attempt ran in.

    The provenance half of every node row the orchestrator writes, with the
    triple as the parameters — the surface ``merge_refusal`` asks each
    spelling of. The defaults are the stands triple, so the gate's own
    fixture data carries a value and every judgement below that builds a
    record without naming a column is judging the stands case, not silently
    exercising an absence.
    """
    base: dict[str, Any] = {
        "evaluator_hash": GATE_EVALUATOR_HASH,
        "snapshot_hash": GATE_SNAPSHOT_HASH,
        "cost_model_hash": GATE_COST_MODEL_HASH,
        "agent_model_id": GATE_MODEL,
    }
    base.update(overrides)
    return AttemptProvenance(**base)


def gate_attempt(provenance: AttemptProvenance) -> Attempt:
    """One attempt as feature 240 logs it — the record the row renders from.

    Built the member's own way (real code, its true hash, a legal theme, a
    parent and a campaign) so the row it renders is a row the write path
    would actually write, and the gate's judgement of that row is a
    judgement of the shipped shape rather than of a fixture invented to
    pass it.
    """
    return Attempt(
        parent_id=GATE_PARENT,
        campaign_id=GATE_CAMPAIGN,
        theme_root="term-structure carry",
        depth=1,
        code=GATE_CODE,
        code_hash=GATE_CODE_HASH,
        stated_mechanism=None,
        provenance=provenance,
    )


def _chain_built_node_table() -> sqlite3.Connection:
    """A ``node`` table as the assembled chain builds it, in memory.

    The skeleton ``0118`` creates plus ``0116``'s own ``upgrade`` — the
    columns the chain a merge ships would add, applied by the migration's
    own code rather than by DDL retyped here, so the constraint the belt
    below exercises is the constraint the merge declares.
    """
    connection = sqlite3.connect(":memory:")
    connection.execute(
        f"CREATE TABLE {MIGRATION.NODE_TABLE} "
        "(id TEXT PRIMARY KEY, parent_id TEXT, campaign_id TEXT, "
        "theme_root TEXT NOT NULL, depth INT NOT NULL)"
    )
    MIGRATION.upgrade(connection)
    return connection


# ── The evaluators: the finding as a pure function of stated data ────────────


def no_value(value: Any) -> bool:
    """Whether one column's spelling carries no value.

    The finding the sentence refuses, evaluated over the one thing every
    seam reads: the value a record states for a column. Every spelling the
    runtime faces refuse folds in here — SQL ``NULL``, the empty string,
    whitespace that a bare ``IS NULL`` test would pass, and any non-string,
    which is no value the ``CHAR(64)`` column holds and no provenance an
    audit can replay. A string that strips non-empty is a value whatever it
    names — whether it names a real evaluator *truthfully* is feature 70's
    and feature 71's question, not this one's.
    """
    if value is MISSING or value is None:
        return True
    if not isinstance(value, str):
        return True
    return not value.strip()


def no_triple_value(record: Any) -> tuple[str, ...]:
    """The members of the provenance triple a rendered record lacks.

    A node record, once rendered, is a mapping of column to value — the
    shape :meth:`discovery.Attempt.row` answers and the shape a hand or a
    vendor writer would hand a tree. This reads the three named columns
    back, the absent key told apart from every present one (``.get`` with
    the sentinel), and names each member that carries no value. Empty means
    the record carries the whole triple and the merge stands over it — this
    face never writes, never opens, and never asks a store to vouch for a
    record the gate can read for itself.
    """
    findings = [
        column for column in TRIPLE_COLUMNS if no_value(record.get(column, MISSING))
    ]
    return tuple(sorted(findings))


def merge_refusal(build: Any) -> tuple[str, ...]:
    """The gate itself: the no-value spellings a record surface accepts.

    Asks a provenance-record authoring surface — any callable that takes
    the triple columns as keywords, which is the shape of the shipped
    surface (:class:`discovery.AttemptProvenance`'s construction) — to
    carry each no-value spelling of each column in turn, and names the
    spellings it accepted. Empty means the merge stands: every no-value
    spelling was refused by the surface it was asked of. Computed by
    asking, never by writing, so the gate cannot author a row while
    judging the record that would produce one.

    A spelling counts as refused when asking for it raises; the per-spelling
    faces below pin the exact class the shipped refusal carries, which is
    what keeps this aggregate's breadth anchored rather than excused — the
    gate does not care which vocabulary refuses the value, only that some
    refusal does.
    """
    accepted: list[str] = []
    for column in TRIPLE_COLUMNS:
        for description, value in CARRIED_SPELLINGS:
            try:
                build(**{column: value})
            except Exception:  # noqa: BLE001, S112 - the finding is the
                # *acceptance*: the gate does not care which vocabulary
                # refuses the value, only that some refusal does, and the
                # per-spelling faces below pin the class the shipped
                # refusals carry.
                continue
            accepted.append(f"{column}: {description}")
    return tuple(accepted)


# ── The gate reads the node record the merge carries ─────────────────────────


class TestTheGateReadsTheNodeRecordTheMergeCarries:
    """The gate judges the column, the field and the row a merge ships, as
    data, without writing anything."""

    def test_the_gate_reads_the_migration_that_owns_the_triple(self) -> None:
        # The gate reads the triple's own owner — feature 99's revision,
        # loaded by path the way a runner loads it, never a restatement
        # typed into this file. A gate that re-typed the constraint it
        # judged could agree with itself and pass anything; this one fails
        # the moment the owner moves or changes. It names exactly the three
        # columns the sentence is scoped to, and no fourth.
        assert MIGRATION.REVISION == "0116_provenance_trio"
        assert tuple(MIGRATION.COLUMNS) == TRIPLE_COLUMNS
        assert tuple(MIGRATION.NOT_NULL_COLUMNS) == TRIPLE_COLUMNS

    def test_the_columns_are_declared_not_null_on_both_dialects(self) -> None:
        # The DDL face. On both dialects exactly one statement adds each
        # column, it carries NOT NULL, and no statement anywhere carries a
        # DEFAULT — 0116's own refusal, restated as the gate's: a default
        # would have to name an evaluator, a snapshot and a cost model,
        # three hashes no feature ever computed for the row it fills. A
        # merge that softened either half — the constraint dropped, a
        # default slipped in to ease a backfill — fails here, before any
        # row.
        for dialect in ("other", "sqlite"):
            statements = MIGRATION.statements(dialect)
            for column in TRIPLE_COLUMNS:
                adding = [
                    statement
                    for statement in statements
                    if f"ADD COLUMN {column} " in statement
                ]
                assert len(adding) == 1, (dialect, column, statements)
                assert "NOT NULL" in adding[0].upper()
                assert f"{TRIPLE_TYPE} NOT NULL" in adding[0].upper()
            assert not any("DEFAULT" in statement.upper() for statement in statements)

    def test_the_records_fields_are_required_not_defaulted(self) -> None:
        # The record face, read as a signature. Each of the three fields
        # has no default and no factory: a defaulted field is how "lacks a
        # member" becomes the merge's out-of-the-box configuration — a
        # caller omits the keyword and the record builds. All three are
        # required alike, because the triple is one fact and a module that
        # defaulted any of them would be fabricating provenance.
        fields = {field.name: field for field in dataclasses.fields(AttemptProvenance)}
        for column in TRIPLE_COLUMNS:
            assert fields[column].default is dataclasses.MISSING
            assert fields[column].default_factory is dataclasses.MISSING

    def test_the_row_the_merge_renders_carries_the_triple(self) -> None:
        # The row face's subject exists: the write path renders its node
        # record as a mapping, and the mapping carries all three columns
        # with the values the provenance stated — one value, one place, so
        # the row cannot disagree with the record that produced it. The
        # gate's judgement of that row is the judgement of the shipped
        # shape.
        row = gate_attempt(gate_provenance()).row(GATE_ARTIFACT_URI)
        for column in TRIPLE_COLUMNS:
            assert row[column] == getattr(gate_provenance(), column), column
        assert no_triple_value(row) == ()

    def test_the_gate_judges_the_record_without_opening_a_database(self) -> None:
        # A merge gate refuses the change before it ships; the subject here
        # is a record, and a record is data. The static check the ledger
        # and labeler gates apply to their evaluators, pinned for all of
        # this gate's: none touches anything that could open, drive or
        # settle a connection — a gate that had to run a write to judge it
        # would be an audit after the fact.
        for evaluator in (no_value, no_triple_value, merge_refusal):
            tree = ast.parse(inspect.getsource(evaluator))
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
            assert database_names == []

    def test_the_column_refuses_the_row_the_chain_built(self) -> None:
        # The belt behind the belt: on a table the assembled chain builds,
        # the insert that names no value for one of the three is refused by
        # the column itself, in the engine's own words naming the column —
        # the NOT NULL the DDL declares, doing what it says ahead of the
        # write. Even a caller that bypassed every record surface meets the
        # sentence here, one column at a time. Each of the three is tested:
        # the finding is per member, so the belt must hold per member.
        for column in TRIPLE_COLUMNS:
            with (
                closing(_chain_built_node_table()) as connection,
                pytest.raises(sqlite3.IntegrityError) as excinfo,
            ):
                # Every NOT NULL column but the one under test is filled —
                # the two other triple members and the structural pair
                # ``0118`` declares — so the only constraint the insert can
                # trip is the one the omitted member declares.
                filled = {c: (c * 64)[:64] for c in TRIPLE_COLUMNS if c != column}
                filled["theme_root"] = "macro"
                filled["depth"] = "1"
                connection.execute(
                    f"INSERT INTO {MIGRATION.NODE_TABLE} "
                    f"(id, {', '.join(filled)}) VALUES ('n-{column[:4]}', {', '.join('?' for _ in filled)})",
                    list(filled.values()),
                )
            assert column in str(excinfo.value)


# ── A merge whose node records carry the triple stands ───────────────────────


class TestAMergeWhoseNodeRecordsCarryTheTripleStands:
    """The shipped surfaces, exercised once over a deterministic record,
    carry the triple end to end — the merge stands by construction."""

    def test_the_provenance_record_carries_the_triple_into_the_row(self) -> None:
        # The stands case stated at the record: the deployment supplies the
        # triple, the record validates and carries it, and the row the write
        # path renders states all three under the columns' own names — one
        # value, spelled once, from the caller's argument to the row the
        # tree would hold.
        provenance = gate_provenance()
        for column in TRIPLE_COLUMNS:
            assert getattr(provenance, column) == getattr(gate_provenance(), column)
        row = gate_attempt(provenance).row(GATE_ARTIFACT_URI)
        assert no_triple_value(row) == ()

    def test_every_carried_value_spelling_is_a_value(self) -> None:
        # The stands case stated per spelling: the record surface accepts
        # the stands value for each column, and a value that strips
        # non-empty is a value whatever it names. So the gate's own fixture
        # data carries a value, and the merge stands over it. The shipped
        # surface refuses nothing it is asked to carry here — empty
        # findings on every column, so the merge stands.
        assert merge_refusal(gate_provenance) == ()


# ── A merge whose node record lacks a member of the triple is refused ────────


class TestAMergeWhoseNodeRecordLacksAMemberOfTheTripleIsRefused:
    """Every no-value spelling is refused for every member of the triple —
    and a surface that accepts one is the refusal, whatever else that merge
    does."""

    @pytest.mark.parametrize(
        ("column", "description", "value"),
        [
            (column, description, value)
            for column in TRIPLE_COLUMNS
            for description, value in NO_VALUE_SPELLINGS
        ],
    )
    def test_every_no_value_spelling_is_refused_for_every_column(
        self, column: str, description: str, value: Any
    ) -> None:
        # The record face, one spelling and one column at a time. The
        # refusal is the member's own class and names the column and the
        # constraint, so the operator reads the finding off the exception —
        # a provenance that cannot be built is an attempt that cannot be
        # logged, and the tree never meets the row.
        with pytest.raises(AttemptLogError) as excinfo:
            gate_provenance(**{column: value})
        message = str(excinfo.value)
        # The column is named — the operator reads the finding off the
        # exception, and the refusal is the hash validator's (the sha256
        # hexdigest's own spelling, which the member's words vary by
        # spelling: "must be a string" for the type cases, "64 hexadecimal
        # characters" for the length cases). The column name is the one
        # thing every spelling of the refusal carries, so that is what the
        # gate pins.
        assert column in message

    def test_every_shipped_record_surface_refuses_every_spelling(self) -> None:
        # The gate's own happy path, stated as the gate states it: the one
        # record surface the merge ships — the provenance record's
        # construction — refuses every no-value spelling of every column.
        # Empty findings on all three, so the merge stands.
        assert merge_refusal(gate_provenance) == ()

    def test_the_row_face_names_every_missing_member(self) -> None:
        # The row face's discrimination. A rendered record that omits one
        # column names exactly that column; a record that omits two names
        # both; and the stands record, which carries all three, answers
        # empty. The finding is per member, and it is exactly the members
        # that carry no value — never the ones the record holds.
        full = gate_attempt(gate_provenance()).row(GATE_ARTIFACT_URI)
        assert no_triple_value(full) == ()
        partial = dict(full)
        del partial["snapshot_hash"]
        assert no_triple_value(partial) == ("snapshot_hash",)
        empty = {c: v for c, v in full.items() if c not in TRIPLE_COLUMNS}
        assert no_triple_value(empty) == tuple(sorted(TRIPLE_COLUMNS))

    def test_a_record_surface_that_accepts_a_spelling_is_the_refusal(self) -> None:
        # The load-bearing regression case. A witness that builds a record
        # carrying no value for a column — its field defaulted, its
        # validation demoted — accepts every no-value spelling, and the
        # gate names each spelling it accepted, deterministically. A future
        # edit that weakened a shipped surface (a field given a default, the
        # validation demoted to a warning) turns the test above non-empty
        # right here, at merge time, before any row exists.
        def witness(**kwargs: Any) -> dict[str, Any]:
            # A hand that reached past the record: it renders whatever it is
            # handed, accepting every spelling, the way a vendor writer or a
            # backfill would.
            return {**kwargs}

        accepted = merge_refusal(witness)
        assert len(accepted) == len(TRIPLE_COLUMNS) * len(CARRIED_SPELLINGS)


# ── The finding is exactly the missing member and nothing else ───────────────


class TestTheFindingIsExactlyTheMissingMemberAndNothingElse:
    """The gate refuses exactly the sentence's finding: a rendered record
    that carries no value for one of the three named columns — never a value
    that names a digest, a sibling column's honest state, or a comparison
    between two rows."""

    def test_a_full_triple_is_not_the_finding(self) -> None:
        # The ordinary shape of a genuine score: all three hashes present,
        # each a 64-hex digest. Nothing on this record contradicts feature
        # 357, and a gate that refused it would be refusing every score the
        # system legitimately stored.
        row = gate_attempt(gate_provenance()).row(GATE_ARTIFACT_URI)
        assert no_triple_value(row) == ()

    def test_a_value_that_names_a_digest_is_not_the_finding(self) -> None:
        # The scope is the *absence*, not the truth of the value. A column
        # carrying a genuine digest — however it was cased or spaced, which
        # the member folds rather than refuses — is a value, and the gate
        # does not ask whether it names a real evaluator: that is feature
        # 70's stamp and feature 71's comparison, never this one's. A
        # cased, spaced digest strips to a value and is not the finding.
        row = gate_attempt(gate_provenance()).row(GATE_ARTIFACT_URI)
        row["evaluator_hash"] = "  " + GATE_EVALUATOR_HASH.upper() + "  "
        assert no_triple_value(row) == ()

    def test_the_authoring_model_is_not_this_gates_subject(self) -> None:
        # Feature 358's column is the authoring trio, the thing that *wrote
        # the code*, which the provenance triple deliberately does not pin.
        # A rendered record that carries the model but lacks an evaluator
        # hash is this gate's finding — exactly the evaluator hash, and
        # nothing else — and a record that carries the model and the whole
        # triple is not a finding at all. The two sentences divide the
        # labour: this one refusing the *provenance* absence, that one the
        # *authoring* absence.
        row = gate_attempt(gate_provenance()).row(GATE_ARTIFACT_URI)
        assert "agent_model_id" in row
        del row["cost_model_hash"]
        assert no_triple_value(row) == ("cost_model_hash",)

    def test_a_comparison_between_two_rows_is_not_this_gates_finding(self) -> None:
        # Feature 71's subject is a *pair*: two scores whose evaluator
        # hashes differ, refused as mismatched_provenance. This gate reads
        # one row and names the member it lacks; two rows that each carry a
        # full triple but disagree on the value are feature 71's, never this
        # one's. A record that carries all three is not the finding however
        # another record spells them.
        left = gate_attempt(gate_provenance()).row(GATE_ARTIFACT_URI)
        right = gate_attempt(gate_provenance(evaluator_hash="00" * 32)).row(
            GATE_ARTIFACT_URI
        )
        assert no_triple_value(left) == ()
        assert no_triple_value(right) == ()
