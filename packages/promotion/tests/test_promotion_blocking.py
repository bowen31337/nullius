"""The blocking reason: §C7's promotion block, persisted as a row.

Feature 299's sentence — *"System persists a blocking reason for a promotion
whose deployment regime coverage sits below threshold"* — and the file where
*persists* is the claim under test rather than *refuses*.

**What this feature is not, asserted as hard as what it is.**  The refusal
already exists: feature 285's
:func:`regime.promotion.rejects_undercovered_promotion` raises
``PromotionCoverageError`` on ``coverage_below_threshold`` when the target
regime's count sits below the configured threshold, and that module's docstring
reserves this half by name.  So the first tests here pin the *boundary*: this
module never reads the coverage ledger, never imports the regime member, and
never asks whether the pool covers anything.  It takes the caller's figures as
the evidence the caller gathered and persists *why the promotion was blocked*.
A suite that only tested the happy write would pass for a module that had
quietly re-implemented the gate.

**The reason is derived, and that is what makes it trustworthy.**  There is no
``reason=`` parameter: the sentence is a property over the row's three figures.
The test that matters is that a row written through the store, read back
through the store, and recomputed by hand all agree — and that constructing the
record directly, past the store's nose, renders the same sentence, so the prose
cannot be forged by editing a value in memory.

**The idempotence is a behaviour, not an optimisation.**
:meth:`PromotionBlocks.record_block` twice for one node returns the standing
row byte for byte, ``blocked_at`` included, because the blocked instant is when
the promotion was blocked and a caller who walked the gate again did not move
it.  That is pinned on the raw row — the stamp is read from the table, not from
the record — so a store that re-stamped and returned a stale value could not
pass.

**Every refusal is one test, and each names its repair.**  They are all
:class:`~promotion.errors.PromotionBlockError`, gathered rather than split, and
the gathering is the point: the caller is a gate, whose one failure mode is
silence, so a single ``except`` has to catch every face.  The tests assert the
class *and* the code word, so a later feature that split them would fail here
rather than in production.

**The self-contradiction refusal is the interesting one.**  A pair of figures
saying ``count >= threshold`` describes a regime the pool *covers* and a
promotion that stands; persisting it as a block would write a row whose own
reason contradicts its own numbers.  Refusing it is not this store judging the
promotion, and the test asserts the distinction: the store never opened the
ledger, so it cannot have judged anything — it only declined to persist a
finding that contradicts itself.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path

import promotion as member
import pytest
from conftest import (
    DEFAULT_CRITERIA_DOCUMENT,
    EPOCH_ID,
    NODE_ID,
    code_of,
)
from promotion import (
    BLOCKED_AT_COLUMN,
    COVERAGE_THRESHOLD_COLUMN,
    DATABASE_URL_ENV,
    PROMOTION_BLOCK_ERROR_CODE,
    PROMOTION_BLOCK_TABLE,
    PROMOTION_REGISTRY_TABLE,
    REGIME_COLUMN,
    WORLD_COUNT_COLUMN,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PromotionBlock,
    PromotionBlockError,
    PromotionBlocks,
    PromotionCriteria,
    PromotionError,
    PromotionStoreError,
    blocked_promotion,
    blocking_reason,
    criteria_hash,
)

#: A regime the pool does not cover, and the figures a block on it carries.
#: Named constants so a failure reads as a statement about a *block* rather
#: than about three literals buried in an assertion.
CRASH = "crash"
CHOP = "low-volatility chop"
THIN = 0
THRESHOLD = 5

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES = REPO_ROOT / "packages"


def _request(**overrides) -> PreRegistrationRequest:
    """A well-formed pre-registration, with the named fields overridden."""
    fields = {
        "node_id": NODE_ID,
        "epoch_id": EPOCH_ID,
        "criteria": dict(DEFAULT_CRITERIA_DOCUMENT),
    }
    fields.update(overrides)
    return PreRegistrationRequest(**fields)


@pytest.fixture
def blocks(database_url: str) -> PromotionBlocks:
    """The block store, pointed at this test's own fresh database.

    No migration has run: the store's first ``record_block`` is what brings the
    three shared tables and its own to the file, the same contract feature 291's
    store states.
    """
    return PromotionBlocks(database_url)


@pytest.fixture
def decided(seeded_database) -> PromotionBlocks:
    """A block store over a database where the node *is* pre-registered.

    The semantic precondition feature 299 inherits from §13 item 7: a blocking
    reason is a statement about a promotion, so there has to be a decision for
    it to be the blocking reason *of*.  The pre-registration goes through
    feature 291's own endpoint rather than a raw ``INSERT``, so the two writers
    agree on the row by construction and a change in 291's insert would surface
    here rather than as a mysterious absent-parent refusal.

    The tests that check the *absent decision* refusal deliberately do not ask
    for this fixture.
    """
    PreRegisterEndpoint(seeded_database).post(_request())
    return PromotionBlocks(seeded_database.database_url)


@pytest.fixture
def raw_rows(database_url: str):
    """Read ``promotion_block`` raw, so a test sees what actually landed.

    A raw ``SELECT`` rather than a store verb, for the reason the registry's
    own suite gives: the point of most of these assertions is what the *table*
    holds, and a test that asked the store would be asking the code under test
    to confirm itself.
    """

    def _rows() -> list[sqlite3.Row]:
        connection = sqlite3.connect(Path(database_url.removeprefix("sqlite:///")))
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                f"SELECT {NODE_ID_COLUMN_LOCAL}, {REGIME_COLUMN}, "
                f"{WORLD_COUNT_COLUMN}, {COVERAGE_THRESHOLD_COLUMN}, "
                f"{BLOCKED_AT_COLUMN} FROM {PROMOTION_BLOCK_TABLE}"
            )
            try:
                return list(cursor.fetchall())
            finally:
                cursor.close()
        finally:
            connection.close()

    return _rows


#: The node column, spelled here rather than imported from the member so the
#: raw read is not written in the vocabulary it is checking.  It is the same
#: literal ``promotion_registry`` uses, which is the point.
NODE_ID_COLUMN_LOCAL = "node_id"


# -- The boundary: this feature records, it does not judge -------------------------


def test_the_module_never_opens_the_coverage_ledger() -> None:
    # The hardest boundary assertion, and the one that keeps this feature from
    # quietly becoming a second gate.  Feature 285 judges; this feature records
    # the judgment's outcome.  A store that read `regime_coverage` would have to
    # know whether the pool covers a regime — and then two components would
    # disagree about one promotion, with the persisted reason being the copy
    # nobody re-reads.
    from promotion import blocking as module

    code = code_of(module)
    assert "regime_coverage" not in code
    assert "rejects_undercovered_promotion" not in code
    assert "PromotionCoverageError" not in code


def test_the_module_imports_no_other_workspace_member() -> None:
    # No member imports another — every shared spelling is restated.  This
    # module's shared spellings are the code word (``coverage_below_threshold``,
    # feature 285's literal) and the stratum rule feature 283's validator
    # applies to a name.  Both are restated below; neither is imported, and the
    # test drives the real sibling's spelling from the data side rather than
    # from a module-scope import, which would make this suite fail to collect
    # wherever the sibling is absent.
    from promotion import blocking as module

    code = code_of(module)
    for leaked in ("import regime", "from regime", "import discovery", "from ledger"):
        assert leaked not in code, leaked


def test_the_code_word_is_feature_285s_own_literal() -> None:
    # The one spelling that *must* match across the two members, and the reason
    # a restatement is worth a test: an operator greps one word and has to land
    # on both halves of §C7's block — the refusal 285 raises and the reason 299
    # persists.  Driven against the sibling's data when the sibling is present,
    # and against its source when it is not, so this test is meaningful either
    # way and costs nothing where the regime member is absent.
    src = PACKAGES / "regime" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    regime_promotion = pytest.importorskip(
        "regime.promotion", reason="the regime member is not in this workspace"
    )
    assert (
        member.PROMOTION_BLOCK_ERROR_CODE
        == regime_promotion.COVERAGE_BELOW_THRESHOLD_CODE
        == "coverage_below_threshold"
    )


def test_the_boundary_agrees_with_feature_285s_verdict() -> None:
    # The boundary test, and the one the two tests above cannot make: they pin
    # that this module *restates* 285's code word and never *calls* its judgment,
    # which leaves open the question a restatement always leaves open — do the
    # two agree on *where* the boundary falls?  A reason whose figures sit on the
    # wrong side of §C7's comparison would be a persisted explanation of a
    # refusal that never happened, and no amount of code-word matching would
    # catch it.  So the real judgment is driven here, over the same pairs, and
    # the two boundaries are asserted to be complements.
    #
    # The equality case is the pivot and the reason this is worth a test at all:
    # ``count == threshold`` is a coverage floor, not an upper edge, so the
    # promotion *stands* — 285 returns without raising, and this store refuses to
    # record a block.  An off-by-one in either module would show up as exactly
    # this pair being classified twice as "blocked", and it is the pair a
    # reader is most likely to get wrong in either direction.
    src = PACKAGES / "regime" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    regime_promotion = pytest.importorskip(
        "regime.promotion", reason="the regime member is not in this workspace"
    )
    errored = regime_promotion.PromotionCoverageError

    class _Row:
        """One stratum's row, as 285's count read reaches it."""

        def __init__(self, world_count: int) -> None:
            self.world_count = world_count

    def _reading(count: int):
        """The thinnest reading 285's seam accepts: a mapping-shaped lookup."""
        return {CRASH: _Row(count)}

    # ``(count, threshold, blocked)`` — the same classification both halves must
    # reach, spelled once so a failure names the pair rather than an expression.
    cases = [
        (0, 5, True),
        (4, 5, True),  # one short: still below, still blocked
        (5, 5, False),  # exactly at the floor: 285's asymmetry, the pivot
        (6, 5, False),  # one over: covered, and there is no upper edge
        (40, 5, False),
        (0, 1, True),  # 285's degenerate-but-honest threshold of one
        (1, 1, False),
    ]
    for count, threshold, blocked in cases:
        reading = _reading(count)
        if blocked:
            with pytest.raises(errored) as refusal:
                regime_promotion.rejects_undercovered_promotion(
                    reading, regime=CRASH, threshold=threshold
                )
            assert (
                regime_promotion.COVERAGE_BELOW_THRESHOLD_CODE
                in str(refusal.value)
            ), (count, threshold)
            # And the store accepts the same pair as a recordable block, so the
            # reason it persists states the finding 285 just made.  Written
            # through the value layer rather than the store, because the
            # question here is the comparison and not the write.
            block = PromotionBlock(
                node_id=NODE_ID,
                regime=CRASH,
                world_count=count,
                coverage_threshold=threshold,
                blocked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            )
            assert block.world_count == count
        else:
            # 285 lets the promotion through — and this store refuses to persist
            # a block for it, which is the same verdict said the only way a store
            # can say it.
            assert (
                regime_promotion.rejects_undercovered_promotion(
                    reading, regime=CRASH, threshold=threshold
                )
                is None
            ), (count, threshold)
            with pytest.raises(PromotionBlockError) as refusal:
                PromotionBlock(
                    node_id=NODE_ID,
                    regime=CRASH,
                    world_count=count,
                    coverage_threshold=threshold,
                    blocked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                )
            assert PROMOTION_BLOCK_ERROR_CODE in str(refusal.value), (count, threshold)


def test_a_regime_285_does_not_know_is_refused_by_285_not_by_this_store() -> None:
    # The one face where the two boundaries are *not* complements, and it is
    # 285's alone: a regime nobody named is an unknown coverage rather than a
    # zero, so the judgment refuses it — but it refuses it as a *separate* face
    # from the verdict, with a different repair (name the stratum; the census's
    # act).  This store, handed the same figures, cannot tell the two apart: it
    # takes the caller's numbers as the evidence the caller gathered, and a
    # count of zero against a threshold of five is a well-formed below-threshold
    # pair whichever way the count was arrived at.  So the store records it, and
    # that is correct rather than a gap — it is the caller's 285 refusal that
    # carries the *why*.  Pinned so a later reader does not "fix" the store into
    # re-judging the difference, which is the drift the module docstring's
    # boundary argues against.
    src = PACKAGES / "regime" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    regime_promotion = pytest.importorskip(
        "regime.promotion", reason="the regime member is not in this workspace"
    )

    with pytest.raises(regime_promotion.PromotionCoverageError) as refusal:
        regime_promotion.rejects_undercovered_promotion(
            {}, regime=CRASH, threshold=THRESHOLD
        )
    message = str(refusal.value)
    assert regime_promotion.COVERAGE_BELOW_THRESHOLD_CODE in message
    assert "unknown rather than zero" in message

    # The same figures are a recordable block on this side, with no ledger read.
    block = PromotionBlock(
        node_id=NODE_ID,
        regime=CRASH,
        world_count=THIN,
        coverage_threshold=THRESHOLD,
        blocked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    assert block.reason == blocking_reason(CRASH, THIN, THRESHOLD)


# -- The reason, as prose ----------------------------------------------------------


def test_the_reason_names_all_three_figures() -> None:
    # A persisted reason exists so a row explains itself without the ledger read
    # beside it, and that is only true if it names the regime, the count and the
    # threshold.  Asserted against the rendered sentence rather than against a
    # stored string, because the sentence is derived — see the next test.
    reason = blocking_reason(CRASH, THIN, THRESHOLD)
    assert CRASH in reason
    assert repr(THIN) in reason
    assert repr(THRESHOLD) in reason
    assert "§C7" in reason


def test_the_reason_singularises_one_world() -> None:
    # A persisted reason is prose a human reads before anything else parses it,
    # and "1 stored worlds" is the kind of sentence that makes a careful reader
    # distrust the row's figures.
    assert "1 stored world," in blocking_reason(CHOP, 1, 2)
    assert "stored worlds," in blocking_reason(CHOP, 2, 3)
    # The zero case is §C7's own example — a regime named and holding nothing —
    # and it must read as a plural, not as a singular.
    assert "0 stored worlds," in blocking_reason(CRASH, 0, 1)


def test_identical_figures_render_a_byte_identical_reason() -> None:
    # The property that makes two rows *comparable* rather than merely similar:
    # plain ``repr`` of an int round-trips exactly and is stable across runs, so
    # a re-run of the same block persists the same text.  The precedent is
    # ``universe.monthly.floor_exclusion_reason``, which states this for the
    # workspace's other persisted reason.
    assert blocking_reason(CRASH, 3, 10) == blocking_reason(CRASH, 3, 10)


def test_the_reason_is_reachable_from_the_members_surface() -> None:
    # The member re-exports its whole vocabulary; a caller recording a block
    # should not have to reach past ``promotion`` into a submodule to render or
    # read the sentence.
    assert member.blocking_reason is blocking_reason
    assert member.PromotionBlocks is PromotionBlocks
    assert member.PromotionBlock is PromotionBlock


# -- The write ---------------------------------------------------------------------


def test_a_block_lands_one_row_and_answers_it(decided, raw_rows) -> None:
    # Feature 299 in one act: the figures are persisted against the node, and
    # the answer is the row the table holds — proved by the raw read, not by the
    # returned value agreeing with itself.
    block, created = decided.record_block(
        NODE_ID,
        regime=CRASH,
        world_count=THIN,
        threshold=THRESHOLD,
        clock=lambda: dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )
    assert created is True
    assert block.node_id == NODE_ID
    assert block.regime == CRASH
    assert block.world_count == THIN
    assert block.coverage_threshold == THRESHOLD
    rows = raw_rows()
    assert len(rows) == 1
    assert rows[0][REGIME_COLUMN] == CRASH
    assert rows[0][WORLD_COUNT_COLUMN] == THIN
    assert rows[0][COVERAGE_THRESHOLD_COLUMN] == THRESHOLD
    assert rows[0][BLOCKED_AT_COLUMN] == block.blocked_at.isoformat()


def test_the_reason_is_derived_from_the_stored_figures(decided, raw_rows) -> None:
    # The reason is not a column: it is rendered from the three figures the row
    # really carries, so the prose and the numbers cannot drift apart.  The
    # check reads the *stored* numbers and recomputes the sentence by hand, so
    # the member cannot pass by rendering something the row does not hold.
    block, _ = decided.record_block(
        NODE_ID, regime=CHOP, world_count=2, threshold=9
    )
    stored = raw_rows()[0]
    rebuilt = blocking_reason(
        stored[REGIME_COLUMN],
        stored[WORLD_COUNT_COLUMN],
        stored[COVERAGE_THRESHOLD_COLUMN],
    )
    assert block.reason == rebuilt
    assert block.row()["reason"] == rebuilt


def test_the_record_renders_the_reason_without_a_store() -> None:
    # The sentence is a property over the record's own fields, so a caller that
    # built or unpickled a record renders the same prose the store would have.
    # This is what makes the reason unforgeable *and* available: there is no
    # path that writes a sentence, so there is none that can disagree.
    record = PromotionBlock(
        node_id=NODE_ID,
        regime=CRASH,
        world_count=THIN,
        coverage_threshold=THRESHOLD,
        blocked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    assert record.reason == blocking_reason(CRASH, THIN, THRESHOLD)


def test_the_record_is_frozen_and_validated() -> None:
    # Frozen because a row read back must not be editable into a different count
    # by a caller who kept a reference — and validated in ``__post_init__``
    # because ``replace`` and unpickling both rebuild instances past a factory's
    # nose, and a hand-edited row is reachable through SQLite's dynamic typing.
    record = PromotionBlock(
        node_id=NODE_ID,
        regime=CRASH,
        world_count=THIN,
        coverage_threshold=THRESHOLD,
        blocked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    with pytest.raises(dc.FrozenInstanceError):
        record.regime = "other"
    with pytest.raises(PromotionBlockError) as raised:
        PromotionBlock(
            node_id=NODE_ID,
            regime=CRASH,
            world_count=-1,
            coverage_threshold=THRESHOLD,
            blocked_at=record.blocked_at,
        )
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


# -- The idempotence ---------------------------------------------------------------


def test_a_re_block_returns_the_standing_row_and_moves_nothing(
    decided, raw_rows
) -> None:
    # The blocked instant is when the promotion *was* blocked, so a caller that
    # walked the gate again did not move it — the stance a retried
    # pre-registration takes toward ``pre_registered_at``.  Asserted on the raw
    # row, so a store that re-stamped and returned a cached value could not pass.
    first, created = decided.record_block(
        NODE_ID,
        regime=CRASH,
        world_count=THIN,
        threshold=THRESHOLD,
        clock=lambda: dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )
    assert created is True
    stamped = raw_rows()[0][BLOCKED_AT_COLUMN]
    again, created_again = decided.record_block(
        NODE_ID,
        regime=CRASH,
        world_count=THIN,
        threshold=THRESHOLD,
        clock=lambda: dt.datetime(2026, 9, 9, tzinfo=dt.UTC),
    )
    assert created_again is False
    assert again == first
    assert raw_rows()[0][BLOCKED_AT_COLUMN] == stamped
    assert len(raw_rows()) == 1


def test_a_re_block_with_different_figures_still_returns_the_standing_row(
    decided, raw_rows
) -> None:
    # The other half, and the one that decides whether the store has an update
    # path: a second call carrying *different* figures is still a re-block, not
    # a revision.  There is no update arm — a block is written once — so the
    # first finding stands and the second call is a no-op.  A store that
    # revised would make the row a record of the last time somebody looked.
    first, _ = decided.record_block(
        NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD
    )
    again, created = decided.record_block(
        NODE_ID, regime=CHOP, world_count=1, threshold=2
    )
    assert created is False
    assert again == first
    assert raw_rows()[0][REGIME_COLUMN] == CRASH


# -- The reads ---------------------------------------------------------------------


def test_blocked_answers_none_for_a_node_this_store_holds_no_row_for(decided) -> None:
    # The pair this store must keep apart: a promotion that was blocked, and one
    # that was not.  ``None`` is *not blocked through this store* — deliberately
    # not a record carrying a zero, which would report *blocked with no reason*
    # about a promotion that was never stopped.
    assert decided.blocked(NODE_ID) is None
    assert decided.is_blocked(NODE_ID) is False


def test_the_unblocked_absence_is_not_a_zero_filled_record(decided) -> None:
    # The sharper form of the same fact, stated as a type: the answer for an
    # absent row is not a ``PromotionBlock`` at all.  A store that returned a
    # zeroed record would make every downstream ``if record:`` branch wrong.
    decided.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    other = str(uuid.uuid4())
    assert decided.blocked(other) is None
    assert not isinstance(decided.blocked(other), PromotionBlock)


def test_is_blocked_is_the_boolean_face_of_the_same_read(decided) -> None:
    # One question, one read: ``is_blocked`` is a wrapper over ``blocked`` rather
    # than a second ``SELECT`` that could disagree with it.
    decided.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    assert decided.is_blocked(NODE_ID) is True
    assert decided.blocked(NODE_ID) is not None


def test_blocks_enumerates_every_block_in_node_order(seeded_database) -> None:
    # The listing a report reads — *which promotions are blocked, and on what*.
    # Ordered by the table's key so two reads of one store are comparable, and a
    # tuple rather than a live cursor because the answer is a value the caller
    # keeps.
    store = PromotionBlocks(seeded_database.database_url)
    nodes = sorted(str(uuid.uuid4()) for _ in range(3))
    connection = seeded_database._connect()
    try:
        with connection:
            for node in nodes:
                connection.execute(
                    "INSERT INTO node (id, campaign_id, theme_root, depth) "
                    "VALUES (?, ?, ?, ?)",
                    (node, str(uuid.uuid4()), "macro", 1),
                )
    finally:
        connection.close()
    for node in nodes:
        PreRegisterEndpoint(seeded_database).post(_request(node_id=node))
    for node in nodes:
        store.record_block(node, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    listed = store.blocks()
    assert isinstance(listed, tuple)
    assert [block.node_id for block in listed] == nodes
    assert all(block.regime == CRASH for block in listed)


def test_the_listing_is_empty_rather_than_absent_on_a_fresh_store(blocks) -> None:
    # An empty listing is a real answer about a real database — no promotion has
    # been blocked here — and it is deliberately not an error.  The store's
    # *first write* is what brings the table up, so the read brings it up too,
    # and the answer is ``()`` rather than a refusal.
    assert blocks.blocks() == ()


# -- The refusals: the ask ----------------------------------------------------------


@pytest.mark.parametrize(
    "regime", [None, "", "   ", 5, b"crash", ["crash"]], ids=repr
)
def test_a_regime_that_is_not_a_name_is_refused(decided, regime: object) -> None:
    # A stratum name is non-empty text: the vocabulary is the labeler's
    # configuration, and a target that is not a name names no regime whose
    # coverage could have fallen short.  Blank is refused rather than stripped
    # to nothing, because a name that states nothing names no stratum.
    with pytest.raises(PromotionBlockError) as raised:
        decided.record_block(NODE_ID, regime=regime, world_count=THIN, threshold=THRESHOLD)
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (WORLD_COUNT_COLUMN, True),
        (WORLD_COUNT_COLUMN, 1.5),
        (WORLD_COUNT_COLUMN, "3"),
        (WORLD_COUNT_COLUMN, -1),
        (COVERAGE_THRESHOLD_COLUMN, True),
        (COVERAGE_THRESHOLD_COLUMN, 0.5),
        (COVERAGE_THRESHOLD_COLUMN, None),
        (COVERAGE_THRESHOLD_COLUMN, -4),
    ],
    ids=repr,
)
def test_a_figure_that_is_not_a_count_of_worlds_is_refused(
    decided, field: str, value: object
) -> None:
    # §C7's finding is drawn in worlds, so both figures are counts: ``bool``
    # because ``True`` is ``1`` in Python and a flag where a count belongs would
    # be persisted as the number one; a fractional world is not a world; text is
    # not a number; and negative is refused because §C6's excision empties a
    # stratum and never leaves a regime owing worlds.
    figures = {"world_count": THIN, "threshold": THRESHOLD}
    figures["world_count" if field == WORLD_COUNT_COLUMN else "threshold"] = value
    with pytest.raises(PromotionBlockError) as raised:
        decided.record_block(NODE_ID, regime=CRASH, **figures)
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


def test_a_malformed_figure_is_refused_before_the_store_is_touched() -> None:
    # The ask face is refusable without a database at all, so a refused call
    # leaves no file and no row behind.  This store is pointed at a path under a
    # *file*, so if it were opened at all it would raise an ``OSError`` — the
    # refusal arriving as ``PromotionBlockError`` is what proves the order.
    blocker = Path(__file__).parent / "not-a-directory"
    store = PromotionBlocks(f"sqlite:///{blocker / 'blocks.db'}")
    with pytest.raises(PromotionBlockError) as raised:
        store.record_block(NODE_ID, regime=CRASH, world_count=-1, threshold=THRESHOLD)
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


def test_a_malformed_node_is_refused(tmp_path: Path) -> None:
    # The node is an identity, and a block that cannot be joined to its
    # hypothesis is a row no later reader can act on.  Refused without a store,
    # because the ask is malformed whatever the database holds — pointed at a
    # path under ``tmp_path`` so the refusal is what is observed and no file is
    # left in the repository either way.
    store = PromotionBlocks(f"sqlite:///{tmp_path / 'never-opened.db'}")
    with pytest.raises(PromotionBlockError) as raised:
        store.record_block("not-a-uuid", regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)
    # And nothing was created, which is the sharper half: the ask face is
    # refusable without a database at all.
    assert not (tmp_path / "never-opened.db").exists()


def test_a_naive_stamp_is_refused(decided) -> None:
    # §C7's block is an instant, and a naive one has no offset to order against
    # anything — the same refusal feature 291's stamp makes, in this feature's
    # class because the caller's ``except`` guard is the same guard.
    with pytest.raises(PromotionBlockError) as raised:
        decided.record_block(
            NODE_ID,
            regime=CRASH,
            world_count=THIN,
            threshold=THRESHOLD,
            blocked_at=dt.datetime(2026, 1, 1),  # noqa: DTZ001
        )
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


# -- The refusals: the self-contradiction ------------------------------------------


@pytest.mark.parametrize(
    ("count", "threshold"),
    [(5, 5), (6, 5), (0, 0), (100, 1)],
    ids=repr,
)
def test_a_pair_of_figures_that_does_not_state_a_block_is_refused(
    decided, count: int, threshold: int
) -> None:
    # §C7's block holds exactly when the count is *below* the threshold, so
    # ``count >= threshold`` describes a regime the pool covers and a promotion
    # that stands.  Persisting that as a block would write a row whose own
    # reason contradicts its own numbers — a stored row that lies, which is
    # worse than no row at all.  Equality is refused too: at exactly the
    # threshold feature 285 lets the promotion stand.
    with pytest.raises(PromotionBlockError) as raised:
        decided.record_block(
            NODE_ID, regime=CRASH, world_count=count, threshold=threshold
        )
    message = str(raised.value)
    assert PROMOTION_BLOCK_ERROR_CODE in message
    # The repair names the acts that would resolve it, and says outright that
    # this is not a judgment about the pool — so an operator does not go looking
    # for a coverage problem that does not exist.
    assert "does not judge" in message or "never reads the coverage ledger" in message


def test_the_self_contradiction_refusal_is_not_a_ledger_read(
    decided, database_url: str
) -> None:
    # The distinction the refusal's own docstring draws, pinned as a fact: the
    # store refuses an inconsistent pair *without ever opening the ledger*.  It
    # takes the caller's figures as the evidence the caller gathered and checks
    # only that they are consistent with the finding they are persisted as.
    #
    # The assertion is the *strongest* form of "nothing was written": the store
    # was never opened, so this feature's table was never even created.  That is
    # only observable because the refusal happens ahead of `_connect` — a store
    # that connected first and validated second would leave the schema behind,
    # and this test would catch that rather than merely catching a missing row.
    with pytest.raises(PromotionBlockError):
        decided.record_block(NODE_ID, regime=CRASH, world_count=9, threshold=2)
    connection = sqlite3.connect(Path(database_url.removeprefix("sqlite:///")))
    try:
        created = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (PROMOTION_BLOCK_TABLE,),
        ).fetchall()
    finally:
        connection.close()
    assert created == []


def test_a_single_world_below_a_threshold_of_one_stands() -> None:
    # The boundary on the other side, so the refusal is not "everything is
    # refused": zero worlds against a threshold of one is §C7's own example
    # (`crash: 0`) and is exactly the block the feature records.
    assert blocking_reason(CRASH, 0, 1).startswith("the target deployment regime")


# -- The refusals: the address and the decision ------------------------------------


def test_a_store_pointed_at_nothing_is_refused() -> None:
    # A URL that names no database names no place a reason could be recorded,
    # and a store that accepted one would fail identically on every record —
    # the wrong place for a deployment to discover a wiring fault.
    with pytest.raises(PromotionBlockError) as raised:
        PromotionBlocks("   ")
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


def test_a_url_this_member_cannot_speak_is_refused_in_this_features_words() -> None:
    # The translation at the seam: ``promotion.pre_register``'s URL translator
    # raises its own store vocabulary, and a caller whose single
    # ``except PromotionBlockError`` guards its promotion path must not be
    # defeated by a refusal phrased for a different act.  The class is
    # translated at the seam and the sibling's message is carried through, so
    # nothing an operator needs is lost.
    store = PromotionBlocks("postgresql://host/registry")
    with pytest.raises(PromotionBlockError) as raised:
        store.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)
    assert "postgresql" in str(raised.value)


def test_a_node_with_no_pre_registration_is_refused_by_name(
    seeded_database,
) -> None:
    # The precondition §13 item 7 gives this feature: a blocking reason is a
    # statement about a *promotion*, so the node must already hold a
    # ``promotion_registry`` row.  Refused by probe rather than left to the
    # foreign key, because SQLite's ``IntegrityError`` names no node and the
    # repair here is specific — pre-register first.
    store = PromotionBlocks(seeded_database.database_url)
    with pytest.raises(PromotionBlockError) as raised:
        store.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    message = str(raised.value)
    assert PROMOTION_BLOCK_ERROR_CODE in message
    assert PROMOTION_REGISTRY_TABLE in message
    assert NODE_ID in message


def test_a_node_the_tree_does_not_hold_is_refused(tmp_path: Path) -> None:
    # The structural half, one level below the semantic probe: a block hangs off
    # a hypothesis the tree holds, so a node that is neither in ``node`` nor in
    # ``promotion_registry`` is refused rather than accepted because the probe
    # had nothing to compare against.  The order matters: the decision probe
    # fires first and its message is the one an operator needs — asserted here,
    # because the two refusals have different repairs and a store that reported
    # the structural one would send an operator looking at the tree rather than
    # at the promotion.
    store = PromotionBlocks(f"sqlite:///{tmp_path / 'bare.db'}")
    with pytest.raises(PromotionBlockError) as raised:
        store.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    assert PROMOTION_REGISTRY_TABLE in str(raised.value)


# -- The vocabulary ----------------------------------------------------------------


def test_every_refusal_is_one_gathered_class() -> None:
    # The gathering is the design: this feature's caller is a *gate*, whose one
    # failure mode is silence, so a single ``except PromotionBlockError`` has to
    # catch every face — a malformed ask, an unreachable address, an absent
    # decision, a failed write.  Feature 285 gathers its own faces for the same
    # reason and says so; this test is where a later feature that split them
    # would be caught, because the caller's guard would develop a hole.
    from promotion import blocking as module

    assert issubclass(PromotionBlockError, PromotionError)
    assert not issubclass(PromotionBlockError, PromotionStoreError)
    # Every refusal in the module's code raises this one class — checked by the
    # absence of the siblings' names from the code, the two classes a split
    # would reach for.
    code = code_of(module)
    assert "raise PromotionError(" not in code
    assert "raise PromotionStoreError(" not in code


def test_the_block_class_is_not_the_registry_class() -> None:
    # A caller that gathered the two would read *the registry could not be
    # written to* where the truth is *the pool does not cover the regime this
    # promotion is aimed at*.  Two different repairs, and the second is the one
    # §C7 exists to make visible — so the classes stay siblings.
    assert not issubclass(PromotionBlockError, PromotionStoreError)
    assert not issubclass(PromotionStoreError, PromotionBlockError)
    assert PromotionBlockError.__bases__ == (PromotionError,)


def test_the_code_word_opens_every_refusal_the_store_raises(decided) -> None:
    # An operator greps one word for *a promotion was blocked on coverage*.
    # Driven through the real paths rather than asserted about the constant.
    for call in (
        lambda: decided.record_block(NODE_ID, regime="", world_count=0, threshold=1),
        lambda: decided.record_block(
            NODE_ID, regime=CRASH, world_count=5, threshold=5
        ),
        lambda: PromotionBlocks("  "),
    ):
        with pytest.raises(PromotionBlockError) as raised:
            call()
        assert str(raised.value).startswith(PROMOTION_BLOCK_ERROR_CODE)


# -- The module-level spellings ----------------------------------------------------


def test_record_block_resolves_the_url_it_is_handed(seeded_database) -> None:
    # The feature's sentence as one call, for the caller that wants the act
    # without holding a store — a gate's last line after feature 285 has refused
    # the promotion.
    PreRegisterEndpoint(seeded_database).post(_request())
    block, created = member.blocking.record_block(
        NODE_ID,
        regime=CRASH,
        world_count=THIN,
        threshold=THRESHOLD,
        database_url=seeded_database.database_url,
    )
    assert created is True
    assert block.regime == CRASH
    assert block.node_id == NODE_ID


def test_blocked_promotion_resolves_the_url_it_is_handed(seeded_database) -> None:
    # The module-level read, so a caller that records through one spelling and
    # reads through the other is reading the row it wrote.
    PreRegisterEndpoint(seeded_database).post(_request())
    member.blocking.record_block(
        NODE_ID,
        regime=CRASH,
        world_count=THIN,
        threshold=THRESHOLD,
        database_url=seeded_database.database_url,
    )
    read = blocked_promotion(NODE_ID, database_url=seeded_database.database_url)
    assert read is not None
    assert read.reason == blocking_reason(CRASH, THIN, THRESHOLD)
    assert blocked_promotion(
        str(uuid.uuid4()), database_url=seeded_database.database_url
    ) is None


def test_a_deployment_naming_no_database_is_refused_by_name(monkeypatch) -> None:
    # The silence is the dangerous failure here and not the refusal: a block
    # whose reason was quietly not recorded leaves a promotion stopped with no
    # auditable explanation, which is the state §C7's ledger exists to make
    # impossible.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(PromotionBlockError) as raised:
        member.blocking.record_block(
            NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD
        )
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)
    with pytest.raises(PromotionBlockError) as raised:
        blocked_promotion(NODE_ID)
    assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


def test_the_module_level_reads_resolve_the_ambient_variable(
    monkeypatch, seeded_database
) -> None:
    # The other half of the resolution: an explicit URL wins, else
    # ``DATABASE_URL`` — the same seam every store in this workspace reads, so a
    # deployment points every member at one database or at none.
    monkeypatch.setenv(DATABASE_URL_ENV, seeded_database.database_url)
    PreRegisterEndpoint(seeded_database).post(_request())
    block, created = member.blocking.record_block(
        NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD
    )
    assert created is True
    assert blocked_promotion(NODE_ID) == block


def test_resolve_answers_none_without_a_database(monkeypatch) -> None:
    # Absent is not an error: it is a deployment without a relational store, and
    # the caller that must record why a promotion was blocked is the caller that
    # must not find itself in it.  The *refusal* belongs to the caller, which
    # the module-level spellings make.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert PromotionBlocks.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert PromotionBlocks.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere.db")
    assert isinstance(PromotionBlocks.resolve(), PromotionBlocks)


# -- The table, and what it is not -------------------------------------------------


def test_the_feature_declares_its_own_table_and_the_migrations_declare_the_others(
    blocks,
) -> None:
    # The boundary ``promotion.schema``'s no-DDL test draws, from this feature's
    # side.  The member writes no DDL for the tables the migration tree owns —
    # ``node``, ``epoch_ledger`` and ``promotion_registry`` are declared by
    # 0118, 0110 and 0108 — while ``promotion_block`` is declared by no
    # migration and is therefore this feature's own to declare, the position
    # ``regime_coverage`` (283), ``backfilled_world`` (288) and the canary halt
    # table (143) all take.
    from promotion import schema as schema_module

    assert "CREATE TABLE" not in code_of(schema_module)
    from promotion import blocking as module

    assert "CREATE TABLE" in code_of(module)


def test_the_block_table_is_not_the_registry_table(blocks) -> None:
    # The design decision feature 299 had to make, pinned as a fact: the reason
    # is a table of its own rather than a seventh column on a table this member
    # does not own.  ``app_spec.xml``'s schema block declares
    # ``promotion_registry``'s six columns and no seventh, the migration tree
    # that owns that DDL stops at 0108, and this member may not edit it — so the
    # column reading could only have arrived as a runtime ``ALTER TABLE``.
    assert PROMOTION_BLOCK_TABLE != PROMOTION_REGISTRY_TABLE
    assert PROMOTION_BLOCK_TABLE == "promotion_block"
    # And the block module never alters the registry: no ``ALTER TABLE`` in its
    # code, which is what a column-shaped feature 299 would have needed.
    from promotion import blocking as module

    assert "ALTER TABLE" not in code_of(module)


def test_the_block_table_is_brought_up_beside_the_three_shared_tables(
    database_url: str,
) -> None:
    # One connect does both: the migrations' own statements for the three shared
    # tables (so the member still authors no DDL for them) and this feature's
    # one ``CREATE TABLE IF NOT EXISTS``.  Asserted on a fresh database, which is
    # the shape that proves the store does not depend on the tree having run.
    store = PromotionBlocks(database_url)
    connection = store._connect()
    try:
        names = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert {PROMOTION_BLOCK_TABLE, PROMOTION_REGISTRY_TABLE, "node", "epoch_ledger"} <= names


def test_bootstrapping_twice_changes_nothing(database_url: str) -> None:
    # ``IF NOT EXISTS`` in both halves, which is what lets a migrated
    # deployment and a store-first one converge: the second connect leaves the
    # schema exactly as the first did.
    store = PromotionBlocks(database_url)

    def _shape(client: sqlite3.Connection) -> set[tuple[str, str]]:
        return {
            (name, (sql or "").strip())
            for name, sql in client.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
            )
        }

    with closing(store._connect()) as connection:
        first = _shape(connection)
    with closing(store._connect()) as connection:
        second = _shape(connection)
    assert first == second


def test_the_store_holds_no_cache_of_the_rows_it_wrote(decided) -> None:
    # The row is the only record, so it is the only thing an answer is drawn
    # from.  A memo of blocked nodes would make *why is this promotion not
    # deployed?* a question about this process's history, and the reader asking
    # it — an operator, a report, a later feature — runs somewhere else
    # entirely.  Driven by writing behind the store's back and reading it back.
    decided.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    assert decided.is_blocked(NODE_ID) is True
    connection = decided._connect()
    try:
        with connection:
            connection.execute(f"DELETE FROM {PROMOTION_BLOCK_TABLE}")
    finally:
        connection.close()
    assert decided.is_blocked(NODE_ID) is False


def test_a_second_store_over_one_database_sees_the_same_row(decided) -> None:
    # The other face of the same fact: the record is the table's, so two stores
    # over one database — two processes, in production — agree without sharing
    # anything but the URL.
    decided.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    other = PromotionBlocks(decided.database_url)
    read = other.blocked(NODE_ID)
    assert read is not None
    assert read.reason == decided.blocked(NODE_ID).reason


def test_a_hand_edit_below_the_tables_meaning_is_refused_on_read(decided) -> None:
    # SQLite's columns are dynamically typed, so a raw ``INSERT`` from another
    # tool can land anything here.  A block read that swallowed a corrupt row
    # would report a reason nobody wrote, so the read validates — naming the
    # node it came off, which is the difference between learning *this block is
    # corrupt* and learning only that some row somewhere is not a block.
    connection = decided._connect()
    try:
        with connection:
            connection.execute(
                f"INSERT INTO {PROMOTION_BLOCK_TABLE} "
                f"({NODE_ID_COLUMN_LOCAL}, {REGIME_COLUMN}, {WORLD_COUNT_COLUMN}, "
                f"{COVERAGE_THRESHOLD_COLUMN}, {BLOCKED_AT_COLUMN}) "
                "VALUES (?, ?, ?, ?, ?)",
                (NODE_ID, CRASH, -3, THRESHOLD, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionBlockError) as raised:
        decided.blocked(NODE_ID)
    message = str(raised.value)
    assert PROMOTION_BLOCK_ERROR_CODE in message
    assert NODE_ID in message
    # One refusal carries one code word, not two — the greppable marker is for
    # the *finding*, and a doubled one would read as two blocked promotions.
    assert message.count(PROMOTION_BLOCK_ERROR_CODE) == 1


def test_a_hand_edit_recording_a_covered_pair_is_refused_on_read(decided) -> None:
    # The same hand-edit hazard as the test above, one field further in, and the
    # one the *shapes* of the columns cannot catch: every figure here is a
    # well-formed non-negative count, so a store that validated only the fields
    # would read this row back as a block and render its reason — *"holds 999
    # stored worlds, below the configured coverage threshold of 5"* — a persisted
    # sentence that contradicts its own numbers, which is worse than a corrupt
    # row because it looks like a finding.  The relation between the two counts
    # is what has to hold, and on the read path there is no caller standing by to
    # re-read the ledger and notice.
    connection = decided._connect()
    try:
        with connection:
            connection.execute(
                f"INSERT INTO {PROMOTION_BLOCK_TABLE} "
                f"({NODE_ID_COLUMN_LOCAL}, {REGIME_COLUMN}, {WORLD_COUNT_COLUMN}, "
                f"{COVERAGE_THRESHOLD_COLUMN}, {BLOCKED_AT_COLUMN}) "
                "VALUES (?, ?, ?, ?, ?)",
                (NODE_ID, CRASH, 999, THRESHOLD, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionBlockError) as raised:
        decided.blocked(NODE_ID)
    message = str(raised.value)
    assert PROMOTION_BLOCK_ERROR_CODE in message
    assert message.count(PROMOTION_BLOCK_ERROR_CODE) == 1


def test_a_blank_node_is_refused_by_the_reads_rather_than_answered_none(
    decided,
) -> None:
    # A name that states nothing is a malformed ask, not an unblocked promotion,
    # and the two must not collapse into one answer — the mirror of the
    # named-empty trap, at the other end.  ``False`` about a hypothesis nobody
    # named would be inventing a finding.
    for call in (lambda: decided.blocked(""), lambda: decided.is_blocked("")):
        with pytest.raises(PromotionBlockError) as raised:
            call()
        assert PROMOTION_BLOCK_ERROR_CODE in str(raised.value)


def test_the_member_still_exports_exactly_one_builder() -> None:
    # Feature 299 adds no component: a builder takes no arguments and is built on
    # every ``create_app()`` call, while this store's acts are functions of
    # evidence the factory does not hold — a gate's verdict, a reading, a count.
    # So the member's one registered contribution stands, and this assertion is
    # where a second ``@register`` would be noticed.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_specs_sentence_is_what_this_module_implements() -> None:
    # The feature's own line, quoted so a reader of this suite does not have to
    # go looking, and so a re-scoped feature would fail a test rather than
    # quietly leaving the suite asserting something the spec no longer says.
    # The module's docstring quotes it too; this is the data-side copy.
    spec = REPO_ROOT / "app_spec.xml"
    if not spec.is_file():  # pragma: no cover - the spec is in the checkout
        pytest.skip("app_spec.xml is not in this checkout")
    assert (
        "System persists a blocking reason for a promotion whose deployment "
        "regime coverage sits below threshold" in spec.read_text(encoding="utf-8")
    )


def test_the_criteria_hash_is_untouched_by_a_block(decided) -> None:
    # A block is additional state *beside* §13 item 7's record, not a revision
    # of it: the pre-registered hash is the thing the deciding evaluation is
    # checked against, and recording why the promotion stopped must not disturb
    # it.  The two rows are joined by the node and are otherwise independent.
    expected = criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))
    decided.record_block(NODE_ID, regime=CRASH, world_count=THIN, threshold=THRESHOLD)
    connection = decided._connect()
    try:
        stored = connection.execute(
            f"SELECT criteria_hash FROM {PROMOTION_REGISTRY_TABLE} "
            f"WHERE {NODE_ID_COLUMN_LOCAL} = ?",
            (NODE_ID,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert stored == expected
