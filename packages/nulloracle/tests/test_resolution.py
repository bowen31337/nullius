"""Feature 121: resolving a Type-D request — real targets below the flip, permuted at or beyond it.

app_spec.xml, "Null Oracle & Planted Nulls", feature 121: *System resolves a
Type-D request by which returns real targets below the flip depth and
permuted targets at or beyond it.*  docs/nullius-tech-architecture.md §7.2
spells the rule this suite pins: *"below ``flip_depth`` the real targets are
returned, at or beyond it the permuted ones."*

Two halves, tested the way the member's other two-half features are:

* the *boundary* — :func:`nulloracle.resolution.past_the_flip`, the one
  comparison the whole resolution is — pinned in isolation the way
  ``test_flipdepth.py`` pins the geometric draw;
* the *resolution* — :class:`nulloracle.resolution.TypeDOracle` and the
  module-level :func:`nulloracle.resolve_type_d` — which reads the node's
  stored depth and its branch's stored flip (feature 119's) and serves one of
  the two series.

The sentence's load-bearing words are **below** and **at or beyond**, so the
tests below hold the resolution to both sides of the boundary: the request at
exactly the flip depth is the permuted branch, the request one above it the
real one, and a flip on the branch's root governs every descendant past it
(§7.3: *"every descendant past ``flip_depth`` is null"*).

Four properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* **the boundary is inclusive of the flip** — the node at exactly
  ``flip_depth`` is null, not the last real node;
* **the flip is inherited down the branch** — a request is resolved against
  the flip drawn on the branch, read by walking the ancestor chain, not
  against a flip on the requesting node alone;
* **the permuted branch is never served the real series** — a request past
  the flip with no permutation supplied is refused, because serving the real
  targets there would hand the caller real signal inside a world planted to
  have none;
* **the campaign must be the type that has flips** — a Type-R node's
  null-ness lives in the sidecar, and running the depth rule over it would
  serve real targets to a subtree the sidecar holds null.

The permutation itself is feature 115's, so this suite injects a stand-in
(a reversal) through the same seam the §7.2 endpoint will inject
``block_permute`` through — what is pinned here is *which branch* the oracle
picks, not how a null series is shuffled.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    FlipDepth,
    KsGuardError,
    SidecarError,
    TypeDOracle,
    TypeDResolution,
    past_the_flip,
    resolve_type_d,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0118_node_table.py"

#: The node table name — spelled by the store, and asserted against the
#: migration below.  Kept local so the helpers read.
NODE_TABLE = "node"

#: A stand-in permutation: a deterministic reversal of the series, injected
#: through the seam the §7.2 endpoint will inject ``block_permute`` through.
#: What is under test is *which branch* is served, so any fixed permutation
#: the tests can name on sight serves.
def _reversed(series: Any) -> tuple[float, ...]:
    return tuple(reversed(tuple(series)))


class _Spy:
    """A permutation that records every series it was handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[float, ...]] = []

    def __call__(self, series: Any) -> tuple[float, ...]:
        self.calls.append(tuple(series))
        return _reversed(series)


# -- Helpers ---------------------------------------------------------------------


def _store(tmp_path: Path, name: str = "resolution.db") -> tuple[TypeDOracle, str]:
    """A Type-D oracle over a fresh SQLite file, with its ``DATABASE_URL``."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return TypeDOracle(url), url


def _campaign(
    store: TypeDOracle, campaign_id: str | None = None, *, campaign_type: str = "Type-D"
) -> str:
    """Insert a campaign row the way its planner would, and return its id."""
    identifier = campaign_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, null_fraction) "
            f"VALUES (?, ?, 12, 0.25)",
            (identifier, campaign_type),
        )
    return identifier


def _node(
    store: TypeDOracle,
    campaign_id: str,
    node_id: str | None = None,
    *,
    depth: int,
    parent: str | None = None,
    flip: int | None = None,
) -> str:
    """Insert a node row the way the discovery loop would, and return its id.

    ``flip`` is set directly only where a test needs an exact drawn depth to
    pin the boundary against; the tests that exercise the 119→121 composition
    draw it through feature 119's own store instead.
    """
    identifier = node_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, depth, flip_depth) "
            "VALUES (?, ?, ?, 'macro', ?, ?)",
            (identifier, parent, campaign_id, depth, flip),
        )
    return identifier


def _chain(
    store: TypeDOracle, campaign_id: str, root: str, *, from_depth: int, to_depth: int
) -> list[str]:
    """A parent-linked chain below ``root``, from ``from_depth`` to ``to_depth``."""
    nodes: list[str] = []
    parent = root
    for depth in range(from_depth, to_depth + 1):
        parent = _node(store, campaign_id, depth=depth, parent=parent)
        nodes.append(parent)
    return nodes


def _migration():
    """``migrations/versions/0118_node_table.py``, loaded by path.

    By path rather than by import because that is how a migration runner loads
    it: the file is not a module on any package's ``sys.path``, and a test that
    could only reach it through an import would be testing a different
    arrangement from the one that runs.
    """
    spec = importlib.util.spec_from_file_location(
        "migration_0118_node_table", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    Autouse and unconditional, mirroring the member's other isolation
    fixtures: the default state of a test is a deployment that names no
    relational store, and the tests that assert on the *unconfigured*
    behaviour then do not fight a fixture that helpfully configured one.  Each
    test that wants a store builds its own over ``tmp_path``, so no test in
    this suite can reach a real database.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


# -- The boundary -----------------------------------------------------------------


class TestTheBoundary:
    def test_below_the_flip_is_not_past_it(self) -> None:
        # §7.2: "below flip_depth the real targets are returned" — strictly
        # below, so one above the flip is the real branch.
        assert past_the_flip(1, 3) is False
        assert past_the_flip(2, 3) is False

    def test_at_the_flip_is_past_it(self) -> None:
        # "at or beyond it the permuted ones": the node at exactly the flip
        # depth is the first null node of the branch, not the last real one —
        # §7.3 draws the depth the branch flips *at*.
        assert past_the_flip(3, 3) is True

    def test_beyond_the_flip_is_past_it(self) -> None:
        assert past_the_flip(4, 3) is True
        assert past_the_flip(100, 3) is True

    def test_a_root_is_never_past_a_drawn_flip(self) -> None:
        # The flip's support is {1, 2, 3, …}, so a root (depth 0) is strictly
        # below every flip that can be drawn — §7.3's "every root stays real",
        # seen from the resolution side.
        for flip in range(1, 40):
            assert past_the_flip(0, flip) is False

    def test_the_deepest_drawn_flip_keeps_the_shallow_branch_real(self) -> None:
        # A geometric draw of a very deep flip leaves a long real prefix —
        # the branch the campaign measured refinement on.
        assert past_the_flip(11, 12) is False
        assert past_the_flip(12, 12) is True


class TestTheBoundaryRefusesRatherThanGuesses:
    def test_a_boolean_depth_is_refused(self) -> None:
        # True is an int in Python, but it is not a depth anyone placed a node
        # at.
        with pytest.raises(KsGuardError, match="non-negative integer"):
            past_the_flip(True, 3)

    def test_a_non_integer_depth_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="non-negative integer"):
            past_the_flip("2", 3)
        with pytest.raises(KsGuardError, match="non-negative integer"):
            past_the_flip(1.5, 3)

    def test_a_negative_depth_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="non-negative integer"):
            past_the_flip(-1, 3)

    def test_a_boolean_flip_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="integer >= 1"):
            past_the_flip(2, True)

    def test_a_flip_below_one_is_refused(self) -> None:
        # A flip depth of 0 would turn a root null — retyping the campaign
        # §7.3 holds all roots real in.  The draw cannot produce it (the
        # geometric's support), and the read refuses it.
        with pytest.raises(KsGuardError, match="integer >= 1"):
            past_the_flip(2, 0)
        with pytest.raises(KsGuardError, match="integer >= 1"):
            past_the_flip(2, -3)

    def test_the_refusal_names_the_offending_value(self) -> None:
        with pytest.raises(KsGuardError) as raised:
            past_the_flip(2, 0)
        assert "0" in str(raised.value)
        assert "flip_depth" in str(raised.value)


# -- Below the flip: the real targets ---------------------------------------------


class TestTheRequestBelowTheFlipServesTheRealTargets:
    SERIES = (0.010, -0.020, 0.005, 0.030, -0.001, 0.012, -0.004, 0.008)

    def test_a_node_below_the_flip_is_served_its_real_targets(self, tmp_path: Path) -> None:
        # Feature 121's first half in one call: the request below the flip
        # gets the real series back, unchanged.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=4)
        node = _node(store, campaign, depth=3, parent=root)
        resolution = store.resolve_request(node, self.SERIES, permute=_reversed)
        assert resolution.real is True
        assert resolution.targets == self.SERIES

    def test_the_real_series_is_served_unchanged(self, tmp_path: Path) -> None:
        # Not re-encoded, not re-ordered, not rounded: the same series, in the
        # same order, that the request carried.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=2)
        node = _node(store, campaign, depth=1, parent=root)
        resolution = store.resolve_request(node, self.SERIES, permute=_reversed)
        assert resolution.targets == tuple(self.SERIES)
        assert list(resolution.targets) == list(self.SERIES)

    def test_the_real_branch_never_calls_the_permutation(self, tmp_path: Path) -> None:
        # The callable is the permuted branch's; a resolution that shuffled
        # the real series would be serving a permuted world below the flip.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=5)
        node = _node(store, campaign, depth=4, parent=root)
        spy = _Spy()
        resolution = store.resolve_request(node, self.SERIES, permute=spy)
        assert resolution.real is True
        assert spy.calls == []

    def test_a_root_carrying_its_own_branch_flip_resolves_real(self, tmp_path: Path) -> None:
        # §7.3 draws the flip on the branch's root; the root itself sits at
        # depth 0 and is strictly below every drawable flip, so the root that
        # carries the flip is the first real node of its own branch.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=1)
        resolution = store.resolve_request(root, self.SERIES, permute=_reversed)
        assert resolution.real is True
        assert resolution.targets == self.SERIES

    def test_the_same_request_resolves_identically_twice(self, tmp_path: Path) -> None:
        # §12's determinism contract from the resolution side: the same
        # request, twice, against the same stored facts, is the same answer.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=3)
        node = _node(store, campaign, depth=2, parent=root)
        first = store.resolve_request(node, self.SERIES, permute=_reversed)
        second = store.resolve_request(node, self.SERIES, permute=_reversed)
        assert first == second


# -- At or beyond the flip: the permuted targets -----------------------------------


class TestTheRequestAtOrBeyondTheFlipServesThePermutedTargets:
    SERIES = (0.010, -0.020, 0.005, 0.030, -0.001, 0.012, -0.004, 0.008)

    def test_the_node_at_the_flip_is_served_the_permuted_targets(self, tmp_path: Path) -> None:
        # Feature 121's second half, at its boundary case: depth == flip is
        # the permuted branch ("at or beyond it").
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=3)
        node = _node(store, campaign, depth=3, parent=root)
        resolution = store.resolve_request(node, self.SERIES, permute=_reversed)
        assert resolution.real is False
        assert resolution.targets == _reversed(self.SERIES)

    def test_a_node_beyond_the_flip_is_served_the_permuted_targets(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=2)
        node = _node(store, campaign, depth=7, parent=root)
        resolution = store.resolve_request(node, self.SERIES, permute=_reversed)
        assert resolution.real is False
        assert resolution.targets == _reversed(self.SERIES)

    def test_the_permutation_receives_the_real_series(self, tmp_path: Path) -> None:
        # §7.2 permutes the forward returns — the real series is the input to
        # the permutation, not something the oracle may substitute for.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=1)
        node = _node(store, campaign, depth=2, parent=root)
        spy = _Spy()
        store.resolve_request(node, self.SERIES, permute=spy)
        assert spy.calls == [tuple(self.SERIES)]

    def test_both_branches_answer_the_same_call(self, tmp_path: Path) -> None:
        # §7.3: "nothing in the revealed prefix marks the transition."  The
        # two branches answer one call shape, return one value shape, and
        # differ only in the series served — the flip is silent to everything
        # downstream of this value.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=3)
        below = _node(store, campaign, depth=2, parent=root)
        past = _node(store, campaign, depth=3, parent=root)
        real_resolution = store.resolve_request(below, self.SERIES, permute=_reversed)
        null_resolution = store.resolve_request(past, self.SERIES, permute=_reversed)
        assert set(real_resolution.to_payload()) == set(null_resolution.to_payload())
        assert type(real_resolution) is type(null_resolution)
        assert real_resolution.targets != null_resolution.targets

    def test_a_request_past_the_flip_with_no_permutation_is_refused(self, tmp_path: Path) -> None:
        # Serving the real series past the flip would hand the caller real
        # signal inside a world planted to have none — refused, never guessed.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=2)
        node = _node(store, campaign, depth=4, parent=root)
        with pytest.raises(KsGuardError, match="no permute was supplied") as raised:
            store.resolve_request(node, self.SERIES)
        assert "block_permute" in str(raised.value)

    def test_a_non_callable_permutation_is_refused(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=2)
        node = _node(store, campaign, depth=4, parent=root)
        with pytest.raises(KsGuardError, match="must be callable"):
            store.resolve_request(node, self.SERIES, permute="block_permute")

    def test_a_permutation_of_a_different_length_is_refused(self, tmp_path: Path) -> None:
        # §7.2 promises the caller cannot distinguish the two branches from
        # the response; a different length would mark the branch as plainly
        # as an is_null column would.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=1)
        node = _node(store, campaign, depth=2, parent=root)
        with pytest.raises(KsGuardError, match="different length") as raised:
            store.resolve_request(node, self.SERIES, permute=lambda series: series[:-1])
        assert "mark the branch" in str(raised.value)

    def test_a_permutation_that_returns_a_non_series_is_refused(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=1)
        node = _node(store, campaign, depth=2, parent=root)
        with pytest.raises(KsGuardError, match="sequence of finite reals"):
            store.resolve_request(node, self.SERIES, permute=lambda series: "permuted")

    def test_a_permutation_that_returns_a_non_finite_series_is_refused(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=1)
        node = _node(store, campaign, depth=2, parent=root)
        with pytest.raises(KsGuardError, match="finite"):
            store.resolve_request(
                node, self.SERIES, permute=lambda series: tuple(series[:-1]) + (float("nan"),)
            )


# -- The flip is inherited down the branch ------------------------------------------


class TestTheFlipIsInheritedDownTheBranch:
    SERIES = (0.010, -0.020, 0.005, 0.030, -0.001, 0.012)

    def test_the_whole_branch_resolves_against_the_roots_draw(self, tmp_path: Path) -> None:
        # The headline composition: feature 119 draws the flip through its own
        # store, feature 121 resolves every depth of the branch against it —
        # real below the drawn depth, permuted from it down, root real.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0)
        drawn = FlipDepth(store.database_url).persist(root, 0.3)
        assert drawn >= 1
        nodes = _chain(store, campaign, root, from_depth=1, to_depth=drawn + 3)
        # The root itself stays real (§7.3), and so does every node strictly
        # below the draw.
        assert store.resolve_request(root, self.SERIES, permute=_reversed).real is True
        for depth, node in enumerate(nodes, start=1):
            resolution = store.resolve_request(node, self.SERIES, permute=_reversed)
            assert resolution.flip_depth == drawn
            assert resolution.real is (depth < drawn)
            assert resolution.depth == depth

    def test_a_flip_drawn_on_an_interior_ancestor_governs_its_descendants(self, tmp_path: Path) -> None:
        # The walk collects the flip from wherever on the chain it was drawn,
        # not only from the root: a branch that flipped at an interior node
        # keeps every descendant past that node null.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0)
        interior = _node(store, campaign, depth=1, parent=root, flip=2)
        deep = _node(store, campaign, depth=4, parent=interior)
        resolution = store.resolve_request(deep, self.SERIES, permute=_reversed)
        assert resolution.real is False
        assert resolution.flip_depth == 2

    def test_where_several_draws_land_the_shallowest_decides(self, tmp_path: Path) -> None:
        # §7.3's flip is irreversible: past a flip is past.  Where one chain
        # carries several stored draws, the branch went null at the shallowest
        # — a deeper draw on an already-null branch marks no transition.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=3)
        interior = _node(store, campaign, depth=1, parent=root, flip=5)
        past = _node(store, campaign, depth=4, parent=interior)
        above = _node(store, campaign, depth=2, parent=interior)
        # Depth 4 is past the root's flip 3 even though the interior re-draw
        # says 5: the branch was null from depth 3.
        resolution = store.resolve_request(past, self.SERIES, permute=_reversed)
        assert resolution.real is False
        assert resolution.flip_depth == 3
        # Depth 2 is below the shallowest draw, so it is real — resolved
        # against 3, the boundary the branch actually has.
        resolution = store.resolve_request(above, self.SERIES, permute=_reversed)
        assert resolution.real is True
        assert resolution.flip_depth == 3

    def test_an_undrawn_branch_is_refused(self, tmp_path: Path) -> None:
        # A branch nobody drew a flip for cannot be resolved — serving the
        # real targets would read as "no flip" while the campaign loop
        # believed it had drawn one.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0)
        node = _node(store, campaign, depth=1, parent=root)
        with pytest.raises(KsGuardError, match="no flip_depth is drawn") as raised:
            store.resolve_request(node, self.SERIES, permute=_reversed)
        assert "undrawn branch" in str(raised.value)

    def test_a_cycle_in_the_ancestor_chain_is_refused(self, tmp_path: Path) -> None:
        # A tree whose parent edges form a cycle is a branch whose flip can
        # never be found by walking; the walk refuses rather than loop.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, 'macro', 2)",
                (first, second, campaign),
            )
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, depth, flip_depth) "
                "VALUES (?, ?, ?, 'macro', 3, 4)",
                (second, first, campaign),
            )
        with pytest.raises(KsGuardError, match="revisits"):
            store.resolve_request(first, self.SERIES, permute=_reversed)

    def test_a_dangling_parent_is_refused(self, tmp_path: Path) -> None:
        # A parent the table does not hold is a missing link in the same walk;
        # the branch's flip cannot be found, so the request is refused.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign, depth=2, parent=str(uuid.uuid4()))
        with pytest.raises(KsGuardError, match="is not held by the node table"):
            store.resolve_request(node, self.SERIES, permute=_reversed)


# -- The campaign must be the type that has flips ------------------------------------


class TestTheCampaignMustBeTypeD:
    SERIES = (0.010, -0.020, 0.005, 0.030)

    def test_a_type_r_campaign_is_refused_by_name(self, tmp_path: Path) -> None:
        # §7.3: campaigns are homogeneous in null type.  A Type-R node's
        # null-ness lives in §7.1's sidecar, and running the depth rule over
        # it would serve real targets to a subtree the sidecar holds null.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, campaign_type="Type-R")
        root = _node(store, campaign, depth=0, flip=2)
        node = _node(store, campaign, depth=3, parent=root)
        with pytest.raises(KsGuardError, match="is a 'Type-R' campaign") as raised:
            store.resolve_request(node, self.SERIES, permute=_reversed)
        assert "homogeneous" in str(raised.value)

    def test_a_node_whose_campaign_row_is_missing_is_refused(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        orphan_campaign = str(uuid.uuid4())
        root = _node(store, orphan_campaign, depth=0, flip=2)
        with pytest.raises(KsGuardError, match="holds no row"):
            store.resolve_request(root, self.SERIES, permute=_reversed)

    def test_a_node_the_table_does_not_hold_is_refused(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="holds no row for") as raised:
            store.resolve_request(str(uuid.uuid4()), self.SERIES, permute=_reversed)
        assert "discovery loop" in str(raised.value)

    def test_a_node_that_names_no_campaign_is_refused(self, tmp_path: Path) -> None:
        # The schema's own ``campaign_id NOT NULL`` makes this row
        # unconstructable through the store's schema — the constraint is the
        # first line of defence, and the oracle's ``names no campaign``
        # refusal is the read-side backstop for a store that predates it.  A
        # table without the constraint is created directly so the backstop is
        # pinned rather than trusted.
        path = tmp_path / "loose.db"
        url = f"sqlite:///{path}"
        orphan = str(uuid.uuid4())
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                f"CREATE TABLE {NODE_TABLE} ("
                "id TEXT PRIMARY KEY, parent_id TEXT, campaign_id TEXT, "
                "theme_root TEXT NOT NULL, depth INT NOT NULL, flip_depth INT)"
            )
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
                "VALUES (?, NULL, 'macro', 1)",
                (orphan,),
            )
        oracle = TypeDOracle(url)
        with pytest.raises(KsGuardError, match="names no campaign"):
            oracle.resolve_request(orphan, self.SERIES, permute=_reversed)

    def test_a_malformed_node_id_is_a_store_error_not_a_sidecar_one(self, tmp_path: Path) -> None:
        # The taxonomy's distinction: a malformed id handed to the resolution
        # is a store-contract failure.  A caller reading ``SidecarError`` out
        # of a Type-D request would look in the wrong module for the cause.
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="is not a UUID") as raised:
            store.resolve_request("not-a-uuid", self.SERIES)
        assert not isinstance(raised.value, SidecarError)
        assert isinstance(raised.value.__cause__, SidecarError)

    def test_a_corrupt_stored_depth_is_refused(self, tmp_path: Path) -> None:
        # The depth is the tree's own fact about the node; a row carrying
        # something that is not a depth is a row no comparison could trust.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=2)
        node = _node(store, campaign, depth=3, parent=root)
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {NODE_TABLE} SET depth = 'three' WHERE id = ?", (node,)
            )
        with pytest.raises(KsGuardError, match="carries depth"):
            store.resolve_request(node, self.SERIES, permute=_reversed)

    def test_a_corrupt_stored_flip_is_refused(self, tmp_path: Path) -> None:
        # A stored flip below 1 would turn a root null from the read side —
        # the invariant feature 119 guarantees structurally at the draw, held
        # at the read.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=0)
        node = _node(store, campaign, depth=1, parent=root)
        with pytest.raises(KsGuardError, match="carries flip_depth") as raised:
            store.resolve_request(node, self.SERIES, permute=_reversed)
        assert "root" in str(raised.value)


# -- The request's own depth claim ----------------------------------------------------


class TestTheRequestDepth:
    SERIES = (0.010, -0.020, 0.005, 0.030)

    def test_a_claim_that_agrees_with_the_tree_resolves(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=4)
        node = _node(store, campaign, depth=3, parent=root)
        resolution = store.resolve_request(node, self.SERIES, permute=_reversed, depth=3)
        assert resolution.real is True

    def test_a_claim_that_disagrees_with_the_tree_is_refused(self, tmp_path: Path) -> None:
        # §7.2's request carries the node's depth; a disagreeing claim would
        # let a request move itself across the flip, so it is refused rather
        # than quietly preferred to the row.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=4)
        node = _node(store, campaign, depth=3, parent=root)
        with pytest.raises(KsGuardError, match="claims depth") as raised:
            store.resolve_request(node, self.SERIES, permute=_reversed, depth=2)
        assert "the tree holds 3" in str(raised.value)

    def test_a_malformed_claim_is_refused(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=4)
        node = _node(store, campaign, depth=3, parent=root)
        with pytest.raises(KsGuardError, match="non-negative integer"):
            store.resolve_request(node, self.SERIES, permute=_reversed, depth="3")


# -- The value ------------------------------------------------------------------------


class TestTheResolutionValue:
    SERIES = (0.010, -0.020, 0.005)

    def _value(self, **overrides: Any) -> TypeDResolution:
        fields = {
            "node_id": "6ee6bf93-8326-48f8-b4d5-921662768f45",
            "depth": 2,
            "flip_depth": 4,
            "real": True,
            "targets": self.SERIES,
        }
        fields.update(overrides)
        return TypeDResolution(**fields)

    def test_the_value_is_frozen(self) -> None:
        resolution = self._value()
        with pytest.raises(AttributeError, match="frozen"):
            resolution.real = False  # type: ignore[misc]

    def test_the_payload_names_the_five_fields(self) -> None:
        payload = self._value().to_payload()
        assert set(payload) == {
            "node_id",
            "depth",
            "flip_depth",
            "real",
            "targets",
        }
        assert payload["targets"] == list(self.SERIES)

    def test_a_non_bool_real_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="genuine bool"):
            self._value(real="yes")

    def test_a_value_that_cannot_explain_itself_is_refused(self) -> None:
        # depth 4 is at the flip 4, so a value claiming the real branch there
        # is a resolution that contradicts its own two integers.
        with pytest.raises(KsGuardError, match="disagree"):
            self._value(depth=4, real=True)

    def test_the_targets_are_validated_on_the_value_too(self) -> None:
        # ``dataclasses.replace``-style rebuilds go through the same
        # validation as the store's construction path.
        with pytest.raises(KsGuardError, match="sequence of finite reals"):
            self._value(targets=42)
        with pytest.raises(KsGuardError, match="empty"):
            self._value(targets=())


# -- The store and the migration are one schema ----------------------------------------


class TestTheStoreMirrorsTheMigration:
    SERIES = (0.010, -0.020, 0.005, 0.030)

    def test_the_store_resolves_against_a_migration_created_table(self, tmp_path: Path) -> None:
        # The production arrangement: the node table is the migration's, the
        # flip was drawn by feature 119's store, and the resolution reads both
        # back.  The campaign table is the store's own to create.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        url = f"sqlite:///{theirs_path}"
        campaign = str(uuid.uuid4())
        root = str(uuid.uuid4())
        oracle = TypeDOracle(url)
        with closing(oracle._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, null_fraction) "
                "VALUES (?, 'Type-D', 12, 0.25)",
                (campaign,),
            )
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, 'macro', 0)",
                (root, campaign),
            )
        drawn = FlipDepth(url).persist(root, 0.5)
        child = str(uuid.uuid4())
        with closing(oracle._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, 'macro', ?)",
                (child, root, campaign, drawn),
            )
        below = oracle.resolve_request(root, self.SERIES, permute=_reversed)
        past = oracle.resolve_request(child, self.SERIES, permute=_reversed)
        assert below.real is True
        assert past.real is False
        assert below.targets == self.SERIES
        assert past.targets == _reversed(self.SERIES)

    def test_the_store_adds_the_flip_depth_column_to_the_migration_table(self, tmp_path: Path) -> None:
        # The oracle opens the migration's five-column node table and ends up
        # with feature 119's column, exactly as the flip-depth store does —
        # the two stores' schemas are one schema.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        TypeDOracle(f"sqlite:///{theirs_path}")._connect().close()
        with closing(sqlite3.connect(theirs_path)) as connection:
            columns = [
                row[1] for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")
            ]
        assert "flip_depth" in columns


# -- The store's own refusals -----------------------------------------------------------


class TestTheStoreRefusesRatherThanGuesses:
    SERIES = (0.010, -0.020, 0.005)

    def test_the_store_refuses_a_url_it_cannot_speak(self) -> None:
        with pytest.raises(KsGuardError, match="unsupported") as raised:
            TypeDOracle("postgres:///db").resolve_request(
                str(uuid.uuid4()), self.SERIES
            )
        assert "sqlite" in str(raised.value)

    def test_an_in_memory_url_is_refused(self) -> None:
        # An in-memory database dies with the connection that opened it, and
        # a resolution read from one would be a resolution no replay could
        # reproduce.
        with pytest.raises(KsGuardError, match="no database path"):
            TypeDOracle("sqlite:///:memory:").resolve_request(
                str(uuid.uuid4()), self.SERIES
            )

    def test_a_malformed_series_is_refused_before_the_store_opens(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="sequence of finite reals"):
            store.resolve_request(str(uuid.uuid4()), "0.01,0.02")
        with pytest.raises(KsGuardError, match="empty"):
            store.resolve_request(str(uuid.uuid4()), [])

    def test_an_empty_database_url_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="non-empty database URL"):
            TypeDOracle("   ")


# -- Resolution -------------------------------------------------------------------------


class TestResolve:
    def test_an_unset_database_url_resolves_to_none(self) -> None:
        assert TypeDOracle.resolve() is None

    def test_a_blank_database_url_resolves_to_none(self) -> None:
        assert TypeDOracle.resolve(env={DATABASE_URL_ENV: "   "}) is None

    def test_a_named_database_url_resolves_to_an_oracle(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'resolution.db'}"
        resolved = TypeDOracle.resolve(env={DATABASE_URL_ENV: url})
        assert isinstance(resolved, TypeDOracle)
        assert resolved.database_url == url


# -- The module-level spelling -------------------------------------------------------------


class TestTheModuleLevelSpelling:
    SERIES = (0.010, -0.020, 0.005, 0.030)

    def test_it_resolves_the_same_request_the_store_does(self, tmp_path: Path) -> None:
        store, url = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=2)
        node = _node(store, campaign, depth=3, parent=root)
        assert resolve_type_d(node, self.SERIES, permute=_reversed, database_url=url) == (
            store.resolve_request(node, self.SERIES, permute=_reversed)
        )

    def test_nothing_naming_a_store_answers_none(self, tmp_path: Path) -> None:
        # The same "no store, no resolution" answer the classmethod gives,
        # kept distinct because a caller that mistook an unconfigured
        # deployment for an unresolved request would serve nothing while
        # believing it had resolved a world.
        assert resolve_type_d(str(uuid.uuid4()), self.SERIES) is None
        assert resolve_type_d(str(uuid.uuid4()), self.SERIES, env={}) is None

    def test_the_environment_names_the_store(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store, url = _store(tmp_path)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, flip=2)
        monkeypatch.setenv(DATABASE_URL_ENV, url)
        resolution = resolve_type_d(root, self.SERIES, permute=_reversed)
        assert resolution is not None
        assert resolution.real is True
