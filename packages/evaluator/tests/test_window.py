"""Feature 72 — resolving the evaluation window host-side.

app_spec.xml feature 72: *"System resolves the evaluation window host-side
by slicing a sealed snapshot to the decision time, which returns a
point-in-time universe."* docs/nullius-tech-architecture.md §6.1 names the
step — ``1. resolve_window (host)  slice snapshot to t, resolve PIT
universe`` — and §5.2 shows where its result goes:

    window = materialize_window(snapshot, t, lookback=L, universe=U)  # HOST side, Z0

This suite tests the three claims in that sentence separately, because a
resolution that satisfied any two of them would be a different and worse
feature:

* **host-side** — :func:`resolve_window` reads only the mount's partition
  queries (directory listings), performs no I/O of its own, touches no lake
  or path, and returns a record that carries no path, file handle or mount;
* **a sealed snapshot** — the input is the read-only mount's own partition
  surface (``name``/``partitions``/``dates``), accepted *structurally*, and
  anything that is not a mount — a path, a service, a name — is refused;
* **a point-in-time universe** — the roster is resolved from the sealed
  bars as of the decision date, never from the wall clock, and the slice
  keeps only partitions dated at or before that date.

The universe rule is day-granular (§4.3): a symbol is tradable as of ``t``
when its bars carry a partition on ``t``'s UTC date. A symbol delisted
*after* ``t`` still has the day's candles and is returned (the survivorship
half of §4.3 — dropping it is the pruning that flatters a backtest); a
symbol delisted *before* ``t`` has history that survives the slice but is
not in the roster; a symbol *listed* after ``t`` cannot appear at all.

Two kinds of sealed snapshot are sliced below. A :class:`FakeMount` supplies
the mount's structural surface directly, so the pure resolution logic is
tested without a filesystem — and, crucially, lets a test hand the module an
object that is *almost* a mount (missing one method, carrying a bad date) to
pin each refusal. A real :class:`SnapshotMount` over a real sealed snapshot
(from the snapshot member, bootstrapped onto ``sys.path`` exactly as the
module loader would) proves the structural contract holds against the actual
handle the host hands this module, not just a hand-written stand-in.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evaluator import (
    EvaluatorWindowError,
    ROSTER_STREAM,
    SLICED_STREAMS,
    WindowResolution,
    resolve_window,
)

# The snapshot member is a separate workspace member; the root does not
# depend on it, so its ``src/`` is not on the venv's path. Bootstrap it here,
# exactly as the module loader does when it scans members, so the integration
# tests below open a *real* SnapshotMount rather than only a stand-in.
_SNAPSHOT_SRC = Path(__file__).resolve().parents[3] / "packages" / "snapshot" / "src"
if str(_SNAPSHOT_SRC) not in sys.path:
    sys.path.insert(0, str(_SNAPSHOT_SRC))

from snapshot import (  # type: ignore[import-not-found]
    ReadOnlyPath,
    SnapshotMount,
    SnapshotService,
)

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
HASH = "a3f91c" + "0" * 58
NAME = "2026-09-01T00:00:00Z_a3f91c"


# -- A structural stand-in ---------------------------------------------------


@dataclass(frozen=True)
class FakeMount:
    """The mount's structural surface, spelled by hand.

    Only the three members :func:`resolve_window` reaches for — ``name``,
    ``partitions`` and ``dates`` — plus the layout they describe. The layout
    is ``{stream: {symbol: (ISO dates,)}}``; ``partitions(stream)`` returns
    the symbols and ``dates(stream, symbol)`` the dates, both sorted, exactly
    as :class:`snapshot.SnapshotMount` does. A symbol absent from a stream
    returns an empty tuple, never an error — the same honest miss the real
    mount reports.
    """

    name: str
    layout: dict[str, dict[str, tuple[str, ...]]]

    def partitions(self, stream: str) -> tuple[str, ...]:
        return tuple(sorted(self.layout.get(stream, {})))

    def dates(self, stream: str, symbol: str) -> tuple[str, ...]:
        return tuple(sorted(self.layout.get(stream, {}).get(symbol, ())))


def _layout(**streams: dict[str, tuple[str, ...]]) -> dict[str, dict[str, tuple[str, ...]]]:
    """A layout with the given per-stream symbol→dates maps."""
    return dict(streams)


# -- The universe, resolved from the sealed bars -----------------------------


def test_the_universe_is_the_symbols_with_bars_on_the_decision_date() -> None:
    mount = FakeMount(
        name=NAME,
        layout=_layout(
            bars={
                "BTCUSDT": ("2026-08-31", "2026-09-01"),
                "ETHUSDT": ("2026-09-01",),
                "SOLUSDT": ("2026-08-31",),  # delisted before t
                "DOGEUSDT": ("2026-09-02",),  # listed after t
            },
        ),
    )
    resolution = resolve_window(mount, "2026-09-01T00:00:00Z")
    # BTC and ETH have bars on the decision date; SOL was gone the day before;
    # DOGE does not list until the day after. The roster is day-granular.
    assert resolution.universe == ("BTCUSDT", "ETHUSDT")


def test_the_universe_is_sorted_and_stable() -> None:
    # Feature 46's stable ordering: the roster arrives sorted regardless of
    # the order the layout happened to enumerate its symbols.
    mount = FakeMount(
        name=NAME,
        layout=_layout(bars={"ZZZUSDT": ("2026-09-01",), "AAAUSDT": ("2026-09-01",)}),
    )
    assert resolve_window(mount, "2026-09-01T00:00:00Z").universe == ("AAAUSDT", "ZZZUSDT")


def test_a_delisted_symbols_history_survives_the_slice_but_not_the_roster() -> None:
    # §4.3: a delisted symbol's full history is context and rides along
    # beneath a roster it no longer belongs to. The slice is an upper bound,
    # not a recent-context window.
    mount = FakeMount(
        name=NAME,
        layout=_layout(
            bars={
                "BTCUSDT": ("2026-09-01",),
                "SOLUSDT": ("2026-07-01", "2026-08-01", "2026-08-15"),
            },
            trades={"SOLUSDT": ("2026-08-15",)},
        ),
    )
    resolution = resolve_window(mount, "2026-09-01T00:00:00Z")
    assert resolution.universe == ("BTCUSDT",)
    # SOLUSDT is not tradable, but its history is still served by the window.
    assert resolution.dates("bars", "SOLUSDT") == ("2026-07-01", "2026-08-01", "2026-08-15")
    assert resolution.dates("trades", "SOLUSDT") == ("2026-08-15",)


# -- The slice keeps only partitions at or before t --------------------------


def test_the_slice_keeps_only_partitions_at_or_before_the_decision_date() -> None:
    mount = FakeMount(
        name=NAME,
        layout=_layout(
            bars={"BTCUSDT": ("2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02")},
            trades={"BTCUSDT": ("2026-09-01", "2026-09-02")},
            bookfeat={"BTCUSDT": ("2026-08-31",)},
        ),
    )
    resolution = resolve_window(mount, "2026-09-01T12:00:00Z")
    # The decision date is 2026-09-01; the 09-02 partition is future data.
    assert resolution.dates("bars", "BTCUSDT") == ("2026-08-30", "2026-08-31", "2026-09-01")
    assert resolution.dates("trades", "BTCUSDT") == ("2026-09-01",)
    assert resolution.dates("bookfeat", "BTCUSDT") == ("2026-08-31",)


def test_the_decision_dates_own_partition_stays() -> None:
    # The decision date's partition is kept; row-level absence (truncating
    # rows at t) is enforced downstream at the boundary that reads rows
    # (features 5 and 6), not here.
    mount = FakeMount(
        name=NAME,
        layout=_layout(bars={"BTCUSDT": ("2026-09-01",)}),
    )
    resolution = resolve_window(mount, "2026-09-01T23:59:59Z")
    assert resolution.dates("bars", "BTCUSDT") == ("2026-09-01",)


def test_streams_the_snapshot_does_not_carry_are_absent() -> None:
    mount = FakeMount(name=NAME, layout=_layout(bars={"BTCUSDT": ("2026-09-01",)}))
    resolution = resolve_window(mount, "2026-09-01T00:00:00Z")
    # Only bars was present; the other three sliced streams are absent, and a
    # miss reports as nothing rather than a nearest-match guess.
    assert list(resolution.slices) == ["bars"]
    assert resolution.dates("trades", "BTCUSDT") == ()
    assert resolution.dates("borrow", "BTCUSDT") == ()


def test_a_whole_market_ingest_gap_resolves_to_an_empty_universe() -> None:
    # A decision date *inside* the covered range that no symbol has bars on
    # is not refused: it is present-but-silent content, an honest empty
    # universe — distinguishable from a date the snapshot never covered.
    mount = FakeMount(
        name=NAME,
        layout=_layout(bars={"BTCUSDT": ("2026-08-31", "2026-09-02")}),
    )
    resolution = resolve_window(mount, "2026-09-01T00:00:00Z")
    assert resolution.universe == ()
    # BTCUSDT's history still rides along beneath the empty roster.
    assert resolution.dates("bars", "BTCUSDT") == ("2026-08-31",)


# -- The coverage refusal ----------------------------------------------------


def test_a_decision_date_before_the_first_partition_is_refused() -> None:
    mount = FakeMount(
        name=NAME,
        layout=_layout(bars={"BTCUSDT": ("2026-09-01", "2026-09-02")}),
    )
    with pytest.raises(EvaluatorWindowError, match="before the first"):
        resolve_window(mount, "2026-08-31T00:00:00Z")


def test_a_decision_date_after_the_last_partition_is_refused() -> None:
    mount = FakeMount(
        name=NAME,
        layout=_layout(bars={"BTCUSDT": ("2026-09-01", "2026-09-02")}),
    )
    with pytest.raises(EvaluatorWindowError, match="after the last"):
        resolve_window(mount, "2026-09-03T00:00:00Z")


# -- The decision time -------------------------------------------------------


def test_a_naive_datetime_is_interpreted_as_utc() -> None:
    mount = FakeMount(name=NAME, layout=_layout(bars={"BTCUSDT": ("2026-09-01",)}))
    resolution = resolve_window(mount, datetime(2026, 9, 1, 0, 0, 0))
    assert resolution.t.tzinfo is not None
    assert resolution.decision_date.isoformat() == "2026-09-01"


def test_an_aware_datetime_is_converted_to_utc() -> None:
    from datetime import timedelta

    # 2026-09-01T01:00+02:00 is 2026-08-31T23:00Z — the decision date is the
    # 31st, so the universe question changes.
    mount = FakeMount(
        name=NAME,
        layout=_layout(
            bars={
                "BTCUSDT": ("2026-08-31",),
                "ETHUSDT": ("2026-09-01",),
            }
        ),
    )
    resolution = resolve_window(
        mount, datetime(2026, 9, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    )
    assert resolution.decision_date.isoformat() == "2026-08-31"
    assert resolution.universe == ("BTCUSDT",)


def test_a_bare_date_is_refused() -> None:
    from datetime import date

    mount = FakeMount(name=NAME, layout=_layout(bars={"BTCUSDT": ("2026-09-01",)}))
    with pytest.raises(TypeError, match="a date names a day, not an instant"):
        resolve_window(mount, date(2026, 9, 1))  # type: ignore[arg-type]


# -- The sealed mount, accepted structurally ---------------------------------


def test_a_path_is_refused_not_a_mount() -> None:
    with pytest.raises(EvaluatorWindowError, match="not a sealed snapshot mount"):
        resolve_window(Path("/some/lake/2026-09-01T00:00:00Z_a3f91c"), "2026-09-01T00:00:00Z")


def test_a_service_is_refused_not_a_mount() -> None:
    # A service has no ``partitions``/``dates`` query surface — only a mount
    # does — so handing the service is refused with the remedy spelled out.
    with pytest.raises(EvaluatorWindowError, match="SnapshotService.mount"):
        resolve_window(SnapshotService, "2026-09-01T00:00:00Z")


def test_a_name_string_is_refused_not_a_mount() -> None:
    with pytest.raises(EvaluatorWindowError, match="not a sealed snapshot mount"):
        resolve_window(NAME, "2026-09-01T00:00:00Z")


def test_a_mount_missing_one_method_is_refused_with_the_remedy() -> None:
    @dataclass(frozen=True)
    class AlmostMount:
        name: str = NAME

        def partitions(self, stream: str) -> tuple[str, ...]:  # pragma: no cover
            return ()

    with pytest.raises(EvaluatorWindowError, match="no dates"):
        resolve_window(AlmostMount(), "2026-09-01T00:00:00Z")


def test_a_non_iso_partition_date_is_refused_by_name() -> None:
    mount = FakeMount(
        name=NAME,
        layout=_layout(bars={"BTCUSDT": ("2026-9-1",)}),  # not zero-padded ISO
    )
    with pytest.raises(EvaluatorWindowError, match="not an ISO date"):
        resolve_window(mount, "2026-09-01T00:00:00Z")


def test_a_non_iso_partition_symbol_is_refused() -> None:
    mount = FakeMount(name=NAME, layout=_layout(bars={"": ("2026-09-01",)}))
    with pytest.raises(EvaluatorWindowError, match="non-empty strings"):
        resolve_window(mount, "2026-09-01T00:00:00Z")


def test_a_snapshot_with_no_bars_cannot_say_what_was_tradable() -> None:
    # The roster is read from the bars stream (§4.3); a snapshot whose only
    # stream is trades has no roster to resolve.
    mount = FakeMount(name=NAME, layout=_layout(trades={"BTCUSDT": ("2026-09-01",)}))
    with pytest.raises(EvaluatorWindowError, match="carries no bars"):
        resolve_window(mount, "2026-09-01T00:00:00Z")


def test_the_roster_stream_constant_is_bars() -> None:
    assert ROSTER_STREAM == "bars"


def test_the_sliced_streams_are_the_four_symbol_partitioned_streams() -> None:
    # exchangeinfo is deliberately absent: it is versioned daily, not
    # partitioned by symbol, so there is no symbol= layer to slice.
    assert SLICED_STREAMS == ("bars", "trades", "bookfeat", "borrow")


# -- The resolution record is pure data --------------------------------------


def test_the_resolution_carries_no_path_or_mount() -> None:
    mount = FakeMount(name=NAME, layout=_layout(bars={"BTCUSDT": ("2026-09-01",)}))
    resolution = resolve_window(mount, "2026-09-01T00:00:00Z")
    # The record is a value: nameable, comparable, hashable. It holds the
    # snapshot's name, the instant, the roster and the surviving dates — and
    # no handle back to the sealed tree, which stays host-side.
    assert resolution.snapshot_name == NAME
    assert isinstance(resolution.t, datetime)
    for attribute in ("snapshot", "mount", "root", "path", "files"):
        assert not hasattr(resolution, attribute)


def test_the_resolution_is_hashable_and_comparable() -> None:
    mount = FakeMount(name=NAME, layout=_layout(bars={"BTCUSDT": ("2026-09-01",)}))
    first = resolve_window(mount, "2026-09-01T00:00:00Z")
    second = resolve_window(mount, "2026-09-01T00:00:00Z")
    assert first == second
    assert hash(first) == hash(second)
    # A different instant is a different window.
    assert first != resolve_window(mount, "2026-09-01T06:00:00Z")


def test_a_hand_built_resolution_enforces_its_invariants() -> None:
    # The dataclass checks the record itself, so a producer that emitted a
    # date after the decision time fails loudly rather than carrying a lie.
    from types import MappingProxyType

    with pytest.raises(EvaluatorWindowError, match="after the decision time"):
        WindowResolution(
            snapshot_name=NAME,
            t=datetime(2026, 9, 1, tzinfo=timezone.utc),
            universe=("BTCUSDT",),
            slices=MappingProxyType(
                {"bars": MappingProxyType({"BTCUSDT": ("2026-09-02",)})}
            ),
        )


def test_a_hand_built_resolution_rejects_an_unsorted_universe() -> None:
    from types import MappingProxyType

    with pytest.raises(EvaluatorWindowError, match="sorted and de-duplicated"):
        WindowResolution(
            snapshot_name=NAME,
            t=datetime(2026, 9, 1, tzinfo=timezone.utc),
            universe=("ETHUSDT", "BTCUSDT"),
            slices=MappingProxyType({}),
        )


def test_slicing_is_idempotent_and_reads_no_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No wall clock is read: resolving twice, even with the clock pinned to a
    # different day, yields the same window from the same sealed content.
    monkeypatch.setattr(
        "datetime.datetime",
        type("FrozenClock", (datetime,), {"now": classmethod(lambda cls, tz=None: datetime(2030, 1, 1, tzinfo=timezone.utc))}),  # noqa: UP037
    )
    mount = FakeMount(
        name=NAME,
        layout=_layout(bars={"BTCUSDT": ("2026-09-01", "2026-09-02")}),
    )
    assert resolve_window(mount, "2026-09-01T00:00:00Z").universe == ("BTCUSDT",)


# -- Against a real sealed snapshot ------------------------------------------
#
# The tests above slice a hand-written stand-in; these open the actual
# SnapshotMount the host hands this module, proving the structural contract
# holds against the real handle rather than only a look-alike.


@pytest.fixture
def snapshot_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SnapshotService:
    """A sealing service bound to a test-only lake."""
    lake = tmp_path / "lake"
    (lake / "snapshots").mkdir(parents=True)
    (lake / "staging").mkdir()
    monkeypatch.setenv("LAKE_ROOT", str(lake))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'window-test.db'}")
    return SnapshotService.from_env()


def _stage_bars(staging: Path, symbol: str, dates: tuple[str, ...]) -> None:
    for date in dates:
        partition = staging / "bars" / f"symbol={symbol}" / f"date={date}"
        partition.mkdir(parents=True)
        (partition / "part-0.parquet").write_bytes(f"{symbol}-{date}".encode())


def test_a_real_mount_slices_to_a_point_in_time_universe(
    snapshot_service: SnapshotService, tmp_path: Path
) -> None:
    staging = tmp_path / "staging"
    _stage_bars(staging, "BTCUSDT", ("2026-08-31", "2026-09-01"))
    _stage_bars(staging, "ETHUSDT", ("2026-09-01",))
    _stage_bars(staging, "SOLUSDT", ("2026-08-31",))  # delisted before t
    (staging / "borrow" / "rates.parquet").parent.mkdir(parents=True)
    (staging / "borrow" / "rates.parquet").write_bytes(b"borrow-rates")

    sealed = snapshot_service.seal(staging, sealed_at=AT, snapshot_hash=HASH)
    mount = snapshot_service.mount(sealed.name)

    # The real mount satisfies the same structural surface the FakeMount did.
    assert isinstance(mount, SnapshotMount)
    assert mount.name == NAME
    assert mount.partitions("bars") == ("BTCUSDT", "ETHUSDT", "SOLUSDT")

    resolution = resolve_window(mount, "2026-09-01T00:00:00Z")
    assert resolution.universe == ("BTCUSDT", "ETHUSDT")
    # SOLUSDT is not tradable, but its history is still served.
    assert resolution.dates("bars", "SOLUSDT") == ("2026-08-31",)
    # borrow is present but carries no symbol= partition layer, so it is
    # absent from the slice.
    assert "borrow" not in resolution.slices


def test_a_real_mount_reports_partitions_as_read_only_paths(
    snapshot_service: SnapshotService, tmp_path: Path
) -> None:
    # The slice keeps the partition *spellings* the mount's own select
    # consumes — and those spellings name files that are genuinely read-only.
    staging = tmp_path / "staging"
    _stage_bars(staging, "BTCUSDT", ("2026-08-31", "2026-09-01"))
    sealed = snapshot_service.seal(staging, sealed_at=AT, snapshot_hash=HASH)
    mount = snapshot_service.mount(sealed.name)

    resolution = resolve_window(mount, "2026-09-01T00:00:00Z")
    dates = resolution.dates("bars", "BTCUSDT")
    assert dates == ("2026-08-31", "2026-09-01")
    for date in dates:
        parts = mount.select("bars", "BTCUSDT", date)
        assert parts, f"the slice named a date with no parts: {date}"
        assert all(isinstance(part, ReadOnlyPath) for part in parts)
