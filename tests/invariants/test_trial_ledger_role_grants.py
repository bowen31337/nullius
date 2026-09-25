"""System rejects the merge when a role holding UPDATE or DELETE on
trial_ledger exists.

app_spec.xml feature 361 — the "System Invariant CI Gates" category's
ledger gate — is the merge-time form of two runtime contracts the ledger
category already states. Feature 92: *"System rejects any UPDATE or DELETE
against trial_ledger, enforced by role grants rather than by application
convention."* Feature 103: *"System creates the trial_ledger table with a
bigserial primary key and role grants that deny UPDATE and DELETE."*
docs/nullius-tech-architecture.md §8 states the whole thing as one DDL
comment: ``-- No UPDATE, no DELETE. Enforced by role grants.`` And §2's
trust-zone table seats the ledger in Z0 with an enforcement column that
names the CI as one of its instruments ("Read-only mounts; separate IAM
role; append-only ledger; CI hash check") — the gates in this category are
that column. The runtime faces refuse the *mutation*: the guarded
connection (``ledger.store``) refuses an UPDATE or DELETE statement before
it runs, and the production database's own privilege check refuses it to a
role that was never granted the verb. This gate refuses the *grant* — the
merge that would ship some role its permission to restate a charge is
rejected before any DDL runs, which is the only moment the refusal is
free. After the grant lands, the best the runtime faces can do is watch
each mutation they permit.

**The subject is the grant state the DDL leaves, not the words it
uses.** A merge carries DDL, and migration 0112 returns its DDL as
inspectable data — its public ``statements()``, "the property that makes a
migration reviewable at all". The
gate evaluates those statements the way Postgres evaluates them: ``CREATE
ROLE`` introduces a role holding nothing, ``GRANT`` adds privileges to a
role, ``REVOKE`` takes them away, ``TO PUBLIC`` is a grant to every role,
and ``GRANT ALL`` folds to all seven table privileges. When the last
statement has finished, if any role holds ``UPDATE`` or ``DELETE`` on
``trial_ledger``, the merge is refused. State, not text — which is why a
``GRANT ALL ON trial_ledger TO r`` is refused though it names neither
verb, and a grant undone by its revoke stands though both words appear.
That is also why the checker here is a small evaluator rather than a grep:
a gate that grepped for the verbs could be defeated by every synonym the
grammar offers, and one that grepped *against* them could be defeated by
an ``ALL``.

**Why the CI column and not only the database.** The ledger is §8's
"honest ``K`` counter": ``K_effective`` per epoch, the epoch-usage budget
and the deflation term's ``β₃`` inputs all read this table, and a role
able to UPDATE or DELETE it can restate a charge after the fact — every
number derived downstream silently becomes rewritable history, which is
exactly the undetectable fiction the append-only shape exists to make
impossible. Those grants ship in merges, so the refusal belongs at merge
time: :func:`grant_state` never opens a connection (pinned statically
below), because a gate that had to run the DDL to judge it would be an
audit after the fact, and a restated charge is the one failure §8 refuses
to unwind.

**What this gate is not, asserted as hard as what it is.** It is not the
runtime wall — that is feature 92's guarded seam, the member suite's own
subject; this gate's refusal happens at merge time and names the grant,
not the statement. It is not a judgement on other tables: ``epoch_ledger``
is *meant* to be mutable (feature 294's writer re-supplies its served
counts by UPDATE), so a grant of UPDATE there is not this gate's refusal —
the scope is ``trial_ledger`` exactly as the spec sentence's is. It is not
a name check: the gate is on the privilege, not the identity, so renaming
``trial_ledger_writer`` defeats nothing and a foreign role holding UPDATE
is refused all the same. It does not refuse the append path's own grants
— ``SELECT`` to read the prior sequence on a retry and ``INSERT`` to
append (feature 95's livelihood); a merge that grants exactly those
stands. And the refusal is exactly the two named verbs: a role granted
``TRUNCATE`` alone is not refused *by this sentence* — 0112 revokes the
third verb anyway as its own belt-and-braces, which the stands class pins
as standing state rather than claiming it for the gate.

**The dialect split.** SQLite has no roles, no ``GRANT`` and no
``REVOKE`` — a role holding UPDATE on ``trial_ledger`` cannot exist there,
so the gate has no subject on that dialect and its branch of the DDL
carries no grants to read (pinned below: the SQLite statements are the
``CREATE TABLE`` alone). The gate therefore reads ``statements()`` with no
dialect argument — the spelling the production target receives, the one
dialect where a role can exist at all. On SQLite the append-only guarantee
is the guarded seam, a different face of feature 92 enforced by a
different mechanism, and this gate does not refuse a merge for SQLite's
inability to express a grant.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType

import pytest

# ── The schema's owner, loaded the way its runner loads it ───────────────────

#: tests/invariants/test_trial_ledger_role_grants.py → tests/invariants →
#: tests → the repository root, whose migrations/ tree holds the DDL this
#: gate judges.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The migration tree's versions directory — the one place a merge's DDL
#: lives. The gate reads it rather than a restatement, so a DDL edited in a
#: candidate merge is judged as it will ship, not as this file remembers it.
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The revision that owns the table and its role grants: 0112 is feature
#: 103's migration — the "System creates the trial_ledger table … and role
#: grants that deny UPDATE and DELETE" half of the contract this gate holds.
TRIAL_LEDGER_REVISION = "0112_trial_ledger"

#: The one table this gate is scoped to, in the spelling the spec sentence
#: and §8's DDL comment both use.
TRIAL_LEDGER_TABLE = "trial_ledger"

#: The two privileges whose presence on any role refuses the merge — the
#: feature-361 sentence's own words, and §8's "-- No UPDATE, no DELETE."
#: Kept uppercase because Postgres privilege names are; every comparison
#: below normalises to that case first.
ROW_MUTATING_PRIVILEGES: frozenset[str] = frozenset({"UPDATE", "DELETE"})


def _load_migration(revision: str) -> ModuleType:
    """Load ``revision`` from the versions directory, by path.

    ``migrations/`` is not a package and is not on ``sys.path``; a runner
    loads a migration by path the same way, so loading it by path here is
    the shape a migration is *built* to be used in rather than a
    workaround. A missing file fails with the path in the message, because
    the one failure a gate should never have to guess at is "the schema's
    owner moved" — a gate that silently skipped the DDL would pass for a
    merge that shipped anything.
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this gate judges the migration "
            "that owns trial_ledger's role grants, so it needs the schema's "
            "owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_invariants_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The migration that owns the table and its role grants, loaded once at
#: collection — reading it is a precondition of every judgement below, not
#: a behaviour any one test chooses.
MIGRATION = _load_migration(TRIAL_LEDGER_REVISION)


# ── The evaluator: grant statements → the state they leave ──────────────────

#: One SQL identifier, and the comma-separated lists of them that
#: ``GRANT``/``REVOKE`` spell for both privileges and roles.
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_$]*"
_LIST = rf"{_IDENTIFIER}(?:\s*,\s*{_IDENTIFIER})*"
_TABLE_NAME = rf"{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})?"

#: The three statement shapes that move a role's privileges. Each is
#: searched case-insensitively and whitespace-tolerantly within one
#: statement, because a grant the DDL carries is refused however it is
#: spelled — the same discipline the runtime wall (feature 92's
#: ``_immutability_violation``) applies to the statement itself.
_CREATE_ROLE = re.compile(rf"\bCREATE\s+ROLE\s+(?P<role>{_IDENTIFIER})", re.IGNORECASE)
_GRANT = re.compile(
    rf"\bGRANT\s+(?P<privileges>.+?)\s+ON\s+(?P<table>{_TABLE_NAME})"
    rf"\s+TO\s+(?P<roles>{_LIST})",
    re.IGNORECASE,
)
_REVOKE = re.compile(
    rf"\bREVOKE\s+(?P<privileges>.+?)\s+ON\s+(?P<table>{_TABLE_NAME})"
    rf"\s+FROM\s+(?P<roles>{_LIST})",
    re.IGNORECASE,
)

#: What ``GRANT ALL`` folds to on a table: every privilege Postgres knows
#: how to grant on one. This expansion is the reason the gate judges state
#: rather than text — ``ALL`` names neither refused verb and carries both.
ALL_TABLE_PRIVILEGES: frozenset[str] = frozenset(
    {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
    }
)


def _privileges_named(text: str) -> frozenset[str]:
    """The privileges a comma-separated ``GRANT``/``REVOKE`` list names.

    ``ALL`` and ``ALL PRIVILEGES`` expand to the full table set, exactly
    as Postgres resolves them; every other name is uppercased, the case
    privilege names are compared in.
    """
    expanded: set[str] = set()
    for name in (part.strip().upper() for part in text.split(",")):
        if name in {"ALL", "ALL PRIVILEGES"}:
            expanded |= ALL_TABLE_PRIVILEGES
        else:
            expanded.add(name)
    return frozenset(expanded)


def _roles_named(text: str) -> frozenset[str]:
    """The roles a comma-separated list names, in Postgres's own case.

    Unquoted identifiers fold to lowercase in Postgres, so ``Writer_Role``
    and ``writer_role`` are one role and the state keys them as one.
    ``PUBLIC`` is kept as its own key: a grant to PUBLIC is a grant to
    every role, which makes it the loudest way the collision can happen
    rather than a special case to miss.
    """
    return frozenset(role.strip().lower() for role in text.split(","))


def _names_ledger(table: str) -> bool:
    """Whether ``table`` — the ``ON`` target of a grant or revoke — is the
    ledger.

    Compares the table's own name in any schema, so a grant on
    ``public.trial_ledger`` cannot dodge the gate by qualifying. The
    comparison is the scope the spec sentence states: a grant on any other
    table is not this gate's refusal.
    """
    return table.rsplit(".", 1)[-1].strip().lower() == TRIAL_LEDGER_TABLE


def grant_state(statements: Iterable[str]) -> dict[str, frozenset[str]]:
    """The role → privileges state on ``trial_ledger`` the DDL leaves.

    Evaluates the GRANT/REVOKE/CREATE ROLE shapes the migration tree
    writes — comma-separated privilege and role lists, optionally
    schema-qualified table names, ``ALL [PRIVILEGES]`` — in Postgres's
    evaluation order: statements run in sequence, a GRANT adds to a role,
    a REVOKE removes from it, and the state that survives the last
    statement is the one the database would enforce. The shapes are the
    ones this workspace's DDL uses, not arbitrary SQL; the migration is
    the gate's whole subject, and it speaks this dialect.

    The state starts empty — the cluster's standing defaults (the owner's
    implicit rights, most notably) are not grants any DDL in this tree
    makes or can revoke, and Z0's "Human, via signed release only" governs
    them by other means. What the merge carries is what the merge can be
    refused for.
    """
    state: dict[str, set[str]] = {}
    for statement in statements:
        created = _CREATE_ROLE.search(statement)
        if created is not None:
            # A role is created holding nothing — existing is not the
            # collision; holding a refused verb is.
            state.setdefault(created["role"].lower(), set())
        granted = _GRANT.search(statement)
        if granted is not None and _names_ledger(granted["table"]):
            privileges = _privileges_named(granted["privileges"])
            for role in _roles_named(granted["roles"]):
                state.setdefault(role, set()).update(privileges)
        revoked = _REVOKE.search(statement)
        if revoked is not None and _names_ledger(revoked["table"]):
            privileges = _privileges_named(revoked["privileges"])
            for role in _roles_named(revoked["roles"]):
                state.get(role, set()).difference_update(privileges)
    return {role: frozenset(privileges) for role, privileges in state.items()}


def held_row_mutations(
    state: dict[str, frozenset[str]],
) -> tuple[tuple[str, str], ...]:
    """Every (role, privilege) collision the merge is refused for.

    Sorted, so the refusal is deterministic and names each colliding role
    beside the verb it holds — the operator-facing form of the refusal, the
    way feature 362's gate names both hashes. An empty result is a grant
    state no role holds a refused verb in.
    """
    return tuple(
        sorted(
            (role, privilege)
            for role, privileges in state.items()
            for privilege in privileges
            if privilege in ROW_MUTATING_PRIVILEGES
        )
    )


def merge_refusal(statements: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """The gate itself: collisions that refuse the merge over ``statements``.

    The merge-time form of features 92 and 103. Empty means the merge
    stands — no role holds UPDATE or DELETE on trial_ledger when the DDL
    has finished. Computed from the DDL as data, never by running it.
    """
    return held_row_mutations(grant_state(statements))


# ── The gate reads the grant state the merge carries ─────────────────────────


class TestTheGateReadsTheGrantStateTheMergeCarries:
    """The gate judges the DDL the migration ships, as data, without running
    it."""

    def test_the_gate_reads_the_migration_that_owns_the_table(self) -> None:
        # The gate reads the schema's own owner — the revision that creates
        # trial_ledger and its role grants — loaded by path the way a
        # runner loads it, never a restatement typed into this file. A gate
        # that re-typed the DDL it judged could agree with itself and pass
        # anything; this one fails the moment the owner moves or changes.
        assert MIGRATION.REVISION == TRIAL_LEDGER_REVISION
        assert MIGRATION.TABLES == (TRIAL_LEDGER_TABLE,)

    def test_the_ddl_the_gate_judges_carries_the_role_grants(self) -> None:
        # The statements under judgement are the statements that carry the
        # privilege model: a role creation, at least one GRANT and at least
        # one REVOKE. If the Postgres branch ever stopped carrying grants,
        # this fails before the gate can silently judge an empty subject.
        statements = MIGRATION.statements()
        assert any(_CREATE_ROLE.search(statement) for statement in statements)
        assert any(_GRANT.search(statement) for statement in statements)
        assert any(_REVOKE.search(statement) for statement in statements)

    def test_the_gate_judges_the_ddl_without_running_it(self) -> None:
        # A merge gate refuses the change before it ships; an evaluator
        # that had to run the DDL to judge it would be an audit after the
        # fact. A static check pins that: the evaluator's own source
        # touches nothing that could open, drive or settle a connection —
        # the same discipline feature 362's gate applies to its comparison
        # surface.
        tree = ast.parse(inspect.getsource(grant_state))
        database_names = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr
            in {"connect", "cursor", "execute", "executescript", "commit", "rollback"}
        ]
        assert database_names == []

    def test_the_sqlite_branch_carries_no_grants_and_has_no_subject(self) -> None:
        # SQLite has no roles, no GRANT and no REVOKE, so its branch of the
        # DDL is the CREATE TABLE alone — no grant to read, no role that
        # could hold anything, and the gate does not refuse. The append-only
        # guarantee on that dialect is the guarded seam, a different face
        # of feature 92 the member suite holds; refusing here would be
        # refusing a merge for a dialect's inability to express a grant.
        sqlite_statements = MIGRATION.statements("sqlite")
        assert not any(
            _CREATE_ROLE.search(statement)
            or _GRANT.search(statement)
            or _REVOKE.search(statement)
            for statement in sqlite_statements
        )
        assert merge_refusal(sqlite_statements) == ()


# ── A merge whose grants deny every mutation stands ──────────────────────────


class TestAMergeWhoseGrantsDenyEveryMutationStands:
    """The DDL as it ships leaves no role holding UPDATE or DELETE — the
    merge stands, and the append path keeps the two privileges it lives
    on."""

    def test_no_role_holds_update_or_delete_when_the_ddl_has_finished(self) -> None:
        # The gate's own happy path, stated as the gate states it: the
        # grant state the migration's Postgres DDL leaves contains no role
        # holding UPDATE or DELETE on trial_ledger, so the merge stands.
        assert merge_refusal(MIGRATION.statements()) == ()

    def test_the_writer_role_holds_exactly_the_append_path(self) -> None:
        # The role the application writes through ends the DDL holding
        # exactly the two privileges the append path needs — SELECT to read
        # the prior sequence on a retry (feature 95), INSERT to append —
        # and it is the only role holding anything. The stands case is not
        # "no grants at all": a ledger that could not append would pass a
        # stupider gate. Feature 92's sentence refuses UPDATE and DELETE,
        # never the table's livelihood.
        state = grant_state(MIGRATION.statements())
        writer = MIGRATION.ROLE.lower()
        assert state == {writer: frozenset({"SELECT", "INSERT"})}

    def test_the_row_mutating_verbs_are_revoked_by_name(self) -> None:
        # Feature 103's legibility half: the grants "deny UPDATE and
        # DELETE", said out loud. The state-based refusal above would pass
        # a lazy DDL that merely omitted the verbs — an ungranted privilege
        # is already denied — but the recorded contract says the denial, so
        # the merge must say it too; TRUNCATE rides along as 0112's own
        # belt-and-braces, revoked here though the gate's sentence names
        # only the two verbs.
        revokes = [
            (_privileges_named(match["privileges"]), _roles_named(match["roles"]))
            for match in (
                _REVOKE.search(statement) for statement in MIGRATION.statements()
            )
            if match is not None and _names_ledger(match["table"])
        ]
        assert revokes == [
            (
                frozenset({"UPDATE", "DELETE", "TRUNCATE"}),
                frozenset({MIGRATION.ROLE.lower()}),
            )
        ]

    def test_a_grant_undone_by_its_revoke_stands(self) -> None:
        # The state is final, not cumulative text. A DDL that grants both
        # refused verbs and then revokes them leaves no holder — both words
        # appear and the merge stands, because the database enforces the
        # state the last statement leaves, and so does the gate. This is
        # the mirror of the runtime wall's own rule: a refused statement
        # never ran, and an unheld grant never permits.
        ddl = (
            "CREATE ROLE bulk_backfill LOGIN",
            "GRANT SELECT, UPDATE, DELETE ON trial_ledger TO bulk_backfill",
            "REVOKE UPDATE, DELETE ON trial_ledger FROM bulk_backfill",
        )
        assert merge_refusal(ddl) == ()
        assert grant_state(ddl) == {"bulk_backfill": frozenset({"SELECT"})}


# ── A merge that leaves a role holding UPDATE or DELETE is refused ───────────


class TestAMergeThatLeavesARoleHoldingUpdateOrDeleteIsRefused:
    """Any role, any spelling, any order — the collision refuses the merge
    and the refusal names who holds what."""

    def test_a_grant_of_update_to_the_writer_role_is_refused(self) -> None:
        # The quiet drift: the migration's own DDL plus one grant to the
        # role it already writes through. Nothing about the writer makes
        # this safe — the role the app writes through is precisely the role
        # a bug would speak as — so the merge is refused.
        ddl = (
            *MIGRATION.statements(),
            f"GRANT UPDATE ON trial_ledger TO {MIGRATION.ROLE}",
        )
        assert ("trial_ledger_writer", "UPDATE") in merge_refusal(ddl)

    def test_a_grant_of_delete_to_any_other_role_is_refused(self) -> None:
        # The gate is on the privilege, not the identity: a role the
        # migration never mentions, granted DELETE, is the same collision.
        # A name check would have to enumerate the roles it distrusts, and
        # the sentence refuses the state, however the holder is called.
        ddl = (
            *MIGRATION.statements(),
            "GRANT DELETE ON trial_ledger TO nightly_maintenance",
        )
        assert merge_refusal(ddl) == (("nightly_maintenance", "DELETE"),)

    def test_a_grant_to_public_is_refused(self) -> None:
        # PUBLIC is every role at once — the loudest way the collision can
        # happen. The refusal names both held verbs beside the pseudo-role,
        # deterministically sorted, so the operator sees the whole shape of
        # the break and not one face of it.
        ddl = ("GRANT UPDATE, DELETE ON trial_ledger TO PUBLIC",)
        assert merge_refusal(ddl) == (("public", "DELETE"), ("public", "UPDATE"))

    def test_grant_all_privileges_is_refused_without_naming_either_verb(self) -> None:
        # The refusal is on the state, not the words: ``ALL PRIVILEGES``
        # names neither refused verb and carries both, so the merge is
        # refused. A gate that grepped the DDL for "UPDATE" and "DELETE"
        # would wave this through — the reason the checker is an evaluator.
        ddl = ("GRANT ALL PRIVILEGES ON trial_ledger TO helpful_admin",)
        assert merge_refusal(ddl) == (
            ("helpful_admin", "DELETE"),
            ("helpful_admin", "UPDATE"),
        )

    def test_the_migration_plus_one_hostile_grant_is_refused(self) -> None:
        # The load-bearing regression case: the gate catches a future edit
        # to the migration itself. A change to 0112 that grants UPDATE or
        # DELETE to any role — typo, "temporary" backfill, a copy-paste
        # from another table's grants — fails this gate at merge time,
        # before the DDL ever reaches a database.
        ddl = (*MIGRATION.statements(), "GRANT DELETE ON trial_ledger TO backfill_2027")
        assert merge_refusal(ddl) != ()

    def test_a_grant_after_its_revoke_is_refused(self) -> None:
        # Order matters, because Postgres applies statements in sequence: a
        # revoke followed by a later grant of the same verb leaves the role
        # holding it. The state is the last statement's word, not the
        # first's — the mirror of the stands case above, and the reason the
        # evaluator cannot stop at the first REVOKE it sees.
        ddl = (
            "CREATE ROLE restatement LOGIN",
            "REVOKE UPDATE, DELETE ON trial_ledger FROM restatement",
            "GRANT UPDATE ON trial_ledger TO restatement",
        )
        assert merge_refusal(ddl) == (("restatement", "UPDATE"),)

    @pytest.mark.parametrize(
        ("statement", "role"),
        [
            (
                "grant\n\tupdate\n\tON trial_ledger TO operator_scripts",
                "operator_scripts",
            ),
            ("GRANT UPDATE ON TRIAL_LEDGER TO OPS", "ops"),
            ("\tGRANT  UPDATE  ON  trial_ledger  TO  ops  ", "ops"),
            ("GRANT UPDATE ON public.trial_ledger TO ops", "ops"),
        ],
    )
    def test_case_whitespace_and_schema_do_not_hide_the_grant(
        self, statement: str, role: str
    ) -> None:
        # A grant the DDL carries is refused however it is spelled —
        # lowercased verbs and role names, padding and newlines, a
        # schema-qualified table name — the same discipline the runtime
        # wall applies to the statement it refuses. Each shape resolves to
        # one collision, and the folded role name is the one Postgres
        # would key the grant under.
        assert merge_refusal((statement,)) == ((role, "UPDATE"),)


# ── The refusal is scoped to the ledger and nothing else ─────────────────────


class TestTheRefusalIsScopedToTheLedgerAndNothingElse:
    """The gate refuses exactly the sentence's collision: the two verbs, on
    this table, held — never a role's existence, another table's
    mutability, or the append path's own grants."""

    def test_a_grant_of_update_on_another_table_is_not_this_gates_refusal(
        self,
    ) -> None:
        # The scope is trial_ledger, exactly as the sentence's is. Another
        # table's writer may hold UPDATE: epoch_ledger is meant to be
        # mutable — feature 294's writer re-supplies its served counts by
        # UPDATE — so a grant there is not this gate's refusal, however
        # much the verb resembles the refused one.
        ddl = ("GRANT UPDATE, DELETE ON epoch_ledger TO rotation",)
        assert merge_refusal(ddl) == ()

    def test_read_and_append_grants_are_not_refused(self) -> None:
        # The append path's livelihood: SELECT to read the prior sequence
        # on a retry, INSERT to append (feature 95), granted here to a role
        # the migration never mentions. The gate refuses the row-mutating
        # pair, never the ledger's ability to charge.
        ddl = ("GRANT SELECT, INSERT ON trial_ledger TO replay_reader",)
        assert merge_refusal(ddl) == ()

    def test_a_role_that_exists_with_no_grants_holds_nothing(self) -> None:
        # The collision is holding, not existing: a freshly created role —
        # an auditor, say, created so its grants can be enumerated by other
        # tooling — enters the state holding nothing, and the merge stands.
        # A gate that refused roles for existing would refuse every DDL
        # that prepares one, which is not the sentence it enforces.
        ddl = ("CREATE ROLE auditor LOGIN",)
        assert grant_state(ddl) == {"auditor": frozenset()}
        assert merge_refusal(ddl) == ()

    def test_the_other_table_privileges_are_not_row_mutations(self) -> None:
        # The sentence names UPDATE or DELETE, and the gate is exactly
        # those two: REFERENCES, TRIGGER and TRUNCATE on this very table do
        # not fire it. TRUNCATE's own revocation is 0112's belt-and-braces,
        # pinned in the stands class as standing state — not claimed here
        # as this gate's refusal, because the sentence does not grant it.
        ddl = ("GRANT REFERENCES, TRIGGER, TRUNCATE ON trial_ledger TO maintenance",)
        assert merge_refusal(ddl) == ()
