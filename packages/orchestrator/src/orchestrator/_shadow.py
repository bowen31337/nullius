"""The forward shadow — a stored node's current weights, never a trial.

additions_spec_forward_shadow.xml, "Forward Shadow" feature 2: *System
computes a research node's current target weights from the latest sealed
data, so that a stored signal can be traded forward on the venue it was
scored for.*  :func:`shadow_weights` reproduces
:func:`orchestrator._evaluate.evaluate_node`'s own execution chain for one
date — ``signal_sandbox(context)``, ``resolve_window``, ``execute_signal``
with ``rebalance_dates=[as_of]`` and the context's own ``seed`` and
executor, the conforming check per vector, ``_drop_unpriced_symbols``,
``_score_rebalance_dates`` and (when the book is beta-neutral)
``compute_betas`` — but stops there: the forward book is
``evaluator.book_weights`` over that one date's z-scores and betas, never
``align_targets``, ``gate_targets``, ``apply_costs`` or
``compute_node_metrics``.  There is no target to align against (``as_of`` is
*now*; there is no forward return yet to score), no oracle to ask and no
ledger to debit — a forward shadow prices the book a stored signal would
trade next, it does not re-judge the discovery.

**``allowed_symbols`` is applied before z-scoring, not after.**  A forward
book that z-scores the full research universe and only then drops the
symbols the trading venue cannot carry would no longer be the dollar- and
beta-neutral book the z-scores describe — the cross-section the signal is
*relatively* preferred within must already be the cross-section that gets
traded.  So the order this module runs is: drop unpriced symbols (the perp
instrument's existing rule), drop symbols outside ``allowed_symbols``, *then*
``_score_rebalance_dates``'s normalize-and-z-score, then ``compute_betas``,
then ``book_weights``.

**Every refusal is a single :class:`ShadowError`, naming its cause** — this
module's own error base, in the one-base-per-member shape every other
orchestrator module takes for its own concern (:class:`~orchestrator._evaluate.SandboxExecutionError`,
:class:`~orchestrator._roots.RootPlantError`, :class:`~orchestrator._live_tree.LiveTreeError`
and the rest): a handful of distinct causes sharing one class rather than
growing a taxonomy, because the only thing a caller can do about any of them
is read the message and either fix the code, fix the venue's symbol roster,
or wait for the data. Three causes are named explicitly: a non-conforming
score vector or the sandbox's own failure; fewer than two scored symbols in
the long or the short leg after z-scoring (a dollar-neutral book needs real
diversification on both sides, not one name per leg); and, when the book is
beta-neutral, an ``as_of`` whose beta benchmark carries no close at all —
rescaling a book nobody can benchmark is not beta-neutral, it is unmeasured.
Every other exception the chain raises (a window refusal, a malformed
signal, an evaluator error) is caught and reraised as the same
:class:`ShadowError`, carrying the original failure's message, so a caller
needs exactly one ``except`` to learn a forward shadow could not be priced.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from typing import Final

from evaluator import (
    RawScoreVector,
    SignalExecution,
    book_weights,
    execute_signal,
    resolve_window,
)

from ._context import EvaluationContext, compute_betas, signal_sandbox
from ._evaluate import (
    _END_OF_DAY,
    _drop_unpriced_symbols,
    _executor_failure,
    _materialize_from_context,
    _score_rebalance_dates,
)

__all__ = ["ShadowError", "ShadowWeights", "shadow_weights"]

#: A leg (the long or the short side of the dollar-neutral book, split by
#: the sign of a z-scored symbol) must carry at least this many symbols —
#: one name on a side is not diversification, it is a single-name bet
#: dressed as a leg.
_MIN_SYMBOLS_PER_LEG: Final[int] = 2


class ShadowError(Exception):
    """A forward shadow could not be priced — this module's own error base.

    Raised by :func:`shadow_weights`, and only there, naming one of three
    causes directly (a non-conforming score vector or the sandbox's own
    failure; fewer than :data:`_MIN_SYMBOLS_PER_LEG` scored symbols in
    either leg after z-scoring; an ``as_of`` with no close for the
    beta-neutral book's benchmark) or, failing that, wrapping whatever the
    reproduced evaluation chain itself raised — an evaluator refusal, a
    window that cannot be resolved, a malformed signal.  Every message
    names ``as_of`` and the specific shortfall, so the defect is decidable
    without reading this module's source.
    """


@dataclass(frozen=True)
class ShadowWeights:
    """One research node's current target weights, as of one date.

    ``weights`` is keyed by lake symbol (the same spelling
    :attr:`~orchestrator._context.EvaluationContext.closes` and a node's own
    scores use — a venue mapping, if one is needed, is a caller's job, not
    this module's).  ``code_hash`` is the sha256 the reproduced
    :class:`~evaluator.SignalExecution` computed over the very ``code``
    string handed to :func:`shadow_weights`, so a caller can confirm the
    book it is about to trade was priced from the code it thinks it was.
    ``n_scored`` is how many symbols ended up in :attr:`weights`;
    ``n_dropped_unpriced`` and ``n_dropped_unmapped`` are, respectively, how
    many symbols the perp instrument's missing-close rule dropped and how
    many ``allowed_symbols`` excluded — both counted before z-scoring, so
    neither figure is a share of a book that was already dollar-neutral
    without them. ``book_beta`` is ``None`` when the book is not
    beta-neutral (there is no benchmark to rescale against, so there is no
    figure to report) and otherwise the book's own ``Σ w·β`` over whichever
    symbols a beta was measured for — a float, including a vacuous ``0.0``
    when no symbol in the book rated one.
    """

    as_of: dt.date
    weights: dict[str, float]
    code_hash: str
    n_scored: int
    n_dropped_unpriced: int
    n_dropped_unmapped: int
    book_beta: float | None


def _restrict_to_allowed_symbols(
    execution: SignalExecution,
    as_of: dt.date,
    allowed_symbols: Collection[str] | None,
) -> tuple[SignalExecution, int]:
    """Drop, at ``as_of``, any symbol ``allowed_symbols`` does not name.

    ``None`` means no restriction — every symbol the chain scored stays, and
    the drop count is 0, the same "nothing to drop" identity
    :func:`orchestrator._evaluate._drop_unpriced_symbols` answers for the
    spot instrument.  Applied *before* z-scoring (see the module docstring):
    the symbol is removed from the raw vector's own universe and
    (positionally) its scores, the identical transform
    ``_drop_unpriced_symbols`` already applies for its own reason, so the
    two drops compose without either seeing the other's removed symbols.
    """
    if allowed_symbols is None:
        return execution, 0

    import polars as pl

    allowed = set(allowed_symbols)
    vector = execution.vector(as_of)
    assert vector is not None  # execute_signal always scores every date it was given
    keep_mask = [symbol in allowed for symbol in vector.universe]
    dropped = keep_mask.count(False)
    if dropped == 0:
        return execution, 0
    kept_universe = tuple(
        symbol for symbol, keep in zip(vector.universe, keep_mask) if keep
    )
    kept_scores = vector.scores.filter(pl.Series(keep_mask, dtype=pl.Boolean))
    return (
        SignalExecution(
            snapshot_name=execution.snapshot_name,
            code_hash=execution.code_hash,
            seed=execution.seed,
            vectors={as_of: replace(vector, universe=kept_universe, scores=kept_scores)},
        ),
        dropped,
    )


def _require_two_per_leg(day_scores: Mapping[str, float], as_of: dt.date) -> None:
    """Refuse a z-scored cross-section with fewer than two symbols per leg."""
    long_count = sum(1 for value in day_scores.values() if value > 0.0)
    short_count = sum(1 for value in day_scores.values() if value < 0.0)
    if long_count < _MIN_SYMBOLS_PER_LEG or short_count < _MIN_SYMBOLS_PER_LEG:
        raise ShadowError(
            f"{as_of.isoformat()} scored {len(day_scores)} symbol(s) after "
            f"z-scoring, {long_count} long and {short_count} short; a "
            f"forward shadow needs at least {_MIN_SYMBOLS_PER_LEG} symbols "
            "in each leg to stay dollar- and beta-neutral"
        )


def shadow_weights(
    context: EvaluationContext,
    code: str,
    *,
    as_of: dt.date,
    allowed_symbols: Collection[str] | None = None,
) -> ShadowWeights:
    """The research book ``code`` would trade forward, as of ``as_of``.

    Reproduces :func:`orchestrator._evaluate.evaluate_node`'s own chain for
    the single rebalance date ``as_of`` (see the module docstring for the
    exact steps and their order), under the context's own ``seed`` and
    :func:`~orchestrator._context.signal_sandbox`. Never debits
    ``context``'s trial ledger, never calls a null oracle and never writes
    the tree — none of those three objects is even a parameter here. Point
    in time throughout: ``resolve_window`` is sliced at ``as_of``'s own end
    of day, ``execute_signal`` is asked for no other date, and
    ``compute_betas``'s own window never reads a return dated after
    ``as_of``.

    Raises :class:`ShadowError` — see that class's own docstring for the
    three causes it names directly, and the rest it wraps.
    """
    executor = signal_sandbox(context)
    try:
        decision_time = dt.datetime.combine(as_of, _END_OF_DAY)
        resolution = resolve_window(context.snapshot, decision_time)
        execution = execute_signal(
            resolution,
            code,
            seed=context.seed,
            rebalance_dates=[as_of],
            sandbox=executor,
            materialize=_materialize_from_context(context),
        )
        vector: RawScoreVector | None = execution.vector(as_of)
        assert vector is not None  # rebalance_dates=[as_of] always scores as_of
        if not vector.conforming:
            raise ShadowError(
                f"the sandbox did not return a conforming score vector for "
                f"{as_of.isoformat()}: {vector.problems or _executor_failure(executor)}"
            )

        execution, n_dropped_unpriced = _drop_unpriced_symbols(execution, context)
        execution, n_dropped_unmapped = _restrict_to_allowed_symbols(
            execution, as_of, allowed_symbols
        )

        scores, _flat_dates = _score_rebalance_dates(execution, f"shadow:{as_of.isoformat()}")
        day_scores = scores.get(as_of, {})
        _require_two_per_leg(day_scores, as_of)

        betas: Mapping[str, float] | None = None
        if context.book.beta_neutral:
            benchmark = context.book.beta_benchmark
            if as_of not in context.closes.get(benchmark, {}):
                raise ShadowError(
                    f"{as_of.isoformat()} has no perp close for the beta "
                    f"benchmark {benchmark!r}, and the book is beta-neutral: "
                    "a forward shadow cannot rescale a book it cannot "
                    "benchmark"
                )
            betas = compute_betas(context, {as_of: day_scores}).get(as_of, {})

        weights = book_weights(day_scores, betas if context.book.beta_neutral else None)
    except ShadowError:
        raise
    except Exception as exc:  # every chain failure becomes one ShadowError
        raise ShadowError(
            f"shadow_weights could not price {as_of.isoformat()}: {exc}"
        ) from exc

    book_beta: float | None = None
    if context.book.beta_neutral:
        assert betas is not None
        book_beta = math.fsum(
            weights[symbol] * betas[symbol] for symbol in weights if symbol in betas
        )

    return ShadowWeights(
        as_of=as_of,
        weights=weights,
        code_hash=execution.code_hash,
        n_scored=len(weights),
        n_dropped_unpriced=n_dropped_unpriced,
        n_dropped_unmapped=n_dropped_unmapped,
        book_beta=book_beta,
    )
