"""Feature 127 — the seed re-run, against the properties it pins.

app_spec.xml: *"System re-runs a candidate under a different seed, which
rejects the node when degradation exceeds the configured threshold."*  The
tests are organised around the decisions the module docstring pins — the
degradation's sign and scale, the configured threshold and where √2 comes from,
the union of the three rejection causes, the axis vocabulary, and the record's
separation from feature 125's — because those are the claims a reader has to
take on faith otherwise.

Two of them are load-bearing above all, and both are about *not* being feature
125 restated:

* :func:`test_a_planted_leak_degrades_by_nothing` — a planted leak's surviving
  Sharpe is **identical** across seeds, because a whole-sample statistic does
  not depend on the derangement.  This is the test that pins the two probes as
  different tests: if a re-run caught leaks, it would be feature 125 wearing a
  second seed, and the corpus feature 133 maintains would be asserting the same
  sentence twice.
* :func:`test_a_clean_candidate_is_the_null_the_probe_must_pass` — the probe's
  own default bar is conservative against the null, measured over many draws
  rather than assumed, because the act it licenses is irreversible.

The leak fixtures come from :mod:`_panels`' ``lookahead_panel`` — the same
canonical full-sample-mean leak feature 125's own suite plants — so the claim
"a leak does not degrade" is checked against the leak the member already knows
how to build rather than against a second one invented here.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math

import pytest
from _panels import gaussian_panel, lookahead_panel, monday
from tripwires import (
    DEFAULT_DEGRADATION_THRESHOLD,
    DEFAULT_RERUN_SEED,
    DEFAULT_SHUFFLE_LEVEL,
    DEFAULT_SHUFFLE_SEED,
    PERTURBATION_AXES,
    PERTURBATION_STABILITY_NAME,
    SEED_AXIS,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    SeedRerunVerdict,
    TripwirePanelError,
    normal_quantile,
    planted_signals,
    run_seed_rerun,
    run_time_shuffle_tripwire,
    seed_rerun_degradation,
    time_shuffle_threshold,
)


def _clean_candidate(
    grid: list[dt.date], symbols: list[str], *, seed: int = 3
) -> tuple[dict, dict]:
    """A candidate with no relationship to its targets — scores, targets.

    The scores and the targets are drawn from different streams, so the two
    panels are independent by construction: this is the null the re-run is
    supposed to pass, and therefore the candidate whose *degradation* is pure
    sampler noise.
    """
    targets = {1: gaussian_panel(grid, symbols, seed=seed + 1)}
    scores = gaussian_panel(grid, symbols, seed=seed + 2)
    return scores, targets


def _leaking_candidate(
    grid: list[dt.date], symbols: list[str]
) -> tuple[dict, dict]:
    """The canonical planted leak — a full-sample symbol mean, as scores."""
    targets = {1: gaussian_panel(grid, symbols, seed=11)}
    return lookahead_panel(targets, horizon=1), targets


# -- The degradation is one quantity, with one sign convention -----------------


def test_the_degradation_is_the_magnitude_drop_in_threshold_units() -> None:
    # The arithmetic, stated once and checked against a hand value: a drop of
    # 0.30 in surviving Sharpe measured against a bar of 0.15 is two bars.
    assert seed_rerun_degradation(0.40, 0.10, threshold=0.15) == pytest.approx(
        (0.40 - 0.10) / 0.15
    )


def test_a_sign_reversal_is_maximal_degradation_not_none() -> None:
    # Magnitudes, not signs. A candidate at +0.30 whose re-run lands at −0.30
    # has produced the *least* reproducible outcome available, and a signed
    # difference would call it 0.60 − 0.60 = a perfectly stable zero. This is
    # why the probe reads |surviving Sharpe| on both sides.
    assert seed_rerun_degradation(0.30, -0.30, threshold=0.15) == pytest.approx(0.0)
    assert seed_rerun_degradation(0.30, -0.15, threshold=0.15) == pytest.approx(1.0)


def test_a_better_rerun_is_a_negative_degradation() -> None:
    # The sign convention, pinned from the other side: the re-run's surviving
    # Sharpe grew, so nothing degraded.
    assert seed_rerun_degradation(0.10, 0.40, threshold=0.15) < 0.0


def test_the_degradation_is_scale_free_across_grids() -> None:
    # Standardizing by the reference run's own threshold is what makes the
    # figure comparable between a 60-date probe and a 480-date one: the same
    # *relative* drop reports the same number however wide the grid.
    for dates in (60, 120, 480):
        bar = time_shuffle_threshold(dates, level=DEFAULT_SHUFFLE_LEVEL)
        assert seed_rerun_degradation(2 * bar, bar, threshold=bar) == pytest.approx(
            1.0
        )


def test_a_threshold_that_is_not_a_positive_number_is_refused() -> None:
    # A zero bar names an infinite degradation and a negative one inverts the
    # comparison; both are refused by name rather than divided by.
    for bad in (0.0, -0.15):
        with pytest.raises(TripwirePanelError, match="threshold"):
            seed_rerun_degradation(0.4, 0.1, threshold=bad)
    for not_a_number in (True, None, "0.15"):
        with pytest.raises(TripwirePanelError, match="not a number"):
            seed_rerun_degradation(0.4, 0.1, threshold=not_a_number)


def test_a_non_finite_statistic_is_refused_by_name() -> None:
    # The probe's own arithmetic refuses a NaN or ±inf before it reaches this
    # comparison, so one arriving here came from somewhere else — and it is
    # refused rather than propagated into a stability figure.
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(TripwirePanelError, match="finite"):
            seed_rerun_degradation(bad, 0.1, threshold=0.15)


# -- A leak does not degrade: the two probes are different tests ---------------


def test_a_planted_leak_degrades_by_nothing(grid: list[dt.date], symbols: list[str]) -> None:
    # The test that tells this feature apart from feature 125. A whole-sample
    # statistic is carried in every cross-section regardless of the date, so
    # re-dating the cross-sections (what a different seed does) cannot disturb
    # it: the two runs agree exactly. A re-run therefore does *not* catch
    # leakage — 125 and 126 do — and this is the evidence rather than the
    # assertion.
    scores, targets = _leaking_candidate(grid, symbols)
    reference = run_time_shuffle_tripwire(scores, targets, node_id="node-1")
    rerun = run_time_shuffle_tripwire(
        scores, targets, node_id="node-1", seed=DEFAULT_RERUN_SEED
    )
    assert reference.surviving_sharpe == rerun.surviving_sharpe
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    assert verdict.degradation == 0.0
    assert verdict.degradation_rejected is False


def test_every_corpus_leak_degrades_by_nothing() -> None:
    # The same claim over feature 133's whole maintained corpus, including the
    # sign-flipped and t-statistic kinds: zero degradation for all of them, so
    # "a leak does not degrade" is a property of planted leaks rather than of
    # the one this suite happened to build.
    for signal in planted_signals():
        verdict = run_seed_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        assert verdict.degradation == 0.0, signal.leak_kind


def test_a_leak_rejected_by_the_rerun_is_still_a_rejection(grid: list[dt.date], symbols: list[str]) -> None:
    # A leak is caught by feature 125's own comparison, which both runs make,
    # so the re-run's second cause fires and the union rejects. What the
    # verdict must not do is report the *configured threshold* as the reason.
    scores, targets = _leaking_candidate(grid, symbols)
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    assert verdict.rerun_rejected is True
    assert verdict.degradation_rejected is False
    assert verdict.rejected is True
    assert verdict.outcome == "tripwire_fail"


# -- The null, and the configured threshold's conservatism ---------------------


def test_a_clean_candidate_is_the_null_the_probe_must_pass(grid: list[dt.date], symbols: list[str]) -> None:
    # The other half of the discrimination: an independent candidate's
    # surviving Sharpe is noise, so it moves between seeds — and the module's
    # own default bar is wide enough that a clean candidate clears it. The
    # margin is asserted rather than the bare fact, so a future change that
    # narrowed the default into the noise band fails here.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    assert verdict.degradation < DEFAULT_DEGRADATION_THRESHOLD
    assert verdict.degradation_rejected is False
    assert verdict.rerun_rejected is False
    assert verdict.rejected is False
    assert verdict.outcome == "ok"


def test_the_default_threshold_is_the_derived_folded_normal_bar() -> None:
    # The default is *derived* from feature 125's own arithmetic, not tuned:
    # under the null the standardized surviving Sharpe is |Z|/z, whose variance
    # is 1 − 2/π (a *folded* normal — not 1), and the standardizing quantile is
    # the *two-sided* one. So the one-sided level-level bar over the difference
    # of two draws is Φ⁻¹(1 − level)·√(2(1 − 2/π))/z.
    #
    # It is pinned here against a Monte Carlo of the closed form *and* against
    # the constant's own history: the naive √2 shortcut (which assumes
    # Var(|Z|)=1 and drops the two-sided z) is asserted to be *wrong*, so a
    # future edit back to it fails rather than passing as "close enough".
    level = DEFAULT_SHUFFLE_LEVEL
    two_sided_z = normal_quantile(1.0 - level / 2.0)
    expected = (
        normal_quantile(1.0 - level) * math.sqrt(2.0 * (1.0 - 2.0 / math.pi))
        / two_sided_z
    )
    assert DEFAULT_DEGRADATION_THRESHOLD == pytest.approx(expected)
    assert DEFAULT_DEGRADATION_THRESHOLD == pytest.approx(0.7699, abs=1e-4)
    assert DEFAULT_DEGRADATION_THRESHOLD < math.sqrt(2.0) * 0.6

    # ...and the derivation is checked against the distribution it claims, with
    # a fixed seed: |Z|/z of two independent draws, sampled directly. This is
    # what would have caught the √2 shortcut.
    import random

    rng = random.Random(DEFAULT_RERUN_SEED)
    paired = [abs(rng.gauss(0.0, 1.0)) for _ in range(400_000)]
    observed = [abs(rng.gauss(0.0, 1.0)) for _ in range(400_000)]
    sd = math.sqrt(
        math.fsum(((a - b) / two_sided_z) ** 2 for a, b in zip(observed, paired))
        / len(observed)
    )
    # The bar sits at Φ⁻¹(1 − level) standard deviations above zero.
    assert DEFAULT_DEGRADATION_THRESHOLD / sd == pytest.approx(
        normal_quantile(1.0 - level), rel=0.02
    )


def test_the_threshold_moves_with_the_level() -> None:
    # Unlike the √2 shortcut, the derived bar is *not* level-free: Φ⁻¹(1 − level)
    # and the two-sided z do not cancel. That is the honest behaviour — a level
    # is a false-alarm rate, and a bar that did not move with it would no longer
    # be one — so a deployment tightening the level gets a tighter bar.
    def bar(level: float) -> float:
        return (
            normal_quantile(1.0 - level)
            * math.sqrt(2.0 * (1.0 - 2.0 / math.pi))
            / normal_quantile(1.0 - level / 2.0)
        )

    assert bar(0.001) > bar(0.01) > bar(0.05)


def test_the_configured_threshold_is_a_parameter_that_actually_moves_the_bar(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # "The configured threshold" is a parameter, not a constant: the same
    # candidate and the same two seeds, judged against a bar tight enough that
    # the observed degradation exceeds it. This is the spec's own sentence
    # firing — and it needs a candidate whose surviving Sharpe moved, which a
    # clean one's does.
    scores, targets = _clean_candidate(grid, symbols)
    observed = run_seed_rerun(scores, targets, node_id="node-1").degradation
    assert observed > 0.0, "the fixture must degrade for this test to mean anything"
    tightened = run_seed_rerun(
        scores, targets, node_id="node-1", threshold=observed / 2.0
    )
    assert tightened.rejected is True
    assert tightened.degradation_rejected is True
    assert tightened.outcome == "tripwire_fail"


def test_the_threshold_is_recorded_so_the_decision_can_be_re_derived(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The configured bar travels on the record: a reader recomputes the cause
    # from the degradation and the threshold the verdict carries, rather than
    # from a constant they have to guess the deployment used.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_seed_rerun(scores, targets, node_id="node-1", threshold=0.25)
    assert verdict.degradation_threshold == 0.25
    assert verdict.degradation_rejected == (
        verdict.degradation > verdict.degradation_threshold
    )


# -- The three causes, and the decision that unions them ----------------------


def test_the_rejection_is_the_disjunction_of_its_three_causes(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # `rejected` has exactly one meaning — a run states a failure — and it is
    # re-derivable as the disjunction of the three named causes. Without this
    # a verdict could carry a bit nothing produced.
    for scores, targets in (
        _clean_candidate(grid, symbols),
        _leaking_candidate(grid, symbols),
    ):
        verdict = run_seed_rerun(scores, targets, node_id="node-1")
        assert verdict.rejected is (
            verdict.degradation_rejected
            or verdict.reference_rejected
            or verdict.rerun_rejected
        )


def test_a_candidate_the_probe_itself_rejected_never_comes_back_clean(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The cause that is easiest to forget, and the one this feature was caught
    # missing: the *reference* run — feature 125's probe, on its own terms —
    # can reject while the re-run under the second seed finds nothing and the
    # degradation sits below the bar. The re-run's job is to look again, not to
    # overturn: a node the probe condemned must not be laundered into a pass
    # merely because a second draw was kinder. The reference verdict is quoted
    # in the record for exactly this reason.
    reference = run_time_shuffle_tripwire(
        *_leaking_candidate(grid, symbols), node_id="node-1"
    )
    assert reference.rejected is True, "the fixture must leak for this to test the cause"
    verdict = run_seed_rerun(*_leaking_candidate(grid, symbols), node_id="node-1")
    assert verdict.reference_rejected is True
    assert verdict.outcome == "tripwire_fail"
    assert verdict.rejected is True
    # ...and the cause is named rather than inferred: a reader can tell this
    # rejection apart from one the degradation produced.
    assert verdict.reference_sharpe == reference.surviving_sharpe


def test_a_degradation_rejection_alone_is_a_failure(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The spec's cause by itself: the candidate cleared the probe at the
    # reference seed (so the re-run finds nothing either) but its surviving
    # Sharpe collapsed under the second draw. A record whose rejection came
    # from this cause must not also claim the probe found leakage.
    scores, targets = _clean_candidate(grid, symbols)
    observed = run_seed_rerun(scores, targets, node_id="node-1").degradation
    assert observed > 0.0, "the fixture must degrade for this to test the cause"
    verdict = run_seed_rerun(
        scores, targets, node_id="node-1", threshold=observed / 2.0
    )
    assert verdict.degradation_rejected is True
    assert verdict.rerun_rejected is False
    assert verdict.outcome == "tripwire_fail"


def test_a_degradation_exactly_at_the_bar_is_not_a_rejection(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The spec's verb is *exceeds*, and the boundary is where a bar's meaning
    # actually lives: a candidate degrading by precisely the configured amount
    # has not exceeded it. Pinned rather than left to the ``>``/``>=`` reflex,
    # because the whole point of a *configured* threshold is that an operator
    # can size it to a candidate they mean to keep.
    scores, targets = _clean_candidate(grid, symbols)
    observed = run_seed_rerun(scores, targets, node_id="node-1").degradation
    exact = run_seed_rerun(scores, targets, node_id="node-1", threshold=observed)
    assert exact.degradation == observed
    assert exact.degradation_rejected is False
    assert exact.outcome == "ok"
    # ...and the rejection returns the moment the bar is set even an ulp under
    # the degradation, so the boundary is the comparison and not rounding.
    below = run_seed_rerun(
        scores, targets, node_id="node-1", threshold=observed * (1.0 - 1e-12)
    )
    assert below.degradation_rejected is True
    assert below.outcome == "tripwire_fail"


# -- A re-run under the seed it re-runs is refused ----------------------------


def test_the_same_seed_on_both_runs_is_refused(grid: list[dt.date], symbols: list[str]) -> None:
    # The structural zero, refused by name rather than returned. A re-run under
    # the seed it re-runs draws the same derangement, so its degradation is
    # exactly zero and this feature would report every candidate it was handed
    # — including ones it never perturbed — as perfectly stable.
    scores, targets = _clean_candidate(grid, symbols)
    with pytest.raises(TripwirePanelError, match="two different seeds"):
        run_seed_rerun(scores, targets, node_id="node-1", seed=7, rerun_seed=7)


def test_a_non_integer_rerun_seed_is_refused(grid: list[dt.date], symbols: list[str]) -> None:
    # The second draw is a pure function of the sorted dates and the seed, and
    # a non-integer seed names no stream to draw from. `True` is refused
    # explicitly: it *is* an int in Python, and would silently draw seed 1.
    scores, targets = _clean_candidate(grid, symbols)
    for bad in (True, "1", None, 1.0):
        with pytest.raises(TripwirePanelError, match="integer"):
            run_seed_rerun(scores, targets, node_id="node-1", rerun_seed=bad)


def test_the_default_rerun_seed_is_not_the_reference_seed_plus_one() -> None:
    # The second draw has to be an *independent* one. `DEFAULT_SHUFFLE_SEED + 1`
    # would draw from a neighbouring stream nothing has verified; the corpus and
    # the probe's own leak check exercise the pinned pair instead.
    assert DEFAULT_RERUN_SEED != DEFAULT_SHUFFLE_SEED
    assert DEFAULT_RERUN_SEED != DEFAULT_SHUFFLE_SEED + 1


# -- The refusals the probe makes are the probe's, propagated once -------------


def test_a_panel_the_probe_cannot_measure_refuses_once(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A bundle sharing no horizon with the scores is the probe's refusal, and
    # the re-run propagates it from the *reference* run rather than stating a
    # second cause: one failure, one message.
    scores, _ = _clean_candidate(grid, symbols)
    with pytest.raises(TripwirePanelError, match="shares no horizon"):
        run_seed_rerun(scores, {2: {}}, node_id="node-1")


def test_a_grid_too_short_to_shuffle_refuses(grid: list[dt.date], symbols: list[str]) -> None:
    # One measurable date is the identity, and there is no probe to state — let
    # alone a second draw of it.
    narrow = monday(1)
    scores = {narrow[0]: {name: 0.1 for name in symbols}}
    targets = {1: {narrow[0]: {name: 0.2 for name in symbols}}}
    with pytest.raises(TripwirePanelError, match="measurable rebalance date"):
        run_seed_rerun(scores, targets, node_id="node-1")


def test_a_node_that_cannot_be_named_is_refused(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    for bad in ("", "   ", None):
        with pytest.raises(TripwirePanelError, match="name the node"):
            run_seed_rerun(scores, targets, node_id=bad)


# -- Determinism --------------------------------------------------------------


def test_the_same_re_run_twice_is_bit_identical(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A stability figure is only comparable between campaigns if taking it
    # twice returns the same number: the record is a pure function of the
    # panels, the node and the three knobs, and carries no wall-clock field at
    # all — a timestamp would make two runs of one re-run differ.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_seed_rerun(scores, targets, node_id="node-1")
    second = run_seed_rerun(scores, targets, node_id="node-1")
    assert first == second
    assert hash(first) == hash(second)
    assert not hasattr(first, "created_at")


def test_the_re_run_rebuilds_both_runs_terms_exactly(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The audit path is the probe path: both statistics on the record are what
    # feature 125's probe returns under the two seeds the record carries, and
    # the bar the degradation is measured in is the reference run's own
    # threshold — read off rather than recomputed, so it cannot be a third
    # spelling of it.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_seed_rerun(scores, targets, node_id="node-1", seed=5, rerun_seed=19)
    reference = run_time_shuffle_tripwire(scores, targets, node_id="node-1", seed=5)
    rerun = run_time_shuffle_tripwire(scores, targets, node_id="node-1", seed=19)
    assert verdict.reference_sharpe == reference.surviving_sharpe
    assert verdict.rerun_sharpe == rerun.surviving_sharpe
    assert verdict.reference_threshold == reference.threshold
    assert verdict.dates == reference.dates
    assert verdict.horizon == reference.horizon
    assert verdict.level == reference.level


# -- The record's vocabulary, and its separation from feature 125's -----------


def test_the_record_names_perturbation_stability_not_time_shuffle() -> None:
    # §6.1 step 10 names three probes, and both runs here are time-shuffle
    # probes — the probe this feature adds is the one that moves a knob the
    # time-shuffle probe holds fixed. Naming the record after the underlying
    # statistic would make a re-run indistinguishable from the run it re-runs.
    assert PERTURBATION_STABILITY_NAME == "perturbation-stability"
    assert PERTURBATION_STABILITY_NAME != TIME_SHUFFLE_NAME
    assert SEED_AXIS == "seed"
    assert PERTURBATION_AXES[0] == "seed"


def test_the_axis_vocabulary_is_closed_and_in_the_specs_order() -> None:
    # The family's axes, in §C6's declaration order (seed, start offset,
    # universe subsample) with feature 130's lookback jitter last. Closed for
    # the same reason the horizons and the leak kinds are: an axis the spec
    # does not name is a perturbation nobody calibrated a bar against.
    assert PERTURBATION_AXES == (
        "seed",
        "window-offset",
        "universe-subsample",
        "lookback-jitter",
    )


def test_the_verdict_carries_the_axis_not_just_the_probe() -> None:
    # What was jittered is a field, so features 128 through 130 can add their
    # axes to one record shape rather than four verdict classes.
    scores, targets = _clean_candidate(monday(40), ["A", "B", "C"])
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    assert verdict.axis == "seed"
    assert verdict.tripwire == PERTURBATION_STABILITY_NAME


def test_the_outcome_word_is_the_decision_s_translation(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # §8's two-word slice, the same one feature 125 states: a probe either
    # states no failure or it is the reason the trial failed.
    for scores, targets in (
        _clean_candidate(grid, symbols),
        _leaking_candidate(grid, symbols),
    ):
        verdict = run_seed_rerun(scores, targets, node_id="node-1")
        assert verdict.outcome in TRIPWIRE_OUTCOMES
        assert verdict.outcome == ("tripwire_fail" if verdict.rejected else "ok")


def test_the_verdict_is_frozen_and_compares_by_value(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.degradation = 0.0
    assert verdict == run_seed_rerun(scores, targets, node_id="node-1")


def test_improvement_is_the_degradation_s_negation(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The sign convention lives in one place: a negative degradation means the
    # re-run was better, and a reader asking that question should not have to
    # know it.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    assert verdict.improvement == -verdict.degradation


def test_the_record_does_not_look_like_a_time_shuffle_verdict() -> None:
    # A seam, not a style. Feature 131 validates a verdict *structurally*, by
    # the ten field names a poisoning reads, because the factory's scan gives
    # one source file two class objects and isinstance cannot hold across them.
    # A record shaped like a time-shuffle verdict would pass that check and
    # then be judged on |surviving_sharpe| > threshold — feature 125's
    # comparison over feature 125's statistic — which for a node this feature
    # rejects *because the degradation exceeded its bar* is false, so the store
    # would refuse a poisoning on a mismatched reason.
    #
    # The fields that must differ are the *statistic-bearing* ones: `node_id`
    # is legitimately shared (both features reject a node by name), and so is
    # the §8 vocabulary. What cannot be shared is the number the store would
    # re-derive the decision from.
    from tripwires.poison import _VERDICT_FIELDS

    scores, targets = _clean_candidate(monday(40), ["A", "B", "C"])
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    carried = {field.name for field in verdict.__dataclass_fields__.values()}
    for field in ("surviving_sharpe", "threshold"):
        assert field not in carried, field
        assert field not in _VERDICT_FIELDS or not hasattr(verdict, field), field
    # ...and the record does carry what it *is*: two statistics, the bar
    # between them, and the configured threshold the degradation was judged on.
    assert {"reference_sharpe", "rerun_sharpe", "degradation_threshold"} <= carried


# -- The record's own invariants ----------------------------------------------


def _terms(**overrides) -> dict:
    """A valid verdict's terms, with the named ones overridden.

    Built by running the feature once and reading its own fields back, so a
    test that forges a record is forging it from the real terms rather than
    from a hand-copied shape that could drift.
    """
    scores, targets = _clean_candidate(monday(40), ["A", "B", "C"])
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    terms = {
        field.name: getattr(verdict, field.name)
        for field in verdict.__dataclass_fields__.values()
    }
    terms.update(overrides)
    return terms


def test_a_forged_degradation_is_refused() -> None:
    # The record disagrees with the arithmetic it reports: the degradation must
    # recompute from the two statistics and the reference threshold.
    with pytest.raises(TripwirePanelError, match="disagrees with the arithmetic"):
        SeedRerunVerdict(**_terms(degradation=99.0))


def test_a_forged_decision_is_refused() -> None:
    # The record states a rule it does not apply.
    with pytest.raises(TripwirePanelError, match="does not apply|re-derive"):
        SeedRerunVerdict(**_terms(degradation_rejected=True))


def test_a_rejection_that_is_not_the_disjunction_is_refused() -> None:
    with pytest.raises(TripwirePanelError, match="disjunction"):
        SeedRerunVerdict(**_terms(rejected=True))
    # The third cause is named rather than folded in: a record that claims the
    # reference run failed while the record's own ``reference_rejected`` says
    # it did not is caught by the same invariant, so the disjunction cannot be
    # satisfied by a bit whose cause the record does not carry.
    with pytest.raises(TripwirePanelError, match="disjunction"):
        SeedRerunVerdict(**_terms(reference_rejected=True))


def test_a_forged_threshold_is_refused() -> None:
    # The bar must recompute from the level and the date count, so a reader can
    # size the degradation in a bar they can rebuild from the record.
    with pytest.raises(TripwirePanelError, match="own arithmetic"):
        SeedRerunVerdict(**_terms(reference_threshold=0.5))


def test_a_forged_outcome_word_is_refused() -> None:
    # An outcome outside §8's two-word slice is refused by name...
    with pytest.raises(TripwirePanelError, match="vocabulary"):
        SeedRerunVerdict(**_terms(outcome="crashed"))
    # ...and an outcome *inside* the vocabulary that disagrees with the
    # decision is refused for that reason instead: the word is the decision's
    # own translation, so the two spellings of one fact cannot differ. Built
    # from a genuinely rejected set of terms rather than a forged bit, so the
    # outcome check is what fires rather than an earlier invariant: the
    # configured bar is tightened below the observed degradation, which makes
    # `degradation_rejected` (and so `rejected`) re-derive *true* on its own.
    rejected_terms = _terms(degradation_threshold=1e-9)
    assert rejected_terms["degradation"] > rejected_terms["degradation_threshold"]
    rejected_terms.update(
        degradation_rejected=True, rejected=True, outcome="ok"
    )
    with pytest.raises(TripwirePanelError, match="two spellings"):
        SeedRerunVerdict(**rejected_terms)


def test_a_tripwire_that_is_not_this_probe_is_refused() -> None:
    with pytest.raises(TripwirePanelError, match="re-run indistinguishable"):
        SeedRerunVerdict(**_terms(tripwire=TIME_SHUFFLE_NAME))


def test_an_axis_this_feature_never_perturbed_is_refused() -> None:
    with pytest.raises(TripwirePanelError, match="never moved"):
        SeedRerunVerdict(**_terms(axis="window-offset"))


def test_a_record_whose_two_seeds_agree_is_refused() -> None:
    # The structural zero, refused at the record as well as at the entry point:
    # a verdict built by hand must not be able to report a perturbation it
    # never made.
    with pytest.raises(TripwirePanelError, match="two different seeds|same seed"):
        SeedRerunVerdict(**_terms(rerun_seed=DEFAULT_SHUFFLE_SEED))


def test_a_non_finite_field_is_refused() -> None:
    for field in ("reference_sharpe", "rerun_sharpe", "degradation"):
        with pytest.raises(TripwirePanelError, match="finite|disagrees"):
            SeedRerunVerdict(**_terms(**{field: math.nan}))


# -- The composed component --------------------------------------------------


def test_the_composed_component_exposes_the_re_run(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The re-run is a *method on the probe component*, not a fifth one: it is
    # this probe taken twice, and it needs the statistic, the shuffle and the
    # threshold that already live here. So the composed `tripwires` component
    # carries it, and no new component name was invented.
    from pathlib import Path

    import tripwires as member

    from app.module_loader import Registration, create_app

    member_src = Path(member.__file__).resolve().parent.parent
    probe = create_app(member_src, registry=Registration()).get("tripwires")
    scores, targets = _clean_candidate(grid, symbols)
    verdict = probe.rerun(scores, targets, node_id="node-1")
    assert type(verdict).__name__ == "SeedRerunVerdict"
    assert verdict.tripwire == "perturbation-stability"
    assert verdict.rejected is False


def test_the_composed_re_run_agrees_with_the_module_function(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The component's method is one call to the module function — a thin
    # delegation, not a second implementation.
    #
    # Compared field by field rather than with `==`, and that is the loader's
    # known seam rather than a loose assertion: the scan imports this member
    # under a synthetic module name, so the process holds two distinct
    # `SeedRerunVerdict` classes for one source file and a dataclass's `__eq__`
    # is gated on class identity. The member's component suite documents the
    # same seam for the same reason.
    from pathlib import Path

    import tripwires as member

    from app.module_loader import Registration, create_app

    member_src = Path(member.__file__).resolve().parent.parent
    probe = create_app(member_src, registry=Registration()).get("tripwires")
    scores, targets = _clean_candidate(grid, symbols)
    composed = probe.rerun(scores, targets, node_id="node-1")
    direct = run_seed_rerun(scores, targets, node_id="node-1")
    assert type(composed).__name__ == type(direct).__name__ == "SeedRerunVerdict"
    assert {
        field.name: getattr(composed, field.name)
        for field in composed.__dataclass_fields__.values()
    } == {
        field.name: getattr(direct, field.name)
        for field in direct.__dataclass_fields__.values()
    }


def test_the_re_run_still_needs_no_database() -> None:
    # The property features 131 and 132 must not cost the member, restated for
    # this one: the re-run is two calls to a pure function of two mappings, and
    # it is what the frozen evaluator image would import. It names no fixture,
    # which is the assertion.
    scores, targets = _clean_candidate(monday(40), ["A", "B", "C"])
    verdict = run_seed_rerun(scores, targets, node_id="node-1")
    assert verdict.outcome in ("ok", "tripwire_fail")


def test_the_re_run_reads_no_environment(
    grid: list[dt.date], symbols: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The configured threshold is a parameter, not an environment lookup —
    # deliberately, so a deployment cannot reconfigure a shared object out from
    # under a replay. Two calls in different environments must agree exactly.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_seed_rerun(scores, targets, node_id="node-1")
    for name in ("DATABASE_URL", "NULL_SIDECAR_PATH", "LAKE_ROOT"):
        monkeypatch.setenv(name, "sentinel")
    assert run_seed_rerun(scores, targets, node_id="node-1") == first
