"""Feature 331: every halt event, persisted with its reason and timestamp.

The suite is organised around the sentence's three claims, because they
are the three things that can silently stop being true:

* **Every halt event is persisted.**  The ledger is append-only: a halt
  that happened twice is recorded twice, a duplicate reason is a second
  row, and no surface this module exposes writes a row away.  This is
  the deliberate opposite of the channel beside it — ``risk_order_kill``
  is the one-row state that stands, and the pair of laws is pinned by
  one test that sends a kill and records two halts over the same store.
* **Each row carries its trigger reason and its timestamp.**  The reason
  is the halting feature's own word (the vocabulary is deliberately
  open — 323–329 own their words), refused only when it states nothing;
  the moment is timezone-aware and stored in the one canonical UTC
  spelling; and the row names the process that recorded it, read from
  the kernel rather than accepted from the caller.
* **For later reconciliation.**  The read is a sweep — every event,
  oldest first, ordered by the trigger's own moment with the append
  order breaking same-instant ties — and a caller anchoring it at an
  instant reads the suffix from there, inclusively.  The anchor the
  channel's own docstrings promised this ledger is pinned by the test
  that joins a kill's ``sent_at`` to the events that follow it, and the
  cross-process case is asserted against an actual second interpreter:
  the event a separate supervisor records is the event this process
  reconciles.

The refusals are the fourth subject: a reason that states nothing, a
moment that states no time, a record that names no store, and a stored
row no event can be reconstructed as — each in its own class, each named
by the grep token its messages open with.
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
    HALT_EVENT_CODE,
    RiskError,
    RiskHaltEventError,
    RiskStoreError,
)
from risk.halt_events import (
    DATABASE_URL_ENV,
    RISK_HALT_EVENT_TABLE,
    HaltEvent,
    RiskHaltEventStore,
    record_halt,
    recorded_halt_events,
)
from risk.kill import RISK_ORDER_KILL_TABLE, send_kill

REPO_ROOT = Path(__file__).resolve().parents[3]

TRIGGERED = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
LATER = TRIGGERED + timedelta(hours=1)
EARLIER = TRIGGERED - timedelta(hours=1)


@pytest.fixture
def store(test_database_url: str) -> RiskHaltEventStore:
    return RiskHaltEventStore(test_database_url)


def _iso(moment: datetime) -> str:
    """The store's own canonical spelling, for asserting on stored strings.

    Restated rather than imported from the module's private helper, so
    these tests measure the stored spelling rather than a copy of the
    function that writes it: if the canonical form changed, a test that
    imported it would change with it and assert nothing.
    """
    return moment.astimezone(UTC).isoformat()


def _row_count(database_url: str) -> int:
    """How many rows the ledger holds, read with the driver directly.

    The append-only law is stated in this module's refusal to write rows
    away, so the test that pins it must read the table without going
    through the store whose discipline the law exists to replace.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {RISK_HALT_EVENT_TABLE}"
            ).fetchone()[0]
        )


# -- It persists -----------------------------------------------------------------


class TestTheLedgerPersists:
    def test_construction_touches_no_database(self, tmp_path: Path) -> None:
        # The composition-time promise every store in this workspace
        # states: asking for the ledger is always safe, and the first
        # record is where a file is actually created.
        database = tmp_path / "not-yet.db"
        RiskHaltEventStore(f"sqlite:///{database}")
        assert not database.exists()

    def test_a_fresh_ledger_holds_no_events(self, store: RiskHaltEventStore) -> None:
        assert store.events() == ()

    def test_a_recorded_event_reads_back(self, store: RiskHaltEventStore) -> None:
        recorded = store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        events = store.events()
        assert len(events) == 1
        (event,) = events
        assert event.sequence == recorded.sequence
        assert event.trigger_reason == "manual_halt"
        assert event.triggered_at == TRIGGERED
        assert event.recorded_at == recorded.recorded_at
        assert event.supervisor_process_id == store.process_id

    def test_the_record_carries_its_reason_and_its_moments(
        self, store: RiskHaltEventStore
    ) -> None:
        # The sentence's own terms, on the value the caller holds: a
        # reason, the moment the trigger fired, and — the split canary's
        # halt rows take — the moment the row was written, beside the
        # identity of the process that wrote it.
        event = store.record(trigger_reason="equity_floor", triggered_at=TRIGGERED)
        assert event.trigger_reason == "equity_floor"
        assert event.triggered_at == TRIGGERED
        assert event.recorded_at.tzinfo is not None
        assert event.supervisor_process_id == process_identity()

    def test_recorded_at_is_not_the_callers_to_state(self) -> None:
        # When the row was written is the ledger's own fact: a caller
        # that could set it could forge the very gap between trigger
        # and record a reconciliation reads.
        parameters = inspect.signature(RiskHaltEventStore.record).parameters
        assert "recorded_at" not in parameters

    def test_the_moments_and_reason_are_stored_in_one_canonical_spelling(
        self, store: RiskHaltEventStore
    ) -> None:
        store.record(trigger_reason="clock_skew", triggered_at=TRIGGERED)
        path = store.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            row = connection.execute(
                f"SELECT trigger_reason, triggered_at, recorded_at,"
                f" supervisor_process_id FROM {RISK_HALT_EVENT_TABLE}"
            ).fetchone()
        assert row[0] == "clock_skew"
        assert row[1] == _iso(TRIGGERED)
        assert row[2] == _iso(datetime.fromisoformat(row[2]))
        assert row[3] == store.process_id

    def test_a_non_utc_moment_is_stored_as_the_same_instant(
        self, store: RiskHaltEventStore
    ) -> None:
        # One UTC spelling on the row, whatever offset the caller's clock
        # carried: two supervisors in two timezones that halted at the
        # same moment wrote the same instant, and the sweep orders them
        # as one.
        two_hours_ahead = timezone(timedelta(hours=2))
        store.record(
            trigger_reason="staleness", triggered_at=TRIGGERED.astimezone(two_hours_ahead)
        )
        (event,) = store.events()
        assert event.triggered_at == TRIGGERED

    def test_ensure_schema_is_idempotent(self, store: RiskHaltEventStore) -> None:
        # A fresh database and one this member already prepared take the
        # same path: an operator's seeding pass can run twice.
        store.ensure_schema()
        store.ensure_schema()
        assert store.events() == ()

    def test_a_late_recorded_event_keeps_its_own_moment(
        self, store: RiskHaltEventStore
    ) -> None:
        # A supervisor that recovers and records the halt it observed
        # while hung writes a row whose recorded_at is now but whose
        # triggered_at is the historical moment — and the sweep answers
        # *when did halts happen*, not *when did we find out*.
        hung_moment = datetime.now(UTC) - timedelta(hours=2)
        late = store.record(trigger_reason="staleness", triggered_at=hung_moment)
        assert late.recorded_at > late.triggered_at
        assert store.events()[0].triggered_at == hung_moment


class TestEveryEventIsRecorded:
    def test_a_second_event_is_a_second_row(self, store: RiskHaltEventStore) -> None:
        # The ledger's law, and the deliberate opposite of the channel's:
        # a halt that happened twice is recorded twice, because
        # completeness — not the first fact — is what a reconciliation
        # depends on.
        first = store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        second = store.record(trigger_reason="manual_halt", triggered_at=LATER)
        assert _row_count(store.database_url) == 2
        assert (first.sequence, second.sequence) == (1, 2)

    def test_a_duplicate_reason_is_not_a_deduplication(
        self, store: RiskHaltEventStore
    ) -> None:
        # The identical ask, twice: both happened, both are on record —
        # there is no first-write-wins here to quietly shrink the log.
        store.record(trigger_reason="daily_loss_limit", triggered_at=TRIGGERED)
        store.record(trigger_reason="daily_loss_limit", triggered_at=TRIGGERED)
        assert _row_count(store.database_url) == 2
        reasons = [event.trigger_reason for event in store.events()]
        assert reasons == ["daily_loss_limit", "daily_loss_limit"]

    def test_the_ledger_mints_monotone_numbers(
        self, store: RiskHaltEventStore
    ) -> None:
        sequences = [
            store.record(trigger_reason="manual_halt", triggered_at=moment).sequence
            for moment in (TRIGGERED, LATER, EARLIER)
        ]
        assert sequences == sorted(sequences) == [1, 2, 3]

    def test_the_channel_still_holds_one_row_while_the_ledger_holds_many(
        self, store: RiskHaltEventStore, test_database_url: str
    ) -> None:
        # The two tables' laws coexist on one store: a kill lands once
        # (the state that stands) while the halt events beside it append
        # (the log of what happened) — the shape difference this
        # feature's sentence is the second half of.
        send_kill(database_url=test_database_url, sent_at=TRIGGERED)
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        store.record(trigger_reason="manual_halt", triggered_at=LATER)
        path = test_database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            kills = connection.execute(
                f"SELECT COUNT(*) FROM {RISK_ORDER_KILL_TABLE}"
            ).fetchone()[0]
        assert kills == 1
        assert _row_count(test_database_url) == 2


class TestASeparateProcessRecords:
    def test_the_event_a_second_interpreter_records_reconciles_here(
        self, tmp_path: Path
    ) -> None:
        # The real cross-process case, and the one the sentence's second
        # half is for: a *separate interpreter* — the supervisor process
        # §13.3 speaks of — records the halt, and this process's
        # reconciliation reads it, named for the process that recorded it.
        database = tmp_path / "cross-process.db"
        url = f"sqlite:///{database}"
        store = RiskHaltEventStore(url)
        ours = process_identity()

        script = (
            "import sys;"
            "from risk.halt_events import RiskHaltEventStore;"
            "from risk._identity import process_identity;"
            "event = RiskHaltEventStore(sys.argv[1]).record("
            "trigger_reason='equity_floor');"
            "print(event.supervisor_process_id == process_identity(),"
            " event.sequence, process_identity())"
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
        same_process, sequence, theirs = result.stdout.strip().split(" ", 2)
        assert same_process == "True" and sequence == "1"

        (event,) = store.events()
        assert event.trigger_reason == "equity_floor"
        assert event.supervisor_process_id == theirs
        assert event.supervisor_process_id != ours

    def test_this_process_appends_after_theirs(
        self, tmp_path: Path
    ) -> None:
        # The database, not any process's memory, is the coordination
        # point: their event keeps its number and this process's lands
        # after it, in one ledger both reconcile identically.
        database = tmp_path / "two-writers.db"
        url = f"sqlite:///{database}"
        script = (
            "import sys;"
            "from risk.halt_events import RiskHaltEventStore;"
            "RiskHaltEventStore(sys.argv[1]).record(trigger_reason='manual_halt')"
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
        ours = RiskHaltEventStore(url).record(
            trigger_reason="staleness", triggered_at=LATER
        )
        assert ours.sequence == 2
        assert _row_count(url) == 2


# -- For later reconciliation ------------------------------------------------------


class TestTheReconciliationRead:
    def test_the_sweep_orders_events_by_their_own_moments(
        self, store: RiskHaltEventStore
    ) -> None:
        store.record(trigger_reason="staleness", triggered_at=LATER)
        store.record(trigger_reason="equity_floor", triggered_at=EARLIER)
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        assert [event.trigger_reason for event in store.events()] == [
            "equity_floor",
            "manual_halt",
            "staleness",
        ]

    def test_same_instant_events_keep_their_recording_order(
        self, store: RiskHaltEventStore
    ) -> None:
        # Two halts triggered at the same instant are told apart by the
        # ledger's own numbers, in the order they were recorded — the
        # only order they have.
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        store.record(trigger_reason="staleness", triggered_at=TRIGGERED)
        events = store.events()
        assert [event.sequence for event in events] == [1, 2]
        assert [event.trigger_reason for event in events] == [
            "manual_halt",
            "staleness",
        ]

    def test_the_read_answers_a_tuple(self, store: RiskHaltEventStore) -> None:
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        events = store.events()
        assert isinstance(events, tuple)
        assert all(isinstance(event, HaltEvent) for event in events)

    def test_the_anchor_is_inclusive(self, store: RiskHaltEventStore) -> None:
        # The workspace's window convention, and the one that makes the
        # join with the channel honest: an event triggered at exactly
        # the anchor instant is part of the story the anchor begins.
        store.record(trigger_reason="equity_floor", triggered_at=EARLIER)
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        anchored = store.events(since=TRIGGERED)
        assert [event.trigger_reason for event in anchored] == ["manual_halt"]

    def test_the_kill_and_its_events_reconcile_at_one_anchor(
        self, store: RiskHaltEventStore, test_database_url: str
    ) -> None:
        # The join the channel's own docstrings promised this ledger: a
        # kill sent at T is the anchor, and the reconciliation sweeping
        # from T finds the halt events of the episode it began —
        # including one recorded at exactly T, and none from before it.
        kill = send_kill(database_url=test_database_url, sent_at=TRIGGERED)
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        store.record(trigger_reason="staleness", triggered_at=LATER)
        store.record(trigger_reason="equity_floor", triggered_at=EARLIER)
        swept = store.events(since=kill.sent_at)
        assert [event.trigger_reason for event in swept] == [
            "manual_halt",
            "staleness",
        ]
        assert swept[0].triggered_at == kill.sent_at

    def test_a_naive_anchor_is_refused(self, store: RiskHaltEventStore) -> None:
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
            store.events(since=TRIGGERED.replace(tzinfo=None))


class TestTheLedgerIsAppendOnly:
    def test_no_surface_writes_the_rows_away(self) -> None:
        # The ledger is the record a later reconciliation sweeps, and a
        # surface that could trim it would make "what halted between T
        # and T'?" unanswerable at exactly the moment the question is
        # asked — the same monotonicity the kill channel states for its
        # one row, held here by refusing the verbs entirely.
        forbidden = {
            "clear",
            "reset",
            "resume",
            "erase",
            "unrecord",
            "retract",
            "recall",
            "delete",
            "pop",
            "remove",
            "trim",
            "prune",
            "amend",
            "rewrite",
        }
        public = {
            name
            for name in dir(RiskHaltEventStore)
            if not name.startswith("_") and callable(getattr(RiskHaltEventStore, name))
        }
        assert not (public & forbidden), public & forbidden

    def test_the_module_shelters_no_row_disposal(self) -> None:
        # The class surface can grow a helper with a clean name; the
        # SQL cannot hide.  No statement this module issues against the
        # ledger's table may dispose of a row — the law the schema
        # cannot state (SQLite has no GRANT to refuse it) and this
        # module's discipline therefore holds.
        source = Path(inspect.getsourcefile(RiskHaltEventStore)).read_text()
        assert "DELETE" not in source
        assert f"UPDATE {RISK_HALT_EVENT_TABLE}" not in source

    def test_reads_change_nothing(self, store: RiskHaltEventStore) -> None:
        # Behavioural append-only-ness: the whole read surface leaves
        # the rows as it found them, swept once or swept repeatedly.
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        store.record(trigger_reason="staleness", triggered_at=LATER)
        for _ in range(3):
            assert len(store.events()) == 2
            assert len(store.events(since=TRIGGERED)) == 2
        assert _row_count(store.database_url) == 2

    def test_a_second_store_over_the_same_url_appends(
        self, store: RiskHaltEventStore, test_database_url: str
    ) -> None:
        # The cross-process property, in-process first: a reader that
        # becomes a writer appends to the same ledger it swept, and the
        # rows it read are the rows that stay.
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        other = RiskHaltEventStore(test_database_url)
        assert len(other.events()) == 1
        second = other.record(trigger_reason="staleness", triggered_at=LATER)
        assert second.sequence == 2
        assert len(store.events()) == 2


# -- The recorder's identity -------------------------------------------------------


class TestTheRecordersIdentity:
    def test_the_default_recorder_is_this_process(
        self, store: RiskHaltEventStore
    ) -> None:
        event = store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        assert event.supervisor_process_id == store.process_id
        assert event.supervisor_process_id == process_identity()
        host, _, pid = event.supervisor_process_id.rpartition("/")
        assert host and pid.isdigit()

    def test_the_terms_are_keyword_only(self) -> None:
        # A caller on the supervisor's own path should pass neither of
        # these; the ones that do — an operator re-pronouncing a halt
        # observed before the store was reachable, a replay — have to
        # say so explicitly.  The reason itself is keyword-only too, so
        # a caller reads as naming the thing it halted for.
        parameters = inspect.signature(RiskHaltEventStore.record).parameters
        assert set(parameters) == {
            "self",
            "trigger_reason",
            "triggered_at",
            "supervisor_process_id",
        }
        for name, parameter in parameters.items():
            if name == "self":
                continue
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name

    def test_an_explicit_label_is_filed_as_given(
        self, store: RiskHaltEventStore
    ) -> None:
        event = store.record(
            trigger_reason="manual_halt",
            triggered_at=TRIGGERED,
            supervisor_process_id="bastion-supervisor/1",
        )
        assert event.supervisor_process_id == "bastion-supervisor/1"
        (read_back,) = store.events()
        assert read_back.supervisor_process_id == "bastion-supervisor/1"

    def test_a_label_that_names_no_process_is_refused(
        self, store: RiskHaltEventStore
    ) -> None:
        for label in ("", "   ", 7):
            with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
                store.record(
                    trigger_reason="manual_halt",
                    triggered_at=TRIGGERED,
                    supervisor_process_id=label,
                )


# -- The refusals -------------------------------------------------------------------


class TestTheEventsOwnTerms:
    def test_a_reason_that_states_nothing_is_refused(
        self, store: RiskHaltEventStore
    ) -> None:
        for reason in ("", "   ", 7, None):
            with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
                store.record(trigger_reason=reason, triggered_at=TRIGGERED)
        assert store.events() == ()

    def test_the_vocabulary_is_open_and_the_word_lands_as_given(
        self, store: RiskHaltEventStore
    ) -> None:
        # §13.3's table names the triggers, but the *words* belong to
        # the features that fire them — none of which has arrived yet.
        # The ledger carries any word it is handed, so a trigger
        # feature's own spelling is never refused at the door.
        for word in ("equity_floor", "manual halt", "clock_skew_v2"):
            event = store.record(trigger_reason=word, triggered_at=TRIGGERED)
            assert event.trigger_reason == word

    def test_a_naive_moment_is_refused(self, store: RiskHaltEventStore) -> None:
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
            store.record(
                trigger_reason="manual_halt",
                triggered_at=TRIGGERED.replace(tzinfo=None),
            )

    def test_a_non_moment_is_refused(self, store: RiskHaltEventStore) -> None:
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
            store.record(trigger_reason="manual_halt", triggered_at="12:00")

    def test_the_value_layer_refuses_a_reasonless_event(self) -> None:
        for reason in ("", "   ", 7):
            with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
                HaltEvent(
                    sequence=1,
                    trigger_reason=reason,
                    triggered_at=TRIGGERED,
                    recorded_at=TRIGGERED,
                    supervisor_process_id="supervisor/1",
                )

    def test_the_value_layer_refuses_a_momentless_event(self) -> None:
        for moment in (TRIGGERED.replace(tzinfo=None), "12:00"):
            with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
                HaltEvent(
                    sequence=1,
                    trigger_reason="manual_halt",
                    triggered_at=moment,
                    recorded_at=TRIGGERED,
                    supervisor_process_id="supervisor/1",
                )

    def test_the_value_layer_refuses_a_sequence_the_ledger_never_minted(self) -> None:
        # The number is how an operator cites one event in a
        # reconciliation report; a value wearing one the ledger cannot
        # mint — 0, a negative, a bool dressed as an int, a string — is
        # a row no reader filed.
        for sequence in (0, -1, True, "1", 1.0):
            with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
                HaltEvent(
                    sequence=sequence,
                    trigger_reason="manual_halt",
                    triggered_at=TRIGGERED,
                    recorded_at=TRIGGERED,
                    supervisor_process_id="supervisor/1",
                )

    def test_the_record_is_frozen(self, store: RiskHaltEventStore) -> None:
        event = store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        with pytest.raises(FrozenInstanceError):
            event.trigger_reason = "staleness"  # type: ignore[misc]


class TestTheStoresOwnFaults:
    def test_a_non_sqlite_scheme_is_refused_by_name(
        self, store: RiskHaltEventStore
    ) -> None:
        broken = RiskHaltEventStore("postgres://localhost/risk")
        with pytest.raises(RiskStoreError, match="postgres"):
            broken.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)

    def test_an_in_memory_database_is_refused_by_name(self) -> None:
        store = RiskHaltEventStore("sqlite:///:memory:")
        with pytest.raises(RiskStoreError, match="in-memory"):
            store.events()

    def test_a_host_on_the_sqlite_url_is_refused_by_name(self) -> None:
        store = RiskHaltEventStore("sqlite://elsewhere/risk.db")
        with pytest.raises(RiskStoreError, match="host"):
            store.events()

    def test_an_empty_url_is_refused_at_construction(self) -> None:
        for url in ("", "   "):
            with pytest.raises(RiskStoreError):
                RiskHaltEventStore(url)

    def test_resolve_answers_none_when_nothing_names_a_store(self) -> None:
        assert RiskHaltEventStore.resolve(env={}) is None

    def test_resolve_reads_the_environment_it_is_given(self) -> None:
        resolved = RiskHaltEventStore.resolve(
            env={DATABASE_URL_ENV: "sqlite:///given.db"}
        )
        assert resolved is not None
        assert resolved.database_url == "sqlite:///given.db"


class TestTheModuleLevelSpellings:
    def test_record_halt_refuses_when_nothing_names_a_store(self) -> None:
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE) as raised:
            record_halt(trigger_reason="manual_halt", env={})
        assert DATABASE_URL_ENV in str(raised.value)

    def test_record_halt_records_through_the_named_channel(
        self, tmp_path: Path
    ) -> None:
        url = f"sqlite:///{tmp_path / 'recorded.db'}"
        event = record_halt(
            trigger_reason="manual_halt",
            database_url=url,
            triggered_at=TRIGGERED,
        )
        assert event.triggered_at == TRIGGERED
        assert len(recorded_halt_events(database_url=url)) == 1

    def test_record_halt_reads_the_environment(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'from-env.db'}"
        monkeypatch.setenv(DATABASE_URL_ENV, url)
        event = record_halt(trigger_reason="manual_halt")
        assert event.supervisor_process_id == process_identity()
        assert _row_count(url) == 1

    def test_recorded_halt_events_answers_the_empty_truth_without_a_store(
        self,
    ) -> None:
        # Recording refuses without a store, so a deployment that names
        # none holds no events to reconcile: the empty tuple is the
        # truthful answer, not a clean bill — the reconciler's half of
        # the split the channel's guard takes for its own side.
        assert recorded_halt_events(env={}) == ()
        assert recorded_halt_events(env={}, since=TRIGGERED) == ()

    def test_recorded_halt_events_sweeps_through_the_named_store(
        self, tmp_path: Path
    ) -> None:
        url = f"sqlite:///{tmp_path / 'swept.db'}"
        record_halt(
            trigger_reason="equity_floor", database_url=url, triggered_at=EARLIER
        )
        record_halt(
            trigger_reason="manual_halt", database_url=url, triggered_at=TRIGGERED
        )
        swept = recorded_halt_events(database_url=url, since=TRIGGERED)
        assert [event.trigger_reason for event in swept] == ["manual_halt"]


# -- Rows no event can be ------------------------------------------------------------


class TestRowsNoEventCanBe:
    def test_a_row_of_an_unparseable_moment_is_refused_on_read(
        self, store: RiskHaltEventStore
    ) -> None:
        # Staged through the unconstrained columns, because the moment's
        # spelling is the value layer's law, not the schema's: a row
        # another tool wrote in a moment no parser accepts must refuse
        # the sweep rather than ride it unparsed.
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        path = store.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                f"UPDATE {RISK_HALT_EVENT_TABLE} SET triggered_at = 'not a moment'"
            )
            connection.commit()
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE) as raised:
            store.events()
        assert "not a moment" in str(raised.value)

    def test_a_row_of_no_reason_is_refused_on_read(
        self, store: RiskHaltEventStore
    ) -> None:
        # The reason column carries no CHECK — the vocabulary is the
        # trigger features' own, and the schema must not refuse their
        # words — so an empty reason *can* land from outside, and the
        # read is where it is refused.
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        path = store.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                f"UPDATE {RISK_HALT_EVENT_TABLE} SET trigger_reason = ''"
            )
            connection.commit()
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
            store.events()

    def test_a_row_of_a_naive_moment_is_refused_on_read(
        self, store: RiskHaltEventStore
    ) -> None:
        # Parseable but not orderable: a naive spelling would sort
        # against nothing, and an event that cannot take its place in
        # the sweep is not an event that happens to be early.
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        path = store.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                f"UPDATE {RISK_HALT_EVENT_TABLE}"
                " SET triggered_at = '2026-09-25T12:00:00'"
            )
            connection.commit()
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
            store.events()

    def test_a_row_of_a_sequence_the_ledger_never_minted_is_refused_on_read(
        self, store: RiskHaltEventStore
    ) -> None:
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        path = store.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                f"UPDATE {RISK_HALT_EVENT_TABLE} SET sequence = 0"
            )
            connection.commit()
        with pytest.raises(RiskHaltEventError, match=HALT_EVENT_CODE):
            store.events()

    def test_the_refusal_names_the_row_it_came_from(
        self, store: RiskHaltEventStore
    ) -> None:
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        path = store.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                f"UPDATE {RISK_HALT_EVENT_TABLE} SET triggered_at = 'garbage'"
            )
            connection.commit()
        with pytest.raises(RiskHaltEventError, match="halt event row numbered") as raised:
            store.events()
        # An operator gets the row to repair, not a value with no
        # address: the refusal carries the number and the recorder.
        assert "1" in str(raised.value)

    def test_a_row_that_cannot_be_reconstructed_hides_no_good_rows(
        self, store: RiskHaltEventStore
    ) -> None:
        # The refusal, not a skip: a skipped row would be a hole wearing
        # a shrug, and completeness is this table's law — so one bad row
        # refuses the sweep it would have ridden, loudly enough to grep.
        store.record(trigger_reason="manual_halt", triggered_at=TRIGGERED)
        store.record(trigger_reason="staleness", triggered_at=LATER)
        path = store.database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                f"UPDATE {RISK_HALT_EVENT_TABLE} SET recorded_at = 'later?'"
                " WHERE sequence = 1"
            )
            connection.commit()
        with pytest.raises((RiskHaltEventError, RiskError)):
            store.events(since=EARLIER)

    def test_every_refusal_is_caught_as_the_members_base(
        self, store: RiskHaltEventStore
    ) -> None:
        with pytest.raises(RiskError):
            store.record(trigger_reason="   ")
        with pytest.raises(RiskError):
            store.record(trigger_reason="manual_halt", triggered_at="when?")


# -- The summary ---------------------------------------------------------------------


class TestTheSummary:
    def test_the_summary_names_the_reason_the_moments_and_the_recorder(
        self, store: RiskHaltEventStore
    ) -> None:
        event = store.record(
            trigger_reason="staleness",
            triggered_at=TRIGGERED,
            supervisor_process_id="bastion-supervisor/1",
        )
        summary = event.summary
        assert "staleness" in summary
        assert _iso(TRIGGERED) in summary
        assert "bastion-supervisor/1" in summary
        assert str(event.sequence) in summary
