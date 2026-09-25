"""Feature 314: the order's posture — passive by default, aggressive only
when the decay outruns the fill.

app_spec.xml, "Order Routing & Venue Filters", feature 314: *System posts
orders passively by default, which sends an aggressive order only when
signal decay horizon is shorter than expected fill time.*
``docs/nullius-tech-architecture.md`` §13.2 states the same rule as one
line of the execution engine's constant contract — *"Post-only by
default; aggressive only when the signal's decay horizon is shorter than
the expected fill time."* — and ``docs/alpha-engine-prd.md`` C9 repeats
it with the venue's own words: *"Post-only by default; taker only when
signal decay horizon < expected fill time."*  This module is that one
line as a single question, asked per order as the order path builds it:
**how does this order cross?**

**The two postures buy different things, and that is the whole
economics.**  A passive order buys the maker's price and pays for it
with *time*: it sits in the queue and fills when the tape comes to it.
An aggressive order buys *time* and pays for it twice, once in the
spread it crosses and once in the taker fee — the certain, immediate
half of the round trip the PRD's venue notes price (0.1% taker at VIP0,
≈ 0.2% round trip; the maker leg is the cheap leg everywhere, and free
on the zero-maker venues).  Time is only worth buying when the edge is
running out of it.  So the sentence's default is the crossing that pays
in time, and the exception has to earn itself against the one
comparison that says what waiting would cost: *does the signal's decay
horizon outlive the expected fill?*

**And the exception is exactly that comparison, because of what a
passive fill that arrives too late is.**  The trade exists to capture an
edge; a passive order fills when the queue lets it, which is *later*.
When the decay horizon is shorter than that wait, the fill lands after
the reason for the order is gone: the position fills holding no edge,
having spent the queue wait to acquire it, which is the one outcome
strictly worse than either posture chosen for its own sake.  Crossing
immediately pays the certain cost and captures what remains.  So the
one thing that justifies aggression is the arithmetic — the edge decays
faster than the queue clears — and the sentence admits it *only* then.
Not the order's size, not the time of day, not a caller's say-so: the
clause after the comma is a gate with one input.

**"Only when" is structural, not advisory.**
:func:`resolve_order_posture` takes **no posture argument**.  There is
no way to ask for an aggressive order, no hint, no flag, no urgency
field — the single door to :data:`AGGRESSIVE_ORDER` is the comparison
itself, made inside the one act that resolves a posture.  A caller
cannot smuggle the spread across any more than a caller can merge two
books by forgetting to compare accounts (the stance
:class:`~router.margin.MarginScope` takes for its own sentence); the
order path that wants to know *why* an order crossed reads the two
terms off the answer, because those are the whole of the reason.

**"Shorter than" is strict.**  C9 spells the comparison as ``<``: at
equality the edge exactly survives the wait — every unit of it is still
there when the fill lands — so the default stands.  The comparison is
over :class:`datetime.timedelta` values, exact by construction, so the
boundary sits where the sentence puts it and not where a floating-point
representation happens to round; a horizon one microsecond shorter than
the wait crosses, and one microsecond longer posts.

**Each term is measured, never defaulted.**  ``signal_decay_horizon``
is the promoted signal's own decay — the quantity the research path
measures over its decay axis and §13.4's outer loop recalibrates as the
labels accumulate.  ``expected_fill_time`` is the deployment's own
expectation for how long a passive order waits, measured from shadow
execution the way §6.2's cost-model block demands its latencies be
(*``source: measured_from_shadow``*, **not assumed*) — feature 321's
shadow-mode default is where that measurement accumulates before any
live order exists to be wrong about.  A default for either would be
this module inventing an edge's length or a queue's wait, so both are
**required keywords with no default**, the law feature 316's own
``rebalance_ts`` states for its term: the two facts this decision is
made over have to arrive with the ask, because they are the decision.

**The terms are durations, and they arrive as timedeltas.**  A bare
number states no unit — thirty seconds and thirty minutes compel
different postures over the same queue — so a number is refused by name
rather than guessed at, and so is anything else that is not a length of
time.  Zero is admissible for either term, because zero is a
measurement: a horizon of zero is an edge already gone, the strongest
case the sentence names for crossing (nothing survives waiting), and a
fill time of zero is a queue expected to clear the instant the order
lands, which leaves nothing to outrun and so keeps the default.
Negative is refused: no measurement of a length of time runs backwards,
and a comparison over one would be a comparison over nothing.

**The verdict rides beside its terms.**  :class:`OrderPosture` carries
the two durations next to the posture they compel — the shape
:class:`~router.client_order_id.ClientOrderId` states for itself (the
terms beside the value they fold to), for the same reason: an operator
auditing why an order crossed the spread reads the edge and the wait
off the record, not off a recollection of what the signal was doing.
The ``posture`` field is **computed when omitted** — the sentence's
*by default*, made a construction fact — and **checked when stated**:
a caller that reconstructs a recorded posture states the verdict and
the terms verify it, and a disagreement is refused, because a record
that said aggressive for terms that compel passive would be a record
that lies about why the spread was crossed.

**The vocabulary is the system's, not the venue's.**  ``passive`` and
``aggressive`` — the app_spec sentence's own words — are the closed set
:data:`ORDER_POSTURES`.  §13.2's *post-only* and C9's *taker* are the
venue layer's spellings of the same two postures, at the flags the
venue itself defines, and mapping this module's token onto those flags
(a time-in-force value, a market order) is deliberately **not done
here**: that mapping is a venue constant, and *"rejects any hardcoded
venue constant in the order path"* is feature 311's own sentence — the
law of this whole category.  The caller that speaks to the venue
translates; this module decides.

**No table, no component, no clock, no I/O.**  The posture is a pure
function of the two durations — the same ask answers the same posture
in any process, on any machine, on any day — which is what makes it
safe for the processes §13.2 and feature 320 deliberately separate: a
restarted router re-deriving an order mid-rebalance agrees with the
process it replaced without speaking to it, the same way two processes
agree on feature 316's key.  Nothing to persist (the posture is decided
per order as it is built; a deployment that wants it recorded records
the value in the log that already names the order), so no ``@register``
is added — the member still registers exactly one component, feature
310's exchangeInfo store — and no seat export and no migration either.
Stdlib only, and import-cheap — ``dataclasses`` and one name from
:mod:`datetime` — so the factory's scan pays nothing for the choice.

**What this module deliberately does not do.**  It does not *place*,
*price* or *size* an order — feature 312 rounds to the venue's step and
tick, feature 313 guards the minimum notional, and the book's weights
(features 305, 309) decided *whether* to trade at all; this module
decides only *how the order crosses*.  It does not *model the fill*:
the passive fill probability against queue depth, the trade-through
rule and the queue-position penalty are the cost model's own
quantities, and this module reads no queue depth and prices nothing —
it reads the *expectation* of the wait and leaves the shape of the wait
to the model that owns it.  It does not *measure* either term (see
above — both arrive stated, and the measurement's owners are the
research path and the shadow record).  It does not spell the venue's
order-type flags (one paragraph up).  And it does not decide what
happens to an order that sits unfilled — the posture is chosen once,
per order, as it is built, and the order's life after the post belongs
to the order path, not to the choice that made it a post.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .errors import ORDER_POSTURE_CODE, RouterOrderPostureError

__all__ = [
    "AGGRESSIVE_ORDER",
    "ORDER_POSTURES",
    "PASSIVE_ORDER",
    "OrderPosture",
    "resolve_order_posture",
]

#: The posture the sentence requires by default: the order sits on the
#: passive side of the book and waits for the tape to come to it, paying
#: for the fill with time instead of with the spread and the taker fee.
#: The greppable token the order path branches on, and the value every
#: ask answers unless its own terms compel the other one.
PASSIVE_ORDER = "passive"

#: The posture the sentence admits only under its one comparison: the
#: order crosses the spread and takes, buying time at the certain price
#: of the spread plus the taker fee.  Named here so the refusal can spell
#: the value it received and the value the terms compelled without either
#: being a literal in a message.
AGGRESSIVE_ORDER = "aggressive"

#: The closed posture vocabulary — exactly the two ways an order can
#: cross, and the set the value layer validates against so a posture this
#: system has never heard of is refused rather than mapped onto one of
#: the two.  Built from the two names above, the discipline
#: :data:`~router.margin.MARGIN_MODES` keeps for its own vocabulary: one
#: spelling, one home.  Deliberately *not* the venue's spellings —
#: §13.2's ``post-only`` and C9's ``taker`` name the same two postures
#: one layer down, at the flags the venue itself defines, and admitting
#: them here would be two vocabularies for one fact with nothing to keep
#: them in sync but care.
ORDER_POSTURES = frozenset({PASSIVE_ORDER, AGGRESSIVE_ORDER})


def _validated_decay_horizon(value: Any) -> timedelta:
    """Return ``value`` as a signal's decay horizon, or refuse it by name.

    A :class:`~datetime.timedelta`, non-negative — and both halves of that
    are load-bearing rather than stylistic.  A bare number states no unit,
    and the comparison this term feeds decides the order's posture, so a
    caller handing ``30`` has not stated whether the edge survives thirty
    seconds or thirty minutes against the same queue; the number is
    refused rather than read in some unit this module picked.  Zero is
    admissible, because zero is a measurement — an edge already gone is
    the strongest case the sentence names for crossing — while negative
    is not: no measurement of a length of time runs backwards, and a
    horizon that ended before it began is not a horizon to compare.
    """
    if not isinstance(value, timedelta):
        raise RouterOrderPostureError(
            f"{ORDER_POSTURE_CODE}: signal_decay_horizon must be a "
            f"timedelta, got {value!r} ({type(value).__name__}); the "
            "comparison that gates aggression is over two lengths of "
            "time, and a bare number states no unit, so thirty seconds "
            "and thirty minutes could not be told apart (feature 314)"
        )
    if value < timedelta(0):
        raise RouterOrderPostureError(
            f"{ORDER_POSTURE_CODE}: signal_decay_horizon cannot be "
            f"negative, got {value!r}; the horizon names how long the "
            "signal's edge survives, and an edge that ended before it "
            "began is a length no measurement returns (feature 314)"
        )
    return value


def _validated_fill_time(value: Any) -> timedelta:
    """Return ``value`` as an expected fill time, or refuse it by name.

    The same rule the horizon holds, term for term: a
    :class:`~datetime.timedelta` because the comparison is over two
    lengths of time and a number states no unit; zero admissible because
    a queue expected to clear the instant the order lands is a
    measurement, and one that leaves nothing to outrun, so the default
    stands; negative refused because a wait that finished before the
    order was placed is not a wait anyone measured.  The two validators
    are separate functions rather than one parameterised one for the
    reason :func:`router.margin._validated_book_id` and
    :func:`router.margin._validated_account` are: the refusal names the
    term and the term's own ground, not a placeholder.
    """
    if not isinstance(value, timedelta):
        raise RouterOrderPostureError(
            f"{ORDER_POSTURE_CODE}: expected_fill_time must be a "
            f"timedelta, got {value!r} ({type(value).__name__}); the "
            "comparison that gates aggression is over two lengths of "
            "time, and a bare number states no unit on either side of "
            "it (feature 314)"
        )
    if value < timedelta(0):
        raise RouterOrderPostureError(
            f"{ORDER_POSTURE_CODE}: expected_fill_time cannot be "
            f"negative, got {value!r}; the fill time names how long the "
            "queue is expected to take, and a wait that finished before "
            "the order was placed is a length no measurement returns "
            "(feature 314)"
        )
    return value


def _validated_posture(value: Any) -> str:
    """Return ``value`` as a posture token, or refuse it by name.

    Membership is tested against the *string* the value would have to be
    rather than against the value itself, because ``frozenset``
    membership raises :class:`TypeError` on an unhashable argument — a
    ``[]`` here is a crash, not a ``False`` — and a caller offering a
    list to a vocabulary of tokens deserves this member's refusal naming
    the value, the same trap :func:`router.margin._validated_mode`
    catches for its own set.  No token is case-folded or stripped onto a
    real one: the posture is this system's own vocabulary, not a name a
    deployment spelled, and a value that almost matches one of the two
    postures is a value nobody stated.
    """
    if not isinstance(value, str) or value not in ORDER_POSTURES:
        raise RouterOrderPostureError(
            f"{ORDER_POSTURE_CODE}: a posture is one of "
            f"{sorted(ORDER_POSTURES)}, got {value!r} "
            f"({type(value).__name__}); the posture says which side of "
            "the spread the order crosses on, and the venue's own "
            "spellings (post-only, taker) are a layer this module does "
            "not speak (feature 314)"
        )
    return value


def _posture_for(signal_decay_horizon: timedelta, expected_fill_time: timedelta) -> str:
    """The sentence's comparison, in the one place it lives.

    Strict, as C9 spells it (``<``): a horizon exactly as long as the
    wait still delivers every unit of edge with the fill, so the default
    stands, and a horizon shorter by any margin at all — one microsecond
    — crosses.  Kept as one function rather than an inline expression at
    each use, so the value's derivation, the value's verification and a
    caller recomputing a posture cannot drift the way two spellings of
    one comparison do; the exactness of :class:`~datetime.timedelta`
    puts the boundary where the sentence puts it, not where a float
    rounds to.
    """
    return AGGRESSIVE_ORDER if signal_decay_horizon < expected_fill_time else PASSIVE_ORDER


@dataclass(frozen=True)
class OrderPosture:
    """One order's crossing, decided: the two terms and the posture they compel.

    The value :func:`resolve_order_posture` answers — the verdict a
    caller branches on and the facts it was made over, kept together
    because a verdict that returned only ``passive`` or ``aggressive``
    would lose *why*, and the why is the whole audit trail for a spread
    that got crossed:

    * ``signal_decay_horizon`` — how long the signal's edge survives.
      The promoted signal's own measured decay, stated by the caller
      that knows the signal; never defaulted, because a horizon this
      module invented would be an edge nobody measured.
    * ``expected_fill_time`` — how long a passive order is expected to
      wait for its fill.  The deployment's own shadow-measured
      expectation; never defaulted, for the same reason one layer over.
    * ``posture`` — :data:`PASSIVE_ORDER` or :data:`AGGRESSIVE_ORDER`,
      from :data:`ORDER_POSTURES`.  **Computed when omitted** — omitting
      it *is* the sentence's *by default* — and when stated, validated
      and checked against the terms it rides beside: a stated posture
      that disagrees with its own durations is refused, because that
      value would record an order that crossed differently than its
      urgency compels, which is a record that lies about the one thing
      it exists to say.  The not-stated sentinel is the empty string
      exactly; anything else handed here is a stated posture and is
      judged, never silently derived from.

    Constructible with either posture **on purpose**: the value
    describes a decision, and a value type that could not express the
    posture this module compels under its own terms could not be checked
    against.  The *enforcement* is the comparison's, not the value's —
    see :func:`resolve_order_posture`.

    All three fields are canonicalised at construction — the durations
    validated, the token checked against the vocabulary — so two values
    built from one ask compare equal however the caller came by them.
    Frozen, and hashable: a decision can stand as its own key.
    """

    signal_decay_horizon: timedelta
    expected_fill_time: timedelta
    posture: str = ""

    def __post_init__(self) -> None:
        # Normalize rather than trust: a value built by hand in a test or
        # reconstructed from a record gets the same validation the verb
        # applies, and the stated posture -- if any -- is verified against
        # the terms it travels with before the value exists.  The
        # not-stated sentinel is the empty string *exactly*: anything else
        # a caller hands -- ``None``, a blank padded token, a bare ``0`` --
        # is a stated posture and is judged, not swallowed, because a
        # near-miss that derived silently would be the sentence's default
        # worn as a disguise.
        horizon = _validated_decay_horizon(self.signal_decay_horizon)
        fill = _validated_fill_time(self.expected_fill_time)
        expected = _posture_for(horizon, fill)
        object.__setattr__(self, "signal_decay_horizon", horizon)
        object.__setattr__(self, "expected_fill_time", fill)
        if self.posture == "":
            object.__setattr__(self, "posture", expected)
            return
        stated = _validated_posture(self.posture)
        if stated != expected:
            raise RouterOrderPostureError(
                f"{ORDER_POSTURE_CODE}: the stated posture {stated!r} does "
                f"not match the one compelled by a signal decay horizon "
                f"of {horizon!r} against an expected fill time of {fill!r} "
                f"({expected!r}); a posture that disagrees with its own "
                "terms would record an order that crosses differently "
                "than its urgency compels (feature 314)"
            )
        object.__setattr__(self, "posture", stated)

    @property
    def is_aggressive(self) -> bool:
        """The sentence's exception, spelled as the one question a caller asks.

        ``True`` exactly when the terms compelled the crossing.  There is
        deliberately no ``is_passive`` beside it: over a closed
        vocabulary of two, a second predicate would be a second spelling
        of one fact with nothing to keep them in sync but care — the
        default is what remains when the exception's gate fails, and a
        caller that wants it reads ``not posture.is_aggressive`` or the
        token itself.
        """
        return self.posture == AGGRESSIVE_ORDER


def resolve_order_posture(
    *,
    signal_decay_horizon: Any,
    expected_fill_time: Any,
) -> OrderPosture:
    """Feature 314's verb: decide how an order crosses.

    app_spec.xml, "Order Routing & Venue Filters", feature 314: *System
    posts orders passively by default, which sends an aggressive order
    only when signal decay horizon is shorter than expected fill time.*
    This is that sentence as one call: it answers the frozen
    :class:`OrderPosture` for the order being built — passive unless its
    own terms compel the crossing, aggressive exactly when the decay
    horizon is *strictly* shorter than the expected fill time.

    Each argument is a required keyword with no default, and there is
    deliberately **no posture argument at all**: the sentence's *only
    when* is structural, so the single door to an aggressive order is
    the comparison this function makes, and a caller cannot ask for one.
    A default for either term would be this module inventing an edge's
    length or a queue's wait — the law feature 316's ``rebalance_ts``
    states for its own term, and the same one here.

    Refuses :class:`~router.errors.RouterOrderPostureError` for either
    term that is not a non-negative :class:`~datetime.timedelta`, and
    for a stated posture that contradicts the terms it rides beside (on
    direct construction — this function never states one).

    Deterministic by construction: the same two terms return the same
    posture in any process, on any machine, on any day, with no clock
    read and no state consulted.  That is what makes the choice safe to
    re-derive — a restarted router agrees with the process it replaced —
    and it is the whole contract.
    """
    return OrderPosture(
        signal_decay_horizon=signal_decay_horizon,
        expected_fill_time=expected_fill_time,
    )
