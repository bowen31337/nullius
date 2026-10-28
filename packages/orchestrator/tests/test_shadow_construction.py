"""additions_spec_shadow_book_construction.xml, "Forward Shadow" feature.

System builds each shadow node's book with the evaluation config's own
``book.weighting`` (computing the inverse-vol panel from the snapshot's
closes over ``book.vol_window_days``, exactly as the evaluation chain
does), caps any single name's absolute weight in the combined book at
``--max-name-weight`` with iterative renormalisation to ``--gross``,
optionally scales each node's weight vector by the inverse of its own
trailing realised book volatility before combining under
``--node-weighting inverse_vol``, and writes byte-identical output when
none of this is configured.

This suite is split in two, matching the feature's two collaborators:

* :mod:`orchestrator._shadow` — ``shadow_weights`` over a real sealed
  snapshot and the hardened-subprocess sandbox (the same pattern
  ``test_shadow_weights.py`` already uses): the default ``"z"`` path is
  byte-for-byte what :func:`evaluator.book_weights` was always called with
  (no ``vols``, no ``weighting`` keyword); ``"inverse_vol"`` matches a
  direct :func:`orchestrator._context.compute_vols` call and drops the one
  symbol its panel cannot price; ``"short_tail"`` passes straight through
  with no side panel.
* :mod:`orchestrator.shadow` (the CLI) — ``_cap_name_weights`` and
  ``_node_book_sigma`` as pure functions over hand-built weight vectors and
  close panels (no sandbox, no snapshot — the loop and the trailing-vol
  arithmetic owe nothing to how a node's weights were produced), plus one
  real-snapshot, stubbed-``shadow_weights`` integration pass confirming the
  three new JSON-line keys and the book document's two optional keys are
  wired end to end and absent at their defaults.

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
from evaluator import book_weights
from orchestrator import shadow as shadow_cli
from orchestrator._context import (
    DEFAULT_VOL_WINDOW_DAYS,
    EvaluationContext,
    compute_vols,
    load_evaluation_context,
    signal_sandbox,
)
from orchestrator._evaluate import (
    _END_OF_DAY,
    _drop_unpriced_symbols,
    _materialize_from_context,
    _score_rebalance_dates,
)
from orchestrator._shadow import ShadowWeights, shadow_weights
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0117_identity_trio")

USDM_PATH = Path(cost_model.__file__).with_name("binance_usdm.yaml")

_TS = pa.timestamp("us", tz="UTC")


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_shadow_construction_{revision}", path
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


# ===========================================================================
# Part 1 — orchestrator._shadow.shadow_weights: the config's own weighting
# ===========================================================================


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


def _write_futbars(staging: Path, symbol: str, day: dt.date, fut_close: float) -> None:
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "fut_close": [str(fut_close)],
                "fut_volume": ["1000.0"],
                "taker_buy_volume": ["400.0"],
                "quote_volume": ["100000.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_funding(staging: Path, symbol: str, day: dt.date) -> None:
    partition = staging / "funding" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "funding_rate_sum": ["0.0001"],
                "funding_rate_last": ["0.0001"],
                "n_settlements": pa.array([3], type=pa.int64()),
            }
        ),
        partition / "part-0.parquet",
    )


def _context(
    sealed_path: Path,
    tmp_path: Path,
    *,
    name: str,
    evaluation_date: dt.date,
    book: dict[str, Any] | None = None,
) -> EvaluationContext:
    document: dict[str, Any] = {
        "snapshot_mount": str(sealed_path),
        "evaluation_dates": [evaluation_date.isoformat()],
        "horizon": 1,
        "seed": 20261024,
        "epoch_id": "epoch-shadow-construction-test",
        "artifact_dir": str(tmp_path / f"artifacts-{name}"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
        "instrument": "perp",
    }
    if book is not None:
        document["book"] = book
    config_path = tmp_path / f"evaluation-{name}.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    environment = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": f"sqlite:///{tmp_path / f'{name}.db'}",
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "NULLIUS_COST_MODEL_PATH": str(USDM_PATH),
        "PATH": str(_bwrap_dir(tmp_path)),
    }
    context = load_evaluation_context(environment)
    assert context is not None
    return context


#: A hand-written momentum signal, the same trailing-window shape
#: ``test_shadow_weights.py``'s own ``MOMENTUM_SIGNAL_CODE`` takes. It reads
#: only the trailing ``LOOKBACK`` bars, so a symbol's full history length
#: (long for most, short for the late-listed one below) never changes its
#: score — only :func:`orchestrator._context.compute_vols`'s own coverage
#: rule cares about that.
LOOKBACK = 5
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
            first = float(series[-{LOOKBACK}]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


# -- World A: six symbols, one of them late-listed (too thin to carry a vol) --

SMALL_SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
#: Even, as every happy-path cross-section in this suite's own ancestor
#: (``test_shadow_weights.py``) is: an odd count always strands one symbol
#: exactly on the z-scored mean rank, in neither leg, for reasons that have
#: nothing to do with what any one of these tests means to exercise.
SMALL_MULTIPLIER = {"AAA": 0.4, "BBB": 0.6, "CCC": 0.9, "DDD": 1.2, "EEE": 1.5, "FFF": 1.9}
#: ``EEE`` is the late-listed symbol: it only carries
#: :data:`THIN_HISTORY_DAYS` of history, fewer than half of
#: :data:`~orchestrator._context.DEFAULT_VOL_WINDOW_DAYS` — too thin for
#: :func:`orchestrator._context.compute_vols` to measure a volatility, but
#: still enough (more than :data:`LOOKBACK`) for the signal itself to score
#: a real, non-zero momentum.
THIN_SYMBOL = "EEE"
THIN_HISTORY_DAYS = 10
#: Comfortably more than half of the default vol window, so every other
#: symbol's volatility is measured without question.
FULL_HISTORY_DAYS = (DEFAULT_VOL_WINDOW_DAYS // 2) + 5

LAST_DAY = dt.date(2027, 3, 1)
FULL_DAYS = tuple(
    LAST_DAY - dt.timedelta(days=offset) for offset in range(FULL_HISTORY_DAYS - 1, -1, -1)
)
THIN_DAYS = FULL_DAYS[-THIN_HISTORY_DAYS:]
#: One daily "benchmark" return per day after the first, varied and
#: deterministic (a sine wave, not hand-typed) — each symbol's own price
#: path is this series compounded at its own multiplier, so every symbol's
#: trailing realised volatility is strictly ordered by its multiplier.
_BENCH_RETURNS = tuple(0.02 * math.sin(offset * 0.7 + 1.0) for offset in range(len(FULL_DAYS) - 1))


def _price_path(multiplier: float) -> dict[dt.date, float]:
    prices = {FULL_DAYS[0]: 100.0}
    for offset, r in enumerate(_BENCH_RETURNS):
        prices[FULL_DAYS[offset + 1]] = prices[FULL_DAYS[offset]] * (1.0 + multiplier * r)
    return prices


SMALL_PRICES = {symbol: _price_path(mult) for symbol, mult in SMALL_MULTIPLIER.items()}


@pytest.fixture(scope="module")
def small_world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Six symbols; every one but :data:`THIN_SYMBOL` carries the full
    :data:`FULL_HISTORY_DAYS` of history, so only ``EEE`` is too thin for a
    volatility.
    """
    workdir = tmp_path_factory.mktemp("shadow-construction-small-world")
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol in SMALL_SYMBOLS:
        days = THIN_DAYS if symbol == THIN_SYMBOL else FULL_DAYS
        for day in days:
            price = SMALL_PRICES[symbol][day]
            _write_bars(staging, symbol, day, price)
            _write_futbars(staging, symbol, day, price)
            _write_funding(staging, symbol, day)
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2027, 3, 2, tzinfo=dt.UTC))
    return service, sealed


def _reference_day_scores(
    context: EvaluationContext, code: str, as_of: dt.date
) -> dict[str, float]:
    """The z-scored cross-section the real evaluation chain would compute —
    the same helper shape ``test_shadow_weights.py``'s own
    ``_reference_scores_and_betas`` takes, without the beta leg (this
    module's own book is never beta-neutral)."""
    executor = signal_sandbox(context)
    decision_time = dt.datetime.combine(as_of, _END_OF_DAY)
    from evaluator import execute_signal, resolve_window

    resolution = resolve_window(context.snapshot, decision_time)
    execution = execute_signal(
        resolution,
        code,
        seed=context.seed,
        rebalance_dates=[as_of],
        sandbox=executor,
        materialize=_materialize_from_context(context),
    )
    execution, _dropped = _drop_unpriced_symbols(execution, context)
    scores, _flat = _score_rebalance_dates(execution, "reference")
    return dict(scores[as_of])


# -- (a) default path: byte-identical to the unchanged "z" call ---------------


def test_default_weighting_calls_book_weights_exactly_as_before(
    small_world: Any, tmp_path: Path
) -> None:
    _service, sealed = small_world
    context = _context(sealed.path, tmp_path, name="default", evaluation_date=LAST_DAY)
    assert context.book.weighting == "z"

    result = shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    day_scores = _reference_day_scores(context, MOMENTUM_SIGNAL_CODE, LAST_DAY)
    expected = book_weights(day_scores, None)  # no weighting kw, no vols: today's call

    assert result.weights == expected  # exact equality: the untouched code path
    assert result.weighting == "z"
    assert result.n_vol_dropped == 0


def test_explicit_z_weighting_is_identical_to_the_absent_key(
    small_world: Any, tmp_path: Path
) -> None:
    _service, sealed = small_world
    implicit = _context(sealed.path, tmp_path, name="implicit-z", evaluation_date=LAST_DAY)
    explicit = _context(
        sealed.path, tmp_path, name="explicit-z", evaluation_date=LAST_DAY, book={"beta_neutral": False, "weighting": "z"}
    )

    implicit_result = shadow_weights(implicit, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)
    explicit_result = shadow_weights(explicit, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    assert explicit_result.weights == implicit_result.weights
    assert explicit_result.weighting == "z"
    assert explicit_result.n_vol_dropped == 0


# -- (b) inverse_vol: matches compute_vols directly, drops the thin symbol ----


def test_inverse_vol_weighting_matches_book_weights_with_computed_vols(
    small_world: Any, tmp_path: Path
) -> None:
    _service, sealed = small_world
    context = _context(
        sealed.path, tmp_path, name="inverse-vol", evaluation_date=LAST_DAY,
        book={"beta_neutral": False, "weighting": "inverse_vol"},
    )

    result = shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    day_scores = _reference_day_scores(context, MOMENTUM_SIGNAL_CODE, LAST_DAY)
    assert THIN_SYMBOL in day_scores  # it is scored...
    row_vols = compute_vols(context, {LAST_DAY: day_scores}).get(LAST_DAY, {})
    assert THIN_SYMBOL not in row_vols  # ...but too thin for a volatility

    priced_scores = {s: v for s, v in day_scores.items() if s in row_vols}
    expected = book_weights(priced_scores, None, vols=row_vols, weighting="inverse_vol")

    assert result.weights == pytest.approx(expected, abs=1e-12)
    assert THIN_SYMBOL not in result.weights
    assert result.weighting == "inverse_vol"
    assert result.n_vol_dropped == 1


# -- (c) short_tail / tail_decile: passed straight through, no vols ----------

#: A decile book needs at least ``10 * TAIL_DECILE_MIN_LEG`` = 20 scored
#: symbols (``evaluator._metrics.TAIL_DECILE_MIN_LEG`` is 2) — the small,
#: six-symbol world above is far too thin for it, so this world is its own,
#: wider cross-section. No per-name vol is needed (``vols`` is ignored under
#: both decile weightings), so every symbol carries just one day's lookback
#: history; only the ranking has to be distinct name to name.
WIDE_SYMBOL_COUNT = 24
WIDE_SYMBOLS = tuple(f"SYM{i:02d}USDT" for i in range(WIDE_SYMBOL_COUNT))
WIDE_FIRST_DAY = LAST_DAY - dt.timedelta(days=LOOKBACK)
WIDE_DAYS = tuple(WIDE_FIRST_DAY + dt.timedelta(days=offset) for offset in range(LOOKBACK + 1))
_WIDE_BENCH_RETURNS = tuple(0.01 * math.sin(offset * 0.9 + 0.3) for offset in range(LOOKBACK))


def _wide_price_path(multiplier: float) -> dict[dt.date, float]:
    prices = {WIDE_DAYS[0]: 100.0}
    for offset, r in enumerate(_WIDE_BENCH_RETURNS):
        prices[WIDE_DAYS[offset + 1]] = prices[WIDE_DAYS[offset]] * (1.0 + multiplier * r)
    return prices


WIDE_PRICES = {
    symbol: _wide_price_path(0.2 + 0.1 * index) for index, symbol in enumerate(WIDE_SYMBOLS)
}


@pytest.fixture(scope="module")
def wide_world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    workdir = tmp_path_factory.mktemp("shadow-construction-wide-world")
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol in WIDE_SYMBOLS:
        for day in WIDE_DAYS:
            price = WIDE_PRICES[symbol][day]
            _write_bars(staging, symbol, day, price)
            _write_futbars(staging, symbol, day, price)
            _write_funding(staging, symbol, day)
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2027, 3, 9, tzinfo=dt.UTC))
    return service, sealed


def test_short_tail_weighting_passes_straight_through_with_no_vols(
    wide_world: Any, tmp_path: Path
) -> None:
    _service, sealed = wide_world
    context = _context(
        sealed.path, tmp_path, name="short-tail", evaluation_date=LAST_DAY,
        book={"beta_neutral": False, "weighting": "short_tail"},
    )

    result = shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    day_scores = _reference_day_scores(context, MOMENTUM_SIGNAL_CODE, LAST_DAY)
    expected = book_weights(day_scores, None, weighting="short_tail")

    assert result.weights == pytest.approx(expected, abs=1e-12)
    assert result.weighting == "short_tail"
    assert result.n_vol_dropped == 0


# ===========================================================================
# Part 2 — orchestrator.shadow (the CLI): the cap and the node weighting
# ===========================================================================


# -- (d) --max-name-weight: _cap_name_weights as a pure function -------------


def test_cap_name_weights_clips_the_one_over_cap_name_and_renormalises(
) -> None:
    combined = {"BIG": 0.5, **{f"S{i:02d}": -1.0 / 60.0 for i in range(30)}}

    capped, n_capped = shadow_cli._cap_name_weights(combined, cap=0.05, gross=1.0)

    assert capped["BIG"] == pytest.approx(0.05, abs=1e-9)
    assert n_capped == 1
    gross = math.fsum(abs(value) for value in capped.values())
    assert gross == pytest.approx(1.0, abs=1e-12)
    expected_other = (1.0 - 0.05) / 30.0
    for i in range(30):
        value = capped[f"S{i:02d}"]
        assert abs(value) == pytest.approx(expected_other, abs=1e-9)
        assert abs(value) <= 0.05 + 1e-9


def test_cap_name_weights_refuses_a_cap_unmeetable_at_the_requested_gross() -> None:
    combined = {f"N{i:02d}": (0.025 if i % 2 == 0 else -0.025) for i in range(40)}

    with pytest.raises(shadow_cli.ShadowCliError) as excinfo:
        shadow_cli._cap_name_weights(combined, cap=0.001, gross=1.0)

    message = str(excinfo.value)
    assert "0.001" in message
    assert "1.0" in message
    assert "40" in message


def test_cap_name_weights_is_a_no_op_when_nothing_exceeds_the_cap() -> None:
    # The natural (post-rescale) book is 0.5/-0.5; a cap of 0.6 sits
    # strictly above that, so nothing is ever clipped — unlike a cap of
    # exactly 0.5, which would coincide with the rescaled value and count
    # as "at the cap" even though the clip step never fired.
    combined = {"AAA": 0.3, "BBB": -0.3}

    capped, n_capped = shadow_cli._cap_name_weights(combined, cap=0.6, gross=1.0)

    assert n_capped == 0
    assert capped == pytest.approx({"AAA": 0.5, "BBB": -0.5}, abs=1e-12)


def test_cap_name_weights_is_scale_free_and_exact_at_the_fixed_point() -> None:
    # The cap is a fraction of *gross*, so the input's own scale must not
    # matter: the gross-1 mean and the gross-100 mean (what an
    # inverse-vol-scaled book actually hands in) give the identical book.
    # The answer is exact, not geometric: A is fixed at the cap, and the
    # freed gross is water-filled over B, C, D in proportion to their
    # normalised weights (0.6 / 0.5 = 1.2).
    mean = {"A": 0.5, "B": 0.3, "C": -0.15, "D": -0.05}
    expected = {"A": 0.4, "B": 0.36, "C": -0.18, "D": -0.06}

    capped_at_one, n_one = shadow_cli._cap_name_weights(mean, cap=0.4, gross=1.0)
    capped_at_hundred, n_hundred = shadow_cli._cap_name_weights(
        {symbol: weight * 100.0 for symbol, weight in mean.items()},
        cap=0.4,
        gross=1.0,
    )

    assert capped_at_one == pytest.approx(expected, abs=1e-12)
    assert capped_at_hundred == pytest.approx(expected, abs=1e-12)
    assert n_one == 1
    assert n_hundred == 1


def test_cap_name_weights_water_fills_through_a_second_round() -> None:
    # Capping A frees gross that pushes B over the cap too, so a second
    # round fixes B and redistributes once more. The loop reaches the exact
    # fixed point (gross 1.0) rather than refusing a meetable cap.
    combined = {"A": 0.55, "B": 0.35, "C": 0.1}

    capped, n_capped = shadow_cli._cap_name_weights(combined, cap=0.4, gross=1.0)

    assert capped == pytest.approx({"A": 0.4, "B": 0.4, "C": 0.2}, abs=1e-12)
    assert n_capped == 2


# -- (e) --node-weighting inverse_vol: _node_book_sigma as a pure function ---


NODE_AS_OF = dt.date(2027, 6, 1)


def _alternating_returns_closes(
    days: int, *, pct: float, as_of: dt.date = NODE_AS_OF
) -> dict[dt.date, float]:
    """``days`` consecutive daily closes ending at ``as_of`` whose
    close-to-close returns alternate ``+pct``/``-pct`` — a population
    standard deviation of exactly ``pct`` whenever the count is even.
    """
    dates = tuple(
        as_of - dt.timedelta(days=offset) for offset in range(days - 1, -1, -1)
    )
    prices: dict[dt.date, float] = {dates[0]: 1.0}
    for index in range(1, len(dates)):
        sign = pct if index % 2 == 1 else -pct
        prices[dates[index]] = prices[dates[index - 1]] * (1.0 + sign)
    return prices


def test_node_book_sigma_two_nodes_at_one_and_two_percent_scale_two_to_one() -> None:
    closes_a = {"AAA": _alternating_returns_closes(shadow_cli._NODE_VOL_WINDOW_DAYS + 1, pct=0.01)}
    closes_b = {"BBB": _alternating_returns_closes(shadow_cli._NODE_VOL_WINDOW_DAYS + 1, pct=0.02)}

    sigma_a = shadow_cli._node_book_sigma({"AAA": 1.0}, closes_a, NODE_AS_OF, node_id="node-a")
    sigma_b = shadow_cli._node_book_sigma({"BBB": 1.0}, closes_b, NODE_AS_OF, node_id="node-b")

    assert sigma_a == pytest.approx(0.01, abs=1e-12)
    assert sigma_b == pytest.approx(0.02, abs=1e-12)
    # The scaled vector (1/sigma) is what --node-weighting inverse_vol
    # multiplies the node's own weights by, before the equal-weight mean —
    # the first node's carries exactly twice the second's.
    assert (1.0 / sigma_a) == pytest.approx(2.0 * (1.0 / sigma_b), rel=1e-12)


def test_node_book_sigma_refuses_a_node_with_ten_priced_dates() -> None:
    # 11 consecutive days of closes give exactly 10 close-to-close returns —
    # below shadow._MIN_NODE_VOL_PRICED_DATES (20).
    closes = {"CCC": _alternating_returns_closes(11, pct=0.01)}

    with pytest.raises(shadow_cli.ShadowCliError) as excinfo:
        shadow_cli._node_book_sigma({"CCC": 1.0}, closes, NODE_AS_OF, node_id="node-thin")

    message = str(excinfo.value)
    assert "node-thin" in message
    assert "10" in message


def test_node_book_sigma_refuses_a_node_with_zero_variance() -> None:
    dates = tuple(
        NODE_AS_OF - dt.timedelta(days=offset)
        for offset in range(shadow_cli._NODE_VOL_WINDOW_DAYS, -1, -1)
    )
    closes = {"DDD": {day: 100.0 for day in dates}}  # flat: every return is 0

    with pytest.raises(shadow_cli.ShadowCliError) as excinfo:
        shadow_cli._node_book_sigma({"DDD": 1.0}, closes, NODE_AS_OF, node_id="node-flat")

    assert "node-flat" in str(excinfo.value)


def test_node_book_returns_drops_a_date_any_weighted_symbol_lacks() -> None:
    dates = tuple(
        NODE_AS_OF - dt.timedelta(days=offset)
        for offset in range(shadow_cli._NODE_VOL_WINDOW_DAYS, -1, -1)
    )
    full = {day: 100.0 + index for index, day in enumerate(dates)}
    # BBB is missing its very last date's close: the pair (last, last-1)
    # cannot price a return for the last date, and the whole day is dropped
    # from the book's own return series (never priced on BBB's weight alone).
    partial = dict(full)
    del partial[dates[-1]]

    returns = shadow_cli._node_book_returns(
        {"AAA": 0.5, "BBB": 0.5}, {"AAA": full, "BBB": partial}, NODE_AS_OF
    )

    assert dates[-1] not in returns
    assert len(returns) == shadow_cli._NODE_VOL_WINDOW_DAYS - 1


# -- _mean_weights / _rescale_to_gross / _combine compose unchanged ----------


def test_mean_weights_then_rescale_to_gross_equals_combine() -> None:
    nodes = [
        {"AAA": 0.4, "BBB": -0.3, "CCC": 0.2, "DDD": -0.1},
        {"AAA": 0.2, "BBB": -0.1, "CCC": 0.1, "DDD": -0.2},
    ]

    via_combine = shadow_cli._combine(nodes, gross=1.0)
    via_parts = shadow_cli._rescale_to_gross(shadow_cli._mean_weights(nodes), gross=1.0)

    assert via_combine == via_parts


# -- (f) the CLI end to end: the new keys, present only when configured -----


CLI_DAY = dt.date(2027, 9, 1)
CLI_VOL_SYMBOLS_DAYS = shadow_cli._NODE_VOL_WINDOW_DAYS + 1

CONTRACTS_DOCUMENT = {
    "code": 0,
    "msg": "",
    "data": [
        {"symbol": "AAA-USDT", "status": 1, "apiStateOpen": "true"},
        {"symbol": "BBB-USDT", "status": 1, "apiStateOpen": "true"},
        {"symbol": "CCC-USDT", "status": 1, "apiStateOpen": "true"},
    ],
}

CAMPAIGN_ID = "campaign-construction"
NODE_A_CODE = "# shadow construction test signal A\n"
NODE_B_CODE = "# shadow construction test signal B\n"
#: Each node's book is one single name — unrealistic as a dollar-neutral
#: book, but the stub never runs a real signal, and a single-name vector
#: makes the per-node volatility (and the resulting node-weighting ratio)
#: exact and easy to hand-verify.
WEIGHTS_BY_CODE = {
    NODE_A_CODE: {"AAAUSDT": 1.0},
    NODE_B_CODE: {"BBBUSDT": 1.0},
}


def _cli_code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _cli_stub_shadow_weights(
    context: Any, code: str, *, as_of: dt.date, allowed_symbols: Any = None
) -> ShadowWeights:
    raw = WEIGHTS_BY_CODE[code]
    if allowed_symbols is not None:
        raw = {s: w for s, w in raw.items() if s in allowed_symbols}
    return ShadowWeights(
        as_of=as_of,
        weights=dict(raw),
        code_hash=_cli_code_hash(code),
        n_scored=len(raw),
        n_dropped_unpriced=0,
        n_dropped_unmapped=0,
        book_beta=None,
    )


@pytest.fixture(scope="module")
def cli_sealed_snapshot(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """``AAA`` alternates +-1%% returns, ``BBB`` +-2%% — the same precise
    1%/2% trailing-vol control :func:`test_node_book_sigma_two_nodes_at_one_and_two_percent_scale_two_to_one`
    already pins directly, reused here end to end through ``main()``.
    ``BTCUSDT`` carries exactly one day (:data:`CLI_DAY`), the grid
    benchmark's own minimum, so ``--grid-anchor`` can name the decision date
    outright with no grid arithmetic to hand-check.
    """
    lake_root = tmp_path_factory.mktemp("shadow-construction-cli-lake") / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"

    one_pct = _alternating_returns_closes(CLI_VOL_SYMBOLS_DAYS, pct=0.01, as_of=CLI_DAY)
    two_pct = _alternating_returns_closes(CLI_VOL_SYMBOLS_DAYS, pct=0.02, as_of=CLI_DAY)
    for day, price in one_pct.items():
        _write_bars(staging, "AAAUSDT", day, price)
        _write_futbars(staging, "AAAUSDT", day, price)
    for day, price in two_pct.items():
        _write_bars(staging, "BBBUSDT", day, price)
        _write_futbars(staging, "BBBUSDT", day, price)
    _write_bars(staging, "BTCUSDT", CLI_DAY, 50000.0)
    _write_futbars(staging, "BTCUSDT", CLI_DAY, 50000.0)
    # A third symbol, present only to give the per-name cap test a book of
    # three names instead of two — a cap below ``gross / n`` names can never
    # be met (see _cap_name_weights' own docstring), so demonstrating a cap
    # that actually binds *and* is feasible needs at least one name that
    # stays under it on its own.
    _write_bars(staging, "CCCUSDT", CLI_DAY, 10.0)
    _write_futbars(staging, "CCCUSDT", CLI_DAY, 10.0)

    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2027, 9, 2, tzinfo=dt.UTC))


@dataclass
class _World:
    snapshot_path: Path
    contracts_path: Path
    database_url: str
    artifact_root: Path
    env: dict[str, str]


def _build_world(tmp_path: Path, sealed_snapshot: Any) -> _World:
    database_url = f"sqlite:///{tmp_path / 'shadow-construction.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps(CONTRACTS_DOCUMENT), encoding="utf-8")

    config_document = {
        "snapshot_mount": str(tmp_path / "unused-snapshot-placeholder"),
        "evaluation_dates": ["2020-01-01"],
        "horizon": 1,
        "seed": 20261024,
        "epoch_id": "epoch-shadow-construction-cli-test",
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


def _insert_node(world: _World, *, node_id: str, code_hash: str) -> None:
    with closing(sqlite3.connect(_sqlite_path_of(world.database_url))) as connection:
        connection.execute(
            "INSERT INTO node "
            "(id, campaign_id, theme_root, depth, code_hash, artifact_uri) "
            "VALUES (?, ?, 'shadow-construction-test', 0, ?, 'artifact://shadow-construction-test')",
            (node_id, CAMPAIGN_ID, code_hash),
        )
        connection.commit()


def _node(world: _World, *, node_id: str, code: str) -> None:
    _insert_node(world, node_id=node_id, code_hash=_cli_code_hash(code))
    directory = world.artifact_root / CAMPAIGN_ID / node_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "code.py").write_text(code, encoding="utf-8")


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


def test_default_run_has_no_optional_book_keys_and_default_json_keys(
    tmp_path: Path, cli_sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, cli_sealed_snapshot)
    _node(world, node_id="node-a", code=NODE_A_CODE)
    _node(world, node_id="node-b", code=NODE_B_CODE)
    monkeypatch.setattr(shadow_cli, "shadow_weights", _cli_stub_shadow_weights)

    out = tmp_path / "book.json"
    printed: list[str] = []
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(world.snapshot_path),
            "--node", f"{CAMPAIGN_ID}/node-a",
            "--node", f"{CAMPAIGN_ID}/node-b",
            "--out", str(out),
            "--contracts", str(world.contracts_path),
            "--grid-anchor", CLI_DAY.isoformat(),
        ],
        env=world.env,
        emit=printed.append,
    )

    assert exit_code == shadow_cli.EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    assert set(document) == BOOK_KEYS  # no "construction", no "max_name_weight"

    result = json.loads(printed[0])
    assert result["max_name_weight"] is None
    assert result["node_weighting"] == "equal"
    assert result["n_capped"] == 0
    # Equal weighting: AAA and BBB, equal-weight mean, 50/50.
    assert document["weights"]["AAA-USDT"] == pytest.approx(
        document["weights"]["BBB-USDT"], abs=1e-9
    )


#: A cap below ``gross / n_names`` can never be met (``_cap_name_weights``
#: own docstring), so a two-name book has no feasible cap below 0.5 at
#: gross 1 — demonstrating a real, binding *and* feasible cap needs a third
#: name that is already under the cap on its own, to absorb the first
#: name's excess once it is clipped and the book is renormalised.
_CAP_TEST_WEIGHTS_BY_CODE = {
    NODE_A_CODE: {"AAAUSDT": 1.0},
    NODE_B_CODE: {"BBBUSDT": -0.5, "CCCUSDT": -0.5},
}


def _cap_test_stub_shadow_weights(
    context: Any, code: str, *, as_of: dt.date, allowed_symbols: Any = None
) -> ShadowWeights:
    raw = _CAP_TEST_WEIGHTS_BY_CODE[code]
    if allowed_symbols is not None:
        raw = {s: w for s, w in raw.items() if s in allowed_symbols}
    return ShadowWeights(
        as_of=as_of,
        weights=dict(raw),
        code_hash=_cli_code_hash(code),
        n_scored=len(raw),
        n_dropped_unpriced=0,
        n_dropped_unmapped=0,
        book_beta=None,
    )


def test_max_name_weight_caps_the_combined_book_end_to_end(
    tmp_path: Path, cli_sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path, cli_sealed_snapshot)
    _node(world, node_id="node-a", code=NODE_A_CODE)
    _node(world, node_id="node-b", code=NODE_B_CODE)
    monkeypatch.setattr(shadow_cli, "shadow_weights", _cap_test_stub_shadow_weights)

    out = tmp_path / "book.json"
    printed: list[str] = []
    cap = 0.35
    exit_code = shadow_cli.main(
        [
            "--snapshot", str(world.snapshot_path),
            "--node", f"{CAMPAIGN_ID}/node-a",
            "--node", f"{CAMPAIGN_ID}/node-b",
            "--out", str(out),
            "--contracts", str(world.contracts_path),
            "--grid-anchor", CLI_DAY.isoformat(),
            "--max-name-weight", str(cap),
        ],
        env=world.env,
        emit=printed.append,
    )

    assert exit_code == shadow_cli.EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["max_name_weight"] == pytest.approx(cap, abs=1e-12)
    assert "construction" not in document  # weighting stayed "z"
    for weight in document["weights"].values():
        assert abs(weight) <= cap + 1e-9

    # Exactly the same computation, run directly against the nodes' raw
    # weights (the stub's own dicts), proves main()'s own pipeline — mean,
    # cap, symbol-map, write — reaches the identical book the production
    # function would build on its own.
    expected_combined, expected_n_capped = shadow_cli._cap_name_weights(
        shadow_cli._mean_weights(
            [_CAP_TEST_WEIGHTS_BY_CODE[NODE_A_CODE], _CAP_TEST_WEIGHTS_BY_CODE[NODE_B_CODE]]
        ),
        cap=cap,
        gross=1.0,
    )
    expected_bingx = {
        shadow_cli._map_to_bingx(symbol, {"AAA-USDT", "BBB-USDT", "CCC-USDT"}): weight
        for symbol, weight in expected_combined.items()
    }
    assert document["weights"] == pytest.approx(expected_bingx, abs=1e-12)

    result = json.loads(printed[0])
    assert result["max_name_weight"] == pytest.approx(cap, abs=1e-12)
    assert result["node_weighting"] == "equal"
    assert result["n_capped"] == expected_n_capped
    assert result["n_capped"] >= 1
    assert result["gross"] == pytest.approx(1.0, abs=1e-9)


def test_node_weighting_inverse_vol_scales_each_node_before_the_mean(
    tmp_path: Path, cli_sealed_snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    equal_dir = tmp_path / "equal"
    equal_dir.mkdir()
    inverse_dir = tmp_path / "inverse"
    inverse_dir.mkdir()
    world_equal = _build_world(equal_dir, cli_sealed_snapshot)
    world_inverse = _build_world(inverse_dir, cli_sealed_snapshot)
    for world in (world_equal, world_inverse):
        _node(world, node_id="node-a", code=NODE_A_CODE)
        _node(world, node_id="node-b", code=NODE_B_CODE)
    monkeypatch.setattr(shadow_cli, "shadow_weights", _cli_stub_shadow_weights)

    def _run(world: _World, out: Path, node_weighting: str) -> dict[str, Any]:
        printed: list[str] = []
        exit_code = shadow_cli.main(
            [
                "--snapshot", str(world.snapshot_path),
                "--node", f"{CAMPAIGN_ID}/node-a",
                "--node", f"{CAMPAIGN_ID}/node-b",
                "--out", str(out),
                "--contracts", str(world.contracts_path),
                "--grid-anchor", CLI_DAY.isoformat(),
                "--node-weighting", node_weighting,
            ],
            env=world.env,
            emit=printed.append,
        )
        assert exit_code == shadow_cli.EXIT_OK
        return json.loads(out.read_text(encoding="utf-8"))

    equal_document = _run(world_equal, tmp_path / "equal-book.json", "equal")
    inverse_document = _run(world_inverse, tmp_path / "inverse-book.json", "inverse_vol")

    # Equal weighting: both nodes contribute alike, AAA and BBB tie.
    assert equal_document["weights"]["AAA-USDT"] == pytest.approx(
        equal_document["weights"]["BBB-USDT"], abs=1e-9
    )
    # Inverse-vol: AAA's node (sigma 1%) outweighs BBB's (sigma 2%) 2 to 1 —
    # the same ratio test_node_book_sigma_two_nodes_at_one_and_two_percent_scale_two_to_one
    # pins directly on the underlying sigmas.
    assert inverse_document["weights"]["AAA-USDT"] == pytest.approx(
        2.0 * inverse_document["weights"]["BBB-USDT"], rel=1e-9
    )
