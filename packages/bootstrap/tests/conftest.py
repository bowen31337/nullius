"""Fixtures for the bootstrap member's own suite.

This suite lives inside the workspace member (``packages/bootstrap/tests``)
rather than under the repository-level ``tests/`` tree, because the member
— including its tests — is this feature's file-claim scope, and the
placement is the one the artifacts, sandbox and canary members take for
the same reason: same-basename files collide under one pytest run, so each
member's suite is collected under its own conftest.

There is very little to isolate here, and that is a fact about the feature
rather than an omission.  The siblings that *do* need isolation are the
ones bound to a deployment — the artifact store's ``ARTIFACT_ROOT``, the
null sidecar's ``NULL_SIDECAR_PATH``, the dedup gate's ``DATABASE_URL`` —
and a bootstrap *world* is bound to nothing but its own seed.  It writes
no file, opens no database, reads no environment variable and consults no
clock (docs/nullius-tech-architecture.md §10.6: the worlds give *"no
dependence on market time"*).  So there is no ambient state for a world
test to leak into, and no autouse fixture guarding one.

Feature 188's pool changed that for exactly one object, and the fixtures
grew with it: the pool persists into the database ``DATABASE_URL`` names,
so its tests need a per-test SQLite file the way the tripwires member's
do — a fixture asked for by name, never autouse, because a *world* test
must not acquire a database by accident and the world half of this suite
stays as ambient-free as it was.  The pool fixture is derived from the
same URL rather than given its own file for the tests that need two
stores over one database (a re-read proving persistence, a second store
proving refresh).

What the fixtures below are, then, is the *vocabulary* the tests are
written in: the canonical world, a couple of named cells, the committed
seed and id the package publishes, and — for the pool's suite — the
database URL and the pool over it.  Naming them once keeps the tests
reading as claims about the world rather than as constructions of it.

The path bootstrap puts both import roots on ``sys.path`` regardless of how
pytest was invoked — the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/`` (for
``bootstrap`` itself) — the same bootstrap every member suite in this
workspace performs, so the suite is identical under ``uv run pytest``
(where the venv also provides both) and under a bare ``pytest``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# conftest.py -> packages/bootstrap/tests -> packages/bootstrap -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "bootstrap" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from bootstrap import (
    FEATSEL_SEED,
    FEATSEL_WORLD_ID,
    HYPERPARAMETER_WORLD_ID,
    PRICED_SEED,
    SYMREG_SEED,
    SYMREG_WORLD_ID,
    FeatureSelectionWorld,
    HyperparameterSetting,
    HyperparameterWorld,
    SymbolicRegressionWorld,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; the fixture imports lazily
    from bootstrap import BootstrapPool


@pytest.fixture
def world() -> HyperparameterWorld:
    """The committed world — the id and seed this package publishes.

    Built through the public constructor rather than reached off the
    composed application, because a test of the *world* should not depend
    on the factory having scanned anything; the component tests reach the
    composed one separately.
    """
    return HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)


@pytest.fixture
def other_world() -> HyperparameterWorld:
    """A second world, same lattice, a different seed.

    For the tests that pin what a *world* is: two worlds may share a
    lattice and still be different worlds, which is
    docs/nullius-tech-architecture.md §10.6.1's provenance rule
    (``An upstream that changes is a different world, not an updated
    one``) seen from the authored side.
    """
    return HyperparameterWorld("bootstrap-hpo-other", seed=PRICED_SEED + 1)


@pytest.fixture
def root_node(world: HyperparameterWorld) -> str:
    """The world's root node id — where a walk starts."""
    return world.canonical_node()


@pytest.fixture
def wide_node() -> str:
    """A node at the wide end of the lattice: ``degree=2`` with interactions.

    The setting the committed world's optimum sits at (see
    ``test_world.py``), so the tests that need "a node with a real score"
    name one that is not the root and is not degenerate.
    """
    return "d+1.i+1.s+0.a+3"


@pytest.fixture
def setting() -> HyperparameterSetting:
    """A setting built by keyword — the value type on its own.

    ``degree=2`` with interactions, standardised, at the middle ridge —
    a point three axes off the root, so a test using it is exercising a
    setting that is *not* the canonical one.
    """
    return HyperparameterSetting(
        degree=2, interactions=True, standardize=True, alpha=1.0
    )


# -- Feature 183's world: the symbolic regression vocabulary -------------------


@pytest.fixture
def symreg_world() -> SymbolicRegressionWorld:
    """The committed symbolic regression world — 183's published id and seed.

    Built through the public constructor, on the same terms as ``world``:
    a test of the world should not depend on the factory having scanned
    anything.  Its target is drawn from the committed seed, and the
    oracle cell its lattice holds is derived from that target by the
    tests rather than named by the world — the answer key is the target,
    published, and the cell is a fact about it.
    """
    return SymbolicRegressionWorld(SYMREG_WORLD_ID, seed=SYMREG_SEED)


@pytest.fixture
def symreg_root_node(symreg_world: SymbolicRegressionWorld) -> str:
    """The symbolic world's root node id — where a symreg walk starts."""
    return symreg_world.canonical_node()


# -- Feature 182's world: the feature selection vocabulary ----------------------


@pytest.fixture
def featsel_world() -> FeatureSelectionWorld:
    """The committed feature selection world — 182's published id and seed.

    Built through the public constructor, on the same terms as ``world``
    and ``symreg_world``: a test of the world should not depend on the
    factory having scanned anything.  Its known support is drawn from
    the committed seed and published whole, and the oracle cell its
    lattice holds is derived from that support by the tests rather than
    named by the world — the answer key is the support, published, and
    the cell is a fact about it.
    """
    return FeatureSelectionWorld(FEATSEL_WORLD_ID, seed=FEATSEL_SEED)


@pytest.fixture
def featsel_root_node(featsel_world: FeatureSelectionWorld) -> str:
    """The feature selection world's root node id — where a featsel walk starts."""
    return featsel_world.canonical_node()


# -- Feature 188's reach: a database, on purpose, for the pool's tests ---------


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a pool file only this test can see.

    The repository-level conftest points ``DATABASE_URL`` at a per-test
    SQLite file for every suite under ``tests/``; this suite is not under
    ``tests/``, so the isolation is restated rather than inherited — the
    same fixture the tripwires member's conftest spells for its own
    stores.  Deliberately **not** autouse and deliberately not exported
    into the environment: a world test must not acquire a database by
    accident, and a pool test that wants one asks for this fixture by
    name.
    """
    return f"sqlite:///{tmp_path / 'bootstrap-pool-test.db'}"


@pytest.fixture
def pool(database_url: str) -> BootstrapPool:
    """Feature 188's pool, pointed at this test's own database.

    Imported inside the fixture so the module-level import list of this
    file stays what it was for every world test — the member's package
    ``__init__`` is reached either way, but a reader scanning the imports
    should not have to work out that ``pool`` is the only thing that
    pulls the store in.
    """
    from bootstrap import BootstrapPool

    return BootstrapPool(database_url)
