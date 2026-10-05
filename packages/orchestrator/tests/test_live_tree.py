"""Feature 3, the live tree — a running campaign's rows, as a policy's question.

additions_spec_campaign_driver.xml, "Exploration Policy" category, feature 3:
*System creates a live policy question over a running campaign with
orchestrator._live_tree.live_question(campaign_id, *, database_url,
evaluation_periods, budget=None). It answers a policy_runtime.PolicyQuestion
over a CampaignTree frozen from the campaign's node rows.*  The member is
wiring over the ``node`` table and the ``policy_runtime`` question, so every
test here runs the real seam: a throwaway SQLite database brought to the
node table's own migrations (``0118`` creates the table, ``0114`` adds the
metric columns, exactly as :mod:`test_tree_writer` does for the sibling
write seam), real rows planted with raw SQL, and the real
:class:`~policy_runtime.PolicyQuestion` read back.

One test per claim the feature sentence makes:

* **every evaluated node is revealed** — a node whose ``ic_mean`` is not
  ``NULL`` is in :attr:`~policy_runtime.PolicyQuestion.revealed` and answers
  the spec's four-key payload through
  :meth:`~policy_runtime.PolicyQuestion.observed`.
* **a node with no metrics is not revealed** — ``ic_mean IS NULL`` (never
  evaluated, or a failed attempt) is absent from both ``revealed`` and
  ``observed()``, while remaining a legal structural move
  (:meth:`~policy_runtime.PolicyQuestion.legal_actions`) and answering a
  family-less :meth:`~policy_runtime.PolicyQuestion.meta` rather than
  raising.
* **the tree is rebuilt from the rows on every call** — a child planted
  between two calls is invisible to the first question and visible to the
  second.
* **the module reads only id, parent_id, depth and a metric column** — a
  database carrying none of the identity/provenance/authoring-model columns
  still answers correctly, and the source holds no reference to the sidecar
  or an ``is_null`` bit.
* **the wiring refusals** — a bad ``database_url``, an empty campaign, an
  unmigrated database and a bad ``evaluation_periods`` all raise
  :class:`~orchestrator._live_tree.LiveTreeError`; a bad ``budget`` is left
  to raise :class:`~policy_runtime.PolicyBudgetError`, the question's own.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Each test takes a fresh SQLite file
(never ``sqlite://`` in-memory), for the reason :mod:`test_tree_writer`
states: an in-memory database is per-connection, so a row this test's own
setup wrote would be invisible to the module under test.
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
from orchestrator._live_tree import (
    LIVE_TREE_CODE,
    LiveTreeError,
    live_question,
)
from policy_runtime import (
    PolicyAddressError,
    PolicyBudgetError,
    PolicyObservation,
    budget_account,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up — tests -> orchestrator -> packages ->
# repo root — and the migrations live beside it under migrations/versions.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two migrations that make the tree this feature reads — ``0118``
#: creates the ``node`` table (feature 97), ``0114`` adds the metric columns
#: including ``ic_mean`` (feature 101). Run in the assembled chain's order —
#: the table first, then the columns against it.
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATION_PERIODS = 500


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is deliberately outside this
    member's file-claim scope; a migration is loaded by its runner the same
    way — by path — so loading it by path here is the shape a migration is
    *built* to be used in.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the node table's "
            "own migrations rather than hand-writing its DDL, so it needs "
            "the schema's owner to be where the tree keeps it"
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
    """A ``sqlite:///`` URL for a throwaway database, migrated to the tree.

    Through each migration's own ``apply`` — nothing is hand-written:
    ``0118``'s ``CREATE TABLE`` and ``0114``'s ``ALTER``s are the schema
    under test, and this database carries none of the identity, provenance
    or authoring-model columns (migrations ``0115``-``0117``), which is the
    fixture's own proof that this feature reads only the four columns it
    names.
    """
    url = f"sqlite:///{tmp_path / 'live-tree-test.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test."""
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _plant_node(
    database_url: str,
    campaign_id: str,
    *,
    node_id: str | None = None,
    parent_id: str | None = None,
    depth: int = 0,
    ic_mean: float | None = None,
) -> str:
    """Insert one node row directly — the state a live campaign would write.

    Deliberately raw SQL against the migrated tree, the way
    :mod:`test_tree_writer` plants a node: :func:`live_question` never
    writes a row, so the test must. Only ``ic_mean`` is ever set among the
    seven metric columns — the other six stay ``NULL`` throughout this
    suite, which is itself part of the proof that this feature reads no
    metric column but this one.
    """
    identifier = node_id or str(uuid.uuid4())
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean) VALUES (?, ?, ?, ?, ?, ?)",
            (identifier, parent_id, campaign_id, "macro", depth, ic_mean),
        )
    return identifier


# -- Every evaluated node is revealed, with the spec's payload -----------------


def test_evaluated_node_is_revealed_with_the_spec_payload(tree_database: str) -> None:
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.08)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.revealed == frozenset({root})
    observed = question.observed()
    assert set(observed) == {root}
    assert observed[root] == PolicyObservation(
        node_id=root,
        r2_insample=0.08**2,
        ic_insample=0.08,
        n_periods=EVALUATION_PERIODS,
        n_features=1,
    )


def test_r2_insample_is_ic_mean_squared_for_a_negative_ic(tree_database: str) -> None:
    # ic_mean squared must hold for a negative reading too — r2 is never
    # negative, and a bug that read `ic_mean * 2` or skipped the square would
    # only be caught by a value where the two disagree.
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=-0.2)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    observed = question.observed()[root]
    assert observed.ic_insample == -0.2
    assert observed.r2_insample == pytest.approx(0.04)


def test_a_zero_ic_mean_is_still_evaluated_and_revealed(tree_database: str) -> None:
    # ic_mean=0.0 is falsy but not NULL: a node that measured exactly zero
    # information coefficient was still evaluated, and a check written as
    # `if ic_mean` rather than `if ic_mean is not None` would wrongly treat
    # it as unmeasured.
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.0)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.revealed == frozenset({root})
    assert question.observed()[root].ic_insample == 0.0
    assert question.observed()[root].r2_insample == 0.0


# -- A node with no metrics is not revealed, but is still a legal move ---------


def test_unevaluated_node_is_not_revealed(tree_database: str) -> None:
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.05)
    pending = _plant_node(
        tree_database, campaign_id, parent_id=root, depth=1, ic_mean=None
    )

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert pending not in question.revealed
    assert pending not in question.observed()
    assert question.revealed == frozenset({root})


def test_unevaluated_node_is_still_a_legal_structural_move(tree_database: str) -> None:
    # Not revealed is a fact about the reveal set, not about the tree's
    # shape: an unmeasured node the tree holds is still a node
    # legal_actions() names, the fact a policy needs to find the batch it is
    # about to reveal.
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.05)
    pending = _plant_node(
        tree_database, campaign_id, parent_id=root, depth=1, ic_mean=None
    )

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.legal_actions(root) == [pending]


def test_unevaluated_node_answers_a_family_less_meta_rather_than_raising(
    tree_database: str,
) -> None:
    # meta() is a structural read, answered for revealed and unrevealed
    # nodes alike (docs §11.1) -- an empty-dict payload must not turn that
    # into a crash for a node this feature never reveals.
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=None)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    meta = question.meta(root)
    assert meta.theme_root is None
    assert meta.depth == 0
    assert meta.parent is None


def test_failed_node_with_no_metrics_is_indistinguishable_from_pending(
    tree_database: str,
) -> None:
    # The feature draws no distinction between "failed" and "not yet
    # evaluated": both are ic_mean IS NULL, and both are simply unrevealed.
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.05)
    failed = _plant_node(
        tree_database, campaign_id, parent_id=root, depth=1, ic_mean=None
    )
    pending = _plant_node(
        tree_database, campaign_id, parent_id=root, depth=1, ic_mean=None
    )

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.revealed == frozenset({root})
    assert set(question.legal_actions(root)) == {failed, pending}


# -- The tree is scoped to one campaign ----------------------------------------


def test_another_campaigns_nodes_are_excluded_from_the_tree(tree_database: str) -> None:
    # The table holds every campaign's rows; a live question over campaign A
    # must not see campaign B's nodes at all -- not revealed, not a legal
    # move, not addressable.
    campaign_a = str(uuid.uuid4())
    campaign_b = str(uuid.uuid4())
    root_a = _plant_node(tree_database, campaign_a, ic_mean=0.05)
    root_b = _plant_node(tree_database, campaign_b, ic_mean=0.09)

    question = live_question(
        campaign_a,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question.legal_roots() == [root_a]
    assert question.revealed == frozenset({root_a})
    with pytest.raises(PolicyAddressError):
        question.meta(root_b)


def test_two_campaigns_in_one_database_answer_independent_questions(
    tree_database: str,
) -> None:
    campaign_a = str(uuid.uuid4())
    campaign_b = str(uuid.uuid4())
    root_a = _plant_node(tree_database, campaign_a, ic_mean=0.05)
    root_b = _plant_node(tree_database, campaign_b, ic_mean=0.09)

    question_a = live_question(
        campaign_a,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )
    question_b = live_question(
        campaign_b,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert question_a.legal_roots() == [root_a]
    assert question_b.legal_roots() == [root_b]
    assert question_a.observed()[root_a].ic_insample == 0.05
    assert question_b.observed()[root_b].ic_insample == 0.09


# -- The tree is rebuilt from the rows on every call ---------------------------


def test_a_child_planted_between_two_calls_is_visible_in_the_next_round(
    tree_database: str,
) -> None:
    campaign_id = str(uuid.uuid4())
    root = _plant_node(tree_database, campaign_id, ic_mean=0.05)

    first = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )
    assert first.legal_actions(root) == []

    child = _plant_node(
        tree_database, campaign_id, parent_id=root, depth=1, ic_mean=None
    )

    second = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )
    assert second.legal_actions(root) == [child]
    # The first question is untouched by the second call -- each call is a
    # fresh freeze, not a shared, mutated tree.
    assert first.legal_actions(root) == []


def test_each_call_answers_a_distinct_question_over_a_distinct_tree(
    tree_database: str,
) -> None:
    campaign_id = str(uuid.uuid4())
    _plant_node(tree_database, campaign_id, ic_mean=0.05)

    first = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )
    second = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )
    assert first is not second
    assert first.tree is not second.tree


# -- The budget is forwarded untouched -----------------------------------------


def test_budget_is_forwarded_to_the_question(tree_database: str) -> None:
    campaign_id = str(uuid.uuid4())
    _plant_node(tree_database, campaign_id, ic_mean=0.05)
    account = budget_account(5.0)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
        budget=account,
    )

    assert float(question.budget_remaining()) == pytest.approx(5.0)


def test_no_budget_answers_unbounded(tree_database: str) -> None:
    campaign_id = str(uuid.uuid4())
    _plant_node(tree_database, campaign_id, ic_mean=0.05)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )

    assert float(question.budget_remaining()) == float("inf")


def test_a_bare_number_budget_is_the_questions_own_refusal(tree_database: str) -> None:
    # policy_runtime already owns this refusal (feature 221): a bare float
    # names no resource, and live_question forwards it rather than
    # re-wrapping it in its own vocabulary.
    campaign_id = str(uuid.uuid4())
    _plant_node(tree_database, campaign_id, ic_mean=0.05)

    with pytest.raises(PolicyBudgetError):
        live_question(
            campaign_id,
            database_url=tree_database,
            evaluation_periods=EVALUATION_PERIODS,
            budget=5.0,  # type: ignore[arg-type]
        )


# -- The wiring refusals --------------------------------------------------------


def test_refuses_a_campaign_with_no_rows(tree_database: str) -> None:
    with pytest.raises(LiveTreeError) as excinfo:
        live_question(
            str(uuid.uuid4()),
            database_url=tree_database,
            evaluation_periods=EVALUATION_PERIODS,
        )
    assert LIVE_TREE_CODE in str(excinfo.value)


def test_refuses_an_empty_campaign_id(tree_database: str) -> None:
    with pytest.raises(LiveTreeError):
        live_question(
            "   ",
            database_url=tree_database,
            evaluation_periods=EVALUATION_PERIODS,
        )


@pytest.mark.parametrize("bad_periods", [0, -1, 1.5, True, "500", None])
def test_refuses_a_bad_evaluation_periods(
    tree_database: str, bad_periods: object
) -> None:
    campaign_id = str(uuid.uuid4())
    _plant_node(tree_database, campaign_id, ic_mean=0.05)
    with pytest.raises(LiveTreeError):
        live_question(
            campaign_id,
            database_url=tree_database,
            evaluation_periods=bad_periods,  # type: ignore[arg-type]
        )


def test_refuses_a_non_sqlite_database_url() -> None:
    with pytest.raises(LiveTreeError):
        live_question(
            str(uuid.uuid4()),
            database_url="postgresql://localhost/nullius",
            evaluation_periods=EVALUATION_PERIODS,
        )


def test_refuses_an_in_memory_database_url() -> None:
    with pytest.raises(LiveTreeError):
        live_question(
            str(uuid.uuid4()),
            database_url="sqlite://",
            evaluation_periods=EVALUATION_PERIODS,
        )


def test_refuses_a_database_the_node_migration_has_not_reached(
    tmp_path: Path,
) -> None:
    url = f"sqlite:///{tmp_path / 'unmigrated.db'}"
    # Touch the file into existence with no table at all.
    sqlite3.connect(_path_of(url)).close()
    with pytest.raises(LiveTreeError):
        live_question(
            str(uuid.uuid4()),
            database_url=url,
            evaluation_periods=EVALUATION_PERIODS,
        )


def test_refuses_a_node_outside_the_tree_through_the_questions_own_address_seam(
    tree_database: str,
) -> None:
    # Not this module's refusal, but proof the question it hands back is the
    # real thing: an id the tree never held is refused by policy_runtime's
    # own address seam.
    campaign_id = str(uuid.uuid4())
    _plant_node(tree_database, campaign_id, ic_mean=0.05)
    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )
    with pytest.raises(PolicyAddressError):
        question.reveal("ghost")


# -- Never the sidecar, never a null bit ---------------------------------------


def test_module_imports_no_sidecar_owner_and_selects_no_null_column() -> None:
    # The module docstring *discusses* the sidecar and is_null in prose (to
    # state why neither is read), so a plain text search would false-positive
    # on the explanation. This parses the AST instead, and checks the two
    # places the code itself could actually reach them: no import of the
    # member that owns the sidecar, and no string literal outside a
    # docstring naming a null-bit-shaped column or path.
    import ast

    import orchestrator._live_tree as live_tree

    tree = ast.parse(Path(live_tree.__file__).read_text())

    imported_modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "nulloracle" not in imported_modules

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    code_strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert not any("is_null" in value for value in code_strings)
    assert not any("NULL_SIDECAR" in value for value in code_strings)
    assert not any("nulloracle" in value for value in code_strings)


def test_module_reads_only_the_declared_columns(tree_database: str) -> None:
    # A database carrying none of the identity, provenance or
    # authoring-model columns (migrations 0115-0117) still answers
    # correctly -- proof this feature's SELECT never names them.
    campaign_id = str(uuid.uuid4())
    present_columns = {
        row[1]
        for row in sqlite3.connect(_path_of(tree_database)).execute(
            "PRAGMA table_info(node)"
        )
    }
    assert present_columns == {
        "id",
        "parent_id",
        "campaign_id",
        "theme_root",
        "depth",
        "ic_mean",
        "ic_tstat",
        "ir_standalone",
        "ir_marginal",
        "turnover",
        "cost_adjusted_ir",
        "perturb_stability",
    }
    root = _plant_node(tree_database, campaign_id, ic_mean=0.08)

    question = live_question(
        campaign_id,
        database_url=tree_database,
        evaluation_periods=EVALUATION_PERIODS,
    )
    assert question.revealed == frozenset({root})


# -- The module's surface -------------------------------------------------------


def test_module_surface() -> None:
    import orchestrator._live_tree as live_tree

    assert set(live_tree.__all__) == {"LIVE_TREE_CODE", "LiveTreeError", "live_question"}
    assert issubclass(LiveTreeError, Exception)
    assert isinstance(LIVE_TREE_CODE, str) and LIVE_TREE_CODE
