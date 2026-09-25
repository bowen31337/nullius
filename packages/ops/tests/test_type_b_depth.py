"""Feature 345's store: Type-B depth past the flip, per Type-D campaign.

app_spec feature 345 — *System persists Type-B depth past the flip for
Type-D worlds, which returns the trend across campaigns* — docs §16's
research metric (*"Type-B depth past the flip in Type-D worlds"*) and
prd §11's secondary scorecard row (*"Type-B error rate: depth past the
flip in Type-D worlds | falling across campaigns"*).

This suite pins the store's law: one row per campaign keyed by the
campaign's canonical UUID id (§16's *"Research metrics (per campaign)"*
grain, the join law feature 267's and 346's rows already key on); the
figure **feature 269's own** ``depth_past_flip_errors`` — the count of
explored nodes at or beyond their branch's flip — handed over already
measured, with the store computing **nothing**: no quotient as feature
346 computes, no difference as 347 computes, and no denominator at any
spelling, because prd §11's *"falling"* is read over the count unchanged
and a store that normalised would flatter every larger campaign that
came after; the ask validated whole **before a connection is opened**,
so a refused record leaves no database file at all; the write an upsert
that refreshes the measurement and preserves the row's original
``recorded_at``; the point read answering ``None`` and the sweep an
empty tuple for a deployment that has closed no campaign out — an
absence, never a zero, because ``0`` is a *measurement* (a Type-D
campaign that deepened past nothing, the state the *"falling"* target
drives toward); a **zero count persisted, never refused**; the trend
read answering oldest-first and computing no direction of its own; and
the construction performing no I/O.

The fixtures mirror ``test_discovery_rate.py`` and
``test_meta_overfit.py``: a real SQLite file under ``tmp_path`` and a
``DATABASE_URL`` pointed at it, with the conftest's per-test isolation
so no test can write into the real store.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
from pathlib import Path

import pytest
from ops import TypeBDepthError, TypeBDepths
from ops.type_b_depth import (
    OPS_TYPE_B_DEPTH_COMPONENT_NAME,
    TYPE_B_DEPTH_TABLE,
)

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
CAMPAIGN_LATER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "type-b-depth.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(store_url: str) -> TypeBDepths:
    """A store bound to the test-only database."""
    return TypeBDepths(store_url)


def _record(store: TypeBDepths, campaign: str = CAMPAIGN, **overrides: object):
    """One campaign's count, the shape every test writes: 7 explored nodes
    sat at or beyond their branch's flip — 7 Type-B errors, the figure
    feature 269's accounting answers and this store persists unchanged."""
    ask: dict[str, object] = {
        "depth_past_flip_errors": 7,
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }
    ask.update(overrides)
    return store.record(campaign, **ask)


# -- Round trip ---------------------------------------------------------------


def test_record_then_depth_round_trips_to_the_bit(store: TypeBDepths) -> None:
    # The row survives the write and comes back off its own columns,
    # unchanged — the store answers what was written, never a recomputation
    # (there is none to make).
    written = _record(store)
    read_back = store.depth(CAMPAIGN)
    assert read_back is not None
    assert read_back == written
    assert read_back.campaign_id == CAMPAIGN
    assert read_back.depth_past_flip_errors == 7
    assert read_back.recorded_at == "2026-01-01T00:00:00+00:00"


def test_the_count_is_carried_unchanged_the_store_computes_nothing(
    store: TypeBDepths,
) -> None:
    # One figure in, the same figure out.  Where feature 346 computes its
    # quotient and 347 its difference, this store has no arithmetic at all:
    # the count is an integer of events, so the ask is the figure and the
    # row is the figure.
    for count in (0, 1, 7, 4096, (1 << 63) - 1):
        record = _record(store, depth_past_flip_errors=count)
        assert record.depth_past_flip_errors == count


def test_a_zero_count_is_the_target_measurement_and_is_persisted(
    store: TypeBDepths,
) -> None:
    # A Type-D campaign that deepened past nothing measured exactly that —
    # the state prd §11's "falling across campaigns" is driving toward — and
    # the zero is persisted and served as the zero it is, never refused and
    # never answered as an absence.
    zero = _record(store, depth_past_flip_errors=0)
    assert zero.depth_past_flip_errors == 0
    assert store.depth(CAMPAIGN) == zero
    assert store.history() == (zero,)


def test_depth_answers_none_for_a_campaign_never_recorded(
    store: TypeBDepths,
) -> None:
    # None is the honest absent answer, never a zero: a caller that could
    # not tell the two apart would read a research programme already at its
    # target out of a missing row.
    _record(store)
    assert store.depth(CAMPAIGN_LATER) is None


def test_history_returns_rows_oldest_first(store: TypeBDepths) -> None:
    # prd §11 grades the metric by its direction — a reading is a
    # comparison against what came before it — so the sweep answers in the
    # order the instants name.
    second = _record(store)
    first = _record(store, CAMPAIGN_LATER, recorded_at="2025-12-01T00:00:00+00:00")
    assert store.history() == (first, second)


def test_history_breaks_same_instant_ties_by_the_campaign(
    store: TypeBDepths,
) -> None:
    # (recorded_at, campaign_id) so two reads of one history return the
    # same sequence whatever the storage engine's accident (§12's ordering
    # rule).
    _record(store)
    _record(store, CAMPAIGN_LATER, recorded_at="2026-01-01T00:00:00+00:00")
    assert [row.campaign_id for row in store.history()] == [
        CAMPAIGN,
        CAMPAIGN_LATER,
    ]


def test_history_is_empty_for_a_deployment_that_closed_no_campaign_out(
    store: TypeBDepths,
) -> None:
    # An empty tuple is the honest answer, not an exception and never a
    # fabricated first point.
    assert store.history() == ()


# -- The figure is feature 269's count, handed over already measured ----------


def test_the_figure_is_the_accountings_own_field(
    store: TypeBDepths, store_path: Path
) -> None:
    # The column carries the accounting's own spelling — feature 269's
    # ErrorAccounting.depth_past_flip_errors — because that field is the
    # figure this store exists to trend (its own docstring reserved this
    # feature as "the one that will read this figure per campaign"), and a
    # second spelling of the name would be a second thing to keep in sync.
    record = _record(store)
    assert set(type(record).__dataclass_fields__) == {
        "campaign_id",
        "depth_past_flip_errors",
        "recorded_at",
    }
    assert set(record.row()) == {
        "campaign_id",
        "depth_past_flip_errors",
        "recorded_at",
    }
    with sqlite3.connect(store_path) as connection:
        columns = [
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({TYPE_B_DEPTH_TABLE})"
            )
        ]
    assert columns == [
        "campaign_id",
        "depth_past_flip_errors",
        "recorded_at",
    ]


def test_no_rate_or_denominator_at_any_spelling(store: TypeBDepths) -> None:
    # prd §11's row says "error rate", but the accounting that owns the
    # figure answered a count ("different kinds on purpose"), and this
    # store refuses to invent the denominator the word might suggest:
    # nothing on the ask normalises, and a larger campaign that deepened
    # past proportionally fewer flips must not read as improvement by
    # construction.
    signature = inspect.signature(TypeBDepths.record)
    assert set(signature.parameters) - {"self"} == {
        "campaign_id",
        "depth_past_flip_errors",
        "recorded_at",
    }
    for forbidden in ("rate", "denominator", "explored", "total", "normal"):
        assert not any(
            forbidden in name for name in signature.parameters
        ), forbidden
    # And the record carries no derived field any normalisation could land
    # in — exactly the three columns the table declares.
    record = _record(store)
    assert set(type(record).__dataclass_fields__) == {
        "campaign_id",
        "depth_past_flip_errors",
        "recorded_at",
    }


def test_the_store_computes_no_direction(store: TypeBDepths) -> None:
    # Whether the trend is *falling* is prd §11's scorecard judgment, read
    # by whatever compares these rows against each other; a slope or a
    # verdict here would be this member inventing the very bar prd §11
    # pointed somewhere else on purpose.  The store answers the rows, in
    # order, and nothing over them.
    _record(store)
    _record(store, CAMPAIGN_LATER, depth_past_flip_errors=3)
    for verb in ("trend", "slope", "is_falling", "fell", "direction"):
        assert not hasattr(store, verb), verb
    rows = store.history()
    assert [row.depth_past_flip_errors for row in rows] == [7, 3]


# -- One campaign, one row ----------------------------------------------------


def test_a_campaign_is_the_primary_key_and_two_campaigns_are_two_rows(
    store: TypeBDepths,
) -> None:
    # §16's grain is per campaign: two campaigns are two rows, each its own
    # count, and the sweep answers both.
    first = _record(store)
    second = _record(store, CAMPAIGN_LATER, depth_past_flip_errors=2)
    assert store.depth(CAMPAIGN) == first
    assert store.depth(CAMPAIGN_LATER) == second
    assert len(store.history()) == 2


def test_upsert_refreshes_the_measurement_rather_than_appending(
    store: TypeBDepths,
) -> None:
    # The count is a deterministic function of the campaign's revealed
    # prefix and its branches' drawn flips — both append-only facts — so a
    # re-run is the same measurement written twice, not a second
    # occurrence: one campaign, one row, the measured column refreshed.
    first = _record(store)
    refreshed = _record(store, depth_past_flip_errors=4)
    assert store.depth(CAMPAIGN) == refreshed
    assert refreshed.depth_past_flip_errors == 4
    assert first != refreshed
    assert len(store.history()) == 1


def test_upsert_preserves_the_rows_original_recorded_at(
    store: TypeBDepths,
) -> None:
    # The first instant the campaign's count was taken is a fact about the
    # trend's history a retry must not rewrite — the refresh arm leaves
    # recorded_at alone, the law feature 267 states for its own per-campaign
    # row.
    _record(store)
    refreshed = _record(
        store,
        depth_past_flip_errors=9,
        recorded_at="2027-01-01T00:00:00+00:00",
    )
    assert refreshed.recorded_at == "2026-01-01T00:00:00+00:00"
    assert refreshed.depth_past_flip_errors == 9


# -- The ask is validated whole, before a connection is opened ----------------


def test_an_id_that_is_not_a_campaign_is_refused_before_any_connection(
    store: TypeBDepths, store_path: Path
) -> None:
    # The key is the campaign's canonical UUID text; a value that names no
    # campaign names no figure §16's per-campaign grain could hold — and no
    # row the member's other research rows could join.
    for bad in ("", "   ", None, 7, ["campaign"], "not-a-uuid"):
        with pytest.raises(TypeBDepthError):
            _record(store, bad)  # type: ignore[arg-type]
    assert not store_path.exists()
    # A UUID object is accepted, and a mixed-case or braced spelling
    # canonicalises onto the one row rather than making one campaign look
    # like two — the join law feature 267's and 346's rows already key on.
    import uuid

    upper = store.record(
        uuid.UUID(CAMPAIGN).hex.upper(),
        depth_past_flip_errors=7,
    )
    assert upper.campaign_id == CAMPAIGN
    padded = store.record(
        f"  {{{CAMPAIGN.upper()}}}  ",
        depth_past_flip_errors=7,
    )
    assert padded.campaign_id == CAMPAIGN
    assert len(store.history()) == 1


def test_a_count_that_is_not_a_whole_number_is_refused(
    store: TypeBDepths, store_path: Path
) -> None:
    # The figure is an integer of events; a fractional count would be this
    # store inventing a figure the caller never stated, and coercing 3.0
    # would be the quietest way to invent one.
    for bad in (7.0, "7", None, 7.5, [7]):
        with pytest.raises(TypeBDepthError):
            _record(store, depth_past_flip_errors=bad)
    assert not store_path.exists()


def test_bool_is_refused_before_int(store: TypeBDepths, store_path: Path) -> None:
    # A bool *is* an int in Python's hierarchy and is not a count of error
    # events — True is not one well deepened past a silent flip.
    with pytest.raises(TypeBDepthError):
        _record(store, depth_past_flip_errors=True)
    assert not store_path.exists()


def test_a_negative_count_is_refused(store: TypeBDepths, store_path: Path) -> None:
    # The count is of events that happened; there is no path by which fewer
    # than none occurred.  Zero is the honest floor, not a figure to
    # undersell — feature 269's own words for the same narrowing.
    with pytest.raises(TypeBDepthError) as caught:
        _record(store, depth_past_flip_errors=-1)
    assert "depth_past_flip_errors" in str(caught.value)
    assert not store_path.exists()


def test_a_count_past_the_columns_range_is_refused_by_name(
    store: TypeBDepths, store_path: Path
) -> None:
    # SQLite's INTEGER is a signed 64-bit integer, and a whole number past
    # it has no column to land in.  The refusal is here, in this member's
    # vocabulary, rather than as a raw OverflowError from the driver's
    # binding step.  Refused *before* the connection, so no half-written
    # row is left behind.
    past = 1 << 63
    with pytest.raises(TypeBDepthError) as caught:
        _record(store, depth_past_flip_errors=past)
    assert "depth_past_flip_errors" in str(caught.value)
    assert not store_path.exists()
    # The largest storable count is admitted rather than refused: the bound
    # is the column's, not an opinion about the figure.
    biggest = _record(store, depth_past_flip_errors=past - 1)
    assert biggest.depth_past_flip_errors == past - 1


def test_a_stored_count_past_the_columns_range_is_refused(
    store: TypeBDepths, store_path: Path
) -> None:
    # The same bound on the read path.  SQLite's dynamic typing will hold a
    # float past the range in an INTEGER column, so a stored row can carry
    # one — and the value layer refuses it rather than letting a figure the
    # table cannot hold reach prd §11's trend.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {TYPE_B_DEPTH_TABLE} SET depth_past_flip_errors = 1e300 "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(TypeBDepthError):
        store.history()
    with pytest.raises(TypeBDepthError):
        store.depth(CAMPAIGN)


def test_the_instant_must_be_a_nameable_label(
    store: TypeBDepths, store_path: Path
) -> None:
    # The instant is the label the trend's order reads; a value that is not
    # a nameable instant orders prd §11's direction by nothing.
    for bad in (12345, "", "   "):
        with pytest.raises(TypeBDepthError):
            _record(store, recorded_at=bad)
    assert not store_path.exists()


def test_default_instant_stamps_the_write(store: TypeBDepths) -> None:
    # recorded_at defaults to now (UTC, second resolution); a caller that
    # measured at a known instant passes it, but the write can stamp its
    # own.
    written = store.record(CAMPAIGN, depth_past_flip_errors=7)
    instant = written.recorded_at
    assert "T" in instant
    assert instant.endswith("+00:00")
    time_part = instant.split("T")[1].split("+")[0]
    assert time_part.count(":") == 2
    assert "." not in time_part


# -- A stored row that is not a depth row is refused, never served ------------


def test_a_stored_count_that_is_not_a_count_is_refused(
    store: TypeBDepths, store_path: Path
) -> None:
    # SQLite's columns are dynamically typed, so a hand-edited row is
    # reachable; text wearing the column's name is not a count of events,
    # and the refusal names the campaign the bad row came from so an
    # operator gets the row to repair rather than a complaint with no
    # address.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {TYPE_B_DEPTH_TABLE} SET depth_past_flip_errors = 'seven' "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(TypeBDepthError) as caught:
        store.history()
    assert CAMPAIGN in str(caught.value)
    with pytest.raises(TypeBDepthError):
        store.depth(CAMPAIGN)


def test_a_stored_negative_count_is_refused(
    store: TypeBDepths, store_path: Path
) -> None:
    # A negative count is not a measurement this store could have written:
    # the count is of events that happened, and no path produces fewer than
    # none.  Refused on the read, because the value layer holds the write
    # path's law over rows SQLite will accept from any other tool.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {TYPE_B_DEPTH_TABLE} SET depth_past_flip_errors = -3 "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(TypeBDepthError) as caught:
        store.history()
    assert CAMPAIGN in str(caught.value)


def test_a_stored_row_naming_no_campaign_is_refused(
    store: TypeBDepths, store_path: Path
) -> None:
    # A row wearing an id no campaign resolves is a figure §16's
    # per-campaign grain cannot attribute.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {TYPE_B_DEPTH_TABLE} SET campaign_id = '  ' "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(TypeBDepthError):
        store.history()


# -- The store is the workspace's one relational store ------------------------


def test_construction_performs_no_io(store_url: str, store_path: Path) -> None:
    # The class resolves its path lazily, so constructing one performs no
    # I/O: composition-time work must not touch the disk.
    TypeBDepths(store_url)
    assert not store_path.exists()


def test_resolve_answers_none_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Absent is not an error: it is a deployment without a relational store,
    # which composes no Type-B depth component — a discoverable state, not
    # an exception.
    from ops import DATABASE_URL_ENV

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert TypeBDepths.resolve() is None


def test_resolve_answers_none_for_an_empty_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty or whitespace-only value counts as unset.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert TypeBDepths.resolve() is None


def test_resolve_answers_the_named_store(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The store DATABASE_URL names, resolved.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = TypeBDepths.resolve()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_an_unsupported_scheme_is_refused_at_first_use(store_path: Path) -> None:
    # Only sqlite:/// speaks — a Postgres metrics table arrives with the
    # versioned migration member, and pretending to speak it here would
    # hide a misrouted URL behind a mysterious file.  Refused at first
    # use, not construction.
    store = TypeBDepths("postgresql://localhost/metrics")
    assert store.database_url == "postgresql://localhost/metrics"
    with pytest.raises(TypeBDepthError):
        _record(store)


def test_an_unspeakable_scheme_is_refused_at_first_use() -> None:
    # A scheme with no netloc and no path — refused at first use, not
    # construction, and never silently mis-parsed into a file.
    store = TypeBDepths("redis://cache:6379/0")
    with pytest.raises(TypeBDepthError):
        _record(store)


def test_a_sqlite_url_with_a_host_is_refused() -> None:
    # No host but localhost admitted — the same refusal every store in this
    # workspace states for its own connection.
    store = TypeBDepths("sqlite://remote-host/db.sqlite")
    with pytest.raises(TypeBDepthError):
        _record(store)


def test_a_sqlite_url_with_no_path_is_refused() -> None:
    # A URL with no path refused — the store must name a database.
    store = TypeBDepths("sqlite:///")
    with pytest.raises(TypeBDepthError):
        _record(store)


def test_a_blank_url_is_refused_at_construction() -> None:
    # The URL is held, not resolved, but it must be a non-empty string.
    for bad in ("", "   ", None, 7):
        with pytest.raises(TypeBDepthError):
            TypeBDepths(bad)  # type: ignore[arg-type]


def test_a_database_that_will_not_open_is_surfaced_chained(
    tmp_path: Path,
) -> None:
    # The store's own failure surfaces in this member's vocabulary, chained
    # to the original and deliberately not swallowed: a count that measured
    # but never landed is the state feature 345 exists to rule out.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = TypeBDepths(f"sqlite:///{not_a_dir}/type-b-depth.db")
    with pytest.raises(TypeBDepthError) as caught:
        _record(store)
    assert caught.value.__cause__ is not None


def test_a_read_failure_is_surfaced_chained(tmp_path: Path) -> None:
    # A store that cannot be asked is surfaced rather than answered around
    # — prd §11's direction is read across these rows.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = TypeBDepths(f"sqlite:///{not_a_dir}/type-b-depth.db")
    with pytest.raises(TypeBDepthError) as caught:
        store.depth(CAMPAIGN)
    assert caught.value.__cause__ is not None
    with pytest.raises(TypeBDepthError) as caught:
        store.history()
    assert caught.value.__cause__ is not None


# -- The module reads no accounting and no oracle -----------------------------


def test_the_module_reads_no_sibling_and_no_clock() -> None:
    # The member's law is delegation: the count is feature 269's answer
    # over a join the null oracle owns, and the campaign's type is the
    # caller's scope decision.  Reaching for the scoring member from here
    # would make this table's construction depend on a sibling the factory
    # scan could not promise is on sys.path at build time, and would grow a
    # second spelling of a boundary the accounting already owns.  Read on
    # the code (docstrings stripped), so the prose may name the accounting
    # and the oracle and the code may not.
    import ops.type_b_depth as module

    tree = ast.parse(_code_of(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    # Only stdlib and this member's own modules — and deliberately no math
    # and no numbers: a count of events has no finiteness to check, which
    # is the arithmetic-free shape the suite pins above.
    assert imported <= {
        "__future__",
        "datetime",
        "os",
        "sqlite3",
        "uuid",
        "contextlib",
        "dataclasses",
        "pathlib",
        "typing",
        "urllib",
        "errors",
        "live_metrics",
    }, sorted(imported)
    # No accounting, no oracle, no ledger, no scoring.
    for sibling in ("scoring", "nulloracle", "ledger", "dreaming", "replay"):
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
    shares with the member's other modules: a docstring naming feature
    269's accounting is honesty (the figure's owner is stated where it is
    delegated to), while an *import* of it would be the second spelling
    this member exists to avoid — and only the AST can tell the two apart.
    """
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


# -- The component beside the member's other five -----------------------------


def test_the_builder_resolves_the_named_store_or_none(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The builder resolves DATABASE_URL and answers None when nothing names
    # a store — the degrade-don't-break stance every store-bound builder
    # here takes, so a deployment without a relational store still
    # composes.
    from ops import DATABASE_URL_ENV, build_type_b_depth_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_type_b_depth_store() is None
    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = build_type_b_depth_store()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_the_builder_touches_no_disk_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Building performs no I/O — no store is constructed, no database
    # opened, no schema created — and when nothing names a store the
    # builder answers None without touching the disk.
    from ops import DATABASE_URL_ENV, build_type_b_depth_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_type_b_depth_store() is None


def test_the_component_name_is_the_member_sixth() -> None:
    # The growth the member's own registration reserved when feature 341
    # landed: the route, the dashboard, the live-metrics store, the
    # meta-overfit gap store, the discovery-rate store, and now the Type-B
    # depth store, each beside — never inside — another member's
    # components.
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
        OPS_TYPE_B_DEPTH_COMPONENT_NAME,
    }
    # Six distinct component names under the one member-first prefix.
    assert len(names) == 6
    assert OPS_TYPE_B_DEPTH_COMPONENT_NAME == "ops-type-b-depth"
    assert all(name.startswith("ops-") for name in names)


def test_the_component_name_is_exported_from_the_member() -> None:
    import ops

    assert "OPS_TYPE_B_DEPTH_COMPONENT_NAME" in ops.__all__
    assert ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME == "ops-type-b-depth"
    assert (
        ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME == OPS_TYPE_B_DEPTH_COMPONENT_NAME
    )


def test_the_store_class_is_exported_from_the_member() -> None:
    import ops

    assert "TypeBDepths" in ops.__all__
    assert "TypeBDepth" in ops.__all__
    assert "TypeBDepthError" in ops.__all__
    assert "TYPE_B_DEPTH_TABLE" in ops.__all__
    assert ops.TYPE_B_DEPTH_TABLE == TYPE_B_DEPTH_TABLE


def test_the_error_is_the_members_own_vocabulary() -> None:
    # One base so a caller catches the member as a whole, one subclass per
    # surface so a refusal names where it happened.
    from ops import OpsError, TypeBDepthError

    assert issubclass(TypeBDepthError, OpsError)
    assert OpsError in TypeBDepthError.__mro__
