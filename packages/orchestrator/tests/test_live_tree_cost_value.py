"""Feature 3 (Cost-Aware Selection), the live tree's post-cost value.

additions_spec_cost_aware_selection.xml, "Cost-Aware Selection" category,
feature 3: *System gives the exploration policy each node's post-cost
evidence, so that the fixed baseline's select() returns a batch ranked by
post-cost IR t-statistic.*  Feature 1 of the same spec already lands
``ir_tstat`` on the node row (:mod:`orchestrator._tree_writer`,
``test_post_cost_tstat.py``); this suite is the other half — proof that
:func:`orchestrator._live_tree.live_question` carries that column into the
payload :class:`~policy_runtime.PolicyObservation.from_node` reads, and that
:class:`orchestrator._policy.BaselinePolicy` — unmodified, reading nothing
but ``observation.ic_insample`` — therefore ranks by it.

Like :mod:`test_live_tree`, every test here runs the real seam: a throwaway
SQLite database brought to the node table's own migrations (``0118`` creates
the table, ``0114`` adds ``ic_mean``), real rows planted with raw SQL — and,
because ``ir_tstat`` is not one of ``0114``'s columns but a later probe-then-
``ALTER`` addition (feature 1, the same move :mod:`tripwires.node_metric` and
discovery's ``persist`` make for their own columns), a raw ``ALTER TABLE``
where a test needs the column to exist at all.

One test per claim the feature sentence and its three bullets make:

* **``ic_insample`` is ``ir_tstat`` when the row has one** — read directly
  off :meth:`~policy_runtime.PolicyQuestion.observed`, and end to end through
  :class:`~orchestrator._policy.BaselinePolicy`: a node with a higher
  ``ic_mean`` but a lower ``ir_tstat`` ranks *below* its sibling.
* **the absent ``ir_tstat`` fallback is ``ic_mean``, "as before"** — both
  when the column does not exist on the table at all (a tree feature 1 has
  never written through) and when the column exists but this one row's value
  is ``NULL`` (an older row on an upgraded table) — and the baseline's
  ranking is exactly what it was before feature 3 when every row falls back.
* **``r2_insample`` is unaffected** — it stays ``ic_mean``'s own square
  regardless of ``ir_tstat``, because feature 3 renames the ranking value in
  one place only (``ic_insample``), not the R² stand-in.
* **the batch is deterministic** — two calls over one unchanged tree answer
  one batch, and nodes tied on the ranking value break by node id, the same
  tie-break :class:`~orchestrator._policy.BaselinePolicy` already used for
  ``ic_mean`` alone.

No test opens a network connection or writes outside a pytest temporary
directory, and every database is a fresh ``tmp_path`` file — never
``sqlite://`` in-memory — so the suite is safe under pytest-xdist the same
way :mod:`test_live_tree` already is.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlparse

import pytest
from orchestrator._live_tree import live_question
from orchestrator._policy import BaselinePolicy
from policy_runtime import prefix_view

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up — tests -> orchestrator -> packages ->
# repo root — and the migrations live beside it under migrations/versions.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two migrations that make the tree this feature reads — ``0118``
#: creates the ``node`` table (feature 97), ``0114`` adds the metric columns
#: including ``ic_mean`` (feature 101).  ``ir_tstat`` joins neither chain
#: (feature 1 adds it by probe-then-``ALTER`` in the tree writer, not a
#: migration), so a fixture built from these two alone is the pre-feature-1
#: state this suite's fallback tests need, and a test that wants the column
#: ``ALTER``s it in for itself.
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATION_PERIODS = 500


def _load_migration(revision: str) -> ModuleType:
    """The named migration, imported by path — the schema's own owner.

    ``migrations/`` is not a package and is outside this member's file-claim
    scope; loaded by path, the way its own runner loads it.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the node table's "
            "own migrations rather than hand-writing its DDL"
        )
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, migrated to ``0114``.

    No ``ir_tstat`` column — the pre-feature-1 state every deployment that
    ran before the tree writer's probe-then-``ALTER`` landed, and the state
    this suite's "absent column" fallback tests are built to exercise.
    """
    url = f"sqlite:///{tmp_path / 'live-tree-cost-value-test.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test."""
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _ensure_ir_tstat_column(connection: sqlite3.Connection) -> None:
    """Add ``ir_tstat`` to ``node`` if this connection's table lacks it.

    The same probe :func:`orchestrator._tree_writer._ensure_ir_tstat_column`
    runs in production, restated here with raw SQL because this suite plants
    rows directly rather than through :class:`~orchestrator._tree_writer.NodeMetricsWriter`
    (whose conflict-checking write demands all six core metrics on every
    call — more machinery than a test that wants to control one column
    needs).
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(node)")}
    if "ir_tstat" not in columns:
        connection.execute("ALTER TABLE node ADD COLUMN ir_tstat REAL")


def _plant_node(
    database_url: str,
    campaign_id: str,
    *,
    node_id: str | None = None,
    parent_id: str | None = None,
    depth: int = 0,
    ic_mean: float | None = None,
    ir_tstat: float | None = None,
) -> str:
    """Insert one node row directly — the state a live campaign would write.

    ``ir_tstat`` is written, and the column ``ALTER``ed into existence first,
    only when the caller passes a value; a node planted with the default
    leaves the column exactly as the table already has it — present and
    ``NULL`` on this row (an older row on an upgraded table) when an earlier
    call in the same test already added the column, absent entirely when none
    has.
    """
    identifier = node_id or str(uuid.uuid4())
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        if ir_tstat is not None:
            _ensure_ir_tstat_column(connection)
            connection.execute(
                "INSERT INTO node (id, parent_id, campaign_id, theme_root, "
                "depth, ic_mean, ir_tstat) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (identifier, parent_id, campaign_id, "macro", depth, ic_mean, ir_tstat),
            )
        else:
            connection.execute(
                "INSERT INTO node (id, parent_id, campaign_id, theme_root, "
                "depth, ic_mean) VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, parent_id, campaign_id, "macro", depth, ic_mean),
            )
    return identifier


def _select_batch(database_url: str, campaign_id: str, *, width: int) -> list[str]:
    """The baseline's answer, end to end: live tree -> prefix view -> select().

    The pipeline the feature's own sentence names — "the fixed baseline's
    select() returns a batch ranked by post-cost IR t-statistic" — built the
    same way the round loop builds it (spec B, feature 6), with no edit to
    either :mod:`orchestrator._policy` or :mod:`policy_runtime` along the way.
    """
    question = live_question(
        campaign_id,
        database_url=database_url,
        evaluation_periods=EVALUATION_PERIODS,
    )
    view = prefix_view(question)
    return BaselinePolicy(width).select(view)


# -- ic_insample carries ir_tstat when the row has one --------------------------


def test_ic_insample_is_ir_tstat_when_the_row_has_one(tree_database: str) -> None:
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.05, ir_tstat=3.75)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    observed = question.observed()[root]
    assert observed.ic_insample == pytest.approx(3.75)


def test_r2_insample_stays_ic_means_own_square_regardless_of_ir_tstat(
    tree_database: str,
) -> None:
    # Feature 3 renames the ranking value in one place only (ic_insample);
    # r2_insample is the live evaluator's own in-sample R² stand-in and must
    # not start tracking ir_tstat instead.
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=-0.2, ir_tstat=5.0)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    observed = question.observed()[root]
    assert observed.ic_insample == pytest.approx(5.0)
    assert observed.r2_insample == pytest.approx(0.04)


def test_an_ir_tstat_of_zero_is_present_and_is_not_a_fallback(
    tree_database: str,
) -> None:
    # 0.0 is falsy but not NULL: a node whose post-cost IR t-statistic is
    # exactly zero is still measured, and a check written as `if ir_tstat`
    # rather than `if ir_tstat is not None` would wrongly fall back to
    # ic_mean -- the same trap test_live_tree.py guards against for ic_mean.
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.50, ir_tstat=0.0)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.observed()[root].ic_insample == 0.0


def test_baseline_ranks_a_node_with_lower_ir_tstat_below_a_higher_ic_mean_sibling(
    tree_database: str,
) -> None:
    campaign_id = str(uuid.uuid4())
    high_ic = _plant_node(
        tree_database, campaign_id, node_id="high-ic", ic_mean=0.30, ir_tstat=1.2
    )
    low_ic = _plant_node(
        tree_database, campaign_id, node_id="low-ic", ic_mean=0.05, ir_tstat=4.5
    )

    # ic_mean alone would rank high-ic first; post-cost evidence reverses it.
    batch = _select_batch(tree_database, campaign_id, width=1)
    assert batch == [low_ic]

    full_batch = _select_batch(tree_database, campaign_id, width=2)
    assert full_batch == [low_ic, high_ic]


# -- The absent ir_tstat fallback: ic_mean, exactly as before -------------------


def test_fallback_when_the_table_carries_no_ir_tstat_column_at_all(
    tree_database: str,
) -> None:
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.08)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.observed()[root].ic_insample == pytest.approx(0.08)


def test_fallback_when_the_column_exists_but_this_rows_value_is_null(
    tree_database: str,
) -> None:
    # An older row on a table another node's write already upgraded: the
    # column exists, but this row's ir_tstat was never measured. Its own
    # ic_mean is the fallback, independent of any sibling's ir_tstat.
    campaign_id = str(uuid.uuid4())
    with_ir_tstat = _plant_node(
        tree_database, campaign_id, node_id="has-tstat", ic_mean=0.05, ir_tstat=2.0
    )
    without_ir_tstat = _plant_node(
        tree_database, campaign_id, node_id="no-tstat", ic_mean=0.50
    )

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.observed()[without_ir_tstat].ic_insample == pytest.approx(0.50)
    # The baseline still ranks by the per-node effective value: has-tstat's
    # 2.0 beats no-tstat's own ic_mean fallback of 0.50, despite the raw
    # ic_mean ordering (0.05 < 0.50) running the other way.
    assert _select_batch(tree_database, campaign_id, width=2) == [
        with_ir_tstat,
        without_ir_tstat,
    ]


def test_ranking_is_unchanged_from_before_feature_3_when_every_row_falls_back(
    tree_database: str,
) -> None:
    campaign_id = str(uuid.uuid4())
    lower_ic = _plant_node(tree_database, campaign_id, node_id="lower", ic_mean=0.10)
    higher_ic = _plant_node(tree_database, campaign_id, node_id="higher", ic_mean=0.25)

    assert _select_batch(tree_database, campaign_id, width=2) == [higher_ic, lower_ic]


# -- Determinism ------------------------------------------------------------------


def test_the_batch_is_identical_across_repeated_calls(tree_database: str) -> None:
    campaign_id = str(uuid.uuid4())
    _plant_node(tree_database, campaign_id, node_id="a", ic_mean=0.10, ir_tstat=1.0)
    _plant_node(tree_database, campaign_id, node_id="b", ic_mean=0.20, ir_tstat=3.0)
    _plant_node(tree_database, campaign_id, node_id="c", ic_mean=0.40)

    first = _select_batch(tree_database, campaign_id, width=3)
    second = _select_batch(tree_database, campaign_id, width=3)
    third = _select_batch(tree_database, campaign_id, width=3)

    assert first == second == third


def test_nodes_tied_on_the_ranking_value_break_by_node_id(tree_database: str) -> None:
    campaign_id = str(uuid.uuid4())
    # "zeta" and "alpha" carry the identical effective value (one via
    # ir_tstat, the other via its ic_mean fallback); ascending node id must
    # decide the tie, the same rule BaselinePolicy already applied to a bare
    # ic_mean tie.
    zeta = _plant_node(
        tree_database, campaign_id, node_id="zeta", ic_mean=0.01, ir_tstat=2.0
    )
    alpha = _plant_node(tree_database, campaign_id, node_id="alpha", ic_mean=2.0)

    assert _select_batch(tree_database, campaign_id, width=2) == [alpha, zeta]
