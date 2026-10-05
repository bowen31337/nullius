"""Feature 3, the tree writer — a node's metrics onto its own existing row.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 3:
*System persists a node's evaluated metrics onto its existing node row with
orchestrator._tree_writer.NodeMetricsWriter(database_url), an implementation
of the evaluator's TreeNodeWriter protocol.*  The member is wiring over Z0 —
the evaluator owns the write's shape, the migrations own the ``node`` table —
so every test here runs the *real* seam: a throwaway SQLite database brought
to the node table's own migrations (``0118`` creates the table, ``0114`` adds
the seven metric columns), a real :class:`evaluator` ``NodeRow`` handed across
the seam, and the row read back column by column.  No fake database answers
for the tree, because the feature's whole claim is about what the tree holds.

One test per claim the feature sentence makes:

* **the update** — ``write_node`` sets exactly the seven metric columns on the
  row whose ``id`` is ``node_row.node_id`` and answers ``(node_id, True)`` on a
  first write; the six core scalars land, and the ``perturb_stability`` the
  record left ``None`` leaves the column exactly as the tree held it, so this
  step cannot clobber a tripwire's figure.

* **idempotent by value** — a second write of the same seven values answers
  ``(node_id, False)`` and leaves the row byte-for-byte as it was; the tree is
  not rewritten to say the same thing twice, and the answer is the retry
  signal §14 demands.

* **a changed value is a conflict** — a row that already holds metrics handed
  *different* ones raises :class:`~orchestrator._tree_writer.NodeMetricsConflictError`
  (code word ``node_metrics_conflict``) naming the node and the columns that
  disagree, and the standing values are untouched.

* **a missing row is a conflict, and no INSERT** — a write for a node the tree
  does not hold raises the same class naming the node, and the table gains no
  row: the writer updates an existing row and never creates one.  A database
  the ``node`` migration has not reached is the same refusal.

* **the protocol** — the writer satisfies the evaluator's ``TreeNodeWriter``
  structurally, and its ``write_node`` accepts the evaluator's own ``NodeRow``
  (imported here from ``evaluator._persist_store``, the seam's home), so the
  implementation is checked against the shape it must speak and not a
  lookalike.

* **the module's surface** — ``__all__`` names the writer and its one conflict
  vocabulary; the base error is a wiring refusal, distinct from the conflict.

No test opens a network connection, reads a real credential, or writes outside
a pytest temporary directory.  Each test takes a fresh SQLite file (never
``sqlite://`` in-memory: an in-memory database is per-connection, so the row a
write lands in would be invisible to the next read and every assertion would
be testing connection pooling rather than the tree).
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest
from evaluator._persist_store import NodeRow
from orchestrator._tree_writer import (
    NODE_METRICS_CONFLICT_CODE,
    NodeMetricsConflictError,
    NodeMetricsWriter,
    NodeMetricsWriterError,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up — tests -> orchestrator -> packages ->
# repo root — and the migrations live beside it under migrations/versions.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two migrations that make the tree this feature writes into: ``0118``
#: creates the ``node`` table (feature 97), ``0114`` adds the seven metric
#: columns (feature 101).  Run in the assembled chain's order — the table
#: first, then the columns against it — because ``0114`` is an ``ALTER``
#: against a table ``0118`` creates and SQLite refuses it otherwise.
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

#: The seven metric columns feature 101 lands, in the spec's own order.
METRIC_COLUMNS = (
    "ic_mean",
    "ic_tstat",
    "ir_standalone",
    "ir_marginal",
    "turnover",
    "cost_adjusted_ir",
    "perturb_stability",
)

#: The six this writer always carries; ``perturb_stability`` is separate
#: because its honest ``None`` means *not measured by this step*.
CORE_COLUMNS = METRIC_COLUMNS[:-1]


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is deliberately outside this member's
    file-claim scope; a migration is loaded by its runner the same way — by
    path — so loading it by path here is the shape a migration is *built* to
    be used in.  A missing file fails loudly, because the one failure a test
    should never have to guess at is "the schema owner moved".
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the node table's "
            "own migrations rather than hand-writing its DDL, so it needs the "
            "schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_orchestrator_test_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, migrated to the tree.

    The spec's own sentence taken literally — *tests use a throwaway SQLite
    database migrated with the node table migrations* — through each
    migration's own ``apply``, which opens, runs and commits on the named
    database.  Nothing is hand-written: ``0118``'s ``CREATE TABLE`` and
    ``0114``'s seven ``ALTER``s are the schema under test.
    """
    url = f"sqlite:///{tmp_path / 'tree-test.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


@pytest.fixture
def writer(tree_database: str) -> NodeMetricsWriter:
    """The writer over this test's own migrated tree."""
    return NodeMetricsWriter(tree_database)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test.

    This suite's own few lines rather than a call into the member: the writer's
    ``_resolve_path`` is private, and a test reaching into it would be pinning
    an implementation detail it should be free to change.  The URL grammar is
    the one every store mirrors, so the translation is the same steps by design.
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _plant_node(database_url: str, *, node_id: str | None = None) -> str:
    """Insert one root node row — the state a live evaluation writes onto.

    Deliberately raw SQL against the migrated tree, the way the discovery
    suite plants a root: the writer under test never creates nodes, so the test
    must, and reaching for a planting feature would be testing that feature
    instead of this one.  ``parent_id`` stays ``NULL`` (the row is a root) and
    ``theme_root`` / ``depth`` take the values ``0118`` declares.  The seven
    metric columns are left ``NULL`` — *not yet measured*, the state the first
    write is about.
    """
    identifier = node_id or str(uuid.uuid4())
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, NULL, ?, ?, ?)",
            (identifier, str(uuid.uuid4()), "macro", 0),
        )
    return identifier


def _node_row(node_id: str, **overrides: object) -> NodeRow:
    """The evaluator's own ``NodeRow``, carrying the seven measured values.

    A real :class:`evaluator._persist_store.NodeRow`, not a lookalike: the
    feature claims an implementation of the evaluator's protocol, so the test
    hands the writer exactly the record the evaluator hands across its seam.
    ``perturb_stability`` defaults to ``None`` — feature 85's honest *step 10
    is not this step's input* — and a caller may override any field.
    """
    fields: dict[str, object] = {
        "node_id": node_id,
        "campaign_id": str(uuid.uuid4()),
        "snapshot_name": "sealed-2026-10-05",
        "evaluator_hash": "ab" * 32,
        "cost_model": "binance-vst/2026-10",
        "ic_mean": 0.05,
        "ic_tstat": 2.5,
        "ir_standalone": 0.8,
        "turnover": 0.3,
        "ir_marginal": 0.6,
        "cost_adjusted_ir": 0.55,
        "perturb_stability": None,
    }
    fields.update(overrides)
    return NodeRow(**fields)  # type: ignore[arg-type]


def _read_metrics(database_url: str, node_id: str) -> dict[str, object]:
    """The seven metric columns the tree holds for ``node_id``."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        row = connection.execute(
            f"SELECT {', '.join(METRIC_COLUMNS)} FROM node WHERE id = ?",
            (node_id,),
        ).fetchone()
    assert row is not None, f"the tree lost its row for {node_id!r}"
    return dict(zip(METRIC_COLUMNS, row))


def test_write_node_lands_the_core_scalars_and_answers_written(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # The feature sentence's whole claim, read off the table: the six core
    # scalars land on the row whose id is node_row.node_id, and the answer is
    # (node_id, True) — this call wrote the row.  The record's None
    # perturb_stability is *not* written: the column starts NULL and stays
    # NULL, because this step did not measure it.
    node_id = _plant_node(tree_database)
    answered_id, written = writer.write_node(_node_row(node_id))
    assert answered_id == node_id
    assert written is True

    stored = _read_metrics(tree_database, node_id)
    assert stored["ic_mean"] == 0.05
    assert stored["ic_tstat"] == 2.5
    assert stored["ir_standalone"] == 0.8
    assert stored["ir_marginal"] == 0.6
    assert stored["turnover"] == 0.3
    assert stored["cost_adjusted_ir"] == 0.55
    assert stored["perturb_stability"] is None


def test_a_second_write_of_the_same_values_answers_false(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # §14's retry: the same seven values again is a no-op — answered
    # (node_id, False) — and the row is byte-for-byte what the first write
    # left.  The tree is not rewritten to say the same thing twice, which is
    # what makes the second answer meaningful rather than cosmetic.
    node_id = _plant_node(tree_database)
    row = _node_row(node_id)
    first = writer.write_node(row)
    before = _read_metrics(tree_database, node_id)
    second = writer.write_node(row)
    after = _read_metrics(tree_database, node_id)
    assert first == (node_id, True)
    assert second == (node_id, False)
    assert before == after


def test_a_different_value_on_a_row_that_holds_metrics_is_a_conflict(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # The seven scalars are measured, not assigned: a row that already holds
    # metrics handed different ones is a second evaluation of one hypothesis,
    # and the refusal names the node, the code word and the diverging column —
    # so the conflict is decidable from the message alone.  The standing
    # values are untouched.
    node_id = _plant_node(tree_database)
    writer.write_node(_node_row(node_id))
    standing = _read_metrics(tree_database, node_id)

    with pytest.raises(NodeMetricsConflictError) as raised:
        writer.write_node(_node_row(node_id, ic_mean=0.99))
    message = str(raised.value)
    assert NODE_METRICS_CONFLICT_CODE in message
    assert "node_metrics_conflict" in message
    assert node_id in message
    assert "ic_mean" in message

    assert _read_metrics(tree_database, node_id) == standing


@pytest.mark.parametrize("column", CORE_COLUMNS)
def test_every_core_column_is_compared(
    writer: NodeMetricsWriter, tree_database: str, column: str
) -> None:
    # A changed value in any one of the six core columns is a conflict, not a
    # refresh — so no column is silently allowed to drift by being left out of
    # the comparison.
    node_id = _plant_node(tree_database)
    writer.write_node(_node_row(node_id))
    with pytest.raises(NodeMetricsConflictError, match=column):
        writer.write_node(_node_row(node_id, **{column: 123.5}))


def test_perturb_stability_is_left_untouched_when_the_record_measures_none(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # The tripwires member writes node.perturb_stability on its own (feature
    # 130).  A bare live run's record carries None — *not measured by this
    # step* — and that None both leaves the tripwire's figure standing and does
    # not conflict with it: absence is not a differing measurement.
    node_id = _plant_node(tree_database)
    with closing(sqlite3.connect(_path_of(tree_database))) as connection, connection:
        connection.execute(
            "UPDATE node SET perturb_stability = 0.0125 WHERE id = ?", (node_id,)
        )

    _, written = writer.write_node(_node_row(node_id))
    assert written is True
    stored = _read_metrics(tree_database, node_id)
    assert stored["perturb_stability"] == 0.0125
    assert stored["ic_mean"] == 0.05

    # And the same record again is still a no-op, still not a conflict.
    assert writer.write_node(_node_row(node_id)) == (node_id, False)


def test_a_measured_perturb_stability_is_written_and_compared(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # When the record *does* state a number it is a measurement, so it lands
    # and it falls under the same changed-value law as the other six.
    node_id = _plant_node(tree_database)
    assert writer.write_node(_node_row(node_id, perturb_stability=0.03)) == (
        node_id,
        True,
    )
    assert _read_metrics(tree_database, node_id)["perturb_stability"] == 0.03

    with pytest.raises(NodeMetricsConflictError, match="perturb_stability"):
        writer.write_node(_node_row(node_id, perturb_stability=0.04))


def test_a_missing_node_raises_and_the_writer_never_inserts(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # The write is an UPDATE keyed by the node's id, and a live evaluation
    # never creates nodes: a node the tree does not hold is refused by name —
    # never answered by an INSERT — and the table gains no row.
    missing = str(uuid.uuid4())
    with pytest.raises(NodeMetricsConflictError) as raised:
        writer.write_node(_node_row(missing))
    message = str(raised.value)
    assert NODE_METRICS_CONFLICT_CODE in message
    assert missing in message

    with closing(sqlite3.connect(_path_of(tree_database))) as connection:
        count = connection.execute("SELECT COUNT(*) FROM node").fetchone()[0]
    assert count == 0


def test_a_database_without_the_node_migration_is_the_same_refusal(
    tmp_path: Path,
) -> None:
    # A database the node table's migration has not reached has no table to
    # UPDATE.  From the caller's view that is the same refusal as a missing
    # row — nothing to write onto — and the message names the migration that
    # owns the table, because SQLite's own "no such table" names no feature.
    url = f"sqlite:///{tmp_path / 'unmigrated.db'}"
    # Force the file to exist (and be a valid, empty SQLite database).
    with closing(sqlite3.connect(_path_of(url))):
        pass
    with pytest.raises(NodeMetricsConflictError) as raised:
        NodeMetricsWriter(url).write_node(_node_row(str(uuid.uuid4())))
    assert "0118_node_table" in str(raised.value)


def test_the_writer_satisfies_the_evaluators_tree_node_writer_protocol(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # The feature claims an implementation of the evaluator's TreeNodeWriter
    # protocol: the one method it names is present and callable on this object,
    # and it accepts the evaluator's own NodeRow — the record that crosses the
    # seam — answering the (node_id, appended) pair the protocol declares.  The
    # protocol is structural (satisfied by shape, not inheritance), so the
    # check is that the one method the evaluator names answers its call.
    from evaluator._persist_store import TreeNodeWriter

    assert hasattr(TreeNodeWriter, "write_node")
    assert callable(getattr(writer, "write_node", None))

    node_id = _plant_node(tree_database)
    answer = writer.write_node(_node_row(node_id))
    assert isinstance(answer, tuple) and len(answer) == 2
    assert answer[0] == node_id
    assert isinstance(answer[1], bool)


def test_a_row_the_tree_does_not_hold_is_named_by_its_id(
    writer: NodeMetricsWriter, tree_database: str
) -> None:
    # "A missing node row raises NodeMetricsConflictError naming the node" —
    # the id appears in the message, so an operator greps the node and finds
    # the refusal rather than a stack trace that mentions the table only.
    node_id = _plant_node(tree_database)
    other = str(uuid.uuid4())
    with pytest.raises(NodeMetricsConflictError) as raised:
        writer.write_node(_node_row(other))
    assert other in str(raised.value)
    assert node_id not in str(raised.value)


def test_a_writer_with_no_url_is_refused() -> None:
    # A wiring refusal, and a distinct class from the conflict: a writer with
    # no tree names no table its metrics could reach.  An in-memory URL is
    # refused too — a node row must outlive the connection that wrote it.
    with pytest.raises(NodeMetricsWriterError):
        NodeMetricsWriter("")
    with pytest.raises(NodeMetricsWriterError):
        NodeMetricsWriter("sqlite:///:memory:").write_node(_node_row(str(uuid.uuid4())))
    with pytest.raises(NodeMetricsWriterError):
        NodeMetricsWriter("postgresql://localhost/tree").write_node(
            _node_row(str(uuid.uuid4()))
        )


def test_a_row_with_no_node_id_is_refused_before_the_database(
    writer: NodeMetricsWriter,
) -> None:
    # A row that names no node names no row to update — a wiring fault, not a
    # conflict with a row, and refused before the database is touched.
    with pytest.raises(NodeMetricsWriterError):
        writer.write_node(_node_row(""))


def test_the_module_exports_its_writer_and_its_conflict_vocabulary() -> None:
    # The private module's surface: the writer, the one conflict class and its
    # code word, and the base error — so a caller reaching for
    # orchestrator._tree_writer finds the seam and the refusal it must handle,
    # and no accidental neighbours.
    from orchestrator import _tree_writer

    assert set(_tree_writer.__all__) == {
        "NODE_METRICS_CONFLICT_CODE",
        "NodeMetricsConflictError",
        "NodeMetricsWriter",
        "NodeMetricsWriterError",
    }
    assert issubclass(NodeMetricsConflictError, NodeMetricsWriterError)
    assert NODE_METRICS_CONFLICT_CODE == "node_metrics_conflict"


def test_the_module_imports_no_sibling_member() -> None:
    # The seam is structural: the writer satisfies the evaluator's protocol by
    # shape, and this module holds no `import evaluator`.  Importing the member
    # costs composition nothing, which is the property that lets the scan load
    # it on every create_app() without paying for a writer nobody used.  The
    # check reads the module's *import statements* — not its source text, which
    # discusses the absence — so a real `from evaluator import ...` added later
    # is what fails, not the docstring that explains why there is none.
    import ast

    import orchestrator._tree_writer as module

    tree = ast.parse(Path(module.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "evaluator" not in imported
    assert sys.modules.get("orchestrator._tree_writer") is module
