"""bug_spec_null_carry_leak.xml, bug 3 — the null-validity check tests the
chain's own target.

``deploy/campaign/null_power_check.py`` used to build its panel as the bare
1-day price return off the bars closes and test only mom20/rev5/vol20
against it, so it could not see a bias in the post-cost target the chain
actually permutes: under the perp instrument that target is the *funded*
return, whose carry (bug 1) once rode a null's derangement unpermuted and
biased every funding-driven signal's null upward while this check reported
"null valid at horizon 5".

The script now builds its panel through
``orchestrator._targets.snapshot_forward_returns`` at the config's horizon —
the same series the chain permutes — and adds a fourth probe,
``funding_rank``, the trailing 20-day sum of ``funding_rate_sum`` per symbol
sign-flipped. These tests run the script as a subprocess over sealed
scratch snapshots, the way its own docstring invokes it. Every market here
is built so the property under test is the only source of the behaviour
asserted:

* the perp market gives every symbol small independent price noise beside a
  persistent per-symbol funding rate whose carry dominates the funded
  forward return's cross-section — so ``funding_rank`` scores a real IC t
  far outside anything a bare price panel could produce (the probe is
  unrelated noise against prices alone, |t| ~ 1, and > 3 here on the frozen
  draw) only if the funding carry actually reached the panel. Its exit code
  is not asserted: a synthetic market this static has honestly fat null
  tails (the block derangement reuses one mapping per 20-date block, and a
  persistent cross-section makes every date's IC nearly that block's one
  value), so the gate firing there measures the fixture, not the script —
  the gate's own exits are pinned by the two markets below;
* the spot market carries bars alone — ``funding_rank`` must be skipped
  with a one-line note, and the three price probes' nulls must clear the
  thresholds, exiting 0;
* the gate market keeps three rebalance dates, where a null t over three
  ICs is fat-tailed by construction, so the threshold gate must fire and
  exit 1.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "deploy" / "campaign" / "null_power_check.py"

SYMBOLS = tuple(f"SYM{i:02d}" for i in range(10))
START = dt.date(2026, 6, 1)
UTC = dt.UTC
ONE = dt.timedelta(days=1)

#: Lookback the probes need before the first rebalance date: mom20 reads a
#: close 20 days back, vol20 needs 20 daily returns, funding_rank sums a
#: trailing 20-day funding window.
HISTORY = 21


def _write_row(
    lake_root: Path,
    stream: str,
    symbol: str,
    day: dt.date,
    fields: Mapping[str, object],
) -> None:
    """One symbol-day row in ``stream``, in the staging shape
    :mod:`nullius_ingest.derivs_backfill` writes: a UTC-midnight ``date``
    (bars' ``open_time``) beside string-spelled values.
    """
    partition = lake_root / "staging" / stream / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    instant = dt.datetime(day.year, day.month, day.day, tzinfo=UTC)
    columns: dict[str, object] = {
        "symbol": [symbol], **{key: [value] for key, value in fields.items()}
    }
    if "open_time" in fields:
        columns["open_time"] = pa.array([instant], type=pa.timestamp("us", tz="UTC"))
    else:
        columns["date"] = pa.array([instant], type=pa.timestamp("us", tz="UTC"))
    pq.write_table(pa.table(columns), partition / "part-0.parquet")


def _seal(lake_root: Path) -> Path:
    sealed = SnapshotService(lake_root).seal(
        sealed_at=dt.datetime(2026, 10, 21, tzinfo=UTC)
    )
    return Path(sealed.path)


def _write_config(
    tmp_path: Path, mount: Path, eval_days: Sequence[dt.date], horizon: int,
    instrument: str | None,
) -> Path:
    document = {
        "snapshot_mount": str(mount),
        "evaluation_dates": [day.isoformat() for day in eval_days],
        "horizon": horizon,
    }
    if instrument is not None:
        document["instrument"] = instrument
    path = tmp_path / f"evaluation-config-{instrument or 'spot'}-{horizon}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _run(config: Path, seeds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(config), str(seeds)],
        capture_output=True,
        check=False,
        text=True,
        timeout=300,
    )


def _perp_market(
    lake_root: Path, eval_days: Sequence[dt.date], *, noise: float
) -> None:
    """futbars and funding rows: persistent per-symbol funding rates beside
    independent per-symbol price returns of amplitude ``noise``.

    With ``noise`` small the funded forward return's cross-section is
    dominated by the carry (at ``noise=0.001`` the carry explains ~97% of
    its variance), so a ``funding_rank`` probe scores a large real IC t
    against the funded panel and nothing against a bare price panel. With
    ``noise`` large the market is an ordinary unrelated-cross-section one.
    """
    rng = random.Random(11)
    span = (max(eval_days) - START).days + 3
    rates = [(i - (len(SYMBOLS) - 1) / 2) * 0.0008 for i in range(len(SYMBOLS))]
    closes = [[100.0 * (1.0 + 0.1 * rng.random())] for _ in SYMBOLS]
    for column in closes:
        for day_index in range(1, span):
            column.append(column[-1] * (1.0 + rng.uniform(-noise, noise)))
    for index, symbol in enumerate(SYMBOLS):
        for day_index in range(span):
            day = START + day_index * ONE
            price = format(closes[index][day_index], ".8f")
            _write_row(lake_root, "futbars", symbol, day,
                       {"fut_close": price, "fut_volume": "1.0",
                        "taker_buy_volume": "0.5", "quote_volume": "100.0"})
            _write_row(lake_root, "funding", symbol, day,
                       {"funding_rate_sum": format(rates[index], "f"),
                        "funding_rate_last": format(rates[index], "f"),
                        "n_settlements": 1})


def _spot_market(lake_root: Path, eval_days: Sequence[dt.date]) -> None:
    """Bars alone, with independent per-symbol price noise — the spot
    default's own snapshot."""
    rng = random.Random(37)
    span = (max(eval_days) - START).days + 2
    closes = [[100.0 * (1.0 + 0.1 * rng.random())] for _ in SYMBOLS]
    for column in closes:
        for day_index in range(1, span):
            column.append(column[-1] * (1.0 + rng.uniform(-0.02, 0.02)))
    for index, symbol in enumerate(SYMBOLS):
        for day_index in range(span):
            day = START + day_index * ONE
            _write_row(lake_root, "bars", symbol, day,
                       {"open_time": day.isoformat(),
                        "close": format(closes[index][day_index], ".8f"),
                        "volume": "1.0"})


def _daily(count: int) -> list[dt.date]:
    return [START + (HISTORY + step) * ONE for step in range(count)]


def test_perp_panel_is_the_funded_return_and_tests_funding_rank(
    tmp_path: Path, lake_root: Path
) -> None:
    eval_days = _daily(30)
    _perp_market(lake_root, eval_days, noise=0.001)
    config = _write_config(tmp_path, _seal(lake_root), eval_days, 2, "perp")

    result = _run(config, 40)

    # Exit 0 or 1 — the script must run to completion over the perp snapshot
    # and report every probe, but this market's cross-section is deliberately
    # static (the carry is the whole signal), which makes its null t honestly
    # fat-tailed (see the module docstring), so the gate may or may not fire;
    # the gate's exits are pinned by the spot and fat-tail markets below.
    assert result.returncode in (0, 1), result.stdout + result.stderr
    lines = {line.split()[0]: line for line in result.stdout.splitlines() if line}
    assert set(lines) >= {"mom20", "rev5", "vol20", "funding_rank"}
    for field in ("real t", "null t mean", "sd", "P(t>1.96)", "P(|t|>1.96)"):
        assert field in lines["funding_rank"], lines["funding_rank"]
    # The carry dominates this market's funded cross-section, so a large
    # real t is evidence the panel carries the funding carry — against a
    # bare price panel the probe is unrelated noise (|t| ~ 1).
    real_t = re.search(r"real t (-?[\d.]+)", lines["funding_rank"])
    assert real_t is not None and float(real_t.group(1)) > 3.0


def test_spot_config_skips_funding_rank_with_a_note(
    tmp_path: Path, lake_root: Path
) -> None:
    eval_days = _daily(30)
    _spot_market(lake_root, eval_days)
    config = _write_config(tmp_path, _seal(lake_root), eval_days, 1, None)

    result = _run(config, 40)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "funding_rank skipped" in result.stdout
    stats_lines = [
        line for line in result.stdout.splitlines() if "null t mean" in line
    ]
    assert {line.split()[0] for line in stats_lines} == {"mom20", "rev5", "vol20"}


def test_threshold_gate_exits_one_when_null_tails_are_fat(
    tmp_path: Path, lake_root: Path
) -> None:
    eval_days = _daily(3)
    _perp_market(lake_root, eval_days, noise=0.02)
    config = _write_config(tmp_path, _seal(lake_root), eval_days, 2, "perp")

    result = _run(config, 40)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "null check failed" in result.stdout
