"""Feature 200: the depth model is selected on cache-hit price, and the rate is measured.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 200: *System
persists the measured cache hit rate per campaign, because the depth model
is selected on cache-hit input price rather than list price.*  This file
holds the two halves the sentence joins that need no database — the
**configuration** (a card stating models' list and cache-hit prices) and
the **choice** (the selection over that card) — plus the record the
measurement answers.  The persistence itself — the store, its table, its
idempotence and its refusals — is :mod:`tests.test_cache_store`, and the
wiring is :mod:`tests.test_cache_component`.

The suite's fixture card is §14.2's own depth row (*"Cache-hit price
dominates.  DeepSeek's $0.006 is ~80× below Claude's cached input and ~4×
below Gemini's"*), and the load-bearing property of that row is the
disagreement: the model with the **cheaper list** price (Gemini, $0.25
against DeepSeek's $0.30) is the one with the **dearer hit** ($0.024
against $0.006).  A selection over this card is the sentence's *rather
than* as one comparison, which is why the headline test below asks the
question both ways — what the hit picks, and what the list would have
picked — and holds that the two answers differ.  It is test data, not a
default the module carries; §14.2's own preamble (*"rates move monthly …
the numbers are not"*) is why the module holds only the comparison.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

import pytest
from providers import (
    CachePrice,
    CachePricing,
    DepthCacheError,
    MeasuredCacheRate,
    SelectedDepthModel,
    UnpricedModelError,
    select_depth_model,
)

# ── The configuration's unit: one model's cache price ─────────────────────────


class TestCachePrice:
    """The configuration's unit: one model's list and cache-hit prices."""

    def test_accepts_the_row_the_document_states(self):
        # §14.2's own DeepSeek entry — $0.30 list, $0.006/M cache hits — as
        # the record expects it.  Constructing it is not the selection; a
        # card entry is a description, and describing one is not ranking by
        # it (the same split a 262K DepthModel enjoys).
        price = CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006)
        assert price.model == "deepseek-flash"
        assert price.input_price == 0.30
        assert price.cache_hit_price == 0.006

    def test_the_canonical_text_spells_list_then_hit(self):
        # The form refusals quote and humans read, in the order that keeps
        # the sentence's two axes visible wherever the card is named.
        price = CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006)
        assert price.text() == "deepseek-flash:0.3/0.006"

    def test_a_card_may_state_no_cache_discount_at_all(self):
        # A provider that offers no prompt caching is a stated fact — the
        # hit costs what the miss costs — not an omitted field: the card
        # entry states both prices or the model has none, which is the one
        # shape that leaves the selection no list price to fall back on.
        flat = CachePrice(model="plain-provider", input_price=0.10, cache_hit_price=0.10)
        assert flat.cache_hit_price == flat.input_price

    def test_a_free_hit_is_a_stated_price(self):
        # The self-hosted tier: serving the cached prefix costs nothing,
        # which is a price of zero rather than a missing entry — the
        # selection reads it as the cheapest hit there is.
        free = CachePrice(model="self-hosted", input_price=0.60, cache_hit_price=0.0)
        assert free.cache_hit_price == 0.0

    def test_int_prices_are_prices(self):
        # A whole-dollar card entry is not a different kind of fact from a
        # fractional one; the record holds numbers, and $1 is 1.
        assert CachePrice(model="claude-haiku-4-5", input_price=1, cache_hit_price=0.48).input_price == 1.0

    def test_refuses_a_model_that_is_not_a_name(self):
        # Config noise — a card keyed by a number, or by None — cannot be
        # matched to a candidate, so it is refused rather than keyed.
        with pytest.raises(DepthCacheError, match="must be a string"):
            CachePrice(model=42, input_price=0.30, cache_hit_price=0.006)

    def test_refuses_a_blank_model(self):
        # A blank name describes no model, and every candidate is matched
        # to its price by this name — an entry nothing can match is one
        # the card cannot answer with.
        with pytest.raises(DepthCacheError, match="non-empty"):
            CachePrice(model="  ", input_price=0.30, cache_hit_price=0.006)

    def test_canonicalizes_a_padded_model_name(self):
        # The name is a lookup key: whitespace a config file happened to
        # carry must not make one model into two.
        assert CachePrice(model=" deepseek-flash ", input_price=0.30, cache_hit_price=0.006).model == "deepseek-flash"

    @pytest.mark.parametrize("field", ["input_price", "cache_hit_price"])
    def test_refuses_a_price_that_is_not_a_number(self, field):
        # A string off a rate card's own page ('$0.006') is config noise a
        # selection would otherwise rank on, and a comparison handed a
        # string fails much further from the mistake than this guard does.
        kwargs = {"input_price": 0.30, "cache_hit_price": 0.006}
        kwargs[field] = "$0.006"
        with pytest.raises(DepthCacheError, match="must be a number"):
            CachePrice(model="deepseek-flash", **kwargs)

    @pytest.mark.parametrize("field", ["input_price", "cache_hit_price"])
    def test_refuses_a_bool_where_a_price_belongs(self, field):
        # True is the integer 1: a flag read as a price would silently
        # rank a model at a dollar per million tokens while claiming to be
        # a stated card.
        kwargs = {"input_price": 0.30, "cache_hit_price": 0.006}
        kwargs[field] = True
        with pytest.raises(DepthCacheError, match="must be a number"):
            CachePrice(model="deepseek-flash", **kwargs)

    @pytest.mark.parametrize("field", ["input_price", "cache_hit_price"])
    def test_refuses_a_price_that_is_not_finite(self, field):
        # NaN compares false against every value and would sort the model
        # it names to an arbitrary position; infinity is a price no
        # campaign can pay.  Either would let the selection name a model
        # on a number that is not one.
        kwargs = {"input_price": 0.30, "cache_hit_price": 0.006}
        kwargs[field] = float("nan")
        with pytest.raises(DepthCacheError, match="finite"):
            CachePrice(model="deepseek-flash", **kwargs)

    @pytest.mark.parametrize("field", ["input_price", "cache_hit_price"])
    def test_refuses_a_negative_price(self, field):
        # A price below zero is not a cheap card but a malformed field:
        # the provider that pays the campaign to read its cache does not
        # exist, and a comparison that ranked it would be selecting on
        # nonsense.
        kwargs = {"input_price": 0.30, "cache_hit_price": 0.006}
        kwargs[field] = -0.01
        with pytest.raises(DepthCacheError, match="non-negative"):
            CachePrice(model="deepseek-flash", **kwargs)

    def test_refuses_a_hit_dearer_than_the_miss(self):
        # A cache hit is the same token served from a prefix the provider
        # already holds — it is what the discount is a discount *of* — so
        # a hit above the list price contradicts the feature's own premise
        # rather than describing an unusual provider, and ranking on it
        # would select the model that punishes the depth role's access
        # pattern most.
        with pytest.raises(DepthCacheError, match="must not exceed"):
            CachePrice(model="inverted", input_price=0.01, cache_hit_price=0.30)

    def test_the_record_is_frozen(self):
        # A price is a fact about a provider's rate card, not a field a
        # caller tunes; the record of a fact does not edit.
        price = CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006)
        with pytest.raises(dataclasses.FrozenInstanceError):
            price.input_price = 0.25  # type: ignore[misc]


# ── The configuration: the card ───────────────────────────────────────────────


class TestCachePricing:
    """The frozen collection of the card's prices, one per model."""

    def test_an_empty_card_is_legal_and_describes_no_model(self):
        # Well-formed — a card built incrementally, a config file not yet
        # filled in — and it answers no selection question, which is the
        # selection's refusal to make rather than the record's to prevent.
        empty = CachePricing()
        assert empty.prices == ()
        assert empty.priced_models == ()
        assert empty.text() == ""

    def test_the_card_is_canonicalized_into_model_order(self):
        # Two cards stating the same prices in different orders are one
        # value, so a card read from a config file compares equal to the
        # card a suite built.
        one = CachePricing(
            prices=(
                CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),
                CachePrice(model="gemini-3.1-flash-lite", input_price=0.25, cache_hit_price=0.024),
            )
        )
        two = CachePricing(
            prices=(
                CachePrice(model="gemini-3.1-flash-lite", input_price=0.25, cache_hit_price=0.024),
                CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),
            )
        )
        assert one == two
        assert one.prices == tuple(sorted(one.prices, key=lambda p: p.model))

    def test_a_list_of_prices_is_a_card(self):
        # Any iterable is accepted — a config file's list as naturally as
        # a tuple a caller built — and answered as the immutable tuple.
        card = CachePricing(
            prices=[
                CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006)
            ]
        )
        assert isinstance(card.prices, tuple)

    def test_priced_models_names_the_card_in_model_order(self):
        # The named fact behind "selected on cache-hit input price": which
        # models the card can rank, before a caller offers candidates.
        card = CachePricing(
            prices=(
                CachePrice(model="gemini-3.1-flash-lite", input_price=0.25, cache_hit_price=0.024),
                CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),
            )
        )
        assert card.priced_models == ("deepseek-flash", "gemini-3.1-flash-lite")

    def test_the_cards_text_joins_the_prices_sorted(self):
        # The determinism the card's own spelling owes: two cards stating
        # the same prices spell the same.
        card = CachePricing(
            prices=(
                CachePrice(model="gemini-3.1-flash-lite", input_price=0.25, cache_hit_price=0.024),
                CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),
            )
        )
        assert card.text() == "deepseek-flash:0.3/0.006, gemini-3.1-flash-lite:0.25/0.024"

    def test_price_for_finds_the_entry_by_name(self):
        # The lookup the selection is built on: matched by the model's
        # name, answered with the entry itself.
        card = CachePricing(
            prices=(CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),)
        )
        assert card.price_for("deepseek-flash") == CachePrice(
            model="deepseek-flash", input_price=0.30, cache_hit_price=0.006
        )

    def test_price_for_answers_none_for_an_unpriced_model(self):
        # None means *this card does not price this model* — a
        # configuration gap the selection refuses by name, not a fact the
        # lookup interprets.  A padded name still finds its entry,
        # because the name is a key.
        card = CachePricing(
            prices=(CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),)
        )
        assert card.price_for("claude-haiku-4-5") is None
        assert card.price_for(" deepseek-flash ") == card.price_for("deepseek-flash")

    def test_refuses_a_model_priced_twice(self):
        # A model's cache pricing is one fact looked up by name; two
        # prices for one model would make every selection answer depend on
        # which one the lookup found — the same model selected two ways
        # depending on nothing.
        with pytest.raises(DepthCacheError, match="more than once"):
            CachePricing(
                prices=(
                    CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),
                    CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.012),
                )
            )

    def test_refuses_a_string_where_the_prices_belong(self):
        # A string is iterable but is not a collection of prices: reading
        # one would yield its characters, and a card nobody wrote is worse
        # than a refusal.
        with pytest.raises(DepthCacheError, match="iterable of"):
            CachePricing(prices="deepseek")

    def test_refuses_a_non_iterable(self):
        # A single value is not a card this selection may rank a candidate
        # against.
        with pytest.raises(DepthCacheError, match="iterable of"):
            CachePricing(prices=42)

    def test_refuses_an_entry_that_is_not_a_price(self):
        # A value carrying no model, no list price and no hit price cannot
        # be padded with guesses — that would be selecting models against
        # a card nobody stated.
        with pytest.raises(DepthCacheError, match="must be CachePrice records"):
            CachePricing(prices=(42,))

    def test_re_makes_a_foreign_price_from_its_parts(self):
        # The double-import remedy, applied at the constructor: anything
        # carrying the three named parts is the value — the loader's other
        # class copy over this same source file, or a config layer's
        # record — and the card answers with this module's class, so
        # equality downstream means what it says.
        class Foreign:
            model = "deepseek-flash"
            input_price = 0.30
            cache_hit_price = 0.006

        card = CachePricing(prices=(Foreign(),))
        assert card.prices == (
            CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),
        )

    def test_the_card_is_frozen(self):
        # A card configured twice compares equal, and one a caller holds
        # cannot be edited into a different configuration.
        card = CachePricing()
        with pytest.raises(dataclasses.FrozenInstanceError):
            card.prices = ()  # type: ignore[misc]


# ── The choice: the selection ─────────────────────────────────────────────────


class TestSelectDepthModel:
    """§14.1's instruction as one comparison: lowest cache-hit input price."""

    def test_selects_on_the_hit_not_the_list(self, depth_cache_card, depth_candidates):
        # The headline.  Over §14.2's own depth row, the model with the
        # cheaper list price (Gemini, $0.25) is 4× dearer on the hit
        # ($0.024 against $0.006), and the selection picks DeepSeek —
        # which is what ranking on the cache-hit price looks like, and the
        # sentence's *rather than* is the whole finding.
        chosen = select_depth_model(depth_cache_card, candidates=depth_candidates)
        assert chosen.model == "deepseek-flash"

    def test_the_answer_carries_both_prices_and_the_disagreement(
        self, depth_cache_card, depth_candidates
    ):
        # A caller handed the answer sees the axis the choice turned on:
        # the cheap hit *and* the dearer miss beside it.  On this card the
        # winner's list price is *above* the list price of the model a
        # list-price ranking would have picked — the disagreement, carried
        # by the answer rather than left for the caller to reconstruct.
        chosen = select_depth_model(depth_cache_card, candidates=depth_candidates)
        assert chosen.input_price == 0.30
        assert chosen.cache_hit_price == 0.006
        list_winner = min(depth_cache_card.prices, key=lambda p: p.input_price)
        assert list_winner.model == "gemini-3.1-flash-lite"
        assert chosen.input_price > list_winner.input_price

    def test_the_answer_is_the_record_a_caller_would_build(self, depth_cache_card, depth_candidates):
        # Value-equal to the hand-built record, so a choice a suite
        # computes and a choice a caller holds compare equal.
        chosen = select_depth_model(depth_cache_card, candidates=depth_candidates)
        assert chosen == SelectedDepthModel(
            model="deepseek-flash", input_price=0.30, cache_hit_price=0.006
        )

    def test_the_cache_advantage_answers_the_documents_figure(
        self, depth_cache_card, depth_candidates
    ):
        # §14.1's "Prompt caching is worth 4–5× here" is an instance of
        # this quotient: on the chosen card a hit is 50× cheaper than a
        # miss.  Derived, never stored — the two prices are the record.
        chosen = select_depth_model(depth_cache_card, candidates=depth_candidates)
        assert chosen.cache_advantage == pytest.approx(50.0)

    def test_the_cache_advantage_of_a_free_hit_is_not_a_number(self):
        # The self-hosted tier: the multiple is unbounded rather than
        # small, and pretending it was zero would read the largest
        # possible advantage as none.
        chosen = SelectedDepthModel(model="self-hosted", input_price=0.60, cache_hit_price=0.0)
        assert chosen.cache_advantage is None

    def test_a_tie_on_the_hit_breaks_on_the_cheaper_miss(self):
        # Two models whose hits cost the same are separated by their list
        # prices — the secondary axis is consulted only where the primary
        # one failed to separate, which is the one place it must come from
        # somewhere.
        card = CachePricing(
            prices=(
                CachePrice(model="dear-miss", input_price=0.50, cache_hit_price=0.01),
                CachePrice(model="cheap-miss", input_price=0.30, cache_hit_price=0.01),
            )
        )
        candidates = (
            _candidate("dear-miss"),
            _candidate("cheap-miss"),
        )
        assert select_depth_model(card, candidates=candidates).model == "cheap-miss"

    def test_a_remaining_tie_breaks_on_the_name_and_only_for_totality(self):
        # Same hit, same list: the name decides, so the same card and the
        # same candidates always select the same model whatever order they
        # were stated in — determinism, not a third criterion.
        card = CachePricing(
            prices=(
                CachePrice(model="aaa", input_price=0.30, cache_hit_price=0.01),
                CachePrice(model="bbb", input_price=0.30, cache_hit_price=0.01),
            )
        )
        forward = (_candidate("aaa"), _candidate("bbb"))
        backward = tuple(reversed(forward))
        assert select_depth_model(card, candidates=forward).model == "aaa"
        assert select_depth_model(card, candidates=backward).model == "aaa"

    def test_the_selection_picks_the_free_hit_when_one_is_offered(self):
        # A self-hosted candidate at a zero hit price wins over any hosted
        # card — the cheapest hit there is, stated rather than implied.
        card = CachePricing(
            prices=(
                CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),
                CachePrice(model="self-hosted", input_price=0.60, cache_hit_price=0.0),
            )
        )
        chosen = select_depth_model(card, candidates=(_candidate("deepseek-flash"), _candidate("self-hosted")))
        assert chosen.model == "self-hosted"

    def test_a_single_candidate_is_selected(self, depth_cache_card):
        # The degenerate but legal offering: one survivor of feature 198's
        # gate, priced, selected.  The selection is a comparison, and one
        # candidate is the smallest one there is.
        chosen = select_depth_model(depth_cache_card, candidates=(_candidate("claude-haiku-4-5"),))
        assert chosen.model == "claude-haiku-4-5"
        assert chosen.input_price == 1.00

    def test_refuses_a_candidate_the_card_does_not_price(self, depth_cache_card):
        # The load-bearing refusal: the alternative a silent skip invites
        # is the list-price fallback, the exact failure the sentence's
        # *because* exists to prevent.  The refusal names the model and
        # the card, so the repair is a card entry rather than a guess.
        with pytest.raises(UnpricedModelError, match="'qwen-4-max'"):
            select_depth_model(
                depth_cache_card,
                candidates=(_candidate("deepseek-flash"), _candidate("qwen-4-max")),
            )

    def test_an_empty_card_refuses_the_first_candidate_by_name(self):
        # An empty card holds no names, so the first candidate offered
        # against it is the one the refusal names — the same move an empty
        # batch card forces, and deliberately not the flat-by-day reading
        # an empty peak card takes: a lookup by name reads emptiness as
        # *nothing is configured here*.
        with pytest.raises(UnpricedModelError, match="'deepseek-flash'"):
            select_depth_model(CachePricing(), candidates=(_candidate("deepseek-flash"),))

    def test_the_unpriced_refusal_quotes_the_card_it_asked_for(self):
        # The caller learns what the card *does* state, because that is
        # the difference between an actionable refusal and a complaint.
        card = CachePricing(
            prices=(CachePrice(model="deepseek-flash", input_price=0.30, cache_hit_price=0.006),)
        )
        with pytest.raises(UnpricedModelError, match="deepseek-flash:0.3/0.006"):
            select_depth_model(card, candidates=(_candidate("claude-haiku-4-5"),))

    def test_refuses_an_empty_offering(self, depth_cache_card):
        # A selection chooses between models; an empty offering names
        # nothing to select and nothing to refuse.
        with pytest.raises(DepthCacheError, match="no candidates"):
            select_depth_model(depth_cache_card, candidates=())

    def test_refuses_a_bare_string_of_candidates(self, depth_cache_card):
        # A string is a name with no description behind it; the caller
        # that meant it as a candidate is a DepthModel away from saying
        # so, and the caller that passed a list of strings by accident is
        # told exactly what shape was wanted.
        with pytest.raises(DepthCacheError, match="iterable of"):
            select_depth_model(depth_cache_card, candidates="deepseek-flash")

    def test_refuses_a_non_iterable_offering(self, depth_cache_card):
        with pytest.raises(DepthCacheError, match="iterable of"):
            select_depth_model(depth_cache_card, candidates=42)

    def test_refuses_a_candidate_carrying_no_model_name(self, depth_cache_card):
        # The selection matches a candidate to its card price by the
        # model's name; a value carrying none cannot be priced.
        with pytest.raises(DepthCacheError, match="must each carry a model"):
            select_depth_model(depth_cache_card, candidates=(42,))

    def test_recognises_a_card_by_its_parts_and_re_makes_it(self, depth_cache_card):
        # The double-import remedy at the selection's own gate: a card
        # carrying the ``prices`` part is the card, whatever class it was
        # built from, and the answer is this module's record.
        class ForeignCard:
            prices = depth_cache_card.prices

        chosen = select_depth_model(ForeignCard(), candidates=(_candidate("deepseek-flash"),))
        assert chosen == SelectedDepthModel(
            model="deepseek-flash", input_price=0.30, cache_hit_price=0.006
        )

    def test_refuses_a_value_that_is_not_a_card(self):
        # A selection asked to rank candidates needs a card that prices
        # some; a value carrying no prices is refused as such.
        with pytest.raises(DepthCacheError, match="must be a CachePricing"):
            select_depth_model(42, candidates=(_candidate("deepseek-flash"),))

    def test_the_answer_is_frozen(self, depth_cache_card, depth_candidates):
        # The record of a choice does not edit.
        chosen = select_depth_model(depth_cache_card, candidates=depth_candidates)
        with pytest.raises(dataclasses.FrozenInstanceError):
            chosen.model = "gemini-3.1-flash-lite"  # type: ignore[misc]

    def test_the_answers_text_is_the_winners_card_text(self, depth_cache_card, depth_candidates):
        # One grammar: a refusal quoting a card and an answer naming its
        # winner read the same way.
        chosen = select_depth_model(depth_cache_card, candidates=depth_candidates)
        assert chosen.text() == "deepseek-flash:0.3/0.006"


def _candidate(name: str):
    """A depth-model candidate carrying only what the selection reads.

    The selection matches candidates to card entries by their ``model``
    name — feature 198's gate owns the window and the threshold — so a
    stub carrying the one part exercises this seam without re-stating
    198's record.  For the tests that want the real record, the
    ``depth_candidates`` fixture holds §14.2's three.
    """
    from providers import DepthModel, flat_pricing

    return DepthModel(
        model=name, context_tokens=1_000_000, surcharge_threshold=flat_pricing()
    )


# ── The measurement's record ──────────────────────────────────────────────────


class TestMeasuredCacheRate:
    """The row's four facts as one value — counts, instant, answer state."""

    def test_the_rate_is_the_exact_quotient_of_the_counts(self):
        # 29/30 is exact as a quotient of the two stored ints and is no
        # binary fraction at all: a float property would round it into a
        # number no two computations agree on, and the comparison a
        # caller most wants to make is exactly the one a rounding blurs.
        record = MeasuredCacheRate(
            campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            input_tokens=30,
            cache_read_tokens=29,
            measured_at=_WEDNESDAY(),
        )
        assert record.hit_rate == Fraction(29, 30)
        assert record.hit_rate != Fraction(29, 31)

    def test_a_zero_rate_is_a_measurement(self):
        # A campaign whose calls never hit cache measured zero, and that
        # is a fact worth persisting — the evidence the premise (a large,
        # stable, shared prefix) did not hold, which is what the next
        # selection should know.
        record = MeasuredCacheRate(
            campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            input_tokens=300_000,
            cache_read_tokens=0,
            measured_at=_WEDNESDAY(),
        )
        assert record.hit_rate == Fraction(0)

    def test_the_row_mapping_names_the_tables_own_columns(self):
        # A rendered mapping names the same things the same way the store
        # does; ``recorded`` is deliberately absent — it is this call's
        # answer state, not a fact of the row.
        record = MeasuredCacheRate(
            campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            input_tokens=30,
            cache_read_tokens=29,
            measured_at=_WEDNESDAY(),
        )
        assert record.row() == {
            "campaign_id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            "input_tokens": 30,
            "cache_read_tokens": 29,
            "measured_at": "2026-09-23T12:00:00.000Z",
        }

    def test_recorded_defaults_to_not_this_call(self):
        # The default is the read-side answer state: any record built
        # without writing is a record some earlier call wrote.
        record = MeasuredCacheRate(
            campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            input_tokens=30,
            cache_read_tokens=29,
            measured_at=_WEDNESDAY(),
        )
        assert record.recorded is False

    def test_refuses_an_id_that_is_not_a_uuid(self):
        # A cache hit rate is measured for a campaign, and the id joins
        # the campaign table's rows — a value that cannot join it names
        # no campaign whose calls could be measured.
        with pytest.raises(DepthCacheError, match="not a UUID"):
            MeasuredCacheRate(
                campaign_id="not-a-campaign",
                input_tokens=30,
                cache_read_tokens=29,
                measured_at=_WEDNESDAY(),
            )

    def test_refuses_a_zero_input_total(self):
        # The denominator of the campaign's hit rate is its billed input;
        # a measurement that read nothing is not a measurement of the
        # depth role's calls, which carry the history.
        with pytest.raises(DepthCacheError, match="zero input"):
            MeasuredCacheRate(
                campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
                input_tokens=0,
                cache_read_tokens=0,
                measured_at=_WEDNESDAY(),
            )

    def test_refuses_a_cache_read_above_the_input(self):
        # The cached prefix is part of the prompt: more cache read than
        # there was prompt to read from is a rate above 1.0, and reading
        # it back as a measurement would launder it into the record a
        # selection's premise is audited by.
        with pytest.raises(DepthCacheError, match="more cache was read"):
            MeasuredCacheRate(
                campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
                input_tokens=30,
                cache_read_tokens=31,
                measured_at=_WEDNESDAY(),
            )

    @pytest.mark.parametrize("field", ["input_tokens", "cache_read_tokens"])
    def test_refuses_a_count_that_is_not_an_int(self, field):
        # A count that is not a count cannot be totalled; guessing an
        # interpretation would be measuring a campaign on an accounting
        # nobody reported.
        kwargs = {"input_tokens": 30, "cache_read_tokens": 29}
        kwargs[field] = 29.5
        with pytest.raises(DepthCacheError, match="must be an int"):
            MeasuredCacheRate(
                campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
                measured_at=_WEDNESDAY(),
                **kwargs,
            )

    def test_refuses_a_naive_instant(self):
        # A naive datetime names no instant, and a measurement stamped
        # with one could not be placed on any timeline an auditor reads.
        from datetime import datetime

        with pytest.raises(DepthCacheError, match="timezone-aware"):
            MeasuredCacheRate(
                campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
                input_tokens=30,
                cache_read_tokens=29,
                measured_at=datetime(2026, 9, 23, 12, 0, 0),  # noqa: DTZ001 - the refusal's subject
            )

    def test_the_record_is_frozen(self):
        # The record of an observation does not edit — a caller who kept a
        # reference cannot turn it into a different measurement.
        record = MeasuredCacheRate(
            campaign_id="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            input_tokens=30,
            cache_read_tokens=29,
            measured_at=_WEDNESDAY(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.cache_read_tokens = 30  # type: ignore[misc]


def _WEDNESDAY():
    """The suite's fixed measuring instant — a Wednesday in September 2026.

    The same discipline the scheduler's suite states: a measurement's
    record is a function of its inputs, and a test that read the clock
    would be testing a different question every time it ran.
    """
    from datetime import UTC, datetime

    return datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
