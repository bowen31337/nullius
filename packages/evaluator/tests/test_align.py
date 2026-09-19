"""Feature 75 — aligning forward returns at the five horizons.

app_spec.xml feature 75: *"System aligns forward returns at horizons of 1, 2,
5, 10 and 20 periods, which returns one target series per horizon."*
docs/nullius-tech-architecture.md §6.1 names the step — ``4. align_targets
fetch forward returns at horizons h ∈ {1,2,5,10,20}``.

This suite tests the alignment — the *one target series per horizon* half of
the feature sentence — separately from the execution whose grid it aligns
against (which ``test_execute.py`` covers) and from the normalization that
preceded it (``test_normalize.py``), because the three are independently
testable and a bug in one would be masked by another:

* **one series per horizon** — the result carries exactly the five horizons
  the spec names, always, including a horizon whose coverage is empty;
* **the arithmetic** — the target is the simple forward return
  ``close[d+h] / close[d] − 1``, per symbol, over the cross-section that was
  scored;
* **a period is a bar, not a calendar day** — horizons step on the market
  grid, so horizon 1 from a Friday lands on the Monday bar;
* **absence, never zeros** — a symbol missing its exit bar and a rebalance
  date whose h-period future does not exist are absent from the series, and
  coverage shrinks as the horizon grows;
* **the alignment is aligned to the execution** — the entry close must exist
  on every scored symbol's rebalance date (the roster guaranteed the bar),
  and closes of unscored symbols are ignored, so a whole-market fetch and a
  scored-universe fetch align identically;
* **the coverage refusal** — an alignment with no computable target at any
  horizon is refused, not returned as five empty series;
* **the input contract** — a malformed closes fetch (bad key, non-finite or
  non-positive price, a datetime key) is refused by name;
* **the records** — read-only capture, hashability, and the hand-built
  record invariants (the closed horizon set, the bundle's provenance
  coherence).

The execution is built by hand (:class:`SignalExecution` is a frozen
dataclass), so these tests assert the alignment — the grid walk, the
arithmetic, the refusals — without spawning a sandbox or resolving a window.
"""

from __future__ import annotations

import datetime as dt
from types import MappingProxyType

import pytest

from evaluator import (
    AlignedTargets,
    EvaluatorAlignmentError,
    HORIZONS,
    RawScoreVector,
    SignalExecution,
    TargetSeries,
    align_targets,
)

_START = dt.date(2026, 9, 1)


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid.

    Consecutive calendar days are not how real bars lay out (markets close),
    which is exactly why the *stepping* test below uses a weekend grid; for
    the arithmetic tests a dense grid keeps the index math readable.
    """
    return tuple(start + dt.timedelta(days=i) for i in range(count))


def _execution(
    dates,
    universe: tuple[str, ...] = ("AAA", "BBB"),
    *,
    snapshot_name: str = "snap_abc123",
    per_date_universe: dict[dt.date, tuple[str, ...]] | None = None,
    conforming: bool = True,
) -> SignalExecution:
    """A hand-built execution — feature 73's output — as the alignment consumes it.

    Every date gets one vector over ``universe`` (or its own, via
    ``per_date_universe``).  ``conforming=False`` populates the contract
    problems, because the alignment is over the *grid*, not over
    conformingness — a date the signal failed to score cleanly still has an
    h-period future.  The scores themselves are opaque to this step either
    way (step 4 consumes the grid and the universes, never the values), so
    they are left unset.
    """
    vectors = {}
    for day in dates:
        symbols = (
            per_date_universe[day] if per_date_universe is not None else universe
        )
        vectors[day] = RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(
                day, dt.time(tzinfo=dt.timezone.utc)
            ),
            universe=tuple(symbols),
            seed=7,
            contract_version="0.1.0",
            problems=[] if conforming else ["length"],
        )
    return SignalExecution(
        snapshot_name=snapshot_name,
        code_hash="ab" * 32,
        seed=7,
        vectors=vectors,
    )


def _closes(
    by_symbol: dict[str, list[float]], days: tuple[dt.date, ...]
) -> dict[str, dict[dt.date, float]]:
    """A fetched closes mapping — one close per symbol per grid day."""
    return {
        symbol: dict(zip(days, prices)) for symbol, prices in by_symbol.items()
    }


# The main scenario: a 12-bar grid, three rebalance dates at its head, AAA
# compounding 1% per bar (so the h-bar forward return is 1.01**h - 1 wherever
# both bars exist) and BBB flat at 50 (so its forward return is 0).  With 12
# bars: horizons 1, 2 and 5 cover all three dates, horizon 10 covers the
# first two (the third is 10 bars from the end's edge), horizon 20 covers
# none — the empty-but-carried case.
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = _closes(
    {"AAA": [100.0 * 1.01**i for i in range(12)], "BBB": [50.0] * 12}, _GRID
)


# -- one series per horizon ----------------------------------------------------


def test_one_target_series_per_horizon() -> None:
    # The feature's own clause: the result carries one target series per
    # horizon, and the horizons are the five the spec names — a closed set,
    # not a parameter.  A horizon with no computable target (20, over a
    # 12-bar grid) is carried as an empty series, not dropped: a consumer
    # iterating the five horizons of a decay profile must find five.
    targets = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    assert isinstance(targets, AlignedTargets)
    assert targets.horizons == HORIZONS == (1, 2, 5, 10, 20)
    assert tuple(sorted(targets.series)) == HORIZONS
    for horizon in HORIZONS:
        series = targets.targets(horizon)
        assert isinstance(series, TargetSeries)
        assert series.horizon == horizon


def test_the_series_name_their_sealed_world() -> None:
    # The closes arrive as a value with no provenance of their own, so the
    # alignment stamps the execution's snapshot on every series: a target
    # series that travels alone (to the null gate, into a decay profile)
    # must still say which sealed world its labels came from.
    targets = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    assert targets.snapshot_name == "snap_abc123"
    for series in targets.series.values():
        assert series.snapshot_name == "snap_abc123"


# -- the arithmetic ------------------------------------------------------------


def test_the_target_is_the_simple_forward_return() -> None:
    # close[d+h] / close[d] - 1, per symbol: AAA compounds 1% per bar, so
    # its 1-bar forward return is 1% and its 2-bar one is 1.01**2 - 1; BBB
    # is flat, so its forward return is exactly zero at every horizon.
    targets = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    for horizon in (1, 2, 5, 10):
        row = targets.targets(horizon).at(_REBALANCE[0])
        assert row["AAA"] == pytest.approx(1.01**horizon - 1.0)
        assert row["BBB"] == pytest.approx(0.0)


def test_the_targets_are_keyed_by_symbol_per_date() -> None:
    # One row per rebalance date, keyed by the symbols that were scored —
    # the cross-section the label belongs to.  The row at a date the series
    # does not cover is empty, the miss reported as nothing.
    targets = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    row = targets.targets(1).at(_REBALANCE[1])
    assert set(row) == {"AAA", "BBB"}
    assert targets.targets(20).at(_REBALANCE[0]) == {}


def test_non_conforming_dates_still_align() -> None:
    # The alignment is over the grid, not over conformingness: a date whose
    # vector failed the contract (scores=None, problems populated) has the
    # same h-period future as any other, and the metrics decide what a
    # non-conforming date means — not this step.
    execution = _execution(_REBALANCE, conforming=False)
    targets = align_targets(execution, _MAIN_CLOSES)
    assert targets.targets(1).dates() == _REBALANCE


# -- a period is a bar, not a calendar day -------------------------------------


def test_horizons_step_on_bars_not_calendar_days() -> None:
    # A "period" is one bar on the market grid.  From Friday 2026-09-11 the
    # 1-period forward return lands on Monday 2026-09-14 — the next *bar*,
    # two calendar days later — because the market's clock is its candles;
    # stepping calendar days would land on a Saturday no candle names.
    grid = (
        dt.date(2026, 9, 7),   # Monday
        dt.date(2026, 9, 8),
        dt.date(2026, 9, 9),
        dt.date(2026, 9, 10),
        dt.date(2026, 9, 11),  # Friday
        dt.date(2026, 9, 14),  # Monday — the next bar after Friday
        dt.date(2026, 9, 15),
    )
    friday = grid[4]
    execution = _execution((friday,), universe=("AAA",))
    closes = _closes({"AAA": [100.0, 100.0, 100.0, 100.0, 100.0, 110.0, 121.0]}, grid)
    targets = align_targets(execution, closes)
    # h=1 exits on Monday's close (110), h=2 on Tuesday's (121) — the
    # weekend simply does not exist as grid positions.
    assert targets.targets(1).at(friday)["AAA"] == pytest.approx(0.10)
    assert targets.targets(2).at(friday)["AAA"] == pytest.approx(0.21)


# -- absence, never zeros ------------------------------------------------------


def test_coverage_shrinks_as_the_horizon_grows() -> None:
    # The last ``horizon`` grid dates have no h-period future, so a longer
    # horizon covers fewer rebalance dates — honestly, by absence: horizon
    # 10 over the 12-bar grid covers the first two rebalance dates only,
    # and horizon 20 covers none.
    targets = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    assert targets.targets(1).dates() == _REBALANCE
    assert targets.targets(5).dates() == _REBALANCE
    assert targets.targets(10).dates() == _REBALANCE[:2]
    assert targets.targets(20).dates() == ()
    # And the grid itself still names every date that was scored: the
    # record states what was scored, the series state what each horizon
    # can measure.
    assert targets.rebalance_dates == _REBALANCE


def test_a_symbol_missing_its_exit_bar_is_absent() -> None:
    # A symbol with no bar on the exit date (a gap, or delisted inside the
    # horizon) is missing from that date's row — not zero-filled, not NaN.
    # A zero would read to every downstream metric as "the signal predicted
    # a flat return"; absence says the label does not exist.
    closes = _closes(
        {"AAA": [100.0 * 1.01**i for i in range(12)], "BBB": [50.0] * 12}, _GRID
    )
    # BBB's bar is missing on 2026-09-04 — no rebalance date itself, but
    # the 1-period exit date for the third one (and the 1-period entry's
    # own future for nobody: entries all sit on rebalance dates).
    del closes["BBB"][_GRID[3]]
    targets = align_targets(_MAIN_EXECUTION, closes)
    third = targets.targets(1).at(_REBALANCE[2])
    assert "BBB" not in third  # its exit bar is the missing one
    assert "AAA" in third
    # BBB keeps every entry bar, so it is scored everywhere — only the
    # labels whose exit lands on the gap are absent.
    assert targets.targets(1).at(_REBALANCE[0])["BBB"] == pytest.approx(0.0)
    assert targets.targets(2).at(_REBALANCE[2])["BBB"] == pytest.approx(0.0)


def test_an_empty_universe_date_contributes_nothing() -> None:
    # A rebalance date whose cross-section is empty has no symbols to
    # compute a label for, so it appears in no series — presence in a
    # series means a target was computed.
    execution = _execution(
        _REBALANCE,
        per_date_universe={_REBALANCE[0]: ("AAA", "BBB"), _REBALANCE[1]: ("AAA", "BBB"), _REBALANCE[2]: ()},
    )
    targets = align_targets(execution, _MAIN_CLOSES)
    assert targets.targets(1).dates() == _REBALANCE[:2]
    assert _REBALANCE[2] in targets.rebalance_dates  # the grid keeps it


# -- aligned to the execution --------------------------------------------------


def test_the_entry_close_must_exist_on_the_rebalance_date() -> None:
    # Feature 72's universe rule admits a symbol on a day its sealed bars
    # carry a partition on that very date, so every scored symbol must have
    # that day's close.  A fetch without it is a broken read, refused by
    # name rather than narrowed around — the roster guaranteed the bar.
    execution = _execution((_START, _GRID[1]))
    closes = _closes(
        {"AAA": [100.0 * 1.01**i for i in range(12)], "BBB": [50.0] * 12}, _GRID
    )
    del closes["BBB"][_START]  # BBB scored at _START, but no bar fetched
    with pytest.raises(EvaluatorAlignmentError, match="roster"):
        align_targets(execution, closes)


def test_unscored_symbols_are_ignored() -> None:
    # The market grid is derived from the scored symbols' closes only, so
    # the same execution plus the same closes for those symbols produces
    # the same targets however broad the fetch was — a whole-market fetch
    # (with extra symbols, even ones bar-dating days no scored symbol
    # traded) and a scored-universe fetch align identically.  This is the
    # reproducibility the determinism contract asks for.
    broad = dict(_MAIN_CLOSES)
    broad["CCC"] = {
        _GRID[0]: 7.0,
        _GRID[1]: 7.5,
        # A bar on a day no scored symbol traded: it must not shift the
        # grid, or "5 periods" would silently mean a different span.
        dt.date(2026, 9, 20): 8.0,
    }
    narrow = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    wide = align_targets(_MAIN_EXECUTION, broad)
    assert wide == narrow
    assert hash(wide) == hash(narrow)


def test_integer_closes_are_normalized_to_float() -> None:
    # Cents are a legitimate fetch spelling: an integer close is accepted
    # and the targets are floats either way.
    closes = _closes({"AAA": [100, 110, 121] + [121.0] * 9}, _GRID)
    targets = align_targets(_execution(_REBALANCE, universe=("AAA",)), closes)
    assert targets.targets(1).at(_REBALANCE[0])["AAA"] == pytest.approx(0.10)


def test_iso_date_keys_are_accepted() -> None:
    # The same courtesy the window extends the decision time: an ISO date
    # string names the same bar a ``date`` does, and both spellings produce
    # the same alignment.
    string_keyed = {
        symbol: {day.isoformat(): price for day, price in series.items()}
        for symbol, series in _MAIN_CLOSES.items()
    }
    assert align_targets(_MAIN_EXECUTION, string_keyed) == align_targets(
        _MAIN_EXECUTION, _MAIN_CLOSES
    )


# -- the coverage refusal ------------------------------------------------------


def test_no_forward_coverage_is_refused() -> None:
    # The closes end at the (single) rebalance date: every date on the grid
    # is the last one, so no horizon has any computable target, and five
    # empty series would report "aligned" for an evaluation with nothing to
    # measure.  Refused, naming the condition, so the caller learns the
    # fetch dropped the forward half of the label.  (A fetch that ends
    # *between* rebalance dates is not this refusal: the earlier dates'
    # shorter-horizon targets are computable and honestly returned.)
    day = _REBALANCE[0]
    execution = _execution((day,))
    closes = {"AAA": {day: 100.0}, "BBB": {day: 50.0}}
    with pytest.raises(EvaluatorAlignmentError, match="no forward return"):
        align_targets(execution, closes)


def test_an_empty_execution_is_refused() -> None:
    # No rebalance dates means no grid to align on — the same refusal
    # execute_signal makes when there is nothing to score.
    with pytest.raises(EvaluatorAlignmentError, match="no rebalance dates"):
        align_targets(
            SignalExecution(snapshot_name="s", code_hash="ab" * 32, seed=7, vectors={}),
            _MAIN_CLOSES,
        )


def test_an_everywhere_empty_universe_is_refused() -> None:
    # Symbols are what a label belongs to; an execution that scored none at
    # any date has nothing to align for.
    execution = _execution(_REBALANCE, universe=())
    with pytest.raises(EvaluatorAlignmentError, match="empty universe"):
        align_targets(execution, _MAIN_CLOSES)


# -- the input contract --------------------------------------------------------


def test_a_non_execution_is_refused() -> None:
    # The grid and the per-date universe come from the execution's vectors;
    # anything else (here, a window resolution — the previous step's
    # record) cannot supply them.
    with pytest.raises(EvaluatorAlignmentError, match="SignalExecution"):
        align_targets(_MAIN_CLOSES, _MAIN_CLOSES)  # type: ignore[arg-type]


def test_malformed_closes_are_refused() -> None:
    # The mapping is the fetch's whole content, and every price handed in
    # is validated: a NaN anywhere is a broken read, not a symbol-scoped
    # inconvenience.
    with pytest.raises(EvaluatorAlignmentError, match="mapping of symbol"):
        align_targets(_MAIN_EXECUTION, [1.0, 2.0])  # type: ignore[arg-type]
    with pytest.raises(EvaluatorAlignmentError, match="non-empty strings"):
        align_targets(_MAIN_EXECUTION, {"": {}})  # type: ignore[dict-item]
    with pytest.raises(EvaluatorAlignmentError, match="map date to close"):
        align_targets(_MAIN_EXECUTION, {"AAA": [100.0]})  # type: ignore[arg-type]
    with pytest.raises(EvaluatorAlignmentError, match="not an ISO date"):
        align_targets(_MAIN_EXECUTION, {"AAA": {"Sept 1": 100.0}})  # type: ignore[dict-item]


def test_a_datetime_key_is_refused() -> None:
    # The alignment is day-granular: bars are daily candles and the
    # rebalance grid is dates.  A datetime names an instant, and truncating
    # it to its day silently would guess which candle the caller meant.
    with pytest.raises(EvaluatorAlignmentError, match="datetime"):
        align_targets(
            _MAIN_EXECUTION,
            {"AAA": {dt.datetime(2026, 9, 1, 12, 0): 100.0}},  # type: ignore[dict-item]
        )


def test_one_bar_one_close() -> None:
    # The same day under two spellings (a date and its ISO string) is one
    # bar named twice, and a bar has one close — refusing keeps the fetch
    # honest instead of letting dict order pick a winner.
    with pytest.raises(EvaluatorAlignmentError, match="twice"):
        align_targets(
            _MAIN_EXECUTION,
            {"AAA": {_START: 100.0, _START.isoformat(): 101.0}},  # type: ignore[dict-item]
        )


def test_non_positive_and_non_finite_prices_are_refused() -> None:
    # The forward return divides by the entry close: a zero divides by
    # zero, a negative flips the sign of every return measured off it, and
    # a NaN reaches the metrics dressed as a measurement.
    for bad in (0.0, -50.0, float("nan"), float("inf")):
        with pytest.raises(EvaluatorAlignmentError):
            align_targets(
                _MAIN_EXECUTION, {"AAA": {_START: bad}, "BBB": {_START: 50.0}}
            )


def test_a_bool_price_is_refused() -> None:
    # Python calls ``True`` an int; the alignment does not call it a price.
    with pytest.raises(EvaluatorAlignmentError, match="must be a number"):
        align_targets(_MAIN_EXECUTION, {"AAA": {_START: True}})  # type: ignore[dict-item]


# -- the records ---------------------------------------------------------------


def test_the_records_are_read_only() -> None:
    # The mappings are captured behind read-only proxies at construction:
    # a caller keeping the dict it passed cannot add a target to a live
    # series, and neither can a caller of the finished alignment.
    values = {_START: {"AAA": 0.1}}
    series = TargetSeries(horizon=1, snapshot_name="snap_abc123", values=values)
    values[_GRID[1]] = {"AAA": 0.2}  # mutate after construction
    assert series.at(_GRID[1]) == {}
    with pytest.raises(TypeError):
        series.values[_GRID[1]] = {"AAA": 0.2}  # type: ignore[index]
    targets = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    with pytest.raises(TypeError):
        targets.series[3] = series  # type: ignore[index]


def test_identical_alignments_are_interchangeable() -> None:
    # The records are values: two alignments of the same execution over the
    # same closes are equal and hash-equal, so they are interchangeable as
    # dict keys — a cache of alignments, a replay comparing a stored one
    # against a fresh one.
    a = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    b = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    assert a == b
    assert hash(a) == hash(b)
    assert hash(a.targets(5)) == hash(b.targets(5))


def test_an_unknown_horizon_is_refused() -> None:
    # The five horizons are the spec's, not a caller's to widen: asking for
    # horizon 3 is asking for a label the spec never defined, and the
    # closed set is named rather than a None to trip over later.
    targets = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)
    with pytest.raises(EvaluatorAlignmentError, match="1, 2, 5, 10, 20"):
        targets.targets(3)  # type: ignore[arg-type]


def test_a_hand_built_series_is_validated() -> None:
    # The invariants are on the record, so a producer that drifted — here,
    # in a later feature — fails loudly rather than carrying a lying
    # series: the horizon set is closed, prices are finite, and the
    # bundle's series agree on horizon and snapshot.
    with pytest.raises(EvaluatorAlignmentError, match="horizons the spec"):
        TargetSeries(horizon=3, snapshot_name="s", values={})
    with pytest.raises(EvaluatorAlignmentError, match="integer"):
        TargetSeries(horizon=True, snapshot_name="s", values={})  # type: ignore[arg-type]
    with pytest.raises(EvaluatorAlignmentError, match="not finite"):
        TargetSeries(
            horizon=1, snapshot_name="s", values={_START: {"AAA": float("nan")}}
        )
    series = TargetSeries(horizon=1, snapshot_name="s", values={})
    with pytest.raises(EvaluatorAlignmentError, match="one series per horizon"):
        AlignedTargets(
            snapshot_name="s",
            rebalance_dates=(_START,),
            series=MappingProxyType({1: series}),
        )
    with pytest.raises(EvaluatorAlignmentError, match="wrong horizon"):
        AlignedTargets(
            snapshot_name="s",
            rebalance_dates=(_START,),
            series=MappingProxyType({**{h: TargetSeries(horizon=h, snapshot_name="s", values={}) for h in HORIZONS if h != 1}, 1: TargetSeries(horizon=2, snapshot_name="s", values={})}),
        )
    with pytest.raises(EvaluatorAlignmentError, match="one alignment reads one"):
        AlignedTargets(
            snapshot_name="s",
            rebalance_dates=(_START,),
            series=MappingProxyType({h: TargetSeries(horizon=h, snapshot_name="other", values={}) for h in HORIZONS}),
        )
    with pytest.raises(EvaluatorAlignmentError, match="sorted and de-duplicated"):
        AlignedTargets(
            snapshot_name="s",
            rebalance_dates=(_GRID[1], _START),
            series=MappingProxyType({h: TargetSeries(horizon=h, snapshot_name="s", values={}) for h in HORIZONS}),
        )


def test_the_alignment_imports_nothing_beyond_the_stdlib() -> None:
    # The module is stdlib-only — no polars, no pyarrow, no lake, no
    # environment — so composing the application (and the replay path §1
    # forbids from reaching the evaluator) pays nothing for importing this
    # member.  The closes and the targets are keyed data, not frames.
    import evaluator._align as module

    assert "polars" not in vars(module)
    assert callable(module.align_targets)
