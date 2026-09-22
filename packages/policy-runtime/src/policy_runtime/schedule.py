"""Feature 227, the threshold schedule — every threshold routed through one mapping.

app_spec.xml, "Exploration Policy Runtime", feature 227: *System routes every
threshold through one schedule mapping derived from beta, which returns all
thresholds as a single mapping.*  docs/nullius-tech-architecture.md §609 states
the law verbatim — *"`beta` is read once in ``__init__``, fixed for the episode,
routed through a single ``_schedule(beta) -> dict`` so every threshold moves
together.  Swept on a grid offline.  This is carried over from the paper
unchanged because it is what makes cross-cycle comparison legible."* — and
docs/alpha-engine-prd.md §7.4 names the thresholds beta governs: *explore/exploit,
patience, and pruning aggressiveness*, plus the added role where beta *gates
overfit aversion* — *"high beta tolerates longer branches before demanding
out-of-sample confirmation; low beta prunes on the first sign of the §4.5
signature"*.

**The feature is the derivation half, and its precedent is the value half already
in this workspace.**  Feature 226's :class:`EpisodeBeta` is the scalar — read
once, fixed, one number the whole episode is compared under.  What downstream
derives from it is *every threshold in the episode*, and feature 227 is the one
place that derivation happens: :func:`schedule` takes the scalar and returns
*all* the thresholds, together, as a single mapping.  The split is the feature,
and it is the same split §609 draws: 226 says *the scalar is one number and it
does not move*; 227 says *every threshold is derived from it, together*.  A
threshold reached anywhere but through this one mapping would be a second beta —
a threshold derived from the scalar by some other path is exactly the drift the
single-scalar discipline exists to prevent, arriving through a second formula
instead of through a reassignment.

**One mapping, and it is the only way to a threshold.**  :func:`schedule` returns
the whole set of thresholds as a single :class:`types.MappingProxyType`; there is
no ``explore_threshold(beta)``, no ``patience(beta)`` — no free function that
derives one threshold on its own.  A caller that needs a threshold reads it from
the mapping the schedule returns, so the mapping is the single derivation point
and "every threshold moves together" is a fact about the code rather than a
promise in a docstring.  The mapping carries *all* the thresholds on every call —
never a subset — so a schedule that forgot a threshold is refused by the tests,
not silently partial: the four thresholds the paper names (explore/exploit,
patience, pruning aggressiveness, overfit aversion) are always present, always
the same four keys, whatever the scalar is.

**A pure function of beta, and nothing else.**  :func:`schedule` consults no
store, no clock, no configuration and no episode state — it is ``beta -> dict``
and nothing more, so the same scalar returns the identical mapping however it is
asked, and two cycles opened at one scalar are comparable because they explored
under the identical thresholds.  That is the legibility §609 says the discipline
exists to protect.  Each threshold is a *deterministic, monotonic* function of
the scalar: they move together (all are functions of the one number) but not
identically (each is its own curve, at its own steepness), so a sweep over beta
moves the four thresholds in concert without collapsing them into one.

**The scalar reaches here already validated.**  :func:`schedule` does not
re-check that beta is a finite real number — :func:`policy_runtime.read_beta`
refused anything else at the top of the episode (feature 226), so the scalar that
reaches the schedule is already the finite real the episode is fixed to, and the
schedule is therefore pure arithmetic over it.  Re-validating here would be a
second spelling of 226's guard, and a second spelling of a pure gate is a second
thing to keep in sync.  The numerically stable sigmoid (:func:`_sigmoid`) is what
keeps the arithmetic honest for a large-but-finite scalar: a beta of ``1e9`` is a
legitimate grid point (226 imposes no band), and a naive ``1 / (1 + exp(-z))``
would overflow on it — so the stable form saturates to 0 or 1 instead, and a
finite scalar always derives finite thresholds.

**The returned mapping is frozen.**  A threshold is a *recorded* fact — what a
policy explored under, and what its score was earned under — and a policy
comparing two cycles must not be able to move either.  So the mapping is a
:class:`types.MappingProxyType` over a freshly built dict: read-only, so a caller
that holds it holds the thresholds as they were derived, and cannot reassign one
— the same "a value type cannot be moved" stance :class:`EpisodeBeta` takes on the
scalar, restated for the thresholds the scalar derives.  A fresh dict per call,
never a shared one, so two calls never alias.

Stdlib only, and import-cheap: :mod:`math`, :mod:`types` and the typing helpers —
nothing from :mod:`.beta` (the scalar is read as the float it is, so the schedule
does not depend on the value type it derives from) and nothing at module scope
the factory's scan pays for.  The split from 226 is deliberate and kept: the
scalar is validated there, derived from here.
"""

from __future__ import annotations

import math
import types
from collections.abc import Mapping

__all__ = [
    "EXPLORE_EXPLOIT",
    "OVERFIT_AVERSION",
    "PATIENCE",
    "PRUNE_AGGRESSIVENESS",
    "SCHEDULE_KEYS",
    "schedule",
]

#: The threshold keys, in the order the mapping carries them — the *whole* set a
#: schedule returns.  Kept as named constants so a caller reads a threshold by
#: its name rather than a string literal, and so "all thresholds" has exactly
#: one spelling: the four the paper names (docs §7.4), no more, no fewer.
#:
#: * :data:`EXPLORE_EXPLOIT` — the fraction of the search budget spent exploring
#:   rather than exploiting; rises with beta.  A fraction in ``(0, 1)``.
#: * :data:`PATIENCE` — how many refinement steps a branch is granted before it
#:   must show out-of-sample progress; rises with beta.  A budget in ``(1, 10)``.
#: * :data:`PRUNE_AGGRESSIVENESS` — how readily a branch is pruned on a weak
#:   reading; *falls* with beta, because high beta tolerates longer branches
#:   before demanding confirmation (docs §7.4).  A fraction in ``(0, 1)``.
#: * :data:`OVERFIT_AVERSION` — how strongly the §4.5 overfit signature must be
#:   confirmed before a branch is trusted; *falls* with beta for the same reason.
#:   A fraction in ``(0, 1)``.
EXPLORE_EXPLOIT = "explore_exploit"
PATIENCE = "patience"
PRUNE_AGGRESSIVENESS = "prune_aggressiveness"
OVERFIT_AVERSION = "overfit_aversion"

#: The four keys, as the single ordered tuple the mapping always carries — the
#: definition of "all thresholds", so a caller can iterate the whole set and a
#: test can assert the schedule is never partial.
SCHEDULE_KEYS = (EXPLORE_EXPLOIT, PATIENCE, PRUNE_AGGRESSIVENESS, OVERFIT_AVERSION)

#: The steepness of each falling threshold's curve.  Pruning drops off *sharply*
#: as beta rises (a branch is tolerated only a little longer per unit of beta),
#: while overfit aversion drops off *gently* (the §4.5 signature stays aversive
#: across the sweep).  Distinct scales so the two falling thresholds are two
#: curves, not one — they move together because both are functions of beta, but
#: not identically, which is what lets an offline sweep discriminate them.
_PRUNE_SCALE = 0.5
_OVERFIT_SCALE = 1.5

#: The patience band — the floor and span the scalar is mapped onto.  A branch is
#: granted at least one refinement step (a floor of one, so explore-only is not
#: the default) and at most ten; the exact band is the offline sweep's, not a law
#: (226 imposes no band on beta, and which finite betas a grid tries is the
#: deployment's business), so these are the default parameterization the sweep
#: replaces, stated here rather than hidden in the formula.
_PATIENCE_FLOOR = 1.0
_PATIENCE_SPAN = 9.0


def _sigmoid(z: float) -> float:
    """The logistic sigmoid, in a form that never overflows for a finite ``z``.

    The naive ``1 / (1 + exp(-z))`` overflows to an :class:`OverflowError` once
    ``-z`` is large — and a beta of ``1e9`` is a legitimate grid point (feature
    226 refuses only a non-finite scalar, never a large one), so ``-z`` *is*
    large across the sweep.  Split on the sign of ``z``: for a non-negative
    argument the decaying exponential underflows to zero rather than the growing
    one overflowing, and for a negative argument it is the growing exponential
    that is bounded.  Either way a finite scalar saturates to 0 or 1 instead of
    raising, so every finite beta derives finite thresholds — the arithmetic is
    honest for the whole of 226's un-banded domain.
    """
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    overflow = math.exp(z)
    return overflow / (1.0 + overflow)


def schedule(beta: float) -> Mapping[str, float]:
    """Derive every threshold from the episode's beta, as one frozen mapping.

    The feature's verb.  Takes the episode's scalar — already the finite real
    :func:`policy_runtime.read_beta` guaranteed at the top of the episode
    (feature 226), so this is pure arithmetic over it, not a re-validation — and
    returns *all* the thresholds, together, as a single read-only mapping keyed by
    :data:`SCHEDULE_KEYS`.  It is the one derivation point: there is no other way
    to a threshold, so every threshold in the episode is a function of the one
    number that cannot move, and the thresholds a policy explored under are the
    thresholds its score was earned under.

    Each threshold is a deterministic, monotonic function of the scalar, so the
    mapping moves together with beta — but not identically, each at its own
    steepness:

    * :data:`EXPLORE_EXPLOIT` rises with beta — a higher scalar devotes more of
      the search budget to exploration, the paper's explore/exploit knob;
    * :data:`PATIENCE` rises with beta — a higher scalar grants a branch more
      refinement steps before it must show out-of-sample progress;
    * :data:`PRUNE_AGGRESSIVENESS` falls with beta — a higher scalar prunes less
      readily, tolerating a longer branch before demanding confirmation;
    * :data:`OVERFIT_AVERSION` falls with beta, more gently than pruning — a
      higher scalar is slower to demand confirmation of the §4.5 signature.

    The returned mapping is a :class:`types.MappingProxyType` over a fresh dict —
    read-only, so a caller cannot move a threshold once derived, and never a
    shared dict, so two calls never alias.  A fresh mapping per call, but with
    identical values for an identical scalar: the schedule is a pure function of
    beta, so two cycles opened at one scalar explore under identical thresholds,
    which is the cross-cycle legibility §609 says the discipline exists to
    protect.
    """
    scalar = float(beta)
    thresholds = {
        EXPLORE_EXPLOIT: _sigmoid(scalar),
        PATIENCE: _PATIENCE_FLOOR + _PATIENCE_SPAN * _sigmoid(scalar),
        PRUNE_AGGRESSIVENESS: _sigmoid(-scalar / _PRUNE_SCALE),
        OVERFIT_AVERSION: _sigmoid(-scalar / _OVERFIT_SCALE),
    }
    # Frozen over a fresh dict: the thresholds are a recorded fact a caller holds
    # and compares, not a mapping it can move — the value-type stance 226 takes on
    # the scalar, restated for the thresholds the scalar derives.
    return types.MappingProxyType(thresholds)
