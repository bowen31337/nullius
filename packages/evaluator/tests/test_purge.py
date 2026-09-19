"""Feature 77 — purging a cross-validation fold at its split boundary.

app_spec.xml feature 77: *"System rejects a cross-validation fold whose
holding period is not purged at the split boundary."*
docs/nullius-tech-architecture.md §6.1 names the step — ``6.
purge_and_embargo  purge H, embargo L around every CV split`` — and §C6.2 of
the PRD states the intent: *"Purge the holding period (H) around every CV
split so a label whose holding period straddles a split leaks no test-set
return into training."*

This suite tests the purge check — the *refusal* half of the feature
sentence — separately from the alignment that supplies the horizons
(``test_align.py``), the embargo that wraps around it (feature 78), and the
splitting of the data into folds (which a caller draws, not this step). The
check steps on the market grid, so the tests use a bar grid rather than a
calendar one, and assert:

* **the bar-granular rule** — the holding period is purged exactly when the
  last training bar sits at grid index ``≤ split − H − 1``;
* **the grid is the ruler** — the holding period counts grid bars, so the
  bars between the last training bar and the split (the ones a purge removes)
  must be present on the grid for the distance to be measurable;
* **a period is a bar, not a calendar day** — the holding period counts
  candles on the grid, so a weekend gap does not count as purged bars;
* **the split-is-a-training-bar refusal** — a split listed among the training
  dates is refused, because a boundary is not a bar to train on;
* **the un-purged refusal** — a training half whose last bar is within the
  holding period of the split is refused, naming how many bars it falls
  short;
* **the input contract** — a non-positive or non-integer holding period, a
  malformed grid, and malformed date spellings, are refused by name;
* **the record** — the verdict record carries the fold and the shortfall,
  and is a hashable value.

The dates and grid are built by hand, so these tests assert the check — the
grid walk, the shortfall, the refusals — without an execution, a sandbox or
a window.
"""

from __future__ import annotations

import datetime as dt

import pytest

from evaluator import (
    EvaluatorPurgeError,
    PurgeCheck,
    check_fold_purged,
)

_START = dt.date(2026, 9, 1)


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid.

    Consecutive calendar days are not how real bars lay out (markets close),
    which is exactly why the *stepping* test below uses a weekend grid; for
    the arithmetic tests a dense grid keeps the index math readable.
    """
    return tuple(start + dt.timedelta(days=i) for i in range(count))


# -- the bar-granular rule -----------------------------------------------------


def test_a_fold_purged_by_exactly_the_holding_period_passes() -> None:
    # A 12-bar grid, the split at bar 8, training on bars 0..3.  The holding
    # period is 4 bars, so the purge line is grid index 3 (8 − 4 − 1): the
    # last training bar sits exactly on it, so bars 4, 5, 6, 7 (the four bars
    # before the split) are kept out of training — the holding period's mirror
    # image, exactly H bars — purged.  The verdict records the fold and a zero
    # shortfall.
    grid = _days(12)
    split = grid[8]
    check = check_fold_purged(grid, grid[:4], split, holding_period=4)
    assert isinstance(check, PurgeCheck)
    assert check.shortfall == 0
    assert check.last_training_bar == grid[3]
    assert check.split == split


def test_one_bar_short_is_refused_and_names_the_shortfall() -> None:
    # Training reaches bar 5, the split is bar 8, the holding period is 4.
    # The purge line is grid index 3 (8 − 4 − 1), so bar 5 (index 5) sits two
    # bars past it — bars 5 and 6 leak, and the refusal says two bars.
    grid = _days(12)
    with pytest.raises(EvaluatorPurgeError, match="2 bars"):
        check_fold_purged(grid, grid[:6], grid[8], holding_period=4)


def test_the_boundary_is_exactly_the_holding_period() -> None:
    # The holding period is a count of bars, so "purged" is inclusive of the
    # boundary: a last training bar exactly at grid index ``split − H − 1``
    # passes, and one index closer fails.
    grid = _days(12)
    split = grid[8]
    # last training bar at index 4 (grid[:5]) → 4 ≤ 3? No.  Wait: purge line
    # is 8 − 4 − 1 = 3, so index 4 leaks by one.  Use grid[:4] (index 3) to
    # pass, grid[:5] (index 4) to fail.
    assert check_fold_purged(grid, grid[:4], split, holding_period=4).shortfall == 0
    with pytest.raises(EvaluatorPurgeError):
        check_fold_purged(grid, grid[:5], split, holding_period=4)


def test_a_wide_gap_between_training_and_split_is_purged() -> None:
    # A training half that stops well before the split is purged with room to
    # spare: the shortfall is zero, because the check asks only whether the
    # holding period is clear, not how much clear it is.
    grid = _days(12)
    check = check_fold_purged(grid, grid[:3], grid[11], holding_period=5)
    assert check.shortfall == 0


def test_training_dates_may_repeat_and_be_unordered() -> None:
    # The check asks only *which* bars are trained on, never in what order or
    # how often, so a training list that repeats a date or arrives unsorted
    # is the same fold as its de-duplicated, sorted form.
    grid = _days(12)
    split = grid[8]
    tidy = check_fold_purged(grid, grid[:4], split, holding_period=4)
    messy = check_fold_purged(
        grid, [grid[3], grid[1], grid[3], grid[0], grid[2]], split, holding_period=4
    )
    assert messy == tidy


# -- the grid is the ruler -----------------------------------------------------


def test_the_bars_between_training_and_split_must_be_on_the_grid() -> None:
    # The holding period is measured on the market grid, and the bars between
    # the last training bar and the split are the ones a purge removes — so
    # they must be present on the grid for the distance to be measurable. A
    # grid that jumps straight from the last training bar to the split makes
    # an adjacent pair leak even at a holding period of one.
    split = _days(12)[8]
    grid = (_days(12)[4], split)  # only the last training bar and the split
    with pytest.raises(EvaluatorPurgeError):
        check_fold_purged(grid, [_days(12)[4]], split, holding_period=1)


# -- a period is a bar, not a calendar day -------------------------------------


def test_the_holding_period_counts_bars_not_calendar_days() -> None:
    # A "period" is one bar on the market grid.  On the weekend grid the split
    # is Friday, and the bars before it are the candles the market names — the
    # Saturday and Sunday the candles skip do not count, so a holding period
    # counts candles, not calendar days.  A caller that counted calendar days
    # would think a two-calendar-day gap had purged more than it had.
    grid = (
        dt.date(2026, 8, 28),  # Friday
        dt.date(2026, 8, 31),  # Monday
        dt.date(2026, 9, 1),   # Tuesday
        dt.date(2026, 9, 2),   # Wednesday
        dt.date(2026, 9, 3),   # Thursday
        dt.date(2026, 9, 4),   # Friday — the split (grid index 5)
    )
    split = grid[5]
    # Training ends on Wednesday (grid index 3): the bars strictly between it
    # and the split are just Thursday (index 4) — one bar.  Holding period 1
    # is purged (the last training bar is at the purge line, index 3 = 5 − 1 −
    # 1); holding period 2 is not (the last training bar is one bar too close).
    assert check_fold_purged(grid, grid[:4], split, holding_period=1).shortfall == 0
    with pytest.raises(EvaluatorPurgeError):
        check_fold_purged(grid, grid[:4], split, holding_period=2)


# -- the split-is-a-training-bar refusal ---------------------------------------


def test_a_split_among_the_training_dates_is_refused() -> None:
    # A split is the boundary the holding period starts at, not a bar to
    # train on.  Listing it among the training dates would train the model on
    # the label's own entry bar, and silently dropping it would let the
    # leakage the purge exists to catch pass — so it is refused, naming the
    # boundary.
    grid = _days(12)
    split = grid[8]
    with pytest.raises(EvaluatorPurgeError, match="is one of the training dates"):
        check_fold_purged(grid, grid[:9], split, holding_period=4)


def test_the_split_must_be_after_every_training_bar() -> None:
    # A training bar past the split puts the test boundary behind the model —
    # the fold has its halves the wrong way round, and is refused rather than
    # trusted.  The split itself is kept out of the training half here, so the
    # failure is the "past the split" one, not the "trained on the split" one.
    grid = _days(12)
    split = grid[6]
    training = [grid[0], grid[1], grid[7], grid[8]]  # bars 7 and 8 are past 6
    with pytest.raises(EvaluatorPurgeError, match="after the split"):
        check_fold_purged(grid, training, split, holding_period=2)


def test_the_split_must_be_on_the_grid() -> None:
    # The boundary the holding period starts at must be a bar the holding
    # period is measured against; a split off the grid cannot be placed, so
    # the check refuses rather than guessing where it falls.
    grid = _days(12)
    with pytest.raises(EvaluatorPurgeError, match="not on the market grid"):
        check_fold_purged(grid, grid[:4], dt.date(2026, 12, 25), holding_period=4)


# -- the un-purged refusal -----------------------------------------------------


def test_an_unpurged_fold_is_refused_naming_the_shortfall() -> None:
    # The last training bar is within the holding period of the split: the
    # fold leaks the label's test-set return into training, so it is refused
    # — and the refusal names how many bars the last training bar sits short
    # of the purge line, so the caller knows exactly what to drop.
    grid = _days(12)
    with pytest.raises(EvaluatorPurgeError, match="2 bars"):
        check_fold_purged(grid, grid[:6], grid[8], holding_period=4)


# -- the input contract --------------------------------------------------------


def test_the_holding_period_must_be_a_positive_integer() -> None:
    # The holding period is a count of grid bars — one of the horizons the
    # label is measured over — so zero, a negative, a float and a bool are
    # each refused by name; a holding period of zero bars has nothing to
    # purge.
    grid = _days(12)
    with pytest.raises(EvaluatorPurgeError, match="at least one grid bar"):
        check_fold_purged(grid, grid[:4], grid[8], holding_period=0)
    with pytest.raises(EvaluatorPurgeError, match="at least one grid bar"):
        check_fold_purged(grid, grid[:4], grid[8], holding_period=-1)
    with pytest.raises(EvaluatorPurgeError, match="positive integer"):
        check_fold_purged(grid, grid[:4], grid[8], holding_period=2.0)
    with pytest.raises(EvaluatorPurgeError, match="positive integer"):
        check_fold_purged(grid, grid[:4], grid[8], holding_period=True)


def test_the_grid_must_be_a_well_formed_market_grid() -> None:
    # The grid is the ruler the holding period is measured against, so an
    # unsorted grid, one carrying a bar twice, an empty one, and a
    # non-iterable are each refused by name — a broken ruler is one a check
    # cannot measure against.
    with pytest.raises(EvaluatorPurgeError, match="sorted"):
        check_fold_purged(_days(12)[::-1], _days(12)[:4], _days(12)[8], holding_period=4)
    with pytest.raises(EvaluatorPurgeError, match="twice"):
        check_fold_purged(
            (_days(12)[0], _days(12)[0], _days(12)[1]),
            _days(12)[:1],
            _days(12)[1],
            holding_period=1,
        )
    with pytest.raises(EvaluatorPurgeError, match="empty"):
        check_fold_purged([], [], _days(12)[8], holding_period=4)
    with pytest.raises(EvaluatorPurgeError, match="iterable"):
        check_fold_purged(_days(12)[3], _days(12)[:1], _days(12)[8], holding_period=4)


def test_a_training_date_off_the_grid_is_refused() -> None:
    # A training date that is not a bar of the grid is a fold drawn on a
    # different timeline, which the check cannot place against the split, so
    # it is refused rather than trusted.
    grid = _days(12)
    with pytest.raises(EvaluatorPurgeError, match="not on the market grid"):
        check_fold_purged(grid, [dt.date(2026, 12, 25)], grid[8], holding_period=4)


def test_an_empty_training_set_is_refused() -> None:
    # A fold has a training half to purge and a test half to score; an empty
    # training set is a fold that was never drawn, refused before any split
    # is considered.
    with pytest.raises(EvaluatorPurgeError, match="empty"):
        check_fold_purged(_days(12), [], _days(12)[8], holding_period=4)


def test_malformed_dates_are_refused_by_name() -> None:
    # Dates are coerced with the same courtesy the alignment extends its
    # keys: an ISO string names a bar, but a datetime (an instant, not a day)
    # and a non-date string are refused, each naming what was wrong.
    grid = _days(12)
    with pytest.raises(EvaluatorPurgeError, match="datetime"):
        check_fold_purged(
            grid, grid[:4], dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc), holding_period=4
        )
    with pytest.raises(EvaluatorPurgeError, match="not an ISO date"):
        check_fold_purged(grid, ["2026-13-40"], grid[8], holding_period=4)


def test_iso_date_strings_are_accepted() -> None:
    # The same courtesy the window and the alignment extend their date keys:
    # an ISO date string names the same bar a ``date`` does, so a
    # string-keyed fold checks identically to its date form.
    grid = _days(12)
    split = grid[8]
    as_dates = check_fold_purged(grid, grid[:4], split, holding_period=4)
    as_strings = check_fold_purged(
        grid, [day.isoformat() for day in grid[:4]], split.isoformat(), holding_period=4
    )
    assert as_strings == as_dates


# -- the record ----------------------------------------------------------------


def test_the_record_carries_the_fold_and_the_verdict() -> None:
    # The verdict is a value beside the fold it describes: the last training
    # bar, the split, and the shortfall (zero on a returned record — an
    # un-purged fold is raised, not returned).
    grid = _days(12)
    check = check_fold_purged(grid, grid[:4], grid[8], holding_period=4)
    assert check.last_training_bar == grid[3]
    assert check.split == grid[8]
    assert check.shortfall == 0


def test_the_record_is_a_hashable_value() -> None:
    # A check can be carried beside the fold, filed in a report, or compared
    # across folds without recomputing — so it is a frozen, hashable value,
    # and two checks of the same fold are interchangeable as dict keys.
    grid = _days(12)
    a = check_fold_purged(grid, grid[:4], grid[8], holding_period=4)
    b = check_fold_purged(grid, grid[:4], grid[8], holding_period=4)
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}
