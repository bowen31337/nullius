"""Aligning forward returns to the score grid — pipeline step 4.

app_spec.xml feature 75: *"System aligns forward returns at horizons of 1, 2,
5, 10 and 20 periods, which returns one target series per horizon."*
docs/nullius-tech-architecture.md §6.1 names the step — ``4. align_targets
fetch forward returns at horizons h ∈ {1,2,5,10,20}`` — and the features
around it pin what the result is *for*: the null gate substitutes it (feature
76, "the only place the oracle supplies a target series"), costs apply to it
(feature 79, "the aligned returns"), and the decay profile measures
information coefficient at each of *the five horizons* (feature 81) — so what
this module returns is the label every downstream metric is computed against.

The feature sentence has three phrases, and each is a decision this module
enforces rather than a choice it offers:

*at horizons of 1, 2, 5, 10 and 20 periods*
    The set is closed, and it is spelled once: :data:`HORIZONS`. There is no
    ``horizons=`` parameter, because the five horizons are not a
    configuration — feature 81 measures "at each of the five horizons",
    feature 76's oracle is asked per horizon, and a caller who could widen
    the set would produce a decay profile whose x-axis the spec does not
    define. A "period" is one bar on the market grid — the sorted union of
    the bar dates the closes name — not one calendar day: the market's clock
    is its candles (weekends and holidays have no bars), so horizon 5 means
    *five bars forward*, and the same sealed data resolves the same grid on
    any machine, any day (the determinism contract §12). Stepping on the
    *market* grid rather than each symbol's own keeps a horizon meaning the
    same thing for every symbol: a decay profile comparing IC at horizon 5
    across symbols is only a decay profile if "5" names the same span for
    each of them.

*forward returns*
    The label for a decision at rebalance date ``d`` is the simple return
    from the close on ``d`` to the close ``h`` grid steps later —
    ``close[d+h] / close[d] − 1`` — computed per symbol. Two conventions are
    pinned here. The entry is the rebalance date's own close (not the prior
    day's, not the next open): a target is a *label*, not an executable
    P&L — the fill and fee model that turns a label into a return an
    account would have earned is step 7 (feature 79) — and the close-to-close
    forward return is the one spelling every downstream consumer (rank IC,
    post-cost series, decay) is defined over. The return is the simple
    (arithmetic) form, because the costs applied to it at step 7 are
    arithmetic (a fee of *k* bps subtracts from a simple return, not from a
    log one), and rank IC — the other consumer — is invariant to the
    monotone transform anyway.

    Future data enters the pipeline *here*, and only here on this path: a
    target is future data by definition, which is exactly why it is aligned
    host-side, *after* the sandbox has run, keyed by the decision dates the
    signal already scored. Principle P4's guarantee — the sandbox receives
    "a pre-sliced, materialized array containing only data at or before
    ``t``" — is about what the *signal* can see, and nothing this module
    returns is ever handed back to one: the series goes forward to the null
    gate and the metrics, never backward to the execution. Feeding a target
    to a signal is the look-ahead this architecture makes physically
    impossible by construction, not by policy.

*one target series per horizon*
    The output carries exactly five :class:`TargetSeries` — one per horizon
    in :data:`HORIZONS`, always, including a horizon whose coverage is empty
    — each mapping rebalance date to the per-symbol forward returns that
    date's cross-section has targets for. A target that cannot be computed
    is **absent**, never zero-filled and never NaN: a symbol with no bar on
    the exit date (a data gap, or the symbol was delisted inside the
    horizon) is missing from that date's inner mapping, and a rebalance
    date whose ``h``-period future does not exist in the sealed closes —
    the grid runs off the end — is missing from that horizon's series. This
    is why the shorter horizons cover more dates than the longer ones, and
    it is the honest alignment: the decay profile at horizon 20 is computed
    over the dates horizon 20 can speak for, not over a grid padded with
    zeros that would read to every metric as "the signal predicted
    nothing". Zero is a measurement; absence is the absence of one.

**What the alignment is aligned *to*.** The grid and the cross-section are
the execution's — :func:`evaluator.execute_signal`'s :class:`SignalExecution`
— because "aligned" names the pairing that makes an information coefficient
meaningful: a score at date ``d`` for the symbols of ``d``'s universe,
against a target at date ``d`` for those same symbols. Two coherence rules
follow, each refused rather than smoothed over:

* *the entry close must exist.* Feature 72's universe rule admits a symbol
  on a day its sealed bars carry a partition on that very date, so every
  symbol a vector scored *must* have a close on its rebalance date. A
  fetch that omits one is not a narrower alignment; it is a bug in the
  read the alignment refuses to paper over (see :func:`align_targets`).
* *the closes of unscored symbols are ignored.* The market grid is derived
  from the closes of the symbols the execution scored, so the same
  execution plus the same closes for those symbols produces the same
  targets however broad the fetch was — a whole-market fetch and a
  scored-universe fetch align identically, which is the reproducibility
  the determinism contract asks for.

**The coverage refusal.** An alignment with no computable target at *any*
horizon is refused, not returned empty: the closes the caller handed in
carry no bar after any rebalance date, so the fetch that was supposed to
supply the forward half of the label supplied none of it, and five empty
series would report "aligned" to a caller whose evaluation has nothing to
measure. Per-horizon emptiness is *not* refused — a short evaluation
window legitimately leaves horizons 5, 10 and 20 with no dates, and
features 77 and 78 (purge and embargo) exist precisely because short
grids are a case the pipeline plans for — only the alignment that
produced nothing at all is.

**What this module does not do.** It does not fetch — the closes arrive as
a value, read from the sealed snapshot by the caller host-side (the same
seam feature 73's ``materialize`` opens: the lake read is injected, never
reached for). It does not substitute (feature 76's null gate is the only
place an oracle supplies a target series), purge or embargo (features 77
and 78), apply costs (feature 79), or compute any metric (features 80 on).
It takes an execution and its closes and answers exactly the one question
step 4 puts in scope: *what is the h-period forward return, for every
horizon the spec names, at every date the signal scored?*

**The layering note.** This module is stdlib-only — no polars, no
pyarrow, no lake, no environment. The values in and out are plain floats
in plain mappings, because a target series is keyed data, not a frame:
the frame materialization happened two steps ago (feature 73's payload),
and the consumer of a target is a join on ``(date, symbol)``, which a
mapping states directly. Importing this member therefore costs composition
— and the replay path §1 forbids from reaching the evaluator — nothing at
all, which is the cheapest import in this package so far.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Tuple, Union

from ._errors import EvaluatorAlignmentError
from ._execute import SignalExecution

__all__ = [
    "HORIZONS",
    "AlignedTargets",
    "TargetSeries",
    "align_targets",
]

#: The horizons the spec names, ascending — the closed set feature 75 pins.
#:
#: ``app_spec.xml`` feature 75 spells them ("horizons of 1, 2, 5, 10 and 20
#: periods"), §6.1 step 4 spells them again (``h ∈ {1,2,5,10,20}``), and
#: feature 81 leans on the count ("each of the five horizons").  Exposed as a
#: value rather than kept private because the closed set is shared vocabulary:
#: the null gate asks per horizon, the decay profile iterates all five, and a
#: caller validating a stored profile's axis reads the same tuple this module
#: aligned over.  Deliberately *not* a parameter of :func:`align_targets` —
#: the five horizons are the spec's, not a caller's to widen.
HORIZONS: Tuple[int, ...] = (1, 2, 5, 10, 20)


# -- The closes, accepted and validated ---------------------------------------


def _close_date(symbol: str, key: Any) -> dt.date:
    """Coerce one close-series key to a calendar :class:`datetime.date`.

    Accepted spellings: a ``date``, or an ISO string naming one — the same
    courtesy ``_window._as_utc`` extends the decision time.  A ``datetime``
    is refused (it names an instant, and the alignment is day-granular: the
    bars are daily candles, the rebalance grid is dates, and silently
    truncating an instant to its day would be a guess about which candle
    the caller meant), and anything else is refused by name.
    """
    if isinstance(key, dt.datetime):
        raise EvaluatorAlignmentError(
            f"closes for {symbol!r} are keyed by a datetime ({key!r}); the "
            "alignment is day-granular — key by the calendar date (or its "
            "ISO string), the day the candle belongs to"
        )
    if isinstance(key, dt.date):
        return key
    if isinstance(key, str):
        try:
            return dt.date.fromisoformat(key)
        except ValueError as exc:
            raise EvaluatorAlignmentError(
                f"close date {key!r} for {symbol!r} is not an ISO date; "
                "closes are keyed by calendar dates (or ISO date strings), "
                "one per bar"
            ) from exc
    raise EvaluatorAlignmentError(
        f"close dates for {symbol!r} must be dates or ISO date strings, got "
        f"{key!r} ({type(key).__name__})"
    )


def _close_price(symbol: str, day: dt.date, raw: Any) -> float:
    """One close price, as a finite positive float.

    Positive because a price is: the forward return divides by it, and a
    zero would divide by zero while a negative would flip the sign of every
    return measured off it — either poisons the label silently.  Finite
    because a NaN or ±inf target would reach the metrics dressed as a
    measurement.  A ``bool`` is refused even though Python calls it an
    ``int``: ``True`` is not a price, and the arithmetic would happily
    carry it.  Integers are accepted and normalized to float — cents are a
    legitimate fetch spelling.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise EvaluatorAlignmentError(
            f"close for {symbol!r} on {day.isoformat()} must be a number, "
            f"got {raw!r} ({type(raw).__name__})"
        )
    price = float(raw)
    if not math.isfinite(price):
        raise EvaluatorAlignmentError(
            f"close for {symbol!r} on {day.isoformat()} is not finite "
            f"({raw!r}); a NaN or ±inf price would poison every forward "
            "return measured off it"
        )
    if price <= 0.0:
        raise EvaluatorAlignmentError(
            f"close for {symbol!r} on {day.isoformat()} must be positive, "
            f"got {raw!r}; the forward return divides by the entry close, "
            "so a zero or negative price is not a price the label can be "
            "measured from"
        )
    return price


def _validated_closes(closes: Any) -> dict[str, dict[dt.date, float]]:
    """The whole fetch, validated once, as ``{symbol: {date: close}}``.

    Every price handed in is checked — including symbols the execution did
    not score — because the mapping is the fetch's whole content and a NaN
    anywhere in it is a broken read, not a symbol-scoped inconvenience; the
    *grid* then uses only the scored symbols (see :func:`align_targets`).
    Returns plain dicts: the input mapping is the caller's to keep, and the
    alignment works over its own normalized copy.
    """
    if not isinstance(closes, Mapping):
        raise EvaluatorAlignmentError(
            "closes must be a mapping of symbol to {date: close}, got "
            f"{type(closes).__name__} — the alignment reads the fetched "
            "closes as a value, not a callable or frame"
        )
    normalized: dict[str, dict[dt.date, float]] = {}
    for symbol, series in closes.items():
        if not isinstance(symbol, str) or not symbol:
            raise EvaluatorAlignmentError(
                f"close symbols must be non-empty strings, got {symbol!r}"
            )
        if not isinstance(series, Mapping):
            raise EvaluatorAlignmentError(
                f"closes for {symbol!r} must map date to close, got "
                f"{type(series).__name__}"
            )
        prices: dict[dt.date, float] = {}
        for key, raw in series.items():
            day = _close_date(symbol, key)
            if day in prices:
                raise EvaluatorAlignmentError(
                    f"closes for {symbol!r} carry {day.isoformat()} twice "
                    "under different spellings; one bar, one close"
                )
            prices[day] = _close_price(symbol, day, raw)
        normalized[symbol] = prices
    return normalized


# -- The records --------------------------------------------------------------


@dataclass(frozen=True)
class TargetSeries:
    """One horizon's forward returns — pure data, keyed by ``(date, symbol)``.

    The unit the feature's clause names ("one target series per horizon"):
    for the horizon :attr:`horizon`, the per-symbol forward return at every
    rebalance date whose ``h``-period future exists in the sealed closes.
    What a downstream step holds when it asks the null gate for a target
    series (feature 76) or measures IC at one horizon (feature 81) — a
    value that travels alone, so it carries its own horizon and its own
    snapshot name rather than borrowing them from a wrapper.

    The invariants are checked at construction, so a record built by hand —
    or by a later feature whose producer drifted — fails loudly rather than
    carrying a lying series: the horizon is one of :data:`HORIZONS`, the
    snapshot name is non-empty, every value is a finite float, and the
    mappings are captured behind read-only proxies (a caller keeping the
    dict it passed cannot add a target to a live series).

    Absence is structural, not spelled: a date with no targets for this
    horizon simply has no key, and a symbol missing its exit bar has no key
    in that date's mapping — the alignment never writes a zero or a NaN
    where a target could not be computed (see the module docstring).
    """

    #: The horizon this series measures, in periods (bars) — one of
    #: :data:`HORIZONS`.
    horizon: int

    #: The canonical name of the sealed snapshot the closes were read from.
    #: The closes arrive as a value with no provenance of their own, so the
    #: alignment stamps the execution's snapshot here: a target series must
    #: be able to say *which* sealed world its labels came from.
    snapshot_name: str

    #: The forward returns, as ``{rebalance date: {symbol: h-period forward
    #: return}}``.  Dates whose ``h``-period future does not exist in the
    #: closes, and symbols missing their exit bar, are absent.
    values: Mapping[dt.date, Mapping[str, float]]

    def __post_init__(self) -> None:
        # object.__setattr__ throughout: frozen dataclass, and these are
        # normalizations of arguments the constructor accepted.
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise EvaluatorAlignmentError(
                f"a target series' horizon must be an integer period count, "
                f"got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise EvaluatorAlignmentError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}); the set is "
                "closed — feature 75 pins it and feature 81 counts on it"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorAlignmentError(
                "a target series must name the sealed snapshot its closes "
                f"came from, got {self.snapshot_name!r}"
            )
        if not isinstance(self.values, Mapping):
            raise EvaluatorAlignmentError(
                "a target series' values must map rebalance date to "
                "{symbol: forward return}, got "
                f"{type(self.values).__name__}"
            )
        captured: dict[dt.date, Mapping[str, float]] = {}
        for day, row in self.values.items():
            if not isinstance(day, dt.date):
                raise EvaluatorAlignmentError(
                    f"target dates must be calendar dates, got {day!r}"
                )
            if not isinstance(row, Mapping):
                raise EvaluatorAlignmentError(
                    f"targets for {day.isoformat()} must map symbol to "
                    f"forward return, got {type(row).__name__}"
                )
            inner: dict[str, float] = {}
            for symbol, value in row.items():
                if not isinstance(symbol, str) or not symbol:
                    raise EvaluatorAlignmentError(
                        f"target symbols for {day.isoformat()} must be "
                        f"non-empty strings, got {symbol!r}"
                    )
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise EvaluatorAlignmentError(
                        f"the target for {symbol!r} on {day.isoformat()} must "
                        f"be a number, got {value!r}"
                    )
                target = float(value)
                if not math.isfinite(target):
                    raise EvaluatorAlignmentError(
                        f"the target for {symbol!r} on {day.isoformat()} is "
                        f"not finite ({value!r}); a NaN or ±inf label would "
                        "reach the metrics dressed as a measurement"
                    )
                inner[symbol] = target
            if inner:
                captured[day] = MappingProxyType(inner)
        object.__setattr__(self, "values", MappingProxyType(captured))

    def dates(self) -> Tuple[dt.date, ...]:
        """The rebalance dates this horizon has targets for, ascending.

        Shorter than the full rebalance grid by construction: the last
        ``horizon`` grid dates have no ``h``-period future, and the
        coverage shrinks as the horizon grows.  The decay profile at this
        horizon is computed over exactly these dates — the dates this
        horizon can speak for.
        """
        return tuple(sorted(self.values))

    def at(self, rebalance_date: dt.date) -> Mapping[str, float]:
        """One date's cross-sectional targets, as ``{symbol: return}``.

        Empty for a date this horizon does not cover — the miss reported as
        nothing, on the same principle as the contract's accessors: an
        empty answer cannot leak a target the alignment excluded, where a
        nearest-date fallback silently would.
        """
        return self.values.get(rebalance_date, MappingProxyType({}))

    def __hash__(self) -> int:
        # Hashable because the record is a value: two alignments of the same
        # execution over the same closes must be interchangeable as dict
        # keys.  The mappings are not hashable, so they fold into nested
        # tuples — which also keeps __hash__ consistent with __eq__.
        return hash(
            (
                self.horizon,
                self.snapshot_name,
                tuple(
                    (day, tuple(sorted(row.items())))
                    for day, row in sorted(self.values.items())
                ),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"TargetSeries(horizon={self.horizon}, "
            f"snapshot={self.snapshot_name!r}, "
            f"{len(self.values)} dates)"
        )


@dataclass(frozen=True)
class AlignedTargets:
    """Step 4's whole result — one :class:`TargetSeries` per horizon.

    The five-horizon bundle the pipeline hands to the null gate (feature
    76) and the metrics (features 79 on): the rebalance grid the targets
    were aligned over, and the series keyed by horizon.  Always one series
    for *every* horizon in :data:`HORIZONS` — a horizon whose coverage is
    empty is carried as an empty series, not dropped, because "one target
    series per horizon" is a promise about shape as well as content: a
    consumer iterating the five horizons of a decay profile must find five,
    including the ones a short window left with nothing to measure.

    Construction validates the bundle's coherence, not just its members:
    the series' keys are exactly :data:`HORIZONS`, each series carries its
    own horizon, and every series names the same snapshot — a bundle whose
    series disagreed about which sealed world they came from would be a
    provenance fault no downstream hash can catch.
    """

    #: The canonical name of the sealed snapshot the execution's window —
    #: and therefore this alignment's closes — belong to.
    snapshot_name: str

    #: The rebalance dates the alignment ran over (the execution's grid),
    #: ascending.  Wider than any single series' :meth:`TargetSeries.dates`
    #: by construction: the grid states what was scored, the series state
    #: what each horizon can measure.
    rebalance_dates: Tuple[dt.date, ...]

    #: The five series, as ``{horizon: TargetSeries}``.
    series: Mapping[int, TargetSeries]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorAlignmentError(
                "aligned targets must name the sealed snapshot they were "
                f"aligned over, got {self.snapshot_name!r}"
            )
        if not isinstance(self.rebalance_dates, tuple):
            raise EvaluatorAlignmentError(
                "rebalance_dates must be a tuple of dates, got "
                f"{type(self.rebalance_dates).__name__}"
            )
        for day in self.rebalance_dates:
            if not isinstance(day, dt.date):
                raise EvaluatorAlignmentError(
                    f"rebalance dates must be calendar dates, got {day!r}"
                )
        if list(self.rebalance_dates) != sorted(set(self.rebalance_dates)):
            # Refused rather than quietly re-sorted: sortedness is the
            # grid's invariant, and a producer that emitted an unsorted or
            # duplicated grid is a bug this should surface, not absorb —
            # the same rule WindowResolution holds the universe to.
            raise EvaluatorAlignmentError(
                "rebalance_dates must arrive sorted and de-duplicated; the "
                "producer that emitted them drifted"
            )
        if not isinstance(self.series, Mapping):
            raise EvaluatorAlignmentError(
                "series must map horizon to TargetSeries, got "
                f"{type(self.series).__name__}"
            )
        carried = tuple(sorted(self.series))
        if carried != HORIZONS:
            raise EvaluatorAlignmentError(
                "aligned targets carry one series per horizon the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}), got "
                f"{', '.join(str(h) for h in carried) or 'none'}"
            )
        for horizon, series in self.series.items():
            if series.horizon != horizon:
                raise EvaluatorAlignmentError(
                    f"the series filed under horizon {horizon} carries "
                    f"horizon {series.horizon}; a series filed under the "
                    "wrong horizon is a pairing every downstream metric "
                    "would trust and be wrong by"
                )
            if series.snapshot_name != self.snapshot_name:
                raise EvaluatorAlignmentError(
                    f"the horizon-{horizon} series names snapshot "
                    f"{series.snapshot_name!r} but the alignment names "
                    f"{self.snapshot_name!r}; one alignment reads one "
                    "sealed world"
                )
        object.__setattr__(
            self, "series", MappingProxyType(dict(self.series))
        )

    @property
    def horizons(self) -> Tuple[int, ...]:
        """The horizons carried, ascending — always :data:`HORIZONS`."""
        return HORIZONS

    def targets(self, horizon: int) -> TargetSeries:
        """One horizon's target series.

        Refused for a horizon outside :data:`HORIZONS` — the set is closed,
        and a caller asking for horizon 3 is asking for a label the spec
        never defined, which deserves the vocabulary named rather than a
        ``None`` to trip over later.
        """
        if horizon not in self.series:
            raise EvaluatorAlignmentError(
                f"horizon {horizon} is not one of the horizons this "
                f"alignment carries ({', '.join(str(h) for h in HORIZONS)}); "
                "the null gate and the decay profile ask per horizon, and "
                "the set is the spec's, not the caller's to widen"
            )
        return self.series[horizon]

    def __hash__(self) -> int:
        # Same fold as TargetSeries, for the same reason: the record is a
        # value, and the mapping is not hashable until it collapses to
        # tuples.
        return hash(
            (
                self.snapshot_name,
                self.rebalance_dates,
                tuple(sorted(self.series.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"AlignedTargets(snapshot={self.snapshot_name!r}, "
            f"{len(self.rebalance_dates)} rebalance dates, "
            f"horizons={list(self.series)!r})"
        )


# -- The alignment ------------------------------------------------------------


def align_targets(
    execution: SignalExecution,
    closes: Mapping[str, Mapping[Union[dt.date, str], Any]],
) -> AlignedTargets:
    """Align forward returns to an execution's grid, one series per horizon.

    Pipeline step 4 (§6.1): for every horizon ``h`` in :data:`HORIZONS` and
    every rebalance date the ``execution`` scored, the per-symbol forward
    return ``close[d+h] / close[d] − 1`` over the market grid the closes
    name — the sorted union of the scored symbols' bar dates, so a horizon
    steps forward in *bars*, never calendar days.  The result is an
    :class:`AlignedTargets`: five :class:`TargetSeries`, one per horizon,
    absent — never zero, never NaN — wherever the target cannot be computed
    from the sealed data.

    ``execution`` is feature 73's result: its dates are the grid, each
    vector's universe is the cross-section targets are aligned for, and its
    snapshot name is the provenance stamped on every series.  ``closes`` is
    the fetched close prices as ``{symbol: {date: close}}`` — a value read
    from the sealed snapshot host-side, keyed by calendar date or ISO
    string, every price finite and positive.  Closes for symbols the
    execution did not score are validated and then ignored, so a
    whole-market fetch and a scored-universe fetch align identically.

    Refused, each with its reason (see ``_errors`` for the taxonomy): an
    ``execution`` that is not one; a ``closes`` mapping that is not one or
    carries a malformed key or price; an execution with no rebalance dates
    or no scored symbols at all; a scored symbol whose entry close is
    missing on its own rebalance date (feature 72's universe rule admitted
    it *because* it had a bar that day — the fetch is missing what the
    roster guarantees); and an alignment with no computable target at any
    horizon (the closes carry nothing after the rebalance grid — five
    empty series would report "aligned" for an evaluation with nothing to
    measure).
    """
    if not isinstance(execution, SignalExecution):
        raise EvaluatorAlignmentError(
            "align_targets aligns against a SignalExecution — the grid and "
            "the per-date universe come from the execution's vectors — got "
            f"{type(execution).__name__}"
        )

    prices = _validated_closes(closes)

    dates = execution.dates()
    if not dates:
        raise EvaluatorAlignmentError(
            "the execution scored no rebalance dates, so there is no grid "
            "to align targets on — execute the signal over a window first "
            "(feature 73)"
        )

    scored: dict[str, None] = {}
    for vector in execution.vectors.values():
        for symbol in vector.universe:
            scored.setdefault(symbol, None)
    if not scored:
        raise EvaluatorAlignmentError(
            "the execution scored an empty universe at every rebalance "
            "date, so there is no cross-section to align targets for — a "
            "target is a label for symbols that were scored"
        )

    # The entry closes.  The universe rule (feature 72) admits a symbol on
    # a day its sealed bars carry a partition on that very date, so every
    # scored symbol must have that day's close; a fetch without it is a
    # broken read, refused by name rather than narrowed around.
    entry: dict[Tuple[dt.date, str], float] = {}
    for day in dates:
        for symbol in execution.vectors[day].universe:
            price = prices.get(symbol, {}).get(day)
            if price is None:
                raise EvaluatorAlignmentError(
                    f"the closes carry no bar for {symbol!r} on "
                    f"{day.isoformat()}, its rebalance date — the universe "
                    "rule (feature 72) admits a symbol only on a day its "
                    "sealed bars carry a partition, so a scored symbol must "
                    "have that day's close; the fetch is missing what the "
                    "roster guarantees"
                )
            entry[(day, symbol)] = price

    # The market grid: the scored symbols' bar dates, sorted.  This — not
    # the calendar — is what a "period" steps on, and deriving it from the
    # scored symbols only is what makes the alignment reproducible however
    # broad the fetch was.
    grid = sorted({day for symbol in scored for day in prices[symbol]})
    position = {day: index for index, day in enumerate(grid)}

    aligned: dict[int, dict[dt.date, dict[str, float]]] = {
        horizon: {} for horizon in HORIZONS
    }
    for day in dates:
        at = position.get(day)
        if at is None:
            # An empty-universe date contributes its (empty) cross-section
            # to nothing: presence in a series means a target was computed,
            # and there were no symbols to compute one for.
            continue
        for horizon in HORIZONS:  # ascending — see the break below
            exit_at = at + horizon
            if exit_at >= len(grid):
                # Grid positions are ascending and so are the horizons:
                # once one horizon runs off the end, every later one does.
                break
            exit_day = grid[exit_at]
            row: dict[str, float] = {}
            for symbol in execution.vectors[day].universe:
                exit_price = prices[symbol].get(exit_day)
                if exit_price is not None:
                    # The simple (arithmetic) forward return — the label
                    # spelling step 7's costs and step 8's rank IC are
                    # defined over (see the module docstring).
                    row[symbol] = exit_price / entry[(day, symbol)] - 1.0
            if row:
                aligned[horizon][day] = row

    if not any(aligned.values()):
        raise EvaluatorAlignmentError(
            "no forward return could be aligned at any horizon — the "
            f"market grid the closes name ends {grid[-1].isoformat()} and "
            "no rebalance date has a bar after it, so the fetch supplied "
            "none of the forward half of the label; fetch closes that "
            "extend past the last rebalance date"
        )

    series = {
        horizon: TargetSeries(
            horizon=horizon,
            snapshot_name=execution.snapshot_name,
            values=MappingProxyType(values),
        )
        for horizon, values in aligned.items()
    }
    return AlignedTargets(
        snapshot_name=execution.snapshot_name,
        rebalance_dates=dates,
        series=MappingProxyType(series),
    )
