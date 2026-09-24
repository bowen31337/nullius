"""Feature 316: the client order identifier, hashed not generated.

app_spec.xml, "Order Routing & Venue Filters", feature 316: *System derives
a client order identifier by hashing book id, rebalance timestamp and
symbol, which returns an idempotent resubmission key.*  The tests below are
organised around the three things that sentence claims, because each is a
thing that can be false while the others are true:

* **derives ... by hashing book id, rebalance timestamp and symbol** — each
  of the three terms is a genuine term: moving any one moves the key, the
  framing keeps terms that could bleed into each other apart, and the
  byte-level spelling is pinned to one exact digest, because a hash over
  under-specified bytes is a hash over nothing;
* **idempotent** — the same three terms answer the same key whatever
  spelling the caller held the instant in, whatever whitespace a pasted
  copy of the book's name carried, in this process and in a restarted one,
  with no clock read and no state consulted;
* **a resubmission key** — the value a re-sending process derives and the
  value the first process derived are one value, which is the property
  feature 317's duplicate answer and feature 320's health join are built
  on: the join 320 documented for its ``client_order_id`` column is
  exercised against the real key at the bottom of this suite.

No test needs a database.  The derivation is a pure function — the suite
pins that too, by deleting ``DATABASE_URL`` and deriving anyway — so every
test here runs with no store behind it, which is the feature's own shape:
nothing to persist, nothing to compose.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone

import pytest
import router as member
from router.client_order_id import (
    CLIENT_ORDER_ID_LENGTH,
    ClientOrderId,
    client_order_digest,
    derive_client_order_id,
    normalize_client_order_id,
)
from router.errors import (
    CLIENT_ORDER_ID_CODE,
    RouterClientOrderIdError,
    RouterError,
    RouterFilterError,
    RouterRateLimitError,
    RouterStoreError,
    RouterSubmissionHealthError,
)
from router.submission_health import (
    ORDER_SUBMISSION_ACCEPTED,
    ORDER_SUBMISSION_OUTCOMES,
    SubmissionObservation,
    process_identity,
)

#: The fixed instant the whole suite reasons from — and, deliberately, the
#: same calendar day ``test_retry.py`` and ``test_limiter.py`` reason from,
#: so the three suites describe one order path on one trading day.
T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

#: The book the suite submits for: a deployment's own name, spelled the way
#: a configuration file would spell it.
BOOK = "momentum-core"

#: The leg the suite submits: the venue's own spelling, upper-case the way
#: exchangeInfo lists it (the fixtures in ``conftest.py`` carry the same
#: two symbols).
SYMBOL = "BTCUSDT"

#: The exact digest of ``(BOOK, T0, SYMBOL)`` under the formula's pinned
#: byte-level spelling — the three canonical terms as one compact JSON
#: array, UTF-8, sha256, hexdigest.  Pinned, deliberately: the preimage
#: *is* the format, so a change to the framing, the separators, the term
#: order or the timestamp spelling must break this test loudly rather than
#: silently re-keying every order the system has ever submitted.  The
#: snapshot and evaluator suites pin their formulas' spellings the same
#: way.
PINNED_DIGEST = "dae4db89859497b1e5de8f70b518266c7704fb95f77b53347a93eac7e5ed633a"

_HEX = frozenset("0123456789abcdef")


def _derive(
    book: str = BOOK, moment: datetime = T0, symbol: str = SYMBOL
) -> ClientOrderId:
    """The suite's one spelling of the ask, so no test restates keywords."""
    return derive_client_order_id(
        book_id=book, rebalance_ts=moment, symbol=symbol
    )


class TestTheFormula:
    """*By hashing book id, rebalance timestamp and symbol* — the terms."""

    def test_the_digest_is_64_lowercase_hex_characters(self) -> None:
        key = _derive()
        assert len(key.client_order_id) == CLIENT_ORDER_ID_LENGTH == 64
        assert set(key.client_order_id) <= _HEX

    def test_the_byte_level_spelling_is_pinned(self) -> None:
        # The preimage is the format: compact JSON array of the canonical
        # terms, UTF-8, hashed once.  Any silent change to that spelling
        # re-keys every order ever submitted, so it must not be silent.
        assert _derive().client_order_id == PINNED_DIGEST
        assert (
            client_order_digest(
                book_id=BOOK, rebalance_ts=T0, symbol=SYMBOL
            )
            == PINNED_DIGEST
        )

    def test_book_is_a_term(self) -> None:
        # Two books holding the same symbol at the same instant are two
        # orders (§C9 runs more than one book), so the book moves the key.
        assert _derive().client_order_id != _derive(book="carry-lean").client_order_id

    def test_rebalance_ts_is_a_term(self) -> None:
        # A book rebalanced twice to the same symbol places two orders;
        # one microsecond is enough to tell them apart, because the
        # instant is folded to whole-microsecond precision.
        later = T0 + timedelta(microseconds=1)
        assert _derive().client_order_id != _derive(moment=later).client_order_id
        next_day = T0 + timedelta(days=1)
        assert _derive().client_order_id != _derive(moment=next_day).client_order_id

    def test_symbol_is_a_term(self) -> None:
        # A rebalance is a set of weights; each symbol's order is one leg
        # with its own key, because the venue fills per symbol.
        assert _derive().client_order_id != _derive(symbol="ETHUSDT").client_order_id

    def test_the_framing_keeps_terms_separable(self) -> None:
        # The one attack a separator-less concatenation admits: a book
        # whose name ends where another's begins, folding the same bytes
        # under a different split of the same terms.  The JSON framing
        # escapes its own structure, so the two triples stay two keys.
        glued = _derive(book="momentum", symbol="core-BTCUSDT").client_order_id
        split = _derive(book="momentum-core", symbol="BTCUSDT").client_order_id
        assert glued != split

    def test_terms_do_not_bleed_across_orders(self) -> None:
        # No order's key is another order's key: varying each term across
        # a handful of values mints a handful of distinct keys, which is
        # all a resubmission answer needs from a hash (and sha256's
        # collision resistance is the reason the digest is kept whole).
        keys = set()
        for book in ("momentum-core", "carry-lean", "stat-arb"):
            for hours in (0, 6, 12, 18):
                for symbol in ("BTCUSDT", "ETHUSDT"):
                    keys.add(
                        _derive(
                            book=book,
                            moment=T0 + timedelta(hours=hours),
                            symbol=symbol,
                        ).client_order_id
                    )
        assert len(keys) == 3 * 4 * 2


class TestIdempotence:
    """*Idempotent* — one triple, one key, always."""

    def test_the_same_terms_answer_the_same_key(self) -> None:
        assert _derive() == _derive()
        assert _derive().client_order_id == _derive().client_order_id

    def test_two_spellings_of_one_instant_are_one_order(self) -> None:
        # 12:00+02:00 and 10:00+00:00 are one rebalance; a router holding
        # the instant in the venue's timezone must not mint a second key
        # for the order the UTC-holding process already sent.
        summer = T0.astimezone(timezone(timedelta(hours=2)))
        assert _derive(moment=summer).client_order_id == PINNED_DIGEST
        assert _derive(moment=summer) == _derive()

    def test_a_normalized_instant_folds_like_a_bare_utc_one(self) -> None:
        # ``astimezone`` round-trips are free: the term is the instant,
        # not the spelling, so re-normalizing changes nothing.
        re_normalized = T0.astimezone(timezone(timedelta(hours=-5))).astimezone(UTC)
        assert _derive(moment=re_normalized).client_order_id == PINNED_DIGEST

    def test_zero_microseconds_fold_like_absent_ones(self) -> None:
        # isoformat omits a zero-microsecond component; the two spellings
        # are still one instant and therefore one term.
        explicit = datetime(
            2026, 9, 25, 12, 0, 0, 0, tzinfo=UTC
        )
        assert _derive(moment=explicit).client_order_id == PINNED_DIGEST

    def test_whitespace_around_a_name_is_not_a_second_book(self) -> None:
        # A pasted copy of the deployment's configuration must not derive
        # a second identity for every order one book places.
        padded = _derive(book=f"  {BOOK}\n", symbol=f" {SYMBOL} ")
        assert padded == _derive()
        assert padded.client_order_id == PINNED_DIGEST

    def test_the_three_entry_points_answer_one_value(self) -> None:
        # The bare digest, the verb and direct construction fold through
        # the one ``_fold``, so a caller cannot hold two spellings of one
        # order's name depending on how it asked.
        digest = client_order_digest(
            book_id=BOOK, rebalance_ts=T0, symbol=SYMBOL
        )
        built = ClientOrderId(
            book_id=BOOK, rebalance_ts=T0, symbol=SYMBOL
        )
        assert _derive().client_order_id == digest == built.client_order_id

    def test_a_restarted_router_derives_the_same_key(self) -> None:
        # The resubmission scenario itself: the process that retries the
        # order is not the process that first sent it, so the key must be
        # a function of the order alone — proven by deriving it in a
        # second interpreter with none of this process's state.
        program = (
            "from datetime import UTC, datetime\n"
            "from router import client_order_digest\n"
            "print(client_order_digest(book_id='momentum-core', "
            "rebalance_ts=datetime(2026, 9, 25, 12, 0, tzinfo=UTC), "
            "symbol='BTCUSDT'))\n"
        )
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
        completed = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        assert completed.stdout.strip() == PINNED_DIGEST

    def test_the_terms_are_required_keywords(self) -> None:
        # No default of *now*, no positional drift: a caller that cannot
        # state the rebalance's instant has no order to name, and the
        # signature says so before any hash is computed.
        with pytest.raises(TypeError):
            client_order_digest(BOOK, T0, SYMBOL)  # type: ignore[misc]
        with pytest.raises(TypeError):
            derive_client_order_id(BOOK, T0, SYMBOL)  # type: ignore[misc]


class TestCanonicalisation:
    """The near-miss laws — what is normalised, what is refused, what stays.

    Stripped and UTC-folded is only half the discipline: the names are kept
    **verbatim** otherwise, because re-spelling a book or a symbol would
    rename what the deployment configured and what the venue lists.
    """

    def test_a_book_name_is_not_case_folded(self) -> None:
        # The deployment's configuration is the deployment's spelling; two
        # casings are two books, exactly as the rebalance table (feature
        # 309) would record them.
        assert _derive(book="Momentum-Core") != _derive()

    def test_a_symbol_is_not_re_spelled(self) -> None:
        # exchangeInfo lists symbols in the venue's own spelling and the
        # filters are keyed by it; a derivation that re-cased a symbol
        # would name an instrument the order path could not look a filter
        # up for.
        assert _derive(symbol="btcusdt") != _derive()

    def test_the_value_normalises_the_instant_it_carries(self) -> None:
        # Two values for one instant are equal as values, not merely as
        # keys: the record a caller joins on holds the UTC instant.
        summer = T0.astimezone(timezone(timedelta(hours=2)))
        assert _derive(moment=summer).rebalance_ts == T0

    def test_a_blank_book_is_refused(self) -> None:
        with pytest.raises(RouterClientOrderIdError) as raised:
            _derive(book="   ")
        assert str(raised.value).startswith(f"{CLIENT_ORDER_ID_CODE}:")
        assert "book_id" in str(raised.value)
        assert "(feature 316)" in str(raised.value)

    def test_a_non_text_book_is_refused(self) -> None:
        with pytest.raises(RouterClientOrderIdError) as raised:
            _derive(book=42)  # type: ignore[arg-type]
        assert "book_id must be non-empty text" in str(raised.value)
        assert "42" in str(raised.value)

    def test_a_naive_instant_is_refused(self) -> None:
        # A naive timestamp names an offset nobody agreed on; folding one
        # could collide two books' rebalances into one key.
        with pytest.raises(RouterClientOrderIdError) as raised:
            _derive(moment=T0.replace(tzinfo=None))
        assert "timezone-aware" in str(raised.value)

    def test_a_non_datetime_instant_is_refused(self) -> None:
        with pytest.raises(RouterClientOrderIdError) as raised:
            _derive(moment="2026-09-25T12:00:00+00:00")  # type: ignore[arg-type]
        assert "rebalance_ts must be a datetime" in str(raised.value)
        # ...and the ISO *text* is refused rather than parsed, because the
        # term is an instant the caller holds, not a spelling to interpret.
        assert "str" in str(raised.value)

    def test_a_blank_symbol_is_refused(self) -> None:
        with pytest.raises(RouterClientOrderIdError) as raised:
            _derive(symbol="")
        assert "symbol must be non-empty text" in str(raised.value)

    def test_every_refusal_is_the_members_vocabulary(self) -> None:
        # One base class, one grep token: a caller catching RouterError
        # catches every way the ask can be malformed, and an operator
        # grepping the code token finds every refusal this module raises.
        assert issubclass(RouterClientOrderIdError, RouterError)
        assert not issubclass(RouterClientOrderIdError, RouterFilterError)
        assert not issubclass(RouterClientOrderIdError, RouterStoreError)
        assert not issubclass(
            RouterClientOrderIdError, RouterSubmissionHealthError
        )
        assert not issubclass(RouterClientOrderIdError, RouterRateLimitError)
        assert CLIENT_ORDER_ID_CODE
        assert CLIENT_ORDER_ID_CODE == CLIENT_ORDER_ID_CODE.lower()
        assert " " not in CLIENT_ORDER_ID_CODE


class TestTheValue:
    """The sentence's return — the key, with its terms riding beside it."""

    def test_the_terms_ride_beside_the_key(self) -> None:
        # The hash is one-way: a value holding only it can say *that* two
        # submissions differed, never *how*.  The triple is what a caller
        # that must act on a collision needs, so it travels with the key.
        key = _derive()
        assert key.book_id == BOOK
        assert key.rebalance_ts == T0
        assert key.symbol == SYMBOL

    def test_the_value_is_frozen(self) -> None:
        # An identity that could be edited after the fact would let one
        # object stand for two orders — the defect the hash detects.
        with pytest.raises(dataclasses.FrozenInstanceError):
            _derive().symbol = "ETHUSDT"  # type: ignore[misc]

    def test_the_value_is_hashable_and_stands_as_its_own_key(self) -> None:
        # The dedupe map feature 317 builds keys rows by this value; a
        # frozen dataclass over strings and a datetime hashes by its terms.
        first = _derive()
        again = _derive()
        assert hash(first) == hash(again)
        assert len({first, again}) == 1
        assert {first: "prior result"}[again] == "prior result"

    def test_str_is_the_digest(self) -> None:
        # ``f"{key}"`` is the 64 hex characters — the spelling a log line
        # or a venue payload carries, with no reaching through the value.
        key = _derive()
        assert str(key) == key.client_order_id == PINNED_DIGEST

    def test_a_stated_key_that_agrees_is_kept_normalised(self) -> None:
        # A value rebuilt from a row (or pasted from a log, upper-cased by
        # a database's collation) is the value it always was.
        rebuilt = ClientOrderId(
            book_id=BOOK,
            rebalance_ts=T0,
            symbol=SYMBOL,
            client_order_id=PINNED_DIGEST.upper(),
        )
        assert rebuilt == _derive()
        assert rebuilt.client_order_id == PINNED_DIGEST

    def test_a_stated_key_that_disagrees_with_its_terms_is_refused(self) -> None:
        # An identity whose hash contradicts its inputs would persist as a
        # row that lies about which order it names.
        with pytest.raises(RouterClientOrderIdError) as raised:
            ClientOrderId(
                book_id="carry-lean",
                rebalance_ts=T0,
                symbol=SYMBOL,
                client_order_id=PINNED_DIGEST,
            )
        message = str(raised.value)
        assert message.startswith(f"{CLIENT_ORDER_ID_CODE}:")
        # The refusal names both the terms and the expected digest, so the
        # caller can see which order the stated key actually belongs to.
        assert "carry-lean" in message
        assert PINNED_DIGEST in message

    def test_omitting_the_key_computes_it(self) -> None:
        built = ClientOrderId(book_id=BOOK, rebalance_ts=T0, symbol=SYMBOL)
        assert built.client_order_id == PINNED_DIGEST


class TestNormalize:
    """The seam a presented key is read through — 317's front door."""

    def test_a_derived_key_round_trips(self) -> None:
        key = _derive().client_order_id
        assert normalize_client_order_id(key) == key
        # ...and normalizing twice changes nothing, the idempotence of the
        # normalizer itself.
        assert normalize_client_order_id(normalize_client_order_id(key)) == key

    def test_uppercase_hex_is_the_same_key(self) -> None:
        assert normalize_client_order_id(PINNED_DIGEST.upper()) == PINNED_DIGEST

    def test_an_algorithm_prefix_is_refused(self) -> None:
        # ``sha256:<hex>`` is an image-reference spelling; accepting it
        # here would let a caller compare a digest against a key.
        with pytest.raises(RouterClientOrderIdError) as raised:
            normalize_client_order_id(f"sha256:{PINNED_DIGEST}")
        assert "algorithm prefix" in str(raised.value)

    @pytest.mark.parametrize(
        "near_miss",
        [
            PINNED_DIGEST[:-1],  # one short
            PINNED_DIGEST + "0",  # one long
            PINNED_DIGEST[:-1] + "g",  # not hex
            "book-1-1758715200-BTCUSDT",  # a human-readable slug
            "",
        ],
    )
    def test_a_near_miss_key_is_refused(self, near_miss: str) -> None:
        # A value that is *almost* an order's name must not silently miss
        # every row it should have matched — which is what keying a store
        # on an unvalidated string does.
        with pytest.raises(RouterClientOrderIdError):
            normalize_client_order_id(near_miss)

    def test_a_non_text_key_is_refused(self) -> None:
        with pytest.raises(RouterClientOrderIdError) as raised:
            normalize_client_order_id(64)  # type: ignore[arg-type]
        assert "int" in str(raised.value)


class TestTheVerbIsPure:
    """No table, no component, no clock, no I/O — the feature's own shape."""

    def test_deriving_needs_no_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The key is a function of the order, not of a store: a router
        # asked to resubmit derives the identity before anything is
        # opened, so no DATABASE_URL is a non-event.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert _derive().client_order_id == PINNED_DIGEST

    def test_the_module_reads_no_clock(self) -> None:
        # Every moment in the module came from the caller's terms, and a
        # clock read anywhere in the derivation would be a second spelling
        # of the generated name the key exists to replace.  Pinned
        # statically — the same shape the policy-admission checks
        # (features 230/231) use — because the pinned digest above cannot
        # notice a ``now()`` added to a path this suite never walks.
        import ast
        import inspect

        import router.client_order_id as module

        tree = ast.parse(inspect.getsource(module))
        clock_reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now"
        ]
        assert not clock_reads

    def test_the_member_exports_the_feature_316_names(self) -> None:
        for name in (
            "CLIENT_ORDER_ID_CODE",
            "CLIENT_ORDER_ID_LENGTH",
            "ClientOrderId",
            "RouterClientOrderIdError",
            "client_order_digest",
            "derive_client_order_id",
            "normalize_client_order_id",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_member_still_registers_exactly_one_component(self) -> None:
        assert [
            name for name in dir(member) if name.startswith("build_")
        ] == ["build_router_exchange_info_store"]


class TestTheJoin320Documented:
    """The key rides in a submission-health row — for joining, uninterpreted."""

    def test_a_health_observation_carries_the_derived_key(self) -> None:
        # Feature 320's ``client_order_id`` column was documented as "for
        # joining only", waiting on this feature's key: an operator
        # walking a rejection spike back to the order that earned it joins
        # on the value this module returns, spelled exactly once.
        key = _derive()
        observation = SubmissionObservation(
            process_id=process_identity(),
            observed_at=T0 + timedelta(seconds=30),
            outcome=ORDER_SUBMISSION_ACCEPTED,
            symbol=key.symbol,
            client_order_id=str(key),
        )
        assert observation.client_order_id == PINNED_DIGEST
        assert observation.outcome in ORDER_SUBMISSION_OUTCOMES

    def test_the_key_names_the_row_it_joins_to(self) -> None:
        # The join is answerable from the value alone: the symbol on the
        # health row is the symbol in the terms, so the two records agree
        # about which leg of which rebalance they describe.
        key = _derive()
        observation = SubmissionObservation(
            process_id=process_identity(),
            observed_at=T0 + timedelta(seconds=30),
            outcome=ORDER_SUBMISSION_ACCEPTED,
            symbol=key.symbol,
            client_order_id=key.client_order_id,
        )
        assert observation.symbol == key.symbol == SYMBOL
