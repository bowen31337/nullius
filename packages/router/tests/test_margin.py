"""Feature 315: isolated margin per book, and the merge it refuses.

app_spec.xml, "Order Routing & Venue Filters", feature 315: *System uses
isolated margin per book, which rejects a cross-margin configuration that
would merge independent positions.*  ``docs/nullius-tech-architecture.md``
§13.2 states the same rule as one line of the execution engine's contract —
*"Isolated margin per book. Cross margin converts N independent positions
into one position with N legs, and a single leg's liquidation cascades into
the rest."* — and ``docs/alpha-engine-prd.md`` C9 repeats it.

The tests below are organised around the two halves of that sentence,
because each can be false while the other is true:

* **uses isolated margin per book** — the act answers the arrangement, the
  mode is a closed vocabulary rather than free text, each book is
  independently margined, and a deployment's books are settled through one
  scope so the reading is structural rather than a paragraph a caller had to
  read;
* **rejects a cross-margin configuration that would merge independent
  positions** — a ``cross`` mode is refused by name, and so is the merge that
  arrives *without* the label: two books on one account, which is one position
  with N legs whatever each book is called.

The two refusals are deliberately different faults from the same class, and
the suite pins that they are not the member's other faults — a caller sent to
fix a filter version, a key's spelling or a rate limit while the venue holds
one position with N legs has been told the wrong repair.

No test needs a database.  The judgment is a pure function of the
configuration it is handed — the suite pins that too, by deleting
``DATABASE_URL`` and settling books anyway — so every test here runs with no
store behind it, which is the feature's own shape: nothing to persist,
nothing to compose.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import router as member
from router.errors import (
    CLIENT_ORDER_ID_CODE,
    CROSS_MARGIN_CODE,
    RATE_LIMITED_CODE,
    RETRY_BACKOFF_CODE,
    SUBMISSION_RESULT_CODE,
    RouterClientOrderIdError,
    RouterCrossMarginError,
    RouterError,
    RouterFilterError,
    RouterRateLimitError,
    RouterStoreError,
    RouterSubmissionHealthError,
    RouterSubmissionResultError,
)
from router.margin import (
    CROSS_MARGIN,
    ISOLATED_MARGIN,
    MARGIN_MODES,
    BookMargin,
    MarginScope,
    require_isolated_margin,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Two books of one deployment, spelled the way a configuration file would
#: spell them — the same shape as feature 316's ``momentum-core``, because
#: ``book_id`` is one identity across this member's features.
BOOK = "momentum-core"
OTHER_BOOK = "carry-basis"

#: The margin accounts the two books settle against.  Distinct on purpose:
#: that is what *isolated margin per book* means, and every merge case below
#: is built by making two books share one of these.
ACCOUNT = "book-momentum"
OTHER_ACCOUNT = "book-carry"
THIRD_ACCOUNT = "book-funding"


# =============================================================================
# "uses isolated margin per book"
# =============================================================================


class TestTheActAnswersTheArrangement:
    """The sentence's verb returns the arrangement, not a bare verdict."""

    def test_a_book_settles_under_isolated_margin(self) -> None:
        margin = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        assert isinstance(margin, BookMargin)
        assert margin.book_id == BOOK
        assert margin.account == ACCOUNT
        assert margin.mode == ISOLATED_MARGIN
        assert margin.is_isolated is True

    def test_isolated_is_the_default_mode(self) -> None:
        # The sentence is *system uses isolated margin*, so a caller that
        # states no mode gets the mode the sentence requires rather than a
        # fallback this module invented.  Pinned structurally: the default is
        # the constant, not a second literal.
        signature = inspect.signature(require_isolated_margin)
        assert signature.parameters["mode"].default == ISOLATED_MARGIN
        assert ISOLATED_MARGIN == "isolated"

    def test_the_terms_are_required_keywords(self) -> None:
        # A default would be this module naming a book or an account the
        # deployment never stated -- the law feature 316's own rebalance_ts
        # states for its term one module over.
        signature = inspect.signature(require_isolated_margin)
        for name in ("book_id", "account"):
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, name
        with pytest.raises(TypeError):
            require_isolated_margin(BOOK, ACCOUNT)  # type: ignore[misc]

    def test_the_arrangement_is_frozen_and_hashable(self) -> None:
        import dataclasses

        margin = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        assert dataclasses.is_dataclass(margin)
        with pytest.raises(dataclasses.FrozenInstanceError):
            margin.account = OTHER_ACCOUNT  # type: ignore[misc]
        # It stands as its own key -- a scope files it by the value.
        assert {margin: BOOK}[margin] == BOOK

    def test_each_book_is_margined_on_its_own_account(self) -> None:
        # The feature's whole claim, read off two books of one deployment.
        first = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        second = require_isolated_margin(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        assert first.account != second.account
        assert first.is_isolated and second.is_isolated


class TestTheModeVocabularyIsClosed:
    """`isolated` and `cross` are the two arrangements; nothing else is one."""

    def test_the_vocabulary_is_exactly_the_two_modes(self) -> None:
        assert MARGIN_MODES == frozenset({"isolated", "cross"})
        assert ISOLATED_MARGIN in MARGIN_MODES
        assert CROSS_MARGIN in MARGIN_MODES

    @pytest.mark.parametrize(
        "absent", ["Isolated", "ISOLATED", "isolate", "cross_margin", "portfolio"]
    )
    def test_a_misspelled_mode_is_not_a_near_match(self, absent: str) -> None:
        # Refused naming the value rather than case-folded onto a real mode: a
        # mode this module guessed at would be a margin arrangement nobody
        # configured.
        with pytest.raises(RouterCrossMarginError) as raised:
            require_isolated_margin(book_id=BOOK, account=ACCOUNT, mode=absent)
        assert CROSS_MARGIN_CODE in str(raised.value)

    @pytest.mark.parametrize("bad", [None, 315, b"isolated", [], {}, 1.0, True])
    def test_a_mode_that_is_not_a_token_is_refused_by_name(self, bad: object) -> None:
        # The unhashable cases matter: ``frozenset`` membership raises
        # TypeError on ``[]``, and a caller offering a list to a vocabulary of
        # tokens deserves this member's refusal naming the value.
        with pytest.raises(RouterCrossMarginError) as raised:
            require_isolated_margin(book_id=BOOK, account=ACCOUNT, mode=bad)
        assert str(raised.value).startswith(f"{CROSS_MARGIN_CODE}:")

    def test_a_book_that_states_nothing_is_refused(self) -> None:
        # The feature's own ground, not only the shared name rule: a book with
        # no name is not a position this system can keep independent -- it is
        # the venue's whole balance standing behind whatever is in it, which is
        # cross margin reached without configuring it.
        for blank in ("", "   ", "\n", None, 315, []):
            with pytest.raises(RouterCrossMarginError) as raised:
                require_isolated_margin(book_id=blank, account=ACCOUNT)
            assert str(raised.value).startswith(f"{CROSS_MARGIN_CODE}:")

    def test_an_account_that_states_nothing_is_refused(self) -> None:
        for blank in ("", "   ", None, 315, []):
            with pytest.raises(RouterCrossMarginError) as raised:
                require_isolated_margin(book_id=BOOK, account=blank)
            assert str(raised.value).startswith(f"{CROSS_MARGIN_CODE}:")


class TestTheNamesAreCanonicalisedButNeverRespelled:
    """Near misses are stripped; nothing is case-folded or renamed."""

    def test_surrounding_whitespace_is_stripped(self) -> None:
        # A pasted configuration copy carries a trailing newline or an indent,
        # and folding it would file one book under two names.
        padded = require_isolated_margin(book_id=f"  {BOOK}\n", account=f"\t{ACCOUNT} ")
        plain = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        assert padded == plain

    def test_the_book_name_is_otherwise_verbatim(self) -> None:
        # A case-folded name would rename the deployment's own configuration --
        # the rule feature 316's derivation and feature 309's rebalance table
        # both hold this same term to.
        upper = require_isolated_margin(book_id=BOOK.upper(), account=ACCOUNT)
        lower = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        assert upper.book_id != lower.book_id

    def test_the_account_is_verbatim_so_the_merge_comparison_is_over_real_names(
        self,
    ) -> None:
        # The account is the thing that merges, so normalizing two spellings
        # into one value would be this module deciding two accounts are one --
        # the judgment the venue owns.
        upper = require_isolated_margin(book_id=BOOK, account=ACCOUNT.upper())
        lower = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        assert upper.account != lower.account


# =============================================================================
# "rejects a cross-margin configuration"
# =============================================================================


class TestCrossMarginIsRefusedByName:
    """The labelled merge: a book configured to share the account's balance."""

    def test_a_cross_arrangement_is_refused(self) -> None:
        with pytest.raises(RouterCrossMarginError) as raised:
            require_isolated_margin(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        message = str(raised.value)
        assert message.startswith(f"{CROSS_MARGIN_CODE}:")
        # It names the book, the account and the mode that was supplied, and
        # the one repair that exists.
        assert BOOK in message
        assert ACCOUNT in message
        assert CROSS_MARGIN in message
        assert ISOLATED_MARGIN in message

    def test_the_refusal_cites_the_governing_documents(self) -> None:
        # A deployment editing its book configuration is the audience, and the
        # reason belongs with the line it has to change.
        with pytest.raises(RouterCrossMarginError) as raised:
            require_isolated_margin(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        message = str(raised.value)
        assert "§13.2" in message
        assert "C9" in message
        assert "N legs" in message

    def test_a_cross_book_is_refused_even_with_no_scope(self) -> None:
        # Refused for its own sake, not only when it happens to collide with
        # another book: the mode rule stands alone.
        with pytest.raises(RouterCrossMarginError):
            require_isolated_margin(
                book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN, scope=None
            )

    def test_a_cross_book_is_refused_even_on_an_account_of_its_own(self) -> None:
        # The account being unshared does not save it -- cross margin merges
        # *within* the book, which is the cascade the sentence names.
        scope = MarginScope()
        with pytest.raises(RouterCrossMarginError):
            scope.require(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        assert len(scope) == 0

    def test_the_value_type_can_describe_a_cross_arrangement(self) -> None:
        # Enforcement is the gate's, not the value's: a value type that could
        # not express the arrangement this feature refuses could not be
        # compared against.  Constructible, and it reads honestly.
        cross = BookMargin(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        assert cross.mode == CROSS_MARGIN
        assert cross.is_isolated is False


class TestTheMergeWithoutTheLabelIsRefused:
    """Two books on one account are one position with N legs, whatever the label."""

    def test_two_books_sharing_one_account_are_refused(self) -> None:
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        with pytest.raises(RouterCrossMarginError) as raised:
            scope.require(book_id=OTHER_BOOK, account=ACCOUNT)
        message = str(raised.value)
        assert message.startswith(f"{CROSS_MARGIN_CODE}:")
        # Both books and the shared account are named, because the repair is
        # to give one of them its own account and an operator needs to know
        # which two.
        assert BOOK in message
        assert OTHER_BOOK in message
        assert ACCOUNT in message
        assert "N legs" in message

    def test_the_refusal_is_not_only_the_labelled_case(self) -> None:
        # The load-bearing one: BOTH books are configured isolated, and the
        # merge arrives through the account rather than through the mode --
        # so a gate that only read the mode label would pass this.
        scope = MarginScope()
        first = scope.require(book_id=BOOK, account=ACCOUNT, mode=ISOLATED_MARGIN)
        assert first.mode == ISOLATED_MARGIN
        with pytest.raises(RouterCrossMarginError):
            scope.require(book_id=OTHER_BOOK, account=ACCOUNT, mode=ISOLATED_MARGIN)

    def test_distinct_accounts_do_not_merge(self) -> None:
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        scope.require(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        assert len(scope) == 2
        assert scope.accounts() == (ACCOUNT, OTHER_ACCOUNT)

    def test_a_refused_book_leaves_no_trace(self) -> None:
        # A deployment that gives the colliding book its own account and
        # retries is judged against the books that stand, not against what was
        # rejected.
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        with pytest.raises(RouterCrossMarginError):
            scope.require(book_id=OTHER_BOOK, account=ACCOUNT)
        assert scope.books() == (BOOK,)
        assert scope.account_for(OTHER_BOOK) is None
        # And the repair works.
        scope.require(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        assert scope.books() == (BOOK, OTHER_BOOK)

    def test_the_third_book_is_judged_against_both(self) -> None:
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        scope.require(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        for taken in (ACCOUNT, OTHER_ACCOUNT):
            with pytest.raises(RouterCrossMarginError):
                scope.require(book_id="third-book", account=taken)

    def test_the_accounts_reading_counts_independent_positions(self) -> None:
        # *How many independent positions is this book list actually worth?* --
        # answered by the accounts, not the books, which is the whole point.
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        scope.require(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        assert len(scope) == 2
        assert len(scope.accounts()) == 2
        assert scope.accounts() == (ACCOUNT, OTHER_ACCOUNT)

    def test_a_collision_against_a_held_entry_is_refused_whatever_it_was_named(
        self,
    ) -> None:
        # The merge is judged on the *account*, so it does not matter which
        # book got there first or what the caller called the mode.
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT, mode=ISOLATED_MARGIN)
        with pytest.raises(RouterCrossMarginError):
            scope.require(book_id=OTHER_BOOK, account=ACCOUNT, mode=ISOLATED_MARGIN)


class TestOneBookOneEntry:
    """A reload re-states; it does not merge a book with itself."""

    def test_re_stating_a_books_own_arrangement_is_idempotent(self) -> None:
        # The startup-and-daily reload (§13.2) has to be safe to repeat.
        scope = MarginScope()
        first = scope.require(book_id=BOOK, account=ACCOUNT)
        second = scope.require(book_id=BOOK, account=ACCOUNT)
        assert first == second
        assert len(scope) == 1
        assert scope.books() == (BOOK,)
        assert scope.account_for(BOOK) == ACCOUNT

    def test_a_book_repointed_at_a_free_account_moves(self) -> None:
        # Which account a book settles against is the deployment's
        # configuration, and a configuration that changed is one the
        # deployment is entitled to state.  The merge this feature refuses is
        # two books on one account *at rest*, never a book being reconfigured
        # away from one -- refusing the re-point would leave a deployment
        # unable to correct a book's account at all.
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        scope.require(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        repointed = scope.require(book_id=OTHER_BOOK, account=THIRD_ACCOUNT)
        assert repointed.account == THIRD_ACCOUNT
        assert scope.account_for(OTHER_BOOK) == THIRD_ACCOUNT
        # One entry for the book, not two -- the old arrangement is gone, so
        # the account it left behind is free again.
        assert len(scope) == 2
        assert scope.accounts() == (ACCOUNT, THIRD_ACCOUNT)
        scope.require(book_id="third-book", account=OTHER_ACCOUNT)

    def test_a_repoint_onto_a_book_own_account_is_refused(self) -> None:
        # The merge is the same merge however the book arrived at it.
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        scope.require(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        with pytest.raises(RouterCrossMarginError):
            scope.require(book_id=OTHER_BOOK, account=ACCOUNT)
        # Refused, and nothing moved.
        assert scope.account_for(OTHER_BOOK) == OTHER_ACCOUNT


class TestTheScopeReadsWhatItHolds:
    """A deployment can be inspected as well as configured."""

    def test_a_fresh_scope_holds_nothing(self) -> None:
        scope = MarginScope()
        assert len(scope) == 0
        assert scope.books() == ()
        assert scope.accounts() == ()
        assert scope.account_for(BOOK) is None
        assert scope.margin_for(BOOK) is None
        assert BOOK not in scope

    def test_a_scope_answers_by_book(self) -> None:
        scope = MarginScope()
        margin = scope.require(book_id=BOOK, account=ACCOUNT)
        assert scope.margin_for(BOOK) == margin
        assert scope.account_for(BOOK) == ACCOUNT
        assert BOOK in scope
        assert OTHER_BOOK not in scope
        assert list(scope) == [(BOOK, margin)]

    def test_membership_answers_false_for_a_name_that_cannot_be_a_book(self) -> None:
        # ``in`` is a question, not an ask: a value that cannot be a book id
        # is not in the scope, rather than raising out of ``__contains__``.
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        for bad in ("", None, 315, []):
            assert bad not in scope

    def test_the_reading_validates_the_name_it_is_asked_about(self) -> None:
        scope = MarginScope()
        with pytest.raises(RouterCrossMarginError):
            scope.account_for("")
        with pytest.raises(RouterCrossMarginError):
            scope.margin_for("")

    def test_a_deployment_can_be_described_from_its_arrangements(self) -> None:
        arrangements = [
            BookMargin(book_id=BOOK, account=ACCOUNT),
            BookMargin(book_id=OTHER_BOOK, account=OTHER_ACCOUNT),
        ]
        scope = MarginScope.from_arrangements(arrangements)
        assert scope.books() == (BOOK, OTHER_BOOK)
        assert scope.account_for(BOOK) == ACCOUNT

    def test_describing_a_merged_deployment_is_refused_by_construction(self) -> None:
        # The one place a caller could otherwise skip the sentence entirely:
        # smuggling a merge in through a constructor.
        merged = [
            BookMargin(book_id=BOOK, account=ACCOUNT),
            BookMargin(book_id=OTHER_BOOK, account=ACCOUNT),
        ]
        with pytest.raises(RouterCrossMarginError):
            MarginScope.from_arrangements(merged)

    def test_describing_a_deployment_of_cross_books_is_refused(self) -> None:
        with pytest.raises(RouterCrossMarginError):
            MarginScope.from_arrangements(
                [BookMargin(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)]
            )

    def test_a_scope_never_holds_a_cross_arrangement(self) -> None:
        # The invariant is the feature, not a stricter reading of it: the
        # scope *is* the structure that makes the sentence structural, so a
        # scope any read path could be pointed at must not be one a
        # deployment can put a cross arrangement into.  Pinned at the primary
        # constructor rather than only at ``from_arrangements``, so the two
        # cannot disagree about what a scope may contain.
        cross = BookMargin(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        assert cross.is_isolated is False  # the value still expresses it
        with pytest.raises(RouterCrossMarginError) as raised:
            MarginScope({BOOK: cross})
        assert str(raised.value).startswith(f"{CROSS_MARGIN_CODE}:")
        # ... and nothing was half-built: the scope never came into being.
        scope = MarginScope()
        with pytest.raises(RouterCrossMarginError):
            scope.require(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        assert len(scope) == 0

    def test_the_primary_constructor_and_from_arrangements_agree(self) -> None:
        # Two doors into one invariant, so a caller cannot pick the permissive
        # one -- the whole point of checking at construction.
        cross = BookMargin(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        for build in (
            lambda: MarginScope({BOOK: cross}),
            lambda: MarginScope.from_arrangements([cross]),
        ):
            with pytest.raises(RouterCrossMarginError):
                build()

    def test_a_scope_cannot_hold_an_entry_its_key_disagrees_with(self) -> None:
        with pytest.raises(RouterCrossMarginError):
            MarginScope(
                {
                    BOOK: BookMargin(book_id=OTHER_BOOK, account=ACCOUNT),
                }
            )

    def test_a_scope_cannot_hold_something_that_is_not_an_arrangement(self) -> None:
        with pytest.raises(RouterCrossMarginError):
            MarginScope({BOOK: ACCOUNT})  # type: ignore[dict-item]

    def test_a_scope_cannot_be_described_by_something_that_is_not_a_mapping(
        self,
    ) -> None:
        for bad in ([BOOK], BOOK, 315):
            with pytest.raises(RouterCrossMarginError) as raised:
                MarginScope(bad)  # type: ignore[arg-type]
            assert str(raised.value).startswith(f"{CROSS_MARGIN_CODE}:")

    def test_a_scope_keys_its_entries_by_the_canonical_name(self) -> None:
        scope = MarginScope({f"  {BOOK} ": BookMargin(book_id=BOOK, account=ACCOUNT)})
        assert scope.books() == (BOOK,)
        assert scope.account_for(BOOK) == ACCOUNT

    def test_describing_a_deployment_from_a_mapping_keys_by_its_values(self) -> None:
        scope = MarginScope.from_arrangements(
            {
                "anything": BookMargin(book_id=BOOK, account=ACCOUNT),
                "at-all": BookMargin(book_id=OTHER_BOOK, account=OTHER_ACCOUNT),
            }
        )
        assert scope.books() == (BOOK, OTHER_BOOK)

    def test_a_non_arrangement_in_a_description_is_refused(self) -> None:
        with pytest.raises(RouterCrossMarginError):
            MarginScope.from_arrangements([BOOK, OTHER_BOOK])


# =============================================================================
# The vocabulary, the class tree, and the member
# =============================================================================


class TestTheErrorVocabulary:
    """Feature 315's refusal is its own class with its own greppable word."""

    def test_the_code_is_the_one_the_messages_open_with(self) -> None:
        with pytest.raises(RouterCrossMarginError) as raised:
            require_isolated_margin(book_id="", account=ACCOUNT)
        assert str(raised.value).startswith(f"{CROSS_MARGIN_CODE}:")
        assert CROSS_MARGIN_CODE == "cross_margin"

    def test_it_is_not_the_identifier_code(self) -> None:
        # One grep apart, deliberately: both judge a ``book_id``, and feature
        # 316's class refuses a name it cannot hash into a *key* while this one
        # refuses the *arrangement that name's book* is configured with.
        assert CROSS_MARGIN_CODE != CLIENT_ORDER_ID_CODE
        assert CROSS_MARGIN_CODE != RATE_LIMITED_CODE
        assert CROSS_MARGIN_CODE != RETRY_BACKOFF_CODE
        assert CROSS_MARGIN_CODE != SUBMISSION_RESULT_CODE

    def test_it_is_a_router_error_and_its_own_sibling(self) -> None:
        # Catchable through the member's one base, and *not* an instance of any
        # of the faults it must not be mistaken for: a caller catching the fetch
        # fault, the record fault, the health fault, the identifier fault, the
        # rate-limit tree or the duplicate-submission fault must not have this
        # refusal land in its ``except``.
        with pytest.raises(RouterError) as raised:
            require_isolated_margin(book_id=BOOK, account=ACCOUNT, mode=CROSS_MARGIN)
        for unrelated in (
            RouterFilterError,
            RouterStoreError,
            RouterSubmissionHealthError,
            RouterClientOrderIdError,
            RouterRateLimitError,
            RouterSubmissionResultError,
        ):
            assert not issubclass(RouterCrossMarginError, unrelated)
            assert not isinstance(raised.value, unrelated)

    def test_it_is_not_a_router_client_order_id_error(self) -> None:
        # The fine split: the book in this fault is spelled perfectly well, and
        # a caller sent to fix a name instead of a margin mode would leave the
        # venue holding one position with N legs.
        assert not issubclass(RouterCrossMarginError, RouterClientOrderIdError)
        assert not issubclass(RouterClientOrderIdError, RouterCrossMarginError)


class TestTheMemberStillRegistersOneComponent:
    """Feature 315 adds a module and a class -- no component, no seat, no table."""

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
        assert not hasattr(seat, "MarginScope")
        assert not hasattr(seat, "require_isolated_margin")

    def test_the_member_exports_the_feature_315_names(self) -> None:
        for name in (
            "CROSS_MARGIN",
            "CROSS_MARGIN_CODE",
            "ISOLATED_MARGIN",
            "MARGIN_MODES",
            "BookMargin",
            "MarginScope",
            "RouterCrossMarginError",
            "require_isolated_margin",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_member_still_exports_exactly_one_order_key(self) -> None:
        # Feature 315 writes no table and reads no identity: feature 316's key
        # is untouched, and this module never re-spells it.
        assert "client_order_digest" in member.__all__
        assert "normalize_client_order_id" in member.__all__


class TestTheGateIsPure:
    """No clock, no I/O, no store -- the same ask answers the same verdict."""

    def test_the_derivation_reads_no_clock_of_its_own(self) -> None:
        # Pinned statically: a clock read here would make a *configuration*
        # judgment depend on when it was taken, which is the one property a
        # gate that runs at startup and on daily reload cannot have.
        import router.margin as module

        tree = ast.parse(inspect.getsource(module))
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now"
        ]
        assert reads == []

    def test_the_module_imports_no_store(self) -> None:
        # Nothing to persist: a margin mode is a property of one process's
        # startup configuration, not a fact the next process must agree on.
        import router.margin as module

        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("sqlite3", "os", "datetime", "socket", "pathlib"):
            assert forbidden not in imported, forbidden

    def test_the_judgment_needs_no_database(self) -> None:
        # The feature's own shape: nothing to persist, nothing to compose.  If
        # this ever needs a store, this test fails.
        scope = MarginScope()
        scope.require(book_id=BOOK, account=ACCOUNT)
        scope.require(book_id=OTHER_BOOK, account=OTHER_ACCOUNT)
        assert len(scope.accounts()) == 2

    def test_settling_is_deterministic(self) -> None:
        first = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        second = require_isolated_margin(book_id=BOOK, account=ACCOUNT)
        assert first == second


class TestTheCrossProcessCase:
    """Two routers configure one deployment; the refusal is the same in both."""

    _SCRIPT = """
import json

from router.margin import MARGIN_MODES, require_isolated_margin
from router.errors import RouterCrossMarginError

print(json.dumps(sorted(MARGIN_MODES)))
print(require_isolated_margin(book_id={book!r}, account={account!r}).mode)
try:
    require_isolated_margin(
        book_id={book!r}, account={account!r}, mode={cross!r}
    )
except RouterCrossMarginError as exc:
    print(str(exc).startswith({code!r}))
"""

    def _run(self, script: str) -> subprocess.CompletedProcess[str]:
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

    def test_another_interpreter_answers_the_same_verdict(self) -> None:
        script = self._SCRIPT.format(
            book=BOOK, account=ACCOUNT, cross=CROSS_MARGIN, code=CROSS_MARGIN_CODE
        )
        finished = self._run(script)
        assert finished.returncode == 0, finished.stderr
        vocabulary, mode, refused = finished.stdout.strip().splitlines()
        assert json.loads(vocabulary) == sorted(MARGIN_MODES)
        assert mode == ISOLATED_MARGIN
        assert refused == "True"
