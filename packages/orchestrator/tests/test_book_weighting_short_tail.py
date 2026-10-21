"""The ``"short_tail"`` research book, from the evaluation config to the
metrics.

additions_spec_short_tail_book.xml: the evaluation config's ``book.weighting``
gains a fourth spelling, ``"short_tail"``, under which each date's research
book is short the bottom decile of that date's scores, equal-weight within
that leg, and long every other scored name equal-weight — dollar-neutral at
gross 1, the long leg the market-like complement of the short rather than a
second bet on a decile that carries no gradient (the committed
preregistration results show the gradient living in the bottom decile of
scores alone).  The beta-neutral rescale applies after, exactly as for every
other weighting, and with ``"z"``, ``"inverse_vol"`` or ``"tail_decile"``
every number is identical to today.

Two groups of tests, with no shared module-level mutable state:

* **the config** — :data:`orchestrator._context.BOOK_KEY`'s closed vocabulary
  gains ``"short_tail"``
  (:data:`orchestrator._context.SHORT_TAIL_WEIGHTING`) beside ``"z"``,
  ``"inverse_vol"`` and ``"tail_decile"``; the value parses through
  :func:`~orchestrator._context.load_evaluation_context` — the real public
  seam, over a genuine sealed lake — one of the other three spellings loads
  unchanged, and an unknown spelling is still refused by name, with the
  refusal now naming all four weightings.
* **the metrics** — :func:`evaluator.compute_node_metrics` under
  ``"short_tail"`` on a small hand-priced
  :class:`evaluator.PostCostReturns` fixture reports ``tail_k = floor(n/10)``
  per date and ``book_returns`` equal to the short-tail book's per-date
  returns computed directly in the test (1e-12), which is what both
  evaluation chains measure, since they pass
  ``weighting=context.book.weighting`` through unchanged and compute no side
  panel for this spelling.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Runs under pytest-xdist: every fixture
builds a fresh temporary database and lake.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from evaluator import (
    HORIZONS,
    CostModelRef,
    EvaluatorMetricsError,
    PostCostReturns,
    PostCostSeries,
    book_weights,
    compute_node_metrics,
)
from orchestrator._context import (
    BOOK_WEIGHTINGS,
    INVERSE_VOL_WEIGHTING,
    SHORT_TAIL_WEIGHTING,
    TAIL_DECILE_WEIGHTING,
    Z_WEIGHTING,
    BookConfig,
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from snapshot import SnapshotService

CODE_WORD = "evaluation_config"

_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)


# == Part A: the config, through load_evaluation_context =======================

PART_A_SYMBOLS = ("SYM00", "SYM01")
PART_A_FIRST_DAY = dt.date(2026, 9, 1)
PART_A_BAR_DAYS = tuple(
    PART_A_FIRST_DAY + dt.timedelta(days=offset) for offset in range(12)
)
PART_A_EVALUATION_DAYS = tuple(day.isoformat() for day in PART_A_BAR_DAYS[6:10])


def _part_a_close(symbol_index: int, day_index: int) -> float:
    return round(100.0 + 10.0 * symbol_index + 0.25 * day_index, 2)


def _stage_and_seal_part_a(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(PART_A_SYMBOLS):
        for offset, day in enumerate(PART_A_BAR_DAYS):
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "close": [str(_part_a_close(index, offset))],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


@pytest.fixture
def document_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, str]]:
    """One valid base document and environment, pointing at a real sealed lake."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _stage_and_seal_part_a(tmp_path / "lake")

    cost_model_path = tmp_path / "cost_model.yaml"
    cost_model_path.write_text(
        'cost_model:\n  version: "2026.10.0"\n  venue: testnet_spot\n'
        "  fees:\n    taker_bps: 12.5\n    maker_bps: 8.0\n",
        encoding="utf-8",
    )

    bwrap_dir = tmp_path / "bin"
    bwrap_dir.mkdir()
    bwrap = bwrap_dir / "bwrap"
    bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)

    document: dict[str, Any] = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(PART_A_EVALUATION_DAYS),
        "horizon": 1,
        "seed": 20261021,
        "epoch_id": "epoch-2026-10-21-short-tail",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    environment = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'ctx.db'}",
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bwrap_dir),
    }
    return document, environment


def _load(
    document: Mapping[str, Any],
    environment: Mapping[str, str],
    tmp_path: Path,
    name: str,
) -> EvaluationContext | None:
    path = tmp_path / f"evaluation-{name}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    env = dict(environment)
    env["NULLIUS_EVALUATION_CONFIG"] = str(path)
    return load_evaluation_context(env)


def _refuses(
    document: Mapping[str, Any],
    environment: Mapping[str, str],
    tmp_path: Path,
    name: str,
    *needles: str,
) -> str:
    with pytest.raises(EvaluationConfigError) as record:
        _load(document, environment, tmp_path, name)
    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:"), message
    for needle in needles:
        assert needle in message, (needle, message)
    return message


def test_short_tail_weighting_parses(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document,
        book={"beta_neutral": False, "weighting": SHORT_TAIL_WEIGHTING},
    )
    context = _load(document, environment, tmp_path, "short-tail")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == SHORT_TAIL_WEIGHTING
    assert context.book == BookConfig(beta_neutral=False, weighting=SHORT_TAIL_WEIGHTING)


def test_short_tail_parses_beside_beta_neutral(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    """The two knobs are independent, exactly as the other weightings' are:
    a short-tail book can be beta-neutral too."""
    document, environment = document_env
    document = dict(
        document,
        book={
            "beta_neutral": True,
            "beta_window_days": 20,
            "weighting": SHORT_TAIL_WEIGHTING,
        },
    )
    context = _load(document, environment, tmp_path, "short-tail-neutral")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == SHORT_TAIL_WEIGHTING
    assert context.book.beta_neutral is True


def test_a_prior_spelling_loads_unchanged(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    """The vocabulary grew by one member, and every spelling that parsed
    before still parses to the same BookConfig."""
    document, environment = document_env
    document = dict(
        document,
        book={"beta_neutral": False, "weighting": TAIL_DECILE_WEIGHTING},
    )
    context = _load(document, environment, tmp_path, "tail-decile-unchanged")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == TAIL_DECILE_WEIGHTING


@pytest.mark.parametrize("spelling", [Z_WEIGHTING, INVERSE_VOL_WEIGHTING])
def test_the_legacy_spellings_load_unchanged(
    document_env: tuple[dict[str, Any], dict[str, str]],
    tmp_path: Path,
    spelling: str,
) -> None:
    document, environment = document_env
    document = dict(document, book={"beta_neutral": False, "weighting": spelling})
    context = _load(document, environment, tmp_path, f"legacy-{spelling}")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == spelling


def test_short_tail_of_the_wrong_type_is_still_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(document, book={"beta_neutral": False, "weighting": 4})
    _refuses(document, environment, tmp_path, "short-tail-int", "weighting")


def test_unknown_weighting_is_refused_naming_all_four(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    """The closed vocabulary grew by one, and the refusal names every member
    of it — a reader who mistyped the new spelling is told what was expected."""
    document, environment = document_env
    document = dict(
        document, book={"beta_neutral": False, "weighting": "short_tale"}
    )
    message = _refuses(
        document, environment, tmp_path, "unknown-short-tail", "short_tale"
    )
    for spelling in BOOK_WEIGHTINGS:
        assert spelling in message, (spelling, message)


# == Part B: the metrics, on a small hand-priced PostCostReturns ===============

_D0 = dt.date(2026, 9, 1)
_D1 = _D0 + dt.timedelta(days=1)


def _hand_priced(
    returns_by_date: dict[dt.date, dict[str, float]],
    *,
    horizon: int = 1,
) -> PostCostReturns:
    """A hand-built, single-horizon priced bundle — the same shape the
    evaluator member's own book-weight suites use, small enough to rebuild
    every figure in the test."""
    series: dict[int, PostCostSeries] = {}
    for h in HORIZONS:
        values = returns_by_date if h == horizon else {}
        series[h] = PostCostSeries(
            horizon=h,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={day: dict(row) for day, row in values.items()},
            charges={
                day: {symbol: 0.001 for symbol in row} for day, row in values.items()
            },
        )
    return PostCostReturns(
        node_id="node_1",
        snapshot_name="snap_abc123",
        rebalance_dates=tuple(sorted(returns_by_date)),
        cost_model=_REF,
        series=series,
        charges_budget=False,
    )


def _decile_scores(count: int) -> dict[str, float]:
    """``count`` symbols with strictly increasing scores, so the ranking is
    unambiguous and the tie-break never fires."""
    return {f"S{i:02d}": float(i + 1) for i in range(count)}


def _shifted_returns(scores: dict[str, float], *, shift: int = 5) -> dict[str, float]:
    """Forward returns whose ordering is the scores' own, rotated by ``shift``
    names — a cross-section the ranking is *related* to but does not
    reproduce, so the two dates' information coefficients differ (two dates
    sharing one IC would have a zero standard error of the mean and
    ``ic_tstat`` refuses that by design)."""
    ordered = sorted(scores)
    count = len(ordered)
    return {
        ordered[i]: scores[ordered[(i + shift) % count]] for i in range(count)
    }


def test_compute_node_metrics_reports_short_tail_tail_k_and_book_returns():
    """Under ``"short_tail"`` the record carries ``tail_k = floor(n/10)`` per
    date and per-date ``book_returns`` equal to the short-tail book's own
    returns, rebuilt directly in the test (1e-12) — the figures both
    evaluation chains measure, since they pass the config's weighting through
    to this call unchanged."""
    d0_scores = _decile_scores(20)
    d1_scores = _decile_scores(50)
    d1_returns = _shifted_returns(d1_scores)
    scores = {_D0: d0_scores, _D1: d1_scores}
    priced = _hand_priced({_D0: d0_scores, _D1: d1_returns})

    metrics = compute_node_metrics(priced, scores, weighting=SHORT_TAIL_WEIGHTING)

    # tail_k is the short leg's size per date — floor(n/10) of the joined
    # cross-section, the same figure the tail-decile weighting records.
    assert dict(metrics.tail_k) == {_D0: 20 // 10, _D1: 50 // 10}

    # And every measured date's book return is the short-tail book's return,
    # rebuilt from the ranking by hand: the k lowest names short at −0.5/k,
    # every other name long at +0.5/(n−k).
    for day, returns_row in ((_D0, d0_scores), (_D1, d1_returns)):
        weights = book_weights(scores[day], weighting=SHORT_TAIL_WEIGHTING)
        assert math.fsum(abs(w) for w in weights.values()) == pytest.approx(
            1.0, abs=1e-12
        )
        expected = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in weights
        )
        assert metrics.book_returns[day] == pytest.approx(expected, abs=1e-12)


def test_compute_node_metrics_short_tail_thin_cross_section_is_refused():
    """The same thin-cross-section refusal guards the short tail: fifteen
    names hold floor(15/10) = 1 per short leg, which is not a decile but a
    directional bet — refused naming the date and the count."""
    scores = {_D0: _decile_scores(15), _D1: _decile_scores(15)}
    priced = _hand_priced(
        {_D0: _decile_scores(15), _D1: _shifted_returns(_decile_scores(15))}
    )
    with pytest.raises(EvaluatorMetricsError) as refusal:
        compute_node_metrics(priced, scores, weighting=SHORT_TAIL_WEIGHTING)
    message = str(refusal.value)
    assert _D0.isoformat() in message
    assert "15" in message
    assert "floor(15/10) = 1" in message
