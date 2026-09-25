"""Feature 347's store: the train-versus-holdout world score gap.

app_spec feature 347 — *System persists the train-versus-holdout world score
gap as the meta-overfitting indicator* — and docs §16's research-metrics line
(*"train-vs-holdout world score gap (meta-overfit)"*), the observable half of
§15's *"dreaming overfits the pool | Holdout-world score diverges from
train-world score"* row.

This suite pins the store's law: one row per dreaming cycle keyed by the
cycle's own name; the gap **computed by the store** as ``train_mean −
holdout_mean`` with no parameter for it at any spelling; both halves' levels
handed over already measured (the store reads no pool and takes no mean);
both world counts carried as context, validated as positive whole numbers and
entering no arithmetic; the ask validated whole **before a connection is
opened**, so a refused record leaves no database file at all; the write an
upsert that refreshes the measurement and preserves the row's original
``recorded_at``; the point read answering ``None`` and the sweep an empty
tuple for a deployment that has closed no cycle out — an absence, never a
zero, because ``0.0`` is a *measurement* (a cycle whose halves read
identically) and a caller that could not tell them apart would read a clean
cycle out of a missing row; the trend read answering oldest-first; a stored
row whose gap disagrees with its own two halves refused rather than served;
and the construction performing no I/O.

The fixtures mirror ``test_live_metrics.py``: a real SQLite file under
``tmp_path`` and a ``DATABASE_URL`` pointed at it, with the conftest's
per-test isolation so no test can write into the real store.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from ops import MetaOverfitGapError, MetaOverfitGaps
from ops.meta_overfit import (
    META_OVERFIT_TABLE,
    OPS_META_OVERFIT_COMPONENT_NAME,
)

CYCLE = "cycle-0001"
CYCLE_LATER = "cycle-0002"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "meta-overfit.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(store_url: str) -> MetaOverfitGaps:
    """A store bound to the test-only database."""
    return MetaOverfitGaps(store_url)


def _record(store: MetaOverfitGaps, cycle: str = CYCLE, **overrides: object):
    """One cycle's gap, the shape every test writes: 35 train worlds at 0.9
    against 15 holdout worlds at 0.3 — a positive gap, §15's row."""
    ask: dict[str, object] = {
        "train_mean": 0.9,
        "holdout_mean": 0.3,
        "train_worlds": 35,
        "holdout_worlds": 15,
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }
    ask.update(overrides)
    return store.record(cycle, **ask)


# -- Round trip ---------------------------------------------------------------


def test_record_then_gap_round_trips_to_the_bit(store: MetaOverfitGaps) -> None:
    # The row survives the write and comes back off its own columns,
    # unchanged — the store answers what was written, never a recomputation.
    written = _record(store)
    read_back = store.gap(CYCLE)
    assert read_back is not None
    assert read_back == written
    assert read_back.train_mean == 0.9
    assert read_back.holdout_mean == 0.3
    assert read_back.train_worlds == 35
    assert read_back.holdout_worlds == 15
    assert read_back.recorded_at == "2026-01-01T00:00:00+00:00"


def test_the_gap_is_the_stores_own_arithmetic(store: MetaOverfitGaps) -> None:
    # The one figure the sentence names, computed by the store as
    # train_mean - holdout_mean.  There is no parameter for it at any
    # spelling: a caller-stated difference would let the system persist two
    # levels and a third number that disagrees with both, and §15's remedy
    # (*cap M per §10.3.1*) is read off these rows.
    import inspect

    signature = inspect.signature(MetaOverfitGaps.record)
    assert "gap" not in signature.parameters
    assert not any("gap" in name for name in signature.parameters)
    record = _record(store, train_mean=0.9, holdout_mean=0.3)
    assert record.gap == pytest.approx(0.6)
    # Negative is a measurement too: the holdout half reading better is the
    # honest direction §15's row is *not* triggered by.
    other = _record(store, cycle=CYCLE_LATER, train_mean=0.2, holdout_mean=0.8)
    assert other.gap == pytest.approx(-0.6)
    # Exactly equal halves are a measurement of "no divergence", not an
    # absence: 0.0 is stored, not None.
    flat = _record(store, cycle="cycle-0003", train_mean=0.5, holdout_mean=0.5)
    assert flat.gap == 0.0
    # And the value carries no verdict past the number: no threshold, no
    # flag — whether a gap *is* meta-overfitting is §15's remedy's judgment,
    # reached by the loop that holds M, the split's rotation and the pool
    # size, and read off these rows rather than decided by this member.
    assert not any(
        "threshold" in name or "overfit" in name or "diverges" in name
        for name in dir(flat)
    )


def test_a_gap_at_any_spelling_is_refused(store: MetaOverfitGaps) -> None:
    # The value's own shape: a gap that disagrees with the two levels beside
    # it is a row lying about its own subtraction, refused rather than
    # served — the only arithmetic the store performs is the one it can check.
    from ops import MetaOverfitGap

    with pytest.raises(MetaOverfitGapError):
        MetaOverfitGap(
            iteration_id=CYCLE,
            train_mean=0.9,
            holdout_mean=0.3,
            train_worlds=35,
            holdout_worlds=15,
            gap=0.5,  # 0.9 - 0.3 is 0.6, not 0.5
            recorded_at="2026-01-01T00:00:00+00:00",
        )


def test_gap_answers_none_for_a_cycle_never_recorded(store: MetaOverfitGaps) -> None:
    # A cycle with no row answers None, never 0.0 — a zero is a measurement
    # (halves reading identically, no overfitting), and a cycle that closed
    # no gap out is not one.
    _record(store)
    assert store.gap(CYCLE) is not None
    assert store.gap(CYCLE_LATER) is None


def test_history_returns_rows_oldest_first(store: MetaOverfitGaps) -> None:
    # The trend §15's remedy watches the divergence across: ordered by the
    # row's own instant, oldest first.
    _record(store, cycle="cycle-0003", recorded_at="2026-03-01T00:00:00+00:00")
    _record(store, cycle=CYCLE, recorded_at="2026-01-01T00:00:00+00:00")
    _record(store, cycle=CYCLE_LATER, recorded_at="2026-02-01T00:00:00+00:00")
    assert [row.iteration_id for row in store.history()] == [
        CYCLE,
        CYCLE_LATER,
        "cycle-0003",
    ]


def test_history_breaks_same_instant_ties_by_the_cycle(store: MetaOverfitGaps) -> None:
    # Two cycles closing out at the same instant is one ordering the store
    # must not leave to the storage engine's accident: (recorded_at,
    # iteration_id), so two reads of one history return the same sequence.
    _record(store, cycle="cycle-0002", recorded_at="2026-01-01T00:00:00+00:00")
    _record(store, cycle="cycle-0001", recorded_at="2026-01-01T00:00:00+00:00")
    assert [row.iteration_id for row in store.history()] == [
        "cycle-0001",
        "cycle-0002",
    ]


def test_history_is_empty_for_a_deployment_that_closed_no_cycle_out(
    store: MetaOverfitGaps,
) -> None:
    # An empty tuple is the honest answer: a discoverable state, not an
    # exception and never a fabricated first point.
    assert store.history() == ()


# -- One cycle, one row -------------------------------------------------------


def test_the_row_carries_the_seven_columns_it_declares(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # The table's shape, pinned: the cycle's own name, the two halves'
    # levels, the two world counts, the derived gap and the row's label.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        rows = connection.execute(
            f"SELECT iteration_id, train_mean, holdout_mean, train_worlds, "
            f"holdout_worlds, gap, recorded_at FROM {META_OVERFIT_TABLE}"
        ).fetchall()
    assert len(rows) == 1
    cycle, train, holdout, train_n, holdout_n, gap, recorded_at = rows[0]
    assert cycle == CYCLE
    assert (train, holdout) == (0.9, 0.3)
    assert (train_n, holdout_n) == (35, 15)
    assert gap == pytest.approx(0.6)
    assert recorded_at == "2026-01-01T00:00:00+00:00"


def test_a_cycle_is_the_primary_key_and_two_cycles_are_two_rows(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # The key is the cycle's own name (feature 270's and 279's identity),
    # because the 70/30 split is taken per cycle and the gap is a property
    # of one cycle's split and its scores.
    _record(store, cycle=CYCLE)
    _record(store, cycle=CYCLE_LATER)
    with sqlite3.connect(store_path) as connection:
        rows = connection.execute(
            f"SELECT iteration_id FROM {META_OVERFIT_TABLE} ORDER BY iteration_id"
        ).fetchall()
    assert rows == [(CYCLE,), (CYCLE_LATER,)]
    assert len(store.history()) == 2


def test_upsert_refreshes_the_measurement_rather_than_appending(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A re-run of the same cycle's measurement refreshes the measured
    # columns — the figure is deterministic in the split and the pool feature
    # 270 holds fixed for the cycle, so it is the same measurement written
    # twice rather than a second occurrence.
    _record(store, train_mean=0.9, holdout_mean=0.3)
    _record(store, train_mean=0.7, holdout_mean=0.4)
    with sqlite3.connect(store_path) as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {META_OVERFIT_TABLE}"
        ).fetchone()[0]
    assert count == 1
    standing = store.gap(CYCLE)
    assert standing is not None
    assert standing.train_mean == 0.7
    assert standing.gap == pytest.approx(0.3)


def test_upsert_preserves_the_rows_original_recorded_at(store: MetaOverfitGaps) -> None:
    # The refresh arm deliberately does not touch recorded_at: the first
    # instant the cycle's gap was computed is a fact about the trend's
    # history a retry must not rewrite — feature 267's stance toward its own
    # per-campaign row, restated.
    first = _record(store, recorded_at="2026-01-01T00:00:00+00:00")
    refreshed = _record(store, train_mean=0.8, recorded_at="2026-09-09T09:09:09+00:00")
    assert first.recorded_at == "2026-01-01T00:00:00+00:00"
    # The answer is read back inside the write's transaction, so it is the
    # row's own instant rather than the argument's.
    assert refreshed.recorded_at == "2026-01-01T00:00:00+00:00"
    assert refreshed.train_mean == 0.8


# -- The ask is validated whole, before a connection is opened ----------------


def test_a_cycle_that_names_no_cycle_is_refused_before_any_connection(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # The key is the cycle's own name; a value that names no cycle names no
    # split and no gap, and there is no row to attribute a divergence to.
    for bad in ("", "   ", None, 7, ["cycle-0001"]):
        with pytest.raises(MetaOverfitGapError):
            store.record(
                bad,  # type: ignore[arg-type]
                train_mean=0.9,
                holdout_mean=0.3,
                train_worlds=35,
                holdout_worlds=15,
            )
    assert not store_path.exists()
    # A cycle name is stripped, so a padded spelling joins the same row.
    padded = store.record(
        f"  {CYCLE}  ",
        train_mean=0.9,
        holdout_mean=0.3,
        train_worlds=35,
        holdout_worlds=15,
    )
    assert padded.iteration_id == CYCLE
    assert store.gap(CYCLE) is not None


def test_a_level_that_is_not_a_finite_real_is_refused_before_any_connection(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A half's level is one finite real number.  Text, None, a sequence and a
    # flag are all refused ahead of any connection.
    for bad in (None, "0.9", [0.9], {"mean": 0.9}):
        with pytest.raises(MetaOverfitGapError):
            _record(store, train_mean=bad)
        with pytest.raises(MetaOverfitGapError):
            _record(store, holdout_mean=bad)
    assert not store_path.exists()


def test_an_infinite_or_nan_level_is_refused_by_name(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A replay that emitted no pick is scored -inf (feature 249's floor, the
    # miss), so a half on which every world missed has a level of -inf — and
    # a level that is not a number is not a level to compare.  A NaN is
    # refused for the same reason loudest of all: it compares false against
    # everything and would ride into the trend §15's remediation reads while
    # looking exactly like a data point.
    for field in ("train_mean", "holdout_mean"):
        for bad in (float("-inf"), float("inf"), float("nan")):
            with pytest.raises(MetaOverfitGapError) as caught:
                _record(store, **{field: bad})
            assert field in str(caught.value)
    assert not store_path.exists()


def test_two_finite_levels_whose_difference_overflows_are_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # Both operands are finite reals and each passes its own gate, but their
    # difference can still overflow the double range: 1e308 - (-1e308) is
    # +inf.  A gap that is not a number is not a divergence anybody can act
    # on, so it is refused — and refused *at the door*, before a connection
    # opens, not on the read-back after the row has already landed.  The
    # distinction is the whole test: the read-back is inside the write's
    # transaction, so a check that lived only there would INSERT the row,
    # refuse its own read, and leave a permanently unreadable gap in the
    # trend §15's remedy is read off.
    with pytest.raises(MetaOverfitGapError) as caught:
        _record(store, train_mean=1e308, holdout_mean=-1e308)
    assert "train_mean" in str(caught.value)
    # The ask was refused whole: no database file, so no wedged row.
    assert not store_path.exists()


def test_a_stored_row_whose_halves_overflow_the_subtraction_is_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # The same arithmetic, reached on the read path: a hand-inserted row
    # whose own two levels subtract to an infinity is a row no gap row could
    # be, and the value layer refuses it rather than handing a caller an
    # indicator that is not a number.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {META_OVERFIT_TABLE} SET train_mean = 1e308, "
            f"holdout_mean = -1e308, gap = 9e307 WHERE iteration_id = ?",
            (CYCLE,),
        )
    with pytest.raises(MetaOverfitGapError):
        store.history()
    with pytest.raises(MetaOverfitGapError):
        store.gap(CYCLE)


def test_bool_is_refused_before_real(store: MetaOverfitGaps, store_path: Path) -> None:
    # True is 1 in Python, and a flag where a level belongs would persist a
    # figure nobody measured; bool refused before real, the discipline the
    # live-metrics store beside this one states for its own values.
    with pytest.raises(MetaOverfitGapError):
        _record(store, train_mean=True)
    with pytest.raises(MetaOverfitGapError):
        _record(store, holdout_mean=False)
    assert not store_path.exists()


def test_a_level_has_no_sign_bound_and_no_magnitude_bound(
    store: MetaOverfitGaps,
) -> None:
    # An out-of-sample IR has no structural limit the way a correlation's
    # [-1, 1] does, and the *sign of the gap* is the headline — the direction
    # of §15's divergence — so a negative level or a large one is a
    # measurement, not a mistake, and clamping it would answer a gap nobody
    # measured.
    record = _record(store, train_mean=-12.5, holdout_mean=-9.25)
    assert record.train_mean == -12.5
    assert record.gap == pytest.approx(-3.25)
    wild = _record(store, cycle=CYCLE_LATER, train_mean=8.5e3, holdout_mean=-8.5e3)
    assert wild.gap == pytest.approx(17.0e3)


def test_a_count_that_is_not_a_whole_number_is_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A fractional world is not a world, and coercing it would be this store
    # inventing a split size the caller never stated.
    for bad in (35.0, "35", None, 35.5):
        with pytest.raises(MetaOverfitGapError):
            _record(store, train_worlds=bad)
        with pytest.raises(MetaOverfitGapError):
            _record(store, holdout_worlds=bad)
    assert not store_path.exists()


def test_a_count_of_zero_or_less_is_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A half with no worlds has a level that is a mean of nothing, and
    # §10.3.1's *select on train, report on holdout* needs both halves to
    # exist — the refusal feature 278 states for a fraction that empties one,
    # restated for the row that would record it.
    for bad in (0, -1):
        with pytest.raises(MetaOverfitGapError):
            _record(store, train_worlds=bad)
        with pytest.raises(MetaOverfitGapError):
            _record(store, holdout_worlds=bad)
    assert not store_path.exists()


def test_bool_is_refused_before_int_for_a_count(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A bool *is* an int in Python's hierarchy and is not a count of worlds.
    with pytest.raises(MetaOverfitGapError):
        _record(store, train_worlds=True)
    assert not store_path.exists()


def test_the_counts_enter_no_arithmetic(store: MetaOverfitGaps) -> None:
    # The counts are context — a 35/15 gap is not the indicator a 3/1 one is
    # — and nothing else: the gap is the difference of the two levels and
    # only that.  Two rows with the same levels and different counts carry
    # the same gap.
    one = _record(store, train_worlds=35, holdout_worlds=15)
    two = _record(store, cycle=CYCLE_LATER, train_worlds=3, holdout_worlds=1)
    assert one.gap == two.gap
    assert (two.train_worlds, two.holdout_worlds) == (3, 1)


def test_the_instant_must_be_a_nameable_label(store: MetaOverfitGaps, store_path: Path) -> None:
    # The instant is the label the trend's order reads; a value that is not a
    # nameable instant orders nothing.
    for bad in (12345, "", "   "):
        with pytest.raises(MetaOverfitGapError):
            _record(store, recorded_at=bad)
    assert not store_path.exists()


def test_default_instant_stamps_the_write(store: MetaOverfitGaps) -> None:
    # recorded_at defaults to now (UTC, second resolution); a caller that
    # measured at a known instant passes it, but the write can stamp its own.
    written = store.record(
        CYCLE,
        train_mean=0.9,
        holdout_mean=0.3,
        train_worlds=35,
        holdout_worlds=15,
    )
    instant = written.recorded_at
    assert "T" in instant
    assert instant.endswith("+00:00")
    time_part = instant.split("T")[1].split("+")[0]
    assert time_part.count(":") == 2
    assert "." not in time_part


# -- A stored row that is not a gap row is refused, never served --------------


def test_a_stored_row_whose_gap_disagrees_with_its_halves_is_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # SQLite's columns are dynamically typed, so a hand-edited row is
    # reachable; §15's remedy acts on this sweep, and a row that disagrees
    # with its own subtraction is refused rather than served — a skipped row
    # is a divergence wearing a shrug.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {META_OVERFIT_TABLE} SET gap = 99.0 WHERE iteration_id = ?",
            (CYCLE,),
        )
    with pytest.raises(MetaOverfitGapError) as caught:
        store.history()
    # The refusal names the cycle the bad row came from, so an operator gets
    # the row to repair rather than a complaint about a value with no
    # address.
    assert CYCLE in str(caught.value)
    with pytest.raises(MetaOverfitGapError):
        store.gap(CYCLE)


def test_a_stored_row_whose_level_is_not_a_measurement_is_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A level that is not a finite real is not a measurement any reader of
    # §15's divergence can act on.  SQLite's columns are dynamically typed,
    # so text lands in a REAL column (its NOT NULL constraint is the belt
    # against NULL, not a type gate) — and the store refuses it on read.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {META_OVERFIT_TABLE} SET train_mean = 'zero point nine' "
            f"WHERE iteration_id = ?",
            (CYCLE,),
        )
    with pytest.raises(MetaOverfitGapError):
        store.history()
    with pytest.raises(MetaOverfitGapError):
        store.gap(CYCLE)


def test_a_stored_row_whose_count_is_not_a_count_is_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A half-size that is not a count of worlds would otherwise reach §15's
    # remedy as context nobody measured.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {META_OVERFIT_TABLE} SET holdout_worlds = 0 "
            f"WHERE iteration_id = ?",
            (CYCLE,),
        )
    with pytest.raises(MetaOverfitGapError):
        store.history()


def test_a_stored_row_naming_no_cycle_is_refused(
    store: MetaOverfitGaps, store_path: Path
) -> None:
    # A row wearing a cycle no split was taken at is an indicator attributed
    # to no tournament.
    _record(store)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            f"UPDATE {META_OVERFIT_TABLE} SET iteration_id = '  ' WHERE iteration_id = ?",
            (CYCLE,),
        )
    with pytest.raises(MetaOverfitGapError):
        store.history()


# -- The store is the workspace's one relational store ------------------------


def test_construction_performs_no_io(store_url: str, store_path: Path) -> None:
    # The class resolves its path lazily, so constructing one performs no
    # I/O: composition-time work must not touch the disk.
    MetaOverfitGaps(store_url)
    assert not store_path.exists()


def test_resolve_answers_none_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Absent is not an error: it is a deployment without a relational store,
    # which composes no meta-overfit component — a discoverable state, not an
    # exception.
    from ops import DATABASE_URL_ENV

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert MetaOverfitGaps.resolve() is None


def test_resolve_answers_none_for_an_empty_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty or whitespace-only value counts as unset.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert MetaOverfitGaps.resolve() is None


def test_resolve_answers_the_named_store(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The store DATABASE_URL names, resolved.
    from ops import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = MetaOverfitGaps.resolve()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_an_unsupported_scheme_is_refused_at_first_use(
    store_path: Path,
) -> None:
    # Only sqlite:/// speaks — a Postgres metrics table arrives with the
    # versioned migration member, and pretending to speak it here would hide
    # a misrouted URL behind a mysterious file.  Refused at first use, not
    # construction.
    store = MetaOverfitGaps("postgresql://localhost/metrics")
    assert store.database_url == "postgresql://localhost/metrics"
    with pytest.raises(MetaOverfitGapError):
        _record(store)


def test_an_unspeakable_scheme_is_refused_at_first_use() -> None:
    # A scheme with no netloc and no path — refused at first use, not
    # construction, and never silently mis-parsed into a file.
    store = MetaOverfitGaps("redis://cache:6379/0")
    with pytest.raises(MetaOverfitGapError):
        _record(store)


def test_a_sqlite_url_with_a_host_is_refused() -> None:
    # No host but localhost admitted — the same refusal every store in this
    # workspace states for its own connection.
    store = MetaOverfitGaps("sqlite://remote-host/db.sqlite")
    with pytest.raises(MetaOverfitGapError):
        _record(store)


def test_a_sqlite_url_with_no_path_is_refused() -> None:
    # A URL with no path refused — the store must name a database.
    store = MetaOverfitGaps("sqlite:///")
    with pytest.raises(MetaOverfitGapError):
        _record(store)


def test_a_blank_url_is_refused_at_construction() -> None:
    # The URL is held, not resolved, but it must be a non-empty string.
    for bad in ("", "   ", None, 7):
        with pytest.raises(MetaOverfitGapError):
            MetaOverfitGaps(bad)  # type: ignore[arg-type]


def test_a_database_that_will_not_open_is_surfaced_chained(
    tmp_path: Path,
) -> None:
    # The store's own failure surfaces in this member's vocabulary, chained
    # to the original and deliberately not swallowed: a divergence that
    # measured but never landed is the state feature 347 exists to rule out.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = MetaOverfitGaps(f"sqlite:///{not_a_dir}/meta-overfit.db")
    with pytest.raises(MetaOverfitGapError) as caught:
        _record(store)
    assert caught.value.__cause__ is not None


def test_a_read_failure_is_surfaced_chained(tmp_path: Path) -> None:
    # A store that cannot be asked is surfaced rather than answered around —
    # §15's remedy and §16's metric are read off these rows.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = MetaOverfitGaps(f"sqlite:///{not_a_dir}/meta-overfit.db")
    with pytest.raises(MetaOverfitGapError) as caught:
        store.gap(CYCLE)
    assert caught.value.__cause__ is not None
    with pytest.raises(MetaOverfitGapError) as caught:
        store.history()
    assert caught.value.__cause__ is not None


# -- The component beside the member's other three ----------------------------


def test_the_builder_resolves_the_named_store_or_none(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The builder resolves DATABASE_URL and answers None when nothing names a
    # store — the degrade-don't-break stance every store-bound builder here
    # takes, so a deployment without a relational store still composes.
    from ops import DATABASE_URL_ENV, build_meta_overfit_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_meta_overfit_store() is None
    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = build_meta_overfit_store()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_the_builder_touches_no_disk_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Building performs no I/O — no store is constructed, no database opened,
    # no schema created — and when nothing names a store the builder answers
    # None without touching the disk.
    from ops import DATABASE_URL_ENV, build_meta_overfit_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_meta_overfit_store() is None


def test_the_component_name_is_the_member_fourth() -> None:
    # The growth the member's own registration reserved when feature 341
    # landed: the route, the dashboard, the live-metrics store, and now the
    # meta-overfit gap store, each beside — never inside — another member's
    # components.
    from ops import (
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
        OPS_META_OVERFIT_COMPONENT_NAME,
    )

    names = {
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
        OPS_META_OVERFIT_COMPONENT_NAME,
    }
    # Four distinct component names under the one member-first prefix.
    assert len(names) == 4
    assert OPS_META_OVERFIT_COMPONENT_NAME == "ops-meta-overfit"
    assert all(name.startswith("ops-") for name in names)


def test_the_component_name_is_exported_from_the_member() -> None:
    import ops

    assert "OPS_META_OVERFIT_COMPONENT_NAME" in ops.__all__
    assert ops.OPS_META_OVERFIT_COMPONENT_NAME == "ops-meta-overfit"
    assert (
        ops.OPS_META_OVERFIT_COMPONENT_NAME == OPS_META_OVERFIT_COMPONENT_NAME
    )


def test_the_store_class_is_exported_from_the_member() -> None:
    import ops

    assert "MetaOverfitGaps" in ops.__all__
    assert "MetaOverfitGap" in ops.__all__
    assert "MetaOverfitGapError" in ops.__all__
    assert "META_OVERFIT_TABLE" in ops.__all__
    assert ops.META_OVERFIT_TABLE == META_OVERFIT_TABLE
