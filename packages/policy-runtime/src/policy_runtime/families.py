"""Feature 228, family conditioning — thresholds keyed on ``theme_root``.

app_spec.xml, "Exploration Policy Runtime", feature 228: *System supports
family-conditional thresholds keyed on theme_root, which returns a global
default for a theme carrying no evidence yet, expressed as policy-authored
thresholds rather than a fitted classifier.*  docs/nullius-tech-architecture.md
§11.1 states the reason the conditioning exists — *"the overfit signature is
only partly family-invariant"*: contribution concentration (Gini) *inverts*
across families (overfitting in cross-sectional momentum, the expected shape of
a working event-driven signal), and so does rolling-IC non-stationarity, so
*"a single global threshold averages the inverted features into uselessness, or
learns the majority family's sign and actively mis-ranks the minority.  The
policy writes **family-conditional thresholds routed through the same
``_schedule(beta)`` dict**, shrunk toward a global default so a new theme
starts at the prior and differentiates as evidence accumulates."* — and
docs/alpha-engine-prd.md §195 adds the guardrail on what that must not become:
*"Read 'model ``P(null | …)``' as a functional form, not as a mandate to train
one.  The default implementation is family-conditional thresholds written by
the policy-development agent — code, revised by dreaming, deterministic under
replay."*

**The feature is the family half of the schedule, and the split is the
feature.**  The beta knob has three halves, one per feature, and each guards a
different failure.  Feature 226 owns the scalar: :class:`EpisodeBeta`, read
once, fixed — a scalar that moves mid-episode is its failure.  Feature 227 owns
the mapping: :func:`schedule` returns *all* the thresholds from the one
derivation point — a threshold derived outside that mapping (a second beta) is
its failure.  Feature 228 owns the family dimension: the theme-keyed lookup
*over* that mapping — a family threshold that stopped being routed through the
schedule is its failure, and it arrives as plainly as an adjustment keyed by
something the one mapping does not carry.  :class:`FamilyConditional` is the
authored input (a theme, an adjustment per threshold, the evidence the theme
has accumulated); :class:`FamilySchedule` is the composed lookup;
:func:`family_schedule` is the one factory verb.

**Authored, not fitted — the positive half of feature 231's refusal.**  The
admission gate refuses a policy that reaches for a learned component, because
§11.2 defers that decision to the M1 triage; this module is what the policy
writes *instead*, and the two are one split.  A conditional is plain floats
authored by the policy-development agent — an adjustment per threshold, an
evidence count per theme — and the composition is arithmetic: no model class,
no checkpoint, no inference, nothing for feature 231's screen to find because
there is nothing learned here at all.  The dreaming loop revises the *numbers*
when a cycle's evidence says a theme differentiated, which is the whole of
"deterministic under replay": the same authored numbers compose the same
thresholds every time, on any machine, in any batch shape.  The theme the
conditioning is keyed on is the structural slug the ``question.meta(node_id)``
API exposes (docs §11, feature 219's accessor) — reached only via ``meta()``,
the check feature 230's gate already makes.

**Keyed on ``theme_root`` — and deliberately not the legal set.**  The key is
the slug itself, so a campaign's every cell can be looked up by the metadata it
carries.  This module's refusal on a key is structural only — a non-empty
string — because *which* themes may exist is feature 241's committed
``legal_themes.json``, a deployment's config; restating that ceiling here would
be a second spelling of a config-bound law, the drift both features exist to
prevent.  An *unknown* key is not an error at all: it is the feature's own
headline, the next paragraph's law.

**A new theme starts at the prior, exactly.**  The shrinkage weight is
``evidence / (evidence + PRIOR_STRENGTH)`` — the classic partial-pooling ratio,
which is the whole of *"family-specific behaviour shrunk toward a global prior
… no hierarchical Bayesian machinery required"*: empirical-Bayes shrinkage
without the Bayes.  Zero evidence yields a weight of zero, and a weight of zero
adds ``0.0``, so a theme carrying no evidence yet answers the global default
*to the bit* — even a theme the policy has already authored a conditional for
(authored intent, no evidence, prior answer: the safe direction for a default).
Evidence accumulates, the weight rises monotonically, and the theme
differentiates: its thresholds interpolate between the prior and the authored
position, never past it, and never at full strength for any finite evidence.
:data:`PRIOR_STRENGTH` is the knob — the evidence at which a conditional is
trusted at half strength — stated as a named constant rather than hidden in the
formula, the default parameterization the dreaming loop's own tuning replaces,
exactly the way feature 227 states ``_PATIENCE_FLOOR`` rather than inventing a
law.  The evidence *unit* is deliberately abstract (whatever the dreaming loop
records under a theme — campaigns, cells); the runtime takes the magnitude and
refuses a negative or non-finite one, because a negative count would push a
theme *past* its authored position, outside the interpolation the prior exists
to bound.

**Routed through the same schedule, or refused.**  The composition *calls*
:func:`schedule` — the one mapping feature 227 owns — and derives every family
threshold as that mapping's value plus the weighted adjustment, so a family
threshold is still a function of beta: move the scalar and the family
thresholds move with it, anchored, because the authored part is the *deviation*
from the schedule rather than a second dict of absolute values (which would
stand still while beta moved — the second beta, arriving as a table).  An
adjustment naming a key outside :data:`SCHEDULE_KEYS` is refused with this
member's own vocabulary: a threshold derived anywhere but through the one
mapping is the drift §609's single-scalar discipline exists to prevent, and a
family key is just a new road to it.  A partial conditional is legitimate — a
theme may condition only the thresholds whose §4.5 meaning inverts for it — but
an empty one is refused: a conditional that adjusts nothing conditions nothing.
And every answer, known theme or unknown, carries all four keys on every
lookup: the family path cannot narrow the schedule.

**The value-type stance.**  :class:`FamilyConditional` is frozen and validated
at construction, and its adjustments are copied into a read-only mapping —
never aliased to the dict it was authored from, so a caller that keeps writing
its authoring dict cannot move a conditional already composed.  Every
:meth:`FamilySchedule.thresholds` call returns a fresh frozen mapping, read-only
and never aliased, the stance feature 227's schedule takes restated for the
family dimension.  The composition is a pure function of ``(beta, authored
conditionals)`` — no store, no clock, no configuration — so two replays under
one authored policy answer identically, which is §609's cross-cycle legibility
extended across themes: a score earned under a family threshold is comparable
to one earned under the prior, because both are recorded facts derived from one
scalar and one authoring.

**The seam is duck-typed, and validates what it reads.**  :func:`family_schedule`
accepts any object carrying ``theme_root``, ``evidence`` and ``adjustments``
rather than testing ``isinstance`` — the module loader imports this member under
a synthetic name and re-executes it, so a conditional built from the composed
copy would fail an ``isinstance`` against this module's class, the same hazard
the tree/question seam documents.  But what the seam *reads* it validates: a
text evidence count, a NaN adjustment or an unkeyable theme reaching composition
through a foreign carrier is refused here, in this module's own
:class:`FamilyThresholdError`, rather than escaping as a bare :class:`ValueError`
or silently poisoning every threshold in the table with NaN — an error
vocabulary that leaked through a seam is the leak this member refuses.  The
constructor and the seam share one spelling of each guard (the private
validators below), so "validated at both ends" is one rule read twice, not two
rules that can drift apart.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers`, the
:mod:`collections.abc` and :mod:`types` helpers, and the member's own
:mod:`.errors` and :mod:`.schedule` — the family dimension is built on the one
mapping, so the dependency runs exactly one way.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import FamilyThresholdError
from .schedule import SCHEDULE_KEYS, schedule

__all__ = [
    "PRIOR_STRENGTH",
    "FamilyConditional",
    "FamilySchedule",
    "FamilyThresholdError",
    "family_schedule",
]

#: The shrinkage knob — the weight of evidence at which an authored conditional
#: is trusted at half strength, in the partial-pooling ratio
#: ``evidence / (evidence + PRIOR_STRENGTH)``.
#:
#: This is the whole of §11.1's *"family-specific behaviour shrunk toward a
#: global prior … no hierarchical Bayesian machinery required"*: the ratio is
#: empirical-Bayes shrinkage, and the constant is the prior's equivalent sample
#: size.  Six units of recorded evidence before half trust is the *default
#: parameterization* the dreaming loop's own tuning replaces — stated here as a
#: named constant rather than hidden in the formula, exactly the way feature
#: 227 states its bands, because no document states a number and none is
#: invented beyond a stated default.
PRIOR_STRENGTH = 6.0


def _theme_key(value: object) -> str:
    """Read a conditional's key — a theme_root that can be keyed, or refuse it.

    One spelling of the structural check, shared by the conditional's
    constructor and the composition seam: the key must be a non-empty string,
    because it is the slug ``meta()`` exposes and a theme that cannot be named
    cannot be conditioned.  Deliberately *not* checked against the legal-theme
    set — which themes may exist is feature 241's committed config, and a second
    spelling of a config-bound ceiling is the drift both features exist to
    prevent.  An unknown-but-well-formed key is never an error: it is the
    feature's own headline, answered by the caller's lookup, not by this guard.
    """
    if not isinstance(value, str) or not value.strip():
        raise FamilyThresholdError(
            f"a family conditional must be keyed on a theme_root that is a "
            f"non-empty string, got {value!r} ({type(value).__name__}): the key "
            f"is the structural slug meta() exposes, and a theme that cannot be "
            f"named cannot be conditioned (feature 228, docs §11.1)"
        )
    return value


def _magnitude(value: object, what: str) -> float:
    """Read an authored number — a finite real, or refuse it.

    One spelling of the magnitude check, shared by the constructor and the
    composition seam, and the member's never-coerce stance restated for the
    family dimension: a ``bool`` is refused (a flag is not a magnitude), text is
    refused rather than coerced (coercion is how a mistyped conditional becomes
    a silent episode), and a non-finite value is refused (a NaN compares false
    against everything, so no threshold it adjusts is a threshold; an infinite
    one is a magnitude no authored arithmetic yields).  The conversion's own
    failures are translated into this module's vocabulary rather than escaping
    the seam as a bare :class:`OverflowError`.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise FamilyThresholdError(
            f"{what} must be a real number, got {value!r} "
            f"({type(value).__name__}): a family threshold is authored "
            f"arithmetic over the schedule, and a value that is not a number "
            f"adjusts nothing — text is refused rather than coerced, because "
            f"coercion is how a mistyped conditional becomes a silent episode "
            f"(feature 228, docs §11.1)"
        )
    try:
        scalar = float(value)
    except (OverflowError, ValueError, TypeError) as unconvertible:
        raise FamilyThresholdError(
            f"{what} must be a finite number a float can carry, got "
            f"{value!r}: the composition is arithmetic over authored numbers, "
            f"and a magnitude beyond floating point adjusts no threshold at "
            f"all (feature 228, docs §11.1)"
        ) from unconvertible
    if not math.isfinite(scalar):
        raise FamilyThresholdError(
            f"{what} must be finite, got {value!r}: a NaN compares false "
            f"against everything, so no threshold it adjusts is a threshold, "
            f"and an infinite magnitude is one no authored arithmetic yields "
            f"(feature 228, docs §11.1)"
        )
    return scalar


def _evidence(value: object) -> float:
    """Read a theme's evidence count — a non-negative finite real, or refuse it.

    Evidence accumulates from zero as the dreaming loop records it, so a
    negative count is not evidence but its absence wearing a sign — and in the
    shrinkage ratio it would push a theme *past* its authored position, outside
    the interpolation between prior and author that the prior exists to bound.
    """
    evidence = _magnitude(value, "a theme's evidence")
    if evidence < 0.0:
        raise FamilyThresholdError(
            f"a theme's evidence must be a non-negative magnitude, got "
            f"{value!r}: evidence accumulates from zero as the dreaming loop "
            f"records it, and a negative count would shrink a theme past its "
            f"authored position — outside the interpolation between the prior "
            f"and the author that the shrinkage exists to bound (feature 228, "
            f"docs §11.1)"
        )
    return evidence


def _deltas(adjustments: object) -> dict[str, float]:
    """Read a conditional's adjustments — keyed by the one mapping, or refuse.

    One spelling of the routing law, shared by the constructor and the
    composition seam: every adjustment must name a key the schedule mapping
    carries, because a threshold derived anywhere but through that one mapping
    is a second beta (docs §609) — arriving here through a family key instead
    of a second formula.  The adjustments must also be non-empty: a conditional
    that adjusts nothing conditions nothing, and the theme it names would be
    indistinguishable from one never authored.
    """
    if not isinstance(adjustments, Mapping):
        raise FamilyThresholdError(
            f"a conditional's adjustments must be a mapping of threshold key "
            f"to adjustment, got {adjustments!r} ({type(adjustments).__name__}): "
            f"the composition reads them key by key, and a value that is not a "
            f"mapping cannot be read that way (feature 228, docs §11.1)"
        )
    deltas: dict[str, float] = {}
    for key, raw in adjustments.items():
        if key not in SCHEDULE_KEYS:
            raise FamilyThresholdError(
                f"a conditional may adjust only the thresholds the one "
                f"schedule mapping carries, and {key!r} is not one of them: a "
                f"threshold derived anywhere but through schedule(beta) is a "
                f"second beta, the drift the single-scalar discipline exists "
                f"to prevent, arriving through a family key (features 227 and "
                f"228, docs §609)"
            )
        deltas[key] = _magnitude(raw, "an adjustment")
    if not deltas:
        raise FamilyThresholdError(
            "a family conditional must adjust at least one threshold, got "
            "none: a conditional that adjusts nothing conditions nothing, and "
            "the theme it names would be indistinguishable from one never "
            "authored — the vacuous entry the table refuses (feature 228)"
        )
    return deltas


@dataclass(frozen=True)
class FamilyConditional:
    """One theme's authored conditional — the deviations and the evidence.

    The authored half of feature 228: what a policy-development agent writes
    where §11.2 says no classifier may stand.  A conditional is *plain
    arithmetic authored in advance* — an additive adjustment per threshold the
    theme's §4.5 signature inverts or shifts, plus the count of evidence the
    dreaming loop has recorded under the theme — and nothing else.  The
    composition anchors every adjustment at the schedule's beta-derived value,
    so the conditional is the *deviation* from the schedule rather than a
    second dict of absolute thresholds: an absolute table would stand still
    while beta moved, and a family threshold that no longer moves with the
    scalar is the second beta this member refuses.

    Frozen and validated in :meth:`__post_init__`, and the adjustments are
    copied into a read-only mapping — never aliased to the dict the conditional
    was authored from — so a conditional once composed cannot be moved by a
    caller that keeps writing its authoring dict.  ``evidence`` defaults to
    zero, the universal starting state: a conditional may be authored for a
    theme before any evidence exists, and until evidence accumulates the theme
    answers the prior — authored intent, no evidence, prior answer, which is
    the safe direction for a default.

    Fields:

    * **``theme_root``** — the theme the conditional conditions, the structural
      slug ``meta()`` exposes.  A non-empty string; the *legal* set is feature
      241's config, deliberately not restated here.
    * **``adjustments``** — ``{threshold key: additive delta}``, every key one
      of :data:`SCHEDULE_KEYS`, every value a finite real.  Partial is
      legitimate (a theme conditions the thresholds that invert for it); empty
      is refused.
    * **``evidence``** — how much evidence the theme has accumulated, in
      whatever unit the dreaming loop records.  A non-negative finite real;
      the shrinkage weight is derived from it, never authored directly.
    """

    theme_root: str
    adjustments: Mapping[str, float]
    evidence: float = 0.0

    def __post_init__(self) -> None:
        # One spelling of each guard, shared with the composition seam: the
        # constructor validates the authored form it was handed, and the seam
        # validates what it reads — the same private validators, so the rule
        # cannot drift between the two ends.
        theme_root = _theme_key(self.theme_root)
        deltas = _deltas(self.adjustments)
        evidence = _evidence(self.evidence)
        object.__setattr__(self, "theme_root", theme_root)
        # A fresh mapping over the validated deltas, never the author's dict:
        # the conditional is a recorded authoring, not a view onto whatever the
        # caller is still writing.
        object.__setattr__(self, "adjustments", MappingProxyType(deltas))
        object.__setattr__(self, "evidence", evidence)


class FamilySchedule:
    """The theme-keyed threshold lookup — feature 228's composed surface.

    Built once from the episode's beta and the policy's authored conditionals,
    and answering one question thereafter: *what thresholds does this theme
    explore under?*  A theme carrying evidence answers the schedule's global
    thresholds adjusted by its weighted conditional — differentiated, shrunk
    toward the prior by how much evidence backs it.  A theme carrying no
    evidence yet answers the global default itself, so a campaign opening a
    theme the pool has never seen starts at the prior — §11.1's law as a lookup
    fact rather than a configuration step.

    The composition happens once, here in ``__init__``: the one mapping is
    derived (through :func:`schedule`, the only road to a threshold), each
    conditional's weight is computed from its evidence, and each authored
    theme's thresholds are interpolated and frozen into the table.  Every
    answer afterwards is a read of that recorded state — a fresh read-only
    mapping per call, never a shared dict — so the lookup is deterministic and
    pure: the same beta and the same authored numbers answer identically,
    however often and in whatever order the themes are asked.
    """

    __slots__ = ("_beta", "_default", "_table")

    def __init__(
        self,
        beta: float,
        conditionals: Iterable[FamilyConditional] = (),
    ) -> None:
        # The conditionals are typed as FamilyConditional but checked
        # duck-typed, for the reason the tree/question seam documents: the
        # module loader imports this member under a synthetic name and
        # re-executes it, so a conditional built from the composed copy is a
        # second FamilyConditional class object and an isinstance here would
        # refuse the very authoring create_app() would front.  What the seam
        # reads, it validates — in this module's own vocabulary.
        if isinstance(conditionals, (str, bytes)) or not isinstance(
            conditionals, Iterable
        ):
            raise FamilyThresholdError(
                f"family conditioning arrives as an iterable of authored "
                f"conditionals, got {conditionals!r} "
                f"({type(conditionals).__name__}): the composition reads them "
                f"one by one, and a string is a theme key, not a conditional "
                f"(feature 228, docs §11.1)"
            )
        # The one mapping, derived here — the only road to a threshold, so the
        # family table is anchored at exactly what the schedule carries.
        default = dict(schedule(beta))
        table: dict[str, dict[str, float]] = {}
        for item in conditionals:
            if not (
                hasattr(item, "theme_root")
                and hasattr(item, "evidence")
                and hasattr(item, "adjustments")
            ):
                raise FamilyThresholdError(
                    f"a conditional carries theme_root, evidence and "
                    f"adjustments, got {item!r} ({type(item).__name__}): the "
                    f"composition reads exactly those three, and an object "
                    f"carrying none of them names no conditioning (feature 228)"
                )
            key = _theme_key(item.theme_root)
            deltas = _deltas(item.adjustments)
            evidence = _evidence(item.evidence)
            if key in table:
                raise FamilyThresholdError(
                    f"two conditionals are keyed on theme_root {key!r}: which "
                    f"one wins is not a question the schedule answers "
                    f"silently — a theme carries one authored conditional, and "
                    f"a second is a resubmission, not an update (feature 228)"
                )
            # Partial pooling without the machinery: the weight rises with the
            # evidence from exactly zero (a new theme, at the prior) toward —
            # never reaching — full trust in the authored deviation.
            weight = evidence / (evidence + PRIOR_STRENGTH)
            table[key] = {
                threshold: default[threshold] + weight * deltas.get(threshold, 0.0)
                for threshold in SCHEDULE_KEYS
            }
        self._beta = float(beta)
        self._default = default
        self._table = table

    @property
    def beta(self) -> float:
        """The scalar the conditioning was composed over — read-only."""
        return self._beta

    @property
    def default(self) -> Mapping[str, float]:
        """The global default — the one mapping, as a fresh frozen mapping.

        The prior every theme starts at: exactly what
        :func:`policy_runtime.schedule` derives from this schedule's own beta,
        read here so a caller never has to re-derive it (and never could
        re-derive it differently — there is one road to a threshold).
        """
        return MappingProxyType(dict(self._default))

    @property
    def theme_roots(self) -> frozenset[str]:
        """The themes carrying authored conditionals — the table's keys.

        A diagnostic reading, not a gate: a theme absent here is not an error
        but a theme answering the global default, and this property is how an
        operator tells the two apart in a report.
        """
        return frozenset(self._table)

    def thresholds(self, theme_root: str) -> Mapping[str, float]:
        """The thresholds a theme explores under — its conditional, shrunk.

        The feature's verb.  A theme the table carries answers its composed
        thresholds — the global mapping adjusted by the weighted conditional,
        every one of :data:`SCHEDULE_KEYS` present, never partial.  Any other
        theme — one never authored, or authored with no evidence yet — answers
        the global default itself: a new theme starts at the prior, and
        differentiates only as evidence accumulates.  The key is read with the
        same structural guard the conditional was keyed with (a non-empty
        string; the legal set is feature 241's, not this lookup's), and the
        answer is a fresh frozen mapping per call, so a caller that holds one
        holds the thresholds as they were composed and cannot move them.
        """
        key = _theme_key(theme_root)
        values = self._table.get(key, self._default)
        return MappingProxyType(dict(values))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FamilySchedule(beta={self._beta!r}, "
            f"themes={sorted(self._table)!r})"
        )


def family_schedule(
    beta: float,
    conditionals: Iterable[FamilyConditional] = (),
) -> FamilySchedule:
    """Compose the family-conditional schedule — one beta, one authoring.

    The one factory verb, the spelling a runtime reads best at the top of an
    episode: the episode's scalar plus the policy's authored conditionals
    compose into the :class:`FamilySchedule` every theme lookup goes through
    thereafter.  The conditional half may be empty — a policy that has authored
    no conditioning yet composes a schedule that answers the global default for
    every theme, which is the honest starting state, not a vacuous one: the
    prior is where every theme begins.

    Pure: the composition consults no store, no clock and no configuration —
    it is a function of the scalar and the authored numbers and nothing else —
    so the same authoring under the same beta composes the same thresholds on
    every replay, which is §609's cross-cycle legibility holding across the
    family dimension.  Constructing through the verb and through the class are
    the same act, exactly as :func:`policy_runtime.policy_question` fronts
    :class:`PolicyQuestion`.
    """
    return FamilySchedule(beta, conditionals)
