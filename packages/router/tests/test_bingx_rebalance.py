"""Tests for :mod:`router.bingx_rebalance` — Stage 2 feature 4, one slot.

``additions_spec_bingx_vst_stage2.xml``, "BingX VST Stage 2", feature 4:
*System runs one scheduled rebalance slot from* ``python -m
router.bingx_rebalance --book BOOK`` *and prints one JSON summary line.
The slot is the current UTC time floored to a 4-hour boundary, and
rebalance_ts is the slot start, so a second run in the same slot prints
prior for every order and places nothing new.*  The spec's own order
inside a slot — the daily-loss guard, the cancel of the book's earlier
resting orders, the previous slot's reconciliation, the plan and its
placement, the persistence into the book member's store — is held below
one step at a time, over the same recording doubles the two acts it calls
are proven with in their own suites.

Every clause of that sentence is a test here.  The **slot's floor** is
asserted on both sides of a boundary and against a non-UTC offset; the
**guard runs before anything is placed** on the venue's own call order and
on the day it measures against; the **cancel** names the previous slots'
orders by feature 316's own identifier and leaves a foreign order alone;
the **reconcile** reads the terms placement recorded — never a rebuilt
plan — and lands a row in feature 340's store; the **placement** is
idempotent inside a slot and only inside it; and the **persistence** is
written for a book that names its provenance and skipped, with its reason,
for the synthetic book that does not.

The three exits the spec names are pinned as they are reached: 0 when
every order is placed or prior, 1 when a leg is *refused* — which a leg the
*gates* closed is not, because it names no venue order — and 3 on a
daily-loss refusal, both the breach and a halt that already stands.

**Feature 2 of the alerts spec** — *alerts on every rebalance slot's
outcome without changing it* — is held by the suite's tail: every finished
slot appends its completion (``book_id``, ``slot``, ``finished_at``,
``exit_code``) to the module's own table in the ``DATABASE_URL`` store and
then sends feature 1's alert — urgent on 3 naming the loss, the limit and
the manual reset; warning on 1 listing each refused symbol with its code
and message; silent info on 0 summarising the legs, the cancels, the
reconcile and the day's loss.  The alert rides the same injected
``transport`` the venue does, so no test opens a socket, and the fake
token feature 1's suite coins is asserted absent from every captured
output — stdout, stderr and the log.

No test opens a socket.  The client is the recording double
:mod:`packages.router.tests.test_bingx_mirror` already proves the mirror
against, every BingX answer it serves is the recorded fixture under
``fixtures/bingx_vst/`` or derived from one (a balance row at a re-spelled
equity, a filled order answer built from the live single-order document),
and the one store is the per-test SQLite database the member's ``conftest``
gives every test through ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from risk.daily_loss import halt_on_daily_loss, recorded_daily_loss_halts
from router.bingx_alert import BOT_NAME, INFO, URGENT, WARNING
from router.bingx_client_order_id import project_bingx_client_order_id
from router.bingx_mirror import (
    MIRROR_OUTCOME_PLACED,
    MIRROR_OUTCOME_PRIOR,
    MIRROR_OUTCOME_REFUSED,
)
from router.bingx_rebalance import (
    BINGX_REBALANCE_CODE,
    DATABASE_URL_MISSING_CODE,
    EXIT_DAILY_LOSS_HALT,
    EXIT_OK,
    EXIT_REFUSED,
    REBALANCE_SLOT_HOURS,
    ROUTER_SLOT_COMPLETION_TABLE,
    SLOT_LOOKBACK_HOURS,
    RouterBingXRebalanceError,
    RouterSlotCompletionStore,
    SlotCompletion,
    floor_to_slot,
    main,
)
from router.bingx_risk import ROUTER_DAILY_OPENING_EQUITY_TABLE
from router.client_order_id import derive_client_order_id
from router.submission_result import RouterOrderPlacementStore

# The doubles this member's mirror suite already proves the placement path
# against, reused rather than re-written: a recording client with every
# face the plan, the preflight, the repricing, the read-back and the cancel
# read the venue through, a limiter that meters nothing, and the pinned
# clock the preflight's skew is measured against.
from test_bingx_mirror import (  # isort: skip
    _book,
    _clock,
    _CountingLimiter,
    _MirrorClient,
)
import test_bingx_reconcile as reconcile_fixtures  # isort: skip
import test_bingx_alert as alert_fixtures  # isort: skip

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: The recorded account's equity, verbatim from ``live/balance.json``: the
#: figure every day-figure test measures against, and the one the guard
#: reads out of the recorded row.
RECORDED_EQUITY = "9999.2781"

#: The recorded resting order's identifier — an order that belongs to no
#: book and no rebalance, so it is exactly the order a cancel must leave
#: alone.
FOREIGN_ORDER_ID = "nulliusprobe0000000000000000000000000000"

#: A moment inside the 12:00 slot: the slot's own start is 12:00, and the
#: forty minutes past it are what the floor must discard.
MID_SLOT = datetime(2026, 10, 4, 12, 37, tzinfo=UTC)
SLOT_NOON = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

#: The slot one boundary earlier — the rebalance a 12:00 slot reconciles.
SLOT_MORNING = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


def _live(name: str) -> dict:
    """One recorded fixture, verbatim — an input, never edited."""
    return json.loads((FIXTURES / "live" / name).read_text(encoding="utf-8"))


def _funded_balance(equity: str = RECORDED_EQUITY) -> dict:
    """The recorded balance row, at a re-spelled equity and a funded margin.

    Derived from ``live/balance.json`` — the venue's one row with two of its
    fields re-spelled, never an invented response shape — so the guard reads
    the day's equity out of the venue's own document shape while the
    preflight's margin door is comfortably funded for the five legs the
    synthetic book orders.
    """
    data = json.loads(json.dumps(_live("balance.json")["data"]))
    data["balance"]["equity"] = equity
    data["balance"]["availableMargin"] = "100000"
    return data


def _client(*, balance: dict | None = None, **kwargs) -> _MirrorClient:
    """The mirror's recording client, funded by default.

    The default balance is the recorded row, because a slot's *first* step
    reads the account's equity and the mirror's own default carries none —
    the daily-loss guard would refuse a balance document with no equity in
    it, which is that guard's own law and not this suite's subject.
    """
    return _MirrorClient(
        balance=_funded_balance() if balance is None else balance, **kwargs
    )


def _write_book(tmp_path: Path, **changes) -> Path:
    """Write a book document to ``tmp_path``, with overrides applied."""
    book = _book()
    book.update(changes)
    path = tmp_path / "book.json"
    path.write_text(json.dumps(book), encoding="utf-8")
    return path


def _run(
    book_path: Path,
    *,
    client: _MirrorClient,
    url: str,
    now: datetime = MID_SLOT,
    store: RouterOrderPlacementStore | None = None,
    limiter: _CountingLimiter | None = None,
    book_store: object | None = None,
    env: dict | None = None,
    transport: object | None = None,
    alert: object | None = None,
    completion_store: object | None = None,
) -> tuple[int, list[dict]]:
    """One slot of the command, with the suite's doubles, as (exit, lines).

    Every seam the command is not testing here is injected: the store and
    the limiter are the doubles this member's other suites use, the clock
    is the pinned millisecond the preflight compares against the double's
    server time, and ``emit`` collects the JSON lines instead of printing
    them — so the one line the command prints is the assertion's operand
    and never the test runner's stdout.  The alert's own seams — the
    ``transport`` the Bot API POST would ride and the ``alert`` sender
    itself — pass straight through, so an alert test configures the
    environment and watches the one call, and every other test leaves them
    unconfigured (``env={}`` answers no token, so nothing is sent and no
    socket opens).
    """
    emitted: list[str] = []
    code = main(
        ["--book", str(book_path)],
        client=client,
        transport=transport,
        store=store or RouterOrderPlacementStore(url),
        limiter=limiter or _CountingLimiter(),
        book_store=book_store,
        completion_store=completion_store,
        env={} if env is None else env,
        database_url=url,
        now=lambda: now,
        clock=_clock,
        sleep=lambda _d: None,
        alert=alert,
        emit=emitted.append,
    )
    return code, [json.loads(line) for line in emitted]


def _slot_identifier(book_id: str, slot: datetime, symbol: str) -> str:
    """One leg's identifier as the venue spells it — feature 316, projected.

    The identifier placement names an order with, the way
    :func:`router.bingx_orders.cancel_rebalance_orders` compares it against
    the venue's own 40-character projection.
    """
    return project_bingx_client_order_id(
        derive_client_order_id(book_id=book_id, rebalance_ts=slot, symbol=symbol)
    )


def _opening_equity_days(url: str) -> list[str]:
    """The days this feature's guard has opened rows for, read raw.

    Straight out of the store with SQL, so the table's own name and the
    store's own spellings are pinned rather than read back through the
    guard under test.
    """
    path = url.removeprefix("sqlite://")
    with sqlite3.connect(path) as plain:
        return [
            row[0]
            for row in plain.execute(
                f"SELECT day FROM {ROUTER_DAILY_OPENING_EQUITY_TABLE} ORDER BY day"
            )
        ]


# -- The slot's floor ----------------------------------------------------------


@pytest.mark.parametrize(
    "moment, expected",
    [
        ("2026-10-04T00:00:00+00:00", "2026-10-04T00:00:00+00:00"),
        ("2026-10-04T00:05:00+00:00", "2026-10-04T00:00:00+00:00"),
        ("2026-10-04T03:59:59+00:00", "2026-10-04T00:00:00+00:00"),
        ("2026-10-04T04:00:00+00:00", "2026-10-04T04:00:00+00:00"),
        ("2026-10-04T12:00:00+00:00", "2026-10-04T12:00:00+00:00"),
        ("2026-10-04T15:59:59+00:00", "2026-10-04T12:00:00+00:00"),
        ("2026-10-04T16:05:00+00:00", "2026-10-04T16:00:00+00:00"),
        ("2026-10-04T23:59:59+00:00", "2026-10-04T20:00:00+00:00"),
    ],
)
def test_the_moment_is_floored_to_the_start_of_its_four_hour_slot(
    moment: str, expected: str
) -> None:
    """Both sides of every boundary the timer fires just past.

    The spec's own *"the current UTC time floored to a 4-hour boundary"*,
    and the answer is the boundary's **start** — the ``rebalance_ts`` a slot
    stamps, which is what makes two runs in one slot derive one identifier
    per symbol.
    """
    assert floor_to_slot(datetime.fromisoformat(moment)) == datetime.fromisoformat(
        expected
    )


def test_the_floor_keeps_no_minute_second_or_microsecond() -> None:
    floored = floor_to_slot(datetime(2026, 10, 4, 12, 37, 44, 123456, tzinfo=UTC))
    assert (floored.minute, floored.second, floored.microsecond) == (0, 0, 0)


def test_the_floor_is_the_utc_boundary_not_the_hosts() -> None:
    """An instant stated at another offset is floored on the UTC clock.

    ``17:37+05:30`` is ``12:07Z``, so its slot starts at 12:00Z — not at
    17:00+05:30, which would be a boundary the venue's day does not have.
    """
    local = datetime.fromisoformat("2026-10-04T17:37:00+05:30")
    assert floor_to_slot(local) == SLOT_NOON
    assert floor_to_slot(local).utcoffset() == timedelta(0)


def test_a_naive_instant_is_refused_by_name() -> None:
    with pytest.raises(RouterBingXRebalanceError) as refusal:
        # Naive on purpose: this is the shape being refused.
        floor_to_slot(datetime(2026, 10, 4, 12, 37))  # noqa: DTZ001
    assert str(refusal.value).startswith(BINGX_REBALANCE_CODE)


def test_a_non_datetime_is_refused_by_name() -> None:
    with pytest.raises(RouterBingXRebalanceError) as refusal:
        floor_to_slot("2026-10-04T12:37:00+00:00")  # type: ignore[arg-type]
    assert str(refusal.value).startswith(BINGX_REBALANCE_CODE)


def test_the_slot_widths_are_the_specs_own_numbers() -> None:
    assert REBALANCE_SLOT_HOURS == 4
    assert SLOT_LOOKBACK_HOURS == 24


# -- One slot, end to end ------------------------------------------------------


def test_one_slot_places_each_order_once_and_prints_one_json_line(
    tmp_path, test_database_url
) -> None:
    """The happy path: five orders placed, exit 0, one line on stdout.

    The line carries the slot's own start (not the 12:37 moment it was run
    at), the day's guard figures, every leg's outcome and the exit code —
    the spec's *"prints one JSON summary line"*.
    """
    client = _client()
    code, lines = _run(
        _write_book(tmp_path), client=client, url=test_database_url
    )

    assert code == EXIT_OK
    assert len(lines) == 1
    line = lines[0]
    assert line["book_id"] == "synthetic-vst-0"
    assert line["rebalance_ts"] == SLOT_NOON.isoformat()
    assert line["slot"] == SLOT_NOON.isoformat()
    assert line["exit_code"] == EXIT_OK
    assert line["opening_equity"] == RECORDED_EQUITY
    assert line["current_equity"] == RECORDED_EQUITY
    assert line["daily_loss"] == "0.0000"
    assert line["refused"] == []
    # Five orders left the venue, each once, and every one is `placed`.
    assert len(client.placed) == 5
    assert [o["outcome"] for o in line["orders"]] == [MIRROR_OUTCOME_PLACED] * 5


def test_the_gate_closed_legs_are_reported_but_are_not_refusals(
    tmp_path, test_database_url
) -> None:
    """A leg the gates closed names no venue order, so it never moves the exit.

    The synthetic book's AGLD weight is below the venue's notional floor and
    NCFXUSD2ARS is not tradable: both are reported under ``skipped`` — the
    way Stage 1's mirror reports them — and neither is a *refusal*, which
    would be an order this run tried to send and the venue would not take.
    """
    code, lines = _run(
        _write_book(tmp_path), client=_client(), url=test_database_url
    )

    assert code == EXIT_OK
    assert {
        (leg["symbol"], leg["code"]) for leg in lines[0]["skipped"]
    } == {
        ("AGLD-USDT", "below_min_notional"),
        ("NCFXUSD2ARS-USDT", "not_tradable"),
    }
    assert lines[0]["refused"] == []


def test_a_second_run_in_the_same_slot_places_nothing_and_reports_prior(
    tmp_path, test_database_url
) -> None:
    """The spec's own idempotence clause.

    Two runs, one slot: the second is answered from the rows the first
    wrote, so no order leaves the venue again and every leg reads ``prior``
    — which is what makes the timer's ``Persistent=true`` catch-up safe.
    """
    book_path = _write_book(tmp_path)
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()

    first = _client()
    code, lines = _run(
        book_path,
        client=first,
        url=test_database_url,
        store=store,
        limiter=limiter,
    )
    assert (code, len(first.placed)) == (EXIT_OK, 5)
    after_first = len(limiter.operations)

    second = _client()
    code, lines = _run(
        book_path,
        client=second,
        url=test_database_url,
        store=store,
        limiter=limiter,
    )

    assert code == EXIT_OK
    assert second.placed == []
    # Nothing left the venue the second time — though each leg still priced
    # itself against the weight budget before the store answered it `prior`,
    # exactly as Stage 1's mirror does: the meter runs before the claim.
    assert len(limiter.operations) - after_first == 5
    assert [o["outcome"] for o in lines[0]["orders"]] == [MIRROR_OUTCOME_PRIOR] * 5
    assert lines[0]["rebalance_ts"] == SLOT_NOON.isoformat()


def test_the_next_slot_places_its_own_orders(tmp_path, test_database_url) -> None:
    """Idempotence is per slot, not per book: the next boundary orders again.

    The slot is folded into every order's own name, so 16:00's plan is a new
    set of identifiers and every leg is a fresh placement — the reason the
    sweep in step 2 exists at all.
    """
    book_path = _write_book(tmp_path)
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()

    first = _client()
    _run(book_path, client=first, url=test_database_url, store=store, limiter=limiter)

    later = _client()
    code, lines = _run(
        book_path,
        client=later,
        url=test_database_url,
        store=store,
        limiter=limiter,
        now=datetime(2026, 10, 4, 16, 5, tzinfo=UTC),
    )

    assert code == EXIT_OK
    assert len(later.placed) == 5
    assert [o["outcome"] for o in lines[0]["orders"]] == [MIRROR_OUTCOME_PLACED] * 5
    assert lines[0]["rebalance_ts"] == datetime(
        2026, 10, 4, 16, 0, tzinfo=UTC
    ).isoformat()


def test_the_book_document_is_never_mutated(tmp_path, test_database_url) -> None:
    """The slot stamps *a copy*: the operator's document is left as it read."""
    path = _write_book(tmp_path)
    before = path.read_text(encoding="utf-8")
    _run(path, client=_client(), url=test_database_url)
    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before)["rebalance_ts"] == "2026-09-30T00:00:00+00:00"


# -- Step 1: the daily-loss guard runs before anything is placed ---------------


def test_the_guard_runs_before_a_single_order_leaves(
    tmp_path, test_database_url
) -> None:
    """The spec's own ordering: step 1 precedes step 4.

    The guard's balance read is the run's first venue call, and it precedes
    every placement — the sentence's *"before anything is placed"* held on
    the call order rather than on a promise.
    """
    client = _client()
    _run(_write_book(tmp_path), client=client, url=test_database_url)

    first_place = next(
        index
        for index, call in enumerate(client.calls)
        if call[0] == "place_order"
    )
    assert ("balance",) in client.calls[:first_place]
    assert client.calls[:first_place][0] == ("balance",)


def test_the_guard_measures_the_slots_own_utc_day(
    tmp_path, test_database_url
) -> None:
    """The day the check opens a row for is the slot's day, not the wall clock's.

    A slot at 20:00 on the 4th and a slot at 00:00 on the 5th open a row for
    each of those days — the guard is handed the slot's own instant, so the
    UTC day it measures is the fact the slot's boundary was taken from.
    """
    book_path = _write_book(tmp_path)

    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        now=datetime(2026, 10, 4, 23, 59, tzinfo=UTC),
    )
    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        now=datetime(2026, 10, 5, 0, 7, tzinfo=UTC),
    )

    assert _opening_equity_days(test_database_url) == ["2026-10-04", "2026-10-05"]


def test_a_daily_loss_breach_refuses_the_slot_with_exit_three(
    tmp_path, test_database_url, capsys
) -> None:
    """The day's loss past 3% of the book's equity: halt, flatten, exit 3.

    The spec gives the daily-loss refusal its own exit code.  The first
    check of the day opens the row at the recorded equity; the second check
    — a later slot of the same day, on an account that has lost 499.28
    against the book's 10000 equity, well past the 300 limit — trips
    feature 2's halt and the command answers 3.
    """
    book_path = _write_book(tmp_path)

    opening = _client()
    code, _ = _run(
        book_path,
        client=opening,
        url=test_database_url,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    assert code == EXIT_OK

    losing = _client(balance=_funded_balance("9500"))
    code, lines = _run(
        book_path,
        client=losing,
        url=test_database_url,
        now=datetime(2026, 10, 4, 12, 7, tzinfo=UTC),
    )

    assert code == EXIT_DAILY_LOSS_HALT
    # No summary line: a refused slot prints its reason, not an outcome.
    assert lines == []
    assert losing.placed == []
    # The halt stands in the store feature 325 owns.
    assert len(recorded_daily_loss_halts(database_url=test_database_url)) == 1
    assert "daily_loss_halt" in capsys.readouterr().err


def test_a_standing_halt_refuses_a_slot_with_nothing_read_from_the_venue(
    tmp_path, test_database_url, capsys
) -> None:
    """A halt that already stands is asked before any venue read.

    ``require_within_daily_loss_limit`` is the guard's first question, so a
    halted day refuses with exit 3 without pricing a plan or reading a
    balance — the account is asked nothing at all.
    """
    halt_on_daily_loss(
        daily_loss=400.0,
        daily_loss_limit=300.0,
        database_url=test_database_url,
    )

    client = _client()
    code, lines = _run(
        _write_book(tmp_path), client=client, url=test_database_url
    )

    assert code == EXIT_DAILY_LOSS_HALT
    assert lines == []
    assert client.calls == []
    assert "orders_halted" in capsys.readouterr().err


def test_a_loss_inside_the_limit_passes(tmp_path, test_database_url) -> None:
    """A day inside its limit is not a refusal: the slot runs normally."""
    book_path = _write_book(tmp_path)

    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    # 9999.2781 - 9750 = 249.2781, inside the book's 300 limit.
    code, lines = _run(
        book_path,
        client=_client(balance=_funded_balance("9750")),
        url=test_database_url,
        now=datetime(2026, 10, 4, 12, 7, tzinfo=UTC),
    )

    assert code == EXIT_OK
    assert lines[0]["daily_loss"] == "249.2781"


# -- Step 2: the cancel sweeps the book's earlier slots ------------------------


def test_the_cancel_removes_the_previous_slots_resting_orders(
    tmp_path, test_database_url
) -> None:
    """The spec's *"cancels resting orders left by this book's earlier slots"*.

    The venue's listing carries one order this book placed four hours ago
    and one order that belongs to nobody: the sweep cancels the first by its
    own feature 316 name and leaves the foreign order untouched — the
    ownership test :func:`cancel_rebalance_orders` states.
    """
    previous_id = _slot_identifier("synthetic-vst-0", SLOT_MORNING, "BTC-USDT")
    client = _client(
        open_orders=[
            {"symbol": "BTC-USDT", "clientOrderId": previous_id},
            {"symbol": "ETH-USDT", "clientOrderId": FOREIGN_ORDER_ID},
        ]
    )

    code, lines = _run(_write_book(tmp_path), client=client, url=test_database_url)

    assert code == EXIT_OK
    assert lines[0]["cancelled"] == [previous_id]
    cancelled = [call for call in client.calls if call[0] == "cancel_order"]
    assert [call[1] for call in cancelled] == [previous_id]


def test_the_cancel_sweeps_the_whole_trailing_day(
    tmp_path, test_database_url
) -> None:
    """All six earlier slots' names are offered to the listing, not one.

    A resting order from five slots back — 20 hours before the 12:00 slot —
    is still inside the 24-hour window and is cancelled, which proves the
    sweep walks the day rather than only the immediately previous boundary.
    """
    old_id = _slot_identifier(
        "synthetic-vst-0", SLOT_NOON - timedelta(hours=20), "ETH-USDT"
    )
    client = _client(open_orders=[{"symbol": "ETH-USDT", "clientOrderId": old_id}])

    code, lines = _run(_write_book(tmp_path), client=client, url=test_database_url)

    assert code == EXIT_OK
    assert lines[0]["cancelled"] == [old_id]


def test_the_cancel_leaves_this_slots_own_orders_alone(
    tmp_path, test_database_url
) -> None:
    """The sweep is the *earlier* slots': the current slot's name is not in it.

    An order carrying this slot's own identifier is not something an earlier
    run could have left, and the sweep must not cancel the order this run is
    about to reconcile against.
    """
    own_id = _slot_identifier("synthetic-vst-0", SLOT_NOON, "BTC-USDT")
    client = _client(open_orders=[{"symbol": "BTC-USDT", "clientOrderId": own_id}])

    code, lines = _run(_write_book(tmp_path), client=client, url=test_database_url)

    assert code == EXIT_OK
    assert lines[0]["cancelled"] == []


def test_an_empty_listing_cancels_nothing(tmp_path, test_database_url) -> None:
    code, lines = _run(
        _write_book(tmp_path), client=_client(), url=test_database_url
    )
    assert code == EXIT_OK
    assert lines[0]["cancelled"] == []


# -- Step 3: the previous slot is reconciled from the recorded terms ----------


def _filled_answers(
    store: RouterOrderPlacementStore, *, book_id: str, slot: datetime
) -> dict[str, dict]:
    """A fully-filled answer for every order a slot recorded as placed.

    Each answer is the live single-order document with this fill's own
    measurements — derived from the recorded fixture rather than invented,
    the way :mod:`test_bingx_reconcile` builds its own — keyed by the *full*
    64-hex identifier the read-back looks the order up by (feature 3
    projects the recorded key down to the venue's 40 characters for the
    query it sends, then folds the answer back onto the full key).

    The fill's ``avgPrice`` is each order's **recorded reference price** —
    the price placement actually recorded, the repriced limit or the mark
    read in the run — so a fill at that price has zero slippage and the
    realized cost is the fee alone.  Builing the answers from the *store*
    rather than from the plan is the point: it is the recorded reference
    that a fill is measured against, and this is what proves the reference
    the plan carried was superseded by the one the order went out at.
    """
    answers: dict[str, dict] = {}
    for record in store.records_for(book_id, slot):
        # Keyed by the 40 characters the read-back *asks* the venue with —
        # the projection feature 3 sends — while the answer document carries
        # the full 64-hex name the read-back folds it back onto.
        query_key = project_bingx_client_order_id(record.client_order_id)
        answers[query_key] = reconcile_fixtures._filled_answer(
            query_key,
            symbol=record.symbol,
            type_=record.type,
            qty=str(record.quantity),
            price=str(record.reference_price),
        )
    return answers


def test_the_previous_slot_is_reconciled_from_the_terms_placement_recorded(
    tmp_path, test_database_url
) -> None:
    """Step 3, and the defect the recorded terms exist to close.

    The 08:00 slot places five orders; the 12:00 slot then reconciles *that*
    slot — reading its terms back out of the store rather than rebuilding a
    plan, which today's positions and marks would size differently — and
    feature 340's store answers with the row it landed.
    """
    from forward.reconciliation import reconciled_fill_costs

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

    # Every order the morning slot placed has filled, at its recorded price.
    afternoon = _client()
    afternoon._query_answers = _filled_answers(
        store, book_id="synthetic-vst-0", slot=SLOT_MORNING
    )

    code, lines = _run(
        book_path,
        client=afternoon,
        url=test_database_url,
        store=store,
        limiter=limiter,
    )

    assert code == EXIT_OK
    assert lines[0]["reconciled"] is True
    rows = reconciled_fill_costs(database_url=test_database_url)
    assert len(rows) == 1
    assert rows[0].rebalance_ts == SLOT_MORNING
    # A fill at its own reference price pays the fee alone: zero slippage.
    assert rows[0].difference_bps == pytest.approx(0.0)


def test_a_previous_slot_with_no_recorded_terms_reconciles_nothing(
    tmp_path, test_database_url
) -> None:
    """Nothing placed last slot means no terms to price: the step is a no-op.

    ``reconciled`` is ``False`` rather than a zero cost, which would read as
    a perfectly calibrated model — the distinction feature 340's own store
    makes between *no row* and *a row of zero*.
    """
    from forward.reconciliation import reconciled_fill_costs

    code, lines = _run(
        _write_book(tmp_path), client=_client(), url=test_database_url
    )

    assert code == EXIT_OK
    assert lines[0]["reconciled"] is False
    assert reconciled_fill_costs(database_url=test_database_url) == ()


def test_the_reconcile_reads_the_previous_slot_not_this_one(
    tmp_path, test_database_url
) -> None:
    """The lookup is addressed by the *previous* boundary.

    Every term the run reads back belongs to the slot that has just
    finished, so the orders this run is placing are never the ones it is
    pricing — the rebalance a 12:00 slot reconciles is the 08:00 one.
    """
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

    afternoon = _client()
    _run(
        book_path,
        client=afternoon,
        url=test_database_url,
        store=store,
        limiter=limiter,
        now=datetime(2026, 10, 4, 12, 7, tzinfo=UTC),
    )

    asked = {call[1] for call in afternoon.calls if call[0] == "query_order"}
    expected = {
        _slot_identifier("synthetic-vst-0", SLOT_MORNING, order.symbol)
        for order in morning.placed
    }
    assert asked == expected


# -- Step 5: the rebalance is persisted when the book names its provenance -----


def test_the_rebalance_is_persisted_when_the_book_names_its_signals(
    tmp_path, test_database_url
) -> None:
    """The spec's conditional step 5, on the branch that writes.

    A book naming ``originating_signal_ids`` has its weights and provenance
    recorded in the book member's own store, addressed by the book and the
    slot — read back here through that member's reader, so the row is proven
    to have landed where feature 309's consumers will look for it.
    """
    from book import RebalanceTargetWeightsStore

    book_store = RebalanceTargetWeightsStore(test_database_url)
    code, lines = _run(
        _write_book(
            tmp_path,
            originating_signal_ids=[{"signal_id": "momentum-42"}],
        ),
        client=_client(),
        url=test_database_url,
        book_store=book_store,
    )

    assert code == EXIT_OK
    assert lines[0]["persisted"] is True
    assert lines[0]["persist_skipped"] is None
    record = book_store.get(book_id="synthetic-vst-0", rebalance_ts=SLOT_NOON)
    assert record is not None
    assert record.rebalance_ts == SLOT_NOON


def test_the_rebalance_is_skipped_with_its_reason_when_no_signals_are_named(
    tmp_path, test_database_url
) -> None:
    """The synthetic book names no provenance — a state, not a fault.

    The step is skipped and the *reason* is reported, because the spec names
    the swap to real signals as a later input change: a book with no
    provenance is a legitimate deployment, and the run still exits 0.
    """
    from book import RebalanceTargetWeightsStore

    book_store = RebalanceTargetWeightsStore(test_database_url)
    code, lines = _run(
        _write_book(tmp_path), client=_client(), url=test_database_url,
        book_store=book_store,
    )

    assert code == EXIT_OK
    assert lines[0]["persisted"] is False
    assert lines[0]["persist_skipped"] == "no_originating_signal_ids"
    assert book_store.get(book_id="synthetic-vst-0", rebalance_ts=SLOT_NOON) is None


def test_an_empty_provenance_is_refused_rather_than_skipped(
    tmp_path, test_database_url
) -> None:
    """A book that *names* an empty provenance is a mistyped one, not a book
    with none: the run is refused rather than quietly persisted nowhere."""
    code, lines = _run(
        _write_book(tmp_path, originating_signal_ids=[]),
        client=_client(),
        url=test_database_url,
    )

    assert code == EXIT_REFUSED
    assert lines == []


def test_a_provenance_naming_no_signal_identifier_is_refused(
    tmp_path, test_database_url
) -> None:
    code, _ = _run(
        _write_book(tmp_path, originating_signal_ids=[{"signal_id": "  "}]),
        client=_client(),
        url=test_database_url,
    )
    assert code == EXIT_REFUSED


# -- The exits: 0 placed-or-prior, 1 refused, 3 daily loss ---------------------


def test_a_venue_refusal_on_one_leg_exits_one(
    tmp_path, test_database_url
) -> None:
    """The spec's *"1 when any leg is refused"*, on one leg of five.

    The venue takes four orders and refuses the fifth with its own code —
    the recorded PostOnly cross, BingX 101215.  The refusal is that *leg's*,
    never the run's end: its four siblings still leave, the line names the
    refused symbol and the venue's own code, and the exit is 1.
    """
    from router.bingx_client import RouterBingXRefusedError

    refusal = RouterBingXRefusedError(
        "101215", "the PostOnly order would have crossed the book"
    )
    # The fourth order the plan sends is refused; the rest are taken.
    effects: list = [lambda: {"orderId": "x"} for _ in range(3)]
    effects.append(lambda: (_ for _ in ()).throw(refusal))
    effects.append(lambda: {"orderId": "x"})
    client = _client(place_effects=effects)

    code, lines = _run(_write_book(tmp_path), client=client, url=test_database_url)

    assert code == EXIT_REFUSED
    assert lines[0]["exit_code"] == EXIT_REFUSED
    refused = lines[0]["refused"]
    assert len(refused) == 1
    assert refused[0]["placement"] == "101215"
    assert refused[0]["message"] == "the PostOnly order would have crossed the book"
    # The siblings still left: the refusal did not end the walk.
    outcomes = {o["symbol"]: o["outcome"] for o in lines[0]["orders"]}
    assert len(outcomes) == 5
    assert outcomes[refused[0]["symbol"]] == MIRROR_OUTCOME_REFUSED
    assert list(outcomes.values()).count(MIRROR_OUTCOME_PLACED) == 4


def test_a_preflight_refusal_of_the_whole_plan_exits_one(
    tmp_path, test_database_url, capsys
) -> None:
    """A refusal of the *ask* — the account cannot fund the plan — exits 1.

    The preflight's balance door judges the margin the orders need before a
    single order leaves, so an unfunded account refuses the whole run: no
    summary line, the refusal's own message on stderr, and the spec's
    *"1 when any leg is refused"*.
    """
    unfunded = {
        "balance": {
            "asset": "USDT",
            "equity": RECORDED_EQUITY,
            "availableMargin": "100",
        }
    }
    client = _client(balance=unfunded)
    code, lines = _run(
        _write_book(tmp_path), client=client, url=test_database_url
    )

    assert code == EXIT_REFUSED
    assert lines == []
    assert client.placed == []
    assert "insufficient_balance" in capsys.readouterr().err


def test_the_three_exit_codes_are_the_specs_own_numbers() -> None:
    assert (EXIT_OK, EXIT_REFUSED, EXIT_DAILY_LOSS_HALT) == (0, 1, 3)


# -- The ask: a store, a book, a moment ----------------------------------------


def test_a_run_with_no_database_url_refuses_to_start(
    tmp_path, capsys
) -> None:
    """The spec's *"It refuses to start without DATABASE_URL"*.

    The refusal is named with its own code word, and it is reached before
    anything is read from the venue — every step of a slot reads or writes
    that store, so a run with nowhere to keep them never begins.
    """
    client = _client()
    code = main(
        ["--book", str(_write_book(tmp_path))],
        client=client,
        env={},
        database_url=None,
        now=lambda: MID_SLOT,
        emit=lambda _line: None,
    )

    assert code == EXIT_REFUSED
    assert client.calls == []
    assert DATABASE_URL_MISSING_CODE in capsys.readouterr().err


def test_a_blank_database_url_is_the_same_refusal(tmp_path, capsys) -> None:
    code = main(
        ["--book", str(_write_book(tmp_path))],
        client=_client(),
        env={"DATABASE_URL": "   "},
        now=lambda: MID_SLOT,
        emit=lambda _line: None,
    )
    assert code == EXIT_REFUSED
    assert DATABASE_URL_MISSING_CODE in capsys.readouterr().err


def test_the_database_url_is_read_from_the_environment_when_not_named(
    tmp_path, test_database_url
) -> None:
    """The deployment's own path: nothing is injected but the environment.

    ``env`` names the store, so the command resolves it the way
    ``run.sh``'s default does — no ``database_url`` argument at all.
    """
    emitted: list[str] = []
    code = main(
        ["--book", str(_write_book(tmp_path))],
        client=_client(),
        limiter=_CountingLimiter(),
        env={"DATABASE_URL": test_database_url},
        now=lambda: MID_SLOT,
        clock=_clock,
        sleep=lambda _d: None,
        emit=emitted.append,
    )
    assert code == EXIT_OK
    assert json.loads(emitted[0])["book_id"] == "synthetic-vst-0"


def test_a_missing_book_document_is_refused(tmp_path, test_database_url) -> None:
    code, _ = _run(
        tmp_path / "nowhere.json",
        client=_client(),
        url=test_database_url,
    )
    assert code == EXIT_REFUSED


def test_a_book_document_that_is_not_json_is_refused(
    tmp_path, test_database_url
) -> None:
    path = tmp_path / "book.json"
    path.write_text("{not json", encoding="utf-8")
    code, _ = _run(path, client=_client(), url=test_database_url)
    assert code == EXIT_REFUSED


def test_a_book_document_that_is_not_an_object_is_refused(
    tmp_path, test_database_url
) -> None:
    path = tmp_path / "book.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    code, _ = _run(path, client=_client(), url=test_database_url)
    assert code == EXIT_REFUSED


def test_a_book_naming_no_book_id_is_refused(tmp_path, test_database_url) -> None:
    book = _book()
    del book["book_id"]
    path = tmp_path / "book.json"
    path.write_text(json.dumps(book), encoding="utf-8")
    code, _ = _run(path, client=_client(), url=test_database_url)
    assert code == EXIT_REFUSED


def test_a_book_with_a_naive_rebalance_ts_is_refused(
    tmp_path, test_database_url
) -> None:
    """A naive instant would fold an offset nobody agreed on into every
    order's name, so the ask is refused before a plan is built."""
    code, _ = _run(
        _write_book(tmp_path, rebalance_ts="2026-09-30T00:00:00"),
        client=_client(),
        url=test_database_url,
    )
    assert code == EXIT_REFUSED


def test_a_book_with_an_unparsable_rebalance_ts_is_refused(
    tmp_path, test_database_url
) -> None:
    code, _ = _run(
        _write_book(tmp_path, rebalance_ts="yesterday"),
        client=_client(),
        url=test_database_url,
    )
    assert code == EXIT_REFUSED


def test_the_command_refuses_a_missing_book_argument(test_database_url) -> None:
    """``--book`` is required; argparse's own usage exit is not a slot outcome."""
    with pytest.raises(SystemExit) as exit_info:
        main([], client=_client(), env={}, database_url=test_database_url)
    assert exit_info.value.code == 2


def test_a_deployment_injecting_only_the_environment_still_runs_a_slot(
    tmp_path, test_database_url
) -> None:
    """The wiring the systemd unit relies on: nothing is injected but ``env``.

    No store, limiter, book store or database_url is handed in, so the
    command builds the real ones at the URL ``env`` names — the same store
    the guard, the cancel, the reconcile and the placements all share — and
    the slot completes.  The proof it *did* is in that store: five placement
    rows under feature 316's own keys, one per order the line reports.
    """
    emitted: list[str] = []
    code = main(
        ["--book", str(_write_book(tmp_path))],
        client=_client(),
        env={"DATABASE_URL": test_database_url},
        now=lambda: MID_SLOT,
        clock=_clock,
        sleep=lambda _d: None,
        emit=emitted.append,
    )

    assert code == EXIT_OK
    assert len(emitted) == 1
    line = json.loads(emitted[0])
    store = RouterOrderPlacementStore(test_database_url)
    recorded = store.records_for("synthetic-vst-0", SLOT_NOON)
    assert len(recorded) == 5
    assert {record.symbol for record in recorded} == {
        order["symbol"] for order in line["orders"]
    }


# -- Alerts feature 2: the slot's own record and alert --------------------------
#
# "System alerts on every rebalance slot's outcome without changing it.
# After each slot it records the slot's completion (book_id, slot,
# finished_at, exit_code) in its own table in the DATABASE_URL store, then
# sends feature 1's alert" — the record first (so the heartbeat that reads
# it cannot miss a finish because a phone was unreachable), the alert
# second, and neither able to touch the summary line, the orders or the
# exit code.  The Bot API is configured through the same literal
# environment mapping feature 1's suite uses, with its fake token, and the
# transport is a recorder — so no test here opens a socket, and the one
# token that legitimately appears (the request URL's own path) is asserted
# to appear nowhere else.

#: Feature 1's suite's own fake credential — the Bot API's shape, never a
#: real secret, and asserted absent from every captured output below.
FAKE_TOKEN = alert_fixtures.FAKE_TOKEN


class _AlertTransport:
    """A recording stand-in for the Bot API transport the alert rides.

    The same contract the venue's transport answers — ``(method, url,
    headers, body) -> (status, body)`` — which is why one injected door
    serves both.  Answers feature 1's own canned documents (its ``_ok``
    and ``_refused``), so the alert's delivery outcomes are the venue-shaped
    bytes the real sender parses; ``journal`` lets an ordering test watch
    the call land next to the summary line it follows.
    """

    def __init__(
        self,
        answer: tuple[int, bytes] | None = None,
        *,
        journal: list[str] | None = None,
    ) -> None:
        self.answer = alert_fixtures._ok() if answer is None else answer
        self.journal = journal
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, dict(headers), body))
        if self.journal is not None:
            self.journal.append("alert")
        return self.answer


def _alert_env() -> dict[str, str]:
    """An environment the Bot API is configured by — fake token, fake chat."""
    return alert_fixtures._env()


def _alert_body(transport: _AlertTransport) -> dict:
    """The one alert's decoded request body."""
    assert len(transport.calls) == 1, transport.calls
    return json.loads(transport.calls[0][3].decode("utf-8"))


def _assert_no_token_anywhere(capsys, caplog) -> None:
    """The fake token appears in the request URL's path and nowhere else.

    The spec's own constraint: not in a log line, an exception message, a
    repr or stdout — so every captured surface is checked, not just the
    one a given failure would reach.
    """
    captured = capsys.readouterr()
    for surface in (captured.out, captured.err, caplog.text):
        assert FAKE_TOKEN not in surface


def _completions(url: str) -> list[tuple]:
    """The completion rows, straight out of the store with SQL.

    Read raw, the way ``_opening_equity_days`` reads the guard's own table,
    so the table's name and the record's own spellings are pinned rather
    than read back through the door under test.
    """
    path = url.removeprefix("sqlite://")
    with sqlite3.connect(path) as plain:
        return list(
            plain.execute(
                f"SELECT book_id, slot, finished_at, exit_code "
                f"FROM {ROUTER_SLOT_COMPLETION_TABLE} ORDER BY id"
            )
        )


def _refusing_client() -> _MirrorClient:
    """The venue that takes four legs and refuses the fifth, PostOnly-cross.

    The recorded refusal (BingX 101215) staged on the fourth placement, so
    one leg of five is refused with a code and a message — the leg the
    warning alert must list.
    """
    from router.bingx_client import RouterBingXRefusedError

    refusal = RouterBingXRefusedError(
        "101215", "the PostOnly order would have crossed the book"
    )
    effects: list = [lambda: {"orderId": "x"} for _ in range(3)]
    effects.append(lambda: (_ for _ in ()).throw(refusal))
    effects.append(lambda: {"orderId": "x"})
    return _client(place_effects=effects)


# -- ...its own table in the DATABASE_URL store ---------------------------------


def test_each_finished_slot_records_its_completion(
    tmp_path, test_database_url
) -> None:
    """The record's four fields, once, in the module's own table.

    ``finished_at`` is the same clock the slot's moment came from, asked
    once more at the finish — so the row states when the slot ended, not
    merely which boundary it belonged to.
    """
    code, _ = _run(_write_book(tmp_path), client=_client(), url=test_database_url)

    assert code == EXIT_OK
    assert _completions(test_database_url) == [
        ("synthetic-vst-0", SLOT_NOON.isoformat(), MID_SLOT.isoformat(), EXIT_OK)
    ]


def test_a_refused_slot_records_its_completion_with_exit_one(
    tmp_path, test_database_url
) -> None:
    code, _ = _run(
        _write_book(tmp_path),
        client=_refusing_client(),
        url=test_database_url,
    )

    assert code == EXIT_REFUSED
    assert _completions(test_database_url) == [
        ("synthetic-vst-0", SLOT_NOON.isoformat(), MID_SLOT.isoformat(), EXIT_REFUSED)
    ]


def test_a_daily_loss_halt_records_its_completion_with_exit_three(
    tmp_path, test_database_url
) -> None:
    """A halted slot finished too: exit 3 is an outcome, recorded as one.

    Without the row, a day spent halted would look to the heartbeat like a
    day the bot never ran — and the operator has already been told
    urgently, so the record is what keeps the two alerts from arguing.
    """
    book_path = _write_book(tmp_path)
    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    code, _ = _run(
        book_path,
        client=_client(balance=_funded_balance("9500")),
        url=test_database_url,
        now=datetime(2026, 10, 4, 12, 7, tzinfo=UTC),
    )

    assert code == EXIT_DAILY_LOSS_HALT
    assert _completions(test_database_url) == [
        (
            "synthetic-vst-0",
            SLOT_MORNING.isoformat(),
            datetime(2026, 10, 4, 8, 7, tzinfo=UTC).isoformat(),
            EXIT_OK,
        ),
        (
            "synthetic-vst-0",
            SLOT_NOON.isoformat(),
            datetime(2026, 10, 4, 12, 7, tzinfo=UTC).isoformat(),
            EXIT_DAILY_LOSS_HALT,
        ),
    ]


def test_a_second_run_in_the_same_slot_appends_a_second_completion(
    tmp_path, test_database_url
) -> None:
    """The record is an append, never an upsert.

    Two runs inside one slot are two completions of it (the timer's
    catch-up), and the reader asks for the newest finish — so rewriting
    the row would hide exactly the fact the record exists to state.
    """
    book_path = _write_book(tmp_path)
    _run(book_path, client=_client(), url=test_database_url)
    code, _ = _run(book_path, client=_client(), url=test_database_url)

    assert code == EXIT_OK
    rows = _completions(test_database_url)
    assert len(rows) == 2
    assert {row[1] for row in rows} == {SLOT_NOON.isoformat()}


def test_the_newest_completion_is_answered_for_the_heartbeat(
    tmp_path, test_database_url
) -> None:
    """The read door feature 3 will ask through: newest finish, or nothing.

    An empty table answers ``None`` rather than a completion, because "no
    slot has finished" is the heartbeat's own urgent state, not a fault
    here.
    """
    book_path = _write_book(tmp_path)
    assert RouterSlotCompletionStore(test_database_url).newest() is None

    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        now=datetime(2026, 10, 4, 12, 7, tzinfo=UTC),
    )

    newest = RouterSlotCompletionStore(test_database_url).newest()
    assert newest == SlotCompletion(
        book_id="synthetic-vst-0",
        slot=SLOT_NOON,
        finished_at=datetime(2026, 10, 4, 12, 7, tzinfo=UTC),
        exit_code=EXIT_OK,
    )


def test_the_completion_store_refuses_an_exit_outside_the_specs_three(
    test_database_url,
) -> None:
    store = RouterSlotCompletionStore(test_database_url)
    with pytest.raises(RouterBingXRebalanceError) as refusal:
        store.record(
            book_id="synthetic-vst-0",
            slot=SLOT_NOON,
            finished_at=MID_SLOT,
            exit_code=2,
        )
    assert str(refusal.value).startswith(BINGX_REBALANCE_CODE)


def test_the_completion_store_refuses_a_row_it_could_not_have_written(
    tmp_path,
) -> None:
    """A moment no parser accepts fails to reconstruct, not to load."""
    url = f"sqlite:///{tmp_path / 'tampered.db'}"
    store = RouterSlotCompletionStore(url)
    store.ensure_schema()
    with sqlite3.connect(url.removeprefix("sqlite://")) as plain:
        plain.execute(
            f"INSERT INTO {ROUTER_SLOT_COMPLETION_TABLE} "
            "(book_id, slot, finished_at, exit_code) "
            "VALUES ('b', 'today', '2026-10-04T12:37:00+00:00', 0)"
        )

    with pytest.raises(RouterBingXRebalanceError) as refusal:
        store.newest()
    assert ROUTER_SLOT_COMPLETION_TABLE in str(refusal.value)


# -- ...then sends feature 1's alert ---------------------------------------------


def test_an_exit_zero_slot_sends_one_silent_info_alert(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """Info on 0: the slot's own summary, delivered silently.

    Every clause of the sentence's list is in the body — the legs placed,
    prior and skipped, the orders cancelled (one, the sweep took the
    resting order the morning slot left), the reconcile, the day's loss —
    and the message opens the way feature 1's sender formats every level:
    the level, the bot's name, then this body.  The figures are the
    summary line's own spellings, so the phone and the journal agree.
    """
    previous_id = _slot_identifier("synthetic-vst-0", SLOT_MORNING, "BTC-USDT")
    transport = _AlertTransport()
    code, _ = _run(
        _write_book(tmp_path),
        client=_client(
            open_orders=[{"symbol": "BTC-USDT", "clientOrderId": previous_id}]
        ),
        url=test_database_url,
        env=_alert_env(),
        transport=transport,
    )

    assert code == EXIT_OK
    body = _alert_body(transport)
    assert body["disable_notification"] is True
    text = body["text"]
    assert text.startswith(f"{INFO}: {BOT_NAME}\n\n")
    summary = text.removeprefix(f"{INFO}: {BOT_NAME}\n\n")
    assert summary == "\n".join(
        (
            f"The {SLOT_NOON.isoformat()} slot for book synthetic-vst-0 exited 0.",
            "Orders: 5 placed, 0 prior, 2 skipped by the gates.",
            "Cancelled 1 resting order(s) left by earlier slots.",
            "The previous slot was reconciled: no.",
            "The day's loss is 0.0000 USDT against the limit 300.00 USDT.",
        )
    )
    # The token rides the request URL's path — the Bot API's own shape —
    # and appears on no captured surface.
    assert f"/bot{FAKE_TOKEN}/sendMessage" in transport.calls[0][1]
    _assert_no_token_anywhere(capsys, caplog)


def test_the_info_alert_names_a_reconciled_previous_slot(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """The reconcile clause on its writing branch.

    The 12:00 slot reconciles the 08:00 one from its recorded terms, so
    the body states the previous slot *was* reconciled — the fact the
    sentence asks the summary to carry, not a figure derived from one.
    """
    book_path = _write_book(tmp_path)
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        store=store,
        limiter=limiter,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    afternoon = _client()
    afternoon._query_answers = _filled_answers(
        store, book_id="synthetic-vst-0", slot=SLOT_MORNING
    )
    transport = _AlertTransport()
    code, _ = _run(
        book_path,
        client=afternoon,
        url=test_database_url,
        store=store,
        limiter=limiter,
        env=_alert_env(),
        transport=transport,
    )

    assert code == EXIT_OK
    assert "The previous slot was reconciled: yes." in _alert_body(transport)["text"]
    _assert_no_token_anywhere(capsys, caplog)


def test_an_exit_one_slot_sends_one_warning_alert_listing_each_refused_leg(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """Warning on 1: each refused symbol, with its code and its message.

    The listing answers the summary line's own ``refused`` entries — same
    symbols, same code, same message — so the phone and the journal state
    one refusal, and the alert rings.
    """
    transport = _AlertTransport()
    code, lines = _run(
        _write_book(tmp_path),
        client=_refusing_client(),
        url=test_database_url,
        env=_alert_env(),
        transport=transport,
    )

    assert code == EXIT_REFUSED
    body = _alert_body(transport)
    assert body["disable_notification"] is False
    text = body["text"]
    assert text.startswith(f"{WARNING}: {BOT_NAME}\n\n")
    refused = lines[0]["refused"]
    assert len(refused) == 1
    assert (
        f"- {refused[0]['symbol']}: 101215 "
        "— the PostOnly order would have crossed the book" in text
    )
    _assert_no_token_anywhere(capsys, caplog)


def test_a_breach_slot_sends_one_urgent_alert_naming_loss_limit_and_reset(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """Urgent on 3, on the branch that tripped the halt this run.

    The day's loss (499.2781, the recorded equity against 9500), the limit
    (300.00, 3% of the book's equity, the guard's own spelling) and the
    manual reset — the three things the sentence says the urgent alert
    names, and the alert rings.
    """
    book_path = _write_book(tmp_path)
    _run(
        book_path,
        client=_client(),
        url=test_database_url,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    transport = _AlertTransport()
    code, _ = _run(
        book_path,
        client=_client(balance=_funded_balance("9500")),
        url=test_database_url,
        now=datetime(2026, 10, 4, 12, 7, tzinfo=UTC),
        env=_alert_env(),
        transport=transport,
    )

    assert code == EXIT_DAILY_LOSS_HALT
    body = _alert_body(transport)
    assert body["disable_notification"] is False
    text = body["text"]
    assert text.startswith(f"{URGENT}: {BOT_NAME}\n\n")
    assert (
        "The day's loss 499.2781 USDT passed the daily loss limit 300.00 USDT."
        in text
    )
    assert "manual reset" in text
    assert "risk.daily_loss.manual_reset" in text
    assert f"The {SLOT_NOON.isoformat()} slot for book synthetic-vst-0" in text
    _assert_no_token_anywhere(capsys, caplog)


def test_a_standing_halt_slot_sends_one_urgent_alert_from_the_halt_record(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """Urgent on 3, on the branch where the halt already stood.

    No check was run this slot — the guard refused before reading the
    venue — so the figures the alert names come from the halt record
    feature 325 wrote when the breach tripped, carried on the refusal
    itself and spelled the way that member's own summary spells them.
    """
    halt_on_daily_loss(
        daily_loss=400.0,
        daily_loss_limit=300.0,
        database_url=test_database_url,
    )
    transport = _AlertTransport()
    code, _ = _run(
        _write_book(tmp_path),
        client=_client(),
        url=test_database_url,
        env=_alert_env(),
        transport=transport,
    )

    assert code == EXIT_DAILY_LOSS_HALT
    text = _alert_body(transport)["text"]
    assert "The day's loss 400.0 USDT passed the daily loss limit 300.0 USDT." in text
    assert "risk.daily_loss.manual_reset" in text
    _assert_no_token_anywhere(capsys, caplog)


def test_the_alert_follows_the_summary_line(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """The record and the alert come after the summary line is emitted.

    The spec's own order, held on a shared journal: the line first (the
    outcome on the record), then the one alert that reports it.
    """
    journal: list[str] = []
    transport = _AlertTransport(journal=journal)
    code = main(
        ["--book", str(_write_book(tmp_path))],
        client=_client(),
        limiter=_CountingLimiter(),
        env=_alert_env(),
        database_url=test_database_url,
        now=lambda: MID_SLOT,
        clock=_clock,
        sleep=lambda _d: None,
        transport=transport,
        emit=lambda _line: journal.append("summary"),
    )

    assert code == EXIT_OK
    assert journal == ["summary", "alert"]
    _assert_no_token_anywhere(capsys, caplog)


# -- ...without changing it ------------------------------------------------------


def test_the_outcome_is_identical_whether_alerting_succeeds_fails_or_is_unconfigured(
    tmp_path, capsys, caplog
) -> None:
    """The spec's own constraint, on three identical slots.

    Three fresh stores, three fresh clients, one book, one moment: the
    alert is delivered, refused by the Bot API, or never configured — and
    the exit code, the whole summary line and every order the venue saw
    are the same three times.  The one difference is the log.
    """
    book_path = _write_book(tmp_path)
    delivered = _AlertTransport()
    refused = _AlertTransport(alert_fixtures._refused())
    unconfigured = _AlertTransport()

    runs: list[tuple[int, list[dict], list]] = []
    for name, environment, transport in (
        ("delivered", _alert_env(), delivered),
        ("refused_by_the_bot_api", _alert_env(), refused),
        ("unconfigured", {}, unconfigured),
    ):
        url = f"sqlite:///{tmp_path / name}.db"
        client = _client()
        code, lines = _run(
            book_path,
            client=client,
            url=url,
            env=environment,
            transport=transport,
        )
        runs.append((code, lines, [str(order) for order in client.placed]))

    assert [code for code, _, _ in runs] == [EXIT_OK] * 3
    lines = [line for _, run_lines, _ in runs for line in run_lines]
    assert len(lines) == 3
    assert lines[0] == lines[1] == lines[2]
    placed = [orders for _, _, orders in runs]
    assert placed[0] == placed[1] == placed[2]
    assert len(placed[0]) == 5
    # One alert left per configured slot, none from the unconfigured one.
    assert len(delivered.calls) == 1
    assert len(refused.calls) == 1
    assert unconfigured.calls == []
    _assert_no_token_anywhere(capsys, caplog)


def test_an_alert_that_raises_is_caught_and_logged(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """A raising alert is one log line — never a changed outcome.

    The raise is staged with the bot path inside it, the worst case this
    module's own log line could meet: the line that lands is scrubbed, the
    slot still exits 0, its summary line still prints and its completion
    was still recorded before the alert was ever attempted.
    """

    def raising_alert(
        level: str, text: str, *, env: object = None, transport: object = None
    ) -> bool:
        raise RuntimeError(
            f"connection error posting "
            f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
        )

    book_path = _write_book(tmp_path)
    code, lines = _run(
        book_path,
        client=_client(),
        url=test_database_url,
        env=_alert_env(),
        alert=raising_alert,
    )

    assert code == EXIT_OK
    assert len(lines) == 1
    assert _completions(test_database_url) == [
        ("synthetic-vst-0", SLOT_NOON.isoformat(), MID_SLOT.isoformat(), EXIT_OK)
    ]
    assert "alert raised and was caught" in caplog.text
    assert "/bot<redacted>" in caplog.text
    _assert_no_token_anywhere(capsys, caplog)


def test_a_completion_that_cannot_be_recorded_is_logged_and_the_alert_still_leaves(
    tmp_path, test_database_url, capsys, caplog
) -> None:
    """The record's fault is one log line too — and never silence.

    A slot that could not be recorded still alerts: the two acts are
    separately wrapped, because a store that cannot take the row is no
    reason to keep the operator uninformed about the outcome itself.
    """

    class _BrokenStore:
        def record(self, **_kwargs) -> None:
            raise sqlite3.OperationalError("disk I/O error")

    transport = _AlertTransport()
    code, lines = _run(
        _write_book(tmp_path),
        client=_client(),
        url=test_database_url,
        env=_alert_env(),
        transport=transport,
        completion_store=_BrokenStore(),
    )

    assert code == EXIT_OK
    assert len(lines) == 1
    assert len(transport.calls) == 1
    assert "could not be recorded" in caplog.text
    _assert_no_token_anywhere(capsys, caplog)


# -- The systemd unit supplies its own environment -----------------------------
#
# The bug this suite's tail closes: the unit assumed the operator's
# interactive shell.  A systemd user service inherits neither the
# ``OP_SERVICE_ACCOUNT_TOKEN`` ``~/.zshrc`` exports from
# ``~/.config/op/service-token`` nor the ``~/.local/bin`` that holds ``uv``,
# so every slot failed — first on ``op`` ("No accounts configured"), then,
# once the token was supplied, on ``uv`` ("executable file not found in
# $PATH").  The service must carry both itself, and the token value must
# never appear in the unit, the repository or a log line.
#
# These tests read the *shipped* unit, not a copy: the file the operator
# links into ``~/.config/systemd/user/`` is the one pinned here.  Nothing is
# installed or enabled, and no test opens a socket.

UNIT_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "systemd"
    / "nullius-vst-rebalance.service"
)

#: The unit's own spelling of the operator's home, and of the token file
#: ``~/.zshrc`` loads the token from (mode 0600, outside the repository).
UNIT_HOME_SPECIFIER = "%h"
TOKEN_FILE_SUFFIX = "/.config/op/service-token"


def _unit_text() -> str:
    return UNIT_PATH.read_text(encoding="utf-8")


def _unit_directive(name: str) -> str:
    """The single directive line ``name`` in the shipped unit.

    A directive that is absent is a *failure* — systemd would fall back to
    its own inherited environment, which is exactly the defect — so the
    absence is reported by index rather than silently skipped.  The
    ``Environment=PATH`` and ``ExecStart`` lines are each expected exactly
    once; a second would shadow the first.
    """
    matches = [
        line
        for line in _unit_text().splitlines()
        if line.startswith(f"{name}=")
    ]
    assert matches, f"the unit declares no {name}="
    assert len(matches) == 1, f"the unit declares {name}= more than once"
    return matches[0]


def _systemd_expand(command: str, *, home: str) -> str:
    """The line's text as systemd hands it to the kernel, minimally.

    Only the two substitutions the unit actually uses are applied, both
    documented in ``systemd.service(5)``: the ``%h`` specifier becomes the
    operator's home, and a literal ``$$`` becomes a single ``$`` (systemd's
    own escape for a dollar sign it must not itself expand).  A bare ``$``
    would otherwise be consumed by systemd as an environment substitution
    before the shell ever saw it, so the escape is load-bearing, and this
    helper is deliberately strict about the only transformation being the
    documented one.
    """
    return command.replace("$$", "$").replace(UNIT_HOME_SPECIFIER, home)


def test_the_unit_puts_the_operators_local_bin_before_the_system_path() -> None:
    """The first defect: ``uv`` lives in ``%h/.local/bin``, not the system PATH.

    A systemd user service is handed the manager's PATH, never a login
    shell's, so ``Environment=PATH`` must name both the operator's tools and
    the system directories — with ``%h/.local/bin`` *first*, so the pinned
    ``uv`` wins over any system copy.
    """
    environment = _unit_directive("Environment")
    assert environment.startswith("Environment=PATH=")
    path = environment.removeprefix("Environment=PATH=")
    entries = path.split(":")
    assert entries[:4] == [
        f"{UNIT_HOME_SPECIFIER}/.local/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]


def test_the_unit_execstart_loads_the_token_file_not_a_literal() -> None:
    """The second defect: ``op`` needs the token the login shell exports.

    The ExecStart must load ``OP_SERVICE_ACCOUNT_TOKEN`` from
    ``%h/.config/op/service-token`` at start — inside the shell it invokes,
    with the literal-dollar escape systemd requires — rather than assuming
    the variable is already in its environment.
    """
    exec_start = _unit_directive("ExecStart")
    assert "op run" not in exec_start or "/bin/sh" in exec_start
    assert exec_start.removeprefix("ExecStart=").startswith("/bin/sh -c ")
    assert "OP_SERVICE_ACCOUNT_TOKEN=" in exec_start
    # The value is read from the operator's file, never written in.  Both
    # substitutions are applied together: systemd turns `%h` into the home,
    # and the escaped `$$` into the single `$` the shell then runs.
    expanded = _systemd_expand(exec_start, home="/home/operator")
    assert f"$(cat /home/operator{TOKEN_FILE_SUFFIX})" in expanded
    # The dollar of that command substitution is escaped in the *source*, so
    # it survives the manager's own expansion and reaches the shell.
    assert "$$(cat" in exec_start


def test_the_unit_carries_no_literal_service_account_token() -> None:
    """No token, key or secret is ever written into a repository file.

    1Password service-account tokens carry an ``ops_`` prefix; the unit must
    contain no such string, and no assignment of a literal value to the
    token variable — its only occurrence is the ``cat`` of the operator's
    own file.
    """
    text = _unit_text()
    assert "ops_" not in text
    # The *executable* lines carry the token — comments may name the variable
    # without assigning it, which is documentation, not a leak.
    for index, line in enumerate(text.splitlines(), start=1):
        if line.startswith("#") or "OP_SERVICE_ACCOUNT_TOKEN" not in line:
            continue
        # The single legitimate shape: the variable is *assigned from* the
        # token file.  Any other assignment (e.g. a literal value, or a bare
        # environment pass) is a token whose provenance the unit does not
        # control.
        assert "OP_SERVICE_ACCOUNT_TOKEN=" in line, (
            f"line {index} mentions the token without assigning it from the file"
        )
        assert "cat" in line and TOKEN_FILE_SUFFIX in line


def _unit_environment(home: Path) -> dict[str, str]:
    """The environment systemd would give the unit's own ``ExecStart``.

    Only the keys ``Environment=PATH`` declares are supplied — a systemd
    user service inherits the manager's environment, whose PATH is the one
    this line overwrites — plus ``HOME`` (which is how ``%h`` resolves) and
    ``USER``.  Nothing else, so the test is the ``env -i`` proof the bug
    report asks for: if the unit does not supply PATH and the token itself,
    the child does not see them.
    """
    path = _unit_directive("Environment").removeprefix("Environment=PATH=")
    return {
        "PATH": _systemd_expand(path, home=str(home)),
        "HOME": str(home),
        "USER": "operator",
    }


def _unit_exec_start(home: Path) -> str:
    """The ExecStart, as systemd's substitutions leave it for the shell."""
    return _systemd_expand(
        _unit_directive("ExecStart").removeprefix("ExecStart="), home=str(home)
    )


def _run_unit(tmp_path: Path, *, token: str | None) -> subprocess.CompletedProcess:
    """Exercise the shipped ExecStart in a systemd-like environment.

    ``%h`` is the temporary home, so ``%h/projects/nullius/run.sh`` is a stub
    written here rather than the repository's own wrapper — the point is the
    environment that reaches it, not what the wrapper then does.  The stub
    records the token and PATH it was handed, so a passing run can assert
    they *arrived* rather than merely that the process exited 0.
    """
    home = tmp_path / "home"
    repo = home / "projects" / "nullius"
    repo.mkdir(parents=True)
    marker = tmp_path / "stub-env.txt"
    stub = repo / "run.sh"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "TOKEN=%s\\nPATH=%s\\n" "$OP_SERVICE_ACCOUNT_TOKEN" "$PATH" '
        f'> "{marker}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    if token is not None:
        token_file = home / ".config" / "op" / "service-token"
        token_file.parent.mkdir(parents=True)
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(0o600)

    result = subprocess.run(
        ["/bin/sh", "-c", _unit_exec_start(home)],
        cwd=repo,
        env=_unit_environment(home),
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def test_a_missing_token_file_makes_the_unit_fail_clearly(tmp_path: Path) -> None:
    """Fails closed: no token file means the unit stops, it does not run ``op``.

    The ExecStart is exercised in an ``env -i`` environment built from the
    unit's own ``Environment=PATH``, with ``run.sh`` replaced by a stub.  A
    missing token file must yield a non-zero exit *outside* the unit's own
    ``SuccessExitStatus`` (0, 1, 3 — a refusal, not a failure), so systemd
    records it as failed rather than green, with a message naming the file;
    and ``run.sh`` must never have been reached.
    """
    result = _run_unit(tmp_path, token=None)

    assert result.returncode not in (0, 1, 3), result.stderr
    assert TOKEN_FILE_SUFFIX in result.stderr
    # The unit's own message, not merely whatever `cat` printed — so a failure
    # names the token file rather than looking like an unrelated command error.
    assert "unreadable" in result.stderr
    assert not (tmp_path / "stub-env.txt").exists()


def test_the_exec_start_hands_path_and_token_to_run_sh(tmp_path: Path) -> None:
    """The whole clause: both defects, on the command the unit actually ships.

    The ExecStart runs against a stub ``run.sh`` in a bare environment.  Both
    things the interactive shell used to provide must reach the child: the
    ``%h/.local/bin`` PATH entry (where ``uv`` lives) and the token read from
    ``%h/.config/op/service-token`` — the value itself never written into the
    unit, only read from the operator's file at start.
    """
    # A synthetic placeholder, in a temporary directory — not a credential,
    # and deliberately not shaped like one.
    token = "token-value-read-from-the-operators-file"
    result = _run_unit(tmp_path, token=token)

    assert result.returncode == 0, result.stderr
    recorded = (tmp_path / "stub-env.txt").read_text(encoding="utf-8")
    assert f"TOKEN={token}\n" in recorded
    path_line = next(
        line for line in recorded.splitlines() if line.startswith("PATH=")
    )
    first_entry = path_line.removeprefix("PATH=").split(":")[0]
    assert first_entry == str(tmp_path / "home" / ".local" / "bin")
