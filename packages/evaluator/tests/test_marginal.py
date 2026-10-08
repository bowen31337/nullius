"""Feature 83 — the marginal information ratio: ir_marginal.

app_spec.xml feature 83: *"System computes ir_marginal by orthogonalizing the
candidate against the current book, which returns the incremental information
ratio."*  docs/nullius-tech-architecture.md §6.1 names the step
(``marginal_ir    orthogonalize vs. current book → ir_marginal``), §9.1 names
the ``ir_marginal`` column on the ``node`` table, and docs/alpha-engine-prd.md's
node block spells the same metric under ``metrics`` (``ir_marginal: float  # vs.
current book — see §6.2``) with its definition in §6.2 —
``ir_marginal(v | book) = IR(book ∪ {v}) − IR(book)``.

This suite tests the computation and the persistence as the two halves of one
feature sentence, because each is separately assertable and a bug in either
would be masked by the other:

* **``ir_marginal`` is ``IR(book ∪ {v}) − IR(book)``** — asserted as the
  *property* that makes it the right number for this pipeline: the incremental
  information ratio of the candidate against the current book, measured as the
  difference of two equal-weight information ratios, each of which is the mean
  per-date return over its population standard deviation — *exactly* the
  information ratio feature 80 pins for ``ir_standalone``, so ``ir_standalone``
  is the special case of a book of one and the two are measured on one axis;
* **the candidate and the book are measured on one priced panel, over one pinned
  horizon** — the shortest the priced panel covers, the same one feature 80
  reduces its four scalars over, so the marginal IR sits on one axis with
  ``ic_mean``, the decay profile and the capacity estimate;
* **the book is equal-weight** — ``1/k`` on each of the ``k`` signals, the
  candidate joining at ``1/(k+1)`` — the convention feature 80 and feature 82
  both use;
* **the record carries the terms it reduces from** — the book, combined and
  candidate per-date returns and the three ratios — and each ratio must be the
  information ratio of its own returns, and ``ir_marginal`` their difference,
  enforced at construction and on read-back;
* **the input contract** — step 7's own result and the current book's per-date
  returns; a bundle that is not priced, a panel that covers no horizon, a book
  that misses a priced date, an empty book, and a book signal that is malformed
  are all refused;
* **persistence** — the scalar and its three series round-trip losslessly, a
  re-persist upserts rather than doubles, a node never measured reads back
  ``None``, and the read path refuses a tampered row;
* **the record** — read-only capture, hashability, and the hand-built
  invariants (a ratio that is not its own series' answer, a marginal IR that is
  not the difference of its own two ratios, a date count that disagrees with the
  series it summarises).

The priced bundle is produced by the real step-4-through-7 path where the
provenance matters (a stub oracle over a real alignment, a stub fee schedule —
the same fixtures ``test_costs.py``, ``test_capacity.py`` and ``test_metrics.py``
use) and hand-built where the test is about step 9's own contract.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from contextlib import closing

import contract
import pytest
from evaluator import (
    HORIZONS,
    NODE_MARGINAL_IR_TABLE,
    AlignedTargets,
    CostModelRef,
    CostQuote,
    CostRequest,
    EvaluatorMarginalError,
    EvaluatorStoreError,
    GatedTargets,
    MarginalIR,
    OracleRequest,
    OracleResponse,
    PostCostReturns,
    PostCostSeries,
    RawScoreVector,
    SignalExecution,
    align_targets,
    apply_costs,
    compute_marginal_ir,
    gate_targets,
    load_marginal_ir,
    persist_marginal_ir,
)

_START = dt.date(2026, 9, 1)
_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid."""
    return tuple(start + dt.timedelta(days=i) for i in range(count))


def _varying_signal(dates: tuple[dt.date, ...], values: list[float]) -> dict[dt.date, float]:
    """A per-date return series with genuine cross-date variation.

    A book signal whose return is constant across dates has no information
    ratio (its standard deviation is zero), so the book would be refused before
    the marginal IR could be measured.  A signal that varies across dates is the
    book that actually has an IR to increment.
    """
    return {day: values[i] for i, day in enumerate(dates)}


# A book signal with genuine cross-date variation — the book that has an IR.
_BOOK_VALUES = [0.01, -0.02, 0.015, 0.03, -0.025, 0.02]


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
# 10 cover all three, horizon 20 covers none (the empty-but-carried case).
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
# BBB's closes vary across the grid too — a flat close would give a constant
# per-date return and an equal-weight book that never varies, which the marginal
# IR refuses (a book that never varied has no reward-to-variance ratio).  A
# gently oscillating close keeps BBB's forward returns moving across dates.
_BBB_DAILY = [1.0 + 0.002 * (1 + (i % 3)) for i in range(11)]
_BBB_COMPOUND = [50.0]
for _rate in _BBB_DAILY:
    _BBB_COMPOUND.append(_BBB_COMPOUND[-1] * _rate)
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = {
    "AAA": dict(zip(_GRID, _COMPOUND)),
    "BBB": dict(zip(_GRID, _BBB_COMPOUND)),
}
_MAIN_ALIGNED = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)


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
    evaluator's *marginal-IR* half neither holds nor duplicates it.  The rate is
    nonzero so the ratios really are measured against net returns and not, by
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
    """A hand-built priced bundle — step 9's input, built to the test's order.

    Hand-built because most of this suite is about step 9's *own* contract — the
    increment, the horizon, the refusals — which should be assertable without
    re-running steps 4 through 7 to arrange a shape.  Where the provenance of the
    bundle actually matters (the input-contract tests), the suite uses ``_priced``.
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


def _information_ratio(returns: dict[dt.date, float]) -> float:
    """The equal-weight book's information ratio, spelled independently.

    The mean per-date return over its population standard deviation — spelled in
    its own terms rather than by calling anything in the package, so the suite
    pins the ratio rather than trusting the implementation to define it.
    """
    values = [returns[day] for day in sorted(returns)]
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    return mean / math.sqrt(variance)


def _book_plus_candidate(
    book: dict[str, dict[dt.date, float]],
    candidate: dict[dt.date, float],
) -> dict[dt.date, float]:
    """The equal-weight book-plus-candidate per-date return, spelled independently."""
    k = len(book)
    out: dict[dt.date, float] = {}
    for day, cval in candidate.items():
        total = sum(row[day] for row in book.values())
        out[day] = (total + cval) / (k + 1)
    return out


def _book_return(book: dict[str, dict[dt.date, float]]) -> dict[dt.date, float]:
    """The equal-weight book per-date return, spelled independently."""
    k = len(book)
    out: dict[dt.date, float] = {}
    for day in next(iter(book.values())):
        out[day] = sum(row[day] for row in book.values()) / k
    return out


# -- ir_marginal is the increment ------------------------------------------------


def test_ir_marginal_is_the_increment_in_the_book_information_ratio():
    """ir_marginal is IR(book ∪ {v}) − IR(book), each IR feature 80's definition."""
    dates = _days(6)
    candidate = {
        dates[0]: {"AAA": 0.02, "BBB": -0.01},
        dates[1]: {"AAA": 0.01, "BBB": 0.0},
        dates[2]: {"AAA": -0.01, "BBB": 0.02},
        dates[3]: {"AAA": 0.03, "BBB": 0.0},
        dates[4]: {"AAA": -0.02, "BBB": 0.01},
        dates[5]: {"AAA": 0.01, "BBB": -0.02},
    }
    priced = _hand_priced({1: candidate})
    book = {
        "sigA": {day: {
            dates[0]: 0.01, dates[1]: -0.02, dates[2]: 0.01,
            dates[3]: 0.02, dates[4]: -0.01, dates[5]: 0.0,
        }[day] for day in dates},
        "sigB": {day: {
            dates[0]: 0.0, dates[1]: 0.01, dates[2]: -0.01,
            dates[3]: 0.01, dates[4]: 0.0, dates[5]: -0.01,
        }[day] for day in dates},
    }
    marginal = compute_marginal_ir(priced, book)
    candidate_return = {
        day: (sum(candidate[day].values()) / len(candidate[day])) for day in dates
    }
    book_return = _book_return(book)
    combined_return = _book_plus_candidate(book, candidate_return)
    expected = _information_ratio(combined_return) - _information_ratio(book_return)
    assert marginal.ir_marginal == pytest.approx(expected)
    assert marginal.book_ir == pytest.approx(_information_ratio(book_return))
    assert marginal.combined_ir == pytest.approx(_information_ratio(combined_return))
    assert marginal.candidate_ir == pytest.approx(_information_ratio(candidate_return))


def test_the_candidate_ir_is_the_candidate_standalone_information_ratio():
    """The candidate_ir the record carries is the candidate's standalone IR.

    ir_standalone (feature 80) is the k=0 special case of ir_marginal — the
    candidate alone.  This asserts the *definition* link: the candidate_ir this
    module carries equals the information ratio of the candidate's own per-date
    return, measured on one axis with the book and combined ratios.
    """
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    marginal = compute_marginal_ir(priced, {"sigA": _varying_signal(dates, _BOOK_VALUES)})
    candidate_return = {
        day: (sum(candidate[day].values()) / len(candidate[day])) for day in dates
    }
    assert marginal.candidate_ir == pytest.approx(_information_ratio(candidate_return))


def test_ir_marginal_can_be_negative():
    """A candidate that adds variance without mean drags the combined IR down.

    A mean-zero candidate that is *not* collinear with the book return adds
    variance to the equal-weight combined portfolio while leaving its mean
    roughly in place, so the combined information ratio falls strictly below
    the book's and the increment is negative.  The marginal IR is signed, and
    a signal that hurts the book says so.  The book is two signals (so it
    genuinely varies — a constant book has no IR).
    """
    dates = _days(6)
    book_return = {
        dates[0]: 0.02, dates[1]: 0.01, dates[2]: -0.01,
        dates[3]: 0.03, dates[4]: -0.02, dates[5]: 0.01,
    }
    # Mean-zero, non-collinear noise: it spreads the combined series out.
    cand_return = {
        dates[0]: 0.03, dates[1]: -0.03, dates[2]: 0.0,
        dates[3]: 0.0, dates[4]: -0.03, dates[5]: 0.03,
    }
    candidate = {day: {"AAA": cand_return[day]} for day in dates}
    priced = _hand_priced({1: candidate})
    # Two book signals whose equal-weight return is book_return.
    book = {
        "sigA": {day: book_return[day] for day in dates},
        "sigB": {day: book_return[day] for day in dates},
    }
    marginal = compute_marginal_ir(priced, book)
    # Equal-weight book of two identical signals is book_return itself.
    book_returns = {day: book_return[day] for day in dates}
    # Combined: book re-normalised to 2/3, candidate to 1/3.
    combined_returns = {day: (2 * book_return[day] + cand_return[day]) / 3 for day in dates}
    assert marginal.book_returns == pytest.approx(book_returns)
    assert marginal.combined_returns == pytest.approx(combined_returns)
    assert marginal.book_ir == pytest.approx(_information_ratio(book_returns))
    assert marginal.combined_ir == pytest.approx(_information_ratio(combined_returns))
    expected_marginal = marginal.combined_ir - marginal.book_ir
    assert marginal.ir_marginal == pytest.approx(expected_marginal)
    assert marginal.ir_marginal < 0.0


def test_ir_marginal_is_zero_for_a_candidate_the_book_already_explains():
    """A candidate the book already explains adds nothing — the increment is 0.

    A candidate whose per-date return equals the equal-weight book return moves
    the combined portfolio's return series only by a rescale, so the two
    information ratios are equal and the increment is zero — the economic content
    of "orthogonalizing the candidate against the book".  The book is two signals
    (so it genuinely varies — a constant book has no IR).
    """
    dates = _days(6)
    book_return = {
        dates[0]: 0.02, dates[1]: 0.01, dates[2]: -0.01,
        dates[3]: 0.03, dates[4]: -0.02, dates[5]: 0.01,
    }
    candidate_return = dict(book_return)
    candidate = {day: {"AAA": candidate_return[day]} for day in dates}
    priced = _hand_priced({1: candidate})
    book = {
        "sigA": {day: book_return[day] for day in dates},
        "sigB": {day: book_return[day] for day in dates},
    }
    marginal = compute_marginal_ir(priced, book)
    # Combined return is (book + candidate)/3 = book_return, so combined_ir ==
    # book_ir and the increment is 0.
    assert marginal.ir_marginal == pytest.approx(0.0)
    assert marginal.combined_ir == pytest.approx(marginal.book_ir)


# -- one priced panel, one pinned horizon ----------------------------------------


def test_the_marginal_ir_is_computed_over_the_shortest_covered_horizon():
    """The marginal IR reduces over the shortest horizon the priced panel covers."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate, 2: candidate, 5: candidate})
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    assert marginal.horizon == 1


def test_the_marginal_ir_skips_an_empty_horizon():
    """A horizon the panel does not cover is absent, not zero — the next is used."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    # Horizon 1 empty, horizon 2 covered — the marginal IR reduces over 2.
    priced = _hand_priced({2: candidate})
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    assert marginal.horizon == 2


# -- the record ------------------------------------------------------------------


def test_the_record_carries_its_terms_and_is_self_consistent():
    """The record carries the book, combined and candidate returns and the ratios."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    assert marginal.book_size == 1
    assert marginal.dates == 6
    assert marginal.node_id == "node_1"
    assert marginal.snapshot_name == "snap_abc123"
    assert marginal.cost_model is _REF
    assert marginal.ir_marginal == pytest.approx(marginal.combined_ir - marginal.book_ir)
    # The record is hashable and equal to a rebuilt copy of itself.
    rebuilt = MarginalIR(
        node_id=marginal.node_id,
        snapshot_name=marginal.snapshot_name,
        cost_model=marginal.cost_model,
        horizon=marginal.horizon,
        dates=marginal.dates,
        book_size=marginal.book_size,
        book_ir=marginal.book_ir,
        combined_ir=marginal.combined_ir,
        candidate_ir=marginal.candidate_ir,
        ir_marginal=marginal.ir_marginal,
        book_returns=marginal.book_returns,
        combined_returns=marginal.combined_returns,
        candidate_returns=marginal.candidate_returns,
    )
    assert marginal == rebuilt
    assert hash(marginal) == hash(rebuilt)


def test_a_hand_built_record_whose_marginal_ir_is_not_the_difference_is_refused():
    """A record whose ir_marginal is not combined_ir − book_ir is refused."""
    dates = _days(6)
    book_returns = {day: 0.01 * (i % 3 - 1) for i, day in enumerate(dates)}
    combined_returns = {day: 0.01 * (i % 4 - 1.5) for i, day in enumerate(dates)}
    candidate_returns = {day: 0.01 * (i % 2) for i, day in enumerate(dates)}
    with pytest.raises(EvaluatorMarginalError, match="increment"):
        MarginalIR(
            node_id="node_1",
            snapshot_name="snap",
            cost_model=_REF,
            horizon=1,
            dates=6,
            book_size=1,
            book_ir=_information_ratio(book_returns),
            combined_ir=_information_ratio(combined_returns),
            candidate_ir=_information_ratio(candidate_returns),
            ir_marginal=999.0,  # not the difference
            book_returns=book_returns,
            combined_returns=combined_returns,
            candidate_returns=candidate_returns,
        )


def test_a_hand_built_record_whose_ratio_is_not_its_own_series_is_refused():
    """A record whose book_ir is not the information ratio of its book returns is refused."""
    dates = _days(6)
    book_returns = {day: 0.01 * (i % 3 - 1) for i, day in enumerate(dates)}
    combined_returns = {day: 0.01 * (i % 4 - 1.5) for i, day in enumerate(dates)}
    candidate_returns = {day: 0.01 * (i % 2) for i, day in enumerate(dates)}
    book_ir = _information_ratio(book_returns)
    combined_ir = _information_ratio(combined_returns)
    candidate_ir = _information_ratio(candidate_returns)
    with pytest.raises(EvaluatorMarginalError, match="book_ir"):
        MarginalIR(
            node_id="node_1",
            snapshot_name="snap",
            cost_model=_REF,
            horizon=1,
            dates=6,
            book_size=1,
            book_ir=book_ir + 0.5,  # not its own series' answer
            combined_ir=combined_ir,
            candidate_ir=candidate_ir,
            ir_marginal=combined_ir - book_ir,
            book_returns=book_returns,
            combined_returns=combined_returns,
            candidate_returns=candidate_returns,
        )


def test_a_record_with_a_date_count_disagreeing_with_its_series_is_refused():
    """A record whose date count disagrees with its own series is refused."""
    dates = _days(6)
    book_returns = {day: 0.01 * (i % 3 - 1) for i, day in enumerate(dates)}
    combined_returns = {day: 0.01 * (i % 4 - 1.5) for i, day in enumerate(dates)}
    candidate_returns = {day: 0.01 * (i % 2) for i, day in enumerate(dates)}
    with pytest.raises(EvaluatorMarginalError, match="denominator|measured dates"):
        MarginalIR(
            node_id="node_1",
            snapshot_name="snap",
            cost_model=_REF,
            horizon=1,
            dates=5,  # the series carry 6
            book_size=1,
            book_ir=_information_ratio(book_returns),
            combined_ir=_information_ratio(combined_returns),
            candidate_ir=_information_ratio(candidate_returns),
            ir_marginal=_information_ratio(combined_returns) - _information_ratio(book_returns),
            book_returns=book_returns,
            combined_returns=combined_returns,
            candidate_returns=candidate_returns,
        )


# -- the input contract ----------------------------------------------------------


def test_a_bundle_that_is_not_step_seven_is_refused():
    """A returns that is not step 7's own PostCostReturns is refused."""
    with pytest.raises(EvaluatorMarginalError, match="PostCostReturns|step 7"):
        compute_marginal_ir({"not": "a PostCostReturns"}, {"sigA": {_START: 0.0}})


def test_an_empty_book_is_refused():
    """An empty book is refused — that is the candidate's standalone IR, not marginal."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    with pytest.raises(EvaluatorMarginalError, match="empty|standalone"):
        compute_marginal_ir(priced, {})


def test_a_book_of_zero_signals_is_not_a_standalone_ir():
    """A book of zero signals has no information ratio to increment from."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    with pytest.raises(EvaluatorMarginalError, match="book must hold at least one|standalone"):
        compute_marginal_ir(priced, {})


def test_a_book_signal_that_misses_a_priced_date_is_refused():
    """A book signal that misses a priced date is a hole in the resident array — refused."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"sigA": {day: 0.0 for day in dates[:5]}}  # missing the last date
    with pytest.raises(EvaluatorMarginalError, match="misses a priced date|no return"):
        compute_marginal_ir(priced, book)


def test_a_book_signal_with_a_non_finite_value_is_refused():
    """A book signal carrying a non-finite value is refused."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    signal = _varying_signal(dates, _BOOK_VALUES)
    signal[dates[2]] = float("nan")  # poison one date before handing the book over
    book = {"sigA": signal}
    with pytest.raises(EvaluatorMarginalError, match="not finite"):
        compute_marginal_ir(priced, book)


def test_a_panel_that_covers_no_horizon_is_refused():
    """A panel that covers no horizon at all is refused — nothing measured."""
    priced = _hand_priced({})
    book = {"sigA": {_START: 0.0}}
    with pytest.raises(EvaluatorMarginalError, match="covers no horizon|nothing to compute"):
        compute_marginal_ir(priced, book)


def test_a_panel_with_fewer_than_two_dates_is_refused():
    """An information ratio over one date names a zero standard deviation — refused."""
    priced = _hand_priced({1: {_START: {"AAA": 0.01, "BBB": -0.01}}})
    book = {"sigA": {_START: 0.0}}
    with pytest.raises(EvaluatorMarginalError, match="fewer than two|single date|standard deviation"):
        compute_marginal_ir(priced, book)


def test_a_constant_book_return_is_refused():
    """A book whose per-date return never varies has no information ratio — refused."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"sigA": {day: 0.01 for day in dates}}  # constant
    with pytest.raises(EvaluatorMarginalError, match="constant|never varied|dividing by zero"):
        compute_marginal_ir(priced, book)


def test_a_book_with_an_empty_signal_name_is_refused():
    """A book signal with an empty name is refused."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"": {day: 0.0 for day in dates}}
    with pytest.raises(EvaluatorMarginalError, match="non-empty"):
        compute_marginal_ir(priced, book)


# -- the real path ---------------------------------------------------------------


def test_the_marginal_ir_is_measured_from_a_priced_bundle():
    """The marginal IR is measured from step 7's own priced record, over the real path."""
    priced = _priced()
    priced_dates = priced.series[1].dates()
    # A book signal with genuine cross-date variation over the priced dates — a
    # constant book has no IR to increment.  The values are the candidate's own
    # per-date returns, which vary across the priced dates.
    candidate_return = {
        day: sum(priced.series[1].at(day).values()) / len(priced.series[1].at(day))
        for day in priced_dates
    }
    book = {"sigA": candidate_return}
    marginal = compute_marginal_ir(priced, book)
    assert marginal.horizon == 1
    assert marginal.book_size == 1
    # The record's terms are self-consistent.
    assert marginal.ir_marginal == pytest.approx(marginal.combined_ir - marginal.book_ir)


# -- persistence -----------------------------------------------------------------


def test_the_marginal_ir_round_trips_through_the_store():
    """The scalar and its three series round-trip losslessly."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    persist_marginal_ir(marginal)
    back = load_marginal_ir("node_1", _REF)
    assert back is not None
    assert back == marginal
    assert back.ir_marginal == marginal.ir_marginal
    assert back.book_ir == marginal.book_ir
    assert back.combined_ir == marginal.combined_ir
    assert back.candidate_ir == marginal.candidate_ir
    assert back.book_returns == marginal.book_returns
    assert back.combined_returns == marginal.combined_returns
    assert back.candidate_returns == marginal.candidate_returns


def test_a_repersist_upserts_rather_than_doubles():
    """A re-persist over the same key refreshes the row rather than adding a second."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    persist_marginal_ir(marginal)
    persist_marginal_ir(marginal)
    with closing(sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[1])) as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {NODE_MARGINAL_IR_TABLE}"
        ).fetchone()[0]
    assert count == 1


def test_a_node_never_measured_reads_back_none():
    """A node this store never measured reads back ``None``."""
    assert load_marginal_ir("node_never", _REF) is None


def test_the_read_path_refuses_a_tampered_row():
    """A row whose scalar was edited while its series were left alone is refused."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    persist_marginal_ir(marginal)
    # Edit the stored ir_marginal in place, leaving the series alone.
    with closing(sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[1])) as connection, connection:
        connection.execute(
            f"UPDATE {NODE_MARGINAL_IR_TABLE} SET ir_marginal = ir_marginal + 1.0"
        )
    with pytest.raises(EvaluatorStoreError, match="does not reconstruct|not its own"):
        load_marginal_ir("node_1", _REF)


def test_the_read_path_refuses_a_row_whose_ratio_is_not_its_series():
    """A row whose book_ir was edited while its book series were left alone is refused."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate})
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    persist_marginal_ir(marginal)
    with closing(sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[1])) as connection, connection:
        connection.execute(
            f"UPDATE {NODE_MARGINAL_IR_TABLE} SET book_ir = book_ir + 1.0"
        )
    with pytest.raises(EvaluatorStoreError, match="does not reconstruct"):
        load_marginal_ir("node_1", _REF)


# -- provenance ------------------------------------------------------------------


def test_the_marginal_ir_carries_the_evaluation_provenance():
    """The marginal IR is stamped with node, snapshot and cost model."""
    dates = _days(6)
    candidate = {day: {"AAA": 0.02 * (i - 2) + 0.005, "BBB": 0.01 * (2 - i)} for i, day in enumerate(dates)}
    priced = _hand_priced({1: candidate}, node_id="node_7", snapshot_name="snap_xyz")
    book = {"sigA": _varying_signal(dates, _BOOK_VALUES)}
    marginal = compute_marginal_ir(priced, book)
    assert marginal.node_id == "node_7"
    assert marginal.snapshot_name == "snap_xyz"
    assert marginal.cost_model.venue == _VENUE
    assert marginal.cost_model.version == _VERSION
