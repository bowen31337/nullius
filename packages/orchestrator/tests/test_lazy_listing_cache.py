"""A symbol's partition listing is read once per process, not once per lookup.

``_LazyCloses``/``_LazyFunding`` hand out a fresh per-symbol mapping on every
index, and the beta window and funding carry look up one date per
(date x symbol x day). Each lookup used to re-list the symbol's partitions
(about 77 ms on the archive snapshot), so archP00's first roots ran for 15+
minutes on listings alone. These tests count the listings through a stub
mount.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from orchestrator._context import (
    FUTBARS_STREAM,
    _LazyCloses,
    _LazyFunding,
)


class _CountingMount:
    def __init__(self, days: list[str]) -> None:
        self.days = days
        self.listings = 0

    def dates(self, stream: str, symbol: str) -> list[str]:
        self.listings += 1
        return list(self.days)


def _mount(days: list[str]) -> Any:
    return _CountingMount(days)


def _days(n: int) -> list[str]:
    start = dt.date(2025, 1, 1)
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def test_closes_list_each_symbol_once_across_fresh_mappings() -> None:
    mount = _mount(_days(2000))
    closes = _LazyCloses(mount, uuid.uuid4().hex, ("AAAUSDT", "BBBUSDT"))
    probe = dt.date(2026, 1, 1)
    for _ in range(500):
        for symbol in ("AAAUSDT", "BBBUSDT"):
            assert probe in closes[symbol]
            assert dt.date(2031, 1, 1) not in closes[symbol]
    assert mount.listings == 2
    assert len(closes["AAAUSDT"]) == 2000
    assert next(iter(closes["AAAUSDT"])) == dt.date(2025, 1, 1)


def test_funding_lists_each_symbol_once_and_misses_are_key_errors() -> None:
    mount = _mount(_days(30))
    funding = _LazyFunding(mount, uuid.uuid4().hex, ("AAAUSDT",))
    for _ in range(200):
        assert funding["AAAUSDT"].get(dt.date(2030, 1, 1), 0.0) == 0.0
    assert mount.listings == 1


def test_the_stream_and_snapshot_are_part_of_the_listing_key() -> None:
    snapshot = uuid.uuid4().hex
    bars = _mount(_days(3))
    perp = _mount(_days(5))
    assert len(_LazyCloses(bars, snapshot, ("AAAUSDT",))["AAAUSDT"]) == 3
    futbars = _LazyCloses(
        perp, snapshot, ("AAAUSDT",), stream=FUTBARS_STREAM,
        day_column="date", close_column="fut_close",
    )
    assert len(futbars["AAAUSDT"]) == 5
    other = _mount(_days(7))
    assert len(_LazyCloses(other, uuid.uuid4().hex, ("AAAUSDT",))["AAAUSDT"]) == 7
