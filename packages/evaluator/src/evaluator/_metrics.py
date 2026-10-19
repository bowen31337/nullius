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

**Turnover cost is charged here, not where the returns were priced.**  Step 7
(:func:`apply_costs`) charges one taker fee per symbol, uniformly, against
every return it prices, and a uniform fee charged against a dollar-neutral
book *cancels*: the book return is ``Σ w_i (r_i − f) = Σ w_i r_i − f · Σ w_i``,
and ``Σ w_i = 0`` by construction (``w_i = z_i / Σ|z_j|`` over centered
scores), so the fee term vanishes regardless of how much the book actually
traded — a signal that reshuffles its whole book every bar and one that never
changes its ranks would report the identical ``ir_standalone``. Turnover cost
belongs where the weights exist instead, so :func:`compute_node_metrics`
accepts an optional, keyword-only ``cost_per_unit_traded`` (a fraction of
traded notional — ``0.001`` is 10 bps; a negative or non-finite value is
refused) and charges it against the *book* return, not the per-symbol return:
on each book date ``d`` the net return is the gross book return minus
``cost_per_unit_traded × traded_d``, where ``traded_d = Σ|w_d − w_{d-1}|``
over the union of symbols either side holds a weight for (a symbol absent
from one side holds weight 0 there, the same absence convention
:attr:`NodeMetrics.turnover` uses) and, on the first book date — no
predecessor — ``traded_d = Σ|w_d|``, the full cost of putting the book on.
:attr:`NodeMetrics.book_returns`, :attr:`NodeMetrics.ir_standalone` and
everything reduced from them are therefore net of this charge;
:attr:`NodeMetrics.turnover` keeps its own definition (``½ · Σ|Δw|``)
unchanged, since turnover is a fraction of the book, not a cost. The
default, ``cost_per_unit_traded=0.0``, charges nothing and reproduces every
figure this module computed before the parameter existed.

**Volatility scaling is an optional rescale of the scores, before the book.**
A correct ranking of a crypto cross-section is not a tradable book: three to
five times of volatility dispersion between names means the ``z_i / Σ|z_j|``
book quietly hands most of its gross to the few most volatile names, so a
signal whose ordering is right can still lose money on the names whose noise
dominates.  :func:`book_weights` and :func:`compute_node_metrics` therefore
accept an optional, keyword-only ``vols`` — ``{symbol: vol}`` in
:func:`book_weights`, ``{date: {symbol: vol}}`` in
:func:`compute_node_metrics`, the same shape and the same refusals its
``betas`` take.  When given, each score is divided by its own symbol's
volatility *before* the book is normalized (``w_i = (z_i / vol_i) / Σ_j |z_j /
vol_j|``), so the weights are proportional to ``z_i / vol_i`` — an inverse-
volatility book with gross exposure 1, and net 0 exactly when the vol-scaled
cross-section stays centered (which holds whenever both sides of an offsetting
pair of scores carry the same volatility — in particular for any all-equal
``vols`` panel, where the scaling is an identity on the book).  Dividing each
symbol by its own positive scale is not a no-op on the *sum*, so an
inverse-vol book is dollar-neutral by construction of the scores rather than
by construction of the scaling.  The volatility is a positive scale,
not a direction, so a vol that is non-finite or non-positive is refused
**by name** rather than silently defaulted: defaulting it would hand the name a
weight the signal did not ask for, which is a different book than the one the
caller named.  A symbol a date's ``vols`` row simply does not name is not the
same case — that row is the answer to "whose volatility could be measured over
the trailing window", and a name absent from it (too few returns, or a flat
window: a perp delisted in place measures exactly ``0.0``) is **dropped from
that date's book** and the survivors renormalised, with the drop counted in
:attr:`NodeMetrics.vol_dropped`.  That is the one place the two conventions
differ deliberately: :func:`book_weights` still refuses a scored symbol its
``vols`` does not name, because a direct caller handing it an incomplete row
has made an error worth naming, while :func:`compute_node_metrics` — which
*computes* the row from the window — treats a name the window could not measure
as untradeable and leaves it out, rather than discarding every other name's
measurement with it.  The beta-neutral leg rescale, when ``betas`` is also
given, applies *after* the vol scaling, to the vol-scaled weights — the two transforms
compose in the order the sentence names ("proportional to z_i / vol_i, then
applies the existing beta-neutral rescale"), so a book can be both
volatility-scaled and beta-neutral and the beta split is computed on the
weights that will actually be traded.  The default, ``vols=None``, scales
nothing and reproduces every figure this module computed before the parameter
existed.

**A third weighting trades the tails instead of the whole cross-section.**
Both books above weight every scored name in proportion to its own score,
so a ranking whose *ordering* is right everywhere but whose return *gradient*
lives only at the extremes — the middle deciles carrying no relationship to
forward return at all — spreads its gross over the names that carry no
gradient and monetises little of the one it has.  :func:`book_weights` and
:func:`compute_node_metrics` therefore accept a keyword-only ``weighting``,
a closed vocabulary (:data:`WEIGHTINGS`: :data:`Z_WEIGHTING`,
:data:`INVERSE_VOL_WEIGHTING`, :data:`TAIL_DECILE_WEIGHTING`), and under
:data:`TAIL_DECILE_WEIGHTING` each date's book is built from that date's
ranking alone.  The symbols are sorted by score ascending with ties broken by
symbol name — the one deterministic tie-break this workspace uses wherever a
ranking has to be total, since two equal scores are not evidence for one name
over another and an unstable sort would make the book a function of a dict's
insertion order.  The bottom decile is the first ``floor(n/10)`` names and
the top decile the last ``floor(n/10)``; the long leg carries ``+0.5/k`` per
name and the short leg ``-0.5/k``, and every name between them is held at
exactly ``0.0``.  The book is therefore equal-weight within each leg, gross 1
and net 0 **by construction** — no centering of the scores is needed, and the
score's *magnitude* is unused: the book is a function of the ranking.  A
cross-section too thin to hold two non-empty deciles is refused rather than
traded: ``k`` below :data:`TAIL_DECILE_MIN_LEG` names a leg of one name (or
none), which is a directional bet dressed as a cross-sectional one, so
:func:`_tail_decile_weights` raises :class:`EvaluatorMetricsError` naming the
count, and :func:`compute_node_metrics` — the per-date caller — restates it
with the rebalance date the count belongs to.  A ``vols`` panel handed
beside this weighting is ignored, because the two weightings disagree about
what a volatility would even mean here; the beta-neutral leg rescale, when
``betas`` is given, applies *after* the legs are formed, exactly as it does
for the other weightings.  :attr:`NodeMetrics.tail_k` records ``k`` per date.
Every figure this module computed before the parameter existed is unchanged
under the default, :data:`Z_WEIGHTING`.

**Beta-neutral legs are an optional rescale of the same weights.**  The
dollar-neutral book (``w_i = z_i / Σ|z_j|``) is net-zero but not benchmark
beta-neutral: a book tilted toward low-beta names on the long side and
high-beta names on the short side (or the reverse) carries a residual
market-beta exposure that is not the signal's edge.  :func:`compute_node_metrics`
accepts an optional, keyword-only ``betas`` (``{date: {symbol: beta}}``); when
given, each date's book is split into its long leg (``w > 0``) and short leg
(``w < 0``), and the symbols either leg has a beta for are weight-averaged
into ``β_L`` and ``β_S`` (``Σ w·β / Σ w`` over the rated symbols of that leg —
well-defined for the short leg too, since a negative numerator over a negative
denominator is the ordinary positive weighted mean of the shorted names'
betas). The rated symbols of each leg are then rescaled so the *whole* leg
(rated weight plus whatever unrated weight it already carries, which is left
untouched) reaches gross ``gl`` for the long leg and ``1 − gl`` for the short,
with ``gl = β_S / (β_L + β_S)`` — the split that makes ``gl·β_L = (1 − gl)·β_S``,
so the book's net beta (``Σ w·β`` over the rated symbols) is exactly zero
when every symbol in the book is rated, and total gross exposure is still 1
either way, because the two legs' targets still sum to 1 and the unrated
weight moved from nowhere. A date falls back to the plain weights — no
rescale — whenever the split cannot be done: either leg has no rated
symbols (``β_L`` or ``β_S`` would be a division by zero), ``β_L + β_S ≤ 0``
(the split ``gl`` would be undefined or outside ``[0, 1]``), or the unrated
weight already parked in a leg exceeds that leg's target gross (the rated
symbols would have to carry negative gross to compensate, which would flip
their sign). The rescaled weights feed the book return, the turnover and the
COST-1 turnover charge exactly as the plain weights did — cost reflects what
the beta-neutral book actually trades — while ``ic_mean`` and ``ic_tstat`` are
unchanged, since the coefficient is rank-based on the scores, not the
weights. The default, ``betas=None``, never attempts a rescale and reproduces
every figure this module computed before the parameter existed.

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
    "INVERSE_VOL_WEIGHTING",
    "METRICS_HORIZON",
    "METRICS_STEP",
    "NodeMetrics",
    "TAIL_DECILE_MIN_LEG",
    "TAIL_DECILE_WEIGHTING",
    "WEIGHTINGS",
    "Z_WEIGHTING",
    "book_weights",
    "compute_node_metrics",
]

#: The weightings :func:`book_weights` and :func:`compute_node_metrics` build a
#: date's book under — closed, the same stance :data:`HORIZONS` takes toward
#: its own five-member set, because a weighting is the *whole* book's
#: construction: running one a caller never named is measuring a different
#: portfolio than the one asked for.
#:
#: * :data:`Z_WEIGHTING` — ``w_i = z_i / Σ|z_j|``, the score-proportional
#:   dollar-neutral book this module has always built, and the default.  It is
#:   also the *permissive* spelling: with ``vols`` given it means the
#:   inverse-volatility book, exactly as it did before this parameter existed,
#:   so every caller that predates the parameter keeps its byte-for-byte
#:   behaviour.
#: * :data:`INVERSE_VOL_WEIGHTING` — each score divided by its own symbol's
#:   volatility, then normalized (see the module docstring).  It is what
#:   ``vols=<a panel>`` means, so the two must agree: naming this weighting
#:   while handing ``vols=None`` is refused **by name**, rather than quietly
#:   building the z book under an inverse-vol label.
#: * :data:`TAIL_DECILE_WEIGHTING` — long the top decile of the day's scores
#:   and short the bottom decile, equal-weight within each leg (see
#:   :func:`_tail_decile_weights`), for a ranking whose return gradient lives
#:   in its tails.  ``vols`` is ignored under it.
Z_WEIGHTING: str = "z"
INVERSE_VOL_WEIGHTING: str = "inverse_vol"
TAIL_DECILE_WEIGHTING: str = "tail_decile"
WEIGHTINGS: tuple[str, str, str] = (
    Z_WEIGHTING,
    INVERSE_VOL_WEIGHTING,
    TAIL_DECILE_WEIGHTING,
)

#: The fewest names either leg of a tail-decile book may hold — two, the floor
#: :mod:`orchestrator._shadow` already applies to a dollar-neutral book's legs
#: ("a dollar-neutral book needs real diversification on both sides, not one
#: name per leg"), restated here because it is now this module's own refusal:
#: a leg of one name *is* that name, so the "decile" would be a directional bet
#: dressed as a cross-sectional one.  Each leg holds ``floor(n/10)`` names, so
#: this floor is met exactly when the date's cross-section carries at least
#: ``10 × TAIL_DECILE_MIN_LEG`` = 20 scored symbols.
TAIL_DECILE_MIN_LEG: int = 2

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


def _resolve_metrics_horizon(
    returns: PostCostReturns, horizon: int | None
) -> int:
    """Settle the horizon :func:`compute_node_metrics` reduces over.

    ``None`` — the default — is :func:`_metrics_horizon`'s own policy
    unchanged: the shortest horizon :data:`HORIZONS` names that the priced
    panel covers.  An explicit ``horizon`` instead names the one the caller's
    evaluation was configured for (the config's horizon, a weekly horizon-5
    campaign, native-horizon OOS replay), and is refused rather than quietly
    resolved to the shortest covered when it cannot be honoured: a value
    outside :data:`HORIZONS` (the spec's own closed set) is not a horizon at
    all, and a value the spec does name but the priced panel carries no
    rebalance date for is *absent*, not a reason to fall back — the caller
    asked for a specific horizon's evidence, and silently substituting
    another horizon's would answer a different question than the one asked.
    Both refusals name the horizon asked for; the coverage refusal also names
    the horizons the panel actually covers, so a caller sees exactly what is
    available instead of guessing.
    """
    if horizon is None:
        return _metrics_horizon(returns)
    if isinstance(horizon, bool) or not isinstance(horizon, int):
        raise EvaluatorMetricsError(
            "compute_node_metrics' horizon must be an integer period count "
            f"or None, got {horizon!r}"
        )
    if horizon not in HORIZONS:
        raise EvaluatorMetricsError(
            f"horizon {horizon} is not one of the horizons the spec names "
            f"({', '.join(str(h) for h in HORIZONS)}); the metrics are "
            "computed over one pinned horizon, and that horizon is one the "
            "spec covers"
        )
    if not returns.series[horizon].dates():
        covered = [h for h in HORIZONS if returns.series[h].dates()]
        covered_text = ", ".join(str(h) for h in covered) if covered else "none"
        raise EvaluatorMetricsError(
            f"horizon {horizon} was asked for, but the priced panel covers "
            f"no rebalance date at it; the panel covers {covered_text} — pass "
            "one of those, or leave horizon out to measure the shortest one "
            "covered"
        )
    return horizon


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
    #: How many names each rebalance date's inverse-volatility book dropped for
    #: want of a volatility — the diagnostic that keeps the drop *recorded*
    #: rather than silent. A symbol whose window is flat (a perp delisted in
    #: place, its archived close constant) has a realised volatility of exactly
    #: 0, which is not a positive scale to divide a score by; rather than
    #: refusing the whole evaluation over one untradeable name, the date's book
    #: is restricted to the joined symbols that *do* carry a volatility and the
    #: rest are renormalised to gross 1 through the same
    #: :func:`book_weights` call (see :func:`compute_node_metrics`). Every date
    #: the horizon measured carries an entry — ``0`` where nothing was dropped
    #: — so a reader can tell a clean book from a thinned one. Empty with
    #: ``vols=None`` (nothing is ever dropped from a z-weighted book, which
    #: keeps such a name at a zero return as it always has) and empty on a
    #: record rebuilt from the metrics store, which persists neither this field
    #: nor :attr:`book_returns` nor :attr:`turnover_series`. Excluded from
    #: equality (``compare=False``) for the same reason those two are: a
    #: record rebuilt from the store is still the same measurement as the one
    #: that produced it. Carried as a plain ``dict`` rather than a
    #: ``MappingProxyType`` — unlike its siblings — because
    #: :mod:`orchestrator._process_pool`'s ``NodeMetrics`` reducer unwraps only
    #: the three proxy fields it names, and a fourth proxy would reach the
    #: pickler as an unpicklable ``mappingproxy``.
    vol_dropped: Mapping[dt.date, int] = field(default_factory=dict, compare=False)
    #: How many names each leg of each rebalance date's tail-decile book held —
    #: ``floor(n/10)`` for that date's joined cross-section of ``n`` scored
    #: symbols, where the long leg holds the top ``k`` and the short leg the
    #: bottom ``k``, each name at ``±0.5/k``.  Carried for the reason
    #: :attr:`vol_dropped` is: the weights alone say a tail-decile book was
    #: equal-weight within its legs but not how many names shared the gross, so
    #: a reader cannot tell a two-name leg from a fifty-name one without it,
    #: and that count is the figure a capacity or concentration read needs.
    #: Every measured date carries an entry under
    #: ``weighting="tail_decile"``; empty under every other weighting (the z
    #: and inverse-vol books hold every symbol, so there is no ``k`` to
    #: record) and on a record rebuilt from the metrics store, which persists
    #: neither this field nor :attr:`book_returns` nor
    #: :attr:`turnover_series`.  Excluded from equality (``compare=False``)
    #: for the same reason those three are: a record rebuilt from the store is
    #: still the same measurement as the one that produced it. Carried as a
    #: plain ``dict`` rather than a ``MappingProxyType`` — unlike its three
    #: proxy siblings — for the reason :attr:`vol_dropped` is:
    #: :mod:`orchestrator._process_pool`'s ``NodeMetrics`` reducer unwraps only
    #: the three proxy fields it names, and a fourth proxy would reach the
    #: pickler as an unpicklable ``mappingproxy``.
    tail_k: Mapping[dt.date, int] = field(default_factory=dict, compare=False)

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
        captured_dropped: dict[dt.date, int] = {}
        for day, value in self.vol_dropped.items():
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorMetricsError(
                    "a node metrics' vol_dropped must be keyed by calendar "
                    f"dates, got {day!r}"
                )
            if isinstance(value, bool) or not isinstance(value, int):
                raise EvaluatorMetricsError(
                    f"the vol_dropped count on {day.isoformat()} must be an "
                    f"integer, got {value!r}; the field counts names, and a "
                    "fractional one would name a book that traded part of a "
                    "symbol"
                )
            if value < 0:
                raise EvaluatorMetricsError(
                    f"the vol_dropped count on {day.isoformat()} is negative "
                    f"({value!r}); a drop count is a count of names removed "
                    "from the book"
                )
            captured_dropped[day] = value
        object.__setattr__(self, "vol_dropped", captured_dropped)
        captured_tail: dict[dt.date, int] = {}
        for day, value in self.tail_k.items():
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorMetricsError(
                    "a node metrics' tail_k must be keyed by calendar dates, "
                    f"got {day!r}"
                )
            if isinstance(value, bool) or not isinstance(value, int):
                raise EvaluatorMetricsError(
                    f"the tail_k count on {day.isoformat()} must be an "
                    f"integer, got {value!r}; the field counts the names one "
                    "leg of the date's tail-decile book held, and a fractional "
                    "one would name a book that traded part of a symbol"
                )
            if value < TAIL_DECILE_MIN_LEG:
                raise EvaluatorMetricsError(
                    f"the tail_k count on {day.isoformat()} is {value!r}, "
                    f"below the {TAIL_DECILE_MIN_LEG} names a leg of a "
                    "tail-decile book must hold; a leg of fewer names is not "
                    "a decile, and a record claiming one was never built by "
                    "this module's arithmetic"
                )
            captured_tail[day] = value
        object.__setattr__(self, "tail_k", captured_tail)

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


def _beta_neutral_weights(
    weights: Mapping[str, float], beta_row: Mapping[str, float]
) -> Mapping[str, float]:
    """Rescale one date's book so its long and short legs carry equal beta.

    ``weights`` is the date's plain dollar-neutral book (``w_i = z_i / Σ|z_j|``,
    gross 1); ``beta_row`` is whatever subset of its symbols a beta was
    supplied for that date (possibly empty). See the module docstring for the
    ``β_L``, ``β_S`` and ``gl`` derivation. Returns ``weights`` unchanged —
    the fallback — whenever either leg has no rated symbol, ``β_L + β_S`` is
    not strictly positive, or the unrated weight already parked in a leg
    would leave that leg's rated symbols a non-positive gross to carry;
    otherwise returns a new mapping with the rated symbols of each leg scaled
    and every other symbol (unrated, or already exactly 0) carried over as-is.
    """
    long_syms = [symbol for symbol, w in weights.items() if w > 0.0]
    short_syms = [symbol for symbol, w in weights.items() if w < 0.0]
    rated_long = [symbol for symbol in long_syms if symbol in beta_row]
    rated_short = [symbol for symbol in short_syms if symbol in beta_row]
    if not rated_long or not rated_short:
        return weights
    long_weight_sum = math.fsum(weights[symbol] for symbol in rated_long)
    short_weight_sum = math.fsum(weights[symbol] for symbol in rated_short)
    beta_l = (
        math.fsum(weights[symbol] * beta_row[symbol] for symbol in rated_long)
        / long_weight_sum
    )
    beta_s = (
        math.fsum(weights[symbol] * beta_row[symbol] for symbol in rated_short)
        / short_weight_sum
    )
    if beta_l + beta_s <= 0.0:
        return weights
    gl = beta_s / (beta_l + beta_s)
    long_unrated = math.fsum(
        weights[symbol] for symbol in long_syms if symbol not in beta_row
    )
    short_unrated = -math.fsum(
        weights[symbol] for symbol in short_syms if symbol not in beta_row
    )
    long_target = gl - long_unrated
    short_target = (1.0 - gl) - short_unrated
    if long_target <= 0.0 or short_target <= 0.0:
        return weights
    scale_long = long_target / long_weight_sum
    scale_short = short_target / (-short_weight_sum)
    rescaled = dict(weights)
    for symbol in rated_long:
        rescaled[symbol] = weights[symbol] * scale_long
    for symbol in rated_short:
        rescaled[symbol] = weights[symbol] * scale_short
    return rescaled


def _validate_weights_panel(
    panel: object, *, label: str, singular: str
) -> dict[dt.date, Mapping[str, float]]:
    """Validate a ``{date: {symbol: number}}`` panel — ``betas`` or ``vols``.

    :func:`compute_node_metrics` takes two per-date panels of per-symbol
    numbers, ``betas`` and ``vols``, with the same shape and the same
    refusals (the spec's own words: "validated like betas (same shape, same
    refusals)"), so the shape rules live here once rather than twice:
    a mapping keyed by calendar dates, each value a mapping of non-empty
    symbol names to finite numbers.  ``label`` and ``singular`` are the
    caller's own spellings of the panel and of one entry of it, so a refusal
    names the parameter the caller passed rather than a generic one.  The
    caller applies whatever value constraints go beyond finiteness — ``vols``
    also requires a positive scale; ``betas`` are signed and take any finite
    number.
    """
    if not isinstance(panel, Mapping):
        raise EvaluatorMetricsError(
            f"{label} must map rebalance date to {{symbol: {singular}}}, got "
            f"{type(panel).__name__}"
        )
    validated: dict[dt.date, Mapping[str, float]] = {}
    for day, row in panel.items():
        if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
            raise EvaluatorMetricsError(
                f"{label} must be keyed by calendar dates, got {day!r}"
            )
        if not isinstance(row, Mapping):
            raise EvaluatorMetricsError(
                f"{label} for {day.isoformat()} must map symbol to a "
                f"{singular}, got {type(row).__name__}"
            )
        inner: dict[str, float] = {}
        for symbol, value in row.items():
            if not isinstance(symbol, str) or not symbol:
                raise EvaluatorMetricsError(
                    f"{label} for {day.isoformat()} must be keyed by "
                    f"non-empty symbol names, got {symbol!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMetricsError(
                    f"the {singular} for {symbol!r} on {day.isoformat()} must "
                    f"be a number, got {value!r}"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EvaluatorMetricsError(
                    f"the {singular} for {symbol!r} on {day.isoformat()} is "
                    f"not finite ({value!r}); a NaN or ±inf would reach the "
                    "book's weights dressed as a measurement"
                )
            inner[symbol] = number
        validated[day] = MappingProxyType(inner)
    return validated


def _inverse_vol_scores(
    scores: Mapping[str, float], vols: Mapping[str, float]
) -> dict[str, float]:
    """Divide each score by its own symbol's volatility — ``z_i / vol_i``.

    ``scores`` is one date's already-validated cross-section; ``vols`` is
    whatever that date's ``{symbol: volatility}`` mapping the caller supplied.
    Every scored symbol must be named in ``vols`` with a finite, strictly
    positive number, and one that is not is refused **by name**: a volatility
    is a positive scale, so a missing or non-positive one would silently drop
    the name from the book or hand it a weight the signal never asked for, and
    either is a different book than the caller named. The returned mapping is
    the scaled scores, to be normalized by the caller exactly as the unscaled
    ones were — which keeps the book's gross exposure at 1 unconditionally,
    while its net weight is zero exactly when the *scaled* cross-section stays
    centered (see the module docstring: a per-symbol positive scale does not
    preserve the sum of a centered row).
    """
    if not isinstance(vols, Mapping):
        raise EvaluatorMetricsError(
            "book_weights' vols must map symbol to a volatility, got "
            f"{type(vols).__name__}"
        )
    validated_vols: dict[str, float] = {}
    for symbol, value in vols.items():
        if not isinstance(symbol, str) or not symbol:
            raise EvaluatorMetricsError(
                "book_weights' vols must be keyed by non-empty symbol names, "
                f"got {symbol!r}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluatorMetricsError(
                f"the volatility for {symbol!r} must be a number, got {value!r}"
            )
        number = float(value)
        if not math.isfinite(number):
            raise EvaluatorMetricsError(
                f"the volatility for {symbol!r} is not finite ({value!r}); a "
                "NaN or ±inf would reach the book's weights dressed as a "
                "measurement"
            )
        if number <= 0.0:
            raise EvaluatorMetricsError(
                f"the volatility for {symbol!r} is not positive ({value!r}); a "
                "volatility is a positive scale, and a score divided by it "
                "would flip or drop the name rather than weight it"
            )
        validated_vols[symbol] = number
    scaled: dict[str, float] = {}
    for symbol, value in scores.items():
        symbol_vol = validated_vols.get(symbol)
        if symbol_vol is None:
            raise EvaluatorMetricsError(
                f"the scored symbol {symbol!r} is missing from book_weights' "
                "vols; the inverse-volatility book needs a volatility for "
                "every name it weights, and defaulting one would trade a book "
                "other than the one named — supply it or leave vols out"
            )
        quotient = value / symbol_vol
        if not math.isfinite(quotient):
            # Both inputs are finite, but a score near the double maximum over
            # a near-denormal volatility overflows the quotient — and a NaN
            # would then propagate through the gross normalization into every
            # weight.  Refused here for the same reason the raw score and the
            # vol are: a non-finite number must not reach the book dressed as
            # a measurement.
            raise EvaluatorMetricsError(
                f"the score for {symbol!r} divided by its volatility "
                f"({value!r} / {symbol_vol!r}) is not finite ({quotient!r}); "
                "the vol scaling overflowed, and a NaN or ±inf would reach "
                "the book's weights dressed as a measurement"
            )
        scaled[symbol] = quotient
    return scaled


def _tail_decile_weights(
    scores: Mapping[str, float], *, day: dt.date | None = None
) -> dict[str, float]:
    """The tail-decile book for one date — long the top decile, short the bottom.

    ``scores`` is one date's already-validated cross-section.  The symbols are
    sorted by score ascending, ties broken by symbol name (the one
    deterministic tie-break this workspace uses wherever a ranking has to be
    total — an unstable sort would make the book a function of dict insertion
    order, and two equal scores are not evidence for one name over another).
    The bottom decile is then the first ``floor(n/10)`` names and the top
    decile the last ``floor(n/10)``; the long leg's names each carry
    ``+0.5 / k`` and the short leg's each ``-0.5 / k``, every other name
    ``0.0``.  The book is therefore equal-weight within each leg, gross 1
    (``k · 0.5/k + k · 0.5/k``) and net 0 (the two legs' identical gross sums
    cancel) by construction, whatever the scores' own scale or centering — the
    whole point of the weighting, since a ranking whose return gradient lives
    in its tails is traded where the gradient is rather than spread
    proportionally over deciles that carry none.

    A cross-section too small for two non-empty deciles is refused: ``k``
    below :data:`TAIL_DECILE_MIN_LEG` names a leg of one name (or none), and a
    "decile" holding a single symbol is a directional bet dressed as a
    cross-sectional one.  ``day``, when the caller has one, is named in the
    refusal beside the count, so a per-date caller's message says *which*
    rebalance date's cross-section was too thin; :func:`book_weights` has no
    date to name and omits it.
    """
    ordered = sorted(scores, key=lambda symbol: (scores[symbol], symbol))
    count = len(ordered)
    leg = count // 10
    where = f" on {day.isoformat()}" if day is not None else ""
    if leg < TAIL_DECILE_MIN_LEG:
        raise EvaluatorMetricsError(
            f"the cross-section{where} carries {count} scored symbols, so its "
            f"top and bottom deciles would hold floor({count}/10) = {leg} "
            f"name(s) each; a tail-decile book needs at least "
            f"{TAIL_DECILE_MIN_LEG} names per leg (a leg of one name is a "
            "directional bet, not a cross-sectional one), which needs at least "
            f"{10 * TAIL_DECILE_MIN_LEG} scored symbols — refusing rather than "
            "trading a decile that is not one"
        )
    weight = 0.5 / leg
    weights = dict.fromkeys(ordered, 0.0)
    for symbol in ordered[:leg]:
        weights[symbol] = -weight
    for symbol in ordered[count - leg:]:
        weights[symbol] = weight
    return weights


def _resolve_weighting(weighting: object, vols: object) -> str:
    """Settle which book the caller asked for — and refuse a contradiction.

    ``weighting`` is the caller's spelling, one of :data:`WEIGHTINGS`; ``vols``
    is the panel it handed beside it (or ``None``).  Two of the three
    weightings are named by the panel rather than only by the string, so the
    two must agree:

    * :data:`Z_WEIGHTING` with a ``vols`` panel is the inverse-volatility book
      — that is what ``vols`` has meant to every caller since the parameter
      existed, and it stays that way, so an old caller's call is unchanged.
    * :data:`INVERSE_VOL_WEIGHTING` with ``vols=None`` is a contradiction: the
      caller named a book whose whole construction is the division by a
      volatility and supplied no volatility, so it is refused **by name**
      rather than quietly built as the z book the caller did not ask for.
    * :data:`TAIL_DECILE_WEIGHTING` is a function of the scores alone; a
      ``vols`` panel handed with it is ignored, exactly as the spec's own
      sentence says, because the two weightings disagree about what a
      volatility would even mean here.
    """
    if not isinstance(weighting, str) or weighting not in WEIGHTINGS:
        raise EvaluatorMetricsError(
            "book_weights' weighting must be one of "
            f"{', '.join(repr(name) for name in WEIGHTINGS)}, got "
            f"{weighting!r}; the weighting is the whole book's construction, "
            "and a value outside that closed set is refused rather than "
            "guessed — building one the caller never named would trade a "
            "different portfolio than the one asked for"
        )
    if weighting == INVERSE_VOL_WEIGHTING and vols is None:
        raise EvaluatorMetricsError(
            f"book_weights was asked for the {INVERSE_VOL_WEIGHTING!r} book "
            "but carries no vols; the weighting divides every score by its "
            "own symbol's volatility, so a vols of None leaves nothing to "
            "divide by — supply the panel or ask for "
            f"{Z_WEIGHTING!r}, which weights each name by its own score"
        )
    if weighting == Z_WEIGHTING and vols is not None:
        return INVERSE_VOL_WEIGHTING
    return weighting


def book_weights(
    scores: Mapping[str, float],
    betas: Mapping[str, float] | None = None,
    *,
    vols: Mapping[str, float] | None = None,
    weighting: str = Z_WEIGHTING,
) -> dict[str, float]:
    """The research book's weights for one date — the public spelling of step 8's book.

    ``scores`` is one rebalance date's cross-section (``{symbol: normalized
    score}``); the return is the dollar-neutral, gross-1 book
    :func:`compute_node_metrics` trades that date, ``w_i = z_i / Σ|z_j|``.
    ``betas`` (keyword-only, default ``None``), when given, is that date's
    ``{symbol: beta}`` and rescales the plain weights by the same beta-neutral
    leg rule :func:`compute_node_metrics` applies — see
    :func:`_beta_neutral_weights` for the ``β_L``, ``β_S`` and ``gl``
    derivation and the fallback to the plain weights on a degenerate split.
    ``vols`` (keyword-only, default ``None``), when given, is that date's
    ``{symbol: volatility}``; each score is divided by its own symbol's
    volatility before the book is normalized, so the weights are proportional
    to ``z_i / vol_i`` — the inverse-volatility book the module docstring
    describes, gross 1 and dollar-neutral whenever the scaled row stays
    centered.  When both are given the beta-neutral
    rescale is applied *after* the vol scaling, to the vol-scaled weights.
    ``weighting`` (keyword-only, default :data:`Z_WEIGHTING`), one of
    :data:`WEIGHTINGS`, names which of the three books to build; the default
    and ``vols=None`` together are exactly this function's behaviour before
    the parameter existed.  ``vols`` and ``weighting`` must agree — see
    :func:`_resolve_weighting`: ``vols=<a panel>`` *is* the
    ``"inverse_vol"`` weighting, and ``weighting="inverse_vol"`` with no panel
    is refused by name.  Under ``weighting="tail_decile"`` the book is the
    tail-decile one (:func:`_tail_decile_weights`): long the top decile of
    scores, short the bottom, equal-weight within each leg, ``vols`` ignored;
    the beta-neutral rescale is still applied after the legs are formed.  This
    is the one place those rules are spelled out;
    :func:`compute_node_metrics` calls this function for its own per-date
    weights, so the two cannot drift, and a forward shadow that calls this
    function with the same scores, betas and vols an evaluation scored trades
    exactly the book the evaluation did.

    Raises :class:`~evaluator.EvaluatorMetricsError` when ``scores`` is empty,
    carries a non-finite value, or sums to zero gross exposure (``Σ|s| = 0``,
    the weights would be a division by zero); when ``betas`` is supplied but is
    malformed or carries a non-finite value; when ``vols`` is supplied but
    is malformed, carries a non-finite value, or is missing a scored symbol or
    gives it a non-positive volatility — each refused by name, never silently
    defaulted, because a vol is a positive scale rather than a direction; when
    ``weighting`` is outside :data:`WEIGHTINGS`, or names
    ``"inverse_vol"`` with no ``vols``; and, under ``"tail_decile"``, when the
    cross-section is too small for two non-empty deciles (fewer than
    ``10 × TAIL_DECILE_MIN_LEG`` scored symbols), the refusal naming the count.
    """
    if not isinstance(scores, Mapping):
        raise EvaluatorMetricsError(
            f"book_weights' scores must map symbol to a score, got "
            f"{type(scores).__name__}"
        )
    validated_scores: dict[str, float] = {}
    for symbol, value in scores.items():
        if not isinstance(symbol, str) or not symbol:
            raise EvaluatorMetricsError(
                "book_weights' scores must be keyed by non-empty symbol "
                f"names, got {symbol!r}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluatorMetricsError(
                f"the score for {symbol!r} must be a number, got {value!r}"
            )
        number = float(value)
        if not math.isfinite(number):
            raise EvaluatorMetricsError(
                f"the score for {symbol!r} is not finite ({value!r}); a NaN "
                "or ±inf would reach the book's weights dressed as a "
                "measurement"
            )
        validated_scores[symbol] = number
    if not validated_scores:
        raise EvaluatorMetricsError(
            "book_weights needs at least one scored symbol; an empty date "
            "has no dollar-neutral book to weight"
        )
    # The weighting is settled *before* the book is built, so a contradiction
    # between the spelling and the panel is refused rather than half-honoured:
    # `z` with vols is the inverse-vol book (every caller since the parameter
    # existed means that), and a name that disagrees with the panel is
    # refused by name.
    book = _resolve_weighting(weighting, vols)
    if book == TAIL_DECILE_WEIGHTING:
        # A function of the scores alone: a decile is a count of names, not a
        # share of gross, so a volatility has nothing to divide here.
        weights = _tail_decile_weights(validated_scores)
    else:
        if vols is not None:
            validated_scores = _inverse_vol_scores(validated_scores, vols)
        gross = math.fsum(abs(value) for value in validated_scores.values())
        if gross == 0.0:
            raise EvaluatorMetricsError(
                "book_weights' scores sum to zero gross exposure (every score "
                "is exactly 0), so the dollar-neutral weights z_s / Σ|z| are "
                "undefined; refusing rather than dividing by zero"
            )
        weights = {
            symbol: value / gross for symbol, value in validated_scores.items()
        }
    if betas is None:
        return weights
    if not isinstance(betas, Mapping):
        raise EvaluatorMetricsError(
            f"book_weights' betas must map symbol to a beta, got "
            f"{type(betas).__name__}"
        )
    validated_betas: dict[str, float] = {}
    for symbol, value in betas.items():
        if not isinstance(symbol, str) or not symbol:
            raise EvaluatorMetricsError(
                "book_weights' betas must be keyed by non-empty symbol "
                f"names, got {symbol!r}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluatorMetricsError(
                f"the beta for {symbol!r} must be a number, got {value!r}"
            )
        number = float(value)
        if not math.isfinite(number):
            raise EvaluatorMetricsError(
                f"the beta for {symbol!r} is not finite ({value!r}); a NaN "
                "or ±inf would reach the book's weights dressed as a "
                "measurement"
            )
        validated_betas[symbol] = number
    return _beta_neutral_weights(weights, validated_betas)


def compute_node_metrics(
    returns: PostCostReturns,
    scores: Mapping[dt.date | str, Mapping[str, float]],
    *,
    cost_per_unit_traded: float = 0.0,
    betas: Mapping[dt.date, Mapping[str, float]] | None = None,
    vols: Mapping[dt.date, Mapping[str, float]] | None = None,
    weighting: str = Z_WEIGHTING,
    horizon: int | None = None,
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

    ``cost_per_unit_traded`` (keyword-only, default ``0.0``) is a fraction of
    traded notional charged against the book's own return on each date — see
    the module docstring for the formula and why the per-symbol fee step 7
    already charged cancels in this dollar-neutral book. The default charges
    nothing, so :attr:`NodeMetrics.book_returns` and
    :attr:`NodeMetrics.ir_standalone` are unchanged from before the parameter
    existed.

    ``betas`` (keyword-only, default ``None``) is ``{date: {symbol: beta}}``;
    when given, each date's book is rescaled so its long and short legs carry
    equal benchmark beta — see the module docstring and
    :func:`_beta_neutral_weights` for the ``β_L``, ``β_S`` and ``gl``
    derivation and the fallback to the plain weights on a degenerate split.
    The rescaled weights are what feed the book return, the turnover and the
    turnover cost charge; ``ic_mean`` and ``ic_tstat`` are unaffected, since
    the coefficient is rank-based on the scores. The default, ``None``, never
    attempts a rescale and reproduces every figure this module computed
    before the parameter existed.

    ``vols`` (keyword-only, default ``None``) is ``{date: {symbol: vol}}``,
    validated exactly like ``betas`` (the same shape, the same refusals) and
    with one constraint of its own: a volatility is a positive scale, so a vol
    that is non-finite or non-positive is refused by name rather than silently
    defaulted — the panel's own values are still checked, because a caller who
    hands this function a vol of ``0.0`` has made an arithmetic error this
    function should name rather than quietly reinterpret.  A symbol the day's
    row simply *does not name* is a different case: the row is the answer to
    "whose volatility could be measured over the trailing window", and a name
    that is absent from it was left out by whoever computed it (too few
    returns, or a flat window — a perp delisted in place measures exactly
    ``0.0``).  Such a name is **dropped from that date's book** rather than
    refusing the whole evaluation: it is untradeable at a volatility nobody
    measured, so it belongs outside that date's cross-section by the same
    missing-input rule that neutralises a symbol with no stream.  The
    surviving symbols are handed to :func:`book_weights` with the day's vols,
    so the thinned book is renormalised to gross 1 and net 0 exactly as the
    full one was, and the number of names dropped is recorded per date in
    :attr:`NodeMetrics.vol_dropped` (every measured date carries an entry,
    ``0`` where nothing was dropped).  The rank coefficient for the date is
    still measured over the **full** joined cross-section — a frozen name has
    a score and a return of 0, and the book's membership is not what the
    ranking is measured on — so ``ic_mean`` and ``ic_tstat`` are unchanged by
    the drop.  When given, each date's cross-section is handed to
    :func:`book_weights` with its own day's vols, so the day's book is
    proportional to ``z_i / vol_i`` — gross 1 and dollar-neutral whenever the
    scaled row stays centered — and, when ``betas`` is also given, the
    beta-neutral rescale composes after the vol scaling. The rescaled weights
    feed the book return, the turnover and the turnover cost charge exactly as
    the unscaled ones did. The default, ``None``, scales nothing, drops
    nothing, and every number this function returns is identical to the one it
    returned before the parameter existed.

    ``weighting`` (keyword-only, default :data:`Z_WEIGHTING`) names which of
    :data:`WEIGHTINGS`' three books each date's weights are built under, and is
    passed straight to :func:`book_weights` per date; with ``"z"`` it composes
    with ``vols`` exactly as the previous paragraph describes (``vols`` given
    *is* the inverse-volatility weighting).  Under ``"tail_decile"`` each
    date's book is the tail-decile one — long the top decile of that date's
    scores, short the bottom, equal-weight within each leg, gross 1 and net 0 —
    and **the rank coefficient is unchanged**: ``ic_mean`` and ``ic_tstat`` are
    still measured over the full joined cross-section, since the book's
    membership is not what the ranking is measured on.  What changes is the
    weights, and so :attr:`NodeMetrics.book_returns`,
    :attr:`NodeMetrics.ir_standalone`, the turnover and the turnover cost
    charge — which is the whole point: a ranking whose return gradient lives in
    its tails is traded where the gradient is.  Each measured date's leg count
    ``k`` is recorded in :attr:`NodeMetrics.tail_k`.  ``vols`` is ignored under
    ``"tail_decile"`` (a decile is a count of names, not a share of gross, so a
    volatility has nothing to divide here); a date whose joined cross-section
    is too small for two non-empty deciles (fewer than
    ``10 × TAIL_DECILE_MIN_LEG`` scored symbols) is refused **by name, naming
    that date and its count** rather than trading a decile of one name.

    ``horizon`` (keyword-only, default ``None``) names the horizon the four
    scalars are measured over, overriding :data:`METRICS_HORIZON`'s "shortest
    the panel covers" policy with the one the caller's evaluation was
    configured for. The default, ``None``, is that policy unchanged — every
    figure this function returns is identical to the one it returned before
    this parameter existed. An explicit ``horizon`` must be one of
    :data:`HORIZONS` and one the priced panel carries at least one rebalance
    date for; either failure is refused by
    :class:`~evaluator.EvaluatorMetricsError` naming the horizon asked for
    (and, when the panel simply does not cover it, the horizons the panel
    does cover) rather than silently falling back to the shortest covered.

    Raises :class:`~evaluator.EvaluatorMetricsError`, each with its reason (see
    ``_errors``): a ``returns`` that is not step 7's own result; a ``scores``
    mapping that is malformed, empty, or carries a non-finite value; a
    ``cost_per_unit_traded`` that is negative or not finite; a ``betas``
    mapping that is malformed or carries a non-finite value; a ``vols``
    mapping that is malformed, carries a non-finite value, or gives any
    symbol a non-positive volatility; a ``horizon`` that is not one of
    :data:`HORIZONS`, or one the priced panel carries no rebalance date for;
    a panel that
    covers no horizon at all (nothing measured); a horizon with fewer than
    two dates (a t-statistic over one date names a zero standard error and a
    fabricated infinity); and — via the record — a hand-built metrics whose
    scalars do not reduce from their own terms.
    """
    if isinstance(cost_per_unit_traded, bool) or not isinstance(
        cost_per_unit_traded, (int, float)
    ):
        raise EvaluatorMetricsError(
            "cost_per_unit_traded must be a number (a fraction of traded "
            f"notional, e.g. 0.001 for 10 bps), got {cost_per_unit_traded!r}"
        )
    cost_per_unit_traded = float(cost_per_unit_traded)
    if not math.isfinite(cost_per_unit_traded):
        raise EvaluatorMetricsError(
            "cost_per_unit_traded must be finite, got "
            f"{cost_per_unit_traded!r}; a NaN or ±inf would reach every book "
            "return dressed as a measurement"
        )
    if cost_per_unit_traded < 0.0:
        raise EvaluatorMetricsError(
            "cost_per_unit_traded must be non-negative, got "
            f"{cost_per_unit_traded!r}; it charges the book for trading, and "
            "a negative charge would pay the book for trading instead"
        )
    if not isinstance(returns, PostCostReturns):
        raise EvaluatorMetricsError(
            "compute_node_metrics reduces step 7's own result — a "
            "PostCostReturns, the priced series the cost schedule produced — "
            f"got {type(returns).__name__}; the four scalars are measured from "
            "the post-cost returns, and the gross series alone cannot say which "
            "schedule priced them"
        )
    # The weighting is settled once, up front, against the panel the caller
    # handed: `z` with vols is the inverse-vol book (unchanged for every
    # caller that predates the parameter), and a name that disagrees with the
    # panel is refused before a single date is measured.
    book = _resolve_weighting(weighting, vols)
    if book == TAIL_DECILE_WEIGHTING:
        # A decile is a count of names, not a share of gross, so a volatility
        # has nothing to divide here; the spec's own sentence says a vols
        # handed under this weighting is ignored, and dropping it here (rather
        # than at each use below) is what keeps that from becoming a special
        # case in the per-date loop — no vol is validated, none is dropped,
        # and NodeMetrics.vol_dropped stays empty exactly as it does when vols
        # is absent.
        vols = None
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

    validated_betas: dict[dt.date, Mapping[str, float]] = {}
    if betas is not None:
        validated_betas = _validate_weights_panel(betas, label="betas", singular="beta")

    validated_vols: dict[dt.date, Mapping[str, float]] = {}
    if vols is not None:
        validated_vols = _validate_weights_panel(vols, label="vols", singular="vol")
        # A volatility is a positive scale, not a direction: a non-positive
        # one would flip or drop the name it weights, so the day's row is
        # checked here rather than left for the division to produce a
        # reflected or infinite weight.
        for day, vol_row in validated_vols.items():
            for symbol, vol in vol_row.items():
                if vol <= 0.0:
                    raise EvaluatorMetricsError(
                        f"the vol for {symbol!r} on {day.isoformat()} is not "
                        f"positive ({vol!r}); a volatility is a positive "
                        "scale, and a score divided by it would flip or drop "
                        "the name rather than weight it"
                    )

    horizon = _resolve_metrics_horizon(returns, horizon)
    series = returns.series[horizon]
    per_date_ic: dict[dt.date, float] = {}
    per_date_return: dict[dt.date, float] = {}
    per_date_weights: dict[dt.date, Mapping[str, float]] = {}
    vol_dropped: dict[dt.date, int] = {}
    tail_k: dict[dt.date, int] = {}
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
        # against) — :func:`book_weights`, the one spelling of the
        # ``w_i = z_i / Σ|z_j|`` book and its beta-neutral rescale, so this
        # function's own book cannot drift from the one that function hands a
        # forward shadow.
        book_symbols = sorted(set(score_row) & set(returns_row))
        row_betas = validated_betas.get(day) if betas is not None else None
        row_vols: Mapping[str, float] | None = None
        if vols is None:
            weighted_symbols = book_symbols
        else:
            row_vols = validated_vols.get(day)
            if row_vols is None:
                # Scaling some dates and not others would be a book half
                # inverse-vol and half z-weighted — an inconsistency the
                # caller never asked for, and one that would read as a
                # measurement.  A date the scores carry must be scaled or
                # refused by name.
                raise EvaluatorMetricsError(
                    f"vols carries no row for {day.isoformat()}, a rebalance "
                    "date the normalized scores and the priced panel share; "
                    "the inverse-volatility book needs a volatility for every "
                    "name it weights, on every date it weights them — supply "
                    "the date's vols or leave vols out"
                )
            # A symbol this date's row carries no volatility for is *dropped
            # from this date's book*, not refused: the row already names whose
            # volatility could be measured over the trailing window (a symbol
            # with too few returns was left out by whoever computed it, and a
            # flat window — a perp delisted in place — measures exactly 0.0,
            # which is no positive scale to divide a score by).  Such a name is
            # untradeable at that volatility, so it belongs outside the date's
            # cross-section by the same missing-input rule that neutralises a
            # symbol with no stream; refusing the whole evaluation over one
            # frozen perp would discard every other name's measurement with it.
            # The rank coefficient above was still measured over the *full*
            # joined cross-section — the book's membership is not what the
            # ranking is measured on, and a frozen name carries a return of 0
            # and a score, so dropping it from the book does not change the
            # cross-section the IC is taken over.  The drops are counted per
            # date and the surviving weights go through the same
            # :func:`book_weights` call, so the thinned book is renormalised to
            # gross 1 exactly as the full one was.
            weighted_symbols = [
                symbol for symbol in book_symbols if symbol in row_vols
            ]
            # Every measured date carries an entry, ``0`` where nothing was
            # dropped, so a reader can tell a clean book from a thinned one
            # without inferring it from the row's own membership.
            vol_dropped[day] = len(book_symbols) - len(weighted_symbols)
        row_scores = {symbol: score_row[symbol] for symbol in weighted_symbols}
        try:
            weights = book_weights(
                row_scores, row_betas, vols=row_vols, weighting=book
            )
        except EvaluatorMetricsError as exc:
            if book == TAIL_DECILE_WEIGHTING:
                # The tail-decile book refuses a cross-section too small for
                # two non-empty deciles; the refusal above names the count,
                # and this is the per-date caller, so it is restated with the
                # date the count belongs to — "which rebalance date was too
                # thin" is the one thing a reader cannot recover from the
                # count alone.
                raise EvaluatorMetricsError(
                    f"horizon {horizon} on {day.isoformat()}: {exc}"
                ) from exc
            # _rank_correlation above already required the joined symbols'
            # scores to have nonzero rank spread, so they cannot all be
            # exactly zero; unreachable in practice, refused rather than
            # producing a NaN book if that invariant is ever broken.
            raise EvaluatorMetricsError(
                f"horizon {horizon} on {day.isoformat()} has an all-zero "
                "normalized score across its joined cross-section, so the "
                "dollar-neutral book's weights are undefined; refusing "
                "rather than dividing by zero"
            ) from exc
        per_date_weights[day] = weights
        if book == TAIL_DECILE_WEIGHTING:
            # The count of names each leg actually held on this date — the
            # figure that makes the recorded book checkable, since the weights
            # alone say the legs were equal-weight but not how many names
            # carried that weight.  ``floor(len/10)`` is the same expression
            # :func:`_tail_decile_weights` used to build the weights above, so
            # the two cannot disagree.
            tail_k[day] = len(weighted_symbols) // 10
        per_date_return[day] = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in weighted_symbols
        )
    if not per_date_ic:
        raise EvaluatorMetricsError(
            "the priced panel and the normalized scores share no rebalance "
            "date at the metrics horizon, so no information coefficient was "
            "measured and there are no node metrics to store — score and price "
            "an alignment with coverage first (features 75 through 79)"
        )

    # Turnover cost is charged against the book return itself, here, rather
    # than per symbol where step 7 charges it: a uniform per-symbol fee
    # charged against a dollar-neutral book cancels (Σ w_i f = f Σ w_i = 0),
    # so the only place a trading cost can actually bite is the traded
    # notional of the book's own weights (see the module docstring). On the
    # first book date there is no predecessor, so the whole book is entry
    # cost; on every later date, traded_d is the weight that moved between
    # this book and the previous one, absent symbols holding weight 0.
    if cost_per_unit_traded != 0.0:
        prev_weights: Mapping[str, float] | None = None
        for day in sorted(per_date_weights):
            weights = per_date_weights[day]
            if prev_weights is None:
                traded = math.fsum(abs(value) for value in weights.values())
            else:
                symbols = set(prev_weights) | set(weights)
                traded = math.fsum(
                    abs(weights.get(symbol, 0.0) - prev_weights.get(symbol, 0.0))
                    for symbol in symbols
                )
            per_date_return[day] -= cost_per_unit_traded * traded
            prev_weights = weights

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
        vol_dropped=vol_dropped,
        tail_k=tail_k,
    )
