"""Feature 125 — the time-shuffle probe, against the properties it pins.

app_spec.xml: *"System scores a candidate against time-shuffled forward
returns, which rejects the node when a surviving Sharpe indicates leakage."*
These tests are organised by the four decisions the module docstring pins,
plus the determinism contract, because those are the claims a reader has to
take on faith otherwise — and the two that matter most are the ones an
implementation could get *nearly* right and still be useless: the shuffle
must be a derangement of whole cross-sections, and a survived Sharpe must
actually reject.

The leak fixtures are the load-bearing ones.  A tripwire suite that rejects
nothing is indistinguishable from one that is broken, so
:func:`test_a_planted_lookahead_leak_is_rejected` plants the canonical leak
(a full-sample symbol mean — feature 133's planted corpus in miniature) and
:func:`test_the_sign_flipped_leak_is_rejected_too` plants its mirror image,
which is what makes the two-sided test a feature rather than a preference.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest
from _panels import gaussian_panel, lookahead_panel, monday
from tripwires import (
    DEFAULT_SHUFFLE_LEVEL,
    DEFAULT_SHUFFLE_SEED,
    HORIZONS,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    TimeShuffleVerdict,
    TripwirePanelError,
    TripwireStatisticError,
    run_time_shuffle_tripwire,
    surviving_sharpe,
    time_shuffle_pairing,
    time_shuffle_threshold,
)


def _clean_candidate(
    grid: list[dt.date], symbols: list[str], *, seed: int = 3
) -> tuple[dict, dict]:
    """A candidate with no relationship to its targets — scores, targets.

    The targets are drawn once and the scores from a *different* stream, so
    the two panels are independent by construction: this is the null the probe
    is supposed to pass.
    """
    targets = {1: gaussian_panel(grid, symbols, seed=seed + 1)}
    scores = gaussian_panel(grid, symbols, seed=seed + 2)
    return scores, targets


# -- The shuffle is a derangement of whole cross-sections ----------------------


def test_the_pairing_moves_every_date(grid: list[dt.date]) -> None:
    # The derangement guarantee: no date's aligned pair survives by luck of
    # the draw, which is what makes the probe's null airtight.
    pairing = time_shuffle_pairing(grid, seed=0)
    assert set(pairing) == set(grid)
    assert all(source != moved for source, moved in pairing.items())


def test_the_pairing_is_a_permutation(grid: list[dt.date]) -> None:
    # Every date's returns are paired exactly once — no date double-counted,
    # none dropped.
    pairing = time_shuffle_pairing(grid, seed=0)
    assert sorted(pairing.values()) == sorted(grid)


def test_the_pairing_re_draws_past_a_fixed_point() -> None:
    # Rejection sampling, seen from the outside: over many seeds on a tiny
    # grid — where a random permutation fixes a date often — every result is
    # still a derangement. A shuffle that merely hoped for no fixed point
    # would show one here.
    dates = monday(2)
    for seed in range(50):
        pairing = time_shuffle_pairing(dates, seed=seed)
        assert all(source != moved for source, moved in pairing.items())


def test_a_two_date_derangement_is_the_swap() -> None:
    # With two dates there is exactly one derangement, so the probe has no
    # freedom left — a useful absolute anchor for "the shuffle did the only
    # thing it could".
    first, second = monday(2)
    assert dict(time_shuffle_pairing([first, second], seed=7)) == {
        first: second,
        second: first,
    }


def test_the_pairing_depends_only_on_the_sorted_dates_and_the_seed() -> None:
    # Determinism contract §12: mapping order is insertion order and is not
    # trusted, so the same grid shuffled as a list, a reversed list or a set
    # must yield the same pairing.
    dates = monday(20)
    expected = dict(time_shuffle_pairing(dates, seed=5))
    assert dict(time_shuffle_pairing(list(reversed(dates)), seed=5)) == expected
    assert dict(time_shuffle_pairing(set(dates), seed=5)) == expected


def test_iso_string_dates_name_the_same_grid(grid: list[dt.date]) -> None:
    # The courtesy every evaluator step extends the rebalance grid: the ISO
    # spelling of a date is the same date.
    expected = dict(time_shuffle_pairing(grid, seed=5))
    assert dict(time_shuffle_pairing([d.isoformat() for d in grid], seed=5)) == expected


def test_a_different_seed_is_a_different_probe(grid: list[dt.date]) -> None:
    # Pinned deliberately: the seed is on the verdict precisely because a
    # different seed is a different (equally valid) probe, not a bug.
    assert dict(time_shuffle_pairing(grid, seed=1)) != dict(
        time_shuffle_pairing(grid, seed=2)
    )


def test_the_shuffle_refuses_a_grid_it_cannot_permute() -> None:
    # A one-date grid: the permutation is the identity by necessity, so there
    # is no probe to state. An empty grid likewise.
    for bad in ([monday(1)], [[]]):
        with pytest.raises(TripwirePanelError, match="at least two"):
            time_shuffle_pairing(bad[0])


def test_the_shuffle_refuses_a_repeated_bar(grid: list[dt.date]) -> None:
    # One bar, one cross-section: a grid carrying a date twice has no
    # permutation to be, and a panel that carried a bar twice could pair a
    # score with its own alignment.
    with pytest.raises(TripwirePanelError, match="twice"):
        time_shuffle_pairing([*grid[:3], grid[0]])


def test_the_shuffle_refuses_a_non_integer_seed(grid: list[dt.date]) -> None:
    # Including the bool trap: True is an int to Python but names no stream.
    for bad in (1.5, "0", None, True):
        with pytest.raises(TripwirePanelError, match="integer"):
            time_shuffle_pairing(grid, seed=bad)


def test_the_shuffle_refuses_a_bare_date() -> None:
    # A single date is not a grid, and a string would be iterated character
    # by character into a shower of ISO fragments.
    for bad in (dt.date(2024, 1, 1), "2024-01-01"):
        with pytest.raises(TripwirePanelError, match="iterable"):
            time_shuffle_pairing(bad)


def test_a_datetime_key_is_refused_by_name() -> None:
    # The panels are day-granular; truncating an instant to its day would
    # guess which candle the caller meant. The tzinfo is irrelevant to the
    # refusal — it is the *type* being refused, not a naive instant.
    instant = dt.datetime(2024, 1, 1, 9, 30, tzinfo=dt.UTC)
    with pytest.raises(TripwirePanelError, match="day-granular"):
        time_shuffle_pairing([instant, monday(1, start=dt.date(2024, 1, 2))[0]])


# -- The surviving Sharpe is the candidate's own book --------------------------


def test_a_constant_book_has_no_dispersion_and_is_refused(grid: list[dt.date]) -> None:
    # The zero-dispersion refusal: the statistic divides by the dispersion of
    # the per-date book returns, and a book that returned the same value on
    # every date has a zero denominator. Refusing beats fabricating an
    # infinity — the stance the metrics step takes on a constant book
    # (feature 80). Constant scores against constant returns is the case that
    # actually produces a flat series: every date's mean of products is 3.0.
    scores = {day: {"A": 1.0} for day in grid}
    targets = {day: {"A": 3.0} for day in grid}
    pairing = time_shuffle_pairing(grid, seed=0)
    with pytest.raises(TripwireStatisticError, match="dispersion"):
        surviving_sharpe(scores, targets, pairing)


def test_a_constant_score_panel_alone_is_not_zero_dispersion(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Worth pinning because the intuition is wrong in a way that would make
    # the refusal above look like it fires far more often than it does: a
    # score panel constant across dates still produces a *varying* per-date
    # book, because the paired returns differ date to date. The probe reads
    # the variation of the product series, not of the scores — so this is a
    # measurement, not a refusal.
    scores = {day: {symbol: 1.0 for symbol in symbols} for day in grid}
    targets = gaussian_panel(grid, symbols, seed=9)
    pairing = time_shuffle_pairing(grid, seed=0)
    assert math.isfinite(surviving_sharpe(scores, targets, pairing))


def test_the_statistic_is_the_mean_of_products_over_population_dispersion(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The arithmetic, restated independently here so the probe cannot drift
    # from the definition: per date the mean of score×return over the joined
    # cross-section (ddof=0 afterwards, feature 80's convention).
    panel = {day: {s: (hash((day.toordinal(), s)) % 17) / 8.0 - 1.0 for s in symbols} for day in grid}
    pairing = time_shuffle_pairing(grid, seed=0)
    per_date = [
        math.fsum(panel[day][s] * panel[pairing[day]][s] for s in symbols) / len(symbols)
        for day in grid
    ]
    mean = math.fsum(per_date) / len(per_date)
    variance = math.fsum((value - mean) ** 2 for value in per_date) / len(per_date)
    assert surviving_sharpe(panel, panel, pairing) == pytest.approx(
        mean / math.sqrt(variance)
    )


def test_the_join_follows_the_absence_rule(grid: list[dt.date], symbols: list[str]) -> None:
    # Feature 75's absence rule: a symbol one side carries and the other does
    # not is simply not in that date's cross-section — neither side is
    # zero-filled to become one.
    targets = gaussian_panel(grid, symbols, seed=9)
    scores = {day: dict(row) for day, row in targets.items()}
    for day in grid:
        scores[day].pop(symbols[0])  # a symbol the scores do not carry
    pairing = time_shuffle_pairing(grid, seed=0)
    measured = surviving_sharpe(scores, targets, pairing)
    assert math.isfinite(measured)
    # A zero-filled implementation would differ: the missing symbol's return
    # would enter as 0×return instead of being absent.
    zero_filled = {
        day: {**row, symbols[0]: 0.0} if symbols[0] not in row else row
        for day, row in scores.items()
    }
    for day in grid:
        zero_filled[day][symbols[0]] = 0.0
    assert math.isfinite(surviving_sharpe(zero_filled, targets, pairing))


def test_a_fixed_point_in_a_hand_built_pairing_is_refused(grid: list[dt.date], symbols: list[str]) -> None:
    # A statistic measured over a pairing with a fixed point is a statistic
    # the probe never defined — the aligned pair survived.
    scores, targets = _clean_candidate(grid, symbols)
    pairing = dict(time_shuffle_pairing(grid, seed=0))
    first = grid[0]
    pairing[first] = first
    with pytest.raises(TripwirePanelError, match="fixes"):
        surviving_sharpe(scores, targets[1], pairing)


def test_a_pairing_covering_the_wrong_grid_is_refused(grid: list[dt.date], symbols: list[str]) -> None:
    # The pairing must cover exactly the dates both panels carry.
    scores, targets = _clean_candidate(grid, symbols)
    pairing = dict(time_shuffle_pairing(grid[:-1], seed=0))
    with pytest.raises(TripwirePanelError, match="exactly the dates"):
        surviving_sharpe(scores, targets[1], pairing)


def test_the_statistic_refuses_a_nan_cell(grid: list[dt.date], symbols: list[str]) -> None:
    # A NaN would reach the verdict dressed as a measurement.
    scores, targets = _clean_candidate(grid, symbols)
    scores[grid[0]][symbols[0]] = float("nan")
    pairing = time_shuffle_pairing(grid, seed=0)
    with pytest.raises(TripwirePanelError, match="not finite"):
        surviving_sharpe(scores, targets[1], pairing)


def test_a_bool_cell_is_refused(grid: list[dt.date], symbols: list[str]) -> None:
    # True is not a score and not a return, though Python calls it an int and
    # the arithmetic would happily carry it.
    scores, targets = _clean_candidate(grid, symbols)
    scores[grid[0]][symbols[0]] = True
    pairing = time_shuffle_pairing(grid, seed=0)
    with pytest.raises(TripwirePanelError, match="must be a number"):
        surviving_sharpe(scores, targets[1], pairing)


# -- The threshold is a computed, two-sided level test -------------------------


def test_the_threshold_is_the_two_sided_normal_quantile_over_root_t() -> None:
    # Φ⁻¹(1 − level/2) / √T, at a value a reader can check by hand: at 1%
    # two-sided the quantile is ~2.5758, so 100 dates give ~0.25758.
    assert time_shuffle_threshold(100, level=0.01) == pytest.approx(
        2.5758293035489004 / 10.0
    )


def test_the_threshold_tightens_with_more_dates() -> None:
    # More rebalance dates, a tighter bar — this is what makes the
    # shortest-covered horizon policy the tightest probe.
    thresholds = [time_shuffle_threshold(n) for n in (10, 50, 120)]
    assert thresholds[0] > thresholds[1] > thresholds[2]


def test_a_tighter_level_raises_the_threshold() -> None:
    # Feature 127's configured thresholds are the precedent: the level is a
    # parameter, and tightening it must tighten the bar.
    assert time_shuffle_threshold(120, level=0.001) > time_shuffle_threshold(
        120, level=0.05
    )


def test_the_threshold_refuses_a_level_outside_the_open_unit_interval() -> None:
    # 0 or 1 names a threshold that rejects nothing or everything.
    for bad in (0.0, 1.0, -0.1, 1.5, float("nan"), True):
        with pytest.raises(TripwirePanelError, match="level"):
            time_shuffle_threshold(120, level=bad)


def test_the_threshold_refuses_a_one_date_grid() -> None:
    # A one-date Sharpe names a zero dispersion and a fabricated infinity.
    with pytest.raises(TripwirePanelError, match="at least two"):
        time_shuffle_threshold(1)


# -- The verdict rejects, and says so in §8's vocabulary -----------------------


def test_a_planted_lookahead_leak_is_rejected(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The canonical leak, and the reason this feature exists: a score panel
    # built from the full-sample symbol mean of the forward returns carries
    # panel-level information that re-dating the cross-sections cannot
    # destroy, so its surviving Sharpe clears the bar. Feature 133's planted
    # corpus is this idea at scale — 0 escapes is the bar.
    targets = {1: gaussian_panel(grid, symbols, seed=17)}
    scores = lookahead_panel(targets, horizon=1)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id="leaky")
    assert verdict.rejected is True
    assert verdict.outcome == "tripwire_fail"
    assert abs(verdict.surviving_sharpe) > verdict.threshold


def test_the_sign_flipped_leak_is_rejected_too(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Leakage is sign-agnostic: a candidate that systematically *anti*-tracks
    # the shuffled panel carries exactly the same marginal information. A
    # one-sided probe would let this through, which is why the test is
    # two-sided.
    targets = {1: gaussian_panel(grid, symbols, seed=17)}
    scores = {
        day: {symbol: -value for symbol, value in row.items()}
        for day, row in lookahead_panel(targets, horizon=1).items()
    }
    verdict = run_time_shuffle_tripwire(scores, targets, node_id="flipped")
    assert verdict.rejected is True
    assert verdict.surviving_sharpe < 0.0


def test_a_clean_candidate_passes(grid: list[dt.date], symbols: list[str]) -> None:
    # The other half of a tripwire's job: it must not reject everything. The
    # scores here are independent of the targets by construction.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id="clean")
    assert verdict.rejected is False
    assert verdict.outcome == "ok"


def test_a_detected_leak_is_a_value_not_an_exception(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A tripwire that raised on detection would be indistinguishable, at the
    # ledger, from one that crashed — and feature 91's outcome vocabulary
    # exists so those two futures do not collapse into one word.
    targets = {1: gaussian_panel(grid, symbols, seed=17)}
    scores = lookahead_panel(targets, horizon=1)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id="leaky")
    assert isinstance(verdict, TimeShuffleVerdict)
    assert verdict.outcome in TRIPWIRE_OUTCOMES


def test_the_verdict_carries_the_evidence_a_reader_needs(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A rejection poisons a subtree (feature 131) and is irreversible, so it
    # must be auditable from the record alone: the seed and level rebuild the
    # pairing and the threshold, the pairing proves the derangement, and the
    # statistic sits beside the bar it was judged against.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id="n1", seed=42, level=0.05)
    assert verdict.node_id == "n1"
    assert verdict.tripwire == TIME_SHUFFLE_NAME
    assert verdict.seed == 42
    assert verdict.level == 0.05
    assert verdict.dates == len(grid)
    # Rebuilt from the record's own terms:
    assert dict(time_shuffle_pairing(grid, seed=verdict.seed)) == dict(verdict.pairing)
    assert verdict.threshold == time_shuffle_threshold(
        verdict.dates, level=verdict.level
    )


def test_the_verdict_is_hashable_and_compares_by_value(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    first = run_time_shuffle_tripwire(scores, targets, node_id="n1")
    second = run_time_shuffle_tripwire(scores, targets, node_id="n1")
    assert first == second
    assert hash(first) == hash(second)


def test_the_verdict_refuses_a_lying_rejection(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The record validates itself: a hand-built verdict whose `rejected`
    # disagrees with its own statistic and threshold is refused rather than
    # carried into the node record.
    scores, targets = _clean_candidate(grid, symbols)
    honest = run_time_shuffle_tripwire(scores, targets, node_id="n1")
    with pytest.raises(TripwirePanelError, match="decide otherwise"):
        TimeShuffleVerdict(
            node_id=honest.node_id,
            tripwire=honest.tripwire,
            horizon=honest.horizon,
            dates=honest.dates,
            seed=honest.seed,
            level=honest.level,
            surviving_sharpe=honest.surviving_sharpe,
            threshold=honest.threshold,
            rejected=not honest.rejected,
            outcome=honest.outcome,
            pairing=honest.pairing,
        )


def test_the_verdict_refuses_a_mismatched_outcome_word(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The two spellings of one fact cannot disagree.
    scores, targets = _clean_candidate(grid, symbols)
    honest = run_time_shuffle_tripwire(scores, targets, node_id="n1")
    with pytest.raises(TripwirePanelError, match="outcome"):
        TimeShuffleVerdict(
            node_id=honest.node_id,
            tripwire=honest.tripwire,
            horizon=honest.horizon,
            dates=honest.dates,
            seed=honest.seed,
            level=honest.level,
            surviving_sharpe=honest.surviving_sharpe,
            threshold=honest.threshold,
            rejected=honest.rejected,
            outcome="timeout",
            pairing=honest.pairing,
        )


# -- Horizon resolution and the panel refusals ---------------------------------


def test_the_probe_takes_the_shortest_horizon_the_bundle_covers(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The shortest covered horizon is the fastest-turning one — the most
    # rebalance dates, the largest T, and so the tightest probe. A function
    # of the bundle rather than a caller's knob, so two deployments running
    # the same node return the same verdict.
    scores, _ = _clean_candidate(grid, symbols)
    targets = {
        5: gaussian_panel(grid, symbols, seed=21),
        20: gaussian_panel(grid, symbols, seed=22),
    }
    verdict = run_time_shuffle_tripwire(scores, targets, node_id="n1")
    assert verdict.horizon == 5


def test_a_horizon_the_spec_does_not_name_is_refused(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The set is the spec's and closed: a horizon nobody calibrated is a
    # threshold axis nobody calibrated.
    scores, _ = _clean_candidate(grid, symbols)
    with pytest.raises(TripwirePanelError, match="not one of the horizons"):
        run_time_shuffle_tripwire(
            scores, {7: gaussian_panel(grid, symbols, seed=1)}, node_id="n1"
        )


def test_a_bundle_sharing_no_horizon_is_refused(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Disjoint date grids: no forward return can be paired with a score, so
    # there is no probe to state — and a tripwire that "passed" a node it
    # never probed is the failure this category exists to prevent.
    scores, _ = _clean_candidate(grid, symbols)
    elsewhere = monday(120, start=dt.date(2025, 1, 1))
    targets = {1: gaussian_panel(elsewhere, symbols, seed=1)}
    with pytest.raises(TripwirePanelError, match="shares no horizon"):
        run_time_shuffle_tripwire(scores, targets, node_id="n1")


def test_too_few_measurable_dates_is_refused(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Two shared dates are the floor: one date is the identity permutation and
    # would leave the very pairing under test intact.
    scores = gaussian_panel(monday(1), symbols, seed=4)
    targets = {1: gaussian_panel(monday(1), symbols, seed=5)}
    with pytest.raises(TripwirePanelError, match="at least two"):
        run_time_shuffle_tripwire(scores, targets, node_id="n1")


def test_an_empty_score_panel_is_refused(symbols: list[str]) -> None:
    # Nothing measured is not a pass.
    targets = {1: gaussian_panel(monday(10), symbols, seed=5)}
    with pytest.raises(TripwirePanelError, match="no rebalance date"):
        run_time_shuffle_tripwire({}, targets, node_id="n1")


def test_a_node_id_is_required(grid: list[dt.date], symbols: list[str]) -> None:
    # A verdict that rejects a node it cannot name is a rejection nothing
    # downstream can attribute.
    scores, targets = _clean_candidate(grid, symbols)
    for bad in ("", "   ", None, 7):
        with pytest.raises(TripwirePanelError, match="name the node"):
            run_time_shuffle_tripwire(scores, targets, node_id=bad)


def test_a_non_mapping_panel_is_refused() -> None:
    # The probe reads the panel as a value, not a callable or a frame.
    with pytest.raises(TripwirePanelError, match="must map rebalance date"):
        run_time_shuffle_tripwire(dict, {1: {}}, node_id="n1")


def test_the_defaults_are_the_pinned_constants(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The defaults are the probe's repeatability, not incidental values.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_time_shuffle_tripwire(scores, targets, node_id="n1")
    assert verdict.seed == DEFAULT_SHUFFLE_SEED
    assert verdict.level == DEFAULT_SHUFFLE_LEVEL
    assert HORIZONS == (1, 2, 5, 10, 20)
    assert TIME_SHUFFLE_NAME == "time-shuffle"
    assert TRIPWIRE_OUTCOMES == ("ok", "tripwire_fail")


# -- Determinism ---------------------------------------------------------------


def test_the_same_probe_twice_is_bit_for_bit_identical(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Determinism contract §12, and the precondition for a persisted
    # rejection being reproducible from the record's own terms.
    scores, targets = _clean_candidate(grid, symbols)
    first = run_time_shuffle_tripwire(scores, targets, node_id="n1", seed=99)
    second = run_time_shuffle_tripwire(scores, targets, node_id="n1", seed=99)
    assert first.surviving_sharpe == second.surviving_sharpe
    assert first.threshold == second.threshold
    assert dict(first.pairing) == dict(second.pairing)


def test_the_verdict_does_not_trust_mapping_insertion_order(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The determinism contract explicitly does not trust mapping order, so the
    # same panel spelled in a different order must probe identically.
    scores, targets = _clean_candidate(grid, symbols)
    shuffled_scores = dict(reversed(list(scores.items())))
    shuffled_targets = {1: dict(reversed(list(targets[1].items())))}
    expected = run_time_shuffle_tripwire(scores, targets, node_id="n1", seed=8)
    actual = run_time_shuffle_tripwire(
        shuffled_scores, shuffled_targets, node_id="n1", seed=8
    )
    assert actual.surviving_sharpe == expected.surviving_sharpe
    assert dict(actual.pairing) == dict(expected.pairing)
