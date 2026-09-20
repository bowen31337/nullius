"""Sizing the book and splitting its edge — pipeline step 8, features 82.

app_spec.xml feature 82: *"System computes a capacity estimate plus regime
attribution, persisting both into the node artifact directory."*
docs/nullius-tech-architecture.md §6.1 names both halves inside step 8 —
``8. compute_metrics    IC series, IR, turnover, decay, capacity, regime
attribution`` — and §9.2 names where they land:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      regime_attribution.json

docs/alpha-engine-prd.md's node artifact block spells the two values the
step produces — ``capacity_estimate: float`` and ``regime_attribution:
dict`` — and its §"Capacity" row states what the first is *for*: *"Anything
that works on $50k but not $50M is invisible to professionals and therefore
uncrowded.  Small-cap cross-section is the canonical case."*  The
computation lives here; :mod:`evaluator._capacity_store` writes it down, on
the split this package already uses twice (``_identity`` computes and
``_store`` persists for feature 70; ``_costs`` and ``_cost_store`` for 79).

Three decisions carry the capacity half, and each is a pin rather than a
knob:

*capacity is a dollar book, sized against the measured edge.*
    The estimate answers the PRD's question directly: *how many dollars can
    this signal run before its own trading eats the edge it measured?*  The
    edge is step 7's own record — the per-symbol post-cost returns, fee
    schedule already paid — and the drag is the only thing that grows with
    size: market impact.  A book of ``B`` dollars, equal-weighted over date
    ``d``'s cross-section of ``n`` symbols, puts ``B/n`` dollars to work per
    name; its participation is ``(B/n) / dollar_volume``, and the pinned
    impact law is the square-root law — a trade of participation ``q`` costs
    :data:`IMPACT_COEFFICIENT` × ``√q`` of its notional.  The estimate is
    the largest ``B`` whose mean drag still leaves
    :data:`EDGE_SURVIVAL_FRACTION` of the mean post-cost edge — the classic
    "AUM at which half the edge survives" definition — and because drag
    grows as ``√B`` the crossing has one closed form (see
    :func:`_solve_capacity`), so the number is exact, deterministic and
    reproducible rather than the output of a search.
*the impact law is pinned here, and that is not a second fee schedule.*
    §6.2 and feature 69 forbid a second implementation of the *fee schedule
    and fill model* — the per-trade pricing the live engine also performs —
    and step 7 already routes every trade through that shared library.  A
    capacity estimate is a different kind of object: a research metric the
    live engine never computes, so there is no research/live divergence for
    ``β₄`` to penalize, and every such metric in this package pins its own
    estimator rather than asking the deployment to inject one — feature 74
    pins rank-then-z-score for normalization, feature 80 will pin the IC
    arithmetic, and this module pins the square-root law the way those pin
    theirs.  What arrives from outside is not the law but the *fact* it
    consumes: dollar volumes, read host-side from the sealed snapshot and
    passed as a value, exactly as step 4's closes arrive (the seam feature
    73's ``materialize`` opens — the lake read is injected, never reached
    for).
*the unit book is equal-weighted, and the reported estimate is the minimum
across the five horizons.*
    Equal weight is the workspace's one existing weighting convention —
    feature 55's market return series is the equal-weighted mean across the
    cross-section — and it is the only convention available to a step that
    holds returns rather than weights: feature 82's declared dependency is
    feature 79's record, which carries per-symbol post-cost returns, and
    deriving weights from scores would reach for feature 74's output two
    steps back.  The minimum across horizons is the binding constraint, and
    it is deliberately the conservative direction: the PRD's warning is a
    *capacity illusion* — gains concentrated in the lowest-liquidity names,
    "a capacity illusion in a large-cap family, the expected footprint in a
    small-cap one" — so an overstatement is the error that costs money and
    an understatement is merely a missed size.  A signal whose long-horizon
    edge has decayed negative can still be promoted on its short-horizon
    numbers, but the capacity estimate is not the place to hide the horizon
    it fails at.  Ties resolve to the lowest horizon index, on the same
    deterministic-tie-break principle the labeler's k-means states.

The attribution half carries two pins of its own:

*the strata are names, and the evaluator does not label.*
    Regime labels are produced by feature 58's causal rolling-window
    labeler — the only labeler the system has, whose trailing-window
    discipline is that member's contract to enforce — and named to match
    the strata the regime plugin counts coverage across ("high-volatility
    trend", "low-volatility chop", "crash"; features 283 and 290, and the
    ``regime_coverage`` table migration 0107 names).  They arrive here as a
    value, ``{date: stratum}``, and this module fits nothing: re-deriving
    labels inside the evaluator would be a second labeler in exactly the
    way a second fee schedule is one, and it would restate the causality
    guarantee (labels fit on trailing data only) somewhere it can no longer
    be enforced.  A label for a date outside the rebalance grid is ignored
    — the same rule the alignment applies to closes of unscored symbols, so
    a whole-market labelling and a grid labelling attribute identically —
    while a grid date carrying no label is *counted* in
    :attr:`RegimeAttribution.unattributed_dates`, never silently dropped.
*one convention for both halves.*
    The attributed quantity is the same equal-weight cross-sectional mean
    post-cost return the capacity half measures — one reduction, stated
    once, shared — split per stratum per horizon, each slice carrying its
    own date count because the five horizons cover different supports and a
    mean without its denominator cannot be read.  §10.3 aggregates *across
    worlds* with regime-stratified CVaR; this artifact is the within-node
    half of that sentence — the split that makes any later stratified
    aggregation possible at all.

**Absence is not zero**, four times over.  A horizon whose series is empty
carries *no* capacity — ``None``, not ``0.0``, because a horizon the window
was too short to measure is not a horizon that supports no book — and a
bundle whose every horizon is empty is refused outright (no edge to size).
A stratum named on the grid but measured at no horizon is carried with
empty slices rather than dropped, so "measured a mean of zero" and "never
measured" stay distinguishable — the same distinction §C7's coverage ledger
draws by writing the zero.  A missing dollar volume for a ``(symbol,
date)`` the returns scored is refused rather than priced as free
liquidity: a name nobody can trade would otherwise read as infinitely
tradable, which is the capacity illusion again, produced by a hole in the
fetch instead of a thin market.  And a volume that is not a positive
finite number is refused for the reason every non-finite value in this
package is: it would reach the artifact dressed as a measurement.

**The closed-form arithmetic, stated once.**  For a horizon ``h`` with
supported dates ``D``, per-date cross-section ``S_d`` of size ``n_d``:

.. code-block:: text

    r_d  = (1/n_d) · Σ_i net_{i,d}                  the unit book at d
    E_h  = mean_d r_d                               the post-cost edge
    a_d  = (1/n_d) · Σ_i 1/√(n_d · DV_{i,d})        the per-√$ drag terms
    ā_h  = mean_d a_d
    drag(B) = κ · √B · ā_h                          square-root impact law
    B*   = ((1−θ) · E_h / (κ · ā_h))²               drag = (1−θ) · E_h

with ``κ`` = :data:`IMPACT_COEFFICIENT` and ``θ`` =
:data:`EDGE_SURVIVAL_FRACTION`.  An edge of zero or less yields a capacity
of exactly ``0.0`` — a signal that measured no edge has no book to size,
which is a finding, not a failure.  The reported
:attr:`CapacityEstimate.capacity_usd` is ``min_h B*_h`` over the horizons
with support, and :attr:`CapacityEstimate.binding_horizon` names the
horizon that achieved it.

**What this module does not do.**  It prices no trade (§6.2's shared
library, consumed at step 7), labels no regime (feature 58's labeler),
persists nothing (:mod:`evaluator._capacity_store` owns the write, and the
node artifact directory's ``regime_attribution.json`` is written by the
artifacts member — feature 172 — reading this store back, the same
division feature 79's cost store states for ``signal_returns.parquet``),
and computes no other metric: IC, IR and turnover are feature 80, the
decay profile feature 81, ``ir_marginal`` feature 83.  It takes step 7's
record, the sealed dollar volumes and the causal labels, and answers the
two questions step 8 puts in its scope: *how big a book does this edge
support, and where does that edge live?*

**The layering note.**  This module is stdlib-only — dates, mappings and
square roots; no polars, no pyarrow, no lake, no environment, no HTTP, and
no import of any other member.  The labeler whose output it consumes is
never imported (the labels arrive as a value, like the closes and the
volumes), so importing this member costs composition — and the replay path
§1 forbids from reaching the evaluator — nothing at all.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional, Tuple

from ._align import HORIZONS
from ._costs import CostModelRef, PostCostReturns
from ._errors import EvaluatorCapacityError

__all__ = [
    "CAPACITY_STEP",
    "EDGE_SURVIVAL_FRACTION",
    "IMPACT_COEFFICIENT",
    "CapacityEstimate",
    "HorizonCapacity",
    "RegimeAttribution",
    "StratumAttribution",
    "StratumSlice",
    "attribute_regimes",
    "estimate_capacity",
]

#: The pipeline-step name, in §6.1's own spelling.  Step 8 is the metrics
#: step — ``compute_metrics    IC series, IR, turnover, decay, capacity,
#: regime attribution`` — and this module owns the last two items on that
#: list.  Shared vocabulary: the feature sentence, the refusals below, and
#: every reader of a persisted estimate name the one step that sizes a
#: book, and they name it once.
CAPACITY_STEP: str = "compute_metrics"

#: The square-root impact law's coefficient — the fraction of notional a
#: trade costs at *full* participation (``q = 1``): ``cost = κ·√q``.  The
#: square-root law is the empirical convention the capacity literature
#: uses, and this constant is its intercept.  Pinned here, not configured:
#: a capacity estimate is a research metric with one definition (see the
#: module docstring's second decision), and two deployments of the same
#: evaluator must agree about it or the same node would report different
#: books under the same ``evaluator_hash``.
IMPACT_COEFFICIENT: float = 0.1

#: The fraction of the post-cost edge that must survive at the capacity
#: bound: the estimate is the book whose impact drag eats exactly
#: ``1 − 0.5`` of the edge.  "AUM at which half the edge survives" is the
#: classic capacity definition, and the half is what makes the estimate a
#: *capacity* rather than a break-even — a book sized to the break-even has
#: no margin for the estimate to be wrong in, and the estimate is a
#: research number that will be wrong.
EDGE_SURVIVAL_FRACTION: float = 0.5


# -- The inputs, as values -----------------------------------------------------


def _as_metric_date(key: object, *, kind: str) -> dt.date:
    """One keyed date, as a calendar :class:`datetime.date`.

    The same rule the charge keys and the gate's answers apply, restated
    for this step's two keyed inputs: a ``date``, or an ISO string naming
    one — a service boundary's wire spelling.  A ``datetime`` is refused
    (it names an instant, and both a dollar volume and a regime stratum
    belong to a *day*), and anything else is refused by name.
    """
    if isinstance(key, dt.datetime):
        raise EvaluatorCapacityError(
            f"the {kind} is keyed by a datetime ({key!r}); a dollar volume "
            "and a regime stratum are day-granular — key by the calendar "
            "date (or its ISO string)"
        )
    if isinstance(key, dt.date):
        return key
    if isinstance(key, str):
        try:
            return dt.date.fromisoformat(key)
        except ValueError as exc:
            raise EvaluatorCapacityError(
                f"the {kind} date {key!r} is not an ISO date; both inputs "
                "are keyed by calendar dates (or ISO date strings), one "
                "per bar"
            ) from exc
    raise EvaluatorCapacityError(
        f"{kind} dates must be dates or ISO date strings, got {key!r} "
        f"({type(key).__name__})"
    )


def _validated_volumes(
    volumes: object,
) -> dict[str, dict[dt.date, float]]:
    """The dollar volumes, validated and captured per symbol per day.

    ``{symbol: {date: dollar volume}}`` — the venue's traded notional per
    name per bar, a market fact read host-side from the sealed snapshot the
    same way step 4's closes are.  Every value must be a positive finite
    number: a zero-volume day for a name the returns scored is a hole in
    the fetch this step refuses to read as free liquidity (see
    :func:`estimate_capacity`'s coverage check), and a NaN or ±inf would
    reach the estimate dressed as a measurement.
    """
    if not isinstance(volumes, Mapping):
        raise EvaluatorCapacityError(
            "the dollar volumes must map symbol to {date: dollar volume}, "
            f"got {type(volumes).__name__}"
        )
    captured: dict[str, dict[dt.date, float]] = {}
    for symbol, row in volumes.items():
        if not isinstance(symbol, str) or not symbol:
            raise EvaluatorCapacityError(
                f"the dollar volumes' symbols must be non-empty strings, "
                f"got {symbol!r}"
            )
        if not isinstance(row, Mapping):
            raise EvaluatorCapacityError(
                f"the dollar volumes for {symbol!r} must map date to a "
                f"dollar volume, got {type(row).__name__}"
            )
        inner: dict[dt.date, float] = {}
        for key, value in row.items():
            day = _as_metric_date(key, kind="dollar volumes")
            if day in inner:
                raise EvaluatorCapacityError(
                    f"the dollar volumes for {symbol!r} carry "
                    f"{day.isoformat()} twice under different spellings; "
                    "one bar, one volume"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorCapacityError(
                    f"the dollar volume for {symbol!r} on "
                    f"{day.isoformat()} must be a number, got {value!r}"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EvaluatorCapacityError(
                    f"the dollar volume for {symbol!r} on "
                    f"{day.isoformat()} is not finite ({value!r}); a NaN or "
                    "±inf would reach the estimate dressed as a measurement"
                )
            if number <= 0.0:
                # Zero is a *fact* about a bar nobody traded, but this step
                # divides by it: pricing the name as infinitely tradable is
                # the capacity illusion produced by a hole in the data
                # rather than a thin market, so the bar is refused rather
                # than smoothed over.
                raise EvaluatorCapacityError(
                    f"the dollar volume for {symbol!r} on "
                    f"{day.isoformat()} is {value!r}; a capacity estimate "
                    "divides by the volume, and a name with no traded "
                    "notional that day is one this book cannot trade — "
                    "supply the bar or drop the symbol from the returns"
                )
            inner[day] = number
        if inner:
            captured[symbol] = inner
    return captured


def _validated_labels(labels: object) -> dict[dt.date, str]:
    """The regime strata, validated and captured per day.

    ``{date: stratum}`` — the causal labeler's answer (feature 58), read as
    a value.  Stratum names are stripped and must be non-empty, so a
    whitespace-only label cannot name a stratum nobody labeled; a name
    spelled twice under two date spellings collapses to one day, and the
    double spelling itself is refused, on the same one-bar-one-value rule
    every keyed input in this package applies.
    """
    if not isinstance(labels, Mapping):
        raise EvaluatorCapacityError(
            "the regime labels must map date to stratum name, got "
            f"{type(labels).__name__}"
        )
    captured: dict[dt.date, str] = {}
    for key, name in labels.items():
        day = _as_metric_date(key, kind="regime labels")
        if day in captured:
            raise EvaluatorCapacityError(
                f"the regime labels carry {day.isoformat()} twice under "
                "different spellings; one bar, one stratum"
            )
        if not isinstance(name, str) or not name.strip():
            raise EvaluatorCapacityError(
                f"the regime label for {day.isoformat()} must be a "
                f"non-empty stratum name, got {name!r}; strata are names "
                "(feature 283 names them), and an unnamed stratum cannot "
                "be attributed to"
            )
        captured[day] = name.strip()
    return captured


# -- The one spelling of the law ------------------------------------------------


def _solve_capacity(edge: float, drag: float) -> float:
    """The closed-form crossing: the book whose drag eats ``1 − θ`` of the edge.

    ``drag(B) = κ·√B·ā`` reaches ``(1−θ)·E`` at exactly ``((1−θ)·E/(κ·ā))²``
    — no search, no iteration, no tolerance, so the writer and the reader
    (see :mod:`evaluator._capacity_store`) recompute the same bits from the
    same terms and a stored row that disagrees with its own inputs is a
    tamper rather than a rounding story.  An edge of zero or less is the
    *finding* that the horizon supports no book, and it yields exactly
    ``0.0``.
    """
    if edge <= 0.0:
        return 0.0
    return (
        (1.0 - EDGE_SURVIVAL_FRACTION) * edge / (IMPACT_COEFFICIENT * drag)
    ) ** 2


# -- The records ----------------------------------------------------------------


@dataclass(frozen=True)
class HorizonCapacity:
    """One horizon's capacity, with the terms it was solved from.

    The per-horizon half of :class:`CapacityEstimate`.  The terms are
    carried beside the answer because an answer alone cannot be checked:
    ``capacity_usd`` is exactly :func:`_solve_capacity` over
    :attr:`mean_post_cost_return` and :attr:`impact_drag`, enforced here at
    construction and again on every read-back, so a row — or a record built
    by hand — that disagrees with its own inputs is refused rather than
    trusted.  That is the same defence the identity store applies to a hash
    that does not fold from its terms, for the same reason: what downstream
    trusts is the stored number.
    """

    #: The horizon this capacity sizes, in periods — one of
    #: :data:`HORIZONS`.
    horizon: int
    #: How many rebalance dates this horizon measured — the denominator of
    #: both means, carried because the five horizons cover different
    #: supports and a mean without its count cannot be read.
    dates: int
    #: The equal-weight mean post-cost return over those dates — ``E_h``,
    #: the edge the book is sized against.
    mean_post_cost_return: float
    #: The mean per-√$ drag over those dates — ``ā_h``, from the sealed
    #: dollar volumes.  Strictly positive by construction (every volume is
    #: finite and positive), which is what keeps the closed form finite.
    impact_drag: float
    #: The largest book this horizon supports, in dollars — ``B*_h``.
    capacity_usd: float

    def __post_init__(self) -> None:
        # object.__setattr__ where the constructor normalizes; this record
        # validates only, like the per-horizon series it summarises.
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise EvaluatorCapacityError(
                f"a horizon capacity's horizon must be an integer period "
                f"count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise EvaluatorCapacityError(
                f"horizon {self.horizon} is not one of the horizons the "
                f"spec names ({', '.join(str(h) for h in HORIZONS)}); the "
                "set is closed — feature 75 pins it and step 8 sizes each "
                "of the horizons it covers"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise EvaluatorCapacityError(
                f"a horizon capacity's date count must be an integer, got "
                f"{self.dates!r}"
            )
        if self.dates < 1:
            raise EvaluatorCapacityError(
                f"the horizon-{self.horizon} capacity claims {self.dates} "
                "measured dates; a horizon with no dates carries no "
                "capacity at all — absence, not zero — and is spelled "
                "``None`` on the estimate"
            )
        for field, value in (
            ("mean post-cost return", self.mean_post_cost_return),
            ("impact drag", self.impact_drag),
            ("capacity", self.capacity_usd),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorCapacityError(
                    f"a horizon capacity's {field} must be a number, got "
                    f"{value!r}"
                )
            if not math.isfinite(float(value)):
                raise EvaluatorCapacityError(
                    f"a horizon capacity's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the artifact "
                    "dressed as a measurement"
                )
        object.__setattr__(
            self, "mean_post_cost_return", float(self.mean_post_cost_return)
        )
        object.__setattr__(self, "impact_drag", float(self.impact_drag))
        object.__setattr__(self, "capacity_usd", float(self.capacity_usd))
        if self.impact_drag <= 0.0:
            raise EvaluatorCapacityError(
                f"the horizon-{self.horizon} capacity's impact drag is "
                f"{self.impact_drag!r}; the drag is a mean of "
                "positive terms over positive dollar volumes, and one that "
                "is not positive did not come out of this module's "
                "arithmetic"
            )
        if self.capacity_usd < 0.0:
            raise EvaluatorCapacityError(
                f"the horizon-{self.horizon} capacity is negative "
                f"({self.capacity_usd!r}); a book is a size, and a size "
                "cannot be negative"
            )
        solved = _solve_capacity(self.mean_post_cost_return, self.impact_drag)
        if self.capacity_usd != solved:
            raise EvaluatorCapacityError(
                f"the horizon-{self.horizon} capacity says "
                f"{self.capacity_usd!r} but its own terms solve to "
                f"{solved!r}; the record disagrees with itself, so it was "
                "built somewhere other than this module's arithmetic — a "
                "capacity the terms do not fold to is a number the "
                "artifact would trust and be wrong by"
            )


@dataclass(frozen=True)
class CapacityEstimate:
    """Step 8's first answer — the book the post-cost edge supports.

    The binding minimum across the five horizons, with every horizon's own
    :class:`HorizonCapacity` carried beside it — the minimum alone cannot
    say *which* measurement constrained it, and a reader deciding whether
    to re-run a node at a different horizon is the first reader that
    question matters to.  A horizon the window was too short to measure is
    carried as ``None``, never as ``0.0``: a horizon with no returns is an
    un-measured horizon, not a horizon that supports no book, and the
    difference is exactly the difference between "short window" and "no
    edge".

    The bundle is stamped with the evaluation's provenance — node, sealed
    snapshot, cost model — because the estimate is a function of a priced
    series: two fee schedules net different post-cost edges out of the same
    gross returns, so the pair is in the store's key beside the node, the
    same way it is in the signal-returns tables.
    """

    #: The node whose signal was sized.
    node_id: str
    #: The canonical name of the sealed snapshot the priced returns were
    #: measured in.
    snapshot_name: str
    #: The cost model the priced returns were netted against.
    cost_model: CostModelRef
    #: The binding capacity — ``min`` over the horizons with support, in
    #: dollars.
    capacity_usd: float
    #: The horizon that achieved the binding capacity; ties resolve to the
    #: lowest horizon index.
    binding_horizon: int
    #: One entry per horizon in :data:`HORIZONS` — a
    #: :class:`HorizonCapacity` where the horizon carried returns,
    #: ``None`` where it carried none.
    horizons: Mapping[int, Optional[HorizonCapacity]]

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise EvaluatorCapacityError(
                "a capacity estimate must name the node whose signal it "
                f"sizes, got {self.node_id!r}"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorCapacityError(
                "a capacity estimate must name the sealed snapshot its "
                f"returns were measured in, got {self.snapshot_name!r}"
            )
        if not isinstance(self.cost_model, CostModelRef):
            raise EvaluatorCapacityError(
                "a capacity estimate must name the cost model its returns "
                f"were priced under, got {type(self.cost_model).__name__}; "
                "pass a CostModelRef (or coerce one with cost_model_ref())"
            )
        if not isinstance(self.horizons, Mapping):
            raise EvaluatorCapacityError(
                "a capacity estimate's horizons must map horizon to "
                f"HorizonCapacity or None, got {type(self.horizons).__name__}"
            )
        carried = tuple(sorted(self.horizons))
        if carried != HORIZONS:
            raise EvaluatorCapacityError(
                "a capacity estimate carries one entry per horizon the "
                f"spec names ({', '.join(str(h) for h in HORIZONS)}), got "
                f"{', '.join(str(h) for h in carried) or 'none'}"
            )
        for horizon, capacity in self.horizons.items():
            if capacity is not None and capacity.horizon != horizon:
                raise EvaluatorCapacityError(
                    f"the capacity filed under horizon {horizon} carries "
                    f"horizon {capacity.horizon}; a capacity filed under "
                    "the wrong horizon is a pairing every downstream "
                    "reader would trust and be wrong by"
                )
        measured = [
            capacity
            for capacity in self.horizons.values()
            if capacity is not None
        ]
        if not measured:
            raise EvaluatorCapacityError(
                "a capacity estimate with no measured horizon has no edge "
                "to size — the bundle it was built from measured nothing, "
                "which step 7 refuses and no step 8 should paper over"
            )
        if isinstance(self.capacity_usd, bool) or not isinstance(
            self.capacity_usd, (int, float)
        ):
            raise EvaluatorCapacityError(
                f"the capacity must be a number, got {self.capacity_usd!r}"
            )
        object.__setattr__(self, "capacity_usd", float(self.capacity_usd))
        if not math.isfinite(self.capacity_usd):
            raise EvaluatorCapacityError(
                f"the capacity is not finite ({self.capacity_usd!r}); a "
                "NaN or ±inf would reach the artifact dressed as a "
                "measurement"
            )
        binding = min(measured, key=lambda capacity: capacity.capacity_usd)
        if self.capacity_usd != binding.capacity_usd:
            raise EvaluatorCapacityError(
                f"the estimate says {self.capacity_usd!r} but its own "
                f"horizons bind at {binding.capacity_usd!r}; the reported "
                "capacity is the minimum of the per-horizon capacities, "
                "and a record that disagrees with its own terms did not "
                "come out of this module"
            )
        if isinstance(self.binding_horizon, bool) or not isinstance(
            self.binding_horizon, int
        ):
            raise EvaluatorCapacityError(
                "the binding horizon must be an integer period count, got "
                f"{self.binding_horizon!r}"
            )
        # The lowest horizon achieving the minimum wins ties — the same
        # deterministic tie-break the labeler's nearest-center rule states,
        # for the same reason: the answer must not depend on iteration
        # order.
        expected = min(
            horizon
            for horizon in HORIZONS
            if self.horizons[horizon] is not None
            and self.horizons[horizon].capacity_usd  # type: ignore[union-attr]
            == self.capacity_usd
        )
        if self.binding_horizon != expected:
            raise EvaluatorCapacityError(
                f"the binding horizon is {self.binding_horizon} but the "
                f"lowest horizon achieving {self.capacity_usd!r} is "
                f"{expected}; the binding horizon names the measurement "
                "that constrained the book, and it is not the caller's "
                "to choose"
            )
        object.__setattr__(
            self, "horizons", MappingProxyType(dict(self.horizons))
        )

    @property
    def binding(self) -> HorizonCapacity:
        """The horizon capacity that set :attr:`capacity_usd`."""
        binding = self.horizons[self.binding_horizon]
        assert binding is not None  # validated at construction
        return binding

    def at(self, horizon: int) -> Optional[HorizonCapacity]:
        """One horizon's capacity, or ``None`` where the horizon is un-measured.

        Refused for a horizon outside :data:`HORIZONS` — the set is closed,
        on the same terms as every per-horizon accessor this package
        carries.
        """
        if horizon not in self.horizons:
            raise EvaluatorCapacityError(
                f"horizon {horizon} is not one of the horizons this "
                f"estimate carries ({', '.join(str(h) for h in HORIZONS)}); "
                "the set is the spec's, not the caller's to widen"
            )
        return self.horizons[horizon]

    def __hash__(self) -> int:
        # The mapping is not hashable until it collapses to tuples; the
        # fold keeps __hash__ consistent with __eq__, as every record in
        # this package does.
        return hash(
            (
                self.node_id,
                self.snapshot_name,
                self.cost_model,
                self.capacity_usd,
                self.binding_horizon,
                tuple(
                    (horizon, self.horizons[horizon])
                    for horizon in HORIZONS
                ),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"CapacityEstimate(node={self.node_id!r}, "
            f"${self.capacity_usd:,.0f} at h={self.binding_horizon})"
        )


@dataclass(frozen=True)
class StratumSlice:
    """One stratum's measured edge at one horizon.

    The atom of the attribution: a stratum, a horizon, how many labeled
    dates that horizon measured, and the equal-weight mean post-cost return
    over exactly those dates.  The count is carried because the five
    horizons cover different supports *and* the strata partition the grid
    unevenly — a stratum's horizon-1 mean over 3 dates and its horizon-20
    mean over 2 are different measurements, and a reader who could not see
    the denominators would read them as one series.
    """

    #: The horizon this slice measured — one of :data:`HORIZONS`.
    horizon: int
    #: How many labeled dates the slice measured at this horizon.
    dates: int
    #: The equal-weight mean post-cost return over those dates — the same
    #: reduction the capacity half measures, stated once in the module
    #: docstring and shared.
    mean_post_cost_return: float

    def __post_init__(self) -> None:
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise EvaluatorCapacityError(
                f"a stratum slice's horizon must be an integer period "
                f"count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise EvaluatorCapacityError(
                f"horizon {self.horizon} is not one of the horizons the "
                f"spec names ({', '.join(str(h) for h in HORIZONS)}); the "
                "attribution is filed per horizon and the set is closed"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise EvaluatorCapacityError(
                f"a stratum slice's date count must be an integer, got "
                f"{self.dates!r}"
            )
        if self.dates < 1:
            raise EvaluatorCapacityError(
                f"the horizon-{self.horizon} slice claims {self.dates} "
                "measured dates; a stratum measured at no date at a "
                "horizon carries *no* slice there — absence, not zero — "
                "so the horizon's key is simply missing from the stratum"
            )
        if (
            isinstance(self.mean_post_cost_return, bool)
            or not isinstance(self.mean_post_cost_return, (int, float))
            or not math.isfinite(float(self.mean_post_cost_return))
        ):
            raise EvaluatorCapacityError(
                f"a stratum slice's mean post-cost return must be a finite "
                f"number, got {self.mean_post_cost_return!r}"
            )
        object.__setattr__(
            self, "mean_post_cost_return", float(self.mean_post_cost_return)
        )


@dataclass(frozen=True)
class StratumAttribution:
    """One named stratum's attribution — its slices, per measured horizon.

    ``slices`` carries one :class:`StratumSlice` per horizon where at least
    one of that horizon's dates carried this stratum's label; a horizon
    with none is *absent*, not zero-filled, so "measured a mean of zero"
    and "never measured at that horizon" stay distinguishable.  A stratum
    named on the grid but measured at no horizon at all — its labeled dates
    all fell outside every horizon's support, which a short window makes
    real — is carried with *empty* slices rather than dropped, the same
    "write the zero" discipline §C7's coverage ledger applies: a named
    stratum is a fact about the labels, and an un-measured one is a
    different fact from an unnamed one.
    """

    #: The stratum's name, as the labels spell it.
    stratum: str
    #: The per-horizon slices, keyed by horizon; empty for a stratum named
    #: on the grid but measured at no horizon.
    slices: Mapping[int, StratumSlice]

    def __post_init__(self) -> None:
        if not isinstance(self.stratum, str) or not self.stratum.strip():
            raise EvaluatorCapacityError(
                f"a stratum attribution must name its stratum, got "
                f"{self.stratum!r}; strata are names, and an unnamed "
                "stratum cannot be attributed to"
            )
        object.__setattr__(self, "stratum", self.stratum.strip())
        if not isinstance(self.slices, Mapping):
            raise EvaluatorCapacityError(
                "a stratum attribution's slices must map horizon to "
                f"StratumSlice, got {type(self.slices).__name__}"
            )
        for horizon, slice_ in self.slices.items():
            if slice_.horizon != horizon:
                raise EvaluatorCapacityError(
                    f"the slice filed under horizon {horizon} carries "
                    f"horizon {slice_.horizon}; a slice filed under the "
                    "wrong horizon is a pairing every stratified reader "
                    "would trust and be wrong by"
                )
        object.__setattr__(
            self, "slices", MappingProxyType(dict(self.slices))
        )

    @property
    def measured_horizons(self) -> Tuple[int, ...]:
        """The horizons this stratum was measured at, ascending."""
        return tuple(sorted(self.slices))

    def at(self, horizon: int) -> Optional[StratumSlice]:
        """One horizon's slice, or ``None`` where the stratum was un-measured.

        Refused for a horizon outside :data:`HORIZONS`, on the same closed
        set every accessor in this package enforces.
        """
        if horizon not in HORIZONS:
            raise EvaluatorCapacityError(
                f"horizon {horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}); the "
                "attribution is filed per horizon and the set is the "
                "spec's, not the caller's to widen"
            )
        return self.slices.get(horizon)

    def __hash__(self) -> int:
        # Same fold as the estimate's, for the same reason.
        return hash((self.stratum, tuple(sorted(self.slices.items()))))

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"StratumAttribution({self.stratum!r}, "
            f"{len(self.slices)} horizons)"
        )


@dataclass(frozen=True)
class RegimeAttribution:
    """Step 8's second answer — where the edge lives, per named stratum.

    One :class:`StratumAttribution` per stratum the labels name on the
    rebalance grid, plus the count of grid dates that carried no label at
    all.  The un-attributed count is carried rather than dropped because it
    is the honest denominator caveat: an attribution over a grid whose
    every date was labeled and one over a grid whose labels cover half the
    dates are different qualities of evidence, and a reader comparing two
    nodes' attributions is exactly the reader the difference matters to.

    Stamped with the same provenance triple as the estimate, because the
    two halves persist together (see :mod:`evaluator._capacity_store`) and
    a pair that disagreed about whose returns it was computed over could
    not.
    """

    #: The node whose signal was attributed.
    node_id: str
    #: The canonical name of the sealed snapshot the priced returns were
    #: measured in.
    snapshot_name: str
    #: The cost model the priced returns were netted against.
    cost_model: CostModelRef
    #: One attribution per stratum named on the grid — including a stratum
    #: measured at no horizon, carried with empty slices.
    strata: Mapping[str, StratumAttribution]
    #: How many rebalance dates carried no regime label — carried, never
    #: silently excluded.
    unattributed_dates: int

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise EvaluatorCapacityError(
                "a regime attribution must name the node whose signal it "
                f"attributes, got {self.node_id!r}"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorCapacityError(
                "a regime attribution must name the sealed snapshot its "
                f"returns were measured in, got {self.snapshot_name!r}"
            )
        if not isinstance(self.cost_model, CostModelRef):
            raise EvaluatorCapacityError(
                "a regime attribution must name the cost model its returns "
                f"were priced under, got {type(self.cost_model).__name__}; "
                "pass a CostModelRef (or coerce one with cost_model_ref())"
            )
        if not isinstance(self.strata, Mapping):
            raise EvaluatorCapacityError(
                "a regime attribution's strata must map stratum name to "
                f"StratumAttribution, got {type(self.strata).__name__}"
            )
        for name, attribution in self.strata.items():
            if attribution.stratum != name:
                raise EvaluatorCapacityError(
                    f"the attribution filed under {name!r} names stratum "
                    f"{attribution.stratum!r}; a stratum filed under the "
                    "wrong name is a pairing every stratified reader would "
                    "trust and be wrong by"
                )
        if not self.strata:
            raise EvaluatorCapacityError(
                "a regime attribution with no strata attributed nothing; "
                "an evaluation whose every grid date carried no label has "
                "no attribution to persist, and step 8 refuses it rather "
                "than writing an empty one"
            )
        if isinstance(self.unattributed_dates, bool) or not isinstance(
            self.unattributed_dates, int
        ):
            raise EvaluatorCapacityError(
                "the un-attributed date count must be an integer, got "
                f"{self.unattributed_dates!r}"
            )
        if self.unattributed_dates < 0:
            raise EvaluatorCapacityError(
                f"the un-attributed date count is negative "
                f"({self.unattributed_dates!r}); it counts grid dates "
                "carrying no label, and a count cannot be negative"
            )
        object.__setattr__(
            self, "strata", MappingProxyType(dict(self.strata))
        )

    @property
    def named_strata(self) -> Tuple[str, ...]:
        """The strata carried, sorted — stable for readers and writers alike."""
        return tuple(sorted(self.strata))

    def stratum(self, name: str) -> StratumAttribution:
        """One stratum's attribution.

        Refused for a name the attribution does not carry: a stratum nobody
        named on the grid is not an empty attribution, it is an absence,
        and returning an invented empty one would blur exactly the
        distinction §C7's ledger keeps by writing real zeros only for
        strata somebody named.
        """
        if name not in self.strata:
            raise EvaluatorCapacityError(
                f"the attribution carries no stratum {name!r}; the strata "
                f"named on the grid are {', '.join(self.named_strata)} — a "
                "stratum nobody named is absent, not empty"
            )
        return self.strata[name]

    def __hash__(self) -> int:
        # Same fold as the estimate's, for the same reason.
        return hash(
            (
                self.node_id,
                self.snapshot_name,
                self.cost_model,
                self.unattributed_dates,
                tuple(sorted(self.strata.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"RegimeAttribution(node={self.node_id!r}, "
            f"{len(self.strata)} strata, "
            f"{self.unattributed_dates} un-attributed)"
        )


# -- The one reduction both halves share -----------------------------------------


def _date_edge(row: Mapping[str, float]) -> float:
    """One date's equal-weight cross-sectional mean post-cost return.

    The unit book's return on that date: equal weight across the
    cross-section the returns carry, the workspace's one weighting
    convention (feature 55's market series is the same mean).  ``fsum``
    keeps it exact regardless of the row's iteration order, which is what
    makes the same panel attribute identically however it was built.
    """
    return math.fsum(row[symbol] for symbol in sorted(row)) / len(row)


# -- Step 8's first half ---------------------------------------------------------


def estimate_capacity(
    returns: PostCostReturns,
    volumes: Mapping[str, Mapping[object, float]],
) -> CapacityEstimate:
    """Size the book the post-cost edge supports — step 8's capacity half.

    For every horizon in :data:`HORIZONS` that ``returns`` covers, measure
    the equal-weight edge and the per-√$ drag over that horizon's own
    support, solve the closed-form crossing (:func:`_solve_capacity`), and
    keep every horizon's :class:`HorizonCapacity` beside the binding
    minimum.  A horizon with no returns carries ``None`` — un-measured, not
    zero — and a bundle with no measured horizon is refused (no edge to
    size).

    ``volumes`` is the sealed dollar volumes as ``{symbol: {date: dollars}}``
    — the venue's traded notional per name per bar, a market fact read
    host-side from the sealed snapshot, exactly as step 4's closes arrive.
    Volumes for symbols or dates the returns do not score are validated and
    then ignored, so a whole-market fetch and a scored-universe fetch size
    the same book; a ``(symbol, date)`` the returns score that the volumes
    *miss* is refused, because pricing a name nobody traded that day as
    infinitely tradable is the capacity illusion produced by a hole in the
    fetch rather than a thin market.

    Raises :class:`~evaluator.EvaluatorCapacityError`, each with its
    reason (see ``_errors``): a ``returns`` that is not step 7's own
    result; a ``volumes`` mapping that is malformed, carries a non-positive
    or non-finite volume, or misses a covered ``(symbol, date)``; a bundle
    whose every horizon is empty; and — via the records — a hand-built
    estimate whose capacity is not the minimum of its own horizons.
    """
    if not isinstance(returns, PostCostReturns):
        raise EvaluatorCapacityError(
            "estimate_capacity sizes step 7's own result — a "
            "PostCostReturns, the priced series the cost schedule "
            f"produced — got {type(returns).__name__}; the edge being "
            "sized is the edge that was actually netted, and the gross "
            "series alone cannot say which fee schedule netted it"
        )
    validated = _validated_volumes(volumes)

    horizons: dict[int, Optional[HorizonCapacity]] = {}
    for horizon in HORIZONS:
        series = returns.series[horizon]
        dates = series.dates()
        if not dates:
            horizons[horizon] = None
            continue
        # The coverage check runs before any arithmetic, so a hole in the
        # volumes can never become an infinite capacity by accident of
        # evaluation order.
        missing: list[str] = []
        for day in dates:
            row = series.at(day)
            for symbol in row:
                if day not in validated.get(symbol, {}):
                    missing.append(f"{symbol} on {day.isoformat()}")
        if missing:
            listed = "; ".join(missing[:3]) + (
                f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
            )
            raise EvaluatorCapacityError(
                f"the dollar volumes miss returns this evaluation scored — "
                f"{listed}; a missing volume is not free liquidity, and "
                "sizing the book without it would read a name nobody can "
                "trade as infinitely tradable"
            )
        edges: list[float] = []
        drags: list[float] = []
        for day in dates:
            row = series.at(day)
            count = len(row)
            edges.append(_date_edge(row))
            drags.append(
                math.fsum(
                    1.0
                    / math.sqrt(count * validated[symbol][day])
                    for symbol in sorted(row)
                )
                / count
            )
        edge = math.fsum(edges) / len(edges)
        drag = math.fsum(drags) / len(drags)
        horizons[horizon] = HorizonCapacity(
            horizon=horizon,
            dates=len(dates),
            mean_post_cost_return=edge,
            impact_drag=drag,
            capacity_usd=_solve_capacity(edge, drag),
        )

    if all(capacity is None for capacity in horizons.values()):
        raise EvaluatorCapacityError(
            "the bundle carries no computable return at any horizon, so "
            "there is no edge to size and no capacity to persist — an "
            "estimate of anything would report a book for an evaluation "
            "that measured nothing; gate and cost an alignment with "
            "coverage first (features 75 through 79)"
        )

    binding = min(
        (
            capacity
            for capacity in horizons.values()
            if capacity is not None
        ),
        key=lambda capacity: capacity.capacity_usd,
    )
    binding_horizon = min(
        horizon
        for horizon in HORIZONS
        if horizons[horizon] is not None
        and horizons[horizon].capacity_usd == binding.capacity_usd
    )
    return CapacityEstimate(
        node_id=returns.node_id,
        snapshot_name=returns.snapshot_name,
        cost_model=returns.cost_model,
        capacity_usd=binding.capacity_usd,
        binding_horizon=binding_horizon,
        horizons=MappingProxyType(horizons),
    )


# -- Step 8's second half --------------------------------------------------------


def attribute_regimes(
    returns: PostCostReturns,
    labels: Mapping[object, str],
) -> RegimeAttribution:
    """Split the edge across named regime strata — step 8's other half.

    For every stratum the ``labels`` name on the rebalance grid, and every
    horizon in :data:`HORIZONS`, the equal-weight mean post-cost return
    over exactly that horizon's labeled dates, as a :class:`StratumSlice`
    carrying its own date count.  A label for a date outside the grid is
    ignored (a whole-market labelling and a grid labelling attribute
    identically, the same reproducibility rule the alignment applies to
    closes); a grid date with no label is counted in
    :attr:`RegimeAttribution.unattributed_dates` and measured nowhere; a
    stratum measured at no horizon is carried with empty slices, not
    dropped.

    ``labels`` is ``{date: stratum}`` — feature 58's causal rolling-window
    labeler's answer, read as a value.  This function fits nothing: the
    trailing-window discipline that makes labels causal is the labeler's
    contract to enforce, and restating it here would be a second labeler in
    exactly the way a second fee schedule is one (feature 69's logic,
    applied to labels).

    Raises :class:`~evaluator.EvaluatorCapacityError`, each with its
    reason (see ``_errors``): a ``returns`` that is not step 7's own
    result; a ``labels`` mapping that is malformed or carries a blank
    stratum name; and a grid whose every date carries no label (nothing to
    attribute — an empty attribution would report a split for an evaluation
    whose regimes were never named).
    """
    if not isinstance(returns, PostCostReturns):
        raise EvaluatorCapacityError(
            "attribute_regimes attributes step 7's own result — a "
            "PostCostReturns, the priced series the cost schedule "
            f"produced — got {type(returns).__name__}; the edge being "
            "split is the edge that was actually netted, and the gross "
            "series alone cannot say which fee schedule netted it"
        )
    validated = _validated_labels(labels)

    grid = returns.rebalance_dates
    labeled = {
        day: validated[day] for day in grid if day in validated
    }
    if not labeled:
        raise EvaluatorCapacityError(
            "no rebalance date of this evaluation carries a regime label, "
            "so there is nothing to attribute — five empty strata would "
            "report a split for an evaluation whose regimes were never "
            "named; supply the causal labeler's answer for the grid "
            "(feature 58)"
        )

    # {stratum: {horizon: [edge per labeled date in that horizon's support]}}
    observed: dict[str, dict[int, list[float]]] = {
        name: {} for name in labeled.values()
    }
    for horizon in HORIZONS:
        series = returns.series[horizon]
        for day in series.dates():
            name = labeled.get(day)
            if name is None:
                continue
            observed[name].setdefault(horizon, []).append(
                _date_edge(series.at(day))
            )

    strata: dict[str, StratumAttribution] = {}
    for name, by_horizon in observed.items():
        slices = {
            horizon: StratumSlice(
                horizon=horizon,
                dates=len(edges),
                mean_post_cost_return=math.fsum(edges) / len(edges),
            )
            for horizon, edges in sorted(by_horizon.items())
        }
        strata[name] = StratumAttribution(
            stratum=name, slices=MappingProxyType(slices)
        )

    return RegimeAttribution(
        node_id=returns.node_id,
        snapshot_name=returns.snapshot_name,
        cost_model=returns.cost_model,
        strata=MappingProxyType(strata),
        unattributed_dates=len(grid) - len(labeled),
    )
