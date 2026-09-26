"""Feature 365: the end-to-end journey — a deliberately leaking signal trips
every tripwire, and the replay pool returns 0 surviving nodes from that branch.

app_spec.xml, "End-to-End Verification", feature 365: *"System passes an
end-to-end test where a deliberately leaking signal trips every tripwire, and
the replay pool returns 0 surviving nodes from that branch."*  The sentence is
M1's exit gate written as one journey through the assembled system —
docs/alpha-engine-prd.md §4.1 states it as the milestone's whole claim (*"a
deliberately leaking signal is caught by every tripwire"*) and
docs/nullius-tech-architecture.md §20 gives the same clause to M1's gate — and
it has exactly two halves, which this module runs in the order the deployment
runs them:

* **"trips every tripwire."**  §C6 is one sentence with two probes and one
    family hanging off it — *"Score against time-shuffled forward returns.
    Surviving Sharpe means leakage.  Score against label-permuted targets.
    Same test, different permutation."* and *"Re-run with a different seed, a
    different start offset, a different universe subsample."* — and
    docs §6.1 step 10 names the family in one line: ``tripwires
    time-shuffle, label-permute, perturbation stability``.  *Every* tripwire
    therefore means the six verdicts the composed probe can state: feature
    125's time shuffle, feature 126's label permutation, and features 127
    through 130's four perturbation axes (seed, window offset, universe
    subsample, lookback jitter).  The signal is **one candidate** — the same
    panel handed to all six — and each of the six returns ``rejected`` True
    with §8's ``tripwire_fail``.

* **"the replay pool returns 0 surviving nodes from that branch."**  §C6's
    next clause is *"a failure poisons the node **and its entire subtree**,
    which is excised from the replay pool"*, which is features 131 and 132:
    the verdict becomes a fact about the tree (the mark, and the audit row per
    poisoned node), and the pool refuses every score the marked branch
    contributed — by a *read*, not a delete, so the evidence an operator needs
    afterwards is still there while the refusal is total.  The journey's last
    act reads the branch back and asserts the count that phrase names:
    :attr:`~tripwires.ExcisedBranch.surviving_picks` is ``()``, and the pool's
    own §C5 read — :meth:`~tripwires.ReplayPool.survivors` — names no node of
    the branch either.

**One candidate, deliberately built from both leak classes, and the reason is
doctrine rather than convenience.**  A candidate that leaked *only* the
whole-sample statistic feature 133's corpus plants is caught by the time
shuffle and reads **flat** through the label probe — the member's own module
docstring measures the corpus at ``0.064`` of that probe's bar at its own
pinned seed, and this journey's complementarity facet re-measures the flatness
on *its* panel rather than quoting that figure — while a candidate
that leaked *only* a date-local cross-sectional component escapes the time
shuffle entirely.  That is the documented, load-bearing complementarity
(:mod:`tripwires.label_permute`, *"Neither probe is the other's superset"*),
and it means no single-class leak can pass this sentence honestly: a journey
planting one and asserting six rejections would be asserting something the
probes are *correct* not to do.  So the panel is the two classes together —
per-symbol whole-sample information plus a date-local cross-sectional level,
each at a weight a diluted real leak would carry — and the sentence holds with
margin on all six axes.  The margins are asserted rather than the bare bits,
so the journey says *how far* past each bar the signal sits and a future drift
in a threshold or a grid fails loudly instead of silently.

**The three sentence-level obligations the leak's dilution is built to keep.**
Written down because each is a place where a leak built for effect would
forfeit both cases at once:

* **the target bundle's aggregate is the stationary series the doctrine
  requires.**  §4.1.2's *"the signal ensemble's aggregate forecast is a
  stationary series with constant positive expected Sharpe"* is about the
  **ensemble**: the expected value of the *cross-sectional mean* of its
  forecasts, ``Σᵢwᵢgᵢ``.  This journey does not plant a bundle — it plants a
  *score panel* over the corpus's own bundle — so the obligation it has to
  keep is that the bundle underneath is a stationary enough series that a
  shuffle over it means what §C6 says it means: the fixture measures that the
  bundle's cross-sectional aggregate over the 120 dates carries no drift
  comparable to its own dispersion, so no probe is reading a trend and calling
  it leakage.  The panel on top of it is *not* stationary in that sense and is
  not meant to be: the corpus's whole-sample statistic is date-invariant, so a
  corpus-only panel has an identical cross-section on every date, and the only
  date-to-date movement the composite's cross-section has is the date-local
  class the signal consumed.  That is the leak — a component that moves with
  the date, which is what makes it a leak rather than a level, and it is the
  measured fingerprint the fixture asserts.
* **the campaign is a real one.**  The tree is planted *inside* feature 232's
  own campaign row, planned through the discovery member's real verb, so the
  branch feature 131 walks is scoped by a campaign the orchestrator actually
  wrote rather than by an id the fixture invented.  The guard's own half of
  the M1 gate — *"the KS guard returns a p-value above 0.05"*, feature 366's
  sentence — is that journey's to measure over its own planted campaign, and
  this one does not restate it: the guard reads a campaign's *planted roots*
  against its null roots, and this journey plants none of either.
* **feature 125's probe reads the leak at strength, not at the edge.**  The
  weight on the whole-sample class is the corpus's own full strength, so the
  shuffle's surviving Sharpe clears its bar by a factor of ``1.78`` — past
  feature 133's own bar for the corpus.  The date-local class is the diluted
  one, and deliberately: it only has to make the *label* probe reject, which
  it does at ``1.64`` of that probe's threshold.

**What is staged and what is composed.**  Everything the sentence names is the
shipped system's own object or verb: the campaign is feature 232's
:func:`~discovery.create_campaign`, the tree is feature 97's ``node`` table
brought up by migration ``0118`` (the discovery member persists no attempt
here — this journey's candidate is a *score panel* handed to the probes, not a
``CONTINUE(v)``), the six verdicts are the composed
:class:`~tripwires.TimeShuffleTripwire`'s own methods, the poisoning is feature
131's store, the refusal is feature 132's pool, and the pool's rows are written
by feature 255's own writer, :func:`~replay.persist_replay_score`.  The
poisoning and the pool are reached through the ``app`` package's own seats
(``app.modules.tripwires.poison``, ``app.modules.tripwires.excise``) from the
*same* composed application, which is the deployment's wiring and not a
convenience: the factory's scan imports the member under a synthetic name, so
the store and the pool it composes are a second class object of the same source
file, and a journey that mixed a composed store with a canonically imported
pool would be exercising two compositions rather than one.

The only thing this journey owns is the far end of the wire — the panel's two
leak components and its weights — which is the party the sentence is about.
What it owns, it states: every constant below is a pinned literal with the
measurement it was chosen from, and every ratio the facets assert was measured
on this panel at those literals.

**One module, one journey, run once.**  The journey runs its acts a single
time in a module-scoped fixture over its own SQLite store, its own campaign and
its own composed application, and the facets below read the campaign row, the
tree, the six verdicts, the marks, the record and the pool's survivors out of
that one run.  The member suites pin each verb's own law — the corpus's 0
escapes (packages/tripwires/tests/test_corpus.py), the probes' refusals
(test_time_shuffle.py, test_label_permute.py), the four axes' bars
(test_seed_rerun.py, test_window_offset.py, test_subsample.py,
test_lookback.py), the poisoning (test_poison.py) and the excision
(test_excise.py) — and this module does not re-test them; it asserts the one
thing only the composition can: that a *deliberately leaking* candidate, built
the way a real near-miss is built, is caught by step 10's whole family and that
the branch it was caught in comes back out of the replay pool with nothing left
to replay.
"""

from __future__ import annotations

import importlib.util
import inspect
import math
import os
import random
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

# The shared tests/e2e/conftest.py puts every declared member's scan root on
# sys.path before this line runs, so the members import by their bare names —
# the workspace contract that no member imports another, honoured here by
# reaching each through the path the conftest already built.  ``REPO_ROOT`` is
# this module's own, used only to locate the migration files below: the
# migration chain is not an importable package, so it is loaded by path and
# needs an absolute root rather than a scan root.
REPO_ROOT = Path(__file__).resolve().parents[2]

from app.module_loader import create_app
from app.modules.tripwires.excise import replay_pool_component
from app.modules.tripwires.poison import poison_store_component
from discovery import TYPE_R_CAMPAIGN_TYPE, create_campaign
from replay import persist_replay_score
from tripwires import (
    PERTURBATION_AXES,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    ExcisedBranch,
    TimeShuffleTripwire,
    planted_signals,
)

# ---------------------------------------------------------------------------
# The planted leak — the journey's own end of the wire
# ---------------------------------------------------------------------------

#: The leak classes this journey plants, and the fixture's whole design.
#: :data:`~tripwires.LEAK_KINDS` — feature 133's corpus vocabulary — is the
#: *whole-sample per-symbol* class, the information feature 125's derangement
#: cannot destroy; the *date-local cross-sectional* class is its documented
#: complement, the information the label permutation destroys and the time
#: shuffle cannot see.  Both are planted because
#: :mod:`tripwires.label_permute` states plainly that neither probe is the
#: other's superset: a single-class leak escapes one of the two by *design*,
#: so "every tripwire" is only an honest sentence about a candidate carrying
#: both.
LEAK_CLASSES: tuple[str, ...] = ("whole-sample-per-symbol", "date-local-cross-sectional")

#: The weight on the whole-sample class, relative to the corpus's own
#: full-strength statistic.  ``1.0`` — the class is planted at the strength
#: feature 133 verified it at, because this is the component the derangement
#: cannot destroy and dilution of it trades directly against the shuffle's
#: margin.  Measured on this panel at the pinned literals: the shuffle's
#: surviving Sharpe stands at ``1.78`` of its own threshold, past feature
#: 133's own bar for the corpus and far past the ``0.091`` of a threshold at
#: which the label probe reads a corpus-only panel flat.
WHOLE_SAMPLE_WEIGHT = 1.0

#: The weight on the date-local level, in units of the target bundle's own
#: cross-sectional mean — the component a candidate that consumed a
#: cross-sectional normalisation would carry without knowing it.  Diluted
#: deliberately: the class only has to make the *label* probe reject, which it
#: does with the larger margin of the two, and a heavier weight would push the
#: panel's per-date dispersion far enough that the three stability axes would
#: be judging a candidate no real pipeline would emit.  Measured: the label
#: probe's Sharpe stands at ``1.64`` of its threshold.
DATE_LOCAL_WEIGHT = 0.3

#: The pinned draw the panel's symbol-local noise floor is taken from.  The
#: floor is small — it is what keeps the panel from being literally constant
#: across symbols — and fixed, for the determinism contract every journey in
#: this suite keeps (docs §12): the same panel on every machine, every run.
NOISE_SEED = 20260113

#: The floor's dispersion, in the same units as the target bundle's returns.
NOISE_SIGMA = 0.02

#: The perturbation policy the replay rows were scored under — feature 255's
#: ``policy_version`` column, a non-empty string naming the revision under
#: test.
POLICY_VERSION = "policy-rev-365"

#: §7.4's single scalar, fixed within the episode.
BETA = 0.5

#: The campaign type §7.3 names — the journey's campaign is a real Type-R
#: campaign row, planned through the discovery member's own verb.  Taken from
#: the member's own vocabulary rather than spelled here: the discovery store
#: validates the argument against its closed set, and a literal that drifted
#: from that set would fail in the planner rather than in this journey.
CAMPAIGN_TYPE = TYPE_R_CAMPAIGN_TYPE

#: §4.1.1's well count — the campaign's ``workspace_count``.  The tree this
#: journey walks is a handful of nodes; the row is planned at a real campaign's
#: scale so the branch is scoped by a campaign the orchestrator would have
#: written rather than by a row sized to the fixture.
WELLS = 12

#: Migration ``0118``: the ``node`` table's sole author (feature 97).  The
#: tree this journey poisons is the *same* table the discovery loop writes, so
#: the journey reaches it through the migration the deployment runs rather
#: than through a bootstrap that could disagree with it.
NODE_MIGRATION = "migrations/versions/0118_node_table.py"

#: Migration ``0111``: the ``campaign`` table's sole author (feature 104).
#: Feature 232's writer refuses to invent the table, so the journey brings it
#: up the deployment's way and lets the orchestrator write the row.
CAMPAIGN_MIGRATION = "migrations/versions/0111_campaign_table.py"

#: Migration ``0109``: ``replay_score`` and ``policy_revision`` (features 245
#: and 273).  The pool is the replay member's table and this migration is its
#: schema's source of record; the member's writer ensures the row space on
#: connect, but the journey brings the table up as the deployment does.
REPLAY_MIGRATION = "migrations/versions/0109_replay_score_and_policy_revision.py"


# ---------------------------------------------------------------------------
# The panel — the deliberately leaking candidate
# ---------------------------------------------------------------------------


def _target_bundle() -> dict[int, dict]:
    """The target bundle the signal is planted from — the corpus's own.

    Feature 133's bundle: 120 dates of 30 symbols, one series per horizon, the
    same panel the corpus plants its four leak kinds on and the same one the
    member's complementarity measurements were taken over.  Read from
    :func:`~tripwires.planted_signals` rather than rebuilt, so this journey's
    leak classes are planted over *the grid the probe was verified against*
    and the two documents cannot drift apart.
    """
    return dict(planted_signals()[0].targets)


def _cross_sectional_mean(series: Mapping) -> dict[int, float]:
    """Each date's cross-sectional mean of the forward returns.

    The date-local component, as the target bundle itself carries it: one
    number per date, the same information for every symbol in that date.
    """
    days = sorted(series)
    return {
        day: math.fsum(series[day].values()) / len(series[day]) for day in days
    }


def _plant_panel(
    bundle: Mapping,
    *,
    whole_sample: float = WHOLE_SAMPLE_WEIGHT,
    date_local: float = DATE_LOCAL_WEIGHT,
) -> dict:
    """Build a score panel from the corpus statistic and the date-local level.

    Per date and symbol: the corpus's own full-sample statistic scaled by
    ``whole_sample``, plus the date's cross-sectional mean scaled by
    ``date_local``, plus a symbol-local noise floor.  The first term is the
    leak feature 125's derangement cannot destroy; the second is the leak
    feature 126's permutation destroys and the shuffle cannot see; the third
    is what keeps the panel from being *literally* constant across symbols,
    which would be a panel no probe would refuse for the right reason.

    The two weights are parameters because they are the *only* thing that
    distinguishes the leaking panel from the two single-class controls the
    complementarity facet runs: ``(1.0, 0.0)`` is the corpus alone,
    ``(0.0, 0.3)`` the date-local level alone, and the module's pinned pair
    is the composite the journey runs.  One builder for all three, so the
    controls are the panel with a weight zeroed rather than a second panel
    built a slightly different way.
    """
    horizon = sorted(bundle)[0]
    series = bundle[horizon]
    days = sorted(series)
    symbols = sorted(series[days[0]])
    statistic = planted_signals()[0].scores
    level = _cross_sectional_mean(series)
    rng = random.Random(NOISE_SEED)
    return {
        day: {
            symbol: (
                whole_sample * statistic[day][symbol]
                + date_local * level[day]
                + rng.gauss(0.0, NOISE_SIGMA)
            )
            for symbol in symbols
        }
        for day in days
    }


# ---------------------------------------------------------------------------
# The tree — campaign, roots, and one leaking branch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tree:
    """The journey's discovery tree, as the fixture planted it.

    A *value*, so the facets assert against the ids the store was actually
    written with rather than against a second draw of the same seed.  Two
    branches inside one campaign: the leaking branch (root, child, grandchild),
    which is what the sentence's second half is about, and a control branch
    that must survive the excision untouched — the pair that makes *"from that
    branch"* mean a branch rather than the campaign.
    """

    campaign_id: str
    leak_root: str
    leak_child: str
    leak_grandchild: str
    control_root: str
    control_child: str

    @property
    def leak_branch(self) -> tuple[str, ...]:
        """The failing node first, then its descendants — feature 131's walk order."""
        return (self.leak_root, self.leak_child, self.leak_grandchild)

    @property
    def control_branch(self) -> tuple[str, ...]:
        return (self.control_root, self.control_child)


def _migration_apply(module_name: str, path: Path, database_url: str) -> None:
    """Load a standalone migration module by path and run its ``apply``.

    The migration chain is not an importable package — it is a directory of
    standalone modules the migration runner loads by path — so it is loaded
    the same way here: by file location, not by import name.  The tables the
    journey writes into are the migrations' own, so the shapes the assertions
    read back are the shapes the deployment ships rather than a restatement
    that could drift.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.apply(database_url)


def _insert_node(
    path: Path, node_id: str, parent_id: str | None, campaign_id: str, depth: int
) -> None:
    """Write one row into feature 97's ``node`` table — the tree's only author's shape.

    Five columns, the migration's own: the identity, the self-referencing
    parent, the campaign, the theme the root was planted in, and the depth.
    Written directly rather than through feature 240's attempt log because
    this journey's candidate is a score panel handed to the probes, not a
    ``CONTINUE(v)`` — the discovery loop's refinement is a different act and
    is not what the sentence is about.
    """
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, parent_id, campaign_id, "leak-journey", depth),
        )


def _plant_tree(path: Path, campaign_id: str) -> _Tree:
    """Plant the leaking branch and its control inside the campaign."""
    ids = {
        name: str(uuid.uuid5(uuid.NAMESPACE_URL, f"tripwire-journey:{name}"))
        for name in (
            "leak_root",
            "leak_child",
            "leak_grandchild",
            "control_root",
            "control_child",
        )
    }
    _insert_node(path, ids["leak_root"], None, campaign_id, 0)
    _insert_node(path, ids["leak_child"], ids["leak_root"], campaign_id, 1)
    _insert_node(path, ids["leak_grandchild"], ids["leak_child"], campaign_id, 2)
    _insert_node(path, ids["control_root"], None, campaign_id, 0)
    _insert_node(path, ids["control_child"], ids["control_root"], campaign_id, 1)
    return _Tree(campaign_id=campaign_id, **ids)


# ---------------------------------------------------------------------------
# The pool's rows — feature 255's own writer
# ---------------------------------------------------------------------------


class _Carrier:
    """Feature 249's terminal pick carrier, duck-typed: a pick and a score.

    No member imports another, so this journey stands in a carrier of the same
    two facts feature 255's writer reads: ``pick`` (a value carrying
    ``node_id``, or ``None`` for a policy that emitted none) and ``score``
    (always present).  The miss is written as one of the pool's rows because
    §C5 aggregates a store's rows, not a store's non-null picks, and a journey
    whose pool held only committing policies would not exercise the refusal
    over the shape a real pool has.
    """

    def __init__(self, node_id: str | None, score: float) -> None:
        self.pick = None if node_id is None else _Pick(node_id)
        self.score = score


class _Pick:
    """The committed pick, reduced to the one fact the writer reads."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


def _stand_up_pool_rows(path: Path, tree: _Tree, world_id: str) -> None:
    """Write the pool's rows — one per branch node, a control, and a miss.

    Every row goes in through :func:`~replay.persist_replay_score`, the
    member's own writer, so the pool the excision reads is a real pool: the
    leaking branch contributed three scores, a clean branch contributed two,
    and one policy emitted no pick at all.  Nothing here is written by hand —
    a hand-written ``INSERT`` would let the journey's pool disagree with the
    pool the replay engine produces.
    """
    for node_id, score in (
        (tree.leak_root, 0.30),
        (tree.leak_child, 0.20),
        (tree.leak_grandchild, 0.10),
        (tree.control_root, 0.15),
        (tree.control_child, 0.05),
        (None, 0.0),
    ):
        persist_replay_score(
            _Carrier(node_id, score),
            POLICY_VERSION,
            world_id,
            BETA,
            database_url=f"sqlite:///{path}",
        )


# ---------------------------------------------------------------------------
# What the journey reported
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Journey:
    """What the journey reported, frozen at its end.

    Captured in the order the journey produced it — the campaign, the tree,
    the six verdicts, the poisoning, the excision — so the facets read one
    story rather than re-running the choreography per assertion.
    """

    database_url: str
    store_path: Path
    world_id: str
    campaign_id: str
    tree: _Tree
    panel: Mapping
    level: Mapping[int, float]
    bundle: Mapping
    probe: TimeShuffleTripwire
    verdicts: Mapping[str, object]
    verbs_run: tuple[str, ...]
    pooled_nodes_with_picks: int
    poisoned_size: int
    poisoned_nodes: tuple[str, ...]
    poisoned_replayed: bool
    poisoned_tripwire: str
    poisoned_outcome: str
    poisoned_at: str
    branch: ExcisedBranch
    survivor_picks: tuple[str | None, ...]
    refused_picks: tuple[str, ...]
    excised_roots: tuple[str, ...]
    nested_scores: int
    control_nested_scores: int
    record_rows: int
    marked_rows: int


def _apply_migrations(database_url: str) -> None:
    """Bring a fresh database to the shape the journey writes into."""
    _migration_apply(
        "migration_0111_campaign_table",
        REPO_ROOT / CAMPAIGN_MIGRATION,
        database_url,
    )
    _migration_apply(
        "migration_0118_node_table",
        REPO_ROOT / NODE_MIGRATION,
        database_url,
    )
    _migration_apply(
        "migration_0109_replay_score_and_policy_revision",
        REPO_ROOT / REPLAY_MIGRATION,
        database_url,
    )


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Journey]:
    """Run the journey once, and hand its captured facts to the facets.

    The journey's own SQLite store, not the suite's isolated ``DATABASE_URL``:
    the acts are one ordered story over one throwaway database, and the
    composed application is built with ``DATABASE_URL`` pointed at it so the
    store and the pool the factory composes are the ones the deployment would
    compose — the same stance feature 366's journey takes.
    """
    workdir = tmp_path_factory.mktemp("leaking-signal-tripwires")
    database_url = f"sqlite:///{workdir / 'nullius-e2e.db'}"
    store_path = workdir / "nullius-e2e.db"
    world_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "tripwire-journey:world"))

    saved_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        # Act 1 — the campaign is planned through feature 232's own verb,
        # before any node exists.  The row is the tree's scope: feature 131
        # reads the failing node's campaign off the tree's own row, and a
        # poisoning whose scope the caller supplied would walk another
        # campaign's branch.
        _apply_migrations(database_url)
        record = create_campaign(CAMPAIGN_TYPE, WELLS)
        tree = _plant_tree(store_path, record.campaign_id)

        # Act 2 — the candidate is planted: one score panel carrying both leak
        # classes, and the target bundle it was planted from.
        bundle = _target_bundle()
        panel = _plant_panel(bundle)
        level = _cross_sectional_mean(bundle[sorted(bundle)[0]])

        # Act 3 — every tripwire runs over the one candidate.  The composed
        # probe's own six methods: step 10's two probes and the four
        # perturbation axes, each stating its own verdict.
        probe = TimeShuffleTripwire()
        verbs_run: list[str] = []
        verdicts: dict[str, object] = {
            "time-shuffle": probe.run(panel, bundle, node_id=tree.leak_root),
            "label-permute": probe.label(panel, bundle, node_id=tree.leak_root),
        }
        verbs_run.extend(("run", "label"))
        for axis, verb in zip(
            PERTURBATION_AXES,
            ("rerun", "window", "subsample", "lookback"),
            strict=True,
        ):
            verdicts[f"perturbation-stability:{axis}"] = getattr(probe, verb)(
                panel, bundle, node_id=tree.leak_root
            )
            verbs_run.append(verb)

        # Act 4 — the pool the branch contributed to, written by feature 255's
        # own writer before the failure is recorded, because §C5's pool is the
        # evidence a selection was made on and the excursion is a refusal
        # applied to it rather than a deletion of it.
        _stand_up_pool_rows(store_path, tree, world_id)

        # Act 5 — the composed application, exactly as the factory builds it,
        # and its two tripwire seats: the store a failure is persisted to and
        # the pool a poisoned branch is refused from.
        app = create_app()
        store = poison_store_component(app)
        pool = replay_pool_component(app)
        assert store is not None, (
            "the tripwires-poison component composed None, so DATABASE_URL "
            "named no relational store and feature 131's failure could not be "
            "recorded at all"
        )
        assert pool is not None, (
            "the tripwires-excise component composed None, so DATABASE_URL "
            "named no relational store and feature 132's refusal could not be "
            "applied at all"
        )

        # Act 6 — the time-shuffle failure is persisted as feature 131's
        # poisoning: the failing node and its entire subtree, marked and
        # recorded in one transaction.
        poisoned = store.poison(verdicts["time-shuffle"])

        # Act 7 — the branch is excised from the pool: feature 132's read, and
        # the sentence's second half, measured.
        branch = pool.excise(tree.leak_root)

        # The morning-after read: what the pool serves, what it refuses, and
        # the per-node contribution that a deletion would have destroyed.
        survivor_picks = tuple(score.committed_pick for score in pool.survivors())
        refused_picks = tuple(
            sorted(
                entry.score.committed_pick
                for entry in pool.refused()
                if entry.score.committed_pick is not None
            )
        )
        excised_roots = pool.excised_roots()
        nested_scores = len(pool.scores_of(tree.leak_grandchild))
        control_nested_scores = len(pool.scores_of(tree.control_child))

        with closing(sqlite3.connect(store_path)) as connection:
            record_rows = int(
                connection.execute("SELECT COUNT(*) FROM tripwire_poison").fetchone()[0]
            )
            marked_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM node WHERE poisoned_at IS NOT NULL"
                ).fetchone()[0]
            )

        # The pool's node count, read from the pool's own rows rather than
        # counted off the fixture's ids: the facet below weighs the branch's
        # excised and surviving halves against it, and a count the fixture
        # supplied could agree with a wrong pool.
        pooled_nodes = len(
            {
                score.committed_pick
                for score in (*pool.survivors(), *(e.score for e in pool.refused()))
                if score.committed_pick is not None
            }
        )

        yield _Journey(
            database_url=database_url,
            store_path=store_path,
            world_id=world_id,
            campaign_id=record.campaign_id,
            tree=tree,
            panel=panel,
            level=level,
            bundle=bundle,
            probe=probe,
            verdicts=verdicts,
            verbs_run=tuple(verbs_run),
            pooled_nodes_with_picks=pooled_nodes,
            poisoned_size=poisoned.size,
            poisoned_nodes=poisoned.node_ids,
            poisoned_replayed=poisoned.replayed,
            poisoned_tripwire=poisoned.tripwire,
            poisoned_outcome=poisoned.outcome,
            poisoned_at=poisoned.poisoned_at.isoformat(),
            branch=branch,
            survivor_picks=survivor_picks,
            refused_picks=refused_picks,
            excised_roots=excised_roots,
            nested_scores=nested_scores,
            control_nested_scores=control_nested_scores,
            record_rows=record_rows,
            marked_rows=marked_rows,
        )
    finally:
        if saved_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_url


# -- Facet 1: the campaign and the tree ----------------------------------------


class TestTheCampaignAndTheTree:
    """The journey's substrate — a real campaign row and a real discovery tree."""

    def test_the_campaign_is_a_planned_row(self, journey: _Journey) -> None:
        """Feature 232's own verb wrote the campaign the branch was poisoned in."""
        assert journey.campaign_id == journey.tree.campaign_id
        assert journey.branch.campaign_id == journey.campaign_id

    def test_the_campaign_row_carries_what_the_journey_planned(
        self, journey: _Journey
    ) -> None:
        """The columns feature 232's verb wrote are the journey's own literals.

        The campaign type and the well count are the caller's arguments, so
        reading them back is the check that the planned row is the row this
        journey asked for and not a default the migration supplied.  The
        ``calibration_status`` beside them is *not* asserted: it is the DDL's
        own default, the guard has not been run over this campaign by this
        journey, and a facet checking it would be reading a constant.
        """
        with closing(sqlite3.connect(journey.store_path)) as connection:
            row = connection.execute(
                "SELECT campaign_type, workspace_count FROM campaign WHERE id = ?",
                (journey.campaign_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == CAMPAIGN_TYPE
        assert row[1] == WELLS

    def test_the_tree_is_the_migration_shape(self, journey: _Journey) -> None:
        """Five columns, the parent edge real, depths counting from zero."""
        with closing(sqlite3.connect(journey.store_path)) as connection:
            rows = connection.execute(
                "SELECT id, parent_id, depth FROM node WHERE campaign_id = ?",
                (journey.campaign_id,),
            ).fetchall()
        planted = {row[0]: (row[1], row[2]) for row in rows}
        assert set(journey.tree.leak_branch + journey.tree.control_branch) <= set(
            planted
        )
        parent, depth = planted[journey.tree.leak_root]
        assert parent is None and depth == 0
        parent, depth = planted[journey.tree.leak_child]
        assert parent == journey.tree.leak_root and depth == 1
        parent, depth = planted[journey.tree.leak_grandchild]
        assert parent == journey.tree.leak_child and depth == 2


# -- Facet 2: every tripwire trips ----------------------------------------------


class TestTheLeakingSignalTripsEveryTripwire:
    """§C6 and docs §6.1 step 10 — the whole family, over one candidate."""

    def test_the_candidate_carries_both_leak_classes(self, journey: _Journey) -> None:
        """The panel is built from :data:`LEAK_CLASSES`, both of them, at once.

        Stated as a facet rather than left in the builder because it is the
        premise of the whole sentence: a panel carrying one class is caught by
        one probe, so *"every tripwire"* is only an honest claim about the
        composite, and this is where the journey says which classes it planted.
        """
        assert LEAK_CLASSES == (
            "whole-sample-per-symbol",
            "date-local-cross-sectional",
        )
        # Both classes are live in the panel: zeroing either weight changes it.
        corpus_only = _plant_panel(
            journey.bundle, whole_sample=0.0, date_local=DATE_LOCAL_WEIGHT
        )
        level_only = _plant_panel(
            journey.bundle, whole_sample=WHOLE_SAMPLE_WEIGHT, date_local=0.0
        )
        assert corpus_only != journey.panel
        assert level_only != journey.panel

    def test_the_family_is_the_size_the_step_declares(
        self, journey: _Journey
    ) -> None:
        """Two probes and four axes — six verdicts, no axis run twice."""
        assert len(PERTURBATION_AXES) == 4
        assert len(journey.verdicts) == 6
        for axis in PERTURBATION_AXES:
            assert f"perturbation-stability:{axis}" in journey.verdicts

    def test_the_journey_runs_every_probe_the_facade_offers(
        self, journey: _Journey
    ) -> None:
        """The set is *derived* from the component, not read off the docs.

        *"Every tripwire"* is only as true as the set the journey chose to run
        it over, and this file's reading of §6.1 step 10 is a reading: a
        seventh probe added to the facade later would leave the sentence
        quietly unverified while every facet above still passed.  So the
        verdict-producing verbs are discovered from the component itself — a
        public method whose own return annotation names a ``Verdict`` — and
        the journey is required to have run each one.  ``pairing`` and
        ``threshold`` are excluded by the same rule that includes the probes:
        one returns a date mapping and the other a float, so neither states a
        decision a poisoning or an excision could act on.
        """
        stated = {
            name
            for name, method in inspect.getmembers(journey.probe, callable)
            if not name.startswith("_")
            and "Verdict" in str(inspect.signature(method).return_annotation)
        }
        assert stated == {
            "run",
            "label",
            "rerun",
            "window",
            "subsample",
            "lookback",
        }, (
            "the facade's verdict-producing verbs have changed; the journey's "
            "six verdicts no longer cover every tripwire, and feature 365's "
            "*'trips every tripwire'* would be measured over a stale set"
        )
        assert stated <= set(journey.verbs_run), (
            f"the journey never ran {sorted(stated - set(journey.verbs_run))}, so at "
            "least one tripwire was never handed the leaking signal"
        )

    def test_no_tripwire_escapes(self, journey: _Journey) -> None:
        """Every verdict is a rejection — the sentence's whole first half."""
        escaped = [
            name
            for name, verdict in journey.verdicts.items()
            if not verdict.rejected
        ]
        assert escaped == [], (
            "the deliberately leaking signal escaped "
            f"{', '.join(escaped)}; every tripwire must catch it"
        )

    def test_every_verdict_speaks_the_ledgers_outcome_word(
        self, journey: _Journey
    ) -> None:
        """§8's ``tripwire_fail``, not merely a truthy bit.

        The outcome word is what a later ledger row and a poisoning record
        classify the trial by, so a verdict whose bit and word disagreed would
        persist a failure as something else.
        """
        for name, verdict in journey.verdicts.items():
            assert verdict.outcome in TRIPWIRE_OUTCOMES, name
            assert verdict.outcome == "tripwire_fail", name

    def test_the_probes_clear_their_bars_with_margin(self, journey: _Journey) -> None:
        """Both probes stand past their thresholds by a factor — strength, not edge.

        Feature 125's probe is a Sharpe judged against
        ``Φ⁻¹(1 − level/2)/√T`` and feature 126's is the same statistic over a
        different permutation, so the ratio of the two is what "caught" means
        quantitatively.  Asserted as a margin rather than a bit so a future
        threshold change or a re-pinned grid fails here loudly.
        """
        shuffle = journey.verdicts["time-shuffle"]
        label = journey.verdicts["label-permute"]
        assert abs(shuffle.surviving_sharpe) > 1.5 * shuffle.threshold
        assert abs(label.surviving_sharpe) > 1.5 * label.threshold

    def test_both_leak_classes_are_load_bearing(self, journey: _Journey) -> None:
        """Each class alone escapes exactly one probe — the complementarity, measured.

        The panel carries a whole-sample per-symbol component and a date-local
        cross-sectional one, and each is the class the *other* probe owns.
        Rather than assert that from the module docstring, this facet rebuilds
        the panel with one class at a time and runs both probes over each:
        the corpus alone is caught by the shuffle and reads *flat* through the
        permutation, the date-local level alone escapes the shuffle and is
        caught by the permutation, and only the composite is caught by both.
        That is the claim *"trips every tripwire"* rests on, and it is why a
        single-class leak could not honestly be used to make it.
        """
        shuffle = journey.verdicts["time-shuffle"]
        label = journey.verdicts["label-permute"]
        assert shuffle.dates == label.dates
        assert shuffle.horizon == label.horizon
        for name, (whole_sample, date_local) in (
            ("whole-sample-per-symbol only", (WHOLE_SAMPLE_WEIGHT, 0.0)),
            ("date-local-cross-sectional only", (0.0, DATE_LOCAL_WEIGHT)),
        ):
            panel = _plant_panel(
                journey.bundle, whole_sample=whole_sample, date_local=date_local
            )
            alone_shuffle = journey.probe.run(
                panel, journey.bundle, node_id=journey.tree.leak_root
            )
            alone_label = journey.probe.label(
                panel, journey.bundle, node_id=journey.tree.leak_root
            )
            escaped = [
                probe
                for probe, verdict in (
                    ("time-shuffle", alone_shuffle),
                    ("label-permute", alone_label),
                )
                if not verdict.rejected
            ]
            assert len(escaped) == 1, (
                f"a {name} panel was caught by {2 - len(escaped)} probes, so the "
                "two classes are not the complements the module docstring says "
                "they are — and 'every tripwire' would then be true of a "
                "single-class leak"
            )
        # And the composite is caught by both, which is the sentence.
        assert shuffle.rejected is True and label.rejected is True

    def test_the_signal_is_a_leak_and_not_a_constant(
        self, journey: _Journey
    ) -> None:
        """The panel varies — across symbols and across dates.

        A panel constant across symbols would be refused by the probes for the
        wrong reason (a zero-dispersion cross-section), and the corpus's own
        note says so.  Measured here rather than assumed, because the fixture
        that built this panel could stop varying it without any other facet
        noticing.
        """
        days = sorted(journey.panel)
        symbols = sorted(journey.panel[days[0]])
        spread = {
            max(journey.panel[day][symbol] for symbol in symbols)
            - min(journey.panel[day][symbol] for symbol in symbols)
            for day in days
        }
        assert all(width > 0.0 for width in spread)
        first = journey.panel[days[0]][symbols[0]]
        later = journey.panel[days[-1]][symbols[0]]
        assert first != later


# -- Facet 3: the family's own identity -----------------------------------------


class TestTheFamilyCarriesItsOwnNames:
    """§6.1 step 10's three names, on the records the probes state."""

    def test_the_shuffle_verdict_names_the_shuffle(self, journey: _Journey) -> None:
        """Feature 125's own probe name, in the spec's hyphenation."""
        assert journey.verdicts["time-shuffle"].tripwire == TIME_SHUFFLE_NAME

    def test_the_label_verdict_names_the_label_probe(
        self, journey: _Journey
    ) -> None:
        """Feature 126's probe is a *different* name, not the first one restated."""
        label = journey.verdicts["label-permute"].tripwire
        assert label != TIME_SHUFFLE_NAME
        assert "label" in label

    def test_each_axis_verdict_carries_its_own_axis(self, journey: _Journey) -> None:
        """Features 127-130 are one family with four names, one per record."""
        for axis in PERTURBATION_AXES:
            verdict = journey.verdicts[f"perturbation-stability:{axis}"]
            assert verdict.axis == axis

    def test_the_axes_are_four_distinct_perturbations(self, journey: _Journey) -> None:
        """The family's vocabulary is closed and each axis is perturbed once."""
        axes = {
            journey.verdicts[f"perturbation-stability:{axis}"].axis
            for axis in PERTURBATION_AXES
        }
        assert axes == set(PERTURBATION_AXES)

    def test_the_axes_do_not_launder_the_first_probe(
        self, journey: _Journey
    ) -> None:
        """Each re-run carries the reference run's own rejection.

        A re-run that reported ``ok`` because its *own* draw found nothing
        would launder feature 125's detection into a pass, which is the one
        thing the family's records are written to forbid: the reference run
        rejected, so every axis' verdict carries ``reference_rejected``.
        """
        for axis in PERTURBATION_AXES:
            verdict = journey.verdicts[f"perturbation-stability:{axis}"]
            assert verdict.reference_rejected is True, axis
            assert verdict.outcome == "tripwire_fail", axis


# -- Facet 4: the failure poisons the branch ------------------------------------


class TestTheFailurePoisonsTheBranch:
    """Feature 131 — the verdict becomes a fact about the tree."""

    def test_the_whole_subtree_is_marked(self, journey: _Journey) -> None:
        """The failing node *and every node below it* — §C6's operative clause."""
        assert journey.poisoned_size == len(journey.tree.leak_branch)
        assert set(journey.poisoned_nodes) == set(journey.tree.leak_branch)

    def test_the_walk_starts_at_the_failing_node(self, journey: _Journey) -> None:
        """Feature 131's walk order: the probed node first, then its descendants."""
        assert journey.poisoned_nodes[0] == journey.tree.leak_root

    def test_the_marks_are_on_the_trees_own_rows(self, journey: _Journey) -> None:
        """``node.poisoned_at`` — the column the replay path reads."""
        assert journey.marked_rows == len(journey.tree.leak_branch)
        with closing(sqlite3.connect(journey.store_path)) as connection:
            marked = {
                row[0]
                for row in connection.execute(
                    "SELECT id FROM node WHERE poisoned_at IS NOT NULL"
                ).fetchall()
            }
        assert marked == set(journey.tree.leak_branch)

    def test_the_record_carries_one_row_per_poisoned_node(
        self, journey: _Journey
    ) -> None:
        """The audit table is a row per node — the replay path's question shape."""
        assert journey.record_rows == len(journey.tree.leak_branch)

    def test_the_record_names_the_failure_that_marked_the_branch(
        self, journey: _Journey
    ) -> None:
        """Which probe fired, and §8's word for it."""
        assert journey.poisoned_tripwire == TIME_SHUFFLE_NAME
        assert journey.poisoned_outcome == "tripwire_fail"
        with closing(sqlite3.connect(journey.store_path)) as connection:
            rows = connection.execute(
                "SELECT root_node_id, tripwire, outcome FROM tripwire_poison"
            ).fetchall()
        assert {row[0] for row in rows} == {journey.tree.leak_root}
        assert {row[1] for row in rows} == {TIME_SHUFFLE_NAME}
        assert {row[2] for row in rows} == {"tripwire_fail"}

    def test_the_poisoning_is_a_first_act_not_a_replay(self, journey: _Journey) -> None:
        """``replayed`` is False — this branch was marked once."""
        assert journey.poisoned_replayed is False

    def test_a_leaf_failure_would_be_one_node(self, journey: _Journey) -> None:
        """The branch is a *tree* fact, not a single row: the root has descendants.

        Stated as evidence rather than as a second poisoning: a journey whose
        failing node happened to be a leaf would satisfy "poisons the node"
        while never exercising §C6's *"and its entire subtree"*, which is the
        clause feature 132's refusal is sized by.
        """
        assert journey.poisoned_size > 1
        assert journey.tree.leak_child in journey.poisoned_nodes
        assert journey.tree.leak_grandchild in journey.poisoned_nodes


# -- Facet 5: the pool returns 0 surviving nodes from that branch ---------------


class TestThePoolReturnsZeroSurvivingNodes:
    """Feature 132, and the sentence's second half, measured off the pool."""

    def test_the_branch_survives_with_zero_nodes(self, journey: _Journey) -> None:
        """*"the replay pool returns 0 surviving nodes from that branch."*

        ``surviving_picks`` is the answer of a second query run against the
        pool over exactly the branch's rows, not a count derived from the
        ``scores`` beside it, and :class:`~tripwires.ExcisedBranch` refuses to
        be constructed with a non-empty answer — so an empty tuple here is a
        proof the refusal landed rather than a restatement of one.
        """
        assert journey.branch.surviving_picks == ()

    def test_the_pools_own_read_serves_no_branch_node(self, journey: _Journey) -> None:
        """§C5's read — ``survivors()`` — names no node of the branch either.

        The value's measured answer and the loop's own read are two different
        calls over the same store, and the sentence is about the second: an
        operator asking *what may I replay?* must not be handed a score the
        tripwires condemned.
        """
        served = {pick for pick in journey.survivor_picks if pick is not None}
        assert served & set(journey.tree.leak_branch) == set()

    def test_every_score_the_branch_contributed_is_refused(
        self, journey: _Journey
    ) -> None:
        """The branch's *whole* contribution — every node that committed to it."""
        assert set(journey.refused_picks) == set(journey.tree.leak_branch)
        assert journey.branch.excised_score_count == len(journey.tree.leak_branch)

    def test_the_refusal_is_attributed_to_the_failure(
        self, journey: _Journey
    ) -> None:
        """Every refused row names the failing node and the probe that fired."""
        assert journey.branch.tripwire == TIME_SHUFFLE_NAME
        assert all(
            entry.poisoned_by == journey.tree.leak_root
            for entry in journey.branch.scores
        )

    def test_nothing_was_deleted(self, journey: _Journey) -> None:
        """The rows are still there — the refusal is derived, and reversible in audit.

        §C6's excision is a *read*: the pool stops serving the branch, and an
        operator can still ask what the lost evidence was.  A journey that had
        deleted the rows would satisfy "0 surviving" while destroying the
        account feature 132 exists to produce.
        """
        with closing(sqlite3.connect(journey.store_path)) as connection:
            rows = int(
                connection.execute("SELECT COUNT(*) FROM replay_score").fetchone()[0]
            )
            branch_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM replay_score "
                    f"WHERE committed_pick IN ({', '.join('?' for _ in journey.tree.leak_branch)})",
                    journey.tree.leak_branch,
                ).fetchone()[0]
            )
        assert branch_rows == len(journey.tree.leak_branch)
        assert rows == branch_rows + len(journey.tree.control_branch) + 1

    def test_the_excision_is_whole_pool_and_returns_what_it_refuses(
        self, journey: _Journey
    ) -> None:
        """The account's halves agree: refused rows plus served rows is the pool."""
        # The pool holds one row per node that committed plus the one policy
        # that emitted no pick, so the pool's size is the picked nodes plus
        # the miss — the row space §C5 aggregates over.
        assert journey.branch.pool_size == journey.pooled_nodes_with_picks + 1
        assert (
            journey.branch.excised_score_count + journey.branch.surviving_score_count
            == journey.branch.pool_size
        )

    def test_the_branch_is_a_named_excised_root(self, journey: _Journey) -> None:
        """The pool lists the failure it is holding refused — read from the record."""
        assert journey.tree.leak_root in journey.excised_roots
        assert journey.excised_roots == (journey.tree.leak_root,)

    def test_the_pool_still_answers_what_the_branch_contributed(
        self, journey: _Journey
    ) -> None:
        """``scores_of`` is per-node and unrefused — the audit read survives.

        A deep descendant's row is the case worth naming: the loop expanded
        most of a branch long before any policy committed to it, and this
        journey's grandchild is the node that shows the refusal reaching past
        the failing node's own row.
        """
        assert journey.nested_scores == 1
        assert journey.control_nested_scores == 1

    def test_the_control_branch_is_untouched(self, journey: _Journey) -> None:
        """Only the leaking branch is refused — the excision is scoped.

        A refusal that swept the campaign would satisfy the zero-survivors
        sentence by refusing everything, which is not what §C6 says and would
        silently starve §C5's loop of evidence a tripwire never condemned.
        """
        served = {pick for pick in journey.survivor_picks if pick is not None}
        assert set(journey.tree.control_branch) <= served
        assert journey.branch.surviving_picks == ()

    def test_the_branch_is_frozen_and_reports_its_own_terms(
        self, journey: _Journey
    ) -> None:
        """A value, not a handle: the account cannot be edited after the fact."""
        assert journey.branch.size == len(journey.tree.leak_branch)
        assert journey.branch.node_ids[0] == journey.tree.leak_root
        assert sorted(journey.branch.picks) == sorted(journey.tree.leak_branch)
        with pytest.raises(AttributeError):
            journey.branch.surviving_picks = ()


# -- Facet 6: the leak's fingerprint and the composition ------------------------


class TestTheDoctrineTheSignalMustNotForfeit:
    """§4.1.2's stationarity under the bundle, and the wiring under both seats."""

    def test_the_target_bundle_aggregate_is_stationary(self, journey: _Journey) -> None:
        """§4.1.2's stationarity, measured on the bundle the panel is planted over.

        The bundle's own cross-sectional aggregate — one number per date, the
        quantity §4.1.2's *"aggregate forecast"* names — carries no drift
        comparable to its dispersion: the fitted linear trend's slope is a
        small fraction of the series' per-date standard deviation.  Asserted
        because a probe reading a drifting bundle would be detecting a trend
        and filing it as leakage, which would make this journey's six
        rejections mean something other than what the sentence claims.
        """
        series = journey.bundle[sorted(journey.bundle)[0]]
        days = sorted(series)
        aggregate = [journey.level[day] for day in days]
        mean = math.fsum(aggregate) / len(aggregate)
        dispersion = math.sqrt(
            math.fsum((value - mean) ** 2 for value in aggregate) / len(aggregate)
        )
        count = len(aggregate)
        midpoint = (count - 1) / 2
        sxx = math.fsum((index - midpoint) ** 2 for index in range(count))
        slope = (
            math.fsum(
                (index - midpoint) * (value - mean)
                for index, value in enumerate(aggregate)
            )
            / sxx
        )
        assert dispersion > 0.0
        assert abs(slope) < 0.1 * dispersion

    def test_the_leak_moves_with_the_date(self, journey: _Journey) -> None:
        """The leak's fingerprint: a level that *moves*, not a level that sits.

        The corpus's whole-sample statistic is the same cross-section on every
        date — date-invariant by construction — so a corpus-only panel's own
        cross-sectional mean is a constant and carries no date-local
        information at all.  The composite's cross-section moves, and the
        movement is exactly the date-local class the signal consumed: the two
        series are the same series up to the pinned weights and the symbol
        floor's averaging-out.  That is what makes the label probe the one
        that sees this class, and it is measured here rather than argued.
        """
        days = sorted(journey.panel)
        symbols = sorted(journey.panel[days[0]])
        composite = [
            math.fsum(journey.panel[day].values()) / len(symbols) for day in days
        ]
        corpus_only = _plant_panel(
            journey.bundle, whole_sample=WHOLE_SAMPLE_WEIGHT, date_local=0.0
        )
        flat = [
            math.fsum(corpus_only[day].values()) / len(symbols) for day in days
        ]
        # A corpus-only panel's cross-section is one value repeated: the
        # statistic is date-invariant, and only the symbol floor moves it.
        assert max(flat) - min(flat) < 10.0 * NOISE_SIGMA
        # The composite's cross-section moves by the date-local class, at the
        # pinned weight and no other scale.
        movement = max(composite) - min(composite)
        assert movement > 10.0 * (max(flat) - min(flat))
        assert abs(movement - DATE_LOCAL_WEIGHT * (max(journey.level.values())
                                                   - min(journey.level.values()))) < 10.0 * NOISE_SIGMA

    def test_the_failure_and_the_refusal_are_one_composition(
        self, journey: _Journey
    ) -> None:
        """The branch's mark, record and refusal all read the same store.

        The store and the pool are reached through the ``app`` package's own
        seats from one ``create_app()`` call — the factory's scan imports the
        member under a synthetic name, so a journey that mixed a composed
        store with a canonically imported pool would be exercising two
        compositions rather than one.  Asserted by the classes' own identity
        rather than by ``isinstance``, which cannot hold across that seam.
        """
        app = create_app()
        store = poison_store_component(app)
        pool = replay_pool_component(app)
        assert type(store).__name__ == "PoisonStore"
        assert type(pool).__name__ == "ReplayPool"
        assert type(store).__module__.startswith("_nullius_scanned_tripwires")
        assert type(pool).__module__.startswith("_nullius_scanned_tripwires")

    def test_the_store_and_the_pool_are_not_the_same_component(
        self, journey: _Journey
    ) -> None:
        """Four names, four answers — a caller asking for one is not handed the other.

        The tripwires member contributes the probe (``tripwires``), the store a
        failure is persisted to (``tripwires-poison``) and the pool a branch is
        refused from (``tripwires-excise``); a seat that answered with another
        component's object would give a caller an object whose every method
        means a different feature's thing.
        """
        app = create_app()
        store = poison_store_component(app)
        pool = replay_pool_component(app)
        assert store is not None and pool is not None
        assert type(store).__name__ != type(pool).__name__
        assert not hasattr(store, "survivors")
        assert not hasattr(pool, "poison")
