"""Feature 266's law — sensitivity and specificity over the planted
nulls, answered as the base-rate independent pair.

*System computes sensitivity and specificity on planted nulls, which
returns both as base-rate independent figures* (app_spec.xml,
"Objective Scoring & CVaR Aggregation").  prd §4.1.3 states the clause
the tests are organized around (line 144): *"Sensitivity and
specificity are base-rate independent, so measure them where you have
power for both, then reweight"* — and this suite pins it at every face
it has:

* **the answer's shape** — one value, two separately named figures,
  and deliberately no third: nothing that divides by the declaration's
  size, no counts, no base rate;
* **the figures** — the four cells over the planted population against
  the claimed picks, hand-computed on the fixture campaign (every
  quotient dyadic, checkable with ``==``), the declaration a *set*
  where the rate's ask is a multiset, and the empty declaration
  answered (``0.0`` and ``1.0``) where the rate's empty ask is
  refused;
* **base-rate independence itself** — the fixture plant widened by two
  nulls, the within-class behaviour held fixed: the figures cannot
  move, and the rate must;
* **the barrier** — the reads are the population's canonical ids, once
  each, in handed order, and the picks are never read at all; a
  refused ask touches no label; no label-shaped anything crosses out;
* **the refusals** — this seam's own vocabulary for the population and
  the pair's laws, feature 265's vocabulary propagated untranslated
  for the pick law it owns, and §4.1.1's floor held as refusals on
  both one-sided plants.

The fixtures come from the suite's conftest: the recording stand-in
sidecar, the four-address planted campaign (two nulls, two reals), and
the two further null addresses the base-rate test widens the plant
with.  The process is feature 265's own class throughout — the verb
under test is the one the process's law reserved room for.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local
    NULL_FOUR,
    NULL_ONE,
    NULL_THREE,
    NULL_TWO,
    REAL_ONE,
    REAL_TWO,
    UNHELD,
    StandInPick,
    StandInSidecar,
)
from scoring import (
    CalibrationFigures,
    CalibrationFiguresError,
    NullPickRateError,
    NullPickScorer,
    ScoringError,
)


@pytest.fixture
def scorer(sidecar: StandInSidecar) -> NullPickScorer:
    """The real process over the conftest's recording stand-in sidecar —
    feature 265's own class, so the figures' ask runs the read law it
    will run in a deployment, and the sidecar's log is the one the
    barrier tests below read."""
    return NullPickScorer(sidecar)


# -- The answer's shape ----------------------------------------------------------


def test_the_answer_is_two_figures_and_no_third(
    scorer: NullPickScorer, planted_population: list[str]
) -> None:
    # The closing clause, read off the answer's type: two separately
    # named fields — sensitivity and specificity — each a bare float,
    # and nothing besides.  No third figure to conflate into, no count
    # of either class (the process lets figures out, never a census),
    # nothing that divides by the declaration's size, and no base rate:
    # π₀ is feature 267's constant, and a verb that took it would let
    # the caller fold 267's projection into the measurement 267 exists
    # to project from.
    figures = scorer.calibration_figures(planted_population, picks=[NULL_ONE, REAL_ONE])
    assert isinstance(figures, CalibrationFigures)
    assert [field.name for field in dataclasses.fields(figures)] == [
        "sensitivity",
        "specificity",
    ]
    for field in dataclasses.fields(figures):
        assert type(getattr(figures, field.name)) is float
    # Frozen, and equal by its figures: a measurement already made is a
    # value a report holds, not a handle a caller edits.
    with pytest.raises(dataclasses.FrozenInstanceError):
        figures.sensitivity = 1.0  # type: ignore[misc]
    assert figures == CalibrationFigures(sensitivity=0.5, specificity=0.5)


def test_hand_built_values_answer_to_the_same_law() -> None:
    # Every field is validated at construction — the stance the world
    # score takes and every value after it inherits — so a value built
    # by the verb and one built by hand answer identically to the law.
    assert CalibrationFigures(0, 1) == CalibrationFigures(0.0, 1.0)
    for bad in (1.5, -0.25, float("nan"), float("inf"), "0.5", True):
        with pytest.raises(CalibrationFiguresError):
            CalibrationFigures(bad, 0.5)  # type: ignore[arg-type]
        with pytest.raises(CalibrationFiguresError):
            CalibrationFigures(0.5, bad)  # type: ignore[arg-type]
    for good in (0, 1, 0.5):
        assert isinstance(CalibrationFigures(good, good).sensitivity, float)
    # The refusal names the field it refused, because the two figures
    # are different measurements with the same shape.
    with pytest.raises(CalibrationFiguresError) as narrowed:
        CalibrationFigures(0.5, 47)
    assert "specificity" in str(narrowed.value)
    assert "a *count*" in str(narrowed.value)
    # And the family catches under the member's one base, so a caller's
    # single except holds for the whole vocabulary.
    assert issubclass(CalibrationFiguresError, ScoringError)


# -- The figures over the campaign -------------------------------------------------


def test_the_pair_over_the_fixture_campaign(
    scorer: NullPickScorer, planted_population: list[str]
) -> None:
    # The four cells by hand: claiming one null and one real of the
    # 2-null/2-real plant — TP=1, FN=1, TN=1, FP=1 — both figures 1/2
    # exactly (dyadic, one division each, checkable with ==).
    figures = scorer.calibration_figures(planted_population, picks=[NULL_ONE, REAL_ONE])
    assert figures.sensitivity == 0.5
    assert figures.specificity == 0.5


def test_every_declaration_answers_its_own_dyadic_pair(
    scorer: NullPickScorer, planted_population: list[str]
) -> None:
    # Every cell count the fixture plant admits, each quotient dyadic:
    # from the all-claimed campaign (sensitivity 1.0, specificity 0.0 —
    # everything found, everything declared against) to the clean one
    # (both reals only — nothing wrongly declared, everything found).
    declarations = [
        ([NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO], 1.0, 0.0),
        ([REAL_ONE, REAL_TWO], 1.0, 1.0),
        ([REAL_ONE], 0.5, 1.0),
        ([NULL_ONE, NULL_TWO, REAL_ONE], 0.5, 0.0),
        ([NULL_ONE, REAL_TWO], 0.5, 0.5),
    ]
    for picks, sensitivity, specificity in declarations:
        answered = scorer.calibration_figures(planted_population, picks=picks)
        assert answered.sensitivity == sensitivity, picks
        assert answered.specificity == specificity, picks
    # The address and value spellings of a pick claim the same node.
    by_value = scorer.calibration_figures(
        planted_population, picks=[StandInPick(NULL_ONE), StandInPick(REAL_ONE)]
    )
    assert by_value == CalibrationFigures(sensitivity=0.5, specificity=0.5)


def test_the_empty_declaration_is_answered_not_refused(
    scorer: NullPickScorer, planted_population: list[str]
) -> None:
    # A campaign that committed to nothing is the corner measurement:
    # none of the reals found (0.0) and none of the nulls wrongly
    # declared (1.0).  Deliberately NOT the rate's stance — an empty
    # pick collection there is 0/0 and refused — because these
    # denominators are the planted classes, and both classes exist.
    figures = scorer.calibration_figures(planted_population, picks=[])
    assert figures.sensitivity == 0.0
    assert figures.specificity == 1.0


def test_the_declaration_is_a_set_where_the_rate_is_a_multiset(
    scorer: NullPickScorer, planted_population: list[str]
) -> None:
    # Two replays committing to one node are two picks for the rate and
    # one discovery for these figures: the same collection reads 2/3
    # under the rate verb (two null picks of three) and 1/2 under this
    # one (one of two nulls declared, one of two reals found) — the
    # two laws stated side by side off one process, neither restating
    # the other.
    picks = [NULL_ONE, NULL_ONE, REAL_ONE]
    assert scorer.null_pick_rate(picks) == 2 / 3
    figures = scorer.calibration_figures(planted_population, picks=picks)
    assert figures == CalibrationFigures(sensitivity=0.5, specificity=0.5)


# -- Base-rate independence — the feature's own clause -----------------------------


def test_both_figures_are_base_rate_independent() -> None:
    # The clause as an experiment: widen the plant by two nulls (φ from
    # 1/2 to 2/3) while holding the within-class behaviour fixed —
    # half of each class declared in both campaigns — and the figures
    # cannot move while the raw rate must.  That is §4.1.3's whole
    # argument for measuring the pair and reweighting later (267)
    # instead of calibrating on the rate, and the reason §4.1.1 shades
    # φ down only after noting joint precision peaks near 0.5: the
    # design constant is free to move because these two numbers are
    # not functions of it.
    narrow = {NULL_ONE: True, REAL_ONE: False, NULL_TWO: True, REAL_TWO: False}
    wide = {**narrow, NULL_THREE: True, NULL_FOUR: True}
    narrow_process = NullPickScorer(StandInSidecar(narrow))
    wide_process = NullPickScorer(StandInSidecar(wide))
    narrow_figures = narrow_process.calibration_figures(
        [NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO], picks=[NULL_ONE, REAL_ONE]
    )
    wide_figures = wide_process.calibration_figures(
        [NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO, NULL_THREE, NULL_FOUR],
        picks=[NULL_ONE, REAL_ONE, NULL_THREE],
    )
    assert narrow_figures == wide_figures
    assert narrow_figures.sensitivity == 0.5
    assert narrow_figures.specificity == 0.5
    # The rate over the same behaviour is an artifact of φ: it moved,
    # from one half to two thirds, between the two campaigns.
    assert narrow_process.null_pick_rate([NULL_ONE, REAL_ONE]) == 0.5
    assert wide_process.null_pick_rate([NULL_ONE, REAL_ONE, NULL_THREE]) == 2 / 3


# -- The barrier: what is read, and what crosses ------------------------------------


def test_the_sidecar_is_asked_once_per_planted_node_in_canonical_form(
    scorer: NullPickScorer,
    sidecar: StandInSidecar,
    planted_population: list[str],
) -> None:
    # The reads are the population's canonical ids, once each, in the
    # handed order — and nothing for the picks: every pick is inside
    # the population, so its label is the population's own, and the
    # barrier's read pass never widens past the whole it was handed.
    scorer.calibration_figures(planted_population, picks=[NULL_ONE, REAL_ONE])
    assert sidecar.reads == planted_population


def test_a_second_ask_reads_again_no_label_cache(
    scorer: NullPickScorer,
    sidecar: StandInSidecar,
    planted_population: list[str],
) -> None:
    # The held sidecar's file is read per ask and never cached — 265's
    # own law, held by this verb unchanged — and the second ask answers
    # the same pair to the bit (four counts, two divisions, nothing
    # else in the verb but the read).
    first = scorer.calibration_figures(planted_population, picks=[REAL_ONE])
    assert sidecar.reads == planted_population
    second = scorer.calibration_figures(planted_population, picks=[REAL_ONE])
    assert sidecar.reads == [*planted_population, *planted_population]
    assert first == second


def test_the_ask_is_order_independent_where_the_reads_follow_the_order(
    scorer: NullPickScorer,
    sidecar: StandInSidecar,
    planted_population: list[str],
) -> None:
    # Counts are order-free: the reversed plant answers the identical
    # pair (both divisions of the same four integers), while the read
    # log follows the order the population was handed — the one fact
    # the ask carries that a caller can debug against.
    forward = scorer.calibration_figures(planted_population, picks=[REAL_ONE])
    assert sidecar.reads == planted_population
    reversed_population = list(reversed(planted_population))
    backward = scorer.calibration_figures(reversed_population, picks=[REAL_ONE])
    assert sidecar.reads[-4:] == reversed_population
    assert forward == backward


def test_every_uuid_spelling_of_a_planted_node_joins(
    scorer: NullPickScorer,
    sidecar: StandInSidecar,
    planted_population: list[str],
) -> None:
    # The join is uuid's law, restated for the planted node: mixed case,
    # braces and the urn form all canonicalize to the sidecar's keys —
    # and the reads the stand-in records are the canonical spellings,
    # which is what proves the join happened before the read.
    spelled = [
        NULL_ONE.upper(),
        "{" + REAL_ONE + "}",
        "urn:uuid:" + NULL_TWO,
        REAL_TWO.upper(),
    ]
    figures = scorer.calibration_figures(spelled, picks=[NULL_ONE, REAL_ONE])
    assert figures == CalibrationFigures(sensitivity=0.5, specificity=0.5)
    assert sidecar.reads == planted_population


def test_a_refused_ask_never_touches_a_label(
    scorer: NullPickScorer,
    sidecar: StandInSidecar,
    planted_population: list[str],
) -> None:
    # Shapes first, labels last: every pure refusal — the mapping, the
    # empty plant, the duplicate node, the pick outside the population —
    # fires before the first read, and the stand-in's log proves it
    # stayed empty.  The discipline is 265's own (*the ask is validated
    # whole before the first label is read*), held one feature later.
    refused_asks: list[tuple[Any, dict[str, Any]]] = [
        ({"campaign": "not-a-plant"}, {"picks": []}),
        ([], {"picks": []}),
        ([NULL_ONE, NULL_ONE], {"picks": []}),
        (planted_population, {"picks": [UNHELD]}),
    ]
    for population, kwargs in refused_asks:
        with pytest.raises(CalibrationFiguresError):
            scorer.calibration_figures(population, **kwargs)
        assert sidecar.reads == []


def test_a_read_that_fails_names_only_the_node_it_failed_on(
    sidecar_labels: dict[str, bool],
) -> None:
    # The unlabelled planted node is refused in this seam's vocabulary,
    # naming that node — the caller's own declared population member —
    # and no other; the reads before it happened (the population is
    # measured in order, and unknown is learned only by reading), so
    # the log carries the prefix and the refusal carries the one node.
    labels = dict(sidecar_labels)
    labels[UNHELD] = None  # type: ignore[assignment]
    sidecar = StandInSidecar(labels)  # type: ignore[arg-type]
    scorer = NullPickScorer(sidecar)
    with pytest.raises(CalibrationFiguresError) as raised:
        scorer.calibration_figures(
            [NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO, UNHELD], picks=[REAL_ONE]
        )
    message = str(raised.value)
    assert UNHELD in message
    assert "no entry" in message
    for held in (NULL_ONE, NULL_TWO, REAL_ONE, REAL_TWO):
        assert held not in message


def test_an_is_null_that_is_not_a_bool_is_refused(
    sidecar_labels: dict[str, bool],
) -> None:
    # The bit decides which class a node conditions on, and
    # bool("false") is True: a coerced bit would count the wrong class,
    # the same refusal the oracle's own layers make at write and read.
    sidecar = StandInSidecar({**sidecar_labels, NULL_ONE: "false"})  # type: ignore[dict-item]
    scorer = NullPickScorer(sidecar)
    with pytest.raises(CalibrationFiguresError) as raised:
        scorer.calibration_figures(
            [NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO], picks=[REAL_ONE]
        )
    assert "is_null" in str(raised.value)


def test_a_foreign_failure_is_translated_and_chained(
    planted_population: list[str],
) -> None:
    # Whatever the carrier raised, the fact for the caller is one thing
    # — the label could not be read — in this member's vocabulary, with
    # the original chained: the translation law every cross-member seam
    # states, so a caller's single ``except ScoringError`` catches the
    # whole member and no foreign type escapes wearing this seam's name.

    class Exploding:
        def assignment(self, node_id: str) -> None:
            raise RuntimeError("the sealed file moved")

    with pytest.raises(CalibrationFiguresError) as raised:
        NullPickScorer(Exploding()).calibration_figures(
            planted_population, picks=[REAL_ONE]
        )
    assert "could not be read" in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)


# -- The refusals: this seam's laws, in order --------------------------------------


def test_a_population_that_is_not_the_planted_nodes_is_refused(
    scorer: NullPickScorer,
) -> None:
    # A mapping's keys are not its nodes, a bare string is one node
    # spelled where the collection belongs, and something uniterable is
    # not a plant — each named for what it carried, none of them
    # fractions over a whole anybody declared.
    for carried in ({"NULL_ONE": True}, NULL_ONE, b"noise", 7):
        with pytest.raises(CalibrationFiguresError) as raised:
            scorer.calibration_figures(carried, picks=[])  # type: ignore[arg-type]
        message = str(raised.value)
        assert "planted" in message
        assert "feature 266" in message


def test_a_plant_with_no_nodes_is_refused(
    scorer: NullPickScorer,
    planted_population: list[str],
) -> None:
    # The empty *plant* is not the empty declaration: no nodes means no
    # classes and no denominator at all, and the refusal says which of
    # the two empties it is — the ask that committed to nothing is
    # answered above, this one never reaches a figure.
    with pytest.raises(CalibrationFiguresError) as raised:
        scorer.calibration_figures([], picks=[])
    assert "carried none" in str(raised.value)


def test_a_node_planted_twice_is_refused_in_either_spelling(
    scorer: NullPickScorer,
) -> None:
    # The plant is a set, and both denominators are counts over it: one
    # node twice — twice in one spelling, or once each in two spellings
    # of one UUID — would double-count whichever class it conditions
    # on, so the second spelling is refused, naming the canonical id
    # both spellings name.
    with pytest.raises(CalibrationFiguresError) as raised:
        scorer.calibration_figures([NULL_ONE, NULL_ONE], picks=[])
    assert NULL_ONE in str(raised.value)
    assert "twice" in str(raised.value)
    with pytest.raises(CalibrationFiguresError) as braced:
        scorer.calibration_figures(
            [NULL_ONE, "{" + NULL_ONE.upper() + "}"], picks=[]
        )
    assert NULL_ONE in str(braced.value)


def test_a_planted_node_that_names_no_node_is_refused(
    scorer: NullPickScorer,
    planted_population: list[str],
) -> None:
    # The population's two spellings, refused in this seam's own words
    # when they name nothing: a bool, a None, an object exposing no
    # node_id, and an address that is not a UUID (the fixture's own
    # pick address — a tree path, not a sidecar key — is the likeliest
    # wrong shape a caller could hand).
    for node in (True, None, object(), "campaign-01/momentum-branch/d+1"):
        with pytest.raises(CalibrationFiguresError):
            scorer.calibration_figures([*planted_population, node], picks=[])  # type: ignore[list-item]


def test_the_pick_law_stays_feature_265_s(
    scorer: NullPickScorer,
    planted_population: list[str],
) -> None:
    # A collection that is not the picks themselves, and a pick that
    # names no node, refuse in 265's vocabulary — propagated
    # untranslated, exactly as the accounting propagates the same law,
    # so the repair stays named where the law lives.  Both still catch
    # under the member's one base, which is the property a caller's
    # single except buys.
    for picks in ({"a": 1}, NULL_ONE, 7):
        with pytest.raises(NullPickRateError):
            scorer.calibration_figures(planted_population, picks=picks)  # type: ignore[arg-type]
    with pytest.raises(NullPickRateError) as raised:
        scorer.calibration_figures(planted_population, picks=[None])
    assert "not a committed pick" in str(raised.value) or "miss" in str(raised.value)
    with pytest.raises(NullPickRateError):
        scorer.calibration_figures(planted_population, picks=["not-a-uuid"])


def test_a_pick_outside_the_population_is_refused(
    scorer: NullPickScorer,
    planted_population: list[str],
) -> None:
    # A discovery claimed outside the measured whole counts on neither
    # side of either fraction — a real one would leave sensitivity's
    # numerator empty, a null one specificity's denominator short — and
    # the figures would be fractions over a whole nobody chose.  The
    # refusal names the pick, and the repair is one of two collections
    # only the caller knows which.
    with pytest.raises(CalibrationFiguresError) as raised:
        scorer.calibration_figures(planted_population, picks=[UNHELD])
    assert UNHELD in str(raised.value)
    assert "does not hold" in str(raised.value)


def test_a_plant_with_no_reals_refuses_sensitivity(
    scorer: NullPickScorer,
) -> None:
    # §4.1.1's floor, one side: a tree of nothing but nulls has nothing
    # for a discovery to find, and a sensitivity about an empty class
    # would be a stand-in where §4.1.3 asks for a measurement — 0.0 is
    # refused, not answered.
    with pytest.raises(CalibrationFiguresError) as raised:
        scorer.calibration_figures([NULL_ONE, NULL_TWO], picks=[NULL_ONE])
    assert "no real" in str(raised.value)
    assert "§4.1.1" in str(raised.value)


def test_a_plant_with_no_nulls_refuses_specificity(
    scorer: NullPickScorer,
) -> None:
    # The floor's other side: a population of nothing but reals cannot
    # be wrongly declared against — specificity's class is empty, and
    # 1.0 is refused rather than defaulted.
    with pytest.raises(CalibrationFiguresError) as raised:
        scorer.calibration_figures([REAL_ONE, REAL_TWO], picks=[REAL_ONE])
    assert "no null" in str(raised.value)


# -- Determinism, stated as the corpus states it ------------------------------------


def test_the_figures_are_exact_and_finite(
    scorer: NullPickScorer,
    planted_population: list[str],
) -> None:
    # One correctly-rounded division of two integers per figure, over
    # dyadic quotients: exact in binary, checkable with ==, and finite
    # by construction — the narrowing admits nothing else.
    figures = scorer.calibration_figures(planted_population, picks=[REAL_ONE])
    assert figures.sensitivity == 0.5
    assert figures.specificity == 1.0
    assert math.isfinite(figures.sensitivity)
    assert math.isfinite(figures.specificity)
