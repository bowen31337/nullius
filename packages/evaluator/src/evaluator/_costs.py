"""Applying the cost model to the aligned returns — pipeline step 7.

app_spec.xml feature 79: *"System applies the cost model to the aligned
returns, persisting a post-cost signal return series per symbol."*
docs/nullius-tech-architecture.md §6.1 names the step — ``7. apply_costs
venue fee schedule + queue-position fill model`` — and §9.2 names what it
leaves behind:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost  ← enables ir_marginal

That artifact is the point of the step, and its comment is the reason it is
kept in full: because the *per-symbol* series survives, marginal
contribution against any book can be recomputed at replay time, so the same
node scores differently depending on the path a policy took to reach it
while replay stays fully deterministic. A step that reported only a
summary — a mean cost, a total drag — would make that recomputation
impossible, which is why the feature sentence says "per symbol" and why
this module reduces nothing.

The feature sentence has three phrases, and each is a decision this module
enforces rather than a choice it offers:

*the cost model*
    Not "a fee schedule" and not "the fees in the configuration". §6.2 is
    explicit that the cost library is *shared*: *"Shared library used by
    both the evaluator and the live execution engine. Divergence between
    these two is exactly the quantity ``β₄`` penalizes, so they must be the
    same code, not two implementations of the same document"*, and feature
    69 states the refusal independently ("rejects a second implementation
    of the fee schedule"). So this module computes **no** fee arithmetic of
    its own: no bps constant, no taker/maker split, no rounding, no
    discount. What it owns is the *application* — which returns get charged,
    against which cost model's identity, and what the charged series means.
    The charges themselves arrive through an injected seam
    (:data:`CostSchedule`), exactly as §7.2's oracle arrives at step 5 and
    the lake read arrives at step 2 — the shared library is wired
    underneath by the deployment, never reached for here. A member of this
    package that hard-coded 10 bps would *be* the second implementation
    feature 69 exists to reject.

*the aligned returns*
    The series charged are step 5's: :class:`~evaluator.GatedTargets`, the
    null gate's own answer, not step 4's alignment. The distinction is not
    bookkeeping. A node whose targets were block-permuted was measured
    against a *different* world, and the costs it is charged must be the
    costs of the world it was actually measured in — charging the real
    returns while the metrics measure the permuted ones would price one
    experiment and report another. §6.1's ordering puts ``apply_costs``
    after ``null_gate`` for this reason, and feature 79's ``depends_on`` is
    feature 76 rather than 75. What flows in is whatever the gate supplied;
    this module never compares those values to the aligned ones, because
    that comparison is the client-side null detector principle P2 forbids
    (see ``_gate``).

*persisting a post-cost signal return series per symbol*
    Two verbs again — *applies* and *persists* — and the same split this
    package already uses for feature 70: the arithmetic lives here, the row
    in :mod:`evaluator._cost_store`. The series is keyed
    ``(rebalance date, symbol)`` per horizon, on exactly the support the
    gate answered on, and what it carries is
    ``post_cost = gross − charge``. The *charge* is carried beside the
    post-cost return rather than discarded, so the persisted row explains
    the difference between what the signal predicted and what it would have
    earned — "how much did the fee schedule eat?" is the first question
    anyone asks of a cost-adjusted number, and a series that stored only
    the net would make it unanswerable without re-running the schedule.

Three refusals carry the feature, and each is a case where the alternative
would be a plausible-looking lie:

* *A quote priced under a different cost model is refused.* Step 7 charges
  one evaluation against one cost model, and the pair the caller names is
  stamped on every series it returns. A schedule that answers with a
  different ``(venue, version)`` has priced a different fee schedule — the
  §15 failure table's "cost model changed" case — and applying it would
  file numbers under one cost model's provenance while computing them with
  another's. This is the mirror of the gate's snapshot pin, on the cost
  axis: one evaluation reads one sealed world *and* prices one schedule.
* *A charge series that does not live on the charged support is refused.*
  Every date the gross series covers must be quoted, and every symbol on
  each of those dates, no wider and no narrower. A quote for a symbol
  nobody scored is a charge for nobody; a *missing* quote is not a free
  trade, it is a hole in the fee schedule, and pricing it as zero would
  understate the cost in the one direction the whole method cares about
  (§6.1 step 7 is what turns a label into a return an account would have
  earned; feature 64 makes the same point from the other side — "a
  zero-maker venue still returns a nonzero cost"). Absence is not zero,
  the same rule the alignment enforces one step earlier.
* *An evaluation with nothing chargeable is refused, not returned empty.*
  A bundle whose every horizon is empty has no return to net a cost out of;
  five empty series would report "costed" for an evaluation that measured
  nothing. Per-*horizon* emptiness is fine — a short window legitimately
  leaves the long horizons with no dates — and is carried as an empty
  series, keeping feature 75's five-horizon shape promise.

**Sign, and what is deliberately not refused.** A charge is normally a
non-negative deduction, but this module does **not** require one: maker
rebates are a real feature of real venues, and §6.2's document prices a
maker at the same 10 bps as a taker only for the venue it happens to
describe. Refusing a negative charge would be inventing a policy the spec
does not state, and it would refuse it inside the evaluator — the one place
that must not hold a fee opinion. What *is* refused is a charge that is not
finite: a NaN or ±inf would propagate silently into every downstream metric
dressed as a measurement.

**What this module does not do.** It does not compute fees (feature 61-62,
the shared library), model fills, queue position or book walking (63-66),
measure latency (67) or source borrow (68); it does not purge or embargo
(77-78 — folds, not returns); it does not certify the gate's supply
(feature 76's :func:`~evaluator.check_targets_gated` — a caller wanting
that certification asks for it, and this module states that it consumes the
gate's answer rather than re-deriving it); and it computes no metric
(features 80 on). It takes a gated bundle and a cost schedule and answers
exactly the one question step 7 puts in scope: *what would this signal have
earned, per symbol, once its fee schedule was paid?*

**The layering note.** This module is stdlib-only — records, mappings and
dates; no polars, no pyarrow, no lake, no environment, no HTTP, and no
import of the cost-model member. The schedule is the injected seam, so
importing this member pays nothing, which keeps composition — and the
replay path §1 forbids from reaching the evaluator — as cheap as the
alignment this module charges.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Tuple

from ._align import HORIZONS, TargetSeries
from ._errors import EvaluatorCostError
from ._gate import GatedTargets

__all__ = [
    "COST_STEP",
    "CostModelRef",
    "CostQuote",
    "CostRequest",
    "CostSchedule",
    "PostCostReturns",
    "PostCostSeries",
    "apply_costs",
    "cost_model_ref",
]

#: The pipeline-step name, in §6.1's own spelling.  Shared vocabulary: the
#: feature sentence, the refusals below, and every reader of a persisted
#: series name the one step that turns a label into a net return, and they
#: name it once.
COST_STEP: str = "apply_costs"

#: The cost-schedule seam — §6.2's shared cost library, injected into
#: :func:`apply_costs`.  Takes the request, returns the quote; a schedule
#: that raises propagates (its failures are its own, like an HTTP client's),
#: and a return that is not a :class:`CostQuote` is refused by the caller.
#:
#: The seam exists so that the fee arithmetic stays in the one shared
#: library §6.2 and feature 69 require.  This package's contribution is the
#: *pairing* — which returns, under which cost model's identity, on which
#: support — never the fees.
CostSchedule = Callable[["CostRequest"], "CostQuote"]


# -- The cost model's identity, on this side of the seam -----------------------


def _as_component(value: object, field: str) -> str:
    """Return ``value`` as one component of a cost model's identity.

    The same rule :class:`cost_model.config.CostModelConfig` applies to its
    own pair, restated here rather than imported: this module must not
    depend on the cost-model member (it is stdlib-only and import-cheap by
    design), but the *spelling* of the pair has to agree with it, because
    the two are compared — the venue and version a quote names are checked
    against the ones the caller named, and a member that accepted ``""``
    where the library refuses it would let an unnamed cost model look like
    a priced one.
    """
    if not isinstance(value, str):
        raise EvaluatorCostError(
            f"the cost model's {field} must be a string, got "
            f"{type(value).__name__} ({value!r}); a cost model is identified "
            "by its (venue, version) pair — feature 59 — and a non-string is "
            "not half of one"
        )
    text = value.strip()
    if not text:
        raise EvaluatorCostError(
            f"the cost model's {field} is blank; a resolved cost model names "
            f"a non-empty {field}"
        )
    return text


@dataclass(frozen=True)
class CostModelRef:
    """The ``(venue, version)`` pair feature 59 persists, as step 7 names it.

    The identity every post-cost series is stamped with: which fee schedule
    these returns were netted against.  §14.1's provenance triple pins
    ``cost_model_hash`` as its own axis — deliberately separate from
    ``evaluator_hash`` — and the reason is stated in ``_config``: folding
    fees into the evaluator's identity would make a re-priced venue look
    like a changed evaluator, and "the two hashes §15 relies on to tell
    those cases apart would stop disagreeing in the way they are meant to".
    So the cost axis is carried here, on the value it belongs to, rather
    than absorbed anywhere.

    Small by design, and not a re-implementation of the library's own
    config record: :class:`cost_model.config.CostModelConfig` carries a
    ``source`` and will grow a hash (feature 60), and neither belongs on a
    return series.  What step 7 needs from the library is exactly which
    schedule priced these returns, so that is exactly what this carries.
    """

    #: The venue whose schedule priced the returns.
    venue: str
    #: The version string of that schedule, as the document carries it.
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _as_component(self.venue, "venue"))
        object.__setattr__(
            self, "version", _as_component(self.version, "version")
        )

    @property
    def reference(self) -> str:
        """The pair as one string: ``"<venue>/<version>"``.

        The same spelling :attr:`cost_model.config.CostModelConfig.reference`
        uses, so a row written by this package and a row written by the cost
        model member name the same cost model the same way.
        """
        return f"{self.venue}/{self.version}"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.reference


def cost_model_ref(config: object) -> CostModelRef:
    """Coerce a resolved cost model to the pair step 7 stamps.

    Accepts a :class:`CostModelRef` as-is, a mapping carrying ``venue`` and
    ``version``, or any object exposing those two attributes — which is what
    makes ``cost_model.CostModelConfig`` (feature 59's resolved value) drop
    straight in without this package importing the cost-model member.  That
    duck-typed seam is the point: §6.2 and feature 69 require research
    evaluation and live execution to price against *one* shared library, and
    a hard import here would either create a package dependency this member
    does not have or tempt a second ``(venue, version)`` reader into
    existing beside the library's own.

    Anything without both components is refused by name, because a cost
    model that cannot say which schedule it is cannot be stamped on a
    series — and an unstamped post-cost series is a number whose fee
    assumptions are unknown, which is the state feature 59 exists to rule
    out.
    """
    if isinstance(config, CostModelRef):
        return config
    if isinstance(config, Mapping):
        venue = config.get("venue")
        version = config.get("version")
    else:
        venue = getattr(config, "venue", None)
        version = getattr(config, "version", None)
    if venue is None or version is None:
        raise EvaluatorCostError(
            "the cost model must name its (venue, version) pair — feature "
            "59's resolved identity, the thing every post-cost series is "
            f"stamped with — got {config!r} ({type(config).__name__}); pass "
            "a CostModelRef, or the shared cost library's resolved config"
        )
    return CostModelRef(venue=venue, version=version)


# -- The seam's records --------------------------------------------------------


def _as_charge_date(key: object) -> dt.date:
    """One charge key, as a calendar :class:`datetime.date`.

    Accepted spellings: a ``date``, or an ISO string naming one — a service
    boundary's wire spelling, the same courtesy ``_gate._as_response_date``
    extends §7.2's answers.  A ``datetime`` is refused (it names an instant,
    and a return is day-granular: silently truncating it would be a guess
    about which bar the charge belongs to), and anything else is refused by
    name.
    """
    if isinstance(key, dt.datetime):
        raise EvaluatorCostError(
            f"the charge series is keyed by a datetime ({key!r}); a "
            "post-cost return is day-granular — key by the calendar date "
            "(or its ISO string)"
        )
    if isinstance(key, dt.date):
        return key
    if isinstance(key, str):
        try:
            return dt.date.fromisoformat(key)
        except ValueError as exc:
            raise EvaluatorCostError(
                f"the charge date {key!r} is not an ISO date; the series is "
                "keyed by calendar dates (or ISO date strings), one per bar"
            ) from exc
    raise EvaluatorCostError(
        f"charge dates must be dates or ISO date strings, got {key!r} "
        f"({type(key).__name__})"
    )


def _validated_row(
    row: object, day: dt.date, *, label: str
) -> Mapping[str, float]:
    """One date's ``{symbol: return}`` row, validated and captured read-only.

    The single validator for the two series this module carries — the gross
    returns in a request and the charges in a quote — so the two cannot
    drift into different rules.  Values must be finite numbers: a NaN or
    ±inf would reach every downstream metric dressed as a measurement, on
    either side of the subtraction.
    """
    if not isinstance(row, Mapping):
        raise EvaluatorCostError(
            f"the {label} for {day.isoformat()} must map symbol to a number, "
            f"got {type(row).__name__}"
        )
    inner: dict[str, float] = {}
    for symbol, value in row.items():
        if not isinstance(symbol, str) or not symbol:
            raise EvaluatorCostError(
                f"the {label} symbols for {day.isoformat()} must be "
                f"non-empty strings, got {symbol!r}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluatorCostError(
                f"the {label} for {symbol!r} on {day.isoformat()} must be a "
                f"number, got {value!r}"
            )
        number = float(value)
        if not math.isfinite(number):
            raise EvaluatorCostError(
                f"the {label} for {symbol!r} on {day.isoformat()} is not "
                f"finite ({value!r}); a NaN or ±inf would reach the metrics "
                "dressed as a measurement"
            )
        inner[symbol] = number
    return MappingProxyType(inner)


@dataclass(frozen=True)
class CostRequest:
    """What step 7 asks the shared cost library — one ask per covered horizon.

    The gross returns the schedule is being asked to price, together with
    the terms it prices them under: which node's evaluation this is, which
    ``(venue, version)`` schedule must answer, which horizon the returns
    measure, and the support they live on.  Built by :func:`apply_costs`
    from the gated bundle's own series, so a schedule — or a test, or an
    audit log — reads exactly what was charged and nothing that was not.

    ``gross_returns`` is the whole question, not a sample of it: a schedule
    that cannot see the returns cannot charge a model that depends on them
    (a proportional fee, a slippage figure keyed to the move), and one that
    is handed only a summary would have to answer for a world nobody ran.
    Its support is validated eagerly — every date carries a cross-section
    that is a subset of :attr:`symbols` (a point-in-time universe: a listing
    or a delisting inside the horizon's own span need not leave every date
    with the same symbols), the union of every date's cross-section recovers
    :attr:`symbols` exactly, and the dates span exactly :attr:`date_range` —
    so the record is internally consistent rather than merely well-formed.

    Hashable, like §7.2's request: the returns mapping folds to nested
    tuples (see :meth:`__hash__`).
    """

    #: The node being evaluated — whose signal these returns are.
    node_id: str
    #: The venue of the cost model that must answer.
    venue: str
    #: The version of the cost model that must answer.
    version: str
    #: The horizon these returns measure — one of :data:`HORIZONS`.
    horizon: int
    #: Every symbol the gross series names across all its dates — the union
    #: of each date's own cross-section, sorted and de-duplicated.  A date's
    #: own row may be a strict subset (a listing or a delisting partway
    #: through the horizon's span); every symbol named here must still
    #: appear on at least one date, and no date may name a symbol outside it.
    symbols: Tuple[str, ...]
    #: The span of the gross returns' dates, as ``(first, last)``.
    date_range: Tuple[dt.date, dt.date]
    #: The gross (pre-cost) returns being charged, as ``{rebalance date:
    #: {symbol: forward return}}`` — step 5's supplied series, verbatim.
    gross_returns: Mapping[dt.date, Mapping[str, float]]

    def __post_init__(self) -> None:
        # object.__setattr__ throughout: frozen dataclass, and these are
        # normalizations of arguments the constructor accepted.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise EvaluatorCostError(
                "node_id must be a non-empty string — the evaluation whose "
                f"returns are being charged — got {self.node_id!r}"
            )
        object.__setattr__(self, "venue", _as_component(self.venue, "venue"))
        object.__setattr__(
            self, "version", _as_component(self.version, "version")
        )
        if (
            isinstance(self.horizon, bool)
            or not isinstance(self.horizon, int)
            or self.horizon not in HORIZONS
        ):
            raise EvaluatorCostError(
                "the request's horizon must be one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}), got "
                f"{self.horizon!r}; step 7 charges each horizon's own series"
            )
        if not isinstance(self.symbols, tuple) or not self.symbols:
            raise EvaluatorCostError(
                "symbols must be a non-empty tuple of the symbols the gross "
                f"series carries, got {self.symbols!r}; a covered horizon has "
                "a cross-section to charge"
            )
        for symbol in self.symbols:
            if not isinstance(symbol, str) or not symbol:
                raise EvaluatorCostError(
                    f"symbols must be non-empty strings, got {symbol!r}"
                )
        if list(self.symbols) != sorted(set(self.symbols)):
            raise EvaluatorCostError(
                "symbols must arrive sorted and de-duplicated; the ask names "
                "the cross-section once"
            )
        if (
            not isinstance(self.date_range, tuple)
            or len(self.date_range) != 2
            or not all(
                isinstance(day, dt.date) and not isinstance(day, dt.datetime)
                for day in self.date_range
            )
        ):
            raise EvaluatorCostError(
                "date_range must be a pair of calendar dates (first, last) — "
                f"the span the gross returns live inside — got "
                f"{self.date_range!r}"
            )
        if self.date_range[0] > self.date_range[1]:
            raise EvaluatorCostError(
                f"date_range must run first-to-last, got {self.date_range!r}"
            )
        if not isinstance(self.gross_returns, Mapping):
            raise EvaluatorCostError(
                "gross_returns must map rebalance date to {symbol: forward "
                "return}, got "
                f"{type(self.gross_returns).__name__}"
            )
        captured: dict[dt.date, Mapping[str, float]] = {}
        symbol_set = set(self.symbols)
        covered_symbols: set[str] = set()
        for key, row in self.gross_returns.items():
            day = _as_charge_date(key)
            if day in captured:
                raise EvaluatorCostError(
                    f"gross_returns carries {day.isoformat()} twice under "
                    "different spellings; one bar, one series"
                )
            inner = _validated_row(row, day, label="gross return")
            if not inner:
                raise EvaluatorCostError(
                    f"gross_returns carries {day.isoformat()} with no "
                    "symbols; a covered date has a cross-section to charge"
                )
            extra = set(inner) - symbol_set
            if extra:
                raise EvaluatorCostError(
                    f"gross_returns carries {day.isoformat()} for "
                    f"{', '.join(sorted(inner))}, including "
                    f"{', '.join(sorted(extra))}, which the request's "
                    f"cross-section ({', '.join(self.symbols)}) does not "
                    "name; the ask and the returns it asks about must name "
                    "the same support"
                )
            covered_symbols.update(inner)
            captured[day] = inner
        if not captured:
            raise EvaluatorCostError(
                "gross_returns is empty; a covered horizon has returns to "
                "charge, and a request carrying none asks a fee schedule "
                "about nothing"
            )
        if covered_symbols != symbol_set:
            missing = sorted(symbol_set - covered_symbols)
            raise EvaluatorCostError(
                f"the request names {', '.join(self.symbols)} as its "
                f"cross-section, but {', '.join(missing)} appear(s) on no "
                "date in gross_returns; the ask and the returns it asks "
                "about must name the same support"
            )
        dates = tuple(sorted(captured))
        if self.date_range != (dates[0], dates[-1]):
            raise EvaluatorCostError(
                f"date_range is {self.date_range!r} but the gross returns "
                f"span {(dates[0], dates[-1])!r}; the request restates the "
                "support of the series it carries, and a range that disagrees "
                "with its own data is a producer that drifted"
            )
        object.__setattr__(
            self, "gross_returns", MappingProxyType(captured)
        )

    def __hash__(self) -> int:
        # The mapping is not hashable until it collapses to tuples, and the
        # fold keeps __hash__ consistent with __eq__, as the gate's records
        # do.
        return hash(
            (
                self.node_id,
                self.venue,
                self.version,
                self.horizon,
                self.symbols,
                self.date_range,
                tuple(
                    (day, tuple(sorted(row.items())))
                    for day, row in sorted(self.gross_returns.items())
                ),
            )
        )


@dataclass(frozen=True)
class CostQuote:
    """What the shared cost library answers — the charge, per symbol per bar.

    ``{costs: {rebalance date: {symbol: charge}}}``, under the identity of
    the schedule that produced it.  The charge is a deduction *in the same
    units as a simple return* — a fee of 10 bps is ``0.001`` — because the
    subtraction at this step is arithmetic on simple returns: the alignment
    computes ``close[d+h] / close[d] − 1`` and the module docstring of
    ``_align`` pins the simple form precisely so that costs, which are
    arithmetic, subtract cleanly from it.

    Validated at construction because the quote is the seam's payload:
    whatever the deployment's wiring deserializes, a payload that is not a
    well-formed charge series is refused here, before the harder question of
    whether it is a charge for *this* evaluation is asked.  As with §7.2's
    answer, the *shape* is checked here and the *support* is checked by the
    caller — a quote may legitimately be narrower than what was asked, and
    :func:`apply_costs` is where that becomes a refusal with a message
    naming the gap.
    """

    #: The venue of the schedule that produced these charges.
    venue: str
    #: The version of the schedule that produced these charges.
    version: str
    #: The charges, as ``{rebalance date: {symbol: charge}}`` — keyed at
    #: construction by calendar date or ISO string (the wire spelling) and
    #: normalized to dates on capture, every value a finite number.
    costs: Mapping[dt.date, Mapping[str, float]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _as_component(self.venue, "venue"))
        object.__setattr__(
            self, "version", _as_component(self.version, "version")
        )
        if not isinstance(self.costs, Mapping):
            raise EvaluatorCostError(
                "the quote's costs must map rebalance date to {symbol: "
                "charge}, got "
                f"{type(self.costs).__name__}"
            )
        captured: dict[dt.date, Mapping[str, float]] = {}
        for key, row in self.costs.items():
            day = _as_charge_date(key)
            if day in captured:
                raise EvaluatorCostError(
                    f"the quote's costs carry {day.isoformat()} twice under "
                    "different spellings; one bar, one charge"
                )
            captured[day] = _validated_row(row, day, label="charge")
        if not captured:
            raise EvaluatorCostError(
                "the quote carries no charges at all; a schedule asked to "
                f"price a horizon answers for it — see the {COST_STEP} step, "
                "which refuses a missing quote rather than pricing it at zero"
            )
        object.__setattr__(self, "costs", MappingProxyType(captured))

    def ref(self) -> CostModelRef:
        """The cost model these charges were priced under."""
        return CostModelRef(venue=self.venue, version=self.version)

    def __hash__(self) -> int:
        # Same fold as CostRequest, for the same reason.
        return hash(
            (
                self.venue,
                self.version,
                tuple(
                    (day, tuple(sorted(row.items())))
                    for day, row in sorted(self.costs.items())
                ),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"CostQuote({self.venue}/{self.version}, "
            f"{len(self.costs)} dates)"
        )


# -- Step 7's result -----------------------------------------------------------


@dataclass(frozen=True)
class PostCostSeries:
    """One horizon's post-cost returns — what the signal earned net of fees.

    The unit the feature's clause names ("a post-cost signal return series
    per symbol"), for the horizon :attr:`horizon`: at every rebalance date
    the gate answered for, the per-symbol ``gross − charge`` (in
    :attr:`values`) beside the charge that was deducted (in
    :attr:`charges`).

    Both halves are carried, and the second is not redundancy.  A series
    storing only the net cannot answer the first question anyone asks of a
    cost-adjusted number — *how much did the fee schedule eat?* — without
    re-running the schedule, and re-running it later is precisely the thing
    §6.2's shared library and feature 60's hash exist to make *unnecessary*
    rather than merely possible: the assumption being re-evaluated may have
    moved.  Keeping the deduction on the record makes the persisted row
    self-explaining, and makes "the schedule was applied" a fact about
    stored data rather than a claim about a code path.

    The invariants are checked at construction, so a record built by hand —
    or by a later feature whose producer drifted — fails loudly rather than
    carrying a lying series: the horizon is one of :data:`HORIZONS`, the
    snapshot and schedule names are non-empty, every value is a finite
    float, the two mappings live on exactly the same support, and both are
    captured behind read-only proxies.

    Absence stays structural here, as it does one step earlier: a date this
    horizon does not cover simply has no key, and there is never a zero
    charge standing in for a charge nobody quoted — :func:`apply_costs`
    refuses that case outright.
    """

    #: The horizon these returns measure, in periods (bars) — one of
    #: :data:`HORIZONS`.
    horizon: int

    #: The canonical name of the sealed snapshot the charged returns belong
    #: to — carried through from the gate, so a post-cost series can say
    #: which sealed world it was measured in as well as which schedule it
    #: was priced under.
    snapshot_name: str

    #: The venue of the cost model these returns were netted against.
    venue: str

    #: The version of that cost model.
    version: str

    #: The post-cost returns, as ``{rebalance date: {symbol: gross − charge}}``.
    values: Mapping[dt.date, Mapping[str, float]]

    #: The charges deducted, as ``{rebalance date: {symbol: charge}}`` — the
    #: same support as :attr:`values`, and the reason each net differs from
    #: the gross the gate supplied.
    charges: Mapping[dt.date, Mapping[str, float]]

    def __post_init__(self) -> None:
        # object.__setattr__ throughout: frozen dataclass, and these are
        # normalizations of arguments the constructor accepted.
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise EvaluatorCostError(
                f"a post-cost series' horizon must be an integer period "
                f"count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise EvaluatorCostError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}); the set is "
                "closed — feature 75 pins it and step 7 charges each of them"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorCostError(
                "a post-cost series must name the sealed snapshot its returns "
                f"were measured in, got {self.snapshot_name!r}"
            )
        object.__setattr__(self, "venue", _as_component(self.venue, "venue"))
        object.__setattr__(
            self, "version", _as_component(self.version, "version")
        )
        captured: dict[dt.date, Mapping[str, float]] = {}
        charged: dict[dt.date, Mapping[str, float]] = {}
        for field, label, target in (
            (self.values, "post-cost return", captured),
            (self.charges, "charge", charged),
        ):
            if not isinstance(field, Mapping):
                raise EvaluatorCostError(
                    f"a post-cost series' {label}s must map rebalance date to "
                    f"{{symbol: number}}, got {type(field).__name__}"
                )
            for day, row in field.items():
                if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                    raise EvaluatorCostError(
                        f"{label} dates must be calendar dates, got {day!r}"
                    )
                if day in target:
                    raise EvaluatorCostError(
                        f"the {label}s carry {day.isoformat()} twice under "
                        "different spellings; one bar, one number"
                    )
                target[day] = _validated_row(row, day, label=label)
        if set(captured) != set(charged):
            missing = sorted(set(captured) - set(charged))
            extra = sorted(set(charged) - set(captured))
            raise EvaluatorCostError(
                "a post-cost series carries its returns and its charges on "
                "the same support"
                + (
                    f" — no charge for "
                    f"{', '.join(day.isoformat() for day in missing)}"
                    if missing
                    else ""
                )
                + (
                    f" — a charge for "
                    f"{', '.join(day.isoformat() for day in extra)}, which "
                    "carries no return"
                    if extra
                    else ""
                )
            )
        for day, row in captured.items():
            if set(row) != set(charged[day]):
                raise EvaluatorCostError(
                    f"the returns for {day.isoformat()} cover "
                    f"{', '.join(sorted(row)) or 'no symbols'} but the "
                    f"charges cover "
                    f"{', '.join(sorted(charged[day])) or 'no symbols'}; a "
                    "charge nobody's return was netted against is a cost the "
                    "series does not explain"
                )
        object.__setattr__(self, "values", MappingProxyType(captured))
        object.__setattr__(self, "charges", MappingProxyType(charged))

    def dates(self) -> Tuple[dt.date, ...]:
        """The rebalance dates this horizon has post-cost returns for.

        Exactly the dates the gate answered on for this horizon — step 7
        charges every return it was given and invents none — so the decay
        profile and the IC series one step on measure over the same span as
        the gross series they net out.
        """
        return tuple(sorted(self.values))

    def at(self, rebalance_date: dt.date) -> Mapping[str, float]:
        """One date's post-cost returns, as ``{symbol: net return}``.

        Empty for a date this horizon does not cover — the miss reported as
        nothing, on the same principle as the alignment's own accessor: an
        empty answer cannot leak a return the series excluded, where a
        nearest-date fallback silently would.
        """
        return self.values.get(rebalance_date, MappingProxyType({}))

    def charge_at(self, rebalance_date: dt.date) -> Mapping[str, float]:
        """One date's charges, as ``{symbol: deduction}`` — empty on a miss.

        The companion to :meth:`at`, over the same support: for every symbol
        the post-cost return covers, this is what was taken off it.
        """
        return self.charges.get(rebalance_date, MappingProxyType({}))

    def __hash__(self) -> int:
        # Hashable because the record is a value: two applications of the
        # same schedule over the same bundle must be interchangeable as dict
        # keys.  The mappings fold into nested tuples, which also keeps
        # __hash__ consistent with __eq__.
        return hash(
            (
                self.horizon,
                self.snapshot_name,
                self.venue,
                self.version,
                tuple(
                    (day, tuple(sorted(row.items())))
                    for day, row in sorted(self.values.items())
                ),
                tuple(
                    (day, tuple(sorted(row.items())))
                    for day, row in sorted(self.charges.items())
                ),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"PostCostSeries(horizon={self.horizon}, "
            f"snapshot={self.snapshot_name!r}, "
            f"{self.venue}/{self.version}, {len(self.values)} dates)"
        )


@dataclass(frozen=True)
class PostCostReturns:
    """Step 7's whole result — the post-cost series, one per horizon.

    The five-horizon bundle the metrics are computed over (features 80 on):
    the node whose signal was charged, the sealed world it was measured in,
    the rebalance grid it was scored on, the cost model every series was
    priced under, and the series themselves keyed by horizon.

    Always one series for *every* horizon in :data:`HORIZONS` — a horizon
    with nothing aligned is carried empty, keeping feature 75's shape
    promise — and always stamped with one snapshot and one cost model, in
    the same sense :class:`~evaluator.GatedTargets` is stamped with one
    snapshot: a bundle whose series disagreed about which schedule priced
    them would be a provenance fault no downstream hash could catch, and
    §15's failure table treats a changed cost model as its own case rather
    than as noise.

    Carrying :attr:`node_id` is what makes the bundle addressable: §9.2's
    artifact directory is ``<campaign_id>/<node_id>/``, and this value is
    the record that lands there.

    §7.2's opaque budget directive is carried forward untouched, exactly as
    the gate carries it: parameterized on, never read.  Step 7 has no use
    for it, but dropping it here would lose the bit for every step after —
    features 80, 83 and 84 receive *this* record, and feature 84's trial
    charge is precisely the write that happens when an evaluation went
    wrong, so "the later step can ask the gate again" is not available.
    """

    #: The node whose signal these returns belong to.
    node_id: str
    #: The canonical name of the sealed snapshot the gated returns were
    #: measured in.
    snapshot_name: str
    #: The rebalance dates the evaluation was scored on, ascending — what
    #: was scored, restated by the series that net the costs out of it.
    rebalance_dates: Tuple[dt.date, ...]
    #: The cost model every series was priced under.
    cost_model: CostModelRef
    #: The five post-cost series, as ``{horizon: PostCostSeries}`` — always
    #: one per horizon in :data:`HORIZONS`, a horizon with nothing aligned
    #: carried as an empty series.
    series: Mapping[int, PostCostSeries]
    #: §7.2's opaque budget directive, carried through untouched — the same
    #: bit :class:`~evaluator.GatedTargets` carries, forwarded so it is still
    #: reachable from step 7's result.  Interpreted nowhere here, for the
    #: reason §7.4 names: an evaluator that could read *why* the flag was set
    #: would learn ``is_null``, and the whole point of crossing the barrier as
    #: a directive rather than a label is that it cannot.  It is carried
    #: rather than dropped because the steps that consume it receive *this*
    #: record, not the gate's — feature 84's trial charge is written even
    #: when the evaluation failed, so a bit lost at step 7 is a bit no later
    #: step can recover.  Required, with no default: §8 stores ``FALSE`` for
    #: a null node, so a default would let a producer that forgot the bit
    #: declare an ordinary node null and quietly stop debiting statistical
    #: budget — an under-charge in the one direction §7.4 audits.
    charges_budget: bool

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise EvaluatorCostError(
                "post-cost returns must name the node whose signal they "
                f"belong to, got {self.node_id!r}"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorCostError(
                "post-cost returns must name the sealed snapshot their "
                f"returns were measured in, got {self.snapshot_name!r}"
            )
        if not isinstance(self.rebalance_dates, tuple):
            raise EvaluatorCostError(
                "rebalance_dates must be a tuple of dates, got "
                f"{type(self.rebalance_dates).__name__}"
            )
        for day in self.rebalance_dates:
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorCostError(
                    f"rebalance dates must be calendar dates, got {day!r}"
                )
        if list(self.rebalance_dates) != sorted(set(self.rebalance_dates)):
            raise EvaluatorCostError(
                "rebalance_dates must arrive sorted and de-duplicated; the "
                "producer that emitted them drifted"
            )
        if not isinstance(self.cost_model, CostModelRef):
            raise EvaluatorCostError(
                "post-cost returns must name the cost model their series were "
                f"priced under, got {type(self.cost_model).__name__}; pass a "
                "CostModelRef (or coerce one with cost_model_ref())"
            )
        if not isinstance(self.series, Mapping):
            raise EvaluatorCostError(
                "series must map horizon to PostCostSeries, got "
                f"{type(self.series).__name__}"
            )
        carried = tuple(sorted(self.series))
        if carried != HORIZONS:
            raise EvaluatorCostError(
                "post-cost returns carry one series per horizon the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}), got "
                f"{', '.join(str(h) for h in carried) or 'none'}"
            )
        for horizon, series in self.series.items():
            if series.horizon != horizon:
                raise EvaluatorCostError(
                    f"the series filed under horizon {horizon} carries "
                    f"horizon {series.horizon}; a series filed under the "
                    "wrong horizon is a pairing every downstream metric would "
                    "trust and be wrong by"
                )
            if series.snapshot_name != self.snapshot_name:
                raise EvaluatorCostError(
                    f"the horizon-{horizon} series names snapshot "
                    f"{series.snapshot_name!r} but the bundle names "
                    f"{self.snapshot_name!r}; one evaluation reads one "
                    "sealed world"
                )
            if (series.venue, series.version) != (
                self.cost_model.venue,
                self.cost_model.version,
            ):
                raise EvaluatorCostError(
                    f"the horizon-{horizon} series was priced under "
                    f"{series.venue}/{series.version} but the bundle names "
                    f"{self.cost_model.reference}; one evaluation prices one "
                    "fee schedule — a bundle whose series disagree about "
                    "their cost model is a provenance fault §15's failure "
                    "table has no way to catch downstream"
                )
        if not isinstance(self.charges_budget, bool):
            raise EvaluatorCostError(
                "charges_budget must be a bool — §7.2's opaque directive, the "
                f"only bit that crosses the barrier — got "
                f"{self.charges_budget!r} ({type(self.charges_budget).__name__}); "
                "a bit is not an int that happens to be 0 or 1"
            )
        object.__setattr__(
            self, "series", MappingProxyType(dict(self.series))
        )

    @property
    def horizons(self) -> Tuple[int, ...]:
        """The horizons carried, ascending — always :data:`HORIZONS`."""
        return HORIZONS

    @property
    def cost_model_reference(self) -> str:
        """The pricing schedule as one string — ``"<venue>/<version>"``."""
        return self.cost_model.reference

    def costed(self, horizon: int) -> PostCostSeries:
        """One horizon's post-cost series.

        Refused for a horizon outside :data:`HORIZONS` — the set is closed,
        on the same terms as the alignment's and the gate's own accessors,
        which this bundle mirrors.
        """
        if horizon not in self.series:
            raise EvaluatorCostError(
                f"horizon {horizon} is not one of the horizons this bundle "
                f"carries ({', '.join(str(h) for h in HORIZONS)}); the decay "
                "profile and the IC series ask per horizon, and the set is "
                "the spec's, not the caller's to widen"
            )
        return self.series[horizon]

    def returns(self, horizon: int) -> Mapping[dt.date, Mapping[str, float]]:
        """One horizon's post-cost returns — the ``{date: {symbol: net}}``."""
        return self.costed(horizon).values

    def charges(self, horizon: int) -> Mapping[dt.date, Mapping[str, float]]:
        """One horizon's charges — the ``{date: {symbol: deduction}}``."""
        return self.costed(horizon).charges

    def __hash__(self) -> int:
        # Same fold as the gate's bundle, for the same reason: the record is
        # a value, and the mapping is not hashable until it collapses to
        # tuples.
        return hash(
            (
                self.node_id,
                self.snapshot_name,
                self.rebalance_dates,
                self.cost_model,
                self.charges_budget,
                tuple(sorted(self.series.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"PostCostReturns(node={self.node_id!r}, "
            f"snapshot={self.snapshot_name!r}, "
            f"{self.cost_model.reference}, "
            f"{len(self.rebalance_dates)} rebalance dates)"
        )


# -- The one spelling of the support rule --------------------------------------


def _check_charge_support(quote: CostQuote, request: CostRequest) -> None:
    """Refuse a quote that does not live on the charged support.

    Step 7 charges every return the gate supplied, so a horizon's charges
    must cover exactly the dates that horizon's gross series covers, and
    exactly the symbols on each of them.  Anything else did not come out of
    a schedule being asked about *this* evaluation.  The two directions are
    not the same fault and are refused with different messages:

    * a date or symbol the gross series does not back is a charge for a
      trade nobody made — a fee schedule answering for another evaluation's
      cross-section, or a stale quote replayed into this one;
    * a date or symbol the gross series backs and the quote *omits* is a
      free ride.  The tempting repair — price the missing bar at zero —
      would understate cost in the one direction the whole method cares
      about, and would do it silently, inside the artifact replay reads
      back.  Absence is not zero: a fee the schedule did not quote is a
      hole in the schedule, and it is named rather than filled.
    """
    quoted_days = set(quote.costs)
    asked_days = set(request.gross_returns)
    if quoted_days != asked_days:
        parts: list[str] = []
        missing = sorted(asked_days - quoted_days)
        if missing:
            parts.append(
                f"no charge for "
                f"{', '.join(day.isoformat() for day in missing)} — the fee "
                "schedule did not quote it, and a missing charge is not a "
                "free trade"
            )
        extra = sorted(quoted_days - asked_days)
        if extra:
            parts.append(
                f"a charge for "
                f"{', '.join(day.isoformat() for day in extra)}, which this "
                "evaluation scored no returns on"
            )
        raise EvaluatorCostError(
            f"the quote for horizon {request.horizon} does not live on the "
            f"returns it was asked to price — {'; '.join(parts)}; step 7 "
            f"charges the support the {COST_STEP} step was given, no wider "
            "and no narrower"
        )
    for day in sorted(asked_days):
        quoted_symbols = set(quote.costs[day])
        asked_symbols = set(request.gross_returns[day])
        if quoted_symbols != asked_symbols:
            missing = sorted(asked_symbols - quoted_symbols)
            extra = sorted(quoted_symbols - asked_symbols)
            raise EvaluatorCostError(
                f"the quote for horizon {request.horizon} prices "
                f"{day.isoformat()} for "
                f"{', '.join(sorted(quoted_symbols)) or 'no symbols'}, but "
                f"that bar's cross-section is "
                f"{', '.join(sorted(asked_symbols))}"
                + (f" — missing {', '.join(missing)}" if missing else "")
                + (
                    f" — charging {', '.join(extra)}, whom nobody scored"
                    if extra
                    else ""
                )
                + "; a missing charge is not a free trade and a charge for an "
                "unscored symbol is a fee for nobody — the schedule answers "
                "for the cross-section it was asked about"
            )


# -- The application -----------------------------------------------------------


def apply_costs(
    gated: GatedTargets,
    charges: CostSchedule,
    *,
    node_id: str,
    cost_model: object,
) -> PostCostReturns:
    """Charge the cost model against step 5's returns — pipeline step 7.

    For every horizon in :data:`HORIZONS` that the ``gated`` bundle covers,
    build :class:`CostRequest` from that horizon's own series — the node
    identity, the ``(venue, version)`` the caller's ``cost_model`` resolves
    to, the horizon, the cross-section the series carries, the series' own
    span, and the gross returns themselves — and ask the injected
    ``charges`` schedule.  The quote is validated as a payload (by
    :class:`CostQuote`'s constructor) and then as a *pricing*: it must name
    the same cost model, and it must live on exactly the charged support,
    per date and per symbol.  Each return is then netted —
    ``post_cost = gross − charge`` — and the result is a
    :class:`PostCostReturns` carrying the post-cost series beside the
    charges that produced it.  A horizon with nothing aligned is not asked
    and is carried as an empty series.

    The ``charges`` schedule is the shared cost library of §6.2 and feature
    69, arriving as a callable taking a :class:`CostRequest` and returning a
    :class:`CostQuote` — the same injected-seam shape feature 73's
    ``materialize`` and feature 76's oracle use.  This function computes no
    fee arithmetic of its own: a fee schedule implemented here would be the
    second implementation feature 69 refuses, and divergence between
    research and live execution is exactly the quantity ``β₄`` penalizes.
    A schedule that raises propagates — its failures are its own, and
    dressing them as cost errors would hide the seam.

    Nothing is persisted here; :func:`evaluator.persist_signal_returns`
    (or :class:`~evaluator.PostCostStore`) writes the series down, the same
    split features 70's ``_identity`` and ``_store`` use.  And the gate's
    *supply* is not re-certified: this function checks that the bundle is a
    :class:`~evaluator.GatedTargets`, not that it is the gate's own answer
    over a particular alignment — that certification is feature 76's
    :func:`~evaluator.check_targets_gated`, and a consumer that needs it
    asks for it.

    Raises :class:`~evaluator.EvaluatorCostError`, each with its reason (see
    ``_errors``): a ``gated`` that is not step 5's own result; a ``charges``
    that is not callable; a ``node_id`` that is not a name or a
    ``cost_model`` that does not resolve to a ``(venue, version)`` pair; a
    bundle with no computable target at any horizon (nothing to charge, so
    no post-cost series exists to persist); a quote that is not a
    ``CostQuote``, that names a different cost model, or that does not live
    on the charged support.
    """
    if not isinstance(gated, GatedTargets):
        raise EvaluatorCostError(
            "apply_costs charges step 5's own result — a GatedTargets, the "
            "target series the null gate supplied — got "
            f"{type(gated).__name__}; costs are applied to the world the "
            "evaluation is actually measured in, so the alignment alone is "
            "not enough and a raw mapping is less"
        )
    if not callable(charges):
        raise EvaluatorCostError(
            "the cost schedule must be a callable taking a CostRequest and "
            "returning a CostQuote — §6.2's shared cost library, injected, "
            f"never reached for — got {type(charges).__name__}"
        )
    if not isinstance(node_id, str) or not node_id.strip():
        raise EvaluatorCostError(
            "node_id must be a non-empty string — the evaluation whose "
            f"returns are being charged — got {node_id!r}"
        )
    model = cost_model_ref(cost_model)

    covered = [
        horizon for horizon in HORIZONS if gated.targets(horizon).dates()
    ]
    if not covered:
        raise EvaluatorCostError(
            "the gated bundle carries no computable target at any horizon, "
            "so there is no return to net a cost out of and no post-cost "
            "series to persist — five empty series would report a costed "
            "evaluation for one that measured nothing; gate an alignment "
            "with coverage first (features 75 and 76)"
        )

    series: dict[int, PostCostSeries] = {}
    for horizon in HORIZONS:
        supplied: TargetSeries = gated.targets(horizon)
        dates = supplied.dates()
        if not dates:
            # Nothing supplied, nothing charged: carried as the empty series
            # the bundle's shape promise requires (feature 75's five-horizon
            # rule), stamped with the evaluation's own provenance.
            series[horizon] = PostCostSeries(
                horizon=horizon,
                snapshot_name=gated.snapshot_name,
                venue=model.venue,
                version=model.version,
                values=MappingProxyType({}),
                charges=MappingProxyType({}),
            )
            continue
        symbols = tuple(
            sorted({symbol for day in dates for symbol in supplied.at(day)})
        )
        request = CostRequest(
            node_id=node_id,
            venue=model.venue,
            version=model.version,
            horizon=horizon,
            symbols=symbols,
            date_range=(dates[0], dates[-1]),
            gross_returns=MappingProxyType(
                {day: supplied.at(day) for day in dates}
            ),
        )
        quote = charges(request)
        if not isinstance(quote, CostQuote):
            raise EvaluatorCostError(
                "the cost schedule must return a CostQuote — the charges for "
                "the horizon it was asked about, under the identity of the "
                f"schedule that priced them — got {type(quote).__name__}; "
                "the seam's payload is validated at the record, and anything "
                "else is not an answer"
            )
        if quote.ref() != model:
            raise EvaluatorCostError(
                f"the cost schedule answered under "
                f"{quote.ref().reference} but this evaluation names "
                f"{model.reference}; step 7 charges one evaluation against "
                "one cost model, and applying another schedule's charges "
                "would file these returns under one cost model's provenance "
                "while computing them with another's — §15 treats a changed "
                "cost model as its own failure, not as noise"
            )
        _check_charge_support(quote, request)
        values = {
            day: {
                symbol: request.gross_returns[day][symbol]
                - quote.costs[day][symbol]
                for symbol in request.gross_returns[day]
            }
            for day in dates
        }
        series[horizon] = PostCostSeries(
            horizon=horizon,
            snapshot_name=gated.snapshot_name,
            venue=model.venue,
            version=model.version,
            values=MappingProxyType(
                {day: MappingProxyType(row) for day, row in values.items()}
            ),
            charges=MappingProxyType(
                {day: quote.costs[day] for day in dates}
            ),
        )

    return PostCostReturns(
        node_id=node_id,
        snapshot_name=gated.snapshot_name,
        rebalance_dates=gated.rebalance_dates,
        cost_model=model,
        series=MappingProxyType(series),
        charges_budget=gated.charges_budget,
    )
