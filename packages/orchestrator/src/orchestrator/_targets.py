"""Supplies forward returns from the context's own sealed snapshot to the null oracle.

additions_spec_real_campaign_path.xml, "Campaign Evaluation Path", feature 4:
*System supplies forward returns from the evaluation context's own sealed
snapshot to the null oracle, so LiveEvaluator.evaluate returns a scored node,
not a refusal, when the composed target route carries no target supply.*

**The gap this closes.** :func:`nulloracle.build_target_route` composes
``TargetEndpoint(sidecar, permute=...)`` with no ``targets=`` — "neither is
this member's to resolve from an environment variable" is that builder's own
word for it — so a live evaluation that only ever asked the composed
``"nulloracle-target-route"`` component got the honest refusal that route is
built to give: no supply, no answer, on *both* branches alike (feature 112's
own symmetric-refusal rule). This module is the supply
:func:`orchestrator._context.load_evaluation_context` already paid to read:
``context.closes`` is the sealed snapshot's own bars, parsed once at context
load through the evaluator's own closes reader, so a forward return computed
from it opens no second connection to the mount and reinvents no reader.

**The formula.** docs/nullius-tech-architecture.md §6.1's own spelling —
``close[d+h] / close[d] - 1``, the simple close-to-close return — with one
deliberate narrowing from pipeline step 4's own alignment
(:mod:`evaluator._align`): ``h`` here is always ``context.horizon``, the one
horizon a live evaluation's :class:`~orchestrator._context.EvaluationContext`
carries, never the asking request's own ``horizon``. §7.2's route is asked
once per horizon the alignment covers (:func:`evaluator._gate.gate_targets`
asks for every horizon with any computable target, not only the one the
campaign measures its headline metrics at), and this fallback does not chase
that whole set — it is scoped to the one horizon a live deployment
configured, which is the horizon ``context.closes`` was read for and the one
:class:`~orchestrator._evaluate.NodeEvaluation` actually scores.

**What "trading days" means here.** A symbol's own sorted sequence of the
dates it has a close for in ``context.closes[symbol]`` — not the calendar,
and not the cross-symbol market grid :mod:`evaluator._align` resolves its
"period" against. Two symbols quoted on different days can therefore see "h
trading days" span different calendar spans; that is a narrower claim than
step 4's own, and a necessary one — this seam has no cross-section to
resolve a shared grid from, only the one symbol's own series it is asked
about.

**Never zero-filled.** A ``(date, symbol)`` pair with no close ``h`` trading
days ahead of its own entry — the tail of a series, or a symbol whose
history ends earlier than another's — is omitted from the returned mapping
entirely. A caller reading an absent key sees no claim; a zero would read as
"the signal predicted nothing", the exact confusion
:mod:`evaluator._align`'s own docstring refuses for the same reason.

**The barrier.** This module never imports ``nulloracle`` and reads no null
bit: the callable it returns answers the same series shape (``{date:
{symbol: return}}``) whichever node asks, and which branch is served — the
real series or a block permutation of it — is chosen entirely downstream of
this seam, inside ``TargetEndpoint.post``, from the sidecar's own sealed
assignment. Nothing in this module could tell the two branches apart even if
it tried, because it is never told which branch it was supplying.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from typing import Any

__all__ = ["grid_forward_returns", "snapshot_forward_returns"]


def snapshot_forward_returns(
    context: Any,
) -> Callable[[Any], dict[dt.date, dict[str, float]]]:
    """A ``targets`` seam over ``context``'s own sealed closes.

    Returns a callable ``(request) -> {date: {symbol: return}}`` — the shape
    :class:`nulloracle.TargetEndpoint`'s ``targets`` seam calls with its
    request and expects a forward-return panel back from. Reads only
    ``context.closes`` (the evaluation context's own ``{symbol: {date:
    close}}``, already parsed once from the sealed snapshot by
    :func:`orchestrator._context.load_evaluation_context`) and
    ``context.horizon`` — no further I/O, and no second pass over the mount.

    The returned callable narrows to ``request.symbols`` when the request
    states them (every symbol in ``context.closes`` otherwise) and to
    ``request.date_range`` when the request states one (the whole of each
    symbol's own series otherwise), so a caller handing this seam straight to
    :class:`nulloracle.TargetEndpoint` gets back exactly the cross-section
    and the span the ask named — the coherence
    :meth:`~nulloracle.TargetEndpoint._covers` checks on both branches alike.

    Each value is the close-to-close simple return over ``context.horizon``
    of that *symbol's own* trading days (the sorted dates it has a close
    for): entry index ``i``'s return is ``close[i + horizon] / close[i] -
    1``. A ``(date, symbol)`` pair with no close that many trading days
    ahead — the tail of a symbol's series, or a symbol whose series ends
    earlier than another's — is omitted, never zero-filled.
    """

    closes: Mapping[str, Mapping[dt.date, float]] = context.closes
    horizon = context.horizon

    def _forward_returns(request: Any) -> dict[dt.date, dict[str, float]]:
        requested_symbols = getattr(request, "symbols", None)
        symbols = (
            tuple(requested_symbols) if requested_symbols is not None else tuple(closes)
        )
        span = getattr(request, "date_range", None)
        # The evaluator asks once per aligned horizon (1, 2, 5, 10, 20), so the
        # answer's horizon is the request's own. context.horizon is only the
        # metrics horizon: serving it for every ask labelled 5-day returns as
        # horizon-1 (archive smoke campaign 2a0700fa, KEEPUSDT on 2022-02-14).
        asked = getattr(request, "horizon", None)
        step = asked if isinstance(asked, int) and not isinstance(asked, bool) else horizon

        series: dict[dt.date, dict[str, float]] = {}
        for symbol in symbols:
            by_date = closes.get(symbol)
            if not by_date:
                continue
            ordered = sorted(by_date)
            for index, entry_day in enumerate(ordered):
                if span is not None and not (span[0] <= entry_day <= span[1]):
                    continue
                exit_index = index + step
                if exit_index >= len(ordered):
                    continue
                entry_close = by_date[entry_day]
                exit_close = by_date[ordered[exit_index]]
                series.setdefault(entry_day, {})[symbol] = exit_close / entry_close - 1.0
        return series

    return _forward_returns


def grid_forward_returns(
    context: Any,
) -> Callable[[Any], dict[dt.date, dict[str, float]]]:
    """:func:`snapshot_forward_returns`, narrowed to the context's own
    rebalance grid (``context.evaluation_dates``).

    The live target route serves exactly the dates a node is scored on. The
    gate requires the served support to equal the alignment's support, and
    the null permutation must shuffle blocks of rebalances, not blocks of
    calendar days. A dense daily grid serves the same panel as before. A
    sparse grid (the weekly archive config) used to receive every trading
    day in the span, and every node failed EvaluatorGateError (archive
    campaign 1, 2026-10-08).
    """
    grid = frozenset(context.evaluation_dates)
    base = snapshot_forward_returns(context)

    def _on_grid(request: Any) -> dict[dt.date, dict[str, float]]:
        return {day: row for day, row in base(request).items() if day in grid}

    return _on_grid
