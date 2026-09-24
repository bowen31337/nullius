"""The final target weights — feature 305: the one output the order layer reads.

app_spec.xml, "Portfolio Book Construction", feature 305: *System returns
final target weights as the only output consumed by the order layer.*  Both
documents put this fact at the foot of the construction's own chain, and both
state it as the chain's last arrow rather than as another step:

    Signal book → IR-weighted combination with shrinkage → volatility
    targeting → position and concentration limits → **orders**.
    Version-controlled, human-authored, explicitly outside the search space.

docs/alpha-engine-prd.md §C8 writes the chain through to *"orders"* and
docs/nullius-tech-architecture.md §13.1 writes the same chain through to
*"target weights"* — one chain named at its two ends — and §13.2 opens the
execution engine on the other side of that seam.  So this feature adds no
arithmetic: every act the sentence depends on already exists in this member
(feature 301 combines, feature 303 scales, feature 304 bounds) and *nothing in
the sentence adds one*.  What the sentence states is a **shape** the
construction's answer must have: one value — the final target weights — is what
the order layer consumes, and it is the *only* thing it consumes.

**Why the shape is the feature.**  A chain whose every step returned its own
record would hand the order layer three or four things to reconcile — a
composite, a gross book, a scale, two volatility figures, a set of weights —
and the order layer would then have to decide which of them is the book: that
is the construction's job performed one layer down, with no bound re-run and no
document stating which record wins.  The sentence forecloses it by naming one
output.  :class:`FinalTargetWeights` is that output, and it publishes the
weights the construction built — the same mapping :class:`book.TargetWeights`
carries — together with the symbols they are held at, so a caller handed the
final weights has everything the chain's next step reads and nothing else.  The
composite (feature 301), the gross-normalized book, the scale and the two
volatility figures (feature 303) and the limits the book was judged against
(feature 304) are the construction's *working*: they stay where the
construction computed them, reachable on the record the act answered, never
published as this seam's output.

**A claim, not a second computation.**  :func:`final_target_weights` takes the
bounded target weights and answers the final set.  It re-runs **no** arithmetic
— no re-normalization, no re-scaling, no re-ranking, no rounding, no clamping —
because every one of those would be a second answer to a question feature 301,
303 or 304 already answered, and two answers to one question is exactly the
drift this member's every other seam refuses.  :meth:`FinalTargetWeights.weight`
therefore returns the very float feature 303 scaled and feature 304 bounded,
which is what *"returns final target weights"* means when read as the last
arrow of a chain rather than as another act in it.

**The order layer consumes this and nothing else, so the value says so.**
:meth:`FinalTargetWeights.consumed_by_order_layer` answers ``True`` — the
sentence's own claim, made answerable off the value a caller holds — and
:func:`is_only_output` reads the sentence's *only* over the construction's
whole surface: handed the value meant for the orders and everything else the
caller holds (the composite, the target weights, a scale, a bound's record), it
answers ``True`` exactly when the value meant for the orders declares itself a
published final weight set and **no other** value declares itself one too.
:func:`assert_only_output` is the same reading as a verdict, raising
:class:`~book.errors.OrderLayerOutputError` on the sentence's own code.  Both
read that declaration **duck-typed**, off each value's own ``kind`` word, so a
caller's own spelling of a published book is judged by the same law as this
member's record and no class is isinstance-gated at the seam — which matters
here more than elsewhere, because the loader imports every member under a
synthetic name, so a value this process composed may be a second class object.

**Why the construction's working is admissible and a second published set is
not.**  The working is not contraband: a caller may hold the composite, the
scale and the target weights, and features 303 and 304's records are where
those figures *belong*.  What the sentence forecloses is a second **published**
set — two records both claiming to be the order layer's instruction — because
then the order layer would have to choose between them, which is the
construction's own act done one layer down with no bound re-run.  So the
reading counts declarations of the one word, not values: exactly one, and it is
the one meant for the orders.

**Absence is not zero, read on the last step of the chain.**  A value handed to
:func:`final_target_weights` that carries no ``weights`` is refused rather than
treated as a flat book; a published set covering no symbols is refused rather
than passed on as an empty instruction; and a weight that is not a finite real
is refused, because a ``nan`` or ``±inf`` would reach the venue dressed as a
position.  None of those is a *book* — they are the absence of one — and the
order layer's instruction must be a book.  A book that holds *nothing* is a
different fact and is **answered**: feature 303's zero-target answer is every
weight ``0.0`` and feature 304 admits it at every limit of zero or more, so
*hold nothing* is an instruction the construction is entitled to publish, where
no book at all is not.

**Where this act does not reach.**  It re-opens no information-ratio weight
(301), applies no volatility target and re-scales nothing (303), shrinks no
covariance (302), re-judges no bound (304), bounds no leverage (308), rounds no
order to a venue's step or tick, sizes no order, prices nothing, chooses no
venue and formats no ``client_order_id`` — every one of those belongs to the
router's own features, which own ``LOT_SIZE`` / ``NOTIONAL`` / ``PRICE_FILTER``
rounding and the venue's filters (§13.2).  This act takes the book the
construction built and publishes it as the one output the chain's next step
reads, which is the whole of what its sentence says.

**No new component, and the layering note.**  The act arrives as free functions
beside the combiner, the way feature 303's target, feature 304's limits,
feature 306's guard, feature 307's companion and feature 308's cap sit: its
whole input is a value the caller already holds, so there is nothing for the
factory to compose and nothing for a deployment to configure.  No ``@register``,
no table, no endpoint, no migration, no seat edit, and no third-party import —
``collections``, ``dataclasses``, ``math``, ``typing`` and the member's own
``.errors`` — so the factory's scan, which imports this package on every
``create_app()`` to fire its ``@register``, pays nothing for the act beyond the
import it already paid for the combiner, and the replay path stays
import-cheap.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar

from .errors import FinalWeightsRequestError, OrderLayerOutputError

__all__ = [
    "ANNEXED_RECORD_CODE",
    "NO_BOOK_CODE",
    "PUBLISHED_KIND",
    "FinalTargetWeights",
    "assert_only_output",
    "final_target_weights",
    "is_only_output",
]

#: The code an ask refusal opens with when what the caller handed over is not a
#: book at all — a value carrying no ``weights``, a non-mapping, a set covering
#: no symbols, or a value meant for the orders that declares itself nothing.
#: Greppable by the word that names what is missing rather than what is wrong
#: with it.  Feature 305's sentence mandates no token (it names its subject in
#: prose), so the code is this module's own, minted on the ``flat_book`` /
#: ``position_above_limit`` / ``missing_changelog_entry`` convention the
#: workspace states for the one refusal an operator greps a deployment log for:
#: *why did no instruction reach the order layer?*  It is deliberately not the
#: code of the bound one step upstream: ``position_above_limit`` tells a caller
#: the book was real and too large, while ``no_book`` tells it there was no book
#: to publish — two different repairs.
NO_BOOK_CODE = "no_book"

#: The code the one judgment opens with — a second record declaring itself the
#: order layer's output is annexed to the first.  This is the sentence's own
#: word made greppable: the order layer consumes the final target weights as the
#: **only** output, so two published sets leave it choosing between them, and an
#: operator greps this word to find out *what else reached the orders*.
ANNEXED_RECORD_CODE = "annexed_record"

#: The word the final target weights declare themselves under, published as
#: :attr:`FinalTargetWeights.kind` and read duck-typed off any value handed to
#: :func:`is_only_output` — a caller's own spelling of a published book declares
#: itself the same way, so the seam gates on the declaration rather than on the
#: class.
PUBLISHED_KIND = "final_target_weights"

#: Sentinel for "attribute not present", so a value that carries no ``weights``
#: is distinguished from one that carries ``weights=None``: a value that omits
#: its weights entirely is not a book the construction could publish, which is a
#: different report from one that stated its weights as nothing.  The
#: combiner's, the act's, the limits' and the guard's own ``_MISSING``
#: discipline, read on this feature's value.
_MISSING = object()


def _book_of(target_weights: Any) -> dict[str, float]:
    """Read a value's ``weights`` as the book to publish, or refuse it.

    The surface feature 303's :class:`~book.TargetWeights` carries and this act
    publishes — one weight per symbol, the final positions the order layer would
    hold.  Read duck-typed, so a value exposing ``weights`` is a book here
    whatever composed it (a member never isinstance-gates the value a
    composition seam hands out), and the sentinel keeps *this is not a book*
    apart from *this book covers no symbols* — different repairs, so different
    reports.

    Every scalar check is the shape this member's other readers state: a
    ``bool`` is a flag where a magnitude belongs, and a ``nan`` / ``inf`` weight
    is not a size any venue could hold.  A book whose weights are all zero is
    **not** refused here: *hold nothing* is a decision the construction is
    entitled to publish (feature 303 answers exactly that set for a zero
    configured target, and feature 304 admits it at every limit of zero or
    more), and refusing it would report a risk appetite's own consequence as a
    malformed ask.  It is named :data:`NO_BOOK_CODE` wherever it fails, because
    each of these failures means the same thing to the caller: what it meant to
    hand the order layer is not a book.
    """
    weights = getattr(target_weights, "weights", _MISSING)
    if weights is _MISSING:
        raise FinalWeightsRequestError(
            "the final target weights are the construction's book — got "
            f"{target_weights!r} ({type(target_weights).__name__}), which "
            f"carries no ``weights`` ({NO_BOOK_CODE}); hand the bounded target "
            "weights the construction built (feature 303's "
            "apply_volatility_target answer, judged by feature 304's limits), "
            "or any value exposing the same ``weights`` mapping of symbol to "
            "weight, and this act will publish it as the one output the order "
            "layer consumes"
        )
    if not isinstance(weights, Mapping):
        raise FinalWeightsRequestError(
            "the final target weights are a mapping of symbol to weight — got "
            f"{type(weights).__name__} ({NO_BOOK_CODE}); the order layer holds a "
            "book one symbol at a time, and a value that is not a mapping names "
            "no book to publish"
        )
    if not weights:
        raise FinalWeightsRequestError(
            "the final target weights cover at least one symbol — got none "
            f"({NO_BOOK_CODE}); a published book covering no symbols is an "
            "empty instruction, which is the absence of a book rather than a "
            "book held flat — a flat book is every symbol weighted 0.0, and "
            "that is a decision this act does publish"
        )
    validated: dict[str, float] = {}
    for symbol, weight in weights.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise FinalWeightsRequestError(
                "the final target weights must be keyed by non-empty symbol "
                f"names — got {symbol!r}; the order layer routes an instruction "
                "to a symbol, and a position cannot be attributed to a name the "
                "book does not carry"
            )
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise FinalWeightsRequestError(
                f"the final target weight for symbol {symbol!r} must be a "
                f"finite real — got {weight!r} ({type(weight).__name__}); a "
                "weight that is not a number is not a size any venue could hold, "
                "and the order layer would have to invent one"
            )
        number = float(weight)
        if not math.isfinite(number):
            raise FinalWeightsRequestError(
                f"the final target weight for symbol {symbol!r} is not finite "
                f"({weight!r}); a NaN or ±inf would reach the venue dressed as a "
                "position, and no rounding to a venue's step size could make one "
                "of it"
            )
        validated[symbol] = number
    return validated


@dataclass(frozen=True)
class FinalTargetWeights:
    """The final target weights — feature 305's answer, and the chain's output.

    The one value the sentence says the order layer consumes: the book the
    construction built, published as an instruction.  It carries the weights
    themselves — the same mapping :class:`book.TargetWeights` holds, and for a
    record built by :func:`final_target_weights` the *same floats*, because this
    act re-runs no arithmetic — and answers the symbols and the gross exposure
    the instruction is stated over, so a caller handed the final weights has
    everything the chain's next step reads.

    Frozen for the reason :class:`book.CompositeBook`,
    :class:`book.TargetWeights` and :class:`book.PromotedSignal` are: these are
    the weights the order layer holds, and a value that could move after it was
    read would be a book that changed beneath the instruction that consumes it.
    On *this* record that guarantee carries the sentence's own subject, because
    feature 305 is precisely the claim that what the order layer reads is
    *final*: a published set a later edit could re-scale would be a rebalance
    nobody decided, and it would be worse here than one step upstream, since the
    order layer has no bound to re-run and no act to re-apply — nothing
    downstream could catch it.

    The record is a check rather than a claim.  Construction enforces the
    sentence's own terms:

    * every :attr:`weights` entry is a finite real, so what reaches the order
      layer is a size it can round to a venue's step size rather than a value no
      venue could hold;
    * :attr:`weights` covers at least one symbol — a published set with no
      symbols is an empty instruction, and an empty instruction is not a book;
    * :attr:`kind` is this member's own constant rather than a field, so a
      record cannot be built that declares itself something else and then
      reaches the order layer through :func:`is_only_output`'s own gate.  A
      published book is the only thing this class can be.

    It deliberately carries nothing else.  The composite, the gross-normalized
    book, the scale, the two volatility figures and the limits the book was
    judged against are the construction's working; the sentence's *only* is what
    keeps them out of the order layer's instruction, and they remain reachable
    on the record the act answered, which is where the construction computed
    them.
    """

    #: The final target weights — the book the order layer holds, keyed by
    #: symbol in sorted order so two publications of the same book answer
    #: identical values.
    weights: Mapping[str, float]
    #: The word this record declares itself under, read by
    #: :func:`is_only_output` off any value handed to it.  A constant rather
    #: than a field, so the declaration cannot be hand-set to something else.
    kind: ClassVar[str] = PUBLISHED_KIND

    def weight(self, symbol: str) -> float:
        """The final weight for one symbol — the order layer's figure for it.

        Refuses with :class:`~book.errors.FinalWeightsRequestError` a symbol the
        book does not cover, rather than answering a fabricated zero: a symbol
        the book carries no weight for is not a symbol this instruction routes
        to, and a zero would read to the order layer as *hold none of it* — a
        position decision the construction never made.  The message opens with
        the same ``uncovered_symbol`` word feature 301's
        ``CompositeBook.target_score`` and feature 303's
        :meth:`book.TargetWeights.weight` answer with, because it is the same
        fact about the same surface read one step further along the chain.
        """
        try:
            return self.weights[symbol]
        except KeyError:
            raise FinalWeightsRequestError(
                f"uncovered_symbol: the final target weights hold no weight for "
                f"symbol {symbol!r}; the book covers {sorted(self.weights)}"
            ) from None

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols the published book is held at, sorted.

        Derived from :attr:`weights` rather than stored, so it can never
        disagree with the book it summarises (the discipline
        :attr:`book.TargetWeights.gross_exposure` states for its own derived
        figure).  Exposed because it is what the order layer routes over: the
        instruction names a set of symbols, and a caller that wants to know
        *which* without walking the mapping reads this.
        """
        return tuple(sorted(self.weights))

    @property
    def gross_exposure(self) -> float:
        """The book's gross exposure, ``Σ_s |w_s|`` — the published size.

        Derived, like :attr:`symbols`, and for the same reason.  It is the
        figure the chain's next step is stated over — §13.2's engine holds a
        book of this size — and the same number feature 303 exposes and feature
        308's cap judges, answered here so a consumer of *this* record needs no
        second value to read it.  A flat book's gross exposure is ``0.0``, which
        is the honest reading of *hold nothing* rather than a missing
        measurement: the weights exist and they sum to nothing.
        """
        return math.fsum(abs(weight) for weight in self.weights.values())

    def consumed_by_order_layer(self) -> bool:
        """Answer the sentence in its own terms: is this what the orders consume?

        ``True`` for every well-stated final target weights, and it answers
        ``True`` because that is what this record *is*: feature 305's output,
        the one value the sentence says the order layer reads.  It is a method
        rather than a field so the claim is read off the value a caller holds
        rather than about the class, the shape
        :func:`book.is_breaching_limits` and :func:`book.is_agent_authored` take
        for their own facts — and unlike those, no argument of this record's can
        make it answer otherwise, because the sentence's shape is what the act
        that built it enforced: a value that is not this one never becomes a
        :class:`FinalTargetWeights` at all.
        """
        return True

    def __post_init__(self) -> None:
        # object.__setattr__ where the frozen constructor would normalize: this
        # value validates and freezes, like CompositeBook and TargetWeights.
        # The weights are read and validated by the same reader the act uses, so
        # a hand-built record and a published one cannot be judged differently.
        object.__setattr__(self, "weights", MappingProxyType(_book_of(self)))


def final_target_weights(target_weights: Any) -> FinalTargetWeights:
    """Publish the construction's book as the final target weights — 305's act.

    Feature 305's verb: *System returns final target weights as the only output
    consumed by the order layer.*  ``target_weights`` is the book the
    construction built — a :class:`book.TargetWeights`, or any value exposing
    the same ``weights`` mapping of symbol to weight; a member never
    isinstance-gates the value a composition seam hands out, so the surface is
    read, not the type — and the answer is a frozen
    :class:`FinalTargetWeights` carrying the weights the order layer holds
    *unchanged*.

    **It re-runs no arithmetic, and that is the feature.**  The chain's earlier
    steps have already happened by the time a caller reaches here: feature 301
    combined the promoted signals, feature 303 normalized and scaled the
    composite to the configured annualized volatility, and feature 304 judged
    the result against the deployment's two bounds.  Publication is the last
    arrow of §C8's chain, so this act adds no re-normalization, no re-scaling,
    no re-ranking, no rounding and no clamping: a second answer to a question an
    earlier step answered is exactly the drift the sentence's *only*
    forecloses, and :meth:`FinalTargetWeights.weight` returns the very float the
    construction produced.

    The steps, in the order they must happen, each refusal leaving no value:

    (1) read the book's ``weights``, refusing a value that carries none
    (:data:`NO_BOOK_CODE`), a non-mapping, and a book covering no symbols — the
    ask's own facts;
    (2) read each symbol and weight, refusing a blank symbol name and a weight
    that is not a finite real, **before anything is published** — the ordering
    every verdict and act in this workspace states: a caller that handed a
    malformed book is told *what to fix*, never handed a half-formed
    instruction;
    (3) answer the frozen :class:`FinalTargetWeights`, whose construction
    re-checks the same facts about the same fields through the same reader.

    **A book held flat is answered.**  Every weight ``0.0`` is feature 303's own
    answer for a configured target of zero, and feature 304 admits it at every
    limit of zero or more: *hold nothing* is an instruction the construction is
    entitled to publish, and this act publishes it.  That is a different fact
    from a value carrying no weights, an empty book and a malformed weight —
    those are the *absence* of a book and are refused as the ask's own facts.
    Absence is not zero on this step exactly as it is not one step upstream.

    Deterministic and order-independent: the weights are read once and emitted
    sorted, no figure is derived, and the act holds no state between calls — two
    calls over the same book answer identical values.
    """
    book = _book_of(target_weights)
    return FinalTargetWeights(weights={symbol: book[symbol] for symbol in sorted(book)})


def _asserts_final_target_weights(value: Any) -> bool:
    """Answer whether one value declares itself a published final weight set.

    Read duck-typed off the value's own ``kind``, with the sentinel keeping an
    *omitted* declaration apart from one that declared itself something else
    (both answer ``False`` here, but the sentinel is what stops a record
    carrying ``kind=None`` from being read as a record that never spoke).  A
    caller's own spelling of a published book is judged by exactly the word this
    member's record carries, so the seam gates on the declaration rather than on
    the class — which is what makes it survive the loader importing this member
    under a synthetic name, where a value composed in this process may be a
    second class object that no ``isinstance`` here would recognise.
    """
    kind = getattr(value, "kind", _MISSING)
    if kind is _MISSING:
        return False
    return bool(kind == PUBLISHED_KIND)


def _annexed(published: Any, also_handed: tuple[Any, ...]) -> list[Any]:
    """Settle the ask and count the published sets among the values handed in.

    The one reading both public verbs take, so the predicate and the verdict
    cannot disagree about whether a second published set is in the instruction
    — the discipline :func:`book._limits._judge` states for its own pair.  The
    ask's own facts settle first, before any count is taken: a caller that
    handed no book is told *what to fix* rather than told its instruction
    carried two published sets.

    Returns the values declaring themselves published final weight sets
    *besides* ``published``, in the order handed, so the refusal names them.

    **Distinct by identity, not by value.**  The sentence counts *outputs*, not
    repetitions of one: a caller that hands the same record twice — the whole
    construction's surface passed through whole, a value listed beside itself by
    a comprehension — has still published one set, and refusing it would report
    a caller's own bookkeeping as a second instruction.  Two differently-built
    records holding equal weights *are* two outputs and are caught, which is why
    this is ``is not`` rather than an equality test: the copies an earlier
    feature's act answered are distinct values even when they are equal, and
    those are exactly the second instruction the sentence forecloses.
    """
    if not _asserts_final_target_weights(published):
        raise FinalWeightsRequestError(
            f"{NO_BOOK_CODE}: the value meant for the order layer is not the "
            f"final target weights — it is {published!r} "
            f"({type(published).__name__}), which declares no {PUBLISHED_KIND!r} "
            "kind. Feature 305 states that the final target weights are the only "
            "output consumed by the order layer, so the instruction must be that "
            "value: publish the construction's book with final_target_weights"
        )
    return [
        value
        for value in also_handed
        if value is not published and _asserts_final_target_weights(value)
    ]


def is_only_output(published: Any, *also_handed: Any) -> bool:
    """Answer the sentence's *only* over the construction's whole surface.

    Feature 305's fact, read as a predicate: *the final target weights are the
    only output consumed by the order layer.*  ``published`` is the value a
    caller means to hand the order layer; ``also_handed`` is everything else the
    construction produced that the caller still holds — the composite feature
    301 answered, the target weights feature 303 answered, a scale, a gross
    book, a bound's record.  ``True`` exactly when the value meant for the
    orders declares itself a published final weight set and **no other** value
    handed declares itself one too.

    **A value listed beside itself is not a second output.**  The sentence
    counts outputs, not repetitions: handing the same record twice — the whole
    surface passed through whole, a value repeated by a comprehension — is
    still one published set, and the reading is by identity so it is not
    mistaken for two (see :func:`_annexed`).  Two differently-built records
    holding equal weights *are* two outputs and are caught: an earlier feature's
    act answering a copy is a distinct value, and that is exactly the second
    instruction the sentence forecloses.

    The shape :func:`book.is_breaching_limits` and
    :func:`book.is_missing_changelog_entry` take for their own facts: settle the
    ask, answer a fact, and let the caller decide what to do with it.  A caller
    that wants the refusal calls :func:`assert_only_output`; a caller that only
    wants to *know* (a report, an audit line, a test) calls this, and the two
    cannot disagree because they settle the ask and count the declarations once,
    in :func:`_annexed`.

    Refuses what the verdict refuses, in the same order, with the same class:
    a value meant for the orders that declares itself no published book at all
    is refused as the ask's own fact
    (:class:`~book.errors.FinalWeightsRequestError`, opening with
    :data:`NO_BOOK_CODE`) before any count is taken.  A second published set is
    **not** refused here — that is the sentence's judgment, and it belongs to
    the verdict; this answers ``False`` for it, which is honestly the fact.

    **Why the construction's working is not counted.**  The composite, the
    gross book, the scale and the target weights are values a caller may hold
    beside the published set — those records are where the construction's
    arithmetic belongs, and the sentence forecloses a second published
    *instruction*, not the working that produced the first.  So this counts
    declarations of the one word, not values.
    """
    return not _annexed(published, also_handed)


def assert_only_output(published: Any, *also_handed: Any) -> None:
    """Refuse anything but one published set reaching the order layer — 305's call.

    The verdict spelling of :func:`is_only_output`: the same ask settlement, the
    same count of declarations, and a raise instead of a ``bool``, so a caller
    that runs it on its last line before handing a book to the order layer is
    stopped at this seam rather than at the venue.  ``None`` on the path feature
    305 states — one published final target weights, with the construction's
    working beside it — the return the guard's, the companion's, the limits' and
    the cap's verdicts all state for theirs.

    The one judgment the sentence mints is
    :class:`~book.errors.OrderLayerOutputError`, opening with
    :data:`ANNEXED_RECORD_CODE` and naming every annexed record: two published
    sets leave the order layer choosing between them, which is the
    construction's own act performed one layer down with no bound re-run.  The
    repair is the caller's — *hand the order layer exactly one published set* —
    because this module reconciles nothing and chooses nothing.

    The ask's own facts are refused by the shared read, so a caller that handed
    no book meets :class:`~book.errors.FinalWeightsRequestError` and never this
    judgment — the ordering every verdict in this workspace states.  The two
    classes are this feature's own siblings under the member's base, and they
    are two rather than two codes on one because the caller's position differs:
    the first is an ask that named no book, the second is a real book in a
    malformed instruction.  That is the test feature 304 states for its own two
    codes, read the other way — its two bounds gather under one class because
    the repairs differ while the caller's position does not, and these two
    separate because the caller's position does.
    """
    annexed = _annexed(published, also_handed)
    if annexed:
        raise OrderLayerOutputError(
            f"{ANNEXED_RECORD_CODE}: {len(annexed)} further record(s) declare "
            f"themselves {PUBLISHED_KIND!r} beside the one meant for the order "
            f"layer — {annexed!r}. Feature 305 states that the final target "
            "weights are the *only* output consumed by the order layer, and two "
            "published sets leave the order layer choosing between them, which "
            "is the construction's own act performed one layer down with no "
            "bound re-run. The construction's working — the composite feature "
            "301 answered, the target weights feature 303 answered, their "
            "figures — is not a second output and may be held beside this one; "
            "the repair is to hand the order layer exactly one published set"
        )
