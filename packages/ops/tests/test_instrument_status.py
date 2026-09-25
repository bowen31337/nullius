"""Feature 342's route: GET /metrics/instrument-status, docs §5.4's three
binary lamps.

app_spec.xml, "Observability & Dashboards", feature 342 — *System exposes
GET /metrics/instrument-status which returns canary, KS guard and ingest
lag as three binary lamps* — with the domain's API summary spelling it
*"Return canary, KS guard and ingest lag status"*.  docs/design.md §5.4 is
the doctrine behind it::

    canary     ok        replay is deterministic
    ks guard   ok        nulls indistinguishable
    ingest     1.2s      feed lag

*"Three binary lamps at the top of the left rail, because everything below
them is worthless if any is out."*

This suite pins the *route's* law — the seam, not the three instruments:

* the route is exactly ``/metrics/instrument-status``, carried on the
  endpoint as well as spelled as a module constant, so the spec's row and
  the component cannot drift;
* ``get()`` takes no arguments and answers the whole rail — three lamps,
  never one instrument's detail, because the sentence asks for *three
  binary lamps*;
* each lamp is the owning member's own read, never re-spelled here:
  §12's halt through feature 143's canary store, §7.4's detectability
  reading through feature 123's nulloracle journal judged against feature
  124's own ``VOID_THRESHOLD``, and the recorded feed silence through this
  member's own feature-350 row — pinned by pointing the endpoint at a
  *real* SQLite file, writing each lamp through the owning member's own
  verb, and asserting the answer agrees;
* the KS lamp reports on the campaign the *top-line figure* is attributed
  to (the newest row of feature 267's own trend read), and the answer
  carries that campaign and the p-value, so the bit is reconstructible;
* the three absences are held apart from one another and from a broken
  read: no campaign closed out, no guard run for the named campaign, no
  recorded feed reading, no configured band — each answered as an absence,
  never as a lit lamp and never as a refusal; and the two halves of the
  ingest watchdog stay distinguishable on the answer;
* the response validates what it holds (a lamp that is not a genuine bool
  with ``int`` refused first, a p-value outside ``[0, 1]``, a negative or
  non-finite silence, a band that is not strictly positive, a lamp carried
  without the number that decides it, a bit that *disagrees with its own
  number*), and is frozen;
* a read that fails is translated into this member's vocabulary — once per
  lamp, chained, and never answered around with a lamp nobody read; and
* building performs no I/O of any kind, and this module reaches no sibling
  member at module scope or build time — the cross-member reads are the
  deferred, declared ``canary`` and ``nulloracle`` doors (and the scoring
  door feature 341's route already opened).

The fixtures mirror ``test_fdr_route.py`` and ``test_regime_coverage.py``:
a real SQLite file under ``tmp_path`` with ``DATABASE_URL`` pointed at it,
so the route is exercised end to end through the members' own stores rather
than through hand-rolled doubles that could agree with a misreading here.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import canary
import nulloracle
import pytest
import scoring
from ops import (
    FEED_STALENESS_METRIC,
    FEED_STALENESS_THRESHOLD_ENV,
    INSTRUMENT_STATUS_ROUTE,
    LAMP_NAMES,
    OPS_INSTRUMENT_STATUS_COMPONENT_NAME,
    InstrumentStatusEndpoint,
    InstrumentStatusError,
    InstrumentStatusResponse,
    LiveMetricError,
    require_canary,
    require_nulloracle,
)
from ops.live_metrics import LIVE_METRICS, LiveMetricsStore

#: The campaign every fixture writes, in the canonical UUID text feature
#: 267's store and feature 123's guard store both key on.
CAMPAIGN = "11111111-1111-4111-8111-111111111111"

#: A second campaign, so *newest* is a real ordering rather than a single
#: row — the attribution's whole point.
NEWER_CAMPAIGN = "22222222-2222-4222-8222-222222222222"

#: A recorded silence, in seconds — docs §5.4's own example reading
#: (``ingest 1.2s``).
LAG_SECONDS = 1.2

#: The instant that reading was labelled with, as feature 350 stores it.
LAG_AT = "2026-09-01T00:00:00Z"

#: The instants a recorded determinism break carries — feature 143's own
#: two labels, taken from its suite's fixtures so this route reads the row
#: the canary member's own tests write.
DETECTED_AT = datetime(2026, 9, 1, 3, 0, 0, tzinfo=UTC)
HALTED_AT = datetime(2026, 9, 1, 3, 0, 1, tzinfo=UTC)

#: A band the recorded silence is comfortably inside.
BAND_SECONDS = 5.0

#: A p-value well above feature 124's level: nulls indistinguishable, the
#: lamp lit.
INDISTINGUISHABLE_P = 0.9


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "instrument-status.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def halt_store(store_url: str) -> canary.CanaryHaltStore:
    """The *canary member's own* halt store over the test database."""
    return canary.CanaryHaltStore(store_url)


@pytest.fixture
def guard(store_url: str) -> nulloracle.KsGuard:
    """The *nulloracle member's own* guard store over the test database."""
    return nulloracle.KsGuard(store_url)


@pytest.fixture
def trend(store_url: str) -> scoring.FdrDeployStore:
    """The *scoring member's own* trend store over the test database."""
    return scoring.FdrDeployStore(store_url)


@pytest.fixture
def live(store_url: str) -> LiveMetricsStore:
    """This member's own live-metrics store over the test database."""
    return LiveMetricsStore(store_url)


@pytest.fixture
def endpoint(store_url: str) -> InstrumentStatusEndpoint:
    """The route over the test database, with the ingest band configured."""
    endpoint = InstrumentStatusEndpoint.from_env(
        {"DATABASE_URL": store_url, FEED_STALENESS_THRESHOLD_ENV: str(BAND_SECONDS)}
    )
    assert endpoint is not None
    return endpoint


class _Pair:
    """A carrier exposing feature 266's two figures, duck-typed.

    ``FdrDeployStore.persist`` reads the calibration *pair* by what the
    carrier exposes rather than by its class (the loader imports members
    under synthetic names, so an ``isinstance`` would refuse the very pair
    composition produced), and this suite only needs a row in the trend —
    the figure itself is feature 267's, and this route never reads it.
    """

    def __init__(self, sensitivity: float = 0.8, specificity: float = 0.9) -> None:
        self.sensitivity = sensitivity
        self.specificity = specificity


def _plan_campaign(guard: nulloracle.KsGuard, campaign: str) -> None:
    """Plan a campaign — the row §7.4's guard joins its p-value to.

    Written through the guard store's own connection because the campaign
    table belongs to feature 104's planner, which this member neither owns
    nor imports; the guard's own ``_require_campaign`` refuses a campaign
    nobody planned, so the row must exist before any lamp is lit.
    """
    # The store's own connection (private by convention): the campaign
    # table is not this member's, so there is no public door to it here.
    connection = guard._connect()
    with connection:
        connection.execute(
            f"INSERT INTO {nulloracle.CAMPAIGN_TABLE} "
            "(id, campaign_type, workspace_count, null_fraction) "
            "VALUES (?, 'discovery', 10, 0.5)",
            (campaign,),
        )


def _close_campaign(
    trend: scoring.FdrDeployStore,
    campaign: str,
    *,
    computed_at: str,
) -> None:
    """Close a campaign out — one row of feature 267's own trend read."""
    trend.persist(campaign, _Pair(), computed_at=computed_at)


def _record_halt(halt_store: canary.CanaryHaltStore) -> canary.DreamHalt:
    """Record a determinism break through feature 143's own writer.

    The pair is a real frozen policy/tree and the replay is the member's
    own ``replay_pair``, so the row feature 143 persists is the row this
    route's first lamp reads — not a hand-written INSERT that could agree
    with a misreading here.
    """
    policy = canary.CanaryPolicy.freeze(
        version="canary-v1",
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}, "threshold": 0.7},
    )
    tree = canary.CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
            "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
            "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
        }
    )
    replayed = 0.8 * 0.3 + 0.6 * 0.7
    pair = canary.CanaryReferencePair(
        policy=policy,
        tree=tree,
        recorded_score=replayed + 0.5,
        id=None,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return halt_store.halt(
        pair,
        canary.replay_pair(pair),
        detected_at=DETECTED_AT,
        halted_at=HALTED_AT,
    )


def _guard_campaign(
    guard: nulloracle.KsGuard,
    campaign: str,
    *,
    samples: tuple[list[float], list[float]],
) -> float:
    """Run §7.4's guard through feature 123's own verb; answer its p-value."""
    null_scores, real_scores = samples
    return float(guard.guard(campaign, null_scores, real_scores).pvalue)


#: Two samples §7.4's test cannot separate — the nulls are indistinguishable,
#: so the p-value is high and the lamp stays lit.
SAME_SAMPLES: tuple[list[float], list[float]] = ([0.1] * 20, [0.1] * 20)

#: Two samples §7.4's test separates decisively — the p-value collapses well
#: below feature 124's level and the lamp goes out.
SEPARATED_SAMPLES: tuple[list[float], list[float]] = ([0.1] * 50, [0.6] * 50)


# -- The route's name ----------------------------------------------------------


def test_the_route_is_the_one_the_spec_writes() -> None:
    # The spec's API summary row for the Observability domain, spelled
    # once: "GET /metrics/instrument-status — Return canary, KS guard and
    # ingest lag status".  Pinned as a literal so a rename cannot quietly
    # pass by agreeing with itself.
    assert INSTRUMENT_STATUS_ROUTE == "/metrics/instrument-status"
    assert InstrumentStatusEndpoint.route == INSTRUMENT_STATUS_ROUTE


def test_the_component_name_is_the_member_prefixed_one() -> None:
    # The component name is the route's, member-first and route-second —
    # feature 341's `ops-fdr-deploy` and feature 343's
    # `ops-regime-coverage` beside it — so a composed application's
    # `order` sorts the category's read-only routes as peers rather than
    # across prefix families.
    assert OPS_INSTRUMENT_STATUS_COMPONENT_NAME == "ops-instrument-status"


def test_the_rail_is_the_three_lamps_the_design_draws() -> None:
    # docs §5.4's rail, in its own order and with its own three names:
    # canary, KS guard, ingest.  Four lamps, a fourth name or a renamed
    # lamp would be a rail the design does not draw and the spec's
    # sentence does not ask for.
    assert LAMP_NAMES == ("canary", "ks_guard", "ingest")


def test_the_ingest_lamp_reads_a_metric_the_store_publishes() -> None:
    # The recorded silence is feature 350's row, and the name this route
    # asks for is one of the four the store's own value layer validates —
    # so the route cannot ask for a spelling the store would refuse.
    assert FEED_STALENESS_METRIC == "feed_staleness_s"
    assert FEED_STALENESS_METRIC in LIVE_METRICS


# -- The route's answer --------------------------------------------------------


def test_the_route_answers_three_lamps(
    endpoint: InstrumentStatusEndpoint,
    halt_store: canary.CanaryHaltStore,
    guard: nulloracle.KsGuard,
    trend: scoring.FdrDeployStore,
    live: LiveMetricsStore,
) -> None:
    # The feature sentence at its seam: canary, KS guard and ingest lag,
    # one bit each, with the top-line figure's campaign attributed beside
    # them.
    _plan_campaign(guard, CAMPAIGN)
    _guard_campaign(guard, CAMPAIGN, samples=SAME_SAMPLES)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    response = endpoint.get()
    assert isinstance(response, InstrumentStatusResponse)
    assert response.canary is True
    assert response.ks_guard is True
    assert response.ingest is True
    assert response.campaign == CAMPAIGN
    assert response.lamps == {"canary": True, "ks_guard": True, "ingest": True}
    assert response.absent == ()
    assert response.failing == ()
    assert bool(response) is True


def test_the_canary_lamp_is_feature_143s_own_bit(
    endpoint: InstrumentStatusEndpoint, halt_store: canary.CanaryHaltStore
) -> None:
    # The lamp is the canary member's monotone halt, read through its own
    # store, in both directions — a second spelling of *has a break been
    # recorded* here would be a second place §12's halt could drift from
    # the bit that pages an operator.
    assert endpoint.get().canary is True
    assert halt_store.halted() is False
    _record_halt(halt_store)
    assert halt_store.halted() is True
    assert endpoint.get().canary is False


def test_the_ks_lamp_is_feature_123s_reading_against_feature_124s_level(
    endpoint: InstrumentStatusEndpoint, guard: nulloracle.KsGuard,
    trend: scoring.FdrDeployStore,
) -> None:
    # §7.4's reading, judged against the level the *nulloracle member*
    # spells: a p-value at or above VOID_THRESHOLD leaves the nulls
    # indistinguishable and the lamp lit; a p-value strictly below it is
    # detectable and the lamp goes out.  Both directions, over the same
    # store, so the comparison is the member's and not a restatement here.
    _plan_campaign(guard, CAMPAIGN)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")

    high = _guard_campaign(guard, CAMPAIGN, samples=SAME_SAMPLES)
    assert high >= float(nulloracle.VOID_THRESHOLD)
    lit = endpoint.get()
    assert lit.ks_pvalue == high
    assert lit.ks_guard is True

    low = _guard_campaign(guard, CAMPAIGN, samples=SEPARATED_SAMPLES)
    assert low < float(nulloracle.VOID_THRESHOLD)
    out = endpoint.get()
    assert out.ks_pvalue == low
    assert out.ks_guard is False
    assert out.failing == ("ks_guard",)


def test_the_ks_lamp_reports_on_the_campaign_the_top_line_names(
    endpoint: InstrumentStatusEndpoint,
    guard: nulloracle.KsGuard,
    trend: scoring.FdrDeployStore,
) -> None:
    # The attribution, and the reason this route can be read beside
    # feature 341's figure: the lamp reports the guard finding for the
    # *newest* row of feature 267's own trend read — the campaign the
    # top-line numeral belongs to — and says which campaign that was.
    _plan_campaign(guard, CAMPAIGN)
    _plan_campaign(guard, NEWER_CAMPAIGN)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    _close_campaign(trend, NEWER_CAMPAIGN, computed_at="2026-08-02T00:00:00Z")

    # The older campaign is guarded and detectable; the newer one is
    # indistinguishable.  The lamp must report the newer.
    _guard_campaign(guard, CAMPAIGN, samples=SEPARATED_SAMPLES)
    newer_p = _guard_campaign(
        guard, NEWER_CAMPAIGN, samples=SAME_SAMPLES,
    )

    response = endpoint.get()
    assert response.campaign == NEWER_CAMPAIGN
    assert response.ks_pvalue == newer_p
    assert response.ks_guard is True


def test_the_route_reads_the_stores_every_time(
    endpoint: InstrumentStatusEndpoint, live: LiveMetricsStore
) -> None:
    # No memo of a previous rail: the nightly runner, a campaign job and
    # the order path all write from other processes, so a cached rail
    # would make the operator's view of the instruments a fact about when
    # the surface started rather than about what they are doing.
    assert endpoint.get().ingest_lag_seconds is None
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    assert endpoint.get().ingest_lag_seconds == LAG_SECONDS


def test_the_ingest_lamp_is_feature_350s_newest_recorded_reading(
    endpoint: InstrumentStatusEndpoint, live: LiveMetricsStore
) -> None:
    # The recorded silence is this member's own table, and *newest* is the
    # store's own ordering rather than a second ORDER BY here: two rows,
    # the later one's label and value are what the rail reports.
    live.record(FEED_STALENESS_METRIC, 4.0, logged_at="2026-08-31T00:00:00Z")
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    response = endpoint.get()
    assert response.ingest_lag_seconds == LAG_SECONDS
    assert response.ingest_read_at == LAG_AT


def test_the_ingest_lamp_judges_section_13_3s_boundary_strictly(
    endpoint: InstrumentStatusEndpoint, live: LiveMetricsStore
) -> None:
    # §13.3's row is *staleness > threshold*, so a silence of exactly the
    # band is inside it: the lamp stays lit at equality and goes out
    # strictly past it.  The boundary every member of this workspace
    # shares (feature 328's judgement, feature 314's posture), applied to
    # this route's own reading.
    live.record(FEED_STALENESS_METRIC, BAND_SECONDS, logged_at=LAG_AT)
    at_band = endpoint.get()
    assert at_band.ingest_lag_seconds == BAND_SECONDS
    assert at_band.ingest is True

    live.record(FEED_STALENESS_METRIC, BAND_SECONDS + 0.001, logged_at=LAG_AT)
    past_band = endpoint.get()
    assert past_band.ingest is False
    assert past_band.failing == ("ingest",)


def test_the_route_reads_no_clock(
    endpoint: InstrumentStatusEndpoint, live: LiveMetricsStore
) -> None:
    # The reading's instant is the row's own label, carried rather than
    # re-stamped: a route that measured the silence from its own wall
    # clock could not be reconciled with feature 350's `logged_at` and
    # would be answering a different quantity on every call.
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    response = endpoint.get()
    assert response.ingest_read_at == LAG_AT


def test_the_answer_exposes_the_rail_as_a_mapping(
    endpoint: InstrumentStatusEndpoint,
    guard: nulloracle.KsGuard,
    trend: scoring.FdrDeployStore,
    live: LiveMetricsStore,
) -> None:
    # docs §5.4's rail, as the shape a render reaches for: the three lamp
    # names mapped to their bits, in the design's own order.  A lamp that
    # is out or absent still holds its seat in the mapping — a render that
    # dropped an unmeasured lamp would draw a shorter rail than the design
    # and hide the missing instrument rather than showing it dark.
    _plan_campaign(guard, CAMPAIGN)
    _guard_campaign(guard, CAMPAIGN, samples=SAME_SAMPLES)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    lamps = endpoint.get().lamps
    assert list(lamps) == list(LAMP_NAMES)
    assert lamps == {"canary": True, "ks_guard": True, "ingest": True}


def test_the_rail_mapping_keeps_a_seat_for_an_absent_lamp(
    endpoint: InstrumentStatusEndpoint,
) -> None:
    # An absent lamp keeps its seat in the mapping and holds None there: a
    # render that dropped an unmeasured lamp would draw a shorter rail than
    # the design draws and hide the missing instrument rather than showing
    # it dark.
    lamps = endpoint.get().lamps
    assert list(lamps) == list(LAMP_NAMES)
    assert lamps == {"canary": True, "ks_guard": None, "ingest": None}


def test_the_lamps_mapping_is_a_fresh_view_each_time() -> None:
    # The mapping is a view *over* the three fields, not a second record
    # of the rail: a caller that mutates the dict it was handed cannot
    # change this value's answer.
    response = InstrumentStatusResponse(canary=True)
    lamps = response.lamps
    lamps["canary"] = False
    lamps["ks_guard"] = True
    assert response.lamps == {"canary": True, "ks_guard": None, "ingest": None}


def test_get_takes_no_arguments() -> None:
    # A GET over the deployment's instruments has no body and no campaign
    # to state; a filtered ask (one lamp, another campaign) is the store's
    # own read, not this route's.
    signature = inspect.signature(InstrumentStatusEndpoint.get)
    assert list(signature.parameters) == ["self"]


# -- Absent lamps, held apart --------------------------------------------------


def test_the_canary_lamp_is_never_absent(endpoint: InstrumentStatusEndpoint) -> None:
    # A database the store can open answers one bit: *no rows* is
    # *dreaming runs*, which is a measurement of the halt table's content
    # and not the absence of one.  So this lamp is the one that is never
    # absent on a composed route.
    response = endpoint.get()
    assert response.canary is True
    assert "canary" not in response.absent


def test_the_ks_lamp_is_absent_when_no_campaign_is_closed_out(
    endpoint: InstrumentStatusEndpoint,
) -> None:
    # No campaign has been closed out, so there is no campaign for a guard
    # reading to belong to.  The lamp is absent — and the answer names the
    # absence rather than reporting a lit lamp for a finding nobody made.
    response = endpoint.get()
    assert response.ks_guard is None
    assert response.ks_pvalue is None
    assert response.campaign is None
    assert "ks_guard" in response.absent
    assert "ks_guard" not in response.failing


def test_the_ks_lamp_is_absent_when_the_guard_has_not_run(
    endpoint: InstrumentStatusEndpoint, trend: scoring.FdrDeployStore
) -> None:
    # The campaign is known and the finding is not: feature 123's own
    # `load` answers None for *"a campaign the orchestrator has created and
    # no job has read yet"*, and an unguarded campaign is **not** a passing
    # one — `ks_pvalue` is NULL until the guard fills it, so a lamp that
    # read green here would certify the one state §7.4 exists to catch.
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    response = endpoint.get()
    assert response.campaign == CAMPAIGN
    assert response.ks_pvalue is None
    assert response.ks_guard is None
    assert response.absent == ("ks_guard", "ingest")


def test_no_campaign_and_no_finding_are_different_absences(
    endpoint: InstrumentStatusEndpoint, trend: scoring.FdrDeployStore
) -> None:
    # The distinction an operator chasing a dark lamp needs first: *the
    # trend names no campaign* and *the named campaign is unguarded* leave
    # different fields present.  Both leave the lamp absent — neither is a
    # refusal — but only the second says which campaign is waiting.
    unnamed = endpoint.get()
    assert unnamed.campaign is None
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    named = endpoint.get()
    assert named.campaign == CAMPAIGN
    assert named.ks_guard is None


def test_the_ingest_lamp_is_absent_without_a_recorded_reading(
    endpoint: InstrumentStatusEndpoint,
) -> None:
    # Nothing has measured the feed, so there is no silence to judge.  The
    # configured band is still carried — *the knob is set and nothing has
    # been measured* is exactly the half a half-wired watchdog shows.
    response = endpoint.get()
    assert response.ingest is None
    assert response.ingest_lag_seconds is None
    assert response.ingest_read_at is None
    assert response.threshold_seconds == BAND_SECONDS
    assert "ingest" in response.absent


def test_the_ingest_lamp_is_absent_without_a_configured_band(
    store_url: str, live: LiveMetricsStore
) -> None:
    # §13.3 says "threshold" and names no number, so the band is
    # configuration; a reading with no band is *half a watchdog*, and this
    # route answers it as an absence rather than judging against nothing.
    # The reading itself is still carried, so the operator sees what was
    # measured while the band is missing.
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    endpoint = InstrumentStatusEndpoint.from_env({"DATABASE_URL": store_url})
    assert endpoint is not None
    response = endpoint.get()
    assert response.ingest is None
    assert response.threshold_seconds is None
    assert response.ingest_lag_seconds == LAG_SECONDS
    assert response.ingest_read_at == LAG_AT
    assert "ingest" in response.absent
    assert "ingest" not in response.failing


def test_the_two_halves_of_the_watchdog_are_distinguishable(
    store_url: str, live: LiveMetricsStore
) -> None:
    # The whole reason the response keeps the halves apart: an operator
    # whose watchdog is half-wired needs to see *which* half.  No band and
    # no reading is the only state with neither field.
    bare = InstrumentStatusEndpoint.from_env({"DATABASE_URL": store_url})
    assert bare is not None
    nothing = bare.get()
    assert nothing.threshold_seconds is None
    assert nothing.ingest_lag_seconds is None

    half = InstrumentStatusEndpoint.from_env(
        {"DATABASE_URL": store_url, FEED_STALENESS_THRESHOLD_ENV: str(BAND_SECONDS)}
    )
    assert half is not None
    banded = half.get()
    assert banded.threshold_seconds == BAND_SECONDS
    assert banded.ingest_lag_seconds is None

    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    measured = bare.get()
    assert measured.threshold_seconds is None
    assert measured.ingest_lag_seconds == LAG_SECONDS


def test_an_absent_lamp_is_not_a_failing_one(
    endpoint: InstrumentStatusEndpoint,
) -> None:
    # The conflation this route refuses: a caller that treated *never
    # read* as *out* would report an unmeasured instrument as a broken one
    # — and would turn the rail dark for a deployment that has simply not
    # run a census yet.
    response = endpoint.get()
    assert response.absent == ("ks_guard", "ingest")
    assert response.failing == ()


def test_an_absent_lamp_is_not_a_lit_one() -> None:
    # The other direction: a rail with an unmeasured instrument is not a
    # rail that may be believed, so `bool` is conservative — §5.4's
    # *"everything below them is worthless if any is out"*.
    assert bool(InstrumentStatusResponse(canary=True)) is False
    assert bool(InstrumentStatusResponse(canary=False)) is False
    assert (
        bool(
            InstrumentStatusResponse(
                canary=True,
                ks_guard=True,
                ingest=True,
                campaign=CAMPAIGN,
                ks_pvalue=INDISTINGUISHABLE_P,
                ingest_lag_seconds=LAG_SECONDS,
                ingest_read_at=LAG_AT,
                threshold_seconds=BAND_SECONDS,
            )
        )
        is True
    )


def test_a_dark_rail_is_falsy_and_names_the_lamp(
    endpoint: InstrumentStatusEndpoint,
    halt_store: canary.CanaryHaltStore,
    trend: scoring.FdrDeployStore,
    guard: nulloracle.KsGuard,
    live: LiveMetricsStore,
) -> None:
    # Every lamp lit but one: the rail is falsy and `failing` names
    # exactly the lamp that is out.
    _plan_campaign(guard, CAMPAIGN)
    _guard_campaign(guard, CAMPAIGN, samples=SAME_SAMPLES)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    assert bool(endpoint.get()) is True

    _record_halt(halt_store)
    response = endpoint.get()
    assert response.canary is False
    assert response.failing == ("canary",)
    assert response.absent == ()
    assert bool(response) is False


# -- The response's own law ----------------------------------------------------


@pytest.mark.parametrize("lamp", LAMP_NAMES)
def test_every_lamp_refuses_a_truthy_look_alike(lamp: str) -> None:
    # The same refusal at each of the three seats, built around the fields
    # the seat's own law requires so the *bool* check is the one that
    # fires.
    rail: dict = {"canary": True}
    rail[lamp] = 1
    if lamp == "ks_guard":
        rail.update(campaign=CAMPAIGN, ks_pvalue=INDISTINGUISHABLE_P)
    if lamp == "ingest":
        rail.update(
            ingest_lag_seconds=LAG_SECONDS,
            ingest_read_at=LAG_AT,
            threshold_seconds=BAND_SECONDS,
        )
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(**rail)
    assert "binary lamps" in str(caught.value)


@pytest.mark.parametrize("value", ["ok", "1.2s", 0, 1.5, [], {}])
def test_a_lamp_refuses_everything_that_is_not_a_bool(value: object) -> None:
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(canary=value)


def test_a_ks_lamp_without_its_number_is_refused() -> None:
    # The lamp *is* the verdict on feature 123's number: a lamp without it
    # is a verdict nothing stands behind.
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(canary=True, ks_guard=True, campaign=CAMPAIGN)
    assert "p-value" in str(caught.value)


def test_a_ks_number_without_its_lamp_is_refused() -> None:
    # And the reverse: a finding nobody rendered.
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True, ks_pvalue=INDISTINGUISHABLE_P, campaign=CAMPAIGN
        )


def test_a_ks_lamp_without_a_campaign_is_refused() -> None:
    # §7.4's reading is a fact about a campaign, so a lamp with no
    # campaign is an instrument status nobody can attribute.
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(
            canary=True, ks_guard=True, ks_pvalue=INDISTINGUISHABLE_P
        )
    assert "campaign" in str(caught.value)


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), "0.9", True])
def test_a_pvalue_outside_the_unit_interval_is_refused(value: object) -> None:
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True, ks_guard=True, ks_pvalue=value, campaign=CAMPAIGN
        )


def test_a_ks_lamp_that_disagrees_with_its_own_number_is_refused() -> None:
    # The re-derivation: the bit must equal `pvalue >= VOID_THRESHOLD`, so
    # a rail whose lamp contradicted the reading beside it cannot be
    # built.  Both directions — lit over a detectable p-value and out over
    # an indistinguishable one.
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(
            canary=True,
            ks_guard=True,
            ks_pvalue=0.001,
            campaign=CAMPAIGN,
        )
    assert "strictly below" in str(caught.value)
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True,
            ks_guard=False,
            ks_pvalue=INDISTINGUISHABLE_P,
            campaign=CAMPAIGN,
        )


def test_the_ks_boundary_keeps_a_campaign_in() -> None:
    # §7.4's own strict `<`: a p-value exactly at the level is *not* below
    # it, so the nulls are still indistinguishable and the lamp is lit —
    # the margin feature 124's docstring argues for, read here against the
    # member's own constant rather than against a literal 0.05.
    level = float(nulloracle.VOID_THRESHOLD)
    at_level = InstrumentStatusResponse(
        canary=True, ks_guard=True, ks_pvalue=level, campaign=CAMPAIGN
    )
    assert at_level.ks_guard is True
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True, ks_guard=False, ks_pvalue=level, campaign=CAMPAIGN
        )


def test_an_ingest_lamp_without_both_halves_is_refused() -> None:
    # A lit-or-dark lamp needs the reading *and* the band: half a watchdog
    # is an absence, never a verdict.
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(canary=True, ingest=True)
    assert "half a watchdog" in str(caught.value)
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True,
            ingest=True,
            ingest_lag_seconds=LAG_SECONDS,
            ingest_read_at=LAG_AT,
        )
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True, ingest=True, threshold_seconds=BAND_SECONDS
        )


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), "1.2", True])
def test_a_silence_that_is_not_a_non_negative_real_is_refused(value: object) -> None:
    # A negative silence is not a silence: it is two readings that
    # disagree about what time it is — feature 328's own refusal, applied
    # to the same quantity on this rail.
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True,
            ingest=True,
            ingest_lag_seconds=value,
            ingest_read_at=LAG_AT,
            threshold_seconds=BAND_SECONDS,
        )


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_a_band_that_is_not_strictly_positive_is_refused(value: object) -> None:
    # §13.3 names no number, so the band is configuration — but a band of
    # zero or less is a watchdog that judges every silence past it, which
    # is a dark lamp rather than a tolerance.
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True,
            ingest=True,
            ingest_lag_seconds=0.0,
            ingest_read_at=LAG_AT,
            threshold_seconds=value,
        )


def test_an_ingest_lamp_that_disagrees_with_its_own_reading_is_refused() -> None:
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(
            canary=True,
            ingest=True,
            ingest_lag_seconds=BAND_SECONDS * 2,
            ingest_read_at=LAG_AT,
            threshold_seconds=BAND_SECONDS,
        )
    assert "staleness > threshold" in str(caught.value)
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True,
            ingest=False,
            ingest_lag_seconds=LAG_SECONDS,
            ingest_read_at=LAG_AT,
            threshold_seconds=BAND_SECONDS,
        )


def test_a_silence_without_its_instant_is_refused() -> None:
    # The reading and its label are one row (feature 350's
    # `(metric, logged_at)` key), so an age without its instant could not
    # be ordered against anything.
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(canary=True, ingest_lag_seconds=LAG_SECONDS)
    assert "instant" in str(caught.value)
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(canary=True, ingest_read_at=LAG_AT)


def test_a_blank_campaign_or_instant_is_refused() -> None:
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True,
            ks_guard=True,
            ks_pvalue=INDISTINGUISHABLE_P,
            campaign="   ",
        )
    with pytest.raises(InstrumentStatusError):
        InstrumentStatusResponse(
            canary=True, ingest_lag_seconds=LAG_SECONDS, ingest_read_at=" "
        )


def test_the_response_strips_a_padded_campaign_and_instant() -> None:
    # The stores strip before writing, so a padded name arriving here is
    # the same name — and holding it unstripped would answer a *second*
    # campaign for one id.
    response = InstrumentStatusResponse(
        canary=True,
        ks_guard=True,
        ks_pvalue=INDISTINGUISHABLE_P,
        campaign=f"  {CAMPAIGN}  ",
        ingest=False,
        ingest_lag_seconds=BAND_SECONDS * 2,
        ingest_read_at=f"  {LAG_AT}  ",
        threshold_seconds=BAND_SECONDS,
    )
    assert response.campaign == CAMPAIGN
    assert response.ingest_read_at == LAG_AT


def test_the_response_is_frozen() -> None:
    # The response is the route's testimony about the instruments at the
    # moment it was read; nothing on it is a knob to adjust.
    response = InstrumentStatusResponse(canary=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.canary = False


def test_a_refused_rail_names_the_feature_and_the_route() -> None:
    # The refusal's argument, so an operator reading a log line learns
    # which route and which doctrine the rail they passed broke.
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusResponse(canary=1)
    message = str(caught.value)
    assert "feature 342" in message
    assert INSTRUMENT_STATUS_ROUTE in message


# -- The store seams -----------------------------------------------------------


def test_the_endpoint_refuses_a_carrier_that_cannot_read_the_rail() -> None:
    # Duck-checked, never isinstance-guarded: a carrier that cannot answer
    # one of the four facts leaves that lamp unreadable, and the refusal
    # names the missing read because the repair differs by lamp.
    with pytest.raises(TypeError) as caught:
        InstrumentStatusEndpoint(object())
    assert "canary_halted()" in str(caught.value)
    with pytest.raises(TypeError):
        InstrumentStatusEndpoint({"canary_halted": None})


def test_a_carrier_missing_one_read_is_refused_by_that_reads_name() -> None:
    class Partial:
        def canary_halted(self) -> bool:
            return False

        def campaign(self) -> None:
            return None

        def ks_pvalue(self, campaign: str) -> None:
            return None

    with pytest.raises(TypeError) as caught:
        InstrumentStatusEndpoint(Partial())
    assert "feed_reading()" in str(caught.value)


def test_a_canary_read_that_fails_is_translated_not_answered_around() -> None:
    # The member-seam law, once per lamp: a caller that wrote
    # `except InstrumentStatusError` must not be taken down by the canary
    # member's own error class — translated at the seam, chained, and
    # never caught *into* a lit lamp.
    class Refusing:
        def canary_halted(self) -> bool:
            raise canary.CanaryError("the halt store's own words")

        def campaign(self) -> None:
            return None

        def ks_pvalue(self, campaign: str) -> None:
            return None

        def feed_reading(self) -> None:
            return None

    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusEndpoint(Refusing()).get()
    assert INSTRUMENT_STATUS_ROUTE in str(caught.value)
    assert isinstance(caught.value.__cause__, canary.CanaryError)
    assert "the halt store's own words" in str(caught.value.__cause__)


def test_a_guard_read_that_fails_is_translated_not_answered_around() -> None:
    class Refusing:
        def canary_halted(self) -> bool:
            return False

        def campaign(self) -> str:
            return CAMPAIGN

        def ks_pvalue(self, campaign: str) -> None:
            raise nulloracle.KsGuardError("the guard journal's own words")

        def feed_reading(self) -> None:
            return None

    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusEndpoint(Refusing()).get()
    assert isinstance(caught.value.__cause__, nulloracle.KsGuardError)
    assert "the guard journal's own words" in str(caught.value.__cause__)


def test_a_trend_read_that_fails_is_translated_not_answered_around() -> None:
    # The attribution's own failure: the lamp reports on the campaign the
    # top-line figure belongs to, so a trend that cannot be asked leaves
    # this lamp unattributable — refused rather than answered by picking
    # some other campaign.
    class Refusing:
        def canary_halted(self) -> bool:
            return False

        def campaign(self) -> None:
            raise scoring.FdrDeployError("the trend's own words")

        def ks_pvalue(self, campaign: str) -> None:
            return None

        def feed_reading(self) -> None:
            return None

    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusEndpoint(Refusing()).get()
    assert isinstance(caught.value.__cause__, scoring.FdrDeployError)
    assert "the trend's own words" in str(caught.value.__cause__)


def test_a_live_metrics_read_that_fails_is_translated() -> None:
    # The third lamp is this member's *own* table, so its refusal is the
    # one the route can still name in its own words — but it is
    # translated all the same, so the caller's single `except` catches it.
    class Refusing:
        def canary_halted(self) -> bool:
            return False

        def campaign(self) -> None:
            return None

        def ks_pvalue(self, campaign: str) -> None:
            return None

        def feed_reading(self) -> None:
            raise LiveMetricError("the live store's own words")

    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusEndpoint(Refusing()).get()
    assert isinstance(caught.value.__cause__, LiveMetricError)


def test_a_carrier_bug_is_not_dressed_up_as_a_store_failure() -> None:
    # Only each store's own vocabulary is translated.  A carrier that
    # fails with anything else is a caller bug and propagates raw —
    # translating it would dress a programming error up as a metrics
    # refusal and send an operator hunting a database that is fine.
    class Buggy:
        def canary_halted(self) -> bool:
            raise ValueError("a bug, not a refusal")

        def campaign(self) -> None:
            return None

        def ks_pvalue(self, campaign: str) -> None:
            return None

        def feed_reading(self) -> None:
            return None

    with pytest.raises(ValueError, match="a bug, not a refusal"):
        InstrumentStatusEndpoint(Buggy()).get()


def test_a_half_written_guard_row_surfaces_as_this_members_vocabulary(
    store_url: str, store_path: Path, guard: nulloracle.KsGuard,
    trend: scoring.FdrDeployStore,
) -> None:
    # Feature 123's own half-refusal: a campaign column carrying a
    # ks_pvalue with no provenance row behind it — the two halves are one
    # reading's content, and a reader must never see one without the
    # other.  That refusal reaches this route's caller in this member's
    # vocabulary, chained, and is never answered around with a lamp.
    _plan_campaign(guard, CAMPAIGN)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    connection = sqlite3.connect(store_path)
    with connection:
        connection.execute(
            f"UPDATE {nulloracle.CAMPAIGN_TABLE} SET ks_pvalue = ? WHERE id = ?",
            (0.9, CAMPAIGN),
        )
    connection.close()
    endpoint = InstrumentStatusEndpoint.from_env({"DATABASE_URL": store_url})
    assert endpoint is not None
    with pytest.raises(InstrumentStatusError) as caught:
        endpoint.get()
    assert isinstance(caught.value.__cause__, nulloracle.KsGuardError)
    assert CAMPAIGN in str(caught.value.__cause__)


def test_a_halt_read_against_an_unreachable_database_is_surfaced() -> None:
    # A store the route cannot ask is surfaced in this member's vocabulary
    # rather than answered around with a lit lamp: a green canary over a
    # database that would not open is exactly the *"bad data quietly aging
    # into good data"* §5.4 draws this surface to prevent.
    endpoint = InstrumentStatusEndpoint.from_env(
        {"DATABASE_URL": "postgresql://host/instruments"}
    )
    assert endpoint is not None
    with pytest.raises(InstrumentStatusError) as caught:
        endpoint.get()
    assert isinstance(caught.value.__cause__, canary.CanaryError)


def test_the_endpoint_holds_the_carrier_it_was_given() -> None:
    class Carrier:
        def canary_halted(self) -> bool:
            return True

        def campaign(self) -> None:
            return None

        def ks_pvalue(self, campaign: str) -> None:
            return None

        def feed_reading(self) -> None:
            return None

    carrier = Carrier()
    assert InstrumentStatusEndpoint(carrier).readings is carrier


# -- from_env ------------------------------------------------------------------


def test_from_env_answers_none_without_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured store is a discoverable deployment state, not an
    # error — and deliberately *not* the absent-lamp answer: no route at
    # all says there is nowhere a reading could have come from, while a
    # composed route with an absent lamp says which specific instrument
    # was never measured.  Two different facts.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert InstrumentStatusEndpoint.from_env() is None


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_from_env_refuses_a_blank_url(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", value)
    assert InstrumentStatusEndpoint.from_env() is None


def test_from_env_holds_the_url_without_touching_the_disk(
    store_url: str, store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The URL and the band are composition facts, resolved eagerly; the
    # *stores* are deferred, because a builder runs after the factory's
    # scan has taken the sibling members' src/ back off sys.path.  In
    # particular the canary member is never even imported to build this.
    monkeypatch.setenv("DATABASE_URL", store_url)
    monkeypatch.setenv(FEED_STALENESS_THRESHOLD_ENV, str(BAND_SECONDS))
    endpoint = InstrumentStatusEndpoint.from_env()
    assert endpoint is not None
    assert endpoint.readings.database_url == store_url
    assert endpoint.threshold_seconds == BAND_SECONDS
    assert not store_path.exists()


def test_from_env_reads_a_mapping_it_is_handed(store_url: str) -> None:
    endpoint = InstrumentStatusEndpoint.from_env({"DATABASE_URL": store_url})
    assert endpoint is not None
    assert endpoint.readings.database_url == store_url


def test_from_env_reads_the_band_from_the_same_mapping(store_url: str) -> None:
    endpoint = InstrumentStatusEndpoint.from_env(
        {"DATABASE_URL": store_url, FEED_STALENESS_THRESHOLD_ENV: " 2.5 "}
    )
    assert endpoint is not None
    assert endpoint.threshold_seconds == 2.5


@pytest.mark.parametrize("value", ["", "   "])
def test_an_unset_band_is_an_absence_not_an_error(
    store_url: str, value: str
) -> None:
    endpoint = InstrumentStatusEndpoint.from_env(
        {"DATABASE_URL": store_url, FEED_STALENESS_THRESHOLD_ENV: value}
    )
    assert endpoint is not None
    assert endpoint.threshold_seconds is None


@pytest.mark.parametrize("value", ["soon", "0", "-1", "nan", "inf"])
def test_a_set_but_unusable_band_is_refused_by_name(store_url: str, value: str) -> None:
    # A deployment that set the knob believes its watchdog is wired, so a
    # value that cannot be used is refused rather than silently treated as
    # unset — the refusal names the variable, so an operator learns which
    # knob to fix.
    with pytest.raises(InstrumentStatusError) as caught:
        InstrumentStatusEndpoint.from_env(
            {"DATABASE_URL": store_url, FEED_STALENESS_THRESHOLD_ENV: value}
        )
    assert FEED_STALENESS_THRESHOLD_ENV in str(caught.value)


def test_the_deferred_carrier_reaches_every_sibling_read(
    store_url: str,
    store_path: Path,
    halt_store: canary.CanaryHaltStore,
    guard: nulloracle.KsGuard,
    trend: scoring.FdrDeployStore,
    live: LiveMetricsStore,
) -> None:
    # The endpoint built by from_env answers the same rail the members'
    # own stores do — the deferral moves *when* the stores are
    # constructed, never *what* they are.
    endpoint = InstrumentStatusEndpoint.from_env(
        {"DATABASE_URL": store_url, FEED_STALENESS_THRESHOLD_ENV: str(BAND_SECONDS)}
    )
    assert endpoint is not None
    _plan_campaign(guard, CAMPAIGN)
    _guard_campaign(guard, CAMPAIGN, samples=SAME_SAMPLES)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)
    _record_halt(halt_store)

    response = endpoint.get()
    assert response.canary is False
    assert response.ks_guard is True
    assert response.ingest is True
    assert response.campaign == CAMPAIGN
    assert store_path.exists()


def test_the_composed_route_and_the_members_own_stores_agree(
    endpoint: InstrumentStatusEndpoint,
    halt_store: canary.CanaryHaltStore,
    guard: nulloracle.KsGuard,
    trend: scoring.FdrDeployStore,
    live: LiveMetricsStore,
) -> None:
    # Both directions, over the same rows: the route re-derives nothing,
    # and each lamp's bit is the owning read's own answer.
    _plan_campaign(guard, CAMPAIGN)
    pvalue = _guard_campaign(guard, CAMPAIGN, samples=SAME_SAMPLES)
    _close_campaign(trend, CAMPAIGN, computed_at="2026-08-01T00:00:00Z")
    live.record(FEED_STALENESS_METRIC, LAG_SECONDS, logged_at=LAG_AT)

    response = endpoint.get()
    assert response.canary is (not halt_store.halted())
    assert response.campaign == trend.history()[-1][0]
    assert response.ks_pvalue == guard.load(CAMPAIGN).pvalue == pvalue
    assert response.ingest_lag_seconds == live.series(FEED_STALENESS_METRIC)[-1][1]


# -- The module's own law ------------------------------------------------------


def test_require_canary_answers_the_member() -> None:
    assert require_canary() is canary


def test_require_nulloracle_answers_the_member() -> None:
    assert require_nulloracle() is nulloracle


def test_the_module_imports_no_sibling_at_scope() -> None:
    # The member's law is delegation, and the cross-member reads are the
    # deferred, declared doors.  Read on the code (docstrings stripped),
    # so the prose may name the sibling members and the code may not reach
    # them at module scope.
    import ops.instrument_status as module

    tree = ast.parse(_code_of(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.lstrip(".").split(".")[0])
    assert imported <= {
        "__future__",
        "canary",
        "collections",
        "dataclasses",
        "errors",
        "fdr_route",
        "live_metrics",
        "math",
        "nulloracle",
        "os",
        "typing",
    }, sorted(imported)
    # The scoring member is reached through feature 341's own door, never
    # imported here at module scope; and every other member is absent —
    # this route re-derives no figure of its own.
    for sibling in ("scoring", "regime", "promotion", "ledger", "dreaming", "risk"):
        assert sibling not in imported
    # And no clock: the rail is a reading, and nothing here stamps an
    # instant of its own.
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "perf_counter" not in names
    assert "now" not in names
    assert "utcnow" not in names


def test_the_sibling_imports_live_inside_their_doors() -> None:
    # `import canary` and `import nulloracle` each appear in exactly one
    # place — inside their door, where the import is deferred past module
    # scope and past builder time.
    import ops.instrument_status as module

    tree = ast.parse(_code_of(module))
    at_scope = [
        node
        for node in tree.body
        if isinstance(node, ast.Import)
        and any(alias.name in {"canary", "nulloracle"} for alias in node.names)
    ]
    assert at_scope == []
    source = _code_of(module)
    assert source.count("import canary") == 1
    assert source.count("import nulloracle") == 1


def test_the_module_restates_no_sibling_vocabulary() -> None:
    # The two constants this route must not own: §7.4's level (feature
    # 124's) and §12's tolerance (feature 141's).  Both are read through
    # the member that spells them, so no literal of either appears in this
    # module's code — a second spelling would be a second place the
    # comparison or the band could drift from what the member voids on.
    import ops.instrument_status as module

    source = _code_of(module)
    assert "0.05" not in source
    assert "1e-12" not in source


def test_the_module_keeps_the_three_store_names_it_imports() -> None:
    # The live-metrics store is this member's own table, so its module and
    # the URL spelling are imported rather than restated; the metric name
    # is *selected* out of the store's published vocabulary, so a typo
    # would fail at import rather than silently asking the store for a
    # name it refuses.
    import ops.instrument_status as module

    assert module.FEED_STALENESS_METRIC in module.LIVE_METRICS
    assert module.DATABASE_URL_ENV == "DATABASE_URL"


def test_the_module_declares_its_dependencies_in_the_member_pyproject() -> None:
    # Both sibling members are declared workspace dependencies of this
    # member, the same way the scoring member is for feature 341's route
    # and the regime member for 343's: the imports are deferred, but they
    # are not undeclared.
    member_root = Path(__file__).resolve().parents[1]
    declaration = (member_root / "pyproject.toml").read_text()
    project = declaration.split("[project]")[1].split("[build-system]")[0]
    assert "canary" in project
    assert "nulloracle" in project


@pytest.mark.parametrize("member", ["canary", "nulloracle"])
def test_a_door_says_which_wheel_is_missing(member: str) -> None:
    # The doors' own failure mode: a deployment that genuinely needs the
    # rail and cannot reach the sibling member is told what to run rather
    # than shown a bare ImportError.  Simulated by making the import fail.
    import builtins

    door = require_canary if member == "canary" else require_nulloracle
    real_import = builtins.__import__

    def refusing(name: str, *args: object, **kwargs: object) -> object:
        if name == member:
            raise ModuleNotFoundError(f"No module named {member!r}")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = refusing
    try:
        with pytest.raises(ModuleNotFoundError) as caught:
            door()
    finally:
        builtins.__import__ = real_import
    assert "uv sync --all-packages" in str(caught.value)
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)


def _code_of(module: object) -> str:
    """The module's source with every docstring stripped.

    The "what the code does, not what the prose says" reading this suite
    shares with the member's other suites: a docstring naming the canary
    member's store is honesty (the lamp's owner is stated where it is
    delegated to), while an *import* of it at module scope would be the
    second spelling this route exists to avoid — and only the AST can tell
    the two apart.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)
