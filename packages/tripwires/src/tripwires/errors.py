"""The tripwires member's error vocabulary.

Every refusal in this package raises one of three errors, and each names a
*reason* rather than a bare fact, because a tripwire suite runs unattended
inside a frozen evaluator (docs/nullius-tech-architecture.md §5) whose
failures travel as trial outcomes (§8's ``ok | timeout | error |
tripwire_fail``): an ``error`` outcome is only actionable if the exception
behind it says what was wrong with the panel, the shuffle or the statistic
rather than "value error".

The split is by *where* the refusal happens, which is the split the
pipeline's own step boundaries already draw:

* :class:`TripwirePanelError` — the inputs are not a panel a tripwire can
  probe.  Malformed scores or targets (wrong container shapes, non-finite
  values, keys that are not dates), a candidate and a target bundle that
  share no horizon, or a join with fewer than the two dates a shuffle
  needs.  The analogue of the alignment and window refusals upstream
  (features 72 through 75): nothing was measured, and dressing an absent
  measurement up as a verdict is exactly the failure mode this category
  exists to prevent — a tripwire that "passed" a node it never probed.
* :class:`TripwireStatisticError` — the panel is well-formed but the
  statistic is undefined on it.  The surviving Sharpe divides by a
  dispersion, and a candidate whose per-date probe returns never varied
  has a zero denominator: refusing rather than fabricating an infinity is
  the same stance the metrics step takes on a constant book (feature 80)
  and the coefficient takes on a constant side (feature 81).

There is deliberately no ``TripwireVerdictError``.  A verdict is stated,
not raised: the two things a tripwire can say about a node are *pass* and
*leakage indicated*, and both are values (:class:`~tripwires.time_shuffle.
TimeShuffleVerdict.rejected`).  A tripwire that raised on detection would
be indistinguishable, at the trial-ledger layer, from a tripwire that
crashed — and feature 91's outcome vocabulary exists precisely so those
two futures do not collapse into one word.
"""

from __future__ import annotations

__all__ = [
    "TripwireError",
    "TripwirePanelError",
    "TripwireStatisticError",
]


class TripwireError(Exception):
    """The base of every refusal this member raises.

    The tripwires are step 10 of the evaluator pipeline (§6.1), but they
    are *not* the evaluator: this member imports no other workspace
    member, so its errors share no hierarchy with the evaluator's — a
    caller catching :class:`~evaluator.EvaluatorError` will not
    accidentally swallow a tripwire's refusal, and vice versa.  Catch this
    base only when the reason does not matter.
    """


class TripwirePanelError(TripwireError):
    """The candidate or the targets are not a panel a tripwire can probe."""


class TripwireStatisticError(TripwireError):
    """The panel is well-formed but the statistic is undefined on it."""
