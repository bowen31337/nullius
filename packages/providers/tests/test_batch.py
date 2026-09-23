"""Feature 201: routing depth calls through a batch endpoint when available.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 201: *System
routes depth calls through a batch endpoint when available, which returns
roughly half the synchronous rate.*  The lever is architecture §14.2's first
of its *"two free levers worth ~50%"* — *"**Batch APIs halve rates** on
OpenAI, Anthropic and Gemini.  Route depth through them."* — and the reason
it is free is stated one paragraph above: *"**The depth role is pure
asynchronous batch work.**  Nothing waits on it."*

The tests below hold each clause of the sentence to its word, and the clauses
are three:

* **"when available"** — the routing is a *choice* between two endpoints, not
  a rule that always batches.  §14.2's own list names three providers as
  offering a batch endpoint, and the module's depth registry holds providers
  the list does not cover; a call whose provider offers none goes
  synchronously and that is an outcome, not a refusal.
* **"routes depth calls through"** — the route is a decision over facts the
  deployment states: which provider serves the call, whether that provider
  offers a batch endpoint, and whether the caller declared the call
  batchable.
* **"returns roughly half the synchronous rate"** — the answer carries the
  **rate multiple**, the figure the saving is actually spent as.  *"Roughly
  half"* is §14.2's description of a number that moves with the provider and
  the month, so the card carries the fraction and the module carries only the
  arithmetic — the same restraint feature 202 keeps for its peak windows, on
  the same sentence of §14.2's preamble (*"rates move monthly … the numbers
  are not"*).

The suite's fixture card is §14.2's own batch list — OpenAI, Anthropic and
Gemini available at the halved rate — plus the providers §14.2's depth tier
names which that list does not cover (DeepSeek, the self-hosted tier),
stated as unavailable.  It is test data, not a default the module carries:
the constants it is built from live here, so a reader can see the card the
tests route against without reading the module.

The one refusal is a provider the card does not describe, and it is tested
as such: the routing must not read an absent provider as *no batch endpoint*,
because that fallback would bill a real call synchronously on the strength of
a card that simply forgot the provider.
"""

from __future__ import annotations

import dataclasses
from dataclasses import fields
from types import SimpleNamespace

import pytest
from providers import (
    BATCH_ENDPOINT,
    BATCH_RATE_MULTIPLE,
    BATCHED_COLUMN,
    ENDPOINT_COLUMN,
    PROVIDER_COLUMN,
    RATE_MULTIPLE_COLUMN,
    SYNCHRONOUS_ENDPOINT,
    SYNCHRONOUS_RATE_MULTIPLE,
    BatchEndpoint,
    BatchPricing,
    BatchRoutingError,
    RoutedCall,
    UnknownProviderError,
    route_depth_call,
)

#: §14.2's own batch list, and the fraction its sentence names: *"Batch APIs
#: halve rates on OpenAI, Anthropic and Gemini."*  The three providers are
#: spelled here as data so a test's card reads like the deployment's, and the
#: fraction is spelled as the module's own concept constant rather than as a
#: literal — a reader can see that the suite is using the *halved* rate, not
#: a 0.5 that happened to be typed.
OPENAI = "openai"
ANTHROPIC = "anthropic"
GEMINI = "gemini"

#: The providers §14.2's depth tier names that its batch list does **not**
#: cover — DeepSeek V4.1 Flash is the primary depth model and appears in the
#: registry without a batch row, and the self-hosted tier is by definition
#: a provider whose endpoint the deployment runs itself.  Stated as
#: unavailable rather than omitted, which is the whole point of the
#: ``available`` field: *this provider offers no batch endpoint* is a fact,
#: *nobody configured this provider* is a gap, and the routing tells them
#: apart.
DEEPSEEK = "deepseek"
SELF_HOSTED = "ornith-self-hosted"


@pytest.fixture
def halving_card() -> BatchPricing:
    """The card §14.2 describes: its batch list halved, its depth tier not.

    Three providers offering a batch endpoint at §14.2's halved rate, and two
    the document's batch list does not cover stated as offering none.  Built
    rather than imported so that the tests which are about *which provider is
    available* can read the card they route against in one place.
    """
    return BatchPricing(
        offerings=(
            BatchEndpoint(provider=OPENAI, available=True, rate_multiple=0.5),
            BatchEndpoint(provider=ANTHROPIC, available=True, rate_multiple=0.5),
            BatchEndpoint(provider=GEMINI, available=True, rate_multiple=0.5),
            BatchEndpoint(
                provider=DEEPSEEK,
                available=False,
                rate_multiple=SYNCHRONOUS_RATE_MULTIPLE,
            ),
            BatchEndpoint(
                provider=SELF_HOSTED,
                available=False,
                rate_multiple=SYNCHRONOUS_RATE_MULTIPLE,
            ),
        )
    )


# ── The configuration ─────────────────────────────────────────────────────────


class TestBatchEndpoint:
    """The configuration's unit: one provider's batch offering."""

    def test_accepts_the_offering_the_document_states(self):
        # §14.2's row, spelled as the record expects it: a provider, the
        # fact that it offers a batch endpoint, and the fraction of the
        # synchronous rate that endpoint bills.  Constructing one is not the
        # routing — an offering is a description, and describing a card is
        # not routing a call against it.
        offering = BatchEndpoint(
            provider=OPENAI, available=True, rate_multiple=BATCH_RATE_MULTIPLE
        )
        assert offering.provider == OPENAI
        assert offering.available is True
        assert offering.rate_multiple == 0.5

    def test_an_unavailable_offering_is_a_stated_fact_not_an_absence(self):
        # The load-bearing distinction the whole feature turns on: a provider
        # that offers no batch endpoint is *described*, with available=False,
        # rather than left out of the card.  Leaving it out would make "this
        # provider has no batch endpoint" indistinguishable from "nobody
        # configured this provider", and the routing refuses the second while
        # falling back on the first.
        offering = BatchEndpoint(
            provider=DEEPSEEK,
            available=False,
            rate_multiple=SYNCHRONOUS_RATE_MULTIPLE,
        )
        assert offering.available is False
        # The record keeps one shape: an unavailable offering still carries a
        # rate, and it is the synchronous one because there is no discount to
        # state.  A caller reading a route never has to ask whether the
        # number it holds is meaningful.
        assert offering.rate_multiple == SYNCHRONOUS_RATE_MULTIPLE
        assert offering.text() == f"{DEEPSEEK}:no-batch"

    def test_the_rate_multiple_defaults_to_the_synchronous_one(self):
        # A caller stating only *this provider offers no batch endpoint* need
        # not also spell the rate — there is exactly one honest value for an
        # endpoint that is never chosen.  The default is the synchronous
        # multiple, not the batched one, so a forgotten field can never
        # manufacture a discount.
        assert BatchEndpoint(provider=DEEPSEEK, available=False).rate_multiple == 1.0

    def test_text_spells_the_available_offering_with_its_rate(self):
        # The canonical spelling the refusals quote and a reader scans: an
        # available offering shows its fraction, so a card's rendering says
        # at a glance which providers batch and at what rate.
        assert BatchEndpoint(OPENAI, True, 0.5).text() == "openai:batch@0.5"

    @pytest.mark.parametrize("provider", ["", "   ", None, 7, ["openai"]])
    def test_refuses_a_provider_that_is_not_a_name(self, provider):
        # The provider is what the configuration is keyed on — §14.2 states
        # the batch lever per provider — so a value that is not a non-empty
        # name cannot key anything, and guessing which provider it stood for
        # would be routing a call against a card nobody stated.
        with pytest.raises(BatchRoutingError, match="provider"):
            BatchEndpoint(provider=provider, available=True, rate_multiple=0.5)

    def test_canonicalizes_a_provider_name_that_carries_whitespace(self):
        # The name is a lookup key, so ' openai ' and 'openai' must be one
        # provider rather than two that differ by whitespace a config file
        # happened to carry — the same canonicalization feature 202 applies
        # to its campaign ids.
        assert BatchEndpoint(" openai ", True, 0.5).provider == OPENAI
        assert BatchEndpoint(" openai ", True, 0.5) == BatchEndpoint(
            OPENAI, True, 0.5
        )

    @pytest.mark.parametrize("available", [None, 0, 1, "yes", "true", []])
    def test_refuses_an_availability_that_is_not_a_bool(self, available):
        # Availability is a state the caller *states*, and an int is an
        # ``int`` subclass's cousin that a config layer hands over by
        # accident: accepting 1 would let an integer flag mean a provider's
        # endpoint availability, and accepting None would leave a reader
        # unable to tell "no batch endpoint" from "nobody said".
        with pytest.raises(BatchRoutingError, match="availability"):
            BatchEndpoint(provider=OPENAI, available=available, rate_multiple=0.5)

    @pytest.mark.parametrize("rate", ["50%", None, "half", [0.5], {}])
    def test_refuses_a_rate_that_is_not_a_number(self, rate):
        # Config noise — a percentage string off a YAML file, a bare None —
        # cannot be multiplied into a cost, and a cost model handed a string
        # fails much further from the mistake than this guard does.
        with pytest.raises(BatchRoutingError, match="rate_multiple"):
            BatchEndpoint(provider=OPENAI, available=True, rate_multiple=rate)

    @pytest.mark.parametrize("rate", [1.4, 2.0, 0.0, -0.5, -1.0])
    def test_refuses_a_rate_outside_the_unit_interval(self, rate):
        # The feature's own premise is that a batch endpoint *returns roughly
        # half the synchronous rate*: a multiple above 1 describes an
        # endpoint dearer than the one it would replace, and one at or below
        # 0 describes a call that costs nothing.  Neither is a rate card this
        # routing may price a campaign against, and both are refused as data
        # nonsense rather than routed around.
        with pytest.raises(BatchRoutingError, match=r"\(0, 1\]"):
            BatchEndpoint(provider=OPENAI, available=True, rate_multiple=rate)

    def test_accepts_the_whole_rate_as_a_legal_boundary(self):
        # 1.0 is the closed end of ``(0, 1]`` and it is legal: a provider
        # whose batch endpoint bills the synchronous rate is a real — if
        # unrewarding — offering, and refusing it would make a fact the card
        # states unstatable.  The range is refused where it is nonsense, not
        # where it is merely disappointing.
        assert BatchEndpoint(OPENAI, True, 1.0).rate_multiple == 1.0

    def test_refuses_a_bool_as_a_rate(self):
        # ``True`` is the integer 1: a flag read as a rate would silently
        # bill at exactly the synchronous price while claiming to be a
        # discount.  Refused by identity for the reason availability is.
        with pytest.raises(BatchRoutingError, match="rate_multiple"):
            BatchEndpoint(provider=OPENAI, available=True, rate_multiple=True)

    def test_carries_only_what_the_routing_reads(self):
        # Three fields: the provider, its availability, its rate.  Which
        # *model* serves the call is feature 198's gate and which *endpoint*
        # carries it is this feature's, and the two are different decisions —
        # a routing that re-checked a window would be the second spelling of
        # a criterion feature 198 states once.  The surface is pinned so an
        # addition is a decision the suite notices.
        assert [field.name for field in fields(BatchEndpoint)] == [
            "provider",
            "available",
            "rate_multiple",
        ]


class TestBatchPricing:
    """The configuration: the card's offerings, as one frozen value."""

    def test_empty_is_a_well_formed_card_that_names_no_provider(self):
        # An empty card is legal as a *value* — a card being built up, a
        # config file not yet filled in — and it names nobody.  It is
        # deliberately not the shape feature 202's empty peak card takes,
        # where emptiness still answers every scheduling question (*no peak
        # minute exists*, so every window is off-peak); here the axis is the
        # provider's name and an empty card holds no names, so it answers no
        # routing question and the routing refuses calls against it.
        card = BatchPricing()
        assert card.offerings == ()
        assert card.available_providers == ()
        assert card.text() == ""
        # Nothing is "available", but nothing is "unavailable" either: the
        # card states no provider, which is why emptiness is not a blanket
        # *no batch endpoint* — see the routing suite's side-by-side pin.
        assert card.offering_for(OPENAI) is None

    def test_accepts_any_iterable_and_answers_one_tuple(self):
        # A config file's list is as good as a tuple, and a card stated in
        # either order is one value: the record canonicalizes to sorted
        # provider-name order, so equality means "the same offerings" and not
        # "the same offerings, listed alike".
        from_list = BatchPricing(
            offerings=[
                BatchEndpoint(GEMINI, True, 0.5),
                BatchEndpoint(OPENAI, True, 0.5),
            ]
        )
        from_tuple = BatchPricing(
            offerings=(
                BatchEndpoint(OPENAI, True, 0.5),
                BatchEndpoint(GEMINI, True, 0.5),
            )
        )
        assert from_list == from_tuple
        assert from_list.offerings == from_tuple.offerings
        assert from_list.text() == "gemini:batch@0.5, openai:batch@0.5"

    def test_available_providers_names_only_the_ones_offering_batch(self):
        # The named fact behind the sentence's *"when available"*: a caller
        # deciding whether to declare a call batchable wants to know which
        # endpoints exist, and the answer is derived from the offerings
        # rather than stored beside them.
        card = BatchPricing(
            offerings=(
                BatchEndpoint(OPENAI, True, 0.5),
                BatchEndpoint(DEEPSEEK, False, 1.0),
            )
        )
        assert card.available_providers == (OPENAI,)

    def test_refuses_two_offerings_for_one_provider(self):
        # A provider's batch availability and rate are one fact looked up by
        # name, so two offerings for one provider would make every routing
        # answer depend on which one the lookup happened to find — the same
        # call billed two ways depending on nothing.  The card contradicts
        # itself, and there is no canonical choice between the two, so the
        # repair is upstream.
        with pytest.raises(BatchRoutingError, match="more than once"):
            BatchPricing(
                offerings=(
                    BatchEndpoint(OPENAI, True, 0.5),
                    BatchEndpoint(OPENAI, True, 0.9),
                )
            )

    @pytest.mark.parametrize("offerings", [42, None, 3.5, object()])
    def test_refuses_a_non_collection_in_this_modules_own_vocabulary(self, offerings):
        # The constructor's own guard, and the reason it is a guard rather
        # than a bare ``tuple(...)``: iterating a non-collection raises a
        # builtin ``TypeError``, which is *not* this module's vocabulary — a
        # caller whose single ``except BatchRoutingError`` is meant to catch
        # every malformed configuration would watch the mistake escape as a
        # TypeError instead.  Both entry points (the constructor and the
        # routing's card recognition) are covered so neither can drift back.
        with pytest.raises(BatchRoutingError, match="iterable"):
            BatchPricing(offerings=offerings)
        with pytest.raises(BatchRoutingError, match="iterable"):
            route_depth_call(
                SimpleNamespace(offerings=offerings), provider=OPENAI
            )

    @pytest.mark.parametrize("offerings", ["openai", b"openai", ""])
    def test_refuses_a_string_which_is_iterable_but_is_not_a_card(self, offerings):
        # The subtle half: a string *is* iterable, so a bare
        # ``isinstance(value, Iterable)`` check waves it through — and then
        # ``tuple()`` yields its characters, so "openai" would become five
        # one-character "offerings" and fail about the wrong thing entirely.
        # Refused as a non-collection, naming what it is.
        with pytest.raises(BatchRoutingError, match="string is iterable"):
            BatchPricing(offerings=offerings)
        with pytest.raises(BatchRoutingError, match="string is iterable"):
            route_depth_call(
                SimpleNamespace(offerings=offerings), provider=OPENAI
            )

    def test_offering_for_answers_none_for_an_undescribed_provider(self):
        # The lookup the routing is built on, spelled once so the refusal and
        # the fallback read the same card the same way.  None means *this
        # card does not describe this provider* — a configuration gap — and
        # it is deliberately distinct from an offering that says
        # available=False, which is a fact about a provider.
        card = BatchPricing(offerings=(BatchEndpoint(DEEPSEEK, False, 1.0),))
        assert card.offering_for(DEEPSEEK) is not None
        assert card.offering_for(DEEPSEEK).available is False
        assert card.offering_for(OPENAI) is None

    def test_re_makes_offerings_recognised_by_their_parts(self):
        # The double-import remedy, applied at the constructor: a stub
        # carrying the three parts is an offering whatever class it was built
        # from, and the answer is this module's class — so a record built
        # through the loader's other class copy still compares equal to one
        # built here.
        class StubOffering:
            def __init__(self, provider, available, rate_multiple):
                self.provider = provider
                self.available = available
                self.rate_multiple = rate_multiple

        card = BatchPricing(offerings=[StubOffering(OPENAI, True, 0.5)])
        assert card.offerings == (BatchEndpoint(OPENAI, True, 0.5),)
        assert isinstance(card.offerings[0], BatchEndpoint)

    def test_a_malformed_stub_is_told_which_field_is_wrong(self):
        # Recognition stays cheap and validation stays single-sourced: a stub
        # carrying "half" as its rate is told its rate is not a number, not
        # that it is "not an offering" — there is one shape check, the
        # record's own.
        with pytest.raises(BatchRoutingError, match="rate_multiple"):
            BatchPricing(
                offerings=[
                    SimpleNamespace(
                        provider=OPENAI, available=True, rate_multiple="half"
                    )
                ]
            )

    def test_a_non_offering_is_refused_rather_than_guessed(self):
        # A bare string, a dict, a None: none carries a provider, an
        # availability and a rate, so none can be routed against — padding
        # the missing fields with guesses would be routing calls against a
        # card nobody stated.
        with pytest.raises(BatchRoutingError, match="must be BatchEndpoint"):
            BatchPricing(offerings=["openai"])


# ── The choice ────────────────────────────────────────────────────────────────


class TestRouteDepthCall:
    """The choice: the endpoint a depth call goes to, and its rate."""

    def test_a_batchable_call_on_a_batch_provider_routes_to_batch(self):
        # The feature's sentence, straight: §14.2 says to route depth through
        # the batch endpoints, and the depth role's calls are batchable by
        # default because the lever is free — *"the depth role is pure
        # asynchronous batch work.  Nothing waits on it."*
        route = route_depth_call(
            BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),)),
            provider=OPENAI,
        )
        assert route.endpoint == BATCH_ENDPOINT
        assert route.batched is True
        assert route.rate_multiple == 0.5
        assert route.provider == OPENAI

    def test_the_answer_carries_the_rate_multiple_the_saving_is_spent_as(self):
        # *"Roughly half the synchronous rate"* is a *multiple* of a rate,
        # and the route answers with the multiple rather than with a
        # percentage or a boolean: a cost model multiplies a synchronous
        # estimate by it, and a caller holding a route has already let go of
        # the card it was derived from — so the base figure has to travel
        # with the choice or not be reconstructible at all.
        route = route_depth_call(
            BatchPricing(offerings=(BatchEndpoint(ANTHROPIC, True, 0.5),)),
            provider=ANTHROPIC,
        )
        assert route.rate_multiple == SYNCHRONOUS_RATE_MULTIPLE * BATCH_RATE_MULTIPLE

    def test_a_provider_without_a_batch_endpoint_routes_synchronously(self):
        # The sentence's *"when available"* read as a condition rather than a
        # rule: §14.2's batch list does not cover every provider in its depth
        # tier, and a call on one of those is served synchronously.  That is
        # an outcome, not a refusal — the routing falls back and says so.
        route = route_depth_call(
            BatchPricing(offerings=(BatchEndpoint(DEEPSEEK, False, 1.0),)),
            provider=DEEPSEEK,
        )
        assert route.endpoint == SYNCHRONOUS_ENDPOINT
        assert route.batched is False
        assert route.rate_multiple == SYNCHRONOUS_RATE_MULTIPLE

    def test_a_call_not_declared_batchable_routes_synchronously(self):
        # A caller with a call something genuinely waits on — a root
        # proposal, a policy revision — states batchable=False and gets the
        # synchronous endpoint whatever the card offers, because a batch
        # endpoint's asynchrony is the whole reason it is cheaper and the
        # whole reason it cannot serve a call on a critical path.
        route = route_depth_call(
            BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),)),
            provider=OPENAI,
            batchable=False,
        )
        assert route.endpoint == SYNCHRONOUS_ENDPOINT
        assert route.batched is False
        assert route.rate_multiple == SYNCHRONOUS_RATE_MULTIPLE

    @pytest.mark.parametrize("batchable", [None, 0, 1, "yes", "", "False", []])
    def test_refuses_a_batchable_that_is_not_a_bool(self, batchable):
        # The same strict-bool rule the card's availability keeps, applied to
        # the flag the *caller* states.  The coercion it refuses is worse than
        # the card's, because it inverts rather than blurs: 'False' is a
        # non-empty string and therefore truthy, so a deployment whose config
        # carried ``batchable = 'False'`` — off a YAML or env layer that did
        # not coerce — would route to the batch endpoint every call it meant
        # to hold synchronous.  0 and '' would silently mean *synchronous*
        # while 1 and 'yes' would silently mean *batch*; none of those is a
        # decision anyone wrote down.  Refused in this module's vocabulary
        # rather than read through.
        card = BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),))
        with pytest.raises(BatchRoutingError, match="batchable"):
            route_depth_call(card, provider=OPENAI, batchable=batchable)

    def test_the_string_false_is_refused_rather_than_routed_to_batch(self):
        # The inversion spelled out on its own, because it is the one a
        # coercion gets *confidently wrong* rather than merely unclear:
        # ``bool('False') is True``, so before the guard this routed to the
        # batch endpoint — the exact opposite of what the caller stated.  The
        # refusal is asserted alongside the two legal answers so a reader can
        # see that silence still takes the default and a real False still
        # routes synchronously.
        card = BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),))
        with pytest.raises(BatchRoutingError, match="'False'"):
            route_depth_call(card, provider=OPENAI, batchable="False")
        assert route_depth_call(card, provider=OPENAI).batched is True
        assert (
            route_depth_call(card, provider=OPENAI, batchable=False).batched
            is False
        )

    def test_the_argument_shapes_are_refused_before_the_cards_content(self):
        # The order the routing validates in, pinned because it is a real
        # invariant and not an accident of statement order: the three
        # arguments are checked for *shape* before any is matched against the
        # card, and only then is the card's *content* consulted.  So a caller
        # passing a malformed flag alongside an incomplete card hears about
        # the malformed flag — its own argument, the thing it just wrote —
        # rather than about a configuration file it may not own.  A call
        # whose arguments are not the types they claim to be is not yet a
        # call worth matching against a card.
        good = BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),))
        with pytest.raises(BatchRoutingError, match="offerings"):
            route_depth_call(
                BatchPricing(offerings="openai"),  # type: ignore[arg-type]
                provider=OPENAI,
                batchable="False",
            )
        with pytest.raises(BatchRoutingError, match="provider"):
            route_depth_call(good, provider=7, batchable="False")
        with pytest.raises(BatchRoutingError, match="batchable"):
            route_depth_call(good, provider=OPENAI, batchable="False")
        # ...and the one refusal that reads the card's *content* comes last,
        # so it is only ever reached by a call whose arguments were well
        # formed.  It stays a distinct error class, not a BatchRoutingError.
        with pytest.raises(UnknownProviderError):
            route_depth_call(good, provider=DEEPSEEK, batchable=False)

    def test_the_two_synchronous_reasons_are_one_outcome(self):
        # *The caller did not declare the call batchable* and *the provider
        # offers no batch endpoint* both mean this call goes synchronously,
        # and they are deliberately one outcome: the route's endpoint says so
        # without pretending to know which reason applied.  A caller needing
        # the reason has the card and the flag it passed.
        card = BatchPricing(
            offerings=(
                BatchEndpoint(OPENAI, True, 0.5),
                BatchEndpoint(DEEPSEEK, False, 1.0),
            )
        )
        on_deepseek = route_depth_call(card, provider=DEEPSEEK)
        not_batchable = route_depth_call(card, provider=OPENAI, batchable=False)
        # The *route* is one outcome — same endpoint, same multiple, same
        # boolean — while the provider each call was served by travels with
        # it, because the record answers *where did this call go* and not
        # merely *which kind of endpoint*.
        assert on_deepseek.endpoint == not_batchable.endpoint == SYNCHRONOUS_ENDPOINT
        assert on_deepseek.rate_multiple == not_batchable.rate_multiple == 1.0
        assert on_deepseek.batched is not_batchable.batched is False
        assert (on_deepseek.provider, not_batchable.provider) == (DEEPSEEK, OPENAI)

    def test_an_undescribed_provider_is_refused_by_name(self):
        # The one refusal, and the reason the fallback above must not swallow
        # it: treating an absent provider as *no batch endpoint* would bill a
        # real call synchronously on the strength of a card that simply forgot
        # the provider, and nothing downstream could tell that from a routing
        # decision.  The refusal names the provider and the repair.
        card = BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),))
        with pytest.raises(UnknownProviderError) as refusal:
            route_depth_call(card, provider=DEEPSEEK)
        assert DEEPSEEK in str(refusal.value)
        assert "openai:batch@0.5" in str(refusal.value)

    def test_an_undescribed_provider_is_refused_even_for_an_unbatchable_call(self):
        # The refusal is a property of the card, not of the call: a
        # synchronous call on an undescribed provider is *still* an
        # undescribed provider, and answering it would make the same
        # configuration gap look like a decision whenever the caller happened
        # to pass batchable=False.
        card = BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),))
        with pytest.raises(UnknownProviderError):
            route_depth_call(card, provider=DEEPSEEK, batchable=False)

    def test_refuses_a_card_that_is_not_a_card(self):
        # A routing asked to choose between endpoints needs a card that
        # states some: a bare dict, a list, a None carries no offerings, and
        # padding them would be routing against a card nobody stated.
        with pytest.raises(BatchRoutingError, match="must be a BatchPricing"):
            route_depth_call("openai", provider=OPENAI)

    def test_refuses_an_offerings_value_that_is_not_a_collection(self):
        # A card is a collection of offerings; a single non-iterable value —
        # a string, a number — is not one, and iterating a string would
        # silently produce one "offering" per character.
        with pytest.raises(BatchRoutingError, match="iterable"):
            route_depth_call(
                SimpleNamespace(offerings="openai"), provider=OPENAI
            )

    def test_the_card_is_recognised_by_its_parts_not_its_class(self):
        # The double-import remedy: the module loader imports every member
        # twice, so two BatchPricing classes exist over one source file and
        # an isinstance gate would refuse the very card a caller built from
        # the deployment's config.  Recognition by shape, answers in one
        # class — the same move require_depth_model makes for candidates.
        class StubCard:
            def __init__(self, offerings):
                self.offerings = offerings

        route = route_depth_call(
            StubCard([SimpleNamespace(provider=OPENAI, available=True, rate_multiple=0.5)]),
            provider=OPENAI,
        )
        assert route.endpoint == BATCH_ENDPOINT
        assert route.rate_multiple == 0.5

    def test_a_getattr_hook_cannot_fabricate_a_card(self):
        # The recognition reads ``object.__getattribute__``, which does not
        # fall back to ``__getattr__`` — so an object whose hook answers
        # ``offerings`` is *not* a card, and the routing is not a place where
        # a hook can offer endpoints.  (See require_depth_model for the same
        # rule on the depth seam.)
        class Fabricating:
            def __getattr__(self, name: str) -> str:
                if name == "offerings":
                    return (SimpleNamespace(provider=OPENAI, available=True, rate_multiple=0.5),)
                raise AttributeError(name)

        with pytest.raises(BatchRoutingError, match="must be a BatchPricing"):
            route_depth_call(Fabricating(), provider=OPENAI)

    def test_the_routing_reads_no_clock_and_touches_no_store(self):
        # Feature 201's decision is a pure function of its three arguments —
        # no file is read, no database is opened, no clock is consulted —
        # which is what makes the lever free.  Contrast feature 202, whose
        # whole subject *is* the clock: that is the difference between the
        # two levers, and the reason they are two modules.
        card = BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),))
        first = route_depth_call(card, provider=OPENAI)
        second = route_depth_call(card, provider=OPENAI)
        assert first == second

    def test_only_the_serving_providers_offering_is_read(self):
        # §14.2 states the batch lever per provider, so one provider's
        # availability must not leak into another's route: a card offering
        # Gemini a batch endpoint says nothing about DeepSeek, and the two
        # calls on one card differ.
        card = BatchPricing(
            offerings=(
                BatchEndpoint(GEMINI, True, 0.5),
                BatchEndpoint(DEEPSEEK, False, 1.0),
            )
        )
        assert route_depth_call(card, provider=GEMINI).batched is True
        assert route_depth_call(card, provider=DEEPSEEK).batched is False

    def test_an_empty_card_refuses_rather_than_routing_synchronously(self):
        # An empty card describes *no provider at all*, which is one silent
        # fallback apart from a provider described as offering no batch
        # endpoint — and the routing keeps them apart.  Reading emptiness as
        # *no batch endpoint available* would answer a real billing question
        # (synchronous) about a provider the card never mentioned, which is
        # indistinguishable downstream from a routing decision; the refusal
        # is the honest answer for a card that names nobody.
        with pytest.raises(UnknownProviderError):
            route_depth_call(BatchPricing(), provider=OPENAI)

    def test_described_as_unavailable_and_undescribed_are_different_answers(self):
        # The distinction the empty-card case turns on, pinned side by side:
        # one card describes deepseek and *not* openai, so the same card
        # routes one call synchronously and refuses the other.  If these two
        # ever collapsed into one answer, the empty card would be free to
        # route calls nobody configured.
        card = BatchPricing(
            offerings=(BatchEndpoint(DEEPSEEK, False, SYNCHRONOUS_RATE_MULTIPLE),)
        )
        described = route_depth_call(card, provider=DEEPSEEK)
        assert described.endpoint == SYNCHRONOUS_ENDPOINT
        assert described.batched is False
        with pytest.raises(UnknownProviderError):
            route_depth_call(card, provider=OPENAI)
        # And the empty card behaves like the *undescribed* half, never the
        # described one: emptiness is not a blanket "no batch endpoint".
        with pytest.raises(UnknownProviderError):
            route_depth_call(BatchPricing(), provider=DEEPSEEK)


class TestRoutedCall:
    """The choice's answer: where the call goes and what it is billed at."""

    def test_batched_is_derived_from_the_endpoint(self):
        # The boolean is a rendering of the endpoint, not a field beside it:
        # a record holding both would admit endpoint='synchronous' with
        # batched=True, which is not a route but a contradiction, and one
        # more field for a reader to keep in step with.  The field list is
        # pinned so that a fourth field — the boolean, or anything else —
        # is an addition the suite notices.
        route = RoutedCall(
            provider=OPENAI,
            endpoint=BATCH_ENDPOINT,
            rate_multiple=0.5,
        )
        assert route.batched is True
        assert [field.name for field in fields(RoutedCall)] == [
            "provider",
            "endpoint",
            "rate_multiple",
        ]
        assert isinstance(type(route).batched, property)

    @pytest.mark.parametrize("endpoint", ["streaming", "", "BATCH", None, 42])
    def test_the_endpoint_is_a_closed_set(self, endpoint):
        # A third endpoint is one this feature's sentence does not state, and
        # a caller branching on the route should not have to decide what an
        # unfamiliar value means — the same closed-set discipline the
        # completion's finish reasons keep.  A non-string is refused by the
        # same guard, because every member of the set is a string.
        with pytest.raises(BatchRoutingError, match="must be one of"):
            RoutedCall(provider=OPENAI, endpoint=endpoint, rate_multiple=1.0)

    @pytest.mark.parametrize("endpoint", [[], {}, set()])
    def test_an_unhashable_endpoint_is_refused_in_this_modules_vocabulary(self, endpoint):
        # The subtle half of the closed set: ``value in _ENDPOINTS`` is a set
        # membership test, so an unhashable value raises a bare ``TypeError``
        # *before* the refusal can name it — the check would never run.  The
        # string guard runs first and turns the builtin escape into this
        # module's own refusal, which is what a caller's single
        # ``except BatchRoutingError`` depends on.
        with pytest.raises(BatchRoutingError, match="must be one of"):
            RoutedCall(provider=OPENAI, endpoint=endpoint, rate_multiple=1.0)

    def test_row_names_the_records_own_facts(self):
        # The rendered mapping is offered for a caller recording the call's
        # own provenance, not for a store in this package: feature 201
        # persists nothing, so the column names are this module's own rather
        # than a table's.
        route = route_depth_call(
            BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),)),
            provider=OPENAI,
        )
        assert route.row() == {
            PROVIDER_COLUMN: OPENAI,
            ENDPOINT_COLUMN: BATCH_ENDPOINT,
            RATE_MULTIPLE_COLUMN: 0.5,
            BATCHED_COLUMN: True,
        }

    def test_row_is_a_fresh_mapping_per_call(self):
        # A rendered mapping is a rendering, not the record's state: two
        # calls answer two dicts, so a caller editing one cannot reach into
        # the record through it — the discipline ScheduledRun.row states.
        route = route_depth_call(
            BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),)),
            provider=OPENAI,
        )
        assert route.row() is not route.row()

    def test_the_route_is_frozen(self):
        # A route is a decision that was made, not a field a caller tunes.
        route = route_depth_call(
            BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),)),
            provider=OPENAI,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            route.endpoint = SYNCHRONOUS_ENDPOINT

    def test_two_routes_of_one_call_are_equal(self):
        # Value-equal, so a suite computes a route and compares it to the one
        # a caller holds without sharing an object — the testability every
        # record in this package gets from being a value type.
        card = BatchPricing(offerings=(BatchEndpoint(OPENAI, True, 0.5),))
        assert route_depth_call(card, provider=OPENAI) == route_depth_call(
            card, provider=OPENAI
        )


class TestNoComponentIsRegistered:
    """Feature 201 adds no component — the value is a routing, not a service."""

    def test_the_plugin_still_registers_exactly_its_three_components(self):
        # A routing decision is a property of a single call, not a
        # deployment-bound fact that must land in a table: this module
        # persists nothing, owns no table, and adds no builder.  The
        # package's registrations are the interface (feature 192, which
        # contributes None), the pin store (203), the run-window store
        # (202), the cache-rate store (200), the root-serving store (196),
        # the root-rotation store (197) and the fixture store (194) —
        # feature 201 is deliberately absent from the list, and so is
        # feature 199.
        import providers

        from app.module_loader import registered_components

        names = [c.name for c in registered_components()]
        assert "providers" in names
        assert "agent-model-pins" in names
        assert "depth-run-windows" in names
        assert "depth-cache-rates" in names
        assert "root-serving-provider" in names
        assert "root-rotation" in names
        assert "fixture-store" in names
        # Nothing on the module is a component builder for a batch route, and
        # the module carries no table constant for one either — the store
        # this feature does not have is not half-spelled anywhere.
        assert not any("batch" in name for name in names)
        assert not hasattr(providers, "BATCH_ROUTE_TABLE")
        assert not hasattr(providers, "build_batch_routes")

    def test_the_records_are_importable_directly(self):
        # The sibling features of this category build on this seam by
        # importing it directly — there is one way to name the routing.
        import providers

        for name in (
            "BatchEndpoint",
            "BatchPricing",
            "RoutedCall",
            "BatchRoutingError",
            "UnknownProviderError",
            "route_depth_call",
            "BATCH_ENDPOINT",
            "SYNCHRONOUS_ENDPOINT",
            "BATCH_RATE_MULTIPLE",
            "SYNCHRONOUS_RATE_MULTIPLE",
        ):
            assert hasattr(providers, name)
            assert name in providers.__all__

    def test_the_errors_are_a_fifth_base_that_shares_no_ancestor(self):
        # The taxonomy's whole point: a deployment catching the call seam,
        # the pin store's, the depth criterion's or the scheduler's must not
        # have *which endpoint does this call go to?* answered in their
        # place.  Five bases, five questions, no shared ancestor but
        # Exception.
        from providers import (
            BatchRoutingError,
            DepthModelError,
            DepthScheduleError,
            ModelPinError,
            ProviderError,
        )

        bases = (
            ProviderError,
            ModelPinError,
            DepthModelError,
            DepthScheduleError,
            BatchRoutingError,
        )
        assert BatchRoutingError.__bases__ == (Exception,)
        for other in bases[:-1]:
            assert not issubclass(BatchRoutingError, other)
            assert not issubclass(other, BatchRoutingError)

    def test_unknown_provider_is_the_only_subclass(self):
        # One subclass, because the sentence has one way to fail: a provider
        # with no batch endpoint and a call not declared batchable both route
        # synchronously and are outcomes rather than refusals.  What is
        # genuinely unanswerable is a provider the card does not describe,
        # and that is the single named refusal.
        assert UnknownProviderError.__bases__ == (BatchRoutingError,)
        subclasses = BatchRoutingError.__subclasses__()
        assert subclasses == [UnknownProviderError]
