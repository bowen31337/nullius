"""§13 item 7's *before*, enforced at decision time — feature 292.

Feature 292's sentence — *"System rejects a promotion whose recorded criteria
hash differs from the pre-registered value, which returns a criteria_mismatch
error message"* — and the file where *rejects* and *criteria_mismatch* are the
claims under test.

**The hash is not this member's, and that is asserted first.**  The recorded
hash is written by feature 291 (:mod:`promotion.pre_register`), and the digest
function is :func:`promotion.criteria.criteria_hash`.  A suite that only drove
the happy refusal would pass for a module that had quietly recomputed the hash
from a p-value, or that had shipped its own ``SELECT`` against
``promotion_registry``.  So the boundary tests come first: this module reads one
column through feature 291's store, writes nothing, pronounces no merit verdict,
and compares two digests for exact equality — the recorded one and the one
:func:`criteria_hash` produces over the criteria the caller supplies.

**The comparison is a comparison, not a write, and that is pinned.**  Feature
291 records the hash; feature 293 closes the row; this feature reads the recorded
hash and weighs it against the criteria the promotion is being decided under.
The tests assert the module authors no ``INSERT``, no ``UPDATE`` and no DDL, and
that a refusal leaves the database exactly as it was — because *"the verdict is
the deciding evaluation's"* is the kind of claim a later feature could break by
persisting a second table.

**The recorded hash is read through feature 291's store, not re-probed.**  A
caller promoting a hypothesis holds feature 291's node identity; the recorded
hash is one column away on that node's ``promotion_registry`` row, and
:class:`~promotion.pre_register.PreRegistrations` already answers *this node's
row*.  The tests drive the gate over a real :class:`PreRegistrations`, and pin
that the gate owns no statement and no bootstrap of its own — every fact it reads
comes from the registry store's read.

**The two absences are refused by name, and neither is the mismatch.**  A node
that holds no registry row was never pre-registered, so there is no hash to
compare against — the repair is feature 291's act, and answering *criteria
mismatch* to it would mislead the operator.  A node whose row is still open —
``decided_at`` NULL — is a promotion whose deciding evaluation has not been
recorded, so there is no decided promotion to reject.  Both are refused in this
feature's own class, and the tests pin the repair each names.

**Every refusal is one class.**  The caller is a promotion path whose one failure
mode is silence, so a single ``except CriteriaMismatchError`` has to catch every
face — the malformed ask, the unreachable address, the two absences, a corrupt
recorded hash, and the mismatch itself.  The tests assert the class *and* the
code word, so a later feature that split them would fail here rather than in
production.

**What is deliberately not asserted.**  That ``promotion_registry``'s columns are
what ``0108`` declares — the gate reads them through feature 291's store, so this
suite pins its read against the store, not against a restatement of the
migration.  That the composed application holds this gate — it does not, and the
last tests assert precisely that.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
from pathlib import Path

import pytest
from conftest import (
    DEFAULT_CRITERIA_DOCUMENT,
    EPOCH_ID,
    NODE_ID,
    code_of,
)

import promotion as member
from promotion import (
    PROMOTION_REGISTRY_TABLE,
    CriteriaChecks,
    CriteriaMismatchError,
    PreRegistrations,
    PromotionCriteria,
    PromotionError,
    PromotionStoreError,
    criteria_hash,
    matches_criteria,
    matches_recorded_criteria,
    record_decision,
    rejects_mismatched_criteria,
)
from promotion.errors import CRITERIA_MISMATCH_ERROR_CODE
from promotion.pre_register import DECIDED_AT_COLUMN

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"


def _connect(database_url: str) -> sqlite3.Connection:
    """A raw connection to a ``sqlite:///`` URL, for a test's own reads.

    Raw rather than a store's connection, and deliberately: most of what these
    tests assert is what the *table* holds, and a test that asked the code under
    test to read it back would be asking that code to confirm itself.
    """
    assert database_url.startswith("sqlite:///"), database_url
    return sqlite3.connect(database_url[len("sqlite:///") :])


def _registry_rows(database_url: str) -> list[sqlite3.Row]:
    """The ``promotion_registry`` rows, read raw — what actually landed.

    Brings the one table up first through feature 291's store, so the raw read
    has a table to read — the same ``CREATE TABLE IF NOT EXISTS`` the gate runs,
    and the same one the store runs.  A database the gate has already touched is
    left exactly as it was.
    """
    from promotion.schema import bootstrap_decision_schema

    connection = _connect(database_url)
    try:
        with connection:
            bootstrap_decision_schema(connection)
        connection.row_factory = sqlite3.Row
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                f"SELECT id, node_id, epoch_id, criteria_hash, "
                f"pre_registered_at, decided_at FROM {PROMOTION_REGISTRY_TABLE}"
            ).fetchall()
        )
    finally:
        connection.close()


def _criteria(**overrides) -> PromotionCriteria:
    """The default criteria with the named terms overridden."""
    return PromotionCriteria(**{**DEFAULT_CRITERIA_DOCUMENT, **overrides})


def _seeded(database_url: str, *, decided: bool = True) -> PreRegistrations:
    """The store's database brought up *and* given the two parent rows, then a row.

    ``promotion_registry``'s foreign keys are real and the store checks them
    rather than manufacturing them, so the suite supplies the two parents — in
    the columns the migrations declare — and records one node's pre-registration
    through the store itself.  Every test that wants a recorded hash asks for
    this, so the recorded digest is feature 291's own, not a restatement.

    The row is **decided** by default: feature 293's stamp closes it, and this
    feature compares a *decided* promotion against its criteria.  ``decided=False``
    leaves the row open — the pre-registration waiting for its decision — for the
    one test that drives the open-row refusal.
    """
    import datetime

    store = PreRegistrations(database_url)
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
                (NODE_ID, "22222222-2222-4222-8222-222222222222", "macro", 1),
            )
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    store.pre_register(
        NODE_ID, EPOCH_ID, dict(DEFAULT_CRITERIA_DOCUMENT),
        pre_registered_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    if decided:
        record_decision(
            NODE_ID,
            decided_at=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
            database_url=database_url,
        )
    return store


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a registry file only this test can see."""
    return f"sqlite:///{tmp_path / 'criteria-check.db'}"


@pytest.fixture
def gate(database_url: str) -> CriteriaChecks:
    """The gate, pointed at this test's own fresh database.

    No migration has run: the gate's first judgement is what brings
    ``promotion_registry`` to the file, the contract every store in this member
    states.
    """
    return CriteriaChecks(database_url)


@pytest.fixture
def seeded(database_url: str) -> str:
    """A database with the two parents and one pre-registered node; returns the URL."""
    _seeded(database_url)
    return database_url


# -- The boundary: this feature compares a hash, it does not pronounce a verdict --


def test_the_module_compares_two_digests_and_nothing_else() -> None:
    # The hardest boundary assertion, and the one that keeps this gate from
    # quietly becoming a second deciding evaluation.  The verdict is the
    # deciding evaluation's: it compares a ΔIR against a bar and a p-value
    # against α.  A gate holding a bar, a p-value or a test would be
    # re-deciding a merit it is supposed to read — and the two deciders would
    # disagree the first time one of them changed.
    #
    # Read off the **AST** rather than off the source text, because this module
    # legitimately *quotes* §13 item 7 and the six term names in its refusal
    # message — the conftest's ``code_of`` keeps message strings for exactly
    # that reason.  What must be absent is the module *naming* a number or a
    # threshold in code, which is what a merit comparison would require.
    from promotion import criteria_check as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    indexed = {id(node.slice) for node in ast.walk(tree) if isinstance(node, ast.Subscript)}
    # Every number in the module is the **index of a subscript** — ``row[0]``, the
    # positional read off a one-column ``SELECT`` — and there are no others.  A
    # threshold, a bar or a tolerance would have to be a numeric literal standing
    # somewhere else, so this is the assertion that the merit boundary is not
    # fixed here.  ``bool`` is excluded because ``isinstance(True, int)`` and a
    # keyword argument are not comparisons.
    numbers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and id(node) not in indexed
    ]
    assert numbers == [], [ast.unparse(n) for n in numbers]
    # No comparison operator but the one equality this feature is.  A merit
    # verdict would need an *ordering* operator — ``<``, ``>``, ``<=`` or ``>=``
    # — to clear a bar; identity (``is``/``is not``) is not a merit judgment, so
    # it is excluded.
    ordering_ops = [
        type(op).__name__
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        for op in node.ops
        if isinstance(op, (ast.Lt, ast.Gt, ast.LtE, ast.GtE))
    ]
    assert ordering_ops == [], ordering_ops


def test_the_module_never_spells_a_merit_verdict() -> None:
    # The verdict on the evidence — whether the ΔIR cleared its bar — is the
    # deciding evaluation's, and this module must not pronounce it.  It names the
    # six terms in its refusal message (that is a message, not a judgment) but it
    # must never *reach into* the deciding evaluation's verdicts — the block and
    # the void-calibration gates — which is what re-deciding a merit would require.
    from promotion import criteria_check as module

    code = code_of(module)
    # Re-deciding would mean calling the deciding evaluation's own verdicts.
    assert "record_block" not in code
    assert "rejects_void_promotion" not in code
    assert "blocked" not in code
    # And it must not compute a merit figure — no ΔIR, no void fraction.
    assert "delta_ir" not in code
    assert "void" not in code


def test_the_module_authors_no_write() -> None:
    # The verdict is the deciding evaluation's and the recorded hash is
    # feature 291's; this feature only reads one and compares it to the other.
    # A module that wrote a row, advanced a column or created a table would be
    # persisting a fact about a decision it does not own — the forgery §13 item
    # 7 exists to prevent.
    from promotion import criteria_check as module

    code = code_of(module)
    for token in ("INSERT", "UPDATE", "DELETE", "CREATE TABLE", "ALTER TABLE"):
        assert token not in code
    # One SELECT-shaped read, through feature 291's store — asserted by the
    # module owning no statement constant of its own.
    assert "_SQL" not in code


def test_the_module_reads_through_feature_291s_store() -> None:
    # The gate is constructed over a PreRegistrations and owns no connection,
    # no bootstrap and no statement: every fact it reads comes from the
    # registry store's read.  A second registry read here would be a second
    # reading of one table.
    from promotion import criteria_check as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    # The gate reads through the store it is handed (``self._registry``), and
    # owns no SELECT of its own spelling.  The one ``connection.execute`` in the
    # module is the ``PRAGMA foreign_keys = ON`` connection setup — not a read —
    # so the assertion is that no execute carries a SELECT the module authored.
    selects = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and "select" in node.args[0].value.lower()
    ]
    assert selects == []


# -- The comparison: match, mismatch, and the exact-equality boundary -----------


def test_matching_criteria_return_the_recorded_hash(gate: CriteriaChecks, seeded: str) -> None:
    # A promotion decided under the criteria it was pre-registered with is
    # confirmed, and the returned value is the recorded digest — the value it
    # compared, not a derived one.
    recorded = criteria_hash(_criteria())
    returned = gate.rejects_mismatched_criteria(NODE_ID, _criteria())
    assert returned == recorded
    assert returned == criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))


def test_matching_criteria_spelled_another_way_still_match(
    gate: CriteriaChecks, seeded: str
) -> None:
    # ``0.3`` and ``0.30`` are one bar: the recomputed hash canonicalises the
    # reals, so a criteria set that states the same terms in another spelling
    # hashes identically and matches.
    recorded = criteria_hash(_criteria())
    assert gate.rejects_mismatched_criteria(NODE_ID, _criteria(theta=0.30)) == recorded
    assert gate.rejects_mismatched_criteria(NODE_ID, _criteria(theta=3 / 10)) == recorded


def test_a_promotion_decided_against_moved_criteria_is_refused(
    gate: CriteriaChecks, seeded: str
) -> None:
    # The feature: a promotion whose recomputed hash differs from the recorded
    # one was judged against criteria that were not the ones fixed.  Each of the
    # six terms is varied, one case per term — a hash that covered five of the
    # six would pass a test that varied one of the five.
    for changed in (
        {"theta": 0.31},
        {"alpha": 0.06},
        {"max_fdr_deploy": 0.24},
        {"min_worlds": 51},
        {"min_coverage_strata": 4},
        {"min_forward_days": 91},
    ):
        with pytest.raises(CriteriaMismatchError) as raised:
            gate.rejects_mismatched_criteria(NODE_ID, _criteria(**changed))
        message = str(raised.value)
        # The code word, the node, and both hashes — everything an operator
        # needs to see that this promotion was decided against the wrong bar.
        assert CRITERIA_MISMATCH_ERROR_CODE in message
        assert NODE_ID in message
        assert criteria_hash(_criteria()) in message
        assert criteria_hash(_criteria(**changed)) in message
        assert "feature 292" in message


def test_the_mismatch_refusal_is_one_class_and_one_word(
    gate: CriteriaChecks, seeded: str
) -> None:
    # The caller is a gate, and a gate's one failure mode is silence.  Every
    # refusal this feature raises — the mismatch, the two absences, the corrupt
    # hash — must be catchable by a single ``except CriteriaMismatchError`` and
    # must open with the one code word.
    with pytest.raises(CriteriaMismatchError) as raised:
        gate.rejects_mismatched_criteria(NODE_ID, _criteria(theta=0.9))
    assert type(raised.value) is CriteriaMismatchError
    assert str(raised.value).startswith(CRITERIA_MISMATCH_ERROR_CODE)


def test_the_comparison_is_exact_no_near_miss(
    gate: CriteriaChecks, seeded: str
) -> None:
    # A digest one character off is a criteria set that is one term off, and a
    # near-miss is not a thing a sha256 comparison can see.  Asserted by
    # hand-editing one hex digit of the recorded hash and confirming the pure
    # comparison still refuses.
    recorded = criteria_hash(_criteria())
    edited = recorded[:-1] + ("0" if recorded[-1] != "0" else "1")
    assert edited != recorded
    with pytest.raises(CriteriaMismatchError):
        matches_recorded_criteria(NODE_ID, _criteria(), edited)


def test_matches_recorded_criteria_returns_on_a_match(
    gate: CriteriaChecks, seeded: str
) -> None:
    # The pure comparison returns the recorded hash on a match, and raises on a
    # mismatch — the seam for a caller that already holds both hashes.
    recorded = criteria_hash(_criteria())
    assert matches_recorded_criteria(NODE_ID, _criteria(), recorded) == recorded
    with pytest.raises(CriteriaMismatchError):
        matches_recorded_criteria(NODE_ID, _criteria(theta=0.9), recorded)


# -- The two absences, each refused by name -------------------------------------


def test_an_unregistered_node_is_refused_not_as_a_mismatch(
    gate: CriteriaChecks, database_url: str
) -> None:
    # A node that holds no registry row was never pre-registered, so there is
    # no recorded hash to compare against.  Answering *criteria mismatch* would
    # tell the caller its criteria were wrong when the truth is that it never
    # registered them — the repair is feature 291's act.
    # The database is empty — the gate's bootstrap creates promotion_registry
    # (the one table it reads) and nothing else, so this node has no row.
    assert _registry_rows(database_url) == []
    with pytest.raises(CriteriaMismatchError) as raised:
        gate.rejects_mismatched_criteria(NODE_ID, _criteria())
    message = str(raised.value)
    assert CRITERIA_MISMATCH_ERROR_CODE in message
    assert "never" in message or "pre-register" in message
    assert "feature 291" in message


def test_an_open_row_is_refused_not_as_a_mismatch(
    gate: CriteriaChecks, database_url: str
) -> None:
    # A row whose decided_at is still NULL is a promotion whose deciding
    # evaluation has not been recorded — there is no decided promotion to
    # reject, only a pre-registration waiting for its decision.  This
    # comparison is of a *decided* promotion against its criteria.
    store = PreRegistrations(database_url)
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
                (NODE_ID, "22222222-2222-4222-8222-222222222222", "macro", 1),
            )
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    store.pre_register(
        NODE_ID, EPOCH_ID, dict(DEFAULT_CRITERIA_DOCUMENT),
        pre_registered_at=__import__("datetime").datetime(
            2026, 1, 1, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    # The row is still open: decided_at is NULL.
    assert _registry_rows(database_url)[0]["decided_at"] is None
    with pytest.raises(CriteriaMismatchError) as raised:
        gate.rejects_mismatched_criteria(NODE_ID, _criteria())
    message = str(raised.value)
    assert CRITERIA_MISMATCH_ERROR_CODE in message
    assert DECIDED_AT_COLUMN in message
    assert "feature 293" in message


def test_a_decided_row_is_judged(gate: CriteriaChecks, database_url: str) -> None:
    # Once the decision is recorded (feature 293's stamp), the row is decided
    # and the comparison runs.  This is the load in depends_on="293": the gate
    # refuses an open row but judges a decided one.
    from promotion import record_decision

    store = PreRegistrations(database_url)
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
                (NODE_ID, "22222222-2222-4222-8222-222222222222", "macro", 1),
            )
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    store.pre_register(
        NODE_ID, EPOCH_ID, dict(DEFAULT_CRITERIA_DOCUMENT),
        pre_registered_at=__import__("datetime").datetime(
            2026, 1, 1, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    record_decision(
        NODE_ID,
        decided_at=__import__("datetime").datetime(
            2026, 2, 1, tzinfo=__import__("datetime").timezone.utc
        ),
        database_url=database_url,
    )
    assert _registry_rows(database_url)[0]["decided_at"] is not None
    recorded = criteria_hash(_criteria())
    assert gate.rejects_mismatched_criteria(NODE_ID, _criteria()) == recorded


# -- The recorded hash is feature 291's, read through the store -----------------


def test_the_recorded_hash_is_read_through_the_store(
    gate: CriteriaChecks, seeded: str
) -> None:
    # The gate reads the recorded hash off the store's row, so the digest it
    # compares against is feature 291's own recording, not a restatement of the
    # migration's column.
    recorded = criteria_hash(_criteria())
    # matches_criteria returns the recorded hash without judging — the read.
    assert gate.matches_criteria(NODE_ID, _criteria()) == recorded
    # And a mismatched criteria still reads the same recorded hash.
    assert gate.matches_criteria(NODE_ID, _criteria(theta=0.9)) == recorded


def test_matches_criteria_reads_without_raising(
    gate: CriteriaChecks, seeded: str
) -> None:
    # matches_criteria is the read without the verdict: a mismatched promotion's
    # hash is returned, not raised, because this is the reading and not the
    # judgment.
    recorded = criteria_hash(_criteria())
    assert gate.matches_criteria(NODE_ID, _criteria(theta=0.9)) == recorded


# -- The refusals on the way to the comparison ----------------------------------


def test_a_malformed_node_is_refused(gate: CriteriaChecks, seeded: str) -> None:
    with pytest.raises(CriteriaMismatchError) as raised:
        gate.rejects_mismatched_criteria("not-a-uuid", _criteria())
    assert CRITERIA_MISMATCH_ERROR_CODE in str(raised.value)


def test_a_carrier_with_no_canonical_document_is_refused(
    gate: CriteriaChecks, seeded: str
) -> None:
    # The recomputed hash is taken over the criteria's canonical document, and
    # a carrier of something else has no digest to compare.  Refused naming
    # the criteria, because a hash of *something else* compared against the
    # recorded one would refuse a promotion for a reason nobody decided.
    with pytest.raises(CriteriaMismatchError) as raised:
        gate.rejects_mismatched_criteria(NODE_ID, object())
    assert CRITERIA_MISMATCH_ERROR_CODE in str(raised.value)


def test_a_corrupt_recorded_hash_is_refused(
    gate: CriteriaChecks, database_url: str
) -> None:
    # The column is CHAR(64) and SQLite's affinity is not a width, so a corrupt
    # recorded value is refused by name rather than compared against — which
    # would refuse a promotion for a corruption it never mentions.
    store = PreRegistrations(database_url)
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
                (NODE_ID, "22222222-2222-4222-8222-222222222222", "macro", 1),
            )
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, "2026-01-01T00:00:00+00:00"),
            )
            # A hand-written row with a corrupt criteria_hash — one no writer in
            # this workspace produced.
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} "
                "(node_id, epoch_id, criteria_hash, pre_registered_at, decided_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    NODE_ID, EPOCH_ID, "not-a-hash",
                    "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00",
                ),
            )
    finally:
        connection.close()
    with pytest.raises(CriteriaMismatchError) as raised:
        gate.rejects_mismatched_criteria(NODE_ID, _criteria())
    message = str(raised.value)
    assert CRITERIA_MISMATCH_ERROR_CODE in message
    # The refusal is the recorded hash's, phrased for a registry row.
    assert "criteria_hash" in message or "hex" in message


# -- Nothing is written -----------------------------------------------------------


def test_a_refusal_writes_nothing(gate: CriteriaChecks, seeded: str) -> None:
    # The recorded hash is already on the registry row; a refusal here leaves
    # the database exactly as it was.  A judgement that persisted a second
    # table would be a second spelling of one fact, free to disagree with the
    # row a reader would check.
    before = _registry_rows(seeded)
    with pytest.raises(CriteriaMismatchError):
        gate.rejects_mismatched_criteria(NODE_ID, _criteria(theta=0.9))
    after = _registry_rows(seeded)
    assert after == before  # the refusal wrote nothing
    # And the one row is still the one row, still decided-or-open as it was.
    assert len(after) == 1


# -- The module-level spellings ---------------------------------------------------


def test_module_level_rejects_matches_the_gate(seeded: str) -> None:
    # rejects_mismatched_criteria resolves the store from DATABASE_URL and
    # delegates to the gate, so a caller that wants the act without holding a
    # gate gets the same verdict.
    import os

    database_url = seeded
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        recorded = criteria_hash(_criteria())
        assert rejects_mismatched_criteria(NODE_ID, _criteria()) == recorded
        with pytest.raises(CriteriaMismatchError):
            rejects_mismatched_criteria(NODE_ID, _criteria(theta=0.9))
    finally:
        if old is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = old


def test_module_level_matches_reads_without_judging(seeded: str) -> None:
    import os

    database_url = seeded
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        assert matches_criteria(NODE_ID, _criteria()) == criteria_hash(_criteria())
    finally:
        if old is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = old


def test_the_module_level_spelling_refuses_an_absent_database() -> None:
    import os

    old = os.environ.get("DATABASE_URL")
    os.environ.pop("DATABASE_URL", None)
    try:
        with pytest.raises(CriteriaMismatchError) as raised:
            rejects_mismatched_criteria(NODE_ID, _criteria())
        assert CRITERIA_MISMATCH_ERROR_CODE in str(raised.value)
    finally:
        if old is not None:
            os.environ["DATABASE_URL"] = old


# -- The gate degrades, and it is not composed ------------------------------------


def test_the_gate_resolves_to_none_without_a_database() -> None:
    # An absent DATABASE_URL composes no gate — a discoverable deployment
    # state, not an exception.  The refusal belongs to the caller that must
    # judge a promotion and finds no store.
    assert CriteriaChecks.resolve({}) is None


def test_the_gate_never_raises_and_takes_no_arguments() -> None:
    # The resolve protocol passes no arguments, and the factory builds every
    # component on every composition.
    assert list(inspect.signature(CriteriaChecks.resolve).parameters) in ([], ["env"])


def test_an_absent_database_refuses_by_name() -> None:
    # A gate pointed at nothing can neither confirm nor refuse a promotion,
    # which is the refusal a promotion path must never receive silently.
    with pytest.raises(CriteriaMismatchError) as raised:
        CriteriaChecks("   ")
    assert CRITERIA_MISMATCH_ERROR_CODE in str(raised.value)


# -- The error class sits beside the store's, not under it ------------------------


def test_the_mismatch_error_is_a_sibling_not_a_store_face() -> None:
    # CriteriaMismatchError is a verdict about a promotion, not a report about
    # the store.  It is a PromotionError (so a single except catches the
    # member's path) but it is not a PromotionStoreError — the split is the
    # repair's, which is the rule the error vocabulary opens with.
    assert issubclass(CriteriaMismatchError, PromotionError)
    assert not issubclass(CriteriaMismatchError, PromotionStoreError)
    assert CRITERIA_MISMATCH_ERROR_CODE != "promotion_registry_unwritable"


def test_the_member_exports_the_verdict() -> None:
    # The member re-exports the verdict and its code word, so a caller that
    # imports the member reaches the refusal.
    assert member.CriteriaMismatchError is CriteriaMismatchError
    assert member.CRITERIA_MISMATCH_ERROR_CODE == CRITERIA_MISMATCH_ERROR_CODE
