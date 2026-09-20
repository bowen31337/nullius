"""Suite-local fixtures for the tripwires package's tests.

This suite lives inside the workspace member (``packages/tripwires/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
Nothing here needs them: feature 125's probe is a pure function of plain
mappings, so there is no lake to isolate, no database to point at and no
environment to clear.  The absence of those fixtures is itself a property
worth stating — the member is deliberately stdlib-only and environment-free,
so a test that needed a temp lake would mean the probe had grown a dependency
it is not allowed to have.

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
