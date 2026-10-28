"""additions_spec_shadow_liquidity_cut.xml, "Forward Shadow" feature.

System restricts the forward shadow's scored universe to the ``--liquidity-top``
``N`` mapped names ranked by the *median* of the snapshot's own
``futbars.quote_volume`` over the trailing ``--liquidity-window-days`` calendar
days ending on the decision date (inclusive), excludes a name carrying fewer
than ``--liquidity-min-days`` rows in that window, passes exactly that kept set
as ``allowed_symbols`` to :func:`orchestrator._shadow.shadow_weights` — *before*
any node is scored — reports the cut in the JSON line and in ``book.json``, and
writes byte-identical output when ``--liquidity-top`` is absent.

This suite is the liquidity cut's own, in the style of
``test_shadow_construction.py``: small synthetic sealed snapshots whose
``futbars`` carry the ``quote_volume`` values the ranking reads, one sqlite
``node`` table and one artifact tree per world, the sandbox itself stubbed out
except for the one real-scoring test that proves the kept book is still built
before it is scored.

Covers, in order:

* :func:`orchestrator.shadow._liquidity_rank` directly over a real mount: the
  window boundary (a row the day before the window's first date never counts, a
  row on the decision date always does), the median ranking and its
  lexically-smaller-first tie-break, and the too-thin-row exclusion and count;
* the CLI end to end over sealed snapshots with ``shadow_weights`` stubbed: the
  byte-identical default, the exactly-N cut with the dropped count, the
  too-thin-but-liquid exclusion, the tie-break pinned through ``book.json``,
  the two by-name refusals and the ``book.json`` keys present only when set;
* one real-scoring pass: the kept book is still the dollar-neutral book the
  z-scores describe (weights summing to 0, gross equal to ``--gross``), with the
  per-node ``allowed_symbols`` captured and shown to equal the kept set.

No test opens a network connection or writes outside a pytest temporary
directory. Runs under pytest-xdist: every fixture builds its own temporary
database, lake and artifact tree, with no shared module-level mutable state
across tests.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import cost_model
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from orchestrator import shadow as shadow_cli
from orchestrator._context import FUTBARS_STREAM
from orchestrator._shadow import ShadowWeights
from snapshot import SnapshotMount, SnapshotService

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0117_identity_trio")

USDM_PATH = Path(cost_model.__file__).with_name("binance_usdm.yaml")

_TS = pa.timestamp("us", tz="UTC")


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_shadow_liquidity_{revision}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sqlite_path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _bwrap_dir(tmp_path: Path) -> Path:
    bwrap_dir = tmp_path / "bin"
    bwrap_dir.mkdir(exist_ok=True)
    bwrap = bwrap_dir / "bwrap"
    if not bwrap.exists():
        bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
        bwrap.chmod(0o755)
    return bwrap_dir


def _stamp(day: dt.date) -> Any:
    return dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)


def _write_bars(staging: Path, symbol: str, day: dt.date, close: float) -> None:
    partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "open_time": pa.array([_stamp(day)], type=_TS),
                "close": [str(close)],
                "volume": ["10.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_futbars(
    staging: Path, symbol: str, day: dt.date, close: float, quote_volume: float
) -> None:
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "fut_close": [str(close)],
                "fut_volume": ["1000.0"],
                "taker_buy_volume": ["400.0"],
                "quote_volume": [str(quote_volume)],
            }
        ),
        partition / "part-0.parquet",
    )


# ===========================================================================
# World L1 — eight mapped names, distinct constant quote volumes, one tie
# ===========================================================================


#: The lake's own eight names, in the order the ranking reads them. Every
#: symbol carries :data:`PRICE_DAYS` days of bars and futbars.
LAKE_SYMBOLS = (
    "AAAUSDT",
    "BBBUSDT",
    "CCCUSDT",
    "DDDUSDT",
    "EEEUSDT",
    "FFFUSDT",
    "GGGUSDT",
    "HHHUSDT",
)
#: Distinct constant quote volumes, one per name — except ``EEEUSDT`` and
#: ``FFFUSDT``, which share ``500.0`` so the tie-break has a boundary to
#: decide. Median is that constant, the same every day.
QUOTE_VOLUME = {
    "AAAUSDT": 100.0,
    "BBBUSDT": 200.0,
    "CCCUSDT": 300.0,
    "DDDUSDT": 400.0,
    "EEEUSDT": 500.0,
    "FFFUSDT": 500.0,
    "GGGUSDT": 700.0,
    "HHHUSDT": 800.0,
}
#: A distinct, alternating-sign daily return per name, so momentum over the
#: signal's own lookback is distinct name to name *and* two names sit positive
#: and two negative among any four the cut keeps — the 2-per-leg a dollar-
#: neutral z-book needs.
_RETURN_BY_INDEX = tuple(
    (0.01 * (index + 1)) * (1.0 if index % 2 == 0 else -1.0)
    for index in range(len(LAKE_SYMBOLS))
)
RETURN_BY_SYMBOL = dict(zip(LAKE_SYMBOLS, _RETURN_BY_INDEX))

#: The decision date the CLI recovers from the grid, and the anchor/grid the
#: suite hands it so the answer is this date with no arithmetic to hand-check.
DAY = dt.date(2027, 4, 1)
ANCHOR = DAY
GRID_DAYS = 1
#: Thirty-one days ending at the decision date: the thirty inside the default
#: window (:data:`DAY` - 29 … :data:`DAY`) plus one *before* it
#: (:data:`DAY` - 30) that the window must never count.
PRICE_DAYS = tuple(
    DAY - dt.timedelta(days=offset) for offset in range(30, -1, -1)
)


def _price(rate: float, offset: int) -> float:
    return 100.0 * (1.0 + rate) ** offset


@dataclass
class _Sealed:
    service: SnapshotService
    sealed: Any

    @property
    def path(self) -> Path:
        return self.sealed.path


@pytest.fixture(scope="module")
def liquid_world(tmp_path_factory: pytest.TempPathFactory) -> _Sealed:
    """Eight mapped names, distinct constant quote volumes, one tie."""
    lake_root = tmp_path_factory.mktemp("shadow-liquidity-liquid") / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol in LAKE_SYMBOLS:
        for offset, day in enumerate(PRICE_DAYS):
            price = _price(RETURN_BY_SYMBOL[symbol], offset)
            _write_bars(staging, symbol, day, price)
            _write_futbars(staging, symbol, day, price, QUOTE_VOLUME[symbol])
    # The grid benchmark: exactly one day, so the latest grid date the CLI
    # finds is the decision date itself. It is deliberately *not* among the
    # contracts document's listed names, so it never enters the cut universe.
    _write_bars(staging, "BTCUSDT", DAY, 50000.0)
    _write_futbars(staging, "BTCUSDT", DAY, 50000.0, 1000.0)
    service = SnapshotService(lake_root)
    return _Sealed(service, service.seal(sealed_at=dt.datetime(2027, 4, 2, tzinfo=dt.UTC)))


# -- (e) _liquidity_rank directly over the real mount: the window boundary ---


def test_liquidity_rank_window_excludes_the_day_before_and_counts_the_decision_day(
    liquid_world: _Sealed,
) -> None:
    mount = SnapshotMount.for_directory(liquid_world.path)
    listed = set(mount.dates(FUTBARS_STREAM, "AAAUSDT"))
    # The extra day *before* the window's first date really is on the mount...
    assert (DAY - dt.timedelta(days=30)).isoformat() in listed
    assert (DAY).isoformat() in listed

    # ...but the thirty calendar days ending at DAY (DAY-29 … DAY) hold thirty
    # rows, so a floor of exactly thirty keeps the name: the decision-date row
    # is counted.
    ranked, medians, excluded = shadow_cli._liquidity_rank(
        mount, ["AAAUSDT"], DAY, window_days=30, min_days=30
    )
    assert ranked == ["AAAUSDT"]
    assert excluded == 0
    assert medians["AAAUSDT"] == pytest.approx(QUOTE_VOLUME["AAAUSDT"], abs=1e-12)

    # A floor of thirty-one is one more than the window can hold: the DAY-30
    # row that *is* present on the mount did not count toward the window, so
    # the name is excluded.
    ranked_one_too_many, medians_none, excluded_one_too_many = (
        shadow_cli._liquidity_rank(mount, ["AAAUSDT"], DAY, window_days=30, min_days=31)
    )
    assert ranked_one_too_many == []
    assert medians_none == {}
    assert excluded_one_too_many == 1


def test_liquidity_rank_orders_by_median_and_breaks_ties_by_symbol(
    liquid_world: _Sealed,
) -> None:
    mount = SnapshotMount.for_directory(liquid_world.path)

    ranked, medians, excluded = shadow_cli._liquidity_rank(
        mount, LAKE_SYMBOLS, DAY, window_days=30, min_days=20
    )

    assert excluded == 0
    # Volume descending, and the EEE/FFF tie (both 500.0) resolved by the
    # lexically smaller lake symbol first.
    assert ranked == [
        "HHHUSDT",
        "GGGUSDT",
        "EEEUSDT",
        "FFFUSDT",
        "DDDUSDT",
        "CCCUSDT",
        "BBBUSDT",
        "AAAUSDT",
    ]
    assert medians["EEEUSDT"] == medians["FFFUSDT"]


# ===========================================================================
# World L2 — a name carrying the highest volume but too few rows to rank
# ===========================================================================


THIN_SYMBOL = "THINUSDT"
THIN_QUOTE_VOLUME = 99999.0
THIN_ROWS = 10
THIN_DAYS = tuple(
    DAY - dt.timedelta(days=offset) for offset in range(THIN_ROWS - 1, -1, -1)
)
#: Four ordinary names, all with the full window's rows, below the thin name's
#: volume but otherwise unremarkable: they are what a correct cut keeps.
L2_SYMBOLS = ("LIQ1USDT", "LIQ2USDT", "LIQ3USDT", "LIQ4USDT")
L2_QUOTE_VOLUME = {
    "LIQ1USDT": 100.0,
    "LIQ2USDT": 200.0,
    "LIQ3USDT": 300.0,
    "LIQ4USDT": 400.0,
}


@pytest.fixture(scope="module")
def thin_world(tmp_path_factory: pytest.TempPathFactory) -> _Sealed:
    lake_root = tmp_path_factory.mktemp("shadow-liquidity-thin") / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(L2_SYMBOLS):
        rate = 0.01 * (index + 1) * (1.0 if index % 2 == 0 else -1.0)
        for offset, day in enumerate(PRICE_DAYS):
            price = _price(rate, offset)
            _write_bars(staging, symbol, day, price)
            _write_futbars(staging, symbol, day, price, L2_QUOTE_VOLUME[symbol])
    # The highest volume on the mount, but only ten rows inside the window.
    for offset, day in enumerate(THIN_DAYS):
        price = 100.0 + offset
        _write_bars(staging, THIN_SYMBOL, day, price)
        _write_futbars(staging, THIN_SYMBOL, day, price, THIN_QUOTE_VOLUME)
    _write_bars(staging, "BTCUSDT", DAY, 50000.0)
    _write_futbars(staging, "BTCUSDT", DAY, 50000.0, 1000.0)
    service = SnapshotService(lake_root)
    return _Sealed(service, service.seal(sealed_at=dt.datetime(2027, 4, 2, tzinfo=dt.UTC)))


# ===========================================================================
# The CLI: one world, one store, one artifact tree
# ===========================================================================


def _contracts_document(lake_symbols: tuple[str, ...]) -> dict[str, Any]:
    return {
        "code": 0,
        "msg": "",
        "data": [
            {"symbol": f"{symbol[: -len('USDT')]}-USDT", "status": 1, "apiStateOpen": "true"}
            for symbol in lake_symbols
        ],
    }


@dataclass
class _World:
    snapshot_path: Path
    contracts_path: Path
    database_url: str
    artifact_root: Path
    env: dict[str, str]


def _build_world(
    tmp_path: Path, sealed: _Sealed, lake_symbols: tuple[str, ...]
) -> _World:
    database_url = f"sqlite:///{tmp_path / 'shadow-liquidity.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(
        json.dumps(_contracts_document(lake_symbols)), encoding="utf-8"
    )

    config_document = {
        "snapshot_mount": str(tmp_path / "unused-snapshot-placeholder"),
        "evaluation_dates": ["2020-01-01"],
        "horizon": 10,
        "seed": 20261028,
        "epoch_id": "epoch-shadow-liquidity-test",
        "artifact_dir": str(artifact_root),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
        "instrument": "perp",
    }
    config_path = tmp_path / "evaluation-config.json"
    config_path.write_text(json.dumps(config_document), encoding="utf-8")

    env = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": database_url,
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "NULLIUS_COST_MODEL_PATH": str(USDM_PATH),
        "PATH": str(_bwrap_dir(tmp_path)),
    }
    return _World(
        snapshot_path=sealed.path,
        contracts_path=contracts_path,
        database_url=database_url,
        artifact_root=artifact_root,
        env=env,
    )


CAMPAIGN_ID = "campaign-liquidity"
NODE_CODE = "# shadow liquidity test signal\n"
#: A hand-written momentum signal over a short trailing window: distinct,
#: alternating-sign returns per name make the cross-section's z-scores distinct
#: and two-per-leg, so the real-scoring pass gets a book to check.
LOOKBACK = 3
MOMENTUM_SIGNAL_CODE = f"""
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    momentum = {{}}
    for symbol in ctx.universe:
        series = frame.filter(pl.col("symbol") == symbol).sort("open_time")
        if len(series) < {LOOKBACK}:
            momentum[symbol] = 0.0
        else:
            first = float(series[0 - {LOOKBACK}]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


def _node(world: _World, *, node_id: str, code: str) -> None:
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(_sqlite_path_of(world.database_url))) as connection:
        connection.execute(
            "INSERT INTO node "
            "(id, campaign_id, theme_root, depth, code_hash, artifact_uri) "
            "VALUES (?, ?, 'shadow-liquidity-test', 0, ?, 'artifact://shadow-liquidity-test')",
            (node_id, CAMPAIGN_ID, code_hash),
        )
        connection.commit()
    directory = world.artifact_root / CAMPAIGN_ID / node_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "code.py").write_text(code, encoding="utf-8")


def _stub_shadow_weights(symbols: tuple[str, ...], *, capture: list[Any] | None = None):
    """A stand-in answering a fixed alternating-sign book over ``symbols``.

    Restricted to ``allowed_symbols`` exactly as the real function restricts
    its own answer, so the CLI's cut is the only thing that decides what the
    book carries. Records each call's ``allowed_symbols`` when ``capture`` is
    given.
    """

    def stub(
        context: Any, code: str, *, as_of: dt.date, allowed_symbols: Any = None
    ) -> ShadowWeights:
        if capture is not None:
            capture.append(allowed_symbols)
        raw = {
            symbol: (1.0 if index % 2 == 0 else -1.0)
            for index, symbol in enumerate(sorted(symbols))
        }
        if allowed_symbols is not None:
            raw = {symbol: weight for symbol, weight in raw.items() if symbol in allowed_symbols}
        return ShadowWeights(
            as_of=as_of,
            weights=dict(raw),
            code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
            n_scored=len(raw),
            n_dropped_unpriced=0,
            n_dropped_unmapped=0,
            book_beta=None,
        )

    return stub


BOOK_KEYS = {
    "book_id",
    "rebalance_ts",
    "account",
    "margin_mode",
    "equity_usdt",
    "weights",
    "decay_horizon_seconds",
    "expected_fill_seconds",
    "positions",
    "originating_signal_ids",
}


def _run(world: _World, out: Path, extra: list[str]) -> tuple[int, list[str], str]:
    printed: list[str] = []
    argv = [
        "--snapshot", str(world.snapshot_path),
        "--node", f"{CAMPAIGN_ID}/node-a",
        "--out", str(out),
        "--contracts", str(world.contracts_path),
        "--grid-anchor", ANCHOR.isoformat(),
        "--grid-days", str(GRID_DAYS),
        *extra,
    ]
    exit_code = shadow_cli.main(argv, env=world.env, emit=printed.append)
    return exit_code, printed, ""


# -- (a) default path: no --liquidity-top, byte-identical, new keys at default -


def test_default_path_is_byte_identical_and_carries_default_liquidity_keys(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    exit_first, printed_first, _ = _run(world, first, [])
    exit_second, _printed_second, _ = _run(world, second, [])

    assert exit_first == shadow_cli.EXIT_OK
    assert exit_second == shadow_cli.EXIT_OK
    # Two identical runs — and, since nothing about the cut ran, exactly the
    # bytes the unchanged code path writes for this snapshot, nodes and flags.
    assert first.read_bytes() == second.read_bytes()

    document = json.loads(first.read_text(encoding="utf-8"))
    assert set(document) == BOOK_KEYS  # no liquidity_top, no liquidity_window_days
    assert "liquidity_top" not in document
    assert "liquidity_window_days" not in document

    # The written weights are the plain mean of the nodes' books (one node
    # here), renormalised to --gross and mapped — the unchanged pipeline, over
    # the whole mapped universe, with no cut in sight.
    node_book = dict(_stub_shadow_weights(LAKE_SYMBOLS)(None, NODE_CODE, as_of=DAY).weights)
    expected = shadow_cli._combine([node_book], gross=1.0)
    listed = {f"{symbol[: -len('USDT')]}-USDT" for symbol in LAKE_SYMBOLS}
    expected_bingx = {
        shadow_cli._map_to_bingx(symbol, listed): weight
        for symbol, weight in expected.items()
    }
    assert document["weights"] == pytest.approx(expected_bingx, abs=1e-12)

    result = json.loads(printed_first[0])
    assert result["liquidity_top"] is None
    assert result["liquidity_window_days"] == 30
    assert result["n_liquidity_ranked"] is None
    assert result["n_dropped_illiquid"] == 0


# -- (b)(h) exactly the N most liquid names, and the book.json keys ----------


def test_liquidity_top_keeps_exactly_the_four_most_liquid(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    out = tmp_path / "book.json"
    exit_code, printed, _ = _run(world, out, ["--liquidity-top", "4"])

    assert exit_code == shadow_cli.EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    kept = {"EEE-USDT", "FFF-USDT", "GGG-USDT", "HHH-USDT"}
    dropped = {"AAA-USDT", "BBB-USDT", "CCC-USDT", "DDD-USDT"}
    assert set(document["weights"]) == kept
    assert not (set(document["weights"]) & dropped)

    # (h) the two informational keys are present, and only because the cut ran.
    assert document["liquidity_top"] == 4
    assert document["liquidity_window_days"] == 30

    result = json.loads(printed[0])
    assert result["liquidity_top"] == 4
    assert result["liquidity_window_days"] == 30
    assert result["n_liquidity_ranked"] == 8
    assert result["n_dropped_illiquid"] == 4


def test_liquidity_window_days_is_reported_at_its_flag_value_and_not_written_when_absent(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    out = tmp_path / "book.json"
    exit_code, printed, _ = _run(
        world, out, ["--liquidity-top", "4", "--liquidity-window-days", "30"]
    )

    assert exit_code == shadow_cli.EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    # The window key rides along with the cut, at the flag's own value.
    assert document["liquidity_window_days"] == 30
    assert json.loads(printed[0])["liquidity_window_days"] == 30


# -- (c) a name with the highest volume but too few rows is excluded ----------


def test_liquidity_top_excludes_the_thin_name_and_counts_it_illiquid(
    tmp_path: Path, thin_world: _Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    all_symbols = (*L2_SYMBOLS, THIN_SYMBOL)
    world = _build_world(tmp_path, thin_world, all_symbols)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(shadow_cli, "shadow_weights", _stub_shadow_weights(all_symbols))

    # The thin name really is the most liquid on the mount.
    assert all(THIN_QUOTE_VOLUME > volume for volume in L2_QUOTE_VOLUME.values())

    out = tmp_path / "book.json"
    exit_code, printed, _ = _run(world, out, ["--liquidity-top", "3"])

    assert exit_code == shadow_cli.EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    # The kept three are the three most liquid *rankable* names; the thin name
    # and the fourth name are both gone.
    assert set(document["weights"]) == {"LIQ2-USDT", "LIQ3-USDT", "LIQ4-USDT"}
    assert "THIN-USDT" not in document["weights"]

    result = json.loads(printed[0])
    assert result["liquidity_top"] == 3
    assert result["n_liquidity_ranked"] == 4  # the thin name is not rankable
    assert result["n_dropped_illiquid"] == 2  # the thin name + the fourth name


# -- (d) identical medians: the lexically smaller name ranks first -----------


def test_liquidity_tie_break_keeps_the_lexically_smaller_name(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    out = tmp_path / "book.json"
    # HHH (800), GGG (700) lead; EEE and FFF tie at 500 for the third seat, so
    # a top of three keeps exactly one of them — the lexically smaller EEE.
    exit_code, printed, _ = _run(world, out, ["--liquidity-top", "3"])

    assert exit_code == shadow_cli.EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    assert set(document["weights"]) == {"EEE-USDT", "GGG-USDT", "HHH-USDT"}
    assert "FFF-USDT" not in document["weights"]
    assert json.loads(printed[0])["n_liquidity_ranked"] == 8


# -- (f) the kept book is still built before it is scored --------------------


def test_kept_set_rides_into_shadow_weights_as_allowed_symbols(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    captured: list[Any] = []
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS, capture=captured)
    )

    out = tmp_path / "book.json"
    exit_code, _printed, _ = _run(world, out, ["--liquidity-top", "4"])

    assert exit_code == shadow_cli.EXIT_OK
    assert len(captured) == 1
    assert set(captured[0]) == {"EEEUSDT", "FFFUSDT", "GGGUSDT", "HHHUSDT"}


def test_real_scoring_builds_a_neutral_kept_book_before_scoring(
    tmp_path: Path, liquid_world: _Sealed
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=MOMENTUM_SIGNAL_CODE)

    out = tmp_path / "book.json"
    # No monkeypatch: shadow_weights runs the real chain in the sandbox over
    # the cut universe, so the book is the one the kept cross-section z-scores.
    gross = 1.5
    exit_code, printed, _ = _run(
        world, out, ["--liquidity-top", "4", "--gross", str(gross)]
    )

    assert exit_code == shadow_cli.EXIT_OK, printed
    document = json.loads(out.read_text(encoding="utf-8"))
    assert set(document["weights"]) == {"EEE-USDT", "FFF-USDT", "GGG-USDT", "HHH-USDT"}

    weights = document["weights"]
    assert math.fsum(weights.values()) == pytest.approx(0.0, abs=1e-12)
    assert math.fsum(abs(value) for value in weights.values()) == pytest.approx(
        gross, abs=1e-12
    )

    result = json.loads(printed[0])
    assert result["n_liquidity_ranked"] == 8
    assert result["n_dropped_illiquid"] == 4


# -- (g) the by-name refusals ------------------------------------------------


def test_liquidity_top_below_two_is_refused_by_name(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    exit_code, printed, _ = _run(world, tmp_path / "book.json", ["--liquidity-top", "1"])

    assert exit_code == shadow_cli.EXIT_REFUSED
    assert printed == []
    assert "--liquidity-top" in capsys.readouterr().err


def test_liquidity_min_days_above_the_window_is_refused_by_name(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    exit_code, printed, _ = _run(
        world,
        tmp_path / "book.json",
        ["--liquidity-top", "4", "--liquidity-window-days", "30", "--liquidity-min-days", "40"],
    )

    assert exit_code == shadow_cli.EXIT_REFUSED
    assert printed == []
    assert "--liquidity-min-days" in capsys.readouterr().err


# -- the held branch carries the new keys too, and never re-ranks ------------


def test_held_branch_carries_the_liquidity_keys_and_keeps_the_book(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    out = tmp_path / "book.json"
    flags = ["--liquidity-top", "4"]
    first_exit, first_printed, _ = _run(world, out, flags)
    assert first_exit == shadow_cli.EXIT_OK
    written = out.read_bytes()

    second_exit, second_printed, _ = _run(world, out, flags)

    assert second_exit == shadow_cli.EXIT_OK
    assert out.read_bytes() == written  # the hold rule rebuilt nothing
    held = json.loads(second_printed[0])
    assert held["held"] is True
    assert held["liquidity_top"] == 4
    assert held["liquidity_window_days"] == 30
    assert held["n_liquidity_ranked"] is None  # the hold rule stays cheap
    assert held["n_dropped_illiquid"] == 0
    assert json.loads(first_printed[0])["liquidity_top"] == 4


def test_liquidity_window_below_one_is_refused_by_name(
    tmp_path: Path, liquid_world: _Sealed, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = _build_world(tmp_path, liquid_world, LAKE_SYMBOLS)
    _node(world, node_id="node-a", code=NODE_CODE)
    monkeypatch.setattr(
        shadow_cli, "shadow_weights", _stub_shadow_weights(LAKE_SYMBOLS)
    )

    exit_code, _printed, _ = _run(
        world, tmp_path / "book.json", ["--liquidity-top", "4", "--liquidity-window-days", "0"]
    )

    assert exit_code == shadow_cli.EXIT_REFUSED
    assert "--liquidity-window-days" in capsys.readouterr().err
