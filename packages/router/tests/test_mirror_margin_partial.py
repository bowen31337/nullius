"""Tests for partial placement at the margin door: :mod:`router.bingx_mirror`.

``bug_spec_vst_margin_partial_placement.xml``, bug 1.  The fix that netted
the reducing legs' release against the increasing legs' requirement
(``bug_spec_vst_slot_resilience.xml``, bug 1) did not end the deadlock it
was written for, because the counterfactual it rested on was never bought:
the venue frees a reducing fill's margin only as the fill settles, and a
preflight that judged the netted term *before any order was sent* could
never let a reducing leg leave.  The live Addenda record the result — six
consecutive four-hour slots (2026-10-22 12:00 to 2026-10-23 08:00 UTC), each
refused in under ten seconds with the same available figure to four decimals
across twenty-four hours (*"insufficient_balance: available USDT 636.2532 is
below the N this plan's orders need"*, N between 700 and 828) — a stalled
heartbeat and no order placed since 2026-10-22 00:06 UTC.

The fix, clause by clause:

* :func:`router.bingx_preflight.run_bingx_preflight` keeps its signature and
  its four checks; the mirror now hands it ``required_usdt=Decimal(0)``, so
  the kill, skew, hedge-mode and per-symbol preparation checks still run
  while the balance door passes vacuously.
  :func:`router.bingx_preflight.read_available_usdt` exposes the balance
  read the mirror judges with.
* :func:`router.bingx_mirror.mirror_place` sends the position-reducing legs
  first, re-reads the account (polling up to
  :data:`router.bingx_mirror.MARGIN_SETTLE_POLLS` times at
  :data:`router.bingx_mirror.MARGIN_SETTLE_INTERVAL` when a reducing leg was
  placed this run, so a settling fill can release its margin), then admits
  the increasing legs in descending order of their own requirement while the
  running total stays at or below the available figure.  A leg that does not
  fit is a ``refused`` :class:`~router.bingx_mirror.MirrorLeg` carrying
  :data:`router.bingx_mirror.MARGIN_DEFERRED_CODE` — reported, never sent,
  never silently dropped — so the next slot re-reads the balance instead of
  the book deadlocking forever.
* A plan the account can fund whole admits every leg and is placed in exactly
  the order the verb sent before this bug existed; a leg the store already
  holds is answered ``prior`` and is never deferred.

Every test injects a client double — no socket, no key, no network — in the
style of :mod:`packages.router.tests.test_mirror_margin_netting`, whose fakes
and fixture book this suite reuses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import test_mirror_margin_netting as netting_fixtures
from risk.kill import send_kill
from router.bingx_mirror import (
    MARGIN_DEFERRED_CODE,
    MARGIN_SETTLE_INTERVAL,
    MARGIN_SETTLE_POLLS,
    MIRROR_OUTCOME_PLACED,
    MIRROR_OUTCOME_PRIOR,
    MIRROR_OUTCOME_REFUSED,
    mirror_place,
)
from router.bingx_order import BINGX_BUY, BINGX_SELL, BingXOrder
from router.bingx_preflight import (
    RouterBingXHedgeModeError,
    RouterBingXOrdersKilledError,
    read_available_usdt,
    run_bingx_preflight,
)
from router.submission_result import RouterOrderPlacementStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: The moment the planted kill is sent, taken from the kill suite's own
#: pinned instant so the two suites record the same instruction.
KILL_SENT_AT = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)

#: The spec's own case-(a) figures, at the fixture's price of one so every
#: quantity reads as its own notional: two reducing legs, three increasing
#: legs needing 300, 100 and 200, and 450 available once the reducing legs
#: have filled.
AVAILABLE_AFTER_FILL = "450"
C_NEEDS = "100"
D_NEEDS = "300"
E_NEEDS = "200"

#: The five symbols the plan trades: the venue's contracts and premiumIndex
#: documents must price every one of them, so the double answers for all
#: five rather than the netting fixture's narrower four.
PLAN_SYMBOLS = ("A-USDT", "B-USDT", "C-USDT", "D-USDT", "E-USDT")


def _held() -> tuple[dict, ...]:
    """A long A and a short B — the two legs the plan trims."""
    return (
        {"symbol": "A-USDT", "positionSide": "LONG", "positionAmt": "100"},
        {"symbol": "B-USDT", "positionSide": "SHORT", "positionAmt": "100"},
    )


def _book() -> dict:
    """The netting fixture's book, widened to the fifth leg.

    Five legs, not four: a repriced leg is judged through its symbol's
    decay horizon, so a book that states none for a symbol the plan orders
    refuses that leg before it leaves — a wiring fault, not the margin
    behaviour this suite is about.  The terms are the sibling book's own.
    """
    book = netting_fixtures._book()
    book["weights"] = {symbol: 0.01 for symbol in PLAN_SYMBOLS}
    book["decay_horizon_seconds"] = {
        symbol: 14400 for symbol in PLAN_SYMBOLS
    }
    return book


def _plan() -> list[BingXOrder]:
    """The spec's five legs: A and B reduce, C, D and E increase.

    Spelled reducing-first, so the plan's own order already matches the send
    order and a funded run's sequence is unambiguous.
    """
    leg = netting_fixtures._leg
    return [
        leg(symbol="A-USDT", side=BINGX_SELL, quantity="50"),
        leg(symbol="B-USDT", side=BINGX_BUY, quantity="50"),
        leg(symbol="C-USDT", side=BINGX_BUY, quantity=C_NEEDS),
        leg(symbol="D-USDT", side=BINGX_BUY, quantity=D_NEEDS),
        leg(symbol="E-USDT", side=BINGX_BUY, quantity=E_NEEDS),
    ]


def _balance(available: str) -> dict:
    """A balance document answering ``available`` for the one USDT row."""
    return {"balance": {"asset": "USDT", "availableMargin": available}}


class _SequencedClient(netting_fixtures._NettingClient):
    """A netting client whose ``balance`` walks a list of answers.

    The last answer repeats once the list is spent, so a poll that finds no
    movement keeps reading the same figure — the state the deadlocked
    account was in for a day.
    """

    def __init__(
        self, *, balances: list[str], symbols: object = PLAN_SYMBOLS, **kwargs
    ) -> None:
        super().__init__(symbols=symbols, **kwargs)
        self._answers = list(balances)
        self.balance_reads = 0

    def balance(self) -> object:
        self.balance_reads += 1
        index = min(self.balance_reads, len(self._answers)) - 1
        return _balance(self._answers[index])


def _place(client, plan, database_url, *, sleep=lambda _d: None):
    return mirror_place(
        client=client,
        book=_book(),
        plan=plan,
        store=RouterOrderPlacementStore(database_url),
        limiter=netting_fixtures._CountingLimiter(),
        database_url=database_url,
        clock=lambda: netting_fixtures.LOCAL_MILLIS,
        sleep=sleep,
    )


def _deferred(outcomes) -> dict:
    return {
        symbol: outcome
        for symbol, outcome in outcomes.items()
        if outcome.code == MARGIN_DEFERRED_CODE
    }


# -- (a) descending admission defers only the leg that does not fit --------------


def test_the_running_total_admits_the_largest_legs_and_defers_the_middle_one(
    test_database_url,
):
    """The spec's own case: 300, 100 and 200 against 450 available.

    Descending admission keeps the 300, skips the 200 (300 + 200 is above
    450) and then admits the 100 — so the one deferred leg is the 200, and
    it is deferred rather than sent: the walk does not stop at the leg that
    did not fit.  Its message names the three figures the spec names — its
    own requirement 200, the 400 the account ends up committed to, and the
    450 available.
    """
    client = _SequencedClient(
        balances=[AVAILABLE_AFTER_FILL], positions=_held()
    )

    outcomes = _place(client, _plan(), test_database_url)

    assert len(outcomes) == 5
    assert [o.symbol for o in client.placed] == [
        "A-USDT",
        "B-USDT",
        "C-USDT",
        "D-USDT",
    ]
    assert outcomes["A-USDT"].outcome == MIRROR_OUTCOME_PLACED
    assert outcomes["B-USDT"].outcome == MIRROR_OUTCOME_PLACED
    assert outcomes["C-USDT"].outcome == MIRROR_OUTCOME_PLACED
    assert outcomes["D-USDT"].outcome == MIRROR_OUTCOME_PLACED
    deferred = _deferred(outcomes)
    assert set(deferred) == {"E-USDT"}
    message = deferred["E-USDT"].message
    assert message.startswith("margin_deferred")
    assert deferred["E-USDT"].outcome == MIRROR_OUTCOME_REFUSED
    for figure in (E_NEEDS, "400", AVAILABLE_AFTER_FILL):
        assert figure in message, f"{figure} missing from {message!r}"
    # Nothing was sent for the deferred leg.
    assert all(order.symbol != "E-USDT" for order in client.placed)


# -- (b) an account that cannot afford anything defers every increasing leg ------


def test_available_50_places_the_reducing_legs_and_defers_every_increasing_leg(
    test_database_url,
):
    """Nothing is raised: the legs that fit are sent, the rest are reported."""
    client = _SequencedClient(balances=["50"], positions=_held())

    outcomes = _place(client, _plan(), test_database_url)

    assert [o.symbol for o in client.placed] == ["A-USDT", "B-USDT"]
    assert set(_deferred(outcomes)) == {"C-USDT", "D-USDT", "E-USDT"}
    assert outcomes["A-USDT"].outcome == MIRROR_OUTCOME_PLACED
    for symbol in ("C-USDT", "D-USDT", "E-USDT"):
        assert outcomes[symbol].outcome == MIRROR_OUTCOME_REFUSED
        assert "50" in outcomes[symbol].message


# -- (c) a funded plan is placed exactly as before ------------------------------


def test_a_funded_account_places_every_leg_in_the_plan_order(
    test_database_url,
):
    """The constraint's own regression guard: no deferral, no reordering.

    With 1000 available the plan's 600 of increasing legs are all admitted,
    and the sequence is the reducing-first one this verb has sent since
    ``bug_spec_vst_slot_resilience.xml`` — byte-for-byte the pre-bug order,
    because the admission judges largest-first but a funded plan admits
    everything.
    """
    client = _SequencedClient(balances=["1000"], positions=_held())

    outcomes = _place(client, _plan(), test_database_url)

    assert [o.symbol for o in client.placed] == [
        "A-USDT",
        "B-USDT",
        "C-USDT",
        "D-USDT",
        "E-USDT",
    ]
    assert all(
        outcome.outcome == MIRROR_OUTCOME_PLACED
        for outcome in outcomes.values()
    )
    assert _deferred(outcomes) == {}


# -- (d) the balance poll -------------------------------------------------------


def test_a_reducing_fill_that_releases_margin_is_seen_by_the_poll(
    test_database_url,
):
    """400 on the first read, 450 on the third: the poll waits the fill out.

    Three reads, in order: the preflight's own check, the read the mirror
    makes straight after the reducing legs leave — both 400, the pre-fill
    figure — and the poll's first read, which is the 450 the settling fill
    released.  The rise is seen on the third read, after one wait, and the
    poll stops there.  The admission it then makes is case (a)'s: the 100
    is admitted beside the 300 (300 + 100 <= 450) and the 200 is deferred.
    """
    client = _SequencedClient(
        balances=["400", "400", "450"], positions=_held()
    )
    slept: list = []

    outcomes = _place(
        client, _plan(), test_database_url, sleep=slept.append
    )

    assert client.balance_reads == 3
    assert slept == [MARGIN_SETTLE_INTERVAL]
    assert "D-USDT" in {order.symbol for order in client.placed}
    assert "C-USDT" in {order.symbol for order in client.placed}
    assert set(_deferred(outcomes)) == {"E-USDT"}


def test_a_plan_with_no_reducing_leg_does_not_poll(test_database_url):
    """Nothing was placed that could fill, so nothing is waited for.

    Three increasing legs against 450: the 300 and the 100 are admitted, the
    200 deferred, and the ``sleep`` seam is never called — the mirror does
    not spend half a minute of the slot's budget on an account it has not
    asked to fill anything.  The balance is read twice and no more: once by
    the preflight's own check and once by the judgement that follows it.
    """
    client = _SequencedClient(balances=[AVAILABLE_AFTER_FILL], positions=_held())
    slept: list = []

    outcomes = _place(
        client,
        [
            netting_fixtures._leg(symbol="C-USDT", side=BINGX_BUY, quantity=C_NEEDS),
            netting_fixtures._leg(symbol="D-USDT", side=BINGX_BUY, quantity=D_NEEDS),
            netting_fixtures._leg(symbol="E-USDT", side=BINGX_BUY, quantity=E_NEEDS),
        ],
        test_database_url,
        sleep=slept.append,
    )

    assert slept == []
    assert client.balance_reads == 2
    assert set(_deferred(outcomes)) == {"E-USDT"}


# -- (e) the preflight's four checks still run under required_usdt 0 ------------


def test_a_killed_order_layer_still_refuses_the_mirror(test_database_url):
    """The kill outranks the balance, and ``Decimal(0)`` does not skip it."""
    send_kill(
        database_url=test_database_url,
        sent_at=KILL_SENT_AT,
        supervisor_process_id="margin-partial-test/1",
    )
    client = _SequencedClient(
        balances=[AVAILABLE_AFTER_FILL], positions=_held()
    )

    with pytest.raises(RouterBingXOrdersKilledError):
        _place(client, _plan(), test_database_url)

    assert client.placed == []


def test_a_hedge_mode_account_still_refuses_the_mirror(test_database_url):
    """The account's shape is checked before its size, as before."""
    client = _SequencedClient(
        balances=[AVAILABLE_AFTER_FILL], positions=_held()
    )
    client.position_mode = lambda: True  # type: ignore[method-assign]

    with pytest.raises(RouterBingXHedgeModeError):
        _place(client, _plan(), test_database_url)

    assert client.placed == []


def test_the_preparation_runs_under_required_usdt_zero(
    test_database_url,
):
    """Every ordered symbol is still prepared, and the report records both terms.

    ``run_bingx_preflight(client, required_usdt=Decimal(0), ...)`` answers a
    passing report whose ``required_usdt`` is the zero it was handed and
    whose ``available_usdt`` is the account's own reading — the seam the
    mirror calls it through.
    """
    client = _SequencedClient(
        balances=[AVAILABLE_AFTER_FILL], positions=_held()
    )

    report = run_bingx_preflight(
        client,
        required_usdt=Decimal(0),
        symbols=[leg.symbol for leg in _plan()],
        database_url=None,
        clock=lambda: netting_fixtures.LOCAL_MILLIS,
    )

    assert report.required_usdt == Decimal(0)
    assert report.available_usdt == Decimal(AVAILABLE_AFTER_FILL)
    assert report.symbols == (
        "A-USDT", "B-USDT", "C-USDT", "D-USDT", "E-USDT"
    )
    assert read_available_usdt(client) == Decimal(AVAILABLE_AFTER_FILL)


# -- (f) a replay in the same slot places nothing and defers nothing ------------


def test_a_second_run_in_the_slot_defers_nothing(test_database_url):
    """The store's prior rows win: a held leg is never reported deferred.

    The second run reads the *same* short balance, but every leg this
    rebalance placed is already recorded, so all five are answered ``prior``
    and none is deferred — idempotence is not broken by the balance door.
    """
    first = _SequencedClient(balances=["1000"], positions=_held())
    _place(first, _plan(), test_database_url)

    second = _SequencedClient(balances=["10"], positions=_held())
    outcomes = _place(second, _plan(), test_database_url)

    assert second.placed == []
    assert all(
        outcome.outcome == MIRROR_OUTCOME_PRIOR
        for outcome in outcomes.values()
    )
    assert _deferred(outcomes) == {}


# -- The report the fixtures describe -------------------------------------------


def test_the_balance_fixture_states_the_deadlocked_figure_and_its_release():
    """The recorded pair: 636.2532 before, 789.4116 after the fill settles.

    The before figure is the Addenda's own — *"available USDT 636.2532 is
    below the N this plan's orders need"* — and the after figure is the
    margin a filled reducing leg released.  Read through the preflight's own
    public balance verb over the venue's document shape, so the two numbers
    the fix turns on are pinned beside the code that compares them.
    """
    document = json.loads(
        (
            FIXTURES / "live" / "balance_after_reducing_fill.json"
        ).read_text(encoding="utf-8")
    )

    class _DocumentClient:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def balance(self) -> object:
            return self._payload

    before = read_available_usdt(
        _DocumentClient(document["before"]["data"])
    )
    after = read_available_usdt(_DocumentClient(document["after"]["data"]))

    assert before == Decimal("636.2532")
    assert after == Decimal("789.4116")
    assert after > before


def test_the_settle_polls_are_bounded_and_the_interval_is_the_stated_one():
    """The two knobs the mirror waits on are module constants, documented."""
    assert MARGIN_SETTLE_POLLS == 6
    assert MARGIN_SETTLE_INTERVAL.total_seconds() == 5


def test_the_wait_is_bounded_when_the_balance_never_moves(
    test_database_url,
):
    """A fill that never settles costs the slot six waits and no more.

    The deadlocked account's own shape: the same figure to four decimals
    read after read.  The poll gives up after
    :data:`MARGIN_SETTLE_POLLS` waits — it does not spin — and the legs are
    admitted against the last figure it read, the 50 the account actually
    answers rather than a release that never came.
    """
    client = _SequencedClient(balances=["50"], positions=_held())
    slept: list = []

    outcomes = _place(
        client, _plan(), test_database_url, sleep=slept.append
    )

    assert slept == [MARGIN_SETTLE_INTERVAL] * MARGIN_SETTLE_POLLS
    assert [order.symbol for order in client.placed] == ["A-USDT", "B-USDT"]
    assert set(_deferred(outcomes)) == {"C-USDT", "D-USDT", "E-USDT"}
