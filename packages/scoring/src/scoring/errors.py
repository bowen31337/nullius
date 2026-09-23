"""The scoring member's error vocabulary.

One base class (:class:`ScoringError`) so a caller — the replay engine,
the dreaming loop's argmax, an operator script, a later feature in this
category — can catch every failure of the objective's arithmetic with a
single ``except``, the discipline :mod:`bootstrap.errors`,
:mod:`discovery.errors` and :mod:`policy_runtime.errors` state for their
own trees.  The categories this member will grow are visible in
app_spec.xml's "Objective Scoring & CVaR Aggregation" from the start —
the β-terms (257 through 262), the cross-world aggregation (263), the
scorer-process calibration figures (265 through 269) — and each carries
its own refusals when it lands; a subclass is added then, named for what
the caller must do about it, not for the line that raised.

Feature 256 needs exactly one: :class:`WorldObjectiveError`, the refusal
of a per-world objective ask that cannot be scored.  Feature 263 adds the
aggregation's own: :class:`AggregationError`, the refusal of a cross-world
ask that cannot be blended (see :mod:`scoring._aggregate` for that law's
own statement of which asks those are).  Every refusal either carries is a
fact about the *ask* — a world that is not a name, a pick that names no
node, a sequestered panel that cannot define a ratio, a stratum that holds
no worlds, a λ outside the band prd §7.2 states — and nothing was read
from any store and nothing is written when one raises, so the repair is
always to re-consider what was handed in.  That is a smaller taxonomy than
the store-owning members need because the objective is pure arithmetic:
it has no ordering laws to contradict and no deployment state to be
absent.  The division of labour that keeps it small is stated in
:mod:`scoring._objective` and worth restating here, because the two
refusals a caller might expect from a "scoring" member and does not get
are deliberate:

* **the non-committing policy is not this member's refusal.**  prd §438
  and docs §598 spell it as a *score*, ``−∞``, and feature 222 owns that
  value (:data:`policy_runtime.NON_COMMITTING_SCORE`, spelled once
  there) — the miss is answered by the termination, which routes the
  scorer only when a pick exists, so this member's arithmetic never sees
  a pickless ask and never invents an error for one.
* **a deployment with no data is not this member's refusal either.**
  Reaching the sequestered epoch's return readings is the replay
  engine's data access; the objective is a function of the readings it
  is handed.  A caller that has none has not been refused — it has not
  yet asked.
"""

from __future__ import annotations

__all__ = ["AggregationError", "ScoringError", "WorldObjectiveError"]


class ScoringError(Exception):
    """The base class of every refusal the scoring member raises.

    Deliberately not the base of the ``−∞`` a non-committing policy
    earns — that is a score, not an error (feature 222, prd §438) — and
    not the base of any failure in the data paths that feed the
    objective.  Catching this class catches the objective's own laws and
    nothing else, which is what a replay loop wrapping its scoring step
    in a single ``except`` needs to be true.
    """


class WorldObjectiveError(ScoringError):
    """A per-world objective ask that cannot be scored (feature 256).

    The ask was malformed — a world id that is not a name, a pick that
    names no node, a sequestered panel that cannot define an information
    ratio (fewer than two dates, a series that never varied, a reading
    that is not a finite real) — and the refusal names which, because
    the repair differs: a malformed pick is a wiring fault at the
    replay's commit seam, an undefined ratio is a data-coverage fact
    about the sequestered epoch, and conflating the two would send the
    operator looking in the wrong place.

    No partial value escapes a refusal: the objective either answers a
    frozen :class:`~scoring.WorldScore` or raises, so a caller can never
    hold a half-scored world it must remember to discard.
    """


class AggregationError(ScoringError):
    """A cross-world aggregation ask that cannot be blended (feature 263).

    The ask was malformed — strata that are not a mapping of stratum name
    to that stratum's world scores, a stratum that holds no worlds (whose
    mean would be a number nobody measured), a world carried by two
    strata or twice by one, a carrier that is not a world score, or a λ
    outside prd §7.2's ``[0.5, 0.7]`` band — and the refusal names which,
    because the repairs differ: an unstratified collection of scores is
    the plain mean over regimes that feature 264 exists to reject, an
    empty stratum is a coverage hole feature 286's ``empty_stratum``
    warning reports on the ledger (not a figure this blend may invent),
    and an out-of-band λ is a mis-set knob, not a broken input.

    No partial value escapes a refusal: the aggregation either answers a
    frozen :class:`~scoring.AggregatedObjective` or raises, so a caller
    can never hold a half-blended score it must remember to discard —
    the same guarantee :class:`WorldObjectiveError` makes one feature
    earlier, held here for the number the dreaming loop's argmax ranks
    candidates on (feature 274).
    """
