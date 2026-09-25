"""Feature 352's surface: the permanent chrome — the remaining clean
epoch count.

These tests hold the chrome to its own sentence — *displays the
remaining clean epoch count in permanent dashboard chrome, so
depletion stays visible* — from the side the member owns.  The figure
is the promotion member's (feature 297's gauge over feature 294's
ledger); what is pinned here is the strip: the count that is feature
297's figure to the bit and never a second derivation, the permanence
(a page is not constructible without its chrome, and the strip renders
beneath the title on every page — including the one where no campaign
has closed), the visible exhaustion (a zero count renders as zero,
never a refusal, never a blank), the refusal vocabulary (a carrier
that cannot answer the count, a count that is not one, a ledger read
that fails — each named, none answered around), and the composition
facts (the gauge rides the URL the route carried; building imports no
sibling and no UI library).

The ledger rows are landed the way the promotion member's own suite
lands them: the epoch rows by a raw insert standing in for the
sealing process (the write this workspace assigns to the sealing
process, not to the promotion member), the served counts by a raw
update standing in for the charging one — so the chrome under test
reads real rows through the real gauge, and the count on the screen
is the count §13 item 4 budgets the system's continuation on.
"""

from __future__ import annotations

import ast
import sqlite3
import sys
import types
import uuid
from pathlib import Path

import promotion
import pytest
import scoring
from ops import (
    EPOCH_COUNT_LABEL,
    DashboardPage,
    DashboardRenderError,
    EpochCountChrome,
    EpochCountGauge,
    FdrDeployEndpoint,
    OperatorDashboard,
    OpsError,
    main,
    require_promotion,
)

from app.module_loader import Registration, create_app
from app.modules import ops as ops_seat

MEMBER_SRC = Path(__import__("ops").__file__).resolve().parent.parent

#: The sealing instant the landed rows carry — the same literal shape
#: the promotion member's own suite seeds, so a row read back through
#: the member's validators revalidates.
SEALED_AT = "2026-01-01T00:00:00+00:00"

#: Three epoch names, so a count reads as a statement about the whole
#: ledger rather than about one row.
EPOCH_A = "epoch-2026-01"
EPOCH_B = "epoch-2026-02"
EPOCH_C = "epoch-2026-03"


class _Pair:
    """A stand-in for feature 266's calibration figures — exactly the
    two attributes the reweighting reads, and nothing else."""

    __slots__ = ("sensitivity", "specificity")

    def __init__(self, sensitivity: float, specificity: float) -> None:
        self.sensitivity = sensitivity
        self.specificity = specificity


class _RecordingStreamlit:
    """A duck-typed stand-in for the ``streamlit`` module — one entry
    per call, in order, which is what makes the render's order (where
    the chrome sits) assertable without the UI library."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def _call(*args, **kwargs) -> None:
            self.calls.append((name, args, kwargs))

        return _call

    @property
    def names(self) -> list[str]:
        return [name for name, _args, _kwargs in self.calls]

    def captions(self) -> list[str]:
        """Every caption's text, in render order — the chrome strip
        first (beneath the title), the panel's words after."""
        return [call[1][0] for call in self.calls if call[0] == "caption"]


def _land_ledger(test_database_url: str, served_by_epoch: dict[str, int]) -> None:
    """Land epoch rows the way the promotion member's own suite does.

    The epoch row is the sealing process's write and the served count
    is the charging one's — neither of which is the ops member's to
    invent — so both are landed raw, over the table feature 294's own
    store brings up through the owning migration's statements (the
    first ``epochs()`` read creates it), exactly the stance
    ``packages/promotion/tests/test_promotion_remaining.py`` takes for
    the same rows.
    """
    promotion.EpochCharges(test_database_url).epochs()
    connection = sqlite3.connect(
        Path(test_database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            for epoch, served in served_by_epoch.items():
                connection.execute(
                    f"INSERT INTO {promotion.EPOCH_LEDGER_TABLE} "
                    f"({promotion.EPOCH_ID_COLUMN}, "
                    f"{promotion.SEALED_AT_COLUMN}) VALUES (?, ?)",
                    (epoch, SEALED_AT),
                )
                connection.execute(
                    f"UPDATE {promotion.EPOCH_LEDGER_TABLE} "
                    f"SET {promotion.PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
                    f"WHERE {promotion.EPOCH_ID_COLUMN} = ?",
                    (served, epoch),
                )
    finally:
        connection.close()


def _spend(test_database_url: str, epoch: str, served: int) -> None:
    """Advance one epoch's served count, standing in for the charging
    process — the write that must move the strip on the next render."""
    connection = sqlite3.connect(
        Path(test_database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {promotion.EPOCH_LEDGER_TABLE} "
                f"SET {promotion.PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
                f"WHERE {promotion.EPOCH_ID_COLUMN} = ?",
                (served, epoch),
            )
    finally:
        connection.close()


def _raw_ledger(test_database_url: str) -> list[tuple]:
    """The whole ledger raw, so a test sees the table rather than
    asking the code under test to confirm itself."""
    connection = sqlite3.connect(
        Path(test_database_url.removeprefix("sqlite:///"))
    )
    try:
        cursor = connection.execute(
            f"SELECT * FROM {promotion.EPOCH_LEDGER_TABLE} "
            f"ORDER BY {promotion.EPOCH_ID_COLUMN}"
        )
        try:
            return cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()


def _dashboard(test_database_url: str) -> OperatorDashboard:
    """A dashboard over both real figures: one closed campaign for the
    primary panel, the promotion ledger for the chrome."""
    store = scoring.FdrDeployStore(test_database_url)
    store.persist(
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        _Pair(0.45, 0.95),
        computed_at="2026-02-01T00:00:00",
    )
    return OperatorDashboard(
        FdrDeployEndpoint(store), EpochCountGauge(test_database_url)
    )


def _code_of(module) -> str:
    """A module's *code* as unparsed text, with every docstring
    stripped — the promotion member's own technique, so a test can
    assert a claim about what a module does (never spells a budget,
    never spells a SELECT) without tripping on the prose that says
    so."""
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    holders = [tree]
    holders += [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for holder in holders:
        body = holder.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            holder.body = body[1:]
    return ast.unparse(tree)


# -- the count is feature 297's figure --------------------------------------------


def test_the_count_is_feature_297s_figure_to_the_bit(
    test_database_url: str,
) -> None:
    # The member's law is delegation, and this is its hardest form: a
    # ledger with two clean epochs and one spent (served == budget),
    # read three ways — through the dashboard's chrome, through the
    # promotion member's own gauge over its own store, and through the
    # pure count over the same rows — answers one figure.  A chrome
    # that had re-derived "clean" its own way would have to agree with
    # feature 297 by luck, not by construction.
    _land_ledger(
        test_database_url,
        {EPOCH_A: 0, EPOCH_B: promotion.SEQUESTERED_EPOCH_BUDGET - 1, EPOCH_C: 3},
    )
    chrome = _dashboard(test_database_url).page().chrome
    through_the_store = promotion.RemainingCleanEpochs(
        promotion.EpochCharges(test_database_url)
    ).remaining()
    through_the_pure_count = promotion.clean_epochs_remaining(
        promotion.EpochCharges(test_database_url).epochs()
    )
    assert chrome.count == through_the_store == through_the_pure_count == 2


def test_the_derivation_is_never_restated() -> None:
    # The budget, the served column and the comparison are the
    # promotion member's spellings, and a second one here would be a
    # second place the system's remaining lifetime could be computed
    # two ways.  Pinned on the code (docstrings stripped) rather than
    # the words: no budget constant, no served-column read, and no SQL
    # of its own — the only table access is the gauge's ``remaining()``.
    from ops import chrome as module

    code = _code_of(module)
    assert "SEQUESTERED_EPOCH_BUDGET" not in code
    assert "PROMOTION_DECISIONS_SERVED" not in code
    assert "SELECT" not in code
    assert "epoch_ledger" not in code
    # And the sibling is deferred: the module carries no module-scope
    # handle on it (the import lives inside the door, fired on the
    # read path and nowhere else).
    assert not hasattr(module, "promotion")


def test_the_count_never_reads_the_flag_or_the_sealing_instant() -> None:
    # Feature 297's own boundary, held at the surface: ``retired`` is
    # feature 296's flag and ``sealed_at`` is the sealing process's
    # fact, and a chrome that read either would be judging the
    # terminal state or re-deriving sequestration — promotion's job,
    # already done, on the figure this strip displays.
    from ops import chrome as module

    code = _code_of(module)
    assert ".retired" not in code
    assert ".sealed_at" not in code


def test_a_read_leaves_the_ledger_untouched(test_database_url: str) -> None:
    # The chrome is a reader: the count is 294's to persist and the
    # flag 296's to set, so a render — permitted, spent or empty —
    # leaves the raw table byte-identical.
    _land_ledger(test_database_url, {EPOCH_A: 1, EPOCH_B: 3})
    before = _raw_ledger(test_database_url)
    _dashboard(test_database_url).render(_RecordingStreamlit())
    assert _raw_ledger(test_database_url) == before


# -- depletion stays visible --------------------------------------------------------


def test_depletion_moves_the_strip_between_renders(test_database_url: str) -> None:
    # The feature's clause, made literal: an epoch spent between two
    # renders moves the second strip.  Nothing caches — not the
    # dashboard, not the gauge (feature 297's own law) — because a
    # chrome that memoised its count would make "how much system is
    # left?" a fact about when the page was first opened, which is the
    # invisibility this feature exists to prevent.
    _land_ledger(
        test_database_url, {EPOCH_A: 0, EPOCH_B: 0, EPOCH_C: 3}
    )
    dashboard = _dashboard(test_database_url)
    st = _RecordingStreamlit()
    assert dashboard.render(st).chrome.count == 2
    assert st.captions()[0] == f"{EPOCH_COUNT_LABEL}: 2"

    _spend(test_database_url, EPOCH_B, promotion.SEQUESTERED_EPOCH_BUDGET)
    st = _RecordingStreamlit()
    page = dashboard.render(st)
    assert page.chrome.count == 1
    assert st.captions()[0] == f"{EPOCH_COUNT_LABEL}: 1"


@pytest.mark.parametrize(
    "served_by_epoch, expected",
    [
        ({}, 0),  # never sequestered: zero is the honest answer
        ({EPOCH_A: 3, EPOCH_B: 4}, 0),  # wholly spent: the visible exhaustion
        ({EPOCH_A: 0}, 1),
        ({EPOCH_A: 0, EPOCH_B: 1, EPOCH_C: 2}, 3),
    ],
)
def test_zero_is_rendered_never_refused_or_blanked(
    test_database_url: str, served_by_epoch: dict[str, int], expected: int
) -> None:
    # Feature 297's law, inherited whole and restated at the surface:
    # an empty or wholly spent ledger answers 0 — the figure the
    # caller asked for — and the chrome renders the 0 exactly as it
    # renders a 3, because §13 item 4's "When clean epochs run out,
    # the system stops" is a state the operator must SEE arriving, not
    # one whose arrival turns the strip silent or red-with-refusal.
    _land_ledger(test_database_url, served_by_epoch)
    st = _RecordingStreamlit()
    page = _dashboard(test_database_url).render(st)
    assert page.chrome.count == expected
    assert page.chrome.numeral == str(expected)
    assert st.captions()[0] == f"{EPOCH_COUNT_LABEL}: {expected}"


def test_the_strip_renders_beneath_the_title_on_every_page(
    test_database_url: str,
) -> None:
    # "Permanent chrome" and "at all times", as an ordering law: the
    # strip sits immediately beneath the title — above the fold, above
    # the panel — and it renders on the honest-absence page too, where
    # there is no numeral to read at all.  A count that waited for
    # content would be invisible exactly on the deployment's first
    # page, the one an operator is most likely to be looking at.  The
    # absence page is rendered first, on the store no campaign has
    # closed into yet; the populated one after, over the campaign
    # ``_dashboard`` persists — the same database, both of its pages.
    _land_ledger(test_database_url, {EPOCH_A: 0, EPOCH_B: 3})
    empty_panel = OperatorDashboard(
        FdrDeployEndpoint(scoring.FdrDeployStore(test_database_url)),
        EpochCountGauge(test_database_url),
    )
    st = _RecordingStreamlit()
    page = empty_panel.render(st)
    assert not page.primary
    captions = st.captions()
    assert captions[0] == f"{EPOCH_COUNT_LABEL}: 1"
    assert captions[1].startswith("no campaign has closed")
    assert "line_chart" not in st.names

    st = _RecordingStreamlit()
    page = _dashboard(test_database_url).render(st)
    names = st.names
    assert names.index("title") < names.index("caption")
    assert names.index("caption") < names.index("header")
    assert st.captions()[0] == page.chrome.line


def test_the_count_never_becomes_a_second_metric_tile(
    test_database_url: str,
) -> None:
    # §16 fixes the top-line number, and the render holds that
    # fixation: the primary numeral is the page's one metric tile, and
    # the chrome strip is a caption — furniture, visible always,
    # competing never.  A count rendered as a metric would put a
    # governance figure beside the epistemic top line in the same
    # visual voice.
    _land_ledger(test_database_url, {EPOCH_A: 0})
    st = _RecordingStreamlit()
    page = _dashboard(test_database_url).render(st)
    metric_calls = [call for call in st.calls if call[0] == "metric"]
    assert len(metric_calls) == 1
    assert metric_calls[0][2]["label"] == "FDR_deploy"
    assert metric_calls[0][2]["value"] == page.primary.numeral
    assert "remaining clean epoch" not in metric_calls[0][2]["value"]


def test_the_label_is_the_one_spelling(test_database_url: str) -> None:
    # The strip's words, pinned: the spec's own phrase for the figure
    # ("the remaining clean epoch count ... sit in permanent chrome",
    # feature 297's "remaining clean epochs as a depleting count"),
    # carried once so the strip, the tests and the spec cannot drift
    # apart on the name of the thing depletion is counted in.
    chrome = EpochCountChrome(count=7)
    assert EPOCH_COUNT_LABEL == "remaining clean epochs"
    assert chrome.line == f"{EPOCH_COUNT_LABEL}: 7"
    assert chrome.numeral == "7"


# -- the permanence, held structurally -----------------------------------------------


def test_a_page_is_not_constructible_without_its_chrome(
    test_database_url: str,
) -> None:
    # The structural half of "permanent": the chrome is a required
    # field of the page model, so a chromeless dashboard cannot be
    # represented, let alone rendered — there is no construction to
    # forget to pass, and no default that could quietly drop the
    # strip from a page.
    panel = _dashboard(test_database_url).page().primary
    with pytest.raises(TypeError, match="chrome"):
        DashboardPage(primary=panel)  # type: ignore[call-arg]


def test_the_chrome_seat_judges_the_contract_not_the_class(
    test_database_url: str,
) -> None:
    # The factory's scan imports members under synthetic names, so a
    # composed chrome is structurally this member's without being the
    # same class object a direct import yields — the page duck-checks
    # the display contract, and a carrier that answers all of it *is*
    # an epoch-count chrome for every purpose the render has.
    real = _dashboard(test_database_url).page().chrome

    class _DuckChrome:
        count = real.count
        numeral = real.numeral
        line = real.line

    page = DashboardPage(
        primary=_dashboard(test_database_url).page().primary,
        chrome=_DuckChrome(),  # type: ignore[arg-type]
    )
    assert page.chrome.line == real.line


def test_a_chrome_carrier_that_cannot_answer_the_count_is_refused(
    test_database_url: str,
) -> None:
    # The named, actionable spelling of the permanence law: a carrier
    # that does not answer the chrome's display contract cannot sit in
    # permanent chrome, and the page — the review — refuses it rather
    # than rendering a strip with nothing to say.
    class _LampPanel:
        """342's future content posing as chrome: binary lamps, and no
        count anywhere — the seat refuses it by name."""

        lamps = (True, False, True)

    panel = _dashboard(test_database_url).page().primary
    with pytest.raises(DashboardRenderError) as raised:
        DashboardPage(primary=panel, chrome=_LampPanel())  # type: ignore[arg-type]
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "chrome" in message
    assert "count" in message
    assert "at all times" in message


@pytest.mark.parametrize("not_a_count", [True, -1, 1.5, "7", None])
def test_a_count_that_is_not_a_count_is_refused(not_a_count) -> None:
    # A count of rows is a non-negative int, with bool refused first —
    # True is 1 in Python, and a flag where a count belongs would
    # silently answer one clean epoch nobody sealed.  A figure that is
    # not a count of rows is a number nobody derived, and a strip on
    # every page rendering one would show depletion the ledger does
    # not state.
    with pytest.raises(DashboardRenderError) as raised:
        EpochCountChrome(count=not_a_count)
    assert isinstance(raised.value, OpsError)
    assert "non-negative integer" in str(raised.value)


def test_the_chrome_value_is_frozen_testimony() -> None:
    # The strip's figure is the gauge's testimony at the moment of the
    # read; nothing on it is a knob to adjust.
    import dataclasses

    chrome = EpochCountChrome(count=2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        chrome.count = 3  # type: ignore[misc]


# -- the refusals -------------------------------------------------------------------


def test_a_failing_ledger_read_aborts_the_render_translated(
    test_database_url: str,
) -> None:
    # The member-seam law, held for the second figure: the ledger is
    # the promotion member's, the chrome is this member's, and a
    # caller whose single ``except DashboardRenderError`` guards a
    # render must not be taken down by ``EpochChargeError`` — an error
    # from a module it never imported.  Translated, chained, and
    # never caught into an answer: every fallback count is a figure
    # nobody measured.  The gauge here is a duck carrier, which pins
    # where the translation lives: the seam caller (the page), not the
    # carrier — the route's own stance toward its deferred store.
    class _RefusingGauge:
        def remaining(self) -> int:
            raise promotion.EpochChargeError(
                "EC-294: the ledger refused the read"
            )

    dashboard = OperatorDashboard(
        FdrDeployEndpoint(scoring.FdrDeployStore(test_database_url)),
        _RefusingGauge(),
    )
    with pytest.raises(DashboardRenderError) as raised:
        dashboard.page()
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "chrome" in message
    assert "could not read" in message
    assert "EC-294" in message  # the original's words carried, chained
    assert raised.value.__cause__ is not None
    with pytest.raises(DashboardRenderError):
        dashboard.render(_RecordingStreamlit())


def test_the_real_gauges_failing_read_is_translated_too(
    test_database_url: str,
) -> None:
    # The same law through the member's own gauge, not a duck: a
    # ledger row corrupted past the read path's validators (a served
    # count no count of decisions could be, landed raw — a hand that
    # reached past the charging process) makes the promotion member's
    # own ``epochs()`` refuse, and the page translates that refusal
    # the same way — one vocabulary for every way the count can fail
    # to be had, whichever carrier raised it.
    _land_ledger(test_database_url, {EPOCH_A: 0, EPOCH_B: 1})
    connection = sqlite3.connect(
        Path(test_database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {promotion.EPOCH_LEDGER_TABLE} "
                f"SET {promotion.PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
                f"WHERE {promotion.EPOCH_ID_COLUMN} = ?",
                ("not-a-count", EPOCH_A),
            )
    finally:
        connection.close()

    dashboard = _dashboard(test_database_url)
    with pytest.raises(DashboardRenderError) as raised:
        dashboard.page()
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "chrome" in message
    # The promotion member's own code word, carried in the chained
    # original's words — one code per refusal, and this one is that
    # member's spelling of it, not a guess at an ordinal.
    assert promotion.EPOCH_CHARGE_ERROR_CODE in message
    assert raised.value.__cause__ is not None


def test_the_gauge_carrier_is_duck_checked(test_database_url: str) -> None:
    # The contract is the gauge's remaining() — the promotion member's
    # store itself is not enough (it answers rows, not feature 297's
    # figure), and the refusal names what the chrome needs.
    with pytest.raises(TypeError, match="remaining"):
        OperatorDashboard(
            FdrDeployEndpoint(scoring.FdrDeployStore(test_database_url)),
            promotion.EpochCharges(test_database_url),
        )


def test_the_gauge_refuses_a_url_that_names_nothing() -> None:
    # The chrome renders on every page, so a gauge pointed at nothing
    # is refused at wiring rather than silently rendering a count
    # nobody read — the same stance the charge store takes toward its
    # own URL, restated for the strip that displays the figure.
    with pytest.raises(DashboardRenderError) as raised:
        EpochCountGauge("   ")
    assert "non-empty database URL" in str(raised.value)


# -- the composition ----------------------------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"DATABASE_URL": ""},
        {"DATABASE_URL": "   "},
        {"DATABASE_URL": "sqlite:///tmp/ops-chrome-env-1.db"},
        {"DATABASE_URL": "sqlite:///tmp/ops-chrome-env-2.db"},
    ],
)
def test_the_gauge_rides_the_routes_carried_url(env) -> None:
    # One database, three surfaces: the chrome composes exactly when
    # the route does (the same unset spellings), and the gauge carries
    # the URL the route resolved at composition rather than re-reading
    # the environment — so a later environment cannot move the chrome
    # without moving the store it counts, the law the deferred store
    # states for the top line, held for the count.
    route = FdrDeployEndpoint.from_env(env)
    dashboard = OperatorDashboard.from_env(env)
    if route is None:
        assert dashboard is None
    else:
        assert dashboard is not None
        assert dashboard.gauge.database_url == route.store.database_url


def test_the_composed_chrome_reads_the_one_database(
    test_database_url: str,
) -> None:
    # The composed application's dashboard carries a chrome wired over
    # the same database the route serves §16's figure from — §16's
    # "single Postgres metrics table" allowance, held for the count —
    # and the strip a render draws through the composed route reads
    # the ledger the deployment's charges wrote.
    _land_ledger(test_database_url, {EPOCH_A: 0, EPOCH_B: 0, EPOCH_C: 3})
    scoring.FdrDeployStore(test_database_url).persist(
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        _Pair(0.45, 0.95),
        computed_at="2026-02-01T00:00:00",
    )
    app = create_app(MEMBER_SRC, registry=Registration())
    dashboard = ops_seat.dashboard_component(app)
    assert dashboard is not None
    assert dashboard.gauge.database_url == test_database_url
    st = _RecordingStreamlit()
    page = main(app=app, st=st)
    assert page.chrome.count == 2
    assert st.captions()[0] == f"{EPOCH_COUNT_LABEL}: 2"


def test_building_imports_no_sibling_and_no_ui_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The scan-order law, held for the third deferred name: builders
    # fire after the factory's scan has taken each member's src/ back
    # off sys.path, so constructing the dashboard (and the chrome's
    # gauge inside it) must import neither sibling whose figures the
    # page reads nor the UI library the render defers to.  The first
    # page is where all three are needed.
    import builtins

    real_import = builtins.__import__

    def _no_deferred(name, *args, **kwargs):
        if name in ("promotion", "scoring", "streamlit"):
            raise AssertionError(
                f"the builder must not import {name} — it runs after the "
                "factory's scan has taken the siblings' src/ off "
                "sys.path, and the UI library is the deployment's "
                "ambient dependency (feature 352)"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_deferred)
    dashboard = OperatorDashboard.from_env(
        {"DATABASE_URL": "sqlite:///tmp/ops-chrome-deferred-test.db"}
    )
    assert dashboard is not None
    assert dashboard.gauge.database_url == "sqlite:///tmp/ops-chrome-deferred-test.db"


def test_the_gauge_is_deferred_to_the_first_read(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the deferral: the gauge constructs the
    # promotion member's objects on the first ``remaining()`` and
    # holds them from then on — the move the route's deferred store
    # makes, one figure later.  Pinned by counting constructions of
    # the charge store through the member's own seam.
    constructions = []
    real_epoch_charges = promotion.EpochCharges

    class _CountingCharges(real_epoch_charges):
        def __init__(self, database_url):
            constructions.append(database_url)
            super().__init__(database_url)

    fake = types.ModuleType("promotion")
    fake.EpochCharges = _CountingCharges
    fake.RemainingCleanEpochs = promotion.RemainingCleanEpochs
    fake.EpochChargeError = promotion.EpochChargeError
    monkeypatch.setitem(sys.modules, "promotion", fake)
    gauge = EpochCountGauge(test_database_url)
    assert constructions == []
    assert gauge.remaining() == 0
    assert gauge.remaining() == 0
    assert constructions == [test_database_url]


def test_require_promotion_returns_the_member_that_owns_the_count() -> None:
    # The deferred door, pinned from the side that has the member: the
    # door resolves exactly the module the workspace declares — the
    # one whose gauge owns the count — and nothing else.
    resolved = require_promotion()
    assert resolved is promotion
    assert resolved.RemainingCleanEpochs is promotion.RemainingCleanEpochs


def test_require_promotion_resolves_an_injected_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The other half of the deferral: a deployment environment that
    # carries its own importable promotion member gets exactly the
    # module it installed — the door resolves and returns, nothing
    # more, the same contract ``require_scoring`` pins for the first
    # sibling.
    fake = types.ModuleType("promotion")
    monkeypatch.setitem(sys.modules, "promotion", fake)
    assert require_promotion() is fake


# -- the module scope -----------------------------------------------------------------


def test_the_chrome_module_imports_no_sibling_at_module_scope() -> None:
    # The import-cheap law, pinned as a fact about the module's own
    # namespace: nothing from the promotion member (module, store or
    # gauge) is bound at module scope, so the factory's scan imports
    # this package for the near-nothing it always did.
    from ops import chrome as module

    for name in ("promotion", "EpochCharges", "RemainingCleanEpochs"):
        assert not hasattr(module, name), name


def test_the_streamlit_run_bootstrap_reaches_the_chrome(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `streamlit run packages/ops/src/ops/dashboard.py` lands on the
    # same page the entrypoint builds — chrome and all.  Streamlit is
    # absent here by design, so the run reaches the render's repair
    # refusal only after composing both figures' carriers, which is
    # the proof that the script path wires the chrome too (a bootstrap
    # that lost the gauge would fail one act earlier, on a TypeError
    # nobody repaired).
    import importlib.util
    import runpy

    if importlib.util.find_spec("streamlit") is not None:
        pytest.skip("streamlit importable in this environment")
    with pytest.raises(ModuleNotFoundError) as raised:
        runpy.run_path(
            str(MEMBER_SRC / "ops" / "dashboard.py"),
            run_name="__main__",
        )
    assert "uv pip install streamlit" in str(raised.value)
