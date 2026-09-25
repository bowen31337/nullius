"""Fixtures for the forward member's own suite.

This suite lives inside the workspace member (``packages/forward/tests``)
rather than under the repository-level ``tests/`` tree, because the member —
including its tests — is this feature's file-claim scope, and the placement is
the one the promotion, regime, discovery, replay, canary and sandbox members
take for the same reason: same-basename files collide under one pytest run, so
each member's suite is collected under its own conftest.

**The path bootstrap is wider than a single member's, and deliberately so.**
Feature 332's whole subject is an instant this member does **not** own: the
promotion timestamp is feature 293's stamp, read back through feature 300's
``promotion_window``, and :mod:`forward.window` reaches it with
``importlib.import_module("promotion")`` at call time.  Under ``uv run`` every
workspace member is installed, so that import finds the promotion package on
its own — but under a bare ``pytest`` it would not, and the suite would test
the *absence* path on every test while looking green on none of the real ones.

So the bootstrap puts **every declared member's scan root** on ``sys.path``,
read from the root ``pyproject.toml``'s own ``[tool.uv.workspace]`` declaration
via :func:`app.module_loader.workspace_scan_roots` — the same declaration the
production loader reads, and therefore the same one that decides whether the
promotion member is reachable at all.  That is the bootstrap
``tests/contract/conftest.py`` and ``tests/replay/conftest.py`` perform, and it
is chosen over hard-coding ``packages/promotion/src`` for the reason they give:
a hard-coded path here could quietly disagree with the declaration, and this
suite's assertions are about the seam between two members.

Note what that bootstrap is **not**: it is not this member importing another.
``packages/forward/src/forward/**`` names no workspace member but ``nullius``
and reaches ``promotion`` only through ``importlib`` at call time; the member's
own suite asserts that.  A *test* may put a sibling on the path because a test
has to be able to build the real promotion rows the act reads — the alternative
is a fake promotion member, which would pin this member's behaviour against a
sibling the suite made up.

**The promotion side of the fixture is real, and it is the promotion member
that writes it.**  Feature 293's ``PromotionDecisions.record_decision`` is the
one writer of ``promotion_registry.decided_at``, and the instant feature 332's
row must carry is exactly that column.  So the suite drives the *actual*
promotion store — pre-register through :class:`~promotion.
pre_register.PreRegistrations`, decide through :class:`~promotion.decision.
PromotionDecisions` — rather than hand-writing a registry row.  That is what
makes the feature's central claim testable: *the instant the forward record
carries is the instant the promotion was decided*, asserted against the raw
table rather than against anything this member computed.

:func:`migrated_database` exists for the *convergence* half of the schema law:
the deployment shape where the versioned tree got there first, which a store
that helped itself to a different spelling would corrupt or duplicate.  It
loads ``0118_node_table.py`` and ``0108_forward_and_universe_tables.py`` **by
file path** and calls their ``apply`` — by path rather than by module name
because ``migrations/`` is not a package, and *in dependency order* because the
dependency is real even where SQLite is tolerant: SQLite does not resolve a
foreign key's parent until a row is written, so a records-only database is
*declared* happily and then refuses every ``INSERT`` with ``no such table:
main.node``.  Should a file move, the import fails loudly and says so, which is
a better failure than a silent green against a fictional table.

The database URL fixture is deliberately **not** autouse.  The repository-level
conftest points ``DATABASE_URL`` at a per-test SQLite file for every suite
under ``tests/``; this suite is not under ``tests/``, so the isolation is
restated rather than inherited — and restated as a fixture asked for by name,
the same stance the promotion and regime members' conftests take.  A test of
the *refusals* must not acquire a database by accident.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# conftest.py -> packages/forward/tests -> packages/forward -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "forward" / "src"


def _ensure_on_path(directory: Path) -> None:
    entry = str(directory)
    if directory.is_dir() and entry not in sys.path:
        sys.path.insert(0, entry)


# The factory first: workspace_scan_roots() below is imported from it.
_ensure_on_path(APP_SRC)

from app.module_loader import workspace_scan_roots

# Then every declared member's scan root — `forward` and `promotion` alike —
# resolved from the same declaration the production loader reads.
for _root in workspace_scan_roots(REPO_ROOT / "src" / "app" / "module_loader.py"):
    _ensure_on_path(_root)

_ensure_on_path(PACKAGE_SRC)

from forward import ForwardRecord, ForwardRecords

VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two tables feature 332's one ``INSERT`` needs, and the revision that
#: owns each — the same order :data:`forward.schema.MIGRATION_ORDER` states,
#: restated as data here so the suite asserts *that* order rather than
#: importing it (a suite that imported the constant would agree with the member
#: by construction and pin nothing).
MIGRATION_REVISIONS: tuple[str, ...] = (
    "0118_node_table",
    "0108_forward_and_universe_tables",
)

#: A node identity, a campaign and an epoch the suite reuses, so every test's
#: rows join to the same parents and a failure names a constant rather than a
#: literal buried in an assertion.  Deliberately the promotion suite's own
#: values: the two members' rows are about the same signal in a real
#: deployment, and a suite that used different ones would make the join look
#: incidental.
NODE_ID = "11111111-1111-4111-8111-111111111111"
CAMPAIGN_ID = "22222222-2222-4222-8222-222222222222"
EPOCH_ID = "epoch-2026-01"

#: The instant the criteria are pre-registered at, and the instant the promotion
#: is decided at — both fixed, and in this order.
#:
#: A fixed stamp rather than "now" for the decision, because the whole feature is
#: an assertion about *which* instant the row carries: a test that let the clock
#: choose would pass on any implementation that stamped the row with anything
#: roughly contemporaneous.
#:
#: The registration's stamp is pinned for a second reason, and it is not
#: cosmetic: feature 360's CI invariant makes §13 item 7's law an *ordering*
#: between exactly these two columns — the criteria are pre-registered and
#: hashed before the evaluation that decides them — and feature 293's own store
#: refuses to persist the reverse order.  A suite that let the pre-registration
#: mint "now" while the decision stated a fixed instant in the past would have
#: its fixture refused before feature 332's act ever ran, which is a fact about
#: the suite rather than about this member.
REGISTERED_AT = "2026-02-01T00:00:00+00:00"
DECIDED_AT = "2026-03-01T12:00:00+00:00"

#: The horizon the record is opened over — §5's own 90 days, and the sixth term
#: of the promotion member's own criteria document (``min_forward_days``), so
#: the figure a real caller would read off the registration.
FORWARD_DAYS = 90

#: The criteria every test pre-registers, as the promotion member's own
#: six-term document.  Restated here rather than imported: the promotion
#: member's conftest is not this suite's to reach into, and the document's
#: *content* does not matter to feature 332 — only that the promotion row
#: exists and is closed.
CRITERIA_DOCUMENT: dict[str, Any] = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": FORWARD_DAYS,
}


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is not on ``sys.path``; a migration is
    loaded by its runner the same way — by path — so loading it by path here is
    the shape a migration is *built* to be used in rather than a workaround.  A
    missing file fails with the path in the message, because the one failure a
    test should never have to guess at is "the schema owner moved".
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the forward record's "
            "own migrations rather than hand-writing its DDL, so it needs the "
            "schema's owners to be where the tree keeps them"
        )
    spec = importlib.util.spec_from_file_location(
        f"_forward_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def code_of(module: Any) -> str:
    """A module's *code* as unparsed text, with every docstring stripped.

    For the assertions that a claim is true of what a module **does** rather
    than of what it **says**.  :mod:`forward.schema` has to be able to write
    the sentence *no ``CREATE TABLE`` is authored here* in its own docstring
    while authoring none, and :mod:`forward.record` has to be able to name
    ``promoted_at`` in order to explain why the caller may not state it — so a
    test that scanned the raw file for those words would fail on the very prose
    that makes the claim, and would tempt a later author to delete the
    explanation to keep the suite green.

    Docstrings are removed by position: for every module, class and function in
    the tree, a first statement that is a bare string constant is dropped
    before unparsing.  Everything else — including the f-strings a module
    builds its SQL out of, which is exactly what the DDL and ``INSERT`` claims
    need to see — survives.
    """
    import ast

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    holders = [tree]
    holders += [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for holder in holders:
        body = holder.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            holder.body = body[1:]
    return ast.unparse(tree)


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a record file only this test can see.

    Nothing is created: the file does not exist until the store's first
    ``open_record`` brings the two tables to it (the store runs the owning
    migrations' own statements) or a fixture runs the migrations — which is
    what lets both creators' orders be tested as a *first* act on a fresh
    database.
    """
    return f"sqlite:///{tmp_path / 'forward-test.db'}"


@pytest.fixture
def migrations() -> tuple[ModuleType, ...]:
    """The two schema owners, loaded by path, in dependency order."""
    return tuple(_load_migration(revision) for revision in MIGRATION_REVISIONS)


@pytest.fixture
def migrated_database(database_url: str, migrations: tuple[ModuleType, ...]) -> str:
    """A database holding both tables *by migration*.

    The deployment shape where the versioned tree got there first: the schema is
    the migrations', and what this fixture lets a test ask is whether the
    plugin's writer serves it — the convergence pinned from the other
    direction.  The order is the chain's rather than SQLite's demand: SQLite
    would accept ``forward_record`` declared first and fail at the first row
    instead, which is a tolerance and not a licence to reorder.
    """
    for migration in migrations:
        migration.apply(database_url)
    return database_url


@pytest.fixture
def store(database_url: str) -> ForwardRecords:
    """The store, pointed at this test's own fresh database.

    No migration has run: the store's first ``open_record`` is what brings the
    two tables to it.  That is the contract the member's schema adapter states
    — it authors no DDL and runs the owners' own statements — and the reason
    this fixture does not ask for :func:`migrated_database`.
    """
    return ForwardRecords(database_url)


def promote_signal(
    database_url: str,
    *,
    node_id: str = NODE_ID,
    registered_at: str = REGISTERED_AT,
    decided_at: str | None = DECIDED_AT,
) -> None:
    """Bring a database up and leave one signal's registry row in it.

    The whole of :func:`promoted_signal` as a plain function, so a test that
    needs a *second* signal — in a second database, at a second instant, or
    still open — can have one without restating the fixture.

    Both instants are parameters and both are pinned, and the pair is ordered
    by construction: feature 360's CI invariant makes §13 item 7's law an
    ordering between ``pre_registered_at`` and ``decided_at``, and feature
    293's store refuses to persist the reverse.  A helper that registered at
    the wall clock would satisfy that law only for a decision also stamped at
    the wall clock — so the moment a caller passes a fixed past ``decided_at``
    the *fixture* is refused, before the act under test has run at all.  The
    default pair is fixed and ordered, and so is every pair a caller builds.

    ``decided_at=None`` leaves the row **open** — pre-registered and never
    decided — which is the state between feature 291's act and feature 293's,
    and the second of the two ways a signal can have no promotion instant.
    """
    from promotion import PreRegistrations, PromotionCriteria
    from promotion.decision import PromotionDecisions

    registrations = PreRegistrations(database_url)
    registrations._connect().close()  # brings node + epoch_ledger + registry up
    connection = registrations._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, ?)",
                (node_id, CAMPAIGN_ID, "macro", 1),
            )
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    registrations.pre_register(
        node_id,
        EPOCH_ID,
        PromotionCriteria(**CRITERIA_DOCUMENT),
        clock=lambda: _instant(registered_at),
    )
    if decided_at is not None:
        PromotionDecisions(database_url).record_decision(
            node_id, decided_at=_instant(decided_at)
        )


@pytest.fixture
def promoted_signal(store: ForwardRecords) -> ForwardRecords:
    """The store's database brought up *and* holding one closed promotion.

    Feature 332 reads and writes nothing on the promotion side: the node's row
    is the discovery loop's write, the epoch's is the sealing process's, and the
    ``decided_at`` stamp is feature 293's act.  So the suite drives the *real*
    promotion member's stores to produce them — :class:`~promotion.
    pre_register.PreRegistrations` opens the row, :class:`~promotion.decision.
    PromotionDecisions` closes it at :data:`DECIDED_AT` — rather than
    hand-writing a registry row, because the feature's central assertion is
    that the forward record carries *that* instant, and a hand-written row
    would pin the behaviour against a fixture the suite made up.

    The three tables the promotion stores need are brought up by those stores'
    own bootstraps (``0118``, ``0110``, ``0108``), which is the same set of
    files this member's store runs — so the two members converge on one
    database without either of them naming the other's schema.

    The parent rows are supplied in the columns the migrations declare, through
    the store's own connection, exactly as the promotion member's suite does
    and for the same reason: the foreign keys are real, and the stores *check*
    them rather than manufacturing them.
    """
    store._connect().close()  # brings this member's own two tables up
    promote_signal(store.database_url)
    return store


def _instant(text: str) -> Any:
    """A fixed instant, parsed — one spelling for the whole suite."""
    import datetime as dt

    return dt.datetime.fromisoformat(text)


@pytest.fixture
def opened_record(promoted_signal: ForwardRecords) -> ForwardRecord:
    """One signal's record, opened — the state feature 333 observes onto.

    Feature 332's whole act run once, over the real promotion side (see
    :func:`promoted_signal`), so the boundary every observation test asserts
    against is the one the member actually wrote: ``promoted_at`` at
    :data:`DECIDED_AT` — 2026-03-01T12:00:00+00:00 — whose own UTC date
    2026-03-01 is the boundary day, making **2026-03-02 the first day an
    observation may honestly name**.  The constants are stated here once so
    the observation suite's dates are read against a boundary the fixture
    pins rather than one each test recomputes.

    The row is opened through the store under test (not inserted by hand)
    for the reason :func:`promoted_signal` states about the promotion side:
    a hand-written ``forward_record`` row would pin the boundary against a
    fixture the suite made up, and the one thing feature 333's appends must
    provably carry is *the record's own* instant.
    """
    record, _created = promoted_signal.open_record(
        NODE_ID, forward_days=FORWARD_DAYS
    )
    return record


@pytest.fixture
def forward_rows(store: ForwardRecords):
    """Read ``forward_record`` raw, so a test can see what actually landed.

    Returns a callable rather than a list because most tests read *after* the
    act under test.  Deliberately a raw ``SELECT`` rather than a store verb:
    the point of most of these assertions is what the *table* holds — including
    the three NULL observation columns, which no store read here is shaped to
    return as a bare fact — and a test that asked the store would be asking the
    code under test to confirm itself.
    """

    def _rows() -> list[sqlite3.Row]:
        connection = store._connect()
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                "SELECT id, node_id, promoted_at, observed_on, live_ic, "
                "backtest_ic, realized_cost_bps FROM forward_record"
            )
            try:
                return list(cursor.fetchall())
            finally:
                cursor.close()
        finally:
            connection.close()

    return _rows


@pytest.fixture
def promotion_rows(store: ForwardRecords):
    """Read ``promotion_registry`` raw — the instant this feature must carry."""

    def _rows() -> list[sqlite3.Row]:
        connection = store._connect()
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                "SELECT node_id, criteria_hash, pre_registered_at, decided_at "
                "FROM promotion_registry"
            )
            try:
                return list(cursor.fetchall())
            finally:
                cursor.close()
        finally:
            connection.close()

    return _rows
