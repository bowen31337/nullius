"""Feature 263's law: the cross-world aggregation.

*System aggregates across worlds as a blend of the stratum mean and the
stratum minimum, which returns a score with lambda between 0.5 and 0.7*
(app_spec.xml, "Objective Scoring & CVaR Aggregation").  The tests here
hold :mod:`scoring._aggregate` to the sentence's three clauses, in
order:

* **the blend** — prd §7.2's and docs §10.3's
  ``(1 − λ)·mean_g(V_g^m) + λ·min_g(V_g^m)``, taken over stratum
  figures that weigh equally (never by world count), answering a
  convex combination that can neither flatter above the stratum mean
  nor bury below the stratum minimum
  (:func:`test_the_blend_is_the_formula`,
  :func:`test_strata_weigh_equally_not_by_world_count`,
  :func:`test_the_score_stays_between_the_two_terms`,
  :func:`test_a_catastrophic_stratum_drags_the_score_below_the_plain_mean`);
* **across worlds** — one world once, one stratum each, duck-typed
  carriers read for the two attributes the blend needs, and the strata
  arriving as a mapping (an unstratified collection is the plain mean
  feature 264 exists to reject, and is refused here)
  (:func:`test_a_world_is_read_duck_typed`, the partition and
  shape-refusal tests below);
* **with lambda between 0.5 and 0.7** — the band's edges blend and its
  outside refuses, each side of the band named in the refusal for the
  aggregation it drifts into, and the value carrying the λ it was
  blended under (:func:`test_the_bands_edges_blend`,
  :func:`test_a_lambda_outside_the_band_is_refused`,
  :func:`test_the_value_carries_the_lambda_it_was_blended_under`).

The empty-stratum half of the refusal profile is pinned from this side
too (:func:`test_an_empty_stratum_is_refused_not_zeroed`): the hole is
the coverage ledger's to name and feature 286's ``empty_stratum``
warning's to report — an aggregation that invented a 0.0 for a stratum
nobody measured would drag the blend's minimum onto a number nobody
measured, which is worse than refusing.

What these tests deliberately do not reach: composition (that is
``test_component.py`` — 263 adds no component, the composed ``scoring``
callable stays the per-world objective), the seat (``test_app_module.py``
— unchanged), and anything that names *which* strata exist or rejects a
plain mean across them (feature 264's law over this seam).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import FrozenInstanceError

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    StandInScore,
    world_score,
)
from scoring import (
    LAMBDA_CEILING,
    LAMBDA_DEFAULT,
    LAMBDA_FLOOR,
    AggregatedObjective,
    AggregationError,
    ScoringError,
    WorldScore,
    aggregate_objective,
    world_objective,
)

#: Every λ in the band, in steps the floats carry exactly — the sweep the
#: convexity and monotonicity tests read.
_BAND = [0.5, 0.55, 0.6, 0.65, 0.7]


# -- the blend --------------------------------------------------------------------


def test_the_blend_is_the_formula(strata: dict[str, list[WorldScore]]) -> None:
    # prd §7.2's formula over the fixture's hand-computed figures: stratum
    # figures 0.75 / 0.5 / 0.25, unweighted stratum mean 0.5 (exact — the
    # three figures sum to 1.5 over three strata), stratum minimum 0.25
    # earned by crash, and therefore (1 − 0.5)·0.5 + 0.5·0.25 = 0.375 —
    # every number in the chain dyadic, so the equality is exact and not
    # an approximation a wrong-but-close formula could also pass.
    aggregate = aggregate_objective(strata, lam=0.5)
    assert aggregate.stratum_means == {
        "high-volatility trend": 0.75,
        "low-volatility chop": 0.5,
        "crash": 0.25,
    }
    assert aggregate.stratum_mean == 0.5
    assert aggregate.stratum_minimum == 0.25
    assert aggregate.worst_stratum == "crash"
    assert aggregate.score == 0.375
    assert aggregate.world_count == 7


def test_the_default_lambda_is_the_bands_midpoint(
    strata: dict[str, list[WorldScore]],
) -> None:
    # Both documents state a band, not a point, so the default is a stated
    # parameterization — the midpoint — published as a constant rather
    # than hidden in a keyword (the stance feature 228's PRIOR_STRENGTH
    # takes for its own unstated number), and a caller that names no λ
    # blends under exactly it.
    assert LAMBDA_FLOOR == 0.5
    assert LAMBDA_CEILING == 0.7
    assert LAMBDA_DEFAULT == (LAMBDA_FLOOR + LAMBDA_CEILING) / 2
    aggregate = aggregate_objective(strata)
    assert aggregate.lam == LAMBDA_DEFAULT
    assert aggregate.score == pytest.approx(0.35)


def test_the_bands_edges_blend(strata: dict[str, list[WorldScore]]) -> None:
    # Inclusive at both edges, as prd §7.2's λ ∈ [0.5, 0.7] states: the
    # floor is the most mean-leaning posture the documents allow and the
    # ceiling the most tail-leaning, and both are blends, not refusals.
    # Between them the score falls monotonically — score(λ) = mean +
    # λ·(min − mean), and min < mean — which is the whole point of the
    # knob: more λ, more fear.
    scores = [aggregate_objective(strata, lam=lam).score for lam in (0.5, 0.6, 0.7)]
    assert scores[0] == 0.375
    assert scores[1] == pytest.approx(0.35)
    assert scores[2] == pytest.approx(0.325)
    assert scores[0] > scores[1] > scores[2]


def test_the_score_stays_between_the_two_terms(
    strata: dict[str, list[WorldScore]],
) -> None:
    # A convex combination over a λ in [0, 1]: the answer can never leave
    # the interval between the stratum minimum and the stratum mean — no λ
    # in the band can flatter a policy above its strata-average figure,
    # and none can bury it below the regime that actually earned the
    # bottom.  Swept across the band rather than pinned at the edges,
    # because the guarantee is about every blend the band allows.
    for lam in _BAND:
        aggregate = aggregate_objective(strata, lam=lam)
        assert aggregate.stratum_minimum <= aggregate.score <= aggregate.stratum_mean
        assert aggregate.stratum_minimum < aggregate.score < aggregate.stratum_mean


def test_strata_weigh_equally_not_by_world_count(
    strata: dict[str, list[WorldScore]],
) -> None:
    # mean_g averages the stratum *figures* — a stratum with three worlds
    # and a stratum with two weigh the same — because a mean over worlds
    # would weight a regime by how many worlds happen to be stored in it,
    # and a chop pool twice the size of the trend pool would quietly halve
    # the chop regime's voice exactly when the blend exists to amplify it.
    # The fixture is built for this: the plain mean over its seven worlds
    # is 3.25/7 ≈ 0.4643, and the stratum mean is 0.5 — a full world-count
    # weighting apart, pinned so the blend cannot quietly slide onto the
    # other one.
    plain_mean_over_worlds = pytest.approx(3.25 / 7)
    assert 0.5 != plain_mean_over_worlds
    for lam in _BAND:
        # Every blend in the band reads the equal-weight figure — the
        # weighting is the arithmetic's, not the knob's.
        assert aggregate_objective(strata, lam=lam).stratum_mean == 0.5


def test_a_catastrophic_stratum_drags_the_score_below_the_plain_mean() -> None:
    # The PRD's own story, stated three lines above the formula: *"a
    # policy that is brilliant in trending worlds and catastrophic in chop
    # averages to 'fine' and then blows up."*  Trend at +0.8, chop at
    # −0.4, crash at −0.2: the plain mean over the worlds calls this
    # policy +0.0667 — fine — while the blend at any λ in the band calls
    # it what the worst regime says it is, below the mean by λ·(mean −
    # min) and falling as λ rises.
    pool = {
        "high-volatility trend": [world_score("t1", 0.8), world_score("t2", 0.8)],
        "low-volatility chop": [world_score("c1", -0.4), world_score("c2", -0.4)],
        "crash": [world_score("k1", -0.2), world_score("k2", -0.2)],
    }
    plain = (0.8 + 0.8 - 0.4 - 0.4 - 0.2 - 0.2) / 6
    for lam in _BAND:
        aggregate = aggregate_objective(pool, lam=lam)
        assert aggregate.score < plain
        assert aggregate.worst_stratum == "low-volatility chop"
    # And the drag is the knob's own arithmetic: mean 0.0667, min −0.4,
    # λ = 0.7 → 0.3·0.0667 − 0.7·0.4 ≈ −0.26.
    assert aggregate_objective(pool, lam=0.7).score == pytest.approx(-0.26)


def test_agreeing_strata_answer_that_figure() -> None:
    # Where the stratum figures all agree, every λ in the band answers
    # that figure — the minimum and the mean are the same number, and the
    # blend is then the mean.  The only pool for which that is true, and
    # the reason a swept λ is worth its noise only when strata disagree.
    pool = {
        "trend": [world_score("t1", 0.5), world_score("t2", 0.75)],
        "chop": [world_score("c1", 0.625)],
    }
    for lam in _BAND:
        aggregate = aggregate_objective(pool, lam=lam)
        assert aggregate.stratum_mean == pytest.approx(0.625)
        assert aggregate.stratum_minimum == pytest.approx(0.625)
        assert aggregate.score == pytest.approx(0.625)


def test_a_single_stratum_answers_its_mean() -> None:
    # One stratum is the degenerate pool: its figure is both the mean term
    # and the minimum term, the worst stratum is the only stratum, and
    # every λ answers the figure.  Not refused — a pool early in coverage
    # may well hold one populated stratum — and not flattened either: the
    # worlds still weigh once each inside the figure.
    pool = {"crash": [world_score("k1", -0.2), world_score("k2", 0.1)]}
    aggregate = aggregate_objective(pool, lam=LAMBDA_DEFAULT)
    assert aggregate.stratum_means == {"crash": pytest.approx(-0.05)}
    assert aggregate.stratum_mean == aggregate.stratum_minimum
    assert aggregate.worst_stratum == "crash"
    assert aggregate.score == pytest.approx(-0.05)
    assert aggregate.world_count == 2


def test_a_tie_on_the_minimum_names_the_first_stratum() -> None:
    # The one place the arithmetic is order-sensitive is the argmin, and
    # the law fixes it: strata are read in sorted-name order, so a tie on
    # the minimum names the lexicographically first stratum — the same
    # figures always name the same worst regime, whatever order the
    # caller's mapping happened to iterate in.
    pool = {
        "low-volatility chop": [world_score("c1", 0.25)],
        "crash": [world_score("k1", 0.25)],
        "high-volatility trend": [world_score("t1", 0.75)],
    }
    aggregate = aggregate_objective(pool, lam=0.5)
    assert aggregate.stratum_minimum == 0.25
    assert aggregate.worst_stratum == "crash"


def test_the_aggregate_is_order_independent(strata: dict[str, list[WorldScore]]) -> None:
    # The same strata, every order the caller could hand them in: the
    # mapping reversed, each stratum's worlds reversed, and both — the
    # same score to the last bit, because the figures are summed with
    # math.fsum (exactly rounded, so order-independent in its result) and
    # read over sorted names.  The determinism law the per-world score
    # states (docs §10.1), held one level up at the number the dreaming
    # loop's argmax ranks on.
    reference = aggregate_objective(strata, lam=0.5)
    reversed_strata = {
        name: list(reversed(worlds)) for name, worlds in reversed(list(strata.items()))
    }
    assert list(reversed_strata) != list(strata)
    reordered = aggregate_objective(reversed_strata, lam=0.5)
    assert reordered.score == reference.score
    assert reordered.stratum_mean == reference.stratum_mean
    assert reordered.stratum_minimum == reference.stratum_minimum
    assert reordered.worst_stratum == reference.worst_stratum
    assert reordered.stratum_means == reference.stratum_means


def test_the_value_carries_the_lambda_it_was_blended_under(
    strata: dict[str, list[WorldScore]],
) -> None:
    # The sentence's second clause is a fact about the value, not only
    # about the ask: *"returns a score with lambda between 0.5 and 0.7"*
    # — so the score carries the knob it was blended under, and an
    # operator comparing two aggregates reads the λ each was blended at
    # off the values themselves rather than off the calls that made them.
    for lam in _BAND:
        assert aggregate_objective(strata, lam=lam).lam == lam
    assert LAMBDA_FLOOR <= aggregate_objective(strata).lam <= LAMBDA_CEILING


def test_the_value_is_frozen_and_unaliased(
    strata: dict[str, list[WorldScore]],
) -> None:
    # A ranking that moved beneath the dreaming loop's argmax would be a
    # selection that changed with nothing — the same guarantee the world
    # score makes one feature earlier — and the stratum figures are a
    # read-only copy, never the caller's dict, so a caller that keeps
    # writing its authoring mapping cannot move an aggregate already
    # answered.
    aggregate = aggregate_objective(strata, lam=0.5)
    with pytest.raises(FrozenInstanceError):
        aggregate.score = 1.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        aggregate.stratum_means["crash"] = 0.0  # type: ignore[index]
    authoring = {"crash": [world_score("k1", 0.25)]}
    answered = aggregate_objective(authoring, lam=0.5)
    authoring["crash"].append(world_score("k2", 9.0))
    authoring["spare"] = [world_score("s1", 9.0)]
    assert answered.stratum_means == {"crash": 0.25}
    assert answered.world_count == 1


# -- across worlds: the seam and the partition ------------------------------------


def test_a_world_is_read_duck_typed(strata: dict[str, list[WorldScore]]) -> None:
    # The blend reads the two attributes it needs — world_id and score —
    # and validates what it reads, because the module loader imports this
    # member under a synthetic name and re-executes it, so a score this
    # process composed may be a second WorldScore class object and a type
    # check would refuse the very objects composition produces.  A carrier
    # exposing exactly those two attributes aggregates identically.
    stand_in = {
        "high-volatility trend": [StandInScore("trend-a", 0.75), StandInScore("trend-b", 0.75)],
        "low-volatility chop": [StandInScore("chop-a", 0.5), StandInScore("chop-b", 0.5)],
        "crash": [
            StandInScore("crash-a", 0.25),
            StandInScore("crash-b", 0.25),
            StandInScore("crash-c", 0.25),
        ],
    }
    from_scores = aggregate_objective(strata, lam=0.5)
    from_carriers = aggregate_objective(stand_in, lam=0.5)  # type: ignore[arg-type]
    assert from_carriers.score == from_scores.score
    assert from_carriers.stratum_means == from_scores.stratum_means
    assert from_carriers.world_count == from_scores.world_count


def test_a_stratum_accepts_the_mapping_spelling() -> None:
    # A stratum's worlds may arrive as a mapping of world id to score,
    # read for its values — iterating a mapping would read its keys,
    # which are names, not scores, and a seam that refused a right shape
    # spelled the other right way would be harder than the law it
    # carries.
    by_id = {
        "crash": {
            "k1": StandInScore("k1", 0.25),
            "k2": StandInScore("k2", 0.75),
        }
    }
    aggregate = aggregate_objective(by_id, lam=0.5)  # type: ignore[arg-type]
    assert aggregate.stratum_means == {"crash": 0.5}
    assert aggregate.world_count == 2


def test_a_beta_term_moves_the_blend_not_the_measurement(
    strata: dict[str, list[WorldScore]],
) -> None:
    # The pipeline the category is building, end to end over the seam the
    # objective shipped: every world's score is moved by its β-terms
    # through WorldScore.adjusted (features 257-262), and the blend takes
    # the scores as they were earned.  A −0.25 penalty on every world
    # moves every figure and the answer by exactly −0.25 — the blend is
    # translation-equivariant, so penalties a candidate earned travel
    # into its aggregate whole, and the measurement underneath each score
    # is still the measurement.
    penalized = {
        name: [world.adjusted(-0.25) for world in worlds]
        for name, worlds in strata.items()
    }
    reference = aggregate_objective(strata, lam=0.5)
    moved = aggregate_objective(penalized, lam=0.5)
    assert moved.score == pytest.approx(reference.score - 0.25)
    assert moved.stratum_means == {
        name: pytest.approx(figure - 0.25)
        for name, figure in reference.stratum_means.items()
    }
    assert moved.worst_stratum == reference.worst_stratum


def test_an_aggregate_from_the_objectives_own_scores() -> None:
    # The two laws of the member, composed: three worlds scored by the
    # per-world objective over hand-computed panels (ratios 3.0, 6.0 and
    # 0.0 — two dates each, the ratio (a+b)/|a−b| of a two-date panel:
    # 3/1 for (1, 2), 12/2 for (5, 7), 0/2 for (−1, 1)),
    # grouped into strata, blended.  Figures 3.0 / 6.0 / 0.0, stratum mean
    # 3.0, minimum 0.0 earned by the crash pick, λ = 0.5 → 1.5 exactly:
    # the number feature 274's argmax will rank on, built from the number
    # feature 256 answers.
    panels = {
        "high-volatility trend": {dt.date(2026, 1, 5): 1.0, dt.date(2026, 1, 6): 2.0},
        "low-volatility chop": {dt.date(2026, 1, 5): 5.0, dt.date(2026, 1, 6): 7.0},
        "crash": {dt.date(2026, 1, 5): -1.0, dt.date(2026, 1, 6): 1.0},
    }
    worlds = {
        name: [world_objective(name, f"campaign-01/{name}/pick", panel)]
        for name, panel in panels.items()
    }
    aggregate = aggregate_objective(worlds, lam=0.5)
    assert aggregate.stratum_means == {
        "high-volatility trend": 3.0,
        "low-volatility chop": 6.0,
        "crash": 0.0,
    }
    assert aggregate.stratum_mean == 3.0
    assert aggregate.stratum_minimum == 0.0
    assert aggregate.score == 1.5


# -- the refusals -----------------------------------------------------------------


@pytest.mark.parametrize(
    "carried",
    [
        [world_score("w1", 0.5), world_score("w2", 0.25)],
        (world_score("w1", 0.5),),
        None,
        42,
    ],
)
def test_an_unstratified_collection_is_refused(carried: object) -> None:
    # The strata are the axis the blend is taken over — a flat collection
    # of world scores cannot say which worlds share a regime, and
    # aggregating it anyway would be the plain mean feature 264 exists to
    # reject, arrived at from this feature's own side of the seam.  The
    # refusal names that, so the repair is a grouping, not a different
    # number.
    with pytest.raises(AggregationError, match="stratifies|plain mean"):
        aggregate_objective(carried)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["", "   ", 7, True, None])
def test_a_stratum_that_is_not_a_name_is_refused(name: object) -> None:
    # A stratum that cannot be named cannot be reported, warned empty by
    # the coverage ledger, or weighted — and the worst stratum is reported
    # *by name*, so the name has to be one.
    with pytest.raises(AggregationError, match="stratum"):
        aggregate_objective({name: [world_score("w1", 0.5)]})  # type: ignore[dict-item]


def test_no_strata_at_all_is_refused() -> None:
    # min_g over an empty set is undefined, and no neutral score is
    # invented for an ask with nothing to aggregate — a fabricated figure
    # would enter the dreaming loop's argmax as though a pool had been
    # measured.
    with pytest.raises(AggregationError, match="no strata"):
        aggregate_objective({})


def test_an_empty_stratum_is_refused_not_zeroed() -> None:
    # A stratum with no worlds has no figure to lend the blend, and a 0.0
    # invented for it would be read as a *measured* catastrophic regime —
    # dragging the blend's minimum onto a number nobody measured, which is
    # worse than the hole it papered over.  The hole is the ledger's to
    # name and feature 286's empty_stratum warning's to report; the
    # aggregation's own move is to refuse.
    with pytest.raises(AggregationError, match="nobody measured|empty_stratum"):
        aggregate_objective({"crash": []})


@pytest.mark.parametrize("worlds", [world_score("k1", 0.25), 42, None])
def test_a_stratum_whose_worlds_are_not_a_shape_is_refused(worlds: object) -> None:
    # A single world score is one world — the stratum's worlds arrive
    # together — and a scalar is not a collection of anything.
    with pytest.raises(AggregationError, match="iterable of world scores"):
        aggregate_objective({"crash": worlds})  # type: ignore[dict-item]


def test_a_bare_string_is_refused_as_the_worlds() -> None:
    # A string is a world's name, not the stratum's worlds; read as an
    # iterable it would iterate characters, and the refusal the first
    # character earned would be a message about the wrong repair
    # entirely.  Refused as itself, naming the two right shapes.
    with pytest.raises(AggregationError, match="a string is a world's name"):
        aggregate_objective({"crash": "crash-a"})  # type: ignore[dict-item]


@pytest.mark.parametrize("carried", [0.25, "crash-a", object(), None, True])
def test_a_carrier_that_is_not_a_world_score_is_refused(carried: object) -> None:
    # The seam is duck-typed, so what it reads it validates: a bare
    # number has no world to be, a string is a name and not the score
    # itself, and a plain object exposes nothing to read.  Refused here
    # rather than escaping as a TypeError from inside math.fsum.
    with pytest.raises(AggregationError, match="world score"):
        aggregate_objective({"crash": [carried]})  # type: ignore[list-item]


@pytest.mark.parametrize("world_id", ["", "   ", 7, True, None])
def test_a_carrier_whose_world_id_is_not_a_name_is_refused(world_id: object) -> None:
    # A world that cannot be named cannot be counted once — the partition
    # of worlds over strata is the blend's own arithmetic, and it starts
    # at the name.
    with pytest.raises(AggregationError, match="world_id"):
        aggregate_objective({"crash": [StandInScore(world_id, 0.25)]})  # type: ignore[arg-type]


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_a_carrier_whose_score_is_not_finite_is_refused(score: float) -> None:
    # The −∞ division of labour, held at the aggregate: the miss's −∞ is
    # feature 222's value, answered by the termination and never carrying
    # a pick, so no aggregation may counterfeit it — and a NaN would
    # compare false against every aggregate and drop out of the argmax
    # the blend exists to feed.
    with pytest.raises(AggregationError, match="must be finite"):
        aggregate_objective({"crash": [StandInScore("k1", score)]})


def test_a_world_twice_in_one_stratum_is_refused() -> None:
    # One world, once: a world id repeated inside its stratum
    # double-counts it in the stratum's own mean — a stratum
    # over-represented in its own figure.
    with pytest.raises(AggregationError, match="twice among the worlds"):
        aggregate_objective(
            {"crash": [world_score("k1", 0.25), world_score("k1", 0.75)]}
        )


def test_a_world_in_two_strata_is_refused() -> None:
    # The strata of one aggregation partition the worlds — each stored
    # world is assigned one stratum by the labeler — and a world blended
    # into two strata is counted twice in the mean over strata, whatever
    # each stratum's own figure says.
    with pytest.raises(AggregationError, match="in both stratum"):
        aggregate_objective(
            {
                "crash": [world_score("k1", 0.25)],
                "low-volatility chop": [world_score("k1", 0.75)],
            }
        )


@pytest.mark.parametrize("lam", [0.49, 0.71, 0.4, 1.0, -0.1, 0.4999999])
def test_a_lambda_outside_the_band_is_refused(
    lam: float, strata: dict[str, list[WorldScore]]
) -> None:
    # Both edges of the band are load bearing, and the refusal names the
    # drift each side falls into: below the floor the blend slides toward
    # the plain mean feature 264 exists to reject (regimes would weigh by
    # world count, not as regimes), above the ceiling it collapses onto
    # the single worst stratum — a pure minimum nobody specified.
    with pytest.raises(AggregationError, match="band"):
        aggregate_objective(strata, lam=lam)


@pytest.mark.parametrize("lam", [float("nan"), float("inf"), float("-inf"), True, "0.6", None])
def test_a_lambda_that_is_not_a_real_is_refused(
    lam: object, strata: dict[str, list[WorldScore]]
) -> None:
    # A NaN λ would make the blend a NaN, a bool is not a weight, and
    # text is refused rather than coerced — coercion is how a mistyped
    # knob becomes a silent blend.  (A ``bool`` is refused a branch
    # earlier — it is not a real at all — hence the two-pattern match.)
    with pytest.raises(AggregationError, match="real number|must be finite"):
        aggregate_objective(strata, lam=lam)  # type: ignore[arg-type]


# -- the value's own construction ---------------------------------------------------


def test_the_terms_cannot_disagree_with_the_trail() -> None:
    # The value validates at construction, the stance the world score
    # takes one feature earlier, and its terms cannot disagree with the
    # trail they summarize: a stratum_minimum that is not the figures'
    # minimum, a worst_stratum the figures do not carry, an empty trail,
    # or a count of no worlds are all refused — a value that let them
    # disagree could hide which regime was worst.
    good = dict[str, float](crash=0.25, trend=0.75)
    for broken in (
        {"score": 0.5, "lam": 0.6, "stratum_mean": 0.5, "stratum_minimum": 0.4,
         "worst_stratum": "crash", "stratum_means": good, "world_count": 2},
        {"score": 0.5, "lam": 0.6, "stratum_mean": 0.5, "stratum_minimum": 0.25,
         "worst_stratum": "chop", "stratum_means": good, "world_count": 2},
        {"score": 0.5, "lam": 0.6, "stratum_mean": 0.5, "stratum_minimum": 0.25,
         "worst_stratum": "crash", "stratum_means": {}, "world_count": 2},
        {"score": 0.5, "lam": 0.6, "stratum_mean": 0.5, "stratum_minimum": 0.25,
         "worst_stratum": "crash", "stratum_means": good, "world_count": 0},
        {"score": 0.5, "lam": 0.9, "stratum_mean": 0.5, "stratum_minimum": 0.25,
         "worst_stratum": "crash", "stratum_means": good, "world_count": 2},
    ):
        with pytest.raises(AggregationError):
            AggregatedObjective(**broken)  # type: ignore[arg-type]


# -- the vocabulary ----------------------------------------------------------------


def test_the_error_is_the_member_vocabulary(
    strata: dict[str, list[WorldScore]],
) -> None:
    # One base class for the member, so a dreaming loop wrapping its
    # aggregation step in a single except catches the blend's laws and
    # nothing else — the discipline the objective's own refusal pinned
    # one feature earlier, held for the number the argmax ranks on.
    with pytest.raises(AggregationError):
        aggregate_objective(strata, lam=0.9)
    assert issubclass(AggregationError, ScoringError)
    with pytest.raises(ScoringError):
        aggregate_objective(strata, lam=0.9)


def test_a_refusal_answers_nothing_partial(
    strata: dict[str, list[WorldScore]],
) -> None:
    # The aggregation either answers a complete frozen value or raises —
    # a caller can never hold a half-blended score it must remember to
    # discard.  The out-of-band ask and the legal one on either side of
    # it answer independently, so the refusal left no state behind.
    before = aggregate_objective(strata, lam=0.5)
    with pytest.raises(AggregationError):
        aggregate_objective(strata, lam=0.9)
    after = aggregate_objective(strata, lam=0.5)
    assert after == before
