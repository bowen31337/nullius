"""The paired continuous statistic — feature 281, and the comparison's own shape.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 281: *System rejects a
difference-in-proportions comparison, using a paired continuous statistic over
the same worlds instead.*  docs/alpha-engine-prd.md §11.0 states the rule the
sentence exists to enforce, and states it as a decision about the *statistic*
rather than about the experiment:

    Raw FDR is a proportion, and proportions are power-poor.  Detecting
    ``0.30 → 0.21`` at 80% power needs ~364 independent commits per arm;
    replays clustered by world inflate that by the design effect to well over
    a thousand.  That test is not buildable at this scale.

    Fix the statistic, not the ambition.  **Score each commit continuously**
    using the out-of-sample IR of the committed pick, which is continuous and
    zero in expectation under the null, and run the comparison **paired** —
    same policy pair, same worlds.  A paired t-test detecting ``ΔIR = 0.3``
    with ``σ_diff ≈ 0.8`` needs ~56 worlds, which is reachable.

docs/nullius-tech-architecture.md §10.3.1 restates it as the reason the M3 gate
is written the way it is — *"Policy comparison uses a **paired** continuous
statistic — OOS IR of the committed pick, same policy pair on the same worlds —
not a difference in proportions"* — and Appendix B carries the arithmetic of
both arms of the comparison:

    Paired-test n for ΔIR at 80% power    n ≈ 8(σ_diff/Δ)²   → ~56 at σ=0.8, Δ=0.3

**Why the sentence needs a module rather than a convention.**  The quantity the
M3 gate reads is ``FDR_deploy``, which is a *proportion*, and every arm of the
dreaming loop produces a binary outcome per committed pick.  So a difference in
proportions is the comparison a caller will reach for, and it is the one
comparison this pool cannot fund: §11.0's ~364 independent commits per arm
before clustering is two orders of magnitude past what §C5's loop runs.  A
convention would leave that comparison available and merely discouraged, and
the failure mode is the one §12 names for the whole system — *"Non-determinism
does not announce itself; it just slowly makes every conclusion wrong"* is the
same shape of sentence as an under-powered test: it returns a number, the
number looks like a p-value, and the conclusion it supports is wrong.  So the
refusal is a **raised error** rather than a docstring, and the replacement is a
function the caller reaches instead.

What this module is
-------------------

Three spellings of one act, and the record they answer with:

* :func:`paired_ir_difference` — the feature's own call: two arms' per-world
  out-of-sample IR readings in, a :class:`PairedDifference` out.  The paired
  t-statistic over the worlds **both arms carry**, with the sample standard
  deviation of the differences, the standard error, and the two-sided
  ``p``-value at :data:`PAIRED_LEVEL`;
* :func:`rejects_proportion_comparison` — the **rejects** of the sentence, and
  the shape the ladder's other verdicts take
  (:func:`dreaming.ladder.rejects_thin_pool`,
  :func:`dreaming.ceiling.rejects_uncapped_sweep`,
  :func:`dreaming.cap.revision_cap`): a verdict over a figure the caller
  already holds, never a count.  Given the proportion the caller means to
  compare and the two arm sizes, it decides whether such a test is buildable
  at this scale — via §11.0's own ``n ≈ 8(σ_diff/Δ)²`` — and raises
  :class:`~dreaming.errors.ProportionComparisonError` when it is not, naming
  the paired statistic the caller should ask for instead;
* :func:`paired_pool_difference` — the same judgment over the **store**: the
  arms' world-keyed readings read from the pool's own ``replay_score`` rows.

And the answer is a :class:`PairedDifference`: the world count the pair was
taken over, the two arms' means, the mean difference, the sample deviation of
the differences, the standard error, the ``t`` statistic and the two-sided
``p``-value — the facts §11.0's M3 gate is evaluated on, carried together the
way a :class:`~dreaming.split.PoolSplit` carries its halves, so an operator
reading a comparison can see *which* comparison it was rather than only that it
was one.

The statistic
-------------

**Paired, because the pairing is what buys the power.**  §11.0's move is not
merely *use a continuous figure*; it is *differencing world by world and
testing the differences*.  The two arms replay the **same worlds**, so the
world-to-world variation that dominates each arm's readings cancels inside each
difference, and what is left is a sample of one number per world whose spread
is ``σ_diff`` — ≈0.8 in the PRD's arithmetic rather than the ≈2.6 an unpaired
reading of the same worlds would carry.  That is the entire ``~364 → ~56``
improvement, and it is why this module **refuses** rather than drops a world
that carries only one arm's figure: a dropped world silently converts the
comparison into the unpaired one it was chosen to avoid, and the number that
comes out still looks like a paired ``t``.

**The formula is the module's one piece of arithmetic, stated as the PRD
states it.**  For ``n`` paired differences ``dᵢ`` with mean ``d̄``:

    s      = sqrt( Σ(dᵢ − d̄)² / (n − 1) )      the sample deviation
    SE     = s / sqrt(n)                       the standard error
    t      = d̄ / SE                            the test statistic
    p      = 2 · (1 − Φ(|t|))                  two-sided, at PAIRED_LEVEL

``(n − 1)`` and not ``n``: the deviation is an *estimate* from a sample, and the
Bessel correction is what makes the interval/variance estimate unbiased — the
distinction Appendix B's ``SE(IC), n observations ≈ 1/√n`` glosses over for a
*known* ``σ`` and which matters here, where ``σ_diff`` is measured from the
same worlds the test is run on.  ``Φ`` is :class:`statistics.NormalDist`'s, the
stdlib normal the workspace already reaches for its quantiles: at the ``~56``
worlds §11.0 sizes the test at, the normal is the right limit and the workspace
has no Student-``t`` survival function to hand.  The approximation is stated
rather than hidden — :attr:`PairedDifference.method` names it, and the
``p``-value is carried beside the ``t`` and the ``n`` it came from so a reader
who needs the exact ``t`` tail has every input it requires.

**The null is IR = 0, and it is not a parameter.**  §11.0's figure is *"the
out-of-sample IR of the committed pick, which is continuous and zero in
expectation under the null"*, so the hypothesis the test is against is *the
arms read the same on these worlds* — a difference of zero.  A one-sample
``t`` against zero is therefore the whole of it, and a caller that wants to
test against a non-zero difference is asking a question §11.0 does not pose:
the M3 gate's bar (feature 280's ``√(2 ln M) · σ_V / √n_worlds``) is applied to
the *advantage* the difference represents, not folded into the hypothesis.  A
``mu`` keyword would invite exactly that fold, so there is none.

What this module is not
-----------------------

**It is not the ``√(2 ln M)`` bar, the selector, the split, or the evaluator.**
Deciding whether the *winning* revision clears its selection bar is feature
280's sentence; running ``M`` revisions and selecting the argmax are features
271-274; the train/holdout split is feature 278's and this module reads neither
half by name — it compares whatever worlds the caller hands it, which is what
makes the same function serve the holdout report (feature 278's *"report on
holdout"*) and the M2-baseline comparison M3's exit criterion is written
against.  Evaluating a candidate against a world (feature 272) is the loop's
own act; this module reads the scores that produced and never runs a policy.

**It reads the pool and writes nothing.**  :func:`paired_pool_difference` reads
``replay_score`` — the two columns that name a reading, ``world_id`` and
``score``, plus the ``policy_version`` the arm is selected by — and touches no
row: the same read-time discipline :mod:`dreaming.split` states for the pool's
membership, and for the same reason, since feature 270 holds the pool fixed
while a cycle walks it and a comparison that wrote would be the mutation the
hold exists to refuse.  No new component either: feature 270's single
``"dreaming"`` component is the member's whole composition, and the comparison
is reached the way the floor, the cap, the ceiling and the split are, as free
functions beside the store.  No seat edit, no migration, no third party:
``math`` and ``statistics`` — the latter stdlib's normal distribution and
nothing else — so the factory's scan, which imports this package to fire its
``@register``, pays nothing for the comparison.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from .cycle import sqlite_path
from .errors import (
    FreezeRequestError,
    PairedComparisonError,
    ProportionComparisonError,
)
from .layout import DATABASE_URL_ENV, REPLAY_SCORE_TABLE, pool_tables_present

__all__ = [
    "PAIRED_CODE",
    "PAIRED_LEVEL",
    "POWER",
    "PROPORTION_CODE",
    "PROPORTION_DESIGN_EFFECT",
    "PairedDifference",
    "paired_ir_difference",
    "paired_pool_difference",
    "power_capacity",
    "rejects_proportion_comparison",
]

#: The code a *proportion-comparison* refusal opens with — the caller asked for
#: the one comparison §11.0 says is not buildable at this scale — so the
#: rejection is greppable by the word that names it.  Feature 281's sentence
#: mandates no token (*"rejects a difference-in-proportions comparison"* names
#: its subject in prose), so this code is this module's own, minted on the
#: ``pool_frozen`` / ``pool_too_thin`` / ``illegal_theme`` convention the
#: workspace states for a refusal an operator greps for.
PROPORTION_CODE = "proportion_comparison"

#: The code a *pairing* refusal opens with — the paired statistic is the right
#: one and the worlds handed to it do not pair.  A distinct code from
#: :data:`PROPORTION_CODE` because the two are different repairs on the same
#: sentence: *ask for the paired statistic* against *compare the arms over the
#: worlds that carry both*.  An operator grepping one word must land on one
#: repair, which is why they are not one token with a differing message.
PAIRED_CODE = "unpaired_worlds"

#: The two-sided confidence level the ``p``-value is reported at — 95%.  §11.0
#: writes the gate as *"ΔIR = 0.3 with σ_diff ≈ 0.8 needs ~56 worlds"* at 80%
#: **power** and PRD §12's M3 exit criterion states it as *"Paired ΔIR > 0.3
#: with ``p < 0.05``"*, so :data:`PAIRED_LEVEL` and :data:`POWER` are the two
#: figures that arithmetic is computed at.  Named as data rather than left as a
#: literal inside the arithmetic because both are *claims* about the figure —
#: a ``p``-value without its level, and a required ``n`` without its power, are
#: numbers nobody can check against the criterion they came from.
PAIRED_LEVEL = 0.95

#: The power §11.0's ``n ≈ 8(σ_diff/Δ)²`` is derived at — ``0.8``, the
#: conventional ``1 − β`` and the figure the PRD's "80% power" names.  It is
#: the ``8`` in that formula (``2(z_{α/2} + z_β)²`` at 95%/80%), so it is
#: consumed by :func:`power_capacity` rather than respelled there.
POWER = 0.80

#: The two-sided quantile for :data:`PAIRED_LEVEL` — computed rather than
#: written as a literal, the discipline :mod:`signal_agent._discrimination`
#: states for its own interval.  ``1.96`` is the folklore spelling of
#: ``1.959963984540054``; a magic constant in an arithmetic the PRD's ``~56
#: worlds`` is derived from would be a number nobody could check against the
#: criterion it claims to serve.  Every sizing calculation in this module reads
#: it from here, so the ``p``-value's level and the required-``n`` levels
#: cannot disagree on what :data:`PAIRED_LEVEL` means.
_Z_ALPHA = statistics.NormalDist().inv_cdf(1.0 - (1.0 - PAIRED_LEVEL) / 2.0)

#: The two-sided normal tail, spelled once so the ``p``-value and the capacity
#: judgement cannot disagree on what "two-sided" means.
_TWO_SIDED = 2.0

#: The design effect §11.0 attributes to clustering replays by world —
#: *"replays clustered by world inflate that by the design effect to well over
#: a thousand"*.  Named as a knob rather than folded into the arithmetic
#: because §11.0 states it as an order-of-magnitude floor and not as an
#: estimate this member can reproduce from the evidence it holds; a caller
#: with a measured effect passes its own.  The refusal's direction does not
#: depend on the exact factor at any pool size §12.1's ladder admits.
#:
#: Deliberately **not** a parameter of :func:`_proportion_arm_size`: that
#: function sizes the *unclustered* two-proportion test, which is the
#: formula's own quantity and the figure §11.0 quotes as "~364".  The
#: clustering is applied by the caller
#: (:func:`rejects_proportion_comparison`) as a multiple of the independent
#: requirement, so the two figures the refusal compares are computed on the
#: same terms.
PROPORTION_DESIGN_EFFECT = 4.0


def _validated_figure(value: Any, *, name: str, code: str, error: type[Exception]) -> float:
    """Check that ``value`` is a finite real figure, or refuse it by name.

    The one spelling of what each of this module's numbers must be, shared by
    the arm readings, the proportions and the arm sizes: a finite real.  A
    ``bool`` is refused where a figure belongs — ``True`` is ``1`` in Python,
    so a flag where an IR belongs would read as a unit reading and a flag where
    an arm size belongs as one commit — and ``nan``/``inf`` are refused because
    they are not readings at all: a ``nan`` difference propagates into the
    mean, the deviation and the ``t`` and returns a ``nan`` ``p``-value, which
    is a comparison that produced no number while appearing to have produced
    one.  Refused in the caller's own vocabulary (``code`` and ``error``), so
    the message names the figure and the code the caller greps for.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error(
            f"{code}: {name} is a number — got {value!r} "
            f"({type(value).__name__}); the comparison is arithmetic over "
            "measured figures, and a value that is not one names no reading "
            "this statistic can be taken over"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise error(
            f"{code}: {name} is a finite number — got {value!r}; a non-finite "
            "reading propagates through the mean, the deviation and the "
            "statistic and returns a ``p``-value that is not a number, which "
            "is a comparison that produced nothing while looking like it "
            "produced something"
        )
    return figure


def power_capacity(
    delta: Any,
    *,
    spread: Any,
    power: Any = POWER,
) -> int:
    """How many paired worlds ``delta`` at ``spread`` needs — §11.0's own arithmetic.

    Appendix B's ``n ≈ 8(σ_diff/Δ)²`` at 80% power, generalised to any power
    through its derivation ``n = (z_{α/2} + z_β)² · (σ_diff/Δ)²`` — the ``8``
    is that expression at 95%/80% and nothing else, so ``power`` is a keyword
    rather than a literal folded into an 8.  The answer is rounded **up**: the
    figure is a *requirement*, and a pool one world short of it is a pool that
    does not fund the test — rounding to nearest would report 56 required
    worlds for a figure of 56.4, and a caller reading 56 would size its pool to
    a number the arithmetic does not support.

    ``delta`` is the difference the comparison is meant to detect (PRD §11.0's
    target advantage, 0.3) and ``spread`` the sample deviation of the paired
    differences (its ``σ_diff``, ≈0.8), so the ratio is *signal over noise* —
    the quantity the whole power calculation is a function of.  A ``delta`` of
    zero is **refused** rather than answered with an infinity: an effect of
    zero is detected by no number of worlds, and an infinite requirement
    returned as a float would be a number a caller could compare against a pool
    size and act on, which is the failure this module's sibling classes exist
    to prevent.  ``spread`` of zero is admitted and answers zero — two arms
    that read identically on every world need no worlds to be told apart, and
    the arithmetic's own value is right there.

    Refuses, in this order, each naming what it is about: a ``delta``,
    ``spread`` or ``power`` that is not a finite real; a ``power`` outside the
    open interval ``(0, 1)`` — a power of one needs an infinite ``z_β``, and a
    power of zero or less is not a power; and a ``delta`` of zero, by name.
    """
    effect = _validated_figure(
        delta,
        name="the difference the comparison must detect",
        code=PROPORTION_CODE,
        error=ProportionComparisonError,
    )
    deviation = _validated_figure(
        spread,
        name="the sample deviation of the paired differences",
        code=PROPORTION_CODE,
        error=ProportionComparisonError,
    )
    wanted = _validated_figure(
        power, name="the power", code=PROPORTION_CODE, error=ProportionComparisonError
    )
    if not 0.0 < wanted < 1.0:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: the power a comparison is sized at lies "
            f"strictly between none and certain — got {power!r}; §11.0's "
            "arithmetic is stated at 80% power, and a power of one needs a "
            "``z`` this calculation cannot answer while a power at or below "
            "zero asks for a number of worlds that means nothing"
        )
    if effect == 0.0:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: the difference a comparison must detect is "
            "not zero — got 0.0; an effect of zero is detected by no number "
            "of worlds at all, so the requirement is infinite rather than "
            "large, and answering it with a figure a caller could compare "
            "against its pool size would be handing it a number to act on "
            "where the honest answer is that no pool funds this"
        )
    if deviation == 0.0:
        return 0
    beta_quantile = statistics.NormalDist().inv_cdf(wanted)
    return max(
        2,
        math.ceil(((_Z_ALPHA + beta_quantile) ** 2) * (deviation / effect) ** 2),
    )


def _validated_arm(
    readings: Any, *, name: str, code: str, error: type[Exception]
) -> dict[str, float]:
    """Check that ``readings`` are an arm's per-world figures, or refuse them.

    An arm is a mapping of world id to the arm's out-of-sample IR reading on
    that world — the shape §10.3.1's *"same policy pair on the same worlds"*
    needs to pair two of them at all.  The world id is non-empty text, matching
    every other world seam in this member (the split's ``pool_worlds``, the
    commitment's membership), and the reading is a finite real
    (:func:`_validated_figure`).  A bare string is refused where a mapping
    belongs, and the refusal is explicit rather than incidental: Python would
    iterate a string's *characters*, and a nine-character world id would
    silently become nine one-character worlds reading nothing — an arm nobody
    holds, compared against another one, with the ``t`` statistic coming out
    finite and the ``p``-value looking like a result.

    An iterable of readings with no world ids is refused too, and that refusal
    is the module's central claim expressed as an input check: without ids
    there is **nothing to pair**, so a sequence of figures is two samples
    rather than one set of differences, and accepting it would mean pairing by
    position — which is the unpaired comparison §11.0 rejects, wearing the
    signature of the paired one.
    """
    if isinstance(readings, (str, bytes)):
        raise error(
            f"{code}: an arm's readings are a mapping of world id to figure — "
            f"got the single {type(readings).__name__} {readings!r}; a bare "
            "string names one world, and iterating it would read its "
            "characters as worlds nobody holds"
        )
    if not isinstance(readings, Mapping):
        raise error(
            f"{code}: an arm's readings are a mapping of world id to figure — "
            f"got {readings!r} ({type(readings).__name__}); the comparison is "
            "*paired*, so each arm must say which world each figure is about, "
            "and figures with no world ids are two samples rather than one set "
            "of differences (see docs/alpha-engine-prd.md §11.0). Pass a "
            "mapping of world id to reading, or read one from the pool with "
            "paired_pool_difference"
        )
    arm: dict[str, float] = {}
    for world_id, reading in readings.items():
        if not isinstance(world_id, str) or not world_id.strip():
            raise error(
                f"{code}: a world is named by a non-empty string — got "
                f"{world_id!r} ({type(world_id).__name__}); the two arms are "
                "paired by world, and an id that names no world pairs nothing"
            )
        arm[world_id] = _validated_figure(
            reading,
            name=f"the {name} reading for world {world_id!r}",
            code=code,
            error=error,
        )
    return arm


def _validated_spread(value: Any, *, code: str, error: type[Exception]) -> float:
    """Check that ``value`` is a positive deviation, or refuse it.

    The scale the comparison is judged against — §11.0's ``σ_diff`` — which
    must be strictly positive: a deviation of zero is a pool on which every
    difference is identical, and the ``t`` statistic is a division by zero.  A
    literal ``0.0`` reaching the arithmetic would raise Python's own
    ``ZeroDivisionError``, which is a fact about floats rather than about the
    pool, and the caller would meet the interpreter's vocabulary for a refusal
    that is this member's to state.
    """
    deviation = _validated_figure(value, name="the pool's spread", code=code, error=error)
    if deviation <= 0.0:
        raise error(
            f"{code}: the spread the comparison is judged against is strictly "
            f"positive — got {value!r}; a deviation of zero is a pool whose "
            "every difference is the same, and the statistic is a division by "
            "exactly nothing"
        )
    return deviation


class PairedDifference:
    """One taken paired comparison — feature 281's answer.

    The row's facts and nothing derived: how many worlds the pair was taken
    over, each arm's mean reading, the mean difference, the sample deviation of
    the differences, the standard error, the ``t`` statistic and the two-sided
    ``p``-value.  Carried as one immutable value rather than handed back as a
    bare p-value for the reason :class:`dreaming.split.PoolSplit` gives: §11.0's
    M3 exit criterion is *"Paired ΔIR > 0.3 with ``p < 0.05``"*, and a caller
    shown a ``0.04`` with no ``n``, no ``ΔIR`` and no ``σ_diff`` beside it has
    been handed a number it cannot check against the criterion the number
    exists to serve.

    Held as a value rather than a live view, and answering :meth:`clears` for
    the caller that only wants the verdict: the decision itself (feature 280's
    ``√(2 ln M)`` bar, and what the gate does about a cleared one) is another
    feature's, so this record carries the facts and states no verdict of its
    own beyond the two figures the PRD's criterion is written in.
    """

    __slots__ = (
        "_differences",
        "baseline_mean",
        "candidate_mean",
        "mean_difference",
        "method",
        "p_value",
        "paired_worlds",
        "spread",
        "standard_error",
        "t_statistic",
    )

    def __init__(
        self,
        *,
        paired_worlds: int,
        candidate_mean: float,
        baseline_mean: float,
        mean_difference: float,
        spread: float,
        standard_error: float,
        t_statistic: float,
        p_value: float,
        differences: tuple[tuple[str, float], ...],
        method: str = "paired t, normal two-sided",
    ) -> None:
        #: How many worlds the pair was taken over — the ``n`` Appendix B's
        #: ``n ≈ 8(σ_diff/Δ)²`` is computed against, so a reader comparing this
        #: comparison's power against the pool it came from has the figure.
        self.paired_worlds = paired_worlds
        #: The candidate arm's mean reading — §C5's ``M`` revisions.
        self.candidate_mean = candidate_mean
        #: The baseline arm's mean reading — the M2 fixed policy
        #: (``docs/alpha-engine-prd.md`` §12) the gate compares against.
        self.baseline_mean = baseline_mean
        #: The mean **paired** difference, world by world: the ``ΔIR`` §11.0's
        #: criterion is written in.
        self.mean_difference = mean_difference
        #: The sample deviation of the per-world differences — §11.0's
        #: ``σ_diff``, Bessel-corrected because it is estimated from the same
        #: worlds the test runs on.
        self.spread = spread
        #: The standard error of the mean difference: ``spread / sqrt(n)``.
        self.standard_error = standard_error
        #: The test statistic: ``mean_difference / standard_error``.
        self.t_statistic = t_statistic
        #: The two-sided ``p``-value at :data:`PAIRED_LEVEL`.
        self.p_value = p_value
        #: Which tail limit produced :attr:`p_value`, named rather than
        #: implied: the normal is the right limit at the ~56 worlds §11.0
        #: sizes the test at, and at a handful of worlds a reader may want the
        #: exact Student ``t`` tail instead — which it can compute from the
        #: ``t``, the ``n`` and this name rather than from a number whose
        #: provenance it would otherwise have to guess.
        self.method = method
        # The per-world differences themselves, world id beside figure, in the
        # order the worlds were compared — so a caller auditing one world's
        # contribution reads it here rather than re-deriving the pairing.
        self._differences = differences

    @property
    def differences(self) -> tuple[tuple[str, float], ...]:
        """The per-world differences, ``(world_id, d)``, in comparison order."""
        return self._differences

    @property
    def is_positive(self) -> bool:
        """Whether the candidate arm reads *better* than the baseline on balance.

        The sign of the mean paired difference and nothing more — an interval
        or a bar is feature 280's, and a verdict about deployment is the gate's
        (`docs/alpha-engine-prd.md` §12).  This answers only the direction §C5
        names in ``V^{m★} ≥ V^0``.
        """
        return self.mean_difference > 0.0

    def clears(self, *, delta: float = 0.0, level: float = 0.05) -> bool:
        """Whether the comparison clears ``ΔIR > delta`` at ``p < level``.

        §12's M3 exit criterion read literally — *"Paired ΔIR > 0.3 with
        ``p < 0.05``"* — with the two figures as keywords because the criterion
        names deployment figures and a caller checking a different pair's
        advantage is asking the same question of other numbers.  Both edges are
        strict, as the criterion writes them: a ``ΔIR`` exactly equal to the
        bar is not *greater* than it, and a ``p`` exactly at the level is not
        below it.  A convenience over :attr:`mean_difference` and
        :attr:`p_value`, not a second statistic — it computes nothing the
        record does not already carry.
        """
        return self.mean_difference > delta and self.p_value < level

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a report or a persistence seam reads the comparison through:
        every figure the record carries, under the names its own fields answer
        to.  ``differences`` is included because it is the *evidence* the other
        figures are derived from — the same stance ``0109``'s ``replay_score``
        takes toward a revision's aggregate.
        """
        return {
            "paired_worlds": self.paired_worlds,
            "candidate_mean": self.candidate_mean,
            "baseline_mean": self.baseline_mean,
            "mean_difference": self.mean_difference,
            "spread": self.spread,
            "standard_error": self.standard_error,
            "t_statistic": self.t_statistic,
            "p_value": self.p_value,
            "method": self.method,
            "differences": self._differences,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PairedDifference):
            return NotImplemented
        return self.row() == other.row()

    def __hash__(self) -> int:
        return hash(
            (
                self.paired_worlds,
                self.candidate_mean,
                self.baseline_mean,
                self.mean_difference,
                self.spread,
                self.standard_error,
                self.t_statistic,
                self.p_value,
                self.method,
                self._differences,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PairedDifference(paired_worlds={self.paired_worlds}, "
            f"mean_difference={self.mean_difference!r}, "
            f"p_value={self.p_value!r})"
        )


def paired_ir_difference(
    candidate: Any,
    baseline: Any,
    *,
    spread: Any | None = None,
    delta: Any = 0.0,
    power: Any = POWER,
) -> PairedDifference:
    """Compare two arms' per-world IR readings, paired — feature 281's call.

    §11.0's statistic, spelled as the section spells it: each arm is a mapping
    of world id to that arm's out-of-sample IR on the world (*"the OOS IR of
    the committed pick"*), the two are paired **by world id** — never by
    position, which is what a mapping buys — and the differences are tested
    against zero.  Both arms on the same worlds is §10.3.1's *"same policy pair
    on the same worlds"*, and it is the property that makes the comparison
    paired rather than a comparison of two samples.

    ``spread`` is optional, and it is there for the caller that already holds a
    pool-scale deviation (Appendix B's ``σ_diff ≈ 0.8``) it wants the
    comparison *judged* against rather than measured from these worlds: given
    it, the capacity check below is run against that figure — the figure the
    comparison's power is actually a function of — and the record still carries
    the deviation these worlds measured.  Omitted, the capacity check is run
    against the measured deviation, which is the honest reading when the caller
    has nothing else.  ``delta`` is the difference the comparison must detect
    and ``power`` the power it is sized at; both are passed to
    :func:`power_capacity` and both default to the PRD's own figures.

    Refuses, in this order, each naming what it is about:

    1. an arm that is not a mapping of non-empty world ids to finite readings,
       for either arm — including a bare sequence of figures, which carries no
       ids to pair on and is therefore two samples rather than one set of
       differences (:class:`~dreaming.errors.PairedComparisonError`);
    2. worlds that do not pair — a world only one arm carries, or two arms
       whose world sets are not the same worlds at all, or fewer than two
       paired worlds surviving — because a dropped world silently converts the
       comparison into the unpaired one §11.0 rejects, and one difference has
       no spread to measure
       (:class:`~dreaming.errors.PairedComparisonError`);
    3. a ``spread`` that is not strictly positive, or a ``delta``/``power``
       that cannot size a comparison
       (:class:`~dreaming.errors.PairedComparisonError` for the spread — it is
       a fact about the evidence — and
       :class:`~dreaming.errors.ProportionComparisonError` for the sizing, in
       the vocabulary of the arithmetic that refused it).
    """
    candidate_arm = _validated_arm(
        candidate,
        name="candidate",
        code=PAIRED_CODE,
        error=PairedComparisonError,
    )
    baseline_arm = _validated_arm(
        baseline,
        name="baseline",
        code=PAIRED_CODE,
        error=PairedComparisonError,
    )

    candidate_worlds = frozenset(candidate_arm)
    baseline_worlds = frozenset(baseline_arm)
    if candidate_worlds != baseline_worlds:
        raise PairedComparisonError(
            f"{PAIRED_CODE}: a paired comparison runs over the worlds *both* "
            f"arms carry — got {len(candidate_worlds)} candidate world(s) and "
            f"{len(baseline_worlds)} baseline, of which "
            f"{len(candidate_worlds & baseline_worlds)} are shared; the "
            f"unshared {sorted(candidate_worlds ^ baseline_worlds)[:3]} carry "
            "one arm's reading and not the other's, so they contribute no "
            "difference. Including them would mean inventing the missing arm "
            "and reading the missing figure as a zero difference, which is the "
            "same invention spelled less visibly — and it is the *unpaired* "
            "comparison docs/alpha-engine-prd.md §11.0 rejects, arriving "
            "through the arithmetic rather than through the request. Compare "
            "the two arms over the worlds that carry both"
        )

    paired_ids = sorted(candidate_worlds)
    if len(paired_ids) < 2:
        raise PairedComparisonError(
            f"{PAIRED_CODE}: a paired comparison needs at least two worlds "
            f"carrying both arms — got {len(paired_ids)}; one world is one "
            "difference, and one difference has no spread: the sample "
            "deviation is a division by n − 1, so at n = 1 there is nothing to "
            "divide by and a t figure reported off it would be a spread this "
            "pool does not have. Compare the arms over more worlds, or report "
            "the two means without a test"
        )

    differences = tuple(
        (world_id, candidate_arm[world_id] - baseline_arm[world_id])
        for world_id in paired_ids
    )
    figures = [difference for _, difference in differences]
    count = len(figures)
    mean_difference = math.fsum(figures) / count
    measured = math.sqrt(
        math.fsum((value - mean_difference) ** 2 for value in figures) / (count - 1)
    )
    standard_error = measured / math.sqrt(count)
    judged = (
        measured
        if spread is None
        else _validated_spread(
            spread, code=PAIRED_CODE, error=PairedComparisonError
        )
    )

    if standard_error == 0.0:
        # Every world read the same difference: the statistic is a division by
        # exactly nothing, and there is no spread in this pool to test.  This
        # is the ``n = 1`` refusal's own fact arriving at a larger ``n``, so it
        # is refused in the same word rather than answered with an infinity.
        raise PairedComparisonError(
            f"{PAIRED_CODE}: the {count} paired world(s) read an identical "
            f"difference of {mean_difference!r} on every one of them, so the "
            "statistic would divide by a standard error of exactly zero; a "
            "pool on which every world moved by the same amount carries no "
            "spread to test, and a t figure reported off it would be a number "
            "no worlds produced. The comparison is not refused for its "
            "direction — it is refused for having no evidence of one"
        )

    # The capacity check: the figures the comparison is sized at, against the
    # pool it actually has.  ``delta`` of zero asks *is this difference
    # distinguishable from none*, which needs no capacity figure.
    if float(delta) != 0.0:
        power_capacity(delta, spread=judged, power=power)

    t_statistic = mean_difference / standard_error
    tail = statistics.NormalDist().cdf(-abs(t_statistic))
    return PairedDifference(
        paired_worlds=count,
        candidate_mean=math.fsum(candidate_arm.values()) / len(candidate_arm),
        baseline_mean=math.fsum(baseline_arm.values()) / len(baseline_arm),
        mean_difference=mean_difference,
        spread=measured,
        standard_error=standard_error,
        t_statistic=t_statistic,
        p_value=min(1.0, _TWO_SIDED * tail),
        differences=differences,
    )


def rejects_proportion_comparison(
    proportion: Any,
    *,
    arm_size: Any,
    rate_delta: Any,
    delta: Any,
    spread: Any,
    power: Any = POWER,
) -> None:
    """Refuse a difference-in-proportions comparison — feature 281's own sentence.

    The **rejects** of *"System rejects a difference-in-proportions comparison,
    using a paired continuous statistic over the same worlds instead"*, spelled
    as the ladder's other verdicts are
    (:func:`dreaming.ladder.rejects_thin_pool`,
    :func:`dreaming.ceiling.rejects_uncapped_sweep`): a verdict over figures the
    caller already holds, which never opens a database, because a verdict is
    not a count and the count is the caller's to supply.

    ``proportion`` is the binary rate the caller means to compare — §11.0's
    *"``0.30 → 0.21``"*, the FDR-style figure the loop emits per arm — and
    ``arm_size`` the number of independent commits it would run that test over.

    **Two effect sizes, because §11.0 names two.**  ``rate_delta`` is the shift
    between the two *rates* the proportion test would compare — the 0.09 that
    carries ``0.30`` to ``0.21`` — and ``delta``/``spread`` are ``ΔIR`` and
    ``σ_diff``, the figures the *paired continuous* alternative is sized at.
    They are separate keywords because they are separate quantities on separate
    scales: §11.0's two worked examples use 0.09 and 0.3 respectively, and a
    signature with one ``delta`` would size one of the two tests at the other's
    figure — inflating the proportion requirement by ``(0.3/0.09)² ≈ 11×``, or
    shrinking the paired one to the point where the M3 precondition lost its
    meaning.  Both would return a plausible integer and neither would announce
    the substitution.  Defaulting ``rate_delta`` to ``delta`` was the tempting
    edit and is the same failure spelled less visibly, so it is a required
    keyword and the caller states each figure it means.

    The judgment is the comparison of two **capacities**: what a proportion
    test of this size, clustered as §11.0 says replays are, would need, against
    the capacity the paired statistic would need (:func:`power_capacity`).  A
    caller holding an ``arm_size`` below the paired requirement is refused
    outright — that is the M3 precondition, and no statistic funds it.  A
    caller whose ``arm_size`` is between the two requirements is refused too,
    and *that* is the feature's own sentence: the size buys the paired
    comparison and does not buy the proportion one, so the comparison that
    works is available and the one being asked for is not.

    The two requirements are computed by two different formulas, deliberately.
    The paired side is Appendix B's ``n ≈ 8(σ_diff/Δ)²``
    (:func:`power_capacity`), and the proportion side is the standard
    two-sample proportion sizing over §11.0's own pair (:func:`_proportion_arm_size`),
    which reproduces the PRD's *"~364"* at ``0.30 → 0.21``.  The clustering
    factor is the PRD's own — §11.0's *"replays clustered by world inflate that
    by the design effect to well over a thousand"* — and it is applied as a
    **multiple of the independent-commit requirement** rather than modelled:
    :data:`PROPORTION_DESIGN_EFFECT` states the inflation as the named default
    it is, because §11.0 gives "well over a thousand" as an order-of-magnitude
    floor and not as a design-effect estimate this member could reproduce from
    the evidence in hand.  Naming it as a knob is the honest reading: the
    refusal's direction does not depend on the exact factor at any scale the
    pool operates at, and a caller with a measured design effect passes its own
    rather than being silently given a different one.

    Refuses, in this order, each naming what it is about:

    1. a ``proportion``, ``arm_size``, ``rate_delta``, ``delta``, ``spread``
       or ``power`` that is not a finite real, or an ``arm_size`` that is not a
       non-negative whole number of commits, or a ``proportion`` outside
       ``[0, 1]`` (:class:`~dreaming.errors.ProportionComparisonError`) — each
       a fact about the ask;
    2. a ``rate_delta`` that carries the rate off the unit interval, or that is
       zero or negative, or a ``delta``/``spread``/``power`` that cannot size a
       comparison (:class:`~dreaming.errors.ProportionComparisonError`, from
       :func:`_proportion_arm_size` and :func:`power_capacity`);
    3. an ``arm_size`` below the **paired** requirement — the M3
       precondition, and the one refusal here that is about the pool rather
       than about the statistic
       (:class:`~dreaming.errors.ProportionComparisonError`).  Asked **first**,
       because the two requirements are not ordered relative to each other: a
       large enough ``spread`` makes the paired test *harder* than the
       proportion one, and an admission check asked second would then let an
       arm fund the wrong statistic;
    4. an ``arm_size`` that funds the paired statistic and not the proportion
       one — the feature's own refusal, naming both requirements.  The band
       between them is where §11.0's sentence lives, and it is reached only
       once the precondition above is cleared.
    """
    rate = _validated_figure(
        proportion,
        name="the proportion being compared",
        code=PROPORTION_CODE,
        error=ProportionComparisonError,
    )
    if not 0.0 <= rate <= 1.0:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: a proportion lies between none and all of a "
            f"set — got {proportion!r}; §11.0's figure is a rate over a set of "
            "commits, and a value outside [0, 1] is not one"
        )
    commits = _validated_figure(
        arm_size,
        name="the number of independent commits per arm",
        code=PROPORTION_CODE,
        error=ProportionComparisonError,
    )
    if not commits.is_integer() or commits < 0:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: an arm's size is a non-negative whole number "
            f"of commits — got {arm_size!r}; a proportion test is run over a "
            "count of independent commits, and a value that is not one names "
            "no test this judgement can size"
        )
    count = int(commits)

    paired_needs = power_capacity(delta, spread=spread, power=power)
    unclustered = _proportion_arm_size(
        rate,
        delta=_validated_figure(
            rate_delta,
            name="the shift between the two rates the proportion test compares",
            code=PROPORTION_CODE,
            error=ProportionComparisonError,
        ),
        power=_validated_figure(
            power, name="the power", code=PROPORTION_CODE, error=ProportionComparisonError
        ),
    )
    needed = math.ceil(unclustered * PROPORTION_DESIGN_EFFECT)

    # The M3 precondition is asked **first**, and asked of the *paired*
    # requirement.  §12's gate is written against that figure, so a pool below
    # it funds no comparison at all — not the proportion test being asked for
    # and not the statistic that would replace it.  Order matters because the
    # two requirements are not ordered relative to each other: a large enough
    # ``spread`` makes the paired test *harder* than the proportion one
    # (``paired_needs > needed``), and in that case an arm_size that funds the
    # proportion test would slip past an admission check asked second.  Asking
    # it first means ``count >= needed`` is only ever reached once the paired
    # figure is already cleared, so admission cannot mean funding the wrong one.
    if count < paired_needs:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: a difference-in-proportions comparison over "
            f"{count} commit(s) per arm is refused, and so is the paired "
            f"statistic it would be replaced with — §11.0's proportion test "
            f"needs ~{needed} independent commits per arm once clustered "
            f"replays are paid for, and the paired continuous test needs "
            f"~{paired_needs} paired worlds; this arm holds {count}, which is "
            "below the paired requirement. docs/alpha-engine-prd.md §12's M3 "
            "precondition is a pool of the paired figure's order, so the "
            "repair is the pool's: accumulate worlds until it clears the "
            "paired requirement. Do not run the comparison on this one"
        )

    if count >= needed:
        # Both requirements are cleared — the paired one by the refusal above,
        # the proportion one here.  Nothing to refuse: this module does not
        # forbid a comparison the evidence supports, and a refusal here would
        # be editorialising rather than judging.
        return

    raise ProportionComparisonError(
        f"{PROPORTION_CODE}: a difference-in-proportions comparison is refused "
        f"— §11.0: *'Raw FDR is a proportion, and proportions are power-poor'*. "
        f"Detecting this difference at {power:.0%} power needs ~{needed} "
        f"independent commits per arm once the design effect of clustered "
        f"replays is paid, and this arm holds {count}; the *paired* continuous "
        f"statistic over the same worlds needs ~{paired_needs}, which these "
        f"{count} worlds already fund. Fix the statistic, not the ambition: "
        f"score each commit continuously with the out-of-sample IR of the "
        f"committed pick and compare the arms **paired** — same policy pair, "
        f"same worlds — with dreaming.paired.paired_ir_difference over the "
        f"same pool. Do not widen the pool to fund a test §11.0 says is not "
        f"buildable at this scale"
    )


def _proportion_arm_size(proportion: float, *, delta: float, power: float) -> int:
    """The independent commits a two-proportion test of this size would need.

    The standard two-sample proportion sizing at :data:`PAIRED_LEVEL` and
    ``power``, run over §11.0's own worked pair:

        n = (z_{α/2} + z_β)² · [p₁(1 − p₁) + p₂(1 − p₂)] / (p₁ − p₂)²

    — evaluated at ``0.30`` falling to ``0.30 − delta``, which is the PRD's
    ``0.30 → 0.21`` at the ``delta`` of ``0.09`` both rates differ by, and the
    single reduction §11.0's sentence requires: the section gives one arm's
    rate and the shift, and the two arms' variances are each ``p(1 − p)`` of
    their own rate.  At ``(0.30, 0.21)`` this answers **364** — the PRD's own
    *"~364 independent commits per arm"*, reproduced rather than paraphrased,
    which is the whole reason the formula is spelled out here instead of a
    figure being quoted.

    The lower rate is refused when ``delta`` drives it outside ``[0, 1]``: a
    shift that lands an arm's rate off the unit interval is not a rate, and
    clamping it would size a test of a pair the caller never named.  A
    ``delta`` of zero is refused for the reason :func:`power_capacity` refuses
    it — a shift of nothing is detected by no number of commits, and the answer
    would be an infinity wearing a float — and refused **here** rather than
    left to the arithmetic, which is a division by ``delta ** 2`` and would
    raise the interpreter's own ``ZeroDivisionError`` about floats for a fact
    that is about the pair of rates.  A **negative** shift is refused too: this
    formula is stated as one rate falling to a lower one, and a negative
    ``delta`` would size the same pair of rates read the other way round while
    the variance term — symmetric in the two rates — silently cancelled the
    sign, so the refusal is what keeps the figure a claim about the pair §11.0
    names.  A rate at either edge without a shift
    answers zero: a proportion of exactly zero or one has no variance, so a
    test of it detects nothing and needs no commits — the arithmetic's own
    value, and the reason it is answered rather than refused.  The
    ``max(..., 2)`` matches :func:`power_capacity`'s floor, so the two figures
    the refusal compares are computed on the same terms.
    """
    if delta == 0.0:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: the difference a proportion test must detect "
            "is not zero — got 0.0; a shift of nothing is detected by no "
            "number of independent commits at all, so the requirement is "
            "infinite rather than large, and the arithmetic's own answer would "
            "be a division by ``delta ** 2`` — which is a fact about floats "
            "rather than about the pair of rates the caller named"
        )
    if delta < 0.0:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: the difference a proportion test must detect "
            f"is a positive shift — got {delta!r}; §11.0's comparison is "
            "written as one rate falling to a lower one (``0.30 → 0.21``), and "
            "a negative shift names the same pair read the other way round. "
            "Name the shift as §11.0 writes it"
        )
    lowered = proportion - delta
    if not 0.0 <= lowered <= 1.0:
        raise ProportionComparisonError(
            f"{PROPORTION_CODE}: the difference a proportion test must detect "
            f"can carry its rate off the unit interval — got a rate of "
            f"{proportion!r} shifted by {delta!r} to {lowered!r}; §11.0's "
            "comparison is between two rates, and a shift that lands one "
            "outside [0, 1] names no second rate to compare against"
        )
    variance = proportion * (1.0 - proportion) + lowered * (1.0 - lowered)
    if variance == 0.0:
        return 0
    beta_quantile = statistics.NormalDist().inv_cdf(power)
    numerator = ((_Z_ALPHA + beta_quantile) ** 2) * variance
    return max(2, math.ceil(numerator / (delta**2)))


def _pool_arm(path: Path, policy_version: str) -> dict[str, float]:
    """One arm's readings, read from the pool's own ``replay_score`` rows.

    A world's reading for a policy is that policy's score row for the world;
    the world is ``replay_score.world_id`` and the figure is
    ``replay_score.score`` — the out-of-sample IR the replay member wrote
    (feature 255's lineage), which is the quantity §11.0 names (*"the
    out-of-sample IR of the committed pick"*).  Rows are keyed by world, so a
    policy with several rows for one world (several ``beta`` readings) takes
    the **last one written**, deterministically: ``ORDER BY id`` over the
    world's rows, so a repeated read answers the same arm in any process — the
    §12 ordering rule every store in this workspace restates, and the reason
    this cannot be ``SELECT DISTINCT`` over the two columns, which would return
    *two* readings for a world and silently drop one at the dict boundary.

    A policy with no rows in the pool reads as an **empty arm**, and that is
    the honest answer rather than a refusal: the world sets then fail to pair
    in :func:`paired_ir_difference`, which refuses naming both arms' sizes —
    the fact about the world, stated by the function that knows what pairing
    means, rather than a second refusal spelled here.
    """
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            f"SELECT world_id, score FROM {REPLAY_SCORE_TABLE} "
            "WHERE policy_version = ? AND world_id IS NOT NULL AND score IS NOT NULL "
            "ORDER BY id",
            (policy_version,),
        ).fetchall()
    arm: dict[str, float] = {}
    for world_id, score in rows:
        arm[world_id] = float(score)
    return arm


def _pool_path(database_url: Any, env: Mapping[str, str] | None) -> Path:
    """Resolve the pool a comparison is taken over: the URL, then ``DATABASE_URL``.

    The same resolution order :func:`dreaming.split._split_path` and
    :func:`dreaming.cap._cap_path` take, and the same refusal stance: an act
    that means to read the pool and resolves nothing is refused by name rather
    than answered with ``None``.  A URL this member cannot speak is refused in
    the comparison's own vocabulary, translated at the seam from the one
    spelling of what a ``sqlite:///`` URL names — the discipline the workspace
    states for error vocabularies and this member applies at each store seam,
    so a caller comparing two arms never meets feature 270's
    :class:`~dreaming.errors.FreezeRequestError` for an act that held nothing.
    """
    url = (
        database_url
        if database_url is not None
        else (os.environ if env is None else env).get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise PairedComparisonError(
            f"{PAIRED_CODE}: comparing two arms over the pool needs the "
            f"database it lives in — pass it explicitly or set "
            f"{DATABASE_URL_ENV}. A comparison taken over no database would "
            "report a difference between two arms that were never read, and "
            "the figures would look exactly like ones that had been"
        )
    try:
        return sqlite_path(url)
    except FreezeRequestError as refusal:
        raise PairedComparisonError(
            f"{PAIRED_CODE}: the arms a comparison is paired over are read "
            f"from the database the replay pool lives in, and the URL given "
            f"does not name one this member can speak — see the refusal it "
            f"raised: {refusal}. The comparison reads the pool's own score "
            "rows rather than fetching two arms it could pair with nothing, "
            "because §10.3.1's *same policy pair on the same worlds* is a "
            "claim about one store and not two"
        ) from refusal


def paired_pool_difference(
    candidate_policy: Any,
    baseline_policy: Any,
    *,
    database_url: str | None = None,
    spread: Any | None = None,
    delta: Any = 0.0,
    power: Any = POWER,
    env: Mapping[str, str] | None = None,
) -> PairedDifference:
    """Compare two policy versions over the pool's own rows — feature 281, over the store.

    The store seam of the feature's call: name the two arms by their
    ``policy_version``, resolve the database the deployment names (an explicit
    URL first, then ``DATABASE_URL``, refused when neither names one), read
    each arm's per-world readings from ``replay_score``, and compare them
    paired (:func:`paired_ir_difference`).  §10.3.1's *"same policy pair on the
    same worlds"* is exactly what reading both arms from one pool buys: the
    worlds are paired by construction rather than by the caller's bookkeeping,
    and a world only one arm was replayed against is refused rather than
    silently dropped.

    ``candidate_policy`` is §C5's revision under test and ``baseline_policy``
    the arm it is compared against — PRD §12's M2 fixed baseline for the M3
    gate, or any earlier version for a cycle-to-cycle comparison.  The two must
    differ: comparing a policy against **itself** would pair every world
    against its own reading, so every difference would be exactly zero, and the
    statistic would be a division by a standard error of nothing.  That is
    refused by name here rather than left to the arithmetic, because the
    message the arithmetic produces names a pool on which every world moved by
    the same amount — which is true of a self-comparison and reads like a fact
    about the pool.

    Refuses, in this order, each naming what it is about:

    1. a policy version that is not non-empty text, or the same version named
       as both arms (:class:`~dreaming.errors.PairedComparisonError`) — the
       ask's own facts, refused before any database is opened;
    2. a URL that names no database or one this member cannot speak
       (:class:`~dreaming.errors.PairedComparisonError`, translated at the
       seam);
    3. a database that holds no ``replay_score`` table — no pool to compare
       over (:class:`~dreaming.errors.PairedComparisonError`), because a
       comparison over a database without it would report a difference between
       two arms that were never read and nothing in the result would look
       wrong;
    4. arms that do not pair, or too few paired worlds
       (:class:`~dreaming.errors.PairedComparisonError`), by
       :func:`paired_ir_difference`.
    """
    candidate = _validated_policy(candidate_policy)
    baseline = _validated_policy(baseline_policy)
    if candidate == baseline:
        raise PairedComparisonError(
            f"{PAIRED_CODE}: the two arms of a comparison are two policies — "
            f"got {candidate!r} on both sides; a policy compared against "
            "itself pairs every world with its own reading, so every "
            "difference is exactly zero and the statistic divides by a "
            "standard error of nothing. That is a fact about the comparison "
            "rather than about the pool, and the arithmetic's own message "
            "would describe the pool instead. Name the arm this policy is to "
            "be compared against"
        )
    path = _pool_path(database_url, env)
    with closing(sqlite3.connect(path)) as connection:
        if REPLAY_SCORE_TABLE not in pool_tables_present(connection):
            raise PairedComparisonError(
                f"{PAIRED_CODE}: the database at {path} holds no "
                f"{REPLAY_SCORE_TABLE} table, so there is no pool here to "
                "compare the two arms over — a difference reported between "
                "them would be a difference between two arms that were never "
                "read, and the figures would look exactly like ones that had "
                f"been. Point {DATABASE_URL_ENV} at the database the replay "
                "pool lives in, or migrate it"
            )
    return paired_ir_difference(
        _pool_arm(path, candidate),
        _pool_arm(path, baseline),
        spread=spread,
        delta=delta,
        power=power,
    )


def _validated_policy(value: Any) -> str:
    """Check that ``value`` names a policy version, or refuse it.

    Non-empty text, matching the one spelling of what a policy version is in
    this workspace (``0109``'s ``policy_version`` column, ``TEXT NOT NULL
    UNIQUE``, and feature 274's write into it).  Refused in this module's own
    vocabulary rather than by borrowing a store's, and refused *before* any
    database is opened — an arm named by nothing is an ask's own fault, and the
    repair is to name it.
    """
    if not isinstance(value, str) or not value.strip():
        raise PairedComparisonError(
            f"{PAIRED_CODE}: a policy version is named by a non-empty string — "
            f"got {value!r} ({type(value).__name__}); an arm of the comparison "
            "is a specific policy, and a value that names none names no arm to "
            "pair the other against"
        )
    return value


