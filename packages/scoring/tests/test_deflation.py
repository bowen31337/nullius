"""Feature 259's law: the beta-three deflation penalty.

*System rejects a deflation input taken from raw trial counts, computing
the beta-three term from K_effective instead* (app_spec.xml, "Objective
Scoring & CVaR Aggregation") — prd §7.1's third line (``− β₃ ·
deflation(K_eff)``, line 321) and docs §10.3's (line 496), the one
β-term whose feature sentence is a *rejection*.  The tests here hold
:mod:`scoring._deflation` to the sentence's clauses, in order:

* **rejects a deflation input taken from raw trial counts** — the
  feature's verb, and a rejection of a *shape* rather than a value: a
  bare number (the ledger's plain row count, null nodes included, or
  the ``len(rows)`` a caller computes over them) is refused whatever
  its value, even one that happens to equal the honest count — no
  arithmetic on an integer can say whether it was counted honestly
  (:func:`test_a_raw_trial_count_is_refused`,
  :func:`test_an_honest_count_handed_as_a_number_is_still_refused`);
* **computing the beta-three term from K_effective instead** — the
  input is the derivation: the view feature 93 derives (or feature 94's
  response over it), consumed by the one pooled figure the ledger
  states this term takes, and the haircut itself is §7.3's growth law —
  the expected maximum null Sharpe across K trials, ``√(2·ln K)``,
  pinned here against §7.3's own table and its "the log is on search's
  side" arithmetic (:func:`test_the_haircut_is_section_seven_threes_null_bar`,
  :func:`test_the_bar_matches_the_tables_own_figures`,
  :func:`test_the_charge_follows_the_pooled_figure_not_one_epoch`,
  :func:`test_the_log_is_on_searchs_side`); the count of zero — the
  all-null epoch feature 93 reports rather than omits — and one both
  pay no haircut, a measured figure honored rather than an absence read
  as a stand-in (:func:`test_one_honest_trial_pays_no_haircut`,
  :func:`test_an_epoch_that_charged_nothing_pays_no_haircut`).

And the shape every β-term's suite holds: the term can only subtract
(:func:`test_the_penalty_never_adds`), rides the one seam the objective
ships and composes with the terms that ride it beside
(:func:`test_the_charge_composes_with_the_other_terms`), refuses a
coefficient that could counterfeit a bonus, and owns no component and
no seat (:func:`test_the_term_is_pure_arithmetic_not_a_component`).

Exactness is the suite's own discipline, inherited from the conftest's
fixtures — with the one honest exception this member has to make: the
bar is irrational for every integer ``K ≥ 2``, so no charge it sizes
can be dyadic.  Single charges are therefore pinned with ``==`` against
the same spelling the law computes (``math.sqrt(2.0 * math.log(K))`` —
identical operations in identical order answer identical bits), the
coefficient's proportionality is exact because its multipliers are
powers of two, and the one cross-term composition test asserts with
``pytest.approx`` — the place the divergence suite's all-dyadic figures
cannot reach, and said so here rather than pretended otherwise.  What
these tests deliberately do not reach: composition (``test_component.py``
— the penalty needs no component, which is itself pinned here by the
member's surface), and any
persistence or any read of the trial ledger (the ``replay_score`` row is
feature 255's, and the ledger's rows are the ledger member's data
access — this seam is a function of the view it is handed, pinned
against the real derivation in the cross-member section at the foot).
"""

from __future__ import annotations

import itertools
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from scoring import (
    BETA_FIVE_DEFAULT,
    BETA_FOUR_DEFAULT,
    BETA_SIX_DEFAULT,
    BETA_THREE_DEFAULT,
    AggregationError,
    DeflationPenaltyError,
    DivergencePenaltyError,
    OrthogonalityError,
    RegimeIndexError,
    ScoringError,
    SwitchPenaltyError,
    WorldObjectiveError,
    WorldScore,
    deflation_penalty,
    divergence_penalty,
    switch_penalty,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_SRC = REPO_ROOT / "packages" / "ledger" / "src"

#: The one switch the composition test charges for, at the deployment's
#: own price — dyadic, and the same figure the divergence suite composes
#: with, so the three terms' charges are comparable beside each other.
_COST = 0.5

#: The forward/backtest information-coefficient gap the composition test
#: lands beside this term's charge — a half unit between two dyadic
#: figures, so β₄'s product over it is exact and the only irrational in
#: any composed scalar is this term's own bar.
_GAP = 0.5

#: The two regime names the composition test's switch charge is written
#: in — restated here rather than imported for the reason every member
#: suite restates what it crosses (a member never imports another member,
#: and the count turns on *difference* of names).
_TREND = "high-volatility trend"
_CHOP = "low-volatility chop"


@dataclass(frozen=True)
class _PooledView:
    """A carrier exposing exactly the one attribute this law reads —
    ``total``, the pooled honest count — and nothing else.

    The derivation itself is per-epoch (feature 93 reports a breakdown),
    but this term asks it for the one figure, so this shape composes —
    and composing is what proves the seam validates the figure it reads
    rather than the type it was handed.
    """

    total: int


@dataclass(frozen=True)
class _EpochsView:
    """A stand-in shaped like the derivation feature 93 answers — the
    per-epoch pairs, the epoch lookup, and the pooled total.

    The same three reads feature 94's response fronts, and the shape the
    cross-member section below pins against the real ``KEffective``: a
    naive implementation reaching for ``of(epoch)`` would answer a
    different charge than this view's ``total``, which is exactly what
    :func:`test_the_charge_follows_the_pooled_figure_not_one_epoch`
    holds apart.
    """

    counts: tuple[tuple[str | None, int], ...]

    @property
    def total(self) -> int:
        return sum(count for _, count in self.counts)

    def of(self, epoch: str | None) -> int:
        return dict(self.counts).get(epoch, 0)


@dataclass(frozen=True)
class _BadView:
    """A carrier whose ``total`` is not a count of trials.

    Holds whatever it is handed and exposes it under the one name the
    seam reads, so each malformed figure is refused as itself rather
    than as a type fault the dataclass invented.
    """

    total: object


def _bar(trials: int) -> float:
    """§7.3's growth law, spelled identically to the law's own helper.

    The same operations in the same order — one ``log``, one doubling,
    one ``sqrt`` — so a charge the law computes and a figure this suite
    computes are the same bits, and the ``==`` assertions below are
    assertions about the law rather than about float luck.
    """
    return math.sqrt(2.0 * math.log(trials))


def _charge(trials: int, beta: float = BETA_THREE_DEFAULT) -> float:
    """The haircut at a stated honest count, in the law's own spelling."""
    if trials < 2:
        return 0.0
    return beta * _bar(trials)


# -- the haircut ----------------------------------------------------------------


def test_the_haircut_is_section_seven_threes_null_bar(
    score: WorldScore,
) -> None:
    # The term's reason for existing, in its canonical case: a search
    # that honestly charged four hypotheses is haircut by the expected
    # maximum null Sharpe across four trials — √(2·ln 4) SE units — at
    # the coefficient the deployment named.  The charge is the law's own
    # spelling, asserted with == because the suite spells the bar with
    # the same operations in the same order, and everything the charge
    # did not touch is untouched: the measurement, the identity, the
    # epoch.  The term lands beside the leading term, never through it.
    moved = deflation_penalty(score, k_effective=_PooledView(4))
    assert isinstance(moved, WorldScore)
    assert moved.score == score.score - _charge(4)
    assert moved.ir_oos == score.ir_oos
    assert moved.world_id == score.world_id
    assert moved.node_id == score.node_id
    assert moved.epoch_id == score.epoch_id
    # And the score that was handed over is frozen through the call.
    assert score.score == score.ir_oos


@pytest.mark.parametrize(
    ("trials", "table"),
    [
        (10, 2.15),
        (100, 3.03),
        (1_000, 3.72),
        (10_000, 4.29),
        (100_000, 4.80),
    ],
)
def test_the_bar_matches_the_tables_own_figures(trials: int, table: float) -> None:
    # prd §7.3's first table (lines 345-352) is the growth law's own
    # ground truth — five counts, five bars, stated to two decimals by
    # the document that states the law.  The bar this term charges
    # rounds to every one of them, which pins the spelling (√(2·ln K),
    # in SE units) against something no re-derivation could fudge: a
    # mistaken 2·ln(K)/2, an ln(K²), or a base-10 logarithm each miss at
    # least one row of the table.
    assert round(_bar(trials), 2) == table


def test_one_honest_trial_pays_no_haircut(score: WorldScore) -> None:
    # ln 1 = 0: one honest trial tests one hypothesis, and there is no
    # selection among many to correct — the expected maximum of a single
    # null Sharpe is 0 in SE units, and the growth law says so in
    # arithmetic rather than by a special case this member invented.
    moved = deflation_penalty(score, k_effective=_PooledView(1))
    assert moved == score
    assert moved.score == score.score


def test_an_epoch_that_charged_nothing_pays_no_haircut(
    score: WorldScore,
) -> None:
    # The zero is feature 93's whole point made visible: an epoch whose
    # trials were all null nodes is *reported* at 0 rather than omitted,
    # precisely so the deflation term can be told it contributed no
    # degrees of freedom.  This term honors the telling — the haircut
    # for zero tested hypotheses is nothing, the same figure one honest
    # trial answers — and refusing the 0 would make the ledger's
    # reporting a fact no consumer may state.
    moved = deflation_penalty(score, k_effective=_PooledView(0))
    assert moved == score


def test_the_penalty_never_adds(score: WorldScore) -> None:
    # The spec's verb is *subtracts*, and no path can turn the term
    # around: across a sweep of honest counts spanning one trial to a
    # hundred thousand, the moved score is never above the handed one,
    # and equality is earned exactly where the growth law itself answers
    # zero — the counts below two.  The delta is one negated product of
    # two non-negative factors (a square root and a refused-when-negative
    # coefficient), with no summation and no cancellation in it.
    sweep = [
        deflation_penalty(score, k_effective=_PooledView(trials))
        for trials in (0, 1, 2, 3, 4, 10, 100, 1_000, 100_000)
    ]
    assert all(moved.score <= score.score for moved in sweep)
    assert sum(1 for moved in sweep if moved.score == score.score) == 2


def test_the_log_is_on_searchs_side(score: WorldScore) -> None:
    # §7.3's closing argument is the property this term must price, not
    # fight: *"Going from 1,000 to 100,000 hypotheses raises your
    # significance bar by about 30% while giving you 100× more shots"*.
    # A hundredfold search raises the bar 29%, not a hundredfold — and
    # at the default coefficient the extra charge is ~0.27 of a ratio
    # unit, visible beside a leading term of order one and never a
    # reason the search that found the pick should not have run.
    small = deflation_penalty(score, k_effective=_PooledView(1_000))
    large = deflation_penalty(score, k_effective=_PooledView(100_000))
    ratio = (score.score - large.score) / (score.score - small.score)
    assert ratio == pytest.approx(1.29, abs=0.01)
    assert ratio < 1.3
    assert (small.score - large.score) == pytest.approx(0.27, abs=0.01)
    # And the charge is monotone in the honest count throughout: every
    # hypothesis honestly charged raises the bar, by less and less.
    charges = [
        score.score
        - deflation_penalty(score, k_effective=_PooledView(trials)).score
        for trials in (2, 10, 100, 1_000, 10_000, 100_000)
    ]
    assert all(
        earlier <= later for earlier, later in itertools.pairwise(charges)
    )
    assert all(
        later - earlier < earlier - before
        for before, earlier, later in zip(charges, charges[1:], charges[2:])
    )


def test_the_charge_is_proportional_in_the_coefficient(
    score: WorldScore,
) -> None:
    # The feature's own arithmetic: the delta is one product, so halving
    # and doubling the coefficient halves and doubles the charge — and
    # exactly, because the multipliers are powers of two: the product
    # 0.25·bar is bar quartered without rounding, so doubling it back is
    # the same float the half-coefficient charged.  The count stays
    # fixed so the proportionality is in the coefficient and not in K.
    quarter = deflation_penalty(score, k_effective=_PooledView(100))
    half = deflation_penalty(
        score, k_effective=_PooledView(100), beta=2 * BETA_THREE_DEFAULT
    )
    assert quarter.score == score.score - _charge(100)
    assert half.score == score.score - 2 * _charge(100)
    assert half.score == score.score - 2 * (score.score - quarter.score)


# -- the rejection: the feature's own verb ---------------------------------------


@pytest.mark.parametrize("count", [0, 1, 2, 47, 100, 100_000])
def test_a_raw_trial_count_is_refused(score: WorldScore, count: int) -> None:
    # The spec's verb is *rejects*, and the rejected thing is a deflation
    # input taken from raw trial counts: the ledger's plain row count
    # (TrialLedger.count(), every row, null nodes included) or the
    # len(rows) a caller computes over them.  A bare integer is that
    # shape, and it is refused at any value — including the values that
    # are themselves honest, which is the next test's point.
    with pytest.raises(DeflationPenaltyError, match="raw trial counts"):
        deflation_penalty(score, k_effective=count)


@pytest.mark.parametrize("count", [47.0, 4 / 2, float("nan"), float("inf")])
def test_a_bare_real_is_the_same_refusal(score: WorldScore, count: float) -> None:
    # A float count is no more a derivation than an int is — and NaN or
    # ±inf are the shapes a caller hands when the count never existed.
    # The branch is the number branch, not the coefficient's: the
    # refusal names the raw-count substitution, not a knob.
    with pytest.raises(DeflationPenaltyError, match="raw trial counts"):
        deflation_penalty(score, k_effective=count)


def test_an_honest_count_handed_as_a_number_is_still_refused(
    score: WorldScore,
) -> None:
    # The sharpest edge of the rejection, and the one a reviewer will
    # press: a caller who counted *correctly* — whose 47 is exactly what
    # feature 93's derivation would answer — is refused anyway, because
    # the seam cannot tell that 47 from the inflated one.  Provenance is
    # not checkable at a seam, there is no arithmetic on an integer that
    # could notice a null node hiding inside it, and admitting the lucky
    # numbers is how the inflated ones slip through.  The caller that
    # counted honestly has the derivation in hand already — handing the
    # number instead is the substitution the feature exists to reject.
    view = _PooledView(47)
    moved = deflation_penalty(score, k_effective=view)
    assert moved.score == score.score - _charge(47)
    with pytest.raises(DeflationPenaltyError, match="raw trial counts") as caught:
        deflation_penalty(score, k_effective=47)
    assert "47" in str(caught.value)


@pytest.mark.parametrize("boolean", [True, False])
def test_a_truth_value_is_not_a_derivation(score: WorldScore, boolean: bool) -> None:
    # True is one keystroke from 1 and is an int in Python's hierarchy;
    # it arrives at the same branch the raw counts do, refused as the
    # count it would pass as rather than admitted as a view it is not.
    with pytest.raises(DeflationPenaltyError, match="raw trial counts"):
        deflation_penalty(score, k_effective=boolean)


@pytest.mark.parametrize(
    "carrier", [object(), {}, [], _EpochsView((("epoch-a", 3),)).counts]
)
def test_a_carrier_that_speaks_no_total_is_refused(
    score: WorldScore, carrier: object
) -> None:
    # The derivation's contract is the one figure the ledger states this
    # term consumes: total, the pooled count of budget-charging trials.
    # A carrier that cannot state it — a bare object, a mapping, the
    # per-epoch pairs without the view around them — has no haircut to
    # land, and is refused naming the read rather than escaping as an
    # AttributeError from inside the arithmetic.
    with pytest.raises(DeflationPenaltyError, match="total"):
        deflation_penalty(score, k_effective=carrier)


@pytest.mark.parametrize("total", [None, "47", 47.0, 4 + 0.0, True])
def test_a_total_that_is_not_a_count_is_refused(
    score: WorldScore, total: object
) -> None:
    # The ledger's own view validates its counts (a non-negative int,
    # and not a bool), and the seam that consumes the figure holds the
    # same discipline for the carriers it duck-reads: a None is an
    # absent figure, a string is a type fault, a float is a count that
    # stopped being a count of rows, and True is one keystroke from 1.
    with pytest.raises(DeflationPenaltyError, match="total"):
        deflation_penalty(score, k_effective=_BadView(total))


@pytest.mark.parametrize("total", [-1, -47])
def test_a_negative_total_is_refused(score: WorldScore, total: int) -> None:
    # A negative count of trials is not a number of hypotheses anyone
    # tested — the honest counter cannot move in that direction any
    # more than it may understate, and the refusal names the direction
    # that lets a false discovery through when it is traveled the other
    # way.
    with pytest.raises(DeflationPenaltyError, match="non-negative"):
        deflation_penalty(score, k_effective=_BadView(total))


# -- the honest count: what the term reads, and what it does not -----------------


def test_the_charge_follows_the_pooled_figure_not_one_epoch() -> None:
    # The view is per-epoch because the ledger reports per epoch; the
    # term asks it for the one pooled figure, because §7.3's K is the
    # count of hypotheses *the search* tested — the hunt the pick came
    # out of — and the caller scopes the view to that hunt.  A score
    # measured on epoch-b, over a hunt that charged epoch-a three times
    # and epoch-b fifty, is haircut for all fifty-three: the epoch names
    # where the panels were measured, not the size of the search.
    scored = WorldScore(
        world_id="financial-campaign-01",
        node_id="campaign-01/momentum-branch/d+1",
        ir_oos=0.5,
        score=0.5,
        epoch_id="epoch-b",
    )
    epochs = _EpochsView((("epoch-a", 3), ("epoch-b", 50)))
    moved = deflation_penalty(scored, k_effective=epochs)
    assert moved.score == scored.score - _charge(53)
    # Decisively not the epoch the carrier names: bar(3) is a different,
    # smaller charge, and bar(50) a different one still.
    assert moved.score != scored.score - _charge(3)
    assert moved.score != scored.score - _charge(50)
    assert epochs.of("epoch-b") == 50  # the lookup the term did *not* make


def test_null_only_epochs_reported_at_zero_do_not_move_the_charge(
    score: WorldScore,
) -> None:
    # The consumption side of feature 93's reporting law: epochs whose
    # every trial was a null node enter the view at 0 — the honest
    # count of what they charged — and leave this charge exactly where
    # an epoch never named would, including the un-named bucket.  The
    # null nodes' compute cost is β₁'s sibling business (feature 257);
    # their degrees of freedom are nobody's, and this term charges for
    # those alone.
    with_nulls = _EpochsView((("epoch-a", 7), ("epoch-b", 0), (None, 0)))
    without_their_epochs = _EpochsView((("epoch-a", 7),))
    charged_with = deflation_penalty(score, k_effective=with_nulls)
    charged_without = deflation_penalty(score, k_effective=without_their_epochs)
    assert charged_with.score == charged_without.score
    assert charged_with.score == score.score - _charge(7)


def test_the_term_reads_the_view_it_does_not_count_rows(
    score: WorldScore,
) -> None:
    # The seam is one read, and the read is total: a carrier exposing
    # exactly that attribute — no per-epoch pairs, no epoch lookup, no
    # row access of any kind — composes like the derivation itself.
    # That is the shape that proves the term takes the derivation's
    # answer rather than re-deriving it here, the same division of
    # labour the regime index takes toward the census's labels: one
    # derivation, one spelling, in the member that owns the filter.
    assert deflation_penalty(
        score, k_effective=_PooledView(4)
    ).score == score.score - _charge(4)


# -- the coefficient ------------------------------------------------------------


@pytest.mark.parametrize(
    "beta", [float("nan"), float("inf"), -0.25, -1e-9, True, "0.25", None]
)
def test_a_coefficient_that_cannot_subtract_is_refused(
    score: WorldScore, beta: object
) -> None:
    # NaN and ±inf are not coefficients; a negative one counterfeits a
    # bonus through the penalty seam (the spec's verb is *subtracts*),
    # teaching the loop that searching profligately pays; a bool is an
    # int in Python's hierarchy and not a weight; a string and a None
    # are type faults.  Every one of them is refused, and the branch
    # each lands in names its own fault.
    with pytest.raises(DeflationPenaltyError) as caught:
        deflation_penalty(score, k_effective=_PooledView(100), beta=beta)
    # Only the negative coefficient is refused on the verb's own
    # sentence — that is the branch whose message names the inversion
    # (a bonus for profligate search).  A bool is refused one step
    # earlier, by the type gate, and NaN/±inf by the finiteness gate.
    if isinstance(beta, float) and beta < 0.0:
        assert "profligately" in str(caught.value)


def test_a_zero_coefficient_declines_the_charge_not_the_term(
    score: WorldScore,
) -> None:
    # Zero is admitted — an ablation the documents leave to the
    # deployment, not a contradiction of the term: a deployment that
    # zeroes β₃ has declined to price multiple testing, the way feature
    # 262 admits a zeroed β₆ and feature 261 a zeroed β₅.  The honest
    # count is still required and still validated, which is what keeps
    # this a declined charge rather than an unassembled term.
    assert (
        deflation_penalty(score, k_effective=_PooledView(100), beta=0.0)
        == score
    )


def test_the_default_coefficient_is_a_stated_parameterization() -> None:
    # Neither document sizes β₃ — the formula spells the term and moves
    # on — so the default is the member's own stated parameterization.
    # The base quarter rather than β₄'s deliberate half, on the term's
    # own arithmetic: the factor it scales is already the largest in the
    # formula at realistic counts (§7.3's bar crosses 3.0 at a hundred
    # honest trials, where β₄'s bound caps at 2.0 and β₆'s payment at
    # 1.0), so the coefficient takes the base and lets the log do the
    # scaling.  The test pins the ordering rather than only the figure,
    # because the reason is on the section's own table.
    assert BETA_THREE_DEFAULT == 0.25
    assert BETA_THREE_DEFAULT == BETA_FIVE_DEFAULT == BETA_SIX_DEFAULT
    assert BETA_THREE_DEFAULT < BETA_FOUR_DEFAULT


# -- the carrier -----------------------------------------------------------------


@dataclass(frozen=True)
class _OnlySeam:
    """A carrier exposing exactly the one attribute this law reads off
    the score — ``adjusted`` — and nothing else, not even a measurement.

    The deflation penalty measures nothing off the pick's panel and
    deliberately reads nothing off the score's epoch (the epoch is where
    the panel was measured, not the scope of the hunt), so this shape
    composes, and composing is what proves the seam validates what it
    reads rather than the type it was handed.
    """

    score: float

    def adjusted(self, delta: float) -> _OnlySeam:
        return _OnlySeam(self.score + delta)


def test_the_term_measures_nothing_off_the_carrier() -> None:
    # A carrier holding a scalar and the seam — no world, no pick, no
    # epoch, no measurement — is charged like any world score, which is
    # the docstring's claim that the haircut is a fact about the honest
    # count, landed beside the score it moves.
    moved = deflation_penalty(_OnlySeam(1.0), k_effective=_PooledView(4))
    assert moved.score == 1.0 - _charge(4)


def test_a_carrier_without_the_seam_is_refused() -> None:
    with pytest.raises(DeflationPenaltyError, match="adjusted"):
        deflation_penalty(object(), k_effective=_PooledView(4))


def test_the_charge_composes_with_the_other_terms(score: WorldScore) -> None:
    # The β-terms ride one seam, so the charge must land on a score
    # another term has already moved — the measurement still pinned, the
    # identity still untouched — and the order the caller applies terms
    # in is the caller's.
    penalized = score.adjusted(-0.1)
    moved = deflation_penalty(penalized, k_effective=_PooledView(100))
    assert moved.score == penalized.score - _charge(100)
    assert moved.ir_oos == score.ir_oos
    assert moved.node_id == score.node_id


def test_both_orders_of_two_terms_land_on_the_same_scalar() -> None:
    # The same composition against the divergence and switch penalties,
    # on their own dyadic charges beside this term's irrational one: the
    # bar is irrational for every integer K ≥ 2, so the one place the
    # sibling suites pin bit-exact orderings is closed here — and the
    # honest assertion is approx, with the reason stated, rather than a
    # fixture pretending √(2·ln 4) is dyadic.  Divergence then deflation
    # and deflation then divergence both land within a float epsilon of
    # the same scalar, which is the property the terms landing through
    # one seam depend on: no term's delta can see another's.
    scored = _OnlySeam(0.5)
    charged = deflation_penalty(scored, k_effective=_PooledView(4))
    diverged = divergence_penalty(scored, ic_forward=0.0, ic_backtest=_GAP)
    both_a = deflation_penalty(
        diverged, k_effective=_PooledView(4)
    )
    both_b = divergence_penalty(charged, ic_forward=0.0, ic_backtest=_GAP)
    assert both_a.score == pytest.approx(both_b.score, rel=1e-12)
    assert both_a.score == pytest.approx(
        0.5 - _charge(4) - BETA_FOUR_DEFAULT * _GAP, rel=1e-12
    )
    # And with the switch penalty, the third term on the same seam: all
    # three orders of the three charges agree to the same scalar — β₄
    # over the half-unit gap, β₅ over one crossing at the stated price,
    # both dyadic so the only irrational in the sum is this term's own.
    three_a = switch_penalty(
        divergence_penalty(charged, ic_forward=0.0, ic_backtest=_GAP),
        (_TREND, _CHOP),
        switch_cost=_COST,
    )
    three_b = divergence_penalty(
        switch_penalty(charged, (_TREND, _CHOP), switch_cost=_COST),
        ic_forward=0.0,
        ic_backtest=_GAP,
    )
    three_c = deflation_penalty(
        switch_penalty(diverged, (_TREND, _CHOP), switch_cost=_COST),
        k_effective=_PooledView(4),
    )
    assert three_a.score == pytest.approx(three_b.score, rel=1e-12)
    assert three_b.score == pytest.approx(three_c.score, rel=1e-12)
    assert three_c.score == pytest.approx(
        0.5 - _charge(4) - BETA_FOUR_DEFAULT * _GAP - BETA_FIVE_DEFAULT * _COST,
        rel=1e-12,
    )


# -- determinism, vocabulary, surface --------------------------------------------


def test_the_same_view_answers_the_same_charge(score: WorldScore) -> None:
    # Deterministic and pure: the same view — asked twice, or asked on a
    # score another term has moved — answers the same charge to the last
    # bit, because the bar is one logarithm and one square root over the
    # pooled count and the delta one negated product of it.  There is no
    # summation whose order could matter, and no clock, store or
    # environment anywhere in the term.
    view = _EpochsView((("epoch-a", 3), ("epoch-b", 50)))
    first = deflation_penalty(score, k_effective=view)
    again = deflation_penalty(score, k_effective=_EpochsView(view.counts))
    assert first == again
    assert first.score == score.score - _charge(53)


def test_the_error_is_a_sibling_of_the_others() -> None:
    # 256 refuses an ask that cannot be scored; 262 one whose bonus
    # cannot be measured; 261 one whose charge cannot be counted; 260
    # one whose divergence cannot be read; 259 one whose haircut cannot
    # be trusted — and the repairs differ (a sequestration fault, a
    # resident-array hole, a census that has not run, a mis-set price,
    # the forward-test record, the trial ledger), so the classes stay
    # distinguishable behind separate excepts — the reasoning that keeps
    # every sibling in this member apart, held here for the fourth
    # β-term to land.
    assert issubclass(DeflationPenaltyError, ScoringError)
    for other in (
        WorldObjectiveError,
        OrthogonalityError,
        SwitchPenaltyError,
        DivergencePenaltyError,
        AggregationError,
        RegimeIndexError,
    ):
        assert not issubclass(DeflationPenaltyError, other)
        assert not issubclass(other, DeflationPenaltyError)


def test_the_term_is_pure_arithmetic_not_a_component() -> None:
    # Like the blend, the index, the bonus and the two landed penalties,
    # the deflation charge owns no deployment state, so it adds no
    # component beside the objective and no seat beside the member's:
    # the surface it joins is the member's namespace, and the composed
    # "scoring" component stays the per-world objective — the growth
    # pattern every free seam in this workspace takes.
    import scoring

    assert "deflation_penalty" in scoring.__all__
    assert "BETA_THREE_DEFAULT" in scoring.__all__
    assert "DeflationPenaltyError" in scoring.__all__
    assert scoring.COMPONENT_NAME == "scoring"


# -- the cross-member seam --------------------------------------------------------


class TestTheHaircutRidesTheRealDerivation:
    """Feature 259's seam, driven by the derivation it was written for.

    The workspace contract is that no member imports another, and the
    remedy everywhere a shape has to be shared is the same: the shape is
    *restated* in the member that needs it, and a test against the real
    value is what keeps the restatement honest — the discipline
    ``test_cross_member.py`` states for the census seam, applied here to
    the ledger's.  What this section pins is that the **real**
    ``K_effective`` derivation (feature 93) and the **real** response
    feature 94 frames it in satisfy the surface :func:`deflation_penalty`
    duck-reads, and that the two members' halves of §10.3's third line
    compose: one hundred rows of which ninety-three were null nodes
    charge the pick for the seven that spent degrees of freedom, and for
    nothing else — prd §4's law, held at the seam that consumes it.

    The imports are inside the tests for the reason the census file
    states: a module-scope ``import ledger`` would fail this member's
    suite to collect wherever the sibling is absent, while in a function
    the absence costs one test, and that test says what is missing.  The
    path insert is the same bootstrap every member suite performs for
    itself, applied to a sibling.
    """

    def _ledger(self):
        """The ledger member's derivation modules, imported in-function."""
        if str(LEDGER_SRC) not in sys.path:
            sys.path.insert(0, str(LEDGER_SRC))
        ledger = pytest.importorskip(
            "ledger", reason="the ledger member is not in this workspace"
        )
        return pytest.importorskip(
            f"{ledger.__name__}.keffective",
            reason="the derivation module is not where its member keeps it",
        )

    def test_the_real_derivation_charges_the_honest_count(
        self, score: WorldScore
    ) -> None:
        # One hundred trial rows, of which seven charged budget and
        # ninety-three were null nodes (feature 90's opaque directive,
        # restated as the pairs the derivation reads): the charge is the
        # bar of *seven*, exactly — the count that spent degrees of
        # freedom — and the ninety-three nulls move it by nothing,
        # however many of them the campaign ran.
        keffective = self._ledger()
        trials = [("epoch-a", True)] * 7 + [("epoch-a", False)] * 93
        view = keffective.derive_k_effective(trials)
        moved = deflation_penalty(score, k_effective=view)
        assert view.total == 7
        assert moved.score == score.score - _charge(7)

    def test_the_real_route_response_rides_the_same_seam(
        self, score: WorldScore
    ) -> None:
        # Feature 94's response fronts the derivation as *the deflation
        # input* — and it satisfies the same duck-read, so the route a
        # scoring process would consume is the view this term charges
        # from, drawn one way.  Its own docstring says there is
        # deliberately no raw trial count on it; this is the term that
        # refused to be handed one.
        keffective = self._ledger()
        ledger = pytest.importorskip(
            "ledger", reason="the ledger member is not in this workspace"
        )
        route = pytest.importorskip(
            f"{ledger.__name__}.keffective_route",
            reason="the route module is not where its member keeps it",
        )
        view = keffective.derive_k_effective(
            [("epoch-a", True)] * 4 + [("epoch-b", False)]
        )
        response = route.KEffectiveResponse(view)
        moved = deflation_penalty(score, k_effective=response)
        assert moved.score == score.score - _charge(4)

    def test_a_derivation_of_nothing_charges_nothing(self, score: WorldScore) -> None:
        # The empty ledger and the all-null ledger both derive to a view
        # whose total is zero, and both pay no haircut — the two states
        # feature 93's ``__bool__`` deliberately answers the same, and
        # the honest reading of either here is that no hypothesis spent
        # anything.  The term is still callable: it declines the charge
        # and answers the score unchanged rather than refusing to be
        # asked.
        keffective = self._ledger()
        empty = keffective.derive_k_effective([])
        all_null = keffective.derive_k_effective(
            [("epoch-a", False), ("epoch-b", False)]
        )
        assert deflation_penalty(score, k_effective=empty) == score
        assert deflation_penalty(score, k_effective=all_null) == score
