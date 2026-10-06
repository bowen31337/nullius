"""Feature 3, the sealing CLI -- ``python -m snapshot.seal``.

``additions_spec_real_campaign_path.xml``, "Market Data to Sealed Snapshot"
category, feature 3: *System seals the staging area with* ``python -m
snapshot.seal --lake LAKE [--sealed-at ISO]`` *and displays one JSON line
with the snapshot name, path, full hash, file count and row count.* This
suite drives :func:`snapshot.seal.main` directly over a throwaway lake and
database -- never a real subprocess, mirroring ``test_fill_cli.py`` and
``test_canary_run.py``.

One test per claim the feature sentence makes:

* **a seal persists the staged tree and prints the five fields** -- name,
  path, full hash (64 hex) and file count match the sealed directory, and
  the manifest records the same per-file hashes, row counts and the read
  ``universe.json``.
* **``universe.json`` is read from beside staging, folded into the hash and
  the manifest, and never copied into the sealed tree.**
* **a stray path outside ``bars/`` refuses with exit 1**, naming the path,
  and nothing is sealed.
* **an already-sealed target name refuses with exit 1**, naming it, and the
  first seal is left untouched.
* **``DATABASE_URL`` set records the ``snapshot_manifest`` row** exactly as
  :func:`~snapshot.seal_snapshot` does.
* **no ``DATABASE_URL`` still seals**, exit 0, with one line on stderr
  saying so.

This file sits inside ``packages/snapshot/tests``, so the suite-local
``conftest.py`` applies: ``DATABASE_URL`` is isolated per test even though
every test below passes it to :func:`~snapshot.seal.main` explicitly rather
than relying on the process environment, and no test here opens a network
connection or holds state at module scope, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from contextlib import redirect_stderr
from pathlib import Path

import pytest
from snapshot import SCHEMA_VERSION, SnapshotManifestStore, count_rows
from snapshot.seal import (
    ALREADY_SEALED_CODE,
    EXIT_OK,
    EXIT_REFUSED,
    STRAY_PATH_CODE,
    main,
)

AT = "2026-09-01T00:00:00Z"

BTC_PART_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_PART_1 = b"BTCUSDT-2026-09-01-part-1"
ETH_PART_0 = b"ETHUSDT-2026-09-01-part-0"


def _formula(
    file_hashes: list[str],
    universe: Mapping[str, object] | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """The §4.2 formula, spelled out independently of the implementation."""
    universe_term = (
        "null"
        if universe is None
        else json.dumps(dict(universe), sort_keys=True, separators=(",", ":"))
    )
    preimage = "\n".join(
        ("".join(sorted(file_hashes)), universe_term, schema_version)
    ).encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    """A fresh §4.2 lake, with a staging tree of two symbols, one day each."""
    root = tmp_path / "lake"
    btc = root / "staging" / "bars" / "symbol=BTCUSDT" / "date=2026-09-01"
    btc.mkdir(parents=True)
    (btc / "part-0.parquet").write_bytes(BTC_PART_0)
    (btc / "part-1.parquet").write_bytes(BTC_PART_1)
    eth = root / "staging" / "bars" / "symbol=ETHUSDT" / "date=2026-09-01"
    eth.mkdir(parents=True)
    (eth / "part-0.parquet").write_bytes(ETH_PART_0)
    return root


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway, untouched database."""
    return f"sqlite:///{tmp_path / 'snapshot-seal-cli-test.db'}"


def _expected_hash(universe: Mapping[str, object] | None = None) -> str:
    parts = [BTC_PART_0, BTC_PART_1, ETH_PART_0]
    return _formula([hashlib.sha256(p).hexdigest() for p in parts], universe)


# -- Sealing and the printed line --------------------------------------------


def test_seal_prints_name_path_hash_file_count_and_row_count(
    lake: Path, database_url: str
) -> None:
    lines: list[str] = []

    exit_code = main(
        ["--lake", str(lake), "--sealed-at", AT],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    payload = json.loads(lines[0])

    expected_hash = _expected_hash()
    expected_name = f"{AT}_{expected_hash[:6]}"
    sealed_path = lake / "snapshots" / expected_name

    assert payload["name"] == expected_name
    assert payload["path"] == str(sealed_path)
    assert payload["snapshot_hash"] == expected_hash
    assert payload["file_count"] == 3
    expected_rows = sum(
        count_rows(sealed_path / rel)
        for rel in (
            "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet",
            "bars/symbol=BTCUSDT/date=2026-09-01/part-1.parquet",
            "bars/symbol=ETHUSDT/date=2026-09-01/part-0.parquet",
        )
    )
    assert payload["row_count"] == expected_rows

    assert sealed_path.is_dir()
    assert (
        sealed_path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
    ).read_bytes() == BTC_PART_0


def test_default_sealed_at_is_now(lake: Path, database_url: str) -> None:
    lines: list[str] = []

    exit_code = main(
        ["--lake", str(lake)], env={"DATABASE_URL": database_url}, emit=lines.append
    )

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["snapshot_hash"] == _expected_hash()
    assert (lake / "snapshots" / payload["name"]).is_dir()


# -- The manifest -------------------------------------------------------------


def test_the_manifest_records_the_per_file_hashes_and_row_counts(
    lake: Path, database_url: str
) -> None:
    lines: list[str] = []
    main(
        ["--lake", str(lake), "--sealed-at", AT],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )
    payload = json.loads(lines[0])
    sealed_path = lake / "snapshots" / payload["name"]

    manifest = json.loads((sealed_path / "MANIFEST.json").read_bytes())
    assert manifest["snapshot_hash"] == payload["snapshot_hash"]
    assert set(manifest["files"]) == {
        "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet",
        "bars/symbol=BTCUSDT/date=2026-09-01/part-1.parquet",
        "bars/symbol=ETHUSDT/date=2026-09-01/part-0.parquet",
    }
    assert manifest["files"][
        "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"
    ]["sha256"] == hashlib.sha256(BTC_PART_0).hexdigest()
    assert manifest["totals"] == {"files": 3, "rows": payload["row_count"]}


# -- universe.json ------------------------------------------------------------


def test_universe_json_is_folded_into_the_hash_and_manifest_but_never_sealed(
    lake: Path, database_url: str
) -> None:
    universe = {"top_n": 40, "as_of": "2026-09-01"}
    (lake / "universe.json").write_text(json.dumps(universe), encoding="utf-8")
    lines: list[str] = []

    exit_code = main(
        ["--lake", str(lake), "--sealed-at", AT],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["snapshot_hash"] == _expected_hash(universe)

    sealed_path = lake / "snapshots" / payload["name"]
    manifest = json.loads((sealed_path / "MANIFEST.json").read_bytes())
    assert manifest["universe"] == universe

    # Never copied into the sealed tree, nor counted among its files.
    assert not (sealed_path / "universe.json").exists()
    assert "universe.json" not in manifest["files"]
    assert payload["file_count"] == 3


def test_no_universe_json_folds_null(lake: Path, database_url: str) -> None:
    lines: list[str] = []
    main(
        ["--lake", str(lake), "--sealed-at", AT],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )
    payload = json.loads(lines[0])
    sealed_path = lake / "snapshots" / payload["name"]
    manifest = json.loads((sealed_path / "MANIFEST.json").read_bytes())
    assert manifest["universe"] is None


def test_malformed_universe_json_refuses_and_seals_nothing(
    lake: Path, database_url: str
) -> None:
    (lake / "universe.json").write_text("{not valid json", encoding="utf-8")
    stderr = io.StringIO()

    with redirect_stderr(stderr):
        exit_code = main(
            ["--lake", str(lake), "--sealed-at", AT],
            env={"DATABASE_URL": database_url},
            emit=lambda _line: None,
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "universe.json" in message
    assert "Traceback" not in message
    assert not (lake / "snapshots").exists() or not any(
        (lake / "snapshots").iterdir()
    )


def test_universe_json_that_is_not_a_json_object_refuses(
    lake: Path, database_url: str
) -> None:
    (lake / "universe.json").write_text("[1, 2, 3]", encoding="utf-8")
    stderr = io.StringIO()

    with redirect_stderr(stderr):
        exit_code = main(
            ["--lake", str(lake), "--sealed-at", AT],
            env={"DATABASE_URL": database_url},
            emit=lambda _line: None,
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "JSON object" in message
    assert "Traceback" not in message


# -- The stray-path refusal ---------------------------------------------------


def test_a_stray_path_outside_bars_refuses_and_seals_nothing(
    lake: Path, database_url: str
) -> None:
    (lake / "staging" / "notes.txt").write_bytes(b"not a bars partition")
    stderr = io.StringIO()

    with redirect_stderr(stderr):
        exit_code = main(
            ["--lake", str(lake), "--sealed-at", AT],
            env={"DATABASE_URL": database_url},
            emit=lambda _line: None,
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert STRAY_PATH_CODE in message
    assert "notes.txt" in message
    assert "Traceback" not in message
    assert not (lake / "snapshots").exists() or not any(
        (lake / "snapshots").iterdir()
    )


def test_a_stray_top_level_directory_outside_bars_refuses(
    lake: Path, database_url: str
) -> None:
    other = lake / "staging" / "trades" / "symbol=BTCUSDT"
    other.mkdir(parents=True)
    (other / "part-0.parquet").write_bytes(b"trade-rows")
    stderr = io.StringIO()

    with redirect_stderr(stderr):
        exit_code = main(
            ["--lake", str(lake), "--sealed-at", AT],
            env={"DATABASE_URL": database_url},
            emit=lambda _line: None,
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert STRAY_PATH_CODE in message
    assert "trades/symbol=BTCUSDT/part-0.parquet" in message


# -- The already-sealed refusal ------------------------------------------------


def test_an_already_sealed_target_name_refuses_and_leaves_it_untouched(
    lake: Path, database_url: str
) -> None:
    first = main(
        ["--lake", str(lake), "--sealed-at", AT],
        env={"DATABASE_URL": database_url},
        emit=lambda _line: None,
    )
    assert first == EXIT_OK
    sealed_path = lake / "snapshots" / f"{AT}_{_expected_hash()[:6]}"
    before = (
        sealed_path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
    ).read_bytes()

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        second = main(
            ["--lake", str(lake), "--sealed-at", AT],
            env={"DATABASE_URL": database_url},
            emit=lambda _line: None,
        )

    assert second == EXIT_REFUSED
    message = stderr.getvalue()
    assert ALREADY_SEALED_CODE in message
    assert f"{AT}_{_expected_hash()[:6]}" in message
    assert "Traceback" not in message
    after = (
        sealed_path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
    ).read_bytes()
    assert before == after == BTC_PART_0


# -- The snapshot_manifest record ----------------------------------------------


def test_database_url_set_records_the_snapshot_manifest_row(
    lake: Path, database_url: str
) -> None:
    lines: list[str] = []
    exit_code = main(
        ["--lake", str(lake), "--sealed-at", AT],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )
    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])

    store = SnapshotManifestStore(database_url)
    record = store.record_for(payload["snapshot_hash"])
    assert record is not None
    assert record.snapshot_hash == payload["snapshot_hash"]
    assert record.file_count == payload["file_count"]
    assert record.row_count == payload["row_count"]


def test_no_database_url_still_seals_and_says_so_on_stderr(lake: Path) -> None:
    lines: list[str] = []
    stderr = io.StringIO()

    with redirect_stderr(stderr):
        exit_code = main(
            ["--lake", str(lake), "--sealed-at", AT], env={}, emit=lines.append
        )

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["snapshot_hash"] == _expected_hash()

    message = stderr.getvalue()
    assert "DATABASE_URL" in message
    assert "Traceback" not in message

    sealed_path = lake / "snapshots" / payload["name"]
    assert sealed_path.is_dir()
