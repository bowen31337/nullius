"""Feature 128 — the window-offset re-run, against the properties it pins.

app_spec.xml: *"System re-runs a candidate from a different window start
offset, persisting the resulting stability delta."*  Feature 129's and 130's
suites open by naming the tests that keep their axes from being their
siblings restated; this one does the same for the second axis, and the
load-bearing claims are four:

* :func:`test_the_default_threshold_is_the_independent_runs_bar` — the bar is
  ``√2``, derived for **equal-length independent** runs, and the tempting
  shared-window bar of ``√(2(1 − √s))`` over the shared fraction ``s`` is
  asserted to be **wrong** rather than close enough.  The temptation here is
  feature 130's mistake (the runs *look* correlated — they share most of
  their dates) and the falsification is the same re-dating argument: the
  derangement is a pure function of the whole date list, so a slid window
  re-dates every date and the two runs share no noise at all.  The axis' own
  surprise is that the true bar carries no **offset** term either — the null
  is the same ``√2`` at a twelfth and at half the grid, and only the wrong
  derivation moves with the slide.
* :func:`test_the_false_alarm_rate_is_the_level_and_the_wrong_bar_s_isnt` —
  the calibration, measured over 300 pinned trials rather than asserted: the
  derived bar fires on clean candidates at roughly the probe's own nominal
  rate, at the pinned twelfth *and* at a quarter of the grid, while the
  shared-window bar fires on over half of them.  That second number is not a
  calibration quibble; it is a probe that rejects every second honest book.
* :func:`test_every_corpus_leak_is_window_stable_and_caught_by_the_union` —
  the corpus's whole-panel leaks are *invariant* to where the window sits
  (figure ≈ 0.24 against the 1.41 bar, a six-fold margin), so the stability
  cause does not fire; what rejects them is the union, both runs' own
  detections — while the *same* panels through feature 129's axis figure
  ≈ 1.71 and reject on the stability, through feature 130's ≈ 0.16 under its
  own bar, and through feature 127's degrade by exactly ``0.0``.  Four axes,
  four answers about one candidate: the family's argument, measured.
* :func:`test_the_figure_lands_in_the_ledger_beside_its_sibling_axis` — the
  persistence half, through feature 129's ledger rather than a store of this
  feature's own: the row is keyed ``(node_id, "window-offset")``, its three
  knob columns read ``NULL``, and it coexists with a *real* subsample row on
  the same node — the coexistence feature 129's suite could only check by
  hand-inserting a synthetic window-offset row and this test replaces with
  the verdict itself.

The leak fixtures come from :mod:`_panels`' ``gaussian_panel`` and feature
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
from _panels import DEFAULT_SYMBOLS, gaussian_panel, monday
from tripwires import (
    DEFAULT_DEGRADATION_THRESHOLD,
    DEFAULT_LOOKBACK_STABILITY_THRESHOLD,
    DEFAULT_SHUFFLE_SEED,
    DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
    DEFAULT_WINDOW_OFFSET,
    DEFAULT_WINDOW_STABILITY_THRESHOLD,
    LOOKBACK_AXIS,
    PERTURBATION_AXES,
    PERTURBATION_STABILITY_NAME,
    POISON_TABLE,
    STABILITY_TABLE,
    SUBSAMPLE_AXIS,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    WINDOW_AXIS,
    LookbackRerunVerdict,
    PoisonStore,
    StabilityStore,
    SubsampleRerunVerdict,
    TripwirePanelError,
    TripwireStabilityError,
    WindowRerunVerdict,
    record_stability,
    run_lookback_rerun,
    run_seed_rerun,
    run_subsample_rerun,
    run_time_shuffle_tripwire,
    run_window_rerun,
    stability_of,
    time_shuffle_threshold,
    window_figure,
    window_starts,
)

_NODE = "11111111-1111-1111-1111-111111111111"

_OTHER = "22222222-2222-2222-2222-222222222222"

_STAMP = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC)


def _clean_candidate(
    grid: list[dt.date], symbols: list[str], *, seed: int = 7
) -> tuple[dict, dict]:
    """A candidate with no relationship to its targets — scores, targets.

    The two panels are drawn from different streams, so they are independent by
    construction: this is the null the re-run must pass, and therefore the
    candidate whose stability figure is pure sampler noise.  The default seed
    is pinned, and pinned *lower* than the sibling suites' 3: a clean
    candidate here must clear not two probes but three (the span run that
    resolves the horizon, plus both windows' own detections), and at seed 3
    the offset window's own 1-percent probe fires — a legitimate false alarm
    of the run itself, but a fixture that rejects is a fixture the null test
    cannot use.
    """
    targets = {1: gaussian_panel(grid, symbols, seed=seed + 1)}
    scores = gaussian_panel(grid, symbols, seed=seed + 2)
    return scores, targets


def _corpus_leak() -> tuple[dict, dict]:
    """The corpus's own ``full_sample_mean`` leak — a *stable* planted leak.

    The fixture for every assertion that turns on a rejection, because its
    behaviour on this axis is not a draw: the corpus's grid and universe give
    it a figure of ≈ 0.24 against the 1.41 bar (window-stable — a whole-sample
    statistic does not care which stretch of the grid the window holds),
    rejected by *both* runs' own detections and therefore by the union.  A
    test that needs "a rejected candidate" must not be at the mercy of a panel
    that might have been stable.
    """
    from tripwires import planted_signals

    for signal in planted_signals():
        if signal.leak_kind == "full_sample_mean":
            return dict(signal.scores), dict(signal.targets)
    raise AssertionError("the corpus no longer plants a full_sample_mean leak")


def _kept(panel: dict, days: list[dt.date]) -> dict:
    """One panel cut to ``days`` — the test-side spelling of the window cut."""
    keep = set(days)
    return {day: row for day, row in panel.items() if day in keep}


# -- The slide arithmetic -------------------------------------------------------


def test_the_offset_is_the_pinned_twelfth_of_the_corpus_grid() -> None:
    # The spec's own *a different window start offset* names the move without
    # quantifying it, so the size is this feature's to pin: a tenth of the
    # corpus's 120-date grid, in bars — the same proportion feature 130's
    # pinned tenth jitters, stated as a count because a start offset is a
    # position and positions are counted, not scaled.
    assert DEFAULT_WINDOW_OFFSET == 12
    assert window_starts(120) == (12, 0)
    assert window_starts(120, offset=12, window=100) == (20, 8)
    # Deterministic in (span, offset, window): two callers naming one declared
    # window get one pair of starts, bit for bit.
    assert window_starts(120) == window_starts(120)
    # The two windows are equal-length by construction — the axis moves the
    # window's position, never its length — and the re-run ends exactly the
    # offset before the panel's newest bar, which is the sentence's own
    # definition of the perturbation.
    reference_start, rerun_start = window_starts(120)
    assert 120 - reference_start == rerun_start + (120 - reference_start) - 0
    assert rerun_start + 108 == 120 - DEFAULT_WINDOW_OFFSET
    # A declared window moves both starts together: 100 bars over a 120-date
    # grid sits 20 in from the end, and the slide puts the re-run 12 earlier
    # still.
    reference_start, rerun_start = window_starts(120, offset=12, window=100)
    assert 120 - reference_start == 100
    assert reference_start - rerun_start == 12


def test_no_declared_window_means_the_maximal_runnable_one(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The family's full-span default is structurally unavailable here — a
    # window that *is* the grid has no position to move to — so ``window=None``
    # names the maximal window the offset can slide: the span less the offset,
    # leaving exactly its own offset as lead-in.  Two consequences, both
    # pinned: the default call always runs (the corpus's own 120-date grid
    # measures two 108-bar windows, where a full-span default would refuse),
    # and a caller declaring exactly that window gets the same measurement
    # with the declaration carried as a fact about the candidate rather than
    # a second arithmetic.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE)
    assert verdict.window is None
    assert verdict.dates == len(grid) - DEFAULT_WINDOW_OFFSET == 108
    assert verdict.span == len(grid) == 120
    declared = run_window_rerun(scores, targets, node_id=_NODE, window=108)
    assert declared.reference_sharpe == verdict.reference_sharpe
    assert declared.rerun_sharpe == verdict.rerun_sharpe
    assert declared.stability == verdict.stability
    assert declared.window == 108
    # ...and on a narrower grid the same default names the same proportion of
    # lead-in, which is what keeps one campaign's figure comparable with
    # another's.
    narrow = monday(60)
    scores, targets = _clean_candidate(narrow, symbols)
    smaller = run_window_rerun(scores, targets, node_id=_NODE)
    assert smaller.dates == 60 - DEFAULT_WINDOW_OFFSET == 48
    assert smaller.span == 60


def test_an_offset_that_perturbs_nothing_is_refused_by_name() -> None:
    # The feature's own ways of measuring nothing, refused rather than
    # clamped.  An offset of 0 leaves the window where it was (the figure
    # would be identically zero for *every* candidate, including a planted
    # one); a negative offset would need history the panel has not measured
    # yet; a non-integer names no distance to move by, and a ``bool`` is an
    # ``int`` in Python, so ``True`` would silently slide by one bar.
    with pytest.raises(TripwirePanelError, match="not 0"):
        window_starts(120, offset=0)
    with pytest.raises(TripwirePanelError, match="at least one bar"):
        window_starts(120, offset=-3)
    for bad in (True, "12", 12.0, None):
        with pytest.raises(TripwirePanelError, match="integer count of bars"):
            window_starts(120, offset=bad)
    # A span that is not a count of measured dates, or is too short to shuffle
    # at all, and a declared window below two bars, are each refused for the
    # reasons the sibling axes refuse them.
    with pytest.raises(TripwirePanelError, match="count of measured dates"):
        window_starts(120.0)
    with pytest.raises(TripwirePanelError, match="at least two measured dates"):
        window_starts(1)
    with pytest.raises(TripwirePanelError, match="at least two bars"):
        window_starts(120, window=1)
    with pytest.raises(TripwirePanelError, match="count of bars or None"):
        window_starts(120, window=1.5)
    # ...and the runner's own early refusals propagate before any panel is
    # read, so a caller sees one cause rather than two frames of one.
    with pytest.raises(TripwirePanelError, match="node"):
        run_window_rerun({}, {}, node_id="")
    with pytest.raises(TripwirePanelError, match="seed"):
        run_window_rerun({}, {}, node_id=_NODE, seed=True)
    with pytest.raises(TripwirePanelError, match="not 0"):
        run_window_rerun({}, {}, node_id=_NODE, offset=0)
    with pytest.raises(TripwirePanelError, match="count of bars or None"):
        run_window_rerun({}, {}, node_id=_NODE, window=1.5)


def test_a_window_the_panel_cannot_slide_is_refused_by_name(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A declared window longer than the measured span was never the
    # candidate's to declare, and silently clamping it would measure a window
    # that was not offset because it did not exist.  A window that fits the
    # span but leaves no lead-in for the slide is the same refusal from the
    # other side: 109 bars of a 120-date grid plus a 12-bar slide needs 121
    # dates, and the grid has no position left to move the window to.
    scores, targets = _clean_candidate(grid, symbols)
    with pytest.raises(TripwirePanelError, match="longer than"):
        run_window_rerun(scores, targets, node_id=_NODE, window=len(grid) + 1)
    with pytest.raises(TripwirePanelError, match="no position left to move"):
        run_window_rerun(scores, targets, node_id=_NODE, window=109)
    with pytest.raises(TripwirePanelError, match="no position left to move"):
        run_window_rerun(scores, targets, node_id=_NODE, window=len(grid))
    # A span too short to leave the maximal window its two dates: a 13-date
    # panel under a 12-bar offset leaves one bar, and one bar has no shuffle
    # and no statistic.
    with pytest.raises(TripwirePanelError, match="under two dates"):
        window_starts(13, offset=12)


# -- The bar: √2, level-free, grid-free, offset-free -----------------------------


def test_the_default_threshold_is_the_independent_runs_bar() -> None:
    # The default is *derived*, not tuned, and the derivation turns on the
    # same fact feature 130's does, read over a slide instead of a shrink:
    # the two windows share (L − offset) of their L dates, so the runs *look*
    # correlated, but the derangement is a pure function of the whole date
    # list — sliding the window re-dates every date, and the shared panel is
    # shuffled two different ways.  Under feature 125's null the per-date
    # noise of a shuffled cross-section is fresh noise, so the two statistics
    # are independent with equal variances σ²/L: Var(ΔS) = 2σ²/L, and in
    # units of the reference run's own threshold z·σ/√L the folded figure's
    # bar at `level` is √2 — the equal-length limit feature 130's formula
    # tends to as its jitter shrinks, stated here as the whole answer.
    assert DEFAULT_WINDOW_STABILITY_THRESHOLD == pytest.approx(math.sqrt(2.0))
    assert DEFAULT_WINDOW_STABILITY_THRESHOLD == pytest.approx(1.414214, abs=1e-5)

    # The tempting shared-window bar — corr = √s over the shared fraction
    # s = (L − offset)/L — is 0.338 at the pinned twelfth over the default
    # window, and it is asserted to be WRONG rather than close enough: it is
    # a bar the true null exceeds with probability ~0.53, which is not a
    # calibration quibble but a probe that rejects every second honest book.
    # The rate test below is the measurement that says so.
    shared = (108 - DEFAULT_WINDOW_OFFSET) / 108
    wrong = math.sqrt(2.0 * (1.0 - math.sqrt(shared)))
    assert wrong == pytest.approx(0.338204, abs=1e-4)
    assert DEFAULT_WINDOW_STABILITY_THRESHOLD != pytest.approx(wrong)
    assert DEFAULT_WINDOW_STABILITY_THRESHOLD / wrong > 4.0

    # It is a *different number* from every sibling axis' bar, and asserting
    # the differences is the point: applying one feature's bar to another's
    # figure is the mistake a reader is most likely to make.  The seed axis'
    # 0.77 is included even though it judges a different quantity entirely —
    # a signed degradation, not a magnitude — because it is the number a
    # reader holding "the perturbation bar" is most likely to reach for.
    for sibling in (
        DEFAULT_DEGRADATION_THRESHOLD,
        DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
        DEFAULT_LOOKBACK_STABILITY_THRESHOLD,
    ):
        assert DEFAULT_WINDOW_STABILITY_THRESHOLD != pytest.approx(sibling)

    # The wrong bar is not wrong everywhere, and where it is right is the
    # sharpest way to state what the mistake is: at a slide equal to the
    # window (offset = L, s = 0) the two windows share no dates and even the
    # correlated derivation lands on √2 — the truth and the mistake agree at
    # the endpoint and nowhere between, because between the endpoints the
    # shared panel is real and the shared *noise* is not.
    assert math.sqrt(2.0 * (1.0 - math.sqrt(0.0))) == pytest.approx(
        DEFAULT_WINDOW_STABILITY_THRESHOLD
    )


def test_the_bar_is_a_function_of_nothing_at_all() -> None:
    # The three absences, pinned.  `level` and `dates` both cancel — the
    # figure is measured in units of a threshold that carries each — so the
    # bar is a pure constant; a bar derived as "z standard deviations of the
    # null" would have to be recomputed whenever the grid widened or the
    # level tightened; this one does not, which is what makes a 60-date
    # campaign's figure comparable with a 480-date one's.
    for dates in (60, 120, 480):
        for level in (0.01, 0.05, 0.10):
            bar = time_shuffle_threshold(dates, level=level)
            assert window_figure(bar, 0.0, threshold=bar) == pytest.approx(1.0)
    # ...and it does not depend on the offset either — the axis' own absence,
    # and the one that separates this bar from every sibling's.  The wrong
    # derivation moves with the slide (0.338 at a twelfth of the grid, 0.518
    # at a fifth, √2 at a half); the derived bar is the same √2 at all of
    # them, because the re-dating leaves the runs sharing no noise at any
    # offset.  The rate test below measures this at two offsets, not one.
    for offset in (12, 24, 60):
        shared = (120 - 2 * offset) / (120 - offset)
        assert math.sqrt(2.0 * (1.0 - math.sqrt(shared))) != pytest.approx(
            DEFAULT_WINDOW_STABILITY_THRESHOLD
        ) or offset == 60


def test_the_bar_is_the_null_s_own_standard_deviation() -> None:
    # The model checked against the distribution it claims, with a fixed seed
    # — the same move the sibling suites make.  Two independent standard
    # normals have a difference of standard deviation √2 — the bar, because
    # the bar is the null's own spread in the units the figure is measured
    # in.  The equal lengths are what make the two contributions equal; the
    # re-dating is what makes them independent.
    import random

    rng = random.Random(DEFAULT_SHUFFLE_SEED)
    first = [rng.gauss(0.0, 1.0) for _ in range(400_000)]
    independent = [rng.gauss(0.0, 1.0) for _ in range(400_000)]
    differences = [a - b for a, b in zip(first, independent)]
    sd = math.sqrt(math.fsum(d * d for d in differences) / len(differences))
    assert sd == pytest.approx(math.sqrt(2.0), rel=0.01)
    assert DEFAULT_WINDOW_STABILITY_THRESHOLD == pytest.approx(sd, rel=0.01)
    # The shared-noise construction the wrong derivation believes in — a
    # correlation of √s over the shared fraction s = 8/9, the model feature
    # 129's bar is built on and this axis's dates tempt — measured to the
    # spread it actually produces: ≈ 0.338, within a percent of the wrong
    # algebra's closed form, and a quarter of the null's true width.  That is
    # *why* it false-alarms: the null is wider than it thinks.
    shared = math.sqrt(8.0 / 9.0)
    correlated = [
        shared * a + math.sqrt(1.0 - shared**2) * b
        for a, b in zip(first, independent)
    ]
    wrong_sd = math.sqrt(
        math.fsum((a - c) ** 2 for a, c in zip(first, correlated)) / len(first)
    )
    assert wrong_sd == pytest.approx(math.sqrt(2.0 * (1.0 - math.sqrt(8.0 / 9.0))), rel=0.01)
    assert wrong_sd == pytest.approx(0.338204, rel=0.01)
    assert wrong_sd < DEFAULT_WINDOW_STABILITY_THRESHOLD / 4.0


def test_the_false_alarm_rate_is_the_level_and_the_wrong_bar_s_isnt() -> None:
    # The calibration, measured rather than asserted — and the test that
    # falsifies the shared-window bar behaviourally, at two offsets.  The
    # figure's false-alarm rate is not hypothesised: the bar is derived from
    # the null and sits `z` standard deviations of it out, so the rate comes
    # back at roughly the probe's own nominal level (asserted as a band, not
    # a point — this is a calibration check over a finite sample).  With the
    # tempting 0.338 it comes back at ~0.53: over half of all clean
    # candidates rejected, the failure mode that matters, since a probe that
    # fires on every honest book is a probe whose rejections mean nothing.
    # The second loop, at a quarter of the grid, is the offset-freedom
    # claim measured: the same √2 holds its rate where the slide doubled,
    # while the wrong bar — which moved from 0.338 to 0.518 — still fires on
    # a third of them.  Seeds are pinned, so the rates are measurements.
    grid = monday(120)
    names = [f"S{index:02d}" for index in range(DEFAULT_SYMBOLS)]
    trials = 300
    wrong = math.sqrt(2.0 * (1.0 - math.sqrt((108 - DEFAULT_WINDOW_OFFSET) / 108)))
    over = fired_wrong = 0
    for trial in range(trials):
        targets = {1: gaussian_panel(grid, names, seed=1000 + 2 * trial)}
        scores = gaussian_panel(grid, names, seed=1001 + 2 * trial)
        verdict = run_window_rerun(scores, targets, node_id=_NODE, seed=trial)
        over += verdict.stability > DEFAULT_WINDOW_STABILITY_THRESHOLD
        fired_wrong += verdict.stability > wrong
    assert 0 < over < trials // 10
    assert fired_wrong > trials // 2

    wider = math.sqrt(2.0 * (1.0 - math.sqrt((96 - 24) / 96)))
    assert wider == pytest.approx(0.517638, abs=1e-4)
    over_again = fired_wider = 0
    for trial in range(trials):
        targets = {1: gaussian_panel(grid, names, seed=1000 + 2 * trial)}
        scores = gaussian_panel(grid, names, seed=1001 + 2 * trial)
        verdict = run_window_rerun(
            scores, targets, node_id=_NODE, offset=24, seed=trial
        )
        over_again += verdict.stability > DEFAULT_WINDOW_STABILITY_THRESHOLD
        fired_wider += verdict.stability > wider
    assert over_again < trials // 10
    assert fired_wider > trials // 4


# -- The corpus's answer: window-stable leaks, caught by the union ----------------


def test_every_corpus_leak_is_window_stable_and_caught_by_the_union() -> None:
    # The measured fact about this axis' catch, over feature 133's whole
    # maintained corpus.  A whole-sample statistic does not depend on *where*
    # along the grid the window sits, so every planted leak's figure is
    # ≈ 0.24 against the 1.41 bar — under it, with a six-fold margin — and
    # the stability cause does not fire.  What fires is the union: both runs'
    # own detections reject the leak in the trailing window and in the offset
    # window alike, and the verdict reports *which* cause did the work rather
    # than laundering the rejection into a stability figure it was not.
    from tripwires import planted_signals

    for signal in planted_signals():
        verdict = run_window_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        assert verdict.stability_rejected is False, signal.leak_kind
        assert verdict.stability / DEFAULT_WINDOW_STABILITY_THRESHOLD < 0.5, (
            signal.leak_kind
        )
        assert verdict.reference_rejected is True, signal.leak_kind
        assert verdict.rerun_rejected is True, signal.leak_kind
        assert verdict.rejected is True, signal.leak_kind
        assert verdict.outcome == "tripwire_fail", signal.leak_kind
        # The perturbation is real on every one of them: two 108-bar windows
        # of a 120-date grid, the slide genuinely run and the newest twelve
        # bars genuinely absent from the re-run.
        assert verdict.dates == 108, signal.leak_kind
        assert verdict.span == 120, signal.leak_kind
        assert verdict.offset == DEFAULT_WINDOW_OFFSET, signal.leak_kind


def test_four_axes_four_answers_on_one_corpus() -> None:
    # The sharpest measured form of the family's four-axes argument, now
    # complete: the same four corpus panels through all four re-runs.  The
    # leaks are window-position-stable (figure ≈ 0.24, under this bar) and
    # universe-fragile (figure ≈ 1.71, over that one) and length-stable
    # (figure ≈ 0.16, under that one) — while feature 127's axis, which
    # moves only the derangement, sees exactly 0.0.  Four axes, four
    # different answers about one candidate, each of which a single
    # "perturbation" knob would have collapsed into one of the others.
    from tripwires import planted_signals

    for signal in planted_signals():
        here = run_window_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        thin = run_subsample_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        seed = run_seed_rerun(signal.scores, signal.targets, node_id=signal.node_id)
        length = run_lookback_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        assert here.stability < DEFAULT_WINDOW_STABILITY_THRESHOLD, signal.leak_kind
        assert here.stability_rejected is False, signal.leak_kind
        assert thin.stability > DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD, signal.leak_kind
        assert thin.stability_rejected is True, signal.leak_kind
        assert length.stability < DEFAULT_LOOKBACK_STABILITY_THRESHOLD, signal.leak_kind
        assert length.stability_rejected is False, signal.leak_kind
        assert seed.degradation == 0.0, signal.leak_kind
        assert seed.degradation_rejected is False, signal.leak_kind
        # The subsample margin, asserted as a margin rather than a bare
        # inequality: a future change that narrowed that axis into the noise
        # band fails there, and one that widened this axis fails here.
        assert thin.stability / DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD > 1.5


def test_the_reference_run_is_a_trailing_window_not_the_span(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # This axis re-runs the probe; it does not replace it — but unlike every
    # sibling, its reference is *never* the full-span run, whatever is
    # declared: an offset window is by construction a strict sub-window of
    # the span, because the slide needs its own offset in lead-in.  The
    # reference is feature 125's own probe over the trailing window, and the
    # re-run is the same probe over the window started twelve bars earlier —
    # recomputed here from first principles, over panels the test cuts
    # itself, so the agreement is with the probe and not with this module's
    # own cutter.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE, seed=13)
    span = run_time_shuffle_tripwire(scores, targets, node_id=_NODE, seed=13)
    assert verdict.horizon == span.horizon
    assert verdict.seed == span.seed == 13
    assert verdict.reference_sharpe != span.surviving_sharpe
    assert verdict.reference_threshold == pytest.approx(
        time_shuffle_threshold(108, level=verdict.level)
    )
    assert verdict.reference_threshold != span.threshold
    reference = run_time_shuffle_tripwire(
        _kept(scores, grid[-108:]),
        {1: _kept(targets[1], grid[-108:])},
        node_id=_NODE,
        seed=13,
    )
    assert verdict.reference_sharpe == reference.surviving_sharpe
    assert verdict.reference_rejected is reference.rejected
    rerun = run_time_shuffle_tripwire(
        _kept(scores, grid[:108]),
        {1: _kept(targets[1], grid[:108])},
        node_id=_NODE,
        seed=13,
    )
    assert verdict.rerun_sharpe == rerun.surviving_sharpe
    assert verdict.rerun_rejected is rerun.rejected
    # ...and the re-run over the offset window is a genuinely different
    # measurement, which is what makes the figure non-zero.
    assert verdict.rerun_sharpe != verdict.reference_sharpe


# -- The null: a clean candidate passes -----------------------------------------


def test_a_clean_candidate_is_the_null_the_probe_must_pass(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # An independent candidate's surviving Sharpe is noise, so it moves under
    # the slide — and the bar is derived from that null, so a clean candidate
    # clears it, through all three of the probes the feature runs.  The
    # margin is asserted rather than the bare fact, so a future change that
    # narrowed the default into the noise band fails here.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE)
    assert verdict.stability < DEFAULT_WINDOW_STABILITY_THRESHOLD / 2.0
    assert verdict.stability_rejected is False
    assert verdict.reference_rejected is False
    assert verdict.rerun_rejected is False
    assert verdict.rejected is False
    assert verdict.outcome == "ok"


def test_a_different_offset_is_a_different_measurement(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # That the figure is measuring the *window's position* and not something
    # else: a different offset is a different window and a different
    # derangement, so the re-run's statistic and the figure both move.  The
    # clean candidate is the honest demonstration — a candidate that *did*
    # feel the slide strongly would be exactly the recency-dependence this
    # axis exists to catch, and the corpus test above is where the opposite
    # behaviour is measured.
    scores, targets = _clean_candidate(grid, symbols)
    twelfth = run_window_rerun(scores, targets, node_id=_NODE)
    fifth = run_window_rerun(scores, targets, node_id=_NODE, offset=24)
    assert fifth.dates != twelfth.dates
    assert fifth.rerun_sharpe != twelfth.rerun_sharpe
    assert fifth.stability != twelfth.stability


def test_the_re_run_is_deterministic_bit_for_bit(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Two callers running the same re-run get the same verdict — the property
    # a deployment needs to compare one campaign's figure against another's,
    # and the reason the verdict carries no wall-clock field at all.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_window_rerun(scores, targets, node_id=_NODE)
    second = run_window_rerun(scores, targets, node_id=_NODE)
    assert first == second
    assert hash(first) == hash(second)


# -- The verdict record ---------------------------------------------------------


def test_the_verdict_carries_every_term_the_figure_was_made_from(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A rejection can poison a subtree (feature 131) and excise a pool
    # (feature 132), both irreversible, so the record must be auditable on its
    # own: the figure recomputes from the statistics it carries, the
    # reference threshold recomputes from the level and the date count, and
    # the slide recomputes from the span, the offset and the declaration
    # together.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE, seed=13)
    assert verdict.stability == pytest.approx(
        abs(verdict.rerun_sharpe - verdict.reference_sharpe)
        / verdict.reference_threshold
    )
    assert verdict.reference_threshold == pytest.approx(
        time_shuffle_threshold(verdict.dates, level=verdict.level)
    )
    assert window_starts(verdict.span, offset=verdict.offset, window=verdict.window) == (
        verdict.span - verdict.dates,
        verdict.span - verdict.dates - verdict.offset,
    )
    assert verdict.window is None
    assert verdict.offset == DEFAULT_WINDOW_OFFSET
    assert verdict.span == len(grid)
    assert verdict.axis == WINDOW_AXIS
    assert WINDOW_AXIS == PERTURBATION_AXES[1] == "window-offset"
    assert verdict.tripwire == PERTURBATION_STABILITY_NAME
    assert verdict.seed == 13
    assert verdict.outcome in TRIPWIRE_OUTCOMES


def test_the_knobs_this_axis_does_not_move_read_absent(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # This axis holds the seed and the universe fixed and moves the window's
    # position alone, and the record says so the way the member's schemas say
    # everything absent: ``None``, not zero.  The three are *properties*
    # rather than fields — not per-verdict values a caller could set but
    # constants about the axis — which is what lets the stability ledger's
    # writer (``record_stability``, which reads any axis' verdict) accept
    # this one unchanged and write its knobs as NULL.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE)
    assert verdict.rerun_seed is None
    assert verdict.subsample_seed is None
    assert verdict.subsample_fraction is None
    field_names = {field.name for field in dataclasses.fields(WindowRerunVerdict)}
    assert {"rerun_seed", "subsample_seed", "subsample_fraction"}.isdisjoint(
        field_names
    )


def test_the_verdict_shares_no_statistic_name_with_the_other_verdicts(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The seam feature 131's structural check depends on. Feature 125's probe
    # and feature 127's re-run both expose ``surviving_sharpe`` and
    # ``threshold``; a fifth verdict shaped like them would pass poison's
    # field check and then be judged on feature 125's comparison over feature
    # 125's statistic. The stability names, by contrast, are shared with
    # features 129's and 130's verdicts *on purpose* — the three records
    # carry the same quantity in the same units, and the ledger's writer
    # reads any of them — while the axis vocabulary stays disjoint, so no
    # reader can mistake which perturbation a record reports.
    from tripwires import SeedRerunVerdict, TimeShuffleVerdict

    own = {field.name for field in dataclasses.fields(WindowRerunVerdict)}
    for other in (TimeShuffleVerdict, SeedRerunVerdict):
        theirs = {field.name for field in dataclasses.fields(other)}
        statistic_bearing = theirs & {
            "surviving_sharpe",
            "threshold",
            "degradation",
        }
        assert statistic_bearing.isdisjoint(own), other.__name__
    assert {"surviving_sharpe", "threshold", "degradation"}.isdisjoint(own)
    for other in (SubsampleRerunVerdict, LookbackRerunVerdict):
        theirs = {field.name for field in dataclasses.fields(other)}
        assert {"stability", "stability_threshold"} <= own
        assert {"reference_sharpe", "rerun_sharpe", "reference_threshold"} <= own & theirs
    # The slide's own vocabulary is this record's alone: the two window axes
    # must not be able to borrow each other's knobs, and neither magnitude
    # sibling has a position to declare.
    assert {"window", "offset", "span"}.isdisjoint(
        {field.name for field in dataclasses.fields(SubsampleRerunVerdict)}
    )
    assert {"window", "offset", "span"}.isdisjoint(
        {field.name for field in dataclasses.fields(LookbackRerunVerdict)}
    )
    assert {"lookback", "jitter", "jittered_lookback"}.isdisjoint(own)
    assert {
        "subsample",
        "symbols",
        "symbols_dropped",
        "subsample_seed",
        "subsample_fraction",
    }.isdisjoint(own)


def test_the_verdict_refuses_a_record_that_disagrees_with_itself(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The invariants are enforced at construction, so a hand-built record — or
    # one from a producer that drifted — fails loudly rather than carrying a
    # lying stability figure into a ledger that outlives the process.
    scores, targets = _clean_candidate(grid, symbols)
    good = run_window_rerun(scores, targets, node_id=_NODE)
    fields = {
        field.name: getattr(good, field.name)
        for field in dataclasses.fields(good)
    }
    # A figure that does not recompute from the terms beside it.
    with pytest.raises(TripwirePanelError, match="stability"):
        WindowRerunVerdict(**{**fields, "stability": good.stability + 1.0})
    # A span whose own arithmetic names a different window than the record
    # claims to have measured.
    with pytest.raises(TripwirePanelError, match="reference window measured"):
        WindowRerunVerdict(**{**fields, "span": good.span - 1})
    # A declared window the reference run did not measure.
    with pytest.raises(TripwirePanelError, match="declares a window"):
        WindowRerunVerdict(**{**fields, "window": good.dates - 1})
    # An offset that perturbs nothing.
    with pytest.raises(TripwirePanelError, match="not 0"):
        WindowRerunVerdict(**{**fields, "offset": 0})
    # Another axis's vocabulary, and the probe's own name.
    with pytest.raises(TripwirePanelError, match="axis"):
        WindowRerunVerdict(**{**fields, "axis": SUBSAMPLE_AXIS})
    with pytest.raises(TripwirePanelError, match="perturbation-stability"):
        WindowRerunVerdict(**{**fields, "tripwire": TIME_SHUFFLE_NAME})
    # A decision that is not the disjunction of the causes it carries.
    with pytest.raises(TripwirePanelError, match="causes"):
        WindowRerunVerdict(**{**fields, "rejected": not good.rejected})


# -- The persistence half: feature 128's own sentence ---------------------------


def test_the_figure_lands_in_the_ledger_beside_its_sibling_axis(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # The sentence's second half, literally: the delta is *persisted*, and the
    # place it persists to is feature 129's ledger — no store of this
    # feature's own, because a table keyed ``(node_id, axis)`` was already the
    # right shape for a second axis.  The structural check that accepts a
    # verdict was written a feature before this verdict existed; this test is
    # the proof it reads the new one: the row lands keyed on ``window-offset``,
    # with the three knobs this axis does not move written NULL — the ledger's
    # own spelling of *this axis perturbs no such knob*, where a zero would
    # read as a real seed.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE)
    row = record_stability(verdict, store=stability_store)
    assert row.node_id == _NODE
    assert row.axis == WINDOW_AXIS
    assert row.tripwire == PERTURBATION_STABILITY_NAME
    assert row.stability == verdict.stability
    assert row.outcome == "ok"
    assert row.rerun_seed is None
    assert row.subsample_seed is None
    assert row.subsample_fraction is None
    # ...and the row re-derives its own figure from the terms it carries:
    # what makes a persisted figure auditable rather than merely recorded.
    # Read through the fixture's store — the module-level spelling resolves
    # ``DATABASE_URL`` and this test pins the file it wrote to, not the
    # environment's.
    read = stability_store.stability_of(_NODE, axis=WINDOW_AXIS)
    assert read == row
    assert hash(read) == hash(row)
    assert read.recomputes() == pytest.approx(verdict.stability)
    assert read.reference_sharpe == verdict.reference_sharpe
    assert read.rerun_sharpe == verdict.rerun_sharpe
    assert read.reference_threshold == verdict.reference_threshold
    assert read.stability_threshold == verdict.stability_threshold
    assert read.measured_dates == verdict.dates == 108
    assert read.horizon == verdict.horizon
    assert read.seed == verdict.seed
    # Read past the store's API: the three knob columns hold NULL, exactly.
    connection = sqlite3.connect(stability_store.path)
    stored = connection.execute(
        f"SELECT rerun_seed, subsample_seed, subsample_fraction FROM "
        f"{STABILITY_TABLE} WHERE node_id = ?",
        (_NODE,),
    ).fetchone()
    count = connection.execute(
        f"SELECT COUNT(*) FROM {STABILITY_TABLE}"
    ).fetchone()[0]
    connection.close()
    assert stored == (None, None, None)
    assert count == 1
    assert stability_store.axes(_NODE) == (WINDOW_AXIS,)


def test_two_axes_on_one_node_coexist_in_the_ledger(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # One row per node *per perturbation* — the half of the key feature 129
    # could only prove structurally, by hand-inserting a synthetic
    # window-offset row next to a real subsample one ("feature 128 will do
    # this through the same key").  This feature now has, so the coexistence
    # is checked with two real verdicts through the same writer: a node
    # measured on both axes carries both figures side by side, neither
    # overwriting the other, and the read refuses a third axis that was never
    # measured rather than answering with a default.
    scores, targets = _clean_candidate(grid, symbols)
    here = run_window_rerun(scores, targets, node_id=_NODE)
    thin = run_subsample_rerun(scores, targets, node_id=_NODE)
    record_stability(here, store=stability_store)
    record_stability(thin, store=stability_store)
    assert stability_store.axes(_NODE) == tuple(sorted([WINDOW_AXIS, SUBSAMPLE_AXIS]))
    assert len(stability_store.figures(_NODE)) == 2
    assert stability_store.stability_of(_NODE, axis=WINDOW_AXIS).stability == here.stability
    assert (
        stability_store.stability_of(_NODE, axis=SUBSAMPLE_AXIS).stability
        == thin.stability
    )
    with pytest.raises(TripwireStabilityError, match="no stability figure"):
        stability_store.stability_of(_NODE, axis=LOOKBACK_AXIS)


def test_a_re_measurement_refreshes_in_place(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # The primary key is the decision, as for every axis in the ledger.
    # Re-running the same node on this axis at a different offset replaces
    # the figure it supersedes rather than adding a row — the property that
    # lets a crash between the measurement and the write be repaired by
    # running the feature again, and the one that keeps "which perturbation
    # moved this candidate?" answerable when a branch shows several figures.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_window_rerun(scores, targets, node_id=_NODE)
    second = run_window_rerun(scores, targets, node_id=_NODE, offset=24)
    assert second.dates != first.dates
    assert second.stability != first.stability
    record_stability(first, store=stability_store, recorded_at=_STAMP)
    refreshed = record_stability(second, store=stability_store, recorded_at=_STAMP)
    rows = stability_store.figures(_NODE)
    assert len(rows) == 1
    assert rows[0] == refreshed
    assert rows[0].stability == second.stability


def test_a_passing_figure_is_persisted_beside_a_failing_one(
    grid: list[dt.date], symbols: list[str], stability_store: StabilityStore
) -> None:
    # The half of this feature no other kind of tripwire store has: the
    # figure is a *measurement*, taken whether or not anything failed, and a
    # ledger keeping only rejections would read as a failure flag rather
    # than a stability record — and would starve the triage figure (feature
    # 134) of the class it needs.  The failing class lands on a second node,
    # because the table's key is ``(node_id, axis)``.
    clean_scores, clean_targets = _clean_candidate(grid, symbols)
    passing = run_window_rerun(clean_scores, clean_targets, node_id=_NODE)
    assert passing.rejected is False
    record_stability(passing, store=stability_store, recorded_at=_STAMP)

    loud_scores, loud_targets = _corpus_leak()
    failing = run_window_rerun(loud_scores, loud_targets, node_id=_OTHER)
    assert failing.rejected is True
    written = record_stability(failing, store=stability_store, recorded_at=_STAMP)

    # Both classes are in the one table, told apart by ``rejected`` — and
    # both survive a fresh store over the same file: this is a *ledger* of
    # measurements, readable without the verdicts that produced them.
    reopened = StabilityStore(stability_store.database_url)
    assert reopened.stability_of(_NODE, axis=WINDOW_AXIS).outcome == "ok"
    assert reopened.stability_of(_NODE, axis=WINDOW_AXIS).recorded_at == _STAMP
    other = reopened.stability_of(_OTHER, axis=WINDOW_AXIS)
    assert other.outcome == "tripwire_fail"
    assert other.stability == written.stability == failing.stability


def test_a_stability_figure_and_a_poisoning_do_not_cross(
    grid: list[dt.date],
    symbols: list[str],
    stability_store: StabilityStore,
    poison_store: PoisonStore,
) -> None:
    # The two stores write per-node facts about different kinds of events
    # into different tables of the *same* database, and the fixtures share
    # one file precisely so that non-crossing is checkable rather than
    # assumed — on separate files neither direction could be asserted at
    # all.  This axis adds nothing to the seam but a second writer on the
    # ledger's side, and the separation is what keeps a condemnation from
    # reading as a measurement.
    from _trees import seed_campaign

    poison_store.ensure_schema()
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE)
    record_stability(verdict, store=stability_store)

    connection = sqlite3.connect(stability_store.path)
    counts = (
        connection.execute(f"SELECT COUNT(*) FROM {POISON_TABLE}").fetchone()[0],
        connection.execute(f"SELECT COUNT(*) FROM {STABILITY_TABLE}").fetchone()[0],
    )
    connection.close()
    assert counts == (0, 1)

    # ...and the other direction: a real poisoning on the same file leaves
    # the stability table alone. A feature-125 verdict is what a poisoning
    # takes, so the leak is the candidate whose detection is unambiguous.
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
    # The poisoning wrote its own table and not one row of the ledger's — the
    # separation, in the direction that matters for a replay: the stability
    # ledger is unaffected by a leak being condemned.
    assert after == (len(poisoned_subtree.node_ids), 1)
    assert after[0] > 0


def test_the_row_survives_a_fresh_store_over_the_same_file(
    grid: list[dt.date], symbols: list[str], database_url: str
) -> None:
    # The sentence is about a *persisted* delta, so the proof is a second
    # process's view: a new store over the same file reads what the first
    # wrote, with no shared Python state between them.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE)
    StabilityStore(database_url).record(verdict)
    reopened = StabilityStore(database_url)
    read = reopened.stability_of(_NODE, axis=WINDOW_AXIS)
    assert read.stability == verdict.stability
    assert read.node_id == _NODE
    assert read.axis == WINDOW_AXIS


def test_the_store_refuses_a_deployment_that_names_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sentence is "persisting", so a no-op that returned successfully
    # would report it satisfied by a deployment with nowhere to write. The
    # module-level entry points refuse by name; the *builder* stays silent,
    # because the factory builds every registered component on every
    # ``create_app()`` and a builder that raised would take composition down
    # for every unrelated feature.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert StabilityStore.resolve({}) is None
    with pytest.raises(TripwireStabilityError, match="DATABASE_URL"):
        record_stability(object())
    with pytest.raises(TripwireStabilityError, match="DATABASE_URL"):
        stability_of(_NODE, axis=WINDOW_AXIS)


def test_the_probe_suite_still_needs_no_database(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The property ``conftest`` guards by keeping every store fixture
    # non-autouse: a probe test takes no database. This feature's temptation
    # is the specific one the second axis brings — a verdict the *ledger*
    # already knows how to persist — so the split is pinned here: the re-run
    # is a pure function of its mappings and needs nothing, while the
    # persistence refuses by name rather than finding a store it was not
    # given.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_window_rerun(scores, targets, node_id=_NODE)
    assert verdict.rejected is False
    assert StabilityStore.resolve({}) is None
