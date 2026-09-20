"""Feature 63 — the passive order filled only on a tape trade-through.

app_spec.xml, "Cost Model & Fill Simulation", feature 63: *System fills a
passive order only when the recorded tape trades through the quoted price,
which rejects fills that merely touch it.*  The sentence is an assertion, a
rejection and a promise, and each can fail independently, so the tests take
them one at a time:

* **fills a passive order** — the order is resting liquidity: a buy rests
  on the bid wanting to buy at the quote or below, a sell rests on the ask
  wanting to sell at the quote or above.  It carries a limit price and no
  urgency, and the two sides never swap.
* **only when the recorded tape trades through the quoted price** — the
  fill is picked off, not granted.  A buy fills only when the tape trades
  strictly below its limit, a sell strictly above; the first such trade is
  the fill trigger and the decision shows it as evidence.
* **which rejects fills that merely touch it** — a trade that prints
  exactly at the quote has reached the price but not crossed it, so the
  order does not fill.  The naive touch-based model fills here; this gate
  refuses, and the touch it survived is kept as the audit hook.

And the one refusal that keeps the gate honest: a document whose
``require_trade_through`` is not ``true`` is refused rather than fallen
back from — the only behaviour the flag could otherwise name is the
touch-fill the sentence rules out, and the library does not carry it.

:mod:`cost_model.passive_fill` owns the gate and its values; the service
tests at the end pin that the composed component resolves the model from
the one cached parse.
"""

from __future__ import annotations

import pytest

from cost_model import (
    CostModelConfigError,
    CostModelFillError,
    CostModelService,
    PassiveFillDecision,
    PassiveFillModel,
    PassiveOrder,
    RecordedTape,
    Trade,
    fill_passive_order,
    resolve_passive_fill_model,
)
from cost_model.config import read_cost_model_document
from cost_model.passive_fill import _TOUCH_EPS, BUY, SELL


def _tape(*prices: float, quantity: float = 1.0) -> RecordedTape:
    """A tape of one-unit trades at the given prices, in order."""
    return RecordedTape([Trade(price=p, quantity=quantity) for p in prices])


# A buy resting on the bid at 100.0.  A trade below it trades through; a
# trade at it touches; a trade above it never reached it.
BUY_AT_100 = PassiveOrder(side=BUY, limit_price=100.0)

# A sell resting on the ask at 100.0.  A trade above it trades through; a
# trade at it touches; a trade below it never reached it.
SELL_AT_100 = PassiveOrder(side=SELL, limit_price=100.0)


class TestTradeThroughFillsABuy:
    def test_a_trade_below_the_quote_fills_the_buy(self) -> None:
        # The tape climbs past the quote and then trades through it: the
        # first strictly-below trade is the trigger, and the fill is
        # charged at the order's own quote.
        decision = fill_passive_order(_tape(100.5, 100.0, 99.5), BUY_AT_100)
        assert decision.fills is True
        assert decision.traded_through is True
        assert decision.through_trade is not None
        assert decision.through_trade.price == 99.5
        assert decision.fill_price == 100.0

    def test_the_first_through_trade_is_the_trigger(self) -> None:
        # Two trades through the quote: the decision names the first, the
        # moment the market crossed the price, not the last.
        decision = fill_passive_order(_tape(101.0, 99.0, 98.0, 99.5), BUY_AT_100)
        assert decision.fills is True
        assert decision.through_trade is not None
        assert decision.through_trade.price == 99.0

    def test_a_buy_is_picked_off_downward_only(self) -> None:
        # A tape that only climbs — never trades below the resting bid —
        # leaves the buy unfilled: the market moved away from the quote,
        # not through it.
        decision = fill_passive_order(_tape(100.5, 101.0, 102.0), BUY_AT_100)
        assert decision.fills is False
        assert decision.through_trade is None

    def test_a_sell_is_picked_off_upward_only(self) -> None:
        # The mirror regime: a sell rests on the ask and fills only when
        # the tape trades strictly above the quote.
        decision = fill_passive_order(_tape(99.5, 100.0, 100.5), SELL_AT_100)
        assert decision.fills is True
        assert decision.through_trade is not None
        assert decision.through_trade.price == 100.5

    def test_a_sell_that_only_falls_is_unfilled(self) -> None:
        decision = fill_passive_order(_tape(99.5, 99.0, 98.0), SELL_AT_100)
        assert decision.fills is False


class TestTouchIsRefused:
    def test_a_trade_at_the_quote_does_not_fill(self) -> None:
        # The heart of the feature: the tape reaches the quote exactly and
        # retreats.  A touch-based model fills here; the trade-through gate
        # refuses, and keeps the touch as the would-be fill it denied.
        decision = fill_passive_order(_tape(100.5, 100.0, 100.3), BUY_AT_100)
        assert decision.fills is False
        assert decision.traded_through is False
        assert decision.through_trade is None
        assert decision.touched is True
        assert decision.touch_trade is not None
        assert decision.touch_trade.price == 100.0
        assert decision.fill_price is None

    def test_a_touch_then_a_through_fills_on_the_through(self) -> None:
        # Touching first does not poison a later through: the order fills on
        # the trade that crosses the quote, and the earlier touch is still
        # named as the first one that reached it.
        decision = fill_passive_order(_tape(100.0, 100.1, 99.5), BUY_AT_100)
        assert decision.fills is True
        assert decision.through_trade is not None
        assert decision.through_trade.price == 99.5
        assert decision.touch_trade is not None
        assert decision.touch_trade.price == 100.0

    def test_a_touch_alone_leaves_a_sell_unfilled(self) -> None:
        decision = fill_passive_order(_tape(99.5, 100.0, 99.8), SELL_AT_100)
        assert decision.fills is False
        assert decision.touched is True
        assert decision.touch_trade.price == 100.0


class TestNeverReached:
    def test_a_tape_that_never_reaches_the_quote_is_unfilled(self) -> None:
        # The market never got to the quote at all: no fill, and no touch
        # either — the order was never even approached.
        decision = fill_passive_order(_tape(101.0, 102.0, 103.0), BUY_AT_100)
        assert decision.fills is False
        assert decision.touched is False
        assert decision.through_trade is None
        assert decision.touch_trade is None

    def test_an_empty_tape_is_an_honest_no_fill(self) -> None:
        # No trades printed: not a refusal, an absence.  The order did not
        # fill because nothing traded, which is the true answer.
        decision = fill_passive_order(RecordedTape(), BUY_AT_100)
        assert decision.fills is False
        assert decision.touched is False
        assert decision.through_trade is None


class TestTheTouchBand:
    def test_a_trade_one_epsilon_below_is_a_touch_not_a_through(self) -> None:
        # A trade a hair inside the band below the quote is float dust, not
        # a genuine trade-through: the gate keeps it a touch.
        just_below = 100.0 * (1.0 - _TOUCH_EPS / 2.0)
        decision = fill_passive_order(_tape(just_below), BUY_AT_100)
        assert decision.fills is False
        assert decision.touched is True

    def test_a_trade_one_epsilon_above_the_band_trades_through(self) -> None:
        # A trade just past the band below the quote has genuinely crossed
        # the quote: the gate fills on it.
        just_past = 100.0 * (1.0 - _TOUCH_EPS * 2.0)
        decision = fill_passive_order(_tape(just_past), BUY_AT_100)
        assert decision.fills is True
        assert decision.through_trade is not None


class TestTheValuesAreConsistent:
    def test_a_decision_is_a_value_not_a_mutable_record(self) -> None:
        # Frozen: the gate's answer cannot be edited into an inconsistent
        # one after the fact.
        with pytest.raises((TypeError, AttributeError)):
            decision = fill_passive_order(_tape(99.0), BUY_AT_100)
            decision.fills = False  # type: ignore[misc]

    def test_a_fill_without_a_through_trade_is_refused(self) -> None:
        # The decision invariant is structural: asserting a fill with no
        # triggering trade is refused rather than allowed to stand.
        with pytest.raises(CostModelFillError):
            PassiveFillDecision(
                side=BUY, limit_price=100.0, fills=True, through_trade=None
            )

    def test_a_non_fill_with_a_through_trade_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            PassiveFillDecision(
                side=BUY,
                limit_price=100.0,
                fills=False,
                through_trade=Trade(price=99.0, quantity=1.0),
            )

    def test_the_summary_rebuilds_from_the_evidence(self) -> None:
        summary = fill_passive_order(_tape(100.5, 100.0, 99.5), BUY_AT_100).summary()
        assert summary == {
            "side": "buy",
            "limit_price": 100.0,
            "fills": True,
            "traded_through": True,
            "touched": True,
            "through_price": 99.5,
            "touch_price": 100.0,
            "fill_price": 100.0,
        }


class TestRefusedInputs:
    def test_a_non_positive_limit_price_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            PassiveOrder(side=BUY, limit_price=0.0)

    def test_a_bad_side_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            PassiveOrder(side="bid", limit_price=100.0)

    def test_a_non_trade_in_the_tape_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            RecordedTape([Trade(100.0, 1.0), "not a trade"])  # type: ignore[list-item]

    def test_a_non_positive_trade_price_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            Trade(price=0.0, quantity=1.0)

    def test_a_non_positive_trade_quantity_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            Trade(price=100.0, quantity=0.0)

    def test_a_non_string_side_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            PassiveOrder(side=123, limit_price=100.0)  # type: ignore[arg-type]


class TestResolvePassiveFillModel:
    def test_the_shipped_default_resolves_to_trade_through(self) -> None:
        # The default §6.2 document carries require_trade_through: true, so
        # the resolved gate is the trade-through one.
        model = resolve_passive_fill_model(read_cost_model_document()[0])
        assert isinstance(model, PassiveFillModel)
        assert model.require_trade_through is True

    def test_the_model_gates_the_same_as_the_function(self) -> None:
        model = resolve_passive_fill_model()
        decision = model.decide(_tape(100.0, 99.5), BUY_AT_100)
        assert decision.fills is True

    def test_a_document_without_a_fill_model_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_passive_fill_model({"version": "2026.09.1", "venue": "x"})

    def test_a_document_without_a_passive_half_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_passive_fill_model({"fill_model": {"aggressive": {"walk_book": True}}})

    def test_a_document_without_the_flag_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_passive_fill_model(
                {"fill_model": {"passive": {"queue_position_penalty_bps": 1.5}}}
            )

    def test_a_require_trade_through_that_is_not_true_is_refused(self) -> None:
        # The only other behaviour the flag could name is the touch-fill the
        # sentence rules out; the library refuses it rather than carrying it.
        with pytest.raises(CostModelConfigError):
            PassiveFillModel(require_trade_through=False)

    def test_the_passive_sections_other_fields_are_not_read(self) -> None:
        # queue_position_penalty_bps (feature 64) and fill_probability_model
        # (feature 65) are tolerated but not required here — the resolver
        # answers for the trade-through gate only.
        model = resolve_passive_fill_model(
            {
                "fill_model": {
                    "passive": {
                        "require_trade_through": True,
                        "queue_position_penalty_bps": 1.5,
                        "fill_probability_model": "exp_decay_vs_queue_depth",
                    }
                }
            }
        )
        assert model.require_trade_through is True


class TestTheServiceResolvesThePassiveModel:
    def test_the_service_exposes_the_passive_gate_from_the_default(self) -> None:
        # The composed service resolves the gate from the one cached parse
        # of the shipped §6.2 document, the same seam the aggressive model
        # sits on.
        service = CostModelService.from_env()
        model = service.passive()
        assert isinstance(model, PassiveFillModel)
        assert model.require_trade_through is True

    def test_the_service_gate_matches_the_module_function(
        self, test_database_url: str
    ) -> None:
        service = CostModelService.from_env()
        decision = service.passive().decide(_tape(100.5, 100.0), BUY_AT_100)
        assert decision.fills is False
        assert decision.touched is True

    def test_the_service_resolves_from_the_one_cached_parse(
        self, test_database_url: str
    ) -> None:
        # The passive and aggressive resolvers read the same cached parse,
        # so the two halves of the fill model cannot disagree about which
        # document was loaded.  A document that is wrong in a way both
        # resolvers would trip on raises once, from the one read.
        service = CostModelService.from_env()
        assert service.passive().require_trade_through is True
        assert service.aggressive().walk_book is True
