"""``python -m nullius_api.demo`` — seed a demo metrics store.

additions_spec_journeys.xml feature 13: *System seeds a demo metrics store
through the members' public stores with ``python -m nullius_api.demo``,
which saves to the named database closed-campaign FDR rows, sealed epochs,
regime coverage, instrument readings, a pre-registered and decided node
with forward observations, trial-ledger charges and node rows carrying the
provenance triple, and provides an in-memory paper execution engine for
the halt route.*

This is what makes docs/user-journeys/RESULTS.md's run possible at all:
J2, J4-J6, J8-J11 and J13 all read a store that has *something* in it, and
this module is the one place that puts something there — through the
same public stores the composed application's own routes read
(:class:`scoring.FdrDeployStore`, :class:`regime.coverage.RegimeCoverage`,
:func:`nulloracle.persist_ks_pvalue`, :class:`ops.live_metrics.
LiveMetricsStore`, :func:`discovery.create_campaign`,
:class:`promotion.pre_register.PreRegistrations`, :func:`promotion.
record_decision`, :func:`forward.forward_record`, :func:`forward.
forward_observation` and :class:`ledger.store.TrialLedger`), never by
inventing a second spelling of a row a member already owns.

**Two tables have no writer of their own, and this module fills the gap
the same way this workspace's own test suites do.**  ``node`` and
``epoch_ledger`` are schema the versioned migration tree owns
(``0118``, ``0110``, widened by ``0116``'s provenance trio) but whose
*parent rows* — a node the discovery loop would have expanded, an epoch
the sealing process would have sealed — no member of this workspace
writes today (see ``packages/promotion/tests/conftest.py``'s
``seeded_database`` fixture, which does the same insert for the same
reason: *"the parent rows are a fixture because they are not the
store's job"*).  A demo has no discovery loop and no sealing process
behind it, so this module inserts those two rows directly, in exactly
the columns the migrations declare — never a schema this module
invents.

**Migrations are loaded by file path and run once, never edited.**
``migrations/`` is not a package; this module loads the five revisions
the seeded rows need (``0111`` campaign, ``0118`` node, ``0110``
epoch_ledger, ``0108`` forward_record/promotion_registry, ``0116``
node's provenance trio) the same way ``packages/promotion/src/promotion/
schema.py`` and the discovery/promotion suites do, and calls each
revision's own ``apply(database_url)`` — the migration is the schema's
sole author, and this module is plumbing that runs it.

**Every figure seeded is a fixed value, not a fresh timestamp.**  A demo
run an operator repeats against the same file must seed the same rows,
not grow the store — so every instant, id and sample below is a
constant, and every write goes through a store whose own law is
idempotent (an upsert on the campaign, the stratum, the node) or is
guarded by ``INSERT OR IGNORE`` where this module writes the row itself.

**The FDR figures are docs/user-journeys/J02's own worked example** —
0.9, ≈0.61, 0.5 for the oldest, middle and newest closed campaign — each
computed by feature 267's reweighting from a plain sensitivity/
specificity pair (:data:`_OLDEST_FIGURES`, :data:`_MIDDLE_FIGURES`,
:data:`_NEWEST_FIGURES`), never spelled as a raw figure this module
invented.

**The seed also seals §7.1's sidecar, because the database is not the whole
world ``POST /target`` reads.**  ``nulloracle``'s route answers from a
*file* — §7.1's ``sidecar.enc``, AES-GCM sealed, the one artifact in the
system allowed to hold a node's null status — and the composed component
exists only when ``NULL_SIDECAR_PATH`` and ``NULL_SIDECAR_KEY_REF`` name
one (:meth:`nulloracle.sidecar.NullSidecar.resolve`).  So a demo that
seeded only tables composed no ``nulloracle-target-route`` at all, and
J12's ``POST /target`` answered 503 ``component_unconfigured`` for every
node — the unknown-node 404 and the null/real information barrier could
not be exercised from the shipped demo however carefully the journey's
steps were followed.  :func:`_seal_null_sidecar` closes that: it seals one
null node and one real node into ``<database directory>/null/sidecar.enc``
through the member's own :meth:`~nulloracle.sidecar.NullSidecar.write`
(which creates the ``0o700`` directory and writes the ``0o600`` file
itself, so this module never spells those modes a second time), under a key
generated for this seeding with :func:`os.urandom`.

The two nodes are identities this module already seeds rather than new
ones: the *real* node is :data:`_NODE_ID` — the node J10's forward curve
and J11's charges already name, so the demo's world stays one world — and
the *null* node is :data:`_NULL_NODE_ID`, the node whose bare, unbudgeted
charge is already in the trial ledger (feature 93's filter needs a node
that is charged but never counted, and a node planted as null is the
honest owner of that charge).  Both get a ``node`` row, so every node the
sidecar holds is a node the tree store holds.

**The demo key is generated per seeding, printed, and never persisted.**
Nothing on disk records it: the file is sealed *under* it, not beside it,
so a second seeding re-seals the sidecar under a fresh key.  That is
deliberate — a checked-in or reused demo key is a key in a repository, and
constraint 7 of the bug report asks for exactly this — and it has one
consequence the entrypoint states plainly: the two strings the summary
prints must be exported *and* the sidecar re-sealed by the same run that
printed them, because the run after this one will have replaced the file
under a key it no longer knows.

**The paper execution engine is stateless and in-memory, and it is not
started by this module.**  :class:`InMemoryPaperEngine` is the four-verb
face :mod:`risk.flatten` drives (``open_orders``, ``cancel_order``,
``open_positions``, ``close_position``); :data:`PAPER_ENGINE` is one
instance, pre-loaded with the open orders and positions J13's precondition
names, importable at ``nullius_api.demo:PAPER_ENGINE`` — the
``module:attribute`` spelling :data:`nullius_api.server.
EXECUTION_ENGINE_ENV` (``NULLIUS_EXECUTION_ENGINE``) takes to bind an
engine to ``POST /risk/halt`` at server start.  This module seeds a
database and seals a sidecar; it does not open a socket and does not read
that environment variable itself.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import unquote, urlparse

__all__ = [
    "DATABASE_URL_ENV",
    "PAPER_ENGINE",
    "DemoSeedReport",
    "InMemoryPaperEngine",
    "main",
    "seed_demo_store",
]

#: The environment variable naming the database this module seeds — the
#: one spelling every store in this workspace resolves its own from.
DATABASE_URL_ENV = "DATABASE_URL"

# demo.py -> nullius_api -> src -> api -> packages -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATIONS_DIR = _REPO_ROOT / "migrations" / "versions"

#: The revisions this module brings a fresh database to, in the order
#: the migration tree's own dependencies demand — ``0116`` last among the
#: node-table statements because it widens a table ``0118`` must have
#: created first, and before any row is written into it.
_SCHEMA_MIGRATIONS: tuple[str, ...] = (
    "0111_campaign_table",
    "0118_node_table",
    "0110_epoch_ledger",
    "0108_forward_and_universe_tables",
)
_PROVENANCE_MIGRATION = "0116_provenance_trio"

#: Fixed identities, so a repeated run seeds the same rows rather than
#: growing the store.  Spelled as canonical UUID text, in the pattern
#: this workspace's own suites use for a fixture id
#: (``packages/promotion/tests/conftest.py``'s ``NODE_ID``/``CAMPAIGN_ID``).
_CAMPAIGN_OLDEST = "00000000-0000-4000-8000-000000000001"
_CAMPAIGN_MIDDLE = "00000000-0000-4000-8000-000000000002"
_CAMPAIGN_NEWEST = "00000000-0000-4000-8000-000000000003"
_NODE_ID = "00000000-0000-4000-8000-0000000000a1"
#: A second, bare charge — a null node's, never pre-registered or
#: forward-tracked, so ``K_effective``'s ``charges_budget`` filter has
#: something to exclude (feature 93: a null node is charged but never
#: counted).  The trial ledger's own schema carries no foreign key on
#: ``node_id``/``campaign_id`` (feature 95's row is an append-only fact,
#: not a join), so this charge needs no parent row of its own.
#:
#: Since the demo also seals a sidecar, this is now the node that *is*
#: planted as null there: a node charged without ever being counted is a
#: node whose signal was never compared to real forward returns, which is
#: what a null assignment means (§8), so the charge and the seal agree
#: about one node rather than describing two.
_NULL_NODE_ID = "00000000-0000-4000-8000-0000000000b2"
_EPOCH_SERVING = "epoch-demo-2026-01"
_EPOCH_CLEAN_A = "epoch-demo-2026-02"
_EPOCH_CLEAN_B = "epoch-demo-2026-03"

#: J02's own worked example: the oldest, middle and newest closed
#: campaign's sensitivity/specificity pair, each reweighted by feature
#: 267's formula to 0.9, ≈0.61 and 0.5 — the figures the dashboard and
#: ``GET /metrics/fdr-deploy`` are seeded to show.
_OLDEST_FIGURES = SimpleNamespace(sensitivity=0.1, specificity=0.9)
_MIDDLE_FIGURES = SimpleNamespace(sensitivity=0.85, specificity=0.85)
_NEWEST_FIGURES = SimpleNamespace(sensitivity=0.9, specificity=0.9)

_OLDEST_COMPUTED_AT = "2026-01-01T00:00:00+00:00"
_MIDDLE_COMPUTED_AT = "2026-02-01T00:00:00+00:00"
_NEWEST_COMPUTED_AT = "2026-03-01T00:00:00+00:00"

#: The provenance triple every seeded node row and trial-ledger charge
#: carries — sha256 hexdigests of fixed demo labels, in the canonical
#: lowercase-hex spelling :func:`ledger.provenance.validated_provenance_hash`
#: and ``0116``'s ``CHAR(64)`` columns both require.
_EVALUATOR_HASH = hashlib.sha256(b"nullius-demo-evaluator").hexdigest()
_SNAPSHOT_HASH = hashlib.sha256(b"nullius-demo-snapshot").hexdigest()
_COST_MODEL_HASH = hashlib.sha256(b"nullius-demo-cost-model").hexdigest()

_PRE_REGISTERED_AT = datetime(2026, 3, 3, 0, 0, tzinfo=UTC)
_DECIDED_AT = datetime(2026, 3, 3, 1, 0, tzinfo=UTC)
_KS_SEEN_AT = datetime(2026, 3, 2, tzinfo=UTC)
_LIVE_METRIC_LOGGED_AT = "2026-03-02T00:00:00+00:00"
_CHARGE_TS = datetime(2026, 3, 3, 2, 0, tzinfo=UTC)
_NULL_CHARGE_TS = datetime(2026, 3, 3, 2, 5, tzinfo=UTC)

#: Two samples, perfectly interleaved rather than merely similar, so
#: §7.4's exact two-sample test answers the p-value at its maximum
#: (1.0) regardless of the estimator's own tie-breaking — the "nulls
#: indistinguishable" reading J4's precondition asks the demo store to
#: hold.
_KS_NULL_SCORES = (0.10, 0.30, 0.50, 0.70, 0.90)
_KS_REAL_SCORES = (0.20, 0.40, 0.60, 0.80, 1.00)

#: docs §5.4's own worked example for §C7's coverage ledger — reused
#: verbatim rather than invented, so a reader who already knows that
#: line recognises the seeded rows.
_REGIME_COVERAGE = (
    ("high_vol_trend", 2),
    ("low_vol_chop", 14),
    ("crash", 0),
)

_FEED_STALENESS_SECONDS = 1.2

#: The directory the demo's sidecar lives in, under the database's own
#: directory, and the file's name — §7.1's own
#: (:data:`nulloracle.SIDECAR_DIRECTORY`, :data:`nulloracle.SIDECAR_FILENAME`).
#: A *literal* here rather than an import, because the two constants are
#: read inside :func:`_sidecar_path` which the module resolves lazily; the
#: one place they must agree with the member is :func:`_seal_null_sidecar`,
#: which writes through the member with the member's own filename.
_DEMO_SIDECAR_DIRECTORY = "null"
_DEMO_SIDECAR_FILENAME = "sidecar.enc"

#: The demo's two planted nodes, by the bit §7.1's schema carries.  The
#: closure of the pair is what makes the information barrier *exerciseable*
#: rather than merely implemented: an operator can post for a node the
#: sidecar does not hold (the 404) and for two nodes it does (the identical
#: refusal, or — once a series supply is wired — one 200 on each branch).
#:
#: The permutation seed each carries is *derived* rather than drawn, through
#: the member's own :func:`nulloracle.perm_seed_for`, which is where a real
#: campaign gets its seeds: a seed derived from ``(campaign_id, node_id)``
#: is stable across processes and machines, so a demo replayed next year
#: reproduces the same null series (§12) and two runs of the seeder cannot
#: disagree about a node's world.
_DEMO_NULL_NODES: tuple[tuple[str, bool], ...] = (
    (_NODE_ID, False),
    (_NULL_NODE_ID, True),
)


# -- Migrations, loaded by path, never edited --------------------------------


def _load_migration(revision: str) -> ModuleType:
    """Import one migration revision by file path, as its runner does.

    ``migrations/`` is not a package and is not on ``sys.path``, so a
    revision cannot be imported by name; every migration runner in this
    workspace loads one by path instead (``packages/promotion/src/
    promotion/schema.py``, every member suite that brings a table up for
    its own tests), and this module does the same rather than inventing
    a second loader.  Cached in ``sys.modules`` under a private name, so
    a second call is a dictionary lookup rather than a re-execution.
    """
    path = _MIGRATIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise RuntimeError(
            f"nullius_api.demo seeds through migrations/versions/{revision}.py, "
            f"which is not at {path}. That file is the schema's sole author; "
            "the repair is to the checkout, not to a statement this module "
            "could improvise"
        )
    module_name = f"_nullius_api_demo_{revision}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"migrations/versions/{revision}.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation every migration and every store in this
    workspace restates rather than imports (a migration must not depend
    on a workspace package being importable to run) — repeated here for
    the one direct read this module makes: checking whether ``node``
    already carries its provenance columns before re-running the
    ``ALTER TABLE`` that would add them a second time.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError(
            f"nullius_api.demo seeds a sqlite:/// database only; "
            f"{DATABASE_URL_ENV} names scheme {parsed.scheme!r}. The repair "
            "is a sqlite:///path/to/store.db URL"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise ValueError(f"{DATABASE_URL_ENV} names no database path")
    return Path(path)


def _node_table_has_provenance(database_url: str) -> bool:
    """Whether ``node`` already carries the provenance trio's columns.

    ``ALTER TABLE ... ADD COLUMN`` is not ``IF NOT EXISTS`` — unlike
    every ``CREATE TABLE`` in this tree, running it twice fails with
    ``duplicate column name`` — so a repeated demo run must ask before
    it repeats ``0116``'s statements.  ``False`` for a database that does
    not exist yet or holds no ``node`` table: both are the fresh-database
    state this migration has never touched.
    """
    path = _sqlite_path(database_url)
    if not path.exists():
        return False
    connection = sqlite3.connect(path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(node)")}
    finally:
        connection.close()
    return "evaluator_hash" in columns


def _bootstrap_schema(database_url: str) -> None:
    """Bring the database to the five revisions this module's rows need.

    Every statement is the migrations' own (``statements("sqlite")``,
    run through each revision's ``apply``), and every ``CREATE TABLE`` is
    idempotent by construction; the one guard this module adds is
    :func:`_node_table_has_provenance`, so a repeated seed does not
    re-run ``0116``'s bare ``ALTER TABLE ADD COLUMN``.
    """
    for revision in _SCHEMA_MIGRATIONS:
        _load_migration(revision).apply(database_url)
    if not _node_table_has_provenance(database_url):
        _load_migration(_PROVENANCE_MIGRATION).apply(database_url)


# -- The two parent rows no member's store writes ----------------------------


def _seed_parent_rows(database_url: str) -> None:
    """Insert the node rows and the three epoch rows directly.

    Neither table has a public writer for exactly this row in this
    workspace today (see the module docstring): a node is ordinarily the
    discovery loop's write and an epoch the sealing process's, and a demo
    has neither behind it.  ``INSERT OR IGNORE`` against the primary key
    is what makes a repeated seed leave a standing row untouched rather
    than refusing on the second run — the same idempotence every public
    store below states for its own upsert.

    Both nodes the sealed sidecar holds get a row here (the real one and
    the null one), because §7.1's file is *about* nodes and a demo whose
    sidecar named a node no tree store held would be a world an operator
    could not join.  The rows are one migration's own columns, nothing more.
    """
    path = _sqlite_path(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.executemany(
                "INSERT OR IGNORE INTO node "
                "(id, campaign_id, theme_root, depth, evaluator_hash, "
                "snapshot_hash, cost_model_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        node_id,
                        _CAMPAIGN_NEWEST,
                        "macro",
                        0,
                        _EVALUATOR_HASH,
                        _SNAPSHOT_HASH,
                        _COST_MODEL_HASH,
                    )
                    for node_id, _is_null in _DEMO_NULL_NODES
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO epoch_ledger "
                "(epoch_id, sealed_at, promotion_decisions_served, retired) "
                "VALUES (?, ?, ?, ?)",
                (
                    (_EPOCH_SERVING, "2026-01-01T00:00:00+00:00", 2, 0),
                    (_EPOCH_CLEAN_A, "2026-01-02T00:00:00+00:00", 0, 0),
                    (_EPOCH_CLEAN_B, "2026-01-03T00:00:00+00:00", 0, 0),
                ),
            )
    finally:
        connection.close()


# -- §7.1's sidecar, sealed beside the database -------------------------------


def _sidecar_path(database_url: str) -> Path:
    """Where the demo seals §7.1's sidecar: beside the database it describes.

    ``<database directory>/null/sidecar.enc``.  Beside the database rather
    than anywhere else, and for the same reason the two files are one
    deployment: an operator who names one path has named the pair, and the
    sidecar travels with the store it belongs to when a demo directory is
    copied or removed.  Never inside the repository — the demo writes only
    where the operator pointed ``DATABASE_URL``.
    """
    return (
        _sqlite_path(database_url).parent
        / _DEMO_SIDECAR_DIRECTORY
        / _DEMO_SIDECAR_FILENAME
    )


def _seal_null_sidecar(database_url: str) -> tuple[str, str]:
    """Seal the two demo nodes into §7.1's sidecar; answer ``(path, key)``.

    The write goes through :meth:`nulloracle.sidecar.NullSidecar.write`,
    which is the member's one door for this artifact: it creates the
    directory ``0o700``, writes the file ``0o600`` through a temporary
    file and an atomic ``os.replace``, and returns the envelope's digest.
    This module therefore spells no mode bits, no temp-file dance and no
    cipher — it hands the member a path, a key and §7.1's assignments and
    lets the member own everything the artifact *is*.

    The key is 32 fresh bytes from :func:`os.urandom`, and it is returned
    raw so the entrypoint can print its ``hex:`` reference and nothing
    else.  It is **not** persisted: nothing on disk records it, so a second
    seeding re-seals the file under a key it alone holds.  That is the
    constraint the bug report states (*"the demo key is generated per
    seeding and is only ever printed for the demo; nothing is written into
    the repository"*) and the reason the entrypoint's summary says the two
    values it prints belong to the run that printed them.

    The assignments carry the member's own
    :func:`nulloracle.perm_seed_for` seeds rather than values invented
    here — the demo's null node is reproducible from the sealed file alone
    (§12), exactly as a campaign's would be.
    """
    import nulloracle

    assignments = [
        nulloracle.NullAssignment(
            node_id=node_id,
            is_null=is_null,
            perm_seed=nulloracle.perm_seed_for(_CAMPAIGN_NEWEST, node_id),
        )
        for node_id, is_null in _DEMO_NULL_NODES
    ]
    material = os.urandom(nulloracle.SIDECAR_KEY_BYTES)
    path = _sidecar_path(database_url)
    nulloracle.NullSidecar(path, material).write(assignments)
    return str(path), material.hex()


# -- The paper execution engine -----------------------------------------------


class InMemoryPaperEngine:
    """A stateful, in-process stand-in for a supervisor's execution engine.

    Speaks exactly the four-verb face :mod:`risk.flatten` drives —
    ``open_orders()``/``open_positions()`` to ask what stands,
    ``cancel_order(order_id)``/``close_position(symbol)`` to end it —
    duck-typed rather than a subclass of anything, because that face is
    all the flatten ever checks for (:func:`risk.flatten._require_face`).
    Held entirely in the process's memory: a halt against this engine
    changes nothing the demo store persisted, and a fresh
    :class:`InMemoryPaperEngine` is what a restarted demo process starts
    from.
    """

    def __init__(
        self, *, orders: tuple[str, ...] = (), positions: tuple[str, ...] = ()
    ) -> None:
        self._orders: list[str] = list(orders)
        self._positions: list[str] = list(positions)

    def open_orders(self) -> list[str]:
        """Every order id still standing."""
        return list(self._orders)

    def cancel_order(self, order_id: str) -> None:
        """End one standing order; absent ids are already flat."""
        if order_id in self._orders:
            self._orders.remove(order_id)

    def open_positions(self) -> list[str]:
        """Every position symbol still open."""
        return list(self._positions)

    def close_position(self, symbol: str) -> None:
        """Close one open position; absent symbols are already flat."""
        if symbol in self._positions:
            self._positions.remove(symbol)


#: The engine J13's precondition names: "an in-memory paper engine with
#: open orders/positions".  Bound to ``POST /risk/halt`` by naming this
#: object at ``nullius_api.demo:PAPER_ENGINE`` in
#: ``NULLIUS_EXECUTION_ENGINE`` (:data:`nullius_api.server.
#: EXECUTION_ENGINE_ENV`) — a deployment decision this module does not
#: make for the caller.
PAPER_ENGINE = InMemoryPaperEngine(
    orders=("demo-order-1", "demo-order-2"),
    positions=("BTCUSDT", "ETHUSDT"),
)


# -- The seed itself -----------------------------------------------------------


@dataclass(frozen=True)
class DemoSeedReport:
    """What one :func:`seed_demo_store` call put in the database — and on disk.

    A value, not a receipt to reinterpret: every field is an identity
    this run either created or reused, so a caller (the CLI's own
    summary, a test) can name exactly which rows to read back rather
    than re-deriving them from the constants above.

    ``real_node_id``/``null_node_id`` are the pair §7.1's sidecar holds,
    and they are *the same two identities* the database side of the seed
    names: ``real_node_id`` is ``node_id`` — the pre-registered, decided,
    forward-tracked node every earlier journey reads — and ``null_node_id``
    is the node whose bare, unbudgeted charge is already in the trial
    ledger.  Both are fields rather than aliases so a caller reads the
    pair's meaning off the report instead of having to know which
    constant played which part.

    ``null_sidecar_key`` is the *demo key itself*, in lowercase hex — the
    material, not a reference to it, which is why the field is named for
    the hex the entrypoint prints.  A report is a value an operator holds
    for the length of the demo they are running; nothing serialises it.
    """

    campaign_ids: tuple[str, str, str]
    node_id: str
    epoch_ids: tuple[str, str, str]
    forward_observed_on: tuple[str, str]
    #: The two nodes §7.1's sidecar holds: the real one (the demo node) and
    #: the null one (the bare charge's node).  Both have ``node`` rows.
    real_node_id: str
    null_node_id: str
    #: Where the sealed sidecar is, and the hex key it is sealed under —
    #: the two values ``NULL_SIDECAR_PATH`` and ``NULL_SIDECAR_KEY_REF``
    #: must carry for the composed ``POST /target`` to serve this demo.
    null_sidecar_path: str
    null_sidecar_key: str

    @property
    def null_sidecar_key_ref(self) -> str:
        """The key as the ``hex:`` reference ``NULL_SIDECAR_KEY_REF`` takes.

        Derived from :attr:`null_sidecar_key` rather than stored beside it,
        so the two can never disagree about which key this run sealed under
        — the ``hex:`` scheme is :mod:`nulloracle.keyref`'s own closed
        spelling, and this property is the one place the demo composes it.
        """
        return f"hex:{self.null_sidecar_key}"


def seed_demo_store(database_url: str) -> DemoSeedReport:
    """Seed one demo metrics store through the members' own public stores.

    Every write below goes through the store the composed application's
    own routes read — never a second spelling of a row a member already
    owns (see the module docstring) — in the one order their foreign
    keys and read-time dependencies demand: the three campaigns before
    anything that names one (the KS guard's row, the node's
    ``campaign_id``); the node rows and the three epoch rows before the
    pre-registration that references both by foreign key; the decided
    promotion before the forward record that reads its ``decided_at``;
    the forward record before the observations appended onto it.  Safe
    to call more than once against the same database: every public
    store's own write is idempotent on its key, and the rows this
    module writes directly are guarded by ``INSERT OR IGNORE``.

    The sidecar is sealed **last**, after every row it is *about* stands:
    a sealed assignment naming a node the tree store does not hold would
    be a sidecar an audit could not join, and the nodes' rows are written
    with the other parents partway through.  It is not idempotent in the
    same way the rows are, and deliberately so — a fresh key per seeding
    (see :func:`_seal_null_sidecar`) means a repeated run seals the same
    assignments under a new key, which is the constraint's own shape: the
    world is stable, the demo's secret is not.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError(
            "seed_demo_store seeds one sqlite:/// database and needs its "
            f"URL; got {database_url!r}"
        )
    url = database_url.strip()
    _bootstrap_schema(url)

    import discovery

    for campaign_id in (_CAMPAIGN_OLDEST, _CAMPAIGN_MIDDLE, _CAMPAIGN_NEWEST):
        discovery.create_campaign(
            discovery.TYPE_R_CAMPAIGN_TYPE,
            50,
            campaign_id=campaign_id,
            database_url=url,
        )

    import scoring

    fdr_store = scoring.FdrDeployStore(url)
    fdr_store.persist(_CAMPAIGN_OLDEST, _OLDEST_FIGURES, computed_at=_OLDEST_COMPUTED_AT)
    fdr_store.persist(_CAMPAIGN_MIDDLE, _MIDDLE_FIGURES, computed_at=_MIDDLE_COMPUTED_AT)
    fdr_store.persist(_CAMPAIGN_NEWEST, _NEWEST_FIGURES, computed_at=_NEWEST_COMPUTED_AT)

    _seed_parent_rows(url)

    import regime

    for stratum, world_count in _REGIME_COVERAGE:
        regime.persist_coverage(stratum, world_count, database_url=url)

    import nulloracle

    nulloracle.persist_ks_pvalue(
        _CAMPAIGN_NEWEST,
        _KS_NULL_SCORES,
        _KS_REAL_SCORES,
        database_url=url,
        seen_at=_KS_SEEN_AT,
    )

    import ops

    ops.LiveMetricsStore(url).record(
        "feed_staleness_s", _FEED_STALENESS_SECONDS, logged_at=_LIVE_METRIC_LOGGED_AT
    )

    import promotion

    criteria = promotion.PromotionCriteria(
        theta=0.3,
        alpha=0.05,
        max_fdr_deploy=0.25,
        min_worlds=50,
        min_coverage_strata=3,
        min_forward_days=90,
    )
    PreRegistrations = promotion.PreRegistrations
    PreRegistrations(url).pre_register(
        _NODE_ID, _EPOCH_SERVING, criteria, pre_registered_at=_PRE_REGISTERED_AT
    )
    promotion.record_decision(_NODE_ID, decided_at=_DECIDED_AT, database_url=url)

    import forward

    record = forward.forward_record(_NODE_ID, forward_days=90, database_url=url)
    promoted_day = record.promoted_at.date()
    observed_on = (promoted_day + timedelta(days=1), promoted_day + timedelta(days=5))
    forward.forward_observation(
        _NODE_ID,
        observed_on=observed_on[0],
        live_ic=0.06,
        forward_days=90,
        database_url=url,
    )
    forward.forward_observation(
        _NODE_ID,
        observed_on=observed_on[1],
        live_ic=0.045,
        forward_days=90,
        database_url=url,
    )

    import ledger

    trial_ledger = ledger.TrialLedger(url)
    trial_ledger.debit(
        _NODE_ID,
        _CAMPAIGN_NEWEST,
        outcome="ok",
        charges_budget=True,
        charge_units=1.0,
        epoch_id=_EPOCH_SERVING,
        evaluator_hash=_EVALUATOR_HASH,
        snapshot_hash=_SNAPSHOT_HASH,
        cost_model_hash=_COST_MODEL_HASH,
        ts=_CHARGE_TS,
    )
    # A second, bare charge for a null node — never registered, decided
    # or forward-tracked — against a different epoch, so K_effective's
    # charges_budget filter has something to exclude.
    trial_ledger.debit(
        _NULL_NODE_ID,
        _CAMPAIGN_NEWEST,
        outcome="ok",
        charges_budget=False,
        charge_units=1.0,
        epoch_id=_EPOCH_CLEAN_A,
        evaluator_hash=_EVALUATOR_HASH,
        snapshot_hash=_SNAPSHOT_HASH,
        cost_model_hash=_COST_MODEL_HASH,
        ts=_NULL_CHARGE_TS,
    )

    # Last, and after every row the sidecar is about: §7.1's file names two
    # nodes, and both must already stand in the tree store for the sealed
    # world to be one an operator can join.
    sidecar_path, sidecar_key = _seal_null_sidecar(url)

    return DemoSeedReport(
        campaign_ids=(_CAMPAIGN_OLDEST, _CAMPAIGN_MIDDLE, _CAMPAIGN_NEWEST),
        node_id=_NODE_ID,
        epoch_ids=(_EPOCH_SERVING, _EPOCH_CLEAN_A, _EPOCH_CLEAN_B),
        forward_observed_on=(observed_on[0].isoformat(), observed_on[1].isoformat()),
        real_node_id=_NODE_ID,
        null_node_id=_NULL_NODE_ID,
        null_sidecar_path=sidecar_path,
        null_sidecar_key=sidecar_key,
    )


# -- The entrypoint -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """``python -m nullius_api.demo`` — read ``DATABASE_URL``, seed it.

    One plain sentence on stderr and exit status 2 for a misconfiguration
    or a refused write — never a traceback, the same stance
    :func:`nullius_api.__main__.main` takes for the server's own
    misconfigurations, because an operator running a seed script is
    exactly the reader the structured refusals in every store below
    already write for.

    The summary prints the two values the demo's ``POST /target`` needs
    exported, spelled as the assignments an operator can paste: the path
    §7.1's sidecar was sealed at and the ``hex:`` reference that opens it.
    The key is printed here and **nowhere else** — it is held by no file
    and by no store — so the summary says whose run those values belong to,
    because the next seeding of the same store will have replaced the file
    under a key only *that* run printed.
    """
    _ = argv  # no flags: the database is named by DATABASE_URL alone
    url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not url:
        print(
            f"nullius_api.demo: {DATABASE_URL_ENV} must name the sqlite:/// "
            "database to seed; the repair is that environment variable, "
            "pointed at the store the server will also read",
            file=sys.stderr,
        )
        return 2
    try:
        report = seed_demo_store(url)
    except Exception as exc:  # noqa: BLE001 - an operator reads this, never a traceback
        print(f"nullius_api.demo: {exc}", file=sys.stderr)
        return 2
    print(f"nullius_api.demo: seeded {url}")
    print(f"  campaigns (oldest to newest): {', '.join(report.campaign_ids)}")
    print(f"  pre-registered, decided node: {report.node_id}")
    print(f"  sealed epochs: {', '.join(report.epoch_ids)}")
    print(f"  forward observations on: {', '.join(report.forward_observed_on)}")
    print(f"  sealed null sidecar: {report.null_sidecar_path}")
    print(
        "    one null node and one real node, so POST /target answers the "
        "unknown-node 404 and the barrier:"
    )
    print(f"    null node: {report.null_node_id}")
    print(f"    real node: {report.real_node_id}")
    print(
        "    export these two to serve POST /target (the key belongs to "
        "THIS run; seeding again re-seals under a new one):"
    )
    print(f"      export NULL_SIDECAR_PATH={report.null_sidecar_path}")
    print(f"      export NULL_SIDECAR_KEY_REF={report.null_sidecar_key_ref}")
    print(
        "  paper execution engine: nullius_api.demo:PAPER_ENGINE "
        "(bind with NULLIUS_EXECUTION_ENGINE to serve POST /risk/halt)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - the entrypoint itself
    raise SystemExit(main())
