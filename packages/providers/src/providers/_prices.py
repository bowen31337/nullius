"""Feature 2 of additions_spec_llm_usage_tracking.xml: a dated, versioned price table.

*System prices a call from a dated, versioned price table, so that
estimate_cost(model, usage) returns a USD figure or None, never a guessed
price.*  The addition's summary names the defect this closes: an operator
asked how much a running campaign had spent and the system could not say,
because nothing it already carries is a *price* — :class:`providers.Usage`
is a token count, and a token count is not a dollar figure until something
states the rate it is billed at.  This module is that something, and the
feature's own word is the discipline: a *price table*, not a formula,
because a rate card is a fact a vendor publishes on a date, not a function
this package could derive.

Why a table, dated and versioned, rather than a constant per model
-------------------------------------------------------------------

A rate moves — the same volatility §14.2 of the architecture doc records
for the depth role's cache and batch economics (*"rates move monthly …
the selection logic is stable, the numbers are not"*) applies just as
much to list pricing.  A cost estimate computed from a stale number is
not a smaller mistake than no estimate at all; it is a wrong one dressed
as an answer.  So the table carries :data:`PRICE_TABLE_VERSION` — the
date the rates were read off the vendor's page — beside every entry's
``source``, and a caller persisting an estimate persists the version
alongside it (feature 3's own column, ``price_table_version``), so a
report made six months from now can tell *which* table priced each row
rather than trusting that the number never moved.

Why unmapped is ``None`` and never a guessed number
----------------------------------------------------

The feature's sentence says the whole of this module's contract in one
clause: *a USD figure or None, never a guessed price*.  A model id this
table does not carry — an unreleased model, a self-hosted checkpoint with
no public rate card, or a **dated served id** such as
``claude-haiku-4-5-20251001`` that the table does not itself list — has
no rate this module can state, and the two wrong ways to answer that are
both a guess: falling back to a sibling model's price (which model is
the right sibling is not this module's to decide) or answering zero
(which looks like a free call rather than an unpriced one).  Feature 3's
own vocabulary is explicit that the caller must record **"unpriced"**
rather than a zero — this module's half of that discipline is to make
the unpriced state the one :func:`estimate_cost` can actually return,
by answering ``None`` and nothing numeric.  The lookup is **exact
string equality** against the table's keys for the same reason: a
prefix match or a fuzzy strip of a dated suffix would be this module
inventing which rate a served id's unstated version should be billed
at, which is the guess the sentence refuses.

What the table prices, and the one rate it checks against another
-------------------------------------------------------------------

Every entry carries four USD-per-million-token rates — plain input,
cache write, cache read and output — because Anthropic's Messages API
bills those four classes of a call's tokens at four different rates
(the fact the addition's summary opens with: *"providers.Usage folds
cache writes into input_tokens although Anthropic bills cache writes,
cache reads and plain input at three different rates"*).  A table that
priced only input and output would answer a number for every call that
touched the cache, silently billing a cache write or a cache read at
the plain-input rate — cheaper for a read, dearer for nothing a caller
asked to pay extra for in the case of a write — and it would do so
without the caller ever learning that the number was wrong on that
axis.

The 5-minute-TTL cache write is **1.25× the plain-input rate on every
entry this table carries**, which :data:`CACHE_WRITE_MULTIPLE` states
once and :class:`ModelPrice` checks on every entry at construction: a
hand-typed rate card is the one place a transcription slip — ``4.00``
copied as ``4.50`` — would otherwise sit undetected until a report's
number looked wrong for a reason nobody could trace back to this table.
The check is this table's own arithmetic, not a law the vendor is
assumed to keep forever: a future entry priced at a different cache-write
ratio is a table this module would need to widen, not a bug this check
exists to paper over.

The arithmetic :func:`estimate_cost` runs
------------------------------------------

A :class:`~providers.Usage`'s ``input_tokens`` is the call's *whole*
billed input — the addition's own fact, carried in
``providers._anthropic``'s own convention, is that ``input_tokens`` is
set to ``input_tokens + cache_creation_input_tokens +
cache_read_input_tokens`` — so the cache-write and cache-read counts are
a **portion of** ``input_tokens``, not additional to it.  Pricing the
whole of ``input_tokens`` at the plain rate and then pricing the cache
counts *again* at their own rates would double-bill exactly the tokens
the cache classes are a portion of, which is the plain-input subtraction
the feature's sentence spells out: the plain-input class a caller is
billed for is ``input_tokens - cache_write_tokens - cache_read_tokens``,
and each of the other three classes is billed at its own rate on top of
that. Every count is read from ``usage`` by name rather than by
``isinstance`` — the workspace's module loader imports every member
twice (once by file path, once as the importable member), so a
:class:`~providers.Usage` built through one copy would fail an
``isinstance`` check written against the other; see
:func:`providers.require_depth_model` for the same remedy applied to a
different record.  ``cache_write_tokens`` and ``cache_read_tokens``
default to zero when ``usage`` carries neither — the state feature 1's
own :class:`~providers.Usage` is in before that field exists, and the
reason features 1 and 2 are independent foundations the addition's
integration points name explicitly.

The answer is a :class:`~decimal.Decimal`, rounded to six places with
:data:`decimal.ROUND_HALF_UP` — the rounding a caller reading a dollar
figure expects, rather than the banker's rounding
:class:`decimal.Context`'s default (``ROUND_HALF_EVEN``) would apply at
the six-decimal boundary a sub-cent per-million rate can land exactly
on.  A :class:`float` was never a candidate: §14.2's own warning that a
cost figure must be exact enough to audit against a vendor invoice is
why :mod:`providers._cache` keeps its measured rate as a
:class:`~fractions.Fraction` rather than a rounded float, and a persisted
spend total is exactly the number a decimal rounding error would make
disagree with the console it is meant to reconcile against.

Stdlib-only: :mod:`dataclasses`, :mod:`decimal` and
:mod:`types.MappingProxyType`, consistent with the addition's own
constraint that "it adds no dependency".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

__all__ = [
    "CACHE_WRITE_MULTIPLE",
    "PRICE_TABLE",
    "PRICE_TABLE_VERSION",
    "ModelPrice",
    "PriceTableError",
    "estimate_cost",
    "price_for",
]


class PriceTableError(ValueError):
    """This module's one refusal: a price table entry or a usage is malformed.

    A single base, on the grounds :mod:`providers._depth_errors` states
    for its own trivia: every refusal in this module is about the same
    question — *can this be priced?* — so a caller catching the question
    has one exception to catch rather than guessing which of several this
    module might raise. A :class:`ValueError` subclass rather than a
    sibling of :class:`providers.ProviderError`: a call that cannot be
    priced has not failed the provider contract — the call completed —
    it is an accounting question about an answer that already exists.
    """


#: The date the rates below were read off the vendor's published list —
#: not the date this module was written, and not today.  A caller
#: persisting an estimate persists this string beside it (feature 3's
#: ``price_table_version`` column), so a report made after the rates have
#: moved can tell which table priced which row. See the module docstring's
#: *"why a table, dated and versioned"*.
PRICE_TABLE_VERSION = "2026-09-25"

#: The 5-minute-TTL cache write's rate as a multiple of the plain-input
#: rate, on every entry this table carries — the fact the feature's own
#: sentence states, and the cross-check :class:`ModelPrice` runs against
#: itself at construction, so a hand-typed transcription slip in either
#: rate is caught at import time rather than surfacing as a silently wrong
#: estimate later.
CACHE_WRITE_MULTIPLE = Decimal("1.25")

#: The unit every rate in this table is quoted per — "USD per million
#: tokens", the rate card's own convention (and :mod:`providers._cache`'s,
#: for the same axis).
_TOKENS_PER_UNIT = Decimal(1_000_000)

#: The six decimal places :func:`estimate_cost` rounds its answer to —
#: the feature's own figure.
_CENTS_PRECISION = Decimal("0.000001")


def _require_text(value: object, field: str) -> str:
    """Return ``value`` as a non-blank string, refusing anything else.

    One guard for a price entry's two string fields (``model``,
    ``source``), because a blank or non-string value in either is a
    rate card entry that names no model or cites no source — data this
    table cannot carry and a caller cannot audit.
    """
    if not isinstance(value, str) or not value.strip():
        raise PriceTableError(
            f"a price table entry's {field} must be a non-empty string, "
            f"got {value!r} ({type(value).__name__}). A price entry with "
            f"a blank {field} prices no model this table could be asked "
            f"about, and estimate_cost's \"a USD figure or None, never a "
            f"guessed price\" promise starts with the table itself being "
            f"well-formed."
        )
    return value


def _require_rate(value: object, field: str) -> Decimal:
    """Return ``value`` as a non-negative :class:`Decimal` rate, refusing anything else.

    Accepts a :class:`Decimal` or an ``int``/``str`` :class:`Decimal`
    could construct from, and refuses ``float`` by name: a rate card's
    figure is exact ($4.00, not a binary fraction near it), and a float
    literal would carry a float's rounding into every estimate this entry
    ever prices. ``bool`` is refused for the reason every numeric guard
    in this workspace refuses it: ``True`` is the integer ``1``, and a
    flag read as a rate would silently price a model at one dollar per
    million tokens.
    """
    if isinstance(value, (bool, float)):
        raise PriceTableError(
            f"a price table entry's {field} must be a Decimal, got "
            f"{value!r} ({type(value).__name__}). A rate card states an "
            f"exact dollar figure, and a float literal carries a binary "
            f"rounding error into every estimate this entry prices — "
            f"state the rate as Decimal(\"...\") instead."
        )
    if isinstance(value, Decimal):
        rate = value
    elif isinstance(value, (int, str)):
        try:
            rate = Decimal(value)
        except Exception as exc:
            raise PriceTableError(
                f"a price table entry's {field} must be a Decimal, got "
                f"{value!r} ({type(value).__name__}) which could not be "
                f"read as one: {exc}."
            ) from exc
    else:
        raise PriceTableError(
            f"a price table entry's {field} must be a Decimal, got "
            f"{value!r} ({type(value).__name__})."
        )
    if rate < 0:
        raise PriceTableError(
            f"a price table entry's {field} must be non-negative, got "
            f"{rate}. A rate below zero is not a discount a vendor offers "
            f"— it is a malformed entry, and pricing a call against it "
            f"would pay the caller to spend tokens rather than charge "
            f"them."
        )
    return rate


@dataclass(frozen=True)
class ModelPrice:
    """One model's USD-per-million-token rates, as a dated rate card states them.

    The four classes a call's tokens are billed under — ``input_price``
    (plain input), ``cache_write_price`` (writing the 5-minute-TTL
    cache), ``cache_read_price`` (reading a cache hit) and
    ``output_price`` — plus ``source``, the citation a caller reads when
    asking *where did this number come from?*  All four rates are always
    stated: there is no optional cache field a caller's lookup could find
    missing, because a table that priced input and output alone would
    answer a number for every cache-touching call while pricing the
    wrong tokens at the wrong rate (see the module docstring).

    ``cache_write_price`` is checked against :data:`CACHE_WRITE_MULTIPLE`
    times ``input_price`` at construction — the feature's own stated fact
    about the 5-minute TTL, restated as an entry-level invariant so a
    transcription slip in either rate fails loudly at import time rather
    than silently mispricing every call this entry prices.

    Frozen and value-equal: a price is a fact a vendor's page states on a
    date, not a field a caller tunes.
    """

    model: str
    input_price: Decimal
    cache_write_price: Decimal
    cache_read_price: Decimal
    output_price: Decimal
    source: str

    def __post_init__(self) -> None:
        # Field by field in declaration order, then the one cross-field
        # law, so an entry malformed in several places is refused for the
        # first one a reader would meet.
        object.__setattr__(self, "model", _require_text(self.model, "model"))
        object.__setattr__(
            self, "input_price", _require_rate(self.input_price, "input_price")
        )
        object.__setattr__(
            self,
            "cache_write_price",
            _require_rate(self.cache_write_price, "cache_write_price"),
        )
        object.__setattr__(
            self,
            "cache_read_price",
            _require_rate(self.cache_read_price, "cache_read_price"),
        )
        object.__setattr__(
            self, "output_price", _require_rate(self.output_price, "output_price")
        )
        object.__setattr__(self, "source", _require_text(self.source, "source"))
        expected_cache_write = self.input_price * CACHE_WRITE_MULTIPLE
        if self.cache_write_price != expected_cache_write:
            raise PriceTableError(
                f"{self.model!r}'s cache_write_price ({self.cache_write_price}) "
                f"must be {CACHE_WRITE_MULTIPLE} times its input_price "
                f"({self.input_price}) = {expected_cache_write}, the 5-minute "
                f"cache TTL's rate every entry in this table prices. A "
                f"mismatch here is a transcription slip in one of the two "
                f"rates, not a provider's unusual pricing — catching it at "
                f"the table rather than in a spend report is the point of "
                f"checking it at all."
            )


#: The dated rate card itself: Anthropic's first-party list prices,
#: verified :data:`PRICE_TABLE_VERSION`. Keyed by the exact model id a
#: served completion names — no prefix match, no stripping of a dated
#: suffix — because inferring which entry an unlisted id should fall
#: back to is the guess :func:`estimate_cost`'s contract refuses to make.
_SOURCE = f"Anthropic first-party list rates, verified {PRICE_TABLE_VERSION}"

PRICE_TABLE: Mapping[str, ModelPrice] = MappingProxyType(
    {
        price.model: price
        for price in (
            ModelPrice(
                model="claude-opus-5-5",
                input_price=Decimal("4.00"),
                cache_write_price=Decimal("5.00"),
                cache_read_price=Decimal("0.20"),
                output_price=Decimal("20.00"),
                source=_SOURCE,
            ),
            ModelPrice(
                model="claude-sonnet-5-5",
                input_price=Decimal("2.00"),
                cache_write_price=Decimal("2.50"),
                cache_read_price=Decimal("0.20"),
                output_price=Decimal("10.00"),
                source=_SOURCE,
            ),
            ModelPrice(
                model="claude-haiku-4-5",
                input_price=Decimal("1.00"),
                cache_write_price=Decimal("1.25"),
                cache_read_price=Decimal("0.10"),
                output_price=Decimal("5.00"),
                source=_SOURCE,
            ),
        )
    }
)


def price_for(model: object) -> ModelPrice | None:
    """The dated rate card entry for ``model``, or ``None`` if the table does not map it exactly.

    Exact string equality against :data:`PRICE_TABLE`'s keys and nothing
    softer: a dated served id such as ``claude-haiku-4-5-20251001`` is a
    different string from ``claude-haiku-4-5``, and reading one as the
    other would be this module guessing that the served id's unstated
    version bills at the base model's rate — exactly the guess the
    feature's sentence refuses. A non-string ``model`` answers ``None``
    for the same reason: it cannot equal any key this table holds.
    """
    if not isinstance(model, str):
        return None
    return PRICE_TABLE.get(model)


def _read_token_count(usage: object, field: str, *, default: int | None = None) -> int:
    """Read ``usage``'s ``field`` as a non-negative token count, refusing the rest.

    ``object.__getattribute__`` rather than ``getattr``, so an arbitrary
    object's ``__getattr__`` cannot fabricate a count this function then
    prices — the recognition :mod:`providers._cache` and
    :mod:`providers._served` use to read a caller's value **by its parts,
    not its class**, which matters here for the same reason it matters
    there: the workspace's module loader imports every member twice, so a
    :class:`~providers.Usage` built through one copy of
    ``providers._completion`` is not an ``instance`` of the class this
    module would import, and a check written against the wrong copy
    would refuse a well-formed usage.

    ``default`` answers a missing field rather than refusing it only for
    ``cache_write_tokens`` and ``cache_read_tokens`` — the two counts
    feature 1 adds and feature 192's :class:`~providers.Usage` already
    defaults to zero, so a usage built before either field existed is
    priced as "no cache activity" rather than refused, which is what
    keeps this feature usable independently of feature 1's landing (the
    addition's own integration point: *"Features 1 and 2 are independent
    foundations"*).
    """
    try:
        value = object.__getattribute__(usage, field)
    except AttributeError:
        if default is not None:
            return default
        raise PriceTableError(
            f"estimate_cost's usage must carry {field!r}, got "
            f"{usage!r} ({type(usage).__name__}) which has none. A "
            f"completion's token accounting is what is priced, and a "
            f"value missing {field!r} carries no count to price."
        ) from None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PriceTableError(
            f"estimate_cost's usage.{field} must be a non-negative int, "
            f"got {value!r} ({type(value).__name__})."
        )
    return value


def estimate_cost(model: object, usage: object) -> Decimal | None:
    """Price one call from :data:`PRICE_TABLE`, or answer ``None`` if it cannot be priced.

    The feature's whole contract: *a USD figure or None, never a guessed
    price*. ``model`` is looked up in :data:`PRICE_TABLE` by exact string
    equality (:func:`price_for`); a model the table does not map exactly
    — including a dated served id the table does not itself list —
    answers ``None`` here, and the caller is the one who records
    "unpriced", never zero (feature 3's own discipline; this function
    only ever returns a real figure or nothing).

    ``usage`` is read by name for four counts: ``input_tokens`` and
    ``output_tokens`` (required), ``cache_write_tokens`` and
    ``cache_read_tokens`` (default to zero when absent — see
    :func:`_read_token_count`). The plain-input class billed is
    ``input_tokens - cache_write_tokens - cache_read_tokens``, because
    ``input_tokens`` is the call's *whole* billed input and the two cache
    counts are a portion of it, not additional to it (the module
    docstring's *"the arithmetic estimate_cost runs"*); pricing the whole
    of ``input_tokens`` at the plain rate on top of the cache counts'
    own rates would double-bill the tokens the cache counts are a
    portion of. A ``usage`` whose cache counts exceed its ``input_tokens``
    cannot be priced this way and is refused as :class:`PriceTableError`
    rather than priced against a negative plain-input class.

    The answer is a :class:`~decimal.Decimal`, rounded to six places with
    :data:`decimal.ROUND_HALF_UP` — never a :class:`float`, so a persisted
    spend total is exact enough to reconcile against the vendor's own
    console.
    """
    price = price_for(model)
    if price is None:
        return None
    input_tokens = _read_token_count(usage, "input_tokens")
    output_tokens = _read_token_count(usage, "output_tokens")
    cache_write_tokens = _read_token_count(usage, "cache_write_tokens", default=0)
    cache_read_tokens = _read_token_count(usage, "cache_read_tokens", default=0)
    plain_input_tokens = input_tokens - cache_write_tokens - cache_read_tokens
    if plain_input_tokens < 0:
        raise PriceTableError(
            f"usage's cache_write_tokens ({cache_write_tokens}) plus "
            f"cache_read_tokens ({cache_read_tokens}) exceed its "
            f"input_tokens ({input_tokens}). input_tokens is a call's "
            f"whole billed input and the two cache counts are a portion "
            f"of it, so a usage reporting more cache than input cannot be "
            f"priced — it is a malformed accounting, not a call this "
            f"module can guess a plain-input class for."
        )
    cost = (
        Decimal(plain_input_tokens) * price.input_price
        + Decimal(cache_write_tokens) * price.cache_write_price
        + Decimal(cache_read_tokens) * price.cache_read_price
        + Decimal(output_tokens) * price.output_price
    ) / _TOKENS_PER_UNIT
    return cost.quantize(_CENTS_PRECISION, rounding=ROUND_HALF_UP)
