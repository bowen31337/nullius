"""Feature 317: the duplicate answer — the prior result, not a second order.

app_spec.xml, "Order Routing & Venue Filters", feature 317: *System returns
the prior result for a duplicate client order identifier rather than placing
a second order.*  The suite is organised around the two halves of that
sentence, because the first can be true while the second is false and that
combination is the failure the feature exists to prevent:

* **returns the prior result** — a second call for a key already held
  answers the exact record the first call landed: the symbol, the outcome
  and the instant the first write produced, untouched by whatever the second
  ask's spellings or clock said.  A key this table has never held is *not* a
  duplicate and is answered by ``None`` from the read rather than by a
  default or a zeroed record.
* **rather than placing a second order** — the placement callable is not
  invoked on a duplicate.  This is the assertion that matters most and the
  one nothing else in the suite would notice: a duplicate that *also*
  reached the venue would look like a success in the returned record, in the
  row count and in every other reading here.  So the callable is a counter
  and the count is pinned at one for however many calls are made.

Two further laws the module states and this suite holds it to:

* **a refusal leaves no row.**  A venue rejection is stated by raising from
  the callable, and the transaction rolls back with it — so the next attempt
  for that order takes the fresh path again.  Without this, one transient
  refusal would be recorded as a placement and every later attempt answered
  *"already placed"* for an order that was never placed.
* **the record is a placement, and only a placement.**  The outcome
  vocabulary admits one token, and a caller offering a venue rejection is
  refused by name rather than obeyed.

The cross-process case — the one the whole feature is for, a reclaimed spot
instance deriving a key its predecessor already used — is asserted with a
real second interpreter at the end, and the concurrent case with real
threads: two routers recovered from one reclamation can derive one key at
the same instant, and the database's write lock is what has to serialise
them.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import router as member
from router.client_order_id import derive_client_order_id
from router.errors import (
    SUBMISSION_RESULT_CODE,
    RouterClientOrderIdError,
    RouterError,
    RouterFilterError,
    RouterRateLimitError,
    RouterStoreError,
    RouterSubmissionHealthError,
    RouterSubmissionResultError,
)
from router.submission_health import (
    ORDER_SUBMISSION_ACCEPTED,
    ORDER_SUBMISSION_REJECTED,
)
from router.submission_result import (
    ORDER_PLACEMENT_OUTCOMES,
    ORDER_PLACEMENT_TABLE,
    OrderPlacement,
    PlacementOrder,
    PlacementResult,
    RouterOrderPlacementStore,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class VenueRefused(Exception):
    """A venue rejection, as the caller's own vocabulary spells it.

    Defined here rather than reused from another exception family on
    purpose: the store must let *whatever* the callable raises through
    untouched, and this suite's subject includes the case where that is a
    class the store's own error handling might have wanted to claim — see
    ``test_an_oserror_from_the_venue_is_not_reported_as_a_bad_database``.
    """


#: The instant the suite reasons from — the same calendar day
#: ``test_client_order_id.py``, ``test_retry.py`` and ``test_limiter.py``
#: reason from, so the four suites describe one order path on one trading
#: day.
T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

BOOK = "momentum-core"
SYMBOL = "BTCUSDT"
OTHER_SYMBOL = "ETHUSDT"


def _key(*, symbol: str = SYMBOL, minutes: int = 0) -> str:
    """Feature 316's key for one leg of one rebalance of the suite's book.

    Derived through the real derivation rather than pasted as a literal:
    this suite's subject is what the *store* does with a key, and a literal
    would stop testing the join between the two features the moment feature
    316's framing moved.
    """
    return str(
        derive_client_order_id(
            book_id=BOOK,
            rebalance_ts=T0 + timedelta(minutes=minutes),
            symbol=symbol,
        )
    )


def _order(*, symbol: str = SYMBOL, minutes: int = 0) -> PlacementOrder:
    return PlacementOrder(
        client_order_id=_key(symbol=symbol, minutes=minutes), symbol=symbol
    )


class _Venue:
    """A venue stand-in that counts the orders it was actually sent.

    The count is the whole point: *"rather than placing a second order"* is
    a claim about a call that must **not** happen, and it is invisible in
    every value the store returns — a duplicate that also reached the venue
    would look like a success in every other reading this suite makes.

    ``refuse`` makes every send raise, which is how a caller states a venue
    rejection.  The return value is deliberately *not* the placement record:
    the store ignores it, because returning from this callable is the
    venue's acceptance and nothing else about the return has any meaning.
    """

    def __init__(self, *, refuse: bool = False) -> None:
        self.sent: list[str] = []
        self._refuse = refuse

    def __call__(self) -> str:
        self.sent.append("send")
        if self._refuse:
            raise VenueRefused("the venue refused the order")
        return "accepted"


@pytest.fixture
def store(test_database_url: str) -> RouterOrderPlacementStore:
    return RouterOrderPlacementStore(test_database_url)


@pytest.fixture
def venue() -> _Venue:
    return _Venue()


# -- The ask's own contract ---------------------------------------------------


class TestPlacementOrder:
    """The ask is a validated value, so two spellings of one order agree."""

    def test_the_key_is_normalized_to_the_lowercase_hex_the_write_lands(self) -> None:
        order = PlacementOrder(client_order_id=_key().upper(), symbol=SYMBOL)
        assert order.key == _key()
        assert order.client_order_id == _key()

    def test_the_symbol_is_stripped_and_kept_verbatim(self) -> None:
        order = PlacementOrder(client_order_id=_key(), symbol=f"  {SYMBOL}\n")
        assert order.symbol == SYMBOL

    def test_a_symbol_that_is_not_the_venues_spelling_is_kept_as_given(self) -> None:
        # The venue's own spelling is the key exchangeInfo files its filters
        # under, so nothing here case-folds it -- feature 316's rule, held on
        # the same term one module over.
        order = PlacementOrder(client_order_id=_key(), symbol="btcusdt")
        assert order.symbol == "btcusdt"

    def test_two_spellings_of_one_order_compare_equal(self) -> None:
        assert PlacementOrder(
            client_order_id=_key().upper(), symbol=SYMBOL
        ) == PlacementOrder(client_order_id=_key(), symbol=SYMBOL)

    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-key",
            "",
            "   ",
            _key()[:-1],
            _key() + "a",
            "sha256:" + _key(),
            None,
            12345,
            b"0" * 64,
        ],
    )
    def test_a_value_that_is_not_a_key_is_refused_as_the_identifiers_own_fault(
        self, bad: object
    ) -> None:
        # Refused in feature 316's class, not this feature's: a key this
        # system never derived is the identifier's fault with the
        # identifier's repair, and this module reads that validation rather
        # than re-spelling it.
        with pytest.raises(RouterClientOrderIdError):
            PlacementOrder(client_order_id=bad, symbol=SYMBOL)

    @pytest.mark.parametrize("bad", ["", "   ", None, 7, ["BTCUSDT"]])
    def test_a_symbol_that_names_no_leg_is_refused(self, bad: object) -> None:
        with pytest.raises(RouterSubmissionResultError) as raised:
            PlacementOrder(client_order_id=_key(), symbol=bad)
        assert str(raised.value).startswith(SUBMISSION_RESULT_CODE)


class TestOrderPlacement:
    """The record validates itself, so a rebuilt row cannot lie."""

    def test_a_placement_carries_its_key_and_the_venues_answer(self) -> None:
        placement = OrderPlacement(
            client_order_id=_key(),
            symbol=SYMBOL,
            outcome=ORDER_SUBMISSION_ACCEPTED,
            placed_at=T0,
        )
        assert placement.key == placement.client_order_id == _key()
        assert placement.outcome == ORDER_SUBMISSION_ACCEPTED
        assert placement.placed_at == T0

    def test_the_order_is_not_the_history_of_asking_for_it(self) -> None:
        # ``appended`` is a fact about the call, so it rides on the result and
        # not on the placement: two values for one row from two calls are the
        # one value, which is what makes "returns the prior result" a
        # comparison a caller can make.
        assert not hasattr(OrderPlacement, "appended")
        assert not hasattr(OrderPlacement, "replayed")
        one = OrderPlacement(
            client_order_id=_key(),
            symbol=SYMBOL,
            outcome=ORDER_SUBMISSION_ACCEPTED,
            placed_at=T0,
        )
        two = OrderPlacement(
            client_order_id=_key(),
            symbol=SYMBOL,
            outcome=ORDER_SUBMISSION_ACCEPTED,
            placed_at=T0,
        )
        assert one == two

    def test_a_venue_rejection_is_not_a_placement_outcome(self) -> None:
        # The one value a caller is most likely to reach for, refused by name
        # with the repair in the message: a refusal placed nothing, so it
        # belongs in feature 320's log where it can be retried, not here
        # where it would make one transient refusal permanent.
        with pytest.raises(RouterSubmissionResultError) as raised:
            OrderPlacement(
                client_order_id=_key(),
                symbol=SYMBOL,
                outcome=ORDER_SUBMISSION_REJECTED,
                placed_at=T0,
            )
        assert str(raised.value).startswith(SUBMISSION_RESULT_CODE)
        assert ORDER_SUBMISSION_REJECTED not in ORDER_PLACEMENT_OUTCOMES
        assert ORDER_PLACEMENT_OUTCOMES == frozenset({ORDER_SUBMISSION_ACCEPTED})

    def test_the_vocabulary_is_the_members_one_spelling(self) -> None:
        # Imported from feature 320 rather than respelled: an operator
        # joining a placement to the submission-health row that describes it
        # must not have to know that two of this member's tables spelled the
        # venue's answer differently.
        from router.submission_health import ORDER_SUBMISSION_OUTCOMES

        assert ORDER_PLACEMENT_OUTCOMES < ORDER_SUBMISSION_OUTCOMES

    @pytest.mark.parametrize("bad", ["placed", "", None, 1, ["accepted"]])
    def test_an_outcome_outside_the_vocabulary_is_refused(self, bad: object) -> None:
        with pytest.raises(RouterSubmissionResultError):
            OrderPlacement(
                client_order_id=_key(),
                symbol=SYMBOL,
                outcome=bad,
                placed_at=T0,
            )

    def test_a_naive_moment_is_refused(self) -> None:
        with pytest.raises(RouterSubmissionResultError):
            OrderPlacement(
                client_order_id=_key(),
                symbol=SYMBOL,
                outcome=ORDER_SUBMISSION_ACCEPTED,
                # Naive on purpose: this is the shape being refused.
                placed_at=datetime(2026, 9, 25, 12, 0),  # noqa: DTZ001
            )


class TestPlacementResult:
    """The answer carries both halves: the record, and which side of it."""

    @pytest.mark.parametrize("appended", [True, False])
    def test_appended_and_replayed_are_one_bit_spelled_twice(
        self, appended: bool
    ) -> None:
        result = PlacementResult(
            appended=appended,
            placement=OrderPlacement(
                client_order_id=_key(),
                symbol=SYMBOL,
                outcome=ORDER_SUBMISSION_ACCEPTED,
                placed_at=T0,
            ),
        )
        assert result.appended is appended
        assert result.replayed is (not appended)
        assert result.key == _key()

    def test_the_result_unpacks_as_the_sentence_says_it(self) -> None:
        # The sentence puts the prior *result* first and the second placement
        # second, and that is the order this unpacks in.
        placement = OrderPlacement(
            client_order_id=_key(),
            symbol=SYMBOL,
            outcome=ORDER_SUBMISSION_ACCEPTED,
            placed_at=T0,
        )
        record, appended = PlacementResult(appended=True, placement=placement)
        assert record == placement
        assert appended is True

    def test_a_non_bool_appended_flag_is_refused(self) -> None:
        with pytest.raises(RouterSubmissionResultError):
            PlacementResult(
                appended=1,
                placement=OrderPlacement(
                    client_order_id=_key(),
                    symbol=SYMBOL,
                    outcome=ORDER_SUBMISSION_ACCEPTED,
                    placed_at=T0,
                ),
            )


# -- The sentence: the prior result, not a second order -----------------------


class TestTheDuplicateIsAnsweredNotResent:
    """Feature 317's two halves, pinned separately."""

    def test_a_first_placement_calls_the_venue_once_and_says_so(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        result = store.place(_order(), venue, now=T0)
        assert venue.sent == ["send"]
        assert result.appended is True
        assert result.replayed is False
        assert result.placement.outcome == ORDER_SUBMISSION_ACCEPTED
        assert result.placement.symbol == SYMBOL
        assert result.placement.placed_at == T0

    def test_a_duplicate_does_not_place_a_second_order(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        store.place(_order(), venue, now=T0)
        again = store.place(_order(), venue, now=T0 + timedelta(hours=3))
        assert venue.sent == ["send"], "the venue was sent a second order"
        assert again.appended is False
        assert again.replayed is True

    def test_the_prior_result_is_the_prior_record_untouched(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        # A retry hands the store another clock reading and another ask; the
        # answer is what the first write produced, not what the second call
        # guessed.  Append-only means a placement is never restated -- and
        # the two *placements* are equal even though the two *results* are
        # not, because only the latter is about the asking.
        first = store.place(_order(), venue, now=T0)
        again = store.place(_order(), venue, now=T0 + timedelta(days=2))
        assert again.placement == first.placement
        assert again != first
        assert again.placement.placed_at == T0, (
            "the duplicate restated when the order landed"
        )

    def test_the_result_unpacks_where_the_sentence_puts_the_prior_result(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        store.place(_order(), venue, now=T0)
        placement, appended = store.place(_order(), venue, now=T0)
        assert appended is False
        assert placement == store.prior_result(_key())

    def test_the_venue_is_called_once_however_many_times_the_key_is_asked(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        for _ in range(5):
            store.place(_order(), venue, now=T0)
        assert len(venue.sent) == 1

    def test_a_second_store_is_answered_by_the_first_ones_row(
        self, test_database_url: str, venue: _Venue
    ) -> None:
        # A different store over the same address is what "persists" means
        # operationally -- and it stands in for the reclaimed spot instance,
        # which is a process that was never told anything by the first.
        first = RouterOrderPlacementStore(test_database_url)
        second = RouterOrderPlacementStore(test_database_url)
        first.place(_order(), venue, now=T0)
        again = second.place(_order(), venue, now=T0)
        assert again.appended is False
        assert again.placement == first.place(_order(), venue, now=T0).placement
        assert venue.sent == ["send"]

    def test_a_different_leg_of_one_rebalance_is_a_different_order(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        # The duplicate test is over the whole key, which names book,
        # rebalance *and* symbol: two legs of one rebalance are two orders
        # and both must reach the venue.
        store.place(_order(symbol=SYMBOL), venue, now=T0)
        store.place(_order(symbol=OTHER_SYMBOL), venue, now=T0)
        assert len(venue.sent) == 2

    def test_a_later_rebalance_of_the_same_leg_is_a_different_order(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        store.place(_order(minutes=0), venue, now=T0)
        store.place(_order(minutes=15), venue, now=T0 + timedelta(minutes=15))
        assert len(venue.sent) == 2

    def test_the_duplicate_is_answered_from_the_row_not_from_memory(
        self, test_database_url: str, venue: _Venue
    ) -> None:
        # Nothing survives in a fresh store object, so an answer that came
        # back is an answer that came off the table.
        RouterOrderPlacementStore(test_database_url).place(_order(), venue, now=T0)
        fresh = RouterOrderPlacementStore(test_database_url)
        assert fresh.place(_order(), venue, now=T0).replayed is True
        assert venue.sent == ["send"]


class TestThePriorResultRead:
    """``prior_result`` answers the same row without attempting anything."""

    def test_a_placed_order_reads_back(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        placed = store.place(_order(), venue, now=T0)
        prior = store.prior_result(_key())
        assert prior is not None
        assert prior == placed.placement
        assert prior.key == _key()
        assert prior.symbol == SYMBOL

    def test_a_key_never_placed_reads_none(
        self, store: RouterOrderPlacementStore
    ) -> None:
        # Not a default and not a zeroed placement: an order that was never
        # placed is a different fact from one that was.
        assert store.prior_result(_key()) is None

    def test_the_read_precedes_the_place(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        assert store.prior_result(_key()) is None
        store.place(_order(), venue, now=T0)
        assert store.prior_result(_key()) is not None

    def test_the_read_carries_no_appended_bit(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        # ``appended`` is about the call that made the answer, and a read
        # made nothing -- so the placement it returns is the same value
        # whether it came from a read or from the call that placed it.
        placed = store.place(_order(), venue, now=T0)
        assert store.prior_result(_key()) == placed.placement

    @pytest.mark.parametrize("bad", ["nope", "", _key()[:-1], "sha256:" + _key()])
    def test_a_malformed_key_is_refused_here_too(
        self, store: RouterOrderPlacementStore, bad: str
    ) -> None:
        with pytest.raises(RouterClientOrderIdError):
            store.prior_result(bad)


# -- The ask's refusals, and what must not be recorded ------------------------


class TestTheAskIsRefusedEagerly:
    """A malformed ask can never be answered *"already placed"*."""

    def test_a_placement_that_cannot_be_called_is_refused(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        store.place(_order(), venue, now=T0)
        # The key *is* already held -- and the ask is still refused rather
        # than answered from the row, because an ask this store cannot
        # honour is not a duplicate of anything.
        with pytest.raises(RouterSubmissionResultError) as raised:
            store.place(_order(), None)
        assert str(raised.value).startswith(SUBMISSION_RESULT_CODE)

    @pytest.mark.parametrize("bad", [None, "an order", _key(), {"key": "x"}])
    def test_a_non_PlacementOrder_ask_is_refused(
        self, store: RouterOrderPlacementStore, venue: _Venue, bad: object
    ) -> None:
        with pytest.raises(RouterSubmissionResultError) as raised:
            store.place(bad, venue)
        assert str(raised.value).startswith(SUBMISSION_RESULT_CODE)

    def test_a_naive_now_is_refused(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        with pytest.raises(RouterSubmissionResultError):
            # Naive on purpose: this is the shape being refused.
            store.place(_order(), venue, now=datetime(2026, 9, 25, 12, 0))  # noqa: DTZ001
        assert venue.sent == []
        assert store.prior_result(_key()) is None

    def test_a_refused_ask_leaves_no_row_and_calls_no_venue(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        with pytest.raises(RouterSubmissionResultError):
            store.place(_order(), "not callable")
        assert store.prior_result(_key()) is None
        assert venue.sent == []

    def test_the_refusal_precedes_the_database(
        self, test_database_url: str, tmp_path: Path
    ) -> None:
        # No file is created at all: the ask is refused before a connection
        # is opened.
        database = tmp_path / "never-opened.db"
        fresh = RouterOrderPlacementStore(f"sqlite:///{database}")
        with pytest.raises(RouterSubmissionResultError):
            fresh.place(_order(), None)
        assert not database.exists()


class TestAVenueRefusalIsNotAResult:
    """A rejection leaves no row, so the order path keeps its retry."""

    def test_a_raising_placement_propagates_untouched(
        self, store: RouterOrderPlacementStore
    ) -> None:
        class VenueRefused(Exception):
            pass

        def refuse() -> None:
            raise VenueRefused("the venue said no")

        with pytest.raises(VenueRefused):
            store.place(_order(), refuse, now=T0)

    def test_a_refused_placement_records_nothing(
        self, store: RouterOrderPlacementStore
    ) -> None:
        def refuse() -> None:
            raise VenueRefused("the venue said no")

        with pytest.raises(VenueRefused):
            store.place(_order(), refuse, now=T0)
        # The check-and-place-and-insert is one transaction: the claim rolls
        # back with the refusal, so nothing is left claiming the order was
        # placed.
        assert store.prior_result(_key()) is None

    def test_an_oserror_from_the_venue_is_not_reported_as_a_bad_database(
        self, store: RouterOrderPlacementStore
    ) -> None:
        # ``ConnectionError`` is an ``OSError``, and so is the family a
        # sqlite failure arrives in.  A venue that could not be reached must
        # reach the order path as itself, not as this member's store fault,
        # or an operator goes and looks at the database for a network
        # problem -- and, worse, a raised refusal would be *recorded*.
        def refuse() -> None:
            raise ConnectionError("the venue's socket died")

        with pytest.raises(ConnectionError):
            store.place(_order(), refuse, now=T0)
        assert store.prior_result(_key()) is None

    def test_the_order_path_keeps_its_retry_after_a_refusal(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        # The whole reason the refusal must not be recorded: a second
        # attempt at a refused order is the retry the order path is entitled
        # to make, not a duplicate.
        def refuse() -> None:
            raise VenueRefused("the venue said no")

        with pytest.raises(VenueRefused):
            store.place(_order(), refuse, now=T0)
        placed = store.place(_order(), venue, now=T0 + timedelta(seconds=1))
        assert placed.appended is True
        assert venue.sent == ["send"]

    def test_a_refusal_does_not_disturb_a_prior_placement(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        # A placement already holds its key; a refusal arrives on a *different*
        # key, so the callable actually runs and actually raises.  The refused
        # order leaves nothing behind, and the placement made before it is
        # exactly as it was -- the two keys are separate rows and the rollback
        # is the refused one's own.
        first = store.place(_order(), venue, now=T0)

        def refuse() -> None:
            raise VenueRefused("the venue said no")

        with pytest.raises(VenueRefused):
            store.place(
                _order(symbol=OTHER_SYMBOL), refuse, now=T0 + timedelta(minutes=1)
            )
        assert store.prior_result(_key()) == first.placement
        assert store.prior_result(_key(symbol=OTHER_SYMBOL)) is None
        assert len(venue.sent) == 1


# -- Concurrency: the window the transaction closes ---------------------------


class TestTwoProcessesOneKey:
    """One key, two askers, one send — the reclamation case."""

    def test_concurrent_asks_send_the_order_once(self, test_database_url: str) -> None:
        # Two routers recovered from one spot reclamation derive one key at
        # one instant.  The database's write lock serialises them: the second
        # blocks until the first commits and is then answered from the
        # committed row rather than racing the venue.
        store = RouterOrderPlacementStore(test_database_url)
        sent: list[str] = []
        lock = threading.Lock()
        started = threading.Event()

        def slow_venue() -> str:
            with lock:
                sent.append("send")
            started.set()
            time.sleep(0.25)  # hold the transaction open, as a venue call does
            return "accepted"

        results: list[PlacementResult] = []
        failures: list[BaseException] = []

        def ask() -> None:
            try:
                results.append(store.place(_order(), slow_venue, now=T0))
            # Blind on purpose: a worker thread that dies holding the lock
            # takes the join with it, so the test hangs rather than fails.
            # Every failure is captured here and re-raised on the main
            # thread below, where it can be read.
            except BaseException as exc:  # noqa: BLE001
                failures.append(exc)

        first = threading.Thread(target=ask)
        second = threading.Thread(target=ask)
        first.start()
        started.wait(timeout=5)  # the first is inside its transaction
        second.start()
        first.join(timeout=10)
        second.join(timeout=10)

        assert failures == []
        assert len(results) == 2
        assert len(sent) == 1, "the venue was sent a second order"
        assert sorted(one.appended for one in results) == [False, True]
        assert len({one.key for one in results}) == 1


# -- The store's own contract -------------------------------------------------


class TestStoreAddress:
    """The address is the member's existing vocabulary, not this feature's."""

    def test_resolves_from_database_url(self, test_database_url: str) -> None:
        store = RouterOrderPlacementStore.resolve()
        assert store is not None
        assert store.database_url == test_database_url

    @pytest.mark.parametrize("unset", [None, "", "   "])
    def test_no_database_url_resolves_to_none(
        self, monkeypatch: pytest.MonkeyPatch, unset: str | None
    ) -> None:
        if unset is None:
            monkeypatch.delenv("DATABASE_URL", raising=False)
        else:
            monkeypatch.setenv("DATABASE_URL", unset)
        assert RouterOrderPlacementStore.resolve() is None

    def test_construction_rejects_a_blank_url(self) -> None:
        with pytest.raises(RouterStoreError):
            RouterOrderPlacementStore("   ")

    def test_a_non_sqlite_scheme_is_refused_as_an_address_fault(
        self, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        # An address this member cannot speak is RouterStoreError -- the
        # member's existing vocabulary for that fault -- and not this
        # feature's own class, whose repairs are about the ask and the row.
        broken = RouterOrderPlacementStore("postgresql://localhost/router")
        with pytest.raises(RouterStoreError):
            broken.place(_order(), venue, now=T0)

    def test_the_store_is_addressed_never_composed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'placed.db'}")
        # No second component under any name a placement store might take.
        from app.module_loader import create_app

        app = create_app()
        for guessed in (
            "order_placement",
            "router_order_placement",
            "submission_result",
            "router-placement",
        ):
            assert app.get(guessed) is None, guessed
        assert app.get(member.COMPONENT_NAME) is not None
        assert RouterOrderPlacementStore.resolve() is not None

    def test_constructing_the_store_opens_no_database(self, tmp_path: Path) -> None:
        database = tmp_path / "unopened.db"
        store = RouterOrderPlacementStore(f"sqlite:///{database}")
        assert not database.exists()
        assert store.prior_result(_key()) is None
        assert database.exists()  # the demand is what wrote


# -- The stored row is not trusted -------------------------------------------


class TestAStoredRowIsRefusedRatherThanBelieved:
    """A row outside the vocabulary is refused, not replayed.

    The table's ``CHECK`` is the first guard, but it is not the only way a row
    lands: anything holding the file -- a repair script, a hand-run
    ``sqlite3``, a future migration, or a build of SQLite willing to skip
    constraints -- can write an outcome this feature never issued.  These
    tests turn the constraint off by name so that path is genuinely reachable
    rather than merely imagined, and then ask the store the same question it
    would be asked by a duplicate: what is the prior result for this key?
    A row it cannot vouch for must raise, because the alternative is telling
    an order path that an order was placed when the row says it was not.
    """

    def _raw_insert(self, url: str, *, outcome: str, placed_at: str) -> None:
        import sqlite3
        from contextlib import closing

        path = url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection, connection:
            # The store's own writes are constrained; this one is not, which
            # is exactly the situation the store has to survive.
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                f"INSERT INTO {ORDER_PLACEMENT_TABLE} "
                "(client_order_id, symbol, outcome, placed_at) VALUES (?,?,?,?)",
                (_key(symbol=OTHER_SYMBOL), OTHER_SYMBOL, outcome, placed_at),
            )

    def test_a_stored_outcome_outside_the_vocabulary_is_refused(
        self, test_database_url: str, store: RouterOrderPlacementStore
    ) -> None:
        store.prior_result(_key())  # create the schema
        self._raw_insert(
            test_database_url,
            outcome="maybe",
            placed_at=T0.isoformat(),
        )
        with pytest.raises(RouterSubmissionResultError) as raised:
            store.prior_result(_key(symbol=OTHER_SYMBOL))
        # The refusal names the row, so an operator has something to repair.
        assert str(raised.value).startswith(SUBMISSION_RESULT_CODE)
        assert _key(symbol=OTHER_SYMBOL) in str(raised.value)

    def test_a_stored_rejection_is_refused_rather_than_replayed(
        self, test_database_url: str, store: RouterOrderPlacementStore
    ) -> None:
        # A tool that wrote a rejection into this table wrote a row this
        # feature cannot answer a duplicate with: the order was not placed,
        # so a later attempt must not be told it was.
        store.prior_result(_key())
        self._raw_insert(
            test_database_url,
            outcome=ORDER_SUBMISSION_REJECTED,
            placed_at=T0.isoformat(),
        )
        with pytest.raises(RouterSubmissionResultError):
            store.prior_result(_key(symbol=OTHER_SYMBOL))

    def test_a_stored_moment_no_parser_accepts_is_refused(
        self, test_database_url: str, store: RouterOrderPlacementStore
    ) -> None:
        store.prior_result(_key())
        self._raw_insert(
            test_database_url,
            outcome=ORDER_SUBMISSION_ACCEPTED,
            placed_at="last tuesday",
        )
        with pytest.raises(RouterSubmissionResultError) as raised:
            store.prior_result(_key(symbol=OTHER_SYMBOL))
        assert str(raised.value).startswith(SUBMISSION_RESULT_CODE)

    def test_a_row_another_tool_wrote_is_still_a_placement(
        self, test_database_url: str, store: RouterOrderPlacementStore, venue: _Venue
    ) -> None:
        # The other direction of the same rule: a *well-formed* row is a
        # placement whoever wrote it, so a duplicate is answered from it and
        # the venue is not called.
        store.prior_result(_key())
        self._raw_insert(
            test_database_url,
            outcome=ORDER_SUBMISSION_ACCEPTED,
            placed_at=T0.isoformat(),
        )
        result = store.place(
            _order(symbol=OTHER_SYMBOL), venue, now=T0 + timedelta(minutes=5)
        )
        assert result.replayed is True
        assert result.placement.symbol == OTHER_SYMBOL
        assert result.placement.placed_at == T0  # the row's moment, not this call's
        assert venue.sent == []


class TestTheTableShape:
    """One row per key, and the schema itself says so."""

    def test_the_key_is_the_primary_key(self, test_database_url: str) -> None:
        import sqlite3
        from contextlib import closing

        store = RouterOrderPlacementStore(test_database_url)
        store.prior_result(_key())  # create the schema
        path = test_database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            columns = connection.execute(
                f"PRAGMA table_info({ORDER_PLACEMENT_TABLE})"
            ).fetchall()
        primary = [row[1] for row in columns if row[5]]
        assert primary == ["client_order_id"]

    def test_one_key_cannot_hold_two_rows(
        self, test_database_url: str, store: RouterOrderPlacementStore
    ) -> None:
        import sqlite3
        from contextlib import closing

        store.place(_order(), _Venue(), now=T0)
        path = test_database_url.removeprefix("sqlite:///")
        with (
            closing(sqlite3.connect(path)) as connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                f"INSERT INTO {ORDER_PLACEMENT_TABLE} "
                "(client_order_id, symbol, outcome, placed_at) "
                "VALUES (?,?,?,?)",
                (_key(), SYMBOL, ORDER_SUBMISSION_ACCEPTED, T0.isoformat()),
            )


# -- The vocabulary, the class tree, and the member ---------------------------


class TestTheErrorVocabulary:
    """Feature 317's refusal is its own class with its own greppable word."""

    def test_the_code_is_the_one_the_messages_open_with(self) -> None:
        with pytest.raises(RouterSubmissionResultError) as raised:
            PlacementOrder(client_order_id=_key(), symbol="")
        assert str(raised.value).startswith(f"{SUBMISSION_RESULT_CODE}:")
        assert SUBMISSION_RESULT_CODE == "submission_result"

    def test_it_is_not_the_identifier_code(self) -> None:
        # One grep apart, deliberately: a malformed key is feature 316's
        # fault with feature 316's repair, and this class is the ask one step
        # further along.
        from router.errors import CLIENT_ORDER_ID_CODE

        assert SUBMISSION_RESULT_CODE != CLIENT_ORDER_ID_CODE

    def test_it_is_a_router_error_and_its_own_sibling(
        self, store: RouterOrderPlacementStore
    ) -> None:
        # Catchable through the member's one base, and *not* an instance of
        # any of the faults it must not be mistaken for: a caller catching
        # any of those must not have this refusal land in its ``except``.
        with pytest.raises(RouterError) as raised:
            store.place(_order(), None)
        for unrelated in (
            RouterFilterError,
            RouterStoreError,
            RouterSubmissionHealthError,
            RouterRateLimitError,
            RouterClientOrderIdError,
        ):
            assert not issubclass(RouterSubmissionResultError, unrelated)
            assert not isinstance(raised.value, unrelated)

    def test_a_store_failure_is_not_this_class(self) -> None:
        # The address fault keeps the member's existing class: a caller
        # catching the ask's refusal must not be handed a deployment fault,
        # and a caller catching the deployment fault must not be handed an
        # ask refusal.
        broken = RouterOrderPlacementStore("postgresql://localhost/router")
        with pytest.raises(RouterStoreError) as raised:
            broken.place(_order(), lambda: None)
        assert not isinstance(raised.value, RouterSubmissionResultError)


class TestTheMemberStillRegistersOneComponent:
    """Feature 317 adds a table, a module and a class — no component, no seat."""

    def test_exactly_one_builder(self) -> None:
        assert [name for name in dir(member) if name.startswith("build_")] == [
            "build_router_exchange_info_store"
        ]

    def test_the_seat_is_untouched(self) -> None:
        from app.modules import router as seat

        assert set(seat.__all__) == {
            "COMPONENT_NAME",
            "router_exchange_info_component",
            "router_submission_health_store",
        }
        assert not hasattr(seat, "RouterOrderPlacementStore")

    def test_the_member_exports_the_feature_317_names(self) -> None:
        for name in (
            "ORDER_PLACEMENT_OUTCOMES",
            "ORDER_PLACEMENT_TABLE",
            "OrderPlacement",
            "PlacementOrder",
            "PlacementResult",
            "RouterOrderPlacementStore",
            "RouterSubmissionResultError",
            "SUBMISSION_RESULT_CODE",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_module_reads_no_clock_of_its_own(self) -> None:
        # The one clock read is the ``now`` default in ``place``, and it is
        # a label rather than a term of any identity -- the key was hashed
        # from the rebalance's instant one module over, so no retry can
        # change a key by landing under a different clock reading.  Pinned
        # statically so a second clock read on a path this suite never walks
        # cannot hide.
        import ast
        import inspect

        import router.submission_result as module

        tree = ast.parse(inspect.getsource(module))
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now"
        ]
        assert len(reads) == 1


# -- Cross-process: the case the feature exists for ---------------------------

_SCRIPT = """
import datetime as dt
from router.client_order_id import derive_client_order_id
from router.submission_result import PlacementOrder, RouterOrderPlacementStore

store = RouterOrderPlacementStore({url!r})
order = PlacementOrder(
    client_order_id=str(
        derive_client_order_id(
            book_id={book!r},
            rebalance_ts=dt.datetime(
                2026, 9, 25, 12, 0, tzinfo=dt.timezone.utc
            ) + dt.timedelta(minutes={minutes}),
            symbol={symbol!r},
        )
    ),
    symbol={symbol!r},
)

sent = []


def place():
    sent.append(1)
    print("PLACED")


result = store.place(order, place, now=dt.datetime.now(dt.timezone.utc))
print("APPENDED" if result.appended else "REPLAYED")
print(len(sent))
"""


def _run(script: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(REPO_ROOT / "src"),
                str(REPO_ROOT / "packages" / "router" / "src"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestASecondProcessIsAnsweredByTheFirst:
    """A reclaimed spot instance re-runs the step; the venue hears it once."""

    def test_the_second_interpreter_does_not_place_a_second_order(
        self, test_database_url: str
    ) -> None:
        first = _run(
            _SCRIPT.format(url=test_database_url, book=BOOK, symbol=SYMBOL, minutes=0)
        )
        assert first.returncode == 0, first.stderr
        assert first.stdout.split() == ["PLACED", "APPENDED", "1"]

        second = _run(
            _SCRIPT.format(url=test_database_url, book=BOOK, symbol=SYMBOL, minutes=0)
        )
        assert second.returncode == 0, second.stderr
        # The second process derived the key itself, found the row the first
        # wrote, and answered from it: no PLACED, and a count of zero.
        assert second.stdout.split() == ["REPLAYED", "0"]

    def test_a_second_processes_different_leg_still_places(
        self, test_database_url: str
    ) -> None:
        _run(_SCRIPT.format(url=test_database_url, book=BOOK, symbol=SYMBOL, minutes=0))
        other = _run(
            _SCRIPT.format(
                url=test_database_url, book=BOOK, symbol=OTHER_SYMBOL, minutes=0
            )
        )
        assert other.returncode == 0, other.stderr
        assert other.stdout.split() == ["PLACED", "APPENDED", "1"]
