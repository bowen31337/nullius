"""Feature 110's decision: ``is_null`` stays out of the tree store.

app_spec.xml, "Null Oracle & Planted Nulls", feature 110: *System keeps
is_null absent from the tree store entirely, which rejects any proposed node
column named is_null.*  This suite pins the three spellings of that one
decision and, harder, the properties that keep each of them from being a
guard in name only:

* **the comparison is SQLite's, not Python's.**  Column names are
  case-insensitive in SQLite — ``node.IS_NULL`` *is* ``node.is_null`` in
  every query — so the refusal is asserted over the uppercase and mixed-case
  spellings too, in the data review, in the DDL review and over the live
  store, where ``PRAGMA table_info`` answers with the declared spelling.
  A guard that refused only the lowercase name would be the convention
  §4.2 says the barrier must not be.

* **the comparison is exactly as wide as the sentence.**  ``is_null_``,
  ``not_is_null`` and ``null_fraction`` pass, because SQLite says those are
  *other* columns: the feature rejects a column *named is_null*, and a guard
  that widened itself to near-misses would refuse DDL no sentence here
  empowers it to.  The wider sweep — the bit visible anywhere outside the
  scorer package — is §4.2's and feature 354's.

* **the DDL review reads the repo's own proposals.**  Every column feature
  98–101 ships is an ``ALTER TABLE node ADD COLUMN`` statement its migration
  exposes as *data* — the convention's stated property, *"returned rather
  than executed so the DDL is inspectable"* — and the review is run over
  every migration the repository actually ships, so the extractor is pinned
  against the real UUID default (four levels of nested parentheses with
  commas inside them), the real comment style, and the real constraint
  clauses, not against a fixture that happens to share their shape.

* **the audit reads and never writes.**  A check must not mutate what it
  checks: the guard opens the store read-only (``mode=ro``), never creates
  the database file, never creates the ``node`` table, and leaves no journal
  behind — so a deployment can audit itself hourly without the audit leaving
  fingerprints, and a path that names nothing still names nothing after the
  audit has "run".

* **absence and uncheckability are different answers.**  A store with no
  ``node`` table holds no forbidden column — true, and answered.  A store
  that exists but will not open, or a URL nothing names, is *refused by
  name*, because a barrier that could not be checked must never read as one
  that holds.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from nulloracle import (
    DATABASE_URL_ENV,
    FORBIDDEN_COLUMN,
    NODE_TABLE,
    NULL_COLUMN,
    IsNullColumnError,
    KsGuardError,
    NullOracleError,
    SchemaAudit,
    TreeStoreGuard,
    audit_tree_store,
    node_columns_from_ddl,
    review_ddl,
    review_node_columns,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The lawful five feature 97 names, in the order the migration declares
#: them — the column list every node-bearing store in this member restates.
NODE_FIVE = ("id", "parent_id", "campaign_id", "theme_root", "depth")

#: A lawful node table's CREATE, in the shape the stores and the migration
#: use, with the constraint clauses (an inline key and a table-level one)
#: that the extractor must read past.
LAWFUL_CREATE = f"""
CREATE TABLE {NODE_TABLE} (
    id           UUID NOT NULL PRIMARY KEY,
    parent_id    UUID,
    campaign_id  UUID NOT NULL,
    theme_root   TEXT NOT NULL,
    depth        INT  NOT NULL
)
"""


# -- Helpers ---------------------------------------------------------------------


def _guard(tmp_path: Path, name: str = "tree.db") -> tuple[TreeStoreGuard, str, Path]:
    """A guard over a fresh SQLite location, with its URL and path."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return TreeStoreGuard(url), url, path


def _make_node_table(path: Path, create: str = LAWFUL_CREATE) -> None:
    """Create the node table directly, the way a migration runner would."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(create)


def _load_migration(path: Path) -> object:
    """A migration module loaded by path, the way its runner loads it.

    By path rather than by import because that is how a migration runner
    reaches these files — the same seam ``test_ksguard.py`` states for the
    campaign migration — and because the review must work over *data* a
    caller hands it, never over an import the caller could have skipped.
    """
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- The one decision: the data spelling ------------------------------------------


class TestTheColumnReview:
    def test_a_lawful_proposal_passes_and_canonicalizes(self) -> None:
        assert review_node_columns(["id", " parent_id ", "flip_depth"]) == (
            "id",
            "parent_id",
            "flip_depth",
        )

    def test_the_forbidden_column_is_refused_by_name(self) -> None:
        with pytest.raises(IsNullColumnError) as raised:
            review_node_columns(NODE_FIVE + ("is_null",))
        assert str(raised.value).startswith(f"{NULL_COLUMN}:")
        assert "'is_null'" in str(raised.value)
        assert FORBIDDEN_COLUMN == "is_null"

    def test_the_refusal_names_the_proposal_it_was_asked_about(self) -> None:
        with pytest.raises(IsNullColumnError) as raised:
            review_node_columns(["is_null"], source="0120_node_null_flag.py")
        assert "0120_node_null_flag.py" in str(raised.value)

    def test_the_uppercase_spelling_is_the_same_column(self) -> None:
        # SQLite column names are case-insensitive: node.IS_NULL answers to
        # node.is_null in every query, so the spellings are one column and
        # must be one refusal — the guard is over the column, not the string.
        with pytest.raises(IsNullColumnError) as raised:
            review_node_columns(NODE_FIVE + ("IS_NULL",))
        # The refusal names the spelling it caught, so an operator learns
        # which one to drop rather than hunting for a lowercase original
        # that does not exist.
        assert "'IS_NULL'" in str(raised.value)

    def test_the_mixed_case_spelling_is_the_same_column(self) -> None:
        with pytest.raises(IsNullColumnError):
            review_node_columns(["Is_Null"])

    def test_padding_does_not_hide_the_column(self) -> None:
        # The proposal is canonicalized first — the lawful test above pins
        # the stripping — so the refusal lands on the column, never on its
        # padding: a name that arrives wrapped in whitespace still names
        # the forbidden column.
        with pytest.raises(IsNullColumnError) as raised:
            review_node_columns([" is_null "])
        assert "'is_null'" in str(raised.value)

    def test_near_miss_names_are_other_columns_and_pass(self) -> None:
        # Exactly as wide as the sentence: SQLite says ``is_null_`` and
        # ``not_is_null`` name *other* columns, and the campaign's own
        # ``null_fraction`` (feature 117's column, φ) is lawful data, so a
        # guard that refused near-misses would refuse the schema the spec
        # itself spells.  The wider sweep over the bit's visibility is
        # §4.2's and feature 354's, not the tree store guard's.
        assert review_node_columns(
            ["is_null_", "not_is_null", "null_fraction", "xis_null", "flip_depth"]
        ) == ("is_null_", "not_is_null", "null_fraction", "xis_null", "flip_depth")

    def test_the_forbidden_column_is_refused_wherever_it_sits(self) -> None:
        with pytest.raises(IsNullColumnError):
            review_node_columns(("is_null",) + NODE_FIVE)

    def test_a_bare_string_is_not_a_column_list(self) -> None:
        with pytest.raises(KsGuardError):
            review_node_columns("is_null")

    def test_a_non_string_name_is_refused_as_a_store_contract_failure(self) -> None:
        with pytest.raises(KsGuardError):
            review_node_columns(["id", None])
        with pytest.raises(KsGuardError):
            review_node_columns(["id", 7])

    def test_a_non_iterable_proposal_is_refused(self) -> None:
        with pytest.raises(KsGuardError):
            review_node_columns(7)


# -- The one decision: the migration spelling --------------------------------------


class TestTheDdlExtraction:
    def test_a_create_table_proposes_its_column_list(self) -> None:
        assert node_columns_from_ddl((LAWFUL_CREATE,)) == NODE_FIVE

    def test_table_constraints_are_not_columns(self) -> None:
        extracted = node_columns_from_ddl(
            (f"""
            CREATE TABLE {NODE_TABLE} (
                id        UUID NOT NULL,
                parent_id UUID,
                CONSTRAINT node_parent FOREIGN KEY (parent_id) REFERENCES node(id),
                PRIMARY KEY (id),
                UNIQUE (id, parent_id),
                CHECK (depth >= 0)
            )
            """,)
        )
        assert extracted == ("id", "parent_id")

    def test_an_alter_table_proposes_its_added_column(self) -> None:
        assert node_columns_from_ddl(
            (f"ALTER TABLE {NODE_TABLE} ADD COLUMN flip_depth INT",)
        ) == ("flip_depth",)

    def test_the_bare_add_spelling_is_read_too(self) -> None:
        # Postgres allows ADD without COLUMN; a proposal may arrive in the
        # other dialect's clothes, and the column it names is the same.
        assert node_columns_from_ddl((f"ALTER TABLE {NODE_TABLE} ADD ic_mean REAL",)) == (
            "ic_mean",
        )

    def test_every_add_in_a_statement_is_read(self) -> None:
        extracted = node_columns_from_ddl(
            (f"ALTER TABLE {NODE_TABLE} ADD COLUMN a INT, ADD COLUMN b INT",)
        )
        assert extracted == ("a", "b")

    def test_an_add_constraint_is_not_a_column(self) -> None:
        assert (
            node_columns_from_ddl(
                (f"ALTER TABLE {NODE_TABLE} ADD CONSTRAINT pk PRIMARY KEY (id)",)
            )
            == ()
        )

    def test_line_comments_are_read_past(self) -> None:
        # Both the member's schemas and the migrations' statements() carry
        # their commentary as -- comments, sometimes between a keyword and
        # its operand; the extractor reads the DDL, not the prose.
        extracted = node_columns_from_ddl(
            (f"""
            -- feature 999: the null flag, which must never exist
            ALTER TABLE {NODE_TABLE}
            -- the column itself
            ADD COLUMN is_null BOOLEAN
            """,)
        )
        assert extracted == ("is_null",)

    def test_one_string_of_many_statements_takes_the_same_path(self) -> None:
        extracted = node_columns_from_ddl(
            f"CREATE TABLE other (x INT); {LAWFUL_CREATE}; "
            f"ALTER TABLE {NODE_TABLE} ADD COLUMN flip_depth INT;"
        )
        assert extracted == NODE_FIVE + ("flip_depth",)

    def test_the_keywords_are_matched_case_insensitively(self) -> None:
        assert node_columns_from_ddl(
            ("create table NODE (is_flag INT); alter TABLE node add column d INT",)
        ) == ("is_flag", "d")

    def test_quoted_identifiers_are_unquoted(self) -> None:
        extracted = node_columns_from_ddl(
            (f'CREATE TABLE "{NODE_TABLE}" ("is_null" BOOLEAN)',)
        )
        assert extracted == ("is_null",)

    def test_a_schema_qualified_table_name_still_names_the_table(self) -> None:
        assert node_columns_from_ddl((f"ALTER TABLE main.{NODE_TABLE} ADD COLUMN x INT",)) == (
            "x",
        )

    def test_statements_about_other_tables_are_skipped_by_name(self) -> None:
        # The boundary the module states: the guard answers for the node
        # table alone.  An is_null column elsewhere in the store is a real
        # leak, but it is §4.2's and feature 354's to police — a guard that
        # silently widened itself over every table would refuse DDL no
        # sentence here empowers it to.
        extracted = node_columns_from_ddl(
            ("ALTER TABLE campaign ADD COLUMN is_null BOOLEAN",)
        )
        assert extracted == ()

    def test_a_drop_column_proposes_nothing(self) -> None:
        # A DROP COLUMN is_null removes the offender rather than proposing
        # it — the remedy the audit's own refusal message prescribes — so
        # the extractor reads no column from it and the review lets it pass.
        assert (
            node_columns_from_ddl((f"ALTER TABLE {NODE_TABLE} DROP COLUMN is_null",))
            == ()
        )

    def test_a_rename_proposes_nothing(self) -> None:
        assert (
            node_columns_from_ddl((f"ALTER TABLE {NODE_TABLE} RENAME TO tree",)) == ()
        )

    def test_an_unbalanced_body_is_declined_rather_than_guessed_at(self) -> None:
        assert node_columns_from_ddl((f"CREATE TABLE {NODE_TABLE} (id INT",)) == ()

    def test_unrecognised_ddl_proposes_nothing(self) -> None:
        assert node_columns_from_ddl(("CREATE INDEX node_campaign ON node (campaign_id)",)) == ()
        assert node_columns_from_ddl(("GRANT SELECT ON node TO nobody",)) == ()

    def test_bytes_are_not_statements(self) -> None:
        with pytest.raises(KsGuardError):
            node_columns_from_ddl(b"ALTER TABLE node ADD COLUMN x INT")

    def test_a_non_string_statement_is_refused(self) -> None:
        with pytest.raises(KsGuardError):
            node_columns_from_ddl((f"ALTER TABLE {NODE_TABLE} ADD COLUMN x INT", 7))


class TestTheDdlReview:
    def test_a_lawful_migration_passes(self) -> None:
        extracted = review_ddl((LAWFUL_CREATE,))
        assert extracted == NODE_FIVE

    def test_a_create_table_naming_the_column_is_refused(self) -> None:
        with pytest.raises(IsNullColumnError) as raised:
            review_ddl((f"CREATE TABLE {NODE_TABLE} (id UUID, is_null BOOLEAN)",))
        assert str(raised.value).startswith(f"{NULL_COLUMN}:")

    def test_an_alter_table_naming_the_column_is_refused(self) -> None:
        # The shape features 98-101 ship — the exact statement a column
        # migration is made of, arriving with the forbidden name on it.
        with pytest.raises(IsNullColumnError):
            review_ddl(
                (f"ALTER TABLE {NODE_TABLE} ADD COLUMN is_null BOOLEAN NOT NULL DEFAULT 0",)
            )

    def test_the_refusal_names_the_migration_it_came_from(self) -> None:
        with pytest.raises(IsNullColumnError) as raised:
            review_ddl(
                (f"ALTER TABLE {NODE_TABLE} ADD COLUMN is_null BOOLEAN",),
                source="0120_node_null_flag.py",
            )
        assert "0120_node_null_flag.py" in str(raised.value)

    def test_the_uppercase_spelling_is_refused_with_its_own_name(self) -> None:
        with pytest.raises(IsNullColumnError) as raised:
            review_ddl((f"ALTER TABLE {NODE_TABLE} ADD COLUMN IS_NULL BOOLEAN",))
        assert "'IS_NULL'" in str(raised.value)

    def test_the_dodged_spelling_is_refused_with_its_own_name(self) -> None:
        # The sneaky one: padding a DDL identifier is not possible the way it
        # is in a name list, but the quoted spelling with padding inside the
        # quotes is — and the refusal names what was declared.
        with pytest.raises(IsNullColumnError):
            review_ddl((f'ALTER TABLE {NODE_TABLE} ADD COLUMN " is_null " BOOLEAN',))


class TestTheRepositoriesOwnMigrations:
    """The review over every migration the repository actually ships.

    Feature 110's sentence is about *proposals*, and in this workspace a
    column proposal arrives as a migration's ``statements("sqlite")`` —
    data, returned rather than executed.  Running the review over all of
    them pins the extractor against the real DDL (the four-level UUID
    default with commas inside it, the comment style, the constraint
    clauses) rather than a fixture shaped like it, and stands as the
    CI-grade statement of the feature: no shipped migration proposes the
    forbidden column.
    """

    @staticmethod
    def _shipped_statements() -> list[tuple[str, tuple[str, ...]]]:
        shipped = []
        for path in sorted(MIGRATIONS_DIR.glob("*.py")):
            module = _load_migration(path)
            statements = getattr(module, "statements", None)
            if statements is None:
                continue
            shipped.append((path.name, statements("sqlite")))
        assert shipped, "no migrations found to review"
        return shipped

    def test_every_shipped_migration_passes_the_review(self) -> None:
        for name, statements in self._shipped_statements():
            # source names the migration so a future refusal names its file.
            review_ddl(statements, source=name)

    def test_the_extractor_finds_the_shipped_node_columns(self) -> None:
        # Guard against a vacuous pass: an extractor that recognised nothing
        # would refuse nothing, so pin that it really read the node columns
        # the tree's migrations declare — five from the table (feature 97)
        # and sixteen from the column trios and metrics (features 98-101).
        found: set[str] = set()
        for _name, statements in self._shipped_statements():
            found.update(node_columns_from_ddl(statements))
        assert set(NODE_FIVE) <= found
        assert {
            "ic_mean",
            "ic_tstat",
            "ir_standalone",
            "ir_marginal",
            "turnover",
            "cost_adjusted_ir",
            "perturb_stability",
            "code_hash",
            "stated_mechanism",
            "artifact_uri",
            "evaluator_hash",
            "snapshot_hash",
            "cost_model_hash",
            "agent_model_id",
            "agent_ckpt_hash",
            "agent_sampling",
        } <= found

    def test_the_node_table_migration_declares_exactly_the_five(self) -> None:
        module = _load_migration(MIGRATIONS_DIR / "0118_node_table.py")
        assert node_columns_from_ddl(module.statements("sqlite")) == NODE_FIVE

    def test_the_metrics_migration_declares_exactly_its_seven(self) -> None:
        module = _load_migration(MIGRATIONS_DIR / "0114_node_metrics.py")
        extracted = node_columns_from_ddl(module.statements("sqlite"))
        assert set(extracted) == set(module.COLUMNS)  # type: ignore[attr-defined]
        assert len(extracted) == 7

    def test_a_doctored_migration_is_refused(self) -> None:
        module = _load_migration(MIGRATIONS_DIR / "0118_node_table.py")
        doctored = module.statements("sqlite") + (
            "ALTER TABLE node ADD COLUMN is_null BOOLEAN NOT NULL DEFAULT 0",
        )
        with pytest.raises(IsNullColumnError) as raised:
            review_ddl(doctored, source="0118_node_table.py (doctored)")
        assert "0118_node_table.py (doctored)" in str(raised.value)


# -- The one decision: the standing audit -----------------------------------------


class TestTheAuditRecord:
    def test_a_clean_record_holds_and_requires_to_itself(self) -> None:
        record = SchemaAudit(columns=NODE_FIVE)
        assert record.holds is True
        assert record.forbidden_columns == ()
        assert record.require() is record

    def test_a_broken_record_names_the_declared_spelling(self) -> None:
        record = SchemaAudit(columns=NODE_FIVE + ("IS_NULL",))
        assert record.holds is False
        assert record.forbidden_columns == ("IS_NULL",)
        with pytest.raises(IsNullColumnError) as raised:
            record.require()
        assert str(raised.value).startswith(f"{NULL_COLUMN}:")
        assert "'IS_NULL'" in str(raised.value)

    def test_the_payload_carries_the_verdict_with_it(self) -> None:
        record = SchemaAudit(columns=NODE_FIVE)
        assert record.to_payload() == {
            "table": NODE_TABLE,
            "columns": list(NODE_FIVE),
            "holds": True,
        }

    def test_a_record_carries_only_names(self) -> None:
        with pytest.raises(KsGuardError):
            SchemaAudit(columns=("id", None))
        with pytest.raises(KsGuardError):
            SchemaAudit(columns=("id", "  "))


class TestTheStandingAudit:
    def test_a_lawful_store_audits_clean(self, tmp_path: Path) -> None:
        guard, _url, path = _guard(tmp_path)
        _make_node_table(path)
        audit = guard.audit()
        assert audit.holds is True
        assert audit.columns == NODE_FIVE

    def test_a_column_added_out_of_band_is_refused(self, tmp_path: Path) -> None:
        # The path that skipped both reviews: a hand-run ALTER, a store
        # restored from an older deployment.  "Keeps absent" is a maintained
        # state, and this is the maintenance — the audit reads what the
        # store declares and refuses the one column it may not.
        guard, _url, path = _guard(tmp_path)
        _make_node_table(path)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                f"ALTER TABLE {NODE_TABLE} ADD COLUMN is_null BOOLEAN NOT NULL DEFAULT 0"
            )
        with pytest.raises(IsNullColumnError) as raised:
            guard.audit()
        assert str(raised.value).startswith(f"{NULL_COLUMN}:")
        assert "'is_null'" in str(raised.value)

    def test_the_uppercase_column_is_the_same_column_in_the_store(self, tmp_path: Path) -> None:
        guard, _url, path = _guard(tmp_path)
        _make_node_table(path)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(f"ALTER TABLE {NODE_TABLE} ADD COLUMN IS_NULL BOOLEAN")
        with pytest.raises(IsNullColumnError) as raised:
            guard.audit()
        # PRAGMA answers with the declared spelling; the refusal repeats it.
        assert "'IS_NULL'" in str(raised.value)

    def test_an_empty_table_with_the_column_is_still_refused(self, tmp_path: Path) -> None:
        # The audit is over the schema, never the rows: the column is the
        # violation, with no data in it or otherwise.  §7.1's rule is about
        # what the table declares, not what any row happens to hold.
        guard, _url, path = _guard(tmp_path)
        _make_node_table(
            path,
            create=f"CREATE TABLE {NODE_TABLE} (id UUID, is_null BOOLEAN)",
        )
        with pytest.raises(IsNullColumnError):
            guard.audit()

    def test_the_audit_never_creates_the_database(self, tmp_path: Path) -> None:
        guard, _url, path = _guard(tmp_path)
        assert guard.audit() == SchemaAudit(columns=())
        assert not path.exists()

    def test_the_audit_never_creates_the_node_table(self, tmp_path: Path) -> None:
        # An existing database with no node table yet — the audit must not
        # build the schema it audits, or it would bless a store it just made.
        guard, _url, path = _guard(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(path).close()
        audit = guard.audit()
        assert audit.columns == ()
        assert audit.holds is True
        with closing(sqlite3.connect(path)) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        assert tables == []

    def test_the_audit_leaves_no_journal_behind(self, tmp_path: Path) -> None:
        guard, _url, path = _guard(tmp_path)
        _make_node_table(path)
        guard.audit()
        guard.audit()  # idempotent: same answer twice, and still no writes
        assert not list(tmp_path.glob(f"{path.name}-journal"))
        assert not list(tmp_path.glob(f"{path.name}-wal"))

    def test_the_audit_reads_the_full_declaration(self, tmp_path: Path) -> None:
        # Every column the store declares is read — including the ones this
        # member's own stores add — so the audit is over the table as it
        # actually stands, not a remembered shape of it.
        guard, _url, path = _guard(tmp_path)
        _make_node_table(path)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(f"ALTER TABLE {NODE_TABLE} ADD COLUMN flip_depth INT")
        assert "flip_depth" in guard.columns()

    def test_construction_performs_no_io(self, tmp_path: Path) -> None:
        # The guard resolves its path on first use, so building one creates
        # nothing — not the database, not a journal beside it.  (tmp_path
        # also holds the conftest's lake directories; the assertion is on
        # the guard's own path, the only place it could have written.)
        _guard_obj, _url, path = _guard(tmp_path)
        assert not path.exists()
        assert not (tmp_path / f"{path.name}-journal").exists()

    def test_the_columns_read_is_available_on_its_own(self, tmp_path: Path) -> None:
        # The read and the refusal are two spellings: a caller may log the
        # declared columns without asserting on them (the audit's own
        # docstring says only the caller about to rely on the barrier needs
        # require()), and a broken store's columns stay readable for the
        # operator who is about to fix it.
        guard, _url, path = _guard(tmp_path)
        _make_node_table(
            path,
            create=f"CREATE TABLE {NODE_TABLE} (id UUID, is_null BOOLEAN)",
        )
        assert "is_null" in guard.columns()


class TestTheStoreContract:
    def test_resolution_reads_the_environment(self, tmp_path: Path) -> None:
        _guard_obj, url, _path = _guard(tmp_path)
        assert TreeStoreGuard.resolve({}) is None
        assert TreeStoreGuard.resolve({DATABASE_URL_ENV: "   "}) is None
        guard = TreeStoreGuard.resolve({DATABASE_URL_ENV: url})
        assert guard is not None and guard.database_url == url

    def test_an_unspeakable_scheme_is_refused_lazily(self, tmp_path: Path) -> None:
        # Construction never raises — the factory's builders must not — so
        # the URL is refused at first use, where a named error is right.
        guard = TreeStoreGuard("postgres:///tree")
        assert guard.database_url == "postgres:///tree"
        with pytest.raises(KsGuardError):
            guard.audit()

    def test_a_host_is_refused(self) -> None:
        with pytest.raises(KsGuardError):
            TreeStoreGuard("sqlite://elsewhere/tree.db").columns()

    def test_an_in_memory_store_is_refused(self) -> None:
        # An in-memory database dies with its connection: an audit of a
        # store that vanishes is a verdict nothing could replay.
        with pytest.raises(KsGuardError):
            TreeStoreGuard("sqlite:///:memory:").columns()

    def test_a_blank_url_is_refused_at_construction(self) -> None:
        with pytest.raises(KsGuardError):
            TreeStoreGuard("   ")


class TestTheModuleLevelSpelling:
    def test_it_audits_the_named_store(self, tmp_path: Path) -> None:
        _guard_obj, url, path = _guard(tmp_path)
        _make_node_table(path)
        assert audit_tree_store(database_url=url).holds is True

    def test_it_reads_the_environment_when_no_url_is_supplied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _guard_obj, url, path = _guard(tmp_path)
        _make_node_table(path)
        monkeypatch.setenv(DATABASE_URL_ENV, url)
        assert audit_tree_store().holds is True

    def test_nothing_naming_a_store_is_refused_by_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        with pytest.raises(KsGuardError) as raised:
            audit_tree_store()
        assert DATABASE_URL_ENV in str(raised.value)
        # The refusal says why in the feature's own terms: an audit that
        # quietly skipped itself is the exact silence this feature removes.
        assert "quietly skipped" in str(raised.value)


# -- The taxonomy ----------------------------------------------------------------


class TestTheErrorTaxonomy:
    def test_the_barrier_error_is_a_null_oracle_error(self) -> None:
        assert issubclass(IsNullColumnError, NullOracleError)

    def test_the_barrier_error_is_not_a_store_error(self) -> None:
        # The split the taxonomy states: a caller catching IsNullColumnError
        # is rejecting a schema; a caller catching KsGuardError is
        # investigating a row or a connection.  Conflating them would let
        # the one forbidden column be retried as a database hiccup.
        assert not issubclass(IsNullColumnError, KsGuardError)
        assert not issubclass(KsGuardError, IsNullColumnError)

    def test_every_barrier_message_begins_with_the_code(self) -> None:
        from nulloracle.schemaguard import _presence_refusal, _proposal_refusal

        assert _proposal_refusal(["is_null"], None).startswith(f"{NULL_COLUMN}:")
        assert _presence_refusal(["is_null"]).startswith(f"{NULL_COLUMN}:")

    def test_the_code_is_the_offenders_own_name(self) -> None:
        assert NULL_COLUMN == "is_null_column"
