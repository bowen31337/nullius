"""Suite-local fixtures for the tripwires package's tests.

This suite lives inside the workspace member (``packages/tripwires/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
Feature 125's probe needs none of them: it is a pure function of plain
mappings, so there is no lake to isolate, no database to point at and no
environment to clear.  The probe's own tests still need none of them, and that
is a property worth keeping stated — a probe test that needed a temp lake would
mean the probe had grown a dependency it is not allowed to have.

**Feature 131 is where a database enters this suite, and it enters on purpose.**
Poisoning "the node together with its entire subtree" is the transitive closure
of the discovery tree's ``parent_id``, and no verdict carries that: the feature
had to reach a store, so its tests have to reach one too.  The fixtures below
are that reach and nothing more — a SQLite file under the test's own temporary
directory, and a store pointed at it.  They are deliberately *named*
for what they are (``database_url``, ``poison_store``) rather than folded into
an autouse fixture, so a probe test reads as one that touches no database:
:func:`test_the_probe_suite_still_needs_no_database` pins exactly that, and it
is the reason these are not autouse.

**Feature 132 arrives on the same file, and that is the feature.**  Excising a
poisoned branch from the replay pool is a *join* between the marks feature 131
writes and the ``replay_score`` rows the pool holds, so its two fixtures —
``pool`` and ``other_pool`` — share this file rather than each taking their own.
Two files would make every excision test pass for the wrong reason: nothing the
pool read would ever be marked, so nothing would ever be refused.

The isolation is the repository-level conftest's pattern, restated here because
that conftest genuinely does not reach this directory: ``tmp_path`` for the
file, so two tests never share a database and no test can write into a
deployment's real store.

This file holds *fixtures only*.  The panel builders — ``monday``,
``gaussian_panel``, ``lookahead_panel``, ``symbols`` — live beside it in
:mod:`_panels`, because they are pure functions rather than fixtures and
because ``conftest`` is a module name every member suite in this workspace
reuses: importing helpers from it works only while exactly one such suite is
collected, and fails with an ``ImportError`` from a sibling's file otherwise.
See :mod:`_panels`' docstring for the full account.

The path bootstrap below puts two trees on ``sys.path``:

* the member's ``src/``, because the root project does not depend on this
  member and the venv therefore does not install it — the same mechanism the
  module loader uses when it scans members;
* the tests directory itself, so ``from _panels import ...`` resolves the way
  the other member suites' ``from conftest import ...`` does (pytest inserts a
  test file's directory for rootdir-relative imports under the default
  ``prepend`` import mode, but doing it explicitly keeps this suite working
  under ``--import-mode=importlib`` too).

This suite runs with the repository's pytest:
``uv run --all-packages pytest packages/tripwires``.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MEMBER_SRC = _HERE.parent / "src"
_FACTORY_SRC = _HERE.parents[2] / "src"
for _path in (_MEMBER_SRC, _FACTORY_SRC, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# Imported after the sys.path bootstrap above, and after ``import pytest``:
# ``_panels`` is not importable until this file's own directory is on the
# path. The alias keeps the builder and the fixture below from being two
# spellings of one identifier in one namespace.
from _panels import DEFAULT_GRID, DEFAULT_SYMBOLS, monday
from _panels import symbols as symbol_names


@pytest.fixture
def grid() -> list[dt.date]:
    """A rebalance grid at the module's own leak-verification width."""
    return monday(DEFAULT_GRID)


@pytest.fixture
def symbols() -> list[str]:
    """Symbol names at the module's own leak-verification width."""
    return symbol_names(DEFAULT_SYMBOLS)


# -- Feature 131's reach: a database, on purpose, for the tests that write ---


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a store file only this test can see.

    The repository-level conftest points ``DATABASE_URL`` at a per-test SQLite
    file for every suite under ``tests/``; this suite is not under ``tests/``,
    so the isolation is restated rather than inherited.  Deliberately **not**
    autouse and deliberately not named ``DATABASE_URL``'s value in the
    environment: a probe test must not acquire a database by accident, and a
    test that wants one asks for this fixture by name.
    """
    return f"sqlite:///{tmp_path / 'tripwires-test.db'}"


@pytest.fixture
def poison_store(database_url: str):
    """Feature 131's store, pointed at this test's own database.

    Imported inside the fixture so the module-level import list of this file
    stays what it was for every probe test — the member's package ``__init__``
    is reached either way, but a reader scanning the imports should not have to
    work out that ``poison_store`` is the only thing that pulls the store in.
    """
    from tripwires import PoisonStore

    return PoisonStore(database_url)


# -- Feature 132's reach: the pool, beside the store, over the same file -------


@pytest.fixture
def pool(database_url: str):
    """Feature 132's replay pool, reading the *same* file as ``poison_store``.

    Deliberately derived from the same ``database_url`` rather than given its
    own temporary file, because the feature is a join: the marks feature 131
    writes to ``node`` and the scores ``_pool.seed_pool`` writes to
    ``replay_score`` have to be in one database for there to be an excision at
    all.  A fixture that pointed the pool at a different file would make every
    test in ``test_excise.py`` pass vacuously — nothing would ever be poisoned
    from the pool's side, so nothing would ever be refused.

    Asked for by name, like the two above, and never autouse: a probe test must
    not acquire a database by accident.
    """
    from tripwires import ReplayPool

    return ReplayPool(database_url)


@pytest.fixture
def other_pool(tmp_path: Path):
    """A second pool over a *different* file — the cross-database refusal.

    ``ReplayPool`` refuses a store handed to it that reads elsewhere, because
    "the pool refuses what the store marked" is a sentence about one database.
    Proving that refusal needs two, and neither may be the file the other
    fixtures use.
    """
    from tripwires import ReplayPool

    return ReplayPool(f"sqlite:///{tmp_path / 'tripwires-other.db'}")
