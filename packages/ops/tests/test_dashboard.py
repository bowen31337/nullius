"""Feature 351's surface: the Streamlit dashboard, primary panel first.

These tests hold the dashboard to its own sentence — *renders a
Streamlit dashboard whose primary panel displays FDR_deploy rather
than an equity curve* — from the side the member owns.  The figure is
the route's (feature 341, over feature 267's rows); what is pinned
here is the screen: the page model that has nowhere for an equity
curve to land, the review that refuses a foreign primary panel by
name, the render order that puts the numeral above every chart, the
honest absence for a deployment that has closed no campaign, and the
refusal — never a fallback numeral — when the route cannot be had.
The instrument lamps ride the same laws (feature 14's addition): the
page model that has nowhere for a lampless page to land, the render
that puts the rail above the count on every page, and the refusal —
never a lamp state nobody read — when the rail cannot be had.

And the provenance triple rides them too (feature 15's addition,
J06's gap — *"No triple is shown"*): the triple beside the figure is
read from the newest campaign's own node rows (§9.1's three CHAR(64)
columns, brought through the migrations' own ``apply`` the way the
providers member's suite brings its trees — never a hand-written
CREATE TABLE this suite would be inventing schema), the unrecorded
words are pinned for every state that honestly carries nothing (no
table, no columns, no stamp — including the backfilled tree whose
NULL rows predate the stamp), disagreeing nodes are refused as mixed
provenance with no triple displayed and none averaged, and a broken
read refuses the render rather than wearing the unrecorded words.

Streamlit is absent from this environment by design (the workspace
lockfile carries no third-party edge for it), so the render is tested
through a recording carrier duck-shaped like the module — which is
the whole contract, the same way the route's store is tested through
duck-typed carriers — and the real module is reached only through the
deferred door, whose repair words the absent case pins.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import runpy
import sqlite3
import sys
import types
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest
import scoring
from ops import (
    DASHBOARD_PAGE_TITLE,
    DASHBOARD_TITLE,
    FDR_DEPLOY_LABEL,
    OPS_DASHBOARD_COMPONENT_NAME,
    DashboardPage,
    DashboardRenderError,
    EpochCountChrome,
    EpochCountGauge,
    FdrDeployEndpoint,
    FdrDeployPanel,
    FdrDeployResponse,
    InstrumentStatusEndpoint,
    OperatorDashboard,
    OpsError,
    main,
    require_streamlit,
)
from ops.chrome import InstrumentLampsChrome
from ops.dashboard import (
    PROVENANCE_UNRECORDED,
    CampaignProvenance,
    NodeProvenanceReader,
)

from app.module_loader import Application, Registration, create_app, scan_components
from app.modules import ops as ops_seat

MEMBER_SRC = Path(__import__("ops").__file__).resolve().parent.parent

#: The Streamlit calls the render makes, in the order the render makes
#: them — the features' ordering law, asserted as the exact
#: transcript: page configuration, the title, the permanent chrome
#: (three lamp captions — docs §5.4's rail at the top of the left
#: rail — then feature 352's count strip), then the primary panel —
#: headline, numeral, plate, the campaign's provenance line — and only
#: then the one chart the dashboard draws.  Nothing renders above the
#: numeral but the chrome.
RENDER_SEQUENCE = (
    "set_page_config",
    "title",
    "caption",
    "caption",
    "caption",
    "caption",
    "header",
    "metric",
    "caption",
    "caption",
    "line_chart",
)

STREAMLIT_INSTALLED = importlib.util.find_spec("streamlit") is not None

# ── The node tree the triple is read from ──────────────────────────────────────
#
# The triple lives in §9.1's node-table columns (feature 99's, on feature
# 97's table), and this suite brings them the way a deployment does —
# through the migrations' own ``apply``, imported by file path exactly as
# ``packages/providers/tests/conftest.py`` loads the same tree's
# migrations (``migrations/`` is not a package and is not on sys.path).
# Nothing here hand-writes a CREATE TABLE: a suite that spelled the node
# schema itself would be pinning the dashboard's read against a schema
# the suite invented.

# conftest.py -> packages/ops/tests -> packages/ops -> packages -> root
VERSIONS_DIR = MEMBER_SRC.parents[2] / "migrations" / "versions"

#: The two revisions the triple's schema lives across, by id: the
#: table's (0118, feature 97's five structural columns) and the trio's
#: (0116, feature 99's three CHAR(64) columns).  Spelled as constants
#: so a reader sees which two migrations the triple is about without
#: reading the fixtures, and so a rename is one edit.
NODE_MIGRATION = "0118_node_table"
PROVENANCE_MIGRATION = "0116_provenance_trio"

#: The newest campaign the persisted store closes — the one whose node
#: rows the panel must read (the older campaign's rows are planted too,
#: with a different triple, so a test that reads the newest campaign's
#: rows is genuinely reading *that* campaign's and not whichever the
#: reader stumbled on).
NEWEST_CAMPAIGN = "22222222-2222-2222-2222-222222222222"
OLDER_CAMPAIGN = "11111111-1111-1111-1111-111111111111"

#: Two complete, distinct triples as 64-hex digests — two evaluators
#: over the same snapshot and cost model, which is the disagreement a
#: mixed campaign actually is: same data, different scorer.  Not real
#: digests of anything, for the reason the providers suite gives: this
#: suite is about which value lands in the reading and which is
#: refused, and a constant that happened to hash some artifact would
#: only invite a reader to think the suite was checking the artifact.
EVALUATOR_A = "e1" * 32
EVALUATOR_B = "b4" * 32
SNAPSHOT_A = "a2" * 32
COST_MODEL_A = "c3" * 32


def _migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    The same discipline ``packages/providers/tests/conftest.py``
    states the reasoning for: ``migrations/`` is not a package and is
    not on sys.path, and a migration is loaded by its runner the same
    way — by path — so loading it by path here is the shape a
    migration is *built* to be used in rather than a workaround.  A
    missing file fails naming the revision, because the one failure a
    test should never have to guess at is "the schema owner moved".
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the migrations "
            "that own the triple's schema rather than hand-writing their "
            "DDL, so it needs the schema's owner to be where the tree "
            "keeps it"
        )
    spec = importlib.util.spec_from_file_location(
        f"_ops_dashboard_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bring_node_table(database_url: str) -> None:
    """Bring the node table the way the chain does: 0118's table, then
    0116's trio.

    The table's migration runs first and the columns' second — 0116's
    ``ALTER`` needs the table to exist — which is the order the node
    tasks were renumbered into and the shape a deployment that ran the
    migrations lands on: three CHAR(64) columns with the NOT NULL
    constraints landed on the empty table, so every row planted after
    carries the triple or is refused by the database itself.
    """
    _migration(NODE_MIGRATION).apply(database_url)
    _migration(PROVENANCE_MIGRATION).apply(database_url)


def _backfilled_node_table(database_url: str) -> None:
    """Bring a populated tree whose trio accepts NULL — the backfill state.

    0116 emits the trio's ``ADD COLUMN`` with a bare ``NOT NULL``, which
    lands on an *empty* table and is refused on a populated one — its
    own docstring calls the refusal correct and the repair *"a
    backfill, not a spell"*.  This tree reaches the repair's first step
    the way the repair does: 0118's table, rows planted, then the trio
    added **without** the constraints — built from 0116's own
    :data:`COLUMNS` and :data:`COLUMN_TYPE` rather than a spelling
    written here, so the shape a test drives is one the schema's owner
    describes.  It is the only tree on which a node row can predate the
    stamp, which is why the NULL-row laws are tested here and not on
    the chain-built tree.
    """
    _migration(NODE_MIGRATION).apply(database_url)
    trio = _migration(PROVENANCE_MIGRATION)
    assert trio.COLUMNS, "0116 adds no columns, so this tree has nothing to add"
    path = Path(database_url.removeprefix("sqlite:///"))
    with closing(sqlite3.connect(path)) as connection, connection:
        for column in trio.COLUMNS:
            connection.execute(
                f"ALTER TABLE node ADD COLUMN {column} {trio.COLUMN_TYPE}"
            )


def _plant_node(
    database_url: str,
    campaign_id: str,
    *,
    evaluator: str | None = None,
    snapshot: str | None = None,
    cost_model: str | None = None,
    node_id: str | None = None,
) -> str:
    """Insert one node row for ``campaign_id``, and answer its id.

    Raw SQL against the table the migrations created rather than a call
    into a node-writing feature: the point is to produce the *state*
    the reading is about — a row exists for this campaign, carrying
    whatever triple it carries — not to reproduce the stamping path.
    The trio is supplied only where the tree has it (the PRAGMA
    presence check ``plant_node`` in the providers suite uses), so one
    helper plants on both trees: a chain-built one (where the NOT NULL
    columns demand a value) and the 0118-only one (where naming a
    column that does not exist would be an OperationalError about this
    helper rather than about the reader under test).  ``parent_id``
    stays NULL, which is what makes the row a root.
    """
    identifier = node_id or str(uuid.uuid4())
    path = Path(database_url.removeprefix("sqlite:///"))
    with closing(sqlite3.connect(path)) as connection, connection:
        present = {
            row[1] for row in connection.execute("PRAGMA table_info(node)")
        }
        columns = ["id", "parent_id", "campaign_id", "theme_root", "depth"]
        values: list[object] = [identifier, None, campaign_id, "macro", 0]
        for column, value in (
            ("evaluator_hash", evaluator),
            ("snapshot_hash", snapshot),
            ("cost_model_hash", cost_model),
        ):
            if column in present:
                columns.append(column)
                values.append(value)
        connection.execute(
            f"INSERT INTO node ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
    return identifier


def _stamped_tree(test_database_url: str) -> str:
    """A database holding the figures *and* both campaigns' node rows.

    The scoring store's two campaigns (the older with the symmetric
    pair, the newest with the 0.5 projection the render assertions
    read) over a chain-built node tree whose older campaign carries
    evaluator A and whose newest carries evaluator B — two distinct
    triples, one per campaign, so the newest campaign's reading is a
    question this tree genuinely answers: the panel must read *its*
    rows, not the older campaign's and not whichever row the reader
    stumbled on first.
    """
    _persisted_store(test_database_url)
    _bring_node_table(test_database_url)
    _plant_node(
        test_database_url,
        OLDER_CAMPAIGN,
        evaluator=EVALUATOR_A,
        snapshot=SNAPSHOT_A,
        cost_model=COST_MODEL_A,
    )
    _plant_node(
        test_database_url,
        NEWEST_CAMPAIGN,
        evaluator=EVALUATOR_B,
        snapshot=SNAPSHOT_A,
        cost_model=COST_MODEL_A,
    )
    return test_database_url


class _Pair:
    """A stand-in for feature 266's calibration figures — exactly the
    two attributes the reweighting reads, and nothing else."""

    __slots__ = ("sensitivity", "specificity")

    def __init__(self, sensitivity: float, specificity: float) -> None:
        self.sensitivity = sensitivity
        self.specificity = specificity


class _RecordingStreamlit:
    """A duck-typed stand-in for the ``streamlit`` module — one entry
    per call, in order, which is what makes the render's *order* (the
    feature's law) assertable without the UI library."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def _call(*args, **kwargs) -> None:
            self.calls.append((name, args, kwargs))

        return _call

    @property
    def names(self) -> list[str]:
        return [name for name, _args, _kwargs in self.calls]

    def of(self, name: str) -> list[tuple[tuple, dict]]:
        """Every call emitted under ``name``, in order — the chrome
        strip and the provenance plate are both captions now (feature
        352 grew the second one), so a page render holds two of that
        name and order is what tells them apart."""
        return [call[1:] for call in self.calls if call[0] == name]

    def one(self, name: str) -> tuple[tuple, dict]:
        """The single call emitted under ``name`` (callers use it only
        for names a page render emits once; captions are read through
        :meth:`of`, in order)."""
        matching = [call for call in self.calls if call[0] == name]
        assert len(matching) == 1, f"expected one {name}, got {matching}"
        return matching[0][1], matching[0][2]


def _persisted_store(test_database_url: str) -> scoring.FdrDeployStore:
    """The real store with two campaigns' figures landed through its
    own write, so the page under test reads real rows.  The pairs are
    chosen for their projections: a symmetric pair reweights to π₀
    (0.9), and the newest campaign's pair (sensitivity 0.45,
    specificity 0.95) reweights to exactly 0.5 — a clean numeral the
    render assertions can read."""
    store = scoring.FdrDeployStore(test_database_url)
    store.persist(
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        _Pair(0.5, 0.5),
        computed_at="2026-01-01T00:00:00",
    )
    store.persist(
        uuid.UUID("22222222-2222-2222-2222-222222222222"),
        _Pair(0.45, 0.95),
        computed_at="2026-02-01T00:00:00",
    )
    return store


class _RailCarrier:
    """A minimal rail carrier — the three seats with one lamp per state
    (lit, no reading, dark) — for page-construction tests that are
    about a different seat.  The rail's own laws live in the chrome
    module's suite, over the real route."""

    def __init__(self) -> None:
        self.lamps = {"canary": True, "ks_guard": None, "ingest": False}


def _lamps() -> InstrumentLampsChrome:
    # The lamps value over the minimal carrier — the page's third
    # required argument, handed to tests that build a page by hand to
    # pin a different seat's law.
    return InstrumentLampsChrome(response=_RailCarrier())


def _rail(test_database_url: str) -> InstrumentStatusEndpoint:
    # The lamps' rail over the same database, wired the way from_env
    # wires it — one env, one URL — so the page under test reads the
    # rail through feature 342's own route, each lamp the owning
    # member's own verdict.
    return InstrumentStatusEndpoint.from_env({"DATABASE_URL": test_database_url})


def _dashboard(test_database_url: str) -> OperatorDashboard:
    # The chrome's gauge, the lamps' rail and the provenance reader
    # all ride the same URL the route's store reads — the one-database
    # law — the gauge reading the epoch ledger the promotion member
    # owns (empty here, so the strip renders the honest 0), the rail
    # reading the instruments the deployment's members measured, and
    # the reader reading whatever node rows the tree carries (none
    # here, so the panel renders the unrecorded words — the states are
    # the dedicated provenance tests' to plant).
    return OperatorDashboard(
        FdrDeployEndpoint(_persisted_store(test_database_url)),
        EpochCountGauge(test_database_url),
        _rail(test_database_url),
        NodeProvenanceReader(test_database_url),
    )


# -- the component and its spellings -------------------------------------------


def test_the_dashboard_component_name_is_spelled_once_everywhere() -> None:
    # The member's constant, the app-seat's constant and the composed
    # application's order are one string — three spellings of one name
    # is exactly the kind of drift a test is cheaper than.
    assert OPS_DASHBOARD_COMPONENT_NAME == "ops-dashboard"
    assert ops_seat.DASHBOARD_COMPONENT_NAME == OPS_DASHBOARD_COMPONENT_NAME


def test_the_scan_registers_both_surfaces_exactly_once() -> None:
    # The registration-lives-in-__init__ invariant, held for the second
    # component: a rescan replaces by name, so one dashboard survives
    # any number of compositions rather than silently dropping out of
    # every one after the first.
    import ops

    registry = Registration()
    names = [c.name for c in scan_components(MEMBER_SRC, registry=registry)]
    assert names.count(OPS_DASHBOARD_COMPONENT_NAME) == 1
    assert OPS_DASHBOARD_COMPONENT_NAME in names
    assert ops.OPS_COMPONENT_NAME in names
    again = [c.name for c in scan_components(MEMBER_SRC, registry=registry)]
    assert again.count(OPS_DASHBOARD_COMPONENT_NAME) == 1


# -- the page is the route's answer ---------------------------------------------


def test_the_page_derives_every_read_from_the_routes_response(
    test_database_url: str,
) -> None:
    # The member's law is delegation: the panel adds display-shaped
    # reads over feature 341's response and re-spells nothing — the
    # numeral is the response's top line, the trend the response's
    # history, one answer rather than two that could disagree.
    dashboard = _dashboard(test_database_url)
    response = FdrDeployEndpoint(_persisted_store(test_database_url)).get()
    panel = dashboard.page().primary

    assert panel.figure == response.fdr_deploy
    assert panel.campaign_id == response.campaign_id == "22222222-2222-2222-2222-222222222222"
    assert panel.computed_at == response.computed_at == "2026-02-01T00:00:00"
    assert panel.trend == response.history
    assert panel.series == tuple(figure for _c, figure, _i in response.history)


def test_the_provenance_triple_is_visible_beside_the_figure(
    test_database_url: str,
) -> None:
    # The spec's ui_layout: "The primary panel is FDR_deploy with its
    # provenance triple", and its success criteria: "The operator reads
    # FDR_deploy as the primary figure with its provenance triple
    # visible".  The numeral (the figure), the plate (the campaign and
    # instant that attribute it) and the headline (the qualifier §16
    # carries beside the number) are all on the panel a render reads.
    panel = _dashboard(test_database_url).page().primary
    assert panel.numeral == "50.0%"
    assert "22222222-2222-2222-2222-222222222222" in panel.plate
    assert "2026-02-01T00:00:00" in panel.plate
    assert panel.headline.startswith(FDR_DEPLOY_LABEL)


def test_the_qualifier_is_read_from_the_one_spelling(
    test_database_url: str,
) -> None:
    # §16 lists the metric as "FDR_deploy at π₀ = 0.9" and the scoring
    # member's law is that the base rate travels beside the number.
    # The panel reads it through the member's deferred door from
    # DEPLOYMENT_BASE_RATE — never a literal here, which would be a
    # second place the deployment projection's constant could drift.
    panel = _dashboard(test_database_url).page().primary
    assert panel.qualifier == scoring.DEPLOYMENT_BASE_RATE
    assert panel.headline == f"FDR_deploy at π₀ = {scoring.DEPLOYMENT_BASE_RATE:g}"


def test_the_numeral_is_the_percentage_the_target_is_stated_in(
    test_database_url: str,
) -> None:
    # prd §11's target is "< 25% at π₀ = 0.9" — the form the operator
    # judges the figure in is a percentage, so that is the form the
    # render displays.  Both ends of [0, 1] are measurements and both
    # display.
    store = scoring.FdrDeployStore(test_database_url)
    store.persist(
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        _Pair(0.5, 1.0),
        computed_at="2026-01-01T00:00:00",
    )
    panel = OperatorDashboard(
        FdrDeployEndpoint(store),
        EpochCountGauge(test_database_url),
        _rail(test_database_url),
    ).page().primary
    assert panel.figure == 0.0
    assert panel.numeral == "0.0%"

    store.persist(
        uuid.UUID("22222222-2222-2222-2222-222222222222"),
        _Pair(0.0, 0.5),
        computed_at="2026-02-01T00:00:00",
    )
    assert panel.figure == 0.0  # the panel is frozen testimony
    fresh = OperatorDashboard(
        FdrDeployEndpoint(store),
        EpochCountGauge(test_database_url),
        _rail(test_database_url),
    ).page().primary
    assert fresh.figure == 1.0
    assert fresh.numeral == "100.0%"


def test_a_campaign_closed_between_two_renders_moves_the_numeral(
    test_database_url: str,
) -> None:
    # No cache anywhere in the dashboard: the route holds none, the
    # page is built fresh per render, and a campaign closed between two
    # renders moves the second numeral — a cached figure would make
    # the top line a fact about when the page was first opened.
    store = _persisted_store(test_database_url)
    dashboard = OperatorDashboard(
        FdrDeployEndpoint(store),
        EpochCountGauge(test_database_url),
        _rail(test_database_url),
    )
    assert dashboard.render(_RecordingStreamlit()).primary.figure == pytest.approx(0.5)

    newest = store.persist(
        uuid.UUID("33333333-3333-3333-3333-333333333333"),
        _Pair(0.75, 0.75),
        computed_at="2026-03-01T00:00:00",
    )
    page = dashboard.render(_RecordingStreamlit())
    assert page.primary.figure == newest == pytest.approx(0.75)
    assert newest != pytest.approx(0.5)
    assert page.primary.campaign_id == "33333333-3333-3333-3333-333333333333"


def test_the_page_is_frozen_testimony(test_database_url: str) -> None:
    # The page is the route's testimony at the moment it was read;
    # nothing on it is a knob to adjust.
    page = _dashboard(test_database_url).page()
    with pytest.raises(dataclasses.FrozenInstanceError):
        page.primary = page.primary  # type: ignore[misc]


# -- the provenance triple beside the figure --------------------------------------


def _tree_without_a_table(database_url: str) -> None:
    """The figures landed, and no node table at all — the deployment
    whose migrations have not brought the tree yet (0118 has not run)."""
    _persisted_store(database_url)


def _tree_without_the_columns(database_url: str) -> None:
    """The figures and the node table, and none of the trio's columns —
    the chain-ordering state 0116's own docstring names (the table's
    migration has run, the column features have not)."""
    _persisted_store(database_url)
    _migration(NODE_MIGRATION).apply(database_url)
    _plant_node(database_url, NEWEST_CAMPAIGN)


def _tree_of_unstamped_rows(database_url: str) -> None:
    """The figures and a backfilled tree whose rows predate the stamp —
    the state 0116 calls the repair (*"a backfill, not a spell"*):
    rows exist, the trio exists, and no row carries a value in it."""
    _persisted_store(database_url)
    _backfilled_node_table(database_url)
    _plant_node(database_url, NEWEST_CAMPAIGN)


def test_the_triple_is_read_from_the_newest_campaigns_own_node_rows(
    test_database_url: str,
) -> None:
    # J06's line, made literal: the newest campaign's
    # evaluator_hash, snapshot_hash and cost_model_hash — read from
    # *that* campaign's node rows.  The older campaign carries a
    # different triple in the same tree, so a reader that fetched
    # whichever rows it stumbled on (no campaign filter) would answer
    # the older campaign's evaluator for the newest campaign's figure —
    # the misattribution the join on campaign_id exists to prevent.
    _stamped_tree(test_database_url)
    provenance = _dashboard(test_database_url).page().primary.provenance
    assert provenance.triple == (EVALUATOR_B, SNAPSHOT_A, COST_MODEL_A)
    assert provenance.stamped == ((EVALUATOR_B, SNAPSHOT_A, COST_MODEL_A),)
    assert EVALUATOR_A not in provenance.stamped[0]
    assert not provenance.unrecorded
    assert not provenance.mixed


def test_the_triple_renders_beside_the_figure_short_form_full_on_the_value(
    test_database_url: str,
) -> None:
    # J06's acceptance: *"short form, full on hover/expand"* — the
    # caption beside the numeral carries each term's first twelve
    # characters under its own label, and the value the caller expands
    # (:attr:`triple`) carries the whole digest, so an operator can
    # read the triple at a glance and an audit can replay it in full.
    _stamped_tree(test_database_url)
    st = _RecordingStreamlit()
    page = _dashboard(test_database_url).render(st)
    line = page.primary.provenance.line
    assert line.startswith("provenance:")
    assert f"evaluator {EVALUATOR_B[:12]}…" in line
    assert f"snapshot {SNAPSHOT_A[:12]}…" in line
    assert f"cost model {COST_MODEL_A[:12]}…" in line
    # The short form is short: no full digest renders in the caption —
    # the expand holds it, not the line.
    for digest in (EVALUATOR_B, SNAPSHOT_A, COST_MODEL_A):
        assert digest not in line
    assert page.primary.provenance.triple == (
        EVALUATOR_B,
        SNAPSHOT_A,
        COST_MODEL_A,
    )
    assert st.of("caption")[5][0][0] == line


@pytest.mark.parametrize(
    "tree",
    [
        pytest.param(_tree_without_a_table, id="no-node-table"),
        pytest.param(_tree_without_the_columns, id="no-trio-columns"),
        pytest.param(_tree_of_unstamped_rows, id="unstamped-rows"),
    ],
)
def test_no_recorded_triple_says_provenance_unrecorded(
    test_database_url: str, tree
) -> None:
    # The other two states of the journey's own line: *"A campaign
    # with no recorded triple says provenance unrecorded"* — the exact
    # words, for every tree that honestly carries nothing: no table
    # (the migrations have not brought it), no columns (the chain's
    # own ordering state), or rows that predate the stamp (the NULL
    # the backfill leaves, the same spelling the ledger's read gives a
    # row that predates feature 87's).  Never a hash nobody recorded,
    # and never a zero-length Franken-triple either.
    tree(test_database_url)
    dashboard = _dashboard(test_database_url)
    provenance = dashboard.page().primary.provenance
    assert provenance.unrecorded
    assert provenance.triple is None
    assert not provenance.mixed
    st = _RecordingStreamlit()
    dashboard.render(st)
    assert st.of("caption")[5][0][0] == PROVENANCE_UNRECORDED


def test_disagreeing_nodes_render_the_mixed_provenance_refusal(
    test_database_url: str,
) -> None:
    # The journey's third state: *"one whose nodes disagree is refused
    # as mixed provenance, never averaged"* — the message names the
    # disagreement, displays no triple and averages none.  Picking
    # either evaluator would attribute the figure to one scorer the
    # campaign ran under while the rows say it ran under two, and an
    # averaged hash names an artifact nobody ever built.
    _stamped_tree(test_database_url)
    _plant_node(
        test_database_url,
        NEWEST_CAMPAIGN,
        evaluator=EVALUATOR_A,
        snapshot=SNAPSHOT_A,
        cost_model=COST_MODEL_A,
    )
    provenance = _dashboard(test_database_url).page().primary.provenance
    assert provenance.mixed
    assert provenance.triple is None
    message = provenance.line
    assert message.startswith("mixed provenance:")
    assert "2 distinct triples" in message
    assert "none is displayed and none is averaged" in message
    # No hash renders — neither of the two the rows carry, nor any
    # prefix of either: the refusal displays the disagreement, not a
    # contested attribution.
    for digest in (EVALUATOR_A, EVALUATOR_B, SNAPSHOT_A, COST_MODEL_A):
        assert digest[:12] not in message
    st = _RecordingStreamlit()
    _dashboard(test_database_url).render(st)
    assert st.of("caption")[5][0][0] == message


def test_a_row_that_predates_the_stamp_cannot_disagree(
    test_database_url: str,
) -> None:
    # The join is over *complete* triples: a row with a NULL term
    # states no triple, and a statement nobody made cannot contradict
    # one somebody did.  So a campaign with one stamped row and one
    # pre-stamp row answers the stamped triple — recorded, not mixed —
    # exactly as the ledger's provenance read treats a row that
    # predates feature 87's stamp.
    _persisted_store(test_database_url)
    _backfilled_node_table(test_database_url)
    _plant_node(
        test_database_url,
        NEWEST_CAMPAIGN,
        evaluator=EVALUATOR_B,
        snapshot=SNAPSHOT_A,
        cost_model=COST_MODEL_A,
    )
    _plant_node(test_database_url, NEWEST_CAMPAIGN)
    provenance = _dashboard(test_database_url).page().primary.provenance
    assert provenance.triple == (EVALUATOR_B, SNAPSHOT_A, COST_MODEL_A)
    assert provenance.stamped == ((EVALUATOR_B, SNAPSHOT_A, COST_MODEL_A),)
    assert not provenance.mixed
    assert provenance.line.startswith("provenance:")


@pytest.mark.parametrize(
    "not_a_digest",
    [
        "sha256:" + "e1" * 32,  # the image-reference spelling
        "deadbeef",  # not 64 characters
        "",  # blank is not NULL
    ],
)
def test_a_hash_that_is_not_the_digests_own_spelling_is_refused(
    test_database_url: str, not_a_digest: str
) -> None:
    # A hash is the one value whose whole meaning is naming an
    # artifact, and a term that names nothing rendered beside the
    # figure would be provenance no audit can replay.  The blank is
    # the important third case: a NULL term is the pre-stamp reading
    # and passes, but a blank string is a write somebody made — the
    # chain-built tree's NOT NULL columns admit it — and it is
    # refused rather than folded into the unrecorded words.
    _persisted_store(test_database_url)
    _bring_node_table(test_database_url)
    _plant_node(
        test_database_url,
        NEWEST_CAMPAIGN,
        evaluator=not_a_digest,
        snapshot=SNAPSHOT_A,
        cost_model=COST_MODEL_A,
    )
    with pytest.raises(DashboardRenderError) as raised:
        _dashboard(test_database_url).page()
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "evaluator_hash" in message
    assert "repair" in message
    # And the refusal never carries the value it refused: a malformed
    # hash is not displayed on its way to being rejected.  (The blank
    # case is checked by length, not containment — every string
    # contains the empty one.)
    if not_a_digest:
        assert not_a_digest not in message


def test_uppercase_hex_folds_to_the_one_artifact(test_database_url: str) -> None:
    # The ledger's canonicalization law, held at the panel: uppercase
    # and lowercase hex name the same digest, so a row stamped in
    # uppercase and one stamped in lowercase are one triple, not a
    # mixed campaign — the fold happens before the disagreement is
    # judged, never after.
    _persisted_store(test_database_url)
    _bring_node_table(test_database_url)
    _plant_node(
        test_database_url,
        NEWEST_CAMPAIGN,
        evaluator=EVALUATOR_B.upper(),
        snapshot=SNAPSHOT_A,
        cost_model=COST_MODEL_A,
    )
    _plant_node(
        test_database_url,
        NEWEST_CAMPAIGN,
        evaluator=EVALUATOR_B,
        snapshot=SNAPSHOT_A,
        cost_model=COST_MODEL_A,
    )
    provenance = _dashboard(test_database_url).page().primary.provenance
    assert not provenance.mixed
    assert provenance.triple == (EVALUATOR_B, SNAPSHOT_A, COST_MODEL_A)


def test_a_provenance_read_leaves_the_tree_untouched(
    test_database_url: str,
) -> None:
    # The reader is a reader: the node table is the migrations' and
    # the rows the discovery loop's, so a render — recorded,
    # unrecorded or mixed — leaves the raw rows byte-identical.
    _stamped_tree(test_database_url)
    path = Path(test_database_url.removeprefix("sqlite:///"))
    with closing(sqlite3.connect(path)) as connection:
        before = connection.execute(
            "SELECT id, campaign_id, evaluator_hash, snapshot_hash, "
            "cost_model_hash FROM node ORDER BY id"
        ).fetchall()
    _dashboard(test_database_url).render(_RecordingStreamlit())
    with closing(sqlite3.connect(path)) as connection:
        after = connection.execute(
            "SELECT id, campaign_id, evaluator_hash, snapshot_hash, "
            "cost_model_hash FROM node ORDER BY id"
        ).fetchall()
    assert after == before


def test_the_reader_refuses_a_campaign_that_names_nothing(
    test_database_url: str,
) -> None:
    # The join is on node.campaign_id, and an id that names nothing
    # would select no rows — rendering *unrecorded* for a campaign
    # that may carry the triple: the quiet wrong answer, refused
    # loudly instead.  The blank and the non-string are both refused.
    reader = NodeProvenanceReader(test_database_url)
    for campaign_id in ("", "   ", None):
        with pytest.raises(DashboardRenderError) as raised:
            reader.reading(campaign_id)
        assert isinstance(raised.value, OpsError)
        assert "campaign" in str(raised.value)


def test_a_broken_node_read_aborts_the_render_path_free(tmp_path: Path) -> None:
    # A read that cannot be made refuses the render — in the render
    # vocabulary, chained, and carrying no filesystem path (the
    # member's own constraint on every refusal it answers).  A URL
    # that names a directory is the honest way to break an sqlite
    # read: the open itself refuses, and the refusal that reaches the
    # operator names the reader and the repair, never the directory.
    reader = NodeProvenanceReader(f"sqlite:///{tmp_path}")
    with pytest.raises(DashboardRenderError) as raised:
        reader.reading(NEWEST_CAMPAIGN)
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "provenance reader" in message
    assert "node" in message
    assert str(tmp_path) not in message  # no filesystem path, ever
    assert raised.value.__cause__ is not None  # sqlite's own words, chained


def test_a_refusing_provenance_read_aborts_the_page_before_the_rail(
    test_database_url: str,
) -> None:
    # The ordering law, held for the fourth figure: the primary seat —
    # figure and triple together — is asked first, so a refusing
    # triple read aborts the page before the rail is ever asked (and
    # the rail, one seat over, before the gauge).  A failing route
    # read, a failing triple read, a failing rail read and a failing
    # ledger read stay distinguishable by vocabulary and by order.
    class _RefusingProvenance:
        def reading(self, campaign_id):
            raise DashboardRenderError("the reader's own words")

    class _NeverAskedRail:
        def get(self):
            raise AssertionError(
                "the rail was asked after the provenance read refused"
            )

    dashboard = OperatorDashboard(
        FdrDeployEndpoint(_persisted_store(test_database_url)),
        EpochCountGauge(test_database_url),
        _NeverAskedRail(),
        _RefusingProvenance(),
    )
    with pytest.raises(DashboardRenderError, match="the reader's own words"):
        dashboard.page()
    with pytest.raises(DashboardRenderError, match="the reader's own words"):
        dashboard.render(_RecordingStreamlit())


def test_the_provenance_carrier_is_duck_checked(test_database_url: str) -> None:
    # The contract is the reader's reading() — the reading value
    # itself is not enough (it answers one campaign, not a read a page
    # can re-ask on every render), the same split the route's and the
    # rail's carriers take, and the refusal names what the triple
    # needs.
    with pytest.raises(TypeError, match="reading"):
        OperatorDashboard(
            FdrDeployEndpoint(_persisted_store(test_database_url)),
            EpochCountGauge(test_database_url),
            _rail(test_database_url),
            CampaignProvenance(),
        )


def test_the_provenance_reader_refuses_a_url_that_names_nothing() -> None:
    # The reader renders on every populated page, so a reader pointed
    # at nothing is refused at wiring rather than silently rendering a
    # triple nobody read — the same stance the gauge takes toward its
    # own URL, restated for the triple's seat.
    with pytest.raises(DashboardRenderError) as raised:
        NodeProvenanceReader("   ")
    assert isinstance(raised.value, OpsError)
    assert "non-empty database URL" in str(raised.value)


def test_the_provenance_reader_wires_lazily_over_the_routes_url(
    test_database_url: str,
) -> None:
    # The three-argument construction from before the triple landed
    # keeps composing over exactly the database it always did: the
    # reader wires itself over the route's own carried URL on first
    # use — the one-database law, held for the fourth surface without
    # a second resolution the figure and its triple could drift apart
    # on.
    route = FdrDeployEndpoint(_persisted_store(test_database_url))
    dashboard = OperatorDashboard(
        route,
        EpochCountGauge(test_database_url),
        _rail(test_database_url),
    )
    assert dashboard.provenance.database_url == route.store.database_url


def test_the_provenance_seat_judges_the_contract_not_the_class(
    test_database_url: str,
) -> None:
    # The factory's scan imports members under synthetic names, so the
    # seat duck-checks the display contract — and the provenance seat
    # is the panel's own field, judged one level down: a carrier that
    # answers the provenance contract *is* the reading for every
    # purpose the render has, and a panel whose provenance answers
    # nothing is refused by name with J06's own reason carried in the
    # words.
    real = _dashboard(test_database_url).page().primary

    class _DuckProvenance:
        triple = real.provenance.triple
        unrecorded = real.provenance.unrecorded
        mixed = real.provenance.mixed
        line = real.provenance.line

    class _DuckPanel:
        figure = real.figure
        trend = real.trend
        qualifier = real.qualifier
        headline = real.headline
        numeral = real.numeral
        plate = real.plate
        series = real.series
        provenance = _DuckProvenance()

    page = DashboardPage(
        primary=_DuckPanel(),  # type: ignore[arg-type]
        chrome=EpochCountChrome(count=0),
        lamps=_lamps(),
    )
    assert page.primary.provenance.line == real.provenance.line

    class _PanelWithoutAReading:
        figure = real.figure
        trend = real.trend
        qualifier = real.qualifier
        headline = real.headline
        numeral = real.numeral
        plate = real.plate
        series = real.series
        provenance = None  # a seat that cannot state its reading

    with pytest.raises(DashboardRenderError) as raised:
        DashboardPage(
            primary=_PanelWithoutAReading(),  # type: ignore[arg-type]
            chrome=EpochCountChrome(count=0),
            lamps=_lamps(),
        )
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "provenance" in message
    assert "triple" in message





def test_an_empty_trend_renders_no_numeral_ever_a_flawless_one(
    test_database_url: str,
) -> None:
    # Feature 341's docstring hands this surface its law: "The
    # dashboard this route feeds renders no numeral for it; what it
    # must never render is a flawless one."  A dash where the numeral
    # would be, words that say why, and no chart of an empty series.
    dashboard = OperatorDashboard(
        FdrDeployEndpoint(scoring.FdrDeployStore(test_database_url)),
        EpochCountGauge(test_database_url),
        _rail(test_database_url),
    )
    panel = dashboard.page().primary
    assert not panel
    assert panel.figure is None
    assert panel.numeral is None
    assert panel.plate is None
    assert panel.series == ()

    st = _RecordingStreamlit()
    page = dashboard.render(st)
    assert not page.primary
    value = st.one("metric")[1]["value"]
    assert value == "—"
    assert value != "0.0%"
    # Five captions, in order: the three lamp lines still render (the
    # "on every render" clause — the rail does not wait for content,
    # and this is the page where every lamp but the canary carries its
    # absence as words), then the count strip (the "at all times"
    # clause — the count does not wait for content either), then the
    # words that say why there is no numeral.
    captions = st.of("caption")
    assert len(captions) == 5
    assert [call[0][0] for call in captions[:3]] == list(page.lamps.lines)
    assert captions[3][0][0] == page.chrome.line
    assert captions[4][0][0].startswith("no campaign has closed")
    # No chart of an empty series: the trend chart is the panel's own,
    # and an absent trend has none to draw.
    assert "line_chart" not in st.names


# -- the render order is the law --------------------------------------------------


def test_the_render_emits_the_primary_panel_first(test_database_url: str) -> None:
    # The features' clause made literal: page configuration, the
    # title, the permanent chrome — the rail first (docs §5.4 draws
    # the lamps at the top of the left rail, so they are the first
    # thing beneath the title), then feature 352's count strip — then
    # the primary panel — headline, numeral, plate, the campaign's
    # provenance line — and only then the one chart the dashboard
    # draws, over the panel's own FDR_deploy trend.  Nothing renders
    # above the numeral but the chrome, and the only series ever
    # charted is the trend's figures.
    st = _RecordingStreamlit()
    page = _dashboard(test_database_url).render(st)

    assert st.names == list(RENDER_SEQUENCE)
    assert st.names.index("metric") < st.names.index("line_chart")
    # The numeral is the primary panel's, labelled with the metric's
    # one spelling.
    metric_args, metric_kwargs = st.one("metric")
    assert not metric_args
    assert metric_kwargs["label"] == FDR_DEPLOY_LABEL
    assert metric_kwargs["value"] == page.primary.numeral
    # The header is the panel's headline — the qualifier beside the
    # figure's name, §16's own line.
    assert st.one("header")[0][0] == page.primary.headline
    # Six captions, in order: the three lamp lines (permanent, above
    # the count), the count strip (permanent, above the panel), then
    # the provenance plate beneath the numeral and the campaign's
    # provenance line completing it.
    captions = st.of("caption")
    assert len(captions) == 6
    assert [call[0][0] for call in captions[:3]] == list(page.lamps.lines)
    assert captions[3][0][0] == page.chrome.line
    assert captions[4][0][0] == page.primary.plate
    assert captions[5][0][0] == page.primary.provenance.line
    # The one chart is the trend, and nothing else is charted.
    chart_args, _kwargs = st.one("line_chart")
    assert chart_args[0] == list(page.primary.series)
    assert st.one("set_page_config")[1]["page_title"] == DASHBOARD_PAGE_TITLE
    assert st.one("title")[0][0] == DASHBOARD_TITLE


def test_the_numeral_carries_no_delta(test_database_url: str) -> None:
    # Streamlit colours a metric delta green-up, and the figure has no
    # "up is good" direction — a lower false discovery rate is better —
    # so the colour would state the opposite of the measurement.  The
    # render passes exactly the label and the value.
    st = _RecordingStreamlit()
    _dashboard(test_database_url).render(st)
    _args, kwargs = st.one("metric")
    assert set(kwargs) == {"label", "value"}


def test_the_render_answers_the_page_it_rendered(test_database_url: str) -> None:
    # The caller (or the test) can read exactly what the operator saw:
    # the page answered is the page that rendered.
    dashboard = _dashboard(test_database_url)
    st = _RecordingStreamlit()
    assert dashboard.render(st) == dashboard.page()


# -- the review: rather than an equity curve --------------------------------------


def test_the_model_has_nowhere_for_an_equity_curve_to_land() -> None:
    # The structural half of the clause, pinned as a shape: the page
    # holds a primary seat, its chrome and its lamps (feature 352's
    # count and the rail's response — the two fields the page grew,
    # carrying figures and bits and nothing a curve could occupy), the
    # panel holds the route's response and the campaign's provenance
    # reading (the two facts the panel attributes the figure by), the
    # response holds the per-campaign FDR_deploy history, the reading
    # holds the node rows — and that is the whole surface, top to
    # bottom.  A returns series, a NAV curve or a Sharpe has no field
    # anywhere on this path to occupy, so the substitution cannot be
    # represented, let alone rendered.
    assert [f.name for f in dataclasses.fields(DashboardPage)] == [
        "primary",
        "chrome",
        "lamps",
    ]
    assert [f.name for f in dataclasses.fields(FdrDeployPanel)] == [
        "response",
        "provenance",
    ]
    assert [f.name for f in dataclasses.fields(FdrDeployResponse)] == ["history"]
    assert [f.name for f in dataclasses.fields(CampaignProvenance)] == ["rows"]
    assert [f.name for f in dataclasses.fields(EpochCountChrome)] == ["count"]
    assert [f.name for f in dataclasses.fields(InstrumentLampsChrome)] == [
        "response"
    ]


def test_a_page_whose_primary_is_not_the_fdr_panel_is_refused() -> None:
    # The spec's design system: "any panel that would promote profit
    # above epistemic state is rejected at review".  The page model is
    # that review, made executable: an equity-curve panel — a carrier
    # of NAV points that answers none of the FDR panel's reads — is
    # refused by name, with §16's abandonment sentence in the refusal.
    class _EquityCurvePanel:
        """What the clause refuses: a P&L series posing as the primary
        panel — points of account equity, and not one epistemic read."""

        series = (100.0, 101.2, 99.8, 103.0)

    with pytest.raises(DashboardRenderError) as raised:
        DashboardPage(
            primary=_EquityCurvePanel(),  # type: ignore[arg-type]
            chrome=EpochCountChrome(count=0),
            lamps=_lamps(),
        )
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "equity curve" in message
    assert "quietly abandoned" in message
    assert "series" in message


def test_a_page_whose_lamps_answer_no_rail_is_refused(
    test_database_url: str,
) -> None:
    # The review's third seat, one refusal over from the primary's: a
    # carrier that answers none of the lamps' display contract (an
    # instrument panel of dials and figures — the shape §5.4's rail is
    # drawn against) cannot sit in permanent chrome, and the page
    # refuses it by name with §5.4's own reason carried in the words.
    class _DialPanel:
        """What the seat refuses: an instrument panel of figures, and
        no rail anywhere — three readings, not three lamps."""

        readings = (0.42, 7.5, 1.0)

    with pytest.raises(DashboardRenderError) as raised:
        DashboardPage(
            primary=_dashboard(test_database_url).page().primary,
            chrome=EpochCountChrome(count=0),
            lamps=_DialPanel(),  # type: ignore[arg-type]
        )
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "lamps" in message
    assert "worthless" in message  # §5.4's own reason, carried


def test_the_primary_seat_judges_the_contract_not_the_class(
    test_database_url: str,
) -> None:
    # The factory's scan imports members under synthetic names, so a
    # composed panel is structurally this member's without being the
    # same class object a direct import yields — the seat duck-checks
    # the display contract, and a carrier that answers all of it *is*
    # an FDR_deploy panel for every purpose the render has.
    real = _dashboard(test_database_url).page().primary

    class _DuckPanel:
        figure = real.figure
        trend = real.trend
        qualifier = real.qualifier
        headline = real.headline
        numeral = real.numeral
        plate = real.plate
        series = real.series
        provenance = real.provenance

    page = DashboardPage(
        primary=_DuckPanel(),  # type: ignore[arg-type]
        chrome=EpochCountChrome(count=0),
        lamps=_lamps(),
    )
    assert page.primary.numeral == real.numeral


# -- the doors and their refusals -------------------------------------------------


def test_composed_refuses_when_the_route_is_absent() -> None:
    # The seat's docstring names this surface as the caller that must
    # refuse: "a caller that needs the top-line figure and resolves
    # None must refuse to proceed rather than rendering a numeral
    # nobody measured."  A composition with no ops route is refused
    # naming the repair — never answered around with a fallback.
    with pytest.raises(DashboardRenderError) as raised:
        OperatorDashboard.composed(Application())
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "/metrics/fdr-deploy" in message
    assert "DATABASE_URL" in message


def test_composed_refuses_when_the_rail_is_absent() -> None:
    # The rail's own absence refusal, one seat over: a composition
    # that carries the fdr-deploy route but no instrument-status route
    # is refused naming the route and the repair — the page it would
    # render is a page whose lamps went missing rather than dark, a
    # shorter rail than the design draws, which is the one screen
    # where an instrument's state could go unasked.  The application
    # here is a duck carrier answering the one component — the seat's
    # contract is the get(), the same duck-check the constructor takes.
    class _AppWithOnlyTheRoute:
        def get(self, name: str):
            return object() if name == ops_seat.COMPONENT_NAME else None

    with pytest.raises(DashboardRenderError) as raised:
        OperatorDashboard.composed(_AppWithOnlyTheRoute())
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "/metrics/instrument-status" in message
    assert "DATABASE_URL" in message
    assert "worthless" in message  # §5.4's own reason, carried


def test_main_refuses_when_the_route_is_absent() -> None:
    # The entrypoint inherits the same law: nothing renders when the
    # figure cannot be had honestly.
    with pytest.raises(DashboardRenderError):
        main(app=Application(), st=_RecordingStreamlit())


def test_the_route_carrier_is_duck_checked() -> None:
    # The contract is the route's get() — the store itself is not
    # enough (it answers the trend, not the route's response), and the
    # refusal says so.
    with pytest.raises(TypeError, match="OperatorDashboard"):
        OperatorDashboard(
            "sqlite:///nowhere.db",
            EpochCountGauge("sqlite:///x.db"),
            InstrumentStatusEndpoint.from_env(
                {"DATABASE_URL": "sqlite:///nowhere.db"}
            ),
        )


def test_the_rail_carrier_is_duck_checked(test_database_url: str) -> None:
    # The contract is the rail's get() — the response itself is not
    # enough (it answers one rail, not a route a page can re-ask on
    # every render), the same split the route's carrier takes, and the
    # refusal names what the lamps need.
    with pytest.raises(TypeError, match="rail"):
        OperatorDashboard(
            FdrDeployEndpoint(scoring.FdrDeployStore(test_database_url)),
            EpochCountGauge(test_database_url),
            _rail(test_database_url).get(),
        )


def test_the_render_carrier_is_duck_checked(test_database_url: str) -> None:
    # The render contract is the Streamlit calls it makes; a carrier
    # that cannot answer them cannot render the primary panel.
    with pytest.raises(TypeError, match="OperatorDashboard"):
        _dashboard(test_database_url).render(object())


def test_a_failing_read_propagates_as_the_routes_own_vocabulary(
    test_database_url: str,
) -> None:
    # The route already translated the store's refusal into the
    # member's vocabulary; the dashboard neither re-wraps it (which
    # would bury which surface refused) nor catches it into an answer
    # (every fallback is a number nobody measured).
    from ops.errors import FdrDeployMetricError

    class _RefusingRoute:
        def get(self):
            raise FdrDeployMetricError("the route's own words")

    class _NeverAskedRail:
        """A rail that fails the test if the lamps are read at all —
        the primary seat is asked first, so a refusing route aborts the
        page before the rail is ever requested."""

        def get(self):
            raise AssertionError("the rail was asked after the route refused")

    class _NeverAskedGauge:
        """A gauge that fails the test if the chrome is read at all —
        the rail is asked before it, so a refusing route aborts the
        page before the count's figure is ever requested either."""

        def remaining(self) -> int:
            raise AssertionError("the chrome was asked after the route refused")

    dashboard = OperatorDashboard(_RefusingRoute(), _NeverAskedGauge(), _NeverAskedRail())
    with pytest.raises(FdrDeployMetricError, match="the route's own words"):
        dashboard.page()
    with pytest.raises(FdrDeployMetricError, match="the route's own words"):
        dashboard.render(_RecordingStreamlit())


def test_streamlit_is_resolved_lazily_and_names_its_repair(
    test_database_url: str,
) -> None:
    # The deferred door: §16's stack line names Streamlit the way it
    # names Postgres — an environment the operator runs, not a
    # workspace dependency — so the module is absent here by design,
    # and the render told to resolve it says which wheel is missing
    # rather than failing with a bare ImportError.
    dashboard = _dashboard(test_database_url)
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    with pytest.raises(ModuleNotFoundError) as raised:
        dashboard.render()
    assert "streamlit" in str(raised.value)
    assert "uv pip install streamlit" in str(raised.value)


def test_require_streamlit_resolves_the_installed_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The deferred door, pinned from the side that has the module: a
    # deployment that carries Streamlit gets exactly the module it
    # installed — the door resolves and returns, nothing more.
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    fake = types.ModuleType("streamlit")
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    assert require_streamlit() is fake


def test_the_deferred_door_uses_an_injected_streamlit(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the deferral: a deployment that does carry
    # Streamlit renders through exactly the module it installed — the
    # door resolves it and the render emits through it.
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    recorder = _RecordingStreamlit()
    fake = types.ModuleType("streamlit")
    for name in RENDER_SEQUENCE:
        setattr(fake, name, getattr(recorder, name))
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    page = _dashboard(test_database_url).render()
    assert page.primary.numeral == "50.0%"
    assert recorder.names == list(RENDER_SEQUENCE)


def test_building_imports_neither_streamlit_nor_the_scoring_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The scan-order law, held for the second component: builders fire
    # after the factory's scan has taken each member's src/ back off
    # sys.path, and this workspace carries no streamlit edge at all —
    # so the builder (and the from_env door it wraps) imports neither
    # the sibling whose constant the qualifier reads nor the UI library
    # the render defers to.  The first page is where both are needed.
    import builtins

    real_import = builtins.__import__

    def _no_deferred(name, *args, **kwargs):
        if name in ("scoring", "streamlit"):
            raise AssertionError(
                f"the builder must not import {name} — it runs after the "
                "factory's scan has taken the sibling's src/ off "
                "sys.path, and the UI library is the deployment's "
                "ambient dependency (feature 351)"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_deferred)
    dashboard = OperatorDashboard.from_env(
        {"DATABASE_URL": "sqlite:///tmp/ops-dashboard-deferred-test.db"}
    )
    assert dashboard is not None
    assert dashboard.route.route == "/metrics/fdr-deploy"


# -- construction and composition -------------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"DATABASE_URL": ""},
        {"DATABASE_URL": "   "},
        {"DATABASE_URL": "sqlite:///tmp/ops-dashboard-env-1.db"},
        {"DATABASE_URL": "sqlite:///tmp/ops-dashboard-env-2.db"},
    ],
)
def test_from_env_composes_exactly_when_the_route_does(env) -> None:
    # The dashboard composes on the route's own decision — the same
    # unset spellings, the same resolved URL — with no second
    # resolution the two surfaces could drift apart on.  The chrome's
    # gauge, the lamps' rail and the provenance reader all ride the URL
    # the route carries, so all four compose on exactly the same
    # decision and point at exactly the same database.
    route = FdrDeployEndpoint.from_env(env)
    dashboard = OperatorDashboard.from_env(env)
    if route is None:
        assert dashboard is None
    else:
        assert dashboard is not None
        assert dashboard.route.store.database_url == route.store.database_url
        assert dashboard.gauge.database_url == route.store.database_url
        assert dashboard.rail.readings.database_url == route.store.database_url
        assert dashboard.provenance.database_url == route.store.database_url


def test_from_env_refuses_when_the_rail_will_not_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The two doors read the one variable, so a rail that answers None
    # while the route composed can only mean the environment moved
    # under the build — and the dashboard refuses rather than
    # answering around with a lampless page, the same page the
    # constructor's own wiring refusal rules out, refused at the one
    # seam that could still build it.  Pinned with a stub door, the
    # one way the split can be made to happen deterministically.
    from ops import dashboard as dashboard_module

    class _NoRail:
        @classmethod
        def from_env(cls, env=None):
            return None

    monkeypatch.setattr(dashboard_module, "InstrumentStatusEndpoint", _NoRail)
    with pytest.raises(DashboardRenderError) as raised:
        OperatorDashboard.from_env(
            {"DATABASE_URL": "sqlite:///tmp/ops-dashboard-rail-split.db"}
        )
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "instrument rail" in message
    assert "/metrics/instrument-status" in message


def test_the_dashboard_and_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, pinned at
    # composition for all five surfaces: the route that answers the
    # figure, the dashboard that renders it, the gauge that counts the
    # ledger, the rail that reads the instruments and the reader that
    # reads the node rows resolve the one database DATABASE_URL names —
    # never two the numeral, its rows, its count, its lamps or its
    # triple could drift apart on.  Feature 352's gauge, the rail and
    # the provenance reader ride the same carried URL, so both strips
    # and the triple are drawn from the one database too.
    app = create_app(MEMBER_SRC, registry=Registration())
    route = app.get("ops-fdr-deploy")
    dashboard = app.get("ops-dashboard")
    assert dashboard is not None and route is not None
    assert dashboard.route.store.database_url == route.store.database_url
    assert dashboard.route.store.database_url == test_database_url
    assert dashboard.gauge.database_url == test_database_url
    assert dashboard.rail.readings.database_url == test_database_url
    assert dashboard.provenance.database_url == test_database_url
    assert "ops-dashboard" in app.order and "ops-fdr-deploy" in app.order
    assert ops_seat.OPS_INSTRUMENT_STATUS_COMPONENT_NAME in app.order


def test_the_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no dashboard,
    # mirroring the route builder beside it.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("ops-dashboard") is None


def test_composing_the_dashboard_touches_no_disk(
    test_database_url: str,
) -> None:
    from urllib.parse import urlparse

    # Building performs no I/O: no store constructed, no database
    # opened, no page read — the first render is where the route is
    # asked, and the route asks the store then.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_seat_exposes_the_composed_dashboard(test_database_url: str) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ops_seat.dashboard_component(app)
    assert component is app.get("ops-dashboard")
    assert component is not None
    assert callable(component.page)


def test_main_renders_through_the_composed_route(test_database_url: str) -> None:
    # The entrypoint's whole path: compose, read, render — the page it
    # answers is the page the operator saw, through the application's
    # own composed route rather than a second resolution.
    _persisted_store(test_database_url)
    app = create_app(MEMBER_SRC, registry=Registration())
    st = _RecordingStreamlit()
    page = main(app=app, st=st)
    assert page.primary.figure == pytest.approx(0.5)
    assert st.names == list(RENDER_SEQUENCE)


# -- the script entrypoint --------------------------------------------------------


def test_the_streamlit_run_bootstrap_reaches_main(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `streamlit run packages/ops/src/ops/dashboard.py` executes the
    # file as a script — no package context — so the module's guard
    # puts the member's src/ on sys.path and resolves __package__
    # before the relative imports run.  Pinned by running the file the
    # way runpy runs it: the imports resolve, main() is reached, and
    # (streamlit being absent here) the render names its repair rather
    # than failing on a relative import nobody fixed.
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    with pytest.raises(ModuleNotFoundError) as raised:
        runpy.run_path(
            str(MEMBER_SRC / "ops" / "dashboard.py"),
            run_name="__main__",
        )
    assert "uv pip install streamlit" in str(raised.value)
