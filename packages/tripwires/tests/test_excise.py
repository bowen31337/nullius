"""Feature 132 — a poisoned subtree, excised from the replay pool.

app_spec.xml: *"System excises a poisoned subtree from the replay pool, which
rejects every score that branch contributed."*  The suite is organised around
the three claims that sentence makes, because each is separately falsifiable and
the feature is only correct when all three hold:

* **the branch** — the unit is the poisoned subtree feature 131 marked, and not
  the failing node alone (which leaves the descendants' scores in the pool), not
  the whole campaign (which would refuse unrelated branches' evidence), and not
  another campaign's nodes at all.  The tests walk a chain, a branching tree and
  a two-campaign pool to pin all three edges.
* **every score it contributed** — plural, and per *node*: §C5 replays a policy
  across many worlds, so one node carries several rows, and all of them must be
  refused.  A refusal keyed on one row per node would pass a chain test and fail
  here.
* **the pool rejects them** — the refusal has to be *applied by the pool*, not
  merely known: ``survivors`` must not contain a single row the branch
  contributed, and every other row must be there unchanged.  A feature that
  reported an excision and left the pool serving the rows would satisfy every
  assertion about the branch and be exactly the failure §C6 exists to prevent.

The rest of the suite is the scaffolding that keeps those three honest: that the
refusal writes nothing (the pool's rows are *all* still there, so an operator can
still ask what a branch cost), that the mark — not the record — is what the pool
believes, that a clean node is not an excision of nothing, and that the answer
carries the attribution an operator needs.

Nothing here re-tests feature 131.  The panels come from the probe's own
builders (:mod:`_panels`), the tree from :mod:`_trees`, the pool from
:mod:`_pool`, and every poisoning is produced by *running feature 131's own
API* — so a change to either feature shows up here as a changed premise rather
than as a silent pass.  :func:`_failure` asserts its own premise for exactly
that reason.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid

import pytest
from _panels import gaussian_panel, lookahead_panel, monday
from _pool import seed_pool
from _trees import Tree, seed_campaign, seed_tree
from tripwires import (
    DATABASE_URL_ENV,
    EXCISE_COMPONENT_NAME,
    ExcisedBranch,
    ExcisedScore,
    PoolScore,
    ReplayPool,
    TripwireExcisionError,
    excise_subtree,
    run_time_shuffle_tripwire,
    surviving_scores,
)

#: This suite's grid and universe — the probe's own leak-verification width
#: (120 dates, 30 symbols), not a smaller one.  That is deliberate and it is
#: inherited from feature 131's suite for the same reason: the suite's input is
#: a *stated failure*, and the planted leak only clears the two-sided bar
#: decisively at this width, so a narrower panel would make every test here
#: depend on a borderline detection the probe's own docstring warns is seed- and
#: grid-sensitive.  A flaky premise is worse than a slow suite.
GRID = monday(120)
SYMBOLS = [f"S{index:02d}" for index in range(30)]


def _failure(node_id: str, seed: int = 7):
    """A *stated* rejection for ``node_id`` — the feature's input, via feature 125.

    Runs the probe over the canonical planted leak (every date carrying the
    full-sample symbol mean, so re-dating the cross-sections cannot disturb it)
    and refuses to hand back anything that is not a rejection.  The assertion is
    the point rather than belt-and-braces: a test built on a verdict that
    quietly stopped being a failure would assert nothing at all, and the failure
    would surface as a confusing message about a missing row rather than as "the
    premise moved".
    """
    targets = {1: gaussian_panel(GRID, SYMBOLS, seed=seed)}
    scores = lookahead_panel(targets, horizon=1)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id=node_id)
    assert verdict.rejected, (
        "the planted leak must be rejected for this suite to mean anything"
    )
    assert verdict.outcome == "tripwire_fail"
    return verdict


def _seed(pool: ReplayPool, **kwargs) -> Tree:
    """Bring the pool's schema up and seed a campaign tree into it.

    ``ensure_schema`` first — it is what creates ``node``, its ``poisoned_at``
    column and ``replay_score`` — then the tree through the same file, so the
    test writes into exactly the schema the pool reads.
    """
    pool.ensure_schema()
    connection = sqlite3.connect(pool.path)
    connection.execute("PRAGMA foreign_keys = ON")
    return seed_campaign(connection, **kwargs)


def _poisoned(pool: ReplayPool, tree: Tree, node_id: str | None = None):
    """Poison ``tree``'s node through feature 131 and return the subtree.

    The suite's only way to produce the input feature 132 reads, and it goes
    through the store's public entry point on purpose: a test that wrote
    ``poisoned_at`` and an audit row by hand would be testing this feature
    against a state feature 131 cannot produce, which is how two features come
    to agree with each other and with nothing else.
    """
    return pool.marks.poison(_failure(node_id or tree.root_id))


def _seeded(pool: ReplayPool, picks, **kwargs):
    """Seed replay-pool rows over the tree already in ``pool``'s database."""
    connection = sqlite3.connect(pool.path)
    connection.execute("PRAGMA foreign_keys = ON")
    return seed_pool(connection, picks, **kwargs)


def _raw_rows(pool: ReplayPool) -> tuple[tuple, ...]:
    """Every ``replay_score`` row, read straight from the table.

    The raw table rather than the pool's own ``survivors`` answer: a test that
    asserted only through the pool's read would pass against a pool whose read
    was as wrong as its refusal, and this table is what the replay path actually
    consults.
    """
    connection = sqlite3.connect(pool.path)
    return tuple(
        connection.execute(
            "SELECT id, committed_pick FROM replay_score ORDER BY created_at, id"
        ).fetchall()
    )


def _picks(pool: ReplayPool) -> set[str | None]:
    """The committed picks of every row the pool still serves."""
    return {row.committed_pick for row in pool.survivors()}


# -- The branch: what is excised ------------------------------------------------


def test_a_branch_s_failure_excises_every_score_it_contributed(pool) -> None:
    # The feature's whole sentence. A chain of three, failed at the root, with
    # every node carrying a score, must come back with all three refused — and
    # the sibling root's row, which belongs to no subtree of the failure, must
    # survive. That one row is the control: a refusal keyed on the campaign
    # rather than the branch would take it too, so its survival is what makes
    # "subtree" mean *subtree* rather than *tree*.
    tree = _seed(pool)
    _seeded(
        pool,
        {tree.root_id: 1, tree.child_id: 1, tree.leaf_id: 1, tree.sibling_root_id: 1},
    )
    _poisoned(pool, tree)

    branch = pool.excise(tree.root_id)

    assert isinstance(branch, ExcisedBranch)
    assert branch.node_ids == tree.subtree_ids
    assert branch.size == 3
    assert branch.root_node_id == tree.root_id
    assert branch.campaign_id == tree.campaign_id
    assert set(branch.picks) == {tree.root_id, tree.child_id, tree.leaf_id}
    assert _picks(pool) == {tree.sibling_root_id}, (
        "the sibling branch's score was not part of the failure"
    )
    assert branch.excised_score_count == 3
    assert branch.pool_size == 4
    assert branch.surviving_score_count == 1


def test_a_leaf_failure_excises_only_that_node_s_scores(pool) -> None:
    # The frontier the loop is still expanding is where failures are most often
    # found, and there the branch is the node itself. The feature must degenerate
    # to "refuse this node's scores" rather than reaching up the tree — the
    # mirror image of feature 131's leaf case.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1, tree.child_id: 1, tree.leaf_id: 1})
    _poisoned(pool, tree, tree.leaf_id)

    branch = pool.excise(tree.leaf_id)

    assert branch.node_ids == (tree.leaf_id,)
    assert branch.size == 1
    assert branch.picks == (tree.leaf_id,)
    assert _picks(pool) == {tree.root_id, tree.child_id}


def test_every_score_of_every_branch_node_is_refused_not_one_per_node(pool) -> None:
    # "every score that branch contributed" is plural per node: §C5 replays a
    # policy across many worlds, so one node carries one row per world. A refusal
    # that keyed on one row per node — the shape a per-node DELETE would have —
    # passes every chain test above and fails here. The root and the child each
    # carry three rows; all six must be gone from the survivors.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 3, tree.child_id: 3})
    _poisoned(pool, tree)

    branch = pool.excise(tree.root_id)

    assert branch.excised_score_count == 6
    assert pool.survivors() == ()
    per_node = {
        node: sum(1 for entry in branch.scores if entry.score.committed_pick == node)
        for node in branch.picks
    }
    assert per_node == {tree.root_id: 3, tree.child_id: 3}
    # ...and the pool's per-node read agrees, which is the shape a replay path
    # would ask the question in.
    assert len(pool.scores_of(tree.root_id)) == 3
    assert len(pool.scores_of(tree.child_id)) == 3


def test_a_branching_failure_refuses_every_leaf_not_just_one_path(pool) -> None:
    # The branch is the transitive closure, not a path: a root with two children,
    # each with its own child, must refuse all five nodes' scores. A depth-first
    # refusal that stopped at the last child visited would pass every chain test
    # above and fail here, which is why a branching tree is in the suite.
    root, left, right, leftleaf, rightleaf = (str(uuid.uuid4()) for _ in range(5))
    pool.ensure_schema()
    connection = sqlite3.connect(pool.path)
    connection.execute("PRAGMA foreign_keys = ON")
    seed_tree(
        connection,
        {
            None: [root],
            root: [left, right],
            left: [leftleaf],
            right: [rightleaf],
        },
    )
    seed_pool(connection, [root, left, right, leftleaf, rightleaf])
    pool.marks.poison(_failure(root))

    branch = pool.excise(root)

    assert set(branch.node_ids) == {root, left, right, leftleaf, rightleaf}
    assert branch.node_ids[0] == root, "the failing node leads the branch"
    assert branch.excised_score_count == 5
    assert pool.survivors() == ()


def test_a_failure_in_one_campaign_leaves_another_campaign_s_pool_alone(pool) -> None:
    # §9.1 scopes every tree query to one campaign, and this feature must not be
    # the exception. Two identically shaped campaigns, both with scores, one
    # failed: the other campaign's rows must survive untouched, because refusing
    # them would reject evidence no tripwire ever condemned.
    pool.ensure_schema()
    connection = sqlite3.connect(pool.path)
    connection.execute("PRAGMA foreign_keys = ON")
    mine = seed_campaign(connection)
    other_campaign = str(uuid.uuid4())
    theirs_root, theirs_child = str(uuid.uuid4()), str(uuid.uuid4())
    connection.executemany(
        "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (theirs_root, None, other_campaign, "other-theme", 0),
            (theirs_child, theirs_root, other_campaign, "other-theme", 1),
        ],
    )
    connection.commit()
    seed_pool(
        connection,
        {mine.root_id: 1, mine.child_id: 1, theirs_root: 1, theirs_child: 1},
    )
    _poisoned(pool, mine)

    branch = pool.excise(mine.root_id)

    assert branch.campaign_id == mine.campaign_id
    assert _picks(pool) == {theirs_root, theirs_child}, (
        "another campaign's scores were excised by one campaign's failure"
    )


def test_a_row_whose_pick_is_null_is_never_refused(pool) -> None:
    # 0109 declares `committed_pick` nullable and says why: a candidate scored
    # but not selected has no pick, and a fabricated nil would read as a real
    # trade. A NULL names *no node*, so it can never match a poisoned one — and
    # that is the correct reading rather than a hole in the feature: such a row
    # contributed no node to any branch.
    tree = _seed(pool)
    _seeded(pool, [tree.root_id, None, None])
    _poisoned(pool, tree)

    branch = pool.excise(tree.root_id)

    assert branch.excised_score_count == 1
    assert [row.committed_pick for row in pool.survivors()] == [None, None], (
        "a row that committed to no node contributed nothing to the branch"
    )


def test_a_pick_the_tree_does_not_hold_is_served_rather_than_lost(pool) -> None:
    # A row whose pick the tree does not hold — a stale id from an old tree —
    # must not vanish from the pool. An inner join would drop it from *both* the
    # survivors and the refused set, which is a silent hole in the pool and the
    # one outcome a refusal must not produce. Nothing marked it, so nothing
    # refuses it, and the three LEFT joins are what keep it visible.
    tree = _seed(pool)
    stale = str(uuid.uuid4())
    _seeded(pool, [tree.root_id, stale])
    _poisoned(pool, tree)

    branch = pool.excise(tree.root_id)

    assert branch.excised_score_count == 1
    assert [row.committed_pick for row in pool.survivors()] == [stale]


# -- Nothing is written: the evidence survives -----------------------------------


def test_an_excision_deletes_nothing_the_pool_still_holds_the_score_rows(pool) -> None:
    # "Excised" means the pool does not *serve* them, not that the rows are gone.
    # The pool is the evidence a policy revision was selected on — 0109's own
    # words — so a deletion would rewrite the reason a past selection was made,
    # and app_spec.xml feature 270 forbids a replay pool mutation outright. Every
    # row must still be in the table after the refusal.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 2, tree.child_id: 1})
    before = _raw_rows(pool)
    _poisoned(pool, tree)

    branch = pool.excise(tree.root_id)

    assert _raw_rows(pool) == before, (
        "the excision modified the pool's rows; the refusal is a read"
    )
    assert branch.excised_score_count == 3
    assert len(pool.refused()) == 3
    # ...and the refused rows are still readable *as* rows — the evidence an
    # operator asks for afterwards, which a deletion would have destroyed.
    assert all(isinstance(entry.score, PoolScore) for entry in pool.refused())


def test_the_refusal_is_idempotent_and_monotone(pool) -> None:
    # Running it again is the same read, and because no code path un-marks a node
    # the surviving set can only shrink. Both properties are what a deletion
    # would have to be argued into; here they are consequences of the design.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1, tree.child_id: 1, tree.sibling_root_id: 1})
    _poisoned(pool, tree)

    first = pool.excise(tree.root_id)
    second = pool.excise(tree.root_id)

    assert first == second
    assert _picks(pool) == {tree.sibling_root_id}
    # A second failure narrows it further and never widens it.
    pool.marks.poison(_failure(tree.sibling_root_id))
    third = pool.excise(tree.sibling_root_id)
    assert third.excised_score_count == 1
    assert pool.survivors() == ()
    assert pool.excise(tree.root_id) == first, "the earlier branch is unchanged"


def test_a_descendant_poisoned_as_its_own_branch_does_not_inflate_the_survivors(
    pool,
) -> None:
    # The overlap, and the bug this test was written to close. Feature 131's
    # record is keyed by `node_id` and upserts, so poisoning the *child* as the
    # origin of its own failure rewrites the child's row to name itself as the
    # root — the root's subtree narrows to the root alone, and this branch's
    # `scores` becomes a strict subset of the rows the pool actually refuses.
    #
    # The tempting way to report `surviving_score_count` is `pool_size -
    # len(scores)`, which is right until exactly this case and then overstates
    # what is served by the rows the *child's* failure covers: the value would
    # claim 4 rows survive while `survivors()` — the read §C5 aggregates from —
    # returns 1. So the count is measured off the pool instead, and this asserts
    # the two agree.
    tree = _seed(pool)
    _seeded(
        pool,
        {tree.root_id: 1, tree.child_id: 1, tree.leaf_id: 1, tree.sibling_root_id: 1},
    )
    _poisoned(pool, tree, tree.root_id)
    pool.marks.poison(_failure(tree.child_id))  # the descendant, as its own root

    branch = pool.excise(tree.root_id)

    assert branch.node_ids == (tree.root_id,), (
        "the record now attributes the child to its own failure"
    )
    assert branch.excised_score_count == 1
    assert branch.surviving_score_count == len(pool.survivors()) == 1, (
        "the count is measured off the pool, not derived from this branch"
    )
    # The marks the child's re-poisoning did not clear still stand, so the pool
    # refuses more rows than this branch's own account names — which is the fact
    # the derivation got wrong.
    assert pool.poisoned(tree.child_id) is True
    assert pool.poisoned(tree.leaf_id) is True
    assert _picks(pool) == {tree.sibling_root_id}
    # ...and the branch value itself is consistent: everything it names is
    # refused, and nothing it names is served.
    excised_ids = {entry.score.id for entry in branch.scores}
    refused_ids = {entry.score.id for entry in pool.refused()}
    served_ids = {row.id for row in pool.survivors()}
    assert excised_ids <= refused_ids, "the branch's rows are all refused"
    assert not (excised_ids & served_ids), "a refused score is never served"
    assert branch.surviving_score_count == len(pool.survivors())


def test_two_overlapping_records_still_account_for_every_refused_score(pool) -> None:
    # Claim 2 in its hardest form. Overlapping poisonings partition the branch
    # between two records: the ancestor's narrows to the nodes still attributed
    # to it, and the descendant's own record takes the tail. Neither record
    # alone names every row the pool refuses — but their *union* must, or a row
    # would be refused by a mark that no branch account mentions, and a caller
    # reconciling `refused()` against the branches the record holds (§C5's loop
    # reads one and reports the other) would find a row that went missing with
    # nothing to explain it.
    #
    # This is why the test walks the branches rather than trusting the root's
    # account: the reconciliation is over `excised_roots()`, which is what a
    # reader of the store actually has.
    tree = _seed(pool)
    _seeded(
        pool,
        {tree.root_id: 2, tree.child_id: 2, tree.leaf_id: 2, tree.sibling_root_id: 1},
    )
    _poisoned(pool, tree, tree.root_id)
    pool.marks.poison(_failure(tree.child_id))  # the descendant, as its own root

    branches = [pool.excise(root) for root in pool.excised_roots()]

    named = {entry.score.id for branch in branches for entry in branch.scores}
    refused = {entry.score.id for entry in pool.refused()}
    served = {row.id for row in pool.survivors()}
    assert named == refused, (
        "the branches between them account for every refused row exactly, and a "
        "union that is short is a row refused with no branch to explain it"
    )
    assert not (named & served)
    # Every branch's own count is measured against the same pool, so all of them
    # report the same number of survivors — the pool's, not their own.
    assert {branch.surviving_score_count for branch in branches} == {len(served)}
    assert len(served) == 1 and _picks(pool) == {tree.sibling_root_id}
    assert pool.poisoned(tree.leaf_id) is True, (
        "the mark the narrowing did not clear still stands"
    )


def test_the_pool_read_and_the_module_level_read_are_one_path(pool) -> None:
    # `surviving_scores` is the module-level spelling a replay loop uses; it must
    # be the same answer as the object's own read, or a caller holding no pool
    # would get a different pool from one holding it.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1, tree.sibling_root_id: 1})
    _poisoned(pool, tree)

    assert surviving_scores(pool=pool) == pool.survivors()
    assert excise_subtree(tree.root_id, pool=pool) == pool.excise(tree.root_id)


# -- The mark is the authority, and the record supplies the attribution ----------


def test_the_pool_believes_the_mark_even_when_the_record_disagrees(pool) -> None:
    # The record is what a failure *wrote*; the mark is what the replay path
    # *reads*, and feature 131 states the mark's residence for exactly that
    # reason. So a hand-cleared mark beside an intact record must NOT be an
    # excision: reporting one would tell a caller the branch was refused while
    # the pool went on serving every score of it.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1})
    _poisoned(pool, tree)
    connection = sqlite3.connect(pool.path)
    connection.execute(
        "UPDATE node SET poisoned_at = NULL WHERE id = ?", (tree.root_id,)
    )
    connection.commit()

    with pytest.raises(TripwireExcisionError, match="carries no mark"):
        pool.excise(tree.root_id)
    # ...and nothing was refused on the strength of the record alone.
    assert len(pool.survivors()) == 1


def test_a_record_with_no_row_for_the_failing_node_is_refused(pool) -> None:
    # The failing node is the row the rest of the branch is read through; its
    # absence means the record was written by something other than this member's
    # poisoning, and guessing the branch's scope from the descendants' rows would
    # report a failure nobody recorded.
    tree = _seed(pool)
    _poisoned(pool, tree)
    connection = sqlite3.connect(pool.path)
    connection.execute(
        "DELETE FROM tripwire_poison WHERE node_id = ?", (tree.root_id,)
    )
    connection.commit()

    with pytest.raises(TripwireExcisionError, match="no row for the node itself"):
        pool.excise(tree.root_id)


def test_a_mark_with_no_attributing_record_is_refused_rather_than_served_or_guessed(
    pool,
) -> None:
    # The third state: a node carries the mark but no audit row names the failure.
    # Feature 131 cannot write it (it writes the mark and the record in one
    # transaction) but a hand can. This feature refuses scores *by branch*, so a
    # mark nothing attributes cannot be excised without the pool inventing which
    # failure condemned it — and serving the row would be worse, because the mark
    # says it is condemned.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1})
    _poisoned(pool, tree)
    connection = sqlite3.connect(pool.path)
    connection.execute(
        "DELETE FROM tripwire_poison WHERE node_id = ?", (tree.root_id,)
    )
    connection.commit()

    with pytest.raises(TripwireExcisionError, match="no record naming the failure"):
        pool.refused()


def test_a_branch_row_that_came_back_unmarked_is_refused_by_the_read_back(pool) -> None:
    # The half-written state feature 131's own `_confirm` exists to make
    # impossible, reached by hand: the record names the node but a row's own mark
    # is cleared, so the pool would go on serving a score the account says it
    # excised. The refusal is total — reporting the branch would be the silent
    # divergence this category exists to prevent.
    #
    # Cleared on a *descendant* rather than the root, so the check that fires is
    # the pool's own read-back and not the failing node's mark check. Which check
    # that is is worth being precise about, because it is the one that carries
    # the feature: the pool's second query names the branch's nodes that still
    # have a served row, finds the child among them, and the branch value refuses
    # to exist with a survivor. (The other guard in `_confirm` — refused rows
    # against rows that came back marked — cannot fire here: both sides of that
    # comparison read the same cleared mark, so they agree.)
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1, tree.child_id: 1})
    _poisoned(pool, tree)
    connection = sqlite3.connect(pool.path)
    connection.execute(
        "UPDATE node SET poisoned_at = NULL WHERE id = ?", (tree.child_id,)
    )
    connection.commit()

    with pytest.raises(TripwireExcisionError, match="still has 1 node"):
        pool.excise(tree.root_id)
    # ...and no branch value was published: the caller is told the refusal did
    # not land rather than handed an account that contradicts the pool. The
    # pool's own read shows exactly the divergence the refusal is about — the
    # root's row refused, the child's still served.
    assert pool.poisoned(tree.child_id) is False
    assert [row.committed_pick for row in pool.survivors()] == [tree.child_id]


def test_a_clean_node_is_not_an_excision_of_nothing(pool) -> None:
    # "Excise this branch" and "this branch was never poisoned" are different
    # sentences, and a pool that answered the second with an empty success would
    # let a caller report an excision it never performed — the failure §C6 exists
    # to prevent, arriving as a quiet green rather than as a red.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1})

    with pytest.raises(TripwireExcisionError, match="no poisoning ever recorded"):
        pool.excise(tree.root_id)
    assert len(pool.survivors()) == 1, "nothing was refused by the refusal"


def test_a_node_id_that_cannot_join_the_record_s_key_is_refused_by_name(pool) -> None:
    # Every id that reaches the pool joins a UUID column, and a mixed-case or
    # braced spelling of one node would read as two nodes in the set that decides
    # whether a branch is served. The refusal is this module's own error, so a
    # §C5 loop catching it catches a malformed id as well as a clean branch.
    with pytest.raises(TripwireExcisionError, match="not a UUID"):
        pool.excise("not-a-uuid")
    with pytest.raises(TripwireExcisionError, match="non-empty UUID"):
        pool.scores_of("")
    with pytest.raises(TripwireExcisionError, match="must be a UUID or its text"):
        pool.excise(None)


def test_a_store_pointed_at_another_database_is_refused(pool, other_pool) -> None:
    # "The pool refuses what the store marked" is a sentence about one database.
    # A pool handed a store reading elsewhere would serve every score of every
    # poisoned branch while an operator read a fully-marked tree, and the failure
    # would be invisible.
    #
    # The refusal is on *use* rather than at construction, deliberately: building
    # the pool is composition-time work and touches no disk, so the earliest
    # moment it can compare the two paths is the first read. That is asserted
    # here rather than assumed — the constructor must not raise.
    from tripwires import PoisonStore

    mixed = ReplayPool(pool.database_url, store=PoisonStore(other_pool.database_url))
    with pytest.raises(TripwireExcisionError, match="another database"):
        mixed.entries()


# -- The values ------------------------------------------------------------------


def test_the_branch_reports_itself_as_a_payload(pool) -> None:
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 2, tree.sibling_root_id: 1})
    _poisoned(pool, tree)

    payload = pool.excise(tree.root_id).to_payload()

    assert payload["root_node_id"] == tree.root_id
    assert payload["campaign_id"] == tree.campaign_id
    assert payload["size"] == 3
    assert payload["node_ids"] == list(tree.subtree_ids)
    assert payload["picks"] == [tree.root_id]
    assert payload["surviving_picks"] == []
    assert payload["excised_score_count"] == 2
    assert payload["pool_size"] == 3
    assert payload["surviving_score_count"] == 1
    assert payload["tripwire"] == "time-shuffle"
    assert payload["poisoned_at"]
    assert len(payload["scores"]) == 2
    assert all(entry["poisoned_by"] == tree.root_id for entry in payload["scores"])
    assert all(entry["committed_pick"] == tree.root_id for entry in payload["scores"])


def test_the_branch_is_frozen_and_compares_by_value(pool) -> None:
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1})
    _poisoned(pool, tree)
    branch = pool.excise(tree.root_id)

    assert branch == pool.excise(tree.root_id)
    assert hash(branch) == hash(pool.excise(tree.root_id))
    assert branch in {branch}, "the value is hashable, for a set"
    assert "root=" in repr(branch)
    with pytest.raises(AttributeError, match="frozen"):
        branch._root_node_id = tree.child_id


def test_the_pool_row_is_frozen_and_compares_by_value(pool) -> None:
    tree = _seed(pool)
    _seeded(pool, {tree.sibling_root_id: 1})
    _poisoned(pool, tree)
    row = pool.survivors()[0]

    assert row == pool.survivors()[0]
    assert hash(row) == hash(pool.survivors()[0])
    assert "policy=" in repr(row)
    assert row.to_payload()["committed_pick"] == tree.sibling_root_id
    assert row.created_at.tzinfo is not None
    with pytest.raises(AttributeError, match="frozen"):
        row._score = 0.0


def test_the_excised_score_carries_the_failure_that_condemned_it(pool) -> None:
    # A descendant was not probed — it was *in the wrong branch* — so the row's
    # accounting belongs to the failure that marked the branch rather than to the
    # descendant that happened to be picked. This is feature 131's central claim
    # read from the other side, and it is the one field an operator acting on a
    # refusal needs: *which* failure cost this score.
    tree = _seed(pool)
    _seeded(pool, {tree.child_id: 1})
    _poisoned(pool, tree)

    entry = pool.refused()[0]

    assert isinstance(entry, ExcisedScore)
    assert entry.poisoned_by == tree.root_id, "the failing node, not the child"
    assert entry.score.committed_pick == tree.child_id, "...which is the row's own"
    assert entry.tripwire == "time-shuffle"
    assert entry.to_payload()["poisoned_by"] == tree.root_id
    assert "poisoned_by=" in repr(entry)
    with pytest.raises(AttributeError, match="frozen"):
        entry._poisoned_by = tree.child_id


def test_the_branch_value_refuses_a_shape_its_own_read_cannot_produce(pool) -> None:
    # The value validates, so a record built by hand — or by a later feature
    # whose producer drifted — fails loudly rather than carrying an excision that
    # never happened. Each refusal below is a state the pool's own read cannot
    # produce, which is what makes them invariants rather than preferences.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1})
    _poisoned(pool, tree)
    real = pool.excise(tree.root_id)
    entry = real.scores[0]
    common = {
        "campaign_id": tree.campaign_id,
        "poisoned_at": real.poisoned_at,
        "pool_size": 1,
        "tripwire": "time-shuffle",
    }

    with pytest.raises(TripwireExcisionError, match="at least the failing node"):
        ExcisedBranch(root_node_id=tree.root_id, node_ids=(), scores=(), **common)
    with pytest.raises(TripwireExcisionError, match="first node must be the failing"):
        ExcisedBranch(
            root_node_id=tree.root_id,
            node_ids=(tree.child_id, tree.root_id),
            scores=(),
            **common,
        )
    with pytest.raises(TripwireExcisionError, match="names each node once"):
        ExcisedBranch(
            root_node_id=tree.root_id,
            node_ids=(tree.root_id, tree.root_id),
            scores=(),
            **common,
        )
    # A score some *other* failure excised: folding two failures into one report
    # would make the branch unanswerable for an operator reading it.
    other_root = str(uuid.uuid4())
    with pytest.raises(TripwireExcisionError, match="one failure's account"):
        ExcisedBranch(
            root_node_id=other_root,
            node_ids=(other_root,),
            scores=(entry,),
            **common,
        )
    # A score committing to a node the branch does not contain — another
    # branch's row, which excising would refuse evidence nothing condemned. The
    # entry is attributed to *this* branch's root so the membership check is the
    # one that fires rather than the attribution check above.
    stray = ExcisedScore(
        score=entry.score, poisoned_by=tree.child_id, tripwire="time-shuffle"
    )
    with pytest.raises(TripwireExcisionError, match="does not contain"):
        ExcisedBranch(
            root_node_id=tree.child_id,
            node_ids=(tree.child_id,),
            scores=(stray,),
            **common,
        )
    # Feature 365 as a construction invariant: a branch the pool still serves.
    with pytest.raises(TripwireExcisionError, match="0 surviving nodes"):
        ExcisedBranch(
            root_node_id=tree.root_id,
            node_ids=(tree.root_id,),
            scores=(),
            surviving_picks=(tree.root_id,),
            **common,
        )
    # More refused rows than the pool holds: the count and the rows describe
    # different pools.
    with pytest.raises(TripwireExcisionError, match="fewer than none"):
        ExcisedBranch(
            root_node_id=tree.root_id,
            node_ids=(tree.root_id,),
            scores=(entry, entry),
            **common,
        )


def test_a_pool_row_whose_columns_are_not_what_they_claim_is_refused() -> None:
    # The row is the pool's own storage, and a corrupted or hand-written one must
    # be refused by name rather than aggregated: a blank policy version cannot be
    # attributed to a revision, and a non-finite score would reach §C5's argmax
    # dressed as a measured number.
    common = {
        "id": str(uuid.uuid4()),
        "world_id": str(uuid.uuid4()),
        "beta": 1.0,
        "score": 0.5,
        "committed_pick": None,
        "is_holdout": False,
        "created_at": dt.datetime(2024, 6, 3, tzinfo=dt.UTC),
    }
    with pytest.raises(TripwireExcisionError, match="policy version"):
        PoolScore(policy_version="", **common)
    with pytest.raises(TripwireExcisionError, match="not finite"):
        PoolScore(policy_version="v", **{**common, "score": float("nan")})
    with pytest.raises(TripwireExcisionError, match="must be a number"):
        PoolScore(policy_version="v", **{**common, "beta": "1.0"})
    # A BOOLEAN column is SQLite's type by affinity only: the driver hands back
    # the integer the row holds, so 0 and 1 are read as the two bits they are —
    # and anything else is refused rather than coerced, because bool(2) is True
    # and would move a corrupt row into the half §7 judges a selection on.
    with pytest.raises(TripwireExcisionError, match="must be a bool or the integer"):
        PoolScore(policy_version="v", **{**common, "is_holdout": 2})
    assert PoolScore(policy_version="v", **common).is_holdout is False
    assert (
        PoolScore(policy_version="v", **{**common, "is_holdout": 1}).is_holdout
        is True
    )


def test_an_excised_score_refuses_anything_that_is_not_a_row() -> None:
    # The refusal is *about* a row, and a report carrying a bare number would not
    # say which row the pool stopped serving.
    with pytest.raises(TripwireExcisionError, match="wraps a pool row"):
        ExcisedScore(score=1.5, poisoned_by=str(uuid.uuid4()), tripwire="time-shuffle")


def test_an_unparseable_stored_instant_is_refused_rather_than_returned(pool) -> None:
    # A caller comparing a string against a datetime would find them unequal
    # always, so a pool that silently ordered by text that is not a date is worse
    # than one that stops. The column is written by the replay member, but it is
    # a column other writers can reach — and the refusal is the *pool's* error,
    # so a §C5 loop catching that error catches this too.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1})
    score_id = _raw_rows(pool)[0][0]
    connection = sqlite3.connect(pool.path)
    connection.execute(
        "UPDATE replay_score SET created_at = 'not-a-date' WHERE id = ?",
        (score_id,),
    )
    connection.commit()

    with pytest.raises(TripwireExcisionError, match="could not be parsed"):
        pool.survivors()
    with pytest.raises(TripwireExcisionError, match="could not be parsed"):
        pool.entries()


def test_the_branch_is_the_record_s_subtree_not_the_tree_s_current_shape(pool) -> None:
    # `subtree_of` reads the audit table rather than re-walking `parent_id`,
    # deliberately: the table records the acts, so a node added beneath a poisoned
    # node *after* the failure is not part of what that failure marked and must
    # not have its scores refused by a later read of the same branch.
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1, tree.sibling_root_id: 1})
    _poisoned(pool, tree)
    late = str(uuid.uuid4())
    connection = sqlite3.connect(pool.path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
        "VALUES (?, ?, ?, ?, ?)",
        (late, tree.leaf_id, tree.campaign_id, "test-theme", 3),
    )
    connection.commit()
    seed_pool(connection, [late])

    branch = pool.excise(tree.root_id)

    assert late not in branch.node_ids
    assert _picks(pool) == {tree.sibling_root_id, late}


def test_the_pool_lists_the_branches_the_record_holds(pool) -> None:
    # The pool's answer to "which branches is this database holding refused?" —
    # read from the record of the acts, so a failure that happened before this
    # process started is listed exactly as one it watched happen. A replay path
    # sweeping a database it did not write asks this question.
    tree = _seed(pool)
    _poisoned(pool, tree, tree.root_id)
    pool.marks.poison(_failure(tree.sibling_root_id))

    assert pool.excised_roots() == (tree.root_id, tree.sibling_root_id)
    assert pool.poisoned(tree.root_id) is True
    assert pool.poisoned(tree.sibling_root_id) is True
    assert pool.poisoned(tree.leaf_id) is True, "a descendant carries the mark too"


# -- The entry points and the component ------------------------------------------


def test_the_module_level_entry_point_runs_the_whole_feature(pool) -> None:
    tree = _seed(pool)
    _seeded(pool, {tree.root_id: 1, tree.child_id: 1, tree.sibling_root_id: 1})
    _poisoned(pool, tree)

    branch = excise_subtree(tree.root_id, database_url=pool.database_url)

    assert branch.node_ids == tree.subtree_ids
    assert branch.excised_score_count == 2
    assert len(surviving_scores(database_url=pool.database_url)) == 1


def test_a_call_that_names_no_pool_refuses_to_pretend_it_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The degrade-don't-break split: the *builder* answers None (composition must
    # not fail), while the entry point refuses, because a replay loop that cannot
    # apply the refusal must not proceed as though it had — §C5's dreaming loop
    # would go on aggregating the very evidence the tripwire rejected.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(TripwireExcisionError, match="no pool to excise from"):
        excise_subtree(str(uuid.uuid4()), pool=None, database_url=None)
    with pytest.raises(TripwireExcisionError, match="no pool to excise from"):
        surviving_scores(pool=None, database_url=None)


def test_a_database_url_this_member_cannot_speak_is_refused_in_the_pool_s_terms() -> None:
    # A URL this member cannot speak has to be refused by the *pool*, not by the
    # store whose schema the pool borrows: a caller that writes
    # `except TripwireExcisionError` around the replay path is the one caller
    # that must not be handed feature 131's error for a misrouted DATABASE_URL.
    with pytest.raises(TripwireExcisionError, match="could not be addressed"):
        ReplayPool("postgresql://localhost/nullius").entries()
    with pytest.raises(TripwireExcisionError, match="could not be addressed"):
        ReplayPool("sqlite://").entries()
    with pytest.raises(TripwireExcisionError, match="could not be addressed"):
        ReplayPool("sqlite://elsewhere/t.db").entries()
    with pytest.raises(TripwireExcisionError, match="non-empty database URL"):
        ReplayPool("   ")


def test_the_composed_component_is_the_pool_the_seat_reaches(
    monkeypatch: pytest.MonkeyPatch, pool
) -> None:
    # The plugin seam from the refusal side: the factory's scan imports the
    # member, its @register fires, and a composed application carries the pool for
    # the deployment the process is running in — reachable by way of the app
    # namespace, which is how §C5's dreaming loop will ask for it.
    from pathlib import Path

    import tripwires

    from app.module_loader import Application, Registration, create_app
    from app.modules.tripwires.excise import COMPONENT_NAME as SEAT_NAME
    from app.modules.tripwires.excise import replay_pool_component

    monkeypatch.setenv(DATABASE_URL_ENV, pool.database_url)
    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    composed = application.get(EXCISE_COMPONENT_NAME)
    assert type(composed).__name__ == "ReplayPool"
    assert replay_pool_component(application) is composed
    # The three seats answer three different questions, and the newest is a
    # component rather than an accessor on an older one.
    assert type(application.get("tripwires")).__name__ == "TimeShuffleTripwire"
    assert type(application.get("tripwires-poison")).__name__ == "PoisonStore"
    assert SEAT_NAME == EXCISE_COMPONENT_NAME == "tripwires-excise"
    # A pool registered but not yet used: composition opens no database.
    assert not Path(composed.path).exists()
    assert replay_pool_component(Application(components={}, order=())) is None


def test_the_composed_pool_reads_its_marks_through_the_composed_store(
    monkeypatch: pytest.MonkeyPatch, pool
) -> None:
    # The two components are two halves of one §C6 sentence, so a caller holding
    # the pool must be able to read the mark that condemned a row without
    # composing a second object graph. `marks` is that seam, and it names the same
    # database as the store feature 131's own seat hands back.
    from pathlib import Path

    import tripwires

    from app.module_loader import Registration, create_app

    monkeypatch.setenv(DATABASE_URL_ENV, pool.database_url)
    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    assert application.get(EXCISE_COMPONENT_NAME).marks.path == pool.path
    assert application.get("tripwires-poison").path == pool.path


def test_an_unconfigured_deployment_composes_no_pool_but_does_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    import tripwires

    from app.module_loader import Registration, create_app

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    assert application.get(EXCISE_COMPONENT_NAME) is None
    assert type(application.get("tripwires")).__name__ == "TimeShuffleTripwire"


def test_the_pool_component_resolves_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, pool
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, pool.database_url)
    resolved = ReplayPool.resolve()
    assert isinstance(resolved, ReplayPool)
    assert resolved.database_url == pool.database_url

    monkeypatch.delenv(DATABASE_URL_ENV)
    assert ReplayPool.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert ReplayPool.resolve() is None, "whitespace counts as unset"


def test_the_bootstrap_adopts_the_pool_the_migration_would_have_built(pool) -> None:
    # The bootstrap is `IF NOT EXISTS` on every statement, so a database the
    # migration already built is adopted rather than fought. This is the property
    # that makes it safe against production, and it is checked twice: the shape
    # is 0109's eight columns, and re-running the bootstrap leaves the DDL
    # byte-for-byte as it was — nothing added, in particular no `excised_at`.
    pool.ensure_schema()
    connection = sqlite3.connect(pool.path)
    shape = {row[1] for row in connection.execute("PRAGMA table_info(replay_score)")}
    assert shape == {
        "id",
        "policy_version",
        "world_id",
        "beta",
        "score",
        "committed_pick",
        "is_holdout",
        "created_at",
    }
    before = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'replay_score'"
    ).fetchone()[0]
    pool.ensure_schema()
    after = (
        sqlite3.connect(pool.path)
        .execute("SELECT sql FROM sqlite_master WHERE name = 'replay_score'")
        .fetchone()[0]
    )
    assert before == after


def test_a_row_the_migration_s_own_defaults_wrote_still_reads_back(pool) -> None:
    # The bootstrap's defaults must produce rows this pool can read: a row
    # inserted with no `id`, no `created_at` and no `is_holdout` — the shape
    # 0109's own DDL permits — is one the pool must be able to serve. The
    # `created_at` default is the dialect-split one, whose parenthesised
    # expression is the whole reason `_SQLITE_NOW_DEFAULT` exists separately
    # from the call that uses it.
    pool.ensure_schema()
    connection = sqlite3.connect(pool.path)
    connection.execute(
        "INSERT INTO replay_score (policy_version, world_id, beta, score) "
        "VALUES ('v1', ?, 1.0, 0.5)",
        (str(uuid.uuid4()),),
    )
    connection.commit()

    row = pool.survivors()[0]
    assert row.policy_version == "v1"
    assert row.committed_pick is None, "no node, so it contributes to no branch"
    assert row.is_holdout is False
    assert row.created_at.tzinfo is not None


def test_the_probe_suite_still_needs_no_database() -> None:
    # The property features 131 and 132 must not cost the member. The probe is a
    # pure function of two mappings and is what the frozen evaluator image
    # imports, so it must keep composing and probing with nothing configured — no
    # DATABASE_URL, no store, no pool, no file. This test names no fixture, which
    # is the assertion: a probe that had grown a database dependency would have
    # shown up as a fixture this file needed, and every fixture above is
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
    # Both stores compose beside it, or do not — the point is that the probe's
    # path does not care which. An unconfigured deployment is the case this
    # asserts on, so both seats answering `None` is the expected outcome.
    assert application.get("tripwires-poison") is None
    assert application.get(EXCISE_COMPONENT_NAME) is None
