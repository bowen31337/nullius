"""Feature 325: new orders refused until a manual reset, on a breached
daily loss limit.

The suite is organised around the sentence's four nouns, because they
are the four things that can silently stop being true, plus the shape
the sentence's *reading* claims:

* **The configured daily loss limit.**  The limit is the deployment's
  own number — a required keyword with no default, refused rather than
  guessed — and the validation tests are half of that claim: each
  near-miss (``bool``, non-finite, non-positive, non-number) is refused
  by name rather than judged against, because a limit nobody could
  evaluate is a halt nobody asked for.
* **Is breached.**  The comparison is strict ``>`` and is pinned at
  equality rather than approximated: a day sitting exactly at its limit
  is a day at the line, not past it, and it answers ``None`` without
  the store even being opened.  The loss figure is handed over, never
  derived, and held to its own terms — non-negative above all, because
  a sign error arriving here would silently disable the halt exactly
  when the day went badly.
* **Rejects new orders.**  The guard reads the standing state from the
  table, not from a flag the last process left in memory, and the
  refusal carries the record it was taken from.  The tests that matter
  most are the ones that make the refusal *stick* — three calls later,
  a fresh store later, a restarted-process read later — because a
  refusal that quietly lifted would be a limit that quietly stopped
  existing.
* **Until a manual reset.**  The clause that decides the architecture:
  the halt is its own standing state with its own reset door, and the
  tests pin both halves — nothing else lifts it (not time, not the loss
  figure getting better, not a restart, not the kill channel being
  cleared, because it never sent one), and the reset lifts exactly it
  (the breach facts stay as they landed; a new breach stands on its own
  row; the kill channel beside it is untouched by the reset).
* **The standing law is the schema's.**  At most one un-reset row, by
  a partial unique index — asserted against the driver directly, both
  sides (a second un-reset row refused; the partition re-opened by a
  reset) — and a table found breaking that law is *refused* by name,
  never arbitrated, because whichever row a reader picked would be a
  refusal the other did not justify.
* **The refusals are the last subject.**  A loss that is not a loss, a
  limit that is not a band, a row no halt can be reconstructed as
  (checked by re-deriving the breach from the row's own two figures —
  the one tamper that would re-open the order layer), half a reset, a
  reset that closed nothing, and the four directions the store's
  absence cuts.  Each is named by the grep token its messages open
  with.
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
from risk.daily_loss import (
    DATABASE_URL_ENV,
    RISK_DAILY_LOSS_HALT_TABLE,
    DailyLossHalt,
    RiskDailyLossHaltStore,
    halt_on_daily_loss,
    manual_reset,
    orders_halted_error,
    recorded_daily_loss_halts,
    require_within_daily_loss_limit,
)
from risk.errors import (
    DAILY_LOSS_CODE,
    ORDERS_HALTED_CODE,
    RiskDailyLossError,
    RiskError,
    RiskOrdersHaltedError,
    RiskOrdersKilledError,
    RiskOrdersStaleError,
    RiskStoreError,
)
from risk.kill import RISK_ORDER_KILL_TABLE, RiskKillSwitch

REPO_ROOT = Path(__file__).resolve().parents[3]

#: A limit and a breach moment fixed for the whole suite, so every
#: assertion about a record or a message is exact.  The loss figures sit
#: unambiguously inside, exactly at, and past the line.
LIMIT = 10.0
BREACHED = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
RESET = datetime(2026, 9, 25, 16, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 25, 17, 0, 0, tzinfo=UTC)


@pytest.fixture
def store(test_database_url: str) -> RiskDailyLossHaltStore:
    return RiskDailyLossHaltStore(test_database_url)


def _iso(moment: datetime) -> str:
    """The module's own canonical spelling, for asserting on messages.

    Restated rather than imported from the module's private helper, so
    these tests measure the spelling a message carries rather than a copy
    of the function that composes it: if the canonical form changed, a
    test that imported it would change with it and assert nothing.
    """
    return moment.astimezone(UTC).isoformat()


def _row_count(database_url: str) -> int:
    """How many rows the halt table holds, read with the driver directly.

    The first-write-wins and episode laws are stated in the schema, so
    the tests that pin them must read the table without going through
    the store whose discipline those laws exist to replace.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {RISK_DAILY_LOSS_HALT_TABLE}"
            ).fetchone()[0]
        )


def _kills(database_url: str) -> int:
    """How many rows feature 322's channel holds — the monotone state."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            (count,) = connection.execute(
                f"SELECT COUNT(*) FROM {RISK_ORDER_KILL_TABLE}"
            ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return count


def _tables(database_url: str) -> set[str]:
    """Every table the member's store holds, read with the driver directly."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {name for (name,) in rows}


def _breach(
    database_url: str,
    *,
    loss: float = 11.0,
    limit: float = LIMIT,
    moment: datetime = BREACHED,
    sender: str | None = None,
) -> DailyLossHalt:
    """The one act every test in this suite starts from, spelled once."""
    halt = RiskDailyLossHaltStore(database_url).halt_on_loss(
        daily_loss=loss,
        daily_loss_limit=limit,
        supervisor_process_id=sender,
        breached_at=moment,
    )
    assert halt is not None, "the fixture must breach, not sit at the line"
    return halt


# -- Is breached -----------------------------------------------------------------


class TestTheJudgement:
    def test_a_day_inside_its_limit_answers_none_and_opens_nothing(
        self, tmp_path: Path
    ) -> None:
        # The day at no risk of halting is not a reason to touch a
        # database: the judge answers before the store is opened, and
        # the file is never created.
        database = tmp_path / "unopened.db"
        store = RiskDailyLossHaltStore(f"sqlite:///{database}")
        assert store.halt_on_loss(daily_loss=9.99, daily_loss_limit=LIMIT) is None
        assert not database.exists()

    def test_a_day_exactly_at_its_limit_is_at_the_line_not_past_it(
        self, tmp_path: Path
    ) -> None:
        # §13.3's trigger is `>`, strictly, so a day sitting exactly on
        # its limit is inside it -- the boundary pinned exactly rather
        # than approximated, and again without opening the store.
        database = tmp_path / "unopened.db"
        assert (
            halt_on_daily_loss(
                daily_loss=LIMIT,
                daily_loss_limit=LIMIT,
                database_url=f"sqlite:///{database}",
            )
            is None
        )
        assert not database.exists()

    def test_the_smallest_possible_step_past_the_limit_halts(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        halt = store.halt_on_loss(daily_loss=LIMIT + 0.000001, daily_loss_limit=LIMIT)
        assert halt is not None
        assert halt.changed is True
        assert halt.loss == LIMIT + 0.000001
        assert halt.standing is True

    def test_a_flat_day_answers_none(self, store: RiskDailyLossHaltStore) -> None:
        # Zero is a figure like any other: a day that has lost nothing
        # is inside every limit there is.
        assert store.halt_on_loss(daily_loss=0.0, daily_loss_limit=LIMIT) is None

    def test_the_loss_figure_is_handed_over_never_derived(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The record's loss is exactly the ask, and the ask is exactly
        # two figures: whoever owns the book owns the number, and this
        # module holds no verb that computes one.
        halt = store.halt_on_loss(daily_loss=1234.5, daily_loss_limit=LIMIT)
        assert halt is not None
        assert halt.loss == 1234.5
        assert halt.limit == LIMIT

    def test_the_limit_and_the_loss_are_required_keywords(self) -> None:
        # Both figures state themselves at the signature: no default,
        # keyword-only, so a caller cannot trade a positional habit for
        # a limit nobody chose.
        for spelling in (RiskDailyLossHaltStore.halt_on_loss, halt_on_daily_loss):
            parameters = inspect.signature(spelling).parameters
            for name in ("daily_loss", "daily_loss_limit"):
                parameter = parameters[name]
                assert parameter.default is inspect.Parameter.empty, name
                assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name

    def test_calling_without_a_figure_is_a_type_error_not_a_default(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        with pytest.raises(TypeError):
            store.halt_on_loss(daily_loss=11.0)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            store.halt_on_loss(daily_loss_limit=LIMIT)  # type: ignore[call-arg]


class TestTheLossFigure:
    @pytest.mark.parametrize("loss", [-0.01, -1.0, -1000000.0])
    def test_a_negative_loss_is_refused_by_name(self, loss: float) -> None:
        # A negative loss is a gain wearing the loss's name, and the
        # sign error it would carry into the comparison is the one that
        # silently disables the halt -- refused, not clamped, not
        # absolutized.
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(daily_loss=loss, daily_loss_limit=LIMIT, env={})
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert "non-negative" in message

    @pytest.mark.parametrize("loss", [True, False])
    def test_a_bool_loss_is_refused(self, loss: bool) -> None:
        # `isinstance(True, int)` is true in Python, so a naive numeric
        # check would pass a loss of one wearing a boolean's name.
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(daily_loss=loss, daily_loss_limit=LIMIT, env={})
        assert "must be a number" in str(refused.value)

    @pytest.mark.parametrize("loss", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_loss_is_refused(self, loss: float) -> None:
        # `nan` compares false against every limit, so a non-finite
        # figure would sit *inside* the limit for any number
        # configured -- the one direction this feature must never fail
        # in.
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(daily_loss=loss, daily_loss_limit=LIMIT, env={})
        assert "finite" in str(refused.value)

    @pytest.mark.parametrize("loss", ["11000", None, object()])
    def test_a_loss_that_is_not_a_number_is_refused(self, loss: object) -> None:
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(
                daily_loss=loss,
                daily_loss_limit=LIMIT,
                env={},  # type: ignore[arg-type]
            )
        assert DAILY_LOSS_CODE in str(refused.value)

    def test_a_whole_number_loss_is_a_figure_like_any_other(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        halt = store.halt_on_loss(daily_loss=11, daily_loss_limit=LIMIT)
        assert halt is not None
        assert halt.loss == 11.0


class TestTheLimitIsConfiguration:
    @pytest.mark.parametrize("limit", [0.0, -10.0])
    def test_a_non_positive_limit_is_refused(self, limit: float) -> None:
        # Every loss above zero breaches a non-positive limit, so a
        # deployment that passed one configured a refusal rather than a
        # tolerance.  §13.3 names the trigger and no number, but it
        # does not name *any* number.
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(daily_loss=11.0, daily_loss_limit=limit, env={})
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert "greater than zero" in message

    @pytest.mark.parametrize("limit", [True, False])
    def test_a_bool_limit_is_refused(self, limit: bool) -> None:
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(daily_loss=11.0, daily_loss_limit=limit, env={})
        assert "must be a number" in str(refused.value)

    @pytest.mark.parametrize("limit", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_limit_is_refused(self, limit: float) -> None:
        # A `nan` limit compares false against every loss, answering
        # *not breached* for a day of any size: a daily loss limit that
        # never once fired.
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(daily_loss=11.0, daily_loss_limit=limit, env={})
        assert "finite" in str(refused.value)

    @pytest.mark.parametrize("limit", ["10000", None, object()])
    def test_a_limit_that_is_not_a_number_is_refused(self, limit: object) -> None:
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(
                daily_loss=11.0,
                daily_loss_limit=limit,
                env={},  # type: ignore[arg-type]
            )
        assert DAILY_LOSS_CODE in str(refused.value)

    def test_the_limit_has_no_default(self) -> None:
        # The sentence's own word for the figure is *configured*: a
        # module that guessed a limit would halt trading on a number
        # nobody chose.  (Pinned at the signature in
        # TestTheJudgement; this is the caller's half of the same law.)
        with pytest.raises(TypeError):
            halt_on_daily_loss(daily_loss=11.0)  # type: ignore[call-arg]


# -- The record ------------------------------------------------------------------


class TestTheRecord:
    def _record(
        self,
        *,
        loss: float = 11.0,
        limit: float = LIMIT,
        reset_at: datetime | None = None,
        reset_by: str | None = None,
        changed: bool = True,
    ) -> DailyLossHalt:
        return DailyLossHalt(
            sequence=1,
            loss=loss,
            limit=limit,
            breached_at=BREACHED,
            supervisor_process_id="supervisor/4711",
            reset_at=reset_at,
            reset_by=reset_by,
            changed=changed,
        )

    def test_the_record_carries_the_whole_sentence(self) -> None:
        # The loss, the limit it broke, the breach moment, the judging
        # process, the reset's two halves and the row's own number: the
        # value is the sentence, and nothing in it is derived.
        halt = self._record()
        assert halt.sequence == 1
        assert halt.loss == 11.0
        assert halt.limit == LIMIT
        assert halt.breached_at == BREACHED
        assert halt.supervisor_process_id == "supervisor/4711"
        assert halt.reset_at is None and halt.reset_by is None
        assert halt.standing is True

    def test_the_record_is_frozen(self) -> None:
        # A record is a value: the facts a refusal rides on cannot be
        # edited after the fact by whoever is holding it.
        halt = self._record()
        with pytest.raises(FrozenInstanceError):
            halt.loss = 1.0  # type: ignore[misc]

    def test_the_breach_is_re_derived_not_trusted(self) -> None:
        # A hand-built record whose loss sits inside its own limit
        # would be a refusal with no breach behind it -- the one shape
        # that could launder a halt nobody justified.
        with pytest.raises(RiskDailyLossError) as refused:
            self._record(loss=5.0)
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert "does not exceed" in message

    def test_the_breach_is_refused_at_exactly_the_line(self) -> None:
        # The record holds the boundary the judgement does: a halt is a
        # *breaching* record, and a loss exactly at its limit is not
        # one -- `>` here too, pinned at equality.
        with pytest.raises(RiskDailyLossError):
            self._record(loss=LIMIT)

    @pytest.mark.parametrize("sequence", [0, -1, True, "1", 1.0, None])
    def test_a_sequence_the_table_never_minted_is_refused(
        self, sequence: object
    ) -> None:
        with pytest.raises(RiskDailyLossError) as refused:
            DailyLossHalt(
                sequence=sequence,  # type: ignore[arg-type]
                loss=11.0,
                limit=LIMIT,
                breached_at=BREACHED,
                supervisor_process_id="supervisor/4711",
                reset_at=None,
                reset_by=None,
                changed=True,
            )
        assert DAILY_LOSS_CODE in str(refused.value)

    def test_a_changed_bit_that_is_not_a_bool_is_refused(self) -> None:
        # `isinstance(1, bool)` is false but `1 == True` is true, so a
        # truthy-looking non-bool would compare equal to the bit while
        # being a different fact.
        with pytest.raises(RiskDailyLossError) as refused:
            self._record(changed=1)  # type: ignore[arg-type]
        assert "must be a bool" in str(refused.value)

    @pytest.mark.parametrize(
        ("reset_at", "reset_by"),
        [
            (RESET, None),  # a moment with no actor
            (None, "operator/7"),  # an actor with no moment
        ],
    )
    def test_half_a_reset_is_refused(
        self, reset_at: datetime | None, reset_by: str | None
    ) -> None:
        # A reset states *when* and *who* or neither at all: half a
        # reset is a halt an operator cannot read.
        with pytest.raises(RiskDailyLossError) as refused:
            self._record(reset_at=reset_at, reset_by=reset_by)
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert "both" in message

    @pytest.mark.parametrize("what", ["breached_at", "reset_at"])
    def test_a_naive_moment_is_refused(self, what: str) -> None:
        # A breach that cannot say unambiguously when it happened
        # cannot be ordered against anything -- the same discipline
        # kill.py holds its ``sent_at`` to.
        moments: dict[str, datetime | None] = {
            "breached_at": BREACHED,
            "reset_at": None,
        }
        moments[what] = BREACHED.replace(tzinfo=None)
        with pytest.raises(RiskDailyLossError) as refused:
            DailyLossHalt(
                sequence=1,
                loss=11.0,
                limit=LIMIT,
                breached_at=moments["breached_at"],  # type: ignore[arg-type]
                supervisor_process_id="supervisor/4711",
                reset_at=moments["reset_at"],
                reset_by=None if moments["reset_at"] is None else "operator/7",
                changed=True,
            )
        assert what in str(refused.value)

    @pytest.mark.parametrize("sender", ["", "   ", 7])
    def test_a_label_that_names_no_process_is_refused(self, sender: object) -> None:
        with pytest.raises(RiskDailyLossError) as refused:
            DailyLossHalt(
                sequence=1,
                loss=11.0,
                limit=LIMIT,
                breached_at=BREACHED,
                supervisor_process_id=sender,  # type: ignore[arg-type]
                reset_at=None,
                reset_by=None,
                changed=True,
            )
        assert "non-empty text" in str(refused.value)

    def test_a_non_utc_breach_is_stored_as_the_same_instant(
        self, test_database_url: str
    ) -> None:
        # One UTC spelling on the row, whatever offset the caller's
        # clock carried: two supervisors in two timezones that judged
        # the same breach wrote the same instant.
        two_hours_ahead = timezone(timedelta(hours=2))
        halt = _breach(test_database_url, moment=BREACHED.astimezone(two_hours_ahead))
        assert halt.breached_at == BREACHED

    def test_the_summary_names_the_figures_the_moment_and_the_door(
        self,
    ) -> None:
        summary = self._record().summary
        assert "11.0" in summary
        assert "10.0" in summary
        assert _iso(BREACHED) in summary
        assert "supervisor/4711" in summary
        assert "until a manual reset" in summary

    def test_the_summary_of_a_closed_halt_names_the_reset_instead(
        self,
    ) -> None:
        # The closing clause says which of the sentence's two halves the
        # record is in: standing refuses, closed explains who re-opened
        # the order layer and when.
        summary = self._record(reset_at=RESET, reset_by="operator/7").summary
        assert "reset" in summary
        assert _iso(RESET) in summary
        assert "operator/7" in summary
        assert "until a manual reset" not in summary

    def test_standing_is_derived_from_the_reset_not_stored_beside_it(
        self,
    ) -> None:
        # One spelling of one state: `standing` is exactly the absence
        # of a reset moment, re-derived on read, so the record cannot
        # hold a standing bit that disagrees with its own reset.
        assert self._record().standing is True
        assert self._record(reset_at=RESET, reset_by="operator/7").standing is False


# -- The halt, and first-write-wins per episode ------------------------------------


class TestTheHalt:
    def test_the_first_breach_lands_one_row(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        halt = _breach(store.database_url, sender="supervisor/4711")
        assert halt.changed is True
        assert halt.sequence == 1
        assert _row_count(store.database_url) == 1
        standing = store.standing()
        assert standing is not None
        assert standing == DailyLossHalt(
            sequence=1,
            loss=11.0,
            limit=LIMIT,
            breached_at=BREACHED,
            supervisor_process_id="supervisor/4711",
            reset_at=None,
            reset_by=None,
            changed=False,
        )

    def test_the_default_judge_is_this_process(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # "A separate process" is only checkable if the row names the
        # process that judged the day -- and the kernel, not the
        # caller, is asked.
        halt = store.halt_on_loss(daily_loss=11.0, daily_loss_limit=LIMIT)
        assert halt is not None
        assert halt.supervisor_process_id == store.process_id
        assert halt.supervisor_process_id == process_identity()
        host, _, pid = halt.supervisor_process_id.rpartition("/")
        assert host and pid.isdigit()

    def test_the_breach_moment_defaults_to_the_instant_of_the_call(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        before = datetime.now(UTC)
        halt = store.halt_on_loss(daily_loss=11.0, daily_loss_limit=LIMIT)
        after = datetime.now(UTC)
        assert halt is not None
        assert before <= halt.breached_at <= after
        assert halt.breached_at.tzinfo is not None

    def test_a_re_breach_writes_nothing_and_answers_the_first_facts(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # A supervisor sweeps again (or restarts and re-judges): the
        # first breach's figures and moment are the fact on record, and
        # a later judge that moved them would quietly shrink the record
        # of how long the order layer has been obliged to stop --
        # including when the day got *worse*, which is not a new
        # episode while the first still stands.
        _breach(store.database_url, loss=11.0, sender="supervisor/1")
        later = _breach(
            store.database_url,
            loss=99.0,
            moment=LATER,
            sender="supervisor/999",
        )
        assert later.changed is False
        assert later.sequence == 1
        assert later.loss == 11.0
        assert later.breached_at == BREACHED
        assert later.supervisor_process_id == "supervisor/1"
        assert _row_count(store.database_url) == 1

    def test_a_breach_from_a_second_store_over_the_same_url_is_one_row(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The cross-process property, in-process first: the row one
        # store writes is the row the next store reads, because the
        # database -- not any process's memory -- is the coordination
        # point.
        _breach(store.database_url)
        other = RiskDailyLossHaltStore(store.database_url)
        assert other.halted() is True
        assert (
            other.halt_on_loss(
                daily_loss=50.0, daily_loss_limit=LIMIT, breached_at=LATER
            ).changed
            is False
        )
        assert _row_count(store.database_url) == 1

    def test_construction_touches_no_database(self, tmp_path: Path) -> None:
        # The composition-time promise every store in this workspace
        # states: asking for the store is always safe, and the first
        # breach is where a file is actually created.
        database = tmp_path / "not-yet.db"
        RiskDailyLossHaltStore(f"sqlite:///{database}")
        assert not database.exists()

    def test_ensure_schema_is_idempotent(self, store: RiskDailyLossHaltStore) -> None:
        store.ensure_schema()
        store.ensure_schema()
        assert store.standing() is None


# -- Rejects new orders -----------------------------------------------------------


class TestTheGuard:
    def test_it_passes_while_no_halt_stands(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        store.require_orders_allowed()  # no refusal, no row written
        assert _row_count(store.database_url) == 0

    def test_it_refuses_under_a_standing_halt(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        _breach(store.database_url)
        with pytest.raises(RiskOrdersHaltedError):
            store.require_orders_allowed()

    def test_the_refusal_carries_the_record_it_was_taken_from(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The caller reaching for an order learns which day, which
        # line, which breach moment and which process -- without a
        # second query, and from the same object the message was
        # composed from, not a copy that could disagree.
        halt = _breach(store.database_url, sender="supervisor/4711")
        with pytest.raises(RiskOrdersHaltedError) as refused:
            store.require_orders_allowed()
        assert refused.value.halt is not None
        assert refused.value.halt.sequence == halt.sequence == 1
        assert refused.value.halt.loss == halt.loss
        assert refused.value.halt.breached_at == halt.breached_at
        assert refused.value.halt.supervisor_process_id == "supervisor/4711"
        assert refused.value.halt.changed is False  # a read-back wrote nothing

    def test_the_refusal_is_greppable_and_names_the_door(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The message is the operator's whole instruction: what
        # happened, what is refused, and what lifts it -- the sentence's
        # own second half, because "how do I re-open the order layer?"
        # is the operator's next question.
        _breach(store.database_url, sender="supervisor/4711")
        with pytest.raises(RiskOrdersHaltedError) as refused:
            store.require_orders_allowed()
        message = str(refused.value)
        assert message.startswith(f"{ORDERS_HALTED_CODE}:")
        assert "11.0" in message
        assert "10.0" in message
        assert _iso(BREACHED) in message
        assert "supervisor/4711" in message
        assert "manual reset" in message

    def test_the_refusal_does_not_lift_by_itself(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The whole difference from feature 328's live reading, asserted
        # directly: three guard calls later, minutes of clock later, the
        # refusal stands exactly as it did -- no calendar, no clock, no
        # recovery in the day's figure lifts it, because "until a
        # manual reset" is the sentence's own clock.
        _breach(store.database_url)
        for _ in range(3):
            with pytest.raises(RiskOrdersHaltedError):
                store.require_orders_allowed()
        assert store.halted() is True
        assert _row_count(store.database_url) == 1

    def test_the_refusal_survives_a_restart_of_the_reading_process(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # A restarted order layer reads the same standing halt its
        # predecessor refused under: the state is the table's, not any
        # process's memory's -- the reason the halt is a row at all.
        _breach(store.database_url)
        restarted = RiskDailyLossHaltStore(store.database_url)
        assert restarted.halted() is True
        with pytest.raises(RiskOrdersHaltedError):
            restarted.require_orders_allowed()

    def test_the_guard_holds_no_memo_of_a_refusal_it_once_raised(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The state that would make the guard answer from memory,
        # asserted against the store's own surface: nothing but the URL
        # and this process's identity.
        _breach(store.database_url)
        with pytest.raises(RiskOrdersHaltedError):
            store.require_orders_allowed()
        assert set(vars(store)) == {"_database_url", "_process_id"}

    def test_the_one_bit_read_refuses_a_broken_table_too(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # `halted()` may not answer a state it cannot stand behind: a
        # `False` read off a broken table would be a clean bill nobody
        # could justify.
        _breach(store.database_url)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute(f"DROP INDEX {RISK_DAILY_LOSS_HALT_TABLE}_standing")
            connection.execute(
                f"INSERT INTO {RISK_DAILY_LOSS_HALT_TABLE} ("
                "daily_loss, daily_loss_limit, breached_at, "
                "supervisor_process_id"
                ") VALUES (99, 10, '2026-09-25T14:00:00+00:00', 'y/2')"
            )
        with pytest.raises(RiskDailyLossError):
            store.halted()

    def test_the_refusal_is_catchable_by_the_members_base(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # A caller catching the member's one vocabulary catches the
        # order layer's receipt along with the limit-keeper's faults.
        _breach(store.database_url)
        with pytest.raises(RiskError):
            store.require_orders_allowed()


class TestTheSiblings:
    def test_the_receipt_is_a_sibling_of_the_killed_and_stale_receipts(
        self,
    ) -> None:
        # Not a child of either, and neither a child of it: the kill is
        # a state that stands forever in this member, the staleness is
        # a live reading that stops being true by itself, and the daily
        # loss halt is the third kind -- standing, not liftable by
        # itself, liftable at one door.  Three facts, three classes,
        # one base to catch all three, because an operator paging on
        # each performs a different repair.
        assert not issubclass(RiskOrdersHaltedError, RiskOrdersKilledError)
        assert not issubclass(RiskOrdersKilledError, RiskOrdersHaltedError)
        assert not issubclass(RiskOrdersHaltedError, RiskOrdersStaleError)
        assert not issubclass(RiskOrdersStaleError, RiskOrdersHaltedError)
        assert issubclass(RiskOrdersHaltedError, RiskError)

    def test_a_hand_built_receipt_carries_no_halt(self) -> None:
        # The attribute is present and `None` on a hand-built error,
        # never absent: a caller reading `exc.halt` never attributes.
        error = RiskOrdersHaltedError("hand-built")
        assert error.halt is None

    def test_the_refusal_is_composed_by_one_function(self) -> None:
        # One spelling for the message, so the log line an operator
        # reads and the record the guard read say the same thing.
        halt = DailyLossHalt(
            sequence=1,
            loss=11.0,
            limit=LIMIT,
            breached_at=BREACHED,
            supervisor_process_id="supervisor/4711",
            reset_at=None,
            reset_by=None,
            changed=False,
        )
        error = orders_halted_error(halt)
        assert isinstance(error, RiskOrdersHaltedError)
        assert error.halt is halt
        assert halt.summary in str(error)

    def test_the_refusal_builder_refuses_anything_but_a_record(self) -> None:
        # An error built from anything else would be a refusal with no
        # breach behind it.
        with pytest.raises(RiskDailyLossError) as refused:
            orders_halted_error("halted")  # type: ignore[arg-type]
        assert DAILY_LOSS_CODE in str(refused.value)


# -- Until a manual reset ----------------------------------------------------------


class TestTheManualReset:
    def test_the_reset_closes_the_standing_halt(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        _breach(store.database_url)
        closed = store.reset(reset_at=RESET, reset_by="operator/7")
        assert closed.changed is True
        assert closed.sequence == 1
        assert closed.reset_at == RESET
        assert closed.reset_by == "operator/7"
        assert closed.standing is False

    def test_the_guard_passes_after_the_reset(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The sentence's own claim, end to end: refused under the
        # breach, passed after the manual reset -- and no other test in
        # this class means anything without this one.
        _breach(store.database_url)
        with pytest.raises(RiskOrdersHaltedError):
            store.require_orders_allowed()
        store.reset()
        store.require_orders_allowed()
        assert store.halted() is False
        assert store.standing() is None

    def test_the_breach_facts_survive_the_reset(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # Which loss broke which limit, when, as judged by whom: the
        # facts the refusal justified, still on the row the reset
        # closed -- because a record that rewrote them would disagree
        # with the halt it explained.
        _breach(store.database_url, sender="supervisor/4711")
        closed = store.reset(reset_at=RESET, reset_by="operator/7")
        assert closed.loss == 11.0
        assert closed.limit == LIMIT
        assert closed.breached_at == BREACHED
        assert closed.supervisor_process_id == "supervisor/4711"

    def test_the_default_reset_is_this_process_at_this_instant(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        before = datetime.now(UTC)
        _breach(store.database_url)
        closed = store.reset()
        after = datetime.now(UTC)
        assert closed.reset_by == store.process_id == process_identity()
        assert before <= closed.reset_at <= after
        assert closed.reset_at.tzinfo is not None

    def test_resetting_with_nothing_standing_is_refused(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # A caller that believes it re-opened the order layer must not
        # be told it did: a reset that closed nothing is the mirrored
        # soft failure of a halt that went nowhere.
        with pytest.raises(RiskDailyLossError) as refused:
            store.reset()
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert "nothing stands" in message

    def test_a_second_reset_is_refused_the_same_way(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        _breach(store.database_url)
        store.reset()
        with pytest.raises(RiskDailyLossError):
            store.reset()

    def test_a_new_breach_after_a_reset_stands_on_its_own_row(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The law is at most one *standing* halt, not at most one halt
        # ever: a deployment that breaches twice on two resets must
        # refuse orders the second time too, and the two episodes are
        # told apart by their numbers.
        _breach(store.database_url, moment=BREACHED)
        store.reset(reset_at=RESET, reset_by="operator/7")
        store.require_orders_allowed()

        second = _breach(store.database_url, loss=25.0, moment=LATER)
        assert second.sequence == 2
        assert second.changed is True
        assert second.loss == 25.0
        assert _row_count(store.database_url) == 2
        standing = store.standing()
        assert standing is not None
        assert standing.sequence == 2
        with pytest.raises(RiskOrdersHaltedError):
            store.require_orders_allowed()

        # And the second episode closes like the first: the reset door
        # is per-episode, not once-ever.
        closed_again = store.reset()
        assert closed_again.sequence == 2
        assert closed_again.changed is True
        store.require_orders_allowed()

    def test_the_sweep_tells_the_whole_story_oldest_first(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The reconciler's read: both episodes, the breach and the
        # reset of each, ordered by the breach's own moment.
        _breach(store.database_url, moment=BREACHED)
        store.reset(reset_at=RESET, reset_by="operator/7")
        _breach(store.database_url, loss=25.0, moment=LATER)
        halts = store.halts()
        assert [halt.sequence for halt in halts] == [1, 2]
        assert halts[0].reset_at == RESET and halts[0].reset_by == "operator/7"
        assert halts[1].standing is True
        assert all(halt.changed is False for halt in halts)

    def test_the_sweep_anchor_is_inclusive_at_the_exact_instant(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The workspace's window convention: a halt breached at exactly
        # the anchor instant is part of the story the anchor begins.
        _breach(store.database_url, moment=BREACHED)
        assert store.halts(since=BREACHED)[0].sequence == 1
        assert store.halts(since=BREACHED + timedelta(microseconds=1)) == ()

    def test_a_naive_anchor_is_refused(self, store: RiskDailyLossHaltStore) -> None:
        _breach(store.database_url)
        with pytest.raises(RiskDailyLossError):
            store.halts(since=BREACHED.replace(tzinfo=None))

    def test_first_reset_wins_and_the_loser_answers_the_winners_facts(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The race the reset door is built for: two operators reset
        # inside one window, and the write that lands second changes
        # nothing -- the halt closes once, at one moment, by one actor,
        # and the record says whose.  The interleaving is staged (the
        # pre-read returns the row as it stood; the winner's reset is a
        # real write on a real second store), because the window between
        # a read and an update is not otherwise enterable from one
        # process.
        _breach(store.database_url)
        winner = RiskDailyLossHaltStore(store.database_url)
        snapshot = winner.standing()
        assert snapshot is not None
        raw = (
            snapshot.sequence,
            snapshot.loss,
            snapshot.limit,
            _iso(snapshot.breached_at),
            snapshot.supervisor_process_id,
            None,
            None,
        )
        store._standing_row = (  # type: ignore[method-assign]
            lambda connection: (
                winner.reset(reset_at=LATER, reset_by="operator/9") and None or raw
            )
        )
        lost = store.reset(reset_at=RESET, reset_by="operator/2")
        assert lost.changed is False
        assert lost.sequence == 1
        assert lost.reset_at == LATER
        assert lost.reset_by == "operator/9"
        # The table holds one closed episode, in the winner's facts.
        closed = store.halts()
        assert len(closed) == 1
        assert closed[0].reset_by == "operator/9"


# -- The standing law is the schema's ----------------------------------------------


class TestTheStandingLaw:
    def test_the_table_refuses_a_second_un_reset_row(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The at-most-one-standing law lives in a partial unique index,
        # not in this module's discipline: even a raw INSERT from
        # another tool cannot mint a second standing halt for an order
        # layer to arbitrate.
        _breach(store.database_url)
        with (
            closing(sqlite3.connect(store.path)) as connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                f"INSERT INTO {RISK_DAILY_LOSS_HALT_TABLE} ("
                "daily_loss, daily_loss_limit, breached_at, "
                "supervisor_process_id"
                ") VALUES (99, 10, '2026-09-25T14:00:00+00:00', 'y/2')"
            )
            connection.commit()

    def test_the_partition_re_opens_after_a_reset(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The other side of the same law: the index keys only the
        # un-reset partition, so a closed episode leaves room for the
        # next breach -- asserted with the driver directly, because
        # this is the schema's promise, not the value layer's.
        _breach(store.database_url)
        store.reset()
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute(
                f"INSERT INTO {RISK_DAILY_LOSS_HALT_TABLE} ("
                "daily_loss, daily_loss_limit, breached_at, "
                "supervisor_process_id"
                ") VALUES (99, 10, '2026-09-25T14:00:00+00:00', 'y/2')"
            )

    def test_the_table_refuses_a_row_that_did_not_breach(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The belt under the value layer's re-derivation: a row whose
        # own figures deny its halt cannot land by INSERT.
        store.ensure_schema()
        with (
            closing(sqlite3.connect(store.path)) as connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                f"INSERT INTO {RISK_DAILY_LOSS_HALT_TABLE} ("
                "daily_loss, daily_loss_limit, breached_at, "
                "supervisor_process_id"
                ") VALUES (3, 10, '2026-09-25T14:00:00+00:00', 'y/2')"
            )

    @pytest.mark.parametrize(
        ("loss", "limit"),
        [(11.0, 0.0), (-5.0, 10.0)],
    )
    def test_the_table_refuses_a_limit_that_is_no_band_and_a_negative_loss(
        self, store: RiskDailyLossHaltStore, loss: float, limit: float
    ) -> None:
        store.ensure_schema()
        with (
            closing(sqlite3.connect(store.path)) as connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                f"INSERT INTO {RISK_DAILY_LOSS_HALT_TABLE} ("
                "daily_loss, daily_loss_limit, breached_at, "
                "supervisor_process_id"
                f") VALUES ({loss}, {limit}, "
                "'2026-09-25T14:00:00+00:00', 'y/2')"
            )

    def test_the_table_refuses_half_a_reset(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        _breach(store.database_url)
        with (
            closing(sqlite3.connect(store.path)) as connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                f"UPDATE {RISK_DAILY_LOSS_HALT_TABLE} "
                "SET reset_at = '2026-09-25T15:00:00+00:00'"
            )


class TestARowEditedOutsideThePackage:
    def test_a_loss_edited_inside_its_own_limit_is_refused_on_read(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The one tamper that would re-open the order layer: the loss
        # edited down to sit inside the limit it broke.  The value
        # layer re-derives the breach from the row's own two figures,
        # so the row fails to reconstruct instead of standing as a
        # quieter halt -- staged with the CHECKs switched off, because
        # the schema would otherwise refuse the edit itself.
        _breach(store.database_url)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                f"UPDATE {RISK_DAILY_LOSS_HALT_TABLE} SET daily_loss = 3.0"
            )
        with pytest.raises(RiskDailyLossError) as refused:
            store.standing()
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert "3.0" in message
        assert "halt 1" in message  # the refusal names the row to repair

    def test_a_row_no_halt_can_be_never_answers_a_clean_bill(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The safe direction of the refusal, on the one-bit read too: a
        # broken row is a fault to repair, not a halt and not an
        # all-clear.
        _breach(store.database_url)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                f"UPDATE {RISK_DAILY_LOSS_HALT_TABLE} SET daily_loss = 3.0"
            )
        with pytest.raises(RiskDailyLossError):
            store.halted()

    def test_a_row_of_an_unparseable_moment_is_refused_on_read(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        _breach(store.database_url)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute(
                f"UPDATE {RISK_DAILY_LOSS_HALT_TABLE} SET breached_at = 'not a moment'"
            )
        with pytest.raises(RiskDailyLossError) as refused:
            store.standing()
        assert "not a moment" in str(refused.value)

    def test_a_row_of_no_sender_is_refused_on_read(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        _breach(store.database_url)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute(
                f"UPDATE {RISK_DAILY_LOSS_HALT_TABLE} SET supervisor_process_id = ' '"
            )
        with pytest.raises(RiskDailyLossError):
            store.standing()

    def test_half_a_reset_is_refused_by_the_sweep(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The pairing the schema's CHECK states and the value layer
        # re-states: a row carrying a reset moment with no actor (or
        # the other way round) is a halt an operator cannot read, and
        # the sweep that reconstructs every row refuses it by name.
        _breach(store.database_url)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                f"UPDATE {RISK_DAILY_LOSS_HALT_TABLE} "
                "SET reset_at = '2026-09-25T15:00:00+00:00'"
            )
        with pytest.raises(RiskDailyLossError) as refused:
            store.halts()
        assert "reset" in str(refused.value)

    def test_two_halts_standing_where_the_law_allows_one_are_refused_by_count(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The belt unbuckled by another tool: the index dropped, a
        # second row inserted past it.  Every face of the store refuses
        # the state by name -- the bootstrap cannot re-create the law
        # over a table that breaks it -- because whichever row a reader
        # picked would be a refusal the other did not justify.
        _breach(store.database_url)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute(f"DROP INDEX {RISK_DAILY_LOSS_HALT_TABLE}_standing")
            connection.execute(
                f"INSERT INTO {RISK_DAILY_LOSS_HALT_TABLE} ("
                "daily_loss, daily_loss_limit, breached_at, "
                "supervisor_process_id"
                ") VALUES (99, 10, '2026-09-25T14:00:00+00:00', 'y/2')"
            )
        for act in (
            store.standing,
            store.halted,
            store.require_orders_allowed,
            store.halts,
            store.ensure_schema,
            store.reset,
        ):
            with pytest.raises(RiskDailyLossError) as refused:
                act()
            assert "2 un-reset" in str(refused.value)


# -- Neither kill nor flatten rides the breach -------------------------------------


class TestTheChannelIsNotTouched:
    def test_a_breach_sends_no_kill(self, store: RiskDailyLossHaltStore) -> None:
        # The refusal must not travel through feature 322's monotone
        # channel: a kill never lifts, and this halt must -- so an
        # operator who read the refusal as a kill and waited for a door
        # to clear a state that was never set would be waiting forever.
        _breach(store.database_url)
        assert _kills(store.database_url) == 0
        assert RiskKillSwitch(store.database_url).standing() is None

    def test_the_refusal_sends_no_kill_either(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        _breach(store.database_url)
        with pytest.raises(RiskOrdersHaltedError):
            store.require_orders_allowed()
        assert _kills(store.database_url) == 0

    def test_the_reset_does_not_touch_a_standing_kill(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The mirrored boundary, and the one that keeps the member's
        # laws from bleeding into each other: the reset door lifts
        # exactly the daily loss halt.  A kill that stood beside it
        # still stands after the reset -- the kill is monotone by its
        # own pinned law, and a manual reset that also cleared it would
        # make "has the order layer been told to stop since T?"
        # unanswerable at exactly the moment feature 331's
        # reconciliation asks it.
        RiskKillSwitch(store.database_url).send(sent_at=BREACHED)
        _breach(store.database_url)
        with pytest.raises(RiskOrdersKilledError):
            RiskKillSwitch(store.database_url).require_orders_allowed()
        store.reset()
        with pytest.raises(RiskOrdersKilledError):
            RiskKillSwitch(store.database_url).require_orders_allowed()
        assert RiskKillSwitch(store.database_url).standing() is not None

    def test_a_standing_kill_does_not_halt_this_guard(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # The independence runs both ways: the daily-loss guard answers
        # its own condition and only it -- a kill is the kill guard's
        # question, and a caller composing both consults both.
        RiskKillSwitch(store.database_url).send(sent_at=BREACHED)
        store.require_orders_allowed()

    def test_the_store_holds_no_switch_and_no_flattener(
        self, store: RiskDailyLossHaltStore
    ) -> None:
        # Nothing in this feature's object graph reaches the channel or
        # the engine: the halt is a row, the guard is a read, and the
        # reset is one UPDATE.
        _breach(store.database_url)
        assert set(vars(store)) == {"_database_url", "_process_id"}

    def test_the_module_exposes_no_verb_of_the_channel_or_the_flatten(
        self,
    ) -> None:
        # §13.3's row for this trigger reads *Flatten, halt until manual
        # reset*, and the flatten half is the composed door's act
        # (feature 323's, driven from a breach by the end-to-end story)
        # -- not the limit-keeper's.  The absence is the assertion: a
        # module that sold the book would have skipped a row of the
        # trigger table on its own authority.
        import risk.daily_loss as module

        forbidden = ("kill", "flatten", "close", "cancel", "liquidate", "drain")
        for name in module.__all__:
            assert not any(word in name.lower() for word in forbidden), name

    def test_the_store_exposes_no_door_but_the_reset(
        self,
    ) -> None:
        # And the reset is the one liftable surface: no clear, no
        # resume, no retract -- the vocabulary of lifting states that
        # are not this feature's to lift.
        forbidden = {
            "clear",
            "resume",
            "unsend",
            "retract",
            "recall",
            "delete",
            "pop",
            "remove",
        }
        public = {
            name
            for name in dir(RiskDailyLossHaltStore)
            if not name.startswith("_")
            and callable(getattr(RiskDailyLossHaltStore, name))
        }
        assert not (public & forbidden), public & forbidden

    def test_no_halt_event_is_written(self, store: RiskDailyLossHaltStore) -> None:
        # Feature 331 owns the event ledger, and its table is created
        # only by its own store: a breach, a refusal and a reset all
        # pass, and the ledger this feature deliberately does not write
        # does not even exist to be read.
        _breach(store.database_url)
        with pytest.raises(RiskOrdersHaltedError):
            store.require_orders_allowed()
        store.reset()
        assert "risk_halt_event" not in _tables(store.database_url)


# -- The module-level spellings ----------------------------------------------------


class TestTheModuleLevelSpellings:
    def test_a_breach_through_the_environment_halts(
        self, test_database_url: str
    ) -> None:
        halt = halt_on_daily_loss(
            daily_loss=11.0, daily_loss_limit=LIMIT, breached_at=BREACHED
        )
        assert halt is not None
        assert halt.changed is True
        standing = RiskDailyLossHaltStore(test_database_url).standing()
        assert standing is not None
        assert standing.breached_at == BREACHED

    def test_a_day_inside_its_limit_needs_no_store_at_all(self) -> None:
        # Judged before the store is demanded: a deployment that names
        # no database still gets its answer for the day it asked about.
        assert (
            halt_on_daily_loss(daily_loss=5.0, daily_loss_limit=LIMIT, env={}) is None
        )

    def test_a_breach_with_no_store_named_is_refused_by_name(self) -> None:
        # The one direction this feature must not fail softly in: a
        # halt that silently went nowhere would leave an order layer
        # believing itself stopped while it traded.
        with pytest.raises(RiskDailyLossError) as refused:
            halt_on_daily_loss(daily_loss=11.0, daily_loss_limit=LIMIT, env={})
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert DATABASE_URL_ENV in message

    def test_an_unnamed_store_with_the_day_inside_its_limit_is_not_a_refusal(
        self,
    ) -> None:
        # The judge runs before the store is demanded, so the refusal
        # is about the *breach*, not about the deployment: an
        # unconfigured deployment with a quiet day is a quiet day.
        assert (
            halt_on_daily_loss(daily_loss=5.0, daily_loss_limit=LIMIT, env={}) is None
        )

    def test_the_guard_passes_vacuously_without_a_store(self) -> None:
        # A deployment with no relational store has no halt standing in
        # one: distinct from a checked table holding no halt, and
        # deliberately not an exception -- the "no store, no status"
        # stance the kill channel's guard takes too.
        require_within_daily_loss_limit(env={})

    def test_the_guard_refuses_through_the_named_store(
        self, test_database_url: str
    ) -> None:
        halt_on_daily_loss(
            daily_loss=11.0, daily_loss_limit=LIMIT, breached_at=BREACHED
        )
        with pytest.raises(RiskOrdersHaltedError):
            require_within_daily_loss_limit()

    def test_a_reset_with_no_store_named_is_refused_by_name(self) -> None:
        # The mirrored direction: a reset that silently went nowhere
        # would leave an operator believing the order layer open while
        # every submission path still refused.
        with pytest.raises(RiskDailyLossError) as refused:
            manual_reset(env={})
        message = str(refused.value)
        assert DAILY_LOSS_CODE in message
        assert DATABASE_URL_ENV in message

    def test_a_reset_through_the_environment_closes(
        self, test_database_url: str
    ) -> None:
        halt_on_daily_loss(
            daily_loss=11.0, daily_loss_limit=LIMIT, breached_at=BREACHED
        )
        closed = manual_reset(reset_at=RESET, reset_by="operator/7")
        assert closed.changed is True
        require_within_daily_loss_limit()

    def test_the_sweep_answers_the_empty_truth_without_a_store(self) -> None:
        # Halting refuses without a store, so a deployment that names
        # none holds no halts to reconcile -- the empty answer is the
        # truthful one, not a clean record.
        assert recorded_daily_loss_halts(env={}) == ()

    def test_the_sweep_reads_through_the_named_store(
        self, test_database_url: str
    ) -> None:
        halt_on_daily_loss(
            daily_loss=11.0, daily_loss_limit=LIMIT, breached_at=BREACHED
        )
        halts = recorded_daily_loss_halts()
        assert len(halts) == 1
        assert halts[0].breached_at == BREACHED

    def test_the_explicit_url_wins_over_the_environment(
        self, test_database_url: str, tmp_path: Path
    ) -> None:
        # A caller that names a store is ruling out the environment's,
        # not consulting it second.
        halt_on_daily_loss(
            daily_loss=11.0,
            daily_loss_limit=LIMIT,
            database_url=f"sqlite:///{tmp_path / 'named.db'}",
        )
        assert recorded_daily_loss_halts() == ()  # the environment's store: empty
        assert RiskDailyLossHaltStore(test_database_url).standing() is None

    def test_resolve_answers_none_when_nothing_names_a_store(self) -> None:
        assert RiskDailyLossHaltStore.resolve(env={}) is None
        assert RiskDailyLossHaltStore.resolve(env={DATABASE_URL_ENV: "   "}) is None

    def test_resolve_reads_the_environment_it_is_given(self) -> None:
        store = RiskDailyLossHaltStore.resolve(
            env={DATABASE_URL_ENV: "sqlite:///given.db"}
        )
        assert store is not None
        assert store.database_url == "sqlite:///given.db"

    def test_the_member_re_exports_the_spellings(self) -> None:
        # The package namespace is the member's one public surface, and
        # this feature's nouns answer from it like the others' do.
        import risk as member

        for name in (
            "DailyLossHalt",
            "RiskDailyLossError",
            "RiskDailyLossHaltStore",
            "RiskOrdersHaltedError",
            "DAILY_LOSS_CODE",
            "ORDERS_HALTED_CODE",
            "RISK_DAILY_LOSS_HALT_TABLE",
            "halt_on_daily_loss",
            "manual_reset",
            "orders_halted_error",
            "recorded_daily_loss_halts",
            "require_within_daily_loss_limit",
        ):
            assert hasattr(member, name), name
            assert name in member.__all__, name

    def test_the_module_registers_nothing(self) -> None:
        # Feature 325 registers nothing with the application factory:
        # the supervisor that judges the day and the order layer that
        # refuses under the halt reach the table from ``DATABASE_URL``
        # without composing anything, and an operator's reset must not
        # be an application's act.  The member's four pinned builders
        # are unchanged (its component suite states the count).
        import risk.daily_loss as module

        assert not [name for name in dir(module) if name.startswith("build_")]
        assert "register" not in dir(module)


# -- The store's address -----------------------------------------------------------


class TestTheStoreAddress:
    def test_a_non_sqlite_scheme_is_refused_by_name(
        self, test_database_url: str
    ) -> None:
        store = RiskDailyLossHaltStore("postgres://localhost/risk")
        with pytest.raises(RiskStoreError, match="postgres"):
            store.halt_on_loss(daily_loss=11.0, daily_loss_limit=LIMIT)

    def test_an_in_memory_database_is_refused_by_name(self) -> None:
        # An in-memory table would die with the connection that opened
        # it, and the halt would vanish with the supervisor's process
        # -- re-opening an order layer that was never re-opened.
        store = RiskDailyLossHaltStore("sqlite:///:memory:")
        with pytest.raises(RiskStoreError, match="in-memory"):
            store.halt_on_loss(daily_loss=11.0, daily_loss_limit=LIMIT)

    def test_a_host_on_the_sqlite_url_is_refused_by_name(self) -> None:
        store = RiskDailyLossHaltStore("sqlite://risk-host/risk.db")
        with pytest.raises(RiskStoreError, match="risk-host"):
            store.halt_on_loss(daily_loss=11.0, daily_loss_limit=LIMIT)

    def test_an_empty_url_is_refused_at_construction(self) -> None:
        with pytest.raises(RiskStoreError):
            RiskDailyLossHaltStore("   ")


# -- Across processes --------------------------------------------------------------


class TestAcrossProcesses:
    def test_a_halt_a_second_interpreter_opened_refuses_here_and_its_reset_passes(
        self, tmp_path: Path
    ) -> None:
        # The deployment the category's own first clause names: a
        # supervisor in its own process judges the day, and this
        # process's order layer refuses under the row it wrote -- then
        # an operator in that process closes it, and this process's
        # guard passes.  Two directions, two interpreters, one table.
        url = f"sqlite:///{tmp_path / 'cross-process.db'}"
        store = RiskDailyLossHaltStore(url)
        ours = process_identity()

        script = """
import sys
from risk.daily_loss import RiskDailyLossHaltStore
from risk.errors import RiskOrdersHaltedError

store = RiskDailyLossHaltStore(sys.argv[1])
halt = store.halt_on_loss(
    daily_loss=11.0,
    daily_loss_limit=10.0,
    supervisor_process_id='supervisor/4711',
)
print(halt.supervisor_process_id, halt.changed)
try:
    store.require_orders_allowed()
except RiskOrdersHaltedError as refused:
    print('refused', refused.halt.sequence)
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
            [sys.executable, "-c", script, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        theirs, changed, refused, sequence = result.stdout.strip().split()
        assert theirs == "supervisor/4711"
        assert changed == "True"
        assert refused == "refused"
        assert sequence == "1"
        assert theirs != ours

        # This process refuses under that process's halt, without ever
        # having spoken to it.
        standing = store.standing()
        assert standing is not None
        assert standing.supervisor_process_id == "supervisor/4711"
        assert standing.breached_at.tzinfo is not None
        with pytest.raises(RiskOrdersHaltedError) as raised:
            store.require_orders_allowed()
        assert raised.value.halt is not None
        assert raised.value.halt.supervisor_process_id == "supervisor/4711"

        # And that process's reset is this process's open door.
        reset_script = """
import sys
from risk.daily_loss import manual_reset

closed = manual_reset(database_url=sys.argv[1], reset_by='operator/9')
print(closed.changed, closed.reset_by)
"""
        result = subprocess.run(
            [sys.executable, "-c", reset_script, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        changed, who = result.stdout.strip().split()
        assert changed == "True"
        assert who == "operator/9"

        store.require_orders_allowed()
        assert store.standing() is None
        assert _kills(url) == 0
