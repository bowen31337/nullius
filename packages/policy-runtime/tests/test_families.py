"""Feature 228, family conditioning — thresholds keyed on ``theme_root``.

The invariants these tests pin are the ones the "family-conditional, shrunk
toward a global default, policy-authored" guarantee depends on:

* **a theme carrying no evidence yet answers the global default** — the
  feature's own sentence: a theme the table does not carry answers
  :func:`schedule`'s mapping to the value, and so does a theme authored with
  zero evidence (a new theme starts at the prior, even when the conditional is
  already written), so a campaign opening a theme the pool has never seen
  explores under the prior;
* **the lookup is keyed on ``theme_root``** — two themes answer their own
  conditionals, never a blend; a key that cannot be keyed (blank, not a
  string) is refused, while an unknown key is not an error but the headline;
* **thresholds differentiate as evidence accumulates, shrunk toward the
  prior** — the weight is ``evidence / (evidence + PRIOR_STRENGTH)``: it rises
  monotonically from exactly zero, interpolates the authored deviation between
  the prior and the authored position (never past it, never at full strength
  for finite evidence), and trusts a conditional at half strength exactly when
  the evidence reaches the prior strength;
* **every family threshold is still routed through the one schedule mapping**
  — the composition calls :func:`schedule` and anchors there, so family
  thresholds move when beta moves, an adjustment naming a key outside
  :data:`SCHEDULE_KEYS` is refused as a second beta, and every answer carries
  all four keys (the family path cannot narrow the schedule);
* **the conditioning is authored, not fitted** — the input is plain floats
  (an adjustment per threshold, an evidence count per theme) and the
  composition is pure arithmetic over them: deterministic across calls, never
  consulting anything else, which is the §11.2 deferral's positive half — the
  thing feature 231's refusal says the policy writes instead;
* **the authored form is validated, and the seam validates what it reads** —
  text, ``bool``, NaN and infinite magnitudes are refused rather than coerced
  at authoring; a duck-typed carrier reaching composition with one is refused
  there too, in this member's own vocabulary, so no ``ValueError`` and no
  silent NaN leaks through the seam.

The headline case is the feature's own sentence: a theme carrying no evidence
yet reads the global default, and differentiates only as evidence accumulates.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest
from policy_runtime import (
    EXPLORE_EXPLOIT,
    OVERFIT_AVERSION,
    PATIENCE,
    PRIOR_STRENGTH,
    PRUNE_AGGRESSIVENESS,
    SCHEDULE_KEYS,
    FamilyConditional,
    FamilySchedule,
    FamilyThresholdError,
    PolicyRuntimeError,
    family_schedule,
    schedule,
)

# The themes the tests condition, named once so the cases read as claims about
# families rather than as spellings of slugs.
MOMENTUM = "cross-sectional-momentum"
EVENTS = "event-driven-listings"


class _StubConditional:
    """A duck-typed conditional — the shape the composition seam accepts.

    Carries exactly the three attributes :func:`family_schedule` reads, and
    nothing else, so the seam tests can hand it values the real value type
    would have refused at construction — the loader's double-import makes the
    seam duck-typed, which makes what it reads the seam's business to check.
    """

    def __init__(
        self,
        theme_root: object,
        adjustments: object,
        evidence: object,
    ) -> None:
        self.theme_root = theme_root
        self.adjustments = adjustments
        self.evidence = evidence


# ---------------------------------------------------------------------------
# A theme carrying no evidence yet answers the global default
# ---------------------------------------------------------------------------


def test_a_theme_carrying_no_evidence_answers_the_global_default() -> None:
    # The feature's own sentence: keyed on theme_root, a theme carrying no
    # evidence yet returns the global default — the one mapping the schedule
    # derives, to the value, so a campaign opening a theme the pool has never
    # seen explores under the prior.
    family = family_schedule(
        0.7,
        [FamilyConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: -0.2}, evidence=6.0)],
    )
    unseen = family.thresholds(EVENTS)
    prior = schedule(0.7)
    for key in SCHEDULE_KEYS:
        assert unseen[key] == prior[key]


def test_the_default_answer_carries_all_four_thresholds() -> None:
    # Never a subset — the family path cannot narrow the schedule, so even the
    # default answer for a never-seen theme carries the whole set.
    unseen = family_schedule(0.5).thresholds("a-theme-never-conditioned")
    assert set(unseen) == set(SCHEDULE_KEYS)


def test_an_authored_theme_with_zero_evidence_still_answers_the_prior() -> None:
    # "A new theme starts at the prior": the conditional may be authored before
    # any evidence exists, and until evidence accumulates the theme answers the
    # global default exactly — authored intent, no evidence, prior answer.
    conditional = FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: 0.25})
    assert conditional.evidence == 0.0
    themed = family_schedule(0.7, [conditional]).thresholds(MOMENTUM)
    prior = schedule(0.7)
    for key in SCHEDULE_KEYS:
        assert themed[key] == prior[key]


def test_the_default_property_is_the_schedule_mapping() -> None:
    # The prior every theme starts at is exactly what schedule(beta) derives —
    # one road to a threshold, and the family dimension reads it, not a second
    # derivation of it.
    assert dict(family_schedule(0.35).default) == dict(schedule(0.35))


def test_the_default_answer_is_frozen() -> None:
    # A threshold is a recorded fact; the mapping a caller holds must not move.
    unseen = family_schedule(0.5).thresholds(EVENTS)
    assert isinstance(unseen, MappingProxyType)
    with pytest.raises(TypeError):
        unseen[EXPLORE_EXPLOIT] = 0.9


def test_two_lookups_never_alias() -> None:
    # A fresh mapping per call, never a shared one — the value-type stance the
    # schedule takes, restated for the family dimension.
    family = family_schedule(0.5)
    assert family.thresholds(EVENTS) is not family.thresholds(EVENTS)
    assert family.thresholds(EVENTS) == family.thresholds(EVENTS)


def test_no_conditionals_at_all_answers_the_prior_for_every_theme() -> None:
    # A policy that has authored no conditioning yet composes a schedule that
    # answers the global default for every theme — the honest starting state,
    # not a vacuous one: the prior is where every theme begins.
    family = family_schedule(0.6, [])
    for theme in (MOMENTUM, EVENTS, "microstructure"):
        assert dict(family.thresholds(theme)) == dict(schedule(0.6))


# ---------------------------------------------------------------------------
# Keyed on theme_root
# ---------------------------------------------------------------------------


def test_two_themes_answer_their_own_conditionals() -> None:
    # A keyed lookup, not a blend: two themes carrying different conditionals
    # answer different thresholds, each its own.
    family = family_schedule(
        0.5,
        [
            FamilyConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: -0.2}, evidence=6.0),
            FamilyConditional(EVENTS, {PRUNE_AGGRESSIVENESS: 0.2}, evidence=6.0),
        ],
    )
    momentum = family.thresholds(MOMENTUM)[PRUNE_AGGRESSIVENESS]
    events = family.thresholds(EVENTS)[PRUNE_AGGRESSIVENESS]
    prior = schedule(0.5)[PRUNE_AGGRESSIVENESS]
    assert momentum < prior < events


def test_theme_roots_names_the_authored_themes() -> None:
    # A diagnostic reading, not a gate: the property names the themes carrying
    # authored conditionals, so an operator can tell a differentiated theme
    # from one answering the default.
    family = family_schedule(
        0.5,
        [FamilyConditional(MOMENTUM, {PATIENCE: 1.0}, evidence=3.0)],
    )
    assert family.theme_roots == frozenset({MOMENTUM})
    assert EVENTS not in family.theme_roots


def test_a_blank_theme_key_is_refused_at_lookup() -> None:
    # The key is the slug meta() exposes; a theme that cannot be named cannot
    # be looked up — refused, not normalised.
    with pytest.raises(FamilyThresholdError, match="non-empty string"):
        family_schedule(0.5).thresholds("   ")


def test_a_non_string_theme_key_is_refused_at_lookup() -> None:
    # The same guard from the other side: a node id or a None is not a slug.
    with pytest.raises(FamilyThresholdError, match="non-empty string"):
        family_schedule(0.5).thresholds(7)


# ---------------------------------------------------------------------------
# Differentiation: shrunk toward the global default as evidence accumulates
# ---------------------------------------------------------------------------


def test_a_theme_differentiates_only_as_evidence_accumulates() -> None:
    # The weight rises monotonically with the evidence, so the theme's distance
    # from the prior grows strictly as evidence accumulates — never jumping to
    # the authored position, always walking toward it.
    prior = schedule(0.5)[EXPLORE_EXPLOIT]
    distances = []
    for evidence in (0.0, 1.5, 6.0, 24.0):
        family = family_schedule(
            0.5, [FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: 0.25}, evidence=evidence)]
        )
        distances.append(abs(family.thresholds(MOMENTUM)[EXPLORE_EXPLOIT] - prior))
    assert distances[0] == 0.0
    assert distances == sorted(distances)
    assert len(set(distances)) == len(distances)


def test_the_family_threshold_interpolates_between_prior_and_author() -> None:
    # "Shrunk toward a global default": the answer sits strictly between the
    # prior and the authored position, never past it — the interpolation the
    # prior exists to bound, pinned for a rising and a falling delta alike.
    for delta in (0.25, -0.25):
        family = family_schedule(
            0.5, [FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: delta}, evidence=4.0)]
        )
        composed = family.thresholds(MOMENTUM)[EXPLORE_EXPLOIT]
        prior = schedule(0.5)[EXPLORE_EXPLOIT]
        assert min(prior, prior + delta) < composed < max(prior, prior + delta)


def test_half_strength_exactly_at_the_prior_strength() -> None:
    # PRIOR_STRENGTH is the knob's definition: evidence equal to it trusts the
    # conditional at half strength.  beta 0 makes the prior exactly 0.5 and the
    # delta 0.25 exact in binary, so the arithmetic is exact: 0.5 + 0.5*0.25.
    family = family_schedule(
        0.0, [FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: 0.25}, evidence=PRIOR_STRENGTH)]
    )
    assert family.thresholds(MOMENTUM)[EXPLORE_EXPLOIT] == 0.625


def test_evidence_is_never_trusted_at_full_strength() -> None:
    # The ratio n / (n + k) never reaches one for finite n, so even a billion
    # units of evidence leaves the theme just short of its authored position —
    # the shrinkage never fully lets go.
    family = family_schedule(
        0.0, [FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: 0.25}, evidence=1e9)]
    )
    composed = family.thresholds(MOMENTUM)[EXPLORE_EXPLOIT]
    assert composed == pytest.approx(0.75, abs=1e-6)
    assert composed < 0.75


def test_negative_evidence_is_refused() -> None:
    # Evidence accumulates from zero; a negative count would shrink a theme
    # past its authored position, outside the interpolation the prior bounds.
    with pytest.raises(FamilyThresholdError, match="non-negative"):
        FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: 0.25}, evidence=-3.0)


def test_non_magnitude_evidence_is_refused() -> None:
    # Text is refused rather than coerced (coercion is how a mistyped
    # conditional becomes a silent episode), a bool is a flag not a magnitude,
    # and a NaN evidence shrinks no threshold toward anything.
    for bad in ("3", True, None, float("nan"), float("inf")):
        with pytest.raises(FamilyThresholdError):
            FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: 0.25}, evidence=bad)


def test_evidence_accepts_an_integer_count() -> None:
    # Evidence arrives as a count the dreaming loop recorded; an int and its
    # float spelling are one magnitude, exactly as beta's grid points are.
    by_int = family_schedule(
        0.5, [FamilyConditional(MOMENTUM, {PATIENCE: 1.0}, evidence=3)]
    )
    by_float = family_schedule(
        0.5, [FamilyConditional(MOMENTUM, {PATIENCE: 1.0}, evidence=3.0)]
    )
    assert dict(by_int.thresholds(MOMENTUM)) == dict(by_float.thresholds(MOMENTUM))


# ---------------------------------------------------------------------------
# Routed through the one schedule mapping
# ---------------------------------------------------------------------------


def test_an_adjustment_outside_the_one_mapping_is_refused() -> None:
    # A threshold derived anywhere but through schedule(beta) is a second beta
    # — the drift the single-scalar discipline exists to prevent, arriving here
    # through a family key.  The refusal names the offending key.
    with pytest.raises(FamilyThresholdError, match="second beta"):
        FamilyConditional(MOMENTUM, {"gini_concentration": 0.2})


def test_family_thresholds_move_with_beta() -> None:
    # Anchored at the schedule: the authored part is the deviation from it, so
    # moving the scalar moves the family thresholds with it — they cannot drift
    # independently of the one number the episode was opened on.
    conditional = FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: 0.25}, evidence=6.0)
    low = family_schedule(0.2, [conditional]).thresholds(MOMENTUM)[EXPLORE_EXPLOIT]
    high = family_schedule(1.8, [conditional]).thresholds(MOMENTUM)[EXPLORE_EXPLOIT]
    assert high > low


def test_a_partial_conditional_leaves_the_other_thresholds_at_the_prior() -> None:
    # A theme conditions the thresholds whose meaning inverts for it — partial
    # is legitimate.  Every key the conditional does not carry stays at the
    # schedule's value exactly, and the answer still carries all four keys.
    family = family_schedule(
        0.5, [FamilyConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: -0.2}, evidence=6.0)]
    )
    themed = family.thresholds(MOMENTUM)
    prior = schedule(0.5)
    assert themed[PRUNE_AGGRESSIVENESS] != prior[PRUNE_AGGRESSIVENESS]
    for key in (EXPLORE_EXPLOIT, PATIENCE, OVERFIT_AVERSION):
        assert themed[key] == prior[key]


def test_the_composition_is_deterministic() -> None:
    # Authored, not fitted: the same beta and the same authored numbers answer
    # identically every time — no store, no clock, no model — so a replay under
    # one authored policy is legible across cycles and across themes.
    conditional = FamilyConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: -0.2}, evidence=6.0)
    readings = [
        dict(family_schedule(0.5, [conditional]).thresholds(MOMENTUM)) for _ in range(50)
    ]
    for reading in readings[1:]:
        assert reading == readings[0]


def test_the_answer_is_pure_arithmetic_over_the_authored_numbers() -> None:
    # The composition is addition: the schedule's value plus the weighted
    # authored deviation.  A test computing it independently must agree to the
    # bit — there is nothing else in the composition to disagree with.
    evidence = 4.0
    delta = -0.2
    family = family_schedule(
        0.7, [FamilyConditional(EVENTS, {PRUNE_AGGRESSIVENESS: delta}, evidence=evidence)]
    )
    weight = evidence / (evidence + PRIOR_STRENGTH)
    expected = schedule(0.7)[PRUNE_AGGRESSIVENESS] + weight * delta
    assert family.thresholds(EVENTS)[PRUNE_AGGRESSIVENESS] == expected


def test_the_conditional_is_frozen_and_copies_its_adjustments() -> None:
    # The conditional is a recorded authoring: no field can be reassigned, and
    # the adjustments are copied into a read-only mapping — a caller that keeps
    # writing its authoring dict cannot move a conditional already composed.
    authored = {PRUNE_AGGRESSIVENESS: -0.2}
    conditional = FamilyConditional(MOMENTUM, authored, evidence=6.0)
    with pytest.raises(FrozenInstanceError):
        conditional.evidence = 12.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        conditional.adjustments[PRUNE_AGGRESSIVENESS] = -0.9  # type: ignore[index]
    authored[PRUNE_AGGRESSIVENESS] = -0.9
    family = family_schedule(0.5, [conditional])
    expected = schedule(0.5)[PRUNE_AGGRESSIVENESS] + 0.5 * -0.2
    assert family.thresholds(MOMENTUM)[PRUNE_AGGRESSIVENESS] == expected


def test_family_schedule_and_the_class_are_the_same_act() -> None:
    # The verb is the named spelling of the constructor, nothing more — the
    # same shape policy_question fronts PolicyQuestion.
    conditional = FamilyConditional(MOMENTUM, {PATIENCE: 1.0}, evidence=2.0)
    by_verb = family_schedule(0.4, [conditional])
    by_class = FamilySchedule(0.4, [conditional])
    assert dict(by_verb.thresholds(MOMENTUM)) == dict(by_class.thresholds(MOMENTUM))
    assert by_verb.beta == by_class.beta == 0.4


# ---------------------------------------------------------------------------
# Authored magnitudes are validated, never coerced
# ---------------------------------------------------------------------------


def test_a_text_adjustment_is_refused_rather_than_coerced() -> None:
    with pytest.raises(FamilyThresholdError, match="real number"):
        FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: "0.2"})


def test_a_bool_adjustment_is_refused() -> None:
    # True is an int and would quietly adjust by 1.0 — a flag is not a
    # magnitude, exactly as feature 226 refuses a bool beta.
    with pytest.raises(FamilyThresholdError, match="real number"):
        FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: True})


def test_a_non_finite_adjustment_is_refused() -> None:
    # A NaN compares false against everything, so no threshold it adjusts is a
    # threshold; an infinite adjustment is a magnitude no authoring yields.
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(FamilyThresholdError, match="finite"):
            FamilyConditional(MOMENTUM, {EXPLORE_EXPLOIT: bad})


def test_an_empty_conditional_is_refused() -> None:
    # A conditional that adjusts nothing conditions nothing — the theme it
    # names would be indistinguishable from one never authored.
    with pytest.raises(FamilyThresholdError, match="at least one threshold"):
        FamilyConditional(MOMENTUM, {})


def test_a_blank_theme_root_is_refused_at_authoring() -> None:
    # The same structural guard the lookup applies, applied where the
    # conditional is authored: a theme that cannot be named cannot be keyed.
    for bad in ("", "   ", 7, None):
        with pytest.raises(FamilyThresholdError, match="non-empty string"):
            FamilyConditional(bad, {EXPLORE_EXPLOIT: 0.25})  # type: ignore[arg-type]


def test_adjustments_that_are_not_a_mapping_are_refused() -> None:
    with pytest.raises(FamilyThresholdError, match="mapping"):
        FamilyConditional(MOMENTUM, [(-0.2, PRUNE_AGGRESSIVENESS)])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# The seam is duck-typed, and validates what it reads
# ---------------------------------------------------------------------------


def test_two_conditionals_for_one_theme_are_refused() -> None:
    # Which one wins is not a question the schedule answers silently — a theme
    # carries one authored conditional, and a second is a resubmission.
    with pytest.raises(FamilyThresholdError, match="two conditionals"):
        family_schedule(
            0.5,
            [
                FamilyConditional(MOMENTUM, {PATIENCE: 1.0}, evidence=2.0),
                FamilyConditional(MOMENTUM, {PATIENCE: 3.0}, evidence=4.0),
            ],
        )


def test_a_string_is_not_an_iterable_of_conditionals() -> None:
    # A string is a theme key, not a conditional — refused as the whole
    # argument rather than iterated into five broken lookups.
    with pytest.raises(FamilyThresholdError, match="iterable"):
        family_schedule(0.5, MOMENTUM)  # type: ignore[arg-type]


def test_a_non_conditional_item_is_refused() -> None:
    with pytest.raises(FamilyThresholdError, match="carries theme_root"):
        family_schedule(0.5, [MOMENTUM])  # type: ignore[list-item]


def test_a_duck_typed_conditional_composes() -> None:
    # The composition seam is duck-typed — the module loader imports this
    # member under a synthetic name and re-executes it, so the composed copy's
    # conditionals are a second class object an isinstance would refuse.  A
    # carrier with the three read attributes composes identically.
    stub = _StubConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: -0.2}, 6.0)
    real = FamilyConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: -0.2}, evidence=6.0)
    assert dict(family_schedule(0.5, [stub]).thresholds(MOMENTUM)) == dict(
        family_schedule(0.5, [real]).thresholds(MOMENTUM)
    )


def test_the_seam_refuses_a_duck_typed_text_evidence() -> None:
    # What the seam reads, it validates: a text evidence reaching composition
    # through a foreign carrier is refused in this member's vocabulary — not
    # escaped as a ValueError, not coerced into an episode.
    stub = _StubConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: -0.2}, "6.0")
    with pytest.raises(FamilyThresholdError, match="real number"):
        family_schedule(0.5, [stub])


def test_the_seam_refuses_a_duck_typed_nan_adjustment() -> None:
    # The same defence for the adjustments: a NaN reaching the seam through a
    # carrier that skipped the constructor must not poison the table.
    stub = _StubConditional(MOMENTUM, {PRUNE_AGGRESSIVENESS: float("nan")}, 6.0)
    with pytest.raises(FamilyThresholdError, match="finite"):
        family_schedule(0.5, [stub])


def test_the_seam_refuses_a_duck_typed_adjustments_non_mapping() -> None:
    stub = _StubConditional(MOMENTUM, [PRUNE_AGGRESSIVENESS], 6.0)
    with pytest.raises(FamilyThresholdError, match="mapping"):
        family_schedule(0.5, [stub])


def test_every_refusal_is_a_policy_runtime_error() -> None:
    # One base class catches every failure of the path — the single-except
    # discipline this member's error tree states.
    with pytest.raises(PolicyRuntimeError):
        FamilyConditional(MOMENTUM, {"gini_concentration": 0.2})
    with pytest.raises(PolicyRuntimeError):
        family_schedule(0.5).thresholds("")
