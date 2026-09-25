"""Feature 346's store: discoveries per 1000 budget-charging trials.

app_spec feature 346 — *System persists discoveries per 1000 budget-charging
trials, excluding null nodes from the denominator* — docs §16's research
metric (*"discoveries per 1000 **budget-charging** trials"*) and prd §11's
secondary scorecard row (*"Discoveries per 1,000 trials charged (nulls
excluded from the denominator) | trending up"*).

This suite pins the store's law: one row per campaign keyed by the campaign's
canonical UUID id (§16's *"Research metrics (per campaign)"* grain); the
quotient **computed by the store** as ``discoveries ÷ budget_charging_trials ×
1000`` with no parameter for it at any spelling; all three counts handed over
already measured (the store reads no ledger and counts no pick); the
**denominator's identity** pinned as feature 93's ``K_effective`` law — the
count of the ledger's rows whose ``charges_budget`` is true, *"excluding null
nodes"*, and deliberately **not** the ledger's plain row count, which the row
carries beside it as ``ledger_trials`` so the exclusion is checkable by
subtraction; the ask validated whole **before a connection is opened**, so a
refused record leaves no database file at all; the write an upsert that
refreshes the measurement and preserves the row's original ``recorded_at``;
the point read answering ``None`` and the sweep an empty tuple for a
deployment that has closed no campaign out — an absence, never a zero,
because ``0.0`` is a *measurement* (a campaign that made no discoveries) and a
caller that could not tell them apart would read a barren research programme
out of a missing row; a **zero rate persisted, never refused**; the trend read
answering oldest-first; the two cross-field laws (the denominator never
exceeds the ledger's rows, and the stored quotient agrees with the counts
beside it) refused rather than served; and the construction performing no I/O.

The fixtures mirror ``test_meta_overfit.py``: a real SQLite file under
``tmp_path`` and a ``DATABASE_URL`` pointed at it, with the conftest's
per-test isolation so no test can write into the real store.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest
from ops import DiscoveryRateError, DiscoveryRates
from ops.discovery_rate import (
    DISCOVERY_RATE_TABLE,
    OPS_DISCOVERY_RATE_COMPONENT_NAME,
)

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
CAMPAIGN_LATER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "discovery-rate.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(store_url: str) -> DiscoveryRates:
    """A store bound to the test-only database."""
    return DiscoveryRates(store_url)


def _record(store: DiscoveryRates, campaign: str = CAMPAIGN, **overrides: object):
    """One campaign's rate, the shape every test writes: 12 discoveries over
    4,000 budget-charging trials out of a ledger of 5,200 rows — a rate of
    3.0 per 1000, with 1,200 null nodes the sentence excludes showing up as
    the difference of the two counts."""
    ask: dict[str, object] = {
        "discoveries": 12,
        "budget_charging_trials": 4000,
        "ledger_trials": 5200,
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }
    ask.update(overrides)
    return store.record(campaign, **ask)


# -- Round trip ---------------------------------------------------------------


def test_record_then_rate_round_trips_to_the_bit(store: DiscoveryRates) -> None:
    # The row survives the write and comes back off its own columns,
    # unchanged — the store answers what was written, never a recomputation.
    written = _record(store)
    read_back = store.rate(CAMPAIGN)
    assert read_back is not None
    assert read_back == written
    assert read_back.discoveries == 12
    assert read_back.budget_charging_trials == 4000
    assert read_back.ledger_trials == 5200
    assert read_back.recorded_at == "2026-01-01T00:00:00+00:00"


def test_the_rate_is_the_stores_own_arithmetic(store: DiscoveryRates) -> None:
    # The one figure the sentence names, computed by the store as
    # discoveries / budget_charging_trials * 1000.  There is no parameter for
    # it at any spelling: a caller-stated quotient would let the system
    # persist a numerator, a denominator and a third number that disagrees
    # with both, and prd §11 reads its direction off this column.
    import inspect

    signature = inspect.signature(DiscoveryRates.record)
    assert "rate" not in signature.parameters
    assert not any("rate" in name for name in signature.parameters)
    record = _record(store)
    assert record.rate == pytest.approx(3.0)
    # The unit is per 1000, not a fraction: the row does NOT carry 0.003.
    assert record.rate != pytest.approx(0.003)
    # A denser campaign reads higher; the same figures over a hundred times
    # the trials read lower — the denominator is not a formality.
    denser = _record(
        store,
        campaign=CAMPAIGN_LATER,
        discoveries=12,
        budget_charging_trials=1000,
        ledger_trials=1000,
    )
    assert denser.rate == pytest.approx(12.0)
    # And the value carries no verdict past the number: no threshold, no
    # flag — whether a rate is *good* is prd §11's scorecard's judgment,
    # reached by the loop that reads the trend, and read off these rows
    # rather than decided by this member.
    assert not any(
        "threshold" in name or "good" in name or "trending" in name
        for name in dir(denser)
    )


def test_a_zero_rate_is_a_measurement_and_is_persisted(
    store: DiscoveryRates, store_path: Path
) -> None:
    # A campaign that found nothing measured exactly that, and prd §11's
    # "trending up" is a direction a flat zero is the honest bottom of.  Zero
    # is therefore *stored*, never refused, and never conflated with the
    # absence of a row.
    record = _record(store, discoveries=0)
    assert record.rate == 0.0
    assert record.discoveries == 0
    standing = store.rate(CAMPAIGN)
    assert standing is not None
    assert standing.rate == 0.0
    with sqlite3.connect(store_path) as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {DISCOVERY_RATE_TABLE}"
        ).fetchone()[0]
    assert count == 1


def test_a_rate_above_1000_is_possible_and_unclamped(store: DiscoveryRates) -> None:
    # There is deliberately no bound relating the discoveries to either
    # count: a committed pick need not have come from a trial this campaign
    # charged (prd §4.2's resident book is selected across campaigns), so a
    # rate above 1000 is possible, is a measurement, and clamping it would be
    # this store inventing a bound the documents do not state.
    record = _record(store, discoveries=9, budget_charging_trials=3, ledger_trials=3)
    assert record.rate == pytest.approx(3000.0)


def test_a_rate_at_any_spelling_is_refused(store: DiscoveryRates) -> None:
    # The value's own shape: a quotient that disagrees with the counts beside
    # it is a row lying about its own division, refused rather than served —
    # the only arithmetic the store performs is the one it can check.
    from ops import DiscoveryRate

    with pytest.raises(DiscoveryRateError):
        DiscoveryRate(
            campaign_id=CAMPAIGN,
            discoveries=12,
            budget_charging_trials=4000,
            ledger_trials=5200,
            rate=3.5,  # 12 / 4000 * 1000 is 3.0, not 3.5
            recorded_at="2026-01-01T00:00:00+00:00",
        )


def test_rate_answers_none_for_a_campaign_never_recorded(
    store: DiscoveryRates,
) -> None:
    # A campaign with no row answers None, never 0.0 — a zero is a
    # measurement (a campaign that found nothing), and a campaign that closed
    # no rate out is not one.
    _record(store)
    assert store.rate(CAMPAIGN) is not None
    assert store.rate(CAMPAIGN_LATER) is None


def test_history_returns_rows_oldest_first(store: DiscoveryRates) -> None:
    # The trend prd §11 grades the metric's *direction* across: ordered by
    # the row's own instant, oldest first.
    _record(store, campaign=CAMPAIGN_LATER, recorded_at="2026-03-01T00:00:00+00:00")
    _record(store, campaign=CAMPAIGN, recorded_at="2026-01-01T00:00:00+00:00")
    third = "33333333-3333-3333-3333-333333333333"
    _record(store, campaign=third, recorded_at="2026-02-01T00:00:00+00:00")
    assert [row.campaign_id for row in store.history()] == [
        CAMPAIGN,
        third,
        CAMPAIGN_LATER,
    ]


def test_history_breaks_same_instant_ties_by_the_campaign(
    store: DiscoveryRates,
) -> None:
    # Two campaigns closing out at the same instant is one ordering the store
    # must not leave to the storage engine's accident: (recorded_at,
    # campaign_id), so two reads of one history return the same sequence.
    _record(store, campaign=CAMPAIGN_LATER, recorded_at="2026-01-01T00:00:00+00:00")
    _record(store, campaign=CAMPAIGN, recorded_at="2026-01-01T00:00:00+00:00")
    assert [row.campaign_id for row in store.history()] == [
        CAMPAIGN,
        CAMPAIGN_LATER,
    ]


def test_history_is_empty_for_a_deployment_that_closed_no_campaign_out(
    store: DiscoveryRates,
) -> None:
    # An empty tuple is the honest answer: a discoverable state, not an
    # exception and never a fabricated first point.
    assert store.history() == ()


# -- The denominator's identity, and the count carried beside it --------------


def test_the_denominator_is_the_budget_charging_count_not_the_ledger_count(
    store: DiscoveryRates, store_path: Path
) -> None:
    # The sentence's second clause, pinned as arithmetic.  The denominator is
    # feature 93's K_effective — the trials whose charges_budget is true
    # (§8: a null node "consumed agent calls and CPU but NO statistical
    # degrees of freedom") — and NOT the ledger's plain row count.  A store
    # that divided by the row count would answer a *smaller* rate exactly in
    # proportion to how many nulls the campaign planted, which is the
    # flattering direction prd §11's "trending up" target would reward.
    _record(store, discoveries=12, budget_charging_trials=4000, ledger_trials=5200)
    with sqlite3.connect(store_path) as connection:
        row = connection.execute(
            f"SELECT discoveries, budget_charging_trials, ledger_trials, rate "
            f"FROM {DISCOVERY_RATE_TABLE} WHERE campaign_id = ?",
            (CAMPAIGN,),
        ).fetchone()
    found, charged, ledger, rate = row
    assert charged == 4000
    assert ledger == 5200
    # The rate is the one taken over the budget-charging count...
    assert rate == pytest.approx(found / charged * 1000.0)
    # ...and demonstrably not the one taken over the ledger's row count,
    # which would have been the smaller, flattering figure.
    assert rate != pytest.approx(found / ledger * 1000.0)


def test_the_ledger_count_is_carried_so_the_exclusion_is_checkable(
    store: DiscoveryRates,
) -> None:
    # "Excluding null nodes from the denominator" is a claim about which
    # count was divided into, and the only way a stored row can be *checked*
    # to have honoured it — rather than merely labelled as having — is for the
    # row to carry both counts, so their difference is the null nodes the
    # sentence excludes.  That is feature 93's own arithmetic stated as a
    # column: the two diverge by exactly the null nodes.
    record = _record(store, budget_charging_trials=4000, ledger_trials=5200)
    assert record.ledger_trials - record.budget_charging_trials == 1200
    # And a campaign that planted none shows the two counts equal.
    clean = _record(
        store,
        campaign=CAMPAIGN_LATER,
        budget_charging_trials=4000,
        ledger_trials=4000,
    )
    assert clean.ledger_trials == clean.budget_charging_trials
    # The two rows read the same rate whatever the ledger's size — the
    # ledger count enters no arithmetic.
    assert clean.rate == record.rate


def test_the_ledger_count_enters_no_arithmetic(store: DiscoveryRates) -> None:
    # The ledger count is context and the check's other operand, and nothing
    # else: the rate is discoveries over the *budget-charging* count and only
    # that.  Two rows with the same discoveries and denominator carry the
    # same rate whatever their ledger sizes.
    one = _record(store, budget_charging_trials=1000, ledger_trials=1000)
    two = _record(
        store,
        campaign=CAMPAIGN_LATER,
        budget_charging_trials=1000,
        ledger_trials=99000,
    )
    assert one.rate == two.rate
    assert (two.budget_charging_trials, two.ledger_trials) == (1000, 99000)


def test_a_denominator_above_the_ledgers_own_size_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # Feature 93's K_effective is the count of the ledger's rows whose
    # charges_budget is true — a *subset* count — so it can never exceed the
    # ledger's own size.  The ledger is append-only with no UPDATE and no
    # DELETE (§8, enforced by role grants), so the impossible pair cannot be
    # produced honestly by any pruning either: a row where it holds is a row
    # claiming to have divided by more charges than were ever recorded, and
    # serving it would put a flattering denominator into prd §11's trend.
    with pytest.raises(DiscoveryRateError) as caught:
        _record(store, budget_charging_trials=5200, ledger_trials=4000)
    assert "budget_charging_trials" in str(caught.value)
    assert not store_path.exists()
    # Equal counts are admissible — a campaign that planted no nulls.
    record = _record(store, budget_charging_trials=4000, ledger_trials=4000)
    assert record.rate == pytest.approx(3.0)


def test_a_stored_row_whose_denominator_exceeds_its_ledger_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # The same span law reached on the read path: a hand-inserted row whose
    # denominator exceeds the ledger size it is paired with is a row no rate
    # row could be, and the value layer refuses it rather than handing a
    # caller a figure divided by an impossible count.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {DISCOVERY_RATE_TABLE} SET budget_charging_trials = 9999, "
            f"rate = 9999.0 WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(DiscoveryRateError):
        store.history()
    with pytest.raises(DiscoveryRateError):
        store.rate(CAMPAIGN)


# -- One campaign, one row ----------------------------------------------------


def test_the_row_carries_the_six_columns_it_declares(
    store: DiscoveryRates, store_path: Path
) -> None:
    # The table's shape, pinned: the campaign's own id, the three counts, the
    # derived rate and the row's label.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        rows = connection.execute(
            f"SELECT campaign_id, discoveries, budget_charging_trials, "
            f"ledger_trials, rate, recorded_at FROM {DISCOVERY_RATE_TABLE}"
        ).fetchall()
    assert len(rows) == 1
    campaign, found, charged, ledger, rate, recorded_at = rows[0]
    assert campaign == CAMPAIGN
    assert (found, charged, ledger) == (12, 4000, 5200)
    assert rate == pytest.approx(3.0)
    assert recorded_at == "2026-01-01T00:00:00+00:00"


def test_a_campaign_is_the_primary_key_and_two_campaigns_are_two_rows(
    store: DiscoveryRates, store_path: Path
) -> None:
    # §16 fixes the grain in its own parenthesis — "Research metrics (per
    # campaign)" — so the key is the campaign id.
    _record(store, campaign=CAMPAIGN)
    _record(store, campaign=CAMPAIGN_LATER)
    with sqlite3.connect(store_path) as connection:
        rows = connection.execute(
            f"SELECT campaign_id FROM {DISCOVERY_RATE_TABLE} ORDER BY campaign_id"
        ).fetchall()
    assert rows == [(CAMPAIGN,), (CAMPAIGN_LATER,)]
    assert len(store.history()) == 2


def test_upsert_refreshes_the_measurement_rather_than_appending(
    store: DiscoveryRates, store_path: Path
) -> None:
    # A re-run of the same campaign's measurement refreshes the measured
    # columns — the figure is a deterministic function of a campaign's ledger
    # rows and its committed picks, so it is the same measurement written
    # twice rather than a second occurrence.
    _record(store, discoveries=12, budget_charging_trials=4000)
    _record(store, discoveries=30, budget_charging_trials=4000)
    with sqlite3.connect(store_path) as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {DISCOVERY_RATE_TABLE}"
        ).fetchone()[0]
    assert count == 1
    standing = store.rate(CAMPAIGN)
    assert standing is not None
    assert standing.discoveries == 30
    assert standing.rate == pytest.approx(7.5)


def test_upsert_preserves_the_rows_original_recorded_at(
    store: DiscoveryRates,
) -> None:
    # The refresh arm deliberately does not touch recorded_at: the first
    # instant the campaign's rate was computed is a fact about the trend's
    # history a retry must not rewrite — feature 267's stance toward its own
    # per-campaign row, restated.
    first = _record(store, recorded_at="2026-01-01T00:00:00+00:00")
    refreshed = _record(store, discoveries=99, recorded_at="2026-09-09T09:09:09+00:00")
    assert first.recorded_at == "2026-01-01T00:00:00+00:00"
    # The answer is read back inside the write's transaction, so it is the
    # row's own instant rather than the argument's.
    assert refreshed.recorded_at == "2026-01-01T00:00:00+00:00"
    assert refreshed.discoveries == 99


# -- The ask is validated whole, before a connection is opened ----------------


def test_an_id_that_is_not_a_campaign_is_refused_before_any_connection(
    store: DiscoveryRates, store_path: Path
) -> None:
    # The key is the campaign's canonical UUID text; a value that names no
    # campaign names no figure §16's per-campaign grain could hold.
    for bad in ("", "   ", None, 7, ["campaign"], "not-a-uuid"):
        with pytest.raises(DiscoveryRateError):
            _record(store, bad)  # type: ignore[arg-type]
    assert not store_path.exists()
    # A UUID object is accepted, and a mixed-case or braced spelling
    # canonicalises onto the one row rather than making one campaign look
    # like two — the join law feature 267's per-campaign row already keys on.
    import uuid

    upper = store.record(
        uuid.UUID(CAMPAIGN).hex.upper(),
        discoveries=12,
        budget_charging_trials=4000,
        ledger_trials=5200,
    )
    assert upper.campaign_id == CAMPAIGN
    padded = store.record(
        f"  {{{CAMPAIGN.upper()}}}  ",
        discoveries=12,
        budget_charging_trials=4000,
        ledger_trials=5200,
    )
    assert padded.campaign_id == CAMPAIGN
    assert len(store.history()) == 1


def test_a_count_that_is_not_a_whole_number_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # A fractional count would be this store inventing a denominator the
    # caller never stated, and the figure is a quotient of three counts.
    for field in ("discoveries", "budget_charging_trials", "ledger_trials"):
        for bad in (12.0, "12", None, 12.5, [12]):
            with pytest.raises(DiscoveryRateError):
                _record(store, **{field: bad})
    assert not store_path.exists()


def test_bool_is_refused_before_int_for_every_count(
    store: DiscoveryRates, store_path: Path
) -> None:
    # A bool *is* an int in Python's hierarchy and is not a count of trials.
    for field in ("discoveries", "budget_charging_trials", "ledger_trials"):
        with pytest.raises(DiscoveryRateError):
            _record(store, **{field: True})
    assert not store_path.exists()


def test_a_zero_denominator_is_refused_by_name(
    store: DiscoveryRates, store_path: Path
) -> None:
    # A rate over no budget-charging trials is undefined — a ledger of
    # nothing but null nodes charges nothing (§8: a null node "must not
    # inflate K") — and answering 0.0 for 0/0 would persist the quietest
    # possible claim about a campaign whose research yield was never
    # measured.
    with pytest.raises(DiscoveryRateError) as caught:
        _record(store, budget_charging_trials=0, ledger_trials=0)
    assert "budget_charging_trials" in str(caught.value)
    with pytest.raises(DiscoveryRateError):
        _record(store, budget_charging_trials=-1, ledger_trials=10)
    assert not store_path.exists()


def test_a_negative_discovery_count_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # Zero is the honest bottom; a negative number of discoveries is not a
    # measurement of anything.
    with pytest.raises(DiscoveryRateError) as caught:
        _record(store, discoveries=-1)
    assert "discoveries" in str(caught.value)
    assert not store_path.exists()


def test_a_ledger_of_zero_rows_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # The ledger count is a count of rows and a rate row's ledger holds at
    # least the denominator, which is itself at least one.
    with pytest.raises(DiscoveryRateError):
        _record(store, budget_charging_trials=1, ledger_trials=0)
    assert not store_path.exists()


def test_a_count_past_the_columns_range_is_refused_by_name(
    store: DiscoveryRates, store_path: Path
) -> None:
    # SQLite's INTEGER is a signed 64-bit integer, and a whole number past it
    # has no column to land in.  The refusal is here, in this member's
    # vocabulary, rather than as a raw OverflowError from the driver's
    # binding step — which is neither this member's error nor a measurement of
    # anything.  Refused *before* the connection, on the write path, so no
    # half-written row is left behind.
    past = 1 << 63
    with pytest.raises(DiscoveryRateError) as caught:
        _record(store, discoveries=past, budget_charging_trials=1, ledger_trials=1)
    assert "discoveries" in str(caught.value)
    assert not store_path.exists()
    # The largest storable count is admitted rather than refused: the bound is
    # the column's, not an opinion about the figure.
    biggest = _record(
        store,
        discoveries=0,
        budget_charging_trials=past - 1,
        ledger_trials=past - 1,
    )
    assert biggest.budget_charging_trials == past - 1
    assert biggest.rate == 0.0


def test_a_stored_count_past_the_columns_range_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # The same bound on the read path.  SQLite's dynamic typing will hold a
    # float past the range in an INTEGER column, so a stored row can carry
    # one — and the value layer refuses it rather than letting a figure the
    # table cannot hold reach prd §11's trend.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {DISCOVERY_RATE_TABLE} SET discoveries = 1e300, "
            f"rate = 2.5e297 WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(DiscoveryRateError):
        store.history()
    with pytest.raises(DiscoveryRateError):
        store.rate(CAMPAIGN)


def test_the_instant_must_be_a_nameable_label(
    store: DiscoveryRates, store_path: Path
) -> None:
    # The instant is the label the trend's order reads; a value that is not a
    # nameable instant orders prd §11's direction by nothing.
    for bad in (12345, "", "   "):
        with pytest.raises(DiscoveryRateError):
            _record(store, recorded_at=bad)
    assert not store_path.exists()


def test_default_instant_stamps_the_write(store: DiscoveryRates) -> None:
    # recorded_at defaults to now (UTC, second resolution); a caller that
    # measured at a known instant passes it, but the write can stamp its own.
    written = store.record(
        CAMPAIGN,
        discoveries=12,
        budget_charging_trials=4000,
        ledger_trials=5200,
    )
    instant = written.recorded_at
    assert "T" in instant
    assert instant.endswith("+00:00")
    time_part = instant.split("T")[1].split("+")[0]
    assert time_part.count(":") == 2
    assert "." not in time_part


# -- A stored row that is not a rate row is refused, never served -------------


def test_a_stored_row_whose_rate_disagrees_with_its_counts_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # SQLite's columns are dynamically typed, so a hand-edited row is
    # reachable; prd §11's grade is read off this column, and a row that
    # disagrees with its own division is refused rather than served — a
    # skipped row is a campaign's yield wearing a shrug.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {DISCOVERY_RATE_TABLE} SET rate = 99.0 WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(DiscoveryRateError) as caught:
        store.history()
    # The refusal names the campaign the bad row came from, so an operator
    # gets the row to repair rather than a complaint about a value with no
    # address.
    assert CAMPAIGN in str(caught.value)
    with pytest.raises(DiscoveryRateError):
        store.rate(CAMPAIGN)


def test_a_stored_rate_that_is_not_a_number_is_refused(
    store: DiscoveryRates, store_path: Path,
) -> None:
    # A rate that is not a real, or not finite, is not the quotient this
    # store computes: a stored NaN compares false against everything and
    # would ride into prd §11's trend while looking exactly like a data
    # point.  SQLite's REAL column holds text too (its NOT NULL constraint is
    # the belt against NULL, not a type gate).
    for bad in ("three point zero", "nan", "inf"):
        _record(store)
        with sqlite3.connect(store_path) as connection:
            connection.execute(
                f"UPDATE {DISCOVERY_RATE_TABLE} SET rate = ? WHERE campaign_id = ?",
                (bad, CAMPAIGN),
            )
        with pytest.raises(DiscoveryRateError):
            store.history()
        with pytest.raises(DiscoveryRateError):
            store.rate(CAMPAIGN)


def test_a_stored_negative_rate_is_refused_as_an_arithmetic_disagreement(
    store: DiscoveryRates, store_path: Path,
) -> None:
    # A rate is non-negative *by construction* — two non-negative counts over
    # a strictly positive denominator — so a stored negative one is not a
    # measurement this store could have written, and it is refused by the
    # arithmetic check (the row disagrees with its own counts) rather than by
    # a sign bound this module would have had to invent.  Pinned, because the
    # refusal's *route* is the point: no `rate < 0` gate exists anywhere, and
    # a future one would be a bound the documents do not state.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {DISCOVERY_RATE_TABLE} SET rate = -3.0 WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(DiscoveryRateError) as caught:
        store.history()
    assert CAMPAIGN in str(caught.value)


def test_a_stored_count_that_is_not_a_count_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # A denominator of zero would otherwise reach prd §11's trend as a
    # quotient nobody could have divided.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {DISCOVERY_RATE_TABLE} SET budget_charging_trials = 0 "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(DiscoveryRateError):
        store.history()


def test_a_stored_row_naming_no_campaign_is_refused(
    store: DiscoveryRates, store_path: Path
) -> None:
    # A row wearing an id no campaign resolves is a figure §16's per-campaign
    # grain cannot attribute.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {DISCOVERY_RATE_TABLE} SET campaign_id = '  ' "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(DiscoveryRateError):
        store.history()


# -- The store is the workspace's one relational store ------------------------


def test_construction_performs_no_io(store_url: str, store_path: Path) -> None:
    # The class resolves its path lazily, so constructing one performs no
    # I/O: composition-time work must not touch the disk.
    DiscoveryRates(store_url)
    assert not store_path.exists()


def test_resolve_answers_none_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Absent is not an error: it is a deployment without a relational store,
    # which composes no discovery-rate component — a discoverable state, not
    # an exception.
    from ops import DATABASE_URL_ENV

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert DiscoveryRates.resolve() is None


def test_resolve_answers_none_for_an_empty_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty or whitespace-only value counts as unset.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert DiscoveryRates.resolve() is None


def test_resolve_answers_the_named_store(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The store DATABASE_URL names, resolved.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = DiscoveryRates.resolve()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_an_unsupported_scheme_is_refused_at_first_use(store_path: Path) -> None:
    # Only sqlite:/// speaks — a Postgres metrics table arrives with the
    # versioned migration member, and pretending to speak it here would hide
    # a misrouted URL behind a mysterious file.  Refused at first use, not
    # construction.
    store = DiscoveryRates("postgresql://localhost/metrics")
    assert store.database_url == "postgresql://localhost/metrics"
    with pytest.raises(DiscoveryRateError):
        _record(store)


def test_an_unspeakable_scheme_is_refused_at_first_use() -> None:
    # A scheme with no netloc and no path — refused at first use, not
    # construction, and never silently mis-parsed into a file.
    store = DiscoveryRates("redis://cache:6379/0")
    with pytest.raises(DiscoveryRateError):
        _record(store)


def test_a_sqlite_url_with_a_host_is_refused() -> None:
    # No host but localhost admitted — the same refusal every store in this
    # workspace states for its own connection.
    store = DiscoveryRates("sqlite://remote-host/db.sqlite")
    with pytest.raises(DiscoveryRateError):
        _record(store)


def test_a_sqlite_url_with_no_path_is_refused() -> None:
    # A URL with no path refused — the store must name a database.
    store = DiscoveryRates("sqlite:///")
    with pytest.raises(DiscoveryRateError):
        _record(store)


def test_a_blank_url_is_refused_at_construction() -> None:
    # The URL is held, not resolved, but it must be a non-empty string.
    for bad in ("", "   ", None, 7):
        with pytest.raises(DiscoveryRateError):
            DiscoveryRates(bad)  # type: ignore[arg-type]


def test_a_database_that_will_not_open_is_surfaced_chained(tmp_path: Path) -> None:
    # The store's own failure surfaces in this member's vocabulary, chained to
    # the original and deliberately not swallowed: a rate that measured but
    # never landed is the state feature 346 exists to rule out.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = DiscoveryRates(f"sqlite:///{not_a_dir}/discovery-rate.db")
    with pytest.raises(DiscoveryRateError) as caught:
        _record(store)
    assert caught.value.__cause__ is not None


def test_a_read_failure_is_surfaced_chained(tmp_path: Path) -> None:
    # A store that cannot be asked is surfaced rather than answered around —
    # prd §11's direction is read across these rows.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = DiscoveryRates(f"sqlite:///{not_a_dir}/discovery-rate.db")
    with pytest.raises(DiscoveryRateError) as caught:
        store.rate(CAMPAIGN)
    assert caught.value.__cause__ is not None
    with pytest.raises(DiscoveryRateError) as caught:
        store.history()
    assert caught.value.__cause__ is not None


# -- The module reads no ledger and counts no pick ----------------------------


def test_the_module_reads_no_sibling_and_no_clock() -> None:
    # The member's law is delegation: the discoveries are the selection
    # surface's, the budget-charging count is feature 93's derivation and the
    # ledger's row count is the ledger store's own plain number.  Reaching
    # for the ledger member would make this table's construction depend on a
    # sibling the factory scan could not promise is on sys.path at build time,
    # and would grow a second spelling of the charges_budget filter feature 93
    # already owns.  Read on the code (docstrings stripped), so the prose may
    # name the ledger and the code may not.
    import ops.discovery_rate as module

    tree = ast.parse(_code_of(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    # Only stdlib and this member's own modules.
    assert imported <= {
        "__future__",
        "datetime",
        "math",
        "os",
        "sqlite3",
        "uuid",
        "contextlib",
        "dataclasses",
        "numbers",
        "pathlib",
        "typing",
        "urllib",
        "errors",
        "live_metrics",
    }, sorted(imported)
    # No ledger, no scoring, no dreaming, no replay.
    for sibling in ("ledger", "scoring", "dreaming", "replay", "discovery"):
        assert sibling not in imported
    # And no clock of its own past the row's label: `datetime.now` appears
    # exactly where the instant defaults, nowhere else.
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "perf_counter" not in names
    assert "time" not in {alias.name for node in ast.walk(tree)
                          if isinstance(node, ast.Import)
                          for alias in node.names}


def _code_of(module: object) -> str:
    """The module's source with every docstring stripped.

    The "what the code does, not what the prose says" reading this suite
    shares with the member's other modules: a docstring naming the ledger
    member is honesty (the figure's owner is stated where it is delegated
    to), while an *import* of it would be the second spelling this member
    exists to avoid — and only the AST can tell the two apart.
    """
    import inspect

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# -- The component beside the member's other four -----------------------------


def test_the_builder_resolves_the_named_store_or_none(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The builder resolves DATABASE_URL and answers None when nothing names a
    # store — the degrade-don't-break stance every store-bound builder here
    # takes, so a deployment without a relational store still composes.
    from ops import DATABASE_URL_ENV, build_discovery_rate_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_discovery_rate_store() is None
    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = build_discovery_rate_store()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_the_builder_touches_no_disk_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Building performs no I/O — no store is constructed, no database opened,
    # no schema created — and when nothing names a store the builder answers
    # None without touching the disk.
    from ops import DATABASE_URL_ENV, build_discovery_rate_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_discovery_rate_store() is None


def test_the_component_name_is_the_member_fifth() -> None:
    # The growth the member's own registration reserved when feature 341
    # landed: the route, the dashboard, the live-metrics store, the
    # meta-overfit gap store, and now the discovery-rate store, each beside —
    # never inside — another member's components.
    from ops import (
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_DISCOVERY_RATE_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
        OPS_META_OVERFIT_COMPONENT_NAME,
    )

    names = {
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
        OPS_META_OVERFIT_COMPONENT_NAME,
        OPS_DISCOVERY_RATE_COMPONENT_NAME,
    }
    # Five distinct component names under the one member-first prefix.
    assert len(names) == 5
    assert OPS_DISCOVERY_RATE_COMPONENT_NAME == "ops-discovery-rate"
    assert all(name.startswith("ops-") for name in names)


def test_the_component_name_is_exported_from_the_member() -> None:
    import ops

    assert "OPS_DISCOVERY_RATE_COMPONENT_NAME" in ops.__all__
    assert ops.OPS_DISCOVERY_RATE_COMPONENT_NAME == "ops-discovery-rate"
    assert (
        ops.OPS_DISCOVERY_RATE_COMPONENT_NAME == OPS_DISCOVERY_RATE_COMPONENT_NAME
    )


def test_the_store_class_is_exported_from_the_member() -> None:
    import ops

    assert "DiscoveryRates" in ops.__all__
    assert "DiscoveryRate" in ops.__all__
    assert "DiscoveryRateError" in ops.__all__
    assert "DISCOVERY_RATE_TABLE" in ops.__all__
    assert ops.DISCOVERY_RATE_TABLE == DISCOVERY_RATE_TABLE


def test_the_error_is_the_members_own_vocabulary() -> None:
    # One base so a caller catches the member as a whole, one subclass per
    # surface so a refusal names where it happened.
    from ops import DiscoveryRateError, OpsError

    assert issubclass(DiscoveryRateError, OpsError)
    assert OpsError in DiscoveryRateError.__mro__
