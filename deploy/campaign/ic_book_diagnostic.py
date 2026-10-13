"""Why do positive-IC signals make losing books? An in-sample diagnostic.

The composite M2 test (docs/preregistration/2026-10-13-m2-composite.RESULT.md)
found 87% of nodes with IC > 0, yet a median *gross* IR t of -0.33. This script
rebuilds archetype v2 signals host-side and scores each one under several book
constructions, so the IC-to-book gap can be attributed. It uses the config's
in-sample ``evaluation_dates`` only (never ``oos_dates``), so it spends no OOS
look. No LLM is called.

Books, all dollar-neutral with gross exposure 1:
  zbook    w = z / sum|z|               (the research evaluator's book today)
  zwins    zbook on returns clipped to the date's 2nd-98th percentile
           (how much of the result is tails)
  invvol   w ∝ z / sigma_60d, renormalised (risk-scaled, like book F303)
  tercile  +1/n on the top third, -1/n on the bottom third
  betaneu  zbook with the legs rescaled so the book's 60d BTC beta is 0
           (gross still 1): tests whether market beta, not the signal, is
           what separates IC from book IR
  voltgt   zbook scaled ex-ante by 1 / (the trailing DISP_WINDOW-day (default 60) mean cross-sectional
           stdev of daily returns): a volatility-targeted book; tests whether
           high-dispersion dates swamping the book's variance is the gap
  bnvt     betaneu, also volatility-targeted
  resid    zbook on residual returns r - beta*r_BTC (what a BTC-hedged book
           would earn before hedge costs)

Also reported: the long and short legs' mean excess return over the
cross-sectional mean, and the net IR t at 10 bps x traded notional.

Usage: uv run --all-packages python -I deploy/campaign/ic_book_diagnostic.py \
    ~/.config/nullius/campaign/evaluation-config-archive-derivs.json [horizon]
"""
import datetime as dt
import glob
import json
import math
import os
import statistics
import sys

import polars as pl

cfg = json.load(open(sys.argv[1]))
H = int(sys.argv[2]) if len(sys.argv) > 2 else int(cfg.get("horizon", 10))
FEE = 0.001
mount = cfg["snapshot_mount"]
days = sorted(dt.date.fromisoformat(d) for d in cfg["evaluation_dates"])


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


bars = stream("bars", ["close", "volume"])
fund = stream("funding", ["funding_rate_sum"])

# Wide daily panels, one column per symbol, indexed by calendar day.
def wide(df: pl.DataFrame, col: str) -> dict[str, dict[dt.date, float]]:
    out: dict[str, dict[dt.date, float]] = {}
    for sym, day, v in df.select("symbol", "day", col).iter_rows():
        if v is not None and math.isfinite(v):
            out.setdefault(sym, {})[day] = v
    return out


close = wide(bars, "close")
qvol = wide(bars.with_columns((pl.col("close") * pl.col("volume")).alias("qv")), "qv")
funding = wide(fund, "funding_rate_sum") if fund.height else {}
one = dt.timedelta(days=1)


def series(d: dict[dt.date, float], day: dt.date, n: int) -> list[float] | None:
    vals = [d.get(day - k * one) for k in range(n)]
    return None if any(v is None for v in vals) else vals


def daily_rets(sym: str, day: dt.date, n: int) -> list[float] | None:
    c = series(close[sym], day, n + 1)
    if c is None:
        return None
    return [c[k] / c[k + 1] - 1 for k in range(n)]


def signals(day: dt.date) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {k: {} for k in
                                        ("low_vol60", "mom90_7", "attention_vol", "funding14", "rev5")}
    for sym in close:
        r60 = daily_rets(sym, day, 60)
        if r60 is None:
            continue
        out["low_vol60"][sym] = -statistics.pstdev(r60)
        c = close[sym]
        if c.get(day - 90 * one) and c.get(day - 7 * one):
            out["mom90_7"][sym] = c[day - 7 * one] / c[day - 90 * one] - 1
        if c.get(day - 5 * one):
            out["rev5"][sym] = -(c[day] / c[day - 5 * one] - 1)
        q7, q90 = series(qvol.get(sym, {}), day, 7), series(qvol.get(sym, {}), day, 90)
        if q7 and q90 and min(q7) > 0 and min(q90) > 0:
            out["attention_vol"][sym] = -(math.log(statistics.mean(q7)) - math.log(statistics.mean(q90)))
        f14 = [funding.get(sym, {}).get(day - k * one) for k in range(14)]
        if all(v is not None for v in f14):
            out["funding14"][sym] = -sum(f14)
    return out


def fwd(sym: str, day: dt.date) -> float | None:
    c0, c1 = close[sym].get(day), close[sym].get(day + H * one)
    return None if not c0 or not c1 else c1 / c0 - 1


def beta60(sym: str, day: dt.date) -> float | None:
    r, m = daily_rets(sym, day, 60), daily_rets("BTCUSDT", day, 60)
    if r is None or m is None:
        return None
    mm, mr = statistics.mean(m), statistics.mean(r)
    var = sum((x - mm) ** 2 for x in m)
    return sum((x - mm) * (y - mr) for x, y in zip(m, r)) / var if var else None


def vol60(sym: str, day: dt.date) -> float | None:
    r = daily_rets(sym, day, 60)
    return None if r is None else statistics.pstdev(r) or None


def ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=xs.__getitem__)
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def zscores(raw: dict[str, float]) -> dict[str, float]:
    syms = sorted(raw)
    rk = ranks([raw[s] for s in syms])
    m, sd = statistics.mean(rk), statistics.pstdev(rk)
    return {s: (r - m) / sd for s, r in zip(syms, rk)} if sd else {}


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else 0.0


def tstat(xs: list[float]) -> float:
    if len(xs) < 2 or statistics.pstdev(xs) == 0:
        return float("nan")
    return statistics.mean(xs) / statistics.pstdev(xs) * math.sqrt(len(xs))


def norm(w: dict[str, float]) -> dict[str, float]:
    g = sum(abs(v) for v in w.values())
    return {s: v / g for s, v in w.items()} if g else {}


names = ("low_vol60", "mom90_7", "attention_vol", "funding14", "rev5")
books = ("zbook", "zwins", "invvol", "tercile", "betaneu", "voltgt", "bnvt", "resid")
acc = {n: {"ic": [], **{b: [] for b in books}, "net": [], "long": [], "short": [],
           "top3share": [], "prev": None} for n in names}

for day in days:
    sig = signals(day)
    for n in names:
        z = zscores(sig[n])
        rets = {s: fwd(s, day) for s in z}
        z = {s: v for s, v in z.items() if rets[s] is not None}
        if len(z) < 10:
            continue
        syms = sorted(z)
        r = [rets[s] for s in syms]
        a = acc[n]
        a["ic"].append(spearman([z[s] for s in syms], r))
        w = norm(z)
        lo, hi = sorted(r)[int(0.02 * len(r))], sorted(r)[int(0.98 * len(r)) - 1]
        a["zbook"].append(sum(w[s] * rets[s] for s in syms))
        a["zwins"].append(sum(w[s] * min(max(rets[s], lo), hi) for s in syms))
        vols = {s: vol60(s, day) for s in syms}
        iv = norm({s: z[s] / vols[s] for s in syms if vols[s]})
        a["invvol"].append(sum(iv[s] * rets[s] for s in iv))
        order = sorted(syms, key=z.__getitem__)
        k = len(order) // 3
        terc = {s: -1 / (2 * k) for s in order[:k]} | {s: 1 / (2 * k) for s in order[-k:]}
        a["tercile"].append(sum(terc[s] * rets[s] for s in terc))
        betas = {s: beta60(s, day) for s in syms}
        bsyms = [s for s in syms if betas[s] is not None]
        longs = {s: w[s] for s in bsyms if w[s] > 0}
        shorts = {s: w[s] for s in bsyms if w[s] < 0}
        bl = sum(longs[s] * betas[s] for s in longs) / max(sum(longs.values()), 1e-12)
        bs = sum(-shorts[s] * betas[s] for s in shorts) / max(-sum(shorts.values()), 1e-12)
        # Long gross gl, short gross gs with gl+gs=1 and gl*bl = gs*bs.
        gl = bs / (bl + bs) if (bl + bs) > 0 else 0.5
        scl = gl / max(sum(longs.values()), 1e-12)
        scs = (1 - gl) / max(-sum(shorts.values()), 1e-12)
        bn = {s: longs[s] * scl for s in longs} | {s: shorts[s] * scs for s in shorts}
        a["betaneu"].append(sum(bn[s] * rets[s] for s in bn))
        disp = []
        for k in range(int(os.environ.get('DISP_WINDOW', '60'))):
            dd = day - k * one
            xs = [close[s][dd] / close[s][dd - one] - 1 for s in syms
                  if close[s].get(dd) and close[s].get(dd - one)]
            if len(xs) >= 10:
                disp.append(statistics.pstdev(xs))
        scale = 1 / statistics.mean(disp) if disp else 0.0
        a["voltgt"].append(a["zbook"][-1] * scale / 100)
        a["bnvt"].append(a["betaneu"][-1] * scale / 100)
        m = fwd("BTCUSDT", day)
        a["resid"].append(sum(w[s] * (rets[s] - betas[s] * m) for s in bsyms) if m is not None else 0.0)
        a.setdefault("bookbeta", []).append(sum(w[s] * betas[s] for s in bsyms))
        a.setdefault("fdisp", []).append(statistics.pstdev(r))
        prev = a["prev"] or {}
        traded = sum(abs(w.get(s, 0) - prev.get(s, 0)) for s in set(w) | set(prev))
        a["net"].append(a["zbook"][-1] - FEE * traded)
        a["prev"] = w
        mkt = statistics.mean(r)
        a["long"].append(statistics.mean(rets[s] - mkt for s in order[-k:]))
        a["short"].append(statistics.mean(rets[s] - mkt for s in order[:k]))
        pnl = sorted((abs(w[s] * rets[s]) for s in syms), reverse=True)
        tot = sum(pnl)
        a["top3share"].append(sum(pnl[:3]) / tot if tot else 0)

print(f"in-sample dates {len(days)} (first {days[0]}, last {days[-1]}), horizon {H}, fee {FEE*1e4:.0f} bps")
print(f"{'signal':14}{'n':>4}{'ICt':>7}" + "".join(f"{b+' IRt':>13}" for b in books)
      + f"{'net IRt':>9}{'long-mkt':>10}{'short-mkt':>11}{'top3|pnl|':>11}{'bookβ':>8}")
for n in names:
    a = acc[n]
    if not a["ic"]:
        print(f"{n:14} no dates")
        continue
    print(f"{n:14}{len(a['ic']):4}{tstat(a['ic']):7.2f}"
          + "".join(f"{tstat(a[b]):13.2f}" for b in books)
          + f"{tstat(a['net']):9.2f}{statistics.mean(a['long'])*100:9.2f}%"
          + f"{statistics.mean(a['short'])*100:10.2f}%{statistics.mean(a['top3share']):11.0%}"
          + f"{statistics.mean(a['bookbeta']):8.2f}")


def corr(x: list[float], y: list[float]) -> float:
    mx, my = statistics.mean(x), statistics.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else float("nan")


print()
print("IC versus realised forward dispersion (the 10-day cross-sectional stdev of returns):")
print(f"{'signal':14}{'corr(IC,disp)':>15}{'IC calm half':>14}{'IC wild half':>14}{'book wild share of |pnl|':>26}")
for n in names:
    a = acc[n]
    if not a["ic"]:
        continue
    med = statistics.median(a["fdisp"])
    calm = [i for i, d in zip(a["ic"], a["fdisp"]) if d <= med]
    wild = [i for i, d in zip(a["ic"], a["fdisp"]) if d > med]
    tot = sum(abs(b) for b in a["zbook"])
    wild_pnl = sum(abs(b) for b, d in zip(a["zbook"], a["fdisp"]) if d > med)
    print(f"{n:14}{corr(a['ic'], a['fdisp']):15.2f}{statistics.mean(calm):14.3f}{statistics.mean(wild):14.3f}{wild_pnl / tot:26.0%}")
