"""Feature 133 — the planted-leak corpus, against the guarantee it pins.

app_spec.xml: *"System maintains a corpus of deliberately leaking signals that
every tripwire must catch, which returns 0 escapes in the suite."*  The suite
is organised around that one sentence, because it is the whole feature: the
corpus is a set of *known leaks*, and the suite asserts that every one of them
is caught.  The tests break that assertion into the pieces a reader has to
trust otherwise — that the corpus is the closed set of leak kinds it claims,
that each planted panel actually leaks (and leaks the way its kind says), that
the corpus is the same corpus every run, and, load-bearing above all, that
running feature 125's probe against every planted signal rejects every one.

The central test is :func:`test_every_planted_signal_is_rejected_with_zero_escapes`.
It is the feature's acceptance gate in miniature: iterate the corpus, run the
probe, assert no escape.  Everything else in the suite is the scaffolding that
keeps that one assertion honest — a corpus that planted clean panels, or
planted the wrong panels, or planted a different corpus each run, would make
"0 escapes" either trivially true or meaninglessly flaky, and a flaky
tripwire test is no test of a tripwire.
"""

from __future__ import annotations

import datetime as dt

from _panels import gaussian_panel
from corpus_leaks import (
    full_sample_mean,
    full_sample_mean_negated,
    full_sample_tstat,
    full_sample_tstat_negated,
)
from tripwires import (
    CORPUS_GRID,
    CORPUS_SEED,
    CORPUS_SYMBOLS,
    HORIZONS,
    LEAK_KINDS,
    CorpusSignal,
    planted_signals,
)

# The independent restatement of each leak kind's builder, keyed by the leak
# vocabulary. A test checks the corpus's planted panel against this builder to
# confirm feature 133 planted what it claims — the corpus owns the panels,
# this module owns the definition of "leak", and the two must agree.
_BUILDERS = {
    "full_sample_mean": full_sample_mean,
    "full_sample_mean_negated": full_sample_mean_negated,
    "full_sample_tstat": full_sample_tstat,
    "full_sample_tstat_negated": full_sample_tstat_negated,
}


# -- The corpus is the closed set of leak kinds --------------------------------


def test_the_corpus_plants_every_leak_kind_once() -> None:
    # The corpus is the probe's own leak taxonomy, closed (LEAK_KINDS), and it
    # plants exactly one signal per kind — a corpus that missed a kind would
    # leave a leak the suite never asserts on, and one that duplicated a kind
    # would be asserting on itself.
    signals = planted_signals()
    assert [signal.leak_kind for signal in signals] == list(LEAK_KINDS)
    assert len(signals) == len(LEAK_KINDS)


def test_the_leak_kinds_are_the_probe_vocabulary() -> None:
    # LEAK_KINDS is not an arbitrary listing — it is the closed leak vocabulary
    # the corpus documents, and every documented kind has a builder and a
    # description, so the corpus cannot name a leak it does not plant or plant
    # a leak it cannot describe.
    from tripwires.corpus import _DESCRIPTIONS, _STATISTICS

    assert set(LEAK_KINDS) == set(_STATISTICS) == set(_DESCRIPTIONS)
    for kind in LEAK_KINDS:
        assert _DESCRIPTIONS[kind].strip()


def test_every_signal_is_a_corpus_signal_value() -> None:
    # Each entry is a frozen CorpusSignal carrying the fields the audit needs:
    # the node it rejects, the leak it planted, why it leaks, the horizon, and
    # the two panels.
    for signal in planted_signals():
        assert isinstance(signal, CorpusSignal)
        assert signal.leak_kind in LEAK_KINDS
        assert signal.node_id.startswith("planted-")
        assert signal.horizon in HORIZONS
        assert signal.scores and signal.targets


def test_the_signals_are_self_describing() -> None:
    # A corpus is maintained to be read: each signal names its leak and states,
    # in its own description, the mechanism a persisted rejection would report.
    descriptions = {
        signal.leak_kind: signal.description for signal in planted_signals()
    }
    assert set(descriptions) == set(LEAK_KINDS)
    assert all(len(desc) > 20 for desc in descriptions.values())


# -- Each planted panel actually leaks -----------------------------------------


def test_a_planted_panel_is_the_whole_sample_statistic_for_its_kind(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The corpus plants what it claims to plant: each signal's score panel is
    # the independent builder's statistic for that kind, held across the target
    # series' dates. The corpus owns the panels; this module restates the
    # definition of "leak"; the two must be bit-for-bit the same.
    bundle = {1: gaussian_panel(grid, symbols, seed=CORPUS_SEED)}
    series = bundle[1]
    for signal in planted_signals():
        expected = _BUILDERS[signal.leak_kind](series)
        assert {day: dict(row) for day, row in signal.scores.items()} == {
            day: dict(expected) for day in sorted(series)
        }


def test_a_planted_panel_is_constant_across_dates() -> None:
    # The leak is date-independence made visible: every date of a planted panel
    # carries the same cross-section, so re-dating the cross-sections (what the
    # time shuffle does) cannot disturb what the panel carries. A planted panel
    # that varied with the date would be leaking something other than the
    # whole-sample statistic, and the corpus would have planted the wrong leak.
    for signal in planted_signals():
        cross_sections = [tuple(sorted(row.items())) for row in signal.scores.values()]
        assert len(set(cross_sections)) == 1


def test_the_four_signals_are_distinct_panels() -> None:
    # The corpus tests the probe against a spread of leaks, not one leak
    # restated: the four planted panels are pairwise distinct, so the suite's
    # "0 escapes" is a statement about four different leaks, not four spellings
    # of one.
    panels = [
        tuple(
            sorted((day, tuple(sorted(row.items()))) for day, row in s.scores.items())
        )
        for s in planted_signals()
    ]
    assert len(set(panels)) == len(panels)


def test_the_negated_kinds_are_the_sign_flips() -> None:
    # The two _negated kinds are the sign-flipped mirrors of the other two —
    # the same information with the opposite sign, which is what makes the
    # two-sided test a feature rather than a preference. A corpus that merely
    # restated the mean twice would not be testing two-sidedness.
    mean, neg, tstat, tstat_neg = planted_signals()
    for day in mean.scores:
        assert {s: -v for s, v in mean.scores[day].items()} == neg.scores[day]
        assert {s: -v for s, v in tstat.scores[day].items()} == tstat_neg.scores[day]


def test_a_planted_signal_covers_every_spec_horizon() -> None:
    # The corpus's bundle carries the full closed horizon set, so a signal's
    # resolved horizon names the horizon it was scored against rather than the
    # only one available. The probe resolves to the shortest covered; the
    # corpus gives it the whole set to resolve over.
    for signal in planted_signals():
        assert set(signal.targets) == set(HORIZONS)


# -- The central guarantee: 0 escapes ------------------------------------------


def test_every_planted_signal_is_rejected_with_zero_escapes() -> None:
    # The feature's acceptance gate in miniature. Every planted leak is a known
    # leak, so every one must be caught: rejected True, outcome tripwire_fail,
    # the surviving Sharpe over the threshold. A single escape fails the
    # feature — the corpus exists to assert exactly this, and an escape means a
    # planted leak the tripwire let through.
    escapes = [signal for signal in planted_signals() if not signal.run().rejected]
    assert escapes == [], (
        "the corpus has escapes — a planted leak the tripwire let through"
    )


def test_every_planted_signal_states_tripwire_fail() -> None:
    # The verdict's two spellings of one fact must agree, and both must be the
    # failure word: a planted leak is rejected, so its outcome is tripwire_fail,
    # not merely rejected. A corpus signal whose outcome were "ok" would be a
    # corpus that planted a pass.
    for signal in planted_signals():
        verdict = signal.run()
        assert verdict.rejected is True
        assert verdict.outcome == "tripwire_fail"


def test_every_planted_leak_clears_the_bar_by_a_margin() -> None:
    # The corpus plants unambiguous leaks, not borderline ones: each surviving
    # Sharpe clears its threshold with room to spare, so the guarantee is not
    # sitting on a knife-edge that a different seed or grid would tip. A corpus
    # of marginal leaks would make "0 escapes" a coin flip.
    for signal in planted_signals():
        verdict = signal.run()
        assert abs(verdict.surviving_sharpe) > verdict.threshold * 1.2


def test_the_probe_reports_the_shortest_horizon_for_a_planted_signal() -> None:
    # Feature 125's pinned shortest-covered policy, seen through the corpus:
    # the bundle covers all five horizons, so the resolved horizon is the
    # shortest the spec names, and the corpus's stated horizon matches it.
    for signal in planted_signals():
        assert signal.run().horizon == min(HORIZONS)


# -- Determinism: the same corpus every run ------------------------------------


def test_the_corpus_is_the_same_corpus_every_run() -> None:
    # Built once from CORPUS_SEED at call time, but deterministic in that seed:
    # the suite that asserts 0 escapes must assert it against the same planted
    # panels every run, on every machine, or the guarantee is a roll of the
    # dice. Two calls return equal tuples of equal signals.
    assert planted_signals() == planted_signals()


def test_the_corpus_is_built_from_the_pinned_seed() -> None:
    # The corpus's one fixed fact: its panels are drawn from CORPUS_SEED. A
    # corpus built from any other seed is a different corpus, which is why the
    # seed is pinned and why the panels are reproducible from it.
    from tripwires.corpus import _target_bundle

    bundle = _target_bundle(CORPUS_SEED)
    for signal in planted_signals():
        assert {day: dict(row) for day, row in signal.targets.items()} == {
            day: dict(row) for day, row in bundle.items()
        }


def test_the_corpus_runs_on_the_probe_verification_grid() -> None:
    # The corpus is scored on feature 125's own leak-verification width — 120
    # dates of 30 symbols — the grid the probe was verified against, so the
    # corpus's guarantee is stated at the size the probe's detection was
    # checked at.
    assert CORPUS_GRID == 120
    assert CORPUS_SYMBOLS == 30
    signal = next(iter(planted_signals()))
    assert len(signal.scores) == CORPUS_GRID
    assert len(next(iter(signal.scores.values()))) == CORPUS_SYMBOLS


# -- The seam: run() is the audit path -----------------------------------------


def test_run_hands_the_planted_panels_to_the_probe(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # CorpusSignal.run is the one seam a signal offers: it runs feature 125's
    # probe on the signal's own panels with the signal's node id, so the audit
    # path (run the planted leak, check it is rejected) is the probe path. The
    # verdict names the planted node and the time-shuffle tripwire.
    from tripwires import TIME_SHUFFLE_NAME, run_time_shuffle_tripwire

    signal = next(s for s in planted_signals() if s.leak_kind == "full_sample_mean")
    expected = run_time_shuffle_tripwire(
        signal.scores, signal.targets, node_id=signal.node_id
    )
    verdict = signal.run()
    assert verdict == expected
    assert verdict.node_id == signal.node_id
    assert verdict.tripwire == TIME_SHUFFLE_NAME


def test_a_planted_signal_is_rejected_independently_of_the_probe_seed(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A corpus leak is a strong leak: it is caught not just at the probe's
    # default seed but across seeds, because its information is date-independent
    # and survives any derangement. This is the property that makes the corpus
    # a stable guarantee rather than a seed-luck artifact.
    from tripwires import run_time_shuffle_tripwire

    for signal in planted_signals():
        for seed in (0, 1, 7, 42):
            verdict = run_time_shuffle_tripwire(
                signal.scores, signal.targets, node_id=signal.node_id, seed=seed
            )
            assert verdict.rejected is True


def test_a_planted_signal_survives_a_clean_candidate_control(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The corpus is leaks only — a control confirms the probe still passes a
    # clean candidate, so "0 escapes" is not "rejects everything". The planted
    # signals are rejected while an independent candidate on the same grid is
    # not, which is what distinguishes a working tripwire from a broken one.
    targets = {1: gaussian_panel(grid, symbols, seed=CORPUS_SEED + 99)}
    scores = gaussian_panel(grid, symbols, seed=CORPUS_SEED + 100)
    from tripwires import run_time_shuffle_tripwire

    assert run_time_shuffle_tripwire(scores, targets, node_id="clean").rejected is False
    assert all(signal.run().rejected for signal in planted_signals())
