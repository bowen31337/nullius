"""Leak-statistic builders for the corpus suite — the probe's own leak theory, restated.

The corpus (:mod:`tripwires.corpus`) plants score panels that leak; this
module is the *independent* restatement of what "leak" means, so the suite can
assert that a planted signal actually leaks rather than merely trusting the
corpus to have built one.  The split is the honest one: the corpus owns the
planted panels (feature 133's maintained artifact), and this module owns the
*definition* of the leak each panel is supposed to embody — the whole-sample
statistic a time shuffle cannot disturb.  A test that checks a planted panel
against this module's builder is checking that feature 133 planted what it
claims to have planted.

Two properties the builders share, and both are the leak:

* **whole-sample.**  Every statistic here is computed over the *entire* target
  series, so the score a date carries does not depend on the date — which is
  exactly why feature 125's derangement (re-dating whole cross-sections)
  cannot destroy it.  A statistic computed over only part of the sample (a
  median, a slope, a half-sample mean) does not have this property and is
  deliberately *absent* here: it would escape the shuffle, and a corpus that
  planted leaks the probe is not supposed to catch would assert a false
  guarantee.  See :mod:`tripwires.corpus` for the discrimination account.

* **date-independent.**  The score panel a builder produces is the statistic
  held constant across dates, keyed identically to the target series.  That
  constancy is not a simplification — it is the leak, made visible: a panel
  that does not vary with the date carries the whole sample into every
  cross-section, so whatever survives the shuffle is panel-level information
  the score was never supposed to see.

The builders are deterministic in the bundle they are handed — a pure function
of the target series — so a planted panel rebuilt from the corpus's own bundle
is bit-for-bit the corpus's panel, which is what lets the suite assert the two
are the same.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping

__all__ = [
    "full_sample_mean",
    "full_sample_mean_negated",
    "full_sample_tstat",
    "full_sample_tstat_negated",
]


def _full_sample_mean(
    series: Mapping[dt.date, Mapping[str, float]],
) -> dict[str, float]:
    """The canonical leak: each symbol's mean over the whole sample."""
    days = sorted(series)
    return {
        name: math.fsum(series[day][name] for day in days) / len(days)
        for name in series[days[0]]
    }


def full_sample_mean(series: Mapping[dt.date, Mapping[str, float]]) -> dict[str, float]:
    """The full-sample mean leak — the corpus's ``full_sample_mean`` panel's statistic."""
    return _full_sample_mean(series)


def full_sample_mean_negated(
    series: Mapping[dt.date, Mapping[str, float]],
) -> dict[str, float]:
    """The sign-flipped full-sample mean — the corpus's ``full_sample_mean_negated``."""
    return {name: -value for name, value in _full_sample_mean(series).items()}


def full_sample_tstat(
    series: Mapping[dt.date, Mapping[str, float]],
) -> dict[str, float]:
    """The full-sample t-statistic leak — the corpus's ``full_sample_tstat``."""
    days = sorted(series)
    statistic: dict[str, float] = {}
    for name in series[days[0]]:
        column = [series[day][name] for day in days]
        mean = math.fsum(column) / len(column)
        dispersion = math.sqrt(
            math.fsum((value - mean) ** 2 for value in column) / len(column)
        )
        statistic[name] = mean / dispersion if dispersion != 0.0 else 0.0
    return statistic


def full_sample_tstat_negated(
    series: Mapping[dt.date, Mapping[str, float]],
) -> dict[str, float]:
    """The sign-flipped full-sample t-statistic — the corpus's ``full_sample_tstat_negated``."""
    return {name: -value for name, value in full_sample_tstat(series).items()}
