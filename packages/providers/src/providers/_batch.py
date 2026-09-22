"""Routing depth calls through a batch endpoint — feature 201.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 201: *System
routes depth calls through a batch endpoint when available, which returns
roughly half the synchronous rate.*  docs/nullius-tech-architecture.md §14.2
states the lever this module implements, as the first of its *"two free
levers worth ~50%"*:

    1. **Batch APIs halve rates** on OpenAI, Anthropic and Gemini. Route
       depth through them.

and gives the reason the lever costs nothing:

    **The depth role is pure asynchronous batch work.**  Nothing waits
    on it.

Feature 198 decides *which model* may take the depth role; feature 202
decides *when* its campaigns run; this feature decides **which endpoint**
the call goes to, and it is the sibling of 202 in more than adjacency: both
are §14.2's *"two free levers worth ~50%"*, both derive their whole premise
from the depth role's asynchrony, and *"these stack with caching.  Applying
both takes the depth role from ~$10 to ~$5 per campaign for a scheduler
change."*  They are two modules because they are two different facts about a
call — 202's is *when the run happens*, this one's is *which endpoint
serves it* — and a run scheduled outside peak is still billed at the
synchronous rate if its calls go to the synchronous endpoint.

The sentence's two halves, and why both are load-bearing
--------------------------------------------------------

*"Routes depth calls through a batch endpoint"* is the routing; *"when
available, which returns roughly half the synchronous rate"* is what makes
it a decision rather than a rule.  Read naively as *"always use batch"* the
sentence would be wrong on its own terms, because the batch endpoint is not
universally available: §14.2 lists three providers that offer one (OpenAI,
Anthropic, Gemini) and the module's own registry — DeepSeek and the
self-hosted tier among its depth entries — is not covered by that list.

So the feature is a **choice between two endpoints on facts a caller
states**, exactly as feature 202's is a choice between two windows on facts
a caller states, and it decomposes the same way:

* :class:`BatchEndpoint` — **the configuration's unit**: one provider's
  batch offering as the card describes it — the provider's name, whether it
  offers a batch endpoint *at all*, and the fraction of the synchronous rate
  that endpoint bills.  Shape-validated on construction: the provider is a
  non-empty string, availability is a strict ``bool`` (a provider with no
  batch endpoint is a *state a caller states*, not one it forgets — the
  discipline :func:`providers.flat_pricing` and
  :func:`providers.hosted_api_weights` keep for their own nulls), and the
  rate is a fraction in ``(0, 1]`` — a discount that is not a discount, or
  a multiplier above 1, is a malformed card rather than an expensive
  endpoint.

* :class:`BatchPricing` — **the configuration**: the frozen collection of
  the providers' offerings, and the answer to *which endpoints are
  available* the feature's sentence asks about.  Empty is legal and
  describes **no provider at all**, which is a different state from a card
  that describes a provider as offering no batch endpoint — and the
  difference is load-bearing at the routing, where the second routes
  synchronously and the first is refused.  See
  :class:`BatchPricing` for why the two are not one.

* :func:`route_depth_call` — **the choice**: the one depth call's endpoint
  from the offering the call's *serving provider* declares.  §14.2's
  *"route depth through them"* as a decision over three facts: which
  provider serves the call, whether that provider offers a batch endpoint,
  and whether the caller declared the call batchable.

* :class:`RoutedCall` — **the choice's answer**: the endpoint that serves
  the call, the provider, and the **rate multiple** the endpoint bills at
  (``1.0`` synchronously, the card's fraction batched) — the figure §14.2's
  *"roughly half"* is spent as, and the reason the record answers with a
  multiple rather than with a boolean: a caller that must account for the
  saving needs the number, and a boolean would leave it to re-derive one
  from a card it no longer holds.

The discount is configured, never constant
------------------------------------------

No fraction is spelled in this module's code, and the restraint is the same
one feature 202 keeps for its peak windows.  *"Roughly half"* is §14.2's
**description** of a rate that moves with the provider and the month, not a
number this module may assert: §14.2's preamble is *"Rates move monthly and
several below are explicitly promotional.  Re-verify before budgeting; the
**selection logic** is stable, the numbers are not."*  A module that
hard-coded ``0.5`` would be wrong on a schedule the document already
publishes, and would make a provider that discounts 40% unrepresentable.
So the card carries the fraction and the module carries the arithmetic —
:data:`BATCH_RATE_MULTIPLE` names the *concept* (a batched call bills at
some fraction of the synchronous rate) and each offering states its own.

This is why the record answers with a multiple rather than with a saving
percentage: the multiple is what a cost model multiplies by, and the
percentage is a rendering of it.  The suite's fixtures use 0.5 for the
providers §14.2 names, so a test reads like the deployment it stands in
for, and nothing in the module depends on that being the value.

A batchable call on a provider without a batch endpoint is not an error
-----------------------------------------------------------------------

A caller declaring a call batchable is stating a **preference**, not an
assertion that a batch endpoint exists: *"this call may go to a batch
endpoint if one is available"* is the sentence's own *"when available"* read
from the caller's side.  So the routing falls back to the synchronous
endpoint and says so in the answer — ``batched=False``, ``rate_multiple``
1.0 — rather than refusing.  Refusing would make the caller's preference a
claim about the deployment, and the deployment's set of batch-capable
providers is not something a caller can know at the call site; a route that
raised whenever a card lacked an endpoint would be a routing decision that
could only be made by reading the card first, which is what the routing
exists to do.

**The one refusal is a call whose serving provider the card does not
describe** — :class:`~providers.UnknownProviderError`, naming the provider.
That is a genuine gap: routing is a choice between endpoints, the choice is
read off the provider's offering, and a provider with no offering has no
endpoints to choose between.  The alternative — treating an absent provider
as *no batch endpoint* — would silently bill a call synchronously on the
strength of a card that never mentioned its provider, which is the failure
mode this feature exists to prevent arriving through the fallback meant to
be safe.

What this feature deliberately does not do
-------------------------------------------

It does not **place** the call.  Feature 192's :class:`providers.Provider`
is the seam a call passes through; this module decides which endpoint that
call should be *sent to*, and a caller holding a route binds the provider
that speaks the chosen endpoint.  There is no transport here, no polling,
no job handle and no completion — the batch APIs §14.2 names are
asynchronous (a job is submitted and collected later), and modelling that
lifecycle is a concrete provider's business, not a routing criterion's.

It does not **persist**.  Feature 196 records the serving provider, feature
200 the measured cache-hit rate, feature 202 the chosen run window; this
feature's decision is a property of a single call, and the call's own
record is where it would belong.  A store here would be a fourth member
owned table for a fact that is already carried in the route the caller
holds — and the routing is a pure function of a card and a call, so there is
nothing to be idempotent about.

It does not **choose the model**.  Feature 198's gate admits a model to the
depth role and this module never sees a :class:`providers.DepthModel`:
which model serves the call and which endpoint carries it are two decisions,
and a routing that re-checked the model's window would be the second
spelling of a criterion feature 198 states once.

Recognition across the workspace's double import
------------------------------------------------

Every entry point (:class:`BatchPricing` itself, :func:`route_depth_call`)
recognises a caller's card **by its parts, not its class**, and re-makes it
from this module's classes — the move :func:`providers.require_depth_model`
makes for candidates and :func:`providers.choose_run_window` makes for
pricing cards, for the same load-bearing reason: the module loader imports
every member twice (once by file path under ``_nullius_scanned_<dir>``,
once as the importable member), so two ``BatchPricing`` classes exist over
one source file, a dataclass's generated ``__eq__`` answers ``False``
between them for every value, and an ``isinstance`` gate would refuse the
very card the caller legitimately built.  Anything carrying an ``offerings``
iterable of ``(provider, available, rate_multiple)``-shaped items is the
configuration; the answer is always this module's classes, so equality
downstream means what it says.

Stdlib-only, like the rest of this tree: two strings, two numbers and the
comparison between them.  No provider is dialed, no job is submitted, no
price list is read — the routing runs before any call is placed, which is
what makes it free.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ._batch_errors import (
    BatchRoutingError,
    UnknownProviderError,
)

__all__ = [
    "BATCHED_COLUMN",
    "BATCH_ENDPOINT",
    "BATCH_RATE_MULTIPLE",
    "ENDPOINT_COLUMN",
    "PROVIDER_COLUMN",
    "RATE_MULTIPLE_COLUMN",
    "SYNCHRONOUS_ENDPOINT",
    "SYNCHRONOUS_RATE_MULTIPLE",
    "BatchEndpoint",
    "BatchPricing",
    "RoutedCall",
    "route_depth_call",
]

#: The endpoint §14.2's first lever routes a depth call to — one of the two
#: values :attr:`RoutedCall.endpoint` may take.  A closed set of two, for the
#: reason :mod:`providers._completion`'s finish reasons are a closed set: a
#: third endpoint is one this feature's sentence does not state, and a caller
#: branching on the route should not have to decide what an unfamiliar value
#: means.  Spelled as data because the choice, the record and the suite all
#: name the same two, and two places spelling one is one that can drift.
BATCH_ENDPOINT = "batch"

#: The endpoint a call goes to when no batch endpoint serves it — the other
#: half of the closed pair above, and the *only* endpoint on a deployment
#: whose providers offer no batch API at all (§14.2's own batch list does not
#: cover every provider in its depth registry).
SYNCHRONOUS_ENDPOINT = "synchronous"

#: The two endpoints, as the closed set :class:`RoutedCall` validates against.
#: Declared as data beside the two spellings rather than written into the
#: guard, so the set and the constants cannot drift: adding an endpoint is one
#: edit here, and the guard, the record and the suite all read it.
_ENDPOINTS: frozenset[str] = frozenset({BATCH_ENDPOINT, SYNCHRONOUS_ENDPOINT})

#: The column names :meth:`RoutedCall.row` renders under — this module's own
#: spellings rather than a table's, because feature 201 persists nothing (see
#: the module docstring): there is no ``batch_route`` table for them to
#: match, so they name the record's facts and nothing else.
PROVIDER_COLUMN = "provider"
ENDPOINT_COLUMN = "endpoint"
RATE_MULTIPLE_COLUMN = "rate_multiple"
BATCHED_COLUMN = "batched"

#: The rate multiple a **synchronous** call bills at — the whole of the
#: rate card's price, as the fraction a batched call is stated against.
#: Not a discount and not a default: it is the unit the batched fractions
#: are fractions *of*, and naming it is what lets
#: :class:`RoutedCall.rate_multiple` answer with one figure whatever
#: endpoint served the call — a caller multiplies by it in both cases and
#: never has to ask which kind of number it is holding.
SYNCHRONOUS_RATE_MULTIPLE = 1.0

#: The concept §14.2's first lever is worth — *"batch APIs halve rates"* —
#: spelled as data so the module can state the *shape* of the discount
#: without asserting its value.  It exists for the reason
#: :data:`providers.FLAT_AT_ANY_CONTEXT` and
#: :data:`packages.providers.tests.conftest.DEFAULT_AUTHOR` exist: the
#: number a document states is data a deployment re-verifies, and
#: §14.2's own preamble (*"rates move monthly … the numbers are not"*) is
#: the standing warning against baking one in.  A card that states this
#: value is stating the common case; a card that states 0.6 is stating a
#: different provider's offering, and both are legal configuration.  No
#: default on :class:`BatchEndpoint` reads it — an offering states its own
#: fraction — so this constant is documentation the suite and a caller may
#: cite, never a value the routing assumes.
BATCH_RATE_MULTIPLE = 0.5

#: The parts a batch offering is recognised by, in declaration order —
#: duck typing across the module loader's double import (see the module
#: docstring), the same tuple :mod:`providers._depth` and
#: :mod:`providers._schedule` declare for their own records.
_OFFERING_PARTS: tuple[str, ...] = ("provider", "available", "rate_multiple")

#: The parts a batch-pricing configuration is recognised by.
_PRICING_PARTS: tuple[str, ...] = ("offerings",)


# ── The configuration ─────────────────────────────────────────────────────────


def _require_provider_name(value: object) -> str:
    """Return ``value`` as a provider's name, refusing anything else.

    Shape only — whether the named provider actually offers a batch
    endpoint is the offering's own ``available`` fact, and whether a call's
    serving provider is *described* at all is the routing's question.  A
    name this function refuses is a name no call could route by: §14.2's
    batch row is stated per provider (OpenAI, Anthropic, Gemini), so the
    provider is the axis the whole configuration is keyed on, and a value
    that is not a name cannot key anything.

    Left as the base :class:`BatchRoutingError` rather than a subclass, on
    the grounds :mod:`providers._depth_errors` states for its own trivia:
    a malformed description is not a failed routing, and the taxonomy
    splits by question rather than by call site.
    """
    if not isinstance(value, str):
        raise BatchRoutingError(
            f"a batch offering's provider must be a string, got {value!r} "
            f"({type(value).__name__}). Feature 201 routes a depth call "
            "between the endpoints its serving provider offers, so the "
            "provider is what the configuration is keyed on — a value that "
            "is not a name cannot be looked up by one, and guessing which "
            "provider it stood for would be routing a call against a card "
            "nobody stated."
        )
    if not value.strip():
        raise BatchRoutingError(
            f"a batch offering's provider must be a non-empty string, got "
            f"{value!r}. A blank name describes no provider, and every "
            "call's route is read off the offering of the provider that "
            "serves it — an offering no call can be matched to is one this "
            "configuration cannot answer any routing question with."
        )
    # Canonicalized on the same grounds feature 202's campaign ids are:
    # the name is a lookup key, so ' bedrock ' and 'bedrock' must be one
    # provider rather than two that differ by whitespace a config file
    # happened to carry.
    return value.strip()


def _require_availability(value: object) -> bool:
    """Return ``value`` as whether a provider offers a batch endpoint.

    A strict ``bool``, because the fact is a **state a caller states** and
    not one it forgets: §14.2's own list distinguishes providers that offer
    a batch endpoint from providers that do not, and an offering that
    carried ``None`` or ``0`` for *unavailable* would leave a reader unable
    to tell *this provider has no batch endpoint* from *nobody said* — the
    discipline :func:`providers.flat_pricing` and
    :func:`providers.hosted_api_weights` keep for their own nulls, applied
    where the two states are a boolean apart rather than a ``None``.

    ``bool`` is checked by identity rather than by ``isinstance`` alone
    because it is an ``int`` subclass in Python and a config layer can hand
    over ``1`` by accident: accepting it would let an integer flag mean a
    provider's endpoint availability, which is exactly the kind of silent
    coercion both values below would then be read through.
    """
    if value is not True and value is not False:
        raise BatchRoutingError(
            f"a batch offering's availability must be a bool (True or "
            f"False), got {value!r} ({type(value).__name__}). Whether a "
            "provider offers a batch endpoint is a fact the configuration "
            "states: §14.2's own list names OpenAI, Anthropic and Gemini as "
            "offering one and several depth-tier providers as not, and a "
            "value that is neither True nor False — None, 0, 'yes' — cannot "
            "be read as either without inventing the answer."
        )
    return value


def _require_batchable(value: object) -> bool:
    """Return ``value`` as whether the caller declares the call may batch.

    The strict-``bool`` rule of :func:`_require_availability` applied to the
    other side of the same decision.  An offering's ``available`` is a fact
    the *configuration* states; this is a fact the *caller* states, and both
    are states rather than absences — the difference being that a caller who
    says nothing gets the default, while a caller who says something that is
    not a bool has said something this routing must not guess at.

    The coercion this refuses is the one a config layer makes most often and
    the most damaging of the class, because it **inverts** rather than
    blurs: ``'False'`` is a non-empty string and therefore *truthy*, so a
    deployment whose config carries ``batchable = 'False'`` — the string,
    off a YAML or env layer that did not coerce — would be routed to the
    batch endpoint by every call it meant to hold synchronous.  ``0`` and
    ``''`` and ``None`` would silently mean *synchronous* while ``1``,
    ``'yes'`` and ``'off'`` would silently mean *batch*; none of those is a
    decision anyone wrote down.  The caller's intent is read as stated or
    refused, never read through.
    """
    if value is not True and value is not False:
        raise BatchRoutingError(
            f"route_depth_call's batchable must be a bool (True or False), "
            f"got {value!r} ({type(value).__name__}). It declares whether "
            "the caller permits this particular depth call to be routed to "
            "a batch endpoint, and the truthiness coercion that would read a "
            "non-bool is not safe here: 'False' (a string, as a config layer "
            "would hand it over) is truthy and would route to batch — the "
            "exact opposite of what it states — while 0, '' and None would "
            "be read as *synchronous* and 1, 'yes' and 'off' as *batch*, "
            "none of which anyone decided. Pass True or False, or omit the "
            "argument to take the default."
        )
    return value


def _require_rate_multiple(value: object) -> float:
    """Return ``value`` as a batched call's rate multiple, refusing anything else.

    The fraction of the synchronous rate a batch endpoint bills, and the
    two refusals are the two ways a fraction can fail to be one:

    * not a number at all — ``'50%'`` (a string off a config file) or
      ``None`` is config noise this routing would otherwise multiply a cost
      by, and a cost model handed a string fails much further from the
      mistake than this guard does;
    * outside ``(0, 1]`` — a multiple above 1 is a batch endpoint *more*
      expensive than the synchronous one, which contradicts the feature's
      own premise (*"returns roughly half the synchronous rate"*) rather
      than describing an unusual card; a multiple of zero or below is a
      call that costs nothing or earns the caller money, which is not a
      rate card but a malformed field.  A rate is refused as data nonsense
      here for the same reason :func:`providers._depth._require_token_count`
      refuses a threshold of zero: hiding the malformation inside a routing
      it does not belong to would let a nonsense card route real calls.

    ``bool`` is refused by identity for the reason
    :func:`_require_availability` gives: ``True`` is the integer 1, and a
    flag read as a rate would silently bill at exactly the synchronous
    price while claiming to be a discount.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BatchRoutingError(
            f"a batch offering's rate_multiple must be a number, got "
            f"{value!r} ({type(value).__name__}). The batched rate is a "
            "fraction of the synchronous one — §14.2's *\"batch APIs halve "
            "rates\"* is such a fraction — and a value that is not a number "
            "cannot be multiplied into a cost."
        )
    multiple = float(value)
    if not 0.0 < multiple <= 1.0:
        raise BatchRoutingError(
            f"a batch offering's rate_multiple must be in (0, 1] — the "
            f"fraction of the synchronous rate a batched call bills at — "
            f"got {value!r}. Feature 201's premise is that a batch endpoint "
            "returns *roughly half the synchronous rate* (architecture "
            "§14.2), so a multiple above 1 describes an endpoint dearer "
            "than the one it would replace, and a multiple at or below 0 "
            "describes a call that costs nothing — neither is a rate card "
            "this routing may price a campaign against. State the fraction "
            "the provider's card gives, e.g. 0.5 for §14.2's halved rate."
        )
    return multiple


@dataclass(frozen=True)
class BatchEndpoint:
    """One provider's batch offering, as its rate card describes it.

    The three facts feature 201's routing reads, and no others:
    ``provider`` — whose offering this is, the name a call's serving
    provider is matched against; ``available`` — whether that provider
    offers a batch endpoint *at all* (§14.2: *"Batch APIs halve rates on
    OpenAI, Anthropic and Gemini"*, a list that does not cover every
    provider in the module's depth registry); and ``rate_multiple`` — the
    fraction of the synchronous rate the batch endpoint bills, which is
    the number §14.2's *"roughly half"* is spent as.

    **Unavailable is a stated offering, not a missing one.**  A provider
    with no batch endpoint is described by
    ``BatchEndpoint('deepseek', available=False, rate_multiple=1.0)``
    rather than by being left out of the card, for the reason
    :func:`providers.flat_pricing` exists: leaving it out would make *this
    provider offers no batch endpoint* indistinguishable from *nobody
    configured this provider*, and the second is a configuration gap that
    should be repaired while the first is a fact to route around.  The
    routing tells them apart by refusing the second
    (:class:`~providers.UnknownProviderError`) and falling back on the
    first.

    An unavailable offering still carries a ``rate_multiple``, and it must
    be ``1.0``-or-under like any other: the record keeps one shape rather
    than an optional field, and a caller reading
    :class:`RoutedCall.rate_multiple` never has to ask whether the number
    it holds is meaningful.  The routing never *reads* an unavailable
    offering's rate — an unavailable endpoint is never chosen — so the
    value is inert there, and stating the synchronous multiple for a
    provider that has no batch endpoint is the honest spelling of *there
    is no discount to state*.

    Construction validates shape only — a non-empty provider name, a
    strict bool, a fraction in ``(0, 1]``.  Whether a *call* can be
    batched is :func:`route_depth_call`'s question, asked with the call in
    hand, for the same reason a 262K-window :class:`providers.DepthModel`
    constructs happily and only feature 198's gate refuses it: describing a
    card is not routing a call against it.

    Frozen and value-equal for the reasons this package's other records
    are: an offering is a fact about a provider's pricing, not a field a
    caller tunes, and equality by value is what lets a card configured from
    a config file be compared to one a suite built without holding the same
    objects.
    """

    provider: str
    available: bool
    rate_multiple: float = SYNCHRONOUS_RATE_MULTIPLE

    def __post_init__(self) -> None:
        # Field by field in declaration order, so an offering malformed in
        # two places is refused for the first one a reader would meet — the
        # same ordering :class:`providers.DepthModel` and
        # :class:`providers.PeakWindow` use for their own parts.
        object.__setattr__(self, "provider", _require_provider_name(self.provider))
        object.__setattr__(
            self, "available", _require_availability(self.available)
        )
        object.__setattr__(
            self,
            "rate_multiple",
            _require_rate_multiple(self.rate_multiple),
        )

    def text(self) -> str:
        """The offering's canonical ``"provider:batch@0.5"`` spelling.

        The form refusals quote and humans read; the same role
        :meth:`providers.PeakWindow.text` plays for its own record.  An
        unavailable offering spells its state rather than its inert rate,
        so a card's rendering says which providers offer a batch endpoint
        at a glance.
        """
        if not self.available:
            return f"{self.provider}:no-batch"
        return f"{self.provider}:batch@{self.rate_multiple:g}"


@dataclass(frozen=True)
class BatchPricing:
    """Which providers offer a batch endpoint, and at what rate — feature 201's configuration.

    The frozen collection of the providers' :class:`BatchEndpoint`
    offerings, and the answer to the question the feature's sentence asks
    in its second clause: *"when available"* — available to **whom** is
    answered here, per provider.

    **Empty is a legal value that describes no provider — and that is not
    the same state as a provider offering no batch endpoint.**  The two are
    one silent fallback apart, which is precisely why the routing keeps
    them apart:

    * a card holding ``BatchEndpoint('deepseek', available=False, ...)``
      **describes** deepseek, and a call on it routes **synchronously** —
      a stated fact about a provider, routed around without complaint;
    * a card holding nothing **describes nobody**, so every call against
      it is refused as :class:`~providers.UnknownProviderError` — there is
      no endpoint to choose between, and answering *synchronous* would be
      inventing a fact about a provider the card never mentioned.

    So a deployment on providers whose cards offer no batch API does
    **not** express that by configuring an empty card; it states each
    provider it runs on, with ``available=False``, and gets the
    synchronous route it means.  The empty card is legal only in the
    structural sense that a card with no offerings is a well-formed value
    (a card built incrementally, a config file not yet filled in), and it
    answers no routing question — which is the honest answer for a card
    that names no provider, rather than a fallback that would bill real
    calls on the strength of it.

    This is deliberately **not** the shape
    :class:`providers.PeakPricing` takes for its own empty tuple, and the
    difference is worth stating because the analogy is tempting: an empty
    peak card still *answers every scheduling question* — the chooser reads
    the union of its windows as *no peak minute exists*, so every window is
    off-peak and a run is scheduled immediately.  An empty batch card
    answers no routing question at all, because the routing is keyed by a
    provider's name and an empty card holds no names.  The two nulls look
    alike and behave opposite ways: 202's means *flat by time of day*
    because the axes differ; this one means *nothing is configured here*
    because the axis is the provider and emptiness names none.

    **One offering per provider, and a repeated provider is refused.**
    Unlike a peak window — where overlapping windows are legal and mean
    what they say, because the arithmetic reads them as a union of minutes
    — a provider's batch offering is a single fact looked *up* by name, so
    two offerings for one provider would make every routing answer depend
    on which one a lookup happened to find: a card claiming
    ``anthropic`` offers batch at both 0.5 and 0.9 would bill the same
    call two ways.  The record refuses the duplicate at construction
    rather than picking one, naming the provider, because there is no
    canonical choice between them — the card contradicts itself and the
    repair is upstream.

    Construction accepts any iterable of offerings, re-makes each one from
    this module's class (recognised **by its parts** — ``provider``,
    ``available`` and ``rate_multiple`` attributes — the double-import
    remedy the module docstring states, applied at the constructor so
    every path through the configuration single-sources validation here),
    and **canonicalizes the order**: the tuple is stored sorted by
    provider name, so two cards stating the same offerings in different
    orders are one value — the determinism :class:`providers.PeakPricing`
    achieves by sorting on its windows' canonical text, and the reason a
    card read from a config file compares equal to the card a suite built.
    Frozen and value-equal so a card configured twice compares equal.
    """

    offerings: tuple[BatchEndpoint, ...] = ()

    def __post_init__(self) -> None:
        # Any iterable is accepted (a config file's list, a tuple a caller
        # built) and answered as this module's immutable tuple of this
        # module's offerings, in canonical provider-name order — one class
        # and one order, so equality downstream means what it says.  The
        # value is checked for iterability first, through the same guard the
        # routing path uses, so a non-collection is refused in this module's
        # vocabulary rather than dying inside ``tuple()`` as a bare
        # ``TypeError`` — the guard is called here rather than duplicated, so
        # there is one spelling of the rule and one message for it.
        offerings = tuple(
            _offering_from_parts(o) for o in _require_offerings(self.offerings)
        )
        seen: set[str] = set()
        for offering in offerings:
            if offering.provider in seen:
                raise BatchRoutingError(
                    f"the batch pricing card states an offering for "
                    f"{offering.provider!r} more than once. A provider's "
                    "batch availability and rate are one fact looked up by "
                    "the provider's name, so two offerings for one provider "
                    "would make every routing answer depend on which one the "
                    "lookup found — the same campaign billed at two rates "
                    "depending on nothing. Keep one offering per provider; "
                    "the card is contradictory, not merely redundant."
                )
            seen.add(offering.provider)
        object.__setattr__(
            self,
            "offerings",
            tuple(sorted(offerings, key=lambda o: o.provider)),
        )

    @property
    def available_providers(self) -> tuple[str, ...]:
        """The names of the providers offering a batch endpoint, sorted.

        The named fact behind *"when available"*, offered as a property for
        the reason :meth:`providers.PeakPricing.flat_by_time_of_day` is
        one: a caller deciding whether to declare a call batchable wants to
        know which endpoints exist before it makes the call, and the answer
        should say which question it answers.  Derived, never stored — the
        record holds the offerings and this is a reading of them.
        """
        return tuple(o.provider for o in self.offerings if o.available)

    def text(self) -> str:
        """The card's canonical spelling — offerings joined, sorted.

        Sorted by the offerings' canonical text so two cards stating the
        same offerings spell the same, the determinism
        :meth:`providers.PeakPricing.text` gives its own configuration.
        """
        return ", ".join(sorted(o.text() for o in self.offerings))

    def offering_for(self, provider: object) -> BatchEndpoint | None:
        """The offering for ``provider``, or ``None`` when the card holds none.

        The lookup the routing is built on, spelled once so the refusal and
        the fallback read the same card the same way.  ``None`` means *this
        card does not describe this provider* — a configuration gap, which
        :func:`route_depth_call` refuses by name rather than reading as
        *no batch endpoint available*: the two are one silent fallback
        apart, and confusing them is how a call billed synchronously would
        look like a decision.
        """
        name = provider.strip() if isinstance(provider, str) else provider
        for offering in self.offerings:
            if offering.provider == name:
                return offering
        return None


# ── The choice ────────────────────────────────────────────────────────────────


def _require_offerings(value: object) -> Iterable:
    """Return ``value`` as an iterable of offerings, refusing anything else.

    The one guard for a card's collection, called by :class:`BatchPricing`'s
    own constructor **and** by the routing's card-recognition helper, so
    there is a single spelling of the rule and a single message for it.  It
    exists because the failure it prevents is otherwise invisible: ``tuple()``
    over a non-iterable raises a bare ``TypeError``, which is not this
    module's vocabulary — a caller whose single ``except BatchRoutingError``
    is meant to catch every malformed configuration would find the mistake
    escaping as a builtin instead.

    Two refusals, and the second is not pedantry:

    * **not iterable at all** — an int, ``None``, an arbitrary object: there
      is no collection to read offerings from, and a card is a collection.
    * **a string or bytes** — iterable, and therefore the case a bare
      ``isinstance(value, Iterable)`` check would wave through.  Iterating
      one yields its *characters*, so ``BatchPricing(offerings="openai")``
      would produce five one-character "offerings" and fail about the wrong
      thing entirely (or, for a one-character string, succeed with a card
      nobody wrote).  Refused as a non-collection, naming what it is.

    The refusal is the base :class:`BatchRoutingError` rather than a
    subclass, on the grounds :mod:`providers._batch_errors` gives: a
    malformed description is not a failed routing, and the taxonomy splits
    by question rather than by call site.
    """
    if isinstance(value, (str, bytes)):
        raise BatchRoutingError(
            f"a batch pricing card's offerings must be an iterable of "
            f"BatchEndpoint records, got {value!r} (a "
            f"{type(value).__name__}). A string is iterable but is not a "
            "collection of offerings — reading one would yield its "
            "characters, and a card nobody wrote is worse than a refusal. "
            "Pass a sequence of BatchEndpoint records."
        )
    if not isinstance(value, Iterable):
        raise BatchRoutingError(
            f"a batch pricing card's offerings must be an iterable of "
            f"BatchEndpoint records, got {value!r} "
            f"({type(value).__name__}). A card is a collection of "
            "providers' offerings; a single non-iterable value is not a "
            "card this routing may choose an endpoint from."
        )
    return value


def _offering_from_parts(value: object) -> BatchEndpoint:
    """Re-make ``value`` as a :class:`BatchEndpoint` from its parts.

    Recognition is structural — the three attributes
    :data:`_OFFERING_PARTS` names, read on ``object.__getattribute__`` —
    rather than by class, because the module loader gives every member two
    class objects over one source file (see :func:`route_depth_call`).
    ``object.__getattribute__`` rather than ``getattr`` so an arbitrary
    object's ``__getattr__`` cannot fabricate an offering: this function
    decides what may be configured as a batch endpoint, and a hook that
    answered three parts would be a hook that offered one.

    The parts are read whatever their types and handed to the constructor,
    which refuses a malformed one precisely — a stub carrying
    ``rate_multiple="half"`` is told its rate is not a number, not that it
    is "not an offering" — so recognition stays cheap and the validation
    stays single-sourced: there is one shape check, the record's own.
    """
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _OFFERING_PARTS
        )
    except AttributeError:
        raise BatchRoutingError(
            f"a batch pricing card's offerings must be BatchEndpoint "
            f"records ({', '.join(_OFFERING_PARTS)}), got {value!r} "
            f"({type(value).__name__}). Feature 201 routes a depth call by "
            "reading its serving provider's offering, and a value that is "
            "not the record carries no provider, no availability and no "
            "rate — padding the missing fields with guesses would be "
            "routing calls against a card nobody stated."
        ) from None
    return BatchEndpoint(
        provider=parts[0],
        available=parts[1],
        rate_multiple=parts[2],
    )


def _require_pricing(value: object) -> BatchPricing:
    """Return ``value`` as a :class:`BatchPricing`, re-made from its parts.

    The card is recognised by its single ``offerings`` part and re-made
    through :class:`BatchPricing`'s own constructor, so every path into the
    routing single-sources the shape check — the same move
    :func:`providers._schedule._require_pricing` makes for its own
    configuration, and for the same double-import reason.  A value with no
    ``offerings`` attribute at all is refused as the base
    :class:`BatchRoutingError`, because a routing asked to choose between
    endpoints needs a card that states some.
    """
    try:
        offerings = object.__getattribute__(value, "offerings")
    except AttributeError:
        raise BatchRoutingError(
            f"a batch pricing card must be a BatchPricing (offerings), got "
            f"{value!r} ({type(value).__name__}). Feature 201's routing "
            "chooses the endpoint a depth call goes to from the offering "
            "its serving provider declares, and a value that is not the "
            "card offers no endpoints to choose between."
        ) from None
    return BatchPricing(offerings=tuple(_require_offerings(offerings)))


@dataclass(frozen=True)
class RoutedCall:
    """Where one depth call goes, and what it is billed at — feature 201's answer.

    The route's three facts as one value: the ``provider`` that serves the
    call, the ``endpoint`` chosen for it
    (:data:`~providers.BATCH_ENDPOINT` or
    :data:`~providers.SYNCHRONOUS_ENDPOINT`, a closed set of two), and the
    ``rate_multiple`` the chosen endpoint bills at —
    :data:`SYNCHRONOUS_RATE_MULTIPLE` (``1.0``) for a synchronous call, the
    offering's fraction for a batched one.

    ``batched`` is a **property derived from the endpoint**, not a fourth
    field, and the reason is that the alternative admits a state that is not
    a route at all: a record carrying both would happily hold
    ``endpoint='synchronous', batched=True``, and every reader downstream
    would have to decide which of the two contradicting fields to believe.
    The endpoint is the fact the routing decided; the boolean is a rendering
    of it for the caller that wants to branch.

    ``rate_multiple`` is answered as a **multiple** rather than as a
    saving, because that is the figure §14.2's *"roughly half"* is spent
    as: a cost model multiplies a synchronous estimate by it, and the
    percentage is a rendering of the same number.  A record that answered
    ``0.5`` and left the caller to work out *of what* would be handing
    back half an answer — and a caller holding a route has already let go
    of the card it was derived from, so the base figure has to travel with
    the choice or not be reconstructible at all.

    Construction validates the endpoint is one of the two the feature's
    sentence states, for the reason :mod:`providers._completion`'s finish
    reasons are a closed set: a caller branching on the route should not
    have to decide what an unfamiliar third value means, and a route to an
    endpoint this feature does not know is a routing decision nobody made.

    Frozen and value-equal, so a route a suite computes compares equal to
    the route a caller holds — the same testability every record in this
    package gets from being a value type.
    """

    provider: str
    endpoint: str
    rate_multiple: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _require_provider_name(self.provider))
        # The membership test is guarded by a string check rather than run
        # bare: ``_ENDPOINTS`` is a set, so ``x in _ENDPOINTS`` raises a
        # bare ``TypeError`` for an unhashable value (a list, a dict) before
        # this refusal can name it.  Whether the value is a string *must* be
        # asked first, and it is not a redundant check — every member of the
        # closed set is a string, so a non-string can never be one, and the
        # guard turns a builtin escape into this module's own refusal.
        if not isinstance(self.endpoint, str) or self.endpoint not in _ENDPOINTS:
            raise BatchRoutingError(
                f"a routed call's endpoint must be one of "
                f"({BATCH_ENDPOINT!r}, {SYNCHRONOUS_ENDPOINT!r}), got "
                f"{self.endpoint!r}. Feature 201's routing chooses between "
                "the endpoint that serves a depth call asynchronously at a "
                "discount and the one that serves it synchronously — a "
                "third value names an endpoint this feature never decided "
                "on, and a caller branching on the route has no reader for "
                "it."
            )
        object.__setattr__(
            self,
            "rate_multiple",
            _require_rate_multiple(self.rate_multiple),
        )

    @property
    def batched(self) -> bool:
        """Whether this call goes to the batch endpoint — read off the endpoint.

        Derived, never stored: the route's endpoint *is* the decision, and a
        boolean kept beside it would be a second spelling of the same fact
        that could disagree with the first.  A caller branches on this; a
        record that needs to know which endpoint was chosen reads
        :attr:`endpoint`.
        """
        return self.endpoint == BATCH_ENDPOINT

    def row(self) -> dict[str, Any]:
        """The route as a store-shaped mapping — a fresh dict per call.

        The column names are this module's own constants, the discipline
        :meth:`providers.ScheduledRun.row` states: a rendered mapping names
        the same things the same way the record does.  There is no table
        behind it — this feature persists nothing (see the module
        docstring) — so the mapping is offered for a caller that is
        recording the call's own provenance, not for a store in this
        package.
        """
        return {
            PROVIDER_COLUMN: self.provider,
            ENDPOINT_COLUMN: self.endpoint,
            RATE_MULTIPLE_COLUMN: self.rate_multiple,
            BATCHED_COLUMN: self.batched,
        }


def route_depth_call(
    pricing: object,
    *,
    provider: object,
    batchable: bool = True,
) -> RoutedCall:
    """Route one depth call to the endpoint its provider offers — feature 201's choice.

    The feature's sentence as a decision: *"routes depth calls through a
    batch endpoint when available"* — **available** is read off the card's
    offering for the call's serving provider, and the answer is the
    endpoint that serves the call together with the rate multiple it bills
    at.  Three facts go in and one record comes out:

    1. **``pricing``** — the deployment's card: which providers offer a
       batch endpoint and at what fraction of the synchronous rate.  A
       value that is not a :class:`BatchPricing` is refused as the base
       :class:`BatchRoutingError`, because a routing asked to choose
       between endpoints needs a card that states some.
    2. **``provider``** — the provider *serving this call*.  It is the
       serving provider and not the model that matters here: §14.2 states
       the lever per provider (*"on OpenAI, Anthropic and Gemini"*), and
       one model id can be offered by more than one supply chain with
       different batch availability.
    3. **``batchable``** — whether the caller declares this call may go to
       a batch endpoint.  Defaults to ``True``, which is the depth role's
       own answer: §14.2's lever is free *because* depth calls are *"pure
       asynchronous batch work"* and *"nothing waits on it"*.  A caller
       with a call something genuinely waits on — a root proposal, a
       policy revision — states ``False`` and gets the synchronous
       endpoint whatever the card offers, because a batch endpoint's
       asynchrony is the whole reason it is cheaper and the whole reason
       it cannot serve a call on a critical path.  A strict ``bool``, for
       the reason :func:`_require_batchable` gives: ``'False'`` off a
       config layer is a truthy string, and a coercion would route the
       call to batch while the caller was reading its own config as
       saying not to.

    **The two outcomes, in the order they are decided** (branchable
    first, then availability, because a call the caller has not declared
    batchable never asks about batch endpoints at all — asking would be
    reading a card to answer a question the caller already answered):

    * ``batchable`` and the provider's offering says ``available`` — the
      batch endpoint, at the offering's ``rate_multiple``.
    * otherwise — the synchronous endpoint, at
      :data:`SYNCHRONOUS_RATE_MULTIPLE`.  This covers both *the caller
      did not declare the call batchable* and *the provider offers no
      batch endpoint*, and the two are deliberately one outcome: both are
      *this call goes synchronously*, and the route's ``endpoint`` says so
      without pretending to know which reason applied.  A caller that
      needs the reason has the card and the flag it passed.

    **The one refusal** is a provider the card does not describe, as
    :class:`~providers.UnknownProviderError` naming it: routing is a
    choice between endpoints and the choice is read off the provider's
    offering, so a provider with no offering has no endpoints to choose
    between.  Treating an absent provider as *no batch endpoint* would be
    the silent fallback the module docstring refuses — a call billed
    synchronously on the strength of a card that never mentioned its
    provider, which is indistinguishable from a routing decision and is
    therefore the failure mode this feature exists to prevent.

    The card is recognised **by its parts, not its class**, and re-made
    from this module's class.  The workspace's module loader imports every
    member twice — once by file path under ``_nullius_scanned_<dir>``,
    once as the importable member — so two ``BatchPricing`` classes exist
    over one source file, and a dataclass's generated ``__eq__`` answers
    ``False`` between them for every value.  An ``isinstance`` gate would
    therefore refuse the very card the caller legitimately built from the
    deployment's config, and a pass-through would leave the answer's
    comparisons quietly unequal.  Recognition by shape, answers in one
    class — the same move :func:`providers.require_depth_model` makes for
    candidates, for the same reason.

    This function decides **where a call goes**, and nothing else: it does
    not place the call (feature 192's seam and the concrete provider bound
    to it do), does not choose the model (feature 198's gate does), does
    not persist the choice (the call's own record is where that belongs),
    and does not wait for anything (a batch call's collection is the
    transport's business, and §14.2's whole premise is that nothing here
    waits).  It is a pure function of its three arguments — no file is
    read, no database is opened, no clock is consulted — which is what
    makes the lever free.
    """
    # All three arguments are validated before any of them is *read*, and
    # ``batchable`` is guarded for the reason :func:`_require_batchable`
    # gives: the truthiness coercion of a non-bool would route a caller who
    # stated ``'False'`` to the batch endpoint, inverting the intent it just
    # declared.  The order is that every **shape** refusal precedes the one
    # **content** refusal below — a call whose own arguments are not the
    # types they claim to be is not yet a call worth matching against a
    # card, so a caller passing a malformed flag alongside an incomplete
    # card hears about the malformed flag.  Both are mistakes the caller
    # must repair before this returns an answer; neither is hidden by the
    # other.
    card = _require_pricing(pricing)
    name = _require_provider_name(provider)
    may_batch = _require_batchable(batchable)
    offering = card.offering_for(name)
    if offering is None:
        raise UnknownProviderError(
            f"no batch pricing card describes provider {name!r}, so this "
            f"depth call has no endpoint to be routed to. The card states "
            f"{card.text() or 'no offerings'}. Feature 201 routes a call "
            "between the endpoints its **serving provider** offers — "
            "§14.2 states the batch lever per provider (*\"Batch APIs "
            "halve rates on OpenAI, Anthropic and Gemini\"*) — so a card "
            "that does not describe this provider says nothing about "
            "whether the call may be batched. It is deliberately *not* "
            "read as *no batch endpoint available*: that fallback would "
            "bill the call synchronously on the strength of a card that "
            "never mentioned its provider, which is indistinguishable "
            "from a routing decision. Add the provider's offering to the "
            "card — with available=False and rate_multiple="
            f"{SYNCHRONOUS_RATE_MULTIPLE} if it offers no batch endpoint."
        )
    if may_batch and offering.available:
        return RoutedCall(
            provider=name,
            endpoint=BATCH_ENDPOINT,
            rate_multiple=offering.rate_multiple,
        )
    return RoutedCall(
        provider=name,
        endpoint=SYNCHRONOUS_ENDPOINT,
        rate_multiple=SYNCHRONOUS_RATE_MULTIPLE,
    )
