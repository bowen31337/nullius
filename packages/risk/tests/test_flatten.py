"""Feature 330: the flatten that survives a hung strategy process.

The suite is organised around the sentence's three claims, because they
are the three things that can silently stop being true:

* **It flattens.**  The supervisor drives the engine's own verbs —
  enumerate, cancel each order, enumerate again for the positions,
  close each — and returns a record of exactly the work it drove, under
  exactly the kill instruction it read, in its own process's name.
* **Even when the strategy process is hung.**  The flatten's path
  consults nothing the strategy process serves, and — the deeper half
  of the claim — performs **no store write**: the one thing a hung
  strategy process can wedge from outside is the shared store's write
  lock, so the suite wedges it, on purpose, with a real second
  interpreter holding an open write transaction (an uncommitted halt
  event, mid-submission, exactly the way a strategy process dies), and
  flattens anyway — while a probe connection proves the store really
  was refusing writers for the whole duration.  The flattener also has
  no table of its own, and the suite pins that absence: no
  ``ensure_schema``, no rows in either of the member's tables.
* **It returns a completed flatten result.**  *Completed* is derived
  from the engine's own re-reading, never asserted: a cancellation
  that claims success but leaves the order standing, a close that
  closes nothing, an order that arrives mid-flatten, an engine that
  cannot be asked again — each refuses, and the value layer refuses to
  construct a result in any other status, so the type cannot lie.

The refusals are the fourth subject: a face missing its verbs, a
flatten under no standing kill, a module-level flatten that names no
store — each in its own class, each named by the grep token its
messages open with.
"""

from __future__ import annotations

import inspect
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
    RiskError,
    RiskFlattenError,
    RiskStoreError,
)
from risk.flatten import (
    DATABASE_URL_ENV,
    FLATTEN_STATUS_COMPLETED,
    FlattenResult,
    RiskFlattener,
    flatten_positions,
)
from risk.halt_events import RISK_HALT_EVENT_TABLE, RiskHaltEventStore
from risk.kill import (
    KILL_INSTRUCTION,
    RISK_ORDER_KILL_TABLE,
    KillInstruction,
    RiskKillSwitch,
    send_kill,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

SENT = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
FLATTENED = datetime(2026, 9, 25, 12, 5, 0, tzinfo=UTC)


@pytest.fixture
def switch(test_database_url: str) -> RiskKillSwitch:
    return RiskKillSwitch(test_database_url)


@pytest.fixture
def killed(switch: RiskKillSwitch) -> RiskKillSwitch:
    """A channel with a standing kill, sent by a named first supervisor."""
    switch.send(sent_at=SENT, supervisor_process_id="supervisor/4711")
    return switch


@pytest.fixture
def flattener(test_database_url: str) -> RiskFlattener:
    return RiskFlattener(test_database_url)


class _StubEngine:
    """The execution engine's face, as a test double with faults.

    Reports the orders and positions it is seeded with, drives them away
    when told to, and carries the fault knobs the refusals need: ids
    whose cancel or close raises, ids whose cancel or close "succeeds"
    while the thing stays standing (the receipt that lies), and ids that
    appear only on the second enumeration (the order that arrives
    mid-flatten).  Every knob is named for the refusal it stages.
    """

    def __init__(
        self,
        orders: tuple[str, ...] = (),
        positions: tuple[str, ...] = (),
        *,
        refuse_cancel: tuple[str, ...] = (),
        refuse_close: tuple[str, ...] = (),
        inert_cancel: tuple[str, ...] = (),
        inert_close: tuple[str, ...] = (),
        gone_cancel: tuple[str, ...] = (),
        late_orders: tuple[str, ...] = (),
        late_positions: tuple[str, ...] = (),
        refuse_recount: bool = False,
    ) -> None:
        self._orders = list(orders)
        self._positions = list(positions)
        self._refuse_cancel = set(refuse_cancel)
        self._refuse_close = set(refuse_close)
        self._inert_cancel = set(inert_cancel)
        self._inert_close = set(inert_close)
        self._gone_cancel = set(gone_cancel)
        self._late_orders = list(late_orders)
        self._late_positions = list(late_positions)
        self._refuse_recount = refuse_recount
        self.order_reads = 0
        self.position_reads = 0
        self.cancel_calls: list[str] = []
        self.close_calls: list[str] = []

    def open_orders(self) -> tuple[str, ...]:
        self.order_reads += 1
        if self.order_reads == 2:
            self._orders.extend(self._late_orders)
            if self._refuse_recount:
                raise RuntimeError("the engine cannot be asked again")
        return tuple(self._orders)

    def cancel_order(self, order_id: str) -> dict[str, str]:
        self.cancel_calls.append(order_id)
        if order_id in self._refuse_cancel:
            raise RuntimeError(f"venue refused to cancel {order_id}")
        if order_id in self._gone_cancel:
            # The venue's "unknown order": it filled and went in the
            # moment between the enumeration and the drive — the cancel
            # raises, and the re-read will not see it.
            self._orders = [o for o in self._orders if o != order_id]
            raise RuntimeError(f"unknown order {order_id}")
        if order_id not in self._inert_cancel:
            # A cancelled id stops being named at all — the enumeration
            # that reported it twice reports it no times once driven.
            self._orders = [o for o in self._orders if o != order_id]
        return {"client_order_id": order_id, "status": "CANCELED"}

    def open_positions(self) -> tuple[str, ...]:
        self.position_reads += 1
        if self.position_reads == 2:
            self._positions.extend(self._late_positions)
        return tuple(self._positions)

    def close_position(self, symbol: str) -> dict[str, str]:
        self.close_calls.append(symbol)
        if symbol in self._refuse_close:
            raise RuntimeError(f"venue refused to close {symbol}")
        if symbol not in self._inert_close:
            self._positions = [p for p in self._positions if p != symbol]
        return {"symbol": symbol, "status": "CLOSED"}


def _row_count(database_url: str, table: str) -> int:
    """How many rows a member table holds, read with the driver directly.

    The no-write law is this module's own discipline, so the tests that
    pin it must read the tables without going through the flattener —
    or through the switch and the store whose paths the flattener shares.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _wedge(database_url: str) -> sqlite3.Connection:
    """Hold the store's write lock, the way a hung strategy process does.

    An open ``BEGIN IMMEDIATE`` transaction is the exact state a
    strategy process leaves behind when it dies mid-write: every writer
    behind it refuses with *database is locked*, while readers still see
    the last committed state.  The caller closes the connection to
    release the wedge.
    """
    path = database_url.removeprefix("sqlite:///")
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("BEGIN IMMEDIATE")
    return connection


def _assert_writers_are_refused(database_url: str) -> None:
    """Prove the wedge is real: a writer cannot take the store."""
    path = database_url.removeprefix("sqlite:///")
    with (
        closing(sqlite3.connect(path, timeout=0.1, isolation_level=None)) as probe,
        pytest.raises(sqlite3.OperationalError, match="locked"),
    ):
        probe.execute("BEGIN IMMEDIATE")


# -- It flattens -----------------------------------------------------------------


class TestTheFlattenCompletes:
    def test_construction_touches_no_database(self, tmp_path: Path) -> None:
        # The composition-time promise every store in this workspace
        # states — sharper here, because this feature owns no table at
        # all: there is nothing to bring into being, ever.
        database = tmp_path / "not-yet.db"
        RiskFlattener(f"sqlite:///{database}")
        assert not database.exists()

    def test_a_full_book_is_driven_flat(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine(
            ("order-a", "order-b"), ("BTCUSDT", "ETHUSDT")
        )
        result = flattener.flatten(engine, flattened_at=FLATTENED)
        assert result.status == FLATTEN_STATUS_COMPLETED == "completed"
        assert result.cancelled_orders == ("order-a", "order-b")
        assert result.closed_positions == ("BTCUSDT", "ETHUSDT")
        assert engine._orders == [] and engine._positions == []
        assert engine.cancel_calls == ["order-a", "order-b"]
        assert engine.close_calls == ["BTCUSDT", "ETHUSDT"]

    def test_the_result_carries_the_authority_it_acted_under(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # The kill was sent by supervisor/4711; a restarted supervisor
        # (this process) flattens under that first kill's authority, and
        # the record says so rather than claiming its own.
        result = flattener.flatten(_StubEngine(), flattened_at=FLATTENED)
        assert result.instruction.instruction == KILL_INSTRUCTION
        assert result.instruction.supervisor_process_id == "supervisor/4711"
        assert result.instruction.sent_at == SENT
        assert result.supervisor_process_id == flattener.process_id
        assert result.supervisor_process_id == process_identity()
        assert result.flattened_at == FLATTENED

    def test_the_driven_order_is_the_engines_report_order(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # The record lists the work in the order the sweep drove it —
        # the engine's own enumeration order, not a re-derivation.
        result = flattener.flatten(_StubEngine(("late-b", "early-a")))
        assert result.cancelled_orders == ("late-b", "early-a")

    def test_an_already_flat_book_flattens(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # A re-sweep over an engine that reports nothing standing is the
        # recovery protocol's own second half, and it must complete
        # truthfully: the engine was asked, the engine said flat.
        engine = _StubEngine()
        result = flattener.flatten(engine, flattened_at=FLATTENED)
        assert result.status == FLATTEN_STATUS_COMPLETED
        assert result.cancelled_orders == ()
        assert result.closed_positions == ()
        assert engine.cancel_calls == [] and engine.close_calls == []

    def test_a_duplicate_report_is_driven_once(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # An engine that names one id twice is asking twice for one act;
        # the first receipt stands and the duplicate is not re-driven.
        engine = _StubEngine(("order-a", "order-a"))
        result = flattener.flatten(engine)
        assert result.cancelled_orders == ("order-a",)
        assert engine.cancel_calls == ["order-a"]

    def test_the_default_moment_is_now_and_aware(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        before = datetime.now(UTC)
        result = flattener.flatten(_StubEngine())
        after = datetime.now(UTC)
        assert result.flattened_at.tzinfo is not None
        assert before <= result.flattened_at <= after

    def test_the_flatten_writes_nothing_to_the_store(
        self, killed: RiskKillSwitch, flattener: RiskFlattener, test_database_url: str
    ) -> None:
        # The no-write law, read off both of the member's tables: the
        # channel holds the one row the kill wrote, and the ledger holds
        # none — the flatten is not the ledger's writer, and a row it
        # wrote here would be a row a hung strategy process could wedge.
        # The ledger's shape is brought into being first, so "no rows"
        # is a fact about a table that exists rather than an absence.
        RiskHaltEventStore(test_database_url).ensure_schema()
        flattener.flatten(_StubEngine(("order-a",), ("BTCUSDT",)))
        assert _row_count(test_database_url, RISK_ORDER_KILL_TABLE) == 1
        assert _row_count(test_database_url, RISK_HALT_EVENT_TABLE) == 0

    def test_the_flattener_has_no_schema_of_its_own(self) -> None:
        # The absence is the feature: no ensure_schema exists to call,
        # because there is no table whose shape a hung process could
        # wedge the bringing-into-being of.
        assert not hasattr(RiskFlattener, "ensure_schema")

    def test_the_summary_names_the_work_the_authority_and_the_moments(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        result = flattener.flatten(
            _StubEngine(("order-a",), ("BTCUSDT",)), flattened_at=FLATTENED
        )
        summary = result.summary
        assert "completed" in summary
        assert "order-a" in summary and "BTCUSDT" in summary
        assert result.supervisor_process_id in summary
        assert "supervisor/4711" in summary  # the authority, spelled in full
        assert FLATTENED.astimezone(UTC).isoformat() in summary
        assert SENT.astimezone(UTC).isoformat() in summary

    def test_the_record_is_frozen(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        result = flattener.flatten(_StubEngine())
        with pytest.raises(FrozenInstanceError):
            result.status = "interrupted"  # type: ignore[misc]


# -- It acts under the channel ----------------------------------------------------


class TestItActsUnderTheKillChannel:
    def test_a_flatten_under_no_kill_is_refused(self, flattener: RiskFlattener) -> None:
        # The kill stops the source, the flatten drains the sink — in
        # that order, or the flatten races the submissions it exists to
        # stop.  The refusal names the door that fixes it.
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(_StubEngine(("order-a",)))
        message = str(raised.value)
        assert "no kill instruction stands" in message
        assert "send_kill" in message

    def test_the_kill_need_not_be_this_processs_own(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # First-write-wins authority: this process never sent a kill,
        # the channel's row was written by another identity, and the
        # flatten acts under it exactly as the restarted supervisor it
        # is would.
        assert flattener.process_id != "supervisor/4711"
        result = flattener.flatten(_StubEngine(("order-a",)))
        assert result.instruction.supervisor_process_id == "supervisor/4711"

    def test_a_store_this_member_cannot_speak_is_the_channels_refusal(
        self,
    ) -> None:
        # The address fault and its repair belong to the channel's
        # vocabulary; the flattener propagates it unaltered rather than
        # restating it in its own class.
        flattener = RiskFlattener("postgres://localhost/risk")
        with pytest.raises(RiskStoreError, match="postgres"):
            flattener.flatten(_StubEngine())

    def test_the_sender_label_is_keyword_only(self) -> None:
        parameters = inspect.signature(RiskFlattener.flatten).parameters
        assert set(parameters) == {
            "self",
            "execution_engine",
            "flattened_at",
            "supervisor_process_id",
        }
        assert parameters["supervisor_process_id"].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters["flattened_at"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_a_label_that_names_no_process_is_refused(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        for label in ("", "   ", 7):
            with pytest.raises(RiskFlattenError, match=FLATTEN_CODE):
                flattener.flatten(
                    _StubEngine(),
                    supervisor_process_id=label,  # type: ignore[arg-type]
                )

    def test_an_explicit_label_is_filed_as_given(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # The one caller that passes a label — a replay of a recorded
        # flatten — has its replay spelled on the record.
        result = flattener.flatten(
            _StubEngine(), flattened_at=FLATTENED, supervisor_process_id="bastion/1"
        )
        assert result.supervisor_process_id == "bastion/1"


# -- Even when the strategy process is hung ----------------------------------------


class TestEvenWhenTheStrategyProcessIsHung:
    def test_the_flatten_reads_committed_state_under_a_wedged_write_lock(
        self,
        killed: RiskKillSwitch,
        flattener: RiskFlattener,
        test_database_url: str,
    ) -> None:
        # The fast form of the claim, in this process: a second
        # connection holds the store's write lock open — the state a
        # strategy process leaves behind when it dies mid-write — and a
        # probe proves writers are really refused, while the flatten
        # reads the committed kill and completes.
        wedge = _wedge(test_database_url)
        try:
            _assert_writers_are_refused(test_database_url)
            result = flattener.flatten(
                _StubEngine(("order-a",), ("BTCUSDT",)), flattened_at=FLATTENED
            )
            assert result.status == FLATTEN_STATUS_COMPLETED
            assert result.instruction.supervisor_process_id == "supervisor/4711"
        finally:
            wedge.close()
        # The wedge was the only thing refusing writers: released, the
        # store takes a writer again — the flatten left nothing behind.
        probe = sqlite3.connect(
            test_database_url.removeprefix("sqlite:///"), isolation_level=None
        )
        try:
            probe.execute("BEGIN IMMEDIATE")
            probe.execute("ROLLBACK")
        finally:
            probe.close()

    def test_a_second_interpreter_holding_the_lock_cannot_prevent_the_flatten(
        self, tmp_path: Path
    ) -> None:
        # The full §13.3 topology, in the deployment the feature's own
        # sentence names.  A *separate interpreter* — the strategy
        # process — opens a write transaction on the shared store,
        # writes an uncommitted halt event into it (mid-submission,
        # exactly the way a strategy process dies), and hangs holding
        # the lock.  A *second* separate interpreter — the supervisor —
        # flattens over its own hold on the engine and answers
        # completed, in a process of its own, while a probe from this
        # process proves the store was refusing writers throughout.
        database = tmp_path / "cross-process.db"
        url = f"sqlite:///{database}"
        RiskKillSwitch(url).send(sent_at=SENT, supervisor_process_id="supervisor/4711")

        strategy_script = (
            "import sqlite3, time, sys;"
            "from risk.halt_events import RiskHaltEventStore;"
            "RiskHaltEventStore(sys.argv[1]).ensure_schema();"
            "connection = sqlite3.connect("
            "sys.argv[1].removeprefix('sqlite:///'), isolation_level=None);"
            "connection.execute('BEGIN IMMEDIATE');"
            "connection.execute("
            "\"INSERT INTO risk_halt_event (trigger_reason, triggered_at, "
            "recorded_at, supervisor_process_id) VALUES "
            "('strategy_was_here', '2026-09-25T12:01:00+00:00', "
            "'2026-09-25T12:01:00+00:00', 'strategy/1')\");"
            "print('wedged', flush=True);"
            "time.sleep(300)"
        )
        supervisor_script = """
import sys
from risk._identity import process_identity
from risk.flatten import flatten_positions

class Engine:
    def __init__(self):
        self.orders = ['order-a', 'order-b']
        self.positions = ['BTCUSDT']

    def open_orders(self):
        return tuple(self.orders)

    def cancel_order(self, order_id):
        self.orders = [o for o in self.orders if o != order_id]
        return {'client_order_id': order_id, 'status': 'CANCELED'}

    def open_positions(self):
        return tuple(self.positions)

    def close_position(self, symbol):
        self.positions = [p for p in self.positions if p != symbol]
        return {'symbol': symbol, 'status': 'CLOSED'}

result = flatten_positions(
    execution_engine=Engine(), database_url=sys.argv[1])
print(result.status, process_identity(),
      ','.join(result.cancelled_orders),
      ','.join(result.closed_positions),
      result.instruction.supervisor_process_id)
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
        strategy = subprocess.Popen(
            [sys.executable, "-c", strategy_script, url],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert strategy.stdout is not None
            announced = strategy.stdout.readline().strip()
            if announced != "wedged":
                strategy.terminate()
                strategy.wait(timeout=30)
                stderr = (
                    strategy.stderr.read() if strategy.stderr is not None else ""
                )
                pytest.fail(
                    f"the strategy process did not wedge: {announced!r} {stderr!r}"
                )
            _assert_writers_are_refused(url)  # the hang is biting, for writers

            result = subprocess.run(
                [sys.executable, "-c", supervisor_script, url],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            assert result.returncode == 0, result.stderr
            status, theirs, cancelled, closed, authority = (
                result.stdout.strip().split(" ", 4)
            )
            assert status == FLATTEN_STATUS_COMPLETED
            assert cancelled == "order-a,order-b"
            assert closed == "BTCUSDT"
            assert authority == "supervisor/4711"
            assert theirs != process_identity()  # a process of its own

            _assert_writers_are_refused(url)  # still hung, throughout
        finally:
            strategy.terminate()
            strategy.wait(timeout=30)

        # The hung process's uncommitted write died with it: the ledger
        # the flatten never touched holds none of it, and the channel's
        # row is still the one committed kill.
        assert _row_count(url, RISK_ORDER_KILL_TABLE) == 1
        assert _row_count(url, RISK_HALT_EVENT_TABLE) == 0

    def test_the_module_never_reaches_the_order_layers_member(self) -> None:
        # Asserted in a subprocess, because this suite's own imports
        # have already loaded plenty.  The flatten drives the engine it
        # is handed; a module that imported the order layer's member
        # would be holding a second spelling of the engine's face, and
        # the one process this feature must survive is the one whose
        # imports it would then share.
        script = (
            "import sys; import risk, risk.flatten, risk.errors;"
            "assert 'router' not in sys.modules,"
            " 'the risk member imported the order layer at module scope';"
            "print('separate')"
        )
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
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "separate"


# -- Completed is derived, never asserted -------------------------------------------


class TestCompletionIsDerivedFromTheEngine:
    def test_a_cancel_whose_receipt_lies_leaves_the_order_standing(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # cancel_order() returned a receipt and the order is still there
        # on the re-read: the receipts are not the judge, the engine's
        # own answer is, and the completed word waits for it.
        engine = _StubEngine(("order-a",), inert_cancel=("order-a",))
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "open orders still standing" in str(raised.value)
        assert "order-a" in str(raised.value)

    def test_a_close_whose_receipt_lies_leaves_the_position_open(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine((), ("BTCUSDT",), inert_close=("BTCUSDT",))
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "positions still open" in str(raised.value)
        assert "BTCUSDT" in str(raised.value)

    def test_an_order_arriving_mid_flatten_is_caught_by_the_re_read(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # Everything it was shown was driven away, and something new
        # stands anyway: the final asking is what the completed word is
        # made of, and it is asked after the work, not before it.
        engine = _StubEngine(("order-a",), late_orders=("order-late",))
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "order-late" in str(raised.value)

    def test_a_position_arriving_mid_flatten_is_caught_by_the_re_read(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine((), ("BTCUSDT",), late_positions=("ETHUSDT",))
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "ETHUSDT" in str(raised.value)

    def test_an_engine_that_cannot_be_asked_again_refuses_the_result(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # The completion check itself failing is a refusal, not a shrug:
        # a face whose state cannot be known is a face a completed
        # result must never be returned over.
        engine = _StubEngine(("order-a",), refuse_recount=True)
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "open_orders" in str(raised.value)

    def test_a_refusal_is_caught_as_the_members_base(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine(("order-a",), inert_cancel=("order-a",))
        with pytest.raises(RiskError):
            flattener.flatten(engine)


class TestTheDriveIsBestEffort:
    def test_a_refusing_cancel_does_not_stop_the_sweep(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # One refusal must not leave the residue unattempted: the other
        # order was still driven, and the refusal names the fault.
        engine = _StubEngine(
            ("order-a", "order-b"), refuse_cancel=("order-a",)
        )
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert engine.cancel_calls == ["order-a", "order-b"]
        assert "order-a" in str(raised.value)
        assert engine._orders == ["order-a"]  # the refused one, still standing

    def test_a_refusing_close_does_not_stop_the_sweep(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine(
            ("order-a",), ("BTCUSDT", "ETHUSDT"), refuse_close=("BTCUSDT",)
        )
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert engine.close_calls == ["BTCUSDT", "ETHUSDT"]
        assert "BTCUSDT" in str(raised.value)

    def test_a_fault_with_a_clean_re_read_still_refuses(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # A cancel that raises "unknown order" because the order filled
        # and went: the engine ends up reporting nothing standing, and
        # the refusal stands anyway — a result that hid a thrown receipt
        # would disagree with its own run, and the caller that
        # re-flattens completes over whatever the fill left.
        engine = _StubEngine(("order-filled",), gone_cancel=("order-filled",))
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "order-filled" in str(raised.value)
        # The recovery the refusal names: the next sweep re-reads the
        # engine and completes over what remains — here, nothing.
        again = flattener.flatten(engine)
        assert again.status == FLATTEN_STATUS_COMPLETED
        assert again.cancelled_orders == ()


# -- The engine face ---------------------------------------------------------------


class TestTheEngineFace:
    def test_a_face_missing_one_verb_is_refused_by_name(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        class ThreeOfFour:
            def open_orders(self):
                return ()

            def cancel_order(self, order_id):
                return None

            def open_positions(self):
                return ()

        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(ThreeOfFour())  # type: ignore[arg-type]
        assert "close_position" in str(raised.value)

    def test_no_face_at_all_is_refused_with_all_four_verbs(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(None)
        for verb in ("open_orders", "cancel_order", "open_positions", "close_position"):
            assert verb in str(raised.value)

    def test_an_enumeration_that_names_nothing_is_refused(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine()
        engine.open_orders = lambda: [7]  # type: ignore[method-assign]
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "open_orders" in str(raised.value)

    def test_an_enumeration_of_empty_names_is_refused(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine()
        engine.open_positions = lambda: [""]  # type: ignore[method-assign]
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "names nothing" in str(raised.value)

    def test_an_enumeration_that_is_not_names_at_all_is_refused(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        engine = _StubEngine()
        engine.open_orders = lambda: 42  # type: ignore[method-assign]
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            flattener.flatten(engine)
        assert "open_orders" in str(raised.value)

    def test_ids_are_driven_as_reported(
        self, killed: RiskKillSwitch, flattener: RiskFlattener
    ) -> None:
        # Engine ids are exact strings the engine must recognise again:
        # nothing strips or launders them on the way through.
        engine = _StubEngine(("order-exact",))
        flattener.flatten(engine)
        assert engine.cancel_calls == ["order-exact"]


# -- The value layer ----------------------------------------------------------------


class TestTheRecordsOwnShape:
    def _record(self, **overrides: object) -> FlattenResult:
        fields: dict[str, object] = {
            "status": FLATTEN_STATUS_COMPLETED,
            "cancelled_orders": ("order-a",),
            "closed_positions": ("BTCUSDT",),
            "instruction": KillInstruction(
                instruction=KILL_INSTRUCTION,
                supervisor_process_id="supervisor/4711",
                sent_at=SENT,
                changed=True,
            ),
            "supervisor_process_id": "supervisor/4711",
            "flattened_at": FLATTENED,
        }
        fields.update(overrides)
        return FlattenResult(**fields)  # type: ignore[arg-type]

    def test_the_value_layer_refuses_any_other_status(self) -> None:
        for status in ("Complete", "completed ", "interrupted", "", 1):
            with pytest.raises(RiskFlattenError, match=FLATTEN_CODE):
                self._record(status=status)

    def test_the_value_layer_refuses_names_that_state_nothing(self) -> None:
        for cancelled in (("",), ("  ",), (7,)):
            with pytest.raises(RiskFlattenError, match=FLATTEN_CODE):
                self._record(cancelled_orders=cancelled)
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE):
            self._record(closed_positions=("",))

    def test_the_value_layer_refuses_a_bare_string_as_the_work_record(self) -> None:
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE):
            self._record(cancelled_orders="order-a")

    def test_the_value_layer_refuses_a_record_without_the_instruction(self) -> None:
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE) as raised:
            self._record(instruction={"instruction": "kill"})
        assert "standing" in str(raised.value)

    def test_the_value_layer_refuses_a_naive_moment(self) -> None:
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE):
            self._record(flattened_at=FLATTENED.replace(tzinfo=None))

    def test_the_value_layer_refuses_a_label_that_names_no_process(self) -> None:
        with pytest.raises(RiskFlattenError, match=FLATTEN_CODE):
            self._record(supervisor_process_id=" ")


# -- The module-level spelling -------------------------------------------------------


class TestTheModuleLevelSpelling:
    def test_flatten_positions_refuses_when_nothing_names_a_store(self) -> None:
        # The flatten has one caller — the supervisor — and one
        # direction: a flatten that silently skipped its authority
        # check would return a completed result no kill authorised.
        with pytest.raises(RiskFlattenError, match=DATABASE_URL_ENV):
            flatten_positions(execution_engine=_StubEngine(), env={})

    def test_flatten_positions_flattens_through_the_named_store(
        self, tmp_path: Path
    ) -> None:
        url = f"sqlite:///{tmp_path / 'flattened.db'}"
        send_kill(database_url=url, sent_at=SENT, supervisor_process_id="supervisor/1")
        result = flatten_positions(
            execution_engine=_StubEngine(("order-a",), ("BTCUSDT",)),
            database_url=url,
            flattened_at=FLATTENED,
        )
        assert result.status == FLATTEN_STATUS_COMPLETED
        assert result.cancelled_orders == ("order-a",)
        assert result.instruction.supervisor_process_id == "supervisor/1"

    def test_resolve_answers_none_when_nothing_names_a_store(self) -> None:
        assert RiskFlattener.resolve(env={}) is None
        assert RiskFlattener.resolve(env={DATABASE_URL_ENV: "   "}) is None

    def test_resolve_reads_the_environment_it_is_given(self) -> None:
        flattener = RiskFlattener.resolve(env={DATABASE_URL_ENV: "sqlite:///given.db"})
        assert flattener is not None
        assert flattener.database_url == "sqlite:///given.db"

    def test_an_empty_url_is_refused_at_construction(self) -> None:
        with pytest.raises(RiskStoreError):
            RiskFlattener("   ")
