"""Feature 339 — decay priors revised from observed forward half-life.

app_spec.xml, "Forward-Test Tracking", feature 339: *System updates decay
priors from observed forward half-life, which returns revised inputs to
campaign planning.*  The sentence is prd §13.4's third clause made operative:
*"Those outcomes become labels. They recalibrate ``β₄`` (sim-reality
divergence), the decay priors, and which signal families the objective should
reward"* — and the risk register states what the recalibration is *for*:
*"Alpha decay outpaces discovery | Medium | Forward-test loop measures decay
empirically; feed half-life into ``plan_grid``"*.  β₄ is feature 338's; the
signal families are a later feature's.  The decay priors are this module's.

**The half-life is §11's own line, dated.**  §11's secondary promotion
criterion reads *"Forward-test IC retention: live IC ÷ backtest IC at 90 days
| > 0.5"* — a signal passes while it retains **more than half** of its
backtest edge, so the day its retention first falls to half is the day the
criterion stops holding: the signal's *half-life*, in days, from the boundary
the record draws.  The retention itself is feature 337's figure — the mean of
the observed ``live_ic`` rows divided by the opening row's ``backtest_ic`` —
and the half-life is that same statistic computed on **prefixes**: the
running mean over every day up to and including each observed day, and the
first day whose running mean falls to :data:`RETENTION_LINE` of the backtest.
A mean and not the day's own figure, because §C10 demotes only *"over a
statistically meaningful window"* — one noisy day below the line is not a
decay, and a half-life dated on it would hand ``plan_grid`` a timescale nobody
measured.  §C10's own 40% line is deliberately **not** the one read here: that
line demotes a signal, this one dates it, and §11's 0.5 is the figure the
word *half-life* actually names.

**A signal that has not fallen to half is censored, and the censoring is
carried rather than resolved.**  A healthy young signal — three weeks old,
retaining everything — has no observed half-life; what it has is a *bound*:
its half-life is greater than the days it has been observed.  The two silent
resolutions are both fabrications, and both are refused: averaging the bound
in as though it were the value (every censored signal read as though it had
died on its last observed day — a prior that would tighten toward pessimism
precisely when the fleet is healthy) and dropping it (evidence count that
disagrees with the rows).  The censored signal is *counted* —
:attr:`DecayPriorRevision.censored_signals` — and its bound is stated in its
own answer, exactly the way :mod:`forward.retention` refuses to average a
missed day in as a zero: an absence is not a measurement.

**The prior, and the update.**  A decay prior is the figure campaign planning
carries about how long a promoted signal's edge survives — the timescale that
decides how much refinement a family is worth before its members decay out
(the register's *feed half-life into ``plan_grid``*).  Before any forward
evidence exists the prior is the one the prd itself states: **90 days**, §5's
*"After 90 days, that signal has a track record"* and §11's *"at 90 days"*
— the horizon the whole member is shaped around, held with
:data:`PRIOR_WEIGHT` pseudo-observations, the same strength feature 228's
family conditioning gives its zero-evidence prior (``n/(n+6)``): six real
half-lives outvote the default, and until then the default stands.  The update
is the conjugate shrinkage that family established — the revised prior is the
pseudo-count blend::

    revised = (PRIOR_WEIGHT × 90 + Σ observed half-lives) / (PRIOR_WEIGHT + n)

so that **zero observations answer the prior exactly** — the zero-evidence
law, the same stance feature 228 takes (*zero-evidence == schedule(beta)*)
and feature 267 takes toward ``π₀`` — and every observed half-life moves the
figure by ``1/(weight + n)`` of the distance between it and the prior mean.

**Nothing is persisted, and that is this feature's own wording.**  The
category's sibling sentence for β₄ — feature 338, *persists the revised
beta-four value per cycle* — says *persist*; this one says *returns*, and the
split is the spec's own.  The revision is a pure function of rows that still
hold every operand: the observed days and coefficients are feature 333's, the
backtest divisor feature 337's, the boundary feature 332's, and re-deriving
the blend from them is cheaper and safer than keeping a copy that can drift —
the same reason :mod:`forward.retention` keeps no memo of its ratio and
feature 267's reads rebuild from the pair.  Where a campaign's planned-with
figures live is the planning side's own question: feature 242's prior-campaign
manifests are the memory ``plan_grid`` reads, so a campaign planned against a
revised prior records it there, in the member that consumes it.  This module
authors **no table and no DDL**, and adds no component: the act climbs the
member's one ladder off the composed ``forward`` store.

**The aggregate counts what it cannot measure, and refuses what it cannot
state.**  The revision reads every record the table holds, and a fleet is
heterogeneous on purpose: a signal whose ``backtest_ic`` has not landed yet
(feature 337's writer is a separate call) is *unbacktested* — counted, not
fatal, because a young deployment must not have its outer loop blocked by the
one figure that has not arrived; a signal with a divisor and no observations
is *unobserved*; a signal whose backtest is exactly zero — the honest figure
of a signal with no measured edge, which :meth:`forward.retention.
ForwardIcRetentions.record_backtest_ic` stores — has no edge whose halving
could be dated and is counted as *zero-backtest*.  What the aggregate refuses
is a row it cannot vouch for: a record whose rows carry two promotion
instants (a vintage nobody can state, refused in this module's own
vocabulary), a stored backtest outside ``[−1, 1]`` (refused by feature 337's
own coefficient gate, which is the one spelling of *is this a coefficient*
this member has), and a **negative** backtest — a figure a promoted signal
cannot honestly carry, because promotion requires a positive edge, and the
halving of a negative coefficient is not a decay threshold anyone defined.

**The per-signal spelling refuses what the aggregate counts.**  One caller
asking for *this* signal's half-life (:meth:`ForwardDecayPriors.half_life`)
is asking a question with one subject and a specific repair, so the absences
the aggregate shrugs at are refusals here — no record (open one, feature
332's route), no observation (run the job, feature 333), no backtest landed
(land it, feature 337's writer) — each naming its repair the way
:mod:`forward.retention` names its own three.  The split is the same one
feature 337 draws between its writer and its reader: an absence over a fleet
is a state to carry; an absence about the one signal you asked for is a
question the caller needs answered in words.

**The answers re-derive themselves.**  :class:`ForwardHalfLife` refuses an
instance whose crossing day is not its own ``half_life_days`` from the
boundary, whose crossing mean does not actually fall to half, or whose
censored half carries crossing figures — and :class:`DecayPriorRevision`
refuses an instance whose ``revised_half_life_days`` is not the blend of its
own evidence, or whose prior is not the member's own two constants.  The
comparisons are exact, not tolerances, for the reason
:mod:`forward.reconciliation` compares its difference exactly: both sides are
arithmetic this member performed itself over figures it read, so a
disagreement is not rounding — it is a value that was never the answer to the
derivation it sits beside.  A fabricated revision cannot reach ``plan_grid``
any more than a fabricated retention can reach §C10's demotion line.

**No clock is read anywhere in the module.**  Every date in both answers is
the table's own — boundary days, crossing days, the latest observed day —
never the writer's, for the reason :mod:`forward.observation` refuses a
default day: the vintage of a decay measurement is a fact about the data, and
a revision dated "now" would be a prior revised against whatever the job
schedule happened to be.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Any

from .errors import (
    FORWARD_DECAY_PRIOR_ERROR_CODE,
    ForwardDecayPriorError,
    ForwardError,
)
from .record import (
    _READ_SQL,
    DATABASE_URL_ENV,
    FORWARD_RECORD_TABLE,
    NODE_ID_COLUMN,
    OBSERVED_ON_COLUMN,
    ForwardRecord,
    _record_from_row,
    _sqlite_path,
    _validated_date,
    _validated_live_ic,
    _validated_uuid,
)
from .retention import BACKTEST_IC_COLUMN, _validated_backtest_ic
from .schema import bootstrap_schema

__all__ = [
    "FORWARD_PRIOR_SEAM",
    "PRIOR_HALF_LIFE_DAYS",
    "PRIOR_WEIGHT",
    "RETENTION_LINE",
    "REVISED_HALF_LIFE_KEY",
    "DecayPriorRevision",
    "ForwardDecayPriors",
    "ForwardHalfLife",
    "forward_half_life",
    "revised_decay_prior",
]

#: §11's own line, the one the word *half-life* names: retention above
#: ``0.5`` is the criterion a promoted signal must hold, so the day the prefix
#: retention first reaches it is the day the edge fell to half.  Deliberately
#: **not** §C10's 40%: that line demotes a signal (feature 337's readers),
#: this one dates it, and conflating them would make every half-life one
#: fifth shorter than the criterion §11 states over it.
RETENTION_LINE: float = 0.5

#: The decay prior campaign planning carries before any forward evidence
#: exists — prd §5's own figure, *"After 90 days, that signal has a track
#: record"*, which §11's criterion restates as *"at 90 days"*.  The horizon
#: the whole member is shaped around is therefore the zero-evidence prior:
#: planning that knew nothing about real decay would assume an edge survives
#: exactly as long as the window that measures it.
PRIOR_HALF_LIFE_DAYS: float = 90.0

#: How many observed half-lives the prior is worth — its pseudo-count.  Six,
#: the strength feature 228's family conditioning gives its zero-evidence
#: prior (``w = n/(n+6)``): the seventh real half-life tips the blend to the
#: evidence's side, and until then the 90-day default stands.  Spelled once
#: so the revision's arithmetic and its documentation cannot disagree.
PRIOR_WEIGHT: float = 6.0

#: The key the revised figure travels under in :meth:`DecayPriorRevision.
#: summary` — the one a campaign planner reads.  Not a column name: no table
#: holds the revision (see the module docstring for why), and the spelling is
#: the risk register's own words (*feed half-life into ``plan_grid``*), so a
#: reader of the mapping is reading the input the planner was promised.
REVISED_HALF_LIFE_KEY = "revised_half_life_days"

#: The attribute :meth:`ForwardDecayPriors.over` reads off a composed store —
#: deliberately the same string features 333's, 340's and 337's seam readers
#: read: every act in this member writes or reads the one table the composed
#: ``forward`` component points at, so a second seam spelling would be a
#: second way to name one database.
FORWARD_PRIOR_SEAM = "database_url"

#: Every signal the table holds, ascending — the revision is taken over the
#: whole fleet, so the read is the whole table rather than one key.  ``ORDER
#: BY`` makes the answer's evidence order deterministic, which is what makes
#: two revisions of one table comparable row for row.
_NODES_SQL = (
    f"SELECT DISTINCT {NODE_ID_COLUMN} FROM {FORWARD_RECORD_TABLE} "
    f"ORDER BY {NODE_ID_COLUMN}"
)


# -- Validation -------------------------------------------------------------------


def _validated_constant(value: Any, constant: float, field_name: str) -> float:
    """Return ``value`` as this member's own prior constant, or refuse it.

    The prior half-life and its weight are not parameters a caller chooses —
    they are the planning defaults the prd states and this module revises, so
    an instance carrying a different figure is not this feature's answer, and
    the gate is equality with the constant rather than a range.  ``bool`` is
    refused first and the value must be a finite real, for the reason every
    numeric validator in this workspace refuses both: ``True`` is not a
    half-life and a NaN compares false against everything, including the
    equality that would otherwise refuse it.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"{field_name} must be the member's own decay prior as a real "
            f"number — got {value!r} ({type(value).__name__}); the prior is "
            "not a figure a caller states (prd §13.4's recalibration starts "
            "from the 90-day horizon §5 and §11 state, held at feature 228's "
            "pseudo-count strength), so an answer carrying some other figure "
            "in its place is not the input campaign planning was promised "
            "(feature 339)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"{field_name} must be finite — got {narrowed!r}; the prior is a "
            "duration in days and a weight, and neither is a quantity a NaN "
            "or an infinity could honestly carry into the blend the revision "
            "performs over them (feature 339)"
        )
    if narrowed != constant:
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"{field_name} must be this member's own prior ({constant!r}) — "
            f"got {narrowed!r}. The decay prior is not a caller's choice: it "
            "is the figure prd §5 and §11 state (90 days) at the pseudo-count "
            "strength feature 228 established, revised only by the observed "
            "forward half-lives. An answer built over a different prior would "
            "hand campaign planning a decay timescale nobody calibrated "
            "(feature 339)"
        )
    return narrowed


def _validated_count(value: Any, field_name: str) -> int:
    """Return ``value`` as an observed-day count, or refuse it.

    Whole and at least one, ``bool`` refused first — the same gate
    :func:`forward.retention._validated_count` applies over its own module,
    restated here so the refusal arrives in this feature's vocabulary: each
    module refuses in its own words, the member's ``_one_vintage`` precedent.
    The count is the evidence the crossing is dated over; zero is refused
    because a signal observed on no day is refused earlier, by name, as a
    record the job has not reached.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"{field_name} must be a whole number of days — got {value!r} "
            f"({type(value).__name__}); a half-life is dated in days from the "
            "boundary the record draws, and a count that is not a whole "
            "number of them dates nothing (feature 339)"
        )
    if value < 1:
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"{field_name} must be at least 1 — got {value}; a half-life is "
            "measured over observed days, and a signal with none is refused "
            "by name as unobserved rather than answered with a figure over "
            "no evidence (feature 339)"
        )
    return value


def _validated_tally(value: Any, field_name: str) -> int:
    """Return ``value`` as an absence tally, or refuse it.

    Whole and at least zero — the tallies count signals the revision could
    not measure, and zero is the honest common case, so unlike the day count
    it is admitted.  ``bool`` refused first, as everywhere: ``True`` is not a
    census of anything.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"{field_name} must be a whole count of signals — got {value!r} "
            f"({type(value).__name__}); the revision's absences are counted "
            "so a planner can see what the figure was not taken over, and a "
            "count that is not a whole number hides exactly that (feature "
            "339)"
        )
    if value < 0:
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"{field_name} must be at least 0 — got {value}; a tally of "
            "signals the revision could not measure cannot be negative "
            "without measuring more signals than the table holds (feature "
            "339)"
        )
    return value


# -- The per-signal answer ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForwardHalfLife:
    """One signal's observed forward half-life — reached, or censored.

    The input noun of feature 339's sentence, answered per signal the way
    feature 337 answers its ratio per signal.  A *frozen* value whose
    ``__post_init__`` re-derives the crossing and compares: the half-life is
    not a figure a caller may state, it is arithmetic over the record's own
    rows, and an instance whose crossing day, offset or mean disagree with
    its own fields is refused rather than carried — the discipline
    :class:`forward.retention.IcRetention` applies to its quotient and
    :class:`forward.reconciliation.ReconciledFillCosts` to its difference.

    **Censoring is a field, not an absence.**  A signal whose prefix
    retention never fell to half within the days observed carries
    ``half_life_days=None`` with the days it *was* observed beside it: the
    honest statement of *greater than*, which is a bound and not a value, and
    which the prior update declines to average in as though it were one.
    """

    #: The signal this half-life is about — ``forward_record.node_id``.
    node_id: str
    #: The boundary day — the opening row's own ``observed_on``, the UTC date
    #: of the promotion instant.  Offsets are measured from it, and it is the
    #: record's own column validated by the record's own validator rather
    #: than restated here.
    boundary_on: Any
    #: How many rows carried a measurement — the evidence the running mean
    #: was taken over, which continues past a crossing rather than stopping
    #: at one.
    observed_days: int
    #: The latest day a coefficient was observed on — the record's own
    #: extent, censored or not.
    observed_through: Any
    #: The backtest coefficient the halves are measured against — read off
    #: the opening row, positive by refusal.
    backtest_ic: float
    #: Days from the boundary to the crossing — the first day the prefix mean
    #: fell to :data:`RETENTION_LINE` of ``backtest_ic`` — or ``None`` for a
    #: signal that has not fallen to half yet.
    half_life_days: int | None
    #: The crossing day itself, or ``None`` when censored.  Must be exactly
    #: ``half_life_days`` after the boundary.
    crossing_on: Any
    #: The prefix mean on the crossing day — the figure that fell to half —
    #: or ``None`` when censored.
    live_ic_at_crossing: float | None

    @property
    def reached(self) -> bool:
        """Whether the signal's retention fell to half within the window.

        The readable name for the state the two ``None``-able fields carry,
        so a caller does not have to spell ``half_life_days is None`` to ask
        the question the answer exists for — the same role
        :attr:`forward.record.ForwardRecord.observed` plays for its NULL
        column.
        """
        return self.half_life_days is not None

    def __post_init__(self) -> None:
        """Validate every field, then re-derive the crossing and compare.

        The field validators run first, in declaration order, so a malformed
        constituent is refused by its own name before the crossing laws are
        attempted.  Then the three laws that are about the *crossing* rather
        than about any one field:

        * **A censored signal carries no crossing figures.**  ``None`` days
          with a dated crossing is a bound wearing a value's clothes, and the
          aggregate would average it in as though the signal had died on the
          day stated.
        * **The crossing day is the offset from the boundary.**  Exactly,
          because both are dates this member read off rows, and a
          disagreement is a crossing nobody dated.
        * **The crossing mean actually falls to half.**  Compared with the
          same expression the store's loop uses, so an instance cannot state
          a crossing its own figures do not produce.
        """
        _validated_uuid(self.node_id, NODE_ID_COLUMN)
        boundary = _validated_date(self.boundary_on, OBSERVED_ON_COLUMN)
        through = _validated_date(self.observed_through, OBSERVED_ON_COLUMN)
        _validated_count(self.observed_days, "observed_days")
        backtest = _validated_backtest_ic(self.backtest_ic)
        if backtest <= 0.0:
            raise _no_edge(self.node_id, backtest)
        if through <= boundary:
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"node {self.node_id}'s half-life is measured over days "
                f"strictly after the boundary {boundary.isoformat()}, but the "
                f"record extends only to {through.isoformat()}. Feature 333 "
                "observes on days after the boundary day by law, so a record "
                "whose latest day is the boundary itself carries no "
                "observation a running mean could be taken over (feature 339)"
            )
        if self.crossing_on is None:
            if self.half_life_days is not None or self.live_ic_at_crossing is not None:
                raise ForwardDecayPriorError(
                    f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                    f"node {self.node_id}'s half-life carries no crossing day "
                    "but states a half-life or a crossing mean anyway "
                    f"({self.half_life_days!r}, {self.live_ic_at_crossing!r}). "
                    "A signal that has not fallen to half is *censored*: its "
                    "half-life is greater than the days observed, which is a "
                    "bound and not a value, and stating crossing figures for "
                    "it would let the prior update average a bound in as "
                    "though the signal had died on a day it did not "
                    "(feature 339)"
                )
            return
        crossing = _validated_date(self.crossing_on, OBSERVED_ON_COLUMN)
        if isinstance(self.half_life_days, bool) or not isinstance(
            self.half_life_days, int
        ):
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"node {self.node_id}'s half_life_days must be a whole number "
                f"of days — got {self.half_life_days!r} "
                f"({type(self.half_life_days).__name__}); the half-life is "
                "dated in days from the boundary the record draws (feature "
                "339)"
            )
        offset = (crossing - boundary).days
        if self.half_life_days < 1 or offset < 1:
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"node {self.node_id}'s half-life must be at least 1 day "
                f"after the boundary — got {self.half_life_days!r} over an "
                f"offset of {offset}. Feature 333 observes only on days "
                "strictly after the boundary day, so a crossing on the "
                "boundary itself is a figure over in-sample data wearing an "
                "out-of-sample vintage (feature 339)"
            )
        if self.half_life_days != offset:
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"node {self.node_id}'s half_life_days {self.half_life_days!r} "
                f"is not the crossing day's offset from the boundary — "
                f"{crossing.isoformat()} is {offset} days after "
                f"{boundary.isoformat()}. The half-life is not a figure a "
                "caller may state: it is the distance between two dates the "
                "record holds, and an instance whose own dates do not "
                "produce it would date the prior's evidence to a day nobody "
                "measured (feature 339)"
            )
        if not boundary < crossing <= through:
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"node {self.node_id}'s crossing day {crossing.isoformat()} "
                f"does not lie strictly after the boundary "
                f"{boundary.isoformat()} and within the record's own extent "
                f"through {through.isoformat()}. The crossing is a day the "
                "record was observed on, so a crossing outside the rows that "
                "carry the observations is a date nobody wrote (feature 339)"
            )
        mean = _validated_live_ic(self.live_ic_at_crossing)
        if not mean <= backtest * RETENTION_LINE:
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"node {self.node_id}'s crossing mean {mean!r} does not fall "
                f"to §11's line — {RETENTION_LINE!r} of the backtest "
                f"{backtest!r} is {backtest * RETENTION_LINE!r}, and the mean "
                "is above it. A half-life is dated on the day the prefix "
                "retention *reaches* half, so an instance whose own mean has "
                "not fallen dates a crossing that did not happen (feature "
                "339)"
            )

    def summary(self) -> dict[str, Any]:
        """The answer as a JSON-shaped mapping, for a router or a job log.

        Dates travel as ISO strings for the reason every timestamp in this
        member does — :mod:`json` has no ``date`` — and the censored state
        travels as an explicit ``null`` with ``reached`` beside it, so a
        reader of the mapping can tell *not yet* from *never measured*, which
        the ``None`` alone already states but the boolean makes greppable.
        """
        return {
            NODE_ID_COLUMN: self.node_id,
            "boundary_on": self.boundary_on.isoformat(),
            "observed_days": self.observed_days,
            "observed_through": self.observed_through.isoformat(),
            BACKTEST_IC_COLUMN: self.backtest_ic,
            "half_life_days": self.half_life_days,
            "crossing_on": (
                None if self.crossing_on is None else self.crossing_on.isoformat()
            ),
            "live_ic_at_crossing": self.live_ic_at_crossing,
            "reached": self.reached,
        }


# -- The revision -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecayPriorRevision:
    """The revised decay prior — the figure, its evidence, and its absences.

    The answer of :meth:`ForwardDecayPriors.revise`, and the value the risk
    register's *feed half-life into ``plan_grid``* is answered by: the
    planning input is the mapping (:meth:`summary`), and this value is the
    contract behind it — frozen, self-derived, and refusing any instance
    whose revised figure is not the blend of its own evidence.

    The two prior fields are the member's own constants, enforced by
    equality (:func:`_validated_constant`): they are not dials.  What varies
    is the evidence, and the three tallies beside it state what the figure
    was *not* taken over — the visible-absence discipline that keeps a
    revision over a heterogeneous fleet honest about the fleet it read.
    """

    #: The standing prior — :data:`PRIOR_HALF_LIFE_DAYS`, the prd's own
    #: 90-day horizon.  Enforced equal to the constant.
    prior_half_life_days: float
    #: The prior's pseudo-count — :data:`PRIOR_WEIGHT`.  Enforced equal to
    #: the constant.
    prior_weight: float
    #: Every signal the revision measured, ascending by node — reached
    #: half-lives and censored bounds together, each carrying its own
    #: evidence.  The measured fleet is carried whole so the figure can be
    #: audited against the rows it came from rather than trusted.
    signals: tuple[ForwardHalfLife, ...]
    #: Signals whose ``backtest_ic`` has not landed — feature 337's writer is
    #: a separate call, and a young deployment's outer loop must not block on
    #: the figures that have not arrived.
    unbacktested: int
    #: Signals with a divisor and no observed days — the observation job has
    #: not reached them.
    unobserved: int
    #: Signals whose backtest is exactly zero — the honest figure of a signal
    #: with no measured edge, which has no halving to date.
    zero_backtest: int
    #: The latest day any row in the table carried a measurement — the
    #: vintage of the revision, read off the data rather than the clock.
    #: ``None`` only when no row anywhere carries one.
    observed_through: Any
    #: The revised prior — the blend of the constants with the observed
    #: half-lives.  Re-derived in ``__post_init__`` and compared exactly.
    revised_half_life_days: float

    @property
    def observed_half_lives(self) -> int:
        """How many signals reached their half-life — the blend's ``n``.

        Derived, never a field, for the reason feature 294's count is
        derived and not incremented: the evidence is carried whole in
        ``signals``, and a tally kept beside it is a second copy of one fact
        that can drift from the first.
        """
        return sum(1 for signal in self.signals if signal.reached)

    @property
    def censored_signals(self) -> int:
        """How many measured signals have not fallen to half yet.

        Derived, like :attr:`observed_half_lives`: the censored signals are
        the rest of ``signals``, and the count a planner reads beside the
        figure is the same fact restated, not a second one.
        """
        return sum(1 for signal in self.signals if not signal.reached)

    @property
    def half_lives(self) -> tuple[int, ...]:
        """The observed half-lives themselves, in node order.

        The values the blend summed, carried out of ``signals`` so a reader
        of the revision holds the addends as well as the figure — the same
        reason :class:`~forward.retention.IcRetention` carries its day count
        beside its mean.
        """
        return tuple(
            signal.half_life_days for signal in self.signals if signal.reached
        )

    def __post_init__(self) -> None:
        """Validate every field, then re-derive the blend and compare.

        The prior is the member's own (:func:`_validated_constant`), the
        tallies are whole and non-negative, the evidence is ascending by node
        and unique — the deterministic read the store's ``ORDER BY`` buys —
        and the vintage is consistent with the evidence it summarises.  Then
        the one law that is about the *figure*: the revised half-life must
        equal the blend of the prior with its own evidence, exactly, because
        both sides are arithmetic this member performed over figures it read.
        """
        prior = _validated_constant(
            self.prior_half_life_days, PRIOR_HALF_LIFE_DAYS, "prior_half_life_days"
        )
        weight = _validated_constant(self.prior_weight, PRIOR_WEIGHT, "prior_weight")
        _validated_tally(self.unbacktested, "unbacktested")
        _validated_tally(self.unobserved, "unobserved")
        _validated_tally(self.zero_backtest, "zero_backtest")
        for signal in self.signals:
            if not isinstance(signal, ForwardHalfLife):
                raise ForwardDecayPriorError(
                    f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                    "the revision's evidence must be ForwardHalfLife values — "
                    f"got {signal!r} ({type(signal).__name__}); each entry is "
                    "one signal's half-life with its own derivation laws, and "
                    "a value that is not one brings no laws with it (feature "
                    "339)"
                )
        order = [signal.node_id for signal in self.signals]
        if order != sorted(set(order)):
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                "the revision's evidence must name each signal once, "
                f"ascending — got {order}. The store reads the table ordered "
                "by node, so a revision whose evidence is out of order or "
                "names a signal twice is not the reading any store made, and "
                "two revisions of one table would not be comparable entry "
                "for entry (feature 339)"
            )
        if self.signals:
            through = _validated_date(self.observed_through, OBSERVED_ON_COLUMN)
            latest = max(signal.observed_through for signal in self.signals)
            if through < latest:
                raise ForwardDecayPriorError(
                    f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                    f"the revision's vintage {through.isoformat()} precedes "
                    f"the latest day its own evidence reaches "
                    f"({latest.isoformat()}). The vintage is read off the "
                    "table, and a revision dated before the rows it carries "
                    "would state a track record that had not happened yet "
                    "(feature 339)"
                )
        elif self.observed_through is not None:
            _validated_date(self.observed_through, OBSERVED_ON_COLUMN)
        reached = [
            signal.half_life_days for signal in self.signals if signal.reached
        ]
        blended = (prior * weight + sum(reached)) / (weight + len(reached))
        if isinstance(self.revised_half_life_days, bool) or not isinstance(
            self.revised_half_life_days, Real
        ):
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"{REVISED_HALF_LIFE_KEY} must be a real number — got "
                f"{self.revised_half_life_days!r} "
                f"({type(self.revised_half_life_days).__name__}); it is the "
                "input campaign planning feeds to ``plan_grid`` (prd's risk "
                "register), and a value that is not one number is not a "
                "timescale (feature 339)"
            )
        stated = float(self.revised_half_life_days)
        if not math.isfinite(stated):
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"{REVISED_HALF_LIFE_KEY} must be finite — got {stated!r}; "
                "the blend divides a bounded sum of day counts by a positive "
                "weight, so an infinity or a NaN here is a figure that did "
                "not come from the evidence it travels with (feature 339)"
            )
        if stated != blended:
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"the revised half-life {stated!r} is not the blend of the "
                f"prior ({prior!r} days at weight {weight!r}) with the "
                f"{len(reached)} observed half-lives "
                f"({tuple(reached)!r}), which is {blended!r}. The revision "
                "is not a figure a caller may state: prd §13.4's "
                "recalibration is the observed half-lives folded into the "
                "prior, and an instance whose own evidence does not produce "
                "its figure would hand campaign planning a decay timescale "
                "nobody computed. Nothing is wrong with the store: the "
                "repair is to let this feature take the blend (feature 339)"
            )

    def summary(self) -> dict[str, Any]:
        """The revised inputs as a JSON-shaped mapping — the planner's read.

        The keys are the figures the risk register names (*half-life*, fed
        into ``plan_grid``) beside the evidence and absences that qualify
        them, because a planning input without its evidence is a number a
        campaign cannot audit itself against.  The half-lives travel as their
        values in node order and the vintage as an ISO string, the same
        rendering discipline :meth:`forward.retention.IcRetention.summary`
        applies to its own answer.
        """
        return {
            "prior_half_life_days": self.prior_half_life_days,
            "prior_weight": self.prior_weight,
            REVISED_HALF_LIFE_KEY: self.revised_half_life_days,
            "observed_half_lives": self.observed_half_lives,
            "half_lives": list(self.half_lives),
            "measured_signals": len(self.signals),
            "censored_signals": self.censored_signals,
            "unbacktested_signals": self.unbacktested,
            "unobserved_signals": self.unobserved,
            "zero_backtest_signals": self.zero_backtest,
            "observed_through": (
                None
                if self.observed_through is None
                else self.observed_through.isoformat()
            ),
        }


# -- The store --------------------------------------------------------------------


class ForwardDecayPriors:
    """Feature 339's store: the half-lives, and the prior revised from them.

    Two acts over one table and no write of its own.  :meth:`half_life`
    answers one signal's observed forward half-life — the per-signal
    spelling, which refuses the absences the aggregate carries; and
    :meth:`revise` reads the whole table and answers the revised decay prior
    with its evidence — the feature's act.  Both work through
    :data:`forward.record._READ_SQL` — one reading of ``forward_record``
    across features 332, 333, 337, 340 and this one, so the rows the
    half-lives date their crossings on and the rows every other act answered
    with cannot be two readings of one table.

    Constructed over a URL, or over a composed store through :meth:`over`,
    the ladder features 333, 340 and 337 all climb: the classmethod reads
    the ``database_url`` off whatever the component is, the store methods do
    the work, and the module-level spellings resolve ``DATABASE_URL``.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the half-lives are read from.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one signal — the same place
        :class:`forward.retention.ForwardIcRetentions` refuses its own, and
        for the same reason: a URL that is not a non-empty string names no
        table, and a store that accepted one would fail identically on every
        call, which is the wrong place for a deployment to discover a wiring
        fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"{DATABASE_URL_ENV} must be a non-empty database URL. The "
                "decay prior is revised from the half-lives the forward "
                "records' own rows date, so a store pointed at nothing has "
                "nowhere to read a half-life from (feature 339)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> ForwardDecayPriors | None:
        """The prior store ``DATABASE_URL`` names, or ``None``.

        An empty or whitespace-only value counts as unset, the way every
        store in this workspace treats its configuration — and deliberately
        the same spelling :meth:`forward.retention.ForwardIcRetentions.
        resolve` answers with: a deployment with no relational store holds
        no prior reader, which is a discoverable state rather than an
        exception, while the module-level spelling below refuses instead
        because a revision that silently answered the untouched prior would
        look exactly like a revision that ran.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def over(cls, records: Any) -> ForwardDecayPriors:
        """The prior store over a composed forward-record store.

        The bridge from the seat to these acts: a caller holding the
        composed ``forward`` component asks this one question and holds the
        reader for the same database the component points at — one URL, one
        table, five acts.  The one thing read is the store's
        ``database_url``; there is no ``isinstance`` to defeat, because the
        loader imports a member under a synthetic name and an identity check
        would refuse the very value composition produces.
        """
        url = getattr(records, FORWARD_PRIOR_SEAM, None)
        if not isinstance(url, str) or not url.strip():
            raise TypeError(
                "ForwardDecayPriors is built over a forward-record store — "
                f"something exposing a {FORWARD_PRIOR_SEAM!r} string (the "
                "composed 'forward' component, or a ForwardRecords); "
                f"got {type(records).__name__}, which names no database. "
                "The half-lives are dated on the forward record's own rows, "
                "so the reader shares one URL with the record by "
                "construction (feature 339)"
            )
        return cls(url)

    @property
    def database_url(self) -> str:
        """The database URL this store reads."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the records, resolved on first use.

        Nothing is created at construction — the URL is translated the first
        time an operation needs it, by the member's one spelling of that
        translation (:func:`forward.record._sqlite_path`), so a URL this
        member cannot speak is refused in the member's one vocabulary
        whichever store translated it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the records' database, bringing the two tables it names up.

        The same statement of intent every store in this member makes, over
        the same two owners: :func:`forward.schema.bootstrap_schema` runs the
        owning migrations' own ``statements("sqlite")`` — ``0118`` for
        ``node`` and ``0108`` for ``forward_record`` — so this store authors
        no DDL, spells no column and cannot drift from the schema's owner.
        This feature adds **no table and no column**: the half-life is dated
        on rows features 332, 333 and 337 already write, and the revision is
        derived from them, so the act here is a pair of ``SELECT`` s and
        nothing else.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — SQLite's own
        default is off, and the pragma is what makes the row's reference
        hold against a hand that reaches past this store with a raw
        connection.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_schema(connection)
        except ForwardError:
            # The schema adapter's own refusals arrive in this member's
            # vocabulary already — re-raised untouched (and the connection
            # closed) rather than re-framed, for the reason
            # :meth:`forward.record.ForwardRecords._connect` states.
            connection.close()
            raise
        except sqlite3.Error as exc:
            connection.close()
            raise ForwardDecayPriorError(
                f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
                f"{FORWARD_RECORD_TABLE} could not be brought to the "
                f"revision a decay prior needs at {path}: {exc}. The table "
                "is created by "
                "migrations/versions/0108_forward_and_universe_tables.py and "
                "its parent by 0118_node_table.py; this store runs those "
                "files' own statements and authors none of its own "
                "(feature 339)"
            ) from exc
        return connection

    def _rows(
        self, connection: sqlite3.Connection, node: str
    ) -> list[ForwardRecord]:
        """The signal's standing rows, oldest day first — the record itself.

        Feature 332's own read spelling — :data:`forward.record._READ_SQL`
        and :func:`forward.record._record_from_row` — used rather than
        restated, so the rows this act dates crossings on and the rows every
        other act in the member answered with cannot be two readings of one
        table.  A validation refusal off a row is the record contract's own
        (:class:`~forward.errors.ForwardRecordError`) and propagates as
        itself, because it names the row it came off and re-framing it would
        only push a second wording in front of the one an operator needs.
        """
        cursor = connection.execute(_READ_SQL, (node,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return [_record_from_row(row, node) for row in rows]

    # -- Feature 339: the half-life, and the revision -----------------------

    def half_life(self, node_id: Any) -> ForwardHalfLife:
        """Answer one signal's observed forward half-life.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity, before anything is
           opened, so a malformed identity is refused without touching a
           database and a refused call leaves no file behind.
        2. **Read the signal's standing rows.**  No rows is a refusal by
           name (:func:`_absent_record`) — a half-life is dated on a record,
           exactly as an observation and a ratio are.
        3. **Refuse the two-vintages fault** (:func:`_one_vintage`) — rows
           disagreeing about the boundary cannot date an offset from it.
        4. **Refuse the unobserved record** (:func:`_no_observation`) — a
           running mean over no days is not a mean, and answering a
           half-life off it would be answering about a track record that has
           not begun.
        5. **Read the backtest off the opening row**, refusing its absence
           (:func:`_no_backtest`) and its non-positivity (:func:`_no_edge`)
           by name — the per-signal spelling refuses what the aggregate
           counts, because this caller asked about *this* signal and the
           repair is one call away.
        6. **Walk the prefix means** and date the crossing — or carry the
           censoring.

        **The crossing is the first prefix mean at or below half.**  Each
        observed row extends the mean one day at a time, in
        :data:`forward.record._READ_SQL`'s own day order, and the first mean
        at or below :data:`RETENTION_LINE` of the backtest dates the
        half-life.  At-or-below rather than strictly-below because §11's
        criterion is *"> 0.5"*: retention of exactly half is the criterion
        failing, not holding.
        """
        node = _validated_uuid(node_id, NODE_ID_COLUMN)
        with closing(self._connect()) as connection:
            standing = self._rows(connection, node)
        if not standing:
            raise _absent_record(node)
        opening = _one_vintage(node, standing)
        observed = [row for row in standing if row.live_ic is not None]
        if not observed:
            raise _no_observation(node, opening)
        stored = opening.backtest_ic
        if stored is None:
            raise _no_backtest(node, opening)
        backtest = _validated_backtest_ic(stored)
        if backtest <= 0.0:
            raise _no_edge(node, backtest)
        return _measured(node, opening, observed, backtest)

    def revise(self) -> DecayPriorRevision:
        """Revise the decay prior from every observed forward half-life.

        The feature's act.  One connection, one snapshot: every signal the
        table holds is read, classified and folded in order, so the revision
        of a table is a pure function of the table — two calls over unmoved
        rows answer equal values, and no memo is kept because the rows
        already are one.

        **The classification, and its precedence.**  The divisor is checked
        before the observations, because a signal with no divisor cannot be
        measured however many rows it holds: a signal whose ``backtest_ic``
        has not landed is *unbacktested*; one whose stored figure fails
        feature 337's coefficient gate refuses the whole revision in that
        gate's own vocabulary; one whose figure is exactly zero is
        *zero-backtest* (an honest measurement of no edge — nothing to
        halve); one whose figure is negative **refuses** (a promoted signal
        carries a positive edge, and the halving of a negative coefficient
        is not a threshold anyone defined); and only a signal with a
        positive divisor and no observed days is *unobserved*.  Measured
        signals — reached or censored — become the evidence.

        **The blend.**  :class:`DecayPriorRevision` holds the arithmetic:
        the prior's pseudo-count fold over the reached half-lives, with zero
        observations answering the prior exactly.  The censored bounds are
        counted and not averaged — see the class's docstring for the
        fabrication that averaging a bound would be.
        """
        signals: list[ForwardHalfLife] = []
        unbacktested = 0
        unobserved = 0
        zero_backtest = 0
        through: date | None = None
        with closing(self._connect()) as connection:
            cursor = connection.execute(_NODES_SQL)
            try:
                nodes = [row[0] for row in cursor.fetchall()]
            finally:
                cursor.close()
            for node in nodes:
                standing = self._rows(connection, node)
                opening = _one_vintage(node, standing)
                measured_days = [
                    row.observed_on for row in standing if row.live_ic is not None
                ]
                if measured_days:
                    latest = max(measured_days)
                    if through is None or latest > through:
                        through = latest
                stored = opening.backtest_ic
                if stored is None:
                    unbacktested += 1
                    continue
                backtest = _validated_backtest_ic(stored)
                if backtest == 0.0:
                    zero_backtest += 1
                    continue
                if backtest < 0.0:
                    raise _no_edge(node, backtest)
                observed = [row for row in standing if row.live_ic is not None]
                if not observed:
                    unobserved += 1
                    continue
                signals.append(_measured(node, opening, observed, backtest))
        reached = [signal.half_life_days for signal in signals if signal.reached]
        blended = (PRIOR_HALF_LIFE_DAYS * PRIOR_WEIGHT + sum(reached)) / (
            PRIOR_WEIGHT + len(reached)
        )
        return DecayPriorRevision(
            prior_half_life_days=PRIOR_HALF_LIFE_DAYS,
            prior_weight=PRIOR_WEIGHT,
            signals=tuple(signals),
            unbacktested=unbacktested,
            unobserved=unobserved,
            zero_backtest=zero_backtest,
            observed_through=through,
            revised_half_life_days=blended,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- The crossing -----------------------------------------------------------------


def _measured(
    node: str,
    opening: ForwardRecord,
    observed: list[ForwardRecord],
    backtest: float,
) -> ForwardHalfLife:
    """Walk one signal's prefix means and date its crossing — or its censoring.

    The one loop this feature is: the running mean of the observed rows'
    ``live_ic`` figures — feature 337's own statistic, computed on prefixes —
    extended one observed day at a time, in the record's own day order, and
    stopped at the first mean at or below :data:`RETENTION_LINE` of the
    backtest.  The caller has already refused the states a loop cannot run
    over (no rows, no observations, no divisor, a non-positive divisor), so
    what remains is arithmetic.

    ``observed_days`` and ``observed_through`` carry the record's *whole*
    extent and not the crossing's, because the evidence for a half-life
    includes the days that followed it — a signal crossed on day 3 and
    observed through day 40 is a half-life of 3 with 40 days behind it, and
    collapsing the two would read every signal as dying the day it was
    measured dying.
    """
    boundary = opening.observed_on
    total = 0.0
    crossing: ForwardRecord | None = None
    crossing_mean: float | None = None
    for count, row in enumerate(observed, start=1):
        total += float(row.live_ic)
        mean = total / count
        if mean <= backtest * RETENTION_LINE:
            crossing = row
            crossing_mean = mean
            break
    if crossing is None:
        return ForwardHalfLife(
            node_id=node,
            boundary_on=boundary,
            observed_days=len(observed),
            observed_through=observed[-1].observed_on,
            backtest_ic=backtest,
            half_life_days=None,
            crossing_on=None,
            live_ic_at_crossing=None,
        )
    return ForwardHalfLife(
        node_id=node,
        boundary_on=boundary,
        observed_days=len(observed),
        observed_through=observed[-1].observed_on,
        backtest_ic=backtest,
        half_life_days=(crossing.observed_on - boundary).days,
        crossing_on=crossing.observed_on,
        live_ic_at_crossing=crossing_mean,
    )


# -- The private refusals ---------------------------------------------------------


def _one_vintage(node: str, standing: list[ForwardRecord]) -> ForwardRecord:
    """The record's opening row, after checking the record is one record.

    The one-vintage law read back, in this module's own vocabulary — the
    same check :meth:`forward.observation.ForwardObservations._one_vintage`
    and :func:`forward.retention._one_vintage` make in theirs, restated here
    because each module refuses in its own words and a half-life dated from
    two boundaries is a half-life nobody can state.  The opening row is
    ``standing[0]`` because :data:`forward.record._READ_SQL` orders by
    ``observed_on``, which is a property of the ordering clause and not of
    any object.
    """
    instants = {row.promoted_at for row in standing}
    if len(instants) > 1:
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"the {FORWARD_RECORD_TABLE} rows for node {node} carry "
            f"{len(instants)} different promoted_at values — "
            + ", ".join(sorted(t.isoformat() for t in instants))
            + ". A forward record is one vintage: feature 332 opens one row "
            "per signal carrying one instant, and every observation carries "
            "that same instant, so rows disagreeing about it are a hand that "
            "reached past this store. A half-life measured over them would "
            "date a decay from two different boundaries, and the prior it "
            "fed would move campaign planning on a timescale nobody "
            "measured — repair the rows, then revise (feature 339)"
        )
    return standing[0]


def _absent_record(node: str) -> ForwardDecayPriorError:
    """The absence refusal: no record, so no boundary to measure from.

    A half-life is an offset in days from the boundary feature 332's opening
    row draws, and a signal with no record has no boundary — opening one
    silently to measure from would fabricate the very thing the record
    exists to fix.  The repair is the pipeline's, in the order the loop
    runs: promote first, then the record opens.
    """
    return ForwardDecayPriorError(
        f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
        f"{FORWARD_RECORD_TABLE} holds no row for {NODE_ID_COLUMN} {node}, "
        "so there is no boundary a half-life could be measured from. The "
        "half-life is dated in days from the promotion day the opening row "
        "carries, and a signal with no record has no promotion day on the "
        "table — whether or not its promotion was decided. Open the record "
        "first (POST /forward/promote, feature 332), then observe it "
        "(feature 333), then ask for its half-life (feature 339)"
    )


def _no_observation(node: str, opening: ForwardRecord) -> ForwardDecayPriorError:
    """The unobserved refusal: a record with nothing measured on it yet.

    Answered rather than zeroed or infinity'd.  A half-life of zero days
    would read as a signal that died on its promotion day — measured, and
    instantly dead — while this record has not been measured at all, and
    the two must not read alike in front of a prior that moves campaign
    planning.  The repair is feature 333's act, on schedule.
    """
    return ForwardDecayPriorError(
        f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
        f"node {node}'s forward record (promoted at "
        f"{opening.promoted_at.isoformat()}, day "
        f"{opening.observed_on.isoformat()}) holds no row carrying a "
        "live_ic, so there is no prefix for the running mean a half-life is "
        "dated on. A half-life of zero would mean the signal was measured "
        "and died on the spot, while this record has not been measured at "
        "all, and answering it would tighten the decay prior on the "
        "strength of a job that has not run. Nothing is wrong with the "
        "store: the repair is to observe the signal on days the window is "
        "open (feature 333), which is what a half-life is counted over "
        "(feature 339)"
    )


def _no_backtest(node: str, opening: ForwardRecord) -> ForwardDecayPriorError:
    """The unfilled-divisor refusal: no backtest IC landed yet.

    The half of §11's line is half *of the backtest figure*, so a record
    whose ``backtest_ic`` is still NULL has no line to fall to.  The null is
    a state by ``0108``'s own shape — feature 332 opens the record knowing
    nothing about the backtest, feature 337 fills the column — and it is
    named as one.  The repair is feature 337's writer, and it is one call.
    """
    return ForwardDecayPriorError(
        f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
        f"node {node}'s forward record was opened at "
        f"{opening.promoted_at.isoformat()} carrying no "
        f"{BACKTEST_IC_COLUMN}, so there is no edge for a half-life to be "
        "half of. The column is nullable because feature 332 opens the "
        "record and feature 337 fills it, so its absence is a state rather "
        "than a fault: no backtest figure has been recorded for this signal "
        "yet, and neither inventing one nor reading the live IC as its own "
        "baseline would date anything a signal actually did. Nothing is "
        "wrong with the store: the repair is to record the coefficient the "
        "evaluation member measured on the in-sample window "
        "(ForwardIcRetentions.record_backtest_ic, prd §6.1's "
        "metrics.ic_mean, feature 337)"
    )


def _no_edge(node: str, backtest: float) -> ForwardDecayPriorError:
    """The no-edge refusal: a backtest IC that states no positive edge.

    One refusal for two figures, because the fault is the same: a half-life
    is the day the live edge falls to **half** of the backtest edge, and a
    backtest of zero or below states no positive edge whose halving could be
    dated.  A zero is the honest figure of a signal with no measured edge —
    feature 337 stores it and refuses to divide by it, and this module
    agrees with both halves: the aggregate counts the signal, the
    per-signal ask refuses it.  A *negative* figure is worse than honest
    emptiness: promotion requires a positive edge (prd §11's criteria), so a
    negative coefficient on a promoted signal's record is a figure wearing
    the column's name, and no decay threshold anyone defined is the half of
    it.  The repair is offline reconciliation of the figure, not a
    convention here.
    """
    return ForwardDecayPriorError(
        f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
        f"node {node}'s forward record carries a backtest information "
        f"coefficient of {backtest!r}, and a half-life is the day the live "
        "edge falls to half of a *positive* backtest edge — §11's line is "
        "drawn at half of a figure that states one. A zero is the honest "
        "figure of a signal with no measured edge (feature 337 stores it "
        "and refuses the division; the aggregate counts it and moves on), "
        "but no decay can be dated against either. A negative figure is not "
        "honest emptiness: promotion requires a positive edge, so the row "
        "contradicts the promotion that opened it. Nothing is wrong with "
        "the store: the repair is to reconcile the figure offline, then "
        "revise (feature 339)"
    )


# -- The module-level spellings ---------------------------------------------------


def _resolved_store(
    database_url: str | None, env: Mapping[str, str] | None
) -> ForwardDecayPriors:
    """The store the module-level spellings read through, or a refusal.

    An explicit URL wins, else ``DATABASE_URL``, and a deployment that names
    neither is refused *by name* rather than silently answering the prior —
    the dangerous failure here is specific: a revision that ran is
    indistinguishable in shape from the zero-evidence answer, because both
    carry 90 days, so the refusal is what tells them apart.  A caller that
    wants the untouched prior asks for it over a database it names.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url or not str(url).strip():
        raise ForwardDecayPriorError(
            f"{FORWARD_DECAY_PRIOR_ERROR_CODE}: "
            f"no database is named — {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so no decay prior can be revised. "
            "The half-lives are dated on the forward records' own rows, and "
            "the zero-evidence answer this feature would otherwise return "
            "is indistinguishable from a revision that read an empty table "
            "— the refusal is what keeps them apart (feature 339)"
        )
    return ForwardDecayPriors(url)


def forward_half_life(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ForwardHalfLife:
    """Answer one signal's observed forward half-life — the module-level
    spelling.

    The per-signal half of the feature's sentence as one call, for the
    caller that wants the figure without holding a store — the risk
    register's *feed half-life into ``plan_grid``* run per signal, a
    dashboard, a test.  The store is resolved from ``database_url``, else
    from ``DATABASE_URL``, exactly as :func:`forward.retention.
    forward_ic_retention` resolves its own, so a caller reading through one
    spelling and the other is reading the same database.
    """
    return _resolved_store(database_url, env).half_life(node_id)


def revised_decay_prior(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> DecayPriorRevision:
    """Revise the decay prior — the module-level spelling of the feature's act.

    The whole sentence as one call: the observed forward half-lives of every
    signal the named database holds, folded into the 90-day prior at
    :data:`PRIOR_WEIGHT`, answered with the evidence and the absences beside
    it.  **No figure is a parameter**, and that is the feature: the
    half-lives are read from the rows features 333 and 337 wrote, the prior
    is the member's own, and the blend is :class:`DecayPriorRevision`'s to
    perform and verify — a caller cannot hand this call a decay timescale it
    did not compute, exactly as a caller cannot hand feature 337 a ratio.
    """
    return _resolved_store(database_url, env).revise()
