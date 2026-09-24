"""Feature 309's own suite: the persisted rebalance record.

app_spec.xml, "Portfolio Book Construction", feature 309: *System persists each
rebalance target weight set with its originating promoted signal identifiers.*

The suite lives inside the member (``packages/book/tests``) for the reason the
member's other suites state: the member — including its tests — is the feature's
file-claim scope, same-basename files collide under one pytest run, and each
member's suite is collected under its own conftest.

Every test that touches a database builds its own store over a ``tmp_path``
sqlite file, so no test can see another's rows and the suite is rerunnable.  The
verbs take the database path through :class:`book.RebalanceTargetWeightsStore`'s
constructor rather than through ``DATABASE_URL``: the environment is read by
:meth:`resolve` and pinned as such in
:func:`test_resolve_answers_none_for_a_deployment_that_named_no_database`, so a
developer's own exported ``DATABASE_URL`` cannot reach into these tests.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import book as member
import pytest
from book import NO_BOOK_CODE, NO_ORIGINATING_SIGNALS_CODE, REBALANCE_RECORDED_CODE
from conftest import BTC, ETH, SIGNAL_ONE, SIGNAL_THREE, SIGNAL_TWO, SOL, StandInSignal

#: The instant every test in this suite rebalances at, and one hour later — the
#: second rebalance, so a book's history has an order to be read in.
REBALANCE_AT = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
LATER = REBALANCE_AT + timedelta(hours=1)

#: The book every test records under, unless the test is about the book id.
BOOK = "book-a"


def _signals() -> list[StandInSignal]:
    """Three promoted signals — feature 301's own input surface, duck-typed.

    :class:`conftest.StandInSignal` carries exactly ``signal_id`` /
    ``information_ratio`` / ``target_scores``, so recording these exercises the
    same duck-typed seam the combiner depends on: the loader imports members
    under synthetic names, so a signal this process composed may be a second
    class object and the record must read ``signal_id`` rather than gate on the
    class.
    """
    return [
        StandInSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]


class _DuckBook:
    """A value exposing only ``weights`` — a caller's own spelling of a book.

    The seam this member states everywhere: the loader imports members under
    synthetic names, so a value this process composed may be a second class
    object, and the record reads the surface rather than gating on the class.
    """

    def __init__(self, weights) -> None:
        self.weights = weights


def _store(tmp_path) -> member.RebalanceTargetWeightsStore:
    return member.RebalanceTargetWeightsStore(f"sqlite:///{tmp_path}/book.db")


def _book(signals=None):
    """The published set the chain produces from the fixture signals.

    The whole upstream chain run for real — feature 301's combine, feature 303's
    volatility target, feature 305's publication — so the value recorded is the
    very value the order layer consumes rather than a hand-built stand-in.
    """
    return member.final_target_weights(
        member.apply_volatility_target(
            member.combine(_signals() if signals is None else signals),
            volatility=0.5,
            target_volatility=0.2,
        )
    )


# -- The act: the set and the provenance both land ---------------------------------


def test_the_act_records_the_set_and_its_provenance(tmp_path) -> None:
    # The sentence's two halves in one row: the target weight set the chain
    # published, and the identifiers of the promoted signals it originated from.
    store = _store(tmp_path)
    published = _book()
    record = store.record(
        book_id=BOOK,
        rebalance_ts=REBALANCE_AT,
        target_weights=published,
        originating_signals=_signals(),
    )
    assert record.book_id == BOOK
    assert record.rebalance_ts == REBALANCE_AT
    assert dict(record.weights) == dict(published.weights)
    # The provenance is read off the signals, sorted and distinct — three
    # signals, three identifiers, in one spelling.
    assert record.signal_ids == (SIGNAL_THREE, SIGNAL_TWO, SIGNAL_ONE)


def test_the_recorded_set_is_exactly_the_published_book(tmp_path) -> None:
    # No arithmetic: the act writes down the value the order layer consumes, so
    # every float is the very float feature 303 scaled and feature 305 published.
    # A recorded set that disagreed by one ulp would be a second answer to a
    # question the chain already answered.
    store = _store(tmp_path)
    published = _book()
    record = store.record(
        book_id=BOOK,
        rebalance_ts=REBALANCE_AT,
        target_weights=published,
        originating_signals=_signals(),
    )
    for symbol in published.symbols:
        assert record.weight(symbol) == published.weight(symbol)
    assert record.gross_exposure == published.gross_exposure


def test_the_record_survives_the_store_that_wrote_it(tmp_path) -> None:
    # The sentence's verb is *persists*, and the whole point of a database rather
    # than a memo is that a second process reads what the first wrote.  A fresh
    # store over the same file is that process.
    _store(tmp_path).record(
        book_id=BOOK,
        rebalance_ts=REBALANCE_AT,
        target_weights=_book(),
        originating_signals=_signals(),
    )
    read_back = _store(tmp_path).get(book_id=BOOK, rebalance_ts=REBALANCE_AT)
    assert read_back is not None
    assert dict(read_back.weights) == dict(_book().weights)
    assert read_back.signal_ids == (SIGNAL_THREE, SIGNAL_TWO, SIGNAL_ONE)


def test_the_provenance_is_read_off_the_signals_not_retyped(tmp_path) -> None:
    # The design decision the audit table rests on: a caller hands the promoted
    # signals, and this act reads their ``signal_id``.  A bare string of names is
    # refused rather than iterated character by character — a name is a claim
    # nothing can check against the book, which is the one thing provenance must
    # not be.
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights=_book(),
            originating_signals=SIGNAL_ONE,
        )
    assert "not their names" in str(caught.value)


def test_a_value_without_signal_ids_is_refused(tmp_path) -> None:
    # A signal that cannot be named cannot be recorded as one: the provenance is
    # the identifiers of the signals that weighted the book, so a value carrying
    # none has no place in it.
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights=_book(),
            originating_signals=["momentum"],
        )
    assert "carries none" in str(caught.value)


def test_an_absent_provenance_is_refused_not_recorded_empty(tmp_path) -> None:
    # Absence is not zero, read on the provenance: a set written down with no
    # provenance is the absence of one, not a provenance that happens to be
    # empty.  The code names the repair — *hand the signals it came from* — which
    # is a different word from ``no_book`` because the repair differs.
    store = _store(tmp_path)
    for empty in ([], ()):
        with pytest.raises(member.RebalanceRequestError) as caught:
            store.record(
                book_id=BOOK,
                rebalance_ts=REBALANCE_AT,
                target_weights=_book(),
                originating_signals=empty,
            )
        assert NO_ORIGINATING_SIGNALS_CODE in str(caught.value)


def test_a_non_iterable_provenance_is_refused_by_name(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights=_book(),
            originating_signals=7,
        )
    assert NO_ORIGINATING_SIGNALS_CODE in str(caught.value)


def test_a_duplicate_signal_is_refused_under_features_301_word(tmp_path) -> None:
    # A provenance is a *set*: the book was weighted by one signal, and a
    # provenance naming it twice is a malformed set of identifiers rather than a
    # second weighting.  The word is feature 301's own, read one step further
    # along the chain, because it is the same malformed-set fact about the same
    # identifiers.
    store = _store(tmp_path)
    signals = _signals()
    dominated = [signals[0], signals[1], signals[0]]
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights=_book(),
            originating_signals=dominated,
        )
    assert "duplicate_signal" in str(caught.value)


def test_a_blank_signal_id_is_refused(tmp_path) -> None:
    store = _store(tmp_path)
    signals = _signals()
    signals[1] = StandInSignal("  ", 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25})
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights=_book(),
            originating_signals=signals,
        )
    assert "non-empty text" in str(caught.value)


# -- The set: absence is not zero, and the flat book is a decision -----------------


def test_a_value_carrying_no_weights_is_refused_under_feature_305s_word(tmp_path) -> None:
    # ``no_book`` is feature 305's own token, imported rather than respelt: it is
    # the same fact about the same ``weights`` surface read one step further along
    # the chain, and a caller reading a deployment log should not have to learn a
    # second word for it.
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights={"BTC": 0.5},
            originating_signals=_signals(),
        )
    assert NO_BOOK_CODE in str(caught.value)


def test_a_set_covering_no_symbols_is_refused(tmp_path) -> None:
    # An empty *instruction* rather than a book held flat: the flat book is every
    # symbol weighted ``0.0`` and is recorded, while a set covering no symbols is
    # the absence of a book.  The stand-in is duck-typed rather than built through
    # :class:`book.FinalTargetWeights`, whose own construction refuses an empty
    # set (feature 305's law) — so this reaches the reader the way a caller's own
    # spelling of a book would.
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights=_DuckBook({}),
            originating_signals=_signals(),
        )
    assert NO_BOOK_CODE in str(caught.value)


def test_a_non_finite_weight_is_refused(tmp_path) -> None:
    store = _store(tmp_path)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(member.RebalanceRequestError) as caught:
            store.record(
                book_id=BOOK,
                rebalance_ts=REBALANCE_AT,
                target_weights=_DuckBook({BTC: bad}),
                originating_signals=_signals(),
            )
        assert "finite" in str(caught.value)


def test_a_weight_that_is_not_a_number_is_refused(tmp_path) -> None:
    # ``True`` is an ``int`` in Python, and a truthy flag accepted where a
    # magnitude belongs would land a decision in a size column.
    store = _store(tmp_path)
    for bad in ("0.5", True, None):
        with pytest.raises(member.RebalanceRequestError):
            store.record(
                book_id=BOOK,
                rebalance_ts=REBALANCE_AT,
                target_weights=_DuckBook({BTC: bad}),
                originating_signals=_signals(),
            )


def test_a_blank_symbol_is_refused(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=REBALANCE_AT,
            target_weights=_DuckBook({"": 0.5}),
            originating_signals=_signals(),
        )
    assert "symbol" in str(caught.value)


def test_a_book_held_flat_is_recorded_not_refused(tmp_path) -> None:
    # Feature 303's zero-target answer, admitted by feature 304 at every limit of
    # zero or more: *hold nothing* is a decision a rebalance is entitled to
    # record, and the provenance of that decision is real — three signals placed
    # a book at zero.
    store = _store(tmp_path)
    flat = _DuckBook({BTC: 0.0, ETH: 0.0, SOL: 0.0})
    record = store.record(
        book_id=BOOK,
        rebalance_ts=REBALANCE_AT,
        target_weights=flat,
        originating_signals=_signals(),
    )
    assert dict(record.weights) == {BTC: 0.0, ETH: 0.0, SOL: 0.0}
    assert record.gross_exposure == 0.0
    assert record.signal_ids == (SIGNAL_THREE, SIGNAL_TWO, SIGNAL_ONE)


# -- The identity: the rebalance's own pair, required ---------------------------------


def test_both_identity_keywords_are_required(tmp_path) -> None:
    # §13.2 keys the order path on ``(book_id, rebalance_ts, symbol)``, and two of
    # those three are the rebalance's.  Both are required with no default: a book
    # id would be a deployment's identity invented by this member, and a default
    # instant of *now* would make the row's identity the moment somebody called,
    # so a retry would land under a different identity.
    import inspect

    parameters = inspect.signature(member.RebalanceTargetWeightsStore.record).parameters
    for name in ("book_id", "rebalance_ts", "target_weights", "originating_signals"):
        assert parameters[name].default is inspect.Parameter.empty, name


def test_a_blank_book_id_is_refused(tmp_path) -> None:
    store = _store(tmp_path)
    for bad in ("", "   ", 7, None):
        with pytest.raises(member.RebalanceRequestError):
            store.record(
                book_id=bad,
                rebalance_ts=REBALANCE_AT,
                target_weights=_book(),
                originating_signals=_signals(),
            )


def test_a_naive_instant_is_refused(tmp_path) -> None:
    # A naive timestamp cannot say when a rebalance was for, and two books'
    # rebalances would be filed in one order or none.  Built without a tzinfo on
    # purpose: this is the ask the reader must refuse, so the naive construction
    # is the point rather than a slip.
    naive = datetime(  # noqa: DTZ001
        2026, 3, 2, 14, 30
    )
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError) as caught:
        store.record(
            book_id=BOOK,
            rebalance_ts=naive,
            target_weights=_book(),
            originating_signals=_signals(),
        )
    assert "timezone-aware" in str(caught.value)


def test_a_non_datetime_instant_is_refused(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError):
        store.record(
            book_id=BOOK,
            rebalance_ts="2026-03-02T14:30:00Z",
            target_weights=_book(),
            originating_signals=_signals(),
        )


def test_two_offsets_for_one_instant_are_one_rebalance(tmp_path) -> None:
    # The instant is held in one spelling — UTC — so ``14:30+00:00`` and
    # ``16:30+02:00`` are one rebalance and reach one row.  Without that, the
    # primary key would be a pair of *spellings* and a caller's offset would
    # silently double-book a rebalance.
    store = _store(tmp_path)
    published = _book()
    first = store.record(
        book_id=BOOK,
        rebalance_ts=REBALANCE_AT,
        target_weights=published,
        originating_signals=_signals(),
    )
    second = store.record(
        book_id=BOOK,
        rebalance_ts=REBALANCE_AT.astimezone(timezone(timedelta(hours=2))),
        target_weights=published,
        originating_signals=_signals(),
    )
    assert second.recorded_at == first.recorded_at
    assert len(store.history(BOOK)) == 1


# -- Idempotence: an identical re-issue is a retry ---------------------------------


def test_an_identical_re_issue_answers_the_standing_row_untouched(tmp_path) -> None:
    # A re-issue is the same call arriving twice — a reclaimed spot instance, a
    # loop that re-ran its rebalance step.  The set did not change, so the instant
    # it was recorded did not either: ``recorded_at`` is the database's stamp of
    # when the row was written, and a retry did not move it.
    store = _store(tmp_path)
    published = _book()
    first = store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    second = store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    assert second.recorded_at == first.recorded_at
    assert len(store.history(BOOK)) == 1


def test_the_re_issue_is_idempotent_whatever_order_the_signals_arrive_in(tmp_path) -> None:
    # The provenance is stored sorted and distinct, which is what makes one
    # spelling of it: a caller that hands the signals in another order hands the
    # same provenance, and the record says so rather than refusing a retry.
    store = _store(tmp_path)
    published = _book()
    first = store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    shuffled = [_signals()[2], _signals()[0], _signals()[1]]
    second = store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=shuffled,
    )
    assert second.recorded_at == first.recorded_at
    assert second.signal_ids == first.signal_ids


# -- The judgment: a differing set is a rewrite, refused ---------------------------


def test_a_different_set_for_the_same_rebalance_is_refused(tmp_path) -> None:
    # The sentence's *each*: one rebalance, one row.  Two sets for one instant
    # leave every reader of this table choosing between them, and here the row
    # *is* the record — no bound re-runs and no act re-applies — so a silent
    # overwrite would be a rebalance nobody decided, recorded as though somebody
    # had.
    store = _store(tmp_path)
    store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    other = member.final_target_weights(
        member.apply_volatility_target(
            member.combine(_signals()), volatility=0.5, target_volatility=0.3
        )
    )
    with pytest.raises(member.RebalanceRewriteError) as caught:
        store.record(
            book_id=BOOK, rebalance_ts=REBALANCE_AT,
            target_weights=other, originating_signals=_signals(),
        )
    assert REBALANCE_RECORDED_CODE in str(caught.value)
    # And the refusal names both records, so an operator has the row to repair.
    assert "book-a" in str(caught.value)


def test_a_different_provenance_for_the_same_set_is_refused(tmp_path) -> None:
    # The idempotence test is a content test on **both** halves.  A re-issue that
    # changed only the provenance is a different record of the same rebalance —
    # the provenance is half of what this feature writes down, so it is refused
    # as a rewrite rather than waved through as a retry.
    store = _store(tmp_path)
    published = _book()
    store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    with pytest.raises(member.RebalanceRewriteError):
        store.record(
            book_id=BOOK, rebalance_ts=REBALANCE_AT,
            target_weights=published, originating_signals=_signals()[:2],
        )


def test_the_refused_rewrite_leaves_the_standing_row_alone(tmp_path) -> None:
    # The verdict refuses; it does not overwrite.  This is the property that makes
    # the refusal worth having — a store that raised *and* wrote would leave the
    # record saying something nobody decided.
    store = _store(tmp_path)
    published = _book()
    first = store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    with pytest.raises(member.RebalanceRewriteError):
        store.record(
            book_id=BOOK, rebalance_ts=REBALANCE_AT,
            target_weights=_DuckBook({BTC: 0.9, ETH: 0.1}),
            originating_signals=_signals(),
        )
    standing = store.get(book_id=BOOK, rebalance_ts=REBALANCE_AT)
    assert dict(standing.weights) == dict(first.weights)
    assert standing.signal_ids == first.signal_ids
    assert standing.recorded_at == first.recorded_at


def test_a_different_book_may_record_the_same_instant(tmp_path) -> None:
    # The identity is the *pair*: the system runs more than one book (§C9), and
    # two books rebalancing at the same instant are two rebalances, not a
    # collision.
    store = _store(tmp_path)
    published = _book()
    store.record(
        book_id="book-a", rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    store.record(
        book_id="book-b", rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    assert len(store.history("book-a")) == 1
    assert len(store.history("book-b")) == 1


# -- The reads ---------------------------------------------------------------------


def test_a_rebalance_that_was_never_recorded_answers_none(tmp_path) -> None:
    # ``None`` rather than a default or a zeroed set: a rebalance nobody wrote
    # down is a different fact from one recorded flat, and the whole point of the
    # feature is that the second is evidence and the first is a gap.
    store = _store(tmp_path)
    assert store.get(book_id=BOOK, rebalance_ts=REBALANCE_AT) is None


def test_a_book_that_never_rebalanced_answers_no_history(tmp_path) -> None:
    # An empty tuple and not an error: unlike the *ask*, which is refused by name
    # when the book id states nothing.
    assert _store(tmp_path).history(BOOK) == ()


def test_a_malformed_ask_is_refused_by_get_as_well_as_by_record(tmp_path) -> None:
    # Both keywords are validated on the read path too, because a malformed ask
    # must be refused as the ask's own fact whether or not a row exists to read.
    store = _store(tmp_path)
    with pytest.raises(member.RebalanceRequestError):
        store.get(book_id="", rebalance_ts=REBALANCE_AT)
    with pytest.raises(member.RebalanceRequestError):
        store.get(book_id=BOOK, rebalance_ts="2026-03-02")
    with pytest.raises(member.RebalanceRequestError):
        store.history("   ")


def test_the_history_is_ordered_by_the_rebalance_not_by_the_write(tmp_path) -> None:
    # The rebalance's instant *is* the order the book was aimed in, so a backfill
    # that records an older rebalance after a newer one answers in the right
    # place.  Recording the later one first is what makes this test say something.
    store = _store(tmp_path)
    published = _book()
    store.record(
        book_id=BOOK, rebalance_ts=LATER,
        target_weights=published, originating_signals=_signals(),
    )
    store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals(),
    )
    history = store.history(BOOK)
    assert [one.rebalance_ts for one in history] == [REBALANCE_AT, LATER]


def test_the_history_carries_each_rebalances_own_provenance(tmp_path) -> None:
    # The sentence's *each*, read back: two rebalances, two sets, two
    # provenances, and neither is averaged into the other.
    store = _store(tmp_path)
    published = _book()
    store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=published, originating_signals=_signals()[:2],
    )
    store.record(
        book_id=BOOK, rebalance_ts=LATER,
        target_weights=published, originating_signals=_signals()[1:],
    )
    history = store.history(BOOK)
    assert [one.signal_ids for one in history] == [
        tuple(sorted([SIGNAL_ONE, SIGNAL_TWO])),
        tuple(sorted([SIGNAL_TWO, SIGNAL_THREE])),
    ]


# -- The record's own surface ------------------------------------------------------


def test_the_record_answers_which_signals_it_originated_from(tmp_path) -> None:
    # The sentence's own pairing, made answerable off the record, so an auditor
    # asking *did the momentum signal weight this rebalance?* reads it here rather
    # than re-reading the JSON column.
    record = _store(tmp_path).record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals()[:2],
    )
    assert record.originated_from(SIGNAL_ONE) is True
    assert record.originated_from(SIGNAL_THREE) is False
    assert record.symbols == (BTC, ETH, SOL)


def test_the_record_is_frozen_and_its_set_cannot_be_edited(tmp_path) -> None:
    # A record that could move after it was read would be a book that changed
    # beneath the audit that reads it — and on this record that guarantee carries
    # the sentence's own subject, because the row is the only record there is.
    record = _store(tmp_path).record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    # ``FrozenInstanceError`` is a ``dataclasses`` exception and a subclass of
    # ``AttributeError``; naming the concrete class here keeps the assertion
    # honest about what the frozen decorator is supposed to raise.
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.book_id = "book-b"  # type: ignore[misc]
    # And the set itself is a mapping proxy, so the record's weights cannot be
    # edited in place either — the second half of the same guarantee.
    with pytest.raises(TypeError):
        record.weights[BTC] = 0.0  # type: ignore[index]


def test_the_record_refuses_a_symbol_the_set_does_not_cover(tmp_path) -> None:
    # Refused rather than answered with a fabricated zero: a symbol the set
    # carries no weight for is not one this rebalance aimed at, and a zero would
    # read as *hold none of it* — a position decision the construction never made.
    record = _store(tmp_path).record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    with pytest.raises(member.RebalanceRequestError) as caught:
        record.weight("DOGE")
    assert "uncovered_symbol" in str(caught.value)


def test_the_record_renders_the_rows_own_columns(tmp_path) -> None:
    # The column names are the table's own, and the two JSON columns render as
    # their stored text, so what a caller sees here is what an operator at a
    # sqlite3 prompt would see.
    record = _store(tmp_path).record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    row = record.row()
    assert row["book_id"] == BOOK
    assert row["rebalance_ts"] == "2026-03-02T14:30:00+00:00"
    assert row["recorded_at"] is not None
    assert "BTC" in row["weights"]
    assert "momentum" in row["signal_ids"]


# -- The store's own face ----------------------------------------------------------


def test_resolve_answers_none_for_a_deployment_that_named_no_database() -> None:
    # An unset or empty ``DATABASE_URL`` is a discoverable deployment state, not
    # an exception: a deployment without a relational store records no rebalance.
    # The environment is read here and only here.
    assert member.RebalanceTargetWeightsStore.resolve(env={}) is None
    assert member.RebalanceTargetWeightsStore.resolve(env={"DATABASE_URL": "  "}) is None


def test_resolve_reads_the_workspace_environment_variable() -> None:
    store = member.RebalanceTargetWeightsStore.resolve(
        env={"DATABASE_URL": "sqlite:///tmp/book.db"}
    )
    assert store is not None
    assert store.database_url == "sqlite:///tmp/book.db"
    assert member.DATABASE_URL_ENV == "DATABASE_URL"


def test_a_store_pointed_at_nothing_is_refused(tmp_path) -> None:
    with pytest.raises(member.RebalanceStoreError):
        member.RebalanceTargetWeightsStore("")
    with pytest.raises(member.RebalanceStoreError):
        member.RebalanceTargetWeightsStore("   ")


def test_a_scheme_this_store_cannot_speak_is_refused_by_name(tmp_path) -> None:
    # A store's faults are its own class, never the ask's: the caller's position
    # differs — *fix what you handed me* against *your store is unreachable* —
    # and a caller that caught one as the other would repair the wrong thing.
    store = member.RebalanceTargetWeightsStore("postgresql://localhost/book")
    with pytest.raises(member.RebalanceStoreError) as caught:
        store.record(
            book_id=BOOK, rebalance_ts=REBALANCE_AT,
            target_weights=_book(), originating_signals=_signals(),
        )
    assert "sqlite" in str(caught.value)


def test_a_pathless_or_in_memory_url_is_refused(tmp_path) -> None:
    # A record must outlive the call that wrote it: the order path reads it back
    # on a retry and an audit reads it afterwards, both from another process.
    for url in ("sqlite://", "sqlite:///:memory:", "sqlite://localhost"):
        store = member.RebalanceTargetWeightsStore(url)
        with pytest.raises(member.RebalanceStoreError):
            store.record(
                book_id=BOOK, rebalance_ts=REBALANCE_AT,
                target_weights=_book(), originating_signals=_signals(),
            )


def test_construction_touches_no_disk(tmp_path) -> None:
    # Composing an application must never touch the database — the contract every
    # store in this workspace states — so a store built over a path that does not
    # exist composes fine and only fails when an operation is actually taken.
    missing = tmp_path / "nested" / "nowhere" / "book.db"
    store = member.RebalanceTargetWeightsStore(f"sqlite:///{missing}")
    assert store.database_url.endswith("book.db")
    assert not missing.exists()
    store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    assert missing.exists()


def test_a_corrupt_row_is_refused_as_the_stores_fault_naming_the_row(tmp_path) -> None:
    # The columns are rebuilt rather than summarised, so a row that will not
    # decode is refused rather than read as a *smaller* book — the direction that
    # erases the pairing this feature exists to record.  And the refusal is the
    # store's class, not the ask's: a caller never passed this row, so *fix what
    # you handed me* would be the wrong repair.
    import sqlite3

    store = _store(tmp_path)
    store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    connection = sqlite3.connect(store.path)
    with connection:
        connection.execute(
            "UPDATE book_rebalance_target_weights SET weights = ? WHERE book_id = ?",
            ("not json at all", BOOK),
        )
    connection.close()
    with pytest.raises(member.RebalanceStoreError) as caught:
        store.get(book_id=BOOK, rebalance_ts=REBALANCE_AT)
    assert BOOK in str(caught.value)
    assert "not JSON" in str(caught.value)


def test_a_row_whose_provenance_will_not_decode_is_refused(tmp_path) -> None:
    # The provenance half is checked by the same law: a row carrying no
    # provenance is a corrupted record rather than a rebalance that originated
    # from nothing.
    import sqlite3

    store = _store(tmp_path)
    store.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    connection = sqlite3.connect(store.path)
    with connection:
        connection.execute(
            "UPDATE book_rebalance_target_weights SET signal_ids = ? WHERE book_id = ?",
            ("[]", BOOK),
        )
    connection.close()
    with pytest.raises(member.RebalanceStoreError) as caught:
        store.history(BOOK)
    assert REBALANCE_RECORDED_CODE not in str(caught.value)
    assert BOOK in str(caught.value)


def test_the_table_is_created_idempotently(tmp_path) -> None:
    # Two stores, two connects, one table: the member-owned schema is created by
    # the only module that writes it, so no migration step is needed and a second
    # open is not an error.
    first = _store(tmp_path)
    second = _store(tmp_path)
    first.record(
        book_id=BOOK, rebalance_ts=REBALANCE_AT,
        target_weights=_book(), originating_signals=_signals(),
    )
    second.record(
        book_id=BOOK, rebalance_ts=LATER,
        target_weights=_book(), originating_signals=_signals(),
    )
    assert member.REBALANCE_TARGET_WEIGHTS_TABLE == "book_rebalance_target_weights"
    assert len(second.history(BOOK)) == 2


# -- The vocabulary -----------------------------------------------------------------


def test_the_features_three_classes_are_siblings_under_the_members_base() -> None:
    # One base class, so a caller can refuse the whole book surface with a single
    # ``except``; three siblings rather than one, because the caller's position
    # differs between a malformed ask, a rebalance already recorded differently,
    # and an unreachable store.
    for cls in (
        member.RebalanceRequestError,
        member.RebalanceRewriteError,
        member.RebalanceStoreError,
    ):
        assert issubclass(cls, member.BookConstructionError)
        assert cls is not member.BookConstructionError


def test_the_features_classes_are_not_any_other_features() -> None:
    # Never reuse another feature's class: each names a different repair, and a
    # caller that catches one must not accidentally catch the other.
    assert member.RebalanceRequestError is not member.FinalWeightsRequestError
    assert member.RebalanceRewriteError is not member.OrderLayerOutputError
    assert member.RebalanceStoreError is not member.BookConstructionError


def test_the_codes_are_the_sentences_own_words() -> None:
    assert member.NO_ORIGINATING_SIGNALS_CODE == "no_originating_signals"
    assert member.REBALANCE_RECORDED_CODE == "rebalance_already_recorded"
    # ``no_book`` is feature 305's own token, imported rather than respelt — the
    # same fact about the same surface read one step further along the chain.
    assert NO_BOOK_CODE == "no_book"
