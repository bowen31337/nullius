"""Feature 322: the kill instruction, sent by a separate process.

The suite is organised around the feature's two claims, because they are
the two things that can silently stop being true:

* **It runs in a separate process.**  A kill sent from one interpreter is
  standing in another — asserted at the end with an actual second
  interpreter, the deployment the feature's own first clause names — and
  the row names the process that sent it, read from the kernel rather
  than accepted from the caller.  The channel's independence from the
  order layer's own member is pinned too: the module that sends a kill
  instruction *to* the order layer must not import it, or the channel
  would quietly be a function call.
* **It sends one instruction, once.**  The table holds exactly one row —
  by its schema, not by this module's discipline — the first kill's
  sender and moment stay on record, a later send writes nothing, and no
  surface this module exposes writes the row away: the kill is monotone
  because the features that own a reset (323's halt, 325's manual reset)
  have not arrived yet, and this module must not pre-empt them.

The refusals are the third subject: a send that names no channel, a
moment that states no time, a label that names no process, and a stored
row no instruction can be reconstructed as — each in its own class, each
named by the grep token its messages open with.
"""

from __future__ import annotations

import inspect
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from risk._identity import process_identity
from risk.errors import (
    KILL_INSTRUCTION_CODE,
    ORDERS_KILLED_CODE,
    RiskError,
    RiskKillSwitchError,
    RiskOrdersKilledError,
    RiskStoreError,
)
from risk.kill import (
    DATABASE_URL_ENV,
    KILL_INSTRUCTION,
    RISK_ORDER_KILL_TABLE,
    KillInstruction,
    RiskKillSwitch,
    orders_killed_error,
    require_orders_allowed,
    send_kill,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

SENT = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def switch(test_database_url: str) -> RiskKillSwitch:
    return RiskKillSwitch(test_database_url)


def _iso(moment: datetime) -> str:
    """The store's own canonical spelling, for asserting on stored strings.

    Restated rather than imported from the module's private helper, so
    these tests measure the stored spelling rather than a copy of the
    function that writes it: if the canonical form changed, a test that
    imported it would change with it and assert nothing.
    """
    return moment.astimezone(UTC).isoformat()


def _row_count(database_url: str) -> int:
    """How many rows the kill table holds, read with the driver directly.

    The one-row law is stated in the schema, so the test that pins it must
    read the table without going through the switch whose discipline the
    law exists to replace.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {RISK_ORDER_KILL_TABLE}"
            ).fetchone()[0]
        )


# -- It persists -----------------------------------------------------------------


class TestTheChannelPersists:
    def test_construction_touches_no_database(self, tmp_path: Path) -> None:
        # The composition-time promise every store in this workspace
        # states: asking for the channel is always safe, and the first
        # send is where a file is actually created.
        database = tmp_path / "not-yet.db"
        RiskKillSwitch(f"sqlite:///{database}")
        assert not database.exists()

    def test_no_instruction_stands_on_a_fresh_channel(self, switch: RiskKillSwitch) -> None:
        assert switch.standing() is None
        assert switch.killed() is False

    def test_a_sent_instruction_stands(self, switch: RiskKillSwitch) -> None:
        sent = switch.send(sent_at=SENT)
        assert sent.changed is True
        standing = switch.standing()
        assert standing is not None
        assert standing.instruction == KILL_INSTRUCTION
        assert standing.supervisor_process_id == switch.process_id
        assert standing.sent_at == SENT
        assert standing.changed is False  # a read-back wrote nothing
        assert switch.killed() is True

    def test_the_send_returns_the_stored_record(self, switch: RiskKillSwitch) -> None:
        # The caller logging the send holds the record, not a
        # re-derivation of the ask: what came back is what stands.
        sent = switch.send(sent_at=SENT)
        standing = switch.standing()
        assert standing is not None
        assert sent.sent_at == standing.sent_at
        assert sent.supervisor_process_id == standing.supervisor_process_id
        # ... except the bit that names *this* call's side effect.
        assert sent.changed is True and standing.changed is False

    def test_a_second_switch_over_the_same_url_reads_the_kill(
        self, switch: RiskKillSwitch, test_database_url: str
    ) -> None:
        # The cross-process property, in-process first: the row one switch
        # writes is the row the next switch reads, because the database —
        # not any process's memory — is the coordination point.
        switch.send(sent_at=SENT)
        other = RiskKillSwitch(test_database_url)
        assert other.killed() is True
        standing = other.standing()
        assert standing is not None
        assert standing.supervisor_process_id == switch.process_id

    def test_a_non_utc_moment_is_stored_as_the_same_instant(
        self, switch: RiskKillSwitch
    ) -> None:
        # One UTC spelling on the row, whatever offset the caller's clock
        # carried: two supervisors in two timezones that killed at the
        # same moment wrote the same instant.
        two_hours_ahead = timezone(timedelta(hours=2))
        switch.send(sent_at=SENT.astimezone(two_hours_ahead))
        standing = switch.standing()
        assert standing is not None
        assert standing.sent_at == SENT

    def test_ensure_schema_is_idempotent(self, switch: RiskKillSwitch) -> None:
        # A fresh database and one this member already prepared take the
        # same path: an operator's seeding pass can run twice.
        switch.ensure_schema()
        switch.ensure_schema()
        assert switch.standing() is None


class TestASeparateProcessSends:
    def test_the_kill_sent_by_a_second_interpreter_stands_here(
        self, tmp_path: Path
    ) -> None:
        # The real cross-process case, and the one the feature is named
        # for: a *separate interpreter* -- the supervisor process §13.3
        # speaks of -- sends the kill, and this process's order layer
        # reads it standing, named for the process that sent it.
        database = tmp_path / "cross-process.db"
        url = f"sqlite:///{database}"
        switch = RiskKillSwitch(url)
        ours = process_identity()

        script = (
            "import sys;"
            "from risk.kill import RiskKillSwitch;"
            "from risk._identity import process_identity;"
            "sent = RiskKillSwitch(sys.argv[1]).send();"
            "print(sent.supervisor_process_id == process_identity(),"
            " sent.changed, process_identity())"
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
            [sys.executable, "-c", script, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        same_process, changed, theirs = result.stdout.strip().split(" ", 2)
        assert same_process == "True" and changed == "True"

        standing = switch.standing()
        assert standing is not None
        assert standing.supervisor_process_id == theirs
        assert standing.supervisor_process_id != ours
        with pytest.raises(RiskOrdersKilledError) as raised:
            switch.require_orders_allowed()
        assert raised.value.instruction is not None
        assert raised.value.instruction.supervisor_process_id == theirs

    def test_the_module_never_reaches_the_order_layers_member(self) -> None:
        # Asserted in a subprocess, because this suite's own imports have
        # already loaded plenty.  The feature's sentence *sends a kill
        # instruction to the order layer*: an instruction that travelled
        # by importing its addressee would be a function call, and a
        # function call needs the order layer's process to be listening
        # to the supervisor's -- exactly the coupling §13.3 separates the
        # processes to break.
        script = (
            "import sys; import risk, risk.kill, risk.errors;"
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


# -- One instruction, once -------------------------------------------------------


class TestFirstWriteWins:
    def test_a_re_send_writes_nothing_and_answers_the_first_kill(
        self, switch: RiskKillSwitch
    ) -> None:
        # A supervisor sweeps again (or restarts and re-sends): the first
        # kill's sender and moment are the fact on record, and a later
        # send that moved them would quietly shrink the record of how
        # long the order layer has been obliged to stop.
        first = switch.send(sent_at=SENT)
        later = switch.send(
            sent_at=SENT + timedelta(hours=1),
            supervisor_process_id="supervisor/999",
        )
        assert later.changed is False
        assert later.sent_at == first.sent_at == SENT
        assert later.supervisor_process_id == first.supervisor_process_id
        assert _row_count(switch.database_url) == 1

    def test_the_table_itself_refuses_a_second_row(self, switch: RiskKillSwitch) -> None:
        # The one-row law lives in the schema, not in this module's
        # discipline: even a raw INSERT from another tool cannot mint a
        # second standing kill for the order layer to arbitrate.
        switch.send(sent_at=SENT)
        path = switch.database_url.removeprefix("sqlite:///")
        with (
            closing(sqlite3.connect(path)) as connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                f"INSERT INTO {RISK_ORDER_KILL_TABLE} ("
                "singleton, instruction, supervisor_process_id, sent_at"
                ") VALUES (0, 'kill', 'other/1', '2026-09-25T13:00:00+00:00')"
            )

    def test_the_table_refuses_a_row_of_another_word(self, switch: RiskKillSwitch) -> None:
        # The instruction vocabulary is closed in the schema as well as
        # in the value layer: the feature names exactly one instruction,
        # and a row wearing any other word cannot land to stand as it —
        # not by INSERT, and (the same CHECK, read over a standing row)
        # not by a later UPDATE either, which is why the read-back
        # refusals below are staged through the unconstrained columns.
        switch.send(sent_at=SENT)  # a standing row, for the UPDATE to touch
        path = switch.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT INTO {RISK_ORDER_KILL_TABLE} ("
                    "singleton, instruction, supervisor_process_id, sent_at"
                    ") VALUES (0, 'pause', 'other/1', '2026-09-25T13:00:00+00:00')"
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE {RISK_ORDER_KILL_TABLE} SET instruction = 'pause'"
                )


class TestTheKillIsMonotone:
    def test_no_surface_writes_the_row_away(self) -> None:
        # The reset features have not arrived (323's halt, 325's manual
        # reset build on this channel), and this module must not pre-empt
        # them: a kill that code could clear would make "has the order
        # layer been told to stop since T?" unanswerable at exactly the
        # moment feature 331's reconciliation asks it.
        forbidden = {
            "clear",
            "reset",
            "resume",
            "unsend",
            "unkill",
            "retract",
            "recall",
            "delete",
            "pop",
            "remove",
        }
        public = {
            name
            for name in dir(RiskKillSwitch)
            if not name.startswith("_") and callable(getattr(RiskKillSwitch, name))
        }
        assert not (public & forbidden), public & forbidden

    def test_reads_and_guards_change_nothing(self, switch: RiskKillSwitch) -> None:
        # Behavioural monotonicity: the whole read surface — the standing
        # read, the one-bit read, and the refusal — leaves the row as it
        # found it, so the kill holds no matter which door consulted it.
        switch.send(sent_at=SENT)
        for _ in range(3):
            assert switch.killed() is True
            with pytest.raises(RiskOrdersKilledError):
                switch.require_orders_allowed()
        assert _row_count(switch.database_url) == 1
        standing = switch.standing()
        assert standing is not None
        assert standing.sent_at == SENT


# -- The sender's identity -------------------------------------------------------


class TestTheSendersIdentity:
    def test_the_default_sender_is_this_process(self, switch: RiskKillSwitch) -> None:
        # "A separate process" is only checkable if the row names the
        # process that sent it — and the kernel, not the caller, is asked.
        sent = switch.send(sent_at=SENT)
        assert sent.supervisor_process_id == switch.process_id
        assert sent.supervisor_process_id == process_identity()
        host, _, pid = sent.supervisor_process_id.rpartition("/")
        assert host and pid.isdigit()

    def test_the_sender_label_is_keyword_only(self) -> None:
        # A caller on the supervisor's own path should not pass it at
        # all; the one that does (a replay of a recorded kill) has to say
        # so explicitly — same reason feature 320's record keeps its
        # process_id keyword-only.
        parameters = inspect.signature(RiskKillSwitch.send).parameters
        assert set(parameters) == {"self", "sent_at", "supervisor_process_id"}
        assert parameters["supervisor_process_id"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_an_explicit_label_is_filed_as_given(self, switch: RiskKillSwitch) -> None:
        sent = switch.send(
            sent_at=SENT, supervisor_process_id="bastion-supervisor/1"
        )
        assert sent.supervisor_process_id == "bastion-supervisor/1"
        standing = switch.standing()
        assert standing is not None
        assert standing.supervisor_process_id == "bastion-supervisor/1"

    def test_a_label_that_names_no_process_is_refused(self, switch: RiskKillSwitch) -> None:
        for label in ("", "   ", 7):
            with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE):
                switch.send(sent_at=SENT, supervisor_process_id=label)


# -- The guard -------------------------------------------------------------------


class TestTheGuard:
    def test_it_passes_while_no_kill_stands(self, switch: RiskKillSwitch) -> None:
        switch.require_orders_allowed()  # no refusal, no row written
        assert _row_count(switch.database_url) == 0

    def test_it_refuses_under_a_standing_kill(self, switch: RiskKillSwitch) -> None:
        sent = switch.send(sent_at=SENT)
        with pytest.raises(RiskOrdersKilledError) as raised:
            switch.require_orders_allowed()
        assert raised.value.instruction == KillInstruction(
            instruction=sent.instruction,
            supervisor_process_id=sent.supervisor_process_id,
            sent_at=sent.sent_at,
            changed=False,
        )

    def test_the_refusal_is_greppable_and_names_the_sender(
        self, switch: RiskKillSwitch
    ) -> None:
        switch.send(sent_at=SENT, supervisor_process_id="supervisor/4711")
        with pytest.raises(RiskOrdersKilledError) as raised:
            switch.require_orders_allowed()
        message = str(raised.value)
        assert message.startswith(f"{ORDERS_KILLED_CODE}:")
        assert "supervisor/4711" in message
        assert _iso(SENT) in message

    def test_the_refusal_is_caught_as_the_members_base(self, switch: RiskKillSwitch) -> None:
        # A caller catching the member's one vocabulary catches the kill's
        # receipt along with the channel's faults.
        switch.send(sent_at=SENT)
        with pytest.raises(RiskError):
            switch.require_orders_allowed()

    def test_the_refusal_builder_takes_only_a_record(self) -> None:
        with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE):
            orders_killed_error("not a kill instruction")


# -- The refusals ----------------------------------------------------------------


class TestTheAskIsRefused:
    def test_a_naive_moment_is_refused(self, switch: RiskKillSwitch) -> None:
        with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE):
            switch.send(sent_at=SENT.replace(tzinfo=None))

    def test_a_non_moment_is_refused(self, switch: RiskKillSwitch) -> None:
        with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE):
            switch.send(sent_at=SENT.isoformat())  # type: ignore[arg-type]

    def test_the_value_layer_refuses_another_word(self) -> None:
        with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE):
            KillInstruction(
                instruction="pause",
                supervisor_process_id="supervisor/1",
                sent_at=SENT,
                changed=True,
            )

    def test_the_value_layer_refuses_a_non_bool_changed(self) -> None:
        with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE):
            KillInstruction(
                instruction=KILL_INSTRUCTION,
                supervisor_process_id="supervisor/1",
                sent_at=SENT,
                changed=1,  # type: ignore[arg-type]
            )


class TestTheChannelAddress:
    def test_a_non_sqlite_scheme_is_refused_by_name(
        self, test_database_url: str
    ) -> None:
        switch = RiskKillSwitch("postgres://localhost/risk")
        with pytest.raises(RiskStoreError, match="postgres"):
            switch.send(sent_at=SENT)

    def test_an_in_memory_database_is_refused_by_name(self) -> None:
        # An in-memory channel would die with the connection that opened
        # it, and the kill would vanish with the supervisor's process.
        switch = RiskKillSwitch("sqlite:///:memory:")
        with pytest.raises(RiskStoreError, match="in-memory"):
            switch.send(sent_at=SENT)

    def test_a_host_on_the_sqlite_url_is_refused_by_name(self) -> None:
        switch = RiskKillSwitch("sqlite://risk-host/risk.db")
        with pytest.raises(RiskStoreError, match="risk-host"):
            switch.send(sent_at=SENT)

    def test_an_empty_url_is_refused_at_construction(self) -> None:
        with pytest.raises(RiskStoreError):
            RiskKillSwitch("   ")

    def test_resolve_answers_none_when_nothing_names_a_store(self) -> None:
        assert RiskKillSwitch.resolve(env={}) is None
        assert RiskKillSwitch.resolve(env={DATABASE_URL_ENV: "   "}) is None

    def test_resolve_reads_the_environment_it_is_given(self) -> None:
        switch = RiskKillSwitch.resolve(env={DATABASE_URL_ENV: "sqlite:///given.db"})
        assert switch is not None
        assert switch.database_url == "sqlite:///given.db"


class TestTheModuleLevelSpellings:
    def test_send_kill_refuses_when_nothing_names_a_channel(self) -> None:
        # The one direction of the channel's absence that must not fail
        # softly: a supervisor that believed it had killed the order
        # layer, while the order layer kept trading.
        with pytest.raises(RiskKillSwitchError, match=DATABASE_URL_ENV):
            send_kill(env={})

    def test_send_kill_sends_through_the_named_channel(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'sent.db'}"
        sent = send_kill(database_url=url, sent_at=SENT)
        assert sent.changed is True
        standing = RiskKillSwitch(url).standing()
        assert standing is not None
        assert standing.sent_at == SENT

    def test_require_orders_allowed_passes_vacuously_without_a_channel(self) -> None:
        # A deployment with no relational store has no channel, so no
        # kill was ever sent through one: distinct from a checked channel
        # holding no kill, and deliberately not an exception.
        require_orders_allowed(env={})

    def test_require_orders_allowed_refuses_through_the_named_channel(
        self, tmp_path: Path
    ) -> None:
        url = f"sqlite:///{tmp_path / 'sent.db'}"
        send_kill(database_url=url, sent_at=SENT)
        with pytest.raises(RiskOrdersKilledError):
            require_orders_allowed(database_url=url)


class TestARowEditedOutsideThePackage:
    def test_a_row_of_an_unparseable_moment_is_refused_on_read(
        self, switch: RiskKillSwitch
    ) -> None:
        switch.send(sent_at=SENT)
        path = switch.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                f"UPDATE {RISK_ORDER_KILL_TABLE} SET sent_at = 'not a moment'"
            )
        with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE) as raised:
            switch.standing()
        assert "not a moment" in str(raised.value)

    def test_a_row_of_no_sender_is_refused_on_read(self, switch: RiskKillSwitch) -> None:
        switch.send(sent_at=SENT)
        path = switch.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                f"UPDATE {RISK_ORDER_KILL_TABLE} SET supervisor_process_id = ' '"
            )
        with pytest.raises(RiskKillSwitchError, match=KILL_INSTRUCTION_CODE):
            switch.standing()

    def test_a_row_that_cannot_be_reconstructed_never_answers_a_clean_bill(
        self, switch: RiskKillSwitch
    ) -> None:
        # The safe direction of the refusal: a row that cannot be
        # reconstructed is refused loudly (an operator gets a fault to
        # repair), rather than laundered into either a standing kill or
        # a silent all-clear.  Staged through the unconstrained columns —
        # the instruction word itself is CHECK'd in the schema, so the
        # one tamper the value layer also refuses cannot even land.
        switch.send(sent_at=SENT)
        path = switch.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                f"UPDATE {RISK_ORDER_KILL_TABLE} SET sent_at = 'not a moment'"
            )
        with pytest.raises(RiskKillSwitchError):
            switch.killed()


# -- The record's own shape -------------------------------------------------------


class TestTheRecordsOwnShape:
    def test_the_summary_names_the_sender_and_the_moment(self) -> None:
        instruction = KillInstruction(
            instruction=KILL_INSTRUCTION,
            supervisor_process_id="supervisor/4711",
            sent_at=SENT,
            changed=True,
        )
        assert "supervisor/4711" in instruction.summary
        assert _iso(SENT) in instruction.summary

    def test_the_record_is_frozen(self, switch: RiskKillSwitch) -> None:
        sent = switch.send(sent_at=SENT)
        with pytest.raises(FrozenInstanceError):
            sent.instruction = "pause"  # type: ignore[misc]
