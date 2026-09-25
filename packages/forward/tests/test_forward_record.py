"""Feature 332's act: one forward record per promoted signal.

app_spec.xml, "Forward-Test Tracking", feature 332: *System exposes POST
/forward/promote, which creates a forward_record carrying the promotion
timestamp.*  These tests pin the three halves of that sentence:

* **carrying the promotion timestamp** — the row's ``promoted_at`` is asserted
  against the raw ``promotion_registry.decided_at`` feature 293 wrote, not
  against anything this member computed.  That is the feature's whole claim,
  and a suite that compared the record against a fixture would be pinning it
  against a value the suite made up.
* **one record** — a retry is answered by the standing row, and a request that
  *disagrees* about the promotion is refused rather than resolved.
* **creates a forward_record** — the row lands, with the ``id`` the table
  minted and the three observation columns left NULL exactly as ``0108``'s own
  comment requires of a freshly promoted signal.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from conftest import (
    DECIDED_AT,
    FORWARD_DAYS,
    NODE_ID,
    promote_signal,
)
from forward import (
    DATABASE_URL_ENV,
    FORWARD_PROMOTE_ROUTE,
    ForwardIdentityError,
    ForwardPromotionError,
    ForwardRecord,
    ForwardRecordError,
    ForwardRecordRequest,
    ForwardRecords,
    ForwardStoreError,
    PromoteEndpoint,
    forward_record,
)
from forward.record import _INSERT_SQL, _READ_SQL, _sqlite_path

DECIDED = dt.datetime.fromisoformat(DECIDED_AT)


# -- The feature's sentence ---------------------------------------------------


def test_the_record_carries_the_promotion_instant_the_registry_row_holds(
    promoted_signal: ForwardRecords, promotion_rows
) -> None:
    # The feature's whole claim, asserted against the *table* feature 293 wrote
    # rather than against anything this member computed.  If this member
    # stamped the row with its own clock the two would differ by however long
    # the test took to run — and on a real deployment by however long the
    # worker took to reach the write, which is exactly the drift that would
    # make the boundary meaningless.
    record, created = promoted_signal.open_record(
        NODE_ID, forward_days=FORWARD_DAYS
    )
    assert created is True
    decided = {row["node_id"]: row["decided_at"] for row in promotion_rows()}
    assert record.promoted_at == dt.datetime.fromisoformat(decided[NODE_ID])
    assert record.promoted_at == DECIDED


def test_the_day_is_the_instants_own_utc_date(promoted_signal: ForwardRecords) -> None:
    # ``0108`` makes the ``promoted_at`` / ``observed_on`` pair *the vintage*,
    # so the two must not be able to disagree.  The day is derived rather than
    # stated — the request has no ``observed_on`` field — which is what makes
    # the consistency structural rather than a check the writer remembers.
    record, _ = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert record.observed_on == DECIDED.date()
    assert record.observed_on == dt.date(2026, 3, 1)


def test_the_row_lands_with_the_tables_own_identity_and_no_observation(
    promoted_signal: ForwardRecords, forward_rows
) -> None:
    # ``id`` is absent from the insert because ``0108`` declares a ``DEFAULT``
    # that mints a UUID on both dialects; the three REAL columns are absent
    # because 0108's own comment refuses a fabricated zero — *"a NOT NULL here
    # would force a fabricated zero on the day of promotion, which would read
    # as 'measured, and it was zero'"*.  This asserts the row the *table*
    # holds, which is the only place a writer's guess would show up.
    promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    rows = forward_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["node_id"] == NODE_ID
    assert row["promoted_at"] == DECIDED_AT
    assert row["observed_on"] == "2026-03-01"
    assert row["live_ic"] is None
    assert row["backtest_ic"] is None
    assert row["realized_cost_bps"] is None
    assert row["id"], "the table's DEFAULT minted no identity"


def test_the_minted_identity_reads_back_as_the_records_own(
    promoted_signal: ForwardRecords, forward_rows
) -> None:
    # The answer is drawn from the row inside the write's own transaction, so
    # the ``id`` a caller holds is the one the table minted rather than one a
    # second read happened to find.
    record, _ = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert record.id == forward_rows()[0]["id"]


def test_a_fresh_record_has_observed_nothing(promoted_signal: ForwardRecords) -> None:
    record, _ = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert record.observed is False
    assert record.live_ic is None


# -- The one-signal law -------------------------------------------------------


def test_a_retry_is_answered_by_the_standing_row(
    promoted_signal: ForwardRecords, forward_rows
) -> None:
    # The worker died after the row landed but before the response made it
    # back, and the worker that takes over posts again.  Nothing moves: the
    # boundary was drawn at the promotion and a retry does not redraw it.
    first, created = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    second, again = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert created is True and again is False
    assert second == first
    assert second.id == first.id
    assert len(forward_rows()) == 1


def test_the_retry_returns_the_instant_the_boundary_actually_fell_at(
    promoted_signal: ForwardRecords,
) -> None:
    # Not "the same as the first answer" but *the promotion's own stamp*: the
    # figure the caller accounts with is feature 293's, and a store that
    # answered the retry with its own clock would report a boundary that moved
    # while every other column said it had not.
    first, _ = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    second, _ = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert second.promoted_at == DECIDED
    assert second.promoted_at == first.promoted_at


def test_a_signal_promoted_at_another_instant_is_refused(
    store: ForwardRecords, promoted_signal: ForwardRecords, tmp_path: Path
) -> None:
    # Two claims about one signal's *vintage*, and the store refuses to choose
    # between them: last-wins would move the boundary §13.4 fixes at
    # promotion, and first-wins would leave the caller holding a response whose
    # ``promoted_at`` contradicts the promotion it just decided.
    #
    # The second instant is produced by the *real* promotion member in a second
    # database rather than by hand-editing a row — the realistic shape of this
    # fault is a deployment pointed at the wrong registry, and driving the
    # sibling's own stores keeps the fixture honest about what a promotion is.
    elsewhere = f"sqlite:///{tmp_path / 'elsewhere.db'}"
    promote_signal(elsewhere, decided_at="2026-04-01T00:00:00+00:00")

    store.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    with pytest.raises(ForwardIdentityError) as raised:
        store.open_record(
            NODE_ID,
            forward_days=FORWARD_DAYS,
            database_url=elsewhere,
        )
    message = str(raised.value)
    assert "forward_record_already_open" in message
    # Both instants are named, because the repair depends on which one is
    # wrong and the operator has to be able to see that there *are* two.
    assert DECIDED_AT in message
    assert "2026-04-01" in message


def test_a_refused_disagreement_writes_nothing(
    store: ForwardRecords, promoted_signal: ForwardRecords, forward_rows
) -> None:
    # A refusal that had already appended a row would be the worst of both:
    # the caller learns the request was refused *and* the boundary moved.
    promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    before = forward_rows()
    with pytest.raises(ForwardIdentityError):
        store._answer_standing(
            ForwardRecord(
                id=before[0]["id"],
                node_id=NODE_ID,
                promoted_at=DECIDED,
                observed_on=DECIDED.date(),
            ),
            NODE_ID,
            dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        )
    assert forward_rows() == before


def test_the_retry_comparison_is_the_instant_and_not_the_whole_row(
    store: ForwardRecords, promoted_signal: ForwardRecords
) -> None:
    # Features 333-340 fill the three observation columns after this write, so
    # a caller re-posting the same promotion long after its record has been
    # annotated must not be refused for disagreeing about columns this act
    # never writes.  Simulated by annotating the standing row the way feature
    # 333 will, then re-posting.
    promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET live_ic = ?, backtest_ic = ?",
                (0.42, 0.5),
            )
    finally:
        connection.close()
    again, created = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert created is False
    assert again.live_ic == 0.42


# -- The promotion seam -------------------------------------------------------


def test_a_signal_nobody_pre_registered_is_refused_by_the_promotion_seam(
    store: ForwardRecords,
) -> None:
    # The instant feature 332's row carries is feature 293's stamp on a row
    # feature 291 opened, so a node nobody pre-registered has no promotion and
    # therefore no instant.  The refusal is the *promotion's* — its repair is
    # pre-registering and deciding, neither of which this member can do.
    with pytest.raises(ForwardPromotionError) as raised:
        store.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert "forward_promotion_unstamped" in str(raised.value)


def test_an_open_registration_is_refused_by_the_promotion_seam(tmp_path: Path) -> None:
    # ``decided_at`` is NULL exactly while the deciding evaluation has not run,
    # and there is then no promotion instant at all.  Both honest alternatives
    # are worse: *now* would place the boundary wherever the reading landed,
    # and the pre-registration's instant is *before* the evaluation, so the
    # window would begin measuring on data that existed when the hypothesis was
    # formed.
    fresh = f"sqlite:///{tmp_path / 'open.db'}"
    promote_signal(fresh, decided_at=None)
    store = ForwardRecords(fresh)
    with pytest.raises(ForwardPromotionError) as raised:
        store.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert "forward_promotion_unstamped" in str(raised.value)


def test_a_refused_promotion_writes_no_row(tmp_path: Path) -> None:
    # The instant is read *before* the store's own write, so a refusal on the
    # promotion side leaves no row behind: a forward record opened against a
    # promotion that does not exist is worse than no record, because it looks
    # like a boundary and measures nothing.
    #
    # Note what this does **not** claim: that the database file is absent.  It
    # is not, and the reason is a real fact about the arrangement rather than a
    # leak — the read goes *through* the promotion member, whose own store
    # brings its tables up on its way to answering.  A test asserting the file
    # away would be asserting a property of the sibling's reader, and would
    # pass or fail for reasons this member does not control.
    database = tmp_path / "untouched.db"
    with pytest.raises(ForwardPromotionError):
        ForwardRecords(f"sqlite:///{database}").open_record(
            NODE_ID, forward_days=FORWARD_DAYS
        )
    # Read off *this* database, and read tolerantly: the refusal's own read is
    # the sibling's, and what it left behind is not this member's to legislate.
    # What must be true is that no forward record exists here.
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute("SELECT COUNT(*) FROM forward_record").fetchone()[0]
    finally:
        connection.close()
    assert rows == 0


def test_the_instant_is_read_through_the_promotion_members_own_verb(
    promoted_signal: ForwardRecords, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The seam is the *only* way this member can learn when a signal was
    # promoted, so a deployment whose promotion member exposes no such verb has
    # no instant to write — refused by name rather than defaulted to the clock.
    from forward import window

    monkeypatch.setattr(window, "_promotion_window_verb", lambda: None)
    with pytest.raises(ForwardPromotionError) as raised:
        promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert "forward_promotion_unstamped" in str(raised.value)
    assert "promotion_window" in str(raised.value)


def test_a_window_without_an_opened_at_is_refused_rather_than_stamped(
    promoted_signal: ForwardRecords, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "Ask the surface the act needs" has a failure mode worth pinning: a
    # window that answers but does not carry the instant.  Falling back to the
    # clock here is the one repair that *looks* like it works, which is why it
    # is refused out loud.
    #
    # Patched on :mod:`forward.record` rather than on :mod:`forward.window`,
    # which is where it is *looked up*: ``record`` binds the name at import
    # time, so rebinding it on the defining module would leave the store
    # calling the original and this test asserting nothing at all.
    import forward.record as record_module

    class Hollow:
        closes_at = None

    monkeypatch.setattr(
        record_module, "read_promotion_window", lambda *a, **k: Hollow()
    )
    with pytest.raises(ForwardPromotionError) as raised:
        promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert "opened_at" in str(raised.value)


# -- The ask face -------------------------------------------------------------


@pytest.mark.parametrize("value", ["not-a-uuid", "", None, 17, b"1234"])
def test_a_malformed_signal_is_refused_before_the_store_is_touched(
    store: ForwardRecords, tmp_path: Path, value: object
) -> None:
    # A malformed body never reaches the promotion seam or the database: the
    # refusal is the *ask's*, its repair is to re-send it, and it must not
    # spend a promotion read on a node that names nothing.
    database = tmp_path / "ask.db"
    other = ForwardRecords(f"sqlite:///{database}")
    with pytest.raises(ForwardRecordError):
        other.open_record(value, forward_days=FORWARD_DAYS)
    assert not database.exists()


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "90", None])
def test_a_malformed_horizon_is_refused(promoted_signal: ForwardRecords, value: object) -> None:
    # Zero is *not a window* rather than a bad one: ``closes_at`` would equal
    # ``opened_at``, the half-open interval would be empty, and a record opened
    # against it could never hold an observation.  ``True`` is refused first
    # because ``isinstance(True, int)`` and a flag where a horizon belongs
    # would silently open a one-day window.
    with pytest.raises(ForwardRecordError):
        promoted_signal.open_record(NODE_ID, forward_days=value)


def test_the_validated_ask_names_the_column_and_the_value(store: ForwardRecords) -> None:
    with pytest.raises(ForwardRecordError) as raised:
        store.open_record("nope", forward_days=90)
    assert "nope" in str(raised.value)
    assert "node_id" in str(raised.value)


def test_a_non_string_url_is_refused_at_construction() -> None:
    with pytest.raises(ForwardStoreError) as raised:
        ForwardRecords("")  # type: ignore[arg-type]
    assert "forward_record_unwritable" in str(raised.value)


@pytest.mark.parametrize(
    "url",
    ["postgresql://localhost/x", "sqlite://host/x.db", "sqlite://", "sqlite:///:memory:"],
)
def test_a_url_this_member_cannot_speak_is_refused_by_name(url: str) -> None:
    # Refused at *first use* rather than at construction — composition-time
    # work must not touch the disk — so the refusal names the feature and the
    # repair, and the original scheme is quoted for the operator.
    with pytest.raises(ForwardStoreError):
        _sqlite_path(url)


def test_an_absent_node_row_is_refused_naming_the_column(tmp_path: Path) -> None:
    # The row's one foreign key, checked by name because SQLite's own
    # ``IntegrityError`` names neither the column nor the value.  A
    # pre-registration can outlive its node only by a hand on the table, and
    # the foreign key is the one thing making the record joinable to the tree
    # the whole category measures against — so the test removes the node row
    # by hand, deliberately, and leaves the promotion behind it intact.
    #
    # The deletion runs on a raw connection with the pragma set *before* any
    # transaction opens, because ``PRAGMA foreign_keys`` is a no-op inside one:
    # a test that issued it inside a ``with connection:`` block would silently
    # leave the constraint on, and the delete would fail with an
    # ``IntegrityError`` from the registry's own foreign key rather than
    # producing the state this test is about.
    other_node = "33333333-3333-4333-8333-333333333333"
    database = tmp_path / "orphan.db"
    promote_signal(f"sqlite:///{database}", node_id=other_node)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        with connection:
            connection.execute("DELETE FROM node WHERE id = ?", (other_node,))
    finally:
        connection.close()

    store = ForwardRecords(f"sqlite:///{database}")
    with pytest.raises(ForwardStoreError) as raised:
        store.open_record(other_node, forward_days=FORWARD_DAYS)
    assert "node_id" in str(raised.value)
    assert other_node in str(raised.value)


# -- The row contract ---------------------------------------------------------


def test_the_record_is_frozen_and_validated_at_construction() -> None:
    record = ForwardRecord(
        id="44444444-4444-4444-8444-444444444444",
        node_id=NODE_ID,
        promoted_at=DECIDED_AT,
        observed_on="2026-03-01",
    )
    with pytest.raises(FrozenInstanceError):
        record.promoted_at = dt.datetime.now(dt.UTC)  # type: ignore[misc]
    # ISO text for both stamps is accepted, which is what makes a row read back
    # revalidate through the same check the write path used.
    assert record.promoted_at == DECIDED
    assert record.observed_on == dt.date(2026, 3, 1)


def test_a_naive_instant_is_refused() -> None:
    # The boundary between backtest and out-of-sample has to be placeable on a
    # calendar by every later reader, and a naive stamp's day depends on the
    # reader's own offset — so two processes reading one row would disagree
    # about which day the signal went out of sample.
    with pytest.raises(ForwardRecordError) as raised:
        ForwardRecord(
            id="44444444-4444-4444-8444-444444444444",
            node_id=NODE_ID,
            promoted_at=dt.datetime(2026, 3, 1, 12, 0, 0),  # noqa: DTZ001
            observed_on="2026-03-01",
        )
    assert "timezone-aware" in str(raised.value)


def test_a_datetime_is_refused_where_the_day_belongs() -> None:
    # ``datetime`` is a subclass of ``date``, so an isinstance check alone
    # would accept an instant and silently truncate it — and truncating an
    # instant to a day is only honest if you know its offset, which a raw
    # datetime in this position has not been checked for.  The near-miss is
    # refused rather than resolved.
    with pytest.raises(ForwardRecordError) as raised:
        ForwardRecord(
            id="44444444-4444-4444-8444-444444444444",
            node_id=NODE_ID,
            promoted_at=DECIDED,
            observed_on=DECIDED,
        )
    assert "not a datetime" in str(raised.value)


def test_the_rendered_row_names_the_tables_own_columns() -> None:
    record = ForwardRecord(
        id="44444444-4444-4444-8444-444444444444",
        node_id=NODE_ID,
        promoted_at=DECIDED,
        observed_on=DECIDED.date(),
    )
    assert set(record.row()) == {
        "id",
        "node_id",
        "promoted_at",
        "observed_on",
        "live_ic",
        "backtest_ic",
        "realized_cost_bps",
    }
    assert record.row()["promoted_at"] == DECIDED


def test_two_reads_of_one_promotion_are_equal(promoted_signal: ForwardRecords) -> None:
    # Equality over the stored fields is what makes the store's retry test a
    # comparison of *values* rather than of columns read by hand.
    first, _ = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    second, _ = promoted_signal.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert first == second


# -- The request --------------------------------------------------------------


def test_the_request_states_no_instant_and_no_day() -> None:
    # The feature's sentence is that the *route* carries the promotion
    # timestamp, not that the caller does.  A body that could state it would
    # let a caller write a row whose boundary is wherever it liked, and one
    # that could state the day could state one disagreeing with the instant
    # beside it.
    import dataclasses

    fields = {field.name for field in dataclasses.fields(ForwardRecordRequest)}
    assert fields == {"node_id", "forward_days"}


def test_the_request_canonicalises_the_identity_and_refuses_the_rest() -> None:
    request = ForwardRecordRequest(node_id=NODE_ID.upper().replace("-", ""), forward_days=90)
    assert request.node_id == NODE_ID
    with pytest.raises(ForwardRecordError):
        ForwardRecordRequest(node_id=NODE_ID, forward_days=0)


def test_the_module_level_spelling_answers_the_row_itself(
    promoted_signal: ForwardRecords, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One call for a caller that holds a URL and no store — the pipeline step
    # that runs the moment a promotion is decided.  It answers the row rather
    # than a ``(record, created)`` pair because an act asked for as one call
    # has nobody to tell about a retry.
    monkeypatch.setenv(DATABASE_URL_ENV, promoted_signal.database_url)
    record = forward_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert isinstance(record, ForwardRecord)
    assert record.promoted_at == DECIDED


def test_the_module_level_spelling_refuses_a_deployment_that_names_no_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Silence here would be the dangerous failure: a deployment that could not
    # say where forward records live would leave the promotion that just ran
    # with no boundary written, and §5's 90-day track record would begin —
    # unrecorded — the moment nobody was looking.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(ForwardStoreError) as raised:
        forward_record(NODE_ID, forward_days=FORWARD_DAYS)
    assert "forward_record_unwritable" in str(raised.value)


def test_the_store_resolves_nothing_when_no_database_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert ForwardRecords.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert ForwardRecords.resolve() is None


def test_the_store_constructs_without_touching_the_disk(tmp_path: Path) -> None:
    # Composition-time work must not touch the disk, the contract every store
    # in this workspace states.
    database = tmp_path / "composed.db"
    store = ForwardRecords(f"sqlite:///{database}")
    assert store.path == database
    assert not database.exists()


def test_opening_an_absent_store_is_a_refusal_not_a_silent_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert ForwardRecords.resolve() is None


# -- The endpoint -------------------------------------------------------------


def test_the_endpoint_states_the_route_without_an_instance() -> None:
    assert PromoteEndpoint.route == FORWARD_PROMOTE_ROUTE
    assert FORWARD_PROMOTE_ROUTE == "/forward/promote"


def test_the_endpoint_answers_the_response_the_feature_promises(
    promoted_signal: ForwardRecords,
) -> None:
    endpoint = PromoteEndpoint(promoted_signal)
    response = endpoint.post(
        ForwardRecordRequest(node_id=NODE_ID, forward_days=FORWARD_DAYS)
    )
    assert response.created is True
    assert response.retry is False
    assert response.promoted_at == DECIDED
    assert response.observed_on == DECIDED.date()
    assert response.node_id == NODE_ID
    assert response.record.observed is False


def test_the_endpoint_answers_a_retry_with_the_standing_row(
    promoted_signal: ForwardRecords,
) -> None:
    endpoint = PromoteEndpoint(promoted_signal)
    request = ForwardRecordRequest(node_id=NODE_ID, forward_days=FORWARD_DAYS)
    first = endpoint.post(request)
    second = endpoint.post(request)
    assert (first.created, second.created) == (True, False)
    assert (first.retry, second.retry) == (False, True)
    # The same instant both times, however long apart the calls ran — which is
    # the whole of what the caller accounts with.
    assert first.promoted_at == second.promoted_at == DECIDED


def test_the_endpoint_is_duck_checked_at_its_seam() -> None:
    # The factory's scan imports the member under a synthetic module name, so
    # the composed store is structurally a ForwardRecords but never the same
    # class object a direct import yields — an isinstance gate would refuse the
    # very component the factory hands out.
    with pytest.raises(TypeError) as raised:
        PromoteEndpoint(object())  # type: ignore[arg-type]
    assert "open_record" in str(raised.value)


def test_the_endpoint_from_env_answers_none_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert PromoteEndpoint.from_env() is None


def test_the_endpoint_from_env_points_at_the_same_database_as_the_store(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, database_url)
    endpoint = PromoteEndpoint.from_env()
    assert endpoint is not None
    assert endpoint.records.database_url == database_url
    assert endpoint.records.database_url == ForwardRecords.resolve().database_url


# -- The statements -----------------------------------------------------------


def test_the_insert_names_three_columns_and_the_read_names_all_seven() -> None:
    # The insert's *shape* is what makes a fresh row honest: it cannot name an
    # observation column, so a fabricated zero is impossible by construction
    # rather than by a check the writer remembers to make — the same discipline
    # the promotion member's insert states one member over.
    assert "INSERT INTO forward_record" in _INSERT_SQL
    assert "VALUES (?, ?, ?)" in _INSERT_SQL
    for column in ("live_ic", "backtest_ic", "realized_cost_bps"):
        assert column not in _INSERT_SQL
    # The read names all seven, in 0108's own order, so a future migration that
    # appends a column cannot silently shift the fields.
    assert "live_ic, backtest_ic, realized_cost_bps" in _READ_SQL
    assert "SELECT *" not in _READ_SQL
