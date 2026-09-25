"""Feature 370: the end-to-end journey — a daily loss breach drives the
risk supervisor to flatten while the strategy process is unresponsive.

app_spec.xml, "End-to-End Verification", feature 370: *"System passes an
end-to-end test where a daily loss breach drives the risk supervisor to
flatten positions while the strategy process is unresponsive, which
returns a completed flatten."*  The implementation phase of the same spec
names the journey's shape — *"the risk supervisor flattens independently
of a hung strategy process"* — and ``docs/nullius-tech-architecture.md``
§13.3 line 717 gives every clause of it its reason in one sentence:
*"Runs as a separate process with kill authority over the execution
engine, so a hung strategy process cannot prevent a flatten."*  §13.3's
trigger table gives the row whose response this journey is — *"Daily loss
limit breached | Flatten, halt until manual reset"* — and
``docs/alpha-engine-prd.md`` line 474 says the same two words for the
same trigger: *"Daily loss limit → flatten and halt."*

Read as one story, the sentence is four acts, and this module runs them
in the order the deployment runs them in:

* **A daily loss breach.**  The supervisor process judges the day against
  the configured limit — feature 325's own verb, with the figure handed
  over exactly as that module demands — and the breach lands as 325's
  standing halt, a row in its own table that refuses new orders until a
  manual reset.  This is a *write*, and it is the journey's first cause:
  nothing downstream of it happens but for the breach.
* **Drives the risk supervisor to flatten positions.**  §13.3 assigns the
  trigger's response — flatten, halt — to the door that composes the two
  acts: feature 323's ``POST /risk/halt``, which sends feature 322's kill
  and then drives feature 330's flatten, in that order, over the engine
  the supervisor holds.  :mod:`risk.daily_loss` said so in its own
  docstring: the end-to-end story drives that door from a breach exactly
  once, and a module that flattened on its own would be two features
  wearing one verb.  The door's two faces are resolved the way the
  deployment resolves them — through the app seat
  (:func:`app.modules.risk.risk_kill_switch`,
  :func:`app.modules.risk.risk_flattener`) over ``DATABASE_URL`` —
  because the supervisor is a process, not a composition, and the seat is
  the assembled system's answer to a process asking for its channel.
* **While the strategy process is unresponsive.**  A real second
  interpreter — the strategy process — hangs mid-write on the shared
  store: an open ``BEGIN IMMEDIATE`` transaction holding an uncommitted
  row, exactly the state a strategy process leaves behind when it dies
  between two statements.  That open transaction is the one thing a hung
  process can wedge from outside the flatten's module — the shared
  store's *write lock* — and every writer behind it refuses with
  *database is locked* while readers still see the committed state.  A
  probe connection proves the wedge is biting before the flatten runs and
  still biting after it has returned, and the strategy process is still
  alive at that point: it never cooperated, not for one act of the
  flatten.
* **Which returns a completed flatten.**  The door's response carries the
  kill it sent and the flatten it drove, and the flatten's status is the
  one word :class:`risk.flatten.FlattenResult` can wear — *completed*, a
  word the value layer refuses to weaken, earned from the engine's own
  re-reading reporting nothing standing: both orders the strategy process
  left resting are cancelled, both positions it left open are closed.

**The topology is the claim, so the topology is real.**  Three actual
processes tell this story, and their kernel-read identities
(``<host>/<pid>``, :func:`risk.process_identity`) are asserted pairwise
distinct: the strategy process that hangs, the supervisor process that
judges the day and drives the door, and this test process — which plays
the order layer's stance after the journey, asking the guards the
submission path asks, and the record's stance after the night, reading
the committed rows.  Nothing here is threaded or mocked into one
interpreter; §17 leaves no port to serve a socket on, so the store both
processes already hold is the medium, and the store is what the journey
uses.

**One ordering note, stated honestly.**  The kill *send* is a write, so
it cannot run under the wedge — and it does not: the deployment's order
is the supervisor kills, the strategy process stops cooperating, the
supervisor flattens, and that is the order this journey drives.  The
journey's one piece of choreography is a switch that delegates the door's
send to the real resolved switch and, once that write has committed,
stands by while the strategy process wedges the store — a deterministic
clock for an ordering the deployment produces by timing, spelled at the
seam the door itself duck-checks (``something with a send() seam``).
Every store act around it is real: the breach row, the kill row, the
wedge, the refusal of every writer behind it, and the flatten that reads
the committed kill under the hung writer's lock and completes anyway —
the flatten's whole path, its authority read included, runs while the
write lock is held, which is the entire content of *"a hung strategy
process cannot prevent a flatten."*

**What this module deliberately is not.**  It is not a second suite for
the members' own laws — the refusals, the races, the value layers and
the near-misses live in ``packages/risk/tests``, and nothing here re-tests
them; this is the journey, once, through the assembled system's public
seams.  It does not reset, reconcile or repair: the halt stands and the
kill stands at the end of the journey, because those are 325's and 322's
own laws, and the morning after belongs to the doors that own them.  And
it does not seed the store through any face whose discipline the journey
is testing: the strategy process prepares its own table through the
member's own public ``ensure_schema`` before it hangs, the way a real
process would have on its way in.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest
from risk._identity import process_identity
from risk.daily_loss import (
    RISK_DAILY_LOSS_HALT_TABLE,
    require_within_daily_loss_limit,
)
from risk.errors import RiskOrdersHaltedError, RiskOrdersKilledError
from risk.flatten import FLATTEN_STATUS_COMPLETED
from risk.halt_events import RISK_HALT_EVENT_TABLE
from risk.kill import (
    DATABASE_URL_ENV,
    RISK_ORDER_KILL_TABLE,
    require_orders_allowed,
)

from app.module_loader import workspace_scan_roots

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The day the journey stages: a loss a quarter past a configured limit —
#: a bad day by any operator's reading, and a strict breach of the line,
#: which feature 325's comparison demands before any halt may land.
DAILY_LOSS = 12_500.0
DAILY_LOSS_LIMIT = 10_000.0

#: The book the strategy process left standing when it stopped
#: cooperating: two orders resting on the venue, two positions open.  The
#: flatten's completed result must name exactly these, driven away.
STANDING_ORDERS = ("order-1", "order-2")
OPEN_POSITIONS = ("BTCUSDT", "ETHUSDT")


# -- The two processes the journey runs ---------------------------------------------


#: The strategy process: alive and writing until the supervisor has
#: killed, then hung mid-write, holding the store's write lock — the one
#: thing a hung process can wedge from outside the flatten's module, and
#: therefore the one this journey wedges on purpose.  The uncommitted row
#: it dies holding lands in feature 331's ledger table, prepared through
#: the member's own public ``ensure_schema`` the way a real process would
#: have on its way in; the table is the strategy process's own medium,
#: not the journey's subject.
STRATEGY_SCRIPT = """
import os
import sqlite3
import sys
import time
from pathlib import Path

choreography = Path(sys.argv[1])

from risk._identity import process_identity

identity = process_identity()
print("identity", identity, flush=True)

from risk.halt_events import RiskHaltEventStore

RiskHaltEventStore(os.environ["DATABASE_URL"]).ensure_schema()

# Responsive until the supervisor has killed: the wedge begins only after
# the kill's write has committed, which is the only order the deployment
# runs in -- the supervisor kills, the strategy process stops
# cooperating, the supervisor flattens.
deadline = time.monotonic() + 30
while not (choreography / "wedge-now").exists():
    if time.monotonic() > deadline:
        print("never told to wedge", flush=True)
        raise SystemExit(3)
    time.sleep(0.02)

# Mid-write, exactly the way a strategy process dies: the transaction is
# open, its row is uncommitted, and the write lock is held indefinitely.
url = os.environ["DATABASE_URL"]
connection = sqlite3.connect(url.removeprefix("sqlite:///"), isolation_level=None)
connection.execute("BEGIN IMMEDIATE")
connection.execute(
    "INSERT INTO risk_halt_event (trigger_reason, triggered_at, "
    "recorded_at, supervisor_process_id) VALUES (?, ?, ?, ?)",
    (
        "strategy-mid-write",
        "2026-09-25T12:01:00+00:00",
        "2026-09-25T12:01:00+00:00",
        identity,
    ),
)
(choreography / "wedged").write_text("the write lock is held")
print("wedged", flush=True)
time.sleep(300)
"""


#: The supervisor process: the risk process the sentence names.  It
#: judges the day (feature 325), resolves the door's two faces through
#: the app seat the way the deployment resolves them, and drives feature
#: 323's composed halt over its own hold on the execution engine.  The
#: one choreographed seam is the switch the door sends through: it
#: delegates the send to the real resolved switch and, once the kill has
#: committed, stands by while the strategy process wedges the store — so
#: the flatten that follows runs its whole path, the authority read of
#: the channel included, under the hung writer's lock.
SUPERVISOR_SCRIPT = """
import sys
import time
from pathlib import Path

choreography = Path(sys.argv[1])
daily_loss = float(sys.argv[2])
daily_loss_limit = float(sys.argv[3])

from risk import HaltEndpoint, HaltRequest, halt_on_daily_loss
from risk._identity import process_identity

# The journey's first cause: the supervisor judges the day against the
# configured limit, and the breach lands as feature 325's standing halt.
# A write -- so it happens while the strategy process is still responsive.
halt = halt_on_daily_loss(daily_loss=daily_loss, daily_loss_limit=daily_loss_limit)
assert halt is not None, "the day breached its configured limit; the halt must land"

# The door's two faces, resolved the way the deployment resolves them.
from app.modules.risk import risk_flattener, risk_kill_switch

switch = risk_kill_switch()
flattener = risk_flattener()
assert switch is not None, "DATABASE_URL names no store for the door to act through"
assert flattener is not None, "DATABASE_URL names no store to flatten under"


class StrategyStopsCooperating:
    # Delegates the send to the real switch; with the kill committed, the
    # strategy process wedges the store's write lock and hangs.  The
    # journey's deterministic spelling of the deployment's own order.
    def __init__(self, real, choreography):
        self._real = real
        self._choreography = choreography

    def send(self, *, sent_at=None, supervisor_process_id=None):
        instruction = self._real.send(
            sent_at=sent_at, supervisor_process_id=supervisor_process_id
        )
        (self._choreography / "wedge-now").write_text("the kill is committed")
        deadline = time.monotonic() + 30
        while not (self._choreography / "wedged").exists():
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "the strategy process never wedged the store, so a "
                    "flatten under the hang cannot be shown"
                )
            time.sleep(0.02)
        return instruction


class Engine:
    # The supervisor's own hold on the execution engine (the one field no
    # composition can supply), holding the book the strategy process left
    # standing: orders resting, positions open.
    def __init__(self):
        self.orders = ["order-1", "order-2"]
        self.positions = ["BTCUSDT", "ETHUSDT"]

    def open_orders(self):
        return tuple(self.orders)

    def cancel_order(self, order_id):
        self.orders = [o for o in self.orders if o != order_id]
        return {"client_order_id": order_id, "status": "CANCELED"}

    def open_positions(self):
        return tuple(self.positions)

    def close_position(self, symbol):
        self.positions = [p for p in self.positions if p != symbol]
        return {"symbol": symbol, "status": "CLOSED"}


# The composed halt the breach drives: the door sends the kill, the
# strategy process hangs mid-write, and the door's flatten runs under the
# hung writer's lock and returns only a completed result.
door = HaltEndpoint(StrategyStopsCooperating(switch, choreography), flattener)
response = door.post(HaltRequest(execution_engine=Engine()))

print("supervisor", process_identity())
print(
    "breach",
    halt.sequence,
    repr(halt.loss),
    repr(halt.limit),
    int(halt.standing),
    halt.supervisor_process_id,
)
print(
    "kill",
    response.instruction.supervisor_process_id,
    response.instruction.changed,
    response.instruction.sent_at.isoformat(),
)
print(
    "flatten",
    response.result.status,
    ",".join(response.result.cancelled_orders),
    ",".join(response.result.closed_positions),
    response.result.supervisor_process_id,
    response.result.flattened_at.isoformat(),
)
"""


# -- The journey's captured facts ----------------------------------------------------


@dataclass(frozen=True)
class _Journey:
    """What the three processes reported, frozen at the journey's end.

    The facts are captured in the order the journey produced them — the
    supervisor's four lines, the strategy process's aliveness and the
    writers' refusal under its held lock, the guards this process asked
    afterwards, and the committed rows the store held throughout — so the
    facet tests below assert over one story rather than re-running a
    choreography per assertion.
    """

    url: str
    supervisor_identity: str
    strategy_identity: str
    breach_sequence: int
    breach_loss: float
    breach_limit: float
    breach_standing: bool
    breach_judge: str
    kill_sender: str
    kill_changed: bool
    kill_sent_at: str
    flatten_status: str
    flatten_cancelled: tuple[str, ...]
    flatten_closed: tuple[str, ...]
    flatten_driver: str
    flatten_flattened_at: str
    strategy_still_hung: bool
    writers_refused: bool
    writers_error: str
    kill_guard_error: BaseException | None
    daily_guard_error: BaseException | None
    kill_rows: int
    halt_rows: int
    halt_unreset_rows: int
    halt_event_rows: int


def _subprocess_pythonpath() -> str:
    """The import surface a spawned interpreter needs to be the deployment.

    The application factory's ``src`` plus every declared workspace
    member's scan root — the same declaration the production module
    loader reads — so a process the journey spawns reaches ``app`` and
    the members exactly as this process does, rather than through a
    hard-coded path that could quietly disagree with the workspace.
    """
    entries = [str(REPO_ROOT / "src")]
    for root in workspace_scan_roots():
        if str(root) not in entries:
            entries.append(str(root))
    inherited = os.environ.get("PYTHONPATH", "")
    if inherited:
        entries.append(inherited)
    return os.pathsep.join(entries)


def _writers_are_refused(database_url: str) -> tuple[bool, str]:
    """Probe the wedge: can a writer take the store right now?

    The one-bit proof that the strategy process's open transaction is
    really biting — a writer behind it is refused with *database is
    locked*, the exact refusal a hung strategy process imposes on every
    writer that tries to persist while it hangs.
    """
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path, timeout=0.1, isolation_level=None)) as probe:
            probe.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        return True, str(exc)
    return False, "a writer took the store the hung process was holding"


def _guard_refusal(guard: Callable[[], None]) -> BaseException | None:
    """Ask a guard the submission path's question; capture its refusal.

    Returns the raised refusal itself — the record's own class and own
    fields are the datum, not a copy of its name — or ``None`` when the
    guard passed, which for either guard below is a fact the facet tests
    must be able to see and refuse.
    """
    try:
        guard()
    except Exception as exc:  # noqa: BLE001 - the refusal's own type is the datum
        return exc
    return None


def _row_count(database_url: str, table: str, where: str = "") -> int:
    """Count a member table's rows with the driver directly.

    The committed-record assertions must read the store without going
    through any face whose discipline the journey holds to its laws —
    and must read it *under* the wedge, where committed state is exactly
    what a reader still sees.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        return int(
            connection.execute(f"SELECT COUNT(*) FROM {table}{where}").fetchone()[0]
        )


def _supervisor_facts(stdout: str) -> dict[str, list[str]]:
    """The supervisor's four lines, split into their fields.

    Strict about the shape — a line that arrives short is a journey that
    did not finish, and the failure should name what actually came back
    rather than die in an unpack.
    """
    facts: dict[str, list[str]] = {}
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        key, _, rest = line.partition(" ")
        facts[key] = rest.split(" ")
    expected = {"supervisor", "breach", "kill", "flatten"}
    if set(facts) != expected:
        pytest.fail(f"the supervisor's report is not the four facts: {stdout!r}")
    return facts


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Journey]:
    """Run the journey once, and hand its captured facts to the facets.

    The journey's own SQLite URL, not the suite's isolated
    ``DATABASE_URL``: the wedge is one database engine's locking story —
    SQLite's ``BEGIN IMMEDIATE`` refusing every writer behind it is the
    one thing a hung strategy process can wedge — and asking a scratch
    CI database of another engine to play that part would be staging the
    sentence against a lock manager that never wrote it.  The member's
    own cross-process tests take the same stance for the same reason.
    """
    workdir = tmp_path_factory.mktemp("daily-loss-flatten")
    choreography = workdir / "choreography"
    choreography.mkdir()
    url = f"sqlite:///{workdir / 'nullius-e2e.db'}"
    env = {
        **os.environ,
        DATABASE_URL_ENV: url,
        "PYTHONPATH": _subprocess_pythonpath(),
    }

    strategy = subprocess.Popen(
        [sys.executable, "-c", STRATEGY_SCRIPT, str(choreography)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert strategy.stdout is not None
        announced = strategy.stdout.readline().strip()
        if not announced.startswith("identity "):
            # Fail with the corpse's own words: terminate first, then read
            # the stderr the dying process left, so a broken import or a
            # refused start is named rather than guessed at.
            strategy.terminate()
            strategy.wait(timeout=30)
            stderr = strategy.stderr.read() if strategy.stderr is not None else ""
            pytest.fail(
                f"the strategy process never announced itself: {announced!r} {stderr!r}"
            )
        strategy_identity = announced.removeprefix("identity ").strip()

        supervisor = subprocess.run(
            [
                sys.executable,
                "-c",
                SUPERVISOR_SCRIPT,
                str(choreography),
                str(DAILY_LOSS),
                str(DAILY_LOSS_LIMIT),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        if supervisor.returncode != 0:
            pytest.fail(
                f"the supervisor process failed ({supervisor.returncode}): "
                f"{supervisor.stderr}"
            )

        facts = _supervisor_facts(supervisor.stdout)
        if (
            len(facts["breach"]) != 5
            or len(facts["kill"]) != 3
            or (len(facts["flatten"]) != 5)
        ):
            pytest.fail(f"the supervisor's report is malformed: {supervisor.stdout!r}")
        (
            breach_sequence,
            breach_loss,
            breach_limit,
            breach_standing,
            breach_judge,
        ) = facts["breach"]
        kill_sender, kill_changed, kill_sent_at = facts["kill"]
        (
            flatten_status,
            flatten_cancelled,
            flatten_closed,
            flatten_driver,
            flatten_flattened_at,
        ) = facts["flatten"]

        # The strategy process is still hung, and its lock still bites:
        # the flatten that just returned did so under this refusal.
        strategy_still_hung = strategy.poll() is None
        writers_refused, writers_error = _writers_are_refused(url)

        # The order layer's stance, asked from this process while the
        # strategy process is still hung: both guards refuse, each under
        # the standing state its own feature wrote.
        kill_guard_error = _guard_refusal(
            lambda: require_orders_allowed(database_url=url)
        )
        daily_guard_error = _guard_refusal(
            lambda: require_within_daily_loss_limit(database_url=url)
        )

        # The committed record, read under the wedge where committed
        # state is exactly what a reader still sees.
        halt_where = " WHERE reset_at IS NULL"

        yield _Journey(
            url=url,
            supervisor_identity=facts["supervisor"][0],
            strategy_identity=strategy_identity,
            breach_sequence=int(breach_sequence),
            breach_loss=float(breach_loss),
            breach_limit=float(breach_limit),
            breach_standing=breach_standing == "1",
            breach_judge=breach_judge,
            kill_sender=kill_sender,
            kill_changed=kill_changed == "True",
            kill_sent_at=kill_sent_at,
            flatten_status=flatten_status,
            flatten_cancelled=tuple(flatten_cancelled.split(",")),
            flatten_closed=tuple(flatten_closed.split(",")),
            flatten_driver=flatten_driver,
            flatten_flattened_at=flatten_flattened_at,
            strategy_still_hung=strategy_still_hung,
            writers_refused=writers_refused,
            writers_error=writers_error,
            kill_guard_error=kill_guard_error,
            daily_guard_error=daily_guard_error,
            kill_rows=_row_count(url, RISK_ORDER_KILL_TABLE),
            halt_rows=_row_count(url, RISK_DAILY_LOSS_HALT_TABLE),
            halt_unreset_rows=_row_count(url, RISK_DAILY_LOSS_HALT_TABLE, halt_where),
            halt_event_rows=_row_count(url, RISK_HALT_EVENT_TABLE),
        )
    finally:
        strategy.terminate()
        try:
            strategy.wait(timeout=30)
        except subprocess.TimeoutExpired:
            strategy.kill()
            strategy.wait(timeout=30)


# -- A daily loss breach drives the risk supervisor ----------------------------------


class TestTheBreachDroveTheSupervisor:
    def test_the_breach_lands_as_the_journeys_first_cause(
        self, journey: _Journey
    ) -> None:
        # Feature 325's own state, in its own table: the day's figure and
        # the configured limit on one row, standing until a manual reset.
        assert journey.breach_sequence == 1
        assert journey.breach_loss == DAILY_LOSS
        assert journey.breach_limit == DAILY_LOSS_LIMIT
        assert journey.breach_standing is True
        # The same process that drove the flatten judged the day: the
        # supervisor is the risk process, and its kernel-read identity
        # filed the breach.
        assert journey.breach_judge == journey.supervisor_identity

    def test_the_kill_the_flatten_acted_under_was_sent_by_this_supervisor(
        self, journey: _Journey
    ) -> None:
        # The door's first act, on record: this door call wrote the kill
        # (first-write-wins), and the identity that sent it is the
        # supervisor's own.  The send is a write and the journey's writers
        # were refused from the wedge until after the flatten returned --
        # so a kill that landed can only have preceded the hang: the
        # ordering law held by construction and by evidence both.
        assert journey.kill_sender == journey.supervisor_identity
        assert journey.kill_changed is True

    def test_the_flatten_returns_completed_over_the_book_left_standing(
        self, journey: _Journey
    ) -> None:
        # The sentence's last clause, as the one word the value layer
        # permits: completed, over exactly the work the engine was shown,
        # driven by the supervisor's own process identity.
        assert journey.flatten_status == FLATTEN_STATUS_COMPLETED
        assert journey.flatten_cancelled == STANDING_ORDERS
        assert journey.flatten_closed == OPEN_POSITIONS
        assert journey.flatten_driver == journey.supervisor_identity

    def test_the_door_drove_both_acts_at_one_instant(self, journey: _Journey) -> None:
        # The door's own law, read off the two records it returned: the
        # kill's moment and the flatten's moment are one instant -- the
        # door does not compose two decisions, it pronounces one halt.
        assert journey.kill_sent_at == journey.flatten_flattened_at


# -- While the strategy process was unresponsive --------------------------------------


class TestWhileTheStrategyProcessWasUnresponsive:
    def test_the_flatten_completed_under_the_hung_processs_write_lock(
        self, journey: _Journey
    ) -> None:
        # The claim in its strongest form.  The strategy process was
        # still alive when the supervisor's report came back -- it never
        # exited, never cooperated -- and a writer probing the store at
        # that moment was still refused with the lock the hung process
        # held.  The completed flatten above ran its whole path under
        # that refusal: nothing it touched required the strategy process
        # or the write lock it died holding.
        assert journey.strategy_still_hung is True
        assert journey.writers_refused is True
        assert "locked" in journey.writers_error

    def test_the_story_was_told_by_three_processes(self, journey: _Journey) -> None:
        # The identities are kernel-read and pairwise distinct: the
        # strategy process that hung, the supervisor that flattened, and
        # this test process that watched -- three processes, one store,
        # and no thread wearing a taller story anywhere in the journey.
        mine = process_identity()
        assert journey.strategy_identity != journey.supervisor_identity
        assert journey.supervisor_identity != mine
        assert journey.strategy_identity != mine


# -- The standing consequences --------------------------------------------------------


class TestTheStandingConsequences:
    def test_new_order_submission_is_refused_under_the_standing_kill(
        self, journey: _Journey
    ) -> None:
        # The door's other half, read the way the order layer reads it:
        # the kill the door sent is the state feature 322's guard refuses
        # under -- asked from this process, a fourth one, while the
        # strategy process was still hung, because the channel is the
        # medium and the medium does not care who is asking.
        assert isinstance(journey.kill_guard_error, RiskOrdersKilledError)

    def test_the_day_stands_refused_until_a_manual_reset(
        self, journey: _Journey
    ) -> None:
        # The breach's own refusal, feature 325's second clause: the halt
        # stands on its un-reset row and lifts by no door this journey
        # drove -- not the flatten, not the kill, not the hang.
        assert isinstance(journey.daily_guard_error, RiskOrdersHaltedError)
        assert journey.halt_unreset_rows == 1


# -- The committed record --------------------------------------------------------------


class TestTheCommittedRecord:
    def test_the_store_holds_exactly_the_two_acts_and_nothing_else(
        self, journey: _Journey
    ) -> None:
        # Read under the wedge, where committed state is exactly what a
        # reader still sees.  One kill row -- the door's send, written
        # before the hang.  One breach row -- feature 325's halt.  No
        # halt events anywhere: the flatten wrote no row in any table
        # (its no-write law is why the hang could not stop it), and the
        # hung process's uncommitted insert died with it.
        assert journey.kill_rows == 1
        assert journey.halt_rows == 1
        assert journey.halt_event_rows == 0
