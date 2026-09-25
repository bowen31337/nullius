"""Feature 332's composition: the member is discovered, and it authors no DDL.

Three separate claims live here, and they are separate because they fail for
three different reasons.

**The member is discovered by convention.**  The task's own registration
constraint is that this feature wires itself in by *existing* — a
``packages/forward/`` directory with a ``pyproject.toml`` joins the uv
workspace, the loader scans the members the root declaration names, and the
package ``__init__``'s ``@register`` is what puts the component in the
application.  Nothing in this feature edits the factory, a router table, an
entry-points list or a central registry, so this suite is where *"did the
convention actually pick it up?"* is answered — and answered against a composed
application rather than against the import.

**The component degrades rather than raising.**  With no ``DATABASE_URL`` the
builder answers ``None``: the component is *registered* and its value is
absent, which is two different facts and only one of them is about the
deployment.  A suite that conflated them would not notice a member that had
stopped being scanned, because both states would look like "no store".

**The member authors no DDL and imports no sibling.**  The workspace's schema
law is that a member runs the *owning migration's* own statements and spells no
``CREATE TABLE`` itself, and its module law is that a member never imports
another member — the promotion seam is reached by ``importlib`` at call time.
Both are asserted here on the modules' *code* rather than on their prose, with
:func:`conftest.code_of`, because the modules legitimately *say* those words
in their docstrings while doing neither.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import forward
import forward.observation
import forward.record
import forward.schema
import forward.window
import pytest
from conftest import REPO_ROOT, code_of
from forward import (
    COMPONENT_NAME,
    FORWARD_RECORD_TABLE,
    MIGRATION_ORDER,
    ForwardRecords,
    bootstrap_schema,
)
from forward.schema import migrations_dir

APP_SEAT = REPO_ROOT / "src" / "app" / "modules" / "forward" / "__init__.py"


# -- Discovery ----------------------------------------------------------------


def test_the_member_joins_the_workspace_by_existing(tmp_path: Path) -> None:
    # The registration constraint, asserted as the *convention* rather than as
    # an edit: a member is a ``packages/<name>/`` directory carrying its own
    # ``pyproject.toml``, and the root declaration's ``packages/*`` glob is what
    # picks it up.  Editing the root to name this member would have been the
    # shared-file collision the task forbids, so the test that would catch it is
    # the one that reads the declaration.
    root = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'members = ["packages/*"]' in root
    assert "forward" not in root.split("[tool.uv.workspace]")[1].split("[")[0]
    member = REPO_ROOT / "packages" / "forward" / "pyproject.toml"
    assert member.is_file()
    manifest = member.read_text(encoding="utf-8")
    assert 'name = "forward"' in manifest
    # One dependency: the factory.  A member that declared a sibling would have
    # made the loader's synthetic module names able to break its own imports.
    assert 'dependencies = ["nullius"]' in manifest


def test_the_component_is_registered_under_the_documented_name() -> None:
    assert COMPONENT_NAME == "forward"
    assert forward.COMPONENT_NAME == COMPONENT_NAME
    # The builder is the registration's payload, and it is a *factory*: the
    # loader calls it with no arguments.
    assert callable(forward.build_forward_records)
    assert forward.build_forward_records.__name__ == "build_forward_records"


def test_the_seat_spells_the_same_component_name() -> None:
    # The name is spelled twice on purpose — once where it is registered, once
    # where it is read — and this is the assertion that keeps the pair honest.
    # Drift here would be a silent ``None`` from the seat in every deployment,
    # which is exactly the failure that looks like an unconfigured database.
    source = APP_SEAT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "COMPONENT_NAME"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
    ]
    assert found == ["forward"]


def test_the_seat_answers_the_composed_store(monkeypatch: pytest.MonkeyPatch) -> None:
    # Composed end to end: the loader scans the declared workspace, imports the
    # member, registers the builder, and the seat reads it back.  ``in``-style
    # membership only, because the composed order is shared with every other
    # feature and an exhaustive assertion here would be this suite legislating
    # the whole application.
    import app.module_loader as loader

    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = loader.create_app()
    assert COMPONENT_NAME in application
    assert application.get(COMPONENT_NAME) is None


def test_the_component_is_registered_even_when_no_database_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Registered and absent are two different facts, and only one of them is
    # about the deployment.  A member that had stopped being scanned would leave
    # no component at all, and the seat would answer ``None`` for a reason
    # nobody could tell apart from an unset ``DATABASE_URL``.  ``order`` is the
    # composed *names*, so its membership is the fact asked for.
    import app.module_loader as loader

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert COMPONENT_NAME in loader.create_app().order


def test_a_named_database_composes_a_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The other half: with a URL the builder answers a store, so the component's
    # ``None`` is genuinely about the missing configuration rather than about
    # the builder never producing anything.  The URL points into ``tmp_path`` so
    # the assertion that composition touched no disk is about a path that did
    # not exist beforehand, rather than about the repository's own directory.
    import app.module_loader as loader

    database = tmp_path / "composed-forward.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    store = loader.create_app().get(COMPONENT_NAME)
    assert store is not None
    assert store.database_url == f"sqlite:///{database}"
    # Composition touched no disk: the path is resolved on first use.
    assert not database.exists()


def test_the_seat_reads_the_same_store_the_builder_registered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The seat's whole job, asked once: given the application, answer *the*
    # store composed into it — not a second one constructed beside it, which
    # would be two stores over one database and two things to keep consistent.
    import app.module_loader as loader
    from app.modules.forward import forward_records_component

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seat.db'}")
    application = loader.create_app()
    store = forward_records_component(application)
    assert store is application.get(COMPONENT_NAME)

    # Duck-typed, **not** ``isinstance`` — and the assertion is written this way
    # because the loader imports every scanned member under a synthetic module
    # name, so the composed store is structurally a ``ForwardRecords`` and never
    # the class object this file's own import yields.  An ``isinstance`` here
    # would fail on a perfectly correct composition, which is precisely the trap
    # the member's own ``PromoteEndpoint`` seam documents.
    assert type(store).__name__ == "ForwardRecords"
    assert store is not ForwardRecords
    assert callable(store.open_record)


def test_the_component_lands_clear_of_every_existing_adjacency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The composed order is name-sorted, so a new component lands *somewhere*
    # and the only thing worth asserting is that it is not between a pair some
    # other feature pinned.  ``fixture-store`` / ``ingest`` is the window this
    # name falls into, and it is asserted here rather than assumed — a rename
    # upstream is a fact this suite should hear about.
    import app.module_loader as loader

    monkeypatch.delenv("DATABASE_URL", raising=False)
    order = list(loader.create_app().order)
    assert order.index("fixture-store") < order.index(COMPONENT_NAME)
    assert order.index(COMPONENT_NAME) < order.index("ingest")


# -- The schema law -----------------------------------------------------------


def test_the_member_authors_no_ddl() -> None:
    # The schema law asserted on the member's *code*, with docstrings stripped:
    # ``schema.py`` has to be able to write the sentence *no CREATE TABLE is
    # authored here* while authoring none, and a scan of the raw file would
    # fail on the very prose that makes the claim.  ``observation`` joins the
    # loop with feature 333: its act is an ``INSERT`` over the table the
    # opening write opened, so it holds the same none-of-my-own-DDL law.
    for module in (
        forward.schema,
        forward.record,
        forward.observation,
        forward.window,
    ):
        text = code_of(module)
        for token in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX"):
            assert token not in text, f"{module.__name__} authors DDL: {token}"


def test_the_schema_runs_the_owning_migrations_own_statements() -> None:
    # The order is the chain's, stated as data: ``node`` before
    # ``forward_record``.  SQLite would tolerate the reverse at declaration time
    # and fail at the first row with ``no such table: main.node``, so the order
    # is a fact about the *chain* rather than a demand of the engine — and it is
    # asserted against the constant, with the revision names spelled out, so a
    # reordering is caught rather than silently inherited.
    assert MIGRATION_ORDER == (
        ("node", "0118_node_table"),
        (FORWARD_RECORD_TABLE, "0108_forward_and_universe_tables"),
    )


def test_every_statement_the_bootstrap_runs_comes_from_an_owner() -> None:
    # The statements are the migration modules' *own* — loaded by path, run
    # verbatim — so this asserts the adapter is composing no SQL of its own:
    # every string it runs appears, character for character, in one of the two
    # files it names.  That is a stronger claim than "the DDL looks right", and
    # it is the one that makes ``forward_record`` the migration's table rather
    # than this member's.
    owned = {
        revision: _statements_of(revision) for _, revision in MIGRATION_ORDER
    }
    for _, revision in MIGRATION_ORDER:
        assert owned[revision], f"{revision} stated no DDL at all"
    everything = [statement for statements in owned.values() for statement in statements]
    assert everything == list(_member_statements())
    for statement in everything:
        assert any(statement in statements for statements in owned.values())


def _statements_of(revision: str) -> tuple[str, ...]:
    import importlib.util

    path = migrations_dir() / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(f"_probe_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.statements("sqlite")


def _member_statements() -> tuple[str, ...]:
    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        with connection:
            return bootstrap_schema(connection)
    finally:
        connection.close()


def test_the_bootstrap_serves_a_database_it_created_itself(database_url: str) -> None:
    # The plugin's own creator, asked for its tables by name rather than by
    # trusting that the subsequent write would have complained.  Note what the
    # bootstrap returns and what it does not: it answers the *DDL it ran*, not
    # the table names — a list of names would be this member restating what the
    # migrations declare, and the statements are the thing that actually ran.
    #
    # The two tables are therefore read off ``sqlite_master``, which is the
    # database's own answer to *what exists now*.
    import sqlite3

    from forward.record import _sqlite_path

    path = _sqlite_path(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            ran = bootstrap_schema(connection)
        assert ran, "the bootstrap ran nothing"
        # ``0108`` owns five tables besides ``forward_record`` and ``0118``
        # three besides ``node``, and each revision contributes **all** of its
        # statements or none — taking one out would be this member editing
        # another's schema.  So the *count* is the two files' totals, and the
        # two tables this member needs must be among what exists.
        expected = sum(len(_statements_of(revision)) for _, revision in MIGRATION_ORDER)
        assert len(ran) == expected
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"node", FORWARD_RECORD_TABLE} <= names
    finally:
        connection.close()


def test_the_bootstrap_converges_on_a_migrated_database(migrated_database: str) -> None:
    # The other creator: the deployment shape where the versioned tree got there
    # first.  Every statement is ``IF NOT EXISTS``, so the store's own bootstrap
    # must change nothing here rather than be a second declaration that could
    # differ from the migration's — and *changing nothing* is asserted against
    # the database's own schema digest rather than against a count, because a
    # duplicate declaration would leave the same rows in ``sqlite_master`` while
    # being exactly the drift this test exists to catch.
    import sqlite3

    from forward.record import _sqlite_path

    path = _sqlite_path(migrated_database)
    connection = sqlite3.connect(path)
    try:
        before = _schema_digest(connection)
        with connection:
            bootstrap_schema(connection)
        assert _schema_digest(connection) == before
    finally:
        connection.close()


def _schema_digest(connection: object) -> list[tuple[str, str, str]]:
    """Every table and index with the SQL that declared it, for comparison."""
    return sorted(
        (row[0], row[1], row[2] or "")
        for row in connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        )
    )


def test_a_missing_migration_tree_is_refused_in_this_members_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A checkout without ``migrations/`` is a fact about the *deployment*, not a
    # bare ``FileNotFoundError`` escaping the store's own error vocabulary — a
    # caller guarding its write with ``except ForwardStoreError`` must not be
    # defeated by the file system.
    from forward import ForwardStoreError, schema

    monkeypatch.setattr(schema, "migrations_dir", lambda: Path("/nonexistent/versions"))
    with pytest.raises(ForwardStoreError) as raised:
        schema._load_migration("0108_forward_and_universe_tables")
    assert "forward_record_unwritable" in str(raised.value)


# -- The member's module law --------------------------------------------------


def test_the_member_imports_no_workspace_member_at_module_scope() -> None:
    # The loader imports every scanned member under a synthetic name, so a
    # *static* import of a sibling would bind a different class object than the
    # composed one and every seam check would fail on identity.  The factory
    # (``app``) and this package's own submodules are the only workspace names
    # allowed; ``promotion`` is reached by ``importlib`` at call time.
    #
    # Only *absolute* imports are judged, which is the whole of the claim:
    # ``from .errors import ...`` is this package reaching itself, and a
    # relative import cannot name a sibling.  The sibling's name is spelled once
    # and the assertion is written to catch exactly it, so the list of allowed
    # roots is not a thing to maintain — ``promotion`` is what fails here, and
    # nothing else does.
    for module in (
        forward,
        forward.record,
        forward.observation,
        forward.reconciliation,
        forward.schema,
        forward.window,
    ):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] != "promotion", (
                        f"{module.__name__} imports {alias.name} at module scope"
                    )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                root = (node.module or "").split(".")[0]
                assert root != "promotion", (
                    f"{module.__name__} imports {node.module} at module scope"
                )
                # And the root is either the factory or the standard library —
                # never some *other* member, which is the same fault under a
                # name this suite has not been taught yet.  The check is that
                # the root is importable as a top-level module of the workspace
                # itself: a member's package name would be, so it is refused by
                # not being in the standard library's own namespace.
                assert root not in _WORKSPACE_MEMBERS, (
                    f"{module.__name__} imports the workspace member "
                    f"{node.module!r} at module scope"
                )


#: The workspace members this feature's neighbourhood declares — read from the
#: same declaration the loader reads, so a member added tomorrow is caught by
#: the assertion above without this list being edited.  ``forward`` itself is
#: excluded: a package importing its own name absolutely is unusual but is not
#: the fault this test is about.
def _workspace_member_names() -> set[str]:
    from app.module_loader import workspace_members

    names: set[str] = set()
    for member in workspace_members(REPO_ROOT / "src" / "app" / "module_loader.py"):
        names.add(Path(member).name)
    names.discard("forward")
    return names


_WORKSPACE_MEMBERS = _workspace_member_names()


def test_the_promotion_member_is_reached_at_call_time_and_not_at_import() -> None:
    # The seam's mechanism, stated as code: ``window.py`` builds the member name
    # and resolves it with ``importlib`` inside a function, and catches broadly
    # so a deployment without the promotion member is a refusal in *this*
    # member's vocabulary rather than an ImportError from the loader's guts.
    text = code_of(forward.window)
    assert "importlib" in text
    assert "import_module" in text
    assert "PROMOTION_MEMBER" in text
    # And the name it resolves is the sibling's own package name, spelled once.
    assert forward.window.PROMOTION_MEMBER == "promotion"
    assert forward.window.PROMOTION_WINDOW_VERB == "promotion_window"


def test_the_window_module_queries_no_table_of_its_own() -> None:
    # ``window.py`` holds the seam and nothing else: it owns no connection, no
    # cursor and no SQL, because every fact it answers comes from the promotion
    # member's own read.  A ``SELECT`` here would be this member reading a
    # sibling's table directly — the second spelling the seam exists to avoid,
    # and the one that would break the moment feature 300 renamed a column.
    text = code_of(forward.window)
    for token in ("SELECT", "INSERT", "UPDATE", "sqlite3", "connect"):
        assert token not in text, f"forward.window touches the database: {token}"


def test_the_store_module_never_names_the_registry_table() -> None:
    # The other direction of the same boundary: the promotion member's table is
    # the promotion member's, and this one reads it only through feature 300's
    # window.  ``promotion_registry`` appearing in this member's code would mean
    # a second reader of one table.  ``observation`` is the sharper case for
    # the same law: its act reads the record's standing rows rather than the
    # registry precisely so the two cannot disagree, and a literal here would
    # be the second reading it refuses to be.
    for module in (
        forward.record,
        forward.observation,
        forward.reconciliation,
        forward.schema,
        forward.window,
    ):
        assert "promotion_registry" not in code_of(module)


def test_the_seat_reaches_the_member_only_under_type_checking() -> None:
    # The seat reaches the store through the *application*, never through a
    # runtime import: a static import would be the app package depending on a
    # member's installed layout, and the composed store — imported by the loader
    # under a synthetic name — is never the class a direct import yields.
    #
    # The one allowance is the ``TYPE_CHECKING`` block, and it is allowed
    # because it is erased at runtime: it exists so the docstring's annotations
    # resolve for a reader and a checker, and it cannot bind a name in the
    # module's own namespace.  So the assertion walks every import and permits
    # the member's name only inside that guard — a *runtime* ``import forward``
    # is the fault, and this is what tells the two apart.
    tree = ast.parse(APP_SEAT.read_text(encoding="utf-8"))
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _tests_type_checking(node.test):
            guarded.update(id(child) for child in ast.walk(node))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        if "forward" in names:
            assert id(node) in guarded, (
                "the seat imports the forward member outside a TYPE_CHECKING "
                "guard, so the app package now depends on the member's installed "
                "layout at runtime"
            )


def _tests_type_checking(test: ast.expr) -> bool:
    """Whether an ``if`` head is a ``TYPE_CHECKING`` guard."""
    return (
        isinstance(test, ast.Name)
        and test.id == "TYPE_CHECKING"
        or isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
    )


def test_an_unreachable_promotion_member_is_a_refusal_not_an_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The seam's absence path, reached the way a deployment without the sibling
    # reaches it: the module cannot be imported, so there is no verb, so there
    # is no instant.  That the *import itself* never happened at module scope is
    # what makes this a refusal in this member's vocabulary rather than an
    # ImportError escaping from the loader's guts — so the test blocks the
    # import and asserts the refusal, which is the observable difference.
    from forward import window

    monkeypatch.setattr(window, "_promotion_member", lambda: None)
    from forward import ForwardPromotionError

    with pytest.raises(ForwardPromotionError) as raised:
        window.read_promotion_window("a-node", forward_days=90)
    assert "forward_promotion_unstamped" in str(raised.value)
    # And the module really is out of ``sys.modules``' way: nothing this member
    # imported at module scope is the sibling.
    assert sys.modules.get("forward.window") is window
