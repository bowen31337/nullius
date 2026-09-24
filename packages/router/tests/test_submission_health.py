"""Feature 320: the router's own submission health, persisted and read.

The suite is organised around the feature's two claims, because they are
the two things that can silently stop being true:

* **It persists.**  An attempt recorded in one store is readable from a
  *second* store built over the same ``DATABASE_URL`` — which is what
  "persists independently" means operationally, and the one property an
  in-memory flag would fail.  The real cross-process case is asserted at the
  end with an actual second interpreter.
* **It is independent of feed health.**  Nothing in the reading depends on
  a feed, a heartbeat or a clock but the one that bounds the window, so an
  all-accepted window reads healthy with no market data anywhere in sight
  and an all-rejected one reads unhealthy.  The module's imports are pinned
  too: it must not reach the ingest member's streams, because a health
  reading that read the feed would be exactly the conflation the feature's
  own sentence forbids.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import pytest
from router.errors import (
    ORDER_SUBMISSION_UNHEALTHY_CODE,
    RouterError,
    RouterFilterError,
    RouterStoreError,
    RouterSubmissionHealthError,
)
from router.submission_health import (
    ORDER_SUBMISSION_ACCEPTED,
    ORDER_SUBMISSION_HEALTH_TABLE,
    ORDER_SUBMISSION_OUTCOMES,
    ORDER_SUBMISSION_REJECTED,
    SUBMISSION_HEALTH_FAILURE_RATIO,
    SUBMISSION_HEALTH_WINDOW,
    RouterSubmissionHealthStore,
    SubmissionHealth,
    SubmissionObservation,
    process_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=5)


@pytest.fixture
def store(test_database_url: str) -> RouterSubmissionHealthStore:
    return RouterSubmissionHealthStore(test_database_url)


def _iso(moment: datetime) -> str:
    """The store's own canonical spelling, for asserting on stored strings.

    Restated rather than imported from the module's private helper, so these
    tests measure the stored spelling rather than a copy of the function that
    writes it: if ``_isoformat_utc`` changed, a test that imported it would
    change with it and assert nothing.
    """
    return moment.astimezone(UTC).isoformat()


def _record(
    store: RouterSubmissionHealthStore,
    outcomes: str | list[str],
    *,
    at: datetime = NOW,
    spacing: timedelta = timedelta(0),
    **kwargs,
) -> None:
    """Record one attempt per outcome token, ``spacing`` apart."""
    for offset, outcome in enumerate(
        outcomes if isinstance(outcomes, list) else [outcomes]
    ):
        store.record(outcome=outcome, observed_at=at + offset * spacing, **kwargs)


class TestResolve:
    def test_resolves_from_database_url(self, test_database_url: str) -> None:
        resolved = RouterSubmissionHealthStore.resolve()
        assert resolved is not None
        assert resolved.database_url == test_database_url

    @pytest.mark.parametrize("unset", [None, "", "   "])
    def test_no_database_url_resolves_to_none(self, unset: str | None) -> None:
        env = {} if unset is None else {"DATABASE_URL": unset}
        assert RouterSubmissionHealthStore.resolve(env) is None

    def test_construction_rejects_a_blank_url(self) -> None:
        with pytest.raises(RouterStoreError):
            RouterSubmissionHealthStore("   ")

    def test_a_non_sqlite_scheme_is_refused_as_an_address_fault(
        self, store: RouterSubmissionHealthStore
    ) -> None:
        # An address this member cannot speak is the *member's* existing
        # address fault, not this feature's own class: the repair is to
        # point DATABASE_URL at a database this store can open, which is
        # the repair RouterStoreError already names for feature 310.
        unreachable = RouterSubmissionHealthStore("postgresql://host/nullius")
        with pytest.raises(RouterStoreError) as refusal:
            unreachable.health(now=NOW)
        assert not isinstance(refusal.value, RouterSubmissionHealthError)
        assert "postgresql" in str(refusal.value)


class TestProcessIdentity:
    def test_identity_is_host_over_pid(self) -> None:
        identity = process_identity()
        assert identity == f"{socket.gethostname()}/{os.getpid()}"

    def test_identity_is_stable_within_a_process(self) -> None:
        assert process_identity() == process_identity()

    def test_the_store_files_rows_under_this_process(self, store) -> None:
        assert store.process_id == process_identity()
        assert store.record(outcome=ORDER_SUBMISSION_ACCEPTED).process_id == (
            process_identity()
        )

    def test_a_records_identity_can_be_named_explicitly(self, store) -> None:
        # The one caller that does this is a replay of a recorded session or
        # an operator repairing a mislabelled row, so it has to say so.
        observation = store.record(
            outcome=ORDER_SUBMISSION_ACCEPTED, process_id="other-host/7"
        )
        assert observation.process_id == "other-host/7"
        assert store.latest_for_process("other-host/7") == observation

    # ``None`` is deliberately absent from this list: it is not a name that
    # names nothing, it is the *absence* of an argument, and it means "the
    # process asking" — see test_the_store_files_rows_under_this_process.
    @pytest.mark.parametrize("bad", ["", "   ", 7])
    def test_an_identity_that_names_nothing_is_refused(self, store, bad) -> None:
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            store.record(outcome=ORDER_SUBMISSION_ACCEPTED, process_id=bad)
        assert str(refusal.value).startswith(ORDER_SUBMISSION_UNHEALTHY_CODE)


class TestRecord:
    def test_records_an_attempt_with_every_attribution(self, store) -> None:
        observation = store.record(
            outcome=ORDER_SUBMISSION_REJECTED,
            observed_at=NOW,
            symbol="BTCUSDT",
            client_order_id="book-1-1758715200-BTCUSDT",
        )
        assert isinstance(observation, SubmissionObservation)
        assert observation.outcome == ORDER_SUBMISSION_REJECTED
        assert observation.rejected is True
        assert observation.observed_at == NOW
        assert observation.symbol == "BTCUSDT"
        assert observation.client_order_id == "book-1-1758715200-BTCUSDT"

    def test_observed_at_defaults_to_now(self, store) -> None:
        before = datetime.now(UTC)
        observation = store.record(outcome=ORDER_SUBMISSION_ACCEPTED)
        assert before <= observation.observed_at <= datetime.now(UTC)

    def test_an_accepted_attempt_is_not_rejected(self, store) -> None:
        assert store.record(outcome=ORDER_SUBMISSION_ACCEPTED).rejected is False

    def test_the_optional_columns_default_to_none(self, store) -> None:
        observation = store.record(outcome=ORDER_SUBMISSION_ACCEPTED)
        assert observation.symbol is None
        assert observation.client_order_id is None

    @pytest.mark.parametrize("bad", ["maybe", "Accepted", "", 7, None, ["accepted"]])
    def test_an_outcome_outside_the_vocabulary_is_refused(self, store, bad) -> None:
        # The list case pins a real trap: a ``frozenset`` membership test on
        # an unhashable argument raises TypeError, so the check is against
        # the *string* the value would have to be -- and this package's
        # refusal names the value rather than crashing in a set lookup.
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            store.record(outcome=bad, observed_at=NOW)
        assert str(refusal.value).startswith(ORDER_SUBMISSION_UNHEALTHY_CODE)
        # ...and nothing was written: a refused attempt consumes no row.
        assert store.health(now=NOW).total == 0

    def test_a_naive_timestamp_is_refused(self, store) -> None:
        # A naive moment cannot say unambiguously when an attempt happened, so
        # a window built from it would order two processes' attempts by an
        # accident of the reader's own timezone.
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            store.record(
                outcome=ORDER_SUBMISSION_ACCEPTED,
                observed_at=datetime(2026, 9, 24, 12, 0, 0),  # noqa: DTZ001
            )
        assert str(refusal.value).startswith(ORDER_SUBMISSION_UNHEALTHY_CODE)

    def test_a_non_datetime_timestamp_is_refused(self, store) -> None:
        with pytest.raises(RouterSubmissionHealthError):
            store.record(outcome=ORDER_SUBMISSION_ACCEPTED, observed_at="12:00")

    def test_every_attempt_lands_and_none_is_amended(self, store) -> None:
        _record(store, [ORDER_SUBMISSION_ACCEPTED, ORDER_SUBMISSION_REJECTED])
        assert len(store.observations(since=NOW - WINDOW, until=NOW)) == 2


class TestHealthVerdict:
    def test_an_empty_window_is_unmeasured_not_healthy(self, store) -> None:
        # The three-valued reading, and the distinction the feature turns on:
        # a router that has not yet attempted an order is not a router whose
        # orders are failing, and reading the silence as False would page on
        # every quiet window.
        health = store.health(now=NOW)
        assert health.unhealthy is None
        assert health.measured is False
        assert health.rejection_ratio is None
        assert health.total == 0
        assert health.accepted == 0
        assert health.processes == ()

    def test_all_accepted_reads_healthy(self, store) -> None:
        _record(store, [ORDER_SUBMISSION_ACCEPTED] * 4)
        health = store.health(now=NOW)
        assert health.unhealthy is False
        assert health.measured is True
        assert health.rejection_ratio == Fraction(0, 1)

    def test_all_rejected_reads_unhealthy(self, store) -> None:
        _record(store, [ORDER_SUBMISSION_REJECTED] * 4)
        health = store.health(now=NOW)
        assert health.unhealthy is True
        assert health.rejection_ratio == Fraction(1, 1)

    def test_the_bar_is_inclusive(self, store) -> None:
        # Exactly at the bar reads unhealthy: the comparison is >=, and it is
        # exact because the ratio is a Fraction rather than a float.
        _record(store, [ORDER_SUBMISSION_REJECTED, ORDER_SUBMISSION_ACCEPTED])
        health = store.health(now=NOW)
        assert health.rejection_ratio == SUBMISSION_HEALTH_FAILURE_RATIO
        assert health.unhealthy is True

    def test_just_below_the_bar_reads_healthy(self, store) -> None:
        _record(store, [ORDER_SUBMISSION_REJECTED] + [ORDER_SUBMISSION_ACCEPTED] * 2)
        health = store.health(now=NOW)
        assert health.rejection_ratio == Fraction(1, 3)
        assert health.unhealthy is False

    def test_counts_and_the_ratio_agree(self, store) -> None:
        _record(store, [ORDER_SUBMISSION_REJECTED] * 3 + [ORDER_SUBMISSION_ACCEPTED])
        health = store.health(now=NOW)
        assert (health.total, health.rejected, health.accepted) == (4, 3, 1)
        assert health.rejection_ratio == Fraction(3, 4)

    def test_the_ratio_is_exact_for_a_dyadic_split(self, store) -> None:
        # 1/2 and 3/4 are exact in binary, so this pins that the reading is a
        # Fraction rather than a rounded float that a thin window could tip.
        _record(store, [ORDER_SUBMISSION_REJECTED, ORDER_SUBMISSION_ACCEPTED])
        assert store.health(now=NOW).rejection_ratio == Fraction(1, 2)


class TestHealthWindow:
    def test_the_window_is_inclusive_at_both_bounds(self, store) -> None:
        _record(store, ORDER_SUBMISSION_ACCEPTED, at=NOW - WINDOW)
        _record(store, ORDER_SUBMISSION_ACCEPTED, at=NOW)
        assert store.health(now=NOW, window=WINDOW).total == 2

    def test_an_attempt_older_than_the_window_is_not_counted(self, store) -> None:
        _record(store, ORDER_SUBMISSION_REJECTED, at=NOW - WINDOW - timedelta(seconds=1))
        _record(store, ORDER_SUBMISSION_ACCEPTED, at=NOW)
        health = store.health(now=NOW, window=WINDOW)
        assert health.total == 1
        assert health.unhealthy is False

    def test_an_attempt_after_now_is_not_counted(self, store) -> None:
        # A window ends at the reading: rows a peer wrote ahead of this
        # process's clock are not this reading's business, which is why the
        # upper bound is carried rather than left open.
        _record(store, ORDER_SUBMISSION_REJECTED, at=NOW + timedelta(seconds=1))
        assert store.health(now=NOW, window=WINDOW).total == 0

    def test_the_record_carries_the_window_it_covered(self, store) -> None:
        health = store.health(now=NOW, window=timedelta(minutes=2))
        assert health.since == NOW - timedelta(minutes=2)
        assert health.until == NOW

    def test_a_negative_window_is_refused_rather_than_read_as_empty(
        self, store
    ) -> None:
        # The empty window already means something here (unmeasured), so
        # overloading it with a caller's arithmetic slip would turn a
        # misconfigured sweep into a silent one.
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            store.health(now=NOW, window=timedelta(minutes=-1))
        assert str(refusal.value).startswith(ORDER_SUBMISSION_UNHEALTHY_CODE)

    def test_a_zero_window_is_refused(self, store) -> None:
        with pytest.raises(RouterSubmissionHealthError):
            store.health(now=NOW, window=timedelta(0))

    def test_a_non_timedelta_window_is_refused(self, store) -> None:
        with pytest.raises(RouterSubmissionHealthError):
            store.health(now=NOW, window=300)

    def test_an_inverted_explicit_window_is_refused(self, store) -> None:
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            store.observations(since=NOW, until=NOW - WINDOW)
        assert str(refusal.value).startswith(ORDER_SUBMISSION_UNHEALTHY_CODE)

    def test_the_default_window_is_the_named_constant(self, store) -> None:
        assert store.health(now=NOW).since == NOW - SUBMISSION_HEALTH_WINDOW


class TestPerProcessReads:
    def test_a_narrowed_read_sees_only_that_process(self, store) -> None:
        store.record(
            outcome=ORDER_SUBMISSION_REJECTED, observed_at=NOW, process_id="a/1"
        )
        store.record(
            outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW, process_id="b/2"
        )
        assert store.health(now=NOW, process_id="a/1").unhealthy is True
        assert store.health(now=NOW, process_id="b/2").unhealthy is False

    def test_the_default_read_spans_every_process(self, store) -> None:
        # The deployment's reading, and the reason the log lives in the
        # database: one process's clean window must not hide another's.
        store.record(
            outcome=ORDER_SUBMISSION_REJECTED, observed_at=NOW, process_id="a/1"
        )
        store.record(
            outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW, process_id="b/2"
        )
        health = store.health(now=NOW)
        assert health.process_id is None
        assert health.processes == ("a/1", "b/2")
        assert health.total == 2
        assert health.unhealthy is True

    def test_a_restart_is_visible_as_a_new_identity(self, store) -> None:
        # A router that restarted has a new pid, so its window carries two
        # identities and an operator can see the restart without leaving the
        # record -- which is why the identity is read from the kernel rather
        # than configured.
        _record(store, ORDER_SUBMISSION_ACCEPTED, process_id="host/41")
        _record(store, ORDER_SUBMISSION_ACCEPTED, process_id="host/42")
        assert store.health(now=NOW).processes == ("host/41", "host/42")

    def test_a_narrowed_read_names_the_process_it_read(self, store) -> None:
        store.record(
            outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW, process_id="a/1"
        )
        assert store.health(now=NOW, process_id="a/1").process_id == "a/1"

    def test_a_blank_narrowing_is_refused(self, store) -> None:
        with pytest.raises(RouterSubmissionHealthError):
            store.health(now=NOW, process_id="  ")


class TestLatestForProcess:
    def test_the_latest_attempt_comes_back(self, store) -> None:
        _record(
            store,
            [ORDER_SUBMISSION_ACCEPTED, ORDER_SUBMISSION_REJECTED],
            spacing=timedelta(seconds=1),
        )
        latest = store.latest_for_process()
        assert latest is not None
        assert latest.outcome == ORDER_SUBMISSION_REJECTED
        assert latest.observed_at == NOW + timedelta(seconds=1)

    def test_same_instant_attempts_are_ordered_by_insertion(self, store) -> None:
        # A router draining a rebalance submits several orders inside one
        # microsecond, so ordering by the stored moment alone would answer
        # "the most recent" with whichever the storage engine happened to
        # reach first.  The insertion order is the order the attempts were
        # taken in, and that is what latest_for_process must answer.
        _record(store, [ORDER_SUBMISSION_ACCEPTED, ORDER_SUBMISSION_REJECTED])
        assert store.record(outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW)
        latest = store.latest_for_process()
        assert latest is not None
        assert latest.outcome == ORDER_SUBMISSION_ACCEPTED
        # ...and the window reads in the same order.
        assert [one.outcome for one in store.observations(since=NOW, until=NOW)] == [
            ORDER_SUBMISSION_ACCEPTED,
            ORDER_SUBMISSION_REJECTED,
            ORDER_SUBMISSION_ACCEPTED,
        ]

    def test_none_for_a_process_that_never_submitted(self, store) -> None:
        # A router that has never submitted is a different fact from one
        # whose last submission was rejected, so this is None and not a
        # zeroed observation.
        assert store.latest_for_process() is None
        assert store.latest_for_process("host/999") is None


class TestRowsFromOutsideTheStore:
    def test_an_unrecognised_stored_outcome_is_refused_by_name(self, store) -> None:
        # SQLite columns are dynamically typed, so an operator at a sqlite3
        # prompt can land anything in the outcome column.  Counting an
        # unrecognised token as accepted would understate the rejection rate
        # -- the direction that lets a failing router look well -- so the row
        # is refused, naming the process and the moment it came from.
        path = Path(store.database_url.removeprefix("sqlite:///"))
        assert store.health(now=NOW).total == 0  # create the schema
        with closing(sqlite3.connect(path)) as connection, connection:
            # CHECK is bypassed on purpose: this stands in for a database
            # file that predates the constraint, or one written by a tool
            # that does not honour it.  The read is the last line of defence.
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                f"INSERT INTO {ORDER_SUBMISSION_HEALTH_TABLE} "
                "(observed_at, process_id, outcome) VALUES (?, ?, ?)",
                (NOW.isoformat(), "hand/7", "cancelled"),
            )
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            store.health(now=NOW)
        message = str(refusal.value)
        assert message.startswith(ORDER_SUBMISSION_UNHEALTHY_CODE)
        assert "hand/7" in message

    def test_the_table_refuses_a_third_outcome_at_the_schema(self, store) -> None:
        # The CHECK is built from the same frozenset the value layer uses, so
        # the table and the vocabulary cannot drift into disagreement.
        path = Path(store.database_url.removeprefix("sqlite:///"))
        assert store.health(now=NOW).total == 0  # create the schema
        with (
            closing(sqlite3.connect(path)) as connection,
            connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                f"INSERT INTO {ORDER_SUBMISSION_HEALTH_TABLE} "
                "(observed_at, process_id, outcome) VALUES (?, ?, ?)",
                (NOW.isoformat(), "hand/7", "cancelled"),
            )

    def test_an_unparseable_stored_moment_is_refused(self, store) -> None:
        # The reachable case, and the reason the read parses at all: a moment
        # that *sorts* inside the window -- so the window's string comparison
        # hands it back -- but that is not ISO 8601 any parser will accept.
        # (A moment that sorts outside the window is not this read's
        # business: the window is a filter, and a row outside it is not
        # counted into any verdict, which is the safety property that
        # matters.  See the module's _observation_from_row.)
        unparseable = "2026-09-24T12:00:00+25:00"  # an offset no clock has
        assert _iso(NOW - WINDOW) < unparseable < _iso(NOW + WINDOW)
        path = Path(store.database_url.removeprefix("sqlite:///"))
        assert store.health(now=NOW).total == 0
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                f"INSERT INTO {ORDER_SUBMISSION_HEALTH_TABLE} "
                "(observed_at, process_id, outcome) VALUES (?, ?, ?)",
                (unparseable, "hand/7", ORDER_SUBMISSION_ACCEPTED),
            )
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            store.observations(since=NOW - WINDOW, until=NOW + WINDOW)
        assert unparseable in str(refusal.value)
        assert "hand/7" in str(refusal.value)


class TestStoreFailures:
    """Every operation that reaches the driver translates its failure.

    A raw :class:`sqlite3.Error` escaping this member would be a caller
    catching :class:`RouterStoreError` for a failed persist and missing it,
    so the translation is a contract rather than a courtesy — the same
    discipline feature 310's store holds on its own side.
    """

    @pytest.fixture
    def broken(self, tmp_path: Path) -> RouterSubmissionHealthStore:
        # A *directory* where the database file should be: the connect
        # itself fails, which is the most ordinary way a configured store
        # stops working (a lost volume, a permissions change, a full disk).
        directory = tmp_path / "not-a-database"
        directory.mkdir()
        return RouterSubmissionHealthStore(f"sqlite:///{directory}")

    def test_a_failed_write_is_a_store_error_naming_the_attempt(
        self, broken: RouterSubmissionHealthStore
    ) -> None:
        with pytest.raises(RouterStoreError) as refusal:
            broken.record(outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW)
        message = str(refusal.value)
        assert broken.process_id in message
        assert _iso(NOW) in message

    def test_a_failed_read_is_a_store_error(self, broken) -> None:
        with pytest.raises(RouterStoreError):
            broken.health(now=NOW)

    def test_a_failed_latest_read_is_a_store_error(self, broken) -> None:
        with pytest.raises(RouterStoreError):
            broken.latest_for_process("host/1")

    def test_the_translated_failure_is_not_this_features_own_class(
        self, broken: RouterSubmissionHealthStore
    ) -> None:
        # A store that could not be reached is an *address* fault with an
        # address repair, which is the member's existing vocabulary for it.
        with pytest.raises(RouterStoreError) as refusal:
            broken.record(outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW)
        assert not isinstance(refusal.value, RouterSubmissionHealthError)


class TestPersistenceAcrossStoreInstances:
    def test_a_second_store_over_the_same_url_reads_what_the_first_wrote(
        self, test_database_url: str
    ) -> None:
        # The feature's first claim, minimal form: the record is the row, not
        # the object.  A health flag held in the router's own memory is
        # unreadable at exactly the moment it is wanted.
        writer = RouterSubmissionHealthStore(test_database_url)
        _record(writer, [ORDER_SUBMISSION_REJECTED, ORDER_SUBMISSION_ACCEPTED])

        reader = RouterSubmissionHealthStore(test_database_url)
        health = reader.health(now=NOW)
        assert health.total == 2
        assert health.rejection_ratio == Fraction(1, 2)

    def test_the_join_columns_round_trip_and_nulls_stay_null(self, store) -> None:
        # The symbol and the client order id are carried for an operator to
        # join back to the order path's record, so they have to survive the
        # read -- and a NULL has to come back as None rather than as the
        # string "None", which would be an order id no order ever had.
        store.record(
            outcome=ORDER_SUBMISSION_REJECTED,
            observed_at=NOW,
            symbol="BTCUSDT",
            client_order_id="book-1-1758715200-BTCUSDT",
        )
        store.record(outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW)
        with_join, without_join = store.observations(since=NOW, until=NOW)
        assert with_join.symbol == "BTCUSDT"
        assert with_join.client_order_id == "book-1-1758715200-BTCUSDT"
        assert without_join.symbol is None
        assert without_join.client_order_id is None

    def test_a_blank_join_column_is_refused(self, store) -> None:
        with pytest.raises(RouterSubmissionHealthError):
            store.record(
                outcome=ORDER_SUBMISSION_ACCEPTED, observed_at=NOW, symbol="   "
            )

    def test_reading_an_untouched_database_creates_it_and_answers_unmeasured(
        self, tmp_path: Path
    ) -> None:
        database = tmp_path / "fresh.db"
        store = RouterSubmissionHealthStore(f"sqlite:///{database}")
        health = store.health(now=NOW)
        assert isinstance(health, SubmissionHealth)
        assert health.unmeasured is True
        assert database.exists()


class TestIndependenceFromFeedHealth:
    def test_the_reading_needs_no_feed_and_no_market_data(self, store) -> None:
        # The feature's second claim, stated as a measurement: an
        # all-accepted window reads healthy with no feed state anywhere in
        # the process -- nothing here is subscribed, polled or consulted.
        _record(store, [ORDER_SUBMISSION_ACCEPTED] * 3)
        health = store.health(now=NOW)
        assert health.unhealthy is False
        assert health.measured is True

    def test_an_all_rejected_window_reads_unhealthy_with_a_perfect_feed(
        self, store
    ) -> None:
        # The other direction: a router whose every order is refused is
        # unhealthy, and no feed reading is consulted that could soften it.
        _record(store, [ORDER_SUBMISSION_REJECTED] * 3)
        assert store.health(now=NOW).unhealthy is True

    def test_the_module_never_reaches_the_ingest_members_streams(self) -> None:
        # Asserted in a subprocess, because this suite's own imports have
        # already loaded plenty.  A health reading that consulted the
        # websocket, the gap detector or a staleness clock would be exactly
        # the conflation the feature's own sentence ("independently of feed
        # health") forbids, and it would be invisible in the verdicts above.
        script = (
            "import sys; import router, router.submission_health, router._identity;"
            "assert 'nullius_ingest' not in sys.modules,"
            " 'the router imported the ingest member at module scope';"
            "print('independent')"
        )
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "router" / "src"),
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
        assert result.stdout.strip() == "independent"

    def test_a_second_process_reads_this_processes_health(
        self, tmp_path: Path
    ) -> None:
        # The real cross-process case, and the one the feature is named for:
        # a *separate interpreter* -- the operator's health sweep, the
        # supervisor watching the live host -- reads the log this process
        # wrote, and sees the identity this process filed it under.
        database = tmp_path / "cross-process.db"
        store = RouterSubmissionHealthStore(f"sqlite:///{database}")
        _record(store, [ORDER_SUBMISSION_REJECTED, ORDER_SUBMISSION_ACCEPTED])
        ours = process_identity()

        script = (
            "import sys;from datetime import datetime, UTC;"
            "from router.submission_health import RouterSubmissionHealthStore;"
            "store = RouterSubmissionHealthStore(sys.argv[1]);"
            "health = store.health("
            "now=datetime(2026, 9, 24, 12, 0, tzinfo=UTC), process_id=sys.argv[2]);"
            "latest = store.latest_for_process(sys.argv[2]);"
            "print(health.total, health.rejected, health.processes, latest.outcome)"
        )
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "router" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", script, f"sqlite:///{database}", ours],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"2 1 ('{ours}',) {ORDER_SUBMISSION_ACCEPTED}"


class TestTheValueTypesOwnShape:
    def test_more_rejections_than_attempts_is_refused(self) -> None:
        # Every property of such a record still answers a plausible wrong
        # number -- a negative accept count, a ratio above one -- so the
        # shape is refused rather than derived from.
        with pytest.raises(RouterSubmissionHealthError) as refusal:
            SubmissionHealth(
                process_id=None,
                since=NOW - WINDOW,
                until=NOW,
                total=1,
                rejected=2,
                processes=(),
            )
        assert str(refusal.value).startswith(ORDER_SUBMISSION_UNHEALTHY_CODE)

    def test_a_negative_count_is_refused(self) -> None:
        with pytest.raises(RouterSubmissionHealthError):
            SubmissionHealth(
                process_id=None,
                since=NOW - WINDOW,
                until=NOW,
                total=0,
                rejected=-1,
                processes=(),
            )

    def test_an_inverted_window_is_refused(self) -> None:
        with pytest.raises(RouterSubmissionHealthError):
            SubmissionHealth(
                process_id=None,
                since=NOW,
                until=NOW - WINDOW,
                total=0,
                rejected=0,
                processes=(),
            )

    def test_a_well_shaped_record_is_accepted(self) -> None:
        health = SubmissionHealth(
            process_id="host/7",
            since=NOW - WINDOW,
            until=NOW,
            total=4,
            rejected=1,
            processes=["host/7"],
        )
        assert health.accepted == 3
        assert health.rejection_ratio == Fraction(1, 4)
        assert health.unhealthy is False
        assert health.processes == ("host/7",)

    def test_empty_window_faces_agree(self) -> None:
        health = SubmissionHealth(
            process_id=None, since=NOW - WINDOW, until=NOW, total=0, rejected=0,
            processes=(),
        )
        assert health.unmeasured is True
        assert health.measured is False
        assert health.unhealthy is None
        assert health.rejection_ratio is None


class TestErrorVocabulary:
    def test_the_health_error_is_a_sibling_not_a_child(self) -> None:
        # A caller catching the document fault or the stored-record fault
        # must not be told a health refusal is one of them: the nouns differ,
        # so the repairs differ.
        assert issubclass(RouterSubmissionHealthError, RouterError)
        assert not issubclass(RouterSubmissionHealthError, RouterFilterError)
        assert not issubclass(RouterSubmissionHealthError, RouterStoreError)

    def test_the_code_is_the_shared_constant(self) -> None:
        assert ORDER_SUBMISSION_UNHEALTHY_CODE == "order_submission_unhealthy"
        assert not ORDER_SUBMISSION_UNHEALTHY_CODE.startswith("feed")

    def test_the_vocabulary_is_exactly_the_two_outcomes(self) -> None:
        assert ORDER_SUBMISSION_OUTCOMES == frozenset(
            {ORDER_SUBMISSION_ACCEPTED, ORDER_SUBMISSION_REJECTED}
        )
        assert ORDER_SUBMISSION_ACCEPTED != ORDER_SUBMISSION_REJECTED

    def test_the_member_exports_the_feature_320_names(self) -> None:
        import router as member

        for name in (
            "ORDER_SUBMISSION_ACCEPTED",
            "ORDER_SUBMISSION_HEALTH_TABLE",
            "ORDER_SUBMISSION_OUTCOMES",
            "ORDER_SUBMISSION_REJECTED",
            "ORDER_SUBMISSION_UNHEALTHY_CODE",
            "SUBMISSION_HEALTH_FAILURE_RATIO",
            "SUBMISSION_HEALTH_WINDOW",
            "RouterSubmissionHealthError",
            "RouterSubmissionHealthStore",
            "SubmissionHealth",
            "SubmissionObservation",
            "process_identity",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_health_store_is_not_a_second_component(self) -> None:
        # A composed application can answer only for the process that
        # composed it -- the one process whose health is in question -- so
        # the health store is resolved from DATABASE_URL, never registered.
        import router as member

        assert member.COMPONENT_NAME == "router"
        assert [
            name for name in dir(member) if name.startswith("build_")
        ] == ["build_router_exchange_info_store"]
