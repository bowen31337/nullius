"""Feature 2, sealing the derivative streams beside bars.

``additions_spec_derivatives_inputs.xml``, "Snapshot and Window" category,
feature 2: *System seals the derivative streams beside bars, so that*
``./run.sh lake-seal`` *returns a snapshot whose mount lists funding,
futbars and metrics partitions.* ``seal.py``'s allow-list
(:data:`snapshot.seal.ALLOWED_STREAMS`) now admits ``bars``, ``funding``,
``futbars`` and ``metrics`` in one documented constant; every other stray
path is still refused, and the manifest and hash cover the new files
exactly as they already covered ``bars``.

Two claims, one test class each:

* a staging tree holding all four streams seals through
  ``python -m snapshot.seal`` cleanly, and the mounted snapshot's
  ``partitions()`` and ``select()`` answer for every one of them;
* a staging path outside the allow-list -- even one that looks like a
  plausible future derivatives stream -- is still refused by name, exactly
  as a bars-only stray path was before this feature, and nothing is sealed.

This file sits inside ``packages/snapshot/tests``, so the suite-local
``conftest.py`` applies: ``LAKE_ROOT`` and ``DATABASE_URL`` are isolated per
test, no test holds state at module scope, and nothing here opens a real
network connection, so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stderr
from pathlib import Path

import pytest
from snapshot import ReadOnlyPath, SnapshotError, SnapshotService
from snapshot.seal import ALLOWED_STREAMS, STRAY_PATH_CODE, main, seal_lake

AT = "2026-09-01T00:00:00Z"
DATE = "2026-09-01"
SYMBOL = "BTCUSDT"


def _write_partition(
    staging_root: Path, stream: str, symbol: str, date: str, content: bytes
) -> None:
    partition = staging_root / stream / f"symbol={symbol}" / f"date={date}"
    partition.mkdir(parents=True, exist_ok=True)
    (partition / "part-0.parquet").write_bytes(content)


def _content(stream: str) -> bytes:
    return f"{stream}-{SYMBOL}-{DATE}".encode()


@pytest.fixture
def all_streams_staged(lake_root: Path) -> Path:
    """A staging tree holding one partition of each of today's four streams."""
    staging_root = lake_root / "staging"
    for stream in ALLOWED_STREAMS:
        _write_partition(staging_root, stream, SYMBOL, DATE, _content(stream))
    return lake_root


# -- All four streams seal, and the mount answers for each -------------------


class TestAllFourStreamsSeal:
    def test_the_allow_list_names_exactly_todays_four_streams(self) -> None:
        assert set(ALLOWED_STREAMS) == {"bars", "funding", "futbars", "metrics"}

    def test_a_staging_tree_with_all_four_streams_seals(
        self, all_streams_staged: Path, test_database_url: str
    ) -> None:
        lines: list[str] = []
        exit_code = main(
            ["--lake", str(all_streams_staged), "--sealed-at", AT],
            env={"DATABASE_URL": test_database_url},
            emit=lines.append,
        )
        assert exit_code == 0
        payload = json.loads(lines[0])
        assert payload["file_count"] == len(ALLOWED_STREAMS)

        sealed_path = all_streams_staged / "snapshots" / payload["name"]
        for stream in ALLOWED_STREAMS:
            part = (
                sealed_path
                / stream
                / f"symbol={SYMBOL}"
                / f"date={DATE}"
                / "part-0.parquet"
            )
            assert part.read_bytes() == _content(stream)

    def test_mount_partitions_and_select_answer_for_every_stream(
        self, all_streams_staged: Path, test_database_url: str
    ) -> None:
        lines: list[str] = []
        main(
            ["--lake", str(all_streams_staged), "--sealed-at", AT],
            env={"DATABASE_URL": test_database_url},
            emit=lines.append,
        )
        name = json.loads(lines[0])["name"]

        service = SnapshotService(all_streams_staged)
        mount = service.mount(name)

        for stream in ALLOWED_STREAMS:
            assert mount.partitions(stream) == (SYMBOL,)
            assert mount.dates(stream, SYMBOL) == (DATE,)
            parts = mount.select(stream, SYMBOL, DATE)
            assert [part.name for part in parts] == ["part-0.parquet"]
            assert all(isinstance(part, ReadOnlyPath) for part in parts)
            assert parts[0].read_bytes() == _content(stream)

        # A symbol absent from a stream prunes to nothing, same as bars.
        assert mount.select("funding", "ETHUSDT", DATE) == ()
        # An unsealed stream (never written to staging) is empty, not an error.
        assert mount.partitions("borrow") == ()

    def test_the_manifest_and_hash_cover_the_new_stream_files(
        self, all_streams_staged: Path, test_database_url: str
    ) -> None:
        lines: list[str] = []
        main(
            ["--lake", str(all_streams_staged), "--sealed-at", AT],
            env={"DATABASE_URL": test_database_url},
            emit=lines.append,
        )
        payload = json.loads(lines[0])
        sealed_path = all_streams_staged / "snapshots" / payload["name"]
        manifest = json.loads((sealed_path / "MANIFEST.json").read_bytes())

        expected_paths = {
            f"{stream}/symbol={SYMBOL}/date={DATE}/part-0.parquet"
            for stream in ALLOWED_STREAMS
        }
        assert set(manifest["files"]) == expected_paths
        for stream in ALLOWED_STREAMS:
            path = f"{stream}/symbol={SYMBOL}/date={DATE}/part-0.parquet"
            assert manifest["files"][path]["sha256"] == hashlib.sha256(
                _content(stream)
            ).hexdigest()

        # The hash is not blind to the three new streams: changing bytes in
        # a non-bars stream alone still changes the snapshot's full hash.
        other_lake = all_streams_staged.parent / "other-lake"
        other_staging = other_lake / "staging"
        for stream in ALLOWED_STREAMS:
            content = (
                b"different-funding-bytes" if stream == "funding" else _content(stream)
            )
            _write_partition(other_staging, stream, SYMBOL, DATE, content)
        (other_lake / "snapshots").mkdir(parents=True)
        other_lines: list[str] = []
        main(
            ["--lake", str(other_lake), "--sealed-at", AT],
            env={"DATABASE_URL": test_database_url},
            emit=other_lines.append,
        )
        other_payload = json.loads(other_lines[0])
        assert other_payload["snapshot_hash"] != payload["snapshot_hash"]


# -- An unknown stream is still refused ---------------------------------------


class TestUnknownStreamStillRefused:
    def test_an_unknown_stream_refuses_with_exit_1_and_seals_nothing(
        self, lake_root: Path, test_database_url: str
    ) -> None:
        staging_root = lake_root / "staging"
        _write_partition(staging_root, "bars", SYMBOL, DATE, b"bars-btc")
        _write_partition(staging_root, "openinterest", SYMBOL, DATE, b"stray-stream")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(
                ["--lake", str(lake_root), "--sealed-at", AT],
                env={"DATABASE_URL": test_database_url},
                emit=lambda _line: None,
            )

        assert exit_code == 1
        message = stderr.getvalue()
        assert STRAY_PATH_CODE in message
        assert "openinterest" in message
        assert "Traceback" not in message
        assert not (lake_root / "snapshots").exists() or not any(
            (lake_root / "snapshots").iterdir()
        )

    def test_seal_lake_itself_raises_naming_the_stray_path(
        self, lake_root: Path, test_database_url: str
    ) -> None:
        staging_root = lake_root / "staging"
        _write_partition(staging_root, "bars", SYMBOL, DATE, b"bars-btc")
        _write_partition(staging_root, "openinterest", SYMBOL, DATE, b"stray-stream")

        with pytest.raises(SnapshotError, match=STRAY_PATH_CODE) as excinfo:
            seal_lake(
                lake_root,
                sealed_at=AT,
                env={"DATABASE_URL": test_database_url},
            )
        assert "openinterest" in str(excinfo.value)
