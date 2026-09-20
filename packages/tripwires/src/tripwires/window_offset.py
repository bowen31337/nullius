"""The window-offset re-run — the perturbation-stability probe's second axis, feature 128.

app_spec.xml, "Leakage Tripwires", feature 128: *"System re-runs a candidate
from a different window start offset, persisting the resulting stability
delta."*  docs/alpha-engine-prd.md §C6 names the axis second in the sentence
that gives the family its rule — *"Re-run with a different seed, a different
start offset, a different universe subsample, a different lookback.
Degradation beyond threshold is a reject."* — so this is the axis the family's
own declaration order puts between feature 127's seed and feature 129's
subsample, and :data:`~tripwires.seed_rerun.PERTURBATION_AXES` has carried its
slot (``"window-offset"``) since feature 127 spelled the vocabulary.  The
persistence half of the sentence is no second module at all: the verdict this
one states is a row in the ledger feature 129 already owns
(:mod:`tripwires.stability`), keyed ``(node_id, axis)``, which is why that
table was built axis-keyed rather than node-keyed — the second axis needs no
second store, no second builder and no second seat, and its row's
``rerun_seed``/``subsample_seed``/``subsample_fraction`` columns read ``NULL``
for exactly this feature, in the ledger's own spelling of *this axis perturbs
no such knob*.

**The perturbation, stated precisely — and stated against its nearest
neighbour.**  A candidate is measured over a window of the panel's rebalance
dates, and the system re-runs it with that window *slid back*: the reference
window is the trailing ``L`` measured dates, the re-run window is the same
``L`` dates started ``offset`` bars earlier —
``measured[T−L−offset : T−offset]`` against ``measured[T−L : T]``.  The
length never moves; the position does.  That is the whole difference from
feature 130, and lookback's own docstring draws the line this module lives on:
*an offset moves the window along the grid, a jitter moves how long it is.*
The two are as orthogonal as two window perturbations can be — a candidate
fragile under one can be stable under the other, which is the family's
four-axes-not-one-knob argument in miniature — and one consequence is unique
to this axis: the slide moves the window's *newest* bar, the one date the
seed, subsample and lookback axes all hold fixed, so this is the only re-run
whose two windows differ at *both* ends while sharing every date in between
(``L − offset`` of ``L`` at the pinned twelfth).

**``window=None`` is the maximal runnable window, not the family's full span.**
Features 127, 129 and 130 all default their reference run to feature 125's
probe over the panels as handed in, and this axis structurally cannot: a
window that *is* the whole measured grid has no position to move to — the
slide needs ``offset`` bars of lead-in — so the reference a full-span default
would name is the one window the perturbation cannot touch.  The maximal
window that can be offset by ``k`` bars over ``T`` measured dates is ``T − k``,
and that is what ``window=None`` names, leaving exactly its own offset as
lead-in.  Two properties make it the right default rather than a consolation:
it is always runnable (any panel the probe can measure carries ``T ≥ 2`` dates
plus the offset's lead-in — the corpus's own 120-date grid runs two 108-bar
windows under the pinned twelfth, where a full-span default would make the
feature's own default call an error on the corpus's own grid), and it is the
*widest* measurement the axis can state, so a deployment comparing figures
across campaigns is comparing windows as wide as each panel allows.  A
declared ``window`` is honoured verbatim when it fits and refused by name when
it does not, exactly as feature 130 honours a declared lookback.

**The threshold's derivation, and the tempting one this axis inherits from
both its neighbours.**  The bar is derived from feature 125's own arithmetic
rather than tuned.  The two runs hold the seed, the universe and the length
fixed and move the position, so the tempting derivations are exactly the two
the siblings have already falsified, one from each side: feature 129's mistake
was writing noise-sharing runs as independent (the *names* were shared);
feature 130's was writing re-dated runs as correlated (the *dates* were
shared).  This axis shares dates — ``L − offset`` of ``L`` — so the tempting
bar is 130's wrong one read over a shared fraction instead of a length ratio:
a correlation ``√s`` over ``s = (L − offset)/L``, giving
``Var(ΔS) = 2(1 − √s)·σ²/L`` and a bar of ``√(2(1 − √s))``, which at the
pinned twelfth over the default window is ``√(2(1 − √(8/9))) ≈ 0.338``.

**That derivation is wrong here for the reason it was wrong there: the
shuffle.**  The derangement is a pure function of *(sorted dates, seed)* —
:func:`~tripwires.time_shuffle.time_shuffle_pairing` draws one uniform key per
date over the whole grid and sorts — so sliding the window does not keep the
shared dates' pairings and drop the rest: **every date is re-dated**, because
every date's key is drawn in a different lottery.  The dates the two windows
hold in common contribute the same *panel* but different *shuffles* of it,
and under feature 125's null the per-date noise of a shuffled cross-section
is fresh noise both times.  The two statistics are therefore independent with
equal variances ``σ²/L``, so ``Var(ΔS) = 2σ²/L``, and in units of the
reference run's own rejection threshold ``z·σ/√L`` the folded figure's bar at
``level`` is — the ``z`` and the ``√L`` cancelling, exactly as they do for 129
and 130 —

    DEFAULT_WINDOW_STABILITY_THRESHOLD = √2 ≈ 1.4142

The bar two equal-length independent runs have, with nothing left to depend
on: no ``level`` term, no ``dates`` term, and — unlike every sibling — no
``offset`` term either, because the offset changes *which* noise the runs
share and the re-dating leaves them sharing none of it at any offset.

**The calibration, measured rather than asserted.**  300 null re-runs at the
pinned twelfth over the 120-date, 30-symbol grid: the realized standard
deviation of the figure is 0.549 against the ``√2/z`` model's 0.549 —
agreement the model cannot fake — and the derived bar is exceeded at 0.017
against the nominal 0.01 (the same slightly-over-nominal side the probe
itself runs on, per-date books being heavier-tailed than Gaussian).  The
tempting shared-window bar of 0.338 is exceeded at **0.53** — every second
clean candidate rejected, a probe whose rejections would mean nothing.  The
suite pins the closed form and both rates, asserting the shared-window
shortcut **wrong** rather than close enough, the same treatment each sibling
suite gives its own tempting derivation.

There is a structural fact the wrong bar disagrees with, and it is the same
discontinuity feature 130 documents from its own side.  As ``offset → 0`` the
wrong bar ``√(2(1 − √s))`` tends to ``0`` while the true null stays
``√2``-wide for every ``offset ≥ 1`` — any change to the date list re-dates
everything — and at ``offset = 0`` exactly the figure is a structural zero
(same window, same derangement, same statistic, twice).  ``offset = 0`` is
therefore refused by name as a perturbation that never happened, the refusal
the jitter's zero gets, for the same reason.

**What this axis catches, and what it does not — the corpus's own answer.**
The maintained corpus (feature 133) plants whole-panel leaks — a full-sample
mean, a full-sample t-stat, each in both signs — and a whole-sample statistic
is invariant to *which stretch of the grid* the window holds for the same
reason it is invariant to which derangement re-dates it: all four figure
≈ 0.24 against the 1.41 bar, under it with a six-fold margin, so the
stability cause does not fire on the corpus.  What fires is the union: both
runs' *own* detections reject the leak in the trailing window and the offset
window alike, and the verdict reports which cause did the work rather than
laundering the rejection into a stability figure it was not.  Through feature
129's axis the same four panels figure ≈ 1.71 and reject *on the stability*;
through feature 127's, exactly ``0.0``; through feature 130's, ≈ 0.16 under
its own bar.  Four axes, four different answers about one candidate — the
family's argument, measured on one corpus.  What this axis adds over its
siblings is the §4.5 robustness question none of them can ask — *does the
statistic reproduce when the measurement is taken over a different stretch of
the same history?* — and its honest limit is the corpus's own measurement: a
whole-sample statistic does not care which stretch it was fed, and on such
candidates this axis's figure is noise.  The re-run that catches those is
feature 129's, whose thinning moves the statistic itself; what only this axis
can catch is a book whose answer depends on *where* along the grid it was
measured — recency, in one word — and 125's comparison at the trailing
window, not the offset's, is what catches a book fragile in the other
direction.

**The figure is the family's magnitude, not feature 127's signed drop.**
The spec's own words here are *"the resulting stability delta"*, and the
delta is the magnitude the family spells once: like 129's and 130's, two-sided
— a re-run that moved *up* from the offset window is as unreproduced as one
that moved down — and :func:`window_figure` is a delegation to
:func:`~tripwires.subsample.subsample_figure` rather than a second
implementation, for the reason :meth:`~tripwires.stability.StabilityRecord.
recomputes` delegates: one arithmetic, one provenance, and the axis that
happened to arrive first owns it.

**What this module does not do.**  It does not perturb the seed (127), the
universe (129) or the window's *length* (130 — the neighbour whose docstring
draws the line this one lives on); it does not permute labels (126), poison a
subtree (131), excise a pool (132), maintain the corpus (133) or decide the
triage figure (134, whose ``TRIAGE_AXES`` names the three axes its bands were
calibrated over — widening that set is a recalibration, not a one-line
change, and deliberately not this feature's).  It does not re-implement the
statistic, the shuffle or the threshold: the reference run is
:func:`~tripwires.time_shuffle.run_time_shuffle_tripwire` over the trailing
window, the re-run is the same function over the offset window, and the
figure is one subtraction, one ``abs`` and one division.  And it owns no
persistence: the sentence's *"persisting"* is :mod:`tripwires.stability`'s to
do, through the axis-keyed ledger that was waiting for this row.

**The layering note.**  Stdlib-only, like the rest of the member —
arithmetic, mappings, sorting and the three probe calls below; no polars, no
pyarrow, no lake, no environment, no HTTP, and no import of any other
workspace member.  The one import that could surprise a reader is
``.subsample``, and it is the delegation above rather than a dependency on a
sibling axis: the magnitude is shared vocabulary, spelled once.  The verdict
carries **no wall-clock field at all**, for the §12 reason every record in
this member carries it: two runs of the same re-run must return the same
verdict bit-for-bit, and a timestamp would make them differ in a field no
reader consults.
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
    "DEFAULT_WINDOW_OFFSET",
    "DEFAULT_WINDOW_STABILITY_THRESHOLD",
    "WINDOW_AXIS",
    "WindowRerunVerdict",
    "run_window_rerun",
    "window_figure",
    "window_starts",
]

#: The axis this feature perturbs — the second of
#: :data:`~tripwires.seed_rerun.PERTURBATION_AXES`, in §C6's declaration order
#: (*"... a different seed, a different start offset, ..."*).  Spelled by
#: indexing that tuple rather than by a literal here, for the reason
#: :data:`~tripwires.seed_rerun.SEED_AXIS` is: the family's four features must
#: not be able to drift apart on what the shared vocabulary is, and a reader
#: holding one axis has a name to hold this one to.
WINDOW_AXIS: str = PERTURBATION_AXES[1]

#: The offset the re-run slides the window back by, in bars — the size of the
#: move the spec's own *a different window start offset* (app_spec.xml feature
#: 128) names without quantifying.  Pinned at 12: a tenth of the corpus's own
#: 120-date grid (feature 133's ``CORPUS_GRID``), so the default call on the
#: corpus measures two 108-date windows — the same proportion of the grid
#: feature 130's pinned tenth jitters, but stated in bars, because a *start*
#: offset is a position and positions are counted, not scaled.  An absolute
#: count rather than a fraction of the panel, deliberately: the slide consumes
#: lead-in in bars, and a fractional offset would make one declaration mean
#: different slides on different grids.  At least one — ``0`` is refused by
#: name as a perturbation that never happened, for the reason the module
#: docstring's discontinuity paragraph gives.
DEFAULT_WINDOW_OFFSET: int = 12

#: The configured stability threshold, in units of the reference run's own
#: rejection threshold — see the module docstring for the derivation and for
#: the measurement that falsifies the tempting shared-window form.  It is
#: ``√2``, the equal-length independent-runs bar: the limit feature 130's
#: ``√(1 + 1/(1 + jitter))`` lands on as its jitter shrinks, stated here as
#: the whole answer because this axis moves the window's position and never
#: its length.  Written as the expression rather than as a literal so the
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
#:   ``z`` standard deviations out, so both cancel — the cancellation every
#:   sibling axis' bar finds, each from its own side of the same algebra.
#: * **It carries no ``offset`` term either**, and that is this axis' own
#:   surprise.  The wrong derivation makes the bar a function of the shared
#:   fraction ``s = (L − offset)/L``, vanishing as the offset shrinks, but the
#:   re-dating leaves the runs sharing no noise at *any* offset, so the true
#:   null is the same ``√2`` at a twelfth, a half and a hundred bars of slide.
#:   The offset sets how far the window moved, not how much noise the two
#:   measurements share.
#: * **It does not vanish as the offset shrinks, and must not.**  The *figure*
#:   is identically zero at ``offset = 0`` (the windows coincide, so the
#:   derangements do too), but for every ``offset ≥ 1`` the date list changes
#:   and the whole panel is re-dated — the same discontinuity feature 130
#:   documents for its jitter, which is why ``offset = 0`` is refused as a
#:   non-perturbation rather than barred over.
DEFAULT_WINDOW_STABILITY_THRESHOLD: float = math.sqrt(2.0)


def window_starts(
    span: int,
    *,
    offset: int = DEFAULT_WINDOW_OFFSET,
    window: int | None = None,
) -> tuple[int, int]:
    """The two windows' start indices — the reference's and the offset re-run's.

    ``(span − L, span − L − offset)``, where ``L`` is the declared ``window``
    or — when none was declared — the maximal window the offset can slide
    (``span − offset``, the axis' structural substitute for the family's
    full-span default; see the module docstring).  The reference window is the
    trailing ``L`` measured dates and the re-run is the same ``L`` started
    ``offset`` bars earlier, so the two *ends* are fixed by construction —
    the reference ends at the panel's newest bar, the re-run ``offset`` bars
    before it — and only the starts need naming.  Deterministic in
    ``(span, offset, window)``, so two callers naming one declared window get
    one pair of starts, bit-for-bit.

    Refused by name — never clamped — for every way this arithmetic can name
    a window that is not a perturbation at all, or one the panel cannot hold:

    * an ``offset`` that is not an integer, is ``0`` (the un-offset window is
      the reference run itself, and its figure would be a structural zero for
      every candidate including a planted one), or is negative;
    * a ``window`` below two bars (no shuffle, no statistic) or longer than
      the measured ``span`` — a window the panel cannot fill was never the
      candidate's to declare;
    * a declared ``window`` whose slide past the span needs lead-in the panel
      does not carry;
    * a span too short to leave the maximal window its two dates.
    """
    if isinstance(span, bool) or not isinstance(span, int):
        raise TripwirePanelError(
            f"a window offset is taken over a count of measured dates, got "
            f"{span!r} ({type(span).__name__}); the slide is a function of the "
            "grid's geometry, and a non-integer names no grid to move along"
        )
    if span < 2:
        raise TripwirePanelError(
            f"a window offset is taken over at least two measured dates, got "
            f"{span}; below that there is no shuffle, no dispersion and no "
            "statistic, and a one-date window is the run it re-runs"
        )
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TripwirePanelError(
            f"the window offset must be an integer count of bars, got "
            f"{offset!r} ({type(offset).__name__}); the slide is a pure "
            "function of the measured grid and the offset, and a non-integer "
            "names no distance to move the window by"
        )
    if offset == 0:
        raise TripwirePanelError(
            "the window offset is not 0; the un-offset window is the reference "
            "run itself, its figure is a structural zero for every candidate "
            "including a planted one, and a re-run that re-runs the window it "
            "was handed has measured nothing"
        )
    if offset < 0:
        raise TripwirePanelError(
            f"the window offset slides the window back by at least one bar, "
            f"got {offset!r}; the re-run starts earlier than the reference, "
            "and an offset the other way would need history the panel has "
            "not measured yet"
        )
    if window is not None and (isinstance(window, bool) or not isinstance(window, int)):
        raise TripwirePanelError(
            f"a declared window is a count of bars or None, got {window!r} "
            f"({type(window).__name__}); the slide is taken on a number of "
            "dates, and a non-integer names no window"
        )
    if window is not None and window < 2:
        raise TripwirePanelError(
            f"a declared window is at least two bars, got {window}; below "
            "that there is no shuffle, no dispersion and no statistic, and a "
            "window of one date is the run it re-runs"
        )
    if window is not None and window > span:
        raise TripwirePanelError(
            f"a declared window of {window} bars is longer than the {span} "
            "measured dates the panel carries; the reference window is the "
            "declared one, and a window the panel cannot fill was never the "
            "candidate's to declare — silently clamping it to the span would "
            "measure a window that was not offset because it did not exist"
        )
    length = span - offset if window is None else window
    if length + offset > span:
        raise TripwirePanelError(
            f"a {offset}-bar offset of a {window}-bar window needs "
            f"{window + offset} measured dates and the panel carries {span}; "
            "the slide consumes its own offset in lead-in, and this grid has "
            "no position left to move the window to — declare a shorter "
            "window or a smaller offset"
        )
    if length < 2:
        raise TripwirePanelError(
            f"a {offset}-bar offset of a {span}-date panel leaves a "
            f"{length}-bar window, and a re-run under two dates has no "
            "shuffle and no statistic to state; declare a shorter offset or "
            "a longer panel"
        )
    return span - length, span - length - offset


def window_figure(
    reference_sharpe: float, rerun_sharpe: float, *, threshold: float
) -> float:
    """The window-offset stability figure between two surviving Sharpes.

    A **delegation** to :func:`~tripwires.subsample.subsample_figure`, not a
    second implementation: ``|rerun − reference| / threshold`` is the
    perturbation-stability family's one magnitude — the spec's *"stability
    delta"* — spelled once in the module that arrived first and offered to
    this feature's callers under this feature's name, the same reason
    :meth:`~tripwires.stability.StabilityRecord.recomputes` reaches for that
    function rather than restating the subtraction.  Zero exactly when the
    slide changed nothing; positive in *both* directions when it did, because
    stability is two-sided for this axis as for 129's and 130's.

    All of that function's refusals arrive with it — a non-number or
    non-finite statistic, a threshold that is not a finite positive number —
    in this module's own callers' hands, which is what keeps a hand-built
    record and the entry point below from disagreeing about what the figure
    is.
    """
    return subsample_figure(reference_sharpe, rerun_sharpe, threshold=threshold)


@dataclass(frozen=True)
class WindowRerunVerdict:
    """Feature 128's answer — a window-offset re-run's terms, and the decision on them.

    The record this feature states: feature 125's probe run over the trailing
    window and again over the *offset* window — the same length, started
    ``offset`` bars earlier — the stability figure between them, the
    configured bar it was judged against, the offset that produced it, and
    the decision.  Every term the comparison was made from is carried — the
    seed rebuilds the derangement each run drew (over its *own* date list,
    which is the module docstring's whole derivation), the level and the
    date count rebuild the bar the figure is measured in, and both statistics
    sit beside the figure they compose — because a rejection that poisons a
    subtree is an irreversible act and must be auditable from the record
    alone, for the same reason feature 125's, 127's, 129's and 130's verdicts
    carry their own terms.

    The invariants are enforced at construction, so a record built by hand —
    or by a later feature whose producer drifted — fails loudly rather than
    carrying a lying stability figure: ``stability`` must recompute from the
    two statistics and the reference threshold, the windows must recompute
    from the span, the offset and the declared window together, a declared
    window must equal the reference run's own date count (the reference
    window *is* the declared window), ``rejected`` must be the disjunction of
    the three named causes, and the outcome word must be the decision's own
    translation into §8's vocabulary.

    **The field names are the family's, and deliberately not feature 125's.**
    This record has ``reference_sharpe``, ``rerun_sharpe`` and
    ``reference_threshold`` and no ``surviving_sharpe``/``threshold``/
    ``degradation``, for the seam reason
    :class:`~tripwires.subsample.SubsampleRerunVerdict` states: feature 131
    checks a verdict structurally, by field names, because the factory's scan
    gives one source file two class objects — and a record that shared
    feature 125's statistic names would pass the check and then be judged on
    feature 125's comparison over feature 125's statistic.  The stability
    names are shared with 129's and 130's verdicts *on purpose*: the records
    carry the same quantity in the same units, and the stability ledger's
    writer reads any of them.

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
    #: The axis that was perturbed — always :data:`WINDOW_AXIS` here.
    axis: str
    #: The horizon both runs probed — the shortest covered, feature 125's
    #: pinned policy, and necessarily the same for both.
    horizon: int
    #: How many rebalance dates the **reference** run measured — the declared
    #: window, or the maximal runnable one when none was declared.  The ``T``
    #: behind :attr:`reference_threshold`, and the length of *both* windows:
    #: this axis moves the window's position, never its length.
    dates: int
    #: The probe's two-sided level, restated from the reference run.
    level: float
    #: The seed both runs drew their derangement from.  **The same on both
    #: sides**, and the pairing still differs — the derangement is a function
    #: of the whole date list, so the offset window draws its own.  That fact
    #: is the module docstring's derivation, and the reason the seed being
    #: shared does not make the runs correlated.
    seed: int
    #: How many measured dates the panel carried on the probe's horizon — the
    #: full-span count the windows were cut from.  Carried so the slide is
    #: reconstructible from the record alone: with :attr:`dates`,
    #: :attr:`offset` and :attr:`window`, a reader can name both windows'
    #: bounds without the panel in hand, and the constructor below holds the
    #: record to that arithmetic.
    span: int
    #: The declared window, as the caller declared it — ``None`` meaning the
    #: maximal window this axis can offset (the span less the offset; the
    #: family's full-span default is structurally unavailable here, because a
    #: window that is the whole grid has no position to move to).  Carried
    #: verbatim rather than collapsed into :attr:`dates` because the
    #: difference between "the candidate declared 100 bars" and "the
    #: candidate declared everything the slide allows" is a fact about the
    #: candidate.  When not ``None`` it must equal :attr:`dates`: the
    #: reference window *is* the declared window.
    window: int | None
    #: The offset the re-run slid the window back by, in bars.  The
    #: perturbation's own size, and a parameter of the record rather than a
    #: constant so the figure and its bar can be audited against the slide
    #: that actually ran; refused at construction when it perturbs nothing.
    offset: int
    #: The reference run's surviving Sharpe — the number under test.
    reference_sharpe: float
    #: The re-run's surviving Sharpe — the same measurement, offset window.
    rerun_sharpe: float
    #: The reference run's rejection threshold — ``Φ⁻¹(1 − level/2)/√dates``.
    #: Read off the reference verdict rather than recomputed, so the bar the
    #: figure is standardized by is provably the one that run was judged
    #: against.
    reference_threshold: float
    #: ``|rerun_sharpe − reference_sharpe| / reference_threshold`` — the
    #: stability delta this feature's sentence says is persisted.
    stability: float
    #: The configured threshold the figure was judged against, in the same
    #: units — ``√2`` by default, level-, grid- and offset-free (see the
    #: module docstring).
    stability_threshold: float
    #: ``True`` when the figure exceeded the configured threshold — the spec's
    #: own cause on this axis, and the cause the configured bar governs.
    stability_rejected: bool
    #: ``True`` when the run being re-run stated a failure, under its own
    #: comparison.  Feature 125 found leakage, and this record must not
    #: launder that into a pass.
    reference_rejected: bool
    #: ``True`` when the offset window's own probe found leakage the
    #: reference draw did not — one of the two causes the corpus's
    #: whole-panel leaks actually fire through, their figure being
    #: window-stable.
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
                "a window re-run verdict must name the node whose candidate "
                f"it re-ran, got {self.node_id!r}"
            )
        if self.tripwire != PERTURBATION_STABILITY_NAME:
            raise TripwirePanelError(
                f"a window re-run verdict's tripwire is "
                f"{PERTURBATION_STABILITY_NAME!r}, got {self.tripwire!r}; both "
                "runs of this feature are time-shuffle probes and this record "
                "is not one of them, so naming it "
                f"{TIME_SHUFFLE_NAME!r} would make a re-run indistinguishable "
                "from the run it re-runs"
            )
        if self.axis != WINDOW_AXIS:
            raise TripwirePanelError(
                f"a window re-run verdict's axis is {WINDOW_AXIS!r}, got "
                f"{self.axis!r}; this feature slides the window, and a record "
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
                f"a window re-run verdict's horizon must be an integer "
                f"period count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise TripwirePanelError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)})"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise TripwirePanelError(
                f"a window re-run verdict's date count must be an integer, "
                f"got {self.dates!r}"
            )
        if self.dates < 2:
            raise TripwirePanelError(
                f"a window re-run measures at least two dates, got "
                f"{self.dates}; below that there is no shuffle, no dispersion "
                "and no bar, and a stability figure over one date states a "
                "re-run that never ran"
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TripwirePanelError(
                f"a window re-run verdict's seed must be an integer, got "
                f"{self.seed!r}"
            )
        if self.window is not None and (
            isinstance(self.window, bool) or not isinstance(self.window, int)
        ):
            raise TripwirePanelError(
                f"a window re-run verdict's declared window is a count of "
                f"bars or None, got {self.window!r}"
            )
        if self.window is not None and self.window != self.dates:
            raise TripwirePanelError(
                f"the window re-run verdict declares a window of "
                f"{self.window} bars but its reference run measured "
                f"{self.dates} dates; the reference window *is* the declared "
                "window, and a record whose two counts disagree states a "
                "window the reference run never measured"
            )
        for field in (
            "level",
            "reference_sharpe",
            "rerun_sharpe",
            "reference_threshold",
            "stability",
            "stability_threshold",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePanelError(
                    f"a window re-run verdict's {field} must be a number, "
                    f"got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwirePanelError(
                    f"a window re-run verdict's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node record "
                    "dressed as a stability figure"
                )
            object.__setattr__(self, field, float(value))
        if not 0.0 < self.level < 1.0:
            raise TripwirePanelError(
                f"a window re-run verdict's level is a false-alarm rate "
                f"strictly inside (0, 1), got {self.level!r}"
            )
        if self.reference_threshold <= 0.0:
            raise TripwirePanelError(
                f"a window re-run verdict's reference threshold is positive, "
                f"got {self.reference_threshold!r}; the figure is standardized "
                "by it, and a bar of zero names an infinite stability"
            )
        expected_threshold = time_shuffle_threshold(self.dates, level=self.level)
        if self.reference_threshold != expected_threshold:
            raise TripwirePanelError(
                f"the window re-run verdict says its reference threshold is "
                f"{self.reference_threshold!r} but level {self.level!r} over "
                f"{self.dates} dates standardizes to {expected_threshold!r}; "
                "the record disagrees with its own arithmetic, and a figure "
                "measured in a bar no reader can recompute is a stability "
                "figure no reader can size"
            )
        # The perturbation recomputes from the record's own terms — the same
        # audit discipline the figure's recomputation below holds, applied to
        # the slide.  ``window_starts`` itself refuses the offsets and windows
        # that perturb nothing or outrun the panel, so this one check carries
        # those refusals with it, and what remains is the length: the record's
        # ``dates`` must be the window its own span, offset and declaration
        # name.
        reference_start, _ = window_starts(
            self.span, offset=self.offset, window=self.window
        )
        expected_dates = self.span - reference_start
        if self.dates != expected_dates:
            raise TripwirePanelError(
                f"the window re-run verdict says its reference window measured "
                f"{self.dates} dates but a {self.offset}-bar offset over a "
                f"{self.span}-date panel with a "
                f"{'maximal runnable' if self.window is None else f'{self.window}-bar declared'} "
                f"window names {expected_dates}; the record disagrees with the "
                "perturbation it reports, so it was built somewhere other "
                "than this module's window"
            )
        if self.stability_threshold <= 0.0:
            raise TripwirePanelError(
                f"a window re-run verdict's configured stability threshold is "
                f"positive, got {self.stability_threshold!r}; a threshold of "
                "zero rejects every candidate the slide moved at all — which "
                "is every candidate — and a negative one rejects none"
            )
        expected_stability = window_figure(
            self.reference_sharpe,
            self.rerun_sharpe,
            threshold=self.reference_threshold,
        )
        if self.stability != expected_stability:
            raise TripwirePanelError(
                f"the window re-run verdict says its stability is "
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
                    f"a window re-run verdict's {field} is a boolean, got "
                    f"{getattr(self, field)!r}"
                )
        expected_stability_rejected = self.stability > self.stability_threshold
        if self.stability_rejected != expected_stability_rejected:
            raise TripwirePanelError(
                f"the window re-run verdict says stability_rejected="
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
                f"the window re-run verdict says rejected={self.rejected!r} "
                f"while its own causes are stability_rejected="
                f"{self.stability_rejected!r}, reference_rejected="
                f"{self.reference_rejected!r} and rerun_rejected="
                f"{self.rerun_rejected!r}; the decision is their disjunction, "
                "and a record whose bit is not the disjunction of the causes "
                "it carries states a failure nothing produced"
            )
        if self.outcome not in TRIPWIRE_OUTCOMES:
            raise TripwirePanelError(
                f"a window re-run verdict's outcome is one of "
                f"{', '.join(TRIPWIRE_OUTCOMES)} (§8's vocabulary), got "
                f"{self.outcome!r}"
            )
        expected_outcome = "tripwire_fail" if self.rejected else "ok"
        if self.outcome != expected_outcome:
            raise TripwirePanelError(
                f"the window re-run verdict says rejected={self.rejected!r} "
                f"but carries outcome {self.outcome!r}; the outcome word is "
                "the decision's own translation into the trial vocabulary, "
                "and the two spellings of one fact cannot disagree"
            )

    @property
    def rerun_seed(self) -> int | None:
        """``None`` — this axis holds the shuffle seed fixed, so there is no second seed.

        Feature 127's axis is what moves that knob; a window re-run that also
        re-drew the pairing *on purpose* would be two perturbations in one
        measurement.  The pairing still differs between the runs — the
        derangement is a function of the whole date list — but that is a
        consequence of the slide, not a knob, and the record carries it as
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
                self.span,
                self.window,
                self.offset,
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
            f"WindowRerunVerdict(node={self.node_id!r}, "
            f"{self.dates} dates slid {self.offset} back, "
            f"{self.reference_sharpe:+.4f}→{self.rerun_sharpe:+.4f}, "
            f"stability={self.stability:.4f} against "
            f"{self.stability_threshold:.4f}, outcome={self.outcome!r})"
        )


def _windowed(
    panel: Mapping[dt.date | str, Mapping[str, float]], days: list[dt.date | str]
) -> dict[dt.date | str, Mapping[str, float]]:
    """One panel, restricted to a window's dates — a cut of the measured grid.

    The complement of :mod:`tripwires.subsample`'s ``_narrowed`` and the
    sibling of :mod:`tripwires.lookback`'s own: that cut drops dates the
    jitter moved out of a trailing window, this one hands the offset window
    its dates, and both drop rather than pass a date through empty for the
    same reason — the probe refuses an empty cross-section, and the refusal
    would surface as a malformed-panel error a long way from the window that
    caused it.  The rows themselves are handed through untouched: the slide
    moves the window, never a value in it.
    """
    keep = set(days)
    return {day: row for day, row in panel.items() if day in keep}


def run_window_rerun(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
    *,
    node_id: str,
    window: int | None = None,
    offset: int = DEFAULT_WINDOW_OFFSET,
    seed: int = DEFAULT_SHUFFLE_SEED,
    level: float = DEFAULT_SHUFFLE_LEVEL,
    threshold: float = DEFAULT_WINDOW_STABILITY_THRESHOLD,
) -> WindowRerunVerdict:
    """Re-run the probe from a different window start offset — feature 128.

    The feature, in order: run feature 125's probe on ``(scores, targets)``
    under ``seed`` — the full-span run, which resolves the horizon and
    propagates the probe's own panel refusals once, from one frame; read the
    measured dates off that horizon (every date whose score and target
    cross-sections join, the same derivation the sibling axes use); name the
    two windows — the trailing ``window`` dates, or the maximal runnable
    window when none was declared, and the same-length window started
    ``offset`` bars earlier; run the same probe under the **same seed** over
    each; measure the stability between the two surviving Sharpes in units of
    the *reference* run's own rejection threshold; and reject when that
    figure exceeds the configured ``threshold``, or when either run's own
    probe found leakage.

    The full-span run is never the reference here, whatever is declared — the
    one structural difference from feature 130's runner, where declaring the
    span reuses the span run.  An offset window is by construction a strict
    sub-window of the span (the slide needs its own offset in lead-in), so
    the reference is always a run of its own and the span run's job is to
    resolve the horizon and to refuse a panel the probe cannot measure before
    any window arithmetic is consulted.

    Deterministic in ``(scores, targets, node_id, window, offset, seed,
    level, threshold)`` — the same re-run taken twice returns the same
    verdict bit-for-bit, which is what a stability figure has to be if a
    deployment is to compare one campaign's against another's.

    Raises :class:`~tripwires.TripwirePanelError` for a malformed panel, a
    bundle sharing no horizon with the scores, or fewer than two shared
    rebalance dates — the refusals the probe itself makes, propagated from the
    full-span run so a caller sees one cause rather than two frames of the
    same one; and for a ``window`` or ``offset`` that names no perturbation
    this panel can run, which is this feature's own refusal because it is
    this feature's own way of measuring nothing.  Raises
    :class:`~tripwires.TripwireStatisticError` when either run's per-date
    series never varied.  A *detected failure is not an exception*: the
    causes are values on the verdict, because a re-run that raised on
    detection would be indistinguishable at the ledger from one that crashed.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise TripwirePanelError(
            f"the window re-run must name the node whose candidate it "
            f"re-runs, got {node_id!r}; a verdict that rejects a node it cannot "
            "name is a rejection nothing downstream can attribute"
        )
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the shuffle seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); both runs draw their derangement from it "
            "and a non-integer one names no stream"
        )
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TripwirePanelError(
            f"the window offset must be an integer count of bars, got "
            f"{offset!r} ({type(offset).__name__}); the slide is a pure "
            "function of the measured grid and the offset, and a non-integer "
            "names no distance to move the window by"
        )
    if offset == 0:
        raise TripwirePanelError(
            "the window offset is not 0; the un-offset window is the reference "
            "run itself, its figure is a structural zero for every candidate "
            "including a planted one, and a re-run that re-runs the window it "
            "was handed has measured nothing"
        )
    if offset < 0:
        raise TripwirePanelError(
            f"the window offset slides the window back by at least one bar, "
            f"got {offset!r}; the re-run starts earlier than the reference, "
            "and an offset the other way would need history the panel has "
            "not measured yet"
        )
    if window is not None and (
        isinstance(window, bool) or not isinstance(window, int)
    ):
        raise TripwirePanelError(
            f"a declared window is a count of bars or None, got "
            f"{window!r} ({type(window).__name__}); the slide is taken on a "
            "number of dates, and a non-integer names no window"
        )
    if window is not None and window < 2:
        raise TripwirePanelError(
            f"a declared window is at least two bars, got {window}; below "
            "that there is no shuffle, no dispersion and no statistic, and a "
            "window of one date is the run it re-runs"
        )
    # The full-span run first, so a panel the probe cannot measure refuses
    # once, from the run whose horizon resolution the windows inherit — and
    # so the horizon is the probe's own resolution rather than a second
    # spelling of its policy.  It is never the reference (see above).
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
    # The slide's own refusals — an offset or a declared window this panel
    # cannot run — arrive with the pair, once the grid they run over is
    # known.
    reference_start, rerun_start = window_starts(
        len(measured), offset=offset, window=window
    )
    length = len(measured) - reference_start
    reference_window = measured[reference_start:]
    rerun_window = measured[rerun_start : rerun_start + length]
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
    for run, window_days in ((reference, reference_window), (rerun, rerun_window)):
        if run.horizon != span.horizon or run.dates != len(window_days):
            raise TripwirePanelError(
                f"the two runs of one window re-run disagree about what they "
                f"measured (horizon {span.horizon}/{run.horizon}, "
                f"{len(window_days)} dates in the window against {run.dates} "
                f"measured); both windows are equal-length cuts of one "
                f"measured grid, so the slide can move the statistic and "
                "nothing else — a disagreement means the two runs were not "
                "the same probe"
            )
    stability = window_figure(
        reference.surviving_sharpe,
        rerun.surviving_sharpe,
        threshold=reference.threshold,
    )
    stability_rejected = stability > threshold
    rejected = stability_rejected or reference.rejected or rerun.rejected
    return WindowRerunVerdict(
        node_id=reference.node_id,
        tripwire=PERTURBATION_STABILITY_NAME,
        axis=WINDOW_AXIS,
        horizon=reference.horizon,
        dates=reference.dates,
        level=reference.level,
        seed=reference.seed,
        span=span.dates,
        window=window,
        offset=offset,
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
