"""Tests for :mod:`router.bingx_preflight` — the door before any placement.

Feature 2 of additions_spec_bingx_vst_mirror.xml, held clause by clause:
*System runs a VST preflight before any placement and returns a
PreflightReport, or the first refusal, in this order: orders_killed while
risk.kill.require_orders_allowed refuses; clock_skew when the venue's
server time differs from the local clock by more than 1000 ms; hedge_mode
when any position reports positionSide LONG or SHORT, with the repair
"switch the VST account to one-way mode"; insufficient_balance when
available USDT is below the book's equity_usdt.  For each symbol the plan
will order, it then sets margin type ISOLATED and leverage 1, treating an
already-set answer as success.  The report records the measured skew, the
available balance and the symbols prepared.*

Every test drives the preflight over an injected client double — the
suite never opens a socket, and one test patches ``socket.socket`` to
raise to prove it.  The kill channel is the one seam exercised for real:
the guard the feature names is
:func:`risk.kill.require_orders_allowed`, so the orders-killed tests
plant a standing kill through that member's own ``send_kill`` into a
test-only SQLite URL rather than faking the seam the sentence names.
The fixed clock pins the skew measurement, and the venue payloads are
the document shapes BingX's own account endpoints answer (the v2 object
under ``balance``, the v3 array keyed by ``asset``, the positions array
with ``positionSide`` per entry).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from risk.kill import send_kill
from router.bingx_client import RouterBingXRefusedError
from router.bingx_preflight import (
    ALREADY_SET_MSG_MARKERS,
    BINGX_PREFLIGHT_CODE,
    CLOCK_SKEW_CODE,
    HEDGE_MODE_CODE,
    INSUFFICIENT_BALANCE_CODE,
    MAX_CLOCK_SKEW_MILLISECONDS,
    ONE_WAY_REPAIR,
    ORDERS_KILLED_CODE,
    PREFLIGHT_LEVERAGE,
    PreflightReport,
    RouterBingXClockSkewError,
    RouterBingXHedgeModeError,
    RouterBingXInsufficientBalanceError,
    RouterBingXOrdersKilledError,
    RouterBingXPreflightError,
    is_already_set_answer,
    run_bingx_preflight,
)

#: A local clock the tests pin, so the skew is a fact under the test's
#: control rather of the machine it runs on.
LOCAL_MILLIS = 1_700_000_000_123

#: The identity the planted kill is filed under, so the instruction the
#: refusal carries can be asserted against what the test sent.
KILL_SENDER = "supervisor-under-test"

#: The moment the planted kill was sent, fixed for the same reason.
KILL_SENT_AT = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class _DoubleClient:
    """A stand-in for feature 1's client: canned answers, every call recorded.

    Carries the five endpoints the preflight reads the venue through, so
    the double is a complete face and the suite opens no socket.  The
    ``margin_refusals`` and ``leverage_refusals`` mappings let a test
    make one preparation write answer the way a venue answers a
    no-op — by refusing — so the already-set absorption is exercised
    over the client's own exception type, not a fake one.
    """

    def __init__(
        self,
        *,
        server_time: int = LOCAL_MILLIS,
        positions: object = (),
        balance: object = None,
        margin_refusals: dict[str, Exception] | None = None,
        leverage_refusals: dict[str, Exception] | None = None,
    ) -> None:
        self._server_time = server_time
        self._positions = positions
        self._balance = balance
        self._margin_refusals = margin_refusals or {}
        self._leverage_refusals = leverage_refusals or {}
        self.calls: list[tuple] = []

    def server_time(self) -> int:
        self.calls.append(("server_time",))
        return self._server_time

    def positions(self, symbol: str | None = None) -> object:
        self.calls.append(("positions", symbol))
        return self._positions

    def balance(self) -> object:
        self.calls.append(("balance",))
        return self._balance

    def set_margin_type(
        self, symbol: str, margin_type: str = "ISOLATED"
    ) -> object:
        self.calls.append(("set_margin_type", symbol, margin_type))
        if symbol in self._margin_refusals:
            raise self._margin_refusals[symbol]
        return {}

    def set_leverage(
        self, symbol: str, leverage: int = 1, *, side: str = "BOTH"
    ) -> object:
        self.calls.append(("set_leverage", symbol, leverage, side))
        if symbol in self._leverage_refusals:
            raise self._leverage_refusals[symbol]
        return {}


class _UntouchableClient:
    """A client whose every endpoint is a fault — for the refusals that
    must close the door before the venue is asked anything at all."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def server_time(self) -> int:
        self.calls.append(("server_time",))
        raise AssertionError("a killed order layer asks the venue nothing")

    def positions(self, symbol: str | None = None) -> object:
        self.calls.append(("positions", symbol))
        raise AssertionError("a killed order layer asks the venue nothing")

    def balance(self) -> object:
        self.calls.append(("balance",))
        raise AssertionError("a killed order layer asks the venue nothing")

    def set_margin_type(
        self, symbol: str, margin_type: str = "ISOLATED"
    ) -> object:
        self.calls.append(("set_margin_type", symbol, margin_type))
        raise AssertionError("a killed order layer asks the venue nothing")

    def set_leverage(
        self, symbol: str, leverage: int = 1, *, side: str = "BOTH"
    ) -> object:
        self.calls.append(("set_leverage", symbol, leverage, side))
        raise AssertionError("a killed order layer asks the venue nothing")


def _funded_client(**overrides: object) -> _DoubleClient:
    """A double over an account the book can be placed on.

    A flat one-way account (no positions) with available USDT at or
    above the equity the tests compare against, and the venue's v2
    balance spelling — the document shape the client's own
    ``BALANCE_PATH`` pins.  Every field is overridable, so a test
    states only the fact it is exploring.
    """
    terms: dict[str, object] = {
        "server_time": LOCAL_MILLIS,
        "positions": (),
        "balance": {"balance": {"asset": "USDT", "availableMargin": "10000"}},
    }
    terms.update(overrides)
    return _DoubleClient(**terms)


def _kill_into(url: str) -> None:
    """Plant a standing kill instruction into the channel ``url`` names.

    Sent through the risk member's own verb, so the guard the preflight
    consults reads the same row the supervisor's process would have
    written — the test exercises the seam the feature names, not a
    fake of it.
    """
    send_kill(
        database_url=url,
        sent_at=KILL_SENT_AT,
        supervisor_process_id=KILL_SENDER,
    )


# -- The report -----------------------------------------------------------------


def test_a_passing_preflight_answers_the_three_facts() -> None:
    """The report records the measured skew, the balance and the symbols.

    Feature 2's closing sentence names exactly three facts, and the
    report carries exactly those: the skew as it was measured (signed,
    venue minus local — positive here, the venue ahead), the available
    balance as the exact decimal read off the venue's row, and the
    symbols prepared in the sorted order the preparation walked — the
    book's own symbol order, the same order the plan's legs answer in.
    """
    client = _funded_client(server_time=LOCAL_MILLIS + 40)

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=["ETH-USDT", "BTC-USDT", "SOL-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert isinstance(report, PreflightReport)
    assert report.skew_ms == 40
    assert report.available_usdt == Decimal("10000")
    assert report.symbols == ("BTC-USDT", "ETH-USDT", "SOL-USDT")


def test_preparation_sets_isolated_then_leverage_one_per_symbol() -> None:
    """Each ordered symbol is prepared: margin ISOLATED, then leverage 1.

    The feature's own order — *"sets margin type ISOLATED and leverage
    1"* — is the order the writes reach the venue, symbol by symbol in
    sorted order, margin before leverage, because a leverage change on
    a crossed position is a different risk than the same change on an
    isolated one.  The leverage rides the client's one-way default
    side, which the hedge check has already proved the account holds.
    """
    client = _funded_client()

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=["SOL-USDT", "BTC-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.symbols == ("BTC-USDT", "SOL-USDT")
    assert client.calls == [
        ("server_time",),
        ("positions", None),
        ("balance",),
        ("set_margin_type", "BTC-USDT", "ISOLATED"),
        ("set_leverage", "BTC-USDT", PREFLIGHT_LEVERAGE, "BOTH"),
        ("set_margin_type", "SOL-USDT", "ISOLATED"),
        ("set_leverage", "SOL-USDT", PREFLIGHT_LEVERAGE, "BOTH"),
    ]


def test_duplicate_symbols_prepare_once_in_sorted_order() -> None:
    """A repeated symbol is one preparation, not two.

    The plan holds at most one leg per symbol, so duplicates are a
    caller's spelling of the same ask; the venue holds one margin
    arrangement per symbol either way, and a second identical write is
    the already-set answer by definition.
    """
    client = _funded_client()

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=["BTC-USDT", "ETH-USDT", "BTC-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.symbols == ("BTC-USDT", "ETH-USDT")
    assert [call for call in client.calls if call[0] == "set_margin_type"] == [
        ("set_margin_type", "BTC-USDT", "ISOLATED"),
        ("set_margin_type", "ETH-USDT", "ISOLATED"),
    ]


def test_a_flat_plan_prepares_nothing() -> None:
    """A plan ordering no symbols prepares none and still answers a report.

    A flat plan places nothing, so the preparation — the preflight's
    only side effects — has nothing to do; the report still answers,
    with an empty tuple naming the symbols prepared, because the door
    was asked and the door opened.
    """
    client = _funded_client()

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=[],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.symbols == ()
    assert [call for call in client.calls if "set_" in call[0]] == []


# -- The first refusal: orders_killed ---------------------------------------------


def test_the_kill_guard_refuses_while_a_kill_stands(
    test_database_url: str,
) -> None:
    """A standing kill refuses the preflight before the venue is asked.

    The first of the four, planted through the risk member's own
    ``send_kill`` into the test's isolated channel: the guard the
    feature names raises the risk member's refusal, the preflight
    translates it into the router's vocabulary carrying the standing
    instruction verbatim — which process sent the kill, and when — so
    an operator learns the two facts they ask first, and a caller
    catching ``RouterError`` cannot have a kill pass it by.
    """
    _kill_into(test_database_url)
    client = _UntouchableClient()

    with pytest.raises(RouterBingXOrdersKilledError) as raised:
        run_bingx_preflight(
            client,
            equity_usdt="10000",
            symbols=["BTC-USDT"],
            database_url=test_database_url,
            env={},
            clock=lambda: LOCAL_MILLIS,
        )

    message = str(raised.value)
    assert message.startswith(f"{ORDERS_KILLED_CODE}: ")
    assert KILL_SENDER in message
    assert raised.value.instruction is not None
    assert raised.value.instruction.supervisor_process_id == KILL_SENDER
    assert raised.value.instruction.sent_at == KILL_SENT_AT
    assert client.calls == []


def test_orders_killed_outranks_the_venue_checks(
    test_database_url: str,
) -> None:
    """Every later refusal is closed by the first one.

    The order is a safety lattice: with a kill standing, a skewed
    clock, a hedge-mode account and an unfundable balance all present
    at once, the refusal is the kill's — and no venue request is made
    at all, because a killed order layer must not even ask the venue a
    question.
    """
    _kill_into(test_database_url)
    client = _UntouchableClient()

    with pytest.raises(RouterBingXOrdersKilledError):
        run_bingx_preflight(
            client,
            equity_usdt="10000",
            symbols=["BTC-USDT"],
            database_url=test_database_url,
            env={},
            clock=lambda: LOCAL_MILLIS + 10_000,
        )

    assert client.calls == []


def test_a_deployment_with_no_kill_channel_passes_vacuously() -> None:
    """No store named, no channel — the guard's own vacuous pass, inherited.

    The kill guard passes when nothing names a channel ("no store, no
    status"), and the preflight inherits that stance rather than
    re-deciding it: with no channel there is no supervisor that sent a
    kill through one, so the preflight walks on to the venue checks.
    """
    client = _funded_client()

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=["BTC-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.symbols == ("BTC-USDT",)


def test_a_kill_channel_that_will_not_answer_is_not_no_kill(
    tmp_path,
) -> None:
    """A channel that fails to open refuses — it does not read as empty.

    The guard's store fault arrives as the risk member's own error
    class; the preflight translates it into its own vocabulary because
    a channel that cannot be asked whether a kill stands must not read
    as a channel that answered no — the one direction this seam must
    not fail softly in.
    """
    # A directory parked on the database file's own path: the SQLite
    # open fails before any row can be read, deterministically.
    blocked = tmp_path / "kill-channel.db"
    blocked.mkdir()
    url = f"sqlite:///{blocked}"
    client = _funded_client()

    with pytest.raises(RouterBingXPreflightError) as raised:
        run_bingx_preflight(
            client,
            equity_usdt="10000",
            symbols=["BTC-USDT"],
            database_url=url,
            env={},
            clock=lambda: LOCAL_MILLIS,
        )

    assert str(raised.value).startswith(f"{BINGX_PREFLIGHT_CODE}: ")
    assert "kill channel" in str(raised.value)
    assert client.calls == []


# -- The second refusal: clock_skew -----------------------------------------------


def test_clock_skew_refuses_beyond_one_second_and_reads_nothing_else() -> None:
    """A skew beyond 1000 ms refuses, in either direction, at the second step.

    The venue ahead or behind by more than the signing window's
    tolerance is the same fault — the signatures every later read
    depends on would be refused near the middle of the receive window
    — so both signs refuse, the refusal carries the signed measurement
    with the two readings it was taken between, and the account is not
    read at all: the clock closed the door before the balance question
    could be asked.
    """
    for skew in (1500, -1501):
        client = _funded_client(server_time=LOCAL_MILLIS + skew)

        with pytest.raises(RouterBingXClockSkewError) as raised:
            run_bingx_preflight(
                client,
                equity_usdt="10000",
                symbols=["BTC-USDT"],
                env={},
                clock=lambda: LOCAL_MILLIS,
            )

        assert raised.value.skew_ms == skew
        assert raised.value.server_ms == LOCAL_MILLIS + skew
        assert raised.value.local_ms == LOCAL_MILLIS
        message = str(raised.value)
        assert message.startswith(f"{CLOCK_SKEW_CODE}: ")
        assert str(MAX_CLOCK_SKEW_MILLISECONDS) in message
        assert client.calls == [("server_time",)]


def test_a_skew_of_exactly_the_limit_passes_on_either_side() -> None:
    """The comparison is strict: exactly 1000 ms of difference passes.

    "More than 1000 ms" is the feature's own edge, the same strict
    comparison feature 329's clock-skew halt takes — a host at the
    limit is inside the tolerance, and the report records the signed
    measurement it walked past the door with.
    """
    for skew in (MAX_CLOCK_SKEW_MILLISECONDS, -MAX_CLOCK_SKEW_MILLISECONDS):
        client = _funded_client(server_time=LOCAL_MILLIS + skew)

        report = run_bingx_preflight(
            client,
            equity_usdt="10000",
            symbols=[],
            env={},
            clock=lambda: LOCAL_MILLIS,
        )

        assert report.skew_ms == skew


def test_a_clock_or_server_time_that_is_not_milliseconds_is_refused() -> None:
    """Both readings must be whole milliseconds, or there is no skew in them.

    The measurement is a difference between two clock readings; a
    client double answering prose, or an injected clock answering a
    string, names no reading to difference — a fault of the ask, not a
    measurement of 0 that would silently pass.
    """
    from types import SimpleNamespace

    with pytest.raises(RouterBingXPreflightError) as raised:
        run_bingx_preflight(
            _funded_client(server_time="soon"),
            equity_usdt="10000",
            symbols=[],
            env={},
            clock=lambda: LOCAL_MILLIS,
        )
    assert str(raised.value).startswith(f"{BINGX_PREFLIGHT_CODE}: ")

    with pytest.raises(RouterBingXPreflightError):
        run_bingx_preflight(
            _funded_client(),
            equity_usdt="10000",
            symbols=[],
            env={},
            clock=SimpleNamespace(),  # not callable
        )

    with pytest.raises(RouterBingXPreflightError):
        run_bingx_preflight(
            _funded_client(),
            equity_usdt="10000",
            symbols=[],
            env={},
            clock=lambda: "now",
        )


# -- The third refusal: hedge_mode -------------------------------------------------


def test_hedge_mode_refuses_the_first_long_or_short_position() -> None:
    """Any position reporting LONG or SHORT refuses, with the spec's repair.

    A hedge-mode account holds positions per side while every order the
    plan carries states positionSide BOTH — the venue refuses that
    combination outright — so the first LONG or SHORT the account
    reports closes the door, the refusal carries the position's own
    symbol and side, its message quotes the repair the feature's
    sentence quotes verbatim, and the balance is never read: the
    account's shape closed the door before its size could be asked.
    """
    for side in ("LONG", "SHORT"):
        client = _funded_client(
            positions=(
                {"symbol": "ETH-USDT", "positionSide": "BOTH"},
                {"symbol": "BTC-USDT", "positionSide": side},
            )
        )

        with pytest.raises(RouterBingXHedgeModeError) as raised:
            run_bingx_preflight(
                client,
                equity_usdt="10000",
                symbols=["BTC-USDT"],
                env={},
                clock=lambda: LOCAL_MILLIS,
            )

        assert raised.value.symbol == "BTC-USDT"
        assert raised.value.position_side == side
        message = str(raised.value)
        assert message.startswith(f"{HEDGE_MODE_CODE}: ")
        assert ONE_WAY_REPAIR in message
        assert client.calls == [("server_time",), ("positions", None)]


def test_one_way_positions_and_a_flat_account_pass() -> None:
    """A one-way account — BOTH sides, no positions, or an absent array — passes.

    The hedge test is membership among LONG and SHORT, not equality
    with BOTH: an account whose positions all report BOTH, an account
    holding none, and an account whose document answers no array at
    all are each one-way or flat, and the hedge question is answered
    no for each of them.
    """
    for positions in (
        ({"symbol": "BTC-USDT", "positionSide": "BOTH"},),
        (),
        None,
    ):
        client = _funded_client(positions=positions)

        report = run_bingx_preflight(
            client,
            equity_usdt="10000",
            symbols=["BTC-USDT"],
            env={},
            clock=lambda: LOCAL_MILLIS,
        )

        assert report.symbols == ("BTC-USDT",)


def test_a_positions_document_that_is_not_the_array_is_refused() -> None:
    """The hedge question cannot be asked of a value that is not the array.

    The venue's position document answers an array; an object or a
    string in its place is a payload this module cannot judge, refused
    as a fault of the ask rather than read as a flat account — a
    document that cannot be asked must not answer "no positions".
    """
    for payload in ({"BTC-USDT": "LONG"}, "BTC-USDT:LONG", (1, 2)):
        client = _funded_client(positions=payload)

        with pytest.raises(RouterBingXPreflightError) as raised:
            run_bingx_preflight(
                client,
                equity_usdt="10000",
                symbols=[],
                env={},
                clock=lambda: LOCAL_MILLIS,
            )

        assert str(raised.value).startswith(f"{BINGX_PREFLIGHT_CODE}: ")


# -- The fourth refusal: insufficient_balance ---------------------------------------


def test_insufficient_balance_refuses_below_and_passes_at_equity() -> None:
    """Available below equity refuses; exactly at equity passes.

    "Below" is strict — an account holding exactly the book's equity
    passes, because the book asks for no more than the account has —
    and on the refusal the plan's symbols are prepared not at all: the
    balance closed the door before the venue was asked to hold margin
    arrangements for orders that will never arrive.
    """
    thin = _funded_client(
        balance={"balance": {"asset": "USDT", "availableMargin": "9999.99"}}
    )
    with pytest.raises(RouterBingXInsufficientBalanceError) as raised:
        run_bingx_preflight(
            thin,
            equity_usdt="10000",
            symbols=["BTC-USDT"],
            env={},
            clock=lambda: LOCAL_MILLIS,
        )
    assert raised.value.available_usdt == Decimal("9999.99")
    assert raised.value.equity_usdt == Decimal("10000")
    message = str(raised.value)
    assert message.startswith(f"{INSUFFICIENT_BALANCE_CODE}: ")
    assert thin.calls == [
        ("server_time",),
        ("positions", None),
        ("balance",),
    ]

    exact = _funded_client()
    report = run_bingx_preflight(
        exact,
        equity_usdt=Decimal("10000"),
        symbols=["BTC-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )
    assert report.available_usdt == Decimal("10000")


def test_the_balance_row_is_read_from_either_document_spelling() -> None:
    """The v2 object under ``balance`` and the v3 array both name the account.

    The venue has spelled this one read two ways across the endpoint's
    versions — the object under ``balance`` that the client's pinned
    v2 path answers, and the array keyed by ``asset`` the v3 document
    answers — and the available amount itself as ``availableMargin``
    or the older ``availableBalance``.  All four combinations read the
    same exact decimal, and an unlabelled single array row is the
    account's own: the array spelling with the asset field left empty.
    """
    spellings = (
        {"balance": {"asset": "USDT", "availableMargin": "10000"}},
        {"balance": {"asset": "USDT", "availableBalance": "10000"}},
        ({"asset": "USDT", "availableMargin": "10000"},),
        ({"availableMargin": "10000"},),
    )
    for payload in spellings:
        client = _funded_client(balance=payload)

        report = run_bingx_preflight(
            client,
            equity_usdt="10000",
            symbols=[],
            env={},
            clock=lambda: LOCAL_MILLIS,
        )

        assert report.available_usdt == Decimal("10000")


def test_a_balance_document_naming_no_usdt_row_is_refused() -> None:
    """No USDT row and no available amount name no account the plan could fund.

    A document whose rows name other assets, or whose row carries
    neither spelling of the available amount, describes no account the
    plan could draw on — refused as a fault of the ask, because a zero
    read invented for it would pass an empty account off as a funded
    one.
    """
    for payload in (
        ({"asset": "USDC", "availableMargin": "10000"},),
        ({"asset": "USDT", "balance": "10000"},),
        {"balance": {"asset": "USDT"}},
        {"balances": []},
    ):
        client = _funded_client(balance=payload)

        with pytest.raises(RouterBingXPreflightError) as raised:
            run_bingx_preflight(
                client,
                equity_usdt="10000",
                symbols=[],
                env={},
                clock=lambda: LOCAL_MILLIS,
            )

        assert str(raised.value).startswith(f"{BINGX_PREFLIGHT_CODE}: ")


def test_equity_arriving_as_a_float_is_refused_by_name() -> None:
    """The book's equity obeys the member's money law: no floats.

    The same term the sizer refuses a float for, refused here for the
    same reason — a float is a binary approximation of a decimal no
    book ever spelled, and a term read approximately would compare
    approximately.  A decimal string and a Decimal both read exactly.
    """
    for equity in (10000.0, 10000):
        with pytest.raises(RouterBingXPreflightError) as raised:
            run_bingx_preflight(
                _funded_client(),
                equity_usdt=equity,
                symbols=[],
                env={},
                clock=lambda: LOCAL_MILLIS,
            )
        assert "equity_usdt" in str(raised.value)


# -- The preparation ----------------------------------------------------------------


def test_an_already_set_margin_answer_counts_as_success() -> None:
    """A margin-type refusal saying the state already stands is a success.

    The venue makes a no-op hard to recognize — no dedicated error
    code in its published list — so the judgement reads the refusal's
    own message for the fact.  A refusal whose message says the
    arrangement is already in force is the answer the feature names as
    success, and the symbol is prepared all the same.
    """
    client = _funded_client(
        margin_refusals={
            "BTC-USDT": RouterBingXRefusedError(
                -9010, "Margin type is already ISOLATED"
            )
        }
    )

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=["BTC-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.symbols == ("BTC-USDT",)
    assert ("set_leverage", "BTC-USDT", PREFLIGHT_LEVERAGE, "BOTH") in (
        client.calls
    )


def test_an_already_set_leverage_answer_counts_as_success() -> None:
    """A leverage refusal saying no change is needed is a success too.

    The other spelling of the same no-op — the venue's older phrase
    for it — absorbed by the same marker rule, case-insensitively.
    """
    client = _funded_client(
        leverage_refusals={
            "BTC-USDT": RouterBingXRefusedError(
                80014, "No need to change the leverage"
            )
        }
    )

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=["BTC-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.symbols == ("BTC-USDT",)


def test_an_unrelated_venue_refusal_propagates_with_its_code() -> None:
    """A refusal that does not say "already set" is not swallowed.

    The absorption window is exactly one answer wide: a symbol the
    venue does not know propagates unchanged, in the client's own
    vocabulary with its ``code`` and ``msg`` still on it — a caller
    deciding what a refused preparation means reads those off the
    venue's own refusal — and the report is never answered, so no
    caller is told a symbol was prepared the venue refused to hold.
    """
    refusal = RouterBingXRefusedError(
        109425, "The trading pair does not exist or is not supported"
    )
    client = _funded_client(margin_refusals={"BTC-USDT": refusal})

    with pytest.raises(RouterBingXRefusedError) as raised:
        run_bingx_preflight(
            client,
            equity_usdt="10000",
            symbols=["BTC-USDT"],
            env={},
            clock=lambda: LOCAL_MILLIS,
        )

    assert raised.value is refusal


def test_the_already_set_markers_are_the_two_spellings_of_the_fact() -> None:
    """The predicate reads the refusal's message, case-insensitively.

    Both markers — the venue's "already" phrasings and the older "no
    need to change" one — match in any case, and anything that is not
    a refusal carrying a textual ``msg`` answers False: a value the
    predicate cannot judge is not an answer the preflight absorbs.
    """
    for msg in (
        "Margin type is already ISOLATED",
        "no need to change the margin type",
    ):
        assert is_already_set_answer(RouterBingXRefusedError(1, msg))
    assert not is_already_set_answer(
        RouterBingXRefusedError(109425, "The trading pair does not exist")
    )
    # A plain exception carries no ``msg`` — the client refusal's own
    # field — so it is not an answer this predicate can judge, and it
    # answers False rather than being read through ``str()``: the
    # absorption window is the client's vocabulary and nothing wider.
    assert not is_already_set_answer(Exception("ALREADY isolated"))
    assert not is_already_set_answer("already isolated")
    assert ALREADY_SET_MSG_MARKERS == ("already", "no need to change")


# -- The ask ------------------------------------------------------------------------


def test_the_client_face_is_required_up_front() -> None:
    """A client missing an endpoint is a fault of the ask, named before any check.

    The preflight reads the venue only through the five endpoints it
    names, and re-implements none of them; a client missing one is
    refused up front rather than unwinding an AttributeError from the
    middle of the ordered checks.
    """
    from types import SimpleNamespace

    incomplete = SimpleNamespace(
        server_time=lambda: LOCAL_MILLIS,
        positions=lambda symbol=None: (),
        balance=lambda: {},
        set_margin_type=lambda symbol, margin_type="ISOLATED": {},
    )

    with pytest.raises(RouterBingXPreflightError) as raised:
        run_bingx_preflight(
            incomplete,
            equity_usdt="10000",
            symbols=[],
            env={},
            clock=lambda: LOCAL_MILLIS,
        )

    assert "set_leverage" in str(raised.value)


def test_symbols_that_name_nothing_are_refused() -> None:
    """A symbol that is not non-empty text prepares nothing and is refused.

    The preparation would only forward such a value to the venue to be
    refused there; a local refusal names the caller's own value
    instead.  A bare string is refused too — it is one value, not an
    iterable of the plan's symbols, and a plan of one character is no
    plan any book spelled.
    """
    for symbols in (("BTC-USDT", 42), ("",), (" ",), "BTC-USDT", 7):
        with pytest.raises(RouterBingXPreflightError) as raised:
            run_bingx_preflight(
                _funded_client(),
                equity_usdt="10000",
                symbols=symbols,
                env={},
                clock=lambda: LOCAL_MILLIS,
            )
        assert str(raised.value).startswith(f"{BINGX_PREFLIGHT_CODE}: ")


def test_no_socket_is_opened_by_a_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With socket creation patched to raise, the preflight still answers.

    The module's own proof, the same one Stage 0's command pins for
    itself: the preflight holds no transport, no credentials and no
    host — every venue fact arrives through the client it is handed —
    so a socket that cannot open stops nothing.
    """

    def _refused(*args: object, **kwargs: object) -> None:
        raise AssertionError("the preflight opened a socket")

    monkeypatch.setattr("socket.socket", _refused)
    client = _funded_client()

    report = run_bingx_preflight(
        client,
        equity_usdt="10000",
        symbols=["BTC-USDT"],
        env={},
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.symbols == ("BTC-USDT",)
