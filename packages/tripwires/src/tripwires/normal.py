"""The inverse standard normal CDF — one closed form, stated once.

Why this member carries its own: the tripwires' verdicts are thresholds on
a standardized statistic (``surviving_sharpe`` against the null quantile
``z / √T``, docs/alpha-engine-prd.md §7's "√(1/T) standard error" the
frozen evaluator's multiple-testing bars are stated in), and the standard
library ships no ``Φ⁻¹``.  The alternatives were a third-party dependency
(SciPy — a dependency graph the frozen evaluator §12's determinism story
does not want inside a hash-pinned image for one function) or a lookup
table (which pins the levels a caller may ask for, and feature 127's
configured degradation threshold is already a signal that levels want to
stay a parameter).  So the quantile is *computed*, from one pinned
algorithm, and the algorithm is the only numerically clever thing in this
member.

**Acklam's algorithm, and why it is enough.**  The implementation is
Peter Acklam's rational approximation to the inverse normal CDF — the
widely re-published 2003 formulation with two rational pieces around the
central region, switching at ``p = 0.02425``.  Its worst-case *relative*
error is about ``1.15e-9``, which is three orders of magnitude below the
precision a verdict needs: the threshold is compared against a Sharpe
estimated from tens of dates of noisy products, so the eleventh
significant digit of ``z`` is far outside the statistic's own noise.  The
approximation is also symmetric in form (``Φ⁻¹(1−p) = −Φ⁻¹(p)`` — the
upper-tail branch is the lower-tail branch negated, matching to within
the approximation's own relative error), which matters because the
time-shuffle verdict is *two-sided*: the threshold at level ``α`` uses
``Φ⁻¹(1 − α/2)``, and a quantile function with asymmetric branch drift
would make leakage easier to hide on one sign than the other.

**The determinism note.**  The function is a fixed sequence of floating
operations with no platform-dependent calls (no ``math.erf``, no libm
``ndtri``), so the same ``p`` yields bit-identical ``z`` on every machine
that runs Python's IEEE-754 doubles — which is the determinism contract
(§12) at the scale this member operates.  A caller comparing two verdicts
across machines compares two numbers that came off one formula.

What this module does not do: it computes no statistic, states no
verdict, and knows nothing about panels, dates or horizons.  It answers
exactly one question — *which value sits at quantile ``p`` of the
standard normal?* — and every threshold in this member is built from that
one answer.
"""

from __future__ import annotations

import math

from .errors import TripwireError

__all__ = ["NORMAL_QUANTILE_SWITCH", "normal_quantile"]

#: The central-region switch point of Acklam's approximation.  Below it
#: (and above ``1 −`` it) the lower-tail rational piece runs; between the
#: two, the central piece.  Exposed because the switch is part of the
#: pinned algorithm a reproduction of these numbers would have to match,
#: not a tuning knob: moving it trades accuracy between the regions the
#: published coefficients were fitted against.
NORMAL_QUANTILE_SWITCH: float = 0.02425

# The three coefficient sets of Acklam's approximation, verbatim: the
# central region's numerator (a) and denominator (b), and the tail's
# numerator (c) and denominator (d).  Held as tuples of floats rather
# than module constants because they are the algorithm's body, not its
# vocabulary — nothing outside this function should cite them.
_ACKLAM_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_ACKLAM_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_ACKLAM_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_ACKLAM_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)


def normal_quantile(p: float) -> float:
    """The standard normal quantile at ``p`` — ``Φ⁻¹(p)``, Acklam's form.

    One pinned closed form (see the module docstring) with a worst-case
    relative error near ``1.15e-9``, exactly symmetric in ``p`` around
    ``0.5``, and bit-stable across machines.  ``p`` must be a real number
    strictly inside ``(0, 1)``: the quantile at ``0`` or ``1`` is ±∞, and
    a threshold that could name an infinity would reject nothing and
    everything at once, so the endpoints are refused by name rather than
    overflowed into.

    Raises :class:`~tripwires.TripwireError` (this module's base — the
    refusal is about the argument's *domain*, not about a panel or a
    statistic, so neither subclass fits) when ``p`` is not a finite
    number strictly between 0 and 1.
    """
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise TripwireError(
            f"the normal quantile is taken at a probability, got {p!r} "
            f"({type(p).__name__}); a level or a threshold argument "
            "arrived at the quantile spelled as something that is not a "
            "number"
        )
    probability = float(p)
    if not math.isfinite(probability):
        raise TripwireError(
            f"the normal quantile is taken at a finite probability, got "
            f"{p!r}; a NaN or ±inf level cannot name where a threshold "
            "sits"
        )
    if not 0.0 < probability < 1.0:
        raise TripwireError(
            f"the normal quantile is only finite strictly inside (0, 1), "
            f"got {p!r}; the quantile at 0 or 1 is ±∞, and a threshold "
            "that could name an infinity would reject nothing and "
            "everything at once"
        )
    if probability < NORMAL_QUANTILE_SWITCH:
        # The lower tail: both rational pieces run on q = √(−2 ln p).
        q = math.sqrt(-2.0 * math.log(probability))
        numerator = (
            ((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q
            + _ACKLAM_C[3]
        ) * q + _ACKLAM_C[4]
        numerator = numerator * q + _ACKLAM_C[5]
        denominator = (((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q
            + _ACKLAM_D[3]) * q + 1.0
        return numerator / denominator
    if probability <= 1.0 - NORMAL_QUANTILE_SWITCH:
        # The central region: the numerator carries the (p − ½) factor, so
        # the piece is odd in it and Φ⁻¹(0.5) is exactly 0.0.
        q = probability - 0.5
        r = q * q
        numerator = (
            ((_ACKLAM_A[0] * r + _ACKLAM_A[1]) * r + _ACKLAM_A[2]) * r
            + _ACKLAM_A[3]
        ) * r + _ACKLAM_A[4]
        numerator = numerator * r + _ACKLAM_A[5]
        denominator = (
            ((_ACKLAM_B[0] * r + _ACKLAM_B[1]) * r + _ACKLAM_B[2]) * r
            + _ACKLAM_B[3]
        ) * r + _ACKLAM_B[4]
        return numerator * q / (denominator * r + 1.0)
    # The upper tail: the mirrored lower-tail piece, negated.  The mirror
    # is the algorithm's own symmetry — the same rational pieces over the
    # same q = √(−2 ln ·) transform — and it holds to within the
    # approximation's ~1.15e-9 relative error (the rounding of 1 − p is
    # not exact for every small p, so the last ulp can differ; a verdict
    # threshold cannot see that many decimal places in).
    q = math.sqrt(-2.0 * math.log(1.0 - probability))
    numerator = (
        ((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q + _ACKLAM_C[3]
    ) * q + _ACKLAM_C[4]
    numerator = numerator * q + _ACKLAM_C[5]
    denominator = (((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q
        + _ACKLAM_D[3]) * q + 1.0
    return -(numerator / denominator)
