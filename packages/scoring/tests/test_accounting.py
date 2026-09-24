"""Feature 269's law — the error accounting that keeps Type-A commitment
errors and Type-B depth-past-flip errors apart, each as its own metric.

prd §4.1.2 states the instruction (line 140): *"Separate the error
accounting.  Type-A error is committing to a null; Type-B is continuing
to deepen past the flip."*  docs §7.3.1 names why (line 339): *"Two
distinct failures, two distinct terms.  Conflating them was the original
design's blind spot."*  This suite pins the separation at every face it
has:

* **the answer's shape** — one value, two separately named metrics, and
  no third figure to conflate into;
* **Type-A's side** — the rate feature 265's process answers, asked
  through its one public verb, verbatim, exactly once, and never
  derived here (the labels are §4.2's single-component grant);
* **Type-B's side** — a count over handed-over depth facts, §7.2's
  inclusive boundary (the node *at* the flip is the first null node),
  an undrawn branch refused as unknown rather than read as below, and
  no label store touched on this side at all;
* **the refusals** — each in this seam's own vocabulary, except the
  pick law's, which stays feature 265's because the pick law is.

The fixtures come from the suite's conftest: the four-pick committed
campaign (rate 0.5 exactly), the four-node Type-D exploration campaign
(count 2 exactly, the node at the flip counted), and the stand-in
sidecar whose read log is what proves the barrier's reads.  A recording
stand-in process — defined here, not in the conftest, because only this
suite asks it anything — is what proves the ask discipline: asked once,
verbatim, and never when the ask was refused.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local
    AT_FLIP,
    BELOW_ONE,
    BELOW_TWO,
    BEYOND_FLIP,
    FLIP_DEPTH,
    NULL_ONE,
    UNHELD,
    StandInExploration,
    StandInPick,
    StandInSidecar,
    world_score,
)
from scoring import (
    BETA_TWO_DEFAULT,
    ErrorAccounting,
    ErrorAccountingError,
    NullPickPenaltyError,
    NullPickRateError,
    NullPickScorer,
    ScoringError,
    account_errors,
    null_pick_penalty,
)


class RecordingScorer:
    """A stand-in for feature 265's process, behind its one seam.

    Exposes exactly ``null_pick_rate(picks)`` — the verb the accounting
    duck-reads — recording every ask's argument *by identity* so the
    suite can prove the picks were handed over verbatim, and answering a
    fixed rate or raising what its builder named.  The fixture's
    narrowness is the assertion that the accounting asks the process for
    one thing and one thing only.
    """

    def __init__(self, rate: Any = 0.5, failure: Exception | None = None) -> None:
        self._rate = rate
        self._failure = failure
        self.asks: list[object] = []

    def null_pick_rate(self, picks: object) -> float:
        self.asks.append(picks)
        if self._failure is not None:
            raise self._failure
        return self._rate


@pytest.fixture
def scorer(sidecar_labels: dict[str, bool]) -> NullPickScorer:
    """The real process over the conftest's stand-in sidecar — feature
    265's own class, so the accounting's Type-A ask runs the law it will
    run in a deployment, not a stand-in's answer."""
    return NullPickScorer(StandInSidecar(sidecar_labels))


@dataclass(frozen=True)
class DepthOnlyNode:
    """One explored node carrying its depth and no branch fact at all.

    The shape whose refusal is the *undrawn branch's*: a node whose
    facts arrived without the join, presenting no ``flip_depth`` for the
    boundary to resolve against — its position past the flip unknown,
    never below it.  ``StandInExploration`` cannot spell this (its
    ``flip_depth`` is ``None``'s own spelling), so the shape without the
    attribute at all is named here.
    """

    node_id: str
    depth: int


# -- The answer's shape ----------------------------------------------------------


def test_each_error_is_answered_as_its_own_metric(
    scorer: NullPickScorer, committed_picks, type_d_explorations
) -> None:
    # The feature's own closing clause, read off the answer: Type-A's
    # metric is the campaign's realized rate over its committed picks
    # (0.5 exactly, 2/4 dyadic), Type-B's is the count of explorations at
    # or beyond the branch's flip (2 exactly — the node at the flip and
    # the node beyond it, never the two below), and the two are different
    # kinds because the two errors are different kinds of event.
    accounting = account_errors(
        committed_picks, explored=type_d_explorations, scorer=scorer
    )
    assert isinstance(accounting, ErrorAccounting)
    assert accounting.commitment_error_rate == 0.5
    assert accounting.depth_past_flip_errors == 2
    assert type(accounting.commitment_error_rate) is float
    assert type(accounting.depth_past_flip_errors) is int


def test_the_value_carries_no_third_figure(
    scorer: NullPickScorer, committed_picks, type_d_explorations
) -> None:
    # Two fields, named for the two errors, and nothing besides: no
    # total, no blend, no weighting — the single figure over both
    # failures is the conflation docs §7.3.1 calls the original design's
    # blind spot, and the value's shape is where that figure does not
    # exist.
    accounting = account_errors(
        committed_picks, explored=type_d_explorations, scorer=scorer
    )
    assert [field.name for field in dataclasses.fields(accounting)] == [
        "commitment_error_rate",
        "depth_past_flip_errors",
    ]
    for conflation in ("total", "combined", "errors", "rate", "error_count"):
        assert not hasattr(accounting, conflation)


def test_the_value_is_frozen(
    scorer: NullPickScorer, committed_picks, type_d_explorations
) -> None:
    # The two figures will be read by β₂'s charge and feature 345's
    # trend; a value that could be edited after the fact would be a
    # mutable handle to a measurement already made.
    accounting = account_errors(
        committed_picks, explored=type_d_explorations, scorer=scorer
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        accounting.commitment_error_rate = 0.0  # type: ignore[misc]


def test_the_same_ask_answers_the_same_value(
    scorer: NullPickScorer, committed_picks, type_d_explorations
) -> None:
    # Deterministic to the value: one count, one ask, one frozen record,
    # and the equality is the frozen dataclass's own.
    first = account_errors(committed_picks, explored=type_d_explorations, scorer=scorer)
    second = account_errors(committed_picks, explored=type_d_explorations, scorer=scorer)
    assert first == second


# -- Type-A: the process's answer, asked through its one verb ---------------------


def test_type_a_is_the_process_s_own_figure_unchanged(
    scorer: NullPickScorer, committed_picks, type_d_explorations
) -> None:
    # The metric is not derived, re-weighted or rounded here: it is the
    # number the process answers for the same picks, to the bit — the
    # same figure β₂ charges, one spelling (docs §10.3: the number
    # flows out; the labels do not).
    accounting = account_errors(
        committed_picks, explored=type_d_explorations, scorer=scorer
    )
    assert accounting.commitment_error_rate == scorer.null_pick_rate(committed_picks)


def test_the_process_is_asked_exactly_once_with_the_picks_verbatim(
    committed_picks, type_d_explorations
) -> None:
    # One ask, the picks handed over by identity — no copy, no
    # re-validation, no second spelling of feature 265's pick law.  The
    # recording process is the proof: its log holds one entry and the
    # entry is the very object the caller handed in.
    process = RecordingScorer()
    account_errors(committed_picks, explored=type_d_explorations, scorer=process)
    assert len(process.asks) == 1
    assert process.asks[0] is committed_picks


def test_a_refused_ask_never_touches_the_process(
    committed_picks,
) -> None:
    # The shapes are validated whole before the process is asked
    # anything — feature 265's own discipline, held one feature later —
    # so an undrawn branch (or any other refusal below) costs no label
    # read at all.
    process = RecordingScorer()
    with pytest.raises(ErrorAccountingError):
        account_errors(
            committed_picks,
            explored=[StandInExploration(AT_FLIP, FLIP_DEPTH, None)],
            scorer=process,
        )
    assert process.asks == []


def test_a_scorer_without_the_seam_is_refused(
    committed_picks, type_d_explorations, sidecar_labels: dict[str, bool]
) -> None:
    # The wiring fault is named first, before any shape is read: a
    # carrier with no callable null_pick_rate is not a process this
    # accounting can ask, and the refusal names the seam (the sidecar is
    # the likeliest wrong carrier — it holds the labels and lacks the
    # verb).
    with pytest.raises(ErrorAccountingError, match="null_pick_rate"):
        account_errors(
            committed_picks,
            explored=type_d_explorations,
            scorer=StandInSidecar(sidecar_labels),
        )


def test_the_pick_law_refuses_in_the_process_s_vocabulary(
    scorer: NullPickScorer, type_d_explorations
) -> None:
    # The picks are the process's ask, so the process's refusals are the
    # ones the caller sees — untranslated, in feature 265's own
    # vocabulary, because the pick law is 265's and so is its repair.
    # An ask with no picks, and a pick the sidecar holds no entry for:
    # both are the rate's law, not the accounting's.
    with pytest.raises(NullPickRateError, match="committed picks"):
        account_errors([], explored=type_d_explorations, scorer=scorer)
    with pytest.raises(NullPickRateError) as raised:
        account_errors(
            [StandInPick(UNHELD)], explored=type_d_explorations, scorer=scorer
        )
    assert UNHELD in str(raised.value)
    # ... and never re-wrapped into this seam's vocabulary.
    assert not isinstance(raised.value, ErrorAccountingError)


def test_a_foreign_failure_from_the_process_is_translated_and_chained(
    committed_picks, type_d_explorations
) -> None:
    # A carrier that fails while failing to answer — a stand-in's
    # assertion, a foreign process's error — is one fact for the caller:
    # Type-A's rate could not be asked.  Translated into this member's
    # vocabulary (a single ``except ScoringError`` keeps catching the
    # whole member), with the original chained so the operator keeps it.
    burst = RuntimeError("the stand-in broke")
    with pytest.raises(ErrorAccountingError, match="could not be asked") as raised:
        account_errors(
            committed_picks,
            explored=type_d_explorations,
            scorer=RecordingScorer(failure=burst),
        )
    assert raised.value.__cause__ is burst


def test_a_count_answered_where_the_rate_belongs_is_refused(
    committed_picks, type_d_explorations
) -> None:
    # The process hands back no count of nulls by its own class law;
    # when a carrier answers one anyway, the value refuses to receive
    # it.  A NaN is refused with it — a figure that is not a
    # measurement cannot be a fraction of committed picks.
    with pytest.raises(ErrorAccountingError, match="count"):
        account_errors(
            committed_picks,
            explored=type_d_explorations,
            scorer=RecordingScorer(rate=47.0),
        )
    with pytest.raises(ErrorAccountingError, match="finite"):
        account_errors(
            committed_picks,
            explored=type_d_explorations,
            scorer=RecordingScorer(rate=math.nan),
        )


def test_the_type_a_metric_prices_through_beta_two_and_type_b_stands_apart(
    scorer: NullPickScorer, committed_picks, type_d_explorations
) -> None:
    # The two metrics part ways exactly where §4.1.2 says they do:
    # Type-A's rate is the figure β₂ charges (feature 258's term
    # consumes it unchanged), while Type-B's count enters no β-term —
    # β₁ is feature 257's and has not landed, and when it does it will
    # be its own term over its own figure, not a second reader of this
    # one.
    accounting = account_errors(
        committed_picks, explored=type_d_explorations, scorer=scorer
    )
    score = world_score("financial-campaign-01", 0.5)
    charged = null_pick_penalty(
        score, null_pick_rate=accounting.commitment_error_rate
    )
    direct = null_pick_penalty(
        score, null_pick_rate=scorer.null_pick_rate(committed_picks)
    )
    assert charged.score == direct.score
    assert charged.score == score.score - BETA_TWO_DEFAULT * 0.5
    # The count is a whole number of events and joins no ratio.
    assert accounting.depth_past_flip_errors == 2


# -- Type-B: a count over the handed depth facts ----------------------------------


def test_the_node_at_the_flip_is_the_first_null_node(
    scorer: NullPickScorer, committed_picks
) -> None:
    # §7.2's boundary is inclusive — "at or beyond it the permuted
    # ones" — so the node at exactly the flip depth counts and the node
    # one below it does not.  One node per ask, so each side of the
    # boundary is pinned on its own.
    for depth, counted in ((FLIP_DEPTH - 1, 0), (FLIP_DEPTH, 1), (FLIP_DEPTH + 2, 1)):
        accounting = account_errors(
            committed_picks,
            explored=[StandInExploration(AT_FLIP, depth, FLIP_DEPTH)],
            scorer=scorer,
        )
        assert accounting.depth_past_flip_errors == counted


def test_each_branch_is_judged_against_its_own_flip(
    scorer: NullPickScorer, committed_picks
) -> None:
    # The flip is a fact of the branch, not of the campaign: two
    # branches may draw different depths (feature 119 draws one
    # geometric per branch), and each node is judged against its own —
    # depth 3 below a flip at 5 and at it against a flip at 3, in one
    # ask.
    accounting = account_errors(
        committed_picks,
        explored=[
            StandInExploration(BELOW_ONE, 3, 5),
            StandInExploration(AT_FLIP, 3, FLIP_DEPTH),
        ],
        scorer=scorer,
    )
    assert accounting.depth_past_flip_errors == 1


def test_nothing_crossed_answers_zero(
    scorer: NullPickScorer, committed_picks
) -> None:
    # The all-below campaign: every exploration real, zero Type-B
    # errors — a measurement, and the one prd §11's Type-B trend is
    # driving toward.
    accounting = account_errors(
        committed_picks,
        explored=[
            StandInExploration(BELOW_ONE, 1, FLIP_DEPTH),
            StandInExploration(BELOW_TWO, 2, FLIP_DEPTH),
        ],
        scorer=scorer,
    )
    assert accounting.depth_past_flip_errors == 0


def test_an_empty_exploration_collection_answers_zero(
    scorer: NullPickScorer, committed_picks
) -> None:
    # The Type-R campaign's ask — no Type-D facts to hand, because no
    # branch ever flipped and §4.1.2 says wasted depth there is merely
    # inefficient, not this metric's error.  Zero is the honest answer;
    # this is deliberately not the picks ask's refusal, whose rate over
    # an empty denominator is undefined.
    accounting = account_errors(committed_picks, explored=[], scorer=scorer)
    assert accounting.depth_past_flip_errors == 0


def test_the_type_b_side_never_touches_a_label(
    sidecar_labels: dict[str, bool], committed_picks, type_d_explorations
) -> None:
    # Type-B is a fact of depths, read from no label store: the real
    # process over the recording stand-in sidecar reads exactly the four
    # committed picks (once each, in the process's own ask) and never an
    # explored node — the barrier's shape seen from the accounting's
    # side, and the fixture's read log is the proof.
    sidecar = StandInSidecar(sidecar_labels)
    account_errors(
        committed_picks, explored=type_d_explorations, scorer=NullPickScorer(sidecar)
    )
    assert sorted(sidecar.reads) == sorted(sidecar_labels)


# -- The seam's refusals ----------------------------------------------------------


def test_an_undrawn_branch_is_refused_naming_only_the_node(
    scorer: NullPickScorer, committed_picks
) -> None:
    # A branch that never drew a flip presents no flip_depth, and its
    # nodes' position past it is unknown — reading them as below would
    # silently deflate the one figure the count exists to charge, the
    # same direction feature 265 refuses an unlabelled pick for.  The
    # refusal names the node (the caller's own fact) and never the
    # branch, the discipline the oracle's own messages keep.
    for undrawn in (
        StandInExploration(AT_FLIP, FLIP_DEPTH, None),
        DepthOnlyNode(AT_FLIP, FLIP_DEPTH),  # no flip_depth attribute at all
    ):
        with pytest.raises(ErrorAccountingError) as raised:
            account_errors(
                committed_picks, explored=[undrawn], scorer=scorer
            )
        assert AT_FLIP in str(raised.value)
        assert BELOW_ONE not in str(raised.value)


def test_a_flip_below_one_is_refused(
    scorer: NullPickScorer, committed_picks
) -> None:
    # The geometric's support is {1, 2, 3, …} and the support is what
    # keeps every root real: a flip at 0 would sit at depth 0 and retype
    # the campaign Type-R, which §7.3 forbids outright.  A bool flip is
    # refused with it — True is not a depth anyone drew.
    for flip in (0, -2, True):
        with pytest.raises(ErrorAccountingError, match="flip_depth"):
            account_errors(
                committed_picks,
                explored=[StandInExploration(AT_FLIP, 2, flip)],
                scorer=scorer,
            )


def test_a_depth_that_is_not_a_non_negative_integer_is_refused(
    scorer: NullPickScorer, committed_picks
) -> None:
    # The depth is where the tree placed the node and half of §7.2's
    # boundary; a value nobody placed the node at resolves nothing, and
    # a bool is an int in Python's hierarchy but not a placement.
    for depth in (-1, 2.5, True):
        with pytest.raises(ErrorAccountingError, match="depth"):
            account_errors(
                committed_picks,
                explored=[StandInExploration(AT_FLIP, depth, FLIP_DEPTH)],
                scorer=scorer,
            )


def test_a_node_that_cannot_be_named_is_refused(
    scorer: NullPickScorer, committed_picks
) -> None:
    # Every refusal names the node it refuses, so a node that exposes no
    # non-empty text to be named by cannot be refused for anything else
    # — it is refused first, for being unnameable.
    for unnameable in (
        StandInExploration("", 2, FLIP_DEPTH),
        StandInExploration("   ", 2, FLIP_DEPTH),
        object(),
    ):
        with pytest.raises(ErrorAccountingError, match="node_id"):
            account_errors(
                committed_picks, explored=[unnameable], scorer=scorer
            )


def test_a_duplicated_node_is_refused(
    scorer: NullPickScorer, committed_picks
) -> None:
    # The revealed prefix is a set by §10.1's own line, and one node
    # deepened past its flip is one error, not one per spelling: a
    # collection holding it twice would double-charge the count.
    with pytest.raises(ErrorAccountingError, match="twice"):
        account_errors(
            committed_picks,
            explored=[
                StandInExploration(AT_FLIP, FLIP_DEPTH, FLIP_DEPTH),
                StandInExploration(BELOW_ONE, 1, FLIP_DEPTH),
                StandInExploration(AT_FLIP, 4, 5),
            ],
            scorer=scorer,
        )


def test_a_mapping_is_refused_its_keys_are_not_its_explorations(
    scorer: NullPickScorer, committed_picks
) -> None:
    with pytest.raises(ErrorAccountingError, match="mapping"):
        account_errors(
            committed_picks,
            explored={BELOW_ONE: "a node"},
            scorer=scorer,
        )


def test_a_bare_string_is_one_node_spelled_where_the_collection_belongs(
    scorer: NullPickScorer, committed_picks
) -> None:
    with pytest.raises(ErrorAccountingError, match="bare string"):
        account_errors(committed_picks, explored=BELOW_ONE, scorer=scorer)


def test_something_uniterable_is_refused(
    scorer: NullPickScorer, committed_picks
) -> None:
    with pytest.raises(ErrorAccountingError, match="not iterable"):
        account_errors(committed_picks, explored=42, scorer=scorer)


# -- The taxonomy -----------------------------------------------------------------


def test_the_refusal_sits_beside_the_process_s_and_the_penalty_s() -> None:
    # Beside, never under: the penalty (258) refuses a charge on a rate
    # the caller holds, the process (265) refuses the rate itself, and
    # this class refuses the split accounting — three repairs, three
    # places, one shared base so a caller's single except still catches
    # the whole member.
    assert issubclass(ErrorAccountingError, ScoringError)
    assert not issubclass(ErrorAccountingError, NullPickRateError)
    assert not issubclass(ErrorAccountingError, NullPickPenaltyError)
    assert not issubclass(NullPickRateError, ErrorAccountingError)
    assert not issubclass(NullPickPenaltyError, ErrorAccountingError)


def test_the_value_validates_on_construction() -> None:
    # The value is the law's last line: built by the verb or by hand, a
    # rate outside [0, 1] (a count wearing its name), a NaN, a bool, a
    # negative or fractional count — each is refused, so no half-legal
    # accounting escapes a caller that built one itself.
    for rate in (1.4, -0.1, math.inf, True, "0.5"):
        with pytest.raises(ErrorAccountingError):
            ErrorAccounting(commitment_error_rate=rate, depth_past_flip_errors=0)
    for count in (-1, 2.0, True):
        with pytest.raises(ErrorAccountingError):
            ErrorAccounting(commitment_error_rate=0.0, depth_past_flip_errors=count)
    # Both ends of the rate's bound are measurements, honored exactly.
    assert ErrorAccounting(commitment_error_rate=0, depth_past_flip_errors=0) == (
        ErrorAccounting(commitment_error_rate=0.0, depth_past_flip_errors=0)
    )
    assert ErrorAccounting(
        commitment_error_rate=1, depth_past_flip_errors=3
    ).commitment_error_rate == 1.0


def test_the_seam_reads_exactly_the_three_facts_it_names(
    scorer: NullPickScorer, committed_picks
) -> None:
    # The fixture stand-in carries exactly node_id, depth and
    # flip_depth — nothing else — and the accounting answers over it:
    # the proof the seam validates what it reads rather than the type it
    # was handed, the same narrowness the blend's and the index's
    # stand-ins state for their seams.
    narrow = StandInExploration(BELOW_ONE, 1, FLIP_DEPTH)
    assert [field.name for field in dataclasses.fields(narrow)] == [
        "node_id",
        "depth",
        "flip_depth",
    ]
    accounting = account_errors(
        committed_picks, explored=[narrow], scorer=scorer
    )
    assert accounting.depth_past_flip_errors == 0


def test_null_one_is_planted_null_and_the_fixture_campaign_agrees(
    sidecar_labels: dict[str, bool],
) -> None:
    # A fixture-coherence guard in the house style: the campaign the
    # conftest plants is the one the tests above read — two nulls, two
    # reals, a flip at 3 — and the guard names it once, so a later edit
    # that moves the plant moves this test and not seventeen others.
    assert sidecar_labels[NULL_ONE] is True
    assert FLIP_DEPTH == 3
    assert BELOW_TWO == "1a2b3c4d-5e6f-4778-89ab-cdef00000007"
    assert BEYOND_FLIP.endswith("00000009")
    assert AT_FLIP.endswith("00000008")
