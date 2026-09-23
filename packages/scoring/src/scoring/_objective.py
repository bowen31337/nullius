"""Feature 256, the per-world objective — the scalar a replayed policy earns
in one world, starting from the out-of-sample information ratio of its
committed pick.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 256: *System
computes the per-world objective starting from out-of-sample information
ratio of the committed pick, which returns a scalar world score.*  The
formula is prd §7.1's (line 318) and docs/nullius-tech-architecture.md
§10.3's (line 495), the same sentence twice:

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged              # … and five more terms (§7.1)

This module owns the **head** of that formula and nothing below it: the
leading term ``IR_oos(π^m.commit() | book_t)``, and the scalar it starts.
The six adjustments the formula continues with — β₁'s trials, β₂'s null
pick rate, β₃'s deflation, β₄'s IC divergence, β₅'s switches, β₆'s
orthogonality — are features 257 through 262 of the same category, each
subtracting or adding through :meth:`WorldScore.adjusted`, the one seam
this module ships for them.  *"Starting from"* is therefore the feature's
own statement of shape, not a hedge: at 256 the objective **is** its
leading term, :attr:`WorldScore.score` is born equal to
:attr:`WorldScore.ir_oos`, and every later feature moves the scalar
without ever touching the measurement it started from.

**Out-of-sample is a property of the panel, and the seam demands it in the
caller's discipline.**  prd §7.1's Change A is the reason the objective
reads the way it does: during replay the policy *"sees only in-sample
metrics and diagnostics"*, and at termination *"it is scored on a
sequestered epoch it has never observed in any world"*.  Nothing in the
arithmetic can see that boundary — a mean and a standard deviation cannot
tell a sequestered date from an in-sample one — so this module does not
pretend to check it.  What it does is refuse everything that would let an
uncheckable reading pass silently: the panel must be one finite real
reading per date, at least two dates, and a series that actually varied.
Which dates those are is the replay engine's sequestration decision
(docs §10.1's ``epoch`` argument to ``score(...)`` stands where the caller
stands), and a scorer that re-derived the split would be a second place
the barrier could leak.  The ``epoch_id`` the caller may name is carried
into the record unchanged for exactly that reason: the score is only
legible relative to the epoch it was measured on, and a caller that knows
its epoch states it rather than leaving the row to say.

**One spelling of the information ratio.**  The ratio is the mean of the
per-date readings over their **population** standard deviation
(``ddof=0``: the sequestered epoch is the whole sample the pick was
measured over, not a draw from a larger super-population), summed with
:func:`math.fsum` so the answer is exact regardless of the panel's
iteration order, over dates sorted before they are read.  That is feature
80's spelling — the one the evaluator pinned for ``ir_standalone`` and
restated for ``ir_marginal`` — restated here word for word rather than
imported, because a workspace member never imports another workspace
member (the two members share a formula the way they share a node model:
by restating the small thing, not by reaching across the boundary).  One
spelling everywhere is the point: a world score whose leading term was
measured on a different axis than the node metrics the policy read
in-sample would be a comparison across two rulers, and prd §7.1's whole
Change A is that the out-of-sample axis must be the *same* axis the
in-sample diagnostics spoke, or the selection bias the change exists to
kill comes straight back.

**The pick arrives by its address, through a duck-typed seam.**  Two
spellings are accepted, and both name one node: a bare non-empty string
(the address itself), or an object exposing a ``node_id`` attribute —
which is feature 222's :class:`~policy_runtime.CommittedPick`, the value
a :meth:`~policy_runtime.EpisodeCommit.terminate` read hands the runtime.
The seam is duck-typed rather than an ``isinstance`` because the module
loader imports this member under a synthetic name and re-executes it, so
a pick this process composed may be a second ``CommittedPick`` class
object and a type check would refuse the very objects composition
produces — the same stance the commit record itself takes toward the
question it fronts.  The pick is an *address* here, exactly as 222 froze
it: not the node's in-sample observation (the score is out-of-sample by
construction, so a reading beside the pick would be a number the barrier
froze), not the reveal set, not the round — the one field the store's
``replay_score.committed_pick`` column persists (migration 0109).

**−∞ is not this member's number.**  A policy that terminated without
committing *scores* ``−∞`` — that is feature 222's law, spelled once at
:data:`policy_runtime.NON_COMMITTING_SCORE` and answered by the
termination, which routes a scorer only when a pick exists
(``Termination.score`` never calls the scorer pickless).  So this
arithmetic never sees a pickless ask, and a :class:`WorldScore` always
names a pick and is always finite: refused at construction are NaN and
both infinities, for the reasons the commit module states for the miss —
a null score is not a score ("a row in this table is the record of a
completed scoring", migration 0109), and a NaN compares false against
everything, silently dropping out of the dreaming loop's argmax (prd
§C5).  A world score carrying ``−∞`` would be worse than redundant: it
would be the *miss* wearing a pick, a decision that was never made
recorded as one that was — the exact shape migration 0109's nullable
``committed_pick`` exists to keep distinguishable.

**The book is a later term, not a silent rescaling.**  prd §318's
``| book_t`` conditions the pick's reading on the book the policy
committed beside, and §6.2's closed form for book-context measurement
(``ir_marginal``) is the evaluator's, already stored on the node record.
What crosses *this* seam is the committed pick's out-of-sample panel as
the world measured it; the book's explicit contribution to the objective
is β₆'s orthogonality bonus (feature 262), which arrives as its own term
through :meth:`WorldScore.adjusted` — visible, signed, and arguable —
rather than as a hidden reweighting folded into the leading term before
anyone can see it.  A leading term that quietly netted the book would
make β₆ double-count and make every comparison of two picks in different
books unauditable.

**What this law deliberately does not do.**  It does not *aggregate* —
``V^m`` over worlds is regime-stratified CVaR (prd §7.2, docs §10.3,
feature 263), a different feature with a different refusal profile, and a
mean over worlds computed here would be the plain-mean aggregation
feature 264 exists to reject.  It does not *persist* — the
``replay_score`` row is the replay plugin's (feature 255), written from
this value exactly as migration 0109 shapes it.  It does not *calibrate*
— the null pick rate, sensitivity, specificity and ``FDR_deploy`` are
features 265 through 269, and they belong to a scorer process holding the
sidecar key.  And it does not *deflate* — whether the leading term means
anything under multiple testing is β₃'s question (feature 259, prd §7.3),
which is why a series that varies by a float epsilon still gets its
(huge, honest) ratio here rather than a haircut this module invented.

Stdlib only, and import-cheap: :mod:`datetime`, :mod:`math`,
:mod:`numbers`, :mod:`collections.abc`, :mod:`dataclasses` and the
member's own error — no third-party import at module scope, so the
factory's scan (which imports this package to fire its ``@register``
builder) pays nothing for the law.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from numbers import Real

from .errors import WorldObjectiveError

__all__ = [
    "IR_DATES_MINIMUM",
    "WorldScore",
    "world_objective",
]

#: The fewest sequestered dates an information ratio is defined over.  A
#: ratio is a mean over a standard deviation, and a standard deviation over
#: a single date is zero — dividing by it would fabricate an infinity that
#: ranks above every honest score, the same refusal the evaluator's own IR
#: makes (feature 80's spelling, restated) and for the same reason: refuse
#: rather than divide by a number that is not one.
IR_DATES_MINIMUM: int = 2


@dataclass(frozen=True)
class WorldScore:
    """The objective's answer for one world — the scalar, and the term it
    started from.

    A frozen value, because a score that could move after it was read
    would be a ranking that changed beneath the dreaming loop's argmax —
    the same guarantee :class:`~policy_runtime.CommittedPick` makes for
    the decision and :class:`~evaluator.MarginalIR` makes for the
    measurement.  The two numbers a caller must not conflate are both
    carried, and their split is the feature's own shape:

    * :attr:`ir_oos` — the **measurement**: the committed pick's
      out-of-sample information ratio over the sequestered epoch.  Frozen
      for the life of the value, because a measurement is not re-decided
      by a penalty; every later β-term reads it and none moves it.
    * :attr:`score` — the **objective**: the scalar world score, born
      equal to :attr:`ir_oos` (feature 256's *"starting from"*) and moved
      only by :meth:`adjusted` as features 257 through 262 land their
      terms.  This is the number ``V_i^m`` names, the one the aggregated
      objective (feature 263) blends across worlds and the one the
      ``replay_score`` row persists.

    Beside them, the identity of the act that earned the score:
    :attr:`world_id` (which world of the pool the replay ran),
    :attr:`node_id` (the committed pick's address — one node, named once,
    the field migration 0109's ``committed_pick`` column persists) and
    :attr:`epoch_id` (the sequestered epoch the panel was drawn from,
    ``None`` when the caller that sliced the panel did not name it — the
    score is still the same number, and the record is the poorer field,
    not the wrong score).

    Both scalars are finite by construction — NaN and both infinities are
    refused, with the miss's ``−∞`` named as feature 222's and never this
    value's (see the module docstring).  ``int`` readings are accepted and
    narrowed to ``float``, because a caller whose panel is whole numbers
    has measured the same fact a fractional panel has.
    """

    #: The world the score was earned in — one row of the replay pool
    #: (a campaign id or a bootstrap world id), so the aggregated objective
    #: can stratify by it and the two pools can be reported separately
    #: (docs §10.6).
    world_id: str

    #: The committed pick's node id — the address the out-of-sample panel
    #: was read for, and the one field the store persists beside the score.
    node_id: str

    #: The committed pick's out-of-sample information ratio over the
    #: sequestered epoch — the objective's leading term, frozen.
    ir_oos: float

    #: The scalar world score ``V_i^m`` — equal to :attr:`ir_oos` until a
    #: β-term moves it through :meth:`adjusted`.
    score: float

    #: The sequestered epoch the panel was drawn from, when the caller
    #: named it.  Carried unchanged; never derived, never defaulted to a
    #: fabricated id.
    epoch_id: str | None = None

    def __post_init__(self) -> None:
        # The identity fields are names, and a name that names nothing
        # cannot be scored — the same validation the committed pick itself
        # applies to its own id, for the same reason (feature 222).
        _require_name(self.world_id, "world_id", "a world of the replay pool")
        _require_name(self.node_id, "node_id", "the committed pick")
        # The two scalars are finite reals.  NaN and ±inf are refused on
        # both fields: the only −∞ in the objective's vocabulary is the
        # non-committing miss, which feature 222 owns, spells once at
        # NON_COMMITTING_SCORE, and which never carries a pick — a world
        # score holding it would be the miss wearing a pick.
        object.__setattr__(self, "ir_oos", _require_finite(self.ir_oos, "ir_oos"))
        object.__setattr__(self, "score", _require_finite(self.score, "score"))
        if self.epoch_id is not None:
            _require_name(
                self.epoch_id, "epoch_id", "the sequestered epoch the panel was read over"
            )

    def adjusted(self, delta: float) -> WorldScore:
        """The score with one adjustment applied — the seam §7.1's remaining
        terms ride.

        Returns a new :class:`WorldScore` whose :attr:`score` is this
        value's moved by ``delta`` and whose every other field — the
        measurement included — is unchanged; the original is frozen and
        untouched, so a β-term can never reach back into the leading term
        it is meant to sit *beside*.  ``delta`` is signed: features 257
        through 261 subtract (β₁'s trials, β₂'s nulls, β₃'s deflation,
        β₄'s divergence, β₅'s switches) and feature 262 adds (β₆'s
        orthogonality bonus), and the sign is the feature's own arithmetic,
        not this seam's — the seam's whole job is that a penalty is a
        visible, arguable term on a frozen measurement rather than a
        silent rescaling of it.

        ``delta`` must be a finite real (a ``bool`` is not one, and NaN
        would eat the ordering the scalar exists to feed) — refused with
        :class:`~scoring.WorldObjectiveError` otherwise, naming what was
        handed.  A non-finite delta is refused for the same reason the
        constructed score is: the miss's ``−∞`` is a *termination's*
        answer (feature 222), and no β-term may counterfeit it by pushing
        a made pick's score to an infinity the ranking would read as the
        non-committing floor.
        """
        delta = _require_finite(delta, "delta", "an adjustment to a world score")
        return replace(self, score=self.score + delta)


def world_objective(
    world_id: str,
    pick: object,
    returns: Mapping[dt.date, float],
    *,
    epoch_id: str | None = None,
) -> WorldScore:
    """Compute the per-world objective for a committed pick — prd §7.1's
    leading term, as a scalar world score.

    The feature's verb.  ``returns`` is the committed pick's panel over the
    sequestered epoch — one finite real reading per date, the dates the
    replay's sequestration chose (docs §10.1's ``epoch`` stands where the
    caller stands; this function cannot and does not re-derive the split).
    ``pick`` is the committed value or its address: a non-empty node-id
    string, or an object exposing ``node_id`` (feature 222's
    :class:`~policy_runtime.CommittedPick` among them).  ``world_id`` names
    the world of the replay pool the score was earned in, and ``epoch_id``
    — keyword-only, optional — is carried into the record when the caller
    can name the epoch the panel was drawn from.

    Answers a frozen :class:`WorldScore` with ``score == ir_oos`` — the
    objective *starts from* the leading term, and this is the one
    construction where that equality is the law rather than a coincidence
    a later feature happens to leave true.  Refuses, with
    :class:`~scoring.WorldObjectiveError` and nothing partial, an ask that
    cannot be scored:

    * a ``world_id`` or ``epoch_id`` that is not a name;
    * a ``pick`` that names no node (``None``, a blank, a ``bool``, a
      collection, an object with no ``node_id``) — wiring faults at the
      commit seam, named as such;
    * a ``returns`` panel that is not a mapping of dates to finite reals,
      or that holds fewer than :data:`IR_DATES_MINIMUM` dates, or whose
      series never varied — an information ratio is a mean over a standard
      deviation, and none of those panels defines one.

    Deterministic and pure: no store, no clock, no environment, and the
    same panel answers the same score to the last bit regardless of the
    mapping's iteration order (dates are sorted and summed with
    :func:`math.fsum`) — the replay's determinism law (docs §10.1) starts
    here, at the number everything downstream ranks on.
    """
    world = _require_name(world_id, "world_id", "a world of the replay pool")
    node_id = _pick_node_id(pick)
    dates, values = _panel_readings(returns)
    ratio = _ir_oos(dates, values)
    return WorldScore(
        world_id=world,
        node_id=node_id,
        ir_oos=ratio,
        score=ratio,
        epoch_id=epoch_id,
    )


# -- the seam's private vocabulary --------------------------------------------


def _require_name(value: object, field: str, what: str) -> str:
    """Refuse a value that is not a name, answering it unchanged when it is.

    A ``bool`` is refused before the string check because ``True`` would
    otherwise be one character of payload away from passing; a blank is
    refused because a name that names nothing cannot be scored, the same
    validation the committed pick applies to its own id.
    """
    if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
        raise WorldObjectiveError(
            f"{field} must name {what} by a non-empty string, got {value!r} "
            f"({type(value).__name__}): the identity fields of a world score "
            f"are the address the store persists beside it and the world the "
            f"aggregated objective stratifies by, so a value that names "
            f"nothing has no score to carry (feature 256, docs §10.3)"
        )
    return value


def _require_finite(value: object, field: str, what: str = "a world score scalar") -> float:
    """Narrow a real to a finite ``float``, refusing NaN, ±inf and ``bool``.

    ``int`` is accepted and narrowed; ``bool`` is refused before it (a
    ``bool`` is an ``int`` in Python's hierarchy and not a reading here);
    anything that is not a :class:`numbers.Real` is refused as a type
    fault rather than escaping as a ``TypeError`` from inside the
    arithmetic.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise WorldObjectiveError(
            f"{field} must be {what} as a real number, got {value!r} "
            f"({type(value).__name__}): the score and its leading term feed "
            f"the dreaming loop's argmax and the store's REAL column, and a "
            f"value that is not a real has no place in either (feature 256)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise WorldObjectiveError(
            f"{field} must be finite, got {narrowed!r}: a NaN compares false "
            f"against every score and would silently drop out of the argmax, "
            f"and an infinity is not a measurement — the only −∞ the "
            f"objective's vocabulary holds is the non-committing miss, which "
            f"feature 222 owns (NON_COMMITTING_SCORE) and which never "
            f"carries a pick, so no world score may counterfeit it "
            f"(feature 256, migration 0109)"
        )
    return narrowed


def _pick_node_id(pick: object) -> str:
    """The committed pick's node id, from either of the two spellings.

    A non-empty string is the address itself; anything else must expose a
    ``node_id`` attribute that is one — feature 222's ``CommittedPick``
    being the intended object, duck-typed because the module loader's
    synthetic-name re-execution means an ``isinstance`` would refuse the
    very objects composition produces.  Everything else — ``None``, a
    blank, a ``bool``, a collection, an object with no ``node_id`` — is
    refused naming what was carried, because the repair differs: a
    collection is a batch spelled where one pick belongs, and an object
    with no ``node_id`` is not the committed value at all.
    """
    if isinstance(pick, bool):
        raise WorldObjectiveError(_not_a_pick_message(pick, "a bool"))
    if isinstance(pick, str):
        if not pick.strip():
            raise WorldObjectiveError(_not_a_pick_message(pick, "the empty string"))
        return pick
    node_id = getattr(pick, "node_id", None)
    if isinstance(node_id, bool) or not isinstance(node_id, str) or not node_id.strip():
        raise WorldObjectiveError(_not_a_pick_message(pick))
    return node_id


def _not_a_pick_message(pick: object, carried: str | None = None) -> str:
    """The refusal for a pick that names no node, naming what was carried.

    Both accepted spellings are named in the message because the repair is
    at the caller's seam, not this one: the committed value (feature 222's
    pick, or anything exposing its ``node_id``) or the address itself.
    """
    described = (
        f"carried {carried}"
        if carried is not None
        else "exposes no node_id a pick could be read from"
    )
    return (
        f"the per-world objective is computed on the committed pick — one "
        f"node, named once — and this ask {described}: got {pick!r} "
        f"({type(pick).__name__}). Name the pick either by its address (a "
        f"non-empty node-id string) or by the committed value itself (any "
        f"object exposing node_id, feature 222's CommittedPick among them); "
        f"a collection is a batch spelled where one pick belongs, and an "
        f"ask that names no node has no out-of-sample panel to read "
        f"(feature 256, prd §7.1)"
    )


def _panel_readings(returns: object) -> tuple[list[dt.date], list[float]]:
    """Validate and flatten the sequestered panel: sorted dates, readings.

    The panel must be a :class:`~collections.abc.Mapping` — one reading
    per date, because a date with two readings is not a measurement but a
    choice the caller has not made, and the mapping's own key uniqueness
    is what keeps that law for free.  Keys must be dates (a ``datetime``
    is refused as such: it is a date with a clock bolted on, and a panel
    keyed by instants is a caller confusion the seam should name rather
    than silently truncate to its calendar day).  Readings must be finite
    reals (``bool`` refused, NaN and ±inf refused — a NaN reading would
    make the ratio a NaN, and the store's law is that a score is the
    record of a completed measurement).

    A mapping with ``{}``-falsy content is an *empty panel*, refused on
    the count below, not on truthiness — the two are different refusals
    and only one of them is true here.
    """
    if not isinstance(returns, Mapping):
        raise WorldObjectiveError(
            f"the committed pick's sequestered panel must be a mapping of "
            f"dates to readings, got {returns!r} ({type(returns).__name__}): "
            f"one reading per date is the panel's own law — a mapping holds "
            f"it for free, and a sequence cannot (feature 256, prd §7.1)"
        )
    dates: list[dt.date] = []
    values: list[float] = []
    for day, reading in returns.items():
        if isinstance(day, dt.datetime) or not isinstance(day, dt.date):
            raise WorldObjectiveError(
                f"the committed pick's sequestered panel must be keyed by "
                f"dates, and one of its keys is {day!r} "
                f"({type(day).__name__}): the ratio is over per-date "
                f"readings, and a panel keyed by anything else — a "
                f"datetime, a string, a number — is not the sequestered "
                f"epoch's shape (feature 256)"
            )
        dates.append(day)
        reading = _require_finite(
            reading,
            f"the panel's reading for {day.isoformat()}",
            "a per-date reading",
        )
        values.append(reading)
    if len(dates) < IR_DATES_MINIMUM:
        raise WorldObjectiveError(
            f"the committed pick's sequestered panel holds {len(dates)} "
            f"date(s), and an information ratio is a mean over a standard "
            f"deviation — a standard deviation over fewer than "
            f"{IR_DATES_MINIMUM} dates is zero, and dividing by it would "
            f"fabricate an infinity that outranks every honest score; "
            f"refusing rather than dividing (feature 256, prd §7.1)"
        )
    order = sorted(range(len(dates)), key=dates.__getitem__)
    return [dates[i] for i in order], [values[i] for i in order]


def _ir_oos(dates: list[dt.date], values: list[float]) -> float:
    """The information ratio of the pick's panel — feature 80's spelling.

    Mean over population standard deviation (``ddof=0``: the sequestered
    epoch is the whole sample the pick was measured over), summed with
    :func:`math.fsum` over dates sorted by :func:`_panel_readings`, so the
    answer is exact and iteration-order-independent.  Refused when the
    series never varied: a constant panel has no reward-to-variance ratio,
    and the refusal is the honest one — the pick measured nothing, and no
    haircut or default invented here would make the number mean anything.
    """
    count = len(values)
    mean = math.fsum(values) / count
    variance = math.fsum((value - mean) ** 2 for value in values) / count
    std = math.sqrt(variance)
    if std == 0.0:
        raise WorldObjectiveError(
            f"the committed pick's sequestered panel returned a constant "
            f"reading across all {count} of its dates, so its standard "
            f"deviation is zero and its information ratio is undefined; "
            f"refusing rather than dividing by zero — a pick whose return "
            f"never varied has no reward-to-variance ratio to score "
            f"(feature 256, prd §7.1)"
        )
    return mean / std
