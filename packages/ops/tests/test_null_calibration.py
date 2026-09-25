"""Feature 344's store: the planted-null calibration pair, per campaign.

app_spec feature 344 — *System persists sensitivity and specificity on
planted nulls per campaign into the metrics store* — docs §16's research
metric (*"sensitivity/specificity on planted nulls"*) and prd §11's
secondary scorecard row (*"Sensitivity / specificity on planted nulls
(base-rate independent) | tracked, not targeted"*).

This suite pins the store's law: one row per campaign keyed by the
campaign's canonical UUID id (§16's *"Research metrics (per campaign)"*
grain, the join law feature 267's, 346's and 345's rows already key on);
the two figures **feature 266's own** — ``TP/(TP+FN)`` and ``TN/(TN+FP)``
over the campaign's planted population, handed over already measured —
with the store computing **neither** and adding nothing over them: no base
rate, no ``FDR_deploy``, no blend or average over the pair and no interval
around either, so the row is the campaign's key, the two figures and the
instant; the ask validated whole **before a connection is opened**, so a
refused record leaves no database file at all; the write an upsert that
refreshes the measurement and preserves the row's original ``recorded_at``;
the point read answering ``None`` and the sweep an empty tuple for a
deployment that has closed no campaign out — an absence, never a pair of
zeros, because ``0.0`` sensitivity is a *measurement* (a campaign that
found none of its reals) and prd §11 tracks these figures without a target;
both endpoints persisted, never refused; the trend read answering
oldest-first and computing no direction of its own; and the construction
performing no I/O.

The fixtures mirror ``test_type_b_depth.py``: a real SQLite file under
``tmp_path`` and a ``DATABASE_URL`` pointed at it, with the conftest's
per-test isolation so no test can write into the real store.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
import uuid
from pathlib import Path

import pytest
from ops import NullCalibrationError, NullCalibrations
from ops.null_calibration import (
    NULL_CALIBRATION_TABLE,
    OPS_NULL_CALIBRATION_COMPONENT_NAME,
)

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
CAMPAIGN_LATER = "22222222-2222-2222-2222-222222222222"

#: Feature 266's pair for one campaign, the shape every test writes: the
#: policy found 8 of its 10 planted reals and left 9 of its 10 planted nulls
#: alone.
SENSITIVITY = 0.8
SPECIFICITY = 0.9


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "null-calibration.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(store_url: str) -> NullCalibrations:
    """A store bound to the test-only database."""
    return NullCalibrations(store_url)


def _record(store: NullCalibrations, campaign: str = CAMPAIGN, **overrides: object):
    """One campaign's calibration pair, the shape every test writes."""
    ask: dict[str, object] = {
        "sensitivity": SENSITIVITY,
        "specificity": SPECIFICITY,
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }
    ask.update(overrides)
    return store.record(campaign, **ask)


# -- Round trip ---------------------------------------------------------------


def test_record_then_calibration_round_trips_to_the_bit(
    store: NullCalibrations,
) -> None:
    # The row survives the write and comes back off its own columns,
    # unchanged — the store answers what was written, never a recomputation
    # (the two figures have none to make: they are feature 266's).
    written = _record(store)
    read_back = store.calibration(CAMPAIGN)
    assert read_back is not None
    assert read_back == written
    assert read_back.campaign_id == CAMPAIGN
    assert read_back.sensitivity == SENSITIVITY
    assert read_back.specificity == SPECIFICITY
    assert read_back.recorded_at == "2026-01-01T00:00:00+00:00"


def test_the_pair_is_carried_unchanged_the_store_computes_neither_figure(
    store: NullCalibrations,
) -> None:
    # One pair in, the same pair out.  Where feature 346 computes its
    # quotient and 347 its difference, this store has no arithmetic over the
    # figures at all: they are feature 266's fractions of the two planted
    # classes, so the ask is the pair and the row is the pair.
    for sensitivity, specificity in (
        (0.0, 0.0),
        (0.0, 1.0),
        (0.25, 0.5),
        (0.8, 0.9),
        (1.0, 0.0),
        (1.0, 1.0),
    ):
        record = _record(store, sensitivity=sensitivity, specificity=specificity)
        assert record.sensitivity == sensitivity
        assert record.specificity == specificity


def test_the_figures_are_feature_266s_own_field_names(
    store: NullCalibrations, store_path: Path
) -> None:
    # The columns carry the calibration value's own spellings — feature 266's
    # CalibrationFigures.sensitivity and .specificity — because that pair is
    # the figure this store exists to land (266's own docstring reserved this
    # feature as "the ops member's (feature 344's), which reads this pair"),
    # and a second spelling of either name would be a second thing to keep in
    # sync.
    record = _record(store)
    assert set(type(record).__dataclass_fields__) == {
        "campaign_id",
        "sensitivity",
        "specificity",
        "recorded_at",
    }
    assert set(record.row()) == {
        "campaign_id",
        "sensitivity",
        "specificity",
        "recorded_at",
    }
    with sqlite3.connect(store_path) as connection:
        columns = [
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({NULL_CALIBRATION_TABLE})"
            )
        ]
    assert columns == [
        "campaign_id",
        "sensitivity",
        "specificity",
        "recorded_at",
    ]


def test_the_endpoints_are_measurements_and_are_persisted(
    store: NullCalibrations,
) -> None:
    # A sensitivity of 0.0 is a campaign that found none of its reals and a
    # specificity of 1.0 one that wrongly declared nothing — both are the
    # honest corners feature 266 answers deliberately.  prd §11 tracks the
    # pair without a target, so neither is refused and neither is answered as
    # an absence.
    corner = _record(store, sensitivity=0.0, specificity=1.0)
    assert corner.sensitivity == 0.0
    assert corner.specificity == 1.0
    assert store.calibration(CAMPAIGN) == corner
    assert store.history() == (corner,)


def test_calibration_answers_none_for_a_campaign_never_recorded(
    store: NullCalibrations,
) -> None:
    # None is the honest absent answer, never a pair of zeros: a caller that
    # could not tell the two apart would read a research programme that found
    # nothing out of a missing row.
    _record(store)
    assert store.calibration(CAMPAIGN_LATER) is None


def test_history_returns_rows_oldest_first(store: NullCalibrations) -> None:
    # prd §11 tracks the figures across campaigns — a reading is a comparison
    # against what came before it — so the sweep answers in the order the
    # instants name.
    second = _record(store)
    first = _record(store, CAMPAIGN_LATER, recorded_at="2025-12-01T00:00:00+00:00")
    assert store.history() == (first, second)


def test_history_breaks_same_instant_ties_by_the_campaign(
    store: NullCalibrations,
) -> None:
    # (recorded_at, campaign_id) so two reads of one history return the same
    # sequence whatever the storage engine's accident (§12's ordering rule).
    _record(store)
    _record(store, CAMPAIGN_LATER, recorded_at="2026-01-01T00:00:00+00:00")
    assert [row.campaign_id for row in store.history()] == [
        CAMPAIGN,
        CAMPAIGN_LATER,
    ]


def test_history_is_empty_for_a_deployment_that_closed_no_campaign_out(
    store: NullCalibrations,
) -> None:
    # An empty tuple is the honest answer, not an exception and never a
    # fabricated first point.
    assert store.history() == ()


# -- The store derives no compact statistic -----------------------------------


def test_there_is_no_base_rate_and_no_fdr_deploy_at_any_spelling(
    store: NullCalibrations,
) -> None:
    # prd §4.1.3's reweighting into FDR_deploy is feature 267's arithmetic at
    # π₀ = 0.9, and the projection lives with its own store.  A base rate here
    # would let a caller pick the population the pair is judged against, and
    # an FDR column would be the second spelling of a derivation another
    # member owns.  The ask carries the two figures and the label, and nothing
    # else.
    signature = inspect.signature(NullCalibrations.record)
    assert set(signature.parameters) - {"self"} == {
        "campaign_id",
        "sensitivity",
        "specificity",
        "recorded_at",
    }
    for forbidden in ("base_rate", "pi0", "fdr", "deploy", "rate", "threshold"):
        assert not any(forbidden in name for name in signature.parameters), forbidden
    # No interval parameter either: a caller-stated band would be an
    # unreconciled claim persisted on trust, and no document fixes one for a
    # class-conditional figure — so the store derives none and accepts none.
    # Matched as whole names, since "ci" is a substring of "specificity".
    for forbidden in ("ci", "interval", "band", "bound", "confidence"):
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}_")
            for name in signature.parameters
        ), forbidden
    written = _record(store)
    assert not any(
        forbidden in field
        for field in type(written).__dataclass_fields__
        for forbidden in ("fdr", "base_rate", "pi0", "rate", "ci_")
    )


def test_the_store_computes_no_direction_and_no_statistic_over_the_pairs(
    store: NullCalibrations,
) -> None:
    # Whether the figures are moving is prd §11's *"tracked"* judgment, read by
    # whatever compares these rows against each other; a slope, a mean, a
    # verdict or a summary pair here would be this member inventing the very
    # reading the prd pointed at *"tracked"* on purpose — and a summary of two
    # base-rate-independent figures is exactly where a base rate would creep
    # back in.
    _record(store)
    _record(store, CAMPAIGN_LATER, sensitivity=0.4, specificity=0.6)
    for verb in (
        "trend",
        "slope",
        "is_improving",
        "direction",
        "mean",
        "average",
        "summary",
        "blend",
    ):
        assert not hasattr(store, verb), verb
    rows = store.history()
    assert [(row.sensitivity, row.specificity) for row in rows] == [
        (SENSITIVITY, SPECIFICITY),
        (0.4, 0.6),
    ]


# -- One campaign, one row ----------------------------------------------------


def test_a_campaign_is_the_primary_key_and_two_campaigns_are_two_rows(
    store: NullCalibrations,
) -> None:
    # §16's grain is per campaign: two campaigns are two rows, each its own
    # pair, and the sweep answers both.
    first = _record(store)
    second = _record(store, CAMPAIGN_LATER, sensitivity=0.2, specificity=0.3)
    assert store.calibration(CAMPAIGN) == first
    assert store.calibration(CAMPAIGN_LATER) == second
    assert len(store.history()) == 2


def test_upsert_refreshes_the_measurement_rather_than_appending(
    store: NullCalibrations,
) -> None:
    # The pair is a deterministic function of the campaign's planted
    # population and its committed picks — both append-only facts — so a re-run
    # is the same measurement written twice, not a second occurrence: one
    # campaign, one row, the measured columns refreshed.
    first = _record(store)
    refreshed = _record(store, sensitivity=0.5, specificity=0.5)
    assert store.calibration(CAMPAIGN) == refreshed
    assert refreshed.sensitivity == 0.5
    assert first != refreshed
    assert len(store.history()) == 1


def test_upsert_preserves_the_rows_original_recorded_at(
    store: NullCalibrations,
) -> None:
    # The first instant the campaign's pair was taken is a fact about the
    # trend's history a retry must not rewrite — the refresh arm leaves
    # recorded_at alone, the law feature 267 states for its own per-campaign
    # row.
    _record(store)
    refreshed = _record(
        store,
        sensitivity=0.1,
        specificity=0.2,
        recorded_at="2027-01-01T00:00:00+00:00",
    )
    assert refreshed.recorded_at == "2026-01-01T00:00:00+00:00"
    assert refreshed.sensitivity == 0.1


def test_the_two_figures_land_in_their_own_columns_never_widened_into_one(
    store: NullCalibrations, store_path: Path
) -> None:
    # The pair is two figures, not one: recording a symmetric pair leaves two
    # distinct values in two distinct columns, and neither is written over the
    # other.
    _record(store, sensitivity=0.25, specificity=0.75)
    with sqlite3.connect(store_path) as connection:
        row = connection.execute(
            f"SELECT sensitivity, specificity FROM {NULL_CALIBRATION_TABLE}"
        ).fetchone()
    assert row == (0.25, 0.75)


# -- The ask is validated whole, before a connection is opened ----------------


def test_an_id_that_is_not_a_campaign_is_refused_before_any_connection(
    store: NullCalibrations, store_path: Path
) -> None:
    # The key is the campaign's canonical UUID text; a value that names no
    # campaign names no figure §16's per-campaign grain could hold — and no row
    # the member's other research rows could join.
    for bad in ("", "   ", None, 7, ["campaign"], "not-a-uuid"):
        with pytest.raises(NullCalibrationError):
            _record(store, bad)  # type: ignore[arg-type]
    assert not store_path.exists()
    # A UUID object is accepted, and a mixed-case or braced spelling
    # canonicalises onto the one row rather than making one campaign look like
    # two — the join law feature 267's, 346's and 345's rows already key on.
    upper = store.record(
        uuid.UUID(CAMPAIGN).hex.upper(),
        sensitivity=SENSITIVITY,
        specificity=SPECIFICITY,
    )
    assert upper.campaign_id == CAMPAIGN
    padded = store.record(
        f"  {{{CAMPAIGN.upper()}}}  ",
        sensitivity=SENSITIVITY,
        specificity=SPECIFICITY,
    )
    assert padded.campaign_id == CAMPAIGN
    assert len(store.history()) == 1


def test_a_figure_that_is_not_a_real_is_refused(
    store: NullCalibrations, store_path: Path
) -> None:
    # The pair is feature 266's two fractions; a value that is not a real is
    # not a fraction of a planted class.
    for bad in ("0.8", None, [0.8], {"sensitivity": 0.8}):
        with pytest.raises(NullCalibrationError):
            _record(store, sensitivity=bad)
        with pytest.raises(NullCalibrationError):
            _record(store, specificity=bad)
    assert not store_path.exists()


def test_bool_is_refused_before_real(store: NullCalibrations, store_path: Path) -> None:
    # A bool *is* an int in Python's hierarchy and is not a fraction of a
    # planted class — True is not a sensitivity.
    for field in ("sensitivity", "specificity"):
        with pytest.raises(NullCalibrationError):
            _record(store, **{field: True})
    assert not store_path.exists()


def test_a_figure_outside_the_unit_interval_is_refused_rather_than_clamped(
    store: NullCalibrations, store_path: Path
) -> None:
    # The likeliest thing wearing either name is a *count* of found reals or
    # of clean nulls handed where the fraction belongs — clamped to an
    # endpoint it would persist a calibration nobody measured.
    for bad in (-0.1, 1.1, 8, 10, -3):
        with pytest.raises(NullCalibrationError) as caught:
            _record(store, sensitivity=bad)
        assert "sensitivity" in str(caught.value)
    assert not store_path.exists()


def test_a_non_finite_figure_is_refused(
    store: NullCalibrations, store_path: Path
) -> None:
    # A NaN would make one half of the pair a NaN the reweighting silently
    # drops, and an infinity is not a fraction of a class.
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(NullCalibrationError):
            _record(store, sensitivity=bad)
        with pytest.raises(NullCalibrationError):
            _record(store, specificity=bad)
    assert not store_path.exists()


def test_the_instant_must_be_a_nameable_label(
    store: NullCalibrations, store_path: Path
) -> None:
    # The instant is the label the trend's order reads; a value that is not a
    # nameable instant orders prd §11's track by nothing.
    for bad in (12345, "", "   "):
        with pytest.raises(NullCalibrationError):
            _record(store, recorded_at=bad)
    assert not store_path.exists()


def test_default_instant_stamps_the_write(store: NullCalibrations) -> None:
    # recorded_at defaults to now (UTC, second resolution); a caller that
    # measured at a known instant passes it, but the write can stamp its own.
    written = store.record(CAMPAIGN, sensitivity=SENSITIVITY, specificity=SPECIFICITY)
    instant = written.recorded_at
    assert "T" in instant
    assert instant.endswith("+00:00")
    time_part = instant.split("T")[1].split("+")[0]
    assert time_part.count(":") == 2
    assert "." not in time_part


def test_a_malformed_ask_leaves_no_database_file_at_all(
    store: NullCalibrations, store_path: Path
) -> None:
    # The ordering law every write in this workspace states: the ask is
    # validated whole before a connection is opened, so a refused record leaves
    # no half-written row and no database file.
    with pytest.raises(NullCalibrationError):
        _record(store, sensitivity=2.0)
    assert not store_path.exists()
    # The first well-formed ask is what brings the store into being.
    _record(store)
    assert store_path.exists()


# -- A stored row that is not a calibration row is refused, never served ------


def test_a_stored_figure_that_is_not_a_fraction_is_refused(
    store: NullCalibrations, store_path: Path
) -> None:
    # Text wearing the column's name is not a fraction of a planted class.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {NULL_CALIBRATION_TABLE} SET specificity = 'high' "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(NullCalibrationError) as caught:
        store.history()
    assert CAMPAIGN in str(caught.value)
    with pytest.raises(NullCalibrationError):
        store.calibration(CAMPAIGN)


def test_a_stored_figure_out_of_bound_is_refused(
    store: NullCalibrations, store_path: Path
) -> None:
    # A negative sensitivity is not a measurement this store could have
    # written: the figure is a fraction of a class and no path produces fewer
    # than none.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {NULL_CALIBRATION_TABLE} SET sensitivity = -0.5 "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(NullCalibrationError) as caught:
        store.history()
    assert CAMPAIGN in str(caught.value)


def test_a_stored_row_naming_no_campaign_is_refused(
    store: NullCalibrations, store_path: Path
) -> None:
    # A row wearing an id no campaign resolves is a figure §16's per-campaign
    # grain cannot attribute.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {NULL_CALIBRATION_TABLE} SET campaign_id = '  ' "
            f"WHERE campaign_id = ?",
            (CAMPAIGN,),
        )
    with pytest.raises(NullCalibrationError):
        store.history()


# -- The store is the workspace's one relational store ------------------------


def test_construction_performs_no_io(store_url: str, store_path: Path) -> None:
    # The class resolves its path lazily, so constructing one performs no I/O:
    # composition-time work must not touch the disk.
    NullCalibrations(store_url)
    assert not store_path.exists()


def test_resolve_answers_none_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Absent is not an error: it is a deployment without a relational store,
    # which composes no calibration component — a discoverable state, not an
    # exception.
    from ops import DATABASE_URL_ENV

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert NullCalibrations.resolve() is None


def test_resolve_answers_none_for_an_empty_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty or whitespace-only value counts as unset.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert NullCalibrations.resolve() is None


def test_resolve_answers_the_named_store(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The store DATABASE_URL names, resolved.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = NullCalibrations.resolve()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_an_unsupported_scheme_is_refused_at_first_use(store_path: Path) -> None:
    # Only sqlite:/// speaks — a Postgres metrics table arrives with the
    # versioned migration member, and pretending to speak it here would hide a
    # misrouted URL behind a mysterious file.  Refused at first use, not
    # construction.
    store = NullCalibrations("postgresql://localhost/metrics")
    assert store.database_url == "postgresql://localhost/metrics"
    with pytest.raises(NullCalibrationError):
        _record(store)


def test_an_unspeakable_scheme_is_refused_at_first_use() -> None:
    # A scheme with no netloc and no path — refused at first use, not
    # construction, and never silently mis-parsed into a file.
    store = NullCalibrations("redis://cache:6379/0")
    with pytest.raises(NullCalibrationError):
        _record(store)


def test_a_sqlite_url_with_a_host_is_refused() -> None:
    # No host but localhost admitted — the same refusal every store in this
    # workspace states for its own connection.
    store = NullCalibrations("sqlite://remote-host/db.sqlite")
    with pytest.raises(NullCalibrationError):
        _record(store)


def test_a_sqlite_url_with_no_path_is_refused() -> None:
    # A URL with no path refused — the store must name a database.
    store = NullCalibrations("sqlite:///")
    with pytest.raises(NullCalibrationError):
        _record(store)


def test_a_blank_url_is_refused_at_construction() -> None:
    # The URL is held, not resolved, but it must be a non-empty string.
    for bad in ("", "   ", None, 7):
        with pytest.raises(NullCalibrationError):
            NullCalibrations(bad)  # type: ignore[arg-type]


def test_a_database_that_will_not_open_is_surfaced_chained(tmp_path: Path) -> None:
    # The store's own failure surfaces in this member's vocabulary, chained to
    # the original and deliberately not swallowed: a pair that measured but
    # never landed is the state feature 344 exists to rule out.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = NullCalibrations(f"sqlite:///{not_a_dir}/null-calibration.db")
    with pytest.raises(NullCalibrationError) as caught:
        _record(store)
    assert caught.value.__cause__ is not None


def test_a_read_failure_is_surfaced_chained(tmp_path: Path) -> None:
    # A store that cannot be asked is surfaced rather than answered around —
    # prd §11 tracks the figures across these rows.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = NullCalibrations(f"sqlite:///{not_a_dir}/null-calibration.db")
    with pytest.raises(NullCalibrationError) as caught:
        store.calibration(CAMPAIGN)
    assert caught.value.__cause__ is not None
    with pytest.raises(NullCalibrationError) as caught:
        store.history()
    assert caught.value.__cause__ is not None


# -- The module reads no scoring member and no oracle -------------------------


def test_the_module_reads_no_sibling_member() -> None:
    # The member's law is delegation: the pair is feature 266's answer over the
    # campaign's planted population and its committed picks, and the labels the
    # fractions condition on never leave the scorer's process (prd §4.2 grants
    # the sidecar key to exactly one component).  Reaching for the scoring
    # member from here would make this table's construction depend on a sibling
    # the factory scan could not promise is on sys.path at build time, and
    # would grow a second spelling of a boundary the calibration verb already
    # owns.  Read on the code (docstrings stripped), so the prose may name the
    # scoring member and the code may not.
    import ops.null_calibration as module

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
        "pathlib",
        "typing",
        "urllib",
        "errors",
        "live_metrics",
    }, sorted(imported)
    # No scoring, no oracle, no ledger, no dreaming, no replay.
    for sibling in ("scoring", "nulloracle", "ledger", "dreaming", "replay"):
        assert sibling not in imported
    # And no clock of its own past the row's label: no perf_counter and no
    # time module anywhere in the code.
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "perf_counter" not in names
    assert "time" not in {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def _code_of(module: object) -> str:
    """The module's source with every docstring stripped.

    The "what the code does, not what the prose says" reading this suite
    shares with the member's other modules: a docstring naming feature 266's
    calibration verb is honesty (the figure's owner is stated where it is
    delegated to), while an *import* of it would be the second spelling this
    member exists to avoid — and only the AST can tell the two apart.
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


# -- The component beside the member's other six ------------------------------


def test_the_builder_resolves_the_named_store_or_none(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The builder resolves DATABASE_URL and answers None when nothing names a
    # store — the degrade-don't-break stance every store-bound builder here
    # takes, so a deployment without a relational store still composes.
    from ops import DATABASE_URL_ENV, build_null_calibration_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_null_calibration_store() is None
    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = build_null_calibration_store()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_the_builder_touches_no_disk_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Building performs no I/O — no store is constructed, no database opened,
    # no schema created — and when nothing names a store the builder answers
    # None without touching the disk.
    from ops import DATABASE_URL_ENV, build_null_calibration_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_null_calibration_store() is None


def test_the_component_name_is_the_member_seventh() -> None:
    # The growth the member's own registration reserved when feature 341
    # landed: the route, the dashboard, the live-metrics store, the
    # meta-overfit gap store, the discovery-rate store, the Type-B depth store,
    # and now the calibration store, each beside — never inside — another
    # member's components.
    from ops import (
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_DISCOVERY_RATE_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
        OPS_META_OVERFIT_COMPONENT_NAME,
        OPS_TYPE_B_DEPTH_COMPONENT_NAME,
    )

    names = {
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
        OPS_META_OVERFIT_COMPONENT_NAME,
        OPS_DISCOVERY_RATE_COMPONENT_NAME,
        OPS_TYPE_B_DEPTH_COMPONENT_NAME,
        OPS_NULL_CALIBRATION_COMPONENT_NAME,
    }
    # Seven distinct component names under the one member-first prefix.
    assert len(names) == 7
    assert OPS_NULL_CALIBRATION_COMPONENT_NAME == "ops-null-calibration"
    assert all(name.startswith("ops-") for name in names)


def test_the_component_name_is_exported_from_the_member() -> None:
    import ops

    assert "OPS_NULL_CALIBRATION_COMPONENT_NAME" in ops.__all__
    assert ops.OPS_NULL_CALIBRATION_COMPONENT_NAME == "ops-null-calibration"
    assert (
        ops.OPS_NULL_CALIBRATION_COMPONENT_NAME == OPS_NULL_CALIBRATION_COMPONENT_NAME
    )


def test_the_store_class_is_exported_from_the_member() -> None:
    import ops

    assert "NullCalibrations" in ops.__all__
    assert "NullCalibration" in ops.__all__
    assert "NullCalibrationError" in ops.__all__
    assert "NULL_CALIBRATION_TABLE" in ops.__all__
    assert ops.NULL_CALIBRATION_TABLE == NULL_CALIBRATION_TABLE


def test_the_error_is_the_members_own_vocabulary() -> None:
    # One base so a caller catches the member as a whole, one subclass per
    # surface so a refusal names where it happened.
    from ops import OpsError

    assert issubclass(NullCalibrationError, OpsError)
    assert OpsError in NullCalibrationError.__mro__
