"""The lookback-jitter re-run — the perturbation-stability probe's fourth axis, feature 130.

app_spec.xml, "Leakage Tripwires", feature 130: *"System jitters a declared
lookback by plus or minus 10 percent, persisting perturbation_stability as a
node metric."*  docs/alpha-engine-prd.md §C6 names the axis in the sentence
that gives the family its rule — *"Re-run with a different seed, a different
start offset, a different universe subsample, a different lookback.
Degradation beyond threshold is a reject."* — and this module is the fourth
axis and the last of the re-runs.  The persistence half of the same sentence
is a *second* module, :mod:`tripwires.node_metric`, because what it writes is
a different kind of thing: this module is a pure function of mappings, that
one is a store with a database and an environment.  Feature 127 is the
family's first axis, 129 the third; this one completes the set §C6 declares.

**The perturbation, stated precisely.**  A candidate declares a lookback —
how much history its book claims to need — and the system re-runs it with
that lookback *jittered*: ``L′ = round(L · (1 + jitter))``, the pinned
``jitter`` being the spec's own ±10 percent (minus by default, because the
minus side is always runnable while the plus side needs history beyond the
declared window that the panel may not carry).  Both windows are **trailing**:
the newest measured bar is held fixed and the jitter moves the window's
start, because a lookback is a span of *history*, and the two runs differ in
how much of it they see.  A caller who declares no lookback means the panel's
own full measured span, which makes the reference run exactly feature 125's
probe over the panels as handed in — the same reference 127 and 129 re-run,
so the four axes' figures are measured against one number.  ``jitter`` is
signed and a single parameter, never two: this axis moves the *window*, and
a caller who wanted the seed moved too would be running two features'
perturbations in one measurement, which is the coupling the family's
four-features-not-one argument exists to avoid.

**The threshold's derivation, and the mistake it is easiest to make here —
which is the opposite of feature 129's.**  The bar is derived from feature
125's own arithmetic rather than tuned, and like 129's it turns on one fact
about the two runs a reader is most likely to get wrong.  The two modules
disagree about which fact that is, and the disagreement is the family's
cleanest lesson.

Feature 129's tempting mistake was to write the two runs as *independent*;
they were not, because its thinning kept the dates and the seed — hence the
pairing — fixed, so the kept names' noise was shared and the correlation
``√f`` entered the bar.  The tempting mistake *here* runs the other way: the
two windows share 90 percent of their dates (at the pinned tenth), so the
runs "must" share their noise — ``corr = √r`` over the ratio ``r = L′/L`` —
giving ``Var(ΔS) = |1−r|/(rT)`` and a bar of ``√(|jitter|/(1+jitter))``,
exactly **one third** at the pinned ``−0.10``.

**That derivation is wrong, and the reason is the shuffle.**  The derangement
is a pure function of *(sorted dates, seed)* —
:func:`~tripwires.time_shuffle.time_shuffle_pairing` draws one uniform key per
date over the whole grid and sorts — so truncating the window does not keep
the shared dates' pairings and drop the rest: **every date is re-dated**,
because every date's key is drawn in a different lottery.  The shared 108
dates contribute the same *panel* to both runs but different *shuffles* of
it, and under feature 125's null the per-date noise of a shuffled
cross-section is fresh noise.  The two statistics are therefore independent
to the precision the null model holds anywhere: ``Var(S_ref) = σ²/L``,
``Var(S_rerun) = σ²/L′ = σ²/(rL)``, and

    Var(ΔS) = σ²(1/L + 1/L′) = (1 + 1/r)·σ²/L,

which in units of the reference run's own rejection threshold
``z·σ/√L`` gives a folded figure whose bar at ``level`` is — the ``z``
cancelling exactly as it does for 129 —

    DEFAULT_LOOKBACK_STABILITY_THRESHOLD = √(1 + 1/(1 + jitter)) ≈ 1.4530

at the pinned ``−0.10`` percent tenth.  Like ``√2``, it carries no ``level``
term and no ``dates`` term, and for the same reason: the figure is measured
in units of a threshold that already carries both.  Unlike ``√2`` it depends
on the jitter, monotonically: the minus side is *wider* than the plus side
(``1.4530`` against ``1.3817`` at ±10 percent), because a shorter re-run
window is a noisier measurement.

**The calibration, measured rather than asserted.**  Null re-runs over 400
seeds at each of seven configurations (full-span and declared-window, both
signs of the tenth, grids of 60–240 dates): the realized standard deviation
of the figure matches the half-normal prediction
``√(1+1/(1+j))/z·√(1−2/π)`` to within ~2 percent at every one, and the
derived bar is exceeded at 0.0025–0.0175 against the nominal 0.01.  The
tempting correlated-window bar of ``1/3`` is exceeded at **0.55** — over half
of all clean candidates — which is not a calibration quibble but a probe
that rejects every second honest book.  The suite pins the closed form *and*
both rates, asserting the ``√(|j|/(1+j))`` shortcut **wrong** rather than
close enough, the same treatment 127's and 129's suites give their own
tempting derivations, from the opposite side.

There is a structural fact the wrong bar disagrees with, and it is the axis'
own limit case.  As ``jitter → 0`` the bar tends to ``√2`` — the seed axis'
equal-length limit — and does **not** vanish, while the *figure* is
identically zero at ``jitter = 0`` exactly (same window, same seed, same
derangement, same statistic).  The null is discontinuous there, and honestly
so: any ``jitter ≠ 0`` changes the date list and so re-dates everything, and
no ``jitter ≠ 0`` keeps any of the old pairing.  That is the opposite of
feature 129, whose bar ``√(2(1−√f))`` vanishes at ``f = 1`` precisely where
its figure is structurally zero — and it is why ``jitter = 0`` is refused by
name here as a perturbation that never happened, rather than barred over.

**What this axis catches, and what it does not — the corpus's own answer.**
The maintained corpus (feature 133) plants whole-panel leaks — a full-sample
mean, a full-sample t-stat, each in both signs — and a whole-sample
statistic is invariant to *which dates* it sees for the same reason it is
invariant to which derangement re-dates them: feature 127's suite measures
its leaks at a degradation of exactly ``0.0``, and this axis measures all
four at a figure of ≈ 0.16 against the 1.45 bar — under it, with a nine-fold
margin.  So the stability cause does not fire on the corpus.  What fires is
the union: both runs' *own* detections reject the leak at the full span and
at the jittered window alike, and the verdict reports which cause did the
work rather than laundering the rejection into a stability figure it was
not.  Through feature 129's axis the same four panels figure ≈ 1.71 and
reject *on the stability* — two magnitude axes, opposite verdicts on one
corpus, which is the sharpest measured form the family's
four-axes-not-one-parameter argument takes in this member.  What this axis
adds over its siblings is the §4.5 robustness question — *does the
statistic reproduce when the window moves?* — and its honest limit is
measured too: a signal planted on only the oldest 12 of 120 dates is so
diluted in the full-span reference that the move stays inside the null
(exceedance at the nominal rate over 60 seeds).  The axis measures the
*move*, not the location, and a book whose history-dependence is that thin
is 125's comparison to catch, not the window's.

**The figure is the family's magnitude, not feature 127's signed drop.**
Like 129's, this figure is two-sided — a re-run that moved *up* on the
jittered window is as unreproduced as one that moved down — and
:func:`lookback_figure` is a delegation to
:func:`~tripwires.subsample.subsample_figure` rather than a second
implementation, for the reason :meth:`~tripwires.stability.StabilityRecord.
recomputes` delegates: one arithmetic, one provenance, and the axis that
happens to have arrived first owns it.

**What this module does not do.**  It does not perturb the seed (127), a
window *offset* (128, a different feature: an offset moves the window along
the grid, a jitter moves how long it is), or the universe (129); it does not
permute labels (126), poison a subtree (131), excise a pool (132), maintain
the corpus (133) or decide the triage figure (134).  It does not re-implement
the statistic, the shuffle or the threshold: the reference run is
:func:`~tripwires.time_shuffle.run_time_shuffle_tripwire` over the panels as
handed in (or over the declared window, when one is), the re-run is the same
function over the jittered window, and the figure is one subtraction, one
``abs`` and one division.  And it does not persist anything: the node column
0114 declares is :mod:`tripwires.node_metric`'s to write, on its own
lifecycle, behind its own component name.

**The layering note.**  Stdlib-only, like the rest of the member —
arithmetic, mappings, sorting and the two probe calls below; no polars, no
pyarrow, no lake, no environment, no HTTP, and no import of any other
workspace member.  The one import that could surprise a reader is
``.subsample``, and it is the delegation above rather than a dependency on
a sibling axis: the magnitude is shared vocabulary, spelled once.  The
verdict carries **no wall-clock field at all**, for the §12 reason every
record in this member carries it: two runs of the same re-run must return
the same verdict bit-for-bit, and a timestamp would make them differ in a
field no reader consults.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import TripwirePanelError
from .seed_rerun import PERTURBATION_AXES, PERTURBATION_STABILITY_NAME
from .subsample import subsample_figure
from .time_shuffle import (
    DEFAULT_SHUFFLE_LEVEL,
    DEFAULT_SHUFFLE_SEED,
    HORIZONS,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    run_time_shuffle_tripwire,
    time_shuffle_threshold,
)

__all__ = [
    "DEFAULT_LOOKBACK_JITTER",
    "DEFAULT_LOOKBACK_STABILITY_THRESHOLD",
    "LOOKBACK_AXIS",
    "LookbackRerunVerdict",
    "jittered_lookback",
    "lookback_figure",
    "lookback_stability_threshold",
    "run_lookback_rerun",
]

#: The axis this feature perturbs — the fourth and last of
#: :data:`~tripwires.seed_rerun.PERTURBATION_AXES`, in §C6's declaration order
#: (*"... a different lookback"*).  Spelled by indexing that tuple rather than
#: by a literal here, for the reason :data:`~tripwires.seed_rerun.SEED_AXIS`
#: is: the family's four features must not be able to drift apart on what the
#: shared vocabulary is, and a reader holding one axis has a name to hold this
#: one to.
LOOKBACK_AXIS: str = PERTURBATION_AXES[3]

#: The jitter the re-run applies to the declared lookback — the spec's own
#: *plus or minus 10 percent* (app_spec.xml feature 130).  The default is the
#: **minus** side, and that is a decision rather than a coin: the minus side
#: is always runnable — a shorter trailing window of a window the panel
#: already measured exists by construction — while the plus side needs
#: history *beyond* the declared lookback that the panel may not carry, and a
#: default that a bare 120-bar panel refuses would make the feature's own
#: default call an error on the corpus's own grid.  Signed, and one parameter:
#: the axis moves the window's length, and a second seed here would be
#: feature 127's perturbation smuggled into this measurement.
DEFAULT_LOOKBACK_JITTER: float = -0.10

#: The configured stability threshold, in units of the reference run's own
#: rejection threshold — see the module docstring for the derivation and for
#: the measurement that falsifies the tempting correlated-window form.  It is
#: ``√(1 + 1/(1 + jitter))``, which at the pinned tenth is ``√(19/9)`` ≈
#: 1.4530.  Written as the expression rather than as a literal so the
#: constant *is* its derivation, and asserted in the suite against the closed
#: form, the measured false-alarm rate, and the wrong bar's measured rate —
#: the same treatment the sibling axes' bars get, for the same reason.
#:
#: Three things about it are worth naming, because each is a place a reader
#: could reasonably expect something else:
#:
#: * **It carries no ``level`` term and no ``dates`` term.**  The figure is
#:   measured in units of the reference run's own threshold, which carries
#:   ``Φ⁻¹(1 − level/2)`` and ``1/√L``; the bar is that same threshold taken
#:   ``z`` standard deviations out, so both cancel — the cancellation
#:   feature 129's bar found, from the other side of the same algebra.
#: * **It depends on the jitter, monotonically.**  A shorter re-run window is
#:   a noisier measurement, so the minus side's bar (1.4530) is wider than
#:   the plus side's (1.3817), and both are wider than the equal-length
#:   ``√2`` the ``jitter → 0`` limit lands on — the limit the seed axis
#:   lives at permanently.
#: * **It does not vanish as the jitter shrinks, and must not.**  The *figure*
#:   is identically zero at ``jitter = 0`` (the windows coincide, so the
#:   derangements do too), but for every ``jitter ≠ 0`` the date list changes
#:   and the whole panel is re-dated, so the null stays near ``√2``-wide all
#:   the way down.  That discontinuity is the axis' structural difference
#:   from 129 — whose bar vanishes exactly where its figure does — and it is
#:   why ``jitter = 0`` is refused as a non-perturbation rather than barred
#:   over.
DEFAULT_LOOKBACK_STABILITY_THRESHOLD: float = math.sqrt(
    1.0 + 1.0 / (1.0 + DEFAULT_LOOKBACK_JITTER)
)


def lookback_stability_threshold(jitter: float = DEFAULT_LOOKBACK_JITTER) -> float:
    """The derived bar for a ``jitter`` — ``√(1 + 1/(1 + jitter))``.

    The closed form, parameterized, so a deployment jittering at some other
    fraction derives its bar from the same arithmetic the pinned constant
    comes from rather than re-deriving it by hand.  Refuses the same jitters
    :func:`jittered_lookback` refuses — not finite, at or past ``−1`` (the
    window annihilated), or exactly ``0`` (no perturbation; the figure would
    be a structural zero for every candidate including a planted one) —
    because a bar derived over a jitter this feature cannot run is a number
    nothing will ever be judged against.
    """
    if isinstance(jitter, bool) or not isinstance(jitter, (int, float)):
        raise TripwirePanelError(
            f"the lookback jitter must be a number, got {jitter!r} "
            f"({type(jitter).__name__}); the bar is a pure function of the "
            "jitter, and a non-number names no perturbation to derive a bar for"
        )
    proportion = float(jitter)
    if not math.isfinite(proportion):
        raise TripwirePanelError(
            f"the lookback jitter must be finite, got {jitter!r}; a NaN or "
            "±inf names no window, and a bar derived over it would judge "
            "nothing"
        )
    if proportion <= -1.0:
        raise TripwirePanelError(
            f"the lookback jitter must be greater than -1, got {proportion!r}; "
            "a jitter of -100 percent or worse annihilates the window, and "
            "there is no re-run to state a bar for"
        )
    if proportion == 0.0:
        raise TripwirePanelError(
            "the lookback jitter is not 0; the unjittered window is the "
            "reference run itself, its figure is a structural zero for every "
            "candidate including a planted one, and a bar over it would "
            "pretend a perturbation was measured"
        )
    return math.sqrt(1.0 + 1.0 / (1.0 + proportion))


def jittered_lookback(
    lookback: int, *, jitter: float = DEFAULT_LOOKBACK_JITTER
) -> int:
    """The re-run's lookback — ``round(lookback · (1 + jitter))``, refused when it is no perturbation.

    The spec's own arithmetic ("jitters a declared lookback by plus or minus
    10 percent"), with the rounding the sibling axis' count uses: Python's
    ``round``, the one version-stable primitive the member allows itself
    here.  Deterministic in ``(lookback, jitter)``, so two callers naming one
    declared lookback get one jittered one, bit-for-bit.

    Refused by name — never clamped — for the three ways this arithmetic can
    produce a window that is not a perturbation at all:

    * a jitter of ``0`` (or one that is not a finite number strictly greater
      than ``−1``): no window, or none the panel could hold;
    * a count that rounds **back to the declared lookback** — a 10 percent
      jitter of 3 bars is 3 bars — the structural zero feature 127 refuses
      when its two seeds are equal and 129 refuses when its fraction rounds
      to the whole universe, refused here for the same reason: a "stability"
      measured over an unperturbed window is a perfectly stable candidate
      that was never re-run;
    * a jittered count below two: no shuffle exists over one date, and no
      statistic to state.
    """
    if isinstance(lookback, bool) or not isinstance(lookback, int):
        raise TripwirePanelError(
            f"a declared lookback is a count of bars, got {lookback!r} "
            f"({type(lookback).__name__}); the jitter is taken on a number of "
            "dates, and a non-integer names no window"
        )
    if lookback < 2:
        raise TripwirePanelError(
            f"a declared lookback is at least two bars, got {lookback}; below "
            "that there is no shuffle, no dispersion and no statistic, and a "
            "window of one date is the run it re-runs"
        )
    if isinstance(jitter, bool) or not isinstance(jitter, (int, float)):
        raise TripwirePanelError(
            f"the lookback jitter must be a number, got {jitter!r} "
            f"({type(jitter).__name__}); the jittered lookback is a pure "
            "function of the declared one and the jitter, and a non-number "
            "names no stream of windows to draw from"
        )
    proportion = float(jitter)
    if not math.isfinite(proportion):
        raise TripwirePanelError(
            f"the lookback jitter must be finite, got {jitter!r}; a NaN or "
            "±inf names no window"
        )
    if proportion <= -1.0:
        raise TripwirePanelError(
            f"the lookback jitter must be greater than -1, got {proportion!r}; "
            "a jitter of -100 percent or worse annihilates the window, and an "
            "annihilated window is a refusal rather than a stability figure "
            "about nothing"
        )
    if proportion == 0.0:
        raise TripwirePanelError(
            "the lookback jitter is not 0; the unjittered lookback is the "
            "reference run's own, its figure is a structural zero for every "
            "candidate including a planted one, and a re-run that re-runs "
            "the window it was handed has measured nothing"
        )
    jittered = round(lookback * (1.0 + proportion))
    if jittered == lookback:
        raise TripwirePanelError(
            f"a {proportion:+.4f} jitter of {lookback} bars is {jittered}, "
            f"which is the declared lookback again; a jitter that rounds to "
            "nothing has perturbed nothing, and its figure would be a "
            "structural zero dressed as a stability measurement"
        )
    if jittered < 2:
        raise TripwirePanelError(
            f"a {proportion:+.4f} jitter of {lookback} bars is {jittered}, "
            f"and a re-run under two dates has no shuffle and no statistic "
            "to state; declare a longer lookback or a smaller jitter"
        )
    return jittered


def lookback_figure(
    reference_sharpe: float, rerun_sharpe: float, *, threshold: float
) -> float:
    """The lookback stability figure between two surviving Sharpes.

    A **delegation** to :func:`~tripwires.subsample.subsample_figure`, not a
    second implementation: ``|rerun − reference| / threshold`` is the
    perturbation-stability family's one magnitude, spelled once in the module
    that arrived first and offered to this feature's callers under this
    feature's name — the same reason :meth:`~tripwires.stability.
    StabilityRecord.recomputes` reaches for that function rather than
    restating the subtraction.  Zero exactly when the jittered window changed
    nothing; positive in *both* directions when it did, because stability is
    two-sided for this axis as for 129's.

    All of that function's refusals arrive with it — a non-number or
    non-finite statistic, a threshold that is not a finite positive number —
    in this module's own callers' hands, which is what keeps a hand-built
    record and the entry point below from disagreeing about what the figure is.
    """
    return subsample_figure(reference_sharpe, rerun_sharpe, threshold=threshold)


@dataclass(frozen=True)
class LookbackRerunVerdict:
    """Feature 130's answer — a lookback re-run's terms, and the decision on them.

    The record this feature states: feature 125's probe run over the declared
    window (the panel's full measured span when no lookback was declared) and
    again over the *jittered* window, the stability figure between them, the
    configured bar it was judged against, the jitter that produced it, and
    the decision.  Every term the comparison was made from is carried — the
    seed rebuilds the derangement each run drew (over its *own* date list,
    which is the module docstring's whole derivation), the level and the date
    count rebuild the bar the figure is measured in, and both statistics sit
    beside the figure they compose — because a rejection that poisons a
    subtree is an irreversible act and must be auditable from the record
    alone, for the same reason feature 125's, 127's and 129's verdicts carry
    their own terms.

    The invariants are enforced at construction, so a record built by hand —
    or by a later feature whose producer drifted — fails loudly rather than
    carrying a lying stability figure: ``stability`` must recompute from the
    two statistics and the reference threshold, ``jittered_lookback`` must
    recompute from the declared count and the jitter, a declared lookback
    must equal the reference run's own date count (the reference window *is*
    the declared window), ``rejected`` must be the disjunction of the three
    named causes, and the outcome word must be the decision's own translation
    into §8's vocabulary.

    **The field names are the family's, and deliberately not feature 125's.**
    This record has ``reference_sharpe``, ``rerun_sharpe`` and
    ``reference_threshold`` and no ``surviving_sharpe``/``threshold``/
    ``degradation``, for the seam reason
    :class:`~tripwires.subsample.SubsampleRerunVerdict` states: feature 131
    checks a verdict structurally, by field names, because the factory's scan
    gives one source file two class objects — and a record that shared
    feature 125's statistic names would pass the check and then be judged on
    feature 125's comparison over feature 125's statistic.  The stability
    names are shared with 129's verdict *on purpose*: the two records carry
    the same quantity in the same units, and the stability ledger's writer
    reads either.

    **The knobs this axis does not move are ``None``, and read as absent.**
    :attr:`rerun_seed`, :attr:`subsample_seed` and
    :attr:`subsample_fraction` are properties returning ``None`` rather than
    fields: they are not per-verdict values a caller could set but constants
    about the axis — this feature holds the shuffle seed fixed and touches no
    universe — and ``None`` in the ledger row means *this axis perturbs no
    such knob*, the absent-versus-zero distinction the member's schemas keep
    throughout.  A zero would read as a real seed.
    """

    #: The node whose candidate was re-run.
    node_id: str
    #: The probe that fired — always :data:`~tripwires.seed_rerun.
    #: PERTURBATION_STABILITY_NAME`; carried so a persisted failure names
    #: which of §6.1 step 10's probes it was.
    tripwire: str
    #: The axis that was perturbed — always :data:`LOOKBACK_AXIS` here.
    axis: str
    #: The horizon both runs probed — the shortest covered, feature 125's
    #: pinned policy, and necessarily the same for both.
    horizon: int
    #: How many rebalance dates the **reference** run measured — the
    #: declared lookback, or the full measured span when none was declared.
    #: The ``T`` behind :attr:`reference_threshold`.
    dates: int
    #: The probe's two-sided level, restated from the reference run.
    level: float
    #: The seed both runs drew their derangement from.  **The same on both
    #: sides**, and the pairing still differs — the derangement is a function
    #: of the whole date list, so the jittered window draws its own.  That
    #: fact is the module docstring's derivation, and the reason the seed
    #: being shared does not make the runs correlated.
    seed: int
    #: The declared lookback, as the caller declared it — ``None`` meaning
    #: the panel's own full measured span.  Carried verbatim rather than
    #: collapsed into :attr:`dates` because the difference between "the
    #: candidate declared 100 bars" and "the candidate declared everything it
    #: was handed" is a fact about the candidate, and the record is where a
    #: reader audits what was jittered.  When not ``None`` it must equal
    #: :attr:`dates`: the reference window *is* the declared window.
    lookback: int | None
    #: The signed jitter the re-run applied — the spec's ±10 percent, minus
    #: by default.  A parameter of the record rather than a constant so the
    #: figure and its bar can be audited against the jitter that actually
    #: ran, and refused at construction when it perturbs nothing.
    jitter: float
    #: The re-run's lookback — ``round`` of the declared count times
    #: ``(1 + jitter)``, and the count of dates the re-run measured.  The
    #: perturbation's own evidence, recomputable from :attr:`dates` and
    #: :attr:`jitter` alone.
    jittered_lookback: int
    #: The reference run's surviving Sharpe — the number under test.
    reference_sharpe: float
    #: The re-run's surviving Sharpe — the same measurement, jittered window.
    rerun_sharpe: float
    #: The reference run's rejection threshold — ``Φ⁻¹(1 − level/2)/√dates``.
    #: Read off the reference verdict rather than recomputed, so the bar the
    #: figure is standardized by is provably the one that run was judged
    #: against.
    reference_threshold: float
    #: ``|rerun_sharpe − reference_sharpe| / reference_threshold`` — the
    #: stability figure this feature's persistence half writes to the node.
    stability: float
    #: The configured threshold the figure was judged against, in the same
    #: units — ``√(1 + 1/(1 + jitter))`` by default, level- and grid-free
    #: (see the module docstring).
    stability_threshold: float
    #: ``True`` when the figure exceeded the configured threshold — the
    #: spec's own cause on this axis, and the cause the configured bar
    #: governs.
    stability_rejected: bool
    #: ``True`` when the run being re-run stated a failure, under its own
    #: comparison.  Feature 125 found leakage, and this record must not
    #: launder that into a pass.
    reference_rejected: bool
    #: ``True`` when the jittered window's own probe found leakage the
    #: reference draw did not — the cause the corpus's whole-panel leaks
    #: actually fire, their figure being window-stable.
    rerun_rejected: bool
    #: The decision: any of the three named causes above.
    rejected: bool
    #: The decision in §8's trial vocabulary — ``tripwire_fail`` when
    #: rejected, ``ok`` when the re-run states no failure.
    outcome: str

    def __post_init__(self) -> None:
        # Validates only, like the records it sits beside; the constructor of
        # a value this module builds normalizes nothing.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TripwirePanelError(
                "a lookback re-run verdict must name the node whose candidate "
                f"it re-ran, got {self.node_id!r}"
            )
        if self.tripwire != PERTURBATION_STABILITY_NAME:
            raise TripwirePanelError(
                f"a lookback re-run verdict's tripwire is "
                f"{PERTURBATION_STABILITY_NAME!r}, got {self.tripwire!r}; both "
                "runs of this feature are time-shuffle probes and this record "
                "is not one of them, so naming it "
                f"{TIME_SHUFFLE_NAME!r} would make a re-run indistinguishable "
                "from the run it re-runs"
            )
        if self.axis != LOOKBACK_AXIS:
            raise TripwirePanelError(
                f"a lookback re-run verdict's axis is {LOOKBACK_AXIS!r}, got "
                f"{self.axis!r}; this feature jitters the window, and a record "
                "naming another axis would be a stability figure about a knob "
                "this module never moved"
            )
        if self.axis not in PERTURBATION_AXES:
            raise TripwirePanelError(
                f"a perturbation axis is one of "
                f"{', '.join(PERTURBATION_AXES)}, got {self.axis!r}"
            )
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise TripwirePanelError(
                f"a lookback re-run verdict's horizon must be an integer "
                f"period count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise TripwirePanelError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)})"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise TripwirePanelError(
                f"a lookback re-run verdict's date count must be an integer, "
                f"got {self.dates!r}"
            )
        if self.dates < 2:
            raise TripwirePanelError(
                f"a lookback re-run measures at least two dates, got "
                f"{self.dates}; below that there is no shuffle, no dispersion "
                "and no bar, and a stability figure over one date states a "
                "re-run that never ran"
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TripwirePanelError(
                f"a lookback re-run verdict's seed must be an integer, got "
                f"{self.seed!r}"
            )
        if self.lookback is not None and (
            isinstance(self.lookback, bool) or not isinstance(self.lookback, int)
        ):
            raise TripwirePanelError(
                f"a lookback re-run verdict's declared lookback is a count of "
                f"bars or None, got {self.lookback!r}"
            )
        if self.lookback is not None and self.lookback != self.dates:
            raise TripwirePanelError(
                f"the lookback re-run verdict declares a lookback of "
                f"{self.lookback} bars but its reference run measured "
                f"{self.dates} dates; the reference window *is* the declared "
                "window, and a record whose two counts disagree states a "
                "window the reference run never measured"
            )
        for field in ("level", "jitter", "reference_sharpe", "rerun_sharpe",
                      "reference_threshold", "stability", "stability_threshold"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePanelError(
                    f"a lookback re-run verdict's {field} must be a number, "
                    f"got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwirePanelError(
                    f"a lookback re-run verdict's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node record "
                    "dressed as a stability figure"
                )
            object.__setattr__(self, field, float(value))
        if not 0.0 < self.level < 1.0:
            raise TripwirePanelError(
                f"a lookback re-run verdict's level is a false-alarm rate "
                f"strictly inside (0, 1), got {self.level!r}"
            )
        if self.reference_threshold <= 0.0:
            raise TripwirePanelError(
                f"a lookback re-run verdict's reference threshold is positive, "
                f"got {self.reference_threshold!r}; the figure is standardized "
                "by it, and a bar of zero names an infinite stability"
            )
        expected_threshold = time_shuffle_threshold(self.dates, level=self.level)
        if self.reference_threshold != expected_threshold:
            raise TripwirePanelError(
                f"the lookback re-run verdict says its reference threshold is "
                f"{self.reference_threshold!r} but level {self.level!r} over "
                f"{self.dates} dates standardizes to {expected_threshold!r}; "
                "the record disagrees with its own arithmetic, and a figure "
                "measured in a bar no reader can recompute is a stability "
                "figure no reader can size"
            )
        # The perturbation recomputes from the record's own terms — the same
        # audit discipline the figure's recomputation below holds, applied to
        # the window.  ``jittered_lookback`` itself refuses the jitters that
        # perturb nothing, so this one check carries those refusals with it.
        if isinstance(self.jittered_lookback, bool) or not isinstance(
            self.jittered_lookback, int
        ):
            raise TripwirePanelError(
                f"a lookback re-run verdict's jittered lookback is a count of "
                f"bars, got {self.jittered_lookback!r}"
            )
        expected_jittered = jittered_lookback(self.dates, jitter=self.jitter)
        if self.jittered_lookback != expected_jittered:
            raise TripwirePanelError(
                f"the lookback re-run verdict says its jittered lookback is "
                f"{self.jittered_lookback} but a {self.jitter:+.4f} jitter of "
                f"{self.dates} bars is {expected_jittered}; the record "
                "disagrees with the perturbation it reports, so it was built "
                "somewhere other than this module's window"
            )
        if self.stability_threshold <= 0.0:
            raise TripwirePanelError(
                f"a lookback re-run verdict's configured stability threshold "
                f"is positive, got {self.stability_threshold!r}; a threshold "
                "of zero rejects every candidate the jitter moved at all — "
                "which is every candidate — and a negative one rejects none"
            )
        expected_stability = lookback_figure(
            self.reference_sharpe,
            self.rerun_sharpe,
            threshold=self.reference_threshold,
        )
        if self.stability != expected_stability:
            raise TripwirePanelError(
                f"the lookback re-run verdict says its stability is "
                f"{self.stability!r} but its own two statistics against the "
                f"reference threshold standardize to {expected_stability!r} "
                f"(|{self.rerun_sharpe!r} − {self.reference_sharpe!r}| over "
                f"{self.reference_threshold!r}); the record disagrees with the "
                "arithmetic it reports, so it was built somewhere other than "
                "this module's comparison"
            )
        for field in (
            "stability_rejected",
            "reference_rejected",
            "rerun_rejected",
            "rejected",
        ):
            if not isinstance(getattr(self, field), bool):
                raise TripwirePanelError(
                    f"a lookback re-run verdict's {field} is a boolean, got "
                    f"{getattr(self, field)!r}"
                )
        expected_stability_rejected = self.stability > self.stability_threshold
        if self.stability_rejected != expected_stability_rejected:
            raise TripwirePanelError(
                f"the lookback re-run verdict says stability_rejected="
                f"{self.stability_rejected!r} but its own terms decide "
                f"otherwise ({self.stability!r} against the configured "
                f"{self.stability_threshold!r}); the record states a rule it "
                "does not apply, and a rejection nothing can re-derive is a "
                "rejection nothing can audit"
            )
        expected_rejected = (
            self.stability_rejected
            or self.reference_rejected
            or self.rerun_rejected
        )
        if self.rejected != expected_rejected:
            raise TripwirePanelError(
                f"the lookback re-run verdict says rejected={self.rejected!r} "
                f"while its own causes are stability_rejected="
                f"{self.stability_rejected!r}, reference_rejected="
                f"{self.reference_rejected!r} and rerun_rejected="
                f"{self.rerun_rejected!r}; the decision is their disjunction, "
                "and a record whose bit is not the disjunction of the causes "
                "it carries states a failure nothing produced"
            )
        if self.outcome not in TRIPWIRE_OUTCOMES:
            raise TripwirePanelError(
                f"a lookback re-run verdict's outcome is one of "
                f"{', '.join(TRIPWIRE_OUTCOMES)} (§8's vocabulary), got "
                f"{self.outcome!r}"
            )
        expected_outcome = "tripwire_fail" if self.rejected else "ok"
        if self.outcome != expected_outcome:
            raise TripwirePanelError(
                f"the lookback re-run verdict says rejected={self.rejected!r} "
                f"but carries outcome {self.outcome!r}; the outcome word is "
                "the decision's own translation into the trial vocabulary, "
                "and the two spellings of one fact cannot disagree"
            )

    @property
    def rerun_seed(self) -> int | None:
        """``None`` — this axis holds the shuffle seed fixed, so there is no second seed.

        Feature 127's axis is what moves that knob; a lookback re-run that
        also re-drew the pairing *on purpose* would be two perturbations in
        one measurement.  The pairing still differs between the runs — the
        derangement is a function of the whole date list — but that is a
        consequence of the window, not a knob, and the record carries it as
        the module docstring's derivation rather than as a seed.
        """
        return None

    @property
    def subsample_seed(self) -> int | None:
        """``None`` — this axis thins no universe, so no subsample was drawn."""
        return None

    @property
    def subsample_fraction(self) -> float | None:
        """``None`` — this axis thins no universe, so no fraction applies."""
        return None

    def __hash__(self) -> int:
        # Consistent with __eq__, as every record in this workspace is; the
        # fields are all hashable, so no fold is needed.
        return hash(
            (
                self.node_id,
                self.tripwire,
                self.axis,
                self.horizon,
                self.dates,
                self.level,
                self.seed,
                self.lookback,
                self.jitter,
                self.jittered_lookback,
                self.reference_sharpe,
                self.rerun_sharpe,
                self.reference_threshold,
                self.stability,
                self.stability_threshold,
                self.stability_rejected,
                self.reference_rejected,
                self.rerun_rejected,
                self.rejected,
                self.outcome,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"LookbackRerunVerdict(node={self.node_id!r}, "
            f"{self.dates}→{self.jittered_lookback} dates, "
            f"jitter={self.jitter:+.4f}, "
            f"{self.reference_sharpe:+.4f}→{self.rerun_sharpe:+.4f}, "
            f"stability={self.stability:.4f} against "
            f"{self.stability_threshold:.4f}, outcome={self.outcome!r})"
        )


def _windowed(
    panel: Mapping[dt.date | str, Mapping[str, float]], days: list[dt.date | str]
) -> dict[dt.date | str, Mapping[str, float]]:
    """One panel, restricted to the window's dates — a trailing-suffix cut.

    The complement of :mod:`tripwires.subsample`'s ``_narrowed``: that cut
    *symbols* out of every date, this cuts *dates* out of the panel, and a
    date the cut removes is dropped rather than passed through empty for the
    same reason — the probe refuses an empty cross-section, and the refusal
    would surface as a malformed-panel error a long way from the window that
    caused it.  The rows themselves are handed through untouched: the jitter
    moves the window, never a value in it.
    """
    keep = set(days)
    return {day: row for day, row in panel.items() if day in keep}


def run_lookback_rerun(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
    *,
    node_id: str,
    lookback: int | None = None,
    jitter: float = DEFAULT_LOOKBACK_JITTER,
    seed: int = DEFAULT_SHUFFLE_SEED,
    level: float = DEFAULT_SHUFFLE_LEVEL,
    threshold: float = DEFAULT_LOOKBACK_STABILITY_THRESHOLD,
) -> LookbackRerunVerdict:
    """Re-run the probe over a jittered lookback and state the verdict — feature 130.

    The feature, in order: run feature 125's probe on ``(scores, targets)``
    under ``seed`` — the full-span run, which resolves the horizon and, when
    ``lookback`` is ``None``, *is* the reference; read the measured dates off
    that horizon (every date whose score and target cross-sections join, the
    same derivation the sibling axis uses); take the declared window — the
    last ``lookback`` of them, or the whole span when none was declared — and
    the jittered window behind it; run the same probe under the **same seed**
    over each window that is not already the span; measure the stability
    between the two surviving Sharpes in units of the *reference* run's own
    rejection threshold; and reject when that figure exceeds the configured
    ``threshold``, or when either run's own probe found leakage.

    Both windows are **trailing**: the newest measured bar is held fixed and
    the jitter moves the start.  The minus side is always runnable; the plus
    side is refused by name when the panel carries no history beyond the
    declared lookback to jitter into, and so is a declared lookback longer
    than the panel's measured span — a window the panel cannot fill was never
    the candidate's to declare.

    Deterministic in ``(scores, targets, node_id, lookback, jitter, seed,
    level, threshold)`` — the same re-run taken twice returns the same
    verdict bit-for-bit, which is what a stability figure has to be if a
    deployment is to compare one campaign's against another's.

    Raises :class:`~tripwires.TripwirePanelError` for a malformed panel, a
    bundle sharing no horizon with the scores, or fewer than two shared
    rebalance dates — the refusals the probe itself makes, propagated from
    the full-span run so a caller sees one cause rather than two frames of
    the same one; and for a ``lookback`` or ``jitter`` that names no
    perturbation this panel can run, which is this feature's own refusal
    because it is this feature's own way of measuring nothing.  Raises
    :class:`~tripwires.TripwireStatisticError` when either run's per-date
    series never varied.  A *detected failure is not an exception*: the
    causes are values on the verdict, because a re-run that raised on
    detection would be indistinguishable at the ledger from one that crashed.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise TripwirePanelError(
            f"the lookback re-run must name the node whose candidate it "
            f"re-runs, got {node_id!r}; a verdict that rejects a node it cannot "
            "name is a rejection nothing downstream can attribute"
        )
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the shuffle seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); both runs draw their derangement from it "
            "and a non-integer one names no stream"
        )
    if lookback is not None and (
        isinstance(lookback, bool) or not isinstance(lookback, int)
    ):
        raise TripwirePanelError(
            f"a declared lookback is a count of bars or None, got "
            f"{lookback!r} ({type(lookback).__name__}); the jitter is taken on "
            "a number of dates, and a non-integer names no window"
        )
    if lookback is not None and lookback < 2:
        raise TripwirePanelError(
            f"a declared lookback is at least two bars, got {lookback}; below "
            "that there is no shuffle, no dispersion and no statistic, and a "
            "window of one date is the run it re-runs"
        )
    # The full-span run first, so a panel the probe cannot measure refuses
    # once, from the run whose terms the record reports — and so the horizon
    # is the probe's own resolution rather than a second spelling of its
    # policy.  When no lookback is declared this run is also the reference.
    span = run_time_shuffle_tripwire(
        scores, targets, node_id=node_id, seed=seed, level=level
    )
    series = targets[span.horizon]
    # Sorted by the ``str`` of each key: both spellings a panel may carry —
    # ``date`` and ISO text — render chronologically under it, and the window
    # is a *span of time* rather than a slice of mapping order.  Mapping
    # order is insertion order, which the determinism contract §12 does not
    # trust and which need not be chronological at all.
    measured = sorted(
        (day for day in series if set(series[day]) & set(scores.get(day, {}))),
        key=str,
    )
    if lookback is not None and lookback > len(measured):
        raise TripwirePanelError(
            f"a declared lookback of {lookback} bars is longer than the "
            f"{len(measured)} measured dates the panel carries; the reference "
            "window is the declared one, and a window the panel cannot fill "
            "was never the candidate's to declare — silently clamping it to "
            "the span would measure a lookback that was not jittered because "
            "it did not exist"
        )
    declared = len(measured) if lookback is None else lookback
    jittered = jittered_lookback(declared, jitter=jitter)
    if jittered > len(measured):
        raise TripwirePanelError(
            f"a {jitter:+.4f} jitter of a {declared}-bar lookback names "
            f"{jittered} bars and the panel carries {len(measured)}; the plus "
            "side needs history beyond the declared lookback to jitter into, "
            "and this panel has none — declare a shorter lookback or jitter "
            "toward the minus side"
        )
    reference_window = measured[-declared:]
    rerun_window = measured[-jittered:]
    if declared == len(measured):
        reference = span
    else:
        reference = run_time_shuffle_tripwire(
            _windowed(scores, reference_window),
            {h: _windowed(s, reference_window) for h, s in targets.items()},
            node_id=node_id,
            seed=seed,
            level=level,
        )
    rerun = run_time_shuffle_tripwire(
        _windowed(scores, rerun_window),
        {h: _windowed(s, rerun_window) for h, s in targets.items()},
        node_id=node_id,
        seed=seed,
        level=level,
    )
    for run, window, bars in (
        (reference, reference_window, declared),
        (rerun, rerun_window, jittered),
    ):
        if run.horizon != span.horizon or run.dates != len(window) or bars < 2:
            raise TripwirePanelError(
                f"the two runs of one lookback re-run disagree about what they "
                f"measured (horizon {span.horizon}/{run.horizon}, "
                f"{len(window)} dates in the window against {run.dates} "
                f"measured); both windows are trailing cuts of one measured "
                f"grid, so the jitter can move the statistic and nothing else "
                "— a disagreement means the two runs were not the same probe"
            )
    stability = lookback_figure(
        reference.surviving_sharpe,
        rerun.surviving_sharpe,
        threshold=reference.threshold,
    )
    stability_rejected = stability > threshold
    rejected = stability_rejected or reference.rejected or rerun.rejected
    return LookbackRerunVerdict(
        node_id=reference.node_id,
        tripwire=PERTURBATION_STABILITY_NAME,
        axis=LOOKBACK_AXIS,
        horizon=reference.horizon,
        dates=reference.dates,
        level=reference.level,
        seed=reference.seed,
        lookback=lookback,
        jitter=jitter,
        jittered_lookback=jittered,
        reference_sharpe=reference.surviving_sharpe,
        rerun_sharpe=rerun.surviving_sharpe,
        reference_threshold=reference.threshold,
        stability=stability,
        stability_threshold=threshold,
        stability_rejected=stability_rejected,
        reference_rejected=reference.rejected,
        rerun_rejected=rerun.rejected,
        rejected=rejected,
        outcome="tripwire_fail" if rejected else "ok",
    )
