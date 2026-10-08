"""Tripwire false positives on real data: runs the live step-10 tripwires
(orchestrator._tripwire_step.run_tripwires) on three honest signals (20d
momentum, 5d reversal, 20d vol) over the real snapshot. None should be
rejected.

Usage: uv run --all-packages python -I deploy/campaign/tripwire_fp_check.py \
    ~/.config/nullius/campaign/evaluation-config.json 0
"""
import datetime as dt
import glob
import json
import math
import statistics
import sys

import polars as pl
from nulloracle.blockpermute import block_permute_cross_section

cfg = json.load(open(sys.argv[1]))
seeds = int(sys.argv[2])
files = glob.glob(f"{cfg['snapshot_mount']}/bars/symbol=*/date=*/part-0.parquet")
bars = pl.concat([pl.read_parquet(f) for f in files]).with_columns(
    pl.col("close").cast(pl.Float64), pl.col("volume").cast(pl.Float64),
    pl.col("open_time").dt.date().alias("day"),
)
close: dict[str, dict[dt.date, float]] = {}
for sym, day, c in bars.select("symbol", "day", "close").iter_rows():
    close.setdefault(sym, {})[day] = c
eval_days = [dt.date.fromisoformat(d) for d in cfg["evaluation_dates"]]
one = dt.timedelta(days=1)


def back(sym, day, n):
    return close[sym].get(day - n * one)


def signals(day):
    out = {"mom20": {}, "rev5": {}, "vol20": {}}
    for sym, series in close.items():
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
    return out


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


panel = {}
sigs = {}
for day in eval_days:
    row = {}
    for sym, series in close.items():
        c0, c1 = series.get(day), series.get(day + one)
        if c0 and c1:
            row[sym] = c1 / c0 - 1
    panel[day] = row
    sigs[day] = signals(day)


def tstat(target):
    out = {}
    for name in ("mom20", "rev5", "vol20"):
        ics = []
        for day in eval_days:
            s, r = sigs[day][name], target.get(day, {})
            common = sorted(set(s) & set(r))
            if len(common) < 5:
                continue
            ic = spearman([s[x] for x in common], [r[x] for x in common])
            if ic is not None:
                ics.append(ic)
        m, sd = statistics.fmean(ics), statistics.pstdev(ics)
        out[name] = m / (sd / math.sqrt(len(ics)))
    return out



from orchestrator._tripwire_step import run_tripwires


def zscores(row):
    keys = sorted(row)
    vals = [row[k] for k in keys]
    r = ranks(vals)
    m = statistics.fmean(r)
    sd = statistics.pstdev(r) or 1.0
    return {k: (x - m) / sd for k, x in zip(keys, r)}


for name in ("mom20", "rev5", "vol20"):
    scores = {}
    for day in eval_days:
        row = {s: v for s, v in sigs[day][name].items() if s in panel[day]}
        if len(row) >= 5:
            scores[day] = zscores(row)
    targets = {1: {d: {s: panel[d][s] for s in scores[d]} for d in scores}}
    out = run_tripwires(scores, targets, node_id="00000000-0000-4000-8000-0000000000%02d" % len(name))
    print(name, "failed", out.failed, "perturb", out.perturb_stability)
