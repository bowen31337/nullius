"""The position and concentration limits — feature 304: the two bounds.

app_spec.xml, "Portfolio Book Construction", feature 304: *System applies
per-position and concentration limits, which rejects a target weight breaching
either bound.*  Both documents state the step and neither states a figure.
docs/alpha-engine-prd.md §C8 puts it in the construction's own chain, one step
after the volatility target feature 303 applies and one step before the orders:

    Signal book → IR-weighted combination with shrinkage → volatility
    targeting → position and concentration limits → orders.
    Version-controlled, human-authored, explicitly outside the search space.

docs/nullius-tech-architecture.md §13.1 states the same chain as the live
path's book manager — ``promoted signals → IR-weighted combine (Ledoit-Wolf
shrinkage) → volatility targeting → position & concentration limits → target
weights`` — so this act is the last bound the construction applies before the
order layer consumes the weights.  :func:`rejects_breaching_target_weights` is
its verb: it takes the target weights feature 303 answers and the deployment's
two limits, and **raises** when a target weight breaches either bound, so a
caller that runs it on its last line before handing a book to the order layer
is stopped at the bound rather than at the exchange.

**Two bounds, because they bound two different things.**  A book's *size at a
symbol* and a book's *shape across symbols* are different facts, and each is
free of the other.  Feature 303's act sets the first (its scale is exactly the
gross exposure it holds the book at) and cannot see the second at all: scaling
a book multiplies every weight by one factor, so it leaves the book's internal
proportions exactly where feature 301's ranking put them.  So the two limits
here are genuinely orthogonal and neither subsumes the other, which is what
"breaching *either* bound" states:

* the **per-position limit** bounds each position's size — ``|w_s| ≤
  per_position_limit`` for every symbol the book covers.  A *magnitude*, and
  deliberately: a book's position at a symbol is its *size*, so a short at
  ``-0.30`` breaches a ``0.20`` bound exactly as a long at ``0.30`` does, and
  the fig leaves no route by which a book holds arbitrary size by flipping
  signs.  It is the reading the member already takes of a book's extent
  (:attr:`book.TargetWeights.gross_exposure` is ``Σ_s |w_s|``, the absolute
  sum), applied to one symbol.
* the **concentration limit** bounds the book's shape —
  ``max_s |w_s| / Σ_t |w_t| ≤ concentration_limit``, the largest position's
  share of the book's gross exposure.  A *share*, so it is **scale-free**,
  which is exactly what makes it a second bound rather than a second spelling
  of the first: the figure is invariant under feature 303's scaling, and this
  member's suite pins that (a book and the same book levered to a higher
  target have one concentration and two sizes).  The share lives in
  ``(0, 1]`` for every book that holds anything — it is exactly ``1.0`` when
  the whole book is one name, the most concentrated a book can be, and it
  falls toward ``0`` as the book spreads — so the figure a deployment
  configures has a legible floor and ceiling rather than being an arbitrary
  index.

**Concentration is a whole-book figure here, and the reason is an input this
seam does not carry.**  The everyday meaning of a *concentration limit* is a
bound on the aggregate weight of a **group** of correlated names — one theme,
one sector.  This system has such a grouping (``theme_root``, the axis §11.1
conditions thresholds on), but no feature of this category hands a target
weight set a symbol's theme: feature 301's composite is keyed by symbol and
carries nothing else, and feature 303's act reads exactly that surface.  So a
group-based limit would need a membership map this seam is not handed, and
inventing one — guessing a theme per symbol, or a sector table no document
states — would be this module fabricating the input it judges.  The bound is
therefore stated over the book as a whole, where the figure is computable from
the weights themselves and means exactly what it says; a deployment that wants
a per-theme bound supplies that grouping at the layer that *has* it, one step
downstream, exactly as feature 308's cap takes its figures from the caller.

**Both figures are the deployment's, and neither has a default.**  §C8 and
§13.1 name the step and state no figure for either bound — the documents state
the *form* of the construction's chain, a *discount* on a Kelly fraction
(Appendix B's *"use ≤ ¼ Kelly"*, feature 308's constant) and the *form* of a
bar, but nowhere how large a position may be or how concentrated a book may
get.  Those are a deployment's own risk decisions, so they arrive as
**required** keywords, ``per_position_limit`` and ``concentration_limit``, and
deliberately **with no default**: a module-chosen fallback would be a risk
level no document states, silently applied to every deployment that never
configured one.  This is feature 303's boundary exactly, read on the two
figures one step after its own — and, like its own, structural rather than
remembered: the factory's registration protocol takes no arguments, so no
component could carry a limit and no deployment could set one through the
registry (feature 308 states it from the other side: *"the knob in this
neighbourhood is feature 303's configured volatility target, and it is a
different feature's"*).

**The edge is inclusive on the admitted side, and "breaching" is the word.**
A target weight exactly *at* a limit is admitted and one float above it is
refused — the target *exceeds* the bound, it does not *reach* it — the edge
feature 308 states for its own cap (*"``ceiling`` itself runs, ``ceiling + 1``
does not"*, Appendix B's *"use ≤ ¼ Kelly"* being inclusive on the admitted
side) and the same reading of a bound as a *budget*: spending it exactly is
spending within it.

**A zero limit is answered, and it admits exactly the flat book.**  A
``per_position_limit`` of ``0`` says *no position is to be held* and a
``concentration_limit`` of ``0`` says *the book may not be concentrated at
all*; both are well-formed risk appetites whose honest consequence is the flat
book, the reading feature 308 gives a zero Sharpe (*"a zero Sharpe answers a
zero cap and admits only the flat book"*) and feature 303 gives a zero
configured target (*"*take no risk* is a level whose honest consequence is a
flat book"*).  Refusing them would report a deployment's risk appetite as a
malformed ask.  Every book that holds something has a strictly positive
concentration, so a zero concentration limit admits no book but the flat one —
which is not a special case bolted on, but the same sentence read at its
floor.

**The flat book's concentration is ``0.0``, and that is a reading rather than
a division.**  An all-zero target-weight set is a legitimate value on this
path — feature 303 answers exactly it for a configured target of zero, and
feature 308 admits holding a book flat on its own terms — so this act must
answer a concentration for it.  ``max|w| / Σ|w|`` is ``0/0`` there, and the
member's standing law is that a division by exactly nothing is refused rather
than answered (feature 303's ``flat_book``).  This is the different fact, and
the difference is what the figure *is*: feature 303 refuses a flat **composite**
because the weights it would have to invent are a *decision* nobody made,
while the concentration of a book that holds nothing is a *description* of a
book already decided.  A book at no exposure holds nothing, and nothing is not
concentrated: ``0.0`` is the true floor of a figure bounded above by ``1.0``,
not a fabricated substitute for a missing measurement.  So the share is
answered as ``0.0`` for the flat book, the flat book is *admitted* by both
bounds at every limit of zero or more, and no other book answers ``0.0``
because every book that holds something has a largest position and a gross
exposure, both strictly positive.

**This act bounds; it never reshapes.**  It rejects a breaching book, and it
does not scale a position down, re-weight the composite, re-rank the book or
clamp the concentration to the limit — the stance feature 308's refusal states
in its own words (*"refused rather than scaled down, because lowering a target
the caller asked for would be this member *sizing* a position, and sizing is
the order layer's act rather than a bound's"*).  A module that quietly shrank
the oversized positions would hand the order layer a book nobody chose while
reporting that the caller's book had passed, which is the failure the whole
refusal shape exists to prevent.  The repair is always the caller's: hand
weights inside the bounds.

**What this module does not do.**  It re-opens no information-ratio weight
(feature 301's ranking), applies no volatility target and re-scales nothing
(feature 303's act), shrinks no covariance (302's), bounds no *leverage*
(feature 308's cap — a different bound on a different fact: that one judges
the exposure the whole book is held at, this one judges a position's size and
the book's shape, and neither subsumes the other), rounds no order to a venue's
step or tick (the router's features), persists no rebalance target (feature
309's), measures nothing and opens no store.  It takes the target weights and
the deployment's two limits and answers exactly one question: *does any target
weight breach either bound?*

**No new component, and the layering note.**  The act arrives as free
functions beside the combiner, the way feature 306's guard, feature 307's
companion, feature 308's cap and feature 303's own act sit: its whole input is
a value and two figures the caller already holds, so there is nothing for the
factory to compose and nothing for a deployment to configure *through the
registry* — the two things a deployment configures here reach the *call*, not
the composition.  No ``@register``, no table, no endpoint, no migration, no
seat edit, and no third-party import — ``math``, ``collections``,
``dataclasses``, ``typing`` and the member's own ``.errors`` — so the
factory's scan, which imports this package on every ``create_app()`` to fire
its ``@register``, pays nothing for the act beyond the import it already paid
for the combiner, and the replay path stays import-cheap.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import LimitBreachError, LimitRequestError

__all__ = [
    "CONCENTRATION_LIMIT_CODE",
    "PER_POSITION_LIMIT_CODE",
    "concentration",
    "is_breaching_limits",
    "rejects_breaching_target_weights",
]

#: The code a *per-position* refusal opens with — a target weight sits above
#: the deployment's per-position limit — so the rejection is greppable by the
#: word that names the bound it breached.  Feature 304's sentence mandates no
#: token (it names its subject in prose), so the code is this module's own,
#: minted on the ``leverage_above_quarter_kelly`` / ``flat_book`` /
#: ``missing_changelog_entry`` convention the workspace states for the one
#: refusal an operator greps a deployment log for: *why was this book not
#: handed to the order layer?*  The two bounds carry two codes rather than one
#: shared token, for the reason the router's limiter carries two: the repairs
#: differ — *shrink that position* against *spread the book* — and a reader
#: greps the word for the one they have to fix.  Both open the judgment's
#: messages (:class:`~book.errors.LimitBreachError`); the ask's own facts carry
#: no code, for the reason :class:`~book.errors.LimitRequestError` gives.
PER_POSITION_LIMIT_CODE = "position_above_limit"

#: The code a *concentration* refusal opens with — the book's largest position
#: is a larger share of its gross exposure than the deployment's concentration
#: limit admits — so the rejection is greppable by the word that names the
#: other bound.  See :data:`PER_POSITION_LIMIT_CODE` for why the two bounds are
#: two words.
CONCENTRATION_LIMIT_CODE = "concentration_above_limit"

#: Sentinel for "attribute not present" when reading the target weights'
#: surface, so a value that carries no ``weights`` is distinguished from one
#: that carries ``weights=None`` — a value that omits its weights entirely is
#: not a target-weight set, which is a different report from one that stated
#: its weights as nothing.  The combiner's, the act's and the guard's own
#: ``_MISSING`` discipline, read on this feature's value.
_MISSING = object()


def _ask(
    target_weights: Any,
    per_position_limit: Any,
    concentration_limit: Any,
) -> tuple[dict[str, float], float, float]:
    """The whole ask, read once, in the order every refusal depends on.

    The book first and the two limits after it — the ordering this workspace
    states everywhere: a value that is not a target-weight set is reported as
    such before a limit is even looked at, and *this is not a book* is never
    dressed as *your limit was malformed*.  Both limits are then read in the
    sentence's own order — *"per-position and concentration"* — so an ask that
    malformed both is reported on the first, and a caller fixing one at a time
    is told the bound the sentence names first.

    Spelled once, for the reason :func:`_share` is: the predicate and the
    verdict must refuse identically, and a pair of verbs that read the ask in
    two places could refuse one caller's ask and admit another's.
    """
    weights = _weights_of(target_weights)
    per_position = _validated_limit(
        per_position_limit,
        field="per_position_limit",
        bounds="the per-position limit bounds the size of any one position",
    )
    cap = _validated_limit(
        concentration_limit,
        field="concentration_limit",
        bounds=(
            "the concentration limit bounds the largest position's share of "
            "the book's gross exposure"
        ),
    )
    return weights, per_position, cap


def _validated_limit(value: Any, *, field: str, bounds: str) -> float:
    """Check that ``value`` is one of the deployment's two limits, or refuse it.

    Both limits are the same kind of figure — a finite real of **zero or
    more**, a magnitude the book's own shape is judged against — so they are
    read by one helper; ``field`` and ``bounds`` name which of the two was
    ill-stated and what it bounds, so a message states the fact the caller must
    repair.  The policy is stated once because it *is* one policy: feature 303
    spells two validators for its two figures because their policies differ
    (strictly positive against zero-or-more), and this module has no such
    difference to keep apart.

    Zero is admitted and is the honest floor — *hold no position at all* is a
    well-formed risk appetite whose consequence is the flat book (feature 308's
    reading of a zero Sharpe, feature 303's of a zero configured target), and
    on a zero limit the admissible set is exactly the flat book, because every
    book that holds something has a strictly positive position size and a
    strictly positive concentration.  A *negative* limit is refused, and it is
    the ask's own fact rather than a judgment: a limit is a magnitude, and a
    negative one is a direction — it would admit nothing on either side of the
    book and read a risk bound as a view.  A ``bool`` is refused where a figure
    belongs because ``True`` is ``1`` in Python and a flag where a limit
    belongs would read as *one hundred percent*; ``nan``/``±inf`` are refused
    because they are not bounds — a ``nan`` compares false against everything,
    so a verdict against it would refuse every book while looking like it had
    judged one, and an infinite limit is one nothing can breach.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LimitRequestError(
            f"the {field} is a number — got {value!r} ({type(value).__name__}); "
            f"{bounds}, and a value that is not one states no bound this act "
            "can judge a target weight against"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise LimitRequestError(
            f"the {field} is a finite number — got {value!r}; a non-finite "
            "bound is neither breached nor respected: a nan compares false "
            "against everything it is asked about, so a verdict against it "
            "would refuse every book while looking like it had judged one, and "
            "an infinite limit is one no book can breach"
        )
    if figure < 0.0:
        raise LimitRequestError(
            f"the {field} is zero or more — got {value!r}; {bounds}, and a "
            "negative one is a direction rather than a magnitude — it would "
            "admit nothing on either side of the book, reading a risk bound as "
            "a view. A deployment that wants nothing held asks for a limit of "
            "zero, which admits exactly the flat book"
        )
    return figure


def _weights_of(target_weights: Any) -> dict[str, float]:
    """Read the target weights' ``weights`` mapping, or refuse it as the ask's.

    The surface feature 303's :class:`~book.TargetWeights` carries and this act
    needs — one weight per symbol, the positions the order layer would hold.
    Read duck-typed, so a value that exposes ``weights`` is a target-weight set
    here whatever class composed it (a member never isinstance-gates the value
    a composition seam hands out); the sentinel keeps *this is not a
    target-weight set* apart from *this target-weight set is empty*, which are
    different reports.
    """
    weights = getattr(target_weights, "weights", _MISSING)
    if weights is _MISSING:
        raise LimitRequestError(
            "the limits judge the target weights — got "
            f"{target_weights!r} ({type(target_weights).__name__}), which "
            "carries no ``weights``; hand the target weights feature 303's "
            "apply_volatility_target answers (or any value exposing the same "
            "``weights`` mapping of symbol to weight), and this act will judge "
            "every position and the book's concentration against the "
            "deployment's two limits"
        )
    if not isinstance(weights, Mapping):
        raise LimitRequestError(
            "the target weights are a mapping of symbol to weight — got "
            f"{type(weights).__name__}; a book's positions are read one symbol "
            "at a time and a value that is not a mapping names no book"
        )
    if not weights:
        raise LimitRequestError(
            "the target weights cover at least one symbol — got none; a book "
            "that holds no symbol has no position to bound and no shape to "
            "measure, and an empty weight set would be a book presented to the "
            "order layer as if it were a decision"
        )
    validated: dict[str, float] = {}
    for symbol, weight in weights.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise LimitRequestError(
                "the target weights must be keyed by non-empty symbol names — "
                f"got {symbol!r}; a position cannot be attributed to a symbol "
                "the book does not name"
            )
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise LimitRequestError(
                f"the target weight for symbol {symbol!r} must be a finite real "
                f"— got {weight!r} ({type(weight).__name__}); a position whose "
                "weight is not a number is not a size any limit could bound"
            )
        number = float(weight)
        if not math.isfinite(number):
            raise LimitRequestError(
                f"the target weight for symbol {symbol!r} is not finite "
                f"({weight!r}); a NaN or ±inf would reach the order layer "
                "dressed as a position, and no bound can judge it"
            )
        validated[symbol] = number
    return validated


def _share(weights: Mapping[str, float]) -> tuple[float, float]:
    """The book's gross exposure and its concentration — one spelling, twice.

    ``Σ_s |w_s|`` and ``max_s |w_s| / Σ_t |w_t|``: the two figures the second
    bound is stated over, computed once so :func:`concentration`, the verdict
    and the refusal's own message cannot disagree about either — the discipline
    :func:`book._leverage._cap` states for keeping one module's arithmetic from
    drifting.

    The flat book is the one case with a denominator of exactly nothing, and it
    is answered rather than refused: a book that holds nothing is not
    concentrated, so its share is ``0.0`` — the true floor of a figure bounded
    above by ``1.0`` (see the module docstring).  No other book answers
    ``0.0``, because a book that holds something has a largest position and a
    gross exposure, both strictly positive.
    """
    gross = math.fsum(abs(weight) for weight in weights.values())
    if gross == 0.0:
        return gross, 0.0
    return gross, max(abs(weight) for weight in weights.values()) / gross


@dataclass(frozen=True)
class _Breach:
    """Which bound the target weights breached, and the figures behind it.

    The one reading both public verbs take, so the predicate and the verdict
    cannot disagree about whether a book is inside the limits — the discipline
    :func:`book._changelog._presence` states for its own pair.  ``code`` is
    ``None`` exactly when the book breaches neither bound; ``over_limit`` and
    ``largest`` carry ``(symbol, weight)`` pairs sorted by symbol, so a refusal
    names the positions it is about rather than only that something was wrong.
    """

    #: The code of the bound that was breached, or ``None`` when neither was.
    code: str | None
    #: Every symbol whose position is above the per-position limit, sorted.
    over_limit: tuple[tuple[str, float], ...]
    #: Every symbol holding the largest position, sorted — the figure the
    #: concentration bound is stated over, named so the refusal can say which
    #: position made the book as concentrated as it is.
    largest: tuple[tuple[str, float], ...]
    #: The book's gross exposure, ``Σ_s |w_s|``.
    gross: float
    #: The book's concentration, ``max_s |w_s| / Σ_t |w_t|``.
    share: float
    #: How many symbols the book covers — the extent the gross exposure is a
    #: sum over, stated in the refusal so a caller can see how many names the
    #: share is taken across.
    covered: int


def _judge(
    weights: Mapping[str, float],
    per_position_limit: float,
    concentration_limit: float,
) -> _Breach:
    """Read the two bounds over one book — the one comparison this act is.

    Everything else in this module is spelling: validation, and the sentences
    the refusal states.  The order is the sentence's own — *"per-position and
    concentration"* — so a book that breaches both is refused over its
    positions, which is the local repair, and a caller told about the position
    is never left believing the whole shape was the fault.  Both figures are
    computed either way, so the record :func:`_position_refusal` and
    :func:`_concentration_refusal` read carries the same numbers the verdict
    decided on.

    The edge is ``>`` on both bounds: a weight exactly at a limit is admitted,
    for the reasons the module docstring gives.
    """
    over_limit = tuple(
        sorted(
            (symbol, weight)
            for symbol, weight in weights.items()
            if abs(weight) > per_position_limit
        )
    )
    gross, share = _share(weights)
    largest_position = max(abs(weight) for weight in weights.values())
    largest = tuple(
        sorted(
            (symbol, weight)
            for symbol, weight in weights.items()
            if abs(weight) == largest_position
        )
    )
    covered = len(weights)
    if over_limit:
        return _Breach(
            PER_POSITION_LIMIT_CODE, over_limit, largest, gross, share, covered
        )
    if share > concentration_limit:
        return _Breach(
            CONCENTRATION_LIMIT_CODE, (), largest, gross, share, covered
        )
    return _Breach(None, (), largest, gross, share, covered)


def _position_refusal(breach: _Breach, limit: float) -> str:
    """The per-position refusal's own sentence — the positions and the repair.

    Spelled once so :func:`rejects_breaching_target_weights` raises one message
    for this bound, and it names *every* over-limit position rather than the
    first, because they share one repair and a caller that lowered only the one
    it was told about would come back to the same refusal.  It states the
    magnitude the bound is stated over — the fact that makes a large short as
    much a breach as a large long — and the repair that is real: *hand weights
    at or below the limit*, because this module refuses rather than scales a
    position down (feature 308's stance on the same member's other bound).
    """
    spelled = ", ".join(f"{symbol!r} at {weight!r}" for symbol, weight in breach.over_limit)
    return (
        f"{PER_POSITION_LIMIT_CODE}: a target weight is above the per-position "
        f"limit — {len(breach.over_limit)} of the book's positions sit above "
        f"{limit!r}: {spelled}. docs/alpha-engine-prd.md §C8 states the "
        "construction's chain as \"Signal book → IR-weighted combination with "
        "shrinkage → volatility targeting → position and concentration limits "
        "→ orders\", and this is the first of the two bounds it names: no "
        "single position may be held above the size the deployment configured. "
        "The position's size is its magnitude, so a short at -0.30 breaches a "
        "0.20 limit exactly as a long at 0.30 does — the bound is a size, not "
        "a direction, and §C8's chain applies it to the weights feature 303 "
        "returned rather than to the views behind them. The repair is the "
        "caller's: hand target weights whose positions sit at or below the "
        "limit. This act refuses rather than scales a position down, because "
        "lowering a target the caller asked for would be this member sizing a "
        "position rather than bounding one, and sizing is the order layer's "
        "act; a target weight exactly at the limit is admitted, the bound "
        "being a budget rather than a floor"
    )


def _concentration_refusal(breach: _Breach, limit: float) -> str:
    """The concentration refusal's own sentence — the shape and the repair.

    Spelled once so :func:`rejects_breaching_target_weights` raises one message
    for this bound, and it states the figures the caller needs to see the
    arithmetic rather than take it on faith: the largest position (named, with
    its weight), the gross exposure the share is taken over, the share itself
    and the limit.  The repair is the one that exists — *hold more names*, i.e.
    hand a book whose largest position is a smaller share of its gross — and
    the message says what this module will not do about it: it neither
    re-weights the book (feature 301's ranking) nor scales it (feature 303's
    target), because reshaping a caller's book would be this member sizing it
    rather than bounding it.
    """
    spelled = ", ".join(f"{symbol!r} at {weight!r}" for symbol, weight in breach.largest)
    return (
        f"{CONCENTRATION_LIMIT_CODE}: the book is more concentrated than the "
        f"concentration limit — its largest position ({spelled}) is "
        f"{breach.share!r} of the book's gross exposure, above the limit "
        f"{limit!r}. The gross exposure is Σ_s |w_s| = {breach.gross!r} over "
        f"the {breach.covered} symbols the book covers, so the share "
        "is the largest position's weight over the whole book's, and it is "
        "scale-free: feature 303's target scaling multiplies every weight by "
        "one factor and leaves this figure exactly where the ranking put it. "
        "docs/alpha-engine-prd.md §C8 states the construction's chain as "
        "\"Signal book → IR-weighted combination with shrinkage → volatility "
        "targeting → position and concentration limits → orders\", and this is "
        "the second of the two bounds it names — a bound on the book's shape "
        "rather than on a position's size, which is why a book inside the "
        "per-position limit can still breach this one. The repair is the "
        "caller's: hand target weights whose largest position is a smaller "
        "share of the book — hold more names. This act neither re-weights the "
        "book (the information-ratio weighting is feature 301's, and a bound "
        "that re-ranked would be answering a question about the combiner from "
        "inside a verdict) nor scales it down (feature 303's act), because "
        "reshaping a caller's book would be this member sizing it rather than "
        "bounding it; a concentration exactly at the limit is admitted"
    )


def concentration(target_weights: Any) -> float:
    """The book's concentration — the figure the second bound is stated over.

    ``max_s |w_s| / Σ_t |w_t|``: the largest position's share of the book's
    gross exposure, read over the same duck-typed ``weights`` surface the
    verdict reads.  The figure feature 304's concentration limit bounds, and
    the one a caller or an operator consults to see *how concentrated* a book
    is without running the verdict — the shape
    :func:`book.leverage_cap` takes for feature 308's own figure one feature
    over: the number a bound turns on, answered as a pure function of a value
    the caller already holds.

    It lives in ``(0, 1]`` for every book that holds anything: exactly ``1.0``
    when the whole book is one name (the most concentrated a book can be, and
    the figure at which a concentration limit of ``1.0`` is exactly reached),
    falling toward ``0`` as the book spreads.  It is **scale-free** — a book
    and the same book levered to a higher volatility target have one
    concentration and two sizes — which is precisely what makes the
    concentration bound a different bound from the per-position one, and it is
    why this act is applied after feature 303's scaling without either feature
    importing the other.

    The flat book answers ``0.0``: a book that holds nothing is not
    concentrated, and ``0.0`` is the true floor of the figure rather than a
    fabricated substitute for the ``0/0`` the ratio would otherwise be (see the
    module docstring for why this is not feature 303's ``flat_book`` refusal
    read on a second divisor).  Every book that holds something answers a
    strictly positive figure, so ``0.0`` means exactly one thing.

    Refuses, in the same order and with the same class as the verdict, the
    ask's own facts: a value carrying no ``weights``, a non-mapping, a book
    covering no symbols, a blank symbol name and a non-finite weight
    (:class:`~book.errors.LimitRequestError`).
    """
    return _share(_weights_of(target_weights))[1]


def is_breaching_limits(
    target_weights: Any,
    *,
    per_position_limit: Any,
    concentration_limit: Any,
) -> bool:
    """Answer whether a target weight breaches either bound — the fact alone.

    The read-only spelling of feature 304's judgment: the same ask validation,
    the same one comparison, and no refusal.  ``True`` exactly when some
    position's magnitude is above ``per_position_limit`` or the book's
    concentration is above ``concentration_limit``; ``False`` when both bounds
    hold — the path §C8's chain names, where the target weights the
    construction has built are inside the limits the deployment configured.

    The shape :func:`book.is_agent_authored` and
    :func:`book.is_missing_changelog_entry` take for their own facts: validate
    the ask, answer a fact, and let the caller decide what to do with it.  A
    caller that wants the refusal calls
    :func:`rejects_breaching_target_weights`; a caller that only wants to
    *know* (a report, an audit line, a test) calls this, and the two cannot
    disagree because they read the bounds once, in :func:`_judge`.

    Refuses what the verdict refuses, in the same order, with the same class:
    a value that is not a target-weight set, and a limit that is not a finite
    real of zero or more, before any bound is read.
    """
    weights, per_position, cap = _ask(
        target_weights, per_position_limit, concentration_limit
    )
    return _judge(weights, per_position, cap).code is not None


def rejects_breaching_target_weights(
    target_weights: Any,
    *,
    per_position_limit: Any,
    concentration_limit: Any,
) -> None:
    """Refuse a book that breaches either bound — feature 304's call.

    The one judgment for feature 304's sentence: the target weights feature 303
    answers — a :class:`book.TargetWeights`, or any value exposing the same
    ``weights`` mapping of symbol to weight; a member never isinstance-gates
    the value a composition seam hands out, so the surface is read, not the
    type — and the deployment's two limits in, and either the book proceeds to
    the order layer or it is refused.  It **raises**
    :class:`~book.errors.LimitBreachError` when a target weight breaches either
    bound, so a caller that runs it on its last line before handing a book over
    is stopped at the bound rather than at the exchange.

    The steps, in the order they must happen, each refusal leaving no value:

    (1) read the target weights' ``weights``, refusing a value that carries
    none, a non-mapping, a book covering no symbols, a blank symbol name and a
    weight that is not a finite real — the ask's own facts;
    (2) validate the two limits, each a finite real of zero or more — also the
    ask's own facts, refused with :class:`~book.errors.LimitRequestError`
    **before any book is judged**, the ordering every verdict and act in this
    workspace states: a caller that mis-stated a limit is told *what to fix*,
    never told its book is too concentrated;
    (3) read the per-position bound — every position's magnitude against
    ``per_position_limit``, refused with :class:`~book.errors.LimitBreachError`
    opening with :data:`PER_POSITION_LIMIT_CODE` and naming every position above
    it;
    (4) read the concentration bound — ``max_s |w_s| / Σ_t |w_t|`` against
    ``concentration_limit``, refused with the same class opening with
    :data:`CONCENTRATION_LIMIT_CODE` and naming the largest position, the gross
    exposure, the share and the limit.

    A book inside both bounds returns without raising.  The two judgments fire
    in the sentence's own order — *"per-position and concentration"* — so a
    book that breaches both is refused over its positions, the local repair.

    **The edge is inclusive, and "breaching" is the sentence's word.**  A
    weight exactly at a limit is admitted and one float above it is refused —
    the edge feature 308 states for its cap, read on a different bound, and the
    same reading of a limit as a budget: spending it exactly is spending within
    it.

    **A zero limit is answered, and a flat book is admitted by it.**  ``0`` is
    a well-formed risk appetite whose consequence is the flat book, so a book
    at no exposure passes both bounds at every limit of zero or more — every
    position is ``0`` and the concentration of a book that holds nothing is
    ``0.0``, not a division by nothing (see :func:`concentration`).  Only a
    *malformed* limit — a negative one, a ``bool``, a non-finite real, or a
    value that is not a number — is refused, and as the ask's own fact.
    """
    weights, per_position, cap = _ask(
        target_weights, per_position_limit, concentration_limit
    )
    breach = _judge(weights, per_position, cap)
    if breach.code == PER_POSITION_LIMIT_CODE:
        raise LimitBreachError(_position_refusal(breach, per_position))
    if breach.code == CONCENTRATION_LIMIT_CODE:
        raise LimitBreachError(_concentration_refusal(breach, cap))
