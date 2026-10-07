"""bug_spec_the-null-permutation-leaks-time.xml — the fix, proved statistically.

*"The null permutation shuffles each symbol's returns in time, so a null
target can be a return already inside the signal's own lookback, and planted
nulls score as discoveries."* The old mechanism (every caller composed
``block_indices`` over the dates *one symbol* carried a value on) could serve
date d a value the same symbol carried on an earlier date inside a signal's
own lookback window: a 20-day momentum score at d is a function of prices on
``[d-20, d]``, and a block landing one slot early could serve, as d's
"forward return", a number that lookback had already read. The null then
correlated with the signal not by chance but because the two numbers were,
some of the time, literally the same one read twice — on the real snapshot,
20-day momentum scored ``|t|>1.96`` against the null on 34% of seeds.

:func:`nulloracle.blockpermute.block_permute_cross_section` closes that
channel by shuffling *within* one date instead of across dates: every value
served for date d is drawn from date d's own cross-section, so no value from
any other date — inside the lookback or outside it — can ever reach d. This
suite is the bug report's own reproduction (steps 4-8), run against the fixed
mechanism, plus the invariants the fix's docstring states as its contract.

Two groups of tests:

* **the statistical claim** — a seeded synthetic trending panel (92 dates, 40
  symbols, 20-day blocks) over seeds 1-200, scored by three signals whose
  lookback is exactly the shape that used to leak (20-day momentum, 20-day
  volatility, 5-day reversal). A calibrated null's cross-sectional IC t-stat,
  aggregated over seeds, has a mean near zero and rejects at the 5% nominal
  rate; a leaking null does neither, which is the whole of what the bug
  measured and what this suite re-measures against the fix. One test also
  runs the bug's own reproduction — the old per-symbol time shuffle,
  reimplemented independently of production — to confirm it still fails
  exactly the way the bug reports, so a composition that reverted to it would
  be caught here rather than discovered on a live campaign;
* **the mechanism's own invariants** — every served value comes from the
  date it is served on and never equals the symbol's own real value, two
  calls with the same seed agree, the mapping a block draws is shared by
  every date in it with the same membership, a membership change inside a
  block draws its own mapping, and a date with fewer than two symbols passes
  through untouched.

Everything here is pure in-memory floats and dates, generated from fixed
seeds (a market seed distinct from the null's own permutation seed, and the
permutation seeds 1-200 themselves) — no network, no filesystem, no shared
mutable state across tests — so the numbers below are exact and reproducible
on every run and the suite is safe under pytest-xdist. The full 200-seed,
three-signal, two-mechanism sweep runs in a couple of seconds, well inside
the file's 20 second budget.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import statistics

from nulloracle.blockpermute import block_indices, block_permute_cross_section

# -- A seeded synthetic trending market --------------------------------------------

N_SYMBOLS = 40
N_PANEL_DATES = 92
BLOCK_DAYS = 20
MARKET_SEED = 20260101
FIRST_DAY = dt.date(2026, 1, 1)
SEEDS = tuple(range(1, 201))

SYMBOLS = tuple(f"SYM{i:02d}" for i in range(N_SYMBOLS))
DAYS = tuple(FIRST_DAY + dt.timedelta(days=d) for d in range(N_PANEL_DATES))


def _trending_prices() -> list[list[float]]:
    """40 symbols' daily closes, ``N_PANEL_DATES + 1`` points each.

    Deterministic from :data:`MARKET_SEED` — never the null's own
    ``perm_seed`` — so the market every seed below is scored against is one
    fixed world. Each symbol gets its own persistent drift plus daily
    Gaussian noise: a trending, autocorrelated path, the shape a real
    forward-return panel has and the shape a momentum or reversal signal is
    written against.
    """
    rng = random.Random(MARKET_SEED)
    paths: list[list[float]] = []
    for _ in range(N_SYMBOLS):
        drift = rng.uniform(-0.0005, 0.0020)
        path = [100.0]
        for _ in range(N_PANEL_DATES):
            path.append(path[-1] * (1 + drift + rng.gauss(0.0, 0.02)))
        paths.append(path)
    return paths


_PRICES = _trending_prices()

#: The forward 1-day return panel the bug's own reproduction asks for:
#: ``{date: {symbol: forward return}}`` over the market's whole window.
_PANEL: dict[dt.date, dict[str, float]] = {
    DAYS[d]: {SYMBOLS[i]: _PRICES[i][d + 1] / _PRICES[i][d] - 1.0 for i in range(N_SYMBOLS)}
    for d in range(N_PANEL_DATES)
}


def _momentum_scores() -> dict[int, list[float]]:
    """A 20-day momentum score per date — the signal whose own lookback is
    exactly the span a 20-day block can move a value across."""
    return {
        d: [_PRICES[i][d] / _PRICES[i][d - 20] - 1.0 for i in range(N_SYMBOLS)]
        for d in range(20, N_PANEL_DATES)
    }


def _volatility_scores() -> dict[int, list[float]]:
    """A 20-day trailing realised volatility score per date."""
    scores: dict[int, list[float]] = {}
    for d in range(20, N_PANEL_DATES):
        row = []
        for i in range(N_SYMBOLS):
            daily = [_PRICES[i][t] / _PRICES[i][t - 1] - 1.0 for t in range(d - 19, d + 1)]
            row.append(statistics.pstdev(daily))
        scores[d] = row
    return scores


def _reversal_scores() -> dict[int, list[float]]:
    """A 5-day reversal score per date (the negative of the 5-day return)."""
    return {
        d: [-(_PRICES[i][d] / _PRICES[i][d - 5] - 1.0) for i in range(N_SYMBOLS)]
        for d in range(5, N_PANEL_DATES)
    }


_MOMENTUM = _momentum_scores()
_VOLATILITY = _volatility_scores()
_REVERSAL = _reversal_scores()


# -- Plain-Python Spearman IC and a per-seed t-stat --------------------------------


def _ranks(values: list[float]) -> list[float]:
    """Average ranks (1-based), the standard tie handling Spearman uses."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = average
        i = j + 1
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    spread_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    spread_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    return numerator / (spread_x * spread_y) if spread_x and spread_y else 0.0


def _spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_ranks(xs), _ranks(ys))


def _t_stat(values: list[float]) -> float:
    """The time-series t-stat of a cross-sectional IC: mean over standard error."""
    n = len(values)
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    return mean / (sd / math.sqrt(n)) if sd else 0.0


def _signal_t_stat(scores: dict[int, list[float]], permuted: dict) -> float:
    """One permutation's t-stat for one signal: the IC time series, reduced to one number."""
    ics = [
        _spearman(row, [permuted[DAYS[d]][SYMBOLS[i]] for i in range(N_SYMBOLS)])
        for d, row in scores.items()
    ]
    return _t_stat(ics)


def _null_t_values(scores: dict[int, list[float]]) -> list[float]:
    return [
        _signal_t_stat(
            scores, block_permute_cross_section(_PANEL, seed=seed, block_days=BLOCK_DAYS)
        )
        for seed in SEEDS
    ]


# -- The statistical claim: a calibrated null across three signals ----------------


class TestTheNullIsCalibratedAcrossSignals:
    def test_a_20_day_momentum_signal_is_calibrated(self) -> None:
        t_values = _null_t_values(_MOMENTUM)
        mean_t = statistics.mean(t_values)
        rejection_rate = sum(1 for t in t_values if abs(t) > 1.96) / len(t_values)
        assert abs(mean_t) <= 0.35
        assert rejection_rate <= 0.09

    def test_a_20_day_volatility_signal_is_calibrated(self) -> None:
        t_values = _null_t_values(_VOLATILITY)
        assert 0.7 <= statistics.stdev(t_values) <= 1.3

    def test_a_5_day_reversal_signal_is_calibrated(self) -> None:
        t_values = _null_t_values(_REVERSAL)
        mean_t = statistics.mean(t_values)
        rejection_rate = sum(1 for t in t_values if abs(t) > 1.96) / len(t_values)
        assert abs(mean_t) <= 0.35
        assert rejection_rate <= 0.09


def _old_per_symbol_time_shuffle(
    panel: dict[dt.date, dict[str, float]], *, seed: int, block_days: int
) -> dict[dt.date, dict[str, float]]:
    """The mechanism this bug replaces, reimplemented independently of production.

    Not imported from ``blockpermute.py`` — the fix removed this composition
    (block-shuffling the dates *one symbol* is present on) from the module
    entirely, so reproducing the bug means rebuilding it here, from the
    still-public and still-correct :func:`block_indices`. Kept only so the
    test below can show it still fails calibration — a guard against the
    fix's composition ever reverting to it.
    """
    days = list(panel)
    positions_by_symbol: dict[str, list[int]] = {}
    for position, day in enumerate(days):
        for symbol in panel[day]:
            positions_by_symbol.setdefault(symbol, []).append(position)
    permuted: dict[dt.date, dict[str, float]] = {day: {} for day in days}
    for symbol, positions in positions_by_symbol.items():
        values = [panel[days[p]][symbol] for p in positions]
        order = block_indices(range(len(positions)), seed=seed, block_days=block_days)
        for slot, source in enumerate(order):
            permuted[days[positions[slot]]][symbol] = values[source]
    return permuted


class TestTheBugsOwnReproductionStillFails:
    """Steps 4-8 of the bug report, run against the mechanism they describe.

    Not a claim about :func:`block_permute_cross_section` — the opposite: a
    live demonstration that the failure the bug reports is real on this same
    market and these same seeds, so the number the fix's own test above must
    clear is not an arbitrary bound.
    """

    def test_the_old_mechanism_fails_momentum_calibration(self) -> None:
        t_values = [
            _signal_t_stat(
                _MOMENTUM,
                _old_per_symbol_time_shuffle(_PANEL, seed=seed, block_days=BLOCK_DAYS),
            )
            for seed in SEEDS
        ]
        rejection_rate = sum(1 for t in t_values if abs(t) > 1.96) / len(t_values)
        # The bug report measures 34% on the real snapshot; this market's own
        # number need not match exactly; it needs only to be far above the 9%
        # ceiling a calibrated null must clear, which the fix's own test
        # above holds this exact market and these exact seeds to.
        assert rejection_rate > 0.3


# -- The mechanism's own invariants -------------------------------------------------


def _unique_value_panel(n_dates: int = 60, n_symbols: int = 5) -> dict[dt.date, dict[str, float]]:
    """A panel where every ``(date, symbol)`` value is unique panel-wide.

    1000x the symbol index dominates a small per-date offset, so no two
    symbols ever share a value on one date. That is what makes "no symbol
    keeps its own value" and "every value comes from that date" testable
    from outside at all: a panel where two symbols coincide on one date (an
    always-present dense fixture built from a simple formula, say) could
    satisfy either claim by accident.
    """
    days = tuple(FIRST_DAY + dt.timedelta(days=d) for d in range(n_dates))
    symbols = tuple(f"U{i}" for i in range(n_symbols))
    return {
        day: {symbol: 1000.0 * i + 0.001 * d for i, symbol in enumerate(symbols)}
        for d, day in enumerate(days)
    }


class TestEveryValueComesFromItsOwnDateAndNeverFromItself:
    def test_every_permuted_value_is_one_of_that_dates_own_values(self) -> None:
        panel = _unique_value_panel()
        permuted = block_permute_cross_section(panel, seed=99, block_days=20)
        for day, row in panel.items():
            assert set(permuted[day].values()) == set(row.values())

    def test_no_symbol_keeps_its_own_value(self) -> None:
        panel = _unique_value_panel()
        permuted = block_permute_cross_section(panel, seed=99, block_days=20)
        for day, row in panel.items():
            for symbol, value in row.items():
                assert permuted[day][symbol] != value


class TestDeterminismUnderTheSeed:
    def test_the_same_seed_reproduces_the_same_panel(self) -> None:
        panel = _unique_value_panel()
        once = block_permute_cross_section(panel, seed=7, block_days=20)
        twice = block_permute_cross_section(panel, seed=7, block_days=20)
        assert once == twice

    def test_two_seeds_shuffle_differently(self) -> None:
        panel = _unique_value_panel()
        outcomes = {
            tuple(sorted((day, tuple(sorted(row.items()))) for day, row in block_permute_cross_section(
                panel, seed=seed, block_days=20
            ).items()))
            for seed in range(1, 11)
        }
        assert len(outcomes) > 1


def _identity_encoded_panel(
    days: tuple[dt.date, ...], symbols: tuple[str, ...]
) -> dict[dt.date, dict[str, float]]:
    """Every date carries the same row: symbol ``i`` holds the value ``i``.

    A value is therefore the *index of the symbol it came from*, regardless
    of date — exactly what lets a test recover, from the served values
    alone, which symbol-to-symbol correspondence a block actually drew.
    """
    return {day: {symbol: float(i) for i, symbol in enumerate(symbols)} for day in days}


class TestTheMappingIsConstantWithinAConstantMembershipBlock:
    def test_every_date_in_one_block_shares_the_same_mapping(self) -> None:
        symbols = tuple(f"SYM{i}" for i in range(6))
        days = tuple(FIRST_DAY + dt.timedelta(days=d) for d in range(20))
        panel = _identity_encoded_panel(days, symbols)
        permuted = block_permute_cross_section(panel, seed=13, block_days=20)
        signatures = {tuple(int(permuted[day][s]) for s in symbols) for day in days}
        assert len(signatures) == 1

    def test_two_separate_blocks_are_each_internally_constant(self) -> None:
        symbols = tuple(f"SYM{i}" for i in range(6))
        days = tuple(FIRST_DAY + dt.timedelta(days=d) for d in range(40))
        panel = _identity_encoded_panel(days, symbols)
        permuted = block_permute_cross_section(panel, seed=13, block_days=20)

        def _signature(day: dt.date) -> tuple[int, ...]:
            return tuple(int(permuted[day][s]) for s in symbols)

        assert len({_signature(day) for day in days[:20]}) == 1
        assert len({_signature(day) for day in days[20:]}) == 1


class TestMembershipChangesInsideABlockDrawTheirOwnMapping:
    def test_a_mid_block_listing_and_delisting_each_get_their_own_mapping(self) -> None:
        base = ("AAA", "BBB", "CCC")
        days = tuple(FIRST_DAY + dt.timedelta(days=d) for d in range(20))
        panel: dict[dt.date, dict[str, float]] = {}
        for position, day in enumerate(days):
            row = {symbol: float(i) for i, symbol in enumerate(base)}
            if position < 10:
                row["ZRO"] = float(len(base))  # delists after position 9
            else:
                row["LATE"] = float(len(base))  # lists from position 10
            panel[day] = row
        permuted = block_permute_cross_section(panel, seed=21, block_days=20)

        # Membership is exact on every date, listing and delisting alike.
        for day in days:
            assert set(permuted[day]) == set(panel[day])

        def _signature(day: dt.date) -> tuple[int, ...]:
            row = panel[day]
            symbols = sorted(row)
            return tuple(int(permuted[day][s]) for s in symbols)

        # Each side of the membership change is one constant mapping, drawn
        # for its own cross-section rather than inherited from the other.
        assert len({_signature(day) for day in days[:10]}) == 1
        assert len({_signature(day) for day in days[10:]}) == 1


class TestAOneSymbolDatePassesThroughUnchanged:
    def test_a_single_symbol_date_is_identical_to_the_input(self) -> None:
        days = tuple(FIRST_DAY + dt.timedelta(days=d) for d in range(5))
        panel = {day: {"ONLY": float(i)} for i, day in enumerate(days)}
        permuted = block_permute_cross_section(panel, seed=3, block_days=20)
        assert permuted == panel
