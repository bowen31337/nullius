"""Feature 130 — the lookback-jitter re-run, against the properties it pins.

app_spec.xml: *"System jitters a declared lookback by plus or minus 10
percent, persisting perturbation_stability as a node metric."*  Feature 129's
suite opens by naming the tests that keep its axis from being feature 125
restated; this one does the same for the fourth axis and the second half of
the sentence, and the load-bearing claims are four:

* :func:`test_the_default_threshold_is_the_independent_runs_bar` — the bar is
  ``√(1 + 1/(1 + jitter))``, derived for **independent** runs, and the
  tempting shared-window bar of exactly ``1/3`` is asserted to be **wrong**
  rather than close enough.  The derivation turns on the one fact about the
  two runs a reader is most likely to get wrong, and it is the *opposite*
  fact from feature 129's: there, the tempting mistake was to write the runs
  as independent when the shared universe made them correlated; here it is to
  write them as correlated when the shuffle makes them independent — the
  derangement is a pure function of the whole date list, so a truncated
  window re-dates every date and the two runs share no noise at all.
* :func:`test_the_false_alarm_rate_is_the_level_and_the_wrong_bar_s_isnt` —
  the calibration, measured over 300 pinned trials rather than asserted: the
  derived bar fires on clean candidates at roughly the probe's own nominal
  rate, while the ``1/3`` bar fires on over half of them.  That second number
  is not a calibration quibble; it is a probe that rejects every second
  honest book.
* :func:`test_every_corpus_leak_is_window_stable_and_caught_by_the_union` —
  the corpus's whole-panel leaks are *invariant* to which dates the window
  holds (figure ≈ 0.16 against the 1.45 bar, a nine-fold margin), so the
  stability cause does not fire; what rejects them is the union, both runs'
  own detections — while the *same* panels through feature 129's axis figure
  ≈ 1.71 and reject on the stability, and through feature 127's degrade by
  exactly ``0.0``.  Two magnitude axes, opposite verdicts on one corpus: the
  sharpest measured form the family's four-features argument takes.
* :func:`test_a_node_the_tree_does_not_hold_is_refused_and_the_ledger_s_isnt`
  — the persistence half's own decision, the deliberate opposite of feature
  129's stance: a column write is an ``UPDATE`` against a row another feature
  owns, so a node the tree does not hold is refused by name here while the
  ledger accepts the same verdict, because a figure is legitimately known
  before the tree is handed the node.

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
import uuid
from pathlib import Path

import pytest
from _panels import DEFAULT_SYMBOLS, gaussian_panel, monday
from tripwires import (
    DATABASE_URL_ENV,
    DEFAULT_LOOKBACK_JITTER,
    DEFAULT_LOOKBACK_STABILITY_THRESHOLD,
    DEFAULT_SHUFFLE_SEED,
    DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
    LOOKBACK_AXIS,
    NODE_METRIC_COLUMN,
    NODE_METRIC_COMPONENT_NAME,
    PERTURBATION_AXES,
    PERTURBATION_STABILITY_NAME,
    POISON_TABLE,
    STABILITY_TABLE,
    SUBSAMPLE_AXIS,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    LookbackRerunVerdict,
    NodeMetricStore,
    StabilityStore,
    SubsampleRerunVerdict,
    TripwireNodeMetricError,
    TripwirePanelError,
    TripwirePoisonError,
    jittered_lookback,
    lookback_figure,
    lookback_stability_threshold,
    node_bootstrap_schema,
    node_metric_of,
    record_node_metric,
    record_stability,
    run_lookback_rerun,
    run_subsample_rerun,
    run_time_shuffle_tripwire,
    time_shuffle_threshold,
)

_NODE = "11111111-1111-1111-1111-111111111111"

_STAMP = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC)


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


def _corpus_leak() -> tuple[dict, dict]:
    """The corpus's own ``full_sample_mean`` leak — a *stable* planted leak.

    The fixture for every assertion that turns on a rejection, because its
    behaviour on this axis is not a draw: the corpus's grid and universe give
    it a figure of ≈ 0.16 against the 1.45 bar (window-stable — a whole-sample
    statistic does not care which dates the window holds), rejected by *both*
    runs' own detections and therefore by the union.  A test that needs "a
    rejected candidate" must not be at the mercy of a panel that might have
    been stable.
    """
    from tripwires import planted_signals

    for signal in planted_signals():
        if signal.leak_kind == "full_sample_mean":
            return dict(signal.scores), dict(signal.targets)
    raise AssertionError("the corpus no longer plants a full_sample_mean leak")


def _seeded(store: NodeMetricStore):
    """The store's own database, holding a discovery tree — the tree.

    ``seed_campaign``'s chain (root, child, leaf, plus an unrelated sibling
    root in the same campaign) is the shape feature 131's suite builds; here it
    is what a column write needs and a ledger write does not — a *row to
    update* — so both halves of that contrast have the same input to work on.
    """
    from _trees import seed_campaign

    store.ensure_schema()
    connection = sqlite3.connect(store.path)
    tree = seed_campaign(connection)
    connection.close()
    return tree


def _column_of(store: NodeMetricStore, node_id: str) -> object:
    """The raw ``perturb_stability`` cell, read past the store's API."""
    connection = sqlite3.connect(store.path)
    value = connection.execute(
        f"SELECT {NODE_METRIC_COLUMN} FROM node WHERE id = ?", (node_id,)
    ).fetchone()[0]
    connection.close()
    return value


# -- The jitter arithmetic ------------------------------------------------------


def test_the_jitter_is_the_pinned_tenth_of_the_declared_window() -> None:
    # The spec's own "plus or minus 10 percent", pinned as a constant *and* as
    # behaviour.  The default is the minus side, and that is a decision rather
    # than a coin: a shorter trailing window of a window the panel already
    # measured exists by construction, while the plus side needs history the
    # panel may not carry.
    assert DEFAULT_LOOKBACK_JITTER == -0.10
    assert jittered_lookback(120) == 108
    assert jittered_lookback(120, jitter=0.10) == 132
    assert jittered_lookback(100, jitter=0.10) == 110
    assert jittered_lookback(100, jitter=-0.20) == 80
    # Deterministic in (lookback, jitter): two callers naming one declared
    # lookback get one jittered one, bit for bit.
    assert jittered_lookback(120) == jittered_lookback(120)


def test_the_jitter_is_taken_on_the_declared_window_not_the_panel(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The perturbation is a function of the *declared* lookback, so a caller
    # declaring 100 bars over a 120-date panel is jittered to 90 and 110 —
    # not to 108 and 132.  The declared window is the reference; the panel is
    # only the panel.
    scores, targets = _clean_candidate(grid, symbols)
    minus = run_lookback_rerun(scores, targets, node_id=_NODE, lookback=100)
    assert minus.dates == 100
    assert minus.lookback == 100
    assert minus.jittered_lookback == 90
    plus = run_lookback_rerun(
        scores, targets, node_id=_NODE, lookback=100, jitter=0.10
    )
    assert plus.jittered_lookback == 110
    assert plus.dates == 100


def test_no_declared_lookback_means_the_panel_s_own_full_span(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # ``lookback=None`` is not a smaller default: it means the candidate
    # declared everything it was handed, which makes the reference run
    # exactly feature 125's probe over the panels as handed in — the same
    # reference features 127 and 129 re-run, so the four axes' figures are
    # measured against one number.
    scores, targets = _clean_candidate(grid, symbols)
    full = run_lookback_rerun(scores, targets, node_id=_NODE, seed=5)
    span = run_time_shuffle_tripwire(scores, targets, node_id=_NODE, seed=5)
    assert full.lookback is None
    assert full.dates == span.dates == len(grid)
    assert full.reference_sharpe == span.surviving_sharpe
    assert full.reference_threshold == span.threshold
    assert full.reference_rejected == span.rejected
    # ...and the span and the declared-equal window are the *same* reference:
    # a caller declaring exactly the measured span gets the same measurement,
    # with the declaration carried as a fact about the candidate rather than
    # a second arithmetic.
    declared = run_lookback_rerun(
        scores, targets, node_id=_NODE, seed=5, lookback=len(grid)
    )
    assert declared.reference_sharpe == full.reference_sharpe
    assert declared.rerun_sharpe == full.rerun_sharpe
    assert declared.stability == full.stability
    assert declared.lookback == len(grid)


def test_a_jitter_that_perturbs_nothing_is_refused_by_name() -> None:
    # The feature's own ways of measuring nothing, refused rather than
    # clamped.  A jitter of 0 leaves the window untouched (the figure would be
    # identically zero for *every* candidate, including a planted one); a
    # jitter that rounds back to the declared count — 3 bars at the pinned
    # tenth is 2.7, which rounds home — has perturbed nothing; a jittered
    # count under two has no shuffle and no statistic; a jitter at or past
    # −100 percent annihilates the window.
    with pytest.raises(TripwirePanelError, match="not 0"):
        jittered_lookback(120, jitter=0.0)
    with pytest.raises(TripwirePanelError, match="declared lookback again"):
        jittered_lookback(3, jitter=-0.10)
    with pytest.raises(TripwirePanelError, match="under two dates"):
        jittered_lookback(2, jitter=-0.50)
    with pytest.raises(TripwirePanelError, match="greater than -1"):
        jittered_lookback(120, jitter=-1.0)
    with pytest.raises(TripwirePanelError, match="greater than -1"):
        jittered_lookback(120, jitter=-1.5)
    # A non-number jitter, a ``bool`` (an ``int`` in Python, so ``True`` would
    # silently jitter by +100 percent), a NaN, and a non-integer count are
    # each refused for the reason feature 127's suite refuses them.
    for bad in (True, "0.1", None):
        with pytest.raises(TripwirePanelError, match="number"):
            jittered_lookback(120, jitter=bad)
    with pytest.raises(TripwirePanelError, match="finite"):
        jittered_lookback(120, jitter=math.nan)
    with pytest.raises(TripwirePanelError, match="count of bars"):
        jittered_lookback(120.0)
    with pytest.raises(TripwirePanelError, match="at least two bars"):
        jittered_lookback(1)
    # The bar refuses the same jitters, for the reason the constant's comment
    # gives: a bar derived over a jitter this feature cannot run is a number
    # nothing will ever be judged against.
    for bad in (0.0, -1.0, math.inf, math.nan, True):
        with pytest.raises(TripwirePanelError):
            lookback_stability_threshold(bad)


def test_a_window_the_panel_cannot_fill_is_refused_by_name(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A declared lookback longer than the measured span was never the
    # candidate's to declare, and silently clamping it to the span would
    # measure a lookback that was not jittered because it did not exist.
    # The plus side of the tenth over the *whole* panel is the same refusal:
    # 132 bars of a 120-bar panel is history the panel does not carry — the
    # reason the default jitter is the minus side.
    scores, targets = _clean_candidate(grid, symbols)
    with pytest.raises(TripwirePanelError, match="longer than"):
        run_lookback_rerun(scores, targets, node_id=_NODE, lookback=len(grid) + 1)
    with pytest.raises(TripwirePanelError, match="history beyond"):
        run_lookback_rerun(scores, targets, node_id=_NODE, jitter=0.10)
    with pytest.raises(TripwirePanelError, match="at least two bars"):
        run_lookback_rerun(scores, targets, node_id=_NODE, lookback=1)
    # ...and the re-run's own early refusals propagate before any panel is
    # read, so a caller sees one cause rather than two frames of one.
    with pytest.raises(TripwirePanelError, match="node"):
        run_lookback_rerun({}, {}, node_id="")
    with pytest.raises(TripwirePanelError, match="seed"):
        run_lookback_rerun({}, {}, node_id=_NODE, seed=True)
    with pytest.raises(TripwirePanelError, match="count of bars"):
        run_lookback_rerun({}, {}, node_id=_NODE, lookback=1.5)


# -- The bar: √(1 + 1/(1 + jitter)), level-free and grid-free --------------------


def test_the_default_threshold_is_the_independent_runs_bar() -> None:
    # The default is *derived*, not tuned, and the derivation turns on the one
    # fact about the two runs a reader is most likely to get wrong — which is
    # the opposite fact from feature 129's.  There the runs *look* independent
    # (two probes) but share their noise (one universe); here they *look*
    # correlated (90 percent of their dates are the same dates) but share
    # none, because the derangement is a pure function of the whole date list:
    # truncating the window re-dates every date, and the shared panel is
    # shuffled two different ways.  Under feature 125's null the per-date
    # noise of a shuffled cross-section is fresh noise, so the two statistics
    # are independent:  Var(S_ref) = σ²/L,  Var(S_rerun) = σ²/L′,  and in
    # units of the reference run's own threshold the folded figure's bar is
    # √(1 + 1/(1 + jitter)) — at the pinned tenth, √(19/9) ≈ 1.4530.
    expected = math.sqrt(1.0 + 1.0 / (1.0 + DEFAULT_LOOKBACK_JITTER))
    assert DEFAULT_LOOKBACK_STABILITY_THRESHOLD == pytest.approx(expected)
    assert DEFAULT_LOOKBACK_STABILITY_THRESHOLD == pytest.approx(1.452966, abs=1e-5)

    # The tempting shared-window bar — the two runs "must" share their noise
    # over the 90 percent of dates they hold in common — is exactly one third
    # at the pinned tenth, and it is asserted to be WRONG rather than close
    # enough: it is a bar the true null exceeds with probability ~0.55, which
    # is not a calibration quibble but a probe that rejects every second
    # honest book.  The rate test below is the measurement that says so.
    wrong = math.sqrt(abs(DEFAULT_LOOKBACK_JITTER) / (1.0 + DEFAULT_LOOKBACK_JITTER))
    assert wrong == pytest.approx(1.0 / 3.0)
    assert DEFAULT_LOOKBACK_STABILITY_THRESHOLD != pytest.approx(wrong)
    assert DEFAULT_LOOKBACK_STABILITY_THRESHOLD / wrong > 4.0

    # It is a *different number* from every sibling axis' bar, and asserting
    # the differences is the point: applying one feature's bar to another's
    # figure is the mistake a reader is most likely to make.
    assert DEFAULT_LOOKBACK_STABILITY_THRESHOLD != pytest.approx(
        DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD
    )
    assert DEFAULT_LOOKBACK_STABILITY_THRESHOLD != pytest.approx(math.sqrt(2.0))


def test_the_bar_is_a_function_of_the_jitter_and_of_nothing_else() -> None:
    # The two absences, pinned.  `level` and `dates` both cancel — the figure
    # is measured in units of a threshold that carries each — so the bar is a
    # pure function of how far the window moved.  A bar derived as "z
    # standard deviations of the null" would have to be recomputed whenever
    # the grid widened or the level tightened; this one does not, which is
    # what makes a 60-date campaign's figure comparable with a 480-date one's.
    for dates in (60, 120, 480):
        for level in (0.01, 0.05, 0.10):
            bar = time_shuffle_threshold(dates, level=level)
            assert lookback_figure(bar, 0.0, threshold=bar) == pytest.approx(1.0)
    # ...and it *does* depend on the jitter, monotonically: a shorter re-run
    # window is a noisier measurement, so the bar narrows as the jitter
    # grows.  The minus side is wider than the plus side, and both flank the
    # equal-length √2 the seed axis lives at permanently.
    jitters = (-0.50, -0.20, -0.10, 0.10, 0.50)
    bars = [lookback_stability_threshold(j) for j in jitters]
    assert bars == sorted(bars, reverse=True)
    assert lookback_stability_threshold(-0.10) == pytest.approx(1.452966, abs=1e-5)
    assert lookback_stability_threshold(0.10) == pytest.approx(1.381699, abs=1e-5)
    assert lookback_stability_threshold(-1e-9) == pytest.approx(math.sqrt(2.0))


def test_the_bar_is_the_null_s_own_standard_deviation() -> None:
    # The model checked against the distribution it claims, with a fixed seed
    # — the same move feature 129's suite makes, from the other side of the
    # same algebra.  Two independent standard normals, the second scaled to
    # the re-run's shorter window (a variance of 1/r in reference units), have
    # a difference of standard deviation √(1 + 1/r) — the bar, because the
    # bar is the null's own spread in the units the figure is measured in.
    import random

    ratio = 1.0 + DEFAULT_LOOKBACK_JITTER
    rng = random.Random(DEFAULT_SHUFFLE_SEED)
    first = [rng.gauss(0.0, 1.0) for _ in range(400_000)]
    independent = [rng.gauss(0.0, 1.0) for _ in range(400_000)]
    differences = [a - b / math.sqrt(ratio) for a, b in zip(first, independent)]
    sd = math.sqrt(math.fsum(d * d for d in differences) / len(differences))
    assert sd == pytest.approx(math.sqrt(1.0 + 1.0 / ratio), rel=0.01)
    assert DEFAULT_LOOKBACK_STABILITY_THRESHOLD == pytest.approx(sd, rel=0.01)
    # The equal-length limit is √2 — the seed axis' bar — and the null is
    # *wider* than it here, because the re-run's window is shorter.
    equal = [a - b for a, b in zip(first, independent)]
    equal_sd = math.sqrt(math.fsum(d * d for d in equal) / len(equal))
    assert equal_sd == pytest.approx(math.sqrt(2.0), rel=0.01)
    assert equal_sd < DEFAULT_LOOKBACK_STABILITY_THRESHOLD
    # The shared-noise construction the wrong derivation believes in — feature
    # 129's model, a correlation of √r over the shared fraction — measured to
    # the spread it actually produces: ≈ 0.32, within 5 percent of the 1/3
    # the wrong algebra names, and a third of the null's true width.  That is
    # *why* it false-alarms: the null is wider than it thinks.
    shared = math.sqrt(ratio)
    correlated = [
        shared * a + math.sqrt(1.0 - shared**2) * b
        for a, b in zip(first, independent)
    ]
    wrong_sd = math.sqrt(
        math.fsum((a - c) ** 2 for a, c in zip(first, correlated)) / len(first)
    )
    assert wrong_sd == pytest.approx(math.sqrt(2.0 * (1.0 - shared)), rel=0.01)
    assert wrong_sd == pytest.approx(1.0 / 3.0, rel=0.05)
    assert wrong_sd < DEFAULT_LOOKBACK_STABILITY_THRESHOLD / 4.0


def test_the_false_alarm_rate_is_the_level_and_the_wrong_bar_s_isnt() -> None:
    # The calibration, measured rather than asserted — and the test that
    # falsifies the shared-window bar behaviourally.  The figure's
    # false-alarm rate is not hypothesised: the bar is derived from the null
    # and sits `z` standard deviations of it out, so the rate comes back at
    # roughly the probe's own nominal level (the rate is asserted as a band,
    # not a point — this is a calibration check over a finite sample).  With
    # the tempting 1/3 it comes back at ~0.55: over half of all clean
    # candidates rejected, which is the failure mode that matters, since a
    # probe that fires on every honest book is a probe whose rejections mean
    # nothing.  Seeds are pinned, so the rates are measurements.
    grid = monday(120)
    names = [f"S{index:02d}" for index in range(DEFAULT_SYMBOLS)]
    wrong = math.sqrt(abs(DEFAULT_LOOKBACK_JITTER) / (1.0 + DEFAULT_LOOKBACK_JITTER))
    trials = 300
    over = fired_wrong = 0
    for trial in range(trials):
        targets = {1: gaussian_panel(grid, names, seed=1000 + 2 * trial)}
        scores = gaussian_panel(grid, names, seed=1001 + 2 * trial)
        verdict = run_lookback_rerun(scores, targets, node_id=_NODE, seed=trial)
        over += verdict.stability > DEFAULT_LOOKBACK_STABILITY_THRESHOLD
        fired_wrong += verdict.stability > wrong
    assert 0 < over < trials // 10
    assert fired_wrong > trials // 2


# -- The corpus's answer: window-stable leaks, caught by the union ----------------


def test_every_corpus_leak_is_window_stable_and_caught_by_the_union() -> None:
    # The measured fact about this axis' catch, over feature 133's whole
    # maintained corpus.  A whole-sample statistic does not depend on *which
    # dates* the window holds, so every planted leak's figure is ≈ 0.16
    # against the 1.45 bar — under it, with a nine-fold margin — and the
    # stability cause does not fire.  What fires is the union: both runs' own
    # detections reject the leak at the full span and at the jittered window
    # alike, and the verdict reports *which* cause did the work rather than
    # laundering the rejection into a stability figure it was not.
    from tripwires import planted_signals

    for signal in planted_signals():
        verdict = run_lookback_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        assert verdict.stability_rejected is False, signal.leak_kind
        assert verdict.stability / DEFAULT_LOOKBACK_STABILITY_THRESHOLD < 0.5, (
            signal.leak_kind
        )
        assert verdict.reference_rejected is True, signal.leak_kind
        assert verdict.rerun_rejected is True, signal.leak_kind
        assert verdict.rejected is True, signal.leak_kind
        assert verdict.outcome == "tripwire_fail", signal.leak_kind
        # The perturbation is real on every one of them: 120 bars jittered to
        # 108, the window genuinely shorter and the re-run genuinely run.
        assert verdict.dates == 120, signal.leak_kind
        assert verdict.jittered_lookback == 108, signal.leak_kind


def test_two_magnitude_axes_opposite_verdicts_on_one_corpus() -> None:
    # The sharpest measured form of the family's four-features argument.  The
    # same four corpus panels, through this axis and feature 129's: the leaks
    # are window-stable (figure ≈ 0.16, under this bar) and universe-fragile
    # (figure ≈ 1.71, over that one) — while feature 127's axis, which moves
    # only the derangement, sees exactly 0.0.  Three axes, three different
    # answers about one candidate, each of which a single "perturbation"
    # knob would have collapsed into one of the others.
    from tripwires import planted_signals, run_seed_rerun

    for signal in planted_signals():
        here = run_lookback_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        thin = run_subsample_rerun(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        seed = run_seed_rerun(signal.scores, signal.targets, node_id=signal.node_id)
        assert here.stability < DEFAULT_LOOKBACK_STABILITY_THRESHOLD, signal.leak_kind
        assert here.stability_rejected is False, signal.leak_kind
        assert thin.stability > DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD, signal.leak_kind
        assert thin.stability_rejected is True, signal.leak_kind
        assert seed.degradation == 0.0, signal.leak_kind
        assert seed.degradation_rejected is False, signal.leak_kind
        # The subsample margin, asserted as a margin rather than a bare
        # inequality: a future change that narrowed that axis into the noise
        # band fails there, and one that widened this axis fails here.
        assert thin.stability / DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD > 1.5


def test_the_reference_run_is_the_probe_s_own(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # This axis re-runs the probe; it does not replace it.  The reference
    # window is the declared one (the full span when none was declared), and
    # over it the run is feature 125's own — the same seed, the same
    # derangement, the same statistic, the same threshold.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=_NODE, seed=13)
    reference = run_time_shuffle_tripwire(
        scores, targets, node_id=_NODE, seed=13
    )
    assert verdict.reference_sharpe == reference.surviving_sharpe
    assert verdict.reference_threshold == reference.threshold
    assert verdict.reference_rejected is reference.rejected
    assert verdict.horizon == reference.horizon
    assert verdict.seed == reference.seed == 13
    # ...and the re-run over the jittered window is a genuinely different
    # measurement, which is what makes the figure non-zero.
    assert verdict.rerun_sharpe != verdict.reference_sharpe


# -- The null: a clean candidate passes -----------------------------------------


def test_a_clean_candidate_is_the_null_the_probe_must_pass(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # An independent candidate's surviving Sharpe is noise, so it moves under
    # the jitter — and the bar is derived from that null, so a clean candidate
    # clears it.  The margin is asserted rather than the bare fact, so a
    # future change that narrowed the default into the noise band fails here.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=_NODE)
    assert verdict.stability < DEFAULT_LOOKBACK_STABILITY_THRESHOLD
    assert verdict.stability_rejected is False
    assert verdict.reference_rejected is False
    assert verdict.rerun_rejected is False
    assert verdict.rejected is False
    assert verdict.outcome == "ok"


def test_a_different_jitter_is_a_different_measurement(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # That the figure is measuring the *window* and not something else: a
    # different jitter is a different window and a different derangement, so
    # the re-run's statistic and the figure both move.  The clean candidate is
    # the honest demonstration — a candidate that *did* feel the window
    # strongly would be a leak this axis cannot catch, and the corpus test
    # above is where that is measured.
    scores, targets = _clean_candidate(grid, symbols)
    tenth = run_lookback_rerun(scores, targets, node_id=_NODE)
    fifth = run_lookback_rerun(scores, targets, node_id=_NODE, jitter=-0.20)
    assert fifth.jittered_lookback != tenth.jittered_lookback
    assert fifth.rerun_sharpe != tenth.rerun_sharpe
    assert fifth.stability != tenth.stability


def test_the_re_run_is_deterministic_bit_for_bit(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Two callers running the same re-run get the same verdict — the property
    # a deployment needs to compare one campaign's figure against another's,
    # and the reason the verdict carries no wall-clock field at all.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_lookback_rerun(scores, targets, node_id=_NODE)
    second = run_lookback_rerun(scores, targets, node_id=_NODE)
    assert first == second
    assert hash(first) == hash(second)


# -- The verdict record ---------------------------------------------------------


def test_the_verdict_carries_every_term_the_figure_was_made_from(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A rejection can poison a subtree (feature 131) and excise a pool
    # (feature 132), both irreversible, so the record must be auditable on its
    # own: the figure recomputes from the statistics it carries, the reference
    # threshold recomputes from the level and the date count, and the jittered
    # window recomputes from the declared count and the jitter.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=_NODE, seed=13)
    assert verdict.stability == pytest.approx(
        abs(verdict.rerun_sharpe - verdict.reference_sharpe)
        / verdict.reference_threshold
    )
    assert verdict.reference_threshold == pytest.approx(
        time_shuffle_threshold(verdict.dates, level=verdict.level)
    )
    assert verdict.jittered_lookback == jittered_lookback(
        verdict.dates, jitter=verdict.jitter
    )
    assert verdict.jitter == DEFAULT_LOOKBACK_JITTER
    assert verdict.lookback is None
    assert verdict.axis == LOOKBACK_AXIS
    assert LOOKBACK_AXIS == PERTURBATION_AXES[3] == "lookback-jitter"
    assert verdict.tripwire == PERTURBATION_STABILITY_NAME
    assert verdict.seed == 13
    assert verdict.outcome in TRIPWIRE_OUTCOMES


def test_the_knobs_this_axis_does_not_move_read_absent(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # This axis holds the seed and the universe fixed and moves the window
    # alone, and the record says so the way the member's schemas say
    # everything absent: ``None``, not zero.  The three are *properties*
    # rather than fields — not per-verdict values a caller could set but
    # constants about the axis — which is what lets the stability ledger's
    # writer (``record_stability``, which reads any axis' verdict) accept
    # this one unchanged and write its knobs as NULL.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=_NODE)
    assert verdict.rerun_seed is None
    assert verdict.subsample_seed is None
    assert verdict.subsample_fraction is None
    field_names = {field.name for field in dataclasses.fields(LookbackRerunVerdict)}
    assert {"rerun_seed", "subsample_seed", "subsample_fraction"}.isdisjoint(
        field_names
    )


def test_the_verdict_shares_no_statistic_name_with_the_other_two_verdicts(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The seam feature 131's structural check depends on. Feature 125's probe
    # and feature 127's re-run both expose ``surviving_sharpe`` and
    # ``threshold``; a fourth verdict shaped like them would pass poison's
    # field check and then be judged on feature 125's comparison over feature
    # 125's statistic. The stability names, by contrast, are shared with
    # feature 129's verdict *on purpose* — the two records carry the same
    # quantity in the same units, and the ledger's writer reads either —
    # while the axis vocabulary stays disjoint, so no reader can mistake
    # which perturbation a record reports.
    from tripwires import SeedRerunVerdict, TimeShuffleVerdict

    own = {field.name for field in dataclasses.fields(LookbackRerunVerdict)}
    for other in (TimeShuffleVerdict, SeedRerunVerdict):
        theirs = {field.name for field in dataclasses.fields(other)}
        statistic_bearing = theirs & {
            "surviving_sharpe",
            "threshold",
            "degradation",
        }
        assert statistic_bearing.isdisjoint(own), other.__name__
    assert {"surviving_sharpe", "threshold", "degradation"}.isdisjoint(own)
    theirs = {field.name for field in dataclasses.fields(SubsampleRerunVerdict)}
    assert {"stability", "stability_threshold"} <= own
    assert {"reference_sharpe", "rerun_sharpe", "reference_threshold"} <= own & theirs
    assert {"lookback", "jitter", "jittered_lookback"}.isdisjoint(theirs)
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
    # lying stability figure into a column that outlives the process.
    scores, targets = _clean_candidate(grid, symbols)
    good = run_lookback_rerun(scores, targets, node_id=_NODE)
    fields = {
        field.name: getattr(good, field.name)
        for field in dataclasses.fields(good)
    }
    # A figure that does not recompute from the terms beside it.
    with pytest.raises(TripwirePanelError, match="stability"):
        LookbackRerunVerdict(**{**fields, "stability": good.stability + 1.0})
    # A jittered window that does not recompute from the declared one.
    with pytest.raises(TripwirePanelError, match="jittered lookback"):
        LookbackRerunVerdict(
            **{**fields, "jittered_lookback": good.jittered_lookback + 1}
        )
    # A declared lookback the reference run did not measure.
    with pytest.raises(TripwirePanelError, match="reference run measured"):
        LookbackRerunVerdict(**{**fields, "lookback": good.dates - 1})
    # Another axis's vocabulary, and the probe's own name.
    with pytest.raises(TripwirePanelError, match="axis"):
        LookbackRerunVerdict(**{**fields, "axis": SUBSAMPLE_AXIS})
    with pytest.raises(TripwirePanelError, match="perturbation-stability"):
        LookbackRerunVerdict(**{**fields, "tripwire": TIME_SHUFFLE_NAME})
    # A decision that is not the disjunction of the causes it carries.
    with pytest.raises(TripwirePanelError, match="causes"):
        LookbackRerunVerdict(**{**fields, "rejected": not good.rejected})


# -- The persistence half: feature 130's own sentence ---------------------------


def test_the_figure_lands_on_the_node_row_itself(
    grid: list[dt.date], symbols: list[str], node_metric_store: NodeMetricStore
) -> None:
    # The sentence's second half, literally: the figure is written to the
    # node's own row, in the column 0114 has held since three features ago —
    # not to a table of this feature's own, and not by joining anything.
    tree = _seeded(node_metric_store)
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=tree.root_id)
    assert verdict.rejected is False
    receipt = node_metric_store.record(verdict, recorded_at=_STAMP)
    assert receipt.superseded is None
    assert receipt.stability == verdict.stability
    assert receipt.axis == LOOKBACK_AXIS
    assert receipt.outcome == "ok"
    assert receipt.recorded_at == _STAMP
    assert node_metric_store.metric_of(tree.root_id) == pytest.approx(
        verdict.stability
    )
    # ...read past the store's API: the column holds the figure, exactly.
    assert _column_of(node_metric_store, tree.root_id) == pytest.approx(
        verdict.stability
    )


def test_a_node_the_tree_does_not_hold_is_refused_and_the_ledger_s_isnt(
    grid: list[dt.date], symbols: list[str], node_metric_store: NodeMetricStore
) -> None:
    # The persistence half's own decision, and the deliberate opposite of
    # feature 129's stance.  The ledger requires no node row — a figure is
    # legitimately known before the tree is handed the node (§6.1 puts step 10
    # before the trial is debited) — while a *column* write is an UPDATE
    # against a row another feature owns, and an UPDATE that matched nothing
    # would report a metric persisted that no node carries.  The same
    # verdict, through both stores, in one direction each.
    tree = _seeded(node_metric_store)
    scores, targets = _clean_candidate(grid, symbols)
    stranger = str(uuid.uuid4())
    verdict = run_lookback_rerun(scores, targets, node_id=stranger)
    with pytest.raises(TripwireNodeMetricError, match="does not hold"):
        node_metric_store.record(verdict)
    with pytest.raises(TripwireNodeMetricError, match="does not hold"):
        node_metric_store.metric_of(stranger)
    # The ledger over the same file accepts the same verdict — the contrast
    # that makes the refusal a decision rather than an omission.
    ledger = StabilityStore(node_metric_store.database_url)
    row = ledger.record(verdict, recorded_at=_STAMP)
    assert row.node_id == stranger
    assert row.axis == LOOKBACK_AXIS
    # ...and the measured node is untouched by the stranger's figure.
    assert _column_of(node_metric_store, tree.root_id) is None


def test_a_re_measurement_refreshes_in_place_and_reports_what_it_superseded(
    grid: list[dt.date], symbols: list[str], node_metric_store: NodeMetricStore
) -> None:
    # A column holds one number, so a re-measurement is a refresh rather than
    # a second row — the same refresh-on-the-key discipline 129's table
    # keeps, in the one shape a column allows.  What the column cannot keep,
    # the receipt does: the value the write replaced, carried as
    # ``superseded`` so a caller can say how much the node's metric moved.
    tree = _seeded(node_metric_store)
    scores, targets = _clean_candidate(grid, symbols)
    first = run_lookback_rerun(scores, targets, node_id=tree.root_id)
    written = node_metric_store.record(first, recorded_at=_STAMP)
    assert written.superseded is None
    second = run_lookback_rerun(
        scores, targets, node_id=tree.root_id, jitter=-0.20
    )
    assert second.stability != first.stability
    refreshed = node_metric_store.record(second, recorded_at=_STAMP)
    assert refreshed.superseded == pytest.approx(first.stability)
    assert refreshed.stability == second.stability
    # The column keeps only the newest — one number, not a history.
    assert node_metric_store.metric_of(tree.root_id) == pytest.approx(
        second.stability
    )
    assert _column_of(node_metric_store, tree.root_id) == pytest.approx(
        second.stability
    )


def test_metric_of_refuses_the_two_ways_to_be_absent(
    grid: list[dt.date], symbols: list[str], node_metric_store: NodeMetricStore
) -> None:
    # One number, two ways to be absent, and the read that refuses to blur
    # them: a node the tree does not hold is no metric at all, and a node
    # whose column is still NULL was *never measured* — a different sentence
    # from "measured at zero", and a zero specifically would read as a
    # candidate perfectly stable under the jitter, the most flattering
    # figure the axis can state.
    tree = _seeded(node_metric_store)
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=tree.root_id)
    node_metric_store.record(verdict)
    assert isinstance(node_metric_store.metric_of(tree.root_id), float)
    with pytest.raises(TripwireNodeMetricError, match="no perturb_stability"):
        node_metric_store.metric_of(tree.sibling_root_id)
    with pytest.raises(TripwireNodeMetricError, match="does not hold"):
        node_metric_store.metric_of(str(uuid.uuid4()))


def test_a_passing_figure_is_persisted_beside_a_failing_one(
    grid: list[dt.date], symbols: list[str], node_metric_store: NodeMetricStore
) -> None:
    # The half of this feature no other axis has, and where it differs from
    # feature 131's store most sharply.  That store *refuses* a verdict that
    # did not reject, and rightly — there is nothing to poison. This one must
    # not: the metric's consumer (the triage figure, feature 134) needs the
    # figures that were supposed to be small as much as the ones that were
    # not, and a column that only ever held rejections would read as a
    # failure flag rather than a measurement.
    tree = _seeded(node_metric_store)
    clean_scores, clean_targets = _clean_candidate(grid, symbols)
    passing = run_lookback_rerun(clean_scores, clean_targets, node_id=tree.root_id)
    assert passing.rejected is False
    passing_receipt = node_metric_store.record(passing, recorded_at=_STAMP)
    assert passing_receipt.outcome == "ok"
    assert passing_receipt.rejected is False

    # The failing class lands on a *second node*, because the column holds
    # one number per node: a second write on the same node would be a
    # refresh rather than a second class, which is the design working.
    loud_scores, loud_targets = _corpus_leak()
    failing = run_lookback_rerun(
        loud_scores, loud_targets, node_id=tree.child_id
    )
    assert failing.rejected is True
    failing_receipt = node_metric_store.record(failing, recorded_at=_STAMP)
    assert failing_receipt.outcome == "tripwire_fail"
    assert failing_receipt.rejected is True

    # Both classes are on the node rows, told apart by their receipts — and
    # each node's own column reads back its own class.
    assert node_metric_store.metric_of(tree.root_id) == pytest.approx(
        passing.stability
    )
    assert node_metric_store.metric_of(tree.child_id) == pytest.approx(
        failing.stability
    )


def test_the_figure_survives_a_fresh_store_over_the_same_file(
    grid: list[dt.date], symbols: list[str], database_url: str
) -> None:
    # The sentence is about a *persisted* metric, so the proof is a second
    # process's view: a new store over the same file reads what the first
    # wrote, with no shared Python state between them.
    tree = _seeded(NodeMetricStore(database_url))
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=tree.root_id)
    NodeMetricStore(database_url).record(verdict)
    reopened = NodeMetricStore(database_url)
    assert reopened.metric_of(tree.root_id) == pytest.approx(verdict.stability)


def test_the_schema_is_idempotent_and_brings_the_column_by_alter(
    tmp_path: Path,
) -> None:
    # The column arrives the way feature 131 paved for a table the migration
    # made without its column: a ``PRAGMA table_info`` probe and an
    # ``ALTER TABLE ... ADD COLUMN``, because SQLite's ``ADD COLUMN`` carries
    # no ``IF NOT EXISTS``.  A database the orchestrator migrated through 0114
    # already carries the column and is left byte-for-byte as it was; the
    # node bootstrap deliberately does *not* create it (the restraint
    # ``layout`` states: a bootstrap brings what a feature reads or writes,
    # and this writer brings its own column); either way the end state is the
    # table 0114 leaves.
    raw = tmp_path / "raw-0118.db"
    connection = sqlite3.connect(raw)
    connection.executescript(node_bootstrap_schema("sqlite"))
    columns = [row[1] for row in connection.execute("PRAGMA table_info(node)")]
    connection.close()
    assert NODE_METRIC_COLUMN not in columns
    assert NODE_METRIC_COLUMN not in node_bootstrap_schema("sqlite")

    store = NodeMetricStore(f"sqlite:///{raw}")
    store.ensure_schema()
    store.ensure_schema()  # idempotent — the probe, not a blind ALTER
    connection = sqlite3.connect(raw)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(node)")]
    connection.close()
    assert NODE_METRIC_COLUMN in columns
    # A table the bootstrap created (with rows already in it) gets the column
    # the same way, and the existing rows read as never measured — NULL, not
    # zero, the absent-versus-zero distinction the read refuses to blur.
    fresh = NodeMetricStore(f"sqlite:///{tmp_path / 'bootstrapped.db'}")
    fresh.ensure_schema()
    connection = sqlite3.connect(fresh.path)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(node)")]
    connection.close()
    assert NODE_METRIC_COLUMN in columns


def test_the_column_write_does_not_cross_the_other_stores(
    grid: list[dt.date],
    symbols: list[str],
    node_metric_store: NodeMetricStore,
    stability_store: StabilityStore,
) -> None:
    # One verdict, both halves of one sentence, three stores over one file:
    # the ledger row (129's), the node column (130's) and the poison mark
    # (131's) are three different kinds of fact, and the fixtures share a file
    # precisely so their non-crossing is checkable rather than assumed — on
    # separate files every direction would pass vacuously.
    from tripwires import PoisonStore

    poison_store = PoisonStore(node_metric_store.database_url)
    poison_store.ensure_schema()  # its table arrives on its own first use
    tree = _seeded(node_metric_store)
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=tree.root_id)

    # The same lookback verdict, through both persistence halves: the ledger
    # takes it keyed by axis (one row among the four §C6 declares), and the
    # node column takes it as the one axis the spec asks to sit on the node.
    row = record_stability(verdict, store=stability_store)
    receipt = record_node_metric(verdict, store=node_metric_store)
    assert row.axis == receipt.axis == LOOKBACK_AXIS
    assert row.stability == receipt.stability == verdict.stability

    connection = sqlite3.connect(node_metric_store.path)
    counts = (
        connection.execute(f"SELECT COUNT(*) FROM {POISON_TABLE}").fetchone()[0],
        connection.execute(f"SELECT COUNT(*) FROM {STABILITY_TABLE}").fetchone()[0],
        connection.execute(
            f"SELECT {NODE_METRIC_COLUMN} FROM node WHERE id = ?",
            (tree.root_id,),
        ).fetchone()[0],
        connection.execute(
            "SELECT poisoned_at FROM node WHERE id = ?", (tree.root_id,)
        ).fetchone()[0],
    )
    connection.close()
    assert counts[0] == 0
    assert counts[1] == 1
    assert counts[2] == pytest.approx(verdict.stability)
    assert counts[3] is None

    # ...and the other direction: a real poisoning on the same file leaves
    # the metric and the ledger alone. A feature-125 verdict is what a
    # poisoning takes, so the leak is the candidate whose detection is
    # unambiguous.
    loud_scores, loud_targets = _corpus_leak()
    failure = run_time_shuffle_tripwire(
        loud_scores, loud_targets, node_id=tree.sibling_root_id
    )
    assert failure.rejected is True
    poison_store.poison(failure)
    connection = sqlite3.connect(node_metric_store.path)
    after = (
        connection.execute(
            f"SELECT {NODE_METRIC_COLUMN} FROM node WHERE id = ?",
            (tree.sibling_root_id,),
        ).fetchone()[0],
        connection.execute(
            f"SELECT {NODE_METRIC_COLUMN} FROM node WHERE id = ?",
            (tree.root_id,),
        ).fetchone()[0],
        connection.execute(f"SELECT COUNT(*) FROM {STABILITY_TABLE}").fetchone()[0],
    )
    connection.close()
    assert after[0] is None  # a poisoned node is not a measured one
    assert after[1] == pytest.approx(verdict.stability)  # and vice versa
    assert after[2] == 1


def test_the_module_level_entry_points_refuse_a_deployment_that_names_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sentence is "persisting", so a no-op that returned successfully
    # would report it satisfied by a deployment with nowhere to write. The
    # module-level entry points refuse by name; the *builder* stays silent,
    # because the factory builds every component on every ``create_app()``
    # and a builder that raised would take composition down for every
    # unrelated feature.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert NodeMetricStore.resolve({}) is None
    with pytest.raises(TripwireNodeMetricError, match=DATABASE_URL_ENV):
        record_node_metric(object())
    with pytest.raises(TripwireNodeMetricError, match=DATABASE_URL_ENV):
        node_metric_of(_NODE)


def test_the_probe_suite_still_needs_no_database(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The property ``conftest`` guards by keeping every store fixture
    # non-autouse: a probe test takes no database. Feature 130 adds a *third*
    # store to this suite, and the temptation it brings is a figure computed
    # and persisted in one call — so the split is pinned here: the re-run is a
    # pure function of its mappings and needs nothing, while the persistence
    # refuses by name rather than finding a store it was not given.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=_NODE)
    assert verdict.rejected is False
    assert NodeMetricStore.resolve({}) is None


# -- The seam: every refusal answers in this feature's vocabulary ----------------


@pytest.mark.parametrize(
    "database_url",
    ["postgresql://user@host/db", "mysql://host/db", "not-a-url", "sqlite://"],
)
def test_a_misrouted_database_url_refuses_in_this_features_words(
    database_url: str,
) -> None:
    # ``sqlite_path`` is shared with features 131, 132 and 129 and refuses a
    # URL it cannot speak with ``TripwirePoisonError`` — 131's error, which
    # 131's own suite pins. Feature 130's callers catch *this* feature's
    # error, because the node metric is what they asked to persist, so a
    # misrouted ``DATABASE_URL`` arriving as a poisoning error is exactly the
    # case they did not catch: the figure silently goes unrecorded and the
    # caller takes the process down with an error from a feature it never
    # imported. The check stays shared — one provenance — and only the
    # vocabulary is translated, from the original, so ``__cause__`` still
    # names the cause.
    store = NodeMetricStore(database_url)
    with pytest.raises(
        TripwireNodeMetricError, match="could not be addressed"
    ) as caught:
        store.ensure_schema()
    assert isinstance(caught.value.__cause__, TripwirePoisonError)


def test_a_node_id_that_cannot_join_the_tree_refuses_here(
    grid: list[dt.date],
    symbols: list[str],
    node_metric_store: NodeMetricStore,
) -> None:
    # Same seam, the id normalizer. Every value this store writes joins
    # ``node.id UUID PRIMARY KEY``, and it matters more here than anywhere
    # else in the member: the write is an ``UPDATE ... WHERE id = ?``, so a
    # spelling the store quietly accepted would match zero rows and read
    # back as a successful persistence of nothing.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id="not-a-uuid")
    with pytest.raises(TripwireNodeMetricError, match="could not name its node"):
        node_metric_store.record(verdict)
    with pytest.raises(TripwireNodeMetricError, match="could not name its node"):
        node_metric_store.metric_of("not-a-uuid")


def test_a_record_cannot_be_built_with_an_unusable_instant(
    grid: list[dt.date],
    symbols: list[str],
    node_metric_store: NodeMetricStore,
) -> None:
    # The instant parser is shared with 131, whose messages say *a poisoning
    # instant* — right where it was written, wrong here: this module
    # validates when a *node metric* was written, and a caller told its
    # figure was refused over a poisoning would look in the wrong feature.
    # The validation is shared; the sentence is not.
    tree = _seeded(node_metric_store)
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_lookback_rerun(scores, targets, node_id=tree.root_id)
    naive = dt.datetime(2024, 1, 1)  # noqa: DTZ001 - the naive stamp is the input
    for unusable in (naive, "2024-01-01T00:00:00+00:00"):
        with pytest.raises(
            TripwireNodeMetricError, match="not a usable instant"
        ) as caught:
            node_metric_store.record(verdict, recorded_at=unusable)
        assert isinstance(caught.value.__cause__, TripwirePoisonError)


def test_a_verdict_from_another_axis_is_refused_by_name(
    grid: list[dt.date],
    symbols: list[str],
    node_metric_store: NodeMetricStore,
) -> None:
    # The check that is this store's alone. The node column is single-valued,
    # so it holds one axis' figure — this feature's — and a verdict from any
    # other axis would overwrite it with another perturbation's number, which
    # is precisely the drift 129's ``(node_id, axis)`` key exists to prevent.
    # The ledger is where every axis' figure lives side by side; a caller
    # holding one of those verdicts and this store has made the wrong call,
    # and the refusal names the axis it arrived with.
    scores, targets = _clean_candidate(grid, symbols)
    other_axis = run_subsample_rerun(scores, targets, node_id=_NODE)
    with pytest.raises(TripwireNodeMetricError, match="lookback-jitter"):
        node_metric_store.record(other_axis)
    # ...and a producer the store cannot read at all — feature 125's own
    # verdict, and not a verdict — is refused by its missing terms, checked
    # structurally because the factory's scan gives one source file two class
    # objects and ``isinstance`` cannot hold across them.
    detection = run_time_shuffle_tripwire(scores, targets, node_id=_NODE)
    with pytest.raises(TripwireNodeMetricError, match="carries none of"):
        node_metric_store.record(detection)
    with pytest.raises(TripwireNodeMetricError, match="carries none of"):
        node_metric_store.record("not a verdict at all")


# -- The seats: the composed application and the app namespace -------------------


def test_the_composed_component_is_the_store_the_seat_reaches(
    monkeypatch: pytest.MonkeyPatch, node_metric_store: NodeMetricStore
) -> None:
    # The plugin seam from the persistence side: the factory's scan imports
    # the member, its @register fires, and a composed application carries the
    # store for the deployment the process is running in — reachable by way
    # of the app namespace, which is how the evaluation loop will ask for it.
    import tripwires

    from app.module_loader import Application, Registration, create_app
    from app.modules.tripwires.node_metric import COMPONENT_NAME as SEAT_NAME
    from app.modules.tripwires.node_metric import node_metric_store_component

    monkeypatch.setenv(DATABASE_URL_ENV, node_metric_store.database_url)
    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    composed = application.get(NODE_METRIC_COMPONENT_NAME)
    assert type(composed).__name__ == "NodeMetricStore"
    assert node_metric_store_component(application) is composed
    # The sixth component, beside the fifth and not inside it: the two
    # stores persist the same verdict's figure into different places, and a
    # caller asking for one must not be handed the other.
    assert type(application.get("tripwires-stability")).__name__ == "StabilityStore"
    assert SEAT_NAME == NODE_METRIC_COMPONENT_NAME == "tripwires-node-metric"
    # A store registered but not yet used: composition opens no database.
    assert not Path(composed.path).exists()
    assert node_metric_store_component(Application(components={}, order=())) is None


def test_an_unconfigured_deployment_composes_no_store_but_does_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The degrade-don't-break stance every store in this workspace takes
    # toward an absent ``DATABASE_URL``: the factory builds every registered
    # component on every ``create_app()``, so a builder that raised would take
    # composition down for every unrelated feature. Absent is a *discoverable*
    # state — and it is not the same fact as "the node was never re-run on
    # the lookback axis", which is why the module-level entry point refuses
    # instead.
    import tripwires

    from app.module_loader import Registration, create_app

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    member_src = Path(tripwires.__file__).resolve().parent.parent
    application = create_app(member_src, registry=Registration())

    assert application.get(NODE_METRIC_COMPONENT_NAME) is None
    assert type(application.get("tripwires")).__name__ == "TimeShuffleTripwire"
