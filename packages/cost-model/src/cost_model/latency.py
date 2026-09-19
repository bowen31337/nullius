"""Feature 67's measurement layer: the empirical latency distribution.

app_spec.xml, "Cost Model & Fill Simulation", feature 67: *System persists
an empirical p50, p95 and p99 latency distribution measured from shadow
runs rather than an assumed constant.*  The sentence is a rejection of one
thing and an assertion of another, and each word is a separable claim this
module owns:

* **empirical** — the distribution is *measured*, not assumed.  It is the
  order statistics of a sample of observed shadow-run latencies, not a
  parametric family (exponential, log-normal, …) fitted to them.  A model
  carries an assumption about the shape of the tail; an empirical
  distribution carries only what the tape showed, and the day the tail is
  heavier than any named family the empirical one is still right.
* **p50, p95 and p99** — three quantiles, not one.  The single number a
  constant would have been names the centre; a latency distribution that a
  fill model prices against needs the centre *and* the tail, because a
  passive order that fills only when the tape trades through the price
  (feature 63) is exactly the order whose execution cost is set by the
  slow, rare, p99 path, not the p50.  Reporting all three refuses to let a
  latency story collapse to its median.
* **measured from shadow runs** — the data this distribution is built from
  is the round-trip latency the shadow execution path actually recorded
  (docs/nullius-tech-architecture.md §6.2, ``latency.source:
  measured_from_shadow``), not a vendor's published figure or a round
  number.  The module is agnostic to *how* the samples were gathered — a
  caller hands it the numbers — but it names their origin, because a
  latency taken from the wrong source is the one thing a test cannot catch
  from the numbers alone.
* **rather than an assumed constant** — there is deliberately no default
  latency anywhere in this module.  No :data:`DEFAULT_LATENCY_MS`, no
  "until you measure one" fallback: a constant is exactly the assumption
  the feature rules out, and a default would be a latency the evaluator
  prices against that nothing ever measured.  Building a distribution
  without samples is refused, not defaulted.

**A distribution is the samples, not a summary of them.**  The natural
shape for this value would be the three numbers — p50, p95, p99 — and
nothing else, since those are what the feature names and what gets
persisted.  But a distribution that forgets the sample it came from cannot
answer the questions a cost model must answer: *how many shadow runs is
this based on* (a p99 estimated from four samples is a number to distrust),
and *what is the worst case actually observed* (a p99 is a quantile, and a
quantile is not the maximum).  :class:`EmpiricalLatencyDistribution`
therefore keeps the whole sample and derives the quantiles from it, so the
summary and the data it summarises are one object and cannot disagree —
the same stance feature 59 takes on loading the configuration once and
resolving everything from the one parse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .errors import CostModelConfigError

__all__ = [
    "DEFAULT_QUANTILES",
    "QUANTILE_METHOD",
    "EmpiricalLatencyDistribution",
    "quantile",
]

#: The three quantiles feature 67 names, as percentile ranks.  Spelled once
#: so the distribution, its persistence and any caller that reports the
#: latency share one list rather than each inventing ``[50, 95, 99]``.
DEFAULT_QUANTILES = (50.0, 95.0, 99.0)

#: The quantile-definition convention.  ``"linear"`` is numpy's default
#: (``numpy.percentile``'s interpolation method) — the rank of the p-th
#: percentile is ``p/100 * (n - 1)`` in the sorted sample, and a rank that
#: falls between two order statistics is interpolated linearly.  Named here
#: rather than assumed, so the convention a score's cost is computed under
#: is a visible constant and not a buried arithmetic choice.
QUANTILE_METHOD = "linear"


def quantile(sorted_samples: Sequence[float], p: float) -> float:
    """Return the ``p``-th percentile of ``sorted_samples`` (linear method).

    ``sorted_samples`` must already be in non-decreasing order and contain
    at least one value — :func:`EmpiricalLatencyDistribution` sorts and
    guards before calling, so this function is the pure arithmetic of the
    quantile and nothing else.  The rank of the percentile is
    ``p/100 * (n - 1)`` over the sorted sample (``QUANTILE_METHOD``); a
    rank that lands on an order statistic returns that statistic, and a
    rank between two statistics is interpolated between them.  This is
    ``numpy.percentile``'s default behaviour, reproduced in pure Python so
    the member carries no numerical dependency for a computation that is
    three interpolations.

    A percentile outside ``[0, 100]`` is refused: a p100 would read one
    past the last order statistic and a negative percentile has no meaning,
    and a latency quantile built on a silently clamped rank would be a
    cost the numbers do not support.
    """
    if not (0.0 <= p <= 100.0):
        raise CostModelConfigError(
            f"percentile must be within [0, 100], got {p!r}"
        )
    n = len(sorted_samples)
    if n == 1:
        # A single observation has no spread to interpolate over: every
        # quantile is that one value.  This is the honest answer for a
        # one-sample distribution, and numpy agrees.
        return float(sorted_samples[0])
    rank = (p / 100.0) * (n - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_samples[int(rank)])
    fraction = rank - lower
    return float(
        sorted_samples[lower] + fraction * (sorted_samples[upper] - sorted_samples[lower])
    )


@dataclass(frozen=True)
class EmpiricalLatencyDistribution:
    """An empirical latency distribution measured from shadow runs.

    Feature 67's value: the p50, p95 and p99 of a sample of observed
    round-trip latencies, kept *as the sample* so the quantiles are derived
    from it rather than stored beside it.  The distribution is what a
    latency-aware cost computation prices against, and it is empirical in
    the strong sense — no parametric family is fitted, the order statistics
    of the sample are the distribution.

    The sample is validated at construction and the sorted order cached, so
    every quantile is answered from one sort and a distribution built on an
    unusable sample is refused before any number is reported.

    Attributes:
        samples: The observed latencies, in the order they were measured.
            Recorded verbatim (frozen): the distribution is a record of
            what the shadow runs showed, and a caller that could append to
            it after construction would be changing what was measured.
        quantiles: The percentile ranks this distribution reports — p50,
            p95 and p99 by default (see :data:`DEFAULT_QUANTILES`).  A
            caller may ask for a different set, but the set is fixed at
            construction so the reported distribution and the quantiles it
            names cannot drift apart mid-process.

    Raises:
        CostModelConfigError: If the sample is empty, is not a sequence of
            real numbers, or contains a non-finite or negative latency —
            each is a measurement the distribution cannot stand on, named.
    """

    samples: Sequence[float] = field(default_factory=tuple)
    quantiles: Sequence[float] = DEFAULT_QUANTILES

    def __post_init__(self) -> None:
        # A distribution is built from its samples, so the sample is the
        # thing that can be wrong.  Every defect is refused by name, and the
        # ordering of the checks is the ordering the error messages read in.
        object.__setattr__(self, "samples", tuple(self.samples))
        object.__setattr__(self, "quantiles", tuple(self.quantiles))
        if len(self.samples) == 0:
            raise CostModelConfigError(
                "an empirical latency distribution needs at least one "
                "measured shadow-run latency; a distribution with no samples "
                "is the assumed constant feature 67 refuses to fall back to"
            )
        for value in self.samples:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CostModelConfigError(
                    f"latency samples must be real numbers, got "
                    f"{type(value).__name__} ({value!r})"
                )
            if math.isnan(value) or math.isinf(value):
                raise CostModelConfigError(
                    f"latency samples must be finite, got {value!r}: a "
                    "non-finite latency is a measurement error, not a tail"
                )
            if value < 0:
                raise CostModelConfigError(
                    f"latency samples must be non-negative, got {value!r}: a "
                    "negative round-trip latency is a clock error, not a "
                    "measurement"
                )

    @property
    def sorted_samples(self) -> tuple[float, ...]:
        """The samples in non-decreasing order, cached from one sort.

        The quantiles are order statistics, so they read the sample sorted;
        sorting once and caching it means a distribution that answers three
        quantiles sorts once, not three times, and a caller reading the
        ordered sample for its own purposes gets the same ordering the
        quantiles used.
        """
        return tuple(sorted(self.samples))

    @property
    def n(self) -> int:
        """The number of shadow runs this distribution is measured from."""
        return len(self.samples)

    @property
    def observed_minimum(self) -> float:
        """The fastest latency actually observed.

        A p50 is a centre and a p99 is a tail; the minimum is neither, but
        it is the one latency a reader reaches for first, and it is the
        floor the fill model's best-case fill prices against.  Reported
        rather than inferred, because it is a fact the tape recorded.
        """
        return min(self.sorted_samples)

    @property
    def observed_maximum(self) -> float:
        """The slowest latency actually observed.

        A p99 is a quantile, and a quantile is not the maximum: with enough
        samples the worst observed latency sits above the p99, and a reader
        comparing "the tail" to "the worst case" must be able to see both.
        """
        return max(self.sorted_samples)

    def percentile(self, p: float) -> float:
        """Return the ``p``-th percentile of the measured sample.

        The single quantile primitive: sort the sample (cached, see
        :attr:`sorted_samples`) and read the order statistic at rank
        ``p/100 * (n - 1)`` (see :func:`quantile`).  Every reported
        quantile goes through this one seam, so p50, p95 and p99 cannot
        each compute their rank a different way.
        """
        return quantile(self.sorted_samples, p)

    def percentiles(self, quantiles: Optional[Sequence[float]] = None) -> dict[float, float]:
        """Return this distribution's quantiles as a ``{percentile: value}`` map.

        Defaults to :attr:`quantiles` — p50, p95 and p99 — so a caller that
        just wants "the latency distribution" gets exactly the three
        numbers feature 67 names; an explicit ``quantiles`` lets a caller
        ask for more (or fewer) points off the same sample without building
        a second distribution.  The map is rebuilt on every call rather
        than cached, so it always reflects the distribution's current
        sample and never a quantile set from an earlier call.
        """
        ranks = tuple(quantiles) if quantiles is not None else self.quantiles
        return {p: self.percentile(p) for p in ranks}

    @property
    def p50(self) -> float:
        """The median measured latency — the distribution's centre."""
        return self.percentile(50.0)

    @property
    def p95(self) -> float:
        """The 95th-percentile measured latency — the body of the tail."""
        return self.percentile(95.0)

    @property
    def p99(self) -> float:
        """The 99th-percentile measured latency — the extreme tail."""
        return self.percentile(99.0)

    def summary(self) -> dict[str, object]:
        """A human- and machine-readable summary of the measured distribution.

        The shape a caller persists or logs: the three named quantiles plus
        the provenance a cost model needs to trust them — how many shadow
        runs they were measured from, and the observed extremes.  A summary
        is a view over the distribution, not a copy of it, so it is rebuilt
        on every call and names the quantile convention it was computed
        under.
        """
        return {
            "method": QUANTILE_METHOD,
            "n": self.n,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "observed_minimum": self.observed_minimum,
            "observed_maximum": self.observed_maximum,
        }
