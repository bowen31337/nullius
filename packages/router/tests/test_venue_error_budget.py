"""Tests for the venue's error budget — bug 2 of ``bug_spec_vst_slot_resilience.xml``.

The live incident: the 2026-10-20T16:00 UTC slot read back the previous
slot's 70 orders one ``GET /trade/order`` at a time, the venue answered
``109421`` (*order not exist*) for the legs that never landed, and after
twenty of those answers inside 480 s it answered code ``109429`` — its
per-API **error budget** — with *"can retry after time: 1792512797246"*.
Feature 1 treated that envelope as an ordinary ``bingx_refused`` refusal,
so the read-back aborted, the slot exited 1 with nothing else in the
journal, and the key stayed blocked for minutes.

Three repairs, one per clause of the spec's expected section, each held
here by its own test:

* **the client reads the budget.**  A venue envelope carrying code 109429
  is raised as the same :class:`~router.errors.RouterRateLimitedError` a
  HTTP 429 already produces — with ``retry_after`` derived from the
  message's ``can retry after time: EPOCH_MS`` (seconds from the client's
  own clock, floored at zero) and the token-bucket default when the
  message names no instant.  The recorded answer is the new live fixture
  ``live/query_order_error_budget.json``, quoted verbatim.
* **the read-back walks on a budget of its own.**
  :func:`~router.bingx_orders.read_back_orders` takes a keyword-only
  ``not_found_budget`` (default 15): after that many ``not_found``
  answers in one call it stops asking and reports every remaining order
  ``VST_ORDER_UNREAD`` — a status that is neither found nor not_found,
  so a caller that reduces statuses counts it as *not reconciled this
  slot* rather than as a fill or a miss.
* **the slot names the step that was refused.**  Every
  :class:`~router.bingx_client.RouterBingXRefusedError` or
  :class:`~router.errors.RouterRateLimitedError` a step raises is logged
  at info as one greppable line before it propagates; a rate-limit
  refusal from the cancel or the reconcile step is *skipped* — recorded
  in the report as ``cancel_skipped`` / ``reconciled: false`` — and the
  slot still places, because a budget that returns in minutes must not
  cost the book four hours of drift.  A rate-limit refusal from the
  guard, the preflight or the placement still ends the slot with exit 1:
  placing against an unknown account state is the one thing the slot
  must not do.

No test opens a socket: the client tests inject a transport serving the
recorded fixture, the read-back test drives feature 1's real client over
a scripted transport, and the slot tests ride the mirror suite's
recording double with one face answering from the recorded envelope.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from router.bingx_client import (
    VENUE_ERROR_BUDGET_CODE,
    VST_WEIGHT_ALLOWANCE,
    VST_WEIGHT_WINDOW,
    BingXClient,
)
from router.bingx_orders import (
    DEFAULT_NOT_FOUND_BUDGET,
    ORDER_NOT_FOUND_CODES,
    VST_ORDER_NOT_FOUND,
    VST_ORDER_UNREAD,
    read_back_orders,
)
from router.bingx_rebalance import (
    BINGX_REBALANCE_CODE,
    EXIT_OK,
    EXIT_REFUSED,
)
from router.errors import RouterRateLimitedError

# The doubles this member's suites already prove the mirror and the slot
# against, reused rather than re-written — and the funded balance and the
# one-slot driver of the rebalance suite, so a slot test here differs from
# its siblings only in the face that answers from the error budget.
from test_bingx_mirror import _CountingLimiter, _MirrorClient  # isort: skip
from test_bingx_rebalance import (  # isort: skip
    _client,
    _funded_balance,
    _run,
    _write_book,
)

LIVE = Path(__file__).resolve().parent / "fixtures" / "bingx_vst" / "live"

#: The fixture's own retry instant, ``can retry after time: 1792512797246``
#: — the epoch-ms figure the parsed ``retry_after`` is derived from.
RETRY_AT_MS = 1_792_512_797_246

#: The client's pinned clock, ten seconds before the venue's retry instant:
#: a wait the fixture's own message states, so the parse is checked against
#: a figure the venue actually sent rather than one the test chose.
FIXED_MILLIS = RETRY_AT_MS - 10_000

#: The token-bucket default wait for one refused request of weight one:
#: the VST schedule's refill interval (its window over its allowance).
BUCKET_DEFAULT_WAIT = VST_WEIGHT_WINDOW / VST_WEIGHT_ALLOWANCE

#: Fake credentials, as the client suite coins — values, never secrets.
API_KEY = "vst-key-0123456789"
SECRET_KEY = "vst-secret-abcdef"


def _error_budget_body() -> bytes:
    """The recorded error-budget envelope, verbatim, as response bytes."""
    return (LIVE / "query_order_error_budget.json").read_bytes()


def _venue_client(body: bytes, *, clock_ms: int = FIXED_MILLIS) -> BingXClient:
    """Feature 1's real client over a transport answering ``body`` forever.

    The client is the real one — signing, host guard and envelope reading
    included — so the refusal a test catches is exactly the refusal a
    deployment would, class, code and parsed wait alike.  No socket opens:
    the transport is the test's own stand-in.
    """
    return BingXClient(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        transport=lambda method, url, headers, payload: (200, body),
        clock=lambda: clock_ms,
    )


def _error_budget_refusal() -> RouterRateLimitedError:
    """The refusal feature 1 raises for the recorded envelope, raised once.

    Built through the real client so the slot tests' double answers with
    the refusal a deployment actually sees — carrying the venue's own code
    and the parsed wait — rather than a hand-shaped stand-in.
    """
    try:
        _venue_client(_error_budget_body()).query_order("a" * 40)
    except RouterRateLimitedError as refusal:
        return refusal
    raise AssertionError("the recorded error-budget envelope did not refuse")


class _RateLimitedFaceClient(_MirrorClient):
    """The mirror's recording client with one face answering from the budget.

    ``refuse`` names the face — ``balance``, ``open_orders`` or
    ``query_order`` — that raises the recorded error-budget refusal (as
    feature 1 raises it) instead of its document, so a slot test can stage
    the 109429 on exactly the step it is about and watch every other step
    still run.  Every other face answers the way the parent double does.
    """

    def __init__(self, *, refuse: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._refuse = refuse
        self._refusal = _error_budget_refusal()

    def balance(self) -> object:
        if self._refuse == "balance":
            self.calls.append(("balance",))
            raise self._refusal
        return super().balance()

    def open_orders(self, symbol: str | None = None) -> object:
        if self._refuse == "open_orders":
            self.calls.append(("open_orders", symbol))
            raise self._refusal
        return super().open_orders(symbol)

    def query_order(self, client_order_id: str, *, symbol: str | None = None) -> object:
        if self._refuse == "query_order":
            self.calls.append(("query_order", client_order_id, symbol))
            raise self._refusal
        return super().query_order(client_order_id, symbol=symbol)


# -- The client reads the venue's error budget ---------------------------------


def test_the_error_budget_envelope_raises_the_rate_limit_refusal() -> None:
    """Code 109429 is a rate limit, not a bingx_refused — the class a 429 raises.

    The recorded answer arrives as an ordinary HTTP 200 envelope, so the
    code is the only mark that names it; reading it as an ordinary refusal
    is the defect the 2026-10-20T16:00 slot printed.
    """
    with pytest.raises(RouterRateLimitedError) as raised:
        _venue_client(_error_budget_body()).query_order("a" * 40)

    refusal = raised.value
    assert refusal.retry_after == timedelta(seconds=10)
    # The venue's own code travels on the refusal, so the slot's log line
    # can name it without parsing the message.
    assert getattr(refusal, "venue_code", None) == VENUE_ERROR_BUDGET_CODE
    assert "109429" in str(refusal)


@pytest.mark.parametrize("code", [VENUE_ERROR_BUDGET_CODE, str(VENUE_ERROR_BUDGET_CODE)])
def test_both_spellings_of_the_budget_code_are_the_same_refusal(code) -> None:
    """The venue has sent its codes as integers and as strings across versions."""
    envelope = json.loads(_error_budget_body())
    envelope["code"] = code
    body = json.dumps(envelope).encode("utf-8")

    with pytest.raises(RouterRateLimitedError):
        _venue_client(body).query_order("a" * 40)


def test_a_message_naming_no_instant_falls_back_to_the_bucket_default() -> None:
    """No ``can retry after time:`` in the message means no stated wait to read.

    The refusal still carries a well-formed headroom, and its wait is the
    token-bucket default — the same conservative floor a HTTP 429 without
    a ``Retry-After`` header gets.
    """
    envelope = json.loads(_error_budget_body())
    envelope["msg"] = "over 20 error code:109421 requests within 480000 ms"
    body = json.dumps(envelope).encode("utf-8")

    with pytest.raises(RouterRateLimitedError) as raised:
        _venue_client(body).query_order("a" * 40)

    assert raised.value.retry_after == BUCKET_DEFAULT_WAIT


def test_a_retry_instant_already_passed_floors_the_wait_at_zero() -> None:
    """A budget the venue says has already returned is a wait of zero seconds."""
    late_clock = RETRY_AT_MS + 5_000

    with pytest.raises(RouterRateLimitedError) as raised:
        _venue_client(_error_budget_body(), clock_ms=late_clock).query_order("a" * 40)

    assert raised.value.retry_after == timedelta(0)


# -- The read-back walks on a budget of its own --------------------------------


class _BudgetWalkTransport:
    """A transport living the incident: not-exist answers, then the budget.

    Serves the recorded not-exist envelope for the first ``not_found``
    reads and the recorded error-budget envelope for every read after —
    the live sequence of the 2026-10-20T16:00 slot, so a walk that asks
    past its budget meets the same refusal the venue sent that day.
    """

    def __init__(self, not_found_answers: int = 20) -> None:
        self._not_found_left = not_found_answers
        self.requests: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, headers, body) -> tuple[int, bytes]:
        self.requests.append((method, url))
        if self._not_found_left > 0:
            self._not_found_left -= 1
            not_exist = next(
                code for code in ORDER_NOT_FOUND_CODES if code != 109400
            )
            return 200, json.dumps(
                {"code": not_exist, "msg": "order not exist", "data": {}}
            ).encode("utf-8")
        return 200, _error_budget_body()


def _walk_identifiers(count: int) -> list[str]:
    """``count`` bare clientOrderIDs, as a wide book's read-back is handed."""
    return [f"nullius-error-budget-{index:06d}" for index in range(count)]


def test_the_read_back_stops_at_the_not_found_budget_and_reports_the_rest_unread():
    """Seventy legs, twenty not-exist answers: the walk stops at fifteen.

    Before the fix the walk queried all seventy and the twenty-first read
    tripped the venue's error budget; with the budget it makes fifteen
    queries — under the twenty the venue bills — and answers every order
    it stopped asking about as ``unread`` rather than guessing.
    """
    transport = _BudgetWalkTransport(not_found_answers=20)
    client = BingXClient(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        transport=transport,
        clock=lambda: FIXED_MILLIS,
    )

    statuses = read_back_orders(client=client, orders=_walk_identifiers(70))

    assert DEFAULT_NOT_FOUND_BUDGET == 15
    assert len(transport.requests) == 15
    assert len(statuses) == 70
    assert [status.status for status in statuses[:15]] == [VST_ORDER_NOT_FOUND] * 15
    assert [status.status for status in statuses[15:]] == [VST_ORDER_UNREAD] * 55
    # An unread order is neither found nor not_found: it carries no
    # measurement, because the venue was never asked about it.
    unread = statuses[15]
    assert unread.executed_quantity is None
    assert unread.average_price is None
    assert unread.is_open is False


def test_an_explicit_not_found_budget_is_keyword_only() -> None:
    """A caller narrows the walk's own budget by naming it, per call."""
    transport = _BudgetWalkTransport(not_found_answers=20)
    client = BingXClient(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        transport=transport,
        clock=lambda: FIXED_MILLIS,
    )

    statuses = read_back_orders(
        client=client, orders=_walk_identifiers(70), not_found_budget=2
    )

    assert len(transport.requests) == 2
    assert [status.status for status in statuses[:2]] == [VST_ORDER_NOT_FOUND] * 2
    assert [status.status for status in statuses[2:]] == [VST_ORDER_UNREAD] * 68


# -- The slot names the step the venue refused ---------------------------------


def test_a_rate_limited_reconcile_is_skipped_and_the_slot_still_places(
    tmp_path, test_database_url, caplog
) -> None:
    """The incident's own shape: the reconcile's read-back trips 109429.

    The 08:00 slot places five orders; the 12:00 slot's reconcile asks the
    venue about them and the venue answers from its error budget.  The
    step is skipped — ``reconciled: false``, nothing recorded — and the
    slot still places its own five legs and exits 0, with the refusal on
    the journal as one line naming the step and the venue's code.
    """
    from router.submission_result import RouterOrderPlacementStore

    book_path = _write_book(tmp_path)
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()

    morning = _client()
    _run(
        book_path,
        client=morning,
        url=test_database_url,
        store=store,
        limiter=limiter,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    assert len(morning.placed) == 5

    afternoon = _RateLimitedFaceClient(
        refuse="query_order", balance=_funded_balance()
    )
    with caplog.at_level(logging.INFO, logger="router.bingx_rebalance"):
        code, lines = _run(
            book_path, client=afternoon, url=test_database_url, store=store,
            limiter=limiter,
        )

    assert code == EXIT_OK
    line = lines[0]
    assert line["reconciled"] is False
    assert line["cancel_skipped"] is False
    assert line["exit_code"] == EXIT_OK
    # The slot still placed: a budget that returns in minutes must not
    # cost the book four hours of drift.
    assert len(afternoon.placed) == 5
    assert all(
        order["outcome"] == "placed" for order in line["orders"]
    )
    # One greppable line names the step and the venue's own code.
    refusals = [
        record.message
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.message.startswith(f"{BINGX_REBALANCE_CODE}: step=")
    ]
    assert len(refusals) == 1
    assert refusals[0].startswith(
        f"{BINGX_REBALANCE_CODE}: step=reconcile venue_code=109429 symbol=- "
    )
    # The line ends with the venue's own message, so the journal carries
    # the wait the budget names without a second lookup.
    assert "can retry after time" in refusals[0]


def test_a_rate_limited_cancel_is_skipped_and_the_slot_still_places(
    tmp_path, test_database_url, caplog
) -> None:
    """The cancel's listing read refused: sweep nothing, place anyway.

    The step records itself as skipped — ``cancel_skipped: true`` and no
    identifiers — and the resting orders stay resting for the next slot,
    which the venue's own budget will serve again minutes from now.
    """
    afternoon = _RateLimitedFaceClient(
        refuse="open_orders", balance=_funded_balance()
    )
    with caplog.at_level(logging.INFO, logger="router.bingx_rebalance"):
        code, lines = _run(
            _write_book(tmp_path), client=afternoon, url=test_database_url
        )

    assert code == EXIT_OK
    line = lines[0]
    assert line["cancel_skipped"] is True
    assert line["cancelled"] == []
    assert len(afternoon.placed) == 5
    assert any(
        record.message.startswith(
            f"{BINGX_REBALANCE_CODE}: step=cancel venue_code=109429 symbol=- "
        )
        for record in caplog.records
        if record.levelno == logging.INFO
    )


def test_a_rate_limited_guard_still_refuses_the_slot(
    tmp_path, test_database_url, caplog
) -> None:
    """A refusal from the guard ends the slot, as today — but named.

    Placing against an unknown account state is the one thing the slot
    must not do, so the guard's read of the account is not skippable: the
    slot exits 1 with no summary line, and the journal now says which
    step was refused and with what code.
    """
    client = _RateLimitedFaceClient(refuse="balance", balance=_funded_balance())
    with caplog.at_level(logging.INFO, logger="router.bingx_rebalance"):
        code, lines = _run(
            _write_book(tmp_path), client=client, url=test_database_url
        )

    assert code == EXIT_REFUSED
    assert lines == []
    assert client.placed == []
    assert any(
        record.message.startswith(
            f"{BINGX_REBALANCE_CODE}: step=guard venue_code=109429 symbol=- "
        )
        for record in caplog.records
        if record.levelno == logging.INFO
    )
