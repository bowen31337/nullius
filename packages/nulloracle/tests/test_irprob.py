"""Feature 120: ``p`` decreasing in the parent's true IR, varying across campaigns.

app_spec.xml, "Null Oracle & Planted Nulls", feature 120: *System draws the
geometric flip depth with probability decreasing in the parent true information
ratio, which returns a distribution varying across campaigns.*  Feature 119's
suite pins the *draw* and the *column*; this one pins what the depth is drawn
*from*, which is the half the sentence names first and feature 119's docstring
hands over by name: *"What the depth is drawn from — ``p`` decreasing in the
parent's true IR, varied across campaigns — is feature 120's."*

Three clauses, three ways a plausible-looking implementation fails, and the
suite is organised around them:

* **"probability decreasing in the parent true information ratio."**  §7.3
  spells the map as ``p_from_true_ir(branch.true_ir)`` and gives the reason:
  *"strong mechanisms support more refinement before exhausting."*  A constant
  ``p``, or one that rose with the true IR, would invert the design — a strong
  mechanism's branch would flip shallow and stop refining exactly where the
  world is most worth exploring.  So monotonicity is asserted directly, on the
  map and again *through the distribution*, and hand-worked against the
  logistic at the constants.  The degenerate case is named too: a ``p`` of 1
  (or 0) is the "always stop at depth 1" docs/alpha-engine-prd.md §4.1.2 warns
  teaches the policy nothing, and the map's codomain is asserted to sit strictly
  inside feature 119's open interval for *every* finite ratio — including the
  extreme ones — so that feature 119's own refusal can never fire on a
  legitimately drawn branch.

* **"which returns a distribution varying across campaigns."**  §7.3's last line
  is an instruction — *"Vary ``p`` across campaigns"* — and the failure it rules
  out is subtle: a ``p`` that is a function of the true IR *alone* makes every
  campaign the same world re-labelled.  So two campaigns holding branches of
  *identical* true IR must draw from *different* distributions, many campaigns
  must produce many distinct probabilities, and the variation must be legible —
  the distribution carries the shift that moved it, so a reader can say which
  campaign moved it and by how much.  Against that, the ordering within a
  campaign must survive: for a fixed campaign ``p`` is still strictly decreasing
  in the true IR, so "varying across campaigns" is satisfied *together with*
  monotonicity rather than traded off against it.

* **"returns a distribution."**  The sentence's verb is not "computes a
  probability."  The read path returns a value that carries the campaign, the
  ratio, the shift and the probability, and refuses at construction to hold
  fields that disagree — the recompute-and-compare discipline feature 121's
  resolution applies to its own target.  A distribution holding a doctored
  probability is refused by name, because that number is what a branch's depth
  will actually be drawn from.

Determinism gets its own section because §12 is explicit and the consequence is
sharp: the shift is *drawn*, so a re-drawn shift would mean a campaign replayed
from the same seed drew a different depth than the one persisted — the depth
column would disagree with the world that produced it.  Two calls with the same
campaign id must return the same shift, and the map composed with it must be
reproducible.

The store's refusals are pinned last, and the one that matters most is the
campaign gate: only §7.3's Type-D regime has a flip depth at all, and a depth
written onto a Type-R branch would be a boundary in a world that has none —
feature 121 would never serve it, and a Type-B failure count would be measuring
a flip that never happened.
"""

from __future__ import annotations

import itertools
import math
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_SPREAD,
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    NODE_TABLE,
    PROBABILITY_CEILING,
    PROBABILITY_FLOOR,
    TRUE_IR_MIDPOINT,
    TRUE_IR_SCALE,
    FlipDepth,
    FlipDepthDistribution,
    KsGuardError,
    SidecarError,
    TrueIRFlipDepth,
    campaign_as_seed,
    campaign_offset,
    draw_flip_depth,
    flip_depth_distribution,
    probability_from_true_ir,
)

#: A campaign id and a node id that are canonical UUIDs, so a test that is
#: about the *distribution* is never accidentally about id validation.
CAMPAIGN = "3f1c9b60-0000-4000-8000-000000000001"
OTHER_CAMPAIGN = "3f1c9b60-0000-4000-8000-000000000002"
NODE = "3f1c9b60-0000-4000-8000-000000000011"


# -- Helpers ---------------------------------------------------------------------


def _store(tmp_path: Path, name: str = "irprob.db") -> tuple[TrueIRFlipDepth, str]:
    """A true-IR flip-depth store over a fresh SQLite file, with its ``DATABASE_URL``."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return TrueIRFlipDepth(url), url


def _campaign(
    store: TrueIRFlipDepth,
    campaign_id: str | None = None,
    *,
    campaign_type: str = "Type-D",
) -> str:
    """Insert a campaign row the way its planner would, and return its id."""
    identifier = campaign_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, null_fraction) "
            "VALUES (?, ?, 40, 0.15)",
            (identifier, campaign_type),
        )
    return identifier


def _node(
    store: TrueIRFlipDepth,
    campaign_id: str | None,
    node_id: str | None = None,
    *,
    depth: int = 2,
) -> str:
    """Insert a node row the way the discovery loop would, and return its id.

    ``flip_depth`` is left NULL — a value no draw would produce — so a test
    asserting the stored depth came from *this* store cannot pass merely because
    the row was inserted with a plausible value.
    """
    identifier = node_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, 'macro', ?)",
            (identifier, campaign_id, depth),
        )
    return identifier


def _stored_depth(store: TrueIRFlipDepth, node_id: str) -> int | None:
    """The node row's ``flip_depth``, read raw — or ``None`` when the column is absent.

    The column is feature 119's: this store never adds it, so a database on
    which no draw has yet run has no column to read, and "no depth was written"
    is the honest answer for those rows rather than an ``OperationalError``.
    """
    with closing(store._connect()) as connection:
        columns = {row[1] for row in _table_info(connection, NODE_TABLE)}
        if "flip_depth" not in columns:
            return None
        cursor = connection.execute(
            f"SELECT flip_depth FROM {NODE_TABLE} WHERE id = ?", (node_id,)
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    return None if row is None else row[0]


def _table_info(connection: sqlite3.Connection, table: str) -> list[tuple]:
    """``PRAGMA table_info`` for ``table``, as raw rows."""
    cursor = connection.execute(f"PRAGMA table_info({table})")
    try:
        return list(cursor.fetchall())
    finally:
        cursor.close()


def _migration():
    """``migrations/versions/0118_node_table.py``, loaded by path.

    By path rather than by import because that is how a migration runner loads
    it: the file is not a module on any package's ``sys.path``, and a test that
    could only reach it through an import would be testing a different
    arrangement from the one that runs.
    """
    import importlib.util

    repo_root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "migration_0118_node_table",
        repo_root / "migrations" / "versions" / "0118_node_table.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    The repository's conftest already points ``DATABASE_URL`` at a throwaway
    database; this module's store resolves the same variable, and the tests
    that care about the environment say so explicitly rather than inheriting
    whatever invoked pytest.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


# -- The map: decreasing in the true IR -------------------------------------------


class TestTheProbabilityFallsAsTheTrueEdgeRises:
    """§7.3: *"p decreasing in the parent's TRUE ir."*"""

    def test_the_map_is_strictly_decreasing_across_the_useful_range(self) -> None:
        # The clause the sentence leads with.  Over the range a true
        # information ratio actually occupies, every step up must lower p —
        # otherwise a stronger mechanism would flip *sooner*, which is the
        # inversion §7.3's whole design argument rests on.
        ratios = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0]
        probabilities = [probability_from_true_ir(ratio) for ratio in ratios]
        assert all(
            later < earlier for earlier, later in itertools.pairwise(probabilities)
        ), probabilities

    def test_the_map_is_decreasing_to_the_floor_and_no_further(self) -> None:
        # Past the asymptote it is flat rather than decreasing — a logistic
        # necessarily is — and flat-at-the-floor is the right answer: a branch
        # of unbounded true IR already flips as deep as the design allows.
        # What must never happen is a *rise*, which would make the map
        # non-monotone.
        ratios = [x / 10.0 for x in range(30, 200)]
        probabilities = [probability_from_true_ir(ratio) for ratio in ratios]
        assert all(
            later <= earlier for earlier, later in itertools.pairwise(probabilities)
        ), probabilities
        assert probabilities[-1] == pytest.approx(PROBABILITY_FLOOR)

    def test_a_stronger_mechanism_draws_a_deeper_flip_on_average(self) -> None:
        # The consequence in §7.3's own currency: the geometric's mean is 1/p,
        # so a stronger mechanism supports *more* refinements before its branch
        # exhausts.  "Strong mechanisms support more refinement before
        # exhausting" is a claim about the mean, and this is the mean.
        weak = 1.0 / probability_from_true_ir(0.0)
        strong = 1.0 / probability_from_true_ir(1.5)
        assert strong > weak
        assert weak == pytest.approx(2.0)  # the midpoint, by construction

    def test_the_map_is_hand_worked_at_the_midpoint(self) -> None:
        # At true_ir = 0 and no campaign shift the logistic is at its centre,
        # so p is exactly the midpoint of the two asymptotes.  Pinned because
        # the constant is what makes "a mechanism with no edge" a mean depth of
        # exactly 2 — a fact a reader of the campaign manifest can check.
        assert probability_from_true_ir(TRUE_IR_MIDPOINT) == pytest.approx(
            (PROBABILITY_FLOOR + PROBABILITY_CEILING) / 2.0
        )

    def test_one_scale_step_moves_the_logistic_one_step(self) -> None:
        # Hand-worked against the closed form, so the test is not merely
        # asserting that some decreasing function exists: at ratio = scale the
        # exponent is 1, and the weight is 1/(1+e).
        ratio = TRUE_IR_MIDPOINT + TRUE_IR_SCALE
        weight = 1.0 / (1.0 + math.e)
        assert probability_from_true_ir(ratio) == pytest.approx(
            PROBABILITY_FLOOR + (PROBABILITY_CEILING - PROBABILITY_FLOOR) * weight
        )


class TestTheProbabilityIsAGenuineProbabilityEverywhere:
    """Feature 119 refuses ``p`` outside the *open* ``(0, 1)``; this map never gets there."""

    def test_every_finite_ratio_lands_strictly_inside_the_open_interval(self) -> None:
        # The structural guarantee, and the reason the asymptotes exist.  If the
        # map could reach 0 or 1, feature 119's open-interval refusal would fire
        # on an ordinary branch — a truthful exception on a legitimate draw —
        # and the two features would disagree about what a probability is.
        ratios = [x / 4.0 for x in range(-400, 400)] + [0.0]
        for ratio in ratios:
            probability = probability_from_true_ir(ratio)
            assert 0.0 < probability < 1.0, (ratio, probability)

    def test_an_unbounded_ratio_lands_on_the_floor_rather_than_raising(self) -> None:
        # math.exp raises OverflowError rather than returning inf past ~710, so
        # a naive logistic would blow up out of the middle of a campaign loop.
        # The stable form takes the asymptote instead, and the asymptote is
        # still strictly inside (0, 1).
        for ratio in (1e300, 1e308):
            probability = probability_from_true_ir(ratio)
            assert probability == pytest.approx(PROBABILITY_FLOOR)
            assert 0.0 < probability < 1.0

    def test_an_unboundedly_weak_ratio_lands_on_the_ceiling(self) -> None:
        probability = probability_from_true_ir(-1e300)
        assert probability == pytest.approx(PROBABILITY_CEILING)
        assert 0.0 < probability < 1.0

    def test_the_asymptotes_are_inside_the_interval_feature_119_validates(self) -> None:
        # Feature 119's P_MIN/P_MAX are 0.0 and 1.0 and its refusal is strict;
        # this pins the relationship so a future change to either constant
        # cannot silently unmake the guarantee.
        from nulloracle import P_MAX, P_MIN

        assert P_MIN < PROBABILITY_FLOOR < PROBABILITY_CEILING < P_MAX

    def test_the_map_never_returns_a_value_feature_119_would_refuse(self) -> None:
        # Stated as the interaction rather than the interval: feed every
        # probability the map produces into feature 119's own validator, which
        # is what the draw will do, and nothing is refused.
        from nulloracle import flip_depth

        for ratio in (-3.0, -0.5, 0.0, 0.5, 1.0, 2.0, 1e6, -1e6):
            probability = probability_from_true_ir(ratio)
            depth = flip_depth(probability, seed=7)
            assert depth >= 1


class TestTheMapRefusesWhatItCannotMap:
    """A true information ratio is a finite real; a shift is a finite real."""

    @pytest.mark.parametrize("ratio", [True, False, "0.5", None, [0.5], {}])
    def test_a_ratio_that_is_not_a_real_is_refused(self, ratio: object) -> None:
        # Bools are ints in Python and are not quantities; a truthy-looking
        # True would otherwise be mapped as the ratio 1.
        with pytest.raises(KsGuardError):
            probability_from_true_ir(ratio)

    @pytest.mark.parametrize("ratio", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_ratio_is_refused(self, ratio: float) -> None:
        # nan compares false against every bound the map applies, so it would
        # take an arbitrary branch and draw a depth from a number nobody
        # measured; inf would sit past an asymptote the map is meant to
        # approach.
        with pytest.raises(KsGuardError):
            probability_from_true_ir(ratio)

    @pytest.mark.parametrize("shift", [True, "0.1", None, float("nan"), float("inf")])
    def test_a_shift_that_is_not_a_finite_real_is_refused(self, shift: object) -> None:
        with pytest.raises(KsGuardError):
            probability_from_true_ir(0.5, campaign_offset=shift)

    def test_the_refusal_names_the_argument_it_is_about(self) -> None:
        with pytest.raises(KsGuardError, match="true_ir"):
            probability_from_true_ir(float("nan"))
        with pytest.raises(KsGuardError, match="campaign_offset"):
            probability_from_true_ir(0.5, campaign_offset=float("nan"))


# -- The variation: across campaigns ----------------------------------------------


class TestTheDistributionVariesAcrossCampaigns:
    """§7.3: *"Vary ``p`` across campaigns."*"""

    def test_two_campaigns_at_the_same_ratio_draw_different_distributions(self) -> None:
        # The failure this rules out: a p that is a function of the true IR
        # alone.  Two campaigns holding branches of identical true IR would then
        # draw from identical distributions, every campaign in the pool would be
        # one world re-labelled, and a policy tuned on one would transfer to all
        # of them for the wrong reason.
        first = flip_depth_distribution(CAMPAIGN, 1.0)
        second = flip_depth_distribution(OTHER_CAMPAIGN, 1.0)
        assert first.true_ir == second.true_ir
        assert first.probability != second.probability

    def test_many_campaigns_produce_many_distinct_probabilities(self) -> None:
        # Not merely "not all equal": the spread has to be real.  Fifteen
        # campaigns at one ratio should give fifteen different probabilities at
        # double precision — a variation that collapsed onto a handful of values
        # would not be the distribution varying.
        campaigns = [
            f"3f1c9b60-0000-4000-8000-{index:012d}" for index in range(1, 16)
        ]
        probabilities = {
            round(flip_depth_distribution(campaign, 1.0).probability, 12)
            for campaign in campaigns
        }
        assert len(probabilities) == len(campaigns)

    def test_the_variation_is_a_shift_in_the_campaigns_own_units(self) -> None:
        # The shift is bounded by the constant, drawn from the campaign's id,
        # and reported on the distribution — so a reader can say *which*
        # campaign moved the distribution and by how much, rather than only
        # observing that two numbers differ.
        for campaign in (CAMPAIGN, OTHER_CAMPAIGN):
            shift = campaign_offset(campaign)
            assert -CAMPAIGN_SPREAD <= shift <= CAMPAIGN_SPREAD
            assert flip_depth_distribution(campaign, 1.0).campaign_offset == shift

    def test_the_campaigns_shift_is_what_the_map_was_applied_to(self) -> None:
        # The composition, pinned: the distribution's probability is the map
        # applied to the ratio *shifted by the campaign's own shift*, and
        # nothing else.
        shift = campaign_offset(CAMPAIGN)
        distribution = flip_depth_distribution(CAMPAIGN, 0.75)
        assert distribution.probability == probability_from_true_ir(
            0.75, campaign_offset=shift
        )

    def test_the_ordering_by_true_ir_survives_the_campaigns_shift(self) -> None:
        # §7.3's two instructions satisfied *together*: within a campaign the
        # map is still strictly decreasing, whatever shift that campaign drew,
        # because the shift is a constant added to every branch's ratio.  If the
        # shift multiplied or reset the map, a campaign could invert the
        # ordering and a strong mechanism could flip sooner than a weak one.
        ratios = [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
        for campaign in (CAMPAIGN, OTHER_CAMPAIGN, "3f1c9b60-0000-4000-8000-00000000000f"):
            shift = campaign_offset(campaign)
            probabilities = [
                probability_from_true_ir(ratio, campaign_offset=shift)
                for ratio in ratios
            ]
            assert all(
                later < earlier for earlier, later in itertools.pairwise(probabilities)
            ), (campaign, probabilities)

    def test_the_variation_is_large_enough_to_change_the_mean_depth(self) -> None:
        # A variation too small to move the mean would satisfy the letter of
        # "vary" while leaving every campaign effectively identical.  Over the
        # campaigns sampled, the mean depth must span a meaningful range.
        means = [
            flip_depth_distribution(f"3f1c9b60-0000-4000-8000-{index:012d}", 1.0).mean_depth
            for index in range(1, 16)
        ]
        assert max(means) / min(means) > 1.5, means


class TestTheShiftIsReproducible:
    """§12: a campaign replayed from the same seed draws the same distribution."""

    def test_the_same_campaign_always_draws_the_same_shift(self) -> None:
        assert campaign_offset(CAMPAIGN) == campaign_offset(CAMPAIGN)

    def test_a_repeated_distribution_is_identical_field_by_field(self) -> None:
        first = flip_depth_distribution(CAMPAIGN, 0.4)
        second = flip_depth_distribution(CAMPAIGN, 0.4)
        assert first == second
        assert first.to_payload() == second.to_payload()

    def test_the_campaign_id_is_the_seed_the_shift_comes_from(self) -> None:
        # The shift is drawn from the campaign's canonical UUID read as an
        # integer hex, so the mapping is stable and collision-free: two ids that
        # differ anywhere give two different seeds.
        assert campaign_as_seed(CAMPAIGN) != campaign_as_seed(OTHER_CAMPAIGN)
        assert campaign_as_seed(CAMPAIGN) == int(CAMPAIGN.replace("-", ""), 16)

    def test_a_non_canonical_spelling_of_an_id_shifts_the_same_way(self) -> None:
        # A caller who hands the id in upper case, or as a UUID object, has
        # named the same campaign; the shift must be that campaign's shift.
        assert campaign_as_seed(CAMPAIGN.upper()) == campaign_as_seed(CAMPAIGN)
        assert campaign_offset(str(uuid.UUID(CAMPAIGN))) == campaign_offset(CAMPAIGN)

    def test_the_draw_repeated_is_the_same_depth(self, tmp_path: Path) -> None:
        # The end-to-end determinism claim: re-drawing a branch from the same
        # true IR in the same campaign reproduces the depth that was persisted,
        # because the shift and the node seed are both reproducible.
        store, url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        first = store.draw(node, 0.8)
        assert _stored_depth(store, node) == first
        assert store.draw(node, 0.8) == first
        assert FlipDepth(url).load(node) == first

    def test_a_different_campaign_draws_its_own_branch_from_its_own_distribution(
        self, tmp_path: Path
    ) -> None:
        # And the other half: the variation is visible *through the store*, not
        # only on the value.  The same true IR and the same node id — so the
        # geometric seed is identical — drawn in two campaigns: each stored
        # depth is exactly the depth *that* campaign's probability produces,
        # which pins the variation as the cause rather than the seed.
        from nulloracle import flip_depth as geometric

        seed = int(NODE.replace("-", ""), 16)
        for name, campaign in (
            ("a.db", CAMPAIGN),
            ("b.db", OTHER_CAMPAIGN),
        ):
            store, _url = _store(tmp_path, name)
            row = _campaign(store, campaign)
            node = _node(store, row, NODE)
            probability = flip_depth_distribution(campaign, 1.0).probability
            assert store.draw(node, 1.0) == geometric(probability, seed=seed)


# -- The distribution value --------------------------------------------------------


class TestTheDistributionIsAValueRatherThanANumber:
    """"...which returns a distribution" — not merely a probability."""

    def test_the_distribution_carries_its_own_inputs(self) -> None:
        distribution = flip_depth_distribution(CAMPAIGN, 0.6)
        payload = distribution.to_payload()
        assert payload["campaign_id"] == CAMPAIGN
        assert payload["true_ir"] == 0.6
        assert payload["campaign_offset"] == campaign_offset(CAMPAIGN)
        assert payload["probability"] == distribution.probability
        assert payload["mean_depth"] == pytest.approx(1.0 / distribution.probability)

    def test_the_payload_is_json_safe_and_carries_no_node_or_label(self) -> None:
        # A description of a distribution is a thing a log line may carry; the
        # node it will be drawn for and §7.1's bit are not.
        import json

        payload = flip_depth_distribution(CAMPAIGN, 0.6).to_payload()
        assert json.loads(json.dumps(payload)) == payload
        assert "is_null" not in payload
        assert "node_id" not in payload

    def test_a_doctored_probability_is_refused_by_name(self) -> None:
        # The recompute-and-compare discipline: this number is what a branch's
        # depth will actually be drawn from, so a value whose stated probability
        # and whose inputs disagree is not the distribution a branch drew from.
        genuine = flip_depth_distribution(CAMPAIGN, 0.6)
        with pytest.raises(KsGuardError, match="probability"):
            FlipDepthDistribution(
                campaign_id=genuine.campaign_id,
                true_ir=genuine.true_ir,
                campaign_offset=genuine.campaign_offset,
                probability=genuine.probability + 0.01,
            )

    def test_a_doctored_shift_is_refused_by_name(self) -> None:
        genuine = flip_depth_distribution(CAMPAIGN, 0.6)
        with pytest.raises(KsGuardError, match="probability"):
            FlipDepthDistribution(
                campaign_id=genuine.campaign_id,
                true_ir=genuine.true_ir,
                campaign_offset=genuine.campaign_offset + 0.25,
                probability=genuine.probability,
            )

    def test_a_non_canonical_campaign_id_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="campaign_id"):
            FlipDepthDistribution(
                campaign_id="not-a-uuid",
                true_ir=0.0,
                campaign_offset=0.0,
                probability=probability_from_true_ir(0.0),
            )

    def test_a_probability_outside_the_open_interval_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="probability"):
            FlipDepthDistribution(
                campaign_id=CAMPAIGN,
                true_ir=0.0,
                campaign_offset=0.0,
                probability=1.0,
            )

    def test_the_distribution_is_frozen(self) -> None:
        # Frozen rather than merely conventionally immutable: a distribution
        # that could be edited after its own consistency check would be a value
        # whose probability and whose inputs could be made to disagree, which is
        # exactly what __post_init__ exists to prevent.
        import dataclasses

        distribution = flip_depth_distribution(CAMPAIGN, 0.6)
        with pytest.raises(dataclasses.FrozenInstanceError):
            distribution.probability = 0.5  # type: ignore[misc]

    def test_a_malformed_campaign_id_is_refused_before_the_shift_is_drawn(self) -> None:
        with pytest.raises(KsGuardError, match="campaign_id"):
            flip_depth_distribution("not-a-uuid", 0.0)

    def test_a_non_finite_ratio_is_refused_by_the_composing_helper(self) -> None:
        with pytest.raises(KsGuardError, match="true_ir"):
            flip_depth_distribution(CAMPAIGN, float("nan"))


# -- The store ----------------------------------------------------------------------


class TestTheStoreReadsTheCampaignRatherThanTrustingIt:
    """The shift varies by campaign, so the campaign is read from the node's row."""

    def test_the_store_reports_the_nodes_own_campaigns_distribution(
        self, tmp_path: Path
    ) -> None:
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        distribution = store.distribution_for_node(node, 0.9)
        assert distribution.campaign_id == CAMPAIGN
        assert distribution == flip_depth_distribution(CAMPAIGN, 0.9)

    def test_a_caller_supplied_campaign_cannot_override_the_row(self, tmp_path: Path) -> None:
        # There is no campaign argument on the store's read path, deliberately:
        # a caller-supplied id that disagreed with the row would vary the
        # distribution by the wrong campaign, and the drift would be invisible —
        # the depth would persist and resolve like any other.
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        assert (
            store.distribution_for_node(node, 0.9).campaign_id == CAMPAIGN
        )

    def test_the_pure_distribution_needs_no_database_at_all(self, tmp_path: Path) -> None:
        # The campaign's shift is a function of its id, so a caller holding the
        # world's true IRs but no relational store can still report what it is
        # drawing from — and the call must not open the file.
        path = tmp_path / "never.db"
        store = TrueIRFlipDepth(f"sqlite:///{path}")
        distribution = store.distribution(CAMPAIGN, 0.5)
        assert distribution.probability == probability_from_true_ir(
            0.5, campaign_offset=campaign_offset(CAMPAIGN)
        )
        assert not path.exists()

    def test_construction_performs_no_io(self, tmp_path: Path) -> None:
        path = tmp_path / "absent.db"
        store = TrueIRFlipDepth(f"sqlite:///{path}")
        assert store._path is None
        assert not path.exists()
        assert store.database_url == f"sqlite:///{path}"


class TestTheDepthIsDrawnThroughFeature119:
    """The write is feature 119's: this module supplies ``p`` and delegates the draw."""

    def test_the_drawn_depth_is_the_one_the_probability_produces(
        self, tmp_path: Path
    ) -> None:
        # Composed, not merely parallel: the depth stored on the node must be
        # feature 119's own draw from the probability this module computed —
        # otherwise the two features would be drawing from different numbers.
        from nulloracle import flip_depth as geometric

        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        probability = store.distribution(CAMPAIGN, 1.2).probability
        expected = geometric(probability, seed=int(NODE.replace("-", ""), 16))
        assert store.draw(node, 1.2) == expected
        assert _stored_depth(store, node) == expected

    def test_the_drawn_depth_lands_on_the_nodes_own_column(self, tmp_path: Path) -> None:
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        assert _stored_depth(store, node) is None
        depth = store.draw(node, 0.5)
        assert depth >= 1
        assert _stored_depth(store, node) == depth

    def test_every_root_stays_real_through_the_extra_indirection(self, tmp_path: Path) -> None:
        # Feature 119's invariant, preserved: a root sits at depth 0 and the
        # geometric's support starts at 1, so no shift this module can draw can
        # make the flip land on a root.  Asserted across the extreme ratios and
        # a spread of nodes, because the indirection is where a support
        # regression would hide.
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        for index, ratio in enumerate((-1e6, -5.0, 0.0, 5.0, 1e6)):
            node = _node(store, campaign, f"3f1c9b60-0000-4000-8000-{index:012d}")
            assert store.draw(node, ratio) >= 1

    def test_the_module_level_spelling_draws_and_persists(self, tmp_path: Path) -> None:
        store, url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        depth = draw_flip_depth(node, 0.7, database_url=url)
        assert depth >= 1
        assert _stored_depth(store, node) == depth

    def test_the_module_level_spelling_reads_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        monkeypatch.setenv(DATABASE_URL_ENV, url)
        assert draw_flip_depth(node, 0.7) == store.draw(node, 0.7)

    def test_the_store_draws_the_distribution_it_reports(self, tmp_path: Path) -> None:
        # The read path and the write path agree: what distribution_for_node
        # says will be drawn is what draw() actually draws from.
        from nulloracle import flip_depth as geometric

        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        reported = store.distribution_for_node(node, 0.3).probability
        expected = geometric(reported, seed=int(NODE.replace("-", ""), 16))
        assert store.draw(node, 0.3) == expected


class TestTheDrawRefusesRatherThanGuesses:
    """Store-contract and regime refusals, each naming what it is about."""

    def test_a_node_the_table_does_not_hold_is_refused(self, tmp_path: Path) -> None:
        store, _url = _store(tmp_path)
        _campaign(store, CAMPAIGN)
        with pytest.raises(KsGuardError, match="holds no row"):
            store.draw("3f1c9b60-0000-4000-8000-0000000000ff", 0.5)

    def test_a_campaign_the_table_does_not_hold_is_refused(self, tmp_path: Path) -> None:
        store, _url = _store(tmp_path)
        node = _node(store, "3f1c9b60-0000-4000-8000-0000000000aa", NODE)
        with pytest.raises(KsGuardError, match="campaign table holds no row"):
            store.draw(node, 0.5)

    def test_a_type_r_campaign_is_refused_with_its_type_named(self, tmp_path: Path) -> None:
        # §7.3: campaigns are homogeneous in null type, and only the Type-D
        # regime has a flip depth.  A flip drawn onto a Type-R branch would be
        # a depth written down that feature 121 would never serve.
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN, campaign_type="Type-R")
        node = _node(store, campaign, NODE)
        with pytest.raises(KsGuardError, match="Type-R"):
            store.draw(node, 0.5)
        assert _stored_depth(store, node) is None

    def test_a_failure_in_the_delegated_write_leaves_no_depth_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The read and the delegated write are two transactions, so this is the
        # property that keeps that split honest: if feature 119's write fails,
        # nothing is half-recorded.  A branch must never look drawn when it is
        # not — the campaign loop would move on and the world would carry a
        # branch whose flip was never fixed, which is the failure mode §7.3's
        # whole persistence rule exists to prevent.
        from nulloracle import FlipDepth

        store, url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)

        def refuse(*_args: object, **_kwargs: object) -> int:
            raise KsGuardError("simulated failure inside the delegated write")

        monkeypatch.setattr(FlipDepth, "persist", refuse)
        with pytest.raises(KsGuardError, match="delegated write"):
            store.draw(node, 0.5)
        assert _stored_depth(store, node) is None

        # ...and the failure does not wedge the store: once the delegate works
        # again, the draw completes and the depth is the one feature 119 reads.
        monkeypatch.undo()
        depth = store.draw(node, 0.5)
        assert depth >= 1
        assert FlipDepth(url).load(node) == depth

    def test_a_type_r_campaign_is_refused_on_the_read_path_too(self, tmp_path: Path) -> None:
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN, campaign_type="Type-R")
        node = _node(store, campaign, NODE)
        with pytest.raises(KsGuardError, match="Type-R"):
            store.distribution_for_node(node, 0.5)

    @pytest.mark.parametrize("node", ["not-a-uuid", None, 5, ""])
    def test_a_malformed_node_id_is_refused(self, tmp_path: Path, node: object) -> None:
        store, _url = _store(tmp_path)
        with pytest.raises(KsGuardError):
            store.draw(node, 0.5)

    def test_a_node_id_refusal_is_a_ks_guard_error_not_a_sidecar_one(
        self, tmp_path: Path
    ) -> None:
        # The taxonomy: the id handed to a *store* is a store-contract failure.
        # A caller reading SidecarError out of a flip-depth draw would look in
        # the wrong module for the cause.
        store, _url = _store(tmp_path)
        with pytest.raises(KsGuardError) as raised:
            store.draw("not-a-uuid", 0.5)
        assert not isinstance(raised.value, SidecarError)

    @pytest.mark.parametrize("ratio", [float("nan"), float("inf"), True, "0.5", None])
    def test_a_ratio_that_is_not_a_finite_real_is_refused(
        self, tmp_path: Path, ratio: object
    ) -> None:
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        with pytest.raises(KsGuardError):
            store.draw(node, ratio)
        assert _stored_depth(store, node) is None

    def test_a_refused_ratio_opens_no_connection(self, tmp_path: Path) -> None:
        # The ratio is validated before the store is opened, so a refused
        # argument leaves no file behind — a caller retrying with a good ratio
        # starts from the same state.
        path = tmp_path / "untouched.db"
        store = TrueIRFlipDepth(f"sqlite:///{path}")
        with pytest.raises(KsGuardError):
            store.draw(NODE, float("nan"))
        assert not path.exists()

    def test_the_module_level_spelling_refuses_when_no_store_is_named(self) -> None:
        # By name rather than silently doing nothing: a depth that skipped its
        # write would leave a branch looking undrawn while the campaign loop
        # believed it had fixed the flip.
        with pytest.raises(KsGuardError, match="DATABASE_URL"):
            draw_flip_depth(NODE, 0.5, env={})

    def test_the_module_level_spelling_refuses_a_blank_store(self) -> None:
        with pytest.raises(KsGuardError, match="DATABASE_URL"):
            draw_flip_depth(NODE, 0.5, env={DATABASE_URL_ENV: "   "})

    def test_a_blank_store_url_is_refused_at_construction(self) -> None:
        with pytest.raises(KsGuardError, match="DATABASE_URL"):
            TrueIRFlipDepth("")

    def test_a_scheme_this_store_cannot_speak_is_refused(self, tmp_path: Path) -> None:
        store = TrueIRFlipDepth("postgresql://user@host/db")
        with pytest.raises(KsGuardError, match="scheme"):
            store.draw(NODE, 0.5)

    def test_an_in_memory_store_is_refused(self) -> None:
        store = TrueIRFlipDepth("sqlite://")
        with pytest.raises(KsGuardError, match="database path"):
            store.draw(NODE, 0.5)

    def test_an_unconfigured_environment_composes_None_rather_than_raising(self) -> None:
        assert TrueIRFlipDepth.resolve(env={}) is None
        assert TrueIRFlipDepth.resolve(env={DATABASE_URL_ENV: "  "}) is None
        assert isinstance(
            TrueIRFlipDepth.resolve(env={DATABASE_URL_ENV: "sqlite:///x.db"}),
            TrueIRFlipDepth,
        )


class TestTheStoreReadsWhatItSaysItReads:
    """The store's own reads, pinned against the rows the other stores write."""

    def test_the_store_creates_the_five_column_node_table_the_migration_does(
        self, tmp_path: Path
    ) -> None:
        # The node table is owned by feature 97's migration, which creates it
        # with exactly the five structural columns.  A store that recreated the
        # node table with a sixth column would be a second schema wearing the
        # migration's table name, and the two writers of the same rows would
        # disagree about them.
        store, _url = _store(tmp_path)
        with closing(store._connect()) as connection:
            created = [row[1] for row in _table_info(connection, NODE_TABLE)]
        assert created == ["id", "parent_id", "campaign_id", "theme_root", "depth"]

    def test_the_store_works_against_a_migration_created_table(self, tmp_path: Path) -> None:
        # The production arrangement: the node table predates this feature, so
        # the store must open a database the *migration* created and draw
        # against the rows the discovery loop inserted into it.
        migration = _migration()
        path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{path}")
        url = f"sqlite:///{path}"
        store = TrueIRFlipDepth(url)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        depth = store.draw(node, 0.9)
        assert depth >= 1
        assert _stored_depth(store, node) == depth
        assert FlipDepth(url).load(node) == depth

    def test_the_store_does_not_add_the_flip_depth_column(self, tmp_path: Path) -> None:
        # Feature 119 owns that column; this store opens only what it reads, and
        # a store that added it would be reaching into feature 119's contract.
        store, _url = _store(tmp_path)
        with closing(store._connect()) as connection:
            created = {row[1] for row in _table_info(connection, NODE_TABLE)}
        assert "flip_depth" not in created

    def test_the_store_opens_an_existing_database_without_changing_it(
        self, tmp_path: Path
    ) -> None:
        store, _url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        store.draw(node, 0.5)
        before = _stored_depth(store, node)
        # Re-opening is idempotent: the CREATE TABLE IF NOT EXISTS dance leaves a
        # table that already exists exactly as it was.  After a draw the table
        # carries feature 119's column too — added by feature 119's store, once,
        # in the same transaction as the write — and re-opening must not add it
        # a second time or disturb the row.
        for _ in range(2):
            with closing(store._connect()) as connection:
                columns = [row[1] for row in _table_info(connection, NODE_TABLE)]
            assert columns == [
                "id",
                "parent_id",
                "campaign_id",
                "theme_root",
                "depth",
                "flip_depth",
            ]
        assert _stored_depth(store, node) == before

    def test_the_store_composes_with_feature_119s_store_on_one_database(
        self, tmp_path: Path
    ) -> None:
        # The two stores write and read the same rows through their own
        # connections: a depth drawn here is a depth feature 119's store loads,
        # and a campaign feature 119's store would accept is one this accepts.
        store, url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        depth = store.draw(node, 0.9)
        assert FlipDepth(url).load(node) == depth

    def test_a_second_store_over_the_same_url_agrees(self, tmp_path: Path) -> None:
        store, url = _store(tmp_path)
        campaign = _campaign(store, CAMPAIGN)
        node = _node(store, campaign, NODE)
        depth = store.draw(node, 0.9)
        assert TrueIRFlipDepth(url).draw(node, 0.9) == depth
