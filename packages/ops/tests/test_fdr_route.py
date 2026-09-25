"""Feature 341's route: GET /metrics/fdr-deploy, the top-line figure.

These tests hold the route to its own sentence — *returns the
base-rate reweighted false discovery rate as the top-line figure* —
from the side the member owns.  The figures themselves are the
scoring member's (feature 267's store writes them); what is pinned
here is the surface: the one route name, the top line drawn from the
trend's own order, the honest absence for a deployment that has closed
no campaign, the translation of a failed read into this member's
vocabulary, and the validation that makes a hand-built history earn
the guarantees the store's read already stands behind.

The store used throughout is the real one — the scoring member's
:class:`~scoring.FdrDeployStore`, resolved from the per-test
``DATABASE_URL`` the conftest sets — because the route's whole
design is delegation to that one spelling, and a fake could only test
the fake's law.  Fakes appear only where the route's own refusals need
them: the duck-typed carrier check and the translated read failure.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from ops import FDR_DEPLOY_ROUTE, FdrDeployEndpoint, FdrDeployResponse
from ops.errors import FdrDeployMetricError, OpsError
from scoring import FdrDeployError, FdrDeployStore, fdr_deploy


class _Pair:
    """A stand-in for feature 266's calibration figures — a plain
    object exposing exactly the two attributes the reweighting reads,
    and nothing else, which is what proves the store's write seam (and
    the route's read through it) validates what it reads rather than
    the type it was handed.  The same discipline the scoring member's
    own suite states for its cross-member carriers."""

    __slots__ = ("sensitivity", "specificity")

    def __init__(self, sensitivity: float, specificity: float) -> None:
        self.sensitivity = sensitivity
        self.specificity = specificity


class _HistoryOnly:
    """A stand-in carrier exposing exactly the one ``history()`` read
    the route duck-checks for — the shape that proves the endpoint
    holds the store's *contract* rather than its class."""

    __slots__ = ("rows",)

    def __init__(self, rows) -> None:
        self.rows = rows

    def history(self):
        return list(self.rows)


def _store(test_database_url: str) -> FdrDeployStore:
    """The real store, pointed at this test's isolated database."""
    return FdrDeployStore(test_database_url)


def _persist(
    store: FdrDeployStore,
    *,
    campaign: str,
    sensitivity: float,
    specificity: float,
    computed_at: str,
) -> float:
    """Land one campaign's figure through the store's own write."""
    return store.persist(
        uuid.UUID(campaign),
        _Pair(sensitivity, specificity),
        computed_at=computed_at,
    )


# -- the route's one spelling -------------------------------------------------


def test_the_route_is_spelled_once_everywhere_it_is_named() -> None:
    # The spec's API summary row (``GET /metrics/fdr-deploy — Return
    # the base-rate reweighted false discovery rate``), the module's
    # constant and the endpoint's own attribute are one string: three
    # spellings of one name is exactly the kind of drift a test is
    # cheaper than.
    assert FDR_DEPLOY_ROUTE == "/metrics/fdr-deploy"
    assert FdrDeployEndpoint.route == FDR_DEPLOY_ROUTE


def test_the_endpoint_duck_checks_the_carrier_not_its_class() -> None:
    # The factory's scan imports members under synthetic names, so a
    # composed store is structurally the scoring member's and never
    # the same class object a direct import yields — the contract is
    # the history() read, and that is what is checked.  A carrier that
    # cannot answer the trend cannot name the top line, and the
    # refusal says so.
    endpoint = FdrDeployEndpoint(_HistoryOnly([]))
    assert endpoint.get().fdr_deploy is None

    class _OneCampaign:
        def fdr(self, campaign):  # pragma: no cover - never called
            return 0.5

    with pytest.raises(TypeError, match="history"):
        FdrDeployEndpoint(_OneCampaign())
    with pytest.raises(TypeError, match="FdrDeployEndpoint"):
        FdrDeployEndpoint("sqlite:///nowhere.db")


# -- the honest empty state ---------------------------------------------------


def test_an_empty_trend_answers_an_absence_never_a_zero(
    test_database_url: str,
) -> None:
    # A deployment that has never closed a campaign has no top-line
    # figure.  Feature 267's own stance for the same state is the
    # discoverable one, and the route answers it with ``None`` — never
    # ``0.0``, which is a *measurement* (a campaign that projected to
    # no false discoveries) and would answer "a flawless system" for
    # one that never ran.
    response = FdrDeployEndpoint(_store(test_database_url)).get()
    assert not response
    assert len(response) == 0
    assert response.fdr_deploy is None
    assert response.campaign_id is None
    assert response.computed_at is None
    assert response.history == ()


# -- the top line is the trend's newest row ------------------------------------


def test_the_top_line_is_the_newest_campaigns_figure(
    test_database_url: str,
) -> None:
    # §16's research metrics are per-campaign figures and prd §12's M3
    # reads them as a trend, so the deployment holds many while the
    # top line is one: the numeral docs/design.md's hero renders
    # beside the *current* campaign plate.  The route draws it from
    # the store's own oldest-first order and takes the last row — the
    # order is inherited, never restated here.
    store = _store(test_database_url)
    _persist(
        store,
        campaign="11111111-1111-1111-1111-111111111111",
        sensitivity=0.5,
        specificity=0.5,
        computed_at="2026-01-01T00:00:00",
    )
    _persist(
        store,
        campaign="22222222-2222-2222-2222-222222222222",
        sensitivity=0.75,
        specificity=0.75,
        computed_at="2026-02-01T00:00:00",
    )
    newest = _persist(
        store,
        campaign="33333333-3333-3333-3333-333333333333",
        sensitivity=0.9,
        specificity=0.9,
        computed_at="2026-03-01T00:00:00",
    )

    response = FdrDeployEndpoint(store).get()
    assert response
    assert len(response) == 3
    # The whole trend, oldest first — the sequence M3's "improves"
    # reads across, answered from the same read the numeral came from.
    assert [row[0] for row in response.history] == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    assert response.fdr_deploy == newest
    assert response.campaign_id == "33333333-3333-3333-3333-333333333333"
    assert response.computed_at == "2026-03-01T00:00:00"


def test_a_tie_on_the_instant_follows_the_stores_own_order(
    test_database_url: str,
) -> None:
    # Two campaigns computed in the same second are ordered by the
    # store's own tiebreak (campaign_id ascending), so "the last row"
    # stays deterministic without this member restating an ORDER BY of
    # its own — the pinned determinism is the point, not which of the
    # tied campaigns wins.
    store = _store(test_database_url)
    _persist(
        store,
        campaign="aaaaaaaa-0000-0000-0000-000000000001",
        sensitivity=0.5,
        specificity=0.5,
        computed_at="2026-01-01T00:00:00",
    )
    _persist(
        store,
        campaign="bbbbbbbb-0000-0000-0000-000000000002",
        sensitivity=0.25,
        specificity=0.25,
        computed_at="2026-01-01T00:00:00",
    )

    response = FdrDeployEndpoint(store).get()
    assert response.campaign_id == "bbbbbbbb-0000-0000-0000-000000000002"


def test_a_campaign_closed_between_two_reads_moves_the_second_answer(
    test_database_url: str,
) -> None:
    # The endpoint holds no cache of a previous answer: the rows are
    # the only record of what was measured, so they are the only thing
    # the answer is drawn from, on every request.  A cached figure
    # would make the dashboard's numeral a fact about when the reader
    # happened to start.
    store = _store(test_database_url)
    endpoint = FdrDeployEndpoint(store)
    first = _persist(
        store,
        campaign="11111111-1111-1111-1111-111111111111",
        sensitivity=0.5,
        specificity=0.5,
        computed_at="2026-01-01T00:00:00",
    )
    assert endpoint.get().fdr_deploy == first

    second = _persist(
        store,
        campaign="22222222-2222-2222-2222-222222222222",
        sensitivity=0.9,
        specificity=0.9,
        computed_at="2026-02-01T00:00:00",
    )
    answer = endpoint.get()
    assert answer.fdr_deploy == second != first
    assert answer.campaign_id == "22222222-2222-2222-2222-222222222222"


# -- the figure the route answers ----------------------------------------------


def test_both_ends_of_the_projection_are_honoured(
    test_database_url: str,
) -> None:
    # Both ends of [0, 1] are measurements and both are served:
    # specificity 1.0 with sensitivity found reweights to 0.0 (a
    # campaign that never committed a null projects to no false
    # discoveries), and sensitivity 0.0 with specificity below one
    # reweights to 1.0 (a campaign that finds no reals projects every
    # declaration false).  A route that clamped or refused an endpoint
    # would hide a figure the campaign honestly measured.
    store = _store(test_database_url)
    _persist(
        store,
        campaign="11111111-1111-1111-1111-111111111111",
        sensitivity=0.5,
        specificity=1.0,
        computed_at="2026-01-01T00:00:00",
    )
    assert FdrDeployEndpoint(store).get().fdr_deploy == 0.0

    _persist(
        store,
        campaign="22222222-2222-2222-2222-222222222222",
        sensitivity=0.0,
        specificity=0.5,
        computed_at="2026-02-01T00:00:00",
    )
    assert FdrDeployEndpoint(store).get().fdr_deploy == 1.0


def test_every_figure_is_pinned_to_the_deployment_projection(
    test_database_url: str,
) -> None:
    # The figure is the deployment projection — π₀ = 0.9, the one
    # constant — for pairs spread across the measurable range, checked
    # to the bit against the same arithmetic the store's write used.
    # A route that re-spelled the formula (or trusted a stale column)
    # would drift here first.
    store = _store(test_database_url)
    cases = [
        ("11111111-1111-1111-1111-111111111111", 0.5, 0.5),
        ("22222222-2222-2222-2222-222222222222", 0.9, 0.9),
        ("33333333-3333-3333-3333-333333333333", 0.25, 0.75),
        ("44444444-4444-4444-4444-444444444444", 1.0, 0.5),
    ]
    for index, (campaign, sensitivity, specificity) in enumerate(cases, start=1):
        _persist(
            store,
            campaign=campaign,
            sensitivity=sensitivity,
            specificity=specificity,
            computed_at=f"2026-0{index}-01T00:00:00",
        )
    response = FdrDeployEndpoint(store).get()
    assert len(response.history) == len(cases)
    for (campaign, figure, _), (_, sensitivity, specificity) in zip(
        response.history, cases
    ):
        assert figure == fdr_deploy(_Pair(sensitivity, specificity))


# -- refusals -------------------------------------------------------------------


def test_a_corrupt_row_is_refused_translated_and_chained(
    test_database_url: str,
) -> None:
    # The store's own read law refuses a row whose stored figure
    # disagrees with its own pair (the pair is the truth, the figure a
    # derived view).  The route must surface that refusal — translated
    # into this member's vocabulary, the original chained — and never
    # answer around it, because a corrupt top-line figure is a number
    # no dashboard and no M3 gate could rely on.
    store = _store(test_database_url)
    _persist(
        store,
        campaign="11111111-1111-1111-1111-111111111111",
        sensitivity=0.5,
        specificity=0.5,
        computed_at="2026-01-01T00:00:00",
    )
    path = Path(urlparse(test_database_url).path.removeprefix("/"))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE scoring_fdr_deploy SET fdr_deploy = 0.123456")

    with pytest.raises(FdrDeployMetricError) as raised:
        FdrDeployEndpoint(store).get()
    assert isinstance(raised.value, OpsError)
    assert FDR_DEPLOY_ROUTE in str(raised.value)
    assert isinstance(raised.value.__cause__, Exception)


def test_a_failing_read_is_translated_not_answered_around() -> None:
    # The member-seam law: the rows are the scoring member's, the route
    # is this member's, and a caller that wrote ``except
    # FdrDeployMetricError`` must not be taken down by the scoring
    # member's own error class — translated at the seam, chained, and
    # never caught *into* an answer.
    class _Refusing:
        def history(self):
            raise FdrDeployError("the store's own words")

    with pytest.raises(FdrDeployMetricError) as raised:
        FdrDeployEndpoint(_Refusing()).get()
    assert FDR_DEPLOY_ROUTE in str(raised.value)
    assert isinstance(raised.value.__cause__, FdrDeployError)
    assert "the store's own words" in str(raised.value.__cause__)


def test_a_carrier_bug_is_not_dressed_up_as_a_store_failure() -> None:
    # Only the store's own vocabulary is translated.  A carrier that
    # fails with anything else is a caller bug and propagates raw —
    # translating it would dress a programming error up as a metrics
    # refusal and send an operator hunting a database that is fine.
    class _Buggy:
        def history(self):
            raise ValueError("a bug, not a refusal")

    with pytest.raises(ValueError, match="a bug, not a refusal"):
        FdrDeployEndpoint(_Buggy()).get()


# -- the response validates what it holds ---------------------------------------


def test_the_response_normalises_and_narrows_what_it_is_handed() -> None:
    # Constructible by hand (tests, a recorded history) — so
    # construction narrows: lists of lists become the tuple of triples
    # it holds, figures narrow to float, and the guarantees the route
    # lends the value are earned by the value itself.
    response = FdrDeployResponse(
        history=[["campaign-a", 0.5, "2026-01-01T00:00:00"]]
    )
    assert response.history == (("campaign-a", 0.5, "2026-01-01T00:00:00"),)
    assert response.fdr_deploy == 0.5
    assert FdrDeployResponse().history == ()


@pytest.mark.parametrize(
    "rows",
    [
        # instants that run backwards: the top line is *the last row*,
        # so a lying order would silently top-line the wrong campaign.
        [("a", 0.5, "2026-02-01T00:00:00"), ("b", 0.5, "2026-01-01T00:00:00")],
        # figures that have stopped being fractions
        [("a", 1.5, "2026-01-01T00:00:00")],
        [("a", -0.25, "2026-01-01T00:00:00")],
        [("a", float("nan"), "2026-01-01T00:00:00")],
        [("a", float("inf"), "2026-01-01T00:00:00")],
        # a truth value is not a figure (bool is an int subclass)
        [("a", True, "2026-01-01T00:00:00")],
        # a figure that is not a real
        [("a", "0.5", "2026-01-01T00:00:00")],
        # an id that names no campaign
        [("", 0.5, "2026-01-01T00:00:00")],
        [(None, 0.5, "2026-01-01T00:00:00")],
        # an instant that orders nothing
        [("a", 0.5, "")],
        [("a", 0.5, None)],
        # an entry that is not one campaign's triple
        [("a", 0.5)],
        ["abc"],
        [42],
    ],
)
def test_a_history_the_response_cannot_hold_is_refused(rows) -> None:
    with pytest.raises(FdrDeployMetricError):
        FdrDeployResponse(history=rows)


def test_the_response_is_frozen_testimony() -> None:
    # The response is the route's testimony about the store at the
    # moment it was read; nothing on it is a knob to adjust.
    response = FdrDeployResponse(history=[("a", 0.5, "2026-01-01T00:00:00")])
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.history = ()  # type: ignore[misc]


# -- construction from the environment ------------------------------------------


def test_from_env_resolves_the_store_the_builder_resolves() -> None:
    # One relational metrics store (§16's "single Postgres metrics
    # table" allowance): the route resolves exactly what the scoring
    # member's own builder resolves, so both always point at the same
    # database.  An empty or absent value counts as unset — no store
    # composes no endpoint.
    url = "sqlite:///tmp/ops-from-env-test.db"
    endpoint = FdrDeployEndpoint.from_env({"DATABASE_URL": url})
    assert endpoint is not None
    assert endpoint.store.database_url == url

    assert FdrDeployEndpoint.from_env({"DATABASE_URL": ""}) is None
    assert FdrDeployEndpoint.from_env({}) is None


def test_from_env_reads_the_process_environment_when_handed_none(
    test_database_url: str,
) -> None:
    endpoint = FdrDeployEndpoint.from_env()
    assert endpoint is not None
    assert endpoint.store.database_url == test_database_url
    # The read is live: the same endpoint answers the rows this test's
    # database holds, without any second resolution.
    assert endpoint.get().fdr_deploy is None
