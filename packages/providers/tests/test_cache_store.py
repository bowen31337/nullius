"""Feature 200's persistence: the store that measures campaigns and answers the row.

The two halves :mod:`tests.test_cache` states for the configuration and
the choice need no database; this file holds the third half — the
sentence's own verb, *persists*.  :meth:`providers.DepthCacheRates.measure`
is the feature as one call (total the usages, prove the campaign was
planned, insert the row, read it back), and the tests below hold it to
its word on exactly the grounds the sibling stores are held to theirs:

* the **row is the measurement** — one campaign, one measurement, one
  row keyed by the campaign id; an identical re-issue answers the stored
  record with its original instant, and a re-measurement naming
  different totals is refused, naming both;
* the **table is this member's own**, created lazily by the first write
  and by nothing else, while the ``campaign`` table beside it is probed
  read-only and never created (``0111``'s, brought by the fixture the
  way a deployment brings it);
* the **read side re-verifies** — a hand-corrupted row is refused
  naming the campaign, because the read side is where corruption would
  otherwise be laundered, and a rate above 1.0 reading back as a
  measurement would be a campaign billed for more cache than it had
  prompt;
* the **measurement is computed, not trusted** — from the usages feature
  192's completions carry, totalled by the store rather than accepted as
  a caller's ratio, with the per-call invariant (cache read never above
  the input it is a portion of) checked per call, where a campaign total
  could hide a single nonsense report.

Every measuring instant in the suite is fixed and stated (a Wednesday in
September 2026), never ``now()`` — the ``now`` argument exists so the
deployment supplies the moment and the suite supplies a known one.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction

import pytest
from conftest import sqlite_path_of
from providers import (
    CACHE_READ_TOKENS_COLUMN,
    CAMPAIGN_ID_COLUMN,
    CAMPAIGN_TABLE,
    DEPTH_CACHE_RATE_TABLE,
    INPUT_TOKENS_COLUMN,
    MEASURED_AT_COLUMN,
    CacheRateConflictError,
    DepthCacheError,
    DepthCacheRates,
    MeasuredCacheRate,
    UnplannedCampaignError,
    Usage,
    measure_cache_rate,
)

#: The Wednesday every fixed instant in this suite lands on — 2026-09-23,
#: the month §14.2's own verification date (2026-09-19) sits in.
WEDNESDAY = 23

#: The aware UTC instant builder: ``_at(2, 30)`` is Wednesday 02:30 UTC.
#: Every instant in the suite is UTC-aware because the store refuses
#: naive ones — the suite is not in the business of testing what the
#: module refuses before it begins.


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, WEDNESDAY, hour, minute, second, tzinfo=UTC)


#: The spine's ISO-8601 UTC text shape — millisecond precision, ``Z``
#: (``0111``'s own ``strftime`` form), which the row's instant column
#: carries.
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

#: A campaign id spelled once, for the tests that do not plant their own.
_CAMPAIGN = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"


def _usages(*pairs: tuple[int, int]) -> tuple[Usage, ...]:
    """A stream of Usage records from ``(input, cache_read)`` pairs.

    The two counts the measurement reads, in the record feature 192's
    completions carry them — cache reads a portion of the input, output
    tokens present but deliberately beside the point (the cost model's
    axis, not this feature's).
    """
    return tuple(
        Usage(input_tokens=inp, output_tokens=2, cache_read_tokens=cache)
        for inp, cache in pairs
    )


class _Count:
    """A usage-shaped value the store's own guards must refuse.

    Feature 192's :class:`~providers.Usage` already refuses a non-int or
    negative count at construction, so a real record can never carry one
    to the measurement — but the measurement recognises usages **by their
    parts**, and a duck-typed stream (a config layer's record, the loader's
    other class copy) can.  This stub is that stream: two counted parts,
    whatever values they hold, so the tests for the store's count guards
    exercise the guards rather than Usage's.
    """

    __slots__ = ("cache_read_tokens", "input_tokens")

    def __init__(self, inp, cache):
        self.input_tokens = inp
        self.cache_read_tokens = cache


def _stored_row(database: str, campaign: str) -> tuple | None:
    """The measured-rate row straight from the table, unparsed.

    A raw read rather than a call into the store, on the same grounds
    ``test_pin_store.stored_value`` states for the triple: several of
    these tests are about *what the store wrote* and *what it did not
    change*, and asking the store to confirm that would be asking the
    thing under test.
    """
    with closing(sqlite3.connect(sqlite_path_of(database))) as connection:
        return connection.execute(
            f"SELECT campaign_id, input_tokens, cache_read_tokens, measured_at "
            f"FROM {DEPTH_CACHE_RATE_TABLE} WHERE campaign_id = ?",
            (campaign,),
        ).fetchone()


# ── The measurement, persisted ────────────────────────────────────────────────


class TestMeasure:
    """The sentence's verb: measure the campaign, land the row, answer it."""

    def test_measures_the_campaign_and_lands_the_row(
        self, campaign_database, plant_campaign
    ):
        # The feature as one call.  Three depth-role-shaped calls — §14.2's
        # average is ~300K input a call — whose prefix was mostly served
        # from cache; the row holds the two totals, and the answer is the
        # row the table holds (``recorded``: this call wrote it).
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        record = store.measure(
            campaign,
            _usages((300_000, 288_000), (310_000, 300_000), (290_000, 282_000)),
            now=_at(2, 30),
        )
        assert record.campaign_id == campaign
        assert record.input_tokens == 900_000
        assert record.cache_read_tokens == 870_000
        assert record.hit_rate == Fraction(870_000, 900_000)
        assert record.recorded is True
        assert record.measured_at == _at(2, 30)

        row = _stored_row(campaign_database, campaign)
        assert row == (campaign, 900_000, 870_000, "2026-09-23T02:30:00.000Z")

    def test_the_rows_instant_is_the_spines_own_text(
        self, campaign_database, plant_campaign
    ):
        # Millisecond precision and a ``Z`` — ``0111``'s own
        # ``strftime`` form, the one grammar the campaign table's own
        # timestamps keep — so the measurement reads back beside the
        # campaign's records on one timeline.
        campaign = plant_campaign(campaign_database)
        DepthCacheRates(campaign_database).measure(
            campaign, _usages((30, 29)), now=_at(23, 59, 59)
        )
        stored = _stored_row(campaign_database, campaign)
        assert _ISO_UTC.match(stored[3])

    def test_a_zoned_now_is_converted_to_utc(
        self, campaign_database, plant_campaign
    ):
        # An instant is an instant: a caller handing 14:00 at +02:00 and
        # a caller handing 12:00 UTC measured at the same moment, and the
        # row says so in one grammar.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        record = store.measure(
            campaign,
            _usages((30, 29)),
            now=datetime(2026, 9, WEDNESDAY, 14, 0, 0, tzinfo=timezone(timedelta(hours=2))),
        )
        assert record.measured_at == _at(12)

    def test_a_naive_now_is_refused(self, campaign_database, plant_campaign):
        # A naive value names no instant, and a measurement stamped with
        # one could not be placed on the timeline the campaign's own
        # records keep time on.
        campaign = plant_campaign(campaign_database)
        with pytest.raises(DepthCacheError, match="timezone-aware"):
            DepthCacheRates(campaign_database).measure(
                campaign,
                _usages((30, 29)),
                now=datetime(2026, 9, WEDNESDAY, 12, 0, 0),  # noqa: DTZ001 - the refusal's subject
            )

    def test_the_totals_are_computed_not_trusted(
        self, campaign_database, plant_campaign
    ):
        # *Measured* is the sentence's own word: the store totals the
        # counts the usages carry rather than accepting a caller's
        # pre-formed ratio, so two streams with the same per-call shape
        # but different volumes land different rows — the arithmetic is
        # the store's, and a rate persisted on trust would be an estimate
        # wearing a measurement's authority.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        first = store.measure(campaign, _usages((30, 20)), now=_at(1))
        assert (first.input_tokens, first.cache_read_tokens) == (30, 20)

    def test_the_measurement_reads_only_the_two_counts(
        self, campaign_database, plant_campaign
    ):
        # A usage carrying the two counted parts and nothing else — not
        # even feature 192's output_tokens — is the accounting, because
        # the recognition reads what the measurement reads: output tokens
        # are the cost model's axis, and a field read but unused is a
        # field that would drift.
        campaign = plant_campaign(campaign_database)

        class BareUsage:
            __slots__ = ("cache_read_tokens", "input_tokens")

            def __init__(self, inp: int, cache: int):
                self.input_tokens = inp
                self.cache_read_tokens = cache

        record = DepthCacheRates(campaign_database).measure(
            campaign, (BareUsage(30, 29),), now=_at(1)
        )
        assert record.hit_rate == Fraction(29, 30)

    def test_the_table_is_created_lazily_by_the_first_write(
        self, campaign_database, plant_campaign
    ):
        # The member-owned table: absent before the first measurement,
        # present after it, and a read — ``get`` — never brings it into
        # being.  Composing the store created nothing; measuring created
        # the schema and the row together.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)

        def tables() -> set[str]:
            with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as cx:
                return {
                    name
                    for (name,) in cx.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }

        assert tables() == {CAMPAIGN_TABLE}
        assert store.get(campaign) is None
        assert tables() == {CAMPAIGN_TABLE}
        store.measure(campaign, _usages((30, 29)), now=_at(1))
        assert tables() == {CAMPAIGN_TABLE, DEPTH_CACHE_RATE_TABLE}

    def test_the_store_never_creates_the_campaign_table(self, database_url):
        # ``campaign`` is ``0111``'s and this store only ever probes it
        # read-only: on a database with no campaign table the refusal is
        # the same one an unplanned id meets — no campaign has ever been
        # planned here — and the schema is still ``0111``'s to bring.
        store = DepthCacheRates(database_url)
        with pytest.raises(UnplannedCampaignError, match="no campaign table"):
            store.measure(_CAMPAIGN, _usages((30, 29)), now=_at(1))
        with closing(sqlite3.connect(sqlite_path_of(database_url))) as cx:
            names = {
                name
                for (name,) in cx.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert CAMPAIGN_TABLE not in names

    def test_the_answer_is_the_row_the_table_holds(
        self, campaign_database, plant_campaign
    ):
        # Insert, then read back: the counts and the instant in the
        # answer are the row's, re-parsed through the same readers
        # ``get`` uses, so a caller holds one record shape from one
        # source of truth.
        campaign = plant_campaign(campaign_database)
        record = DepthCacheRates(campaign_database).measure(
            campaign, _usages((300_000, 288_000)), now=_at(2)
        )
        row = _stored_row(campaign_database, campaign)
        assert record.row() == {
            CAMPAIGN_ID_COLUMN: campaign,
            INPUT_TOKENS_COLUMN: 300_000,
            CACHE_READ_TOKENS_COLUMN: 288_000,
            MEASURED_AT_COLUMN: "2026-09-23T02:00:00.000Z",
        }
        assert record.row()[MEASURED_AT_COLUMN] == row[3]

    def test_two_campaigns_are_measured_independently(
        self, campaign_database, plant_campaign
    ):
        # One campaign is one run of the discovery loop, and each run's
        # rate is its own row: measuring a second campaign neither
        # disturbs the first's row nor answers from it.
        first = plant_campaign(campaign_database)
        second = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        one = store.measure(first, _usages((30, 29)), now=_at(1))
        two = store.measure(second, _usages((40, 10)), now=_at(2))
        assert one.campaign_id == first
        assert two.campaign_id == second
        assert store.get(first).hit_rate == Fraction(29, 30)
        assert store.get(second).hit_rate == Fraction(1, 4)


# ── One campaign, one measurement, one row ────────────────────────────────────


class TestIdempotence:
    """The re-issue story: the row is the measurement, and it is the fact."""

    def test_an_identical_re_issue_answers_the_stored_row(
        self, campaign_database, plant_campaign
    ):
        # A retry is the same measurement arriving twice: same campaign,
        # same totals — and the answer is the row the table holds,
        # including its original ``measured_at``, which a retry does not
        # move.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        stored = store.measure(campaign, _usages((300, 290)), now=_at(1))
        again = store.measure(campaign, _usages((100, 90), (200, 200)), now=_at(5))
        assert again.recorded is False
        assert again.measured_at == stored.measured_at == _at(1)
        assert (again.input_tokens, again.cache_read_tokens) == (300, 290)

    def test_the_campaign_id_is_canonicalized_before_the_row_is_matched(
        self, campaign_database, plant_campaign
    ):
        # The id joins the campaign table's ``id`` and every reader of
        # this row: a UUID object, the same text upper-cased, and the
        # text a braced literal spells are one campaign, so the second
        # spelling of the same measurement is an idempotent re-issue
        # rather than a second row.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        store.measure(uuid.UUID(campaign), _usages((30, 29)), now=_at(1))
        again = store.measure(campaign.upper(), _usages((30, 29)), now=_at(9))
        assert again.recorded is False
        with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as cx:
            count = cx.execute(
                f"SELECT COUNT(*) FROM {DEPTH_CACHE_RATE_TABLE}"
            ).fetchone()[0]
        assert count == 1

    def test_a_re_measurement_naming_different_totals_is_refused(
        self, campaign_database, plant_campaign
    ):
        # The same campaign cannot have hit cache at two rates — its
        # calls are what they are, and the totals are re-derivable from
        # the completions that served it and from nothing else.  The
        # refusal names both totals and both rates, because that is the
        # difference between an actionable refusal and a complaint.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        store.measure(campaign, _usages((30, 29)), now=_at(1))
        with pytest.raises(CacheRateConflictError) as excinfo:
            store.measure(campaign, _usages((32, 31)), now=_at(2))
        message = str(excinfo.value)
        assert "29/30" in message
        assert "31/32" in message
        assert campaign in message

    def test_the_conflict_leaves_the_stored_row_untouched(
        self, campaign_database, plant_campaign
    ):
        # The stored row is the fact, and a refused ask is not a write:
        # the row a subsequent read answers is the one the first
        # measurement landed.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        store.measure(campaign, _usages((30, 29)), now=_at(1))
        with pytest.raises(CacheRateConflictError):
            store.measure(campaign, _usages((32, 31)), now=_at(2))
        assert store.get(campaign).measured_at == _at(1)
        assert store.get(campaign).hit_rate == Fraction(29, 30)


# ── The store's premise: the campaign was planned ─────────────────────────────


class TestUnplanned:
    """The probe-not-create discipline, seen from the measuring side."""

    def test_refuses_a_campaign_nobody_planned(
        self, campaign_database, plant_campaign
    ):
        # A rate persisted for an id no campaign row holds is an
        # accounting for calls that were never placed, persisted beside
        # campaigns that placed them.
        plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        stranger = str(uuid.uuid4())
        with pytest.raises(UnplannedCampaignError, match=stranger):
            store.measure(stranger, _usages((30, 29)), now=_at(1))

    def test_the_refusal_names_the_planners_repair(self, campaign_database):
        # Plan the campaign, then measure its runs — the repair is the
        # campaign record, not the id and not this store.
        store = DepthCacheRates(campaign_database)
        with pytest.raises(UnplannedCampaignError, match="Plan the campaign"):
            store.measure(_CAMPAIGN, _usages((30, 29)), now=_at(1))

    def test_a_malformed_id_is_refused_before_any_database_is_opened(
        self, campaign_database
    ):
        # The ask is validated first, so config noise is refused without
        # touching a database — and the refusal is this feature's own
        # vocabulary, not a sqlite error about a table the caller never
        # asked about.
        store = DepthCacheRates(campaign_database)
        with pytest.raises(DepthCacheError, match="not a UUID"):
            store.measure("not-a-campaign", _usages((30, 29)), now=_at(1))
        with pytest.raises(DepthCacheError, match="not a UUID"):
            store.get("not-a-campaign")


# ── The measurement's refusals ────────────────────────────────────────────────


class TestMeasurementRefusals:
    """What the totals computation refuses, and why each is a non-measurement."""

    @pytest.fixture
    def store(self, campaign_database, plant_campaign) -> DepthCacheRates:
        self.campaign = plant_campaign(campaign_database)
        return DepthCacheRates(campaign_database)

    def test_refuses_a_string_of_usages(self, store):
        # A string is iterable but is not a stream of token accountings —
        # reading one would yield its characters, and a measurement
        # nobody took is worse than a refusal.
        with pytest.raises(DepthCacheError, match="iterable of Usage records"):
            store.measure(self.campaign, "usages", now=_at(1))

    def test_refuses_a_non_iterable(self, store):
        with pytest.raises(DepthCacheError, match="iterable of Usage records"):
            store.measure(self.campaign, 42, now=_at(1))

    def test_refuses_an_item_that_is_not_a_usage(self, store):
        # A value carrying no counts is not an accounting; padding the
        # missing counts with guesses would be measuring a campaign on
        # calls nobody reported.
        with pytest.raises(DepthCacheError, match="must be Usage records"):
            store.measure(self.campaign, (42,), now=_at(1))

    @pytest.mark.parametrize("field", ["input", "cache"])
    def test_refuses_a_count_that_is_not_an_int(self, store, field):
        # 29.5 tokens is a number but not a count a provider reports —
        # and the duck-typed seam is where such a value can reach the
        # measurement, Usage having refused its own copy at construction.
        bogus = (
            _Count(29.5, 29)
            if field == "input"
            else _Count(30, 29.5)
        )
        with pytest.raises(DepthCacheError, match="must be an int"):
            store.measure(self.campaign, (bogus,), now=_at(1))

    def test_refuses_a_negative_count(self, store):
        # A negative count is not a report a provider could make, and
        # totalled silently it would subtract cache the campaign never
        # read — refused on the duck-typed seam, where Usage's own guard
        # cannot have been the one to catch it.
        with pytest.raises(DepthCacheError, match="non-negative"):
            store.measure(self.campaign, (_Count(30, -1),), now=_at(1))

    def test_refuses_a_usage_whose_cache_read_exceeds_its_own_input(self, store):
        # The per-call invariant, checked per call: the cached prefix is
        # part of the prompt, so one call cannot read more cache than it
        # had prompt — and a campaign total would hide a single nonsense
        # report inside sane ones.
        with pytest.raises(DepthCacheError, match="more cache than it had prompt"):
            store.measure(
                self.campaign,
                _usages((30, 29), (30, 31), (30, 29)),
                now=_at(1),
            )

    def test_refuses_a_measurement_of_no_calls(self, store):
        # There is no cache hit rate to persist for a campaign whose
        # calls were not accounted; a rate persisted from an empty stream
        # would be an estimate wearing a measurement's authority.
        with pytest.raises(DepthCacheError, match="no calls"):
            store.measure(self.campaign, (), now=_at(1))

    def test_refuses_a_stream_that_totals_zero_input(self, store):
        # The rate's denominator is the campaign's billed input, and the
        # depth role's calls carry the history — a zero-input stream
        # names calls the depth role never placed.
        with pytest.raises(DepthCacheError, match="zero input"):
            store.measure(self.campaign, _usages((0, 0), (0, 0)), now=_at(1))


# ── The read side ─────────────────────────────────────────────────────────────


class TestGet:
    """The read: what the store answers, and what it refuses to launder."""

    def test_answers_none_for_an_unmeasured_campaign(
        self, campaign_database, plant_campaign
    ):
        # Planned but never measured — the honest answer is that nothing
        # has accounted this campaign's calls here, not zero and not an
        # exception.
        plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        assert store.get(str(uuid.uuid4())) is None

    def test_answers_the_row_with_this_call_writing_nothing(
        self, campaign_database, plant_campaign
    ):
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        store.measure(campaign, _usages((300_000, 288_000)), now=_at(2))
        record = store.get(campaign)
        assert isinstance(record, MeasuredCacheRate)
        assert record.recorded is False
        assert record.hit_rate == Fraction(288_000, 300_000)
        assert record.measured_at == _at(2)

    def test_a_read_never_rewrites_the_instant(
        self, campaign_database, plant_campaign
    ):
        # A read wrote nothing, so the row it answered is unchanged —
        # pinned by reading the raw column again after the ``get``.
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        store.measure(campaign, _usages((30, 29)), now=_at(1))
        before = _stored_row(campaign_database, campaign)
        store.get(campaign)
        assert _stored_row(campaign_database, campaign) == before

    def test_the_id_is_canonicalized_on_the_way_in(
        self, campaign_database, plant_campaign
    ):
        campaign = plant_campaign(campaign_database)
        store = DepthCacheRates(campaign_database)
        store.measure(campaign, _usages((30, 29)), now=_at(1))
        assert store.get(uuid.UUID(campaign)).hit_rate == Fraction(29, 30)


class TestCorruptRows:
    """The read side re-verifies: corruption is refused, not laundered."""

    @pytest.fixture
    def measured(self, campaign_database, plant_campaign):
        # One planted campaign and one measured row, with the database
        # handed back for the test's raw UPDATE against it.
        campaign = plant_campaign(campaign_database)
        DepthCacheRates(campaign_database).measure(
            campaign, _usages((30, 29)), now=_at(1)
        )
        return campaign_database, campaign

    def _corrupt(self, database: str, campaign: str, column: str, value) -> None:
        with closing(sqlite3.connect(sqlite_path_of(database))) as cx, cx:
            cx.execute(
                f"UPDATE {DEPTH_CACHE_RATE_TABLE} SET {column} = ? "
                f"WHERE campaign_id = ?",
                (value, campaign),
            )

    def test_refuses_a_row_whose_cache_read_exceeds_its_input(self, measured):
        # The invariant the write path enforces per call, restated on the
        # read: a rate above 1.0 reading back as a measurement would be a
        # campaign billed for more cache than it had prompt — a figure no
        # selection should ever be justified by.
        database, campaign = measured
        self._corrupt(database, campaign, CACHE_READ_TOKENS_COLUMN, 31)
        with pytest.raises(DepthCacheError, match="more cache was read"):
            DepthCacheRates(database).get(campaign)

    def test_refuses_a_row_whose_input_is_zero(self, measured):
        # A zero denominator is a rate nobody could have measured, and
        # the measurement gate itself refuses it before writing.
        database, campaign = measured
        self._corrupt(database, campaign, INPUT_TOKENS_COLUMN, 0)
        with pytest.raises(DepthCacheError, match="must be positive"):
            DepthCacheRates(database).get(campaign)

    def test_refuses_a_row_whose_count_is_not_an_integer(self, measured):
        # SQLite's INTEGER affinity holds a float only if something wrote
        # one; coercing it would launder a truncated column into a rate
        # nobody measured.
        database, campaign = measured
        self._corrupt(database, campaign, INPUT_TOKENS_COLUMN, 29.5)
        with pytest.raises(DepthCacheError, match="not the integer count"):
            DepthCacheRates(database).get(campaign)

    def test_refuses_a_row_whose_instant_does_not_parse(self, measured):
        # Text another dialect wrote, or an editing accident: an instant
        # that cannot be read is a measurement this record cannot report.
        database, campaign = measured
        self._corrupt(database, campaign, MEASURED_AT_COLUMN, "yesterday, noon-ish")
        with pytest.raises(DepthCacheError, match="does not parse"):
            DepthCacheRates(database).get(campaign)

    def test_refuses_a_row_whose_instant_has_no_offset(self, measured):
        # It parses but names no instant, so it cannot be placed beside
        # the campaign's own records on any timeline.
        database, campaign = measured
        self._corrupt(database, campaign, MEASURED_AT_COLUMN, "2026-09-23T01:00:00.000")
        with pytest.raises(DepthCacheError, match="without a UTC offset"):
            DepthCacheRates(database).get(campaign)

    def test_refuses_a_row_whose_instant_is_blank(self, measured):
        database, campaign = measured
        self._corrupt(database, campaign, MEASURED_AT_COLUMN, "   ")
        with pytest.raises(DepthCacheError, match="not an ISO-8601 UTC instant"):
            DepthCacheRates(database).get(campaign)


# ── Construction and resolution ───────────────────────────────────────────────


class TestResolution:
    """How a store comes to exist, and what it refuses to be."""

    def test_a_url_is_required(self):
        with pytest.raises(DepthCacheError, match="non-empty database URL"):
            DepthCacheRates("   ")

    def test_resolve_answers_none_when_nothing_names_a_store(self):
        # Absent is not an error: a deployment without a relational store
        # composes no cache-rate component — a discoverable state, and
        # the caller that must persist a measurement treats the ``None``
        # as a refusal to proceed.
        assert DepthCacheRates.resolve({}) is None
        assert DepthCacheRates.resolve({"DATABASE_URL": "   "}) is None

    def test_resolve_builds_the_store_the_deployment_names(self):
        store = DepthCacheRates.resolve({"DATABASE_URL": "sqlite:///somewhere/rates.db"})
        assert store is not None
        assert store.database_url == "sqlite:///somewhere/rates.db"

    def test_construction_touches_no_file(self, tmp_path):
        # Composition-time work must not touch the disk: the path is
        # resolved — and a URL this member cannot speak is refused —
        # only when an operation needs it.
        url = f"sqlite:///{tmp_path / 'never-opened.db'}"
        DepthCacheRates(url)
        assert not (tmp_path / "never-opened.db").exists()

    def test_a_url_this_member_cannot_speak_is_refused_by_name(self):
        # The spec's single-machine allowance is what a stdlib store can
        # speak, and the refusal names the variable to fix.
        store = DepthCacheRates("postgres://localhost:5432/rates")
        with pytest.raises(DepthCacheError, match="unsupported DATABASE_URL scheme"):
            _ = store.path

    def test_an_in_memory_url_is_refused(self):
        # A measured rate must outlive the measuring call — the selection
        # it justifies and the auditor that re-derives it run in another
        # process entirely.
        store = DepthCacheRates("sqlite:///:memory:")
        with pytest.raises(DepthCacheError, match="in-memory"):
            _ = store.path

    def test_the_repr_names_the_store(self):
        store = DepthCacheRates("sqlite:///somewhere/rates.db")
        assert "sqlite:///somewhere/rates.db" in repr(store)


class TestModuleSpelling:
    """The module-level call: the act without holding a store."""

    def test_measures_through_the_named_store(
        self, campaign_database, plant_campaign
    ):
        campaign = plant_campaign(campaign_database)
        record = measure_cache_rate(
            campaign,
            _usages((300_000, 288_000)),
            now=_at(2),
            database_url=campaign_database,
        )
        assert record.recorded is True
        assert record.hit_rate == Fraction(288_000, 300_000)

    def test_the_env_var_names_the_store_when_no_url_is_supplied(
        self, campaign_database, plant_campaign, monkeypatch
    ):
        campaign = plant_campaign(campaign_database)
        monkeypatch.setenv("DATABASE_URL", campaign_database)
        record = measure_cache_rate(campaign, _usages((30, 29)), now=_at(1))
        assert record.recorded is True

    def test_nothing_naming_a_store_is_refused_by_name(self, monkeypatch):
        # A measurement that quietly skipped its write would leave the
        # campaign's economics unaudited — and the next campaign's
        # selection resting on a number that exists nowhere — so the
        # refusal names the variable rather than doing nothing.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(DepthCacheError, match="nothing names a store"):
            measure_cache_rate(_CAMPAIGN, _usages((30, 29)), env={})
