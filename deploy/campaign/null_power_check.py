"""Null validity on real data: IC t-stats of simple signals (20d momentum,
5d reversal, 20d vol, and under the perp instrument a 20d funding-rank
construct) against the live block-permuted target, over many seeds.
Under a valid null they are ~N(0,1), with P(|t|>1.96) near 0.05.

The panel is the series the chain itself permutes, built through
orchestrator._targets.snapshot_forward_returns at the config's horizon and
narrowed to the config's rebalance grid (the same narrowing
grid_forward_returns gives the live target route): the close-to-close
forward return which, under instrument "perp", is the *funded* return —
price return minus the funding carry over the holding window. A bare price
panel was insufficient for exactly that carry: bug_spec_null_carry_leak bug
1 found the carry riding a planted null's derangement unpermuted, biasing
every funding-driven signal's null upward to +1.2..+1.8, while this check
— permuting only the price return — reported the null valid. The
funding_rank probe (trailing 20-day sum of funding_rate_sum, sign-flipped
so high funding ranks low, the funding-crowding theme's construct) exists
because a carry that big needs a signal built from it; it is skipped, with
one line saying so, when the instrument is not perp or the snapshot sealed
no funding rows.

Exits 0 when every tested signal's null t mean is within +-0.3 and its
P(|t|>1.96) is at most 0.10; exits 1 otherwise, naming each signal that
broke a threshold.

Usage: uv run --all-packages python -I deploy/campaign/null_power_check.py \
    ~/.config/nullius/campaign/evaluation-config.json 300
"""
import datetime as dt
import glob
import json
import math
import os
import statistics
import sys
from types import SimpleNamespace

import polars as pl
from nulloracle.blockpermute import block_permute_cross_section
from orchestrator._targets import snapshot_forward_returns

with open(sys.argv[1], encoding="utf-8") as handle:
    cfg = json.load(handle)
seeds = int(sys.argv[2])
mount = cfg["snapshot_mount"]
eval_days = sorted(dt.date.fromisoformat(d) for d in cfg["evaluation_dates"])
horizon = int(cfg["horizon"])
instrument = cfg.get("instrument", "spot")
one = dt.timedelta(days=1)


def stream(name: str, cols: list[str]) -> pl.DataFrame:
    files = glob.glob(f"{mount}/{name}/symbol=*/date=*/part-0.parquet")
    if not files:
        return pl.DataFrame()
    frames = []
    for f in files:
        sym = f.split("symbol=")[1].split(os.sep)[0]
        frames.append(pl.read_parquet(f).with_columns(pl.lit(sym).alias("symbol")))
    df = pl.concat(frames, how="diagonal_relaxed")
    # bars carry an open_time timestamp; the derivative streams carry a date.
    day = (pl.col("open_time").dt.date() if "open_time" in df.columns
           else pl.col("date").cast(pl.Utf8).str.slice(0, 10).str.to_date())
    return df.with_columns(
        [pl.col(c).cast(pl.Float64) for c in cols] + [day.alias("day")]
    )


def wide(df: pl.DataFrame, col: str) -> dict[str, dict[dt.date, float]]:
    out: dict[str, dict[dt.date, float]] = {}
    for sym, day, v in df.select("symbol", "day", col).iter_rows():
        if v is not None and math.isfinite(v):
            out.setdefault(sym, {})[day] = v
    return out


# The context's own closes and funding — the same stream choice
# orchestrator._context.load_evaluation_context makes: futbars' fut_close
# and the funding carry under "perp", bars' close and no funding otherwise.
if instrument == "perp":
    closes = wide(stream("futbars", ["fut_close"]), "fut_close")
    funding = wide(stream("funding", ["funding_rate_sum"]), "funding_rate_sum")
else:
    closes = wide(stream("bars", ["close"]), "close")
    funding = {}

# The panel the chain permutes: the target seam's own answer on the grid.
context = SimpleNamespace(
    closes=closes, horizon=horizon, instrument=instrument, funding=funding or None
)
served = snapshot_forward_returns(context)(SimpleNamespace())
panel = {day: served[day] for day in eval_days if day in served}


def back(sym, day, n):
    return closes[sym].get(day - n * one)


def signals(day):
    out = {name: {} for name in names}
    for sym, series in closes.items():
        c0, c20, c5 = series.get(day), back(sym, day, 20), back(sym, day, 5)
        if None in (c0, c20, c5):
            continue
        rets = [series.get(day - k * one) / series.get(day - (k + 1) * one) - 1
                for k in range(20)
                if series.get(day - k * one) and series.get(day - (k + 1) * one)]
        if len(rets) < 15:
            continue
        out["mom20"][sym] = c0 / c20 - 1
        out["rev5"][sym] = -(c0 / c5 - 1)
        out["vol20"][sym] = statistics.pstdev(rets)
        if sym in funding:
            window = [funding[sym].get(day - k * one) for k in range(20)]
            if None not in window:
                out["funding_rank"][sym] = -sum(window)
    return out


names = ("mom20", "rev5", "vol20")
if instrument == "perp" and funding:
    names = names + ("funding_rank",)
else:
    print("funding_rank skipped:", "instrument is not perp" if instrument != "perp"
          else "the snapshot sealed no funding rows")
sigs = {day: signals(day) for day in eval_days}


def ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    r = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def tstat(target):
    out = {}
    for name in names:
        ics = []
        for day in eval_days:
            s, r = sigs[day][name], target.get(day, {})
            common = sorted(set(s) & set(r))
            if len(common) < 5:
                continue
            ic = spearman([s[x] for x in common], [r[x] for x in common])
            if ic is not None:
                ics.append(ic)
        if len(ics) < 2:
            out[name] = None
            continue
        sd = statistics.pstdev(ics)
        out[name] = statistics.fmean(ics) / (sd / math.sqrt(len(ics))) if sd else float("nan")
    return out


real = tstat(panel)
print("real", {k: (round(v, 2) if v is not None else None) for k, v in real.items()})
draws = {name: [] for name in names}
for seed in range(seeds):
    t = tstat(block_permute_cross_section(panel, seed=seed + 1, block_days=20))
    for k, v in t.items():
        if v is not None:
            draws[k].append(v)
failed = []
for name in names:
    v = draws[name]
    if not v or real[name] is None:
        print(name, "no computable dates")
        continue
    mean, sd = statistics.fmean(v), statistics.pstdev(v)
    p_one = sum(x > 1.96 for x in v) / len(v)
    p_two = sum(abs(x) > 1.96 for x in v) / len(v)
    real_t = "nan" if real[name] != real[name] else round(real[name], 2)
    print(name, "real t", real_t, "null t mean", round(mean, 2), "sd", round(sd, 2),
          "P(t>1.96)", round(p_one, 3), "P(|t|>1.96)", round(p_two, 3))
    if abs(mean) > 0.3:
        failed.append(f"{name} null t mean {mean:.2f} outside +-0.3")
    if p_two > 0.10:
        failed.append(f"{name} P(|t|>1.96) {p_two:.3f} above 0.10")
for reason in failed:
    print("null check failed:", reason)
sys.exit(1 if failed else 0)
