"""Feature 337's act: forward IC retention, live divided by backtest.

app_spec.xml, "Forward-Test Tracking", feature 337: *System computes forward
information coefficient retention as live divided by backtest, which returns
the ratio per signal.*  These tests pin the four halves of that sentence:

* **computes** — the ratio is arithmetic this member performs.  No caller may
  state it: :class:`~forward.retention.IcRetention` re-derives the quotient in
  ``__post_init__`` and refuses an instance whose own operands do not produce
  its ratio, so a fabricated retention cannot reach §C10's demotion line;
* **live divided by backtest** — the live IC is the *mean* of the record's
  observed ``live_ic`` rows, with the day count beside it as evidence, and the
  backtest IC is the figure the caller landed once on the opening row.  Both
  are read; neither is a parameter of
  :func:`~forward.retention.forward_ic_retention`.  A **zero** backtest is
  refused (the quotient §11 states has no value) and the ratio carries **no
  bound** — above one and below zero are both answers, which is exactly the
  fact the scoring member cites when it declines to charge on this ratio;
* **returns the ratio** — the answer is an :class:`IcRetention` carrying its
  own operands, so a reader of the retention also holds the evidence for it;
* **per signal** — keyed by ``node_id``, one record, one answer.

The two laws that make the ratio trustworthy are pinned here too: the backtest
figure lands on the record's **opening row** and nowhere else, and the member
authors **no DDL** (``backtest_ic`` is ``0108``'s own column).
"""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import forward.observation
import forward.reconciliation
import forward.record
import forward.retention
import pytest
from conftest import (
    CAMPAIGN_ID,
    CRITERIA_DOCUMENT,
    DECIDED_AT,
    EPOCH_ID,
    FORWARD_DAYS,
    NODE_ID,
    REGISTERED_AT,
    code_of,
    promote_signal,
)
from forward import (
    BACKTEST_IC_COLUMN,
    DATABASE_URL_ENV,
    FORWARD_PROMOTION_ERROR_CODE,
    FORWARD_RECORD_TABLE,
    FORWARD_RETENTION_ERROR_CODE,
    FORWARD_RETENTION_SEAM,
    RETENTION_RATIO_KEY,
    ForwardIcRetentions,
    ForwardRecord,
    ForwardRecordError,
    ForwardRecords,
    ForwardRetentionError,
    ForwardStoreError,
    IcRetention,
    forward_ic_retention,
)
from forward.observation import ForwardObservations

#: The promotion boundary this suite is measured against, restated so a
#: conftest change that moved ``DECIDED_AT`` fails at the first fixture rather
#: than somewhere inside a refusal message.
DECIDED = dt.datetime.fromisoformat(DECIDED_AT)

#: The boundary day, and the first day an observation may honestly name — the
#: same two constants the observation suite pins, repeated rather than imported
#: because a test that imported them would follow a conftest change silently
#: instead of failing on it.
BOUNDARY_DAY = dt.date(2026, 3, 1)
FIRST_DAY = dt.date(2026, 3, 2)

#: Three observed days and the coefficients measured on them.  ``0.12``,
#: ``0.09`` and ``0.06`` mean exactly ``0.09``, and against a ``0.18`` backtest
#: give a retention of exactly ``0.5`` — figures a test can compare without an
#: epsilon hiding a real arithmetic disagreement.
DAYS = (dt.date(2026, 3, 2), dt.date(2026, 3, 3), dt.date(2026, 3, 4))
COEFFICIENTS = (0.12, 0.09, 0.06)
LIVE_MEAN = 0.09
BACKTEST = 0.18
RETENTION = 0.5


@pytest.fixture
def retentions(promoted_signal: ForwardRecords) -> ForwardIcRetentions:
    """The retention store over the record's own store — 337's seam.

    Built with :meth:`ForwardIcRetentions.over` off the very store the record
    was opened through, so the reader and the opener point at one database by
    construction — the shape a deployment reaches when it asks the composed
    ``forward`` component for the act.
    """
    return ForwardIcRetentions.over(promoted_signal)


@pytest.fixture
def observed_record(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> ForwardRecord:
    """One signal's record with the three days above measured onto it.

    The observations land through feature 333's own act rather than by hand,
    so the ``live_ic`` figures the ratio averages are the ones the member
    actually persists, and the boundary this suite divides across is the
    boundary the member wrote.
    """
    assert opened_record.promoted_at == DECIDED
    assert opened_record.observed_on == BOUNDARY_DAY
    observations = ForwardObservations.over(promoted_signal)
    for day, coefficient in zip(DAYS, COEFFICIENTS, strict=True):
        observations.append_observation(
            NODE_ID, observed_on=day, live_ic=coefficient, forward_days=FORWARD_DAYS
        )
    return opened_record


# -- The feature's sentence ---------------------------------------------------


def test_the_ratio_is_the_mean_live_ic_divided_by_the_backtest(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """The sentence, run once: mean of the observed rows ÷ the backtest.

    The live side is a **mean and not a sum**: three days at ``0.12``, ``0.09``
    and ``0.06`` are a live IC of ``0.09``, and the ratio against a ``0.18``
    backtest is ``0.5``.  A store that summed would answer ``1.5`` — the same
    figure a band of perfect retention produces — so the arithmetic is pinned
    exactly rather than approximately.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    answer = retentions.retention(NODE_ID)

    assert answer.live_ic == pytest.approx(LIVE_MEAN, abs=1e-12)
    assert answer.backtest_ic == BACKTEST
    assert answer.ratio == pytest.approx(RETENTION, abs=1e-12)
    assert answer.ratio == answer.live_ic / answer.backtest_ic


def test_the_answer_carries_its_own_evidence(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """``observed_days`` and the last day travel with the figure.

    §11's criterion is stated *"at 90 days"*, so a ratio over three days and a
    ratio over ninety are the same number and are not the same fact.  The count
    is how many rows carried a measurement and the day is the latest of them —
    the two facts a demotion decision needs, neither of which is recoverable
    from the ratio.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    answer = retentions.retention(NODE_ID)

    assert answer.node_id == NODE_ID
    assert answer.promoted_at == DECIDED
    assert answer.observed_days == len(DAYS)
    assert answer.observed_on == max(DAYS)


def test_a_day_without_a_measurement_is_not_averaged_in_as_zero(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """A missed day is an absence, not a measured zero.

    The record's rows run one per day and a row whose ``live_ic`` is null is a
    day the observation job did not reach.  Averaging nulls in as zeroes would
    let a signal with three measurements and eighty-seven missed days read as a
    signal that collapsed — a fabrication of exactly the kind this table's
    append-only law guards against.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    answer = retentions.retention(NODE_ID)

    assert answer.observed_days == len(DAYS)
    assert answer.live_ic == pytest.approx(LIVE_MEAN, abs=1e-12)


def _promote_second_signal(store: ForwardRecords, node_id: str) -> None:
    """A second signal's closed promotion in the *same* database.

    :func:`conftest.promote_signal` brings the database up as well as filing
    the row, and its ``epoch_ledger`` insert is unconditional — so a second
    call against a database that already holds the epoch collides on the
    primary key.  This helper does the part that is per-signal: the node row
    and the two promotion acts, with the same fixed instant the fixture used,
    so both signals share one boundary and the ratios below differ only by
    their coefficients.
    """
    from promotion import PreRegistrations, PromotionCriteria
    from promotion.decision import PromotionDecisions

    registrations = PreRegistrations(store.database_url)
    connection = registrations._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, ?)",
                (node_id, CAMPAIGN_ID, "macro", 1),
            )
    finally:
        connection.close()
    registrations.pre_register(
        node_id,
        EPOCH_ID,
        PromotionCriteria(**CRITERIA_DOCUMENT),
        clock=lambda: dt.datetime.fromisoformat(REGISTERED_AT),
    )
    PromotionDecisions(store.database_url).record_decision(node_id, decided_at=DECIDED)


def test_the_ratio_is_per_signal(store: ForwardRecords) -> None:
    """Two signals in one database get two ratios, keyed by ``node_id``.

    The feature's last clause, and the reason the store is keyed by the node
    rather than answering over the table: a book-level mean of every signal's
    coefficient would be a figure §11's criterion never asked for.
    """
    second = "33333333-3333-4333-8333-333333333333"
    promote_signal(store.database_url)
    store.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    _promote_second_signal(store, second)
    store.open_record(second, forward_days=FORWARD_DAYS)
    observations = ForwardObservations.over(store)
    observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.12, forward_days=FORWARD_DAYS
    )
    observations.append_observation(
        second, observed_on=FIRST_DAY, live_ic=0.03, forward_days=FORWARD_DAYS
    )
    retentions = ForwardIcRetentions.over(store)
    retentions.record_backtest_ic(NODE_ID, backtest_ic=0.24)
    retentions.record_backtest_ic(second, backtest_ic=0.12)

    assert retentions.retention(NODE_ID).ratio == pytest.approx(0.5, abs=1e-12)
    assert retentions.retention(second).ratio == pytest.approx(0.25, abs=1e-12)


# -- No bound: the load-bearing absence ---------------------------------------


def test_a_ratio_above_one_is_answered_not_clamped(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """Over-delivery is the interesting case, not a fault.

    A live IC larger than the backtest is a signal that did better out of
    sample than the backtest predicted — ``0.09 / 0.045`` is ``2.0`` — and
    :mod:`scoring._divergence` declines to charge on this ratio for exactly the
    reason a clamp would be wrong: it *"reads a forward IC twice the backtest
    as a number above one rather than as the same-sized gap it is"*.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=0.045)
    answer = retentions.retention(NODE_ID)

    assert answer.ratio == pytest.approx(2.0, abs=1e-12)
    assert answer.ratio > 1.0


def test_a_negative_ratio_is_answered_not_clamped(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """An inverted live IC is a larger failure than one that fell to zero.

    Answering ``0.0`` for it would leave §C10's 40% line unable to tell the two
    apart: both would read as equally dead, while only one of them is a signal
    that is still measuring the thing it was promoted for.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=-0.18)
    answer = retentions.retention(NODE_ID)

    assert answer.ratio == pytest.approx(-0.5, abs=1e-12)
    assert answer.ratio < 0.0


def test_the_ratio_validator_imposes_no_interval() -> None:
    """Feature 337 bounds no quotient, and says so in code.

    The module's own vocabulary is checked rather than its prose: the *ratio*
    validator must contain no comparison at all, because the ratio is a
    quotient of two coefficients and lives on its own scale.  The constant
    ``LIVE_IC_BOUND`` is imported and used, but only in
    :func:`forward.retention._validated_backtest_ic` — one operand's own
    domain — and never against the quotient.
    """
    source = code_of(forward.retention)
    assert "LIVE_IC_BOUND" in source
    body = source.split("def _validated_ratio")[1].split("\ndef ")[0]
    assert "LIVE_IC_BOUND" not in body
    assert "<=" not in body
    assert ">=" not in body


def test_a_ratio_of_exactly_one_is_answered(retentions: ForwardIcRetentions) -> None:
    """Parity — §11's line — is a value, not an edge case to refuse."""
    answer = IcRetention(
        node_id=NODE_ID,
        promoted_at=DECIDED,
        observed_on=FIRST_DAY,
        observed_days=1,
        live_ic=BACKTEST,
        backtest_ic=BACKTEST,
        ratio=1.0,
    )

    assert answer.ratio == 1.0


# -- The refusals -------------------------------------------------------------


def test_a_zero_backtest_is_stored_and_the_division_refused(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """Zero is well-formed; the quotient off it is not — and neither is invented.

    The figure itself is a perfectly good information coefficient: it is what a
    signal with no measured in-sample edge has, and the record keeps it.  The
    *division* has no value, and the two silent answers are both fabrications —
    ``inf`` is a division that did not happen, and ``0.0`` reads as a signal
    that kept none of an edge nobody measured.  :mod:`scoring._divergence`
    declines to charge on this ratio on the same ground: it *"is undefined at
    zero backtest IC"*.
    """
    record, created = retentions.record_backtest_ic(NODE_ID, backtest_ic=0.0)

    assert created is True
    assert record.backtest_ic == 0.0

    with pytest.raises(ForwardRetentionError) as refusal:
        retentions.retention(NODE_ID)
    message = str(refusal.value)
    assert message.startswith(FORWARD_RETENTION_ERROR_CODE)
    assert "undefined" in message
    assert "infinity" in message


def test_a_signal_with_no_record_is_refused_by_name(
    retentions: ForwardIcRetentions, promoted_signal: ForwardRecords
) -> None:
    """The coefficient needs the record whose column it lands in.

    A store that opened a record silently to hold the figure would fabricate
    the boundary it failed to read — the same fabrication features 332 and 333
    both refuse, refused here on the third column.  Both acts refuse, because
    both need the record: one to amend it, one to read it.
    """
    with promoted_signal._connect() as probe:
        rows = probe.execute(
            f"SELECT 1 FROM {FORWARD_RECORD_TABLE} WHERE node_id = ?", (NODE_ID,)
        ).fetchall()
    assert rows == []

    for act in (
        lambda: retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST),
        lambda: retentions.retention(NODE_ID),
    ):
        with pytest.raises(ForwardRetentionError) as refusal:
            act()
        message = str(refusal.value)
        assert message.startswith(FORWARD_RETENTION_ERROR_CODE)
        assert "POST /forward/promote" in message


def test_an_unobserved_signal_is_refused_rather_than_zeroed(
    retentions: ForwardIcRetentions, opened_record: ForwardRecord
) -> None:
    """A record with no measurement is not a signal that kept nothing.

    A live IC of zero is §C10's demotion candidate; an unrun job is not, and
    the two must not read alike in front of a demotion line.  Answering zero
    would let a signal promoted this morning be demoted by lunchtime.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)

    with pytest.raises(ForwardRetentionError) as refusal:
        retentions.retention(NODE_ID)
    message = str(refusal.value)
    assert message.startswith(FORWARD_RETENTION_ERROR_CODE)
    assert "live_ic" in message
    assert "feature 333" in message


def test_an_unlanded_backtest_is_refused_by_name(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """The column is nullable by ``0108``'s shape, and its null is a state.

    Feature 332 opens the record and knows nothing about the backtest; this
    feature fills it.  Neither silent reading is honest — zero would refuse as
    undefined a signal whose figure has merely not arrived, and the live IC
    would answer a ratio of one for every unmeasured signal, handing §11's
    criterion its best possible value.
    """
    with pytest.raises(ForwardRetentionError) as refusal:
        retentions.retention(NODE_ID)
    message = str(refusal.value)
    assert message.startswith(FORWARD_RETENTION_ERROR_CODE)
    assert "no divisor" in message
    assert "record_backtest_ic" in message


def test_a_second_disagreeing_backtest_is_refused(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """Two claims about one signal's backtest: the store refuses to choose.

    Last-wins would move the baseline §11's criterion divides by, so a signal
    could be demoted — or spared — by a figure that arrived after the decision.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)

    with pytest.raises(ForwardRetentionError) as refusal:
        retentions.record_backtest_ic(NODE_ID, backtest_ic=0.24)
    message = str(refusal.value)
    assert message.startswith(FORWARD_RETENTION_ERROR_CODE)
    assert "one backtest" in message


@pytest.mark.parametrize(
    "bad",
    [True, False, None, "0.18", [0.18], 1.5, -1.5, float("nan"), float("inf")],
    ids=[
        "true",
        "false",
        "none",
        "text",
        "sequence",
        "above-one",
        "below-minus-one",
        "nan",
        "infinity",
    ],
)
def test_a_malformed_backtest_is_refused_before_any_io(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord, bad: object
) -> None:
    """``bool`` first, then the interval, then finiteness — and never a clamp.

    ``True`` is ``1``, and a flag where a correlation belongs would persist a
    perfect coefficient nobody measured.  A figure outside ``[−1, 1]`` is not a
    large IC but a number that has stopped being one, and the likeliest things
    wearing its name are a z-score, a hit rate or an information ratio.
    """
    with pytest.raises(ForwardRetentionError) as refusal:
        retentions.record_backtest_ic(NODE_ID, backtest_ic=bad)

    assert str(refusal.value).startswith(FORWARD_RETENTION_ERROR_CODE)


def test_a_malformed_identity_is_the_record_contracts_refusal(
    retentions: ForwardIcRetentions,
) -> None:
    """The node is validated in the record's own vocabulary, not this one.

    The identity validator is feature 332's, imported rather than restated, so
    its refusals arrive as :class:`~forward.errors.ForwardRecordError` — the
    row contract's class — even on this feature's act.  That is the right
    class and the right repair: the node is the one field this act shares with
    the record, a malformed one is a caller bug rather than a state of the
    store, and both classes descend from :class:`~forward.errors.ForwardError`
    so a caller's single ``except`` still catches everything this member
    raises.
    """
    for bad in (None, "", 7, "not-a-uuid"):
        with pytest.raises(ForwardRecordError) as refusal:
            retentions.record_backtest_ic(bad, backtest_ic=BACKTEST)
        assert "must be a UUID" in str(refusal.value)
        assert "feature 332" in str(refusal.value)

    assert issubclass(ForwardRetentionError, forward.record.ForwardError)
    assert issubclass(ForwardRecordError, forward.record.ForwardError)
    assert not issubclass(ForwardRetentionError, ForwardRecordError)


def test_a_canonical_uuid_spelling_is_accepted(retentions: ForwardIcRetentions) -> None:
    """The identity is normalised the way the record normalises it.

    A UUID object, an unhyphenated string and an uppercase spelling all name
    one signal; the store reads the record by the canonical form the table
    stores.
    """
    assert forward.record._validated_uuid(uuid.UUID(NODE_ID), "node_id") == NODE_ID
    assert (
        forward.record._validated_uuid(NODE_ID.replace("-", "").upper(), "node_id")
        == NODE_ID
    )


def test_a_refused_call_leaves_no_database_behind(tmp_path) -> None:
    """Validation happens before I/O, so a refusal touches nothing.

    The store is pointed at a database that does not exist yet; a refused
    coefficient must not bring it into being, because the file's existence is
    the deployment's own fact and not an artefact of a caller's typo.
    """
    target = tmp_path / "untouched.db"
    store = ForwardIcRetentions(f"sqlite:///{target}")

    with pytest.raises(ForwardRetentionError):
        store.record_backtest_ic(NODE_ID, backtest_ic=True)

    assert not target.exists()


def test_this_feature_spells_no_window_of_its_own() -> None:
    """The bound on which days may be observed belongs to features 333/335.

    The ratio is taken over whatever rows the record holds, so this module
    computes no horizon and re-reads no window: a change to the 90-day figure
    reaches the observation writer and not this one, and the ratio cannot
    silently start meaning a different span.  Checked in the module's code
    rather than its prose, so the docstring may discuss the horizon while the
    code holds none.
    """
    source = code_of(forward.retention)

    assert "forward_days" not in source
    assert "read_window_close" not in source
    assert "read_promotion_window" not in source


# -- The landing site ---------------------------------------------------------


def test_the_figure_lands_on_the_opening_row_only(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord, forward_rows
) -> None:
    """The backtest belongs on the row that draws the boundary.

    Keying the ``UPDATE`` by ``node_id`` would stamp every out-of-sample row
    with an in-sample figure — a fact about the signal *before* the boundary
    written onto rows whose whole subject is that they are after it.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)

    rows = forward_rows()
    assert len(rows) == len(DAYS) + 1
    carrying = [row for row in rows if row["backtest_ic"] is not None]
    assert len(carrying) == 1
    assert carrying[0]["observed_on"] == BOUNDARY_DAY.isoformat()
    assert carrying[0]["backtest_ic"] == BACKTEST


def test_the_amend_sql_names_the_primary_key() -> None:
    """The landing site is fixed in SQL, not by which row the read returned.

    A test of the module's own vocabulary rather than of its behaviour, because
    the two shapers of the ``UPDATE`` — its key and its column — are what make
    the landing site the opening row.  An edit that keyed it by ``node_id``
    would pass every behavioural assertion above on a single-vintage record
    while stamping an in-sample figure across every row of a real one.
    """
    assert "WHERE id = ?" in forward.retention._AMEND_SQL
    assert f"SET {BACKTEST_IC_COLUMN} = ?" in forward.retention._AMEND_SQL
    assert "node_id" not in forward.retention._AMEND_SQL


def test_the_column_this_feature_owns_is_absent_from_every_other_writer() -> None:
    """A statement that cannot name a column cannot fabricate its value.

    The law :data:`forward.record._INSERT_SQL` and
    :data:`forward.observation._OBSERVATION_INSERT_SQL` both state.  This test
    is the other half of the claim that this module is the column's only
    writer: ``backtest_ic`` appears in exactly one statement in the member, and
    it is this one's ``UPDATE``.
    """
    assert BACKTEST_IC_COLUMN not in forward.observation._OBSERVATION_INSERT_SQL
    assert BACKTEST_IC_COLUMN not in forward.record._INSERT_SQL
    assert BACKTEST_IC_COLUMN in forward.retention._AMEND_SQL


def test_a_stored_backtest_is_validated_on_the_way_out(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord, promoted_signal
) -> None:
    """SQLite's columns are dynamically typed, so a hand can write anything.

    The value is validated on the read as well as on the write, for the reason
    every read in this member validates: the row is what later features and
    §C10's demotion line account with, and a divisor nobody can vouch for is
    worse than a refusal.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                f"UPDATE {FORWARD_RECORD_TABLE} SET {BACKTEST_IC_COLUMN} = ? "
                "WHERE node_id = ?",
                (7.5, NODE_ID),
            )
    finally:
        connection.close()

    with pytest.raises(ForwardRetentionError) as refusal:
        retentions.retention(NODE_ID)
    assert str(refusal.value).startswith(FORWARD_RETENTION_ERROR_CODE)


# -- Retry --------------------------------------------------------------------


def test_resupplying_the_same_figure_is_a_retry(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """The backfill re-ran: answered by the standing row, ``created=False``.

    The row is returned exactly as it is — ``id`` and stamps included —
    because nothing moved.
    """
    first, created = retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    second, again = retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)

    assert created is True
    assert again is False
    assert second.id == first.id
    assert second.backtest_ic == first.backtest_ic


def test_a_retry_after_an_observation_is_not_refused(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """The comparison is over the coefficient, not over the whole row.

    Feature 333 fills ``live_ic`` and feature 340 fills ``realized_cost_bps``,
    so a caller re-supplying the same backtest long after the record has been
    annotated must not be refused for disagreeing about columns this act never
    writes.
    """
    first, _ = retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    observations = ForwardObservations.over(retentions)
    observations.append_observation(
        NODE_ID,
        observed_on=dt.date(2026, 3, 5),
        live_ic=0.03,
        forward_days=FORWARD_DAYS,
    )
    second, again = retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)

    assert again is False
    assert second.backtest_ic == first.backtest_ic
    assert second.live_ic is None


def test_a_retry_does_not_move_the_amended_column(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord, forward_rows
) -> None:
    """``created=False`` and the table agree: the row is untouched."""
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    before = forward_rows()
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    after = forward_rows()

    assert [dict(row) for row in before] == [dict(row) for row in after]


# -- The value ------------------------------------------------------------------


def test_the_ratio_field_cannot_be_fabricated() -> None:
    """A ratio that is not its own operands' quotient is refused.

    The figure §C10 demotes on is arithmetic this member performed; an instance
    whose operands do not produce its ratio would put a number in front of the
    demotion line that nobody computed.
    """
    with pytest.raises(ForwardRetentionError) as refusal:
        IcRetention(
            node_id=NODE_ID,
            promoted_at=DECIDED,
            observed_on=FIRST_DAY,
            observed_days=1,
            live_ic=0.09,
            backtest_ic=BACKTEST,
            ratio=0.9,
        )
    assert str(refusal.value).startswith(FORWARD_RETENTION_ERROR_CODE)


def test_a_zero_backtest_cannot_be_wrapped_either() -> None:
    """The quotient law holds at construction, not only at the store's read."""
    with pytest.raises(ForwardRetentionError) as refusal:
        IcRetention(
            node_id=NODE_ID,
            promoted_at=DECIDED,
            observed_on=FIRST_DAY,
            observed_days=1,
            live_ic=0.09,
            backtest_ic=0.0,
            ratio=0.0,
        )
    assert str(refusal.value).startswith(FORWARD_RETENTION_ERROR_CODE)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "3", None], ids=str)
def test_a_malformed_day_count_is_refused(bad: object) -> None:
    """The evidence field is a positive whole number, not a float or a flag."""
    with pytest.raises(ForwardRetentionError) as refusal:
        IcRetention(
            node_id=NODE_ID,
            promoted_at=DECIDED,
            observed_on=FIRST_DAY,
            observed_days=bad,
            live_ic=0.09,
            backtest_ic=BACKTEST,
            ratio=RETENTION,
        )
    assert str(refusal.value).startswith(FORWARD_RETENTION_ERROR_CODE)


def test_the_stamps_are_validated_in_the_record_members_vocabulary() -> None:
    """The two stamps are the record's columns, checked by the record's rules.

    A :class:`~datetime.datetime` where a day belongs, a naive instant, a
    ``None`` — each is refused rather than carried, and refused as
    :class:`~forward.errors.ForwardRecordError` because the field is feature
    332's or feature 333's and the contract for it is theirs.  Without this a
    bogus stamp would survive construction and surface as an ``AttributeError``
    out of :meth:`IcRetention.summary` — a crash where a refusal belongs.
    """
    good = {
        "node_id": NODE_ID,
        "promoted_at": DECIDED,
        "observed_on": FIRST_DAY,
        "observed_days": 3,
        "live_ic": LIVE_MEAN,
        "backtest_ic": BACKTEST,
        "ratio": RETENTION,
    }

    with pytest.raises(ForwardRecordError):
        IcRetention(**{**good, "promoted_at": None})
    with pytest.raises(ForwardRecordError):
        # A naive stamp is the case under test, so the linter's usual
        # objection to a tz-less ``datetime`` is the point rather than a slip.
        IcRetention(**{**good, "promoted_at": dt.datetime(2026, 3, 1, 12)})  # noqa: DTZ001
    with pytest.raises(ForwardRecordError):
        IcRetention(**{**good, "observed_on": DECIDED})

    assert IcRetention(**good)


def test_the_answer_is_frozen_and_slotted() -> None:
    """A retention is a value: no field moves after it is computed."""
    answer = IcRetention(
        node_id=NODE_ID,
        promoted_at=DECIDED,
        observed_on=FIRST_DAY,
        observed_days=3,
        live_ic=LIVE_MEAN,
        backtest_ic=BACKTEST,
        ratio=RETENTION,
    )

    with pytest.raises(FrozenInstanceError):
        answer.ratio = 0.9  # type: ignore[misc]
    assert not hasattr(answer, "__dict__")


def test_the_summary_names_the_ratio_prd_names(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """The mapping a router or a job log carries is JSON-shaped.

    The ratio is named ``retention_ratio`` and the two operands travel beside
    it, so a reader holding the summary is holding §11's own operand rather
    than a figure that needs re-deriving.
    """
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    summary = retentions.retention(NODE_ID).summary()

    assert summary[RETENTION_RATIO_KEY] == pytest.approx(RETENTION, abs=1e-12)
    assert summary["live_ic"] == pytest.approx(LIVE_MEAN, abs=1e-12)
    assert summary[BACKTEST_IC_COLUMN] == BACKTEST
    assert summary["observed_days"] == len(DAYS)
    assert summary["promoted_at"] == DECIDED_AT
    assert summary["node_id"] == NODE_ID


def test_the_row_is_the_summary_in_order(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """``row`` and ``summary`` are two spellings of the same five figures."""
    retentions.record_backtest_ic(NODE_ID, backtest_ic=BACKTEST)
    answer = retentions.retention(NODE_ID)
    summary = answer.summary()

    assert answer.row() == (
        summary["node_id"],
        summary["observed_days"],
        summary["live_ic"],
        summary[BACKTEST_IC_COLUMN],
        summary[RETENTION_RATIO_KEY],
    )


# -- The ladder ----------------------------------------------------------------


def test_the_module_level_spelling_resolves_database_url(
    observed_record: ForwardRecord, promoted_signal: ForwardRecords
) -> None:
    """A caller with a URL and no store gets the figure in one call.

    The store is resolved from ``DATABASE_URL`` exactly as feature 333's
    module-level spelling resolves its own, so a caller writing through one
    spelling and reading through the other is reading the same database.
    """
    ForwardIcRetentions.over(promoted_signal).record_backtest_ic(
        NODE_ID, backtest_ic=BACKTEST
    )

    answer = forward_ic_retention(
        NODE_ID, env={DATABASE_URL_ENV: promoted_signal.database_url}
    )
    assert answer.ratio == pytest.approx(RETENTION, abs=1e-12)


def test_an_explicit_url_wins_over_the_environment(
    observed_record: ForwardRecord, promoted_signal: ForwardRecords
) -> None:
    """The explicit argument is the caller's own statement, and it wins."""
    ForwardIcRetentions.over(promoted_signal).record_backtest_ic(
        NODE_ID, backtest_ic=BACKTEST
    )

    answer = forward_ic_retention(
        NODE_ID,
        database_url=promoted_signal.database_url,
        env={DATABASE_URL_ENV: "sqlite:///nowhere.db"},
    )
    assert answer.ratio == pytest.approx(RETENTION, abs=1e-12)


def test_an_unconfigured_deployment_is_refused_by_name() -> None:
    """The module-level reader refuses rather than silently answering nothing.

    The silence would be the dangerous failure: a deployment that could not say
    where forward records live would read no ratio at all, and §C10's demotion
    line is a decision that has to be made every cycle rather than only when a
    caller remembers to name a database.
    """
    with pytest.raises(ForwardRetentionError) as refusal:
        forward_ic_retention(NODE_ID, env={})
    message = str(refusal.value)
    assert message.startswith(FORWARD_RETENTION_ERROR_CODE)
    assert DATABASE_URL_ENV in message


def test_the_reader_spelling_answers_none_when_unconfigured() -> None:
    """``resolve`` is the reader's spelling: absent is a state, not an error.

    A deployment with no relational store holds no retention reader, which is
    discoverable — the same stance
    :meth:`forward.observation.ForwardObservations.resolve` takes.
    """
    assert ForwardIcRetentions.resolve(env={}) is None
    assert ForwardIcRetentions.resolve(env={DATABASE_URL_ENV: "  "}) is None
    assert ForwardIcRetentions.resolve(env={DATABASE_URL_ENV: "sqlite:///x.db"})


def test_a_store_pointed_at_nothing_is_refused_at_construction() -> None:
    """The URL is a fact about the store, checked before any call."""
    for bad in ("", "   ", None, 7):
        with pytest.raises(ForwardRetentionError) as refusal:
            ForwardIcRetentions(bad)  # type: ignore[arg-type]
        assert str(refusal.value).startswith(FORWARD_RETENTION_ERROR_CODE)


def test_over_reads_one_attribute_and_refuses_a_bare_object() -> None:
    """The seam reads the value, so a stand-in composes and an object does not.

    There is no ``isinstance`` to defeat: the check is on the ``database_url``
    string the carrier exposes.
    """
    assert ForwardIcRetentions.over(SimpleNamespace(database_url="sqlite:///x.db"))
    with pytest.raises(TypeError) as refusal:
        ForwardIcRetentions.over(object())
    assert FORWARD_RETENTION_SEAM in str(refusal.value)


def test_the_path_is_translated_by_the_members_one_spelling(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """A URL this member cannot speak is refused in the member's vocabulary."""
    assert retentions.database_url == retentions._database_url
    bad = ForwardIcRetentions("postgresql://host/db")
    with pytest.raises(ForwardStoreError):
        _ = bad.path


# -- The laws the member holds --------------------------------------------------


def test_the_member_authors_no_ddl() -> None:
    """``backtest_ic`` is ``0108``'s own column; this module adds no table.

    The third REAL column is declared nullable by the migration and commented
    as the backtest side of this very ratio, so the act here is an ``UPDATE``
    of a column the migration already drew.  A module that spelled its own
    ``CREATE`` would be a second owner of a schema this member has one of.
    """
    source = code_of(forward.retention)

    assert "CREATE TABLE" not in source
    assert "ALTER TABLE" not in source
    assert "bootstrap_schema" in source


def test_the_member_reaches_no_sibling_and_reads_no_sibling_table() -> None:
    """The evaluation member owns prd §6.1's ``metrics.ic_mean``.

    A workspace member never imports another at module scope, and this feature
    must not read the evaluation member's tables at all — so the backtest
    figure arrives from the caller through
    :meth:`ForwardIcRetentions.record_backtest_ic` rather than being fetched.
    """
    source = code_of(forward.retention)

    assert "importlib" not in source
    assert "node_metrics" not in source
    assert "from scoring" not in source


def test_the_retention_read_is_the_record_members_own() -> None:
    """One ``SELECT`` for the whole member, restated nowhere.

    The rows this act divides and the rows the record's opener answered with
    cannot be two readings of one table: the module uses
    :data:`forward.record._READ_SQL` and
    :func:`forward.record._record_from_row` rather than spelling its own.
    """
    source = code_of(forward.retention)

    assert "SELECT" not in source
    assert "_READ_SQL" in source
    assert "_record_from_row" in source


def test_the_refusal_word_is_the_one_an_operator_greps() -> None:
    """One word opens every message, and it is this class's own.

    An operator greps one word per fault: ``forward_record_unwritable`` sends
    them to the database, and none of this feature's refusals is a database
    fault — the store answered and the rows are intact.
    """
    assert FORWARD_RETENTION_ERROR_CODE == "forward_retention_undivided"
    assert FORWARD_RETENTION_ERROR_CODE != forward.record.FORWARD_RECORD_ERROR_CODE
    assert FORWARD_RETENTION_ERROR_CODE != FORWARD_PROMOTION_ERROR_CODE


def test_every_refusal_leads_with_the_code_word(
    retentions: ForwardIcRetentions, observed_record: ForwardRecord
) -> None:
    """The greppable word is not merely defined; it opens each message once.

    A hand-run sweep over the faces :class:`ForwardRetentionError` covers, so
    a future edit that adds a refusal without the constant fails here rather
    than surfacing as an ungreppable line in an operator's log months later.
    The malformed-*identity* face is deliberately absent: that refusal belongs
    to the record's contract and leads with the record's own word.

    **Exactly once**, not merely at the front: a message that leads with the
    word twice greps clean and reads wrong, and a bare ``startswith`` would
    not catch it.  That doubling is not hypothetical — a scripted pass over
    this module's refusals inserted the prefix into :func:`_undefined` a
    second time, and only the count assertion below sees it.
    """
    moments = [
        lambda: retentions.record_backtest_ic(NODE_ID, backtest_ic=7.0),
        lambda: ForwardIcRetentions(""),
        lambda: forward_ic_retention(NODE_ID, env={}),
    ]
    retentions.record_backtest_ic(NODE_ID, backtest_ic=0.0)
    moments.append(lambda: retentions.retention(NODE_ID))
    moments.append(lambda: IcRetention(
        node_id=NODE_ID,
        promoted_at=DECIDED,
        observed_on=BOUNDARY_DAY,
        observed_days=1,
        live_ic=0.09,
        backtest_ic=0.0,
        ratio=0.0,
    ))

    for moment in moments:
        with pytest.raises(ForwardRetentionError) as refusal:
            moment()
        message = str(refusal.value)
        assert message.startswith(FORWARD_RETENTION_ERROR_CODE)
        assert message.count(FORWARD_RETENTION_ERROR_CODE) == 1, message


def test_the_public_surface_is_exactly_six_names() -> None:
    """``__all__`` is the feature's whole surface, and it is closed.

    Two column-or-key spellings, one seam, the store, the value and the
    one-call spelling: every name is either a fact about where the figures
    live or an act over them, and nothing here is an implementation detail
    that escaped.
    """
    assert sorted(forward.retention.__all__) == [
        "BACKTEST_IC_COLUMN",
        "FORWARD_RETENTION_SEAM",
        "ForwardIcRetentions",
        "IcRetention",
        "RETENTION_RATIO_KEY",
        "forward_ic_retention",
    ]


def test_the_signatures_state_that_neither_operand_is_a_parameter() -> None:
    """The feature's sentence, checked at the signature.

    ``retention`` takes the node and nothing else: a live IC or a ratio a
    caller could pass would be a ratio this member did not compute.  The
    module-level spelling takes no coefficient either — only where to read.
    """
    assert list(inspect.signature(ForwardIcRetentions.retention).parameters) == [
        "self",
        "node_id",
    ]

    writer = inspect.signature(ForwardIcRetentions.record_backtest_ic)
    assert list(writer.parameters) == ["self", "node_id", "backtest_ic"]
    assert writer.parameters["backtest_ic"].kind is inspect.Parameter.KEYWORD_ONLY

    module_level = inspect.signature(forward_ic_retention)
    assert list(module_level.parameters) == ["node_id", "database_url", "env"]
    assert (
        module_level.parameters["database_url"].kind is inspect.Parameter.KEYWORD_ONLY
    )


def test_the_store_reprs_its_url(retentions: ForwardIcRetentions) -> None:
    """The debugging aid names the URL and nothing else."""
    assert repr(retentions) == (
        f"ForwardIcRetentions(database_url={retentions.database_url!r})"
    )
