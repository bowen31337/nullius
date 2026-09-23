"""Feature 264's law: the regime index.

*System rejects a plain mean across regimes, indexing aggregation strata
by regime instead* (app_spec.xml, "Objective Scoring & CVaR Aggregation").
The tests here hold :mod:`scoring._regime_index` to the sentence's two
clauses, in the order the sentence states them:

* **the rejection** — every ask whose arithmetic would average across
  regimes is refused, all four faces opening with
  :data:`~scoring.PLAIN_MEAN_CODE`: scores with no labels at all
  (:func:`test_scores_with_no_labels_are_refused`), a scored world the
  census never binned
  (:func:`test_a_scored_world_the_census_never_binned_is_refused`), a
  labelled world no score was earned for
  (:func:`test_a_labelled_world_with_no_score_is_refused`), and a declared
  regime the join does not cover
  (:func:`test_a_declared_regime_with_no_worlds_is_refused`) — plus the
  negative control the whole feature hangs off,
  :func:`test_the_mean_over_worlds_is_not_the_blend`, which computes the
  plain mean the feature rejects and shows it disagreeing with the index's
  blended answer;
* **the index** — the strata keyed by *regime*, not by world
  (:func:`test_the_index_is_keyed_by_regime`), as the mapping feature 263's
  verb takes, sorted and never aliased
  (:func:`test_the_index_is_the_blend_verbs_own_input`,
  :func:`test_the_index_is_order_independent`), with the join's identity
  laws enforced from this side
  (:func:`test_a_world_labelled_twice_is_refused`,
  :func:`test_a_world_scored_twice_is_refused`).

The composed verb is pinned end to end in
:func:`test_regime_aggregate_is_the_two_halves_in_one_call`: the index and
the blend, over the same labels and scores the ``strata`` fixture already
aggregates, answering the same number feature 263's suite pins — the
pipeline the category is building, at the seam where feature 290's census
output becomes 263's input.

What these tests deliberately do not reach: composition (that is
``test_component.py`` — 264 adds no component), the seat
(``test_app_module.py`` — unchanged), the blend's own arithmetic
(``test_aggregate.py``) and the census that writes the labels (the regime
member's ``test_census.py``).  The vocabulary is deliberately left open
here — :func:`test_an_undeclared_regime_is_admitted` is the assertion that
this member did *not* close feature 283's set — because restating another
member's judgement is exactly what the missing-member rule is for.
"""

from __future__ import annotations

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    CHOP,
    CRASH,
    TREND,
    StandInLabel,
    StandInScore,
    world_score,
)
from scoring import (
    LAMBDA_DEFAULT,
    PLAIN_MEAN_CODE,
    AggregatedObjective,
    AggregationError,
    RegimeIndexError,
    ScoringError,
    WorldScore,
    aggregate_objective,
    regime_aggregate,
    regime_strata,
)

#: Feature 283's three names, in the order its own sentence spells them —
#: the vocabulary this suite declares where a declaration is the subject,
#: and the one the regime member publishes as ``DEFAULT_STRATA``.
VOCABULARY = [TREND, CHOP, CRASH]


# -- the rejection ----------------------------------------------------------------


def test_scores_with_no_labels_are_refused() -> None:
    # The shape a caller reaches for when the census has not run: every
    # number present, only the partition missing.  It is the plain mean
    # prd §7.2 rejects — (1/t)·Σ V_i^m, correct only if worlds are
    # exchangeable — and the refusal names that rather than reporting a
    # missing argument, because the repair is to run the census, not to
    # pass None differently.
    with pytest.raises(RegimeIndexError, match=PLAIN_MEAN_CODE):
        regime_strata([], [world_score("w1", 0.75)])


def test_a_scored_world_the_census_never_binned_is_refused() -> None:
    # M worlds scored, N < M labelled: the world with no regime is
    # precisely the one a plain mean swallows, and averaging the scores
    # while reading the labels as commentary is the failure this feature
    # exists to refuse.  The refusal names the world and both counts, so
    # the repair — re-run the census over the pool that was scored — is
    # in the message.
    labels = [StandInLabel("w1", TREND)]
    scores = [world_score("w1", 0.75), world_score("w2", 0.25)]
    with pytest.raises(RegimeIndexError, match=PLAIN_MEAN_CODE) as refusal:
        regime_strata(labels, scores)
    assert "w2" in str(refusal.value)


def test_a_labelled_world_with_no_score_is_refused() -> None:
    # The mirror image, and the quieter failure: the index would omit the
    # world, mean_g would be taken over a pool that is not the pool, and
    # the blend would report a figure for strata it silently thinned.
    # Both directions are refused by name because both end in an average
    # over a set nobody chose.
    labels = [StandInLabel("w1", TREND), StandInLabel("w2", CRASH)]
    scores = [world_score("w1", 0.75)]
    with pytest.raises(RegimeIndexError, match=PLAIN_MEAN_CODE) as refusal:
        regime_strata(labels, scores)
    assert "w2" in str(refusal.value)


def test_a_declared_regime_with_no_worlds_is_refused() -> None:
    # The face feature 263 cannot state from its own side: the blend
    # refuses a stratum it was *handed* with no worlds, but a stratum the
    # index dropped never reaches it — and blending over the covered
    # subset is a mean across the regimes that happened to be present,
    # which is §C7's whole hazard ("run six months in low-vol chop and
    # your entire pool is low-vol chop").  The starved regime is the fact
    # a subset-mean erases, so the declaration is what makes it visible.
    labels = [StandInLabel("w1", TREND)]
    scores = [world_score("w1", 0.75)]
    with pytest.raises(RegimeIndexError, match=PLAIN_MEAN_CODE) as refusal:
        regime_strata(labels, scores, strata=VOCABULARY)
    assert CHOP in str(refusal.value) and CRASH in str(refusal.value)


def test_the_mean_over_worlds_is_not_the_blend(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # The negative control, and the number the feature's first clause is
    # about.  Over the fixture's seven worlds the plain mean is
    # (2·0.75 + 2·0.5 + 3·0.25)/7 = 3.25/7 ≈ 0.464286, while the
    # regime-indexed blend is 0.35 at the default λ — *different numbers*,
    # not different spellings of one answer.  Two separate reasons, and
    # the second is the one the feature is for:
    #
    #   * the λ tail term, which a mean has no counterpart to;
    #   * the weighting, which the next test isolates — the plain mean
    #     weights each regime by how many worlds it happens to hold.
    scores = _scores_of(strata)
    plain_mean = sum(world.score for world in scores) / len(scores)
    assert plain_mean == pytest.approx(3.25 / 7)
    assert regime_aggregate(labels, scores).score == pytest.approx(0.35)
    assert plain_mean != regime_aggregate(labels, scores).score


def test_world_count_moves_the_mean_but_never_the_blend() -> None:
    # The feature's argument, isolated from the λ term: λ and the stratum
    # *figures* are held fixed and only the number of worlds each regime
    # holds changes.  prd §7.2's point is that a pool's shape is an
    # accident of when it was built — three chop worlds against one trend
    # world is a pool that spent its calendar in chop — and a mean over
    # worlds lets that accident set the weighting, swinging 0.5 → 0.375
    # on composition alone.  The blend's weighting is the regime itself,
    # so it answers 0.5·0.5 + 0.5·0.25 = 0.375 both times, unmoved.
    lean = ([StandInLabel("t1", TREND), StandInLabel("c1", CHOP)], [0.75, 0.25])
    padded = (
        [
            StandInLabel("t1", TREND),
            StandInLabel("c1", CHOP),
            StandInLabel("c2", CHOP),
            StandInLabel("c3", CHOP),
        ],
        [0.75, 0.25, 0.25, 0.25],
    )
    blends = [
        regime_aggregate(
            labels,
            [
                world_score(label.world_id, value)
                for label, value in zip(labels, values, strict=True)
            ],
            lam=0.5,
        ).score
        for labels, values in (lean, padded)
    ]
    plain_means = [sum(values) / len(values) for _, values in (lean, padded)]
    assert blends[0] == blends[1] == pytest.approx(0.375)
    assert plain_means[0] == pytest.approx(0.5)
    assert plain_means[1] == pytest.approx(0.375)
    assert plain_means[0] != plain_means[1]


# -- the index --------------------------------------------------------------------


def test_the_index_is_keyed_by_regime(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # The sentence's second clause: the strata are *regimes*, and the
    # worlds inside each one are the worlds the census binned there — so
    # the index's keys are the labeler's names and never a world id.  The
    # figures that come out the other end are 263's own.
    index = regime_strata(labels, _scores_of(strata))
    assert sorted(index) == sorted(strata)
    assert {world.world_id for world in index[CRASH]} == {
        "crash-a",
        "crash-b",
        "crash-c",
    }
    assert all(isinstance(world, StandInScore | WorldScore) for world in index[TREND])


def test_the_index_is_the_blend_verbs_own_input(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # The seam: what this verb answers is what feature 263's verb takes,
    # unchanged — not a wrapper to unwrap, not a shape to convert.  The
    # index and the fixture's hand-grouped mapping are the same object to
    # the blend, so the same aggregate comes out of either.
    index = regime_strata(labels, _scores_of(strata))
    from_index = aggregate_objective(index, lam=0.5)
    from_fixture = aggregate_objective(strata, lam=0.5)
    assert from_index == from_fixture
    assert from_index.score == 0.375
    assert from_index.worst_stratum == CRASH


def test_regime_aggregate_is_the_two_halves_in_one_call(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # The verb this category actually calls: index, then blend, in one
    # ask whose strata are regimes by construction — so a caller never
    # assembles a grouping by hand and never reaches the plain mean by
    # assembling one wrong.  Same labels, same scores, same λ: the same
    # frozen value feature 263's suite pins over the same pool.
    composed = regime_aggregate(labels, _scores_of(strata), lam=0.5)
    assert isinstance(composed, AggregatedObjective)
    assert composed == aggregate_objective(strata, lam=0.5)
    assert composed.score == 0.375
    assert composed.stratum_means == {TREND: 0.75, CHOP: 0.5, CRASH: 0.25}
    assert composed.world_count == 7


def test_the_index_is_order_independent(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # The determinism law the per-world score states (docs §10.1), fixed
    # at the index as well as at the blend: two callers who assembled the
    # same census rows and the same scores in different orders inspect
    # the same object, so the dreaming loop's argmax ranks the same
    # candidates.  Sorted by name, and by world id inside each name.
    scores = _scores_of(strata)
    forward = regime_strata(labels, scores)
    backward = regime_strata(list(reversed(labels)), list(reversed(scores)))
    assert forward == backward
    assert list(forward) == sorted(forward)
    assert [world.world_id for world in forward[CRASH]] == sorted(
        world.world_id for world in forward[CRASH]
    )


def test_the_index_is_not_aliased_to_its_inputs(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # A fresh mapping of fresh tuples: a caller that keeps building on the
    # list it handed over cannot move an index already answered — the
    # stance feature 263's AggregatedObjective takes for its own trail.
    scores = list(_scores_of(strata))
    index = regime_strata(labels, scores)
    before = dict(index)
    scores.append(world_score("crash-d", 0.25))
    labels.append(StandInLabel("crash-d", CRASH))
    assert index == before
    assert all(isinstance(worlds, tuple) for worlds in index.values())


@pytest.mark.parametrize("declared", [None, VOCABULARY])
def test_an_undeclared_vocabulary_admits_the_labels_own_names(
    declared: object, labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # ``strata=None`` is the default and means the labels name their own
    # regimes; a declaration that covers exactly those names answers the
    # identical index.  Two spellings of one ask, one answer — the
    # declaration adds checking, never a different set.
    assert regime_strata(labels, _scores_of(strata), strata=declared) == regime_strata(
        labels, _scores_of(strata)
    )


def test_an_undeclared_regime_is_admitted() -> None:
    # The open-vocabulary law, pinned as behaviour: feature 283's
    # DEFAULT_STRATA is an open set ("such as high-volatility trend …"),
    # and its own module argues the case against feature 241's legal theme
    # set — a stratum name is not a configured space, so nothing there
    # refuses a name outside the default three.  This member must not
    # close it either: a fifth regime a deployment configured indexes
    # fine, and only an explicit declaration can refuse a name.
    labels = [StandInLabel("w1", "sustained melt-up")]
    scores = [world_score("w1", 0.75)]
    assert regime_strata(labels, scores) == {"sustained melt-up": (scores[0],)}
    # …and declared, the same label is admitted too, because the
    # declaration is the caller's and this one names that regime.
    assert regime_strata(
        labels, scores, strata=["sustained melt-up"]
    ) == {"sustained melt-up": (scores[0],)}


# -- the join's identity laws -----------------------------------------------------


def test_a_world_labelled_twice_is_refused() -> None:
    # Each stored world is assigned one stratum by the labeler, and a
    # world carrying two labels would be counted once per label in a mean
    # that holds it once.  Refused in the *join's* vocabulary — feature
    # 290 refuses this too, but these rows are data by the time they
    # arrive, and a partition a caller assembled is checked rather than
    # trusted.
    labels = [StandInLabel("w1", TREND), StandInLabel("w1", CRASH)]
    with pytest.raises(RegimeIndexError, match="labelled twice"):
        regime_strata(labels, [world_score("w1", 0.75)])


def test_a_world_scored_twice_is_refused() -> None:
    # One world earns one score — the pooled quantity the blend averages
    # within a stratum — so a world counted twice would weigh double in
    # the very figure that exists to weigh each world once.
    labels = [StandInLabel("w1", TREND)]
    scores = [world_score("w1", 0.75), world_score("w1", 0.25)]
    with pytest.raises(RegimeIndexError, match="scored twice"):
        regime_strata(labels, scores)


def test_a_label_carrier_that_is_not_one_is_refused() -> None:
    # The label seam is duck-typed, so what it reads it validates: a bare
    # string is a world id with no regime attached, a number has no world
    # to be, and a plain object exposes nothing to read.
    for carried in ("w1", 42, object(), None, True):
        with pytest.raises(RegimeIndexError, match="must name"):
            regime_strata([carried], [world_score("w1", 0.75)])


def test_a_label_whose_stratum_is_not_a_name_is_refused() -> None:
    # A regime that cannot be named cannot be reported, checked against a
    # declared vocabulary, or counted as a key — and the index's keys are
    # regimes by the feature's own sentence.
    for stratum in ("", "   ", 7, True, None):
        with pytest.raises(RegimeIndexError, match="must name"):
            regime_strata(
                [StandInLabel("w1", stratum)],  # type: ignore[arg-type]
                [world_score("w1", 0.75)],
            )


def test_a_score_carrier_that_is_not_a_world_score_is_refused() -> None:
    # Refused at the value it would have poisoned a stratum mean with,
    # rather than escaping as a TypeError from inside the blend's
    # math.fsum — the discipline feature 263's own seam states.
    for carried in (0.25, "crash-a", object(), None, True):
        with pytest.raises(RegimeIndexError, match="must name"):
            regime_strata([StandInLabel("w1", CRASH)], [carried])


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_a_score_that_is_not_finite_is_refused(score: float) -> None:
    # The −∞ division of labour held at the index: the miss's −∞ is
    # feature 222's value, answered by the termination and never carrying
    # a pick, so no indexed world may counterfeit it — and a NaN would
    # compare false against every score and drop out of the ranking the
    # aggregate feeds.
    with pytest.raises(RegimeIndexError, match="must be finite"):
        regime_strata([StandInLabel("w1", CRASH)], [StandInScore("w1", score)])


def test_a_declared_vocabulary_that_cannot_be_checked_is_refused() -> None:
    # A vocabulary is the set a label is checked against, so one that
    # cannot be a set refuses the ask before a single label is read: a
    # bare string is one name, a non-sequence cannot say which regimes a
    # label may name, and a name declared twice cannot be told apart from
    # a label that matched it twice.
    labels = [StandInLabel("w1", TREND)]
    scores = [world_score("w1", 0.75)]
    for declared in (TREND, 42, [TREND, TREND], [], [""]):
        with pytest.raises(RegimeIndexError):
            regime_strata(labels, scores, strata=declared)  # type: ignore[arg-type]


def test_a_label_outside_the_declared_vocabulary_is_refused() -> None:
    # The other direction of the declaration: a label the caller's own
    # ledger cannot show is a stratum nobody declared, and indexing it
    # would blend over a regime outside the checked set.  The refusal
    # names the world, the label and the declared names.
    labels = [StandInLabel("w1", "sustained melt-up")]
    scores = [world_score("w1", 0.75)]
    with pytest.raises(RegimeIndexError, match="declared vocabulary") as refusal:
        regime_strata(labels, scores, strata=VOCABULARY)
    assert "w1" in str(refusal.value)


def test_a_scores_argument_that_is_not_a_collection_is_refused() -> None:
    # The score seam's shape refusal, distinct from a carrier that is not
    # a score: a value that is not a collection of scores has nothing to
    # key, and a string would iterate characters.
    labels = [StandInLabel("w1", TREND)]
    for carried in (world_score("w1", 0.75), "crash-a", 42, None):
        with pytest.raises(RegimeIndexError, match="iterable of world scores"):
            regime_strata(labels, carried)  # type: ignore[arg-type]


# -- the vocabulary ---------------------------------------------------------------


def test_the_error_is_a_sibling_of_the_aggregations(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # One base class for the member, so a dreaming loop wrapping its
    # aggregation step in a single except catches every law of this
    # pipeline; and RegimeIndexError beside AggregationError, never under
    # it — 263 refuses an ask that cannot be *blended*, 264 one that
    # cannot be *partitioned*, and a caller that must react to "the
    # census has not run" would misread it as "the λ is mis-set" if the
    # two shared one except.
    with pytest.raises(ScoringError):
        regime_strata([], [world_score("w1", 0.75)])
    assert issubclass(RegimeIndexError, ScoringError)
    assert not issubclass(RegimeIndexError, AggregationError)
    assert not issubclass(AggregationError, RegimeIndexError)


def test_a_refusal_answers_nothing_partial(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # The index either answers a complete mapping or raises — a caller
    # can never hold a half-built partition it must remember to discard.
    # The refused ask and the legal one on either side of it answer
    # independently, so the refusal left no state behind.
    scores = _scores_of(strata)
    before = regime_strata(labels, scores)
    with pytest.raises(RegimeIndexError):
        regime_strata(labels, scores[:1])
    assert regime_strata(labels, scores) == before


def test_the_plain_mean_code_names_the_refusal() -> None:
    # The greppable word the feature's first clause is named by — the
    # convention pool_frozen (270), illegal_theme (241) and
    # full_history_fit (290) already follow — carried as a published
    # constant because an operator greps a log for it, and the four
    # plain-mean faces are one word because they are one failure.
    assert PLAIN_MEAN_CODE == "plain_mean"
    with pytest.raises(RegimeIndexError) as refusal:
        regime_strata([], [world_score("w1", 0.75)])
    assert str(refusal.value).startswith("the regime index was handed no labels")
    assert PLAIN_MEAN_CODE in str(refusal.value)


def test_the_default_lambda_is_the_blends_own(
    labels: list[StandInLabel], strata: dict[str, list[WorldScore]]
) -> None:
    # The composed verb inherits feature 263's knob rather than restating
    # a second default: a caller that names no λ blends under exactly the
    # band's midpoint, and a λ outside prd §7.2's band is refused by the
    # blend — unwrapped, because that refusal is already this member's
    # vocabulary and a second message would name the wrong act.
    assert regime_aggregate(labels, _scores_of(strata)).lam == LAMBDA_DEFAULT
    with pytest.raises(AggregationError, match="band"):
        regime_aggregate(labels, _scores_of(strata), lam=0.9)


# -- helpers ----------------------------------------------------------------------


def _scores_of(strata: dict[str, list[WorldScore]]) -> list[WorldScore]:
    """The fixture's worlds as one flat pool, in a fixed order.

    The index takes the scores the way the replay hands them over — one
    collection of worlds scored, whose regimes arrive separately as the
    census's rows — rather than the fixture's already-grouped shape.  The
    order is the fixture's name-then-world order, which is one order the
    caller could produce; the order-independence test reverses it.
    """
    return [world for name in sorted(strata) for world in strata[name]]
