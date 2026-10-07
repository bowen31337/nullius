"""The node metrics — pipeline step 8, feature 80.

app_spec.xml feature 80: *"System computes ic_mean, ic_tstat, ir_standalone
and turnover, persisting each as a scalar on the node record."*
docs/nullius-tech-architecture.md §6.1 names the step —
``8. compute_metrics    IC series, IR, turnover, decay, capacity, regime
attribution`` — and §9.1 names where the four scalars land: the ``node``
table's ``ic_mean``, ``ic_tstat``, ``ir_standalone`` and ``turnover`` columns.
docs/alpha-engine-prd.md's node block spells the same four under ``metrics``
(``ic_mean``, ``ic_tstat``, ``ir_standalone``, ``turnover``), beside the
series the artifact keeps in full (``ic_series``, ``turnover_series``) and the
two metrics that are not this module's — ``ir_marginal`` is feature 83's,
computed against the current book at step 9, and ``cost_adjusted_ir`` and
``perturb_stability`` are step 10's tripwire metrics.  The computation lives
here; :mod:`evaluator._metrics_store` writes it down, on the split this package
already uses four times (``_identity`` computes and ``_store`` persists for
feature 70, ``_costs`` and ``_cost_store`` for 79, ``_capacity`` and
``_capacity_store`` for 82, ``_decay`` and ``_decay_store`` for 81), and it is
the split feature 80 owns: this module computes the four scalars, and the
store persists them.

Four decisions carry the feature, and each is a pin rather than a knob:

*the four scalars are computed over the *post-cost* returns, on the rebalance
grid, and that is feature 79's record, not a second panel.*
    The four scalars are all functions of one thing — what the signal earned,
    net of fees, on the dates it was scored — and step 7 has already produced
    that thing: :class:`~evaluator.PostCostReturns`, the per-symbol, per-bar,
    per-horizon ``gross − charge`` series, priced by the shared cost library.
    Every metric here is measured from :attr:`PostCostReturns.series` and
    nothing else: the same panel feature 81 correlates against and feature 82
    sizes a book against, so the four scalars sit on one axis with the decay
    profile and the capacity estimate and a reader comparing a node's
    ``ic_mean`` against its ``decay_profile`` is reading numbers measured over
    one priced panel.  Computing them from the gross returns instead would be
    the capacity illusion once more — an edge measured against a return the fee
    schedule then ate — and would put ``ic_mean`` and the decay profile on two
    different panels, which is the divergence the frozen-evaluator contract
    exists to rule out.  This module is therefore the *last* to touch the
    returns: it takes the record feature 79 produced and reduces it, and it
    prices no trade, charges no fee and aligns no target.

*the horizon is the shortest the panel supports, and that is a report, not a
choice.*
    The four scalars are each *one number*, and the panel is five horizons
    deep, so one horizon has to be chosen to reduce over.  The choice is the
    shortest horizon :data:`HORIZONS` names that the priced panel actually
    covers — :data:`METRICS_HORIZON`, resolved by :func:`_metrics_horizon` — and
    it is the binding horizon for the same reason feature 82 reports the
    minimum capacity there: the shortest horizon is the one the signal turns
    over fastest on, the one with the most rebalance dates and so the tightest
    evidence, and the one whose fees bite hardest, so a signal that earns its
    edge only after costs on the shortest horizon is the strongest claim the
    node can make.  "Shortest supported" is not a free parameter a caller
    tunes: it is a function of the panel (the horizons the spec names, in
    ascending order, taking the first the returns cover), so two deployments of
    the same evaluator report the same four numbers for the same node, which is
    what a stored scalar that is compared across nodes and across cycles must
    be.  A horizon the panel does not cover is *absent*, not zero — :func:`at`
    returns an empty mapping on a miss — and a panel that covers no horizon at
    all is refused outright (nothing measured, no metrics to store — the same
    stance :func:`apply_costs` and :func:`estimate_capacity` take).

*each scalar is a definition, pinned here and stated once.*
    The four are the standard cross-sectional signal metrics, and each is
    pinned to one closed form so a stored value means the same thing wherever
    it is read:

    - ``ic_mean`` is the equal-weight mean over the rebalance dates of the
      per-date information coefficient — the Spearman rank correlation of the
      day's normalized score against the day's post-cost return over the
      symbols both carry — which is *exactly* the coefficient feature 81
      measures at this horizon (:func:`evaluator._decay._rank_correlation`,
      the one spelling of the rank transform feature 74 pins for the scores),
      so ``ic_mean`` is the mean of the very series the artifact files as
      ``ic_series.parquet`` and the mean feature 81's per-date coefficients
      reduce to at this horizon.  It is not a Pearson correlation of the raw
      scores, which would not share feature 74's sign-and-scale invariance and
      so could move when nothing about the signal's ordering did.
    - ``ic_tstat`` is ``ic_mean / SE(ic_mean)``, the mean coefficient divided by
      the standard error of the mean of the per-date coefficients —
      ``std(ddof=1) / √n`` — which is the standard error the t-statistic needs
      (the uncertainty is in the *mean across dates*, so the dispersion that
      enters is the cross-date dispersion of the per-date coefficients, not the
      cross-sectional dispersion within a date), with the population
      convention pinned (the dates are the whole sample the node was measured
      over, not a draw from a larger super-population, so the standard error is
      ``std(ddof=0) / √n`` rather than the sample one) and ``n ≥ 2`` required
      (a t-statistic with one observation names a standard error of zero and a
      division by it — a fabricated infinity — so a horizon with fewer than two
      dates is refused rather than defaulted).  The t-statistic is the
      promotion-relevant number and the one the PRD's multiple-testing bars
      (the null-max-Sharpe table, the ``√(1/T)`` standard error) are stated in,
      so it is pinned here rather than left to a reader to divide the mean by an
      error of its own choosing.
    - ``ir_standalone`` is the node's own dollar-neutral book's information
      ratio over the dates — the mean per-date book post-cost return divided
      by the population standard deviation of those returns — the
      "standalone" counterpart to feature 83's ``ir_marginal`` (which is
      measured against a book), and the number the PRD's ``IR ≈ IC × √breadth``
      names: the mean and the standard deviation are taken over the *same*
      per-date book returns, so the ratio is the Sharpe-like reward-to-variance
      of holding *this signal's own* book on this panel, cost-adjusted, on the
      same horizon ``ic_mean`` is measured over. The book on each date is the
      long-short portfolio the day's normalized scores define — weight
      ``w_i = z_i / Σ|z_j|`` over the symbols that date's scores and post-cost
      returns share, so gross exposure is 1 and net is 0 whenever the scores
      were cross-sectionally centered — not the equal-weight market every node
      scored on the same snapshot would otherwise share, whatever it scored.
    - ``turnover`` is that same book's mean per-date fractional turnover — the
      fraction of the book's weight that changes hands at each rebalance,
      ``½ · Σ |w_{d} − w_{d−1}|`` summed over the symbols (a symbol absent from
      one date's book holds weight 0 there), averaged over the dates that have
      a predecessor — which is the standard "how much of the book is replaced
      each period" number the PRD's ``turnover_series`` is the per-date record
      of, and the number the live loop's turnover gauge reads.

    None of the four is a second implementation of anything: the coefficient is
    feature 81's, the means and standard deviations are the one reduction
    feature 82's attribution shares, and the turnover is the per-date book
    weight this module derives from the node's own scores — not feature 82's
    equal-weight unit book, which is pinned separately and stays equal-weight
    (step 8's capacity half sizes a different, deliberately unit-weighted book).

*the scalars are scalars, and the series is not reduced away here.*
    The feature names four scalars and the PRD's artifact keeps ``ic_series``
    and ``turnover_series`` in full (feature 169); this module computes the
    four scalars only and does not emit the series — ``ic_mean`` is the mean of
    the series feature 81 already produces per date, and ``turnover`` is the
    mean of a series this module does not persist — so the four numbers are the
    whole of what lands on the node record, and the series stays where the
    artifact keeps it.  A scalar without its series is not stored here: the
    four arrive together, in one record, and the store persists them in one
    row and one transaction.

**Absence is not zero**, three times over.  A horizon the priced panel does not
cover carries no metric — a panel that covers no horizon at all is refused
outright (nothing measured, no metrics to store), and a horizon with fewer than
two dates is refused rather than defaulted (a t-statistic over one date names a
zero standard error and a fabricated infinity).  A symbol on a covered date that
one side carries and the other does not is simply not in that date's joined
cross-section — feature 75's absence rule — and neither side is zero-filled to
become one.

**What this module does not do.**  It computes no other metric — ``ir_marginal``
is feature 83, ``cost_adjusted_ir`` and ``perturb_stability`` are step 10's
tripwire metrics, the decay profile feature 81, capacity and regime attribution
feature 82 — it does not normalize (feature 74's ``normalize_scores`` ran two
steps earlier; this step takes the post-cost returns), align (75), gate (76),
price (79), persist (:mod:`evaluator._metrics_store` owns the write) or score
(feature 73).  It takes step 7's record and answers exactly the four questions
step 8 puts in its scope: *what is the mean information coefficient, how much
evidence stands behind it, what is the node's own dollar-neutral book's
information ratio, and how much of that book turns over each period?*

**The layering note.**  This module is stdlib-only — dates, mappings, square
roots and arithmetic; no polars, no pyarrow, no lake, no environment, no HTTP,
and no import of any other member.  The returns arrive as a value (feature 79's
record), so the Polars boundary stays at the edge of the package where every
other member keeps it, which is what makes importing this member cost
composition — and the replay path §1 forbids from reaching the evaluator —
nothing at all.  The coefficient it needs is imported from :mod:`evaluator._decay`
(the one spelling of the rank transform), so this module depends on that one
member and no other.
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ._align import HORIZONS
from ._costs import PostCostReturns
from ._decay import _rank_correlation
from ._errors import EvaluatorMetricsError

__all__ = [
    "METRICS_HORIZON",
    "METRICS_STEP",
    "NodeMetrics",
    "compute_node_metrics",
]

#: The pipeline-step name, in §6.1's own spelling.  Step 8 is the metrics
#: step — ``compute_metrics    IC series, IR, turnover, decay, capacity,
#: regime attribution`` — and this module owns the *IC, IR and turnover*
#: items on that list (the decay, capacity and attribution items are features
#: 81 and 82).  Shared vocabulary: the feature sentence, the refusals below,
#: and every reader of a persisted metric name the one step that computes the
#: node's scalars, and they name it once.
METRICS_STEP: str = "compute_metrics"

#: The horizon the four scalars are computed over — a *policy*, not a number.
#: The four scalars are each one number, and the panel is five horizons deep,
#: so one horizon has to be chosen to reduce over; the policy is "the shortest
#: horizon :data:`HORIZONS` names that the priced panel actually covers", which
#: is the binding horizon for the reasons the module docstring states.  It is
#: not a fixed integer because it is a function of the panel — the first
#: horizon, in the spec's ascending order, whose series has a rebalance date —
#: so two deployments report the same four numbers for the same node.  The
#: resolved value for a given bundle is :attr:`NodeMetrics.horizon`; this name
#: is the policy the resolution implements, and it is what the store and the
#: docstrings refer to when they say "one pinned horizon".
METRICS_HORIZON: str = "the shortest horizon the priced panel covers"


def _metrics_horizon(returns: PostCostReturns) -> int:
    """The horizon the four scalars are computed over — the shortest covered.

    The shortest horizon :data:`HORIZONS` names that the priced panel actually
    covers — the first horizon, in the spec's ascending order, whose series has
    at least one rebalance date — which is the binding horizon for the reasons
    the module docstring states: the fastest-turning, best-evidenced,
    hardest-hit horizon is the strongest claim the node can make, and
    "shortest supported" is a function of the panel rather than a caller's
    knob, so two deployments report the same four numbers for the same node.

    Refused when the panel covers no horizon at all: a bundle whose every
    series is empty measured nothing, and there are no metrics to store — the
    same stance :func:`apply_costs` and :func:`estimate_capacity` take.
    """
    for horizon in HORIZONS:
        if returns.series[horizon].dates():
            return horizon
    raise EvaluatorMetricsError(
        "the post-cost panel covers no horizon at any of the horizons the "
        f"spec names ({', '.join(str(h) for h in HORIZONS)}), so there is "
        "nothing to compute ic_mean, ic_tstat, ir_standalone or turnover "
        "over; the priced panel measured no rebalance date — score and price "
        "an alignment with coverage first (features 75 through 79)"
    )


@dataclass(frozen=True)
class NodeMetrics:
    """Step 8's four scalar answers — ic_mean, ic_tstat, ir_standalone, turnover.

    The four numbers feature 80 persists on the node record, each pinned to one
    closed form (see the module docstring), all measured over one horizon —
    :data:`METRICS_HORIZON`, the shortest the priced panel covers — and stamped
    with the evaluation's provenance (node, sealed snapshot, cost model) for the
    reason the capacity and decay records carry it: the scalars are functions of
    a *priced* panel, two fee schedules net different post-cost returns out of
    the same gross ones, so the pair belongs in the identity of the metrics and
    in the store's key beside the node, exactly as it is in the signal-returns,
    capacity and decay tables.

    The terms are carried beside the four numbers because a scalar alone cannot
    be checked or read: :attr:`dates` and :attr:`horizon` say how much evidence
    stood behind ``ic_tstat``, :attr:`ic_mean` must be the mean of its own
    per-date coefficients (enforced at construction and again on every read-back
    — the defence the identity store applies to a hash that does not fold from
    its terms), and :attr:`turnover_dates` says how many rebalances the turnover
    averaged over (one fewer than :attr:`dates`, since turnover needs a
    predecessor).
    """

    #: The node whose signal was measured.
    node_id: str
    #: The canonical name of the sealed snapshot the panel was measured in.
    snapshot_name: str
    #: The cost model the returns were netted against.
    cost_model: object
    #: The horizon the four scalars were computed over — :data:`METRICS_HORIZON`.
    horizon: int
    #: How many rebalance dates the horizon measured — the denominator behind
    #: ``ic_mean`` and ``ic_tstat``.
    dates: int
    #: The equal-weight mean of the per-date information coefficients —
    #: ``ic_mean``, the mean of the series the artifact files as
    #: ``ic_series.parquet``.
    ic_mean: float
    #: The standard error of the mean of the per-date coefficients — what
    #: ``ic_mean`` is divided by to give ``ic_tstat``.
    ic_se: float
    #: ``ic_mean / ic_se`` — ``ic_tstat``, the promotion-relevant evidence.
    ic_tstat: float
    #: The node's own dollar-neutral book's information ratio over the dates —
    #: the mean per-date book post-cost return divided by its population
    #: standard deviation.
    ir_standalone: float
    #: That same book's mean per-date fractional turnover.
    turnover: float
    #: How many rebalances turnover averaged over — one fewer than :attr:`dates`.
    turnover_dates: int
    #: The per-date information coefficients — the series whose mean is
    #: ``ic_mean``, carried so the store can check the mean against it.
    ic_series: Mapping[dt.date, float]
    #: The per-date dollar-neutral book returns — the series
    #: :attr:`ir_standalone`'s mean and population standard deviation reduce
    #: from, carried beside it the way :attr:`ic_series` is carried beside
    #: ``ic_mean``. Empty on a record rebuilt from the metrics store, which
    #: persists only the four scalars and :attr:`ic_series`; a fresh
    #: measurement from :func:`compute_node_metrics` always carries it, and
    #: that is what :mod:`evaluator._persist_store`'s ``cost_adjusted_ir``
    #: reduces, rather than re-deriving a second, possibly different, book
    #: from the raw panel (which would need the normalized scores this record
    #: does not otherwise carry). Excluded from equality (``compare=False``):
    #: a record rebuilt from the store is still the same measurement as the
    #: one that produced it even though the store carries no column for this
    #: field, the same way a reader must not see two NodeMetrics for one
    #: evaluation disagree merely because one came fresh off the pipeline and
    #: the other off a read-back.
    book_returns: Mapping[dt.date, float] = field(
        default_factory=lambda: MappingProxyType({}), compare=False
    )
    #: The per-date fractional turnover of the node's own dollar-neutral
    #: book — the series whose mean is :attr:`turnover`, carried beside it the
    #: way :attr:`book_returns` is carried beside :attr:`ir_standalone`. Keyed
    #: by the later date of each consecutive pair of rebalance dates (turnover
    #: needs a predecessor), so it carries :attr:`turnover_dates` entries, one
    #: fewer than :attr:`ic_series`. Empty on a record rebuilt from the
    #: metrics store, which persists only the four scalars and
    #: :attr:`ic_series`; a fresh measurement from :func:`compute_node_metrics`
    #: always carries it, and that is what
    #: :func:`evaluator._artifact.render_turnover_series` renders, rather than
    #: re-deriving a different book from the raw panel. Excluded from equality
    #: (``compare=False``) for the same reason :attr:`book_returns` is.
    turnover_series: Mapping[dt.date, float] = field(
        default_factory=lambda: MappingProxyType({}), compare=False
    )

    def __post_init__(self) -> None:
        # object.__setattr__ where the constructor normalizes; this record
        # validates only, like the per-horizon capacity and decay it sits beside.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise EvaluatorMetricsError(
                "a node metrics must name the node whose signal it measures, "
                f"got {self.node_id!r}"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorMetricsError(
                "a node metrics must name the sealed snapshot its panel was "
                f"measured in, got {self.snapshot_name!r}"
            )
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise EvaluatorMetricsError(
                f"a node metrics' horizon must be an integer period count, "
                f"got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise EvaluatorMetricsError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}); the metrics "
                "are computed over one pinned horizon, and that horizon is one "
                "the spec covers"
            )
        captured: dict[dt.date, float] = {}
        for day, value in self.ic_series.items():
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorMetricsError(
                    f"an ic_series must be keyed by calendar dates, got {day!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMetricsError(
                    f"the information coefficient on {day.isoformat()} must be "
                    f"a number, got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise EvaluatorMetricsError(
                    f"the information coefficient on {day.isoformat()} is not "
                    f"finite ({value!r}); a NaN or ±inf would reach the node "
                    "record dressed as a measurement"
                )
            captured[day] = float(value)
        object.__setattr__(self, "ic_series", MappingProxyType(captured))
        if not captured:
            raise EvaluatorMetricsError(
                "a node metrics carries an empty ic_series; a horizon that "
                "measured no date carries no metrics at all — refuse the "
                "bundle before constructing the record"
            )
        if self.dates != len(captured):
            raise EvaluatorMetricsError(
                f"the node metrics claims {self.dates} measured dates but its "
                f"ic_series carries {len(captured)}; the count is the "
                "denominator of ic_mean and ic_tstat, and a record whose "
                "denominator disagrees with its own series is a record no "
                "reader can size the evidence behind"
            )
        for field_name in ("ic_mean", "ic_se", "ic_tstat", "ir_standalone", "turnover"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMetricsError(
                    f"a node metrics' {field_name} must be a number, got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise EvaluatorMetricsError(
                    f"a node metrics' {field_name} is not finite ({value!r}); a NaN "
                    "or ±inf would reach the node record dressed as a "
                    "measurement"
                )
            object.__setattr__(self, field_name, float(value))
        expected_mean = math.fsum(
            captured[day] for day in sorted(captured)
        ) / len(captured)
        if self.ic_mean != expected_mean:
            raise EvaluatorMetricsError(
                f"the node metrics says ic_mean is {self.ic_mean!r} but its "
                f"own ic_series mean to {expected_mean!r}; the record disagrees "
                "with itself, so it was built somewhere other than this "
                "module's arithmetic — a scalar the node record would trust and "
                "be wrong by"
            )
        if isinstance(self.turnover_dates, bool) or not isinstance(
            self.turnover_dates, int
        ):
            raise EvaluatorMetricsError(
                f"a node metrics' turnover_dates must be an integer, got "
                f"{self.turnover_dates!r}"
            )
        if self.turnover_dates != max(0, len(captured) - 1):
            raise EvaluatorMetricsError(
                f"the node metrics says turnover was averaged over "
                f"{self.turnover_dates} dates but its ic_series carries "
                f"{len(captured)}; turnover needs a predecessor for each "
                "rebalance it averages over, so it is one fewer than the date "
                "count, and a record that disagrees with its own series is a "
                "record no reader can size the turnover behind"
            )
        captured_book: dict[dt.date, float] = {}
        for day, value in self.book_returns.items():
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorMetricsError(
                    "a node metrics' book_returns must be keyed by calendar "
                    f"dates, got {day!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMetricsError(
                    f"the book return on {day.isoformat()} must be a number, "
                    f"got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise EvaluatorMetricsError(
                    f"the book return on {day.isoformat()} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node record "
                    "dressed as a measurement"
                )
            captured_book[day] = float(value)
        object.__setattr__(self, "book_returns", MappingProxyType(captured_book))
        captured_turnover: dict[dt.date, float] = {}
        for day, value in self.turnover_series.items():
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorMetricsError(
                    "a node metrics' turnover_series must be keyed by "
                    f"calendar dates, got {day!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMetricsError(
                    f"the turnover on {day.isoformat()} must be a number, "
                    f"got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise EvaluatorMetricsError(
                    f"the turnover on {day.isoformat()} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node record "
                    "dressed as a measurement"
                )
            captured_turnover[day] = float(value)
        object.__setattr__(
            self, "turnover_series", MappingProxyType(captured_turnover)
        )

    def __hash__(self) -> int:
        # The mapping is not hashable until it collapses to tuples; the fold
        # keeps __hash__ consistent with __eq__, as every record in this
        # package does.
        return hash(
            (
                self.node_id,
                self.snapshot_name,
                self.cost_model,
                self.horizon,
                self.ic_mean,
                self.ic_se,
                self.ic_tstat,
                self.ir_standalone,
                self.turnover,
                self.turnover_dates,
                tuple(sorted(self.ic_series.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"NodeMetrics(node={self.node_id!r}, horizon={self.horizon}, "
            f"ic_mean={self.ic_mean:+.4f}, ic_tstat={self.ic_tstat:+.3f}, "
            f"ir={self.ir_standalone:+.3f}, turnover={self.turnover:.3f}, "
            f"{self.dates} dates)"
        )


def compute_node_metrics(
    returns: PostCostReturns,
    scores: Mapping[dt.date | str, Mapping[str, float]],
) -> NodeMetrics:
    """Compute the four node scalars — ic_mean, ic_tstat, ir_standalone, turnover.

    Feature 80's computation: over :data:`METRICS_HORIZON` (the shortest horizon
    :data:`HORIZONS` names that the priced panel covers), for each rebalance date
    that horizon prices, correlate the day's normalized scores against the day's
    post-cost returns — both reduced to average ranks, so the coefficient is the
    Spearman rank correlation feature 81 measures — over the symbols the two
    sides share, then weight that same joined cross-section by the day's own
    normalized scores (``w_i = z_i / Σ|z_j|``, a dollar-neutral book: gross
    exposure 1, net 0) to get the day's book return, and reduce the per-date
    coefficients and the per-date book returns into the four scalars.

    ``returns`` is step 7's own record (:class:`~evaluator.PostCostReturns`),
    and ``scores`` is step 3's own output as ``{rebalance date: {symbol:
    normalized score}}`` — :func:`evaluator.normalize_scores`' vector paired
    with the universe it was scored against (``RawScoreVector.universe``), which
    is how the Polars boundary stays at the edge of this package.  Dates the
    priced grid does not carry are ignored, and a symbol on a covered date that
    one side carries and the other does not is simply not in that date's joined
    cross-section — feature 75's absence rule, applied to both sides at once.

    Raises :class:`~evaluator.EvaluatorMetricsError`, each with its reason (see
    ``_errors``): a ``returns`` that is not step 7's own result; a ``scores``
    mapping that is malformed, empty, or carries a non-finite value; a panel
    that covers no horizon at all (nothing measured); a horizon with fewer than
    two dates (a t-statistic over one date names a zero standard error and a
    fabricated infinity); and — via the record — a hand-built metrics whose
    scalars do not reduce from their own terms.
    """
    if not isinstance(returns, PostCostReturns):
        raise EvaluatorMetricsError(
            "compute_node_metrics reduces step 7's own result — a "
            "PostCostReturns, the priced series the cost schedule produced — "
            f"got {type(returns).__name__}; the four scalars are measured from "
            "the post-cost returns, and the gross series alone cannot say which "
            "schedule priced them"
        )
    if not isinstance(scores, Mapping):
        raise EvaluatorMetricsError(
            "the normalized scores must map rebalance date to {symbol: "
            f"score{'}'}, got {type(scores).__name__}; pass step 3's output "
            "(feature 74) paired with the universe it was scored against"
        )
    validated: dict[dt.date, Mapping[str, float]] = {}
    for key, row in scores.items():
        if isinstance(key, dt.datetime):
            raise EvaluatorMetricsError(
                f"the normalized scores are keyed by a datetime ({key!r}); the "
                "metrics pair one rebalance date's cross-section with that "
                "date's forward return — key by the calendar date (or its ISO "
                "string)"
            )
        if isinstance(key, dt.date):
            day = key
        elif isinstance(key, str):
            try:
                day = dt.date.fromisoformat(key)
            except ValueError as exc:
                raise EvaluatorMetricsError(
                    f"the score date {key!r} is not an ISO date; the scores are "
                    "keyed by rebalance dates (or ISO date strings), one per bar"
                ) from exc
        else:
            raise EvaluatorMetricsError(
                f"score dates must be dates or ISO date strings, got {key!r} "
                f"({type(key).__name__})"
            )
        if day in validated:
            raise EvaluatorMetricsError(
                f"the normalized scores carry {day.isoformat()} twice under "
                "different spellings; one bar, one cross-section"
            )
        if not isinstance(row, Mapping):
            raise EvaluatorMetricsError(
                f"the normalized scores for {day.isoformat()} must map symbol "
                f"to a score, got {type(row).__name__}"
            )
        inner: dict[str, float] = {}
        for symbol, value in row.items():
            if not isinstance(symbol, str) or not symbol:
                raise EvaluatorMetricsError(
                    f"the normalized scores for {day.isoformat()} must be "
                    f"keyed by non-empty symbol names, got {symbol!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMetricsError(
                    f"the normalized score for {symbol!r} on {day.isoformat()} "
                    f"must be a number, got {value!r}"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EvaluatorMetricsError(
                    f"the normalized score for {symbol!r} on {day.isoformat()} "
                    f"is not finite ({value!r}); a NaN or ±inf would reach the "
                    "node metrics dressed as a measurement"
                )
            inner[symbol] = number
        if inner:
            validated[day] = MappingProxyType(inner)

    horizon = _metrics_horizon(returns)
    series = returns.series[horizon]
    per_date_ic: dict[dt.date, float] = {}
    per_date_return: dict[dt.date, float] = {}
    per_date_weights: dict[dt.date, Mapping[str, float]] = {}
    for day in series.dates():
        score_row = validated.get(day)
        if score_row is None:
            # The grid the returns priced is what defines the panel; a scored
            # date this horizon did not price has no forward return to pair,
            # and inventing one is the look-ahead the alignment refuses.
            continue
        returns_row = series.at(day)
        per_date_ic[day] = _rank_correlation(
            score_row, returns_row, day=day, horizon=horizon
        )
        # The node's book on this date is the dollar-neutral long-short
        # portfolio its own normalized scores define, over the same joined
        # cross-section the coefficient above was just measured on (a symbol
        # with no forward return has nothing a weight could be multiplied
        # against). Weight w_i = z_i / Σ|z_j|, so gross exposure is 1 and net
        # is 0 whenever the scores were cross-sectionally centered over this
        # cross-section — this signal's own book, not the equal-weight market
        # every node scored on the same snapshot would otherwise share.
        book_symbols = sorted(set(score_row) & set(returns_row))
        gross = math.fsum(abs(score_row[symbol]) for symbol in book_symbols)
        if gross == 0.0:
            # _rank_correlation above already required these same symbols'
            # scores to have nonzero rank spread, so they cannot all be
            # exactly zero; unreachable in practice, refused rather than
            # producing a NaN book if that invariant is ever broken.
            raise EvaluatorMetricsError(
                f"horizon {horizon} on {day.isoformat()} has an all-zero "
                "normalized score across its joined cross-section, so the "
                "dollar-neutral book's weights are undefined; refusing "
                "rather than dividing by zero"
            )
        weights = {symbol: score_row[symbol] / gross for symbol in book_symbols}
        per_date_weights[day] = weights
        per_date_return[day] = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in book_symbols
        )
    if not per_date_ic:
        raise EvaluatorMetricsError(
            "the priced panel and the normalized scores share no rebalance "
            "date at the metrics horizon, so no information coefficient was "
            "measured and there are no node metrics to store — score and price "
            "an alignment with coverage first (features 75 through 79)"
        )

    count = len(per_date_ic)
    ic_mean = math.fsum(per_date_ic[day] for day in sorted(per_date_ic)) / count
    if count < 2:
        # A t-statistic over one date names a standard error of zero and a
        # division by it — a fabricated infinity — so a horizon with fewer than
        # two measured dates is refused rather than defaulted.
        raise EvaluatorMetricsError(
            f"the metrics horizon ({horizon}) measured only {count} rebalance "
            "date; ic_tstat is ic_mean over the standard error of the mean of "
            "the per-date coefficients, and that standard error is undefined "
            "over a single date — refusing rather than dividing by zero"
        )
    deviations = [per_date_ic[day] - ic_mean for day in sorted(per_date_ic)]
    variance = math.fsum(d * d for d in deviations) / count  # population ddof=0
    ic_se = math.sqrt(variance) / math.sqrt(count)
    if ic_se == 0.0:
        # Every date measured the same information coefficient — the standard
        # error of the mean is zero and ic_tstat names a fabricated infinity,
        # so refusing rather than dividing by zero is the same stance the
        # coefficient takes on a constant side and ir_standalone on a constant
        # book: a metrics that never varied across dates has no evidence ratio.
        raise EvaluatorMetricsError(
            f"the metrics horizon ({horizon}) measured the same information "
            "coefficient on every date, so the standard error of the mean is "
            "zero and ic_tstat is undefined; refusing rather than dividing by "
            "zero — a signal whose per-date evidence never varied has no "
            "t-statistic"
        )
    ic_tstat = ic_mean / ic_se

    returns_values = [per_date_return[day] for day in sorted(per_date_return)]
    n_return = len(returns_values)
    return_mean = math.fsum(returns_values) / n_return
    return_deviations = [value - return_mean for value in returns_values]
    return_variance = math.fsum(d * d for d in return_deviations) / n_return
    return_std = math.sqrt(return_variance)
    if return_std == 0.0:
        # The node's dollar-neutral book earned the same post-cost return
        # every date — the signal expressed no cross-sectional edge on the
        # priced panel, so the information ratio is undefined; refusing
        # rather than dividing by zero, the same stance the coefficient
        # takes on a constant side.
        raise EvaluatorMetricsError(
            f"the metrics horizon ({horizon}) book returned a constant "
            "post-cost return across its dates, so its standard deviation is "
            "zero and ir_standalone is undefined; refusing rather than "
            "dividing by zero — a book that never varied has no "
            "reward-to-variance ratio"
        )
    ir_standalone = return_mean / return_std

    ordered_days = sorted(per_date_return)
    turnover_sum = 0.0
    turnover_count = 0
    per_date_turnover: dict[dt.date, float] = {}
    for prev_day, day in itertools.pairwise(ordered_days):
        prev_weights = per_date_weights[prev_day]
        day_weights = per_date_weights[day]
        # A symbol that enters or exits the book (or whose weight simply
        # moves) contributes |w_d − w_{d−1}|; a symbol absent from one side
        # holds weight 0 there, the same absence convention the book return
        # itself uses.
        symbols = set(prev_weights) | set(day_weights)
        day_turnover = 0.5 * math.fsum(
            abs(day_weights.get(symbol, 0.0) - prev_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        per_date_turnover[day] = day_turnover
        turnover_sum += day_turnover
        turnover_count += 1
    turnover = turnover_sum / turnover_count if turnover_count else 0.0

    return NodeMetrics(
        node_id=returns.node_id,
        snapshot_name=returns.snapshot_name,
        cost_model=returns.cost_model,
        horizon=horizon,
        dates=count,
        ic_mean=ic_mean,
        ic_se=ic_se,
        ic_tstat=ic_tstat,
        ir_standalone=ir_standalone,
        turnover=turnover,
        turnover_dates=turnover_count,
        ic_series=per_date_ic,
        book_returns=per_date_return,
        turnover_series=per_date_turnover,
    )
