"""Suite-local fixtures for the providers package's tests.

This suite lives inside the workspace member (``packages/providers/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
The path bootstrap below puts the member's ``src/`` on ``sys.path`` — the same
mechanism the module loader uses when it scans members — because the root
project does not depend on this member and the venv therefore does not install
it; this suite runs with the repository's pytest (``uv run pytest
packages/providers`` from the workspace root).

The shared builders a test needs — a scripted provider, and the request and
completion constructors — are exposed as fixtures that return factory
callables, the way ``packages/snapshot``'s suite exposes its service.  They
are fixtures rather than a ``helpers.py`` imported by name because a bare
``from helpers import ...`` (or ``from conftest import ...``) resolves to
whichever suite's module was imported first the moment two suites run under
one pytest — the collision the ``infra/security`` suites avoid by importing
helpers on a full namespace path.  This member is not a namespace package, so
it follows the ``packages/`` convention instead: everything a test shares
lives in this conftest, and pytest injects it.

**Feature 203's fixtures bring their schema the way a deployment does.**  The
pin store writes one column on one row of a table two core migrations own, and
it deliberately does not create either (see
:mod:`providers._pin_store`).  So a test that wants a pinned node brings the
``node`` table through ``migrations/versions/0118_node_table.py`` and the
authoring-model column through ``0115_agent_model_trio.py`` — imported **by
file path**, because ``migrations/`` is not a package and is not on
``sys.path`` — which is the discipline ``packages/discovery/tests/conftest.py``
established for the campaign table and states the reasoning for.  A suite that
hand-wrote its own ``CREATE TABLE node`` would be pinning this store's
behaviour against a schema the suite made up.

**The three trees, and the branches only two of them reach.** Revision ``0115``
emits a bare ``NOT NULL`` — no default — on ``agent_model_id`` and on
``agent_sampling``, which SQLite lands on an empty table and refuses on a
populated one; the shipped chain runs the table's migration (``0118``) before
the column's, so both constraints land on an empty table and *hold from then
on*.  A tree the chain built therefore cannot hold a node without an authoring
model or without a sampling record: the database itself is the first half of
features 203 and 204's guarantee, and on such a tree the stores' job is the
second half — refusing a *different* value, refusing an alias, and answering an
idempotent retry.

The trio's third column is the exception and it is the point.
``agent_ckpt_hash`` is nullable **by design** — §9.1's comment on it is
``non-null for self-hosted weights`` — so its null is a recorded fact rather
than an un-backfilled state, and it is the one column feature 204 can write on
the chain-built tree.

So :func:`pinned_database` is the chain-built tree, and the two backfill trees
cover the two columns the chain cannot leave empty:
:func:`nullable_trio_database` is a populated tree whose ``agent_model_id``
accepts NULL, and :func:`weights_database` is one whose ``agent_sampling`` and
``agent_ckpt_hash`` do.  Neither shape is invented for this suite — both are the
state 0115's own docstring names as the repair (*"a backfill, not a spell"*),
reached on either dialect by the three-step form the bare constraint forces
(add nullable, backfill, then constrain).  A backfill is a **write**, so the
stores' write branches are only reachable there, and the fixtures say so.  Both
build that shape from 0115's own :data:`~0115.COLUMN_TYPES` map rather than from
a spelling written here, so the state a test drives is one the schema's owner
describes.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import time
from pathlib import Path
from types import ModuleType

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from providers import (
    AgentModelPins,
    AgentSampling,
    Completion,
    Message,
    ModelPin,
    Provider,
    Request,
    Usage,
)

# conftest.py -> packages/providers/tests -> packages/providers -> packages -> root
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two revisions the ``node`` table's provenance lives across, by id.
#: Spelled as constants so a reader can see which two tables the features are
#: about without reading the fixtures, and so a rename is one edit.
NODE_MIGRATION = "0118_node_table"
TRIO_MIGRATION = "0115_agent_model_trio"

#: The revision that creates the ``campaign`` table — feature 104's, the
#: planned rows feature 232's planner writes and feature 202's scheduler
#: probes read-only.  Brought by the fixture the same way the ``node``
#: revisions above are: through the migration's own ``apply``, never a
#: hand-written ``CREATE TABLE``, so the campaign shape a scheduling test
#: probes against is the schema its owner describes.
CAMPAIGN_MIGRATION = "0111_campaign_table"

#: The authoring model a test's planted node is recorded under when the test
#: does not say, as the column's own spelling.  One constant rather than a
#: literal repeated in the fixture and each test, because the *agreement*
#: between a planted node and a default-built pin is what most of these tests
#: are about — and an agreement two places spell is one that can drift.
DEFAULT_AUTHOR = "anthropic/claude-opus-5/20260401"

#: The sampling record a planted node carries, as the column's own canonical
#: spelling — feature 204's four settings at their defaults, key-sorted and
#: compact, which is what ``AgentSampling().to_json()`` produces.  Written out
#: rather than computed so that :func:`plant_node` can be handed a row by a test
#: that has not imported the member's value type, and pinned against
#: :func:`make_sampling`'s default by the suite rather than by a shared call.
DEFAULT_SAMPLING = '{"seed":0,"temperature":0.0,"thinking":false,"top_p":1.0}'

#: A checkpoint hash a planted node carries when a test supplies one — the
#: digest of "a set of weights", spelled as 64 hex characters so it survives
#: ``require_agent_ckpt_hash``.  Not a real digest of anything: this suite is
#: about which value lands in the column and which is refused, and a constant
#: that happened to hash some artifact would only invite a reader to think the
#: suite was checking the artifact.
DEFAULT_CKPT_HASH = "ab" * 32

#: The columns :func:`plant_node` supplies values for, beyond 0118's five
#: structural ones: exactly the columns 0115 constrains, because a node that
#: omits one cannot exist.  Pinned against the migration by
#: :func:`pinned_database` — no more (which would be this suite inventing
#: schema) and no fewer (which would make the insert incomplete).
PLANTED_CONSTRAINED_COLUMNS = ("agent_model_id", "agent_sampling")

#: The columns :func:`plant_node` supplies *when the tree has them*, beyond the
#: constrained ones above.  ``agent_ckpt_hash`` is 0115's third column and it is
#: the one the schema leaves nullable — deliberately, since §9.1's comment on it
#: is ``non-null for self-hosted weights`` — so a planted node carries one only
#: when the test asks.  A tuple rather than a literal so the fixture and the
#: tests that reason about which columns exist share one list.
PLANTED_OPTIONAL_COLUMNS = ("agent_ckpt_hash",)


class ScriptedProvider(Provider):
    """A test provider that answers from a caller-supplied function.

    The honest shape of a concrete provider: it puts its "transport" in
    :meth:`_complete` as a callable, and inherits the interface's request
    validation, completion validation and error vocabulary from the base
    class for free.  A suite drives the interface through it — the request a
    caller sends, the completion that comes back, the refusals when either is
    malformed — the way feature 150's suites drive the boundary through
    ``RecordingProviderClient``.
    """

    def __init__(self, responder, *, models=None):
        self._responder = responder
        self._models = models

    def _complete(self, request: Request) -> Completion:
        return self._responder(request)

    def check_model(self, model: str) -> str:
        if self._models is not None and model not in self._models:
            from providers import UnknownModelError

            raise UnknownModelError(
                f"this provider does not serve {model!r}; it serves "
                f"{sorted(self._models)}"
            )
        return model


@pytest.fixture
def scripted_provider():
    """Return the :class:`ScriptedProvider` class, for a test to instantiate.

    A factory fixture rather than a bare import: the test supplies the
    responder (and, where it wants to, the served-model set), so the provider
    is built per test with the transport that test is exercising.
    """
    return ScriptedProvider


@pytest.fixture
def make_completion():
    """Return a builder that makes a :class:`Completion` with sensible defaults."""

    def _make(content="answer", *, model="test-model", **usage):
        return Completion(
            content=content,
            model=model,
            usage=Usage(
                input_tokens=usage.get("input_tokens", 1),
                output_tokens=usage.get("output_tokens", 2),
                cache_read_tokens=usage.get("cache_read_tokens", 0),
            ),
        )

    return _make


@pytest.fixture
def make_request():
    """Return a builder that makes a :class:`Request` with sensible defaults."""

    def _make(*, model="test-model", temperature=0.0, max_tokens=64, bodies=()):
        return Request(
            messages=tuple(
                Message(role=role, content=content) for role, content in bodies
            ),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return _make


# ── Feature 203's schema fixtures ─────────────────────────────────────────────
#
# Everything below brings a database to the shape feature 203 writes into, by
# running the migrations that own that shape.  Nothing here hand-writes a
# CREATE TABLE: the column belongs to 0115 and the table to 0118, and a suite
# that spelled either itself would be pinning this store against a schema the
# suite invented — see the module docstring.


def load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is not on ``sys.path``; a migration is
    loaded by its runner the same way — by path — so loading it by path here is
    the shape a migration is *built* to be used in rather than a workaround.  A
    missing file fails with the path in the message, because the one failure a
    test should never have to guess at is "the schema owner moved".

    Public (no leading underscore) because two test modules need it: this
    conftest's fixtures, and the suite that pins 0115's own constants against
    what this member declares.  A suite reaching into a private helper of its
    own conftest would still work, but a reader would have to check whether the
    underscore meant something.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the migrations that "
            "own feature 203's schema rather than hand-writing their DDL, so it "
            "needs the schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_providers_test_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_schema(database_url: str, *revisions: str) -> None:
    """Bring ``database_url`` to ``revisions``, in the order given.

    Through each migration's own ``apply``, which opens, runs and commits on the
    named database — the standalone entry point those files advertise for a
    caller with no migration runner, which is the state of this workspace.
    """
    for revision in revisions:
        load_migration(revision).apply(database_url)


def sqlite_path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test.

    This suite's own four lines rather than a call into the member: the store's
    ``_sqlite_path`` is private, and a test reaching into it would be pinning an
    implementation detail it should be free to change.  The URL grammar the
    migrations use is what :func:`providers._pin_store._sqlite_path` mirrors, so
    the translation is the same three steps by design.
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a tree file only this test can see.

    Nothing is created: the file does not exist until a fixture or a test brings
    a schema to it, which is what lets the "no ``node`` table at all" case be
    tested as the *first* thing that happens to a fresh database.
    """
    return f"sqlite:///{tmp_path / 'tree-test.db'}"


@pytest.fixture
def unpinned_database(database_url: str) -> str:
    """A database holding ``node`` — and no authoring-model column.

    The deployment state ``CampaignRecords``' own docstring describes and this
    store refuses: revision ``0118`` has run, revision ``0115`` has not.  It is
    a real state, not a contrived one — the chain dispatches the column features
    *before* the table feature, so a database assembled in the order the chain
    was built to run stops at 0118 with the table and none of the columns — and
    it is the one whose repair is an operation rather than a value.
    """
    create_schema(database_url, NODE_MIGRATION)
    return database_url


@pytest.fixture
def pinned_database(database_url: str) -> str:
    """A tree as the shipped chain builds it: ``node`` with 0115's trio.

    The deployment-shaped starting point for feature 203, and the tree on which
    the feature's *constraint* half is already enforced: 0115's
    ``agent_model_id TEXT NOT NULL`` is in place, so the database refuses a node
    row with no authoring model.  ``plant_node`` supplies a triple for exactly
    that reason — see its docstring.

    ``migrations/``' chain is not run in revision order here, because ``0115``'s
    ``ALTER`` needs the table to exist — so the table's migration runs first and
    the column's second, which is the order the ``node`` tasks must be renumbered
    into and a property of *this fixture* rather than a claim about the chain
    (0115's own docstring says the collision and this fixture does not restate
    it).
    """
    create_schema(database_url, NODE_MIGRATION, TRIO_MIGRATION)
    # The premise every other fixture in this file rests on, checked rather than
    # assumed: a tree the chain built refuses a node with no authoring model, so
    # `plant_node` supplies exactly the columns 0115 constrains and this is where
    # "exactly" is pinned against the migration — a fourth constrained column
    # added by a future revision breaks here rather than surfacing as a puzzling
    # IntegrityError inside some other feature's test.
    trio = load_migration(TRIO_MIGRATION)
    assert tuple(trio.NOT_NULL_COLUMNS) == PLANTED_CONSTRAINED_COLUMNS, (
        f"0115 constrains {trio.NOT_NULL_COLUMNS!r} but plant_node supplies "
        f"{PLANTED_CONSTRAINED_COLUMNS!r}; the two must agree or a planted node "
        f"cannot exist"
    )
    return database_url


@pytest.fixture
def nullable_trio_database(database_url: str) -> str:
    """A populated tree whose ``agent_model_id`` accepts NULL — the backfill state.

    **The one tree in this suite on which the store's write branch is
    reachable, and it exists because the shipped chain's tree cannot be it.**
    Revision ``0115`` emits ``ALTER TABLE node ADD COLUMN agent_model_id TEXT
    NOT NULL`` with no default, which SQLite and Postgres both land on an *empty*
    table and both refuse on a populated one; 0115's docstring calls that refusal
    correct and says so in as many words:

        A row that predates the column has no recorded authoring model, and no
        default could assert one truthfully ... so the refusal is the correct
        failure and the repair is a backfill, not a spell.

    On :func:`pinned_database` the constraint landed on the empty table and holds
    from then on, so no node there can be missing its authoring model — the
    database enforces feature 203's guarantee and this store's write branch is
    unreachable.  A backfill is a **write**, though, and it is the write the
    store's write branch *is*, so the state it answers has to be reachable
    somewhere or that branch is untested code.  This fixture reaches it the way
    the repair does — the additive-then-constrain form the bare ``NOT NULL``
    forces: 0118's table, then the trio added **without** the constraint, which
    is a populated-safe ``ADD COLUMN`` on both dialects.

    Nothing about the columns is re-decided here: the list and the type come from
    0115's own :data:`~0115.COLUMNS` and :data:`~0115.COLUMN_TYPES`, through
    0115's own :func:`~0115._column_type`, called exactly as its
    ``_add_statement`` calls it.  The only thing omitted is the constraint 0115
    says cannot be expressed on a populated table, and that omission is the
    fixture's whole declaration.

    Two neighbours, neither of them this fixture.  A tree with no trio at all —
    ``tripwires.layout.node_bootstrap_schema``'s five structural columns — is
    :func:`unpinned_database`, which is why the *column absent* case is tested
    there and not here.  And a table whose ``NOT NULL`` was landed on an empty
    table first can never hold a NULL, which is :func:`pinned_database`.
    """
    create_schema(database_url, NODE_MIGRATION)
    trio = load_migration(TRIO_MIGRATION)
    # Every column 0115 adds, at 0115's own SQLite type, deliberately *without*
    # its NOT NULL constraints — the additive step of the repair, with the
    # columns and types read from the migration rather than written here.  The
    # statement is 0115's own `_add_statement` with only its constraint clause
    # dropped, so a reader comparing the two sees one difference and knows it is
    # the whole of this fixture's deviation.
    assert trio.COLUMNS, "0115 adds no columns, so this fixture has nothing to add"
    assert trio.NOT_NULL_COLUMNS, (
        "0115 constrains none of the columns it adds, so no tree it built could "
        "refuse a NULL — and then the constraint this suite's other tree enforces "
        "would not exist and the backfill state would be reached by an ordinary "
        "insert rather than by a repair"
    )
    statements = tuple(
        f"ALTER TABLE {trio.NODE_TABLE} ADD COLUMN {column} "
        f"{trio._column_type(column, 'sqlite')}"
        for column in trio.COLUMNS
    )
    path = sqlite_path_of(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        for statement in statements:
            connection.execute(statement)
    return database_url


@pytest.fixture
def weights_database(database_url: str) -> str:
    """A populated tree whose ``agent_sampling`` and ``agent_ckpt_hash`` accept NULL.

    **The tree feature 204's write branch and its conflict refusals are
    reachable on, and it exists because the chain-built tree cannot be it.**

    Two of the three columns behave differently on the empty table the chain
    actually builds.  ``agent_model_id`` and ``agent_sampling`` carry a bare
    ``NOT NULL`` (0115), so on :func:`pinned_database` both landed on an empty
    table and hold from then on — no node there can be missing either, and
    ``persist_weights``' write branch is unreachable.  ``agent_ckpt_hash`` is
    nullable by design, so *its* null is the hosted-API fact rather than an
    un-backfilled state.

    What this fixture adds is therefore the state ``0115`` calls the repair for
    the *other* column — *"a backfill, not a spell"* — reached the same
    three-step way :func:`nullable_trio_database` reaches it: 0118's table, then
    the trio added **without** the constraints, which is a populated-safe
    ``ADD COLUMN`` on both dialects.  A ``NULL`` sampling is then writable, so
    there is a tree on which ``persist_weights`` genuinely writes rather than
    answering the row it found.

    Nothing about the columns is re-decided here: the list and the types come
    from 0115's own :data:`~0115.COLUMNS` and :data:`~0115.COLUMN_TYPES`,
    through 0115's own :func:`~0115._column_type`, called exactly as its
    ``_add_statement`` calls it.  The only thing omitted is the constraint 0115
    says cannot be expressed on a populated table, and that omission is this
    fixture's whole declaration.

    Its neighbours, so a reader knows which tree to reach for:
    :func:`pinned_database` is the chain-built tree (both ``NOT NULL`` columns
    in place, so only the retry and conflict answers are reachable);
    :func:`nullable_trio_database` is the same shape seen by feature 203, where
    a **model** can be NULL; and :func:`unpinned_database` has no trio at all,
    which is why the missing-column case is tested there.
    """
    create_schema(database_url, NODE_MIGRATION)
    trio = load_migration(TRIO_MIGRATION)
    assert trio.COLUMNS, "0115 adds no columns, so this fixture has nothing to add"
    statements = tuple(
        f"ALTER TABLE {trio.NODE_TABLE} ADD COLUMN {column} "
        f"{trio._column_type(column, 'sqlite')}"
        for column in trio.COLUMNS
    )
    path = sqlite_path_of(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        for statement in statements:
            connection.execute(statement)
    return database_url


@pytest.fixture
def node_id() -> str:
    """A fresh canonical node UUID — an id the caller supplies.

    Distinct per test, and a real UUID, because the store canonicalizes ids
    through :class:`uuid.UUID` and a hand-rolled string would be exercising the
    refusal rather than the feature.
    """
    return str(uuid.uuid4())


@pytest.fixture
def plant_node():
    """Return a callable that inserts one node row, with its authoring record.

    Raw SQL against the table the migration created rather than a call into any
    node-planting feature: there is no such feature in this member, and the point
    is to produce the *state* the features are about — a node row exists,
    carrying whatever authoring record it carries — not to reproduce the
    authoring path.  ``parent_id`` stays ``NULL``, which is what makes the row a
    root.

    **Every value is a parameter, and each one's default is the recorded state
    rather than an absence, because on a tree the chain built the columns cannot
    be omitted.**  0115's ``NOT NULL`` — on ``agent_model_id`` and on
    ``agent_sampling`` — means ``INSERT INTO node (id, parent_id, campaign_id,
    theme_root, depth)`` is not a complete statement; SQLite refuses it, which is
    the database enforcing the authoring record ahead of the store.  So a node
    planted on :func:`pinned_database` is a node some model is recorded as
    having authored, with its dice recorded beside it, and ``agent_model_id=None``
    is how a test asks for the other state — a row with *no* recorded model —
    which only :func:`nullable_trio_database` can hold and the chain-built tree
    correctly refuses.

    ``agent_ckpt_hash`` defaults to ``None`` and that default is the *hosted-API*
    record rather than a missing value: it is 0115's one nullable column, and
    §9.1's comment on it — ``non-null for self-hosted weights`` — makes the null
    a fact about where the weights came from.  A test wanting a self-hosted node
    passes :data:`DEFAULT_CKPT_HASH`.

    The columns supplied beyond 0118's five are exactly
    :data:`PLANTED_CONSTRAINED_COLUMNS` plus :data:`PLANTED_OPTIONAL_COLUMNS` —
    **and only those the tree actually has**.  That second clause is what lets
    one fixture plant on all four of this suite's trees: a chain-built tree has
    the whole trio, the two backfill trees have it too, and
    :func:`unpinned_database` has none of it (revision 0118 has run and 0115 has
    not), where naming a column that does not exist would be an
    ``OperationalError`` about *this fixture* rather than about the store under
    test.  So the statement is assembled from the table's own columns, and the
    caller's values are supplied wherever there is a column to supply them to.
    """

    def _plant(
        database: str,
        identifier: str,
        *,
        agent_model_id: str | None = DEFAULT_AUTHOR,
        agent_sampling: str | None = DEFAULT_SAMPLING,
        agent_ckpt_hash: str | None = None,
        depth: int = 0,
    ) -> str:
        campaign = str(uuid.uuid4())
        columns = ["id", "parent_id", "campaign_id", "theme_root", "depth"]
        values: list[object] = [identifier, None, campaign, "macro", depth]
        with closing(sqlite3.connect(sqlite_path_of(database))) as connection, connection:
            present = {
                row[1] for row in connection.execute("PRAGMA table_info(node)")
            }
            for column, value in (
                ("agent_model_id", agent_model_id),
                ("agent_sampling", agent_sampling),
                ("agent_ckpt_hash", agent_ckpt_hash),
            ):
                if column in present:
                    columns.append(column)
                    values.append(value)
            connection.execute(
                f"INSERT INTO node ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                values,
            )
        return identifier

    return _plant


@pytest.fixture
def stored_weights():
    """Return a callable reading a node's two feature-204 columns straight from the table.

    A raw read rather than a call into the store, on the same grounds
    ``test_pin_store.stored_value`` states for the triple: several of these
    tests are about *what the store did not change*, and asking the store to
    confirm that would be asking the thing under test.  Returns the pair
    ``(ckpt_hash, sampling)`` as the row holds them — unparsed, so a test can
    assert on a NULL and on the exact stored text.
    """

    def _read(database: str, identifier: str):
        with closing(sqlite3.connect(sqlite_path_of(database))) as connection:
            row = connection.execute(
                "SELECT agent_ckpt_hash, agent_sampling FROM node WHERE id = ?",
                (identifier,),
            ).fetchone()
        return None if row is None else tuple(row)

    return _read


@pytest.fixture
def make_weights():
    """Return a builder for the two arguments :meth:`persist_weights` takes.

    A pair builder rather than one call per argument, because the two travel
    together at every call site — this is feature 204's ask, and a test that
    spelled the hash and the sampling on separate lines would be inviting a
    reader to think they were independent.  Defaults are the hosted-API case and
    the defaults of all four settings, which is what a deployment that runs
    hosted and turns no knobs records.
    """

    def _make(ckpt_hash: str | None = None, **sampling):
        return {
            "ckpt_hash": ckpt_hash,
            "sampling": AgentSampling(**sampling) if sampling else AgentSampling(),
        }

    return _make


@pytest.fixture
def make_sampling():
    """Return a builder that makes an :class:`AgentSampling` with sensible defaults.

    The defaults are :data:`~providers.DEFAULT_SAMPLING`'s, so a sampling a test
    builds and the record a planted node carries agree without the test saying
    so twice — the same agreement :func:`make_pin` and :data:`DEFAULT_AUTHOR`
    have for the triple.
    """

    def _make(temperature=0.0, top_p=1.0, thinking=False, seed=0):
        return AgentSampling(
            temperature=temperature, top_p=top_p, thinking=thinking, seed=seed
        )

    return _make


@pytest.fixture
def pins(pinned_database: str) -> AgentModelPins:
    """The pin store, over the tree the shipped chain builds.

    Both of feature 203's migrations have run, so ``agent_model_id`` exists with
    0115's type and its ``NOT NULL`` — the tree on which the store's reads, its
    conflict refusal, its alias refusal and its idempotent retry are exercised,
    because no node here can be missing an authoring model.
    """
    return AgentModelPins(pinned_database)


@pytest.fixture
def nullable_pins(nullable_trio_database: str) -> AgentModelPins:
    """The pin store, over the populated tree whose column accepts NULL.

    The only tree on which ``persist``'s *write* branch is reachable, because
    the chain-built tree cannot hold a node with no authoring model — see
    :func:`nullable_trio_database`.
    """
    return AgentModelPins(nullable_trio_database)


@pytest.fixture
def weights_pins(weights_database: str) -> AgentModelPins:
    """The pin store, over the tree whose sampling and checkpoint columns accept NULL.

    The tree feature 204's write branch is reachable on, for the reason
    :func:`weights_database` sets out: on a chain-built tree the ``NOT NULL`` on
    ``agent_sampling`` landed on the empty table and holds, so
    ``persist_weights`` could only ever answer the row it found.
    """
    return AgentModelPins(weights_database)


@pytest.fixture
def make_pin():
    """Return a builder that makes a :class:`ModelPin` with sensible defaults.

    Defaults chosen from the ids architecture §14.1's own tables name, so a
    test's fixture reads like the deployment it is standing in for: a root-tier
    pin, a depth-tier pin and a self-hosted one are one keyword apart.  The
    defaults are the same triple :data:`DEFAULT_AUTHOR` spells, so a planted node
    and ``make_pin()`` agree about who authored it without a test saying so
    twice.
    """

    def _make(
        provider="anthropic",
        model="claude-opus-5",
        version="20260401",
    ):
        return ModelPin(provider=provider, model=model, version=version)

    return _make


# ── Feature 202's fixtures ─────────────────────────────────────────────────────
#
# The scheduler probes the campaign table read-only and owns its own
# depth_run_window table, so the two database fixtures below are: one that
# brings 0111's campaign table the way a deployment does (through the
# migration's own apply), and the shared file-only URL this suite already
# uses, on which the store's lazily-created table is exercised as the
# *first* thing that happens to a fresh database.


@pytest.fixture
def campaign_database(database_url: str) -> str:
    """A database holding the ``campaign`` table, with no rows planned.

    Revision ``0111`` has run and nothing has been planned into it — the
    state a scheduler meets on a deployment whose planner has not yet run,
    and the one whose repair (:class:`providers.UnknownCampaignError`)
    names the campaign record rather than the migrations.
    """
    create_schema(database_url, CAMPAIGN_MIGRATION)
    return database_url


@pytest.fixture
def plant_campaign():
    """Return a callable that inserts one planned campaign row, by id.

    Raw SQL against the table the migration created rather than a call
    into the discovery member: no member imports another, and the point
    is to produce the *state* feature 202 schedules against — a campaign
    row exists, keyed by the id the scheduler will be handed — not to
    reproduce the planning path.  The three NOT NULL planning columns are
    supplied because ``0111`` refuses a row without them; a fresh UUID is
    minted for the id when the test does not supply one, so the callable's
    return value is always the id to schedule by.
    """

    def _plant(
        database: str,
        campaign_id: str | None = None,
        *,
        campaign_type: str = "Type-R",
        workspace_count: int = 16,
    ) -> str:
        identifier = campaign_id or str(uuid.uuid4())
        null_fraction = min(max(2.0 / workspace_count, 0.15), 0.35)
        with closing(
            sqlite3.connect(sqlite_path_of(database))
        ) as connection, connection:
            connection.execute(
                "INSERT INTO campaign (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, ?, ?, ?)",
                (identifier, campaign_type, workspace_count, null_fraction),
            )
        return identifier

    return _plant


@pytest.fixture
def deepseek_peaks():
    """§14.2's own time-of-day card, as the configuration's test data.

    The card the lever is stated on — *"peak is 01:00–04:00 and 06:00–10:00
    UTC"* — spelled as :class:`providers.PeakPricing` so a scheduling test
    reads like the deployment it stands in for.  It is test data, not a
    default the module carries: §14.2's own preamble (*"rates move monthly
    … the numbers are not"*) is the reason the module holds only the
    arithmetic and never the windows, the same reason feature 198's record
    carries no price at all.
    """
    from providers import PeakPricing, PeakWindow

    return PeakPricing(
        windows=(
            PeakWindow(start=time(1, 0), end=time(4, 0)),
            PeakWindow(start=time(6, 0), end=time(10, 0)),
        )
    )


# ── Feature 200's fixtures ─────────────────────────────────────────────────────
#
# The measurement probes the campaign table read-only and owns its own
# depth_cache_rate table, so it reuses feature 202's campaign fixtures
# (campaign_database, plant_campaign) unchanged.  What this section adds is
# the economics: the card a selection ranks by, and the depth-model
# candidates it ranks.


@pytest.fixture
def depth_cache_card():
    """§14.2's own depth row, as the cache-pricing configuration's test data.

    The card the lever is stated on — *"Select the depth model on cache-hit
    price, not list price"*, over a row whose comment reads *"Cache-hit
    price dominates.  DeepSeek's $0.006 is ~80× below Claude's cached
    input and ~4× below Gemini's"* — spelled as
    :class:`providers.CachePricing` so a selection test reads like the
    deployment it stands in for.  The list prices are §14.2's own
    off-peak figures (``$0.30`` DeepSeek, ``$0.25`` Gemini, ``$1``
    Claude); DeepSeek's hit price is the row's own ``$0.006/M cache
    hits``, and the other two hit prices are read off the row's own
    ratios ($0.006 × ~4 ≈ $0.024, × ~80 ≈ $0.48) because the table
    states them that way rather than as absolutes.

    The load-bearing property is the disagreement: Gemini has the
    **cheaper list** price and the **dearer hit** price, so a selection
    over this card is the sentence's *rather than* as one comparison —
    picking deepseek-flash is what ranking on the hit looks like, and
    picking gemini-3.1-flash-lite is what ranking on the list would have
    looked like, and the fixture exists so a test can tell them apart.
    """
    from providers import CachePrice, CachePricing

    return CachePricing(
        prices=(
            CachePrice(
                model="deepseek-flash", input_price=0.30, cache_hit_price=0.006
            ),
            CachePrice(
                model="gemini-3.1-flash-lite",
                input_price=0.25,
                cache_hit_price=0.024,
            ),
            CachePrice(
                model="claude-haiku-4-5", input_price=1.00, cache_hit_price=0.48
            ),
        )
    )


@pytest.fixture
def depth_candidates():
    """The three models of §14.2's depth row, as feature 198's records.

    Each one clears feature 198's bar (a 1M-token window at flat pricing —
    the row's own ``1M flat`` for DeepSeek, ``flat`` for Gemini and
    ``no long-ctx premium`` for Claude), because feature 200's selection
    composes *behind* that gate: the candidates a cache-pricing card ranks
    are the survivors of the physics check, and a fixture that offered a
    sub-bar candidate would be testing the wrong seam.  The order is the
    card's own, so the two fixtures read as one table.
    """
    from providers import DepthModel, flat_pricing

    return (
        DepthModel(
            model="deepseek-flash",
            context_tokens=1_000_000,
            surcharge_threshold=flat_pricing(),
        ),
        DepthModel(
            model="gemini-3.1-flash-lite",
            context_tokens=1_000_000,
            surcharge_threshold=flat_pricing(),
        ),
        DepthModel(
            model="claude-haiku-4-5",
            context_tokens=1_000_000,
            surcharge_threshold=flat_pricing(),
        ),
    )


# ── Feature 196's fixtures ─────────────────────────────────────────────────────
#
# The root-provenance store probes feature 97's ``node`` table read-only and
# owns its own root_serving_provider table, so what this section adds is a tree
# to record against and the declared rotation to check the record against.
# The database fixtures below bring ``node`` up the way a deployment does —
# through 0118's own apply — and then plant the root the call authored, using
# feature 203's ``plant_node`` unchanged because it assembles its statement
# from the table's own columns.


@pytest.fixture
def tree_database(database_url: str) -> str:
    """A tree holding feature 97's ``node`` table, with no nodes in it.

    Revision ``0118`` has run and nothing has been expanded into it — the
    state a recorder meets on a deployment whose discovery loop has not yet
    placed a root, and the one whose repair
    (:class:`providers.RootNotRecordedError`) names the expansion rather
    than the migrations.

    Deliberately 0118 **alone**: feature 196 records a root call's serving
    provider, and nothing about that record needs 0115's authoring trio — a
    store that demanded one would be demanding feature 203's premise for
    feature 196's fact.  So the tree here is the one the migration that owns
    ``node`` builds, and the root planted into it is planted by a fixture
    that supplies the trio only where the columns exist.
    """
    create_schema(database_url, NODE_MIGRATION)
    return database_url


@pytest.fixture
def root_call():
    """Return a callable building one root call, and the node it is about.

    The callable plants a node row at ``depth`` in a campaign of its own
    choosing and returns the :class:`providers.RootCall` describing it — the
    two facts the recorder will verify against the tree are *the same facts
    the tree was given*, which is the only way a test can mean "a root call
    that happened" rather than "a description a store might accept".

    Returns ``(call, node_id)``: the call for the store, and the bare id for
    the ``get``-side assertions and for the store's own refusals, which name
    it.  ``depth`` defaults to ``0`` — §14.1's shallowest root — and a test
    wanting the boundary's other end passes ``1``; a test wanting the
    refusal passes ``2`` and plants it, because a depth call the tree
    *agrees* about is the case the boundary is really about.

    This fixture plants its own row rather than delegating to
    :func:`plant_node`, and the reason is the store's own gate: feature 196
    verifies a call's campaign against the tree's, so a fixture that minted
    the campaign inside the plant and handed back only the id would leave the
    test unable to build a call that agrees with its own tree.  The
    statement is assembled from ``PRAGMA table_info(node)`` exactly as
    ``plant_node``'s is, so it plants on a tree with or without 0115's trio
    and the two fixtures cannot drift on which columns they supply.
    """

    def _plant(
        database: str,
        *,
        depth: int = 0,
        campaign_id: str | None = None,
        identifier: str | None = None,
    ):
        from providers import RootCall

        node = identifier or str(uuid.uuid4())
        campaign = campaign_id or str(uuid.uuid4())
        with closing(
            sqlite3.connect(sqlite_path_of(database))
        ) as connection, connection:
            columns = ["id", "parent_id", "campaign_id", "theme_root", "depth"]
            values: list[object] = [node, None, campaign, "macro", depth]
            present = {
                row[1] for row in connection.execute("PRAGMA table_info(node)")
            }
            for column, value in (
                ("agent_model_id", DEFAULT_AUTHOR),
                ("agent_sampling", DEFAULT_SAMPLING),
            ):
                if column in present:
                    columns.append(column)
                    values.append(value)
            connection.execute(
                f"INSERT INTO node ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                values,
            )
        return RootCall(node_id=node, campaign_id=campaign, depth=depth), node

    return _plant


@pytest.fixture
def frontier_tier():
    """§14.1's own roots row, as the declared rotation.

    The two-to-three frontier families the architecture's rate card names for
    the roots row — *"Rotate all three.  Different families, different priors,
    different mechanisms proposed"* — spelled as :class:`providers.FrontierTier`.
    It is test data, not a default the module carries: §14.2's own preamble
    (*"rates move monthly … the selection logic is stable, the numbers are
    not"*) is the reason the module declares the boundary and the membership
    rule and never a model name, the same reason feature 198's record carries
    no price and feature 202's carries no window.
    """
    from providers import FrontierProvider, FrontierTier

    return FrontierTier(
        providers=(
            FrontierProvider(provider="anthropic", model="claude-opus-5"),
            FrontierProvider(provider="openai", model="gpt-5.6-sol"),
            FrontierProvider(provider="google", model="gemini-3.1-pro"),
        )
    )


@pytest.fixture
def root_serving_providers(tree_database: str):
    """Feature 196's store, bound to the tree this test can see."""
    from providers import RootProviderRotation

    return RootProviderRotation(tree_database)


@pytest.fixture
def root_rotation(tree_database: str):
    """Feature 197's store, bound to the tree this test can see.

    The same database :func:`root_serving_providers` is handed, because the
    two features are two halves of one act: feature 197 *decides* which
    declared family serves a root and persists that decision, and feature
    196 *records* the provider that answered — the second call goes through
    the first, so a rotation store pointed anywhere else would be pointed at
    a campaign whose roots the paired recorder cannot see.

    Nothing is created here: :func:`tree_database` has run revision 0118 and
    this feature's own table arrives on its first write, which is what lets
    a test observe the "no ``root_provider_rotation`` table yet" case as the
    first thing that happens to a fresh database.
    """
    from providers import RootRotation

    return RootRotation(tree_database)
