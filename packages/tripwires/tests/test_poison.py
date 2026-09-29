"""Feature 131 — a tripwire failure, persisted as a poisoned subtree.

app_spec.xml: *"System persists a tripwire failure as poisoning the node
together with its entire subtree."*  The suite is organised around the two
claims that sentence makes, because each is separately falsifiable and the
feature is only correct when both hold:

* **the subtree** — a failure at a node marks that node *and every node beneath
  it*, and nothing else.  Not the node alone (which leaves the branch's scores
  in the replay pool), not the whole campaign (which excises unrelated
  branches), not a neighbouring campaign's node.  The tests walk a chain, a
  branching tree and a two-campaign database to pin all three edges of that.
* **persisted** — the mark lands on the tree the replay path reads
  (``node.poisoned_at``) and the failure lands in a record that explains itself
  (``tripwire_poison``), both surviving the process that wrote them.  A mark
  that lived only in the verdict would be a fact nobody downstream could act
  on, which is the whole reason this feature exists apart from feature 125.

The rest of the suite is the scaffolding that keeps those two honest: that the
feature refuses to poison on anything but a failure that happened, that a
re-run is idempotent (the act is irreversible, so a retry must not be a second
act), and that every refusal names what is wrong rather than raising something
a caller cannot act on.

Nothing here re-tests feature 125.  The panels come from the probe's own
builders (:mod:`_panels`), the leak is the probe's canonical one, and a test
that needs a verdict *gets it by running the probe* — so a change to the
probe's arithmetic shows up here as a changed premise rather than as a silent
pass.  :func:`_failure` asserts its own premise for exactly that reason.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid

import pytest
from _panels import gaussian_panel, lookahead_panel, monday
from _trees import seed_campaign, seed_tree
from tripwires import (
    NODE_POISONED_COLUMN,
    NODE_TABLE,
    POISON_COMPONENT_NAME,
    POISON_TABLE,
    PoisonedSubtree,
    PoisonRecord,
    TripwirePoisonError,
    poison_node,
    poisoned_node_ids,
    run_time_shuffle_tripwire,
)

#: This suite's grid and universe — the probe's own leak-verification width
#: (120 dates, 30 symbols), not a smaller one.  That is deliberate: the suite's
#: input is a *stated failure*, and the planted leak only clears the two-sided
#: bar decisively at this width, so a narrower panel would make every test here
#: depend on a borderline detection that the probe's own docstring warns is
#: seed- and grid-sensitive.  A flaky premise is worse than a slow suite.
GRID = monday(120)
SYMBOLS = [f"S{index:02d}" for index in range(30)]


def _failure(node_id: str, seed: int = 7):
    """A *stated* rejection for ``node_id`` — the feature's input.

    Runs feature 125's probe over the canonical planted leak (every date
    carrying the full-sample symbol mean, so re-dating the cross-sections
    cannot disturb it) and refuses to hand back anything that is not a
    rejection.  The assertion is the point rather than belt-and-braces: a test
    built on a verdict that quietly stopped being a failure would assert
    nothing at all, and the failure would surface as a confusing message about
    a missing mark rather than as "the premise moved".
    """
    targets = {1: gaussian_panel(GRID, SYMBOLS, seed=seed)}
    scores = lookahead_panel(targets, horizon=1)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id=node_id)
    assert verdict.rejected, (
        "the planted leak must be rejected for this suite to mean anything"
    )
    assert verdict.outcome == "tripwire_fail"
    return verdict


def _passing(node_id: str):
    """A verdict that *passed* — a clean candidate, so there is nothing to poison.

    Its own premise is asserted too, and for a subtler reason: the test using it
    claims "a store that accepted this would mark nodes for a probe that
    succeeded", so a clean candidate that happened to be rejected would make the
    test pass for the wrong reason.
    """
    targets = {1: gaussian_panel(GRID, SYMBOLS, seed=99)}
    scores = gaussian_panel(GRID, SYMBOLS, seed=5)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id=node_id)
    assert not verdict.rejected, "a clean candidate must not be rejected"
    assert verdict.outcome == "ok"
    return verdict


def _seed(poison_store, **kwargs):
    """Bring the store's schema up and seed a campaign tree into it.

    ``ensure_schema`` first — it is what creates the ``node`` table and its
    ``poisoned_at`` column — then the tree through the same file, so the test
    writes into exactly the schema the store reads.
    """
    poison_store.ensure_schema()
    connection = sqlite3.connect(poison_store.path)
    connection.execute("PRAGMA foreign_keys = ON")
    return seed_campaign(connection, **kwargs)


def _marks(poison_store) -> dict[str, str | None]:
    """``{node_id: poisoned_at}``, read straight from ``node``.

    The raw column rather than the store's ``poisoned()`` answer: a test that
    asserted only through the store's own read would pass against a store whose
    read was as wrong as its write, and this column is what the replay path
    actually consults.
    """
    connection = sqlite3.connect(poison_store.path)
    return {
        row[0]: row[1]
        for row in connection.execute(
            f"SELECT id, {NODE_POISONED_COLUMN} FROM {NODE_TABLE}"
        )
    }


# -- The subtree: what gets poisoned ------------------------------------------


def test_a_failure_poisons_the_node_and_its_entire_subtree(poison_store) -> None:
    # The feature's whole sentence. A chain of three, failed at the root, must
    # come back with all three marked — and the sibling root, which has no
    # parent and no children, must be untouched. That one node is the control: a
    # walk that ignored `parent_id` and marked the campaign would poison it, so
    # its survival is what makes "subtree" mean *subtree* rather than *tree*.
    tree = _seed(poison_store)

    subtree = poison_store.poison(_failure(tree.root_id))

    assert isinstance(subtree, PoisonedSubtree)
    assert subtree.node_ids == tree.subtree_ids
    assert subtree.size == 3
    assert subtree.root_node_id == tree.root_id
    assert subtree.campaign_id == tree.campaign_id
    marked = _marks(poison_store)
    assert marked[tree.root_id] is not None
    assert marked[tree.child_id] is not None
    assert marked[tree.leaf_id] is not None
    assert marked[tree.sibling_root_id] is None, (
        "the sibling branch was not part of the failure"
    )


def test_a_leaf_failure_poisons_exactly_one_node(poison_store) -> None:
    # The frontier the loop is still expanding is where failures are most often
    # found, and there the subtree is the node itself. The feature must
    # degenerate correctly rather than reaching upward: a walk that followed
    # `parent_id` in the wrong direction would poison the root and leave the
    # leaf it actually failed on clean.
    tree = _seed(poison_store)

    subtree = poison_store.poison(_failure(tree.leaf_id))

    assert subtree.node_ids == (tree.leaf_id,)
    assert subtree.size == 1
    marked = _marks(poison_store)
    assert marked[tree.leaf_id] is not None
    assert marked[tree.root_id] is None
    assert marked[tree.child_id] is None


def test_the_subtree_covers_every_branch_not_just_one_path(poison_store) -> None:
    # The walk is the transitive closure, not a path: a root with two children,
    # each with its own child, must have all five marked. A depth-first walk
    # that appended only the last child visited would pass every chain test
    # above and fail here, which is why a branching tree is in the suite.
    root, left, right, leftleaf, rightleaf = (str(uuid.uuid4()) for _ in range(5))
    poison_store.ensure_schema()
    connection = sqlite3.connect(poison_store.path)
    seed_tree(
        connection,
        {
            None: [root],
            root: [left, right],
            left: [leftleaf],
            right: [rightleaf],
        },
    )

    subtree = poison_store.poison(_failure(root))

    assert set(subtree.node_ids) == {root, left, right, leftleaf, rightleaf}
    assert subtree.node_ids[0] == root, "the failing node leads the subtree"
    marked = _marks(poison_store)
    assert all(
        marked[node] is not None for node in (root, left, right, leftleaf, rightleaf)
    )


def test_a_failure_in_one_campaign_leaves_another_campaign_clean(poison_store) -> None:
    # §9.1 scopes every tree query to one campaign, and this feature must not be
    # the exception: a `parent_id` that ever pointed across a campaign boundary
    # would otherwise drag an unrelated branch into a poisoning attributed to a
    # campaign that never ran it. Two campaigns, identically shaped, one failed.
    poison_store.ensure_schema()
    connection = sqlite3.connect(poison_store.path)
    mine = seed_campaign(connection)
    other_campaign = str(uuid.uuid4())
    theirs_root, theirs_child = str(uuid.uuid4()), str(uuid.uuid4())
    connection.executemany(
        f"INSERT INTO {NODE_TABLE} "
        "(id, parent_id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?, ?)",
        [
            (theirs_root, None, other_campaign, "other-theme", 0),
            (theirs_child, theirs_root, other_campaign, "other-theme", 1),
        ],
    )
    connection.commit()

    subtree = poison_store.poison(_failure(mine.root_id))

    marked = _marks(poison_store)
    assert subtree.campaign_id == mine.campaign_id
    assert marked[theirs_root] is None, "another campaign's root was poisoned"
    assert marked[theirs_child] is None, "another campaign's child was poisoned"
    # ...and the other campaign's nodes are absent from the record as well, so
    # an audit reading the trail sees one campaign's failure and not two.
    audit = connection.execute(
        f"SELECT DISTINCT campaign_id FROM {POISON_TABLE}"
    ).fetchall()
    assert audit == [(mine.campaign_id,)]


# -- Persistence: what is written ---------------------------------------------


def test_the_mark_outlives_the_store_that_wrote_it(poison_store, database_url) -> None:
    # "Persists" is the feature's verb, so the mark must be in the file and not
    # in the object: a second store built over the same database — the next
    # process, the replay path — must read the same fact back. A store that kept
    # the poisoning in memory would pass every assertion above and fail here.
    from tripwires import PoisonStore

    tree = _seed(poison_store)
    poison_store.poison(_failure(tree.root_id))

    reopened = PoisonStore(database_url)
    assert reopened.is_poisoned(tree.root_id)
    assert reopened.is_poisoned(tree.child_id)
    assert reopened.is_poisoned(tree.leaf_id)
    assert not reopened.is_poisoned(tree.sibling_root_id)
    assert reopened.subtree_of(tree.root_id) == tree.subtree_ids


def test_a_poisoned_node_reports_when_it_was_marked(poison_store) -> None:
    # The read is an instant, not a bit, because a poisoning is an irreversible
    # act whose ordering against the trial that caused it is the thing an audit
    # checks. A store answering only True/False would make "was this branch
    # replayed after it was poisoned?" unanswerable.
    tree = _seed(poison_store)
    stamp = dt.datetime(2026, 1, 13, 9, 30, tzinfo=dt.UTC)

    poison_store.poison(_failure(tree.root_id), poisoned_at=stamp)

    assert poison_store.poisoned(tree.root_id) == stamp
    assert poison_store.poisoned(tree.leaf_id) == stamp, (
        "one act, so one instant across the whole subtree"
    )
    assert poison_store.poisoned(tree.sibling_root_id) is None


def test_the_record_carries_the_verdict_that_caused_the_poisoning(poison_store) -> None:
    # Feature 132 excises scores on the strength of this record, and an excision
    # is irreversible: a reader must be able to check the decision from what was
    # written, without the verdict in hand. So the record carries the whole of
    # it — which probe fired, the statistic, the bar, the seed and level that
    # rebuild the pairing and the threshold, and the measured date count.
    tree = _seed(poison_store)
    verdict = _failure(tree.root_id)

    poison_store.poison(verdict)

    record = poison_store.load(tree.leaf_id)
    assert isinstance(record, PoisonRecord)
    assert record.tripwire == verdict.tripwire == "time-shuffle"
    assert record.outcome == "tripwire_fail"
    assert record.rejected is True
    assert record.surviving_sharpe == verdict.surviving_sharpe
    assert record.threshold == verdict.threshold
    assert record.seed == verdict.seed
    assert record.level == verdict.level
    assert record.horizon == verdict.horizon
    assert record.measured_dates == verdict.dates
    # A descendant carries the *root's* terms: it was not probed, it was in the
    # wrong branch, and its row says which failure marked it.
    assert record.node_id == tree.leaf_id
    assert record.root_node_id == tree.root_id
    assert record.campaign_id == tree.campaign_id
    # And the decision is checkable from the record's own numbers.
    assert abs(record.surviving_sharpe) > record.threshold
    assert record.as_verdict_terms()["node_id"] == tree.root_id


def test_the_record_is_absent_for_a_node_no_poisoning_named(poison_store) -> None:
    tree = _seed(poison_store)
    poison_store.poison(_failure(tree.root_id))

    assert poison_store.load(tree.sibling_root_id) is None
    assert poison_store.load(str(uuid.uuid4())) is None


def test_every_poisoned_node_has_exactly_one_audit_row(poison_store) -> None:
    # One row per poisoned node, keyed by the node: the replay path asks "was
    # this node poisoned, and by what?" a node at a time, and two rows for one
    # node would answer "twice" for a failure that happened once.
    tree = _seed(poison_store)
    poison_store.poison(_failure(tree.root_id))

    connection = sqlite3.connect(poison_store.path)
    rows = connection.execute(
        f"SELECT node_id, root_node_id, campaign_id FROM {POISON_TABLE}"
    ).fetchall()
    assert len(rows) == 3
    assert {row[0] for row in rows} == set(tree.subtree_ids)
    assert {row[1] for row in rows} == {tree.root_id}
    assert {row[2] for row in rows} == {tree.campaign_id}


# -- Irreversibility, idempotence and the re-run -------------------------------


def test_re_running_a_poisoning_changes_nothing_and_says_so(poison_store) -> None:
    # The action is irreversible — nothing in the store or its schema clears a
    # mark — so a retry after a crash must be idempotent, and the caller must be
    # able to tell "I marked it" from "it was already marked". Without that bit
    # a double-mark is indistinguishable from a first one, and a loop that
    # crashed mid-poisoning could never be repaired safely.
    tree = _seed(poison_store)
    verdict = _failure(tree.root_id)

    first = poison_store.poison(verdict)
    second = poison_store.poison(verdict)

    assert first.replayed is False, "the first call performed the act"
    assert second.replayed is True, "the second found it already done"
    assert second.node_ids == first.node_ids
    assert second.poisoned_at == first.poisoned_at, (
        "a retry does not move the instant the branch was halted"
    )
    connection = sqlite3.connect(poison_store.path)
    assert (
        connection.execute(f"SELECT COUNT(*) FROM {POISON_TABLE}").fetchone()[0] == 3
    ), "a refresh, not a second set of rows"


def test_a_re_run_with_an_explicit_instant_records_the_failure_s_time(
    poison_store,
) -> None:
    # A replay stamping the instant the failure *happened* is the one caller
    # that means to say when, not when it was written — so its instant wins even
    # over an existing mark. Refusing it would make a poisoned branch's history
    # unreproducible from the record.
    tree = _seed(poison_store)
    verdict = _failure(tree.root_id)
    first = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    replayed_at = dt.datetime(2026, 2, 2, tzinfo=dt.UTC)

    poison_store.poison(verdict, poisoned_at=first)
    again = poison_store.poison(verdict, poisoned_at=replayed_at)

    assert again.poisoned_at == replayed_at
    assert poison_store.poisoned(tree.root_id) == replayed_at


def test_a_refused_call_never_clears_a_mark(poison_store) -> None:
    # There is no unpoison, and this is the test that says so. A passing verdict
    # at an already-poisoned node is refused rather than applied — but even the
    # refusal path must leave the mark standing, because a store that cleared a
    # mark on the way to refusing would be an unpoison wearing an error.
    tree = _seed(poison_store)
    stamp = dt.datetime(2026, 1, 13, tzinfo=dt.UTC)
    poison_store.poison(_failure(tree.root_id), poisoned_at=stamp)

    with pytest.raises(TripwirePoisonError):
        poison_store.poison(_passing(tree.root_id))

    assert poison_store.poisoned(tree.root_id) == stamp


# -- The refusals ---------------------------------------------------------------


def test_a_verdict_that_passed_cannot_poison_anything(poison_store) -> None:
    # The feature's precondition, and the one that protects the replay pool from
    # the worst failure mode: a store that accepted a passing verdict would mark
    # nodes for probes that succeeded — excising scores nothing rejected.
    tree = _seed(poison_store)

    with pytest.raises(TripwirePoisonError, match="nothing to poison|failed tripwire"):
        poison_store.poison(_passing(tree.root_id))
    assert _marks(poison_store)[tree.root_id] is None


class _LyingVerdict:
    """A verdict whose ``rejected`` disagrees with its own arithmetic.

    Built by hand rather than by mutating a real verdict, and that is forced:
    ``TimeShuffleVerdict`` is a frozen record that re-validates in
    ``__post_init__``, so ``dataclasses.replace`` raises rather than forging
    anything — the record is built so that this lie cannot be told with one.

    Which is exactly why the store needs its own check, and why this class
    exists: the store validates *structurally* (the factory's scan puts two
    ``TimeShuffleVerdict`` classes in one process, so ``isinstance`` cannot
    hold across the seam), and a structural check that only asked "does it
    carry the ten terms?" would take this object's word for the decision.  It
    carries all ten, ``rejected`` says ``True``, the outcome word agrees — and
    the numbers say the bar was never cleared.  Every field below is copied
    from a real failure so the forgery differs from an honest verdict in
    exactly one place: the statistic.
    """

    # The ten terms the store's structural check asks for, and nothing else:
    # the forgery carries *exactly* what a verdict carries, which is what makes
    # the test about the arithmetic rather than about a shape the store would
    # have refused for a different reason.
    __slots__ = (
        "dates",
        "horizon",
        "level",
        "node_id",
        "outcome",
        "rejected",
        "seed",
        "surviving_sharpe",
        "threshold",
        "tripwire",
    )

    def __init__(self, honest) -> None:
        self.node_id = honest.node_id
        self.tripwire = honest.tripwire
        self.horizon = honest.horizon
        self.dates = honest.dates
        self.seed = honest.seed
        self.level = honest.level
        # Half the bar: comfortably inside it, so `abs(x) > threshold` is
        # decisively false rather than false by a rounding hair.
        self.surviving_sharpe = honest.threshold / 2.0
        self.threshold = honest.threshold
        self.rejected = True
        self.outcome = "tripwire_fail"


def test_a_verdict_whose_arithmetic_does_not_re_derive_its_rejection_is_refused(
    poison_store,
) -> None:
    # The one class of error this store cannot repair by being run again: a
    # verdict claiming a failure beside a statistic that clears no bar would
    # poison a subtree on a leak that never happened. The rejection is
    # re-derived from the statistic and the threshold rather than believed, so
    # this is refused even though `rejected` says True and the outcome word
    # agrees with it.
    tree = _seed(poison_store)
    forged = _LyingVerdict(_failure(tree.root_id))
    assert forged.rejected is True and forged.outcome == "tripwire_fail"
    assert not abs(forged.surviving_sharpe) > forged.threshold

    with pytest.raises(TripwirePoisonError, match="arithmetic disagrees"):
        poison_store.poison(forged)
    assert _marks(poison_store)[tree.root_id] is None


def test_an_object_that_is_not_a_verdict_is_refused(poison_store) -> None:
    # A producer of another shape has no terms to store, and the refusal names
    # the fields it could not read rather than raising an AttributeError three
    # frames deeper in the row builder.
    tree = _seed(poison_store)
    with pytest.raises(TripwirePoisonError, match="carries none of"):
        poison_store.poison({"node_id": tree.root_id, "rejected": True})
    with pytest.raises(TripwirePoisonError, match="carries none of"):
        poison_store.poison(None)


def test_a_node_the_tree_does_not_hold_is_refused_not_created(poison_store) -> None:
    # A poisoning is a fact about a node's *place in a tree*. A row this store
    # invented would be a branch nobody expanded — with `parent_id` NULL it would
    # look like a root — and the subtree the verdict rejected would be silently
    # absent from the record. The rule the guard and the campaign verdict both
    # keep, from the other side.
    poison_store.ensure_schema()
    absent = str(uuid.uuid4())

    with pytest.raises(TripwirePoisonError, match="no node"):
        poison_store.poison(_failure(absent))
    connection = sqlite3.connect(poison_store.path)
    assert (
        connection.execute(f"SELECT COUNT(*) FROM {NODE_TABLE}").fetchone()[0] == 0
    ), "the store must not invent the node it could not find"


def test_a_node_id_that_cannot_join_the_tree_key_is_refused_by_name(
    poison_store,
) -> None:
    # Every id that reaches the store joins a `UUID NOT NULL PRIMARY KEY` column,
    # and a mixed-case or braced spelling of one node would read as two nodes in
    # the set that decides whether a branch is replayed.
    with pytest.raises(TripwirePoisonError, match="not a UUID"):
        poison_store.poisoned("not-a-uuid")
    with pytest.raises(TripwirePoisonError, match="non-empty UUID"):
        poison_store.subtree_of("")
    with pytest.raises(TripwirePoisonError, match="must be a UUID or its text"):
        poison_store.poisoned(None)


def test_a_naive_instant_is_refused(poison_store) -> None:
    # A naive datetime silently reinterpreted as local time would place a
    # poisoning hours away from the trial that caused it, and every row would
    # still agree — the ordering would be wrong and invisible.
    tree = _seed(poison_store)
    with pytest.raises(TripwirePoisonError, match="timezone-aware"):
        poison_store.poison(
            _failure(tree.root_id),
            # Naive on purpose: the naive datetime *is* the input under test,
            # so the rule against constructing one has nothing to protect here.
            poisoned_at=dt.datetime(2026, 1, 13, 9, 30),  # noqa: DTZ001
        )


def test_an_unparseable_stored_instant_is_refused_rather_than_returned(
    poison_store,
) -> None:
    # A caller comparing a string against a datetime would find them unequal
    # always, so a poisoning trail that silently compared as "not poisoned" is
    # worse than one that stops. The column is written by this store, but it is
    # a column other writers can reach.
    tree = _seed(poison_store)
    poison_store.poison(_failure(tree.root_id))
    connection = sqlite3.connect(poison_store.path)
    connection.execute(
        f"UPDATE {NODE_TABLE} SET {NODE_POISONED_COLUMN} = 'not-a-date' WHERE id = ?",
        (tree.root_id,),
    )
    connection.commit()

    with pytest.raises(TripwirePoisonError, match="could not be parsed"):
        poison_store.poisoned(tree.root_id)


def test_a_cyclic_parent_chain_is_refused_rather_than_walked_forever(
    poison_store,
) -> None:
    # `parent_id` is a foreign key and the tree's writer is what makes it a tree;
    # this store cannot enforce acyclicity across arbitrary writers, and a
    # recursive CTE over a cycle does not terminate. Refusing by name beats
    # truncating at some depth and reporting a subtree that is not one — a mark
    # is irreversible, and one written from a broken walk is not repairable by
    # running the feature again.
    poison_store.ensure_schema()
    connection = sqlite3.connect(poison_store.path)
    first, second, third = (str(uuid.uuid4()) for _ in range(3))
    # first → second → third → first: a cycle with no root, built with foreign
    # keys off because the FK cannot express one in any insertion order. The
    # walk starts from the node the verdict names rather than from a root, so
    # this is reachable by asking for `first` — which is exactly how a cycle
    # would arrive in production, and why the guard has to be in the walk.
    entry = str(uuid.uuid4())
    seed_tree(
        connection,
        {
            None: [entry],
            entry: [first],
            first: [second],
            second: [third],
            third: [first],
        },
    )

    with pytest.raises(TripwirePoisonError, match="own ancestry"):
        poison_store.poison(_failure(first))
    # ...and nothing was written on the way to the refusal: the walk fails
    # before the mark, so a rejected poisoning leaves the tree exactly as it
    # found it rather than half-marked.
    assert not any(_marks(poison_store).values())


def test_a_cycle_is_the_only_way_a_node_can_be_reached_twice(poison_store) -> None:
    # A diamond — one node reachable by two independent paths — is the other
    # shape a walk could emit twice, and it is worth pinning that it *cannot
    # happen here*: `parent_id` is a single column, so a row names exactly one
    # parent, so the only way back to a node is around a cycle. That is why the
    # guard above is the whole guard, and why the walk has one refusal to name
    # rather than two. A schema change that gave `node` a second parent edge
    # would make this test fail, which is the point of writing it down.
    poison_store.ensure_schema()
    connection = sqlite3.connect(poison_store.path)
    root, left, right, shared = (str(uuid.uuid4()) for _ in range(4))
    # root → {left, right}, and both of them claim → shared: what a diamond
    # *would* be, had the table a column to express it. It has one, so the
    # graph that reaches the database is not a diamond at all — `shared` gets
    # the last parent it was named under, and the walk sees it exactly once,
    # under that parent.
    seed_tree(
        connection,
        {None: [root], root: [left, right], left: [shared], right: [shared]},
    )

    four = poison_store.poison(_failure(root)).node_ids
    assert four[0] == root, "the failing node leads"
    assert set(four) == {root, left, right, shared}
    assert len(four) == 4, (
        "each node once — the second parent edge is gone, not doubled"
    )
    # ...and which parent it landed under is the last one mentioned, which is
    # what makes a cycle expressible: the mapping's later mention is the one
    # that survives, so `{a: [b], b: [a]}` can close a loop that `a`'s key is
    # also needed to open. Asked from `left`, the subtree is one node — the
    # edge that would have made this a diamond is simply not there.
    assert poison_store.poison(_failure(left)).node_ids == (left,)


def test_a_database_url_this_store_cannot_speak_is_refused_by_name() -> None:
    from tripwires import PoisonStore

    with pytest.raises(TripwirePoisonError, match="scheme"):
        PoisonStore("postgresql://localhost/db").poisoned(str(uuid.uuid4()))
    with pytest.raises(TripwirePoisonError, match="no database path"):
        PoisonStore("sqlite://").poisoned(str(uuid.uuid4()))
    with pytest.raises(TripwirePoisonError, match="non-empty"):
        PoisonStore("   ")


def test_a_store_that_names_nothing_refuses_to_pretend_it_persisted() -> None:
    # The module-level entry point refuses a call with no store rather than
    # quietly doing nothing: an evaluation loop that believed §C6's rejection had
    # been recorded, while every score the branch contributed went on being
    # replayed, is exactly the failure this feature exists to make impossible.
    verdict = _failure(str(uuid.uuid4()))
    with pytest.raises(TripwirePoisonError, match="no store"):
        poison_node(verdict, store=None, database_url=None)


# -- The module-level entry points and the composed seam -----------------------


def test_the_module_level_entry_points_run_the_whole_feature(
    poison_store, database_url
) -> None:
    # The shape an evaluation loop wants: it holds a verdict, it needs the list
    # of nodes whose scores it must stop replaying, and it does not want to hold
    # a store to get it.
    tree = _seed(poison_store)
    verdict = _failure(tree.root_id)

    ids = poisoned_node_ids(verdict, database_url=database_url)

    assert ids == tree.subtree_ids
    subtree = poison_node(verdict, database_url=database_url)
    assert subtree.replayed is True, "the call above already poisoned it"
    assert subtree.size == 3


def test_the_composed_component_is_the_poison_store(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    # The plugin seam from the persistence side: the factory's scan imports the
    # member, its @register fires, and a composed application carries the store
    # for the deployment the process is running in — reachable by name from the
    # composed application, which is how a later feature (132's excision) will
    # ask for it.
    from pathlib import Path

    import tripwires

    from app.module_loader import Application, Registration, create_app

    monkeypatch.setenv("DATABASE_URL", database_url)
    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    composed = application.get(POISON_COMPONENT_NAME)
    assert type(composed).__name__ == "PoisonStore"
    # The probe's component still answers its own question, and the store's is a
    # second component rather than a second accessor on the first.
    assert type(application.get("tripwires")).__name__ == "TimeShuffleTripwire"
    assert POISON_COMPONENT_NAME == "tripwires-poison"
    # A store registered but not yet used: composition opens no database.
    assert not Path(composed.path).exists()
    assert Application(components={}, order=()).get(POISON_COMPONENT_NAME) is None


def test_an_unconfigured_deployment_composes_no_store_but_does_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The degrade-don't-break stance every store in this workspace takes toward
    # an absent DATABASE_URL: the factory builds every registered component on
    # every create_app(), so a builder that raised would take composition down
    # for every unrelated feature. Absent is a *discoverable* state — and it is
    # not the same fact as "the failure was recorded and there was nothing to
    # record", which is why the module-level entry point refuses instead.
    from pathlib import Path

    import tripwires

    from app.module_loader import Registration, create_app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    assert application.get(POISON_COMPONENT_NAME) is None
    assert type(application.get("tripwires")).__name__ == "TimeShuffleTripwire"


# -- The value ------------------------------------------------------------------


def test_the_subtree_reports_itself_as_a_payload(poison_store) -> None:
    tree = _seed(poison_store)
    subtree = poison_store.poison(_failure(tree.root_id))

    payload = subtree.to_payload()
    assert payload["root_node_id"] == tree.root_id
    assert payload["campaign_id"] == tree.campaign_id
    assert payload["size"] == 3
    assert payload["node_ids"] == list(tree.subtree_ids)
    assert payload["tripwire"] == "time-shuffle"
    assert payload["outcome"] == "tripwire_fail"
    assert payload["replayed"] is False
    assert payload["poisoned_at"]


def test_the_subtree_is_frozen_and_compares_by_value(poison_store) -> None:
    tree = _seed(poison_store)
    verdict = _failure(tree.root_id)
    stamp = dt.datetime(2026, 1, 13, tzinfo=dt.UTC)
    first = poison_store.poison(verdict, poisoned_at=stamp)

    # Value equality over the whole record of the act — and `replayed` is part
    # of that value rather than excluded from it, which is the decision worth
    # asserting: a first poisoning and a refresh of it describe one branch but
    # are different facts about the caller's situation, and §8's
    # `tree_appended` idiom draws the same distinction for the evaluator's own
    # one-shot write. A caller deciding whether to emit a "branch halted" event
    # reads exactly this difference, so a value that compared them equal would
    # hand them the wrong one.
    assert first.replayed is False
    refreshed = poison_store.poison(verdict, poisoned_at=stamp)
    assert refreshed.replayed is True
    assert first != refreshed, "a refresh is not the act, and the value says so"
    assert first.poisoned_at == refreshed.poisoned_at, (
        "...but the instant, the branch and the terms are all identical"
    )
    assert first.node_ids == refreshed.node_ids
    assert hash(first) != hash(refreshed)
    assert first in {first, refreshed}, "the value is hashable, for a set"
    with pytest.raises(AttributeError, match="frozen"):
        first._root_node_id = "elsewhere"
    # The record is a value too, and its key is the node — so two nodes of one
    # poisoned subtree share every *term* of the failure and differ only in
    # which node they describe.
    root_record = poison_store.load(tree.root_id)
    assert root_record != poison_store.load(tree.child_id)
    assert root_record.as_verdict_terms() == (
        poison_store.load(tree.child_id).as_verdict_terms()
    )
    assert root_record.root_node_id == poison_store.load(tree.child_id).root_node_id
    with pytest.raises(AttributeError, match="frozen"):
        root_record._node_id = "elsewhere"


def test_the_subtree_value_refuses_a_shape_its_own_walk_cannot_produce(
    poison_store,
) -> None:
    # The value validates, so a record built by hand — or by a later feature
    # whose producer drifted — fails loudly rather than carrying a poisoning
    # that never happened.
    root = str(uuid.uuid4())
    campaign = str(uuid.uuid4())
    stamp = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    common = {
        "campaign_id": campaign,
        "tripwire": "time-shuffle",
        "outcome": "tripwire_fail",
        "surviving_sharpe": 3.0,
        "threshold": 1.0,
        "poisoned_at": stamp,
        "replayed": False,
    }

    with pytest.raises(TripwirePoisonError, match="empty subtree"):
        PoisonedSubtree(root_node_id=root, node_ids=(), **common)
    with pytest.raises(
        TripwirePoisonError, match="first node must be the failing node"
    ):
        PoisonedSubtree(root_node_id=root, node_ids=(str(uuid.uuid4()),), **common)
    with pytest.raises(TripwirePoisonError, match="names each node once"):
        PoisonedSubtree(root_node_id=root, node_ids=(root, root), **common)
    with pytest.raises(TripwirePoisonError, match="'tripwire_fail'"):
        PoisonedSubtree(
            root_node_id=root, node_ids=(root,), **{**common, "outcome": "ok"}
        )


def test_the_probe_suite_still_needs_no_database() -> None:
    # The property feature 131 must not cost the member. The probe is a pure
    # function of two mappings and is what the frozen evaluator image imports,
    # so it must keep composing and probing with nothing configured — no
    # ``DATABASE_URL``, no store, no file. This test names no fixture, which is
    # the assertion: a probe that had grown a database dependency would have
    # shown up as a fixture this file needed, and the two fixtures above are
    # deliberately not autouse so that stays visible.
    from pathlib import Path

    import tripwires

    from app.module_loader import Registration, create_app

    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    probe = application.get("tripwires")
    targets = {1: gaussian_panel(GRID, SYMBOLS, seed=3)}
    verdict = probe.run(gaussian_panel(GRID, SYMBOLS, seed=4), targets, node_id="n1")
    assert verdict.outcome == "ok"
    # The store composes beside it, or does not — the point is that the probe's
    # path does not care which. An unconfigured deployment is the case this
    # asserts on (no DATABASE_URL is set for this test), so the second component
    # answering `None` is the expected outcome and not a failure.
    assert application.get(POISON_COMPONENT_NAME) is None


def test_the_store_component_resolves_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    from tripwires import DATABASE_URL_ENV, PoisonStore

    monkeypatch.setenv(DATABASE_URL_ENV, database_url)
    resolved = PoisonStore.resolve()
    assert isinstance(resolved, PoisonStore)
    assert resolved.database_url == database_url

    monkeypatch.delenv(DATABASE_URL_ENV)
    assert PoisonStore.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert PoisonStore.resolve() is None, "whitespace counts as unset"
