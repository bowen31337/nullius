"""The ops member's seam with the scoring member: one figure, two
members.

The route this member exposes serves a number the scoring member owns:
feature 267's per-campaign ``FDR_deploy``, reweighted once at the one
constant, persisted in the scoring member's own table.  These tests
pin the seam from both sides at once — writing through the scoring
member's real store and reading back through this member's real route
— because that is the composition the spec describes (§16: the
dashboard reads the metrics store; feature 341: the route returns the
base-rate reweighted false discovery rate), and because a seam tested
from one side only can drift on the other.

What is pinned:

* **the same figure to the bit** — every triple the route answers
  equals what the store's own ``history()`` answers, and the top-line
  figure equals what the scoring member's pure ``fdr_deploy`` verb
  computes over the same pair;
* **the projection, never the raw rate** — prd §4.1.3's arithmetic is
  the argument: a campaign planted at φ ≈ 0.25 measures a pair whose
  *in-campaign* false discovery rate is small exactly because three
  quarters of its population is real, while the deployment projection
  at π₀ = 0.9 is the number that matters where the system actually
  runs; the route answers the projection;
* **the corner never reaches the surface** — the 0/0 pair (sensitivity
  0.0, specificity 1.0, a campaign that committed to nothing) is
  refused by the store's own write law before any row exists, so the
  route's trend keeps whatever honest shape it had.

A plain stand-in pair (two attributes, nothing else) is used for the
figures rather than the scoring member's own value type — a member
never imports another member's *types* to test what crosses the seam;
the duck-typed carrier is the honest way to do it, and it proves the
seam validates what it reads.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from ops import (
    DiscoveryRateError,
    DiscoveryRates,
    FdrDeployEndpoint,
    TypeBDepths,
    require_scoring,
)
from scoring import FdrDeployError, FdrDeployStore, account_errors, fdr_deploy

CAMPAIGN_A = "11111111-1111-1111-1111-111111111111"
CAMPAIGN_B = "22222222-2222-2222-2222-222222222222"


class _Pair:
    """A stand-in for feature 266's calibration figures — exactly the
    two attributes the reweighting reads, and nothing else."""

    __slots__ = ("sensitivity", "specificity")

    def __init__(self, sensitivity: float, specificity: float) -> None:
        self.sensitivity = sensitivity
        self.specificity = specificity


def test_require_scoring_returns_the_member_that_owns_the_rows() -> None:
    # The delegation door: the route reads the figure through the
    # scoring member itself (the "never grow a second parser" door the
    # router member opened for the ingest parser), so the module it
    # resolves is the one whose store law the figures already passed.
    import scoring

    assert require_scoring() is scoring


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"DATABASE_URL": ""},
        {"DATABASE_URL": "   "},
        {"DATABASE_URL": "sqlite:///tmp/ops-agreement-test.db"},
        {"DATABASE_URL": "sqlite:///tmp/ops-agreement-test-2.db"},
    ],
)
def test_from_env_composes_exactly_when_the_store_resolves(env) -> None:
    # The route reads DATABASE_URL itself (not through the scoring
    # member — the builder runs after the factory's scan has taken the
    # sibling's src/ back off sys.path, so an import there would make
    # every whole-workspace composition depend on scan order).  What
    # must not drift is the *decision*: the route composes exactly when
    # the store resolves, and over the URL the store resolved, so a
    # deployment can never hold a route pointing at one database while
    # feature 267's rows go to another.  Pinned across the unset
    # spellings (absent, empty, whitespace) and two configured ones.
    resolved = FdrDeployStore.resolve(env)
    endpoint = FdrDeployEndpoint.from_env(env)
    if resolved is None:
        assert endpoint is None
    else:
        assert endpoint is not None
        assert endpoint.store.database_url == resolved.database_url


def test_the_deferred_carrier_builds_without_the_scoring_member_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The scan-order law, pinned as the composition bug it once was:
    # the builder must not import the scoring member, because builders
    # fire after the factory's scan has taken each member's ``src/``
    # off ``sys.path`` — in an environment where the members are not
    # installed, that import crashed every whole-workspace
    # composition.  Resolving an endpoint and reading its URL (the
    # composition facts) imports no sibling; the first read is where
    # the import happens, and it names its repair if it cannot.
    import builtins

    real_import = builtins.__import__

    def _no_scoring(name, *args, **kwargs):
        if name == "scoring":
            raise AssertionError(
                "the builder must not import the scoring member — it "
                "runs after the factory's scan has taken the sibling's "
                "src/ off sys.path (feature 341)"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_scoring)
    endpoint = FdrDeployEndpoint.from_env(
        {"DATABASE_URL": "sqlite:///tmp/ops-deferred-test.db"}
    )
    assert endpoint is not None
    # The composition facts are readable without the sibling: the
    # route name and the database the URL names.
    assert endpoint.route == "/metrics/fdr-deploy"
    assert endpoint.store.database_url == "sqlite:///tmp/ops-deferred-test.db"


def test_the_route_answers_the_stores_own_history_exactly(
    test_database_url: str,
) -> None:
    store = FdrDeployStore(test_database_url)
    store.persist(uuid.UUID(CAMPAIGN_A), _Pair(0.5, 0.5), computed_at="2026-01-01T00:00:00")
    store.persist(uuid.UUID(CAMPAIGN_B), _Pair(0.75, 0.25), computed_at="2026-02-01T00:00:00")

    response = FdrDeployEndpoint(store).get()
    assert response.history == tuple(store.history())
    assert len(response.history) == 2


def test_the_top_line_equals_the_scoring_members_reweighting_to_the_bit(
    test_database_url: str,
) -> None:
    # The figure the route top-lines is the one the scoring member's
    # free verb computes over the same pair — no second spelling of
    # §4.1.3's arithmetic anywhere on the path, so there is no place
    # for the route's number and the store's number to drift apart.
    store = FdrDeployStore(test_database_url)
    pair = _Pair(0.75, 0.25)
    persisted = store.persist(
        uuid.UUID(CAMPAIGN_A), pair, computed_at="2026-01-01T00:00:00"
    )

    assert persisted == fdr_deploy(pair)
    assert FdrDeployEndpoint(store).get().fdr_deploy == fdr_deploy(pair)


def test_the_top_line_is_the_projection_never_the_raw_in_campaign_rate(
    test_database_url: str,
) -> None:
    # prd §4.1.3's own argument, pinned as a number.  A campaign
    # planted at φ = 0.25 (the section's shaded floor) with this pair
    # measures an *in-campaign* false discovery rate of
    # φ(1−spec)/[φ(1−spec)+(1−φ)·sens] ≈ 0.036 — small because three
    # quarters of the population is real — while the deployment
    # projection at π₀ = 0.9 is 0.5, the number the section insists the
    # dashboard show.  The route answers 0.5.  A route that answered
    # the raw rate (or fell back to it for a young deployment) would
    # top-line exactly the under-skeptical figure the reweighting
    # exists to replace.
    phi = 0.25
    sensitivity, specificity = 0.9, 0.9
    raw_in_campaign = (phi * (1.0 - specificity)) / (
        phi * (1.0 - specificity) + (1.0 - phi) * sensitivity
    )
    projection = fdr_deploy(_Pair(sensitivity, specificity))

    assert raw_in_campaign == pytest.approx(0.0357, abs=1e-4)
    assert projection == pytest.approx(0.5)
    assert projection != pytest.approx(raw_in_campaign)

    store = FdrDeployStore(test_database_url)
    store.persist(
        uuid.UUID(CAMPAIGN_A),
        _Pair(sensitivity, specificity),
        computed_at="2026-01-01T00:00:00",
    )
    assert FdrDeployEndpoint(store).get().fdr_deploy == projection


def test_the_committed_to_nothing_corner_never_reaches_the_surface(
    test_database_url: str,
) -> None:
    # The 0/0 corner (sensitivity 0.0, specificity 1.0) is feature
    # 266's honest answer for a campaign that committed to nothing,
    # and feature 267's write law refuses to project it: no fraction of
    # declarations is defined for a campaign that made none.  The
    # refusal is the store's, it happens at the write, and the surface
    # this member serves is never asked to render it — the trend keeps
    # the honest shape it had, which here is the honest empty one.
    store = FdrDeployStore(test_database_url)
    with pytest.raises(FdrDeployError):
        store.persist(
            uuid.UUID(CAMPAIGN_A),
            _Pair(0.0, 1.0),
            computed_at="2026-01-01T00:00:00",
        )
    response = FdrDeployEndpoint(store).get()
    assert response.history == ()
    assert response.fdr_deploy is None


def test_the_discovery_rate_answers_the_ledgers_own_filter_law(
    test_database_url: str,
) -> None:
    # Feature 346's denominator against feature 93's derivation, pinned as
    # arithmetic.  This member reads no ledger — the counts are handed over
    # already measured — so the seam that must not drift is the *law*: the
    # denominator is the count of the trials whose charges_budget is true
    # (§8: a null node "consumed agent calls and CPU but NO statistical
    # degrees of freedom"), and the ledger's plain row count is a different
    # number that this store carries only so the exclusion is checkable.
    rate = DiscoveryRates(test_database_url)
    row = rate.record(
        CAMPAIGN_A,
        discoveries=8,
        budget_charging_trials=3200,
        ledger_trials=4000,
    )
    assert row.rate == pytest.approx(2.5)
    # The excluded nulls, visible by subtraction — the number feature 93's
    # K_effective and TrialLedger.count diverge by.
    assert row.ledger_trials - row.budget_charging_trials == 800
    # And the flattering reading is demonstrably not what was stored.
    assert row.rate != pytest.approx(8 / 4000 * 1000.0)


def test_the_discovery_rate_joins_the_fdr_deploy_row_on_the_campaign_id(
    test_database_url: str,
) -> None:
    # §16's research metrics are per campaign, and the two figures are keyed
    # by the same canonical id — so a reader holding one campaign's row can
    # join its yield to its base-rate-reweighted false discovery rate
    # (feature 267's row, feature 341's surface) without a second spelling of
    # the campaign's identity.
    FdrDeployStore(test_database_url).persist(
        uuid.UUID(CAMPAIGN_A), _Pair(0.75, 0.25), computed_at="2026-01-01T00:00:00"
    )
    rate = DiscoveryRates(test_database_url)
    row = rate.record(
        CAMPAIGN_A,
        discoveries=8,
        budget_charging_trials=3200,
        ledger_trials=4000,
    )
    # The row is readable by the same canonical spelling the scoring store
    # used, in any form uuid.UUID parses.
    assert rate.rate(uuid.UUID(CAMPAIGN_A)) == row
    assert rate.rate(CAMPAIGN_A.upper()) == row
    assert row.campaign_id == CAMPAIGN_A


def test_the_discovery_rate_refuses_a_denominator_the_ledger_cannot_hold(
    test_database_url: str,
) -> None:
    # The one cross-member fact this store does check structurally: the
    # ledger is append-only with no UPDATE and no DELETE (§8, enforced by
    # role grants), so the budget-charging subset can never exceed the rows
    # that exist — and a row claiming otherwise would put a flattering
    # denominator into prd §11's trend.
    rate = DiscoveryRates(test_database_url)
    with pytest.raises(DiscoveryRateError):
        rate.record(
            CAMPAIGN_A,
            discoveries=8,
            budget_charging_trials=4000,
            ledger_trials=3200,
        )
    assert rate.history() == ()


def test_the_two_ops_tables_share_the_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance: the scoring member's
    # FDR_deploy rows and this member's research rows live in the one database
    # DATABASE_URL names, so an operator joins them in one query rather than
    # reconciling two stores.
    from pathlib import Path
    from urllib.parse import urlparse

    FdrDeployStore(test_database_url).persist(
        uuid.UUID(CAMPAIGN_A), _Pair(0.75, 0.25), computed_at="2026-01-01T00:00:00"
    )
    DiscoveryRates(test_database_url).record(
        CAMPAIGN_A, discoveries=8, budget_charging_trials=3200, ledger_trials=4000
    )
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "scoring_fdr_deploy" in tables
    assert "ops_discovery_rate" in tables


class _TypeDNode:
    """A stand-in for the oracle-side Type-D resolution — exactly the
    three facts feature 269's seam duck-reads (``node_id``, ``depth`` and
    the branch's drawn ``flip_depth``), and nothing else.  A member never
    imports another member's types to test what crosses the seam; the
    duck-typed carrier is the honest way to do it, and it proves the
    accounting's seam validates what it reads."""

    __slots__ = ("node_id", "depth", "flip_depth")

    def __init__(self, node_id: str, depth: int, flip_depth: int) -> None:
        self.node_id = node_id
        self.depth = depth
        self.flip_depth = flip_depth


class _Scorer:
    """A stand-in for feature 265's process — exactly the one callable
    ``null_pick_rate`` the accounting asks for, answering a fixed rate and
    reading nothing, so the Type-B half of the answer is what the test
    isolates."""

    __slots__ = ()

    def null_pick_rate(self, picks: object) -> float:
        return 0.25


def test_the_type_b_depth_is_the_accountings_own_figure(
    test_database_url: str,
) -> None:
    # Feature 345's seam with feature 269, pinned from both sides at once:
    # the accounting answers Type-B's metric as a count of explored nodes
    # at or beyond their branch's flip (§7.2's inclusive boundary — the
    # node at the flip is the first null node), and this store persists
    # that count per campaign, unchanged, which is the whole of the
    # hand-over ("which returns the trend across campaigns" — the trend
    # over these rows is the trend over the accounting's answers).
    # One Type-D branch, flip drawn at depth 3: below the flip is real
    # exploration (not this metric's error), at or beyond it is one
    # Type-B error per node.
    explored = (
        _TypeDNode("node-below", 2, 3),
        _TypeDNode("node-at", 3, 3),
        _TypeDNode("node-beyond", 4, 3),
        _TypeDNode("node-deeper", 5, 3),
    )
    accounting = account_errors((), explored=explored, scorer=_Scorer())
    assert accounting.depth_past_flip_errors == 3
    store = TypeBDepths(test_database_url)
    row = store.record(
        CAMPAIGN_A,
        depth_past_flip_errors=accounting.depth_past_flip_errors,
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    assert row.depth_past_flip_errors == accounting.depth_past_flip_errors
    # A second Type-D campaign that crossed nothing — the accounting's
    # zero is a measurement, and the trend the store answers is the
    # sequence the scorecard reads its "falling" across.
    clean = account_errors(
        (), explored=(_TypeDNode("node-early", 1, 4),), scorer=_Scorer()
    )
    assert clean.depth_past_flip_errors == 0
    store.record(
        CAMPAIGN_B,
        depth_past_flip_errors=clean.depth_past_flip_errors,
        recorded_at="2026-02-01T00:00:00+00:00",
    )
    assert [r.depth_past_flip_errors for r in store.history()] == [3, 0]


def test_the_type_b_depth_joins_the_research_rows_on_the_campaign_id(
    test_database_url: str,
) -> None:
    # §16's research metrics are per campaign, and the three figures are
    # keyed by the same canonical id — so a reader holding one campaign's
    # row joins its base-rate-reweighted false discovery rate (feature
    # 267's, feature 341's surface), its discoveries per 1000
    # budget-charging trials (feature 346's) and its Type-B depth (this
    # feature's) without a second spelling of the campaign's identity.
    FdrDeployStore(test_database_url).persist(
        uuid.UUID(CAMPAIGN_A), _Pair(0.75, 0.25), computed_at="2026-01-01T00:00:00"
    )
    DiscoveryRates(test_database_url).record(
        CAMPAIGN_A, discoveries=8, budget_charging_trials=3200, ledger_trials=4000
    )
    depths = TypeBDepths(test_database_url)
    row = depths.record(CAMPAIGN_A, depth_past_flip_errors=5)
    # The row is readable by the same canonical spelling the other two
    # stores used, in any form uuid.UUID parses.
    assert depths.depth(uuid.UUID(CAMPAIGN_A)) == row
    assert depths.depth(CAMPAIGN_A.upper()) == row
    assert row.campaign_id == CAMPAIGN_A


def test_the_type_b_rows_share_the_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, held for this
    # table too: the scoring member's FDR_deploy rows, the member's
    # discovery-rate rows and its Type-B depth rows live in the one
    # database DATABASE_URL names, so an operator joins them in one query
    # rather than reconciling stores.
    from pathlib import Path
    from urllib.parse import urlparse

    FdrDeployStore(test_database_url).persist(
        uuid.UUID(CAMPAIGN_A), _Pair(0.75, 0.25), computed_at="2026-01-01T00:00:00"
    )
    DiscoveryRates(test_database_url).record(
        CAMPAIGN_A, discoveries=8, budget_charging_trials=3200, ledger_trials=4000
    )
    TypeBDepths(test_database_url).record(CAMPAIGN_A, depth_past_flip_errors=5)
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "scoring_fdr_deploy" in tables
    assert "ops_discovery_rate" in tables
    assert "ops_type_b_depth" in tables
