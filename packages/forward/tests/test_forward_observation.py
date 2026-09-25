"""Feature 333's act: the live IC observations behind a standing record.

app_spec.xml, "Forward-Test Tracking", feature 333: *System persists one
forward_record per promoted signal carrying live information coefficient
observations over time.*  These tests pin the four halves of that sentence:

* **one forward_record per observation date** — a second append for a day the
  table already holds is a retry answered by the standing row, never a second
  row and never a revision;
* **carrying the live information coefficient** — the appended row carries
  the figure measured, validated as the correlation it claims to be, with
  ``backtest_ic`` and ``realized_cost_bps`` left NULL because naming them is
  feature 337's and feature 340's act;
* **over time** — observations accumulate one row per day, arrive in any
  order, and read back chronologically; the first honest day is the one
  after the record's boundary, and the boundary day itself is refused;
* **per promoted signal** — the observation joins the record 332 opened: the
  ``promoted_at`` it carries is asserted against the registry row feature
  293 stamped (through the raw table, not through anything this member
  computed), a signal with no record is refused naming the promote step, and
  a record whose rows carry two instants is refused rather than extended.
"""

from __future__ import annotations

import datetime as dt
import inspect
import uuid

import forward.observation
import pytest
from conftest import DECIDED_AT, NODE_ID, code_of
from forward import (
    DATABASE_URL_ENV,
    ForwardIdentityError,
    ForwardObservations,
    ForwardRecord,
    ForwardRecordError,
    ForwardStoreError,
    forward_observation,
)
from forward.observation import _OBSERVATION_INSERT_SQL
from forward.record import _sqlite_path

DECIDED = dt.datetime.fromisoformat(DECIDED_AT)

#: The record's boundary day — the promotion instant's own UTC date, spelled
#: as a literal beside the derived value so the two cannot drift apart
#: silently, and so a conftest change that moved :data:`DECIDED_AT` fails
#: here rather than quietly moving every date below with it.
BOUNDARY_DAY = dt.date(2026, 3, 1)

#: The first day an observation may honestly name: the day after the boundary.
FIRST_DAY = dt.date(2026, 3, 2)


@pytest.fixture
def observations(
    opened_record: ForwardRecord, promoted_signal
) -> ForwardObservations:
    """The observation writer over the record's own store — 333's seam.

    Built with :meth:`ForwardObservations.over` off the very store the record
    was opened through, so the writer and the opener point at one database by
    construction — the shape a deployment reaches when it asks the composed
    ``forward`` component for the act.  ``opened_record`` is asked for so the
    record exists before any append, and its boundary is asserted here so a
    conftest change that moved :data:`DECIDED_AT` without moving this file's
    dates fails at the fixture rather than at some refusal deep inside a test.
    """
    assert opened_record.promoted_at == DECIDED
    assert opened_record.observed_on == BOUNDARY_DAY
    return ForwardObservations.over(promoted_signal)


# -- The feature's sentence ---------------------------------------------------


def test_the_observation_lands_as_its_own_row(
    observations: ForwardObservations, forward_rows
) -> None:
    # 0108's shape: one row per promoted signal *per observation date*.  The
    # appended row is a new row — the record 332 opened is not updated and
    # not annotated in place, because the table's whole value is that each
    # day's measurement is its own row with its own minted identity.
    record, created = observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.12
    )
    assert created is True
    rows = forward_rows()
    assert len(rows) == 2
    opening, appended = rows
    assert appended["node_id"] == NODE_ID
    assert appended["observed_on"] == "2026-03-02"
    assert appended["live_ic"] == 0.12
    assert appended["id"] and appended["id"] != opening["id"]
    # And the answer is the row, read back inside the write's transaction.
    assert record.observed_on == FIRST_DAY
    assert record.live_ic == 0.12
    assert record.id == appended["id"]


def test_the_appended_row_carries_the_instant_the_registry_stamped(
    observations: ForwardObservations, promotion_rows, forward_rows
) -> None:
    # The observation joins the record, not the promotion — which makes the
    # instant on the appended row *the registry's own stamp, read once at the
    # open and carried forward*, and that is what is asserted here: against
    # the raw ``promotion_registry.decided_at`` feature 293 wrote, not against
    # anything this member (or this suite) computed on the way past.
    record, _ = observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.12
    )
    decided = {row["node_id"]: row["decided_at"] for row in promotion_rows()}
    assert record.promoted_at == dt.datetime.fromisoformat(decided[NODE_ID])
    assert record.promoted_at == DECIDED
    assert forward_rows()[1]["promoted_at"] == DECIDED_AT


def test_the_two_columns_this_feature_does_not_own_stay_null(
    observations: ForwardObservations, forward_rows
) -> None:
    # The insert names four columns, so the two it cannot name — feature
    # 337's ``backtest_ic`` and feature 340's ``realized_cost_bps`` — arrive
    # NULL exactly as they stood on the opening row.  A writer that guessed
    # a zero into either would be answering for a feature that has not run.
    observations.append_observation(NODE_ID, observed_on=FIRST_DAY, live_ic=0.12)
    appended = forward_rows()[1]
    assert appended["backtest_ic"] is None
    assert appended["realized_cost_bps"] is None


def test_an_appended_row_reports_itself_observed(
    observations: ForwardObservations, opened_record: ForwardRecord
) -> None:
    # The readable name for the state 0108's comment describes: the opening
    # row has measured nothing, the observation row has.
    record, _ = observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=-0.25
    )
    assert record.observed is True
    assert opened_record.observed is False


def test_the_identity_is_canonicalized_on_the_way_in(
    observations: ForwardObservations, forward_rows
) -> None:
    # A :class:`uuid.UUID` in hand is accepted and stored in the table's one
    # spelling, so the appended row joins the opening row's node exactly.
    record, _ = observations.append_observation(
        uuid.UUID(NODE_ID), observed_on=FIRST_DAY, live_ic=0.12
    )
    assert record.node_id == NODE_ID
    assert forward_rows()[1]["node_id"] == NODE_ID


# -- Over time ----------------------------------------------------------------


def test_observations_accumulate_whatever_order_they_arrive_in(
    observations: ForwardObservations, promoted_signal, forward_rows
) -> None:
    # §5's sentence is a measurement *over time*, and a missed day measured
    # later is still a measurement of that day's data — so out-of-order
    # arrival is served, not refused.  The raw table shows the arrival order
    # (rowid order: 03-02, then 03-05, then 03-03), and the member's own read
    # orders them chronologically, which is what keeps feature 334's curve
    # and feature 337's ratio reading one record however it was written.
    observations.append_observation(NODE_ID, observed_on=FIRST_DAY, live_ic=0.12)
    observations.append_observation(
        NODE_ID, observed_on=dt.date(2026, 3, 5), live_ic=0.40
    )
    observations.append_observation(
        NODE_ID, observed_on=dt.date(2026, 3, 3), live_ic=-0.05
    )
    assert [row["observed_on"] for row in forward_rows()] == [
        "2026-03-01",
        "2026-03-02",
        "2026-03-05",
        "2026-03-03",
    ]
    connection = promoted_signal._connect()
    try:
        ordered = promoted_signal._node_records(connection, NODE_ID)
    finally:
        connection.close()
    assert [row.observed_on for row in ordered] == [
        dt.date(2026, 3, 1),
        dt.date(2026, 3, 2),
        dt.date(2026, 3, 3),
        dt.date(2026, 3, 5),
    ]
    assert [row.live_ic for row in ordered] == [None, 0.12, -0.05, 0.40]


# -- One row per date ---------------------------------------------------------


def test_a_retry_is_answered_by_the_standing_observation(
    observations: ForwardObservations, forward_rows
) -> None:
    # The observation job ran twice, or the worker died after the row landed
    # and the one that takes over measures again.  Nothing moves: the day's
    # measurement already exists, and the answer is the standing row with
    # ``created=False`` — the same semantics the opening write gives a
    # retried promote.
    first, created = observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.12
    )
    second, again = observations.append_observation(
        NODE_ID, observed_on="2026-03-02", live_ic=0.12
    )
    assert created is True and again is False
    assert second == first
    assert second.id == first.id
    assert len(forward_rows()) == 2


def test_a_whole_number_coefficient_and_its_float_are_one_observation(
    observations: ForwardObservations,
) -> None:
    # The coefficient is narrowed to float before the retry comparison, so an
    # ``int`` measurement and the same figure re-sent as a float are the same
    # observation rather than a disagreement — the reason the narrowing lives
    # in the validator rather than at the comparison.
    first, created = observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0
    )
    assert created is True
    assert first.live_ic == 0.0
    second, again = observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.0
    )
    assert again is False
    assert second == first


def test_a_second_coefficient_for_a_measured_day_is_refused(
    observations: ForwardObservations, forward_rows
) -> None:
    # Two measurements claiming one day.  Last-wins would revise a fact
    # feature 334's curve and feature 337's ratio may already have read — the
    # track record editing itself — so the store refuses to choose, naming
    # both figures and leaving the row exactly as it stands.
    observations.append_observation(NODE_ID, observed_on=FIRST_DAY, live_ic=0.12)
    with pytest.raises(ForwardIdentityError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=FIRST_DAY, live_ic=0.4
        )
    message = str(raised.value)
    assert "forward_record_already_open" in message
    assert "0.12" in message and "0.4" in message
    assert len(forward_rows()) == 2


# -- The boundary -------------------------------------------------------------


def test_the_boundary_day_is_the_opening_rows_own(
    observations: ForwardObservations, forward_rows
) -> None:
    # Day zero is refused: the record landed on it carrying no measurement
    # (0108's comment protects that NULL), and a "live IC" measured over a
    # span that began at the instant the deciding evaluation itself ran
    # would be an observation wearing a vintage it does not have.
    with pytest.raises(ForwardIdentityError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=BOUNDARY_DAY, live_ic=0.12
        )
    message = str(raised.value)
    assert "forward_record_already_open" in message
    assert "2026-03-01" in message
    assert len(forward_rows()) == 1


def test_a_day_before_the_boundary_is_refused(
    observations: ForwardObservations, forward_rows
) -> None:
    # The contamination case the table exists to exclude: data that existed
    # when the hypothesis was formed, wearing the vintage of data that did
    # not.  Refused as the same disagreement — the record has already fixed
    # when its signal went out of sample.
    with pytest.raises(ForwardIdentityError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=dt.date(2026, 2, 20), live_ic=0.12
        )
    assert "forward_record_already_open" in str(raised.value)
    assert len(forward_rows()) == 1


def test_a_datetime_is_refused_where_a_date_belongs(
    observations: ForwardObservations, forward_rows
) -> None:
    # ``datetime`` is a subclass of ``date``, so an isinstance-only check
    # would truncate the instant silently — and truncating an instant to a
    # day is a choice about which offset the day is read in.
    with pytest.raises(ForwardRecordError) as raised:
        observations.append_observation(
            NODE_ID,
            observed_on=dt.datetime(2026, 3, 2, 12, 0, tzinfo=dt.UTC),
            live_ic=0.12,
        )
    assert "datetime" in str(raised.value)
    assert len(forward_rows()) == 1


# -- The record the observation joins ------------------------------------------


def test_a_signal_with_no_record_is_refused_naming_the_repair(
    promoted_signal, forward_rows
) -> None:
    # The observation job ran ahead of the promote step: the promotion may
    # well be decided (it is, below — the registry row is closed), but the
    # record is what an observation joins, and a writer that opened one
    # silently would fabricate the boundary it failed to read.  The refusal
    # names the repair in order: open the record (feature 332), then observe.
    observations = ForwardObservations.over(promoted_signal)
    with pytest.raises(ForwardStoreError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=FIRST_DAY, live_ic=0.12
        )
    message = str(raised.value)
    assert "forward_record_unwritable" in message
    assert "/forward/promote" in message
    assert forward_rows() == []


def test_a_record_holding_two_instants_is_refused_rather_than_extended(
    observations: ForwardObservations, promoted_signal, forward_rows
) -> None:
    # Rows that disagree about ``promoted_at`` are a hand that reached past
    # the member: every row this member writes carries the one instant, so
    # the disagreement cannot have come from either of its acts.  Appending
    # onto them would compound a fault every later reader inherits, and the
    # boundary they leave is one nobody can state — the refusal names both
    # instants so the repair starts from the rows.
    observations.append_observation(NODE_ID, observed_on=FIRST_DAY, live_ic=0.12)
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET promoted_at = ? "
                "WHERE observed_on != ?",
                ("2026-03-09T09:00:00+00:00", "2026-03-01"),
            )
    finally:
        connection.close()
    with pytest.raises(ForwardStoreError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=dt.date(2026, 3, 4), live_ic=0.2
        )
    message = str(raised.value)
    assert "forward_record_unwritable" in message
    assert DECIDED_AT in message
    assert "2026-03-09T09:00:00+00:00" in message
    assert len(forward_rows()) == 2


# -- The coefficient -----------------------------------------------------------


@pytest.mark.parametrize(
    "coefficient",
    [
        True,  # a flag where a correlation belongs — True is 1
        "0.5",  # text
        None,  # absent is not zero
        float("nan"),  # a gap that would read as measured
        float("inf"),
        float("-inf"),
        1.5,  # outside [−1, 1] — a z-score wearing the field's name
        -1.5,
        0.1 + 2.0,  # 2.1, computed so no literal in the source matches it
        [0.5],  # a sequence
    ],
)
def test_a_coefficient_that_is_not_a_correlation_is_refused(
    observations: ForwardObservations, forward_rows, coefficient
) -> None:
    # An information coefficient is a correlation: bounded in [−1, 1] by
    # construction, finite, one number.  Everything else is refused rather
    # than clamped — clamping 2.5 to one would persist the *maximum*
    # coefficient for a figure that may be an honest something-else — and
    # refused before anything is opened, so the table is untouched.
    with pytest.raises(ForwardRecordError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=FIRST_DAY, live_ic=coefficient
        )
    assert "live_ic" in str(raised.value)
    assert len(forward_rows()) == 1


@pytest.mark.parametrize("coefficient", [-1.0, 0.0, 1.0, 0, -1, 1])
def test_the_bound_is_inclusive_and_integers_are_narrowed(
    observations: ForwardObservations, coefficient
) -> None:
    # Both ends of the bound are measurements — a perfect inverse
    # correlation and a perfect one — and a whole-number coefficient is
    # admitted and narrowed to the float the REAL column holds.
    record, created = observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=coefficient
    )
    assert created is True
    assert record.live_ic == float(coefficient)
    assert isinstance(record.live_ic, float)


def test_a_malformed_ask_touches_no_disk(database_url: str) -> None:
    # The ask is validated before anything is opened, so a refused
    # observation leaves no row and no *file* behind — the database the URL
    # names is never created for a call that was never going to write.
    observations = ForwardObservations(database_url)
    with pytest.raises(ForwardRecordError):
        observations.append_observation(
            NODE_ID, observed_on=FIRST_DAY, live_ic=float("nan")
        )
    assert not _sqlite_path(database_url).exists()


# -- The insert's shape ---------------------------------------------------------


def test_the_insert_names_four_columns_and_fabricates_nothing() -> None:
    # ``node_id``, ``promoted_at``, ``observed_on``, ``live_ic`` — in the
    # order the placeholders bind, and nothing else: ``id`` is the table's
    # own DEFAULT, and ``backtest_ic`` / ``realized_cost_bps`` are feature
    # 337's and feature 340's columns.  A statement that cannot name a
    # column cannot fabricate its value.
    columns = "(node_id, promoted_at, observed_on, live_ic)"
    assert _OBSERVATION_INSERT_SQL.startswith("INSERT INTO forward_record")
    assert columns in _OBSERVATION_INSERT_SQL
    assert "backtest_ic" not in _OBSERVATION_INSERT_SQL
    assert "realized_cost_bps" not in _OBSERVATION_INSERT_SQL
    assert _OBSERVATION_INSERT_SQL.count("?") == 4


def test_the_ask_has_no_default_and_takes_no_clock() -> None:
    # The day an observation belongs to is the day the measured data closed,
    # not the day the writer happened to run — so ``observed_on`` is
    # required with no default, and there is no clock parameter to derive
    # one from.  Pinned on the signature, which is where a default would
    # have to live.
    signature = inspect.signature(ForwardObservations.append_observation)
    assert list(signature.parameters) == [
        "self",
        "node_id",
        "observed_on",
        "live_ic",
    ]
    for name in ("observed_on", "live_ic"):
        parameter = signature.parameters[name]
        assert parameter.default is inspect.Parameter.empty, name
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name


def test_the_act_reads_no_promotion_and_declares_no_horizon() -> None:
    # On the module's *code*, docstrings stripped, because the docstring
    # legitimately names all three while doing none: the observation reads
    # the record's standing rows rather than the registry (no window read,
    # no ``importlib`` reach), stamps nothing (no clock), and enforces no
    # horizon (the 90-day track is feature 335's sentence, not this
    # writer's).
    text = code_of(forward.observation)
    for token in ("read_promotion_window", "utc_now", "forward_days"):
        assert token not in text, (
            f"forward.observation reaches for {token}: the observation joins "
            "the record, not the promotion"
        )


# -- The store's construction ----------------------------------------------------


def test_construction_touches_no_disk(database_url: str) -> None:
    # Composition-time work must not touch the disk: the URL is held, the
    # path is translated on demand, and neither act creates the file — the
    # first ``append_observation`` is what brings the tables to it.
    observations = ForwardObservations(database_url)
    assert observations.database_url == database_url
    assert observations.path == _sqlite_path(database_url)
    assert not observations.path.exists()


def test_resolve_answers_none_when_no_database_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured deployment is a discoverable state, not an exception —
    # the same degrade-don't-break stance the opening store's resolve takes.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert ForwardObservations.resolve() is None
    assert ForwardObservations.resolve({}) is None
    assert ForwardObservations.resolve({DATABASE_URL_ENV: "  "}) is None


def test_resolve_reads_the_url_the_deployment_names(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    resolved = ForwardObservations.resolve({DATABASE_URL_ENV: database_url})
    assert resolved is not None
    assert resolved.database_url == database_url


def test_over_reads_the_url_off_the_composed_store(store) -> None:
    # The bridge from the seat to this act: one attribute read off the
    # composed store, no ``isinstance`` to defeat, and no second database —
    # the observation writer and the record opener are two acts over one
    # URL.
    observations = ForwardObservations.over(store)
    assert observations.database_url == store.database_url


@pytest.mark.parametrize("not_a_store", [object(), None, 42, ForwardRecord])
def test_over_refuses_something_that_names_no_database(not_a_store) -> None:
    with pytest.raises(TypeError) as raised:
        ForwardObservations.over(not_a_store)
    assert "database_url" in str(raised.value)


def test_over_refuses_a_store_whose_url_is_blank() -> None:
    blank = type("BlankStore", (), {"database_url": "  "})()
    with pytest.raises(TypeError) as raised:
        ForwardObservations.over(blank)
    assert "database_url" in str(raised.value)


# -- The module-level spelling ----------------------------------------------------


def test_the_module_level_spelling_lands_the_row(
    opened_record, promoted_signal, forward_rows
) -> None:
    # The feature's sentence as one call, for the observation job that holds
    # a URL and no store: the row lands, and the answer is the record the
    # table holds rather than a ``(record, created)`` pair.
    record = forward_observation(
        NODE_ID,
        observed_on=FIRST_DAY,
        live_ic=0.12,
        database_url=promoted_signal.database_url,
    )
    assert isinstance(record, ForwardRecord)
    assert record.observed_on == FIRST_DAY
    assert record.live_ic == 0.12
    assert record.promoted_at == opened_record.promoted_at
    assert len(forward_rows()) == 2


def test_the_module_level_spelling_reads_the_environment(
    promoted_signal, opened_record, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    record = forward_observation(
        NODE_ID,
        observed_on="2026-03-02",
        live_ic=-0.25,
        env={DATABASE_URL_ENV: promoted_signal.database_url},
    )
    assert record.live_ic == -0.25
    assert record.promoted_at == DECIDED


def test_an_unnamed_database_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Not a silent answer of the caller's own choosing: a measurement that
    # went nowhere is a day of the track record that never landed, and §5's
    # 90-day figure cannot be re-read off a calendar that does not hold it.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(ForwardStoreError) as raised:
        forward_observation(
            NODE_ID, observed_on=FIRST_DAY, live_ic=0.12, env={}
        )
    assert DATABASE_URL_ENV in str(raised.value)
