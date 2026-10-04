"""Tests for :mod:`router.bingx_risk` — Stage 2 feature 2, the daily-loss
guard.

``additions_spec_bingx_vst_stage2.xml``, "BingX VST Stage 2", feature 2:
*System guards each rebalance with a daily-loss check before anything is
placed.  The first check of each UTC day records the account's equity as
that day's opening equity, in its own table in the DATABASE_URL store.
Each check computes daily_loss as opening equity minus current equity.
When daily_loss reaches 3% of the book's equity_usdt, it trips
risk.daily_loss.halt_on_daily_loss, flattens through feature 1 and returns
a daily_loss_halt refusal.  While a halt stands,
require_within_daily_loss_limit refuses every later check with
orders_halted, places nothing, and keeps refusing until
risk.daily_loss.manual_reset.  A profit or a smaller loss passes.*

Every clause of that sentence is held below, over a recording double that
stands in for feature 1's client (never a socket).  The double serves the
recorded balance document ``live/balance.json`` — whose row answers the
account's equity as ``"9999.2781"`` — for the guard's one read, and
carries the flatten's full face (the recorded one-resting-order listing,
the recorded one-way short account's positions, the recorded code-0
answers) for the breach path, so the flatten a breach runs is exercised
against the venue's own spellings.  A day whose equity moved is staged by
deriving a second balance payload from the recorded one — the equity
string re-spelled, every other field verbatim — never by inventing a
response shape.

The halt side is proven through the risk member's own doors: the halt a
breach trips is read back through
:func:`risk.daily_loss.recorded_daily_loss_halts`, the standing refusal is
lifted by nobody but :func:`risk.daily_loss.manual_reset`, and the
figures the guard handed over (the day's loss, 3% of the book's
``equity_usdt``) are asserted on the rows risk itself recorded — so a
test proves *which* figures were handed to the member that owns the
judgement, rather than re-running it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from risk.daily_loss import manual_reset, recorded_daily_loss_halts
from router.bingx_flatten import BINGX_REDUCE_ONLY_TRUE
from router.bingx_risk import (
    BINGX_RISK_CODE,
    DAILY_LOSS_HALT_CODE,
    DAILY_LOSS_LIMIT_FRACTION,
    ROUTER_DAILY_OPENING_EQUITY_TABLE,
    DailyLossCheck,
    DailyOpeningEquity,
    RouterBingXDailyLossHaltError,
    RouterBingXOrdersHaltedError,
    RouterBingXRiskError,
    RouterDailyOpeningEquityStore,
    guard_daily_loss,
)
from router.errors import RouterError

#: The recorded VST fixtures, as every suite in this member reaches them:
#: inputs, never edited.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: The recorded account's equity — the figure ``live/balance.json``'s row
#: answers, the constant every derived balance payload is staged around.
RECORDED_EQUITY = "9999.2781"

#: The recorded resting order's identifier — an order that belongs to no
#: book and no rebalance, which is exactly the order a flatten must
#: cancel when a breach runs one.
FOREIGN_ORDER_ID = "nulliusprobe0000000000000000000000000000"

#: The one check moment most tests run at — a fixed UTC instant, so the
#: UTC day a check measures against is the test's own fact and never the
#: wall clock's.
NOON = datetime(2026, 10, 4, 12, 5, tzinfo=UTC)
THE_DAY = date(2026, 10, 4)
NEXT_DAY = date(2026, 10, 5)


def _live(name: str) -> dict:
    """One recorded fixture, verbatim."""
    return json.loads((FIXTURES / "live" / name).read_text(encoding="utf-8"))


def _balance_data() -> dict:
    """The recorded balance document's ``data``: the object spelling.

    The client answers the envelope's ``data`` field — an object carrying
    the account's one row under ``balance`` — exactly as the recorded
    ``live/balance.json`` spells it.
    """
    return _live("balance.json")["data"]


def _live_listing() -> dict:
    """The live open-orders ``data``: one resting order, wrapped in orders."""
    return _live("open_orders_one_resting.json")["data"]


def _live_positions() -> list:
    """The live positions ``data``: a DOGE short of 5402 beside a BTC long
    of 0.0236 — the account the smoke test recorded."""
    return _live("positions_one_way_short.json")["data"]


def _empty_listing() -> dict:
    """The recorded empty listing's ``data`` (``live/open_orders.json``)."""
    return _live("open_orders.json")["data"]


def _at_equity(spelling: str) -> dict:
    """A balance ``data`` derived from the recorded one, its equity
    re-spelled.

    Every field but the equity string is the recording's own — a
    derivation, never an invented response shape: the venue answers the
    same row and a different equity, which is exactly what a day whose
    account moved looks like on the wire.
    """
    derived = json.loads(json.dumps(_balance_data()))
    derived["balance"]["equity"] = spelling
    return derived


def _book(equity_usdt: str = "10000") -> dict:
    """The synthetic Stage 0 book, with its equity re-spelled when a test
    pins the limit's own term.

    The book is the recorded fixture ``synthetic_book.json``; the equity
    is re-spelled only where a test measures 3% of a different figure.
    """
    book = json.loads((FIXTURES / "synthetic_book.json").read_text())
    book["equity_usdt"] = equity_usdt
    return book


class _GuardedVenue:
    """A recording stand-in for feature 1's client at the guard's seams.

    Serves ``balance`` from scripted payloads — one per call, in order,
    the last repeating — so a test can stage a day whose equity moves
    between the checks that measure it, and carries the flatten's full
    face (``open_orders`` and ``positions`` scripted the same way,
    ``cancel_order`` and ``place_order`` recording what they were handed
    and answering the recorded code-0 data) so the flatten a breach runs
    is feature 1's own walk over the recorded account.  A test that wants
    to prove the guard never reached the venue leaves the balance
    payloads empty and lets :meth:`balance` refuse.
    """

    def __init__(
        self,
        *,
        balance_data: list | None = None,
        open_orders_data: list | None = None,
        positions_data: list | None = None,
    ) -> None:
        self._balance = list(balance_data or [])
        self._open_orders = list(open_orders_data or [[]])
        self._positions = list(positions_data or [[]])
        self.balance_calls = 0
        self.open_orders_calls = 0
        self.positions_calls = 0
        #: Every call in the order it arrived, method first.
        self.calls: list[tuple] = []
        self.cancelled: list[tuple[str, str | None]] = []
        self.placed: list[dict] = []
        self.place_refusals: dict[int, Exception] = {}

    def balance(self):
        self.balance_calls += 1
        self.calls.append(("balance",))
        if not self._balance:
            raise AssertionError("the guard asked the venue for a balance")
        return self._balance[min(self.balance_calls, len(self._balance)) - 1]

    def open_orders(self, symbol: str | None = None):
        self.open_orders_calls += 1
        self.calls.append(("open_orders", symbol))
        return self._open_orders[
            min(self.open_orders_calls, len(self._open_orders)) - 1
        ]

    def positions(self, symbol: str | None = None):
        self.positions_calls += 1
        self.calls.append(("positions", symbol))
        return self._positions[min(self.positions_calls, len(self._positions)) - 1]

    def cancel_order(self, client_order_id: str, *, symbol: str | None = None):
        self.calls.append(("cancel_order", client_order_id, symbol))
        self.cancelled.append((client_order_id, symbol))
        return _live("cancel_order_ok.json")["data"]

    def place_order(self, order):
        self.calls.append(("place_order", dict(order)))
        self.placed.append(dict(order))
        refusal = self.place_refusals.get(len(self.placed))
        if refusal is not None:
            raise refusal
        return _live("cancel_order_ok.json")["data"]

    def then_balance(self, payload: dict) -> _GuardedVenue:
        """Stage one more balance answer, after the scripted ones."""
        self._balance.append(payload)
        return self


def _guard(
    client,
    *,
    book: dict | None = None,
    url: str,
    moment: datetime = NOON,
    emit=lambda line: None,
):
    """The guard's one call, with the test's own clock pinned at
    ``moment`` — the UTC day the check measures against is the test's
    fact, never the wall clock's."""
    return guard_daily_loss(
        client=client,
        book=book if book is not None else _book(),
        database_url=url,
        now=lambda: moment,
        emit=emit,
    )


def _table_rows(url: str) -> list[tuple]:
    """The opening-equity table's rows, read straight out of the store
    the URL names — raw SQL on purpose, so the tests pin the table's own
    name and the venue's verbatim string spellings rather than reading
    them back through the store under test."""
    path = url.removeprefix("sqlite://")
    with sqlite3.connect(path) as plain:
        return plain.execute(
            f"SELECT day, opening_equity, recorded_at "
            f"FROM {ROUTER_DAILY_OPENING_EQUITY_TABLE} ORDER BY day"
        ).fetchall()


def _halted(client, *, url: str, moment: datetime = NOON, book: dict | None = None):
    """The guard's refusal, staged as a breach at ``moment``."""
    with pytest.raises(RouterBingXDailyLossHaltError) as refusal:
        _guard(
            client,
            book=book,
            url=url,
            moment=moment,
        )
    return refusal.value


# -- The first check of each UTC day records the day's opening equity ------------


def test_the_first_check_of_a_utc_day_records_that_days_opening_equity(
    test_database_url: str,
) -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    check = _guard(venue, url=test_database_url)

    assert check.day == THE_DAY
    assert check.opening_equity == Decimal(RECORDED_EQUITY)
    assert check.current_equity == Decimal(RECORDED_EQUITY)
    assert check.daily_loss == Decimal(0)
    assert check.recorded_opening is True
    # The row landed in the store DATABASE_URL names, in this feature's
    # own table, carrying the venue's own spelling verbatim.
    assert _table_rows(test_database_url) == [
        (THE_DAY.isoformat(), RECORDED_EQUITY, NOON.isoformat())
    ]


def test_the_days_opening_is_the_first_checks_own_reading_not_a_high_water_mark(
    test_database_url: str,
) -> None:
    # Whatever the first check of a day reads IS that day's opening — a
    # day that first opens far below yesterday's close opens there, and
    # the loss it measures is measured from its own opening, never from
    # a figure the day never held.
    venue = _GuardedVenue(balance_data=[_at_equity("9500"), _at_equity("9400")])
    _guard(venue, url=test_database_url)
    check = _guard(venue, url=test_database_url)

    assert check.recorded_opening is False
    assert check.opening_equity == Decimal(9500)
    assert check.daily_loss == Decimal(100)


def test_every_later_check_of_the_day_measures_against_the_first(
    test_database_url: str,
) -> None:
    venue = _GuardedVenue(
        balance_data=[_at_equity("10000.0000"), _at_equity("9900.5000")]
    )
    first = _guard(venue, url=test_database_url)
    second = _guard(venue, url=test_database_url)

    assert first.recorded_opening is True
    assert second.recorded_opening is False
    assert second.opening_equity == Decimal("10000.0000")
    assert second.current_equity == Decimal("9900.5000")
    # daily_loss is opening equity minus current equity, exactly.
    assert second.daily_loss == Decimal("99.5000")
    # One row per day, never rewritten.
    assert len(_table_rows(test_database_url)) == 1


def test_the_day_is_the_utc_day_of_the_checks_own_moment(
    test_database_url: str,
) -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    # 01:30 at +02:00 is 23:30 UTC the day before — the UTC day is what
    # the check measures against, not the local calendar's.
    local_two = datetime.fromisoformat("2026-10-05T01:30:00+02:00")
    check = _guard(venue, url=test_database_url, moment=local_two)
    assert check.day == THE_DAY
    assert [row[0] for row in _table_rows(test_database_url)] == ["2026-10-04"]


def test_a_new_utc_day_opens_a_new_row(
    test_database_url: str,
) -> None:
    venue = _GuardedVenue(
        balance_data=[
            _at_equity("10000"),
            _at_equity("10100"),
            _at_equity("10050"),
        ]
    )
    late = datetime(2026, 10, 4, 23, 59, tzinfo=UTC)
    early = datetime(2026, 10, 5, 0, 1, tzinfo=UTC)
    _guard(venue, url=test_database_url, moment=late)
    second = _guard(venue, url=test_database_url, moment=early)
    # The new day's OWN later check measures against the new day's own
    # opening, never against the halted-with-yesterday figure.
    third = _guard(
        venue, url=test_database_url, moment=datetime(2026, 10, 5, 0, 5, tzinfo=UTC)
    )

    assert second.day == NEXT_DAY
    assert second.opening_equity == Decimal(10100)
    assert second.daily_loss == Decimal(0)
    assert third.opening_equity == Decimal(10100)
    assert third.daily_loss == Decimal(50)
    assert [row[0] for row in _table_rows(test_database_url)] == [
        "2026-10-04",
        "2026-10-05",
    ]


def test_the_default_clock_answers_the_present_utc_day(
    test_database_url: str,
) -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    # No ``now`` handed: the check's moment is the instant of the call,
    # and the day it names is whichever UTC day that is — proven
    # self-consistently (the row the check says it recorded is the row
    # the table holds), never against the wall clock a second time.
    check = guard_daily_loss(client=venue, book=_book(), database_url=test_database_url)
    assert isinstance(check.day, date)
    stored = RouterDailyOpeningEquityStore(test_database_url).opening(check.day)
    assert stored is not None
    assert stored.equity == Decimal(RECORDED_EQUITY)


def test_two_records_for_one_day_are_first_write_wins(
    test_database_url: str,
) -> None:
    store = RouterDailyOpeningEquityStore(test_database_url)
    landed = store.record(THE_DAY, equity=Decimal("10000.0000"), recorded_at=NOON)
    raced = store.record(
        THE_DAY,
        equity=Decimal(9000),
        recorded_at=NOON + timedelta(minutes=4),
    )

    assert landed.changed is True
    assert raced.changed is False
    assert raced.equity == Decimal("10000.0000")
    assert raced.recorded_at == NOON
    assert len(_table_rows(test_database_url)) == 1


@pytest.mark.parametrize(
    ("equity", "recorded_at"),
    [
        ("not-a-decimal", "2026-10-04T12:05:00+00:00"),
        ("9999.2781", "not-a-moment"),
        ("9999.2781", "2026-10-04T12:05:00"),  # naive: no UTC day to order by
    ],
)
def test_a_row_another_tool_wrote_badly_is_refused_naming_the_day(
    test_database_url: str, equity: str, recorded_at: str
) -> None:
    # The table is created by the store itself, not by any migration —
    # the same idempotent-on-connect stance every member store takes —
    # so the tamper is seeded into the shape the store will read.
    RouterDailyOpeningEquityStore(test_database_url).ensure_schema()
    path = test_database_url.removeprefix("sqlite://")
    with sqlite3.connect(path) as plain:
        plain.execute(
            f"INSERT INTO {ROUTER_DAILY_OPENING_EQUITY_TABLE} "
            "(day, opening_equity, recorded_at) VALUES (?, ?, ?)",
            (THE_DAY.isoformat(), equity, recorded_at),
        )

    with pytest.raises(RouterBingXRiskError, match=BINGX_RISK_CODE):
        RouterDailyOpeningEquityStore(test_database_url).opening(THE_DAY)


# -- The measurement and the pass ------------------------------------------------


def test_the_limit_is_three_percent_of_the_books_equity_usdt(
    test_database_url: str,
) -> None:
    venue = _GuardedVenue(balance_data=[_at_equity("20000")])
    check = _guard(venue, book=_book("20000"), url=test_database_url)
    assert check.daily_loss_limit == Decimal("600.00")
    assert Decimal(20000) * DAILY_LOSS_LIMIT_FRACTION == Decimal("600.00")


def test_a_profit_passes(test_database_url: str) -> None:
    venue = _GuardedVenue(balance_data=[_at_equity("10000"), _at_equity("10250.75")])
    _guard(venue, url=test_database_url)
    check = _guard(venue, url=test_database_url)

    # A gain wears the loss's name as a negative figure — stated, never
    # clamped — and passes without the risk member being asked for a
    # halt: nothing stands in its table.
    assert check.daily_loss == Decimal("-250.75")
    assert recorded_daily_loss_halts(database_url=test_database_url) == ()


def test_a_smaller_loss_passes(test_database_url: str) -> None:
    venue = _GuardedVenue(
        balance_data=[_at_equity("10299.9999"), _at_equity("10000.0000")]
    )
    _guard(venue, url=test_database_url)
    check = _guard(venue, url=test_database_url)

    assert check.daily_loss == Decimal("299.9999")
    assert check.daily_loss < check.daily_loss_limit
    assert recorded_daily_loss_halts(database_url=test_database_url) == ()


def test_a_loss_sitting_exactly_at_three_percent_passes(
    test_database_url: str,
) -> None:
    # The comparison is risk feature 325's own strict one — a day at
    # exactly its limit is a day at the line, not past it — reached by
    # handing the figures over, never re-judged here.
    venue = _GuardedVenue(
        balance_data=[_at_equity("10300.0000"), _at_equity("10000.0000")]
    )
    _guard(venue, url=test_database_url)
    check = _guard(venue, url=test_database_url)

    assert check.daily_loss == check.daily_loss_limit == Decimal("300.00")
    assert recorded_daily_loss_halts(database_url=test_database_url) == ()


# -- The breach: trip, flatten, refuse -------------------------------------------


def _breached_venue() -> _GuardedVenue:
    """The recorded account, down past 3% by the day's second check.

    The day opens at the recorded equity ``9999.2781``; the second check
    reads ``9649.2781`` — a loss of exactly 350 against the book's
    ``equity_usdt`` 10000, past the 300 the sentence's 3% draws.  The
    flatten's final read answers the recorded empty listing, so the
    flatten succeeds.
    """
    return _GuardedVenue(
        balance_data=[_balance_data(), _at_equity("9649.2781")],
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )


def test_a_loss_past_three_percent_trips_risk_daily_loss_halt(
    test_database_url: str,
) -> None:
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    refusal = _halted(venue, url=test_database_url)

    # The halt landed in the risk member's own table, carrying the two
    # figures this guard handed over: the day's loss and 3% of the
    # book's equity_usdt.
    (halt,) = recorded_daily_loss_halts(database_url=test_database_url)
    assert halt.loss == pytest.approx(350.0)
    assert halt.limit == pytest.approx(300.0)
    assert halt.standing is True
    assert halt.breached_at == NOON
    # The refusal carries the halt and the measurement it was judged on.
    assert refusal.halt is not None
    assert refusal.check.daily_loss == Decimal("350.0000")
    assert refusal.check.daily_loss_limit == Decimal("300.00")
    # The day's opening row is the breach's evidence and stays put.
    assert _table_rows(test_database_url) == [
        (THE_DAY.isoformat(), RECORDED_EQUITY, NOON.isoformat())
    ]


def test_the_breach_refusal_opens_with_daily_loss_halt_and_names_the_reset(
    test_database_url: str,
) -> None:
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    refusal = _halted(venue, url=test_database_url)

    assert isinstance(refusal, RouterError)
    assert str(refusal).startswith(f"{DAILY_LOSS_HALT_CODE}:")
    assert "risk.daily_loss.manual_reset" in str(refusal)


def test_the_breach_flattens_through_feature_one(
    test_database_url: str,
) -> None:
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    lines: list[str] = []
    with pytest.raises(RouterBingXDailyLossHaltError) as caught:
        guard_daily_loss(
            client=venue,
            book=_book(),
            database_url=test_database_url,
            now=lambda: NOON,
            emit=lines.append,
        )

    # The flatten is feature 1's own walk over the recorded account: the
    # foreign resting order cancelled by its identifier with its symbol,
    # one reduce-only MARKET close per non-zero position — a BUY for the
    # DOGE short, a SELL for the BTC long — in the venue's own order.
    assert venue.cancelled == [(FOREIGN_ORDER_ID, "SOL-USDT")]
    assert [order["symbol"] for order in venue.placed] == ["DOGE-USDT", "BTC-USDT"]
    assert all(
        order["type"] == "MARKET" and order["reduceOnly"] == BINGX_REDUCE_ONLY_TRUE
        for order in venue.placed
    )
    doge = next(o for o in venue.placed if o["symbol"] == "DOGE-USDT")
    btc = next(o for o in venue.placed if o["symbol"] == "BTC-USDT")
    assert (doge["side"], doge["quantity"]) == ("BUY", "5402")
    assert (btc["side"], btc["quantity"]) == ("SELL", "0.0236")
    # One JSON line per cancelled order and per close, through the
    # guard's own emit — an operator watching a halted run watches the
    # flatten happen.
    assert len(lines) == 3
    assert all(isinstance(json.loads(line), dict) for line in lines)
    assert caught.value.flatten_report is not None
    assert caught.value.flatten_report.succeeded is True


def test_a_flatten_the_venue_refuses_still_raises_the_daily_loss_halt(
    test_database_url: str,
) -> None:
    from router.bingx_client import RouterBingXRefusedError

    venue = _breached_venue()
    envelope = _live("cancel_order_body_params_refused.json")
    venue.place_refusals = {
        index: RouterBingXRefusedError(envelope["code"], envelope["msg"])
        for index in (1, 2)
    }
    _guard(venue, url=test_database_url)
    with pytest.raises(RouterBingXDailyLossHaltError) as caught:
        _guard(venue, url=test_database_url)

    # The halt stood in the store before the flatten ran, so the refusal
    # is the daily-loss halt's — carrying a report that says the account
    # still needs an operator's eye.
    report = caught.value.flatten_report
    assert report is not None
    assert report.succeeded is False
    assert "operator" in str(caught.value)
    assert recorded_daily_loss_halts(database_url=test_database_url)


def test_a_flatten_that_cannot_be_read_still_raises_the_daily_loss_halt(
    test_database_url: str,
) -> None:
    class _NoFlattenFace:
        """A client the guard can read the balance through but feature 1
        cannot flatten through — the flatten's own ask-refusal, staged to
        prove the breach's refusal survives it."""

        def __init__(self, data: dict) -> None:
            self._data = data

        def balance(self):
            return self._data

    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    refused = _NoFlattenFace(_at_equity("9649.2781"))
    with pytest.raises(RouterBingXDailyLossHaltError) as caught:
        _guard(refused, url=test_database_url)

    assert caught.value.flatten_report is None
    assert caught.value.flatten_fault is caught.value.__cause__
    assert "could not be performed" in str(caught.value)
    # The halt tripped all the same.
    assert recorded_daily_loss_halts(database_url=test_database_url)


# -- While a halt stands ----------------------------------------------------------


def test_every_later_check_refuses_with_orders_halted(
    test_database_url: str,
) -> None:
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    _halted(venue, url=test_database_url)

    # The next check would measure a recovery — but it is never made:
    # the standing halt refuses first, with the risk member's own word.
    venue.then_balance(_at_equity("9990"))
    with pytest.raises(RouterBingXOrdersHaltedError) as caught:
        _guard(venue, url=test_database_url)

    assert isinstance(caught.value, RouterError)
    assert str(caught.value).startswith("orders_halted:")
    assert "risk.daily_loss.manual_reset" in str(caught.value)
    # The refusal carries the standing halt record verbatim.
    assert caught.value.halt is not None
    assert caught.value.halt.loss == pytest.approx(350.0)
    assert caught.value.halt.standing is True


def test_a_standing_halt_refuses_before_the_venue_is_asked_anything(
    test_database_url: str,
) -> None:
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    _halted(venue, url=test_database_url)

    # No balance scripted on the later venue: the double refuses the read
    # itself, so the test fails if the guard reaches the venue under a
    # standing halt — the sentence's own "places nothing", held to "asks
    # nothing".
    late = _GuardedVenue()
    with pytest.raises(RouterBingXOrdersHaltedError):
        _guard(late, url=test_database_url)
    assert late.balance_calls == 0


def test_the_halt_keeps_refusing_across_checks_and_across_utc_days(
    test_database_url: str,
) -> None:
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    _halted(venue, url=test_database_url)

    for _ in range(3):
        with pytest.raises(RouterBingXOrdersHaltedError):
            _guard(venue, url=test_database_url)
    # A new UTC day does not lift it either — "until a manual reset" is
    # the sentence's own clock — and the new day's opening equity is NOT
    # recorded by a check that refused.
    with pytest.raises(RouterBingXOrdersHaltedError):
        _guard(
            venue, url=test_database_url, moment=datetime(2026, 10, 5, 0, 1, tzinfo=UTC)
        )
    assert [row[0] for row in _table_rows(test_database_url)] == ["2026-10-04"]


def test_the_halt_lifts_only_at_risk_daily_loss_manual_reset(
    test_database_url: str,
) -> None:
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    _halted(venue, url=test_database_url)
    with pytest.raises(RouterBingXOrdersHaltedError):
        _guard(venue, url=test_database_url)

    closed = manual_reset(database_url=test_database_url, reset_by="operator")
    assert closed.standing is False

    # The recovered day passes: the loss is back inside the line, and
    # the check that passes is the one the reset re-opened.
    venue.then_balance(_at_equity("9900"))
    check = _guard(venue, url=test_database_url)
    assert check.daily_loss == Decimal("99.2781")
    assert check.daily_loss < check.daily_loss_limit


def test_a_reset_does_not_re_baseline_the_days_opening_equity(
    test_database_url: str,
) -> None:
    # The subtlest clause: the opening equity is the FIRST check's fact
    # for the whole day, and the reset lifts the halt, not the
    # measurement.  A same-day check still down past 3% after a reset
    # therefore trips a NEW halt against the SAME opening — the
    # per-episode law of the risk member's table, reached by this guard
    # handing the day's unchanged figures back to it.
    venue = _breached_venue()
    _guard(venue, url=test_database_url)
    _halted(venue, url=test_database_url)
    manual_reset(database_url=test_database_url, reset_by="operator")
    _halted(venue, url=test_database_url)

    halts = recorded_daily_loss_halts(database_url=test_database_url)
    assert len(halts) == 2
    assert halts[0].standing is False
    assert halts[1].standing is True
    assert halts[1].loss == pytest.approx(350.0)
    # One row for the day, still the recorded opening.
    assert _table_rows(test_database_url) == [
        (THE_DAY.isoformat(), RECORDED_EQUITY, NOON.isoformat())
    ]


# -- The ask's own refusals --------------------------------------------------------


def test_no_store_named_refuses_by_name() -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    with pytest.raises(RouterBingXRiskError) as caught:
        guard_daily_loss(client=venue, book=_book(), env={}, now=lambda: NOON)

    assert str(caught.value).startswith(f"{BINGX_RISK_CODE}:")
    assert "DATABASE_URL" in str(caught.value)
    # The venue was never asked: the check refuses before it records.
    assert venue.balance_calls == 0


def test_an_empty_database_url_counts_as_no_store() -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    with pytest.raises(RouterBingXRiskError, match="DATABASE_URL"):
        guard_daily_loss(client=venue, book=_book(), database_url="", now=lambda: NOON)


def test_a_store_this_module_cannot_speak_is_refused_by_name() -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    with pytest.raises(RouterBingXRiskError, match="sqlite"):
        guard_daily_loss(
            client=venue,
            book=_book(),
            database_url="postgres://localhost:5432/nullius",
            now=lambda: NOON,
        )


def test_a_risk_store_that_cannot_answer_is_translated_not_read_as_open(
    tmp_path: Path,
) -> None:
    # The halt's own store cannot be asked (the database path is a
    # directory), and a store that cannot be asked whether a halt stands
    # must not read as one that answered no — the guard refuses in its
    # own vocabulary rather than letting the rebalance run unguarded.
    # The URL is spelled the conftest's way — sqlite:/// before an
    # absolute path — so the directory the URL names is the directory
    # sqlite tries to open.
    wall = tmp_path / "wall"
    wall.mkdir()
    venue = _GuardedVenue(balance_data=[_balance_data()])
    with pytest.raises(RouterBingXRiskError, match="could not be read"):
        guard_daily_loss(
            client=venue,
            book=_book(),
            database_url=f"sqlite:///{wall}",
            now=lambda: NOON,
        )


@pytest.mark.parametrize(
    "book",
    [
        {},
        {"equity_usdt": None},
        {"equity_usdt": 10000.0},
        {"equity_usdt": "0"},
        {"equity_usdt": "-5"},
        {"equity_usdt": "NaN"},
        "not-a-book",
    ],
)
def test_a_book_no_limit_can_be_drawn_from_is_refused(
    test_database_url: str, book: object
) -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    with pytest.raises(RouterBingXRiskError, match=BINGX_RISK_CODE):
        _guard(venue, book=book, url=test_database_url)
    assert venue.balance_calls == 0


def test_a_client_without_balance_is_refused(test_database_url: str) -> None:
    class _NoBalance:
        pass

    with pytest.raises(RouterBingXRiskError, match="balance"):
        _guard(_NoBalance(), url=test_database_url)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"balance": "9999.2781"},
        [],
        ["not-a-row"],
        # The array spelling with a row labelled by an asset that is
        # neither USDT nor empty names no account row this member reads.
        [_balance_data()["balance"]],
    ],
)
def test_a_balance_payload_naming_no_account_row_is_refused(
    test_database_url: str, payload: object
) -> None:
    class _Serving:
        def __init__(self, data: object) -> None:
            self._data = data

        def balance(self):
            return self._data

    with pytest.raises(RouterBingXRiskError, match="balance payload"):
        _guard(_Serving(payload), url=test_database_url)


@pytest.mark.parametrize("equity", [None, 9999.28, True, "not-a-decimal"])
def test_a_balance_row_naming_no_readable_equity_is_refused(
    test_database_url: str, equity: object
) -> None:
    payload = json.loads(json.dumps(_balance_data()))
    if equity is None:
        del payload["balance"]["equity"]
    else:
        payload["balance"]["equity"] = equity

    with pytest.raises(RouterBingXRiskError, match="equity"):
        _guard(_GuardedVenue(balance_data=[payload]), url=test_database_url)


@pytest.mark.parametrize(
    "payload",
    [
        # The v3 document's array spelling: the row labelled USDT, and
        # the one unlabelled row of an account settled in a single asset
        # — both derived from the recorded row, every field verbatim but
        # the label the endpoint's versions disagree about.
        lambda row: [dict(row, asset="USDT")],
        lambda row: [dict(row, asset="")],
    ],
)
def test_the_balance_row_is_read_in_both_document_spellings(
    test_database_url: str, payload
) -> None:
    row = _balance_data()["balance"]
    venue = _GuardedVenue(balance_data=[payload(row)])
    check = _guard(venue, url=test_database_url)
    assert check.opening_equity == Decimal(RECORDED_EQUITY)


def test_a_naive_clock_answer_is_refused(test_database_url: str) -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    with pytest.raises(RouterBingXRiskError, match="timezone-aware"):
        # The naive moment is the test's subject — a check that cannot
        # say which UTC day it is must refuse rather than guess one.
        _guard(
            venue,
            url=test_database_url,
            moment=datetime(2026, 10, 4, 12, 5),  # noqa: DTZ001
        )
    assert venue.balance_calls == 0


def test_a_non_callable_clock_is_refused(test_database_url: str) -> None:
    venue = _GuardedVenue(balance_data=[_balance_data()])
    with pytest.raises(RouterBingXRiskError, match="now"):
        guard_daily_loss(
            client=venue,
            book=_book(),
            database_url=test_database_url,
            now=NOON,  # a moment, not a clock
        )


# -- The records' own law -----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param(
            {
                "day": THE_DAY,
                "equity": Decimal("NaN"),
                "recorded_at": NOON,
                "changed": True,
            },
            id="a NaN equity",
        ),
        {
            "day": datetime(2026, 10, 4, 12, tzinfo=UTC),
            "equity": Decimal(1),
            "recorded_at": NOON,
            "changed": True,
        },
        {
            "day": THE_DAY,
            "equity": Decimal(1),
            "recorded_at": NOON.replace(tzinfo=None),
            "changed": True,
        },
        {"day": THE_DAY, "equity": Decimal(1), "recorded_at": NOON, "changed": 1},
    ],
)
def test_an_opening_equity_refuses_a_row_no_check_could_write(
    kwargs: dict,
) -> None:
    with pytest.raises(RouterBingXRiskError):
        DailyOpeningEquity(
            equity=kwargs["equity"],
            day=kwargs["day"],
            recorded_at=kwargs["recorded_at"],
            changed=kwargs["changed"],
        )


def test_an_opening_equity_refuses_a_float_equity() -> None:
    with pytest.raises(RouterBingXRiskError, match="Decimal"):
        DailyOpeningEquity(
            day=THE_DAY, equity=9999.2781, recorded_at=NOON, changed=False
        )


@pytest.mark.parametrize(
    "override",
    [
        {"opening_equity": 10000.0},
        {"daily_loss": 1.5},
        {"recorded_opening": 1},
    ],
)
def test_a_check_refuses_a_term_no_check_could_carry(override: dict) -> None:
    terms = {
        "day": THE_DAY,
        "opening_equity": Decimal(10000),
        "current_equity": Decimal(9900),
        "daily_loss": Decimal(100),
        "daily_loss_limit": Decimal("300.00"),
        "recorded_opening": True,
    }
    with pytest.raises(RouterBingXRiskError):
        DailyLossCheck(**{**terms, **override})
