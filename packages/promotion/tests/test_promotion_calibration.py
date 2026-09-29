"""§7.4's verdict, read off the campaign row and refusing the promotion.

Feature 298's sentence — *"System rejects a promotion when the campaign
``calibration_status`` is ``VOID``, because a void campaign carries no usable
calibration"* — and the file where *refuses* is the claim under test.

**The finding is not this member's, and that is asserted first.**  §7.4's
verdict is pronounced and persisted by feature 124
(:class:`nulloracle.verdict.CampaignVerdict`), which writes the one column this
feature reads.  A suite that only drove the happy refusal would pass for a
module that had quietly re-derived the verdict from a p-value, or that had
shipped its own ``CREATE TABLE campaign``.  So the boundary tests come first:
this module reads one column, writes nothing, imports no other member, and holds
no p-value, no threshold and no test.

**Feature 243 is the gate this one is *not*, and the pair is pinned.**  The
discovery member's :func:`~discovery.manifest.admit_completed_campaigns` refuses
a void campaign *when adding completed campaigns to the replay pool*; this one
refuses it *when promoting from one*.  The two callers never meet — one holds
manifests, the other a node — and the one thing that must agree is the **code
word**, because an operator greps one word and has to land on both doors.  That
agreement is driven against the sibling's data when the sibling is present, the
way this member's block suite drives feature 285's own literal.

**The traversal is the feature, so it is tested as one.**  A caller promoting a
hypothesis holds a *node* identity; the campaign that spawned it is one column
away (``node.campaign_id`` → ``campaign.id``) and no store in this member
answered *which campaign is this node's* before this one.  The tests drive the
join against rows written in the migrations' own columns, and pin the two
absences it must refuse separately — a node the tree does not hold, and a node
whose campaign was never planned — because their repairs differ, and a caller
that fixed the wrong one would meet the same refusal again.

**Nothing is written, and that is the design.**  §7.4's record *is* the campaign
row, so a refusal leaves the database exactly as it was.  That is pinned on raw
``sqlite_master`` and row counts rather than assumed, because *"the audit trail
is the row we read"* is the kind of claim a later feature adds a second table
behind.

**Every refusal is one class.**  The caller is a promotion path whose one
failure mode is silence, so a single ``except VoidCalibrationError`` has to
catch every face — the malformed ask, the unreachable address, the two absences,
a status no writer produced, and the verdict itself.  The tests assert the class
*and* the code word, so a later feature that split them would fail here rather
than in production.

**What is deliberately not asserted.**  That the campaign row says what feature
124 wrote — that is the nulloracle member's suite, and driving it here would be
this suite pinning another member's *write* against its own restatement.  That
``0111``'s ``DEFAULT`` is ``'ok'`` — the clean half of every test here takes the
default rather than naming it, so this suite does not become a second place that
literal is fixed.  And that the composed application holds this gate — it does
not, and the last tests assert precisely that.
"""

from __future__ import annotations

import inspect
import sqlite3
import sys
from pathlib import Path

import promotion as member
import pytest
from conftest import (
    DEFAULT_CRITERIA_DOCUMENT,
    EPOCH_ID,
    NODE_ID,
    _load_migration,
    code_of,
)
from promotion import (
    CALIBRATION_MIGRATION_ORDER,
    CALIBRATION_STATUS_COLUMN,
    CALIBRATION_STATUS_OK,
    CALIBRATION_STATUS_VOID,
    CAMPAIGN_ID_COLUMN,
    CAMPAIGN_TABLE,
    MIGRATION_ORDER,
    PROMOTION_BLOCK_ERROR_CODE,
    PromotionBlockError,
    PromotionCalibrations,
    PromotionError,
    PromotionStoreError,
    VoidCalibrationError,
    bootstrap_calibration_schema,
    bootstrap_schema,
    campaign_calibration,
    rejects_void_calibration,
    rejects_void_promotion,
)
from promotion.errors import VOID_CALIBRATION_ERROR_CODE
from promotion.pre_register import NODE_ID_COLUMN
from promotion.schema import _calibration_statements, _statements

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES = REPO_ROOT / "packages"
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: A second campaign, a node whose campaign was never planned, and a node the
#: tree does not hold at all.  Named constants so a failure reads as a statement
#: about a *traversal* rather than about literals buried in an assertion.
OTHER_CAMPAIGN = "55555555-5555-4555-8555-555555555555"
OTHER_NODE = "66666666-6666-4666-8666-666666666666"
ORPHAN_NODE = "33333333-3333-4333-8333-333333333333"
ABSENT_NODE = "44444444-4444-4444-8444-444444444444"
NEVER_PLANNED = "99999999-9999-4999-8999-999999999999"


def _connect(database_url: str) -> sqlite3.Connection:
    """A raw connection to a ``sqlite:///`` URL, for a test's own reads.

    Raw rather than a store's connection, and deliberately: most of what these
    tests assert is what the *table* holds, and a test that asked the code under
    test to read it back would be asking that code to confirm itself.
    """
    assert database_url.startswith("sqlite:///"), database_url
    return sqlite3.connect(database_url[len("sqlite:///") :])


def _write_campaign(
    connection: sqlite3.Connection,
    campaign_id: str,
    *,
    status: str | None = None,
) -> None:
    """Insert one ``campaign`` row in the columns ``0111`` declares.

    Hand-written rather than driven through feature 232's writer, and
    deliberately so: the campaign row is *another member's* to create, and this
    suite pins this module's read against the **migration's** shape rather than
    against a sibling's current write path.  ``status=None`` means *take the
    column's default*, which is how the clean case is written — so this suite
    never restates ``0111``'s default as a literal of its own.
    """
    if status is None:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} "
            "(id, campaign_type, workspace_count, null_fraction) VALUES (?, ?, ?, ?)",
            (campaign_id, "Type-R", 32, 0.15),
        )
    else:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} "
            "(id, campaign_type, workspace_count, null_fraction, "
            f"{CALIBRATION_STATUS_COLUMN}) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, "Type-R", 32, 0.15, status),
        )


def _write_node(
    connection: sqlite3.Connection, node_id: str, campaign_id: str
) -> None:
    """Insert one ``node`` row in the columns ``0118`` declares."""
    connection.execute(
        "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
        (node_id, campaign_id, "macro", 1),
    )


def _set_status(database_url: str, status: str) -> None:
    """Set the campaign's ``calibration_status`` with a raw hand.

    The §7.4 write, performed the way a test has to perform it: this member never
    writes that column (feature 124's guard does), so a suite that needs a voided
    campaign states one.  The ``WHERE`` is left off on purpose — the fixture
    writes exactly one campaign row, and a test that added a second states its
    status at insert time.
    """
    connection = _connect(database_url)
    try:
        with connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET {CALIBRATION_STATUS_COLUMN} = ?",
                (status,),
            )
    finally:
        connection.close()


@pytest.fixture
def campaign_id() -> str:
    """The campaign the promoted node came from — one constant per test."""
    return "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def gate(database_url: str) -> PromotionCalibrations:
    """The gate, pointed at this test's own fresh database.

    No migration has run: the gate's first judgement is what brings ``node`` and
    ``campaign`` to the file, the contract every store in this member states.
    """
    return PromotionCalibrations(database_url)


@pytest.fixture
def planned(gate: PromotionCalibrations, campaign_id: str) -> str:
    """A database with the campaign row and the node that came from it.

    The campaign is written **clean** — ``0111``'s own default — so every test
    that wants ``VOID`` writes it deliberately, and a test that forgot to would
    fail loudly rather than passing for the wrong reason.

    The rows go in through the gate's own connection, so the schema under them is
    the one this feature bootstraps; the *columns* are the migrations' own.
    """
    connection = gate._connect()
    try:
        with connection:
            _write_campaign(connection, campaign_id)
            _write_node(connection, NODE_ID, campaign_id)
    finally:
        connection.close()
    return gate.database_url


# -- The boundary: this feature reads a verdict, it does not pronounce one --------


def test_the_module_never_pronounces_the_verdict_it_reads() -> None:
    # The hardest boundary assertion, and the one that keeps this gate from
    # quietly becoming a second §7.4.  The verdict is feature 124's: it compares a
    # stored p-value against 0.05 and writes the column.  A gate holding a
    # p-value, a threshold or a test would be re-deciding a finding it is supposed
    # to read — and the two deciders would disagree the first time one of them
    # changed, in a category whose disagreement is what §14 files as Fatal.
    #
    # Read off the **AST** rather than off the source text, because this module
    # legitimately *quotes* the guard's snippet in its refusal message — `if
    # ks_pvalue < 0.05` is the rule the refusal explains, and the conftest's
    # ``code_of`` keeps message strings for exactly that reason.  What must be
    # absent is the module *naming* the number or the column in code, which is
    # what a comparison would require.
    import ast

    from promotion import calibration as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    indexed = {
        id(node.slice)
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
    }
    # Every number in the module is the **index of a subscript** — ``row[0]``, the
    # positional read off a one-column ``SELECT`` — and there are no others.  A
    # threshold, a band or a tolerance would have to be a numeric literal standing
    # somewhere else, so this is the assertion that §7.4's boundary is not fixed
    # here.  ``bool`` is excluded because ``isinstance(True, int)`` and a keyword
    # default is not a threshold.
    numeric = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ]
    assert numeric, "the traversal still reads a column positionally"
    assert [node.value for node in numeric] == [0] * len(numeric)
    assert all(id(node) in indexed for node in numeric)
    # ...and no identifier, attribute or bare string that names the guard's input
    # — a *docstring or message* quoting the column is prose, and prose is the half
    # of the module a reader needs, so what is excluded here is the module naming
    # it in code: a ``Name``, an attribute, or a **key** (a short string used as an
    # identifier, which is how a dict lookup would reach a p-value).
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    named |= {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        # A *key*, not a sentence: identifiers are short and unspaced.
        and len(node.value) < 40
        and " " not in node.value
    }
    for leaked in ("ks_pvalue", "pvalue", "VOID_THRESHOLD", "ks_test"):
        assert leaked not in named, leaked
    # The citation survives in the messages and the docstrings, which is the half a
    # reader needs — so this is a test about *code*, not about a module being
    # unable to explain itself.
    assert "ks_pvalue" in code_of(module)


def test_the_module_writes_nothing() -> None:
    # §7.4's record *is* the campaign row this gate reads, so a refusal leaves the
    # database exactly as it was.  A second row carrying a copy of the verdict
    # would be a second spelling of one fact, free to disagree with the row a
    # reader would check — the drift ``0111``'s own docstring warns about when it
    # says the ``VOID`` write *is* the moment a campaign's calibration is voided,
    # singular.
    from promotion import calibration as module

    code = code_of(module)
    for leaked in ("INSERT INTO", "UPDATE ", "DELETE FROM", "CREATE TABLE", "ALTER TABLE"):
        assert leaked not in code, leaked
    # ...and the only SQL it does hold is the two reads, spelled from constants:
    # one for the node's campaign reference, one for the campaign's status.
    assert code.count("SELECT ") == 2


def test_the_module_imports_no_other_workspace_member() -> None:
    # No member imports another — every shared spelling is restated.  This
    # module's shared spellings are feature 124's verdict word (``VOID``) and
    # feature 243's code word (``void_campaign``), and both are driven against the
    # real siblings from the data side rather than from a module-scope import,
    # which would make this suite fail to collect wherever a sibling is absent.
    from promotion import calibration as module

    code = code_of(module)
    for leaked in (
        "import nulloracle",
        "from nulloracle",
        "import discovery",
        "from discovery",
        "import regime",
        "from regime",
    ):
        assert leaked not in code, leaked


def test_the_module_never_opens_the_coverage_ledger() -> None:
    # The sibling act on the same path is feature 299's, and it reads §C7's
    # coverage ledger.  This one must not: a void campaign and an under-covered
    # pool are different findings with different repairs, and a gate that read
    # both would be answering whichever it happened to check second.
    from promotion import calibration as module

    assert "regime_coverage" not in code_of(module)
    assert "coverage" not in code_of(module).lower()


def test_the_code_word_is_feature_243s_own_literal() -> None:
    # One finding, two doors, one word an operator greps.  Feature 243 refuses a
    # void campaign when adding completed campaigns to the replay pool; this
    # feature refuses it when promoting from one.  Nothing else about the two is
    # shared — different inputs, different tables read, different repairs — so the
    # code word is precisely the thing that must not drift.
    #
    # Driven against the sibling's data when the sibling is present, so a rename
    # on the discovery side fails here; a sibling's absence costs one assertion
    # rather than the collection of the whole suite.
    src = PACKAGES / "discovery" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    manifest = pytest.importorskip(
        "discovery.manifest", reason="the discovery member is not in this workspace"
    )
    assert (
        member.VOID_CALIBRATION_ERROR_CODE
        == manifest.VOID_CAMPAIGN_CODE
        == "void_campaign"
    )


def test_the_verdict_word_is_the_one_feature_124_pronounces() -> None:
    # The other shared spelling, pinned the same way: this feature *reads* §7.4's
    # word, and the module that writes it is where it is fixed.  The clean
    # spelling agrees as well, because a gate that read a different ``'ok'`` would
    # admit nothing feature 124 had ever cleared — though note that
    # ``CALIBRATION_STATUS_OK`` is here to be *named*, not to be a second
    # comparison: the gate refuses ``VOID`` and admits everything else.
    src = PACKAGES / "nulloracle" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    verdict = pytest.importorskip(
        "nulloracle.verdict", reason="the nulloracle member is not in this workspace"
    )
    assert member.CALIBRATION_STATUS_VOID == verdict.CALIBRATION_STATUS_VOID == "VOID"
    assert member.CALIBRATION_STATUS_OK == verdict.CALIBRATION_STATUS_OK
    assert member.CALIBRATION_STATUS_COLUMN == "calibration_status"


def test_the_two_gates_are_not_one_gate() -> None:
    # The distinction the module docstring draws, asserted rather than described:
    # feature 243's input is a *batch of manifests* and its repair is about the
    # pool; this feature's input is *a node* and its repair is about a campaign.
    # A caller of either cannot call the other — the promotion path holds no
    # manifest and the pool's add holds no node — so a module that had simply
    # imported and re-exposed 243's function would be the wrong shape, not merely
    # the wrong place.
    from promotion import calibration as module

    assert not hasattr(module, "admit_completed_campaigns")
    # ...and this gate takes a node, which no manifest-shaped call would.
    assert list(
        inspect.signature(PromotionCalibrations.rejects_void_promotion).parameters
    ) == ["self", "node_id"]


# -- The verdict: refusing a promotion from a void campaign -----------------------


def test_a_void_campaign_refuses_the_promotion(
    gate: PromotionCalibrations, planned: str, campaign_id: str
) -> None:
    # Feature 298's sentence, as one call: the campaign is void, so the promotion
    # of a hypothesis that came from it is refused.
    _set_status(planned, CALIBRATION_STATUS_VOID)
    with pytest.raises(VoidCalibrationError) as raised:
        gate.rejects_void_promotion(NODE_ID)
    message = str(raised.value)
    assert VOID_CALIBRATION_ERROR_CODE in message
    assert CALIBRATION_STATUS_VOID in message
    # The *campaign* is named, not only the node: an operator has to be able to go
    # and read the row the verdict is on.
    assert campaign_id in message
    # ...and the sentence's own clause is the reason given, so a reader who has
    # only the log line knows what rule they met.
    assert "carries no usable calibration" in message


def test_a_clean_campaign_admits_the_promotion_and_returns_the_status(
    gate: PromotionCalibrations, planned: str
) -> None:
    # The other half, and the return value is part of it: the answer to *may this
    # promotion proceed?* is *yes, under this calibration*, so the caller that
    # wants to log or carry the figure does not re-read the row.
    assert gate.rejects_void_promotion(NODE_ID) == CALIBRATION_STATUS_OK


def test_the_returned_status_is_the_row_s_own_and_not_a_default(
    gate: PromotionCalibrations, planned: str
) -> None:
    # A status this member has never heard of is *admitted*, and returned as the
    # row spells it.  Refusing an unknown status would be this gate inventing a
    # vocabulary for a verdict feature 124 owns — and *defaulting* it to ``'ok'``
    # would be the same invention wearing the other coat, because a caller would
    # be told a campaign is clean by a gate that never read a clean status.
    _set_status(planned, "suspect")
    assert gate.rejects_void_promotion(NODE_ID) == "suspect"


def test_the_comparison_is_exact(gate: PromotionCalibrations, planned: str) -> None:
    # ``'void'`` and ``'Void'`` are **not** the verdict and are admitted.  Folding
    # case would be this module pronouncing feature 124's finding itself — it has
    # no p-value, no threshold and no test, so the spelling on the row is the
    # whole of what it knows, and the verdict it would invent out of a typo is the
    # one §14 files as Fatal.  The one place the word is fixed is the module that
    # pronounces it.
    for near_miss in ("void", "Void", "vOID", "VOIDS"):
        _set_status(planned, near_miss)
        assert gate.rejects_void_promotion(NODE_ID) == near_miss
    # ...and the exact word still refuses, after all of those, so the loop is not
    # silently testing a gate that admits everything.
    _set_status(planned, CALIBRATION_STATUS_VOID)
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion(NODE_ID)


def test_a_trailing_newline_is_stripped_rather_than_treated_as_another_status(
    gate: PromotionCalibrations, planned: str
) -> None:
    # The one normalisation, and it is a *rejection* rule rather than a comparison
    # rule: ``'VOID\n'`` is read as ``'VOID'`` and refused.  A gate that let
    # whitespace make two spellings of one status would admit a promotion whose
    # campaign a later reader grouping by the column could not see was void.
    _set_status(planned, f"{CALIBRATION_STATUS_VOID}\n")
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion(NODE_ID)
    # ...and the strip does not case-fold: a padded near-miss is still admitted.
    _set_status(planned, "  void  ")
    assert gate.rejects_void_promotion(NODE_ID) == "void"


def test_the_judgement_raises_rather_than_answering_a_boolean(
    gate: PromotionCalibrations, planned: str
) -> None:
    # The shape that blocks a deployment has to be the function's own act: a caller
    # that forgot to branch on a returned boolean would promote a hypothesis whose
    # calibration was voided, which is exactly the outcome §7.4's *"excluded for
    # FDR purposes"* exists to stop.  So the good path *returns* and the bad path
    # *raises*, and neither is optional.
    assert gate.rejects_void_promotion(NODE_ID) == CALIBRATION_STATUS_OK
    _set_status(planned, CALIBRATION_STATUS_VOID)
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion(NODE_ID)


def test_the_act_reaches_the_comparison_through_the_pure_function(
    gate: PromotionCalibrations, planned: str, campaign_id: str
) -> None:
    # One comparison in the member and not two: the act performs the traversal and
    # then calls :func:`rejects_void_calibration`, so the two cannot disagree about
    # where §7.4's boundary falls.  Driven over the same pair through both
    # spellings and compared on the clause both messages carry — the act's naming
    # the campaign it resolved, the function's the one it was handed.
    _set_status(planned, CALIBRATION_STATUS_VOID)
    with pytest.raises(VoidCalibrationError) as via_act:
        gate.rejects_void_promotion(NODE_ID)
    with pytest.raises(VoidCalibrationError) as via_function:
        rejects_void_calibration(campaign_id, CALIBRATION_STATUS_VOID)
    assert VOID_CALIBRATION_ERROR_CODE in str(via_act.value)
    assert VOID_CALIBRATION_ERROR_CODE in str(via_function.value)
    assert f"the campaign {campaign_id}" in str(via_act.value)
    assert f"the campaign {campaign_id}" in str(via_function.value)
    # ...and the *clean* halves agree too: neither raises.
    _set_status(planned, CALIBRATION_STATUS_OK)
    assert gate.rejects_void_promotion(NODE_ID) == rejects_void_calibration(
        campaign_id, CALIBRATION_STATUS_OK
    )


def test_the_refusal_writes_nothing(gate: PromotionCalibrations, planned: str) -> None:
    # *"The audit trail is the campaign row"* is the claim, and it is the kind a
    # later feature adds a second table behind.  So the refusals are driven and the
    # database is compared to itself: same tables, same row counts, same status.

    def snapshot() -> tuple[list[tuple[str, int]], str]:
        connection = _connect(planned)
        try:
            tables = [
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                )
            ]
            counts = [
                (
                    name,
                    connection.execute(
                        f'SELECT COUNT(*) FROM "{name}"'
                    ).fetchone()[0],
                )
                for name in tables
            ]  # (table, row count) per table
            status = connection.execute(
                f"SELECT {CALIBRATION_STATUS_COLUMN} FROM {CAMPAIGN_TABLE}"
            ).fetchone()[0]
        finally:
            connection.close()
        return counts, status

    before = snapshot()
    # An absent node — a refusal, and no write.
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion(ABSENT_NODE)
    assert snapshot() == before

    _set_status(planned, CALIBRATION_STATUS_VOID)
    voided = snapshot()
    # The verdict refusal, the malformed ask, and the read — none of them a write.
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion(NODE_ID)
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion("not-a-uuid")
    assert gate.campaign_calibration(NODE_ID) == CALIBRATION_STATUS_VOID
    assert snapshot() == voided
    # ...and nothing was added for any of them: the refusal is not a record, and
    # the only tables in the database are the two the *gate* brought up, each
    # holding the one row the fixture wrote.
    rows, status = voided
    assert rows == [("campaign", 1), ("node", 1)]
    assert status == CALIBRATION_STATUS_VOID


# -- The traversal: the node, the campaign, and the two absences ------------------


def test_a_node_the_tree_does_not_hold_is_refused_by_name(
    gate: PromotionCalibrations, planned: str
) -> None:
    # The traversal starts at the node, so a node that does not exist names no
    # hypothesis and there is no ``campaign_id`` to follow.  Refused by probe
    # rather than left to the database, for the reason this member's other probes
    # exist: **no SQLite error would ever be raised here at all** — ``0118``
    # declares ``node.campaign_id`` without a ``REFERENCES`` clause, so nothing but
    # this probe stands between a node and a campaign row that does not exist.
    with pytest.raises(VoidCalibrationError) as raised:
        gate.rejects_void_promotion(ABSENT_NODE)
    message = str(raised.value)
    assert VOID_CALIBRATION_ERROR_CODE in message
    assert ABSENT_NODE in message
    assert "node holds no row" in message
    # The repair is named, and it is *this* absence's repair.
    assert "Write the node" in message


def test_a_node_whose_campaign_was_never_planned_is_refused_separately(
    gate: PromotionCalibrations, planned: str
) -> None:
    # A node the tree *does* hold, naming a campaign row that is not there.  This
    # is the second absence and it is refused in its own words because the repair
    # differs from the first's: *plan the campaign* is not *write the node*, and a
    # caller that fixed the wrong one would meet the same refusal again.
    connection = _connect(planned)
    try:
        with connection:
            _write_node(connection, ORPHAN_NODE, NEVER_PLANNED)
    finally:
        connection.close()
    with pytest.raises(VoidCalibrationError) as raised:
        gate.rejects_void_promotion(ORPHAN_NODE)
    message = str(raised.value)
    assert VOID_CALIBRATION_ERROR_CODE in message
    # The campaign it named is in the message — that is the row an operator goes
    # looking for — and the node it came off is too.
    assert NEVER_PLANNED in message
    assert ORPHAN_NODE in message
    assert "campaign holds no row" in message
    assert "Plan the campaign" in message


def test_the_two_absences_are_distinguishable_by_their_messages(
    gate: PromotionCalibrations, planned: str
) -> None:
    # Driven as a pair, because two refusals that *read* differently in a
    # docstring and identically in a log line are one refusal.  A caller that
    # branches on the message has to be able to tell which repair it owes.
    connection = _connect(planned)
    try:
        with connection:
            _write_node(connection, ORPHAN_NODE, NEVER_PLANNED)
    finally:
        connection.close()
    with pytest.raises(VoidCalibrationError) as absent_node:
        gate.rejects_void_promotion(ABSENT_NODE)
    with pytest.raises(VoidCalibrationError) as absent_campaign:
        gate.rejects_void_promotion(ORPHAN_NODE)
    assert str(absent_node.value) != str(absent_campaign.value)
    assert f"{CAMPAIGN_TABLE} holds no row" in str(absent_campaign.value)
    assert f"{CAMPAIGN_TABLE} holds no row" not in str(absent_node.value)
    # Both open with the one code word, so a grep still finds both.
    assert str(absent_node.value).startswith(VOID_CALIBRATION_ERROR_CODE)
    assert str(absent_campaign.value).startswith(VOID_CALIBRATION_ERROR_CODE)


def test_the_join_is_node_campaign_id_to_campaign_id(
    gate: PromotionCalibrations, planned: str
) -> None:
    # The traversal pinned against the *migrations'* own columns rather than
    # against a guess: a join written against the wrong pair (``node.id`` to
    # ``campaign.id``, say) would look for a campaign whose key is a node's
    # identity and would answer *no such campaign* for every node in the tree.  So
    # two campaigns and two nodes are written, and each node must be read against
    # *its own* campaign's status.
    connection = _connect(planned)
    try:
        with connection:
            _write_campaign(connection, OTHER_CAMPAIGN, status=CALIBRATION_STATUS_VOID)
            _write_node(connection, OTHER_NODE, OTHER_CAMPAIGN)
    finally:
        connection.close()
    assert gate.rejects_void_promotion(NODE_ID) == CALIBRATION_STATUS_OK
    assert gate.campaign_calibration(OTHER_NODE) == CALIBRATION_STATUS_VOID
    with pytest.raises(VoidCalibrationError) as raised:
        gate.rejects_void_promotion(OTHER_NODE)
    # The refusal names the campaign *this* node came from and not the other one,
    # which is what makes the join a join rather than a lookup of any campaign.
    # Read off the fixture's own campaign id rather than a literal, so the
    # assertion is about the *pairing* and not about a second copy of the UUID.
    assert OTHER_CAMPAIGN in str(raised.value)
    connection = _connect(planned)
    try:
        fixture_campaign = connection.execute(
            f"SELECT {CAMPAIGN_ID_COLUMN} FROM node WHERE id = ?", (NODE_ID,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert fixture_campaign not in str(raised.value)


def test_the_campaign_reference_is_validated_rather_than_assumed(
    gate: PromotionCalibrations, planned: str
) -> None:
    # ``0118`` declares the column ``UUID NOT NULL``, so a stored row always holds
    # a UUID — but SQLite's columns are dynamically typed, and a hand that reached
    # past every writer could land anything in it.  The refusal names the *node* it
    # came off, because the difference between *this node's row is not one the tree
    # could have written* and *some row somewhere is malformed* is the difference
    # between an operator checking one node and checking all of them.
    connection = _connect(planned)
    try:
        with connection:
            connection.execute(
                f"UPDATE node SET {CAMPAIGN_ID_COLUMN} = ? WHERE id = ?",
                ("not-a-uuid", NODE_ID),
            )
    finally:
        connection.close()
    with pytest.raises(VoidCalibrationError) as raised:
        gate.rejects_void_promotion(NODE_ID)
    message = str(raised.value)
    assert VOID_CALIBRATION_ERROR_CODE in message
    assert NODE_ID in message
    assert "'not-a-uuid'" in message


def test_a_blank_status_is_refused_rather_than_read_as_not_void(
    gate: PromotionCalibrations, planned: str
) -> None:
    # The trap at the far end: answering *this promotion may proceed* on a status
    # that states nothing would be admitting a promotion on a hole.  ``0111``
    # declares the column ``NOT NULL DEFAULT 'ok'``, so a blank one is a row no
    # writer in this workspace produced — and *neither* admitting nor refusing it
    # silently is honest, so it is refused by name.
    for blank in ("", "   ", "\n"):
        _set_status(planned, blank)
        with pytest.raises(VoidCalibrationError) as raised:
            gate.rejects_void_promotion(NODE_ID)
        message = str(raised.value)
        assert VOID_CALIBRATION_ERROR_CODE in message
        assert CALIBRATION_STATUS_COLUMN in message


@pytest.mark.parametrize("bad", ["", "   ", "not-a-uuid", None, 17, b"x", []])
def test_a_malformed_node_is_refused_in_this_members_vocabulary(
    gate: PromotionCalibrations, bad: object
) -> None:
    # The seam rule: the *rule* is feature 291's validator, the *class* is this
    # feature's.  A caller whose single ``except VoidCalibrationError`` guards its
    # promotion path must not be defeated by a pre-registration's ask refusal,
    # because it would read *the body was malformed* where the truth is *this
    # promotion was not judged* — and would go on to promote.
    with pytest.raises(VoidCalibrationError) as raised:
        gate.rejects_void_promotion(bad)
    assert VOID_CALIBRATION_ERROR_CODE in str(raised.value)
    assert isinstance(raised.value, PromotionError)
    # ...and the inner refusal is carried through rather than swallowed, so the
    # operator still learns which field the validator objected to.
    assert NODE_ID_COLUMN in str(raised.value)


def test_the_malformed_node_is_refused_before_anything_is_opened(
    gate: PromotionCalibrations,
) -> None:
    # Refused *before* the connection, so a malformed ask leaves no file behind:
    # the same discipline the other refusals keep, stated separately because the
    # reason differs — here it is that the identity could not name a node at all,
    # so nothing is worth opening.
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion("not-a-uuid")
    assert not Path(gate.database_url[len("sqlite:///") :]).exists()


# -- The store's contract ---------------------------------------------------------


def test_construction_performs_no_io(tmp_path: Path) -> None:
    # Composition-time work must not touch the disk — the contract every store in
    # this workspace states — so a misconfigured deployment composes a gate that
    # refuses when it is used rather than one that raises while being built.
    database = tmp_path / "untouched.db"
    gate = PromotionCalibrations(f"sqlite:///{database}")
    assert not database.exists()
    assert gate.database_url == f"sqlite:///{database}"
    _ = gate.path  # ...and nothing is created by asking for the path either.
    assert not database.exists()


def test_a_url_this_member_cannot_speak_is_refused_in_its_own_words() -> None:
    # Construction performs no I/O, so the URL is translated — and refused by name
    # — the first time an operation needs it.  The class is this feature's and not
    # ``PromotionStoreError``, for the reason the malformed-node test states from
    # the other side.
    gate = PromotionCalibrations("postgresql://localhost/nullius")
    with pytest.raises(VoidCalibrationError) as raised:
        gate.rejects_void_promotion(NODE_ID)
    assert VOID_CALIBRATION_ERROR_CODE in str(raised.value)
    assert "database address" in str(raised.value)


def test_a_blank_database_url_is_refused_at_construction() -> None:
    # A fact about the *gate* rather than about any one promotion: a URL that is
    # not a non-empty string names no table, and a gate that accepted one would
    # fail identically on every judgement — the wrong place for a deployment to
    # discover a wiring fault.
    for bad in ("", "   ", None, 17, []):
        with pytest.raises(VoidCalibrationError) as raised:
            PromotionCalibrations(bad)
        assert VOID_CALIBRATION_ERROR_CODE in str(raised.value)


def test_the_gate_resolves_from_the_environment_and_says_none_when_it_names_none(
    monkeypatch,
) -> None:
    # ``None`` means *nothing named a database* — a statement about the deployment,
    # not an empty campaign table.  A caller that must judge a promotion has to
    # treat it as a refusal to proceed, so the two must not collapse: an absent
    # ``DATABASE_URL`` answers ``None``, a named one answers the gate.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert PromotionCalibrations.resolve() is None
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert PromotionCalibrations.resolve() is None
    monkeypatch.setenv("DATABASE_URL", "sqlite:///somewhere.db")
    gate = PromotionCalibrations.resolve()
    assert gate is not None and gate.database_url == "sqlite:///somewhere.db"
    # An explicit mapping is read instead of the process's environment, so a caller
    # can state the deployment it means.
    assert PromotionCalibrations.resolve({}) is None
    assert PromotionCalibrations.resolve({"DATABASE_URL": "  "}) is None


def test_the_gate_holds_no_cache(gate: PromotionCalibrations, planned: str) -> None:
    # The verdict *moves*: §7.4's guard voids a campaign after it completes, so a
    # gate that remembered a status across a long-lived process would admit a
    # promotion whose campaign was voided a minute ago.  The row is the only record
    # and the only thing an answer is drawn from.
    assert gate.rejects_void_promotion(NODE_ID) == CALIBRATION_STATUS_OK
    _set_status(planned, CALIBRATION_STATUS_VOID)
    with pytest.raises(VoidCalibrationError):
        gate.rejects_void_promotion(NODE_ID)
    assert gate.campaign_calibration(NODE_ID) == CALIBRATION_STATUS_VOID
    # ...and it moves back: the gate reads the row, whatever the row now says.
    _set_status(planned, CALIBRATION_STATUS_OK)
    assert gate.rejects_void_promotion(NODE_ID) == CALIBRATION_STATUS_OK


# -- The two spellings: the pure judgment and the act -----------------------------


def test_the_pure_judgment_needs_no_database_at_all() -> None:
    # :func:`rejects_void_calibration` is the feature's sentence as one comparison,
    # for the caller that *already holds the status* — a promotion path that read
    # the campaign itself, a test judging a carrier, a later feature that reached
    # the row its own way.  It opens nothing, which is what makes it usable at a
    # seam where no store exists.
    campaign = "22222222-2222-4222-8222-222222222222"
    assert (
        rejects_void_calibration(campaign, CALIBRATION_STATUS_OK)
        == CALIBRATION_STATUS_OK
    )
    assert rejects_void_calibration(campaign, "anything else") == "anything else"
    with pytest.raises(VoidCalibrationError) as raised:
        rejects_void_calibration(campaign, CALIBRATION_STATUS_VOID)
    assert VOID_CALIBRATION_ERROR_CODE in str(raised.value)
    # ...and it validates both halves: the identity, because the refusal has to
    # name a campaign an operator can find; the status, because there has to be a
    # verdict to compare.
    with pytest.raises(VoidCalibrationError):
        rejects_void_calibration("not-a-uuid", CALIBRATION_STATUS_OK)
    with pytest.raises(VoidCalibrationError):
        rejects_void_calibration(campaign, "")


def test_the_module_level_spellings_answer_without_a_store(
    planned: str, monkeypatch
) -> None:
    # The feature's sentence as one call, for the caller that wants the act without
    # holding a gate.  Resolved from an explicit URL, else from ``DATABASE_URL`` —
    # the same two-step every store in this workspace uses.
    assert (
        rejects_void_promotion(NODE_ID, database_url=planned) == CALIBRATION_STATUS_OK
    )
    assert campaign_calibration(NODE_ID, database_url=planned) == CALIBRATION_STATUS_OK
    monkeypatch.setenv("DATABASE_URL", planned)
    assert rejects_void_promotion(NODE_ID) == CALIBRATION_STATUS_OK
    assert campaign_calibration(NODE_ID) == CALIBRATION_STATUS_OK
    # ...and the two spellings read the *same* row, which is the whole reason the
    # read and the judgement share one traversal.
    _set_status(planned, CALIBRATION_STATUS_VOID)
    assert campaign_calibration(NODE_ID) == CALIBRATION_STATUS_VOID
    with pytest.raises(VoidCalibrationError):
        rejects_void_promotion(NODE_ID)


def test_an_explicit_url_wins_over_the_environment(
    planned: str, tmp_path: Path
) -> None:
    # Both are named and they disagree: the explicit argument wins, because a
    # caller that passed one stated the database it means, and a process-wide
    # variable is not a second opinion.  Driven with the *environment* naming a
    # different, freshly-bootstrapped database — so the wrong precedence answers
    # *absent node* where the right one answers ``'ok'``.
    other = tmp_path / "other.db"
    other_url = f"sqlite:///{other}"
    PromotionCalibrations(other_url)._connect().close()
    connection = _connect(other_url)
    try:
        with connection:
            _write_node(connection, OTHER_NODE, OTHER_CAMPAIGN)
    finally:
        connection.close()
    # The wrong precedence would read *other* — which holds no row for this node —
    # and refuse; the right one reads ``planned`` and answers.
    assert (
        rejects_void_promotion(
            NODE_ID, database_url=planned, env={"DATABASE_URL": other_url}
        )
        == CALIBRATION_STATUS_OK
    )
    with pytest.raises(VoidCalibrationError) as raised:
        rejects_void_promotion(
            NODE_ID, database_url=other_url, env={"DATABASE_URL": planned}
        )
    assert "node holds no row" in str(raised.value)


def test_the_module_level_spellings_refuse_a_deployment_that_names_no_database(
    monkeypatch,
) -> None:
    # The dangerous failure is the *silence*, not the refusal: a judgement that
    # quietly did not happen leaves a promotion proceeding on no calibration at
    # all, which is the state §7.4's exclusion exists to make impossible.  So a
    # store resolved from nothing is a refusal rather than a no-op.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for call in (rejects_void_promotion, campaign_calibration):
        with pytest.raises(VoidCalibrationError) as raised:
            call(NODE_ID)
        message = str(raised.value)
        assert VOID_CALIBRATION_ERROR_CODE in message
        assert "DATABASE_URL" in message
    # ...and an explicitly blank URL is the same deployment, refused the same way.
    with pytest.raises(VoidCalibrationError) as raised:
        rejects_void_promotion(NODE_ID, database_url="   ", env={})
    assert "DATABASE_URL" in str(raised.value)


def test_the_read_answers_no_verdict(planned: str) -> None:
    # The read is the *reading* and not the decision: a void campaign is returned
    # as the string it is, so a caller that wants the figure rather than the
    # judgment does not have to catch an exception to get it.
    _set_status(planned, CALIBRATION_STATUS_VOID)
    assert (
        campaign_calibration(NODE_ID, database_url=planned) == CALIBRATION_STATUS_VOID
    )
    with pytest.raises(VoidCalibrationError):
        rejects_void_promotion(NODE_ID, database_url=planned)


def test_the_read_and_the_judgement_refuse_the_same_absences(planned: str) -> None:
    # One traversal, two verbs: a second ``SELECT`` for the read could drift from
    # the one a refusal was made on, and a caller would be handed a figure the
    # judgment never saw.  Driven over the absences, which is where a divergence
    # would show first — and a *malformed* identity and an *absent* node are
    # different refusals, so both are driven.
    connection = _connect(planned)
    try:
        with connection:
            connection.execute(
                f"UPDATE node SET {CAMPAIGN_ID_COLUMN} = ? WHERE id = ?",
                ("not-a-uuid", NODE_ID),
            )
    finally:
        connection.close()
    for absent in (ABSENT_NODE, "not-a-uuid"):
        with pytest.raises(VoidCalibrationError):
            campaign_calibration(absent, database_url=planned)
        with pytest.raises(VoidCalibrationError):
            rejects_void_promotion(absent, database_url=planned)


def test_the_read_names_the_campaign_when_it_refuses_an_absent_campaign(
    gate: PromotionCalibrations,
) -> None:
    # The read's refusal is the same refusal, not a thinner one: an operator asking
    # what a node's campaign carries has to be told which campaign was missing, or
    # the diagnostic is a dead end.  Driven through a database holding the orphan
    # node and no campaign row for it — and *not* the ``planned`` fixture, so there
    # is no second campaign for the message to be confused with.
    connection = gate._connect()
    try:
        with connection:
            _write_node(connection, ORPHAN_NODE, NEVER_PLANNED)
    finally:
        connection.close()
    with pytest.raises(VoidCalibrationError) as raised:
        gate.campaign_calibration(ORPHAN_NODE)
    assert NEVER_PLANNED in str(raised.value)
    assert ORPHAN_NODE in str(raised.value)


# -- The schema: the migrations own it, this member runs it -----------------------


def test_the_calibration_bootstrap_authors_no_ddl_of_its_own() -> None:
    # The same claim the member's schema suite makes for the pre-registration's
    # three, over the calibration read's two: not one statement is authored here,
    # and the files this feature names are where the DDL comes from.
    from promotion import schema as schema_module

    assert "CREATE TABLE" not in code_of(schema_module)
    for _table, revision in CALIBRATION_MIGRATION_ORDER:
        assert "CREATE TABLE" in code_of(_load_migration(revision)), revision


def test_the_calibration_order_names_the_two_tables_this_act_reads() -> None:
    # Two tables, one per half of the traversal, each beside the file that owns it.
    # Asserted against the *migration's* declared ``TABLES`` rather than against
    # the DDL text, so a rename is caught here rather than at the first judgement
    # against a fresh database.
    assert [table for table, _revision in CALIBRATION_MIGRATION_ORDER] == [
        "node",
        CAMPAIGN_TABLE,
    ]
    for table, revision in CALIBRATION_MIGRATION_ORDER:
        assert table in tuple(_load_migration(revision).TABLES), revision
        assert (VERSIONS_DIR / f"{revision}.py").is_file()


def test_the_calibration_order_is_not_a_widening_of_the_registrys() -> None:
    # The design decision, pinned as data: feature 291's order is a claim about
    # *the three tables one ``INSERT`` needs*, and the member's schema suite asserts
    # it as such.  Widening it would have made every pre-registration create
    # ``campaign`` — a table its ``INSERT`` never reads — and the calibration read
    # create ``epoch_ledger`` and ``promotion_registry`` for two ``SELECT``s that
    # never name them.  Two acts, two sets.
    assert [table for table, _revision in MIGRATION_ORDER] == [
        "node",
        "epoch_ledger",
        "promotion_registry",
    ]
    assert CAMPAIGN_TABLE not in [table for table, _revision in MIGRATION_ORDER]
    assert "epoch_ledger" not in [
        table for table, _revision in CALIBRATION_MIGRATION_ORDER
    ]
    assert "promotion_registry" not in [
        table for table, _revision in CALIBRATION_MIGRATION_ORDER
    ]
    # ...and the file that owns ``campaign`` is not a file the registry's order runs
    # at all, which is what makes the two sets disjoint rather than nested.
    assert "0111_campaign_table" not in [
        revision for _table, revision in MIGRATION_ORDER
    ]


def test_the_bootstrap_puts_exactly_the_two_tables_this_act_reads(
    gate: PromotionCalibrations,
) -> None:
    # The set driven rather than quoted: bring the database up through the gate,
    # then ask ``sqlite_master`` what exists.  A set that had quietly grown would
    # fail here — and the *absence* of the pre-registration's tables is the half
    # that keeps a reader able to tell a dependency from a habit.
    gate._connect().close()
    connection = _connect(gate.database_url)
    try:
        names = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert {"node", CAMPAIGN_TABLE} <= names
    assert "epoch_ledger" not in names
    assert "promotion_registry" not in names
    assert "forward_record" not in names


def test_the_statements_are_the_owners_own_tuple_for_tuple() -> None:
    # Not "agree with" — *are*.  This is the property that makes drift impossible
    # rather than merely unlikely, and it is asserted over the private helper the
    # bootstrap itself uses, so the two cannot part company.
    expected: list[str] = []
    for _table, revision in CALIBRATION_MIGRATION_ORDER:
        expected.extend(_load_migration(revision).statements("sqlite"))
    assert list(_calibration_statements("sqlite")) == expected
    assert list(_calibration_statements()) == expected
    assert all("IF NOT EXISTS" in statement for statement in expected)


def test_the_two_bootstraps_share_one_rule_and_neither_is_the_other() -> None:
    # Two sets, one discipline — and the *sets* are the assertion, because the
    # whole reason for the second constant is that a reader must be able to tell a
    # dependency from a habit.  Driven on real connections, both ways.
    calibration = _calibration_statements("sqlite")
    registry = _statements("sqlite")
    assert len(calibration) == 2 and len(registry) == 11
    # One ``CREATE TABLE`` per act's set, named off the DDL the migrations wrote:
    # the calibration set is ``node`` and ``campaign``; the registry's is the one
    # ``0118`` file, the one ``0110`` file, and ``0108``'s nine.
    assert "CREATE TABLE IF NOT EXISTS campaign" in " ".join(calibration)
    assert "CREATE TABLE IF NOT EXISTS campaign" not in " ".join(registry)
    assert "CREATE TABLE IF NOT EXISTS epoch_ledger" in " ".join(registry)
    assert "CREATE TABLE IF NOT EXISTS epoch_ledger" not in " ".join(calibration)
    assert "promotion_registry" in " ".join(registry)
    assert "promotion_registry" not in " ".join(calibration)
    # ``node`` is the one table the two acts share — and it is shared by *name*,
    # which is the honest statement: both sets carry ``0118``'s own statement.
    assert "CREATE TABLE IF NOT EXISTS node" in " ".join(calibration)
    assert "CREATE TABLE IF NOT EXISTS node" in " ".join(registry)
    assert set(calibration) & set(registry) == {registry[0]}
    # The reference column rides in on ``0118``'s statement in both sets, so the
    # sets differ in size and in everything but that one shared statement.
    assert calibration[0] == registry[0]

    connection = sqlite3.connect(":memory:")
    try:
        ran = bootstrap_calibration_schema(connection)
        assert ran == calibration
        # ...and answering twice is not an error, which is what makes a fresh
        # database and a fully-migrated one take the same path.
        assert bootstrap_calibration_schema(connection) == calibration
    finally:
        connection.close()

    connection = sqlite3.connect(":memory:")
    try:
        assert bootstrap_schema(connection) == registry
    finally:
        connection.close()


def test_the_bootstraps_converge_on_a_migrated_database(
    tmp_path: Path, planned: str, gate: PromotionCalibrations
) -> None:
    # The deployment shape where the chain got there first: the gate must serve
    # *that* schema rather than a second one of its own.  Compared as
    # ``sqlite_master`` text, because that is the schema the database actually has
    # — a bootstrap that spelled a column differently would build a table the
    # migrations' readers could not use.
    migrated_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    for _table, revision in CALIBRATION_MIGRATION_ORDER:
        _load_migration(revision).apply(migrated_url)

    def schema_of(url: str) -> dict[str, str]:
        connection = _connect(url)
        try:
            return {
                name: sql
                for name, sql in connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()

    expected = schema_of(migrated_url)
    assert set(expected) == {"node", CAMPAIGN_TABLE}
    # The gate's own bootstrap, on the fixture's fresh database, lands the same
    # schema; and reading the *migrated* database does not rewrite it.
    assert schema_of(planned) == expected
    _set_status(planned, CALIBRATION_STATUS_OK)
    assert gate.rejects_void_promotion(NODE_ID) == CALIBRATION_STATUS_OK
    assert schema_of(planned) == expected
    assert schema_of(migrated_url) == expected


def test_the_campaign_table_is_the_one_the_migration_declares() -> None:
    # The strings both sides must spell the same, read off the migration's own
    # ``TABLES`` and its own statements rather than off a hand-written
    # expectation.
    owner = _load_migration("0111_campaign_table")
    assert CAMPAIGN_TABLE in tuple(owner.TABLES)
    assert CALIBRATION_STATUS_COLUMN in " ".join(owner.statements("sqlite"))
    assert CAMPAIGN_ID_COLUMN in " ".join(
        _load_migration("0118_node_table").statements("sqlite")
    )


# -- The member's surface is otherwise untouched ----------------------------------


def test_the_member_still_exports_exactly_one_builder() -> None:
    # Feature 298 adds no component, and it is the sharpest case for the rule: a
    # builder takes no arguments and is built on every ``create_app()`` call, while
    # *which campaign is void* is a fact about a row that no composition can
    # supply.  A component pointed at a campaign status would have to be
    # constructed per campaign, which the factory's protocol cannot express.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_error_is_a_sibling_and_not_a_face_of_the_block() -> None:
    # The taxonomy's split rule, asserted as data: both are merit refusals and both
    # are gathered internally, but they are *different findings about different
    # facts* with different repairs — §C7's pool coverage versus §7.4's calibration
    # verdict — so one ``except`` must not be able to stand for both.  And each
    # carries its own code word, which is what makes each greppable.
    assert not issubclass(VoidCalibrationError, PromotionBlockError)
    assert not issubclass(PromotionBlockError, VoidCalibrationError)
    assert VOID_CALIBRATION_ERROR_CODE != PROMOTION_BLOCK_ERROR_CODE
    assert issubclass(VoidCalibrationError, PromotionError)
    assert issubclass(PromotionStoreError, PromotionError)
    # ...and the calibration gate does not raise the store's class for what is its
    # own address fault, which is the seam rule stated from the class side.
    assert not issubclass(VoidCalibrationError, PromotionStoreError)


def test_the_specs_sentence_is_what_this_module_implements() -> None:
    # The feature's own line, quoted so a reader of this suite does not have to go
    # looking, and so a re-scoped feature would fail a test rather than quietly
    # leaving the suite asserting something the spec no longer says.
    spec = REPO_ROOT / "app_spec.xml"
    if not spec.is_file():  # pragma: no cover - the spec is in the checkout
        pytest.skip("app_spec.xml is not in this checkout")
    assert (
        "System rejects a promotion when the campaign calibration_status is "
        "VOID, because a void campaign carries no usable calibration"
        in spec.read_text(encoding="utf-8")
    )


# -- Independence: the gate does not disturb the other act on the same path -------


def test_a_void_campaign_does_not_disturb_the_pre_registration(
    seeded_database, database_url: str, campaign_id: str
) -> None:
    # The two features are independent over one node: §13 item 7's recorded hash is
    # the thing the deciding evaluation is checked against, and refusing the
    # promotion for a void campaign must not touch it.  This gate writes nothing at
    # all, so the assertion is that a registry row written beforehand reads back
    # byte for byte after a refusal — and that the refusal *still happens*, which is
    # the half a store that quietly did something would also pass.
    #
    # The campaign row is written through *the gate's* connection rather than the
    # registry store's, and that is itself the point of a second set: the
    # pre-registration's bootstrap creates the three tables one ``INSERT`` needs,
    # and ``campaign`` is not among them — so a test that asked the registry to
    # write a campaign would be asking it to fill a table its act never names.
    gate = PromotionCalibrations(database_url)
    connection = gate._connect()
    try:
        with connection:
            _write_campaign(connection, campaign_id)
    finally:
        connection.close()
    member.PreRegisterEndpoint(seeded_database).post(
        member.PreRegistrationRequest(
            node_id=NODE_ID,
            epoch_id=EPOCH_ID,
            criteria=dict(DEFAULT_CRITERIA_DOCUMENT),
        )
    )

    def registry_row() -> tuple[object, ...] | None:
        connection = _connect(database_url)
        try:
            return connection.execute(
                "SELECT id, node_id, epoch_id, criteria_hash, pre_registered_at, "
                "decided_at FROM promotion_registry WHERE node_id = ?",
                (NODE_ID,),
            ).fetchone()
        finally:
            connection.close()

    before = registry_row()
    assert before is not None and before[5] is None  # the row is still open

    _set_status(database_url, CALIBRATION_STATUS_VOID)
    with pytest.raises(VoidCalibrationError):
        rejects_void_promotion(NODE_ID, database_url=database_url)
    assert registry_row() == before
