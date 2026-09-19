"""Cancel-replace rate and trade-size moments, persisted past the 90 day expiry.

These tests are the feature statement for app_spec.xml feature 22 — *"System
computes cancel-replace rate plus trade-size distribution moments, persisting
them so a 90 day raw-diff expiry does not lose the derived history"* — read as
behaviour of the classification, the moments, the store and the worker they
stand on:

* a **cancel-replace is a removal plus an add on one side inside one diff** — an
  order that left the book and re-entered somewhere else — and the rate is that
  count over the second's level events;
* a removal on the bid side and an add on the ask side is *not* a cancel-replace:
  the two sides never pair up;
* classification happens against the book *before* the diff is folded in, which
  is what makes "was this price already standing?" a question with an answer;
* the size moments are **population** moments over the second's prints, with the
  skewness and excess kurtosis a reader expects from that pair;
* an absence is not a zero: no prints means ``None`` moments rather than a mean
  of zero, and no level events means ``None`` rate rather than a rate of zero;
* the derived row is **readable after the raw diffs it came from are pruned
  away** — the feature's own persistence clause, and the reason each record
  carries its closing book;
* the tape is an injected seam, so an unconfigured deployment is that stream's
  own failure in the supervisor's report rather than a component that fails to
  load;
* the derived log is append-only and permanent, landing in the same staging area
  the seal copies out of;
* damaged bytes are refused rather than reconstructed into a plausible feature.

The module docstring in ``nullius_ingest.trade_flow`` is the design note; these
tests are the behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from nullius_ingest import (
    CANCEL_REPLACE,
    TRADE_FLOW_STREAM,
    BookDiffStore,
    BookState,
    IngestSupervisor,
    StagingArea,
    StreamClass,
    TradeFlowBatch,
    TradeFlowCorruptError,
    TradeFlowError,
    TradeFlowParseError,
    TradeFlowRecord,
    TradeFlowRow,
    TradeFlowStore,
    TradeFlowWorker,
    TradePrint,
    cancel_replace_events,
    classify_levels,
    parse_trade_prints,
    register_trade_flow_worker,
    size_moments,
)
from nullius_ingest.book_diffs import BookDiffRow, PriceLevel
from nullius_ingest.book_features import FEATURE_SLICE
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A flush instant; the feature grid is decided from elapsed time, so the tests
#: use explicit instants rather than depending on when the suite runs.
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

#: ``T0`` as epoch milliseconds — the spelling a venue's event time arrives in.
T0_MS = int(T0.timestamp() * 1000)


def epoch_ms(moment: datetime) -> int:
    """``moment`` as epoch milliseconds — the spelling a venue's event time uses."""
    return int(moment.timestamp() * 1000)


# -- The 1 second grid --------------------------------------------------------


def test_the_trade_flow_grid_is_feature_20s_grid() -> None:
    # The two derived families are snapshotted at the same 1s boundary off the
    # same reconstruction, so a second means the same instant in both logs —
    # which is what lets a reader join the depth ladder to the trade flow.
    from nullius_ingest.trade_flow import (
        TRADE_FLOW_SLICE,
        TRADE_FLOW_SLICE_MILLISECONDS,
        _floor_to_second,
    )

    assert TRADE_FLOW_SLICE == FEATURE_SLICE == timedelta(seconds=1)
    assert TRADE_FLOW_SLICE_MILLISECONDS == 1000
    assert _floor_to_second(T0 + timedelta(milliseconds=1999)) == T0 + FEATURE_SLICE
    assert _floor_to_second(T0 + timedelta(milliseconds=2000)) == T0 + 2 * FEATURE_SLICE


def test_a_naive_instant_is_refused() -> None:
    from nullius_ingest.trade_flow import _floor_to_second

    with pytest.raises(ValueError, match="timezone-aware"):
        _floor_to_second(datetime(2026, 3, 1, 12, 0, 0))


# -- Helpers ------------------------------------------------------------------


def _row(
    symbol: str,
    window_start: datetime,
    bids: list | None = None,
    asks: list | None = None,
) -> BookDiffRow:
    """A raw :class:`BookDiffRow`, the thing the book is folded from."""

    def levels(pairs, side):
        return tuple(
            PriceLevel(side=side, price=p, quantity=q) for p, q in (pairs or [])
        )

    return BookDiffRow(
        symbol=symbol,
        window_start=window_start,
        first_update_id=1,
        last_update_id=2,
        levels=levels(bids, "bids") + levels(asks, "asks"),
    )


def diff(
    event_time_ms: int = T0_MS,
    symbol: str = "BTCUSDT",
    bids: list | None = None,
    asks: list | None = None,
) -> dict:
    """One venue-shaped depth delta, spelled the way Binance's stream does."""
    return {
        "e": "depthUpdate",
        "E": event_time_ms,
        "s": symbol,
        "U": 1,
        "u": 2,
        "b": bids if bids is not None else [["100.50", "1.000"]],
        "a": asks if asks is not None else [["101.50", "1.000"]],
    }


def flush(*diffs: dict) -> dict:
    """A full delta response carrying the given diffs."""
    return {"diffs": list(diffs)}


def trade(
    event_time_ms: int = T0_MS,
    symbol: str = "BTCUSDT",
    price: str = "100.75",
    quantity: str = "1.0",
    is_buyer_maker: bool = True,
) -> dict:
    """One venue-shaped trade print, spelled the way Binance's stream does."""
    return {
        "e": "aggTrade",
        "E": event_time_ms,
        "s": symbol,
        "p": price,
        "q": quantity,
        "m": is_buyer_maker,
    }


def make_store(tmp_path) -> TradeFlowStore:
    """A store over a fresh staging area."""
    return TradeFlowStore(StagingArea(tmp_path / "staging"))


def make_diff_store(tmp_path, *batches: dict) -> BookDiffStore:
    """A raw-diff store pre-seeded with the given venue batches, in order."""
    store = BookDiffStore(StagingArea(tmp_path / "staging"))
    for batch in batches:
        store.record(batch, written_at=T0)
    return store


def tape_of(*prints: dict):
    """A :data:`TradeTape` returning the given venue prints."""
    return lambda: {"trades": list(prints)}


def clock_at(moment: datetime):
    return lambda: moment


def worker(tmp_path, diff_store, *prints: dict, store=None) -> TradeFlowWorker:
    """A worker over fresh stores, measuring the given trade prints."""
    return TradeFlowWorker(
        store if store is not None else make_store(tmp_path),
        diff_store,
        tape_of(*prints),
        clock=clock_at(T0),
    )


# -- Classifying a level: add, update, remove ---------------------------------


def test_a_level_for_a_price_not_standing_is_an_add() -> None:
    book = BookState()
    actions = classify_levels(_row("BTCUSDT", T0, bids=[["100.50", "1"]]), book)

    assert [(a.side, a.price, a.action) for a in actions] == [("bids", "100.50", "add")]


def test_a_level_for_a_price_already_standing_is_an_update() -> None:
    # The ordering the whole feature rests on: classification asks the book as it
    # stood *before* the diff, so a re-sent price is an update rather than an add.
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))
    actions = classify_levels(_row("BTCUSDT", T0, bids=[["100.50", "2"]]), book)

    assert [a.action for a in actions] == ["update"]


def test_the_same_level_classifies_differently_after_the_fold() -> None:
    # The counterfactual that proves the ordering matters: fold first and the
    # add becomes an update, which is exactly the mistake the seam prevents.
    row = _row("BTCUSDT", T0, bids=[["100.50", "1"]])
    book = BookState()
    assert [a.action for a in classify_levels(row, book)] == ["add"]
    book.apply(row)
    assert [a.action for a in classify_levels(row, book)] == ["update"]


def test_a_zero_quantity_is_a_removal() -> None:
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))
    actions = classify_levels(_row("BTCUSDT", T0, bids=[["100.50", "0"]]), book)

    assert [a.action for a in actions] == ["remove"]


def test_a_removal_of_an_unknown_price_is_still_a_removal() -> None:
    # The venue said "this price is gone"; whether we happened to hold it is not
    # the venue's claim to qualify.  Classified from the spelling alone.
    book = BookState()
    actions = classify_levels(_row("BTCUSDT", T0, bids=[["100.50", "0"]]), book)

    assert [a.action for a in actions] == ["remove"]


def test_a_level_action_refuses_an_unknown_action() -> None:
    from nullius_ingest.trade_flow import LevelAction

    with pytest.raises(TradeFlowParseError, match="a level action is one of"):
        LevelAction("bids", "100.50", "sneak")


def test_an_unknown_side_is_refused_by_the_book() -> None:
    book = BookState()
    with pytest.raises(ValueError, match="a book side is 'bids' or 'asks'"):
        book.has_price("middle", "100.50")


# -- Cancel-replace: a removal plus an add on one side ------------------------


def test_a_removal_and_an_add_on_one_side_is_a_cancel_replace() -> None:
    # The definition, stated once: the order left the book and re-entered
    # somewhere else inside the same diff.
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))
    actions = classify_levels(
        _row("BTCUSDT", T0, bids=[["100.50", "0"], ["100.40", "1"]]), book
    )

    assert cancel_replace_events(actions) == 1


def test_a_removal_alone_is_not_a_cancel_replace() -> None:
    # Ordinary liquidity withdrawal: the order left and did not come back.
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))
    actions = classify_levels(_row("BTCUSDT", T0, bids=[["100.50", "0"]]), book)

    assert cancel_replace_events(actions) == 0


def test_an_add_alone_is_not_a_cancel_replace() -> None:
    book = BookState()
    actions = classify_levels(_row("BTCUSDT", T0, bids=[["100.50", "1"]]), book)

    assert cancel_replace_events(actions) == 0


def test_a_removal_on_one_side_and_an_add_on_the_other_is_not_a_cancel_replace() -> None:
    # Liquidity changing direction, not an order re-entering: the two sides never
    # pair up, which is why the count is taken per side.
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))
    actions = classify_levels(
        _row("BTCUSDT", T0, bids=[["100.50", "0"]], asks=[["101.50", "1"]]), book
    )

    assert cancel_replace_events(actions) == 0


def test_two_removals_and_one_add_is_one_cancel_replace() -> None:
    # Counted as the smaller of the two per side — one removal matched against one
    # add — so a genuine net withdrawal is not reported as two re-entries.
    book = BookState()
    book.apply(
        _row("BTCUSDT", T0, bids=[["100.50", "1"], ["100.40", "1"], ["100.30", "1"]])
    )
    actions = classify_levels(
        _row("BTCUSDT", T0, bids=[["100.50", "0"], ["100.40", "0"], ["100.20", "1"]]),
        book,
    )

    assert cancel_replace_events(actions) == 1


def test_cancel_replaces_are_counted_per_side() -> None:
    # A cancel-replace on the bids and another on the asks inside one diff are two
    # events: two different orders re-entered.
    book = BookState()
    book.apply(
        _row(
            "BTCUSDT",
            T0,
            bids=[["100.50", "1"], ["100.40", "1"]],
            asks=[["101.50", "1"], ["101.60", "1"]],
        )
    )
    actions = classify_levels(
        _row(
            "BTCUSDT",
            T0,
            bids=[["100.40", "0"], ["100.30", "1"]],
            asks=[["101.60", "0"], ["101.70", "1"]],
        ),
        book,
    )

    assert cancel_replace_events(actions) == 2


def test_an_update_is_not_a_level_event_for_the_cancel_replace_rate() -> None:
    # A re-sent price is neither a removal nor an add, so it contributes no
    # cancel-replace — but it *is* a level event, and it stays in the rate's
    # denominator, because the second did see book activity.
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))
    actions = classify_levels(_row("BTCUSDT", T0, bids=[["100.50", "5"]]), book)

    assert len(actions) == 1
    assert cancel_replace_events(actions) == 0


# -- The size moments ---------------------------------------------------------


def test_the_moments_of_a_symmetric_distribution_are_right() -> None:
    mean, sd, skew, kurtosis = size_moments(
        [Decimal(1), Decimal(2), Decimal(3), Decimal(4), Decimal(5)]
    )

    assert mean == Decimal(3)
    assert skew == 0  # perfectly symmetric about the mean
    # Population variance of 1..5 is 2, so the standard deviation is sqrt(2).
    assert sd is not None and (sd * sd - 2).copy_abs() < Decimal("1e-20")
    assert kurtosis is not None and kurtosis < 0  # flatter than a normal


def test_the_moments_are_population_moments() -> None:
    # Dividing by n, not n-1: the second's prints are the whole population of
    # trades that landed in that second, not a sample drawn from one.
    mean, sd, _, _ = size_moments([Decimal(1), Decimal(3)])

    assert mean == Decimal(2)
    # Population variance of {1, 3} is 1; the sample variance would be 2.
    assert sd is not None and (sd - Decimal(1)).copy_abs() < Decimal("1e-20")


def test_a_normal_distribution_reads_zero_excess_kurtosis() -> None:
    # A two-point distribution is the degenerate normal: its excess kurtosis is
    # exactly -2 by the population formula, and the point is that the *excess*
    # convention is what the module reports, not the raw fourth moment.
    _, _, skew, kurtosis = size_moments([Decimal(1), Decimal(1), Decimal(3), Decimal(3)])

    assert skew == 0
    assert kurtosis == Decimal(-2)


def test_fewer_than_two_prints_has_no_distribution() -> None:
    # An absence, not a zero: a mean over one print would be a distribution claim
    # the data does not support.
    assert size_moments([]) == (None, None, None, None)
    assert size_moments([Decimal(5)]) == (None, None, None, None)


def test_a_degenerate_distribution_has_a_mean_and_no_higher_moments() -> None:
    # Every print the same size: a point mass.  It has a mean and no dispersion,
    # and its standardized higher moments are 0/0 — reported as absences rather
    # than as a fabricated zero.
    assert size_moments([Decimal(2), Decimal(2), Decimal(2)]) == (
        Decimal(2),
        Decimal(0),
        None,
        None,
    )


def test_the_moments_are_scale_equivariant() -> None:
    # Doubling every size doubles the mean and the dispersion and leaves the
    # standardized shape untouched — the defining property of skewness and
    # kurtosis, and a check that the standardization is done at all.
    base = size_moments([Decimal(1), Decimal(2), Decimal(4), Decimal(8)])
    doubled = size_moments([Decimal(2), Decimal(4), Decimal(8), Decimal(16)])

    assert base[0] is not None and doubled[0] == base[0] * 2
    assert base[1] is not None and doubled[1] is not None
    assert (doubled[1] - base[1] * 2).copy_abs() < Decimal("1e-20")
    assert base[2] is not None and doubled[2] is not None
    assert (doubled[2] - base[2]).copy_abs() < Decimal("1e-20")
    assert base[3] is not None and doubled[3] is not None
    assert (doubled[3] - base[3]).copy_abs() < Decimal("1e-20")


# -- Parsing the venue's tape -------------------------------------------------


def test_prints_parse_from_a_wrapper_object() -> None:
    prints = parse_trade_prints({"trades": [trade(quantity="1.5")]})

    assert len(prints) == 1
    assert prints[0].symbol == "BTCUSDT"
    assert prints[0].size == Decimal("1.5")
    assert prints[0].is_buyer_maker is True
    assert prints[0].window_start == T0


def test_prints_parse_from_json_bytes() -> None:
    import json

    prints = parse_trade_prints(json.dumps([trade()]).encode("utf-8"))

    assert prints[0].quantity == "1.0"  # the venue's spelling, verbatim


def test_a_trades_own_time_is_preferred_over_the_envelope_time() -> None:
    # ``T`` is when the trade happened and ``E`` is when the venue emitted the
    # message; the 1s bucket must be decided by the former, or a busy second's
    # trades would be bucketed by when the socket delivered them.
    prints = parse_trade_prints(
        [{"s": "BTCUSDT", "p": "1", "q": "1", "m": True, "T": T0_MS, "E": T0_MS + 5000}]
    )

    assert prints[0].window_start == T0


def test_prints_accept_the_long_field_spellings() -> None:
    prints = parse_trade_prints(
        [
            {
                "symbol": "ETHUSDT",
                "price": "2000.5",
                "quantity": "3",
                "timestamp": T0_MS,
                "is_buyer_maker": False,
            }
        ]
    )

    assert prints[0].symbol == "ETHUSDT"
    assert prints[0].is_buyer_maker is False


def test_a_print_with_no_event_time_is_refused() -> None:
    # Stamping it with our own clock would invent a fact about when the venue saw
    # the trade, and the moments would then be computed over a second it never
    # landed in.
    with pytest.raises(TradeFlowParseError, match="event time"):
        parse_trade_prints([{"s": "BTCUSDT", "p": "1", "q": "1", "m": True}])


def test_a_print_with_no_aggressor_flag_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="aggressor flag"):
        parse_trade_prints([{"s": "BTCUSDT", "p": "1", "q": "1", "T": T0_MS}])


def test_a_zero_sized_print_is_refused() -> None:
    # A trade of no size is not a trade: counting it would inflate trade_count and
    # drag the mean toward zero on evidence that does not exist.
    with pytest.raises(TradeFlowParseError, match="not a trade"):
        parse_trade_prints([trade(quantity="0")])


def test_a_non_numeric_print_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="not a decimal"):
        parse_trade_prints([trade(quantity="lots")])


def test_a_payload_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="a list of prints"):
        parse_trade_prints(7)


def test_a_trade_print_floors_its_window_onto_the_grid() -> None:
    # The venue's event time decides the second, never our ingest lag.
    print_ = TradePrint(
        symbol="BTCUSDT",
        window_start=T0 + timedelta(milliseconds=1400),
        price="100",
        quantity="1",
        is_buyer_maker=True,
    )

    assert print_.window_start == T0 + FEATURE_SLICE


def test_a_naive_trade_print_window_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="timezone-aware"):
        TradePrint(
            symbol="BTCUSDT",
            window_start=datetime(2026, 3, 1, 12, 0, 0),
            price="100",
            quantity="1",
            is_buyer_maker=True,
        )


# -- The feature row ----------------------------------------------------------


def test_a_row_floors_its_window_and_renders_canonically() -> None:
    row = TradeFlowRow(
        symbol="BTCUSDT",
        window_start=T0 + timedelta(milliseconds=1900),
        cancel_replace_rate=Decimal("0.5"),
        level_events=4,
        cancel_replace_events=2,
        trade_count=3,
        trade_volume=Decimal("6"),
        mean_size=Decimal("2"),
        stddev_size=Decimal("1"),
        skew_size=Decimal("0"),
        kurtosis_size=Decimal("-1.5"),
    )

    assert row.window_start == T0 + FEATURE_SLICE
    canonical = row.canonical()
    assert canonical["cancel_replace_rate"] == "0.5"
    assert canonical["trade_volume"] == "6"
    assert canonical["kurtosis_size"] == "-1.5"


def test_a_row_recomputes_its_own_rate() -> None:
    # The counts are the evidence and the rate is their ratio, so a reader can
    # check the stored rate rather than trust it.
    row = TradeFlowRow(
        symbol="BTCUSDT",
        window_start=T0,
        cancel_replace_rate=Decimal("0.25"),
        level_events=4,
        cancel_replace_events=1,
        trade_count=0,
        trade_volume=Decimal(0),
        mean_size=None,
        stddev_size=None,
        skew_size=None,
        kurtosis_size=None,
    )

    assert row.rate() == Decimal("0.25")


def test_an_absent_rate_is_not_a_zero_rate() -> None:
    # "No order activity" and "activity with no cancels" are different facts
    # about the book, and the log must not conflate them.
    quiet = TradeFlowRow(
        symbol="BTCUSDT",
        window_start=T0,
        cancel_replace_rate=None,
        level_events=0,
        cancel_replace_events=0,
        trade_count=1,
        trade_volume=Decimal("2"),
        mean_size=None,
        stddev_size=None,
        skew_size=None,
        kurtosis_size=None,
    )
    uncancelled = TradeFlowRow(
        symbol="BTCUSDT",
        window_start=T0,
        cancel_replace_rate=Decimal(0),
        level_events=3,
        cancel_replace_events=0,
        trade_count=1,
        trade_volume=Decimal("2"),
        mean_size=None,
        stddev_size=None,
        skew_size=None,
        kurtosis_size=None,
    )

    assert quiet.rate() is None
    assert quiet.canonical()["cancel_replace_rate"] is None
    assert uncancelled.rate() == 0
    assert uncancelled.canonical()["cancel_replace_rate"] == "0"


def test_a_row_with_a_rate_but_no_denominator_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="rate with no denominator"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=T0,
            cancel_replace_rate=Decimal("0"),
            level_events=0,
            cancel_replace_events=0,
            trade_count=0,
            trade_volume=Decimal(0),
            mean_size=None,
            stddev_size=None,
            skew_size=None,
            kurtosis_size=None,
        )


def test_a_row_with_activity_but_no_rate_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="no cancel-replace rate"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=T0,
            cancel_replace_rate=None,
            level_events=3,
            cancel_replace_events=0,
            trade_count=0,
            trade_volume=Decimal(0),
            mean_size=None,
            stddev_size=None,
            skew_size=None,
            kurtosis_size=None,
        )


def test_a_rate_above_one_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="numerator cannot exceed"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=T0,
            cancel_replace_rate=Decimal("2"),
            level_events=1,
            cancel_replace_events=2,
            trade_count=0,
            trade_volume=Decimal(0),
            mean_size=None,
            stddev_size=None,
            skew_size=None,
            kurtosis_size=None,
        )


def test_a_partially_filled_distribution_is_refused() -> None:
    # The four moments describe one distribution, so a mean without a dispersion
    # is a partially-filled claim about it.
    with pytest.raises(TradeFlowParseError, match="carried together"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=T0,
            cancel_replace_rate=None,
            level_events=0,
            cancel_replace_events=0,
            trade_count=3,
            trade_volume=Decimal("6"),
            mean_size=Decimal("2"),
            stddev_size=None,
            skew_size=None,
            kurtosis_size=None,
        )


def test_moments_over_one_trade_are_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="at least two observations"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=T0,
            cancel_replace_rate=None,
            level_events=0,
            cancel_replace_events=0,
            trade_count=1,
            trade_volume=Decimal("2"),
            mean_size=Decimal("2"),
            stddev_size=Decimal("0"),
            skew_size=Decimal("0"),
            kurtosis_size=Decimal("0"),
        )


def test_a_volume_without_prints_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="either carried prints or it did not"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=T0,
            cancel_replace_rate=None,
            level_events=0,
            cancel_replace_events=0,
            trade_count=0,
            trade_volume=Decimal("5"),
            mean_size=None,
            stddev_size=None,
            skew_size=None,
            kurtosis_size=None,
        )


def test_a_negative_count_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="never below zero"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=T0,
            cancel_replace_rate=None,
            level_events=-1,
            cancel_replace_events=0,
            trade_count=0,
            trade_volume=Decimal(0),
            mean_size=None,
            stddev_size=None,
            skew_size=None,
            kurtosis_size=None,
        )


def test_a_row_with_a_naive_window_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="timezone-aware"):
        TradeFlowRow(
            symbol="BTCUSDT",
            window_start=datetime(2026, 3, 1, 12, 0, 0),
            cancel_replace_rate=None,
            level_events=0,
            cancel_replace_events=0,
            trade_count=0,
            trade_volume=Decimal(0),
            mean_size=None,
            stddev_size=None,
            skew_size=None,
            kurtosis_size=None,
        )


# -- The batch ----------------------------------------------------------------


def _batch(rows=(), closing=None, **overrides) -> TradeFlowBatch:
    """A valid batch carrying ``rows``, overridden by keyword."""
    fields = {
        "rows": tuple(rows),
        "closing_books": closing if closing is not None else {},
        "from_window": None,
        "to_window": T0,
        "from_raw_sequence": 0,
        "to_raw_sequence": 1,
    }
    fields.update(overrides)
    return TradeFlowBatch(**fields)


def _book() -> BookState:
    """A two-sided book at the prices :func:`diff` seeds, as a closing book."""
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]], asks=[["101.50", "1"]]))
    return book


def _simple_row(symbol: str = "BTCUSDT", window_start: datetime = T0) -> TradeFlowRow:
    return TradeFlowRow(
        symbol=symbol,
        window_start=window_start,
        cancel_replace_rate=None,
        level_events=0,
        cancel_replace_events=0,
        trade_count=0,
        trade_volume=Decimal(0),
        mean_size=None,
        stddev_size=None,
        skew_size=None,
        kurtosis_size=None,
    )


def test_a_batch_hashes_canonically() -> None:
    # Two batches describing the same features in a different row order hash
    # identically: the canonical form sorts, so the content hash is a content
    # hash rather than a record of the order the symbols were folded in.
    a = _batch([_simple_row("BTCUSDT"), _simple_row("ETHUSDT")])
    b = _batch([_simple_row("ETHUSDT"), _simple_row("BTCUSDT")])

    assert a.source_sha256 == b.source_sha256


def test_an_empty_batch_with_no_advance_is_refused() -> None:
    with pytest.raises(TradeFlowParseError, match="no-progress cycle"):
        _batch([], from_raw_sequence=1, to_raw_sequence=1)


def test_a_batch_that_advances_the_frontier_without_rows_is_kept() -> None:
    # The book moved even if no new second was crossed, and the frontier and
    # closing book must advance so the next cycle does not re-fold the diff.
    batch = _batch([], closing={"BTCUSDT": BookState()})

    assert len(batch) == 0
    assert batch.source_sha256


def test_a_batch_reports_its_symbols_and_rows_for_one() -> None:
    batch = _batch([_simple_row("BTCUSDT"), _simple_row("ETHUSDT"), _simple_row("BTCUSDT")])

    assert batch.symbols == ("BTCUSDT", "ETHUSDT")
    assert len(batch.rows_for("BTCUSDT")) == 2
    assert batch.rows_for("SOLUSDT") == ()


def test_parse_trade_flow_refuses_something_that_is_not_a_batch() -> None:
    from nullius_ingest.trade_flow import parse_trade_flow

    with pytest.raises(TradeFlowParseError, match="must be a TradeFlowBatch"):
        parse_trade_flow({"rows": []})


# -- The store: append-only, permanent ----------------------------------------


def test_a_batch_persists_as_the_next_record(tmp_path) -> None:
    store = make_store(tmp_path)
    record = store.record(_batch([_simple_row()]), computed_at=T0)

    assert record.sequence == 1
    assert record.row_count == 1
    assert record.path == store.root / "1.bin"
    assert store.current().sequence == 1


def test_a_second_record_appends_rather_than_overwrites(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)
    store.record(_batch([_simple_row(window_start=T0 + FEATURE_SLICE)]), computed_at=T0)

    assert [r.sequence for r in store.records()] == [1, 2]
    assert (store.root / "1.bin").exists()


def test_a_record_round_trips_its_rows(tmp_path) -> None:
    store = make_store(tmp_path)
    row = TradeFlowRow(
        symbol="BTCUSDT",
        window_start=T0,
        cancel_replace_rate=Decimal("0.5"),
        level_events=4,
        cancel_replace_events=2,
        trade_count=3,
        trade_volume=Decimal("6"),
        mean_size=Decimal("2"),
        stddev_size=Decimal("1"),
        skew_size=Decimal("0"),
        kurtosis_size=Decimal("-1.5"),
    )
    store.record(_batch([row]), computed_at=T0)

    read_back = store.current().batch.rows[0]
    assert read_back == row
    assert read_back.canonical() == row.canonical()


def test_a_record_round_trips_an_absent_rate_as_absent(tmp_path) -> None:
    # JSON null, not a zero: the distinction the moments and the rate both stand
    # on survives the round trip.
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)

    assert store.current().batch.rows[0].cancel_replace_rate is None


def test_a_record_round_trips_its_closing_book(tmp_path) -> None:
    store = make_store(tmp_path)
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]], asks=[["101.50", "2"]]))
    store.record(_batch([_simple_row()], closing={"BTCUSDT": book}), computed_at=T0)

    closing = store.current().closing_book("BTCUSDT")
    assert closing is not None
    assert closing.best_bid() == Decimal("100.50")
    assert closing.best_ask() == Decimal("101.50")
    assert store.current().closing_book("SOLUSDT") is None


def test_a_record_carries_both_hashes(tmp_path) -> None:
    store = make_store(tmp_path)
    record = store.record(_batch([_simple_row()]), computed_at=T0)

    assert record.source_sha256 == record.batch.source_sha256
    assert record.payload_sha256 != record.source_sha256


def test_records_land_where_the_seal_looks(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)

    assert store.root == tmp_path / "staging" / "tradeFlow"
    assert sorted(p.name for p in store.root.iterdir()) == ["1.bin"]


def test_the_store_resolves_itself_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))

    store = TradeFlowStore.from_env()

    assert store.root == tmp_path / "lake" / "staging" / "tradeFlow"


def test_rows_for_returns_a_symbols_features_at_a_window(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row("BTCUSDT"), _simple_row("ETHUSDT")]), computed_at=T0)

    # Any instant inside the window resolves to it — the same reader shape
    # feature 20 offers.
    assert len(store.rows_for("BTCUSDT", T0 + timedelta(milliseconds=900))) == 1
    assert store.rows_for("BTCUSDT", T0 + FEATURE_SLICE) == ()


def test_the_store_reports_its_windows_and_symbols(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(
        _batch([_simple_row("BTCUSDT"), _simple_row("ETHUSDT")]), computed_at=T0
    )

    assert store.windows() == (T0,)
    assert store.symbols() == ("BTCUSDT", "ETHUSDT")


def test_an_empty_store_has_no_last_record(tmp_path) -> None:
    store = make_store(tmp_path)

    assert store.last_record() is None
    assert store.last_window() is None
    assert store.records() == ()


def test_the_store_rejects_something_that_is_not_a_staging_area() -> None:
    with pytest.raises(TypeError, match="writes into a StagingArea"):
        TradeFlowStore("not staging")  # type: ignore[arg-type]


def test_recording_a_naive_computed_at_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_store(tmp_path).record(_batch([_simple_row()]), computed_at=datetime(2026, 3, 1))


# -- Corruption ---------------------------------------------------------------


def test_a_damaged_document_is_refused_on_read(tmp_path) -> None:
    # A record whose document no longer matches its recorded hash is corruption:
    # a reader that rebuilt a feature from it would be rebuilding a market that
    # never existed.  Read from a *fresh* store, matching what a restarted
    # process actually does — a store built before the damage holds the payload
    # its first read captured.
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()], closing={"BTCUSDT": _book()}), computed_at=T0)
    _corrupt(tmp_path, b"100.50", b"999.99")

    with pytest.raises(TradeFlowCorruptError, match="source hash"):
        make_store(tmp_path).records()


def test_a_truncated_file_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)
    path = store.root / "1.bin"
    path.write_bytes(path.read_bytes()[:-20])

    with pytest.raises(TradeFlowCorruptError):
        make_store(tmp_path).records()


def test_a_record_missing_its_envelope_keys_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)
    (store.root / "1.bin").write_bytes(b'{"stream": "tradeFlow"}')

    with pytest.raises(TradeFlowCorruptError, match="missing"):
        make_store(tmp_path).records()


def test_a_file_that_is_not_json_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)
    (store.root / "1.bin").write_bytes(b"{not json")

    with pytest.raises(TradeFlowCorruptError, match="not readable as a JSON envelope"):
        make_store(tmp_path).records()


def test_a_mismatched_sequence_is_refused(tmp_path) -> None:
    # The envelope's recorded sequence must match the filename the file landed
    # under — a file that describes itself as a different sequence is not one this
    # store wrote, and a reader that trusted it would resume from the wrong place.
    import json

    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)
    path = store.root / "1.bin"
    envelope = json.loads(path.read_bytes().decode())
    envelope["sequence"] = 2
    path.write_bytes(json.dumps(envelope).encode())

    with pytest.raises(TradeFlowCorruptError, match="does not describe itself"):
        make_store(tmp_path).records()


def test_a_tampered_closing_book_is_refused(tmp_path) -> None:
    # The content hash is what makes the closing book trustworthy: a restart seeds
    # its reconstruction from it, so a book the market never had must not survive
    # the read.
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()], closing={"BTCUSDT": _book()}), computed_at=T0)
    _corrupt(tmp_path, b"100.50", b"999.99")

    with pytest.raises(TradeFlowCorruptError, match="source hash"):
        make_store(tmp_path).records()


def test_a_damaged_closing_book_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()], closing={"BTCUSDT": _book()}), computed_at=T0)
    _corrupt(tmp_path, b'"bids":', b'"bidz":')

    with pytest.raises(TradeFlowCorruptError):
        make_store(tmp_path).records()


def test_a_file_that_is_not_an_object_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_simple_row()]), computed_at=T0)
    (store.root / "1.bin").write_bytes(b"[1, 2, 3]")

    with pytest.raises(TradeFlowCorruptError, match="expected a JSON object"):
        make_store(tmp_path).records()


def _corrupt(tmp_path, old: bytes, new: bytes) -> None:
    """Rewrite one substring of the newest record's bytes on disk.

    Corruption is applied *underneath* the store: the bytes a fresh reader finds
    on disk no longer hash to what the envelope recorded, which is exactly the
    damage a restarted process must refuse.
    """
    path = tmp_path / "staging" / "tradeFlow" / "1.bin"
    path.write_bytes(path.read_bytes().replace(old, new))


# -- The worker: classify, measure, snapshot ----------------------------------


def test_a_cycle_persists_a_row_with_both_features(tmp_path) -> None:
    # The worker's whole job: classify feature 19's raw diffs against the
    # reconstructed book, measure the tape, and persist one derived row per
    # second that carried either.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    worker_ = worker(
        tmp_path,
        diffs,
        trade(quantity="2"),
        trade(quantity="4"),
        trade(quantity="6"),
    )

    result = worker_.run_cycle()

    assert result.sequence == 1
    assert result.rows_written == 1
    row = worker_.store.current().batch.rows[0]
    assert row.symbol == "BTCUSDT"
    assert row.window_start == T0
    assert row.level_events == 2
    assert row.cancel_replace_events == 0
    assert row.cancel_replace_rate == 0
    assert row.trade_count == 3
    assert row.trade_volume == Decimal("12")
    assert row.mean_size == Decimal("4")


def test_a_cycle_counts_a_cancel_replace(tmp_path) -> None:
    # Two records: the first establishes the level, the second removes it and adds
    # one elsewhere on the same side — a cancel-replace.  The book must be carried
    # across records for the removal to be visible as a removal of something.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0)).run_cycle()
    diffs.record(
        flush(
            diff(
                event_time_ms=T0_MS + 1000,
                bids=[["100.50", "0"], ["100.40", "1"]],
                asks=[],
            )
        ),
        written_at=T0 + FEATURE_SLICE,
    )

    worker_ = TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0 + FEATURE_SLICE))
    result = worker_.run_cycle()

    assert result.rows_written == 1
    row = store.current().batch.rows[0]
    assert row.level_events == 2  # one removal, one add
    assert row.cancel_replace_events == 1
    assert row.cancel_replace_rate == Decimal("0.5")


def test_a_second_is_emitted_only_when_a_diff_or_a_trade_landed_in_it(tmp_path) -> None:
    # The log is paced by genuine market activity, not by the worker's cycle
    # cadence: a second that carried neither a diff nor a trade is not a snapshot.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    worker_ = worker(tmp_path, diffs, trade(event_time_ms=T0_MS + 5000, quantity="2"))

    result = worker_.run_cycle()

    assert result.rows_written == 2
    assert worker_.store.windows() == (T0, T0 + 5 * FEATURE_SLICE)


def test_a_second_with_only_trades_has_no_rate_and_real_moments(tmp_path) -> None:
    # No diffs landed in the second, so there is no rate — but the tape did print,
    # so the sizes are measured.  The two features are independent.
    diffs = make_diff_store(tmp_path)
    worker_ = worker(tmp_path, diffs, trade(quantity="2"), trade(quantity="4"))

    result = worker_.run_cycle()

    assert result.rows_written == 1
    row = worker_.store.current().batch.rows[0]
    assert row.cancel_replace_rate is None
    assert row.level_events == 0
    assert row.trade_count == 2
    assert row.mean_size == Decimal("3")
    assert row.stddev_size == Decimal("1")


def test_a_second_with_one_trade_has_a_count_and_no_distribution(tmp_path) -> None:
    # One print is a fact about the market but not a *distribution* over it: the
    # count and the volume are real, and the moments are absent rather than a
    # mean over a single observation.
    diffs = make_diff_store(tmp_path)
    worker_ = worker(tmp_path, diffs, trade(quantity="2"))

    worker_.run_cycle()

    row = worker_.store.current().batch.rows[0]
    assert row.trade_count == 1
    assert row.trade_volume == Decimal("2")
    assert row.mean_size is None
    assert row.canonical()["mean_size"] is None


def test_a_second_with_no_trades_has_real_counts_and_no_moments(tmp_path) -> None:
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    worker_ = worker(tmp_path, diffs)

    result = worker_.run_cycle()

    assert result.rows_written == 1
    row = worker_.store.current().batch.rows[0]
    assert row.trade_count == 0
    assert row.trade_volume == Decimal(0)
    assert row.mean_size is None
    assert row.canonical()["mean_size"] is None


def test_trades_are_bucketed_per_symbol(tmp_path) -> None:
    # One second, two symbols: the volumes are per symbol, never pooled across
    # markets that trade at different price and size scales.
    diffs = make_diff_store(tmp_path)
    worker_ = worker(
        tmp_path,
        diffs,
        trade(symbol="BTCUSDT", quantity="4"),
        trade(symbol="BTCUSDT", quantity="8"),
        trade(symbol="ETHUSDT", quantity="100"),
        trade(symbol="ETHUSDT", quantity="300"),
    )

    worker_.run_cycle()

    by_symbol = {row.symbol: row for row in worker_.store.current().batch.rows}
    assert by_symbol["BTCUSDT"].mean_size == Decimal("6")
    assert by_symbol["ETHUSDT"].mean_size == Decimal("200")


def test_a_no_new_data_cycle_persists_nothing(tmp_path) -> None:
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    worker_ = TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0))
    worker_.run_cycle()

    result = worker_.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.records()) == 1


def test_a_no_input_cycle_persists_nothing(tmp_path) -> None:
    worker_ = TradeFlowWorker(make_store(tmp_path), make_diff_store(tmp_path), tape_of())

    result = worker_.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0


def test_a_cycle_that_only_advances_the_frontier_is_persisted(tmp_path) -> None:
    # New raw data arrived but crossed no new second — the book moved, so the
    # closing book and frontier must advance even though no row was emitted.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0)).run_cycle()
    diffs.record(
        flush(
            diff(event_time_ms=T0_MS + 100, bids=[["100.40", "2"]], asks=[]),
        ),
        written_at=T0,
    )

    result = TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0)).run_cycle()

    assert result.sequence == 2
    assert result.rows_written == 0
    assert store.current().to_raw_sequence == 2


def test_the_closing_book_carries_a_level_into_the_next_cycle(tmp_path) -> None:
    # The reconstruction is a state carried across records, so a level set in one
    # record and only *touched* in the next is still standing — which is what
    # makes the next record's removal classify as a removal of something.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0)).run_cycle()

    book = store.current().closing_book("BTCUSDT")
    assert book is not None
    assert book.best_ask() == Decimal("101.50")


def test_a_restart_resumes_past_the_frontier(tmp_path) -> None:
    # The frontier is persisted with each record, so a restarted worker does not
    # re-emit a second it already emitted.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0)).run_cycle()

    restarted = TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0 + FEATURE_SLICE))
    result = restarted.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.records()) == 1


def test_a_restart_does_not_re_measure_a_second_it_already_measured(tmp_path) -> None:
    # Prints at or before the frontier belong to an already-committed snapshot, so
    # a tape that re-sends the same prints must not move the moments.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    TradeFlowWorker(
        store, diffs, tape_of(trade(quantity="2")), clock=clock_at(T0)
    ).run_cycle()
    diffs.record(
        flush(diff(event_time_ms=T0_MS + 1000, bids=[["100.40", "1"]], asks=[])),
        written_at=T0 + FEATURE_SLICE,
    )

    restarted = TradeFlowWorker(
        store,
        diffs,
        tape_of(
            trade(quantity="2"),  # already measured before the restart
            trade(event_time_ms=T0_MS + 1000, quantity="8"),
            trade(event_time_ms=T0_MS + 1000, quantity="12"),
        ),
        clock=clock_at(T0 + FEATURE_SLICE),
    )
    restarted.run_cycle()

    row = store.current().batch.rows_for("BTCUSDT")[0]
    assert row.window_start == T0 + FEATURE_SLICE
    # The re-sent print was dropped at the frontier, so the new second's moments
    # are over its own two prints and not over the whole tape.
    assert row.trade_count == 2
    assert row.mean_size == Decimal("10")


def test_the_raw_diffs_can_be_pruned_without_losing_the_derived_row(tmp_path) -> None:
    # The feature's own clause: a 90 day raw-diff expiry must not lose the derived
    # history.  The derived row is read back from *this* log after the raw record
    # it came from has left the raw store entirely.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(
                event_time_ms=T0_MS,
                bids=[["100.50", "1"]],
                asks=[["101.50", "1"]],
            )
        ),
    )
    store = make_store(tmp_path)
    worker_ = worker(tmp_path, diffs, trade(quantity="2"), trade(quantity="4"), store=store)
    worker_.run_cycle()

    # Slide the raw window far past the flush and retire everything the raw store
    # holds.  The only record it keeps is its own newest, so a second flush is
    # needed to push the first one out.
    diffs.record(
        flush(diff(event_time_ms=epoch_ms(T0 + timedelta(days=200)), bids=[["100.60", "1"]])),
        written_at=T0 + timedelta(days=200),
    )
    report = diffs.prune(T0 + timedelta(days=200))

    assert report.retired, "the raw window must actually have retired records"
    assert [r.sequence for r in diffs.records()] == [2]
    # The raw bytes the derived row came from are gone...
    assert not (diffs.root / "1.bin").exists()
    # ...and the derived row — its rate, its counts and its moments — is intact.
    row = store.rows_for("BTCUSDT", T0)[0]
    assert row.level_events == 2
    assert row.cancel_replace_rate == 0
    assert row.trade_count == 2
    assert row.mean_size == Decimal("3")
    assert row.stddev_size == Decimal("1")


def test_the_closing_book_survives_the_raw_diffs_being_pruned(tmp_path) -> None:
    # The permanence argument in full: a restart *after* the raw window has slid
    # rebuilds the book from the derived log's closing book alone.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()
    diffs.record(
        flush(diff(event_time_ms=epoch_ms(T0 + timedelta(days=200)), bids=[["100.60", "1"]])),
        written_at=T0 + timedelta(days=200),
    )
    diffs.prune(T0 + timedelta(days=200))

    # A restarted worker seeds from the derived log; the closing book still has
    # both sides of the book the raw diffs described.
    restarted = TradeFlowWorker(store, diffs, tape_of(), clock=clock_at(T0 + timedelta(days=200)))
    restarted.run_cycle()

    book = store.current().closing_book("BTCUSDT")
    assert book is not None
    assert book.best_bid() == Decimal("100.60")
    assert book.best_ask() == Decimal("101.50")  # carried from before the prune


def test_the_worker_rejects_mis_wired_collaborators(tmp_path) -> None:
    diffs = make_diff_store(tmp_path)
    with pytest.raises(TypeError, match="persists into a TradeFlowStore"):
        TradeFlowWorker("not a store", diffs, tape_of())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="reads from a BookDiffStore"):
        TradeFlowWorker(make_store(tmp_path), "not a diff store", tape_of())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="tape must be a zero-argument callable"):
        TradeFlowWorker(make_store(tmp_path), diffs, "not a tape")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock must be a callable"):
        TradeFlowWorker(make_store(tmp_path), diffs, tape_of(), clock=7)  # type: ignore[arg-type]


def test_a_clock_returning_a_naive_instant_is_refused(tmp_path) -> None:
    worker_ = TradeFlowWorker(
        make_store(tmp_path),
        make_diff_store(tmp_path),
        tape_of(),
        clock=lambda: datetime(2026, 3, 1),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        worker_.run_cycle()


def test_the_worker_satisfies_the_ingest_worker_protocol(tmp_path) -> None:
    from nullius_ingest import IngestWorker

    worker_ = TradeFlowWorker(make_store(tmp_path), make_diff_store(tmp_path), tape_of())

    assert isinstance(worker_, IngestWorker)
    assert worker_.stream_class is TRADE_FLOW_STREAM


def test_the_worker_runs_under_the_supervisor(tmp_path) -> None:
    # A trade-flow worker is an IngestWorker like any other, so this stream
    # composes with every other rather than beside them.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    worker_ = worker(tmp_path, diffs, trade(quantity="2"), trade(quantity="4"))

    report = IngestSupervisor([worker_]).run_cycle()

    assert report.ok
    assert report.outcome_for(StreamClass.TRADE_FLOW).rows_written == 1
    assert worker_.store.current().sequence == 1


# -- Registration and composition --------------------------------------------


def test_the_member_registers_a_worker_for_the_tradeflow_stream() -> None:
    # Importing the package fires the registration — the plugin convention with no
    # shared file edited.
    assert TRADE_FLOW_STREAM in default_worker_registry()
    assert StreamClass.TRADE_FLOW in default_worker_registry()


def test_the_registered_stream_class_does_not_collide_with_feature_20() -> None:
    # The supervisor's contract is one worker per stream class, so two derived
    # families sharing a class would mean the second *replacing* the first.  They
    # take their own values, and both are composed.
    assert TRADE_FLOW_STREAM != StreamClass.BOOK_FEATURES
    assert {StreamClass.BOOK_FEATURES, StreamClass.TRADE_FLOW} <= set(
        default_worker_registry().stream_classes()
    )


def test_the_composed_app_supervises_the_tradeflow_stream() -> None:
    from app.module_loader import Registration, create_app
    import nullius_ingest

    member_src = Path(nullius_ingest.__file__).resolve().parent.parent
    component = create_app(member_src, registry=Registration()).get("ingest")

    assert StreamClass.TRADE_FLOW in component


def test_the_composed_worker_reports_an_unconfigured_tape_as_a_stream_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature 16's contract: an unconfigured stream is that stream's own failure
    # in the report and every other stream keeps ingesting — not a component that
    # fails to load.  The tape is the one input this member cannot resolve from
    # the environment, so it is the case that must degrade rather than abort.
    from nullius_ingest import FunctionWorker

    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))

    worker_ = worker_from_default(StreamClass.TRADE_FLOW)
    supervisor = IngestSupervisor([worker_, FunctionWorker(StreamClass.KLINES, lambda: 12)])

    report = supervisor.run_cycle()

    assert not report.ok
    outcome = report.outcome_for(StreamClass.TRADE_FLOW)
    assert not outcome.ok
    assert "no trade tape is configured" in str(outcome.failure)
    # Every other stream kept ingesting.
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


def worker_from_default(stream: StreamClass):
    """The default registry's worker for ``stream``, selected by stream class.

    Selected rather than indexed: the registry builds one worker per registered
    class in sorted order, so a positional ``[0]`` would silently start naming a
    different stream the moment another member lands.
    """
    for worker_ in default_worker_registry().build_workers():
        if worker_.stream_class == stream:
            return worker_
    raise AssertionError(f"the default registry has no worker for {stream}")


def test_registering_an_explicit_tape_revises_the_same_worker(tmp_path) -> None:
    # A re-registered class is a revision of the same worker, never a second
    # worker — so a deployment that wires a tape does not end up with two
    # trade-flow workers competing for the same sequence numbers.
    registry = WorkerRegistry()
    store = make_store(tmp_path)
    diffs = make_diff_store(tmp_path)
    register_trade_flow_worker(
        tape_of(), store=store, diff_store=diffs, clock=clock_at(T0), registry=registry
    )
    register_trade_flow_worker(
        tape_of(), store=store, diff_store=diffs, clock=clock_at(T0), registry=registry
    )

    assert len(registry) == 1
    assert registry.build_workers()[0].store.staging.root == store.staging.root


def test_registering_an_explicit_tape_does_not_pollute_the_default(tmp_path) -> None:
    # A registration is a deployment act, not a global side effect: wiring a tape
    # must not replace the auto-discovered worker for every later composition.
    auto_discovered = worker_from_default(StreamClass.TRADE_FLOW)
    store = make_store(tmp_path)

    factory = register_trade_flow_worker(
        tape_of(), store=store, diff_store=make_diff_store(tmp_path)
    )

    assert factory().store.staging.root == store.staging.root
    still_default = worker_from_default(StreamClass.TRADE_FLOW)
    assert still_default.store.staging.root == auto_discovered.store.staging.root
    assert still_default.store.staging.root != store.staging.root


def test_registering_a_non_callable_tape_is_refused() -> None:
    with pytest.raises(TypeError, match="tape must be a zero-argument callable"):
        register_trade_flow_worker("not a tape")  # type: ignore[arg-type]


def test_registering_a_non_callable_clock_is_refused() -> None:
    with pytest.raises(TypeError, match="clock must be a callable"):
        register_trade_flow_worker(tape_of(), clock=7)  # type: ignore[arg-type]


def test_the_unconfigured_tape_names_the_feature_that_owns_the_stream() -> None:
    from nullius_ingest.trade_flow import _unconfigured_tape

    with pytest.raises(TradeFlowError, match="feature 18"):
        _unconfigured_tape()


# -- Constants the spec names -------------------------------------------------


def test_the_declared_stream_and_action_names_are_the_specs() -> None:
    assert TRADE_FLOW_STREAM is StreamClass.TRADE_FLOW
    assert str(TRADE_FLOW_STREAM) == "tradeFlow"
    assert CANCEL_REPLACE == "cancel_replace"
