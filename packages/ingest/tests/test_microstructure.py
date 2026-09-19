"""Microprice, spread and windowed OFI, persisted past the 90 day expiry.

These tests are the feature statement for app_spec.xml feature 21 — *"System
computes microprice, spread and order-flow imbalance over several windows,
persisting each as a permanently retained book feature"* — read as behaviour
of the increment, the trail, the store and the worker they stand on:

* "over several windows" attaches to the **OFI**, as §4.1's own punctuation
  has it (*"microprice, spread, OFI over several windows"*): microprice and
  spread are states at the closed 1s boundary, and the OFI is summed over the
  windows :data:`OFI_WINDOWS` names — slice, 5 s, 10 s and the klines minute;
* the increment is the **best-level Cont–Kukanov–Stoikov order flow** between
  two consecutive top-of-book states, with an empty side read as the price
  sent to its sentinel — so a side appearing or vanishing is measured flow,
  and a stream's opening diff measures the imbalance of the arrival itself;
* a second is snapshotted **when it closes**, not when it opens — the first
  diff of a later second, or the end of the pass — because a flow feature
  must carry the whole window it names, and the windows on a row compose
  exactly: the 60 s window at ``S`` is the sum of the sixty 1 s windows it
  spans;
* an absence is not a zero: a one-sided closing book emits no row, a
  microprice over best sizes totalling zero is ``None``, and an OFI window
  that reaches before the symbol's first observed second is ``None`` — while
  a *covered* window with no events is an exact ``0``;
* a late diff for an already-committed second folds into the going-forward
  book and ledger without re-opening the committed second;
* the per-symbol **OFI trail is persisted with each record**, because a 60 s
  window reaches further back than any single cycle and further than the
  90-day raw window — so a restart, even after the raw diffs are pruned,
  sums its windows from the derived log alone;
* the derived log is append-only and permanent, landing in the same staging
  area the seal copies out of, and damaged bytes are refused rather than
  reconstructed into a plausible feature;
* the worker's input is the *internal* raw-diff store, so the stream composes
  fully configured — there is no unconfigured-fetch failure at all.

The module docstring in ``nullius_ingest.microstructure`` is the design note;
these tests are the behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from nullius_ingest import (
    MICROSTRUCTURE_STREAM,
    OFI_WINDOWS,
    BookDiffStore,
    BookState,
    IngestSupervisor,
    IngestWorker,
    MicrostructureBatch,
    MicrostructureCorruptError,
    MicrostructureParseError,
    MicrostructureRow,
    MicrostructureStore,
    MicrostructureWorker,
    OfiTrail,
    StagingArea,
    StreamClass,
    TopOfBook,
    ofi_increment,
    register_microstructure_worker,
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

SECOND = timedelta(seconds=1)


def epoch_ms(moment: datetime) -> int:
    """``moment`` as epoch milliseconds — the spelling a venue's event time uses."""
    return int(moment.timestamp() * 1000)


# -- The constants the spec names ----------------------------------------------


def test_the_stream_class_is_feature_21s_own_value() -> None:
    # The supervisor's contract is one worker per stream class, so this family
    # takes its own value rather than sharing feature 20's: a second family under
    # one class would mean the second registration *replacing* the first.
    assert MICROSTRUCTURE_STREAM is StreamClass.MICROSTRUCTURE
    assert str(MICROSTRUCTURE_STREAM) == "microstructure"
    assert MICROSTRUCTURE_STREAM != StreamClass.BOOK_FEATURES


def test_the_grid_is_feature_20s_grid() -> None:
    # The three derived families are snapshotted at the same 1s boundary off the
    # same reconstruction, so a second means the same instant in all three logs —
    # which is what lets a reader join the depth ladder to the microstructure.
    from nullius_ingest import (
        MICROSTRUCTURE_SLICE,
        MICROSTRUCTURE_SLICE_MILLISECONDS,
    )
    from nullius_ingest.microstructure import _floor_to_second

    assert MICROSTRUCTURE_SLICE == FEATURE_SLICE == timedelta(seconds=1)
    assert MICROSTRUCTURE_SLICE_MILLISECONDS == 1000
    assert _floor_to_second(T0 + timedelta(milliseconds=1999)) == T0 + FEATURE_SLICE
    assert _floor_to_second(T0 + timedelta(milliseconds=2000)) == T0 + 2 * FEATURE_SLICE


def test_a_naive_instant_is_refused() -> None:
    from nullius_ingest.microstructure import _floor_to_second

    with pytest.raises(ValueError, match="timezone-aware"):
        _floor_to_second(datetime(2026, 3, 1, 12, 0, 0))


def test_the_ofi_windows_ladder_runs_from_slice_to_bar() -> None:
    # The "several windows" of the feature statement: the slice itself, a
    # near-term pair, and the 60s minute the klines stream owns — four windows,
    # mirroring the four-band depth ladder feature 20 persists.  Microprice and
    # spread are deliberately absent: they are states, and §4.1 attaches the
    # windows to the OFI alone.
    from nullius_ingest import MAX_OFI_WINDOW

    assert OFI_WINDOWS == (1, 5, 10, 60)
    assert MAX_OFI_WINDOW == timedelta(seconds=60)


# -- Helpers -------------------------------------------------------------------


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


def make_store(tmp_path) -> MicrostructureStore:
    """A store over a fresh staging area."""
    return MicrostructureStore(StagingArea(tmp_path / "staging"))


def make_diff_store(tmp_path, *batches: dict) -> BookDiffStore:
    """A raw-diff store pre-seeded with the given venue batches, in order."""
    store = BookDiffStore(StagingArea(tmp_path / "staging"))
    for batch in batches:
        store.record(batch, written_at=T0)
    return store


def clock_at(moment: datetime):
    return lambda: moment


def worker(tmp_path, diff_store, store=None) -> MicrostructureWorker:
    """A worker over fresh stores, reducing the raw-diff log."""
    return MicrostructureWorker(
        store if store is not None else make_store(tmp_path),
        diff_store,
        clock=clock_at(T0),
    )


def top(
    bid="100.50",
    bid_quantity="1",
    ask="101.50",
    ask_quantity="3",
) -> TopOfBook:
    """A two-sided top of book at the prices :func:`diff` seeds."""
    return TopOfBook(
        bid=None if bid is None else Decimal(bid),
        bid_quantity=None if bid_quantity is None else Decimal(bid_quantity),
        ask=None if ask is None else Decimal(ask),
        ask_quantity=None if ask_quantity is None else Decimal(ask_quantity),
    )


# -- The top of book ------------------------------------------------------------


def test_the_top_of_book_reads_off_the_reconstruction() -> None:
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]], asks=[["101.50", "3"]]))

    assert TopOfBook.from_book(book) == TopOfBook(
        bid=Decimal("100.50"),
        bid_quantity=Decimal("1"),
        ask=Decimal("101.50"),
        ask_quantity=Decimal("3"),
    )


def test_an_empty_side_has_neither_its_price_nor_its_size() -> None:
    # The pair describes one side, so a caller can never weight a price by a
    # size the book never had — the exact failure the microprice exists to avoid.
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))

    assert TopOfBook.from_book(book) == TopOfBook(
        bid=Decimal("100.50"),
        bid_quantity=Decimal("1"),
        ask=None,
        ask_quantity=None,
    )


def test_a_price_without_its_size_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="price and a size together"):
        TopOfBook(
            bid=Decimal("100.50"), bid_quantity=None, ask=None, ask_quantity=None
        )
    with pytest.raises(MicrostructureParseError, match="price and a size together"):
        TopOfBook(bid=None, bid_quantity=Decimal("1"), ask=None, ask_quantity=None)


def test_a_non_decimal_top_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="must be a Decimal or None"):
        TopOfBook(bid="100.50", bid_quantity="1", ask=None, ask_quantity=None)  # type: ignore[arg-type]


# -- The increment: best-level Cont–Kukanov–Stoikov OFI -------------------------


def test_the_opening_diff_measures_the_arrival_imbalance() -> None:
    # Both sides rise out of nothing at once: the sentinels read the bid side's
    # arrival as positive flow and the ask side's as negative, so the opening
    # diff is ``bid_qty - ask_qty`` — the imbalance of the arrival itself,
    # exactly as the same imbalance would be read at any later instant.
    empty = TopOfBook(bid=None, bid_quantity=None, ask=None, ask_quantity=None)
    assert ofi_increment(empty, top(bid_quantity="3", ask_quantity="3")) == 0
    assert ofi_increment(empty, top(bid_quantity="2", ask_quantity="3")) == -1
    assert ofi_increment(empty, top(bid_quantity="3", ask_quantity="2")) == 1


def test_a_deeper_best_bid_is_positive_flow() -> None:
    # Price unchanged: both indicators fire, and the contribution is the change
    # in size — buying interest deepened the best bid.
    assert ofi_increment(top(bid_quantity="1"), top(bid_quantity="3")) == 2


def test_a_shallower_best_bid_is_negative_flow() -> None:
    assert ofi_increment(top(bid_quantity="3"), top(bid_quantity="1")) == -2


def test_an_improving_best_bid_adds_only_its_new_size() -> None:
    # The price rose: buying interest at the new best, and nothing subtracted —
    # the old size did not withdraw, it was lifted through.
    assert ofi_increment(top(bid="100.50", bid_quantity="1"), top(bid="100.60", bid_quantity="2")) == 2


def test_a_worsening_best_bid_subtracts_its_old_size() -> None:
    assert ofi_increment(top(bid="100.60", bid_quantity="2"), top(bid="100.50", bid_quantity="2")) == -2


def test_an_improving_best_ask_is_negative_flow() -> None:
    # Sellers aggressing toward the bid: the ask side enters with the opposite
    # sign, so a *tighter* ask is negative flow.
    assert ofi_increment(top(ask="101.50", ask_quantity="5"), top(ask="101.40", ask_quantity="5")) == -5


def test_a_retreating_best_ask_is_positive_flow() -> None:
    # Sellers pulling away: the best ask got worse, and that withdrawal is
    # positive flow on the ask side's sign.
    assert ofi_increment(top(ask="101.40", ask_quantity="5"), top(ask="101.50", ask_quantity="5")) == 5


def test_a_best_bid_losing_the_side_is_negative_flow() -> None:
    # The price fell to nothing: the sentinel reads it as the worst possible
    # worsening, so the whole resting size withdraws.
    assert ofi_increment(top(bid_quantity="2"), top(bid=None, bid_quantity=None)) == -2


def test_a_best_ask_losing_the_side_is_positive_flow() -> None:
    # Sellers withdrew to infinity.
    assert ofi_increment(top(ask_quantity="4"), top(ask=None, ask_quantity=None)) == 4


def test_a_bid_side_appearing_is_positive_flow() -> None:
    assert ofi_increment(top(bid=None, bid_quantity=None), top(bid_quantity="2")) == 2


def test_an_ask_side_appearing_is_negative_flow() -> None:
    # The price fell from infinity — a whole side of sellers arriving.
    assert ofi_increment(top(ask=None, ask_quantity=None), top(ask_quantity="4")) == -4


def test_a_change_behind_the_best_level_is_zero_flow() -> None:
    # Best-level OFI: the top did not move, so deep liquidity reshuffling is
    # invisible here — the deeper ladder is feature 20's depth bands.
    before = top()
    after = top()
    assert ofi_increment(before, after) == 0


# -- The OFI trail --------------------------------------------------------------


def trail(*pairs) -> OfiTrail:
    """A trail folded from ``(bucket, increment)`` pairs."""
    trail_ = OfiTrail()
    for bucket, increment in pairs:
        trail_.observe(bucket, Decimal(increment))
    return trail_


def test_the_trail_accumulates_per_second_and_floors_raw_instants() -> None:
    # A caller may pass the event's raw instant; the bucket is the second it
    # lands in.  Two events inside one second are one bucket's accumulation.
    trail_ = OfiTrail()
    trail_.observe(T0 + timedelta(milliseconds=100), Decimal("2"))
    trail_.observe(T0 + timedelta(milliseconds=900), Decimal("3"))

    assert trail_.increments == ((T0, Decimal("5")),)


def test_a_late_bucket_moves_the_first_observation_back() -> None:
    # A late diff for a second the ledger had not begun at still proves that
    # second was observed — and a window spanning it is covered after all.
    trail_ = trail((T0 + SECOND, "2"))
    assert trail_.first_window == T0 + SECOND
    trail_.observe(T0, Decimal("1"))
    assert trail_.first_window == T0


def test_a_window_is_half_open_on_the_past_and_closed_on_the_boundary() -> None:
    # ``(S - W, S]``: the W-second window at ``S`` is exactly the last W
    # one-second buckets ending with ``S`` itself, so consecutive windows tile
    # without overlap and the 60s window is the sum of the sixty 1s windows.
    # A quiet observation one second before the flow seeds the coverage: a
    # window is only vouched for when the ledger saw the book before the
    # window's first event.
    trail_ = trail(
        (T0 - SECOND, "0"),
        (T0, "2"),
        (T0 + SECOND, "3"),
        (T0 + 2 * SECOND, "-1"),
    )

    assert trail_.sum_over(T0, 1) == 2
    assert trail_.sum_over(T0 + SECOND, 1) == 3
    assert trail_.sum_over(T0 + 2 * SECOND, 1) == -1
    # The 3s window at T0+2 is all three; the 2s window excludes the first.
    assert trail_.sum_over(T0 + 2 * SECOND, 3) == 4
    assert trail_.sum_over(T0 + 2 * SECOND, 2) == 2
    # Composition, stated once: wide windows are sums of the slice windows.
    assert trail_.sum_over(T0 + 2 * SECOND, 3) == (
        trail_.sum_over(T0, 1)
        + trail_.sum_over(T0 + SECOND, 1)
        + trail_.sum_over(T0 + 2 * SECOND, 1)
    )


def test_an_uncovered_window_is_none_not_a_partial_sum() -> None:
    # A window that reaches before the first observation saw only part of the
    # flow it names — and, just as importantly, its first event was measured
    # against a book the ledger never saw — so the row says ``None`` rather
    # than under-reporting as though the window were whole.
    assert OfiTrail().sum_over(T0, 1) is None
    assert trail((T0, "2")).sum_over(T0, 1) is None  # the first second itself
    assert trail((T0, "2"), (T0 + SECOND, "3")).sum_over(T0 + SECOND, 5) is None


def test_a_covered_window_with_no_events_is_an_exact_zero() -> None:
    # The ledger was watching, and nothing flowed.  A measurement, not an
    # absence — the distinction the OFI's absences stand on.
    trail_ = trail((T0, "2"))

    assert trail_.sum_over(T0 + 100 * SECOND, 1) == Decimal(0)
    assert trail_.sum_over(T0 + 100 * SECOND, 60) == Decimal(0)


def test_prune_retires_unreachable_buckets_and_keeps_the_coverage_fact() -> None:
    # Every window a future row can name starts past the frontier, so a bucket
    # older than the widest window is unreachable.  ``first_window`` survives:
    # coverage is a fact about where the observations began, and pruning it
    # would quietly turn partial windows into under-reported whole ones.
    trail_ = OfiTrail()
    for index in range(71):
        trail_.observe(T0 + index * SECOND, Decimal(1))
    trail_.prune(T0 + 41 * SECOND)

    buckets = [bucket for bucket, _ in trail_.increments]
    assert buckets[0] == T0 + 41 * SECOND
    assert buckets[-1] == T0 + 70 * SECOND
    assert trail_.first_window == T0


def test_the_trail_round_trips_through_its_snapshot() -> None:
    trail_ = trail((T0, "2"), (T0 + SECOND, "-0.5"))

    rebuilt = OfiTrail.from_snapshot(trail_.snapshot())

    assert rebuilt.first_window == T0
    assert rebuilt.increments == trail_.increments
    assert rebuilt.sum_over(T0 + SECOND, 1) == Decimal("-0.5")


def test_an_empty_trail_snapshots_its_absence() -> None:
    # ``first_window`` is what an old symbol's coverage fact looks like after
    # every increment has been pruned away: null first_window, no buckets.
    rebuilt = OfiTrail.from_snapshot(OfiTrail().snapshot())

    assert rebuilt.first_window is None
    assert rebuilt.increments == ()


def test_a_snapshot_that_is_not_a_mapping_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="is a mapping"):
        OfiTrail.from_snapshot([["2026-03-01T12:00:00+00:00", "1"]])  # type: ignore[arg-type]


def test_a_snapshot_with_an_unparseable_first_window_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="not an ISO-8601"):
        OfiTrail.from_snapshot({"first_window": "not a time", "increments": []})


def test_a_snapshot_with_a_naive_bucket_is_refused() -> None:
    # Coverage needs comparable instants; a naive bucket is not one.
    with pytest.raises(MicrostructureParseError, match="naive"):
        OfiTrail.from_snapshot(
            {"first_window": None, "increments": [["2026-03-01T12:00:00", "1"]]}
        )


def test_a_snapshot_with_a_non_decimal_increment_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="is not a decimal"):
        OfiTrail.from_snapshot(
            {
                "first_window": None,
                "increments": [[T0.isoformat(), "lots"]],
            }
        )


def test_a_snapshot_with_a_malformed_pair_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="a pair carries two"):
        OfiTrail.from_snapshot(
            {"first_window": None, "increments": [[T0.isoformat(), "1", "extra"]]}
        )


def test_a_non_integer_window_length_is_refused() -> None:
    trail_ = trail((T0, "2"))
    with pytest.raises(MicrostructureParseError, match="integer number of seconds"):
        trail_.sum_over(T0, 1.5)  # type: ignore[arg-type]
    with pytest.raises(MicrostructureParseError, match="at least one second"):
        trail_.sum_over(T0, 0)


def test_a_non_decimal_increment_is_refused_by_the_trail() -> None:
    trail_ = OfiTrail()
    with pytest.raises(MicrostructureParseError, match="must be a Decimal"):
        trail_.observe(T0, 2)  # type: ignore[arg-type]
    with pytest.raises(MicrostructureParseError, match="must be a datetime"):
        trail_.observe(T0_MS, Decimal("2"))  # type: ignore[arg-type]


# -- The feature row ------------------------------------------------------------


def _feature_row(
    symbol: str = "BTCUSDT",
    window_start: datetime = T0,
    microprice=Decimal("101.00"),
    spread=Decimal("1.00"),
    best_bid=Decimal("100.50"),
    best_ask=Decimal("101.50"),
    best_bid_quantity=Decimal("1"),
    best_ask_quantity=Decimal("1"),
    ofi=None,
) -> MicrostructureRow:
    """A valid row, overridden by keyword."""
    return MicrostructureRow(
        symbol=symbol,
        window_start=window_start,
        microprice=microprice,
        spread=spread,
        best_bid=best_bid,
        best_ask=best_ask,
        best_bid_quantity=best_bid_quantity,
        best_ask_quantity=best_ask_quantity,
        ofi=ofi
        if ofi is not None
        else {seconds: Decimal(0) for seconds in OFI_WINDOWS},
    )


def test_a_row_floors_its_window_and_renders_canonically() -> None:
    row = _feature_row(
        window_start=T0 + timedelta(milliseconds=1900),
        microprice=Decimal("100.75"),
        spread=Decimal("1.00"),
        ofi={1: Decimal("-2"), 5: Decimal(0), 10: None, 60: None},
    )

    assert row.window_start == T0 + FEATURE_SLICE
    canonical = row.canonical()
    assert canonical["microprice"] == "100.75"
    assert canonical["spread"] == "1.00"
    assert canonical["best_bid_quantity"] == "1"
    # An uncovered window is JSON null, not a sentinel string — an absence is
    # unmistakable for the value zero.
    assert canonical["ofi"] == {"1": "-2", "5": "0", "10": None, "60": None}


def test_the_microprice_is_recomputable_from_the_carried_facts() -> None:
    # The row carries the four facts the feature was computed from, so a reader
    # recomputes the microprice rather than trusting a number whose weights are
    # lost — feature 20's reference-price precedent.
    row = _feature_row(
        microprice=Decimal("100.75"),
        best_bid=Decimal("100.50"),
        best_bid_quantity=Decimal("1"),
        best_ask=Decimal("101.50"),
        best_ask_quantity=Decimal("3"),
    )
    recomputed = (
        row.best_bid * row.best_ask_quantity + row.best_ask * row.best_bid_quantity
    ) / (row.best_bid_quantity + row.best_ask_quantity)

    assert recomputed == Decimal("100.75")
    assert row.microprice == recomputed
    assert row.spread == row.best_ask - row.best_bid


def test_the_microprice_leans_toward_the_heavy_side() -> None:
    # Each side's price weighted by the *other* side's resting size: a heavy
    # ask says fair value sits lower, a heavy bid higher.  That lean is the
    # information the plain mid throws away.
    heavy_ask = _feature_row(
        microprice=Decimal("100.75"),
        best_bid_quantity=Decimal("1"),
        best_ask_quantity=Decimal("3"),
    )
    heavy_bid = _feature_row(
        microprice=Decimal("101.25"),
        best_bid_quantity=Decimal("3"),
        best_ask_quantity=Decimal("1"),
    )

    assert heavy_ask.microprice < (heavy_ask.best_bid + heavy_ask.best_ask) / 2
    assert heavy_bid.microprice > (heavy_bid.best_bid + heavy_bid.best_ask) / 2


def test_a_microprice_over_degenerate_sizes_is_an_absence() -> None:
    # A weight that divides by nothing is not a price: two best sizes summing
    # to zero carry ``None``, and the row says so rather than defaulting.
    row = _feature_row(
        microprice=None,
        best_bid_quantity=Decimal("0"),
        best_ask_quantity=Decimal("0"),
    )

    assert row.microprice is None
    assert row.canonical()["microprice"] is None


def test_a_row_whose_microprice_contradicts_its_sizes_is_refused() -> None:
    # The honest-absence rule, pinned on the row itself: the weighted mid
    # exists exactly when the total is not zero.
    with pytest.raises(MicrostructureParseError, match="weighted mid exists exactly"):
        _feature_row(microprice=None)  # total 2, but no microprice
    with pytest.raises(MicrostructureParseError, match="weighted mid exists exactly"):
        _feature_row(
            microprice=Decimal("100"),
            best_bid_quantity=Decimal("0"),
            best_ask_quantity=Decimal("0"),
        )


def test_a_row_must_carry_exactly_the_ofi_windows() -> None:
    with pytest.raises(MicrostructureParseError, match="exactly the windows"):
        _feature_row(ofi={seconds: Decimal(0) for seconds in OFI_WINDOWS[:2]})
    with pytest.raises(MicrostructureParseError, match="exactly the windows"):
        _feature_row(
            ofi={seconds: Decimal(0) for seconds in (*OFI_WINDOWS, 30)}
        )


def test_ofi_at_reads_a_named_window_and_refuses_an_unnamed_one() -> None:
    row = _feature_row(ofi={1: Decimal("-2"), 5: None, 10: None, 60: None})

    assert row.ofi_at(1) == Decimal("-2")
    assert row.ofi_at(5) is None
    with pytest.raises(KeyError):
        row.ofi_at(30)


def test_a_negative_resting_size_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="never below zero"):
        _feature_row(best_bid_quantity=Decimal("-1"))


def test_a_row_with_a_naive_window_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="timezone-aware"):
        _feature_row(window_start=datetime(2026, 3, 1, 12, 0, 0))


def test_a_row_with_an_empty_symbol_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="non-empty symbol"):
        _feature_row(symbol="")


def test_a_row_with_a_non_decimal_feature_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="must be a Decimal"):
        _feature_row(spread="1.00")  # type: ignore[arg-type]
    with pytest.raises(MicrostructureParseError, match="must be a Decimal or None"):
        _feature_row(microprice="100")  # type: ignore[arg-type]


# -- The batch ------------------------------------------------------------------


def _book() -> BookState:
    """A two-sided book at the prices :func:`diff` seeds, as a closing book."""
    book = BookState()
    book.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]], asks=[["101.50", "1"]]))
    return book


def _batch(rows=(), closing=None, flows=None, **overrides) -> MicrostructureBatch:
    """A valid batch carrying ``rows``, overridden by keyword."""
    fields = {
        "rows": tuple(rows),
        "closing_books": closing if closing is not None else {},
        "closing_flows": flows if flows is not None else {},
        "from_window": None,
        "to_window": T0,
        "from_raw_sequence": 0,
        "to_raw_sequence": 1,
    }
    fields.update(overrides)
    return MicrostructureBatch(**fields)


def test_a_batch_hashes_canonically() -> None:
    # Two batches describing the same features in a different row order hash
    # identically: the content hash is a content hash, not a record of the
    # order the symbols were folded in.
    a = _batch([_feature_row("BTCUSDT"), _feature_row("ETHUSDT")])
    b = _batch([_feature_row("ETHUSDT"), _feature_row("BTCUSDT")])

    assert a.source_sha256 == b.source_sha256


def test_an_empty_batch_with_no_advance_is_refused() -> None:
    with pytest.raises(MicrostructureParseError, match="no-progress cycle"):
        _batch([], from_raw_sequence=1, to_raw_sequence=1)


def test_a_batch_that_advances_the_frontier_without_rows_is_kept() -> None:
    # The book moved even if no second closed two-sided, and the frontier and
    # closing state must advance so the next cycle does not re-fold the diff.
    batch = _batch([], closing={"BTCUSDT": BookState()})

    assert len(batch) == 0
    assert batch.source_sha256


def test_a_batch_reports_its_symbols_and_rows_for_one() -> None:
    batch = _batch(
        [_feature_row("BTCUSDT"), _feature_row("ETHUSDT"), _feature_row("BTCUSDT")]
    )

    assert batch.symbols == ("BTCUSDT", "ETHUSDT")
    assert len(batch.rows_for("BTCUSDT")) == 2
    assert batch.rows_for("SOLUSDT") == ()


def test_parse_microstructure_refuses_something_that_is_not_a_batch() -> None:
    from nullius_ingest import parse_microstructure

    with pytest.raises(MicrostructureParseError, match="must be a MicrostructureBatch"):
        parse_microstructure({"rows": []})


# -- The store: append-only, permanent ------------------------------------------


def test_a_batch_persists_as_the_next_record(tmp_path) -> None:
    store = make_store(tmp_path)
    record = store.record(_batch([_feature_row()]), computed_at=T0)

    assert record.sequence == 1
    assert record.row_count == 1
    assert record.path == store.root / "1.bin"
    assert store.current().sequence == 1


def test_a_second_record_appends_rather_than_overwrites(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row()]), computed_at=T0)
    store.record(_batch([_feature_row(window_start=T0 + FEATURE_SLICE)]), computed_at=T0)

    assert [r.sequence for r in store.records()] == [1, 2]
    assert (store.root / "1.bin").exists()


def test_a_record_round_trips_its_rows_including_absences(tmp_path) -> None:
    store = make_store(tmp_path)
    row = _feature_row(
        microprice=Decimal("100.75"),
        spread=Decimal("1.00"),
        best_bid_quantity=Decimal("1"),
        best_ask_quantity=Decimal("3"),
        ofi={1: Decimal("-2"), 5: Decimal(0), 10: None, 60: None},
    )
    store.record(_batch([row]), computed_at=T0)

    read_back = store.current().batch.rows[0]
    assert read_back == row
    assert read_back.canonical() == row.canonical()
    assert read_back.ofi_at(10) is None
    assert read_back.ofi_at(5) == Decimal(0)


def test_a_record_round_trips_its_closing_book_and_trail(tmp_path) -> None:
    # Both halves of the resume seed: the book a restart reconstructs from, and
    # the trail a restart's windows are summed from.
    store = make_store(tmp_path)
    flows = {"BTCUSDT": trail((T0, "2"), (T0 + SECOND, "3"))}
    store.record(
        _batch([_feature_row()], closing={"BTCUSDT": _book()}, flows=flows),
        computed_at=T0,
    )

    record = store.current()
    closing = record.closing_book("BTCUSDT")
    assert closing is not None
    assert closing.best_bid() == Decimal("100.50")
    flow = record.closing_flow("BTCUSDT")
    assert flow is not None
    assert flow.first_window == T0
    assert flow.sum_over(T0 + SECOND, 1) == Decimal("3")
    assert record.closing_book("SOLUSDT") is None
    assert record.closing_flow("SOLUSDT") is None


def test_a_record_carries_both_hashes(tmp_path) -> None:
    store = make_store(tmp_path)
    record = store.record(_batch([_feature_row()]), computed_at=T0)

    assert record.source_sha256 == record.batch.source_sha256
    assert record.payload_sha256 != record.source_sha256


def test_records_land_where_the_seal_looks(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row()]), computed_at=T0)

    assert store.root == tmp_path / "staging" / "microstructure"
    assert sorted(p.name for p in store.root.iterdir()) == ["1.bin"]


def test_the_store_resolves_itself_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))

    store = MicrostructureStore.from_env()

    assert store.root == tmp_path / "lake" / "staging" / "microstructure"


def test_rows_for_returns_a_symbols_features_at_a_window(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row("BTCUSDT"), _feature_row("ETHUSDT")]), computed_at=T0)

    # Any instant inside the window resolves to it — the same reader shape
    # features 20 and 22 offer, which is what lets a reader join the three
    # derived logs on a second.
    assert len(store.rows_for("BTCUSDT", T0 + timedelta(milliseconds=900))) == 1
    assert store.rows_for("BTCUSDT", T0 + FEATURE_SLICE) == ()


def test_the_store_reports_its_windows_and_symbols(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row("BTCUSDT"), _feature_row("ETHUSDT")]), computed_at=T0)

    assert store.windows() == (T0,)
    assert store.symbols() == ("BTCUSDT", "ETHUSDT")


def test_an_empty_store_has_no_last_record(tmp_path) -> None:
    store = make_store(tmp_path)

    assert store.last_record() is None
    assert store.last_window() is None
    assert store.records() == ()


def test_the_store_rejects_something_that_is_not_a_staging_area() -> None:
    with pytest.raises(TypeError, match="writes into a StagingArea"):
        MicrostructureStore("not staging")  # type: ignore[arg-type]


def test_recording_a_naive_computed_at_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_store(tmp_path).record(
            _batch([_feature_row()]), computed_at=datetime(2026, 3, 1)
        )


# -- Corruption -----------------------------------------------------------------


def test_a_damaged_document_is_refused_on_read(tmp_path) -> None:
    # A record whose document no longer matches its recorded hash is corruption:
    # a reader that rebuilt a feature from it would be rebuilding a market that
    # never existed.  Read from a *fresh* store, matching what a restarted
    # process actually does.
    store = make_store(tmp_path)
    store.record(
        _batch([_feature_row()], closing={"BTCUSDT": _book()}), computed_at=T0
    )
    _corrupt(tmp_path, b"100.50", b"999.99")

    with pytest.raises(MicrostructureCorruptError, match="source hash"):
        make_store(tmp_path).records()


def test_a_truncated_file_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row()]), computed_at=T0)
    path = store.root / "1.bin"
    path.write_bytes(path.read_bytes()[:-20])

    with pytest.raises(MicrostructureCorruptError):
        make_store(tmp_path).records()


def test_a_record_missing_its_envelope_keys_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row()]), computed_at=T0)
    (store.root / "1.bin").write_bytes(b'{"stream": "microstructure"}')

    with pytest.raises(MicrostructureCorruptError, match="missing"):
        make_store(tmp_path).records()


def test_a_file_that_is_not_json_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row()]), computed_at=T0)
    (store.root / "1.bin").write_bytes(b"{not json")

    with pytest.raises(MicrostructureCorruptError, match="not readable as a JSON envelope"):
        make_store(tmp_path).records()


def test_a_mismatched_sequence_is_refused(tmp_path) -> None:
    # The envelope's recorded sequence must match the filename the file landed
    # under — a reader that trusted a mismatched one would resume from the
    # wrong place.
    import json

    store = make_store(tmp_path)
    store.record(_batch([_feature_row()]), computed_at=T0)
    path = store.root / "1.bin"
    envelope = json.loads(path.read_bytes().decode())
    envelope["sequence"] = 2
    path.write_bytes(json.dumps(envelope).encode())

    with pytest.raises(MicrostructureCorruptError, match="does not describe itself"):
        make_store(tmp_path).records()


def test_a_damaged_closing_flow_is_refused(tmp_path) -> None:
    # The trail is the other half of the resume seed: a damaged one would
    # measure a restarted worker's windows from flow the market never had,
    # which is worse than the damage being visible, because the windows would
    # still look whole.
    store = make_store(tmp_path)
    store.record(
        _batch([_feature_row()], flows={"BTCUSDT": trail((T0, "2"))}), computed_at=T0
    )
    _corrupt(tmp_path, b'"first_window"', b'"firstWindow"')

    with pytest.raises(MicrostructureCorruptError, match="not a trail snapshot"):
        make_store(tmp_path).records()


def test_a_file_that_is_not_an_object_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch([_feature_row()]), computed_at=T0)
    (store.root / "1.bin").write_bytes(b"[1, 2, 3]")

    with pytest.raises(MicrostructureCorruptError, match="expected a JSON object"):
        make_store(tmp_path).records()


def _corrupt(tmp_path, old: bytes, new: bytes) -> None:
    """Rewrite one substring of the newest record's bytes on disk."""
    path = tmp_path / "staging" / "microstructure" / "1.bin"
    path.write_bytes(path.read_bytes().replace(old, new))


# -- The worker: reconstruct, fold, close each second ---------------------------


def test_a_cycle_persists_rows_with_the_state_features(tmp_path) -> None:
    # The worker's whole job: reconstruct the book from feature 19's raw diffs,
    # take each second's top of book when the second *closes*, and persist the
    # microprice, the spread and the windows.  Two diffs across two seconds
    # close two seconds.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "3"]]),
            diff(
                event_time_ms=T0_MS + 1000,
                bids=[["100.50", "3"]],
                asks=[],
            ),
        ),
    )
    worker_ = worker(tmp_path, diffs)

    result = worker_.run_cycle()

    assert result.sequence == 1
    assert result.rows_written == 2
    assert worker_.store.windows() == (T0, T0 + FEATURE_SLICE)


def test_the_row_carries_the_hand_computed_microprice_and_spread(tmp_path) -> None:
    # bid 100.50 x 1 against ask 101.50 x 3: each side's price weighted by the
    # other side's size is (100.50*3 + 101.50*1)/4 = 100.75 — the microprice
    # leans toward the bid because the ask is the heavy side.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "3"]])),
    )
    worker_ = worker(tmp_path, diffs)

    worker_.run_cycle()
    row = worker_.store.rows_for("BTCUSDT", T0)[0]

    assert row.microprice == Decimal("100.75")
    assert row.spread == Decimal("1.00")
    assert row.best_bid == Decimal("100.50")
    assert row.best_bid_quantity == Decimal("1")
    assert row.best_ask_quantity == Decimal("3")
    # The reader can recompute the feature from the carried facts.
    assert row.microprice == (
        row.best_bid * row.best_ask_quantity + row.best_ask * row.best_bid_quantity
    ) / (row.best_bid_quantity + row.best_ask_quantity)


def test_a_second_closes_only_when_it_is_whole(tmp_path) -> None:
    # A single diff in a single second: the second has no later second to
    # witness its close, so the pass end closes it — the row exists, and its
    # 1s OFI window is the flow of that whole second.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    worker_ = worker(tmp_path, diffs)

    result = worker_.run_cycle()

    assert result.rows_written == 1
    row = worker_.store.rows_for("BTCUSDT", T0)[0]
    # The opening diff measured against an unseeded book: the increment is an
    # honest zero, but the 1s window at the *first* second is not covered —
    # its begin reaches before the first observation.
    assert row.ofi_at(1) is None


def test_the_ofi_windows_compose_across_the_slice(tmp_path) -> None:
    # Sixty-one seconds of alternating best-bid size: +2 on the odd seconds,
    # -2 on the even ones.  The 60s window at T0+60 is the sum of the sixty
    # 1s windows it spans — exactly zero — while the 1s window carries the
    # second's own flow and the 5s window the last five seconds'.
    alternating = [diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])]
    for index in range(1, 61):
        quantity = "3" if index % 2 else "1"
        alternating.append(
            diff(
                event_time_ms=T0_MS + index * 1000,
                bids=[["100.50", quantity]],
                asks=[],
            )
        )
    diffs = make_diff_store(tmp_path, flush(*alternating))
    worker_ = worker(tmp_path, diffs)

    result = worker_.run_cycle()

    assert result.rows_written == 61
    row = worker_.store.rows_for("BTCUSDT", T0 + 60 * FEATURE_SLICE)[0]
    assert row.ofi_at(1) == Decimal("-2")  # even second: 3 -> 1
    assert row.ofi_at(5) == Decimal("-2")  # -2 +2 -2 +2 -2
    assert row.ofi_at(10) == Decimal("0")  # five of each
    assert row.ofi_at(60) == Decimal("0")  # thirty of each: the exact sum
    assert row.microprice == Decimal("101.00")  # bid 100.50x1 vs ask 101.50x1


def test_a_window_becomes_covered_only_when_it_reaches_no_further_back(tmp_path) -> None:
    # The honest-absence ladder: the 5s window is None until five seconds have
    # been observed — T0+4's window reaches before T0 — and a covered value
    # from T0+5 on.  The 60s window stays uncovered until the full minute.
    alternating = [diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])]
    for index in range(1, 60):
        alternating.append(
            diff(
                event_time_ms=T0_MS + index * 1000,
                bids=[["100.50", "3" if index % 2 else "1"]],
                asks=[],
            )
        )
    diffs = make_diff_store(tmp_path, flush(*alternating))
    worker_ = worker(tmp_path, diffs)

    worker_.run_cycle()

    assert worker_.store.rows_for("BTCUSDT", T0 + 4 * FEATURE_SLICE)[0].ofi_at(5) is None
    assert (
        worker_.store.rows_for("BTCUSDT", T0 + 5 * FEATURE_SLICE)[0].ofi_at(5)
        == Decimal("2")
    )
    assert worker_.store.rows_for("BTCUSDT", T0 + 59 * FEATURE_SLICE)[0].ofi_at(60) is None


def test_a_one_sided_closing_book_emits_no_row(tmp_path) -> None:
    # An absence, not a zero: a second whose closing book has an empty side has
    # no top of book, so it is not a microstructure snapshot.  The cycle still
    # persists — the frontier and the closing book advanced.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[]),
            diff(event_time_ms=T0_MS + 1000, bids=[["100.60", "1"]], asks=[]),
        ),
    )
    worker_ = worker(tmp_path, diffs)

    result = worker_.run_cycle()

    assert result.sequence == 1
    assert result.rows_written == 0
    assert worker_.store.windows() == ()
    closing = worker_.store.current().closing_book("BTCUSDT")
    assert closing is not None
    assert closing.best_ask() is None


def test_the_book_gaining_its_second_side_later_starts_the_rows(tmp_path) -> None:
    # The one-sided seconds stay absent; the first two-sided closing book is
    # the first row, with an OFI increment measured through the sentinel.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[]),
            diff(
                event_time_ms=T0_MS + 1000,
                bids=[],
                asks=[["101.50", "3"]],
            ),
        ),
    )
    worker_ = worker(tmp_path, diffs)

    worker_.run_cycle()

    assert worker_.store.windows() == (T0 + FEATURE_SLICE,)
    row = worker_.store.rows_for("BTCUSDT", T0 + FEATURE_SLICE)[0]
    # The ask side fell from infinity: the whole arriving size is negative
    # flow, and the 1s window is covered because the bid side was observed a
    # second before the window began.
    assert row.ofi_at(1) == Decimal("-3")
    assert row.microprice == Decimal("100.75")  # leans toward the bid: heavy ask


def test_a_late_diff_folds_but_never_reopens_a_committed_second(tmp_path) -> None:
    # The log is append-only and a committed window is never amended: a late
    # diff for an already-emitted second updates the going-forward book and
    # ledger — its flow enters the *later* windows — but emits no second row
    # for that second and leaves the committed row byte-identical.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]]),
            diff(event_time_ms=T0_MS + 1000, bids=[["100.50", "3"]], asks=[]),
        ),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()
    before = store.rows_for("BTCUSDT", T0)[0]
    diffs.record(
        flush(diff(event_time_ms=T0_MS + 100, bids=[["100.50", "5"]], asks=[])),
        written_at=T0,
    )

    result = worker(tmp_path, diffs, store=store).run_cycle()

    assert result.sequence == 2
    assert result.rows_written == 0  # no *new* second closed
    assert len(store.rows_for("BTCUSDT", T0)) == 1  # and none re-emitted
    assert store.rows_for("BTCUSDT", T0)[0] == before
    # The fold is real, though: the closing book carries the late size.
    closing = store.current().closing_book("BTCUSDT")
    assert closing is not None
    assert closing.best_bid_quantity() == Decimal("5")


def test_a_late_diffs_flow_enters_only_the_later_windows(tmp_path) -> None:
    # The counterfactual that proves the late fold reached the ledger: a late
    # diff for the *second* second folds +2 into bucket T0+1 after that
    # second's row was already committed.  The committed row keeps its own
    # window, never amended — and the 5s window at T0+5 sees the bucket's full
    # +4, because a wide window is a sum over buckets, not over rows.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]]),
            diff(event_time_ms=T0_MS + 1000, bids=[["100.50", "3"]], asks=[]),
        ),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()
    diffs.record(
        flush(
            diff(event_time_ms=T0_MS + 1100, bids=[["100.50", "5"]], asks=[])
        ),
        written_at=T0,
    )
    worker(tmp_path, diffs, store=store).run_cycle()
    diffs.record(
        flush(diff(event_time_ms=T0_MS + 5000, bids=[["100.50", "7"]], asks=[])),
        written_at=T0,
    )
    worker(tmp_path, diffs, store=store).run_cycle()

    committed = store.rows_for("BTCUSDT", T0 + FEATURE_SLICE)[0]
    assert committed.ofi_at(1) == Decimal("2")  # the committed window, unchanged
    row = store.rows_for("BTCUSDT", T0 + 5 * FEATURE_SLICE)[0]
    assert row.ofi_at(1) == Decimal("2")  # 5 -> 7
    # (T0, T0+5]: bucket T0+1's full +4 (committed +2, late +2) and +2 now.
    assert row.ofi_at(5) == Decimal("6")


def test_a_no_new_data_cycle_persists_nothing(tmp_path) -> None:
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()

    result = worker(tmp_path, diffs, store=store).run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.records()) == 1


def test_a_no_input_cycle_persists_nothing(tmp_path) -> None:
    worker_ = worker(tmp_path, make_diff_store(tmp_path))

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
    worker(tmp_path, diffs, store=store).run_cycle()
    diffs.record(
        flush(diff(event_time_ms=T0_MS + 100, bids=[["100.40", "2"]], asks=[])),
        written_at=T0,
    )

    result = worker(tmp_path, diffs, store=store).run_cycle()

    assert result.sequence == 2
    assert result.rows_written == 0
    assert store.current().to_raw_sequence == 2


def test_a_restart_does_not_reemit_a_second_it_already_committed(tmp_path) -> None:
    # The frontier is persisted with each record, so a restarted worker does
    # not re-emit a second it already emitted — and the reconstruction resumes
    # from the closing book rather than re-deriving from the raw diffs.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]]),
            diff(event_time_ms=T0_MS + 1000, bids=[["100.50", "3"]], asks=[]),
        ),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()
    diffs.record(
        flush(diff(event_time_ms=T0_MS + 2000, bids=[["100.50", "5"]], asks=[])),
        written_at=T0,
    )

    restarted = worker(tmp_path, diffs, store=store)
    result = restarted.run_cycle()

    assert result.sequence == 2
    assert result.rows_written == 1  # only the new second
    row = store.current().batch.rows[0]
    assert row.window_start == T0 + 2 * FEATURE_SLICE
    # The book resumed from the closing state: the increment is 3 -> 5, not
    # 1 -> 5 — the reconstruction itself is a carried state.
    assert row.ofi_at(1) == Decimal("2")
    # The 5s window still reaches before the first observation, so it is
    # honestly uncovered rather than a partial sum.
    assert row.ofi_at(5) is None


def test_a_restarts_windows_sum_from_the_persisted_trail(tmp_path) -> None:
    # The permanence argument for the trail in full: a 60s window at T0+5
    # spans seconds observed *before* the restart, whose raw diffs are not
    # re-read.  The trail persisted with the record answers the window.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]]),
            diff(event_time_ms=T0_MS + 1000, bids=[["100.50", "3"]], asks=[]),
            diff(event_time_ms=T0_MS + 2000, bids=[["100.50", "5"]], asks=[]),
        ),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()
    diffs.record(
        flush(diff(event_time_ms=T0_MS + 5000, bids=[["100.50", "1"]], asks=[])),
        written_at=T0,
    )

    restarted = worker(tmp_path, diffs, store=store)
    restarted.run_cycle()

    row = store.rows_for("BTCUSDT", T0 + 5 * FEATURE_SLICE)[0]
    # The second's own flow: 5 -> 1 is -4.
    assert row.ofi_at(1) == Decimal("-4")
    # The 5s window spans T0+1..T0+5: +2 +2 (pre-restart) and -4 (now) = 0,
    # covered because T0 was observed before the window began.
    assert row.ofi_at(5) == Decimal("0")
    assert row.ofi_at(60) is None  # a minute has not been observed yet


def test_the_trail_is_pruned_to_what_future_windows_can_reach(tmp_path) -> None:
    # Bounded state: a cycle whose frontier reaches T0+100 retires every bucket
    # older than T0+41 — the widest window back, with a slice of margin —
    # while ``first_window`` survives to vouch for coverage.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]]),
            diff(
                event_time_ms=epoch_ms(T0 + 100 * SECOND),
                bids=[["100.50", "3"]],
                asks=[],
            ),
        ),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()

    flow = store.current().closing_flow("BTCUSDT")
    assert flow is not None
    assert [bucket for bucket, _ in flow.increments] == [T0 + 100 * SECOND]
    assert flow.first_window == T0


def test_the_trail_prunes_across_a_long_cycle(tmp_path) -> None:
    # The pruning itself: a cycle whose span exceeds the widest window leaves a
    # trail holding only the reachable tail — first_window excluded from the
    # buckets but preserved as the coverage fact.
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
    worker(tmp_path, diffs, store=store).run_cycle()
    late_flush = flush(
        diff(
            event_time_ms=epoch_ms(T0 + 70 * SECOND),
            bids=[["100.50", "3"]],
            asks=[],
        )
    )
    diffs.record(late_flush, written_at=T0)

    worker(tmp_path, diffs, store=store).run_cycle()

    flow = store.current().closing_flow("BTCUSDT")
    assert flow is not None
    assert [bucket for bucket, _ in flow.increments] == [T0 + 70 * SECOND]
    assert flow.first_window == T0


def test_symbols_are_reduced_independently(tmp_path) -> None:
    # One second, two symbols: the microprices are per symbol, never pooled
    # across markets that trade at different price and size scales.
    diffs = make_diff_store(
        tmp_path,
        flush(
            diff(
                symbol="BTCUSDT",
                event_time_ms=T0_MS,
                bids=[["100.50", "1"]],
                asks=[["101.50", "3"]],
            ),
            diff(
                symbol="ETHUSDT",
                event_time_ms=T0_MS,
                bids=[["2000.00", "2"]],
                asks=[["2001.00", "2"]],
            ),
        ),
    )
    worker_ = worker(tmp_path, diffs)

    worker_.run_cycle()

    btc = worker_.store.rows_for("BTCUSDT", T0)[0]
    eth = worker_.store.rows_for("ETHUSDT", T0)[0]
    assert btc.microprice == Decimal("100.75")
    assert eth.microprice == Decimal("2000.50")


def test_the_raw_diffs_can_be_pruned_without_losing_the_derived_row(tmp_path) -> None:
    # The feature's own clause: the derived history is permanently retained, so
    # a 90-day raw-diff expiry must not lose it.  The row is read back from
    # *this* log after the raw record it came from has left the raw store.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "3"]])),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()

    diffs.record(
        flush(diff(event_time_ms=epoch_ms(T0 + timedelta(days=200)), bids=[["100.60", "1"]])),
        written_at=T0 + timedelta(days=200),
    )
    report = diffs.prune(T0 + timedelta(days=200))

    assert report.retired, "the raw window must actually have retired records"
    assert not (diffs.root / "1.bin").exists()
    # ...and the derived row — microprice, spread and windows — is intact.
    row = store.rows_for("BTCUSDT", T0)[0]
    assert row.microprice == Decimal("100.75")
    assert row.spread == Decimal("1.00")
    assert row.ofi_at(1) is None  # the first second stays honestly uncovered


def test_a_restart_after_the_prune_still_covers_its_windows(tmp_path) -> None:
    # The permanence argument in full: a restart *after* the raw window has
    # slid reconstructs from the derived log's closing book alone, and its
    # window coverage is vouched for by the persisted trail's first_window —
    # the 60s window is covered even though every raw diff from inside it is
    # gone, and it reports an honest zero because nothing flowed.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    store = make_store(tmp_path)
    worker(tmp_path, diffs, store=store).run_cycle()
    diffs.record(
        flush(
            diff(
                event_time_ms=epoch_ms(T0 + timedelta(days=200)),
                bids=[["100.60", "1"]],
                asks=[],
            )
        ),
        written_at=T0 + timedelta(days=200),
    )
    diffs.prune(T0 + timedelta(days=200))

    restarted = MicrostructureWorker(
        store, diffs, clock=clock_at(T0 + timedelta(days=200))
    )
    restarted.run_cycle()

    row = store.rows_for("BTCUSDT", T0 + timedelta(days=200))[0]
    # The bid improved 100.50 -> 100.60 against the carried book: +1 flow.
    assert row.ofi_at(1) == Decimal("1")
    # Covered — the trail's first_window survived the prune — and carrying the
    # second's own +1, even though every *other* bucket inside the window is
    # gone with the raw diffs.  The derived log alone answered the window.
    assert row.ofi_at(60) == Decimal("1")
    assert row.best_bid == Decimal("100.60")
    assert row.best_ask == Decimal("101.50")  # carried from before the prune


def test_the_worker_rejects_mis_wired_collaborators(tmp_path) -> None:
    diffs = make_diff_store(tmp_path)
    with pytest.raises(TypeError, match="persists into a MicrostructureStore"):
        MicrostructureWorker("not a store", diffs)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="reads from a BookDiffStore"):
        MicrostructureWorker(make_store(tmp_path), "not a diff store")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock must be a callable"):
        MicrostructureWorker(make_store(tmp_path), diffs, clock=7)  # type: ignore[arg-type]


def test_a_clock_returning_a_naive_instant_is_refused(tmp_path) -> None:
    worker_ = MicrostructureWorker(
        make_store(tmp_path),
        make_diff_store(tmp_path),
        clock=lambda: datetime(2026, 3, 1),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        worker_.run_cycle()


def test_the_worker_satisfies_the_ingest_worker_protocol(tmp_path) -> None:
    worker_ = worker(tmp_path, make_diff_store(tmp_path))

    assert isinstance(worker_, IngestWorker)
    assert worker_.stream_class is MICROSTRUCTURE_STREAM


def test_the_worker_runs_under_the_supervisor(tmp_path) -> None:
    # A microstructure worker is an IngestWorker like any other, so this stream
    # composes with every other rather than beside them.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.50", "1"]], asks=[["101.50", "1"]])),
    )
    worker_ = worker(tmp_path, diffs)

    report = IngestSupervisor([worker_]).run_cycle()

    assert report.ok
    assert report.outcome_for(StreamClass.MICROSTRUCTURE).rows_written == 1
    assert worker_.store.current().sequence == 1


# -- Registration and composition -----------------------------------------------


def test_the_member_registers_a_worker_for_the_microstructure_stream() -> None:
    # Importing the package fires the registration — the plugin convention with
    # no shared file edited.
    assert MICROSTRUCTURE_STREAM in default_worker_registry()
    assert StreamClass.MICROSTRUCTURE in default_worker_registry()


def test_the_registered_stream_class_does_not_collide_with_its_neighbours() -> None:
    # The supervisor's contract is one worker per stream class, so two derived
    # families sharing a class would mean the second *replacing* the first.
    # They take their own values, and all three are composed.
    assert {StreamClass.BOOK_FEATURES, StreamClass.MICROSTRUCTURE, StreamClass.TRADE_FLOW} <= set(
        default_worker_registry().stream_classes()
    )


def test_the_composed_app_supervises_the_microstructure_stream() -> None:
    from app.module_loader import Registration, create_app
    import nullius_ingest

    member_src = Path(nullius_ingest.__file__).resolve().parent.parent
    component = create_app(member_src, registry=Registration()).get("ingest")

    assert StreamClass.MICROSTRUCTURE in component


def test_the_composed_worker_needs_no_venue_fetch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The worker's input is the *internal* raw-diff store, not a venue
    # endpoint, so — unlike the trade-flow worker's injected tape — there is no
    # unconfigured-fetch failure at all: the stream composes fully configured
    # and an empty lake simply yields an empty cycle.
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))

    worker_ = worker_from_default(StreamClass.MICROSTRUCTURE)
    report = IngestSupervisor([worker_]).run_cycle()

    assert report.ok
    assert report.outcome_for(StreamClass.MICROSTRUCTURE).rows_written == 0


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


def test_registering_explicit_stores_revises_the_same_worker(tmp_path) -> None:
    # A re-registered class is a revision of the same worker, never a second
    # worker — so a deployment that wires stores does not end up with two
    # microstructure workers competing for the same sequence numbers.
    registry = WorkerRegistry()
    store = make_store(tmp_path)
    diffs = make_diff_store(tmp_path)
    register_microstructure_worker(
        store=store, diff_store=diffs, clock=clock_at(T0), registry=registry
    )
    register_microstructure_worker(
        store=store, diff_store=diffs, clock=clock_at(T0), registry=registry
    )

    assert len(registry) == 1
    built = registry.build_workers()[0]
    assert isinstance(built, MicrostructureWorker)
    assert built.store.staging.root == store.staging.root


def test_registering_explicit_stores_does_not_pollute_the_default(tmp_path) -> None:
    # A registration is a deployment act, not a global side effect: wiring
    # stores must not replace the auto-discovered worker for every later
    # composition.
    auto_discovered = worker_from_default(StreamClass.MICROSTRUCTURE)
    store = make_store(tmp_path)

    factory = register_microstructure_worker(
        store=store, diff_store=make_diff_store(tmp_path)
    )

    assert factory().store.staging.root == store.staging.root
    still_default = worker_from_default(StreamClass.MICROSTRUCTURE)
    assert still_default.store.staging.root == auto_discovered.store.staging.root
    assert still_default.store.staging.root != store.staging.root


def test_registering_a_non_callable_clock_is_refused() -> None:
    with pytest.raises(TypeError, match="clock must be a callable"):
        register_microstructure_worker(clock=7)  # type: ignore[arg-type]
