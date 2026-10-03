"""Tests for :mod:`router.bingx_mirror` — the command's own behaviour.

Feature 4 of additions_spec_bingx_vst_mirror.xml, held clause by clause:

*It fetches the contracts and premiumIndex documents from VST, replaces the
book's positions with the account's live VST positions, and builds the plan
with dry_run_plan.  Without ``--place`` it prints the plan in Stage 0's
JSON-lines format and exits 0 while placing nothing.  With ``--place`` it
requires ``DATABASE_URL`` and runs the preflight.  Then it places each order
through RouterOrderPlacementStore.place, acquiring RouterRateLimiter weight
and retrying 429s with retry_rate_limited.  It prints one JSON line per leg:
placed, prior (already placed), or refused with its code.  It exits 0 when
every order was placed or was already placed, and 1 otherwise.  When a POST
/trade/order times out or its connection drops, the outcome is unknown.  The
mirror then queries that clientOrderID before doing anything else.  A found
order is recorded as placed, and only a not_found answer is re-posted, so a
blind retry never meets BingX's duplicate-clientOrderID refusal for an order
that actually landed.  ``--status`` prints feature 3's read-back, and
``--cancel`` cancels the rebalance's open orders.*

Every test injects a client double, a store and a limiter — no test opens a
socket.  The fixtures are inputs and are never edited; the plan is read
through :func:`router.bingx_dry_run.dry_run_plan` exactly as the mirror
builds it.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from router.bingx_client import (
    ORDER_NOT_FOUND_CODE,
    VST_HOST,
    RouterBingXRefusedError,
    RouterBingXTransportError,
)
from router.bingx_mirror import (
    DATABASE_URL_MISSING_CODE,
    MIRROR_CODE,
    MIRROR_OUTCOME_PLACED,
    MIRROR_OUTCOME_PRIOR,
    MIRROR_OUTCOME_REFUSED,
    PLACEMENT_FIELD,
    VST_MIRROR_WEIGHT_SCHEDULE,
    MirrorLeg,
    RouterBingXMirrorError,
    _full_identifier,
    build_mirror_plan,
    live_positions,
    main,
    mirror_place,
)
from router.bingx_order import BingXOrder, BingXRefusedLeg
from router.errors import RouterRateLimitedError
from router.limiter import (
    DEFAULT_WEIGHT_SCOPE,
    OPERATION_PLACE_ORDER,
    OPERATION_QUERY_ORDER,
    RateLimitHeadroom,
)
from router.retry import RetryEventLog
from router.submission_result import RouterOrderPlacementStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: A local clock the tests pin; the preflight compares it against the
#: double's server time, which the tests keep equal so no skew is refused.
LOCAL_MILLIS = 1_700_000_000_123

#: The venue's well-formed account payloads the preflight reads.  The
#: balance is comfortably above the synthetic book's 10000 USDT equity.
BALANCE = {"balance": {"asset": "USDT", "availableMargin": "100000"}}


def _clock() -> int:
    """The pinned local clock the preflight's skew is measured against."""
    return LOCAL_MILLIS


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _book() -> dict:
    return _load("synthetic_book.json")


class _MirrorClient:
    """A stand-in for feature 1's client: canned documents, recorded calls.

    Carries every face the mirror and the preflight read the venue through,
    so the double is a complete stand-in and no test opens a socket.
    ``place_effects`` is a list of callables consumed one per
    ``place_order`` call — each either returns (the venue took the order) or
    raises — so a test can stage a transport failure, a venue refusal or a
    429 on any attempt.  ``orders_held`` names the clientOrderIDs the venue
    claims to hold, which ``query_order`` answers for; everything else is
    the not-found refusal feature 3 translates.
    """

    def __init__(
        self,
        *,
        contracts: object = None,
        marks: object = None,
        positions: object = (),
        server_time: int = LOCAL_MILLIS,
        balance: object = BALANCE,
        place_effects: list | None = None,
        orders_held: set[str] | None = None,
        open_orders: object = (),
    ) -> None:
        self._contracts = _load("contracts.json") if contracts is None else contracts
        self._marks = _load("premium_index.json") if marks is None else marks
        self._positions = positions
        self._server_time = server_time
        self._balance = balance
        self._place_effects = list(place_effects or [])
        self._orders_held = set(orders_held or ())
        self._open_orders = open_orders
        self.calls: list[tuple] = []
        self.placed: list[BingXOrder] = []

    # -- The mirror's three reads -------------------------------------------
    def contracts(self) -> object:
        self.calls.append(("contracts",))
        return self._contracts

    def premium_index(self) -> object:
        self.calls.append(("premium_index",))
        return self._marks

    def positions(self, symbol: str | None = None) -> object:
        self.calls.append(("positions", symbol))
        return self._positions

    # -- The preflight's five faces -----------------------------------------
    def server_time(self) -> int:
        self.calls.append(("server_time",))
        return self._server_time

    def position_mode(self) -> bool:
        # One-way: the state every account these tests place on holds.
        self.calls.append(("position_mode",))
        return False

    def balance(self) -> object:
        self.calls.append(("balance",))
        return self._balance

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> object:
        self.calls.append(("set_margin_type", symbol, margin_type))
        return {}

    def set_leverage(
        self, symbol: str, leverage: int = 1, *, side: str = "BOTH"
    ) -> object:
        self.calls.append(("set_leverage", symbol, leverage, side))
        return {}

    # -- The order path ------------------------------------------------------
    def place_order(self, order: BingXOrder) -> object:
        self.calls.append(("place_order", order.symbol))
        self.placed.append(order)
        if self._place_effects:
            effect = self._place_effects.pop(0)
            return effect()
        return {"orderId": order.symbol}

    def query_order(self, client_order_id: str, *, symbol: str | None = None) -> object:
        self.calls.append(("query_order", client_order_id, symbol))
        if client_order_id in self._orders_held:
            return {
                "symbol": symbol,
                "clientOrderID": client_order_id,
                "status": "NEW",
                "executedQty": "0",
                "avgPrice": "0",
            }
        raise RouterBingXRefusedError(ORDER_NOT_FOUND_CODE, "order does not exist")

    def open_orders(self, symbol: str | None = None) -> object:
        self.calls.append(("open_orders", symbol))
        return self._open_orders

    def cancel_order(self, client_order_id: str, *, symbol: str | None = None) -> object:
        self.calls.append(("cancel_order", client_order_id, symbol))
        return {}


def _rate_limited(operation: str = OPERATION_PLACE_ORDER) -> RouterRateLimitedError:
    """A well-formed rate-limit refusal, as feature 1 raises on a 429.

    Every field a :class:`RateLimitHeadroom` requires, so the refusal
    carries a reading feature 319's backoff can pace — the shape feature 1
    raises when the venue answers HTTP 429.
    """
    reading = RateLimitHeadroom(
        scope=DEFAULT_WEIGHT_SCOPE,
        operation=operation,
        weight=1,
        allowed=False,
        remaining=0,
        capacity=VST_MIRROR_WEIGHT_SCHEDULE.allowance,
        accrued=0,
        observed_at=datetime.now(UTC),
        schedule=VST_MIRROR_WEIGHT_SCHEDULE,
    )
    return RouterRateLimitedError(
        f"rate_limited: the venue refused {operation!r}", headroom=reading
    )


class _CountingLimiter:
    """A limiter double: records every acquire, meters nothing.

    The mirror's law is that every send — every attempt, including a
    re-send — prices itself through :meth:`RouterRateLimiter.acquire`.  The
    suite proves exactly that by counting the calls; the real bucket is
    exercised end to end elsewhere, and using it here would make the store
    and the limiter contend for one sqlite file while a placement is still
    open.  A 429 in these tests is raised by the *venue* — feature 1's
    refusal, out of ``place_order`` — which is what the backoff absorbs and
    what makes the re-send re-acquire.
    """

    def __init__(self) -> None:
        self.operations: list[str] = []

    def acquire(self, operation: str, *, now: datetime | None = None):
        self.operations.append(operation)
        return object()


def _transport_unknown() -> RouterBingXTransportError:
    """A write whose response never arrived — the unknown outcome."""
    return RouterBingXTransportError(
        "POST", f"https://{VST_HOST}/openApi/swap/v2/trade/order",
        "socket timed out", outcome_unknown=True,
    )


def _plan(client: _MirrorClient, book: dict | None = None) -> list:
    return build_mirror_plan(book=book or _book(), client=client)


def _order_symbols(plan: list) -> list[str]:
    return [leg.symbol for leg in plan if isinstance(leg, BingXOrder)]


# -- Reading the plan ----------------------------------------------------------


def test_plan_fetches_the_venues_own_documents_once_each():
    client = _MirrorClient()
    _plan(client)
    fetches = [c for c in client.calls if c[0] in ("contracts", "premium_index")]
    assert fetches == [("contracts",), ("premium_index",)]


def test_plan_reads_the_accounts_live_positions():
    client = _MirrorClient()
    _plan(client)
    assert ("positions", None) in client.calls


def test_flat_account_yields_five_orders_and_two_refusals():
    plan = _plan(_MirrorClient())
    assert _order_symbols(plan) == [
        "1000PEPE-USDT", "BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT"
    ]
    refusals = {
        leg.symbol: leg.code for leg in plan if isinstance(leg, BingXRefusedLeg)
    }
    assert refusals == {
        "AGLD-USDT": "below_min_notional",
        "NCFXUSD2ARS-USDT": "not_tradable",
    }


def test_replaced_positions_change_the_sized_delta():
    """A held BTC position is subtracted from its target, unlike a flat one."""
    flat = {leg.symbol: leg for leg in _plan(_MirrorClient())}
    held = {
        leg.symbol: leg
        for leg in _plan(
            _MirrorClient(
                positions=[{"symbol": "BTC-USDT", "positionAmt": "0.0100"}]
            )
        )
        if isinstance(leg, BingXOrder)
    }
    assert flat["BTC-USDT"].quantity != held["BTC-USDT"].quantity


def test_the_book_document_is_never_mutated():
    book = _book()
    original = dict(book)
    _plan(_MirrorClient(), book=book)
    assert book == original
    assert book["positions"] == {"BTC-USDT": "0.0100"}


def test_the_plan_uses_the_venues_marks_not_the_books_positions():
    """A held position the book never states is still sized away."""
    client = _MirrorClient(
        positions=[{"symbol": "ETH-USDT", "positionAmt": "-0.5"}]
    )
    orders = {leg.symbol: leg for leg in _plan(client) if isinstance(leg, BingXOrder)}
    # ETH's book weight is -0.15; with 0.5 already held short the delta is
    # smaller than the flat-account delta would be.
    flat = {leg.symbol: leg for leg in _plan(_MirrorClient()) if isinstance(leg, BingXOrder)}
    assert orders["ETH-USDT"].quantity != flat["ETH-USDT"].quantity


def test_a_non_mapping_book_is_refused():
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        build_mirror_plan(book=[], client=_MirrorClient())
    assert MIRROR_CODE in str(excinfo.value)


# -- Live positions ------------------------------------------------------------


def test_live_positions_none_is_a_flat_account():
    assert live_positions(_MirrorClient(positions=None)) == {}


def test_live_positions_reads_the_position_amt_spelling():
    client = _MirrorClient(
        positions=[{"symbol": "BTC-USDT", "positionAmt": "-0.0100"}]
    )
    assert live_positions(client) == {"BTC-USDT": "-0.0100"}


def test_live_positions_reads_the_older_position_spelling():
    client = _MirrorClient(positions=[{"symbol": "DOGE-USDT", "position": "12"}])
    assert live_positions(client) == {"DOGE-USDT": "12"}


def test_live_positions_refuses_a_float_size():
    client = _MirrorClient(positions=[{"symbol": "BTC-USDT", "positionAmt": 0.01}])
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_row_without_a_symbol():
    client = _MirrorClient(positions=[{"positionAmt": "1"}])
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_row_without_a_size():
    client = _MirrorClient(positions=[{"symbol": "BTC-USDT"}])
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_non_array_payload():
    client = _MirrorClient(positions={"BTC-USDT": "1"})
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_client_without_the_method():
    class Bare:
        pass

    with pytest.raises(RouterBingXMirrorError):
        live_positions(Bare())


# -- The full identifier -------------------------------------------------------


def test_full_identifier_is_sixty_four_hex_and_prefixes_the_projection():
    book = _book()
    for leg in _plan(_MirrorClient()):
        if isinstance(leg, BingXOrder):
            full = _full_identifier(book, leg.symbol)
            assert len(full) == 64
            assert full.startswith(leg.client_order_id)


def test_full_identifier_needs_a_book_id():
    with pytest.raises(RouterBingXMirrorError):
        _full_identifier({"rebalance_ts": "2026-09-30T00:00:00+00:00"}, "BTC-USDT")


def test_full_identifier_refuses_a_naive_rebalance():
    with pytest.raises(RouterBingXMirrorError):
        _full_identifier(
            {"book_id": "b", "rebalance_ts": "2026-09-30T00:00:00"}, "BTC-USDT"
        )


# -- mirror_place: the happy path ---------------------------------------------


def _place(client, plan, store, limiter, book=None, **kwargs):
    return mirror_place(
        client=client,
        book=book or _book(),
        plan=plan,
        store=store,
        limiter=limiter,
        database_url=kwargs.pop("database_url", "sqlite:///:memory:"),
        clock=kwargs.pop("clock", _clock),
        sleep=kwargs.pop("sleep", lambda _d: None),
        **kwargs,
    )


def test_place_runs_the_preflight_before_any_order_leaves(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    first_place = next(
        i for i, call in enumerate(client.calls) if call[0] == "place_order"
    )
    # Every preflight read precedes the first placement.
    for read in ("server_time", "balance", "set_margin_type", "set_leverage"):
        assert any(call[0] == read for call in client.calls[:first_place])


def test_place_sends_each_order_once_and_reports_placed(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert len(client.placed) == 5
    assert all(o.outcome == MIRROR_OUTCOME_PLACED for o in outcomes.values())
    assert set(outcomes) == set(_order_symbols(_plan(_MirrorClient())))


def test_a_second_place_sends_nothing_and_reports_prior(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    assert len(client.placed) == 5

    second = _MirrorClient()
    outcomes = _place(
        second, _plan(second), store, limiter, database_url=test_database_url
    )
    assert second.placed == []
    assert all(o.outcome == MIRROR_OUTCOME_PRIOR for o in outcomes.values())


def test_the_weight_is_acquired_once_per_send(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    assert limiter.operations == [OPERATION_PLACE_ORDER] * 5


def test_a_refused_leg_is_not_placed_but_its_siblings_are(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    plan = _plan(client)
    outcomes = _place(client, plan, store, limiter, database_url=test_database_url)
    placed_symbols = set(outcomes)
    refused = {
        leg.symbol for leg in plan if isinstance(leg, BingXRefusedLeg)
    }
    assert placed_symbols.isdisjoint(refused)


# -- mirror_place: refusals and the rate limit ---------------------------------


def test_a_venue_refusal_is_reported_with_its_code(test_database_url):
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101204, "insufficient margin")
        )]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    first = outcomes["1000PEPE-USDT"]
    assert first.outcome == MIRROR_OUTCOME_REFUSED
    assert first.code == "101204"


def test_a_rate_limited_send_is_retried_and_succeeds(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_rate_limited())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_PLACED
    # The refused attempt plus the re-send: two places for the first leg.
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 2


def test_a_retried_send_re_acquires_the_weight(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_rate_limited())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    # Five legs, six sends: the retried leg acquired twice.
    assert limiter.operations.count(OPERATION_PLACE_ORDER) == 6


def test_every_retry_emits_one_event(test_database_url):
    log = RetryEventLog()
    client = _MirrorClient(
        place_effects=[
            lambda: (_ for _ in ()).throw(_rate_limited()),
            lambda: (_ for _ in ()).throw(_rate_limited()),
        ]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(
        client, _plan(client), store, limiter,
        database_url=test_database_url, on_retry=log.record,
    )
    assert len(log) == 2


def test_an_exhausted_budget_reports_refused(test_database_url):
    client = _MirrorClient(
        place_effects=[
            lambda: (_ for _ in ()).throw(_rate_limited())
            for _ in range(4)
        ]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter,
        database_url=test_database_url, retries=3,
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_REFUSED


# -- The unknown outcome -------------------------------------------------------


def test_an_unknown_outcome_found_on_the_venue_is_placed_and_not_reposted(
    test_database_url,
):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())])
    order_id = _plan(client)[0].client_order_id
    client._orders_held.add(order_id)
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_PLACED
    # Exactly one POST for that leg: the failure was resolved by asking.
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 1
    assert ("query_order", order_id, "1000PEPE-USDT") in client.calls


def test_an_unknown_outcome_not_found_is_reposted(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_PLACED
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 2


def test_the_query_precedes_the_repost(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    leg_calls = [
        call for call in client.calls
        if call[0] in ("place_order", "query_order")
        and "1000PEPE-USDT" in call
    ]
    assert [call[0] for call in leg_calls] == [
        "place_order", "query_order", "place_order"
    ]


def test_an_unknown_outcome_never_found_twice_is_refused(test_database_url):
    """A venue that keeps dropping the connection is not re-sent forever."""
    client = _MirrorClient(
        place_effects=[
            lambda: (_ for _ in ()).throw(_transport_unknown()),
            lambda: (_ for _ in ()).throw(_transport_unknown()),
        ]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_REFUSED
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 2


def test_a_read_transport_failure_is_refused_without_a_repost(test_database_url):
    """A GET whose connection failed cannot be resolved by asking again."""
    def fail_read(*_args, **_kwargs):
        raise RouterBingXTransportError(
            "GET", f"https://{VST_HOST}/openApi/swap/v2/trade/order",
            "connection reset", outcome_unknown=False,
        )

    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())]
    )
    client.query_order = fail_read  # type: ignore[assignment]
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    # The unresolved write is a refused leg, never a second POST.
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_REFUSED
    assert outcomes["1000PEPE-USDT"].code == "RouterBingXTransportError"
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 1
    # The siblings are unaffected: the failure is one leg's, not the run's.
    assert outcomes["BTC-USDT"].outcome == MIRROR_OUTCOME_PLACED


def test_a_refused_order_is_not_recorded_in_the_store(test_database_url):
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101204, "insufficient margin")
        )]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    key = _full_identifier(_book(), "1000PEPE-USDT")
    assert store.prior_result(key) is None


# -- MirrorLeg ---------------------------------------------------------------


def test_mirror_leg_refuses_an_unknown_outcome_word():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(symbol="BTC-USDT", outcome="maybe")


def test_mirror_leg_refuses_a_refusal_without_a_code():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(symbol="BTC-USDT", outcome=MIRROR_OUTCOME_REFUSED)


def test_mirror_leg_refuses_a_code_on_a_placed_leg():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(symbol="BTC-USDT", outcome=MIRROR_OUTCOME_PLACED, code="x")


# -- main: the command ---------------------------------------------------------


def _run_main(argv, **kwargs) -> tuple[int, str, str]:
    kwargs.setdefault("clock", _clock)
    kwargs.setdefault("sleep", lambda _d: None)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv, **kwargs)
    return code, out.getvalue(), err.getvalue()


def test_without_place_prints_the_plan_and_places_nothing(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient()
    code, out, err = _run_main(["--book", str(book_path)], client=client)
    assert code == 0
    assert client.placed == []
    lines = [json.loads(line) for line in out.splitlines()]
    assert len(lines) == 7
    orders = [line for line in lines if "clientOrderID" in line]
    refusals = [line for line in lines if "refusal" in line]
    assert len(orders) == 5
    assert len(refusals) == 2
    assert err == ""


def test_the_plan_lines_are_stage_zeros_parameters(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    code, out, _ = _run_main(["--book", str(book_path)], client=_MirrorClient())
    assert code == 0
    btc = next(
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get("symbol") == "BTC-USDT"
    )
    assert btc == {
        "symbol": "BTC-USDT",
        "side": "BUY",
        "positionSide": "BOTH",
        "type": "LIMIT",
        "quantity": "0.0240",
        "price": "83137.3",
        "timeInForce": "PostOnly",
        "clientOrderID": _full_identifier(_book(), "BTC-USDT")[:40],
    }


def test_place_without_database_url_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient()
    code, out, err = _run_main(
        ["--book", str(book_path), "--place"], client=client, env={}
    )
    assert code == 1
    assert out == ""
    assert DATABASE_URL_MISSING_CODE in err
    assert client.placed == []


def test_place_prints_placed_and_exits_zero(tmp_path, test_database_url):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient()
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    code, out, err = _run_main(
        ["--book", str(book_path), "--place"],
        client=client,
        store=store,
        limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 0
    assert err == ""
    placed = [
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get(PLACEMENT_FIELD) == MIRROR_OUTCOME_PLACED
    ]
    assert len(placed) == 5


def test_a_second_place_prints_prior_for_all_five(tmp_path, test_database_url):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    _run_main(
        ["--book", str(book_path), "--place"],
        client=_MirrorClient(), store=store, limiter=limiter,
        database_url=test_database_url,
    )
    second = _MirrorClient()
    code, out, _ = _run_main(
        ["--book", str(book_path), "--place"],
        client=second, store=store, limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 0
    assert second.placed == []
    priors = [
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get(PLACEMENT_FIELD) == MIRROR_OUTCOME_PRIOR
    ]
    assert len(priors) == 5


def test_place_refused_leg_exits_one(tmp_path, test_database_url):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101204, "insufficient margin")
        )]
    )
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    code, out, _ = _run_main(
        ["--book", str(book_path), "--place"],
        client=client, store=store, limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 1
    refused = [
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get(PLACEMENT_FIELD) == MIRROR_OUTCOME_REFUSED
    ]
    assert refused and refused[0]["code"] == "101204"


def test_status_prints_the_read_back(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    plan = _plan(_MirrorClient())
    held = {leg.client_order_id for leg in plan if isinstance(leg, BingXOrder)}
    client = _MirrorClient(orders_held=held)
    code, out, err = _run_main(
        ["--book", str(book_path), "--status"], client=client
    )
    assert code == 0
    assert err == ""
    lines = [json.loads(line) for line in out.splitlines()]
    assert len(lines) == 5
    assert all(line["status"] == "NEW" for line in lines)


def test_cancel_prints_the_identifiers_it_cancelled(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    plan = _plan(_MirrorClient())
    owned = [leg.client_order_id for leg in plan if isinstance(leg, BingXOrder)]
    open_orders = [
        {"clientOrderID": owned[0], "symbol": "1000PEPE-USDT"},
        {"clientOrderID": "a" * 40, "symbol": "OTHER-USDT"},
    ]
    client = _MirrorClient(open_orders=open_orders)
    code, out, err = _run_main(
        ["--book", str(book_path), "--cancel"], client=client
    )
    assert code == 0
    assert err == ""
    cancelled = [json.loads(line)["clientOrderID"] for line in out.splitlines()]
    assert cancelled == [owned[0]]
    # The foreign order was never handed to the venue's cancel.
    assert ("cancel_order", "a" * 40, "OTHER-USDT") not in client.calls


def test_a_missing_book_path_refuses(tmp_path):
    client = _MirrorClient()
    code, out, err = _run_main(
        ["--book", str(tmp_path / "absent.json")], client=client
    )
    assert code == 1
    assert out == ""
    assert MIRROR_CODE in err
    assert client.calls == []


def test_a_book_that_is_not_json_refuses(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text("not json", encoding="utf-8")
    code, _out, err = _run_main(["--book", str(book_path)], client=_MirrorClient())
    assert code == 1
    assert MIRROR_CODE in err


def test_the_schedule_is_the_one_the_integration_points_name():
    assert VST_MIRROR_WEIGHT_SCHEDULE.allowance == 10
    assert VST_MIRROR_WEIGHT_SCHEDULE.window == timedelta(seconds=1)
    for operation in (
        OPERATION_PLACE_ORDER,
        OPERATION_QUERY_ORDER,
        "cancel_order",
        "open_orders",
        "account",
    ):
        assert VST_MIRROR_WEIGHT_SCHEDULE.weight_for(operation) == 1
