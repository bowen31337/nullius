"""Measuring the decay profile — pipeline step 8, feature 81.

app_spec.xml feature 81: *"System computes a decay profile measuring
information coefficient at each of the five horizons, persisting it as a
stored array."*  docs/nullius-tech-architecture.md §6.1 names the step —
``8. compute_metrics    IC series, IR, turnover, decay, capacity, regime
attribution`` — and §9.2 names where the profile lands:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      decay_profile.json

docs/alpha-engine-prd.md's artifact block states the shape and the axis in
one line — ``decay_profile: array    # IC at h = 1, 2, 5, 10, 20 periods`` —
and its decay row states what the profile is *for*: the live loop tracks a
promoted signal's forward IC and recalibrates "the decay priors" and, where
the decay outruns discovery, feeds the observed half-life into campaign
planning.  The computation lives here; :mod:`evaluator._decay_store` writes it
down, on the split this package already uses three times (``_identity``
computes and ``_store`` persists for feature 70, ``_costs`` and
``_cost_store`` for 79, ``_capacity`` and ``_capacity_store`` for 82), and it
is the split features 80 and 81 share: this module computes no other metric.

Three decisions carry the feature, and each is a pin rather than a knob:

*the coefficient is the *Spearman rank* correlation, and that is feature 74's
rank transform, not a second one.*
    An information coefficient is "how well did the score order the
    cross-section against what the cross-section then did", and the evaluator
    has already committed to an answer about ordering: step 3 normalizes a raw
    score by *ranking* it and z-scoring the ranks, precisely so two authors who
    agree on order and disagree on magnitude land on the same footing (feature
    74, and §5.1's "Sign and scale are free; the evaluator ranks and
    z-scores").  The coefficient here is therefore computed on the **average
    (fractional) ranks** of both sides — the score's and the forward return's —
    which is exactly the Spearman rank correlation, and exactly the tie
    convention ``normalize_scores`` uses: tied symbols share the mean of the
    ranks they would have occupied.  Two consequences follow and both are
    wanted.  First, the profile measures the order the evaluator committed to,
    so an IC of 0.3 *means* "the ranking the system acted on ordered the next
    ``h`` bars' returns by 0.3" rather than a statement about a magnitude
    normalization threw away.  Second, the profile is invariant to any strictly
    increasing rescale of the score — which is the same invariance §5.1 grants
    the sign and scale — while a Pearson correlation of the raw scores would
    not be, so a node's decay profile could move when nothing about its
    ordering did.  This is *not* a second implementation of anything: the rank
    transform is spelled once in this package (``_decay._average_ranks``) and
    the normalization's z-score is a monotone function of the same ranks, so
    ranking the normalized score and ranking the raw score agree.

*the pairs are (normalized score, post-cost return), joined on the grid the
    *returns* priced.*
    The IC at horizon ``h`` pairs each decision date's cross-section of
    normalized scores with the *same dates'* horizon-``h`` forward returns —
    step 7's series, fees already netted out — over the symbols both sides
    carry.  Pairing against **post-cost** returns rather than step 4's gross
    ones is the same choice the capacity half makes and for the same reason:
    the profile is a statement about the edge this signal would have earned,
    and an IC measured against a gross return the fee schedule then ate is a
    number describing a world nobody traded.  It is also what keeps the five
    entries on one axis with the metrics features 80 and 82 report: §9.2 files
    ``decay_profile.json`` beside ``signal_returns.parquet``, and a reader
    comparing a node's IC at horizon 5 against its capacity at horizon 5 is
    reading two numbers that must have been measured over one priced panel.
    The *symbols* are the intersection, because the two sides legitimately
    differ: a scored symbol may have no return at ``h`` (delisted inside the
    horizon — feature 75's absence rule), and the returns carry symbols the
    signal never scored.  Only the pairs are correlated; neither side is
    zero-filled to meet the other.

*the array is five long, its axis is :data:`HORIZONS`, and an un-measured
    horizon is ``None``.*
    The feature says "each of the five horizons" and the PRD writes the axis
    out — ``h = 1, 2, 5, 10, 20`` — so :meth:`DecayProfile.as_array` returns a
    five-entry tuple whose *i*-th entry is the IC at :data:`HORIZONS`'s *i*-th
    horizon, which is the "stored array" the feature persists and the array
    §9.2's JSON is read back as.  The axis is positional rather than keyed
    because that is what downstream consumes it as: §9.2 stores it as JSON and
    the live loop compares a forward profile against a stored one entry by
    entry, so a profile whose entries were keyed by horizon would have to be
    re-aligned by every reader.  A horizon the window was too short to measure
    — a 12-bar evaluation cannot measure horizon 20 — carries ``None``, never
    ``0.0``: "the window never spanned 20 bars" and "the signal has no edge at
    20 bars" are different findings, and the second is a promotion-relevant
    number while the first says nothing at all.  §9.2's JSON stores it as a
    JSON ``null``, and the store's reader refuses a row whose array disagrees
    with its own per-horizon terms.

**What each entry is measured from, and the denominators.**  For a horizon
``h`` with supported dates ``D_h`` (the dates step 7 priced at ``h`` *and* the
signal scored), and for each date ``d ∈ D_h`` the joined cross-section
``J_d`` of symbols the score and the return both carry:

.. code-block:: text

    ic_d  = spearman( score_{i,d}, net_return_{i,d} ) over i ∈ J_d
    IC_h  = mean_d ic_d                                (the array's entry)
    n_h   = |D_h|                                      (the count carried)

The per-date coefficients are kept on :attr:`HorizonDecay.ic_series` — the
series §9.2 files separately as ``ic_series.parquet`` and the series features
80's ``ic_tstat`` will be computed over — because the mean alone cannot be
read: a mean of 0.05 over 200 dates and the same mean over 3 are different
qualities of evidence, which is why the count travels beside it, and because
the stored row can then be checked against itself (the mean must be the mean
of its own series, see :mod:`evaluator._decay_store`).

**The refusals, and why a fabricated zero is the failure they prevent.**  A
correlation is undefined — not zero — in exactly two shapes, and both are
refused rather than defaulted, on the same terms :func:`evaluator.
normalize_scores` refuses them one step earlier:

* *a cross-section of one* at some date — a correlation needs two points to
  be about anything, and "the signal predicted the order" is meaningless with
  nothing to order.
* *a constant side* at some date — every score identical (the signal ranked
  nothing, feature 74's own refusal) or every return identical (the
  cross-section's outcome had no order to agree with).  The rank spread is
  zero, the denominator is zero, and returning ``0.0`` would dress "no
  measurement exists" up as "measured no relationship" — the one value that
  neither promotes nor demotes and therefore hides the difference.

An evaluation whose every horizon is un-measured is refused outright (nothing
measured, no profile to store — the same stance :func:`apply_costs` and
:func:`estimate_capacity` take), and a score series that is not keyed by dates
the priced grid carries, or whose values are not finite numbers, is refused by
name: a NaN would reach the array dressed as a measurement.

**What this module does not do.**  It computes no other metric — ``ic_mean``,
``ic_tstat``, ``ir_standalone`` and turnover are feature 80, capacity and
regime attribution feature 82, ``ir_marginal`` feature 83 — it does not
normalize (feature 74's ``normalize_scores`` ran two steps earlier; this step
takes its output), align (75), gate (76), price (79) or persist
(:mod:`evaluator._decay_store` owns the write, and the artifacts member's
``decay_profile.json`` — feature 172 — reads that store back, the same
division feature 79's cost store states for ``signal_returns.parquet``).  It
takes step 7's record and step 3's normalized scores and answers exactly the
one question step 8 puts in its scope: *how much information does this signal
carry at each of the five horizons?*

**The layering note.**  This module is stdlib-only — dates, mappings, square
roots and arithmetic; no polars, no pyarrow, no numpy, no lake, no
environment, no HTTP, and no import of any other member.  The score vector
arrives as a *value* (the caller pairs ``RawScoreVector.universe`` with
``normalize_scores``' output, so the Polars boundary stays at the edge of the
package where every other member keeps it), which is what makes importing
this member cost composition — and the replay path §1 forbids from reaching
the evaluator — nothing at all.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Optional, Tuple, Union

from ._align import HORIZONS
from ._costs import CostModelRef, PostCostReturns
from ._errors import EvaluatorDecayError

__all__ = [
    "DECAY_HORIZONS",
    "DECAY_STEP",
    "DecayProfile",
    "HorizonDecay",
    "compute_decay_profile",
]

#: The pipeline-step name, in §6.1's own spelling.  Step 8 is the metrics
#: step — ``compute_metrics    IC series, IR, turnover, decay, capacity,
#: regime attribution`` — and this module owns the *decay* item on that list.
#: Shared vocabulary: the feature sentence, the refusals below, and every
#: reader of a persisted profile name the one step that measures decay, and
#: they name it once.
DECAY_STEP: str = "compute_metrics"

#: The horizons the stored array's axis is pinned to, ascending — the same
#: closed set feature 75 aligns over, restated here as this member's own
#: promise so a reader of :meth:`DecayProfile.as_array` does not have to
#: follow an import to learn what the entries mean.
#:
#: The array is *positional* over this tuple: entry *i* is the IC at
#: ``DECAY_HORIZONS[i]``, which is what "persisting it as a stored array"
#: persists and what the PRD's ``# IC at h = 1, 2, 5, 10, 20 periods``
#: describes.  Deliberately the same object as :data:`~evaluator.HORIZONS`
#: rather than a second tuple that happens to hold the same five numbers: a
#: profile whose axis the alignment did not define would be a decay curve
#: against x-positions the spec does not name.
DECAY_HORIZONS: Tuple[int, ...] = HORIZONS


# -- The score side, accepted and validated ------------------------------------


def _score_date(key: Any) -> dt.date:
    """One score key, as a calendar :class:`datetime.date`.

    Accepted spellings: a ``date``, or an ISO string naming one — a service
    boundary's wire spelling, the same courtesy the charge keys and the gate's
    answers extend.  A ``datetime`` is refused (it names an instant, and both
    sides of an information coefficient are day-granular: the score was taken
    at a rebalance date's close and the return is that date's forward return),
    and anything else is refused by name.
    """
    if isinstance(key, dt.datetime):
        raise EvaluatorDecayError(
            f"the normalized scores are keyed by a datetime ({key!r}); an "
            "information coefficient pairs one rebalance date's cross-section "
            "with that date's forward return — key by the calendar date (or "
            "its ISO string)"
        )
    if isinstance(key, dt.date):
        return key
    if isinstance(key, str):
        try:
            return dt.date.fromisoformat(key)
        except ValueError as exc:
            raise EvaluatorDecayError(
                f"the score date {key!r} is not an ISO date; the scores are "
                "keyed by rebalance dates (or ISO date strings), one per bar"
            ) from exc
    raise EvaluatorDecayError(
        f"score dates must be dates or ISO date strings, got {key!r} "
        f"({type(key).__name__})"
    )


def _validated_scores(
    scores: object,
) -> dict[dt.date, Mapping[str, float]]:
    """The normalized scores, validated and captured per date.

    ``{rebalance date: {symbol: normalized score}}`` — step 3's own output,
    read as a value.  This step does not normalize: the rank-then-z-score
    reduction is feature 74's, and re-doing it here would be a second
    normalization the evaluator could then disagree with itself about, which
    is precisely the divergence the frozen-evaluator contract exists to rule
    out.

    Every value must be a finite number.  A NaN would reach the correlation's
    numerator, make the coefficient NaN, and land in the stored array dressed
    as a measurement — the same refusal every numeric input in this package
    carries, for the same reason.
    """
    if not isinstance(scores, Mapping):
        raise EvaluatorDecayError(
            "the normalized scores must map rebalance date to {symbol: "
            f"score{'}'}, got {type(scores).__name__}; pass step 3's output "
            "(feature 74) paired with the universe it was scored against"
        )
    captured: dict[dt.date, Mapping[str, float]] = {}
    for key, row in scores.items():
        day = _score_date(key)
        if day in captured:
            raise EvaluatorDecayError(
                f"the normalized scores carry {day.isoformat()} twice under "
                "different spellings; one bar, one cross-section"
            )
        if not isinstance(row, Mapping):
            raise EvaluatorDecayError(
                f"the normalized scores for {day.isoformat()} must map symbol "
                f"to a score, got {type(row).__name__}"
            )
        inner: dict[str, float] = {}
        for symbol, value in row.items():
            if not isinstance(symbol, str) or not symbol:
                raise EvaluatorDecayError(
                    f"the normalized scores for {day.isoformat()} must be "
                    f"keyed by non-empty symbol names, got {symbol!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorDecayError(
                    f"the normalized score for {symbol!r} on "
                    f"{day.isoformat()} must be a number, got {value!r}"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EvaluatorDecayError(
                    f"the normalized score for {symbol!r} on "
                    f"{day.isoformat()} is not finite ({value!r}); a NaN or "
                    "±inf would reach the decay profile dressed as a "
                    "measurement"
                )
            inner[symbol] = number
        if inner:
            captured[day] = MappingProxyType(inner)
    if not captured:
        raise EvaluatorDecayError(
            "the normalized scores carry no cross-section at any date, so "
            "there is nothing to measure an information coefficient over; an "
            "empty decay profile would report five horizons of decay for a "
            "signal that was never scored"
        )
    return captured


# -- The one spelling of the coefficient ---------------------------------------


def _average_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """Average (fractional) ranks of one cross-section, keyed by symbol.

    The rank transform feature 74 pins for the scores, applied to either side
    of the coefficient: symbols whose values tie share the *mean* of the ranks
    they would have occupied, so (as ``normalize_scores`` argues) the transform
    is symmetric under negation and the rank sum stays fixed at ``n(n+1)/2``
    whatever the ties look like.  Spelling it once here is what makes the
    measured coefficient the Spearman correlation by construction rather than
    by a second definition that could drift from the normalization's.
    """
    ordered = sorted((value, symbol) for symbol, value in values.items())
    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        stop = index
        while stop + 1 < len(ordered) and ordered[stop + 1][0] == ordered[index][0]:
            stop += 1
        # Ranks are 1-based; a tie group of k starting at position i shares
        # (i + 1 + i + k) / 2, the mean of the k ranks it would have occupied.
        shared = (index + 1 + stop + 1) / 2.0
        for position in range(index, stop + 1):
            ranks[ordered[position][1]] = shared
        index = stop + 1
    return ranks


def _rank_correlation(
    scores: Mapping[str, float],
    returns: Mapping[str, float],
    *,
    day: dt.date,
    horizon: int,
) -> float:
    """The Spearman rank correlation of one date's joined cross-section.

    Both sides are reduced to average ranks (:func:`_average_ranks`) and the
    Pearson coefficient of those ranks is returned — which is what the
    Spearman correlation *is*, stated as arithmetic rather than as a library
    call so the estimator is pinned here the way feature 74 pins its z-score
    and feature 82 pins its square-root law.  ``fsum`` keeps both means and
    the covariance term exact regardless of the cross-section's iteration
    order, so the same panel measures the same IC however it was built.

    Refused rather than defaulted when the coefficient is undefined — a
    cross-section of fewer than two joined symbols, or either side constant
    (zero rank spread) — because the only available default is ``0.0``, and
    "this date measured no relationship" and "this date could not be measured"
    are findings a decay profile must keep apart (see the module docstring).
    """
    symbols = tuple(sorted(set(scores) & set(returns)))
    if len(symbols) < 2:
        raise EvaluatorDecayError(
            f"horizon {horizon} on {day.isoformat()} has "
            f"{len(symbols)} symbol(s) carrying both a normalized score and a "
            "post-cost return; an information coefficient is a correlation, "
            "and a cross-section of one is not a cross-section — nothing can "
            "be relatively preferred within it"
        )
    score_ranks = _average_ranks({symbol: scores[symbol] for symbol in symbols})
    return_ranks = _average_ranks({symbol: returns[symbol] for symbol in symbols})
    count = float(len(symbols))
    score_mean = math.fsum(score_ranks.values()) / count
    return_mean = math.fsum(return_ranks.values()) / count
    covariance = math.fsum(
        (score_ranks[symbol] - score_mean) * (return_ranks[symbol] - return_mean)
        for symbol in symbols
    )
    score_spread = math.fsum(
        (score_ranks[symbol] - score_mean) ** 2 for symbol in symbols
    )
    return_spread = math.fsum(
        (return_ranks[symbol] - return_mean) ** 2 for symbol in symbols
    )
    if score_spread == 0.0 or return_spread == 0.0:
        # Exactly the "the scale that was to be removed was not there" case
        # normalize_scores refuses one step earlier, arriving from either side:
        # a constant score is the signal expressing no preference, and a
        # constant return is a cross-section whose outcome had no order.  Both
        # make the denominator zero, so the only value the arithmetic could
        # return is a fabricated zero.
        flat = "scores" if score_spread == 0.0 else "post-cost returns"
        raise EvaluatorDecayError(
            f"horizon {horizon} on {day.isoformat()} has constant {flat} "
            f"across its {len(symbols)} joined symbols, so the rank spread is "
            "zero and the information coefficient is undefined; refusing "
            "rather than returning 0.0 — 'measured no relationship' and "
            "'could not be measured' are different findings, and a fabricated "
            "zero is the one value that hides the difference"
        )
    return covariance / math.sqrt(score_spread * return_spread)


# -- The records ----------------------------------------------------------------


@dataclass(frozen=True)
class HorizonDecay:
    """One horizon's decay — its entry in the array, and the terms behind it.

    The per-horizon half of :class:`DecayProfile`.  The per-date coefficients
    are carried beside the mean rather than reduced away, for the same reason
    the post-cost series is stored in full: the mean alone cannot be checked,
    cannot be re-read as the IC series §9.2 files separately, and cannot
    support the ``ic_tstat`` feature 80 computes over the same dates.  They
    are also what makes the record self-verifying — :attr:`mean_ic` must be
    the mean of :attr:`ic_series`, enforced at construction *and* again on
    every read-back, so a stored row that disagrees with itself is refused
    rather than trusted (the defence the identity store applies to a hash that
    does not fold from its terms, and the cost store to a net that does not
    equal its own gross less its own charge).
    """

    #: The horizon this entry measures, in periods — one of
    #: :data:`DECAY_HORIZONS`.
    horizon: int
    #: How many rebalance dates this horizon measured — the denominator of
    #: :attr:`mean_ic`, carried because the five horizons cover different
    #: supports and a mean without its count cannot be read.
    dates: int
    #: The equal-weight mean of the per-date information coefficients — the
    #: value that lands in the stored array at this horizon's position.
    mean_ic: float
    #: The per-date coefficients, as ``{rebalance date: information
    #: coefficient}`` — the IC series, in ascending date order.
    ic_series: Mapping[dt.date, float]

    def __post_init__(self) -> None:
        # object.__setattr__ where the constructor normalizes; this record
        # validates only, like the per-horizon capacity it sits beside.
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise EvaluatorDecayError(
                f"a horizon decay's horizon must be an integer period count, "
                f"got {self.horizon!r}"
            )
        if self.horizon not in DECAY_HORIZONS:
            raise EvaluatorDecayError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in DECAY_HORIZONS)}); the "
                "axis of the stored array is closed — feature 75 pins it and "
                "step 8 measures each of the horizons it covers"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise EvaluatorDecayError(
                f"a horizon decay's date count must be an integer, got "
                f"{self.dates!r}"
            )
        if self.dates < 1:
            raise EvaluatorDecayError(
                f"the horizon-{self.horizon} decay claims {self.dates} "
                "measured dates; a horizon with no dates carries no entry at "
                "all — absence, not zero — and is spelled ``None`` on the "
                "profile"
            )
        if not isinstance(self.ic_series, Mapping):
            raise EvaluatorDecayError(
                "a horizon decay's ic_series must map rebalance date to the "
                f"information coefficient measured on it, got "
                f"{type(self.ic_series).__name__}"
            )
        series: dict[dt.date, float] = {}
        for day, value in self.ic_series.items():
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorDecayError(
                    f"an ic_series must be keyed by calendar dates, got {day!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorDecayError(
                    f"the information coefficient on {day.isoformat()} must be "
                    f"a number, got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise EvaluatorDecayError(
                    f"the information coefficient on {day.isoformat()} is not "
                    f"finite ({value!r}); a NaN or ±inf would reach the stored "
                    "array dressed as a measurement"
                )
            series[day] = float(value)
        if not series:
            raise EvaluatorDecayError(
                f"the horizon-{self.horizon} decay carries an empty ic_series; "
                "a horizon that measured no date carries no entry at all"
            )
        if len(series) != self.dates:
            raise EvaluatorDecayError(
                f"the horizon-{self.horizon} decay claims {self.dates} "
                f"measured dates but its ic_series carries {len(series)}; the "
                "count is the denominator of the mean, and a record whose "
                "denominator disagrees with its own series is a record no "
                "reader can size the evidence behind"
            )
        if isinstance(self.mean_ic, bool) or not isinstance(
            self.mean_ic, (int, float)
        ):
            raise EvaluatorDecayError(
                f"a horizon decay's mean information coefficient must be a "
                f"number, got {self.mean_ic!r}"
            )
        object.__setattr__(self, "mean_ic", float(self.mean_ic))
        if not math.isfinite(self.mean_ic):
            raise EvaluatorDecayError(
                f"the horizon-{self.horizon} mean information coefficient is "
                f"not finite ({self.mean_ic!r}); a NaN or ±inf would reach "
                "the stored array dressed as a measurement"
            )
        expected = math.fsum(series[day] for day in sorted(series)) / len(series)
        if self.mean_ic != expected:
            raise EvaluatorDecayError(
                f"the horizon-{self.horizon} decay says its mean information "
                f"coefficient is {self.mean_ic!r} but its own ic_series mean "
                f"to {expected!r}; the record disagrees with itself, so it was "
                "built somewhere other than this module's arithmetic — an "
                "entry the array would trust and be wrong by"
            )
        object.__setattr__(self, "ic_series", MappingProxyType(series))

    def ic(self, rebalance_date: dt.date) -> Optional[float]:
        """One date's information coefficient, or ``None`` where un-measured.

        Absence is structural, as it is everywhere in this package: a date
        this horizon did not measure simply has no key, and there is never a
        zero standing in for a coefficient nobody computed.
        """
        return self.ic_series.get(rebalance_date)

    def __hash__(self) -> int:
        # The mapping is not hashable until it collapses to tuples; the fold
        # keeps __hash__ consistent with __eq__, as every record in this
        # package does.
        return hash(
            (
                self.horizon,
                self.dates,
                self.mean_ic,
                tuple(sorted(self.ic_series.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"HorizonDecay(horizon={self.horizon}, "
            f"ic={self.mean_ic:+.4f}, {self.dates} dates)"
        )


@dataclass(frozen=True)
class DecayProfile:
    """Step 8's decay answer — the stored array, with its terms beside it.

    ``decay_profile: array`` in the PRD's artifact block, `decay_profile.json`
    in §9.2's directory listing: for each of the five horizons feature 75
    pins, the mean information coefficient measured at that horizon, positional
    over :data:`DECAY_HORIZONS` — see :meth:`as_array`.  A horizon the window
    was too short to measure is carried as ``None``, never ``0.0``, so the
    array's own values keep the distinction the module docstring argues for,
    and each measured horizon's :class:`HorizonDecay` is kept beside the array
    because the array alone cannot say *how much evidence* stood behind an
    entry or which dates it was measured over.

    Stamped with the evaluation's provenance — node, sealed snapshot, cost
    model — for the reason the capacity record is: the coefficient is a
    function of a *priced* panel, two fee schedules net different post-cost
    returns out of the same gross ones, so the pair belongs in the identity of
    the profile and in the store's key beside the node, exactly as it is in
    the signal-returns and capacity tables.
    """

    #: The node whose signal was measured.
    node_id: str
    #: The canonical name of the sealed snapshot the panel was measured in.
    snapshot_name: str
    #: The cost model the returns were netted against.
    cost_model: CostModelRef
    #: One entry per horizon in :data:`DECAY_HORIZONS` — a
    #: :class:`HorizonDecay` where the horizon measured at least one date,
    #: ``None`` where the window was too short to measure it.
    horizon_ics: Mapping[int, Optional[HorizonDecay]]

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise EvaluatorDecayError(
                "a decay profile must name the node whose signal it measures, "
                f"got {self.node_id!r}"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorDecayError(
                "a decay profile must name the sealed snapshot its panel was "
                f"measured in, got {self.snapshot_name!r}"
            )
        if not isinstance(self.cost_model, CostModelRef):
            raise EvaluatorDecayError(
                "a decay profile must name the cost model its returns were "
                f"priced under, got {type(self.cost_model).__name__}; pass a "
                "CostModelRef (or coerce one with cost_model_ref())"
            )
        if not isinstance(self.horizon_ics, Mapping):
            raise EvaluatorDecayError(
                "a decay profile's horizon_ics must map horizon to HorizonDecay "
                f"or None, got {type(self.horizon_ics).__name__}"
            )
        carried = tuple(sorted(self.horizon_ics))
        if carried != DECAY_HORIZONS:
            raise EvaluatorDecayError(
                "a decay profile carries one entry per horizon the spec names "
                f"({', '.join(str(h) for h in DECAY_HORIZONS)}), got "
                f"{', '.join(str(h) for h in carried) or 'none'}; the stored "
                "array is positional over that axis, and an array of the wrong "
                "length is a decay curve against x-positions the spec does not "
                "name"
            )
        for horizon, decay in self.horizon_ics.items():
            if decay is not None and decay.horizon != horizon:
                raise EvaluatorDecayError(
                    f"the decay filed under horizon {horizon} carries horizon "
                    f"{decay.horizon}; an entry filed under the wrong horizon "
                    "is a pairing every reader of the stored array would trust "
                    "and be wrong by"
                )
        if all(decay is None for decay in self.horizon_ics.values()):
            raise EvaluatorDecayError(
                "a decay profile with no measured horizon has no information "
                "coefficient to store — an array of five nulls would report a "
                "measured decay for an evaluation whose window never spanned a "
                "single horizon; cost an alignment with coverage first "
                "(features 75 through 79)"
            )
        object.__setattr__(
            self, "horizon_ics", MappingProxyType(dict(self.horizon_ics))
        )

    @property
    def horizons(self) -> Tuple[int, ...]:
        """The array's axis, ascending — always :data:`DECAY_HORIZONS`."""
        return DECAY_HORIZONS

    def as_array(self) -> Tuple[Optional[float], ...]:
        """The stored array: one IC per horizon, positional over the axis.

        The feature's own value — *"persisting it as a stored array"* — as a
        five-entry tuple whose *i*-th entry is the information coefficient at
        ``DECAY_HORIZONS[i]``, or ``None`` where that horizon was un-measured.
        Positional rather than keyed because that is how downstream consumes
        it: the live loop reads a stored profile entry by entry against a
        forward one, and a mapping would have to be re-aligned by every reader.
        """
        return tuple(
            None if self.horizon_ics[horizon] is None
            else self.horizon_ics[horizon].mean_ic  # type: ignore[union-attr]
            for horizon in DECAY_HORIZONS
        )

    @property
    def measured_horizons(self) -> Tuple[int, ...]:
        """The horizons with an entry, ascending — the array's non-null positions."""
        return tuple(
            horizon
            for horizon in DECAY_HORIZONS
            if self.horizon_ics[horizon] is not None
        )

    def at(self, horizon: int) -> Optional[HorizonDecay]:
        """One horizon's decay, or ``None`` where the horizon is un-measured.

        Refused for a horizon outside :data:`DECAY_HORIZONS` — the set is
        closed, on the same terms as every per-horizon accessor this package
        carries.
        """
        if horizon not in self.horizon_ics:
            raise EvaluatorDecayError(
                f"horizon {horizon} is not one of the horizons this profile "
                f"carries ({', '.join(str(h) for h in DECAY_HORIZONS)}); the "
                "axis is the spec's, not the caller's to widen"
            )
        return self.horizon_ics[horizon]

    def __hash__(self) -> int:
        # Same fold as the capacity estimate, for the same reason: the mapping
        # is not hashable until it collapses to tuples.
        return hash(
            (
                self.node_id,
                self.snapshot_name,
                self.cost_model,
                tuple(
                    (horizon, self.horizon_ics[horizon])
                    for horizon in DECAY_HORIZONS
                ),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        measured = self.measured_horizons
        return (
            f"DecayProfile(node={self.node_id!r}, "
            f"{len(measured)}/{len(DECAY_HORIZONS)} horizons measured: "
            f"{[None if value is None else round(value, 4) for value in self.as_array()]})"
        )


# -- Step 8's decay half --------------------------------------------------------


def compute_decay_profile(
    returns: PostCostReturns,
    scores: Mapping[Union[dt.date, str], Mapping[str, float]],
) -> DecayProfile:
    """Measure the information coefficient at each of the five horizons.

    For every horizon in :data:`DECAY_HORIZONS` that ``returns`` priced, and
    every rebalance date that horizon covers, correlate the day's normalized
    scores against the day's post-cost returns — both reduced to average ranks,
    so the coefficient is the Spearman correlation — over the symbols the two
    sides share, and keep each date's coefficient beside their mean.  A horizon
    the priced panel never reached carries ``None``: un-measured, not zero.

    ``scores`` is step 3's own output as ``{rebalance date: {symbol: normalized
    score}}`` — :func:`evaluator.normalize_scores`' vector paired with the
    universe it was scored against (``RawScoreVector.universe``), which is how
    the Polars boundary stays at the edge of this package.  Dates the priced
    grid does not carry are validated and then ignored, the same rule the
    capacity half applies to dollar volumes: a score at a date the returns
    never priced is not a pair, and neither side is zero-filled to become one.
    A *symbol* on a covered date that one side carries and the other does not
    is simply not in that date's joined cross-section — feature 75's absence
    rule, applied to both sides at once.

    Raises :class:`~evaluator.EvaluatorDecayError`, each with its reason (see
    ``_errors``): a ``returns`` that is not step 7's own result; a ``scores``
    mapping that is malformed, empty, or carries a non-finite value; a date
    whose joined cross-section holds fewer than two symbols or on which either
    side is constant (the coefficient is undefined there, and ``0.0`` would
    hide that); and — via the records — a hand-built profile whose array does
    not carry exactly one entry per horizon.
    """
    if not isinstance(returns, PostCostReturns):
        raise EvaluatorDecayError(
            "compute_decay_profile measures step 7's own result — a "
            "PostCostReturns, the priced series the cost schedule "
            f"produced — got {type(returns).__name__}; the coefficient is a "
            "statement about the edge this signal would have earned, and an "
            "IC measured against gross returns a fee schedule then ate "
            "describes a world nobody traded"
        )
    validated = _validated_scores(scores)

    horizon_ics: dict[int, Optional[HorizonDecay]] = {}
    for horizon in DECAY_HORIZONS:
        series = returns.series[horizon]
        per_date: dict[dt.date, float] = {}
        for day in series.dates():
            row = validated.get(day)
            if row is None:
                # The grid the returns priced is what defines the panel; a
                # scored date this horizon did not price has no forward return
                # to correlate against, and inventing one is the look-ahead the
                # alignment refuses by construction.
                continue
            per_date[day] = _rank_correlation(
                row, series.at(day), day=day, horizon=horizon
            )
        if not per_date:
            horizon_ics[horizon] = None
            continue
        horizon_ics[horizon] = HorizonDecay(
            horizon=horizon,
            dates=len(per_date),
            mean_ic=math.fsum(
                per_date[day] for day in sorted(per_date)
            ) / len(per_date),
            ic_series=per_date,
        )

    if all(decay is None for decay in horizon_ics.values()):
        raise EvaluatorDecayError(
            "the priced panel and the normalized scores share no rebalance "
            "date at any horizon, so no information coefficient was measured "
            "and there is no decay profile to store — five nulls would report "
            "a measured decay for an evaluation whose scores and returns never "
            "met; score and price an alignment with coverage first (features "
            "75 through 79)"
        )

    return DecayProfile(
        node_id=returns.node_id,
        snapshot_name=returns.snapshot_name,
        cost_model=returns.cost_model,
        horizon_ics=horizon_ics,
    )
