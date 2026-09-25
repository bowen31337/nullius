"""Feature 323: the halt door — ``POST /risk/halt``.

The suite is organised around the sentence's two claims and the one law that
binds them:

* **It flattens open positions.**  After a halt, the engine reports nothing
  standing — every order cancelled, every position closed — and the response
  carries the completed flatten that proves it.
* **It rejects new order submission.**  Not by a second enforcement the door
  performs, but by the *consequence* of the kill it sent: once the halt has
  returned, ``risk.require_orders_allowed`` over the same store refuses under
  the standing instruction, exactly as the order layer's submission path does.
* **The order is the law.**  The kill is sent first (so the standing
  instruction is on record before anything is flattened) and the flatten is
  driven second (so its authority check finds the kill it just sent); a halt
  over an already-killed channel writes nothing and returns the first kill's
  record while still flattening.

The refusals are the third subject — a flatten that cannot complete propagates
``RiskFlattenError`` and the kill still stands; a request that carries no
engine is refused by name — and the door's own discipline is the fourth: it
holds no caller-supplied kill moment or sender label (both default to the
instant and the kernel-read identity), it resolves both faces from
``DATABASE_URL`` and returns ``None`` when nothing names a store, and it is
duck-checked, not isinstance-guarded, because the composed faces are
structurally the right shape but never the same class object a direct import
yields.

The cross-process case is proven against an actual second interpreter, as the
channel's and flatten's suites do: a halt a separate supervisor process
pronounces is a kill the order layer's guard refuses under.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest
from risk._identity import process_identity
from risk.errors import (
    FLATTEN_CODE,
    ORDERS_KILLED_CODE,
    RiskFlattenError,
    RiskOrdersKilledError,
    RiskStoreError,
)
from risk.flatten import FLATTEN_STATUS_COMPLETED, FlattenResult
from risk.halt import (
    DATABASE_URL_ENV,
    RISK_HALT_ROUTE,
    HaltEndpoint,
    HaltRequest,
)
from risk.kill import (
    KILL_INSTRUCTION,
    RISK_ORDER_KILL_TABLE,
    KillInstruction,
    RiskKillSwitch,
    require_orders_allowed,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

SENT = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)


class _StubEngine:
    """The execution engine's face, as a test double.

    Reports the orders and positions it is seeded with and drives them away
    when told to, so a halt over it ends with nothing standing. A residue is
    staged by refusing to drive a named id, the way the flatten's refusals
    need.
    """

    def __init__(
        self,
        orders: tuple[str, ...] = (),
        positions: tuple[str, ...] = (),
        *,
        refuse_close: tuple[str, ...] = (),
    ) -> None:
        self._orders = list(orders)
        self._positions = list(positions)
        self._refuse_close = set(refuse_close)
        self.cancel_calls: list[str] = []
        self.close_calls: list[str] = []

    def open_orders(self) -> tuple[str, ...]:
        return tuple(self._orders)

    def cancel_order(self, order_id: str) -> dict[str, str]:
        self.cancel_calls.append(order_id)
        self._orders = [o for o in self._orders if o != order_id]
        return {"client_order_id": order_id, "status": "CANCELED"}

    def open_positions(self) -> tuple[str, ...]:
        return tuple(self._positions)

    def close_position(self, symbol: str) -> dict[str, str]:
        self.close_calls.append(symbol)
        if symbol in self._refuse_close:
            raise RuntimeError(f"venue refused to close {symbol}")
        self._positions = [p for p in self._positions if p != symbol]
        return {"symbol": symbol, "status": "CLOSED"}


def _endpoint(test_database_url: str) -> HaltEndpoint:
    return HaltEndpoint.from_env({DATABASE_URL_ENV: test_database_url})  # type: ignore[arg-type]


def _row_count(database_url: str) -> int:
    """How many rows the kill table holds, read with the driver directly.

    The one-row law is stated in the schema, so the test that pins it reads
    the table without going through any face whose discipline the law exists
    to replace.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {RISK_ORDER_KILL_TABLE}"
            ).fetchone()[0]
        )


# -- It sends the kill, then flattens the book -------------------------------------


class TestTheHaltDoorDrivesBothActs:
    def test_a_halt_flattens_the_book(self, test_database_url: str) -> None:
        engine = _StubEngine(orders=("order-a", "order-b"), positions=("BTCUSDT", "ETHUSDT"))
        response = _endpoint(test_database_url).post(HaltRequest(execution_engine=engine))

        assert response.result.status == FLATTEN_STATUS_COMPLETED
        assert set(response.result.cancelled_orders) == {"order-a", "order-b"}
        assert set(response.result.closed_positions) == {"BTCUSDT", "ETHUSDT"}
        # The book is actually flat — the engine's own re-reading reports
        # nothing standing, which is the flatten's completion check.
        assert engine.open_orders() == ()
        assert engine.open_positions() == ()

    def test_the_kill_is_sent_before_the_flatten(self, test_database_url: str) -> None:
        # The standing instruction must be on record before the flatten
        # runs, because a flatten under no standing kill is refused by the
        # flatten's own authority check — so the send precedes the drive.
        engine = _StubEngine(orders=("order-a",), positions=("BTCUSDT",))
        endpoint = _endpoint(test_database_url)

        instruction = endpoint.post(HaltRequest(execution_engine=engine)).instruction

        # The kill is standing on the channel — the order layer's guard
        # refuses under it, which is the "rejects new order submission"
        # half of the sentence, proven through the channel that owns it.
        standing = RiskKillSwitch(test_database_url).standing()
        assert standing is not None
        assert standing.instruction == KILL_INSTRUCTION
        # The standing row and the sent instruction are the same record;
        # only the read-back's ``changed`` bit differs (a read wrote
        # nothing), so the identity is asserted on the fields that are the
        # record, not the bit that is the call.
        assert standing.instruction == instruction.instruction
        assert standing.supervisor_process_id == instruction.supervisor_process_id
        assert standing.sent_at == instruction.sent_at

    def test_the_response_carries_both_records(self, test_database_url: str) -> None:
        engine = _StubEngine(orders=("order-a",), positions=("BTCUSDT",))
        response = _endpoint(test_database_url).post(HaltRequest(execution_engine=engine))

        # The kill: which process killed, and when — first-write-wins.
        assert isinstance(response.instruction, KillInstruction)
        assert response.instruction.supervisor_process_id == process_identity()
        # The flatten: what was driven, completed.
        assert isinstance(response.result, FlattenResult)
        assert response.result.status == FLATTEN_STATUS_COMPLETED

    def test_an_already_flat_book_halts_trivially(self, test_database_url: str) -> None:
        engine = _StubEngine()
        response = _endpoint(test_database_url).post(HaltRequest(execution_engine=engine))

        assert response.result.status == FLATTEN_STATUS_COMPLETED
        assert response.result.cancelled_orders == ()
        assert response.result.closed_positions == ()
        assert RiskKillSwitch(test_database_url).killed() is True

    def test_the_route_is_spelled_once(self) -> None:
        assert HaltEndpoint.route == RISK_HALT_ROUTE == "/risk/halt"


# -- Rejects new order submission is the consequence -------------------------------


class TestTheHaltRejectsNewOrderSubmission:
    def test_the_order_layer_refuses_after_a_halt(self, test_database_url: str) -> None:
        # The rejection is not a third act the door performs — it is the
        # consequence of the kill it sent. The order layer's own guard
        # (feature 322) refuses under the standing instruction.
        engine = _StubEngine(orders=("order-a",), positions=("BTCUSDT",))
        _endpoint(test_database_url).post(HaltRequest(execution_engine=engine))

        with pytest.raises(RiskOrdersKilledError) as excinfo:
            require_orders_allowed(database_url=test_database_url)

        assert ORDERS_KILLED_CODE in str(excinfo.value)


# -- The order is the law ------------------------------------------------------------


class TestTheOrderIsTheLaw:
    def test_a_halt_over_an_already_killed_channel_returns_the_first_kill(
        self, test_database_url: str
    ) -> None:
        # First halt: the channel is killed and the book flattened.
        first = _endpoint(test_database_url).post(
            HaltRequest(execution_engine=_StubEngine(orders=("o1",), positions=("P1",)))
        )
        assert first.instruction.changed is True

        # Second halt over the already-killed channel: the kill writes
        # nothing (first-write-wins) and returns the first kill's record,
        # while still flattening the new book.
        second = _endpoint(test_database_url).post(
            HaltRequest(execution_engine=_StubEngine(orders=("o2",), positions=("P2",)))
        )
        assert second.instruction.changed is False
        assert second.instruction.sent_at == first.instruction.sent_at
        assert second.instruction.supervisor_process_id == first.instruction.supervisor_process_id
        # ...but the book is still flattened.
        assert second.result.status == FLATTEN_STATUS_COMPLETED
        assert second.result.cancelled_orders == ("o2",)
        assert second.result.closed_positions == ("P2",)

    def test_a_halt_writes_one_kill_row(self, test_database_url: str) -> None:
        _endpoint(test_database_url).post(
            HaltRequest(execution_engine=_StubEngine(orders=("o1",), positions=("P1",)))
        )
        _endpoint(test_database_url).post(
            HaltRequest(execution_engine=_StubEngine(orders=("o2",), positions=("P2",)))
        )
        # The kill is one row — the channel's one-row law, not the door's
        # discipline. The door sends through the channel, and the channel
        # holds one.
        assert _row_count(test_database_url) == 1

    def test_the_flatten_uses_the_kill_it_just_sent(self, test_database_url: str) -> None:
        # The flatten's authority check must pass, because the send wrote
        # the row first-write-wins and the flatten reads it back — the two
        # acts are one row in one database.
        engine = _StubEngine(orders=("o1",), positions=("P1",))
        response = _endpoint(test_database_url).post(HaltRequest(execution_engine=engine))
        # The flatten acted under the standing kill — same sender, the
        # kernel-read identity of this process.
        assert response.result.instruction.supervisor_process_id == process_identity()


# -- Refusals propagate, unchanged -----------------------------------------------


class TestTheRefusalsPropagate:
    def test_a_flatten_that_cannot_complete_propagates_the_flattens_refusal(
        self, test_database_url: str
    ) -> None:
        # A position whose close refuses leaves a residue — the flatten
        # cannot complete, and the door propagates the flatten's own
        # refusal rather than composing one of its own.
        engine = _StubEngine(orders=("o1",), positions=("P1",), refuse_close=("P1",))

        with pytest.raises(RiskFlattenError) as excinfo:
            _endpoint(test_database_url).post(HaltRequest(execution_engine=engine))

        # The flatten's own grep token, inherited unchanged.
        assert FLATTEN_CODE in str(excinfo.value)
        # ...and the kill still stands — the door sent it before the
        # flatten, so the order layer is refused even though the book is
        # not flat.
        assert RiskKillSwitch(test_database_url).killed() is True

    def test_a_request_without_an_engine_is_refused(self, test_database_url: str) -> None:
        with pytest.raises(RiskFlattenError) as excinfo:
            HaltRequest(execution_engine=None)  # type: ignore[arg-type]
        assert FLATTEN_CODE in str(excinfo.value)


# -- The door holds no caller-supplied moment or label -----------------------------


class TestTheDoorDefaultsTheMomentAndSender:
    def test_the_kill_moment_defaults_to_the_instant(self, test_database_url: str) -> None:
        before = datetime.now(UTC)
        response = _endpoint(test_database_url).post(
            HaltRequest(execution_engine=_StubEngine())
        )
        after = datetime.now(UTC)
        # The kill's moment is the instant of the call — defaulted at the
        # act, never accepted from the caller — so the standing row names
        # when the halt actually happened.
        assert before <= response.instruction.sent_at <= after
        assert response.instruction.sent_at.tzinfo is not None

    def test_a_clock_is_honoured_when_supplied(self, test_database_url: str) -> None:
        response = _endpoint(test_database_url).post(
            HaltRequest(execution_engine=_StubEngine()), clock=lambda: SENT
        )
        assert response.instruction.sent_at == SENT
        assert response.result.flattened_at == SENT

    def test_the_sender_is_the_kernel_read_identity(self, test_database_url: str) -> None:
        response = _endpoint(test_database_url).post(
            HaltRequest(execution_engine=_StubEngine())
        )
        # The label is read from the kernel, not accepted from the caller —
        # a deployment-settable one is a label the strategy process could
        # borrow.
        assert response.instruction.supervisor_process_id == process_identity()


# -- The values are frozen ---------------------------------------------------------


class TestTheValuesAreFrozen:
    def test_the_request_is_frozen(self) -> None:
        request = HaltRequest(execution_engine=_StubEngine())
        with pytest.raises(FrozenInstanceError):
            request.execution_engine = _StubEngine()  # type: ignore[misc]

    def test_the_response_is_frozen(self, test_database_url: str) -> None:
        response = _endpoint(test_database_url).post(HaltRequest(execution_engine=_StubEngine()))
        with pytest.raises(FrozenInstanceError):
            response.result = None  # type: ignore[misc]


# -- Construction ------------------------------------------------------------------


class TestConstruction:
    def test_from_env_returns_none_without_a_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        assert HaltEndpoint.from_env() is None

    def test_from_env_resolves_both_faces(self, test_database_url: str) -> None:
        endpoint = HaltEndpoint.from_env({DATABASE_URL_ENV: test_database_url})  # type: ignore[arg-type]
        assert isinstance(endpoint.switch, RiskKillSwitch)
        assert endpoint.flattener is not None

    def test_the_endpoint_is_duck_checked_not_isinstance_guarded(
        self, test_database_url: str
    ) -> None:
        # The composed faces are structurally the right shape but never the
        # same class object a direct import yields, so the endpoint checks
        # the seams it drives, not the type. A face missing a seam is
        # refused by name.
        class _NoSend:
            pass

        class _NoFlatten:
            def send(self):  # pragma: no cover - never called
                return None

        good_switch = RiskKillSwitch(test_database_url)
        with pytest.raises(TypeError, match="send"):
            HaltEndpoint(_NoSend(), good_switch)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="flatten"):
            HaltEndpoint(good_switch, _NoFlatten())  # type: ignore[arg-type]

    def test_construction_touches_no_database(self, tmp_path: Path) -> None:
        database = tmp_path / "not-yet.db"
        HaltEndpoint.from_env({DATABASE_URL_ENV: f"sqlite:///{database}"})  # type: ignore[arg-type]
        # Composing the door is always safe — the schema is created on the
        # first send or flatten, not on construction.
        assert not database.exists()


# -- The door composes, never owns -------------------------------------------------


class TestTheDoorComposesNeverOwns:
    def test_a_bad_store_is_the_channels_address_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A URL this member cannot speak is refused as an *address* fault,
        # in the store's own vocabulary — the door inherits the channel's
        # and the flatten's refusals, it composes none of its own. The
        # refusal surfaces at the act (construction touches no database),
        # exactly as the channel's and flatten's own address checks do.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        endpoint = HaltEndpoint.from_env({DATABASE_URL_ENV: "postgres:///nope"})  # type: ignore[arg-type]
        assert endpoint is not None
        with pytest.raises(RiskStoreError):
            endpoint.post(HaltRequest(execution_engine=_StubEngine()))

    def test_the_door_owns_no_schema(self, test_database_url: str) -> None:
        # The halt door owns no table — the kill lands in the channel's
        # risk_order_kill and the flatten writes nothing. Only that one
        # table exists after a halt. (The kill table is INTEGER PRIMARY
        # KEY, not AUTOINCREMENT, so there is no sqlite_sequence table —
        # the door adds no schema of its own, and neither does the
        # channel's one-row law.)
        _endpoint(test_database_url).post(HaltRequest(execution_engine=_StubEngine()))
        path = test_database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        assert tables == {RISK_ORDER_KILL_TABLE}


# -- The cross-process case --------------------------------------------------------


class TestAcrossProcesses:
    def test_a_halt_a_separate_process_pronounces_is_a_kill_the_guard_refuses(
        self, test_database_url: str, tmp_path: Path
    ) -> None:
        # The supervisor that pronounces the halt and the order layer that
        # refuses under it are different processes — the deployment the
        # feature's own first clause names. A halt a separate supervisor
        # process pronounces is a kill this process's guard refuses under,
        # over the same shared store.
        supervisor_script = f"""
import sys
import risk
from risk.halt import HaltEndpoint, HaltRequest

class Engine:
    def __init__(self):
        self.orders = ['order-a', 'order-b']
        self.positions = ['BTCUSDT']

    def open_orders(self):
        return tuple(self.orders)

    def cancel_order(self, order_id):
        self.orders = [o for o in self.orders if o != order_id]
        return {{'client_order_id': order_id, 'status': 'CANCELED'}}

    def open_positions(self):
        return tuple(self.positions)

    def close_position(self, symbol):
        self.positions = [p for p in self.positions if p != symbol]
        return {{'symbol': symbol, 'status': 'CLOSED'}}

endpoint = risk.HaltEndpoint.from_env()
response = endpoint.post(HaltRequest(execution_engine=Engine()))
print(response.result.status,
      ','.join(response.result.cancelled_orders),
      ','.join(response.result.closed_positions))
"""
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "risk" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", supervisor_script],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        status, cancelled, closed = result.stdout.strip().split(" ", 2)
        assert status == FLATTEN_STATUS_COMPLETED
        assert cancelled == "order-a,order-b"
        assert closed == "BTCUSDT"

        # The kill the separate supervisor sent is standing here — the
        # order layer's guard in this process refuses under it, over the
        # same shared store. The two processes share one row.
        with pytest.raises(RiskOrdersKilledError) as excinfo:
            require_orders_allowed(database_url=test_database_url)
        assert ORDERS_KILLED_CODE in str(excinfo.value)
        assert RiskKillSwitch(test_database_url).killed() is True
