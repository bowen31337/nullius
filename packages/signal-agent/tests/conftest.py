"""Fixtures and import wiring for the signal-agent member's own suite.

This suite lives inside the workspace member
(``packages/signal-agent/tests``) rather than under the repository-level
``tests/`` tree, because the member — including its tests — is this feature's
file-claim scope, and the placement is the one the bootstrap, artifacts,
sandbox and canary members take for the same reason: same-basename files
collide under one pytest run, so each member's suite is collected under its
own conftest.

The path bootstrap puts two kinds of tree on ``sys.path``:

* the repository root's ``src/``, because this member's ``__init__`` imports
  ``app.module_loader`` for the registration protocol and the root project
  ships it;
* every declared member's scan root, resolved from the root
  ``pyproject.toml``'s own ``[tool.uv.workspace]`` through
  :func:`app.module_loader.workspace_scan_roots` rather than hard-coded —
  the same convention ``tests/contract/conftest.py`` follows, and for the
  same reason: this member's law is *written against* the ``contract``
  member's signal ABI and *screens against* the ``sandbox`` member's import
  allowlist, so a hard-coded path here could quietly disagree with the
  declaration that decides whether either member is on the path at all.

That gives the suite identical behaviour under
``uv run --all-packages pytest packages/signal-agent`` (where the venv also
provides every member) and under a bare ``pytest``.

**What the fixtures are.**  The vocabulary the tests share: the four laws this
member owns — feature 205's authoring contract, feature 212's legal theme gate,
feature 213's dead-territory gate and feature 211's stated-mechanism law — and
the sandbox's own admission screen.
The proposals every claim in
``test_authoring.py`` is made about live in that file beside the claims rather
than here — they are *text*, and several assertions are about the text itself
(it is returned unmodified; its hash is the tree's ``code_hash``), so a fixture
that rebuilt them per test would make "the same source" a claim about two
constructions rather than about one string.  The same reasoning puts
``test_themes.py``'s legal and illegal slugs at module scope there.

**Feature 211 is the one law here that reads the environment, and it is the
one whose store half has a schema to bring.**  Its barrier clause — *"never as
a scored input"* — is a pure function of the caller's wiring, like the other
three; but its store writes one column on one row of a table two core
migrations own, so :func:`mechanism_database` and :func:`mechanism_store` below
build that shape the way a deployment does: through
``migrations/versions/0118_node_table.py`` and
``migrations/versions/0117_identity_trio.py``, imported **by file path**,
because ``migrations/`` is not a package and is not on ``sys.path``.  That is
the discipline ``packages/providers/tests/conftest.py`` established for the
authoring-model trio and states the reasoning for, and it is the reason this
suite's fixture list stopped being purely value-shaped.

**There is still no environment isolation here.**  ``MechanismStore`` reads
``DATABASE_URL`` only through :meth:`~signal_agent.MechanismStore.resolve`, and
the fixtures below pass an explicit environment mapping rather than mutating
``os.environ`` — a suite that set and restored the process environment would be
one whose tests could interfere, and the store's own seam already takes the
mapping it should read.  Nothing here consults a clock.  A fixture that cleared
the environment would imply a knob this member does not have — the same
statement ``packages/sandbox/tests/conftest`` makes for its own laws.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest

# conftest.py -> packages/signal-agent/tests -> packages/signal-agent -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"

if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from app.module_loader import workspace_scan_roots

for _root in workspace_scan_roots():
    _entry = str(_root)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from signal_agent import (
    DeadTerritoryGate,
    MechanismStore,
    SignalContract,
    SignalThemeGate,
    StatedMechanism,
    dead_territory_gate,
    signal_contract,
    signal_theme_gate,
    stated_mechanism,
)

#: The two revisions feature 211's column lives across, by id — spelled as
#: constants so a reader can see which two migrations the feature is about
#: without reading the fixtures, and so a rename is one edit.  ``0118`` creates
#: the ``node`` table (feature 97) and ``0117`` adds ``stated_mechanism`` beside
#: ``code_hash`` and ``artifact_uri`` (feature 98's identity triple).
NODE_MIGRATION = "0118_node_table"
TRIO_MIGRATION = "0117_identity_trio"

#: The revisions directory the two above are loaded from, resolved off this
#: file rather than hard-coded, so the suite works from any checkout.
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"


@pytest.fixture
def law() -> SignalContract:
    """Feature 205's law, built directly rather than reached off a composed app.

    A test of the *law* should not depend on the factory having scanned
    anything; the component tests reach the composed one separately, which is
    the discipline the bootstrap member's suite states for its own worlds.
    """
    return signal_contract()


@pytest.fixture
def gate() -> SignalThemeGate:
    """Feature 212's law, built directly — the same discipline as ``law``.

    It differs from the fixture above in one way worth stating, because it is
    the feature's: this law *is* configured rather than declared elsewhere, so
    building it reads the committed ``legal_themes.json`` beside it.  That is
    still a fixture and not a composed application — the file ships inside the
    member, so the law needs no factory to be itself — and the component tests
    reach the composed gate separately.
    """
    return signal_theme_gate()


@pytest.fixture
def territory() -> DeadTerritoryGate:
    """Feature 213's law, built directly — the same discipline as ``gate``.

    Like the theme gate it *is* configured rather than declared elsewhere, so
    building it reads the committed ``dead_territory.json`` beside it.  It is
    still a fixture and not a composed application — the file ships inside the
    member — and the component tests reach the composed gate separately.  A
    separate fixture rather than reusing ``gate`` because the two laws are two
    gates: feature 212's allowlist and feature 213's denylist answer different
    questions, and a test of one must not hold the other.
    """
    return dead_territory_gate()


@pytest.fixture
def box_screen():
    """The sandbox's own admission test — feature 167's screen, as a callable.

    Built from the *sandbox member's* law and its committed allowlist, not
    from a stand-in: the claim under test is that feature 205's adoption can
    be gated by the box that will actually run the source, so the screen used
    here must be the real one.  Imported inside the fixture so the member's
    module-level imports stay the ones every other test needs.
    """
    from sandbox import committed_imports_allowlist, screen_module

    allowlist = committed_imports_allowlist()

    def screen(source: str):
        return screen_module(source, allowlist)

    return screen


# ── Feature 211's schema fixtures ─────────────────────────────────────────────
#
# Everything below brings a database to the shape feature 211 writes into, by
# running the migrations that own that shape.  Nothing here hand-writes a
# CREATE TABLE: the column belongs to 0117 and the table to 0118, and a suite
# that spelled either itself would be pinning this store against a schema the
# suite invented.


def load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is not on ``sys.path``; a migration is
    loaded by its runner the same way — by path — so loading it by path here is
    the shape a migration is *built* to be used in rather than a workaround.  A
    missing file fails with the path in the message, because the one failure a
    test should never have to guess at is "the schema owner moved".

    Public (no leading underscore) because ``test_mechanism.py`` pins 0117's own
    ``NOT_NULL_COLUMNS`` against what this feature declares, which is a claim
    about the migration rather than about this fixture.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the migrations that "
            "own feature 211's schema rather than hand-writing their DDL, so it "
            "needs the schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_signal_agent_test_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_schema(database_url: str, *revisions: str) -> None:
    """Bring ``database_url`` to ``revisions``, in the order given.

    Through each migration's own ``apply``, which opens, runs and commits on
    the named database — the standalone entry point those files advertise for a
    caller with no migration runner, which is the state of this workspace.
    """
    for revision in revisions:
        load_migration(revision).apply(database_url)


def sqlite_path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test.

    This suite's own four lines rather than a call into the member: the store's
    ``_sqlite_path`` is private, and a test reaching into it would be pinning an
    implementation detail it should be free to change.  The URL grammar the
    migrations use is what :func:`signal_agent._mechanism._sqlite_path` mirrors,
    so the translation is the same three steps by design.
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


#: The theme root a planted node carries.  One of PRD §9.3's six legal slugs, so
#: a planted row is a node feature 212 would have admitted — this feature's
#: suite is about the mechanism column, and a row that was itself illegal would
#: put a second feature's refusal in the way of every claim here.
PLANTED_THEME_ROOT = "momentum"

#: The columns :func:`plant_node` supplies beyond 0118's structural five:
#: exactly ``0117``'s two ``NOT NULL`` members, because on this tree they are
#: what a node cannot exist without.  Read from the migration by
#: :func:`mechanism_database` rather than written here — see its docstring.
PLANTED_CONSTRAINED_COLUMNS = ("code_hash", "artifact_uri")


def plant_node(database_url: str, node_id: str | None = None, **columns) -> str:
    """Insert one node row and return its id in canonical UUID text.

    The values 0117 constrains are supplied with placeholders, because on a
    tree built by this fixture's chain they are ``NOT NULL`` and a row without
    them cannot exist — the database enforces feature 98's guarantee and this
    function is what satisfies it.  ``stated_mechanism`` is deliberately **not**
    among them: it is the one member of the identity triple 0117 leaves
    nullable, which is the whole premise of feature 211, and a planted row
    therefore starts unstated unless a test passes ``stated_mechanism=``.
    """
    node = node_id or str(uuid.uuid4())
    values = {
        "code_hash": "c" * 64,
        "artifact_uri": f"file:///artifacts/{node}",
    }
    values.update(columns)
    names = ["id", "parent_id", "campaign_id", "theme_root", "depth", *values]
    placeholders = ", ".join("?" for _ in names)
    with (
        closing(sqlite3.connect(sqlite_path_of(database_url))) as connection,
        connection,
    ):
        connection.execute(
            f"INSERT INTO node ({', '.join(names)}) VALUES ({placeholders})",
            (
                node,
                None,
                str(uuid.uuid4()),
                PLANTED_THEME_ROOT,
                0,
                *values.values(),
            ),
        )
    return node


@pytest.fixture
def mechanism_database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a tree file only this test can see.

    Nothing is created: the file does not exist until a fixture or a test brings
    a schema to it, which is what lets the "no ``node`` table at all" case be
    tested as the *first* thing that happens to a fresh database.
    """
    return f"sqlite:///{tmp_path / 'mechanism-tree.db'}"


@pytest.fixture
def mechanism_database(mechanism_database_url: str) -> str:
    """A tree as the shipped chain builds it: ``node`` with 0117's identity triple.

    The deployment-shaped starting point for feature 211.  ``0118`` creates the
    table and ``0117`` adds ``code_hash``, ``stated_mechanism`` and
    ``artifact_uri`` — the table's migration first because ``0117``'s ``ALTER``
    needs the table to exist, which is the order this fixture applies them in
    and a property of *this fixture* rather than a claim about the chain.

    The premise every other fixture here rests on is checked rather than
    assumed: ``0117`` constrains exactly the two columns
    :data:`PLANTED_CONSTRAINED_COLUMNS` names, so a planted node can exist and
    so a fourth constrained column added by a future revision breaks here rather
    than surfacing as a puzzling ``IntegrityError`` inside some other test.
    """
    create_schema(mechanism_database_url, NODE_MIGRATION, TRIO_MIGRATION)
    trio = load_migration(TRIO_MIGRATION)
    assert tuple(trio.NOT_NULL_COLUMNS) == PLANTED_CONSTRAINED_COLUMNS, (
        f"0117 constrains {trio.NOT_NULL_COLUMNS!r} but plant_node supplies "
        f"{PLANTED_CONSTRAINED_COLUMNS!r}; the two must agree or a planted node "
        f"cannot exist"
    )
    return mechanism_database_url


@pytest.fixture
def unstated_database(mechanism_database_url: str) -> str:
    """A database holding ``node`` — and no ``stated_mechanism`` column.

    The deployment state this store refuses by name: revision ``0118`` has run
    and ``0117`` has not, so there is no column for an agent's rationale to live
    in.  It is a real state and not a contrived one — the chain dispatches the
    column features before the table feature, so a database assembled in the
    order the chain was built to run stops here — and it is the one whose repair
    is an operation rather than a value.
    """
    create_schema(mechanism_database_url, NODE_MIGRATION)
    return mechanism_database_url


@pytest.fixture
def mechanism_store(mechanism_database: str) -> MechanismStore:
    """Feature 211's store, over the chain-built tree.

    Built directly rather than reached off a composed application, the same
    discipline ``law``, ``gate`` and ``territory`` follow: a test of the *store*
    should not depend on the factory having scanned anything, and the component
    tests reach the composed law separately.
    """
    return MechanismStore(mechanism_database)


@pytest.fixture
def mechanism(mechanism_database: str) -> StatedMechanism:
    """Feature 211's law, composed over the chain-built tree.

    The law *and* its store in one handle, which is the shape the composed
    component has — so a test that exercises the barrier through the law is
    exercising the same object a deployment hands its caller.  A test that wants
    the store-less law builds :class:`~signal_agent.StatedMechanism` with no
    argument, and one that wants the store without the barrier asks
    :func:`mechanism_store` above; the three seams are separate on purpose.
    """
    return stated_mechanism({"DATABASE_URL": mechanism_database})
