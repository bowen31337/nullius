"""The cross-member spellings this feature restates — pinned as data.

The workspace contract is that **no member imports another**.  It is met
with the same remedy everywhere a spelling has to be shared: the spelling
is *restated* in the member that needs it, and a suite like this one is
what keeps the restatement honest (``packages/discovery/tests/
test_cross_member.py`` and ``packages/sandbox/tests/test_budget_law.py``
state the discipline; the latter demonstrates the in-function import that
costs one test when a sibling is absent rather than the collection of
the whole suite).

This member restates two spellings, and both are the convergence
``0107``'s own docstring sets up:

**The DDL.**  ``migrations/versions/0107_regime_coverage.py`` (feature
107) is the coverage table's first creator, and the regime store is its
second: *"when the plugin lands with its own ``CREATE TABLE IF NOT
EXISTS``, whichever ran first is the winner and the statements agree,
because both take the spec's columns and both are idempotent."*  That is
a promise made in prose by a file this member does not own, and the only
honest way to keep it is to pin the two statements against each other —
the migration's ``statements("sqlite")`` against the schema text the
database itself canonicalized when the store created the table.  A
divergence would be silent exactly where it matters most: two
deployments, one migrated and one store-created, holding two tables a
reader could not tell apart until the day a column is missing.

**The stratum count.**  :data:`regime.DEFAULT_STRATA` names three
strata and :data:`feature_store.regime_labeler.DEFAULT_K` carves three —
the labeler's own comment cites feature 283: *"the labels line up with
the three coverage strata the regime plugin names … the labeler's
clusters are the same regimes that promotion counts coverage across."*
What the two members share is the *count*, not the names: the labeler's
strata are carved clusters (data, not literals — the names are the
ledger's vocabulary), so ``DEFAULT_K`` is the one number both sides
publish and the one a silent edit would corrupt in both directions — a
labeler carving four clusters would label worlds no ledger stratum
holds, and a ledger naming two would count worlds it cannot bin.

**Why the imports are inside the tests.**  A module-scope
``import feature_store`` would make this member's suite fail to collect
wherever the sibling member is absent, which is the outcome the
workspace contract's remedy exists to avoid.  Inside a function, the
absence costs one test, and that test says exactly what is missing.  The
``pytest.importorskip`` is the same stance spelled for the path bootstrap
— these tests need the sibling's ``src/`` on ``sys.path``, which the
workspace's member suites do not otherwise do for each other.  The
migration is loaded by file path for the same reason the member conftest
states: ``migrations/`` is not a package, and the file is the schema's
owner.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest
from regime import COVERAGE_TABLE, DEFAULT_STRATA, RegimeCoverage

REPO_ROOT = Path(__file__).resolve().parents[3]
FEATURE_STORE_SRC = REPO_ROOT / "packages" / "feature-store" / "src"
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
COVERAGE_MIGRATION = "0107_regime_coverage"


def _labeler():
    """The feature-store member's labeler, imported in-function.

    ``importorskip`` rather than a bare import: a workspace that does not
    carry the sibling should lose this test and nothing else.  The path
    insert is the same bootstrap every member suite performs for
    *itself*, applied to a sibling — the workspace's member suites are
    not installed into each other's environments, and the acceptance
    gate does not put them there either.
    """
    if str(FEATURE_STORE_SRC) not in sys.path:
        sys.path.insert(0, str(FEATURE_STORE_SRC))
    feature_store = pytest.importorskip(
        "feature_store", reason="the feature-store member is not in this workspace"
    )
    return pytest.importorskip(
        f"{feature_store.__name__}.regime_labeler",
        reason="the labeler module is not where its member keeps it",
    )


def _migration() -> ModuleType:
    """The coverage table's migration, loaded by path as its runner loads it."""
    path = VERSIONS_DIR / f"{COVERAGE_MIGRATION}.py"
    assert path.is_file(), f"{COVERAGE_MIGRATION} is not at {path}"
    spec = importlib.util.spec_from_file_location(f"_regime_cross_{COVERAGE_MIGRATION}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for a raw read."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _schema_text(database_url: str) -> str:
    """The coverage table's stored schema text, as the database keeps it.

    ``sqlite_master.sql`` is the database's own canonical copy of the
    ``CREATE`` statement that ran — the text a later reader or migration
    compares against — fetched the way a reader that shares no code with
    this member would fetch it.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            f"AND name = '{COVERAGE_TABLE}'"
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    assert row is not None, f"{COVERAGE_TABLE} does not exist at {database_url}"
    return str(row[0])


def _normalized(sql: str) -> str:
    """One ``CREATE TABLE`` statement as comparable text.

    SQLite stores the statement minus its ``IF NOT EXISTS`` clause, so
    that clause is dropped from both sides before the whitespace is
    collapsed — everything else (column names, types, constraints, the
    dialect's default expression) is compared as the database sees it.
    """
    return " ".join(sql.replace("IF NOT EXISTS ", "").split())


# -- The DDL convergence -----------------------------------------------------------


class TestTheTwoCreatorsConverge:
    """0107's convergence clause, pinned from both directions."""

    def test_the_store_creates_the_migrations_table(self, database_url: str) -> None:
        # The store's DDL, as the database itself canonicalized it on a
        # database *no migration has touched*, against the migration's
        # own statement for this dialect — token for token, which is
        # what "the statements agree" has to mean for "whichever ran
        # first is the winner" to be safe.
        RegimeCoverage(database_url).record("crash", 1)
        migration_ddl = _migration().statements("sqlite")[0]
        assert _normalized(_schema_text(database_url)) == _normalized(migration_ddl)

    def test_both_orders_hold_the_same_table_and_rows(self, tmp_path: Path) -> None:
        # Two databases, one per creator, brought to the same state —
        # migration-first (the deployment shape) and store-first (the
        # downgrade-refill shape) — must agree on the schema text and on
        # the rows a reader would find.  That both orders exist at all
        # is 0107's doing; that they agree is this member's to keep.
        migrated = f"sqlite:///{tmp_path / 'migrated-first.db'}"
        created = f"sqlite:///{tmp_path / 'store-first.db'}"
        _migration().apply(migrated)
        for url in (migrated, created):
            RegimeCoverage(url).record("high-volatility trend", 2)
            RegimeCoverage(url).record("low-volatility chop", 14)
            RegimeCoverage(url).name_stratum("crash")
        assert _normalized(_schema_text(migrated)) == _normalized(
            _schema_text(created)
        )
        for url, other in ((migrated, created), (created, migrated)):
            with closing(sqlite3.connect(_path_of(url))) as connection:
                rows = connection.execute(
                    f"SELECT stratum, world_count FROM {COVERAGE_TABLE} "
                    "ORDER BY stratum"
                ).fetchall()
            with closing(sqlite3.connect(_path_of(other))) as connection:
                others = connection.execute(
                    f"SELECT stratum, world_count FROM {COVERAGE_TABLE} "
                    "ORDER BY stratum"
                ).fetchall()
            assert rows == others
        assert ("crash", 0) in rows  # the named-empty row both orders land


# -- The stratum count -------------------------------------------------------------


class TestTheStratumCountTheLabelerCarves:
    """The labeler's DEFAULT_K is the ledger's three — the count both
    members publish, each in its own spelling."""

    def test_the_labelers_k_is_the_ledgers_three(self) -> None:
        # The labeler's comment cites feature 283 by number for exactly
        # this agreement; what keeps the citation honest is the data.  A
        # silent re-K on either side would split the seam in both
        # directions: worlds labeled into a stratum no ledger row holds,
        # and ledger rows no labeler can fill.
        labeler = _labeler()
        assert labeler.DEFAULT_K == len(DEFAULT_STRATA) == 3
