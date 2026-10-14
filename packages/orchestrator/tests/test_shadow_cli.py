"""additions_spec_forward_shadow.xml, "Forward Shadow" feature 3.

System writes the BingX VST book file from one or more research nodes, so
that the rebalance bot trades a research book instead of the synthetic
fixture: ``python -m orchestrator.shadow`` finds the decision date on the
research grid, verifies each node's code against the store's own
``code_hash``, scores every node through :func:`orchestrator._shadow.shadow_weights`
(stubbed here — this suite never starts a sandbox), combines the nodes'
books as an equal-weight mean renormalised to ``--gross``, maps lake
symbols to BingX's hyphenated spelling and writes the book atomically.

Covers, in order:

* the decision-date grid, directly over a stand-in snapshot mount and
  over the module's own refusals when no date qualifies;
* lake-to-BingX symbol mapping, including the ``1000``-prefix's two
  candidate hyphenations;
* the equal-weight combination, its renormalisation to ``--gross`` and its
  1e-6-of-equity drop floor;
* over one real sealed snapshot, one sqlite store and one artifact tree
  (the sandbox itself stubbed out): the hold rule, the code_hash refusal,
  a missing node, the atomic write (a spied ``os.replace``, one temp file,
  no leftovers), the book's exact key set and its combined weights;
* a round-trip of the written book through the router's own
  ``bingx_dry_run`` book loader, run as a real subprocess over the
  router's own recorded fixtures — no router file is read for anything but
  input, and none is edited.

No test opens a network connection or writes outside a pytest temporary
directory. Runs under pytest-xdist: every fixture builds its own temporary
database, lake and artifact tree, with no shared module-level mutable
state across tests.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
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
from orchestrator._context import BARS_STREAM, FUTBARS_STREAM
from orchestrator._shadow import ShadowWeights
from snapshot import SnapshotService

# tests -> orchestrator -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0117_identity_trio")
ROUTER_FIXTURES = REPO_ROOT / "packages" / "router" / "tests" / "fixtures" / "bingx_vst"
ROUTER_COMMAND_ROOTS = (
    REPO_ROOT / "src",
    REPO_ROOT / "packages" / "router" / "src",
    REPO_ROOT / "packages" / "book" / "src",
    REPO_ROOT / "packages" / "ingest" / "src",
)

_TS = pa.timestamp("us", tz="UTC")

USDM_PATH = Path(cost_model.__file__).with_name("binance_usdm.yaml")

#: The sealed world carries bars for every one of these; only BTCUSDT also
#: carries futbars, since the grid rule and ``load_evaluation_context``'s
#: own perp gate need exactly one futbars-carrying symbol to be satisfied.
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "ADAUSDT")
#: Exactly on the research grid (anchor + 100 * grid_days), so the
#: decision date the CLI finds is this date, with no grid arithmetic to
#: hand-check.
ANCHOR = dt.date(2022, 1, 3)
GRID_DAYS = 14
DAY = ANCHOR + dt.timedelta(days=100 * GRID_DAYS)

#: Lists four of :data:`SYMBOLS`' BingX spellings, deliberately omitting
#: ADAUSDT's — the suite's own "one unmapped symbol" fixture.
CONTRACTS_DOCUMENT = {
    "code": 0,
    "msg": "",
    "data": [
        {"symbol": "BTC-USDT", "status": 1, "apiStateOpen": "true"},
        {"symbol": "ETH-USDT", "status": 1, "apiStateOpen": "true"},
        {"symbol": "SOL-USDT", "status": 1, "apiStateOpen": "true"},
        {"symbol": "DOGE-USDT", "status": 1, "apiStateOpen": "true"},
    ],
}

NODE_A_CODE = "# shadow cli test signal A\n"
NODE_B_CODE = "# shadow cli test signal B\n"
WEIGHTS_BY_CODE = {
    NODE_A_CODE: {
        "BTCUSDT": 0.4,
        "ETHUSDT": -0.3,
        "SOLUSDT": 0.2,
        "DOGEUSDT": -0.1,
    },
    NODE_B_CODE: {
        "BTCUSDT": 0.2,
        "ETHUSDT": -0.1,
        "SOLUSDT": 0.1,
        "DOGEUSDT": -0.2,
        # Present only in this node's own answer, and not among the
        # contracts document's four listed symbols: exercises both the
        # "unmapped" drop and allowed_symbols' per-node restriction.
        "ADAUSDT": 0.4,
    },
}


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _stub_shadow_weights(
    context: Any, code: str, *, as_of: dt.date, allowed_symbols: Any = None
) -> ShadowWeights:
    """A stand-in for :func:`orchestrator._shadow.shadow_weights`.

    Never touches ``context``, never starts a sandbox — it answers one of
    two fixed books by the exact ``code`` string handed in, restricted to
    ``allowed_symbols`` exactly as the real function restricts its own
    answer, so the CLI's combination and mapping logic sees the same
    shape a real call would hand it.
    """
    raw = WEIGHTS_BY_CODE[code]
    if allowed_symbols is not None:
        raw = {symbol: weight for symbol, weight in raw.items() if symbol in allowed_symbols}
    return ShadowWeights(
        as_of=as_of,
        weights=dict(raw),
        code_hash=_code_hash(code),
        n_scored=len(raw),
        n_dropped_unpriced=0,
        n_dropped_unmapped=0,
        book_beta=0.5,
    )


# -- migrations and raw sqlite, the same idiom test_shadow_weights.py takes --


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_shadow_cli_{revision}", path
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


# -- the sealed snapshot -------------------------------------------------------


def _stamp(day: dt.date) -> Any:
    return dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)


def _write_bars(staging: Path, symbol: str, day: dt.date) -> None:
    partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "open_time": pa.array([_stamp(day)], type=_TS),
                "close": ["100.0"],
                "volume": ["10.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_futbars(staging: Path, symbol: str, day: dt.date) -> None:
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "fut_close": ["100.0"],
                "fut_volume": ["1000.0"],
                "taker_buy_volume": ["400.0"],
                "quote_volume": ["100000.0"],
            }
        ),
        partition / "part-0.parquet",
    )


@pytest.fixture(scope="module")
def sealed_snapshot(tmp_path_factory: pytest.TempPathFactory) -> Any:
    lake_root = tmp_path_factory.mktemp("shadow-cli-lake") / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol in SYMBOLS:
        _write_bars(staging, symbol, DAY)
    _write_futbars(staging, "BTCUSDT", DAY)
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


# -- one world: a tmp store, artifact tree and evaluation config -------------


@dataclass
class _World:
    snapshot_path: Path
    contracts_path: Path
    database_url: str
    artifact_root: Path
    env: dict[str, str]


def _build_world(
    tmp_path: Path, sealed_snapshot: Any, *, contracts_path: Path | None = None
) -> _World:
    database_url = f"sqlite:///{tmp_path / 'shadow-cli.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    if contracts_path is None:
        contracts_path = tmp_path / "contracts.json"
        contracts_path.write_text(json.dumps(CONTRACTS_DOCUMENT), encoding="utf-8")

    config_document = {
        # Always overridden by the CLI before load_evaluation_context ever
        # sees it — any non-blank placeholder is as good as a real one.
        "snapshot_mount": str(tmp_path / "unused-snapshot-placeholder"),
        "evaluation_dates": ["2020-01-01"],
        "horizon": 10,
        "seed": 20261014,
        "epoch_id": "epoch-shadow-cli-test",
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
        snapshot_path=sealed_snapshot.path,
        contracts_path=contracts_path,
        database_url=database_url,
        artifact_root=artifact_root,
        env=env,
    )


def _insert_node(world: _World, *, campaign_id: str, node_id: str, code_hash: str) -> None:
    with closing(sqlite3.connect(_sqlite_path_of(world.database_url))) as connection:
        connection.execute(
            "INSERT INTO node "
            "(id, campaign_id, theme_root, depth, code_hash, artifact_uri) "
            "VALUES (?, ?, 'shadow-cli-test', 0, ?, 'artifact://shadow-cli-test')",
            (node_id, campaign_id, code_hash),
        )
        connection.commit()


def _write_artifact(world: _World, *, campaign_id: str, node_id: str, code: str) -> None:
    directory = world.artifact_root / campaign_id / node_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "code.py").write_text(code, encoding="utf-8")


CAMPAIGN_ID = "campaign-1"


def _node(
    world: _World,
    *,
    node_id: str,
    code: str,
    stored_hash: str | None = None,
    write_artifact: bool = True,
) -> None:
    if stored_hash is not None:
        _insert_node(world, campaign_id=CAMPAIGN_ID, node_id=node_id, code_hash=stored_hash)
    if write_artifact:
        _write_artifact(world, campaign_id=CAMPAIGN_ID, node_id=node_id, code=code)


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


# -- the decision-date grid, as a pure function over a stand-in mount --------


class _FakeMount:
    def __init__(self, bars: tuple[str, ...], futbars: tuple[str, ...]) -> None:
        self._bars = bars
        self._futbars = futbars

    def dates(self, stream: str, symbol: str) -> tuple[str, ...]:
        if stream == BARS_STREAM:
            return self._bars
        if stream == FUTBARS_STREAM:
            return self._futbars
        raise AssertionError(stream)


def test_decision_date_is_the_latest_grid_point_at_or_before_the_last_common_date() -> None:
    bars = tuple((ANCHOR + dt.timedelta(days=offset)).isoformat() for offset in range(50))
    futbars = tuple((ANCHOR + dt.timedelta(days=offset)).isoformat() for offset in range(40))
    mount = _FakeMount(bars, futbars)

    result = shadow_cli._decision_date(mount, ANCHOR, GRID_DAYS)

    last_common = ANCHOR + dt.timedelta(days=39)
    steps = (last_common - ANCHOR).days // GRID_DAYS
    assert result == ANCHOR + dt.timedelta(days=steps * GRID_DAYS)
    assert result <= last_common


def test_decision_date_refuses_when_there_is_no_common_date() -> None:
    mount = _FakeMount(("2022-01-10",), ("2022-02-10",))
    with pytest.raises(shadow_cli.ShadowCliError):
        shadow_cli._decision_date(mount, ANCHOR, GRID_DAYS)


def test_decision_date_refuses_when_the_last_common_date_precedes_the_anchor() -> None:
    early = (ANCHOR - dt.timedelta(days=10)).isoformat()
    mount = _FakeMount((early,), (early,))
    with pytest.raises(shadow_cli.ShadowCliError):
        shadow_cli._decision_date(mount, ANCHOR, GRID_DAYS)


class _MetricsMount(_FakeMount):
    def __init__(self, bars: tuple[str, ...], metrics: tuple[str, ...]) -> None:
        super().__init__(bars, bars)
        self._metrics = metrics

    def dates(self, stream: str, symbol: str) -> tuple[str, ...]:
        if stream == "metrics":
            return self._metrics
        return super().dates(stream, symbol)


def test_a_required_stream_one_day_late_holds_the_previous_grid_date() -> None:
    # bars/futbars reach a grid date, metrics stop the day before it
    grid_day = 2 * GRID_DAYS
    bars = tuple((ANCHOR + dt.timedelta(days=offset)).isoformat() for offset in range(grid_day + 1))
    mount = _MetricsMount(bars, bars[:-1])

    assert shadow_cli._decision_date(mount, ANCHOR, GRID_DAYS) == ANCHOR + dt.timedelta(days=grid_day)
    assert shadow_cli._decision_date(mount, ANCHOR, GRID_DAYS, ("metrics",)) == ANCHOR + dt.timedelta(
        days=GRID_DAYS
    )


def test_the_require_stream_flag_is_repeatable_and_defaults_empty() -> None:
    parser = shadow_cli._build_parser()
    base = ["--snapshot", "s", "--node", "c/n", "--out", "o", "--contracts", "k"]
    assert parser.parse_args(base).require_streams == []
    assert parser.parse_args([*base, "--require-stream", "metrics"]).require_streams == ["metrics"]


# -- lake -> BingX symbol mapping ----------------------------------------------


def test_plain_usdt_symbol_maps_to_its_hyphenated_bingx_spelling() -> None:
    assert shadow_cli._map_to_bingx("BTCUSDT", {"BTC-USDT"}) == "BTC-USDT"


def test_a_symbol_the_contracts_document_does_not_list_is_unmapped() -> None:
    assert shadow_cli._map_to_bingx("ZZZUSDT", {"BTC-USDT"}) is None


def test_thousand_prefixed_symbol_prefers_its_own_thousand_hyphenation() -> None:
    listed = {"1000PEPE-USDT", "PEPE-USDT"}
    assert shadow_cli._map_to_bingx("1000PEPEUSDT", listed) == "1000PEPE-USDT"


def test_thousand_prefixed_symbol_falls_back_to_the_plain_hyphenation() -> None:
    assert shadow_cli._map_to_bingx("1000PEPEUSDT", {"PEPE-USDT"}) == "PEPE-USDT"


def test_thousand_prefixed_symbol_is_unmapped_when_neither_hyphenation_is_listed() -> None:
    assert shadow_cli._map_to_bingx("1000PEPEUSDT", {"ETH-USDT"}) is None


def test_symbol_map_counts_every_lake_symbol_with_no_bingx_answer() -> None:
    mapped, n_dropped = shadow_cli._symbol_map(
        ("BTCUSDT", "ETHUSDT", "ZZZUSDT"), {"BTC-USDT", "ETH-USDT"}
    )
    assert mapped == {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}
    assert n_dropped == 1


def test_listed_bingx_symbols_reads_the_contracts_documents_data_rows() -> None:
    listed = shadow_cli._listed_bingx_symbols(CONTRACTS_DOCUMENT)
    assert listed == {"BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"}


# -- book_id --------------------------------------------------------------------


def test_nodes_hash_is_independent_of_the_order_the_nodes_were_given_in() -> None:
    assert shadow_cli._nodes_hash(["b", "a"]) == shadow_cli._nodes_hash(["a", "b"])


def test_book_id_embeds_the_decision_date_and_the_nodes_hash() -> None:
    nodes = ["node-a", "node-b"]
    book_id = shadow_cli._book_id(DAY, nodes)
    assert book_id == f"shadow-{DAY.isoformat()}-{shadow_cli._nodes_hash(nodes)}"


# -- equal-weight combination and gross ---------------------------------------


def test_combine_is_the_equal_weight_mean_renormalised_to_gross() -> None:
    node_a = {"BTCUSDT": 0.4, "ETHUSDT": -0.3, "SOLUSDT": 0.2, "DOGEUSDT": -0.1}
    node_b = {"BTCUSDT": 0.2, "ETHUSDT": -0.1, "SOLUSDT": 0.1, "DOGEUSDT": -0.2}

    combined = shadow_cli._combine([node_a, node_b], gross=1.0)

    assert combined == pytest.approx(
        {"BTCUSDT": 0.375, "ETHUSDT": -0.25, "SOLUSDT": 0.1875, "DOGEUSDT": -0.1875},
        abs=1e-12,
    )
    assert sum(abs(w) for w in combined.values()) == pytest.approx(1.0, abs=1e-12)


def test_combine_renormalises_to_whatever_gross_is_asked_for() -> None:
    combined = shadow_cli._combine([{"AAA": 1.0, "BBB": -1.0}], gross=2.0)
    assert sum(abs(w) for w in combined.values()) == pytest.approx(2.0, abs=1e-12)


def test_combine_fills_a_symbol_only_one_node_scored_with_zero_for_the_rest() -> None:
    combined = shadow_cli._combine([{"AAA": 1.0}, {"BBB": -1.0}], gross=1.0)
    assert combined == pytest.approx({"AAA": 0.5, "BBB": -0.5}, abs=1e-12)


def test_combine_drops_weights_below_the_minimum_fraction_of_equity() -> None:
    combined = shadow_cli._combine([{"AAA": 1.0, "BBB": 1e-9}], gross=1.0)
    assert "BBB" not in combined
    # Renormalisation runs before the drop (the spec's own order), so AAA's
    # weight is off exact 1.0 by BBB's own now-discarded share.
    assert combined == pytest.approx({"AAA": 1.0}, abs=1e-8)


def test_combine_refuses_a_book_that_is_flat_across_every_node() -> None:
    with pytest.raises(shadow_cli.ShadowCliError):
        shadow_cli._combine([{"AAA": 0.0}], gross=1.0)


# -- exit codes for a missing DATABASE_URL / evaluation config ---------------


def test_exits_config_when_database_url_is_missing(tmp_path: Path) -> None:
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(tmp_path),
            "--node", "c/n",
            "--out", str(tmp_path / "book.json"),
            "--contracts", str(tmp_path / "contracts.json"),
        ],
        env={"NULLIUS_EVALUATION_CONFIG": "whatever"},
        emit=lambda _line: None,
    )
    assert exit_code == shadow_cli.EXIT_CONFIG


def test_exits_config_when_evaluation_config_is_missing(tmp_path: Path) -> None:
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(tmp_path),
            "--node", "c/n",
            "--out", str(tmp_path / "book.json"),
            "--contracts", str(tmp_path / "contracts.json"),
        ],
        env={"DATABASE_URL": "sqlite:///x.db"},
        emit=lambda _line: None,
    )
    assert exit_code == shadow_cli.EXIT_CONFIG


def test_refuses_a_malformed_node_argument(tmp_path: Path) -> None:
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(tmp_path),
            "--node", "no-slash-here",
            "--out", str(tmp_path / "book.json"),
            "--contracts", str(tmp_path / "contracts.json"),
        ],
        env={"DATABASE_URL": "sqlite:///x.db", "NULLIUS_EVALUATION_CONFIG": "whatever"},
        emit=lambda _line: None,
    )
    assert exit_code == shadow_cli.EXIT_REFUSED


# -- full-CLI coverage: hold rule, code_hash, atomic write, key set ----------


def test_writes_a_book_combining_two_nodes_with_the_exact_key_set(
    tmp_path: Path, sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, sealed_snapshot)
    _node(world, node_id="node-a", code=NODE_A_CODE, stored_hash=_code_hash(NODE_A_CODE))
    _node(world, node_id="node-b", code=NODE_B_CODE, stored_hash=_code_hash(NODE_B_CODE))
    monkeypatch.setattr(shadow_cli, "shadow_weights", _stub_shadow_weights)

    out = tmp_path / "book.json"
    printed: list[str] = []
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(world.snapshot_path),
            "--node", f"{CAMPAIGN_ID}/node-a",
            "--node", f"{CAMPAIGN_ID}/node-b",
            "--out", str(out),
            "--contracts", str(world.contracts_path),
        ],
        env=world.env,
        emit=printed.append,
    )

    assert exit_code == shadow_cli.EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    assert set(document) == BOOK_KEYS
    assert document["book_id"] == shadow_cli._book_id(DAY, ["node-a", "node-b"])
    assert document["rebalance_ts"] == dt.datetime.combine(
        DAY, dt.time(0), tzinfo=dt.UTC
    ).isoformat()
    assert document["account"] == "bingx-vst"
    assert document["margin_mode"] == "isolated"
    assert document["equity_usdt"] == "10000.0"
    assert document["expected_fill_seconds"] == 120
    assert document["positions"] == {}
    assert sorted(document["originating_signal_ids"]) == ["node-a", "node-b"]
    assert document["weights"] == pytest.approx(
        {"BTC-USDT": 0.375, "ETH-USDT": -0.25, "SOL-USDT": 0.1875, "DOGE-USDT": -0.1875},
        abs=1e-9,
    )
    assert document["decay_horizon_seconds"] == {
        symbol: 10 * 86400 for symbol in document["weights"]
    }

    result = json.loads(printed[0])
    assert result["held"] is False
    assert result["as_of"] == DAY.isoformat()
    assert result["decision_date"] == DAY.isoformat()
    assert result["book_path"] == str(out)
    assert sorted(result["nodes"]) == ["node-a", "node-b"]
    assert result["n_long"] == 2
    assert result["n_short"] == 2
    assert result["gross"] == pytest.approx(1.0, abs=1e-9)
    assert result["book_beta"] == pytest.approx(0.5)
    assert result["n_dropped_unmapped"] == 1  # ADAUSDT, node-b's own extra symbol


def test_hold_rule_skips_recomputation_once_the_book_id_already_matches(
    tmp_path: Path, sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, sealed_snapshot)
    _node(world, node_id="node-a", code=NODE_A_CODE, stored_hash=_code_hash(NODE_A_CODE))

    calls: list[str] = []

    def _tracking_stub(context: Any, code: str, *, as_of: dt.date, allowed_symbols: Any = None) -> ShadowWeights:
        calls.append(code)
        return _stub_shadow_weights(context, code, as_of=as_of, allowed_symbols=allowed_symbols)

    monkeypatch.setattr(shadow_cli, "shadow_weights", _tracking_stub)

    out = tmp_path / "book.json"
    args = [
        "--snapshot", str(world.snapshot_path),
        "--node", f"{CAMPAIGN_ID}/node-a",
        "--out", str(out),
        "--contracts", str(world.contracts_path),
    ]

    first_exit = shadow_cli.main(args, env=world.env, emit=lambda _line: None)
    assert first_exit == shadow_cli.EXIT_OK
    assert calls == [NODE_A_CODE]
    written_at = out.stat().st_mtime_ns

    printed: list[str] = []
    second_exit = shadow_cli.main(args, env=world.env, emit=printed.append)

    assert second_exit == shadow_cli.EXIT_OK
    assert calls == [NODE_A_CODE]  # shadow_weights was not called again
    assert out.stat().st_mtime_ns == written_at  # the file was not rewritten

    result = json.loads(printed[0])
    assert result["held"] is True
    assert result["book_path"] == str(out)
    assert result["nodes"] == ["node-a"]
    assert result["n_long"] == 2
    assert result["n_short"] == 2
    assert result["gross"] == pytest.approx(1.0, abs=1e-9)
    assert result["book_beta"] is None  # nothing was recomputed to answer it
    assert result["n_dropped_unmapped"] == 1


def test_refuses_when_the_stored_code_hash_does_not_match_the_artifact(
    tmp_path: Path, sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = _build_world(tmp_path, sealed_snapshot)
    _node(world, node_id="node-a", code=NODE_A_CODE, stored_hash="0" * 64)
    monkeypatch.setattr(shadow_cli, "shadow_weights", _stub_shadow_weights)

    out = tmp_path / "book.json"
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(world.snapshot_path),
            "--node", f"{CAMPAIGN_ID}/node-a",
            "--out", str(out),
            "--contracts", str(world.contracts_path),
        ],
        env=world.env,
        emit=lambda _line: None,
    )

    assert exit_code == shadow_cli.EXIT_REFUSED
    assert not out.exists()
    assert shadow_cli.SHADOW_CLI_CODE in capsys.readouterr().err


def test_refuses_a_node_id_absent_from_the_store(
    tmp_path: Path, sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, sealed_snapshot)
    _node(world, node_id="node-missing", code=NODE_A_CODE, stored_hash=None)
    monkeypatch.setattr(shadow_cli, "shadow_weights", _stub_shadow_weights)

    out = tmp_path / "book.json"
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(world.snapshot_path),
            "--node", f"{CAMPAIGN_ID}/node-missing",
            "--out", str(out),
            "--contracts", str(world.contracts_path),
        ],
        env=world.env,
        emit=lambda _line: None,
    )

    assert exit_code == shadow_cli.EXIT_REFUSED
    assert not out.exists()


def test_the_write_is_atomic_a_temp_file_in_the_same_directory_then_os_replace(
    tmp_path: Path, sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, sealed_snapshot)
    _node(world, node_id="node-a", code=NODE_A_CODE, stored_hash=_code_hash(NODE_A_CODE))
    monkeypatch.setattr(shadow_cli, "shadow_weights", _stub_shadow_weights)

    out_dir = tmp_path / "out-dir"
    out_dir.mkdir()
    out = out_dir / "book.json"

    replace_calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def _spy_replace(src: Any, dst: Any) -> None:
        replace_calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(shadow_cli.os, "replace", _spy_replace)

    exit_code = shadow_cli.main(
        [
            "--snapshot", str(world.snapshot_path),
            "--node", f"{CAMPAIGN_ID}/node-a",
            "--out", str(out),
            "--contracts", str(world.contracts_path),
        ],
        env=world.env,
        emit=lambda _line: None,
    )

    assert exit_code == shadow_cli.EXIT_OK
    assert len(replace_calls) == 1
    src, dst = replace_calls[0]
    assert dst == str(out)
    assert Path(src).parent == out_dir
    assert src != str(out)
    assert [p.name for p in out_dir.iterdir()] == [out.name]  # no leftover temp file


# -- round-trip: the router's own book loader accepts the written book ------


def test_round_trip_the_written_book_is_accepted_by_bingx_dry_run(
    tmp_path: Path, sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(
        tmp_path, sealed_snapshot, contracts_path=ROUTER_FIXTURES / "contracts.json"
    )
    _node(world, node_id="node-a", code=NODE_A_CODE, stored_hash=_code_hash(NODE_A_CODE))
    monkeypatch.setattr(shadow_cli, "shadow_weights", _stub_shadow_weights)

    out = tmp_path / "book.json"
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(world.snapshot_path),
            "--node", f"{CAMPAIGN_ID}/node-a",
            "--out", str(out),
            "--contracts", str(world.contracts_path),
        ],
        env=world.env,
        emit=lambda _line: None,
    )
    assert exit_code == shadow_cli.EXIT_OK

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(str(root) for root in ROUTER_COMMAND_ROOTS),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "router.bingx_dry_run",
            "--book", str(out),
            "--contracts", str(ROUTER_FIXTURES / "contracts.json"),
            "--marks", str(ROUTER_FIXTURES / "premium_index.json"),
        ],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(REPO_ROOT),
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    lines = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert lines  # at least one leg answered
    assert all("refusal" not in line for line in lines)  # every leg sized, none refused


# -- the ticker price guard (direct follow-up, 2026-10-15) ----------------------


def test_ticker_prices_reads_last_price_per_symbol_and_skips_junk_rows() -> None:
    document = {
        "data": [
            {"symbol": "BTC-USDT", "lastPrice": "83000.5"},
            {"symbol": "ETH-USDT", "lastPrice": "not-a-number"},
            {"symbol": "ZERO-USDT", "lastPrice": "0"},
            "junk",
        ]
    }
    assert shadow_cli._ticker_prices(document) == {"BTC-USDT": 83000.5}


def test_ticker_prices_refuses_a_document_with_no_data_list() -> None:
    with pytest.raises(shadow_cli.ShadowCliError):
        shadow_cli._ticker_prices({"code": 0})


def test_price_mismatch_drops_a_same_name_different_coin_and_keeps_a_days_move() -> None:
    d1, d2 = dt.date(2026, 10, 12), dt.date(2026, 10, 13)
    closes = {
        "AAAUSDT": {d1: 1.0, d2: 1.30},  # a 30% move: kept
        "BBBUSDT": {d1: 0.01, d2: 0.01},  # BingX quotes 5.0: another coin
        "PEPEUSDT": {d2: 0.00001},  # mapped to the 1000-contract
        "CCCUSDT": {d2: 2.0},  # no ticker price: left alone
    }
    symbol_map = {
        "AAAUSDT": "AAA-USDT",
        "BBBUSDT": "BBB-USDT",
        "PEPEUSDT": "1000PEPE-USDT",
        "CCCUSDT": "CCC-USDT",
    }
    prices = {"AAA-USDT": 1.0, "BBB-USDT": 5.0, "1000PEPE-USDT": 0.0105}
    assert shadow_cli._price_mismatches(symbol_map, prices, closes) == {"BBBUSDT"}


def test_shadow_context_drops_oos_dates_and_points_lake_roots_at_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    research = {
        "snapshot_mount": "/archive/snapshots/X",
        "evaluation_dates": ["2025-06-30"],
        "oos_dates": ["2025-08-04"],
        "lake_roots": ["/archive"],
        "horizon": 10,
    }
    named = tmp_path / "research.json"
    named.write_text(json.dumps(research), encoding="utf-8")
    snapshot = tmp_path / "lake-shadow" / "snapshots" / "2026-10-14T13:06:42Z_74b7de"
    seen: dict[str, Any] = {}

    def fake_load(env: Any) -> object:
        path = env[shadow_cli.EVALUATION_CONFIG_ENV]
        seen.update(json.loads(Path(path).read_text(encoding="utf-8")))
        return object()

    monkeypatch.setattr(shadow_cli, "load_evaluation_context", fake_load)
    shadow_cli._shadow_context({}, str(named), snapshot, dt.date(2026, 10, 5), tmp_path)
    assert "oos_dates" not in seen
    assert seen["lake_roots"] == [str(tmp_path / "lake-shadow")]
    assert seen["evaluation_dates"] == ["2026-10-05"]
    assert json.loads(named.read_text(encoding="utf-8")) == research
