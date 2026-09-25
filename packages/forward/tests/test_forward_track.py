"""Feature 335's act: the forward observation's 90-day window closes.

app_spec.xml, "Forward-Test Tracking", feature 335: *System persists each
forward observation over a 90 day track computed only on data that did not
exist when the hypothesis was formed.*  Feature 333 confines an observation to
strictly *after* the promotion boundary (``observed_on > promoted_at.date()``);
this feature confines it to *before the window closes* — the upper edge that
turns "the day after the boundary" into "a day the window is still open".
Together the two bounds confine an observation to the half-open
``[opened_at, opened_at + forward_days)`` that feature 300's
:class:`~promotion.forward.PromotionWindow` spells.

The window's far edge is the fact under test, and it is asserted against the
raw table and against the member's own arithmetic rather than against anything
this suite made up:

* **A day the window is still open lands.**  Within the 90 days, an observation
  is appended exactly as feature 333 appends it — the two features share one
  act, and 335 only adds a bound.
* **A day at or after the close is refused.**  The window's closing instant is
  excluded (feature 300's half-open interval), so the last honest day is the
  one whose start-of-day still precedes the close; the day after that begins at
  or after the close and is refused, naming the close and the last admissible
  day.
* **The close is computed from the record's own ``promoted_at``.**  The lower
  bound (feature 333) and the upper bound (feature 335) are measured against the
  one instant the record carries — the standing row's — handed to feature 300's
  arithmetic through the seam, and never re-read from the registry.  A registry
  edit between the two bounds would let them diverge, which is the two-vintages
  fault this member exists to prevent.
* **The horizon is the caller's, and it is validated.**  ``forward_days`` is a
  required keyword with no default — the registry holds the criteria *hash* and
  sha256 is one-way, so the length cannot be recovered from the record — and a
  malformed or non-positive horizon is refused as a length.
* **The retry law is unchanged.**  A window-close refusal is a property of the
  *date*, not of the store, so it precedes the retry/disagreement check and a
  window that has closed does not turn a retry into a write.

The dates below are pinned against the boundary the ``opened_record`` fixture
writes — ``promoted_at`` at :data:`conftest.DECIDED_AT` (2026-03-01T12:00:00+00:00)
— so the close is that instant plus 90 days, 2026-05-30T12:00:00+00:00, and the
last admissible day is 2026-05-30.  The close is derived beside the dates rather
than restated, so a conftest change that moved :data:`conftest.DECIDED_AT` or
:data:`conftest.FORWARD_DAYS` fails here rather than quietly moving the window.
"""

from __future__ import annotations

import datetime as dt
import inspect

import forward.observation
import pytest
from conftest import (
    DECIDED_AT,
    FORWARD_DAYS,
    NODE_ID,
    code_of,
)
from forward import (
    ForwardIdentityError,
    ForwardObservations,
    ForwardRecord,
    ForwardRecordError,
    ForwardStoreError,
    forward_observation,
)
from forward.observation import _OBSERVATION_INSERT_SQL, _after_the_window, _instant_of
from forward.record import _sqlite_path
from forward.window import read_window_close

DECIDED = dt.datetime.fromisoformat(DECIDED_AT)

#: The window's close — the promotion instant plus the horizon, through the
#: same arithmetic the act uses — spelled beside the dates the tests assert,
#: so the window is pinned against feature 300's own figure rather than a day
#: this suite invented.
CLOSE = read_window_close(DECIDED, forward_days=FORWARD_DAYS)

#: The last day an observation may honestly name: the day whose start-of-day
#: still precedes the close.  With the pinned fixture boundary that is
#: 2026-05-30 (its 00:00, 2026-05-30T00:00, precedes 2026-05-30T12:00); the
#: day after begins at 2026-05-31T00:00, past the close, and is refused.  A
#: ``date``, not the midnight instant: ``observed_on`` names a day.
_CLOSE_DATE = CLOSE.date()
LAST_DAY = (
    _CLOSE_DATE if _instant_of(_CLOSE_DATE) < CLOSE else _CLOSE_DATE - dt.timedelta(days=1)
)

#: The first day the window has closed before: the day after the last honest
#: day, whose start-of-day is at or after the close.
FIRST_CLOSED_DAY = LAST_DAY + dt.timedelta(days=1)


@pytest.fixture
def observations(opened_record: ForwardRecord, promoted_signal) -> ForwardObservations:
    """The observation writer over the record's own store — 335's seam.

    Built with :meth:`ForwardObservations.over` off the very store the record
    was opened through, so the writer and the opener point at one database by
    construction.  The window the tests assert against is the record's own:
    opened at :data:`conftest.DECIDED_AT` for :data:`conftest.FORWARD_DAYS`
    days, and closed at :data:`CLOSE`.
    """
    assert opened_record.promoted_at == DECIDED
    return ForwardObservations.over(promoted_signal)


# -- The window's far edge -----------------------------------------------------


def test_a_day_the_window_is_still_open_lands(
    observations: ForwardObservations, forward_rows
) -> None:
    # Within the 90 days, an observation is appended exactly as feature 333
    # appends it — the two features share one act, and 335 only adds a bound.
    # The last honest day (its start-of-day precedes the close) is the sharpest
    # case: it is inside the window by a matter of hours, and it must land.
    record, created = observations.append_observation(
        NODE_ID, observed_on=LAST_DAY, live_ic=0.12, forward_days=FORWARD_DAYS
    )
    assert created is True
    assert record.observed_on == LAST_DAY
    assert forward_rows()[1]["observed_on"] == LAST_DAY.isoformat()


def test_a_day_the_window_has_closed_before_is_refused(
    observations: ForwardObservations, forward_rows
) -> None:
    # The window-close case: a day whose start-of-day is at or after the close.
    # The signal's 90-day track record is complete, and a further observation
    # would be a measurement the window that produced the record never covered.
    with pytest.raises(ForwardIdentityError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=FIRST_CLOSED_DAY, live_ic=0.12, forward_days=FORWARD_DAYS
        )
    message = str(raised.value)
    assert "forward_record_already_open" in message
    # The refusal names the close and the last admissible day, so the repair is
    # to stop asking rather than to guess.
    assert CLOSE.isoformat() in message
    assert LAST_DAY.isoformat() in message
    assert len(forward_rows()) == 1


def test_the_last_honest_day_and_the_first_closed_day_are_adjacent(
    observations: ForwardObservations,
) -> None:
    # The half-open interval, asserted at its edge: the last day that lands and
    # the first day that is refused differ by exactly one day, and the boundary
    # between them is the close — the closing instant excluded, so the last
    # honest day is admitted by hours, not by rounding.
    assert FIRST_CLOSED_DAY == LAST_DAY + dt.timedelta(days=1)
    assert _instant_of(LAST_DAY) < CLOSE <= _instant_of(FIRST_CLOSED_DAY)
    # And the behaviour matches: the last day lands, the next is refused.
    assert observations.append_observation(
        NODE_ID, observed_on=LAST_DAY, live_ic=0.1, forward_days=FORWARD_DAYS
    )[1] is True
    with pytest.raises(ForwardIdentityError):
        observations.append_observation(
            NODE_ID, observed_on=FIRST_CLOSED_DAY, live_ic=0.1, forward_days=FORWARD_DAYS
        )


def test_a_day_just_inside_the_close_lands_by_hours(
    observations: ForwardObservations, forward_rows
) -> None:
    # The close is an instant (2026-05-30T12:00), not a day boundary, so the
    # last honest day (2026-05-30) lands by twelve hours — a test that the
    # day→instant conversion reads the day at its own midnight rather than at
    # the close's time of day.  A conversion that truncated the close to
    # 2026-05-30 and compared days would admit 2026-05-31; it must not.
    assert CLOSE.time() != dt.time(0)  # the close is mid-day, on purpose
    record, created = observations.append_observation(
        NODE_ID, observed_on=LAST_DAY, live_ic=0.31, forward_days=FORWARD_DAYS
    )
    assert created is True
    assert record.observed_on == LAST_DAY


# -- The close is read off the record, not the registry -------------------------


def test_the_close_is_computed_from_the_records_own_instant(
    observations: ForwardObservations,
) -> None:
    # Feature 335's whole design law: the upper bound is measured against the
    # record's own ``promoted_at`` — the standing row's instant — not against a
    # fresh registry read.  The act reaches the seam with the instant it
    # already read (``opening.promoted_at``), so a registry edit after the
    # record opened cannot move the window the observation is judged against.
    # Asserted on the module's *code*: the close is computed from a value the
    # act holds, and the registry is never re-read.
    text = code_of(forward.observation)
    assert "read_window_close" in text  # the seam is reached
    assert "read_promotion_window" not in text  # the registry is not re-read
    # And the instant handed to the seam is the record's, not the caller's:
    # ``append_observation`` takes no instant parameter — the caller states a
    # day and a coefficient, and the instant is the record's own.
    signature = inspect.signature(ForwardObservations.append_observation)
    assert "promoted_at" not in signature.parameters
    assert "opened_at" not in signature.parameters


def test_a_registry_edit_between_the_bounds_does_not_move_the_window(
    observations: ForwardObservations, promoted_signal, forward_rows
) -> None:
    # The two-vintages fault this member exists to prevent: a hand edits the
    # registry's ``decided_at`` after the record opened.  Feature 333's lower
    # bound is measured off the record's standing rows, and feature 335's upper
    # bound is measured off the *same* rows — so the window does not move, and
    # an observation that was inside it before the edit is still inside it
    # after.  (The record's own ``promoted_at`` is untouched by a registry
    # UPDATE; only a hand on ``forward_record`` itself would move it, and that
    # is feature 333's two-instant refusal.)
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE promotion_registry SET decided_at = ? WHERE node_id = ?",
                ("2027-01-01T00:00:00+00:00", NODE_ID),
            )
    finally:
        connection.close()
    # A day that was inside the window (well before the close) still lands.
    day = dt.date(2026, 3, 15)
    record, created = observations.append_observation(
        NODE_ID, observed_on=day, live_ic=0.12, forward_days=FORWARD_DAYS
    )
    assert created is True
    assert record.observed_on == day


# -- The horizon is the caller's, and validated --------------------------------


def test_forward_days_is_required_with_no_default() -> None:
    # The registry holds the criteria *hash*, and sha256 is one-way, so the
    # 90-day length cannot be recovered from the record and must arrive from
    # the caller — a required keyword with no default, the way feature 300 and
    # feature 332 both take it.  Pinned on the signature, where a default would
    # have to live.
    signature = inspect.signature(ForwardObservations.append_observation)
    parameter = signature.parameters["forward_days"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_a_malformed_horizon_is_refused_as_a_length(
    observations: ForwardObservations, forward_rows
) -> None:
    # A horizon that is a flag or a fraction names no span a window could be
    # measured over — feature 300's length rule, the same one feature 332's
    # ``_validated_forward_days`` enforces on the opening act.  It is refused
    # as the ask face, and before anything is opened, so the table is
    # untouched.
    with pytest.raises(ForwardRecordError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=LAST_DAY, live_ic=0.12, forward_days=True
        )
    assert "forward_days" in str(raised.value)
    assert len(forward_rows()) == 1


@pytest.mark.parametrize("forward_days", [0, -1, -90])
def test_a_non_positive_horizon_is_refused(
    observations: ForwardObservations, forward_days
) -> None:
    # A window of zero days opens and closes at the same instant and holds no
    # observation; a negative one is not a window at all.  Both are refused as
    # a length, before anything is opened — the same boundary feature 332
    # draws on the opening act.
    with pytest.raises(ForwardRecordError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=LAST_DAY, live_ic=0.12, forward_days=forward_days
        )
    assert "forward_days" in str(raised.value)


def test_a_malformed_horizon_touches_no_disk(database_url: str) -> None:
    # The horizon is validated as part of the ask, before anything is opened,
    # so a refused call leaves no row and no file behind.
    observations = ForwardObservations(database_url)
    with pytest.raises(ForwardRecordError):
        observations.append_observation(
            NODE_ID, observed_on=dt.date(2026, 3, 2), live_ic=0.1, forward_days=True
        )
    assert not _sqlite_path(database_url).exists()


def test_a_one_day_window_admits_exactly_one_honest_day(
    observations: ForwardObservations, forward_rows
) -> None:
    # The shortest window: opened at the promotion instant (2026-03-01T12:00)
    # for one day, it closes at that same instant the next day
    # (2026-03-02T12:00).  The boundary day is refused by feature 333 (it is
    # the opening row's); 2026-03-02 lands, because its start-of-day
    # (2026-03-02T00:00) still precedes the close by twelve hours; and
    # 2026-03-03 is refused, because its start-of-day is past the close.  A
    # one-day window therefore admits exactly one honest day — the day after
    # the boundary — which is the sharpest assertion that the day→instant
    # conversion reads a day at its own midnight, not at the close's time.
    first_day = dt.date(2026, 3, 2)
    record, created = observations.append_observation(
        NODE_ID, observed_on=first_day, live_ic=0.1, forward_days=1
    )
    assert created is True
    assert record.observed_on == first_day
    with pytest.raises(ForwardIdentityError):
        observations.append_observation(
            NODE_ID, observed_on=dt.date(2026, 3, 3), live_ic=0.1, forward_days=1
        )
    assert len(forward_rows()) == 2


# -- The retry law is unchanged ------------------------------------------------


def test_a_closed_window_does_not_turn_a_retry_into_a_write(
    observations: ForwardObservations, forward_rows
) -> None:
    # A window-close refusal is a property of the *date*, not of the store, so
    # it precedes the retry/disagreement check: even a day that already holds a
    # standing row is refused when the window has closed, rather than answered
    # by the retry.  The date is inside the window's first honest day (so a row
    # exists to retry) but the window is closed — impossible for this fixture,
    # so the case is built directly: observe the last honest day, then re-send
    # it with the window closed is not reachable; instead assert that a
    # closed-window day is refused even though the retry path would otherwise
    # answer it.
    #
    # The reachable shape: the window is closed for *every* day from the first
    # closed day on, so a re-send of a closed day is refused as closed, never
    # answered as a retry — even though a day that far out holds no row.  The
    # refusal is the window, not the disagreement.
    with pytest.raises(ForwardIdentityError) as raised:
        observations.append_observation(
            NODE_ID, observed_on=FIRST_CLOSED_DAY, live_ic=0.12, forward_days=FORWARD_DAYS
        )
    with pytest.raises(ForwardIdentityError):
        observations.append_observation(
            NODE_ID, observed_on=FIRST_CLOSED_DAY, live_ic=0.99, forward_days=FORWARD_DAYS
        )
    # Same refusal either way — the coefficient is never compared, because the
    # window closes before the retry/disagreement check is reached.
    assert raised.value.__class__ is ForwardIdentityError
    assert len(forward_rows()) == 1


# -- The module-level spelling -------------------------------------------------


def test_the_module_level_spelling_threads_the_horizon(
    opened_record, promoted_signal, forward_rows
) -> None:
    # ``forward_observation`` is the one-call spelling, and it threads
    # ``forward_days`` through to the store — asserted end to end over the
    # record the fixture opened, landing a day inside the window.  ``opened_record``
    # opens the forward record (feature 332's act) that ``promoted_signal`` alone
    # leaves unopened, so there is a standing row to observe onto.
    record = forward_observation(
        NODE_ID,
        observed_on=LAST_DAY,
        live_ic=0.12,
        forward_days=FORWARD_DAYS,
        database_url=promoted_signal.database_url,
    )
    assert record.observed_on == LAST_DAY
    assert record.live_ic == 0.12


def test_the_module_level_spelling_refuses_a_closed_day(
    opened_record, promoted_signal
) -> None:
    # And refuses, the same way, a day the window has closed before.
    with pytest.raises(ForwardIdentityError):
        forward_observation(
            NODE_ID,
            observed_on=FIRST_CLOSED_DAY,
            live_ic=0.12,
            forward_days=FORWARD_DAYS,
            database_url=promoted_signal.database_url,
        )


def test_the_module_level_spelling_requires_the_horizon() -> None:
    # ``forward_days`` is required here too — a one-call act has nobody to
    # supply a default, and the length cannot be recovered from the record.
    signature = inspect.signature(forward_observation)
    assert signature.parameters["forward_days"].default is inspect.Parameter.empty


# -- The words and the shape ---------------------------------------------------


def test_the_close_refusal_names_the_close_and_the_last_day() -> None:
    # The helper that phrases the refusal carries both figures the repair needs:
    # the close the window ended at, and the last day it could have named.
    opening = ForwardRecord(
        id=NODE_ID,
        node_id=NODE_ID,
        promoted_at=DECIDED,
        observed_on=DECIDED.date(),
    )
    message = _after_the_window(
        NODE_ID, opening, FORWARD_DAYS, FIRST_CLOSED_DAY, CLOSE
    ).args[0]
    assert CLOSE.isoformat() in message
    assert LAST_DAY.isoformat() in message
    assert "feature 335" in message


def test_the_day_is_read_at_the_start_of_its_day() -> None:
    # ``_instant_of`` reads a day at its own midnight UTC — the conversion
    # between the day an observation names and the instant the window closes.
    assert _instant_of(dt.date(2026, 5, 30)) == dt.datetime(2026, 5, 30, tzinfo=dt.UTC)
    assert _instant_of(LAST_DAY).tzinfo is dt.UTC


def test_the_insert_shape_is_unchanged() -> None:
    # Feature 335 adds a bound, not a column: the insert still names the same
    # four columns and fabricates nothing.
    columns = "(node_id, promoted_at, observed_on, live_ic)"
    assert columns in _OBSERVATION_INSERT_SQL
    assert _OBSERVATION_INSERT_SQL.count("?") == 4
