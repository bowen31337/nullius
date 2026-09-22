"""Feature 226, the beta scalar — read once at initialization, fixed for the
whole episode.

app_spec.xml, "Exploration Policy Runtime", feature 226: *System rejects a
reassignment of the beta scalar after initialization, holding it fixed for the
whole episode.*  docs/nullius-tech-architecture.md §609 states the law verbatim
— *"``beta`` is read once in ``__init__``, fixed for the episode, routed through
a single ``_schedule(beta) -> dict`` so every threshold moves together.  Swept on
a grid offline.  This is carried over from the paper unchanged because it is what
makes cross-cycle comparison legible."* — and docs/alpha-engine-prd.md §7.4
carries the paper's own sentence: *"Keep the paper's single-scalar discipline
verbatim: one ``beta`` controlling explore/exploit, patience, and pruning
aggressiveness; **fixed within an episode**; swept on a grid during offline
evaluation"*.

**The feature is an immutability law, and its precedent is already in this
workspace.**  Feature 10's :class:`contract.MarketWindow` fixes a decision time
at construction and refuses every reassignment path — "no caller can reassign"
— for the same reason in a different currency: a guarantee that anything
downstream derives from the fixed value is only as good as the value's
inability to move.  Here the thing that may not move is ``beta``, and what
downstream derives from it is *every threshold in the episode* (feature 227's
``_schedule(beta) -> dict``).  A beta that could be reassigned mid-episode would
mean the thresholds a policy explored under were not the thresholds its score
was earned under, which is the cross-cycle comparison §609 says the discipline
exists to protect: two cycles are comparable only if each is one scalar from
start to finish.

Feature 226 is therefore the *value* half of the beta knob and nothing more.  It
owns :class:`EpisodeBeta` (the scalar, fixed) and :func:`read_beta` (the one
sanctioned moment it is read — initialization), and it does **not** own the
threshold schedule (feature 227), the grid sweep (an offline evaluation, not a
runtime act), or the per-cycle default ("chosen per cycle from live evidence and
prior sweeps" — a dreaming-loop decision, feature 228's neighbourhood).  The
split is the feature: 226 says *the scalar is one number and it does not move*;
227 says *every threshold is derived from it, together*.

**A scalar, not a wrapper.**  :class:`EpisodeBeta` *is* the number — a
:class:`float` subclass — rather than an object carrying one behind a ``.value``
a consumer has to unwrap.  That is deliberate: the beta of an episode is read by
the schedule (227), by the replay's own arithmetic, and by the ``replay_score``
row that records which scalar a score was earned under (table ``replay_score``,
feature 106's ``beta REAL NOT NULL``), and a wrapper would put a conversion at
every one of those seams — the drift the law exists to prevent arriving through
the wrapper instead of through a reassignment.  It behaves as a float
everywhere: comparisons, arithmetic, hashing, ``json``, a SQL parameter, a dict
key.  What it does *not* do is move.

**The refusal is on every path, including the ones a plain value type leaves
open.**  ``beta.value = 0.9``, ``beta._value = 0.9``, ``beta.anything = 0.9``
and ``del beta.value`` all raise :class:`BetaFixedError`; the scalar carries
``__slots__ = ()`` and so has no ``__dict__``, so a caller reaching past the
attribute protocol with ``object.__setattr__`` finds no slot to rebind and the
float's own C storage is not an attribute at all — the same slots-not-just-a-
guard move :class:`contract.MarketWindow` makes ("the read-only guarantee is
only as strong as the object's inability to grow new attributes"), and the
reason the guard is a fact about the type rather than a promise in a docstring.
A caller that re-invokes the constructor on a live scalar (``beta.__init__(x)``)
cannot move it either: the value was bound in ``__new__``, which the second call
does not reach, so "after initialization" includes a caller reaching for the
initializer a second time.

**What the law deliberately does not do.**  It does not impose a *band*.  Which
finite betas a sweep grid tries, and which one a cycle defaults to, is the
deployment's and the dreaming loop's business — refusing ``beta = 0.0`` or a
negative scalar would be inventing a contract no document states, and the safe
direction for a law is to refuse only what is not a magnitude at all.  So the
value must be a finite real number (a ``bool`` is an ``int`` and is refused;
text is refused rather than coerced — a beta that arrives as ``"0.7"`` is not a
number, and coercion is how a mistyped config becomes a silent episode), and no
band is applied.  It also does not police a caller's *local name*: a caller that
reads a second beta has begun a second episode, and the honest record of which
scalar a score was earned under is the ``replay_score`` row the replay writes —
recorded, not prevented, and the reason 227's schedule is a pure function of
this scalar rather than of an episode's mutable state.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers` and the member's own
error, nothing else at module scope, so the factory's scan (which imports this
package to fire its ``@register`` builder) pays nothing for the law.
"""

from __future__ import annotations

import math
import numbers
from typing import Self

from .errors import BetaFixedError

__all__ = [
    "EpisodeBeta",
    "read_beta",
]


class EpisodeBeta(float):
    """The beta scalar of one replay episode — read once, then fixed.

    A :class:`float` subclass rather than a wrapper, so the scalar is *the*
    number every consumer reads: feature 227's threshold schedule derives from
    it, the replay's own arithmetic uses it, and the ``replay_score`` row
    records it as a plain REAL.  It compares, hashes, rounds, serializes and
    binds like the float it is — and it refuses every path by which a caller
    could move it, which is the whole of feature 226.

    The value is bound in :meth:`__new__` and never again.  Assignment and
    deletion of any attribute raise :class:`BetaFixedError`, naming the scalar
    and the repair; the class carries ``__slots__ = ()`` and so no ``__dict__``,
    so there is no shadow attribute a caller could attach and no slot for
    ``object.__setattr__`` to rebind — the value lives in the float's own
    storage, which is not an attribute.  A second call to the initializer
    (``beta.__init__(other)``) does not reach :meth:`__new__` and so cannot
    move it: "after initialization" includes a caller reaching for the
    initializer again, the same boundary :class:`contract.MarketWindow` draws
    around its own constructor ("build a new window instead of re-initializing
    this one").

    Construct through :func:`read_beta` — the named initialization moment — or
    directly; the two are the same act, and ``read_beta`` is the spelling a
    runtime reads best at the top of an episode.
    """

    #: Empty, deliberately: the read-only guarantee is only as strong as the
    #: object's inability to grow new attributes.  With a ``__dict__`` a caller
    #: could attach shadow state beside the fixed scalar; with no slots at all
    #: and no ``__dict__``, there is nothing to rebind and nothing to attach.
    __slots__ = ()

    def __new__(cls, value: object) -> Self:
        """Bind the scalar once — refusing a value that is not a finite number.

        The one place beta is read into an episode's scalar.  Accepts any real
        number — :class:`numbers.Real`, which is Python's own spelling of "a
        number on the real line": the ``float`` and ``int`` a sweep grid or a
        configuration produces (``beta = 1`` is a legitimate grid point, the
        exploit-only end of the sweep), and the other real types too, so the
        rule is literally *"a real number"* rather than *"a real number, if it
        happens to be spelled float or int"*.  Everything else is refused with
        :class:`BetaFixedError`, naming what arrived:

        * a ``bool``, because ``True`` is an ``int`` and ``beta = True`` is a
          flag that happens to have the value one, not a grid point;
        * text, a ``None``, a ``Decimal`` or a ``complex``, or any other object,
          because those are not real numbers — and **coercion is how a mistyped
          configuration becomes a silent episode**, the same stance the
          member's SQLite layer takes on affinity (never coerce, refuse and
          name).  A ``Decimal`` is refused for exactly that reason: it is a
          *decimal* number, and the scalar's own arithmetic is binary floating
          point, so accepting one would mean the episode ran at a precision the
          config did not name;
        * a value that cannot be a float at all, or is not finite: an ``int``
          too large for a float (``10**400``) and a NaN alike derive no
          threshold — a NaN beta compares false against everything, so no
          threshold derived from it is a threshold, and an infinite beta is a
          magnitude no sweep grid yields.  Only finiteness is checked — no
          *band* is imposed, because which finite values the sweep tries is the
          deployment's business (feature 167's committed ceiling territory),
          not this law's.

        Every refusal is a :class:`BetaFixedError`, including the one the
        conversion itself would raise: ``float(10**400)`` raises
        :class:`OverflowError`, and letting that escape would hand a caller
        catching this member's one base class an exception it does not catch —
        the error-vocabulary leak a member seam must not have
        ([[error-vocabulary-at-member-seams]]).  The conversion's own failures
        are translated rather than propagated.
        """
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise BetaFixedError(
                f"an episode's beta must be a real number, got "
                f"{value!r} ({type(value).__name__}): the scalar is read once at "
                f"initialization and every threshold in the episode is derived "
                f"from it, so a beta that is not a number derives no threshold at "
                f"all — and text is refused rather than coerced, because "
                f"coercion is how a mistyped configuration becomes a silent "
                f"episode (feature 226, docs §609)"
            )
        try:
            scalar = float(value)
        except (OverflowError, ValueError, TypeError) as unconvertible:
            raise BetaFixedError(
                f"an episode's beta must be a finite number a float can carry, "
                f"got {value!r}: the scalar is one number the whole episode is "
                f"compared under and every threshold in it is derived from it, so "
                f"a magnitude beyond floating point derives no threshold at all "
                f"(feature 226, docs §609)"
            ) from unconvertible
        if not math.isfinite(scalar):
            raise BetaFixedError(
                f"an episode's beta must be finite, got {value!r}: a NaN beta "
                f"compares false against everything, so no threshold derived from "
                f"it is a threshold, and an infinite beta is a magnitude no sweep "
                f"grid yields — the scalar is one number the whole episode is "
                f"compared under (feature 226, docs §609)"
            )
        return super().__new__(cls, scalar)

    @property
    def value(self) -> float:
        """The scalar as a plain :class:`float` — read-only, fixed for the episode.

        The scalar itself, unwrapped: ``float(beta)`` and ``beta.value`` are the
        same number, and neither one is a way to change it.  A caller that wants
        a plain float — a configuration echo, a log line, a JSON field — asks
        here rather than reaching for the scalar's storage, and gets a value
        that is equal to the episode's beta however long the episode has run.
        """
        return float(self)

    def __setattr__(self, name: str, value: object) -> None:
        """Refuse every assignment — the scalar is fixed for the episode.

        Not just ``value``: *any* attribute, because the class declares no
        slots, so an accepted assignment here could only be shadow state beside
        the fixed scalar.  The refusal names the act and the repair, the way
        :class:`contract.MarketWindow`'s read-only guard does: a different beta
        is a different episode, not a reassignment of this one.
        """
        raise BetaFixedError(
            f"beta is fixed for the whole episode and cannot be reassigned "
            f"(attempted `beta.{name} = {value!r}`): it is read once at "
            f"initialization and every threshold in the episode is derived from "
            f"it, so a scalar that moves mid-episode would mean the thresholds a "
            f"policy explored under were not the thresholds its score was earned "
            f"under — a different beta is a different episode, not a "
            f"reassignment of this one (feature 226, docs §609)"
        )

    def __delattr__(self, name: str) -> None:
        """Refuse deletion — there is nothing here to remove.

        The same law from the other side: a scalar with no attributes cannot
        lose one, and ``del beta.value`` reaching for the fixed value is the
        reassignment it is not allowed to make.  Refused in the same words, so
        an author who tried the other spelling reads the same sentence.
        """
        raise BetaFixedError(
            f"beta is fixed for the whole episode and carries nothing to delete "
            f"(attempted `del beta.{name}`): the scalar's value is bound at "
            f"initialization and is not an attribute a caller can remove — a "
            f"different beta is a different episode, not a reassignment of this "
            f"one (feature 226, docs §609)"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"EpisodeBeta({float(self)!r})"


def read_beta(value: object) -> EpisodeBeta:
    """Read the episode's beta scalar once — the initialization moment.

    The feature's verb.  A runtime reads its episode's beta here, once, at the
    top of the episode: feature 227's threshold schedule is then derived from
    the returned scalar and nothing else, so every threshold in the episode
    moves together because they are all functions of one number that cannot
    move.  The returned :class:`EpisodeBeta` is fixed from that moment for the
    rest of the episode, and every reassignment path raises
    :class:`BetaFixedError` — the law docs §609 states ("read once in
    ``__init__``, fixed for the episode") read as a value type, the same shape
    feature 10's :class:`contract.MarketWindow` takes on a decision time.

    The verb exists beside the constructor because *when* beta is read is the
    feature: a caller that reads it in the middle of an episode has already
    broken the law the scalar can only enforce from where it sits, and the call
    site ``beta = read_beta(config.beta)`` at the top of an episode says so.
    Reads a ``float`` or an ``int``; refuses everything else with
    :class:`BetaFixedError` rather than coercing it (see
    :meth:`EpisodeBeta.__new__` for what and why).  Pure: it mutates nothing and
    consults nothing — no grid, no store, no clock — so an episode's beta is
    exactly the number it was read from.
    """
    return EpisodeBeta(value)
