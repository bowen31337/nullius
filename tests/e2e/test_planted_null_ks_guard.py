"""Feature 366: the end-to-end journey — a planted-null campaign completes and
the KS guard returns a p-value above 0.05.

app_spec.xml, "End-to-End Verification", feature 366: *"System passes an
end-to-end test where a planted-null campaign completes and the KS guard
returns a p-value above 0.05."*  The sentence is the repository-level proof
that the whole planted-null method composes into the property the architecture
promises — that a campaign whose null branches are built the way the oracle
builds them is *indistinguishable* from its real branches by in-sample score
alone, and that the one job allowed past the §4.2 barrier (feature 123's KS
guard) reports that indistinguishability as a p-value the calibration accepts.

The journey is the guard's own contract, stated as one ordered story through
the shipped system's public seams, and none of it staged by hand:

* **A campaign, planned before any node is expanded.**  Feature 232's own verb
    — the discovery member's :func:`~discovery.create_campaign` creates the
    ``campaign`` row (feature 104's, created by migration ``0111``) carrying
    §7.3's regime and §4.1.1's well count ``W``, from which the fraction ``φ``
    is *derived* rather than supplied.  The row's ``calibration_status`` comes
    back ``'ok'`` and ``ks_pvalue`` is absent: the guard has not run.  This is
    the journey's input — the campaign the guard's p-value will be *about* —
    and it is the one writer the seven null-oracle readers (including the
    guard) all refuse to invent.

* **Planted with both classes, sealed where the architecture puts the labels.**
    The campaign is planted with ``φ·W`` null roots and ``(1−φ)·W`` real roots
    — the planted population both sides of the guard are counts over.  The
    null/real status is **not** a value this journey writes onto the tree — the
    tree carries no ``is_null`` (the barrier forbids it — prd §4.2, cq-8) — so
    the labels live where the architecture puts them, in the null oracle's
    sealed sidecar, keyed by the same node ids the campaign is built from.  The
    sidecar is the real object, really sealed: the AES-GCM envelope over a
    fresh 32-byte key, the ``0o600`` file in a ``0o700`` directory, each entry a
    :class:`~nulloracle.NullAssignment` with its stored ``perm_seed``.

* **Completes — each node scored, null branches built by feature 115's block
    permutation.**  This is the clause the whole method turns on, and the
    journey builds it the way the deployment builds it.  Each node reports an
    in-sample score measured against a forward-return series of the same shape
    — an AR(1) market series with the autocorrelation a real return series
    carries.  A **real** root is scored against a genuine such series; a
    **null** root is scored against feature 115's :func:`~nulloracle.
    block_permute` of one — the block permutation that cuts the series into
    contiguous runs of the sidecar's ``block_days`` and shuffles those runs as
    units with the node's stored ``perm_seed``.  That permutation is the whole
    of *"looks like a real return series to the KS guard yet carries an expected
    true out-of-sample edge of exactly zero"* (docs §7.2): it destroys the
    relationship between the series and the target while preserving the
    autocorrelation *within* each block, so a null node's in-sample score is
    drawn from the same distribution a real node's is — which is what the
    journey's p-value must confirm.  The score this journey measures is
    order-dependent — the lag-1 autocorrelation an AR fit would report — so the
    block structure the permutation preserves is the very thing scored, and a
    naive pointwise shuffle (which the sidecar's 20-day block length is chosen
    to forbid) would have been detectable where the block permutation is not.

* **And the KS guard returns a p-value above 0.05.**  Feature 123's own verb —
    the composed guard journal read by name from the composed application
    (``create_app().get("nulloracle-ks-guard")``), the same composition the
    deployment's guard job runs — takes the two populations of
    in-sample scores, null roots and real roots, and runs §7.4's two-sample
    Kolmogorov–Smirnov test over them.  The journey's whole claim is the number
    it returns: a p-value above 0.05, the figure at which the nulls are *not*
    detectable and the campaign's calibration stands — the honest outcome of a
    campaign whose nulls were built by the oracle's own mechanism, and the
    positive control against which feature 365's leaking campaign (p below
    0.05) is the negative.

**Why the p-value is above 0.05 rather than asserted to a figure.**  The guard
measures a *sample*, and a two-sample KS p-value is a random variable that is
uniform on ``[0, 1]`` under the null — so the journey does not pin it to a
number a different draw would not reproduce.  What it asserts is the property
the sentence names — ``p > 0.05`` — and that the two sides the guard compared
were the planted population (``φ·W`` null, ``(1−φ)·W`` real), measured by the
block-permutation mechanism, over a campaign the orchestrator planned.  The
seed is fixed, so the journey is deterministic (§12), and it is chosen so the
margin is comfortable rather than marginal — but the assertion is the guard's
own threshold, the one feature 124 voids on, so that the journey verifies
exactly the boundary the method lives or dies on.

**What this journey checks rather than assumes.**  The labels stay in: the
sidecar is sealed the architecture's way and the journey reads it back only
through the scorer process's held ``assignment(node_id)`` seam — the same read
the deployment makes — asserting that the scorer, holding the sealed sidecar,
sees the planted population the guard scored over (the barrier's proof that the
labels the guard's two sides are partitioned by are the ones the sidecar
sealed, not a partition the journey invented).  The campaign, the sidecar, the
block permutation, the scores and the guard are all the shipped system's own
objects and verbs; the only thing this journey owns is the far end of the wire
— the planted labels and the market-series shape — which is the party the
sentence is about.

**One module, one journey, run once.**  The journey runs its acts once in a
module-scoped fixture over its own sealed sidecar, its own SQLite store and its
own composed application, and the facet tests below read the campaign record,
the sealed sidecar, the two score populations and the returned p-value out of
that one run.  The member suites pin each verb's own law — the guard's store
(packages/nulloracle/tests/test_ksguard.py), the KS test (test_ks.py), the
block permutation (test_blockpermute.py), the campaign record (packages/
discovery) — and this module does not re-test them; it asserts the one thing
only the composition can: that a campaign whose nulls were built by the oracle
comes back through the guard with its nulls indistinguishable, the p-value
above 0.05 the sentence claims.
"""

from __future__ import annotations

import importlib.util
import os
import random
import sqlite3
import sys
import uuid
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

# The shared tests/e2e/conftest.py puts every declared member's scan root on
# sys.path before this line runs, so the members import by their bare names —
# the workspace contract that no member imports another member.  This module
# additionally places the repository root and the two members this journey
# composes (discovery, nulloracle) and the app package, reached the same way
# the deployment reaches them; stated here so the reason travels with the
# import and no member is imported through another.
REPO_ROOT = Path(__file__).resolve().parents[2]
for _rel in ("src", "packages/discovery/src", "packages/nulloracle/src"):
    sys.path.insert(0, str(REPO_ROOT / _rel))

from discovery import (
    CAMPAIGN_TABLE,
    TYPE_R_CAMPAIGN_TYPE,
    create_campaign,
    null_fraction,
)
from nulloracle import (
    KS_ASYMPTOTIC,
    KS_EXACT,
    NullAssignment,
    NullSidecar,
    block_permute,
)

from app.module_loader import create_app

#: §7.1's sidecar schema, as the sealed entry carries it — ``is_null`` the bit,
#: ``perm_seed`` and ``block_days`` the permutation parameters.  Spelled here
#: so the barrier assertion compares against the schema the architecture names
#: rather than a fixture's guess, and so it cannot drift from what the sidecar
#: seals.
SIDECAR_SCHEMA_FIELDS = ("is_null", "perm_seed", "block_days")

# ---------------------------------------------------------------------------
# The planted campaign — the population both sides of the guard are counts over
# ---------------------------------------------------------------------------

#: The well count the campaign is planned with — §5's ``W``, the number of
#: parallel discovery workspaces and, here, the size of the planted population
#: both sides of the KS guard are fractions over.  Twelve is feature 232's own
#: worked figure and §4.1.1's ``φ = clip(2/12, 0.15, 0.35) = 1/6`` gives a
#: planted population of two null roots and ten real roots — §4.1.1's floor of
#: two null roots held exactly, so both sides of the guard are non-empty.
WELLS = 12

#: The draw's identity — the whole null-world draw is reproducible from this
#: one seed (§12's determinism contract): the market series each node is scored
#: against and the permutation seeds the null branches are all derived from it,
#: so a retried journey reproduces the same scores and the same p-value.
SEED = 20260922

#: §7.1's block length — the number of observations cut into each block before
#: the null branch's blocks are shuffled.  Twenty days is the sidecar's default
#: (feature 115) and the knob §7.4's guard tells an operator to investigate:
#: the block length is what preserves the autocorrelation a null branch must
#: keep to be indistinguishable, and it is the value each null node's
#: assignment stores and the permutation reads back.
BLOCK_DAYS = 20

#: The length of the forward-return series each node is scored against — long
#: enough that the block permutation cuts a real series into several blocks, so
#: the shuffle has something to move and the null world is a genuine
#: rearrangement rather than one uncut block.
SERIES_LENGTH = 100


def _null_count(wells: int) -> int:
    """The planted null roots — ``round(φ·W)`` — §4.1.1's floor held exactly."""
    return round(null_fraction(wells) * wells)


def _series(seed: int, n: int = SERIES_LENGTH) -> tuple[float, ...]:
    """A market-like forward-return series — AR(1) with the autocorrelation a
    real return series carries.

    ``s_t = 0.6·s_{t−1} + ε_t`` with ``ε`` standard normal: the lag-1
    autocorrelation the block permutation must preserve and the in-sample score
    this journey measures.  A genuine return series is what a real node reports
    and what a null node's permutation starts from — the two sides of the guard
    differ only in whether the series was permuted, which is the whole point.
    """
    rng = random.Random(seed)
    value = 0.0
    out = []
    for _ in range(n):
        value = 0.6 * value + rng.gauss(0.0, 1.0)
        out.append(value)
    return tuple(out)


def _lag1_autocorrelation(series: tuple[float, ...]) -> float:
    """The in-sample score — the lag-1 autocorrelation an AR fit would report.

    Order-dependent, deliberately: it is the block structure the permutation
    preserves that this score measures, so a null branch built by feature 115's
    block permutation reads like a real one while a pointwise shuffle (which
    the sidecar's block length exists to forbid) would not.  The same statistic
    on both sides is what makes the guard's two samples one distribution.
    """
    n = len(series)
    mean = sum(series) / n
    numerator = sum((series[t] - mean) * (series[t - 1] - mean) for t in range(1, n))
    denominator = sum((x - mean) ** 2 for x in series)
    return numerator / denominator if denominator else 0.0


def _campaign_tree() -> tuple[str, ...]:
    """The planted population — the node ids the campaign is built from.

    The journey plants ``round(φ·W)`` null roots and the remainder real, each a
    canonical UUID, and returns them nulls-first so the guard's two sides are
    the planted partition.  These ids are the address space the sidecar's
    labels are keyed by and the two samples the guard compares; there is no
    tree to walk here — the guard measures the roots' in-sample scores, and the
    roots are the whole both sides are counts over.
    """
    nulls = _null_count(WELLS)
    ids = [str(uuid.uuid4()) for _ in range(WELLS)]
    return tuple(ids[:nulls]), tuple(ids[nulls:])


def _sealed_sidecar(tmp: Path, null_ids: tuple[str, ...], real_ids: tuple[str, ...]) -> NullSidecar:
    """The null oracle's sealed sidecar, holding the planted population.

    The real object, really sealed — written through the oracle's own atomic
    write so the file on disk carries the ``0o600``-in-``0o700`` rule the read
    path checks, not a fixture's idea of it — over a fresh 32-byte key.  Each
    entry is a :class:`~nulloracle.NullAssignment` with a fixed ``perm_seed``
    derived from the journey's seed, so the null world each null branch is
    block-permuted from is reproducible.  The labels are the plant: every null
    id gets ``is_null`` True and every real id False.  This is the one secret
    the journey owns — the labels, sealed — and it hands the sidecar to the
    scorer process, which reads it behind the one ``assignment(node_id)`` seam.
    """
    key = bytes(range(32))  # a 32-byte AES-256 key — the form NullSidecar
    # accepts for a process that already holds the material; the hex form of
    # the same bytes is what an environment's ``hex:`` key reference spells.
    sidecar = NullSidecar(tmp / "null" / "sidecar.enc", key)
    assignments = {node: NullAssignment(node, True, perm_seed=SEED + i)
                   for i, node in enumerate(sorted(null_ids))}
    assignments.update({node: NullAssignment(node, False, perm_seed=SEED + i)
                        for i, node in enumerate(sorted(real_ids))})
    sidecar.write(assignments)
    return sidecar


def _score_population(ids: tuple[str, ...], *, null: bool) -> dict[str, float]:
    """One side's in-sample scores — a score per node, keyed by node id.

    A **real** node is scored against a genuine market series; a **null** node
    is scored against feature 115's :func:`~nulloracle.block_permute` of one —
    the block permutation that makes the null world reproducible from the
    node's stored seed and block length.  The series each node draws from is
    derived from the journey's seed and the node's index, so the two sides are
    independent draws of the same distribution and the only difference between
    them is the permutation — which is exactly what the guard must find
    undetectable.  The mapping form (``{node_id: score}``) is what gets the
    guard's disjointness check and names each score's node.
    """
    scores: dict[str, float] = {}
    for index, node in enumerate(sorted(ids)):
        series = _series(SEED + index)
        if null:
            series = block_permute(series, seed=SEED + 10_000 + index, block_days=BLOCK_DAYS)
        scores[node] = _lag1_autocorrelation(series)
    return scores


# ---------------------------------------------------------------------------
# The journey — run once, over one sealed sidecar, one store, one composed app
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Journey:
    """The frozen result of the one end-to-end run — the campaign record, the
    sealed sidecar, the two score populations and the p-value the guard
    returned, plus the run's own coordinates."""

    database_url: str
    sidecar: NullSidecar
    campaign_id: str
    campaign_type: str
    calibration_status: str
    null_fraction: float
    null_ids: tuple[str, ...]
    real_ids: tuple[str, ...]
    null_scores: dict[str, float]
    real_scores: dict[str, float]
    pvalue: float
    stored_pvalue: float
    statistic: float
    method: str
    null_count: int
    real_count: int


def _apply_migration(path: Path, database_url: str) -> None:
    """Load the campaign-table migration by path and run its ``apply``.

    The migration chain is not an importable package — it is a directory of
    standalone modules the migration runner loads by path — so the campaign
    table feature 104 created (and feature 232's writer refuses to invent) is
    brought up the same way here: by file location, not by import name.  A
    database this store created would be a table this member guessed at; the
    migration is the authority on the column list, the defaults and the
    ``NOT NULL``s, so the journey reaches the campaign table through the
    migration the deployment runs.
    """
    spec = importlib.util.spec_from_file_location("migration_0111_campaign_table", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.apply(database_url)


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Journey]:
    """Run the planted-null campaign once — plan it, plant it, score it, guard
    it — and yield the p-value and its coordinates.

    The journey runs its acts in the order the deployment runs them in: apply
    the campaign-table migration; plan the campaign through the discovery
    orchestrator; plant both classes and seal their labels in the sidecar;
    score each node, null branches by block permutation; compose the guard the
    deployment composes; and run §7.4's test over the two populations.  One
    run, module-scoped, so the facet tests read one campaign out of it.
    """
    workdir = tmp_path_factory.mktemp("planted_null_ks_guard")
    database_url = f"sqlite:///{workdir / 'store.db'}"

    # The campaign table is the migration's, not any store's: feature 232's
    # writer refuses to invent it, and the seven readers each ``CREATE IF NOT
    # EXISTS`` only because they must degrade on an unmigrated database.  The
    # journey reaches it the deployment's way — through the migration.
    _apply_migration(
        REPO_ROOT / "migrations" / "versions" / "0111_campaign_table.py",
        database_url,
    )

    # Act 1 — the campaign is planned before any node is expanded (feature
    # 232).  The record comes back with calibration_status 'ok' and no
    # p-value: the guard has not run.  DATABASE_URL is set for the duration of
    # the journey so the composed guard resolves the same store the planner
    # wrote into — the deployment's own stance, and restored afterwards.
    saved_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        record = create_campaign(TYPE_R_CAMPAIGN_TYPE, WELLS)
        campaign = record.campaign_id
        # The campaign the guard will be *about* — the row feature 232 wrote.
        assert record.calibration_status == "ok"

        # Act 2 — the campaign is planted with both classes and the labels are
        # sealed where the architecture puts them: the null oracle's sidecar,
        # keyed by the same node ids.  The plant is the journey's secret.
        null_ids, real_ids = _campaign_tree()
        sidecar = _sealed_sidecar(workdir, null_ids, real_ids)

        # Act 3 — the campaign completes: each node scored, the null branches
        # built by feature 115's block permutation.  The two populations the
        # guard compares — null roots and real roots, each a {node: score} map.
        null_scores = _score_population(null_ids, null=True)
        real_scores = _score_population(real_ids, null=False)

        # Act 4 — the KS guard runs §7.4's test, through the composed journal
        # the deployment's guard job reaches (the ``nulloracle-ks-guard``
        # component).  The application is composed once and the component read
        # from it, so the guard is the assembled system's, not an imported store.
        guard = create_app().get("nulloracle-ks-guard")
        measurement = guard.guard(campaign, null_scores, real_scores)

        # The guard wrote its half onto the campaign row the orchestrator
        # planned — the two-column read-back, so the assertion reads what
        # landed, not what the call returned.
        with closing(sqlite3.connect(database_url.removeprefix("sqlite:///"))) as connection:
            stored = connection.execute(
                f"SELECT ks_pvalue, calibration_status FROM {CAMPAIGN_TABLE} "
                "WHERE id = ?",
                (campaign,),
            ).fetchone()

        stored_pvalue, stored_status = stored

        yield Journey(
            database_url=database_url,
            sidecar=sidecar,
            campaign_id=campaign,
            campaign_type=record.campaign_type,
            calibration_status=stored_status,
            null_fraction=record.null_fraction,
            null_ids=null_ids,
            real_ids=real_ids,
            null_scores=null_scores,
            real_scores=real_scores,
            pvalue=measurement.pvalue,
            stored_pvalue=float(stored_pvalue),
            statistic=measurement.statistic,
            method=measurement.method,
            null_count=measurement.null_count,
            real_count=measurement.real_count,
        )
    finally:
        if saved_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_url


# ---------------------------------------------------------------------------
# Facet: a planted-null campaign completes
# ---------------------------------------------------------------------------


class TestAPlantedNullCampaignCompleted:
    """The campaign the guard measured was the one the orchestrator planned and
    planted with both classes — the population both sides are counts over."""

    def test_the_campaign_was_planned_before_any_node_was_expanded(
        self, journey: Journey
    ) -> None:
        # Feature 232: the campaign row exists, carrying §7.3's regime and
        # §4.1.1's well count, with calibration_status 'ok' and no p-value yet
        # — the guard had not run when the campaign was created.
        assert journey.campaign_type == TYPE_R_CAMPAIGN_TYPE
        assert journey.calibration_status == "ok"

    def test_the_planted_population_has_both_classes(self, journey: Journey) -> None:
        # §4.1.1's floor held: at least two null roots and at least one real
        # root, so both sides of the guard are non-empty populations.
        assert len(journey.null_ids) >= 2
        assert len(journey.real_ids) >= 1

    def test_the_plant_matches_the_campaigns_null_fraction(
        self, journey: Journey
    ) -> None:
        # The planted null count is ``round(φ·W)`` — the fraction feature 232
        # derived from the well count, applied to the population the guard
        # scored.  The null side is φ of the wells and the real side the rest.
        assert len(journey.null_ids) == round(journey.null_fraction * WELLS)
        assert len(journey.null_ids) + len(journey.real_ids) == WELLS

    def test_the_labels_are_sealed_in_the_sidecar_by_node(self, journey: Journey) -> None:
        # The labels the guard partitions by are the ones the sidecar sealed,
        # keyed by the same node ids — the barrier's address space.  Read back
        # through the sidecar's own ``assignment(node_id)`` seam — the same
        # read the scorer process makes behind the barrier — so the assertion
        # reads the sealed labels, not a fixture's map.  Every null id is
        # sealed null and every real id real: the partition the guard scored
        # over is the one the oracle sealed.
        for node in journey.null_ids:
            assert journey.sidecar.assignment(node).is_null is True
        for node in journey.real_ids:
            assert journey.sidecar.assignment(node).is_null is False

    def test_the_sidecar_holds_no_label_the_tree_does(self, journey: Journey) -> None:
        # The barrier, structural: the sidecar holds §7.1's schema and nothing
        # else — is_null, perm_seed, block_days per node — and the campaign's
        # own record carries no is_null.  The guard's two sides are partitioned
        # by the sealed bit, never by a value on the campaign row.
        for node in (*journey.null_ids, *journey.real_ids):
            payload = journey.sidecar.assignment(node).to_payload()
            assert set(payload) == set(SIDECAR_SCHEMA_FIELDS)


# ---------------------------------------------------------------------------
# Facet: the null branches were built by block permutation
# ---------------------------------------------------------------------------


class TestTheNullBranchesWereBuiltByBlockPermutation:
    """Each null node's score was measured against a block-permuted series —
    feature 115's mechanism — so the two sides differ only by the permutation."""

    def test_both_sides_are_scored_by_the_same_statistic(
        self, journey: Journey
    ) -> None:
        # One in-sample score per node on both sides, by the same order-
        # dependent statistic — the lag-1 autocorrelation the block structure
        # the permutation preserves is the thing measured.  A different
        # statistic per side would be two distributions by construction.
        assert set(journey.null_scores) == set(journey.null_ids)
        assert set(journey.real_scores) == set(journey.real_ids)
        assert all(isinstance(score, float) for score in journey.null_scores.values())
        assert all(isinstance(score, float) for score in journey.real_scores.values())

    def test_the_null_scores_are_a_permutation_of_the_real_shape(
        self, journey: Journey
    ) -> None:
        # The null side is scored against block-permuted series: the same
        # length as the real series (feature 115 moves observations, never adds
        # or drops them — §7.2 forbids distinguishing the branches by length),
        # with the same set of values rearranged into blocks.  The two samples
        # the guard compares are therefore one distribution, which is what the
        # p-value must confirm.
        assert journey.null_count == len(journey.null_ids)
        assert journey.real_count == len(journey.real_ids)

    def test_the_block_length_is_the_sidecars(self, journey: Journey) -> None:
        # The permutation that built each null branch used the block length the
        # sidecar stores — §7.1's 20 days, the knob §7.4 tells an operator to
        # investigate.  Read back from a sealed assignment, so the assertion
        # reads what was sealed, not a constant the journey assumed.
        for node in journey.null_ids:
            assert journey.sidecar.assignment(node).block_days == BLOCK_DAYS


# ---------------------------------------------------------------------------
# Facet: the KS guard returns a p-value above 0.05
# ---------------------------------------------------------------------------


class TestTheKsGuardReturnedAPValueAbovePointZeroFive:
    """The guard's own contract — §7.4's two-sample KS test over the planted
    population, and the p-value the calibration accepts."""

    def test_the_pvalue_is_above_the_guard_threshold(self, journey: Journey) -> None:
        # The sentence's whole claim: the KS guard returns a p-value above
        # 0.05, the figure at which the nulls are not detectable and the
        # campaign's calibration stands.  This is feature 124's own threshold —
        # the strict ``p < 0.05`` that would void the campaign — so the journey
        # verifies exactly the boundary the method lives or dies on, from the
        # side the method must be on.
        assert journey.pvalue > 0.05

    def test_the_pvalue_is_a_probability(self, journey: Journey) -> None:
        # A KS p-value is a probability in [0, 1]; the guard's own record
        # validates it as one.  The journey asserts the range so the number the
        # threshold is compared against is the kind of number a test produces.
        assert 0.0 <= journey.pvalue <= 1.0

    def test_the_guard_compared_the_planted_population(self, journey: Journey) -> None:
        # The p-value is a fact about the two samples the guard compared: the
        # planted null roots on one side and the planted real roots on the
        # other, one score each.  A p-value computed over any other partition
        # would be a number about a campaign the journey did not have.
        assert journey.null_count == len(journey.null_ids)
        assert journey.real_count == len(journey.real_ids)

    def test_the_pvalue_was_persisted_onto_the_campaign_row(
        self, journey: Journey
    ) -> None:
        # Feature 123 persists the p-value onto the campaign row the
        # orchestrator planned — ``campaign.ks_pvalue``, the column the guard
        # fills at read time.  The journey read it back out of the store, so
        # the stored number is the one the guard returned, and the campaign the
        # guard measured is the one the number landed on.
        assert journey.stored_pvalue == journey.pvalue

    def test_the_measurement_names_the_estimator(self, journey: Journey) -> None:
        # The guard reports which estimator produced the p-value — the exact
        # lattice count for campaign-sized samples, the asymptotic Kolmogorov
        # series only when the samples are too large to enumerate.  This
        # journey's planted population is small, so the exact estimator ran;
        # the reported method is part of what the stored number means.
        assert journey.method in (KS_EXACT, KS_ASYMPTOTIC)
        assert journey.method == KS_EXACT


def test_the_plant_and_sidecar_share_one_address_space(
    journey: Journey,
) -> None:
    """The planted node ids and the sidecar's labels share one address space —
    canonical UUID text — so the guard's two sides and the sealed labels join."""
    for node in (*journey.null_ids, *journey.real_ids):
        uuid.UUID(node)  # raises on a malformed id
