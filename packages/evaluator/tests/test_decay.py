"""Feature 81 — the decay profile.

app_spec.xml feature 81: *"System computes a decay profile measuring
information coefficient at each of the five horizons, persisting it as a
stored array."*  docs/nullius-tech-architecture.md §6.1 names it inside step
8 (``compute_metrics    IC series, IR, turnover, decay, capacity, regime
attribution``), §9.2 names the artifact (``decay_profile.json``), and
docs/alpha-engine-prd.md's artifact block pins the shape and the axis
(``decay_profile: array    # IC at h = 1, 2, 5, 10, 20 periods``).

This suite tests the computation and the persistence as the two halves of one
feature sentence, because each is separately assertable and a bug in either
would be masked by the other:

* **the coefficient is the Spearman rank correlation** — asserted as the
  *property* that makes it the right coefficient for this pipeline: it is
  invariant to any strictly increasing rescale of the score (feature 74 threw
  the author's scale away on purpose, and §5.1 grants "sign and scale are
  free"), it is exactly negated when the signal is read in reverse, and it
  agrees with the closed form ``1 − 6Σd² / (n(n²−1))`` on an untied
  cross-section.  A module that had computed a Pearson correlation of the raw
  scores would fail the rescale property; one that broke ties ordinally would
  fail the negation property;
* **the five-entry stored array** — positional over ``(1, 2, 5, 10, 20)``, with
  ``None`` at a horizon the window was too short to measure.  Absence, not
  zero: the load-bearing distinction the whole package maintains, and the one
  that makes "no edge at 20 bars" readable as a finding rather than a silent
  zero;
* **the pairs are (score, post-cost return) joined on the priced grid** — the
  coefficient is measured against step 7's *net* returns, over the symbols the
  two sides share, with a scored date the panel never priced simply not
  measured and neither side zero-filled to meet the other;
* **the input contract** — step 7's own result and step 3's own output; a
  bundle that is not priced and scores that are malformed are both refused;
* **the refusals that would otherwise fabricate a zero** — a joined
  cross-section of one symbol, a constant score, a constant return, and a
  panel that shares no date with the scores.  Each returns ``0.0`` under the
  naive arithmetic, and each is refused here because a fabricated zero is the
  one value that neither promotes nor demotes and therefore hides the
  difference between "measured nothing" and "could not measure";
* **persistence** — the profile round-trips losslessly (including the null
  horizons and the per-date IC series), a re-persist upserts rather than
  doubles, a node never measured reads back ``None``, and the read path
  refuses a tampered row (an array edited while its terms were left alone, and
  the reverse), a terms object missing a horizon, and a row whose mean is not
  its own series' mean;
* **the records** — read-only capture, hashability, and the hand-built
  invariants (an entry filed under the wrong horizon, a mean that is not its
  own series' mean, a date count that disagrees with the series it summarises,
  a profile that measured no horizon at all).

The priced bundle is produced by the real step-4-through-7 path where the
provenance matters (a stub oracle over a real alignment, a stub fee schedule —
the same fixtures ``test_costs.py`` and ``test_capacity.py`` use, because an IC
measured against a bundle that never went through the gate would be an IC of a
world nobody ran) and hand-built where the test is about step 8's own contract.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
from contextlib import closing
from dataclasses import replace

import contract
import pytest

from evaluator import (
    DECAY_HORIZONS,
    DECAY_PROFILE_TABLE,
    HORIZONS,
    AlignedTargets,
    CostModelRef,
    CostQuote,
    CostRequest,
    DecayProfile,
    DecayStore,
    EvaluatorDecayError,
    EvaluatorStoreError,
    GatedTargets,
    HorizonDecay,
    OracleRequest,
    OracleResponse,
    PostCostReturns,
    PostCostSeries,
    RawScoreVector,
    SignalExecution,
    align_targets,
    apply_costs,
    compute_decay_profile,
    load_decay_profile,
    persist_decay_profile,
)

_START = dt.date(2026, 9, 1)
_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid."""
    return tuple(start + dt.timedelta(days=i) for i in range(count))


def _execution(
    dates,
    universe: tuple[str, ...] = ("AAA", "BBB"),
    *,
    snapshot_name: str = "snap_abc123",
) -> SignalExecution:
    """A hand-built execution — feature 73's output — for step 4 to align."""
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)),
            universe=universe,
            seed=7,
            contract_version=contract.CONTRACT_VERSION,
            problems=[],
        )
        for day in dates
    }
    return SignalExecution(
        snapshot_name=snapshot_name,
        code_hash="ab" * 32,
        seed=7,
        vectors=vectors,
    )


# The main scenario, on the same shape test_costs.py and test_capacity.py use:
# a 12-bar grid with three rebalance dates at its head — horizons 1, 2, 5 and
# 10 cover all three, horizon 20 covers none (the empty-but-carried case, and
# the profile's un-measured entry).
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = {"AAA": dict(zip(_GRID, _COMPOUND)), "BBB": dict(zip(_GRID, [50.0] * 12))}
_MAIN_ALIGNED = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)

#: The horizons the main scenario has coverage at.
_COVERED = (1, 2, 5, 10)


def _oracle(alignment: AlignedTargets):
    """A stub oracle whose real branch is the identity — §7.2's ask seam."""

    def ask(request: OracleRequest) -> OracleResponse:
        aligned = alignment.targets(request.horizon)
        return OracleResponse(
            target_series={day: dict(aligned.at(day)) for day in aligned.dates()},
            charges_budget=False,
        )

    return ask


def _flat_schedule(bps: float = 10.0):
    """A stub fee schedule: a flat ``bps`` charge on every symbol and bar.

    Deliberately not the real cost library — §6.2 and feature 69 keep the fee
    arithmetic in one shared library, and this suite's job is to prove the
    evaluator's *decay* half neither holds nor duplicates it.  The rate is
    nonzero so the IC really is measured against net returns and not, by
    accident of a zero charge, against the gross ones.
    """
    rate = bps / 10_000.0

    def schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: {symbol: rate for symbol in request.symbols}
                for day in request.gross_returns
            },
        )

    return schedule


def _gated(alignment: AlignedTargets = _MAIN_ALIGNED) -> GatedTargets:
    """Step 5's own result, through the real gate over a real alignment."""
    from evaluator import gate_targets

    return gate_targets(
        alignment,
        _oracle(alignment),
        node_id="node_1",
        campaign_id="camp_1",
        depth=2,
    )


def _priced() -> PostCostReturns:
    """Step 7's own result, over the real steps 4 through 7."""
    return apply_costs(
        _gated(), _flat_schedule(), node_id="node_1", cost_model=_REF
    )


def _hand_priced(
    values_by_horizon: dict[int, dict[dt.date, dict[str, float]]],
    *,
    node_id: str = "node_1",
    snapshot_name: str = "snap_abc123",
    rebalance_dates: tuple[dt.date, ...] | None = None,
) -> PostCostReturns:
    """A hand-built priced bundle — step 8's input, built to the test's order.

    Hand-built because most of this suite is about step 8's *own* contract —
    the coefficient, the axis, the refusals — which should be assertable
    without re-running steps 4 through 7 to arrange a shape.  Where the
    provenance of the bundle actually matters (the input-contract tests), the
    suite uses ``_priced``.
    """
    days = rebalance_dates or tuple(
        sorted({day for values in values_by_horizon.values() for day in values})
    )
    series: dict[int, PostCostSeries] = {}
    for horizon in HORIZONS:
        values = values_by_horizon.get(horizon, {})
        series[horizon] = PostCostSeries(
            horizon=horizon,
            snapshot_name=snapshot_name,
            venue=_VENUE,
            version=_VERSION,
            values={day: dict(row) for day, row in values.items()},
            charges={
                day: {symbol: 0.001 for symbol in row}
                for day, row in values.items()
            },
        )
    return PostCostReturns(
        node_id=node_id,
        snapshot_name=snapshot_name,
        rebalance_dates=days,
        cost_model=_REF,
        series=series,
        charges_budget=False,
    )


def _spearman_reference(
    scores: dict[str, float], returns: dict[str, float]
) -> float:
    """The Spearman correlation, spelled independently of the module under test.

    Spearman's coefficient *is* the Pearson correlation of the two
    cross-sections' average ranks, so that is what is written here — sorted
    positions, fractional ranks for ties, then the ordinary product-moment
    formula.  Spelled in its own terms rather than by calling anything in the
    package, so the suite pins the coefficient rather than trusting the
    implementation to define it.

    A second, independent spelling — the textbook shortcut
    ``1 − 6Σd² / (n(n²−1))`` — is asserted to agree on the untied
    cross-section, where it is exact; see
    :func:`test_the_ic_is_the_spearman_rank_correlation`.  It is *not* used
    here because that shortcut is wrong in the presence of ties: on the tied
    three-symbol case below it yields 0.875 where the true coefficient is
    ``√3/2``, and a reference that agrees with a common mistake would be worse
    than no reference at all.
    """
    symbols = sorted(set(scores) & set(returns))

    def ranks(values: dict[str, float]) -> dict[str, float]:
        ordered = sorted((values[symbol], symbol) for symbol in symbols)
        out: dict[str, float] = {}
        index = 0
        while index < len(ordered):
            stop = index
            while stop + 1 < len(ordered) and ordered[stop + 1][0] == ordered[index][0]:
                stop += 1
            for position in range(index, stop + 1):
                out[ordered[position][1]] = (index + stop + 2) / 2.0
            index = stop + 1
        return out

    score_ranks = ranks(scores)
    return_ranks = ranks(returns)
    n = float(len(symbols))
    score_mean = math.fsum(score_ranks.values()) / n
    return_mean = math.fsum(return_ranks.values()) / n
    covariance = math.fsum(
        (score_ranks[symbol] - score_mean) * (return_ranks[symbol] - return_mean)
        for symbol in symbols
    )
    score_spread = math.sqrt(
        math.fsum((score_ranks[symbol] - score_mean) ** 2 for symbol in symbols)
    )
    return_spread = math.sqrt(
        math.fsum((return_ranks[symbol] - return_mean) ** 2 for symbol in symbols)
    )
    return covariance / (score_spread * return_spread)


def _untied_shortcut(scores: dict[str, float], returns: dict[str, float]) -> float:
    """The textbook ``1 − 6Σd² / (n(n²−1))``, exact only when untied."""
    symbols = sorted(set(scores) & set(returns))
    score_order = {symbol: i for i, symbol in enumerate(sorted(symbols, key=scores.get))}
    return_order = {
        symbol: i for i, symbol in enumerate(sorted(symbols, key=returns.get))
    }
    n = len(symbols)
    squared = math.fsum(
        (score_order[symbol] - return_order[symbol]) ** 2 for symbol in symbols
    )
    return 1.0 - 6.0 * squared / (n * (n * n - 1))


#: A four-symbol cross-section on one date, with an untied score and an untied
#: return that agree in order — so the closed form above applies exactly.
_UNTIED_DATES = _days(3)[:2]
_UNTIED_PANEL = _hand_priced(
    {
        1: {
            _UNTIED_DATES[0]: {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03, "DDD": 0.04},
            _UNTIED_DATES[1]: {"AAA": 0.04, "BBB": 0.03, "CCC": 0.02, "DDD": 0.01},
        }
    }
)
_UNTIED_SCORES = {
    _UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0, "DDD": 4.0},
    _UNTIED_DATES[1]: {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0, "DDD": 4.0},
}


# -- The coefficient ------------------------------------------------------------


def test_the_ic_is_the_spearman_rank_correlation() -> None:
    # The coefficient, pinned against two independent spellings of it: the
    # Pearson correlation of the average ranks, and the textbook shortcut
    # ``1 − 6Σd² / (n(n²−1))``, which is exact precisely on an untied
    # cross-section — which is what this one is, for exactly this reason.  The
    # two agreeing is what makes "the IC is the Spearman correlation" a claim
    # rather than a restatement of the implementation.
    profile = compute_decay_profile(_UNTIED_PANEL, _UNTIED_SCORES)
    decay = profile.at(1)
    assert decay is not None
    for day in _UNTIED_DATES:
        returns = _UNTIED_PANEL.series[1].at(day)
        assert _untied_shortcut(_UNTIED_SCORES[day], returns) == pytest.approx(
            _spearman_reference(_UNTIED_SCORES[day], returns)
        )
        assert decay.ic(day) == pytest.approx(
            _spearman_reference(_UNTIED_SCORES[day], returns)
        )
    # The two dates are mirror images: the return order flips between them and
    # the score order does not, so the two coefficients are exact opposites.
    assert decay.ic(_UNTIED_DATES[0]) == 1.0
    assert decay.ic(_UNTIED_DATES[1]) == -1.0
    # And the entry in the array is the mean of the series.
    assert decay.mean_ic == pytest.approx(0.0)


def test_the_ic_ignores_the_author_scale() -> None:
    # Feature 74 threw the author's scale away on purpose and §5.1 grants that
    # "sign and scale are free" — so the decay profile must not move when the
    # score is rescaled by any strictly increasing map.  A Pearson correlation
    # of the raw scores would fail this, which is why it is the assertion that
    # pins the rank transform rather than merely asserting a number.
    baseline = compute_decay_profile(_UNTIED_PANEL, _UNTIED_SCORES)

    # A different multiplicative scale, a shift, and a strictly increasing
    # nonlinear map that is *not* affine — all three must land on the same IC.
    for transform in (
        lambda value: value * 1000.0,
        lambda value: value + 7.5,
        lambda value: math.exp(value),
        lambda value: value**3,
    ):
        rescaled = {
            day: {symbol: transform(score) for symbol, score in row.items()}
            for day, row in _UNTIED_SCORES.items()
        }
        moved = compute_decay_profile(_UNTIED_PANEL, rescaled)
        assert moved.as_array() == baseline.as_array()


def test_the_ic_is_negated_when_the_signal_is_read_in_reverse() -> None:
    # The symmetry property ``normalize_scores`` pins its average-rank method
    # for: a signal read in reverse is the mirror portfolio, so every
    # coefficient flips sign and the array mirrors with it.  Ordinal tie
    # breaking would break this as soon as a tie appeared — hence the tied
    # cross-section, which is also the case that makes the average rank
    # load-bearing rather than cosmetic.
    tied_scores = {
        _UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 1.0, "CCC": 3.0, "DDD": 4.0},
        _UNTIED_DATES[1]: {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0, "DDD": 4.0},
    }
    forward = compute_decay_profile(_UNTIED_PANEL, tied_scores)
    reverse = compute_decay_profile(
        _UNTIED_PANEL,
        {
            day: {symbol: -score for symbol, score in row.items()}
            for day, row in tied_scores.items()
        },
    )
    forward_array = forward.as_array()
    reverse_array = reverse.as_array()
    assert len(forward_array) == len(reverse_array) == 5
    for front, back in zip(forward_array, reverse_array):
        # Both are measured at horizon 1 (the panel prices it) and both are
        # None at horizon 20 (the panel never does), so the mirror is asserted
        # on the entries that exist rather than assumed onto the nulls.
        if front is None:
            assert back is None
        else:
            assert back == pytest.approx(-front)
    assert forward_array[0] is not None


def test_a_tied_cross_section_uses_the_average_rank() -> None:
    # The tie convention is feature 74's, restated: tied symbols share the mean
    # of the ranks they would have occupied.  Asserted against the closed form
    # over average ranks rather than against a hand-computed constant, so the
    # suite states *which* convention it means.
    tied = {"AAA": 1.0, "BBB": 1.0, "CCC": 3.0}
    returns = {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03}
    panel = _hand_priced({1: {_UNTIED_DATES[0]: returns}})
    profile = compute_decay_profile(panel, {_UNTIED_DATES[0]: tied})
    decay = profile.at(1)
    assert decay is not None
    assert decay.ic(_UNTIED_DATES[0]) == pytest.approx(
        _spearman_reference(tied, returns)
    )
    # Three symbols with average ranks 1.5/1.5/3: the formula's denominator is
    # n(n²−1) = 24, so this is a genuinely fractional coefficient rather than
    # the ±1 an ordinal method would produce.
    assert -1.0 < decay.ic(_UNTIED_DATES[0]) < 1.0


def test_the_ic_is_measured_against_post_cost_returns() -> None:
    # The pairing is what makes the profile a statement about the edge the
    # signal would have earned.  The proof: measure the same scores against the
    # same *gross* returns and the coefficient moves — because the schedule
    # charged a different rate per symbol.
    gross = _hand_priced({1: {_UNTIED_DATES[0]: {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03}}})
    # A schedule that charges AAA most and CCC least *reverses* the net order:
    # the price difference is chosen so the net returns come out descending.
    net = PostCostReturns(
        node_id=gross.node_id,
        snapshot_name=gross.snapshot_name,
        rebalance_dates=gross.rebalance_dates,
        cost_model=_REF,
        series={
            horizon: replace(
                gross.series[horizon],
                values={
                    _UNTIED_DATES[0]: {"AAA": 0.05, "BBB": 0.02, "CCC": -0.01}
                },
                charges={_UNTIED_DATES[0]: {"AAA": -0.04, "BBB": 0.0, "CCC": 0.04}},
            )
            if horizon == 1
            else gross.series[horizon]
            for horizon in HORIZONS
        },
        charges_budget=False,
    )
    scores = {_UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}}
    assert compute_decay_profile(gross, scores).at(1).ic(_UNTIED_DATES[0]) == 1.0
    assert compute_decay_profile(net, scores).at(1).ic(_UNTIED_DATES[0]) == -1.0


def test_unscored_and_unpriced_symbols_are_dropped_from_the_pair() -> None:
    # Both sides legitimately carry symbols the other does not: a symbol the
    # signal scored may have no return at ``h`` (feature 75's absence rule), and
    # the returns carry symbols the signal never scored.  Only the joined
    # cross-section is correlated, and neither side is zero-filled to meet the
    # other — so a score for an unpriced symbol must not move the coefficient.
    returns = {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03}
    panel = _hand_priced({1: {_UNTIED_DATES[0]: returns}})
    baseline = compute_decay_profile(
        panel, {_UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}}
    )
    padded = compute_decay_profile(
        panel,
        {
            _UNTIED_DATES[0]: {
                "AAA": 1.0,
                "BBB": 2.0,
                "CCC": 3.0,
                "ZZZ": 99.0,  # scored, but the panel never priced it
            }
        },
    )
    assert padded.as_array() == baseline.as_array()


def test_a_date_the_panel_never_priced_is_not_measured() -> None:
    # A score at a date the returns never priced has no forward return to
    # correlate against, and inventing one is the look-ahead the alignment
    # refuses by construction.  The date is simply absent from the series.
    panel = _hand_priced({1: {_UNTIED_DATES[0]: {"AAA": 0.01, "BBB": 0.02}}})
    profile = compute_decay_profile(
        panel,
        {
            _UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 2.0},
            _UNTIED_DATES[1]: {"AAA": 1.0, "BBB": 2.0},
        },
    )
    decay = profile.at(1)
    assert decay is not None
    assert decay.dates == 1
    assert decay.ic(_UNTIED_DATES[1]) is None


# -- The array ------------------------------------------------------------------


def test_the_array_is_five_long_over_the_spec_horizons() -> None:
    profile = compute_decay_profile(_priced(), _main_scores())
    array = profile.as_array()
    assert len(array) == 5
    assert profile.horizons == DECAY_HORIZONS == HORIZONS
    # Inside [−1, 1] wherever it was measured, and ``None`` at horizon 20 —
    # the 12-bar grid cannot speak for a 20-bar forward return.
    for horizon, entry in zip(DECAY_HORIZONS, array):
        if entry is None:
            assert horizon not in _COVERED
        else:
            assert -1.0 <= entry <= 1.0
    assert array[0] is not None and array[1] is not None
    assert array[2] is not None and array[3] is not None
    assert array[4] is None


def test_an_un_measured_horizon_is_absent_not_zero() -> None:
    # The distinction the whole package maintains, and the one the stored array
    # would destroy if it zero-filled: "the window never spanned 20 bars" and
    # "the signal has no edge at 20 bars" are different findings, and only the
    # first is true here.
    profile = compute_decay_profile(_priced(), _main_scores())
    assert profile.at(20) is None
    assert profile.as_array()[4] is None
    assert 20 not in profile.measured_horizons
    assert 20 in profile.horizons
    # And the measured horizons are exactly the covered ones.
    assert profile.measured_horizons == _COVERED


def test_each_entry_is_the_mean_of_its_own_series() -> None:
    # The array is not a second computation: entry ``i`` is the mean of the
    # per-date coefficients the entry carries, which is what makes the stored
    # row checkable against itself on the read path.
    profile = compute_decay_profile(_priced(), _main_scores())
    for horizon in profile.measured_horizons:
        decay = profile.at(horizon)
        assert decay is not None
        assert decay.dates == len(decay.ic_series)
        # Not every rebalance date is measured at every horizon: a ``h``-bar
        # forward return needs ``h`` bars after the bar, so the panel's last
        # rebalance date has no horizon-10 analogue.  That is the feature 75
        # absence rule arriving on the return side, and the count is asserted
        # as *at most* the rebalance dates rather than assumed equal to them —
        # the equality is pinned per horizon below.
        assert 1 <= decay.dates <= len(_REBALANCE)
        assert decay.mean_ic == pytest.approx(
            math.fsum(decay.ic_series.values()) / decay.dates
        )
        assert profile.as_array()[DECAY_HORIZONS.index(horizon)] == decay.mean_ic
    # Horizon 1 spans the whole grid, so it does measure every rebalance date.
    assert profile.at(1).dates == len(_REBALANCE)


def test_the_profile_decays_when_the_signal_has_a_short_half_life() -> None:
    # The feature's *point*: the profile must be able to show decay.  A panel
    # whose scores order the cross-section correctly one bar ahead and
    # incorrectly twenty bars ahead must produce a monotonically falling curve,
    # which is what the live loop reads a half-life off.
    days = _days(3)
    returns = {
        1: {days[0]: {"AAA": 0.03, "BBB": 0.02, "CCC": 0.01}},
        2: {days[0]: {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03}},
        5: {days[0]: {"AAA": 0.02, "BBB": 0.01, "CCC": 0.00}},
        10: {days[0]: {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03}},
        20: {days[0]: {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03}},
    }
    panel = _hand_priced(returns)
    scores = {days[0]: {"AAA": 3.0, "BBB": 2.0, "CCC": 1.0}}
    array = compute_decay_profile(panel, scores).as_array()
    assert array[0] == 1.0  # horizon 1 agrees with the ordering
    assert array[1] == -1.0  # horizon 2 inverts it
    assert array[4] == -1.0  # and horizon 20 has fully decayed


def _main_scores() -> dict[dt.date, dict[str, float]]:
    """Normalized-looking scores over the main grid's rebalance dates.

    Hand-built rather than run through ``normalize_scores``: this member's
    contract is *step 3's output*, and a test that had to stand up the Polars
    boundary to arrange an input would be testing feature 74 instead.  The
    cross-section is four symbols so no horizon degenerates, and the values are
    ordered to disagree with the priced returns at the long horizons — the
    decay shape the assertions above read.
    """
    return {
        _REBALANCE[0]: {"AAA": 2.0, "BBB": 1.0, "CCC": -1.0, "DDD": -2.0},
        _REBALANCE[1]: {"AAA": 1.0, "BBB": 2.0, "CCC": -2.0, "DDD": -1.0},
        _REBALANCE[2]: {"AAA": -1.0, "BBB": -2.0, "CCC": 2.0, "DDD": 1.0},
    }


# -- The input contract ---------------------------------------------------------


def test_the_input_is_step_sevens_own_result() -> None:
    with pytest.raises(EvaluatorDecayError, match="PostCostReturns"):
        compute_decay_profile(  # type: ignore[arg-type]
            {"node_1": "not a bundle"}, _main_scores()
        )


def test_the_scores_must_be_a_mapping_of_dates_to_cross_sections() -> None:
    with pytest.raises(EvaluatorDecayError, match="must map rebalance date"):
        compute_decay_profile(_priced(), ["not", "a", "mapping"])  # type: ignore[arg-type]


def test_empty_scores_are_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="no cross-section"):
        compute_decay_profile(_priced(), {})


def test_a_non_finite_score_is_refused() -> None:
    scores = _main_scores()
    scores[_REBALANCE[0]]["AAA"] = float("nan")
    with pytest.raises(EvaluatorDecayError, match="not finite"):
        compute_decay_profile(_priced(), scores)


def test_a_non_numeric_score_is_refused() -> None:
    scores = _main_scores()
    scores[_REBALANCE[0]]["AAA"] = "high"  # type: ignore[assignment]
    with pytest.raises(EvaluatorDecayError, match="must be a number"):
        compute_decay_profile(_priced(), scores)


def test_a_datetime_keyed_score_is_refused() -> None:
    # A datetime names an instant; the coefficient pairs one rebalance *date's*
    # cross-section with that date's forward return, and truncating silently
    # would be a guess about which bar the score belongs to.
    scores = {
        dt.datetime.combine(_REBALANCE[0], dt.time(tzinfo=dt.UTC)): {
            "AAA": 1.0,
            "BBB": 2.0,
        }
    }
    with pytest.raises(EvaluatorDecayError, match="datetime"):
        compute_decay_profile(_priced(), scores)


def test_iso_string_keys_are_accepted() -> None:
    # The wire spelling a service boundary uses; a whole-market fetch and a
    # scored-universe fetch must measure identically however the caller spelled
    # its keys.
    as_dates = compute_decay_profile(_priced(), _main_scores())
    as_strings = {
        day.isoformat(): row for day, row in _main_scores().items()
    }
    assert compute_decay_profile(_priced(), as_strings).as_array() == as_dates.as_array()


def test_duplicate_date_spellings_are_refused() -> None:
    scores = dict(_main_scores())
    scores[_REBALANCE[0].isoformat()] = {"AAA": 1.0, "BBB": 2.0}
    with pytest.raises(EvaluatorDecayError, match="twice"):
        compute_decay_profile(_priced(), scores)


# -- The refusals that would fabricate a zero -----------------------------------


def test_a_single_symbol_cross_section_is_refused() -> None:
    # The naive arithmetic returns 0.0 here — the only value available — and
    # that value neither promotes nor demotes, so it silently hides "this date
    # could not be measured" behind "this date measured nothing".
    panel = _hand_priced({1: {_UNTIED_DATES[0]: {"AAA": 0.01}}})
    with pytest.raises(EvaluatorDecayError, match="cross-section of one"):
        compute_decay_profile(panel, {_UNTIED_DATES[0]: {"AAA": 1.0}})


def test_a_constant_score_is_refused() -> None:
    # Feature 74's own refusal, arriving from the other side of the pipeline:
    # every score identical is the signal expressing no preference, so the rank
    # spread is zero and there is no order to correlate.
    panel = _hand_priced(
        {1: {_UNTIED_DATES[0]: {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03}}}
    )
    with pytest.raises(EvaluatorDecayError, match="constant scores"):
        compute_decay_profile(
            panel, {_UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 1.0, "CCC": 1.0}}
        )


def test_a_constant_return_is_refused() -> None:
    # The same degeneracy from the return side: the cross-section's outcome had
    # no order to agree with.  Named separately from the score case because the
    # two are different facts about the world, not the same bug twice.
    panel = _hand_priced(
        {1: {_UNTIED_DATES[0]: {"AAA": 0.02, "BBB": 0.02, "CCC": 0.02}}}
    )
    with pytest.raises(EvaluatorDecayError, match="constant post-cost returns"):
        compute_decay_profile(
            panel, {_UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}}
        )


def test_a_panel_sharing_no_date_with_the_scores_is_refused() -> None:
    # Every horizon un-measured: five nulls would report a measured decay for
    # an evaluation whose scores and returns never met.
    far = _days(3, dt.date(2027, 1, 1))
    panel = _hand_priced({1: {far[0]: {"AAA": 0.01, "BBB": 0.02}}})
    with pytest.raises(EvaluatorDecayError, match="share no rebalance date"):
        compute_decay_profile(
            panel, {_UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 2.0}}
        )


def test_a_refusal_names_the_horizon_and_the_date() -> None:
    # The message is the feature's usability: a caller reading a failed
    # evaluation needs to know *which* horizon on *which* bar degenerated,
    # because the repair is per-horizon (a wider window) or per-date (a
    # labeler/ingest gap), not global.
    panel = _hand_priced(
        {
            1: {_UNTIED_DATES[0]: {"AAA": 0.01, "BBB": 0.02}},
            2: {_UNTIED_DATES[0]: {"AAA": 0.01, "BBB": 0.01}},
        }
    )
    scores = {_UNTIED_DATES[0]: {"AAA": 1.0, "BBB": 2.0}}
    with pytest.raises(EvaluatorDecayError) as caught:
        compute_decay_profile(panel, scores)
    message = str(caught.value)
    assert "horizon 2" in message
    assert _UNTIED_DATES[0].isoformat() in message


# -- Persistence ----------------------------------------------------------------


def test_the_profile_round_trips_losslessly() -> None:
    profile = persist_decay_profile(compute_decay_profile(_priced(), _main_scores()))
    stored = load_decay_profile(profile.node_id, profile.cost_model)
    assert stored is not None
    assert stored.as_array() == profile.as_array()
    assert stored.horizon_ics == profile.horizon_ics
    assert stored == profile
    assert stored.snapshot_name == profile.snapshot_name
    # The null horizon survives the round trip as None — a JSON null on the
    # wire, never a zero.
    assert stored.as_array()[4] is None
    # And every per-date coefficient survives exactly.
    for horizon in profile.measured_horizons:
        before, after = profile.at(horizon), stored.at(horizon)
        assert before is not None and after is not None
        assert dict(after.ic_series) == dict(before.ic_series)


def test_a_node_never_measured_reads_back_none() -> None:
    assert load_decay_profile("node_never", _REF) is None


def test_a_re_persist_upserts_rather_than_doubling() -> None:
    # §9.2's array is read entry by entry against a forward one; a second row
    # for the same evaluation would read as a second observation of the same
    # signal's decay.
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    persist_decay_profile(profile)
    store = DecayStore.resolve()
    with store._connect() as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {DECAY_PROFILE_TABLE}"
        ).fetchone()[0]
    assert count == 1
    assert load_decay_profile(profile.node_id, profile.cost_model) == profile


def test_a_changed_measurement_under_the_same_key_wins() -> None:
    # The key names the inputs, so a re-measurement over the same bundle
    # refreshes the stored array — unlike the identity store, where a changed
    # value under an existing key is a contradiction.  Here it is a producer
    # that re-measured, and the last write is the current answer.
    first = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(first)
    moved = compute_decay_profile(
        _priced(),
        {
            day: {symbol: -score for symbol, score in row.items()}
            for day, row in _main_scores().items()
        },
    )
    persist_decay_profile(moved)
    stored = load_decay_profile(first.node_id, first.cost_model)
    assert stored is not None
    assert stored.as_array() != first.as_array()
    assert stored.as_array() == moved.as_array()


def test_persisting_a_non_profile_is_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="DecayProfile"):
        persist_decay_profile({"node_id": "node_1"})  # type: ignore[arg-type]


def test_a_missing_store_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(EvaluatorStoreError, match="DATABASE_URL is not set"):
        persist_decay_profile(compute_decay_profile(_priced(), _main_scores()))
    with pytest.raises(EvaluatorStoreError, match="DATABASE_URL is not set"):
        load_decay_profile("node_1", _REF)


def test_an_unsupported_url_scheme_is_refused() -> None:
    with pytest.raises(EvaluatorStoreError, match="unsupported"):
        load_decay_profile("node_1", _REF, database_url="postgresql://db/x")


def test_an_empty_node_id_is_refused() -> None:
    with pytest.raises(EvaluatorStoreError, match="non-empty string"):
        load_decay_profile("", _REF)


def test_the_store_binds_to_one_cost_model() -> None:
    # The cost model is part of the question, not a filter over it: an IC
    # measured under one fee schedule is not a partial answer to a question
    # about another, because the two net different returns out of the same
    # gross ones.
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    other = CostModelRef(venue=_VENUE, version="2027.01.1")
    assert load_decay_profile(profile.node_id, other) is None


# -- The tamper checks on the read path -----------------------------------------


def _stored_row(node_id: str, ref: CostModelRef = _REF) -> tuple:
    """The raw row, so a test can edit one half of it in place."""
    store = DecayStore.resolve()
    with store._connect() as connection:
        return connection.execute(
            f"""
            SELECT snapshot_name, decay_array, horizon_terms
            FROM {DECAY_PROFILE_TABLE}
            WHERE node_id = ? AND venue = ? AND version = ?
            """,
            (node_id, ref.venue, ref.version),
        ).fetchone()


def _write_row(node_id: str, column: str, payload: str) -> None:
    """Overwrite one column of a stored row, outside this package's writer."""
    store = DecayStore.resolve()
    with store._connect() as connection, connection:
        connection.execute(
            f"UPDATE {DECAY_PROFILE_TABLE} SET {column} = ? "
            "WHERE node_id = ?",
            (payload, node_id),
        )


def test_an_array_edited_away_from_its_terms_is_refused() -> None:
    # The feature's own value is the array, so an array that is not the array
    # its terms measure is a decay curve the live loop would read and act on —
    # the exact class of lie the store exists to refuse.
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _, array_json, _ = _stored_row(profile.node_id)
    forged = json.loads(array_json)
    forged[0] = 0.0 if forged[0] != 0.0 else 1.0
    _write_row(profile.node_id, "decay_array", json.dumps(forged))

    with pytest.raises(EvaluatorStoreError, match="disagrees with itself"):
        load_decay_profile(profile.node_id, _REF)


def test_terms_edited_away_from_the_array_are_refused() -> None:
    # The same tamper from the other side: the array is untouched and the terms
    # were rewritten, which the re-derivation catches because the profile is
    # rebuilt *from the terms* and then compared to the stored array.
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _, _, terms_json = _stored_row(profile.node_id)
    terms = json.loads(terms_json)
    entry = terms[str(_COVERED[0])]
    series = entry["ic_series"]
    # Rewrite the series consistently (so the entry is still self-consistent)
    # but to different numbers — only the stored array can catch this.
    for day in series:
        series[day] = series[day] / 2.0
    entry["mean_ic"] = sum(series.values()) / len(series)
    _write_row(profile.node_id, "horizon_terms", json.dumps(terms))

    with pytest.raises(EvaluatorStoreError, match="disagrees with itself"):
        load_decay_profile(profile.node_id, _REF)


def test_a_mean_that_is_not_its_own_series_mean_is_refused() -> None:
    # Caught by the record rather than by the array comparison: HorizonDecay
    # re-derives its own mean and refuses a row that is not its own terms'
    # answer — the defence the identity store applies to a hash that does not
    # fold from its terms.
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _, _, terms_json = _stored_row(profile.node_id)
    terms = json.loads(terms_json)
    terms[str(_COVERED[0])]["mean_ic"] += 0.25
    _write_row(profile.node_id, "horizon_terms", json.dumps(terms))

    with pytest.raises(EvaluatorStoreError, match="does not reconstruct"):
        load_decay_profile(profile.node_id, _REF)


def test_a_mean_that_is_not_its_own_series_mean_is_trusted_by_no_reader() -> None:
    # The same tamper again, this time on the terms of *every* measured
    # horizon, so the reconstruction fails before any array comparison could
    # happen — the record refuses the row on its own terms.  Asserted
    # separately because a suite that only ever caught this through the array
    # comparison would not notice if ``HorizonDecay`` stopped re-deriving its
    # own mean.
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _, _, terms_json = _stored_row(profile.node_id)
    terms = json.loads(terms_json)
    for horizon in _COVERED:
        terms[str(horizon)]["mean_ic"] += 0.25
    _write_row(profile.node_id, "horizon_terms", json.dumps(terms))

    with pytest.raises(EvaluatorStoreError, match="disagrees with itself"):
        load_decay_profile(profile.node_id, _REF)


def test_a_terms_object_missing_a_horizon_is_refused() -> None:
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _, _, terms_json = _stored_row(profile.node_id)
    terms = json.loads(terms_json)
    del terms["20"]
    _write_row(profile.node_id, "horizon_terms", json.dumps(terms))

    with pytest.raises(EvaluatorStoreError, match="exactly one entry per horizon"):
        load_decay_profile(profile.node_id, _REF)


def test_an_array_of_the_wrong_length_is_refused() -> None:
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _write_row(profile.node_id, "decay_array", json.dumps([0.1, 0.1]))

    with pytest.raises(EvaluatorStoreError, match="positional over the spec's five horizons"):
        load_decay_profile(profile.node_id, _REF)


def test_non_finite_stored_json_is_refused() -> None:
    # ``json.dumps`` will happily emit ``NaN``, which is not JSON — so a row
    # carrying one did not come out of this store's writer, and the decode
    # names it rather than letting a NaN reach the array.
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _write_row(profile.node_id, "decay_array", "[NaN, 0.1, 0.1, 0.1, 0.1]")

    with pytest.raises(EvaluatorStoreError, match="NaN"):
        load_decay_profile(profile.node_id, _REF)
    # ``Infinity`` is the other spelling ``json.loads`` accepts and JSON does
    # not, and it is refused for the same reason.  The message renders the
    # parsed value rather than the wire text, so it names ``inf`` — the
    # actionable part is the *position*, which points at the offending entry.
    _write_row(profile.node_id, "decay_array", "[Infinity, 0.1, 0.1, 0.1, 0.1]")
    with pytest.raises(EvaluatorStoreError, match="position 0"):
        load_decay_profile(profile.node_id, _REF)


def test_a_stored_series_with_a_bad_date_is_refused() -> None:
    profile = compute_decay_profile(_priced(), _main_scores())
    persist_decay_profile(profile)
    _, _, terms_json = _stored_row(profile.node_id)
    terms = json.loads(terms_json)
    entry = terms[str(_COVERED[0])]
    entry["ic_series"]["not-a-date"] = 0.1
    _write_row(profile.node_id, "horizon_terms", json.dumps(terms))

    # Named by the date decode rather than reported as a generic
    # "does not reconstruct": the offending value is the actionable part of the
    # message, since the repair is to find out what wrote a non-ISO key.
    with pytest.raises(EvaluatorStoreError, match="ISO 8601 calendar date"):
        load_decay_profile(profile.node_id, _REF)


def test_the_store_creates_its_schema_idempotently(tmp_path) -> None:
    # A fresh database and an existing one take one path — the contract every
    # store in this package states, and what makes a migration step unnecessary
    # for this member.
    url = f"sqlite:///{tmp_path / 'decay.db'}"
    first = DecayStore(url)
    profile = compute_decay_profile(_priced(), _main_scores())
    first.persist(profile)
    second = DecayStore(url)
    assert second.load(profile.node_id, _REF) == profile
    # A sqlite file that is actually a sqlite database, not e.g. a stray empty
    # file: the schema landed.
    connection = sqlite3.connect(tmp_path / "decay.db")
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert DECAY_PROFILE_TABLE in tables


def test_a_store_resolved_from_the_environment_is_the_ambient_one() -> None:
    # The module-level functions resolve ``DATABASE_URL`` through
    # :meth:`DecayStore.resolve`, so an operator who configured the store once
    # does not have to thread the URL through every call — and an explicitly
    # built store pointed at the same URL reads the same rows.
    profile = persist_decay_profile(compute_decay_profile(_priced(), _main_scores()))
    ambient = os.environ["DATABASE_URL"]
    assert DecayStore.resolve().database_url == ambient
    assert DecayStore(ambient).load(profile.node_id, _REF) == profile
    # The no-argument spellings and the explicit ones are the same call.
    assert load_decay_profile(profile.node_id, _REF, database_url=ambient) == profile


def test_an_in_memory_store_is_per_connection() -> None:
    # ``sqlite://`` resolves to ``None``, which ``_connect`` reads as
    # ":memory:" — per-connection, so a row written through one connection is
    # invisible to the next.  Stated as an assertion rather than left implicit
    # because it is *why* this suite's isolation fixture uses a file, and a
    # reader who assumed otherwise would think the round-trips above were
    # testing persistence when they were testing a shared dict.
    store = DecayStore("sqlite://")
    profile = compute_decay_profile(_priced(), _main_scores())
    store.persist(profile)
    assert store.load(profile.node_id, _REF) is None
    # The write itself succeeded — it is the *second* connection that cannot
    # see it, so this is not a silent failure of ``persist``.
    with closing(store._connect()) as connection:
        assert connection.execute(
            f"SELECT COUNT(*) FROM {DECAY_PROFILE_TABLE}"
        ).fetchone()[0] == 0


# -- The records -----------------------------------------------------------------


def test_the_profile_is_read_only_and_hashable() -> None:
    profile = compute_decay_profile(_priced(), _main_scores())
    decay = profile.at(1)
    assert decay is not None
    with pytest.raises(TypeError):
        profile.horizon_ics[1] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        decay.ic_series[_REBALANCE[0]] = 0.0  # type: ignore[index]
    assert hash(profile) == hash(compute_decay_profile(_priced(), _main_scores()))


def test_the_five_horizon_shape_is_a_promise() -> None:
    # A consumer iterating the axis of a decay profile must find five entries,
    # including the ones a short window left with nothing to measure — the same
    # shape promise features 75, 76, 79 and 82 make.
    profile = compute_decay_profile(_priced(), _main_scores())
    assert tuple(sorted(profile.horizon_ics)) == HORIZONS
    assert len(profile.as_array()) == 5
    for horizon in HORIZONS:
        assert profile.at(horizon) is None or profile.at(horizon).horizon == horizon


def test_a_horizon_outside_the_axis_is_refused() -> None:
    profile = compute_decay_profile(_priced(), _main_scores())
    with pytest.raises(EvaluatorDecayError, match="not one of the horizons"):
        profile.at(3)


def test_a_hand_built_profile_missing_a_horizon_is_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="one entry per horizon"):
        DecayProfile(
            node_id="node_1",
            snapshot_name="snap_abc123",
            cost_model=_REF,
            horizon_ics={1: _hand_decay(1), 2: _hand_decay(2)},
        )


def test_a_hand_built_profile_with_no_measured_horizon_is_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="no measured horizon"):
        DecayProfile(
            node_id="node_1",
            snapshot_name="snap_abc123",
            cost_model=_REF,
            horizon_ics={horizon: None for horizon in HORIZONS},
        )


def test_an_entry_filed_under_the_wrong_horizon_is_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="carries horizon"):
        DecayProfile(
            node_id="node_1",
            snapshot_name="snap_abc123",
            cost_model=_REF,
            horizon_ics={
                horizon: (None if horizon != 2 else _hand_decay(5))
                for horizon in HORIZONS
            },
        )


def test_a_mean_that_is_not_its_series_mean_is_refused_at_construction() -> None:
    with pytest.raises(EvaluatorDecayError, match="disagrees with itself"):
        HorizonDecay(
            horizon=1,
            dates=2,
            mean_ic=0.5,
            ic_series={_UNTIED_DATES[0]: 0.0, _UNTIED_DATES[1]: 0.0},
        )


def test_a_date_count_that_disagrees_with_the_series_is_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="denominator"):
        HorizonDecay(
            horizon=1,
            dates=3,
            mean_ic=0.0,
            ic_series={_UNTIED_DATES[0]: 0.0, _UNTIED_DATES[1]: 0.0},
        )


def test_an_empty_ic_series_is_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="empty ic_series"):
        HorizonDecay(horizon=1, dates=1, mean_ic=0.0, ic_series={})


def test_a_non_finite_ic_entry_is_refused() -> None:
    with pytest.raises(EvaluatorDecayError, match="not finite"):
        HorizonDecay(
            horizon=1,
            dates=1,
            mean_ic=float("nan"),
            ic_series={_UNTIED_DATES[0]: float("nan")},
        )


def test_a_horizon_outside_the_axis_is_refused_at_construction() -> None:
    with pytest.raises(EvaluatorDecayError, match="not one of the horizons"):
        _hand_decay(3)


def _hand_decay(horizon: int) -> HorizonDecay:
    """A minimal hand-built entry, for the refusals above."""
    return HorizonDecay(
        horizon=horizon,
        dates=1,
        mean_ic=0.0,
        ic_series={_UNTIED_DATES[0]: 0.0},
    )
