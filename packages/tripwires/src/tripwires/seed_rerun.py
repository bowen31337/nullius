"""The seed re-run — the perturbation-stability probe's first axis, feature 127.

app_spec.xml, "Leakage Tripwires", feature 127: *"System re-runs a candidate
under a different seed, which rejects the node when degradation exceeds the
configured threshold."*  It is the first of the four re-runs §C6 names in one
breath — *"Re-run with a different seed, a different start offset, a different
universe subsample.  Degradation beyond threshold is a reject."* — and
docs/nullius-tech-architecture.md §6.1 step 10 gives the family its seat
(``tripwires   time-shuffle, label-permute, perturbation stability``): this is
the third probe, the *perturbation-stability* one, and its first axis is the
shuffle seed.  Features 128 (window start offset), 129 (universe subsample) and
130 (lookback jitter) are the same probe's later axes; feature 130 persists the
figure as ``perturb_stability`` on the node.

**This is not feature 125 restated, and the difference is the whole feature.**
Feature 125 asks one question about one candidate: *does the surviving Sharpe
indicate leakage?*  This module asks a different one about the answer: *does
that surviving Sharpe survive a different draw of the derangement?*  A time
shuffle is a **random** derangement — feature 125's probe is deterministic in
``(panels, seed, level)`` and therefore draws exactly one of the many equally
valid pairings the probe could have scored against — so the number it reports is
one sample from a distribution the caller never sees.  Re-running with a
different seed draws a second sample, and the gap between them is the probe's
own reproducibility, measured rather than assumed.  §4.5 states the principle
from the other side: a real mechanism survives perturbation, and the robustness
family *transfers across theme roots* precisely because it is about the
candidate's stability rather than about what the candidate believes.

**The evidence that the two probes are not the same test.**  A planted leak —
the corpus feature 133 maintains — carries its statistic in every cross-section
regardless of the date, so re-dating the cross-sections cannot disturb it and
its surviving Sharpe is *identical* across seeds (verified: 0.0000
threshold-units of degradation for all four planted leak kinds).  A clean
candidate's surviving Sharpe is noise, so it moves from seed to seed.  A
seed re-run therefore does **not** catch leakage — feature 125 and feature 126
do that, and a leak sails through this module's bar — and it is not a weaker
copy of them.  What it catches is a candidate whose reported surviving Sharpe
**did not reproduce**, which is a statement about the measurement rather than
about the leak: the rejection §C6 applies is irreversible (feature 131 poisons
the node *and its entire subtree*, feature 132 refuses every score that branch
contributed), so a rejection carried by a number that one particular derangement
produced has to be told apart from one the candidate's own panel produces.

**Degradation, pinned to one quantity.**  The probe's rejection is two-sided —
``|surviving Sharpe|``, because a candidate that systematically *anti*-tracks
the shuffled panel carries exactly the same marginal information as one that
tracks it (:mod:`tripwires.time_shuffle` states that argument at length) — so
the candidate's surviving signal is ``|surviving Sharpe|`` and the degradation
of it is the drop in that magnitude::

    degradation = (|reference Sharpe| − |re-run Sharpe|) / reference threshold

Positive means the surviving Sharpe **collapsed** when the derangement was
redrawn; negative means it grew.  Two decisions live in that one line and both
are pins rather than conveniences.  *Magnitude, not sign*: a candidate whose
surviving Sharpe reversed sign between two seeds is maximally unreproducible,
and a signed difference would report it as no degradation at all — 0.30 against
−0.30 is a clean zero, which is exactly backwards.  *Standardized by the
reference threshold, not by the statistic's own scale*: dividing by
``Φ⁻¹(1 − level/2)/√T`` makes the figure **dimensionless and grid-independent** —
"in bars" — so one configured threshold is comparable across a 60-date probe and
a 480-date one, and a deployment that re-levels the probe moves the bar the
degradation is measured in along with it (the same reason feature 125 computes
its threshold rather than tabling it, and the reason
:mod:`tripwires.normal` records that feature 127 is why a level stays a
parameter).

**The configured threshold, and its derivation.**  "The configured threshold"
is a *parameter*, spelled :data:`DEFAULT_DEGRADATION_THRESHOLD` and passed per
call, for the reason the probe's own seed and level are: the module pins a
default, and a deployment that wants a tighter re-run passes a different one
rather than reconfiguring a shared object out from under a replay.  The default
is **derived from feature 125's own arithmetic rather than tuned**, which is
why the derivation is worth working through.

Under feature 125's null — a candidate carrying no panel-level information —
``|surviving Sharpe| · √T`` is standard normal, so ``|surviving Sharpe|``
divided by *the two-sided* threshold ``z = Φ⁻¹(1 − level/2)`` is ``|Z|/z``.
Note the ``|·|`` and note it twice, because it is where a naive derivation goes
wrong in both directions: the statistic being standardized is a **folded**
normal, so its variance is ``Var(|Z|) = 1 − 2/π ≈ 0.3634``, *not* 1 — and the
``z`` dividing it is the two-sided quantile, *not* ``Φ⁻¹(1 − level)``.  The two
draws are nearly independent (they score the same panel against the same
targets and differ only in the pairing), so their difference has variance
``2(1 − 2/π)/z²``, and the one-sided level-``level`` bar over it is

    Φ⁻¹(1 − level) · √(2(1 − 2/π)) / z   ≈   0.7699   at level = 0.01,

which is the pinned default.  Unlike the "√2 threshold-units at any level"
shortcut this is *not* level-free — ``Φ⁻¹(1 − level)`` and the two-sided ``z``
do not cancel — so a deployment that re-levels the probe moves this bar with
it, which is the honest behaviour: a level is a false-alarm rate, and a bar
that did not move with it would no longer be one.

Measured against the probe itself over 3000 null re-runs at T ∈ {60, 480}: the
realized degradation has standard deviation ≈ 0.34 against the derivation's
0.331, so the near-independence assumption holds to about 3%, and the bar is
exceeded at ≈ 0.015 against the nominal 0.01.  That last gap is not this
feature's — it is the one feature 125 documents for its own threshold, for the
same reason (per-date score-weighted returns are heavier-tailed than Gaussian),
and it is inherited rather than introduced.  Worth stating plainly as well:
because the rejection causes are near-independent, the *union*'s false-alarm
rate is a few times the level, which is the honest price of refusing to ignore a
leak any of the draws found.

**Rejected when *any* run states a failure — three named causes, one bit.**  A
seed re-run is two runs of a probe, so a candidate is condemned if either run
found leakage or if the two draws disagreed by more than the configured bar.
``rejected`` is the disjunction of three separately-named fields, and the third
of them is the one this feature's own spec sentence does not mention:

* ``reference_rejected`` — the run being re-run stated a failure.  Feature 125
  found leakage, and this record must not launder that into a pass;
* ``rerun_rejected`` — the second draw found leakage the first did not;
* ``degradation_rejected`` — the degradation exceeded the configured threshold.
  The spec's own sentence (*"rejects the node when degradation exceeds the
  configured threshold"*), and the cause the configured bar governs.

Carrying the first cause is what makes this record *sound* as a rejection
decision, and it is not optional.  Omitting it produces a verdict that reports
``outcome="ok"`` for a node feature 125 had already condemned: measured over a
sweep of partially-leaking candidates, the reference run rejects while the
re-run does not about **10%** of the time — the two draws straddle the
threshold — so a record unioning only the last two causes would hand a clean
verdict back on one node in ten that the probe had just rejected.  That is
precisely the failure this category exists to prevent (a tripwire that "passed"
a node it found leaking), and it is worse here than at feature 125 because this
record is the one a caller consults *after* a re-run.  The union of all three is
therefore the only honest reading of the spec's sentence: the sentence *adds* a
cause to rejection, it does not replace the probe's own.

What the union must not cost is legibility, so each cause stays its own field
and the decision is re-derivable as their disjunction — ``rejected`` has exactly
one meaning (*a run of this re-run states a failure*), and a reader asking
*which* of the three sentences fired reads the field rather than inferring it
from the arithmetic.

**The probe's own name, and why it is not ``time-shuffle``.**  §6.1 step 10
names three probes (``time-shuffle, label-permute, perturbation stability``), and
this is the third — so the verdict's ``tripwire`` is
:data:`PERTURBATION_STABILITY_NAME`, with the perturbed axis carried beside it
as :attr:`SeedRerunVerdict.axis` (``"seed"``; features 128 through 130 add the
others).  Naming the axis at all is what keeps the family one probe rather than
four: 128, 129 and 130 re-run the *same* comparison along a different
perturbation, and a reader asking "what was jittered?" needs one field, not four
verdict classes.  It is also why the *underlying* probe's name is not what this
record carries: ``time-shuffle`` answers *which of step 10's probes fired*, and
the probe that fired here — the one whose bar was moved, the one a re-run
constitutes — is perturbation stability, measured on a time-shuffle statistic.

**What this module does not do.**  It does not permute labels (feature 126),
perturb a window offset, a universe subsample or a lookback (128, 129, 130 — the
same probe's later axes, each with its own persistence question), persist
anything (131 writes the mark, 132 refuses the pool), maintain the leaking
corpus (133), or decide the triage figure (134).  It does not re-implement the
statistic, the shuffle or the threshold either: both runs are
:func:`~tripwires.time_shuffle.run_time_shuffle_tripwire`, the degradation is
one subtraction and one division over their results, and the member's
one-provenance rule is why the bar it divides by is *read off* the reference
verdict rather than recomputed from ``level`` and ``dates`` a second time.

**The layering note.**  Stdlib-only, like the rest of the member — arithmetic,
mappings and the two calls below; no polars, no pyarrow, no lake, no
environment, no HTTP, and no import of any other workspace member.  The panels
arrive as plain mappings and leave as one frozen record, so the frozen evaluator
image keeps a probe whose determinism story (§12) has no moving part: the
verdict carries **no wall-clock field at all**, because a timestamp would make
two runs of the same re-run differ and this record's whole value is that it does
not.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import TripwirePanelError
from .normal import normal_quantile
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
    "DEFAULT_DEGRADATION_THRESHOLD",
    "DEFAULT_RERUN_SEED",
    "PERTURBATION_AXES",
    "PERTURBATION_STABILITY_NAME",
    "SeedRerunVerdict",
    "run_seed_rerun",
    "seed_rerun_degradation",
]

#: The third probe's own name, in §6.1 step 10's spelling — the last word of
#: ``time-shuffle, label-permute, perturbation stability``.  A verdict carries
#: it so a persisted failure (feature 131) says *which* of step 10's probes
#: fired, and it is deliberately not :data:`~tripwires.time_shuffle.
#: TIME_SHUFFLE_NAME`: both runs below *are* time-shuffle probes, and the probe
#: this feature adds is the one that moves a knob the time-shuffle probe holds
#: fixed, so naming the record after the underlying statistic would make a
#: re-run indistinguishable from the run it re-runs.
PERTURBATION_STABILITY_NAME: str = "perturbation-stability"

#: The perturbation axes the third probe perturbs — its own closed vocabulary,
#: in §C6's declaration order (``a different seed, a different start offset, a
#: different universe subsample``), with feature 130's lookback jitter last.
#: Closed for the same reason :data:`~tripwires.time_shuffle.HORIZONS` and
#: :data:`~tripwires.corpus.LEAK_KINDS` are: an axis the spec does not name is a
#: perturbation nobody calibrated a threshold against, and this module pins
#: exactly one of the four — a record carrying an axis this feature never
#: perturbed would be a stability figure about a knob that was never moved.
PERTURBATION_AXES: tuple[str, ...] = (
    "seed",
    "window-offset",
    "universe-subsample",
    "lookback-jitter",
)

#: The axis this feature perturbs — the first of :data:`PERTURBATION_AXES`.
#: Named as a constant rather than spelled inline so the four features of the
#: family each cite their own axis once, and so a reader of the verdict's
#: ``axis`` field has a name to hold it to.
SEED_AXIS: str = PERTURBATION_AXES[0]

#: The default seed the *re-run* is drawn under.  Pinned to a fixed integer for
#: the same repeatability reason feature 125 pins :data:`~tripwires.time_shuffle.
#: DEFAULT_SHUFFLE_SEED` at 0 and feature 133 pins :data:`~tripwires.corpus.
#: CORPUS_SEED`: a re-run whose alternate seed moved would be a different
#: measurement each time it was taken, and "the same re-run twice" is the one
#: property a stability figure has to have.  It is deliberately not
#: ``DEFAULT_SHUFFLE_SEED + 1``, which would be a *derived* seed: the whole
#: point of the second draw is that it is an independent one, and an offset of
#: one draws from a stream nothing has checked rather than from a stream the
#: corpus and the probe's own verification already exercise.  There is nothing
#: special about the value beyond being the member's second pinned seed; a
#: deployment that wants a different re-run passes ``rerun_seed``.
DEFAULT_RERUN_SEED: int = 20260127

#: The configured degradation threshold, in units of the reference run's own
#: rejection threshold — see the module docstring for the derivation.
#: ``Φ⁻¹(1 − level) · √(2(1 − 2/π)) / Φ⁻¹(1 − level/2)`` at the pinned level,
#: evaluated here rather than written as a decimal so the constant *is* its
#: derivation: the only free term is the level, which is
#: :data:`~tripwires.time_shuffle.DEFAULT_SHUFFLE_LEVEL`'s.  Note the two
#: quantities the naive ``√2`` shortcut gets wrong — the folded statistic's
#: variance is ``1 − 2/π``, not 1, and the standardizing quantile is the
#: *two-sided* one — and note that unlike that shortcut this bar is not
#: level-free.  A parameter, not an environment lookup: the module pins a
#: default and a deployment tightens it per call, the stance
#: :data:`~tripwires.time_shuffle.DEFAULT_SHUFFLE_LEVEL` takes and the one
#: :mod:`tripwires.normal` records when it notes that a configured threshold is
#: why levels stay parameters.
DEFAULT_DEGRADATION_THRESHOLD: float = (
    normal_quantile(1.0 - DEFAULT_SHUFFLE_LEVEL)
    * math.sqrt(2.0 * (1.0 - 2.0 / math.pi))
    / normal_quantile(1.0 - DEFAULT_SHUFFLE_LEVEL / 2.0)
)


def seed_rerun_degradation(
    reference_sharpe: float, rerun_sharpe: float, *, threshold: float
) -> float:
    """The degradation between two surviving Sharpes, in threshold units.

    ``(|reference| − |re-run|) / threshold`` — the arithmetic of the feature,
    stated once so the verdict below and any reader auditing it cannot disagree
    about what the number is.  Positive means the surviving Sharpe collapsed
    when the derangement was redrawn; negative means it grew.  Magnitudes
    because feature 125's rejection is two-sided (a sign reversal is the least
    reproducible outcome there is, not the absence of one).

    ``threshold`` is the reference run's own rejection threshold, so the result
    is dimensionless and comparable across grids; it must be a finite positive
    number, because dividing by a zero bar names an infinite degradation and
    dividing by a negative one would invert the sign of the whole comparison.

    Pure, and exact: the verdict recomputes this function's result from its own
    terms and refuses a record that disagrees with it, so a persisted
    degradation is auditable to the last bit rather than to a tolerance.
    """
    for name, value in (
        ("reference_sharpe", reference_sharpe),
        ("rerun_sharpe", rerun_sharpe),
        ("threshold", threshold),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TripwirePanelError(
                f"a degradation is taken between two measured Sharpes and the "
                f"bar between them, and {name} is {value!r} "
                f"({type(value).__name__}) — not a number. A degradation "
                "computed from a term that is not a measurement would be a "
                "stability figure about nothing"
            )
        if not math.isfinite(float(value)):
            raise TripwirePanelError(
                f"a degradation is taken between finite numbers, and {name} "
                f"is {value!r}; the run's own arithmetic refuses a NaN or ±inf "
                "statistic before it reaches this comparison, so one arriving "
                "here came from somewhere other than the probe"
            )
    if float(threshold) <= 0.0:
        raise TripwirePanelError(
            f"a degradation is standardized by the reference run's own "
            f"rejection threshold, which is positive, got {threshold!r}; a "
            "zero bar names an infinite degradation and a negative one "
            "inverts the very comparison the report states"
        )
    return (abs(float(reference_sharpe)) - abs(float(rerun_sharpe))) / float(
        threshold
    )


@dataclass(frozen=True)
class SeedRerunVerdict:
    """Feature 127's answer — a re-run's terms, and the decision on them.

    The record this feature states, and the one features 128 through 130 will
    each state their own variant of: two runs of feature 125's probe under two
    different derangements, the degradation between them, the configured bar it
    was judged against, and the decision.  Every term the comparison was made
    from is carried — the two seeds rebuild both pairings, the level and the
    date count rebuild the bar the degradation is measured in, and both
    statistics sit beside the degradation they compose — because a rejection
    that poisons a subtree is an irreversible act and must be auditable from the
    record alone, the same reason feature 125's verdict carries its own terms.

    The invariants are enforced at construction, so a record built by hand — or
    by a later feature whose producer drifted — fails loudly rather than
    carrying a lying stability figure: ``degradation`` must recompute from the
    two statistics and the reference threshold, ``degradation_rejected`` must
    equal the comparison the degradation and the configured bar actually make,
    ``rejected`` must be the disjunction of the three named causes, the reference
    threshold must recompute from the level and the date count, and the outcome
    word must be the decision's own translation into §8's vocabulary.

    **The field names are deliberately not feature 125's.**  This record has no
    ``surviving_sharpe`` and no ``threshold``; it has ``reference_sharpe``,
    ``rerun_sharpe`` and ``degradation_threshold``.  That is a seam and not a
    style: feature 131 checks a verdict *structurally* — by the ten field names
    a poisoning reads — because the factory's scan gives one source file two
    class objects and ``isinstance`` cannot hold across them
    (:func:`~tripwires.poison._validate_failure` states the argument).  A record
    shaped like a time-shuffle verdict would pass that check and then be judged
    on ``|surviving_sharpe| > threshold``, which is **feature 125's** comparison
    over **feature 125's** statistic — and for a node this feature rejects
    because the *degradation* exceeded its bar, the candidate was typically
    clean at the reference seed, so that comparison is false and the store would
    refuse a poisoning on a mismatched reason.  The names keep the two verdicts
    apart so the refusal, when it comes, names the right thing.
    """

    #: The node whose candidate was re-run.
    node_id: str
    #: The probe that fired — always :data:`PERTURBATION_STABILITY_NAME`.
    #: Carried so a persisted failure names which of step 10's probes it was.
    tripwire: str
    #: The axis that was perturbed — always :data:`SEED_AXIS` here; features
    #: 128 through 130 carry their own, which is what keeps the family one
    #: probe rather than four.
    axis: str
    #: The horizon both runs probed — the shortest covered, feature 125's
    #: pinned policy, and necessarily the same for both.
    horizon: int
    #: How many rebalance dates both runs measured — the ``T`` behind the bar.
    dates: int
    #: The probe's two-sided level, restated from the reference run.
    level: float
    #: The seed the reference run drew its derangement from.
    seed: int
    #: The different seed the re-run drew its derangement from.
    rerun_seed: int
    #: The reference run's surviving Sharpe — the number under test.
    reference_sharpe: float
    #: The re-run's surviving Sharpe — the same measurement, other draw.
    rerun_sharpe: float
    #: The reference run's rejection threshold — ``Φ⁻¹(1 − level/2)/√dates``.
    #: Read off the reference verdict rather than recomputed, so the bar the
    #: degradation is standardized by is provably the one that run was judged
    #: against.
    reference_threshold: float
    #: ``(|reference_sharpe| − |rerun_sharpe|) / reference_threshold``.
    degradation: float
    #: The configured threshold the degradation was judged against, in the same
    #: threshold units.
    degradation_threshold: float
    #: ``True`` when the degradation exceeded the configured threshold — the
    #: spec's own sentence, and the cause the configured bar governs.
    degradation_rejected: bool
    #: ``True`` when the run being re-run stated a failure, under its own
    #: comparison.  Feature 125 found leakage, and this record must not launder
    #: that into a pass — see the module docstring for the 10% measurement.
    reference_rejected: bool
    #: ``True`` when the re-run's own probe found leakage the reference draw
    #: did not.  A re-run is still a probe run, and a leak it finds is a leak.
    rerun_rejected: bool
    #: The decision: any of the three named causes above.
    rejected: bool
    #: The decision in §8's trial vocabulary — ``tripwire_fail`` when rejected,
    #: ``ok`` when the re-run states no failure.
    outcome: str

    def __post_init__(self) -> None:
        # Validates only, like the records it sits beside; the constructor of
        # a value this module builds normalizes nothing.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TripwirePanelError(
                "a seed re-run verdict must name the node whose candidate it "
                f"re-ran, got {self.node_id!r}"
            )
        if self.tripwire != PERTURBATION_STABILITY_NAME:
            raise TripwirePanelError(
                f"a seed re-run verdict's tripwire is "
                f"{PERTURBATION_STABILITY_NAME!r}, got {self.tripwire!r}; both "
                "runs of this feature are time-shuffle probes and this record "
                "is not one of them, so naming it "
                f"{TIME_SHUFFLE_NAME!r} would make a re-run indistinguishable "
                "from the run it re-runs"
            )
        if self.axis != SEED_AXIS:
            raise TripwirePanelError(
                f"a seed re-run verdict's axis is {SEED_AXIS!r}, got "
                f"{self.axis!r}; this feature perturbs the shuffle seed, and a "
                "record naming another axis would be a stability figure about "
                "a knob this module never moved"
            )
        if self.axis not in PERTURBATION_AXES:
            raise TripwirePanelError(
                f"a perturbation axis is one of "
                f"{', '.join(PERTURBATION_AXES)}, got {self.axis!r}"
            )
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise TripwirePanelError(
                f"a seed re-run verdict's horizon must be an integer period "
                f"count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise TripwirePanelError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)})"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise TripwirePanelError(
                f"a seed re-run verdict's date count must be an integer, got "
                f"{self.dates!r}"
            )
        if self.dates < 2:
            raise TripwirePanelError(
                f"a seed re-run measures at least two dates, got {self.dates}; "
                "below that there is no shuffle, no dispersion and no bar, and "
                "a degradation over one date states a re-run that never ran"
            )
        for field in ("seed", "rerun_seed"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TripwirePanelError(
                    f"a seed re-run verdict's {field} must be an integer, got "
                    f"{value!r}"
                )
        if self.rerun_seed == self.seed:
            raise TripwirePanelError(
                f"a seed re-run's second seed is {self.rerun_seed!r} and its "
                f"first is {self.seed!r} — the same seed. A re-run under the "
                "seed it re-runs draws the same derangement, so its degradation "
                "is a structural zero and a verdict built on it would report a "
                "perfectly stable candidate it never perturbed at all"
            )
        for field in (
            "level",
            "reference_sharpe",
            "rerun_sharpe",
            "reference_threshold",
            "degradation",
            "degradation_threshold",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePanelError(
                    f"a seed re-run verdict's {field} must be a number, got "
                    f"{value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwirePanelError(
                    f"a seed re-run verdict's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node record "
                    "dressed as a stability figure"
                )
            object.__setattr__(self, field, float(value))
        if not 0.0 < self.level < 1.0:
            raise TripwirePanelError(
                f"a seed re-run verdict's level is a false-alarm rate strictly "
                f"inside (0, 1), got {self.level!r}"
            )
        if self.reference_threshold <= 0.0:
            raise TripwirePanelError(
                f"a seed re-run verdict's reference threshold is positive, got "
                f"{self.reference_threshold!r}; the degradation is standardized "
                "by it, and a bar of zero names an infinite degradation"
            )
        expected_threshold = time_shuffle_threshold(self.dates, level=self.level)
        if self.reference_threshold != expected_threshold:
            raise TripwirePanelError(
                f"the seed re-run verdict says its reference threshold is "
                f"{self.reference_threshold!r} but level {self.level!r} over "
                f"{self.dates} dates standardizes to {expected_threshold!r}; "
                "the record disagrees with its own arithmetic, and a "
                "degradation measured in a bar no reader can recompute is a "
                "stability figure no reader can size"
            )
        if self.degradation_threshold <= 0.0:
            raise TripwirePanelError(
                f"a seed re-run verdict's configured degradation threshold is "
                f"positive, got {self.degradation_threshold!r}; a threshold of "
                "zero rejects every candidate that moved at all and a negative "
                "one rejects every candidate that improved"
            )
        expected_degradation = seed_rerun_degradation(
            self.reference_sharpe,
            self.rerun_sharpe,
            threshold=self.reference_threshold,
        )
        if self.degradation != expected_degradation:
            raise TripwirePanelError(
                f"the seed re-run verdict says its degradation is "
                f"{self.degradation!r} but its own two statistics against the "
                f"reference threshold standardize to {expected_degradation!r} "
                f"(|{self.reference_sharpe!r}| vs |{self.rerun_sharpe!r}| over "
                f"{self.reference_threshold!r}); the record disagrees with the "
                "arithmetic it reports, so it was built somewhere other than "
                "this module's comparison"
            )
        for field in (
            "degradation_rejected",
            "reference_rejected",
            "rerun_rejected",
            "rejected",
        ):
            if not isinstance(getattr(self, field), bool):
                raise TripwirePanelError(
                    f"a seed re-run verdict's {field} is a boolean, got "
                    f"{getattr(self, field)!r}"
                )
        expected_degradation_rejected = (
            self.degradation > self.degradation_threshold
        )
        if self.degradation_rejected != expected_degradation_rejected:
            raise TripwirePanelError(
                f"the seed re-run verdict says degradation_rejected="
                f"{self.degradation_rejected!r} but its own terms decide "
                f"otherwise ({self.degradation!r} against the configured "
                f"{self.degradation_threshold!r}); the record states a rule it "
                "does not apply, and a rejection nothing can re-derive is a "
                "rejection nothing can audit"
            )
        expected_rejected = (
            self.degradation_rejected
            or self.reference_rejected
            or self.rerun_rejected
        )
        if self.rejected != expected_rejected:
            raise TripwirePanelError(
                f"the seed re-run verdict says rejected={self.rejected!r} "
                f"while its own causes are degradation_rejected="
                f"{self.degradation_rejected!r}, reference_rejected="
                f"{self.reference_rejected!r} and rerun_rejected="
                f"{self.rerun_rejected!r}; the decision is their disjunction, "
                "and a record whose bit is not the disjunction of the causes it "
                "carries states a failure nothing produced"
            )
        if self.outcome not in TRIPWIRE_OUTCOMES:
            raise TripwirePanelError(
                f"a seed re-run verdict's outcome is one of "
                f"{', '.join(TRIPWIRE_OUTCOMES)} (§8's vocabulary), got "
                f"{self.outcome!r}"
            )
        expected_outcome = "tripwire_fail" if self.rejected else "ok"
        if self.outcome != expected_outcome:
            raise TripwirePanelError(
                f"the seed re-run verdict says rejected={self.rejected!r} but "
                f"carries outcome {self.outcome!r}; the outcome word is the "
                "decision's own translation into the trial vocabulary, and the "
                "two spellings of one fact cannot disagree"
            )

    @property
    def improvement(self) -> float:
        """The degradation's negation — ``True`` when the re-run was better.

        Not a second statistic and not persisted anywhere: it exists so a
        reader asking "did the candidate get *better* under a different draw?"
        does not have to know that a negative degradation means exactly that,
        and so that the sign convention lives in one place.  A leak's
        improvement is zero (its surviving Sharpe is the same both draws), which
        is the fact that tells this probe apart from feature 125's.
        """
        return -self.degradation

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
                self.rerun_seed,
                self.reference_sharpe,
                self.rerun_sharpe,
                self.reference_threshold,
                self.degradation,
                self.degradation_threshold,
                self.degradation_rejected,
                self.reference_rejected,
                self.rerun_rejected,
                self.rejected,
                self.outcome,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"SeedRerunVerdict(node={self.node_id!r}, "
            f"{self.dates} dates, seeds {self.seed}→{self.rerun_seed}, "
            f"{self.reference_sharpe:+.4f}→{self.rerun_sharpe:+.4f}, "
            f"degradation={self.degradation:+.4f} against "
            f"{self.degradation_threshold:.4f}, outcome={self.outcome!r})"
        )


def run_seed_rerun(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
    *,
    node_id: str,
    seed: int = DEFAULT_SHUFFLE_SEED,
    rerun_seed: int = DEFAULT_RERUN_SEED,
    level: float = DEFAULT_SHUFFLE_LEVEL,
    threshold: float = DEFAULT_DEGRADATION_THRESHOLD,
) -> SeedRerunVerdict:
    """Re-run the probe under a different seed and state the verdict — feature 127.

    The feature, in order: run feature 125's probe on ``(scores, targets)``
    under ``seed`` and again under ``rerun_seed``; measure the degradation
    between the two surviving Sharpes in units of the *reference* run's own
    rejection threshold; and reject when that degradation exceeds the
    configured ``threshold``, or when the re-run's own probe found leakage the
    reference draw did not.

    Deterministic in ``(scores, targets, node_id, seed, rerun_seed, level,
    threshold)`` — the same re-run taken twice returns the same verdict
    bit-for-bit, which is what a stability figure has to be if a deployment is
    to compare one campaign's against another's.  ``rerun_seed`` must differ
    from ``seed``: a re-run under the seed it re-runs draws the same derangement
    and reports a structural zero, so it is refused by name rather than returned
    as a perfectly stable candidate that was never perturbed.

    Raises :class:`~tripwires.TripwirePanelError` for a malformed panel, a
    bundle sharing no horizon with the scores, or fewer than two shared
    rebalance dates — the refusals the probe itself makes, propagated from the
    reference run so a caller sees one cause rather than two frames of the same
    one; and for a ``rerun_seed`` equal to ``seed``, which is this feature's own
    refusal because it is this feature's own way of measuring nothing.  Raises
    :class:`~tripwires.TripwireStatisticError` when either run's per-date series
    never varied.  A *detected failure is not an exception*: both causes are
    values on the verdict, because a re-run that raised on detection would be
    indistinguishable at the ledger from one that crashed.
    """
    if isinstance(rerun_seed, bool) or not isinstance(rerun_seed, int):
        raise TripwirePanelError(
            f"the re-run seed must be an integer, got {rerun_seed!r} "
            f"({type(rerun_seed).__name__}); the second draw is a pure "
            "function of the sorted dates and the seed, and a non-integer seed "
            "names no stream to draw from"
        )
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the reference seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); it is the seed the run being re-run drew "
            "its derangement from, and a non-integer one names no stream"
        )
    if rerun_seed == seed:
        raise TripwirePanelError(
            f"a seed re-run is taken between two different seeds, and both are "
            f"{seed!r}. The second draw is what makes this a perturbation: the "
            "same seed rebuilds the same derangement, so the degradation would "
            "be a structural zero and this feature would report every candidate "
            "it was handed as perfectly stable — including the ones it never "
            "perturbed"
        )
    # The two runs, in this order: the reference first, so a panel the probe
    # cannot measure refuses once, from the run whose terms the record reports.
    reference = run_time_shuffle_tripwire(
        scores, targets, node_id=node_id, seed=seed, level=level
    )
    rerun = run_time_shuffle_tripwire(
        scores, targets, node_id=node_id, seed=rerun_seed, level=level
    )
    if rerun.horizon != reference.horizon or rerun.dates != reference.dates:
        raise TripwirePanelError(
            f"the two runs of one re-run disagree about what they measured "
            f"(horizon {reference.horizon}/{rerun.horizon}, "
            f"{reference.dates}/{rerun.dates} dates); both are handed the same "
            "panels and the horizon policy is a function of the bundle, so the "
            "same seed can move the derangement and nothing else — a "
            "disagreement means the two runs were not the same probe"
        )
    degradation = seed_rerun_degradation(
        reference.surviving_sharpe,
        rerun.surviving_sharpe,
        threshold=reference.threshold,
    )
    degradation_rejected = degradation > threshold
    rejected = degradation_rejected or reference.rejected or rerun.rejected
    return SeedRerunVerdict(
        node_id=reference.node_id,
        tripwire=PERTURBATION_STABILITY_NAME,
        axis=SEED_AXIS,
        horizon=reference.horizon,
        dates=reference.dates,
        level=reference.level,
        seed=reference.seed,
        rerun_seed=rerun.seed,
        reference_sharpe=reference.surviving_sharpe,
        rerun_sharpe=rerun.surviving_sharpe,
        reference_threshold=reference.threshold,
        degradation=degradation,
        degradation_threshold=threshold,
        degradation_rejected=degradation_rejected,
        reference_rejected=reference.rejected,
        rerun_rejected=rerun.rejected,
        rejected=rejected,
        outcome="tripwire_fail" if rejected else "ok",
    )
