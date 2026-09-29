"""Feature 262's law: the beta-six orthogonality bonus.

*System adds a beta-six orthogonality bonus measured against the committed
book, which returns the final world score* (app_spec.xml, "Objective
Scoring & CVaR Aggregation") — prd §7.1's last line
(``+ β₆ · orthogonality(committed book)``, line 324) and docs §10.3's
(line 498), the formula's only addition.  The tests here hold
:mod:`scoring._orthogonality` to the sentence's clauses, in order:

* **adds** — the term can only pay, never subtract: orthogonality is
  ``1 − |ρ|`` in ``[0, 1]``, the coefficient is non-negative, and ρ is
  clamped so no last-ulp float error flips the sign
  (:func:`test_an_orthogonal_pick_earns_the_full_bonus`,
  :func:`test_the_bonus_never_subtracts`);
* **measured against the committed book** — ``1 − |ρ|`` pays for the
  direction the book does not span *in either sign* (a perfectly
  anti-correlated pick is as redundant as a correlated one), the book
  must cover the sequestered epoch, and a constant book is refused
  rather than paid (:func:`test_a_book_spanned_pick_earns_no_bonus`,
  the book refusals);
* **which returns the final world score** — the answer is the same
  frozen :class:`~scoring.WorldScore` with :attr:`~scoring.WorldScore.score`
  moved through :meth:`~scoring.WorldScore.adjusted`, the measurement
  pinned, the identity untouched, and the panel verified to be the one
  that earned the score (:func:`test_the_measurement_is_pinned_to_the_score`,
  :func:`test_the_bonus_composes_after_another_term` — the property the
  five penalty features landing through the same seam depend on).

Exactness is the suite's own discipline, inherited from the conftest's
fixtures: the orthogonal book's correlation is a signed *zero* to the bit
(not to an epsilon), the spanned book's bonus is *nothing* to the bit,
and the partial case is checked against ``1 − 1/√2`` computed once —
every payment assertible with ``==``.  What these tests deliberately do
not reach: composition (``test_component.py`` — the bonus needs no
component, which is itself pinned here by the member's surface), and any
persistence (the
``replay_score`` row is feature 255's, and it already carries the score
and the β).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import pytest
from scoring import (
    BETA_SIX_DEFAULT,
    AggregationError,
    OrthogonalityError,
    ScoringError,
    WorldObjectiveError,
    WorldScore,
    orthogonality_bonus,
    world_objective,
)

#: The sequestered dates every local panel below is keyed by, in order.
_DAYS = (
    dt.date(2026, 3, 1),
    dt.date(2026, 3, 2),
    dt.date(2026, 3, 3),
    dt.date(2026, 3, 4),
)


def _panel(*values: float) -> dict[dt.date, float]:
    """A sequestered panel from readings in date order."""
    return dict(zip(_DAYS, values, strict=True))


def _dyadic_score() -> WorldScore:
    """A world score whose every figure is exact in binary.

    Readings (3, −1, 3, −1): mean 1, deviations (2, −2, 2, −2),
    population variance 4, so ``ir_oos`` is 1/2 *exactly* and the books
    measured against it below (collinear, anti-collinear, partial) are
    the ones whose correlations the probe of this law's arithmetic
    verified to the bit — integer readings keep every mean, deviation,
    product and ``fsum`` exact, which is why this suite reaches for
    them the moment an equality has to be a ``==`` and not an approx.
    """
    return world_objective("financial-campaign-01", "node-a", _panel(3.0, -1.0, 3.0, -1.0))


# -- the payment ----------------------------------------------------------------


def test_an_orthogonal_pick_earns_the_full_bonus(
    score: WorldScore, panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    # ρ = 0 to the bit against the conftest book, so the bonus is the
    # coefficient exactly — asserted with ==, because a bonus that came
    # out a float epsilon light would be a fixture lying about its own
    # arithmetic, not a tolerance worth honoring.
    moved = orthogonality_bonus(score, panel, book)
    assert isinstance(moved, WorldScore)
    assert moved.score == score.score + BETA_SIX_DEFAULT
    # Everything the bonus did not touch is untouched: the measurement,
    # the identity, the epoch.  The term lands beside the leading term,
    # never through it.
    assert moved.ir_oos == score.ir_oos
    assert moved.world_id == score.world_id
    assert moved.node_id == score.node_id
    assert moved.epoch_id == score.epoch_id
    # And the score that was handed over is frozen through the call.
    assert score.score == score.ir_oos


def test_a_book_spanned_pick_earns_no_bonus() -> None:
    # ρ = +1 and ρ = −1 both pay nothing — the absolute value is the
    # law's own decision, not a convention: the book *explains* a pick in
    # either sign, and an anti-correlated pick is the same redundancy
    # wearing a hedge's clothes.  Both deltas are 0.0 to the bit, so the
    # returned score equals the handed one field for field.
    scored = _dyadic_score()
    collinear = _panel(6.0, -2.0, 6.0, -2.0)  # 2× the pick's readings
    anti = _panel(-6.0, 2.0, -6.0, 2.0)  # −2× them
    for redundant in (collinear, anti):
        moved = orthogonality_bonus(scored, _panel(3.0, -1.0, 3.0, -1.0), redundant)
        assert moved.score == scored.score
        assert moved == scored


def test_partial_orthogonality_is_paid_in_proportion() -> None:
    # Deviations (4, 0, 0, −4) against (2, −2, 2, −2): half the pick's
    # direction is book, half is new, so ρ = 1/√2 and the bonus is the
    # coefficient times 1 − 1/√2 — checked to the bit against the
    # expression computed once, and to an epsilon against its decimal.
    scored = _dyadic_score()
    moved = orthogonality_bonus(
        scored, _panel(3.0, -1.0, 3.0, -1.0), _panel(4.0, 0.0, 0.0, -4.0)
    )
    expected = BETA_SIX_DEFAULT * (1.0 - 1.0 / math.sqrt(2.0))
    assert moved.score == scored.score + expected
    assert moved.score == pytest.approx(0.5 + 0.25 * (1.0 - math.sqrt(0.5)))


def test_the_bonus_scales_with_the_coefficient(
    score: WorldScore, panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    # β₆ is the caller's knob — the number replay_score persists beside
    # the score it moved — and the payment is proportional in it: double
    # the coefficient, double the bonus; zero it, decline the incentive
    # (an ablation the documents leave open, not a refusal).
    assert (
        orthogonality_bonus(score, panel, book, beta=0.5).score
        == score.score + 0.5
    )
    assert orthogonality_bonus(score, panel, book, beta=0.0) == score
    assert orthogonality_bonus(score, panel, book, beta=1.0).score == score.score + 1.0


def test_the_bonus_never_subtracts(
    score: WorldScore, panel: dict[dt.date, float]
) -> None:
    # The formula's one addition cannot counterfeit a penalty: across a
    # deterministic sweep of books — correlated, anti-correlated,
    # uncorrelated, and everything between — the moved score is never
    # below the handed one, and equality is earned exactly at full
    # span.  The clamp on ρ is what keeps a collinear pair's last-ulp
    # float error from manufacturing a negative delta here.
    sweep = []
    for step in range(-8, 9):
        book = _panel(
            3.0 + step * 0.5,
            -1.0 - step * 0.25,
            3.0 - step * 0.125,
            -1.0 + step * 0.75,
        )
        sweep.append(orthogonality_bonus(score, panel, book))
    # The sweep above is every partial overlap between the two extremes,
    # and it ends where the payment is earned exactly: the two books
    # proportional to the pick — ±3× its readings — whose correlations
    # are ±1 to the bit, so the bonus is 0.0 and the moved score equals
    # the handed one field for field.  (Proportionality has to be exact
    # for that: the sweep's own books are all partial overlaps, and a
    # coefficient of 2 leaves rho at 1 − 2⁻⁵³, which pays a hair rather
    # than nothing.)  The claim is that the formula's one addition cannot
    # counterfeit a penalty, and equality is what full span earns.
    readings = (0.1, -0.1, 0.0, 0.2)
    for scale in (3.0, -3.0):
        spanned = orthogonality_bonus(
            score, panel, _panel(*(scale * value for value in readings))
        )
        assert spanned == score
        sweep.append(spanned)
    assert all(moved.score >= score.score for moved in sweep)
    assert any(moved.score == score.score for moved in sweep)


# -- the pinning ----------------------------------------------------------------


def test_the_measurement_is_pinned_to_the_score(
    score: WorldScore, book: dict[dt.date, float]
) -> None:
    # The panel handed here must be the panel that earned the score: the
    # seam recomputes the leading term's ratio in the objective's own
    # spelling and refuses unless it reproduces ir_oos to the bit — a
    # bonus measured on data the score never saw is the hidden
    # reweighting the objective refuses to be.  The refusal names both
    # numbers, because which panel measured the other ratio is the
    # caller's fact to check.
    other_panel = _panel(0.1, -0.1, 0.0, 0.25)
    other_ratio = world_objective(score.world_id, score.node_id, other_panel).ir_oos
    assert other_ratio != score.ir_oos
    with pytest.raises(OrthogonalityError) as caught:
        orthogonality_bonus(score, other_panel, book)
    message = str(caught.value)
    assert repr(other_ratio) in message
    assert repr(score.ir_oos) in message


def test_the_bonus_composes_after_another_term(
    score: WorldScore, panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    # The five penalty features (257-261) land through the same
    # adjusted seam this one rides, so the bonus must compose onto a
    # score they have already moved: the pin still holds — ir_oos was
    # frozen through their deltas — and the payment still lands, beside
    # their subtraction, on the moved scalar.
    penalized = score.adjusted(-0.1)
    moved = orthogonality_bonus(penalized, panel, book)
    assert moved.score == penalized.score + BETA_SIX_DEFAULT
    assert moved.ir_oos == score.ir_oos
    assert moved.node_id == score.node_id


@dataclass(frozen=True)
class _NoMeasurement:
    """A carrier with the seam but not the measurement — the shape that
    proves the duck-typed read validates what it needs, not what the
    caller hoped it checked."""

    def adjusted(self, delta: float) -> _NoMeasurement:  # pragma: no cover
        return self


@dataclass(frozen=True)
class _NoSeam:
    """A carrier with the measurement but not the seam — the mirror
    shape, refused for its own missing face."""

    ir_oos: float


def test_a_carrier_without_a_measurement_is_refused(
    panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    with pytest.raises(OrthogonalityError, match="ir_oos"):
        orthogonality_bonus(_NoMeasurement(), panel, book)


def test_a_carrier_without_the_seam_is_refused(
    panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    with pytest.raises(OrthogonalityError, match="adjusted"):
        orthogonality_bonus(_NoSeam(ir_oos=0.5), panel, book)


def test_a_carrier_with_a_non_finite_measurement_is_refused(
    panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    with pytest.raises(OrthogonalityError, match="finite"):
        orthogonality_bonus(_NoSeam(ir_oos=float("nan")), panel, book)


# -- the coefficient ------------------------------------------------------------


@pytest.mark.parametrize(
    "beta", [float("nan"), float("inf"), -0.25, -1e-9, True, "0.25", None]
)
def test_a_coefficient_that_cannot_add_is_refused(
    score: WorldScore, panel: dict[dt.date, float], book: dict[dt.date, float], beta
) -> None:
    # NaN and ±inf are not coefficients; a negative one counterfeits a
    # penalty through the bonus seam (the spec's verb is *adds*); a bool
    # is an int in Python's hierarchy and not a weight; a string and a
    # None are type faults.  Every one of them is refused, and the
    # branch each lands in names its own fault.
    with pytest.raises(OrthogonalityError) as caught:
        orthogonality_bonus(score, panel, book, beta=beta)
    # Only the negative coefficient is refused on the verb's own sentence
    # — that is the branch whose message says *adds*.  A bool is refused
    # one step earlier, by the type gate (a bool is an int in Python's
    # hierarchy and not a coefficient), and NaN/±inf by the finiteness
    # gate; each names its own fault, which is the point of the split.
    if isinstance(beta, float) and beta < 0.0:
        assert "adds" in str(caught.value)


def test_the_default_coefficient_is_a_stated_parameterization() -> None:
    # Neither document sizes β₆ — the formula spells the term and moves
    # on — so the default is the member's own stated parameterization, a
    # quarter of a ratio unit at full orthogonality: visible beside a
    # leading term of order one, never large enough that being
    # uncorrelated beats being right, and dyadic so this suite's exact
    # cases stay exact.
    assert BETA_SIX_DEFAULT == 0.25


# -- the book's law -------------------------------------------------------------


def test_a_book_that_is_not_a_mapping_is_refused(
    score: WorldScore, panel: dict[dt.date, float]
) -> None:
    with pytest.raises(OrthogonalityError, match="mapping"):
        orthogonality_bonus(score, panel, [(day, 0.1) for day in _DAYS])


def test_a_book_keyed_by_a_datetime_is_refused(
    score: WorldScore, panel: dict[dt.date, float]
) -> None:
    with pytest.raises(OrthogonalityError, match="keyed by dates"):
        orthogonality_bonus(
            score,
            panel,
            # A naive datetime on purpose: the key has to be the clock-keyed
            # shape the seam refuses, not a well-formed instant.
            {dt.datetime(2026, 3, 1): 0.1, dt.date(2026, 3, 2): 0.1},  # noqa: DTZ001
        )


@pytest.mark.parametrize("reading", [float("nan"), float("inf"), True, "0.1"])
def test_a_book_reading_that_is_not_a_finite_real_is_refused(
    score: WorldScore, panel: dict[dt.date, float], reading
) -> None:
    with pytest.raises(OrthogonalityError) as caught:
        orthogonality_bonus(score, panel, {day: reading for day in _DAYS})
    assert "reading" in str(caught.value)


def test_a_book_that_misses_a_sequestered_date_is_refused(
    score: WorldScore, panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    # A hole is a hole in the resident array, not a zero return — a
    # zero is trivially uncorrelated with anything, and zero-filling
    # would fabricate the very orthogonality this term pays for.  The
    # refusal names the earliest date the book missed.
    holed = {day: value for day, value in book.items() if day != dt.date(2026, 3, 3)}
    with pytest.raises(OrthogonalityError) as caught:
        orthogonality_bonus(score, panel, holed)
    assert "2026-03-03" in str(caught.value)
    # An empty book misses the whole epoch, and the one date it can name
    # is the epoch's first.
    with pytest.raises(OrthogonalityError) as empty:
        orthogonality_bonus(score, panel, {})
    assert "2026-03-01" in str(empty.value)


def test_a_book_may_cover_more_than_the_epoch(
    score: WorldScore, panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    # The pick's priced grid defines the panel, the stance feature 83
    # takes for the evaluator's book signals: a book pinned for the
    # whole campaign horizon composes with the sequestered slice of it
    # untouched, and the dates outside the epoch are left unread — the
    # same bonus to the bit as the sliced book's.
    horizon_wide = {dt.date(2026, 2, 27): 9.5, dt.date(2026, 2, 28): -9.5, **book}
    assert horizon_wide != book
    assert orthogonality_bonus(score, panel, horizon_wide).score == (
        orthogonality_bonus(score, panel, book).score
    )


def test_a_constant_book_is_refused(
    score: WorldScore, panel: dict[dt.date, float]
) -> None:
    # The correlation against a constant series is 0/0 — undefined, not
    # zero — and paying the full bonus for it ("a constant book explains
    # nothing") would sell diversification nobody measured.  Refused,
    # naming the fact, exactly as the objective refuses a constant pick
    # panel one feature earlier.
    with pytest.raises(OrthogonalityError) as caught:
        orthogonality_bonus(score, panel, {day: 0.001 for day in _DAYS})
    assert "never varied" in str(caught.value)


@pytest.mark.parametrize(
    "pick_returns",
    [
        [(day, 0.1) for day in _DAYS],  # not a mapping
        {dt.datetime(2026, 3, 1): 0.1, dt.date(2026, 3, 2): -0.1},  # noqa: DTZ001  # clock key
        {dt.date(2026, 3, 1): 0.1},  # one date
        {day: 0.05 for day in _DAYS},  # never varied
    ],
)
def test_the_pick_panels_shape_refusals_are_feature_256s(
    score: WorldScore, book: dict[dt.date, float], pick_returns
) -> None:
    # The pick panel's law was stated once, by the objective that
    # measured the score, and this seam recomputes that number through
    # that code — so the shape refusals arrive untranslated, as
    # WorldObjectiveError, and both classes share the ScoringError base
    # a replay loop's single except catches.  A second spelling of the
    # panel's law here would be a second place the sequestration
    # boundary could drift.
    with pytest.raises(WorldObjectiveError):
        orthogonality_bonus(score, pick_returns, book)


# -- determinism, vocabulary, surface -------------------------------------------


def test_the_bonus_is_order_independent(
    score: WorldScore, panel: dict[dt.date, float], book: dict[dt.date, float]
) -> None:
    # Same panels, reversed key insertion order: the same bonus to the
    # last bit — dates are sorted before they are read and every sum is
    # an fsum, the determinism law the replay holds for the leading term
    # held here for the last one.
    reversed_panel = {day: panel[day] for day in sorted(panel, reverse=True)}
    reversed_book = {day: book[day] for day in sorted(book, reverse=True)}
    assert list(reversed_panel) != list(panel)
    first = orthogonality_bonus(score, panel, book)
    second = orthogonality_bonus(score, reversed_panel, reversed_book)
    assert second.score == first.score


def test_the_error_is_a_sibling_of_the_objectives() -> None:
    # 256 refuses an ask that cannot be scored; 262 refuses one whose
    # bonus cannot be measured; the repairs differ (sequestration
    # against the resident array), so the classes stay distinguishable
    # behind separate excepts — the same reasoning that keeps
    # RegimeIndexError beside AggregationError.
    assert issubclass(OrthogonalityError, ScoringError)
    assert not issubclass(OrthogonalityError, WorldObjectiveError)
    assert not issubclass(OrthogonalityError, AggregationError)
    assert not issubclass(WorldObjectiveError, OrthogonalityError)
    assert not issubclass(AggregationError, OrthogonalityError)


def test_the_term_is_pure_arithmetic_not_a_component() -> None:
    # Like the blend and the index, the bonus owns no deployment state,
    # so it adds no component beside the objective and no seat beside
    # the member's: the surface it joins is the member's namespace, and
    # the composed "scoring" component stays the per-world objective.
    import scoring

    assert "orthogonality_bonus" in scoring.__all__
    assert "BETA_SIX_DEFAULT" in scoring.__all__
    assert "OrthogonalityError" in scoring.__all__
    assert scoring.COMPONENT_NAME == "scoring"
