"""The criteria a promotion is judged against, and the hash that fixes them.

app_spec.xml, "Promotion & Epoch Governance", feature 291: *System exposes
POST /promotion/pre-register, which returns a criteria hash recorded before the
deciding evaluation runs.*  This module is the first half of that sentence —
*which criteria*, and *what hash* — and :mod:`promotion.pre_register` is the
second, the recording.

docs/alpha-engine-prd.md §13 states the law this feature exists to enforce, as
one line among the invariants that *"violating any of these silently
invalidates the system"*::

    7. Promotion criteria are pre-registered and hashed before the evaluation
       that decides them.

The PRD's M4 milestone states what the rule is for, in the deployment it was
written for — *"Pre-register success criteria in a hashed file **before** the
shadow run starts"* — and the architecture doc's M4 gate row reads the same
promise back: *"90 days of shadow meeting pre-registered, hashed criteria."*
The word doing the work in both is **before**.  A criterion written down after
the result is known is not a criterion; it is a description of the result, and
the difference between the two is invisible in prose and decidable in a
timestamp.  So the system's answer is the same one an experimental protocol
gives: fix the criteria, hash them, and let the hash — not the prose — be what
the decision is checked against.

**The six terms are the promotion interface, and §13.7 says "criteria" without
enumerating them.**  :class:`PromotionCriteria` is the enumeration, and it is
not invented here: it is the set of terms the promotion's own surfaces already
carry, each one published by a feature, a milestone or a formula this workspace
ships.

* ``theta`` — the paired ΔIR advantage the promotion must clear.  prd §12's M3
  exit is *"Paired ΔIR > 0.3"* and §11.0's selection bar is the same figure
  from the other side; docs §10.3.1's meta-selection guard is its gate.  This
  is the criterion a promotion is *about*.
* ``alpha`` — the significance level the paired test is judged at.  prd §12's
  M3 exit states it beside the bar (*"p < 0.05"*).  A ΔIR bar with no α beside
  it is a bar with no test behind it.
* ``max_fdr_deploy`` — the ceiling on the deployment-base-rate false discovery
  rate.  prd §11 makes ``FDR_deploy`` the system's primary metric with target
  *"< 25% at π₀ = 0.9"*, and feature 268's headline rule is that this figure is
  the one published.  The ceiling belongs on the criteria because it is the
  number a promotion must not make worse.
* ``min_worlds`` — the pool size the promotion must be judged over.  prd §11.0's
  regimes are stated as pool-size bands (*"< 20 worlds: do not run dreaming"*,
  *"50+: full dreaming"*), and §12's M3 precondition is *"≥50 worlds"*.  A
  promotion decided on a thin pool is the overfitting §14 files as High.
* ``min_coverage_strata`` — how many regime strata the deployment's pool must
  cover.  §C7's promotion block (feature 285) reads one stratum; this is the
  breadth figure beside it, and the risk it answers is §14's *"Replay pool is
  regime-monotone | High"*.
* ``min_forward_days`` — the forward window the promoted signal must be
  measured over.  prd §13.4 and arch §M4 state the promise as 90 days
  (*"90 days of shadow meeting pre-registered, hashed criteria"*), and feature
  300 timestamps the promotion to start exactly that window.

**Why the hash is over a canonical document and not over the prose.**  Two
prose spellings of one criterion differ in whitespace, in key order and in
whether a number was written ``0.3`` or ``0.30``; a hash over the prose would
call those two criteria, and a promotion decided under the first would be
refused under the second for a difference nobody decided.  So the hash is taken
over a *canonical document* — the six terms, written as one JSON object with
its keys sorted, its numbers as JSON numbers, and no whitespace beyond the
separators JSON requires — and :meth:`PromotionCriteria.canonical` is the one
spelling of that document.  The rule the workspace states for every digest
applies unchanged (``artifacts``' ``code_hash``, ``dreaming``'s): ``hashlib.
sha256(canonical.encode("utf-8")).hexdigest()``, lowercase hex, which is the
spelling ``promotion_registry.criteria_hash CHAR(64)`` holds.

**A criterion is a number, and the boundary is the whole vocabulary.**  The
three reals are plain numbers and the three counts are non-negative integers
(``bool`` refused explicitly, for the reason every count validator in this
workspace states: ``True`` is ``1`` in Python, and a flag where a count belongs
would silently name the thinnest admissible pool — prd §11.0's own worry,
since its whole argument is that a thin pool is where dreaming overfits).
``alpha`` and ``max_fdr_deploy`` are probabilities held to ``[0, 1]``: α above
1 is not a level, and a ceiling above 1 refuses nothing, which makes it a
criterion no promotion could fail.  ``theta`` is the one term with no interval
and no floor — see :class:`PromotionCriteria` for why.

**Nothing here reads the evidence.**  This module holds the criteria and
computes their hash; it never reads a pool, a score, a coverage ledger or a
forward record, and it never sees the evaluation's result.  That is not modesty
— it is the mechanism.  §13.7's rule is only meaningful if the criteria are
fixed by a surface that *cannot* know the outcome, and a criteria module that
consulted the evidence would have no way to prove it did not.  Feature 292's
mismatch check and features 293-296's decision machinery read the evidence;
this one is the fixed point they are checked against.

Stdlib only, and import-cheap: ``hashlib``, ``json``, ``dataclasses``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from .errors import PromotionError

__all__ = [
    "CRITERIA_FIELDS",
    "PromotionCriteria",
    "criteria_hash",
]

#: The six terms a promotion's criteria state, in the order the PRD's own
#: milestones read them: the advantage the promotion is about, the test it is
#: judged at, the deployment figure it must not worsen, and the three
#: quantities of evidence it must be measured over.
#:
#: Spelled once as a module constant because three places need the same list
#: and none of them may restate it: :class:`PromotionCriteria`' fields, the
#: canonical document, and the store's read-back.  A seventh criterion is one
#: edit here and one field above.
CRITERIA_FIELDS: tuple[str, ...] = (
    "theta",
    "alpha",
    "max_fdr_deploy",
    "min_worlds",
    "min_coverage_strata",
    "min_forward_days",
)


def _validated_real(value: Any, field_name: str) -> float:
    """Return ``value`` as a finite real, or refuse what is not one.

    ``bool`` is refused explicitly — ``True`` is ``1`` in Python, and a flag
    where a threshold belongs would persist as a plausible number rather than
    an error, the mistake every validator in this workspace guards against.
    ``NaN`` and the infinities are refused for the same reason at a different
    scale: ``NaN`` compares false against everything, so a criterion holding
    one can never be met *or* missed, and a pre-registered criterion that no
    evaluation can decide is not a criterion — it is a promotion that can
    neither stand nor be refused.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PromotionError(
            f"a promotion criterion's {field_name} must be a real number — got "
            f"{value!r} ({type(value).__name__}); §13.7 registers the terms a "
            "promotion is judged against, and a threshold that is a flag or a "
            "string names no bar the deciding evaluation could clear "
            "(feature 291)"
        )
    number = float(value)
    # ``isnan`` rather than ``number != number``: the comparison is the same
    # test, but written this way a reader does not have to stop and decide
    # whether the self-comparison is a typo.
    if math.isnan(number) or math.isinf(number):
        raise PromotionError(
            f"a promotion criterion's {field_name} must be a finite real — got "
            f"{value!r}; a criterion that is NaN or infinite can never be met "
            "and can never be missed, so the deciding evaluation could neither "
            "promote nor refuse, and the pre-registration would have fixed a "
            "term no result could be checked against (feature 291)"
        )
    return number


def _validated_count(value: Any, field_name: str) -> int:
    """Return ``value`` as a non-negative integer, or refuse what is not one.

    ``bool`` refused first and explicitly: ``True`` is an ``int`` subclass
    equal to ``1``, and a flag where a count belongs would name the thinnest
    admissible pool.  A negative count is refused because a number of worlds,
    strata or days cannot be negative.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PromotionError(
            f"a promotion criterion's {field_name} must be a non-negative "
            f"integer — got {value!r} ({type(value).__name__}); this is a "
            "count of evidence a promotion must be measured over, and a count "
            "is not a truthy flag or a fraction (feature 291)"
        )
    if value < 0:
        raise PromotionError(
            f"a promotion criterion's {field_name} must be at least 0 — got "
            f"{value!r}; a negative quantity of worlds, strata or days is not "
            "evidence, and a criterion no pool can fail is not a criterion "
            "(feature 291)"
        )
    return value


def _validated_probability(value: Any, field_name: str) -> float:
    """Return ``value`` as a probability in ``[0, 1]``, or refuse it.

    The interval is the whole point for both terms that use it.  ``alpha`` is
    a significance level: above 1 it is not a level at all, and exactly 1
    accepts every result, which would register a test that can never refuse.
    ``max_fdr_deploy`` is a ceiling: above 1 it refuses nothing and below 0 it
    refuses everything, so a promotion could never be decided either way.
    Both *ends* are honoured — ``0.0`` and ``1.0`` are probabilities, and a
    deployment that deliberately registered α = 0.0 or a zero
    false-discovery-ceiling has made a decision this module has no business
    overruling; whether such a bar is *wise* is the deciding evaluation's
    question, not the pre-registration's.
    """
    number = _validated_real(value, field_name)
    if number < 0.0 or number > 1.0:
        raise PromotionError(
            f"a promotion criterion's {field_name} must lie in [0, 1] — got "
            f"{value!r}; it is a probability, and a value outside the interval "
            "is either not a level at all or a criterion no result could fail "
            "(feature 291)"
        )
    return number


@dataclass(frozen=True, slots=True)
class PromotionCriteria:
    """The six terms of §13.7's pre-registration, as one frozen value.

    Each field is a criterion the deciding evaluation is judged against, and
    the set is enumerated in :data:`CRITERIA_FIELDS` with the PRD line each one
    comes from.  Construction validates every term and canonicalises the
    numbers, so two callers who stated one criterion compare equal however they
    came by it — ``0.3`` and ``0.30`` are one bar, because both canonicalise
    to the same float.  The *counts* are held to ``int`` rather than
    canonicalised into it: ``50.0`` is refused where a count of worlds
    belongs, because a fractional world is not a world and coercing it would
    be this module inventing a pool size the caller did not state.

    Frozen, because a criterion the caller could edit between the
    pre-registration and the decision is precisely the thing §13.7 exists to
    prevent: the hash would have been taken over values that no longer hold,
    and the stored row would vouch for a document nobody can produce.

    ``theta`` is the one term with no interval and no floor, and the omission
    is deliberate rather than an oversight.  The other five have a shape that
    is wrong on its face — a probability outside ``[0, 1]``, a negative count
    — but a *low* advantage bar is not malformed, it is merely a bad
    pre-registration, and the two are different refusals.  prd §12's M3 exit is
    ``> 0.3`` and §11.0's whole argument is that a bar too low is the
    meta-overfitting failure *wearing a pass*, which is a judgement about
    evidence: it belongs to the evaluation that has an M and a σ to compare the
    bar against (§11.0's ``true_advantage > √(2 ln M)·σ_V/√n_worlds``), not to
    the surface that wrote the criteria down.  Refusing a negative θ here would
    also be wrong for a second reason — a deployment may legitimately
    pre-register θ = 0 to mean *the candidate must not be worse*, and that is a
    criterion, not a mistake.
    """

    #: The paired ΔIR advantage the promotion must clear — prd §12's M3 exit
    #: (*"Paired ΔIR > 0.3"*) and §11.0's selection bar.
    theta: float
    #: The significance level the paired test is judged at — prd §12's M3 exit
    #: (*"p < 0.05"*).
    alpha: float
    #: The ceiling on the deployment-base-rate false discovery rate — prd §11's
    #: primary metric target (*"< 25% at π₀ = 0.9"*).
    max_fdr_deploy: float
    #: The pool size the promotion must be judged over — prd §11.0's pool-size
    #: regimes and §12's M3 precondition (*"≥50 worlds"*).
    min_worlds: int
    #: How many regime strata the pool must cover — §C7's breadth figure beside
    #: feature 285's one-stratum block.
    min_coverage_strata: int
    #: The forward window the promoted signal must be measured over — prd §13.4
    #: and arch §M4 (*"90 days"*), the window feature 300 timestamps open.
    min_forward_days: int

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction.  After
        # this the instance is sealed — the discipline the ledger's record
        # layer and the regime member's coverage count both follow.
        object.__setattr__(self, "theta", _validated_real(self.theta, "theta"))
        object.__setattr__(
            self, "alpha", _validated_probability(self.alpha, "alpha")
        )
        object.__setattr__(
            self,
            "max_fdr_deploy",
            _validated_probability(self.max_fdr_deploy, "max_fdr_deploy"),
        )
        object.__setattr__(
            self, "min_worlds", _validated_count(self.min_worlds, "min_worlds")
        )
        object.__setattr__(
            self,
            "min_coverage_strata",
            _validated_count(self.min_coverage_strata, "min_coverage_strata"),
        )
        object.__setattr__(
            self,
            "min_forward_days",
            _validated_count(self.min_forward_days, "min_forward_days"),
        )

    def document(self) -> dict[str, Any]:
        """The criteria as the canonical document the hash is taken over.

        One flat object, :data:`CRITERIA_FIELDS`' keys to their canonical
        values — floats for the three reals, integers for the three counts.
        A fresh mapping each call, so a caller cannot reach through the return
        value into a later hash.
        """
        return {
            "theta": self.theta,
            "alpha": self.alpha,
            "max_fdr_deploy": self.max_fdr_deploy,
            "min_worlds": self.min_worlds,
            "min_coverage_strata": self.min_coverage_strata,
            "min_forward_days": self.min_forward_days,
        }

    def canonical(self) -> str:
        """The document as the one text string the hash is taken over.

        ``json.dumps`` with ``sort_keys=True`` and the tightest separators
        (``(",", ":")`` — no space after either).  Those choices are the whole
        of the canonical form and each is load-bearing:

        * ``sort_keys`` fixes the *order* of the keys, so a caller who built
          the mapping in another order hashes identically;
        * the tight separators fix the *whitespace*, so reformatting the
          document — pretty-printing it into a log line, say — does not change
          its hash;
        * the values are JSON numbers (``0.3``, not ``"0.3"`` or ``"0.30"``),
          so what is hashed is the value rather than a text spelling of it.

        What is deliberately *not* done: no rounding, no renaming of a term, no
        omission of a field a deployment happens to leave at a default.  Every
        term in :data:`CRITERIA_FIELDS` is in the document at its registered
        value, because a hash that omitted a criterion would be a hash that
        does not notice when that criterion changes — and §13.7's whole promise
        is that the criteria cannot change unnoticed.
        """
        return json.dumps(
            self.document(), sort_keys=True, separators=(",", ":")
        )

    @property
    def digest(self) -> str:
        """The criteria's own hash — :func:`criteria_hash` for a caller that
        already holds the value."""
        return criteria_hash(self)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PromotionCriteria(theta={self.theta!r}, alpha={self.alpha!r}, "
            f"max_fdr_deploy={self.max_fdr_deploy!r}, "
            f"min_worlds={self.min_worlds!r}, "
            f"min_coverage_strata={self.min_coverage_strata!r}, "
            f"min_forward_days={self.min_forward_days!r})"
        )


def criteria_hash(criteria: Any) -> str:
    """The sha256 hexdigest of the criteria's canonical document — §13.7's hash.

    ``hashlib.sha256(criteria.canonical().encode("utf-8")).hexdigest()``: 64
    lowercase hex characters, the spelling ``0108``'s ``criteria_hash CHAR(64)
    NOT NULL`` holds and the spelling feature 292 will compare.  The encoding
    is stated rather than left to a default, because a digest is defined over
    *bytes*: a document hashed as UTF-8 in one process and as something else in
    another would be two hashes of one criterion.

    Duck-reads its argument's ``canonical()`` rather than taking an
    ``isinstance``: the factory's scan imports every member under a synthetic
    module name, so the *composed* application serves a second class object of
    the same shape — the discipline every seam in this workspace states — and a
    class check here would refuse the very value composition produced.  A
    carrier with no callable ``canonical`` is refused in this member's
    vocabulary, because a hash of *something else* recorded as a promotion's
    criteria is exactly the row §13.7 exists to make impossible.
    """
    canonical = getattr(criteria, "canonical", None)
    if not callable(canonical):
        raise PromotionError(
            "a promotion's criteria hash is taken over the criteria's own "
            f"canonical document — got {criteria!r} "
            f"({type(criteria).__name__}), which has no callable "
            "``canonical``. §13.7's promise is that the hash names the criteria "
            "as they were written, so a hash taken over anything else would "
            "record a digest of a document no reader could reproduce "
            "(feature 291)"
        )
    text = canonical()
    if not isinstance(text, str):
        raise PromotionError(
            "a promotion's criteria hash is taken over the criteria's "
            f"``canonical()`` text — got {text!r} ({type(text).__name__}); a "
            "non-text document has no one spelling to encode, and two "
            "deployments would take two hashes of one criterion (feature 291)"
        )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
