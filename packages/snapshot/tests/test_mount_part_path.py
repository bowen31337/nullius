"""``part_path``: the day's part, addressed without listing its directory.

``SnapshotMount.select`` answers a partition by building its directory and
sorting the entries it holds.  That is the right shape when a caller does not
know what is in the directory, but the evaluation materializer does: the lake
writes exactly one ``part-0.parquet`` per symbol-day
(``nullius_ingest.bars_backfill``, ``derivs_backfill``), and the resolution
already named the ``(stream, symbol, date)`` triples that exist.  On the
239-symbol wide snapshot the ``scandir``-plus-sort each ``select`` makes was
1.8 s of a 14 s materialized date, so the materializer pays for it once per
symbol-day it reads — 631 times a date.

``part_path`` is the path-only sibling: the same answer on the layout the lake
actually writes, derived from the triple rather than read off the directory.
This file pins the claims it makes:

* **it agrees with ``select``** on every partition that exists and on a
  partition that does not — the materializer's own ``select`` fallback is
  therefore a pure performance choice, never a correctness one;
* **it lists nothing** — ``SnapshotMount.select``'s ``children()`` is never
  reached, which is the whole point;
* **it keeps the mount's refusals** — a missing stream, symbol or date is an
  empty answer (a miss, not an error), and a symlinked component at any level
  is refused rather than followed, exactly as ``select`` refuses it.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state across tests, so the suite is safe
under pytest-xdist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import ReadOnlyPath, SnapshotMount, SnapshotService

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
HASH = "b7c2d1" + "0" * 58
NAME = "2026-09-01T00:00:00Z_b7c2d1"

#: Two symbols with one part each, a symbol carrying an extra part beside the
#: first, and a stream that is not partitioned at all — the shapes a caller
#: can meet and the ones the two accessors must agree on.
PART_ZERO = b"BTCUSDT-2026-09-01-part-0"
PART_ONE = b"BTCUSDT-2026-09-01-part-1"
ETH_ZERO = b"ETHUSDT-2026-09-01-part-0"


@pytest.fixture
def lake_root(tmp_path: Path) -> Path:
    return tmp_path / "lake"


@pytest.fixture
def service(lake_root: Path) -> SnapshotService:
    lake_root.mkdir(parents=True)
    return SnapshotService(lake_root)


@pytest.fixture
def sealed_path(service: SnapshotService, lake_root: Path) -> Path:
    """A sealed snapshot with the §4.2 partition shape."""
    staging = lake_root / "staging"
    bars = staging / "bars" / "symbol=BTCUSDT" / "date=2026-09-01"
    bars.mkdir(parents=True)
    (bars / "part-0.parquet").write_bytes(PART_ZERO)
    (bars / "part-1.parquet").write_bytes(PART_ONE)
    other = staging / "bars" / "symbol=ETHUSDT" / "date=2026-09-01"
    other.mkdir(parents=True)
    (other / "part-0.parquet").write_bytes(ETH_ZERO)
    return service.seal(staging, sealed_at=AT, snapshot_hash=HASH).path


@pytest.fixture
def mount(service: SnapshotService, sealed_path: Path) -> SnapshotMount:
    return service.mount(NAME)


class TestPartPathAgreesWithSelect:
    def test_the_first_part_of_a_partition_is_the_day_the_lake_writes(
        self, mount: SnapshotMount
    ) -> None:
        # The lake's one-part-per-day layout: part_path answers exactly the
        # day's part, and it is a read-only path like every other.
        parts = mount.part_path("bars", "BTCUSDT", "2026-09-01")
        assert [part.name for part in parts] == ["part-0.parquet"]
        assert all(isinstance(part, ReadOnlyPath) for part in parts)
        assert parts[0].read_bytes() == PART_ZERO

    def test_it_matches_the_first_of_select_wherever_select_finds_parts(
        self, mount: SnapshotMount
    ) -> None:
        # The materializer takes ``paths[0]``; on every partition select can
        # see, part_path's single answer is that first part.
        for stream in ("bars",):
            for symbol in ("BTCUSDT", "ETHUSDT"):
                for date in ("2026-09-01", "2026-09-02"):
                    listed = mount.select(stream, symbol, date)
                    built = mount.part_path(stream, symbol, date)
                    if listed:
                        assert [p.relative for p in built] == [listed[0].relative]
                    else:
                        assert built == ()

    def test_a_missing_stream_symbol_or_date_is_an_empty_miss(
        self, mount: SnapshotMount
    ) -> None:
        # Absence is an empty answer, never an exception — the same stance
        # select takes, so a caller can swap one for the other untested.
        for stream, symbol, date in (
            ("nonesuch", "BTCUSDT", "2026-09-01"),
            ("bars", "SOLUSDT", "2026-09-01"),
            ("bars", "BTCUSDT", "1999-01-01"),
        ):
            assert mount.part_path(stream, symbol, date) == ()
            assert mount.select(stream, symbol, date) == ()

    def test_a_partition_holding_only_a_nonzero_part_is_a_miss(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # The one documented divergence: a partition whose only part is named
        # something other than part-0. A path-only accessor cannot see it
        # without listing, and the lake never writes one — select still finds
        # it, which is why the materializer keeps select as its fallback.
        staging = lake_root / "staging2"
        bars = staging / "bars" / "symbol=ODDUSDT" / "date=2026-09-02"
        bars.mkdir(parents=True)
        (bars / "chunk-7.parquet").write_bytes(b"ODD")
        sealed = service.seal(staging, sealed_at=AT, snapshot_hash="c" * 64)
        mounted = service.mount(sealed.name)
        assert mounted.part_path("bars", "ODDUSDT", "2026-09-02") == ()
        assert [p.name for p in mounted.select("bars", "ODDUSDT", "2026-09-02")] == [
            "chunk-7.parquet"
        ]


class TestPartPathNeverLists:
    def test_it_reads_no_directory_entries(self, mount: SnapshotMount) -> None:
        # The listing is the cost this accessor exists to remove: three
        # ``is_dir`` probes and one ``is_file``, and not a single scandir.
        calls: list[object] = []
        root = mount.root
        real_children = ReadOnlyPath.children

        def counting(self: ReadOnlyPath) -> tuple[ReadOnlyPath, ...]:
            calls.append(self.relative)
            return real_children(self)

        ReadOnlyPath.children = counting  # type: ignore[method-assign]
        try:
            parts = mount.part_path("bars", "BTCUSDT", "2026-09-01")
        finally:
            ReadOnlyPath.children = real_children  # type: ignore[method-assign]
        assert [part.name for part in parts] == ["part-0.parquet"]
        assert calls == [], f"part_path listed {calls}, an accessor that must not list"
        assert root is not None


class TestPartitionKeysDoNotRestatEachEntry:
    """``partitions()``/``dates()`` must not ask each entry's type by stat.

    ``_partition_keys`` used to list a directory through ``children()`` and
    then ask each returned :class:`ReadOnlyPath` "is this a directory?" —
    ``is_symlink()`` plus ``is_dir()``, two ``stat``-family syscalls per
    entry, to filter the ``key=value`` directories from anything else beside
    them. On the 239-symbol wide snapshot that was 3.6M ``stat`` and 1.9M
    ``is_symlink`` calls across one ``evaluator.resolve_window`` call — 81.5 s
    of a 114 s profile, almost all of it inside this one filter. The fix
    reads each entry's type from the ``DirEntry`` ``os.scandir`` already
    returned (``is_dir(follow_symlinks=False)``, no extra syscall), so
    ``ReadOnlyPath.is_dir`` — the method that did the restating — must never
    be called while answering a partition-keys query, however many entries
    the directory holds.
    """

    def test_dates_does_not_restat_fifty_partitions(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        staging = lake_root / "staging-many-dates"
        bars_symbol = staging / "bars" / "symbol=BTCUSDT"
        dates = tuple(f"2026-01-{day:02d}" for day in range(1, 51))
        for date in dates:
            partition = bars_symbol / f"date={date}"
            partition.mkdir(parents=True)
            (partition / "part-0.parquet").write_bytes(b"x")
        sealed = service.seal(staging, sealed_at=AT, snapshot_hash="d" * 64)
        mount = service.mount(sealed.name)

        calls: list[str] = []
        real_is_dir = ReadOnlyPath.is_dir

        def counting(self: ReadOnlyPath) -> bool:
            calls.append(self.relative)
            return real_is_dir(self)

        ReadOnlyPath.is_dir = counting  # type: ignore[method-assign]
        try:
            answered = mount.dates("bars", "BTCUSDT")
        finally:
            ReadOnlyPath.is_dir = real_is_dir  # type: ignore[method-assign]
        assert answered == dates
        assert calls == [], f"dates() restated {len(calls)} entries via ReadOnlyPath.is_dir"

    def test_partitions_does_not_restat_fifty_symbols(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        staging = lake_root / "staging-many-symbols"
        symbols = tuple(f"SYM{i:03d}USDT" for i in range(50))
        for symbol in symbols:
            partition = staging / "bars" / f"symbol={symbol}" / "date=2026-09-01"
            partition.mkdir(parents=True)
            (partition / "part-0.parquet").write_bytes(b"x")
        sealed = service.seal(staging, sealed_at=AT, snapshot_hash="e" * 64)
        mount = service.mount(sealed.name)

        calls: list[str] = []
        real_is_dir = ReadOnlyPath.is_dir

        def counting(self: ReadOnlyPath) -> bool:
            calls.append(self.relative)
            return real_is_dir(self)

        ReadOnlyPath.is_dir = counting  # type: ignore[method-assign]
        try:
            answered = mount.partitions("bars")
        finally:
            ReadOnlyPath.is_dir = real_is_dir  # type: ignore[method-assign]
        assert answered == tuple(sorted(symbols))
        assert calls == [], (
            f"partitions() restated {len(calls)} entries via ReadOnlyPath.is_dir"
        )


class TestPartPathKeepsTheMountsRefusals:
    def test_a_symlinked_component_is_refused_not_followed(
        self, service: SnapshotService, lake_root: Path, sealed_path: Path
    ) -> None:
        # Sealing refuses symlinks (``_content.walk_content``), so a sealed
        # tree holds none by construction — which is why this plants one
        # through the documented crack (the owner chmods the root writable
        # and symlinks into it), exactly as test_mount.py does.  A link at
        # any level of the partition path must make part_path answer
        # nothing, as select does: following it would put staging on the
        # mount path.
        import os

        outside = lake_root / "outside" / "date=2026-09-01"
        outside.mkdir(parents=True)
        (outside / "part-0.parquet").write_bytes(b"secret")
        os.chmod(sealed_path / "bars" / "symbol=BTCUSDT", 0o755)
        planted = sealed_path / "bars" / "symbol=BTCUSDT" / "date=1999-01-01"
        os.symlink(outside, planted)
        os.chmod(sealed_path / "bars" / "symbol=BTCUSDT", 0o555)
        mounted = service.mount(NAME, verify=False)
        assert mounted.part_path("bars", "BTCUSDT", "1999-01-01") == ()
        assert mounted.select("bars", "BTCUSDT", "1999-01-01") == ()
        # The real partitions beside it are untouched.
        assert mounted.part_path("bars", "BTCUSDT", "2026-09-01")

    def test_it_returns_a_path_a_read_cannot_mutate(self, mount: SnapshotMount) -> None:
        from snapshot import SnapshotReadOnlyError

        part = mount.part_path("bars", "BTCUSDT", "2026-09-01")[0]
        with pytest.raises(SnapshotReadOnlyError):
            part.write_bytes(b"tampered")
