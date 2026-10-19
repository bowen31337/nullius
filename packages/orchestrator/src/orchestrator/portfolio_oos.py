"""``python -m orchestrator.portfolio_oos`` — a set of picks, scored as one book.

additions_spec_engine_edge_recovery.xml, "Portfolio Scoring", feature 6:
*System scores a set of committed picks as one equal-weight book out of
sample and reports its mean, volatility, t-statistic and effective number of
independent bets beside each pick's own, so that the thing the diagnosis
found carries edge, the population combined, is what gets measured.*

docs/research/2026-10-19-alpha-diagnosis.md's own finding (addition summary,
point 5): *"The only edge-shaped result is a property of the population of
picks combined ... No tool scores a set of picks as one book."*  Every other
feature this addition shipped (inverse-vol weighting, maker execution,
native-horizon OOS, clean-grid admission) repairs one node's own reading;
this command is the one that measures the population those repairs feed —
never writing a node, a ledger debit or a replay_score row, because scoring
a book that already exists is a read, not a discovery.

**Each pick is scored exactly the path
:func:`orchestrator._financial_eval.score_on_financial_world` scores a
committed node by** (:func:`orchestrator._financial_eval._oos_ir`, the
identical read :mod:`orchestrator.canary_cli` wires as its own
``evaluate_node``): the campaign's own recorded ``horizon`` when one is on
record, re-horizoning the evaluation context through
``dataclasses.replace`` exactly as that function does; the context's own
``book.weighting`` and ``execution``, read by
:func:`orchestrator._evaluate.evaluate_on_dates` itself, never duplicated
here; and the real, never-permuted oracle
(:func:`orchestrator._financial_eval._dream_oracle`) over the context's own
``oos_dates`` — a dreaming read, not a close-out one, because this command
holds no sidecar key and a book of already-committed picks is not what any
one pick's own calibration is certified against.  Unlike the dreaming
cycle's :class:`~orchestrator._financial_eval.FinancialEvalContext`, this
module keeps no cross-pick cache: a portfolio run scores each pick once, and
a cache whose scope outlived the call would answer nothing a second lookup
ever asks for.

**Admission is the shared helper's, not a second reading of the same
law.**  :func:`orchestrator._financial_eval.admit_financial_worlds` is the
one admission :mod:`orchestrator.dream`'s cycle and the M3 verdict's pool
check both call; a pick whose campaign this helper does not admit is
reported (with the helper's own message, or this module's own when the
campaign carries no manifest at all — never a VOID campaign's silence) and
excluded from the book, never scored.

**The book is equal-weight over the picks' common out-of-sample dates.**
Every pick is evaluated over the context's own fixed ``oos_dates`` grid, but
a date can still be absent from one pick's ``book_returns`` (an
under-priced universe, a gated date) without being absent from another's —
so the book's own per-date return is the mean of every admitted pick's
return on a date every admitted pick actually measured, and the population
figures (mean, sd, t, ``N_eff``, the mean pairwise correlation) are all
measured over that one shared grid, never a per-pick one.  ``N_eff`` is the
mean per-pick variance divided by the book's own variance — ``K`` when the
picks are uncorrelated, ``1`` when they are the same bet reread ``K``
times — the plain restatement of "how many independent bets is this book
actually one of."
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import os
import sqlite3
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from artifacts import ArtifactStore

from ._context import (
    EVALUATION_CONFIG_ENV,
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from ._evaluate import evaluate_on_dates
from ._financial_eval import _campaign_horizon, _dream_oracle, admit_financial_worlds

__all__ = [
    "DATABASE_URL_ENV",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "MIN_ADMITTED_PICKS",
    "PORTFOLIO_OOS_CODE",
    "PortfolioOosError",
    "PortfolioPick",
    "PortfolioResult",
    "ScoredPick",
    "load_picks_file",
    "load_picks_policy_version",
    "main",
    "score_portfolio",
]

#: The relational store every member in this workspace reads this variable
#: from — restated here, this module's own contract, rather than imported
#: from a sibling's spelling of it.
DATABASE_URL_ENV = "DATABASE_URL"

#: The greppable word every refusal this module raises opens with — never a
#: collaborator's, which already opens with its own
#: (``financial_world_admission``, an ``EvaluationConfigError``'s own code).
PORTFOLIO_OOS_CODE = "portfolio_oos"

#: The floor below which a book has no population to measure — two picks is
#: also the smallest set a pairwise correlation or an ``N_eff`` reading is
#: defined over.
MIN_ADMITTED_PICKS = 2

#: Done — the summary line was printed (and, with ``--out``, the series file written).
EXIT_OK = 0
#: A refusal: malformed ``--picks``, too few admitted picks, an existing ``--out``.
EXIT_REFUSED = 1
#: Missing configuration: no ``DATABASE_URL``, or no ``NULLIUS_EVALUATION_CONFIG``.
EXIT_CONFIG = 2


class PortfolioOosError(Exception):
    """A refusal this module's own: every message opens with :data:`PORTFOLIO_OOS_CODE`."""


@dataclasses.dataclass(frozen=True)
class PortfolioPick:
    """One committed pick this command is asked to score — a world and a node."""

    campaign_id: str
    node_id: str


@dataclasses.dataclass(frozen=True)
class ScoredPick:
    """One pick's out-of-sample reading: the campaign's own horizon, its
    theme, and the two per-date series :func:`orchestrator._evaluate.
    evaluate_on_dates` measured — kept, never reduced to one scalar, because
    the book this command scores is built from the series, not the scalar.
    """

    pick: PortfolioPick
    horizon: int
    theme: str | None
    book_returns: Mapping[dt.date, float]
    ic_series: Mapping[dt.date, float]
    ic_tstat: float


@dataclasses.dataclass(frozen=True)
class PortfolioResult:
    """:func:`score_portfolio`'s whole answer: the printed summary, and the
    series ``--out`` saves."""

    summary: dict[str, Any]
    oos_dates: tuple[dt.date, ...]
    portfolio_series: Mapping[dt.date, float]
    pick_book_returns: Mapping[tuple[str, str], Mapping[dt.date, float]]
    pick_ic_series: Mapping[tuple[str, str], Mapping[dt.date, float]]


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path — this module's
    own restatement of the translation every store in this workspace makes."""
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: this verb speaks sqlite:/// only"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: {DATABASE_URL_ENV} carries no database path"
        )
    return Path(path)


def load_picks_file(path: str) -> tuple[PortfolioPick, ...]:
    """``--picks PATH``: a JSON list of ``{"campaign_id", "node_id"}`` objects."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: --picks {path!r} could not be read: {exc}"
        ) from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: --picks {path!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, list) or not document:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: --picks {path!r} must be a non-empty JSON "
            f'list of {{"campaign_id", "node_id"}} objects, got {document!r}'
        )
    picks: list[PortfolioPick] = []
    for index, entry in enumerate(document):
        campaign_id = entry.get("campaign_id") if isinstance(entry, dict) else None
        node_id = entry.get("node_id") if isinstance(entry, dict) else None
        if (
            not isinstance(campaign_id, str)
            or not campaign_id.strip()
            or not isinstance(node_id, str)
            or not node_id.strip()
        ):
            raise PortfolioOosError(
                f"{PORTFOLIO_OOS_CODE}: --picks {path!r} entry {index} must "
                "carry non-empty 'campaign_id' and 'node_id' strings, got "
                f"{entry!r}"
            )
        picks.append(PortfolioPick(campaign_id=campaign_id, node_id=node_id))
    return tuple(picks)


def load_picks_policy_version(
    database_url: str, policy_version: str
) -> tuple[PortfolioPick, ...]:
    """``--policy-version V``: every committed pick ``replay_score`` holds
    under ``V``, one per world — the latest row per ``world_id``, mirroring
    :func:`orchestrator.m3_verdict._committed_pick`'s own per-world read. A
    world whose latest row under ``V`` committed nothing (``NULL``) names no
    pick and is silently absent, the same miss :mod:`replay.score` itself
    never turns into a pick.
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT world_id, committed_pick FROM replay_score "
            "WHERE policy_version = ? "
            "ORDER BY world_id, created_at DESC, id DESC",
            (policy_version,),
        ).fetchall()
    seen: set[str] = set()
    picks: list[PortfolioPick] = []
    for world_id, committed_pick in rows:
        if world_id in seen:
            continue
        seen.add(world_id)
        if committed_pick is not None:
            picks.append(PortfolioPick(campaign_id=world_id, node_id=committed_pick))
    return tuple(picks)


def _pick_theme(database_url: str, campaign_id: str, node_id: str) -> str | None:
    """The pick's own ``theme_root`` — ``None`` when the tree holds no such row."""
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT theme_root FROM node WHERE campaign_id = ? AND id = ?",
            (campaign_id, node_id),
        ).fetchone()
    return None if row is None else row[0]


def _score_pick_oos(
    pick: PortfolioPick, *, evaluation_context: EvaluationContext
) -> ScoredPick:
    """Score one committed pick out of sample — the same path
    :func:`orchestrator._financial_eval._oos_ir` scores a committed node by
    (see the module docstring), with the measured series kept rather than
    reduced to the one scalar that function answers.
    """
    evaluation = evaluation_context
    horizon = _campaign_horizon(evaluation.database_url, pick.campaign_id)
    if horizon is not None:
        evaluation = dataclasses.replace(evaluation, horizon=horizon)
    code = ArtifactStore(evaluation.artifact_dir).read(
        pick.campaign_id, pick.node_id, "code.py"
    )
    oracle = _dream_oracle(evaluation, evaluation.oos_dates)
    metrics, _cost_adjusted_ir = evaluate_on_dates(
        pick.node_id,
        code.decode("utf-8"),
        context=evaluation,
        oracle=oracle,
        dates=evaluation.oos_dates,
    )
    theme = _pick_theme(evaluation.database_url, pick.campaign_id, pick.node_id)
    return ScoredPick(
        pick=pick,
        horizon=evaluation.horizon,
        theme=theme,
        book_returns=dict(metrics.book_returns),
        ic_series=dict(metrics.ic_series),
        ic_tstat=metrics.ic_tstat,
    )


def _admit(
    picks: Sequence[PortfolioPick], *, database_url: str, oos_first_date: dt.date | None
) -> tuple[tuple[PortfolioPick, ...], tuple[dict[str, Any], ...]]:
    """Split ``picks`` into admitted and excluded, through the shared helper."""
    admission = admit_financial_worlds(database_url, oos_first_date=oos_first_date)
    admitted_ids = frozenset(admission.campaign_ids)
    messages = {exclusion.campaign_id: exclusion.message for exclusion in admission.exclusions}
    admitted: list[PortfolioPick] = []
    excluded: list[dict[str, Any]] = []
    for pick in picks:
        if pick.campaign_id in admitted_ids:
            admitted.append(pick)
            continue
        message = messages.get(
            pick.campaign_id,
            f"{PORTFOLIO_OOS_CODE}: campaign {pick.campaign_id!r} is not "
            "among the campaigns admit_financial_worlds admits (it may "
            "carry no manifest, or be recorded VOID)",
        )
        excluded.append(
            {"campaign_id": pick.campaign_id, "node_id": pick.node_id, "reason": message}
        )
    return tuple(admitted), tuple(excluded)


def _mean_sd_t(values: Sequence[float]) -> tuple[float, float, float]:
    """The population mean, standard deviation and t-statistic of ``values``.

    Refuses rather than dividing by zero — fewer than two values, or a
    series that never varied — mirroring :func:`evaluator._metrics.
    compute_node_metrics`'s own stance on an undefined t-statistic.
    """
    n = len(values)
    if n < 2:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: a mean/sd/t reading needs at least two "
            f"dates, got {n}"
        )
    mean = statistics.fmean(values)
    sd = statistics.pstdev(values, mu=mean)
    if sd == 0.0:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: a series that is constant across its "
            f"{n} dates has zero standard deviation; its t-statistic is "
            "undefined"
        )
    t = (mean / sd) * math.sqrt(n)
    return mean, sd, t


def score_portfolio(
    picks: Sequence[PortfolioPick], *, evaluation_context: EvaluationContext
) -> PortfolioResult:
    """Score ``picks`` as one equal-weight book out of sample — the verb's whole act.

    Admits ``picks`` through the shared helper, refuses a set that admits
    fewer than :data:`MIN_ADMITTED_PICKS`, scores every admitted pick
    through :func:`_score_pick_oos`, and reduces the book to the figures the
    command prints (see the module docstring for ``N_eff`` and the common
    out-of-sample grid).
    """
    oos_first_date = (
        min(evaluation_context.oos_dates) if evaluation_context.oos_dates else None
    )
    admitted, excluded = _admit(
        picks,
        database_url=evaluation_context.database_url,
        oos_first_date=oos_first_date,
    )
    if len(admitted) < MIN_ADMITTED_PICKS:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: only {len(admitted)} of {len(picks)} "
            f"picks were admitted as financial worlds, below the floor of "
            f"{MIN_ADMITTED_PICKS}; a book of fewer than two picks has no "
            "population for the diagnosis's own finding to be measured over"
        )

    scored = [
        _score_pick_oos(pick, evaluation_context=evaluation_context) for pick in admitted
    ]

    common_dates: frozenset[dt.date] | None = None
    for item in scored:
        keys = frozenset(item.book_returns)
        common_dates = keys if common_dates is None else common_dates & keys
    dates = tuple(sorted(common_dates)) if common_dates else ()
    if len(dates) < 2:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: the admitted picks share {len(dates)} "
            "common out-of-sample dates, too few to score a book over"
        )

    series_by_pick = {
        item.pick: [item.book_returns[day] for day in dates] for item in scored
    }
    portfolio_series = [
        statistics.fmean(series_by_pick[item.pick][index] for item in scored)
        for index in range(len(dates))
    ]
    portfolio_mean, portfolio_sd, portfolio_t = _mean_sd_t(portfolio_series)
    portfolio_variance = statistics.pvariance(portfolio_series, mu=portfolio_mean)

    pick_rows: list[dict[str, Any]] = []
    variances: list[float] = []
    for item in scored:
        values = series_by_pick[item.pick]
        mean, sd, t = _mean_sd_t(values)
        variances.append(sd * sd)
        pick_rows.append(
            {
                "campaign_id": item.pick.campaign_id,
                "node_id": item.pick.node_id,
                "horizon": item.horizon,
                "mean": mean,
                "sd": sd,
                "t": t,
                "oos_ic_t": item.ic_tstat,
            }
        )
    n_eff = statistics.fmean(variances) / portfolio_variance

    pairs = [
        statistics.correlation(
            series_by_pick[scored[i].pick], series_by_pick[scored[j].pick]
        )
        for i in range(len(scored))
        for j in range(i + 1, len(scored))
    ]
    mean_pairwise_correlation = statistics.fmean(pairs)

    themes: dict[str, list[ScoredPick]] = {}
    for item in scored:
        themes.setdefault(item.theme or "unknown", []).append(item)
    theme_rows: dict[str, dict[str, Any]] = {}
    for theme, items in themes.items():
        theme_series = [
            statistics.fmean(series_by_pick[item.pick][index] for item in items)
            for index in range(len(dates))
        ]
        theme_mean, theme_sd, theme_t = _mean_sd_t(theme_series)
        theme_rows[theme] = {
            "K": len(items),
            "mean": theme_mean,
            "sd": theme_sd,
            "t": theme_t,
        }

    summary = {
        "K": len(scored),
        "mean": portfolio_mean,
        "sd": portfolio_sd,
        "t": portfolio_t,
        "N_eff": n_eff,
        "mean_pairwise_correlation": mean_pairwise_correlation,
        "oos_dates": len(dates),
        "picks": pick_rows,
        "excluded": list(excluded),
        "themes": theme_rows,
    }
    return PortfolioResult(
        summary=summary,
        oos_dates=dates,
        portfolio_series=dict(zip(dates, portfolio_series)),
        pick_book_returns={
            (item.pick.campaign_id, item.pick.node_id): dict(zip(dates, series_by_pick[item.pick]))
            for item in scored
        },
        pick_ic_series={
            (item.pick.campaign_id, item.pick.node_id): dict(item.ic_series) for item in scored
        },
    )


def _write_series(path: str, result: PortfolioResult) -> None:
    """``--out PATH``: the per-date portfolio and per-pick series, as JSON."""
    payload = {
        "oos_dates": [day.isoformat() for day in result.oos_dates],
        "portfolio": {day.isoformat(): value for day, value in result.portfolio_series.items()},
        "picks": {
            f"{campaign_id}:{node_id}": {
                "book_returns": {
                    day.isoformat(): value
                    for day, value in result.pick_book_returns[(campaign_id, node_id)].items()
                },
                "ic_series": {
                    day.isoformat(): value
                    for day, value in result.pick_ic_series[(campaign_id, node_id)].items()
                },
            }
            for campaign_id, node_id in result.pick_book_returns
        },
    }
    try:
        with open(path, "x", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError as exc:
        raise PortfolioOosError(
            f"{PORTFOLIO_OOS_CODE}: --out {path!r} could not be written: {exc}"
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.portfolio_oos",
        description=(
            "Score a set of committed picks as one equal-weight book out of "
            "sample, and report its mean, volatility, t-statistic and "
            "effective number of independent bets beside each pick's own."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--picks",
        default=None,
        metavar="PATH",
        help='a JSON list of {"campaign_id", "node_id"} committed picks',
    )
    source.add_argument(
        "--policy-version",
        dest="policy_version",
        default=None,
        metavar="V",
        help=(
            "every committed pick replay_score holds under this policy "
            "version, one per world"
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="write the per-date portfolio and per-pick series as JSON",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m orchestrator.portfolio_oos (--picks PATH | --policy-version V) [--out PATH]``."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    try:
        evaluation_context = load_evaluation_context(env=source)
    except EvaluationConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED
    if evaluation_context is None:
        print(
            f"{PORTFOLIO_OOS_CODE}: {EVALUATION_CONFIG_ENV} must name an "
            "evaluation configuration; scoring a set of committed picks out "
            "of sample needs the sealed snapshot, the cost model and the "
            "book's own weighting and execution to score each pick under",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    database_url = evaluation_context.database_url

    try:
        if arguments.picks is not None:
            picks = load_picks_file(arguments.picks)
        else:
            picks = load_picks_policy_version(database_url, arguments.policy_version)
    except PortfolioOosError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    if arguments.out is not None and Path(arguments.out).exists():
        print(
            f"{PORTFOLIO_OOS_CODE}: --out {arguments.out!r} already exists; "
            "refusing to overwrite it",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    try:
        result = score_portfolio(picks, evaluation_context=evaluation_context)
        if arguments.out is not None:
            _write_series(arguments.out, result)
    except PortfolioOosError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(result.summary))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
