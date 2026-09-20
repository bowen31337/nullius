"""Feature 66 — the aggressive order walked through the recorded L2 book.

app_spec.xml, "Cost Model & Fill Simulation", feature 66: *System walks
the recorded L2 book for an aggressive order rather than crossing at the
midpoint, which returns a realistic slippage figure.*  The sentence is an
assertion, a rejection and a promise, and each can fail independently, so
the tests take them one at a time:

* **walks the recorded L2 book** — the fill is consumption: levels taken
  best-first, the last one partial, the fill price the volume-weighted
  average of exactly the levels consumed.  No level is skipped and no
  unrecorded price enters the average.
* **for an aggressive order** — the side picks the ladder: a buy lifts
  asks, a sell hits bids, and the two never swap.
* **rather than crossing at the midpoint** — the midpoint is the
  reference, not the fill.  The naive model it replaces reported zero
  crossing cost *by construction*; the walk measures its figure against
  that same midpoint, so even an order too small to move the book pays
  the half-spread the naive model zeroed.
* **returns a realistic slippage figure** — adverse-positive on both
  sides, in basis points, decomposing exactly into the half-spread and
  the depth impact.

And the two refusals that keep the figure realistic: an order beyond the
recorded depth is refused rather than extrapolated, and a document whose
``walk_book`` is not ``true`` is refused rather than fallen back from —
the only behaviour the flag could otherwise name is the midpoint crossing
the sentence rules out, and the library does not carry it.

:mod:`cost_model.book_walk` owns the walk and its values; the service
tests at the end pin that the composed component resolves the model from
the one cached parse.
"""

from __future__ import annotations

import pytest
from cost_model import (
    AggressiveFillModel,
    AggressiveOrder,
    BookLevel,
    BookWalk,
    CostModelConfig,
    CostModelConfigError,
    CostModelFillError,
    CostModelService,
    RecordedBook,
    resolve_aggressive_fill_model,
    walk_recorded_book,
)
from cost_model.book_walk import BUY, SELL
from cost_model.config import read_cost_model_document

# A one-level-each-side book: mid 100.0, both touches 1.0 away.  The
# simplest book a walk can be priced against, and the one where the
# midpoint model's defect is starkest — it fills a buy at 100.0, a price
# no level ever quoted.
TOUCH_BOOK = RecordedBook(
    bids=[BookLevel(price=99.0, quantity=10.0)],
    asks=[BookLevel(price=101.0, quantity=10.0)],
)

# A three-deep ask ladder with a thin top: mid 99.75, and a 4-unit buy
# must reach the second level.  The book the worked example in the module
# docstring prices.
LADDER_BOOK = RecordedBook(
    bids=[BookLevel(price=99.0, quantity=100.0)],
    asks=[
        BookLevel(price=100.5, quantity=2.0),
        BookLevel(price=101.0, quantity=3.0),
        BookLevel(price=101.5, quantity=10.0),
    ],
)

# A ladder with a hair-thin touch: mid 99.25, one unit bid at 98.0 and
# then a long way down to 80.0.  A 3-unit sell pays 1.25 to reach the
# touch and then dumps two units into a level 18 below it, so its impact
# (≈ 1209 bps) far *exceeds* its half-spread (≈ 126 bps) — the
# ``slippage_bps > 2 * half_spread_bps`` regime where the parts are no
# longer guaranteed to re-add bit-for-bit.  Every other fixture here sits
# inside the touch, where the identity holds for a reason (Sterbenz) that
# does not extend this far; this is the book that tells the two regimes
# apart, and its parts in fact do not re-add exactly, which is the whole
# point of keeping it.
DEEP_BOOK = RecordedBook(
    bids=[
        BookLevel(price=98.0, quantity=1.0),
        BookLevel(price=80.0, quantity=50.0),
    ],
    asks=[BookLevel(price=100.5, quantity=100.0)],
)

# A two-deep bid ladder: mid 100.0, and a 6-unit sell must reach the
# second level.  The sell-side counterpart of LADDER_BOOK.
HIT_BOOK = RecordedBook(
    bids=[
        BookLevel(price=99.5, quantity=5.0),
        BookLevel(price=99.0, quantity=5.0),
    ],
    asks=[BookLevel(price=100.5, quantity=5.0)],
)


class TestTheWalkConsumesTheRecordedBook:
    """The fill is consumption of levels, not a summary of the book."""

    def test_the_fill_is_the_volume_weighted_average_of_levels_consumed(self) -> None:
        # 4 units against the ladder: 2 @ 100.5 then 2 @ 101.0, so the
        # average is (2*100.5 + 2*101.0)/4 = 100.75 — computed here from
        # the definition, not copied from the implementation's output.
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        expected = (2.0 * 100.5 + 2.0 * 101.0) / 4.0
        assert walk.vwap_fill_price == pytest.approx(expected)

    def test_the_last_level_reached_is_partially_filled(self) -> None:
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        assert walk.fills == (
            BookLevel(price=100.5, quantity=2.0),
            BookLevel(price=101.0, quantity=2.0),
        )
        assert walk.levels_consumed == 2

    def test_an_order_within_the_first_level_never_leaves_the_touch(self) -> None:
        # A small aggressive order is not a midpoint order either: it
        # fills at the touch, because that is the only price the ladder
        # quotes to a crossing order.
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 2.0))
        assert walk.levels_consumed == 1
        assert walk.vwap_fill_price == pytest.approx(100.5)
        assert walk.best_price == pytest.approx(100.5)
        assert walk.impact_bps == pytest.approx(0.0)

    def test_an_order_that_exactly_exhausts_a_level_consumes_no_more(self) -> None:
        # 5 units is exactly the top two levels (2 + 3): the walk stops
        # at the boundary and does not touch 101.5.
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 5.0))
        assert walk.levels_consumed == 2
        assert walk.worst_price == pytest.approx(101.0)

    def test_the_evidence_sums_to_the_order(self) -> None:
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        assert walk.filled_quantity == pytest.approx(walk.quantity)

    def test_float_subtraction_dust_is_not_a_shortfall(self) -> None:
        # 0.6 against six 0.1 levels: 0.6 - 0.1*5 is not exactly 0.1 in
        # float, so a walk without a dust tolerance would refuse an order
        # the book filled.  The residue is arithmetic, not liquidity.
        dusty = RecordedBook(
            bids=[BookLevel(price=99.0, quantity=10.0)],
            asks=[BookLevel(price=100.0 + i * 0.1, quantity=0.1) for i in range(6)],
        )
        walk = walk_recorded_book(dusty, AggressiveOrder(BUY, 0.6))
        assert walk.levels_consumed == 6
        assert walk.filled_quantity == pytest.approx(0.6)


class TestTheAggressiveOrderSide:
    """The side names the ladder: a buy lifts asks, a sell hits bids."""

    def test_a_buy_consumes_ask_levels(self) -> None:
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        assert [fill.price for fill in walk.fills] == [100.5, 101.0]
        assert walk.side == BUY

    def test_a_sell_consumes_bid_levels(self) -> None:
        walk = walk_recorded_book(HIT_BOOK, AggressiveOrder(SELL, 6.0))
        assert [fill.price for fill in walk.fills] == [99.5, 99.0]
        assert walk.side == SELL

    def test_the_side_is_coerced_case_insensitively(self) -> None:
        assert AggressiveOrder("BUY", 1.0).side == BUY
        assert AggressiveOrder(" Sell ", 1.0).side == SELL

    def test_a_book_side_is_not_an_order_side(self) -> None:
        # 'bid' and 'ask' name book sides; accepting them would let a
        # caller state the ladder where they meant the direction.
        with pytest.raises(CostModelFillError, match="book sides, not order directions"):
            AggressiveOrder("bid", 1.0)

    def test_a_non_string_side_is_refused(self) -> None:
        with pytest.raises(CostModelFillError, match="must be 'buy' or 'sell'"):
            AggressiveOrder(1, 1.0)  # type: ignore[arg-type]

    def test_a_non_positive_quantity_is_refused(self) -> None:
        for quantity in (0.0, -3.0, float("nan"), float("inf")):
            with pytest.raises(CostModelFillError):
                AggressiveOrder(BUY, quantity)

    def test_a_boolean_quantity_is_refused(self) -> None:
        # isinstance(True, int) — a quantity of True is a broken caller,
        # not a small order.
        with pytest.raises(CostModelFillError, match="real number"):
            AggressiveOrder(BUY, True)  # type: ignore[arg-type]


class TestTheSlippageFigureVsTheMidpoint:
    """The figure is measured against the midpoint the naive model filled at."""

    def test_an_order_too_small_to_move_the_book_pays_the_half_spread(self) -> None:
        # The walk's floor.  The midpoint model reported zero for this
        # order by construction; the walk reports the half-spread,
        # because crossing the spread is what aggressive means.
        walk = walk_recorded_book(TOUCH_BOOK, AggressiveOrder(BUY, 3.0))
        assert walk.slippage_bps == pytest.approx(100.0)  # 1.0 of 100.0 mid
        assert walk.impact_bps == pytest.approx(0.0)

    def test_the_figure_is_adverse_positive_on_both_sides(self) -> None:
        # A buy that lifts and a sell that hits both pay; positive is
        # always what the crossing cost, so a caller can add slippage to
        # fees without re-signing per side.
        buy = walk_recorded_book(TOUCH_BOOK, AggressiveOrder(BUY, 4.0))
        sell = walk_recorded_book(TOUCH_BOOK, AggressiveOrder(SELL, 4.0))
        assert buy.slippage_bps > 0.0
        assert sell.slippage_bps > 0.0
        assert buy.slippage_price == pytest.approx(1.0)
        assert sell.slippage_price == pytest.approx(1.0)

    def test_a_symmetric_book_prices_a_symmetric_pair_of_orders_equally(self) -> None:
        buy = walk_recorded_book(TOUCH_BOOK, AggressiveOrder(BUY, 4.0))
        sell = walk_recorded_book(TOUCH_BOOK, AggressiveOrder(SELL, 4.0))
        assert buy.slippage_bps == pytest.approx(sell.slippage_bps)

    def test_the_figure_is_computed_from_the_definition(self) -> None:
        # mid 99.75, VWAP 100.75: (100.75 - 99.75)/99.75 in bps — derived
        # here from first principles rather than copied from output.
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        mid = (99.0 + 100.5) / 2.0
        vwap = (2.0 * 100.5 + 2.0 * 101.0) / 4.0
        assert walk.arrival_midpoint == pytest.approx(mid)
        assert walk.slippage_bps == pytest.approx((vwap - mid) / mid * 10_000.0)

    def test_the_figure_decomposes_exactly_into_half_spread_and_impact(self) -> None:
        # Impact is defined as the remainder (slippage less half-spread)
        # rather than recomputed from the VWAP, which is what makes the
        # re-add exact here: an order inside the touch has slippage equal
        # to its half-spread, and Sterbenz guarantees a - b is exact for
        # b/2 <= a <= 2b.  A decomposition that only approximately added
        # up would let the parts quietly explain more slippage than the
        # whole, so the invariant is asserted bit-for-bit in this regime.
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        assert walk.slippage_bps <= 2.0 * walk.half_spread_bps
        assert walk.half_spread_bps + walk.impact_bps == walk.slippage_bps
        assert walk.half_spread_bps > 0.0
        assert walk.impact_bps > 0.0

    def test_the_decomposition_holds_to_a_ulp_past_the_touch(self) -> None:
        # The other side of the Sterbenz bound: an order deep enough that
        # the impact outweighs the half-spread leaves the exact regime,
        # and the re-add rounds in the last place.  Pinned rather than
        # left implicit, because every shipped fixture happens to sit
        # inside the touch — where the identity is exact for a reason
        # that does not generalise, and a test asserting bit-for-bit
        # there would never see this case at all.
        walk = walk_recorded_book(DEEP_BOOK, AggressiveOrder(SELL, 3.0))
        parts = walk.half_spread_bps + walk.impact_bps

        assert walk.slippage_bps > 2.0 * walk.half_spread_bps
        # Not merely close: this book's parts genuinely do not re-add
        # exactly, so the test fails if the exactness claim is ever
        # restored to the code or its docstring without re-deriving it.
        assert parts != walk.slippage_bps
        assert parts == pytest.approx(walk.slippage_bps, rel=1e-15)
        # Within one unit in the last place of the figure — the bound the
        # docstring promises, and the reason an audit may compare the
        # parts against the whole but not bit-for-bit past the touch.
        assert abs(parts - walk.slippage_bps) <= abs(walk.slippage_bps) * 2.3e-16
        # In this book the remainder rounds *up*, summing a hair above
        # the whole rather than below — which is why the docstring bounds
        # the error by a ULP in either direction instead of promising the
        # parts never over-explain.  An assertion that they never do is
        # false, and this fixture is the counterexample that proves it.
        assert parts > walk.slippage_bps
        assert walk.impact_bps > walk.half_spread_bps

    def test_the_impact_grows_with_the_order(self) -> None:
        small = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 2.0))
        large = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        assert small.impact_bps == pytest.approx(0.0)
        assert large.impact_bps > small.impact_bps
        # The half-spread is the cost of arriving; the order's size does
        # not change it.
        assert large.half_spread_bps == pytest.approx(small.half_spread_bps)

    def test_the_summary_carries_the_figure_and_its_parts(self) -> None:
        walk = walk_recorded_book(LADDER_BOOK, AggressiveOrder(BUY, 4.0))
        summary = walk.summary()
        assert summary["slippage_bps"] == walk.slippage_bps
        assert summary["impact_bps"] == walk.impact_bps
        assert summary["levels_consumed"] == 2
        assert summary["arrival_midpoint"] == walk.arrival_midpoint
        assert summary["vwap_fill_price"] == walk.vwap_fill_price

    def test_the_walk_is_frozen_after_construction(self) -> None:
        walk = walk_recorded_book(TOUCH_BOOK, AggressiveOrder(BUY, 1.0))
        with pytest.raises(AttributeError):
            walk.side = SELL  # type: ignore[misc]


class TestTheWalkRefusesToInvent:
    """Nothing the tape did not record enters the figure."""

    def test_an_order_beyond_the_recorded_depth_is_refused_not_extrapolated(self) -> None:
        # The worst level's price is not a price for the liquidity beyond
        # it; the refusal names the shortfall and the depth available.
        with pytest.raises(CostModelFillError, match="refuses to price a remainder") as exc:
            walk_recorded_book(HIT_BOOK, AggressiveOrder(BUY, 20.0))
        message = str(exc.value)
        assert "5.0" in message  # the ask depth that was available
        assert "20.0" in message  # the order that overshot it

    def test_a_book_with_an_empty_ladder_side_is_refused(self) -> None:
        empty_asks = RecordedBook(bids=[BookLevel(price=99.0, quantity=5.0)])
        with pytest.raises(CostModelFillError, match="empty ask side"):
            walk_recorded_book(empty_asks, AggressiveOrder(BUY, 1.0))
        empty_bids = RecordedBook(asks=[BookLevel(price=101.0, quantity=5.0)])
        with pytest.raises(CostModelFillError, match="empty bid side"):
            walk_recorded_book(empty_bids, AggressiveOrder(SELL, 1.0))

    def test_a_book_with_an_empty_far_side_is_refused(self) -> None:
        # There is liquidity to lift but no level on the far side, so
        # there is no midpoint to measure slippage against — an honest
        # absence, not a zero figure.
        no_bids = RecordedBook(asks=[BookLevel(price=101.0, quantity=5.0)])
        with pytest.raises(CostModelFillError, match="empty bid side"):
            walk_recorded_book(no_bids, AggressiveOrder(BUY, 1.0))

    def test_a_ladder_out_of_order_is_refused_not_sorted(self) -> None:
        # Sorting it would hide a corrupt recording behind a plausible
        # figure; the venue streams levels best-first and the
        # reconstruction keys them by price, so disorder is corruption.
        with pytest.raises(CostModelFillError, match="must descend strictly"):
            RecordedBook(
                bids=[BookLevel(price=99.0, quantity=1.0), BookLevel(price=100.0, quantity=1.0)],
                asks=[BookLevel(price=101.0, quantity=1.0)],
            )
        with pytest.raises(CostModelFillError, match="must ascend strictly"):
            RecordedBook(
                bids=[BookLevel(price=99.0, quantity=1.0)],
                asks=[BookLevel(price=101.0, quantity=1.0), BookLevel(price=100.5, quantity=1.0)],
            )

    def test_a_duplicate_price_is_not_two_levels(self) -> None:
        with pytest.raises(CostModelFillError, match="must descend strictly"):
            RecordedBook(
                bids=[BookLevel(price=99.0, quantity=1.0), BookLevel(price=99.0, quantity=2.0)],
                asks=[BookLevel(price=101.0, quantity=1.0)],
            )

    def test_a_crossed_or_locked_book_is_refused(self) -> None:
        # A best bid at or above the best ask leaves no priceable
        # midpoint, and a slippage figure against an impossible midpoint
        # is fiction, not realism.
        with pytest.raises(CostModelFillError, match="crossed or locked"):
            RecordedBook(
                bids=[BookLevel(price=102.0, quantity=1.0)],
                asks=[BookLevel(price=101.0, quantity=1.0)],
            )
        with pytest.raises(CostModelFillError, match="crossed or locked"):
            RecordedBook(
                bids=[BookLevel(price=101.0, quantity=1.0)],
                asks=[BookLevel(price=101.0, quantity=1.0)],
            )

    def test_a_zero_quantity_level_is_a_removal_not_liquidity(self) -> None:
        with pytest.raises(CostModelFillError, match="must be positive"):
            BookLevel(price=100.0, quantity=0.0)

    def test_a_non_positive_price_is_not_a_quote(self) -> None:
        with pytest.raises(CostModelFillError, match="must be positive"):
            BookLevel(price=0.0, quantity=1.0)

    def test_a_non_finite_level_is_a_recording_error(self) -> None:
        with pytest.raises(CostModelFillError, match="must be finite"):
            BookLevel(price=float("nan"), quantity=1.0)

    def test_a_boolean_price_is_a_broken_caller(self) -> None:
        with pytest.raises(CostModelFillError, match="real number"):
            BookLevel(price=True, quantity=1.0)  # type: ignore[arg-type]

    def test_a_walk_with_no_fills_is_a_figure_with_no_evidence(self) -> None:
        with pytest.raises(CostModelFillError, match="no fills"):
            BookWalk(
                side=BUY,
                quantity=1.0,
                fills=(),
                arrival_midpoint=100.0,
            )


class TestTheRecordedBookValue:
    """The recorded book is a value: two ladders, best first, honest about absence."""

    def test_the_book_reads_its_own_best_levels_and_midpoint(self) -> None:
        assert LADDER_BOOK.best_bid is not None
        assert LADDER_BOOK.best_bid.price == pytest.approx(99.0)
        assert LADDER_BOOK.best_ask is not None
        assert LADDER_BOOK.best_ask.price == pytest.approx(100.5)
        assert LADDER_BOOK.midpoint == pytest.approx(99.75)

    def test_an_empty_side_is_a_legal_recording_with_no_midpoint(self) -> None:
        # ingest records seconds with an empty side as an honest absence;
        # the book admits the recording, and it is the walk that refuses
        # to price it — the refusal is about the fill, not the fact.
        book = RecordedBook(bids=[BookLevel(price=99.0, quantity=5.0)])
        assert book.best_ask is None
        assert book.midpoint is None

    def test_depth_answers_the_side_an_order_walks(self) -> None:
        assert LADDER_BOOK.depth(BUY) == pytest.approx(15.0)
        assert HIT_BOOK.depth(SELL) == pytest.approx(10.0)
        with pytest.raises(CostModelFillError):
            LADDER_BOOK.depth("long")

    def test_the_book_is_frozen_after_construction(self) -> None:
        with pytest.raises(AttributeError):
            TOUCH_BOOK.bids = ()  # type: ignore[misc]


class TestTheDocumentResolution:
    """§6.2's aggressive half, resolved from the document — walk_book or nothing."""

    def test_the_shipped_document_walks_the_book(self) -> None:
        # The §6.2 document this member ships carries the section §6.2
        # itself specifies, so the default deployment resolves the walk.
        model, _origin = read_cost_model_document()
        assert resolve_aggressive_fill_model(model) == AggressiveFillModel()

    def test_resolving_without_a_model_reads_the_shipped_default(self) -> None:
        assert resolve_aggressive_fill_model() == AggressiveFillModel()

    def test_the_model_walks_exactly_what_the_function_walks(self) -> None:
        model = AggressiveFillModel()
        order = AggressiveOrder(BUY, 4.0)
        assert model.walk(LADDER_BOOK, order) == walk_recorded_book(LADDER_BOOK, order)

    def test_a_document_without_a_fill_model_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="names no 'fill_model'"):
            resolve_aggressive_fill_model({"version": "1", "venue": "v"})

    def test_a_fill_model_without_an_aggressive_half_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="no 'aggressive'"):
            resolve_aggressive_fill_model(
                {"fill_model": {"passive": {"require_trade_through": True}}}
            )

    def test_an_aggressive_half_without_walk_book_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="names no walk_book"):
            resolve_aggressive_fill_model({"fill_model": {"aggressive": {}}})

    def test_a_non_walking_aggressive_half_is_refused(self) -> None:
        # walk_book: false names the midpoint crossing the feature's
        # sentence rules out, and the shared library does not carry it —
        # a fill model behind a flag is how two implementations grow back.
        with pytest.raises(CostModelConfigError, match="midpoint"):
            resolve_aggressive_fill_model(
                {"fill_model": {"aggressive": {"walk_book": False}}}
            )

    def test_walk_book_must_be_a_bool_not_a_truthy_standin(self) -> None:
        for value in (1, "true", "yes"):
            with pytest.raises(CostModelConfigError, match="midpoint crossing"):
                resolve_aggressive_fill_model(
                    {"fill_model": {"aggressive": {"walk_book": value}}}
                )

    def test_the_passive_half_is_tolerated_and_not_read(self) -> None:
        # Features 63-65 own the passive half; its presence beside the
        # aggressive half is §6.2's shape, not an ambiguity to refuse.
        model = resolve_aggressive_fill_model(
            {
                "fill_model": {
                    "passive": {"require_trade_through": True, "queue_position_penalty_bps": 1.5},
                    "aggressive": {"walk_book": True},
                }
            }
        )
        assert model.walk_book is True

    def test_a_non_mapping_section_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a mapping"):
            resolve_aggressive_fill_model({"fill_model": ["aggressive"]})
        with pytest.raises(CostModelConfigError, match="not a mapping"):
            resolve_aggressive_fill_model({"fill_model": {"aggressive": ["walk_book"]}})

    def test_a_non_mapping_document_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a"):
            resolve_aggressive_fill_model(["not", "a", "model"])  # type: ignore[arg-type]

    def test_the_model_is_frozen(self) -> None:
        model = AggressiveFillModel()
        with pytest.raises(AttributeError):
            model.walk_book = False  # type: ignore[misc]


class TestTheServiceSeam:
    """The composed service resolves the fill model from the one cached parse."""

    def test_the_service_resolves_the_walk_from_the_shipped_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NULLIUS_COST_MODEL_PATH", raising=False)
        service = CostModelService.from_env()
        assert service.aggressive() == AggressiveFillModel()

    def test_the_service_resolves_the_walk_from_a_configured_document(
        self, document, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = document(
            "cost_model:\n"
            '  version: "2027.01.1"\n'
            "  venue: kraken_spot\n"
            "  fill_model:\n"
            "    aggressive:\n"
            "      walk_book: true\n"
        )
        monkeypatch.setenv("NULLIUS_COST_MODEL_PATH", str(path))
        service = CostModelService.from_env()
        assert service.aggressive() == AggressiveFillModel()

    def test_a_fresh_load_invalidates_the_cached_parse(
        self, document
    ) -> None:
        # The cached parse belongs to the document that produced it: a
        # service that loads a second document must resolve the second
        # document's behaviour, not keep walking under the first's.
        walking = document(
            "cost_model:\n"
            '  version: "1"\n'
            "  venue: v\n"
            "  fill_model:\n    aggressive:\n      walk_book: true\n",
            name="walking.yaml",
        )
        midcrossing = document(
            "cost_model:\n"
            '  version: "2"\n'
            "  venue: v\n"
            "  fill_model:\n    aggressive:\n      walk_book: false\n",
            name="midcrossing.yaml",
        )
        service = CostModelService(config_path=str(walking))
        assert service.aggressive() == AggressiveFillModel()
        service.load(str(midcrossing))
        with pytest.raises(CostModelConfigError, match="midpoint"):
            service.aggressive()

    def test_a_service_bound_to_a_resolved_config_has_no_document(
        self,
    ) -> None:
        # That service was explicitly told never to read a document; it
        # has no parse to resolve a fill model from, and the refusal
        # names the constructor pair that would carry one.
        service = CostModelService(
            config=CostModelConfig(version="2026.09.1", venue="binance_spot")
        )
        with pytest.raises(CostModelConfigError, match="already-resolved config"):
            service.aggressive()

    def test_the_document_is_parsed_once_and_cached(self) -> None:
        service = CostModelService.from_env()
        assert service.document is service.document

    def test_the_document_is_read_only_at_every_depth(self) -> None:
        # The parsed configuration is a frozen view (see
        # cost_model.config._frozen): a caller cannot rewrite the fill
        # model it walks under.
        service = CostModelService.from_env()
        with pytest.raises(TypeError):
            service.document["fill_model"]["aggressive"]["walk_book"] = False
