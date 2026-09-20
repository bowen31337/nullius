"""Feature 134 — the perturbation-stability triage figure, against its claims.

app_spec.xml: *"System computes the area under the curve for perturbation
stability separating planted nulls from real signals, which emits the triage
figure."*  The sentence asks for one number and names its provenance: two
labelled populations, a reduction of the family's figures over both to an area
under a curve.  The suite is organised around the pieces a reader has to trust
otherwise, and two of them are load-bearing above the rest.

* :func:`test_the_measured_figure_is_the_figure_the_module_states` — the
  module's docstring states 0.4548, per-axis 0.3750 / 0.4932 / 0.4961, and a
  rejection split of 7 of 32 signals against 1 of 32 nulls.  Those are *numbers
  in a docstring*, which is the one kind of claim that cannot be kept true by
  intent, so they are asserted here at the pin: a figure that drifted is a
  figure whose prose describes a different experiment.

* :func:`test_the_positive_control_inverts_the_family` — the docstring's own
  honesty argument, checked behaviourally rather than argued.  With feature
  133's planted *leaks* as the signal class the seed axis scores 1.0000
  exactly, the universe-subsample axis 0.0000, and the lookback axis 0.7812 —
  so the family's one discriminative direction belongs to feature 125's leak
  bar, not to the triage.

The AUC's arithmetic is checked the way an arithmetic should be: against cases
whose answer is known independently (a perfect separation, a total tie, a
reversal) rather than against a second implementation of the same formula.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import random

import pytest
from tripwires import (
    CORPUS_GRID,
    CORPUS_SYMBOLS,
    HORIZONS,
    LOOKBACK_AXIS,
    PERTURBATION_AXES,
    PERTURBATION_STABILITY_NAME,
    SEED_AXIS,
    SUBSAMPLE_AXIS,
    TRIAGE_AXES,
    TRIAGE_KINDS,
    TRIAGE_PERSISTENCE,
    TRIAGE_POPULATION,
    TRIAGE_SEED,
    TRIAGE_SIGNAL_HORIZON,
    TRIAGE_TRUE_IC,
    TriageCandidate,
    TripwirePanelError,
    TripwireStatisticError,
    instability_of,
    planted_nulls,
    planted_signals,
    real_signals,
    run_lookback_rerun,
    run_seed_rerun,
    run_subsample_rerun,
    run_triage,
    triage_auc,
)
from tripwires.triage import _market_targets

#: The figure at the pin, to the last stated digit.  Restated rather than
#: imported, because importing it from the module under test would make the
#: assertion "the module agrees with itself", which is not a claim.
_MEASURED_AUC = 0.4547526041666667
_MEASURED_AXIS_AUCS = {
    SEED_AXIS: 0.375,
    SUBSAMPLE_AXIS: 0.4931640625,
    LOOKBACK_AXIS: 0.49609375,
}


# -- The statistic: the AUC's arithmetic, against known answers -----------------


def test_a_perfect_separation_is_exactly_one() -> None:
    # Every null above every signal: every pair ordered, P(null > signal) = 1.
    assert triage_auc([3.0, 4.0, 5.0], [0.0, 1.0, 2.0]) == 1.0


def test_a_total_reversal_is_exactly_zero() -> None:
    # The orientation is part of the statistic's meaning, so the mirror case is
    # the mirror answer — not an error to flip, the module docstring's point.
    assert triage_auc([0.0, 1.0, 2.0], [3.0, 4.0, 5.0]) == 0.0


def test_a_class_against_itself_is_exactly_one_half() -> None:
    # The all-ties case.  This is the assertion that pins the midrank
    # arithmetic: a formula that ignored ties would return 1.0 or 0.0 here.
    figures = [0.5, 1.5, 2.5, 9.0]
    assert triage_auc(list(figures), list(figures)) == 0.5


def test_ties_between_the_classes_score_a_half() -> None:
    # One null against one identical signal: the single pair is a tie.
    assert triage_auc([7.0], [7.0]) == 0.5
    # Two nulls, one tied with the single signal and one above it:
    # P(>)+ ½P(=) = (1 + 0.5)/2 = 0.75.
    assert triage_auc([7.0, 8.0], [7.0]) == 0.75


def test_the_auc_does_not_depend_on_the_order_the_figures_arrive_in() -> None:
    # fsum over a sorted pool, stated as a property: the same two multisets in
    # any permutation are the same curve, so a caller reading rows out of a
    # table in whatever order the database returned them gets one answer.
    nulls = [0.1, 0.9, 0.4, 0.55, 0.2]
    signals = [0.3, 0.8, 0.45, 0.6]
    expected = triage_auc(nulls, signals)
    for permutation in (
        list(reversed(nulls)),
        [nulls[2], nulls[0], nulls[4], nulls[1], nulls[3]],
    ):
        assert triage_auc(permutation, signals) == expected
        assert triage_auc(nulls, list(reversed(signals))) == expected


def test_a_symmetry_about_one_half_holds() -> None:
    # Swapping the classes reflects the curve about ½ — the property that makes
    # "below ½ means the axis separates with the other sign" literally true.
    nulls = [0.1, 0.2, 0.9]
    signals = [0.15, 0.85]
    assert triage_auc(nulls, signals) + triage_auc(signals, nulls) == 1.0


def test_the_auc_is_the_pair_counting_formula() -> None:
    # The rank-sum spelling and the pair-counting spelling are the same
    # statistic; a brute-force count over the cross product confirms the
    # midrank implementation on a sample with no ties to hide behind.
    nulls = [0.11, 0.42, 0.77, 0.93]
    signals = [0.05, 0.35, 0.61, 0.88, 0.99]
    wins = sum(
        1.0 if n > s else 0.5 if n == s else 0.0 for n in nulls for s in signals
    )
    assert triage_auc(nulls, signals) == wins / (len(nulls) * len(signals))


def test_an_empty_class_is_refused_rather_than_scored_zero() -> None:
    # An AUC over nothing is not zero, it is undefined — and 0.0 is the worst
    # possible confusion with a real answer, so the seam refuses by name.
    for nulls, signals in (([], [1.0]), ([1.0], []), ([], [])):
        with pytest.raises(TripwireStatisticError, match="non-empty"):
            triage_auc(nulls, signals)


def test_a_non_finite_or_non_numeric_figure_is_refused_by_name() -> None:
    # A NaN would reach the figure dressed as a measurement: NaN comparisons
    # are all false, so it would land in the tie branch and silently move the
    # curve.  Each bad cell is refused where it is read.
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(TripwireStatisticError, match="finite"):
            triage_auc([bad], [1.0])
    with pytest.raises(TripwireStatisticError, match="number"):
        triage_auc(["0.5"], [1.0])


def test_a_boolean_figure_is_refused_as_a_number() -> None:
    # ``bool`` is an ``int`` in Python; a True that reached the AUC would rank
    # as 1.0.  The module checks the type rather than trusting arithmetic.
    with pytest.raises(TripwireStatisticError, match="number"):
        triage_auc([True], [1.0])


# -- The populations: planted nulls and real signals ---------------------------


def test_the_two_populations_are_the_spec_sentences_two_nouns() -> None:
    # The class vocabulary is closed and each builder plants exactly its own.
    assert TRIAGE_KINDS == ("planted-null", "real-signal")
    nulls = planted_nulls(seed=TRIAGE_SEED, count=4)
    signals = real_signals(seed=TRIAGE_SEED, count=4)
    assert {c.kind for c in nulls} == {"planted-null"}
    assert {c.kind for c in signals} == {"real-signal"}
    assert all(isinstance(c, TriageCandidate) for c in nulls + signals)


def test_the_populations_are_the_pinned_size_by_default() -> None:
    # The pin is the population the docstring's stated figures were measured
    # over, so a default that drifted would silently re-describe the module.
    assert TRIAGE_POPULATION == 32
    assert len(planted_nulls()) == TRIAGE_POPULATION
    assert len(real_signals()) == TRIAGE_POPULATION


def test_the_populations_are_deterministic_in_their_seed() -> None:
    # The experiment is a pure function of (seed, count) — refused otherwise
    # below — so two calls are equal candidates, value for value.
    assert planted_nulls() == planted_nulls()
    assert real_signals() == real_signals()


def test_a_different_seed_plants_a_different_population() -> None:
    # Determinism is not constancy: the seed really drives the stream, so the
    # experiment can be re-answered on a fresh population.
    assert planted_nulls(seed=TRIAGE_SEED + 1) != planted_nulls()
    assert real_signals(seed=TRIAGE_SEED + 1) != real_signals()


def test_each_candidate_is_drawn_from_its_own_named_stream() -> None:
    # The determinism contract stated exactly: the *i*-th candidate's panels
    # are reproducible from (seed, kind, index) alone, which is what makes a
    # figure attributable without a side table.
    grid = [dt.date(2024, 1, 1) + dt.timedelta(days=n) for n in range(CORPUS_GRID)]
    names = [f"S{i:02d}" for i in range(CORPUS_SYMBOLS)]
    candidate = planted_nulls(seed=7, count=3)[2]
    rng = random.Random(f"{7}:null:{2}")
    targets = _market_targets(rng, TRIAGE_PERSISTENCE)
    scores = {day: {s: rng.gauss(0.0, 1.0) for s in names} for day in grid}
    assert {d: dict(r) for d, r in candidate.scores.items()} == scores
    assert {h: {d: dict(r) for d, r in s.items()} for h, s in candidate.targets.items()} == targets


def test_the_nulls_carry_no_alignment_and_the_signals_do() -> None:
    # The one thing the classes differ in is the date-aligned relationship the
    # evaluator is supposed to find.  Measured as the correlation of score
    # against the loaded horizon's target: near zero for the nulls, near the
    # pinned ic for the signals — the design claim, checked rather than stated.
    def loading(candidate: TriageCandidate) -> float:
        series = candidate.targets[TRIAGE_SIGNAL_HORIZON]
        xs = [candidate.scores[d][s] for d in candidate.scores for s in candidate.scores[d]]
        ys = [series[d][s] for d in candidate.scores for s in candidate.scores[d]]
        mx, my = math.fsum(xs) / len(xs), math.fsum(ys) / len(ys)
        cov = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = math.fsum((x - mx) ** 2 for x in xs)
        vy = math.fsum((y - my) ** 2 for y in ys)
        return cov / math.sqrt(vx * vy)

    null_loadings = [loading(c) for c in planted_nulls(count=8)]
    signal_loadings = [loading(c) for c in real_signals(count=8)]
    assert all(abs(value) < 0.10 for value in null_loadings)
    assert all(0.0 < value < 0.15 for value in signal_loadings)
    # The signals' mean loading recovers the pin; the nulls' does not.
    assert abs(math.fsum(signal_loadings) / len(signal_loadings) - TRIAGE_TRUE_IC) < 0.05


def test_the_signals_load_on_the_shortest_horizon() -> None:
    # The probe's own horizon policy, carried as a constant: the nulls load on
    # nothing, so this is a fact about one class only.
    assert TRIAGE_SIGNAL_HORIZON == min(HORIZONS)
    candidate = real_signals(count=1)[0]
    # The bundle is whole — all five spec horizons — so the probe resolves to
    # the shortest covered rather than to the only one available.
    assert set(candidate.targets) == set(HORIZONS)


def test_the_populations_run_on_the_corpus_width() -> None:
    # The experiment is run on feature 125's own leak-verification width, so
    # the triage's answer is stated at the size the probe's detection was
    # checked at — the two figures are comparable by construction.
    assert CORPUS_GRID == 120
    assert CORPUS_SYMBOLS == 30
    candidate = next(iter(planted_nulls(count=1)))
    assert len(candidate.scores) == CORPUS_GRID
    assert len(next(iter(candidate.scores.values()))) == CORPUS_SYMBOLS


def test_a_candidate_refuses_a_node_it_cannot_attribute() -> None:
    # The shallow validation the dataclass owns: an unnamed candidate's figure
    # is a figure nothing downstream can attribute.
    panels = next(iter(planted_nulls(count=1)))
    for bad in ("", "   "):
        with pytest.raises(TripwirePanelError, match="name its node"):
            TriageCandidate(
                node_id=bad,
                kind="planted-null",
                scores=panels.scores,
                targets=panels.targets,
            )


def test_a_candidate_refuses_a_third_kind() -> None:
    # TRIAGE_KINDS is closed: a third kind is a class the AUC has no branch for.
    panels = next(iter(planted_nulls(count=1)))
    with pytest.raises(TripwirePanelError, match="kind is one of"):
        TriageCandidate(
            node_id="x",
            kind="leak",
            scores=panels.scores,
            targets=panels.targets,
        )


def test_a_candidate_refuses_panels_that_are_not_mappings() -> None:
    panels = next(iter(planted_nulls(count=1)))
    with pytest.raises(TripwirePanelError, match="must be a mapping"):
        TriageCandidate(
            node_id="x", kind="planted-null", scores=[], targets=panels.targets
        )


def test_a_non_integer_seed_or_count_is_refused_by_name() -> None:
    # The experiment is a pure function of (seed, count): a non-integer names
    # no stream and no population.  ``bool`` is refused as a non-integer for
    # the reason the statistic refuses it as a number.
    for bad in (True, 1.0, "7", None):
        with pytest.raises(TripwirePanelError, match="integer"):
            planted_nulls(seed=bad)  # type: ignore[arg-type]
        with pytest.raises(TripwirePanelError, match="integer"):
            real_signals(seed=bad)  # type: ignore[arg-type]
        with pytest.raises(TripwirePanelError, match="count of candidates"):
            planted_nulls(count=bad)  # type: ignore[arg-type]


# -- The read: each axis' figure in its own vocabulary -------------------------


def test_the_triage_axes_are_the_family_axes_this_member_implements() -> None:
    # The window-offset axis is named as *absent* rather than skipped quietly:
    # a family figure over axes nobody ran is a figure nobody measured.
    assert TRIAGE_AXES == (SEED_AXIS, SUBSAMPLE_AXIS, LOOKBACK_AXIS)
    assert set(TRIAGE_AXES) < set(PERTURBATION_AXES)
    assert "window-offset" not in TRIAGE_AXES
    assert TRIAGE_AXES == tuple(a for a in PERTURBATION_AXES if a in TRIAGE_AXES)


def test_the_seed_axis_figure_is_its_degradation_folded() -> None:
    # Feature 127's figure is signed and one-sided against degradation; the
    # triage ranks magnitudes, so a signal that *improved* under the re-run is
    # as unstable as one that degraded — the fold, stated rather than implied.
    @dataclasses.dataclass
    class Verdict:
        degradation: float

    assert instability_of(SEED_AXIS, Verdict(-0.4)) == 0.4
    assert instability_of(SEED_AXIS, Verdict(0.4)) == 0.4
    assert instability_of(SEED_AXIS, Verdict(0.0)) == 0.0


def test_the_magnitude_axes_are_read_as_their_own_stability() -> None:
    # The other two axes already carry magnitudes; the triage reads each axis'
    # own vocabulary rather than one name for all three.
    @dataclasses.dataclass
    class Verdict:
        stability: float

    for axis in (SUBSAMPLE_AXIS, LOOKBACK_AXIS):
        assert instability_of(axis, Verdict(1.71)) == 1.71


def test_the_read_is_structural_not_an_isinstance_check() -> None:
    # Deliberately structural, for the member's two-copies reason: the composed
    # component's classes are distinct objects from a directly imported copy,
    # so a field-name check is the one that holds across both.
    class NotAVerdict:
        degradation = 0.25

    assert instability_of(SEED_AXIS, NotAVerdict()) == 0.25


def test_a_verdict_from_some_other_feature_is_refused_by_name() -> None:
    # A verdict carrying none of the fields the axis ranks is a verdict from
    # some other feature; the message says which field it wanted.
    with pytest.raises(TripwirePanelError, match="degradation"):
        instability_of(SEED_AXIS, object())
    with pytest.raises(TripwirePanelError, match="stability"):
        instability_of(SUBSAMPLE_AXIS, object())


def test_the_window_offset_axis_is_refused_as_not_implemented() -> None:
    # Refused by name rather than KeyError'd, so a caller that handed the
    # fourth axis' name gets the reason rather than a traceback.
    with pytest.raises(TripwirePanelError, match="not in\\s+this member|not in"):
        instability_of("window-offset", object())


def test_a_non_finite_axis_figure_is_refused_by_name() -> None:
    # A NaN would reach the triage figure dressed as a measurement — the same
    # refusal the AUC's own reader makes, at the seam one step earlier.
    @dataclasses.dataclass
    class Verdict:
        stability: float

    with pytest.raises(TripwirePanelError, match="not finite"):
        instability_of(SUBSAMPLE_AXIS, Verdict(float("nan")))


def test_the_read_never_re_derives_an_axis_figure() -> None:
    # The runner is called, not reimplemented: the figure the triage ranks is
    # the figure the axis' own verdict carries, bit for bit.
    candidate = next(iter(real_signals(count=1)))
    verdict = run_seed_rerun(
        candidate.scores, candidate.targets, node_id=candidate.node_id
    )
    assert instability_of(SEED_AXIS, verdict) == abs(verdict.degradation)


# -- The figure: the emitted value and its invariants --------------------------


def test_the_measured_figure_is_the_figure_the_module_states() -> None:
    # The docstring's numbers, at the pin.  A figure that drifted is a figure
    # whose prose describes a different experiment, and prose cannot keep
    # itself true — this assertion is what keeps it true.
    figure = run_triage()
    assert figure.auc == _MEASURED_AUC
    assert dict(figure.aucs) == _MEASURED_AXIS_AUCS
    assert figure.null_count == figure.signal_count == TRIAGE_POPULATION
    assert figure.null_reference_rejections == 1
    assert figure.signal_reference_rejections == 7
    # The family figure is the macro-mean of the axes, not a pooled AUC.
    assert figure.auc == math.fsum(figure.aucs.values()) / len(figure.axes)


def test_the_figure_sits_at_chance_on_both_sides_of_one_half() -> None:
    # The headline reading: the family neither separates well nor inverts
    # wholesale — the macro-mean is *below* ½ because one axis inverts, which
    # is the honest cost the docstring states rather than a bug.
    figure = run_triage()
    assert 0.4 < figure.auc < 0.5
    assert figure.aucs[SEED_AXIS] < 0.5  # the honest inversion
    assert 0.45 < figure.aucs[SUBSAMPLE_AXIS] < 0.55
    assert 0.45 < figure.aucs[LOOKBACK_AXIS] < 0.55


def test_the_seed_axis_inversion_is_the_fold_and_not_a_sampling_wobble() -> None:
    # The docstring's structural explanation, checked: the fold of two noise
    # magnitudes is tighter than the noise itself, so the nulls' two folded
    # Sharpes land *closer together* than the signals' — the nulls' mean figure
    # is the smaller one, which is what puts the AUC below ½.
    figure = run_triage()
    assert figure.null_means[SEED_AXIS] < figure.signal_means[SEED_AXIS]
    assert figure.null_means[SEED_AXIS] < figure.null_means[SUBSAMPLE_AXIS]


def test_the_figure_carries_every_term_it_was_computed_from() -> None:
    # Every term the figure was made from is on the record: without the means,
    # an AUC of 0.37 is a sampling wobble rather than a finding about the axis.
    figure = run_triage(count=4)
    assert figure.tripwire == PERTURBATION_STABILITY_NAME
    assert figure.axes == TRIAGE_AXES
    assert set(figure.aucs) == set(figure.null_means) == set(figure.signal_means)
    assert figure.seed == TRIAGE_SEED
    assert figure.true_ic == TRIAGE_TRUE_IC
    assert figure.persistence == TRIAGE_PERSISTENCE
    assert figure.grid == CORPUS_GRID
    assert figure.symbols == CORPUS_SYMBOLS


def test_the_rejection_counts_are_the_measured_boundary_with_the_probe_bar() -> None:
    # The false-alarm rate over the planted nulls and the signals' brush with
    # leak territory — the fact the figure's honesty turns on.  Counted from
    # the first axis' verdicts, and bounded by its own class.
    figure = run_triage()
    assert 0 <= figure.null_reference_rejections <= figure.null_count
    assert 0 <= figure.signal_reference_rejections <= figure.signal_count


def test_every_candidate_counts_toward_its_class_even_when_rejected() -> None:
    # The triage ranks figures, not verdicts.  Dropping rejected candidates
    # would silently turn the AUC into a figure over the survivors only — a
    # different and flattering experiment — so both classes enter whole.
    figure = run_triage()
    assert figure.null_count == len(planted_nulls())
    assert figure.signal_count == len(real_signals())
    # And the rejected members really are in there: the counts above are
    # non-zero at the pin, so "whole" is not vacuous here.
    assert figure.signal_reference_rejections > 0


def test_the_figure_is_deterministic_bit_for_bit() -> None:
    # The same (seed, count) produce the same figure, on any machine: the
    # payload of one run equals the payload of the same run again, byte for
    # byte in any order-preserving serializer.
    first, second = run_triage(count=4), run_triage(count=4)
    assert first == second
    assert hash(first) == hash(second)
    assert first.to_payload() == second.to_payload()


def test_a_population_under_two_a_side_is_refused_as_a_coin_flip() -> None:
    # One a side is an AUC of 0, ½ or 1 — a coin flip the record would carry
    # as a curve.  Refused at the seam rather than emitted.
    for count in (0, 1, -3):
        with pytest.raises(TripwirePanelError, match="at least two candidates"):
            run_triage(count=count)


def test_a_non_integer_run_argument_is_refused_by_name() -> None:
    for bad in (True, 2.0, "4"):
        with pytest.raises(TripwirePanelError, match="integer"):
            run_triage(seed=bad)  # type: ignore[arg-type]
        with pytest.raises(TripwirePanelError, match="integer"):
            run_triage(count=bad)  # type: ignore[arg-type]


def test_the_figure_refuses_a_record_that_disagrees_with_its_own_arithmetic() -> None:
    # A hand-built record whose family AUC is not the macro-mean of its own
    # per-axis AUCs fails loudly rather than emitting a triage figure nobody
    # measured — the construction-time discipline the family's verdicts keep.
    figure = run_triage(count=4)
    for field, value in (
        ("auc", 0.9),
        ("tripwire", "time-shuffle"),
        ("null_count", 1),
        ("null_reference_rejections", 99),
        ("true_ic", 1.5),
        ("grid", 1),
    ):
        with pytest.raises(TripwirePanelError):
            dataclasses.replace(figure, **{field: value})
    with pytest.raises(TripwirePanelError, match="macro-mean"):
        dataclasses.replace(
            figure, aucs={**figure.aucs, SEED_AXIS: 0.99}
        )


def test_the_figure_refuses_axes_the_family_does_not_run() -> None:
    # An axis nobody ran is a figure nobody measured; and the axes are carried
    # in the family's own order, so two records of one experiment are one shape.
    figure = run_triage(count=4)
    for axes in (("seed", "window-offset"), (), ("seed", "seed"), ("seed",)):
        with pytest.raises(TripwirePanelError):
            dataclasses.replace(figure, axes=axes)


def test_the_payload_is_the_figures_sorted_emitted_form() -> None:
    # The emitted form of the emitted figure, for a log line or a report row:
    # mappings collapse to sorted pairs so the payload of one run equals the
    # payload of the same run again.
    payload = run_triage(count=4).to_payload()
    assert payload["tripwire"] == PERTURBATION_STABILITY_NAME
    assert payload["axes"] == list(TRIAGE_AXES)
    assert list(payload["aucs"]) == sorted(payload["aucs"])
    assert list(payload["null_means"]) == sorted(payload["null_means"])
    assert list(payload["signal_means"]) == sorted(payload["signal_means"])


# -- The positive control: feature 133's leaks as the signal class --------------


def test_the_positive_control_inverts_the_family() -> None:
    # The docstring's honesty argument, checked behaviourally.  With the
    # corpus's planted *leaks* as the signal class, the seed axis scores 1.0000
    # exactly — a whole-sample statistic does not degrade under a second
    # derangement, so its degradation is structurally 0.0, below every null —
    # the universe-subsample axis 0.0000, and the lookback axis 0.7812.  The
    # one direction the family separates in is a direction feature 125's leak
    # bar already owns, which is why the honest classes measure at chance.
    leaks = planted_signals()
    nulls = planted_nulls()
    runners = {
        SEED_AXIS: run_seed_rerun,
        SUBSAMPLE_AXIS: run_subsample_rerun,
        LOOKBACK_AXIS: run_lookback_rerun,
    }
    measured = {}
    for axis, runner in runners.items():
        null_figures = [
            instability_of(
                axis, runner(c.scores, c.targets, node_id=c.node_id)
            )
            for c in nulls
        ]
        leak_figures = [
            instability_of(
                axis, runner(c.scores, c.targets, node_id=c.node_id)
            )
            for c in leaks
        ]
        measured[axis] = triage_auc(null_figures, leak_figures)
        if axis == SEED_AXIS:
            # Structurally zero, not merely under its bar: the sharpest form of
            # the family's four-features argument, measured rather than argued.
            assert all(figure == 0.0 for figure in leak_figures)
    assert measured[SEED_AXIS] == 1.0
    assert measured[SUBSAMPLE_AXIS] == 0.0
    assert measured[LOOKBACK_AXIS] == 0.78125
