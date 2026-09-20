"""Feature 129 — the universe-subsample re-run, against the properties it pins.

app_spec.xml: *"System re-runs a candidate against a 20 percent universe
subsample, persisting the subsample stability figure."*  Feature 127's suite
opens by naming the two tests that keep its probe from being feature 125
restated; this one does the same for the third axis, and the load-bearing
claims are three:

* :func:`test_every_corpus_leak_is_caught_here_and_invisible_to_the_seed_axis`
  — every planted leak in the maintained corpus reports a subsample figure of
  ≈ 1.71 (rejected) and a seed-axis degradation of exactly ``0.0``
  (structurally zero, not merely under its bar).  That is the sharpest form of
  the family's four-features argument, and it is the measurement rather than an
  argument: a whole-sample statistic does not depend on *which date* a
  cross-section is joined against, so the derangement cannot move it — while
  thinning the universe moves it a great deal.
* :func:`test_the_default_threshold_is_the_shared_noise_bar` — the bar is
  ``√(2(1 − √fraction))``, derived from the null's own standard deviation under
  the correlation the two runs actually share (``ρ = √f``, because the
  subsample's names are a *subset* of the reference's) rather than tuned.  It
  carries no ``level`` and no ``dates`` term, both of which cancel because the
  figure is already in units of a threshold that holds them — and the tempting
  ``√2`` derivation, which assumes the two runs are independent, is asserted to
  be **wrong** rather than close enough, because it is a bar ~35% too wide that
  passes every candidate the correct one rejects.
* :func:`test_a_passing_figure_is_persisted_beside_a_failing_one` — the half of
  this feature its sentence names and no other axis has.  Feature 131's store
  refuses a verdict that passed; this one must not, because the triage figure
  (feature 134) computes an AUC over both classes.

The leak fixtures come from :mod:`_panels`' ``lookahead_panel`` and feature
133's corpus, so every claim about "a leak" is checked against the leak the
member already knows how to build rather than against a second one invented
here.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import sqlite3

import pytest
from _panels import DEFAULT_SYMBOLS, gaussian_panel, lookahead_panel, monday
from tripwires import (
    DEFAULT_DEGRADATION_THRESHOLD,
    DEFAULT_SHUFFLE_LEVEL,
    DEFAULT_SHUFFLE_SEED,
    DEFAULT_SUBSAMPLE_FRACTION,
    DEFAULT_SUBSAMPLE_SEED,
    DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
    PERTURBATION_AXES,
    PERTURBATION_STABILITY_NAME,
    STABILITY_COLUMNS,
    STABILITY_TABLE,
    SUBSAMPLE_AXIS,
    TRIPWIRE_OUTCOMES,
    PoisonStore,
    StabilityRecord,
    StabilityStore,
    SubsampleRerunVerdict,
    TripwirePanelError,
    TripwirePoisonError,
    TripwireStabilityError,
    record_stability,
    run_subsample_rerun,
    run_time_shuffle_tripwire,
    stability_bootstrap_schema,
    stability_of,
    subsample_figure,
    subsample_symbols,
    time_shuffle_threshold,
)

_NODE = "11111111-1111-1111-1111-111111111111"


def _clean_candidate(
    grid: list[dt.date], symbols: list[str], *, seed: int = 3
) -> tuple[dict, dict]:
    """A candidate with no relationship to its targets — scores, targets.

    The two panels are drawn from different streams, so they are independent by
    construction: this is the null the re-run must pass, and therefore the
    candidate whose stability figure is pure sampler noise.
    """
    targets = {1: gaussian_panel(grid, symbols, seed=seed + 1)}
    scores = gaussian_panel(grid, symbols, seed=seed + 2)
    return scores, targets


def _leaking_candidate(
    grid: list[dt.date], symbols: list[str]
) -> tuple[dict, dict]:
    """The canonical planted leak — a full-sample symbol mean, as scores.

    Built here rather than taken from the corpus so a test can hand it *this*
    suite's grid and universe.  Its figure is a draw, not a constant: over 40
    seeds of the 120-date, 30-symbol configuration this panel's figure runs
    0.55–2.18, clearing the bar about half the time.  That is not a defect of
    the fixture — a *single* panel's figure is one sample from the null or from
    a weak alternative — and it is why the leak tests that assert a rejection
    use :func:`_corpus_leak` instead, where the member's own maintained corpus
    gives a stable ≈ 1.71.  It is kept for the tests that need a panel *related*
    to its targets and do not care about the figure's value.
    """
    targets = {1: gaussian_panel(grid, symbols, seed=11)}
    return lookahead_panel(targets, horizon=1), targets


def _corpus_leak() -> tuple[dict, dict]:
    """The corpus's own ``full_sample_mean`` leak — a *stable* planted leak.

    The fixture for every assertion that turns on a rejection, because its
    figure is not a draw: the corpus's grid and universe give it ≈ 1.71 against
    this axis' 1.05 bar, reproducibly, and 0.0 under the seed axis.  A test that
    needs "a rejected candidate" must not be at the mercy of a 50/50 panel.
    """
    from tripwires import planted_signals

    for signal in planted_signals():
        if signal.leak_kind == "full_sample_mean":
            return dict(signal.scores), dict(signal.targets)
    raise AssertionError("the corpus no longer plants a full_sample_mean leak")


def _rejected_candidate(
    grid: list[dt.date], symbols: list[str]
) -> tuple[dict, dict]:
    """A candidate whose figure clears this axis' bar — the corpus's worst leak.

    Used where a *rejection* is the input rather than the thing under test: a
    persisted row of each class, a poisoning beside a stability figure.  It is
    the corpus's own ``full_sample_mean`` panel rather than one invented here,
    so the candidate that provokes the bar is the member's maintained artifact.
    """
    from tripwires import planted_signals

    for signal in planted_signals():
        if signal.leak_kind == "full_sample_mean":
            return dict(signal.scores), dict(signal.targets)
    raise AssertionError("the corpus no longer plants a full_sample_mean leak")


# -- The subsample itself -------------------------------------------------------


def test_the_subsample_is_the_pinned_fraction_of_the_universe() -> None:
    # The spec's own "20 percent", pinned as a constant *and* as behaviour: a
    # 30-name universe yields 6 names, so the default fraction is the spec's
    # number rather than whatever the drawing happens to produce.
    names = [f"S{index:02d}" for index in range(DEFAULT_SYMBOLS)]
    drawn = subsample_symbols(names)
    assert DEFAULT_SUBSAMPLE_FRACTION == 0.20
    assert len(drawn) == 6
    assert set(drawn) < set(names)


def test_the_subsample_is_deterministic_in_its_seed() -> None:
    # A stability figure has to be comparable between one campaign and another,
    # which it cannot be if the subsample moves under it. Two calls with one
    # seed are one subsample, bit for bit; two seeds are different draws.
    names = [f"S{index:02d}" for index in range(DEFAULT_SYMBOLS)]
    assert subsample_symbols(names, seed=7) == subsample_symbols(names, seed=7)
    assert subsample_symbols(names, seed=7) != subsample_symbols(names, seed=8)


def test_the_default_subsample_seed_is_not_the_shuffle_seed() -> None:
    # Two knobs, two constants. Reusing feature 125's seed would make the
    # subsample and the derangement move together under any caller that left
    # both at their defaults — two axes perturbed in one measurement, which is
    # exactly what this feature holds fixed on purpose.
    #
    # The verdict pins the same fact from the other side: both runs draw their
    # pairing from the *one* seed the re-run was given, so there is no second
    # seed anywhere in the record — that knob belongs to feature 127.
    assert DEFAULT_SUBSAMPLE_SEED != DEFAULT_SHUFFLE_SEED
    assert "rerun_seed" not in {
        field.name for field in dataclasses.fields(SubsampleRerunVerdict)
    }


def test_the_subsample_is_returned_in_a_canonical_order() -> None:
    # Sorted, so a verdict's ``symbols`` reads the same however the caller's
    # mapping happened to enumerate — two callers handing in the same universe
    # in different orders get one subsample, not two orderings of one.
    names = [f"S{index:02d}" for index in range(DEFAULT_SYMBOLS)]
    shuffled = list(reversed(names))
    assert subsample_symbols(shuffled, seed=3) == subsample_symbols(names, seed=3)
    assert list(subsample_symbols(names, seed=3)) == sorted(
        subsample_symbols(names, seed=3)
    )


def test_a_fraction_that_cannot_make_a_proper_subsample_is_refused() -> None:
    # The feature's own way of measuring nothing, refused by name. A fraction
    # of 1.0 leaves the panel untouched (the figure would be identically zero
    # for *every* candidate, including a planted one); 0.0 and the values below
    # it empty the universe and the probe has no cross-section to score; a
    # fraction so small that fewer than two names survive has no cross-section
    # either. All three are ``TripwirePanelError`` and not a silent clamp.
    names = [f"S{index:02d}" for index in range(DEFAULT_SYMBOLS)]
    for bad in (0.0, 1.0, 1.5, -0.2):
        with pytest.raises(TripwirePanelError, match="fraction"):
            subsample_symbols(names, fraction=bad)
    # 4 names at 10% of 30 is under the two-name floor.
    with pytest.raises(TripwirePanelError, match="subsample"):
        subsample_symbols(names[:8], fraction=0.10)


def test_a_malformed_universe_is_refused_by_name() -> None:
    with pytest.raises(TripwirePanelError, match="symbol"):
        subsample_symbols(["A", ""])
    with pytest.raises(TripwirePanelError, match="twice"):
        subsample_symbols(["A", "A"])
    with pytest.raises(TripwirePanelError, match="symbol"):
        subsample_symbols("ABC")
    # ``bool`` is an ``int`` in Python, and a seed of ``True`` is a typo rather
    # than the seed 1 — refused for the reason feature 127 refuses it.
    with pytest.raises(TripwirePanelError, match="seed"):
        subsample_symbols(["A", "B", "C"], seed=True)


# -- The figure is one quantity, folded ----------------------------------------


def test_the_stability_is_the_magnitude_move_in_reference_threshold_units() -> None:
    # The arithmetic, stated once against a hand value: a drop of 0.30 in
    # surviving Sharpe measured against a reference bar of 0.15 is two bars.
    assert subsample_figure(0.40, 0.10, threshold=0.15) == pytest.approx(2.0)
    assert subsample_figure(0.10, 0.40, threshold=0.15) == pytest.approx(2.0)


def test_the_figure_is_two_sided_where_feature_127_s_is_one_sided() -> None:
    # The sign convention, pinned from the direction that matters. Feature
    # 127's degradation is a *drop* — a collapse is the failure, and an
    # improvement is a negative degradation that nothing rejects. This figure
    # is a magnitude: a re-run that moved *up* is as unstable as one that moved
    # down by the same amount, and an absolute difference is what makes that
    # true. A signed difference would report the largest possible move
    # (−x → +x) as zero.
    assert subsample_figure(0.30, -0.30, threshold=0.15) == pytest.approx(4.0)
    assert subsample_figure(0.30, -0.30, threshold=0.15) != 0.0
    assert subsample_figure(0.10, 0.40, threshold=0.15) == subsample_figure(
        0.40, 0.10, threshold=0.15
    )


def test_the_figure_is_scale_free_across_grids() -> None:
    # Standardizing by the reference run's own threshold is what makes the
    # number comparable between a 60-date probe and a 480-date one.
    for dates in (60, 120, 480):
        bar = time_shuffle_threshold(dates, level=DEFAULT_SHUFFLE_LEVEL)
        assert subsample_figure(2 * bar, bar, threshold=bar) == pytest.approx(1.0)


def test_a_bad_threshold_or_a_non_finite_statistic_is_refused_by_name() -> None:
    for bad in (0.0, -0.15):
        with pytest.raises(TripwirePanelError, match="threshold"):
            subsample_figure(0.4, 0.1, threshold=bad)
    for not_a_number in (True, None, "0.15"):
        with pytest.raises(TripwirePanelError, match="not a number"):
            subsample_figure(0.4, 0.1, threshold=not_a_number)
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(TripwirePanelError, match="finite"):
            subsample_figure(bad, 0.1, threshold=0.15)


# -- The bar: √(2(1 − √f)), level-free and grid-free ---------------------------


def test_the_default_threshold_is_the_shared_noise_bar() -> None:
    # The default is *derived*, not tuned, and the derivation turns on the one
    # fact about the two runs a reader is most likely to get wrong: they are
    # **not independent**.  The subsample's names are a subset of the
    # reference's, so every kept name contributes the *same* noise term to both
    # statistics; the shared part is proportional to the kept names and the
    # unshared part to the whole panel, so corr(reference, re-run) = √f.
    #
    # Under feature 125's null each surviving Sharpe has standard deviation
    # 1/√T over T dates, so the difference of the two has standard deviation
    # √(2(1 − √f))/√T; in units of feature 125's own threshold
    # Φ⁻¹(1 − level/2)/√T that is √(2(1 − √f))/z.  The figure is |·| — folded,
    # because stability is two-sided — so the bar is z of that, and the z
    # cancels because the figure's units already carry one.
    fraction = DEFAULT_SUBSAMPLE_FRACTION
    expected = math.sqrt(2.0 * (1.0 - math.sqrt(fraction)))
    assert DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD == pytest.approx(expected)
    assert DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD == pytest.approx(1.0515, abs=1e-4)

    # The tempting `√2` — which assumes the two runs draw *independent* noise,
    # the f → 0 limit — is asserted to be WRONG rather than close enough.  It
    # is a bar roughly 35% too wide, and the null calibration below is what
    # shows it: this feature's suite makes the same move feature 127's does
    # with its own √2 shortcut, for the same reason.
    assert DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD != pytest.approx(math.sqrt(2.0))
    assert math.sqrt(2.0) / DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD > 1.3

    # It is a *different number* from feature 127's bar, and asserting the
    # difference is the point: applying one feature's bar to the other's figure
    # is the mistake a reader is most likely to make.
    assert DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD != pytest.approx(
        DEFAULT_DEGRADATION_THRESHOLD
    )
    # ...and the structural reason `√2` cannot be right: it does not depend on
    # the fraction at all, so it would put a positive bar over a fraction of
    # 1.0 — the unperturbed panel, whose figure is identically zero for every
    # candidate.  This one vanishes exactly there, which is the limit the
    # arithmetic has to have.
    assert math.sqrt(2.0 * (1.0 - math.sqrt(1.0))) == 0.0


def test_the_bar_is_a_function_of_the_fraction_and_of_nothing_else() -> None:
    # The two absences, pinned.  `level` and `dates` both cancel — the figure is
    # measured in units of a threshold that carries each — so the constant is a
    # pure function of how much of the universe the two runs share.  A bar
    # derived as "z standard deviations of the null" would have to be recomputed
    # whenever the grid widened or the level tightened; this one does not, which
    # is what makes a 60-date campaign's figure comparable with a 480-date one's.
    for dates in (60, 120, 480):
        for level in (0.01, 0.05, 0.10):
            bar = time_shuffle_threshold(dates, level=level)
            # Standardizing a move of `bar` by `bar` is 1.0 at every
            # configuration — the figure carries no level and no date count.
            assert subsample_figure(bar, 0.0, threshold=bar) == pytest.approx(1.0)
    # ...and it *does* depend on the fraction, monotonically: a thinner
    # subsample shares less noise with the reference, so the null spreads wider
    # and the bar with it.
    bars = [
        math.sqrt(2.0 * (1.0 - math.sqrt(f)))
        for f in (0.10, 0.20, 0.30, 0.50, 0.80)
    ]
    assert bars == sorted(bars, reverse=True)
    assert bars[0] > bars[-1]


def test_the_bar_is_the_null_s_own_standard_deviation() -> None:
    # The model checked against the distribution it claims, with a fixed seed:
    # two standard normals sharing a correlation of √f have a difference of
    # standard deviation √(2(1 − √f)), and the bar is one of those — so the
    # constant is the null's own spread in the units the figure is measured in,
    # not a round number chosen for a textbook.
    import random

    fraction = DEFAULT_SUBSAMPLE_FRACTION
    shared = math.sqrt(fraction)
    rng = random.Random(DEFAULT_SUBSAMPLE_SEED)
    first = [rng.gauss(0.0, 1.0) for _ in range(400_000)]
    independent = [rng.gauss(0.0, 1.0) for _ in range(400_000)]
    # A second draw at correlation `shared` with the first.
    second = [shared * a + math.sqrt(1.0 - shared**2) * b for a, b in zip(first, independent)]
    sd = math.sqrt(math.fsum((a - b) ** 2 for a, b in zip(second, first)) / len(first))
    assert sd == pytest.approx(math.sqrt(2.0 * (1.0 - shared)), rel=0.01)
    assert DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD == pytest.approx(sd, rel=0.02)
    # ...and the same computation with *no* correlation gives √2, which is the
    # value the derivation above rejects.
    independent_sd = math.sqrt(
        math.fsum((a - b) ** 2 for a, b in zip(independent, first)) / len(first)
    )
    assert independent_sd == pytest.approx(math.sqrt(2.0), rel=0.01)
    assert independent_sd > DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD


# -- A leak moves here and not under the seed axis: the evidence ---------------


def test_a_planted_leak_is_caught_by_this_axis() -> None:
    # The tempting intuition — "a whole-panel leak is invariant to a symbol
    # subset" — is wrong, and this is the measurement that says so.  The
    # canonical planted leak carries its statistic in every symbol, but the
    # thinning drops most of the statistic's *dispersion* along with its level,
    # and the surviving Sharpe is a ratio of the two.  So the figure is large.
    scores, targets = _corpus_leak()
    reference = run_time_shuffle_tripwire(scores, targets, node_id=_NODE)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    assert verdict.stability > DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD
    assert verdict.stability_rejected is True
    assert verdict.rejected is True
    # The reference run is the probe's own, unchanged: this axis re-runs the
    # probe, it does not replace it.
    assert verdict.reference_sharpe == reference.surviving_sharpe
    # ...and the move is a *move*: the thinned run's Sharpe is not the
    # reference's, which is what makes the figure non-zero.
    assert verdict.rerun_sharpe != verdict.reference_sharpe


def test_every_corpus_leak_is_caught_here_and_invisible_to_the_seed_axis() -> None:
    # The sharpest form of the family's four-features argument, over feature
    # 133's whole maintained corpus.  Each planted leak reports
    #
    #   * a subsample figure of ≈ 1.71 — over this axis' bar, rejected — and
    #   * a seed-axis degradation of exactly 0.0, structurally zero.
    #
    # The second is not "under its bar": a whole-sample statistic does not
    # depend on *which date* a cross-section is joined against, so re-drawing
    # the derangement leaves it untouched while thinning the universe moves it a
    # great deal.  Two arrows at one target, arriving by different routes — and
    # it is the route that distinguishes the features, which is why both numbers
    # are asserted rather than only the rejection.
    from tripwires import planted_signals, run_seed_rerun

    for signal in planted_signals():
        here = run_subsample_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        there = run_seed_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        assert here.stability > DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD, signal.leak_kind
        assert here.stability_rejected is True, signal.leak_kind
        assert there.degradation == 0.0, signal.leak_kind
        assert there.degradation_rejected is False, signal.leak_kind
        # The ratio is the separation, and it is asserted as a margin rather
        # than a bare inequality: a future change that narrowed this axis into
        # the noise band fails here.
        assert here.stability / DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD > 1.5


def test_a_different_subsample_moves_the_figure(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # That the figure is measuring the *thinning* and not something else: a
    # different universe subsample is a different measurement, and a candidate
    # whose book is not evenly spread across the universe feels it.  The clean
    # candidate is the one where the two draws differ without either being
    # meaningful — which is the honest demonstration, since a candidate that
    # *did* feel it strongly would be the leak test above.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_subsample_rerun(scores, targets, node_id=_NODE)
    other = run_subsample_rerun(
        scores, targets, node_id=_NODE, subsample_seed=DEFAULT_SUBSAMPLE_SEED + 1
    )
    assert other.subsample != first.subsample
    assert other.rerun_sharpe != first.rerun_sharpe
    assert other.stability != first.stability


# -- The null: a clean candidate passes ----------------------------------------


def test_a_clean_candidate_is_the_null_the_probe_must_pass(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # An independent candidate's surviving Sharpe is noise, so it moves under
    # thinning — and the bar is wide enough that a clean candidate clears it.
    # The margin is asserted rather than the bare fact, so a future change that
    # narrowed the default into the noise band fails here.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    assert verdict.stability < DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD
    assert verdict.stability_rejected is False
    assert verdict.reference_rejected is False
    assert verdict.rerun_rejected is False
    assert verdict.rejected is False
    assert verdict.outcome == "ok"


def test_a_clean_candidate_s_false_alarm_rate_is_the_level_it_claims() -> None:
    # The calibration, measured rather than asserted — and the test that
    # falsifies the tempting `√2`.  The figure's false-alarm rate is not
    # hypothesised: it is the *null's own tail*, because the bar is derived from
    # the null rather than picked.  The figure is measured in units of a
    # threshold that carries the level, so the bar sits `z` standard deviations
    # of the null out, and the rate comes back at the level.  With the prompt's
    # wrong `√2` it would come back at ~0: a bar ~35% too wide never rejects a
    # clean candidate, which is the failure mode that matters for a removal,
    # since a probe that never fires looks exactly like a probe with nothing to
    # report.
    #
    # The rate is asserted as a band rather than a point: this is a calibration
    # check over a finite sample, not a tolerance for a flake.
    grid = monday(120)
    names = [f"S{index:02d}" for index in range(DEFAULT_SYMBOLS)]
    trials = 300
    over = 0
    for trial in range(trials):
        scores, targets = _clean_candidate(grid, names, seed=100 + 4 * trial)
        if run_subsample_rerun(scores, targets, node_id=_NODE).stability_rejected:
            over += 1
    assert 0 < over < trials // 10


# -- The verdict record --------------------------------------------------------


def test_the_verdict_carries_every_term_the_figure_was_made_from(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A rejection can poison a subtree (feature 131) and excise a pool
    # (feature 132), both irreversible, so the record must be auditable on its
    # own: the figure recomputes from the statistics it carries, the reference
    # threshold recomputes from the level and the date count, and the subsample
    # is exactly the universe the re-run saw.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE, seed=13)
    assert verdict.stability == pytest.approx(
        abs(verdict.rerun_sharpe - verdict.reference_sharpe)
        / verdict.reference_threshold
    )
    assert verdict.reference_threshold == pytest.approx(
        time_shuffle_threshold(verdict.dates, level=verdict.level)
    )
    assert set(verdict.subsample) < set(verdict.symbols)
    assert set(verdict.subsample).isdisjoint(verdict.symbols_dropped)
    assert set(verdict.subsample) | set(verdict.symbols_dropped) == set(
        verdict.symbols
    )
    assert verdict.axis == SUBSAMPLE_AXIS
    assert verdict.tripwire == PERTURBATION_STABILITY_NAME
    assert verdict.seed == 13
    assert verdict.subsample_fraction == DEFAULT_SUBSAMPLE_FRACTION
    assert verdict.subsample_seed == DEFAULT_SUBSAMPLE_SEED
    assert verdict.outcome in TRIPWIRE_OUTCOMES
    assert SUBSAMPLE_AXIS in PERTURBATION_AXES


def test_the_rejection_is_the_union_of_three_named_causes(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # §C6's rejection is over the figure and over either run's own detection.
    # A leak is caught by feature 125's comparison, which both runs make, so
    # the re-run's cause fires and the union rejects — but the verdict must not
    # report the *configured stability threshold* as the reason.
    scores, targets = _leaking_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    assert verdict.rerun_rejected is True
    assert verdict.stability_rejected is False
    assert verdict.rejected is True
    assert verdict.outcome == "tripwire_fail"


def test_the_verdict_shares_no_statistic_name_with_the_other_two_verdicts(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The seam feature 131's structural check depends on. Feature 125's probe
    # and feature 127's re-run both expose ``surviving_sharpe`` and
    # ``threshold``; a third verdict shaped like them would pass poison's
    # ten-field check and then be judged on feature 125's comparison over
    # feature 125's statistic — and for a node this feature rejects for
    # instability the candidate is typically *clean* at the reference universe,
    # so that comparison is false and the store would refuse a poisoning while
    # naming the wrong reason. So the names must not collide.
    from tripwires import SeedRerunVerdict, TimeShuffleVerdict

    own = {field.name for field in dataclasses.fields(SubsampleRerunVerdict)}
    for other in (TimeShuffleVerdict, SeedRerunVerdict):
        theirs = {field.name for field in dataclasses.fields(other)}
        statistic_bearing = theirs & {
            "surviving_sharpe",
            "threshold",
            "degradation",
        }
        assert statistic_bearing.isdisjoint(own), other.__name__
    assert {"stability", "stability_threshold"} <= own
    assert {"surviving_sharpe", "threshold", "degradation"}.isdisjoint(own)


def test_the_verdict_refuses_a_record_that_disagrees_with_itself(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The invariants are enforced at construction, so a hand-built record — or
    # one from a producer that drifted — fails loudly rather than carrying a
    # lying stability figure into a table that outlives the process.
    scores, targets = _clean_candidate(grid, symbols)
    good = run_subsample_rerun(scores, targets, node_id=_NODE)
    fields = {
        field.name: getattr(good, field.name)
        for field in dataclasses.fields(good)
    }
    # A figure that does not recompute from the terms beside it.
    with pytest.raises(TripwirePanelError, match="stability"):
        SubsampleRerunVerdict(**{**fields, "stability": good.stability + 1.0})
    # A "subsample" that is the whole universe — the proper-subset invariant.
    with pytest.raises(TripwirePanelError, match="subset"):
        SubsampleRerunVerdict(**{**fields, "subsample": fields["symbols"]})


def test_the_re_run_is_deterministic_bit_for_bit(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Two callers running the same re-run get the same verdict — the property a
    # deployment needs to compare one campaign's figure against another's.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_subsample_rerun(scores, targets, node_id=_NODE)
    second = run_subsample_rerun(scores, targets, node_id=_NODE)
    assert first == second
    assert hash(first) == hash(second)


def test_the_re_run_refuses_a_panel_it_cannot_probe() -> None:
    # The probe's own refusals propagate from the reference run, so a caller
    # sees one cause rather than two frames of the same one.
    with pytest.raises(TripwirePanelError, match="node"):
        run_subsample_rerun({}, {}, node_id="")
    # A non-integer subsample seed is refused before any panel is read, for the
    # reason feature 127 refuses one: ``True`` is an ``int`` in Python, so it
    # would silently draw seed 1.
    with pytest.raises(TripwirePanelError, match="seed"):
        run_subsample_rerun({}, {}, node_id=_NODE, subsample_seed=True)
    # ...and a fraction that cannot make a proper subsample of the panel it was
    # handed is this feature's own refusal, not the probe's — so the panel has
    # to be one the probe *can* read, or the reference run refuses first and the
    # caller sees the wrong cause.
    grid = monday(40)
    names = ["A", "B", "C"]
    targets = {1: gaussian_panel(grid, names, seed=2)}
    scores = gaussian_panel(grid, names, seed=3)
    with pytest.raises(TripwirePanelError, match="fraction"):
        run_subsample_rerun(scores, targets, node_id=_NODE, fraction=1.0)


# -- The persistence half: feature 129's own sentence --------------------------


def test_a_passing_figure_is_persisted_beside_a_failing_one(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # The half of this feature no other axis has, and where it differs from
    # feature 131's store most sharply. That store *refuses* a verdict that did
    # not reject, and rightly — there is nothing to poison. This one must not:
    # the figure is the input to the triage decision (feature 134 computes the
    # AUC of this family separating planted nulls from real signals), an AUC
    # needs both classes, and a store keeping only the rejections would train
    # the discriminator on the tail it is meant to detect.
    clean_scores, clean_targets = _clean_candidate(grid, symbols)
    passing = run_subsample_rerun(clean_scores, clean_targets, node_id=_NODE)
    assert passing.rejected is False
    record = stability_store.record(passing)
    assert record.outcome == "ok"
    assert record.rejected is False

    # The failing class lands on a *second node*, because the table's key is
    # ``(node_id, axis)``: a second row on the same node and axis would be a
    # refresh rather than a second class, which is the design working.  A
    # deployment measuring many candidates is the ordinary case, and it is the
    # one the triage figure reads.
    other = "22222222-2222-2222-2222-222222222222"
    loud_scores, loud_targets = _corpus_leak()
    failing = run_subsample_rerun(loud_scores, loud_targets, node_id=other)
    assert failing.rejected is True
    written = stability_store.record(failing, recorded_at=record.recorded_at)

    # Both classes are in the one table, told apart by ``rejected`` — which is
    # what an AUC (feature 134) needs and what feature 131's store, which
    # refuses a verdict that passed, could not provide.
    assert [stability_store.stability_of(nid, axis=SUBSAMPLE_AXIS).rejected
            for nid in (_NODE, other)] == [False, True]
    # ...and both survive a fresh store over the same file: this is a *ledger*
    # of measurements, readable without the verdicts that produced them.
    reopened = StabilityStore(stability_store.database_url)
    assert reopened.stability_of(_NODE, axis=SUBSAMPLE_AXIS).outcome == "ok"
    assert reopened.stability_of(other, axis=SUBSAMPLE_AXIS).outcome == "tripwire_fail"
    assert reopened.stability_of(other, axis=SUBSAMPLE_AXIS).stability == written.stability


def test_the_persisted_row_re_derives_its_own_figure(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # What makes a persisted figure auditable rather than merely recorded: a
    # reader holding only the row can recompute the number from the terms the
    # row itself carries, and get what was written.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    stamp = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC)
    written = stability_store.record(verdict, recorded_at=stamp)
    read = stability_store.stability_of(_NODE, axis=SUBSAMPLE_AXIS)
    assert read == written
    assert hash(read) == hash(written)
    assert read.recomputes() == pytest.approx(verdict.stability)
    assert read.stability == verdict.stability
    assert read.stability_threshold == verdict.stability_threshold
    assert read.reference_sharpe == verdict.reference_sharpe
    assert read.rerun_sharpe == verdict.rerun_sharpe
    assert read.reference_threshold == verdict.reference_threshold
    assert read.measured_dates == verdict.dates
    assert read.horizon == verdict.horizon
    assert read.seed == verdict.seed
    assert read.subsample_seed == verdict.subsample_seed
    assert read.subsample_fraction == verdict.subsample_fraction
    assert read.recorded_at == stamp
    assert read.tripwire == PERTURBATION_STABILITY_NAME
    assert read.axis == SUBSAMPLE_AXIS


def test_a_re_run_refreshes_the_row_rather_than_adding_one(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # The primary key is the decision. Re-running the same axis on the same
    # node replaces the figure it supersedes — the property that lets a crash
    # between the measurement and the write be repaired by running the feature
    # again, and the one that keeps "which perturbation moved this candidate?"
    # answerable when a branch shows three figures for one axis.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_subsample_rerun(scores, targets, node_id=_NODE)
    stamp = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC)
    stability_store.record(first, recorded_at=stamp)
    # A second re-run of the same axis, drawn differently: a different figure.
    second = run_subsample_rerun(
        scores, targets, node_id=_NODE, subsample_seed=DEFAULT_SUBSAMPLE_SEED + 3
    )
    assert second.subsample != first.subsample
    refreshed = stability_store.record(second, recorded_at=stamp)
    rows = stability_store.figures(_NODE)
    assert len(rows) == 1
    assert rows[0] == refreshed
    assert rows[0].stability == second.stability


def test_the_axis_is_the_second_half_of_the_key(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # One row per node *per perturbation*, which is why this feature owns a
    # table rather than writing 0114's single ``perturb_stability`` column:
    # §C6 declares four axes, a single REAL holds one number, and whichever ran
    # last would overwrite the others. Two axes on one node must coexist — and
    # the read refuses a third that was never measured rather than answering
    # with a default.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    written = stability_store.record(verdict)
    other = StabilityStore(stability_store.database_url)
    # A second axis, written to the same table by the same store's own writer
    # (feature 128 will do this through the same key; here it is proven
    # structurally, since the column exists for exactly this reason).
    connection = sqlite3.connect(other.path)
    with connection:
        connection.execute(
            f"INSERT INTO {STABILITY_TABLE} ({', '.join(STABILITY_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in STABILITY_COLUMNS)})",
            (
                _NODE,
                PERTURBATION_AXES[1],
                PERTURBATION_STABILITY_NAME,
                "ok",
                0,
                0.5,
                DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
                0.4,
                0.3,
                0.25,
                DEFAULT_SHUFFLE_SEED,
                None,
                None,
                None,
                verdict.horizon,
                verdict.dates,
                written.recorded_at.isoformat(),
            ),
        )
    connection.close()
    assert stability_store.axes(_NODE) == tuple(
        sorted([SUBSAMPLE_AXIS, PERTURBATION_AXES[1]])
    )
    assert len(stability_store.figures(_NODE)) == 2
    # A third axis that was never measured is refused rather than answered with
    # a default — the read that makes "this node's figure is X" and "this node
    # was never re-run on that perturbation" different sentences.
    with pytest.raises(TripwireStabilityError, match="no stability figure"):
        stability_store.stability_of(_NODE, axis=PERTURBATION_AXES[3])


def test_the_row_says_which_knob_this_axis_perturbs(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # ``rerun_seed`` is NULL and ``subsample_seed`` is set — and the NULL means
    # *this axis perturbs no such knob* rather than zero, which is the
    # absent-versus-zero distinction the member's schemas keep throughout. A
    # zero would read as a real seed.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    row = stability_store.record(verdict)
    assert row.rerun_seed is None
    assert row.subsample_seed == DEFAULT_SUBSAMPLE_SEED
    assert row.subsample_fraction == DEFAULT_SUBSAMPLE_FRACTION
    connection = sqlite3.connect(stability_store.path)
    stored = connection.execute(
        f"SELECT rerun_seed, subsample_seed, subsample_fraction FROM "
        f"{STABILITY_TABLE} WHERE node_id = ?",
        (_NODE,),
    ).fetchone()
    connection.close()
    assert stored[0] is None
    assert stored[1] == DEFAULT_SUBSAMPLE_SEED
    assert stored[2] == pytest.approx(DEFAULT_SUBSAMPLE_FRACTION)


def test_a_store_the_feature_did_not_produce_is_refused_by_name(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # The shape check, by field names rather than by ``isinstance`` — the
    # factory's scan gives one source file two class objects, so a suite that
    # also imported the package canonically cannot rely on identity (feature
    # 131's validator states the argument). A feature 125 verdict has none of
    # this feature's terms, and the refusal names them.
    scores, targets = _clean_candidate(grid, symbols)
    detection = run_time_shuffle_tripwire(scores, targets, node_id=_NODE)
    with pytest.raises(TripwireStabilityError, match="stability"):
        stability_store.record(detection)
    with pytest.raises(TripwireStabilityError, match="stability"):
        stability_store.record("not a verdict at all")


def test_the_record_refuses_an_outcome_word_that_disagrees_with_its_bit(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # The one thing a persistence must not take on trust. The outcome word is
    # the decision's own translation into §8's vocabulary, and the row is what
    # survives the in-memory value — a row whose word disagreed with its bit
    # would classify a pass at the ledger as a failure.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    with pytest.raises(TripwireStabilityError, match="outcome"):
        StabilityRecord(
            node_id=_NODE,
            axis=SUBSAMPLE_AXIS,
            tripwire=PERTURBATION_STABILITY_NAME,
            outcome="tripwire_fail",
            rejected=False,
            stability=verdict.stability,
            stability_threshold=verdict.stability_threshold,
            reference_sharpe=verdict.reference_sharpe,
            rerun_sharpe=verdict.rerun_sharpe,
            reference_threshold=verdict.reference_threshold,
            seed=verdict.seed,
            rerun_seed=None,
            subsample_fraction=verdict.subsample_fraction,
            subsample_seed=verdict.subsample_seed,
            horizon=verdict.horizon,
            measured_dates=verdict.dates,
            recorded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        )


def test_the_store_refuses_a_deployment_that_names_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The feature's sentence is "persisting", so a no-op that returned
    # successfully would report it satisfied by a deployment with nowhere to
    # write. The module-level entry point refuses by name; the *builder* stays
    # silent, because the factory builds every component on every
    # ``create_app()`` and a builder that raised would take composition down
    # for every unrelated feature.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert StabilityStore.resolve({}) is None
    with pytest.raises(TripwireStabilityError, match="DATABASE_URL"):
        record_stability(object())
    with pytest.raises(TripwireStabilityError, match="DATABASE_URL"):
        stability_of(_NODE, axis=SUBSAMPLE_AXIS)


def test_a_stability_figure_and_a_poisoning_do_not_cross(
    grid: list[dt.date],
    symbols: list[str],
    stability_store: StabilityStore,
    poison_store: PoisonStore,
) -> None:
    # The two stores write per-node facts about *one* kind of event into
    # different tables of the *same* database, and the separation is the half of
    # this feature a caller reading only the member's builder cannot see: the
    # two components resolve one variable and differ everywhere else.  The
    # fixtures share one file precisely so this is checkable — on separate files
    # neither direction could be asserted at all.
    from _trees import seed_campaign
    from tripwires import POISON_TABLE

    # Both schemas over the one file, as a deployment running both features
    # would have them.
    poison_store.ensure_schema()
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    stability_store.record(verdict)

    connection = sqlite3.connect(stability_store.path)
    counts = (
        connection.execute(f"SELECT COUNT(*) FROM {POISON_TABLE}").fetchone()[0],
        connection.execute(f"SELECT COUNT(*) FROM {STABILITY_TABLE}").fetchone()[0],
    )
    connection.close()
    assert counts == (0, 1)

    # ...and the other direction: a real poisoning on the same file leaves the
    # stability table alone. A feature-125 verdict is what a poisoning takes,
    # so the leak is the candidate whose detection is unambiguous.
    leak_scores, leak_targets = _corpus_leak()
    connection = sqlite3.connect(poison_store.path)
    tree = seed_campaign(connection)
    connection.close()
    failure = run_time_shuffle_tripwire(
        leak_scores, leak_targets, node_id=tree.root_id
    )
    assert failure.rejected is True
    poisoned_subtree = poison_store.poison(failure)
    connection = sqlite3.connect(stability_store.path)
    after = (
        connection.execute(f"SELECT COUNT(*) FROM {POISON_TABLE}").fetchone()[0],
        connection.execute(f"SELECT COUNT(*) FROM {STABILITY_TABLE}").fetchone()[0],
    )
    connection.close()
    # The poisoning wrote its own table and not one row of this feature's — the
    # separation, in the direction that matters for a replay: the stability
    # ledger is unaffected by a leak being condemned.
    assert after == (len(poisoned_subtree.node_ids), 1)
    assert after[0] > 0


def test_the_row_survives_a_fresh_store_over_the_same_file(
    grid: list[dt.date], symbols: list[str], database_url: str
) -> None:
    # The feature's sentence is about a *persisted* figure, so the proof is a
    # second process's view: a new store over the same file reads what the
    # first wrote, with no shared Python state between them.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    StabilityStore(database_url).record(verdict)
    reopened = StabilityStore(database_url)
    read = reopened.stability_of(_NODE, axis=SUBSAMPLE_AXIS)
    assert read.stability == verdict.stability
    assert read.node_id == _NODE


def test_the_schema_is_idempotent_and_spelled_in_one_place() -> None:
    # ``ensure_schema`` is public so an operator can point a member at a
    # database the orchestrator has not migrated, and every statement is
    # ``IF NOT EXISTS`` so running it twice is a no-op. The DDL and the column
    # list live in ``layout`` and are spelled once, which is what keeps the
    # write and the read from drifting apart on a column order.
    statement = stability_bootstrap_schema("sqlite")
    assert "CREATE TABLE IF NOT EXISTS" in statement
    assert STABILITY_TABLE in statement
    for column in STABILITY_COLUMNS:
        assert column in statement, column
    assert "PRIMARY KEY (node_id, axis)" in statement


def test_the_probe_suite_still_needs_no_database(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The property ``conftest`` guards by keeping every store fixture
    # non-autouse: a probe test takes no database. Feature 129 adds a *second*
    # store to this suite, and the temptation it brings is a stability figure
    # computed and persisted in one call — so the split is pinned here: the
    # re-run is a pure function of its mappings and needs nothing, while the
    # persistence refuses by name rather than finding a store it was not given.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    assert verdict.rejected is False
    assert StabilityStore.resolve({}) is None


# -- The seam: every refusal answers in this feature's vocabulary ---------------


@pytest.mark.parametrize(
    "database_url",
    ["postgresql://user@host/db", "mysql://host/db", "not-a-url", "sqlite://"],
)
def test_a_misrouted_database_url_refuses_in_this_features_words(
    database_url: str,
) -> None:
    # ``sqlite_path`` is shared with features 131 and 132 and refuses a URL it
    # cannot speak with ``TripwirePoisonError`` — 131's error, which 131's own
    # suite pins. Feature 129's callers catch *this* feature's error, because
    # the stability figure is what they asked to persist, so a misrouted
    # ``DATABASE_URL`` arriving as a poisoning error is exactly the case they
    # did not catch: the figure silently goes unrecorded and the caller takes
    # the process down with an error from a feature it never imported. The
    # check stays shared — one provenance — and only the vocabulary is
    # translated, from the original, so ``__cause__`` still names the cause.
    store = StabilityStore(database_url)
    with pytest.raises(TripwireStabilityError, match="could not be addressed") as caught:
        store.ensure_schema()
    assert isinstance(caught.value.__cause__, TripwirePoisonError)


def test_a_node_id_that_cannot_join_the_tree_refuses_here(
    database_url: str,
) -> None:
    # Same seam, the id normalizer. Every id a stability row carries joins a
    # UUID column, so the validation is not optional — but a caller reading or
    # writing a figure must be told in this feature's vocabulary.
    store = StabilityStore(database_url)
    store.ensure_schema()
    with pytest.raises(TripwireStabilityError, match="could not name its node"):
        store.figures("not-a-uuid")
    with pytest.raises(TripwireStabilityError, match="could not name its node"):
        store.stability_of("not-a-uuid", axis=SUBSAMPLE_AXIS)


def test_a_record_cannot_be_built_with_an_unusable_instant(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The instant parser is shared with 131, whose messages say *a poisoning
    # instant* — right where it was written, wrong here: this module validates
    # when a *measurement* was taken, and a caller told its stability figure
    # was refused over a poisoning would look in the wrong feature. The
    # validation is shared; the sentence is not.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_subsample_rerun(scores, targets, node_id=_NODE)
    naive = dt.datetime(2024, 1, 1)  # noqa: DTZ001 - the naive stamp is the input
    for unusable in (naive, "2024-01-01T00:00:00+00:00"):
        with pytest.raises(
            TripwireStabilityError, match="not a usable instant"
        ) as caught:
            _record_with(verdict, recorded_at=unusable)
        assert isinstance(caught.value.__cause__, TripwirePoisonError)


def _record_with(verdict: object, *, recorded_at: object) -> StabilityRecord:
    """Build the row the store would write, with ``recorded_at`` overridden.

    Goes through :class:`StabilityRecord` rather than the store so the refusal
    is the *record's*, which is where the instant is validated: the store's
    own ``record`` accepts ``None`` and stamps ``_utc_now()``, so the only way
    to hand this feature an unusable instant is through the record.
    """
    return StabilityRecord(
        node_id=verdict.node_id,
        axis=verdict.axis,
        tripwire=verdict.tripwire,
        outcome=verdict.outcome,
        rejected=verdict.rejected,
        stability=verdict.stability,
        stability_threshold=verdict.stability_threshold,
        reference_sharpe=verdict.reference_sharpe,
        rerun_sharpe=verdict.rerun_sharpe,
        reference_threshold=verdict.reference_threshold,
        seed=verdict.seed,
        rerun_seed=getattr(verdict, "rerun_seed", None),
        subsample_fraction=getattr(verdict, "subsample_fraction", None),
        subsample_seed=getattr(verdict, "subsample_seed", None),
        horizon=verdict.horizon,
        measured_dates=verdict.dates,
        recorded_at=recorded_at,
    )
