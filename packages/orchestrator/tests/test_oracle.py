"""Feature 2, the subtree oracle — a node's root answers for its whole subtree.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 2:
*System creates a null-aware OracleResponse for any node of a campaign with
orchestrator._oracle.SubtreeOracle(endpoint, *, database_url).  This is a
callable evaluator Oracle, OracleRequest -> OracleResponse.*  The member is
wiring over Z0 — the evaluator owns the request and response records, the
nulloracle owns the route — so every test here runs the *real* seam: a
throwaway SQLite database brought to the ``node`` table's own migration, a
real :class:`evaluator.OracleRequest` handed to the oracle, a fake endpoint
that records the requests it receives, and the answer read back as a real
:class:`evaluator.OracleResponse`.

One test per claim the feature sentence makes:

* **the root walk** — a node's root is found by walking ``node.parent_id``
  until it is ``NULL``; a root is its own root, a child resolves to its root,
  a grandchild likewise.

* **children served under the root's id, at their own depth** — the recorded
  ``TargetRequest`` names the *root* (the sealed assignment's identity) and
  carries the *requested node's* depth, because the endpoint's Type-D flip
  resolves on the node actually being evaluated.

* **the OK map** — an ``OK`` answer becomes an ``OracleResponse`` carrying the
  endpoint's ``target_series`` and ``charges_budget``, unchanged.

* **any other status is refused** — a non-``OK`` status raises
  :class:`~orchestrator._oracle.OracleTargetError` (code word ``oracle_target``)
  carrying the status and the endpoint's detail; the endpoint is still called
  (the refusal is the route's answer, not a wiring fault).

* **a node with no row, and a runaway chain** — both raise the same class, and
  neither reaches the endpoint (there is no root id to post).

* **the barrier** — the module reads no null bit and holds no ``import
  nulloracle`` at module level: the branch is selected behind the route, and
  only a series and one directive cross back.

No test opens a network connection, reads a real credential, or writes outside
a pytest temporary directory.  Each test takes a fresh SQLite file (never
in-memory: the row a walk reaches must be visible to the connection the walk
opens, and an in-memory database is per-connection).
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from evaluator import OracleRequest, OracleResponse
from nulloracle.target import NOT_FOUND, OK, TargetResponse
from orchestrator._oracle import (
    MAX_PARENT_CHAIN,
    ORACLE_TARGET_CODE,
    OracleTargetError,
    SubtreeOracle,
    SubtreeOracleError,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up — tests -> orchestrator -> packages ->
# repo root — and the migrations live beside it under migrations/versions.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The migration that creates the ``node`` table (feature 97) — the only one
#: this feature's walk needs, because it reads ``id`` and ``parent_id`` alone
#: and never the metric columns ``0114`` adds.
NODE_TABLE_MIGRATIONS = ("0118_node_table",)

#: A stable, valid campaign id for every request this suite builds.
CAMPAIGN = "11111111-2222-3333-4444-555555555555"

#: The horizon's span — one week of daily bars, the range a request states.
DATE_RANGE = (dt.date(2026, 1, 5), dt.date(2026, 1, 9))


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is deliberately outside this member's
    file-claim scope; a migration is loaded by its runner the same way — by
    path — so loading it by path here is the shape a migration is *built* to
    be used in.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the node table's "
            "own migration rather than hand-writing its DDL, so it needs the "
            "schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_orchestrator_test_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database migrated to the node table."""
    url = f"sqlite:///{tmp_path / 'oracle-tree.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _plant(
    database_url: str, *, node_id: str, parent_id: str | None, depth: int
) -> str:
    """Insert one node row connected to its parent — raw SQL, the tree's own shape.

    The oracle under test only ever reads, so the test must plant the tree it
    walks.  ``parent_id`` is the edge the walk follows and ``NULL`` marks a
    root; the remaining structural columns take values ``0118`` declares.
    Returns the id, canonicalised, so a caller can assert on what it planted.
    """
    identifier = str(uuid.UUID(node_id))
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (identifier, parent_id, CAMPAIGN, "macro", depth),
        )
    return identifier


def _request(
    node_id: str,
    *,
    depth: int = 0,
    horizon: int = 5,
    campaign_id: str = CAMPAIGN,
) -> OracleRequest:
    """The evaluator's own ``OracleRequest``, the record that crosses the seam.

    A real record, not a lookalike: the feature claims an implementation of the
    evaluator's ``Oracle``, so the test hands the oracle exactly the request the
    evaluator's step 5 builds.
    """
    return OracleRequest(
        node_id=node_id,
        campaign_id=campaign_id,
        depth=depth,
        horizon=horizon,
        symbols=("AAA", "BBB"),
        date_range=DATE_RANGE,
    )


class RecordingEndpoint:
    """A fake ``TargetEndpoint``: records every request, answers one response.

    Stands in for ``nulloracle.TargetEndpoint`` so the test sees exactly what
    the oracle posted without a sidecar, a key, or a branch — the feature's own
    sentence, *tests use a fake endpoint that records requests*.
    """

    def __init__(self, response: TargetResponse) -> None:
        self.response = response
        self.requests: list[Any] = []

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
        return self.response


def _ok_response(root_id: str) -> TargetResponse:
    """An ``OK`` answer serving one bar, as the route would return it."""
    return TargetResponse(
        status=OK,
        node_id=root_id,
        target_series={DATE_RANGE[0]: {"AAA": 0.01, "BBB": -0.02}},
        charges_budget=True,
    )


# -- The root walk -------------------------------------------------------------


def test_a_root_node_is_its_own_root(tree_database: str) -> None:
    # The zero-link case: a node whose parent_id is NULL resolves to itself, and
    # a root's sealed assignment is therefore its own.
    node_id = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    endpoint = RecordingEndpoint(_ok_response(node_id))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    oracle(_request(node_id, depth=0))

    assert len(endpoint.requests) == 1
    assert endpoint.requests[0].node_id == node_id
    assert endpoint.requests[0].depth == 0


def test_a_child_is_served_under_the_roots_id_at_its_own_depth(
    tree_database: str,
) -> None:
    # The feature's headline claim.  The child has no sealed assignment of its
    # own; the walk climbs to the root, and the request names the ROOT — but the
    # depth stays the CHILD's, because the endpoint's Type-D flip resolves on the
    # node being evaluated, not on the node whose assignment is sealed.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    child = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=root, depth=1)
    endpoint = RecordingEndpoint(_ok_response(root))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    oracle(_request(child, depth=1))

    posted = endpoint.requests[0]
    assert posted.node_id == root
    assert posted.node_id != child
    assert posted.depth == 1


def test_a_grandchild_walks_the_whole_chain_to_the_root(tree_database: str) -> None:
    # More than one hop: the walk follows parent_id twice, root -> child ->
    # grandchild, and stops only at the NULL parent.  The depth carried is the
    # grandchild's own, three links down having moved the identity to the root.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    child = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=root, depth=1)
    grandchild = _plant(
        tree_database, node_id=str(uuid.uuid4()), parent_id=child, depth=2
    )
    endpoint = RecordingEndpoint(_ok_response(root))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    oracle(_request(grandchild, depth=2))

    posted = endpoint.requests[0]
    assert posted.node_id == root
    assert posted.depth == 2


def test_the_whole_request_moves_to_the_root_but_the_depth_does_not(
    tree_database: str,
) -> None:
    # Every §7.2 term is carried, and exactly one is substituted: node_id.  The
    # campaign, horizon, symbols and date_range are the request's own, so the
    # root's assignment is asked the child's question.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    child = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=root, depth=3)
    endpoint = RecordingEndpoint(_ok_response(root))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    request = _request(child, depth=3, horizon=10)
    oracle(request)

    posted = endpoint.requests[0]
    assert posted.campaign_id == request.campaign_id
    assert posted.horizon == request.horizon
    assert posted.symbols == request.symbols
    assert posted.date_range == request.date_range
    assert posted.depth == request.depth == 3
    assert posted.node_id == root


# -- The answer map ------------------------------------------------------------


def test_an_ok_answer_maps_to_the_evaluators_response(tree_database: str) -> None:
    # The return value is the evaluator's own OracleResponse, carrying the
    # endpoint's series and directive untouched — this module interprets
    # neither, it only relocates the identity.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    endpoint = RecordingEndpoint(_ok_response(root))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    answer = oracle(_request(root, depth=0))

    assert isinstance(answer, OracleResponse)
    assert answer.target_series[DATE_RANGE[0]]["AAA"] == 0.01
    assert answer.target_series[DATE_RANGE[0]]["BBB"] == -0.02
    assert answer.charges_budget is True


def test_a_false_directive_crosses_unchanged(tree_database: str) -> None:
    # charges_budget is the one bit that crosses (§7.2), and a False — the null
    # node's directive — must arrive as False, never coerced: a wrongly-True
    # directive would charge a node that spent no degrees of freedom.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    endpoint = RecordingEndpoint(
        TargetResponse(
            status=OK,
            node_id=root,
            target_series={DATE_RANGE[0]: {"AAA": 0.0}},
            charges_budget=False,
        )
    )
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    answer = oracle(_request(root, depth=0))

    assert answer.charges_budget is False


def test_a_non_ok_status_raises_carrying_status_and_detail(
    tree_database: str,
) -> None:
    # Any status but OK is the world saying no assignment covers this subtree.
    # The refusal carries the status and the endpoint's detail, so a caller reads
    # the figure and the reason off the exception — and the endpoint WAS called,
    # because the refusal is the route's answer and not a wiring fault.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    endpoint = RecordingEndpoint(
        TargetResponse(status=NOT_FOUND, node_id=root, detail="no sealed entry")
    )
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    with pytest.raises(OracleTargetError) as raised:
        oracle(_request(root, depth=0))

    assert ORACLE_TARGET_CODE in str(raised.value)
    assert "oracle_target" in str(raised.value)
    assert raised.value.status == NOT_FOUND
    assert raised.value.detail == "no sealed entry"
    assert len(endpoint.requests) == 1


def test_a_child_refused_by_the_endpoint_names_both_ids(tree_database: str) -> None:
    # When a child cannot be served, the refusal must let an operator tell which
    # node was asked for from which root answered — so both ids appear.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    child = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=root, depth=1)
    endpoint = RecordingEndpoint(
        TargetResponse(status=NOT_FOUND, node_id=root, detail="unknown root")
    )
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    with pytest.raises(OracleTargetError) as raised:
        oracle(_request(child, depth=1))

    message = str(raised.value)
    assert root in message
    assert child in message


# -- The tree refusals ---------------------------------------------------------


def test_a_node_the_tree_does_not_hold_is_refused(tree_database: str) -> None:
    # An id the tree does not hold names no row, and no row is not a root: the
    # walk has nothing to name, so it refuses before the endpoint is called.
    missing = str(uuid.uuid4())
    endpoint = RecordingEndpoint(_ok_response(missing))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    with pytest.raises(OracleTargetError) as raised:
        oracle(_request(missing, depth=0))

    assert ORACLE_TARGET_CODE in str(raised.value)
    assert missing in str(raised.value)
    assert raised.value.status is None
    assert endpoint.requests == []


def test_a_child_whose_parent_row_is_absent_is_refused(tree_database: str) -> None:
    # The requested node exists but its parent_id points at a row that is gone;
    # the walk reaches a missing link and refuses, naming the id it could not
    # resolve — the corruption is in the edge, not the requested node.
    dangling = str(uuid.uuid4())
    child = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=dangling, depth=1)
    endpoint = RecordingEndpoint(_ok_response(child))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    with pytest.raises(OracleTargetError) as raised:
        oracle(_request(child, depth=1))

    assert dangling in str(raised.value)
    assert endpoint.requests == []


def test_a_parent_chain_longer_than_the_limit_is_refused(tree_database: str) -> None:
    # A cycle (or a spine corrupted into one) never reaches a NULL parent.  The
    # walk is bounded, so it terminates and refuses by name rather than looping
    # forever — and the endpoint is never asked, because no root was named.
    # Built one link past the limit so the bound is exercised, not just the loop.
    path = _path_of(tree_database)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executemany(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (str(uuid.uuid4()), str(uuid.uuid4()), CAMPAIGN, "macro", i)
                for i in range(MAX_PARENT_CHAIN + 2)
            ],
        )
        # Wire each row's parent to the next, and close the last back onto the
        # first — a genuine cycle of MAX_PARENT_CHAIN + 2 links.
        rows = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM node ORDER BY depth"
            ).fetchall()
        ]
        for index, row_id in enumerate(rows):
            parent = rows[(index + 1) % len(rows)]
            connection.execute(
                "UPDATE node SET parent_id = ? WHERE id = ?", (parent, row_id)
            )
        start = rows[0]

    endpoint = RecordingEndpoint(_ok_response(start))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    with pytest.raises(OracleTargetError) as raised:
        oracle(_request(start, depth=0))

    assert str(MAX_PARENT_CHAIN) in str(raised.value)
    assert endpoint.requests == []


def test_a_deep_spine_resolves_to_its_root(tree_database: str) -> None:
    # The bound is on *links walked*, and every link of a legitimate spine is
    # followed: a chain of `depth` links resolves to the root at its top, with
    # the leaf's own depth carried in the ask.
    depth = 12
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    parent = root
    leaf = root
    for level in range(1, depth + 1):
        leaf = _plant(
            tree_database, node_id=str(uuid.uuid4()), parent_id=parent, depth=level
        )
        parent = leaf

    endpoint = RecordingEndpoint(_ok_response(root))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    oracle(_request(leaf, depth=depth))

    assert endpoint.requests[0].node_id == root
    assert endpoint.requests[0].depth == depth


# -- The barrier ---------------------------------------------------------------


def test_the_module_reads_no_null_bit_and_imports_no_sidecar_key() -> None:
    # The module must never read a node's null bit and never import the sidecar
    # key: it says so in prose, and this reads its import statements so a real
    # `import nulloracle` (or a sidecar/key module) added at module level fails.
    # Imports reached only inside a call are the deliberate exception — the route
    # members are resolved lazily on the call path — so the check reads the
    # top-level statements, where the module's standing dependencies live.
    import orchestrator._oracle as module

    tree = ast.parse(Path(module.__file__).read_text())
    top_level: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module.split(".")[0])
    assert "nulloracle" not in top_level
    assert "evaluator" not in top_level
    assert not any("sidecar" in name or "keyref" in name for name in top_level)
    assert sys.modules.get("orchestrator._oracle") is module


def test_the_module_never_selects_the_null_column(tree_database: str) -> None:
    # The tree holds no null column at all (0118), and the module reads only
    # parent_id.  This pins the observable half: the walk resolves and answers
    # correctly against a schema that has no bit to read, so a future edit that
    # presupposed one would fail to run rather than silently branch.
    root = _plant(tree_database, node_id=str(uuid.uuid4()), parent_id=None, depth=0)
    with closing(sqlite3.connect(_path_of(tree_database))) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(node)").fetchall()
        }
    assert "is_null" not in columns

    endpoint = RecordingEndpoint(_ok_response(root))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)
    assert isinstance(oracle(_request(root, depth=0)), OracleResponse)


# -- Wiring refusals and surface ----------------------------------------------


def test_an_endpoint_with_no_post_is_refused(tree_database: str) -> None:
    # A wiring fault, distinct from a tree refusal: an endpoint with no post has
    # nothing to ask.
    with pytest.raises(SubtreeOracleError):
        SubtreeOracle(object(), database_url=tree_database)
    with pytest.raises(SubtreeOracleError):
        SubtreeOracle(None, database_url=tree_database)


def test_a_url_this_module_cannot_speak_is_refused(tree_database: str) -> None:
    # Construction still succeeds (no I/O), but the call refuses a scheme, a
    # host and an in-memory URL by name — the same grammar every store restates.
    endpoint = RecordingEndpoint(_ok_response(str(uuid.uuid4())))
    with pytest.raises(SubtreeOracleError):
        SubtreeOracle(endpoint, database_url="")
    with pytest.raises(SubtreeOracleError):
        SubtreeOracle(endpoint, database_url="postgresql://localhost/tree")._root_of(
            str(uuid.uuid4())
        )
    with pytest.raises(SubtreeOracleError):
        SubtreeOracle(endpoint, database_url="sqlite:///:memory:")._root_of(
            str(uuid.uuid4())
        )


def test_a_database_without_the_node_migration_is_the_same_tree_refusal(
    tmp_path: Path,
) -> None:
    # A database the node migration has not reached has no table to walk.  From
    # the caller's view that is the same fact as an absent row — no place in a
    # tree — and the message names the migration that owns the table, because
    # SQLite's own "no such table" names no feature.
    url = f"sqlite:///{tmp_path / 'unmigrated.db'}"
    with closing(sqlite3.connect(_path_of(url))):
        pass
    endpoint = RecordingEndpoint(_ok_response(str(uuid.uuid4())))
    oracle = SubtreeOracle(endpoint, database_url=url)

    with pytest.raises(OracleTargetError) as raised:
        oracle(_request(str(uuid.uuid4()), depth=0))

    assert "0118_node_table" in str(raised.value)
    assert endpoint.requests == []


def test_a_request_that_names_no_node_is_refused(tree_database: str) -> None:
    # A request that names no node names no subtree; refused by name rather than
    # walked (there is no id to put in the WHERE clause).
    endpoint = RecordingEndpoint(_ok_response(str(uuid.uuid4())))
    oracle = SubtreeOracle(endpoint, database_url=tree_database)

    class _Nameless:
        node_id = ""
        campaign_id = CAMPAIGN
        depth = 0
        horizon = 5
        symbols = ("AAA",)
        date_range = DATE_RANGE

    with pytest.raises(OracleTargetError):
        oracle(_Nameless())


def test_the_module_exports_its_oracle_and_its_refusal_vocabulary() -> None:
    # The private module's surface: the oracle, the one target refusal and its
    # code word, the base error and the walk bound — so a caller reaching for
    # orchestrator._oracle finds the seam and the refusal it must handle.
    from orchestrator import _oracle

    assert set(_oracle.__all__) == {
        "MAX_PARENT_CHAIN",
        "ORACLE_TARGET_CODE",
        "OracleTargetError",
        "SubtreeOracle",
        "SubtreeOracleError",
    }
    assert issubclass(OracleTargetError, SubtreeOracleError)
    assert ORACLE_TARGET_CODE == "oracle_target"
    assert MAX_PARENT_CHAIN == 10000
