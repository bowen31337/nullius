"""``resolve_window`` reuses one sealed snapshot's stream layout per process.

On the 239-symbol wide snapshot, ``resolve_window`` cost ~80 s a call — 8
``_stream_layout`` walks (:data:`evaluator._window.ROSTER_STREAM` plus the
seven :data:`evaluator._window.SLICED_STREAMS`, "bars" counted twice), each
listing every symbol's partitions and every symbol's dates. That cost is paid
once per ``evaluate_node``/``evaluate_on_dates`` call — once per node in a
campaign — even though every node of a campaign resolves the *same* sealed
snapshot: a campaign's host re-mounts it fresh for each node
(``SnapshotService.mount(name)`` returns a new object every call), so nothing
about the mount's own identity changed, only which object represents it.

A sealed snapshot's bytes never change once named (``_naming``,
docs/nullius-tech-architecture.md §4.2), so the layout ``resolve_window``
derives from one is a pure function of the snapshot's identity — safe to
keep for the life of the process and reuse across every later mount of the
same name. This suite pins that: a second ``resolve_window`` over a second,
independently-mounted handle to the same sealed snapshot makes no
``partitions``/``dates`` calls at all, and returns a resolution equal to the
first, uncached one — the cache is a reuse of an answer, never a different
one.

The structural stand-ins :mod:`test_window` builds (``FakeMount``) expose no
``hash_prefix``, so this module's cache never applies to them: nothing here
changes their behaviour, which is why that suite needed no change. The
negative test below pins that directly, against two stand-ins that share a
name but disagree on content — proof that an object this module cannot
vouch for is never served a cached answer.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from evaluator import resolve_window

_SNAPSHOT_SRC = Path(__file__).resolve().parents[3] / "packages" / "snapshot" / "src"
if str(_SNAPSHOT_SRC) not in sys.path:
    sys.path.insert(0, str(_SNAPSHOT_SRC))

from snapshot import SnapshotService  # type: ignore[import-not-found]

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
T = "2026-09-01T00:00:00Z"


def _stage_bars(staging: Path, symbol: str, dates: tuple[str, ...]) -> None:
    for date in dates:
        partition = staging / "bars" / f"symbol={symbol}" / f"date={date}"
        partition.mkdir(parents=True)
        (partition / "part-0.parquet").write_bytes(f"{symbol}-{date}".encode())


@pytest.fixture
def sealed_mount_factory(tmp_path: Path):
    """A function building a fresh mount handle onto one sealed snapshot.

    Every call returns a *new* :class:`snapshot.SnapshotMount` object for the
    identical sealed directory — exactly the shape the host's repeated
    ``SnapshotService.mount(name)`` calls take across a campaign's nodes —
    so the suite below proves the cache keys on the snapshot's identity, not
    on an object a caller happened to keep.
    """
    lake_root = tmp_path / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    _stage_bars(staging, "BTCUSDT", ("2026-08-31", "2026-09-01"))
    _stage_bars(staging, "ETHUSDT", ("2026-09-01",))
    service = SnapshotService(lake_root)
    sealed = service.seal(staging, sealed_at=AT)

    def factory():
        return service.mount(sealed.name)

    return factory


class _CountingMount:
    """A real mount, with ``partitions``/``dates`` counted — not mocked.

    Forwards ``name``, ``hash_prefix`` and ``path`` so the cache key
    :func:`evaluator._window._stream_layout_cache_key` builds sees the same
    identity the real mount carries; only the two listing calls are counted,
    so a test asserting zero of them is pinning that the *filesystem* was
    never touched, not merely that some wrapper was bypassed.
    """

    def __init__(self, mount: object) -> None:
        self._mount = mount
        self.partitions_calls = 0
        self.dates_calls = 0

    @property
    def name(self) -> str:
        return self._mount.name  # type: ignore[attr-defined]

    @property
    def hash_prefix(self) -> str:
        return self._mount.hash_prefix  # type: ignore[attr-defined]

    @property
    def path(self):
        return self._mount.path  # type: ignore[attr-defined]

    def partitions(self, stream: str) -> tuple[str, ...]:
        self.partitions_calls += 1
        return self._mount.partitions(stream)  # type: ignore[attr-defined]

    def dates(self, stream: str, symbol: str) -> tuple[str, ...]:
        self.dates_calls += 1
        return self._mount.dates(stream, symbol)  # type: ignore[attr-defined]


def test_a_second_mount_of_the_same_snapshot_is_served_from_cache(
    sealed_mount_factory,
) -> None:
    first_mount = sealed_mount_factory()
    uncached = resolve_window(first_mount, T)

    second_mount = _CountingMount(sealed_mount_factory())
    cached = resolve_window(second_mount, T)

    # The identical answer — caching is a reuse, never a different one.
    assert cached == uncached
    assert hash(cached) == hash(uncached)

    # And it was answered without a single filesystem listing: every
    # partitions()/dates() call the second resolve_window would otherwise
    # have made was served from the first call's cached layout.
    assert second_mount.partitions_calls == 0
    assert second_mount.dates_calls == 0


def test_the_cache_does_not_freeze_the_decision_time(sealed_mount_factory) -> None:
    # The cache holds one stream's *layout* (symbol -> dates), not a whole
    # resolution: two different decision times over the same cached layout
    # must still slice to their own, different universes and dates.
    mount_at_first_date = sealed_mount_factory()
    resolve_window(mount_at_first_date, T)  # warms the cache

    mount_at_earlier_date = _CountingMount(sealed_mount_factory())
    earlier = resolve_window(mount_at_earlier_date, "2026-08-31T00:00:00Z")
    assert earlier.universe == ("BTCUSDT",)  # ETHUSDT does not list until 09-01
    assert earlier.dates("bars", "BTCUSDT") == ("2026-08-31",)
    assert mount_at_earlier_date.partitions_calls == 0
    assert mount_at_earlier_date.dates_calls == 0

    later = resolve_window(sealed_mount_factory(), T)
    assert later.universe == ("BTCUSDT", "ETHUSDT")
    assert later.dates("bars", "BTCUSDT") == ("2026-08-31", "2026-09-01")


@dataclass(frozen=True)
class _FakeMount:
    """The bare structural surface ``test_window.py``'s own suite uses.

    No ``hash_prefix``, no ``path`` — exactly what a hand-written stand-in
    looks like, and exactly what :func:`evaluator._window._stream_layout_cache_key`
    refuses to cache.
    """

    name: str
    layout: dict[str, dict[str, tuple[str, ...]]]

    def partitions(self, stream: str) -> tuple[str, ...]:
        return tuple(sorted(self.layout.get(stream, {})))

    def dates(self, stream: str, symbol: str) -> tuple[str, ...]:
        return tuple(sorted(self.layout.get(stream, {}).get(symbol, ())))


def test_a_structural_stand_in_without_a_hash_is_never_cached() -> None:
    # Two FakeMounts sharing one name but disagreeing on content: if either
    # were served from a cache keyed on name alone, this would either raise
    # or answer the wrong universe. Neither happens — a stand-in missing
    # hash_prefix/path is recomputed fresh on every call.
    shared_name = "2026-09-01T00:00:00Z_aaaaaa"
    first = _FakeMount(name=shared_name, layout={"bars": {"BTCUSDT": ("2026-09-01",)}})
    second = _FakeMount(name=shared_name, layout={"bars": {"ETHUSDT": ("2026-09-01",)}})

    assert resolve_window(first, T).universe == ("BTCUSDT",)
    assert resolve_window(second, T).universe == ("ETHUSDT",)
    # Reversing the order still answers each stand-in's own content.
    assert resolve_window(second, T).universe == ("ETHUSDT",)
    assert resolve_window(first, T).universe == ("BTCUSDT",)
