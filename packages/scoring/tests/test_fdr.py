"""Feature 267's law, first half — the reweighting itself: prd §4.1.3's
formula over feature 266's pair, at the deployment base rate, answered
as one bare float.

*System persists FDR_deploy per campaign, computed by reweighting
sensitivity and specificity to a deployment base rate of 0.9*
(app_spec.xml, "Objective Scoring & CVaR Aggregation").  The store — the
*persists per campaign* half of the sentence — is its own suite
(``test_fdr_store.py``); this one pins the arithmetic the store lands:

* **the formula** — ``π₀(1 − specificity) / [π₀(1 − specificity) +
  (1 − π₀)·sensitivity]``, spelled at :data:`scoring.DEPLOYMENT_BASE_RATE`
  and no other rate, checkable to the bit on the fixture campaign
  (every figure hand-computed; the interesting ones dyadic);
* **the reweighting reweights** — the same pair projects to a different
  figure than the campaign's raw rate, in the direction §4.1.3 warns
  about: deploying into a 90%-null reality, a 50/50 pair projects to
  0.9, not 0.5;
* **the carrier is duck-typed** — feature 266's own value and a stand-in
  exposing exactly the two attributes both reweight, because the loader
  imports members under synthetic names and the seam validates what it
  reads;
* **the refusals** — the singular figure (the raw in-campaign rate the
  likeliest wearer of the shape), the unreadable pair, the figure that
  is not a finite real in ``[0, 1]``, and the one corner refused: the
  campaign that committed to nothing, whose projection is 0/0 at every
  base rate.

The fixtures come from the suite's conftest: the campaign's measured
pair (the four-pick campaign that committed to everything — sensitivity
1.0, specificity 0.0, figure 0.9 exactly) and the stand-in pair carrier.
"""

from __future__ import annotations

import inspect

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local
    StandInFigures,
)
from scoring import (
    DEPLOYMENT_BASE_RATE,
    CalibrationFigures,
    FdrDeployError,
    ScoringError,
    fdr_deploy,
)

# -- The formula -----------------------------------------------------------------


def test_the_figure_campaign_reweights_to_nine_tenths_exactly(
    figures: CalibrationFigures,
) -> None:
    # The fixture campaign — two reals found (sensitivity 1.0), two nulls
    # committed (specificity 0.0) — is the campaign that declared
    # everything: nine parts null, one part real, every declaration
    # made, nine of ten false.  The arithmetic is exact in binary
    # (0.9·1.0 / (0.9·1.0 + 0.1·1.0), denominator exactly 1.0), so the
    # figure is checkable with == and the answer is one bare float.
    answer = fdr_deploy(figures)
    assert type(answer) is float
    assert answer == 0.9


def test_the_formula_is_prd_4_1_3_to_the_bit() -> None:
    # The exact spelling, evaluation order included: three products, one
    # sum, one division, at the deployment base rate.  Recomputed here
    # from the constant (never restated as a literal 0.9), the pair
    # (0.8, 0.8) — whose figure is neither dyadic nor an endpoint — must
    # answer to the bit, which pins the formula's shape and not merely
    # its value.
    pair = StandInFigures(sensitivity=0.8, specificity=0.8)
    pi0 = DEPLOYMENT_BASE_RATE
    hand = pi0 * (1.0 - 0.8) / (pi0 * (1.0 - 0.8) + (1.0 - pi0) * 0.8)
    assert fdr_deploy(pair) == hand


def test_the_base_rate_is_spelled_once_at_nine_tenths() -> None:
    # prd §4.1.3 fixes π₀ ("with π₀ ≈ 0.9", line 148), §11's primary
    # target carries the qualifier ("< 25% at π₀ = 0.9", line 536) and
    # §12's M3 exit reads the figure at it (line 598) — one number, one
    # spelling, and a float so the arithmetic and the row's stored
    # base_rate column agree to the bit.
    assert DEPLOYMENT_BASE_RATE == 0.9
    assert type(DEPLOYMENT_BASE_RATE) is float


def test_the_verb_takes_the_pair_and_never_a_base_rate() -> None:
    # A constant, not a parameter: the projection this verb answers is
    # *the* deployment projection — the number the dashboard and the M3
    # gate read — and a caller able to pick a π₀ would be able to pick
    # the figure the target is judged on.  The signature is the whole
    # law: one parameter, the pair.
    parameters = inspect.signature(fdr_deploy).parameters
    assert list(parameters) == ["figures"]


def test_deterministic_and_pure_the_same_pair_answers_the_same_figure() -> None:
    # No clock, no store, no environment inside the verb: the same pair
    # answers the same figure to the bit, twice — the property that
    # makes a re-run of a campaign's close-out the same measurement
    # written twice, which is the law the store's upsert leans on.
    pair = StandInFigures(sensitivity=0.5, specificity=0.75)
    assert fdr_deploy(pair) == fdr_deploy(pair)


# -- The reweighting reweights -----------------------------------------------------


def test_a_fifty_fifty_pair_projects_to_nine_tenths_not_one_half() -> None:
    # The feature's own point, in one figure: a campaign planted at the
    # φ floor whose pair is (0.5, 0.5) has a raw in-campaign rate of
    # 0.5, and the same pair projects to 0.9 at π₀ = 0.9 — exact in
    # binary (0.9·0.5 / (0.9·0.5 + 0.1·0.5), denominator exactly 0.5).
    # §4.1.3's "systematically under-skeptical policy" is the one that
    # read the 0.5 and deployed into the 92%-null reality.
    assert fdr_deploy(StandInFigures(sensitivity=0.5, specificity=0.5)) == 0.9


def test_the_projection_moves_toward_the_deployment_reality() -> None:
    # A pair better than the raw rate it replaces: sensitivity 0.9,
    # specificity 0.9 — a raw in-campaign rate of ~0.1 (one null
    # committed per ten declarations, at a 50/50 plant) projects to 0.5
    # at π₀ = 0.9, and one of (0.8, 0.8) projects to 9/13 ≈ 0.692.  The
    # direction is §4.1.3's whole argument: figures measured where there
    # is power for both, priced where there is not.
    assert fdr_deploy(
        StandInFigures(sensitivity=0.9, specificity=0.9)
    ) == pytest.approx(0.5)
    assert fdr_deploy(
        StandInFigures(sensitivity=0.8, specificity=0.8)
    ) == pytest.approx(9 / 13)


def test_both_endpoints_are_measurements_and_both_are_honoured() -> None:
    # 0.0 is the projection of a campaign that never committed a null
    # (specificity 1.0, every real found): no false alarms, no false
    # discoveries.  1.0 is the projection of one that finds no reals and
    # declares anyway (sensitivity 0.0, specificity below one): every
    # declaration false, the honest reading of a policy that only ever
    # commits to noise.  Neither is clamped and neither is refused —
    # both are exact in binary.
    assert fdr_deploy(StandInFigures(sensitivity=1.0, specificity=1.0)) == 0.0
    assert fdr_deploy(StandInFigures(sensitivity=0.0, specificity=0.5)) == 1.0


# -- The carrier -------------------------------------------------------------------


def test_feature_266s_own_value_is_the_intended_carrier(
    figures: CalibrationFigures,
) -> None:
    # The measurement this projection is priced on is the pair the
    # scorer process's calibration verb answers, handed over already
    # computed — the fixture is that value, and it reweights untouched.
    assert fdr_deploy(CalibrationFigures(sensitivity=1.0, specificity=0.0)) == 0.9
    assert fdr_deploy(figures) == 0.9


def test_the_pair_is_read_duck_typed_not_by_type() -> None:
    # The loader imports members under synthetic names and re-executes
    # them, so the pair a process composed may be a second class object
    # — the seam validates what it reads, never the type it was handed.
    # The conftest stand-in exposes exactly the two attributes and
    # nothing else: reweighting it is the proof.
    stand_in = StandInFigures(sensitivity=1.0, specificity=0.0)
    assert vars(stand_in).keys() == {"sensitivity", "specificity"}
    assert fdr_deploy(stand_in) == 0.9


# -- The refusals ------------------------------------------------------------------


def test_a_bare_number_is_refused_and_the_raw_rate_is_named() -> None:
    # The likeliest wrong carrier at this seam is singular: the raw
    # in-campaign rate, the figure prd §4.1.3 bars from the dashboard —
    # an artifact of the campaign's φ, and no arithmetic on one number
    # recovers the two the formula needs.  Refused whatever its value,
    # with the substitution named.
    with pytest.raises(FdrDeployError) as narrowed:
        fdr_deploy(0.5)  # type: ignore[arg-type]
    assert "raw in-campaign rate" in str(narrowed.value)
    for singular in (0, 1, 0.9, True, None):
        with pytest.raises(FdrDeployError):
            fdr_deploy(singular)  # type: ignore[arg-type]


def test_a_carrier_exposing_no_pair_is_refused() -> None:
    # The pair is the measurement; a carrier that does not answer it
    # names no measurement to reweight.  The refusal reports what it
    # read on each figure, because the repair (the caller's wiring)
    # differs from a figure that was out of bound.
    class Empty:
        pass

    with pytest.raises(FdrDeployError) as narrowed:
        fdr_deploy(Empty())
    assert "sensitivity" in str(narrowed.value)
    assert "specificity" in str(narrowed.value)
    with pytest.raises(FdrDeployError):
        fdr_deploy(object())


def test_a_figure_that_is_not_a_finite_real_in_band_is_refused() -> None:
    # A duck-typed carrier owes the proof a constructor no longer stands
    # behind: each figure is narrowed exactly as feature 266's
    # constructor narrows it — a real (bool refused before it), finite,
    # in [0, 1] — and the refusal names the field, because the likeliest
    # thing wearing either name out of bound is a *count* of nodes,
    # which clamped to an endpoint would reweight a calibration nobody
    # measured.
    for field in ("sensitivity", "specificity"):
        for bad in (1.5, -0.25, float("nan"), float("inf"), "0.5", 47):
            carrier = StandInFigures(sensitivity=0.5, specificity=0.5)
            object.__setattr__(carrier, field, bad)
            with pytest.raises(FdrDeployError) as narrowed:
                fdr_deploy(carrier)
            assert field in str(narrowed.value)


def test_a_bool_wearing_a_figures_name_is_refused() -> None:
    # True is an int is a Real, and 1.0 would be in band — refused
    # before the narrowing all the same, because a boolean is an answer
    # to a different question ("was it found?") and not a fraction of a
    # planted class.
    carrier = StandInFigures(sensitivity=0.5, specificity=0.5)  # type: ignore[arg-type]
    object.__setattr__(carrier, "sensitivity", True)
    with pytest.raises(FdrDeployError) as narrowed:
        fdr_deploy(carrier)
    assert "sensitivity" in str(narrowed.value)


def test_the_campaign_that_committed_to_nothing_is_refused() -> None:
    # The one corner refused: sensitivity 0.0 with specificity 1.0 is
    # feature 266's honest answer for a campaign that committed to
    # nothing (any commitment is to a real, moving sensitivity, or to a
    # null, moving specificity), and its projection is 0/0 at every
    # base rate.  No fraction of declarations is defined for a campaign
    # that made none, and reading the corner as 0.0 would answer a
    # flawless policy for one that never ran — unknown is not zero, the
    # stance this family takes toward every empty denominator.
    with pytest.raises(FdrDeployError) as narrowed:
        fdr_deploy(StandInFigures(sensitivity=0.0, specificity=1.0))
    assert "committed to nothing" in str(narrowed.value)
    # 266's own value spells the same corner, and the verb holds its
    # refusal for the real carrier as for the stand-in.
    with pytest.raises(FdrDeployError):
        fdr_deploy(CalibrationFigures(sensitivity=0.0, specificity=1.0))
    # No neighbour of the corner is refused: either side of it is a
    # measurement.
    assert fdr_deploy(StandInFigures(sensitivity=0.0, specificity=0.999)) == 1.0
    assert fdr_deploy(StandInFigures(sensitivity=0.001, specificity=1.0)) == 0.0


def test_every_refusal_is_catchable_through_the_member_base() -> None:
    # One base class, so a caller — the close-out, an operator script —
    # catches every refusal of the objective's arithmetic with a single
    # except, and the figure that cannot be reweighted is one of them.
    assert issubclass(FdrDeployError, ScoringError)
    with pytest.raises(ScoringError):
        fdr_deploy(0.5)  # type: ignore[arg-type]
