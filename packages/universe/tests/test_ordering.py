"""Acceptance tests for the stable symbol ordering (feature 46).

Feature 46: "System returns a stable symbol ordering from every universe
resolution, so downstream reductions stay bit-reproducible"
(app_spec.xml). Architecture §12 puts the requirement this serves into
the determinism contract — *stable iteration order: ``PYTHONHASHSEED=0``;
explicit sorts before every reduction* — because floating-point addition
is not associative: two runs handed the same symbols in different orders
produce answers that differ in the last bits, and the canary would flag a
determinism break nobody caused.

Three things are under test. First the *rule itself*:
:func:`universe.ordering.canonical_symbol_order` turns any iterable of
symbols into the same tuple — distinct, ascending by code point —
whatever order it arrived in. Second the *coverage*: every path in this
package that answers "which symbols" — the pure resolution (feature 42),
the service facade over the persisted table, the retained-history window
query (feature 43), the all-symbols read, the gate's known-delistings
knowledge, the audit's delisted listing — returns that one order. Third
the *reproducibility claim itself*: the same universe resolved in
subprocesses under different ``PYTHONHASHSEED`` values answers byte for
byte identically, which is only interesting because the intermediate set
order really does move between those processes — the control test pins
that too, so the equality test can never silently become vacuous.
"""

import datetime as dt
import itertools
import os
import subprocess
import sys
from pathlib import Path

import pytest

from universe import (
    DailyBar,
    PriceBar,
    UniverseConfig,
    UniverseService,
    assert_stable_symbol_order,
    build_monthly_universe,
    canonical_symbol_order,
    is_stable_symbol_order,
    known_delistings,
    membership_intervals,
    resolve_membership,
    UnstableSymbolOrder,
)

# The import roots a subprocess needs to import ``universe`` the way the
# suite's conftest arranges for in-process tests (the package's __init__
# imports ``app.module_loader``, so both roots are required).
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "universe" / "src"

TOP_TEN = UniverseConfig(top_n=10)


# ---------------------------------------------------------------------------
# The roster-shift scenario, in mixed case on purpose
# ---------------------------------------------------------------------------


def daily(symbol: str, start: dt.date, end: dt.date, volume: float) -> list[DailyBar]:
    return [
        DailyBar(symbol, start + dt.timedelta(days=offset), volume)
        for offset in range((end - start).days + 1)
    ]


def window(month: str) -> tuple[dt.date, dt.date]:
    """The trailing 30-day window a build effective in ``month`` reads."""
    year, number = (int(part) for part in month.split("-"))
    first = dt.date(year, number, 1)
    return first - dt.timedelta(days=30), first - dt.timedelta(days=1)


def trades(month: str, volumes: dict[str, float]) -> list[DailyBar]:
    """Bars inside ``month``'s trailing window, one symbol per volume given."""
    start, end = window(month)
    return [
        bar
        for symbol, volume in volumes.items()
        for bar in daily(symbol, start, end, volume)
    ]


# April admits all four; from May on, aaaUSDT is gone — departed, but its
# history and its April answer remain. Mixed case and a digit-leading name
# are deliberate: the canonical order this file pins is by code point
# (digits before upper case before lower case), not a locale's collation.
APRIL = {
    "ZZZUSDT": 100.0,
    "aaaUSDT": 90.0,
    "AaveUsdt": 80.0,
    "1INCHUSDT": 70.0,
}
MAY = {symbol: volume for symbol, volume in APRIL.items() if symbol != "aaaUSDT"}

# All four names, in the one order every resolution must produce:
# '1' (0x31) < 'A' (0x41) < 'Z' (0x5A) < 'a' (0x61).
ALL_FOUR = ("1INCHUSDT", "AaveUsdt", "ZZZUSDT", "aaaUSDT")
SURVIVING_THREE = ("1INCHUSDT", "AaveUsdt", "ZZZUSDT")


def roster_shift_builds() -> list:
    """One build per month, oldest first, bars covering each trailing window."""
    bars = trades("2026-04", APRIL) + trades("2026-05", MAY)
    return [
        build_monthly_universe(bars, "2026-04", TOP_TEN),
        build_monthly_universe(bars, "2026-05", TOP_TEN),
    ]


def roster_shift_intervals():
    return membership_intervals(roster_shift_builds())


def mid_month(month: str) -> dt.date:
    return dt.date(int(month[:4]), int(month[5:]), 15)


def full_price_bars() -> list[PriceBar]:
    """Closes for every symbol across both trailing windows.

    The delisted name's April bars are included on purpose: leaving the
    universe is not leaving the exchange, and the retained history keeps
    accruing (feature 43's retention). Without them, May's window would
    hold no bar for the departed name and the tests below would inspect
    a pruned history — the very thing this package refuses to build on.
    """
    start, _ = window("2026-04")
    _, end = window("2026-05")
    return [
        PriceBar(symbol, start + dt.timedelta(days=offset), 10.0)
        for symbol in APRIL
        for offset in range((end - start).days + 1)
    ]


class TestTheCanonicalOrder:
    """The rule itself: distinct symbols, ascending by code point."""

    def test_it_sorts_what_it_is_given(self) -> None:
        assert canonical_symbol_order(["BTCUSDT", "ADAUSDT", "ETHUSDT"]) == (
            "ADAUSDT",
            "BTCUSDT",
            "ETHUSDT",
        )

    def test_a_symbol_appears_once_even_if_given_twice(self) -> None:
        assert canonical_symbol_order(
            ["BTCUSDT", "ADAUSDT", "BTCUSDT", "ADAUSDT"]
        ) == ("ADAUSDT", "BTCUSDT")

    def test_the_empty_input_is_the_empty_tuple(self) -> None:
        # A decision time before any membership resolves empty — and the
        # empty resolution is as canonical as any other: there is exactly
        # one ordering of nothing.
        assert canonical_symbol_order([]) == ()

    def test_any_iterable_spells_the_same_answer(self) -> None:
        names = list(APRIL)
        assert canonical_symbol_order(names) == canonical_symbol_order(tuple(names))
        assert canonical_symbol_order(names) == canonical_symbol_order(set(names))
        assert canonical_symbol_order(names) == canonical_symbol_order(
            reversed(names)
        )
        assert canonical_symbol_order(names) == canonical_symbol_order(
            (symbol for symbol in names)
        )

    def test_the_order_is_by_code_point_not_locale(self) -> None:
        # Not a case-folded or locale collation, either of which could
        # order these differently and both of which vary by environment:
        # digits before upper case before lower case, always.
        assert canonical_symbol_order(["bUSDT", "AUSDT", "1INCH", "aUSDT", "BUSDT"]) == (
            "1INCH",
            "AUSDT",
            "BUSDT",
            "aUSDT",
            "bUSDT",
        )

    def test_a_non_string_symbol_is_refused(self) -> None:
        with pytest.raises(TypeError, match="sequence of strings"):
            canonical_symbol_order(["ADAUSDT", 42])

    def test_a_blank_symbol_is_refused(self) -> None:
        with pytest.raises(ValueError, match="blank symbol"):
            canonical_symbol_order(["ADAUSDT", "   "])

    def test_it_is_idempotent(self) -> None:
        once = canonical_symbol_order(APRIL)
        assert canonical_symbol_order(once) == once

    def test_every_permutation_lands_in_the_same_order(self) -> None:
        # The load-bearing property, stated exhaustively at a size where
        # exhaustive is possible: no arrival order changes the answer.
        names = list(APRIL)
        for permutation in itertools.permutations(names):
            assert canonical_symbol_order(permutation) == ALL_FOUR


class TestThePredicate:
    """:func:`is_stable_symbol_order` — asking whether a sequence is the order."""

    def test_a_canonical_sequence_is_stable(self) -> None:
        assert is_stable_symbol_order(ALL_FOUR)

    def test_an_unsorted_sequence_is_not(self) -> None:
        assert not is_stable_symbol_order(("ADAUSDT", "1INCHUSDT"))

    def test_a_repeated_symbol_is_not(self) -> None:
        # Strictly increasing, not merely non-decreasing: a repeated index
        # misaligns every zip against it exactly as an unsorted one does.
        assert not is_stable_symbol_order(("ADAUSDT", "ADAUSDT", "BTCUSDT"))

    def test_a_blank_symbol_is_not(self) -> None:
        assert not is_stable_symbol_order(("ADAUSDT", " "))

    def test_a_non_string_member_is_not(self) -> None:
        assert not is_stable_symbol_order(("ADAUSDT", 42))

    def test_the_empty_sequence_is_stable(self) -> None:
        assert is_stable_symbol_order(())

    def test_the_predicate_never_raises(self) -> None:
        # Total on purpose: whatever it is handed, it answers True or
        # False. The loud refusal is the assert's job, not the ask's.
        for candidate in ((), ("A",), ("B", "A"), ("A", "A"), ("A", 0), (0, 1), ("",)):
            assert is_stable_symbol_order(candidate) in (True, False)

    def test_the_canonical_functions_output_always_satisfies_it(self) -> None:
        samples = [
            [],
            list(APRIL),
            list(APRIL)[::-1],
            list(APRIL) + list(APRIL),
            ["z", "a", "M", "9"],
        ]
        for sample in samples:
            assert is_stable_symbol_order(canonical_symbol_order(sample))


class TestTheRefusal:
    """:func:`assert_stable_symbol_order` — the downstream half of the contract."""

    def test_a_stable_ordering_passes_through_unchanged(self) -> None:
        # It judges, it never repairs: what leaves is what arrived, as a
        # tuple. Quietly sorting here would hide exactly the defect the
        # assert exists to catch.
        assert assert_stable_symbol_order(ALL_FOUR) == ALL_FOUR
        assert assert_stable_symbol_order(["ADAUSDT", "BTCUSDT"]) == (
            "ADAUSDT",
            "BTCUSDT",
        )

    def test_the_empty_ordering_passes(self) -> None:
        assert assert_stable_symbol_order(()) == ()

    def test_an_unsorted_ordering_is_refused_naming_the_origin_and_the_pair(
        self,
    ) -> None:
        with pytest.raises(UnstableSymbolOrder) as raised:
            assert_stable_symbol_order(("BTCUSDT", "ADAUSDT"), origin="a test window")
        message = str(raised.value)
        assert "a test window" in message
        assert "'BTCUSDT'" in message and "'ADAUSDT'" in message
        assert "not in the stable symbol ordering" in message
        assert "bit-reproducible" in message

    def test_a_repeated_symbol_is_refused(self) -> None:
        with pytest.raises(UnstableSymbolOrder, match="repeats the symbol"):
            assert_stable_symbol_order(("ADAUSDT", "ADAUSDT"))

    def test_a_blank_symbol_is_refused(self) -> None:
        with pytest.raises(UnstableSymbolOrder, match="blank symbol"):
            assert_stable_symbol_order(("ADAUSDT", ""))

    def test_a_non_string_member_is_a_type_error(self) -> None:
        # Misuse of the API, not instability of the data — the package's
        # standing distinction between a malformed value and a wrong one.
        with pytest.raises(TypeError, match="sequence of strings"):
            assert_stable_symbol_order(("ADAUSDT", None))

    def test_the_refusal_is_a_value_error(self) -> None:
        # Named, but catchable by the broadest existing handler: a caller
        # that guards its inputs with ValueError needs no new guard here.
        assert issubclass(UnstableSymbolOrder, ValueError)

    def test_a_blank_origin_is_refused(self) -> None:
        with pytest.raises(ValueError, match="origin"):
            assert_stable_symbol_order(ALL_FOUR, origin="  ")

    def test_it_accepts_what_the_canonical_function_produces(self) -> None:
        # The round-trip law: produce, then assert. Every resolution path
        # does the first; every consumer may do the second; the two must
        # never disagree.
        shuffled = ["zzzUSDT", "1INCHUSDT", "AaveUsdt", "aaaUSDT"]
        produced = canonical_symbol_order(shuffled)
        assert assert_stable_symbol_order(produced) == produced


class TestEveryResolutionReturnsIt:
    """Feature 46's "every": each path that answers "which symbols" answers in
    the one order — pure resolution, facade, window query, all-symbols read,
    known delistings, audit listing."""

    def test_the_pure_resolution_returns_the_canonical_order(self) -> None:
        assert resolve_membership(
            roster_shift_intervals(), mid_month("2026-04")
        ) == ALL_FOUR

    def test_the_resolution_is_canonical_however_the_rows_arrive(self) -> None:
        intervals = roster_shift_intervals()
        by_symbol = sorted(intervals, key=lambda row: row.symbol)
        for arrangement in (intervals, tuple(reversed(intervals)), by_symbol):
            assert resolve_membership(arrangement, mid_month("2026-04")) == ALL_FOUR
            assert resolve_membership(arrangement, mid_month("2026-05")) == SURVIVING_THREE

    def test_the_service_facade_returns_it(self, test_database_url: str) -> None:
        service = UniverseService(config=TOP_TEN, database_url=test_database_url)
        for universe in roster_shift_builds():
            service.persist(universe)
        assert service.resolve(mid_month("2026-04")) == ALL_FOUR
        assert service.resolve(mid_month("2026-05")) == SURVIVING_THREE
        assert is_stable_symbol_order(service.resolve(mid_month("2026-04")))

    def test_the_window_query_returns_it(self, test_database_url: str) -> None:
        # The retained-history window query — the other half of "every
        # universe resolution", and the one whose order comes out of SQL:
        # SQLite's BINARY collation and Python's code-point sort must
        # agree, and the mixed-case roster is what would catch it if they
        # did not.
        service = UniverseService(config=TOP_TEN, database_url=test_database_url)
        service.ingest_prices(full_price_bars())
        start, end = window("2026-05")
        assert service.price_history.symbols_in_window(start, end) == ALL_FOUR
        assert is_stable_symbol_order(
            service.price_history.symbols_in_window(start, end)
        )

    def test_all_symbols_returns_it(self, test_database_url: str) -> None:
        service = UniverseService(config=TOP_TEN, database_url=test_database_url)
        service.ingest_prices(
            PriceBar(bar.symbol, bar.date, 10.0) for bar in trades("2026-04", APRIL)
        )
        assert service.price_history.all_symbols() == ALL_FOUR

    def test_known_delistings_returns_it(self) -> None:
        intervals = roster_shift_intervals()
        start, end = window("2026-05")
        assert known_delistings(intervals, start, end) == ("aaaUSDT",)
        assert is_stable_symbol_order(known_delistings(intervals, start, end))

    def test_the_audit_lists_delisted_names_in_it(self, test_database_url: str) -> None:
        service = UniverseService(config=TOP_TEN, database_url=test_database_url)
        service.ingest_prices(full_price_bars())
        for universe in roster_shift_builds():
            service.persist(universe)
        audits = service.survivorship_audit()
        by_month = {audit.month: audit for audit in audits}
        assert by_month["2026-05"].delisted_present == ("aaaUSDT",)
        for audit in audits:
            assert is_stable_symbol_order(audit.delisted_present)

    def test_the_facade_refuses_a_resolution_that_drifted(
        self, test_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The facade asserts rather than assumes: if the pure resolution
        # ever stopped producing the canonical order, the service would
        # refuse to hand the drift downstream instead of quietly letting
        # every reduction over it become irreproducible.
        import universe.service as service_module

        def drifting(intervals, when):
            return tuple(reversed(resolve_membership(intervals, when)))

        service = UniverseService(config=TOP_TEN, database_url=test_database_url)
        for universe in roster_shift_builds():
            service.persist(universe)
        monkeypatch.setattr(service_module, "resolve_membership", drifting)
        with pytest.raises(UnstableSymbolOrder, match="UniverseService.resolve"):
            service.resolve(mid_month("2026-04"))


# ---------------------------------------------------------------------------
# Bit-reproducibility across hash seeds
# ---------------------------------------------------------------------------

MANY_SYMBOLS = (
    "1INCHUSDT", "AAVEUSDT", "ACHUSDT", "ADAUSDT", "ALGOUSDT", "ATOMUSDT",
    "AvaxUsdt", "BATUSDT", "BCHUSDT", "BNBUSDT", "btcUSDT", "CfxUsdt",
    "COMPUSDT", "CrvUsdt", "DASHUSDT", "DgbUsdt", "DOTUSDT", "EGLDUSDT",
    "EnjUsdt", "EOSUSDT", "ETCUSDT", "ETHUSDT", "FilUsdt", "FTMUSDT",
    "HbarUsdt", "IcpUsdt", "KavaUsdt", "KsmUsdt", "LtCUSDT", "MaticUsdt",
    "MkrUsdt", "NearUsdt", "OneUsdt", "RoseUsdt", "SolUsdt", "SushiUsdt",
    "TRXUSDT", "UniUsdt", "XLMUSDT", "ZECUSDT", "aaaUSDT", "MmMUsdt",
    "zIlUsdt", "QtUmUsdt",
)
DEPARTED = ("aaaUSDT", "MmMUsdt", "zIlUsdt", "QtUmUsdt")
MAY_ROSTER = tuple(sorted(set(MANY_SYMBOLS) - set(DEPARTED)))

# Runs in a fresh interpreter: derives the intervals from bars (pure
# functions, no store), prints the *raw set iteration order* of the
# covered symbols and then the canonical resolution. The first line moves
# with the process's hash seed; the second must not.
_CHILD_SCRIPT = """
import datetime as dt

from universe import (
    DailyBar,
    UniverseConfig,
    build_monthly_universe,
    membership_intervals,
    resolve_membership,
)

SYMBOLS = __SYMBOLS__
DEPARTED = __DEPARTED__
CONFIG = UniverseConfig(top_n=100)


def window(month):
    year, number = (int(part) for part in month.split("-"))
    first = dt.date(year, number, 1)
    return first - dt.timedelta(days=30), first - dt.timedelta(days=1)


def trades(month, roster):
    start, end = window(month)
    return [
        DailyBar(symbol, start + dt.timedelta(days=offset), 100.0)
        for symbol in roster
        for offset in range((end - start).days + 1)
    ]


april = build_monthly_universe(trades("2026-04", SYMBOLS), "2026-04", CONFIG)
remaining = [symbol for symbol in SYMBOLS if symbol not in DEPARTED]
may = build_monthly_universe(trades("2026-05", remaining), "2026-05", CONFIG)

# Deliberately not month order: the derivation sorts, the input need not.
intervals = membership_intervals((may, april))
when = dt.date(2026, 5, 15)
covered = {interval.symbol for interval in intervals if interval.covers(when)}
print(",".join(covered))
print(",".join(resolve_membership(intervals, when)))
""".replace("__SYMBOLS__", repr(MANY_SYMBOLS)).replace(
    "__DEPARTED__", repr(DEPARTED)
)


def resolve_under_seed(seed: int) -> tuple[str, str]:
    """(raw set order, canonical resolution) from a fresh interpreter."""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(APP_SRC), str(PACKAGE_SRC), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    raw, resolved = result.stdout.strip().splitlines()
    return raw, resolved


class TestBitReproducibilityAcrossHashSeeds:
    """The claim itself: the answer is the same bytes under every hash seed."""

    def test_the_resolution_is_identical_under_every_hash_seed(self) -> None:
        # Architecture §12 pins PYTHONHASHSEED=0 in eval workers; this
        # test is the stronger property that the resolution does not
        # *need* the pin. Four departures out of 44 names keep the set
        # large enough that its iteration order genuinely moves.
        answers = {
            seed: resolve_under_seed(seed)[1] for seed in (0, 1, 2, 7, 31337)
        }
        assert set(answers.values()) == {",".join(MAY_ROSTER)}
        assert is_stable_symbol_order(MAY_ROSTER)
        assert "aaaUSDT" not in MAY_ROSTER

    def test_the_intermediate_set_order_really_does_vary(self) -> None:
        # The control that keeps the test above honest: under at least
        # two of these seeds the raw set iteration order differs, so the
        # identical answers were produced *despite* moved inputs, not
        # because nothing moved. If this ever fails, the environment's
        # set ordering happened not to vary — an environment curiosity,
        # not a product behaviour, but the equality test would then be
        # proving less than it claims.
        raw_orders = {resolve_under_seed(seed)[0] for seed in range(8)}
        assert len(raw_orders) >= 2

    def test_repeated_resolution_in_one_process_is_identical(self) -> None:
        intervals = roster_shift_intervals()
        first = resolve_membership(intervals, mid_month("2026-04"))
        for _ in range(3):
            assert resolve_membership(intervals, mid_month("2026-04")) == first
        assert first == ALL_FOUR
