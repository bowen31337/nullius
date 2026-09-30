"""Feature 3 (BingX VST dry run): the identifier at the venue's own cap.

additions_spec_bingx_dry_run.xml, "BingX VST Dry Run", feature 3: *System
projects the 64-hex client order identifier from feature 316 onto BingX's
40-character clientOrderID as the identifier's first 40 lowercase hex
characters, returning the same projection for the same book_id,
rebalance_ts and symbol and a client_order_id refusal for any value that is
not a 64-hex identifier.*  The tests below are organised around the three
claims of that sentence, because each can be false while the others hold:

* **onto BingX's 40-character clientOrderID as the identifier's first 40
  lowercase hex characters** — the answer is exactly the venue's cap long,
  exactly lowercase hex, and exactly a *prefix* of feature 316's own
  digest, pinned to the byte so that a change to the cap, the slice or the
  derivation's spelling breaks loudly rather than silently re-naming every
  order the dry run would send;
* **the same projection for the same book_id, rebalance_ts and symbol** —
  idempotence inherited from the derivation and asserted for this splice
  of it: two derivations, two spellings of one instant, a restarted
  process, and terms that move the projection the way they move the
  digest;
* **a client_order_id refusal for any value that is not a 64-hex
  identifier** — feature 316's own validator doing the refusing, with this
  feature's own 40-character output the near-miss it must catch first: a
  projection fed back in would project a projection.

No test needs a database and none opens a socket: the projection is a pure
function of the identifier, and Stage 0's own law — nothing in this
addition connects, signs or reads a credential — is pinned at the bottom
of the suite by reading the module's imports.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone

import pytest
from router.bingx_client_order_id import (
    BINGX_CLIENT_ORDER_ID_LENGTH,
    project_bingx_client_order_id,
)
from router.client_order_id import (
    ClientOrderId,
    derive_client_order_id,
)
from router.errors import (
    CLIENT_ORDER_ID_CODE,
    RouterClientOrderIdError,
    RouterError,
)

#: The synthetic book's own identity — the triple the Stage 0 dry run
#: submits for, spelled the way
#: ``fixtures/bingx_vst/synthetic_book.json`` spells it: BingX's hyphenated
#: symbol end to end, nothing mapped to Binance's ``BTCUSDT``.
T0 = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

#: The book the suite projects for — the fixture's own ``book_id``.
BOOK = "synthetic-vst-0"

#: The leg the suite projects — the fixture's first symbol, in the venue's
#: own spelling, the spelling that is a term of the hash.
SYMBOL = "BTC-USDT"

#: The exact projection of ``(BOOK, T0, SYMBOL)``: the first 40 lowercase
#: hex characters of feature 316's identifier for that triple.  Pinned,
#: deliberately, for the same reason the derivation's own suite pins its
#: digest: the slice *is* the format — a change to the cap, to which 40
#: characters are taken, or to the derivation's byte-level spelling must
#: break this test loudly rather than silently re-naming every order the
#: dry run would send under an identifier the venue already saw.
PINNED_PROJECTION = "cd2a5cafc184c765919a0a3e923135ace3e43079"

#: Feature 316's own suite pins this digest for
#: ``("momentum-core", 2026-09-25T12:00:00+00:00, "BTCUSDT")``; quoting it
#: here ties the projection to the *derivation* rather than to a second,
#: independent formula: if feature 316's framing, separators, term order or
#: timestamp spelling ever change, this suite breaks with it instead of
#: silently projecting a different prefix of a different digest.
FEATURE_316_PINNED_DIGEST = (
    "dae4db89859497b1e5de8f70b518266c7704fb95f77b53347a93eac7e5ed633a"
)

_HEX = frozenset("0123456789abcdef")


def _key(
    book: str = BOOK, moment: datetime = T0, symbol: str = SYMBOL
) -> ClientOrderId:
    """The suite's one spelling of the derivation, so no test restates it."""
    return derive_client_order_id(
        book_id=book, rebalance_ts=moment, symbol=symbol
    )


def _project_key(
    book: str = BOOK, moment: datetime = T0, symbol: str = SYMBOL
) -> str:
    """The suite's one spelling of the ask: derive, then project."""
    return project_bingx_client_order_id(_key(book, moment, symbol))


class TestTheProjection:
    """*Onto BingX's 40-character clientOrderID as the identifier's first 40
    lowercase hex characters* — the slice itself."""

    def test_the_venue_cap_is_forty_characters(self) -> None:
        # BingX's own document for POST /openApi/swap/v2/trade/order caps
        # clientOrderID at 40 characters; the constant is that number and
        # nothing this workspace chose for itself.
        assert BINGX_CLIENT_ORDER_ID_LENGTH == 40

    def test_the_answer_is_40_lowercase_hex_characters(self) -> None:
        projected = _project_key()
        assert len(projected) == BINGX_CLIENT_ORDER_ID_LENGTH == 40
        assert set(projected) <= _HEX
        assert projected == projected.lower()

    def test_the_answer_is_the_identifiers_first_40_characters(self) -> None:
        # A prefix, not a suffix and not a re-hash: the venue field carries
        # the beginning of the system's own name for the order, so the two
        # spellings agree character for character as far as the field goes.
        key = _key()
        assert _project_key() == key.client_order_id[:40]
        assert _project_key() == str(key)[:BINGX_CLIENT_ORDER_ID_LENGTH]

    def test_the_projection_is_pinned(self) -> None:
        # The slice is the format: pinned to the byte, for the reason the
        # derivation's own digest is pinned — a silent change would re-name
        # every order the dry run sends.
        assert _project_key() == PINNED_PROJECTION

    def test_the_projection_is_feature_316s_identifier(self) -> None:
        # Quoting feature 316's own pinned triple and digest: the
        # projection is *that* identifier's first 40 characters, not the
        # output of a second formula that could drift from it.
        key = derive_client_order_id(
            book_id="momentum-core",
            rebalance_ts=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
            symbol="BTCUSDT",
        )
        assert key.client_order_id == FEATURE_316_PINNED_DIGEST
        assert project_bingx_client_order_id(key) == (
            FEATURE_316_PINNED_DIGEST[:40]
        )

    def test_the_full_identifier_stays_sixty_four(self) -> None:
        # Projecting folds nothing back: the value's own digest is the
        # whole 64 hex characters it always was, because the system's key
        # (feature 317's idempotency, feature 320's join) is the full
        # identifier and only the venue field carries the prefix.
        key = _key()
        projected = project_bingx_client_order_id(key)
        assert key.client_order_id.startswith(projected)
        assert len(key.client_order_id) == 64

    def test_a_bare_identifier_projects_identically(self) -> None:
        # The projection is a function of the identifier, not of the
        # object carrying it: a key read from a row or pasted from a log
        # line projects to the same 40 characters the derived value gives.
        assert project_bingx_client_order_id(_key().client_order_id) == (
            PINNED_PROJECTION
        )

    def test_an_upper_cased_identifier_is_the_same_projection(self) -> None:
        # A database's collation upper-cases what it stores; the
        # identifier means the same value and projects to the same prefix,
        # lower-cased the way the venue field wants it.
        assert project_bingx_client_order_id(
            _key().client_order_id.upper()
        ) == PINNED_PROJECTION


class TestSameTerms:
    """*The same projection for the same book_id, rebalance_ts and symbol* —
    idempotence, inherited from the derivation and asserted here."""

    def test_the_same_terms_answer_the_same_projection(self) -> None:
        assert _project_key() == _project_key()
        assert project_bingx_client_order_id(_key()) == _project_key()

    def test_two_spellings_of_one_instant_are_one_projection(self) -> None:
        # 00:00+02:00 and 2026-09-30T00:00:00+00:00 are one rebalance; the
        # venue field must not see a second clientOrderID for the order a
        # UTC-holding process already sent.
        summer = T0.astimezone(timezone(timedelta(hours=2)))
        assert _project_key(moment=summer) == PINNED_PROJECTION

    def test_whitespace_around_a_name_changes_nothing(self) -> None:
        # A pasted copy of the deployment's configuration derives the same
        # identifier (feature 316 strips the names), so the projection
        # cannot move either.
        padded = project_bingx_client_order_id(
            _key(book=f"  {BOOK}\n", symbol=f" {SYMBOL} ")
        )
        assert padded == PINNED_PROJECTION

    def test_each_term_moves_the_projection(self) -> None:
        # The prefix keeps the digest's discriminating power: two books
        # holding one symbol at one instant are two orders, a book
        # rebalanced twice places two, and a rebalance's other leg is its
        # own order — each difference must reach the venue field.
        assert _project_key(book="carry-lean") != _project_key()
        assert _project_key(moment=T0 + timedelta(microseconds=1)) != (
            _project_key()
        )
        assert _project_key(symbol="ETH-USDT") != _project_key()

    def test_no_two_orders_share_a_projection(self) -> None:
        # What a 40-hex prefix inherits from the digest: across a handful
        # of books, rebalances and legs, every projection is its own —
        # all the venue's idempotency name ever needs from it.
        projections = set()
        for book in ("synthetic-vst-0", "carry-lean", "stat-arb"):
            for hours in (0, 6, 12, 18):
                for symbol in ("BTC-USDT", "ETH-USDT"):
                    projections.add(
                        _project_key(
                            book=book,
                            moment=T0 + timedelta(hours=hours),
                            symbol=symbol,
                        )
                    )
        assert len(projections) == 3 * 4 * 2

    def test_a_restarted_router_projects_the_same_value(self) -> None:
        # The resubmission scenario itself: the process that re-sends the
        # order is not the process that first sent it, so the 40 characters
        # the venue sees must be a function of the order alone — proven by
        # projecting in a second interpreter with none of this process's
        # state.
        program = (
            "from datetime import UTC, datetime\n"
            "from router.bingx_client_order_id import "
            "project_bingx_client_order_id\n"
            "from router.client_order_id import derive_client_order_id\n"
            "key = derive_client_order_id(book_id='synthetic-vst-0', "
            "rebalance_ts=datetime(2026, 9, 30, 0, 0, tzinfo=UTC), "
            "symbol='BTC-USDT')\n"
            "print(project_bingx_client_order_id(key))\n"
        )
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
        completed = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        assert completed.stdout.strip() == PINNED_PROJECTION


class TestRefusals:
    """*A client_order_id refusal for any value that is not a 64-hex
    identifier* — feature 316's own validator doing the refusing."""

    def test_a_projection_fed_back_in_is_refused(self) -> None:
        # The near-miss this feature owns outright: its own output.  Forty
        # hex characters are not sixty-four, and accepting one would
        # project a *projection* — a value naming no order any process
        # ever derived — onto the venue's idempotency field.
        with pytest.raises(RouterClientOrderIdError) as raised:
            project_bingx_client_order_id(PINNED_PROJECTION)
        message = str(raised.value)
        assert message.startswith(f"{CLIENT_ORDER_ID_CODE}:")
        # The validator's own words name this shape of near-miss: a
        # truncated key names no order this system derived.
        assert "truncated" in message

    @pytest.mark.parametrize(
        "near_miss",
        [
            FEATURE_316_PINNED_DIGEST[:-1],  # one short
            FEATURE_316_PINNED_DIGEST + "0",  # one long
            FEATURE_316_PINNED_DIGEST[:-1] + "g",  # not hex
            FEATURE_316_PINNED_DIGEST[:40] + "g" * 24,  # right length, wrong alphabet
            "book-1-1758715200-BTC-USDT",  # a human-readable slug
            f"sha256:{FEATURE_316_PINNED_DIGEST}",  # an image reference
            "",
        ],
    )
    def test_a_near_miss_identifier_is_refused(self, near_miss: str) -> None:
        # Whatever is not a 64-hex identifier meets the one refusal, so a
        # value that is *almost* an order's name cannot reach the venue
        # field and quietly collide with — or miss — an order it should
        # have matched.
        with pytest.raises(RouterClientOrderIdError):
            project_bingx_client_order_id(near_miss)

    def test_a_non_text_value_is_refused(self) -> None:
        with pytest.raises(RouterClientOrderIdError) as raised:
            project_bingx_client_order_id(40)  # type: ignore[arg-type]
        assert str(raised.value).startswith(f"{CLIENT_ORDER_ID_CODE}:")
        assert "int" in str(raised.value)

    def test_the_refusal_is_feature_316s_own_validator(self) -> None:
        # Read, not re-implemented: the refusal that answers a bad value
        # is the one :func:`router.client_order_id.normalize_client_order_id`
        # raises — its message carries feature 316's own citation, so the
        # caller is sent to the derivation, not to a second validator that
        # could drift from it.
        with pytest.raises(RouterClientOrderIdError) as raised:
            project_bingx_client_order_id(PINNED_PROJECTION)
        assert "(feature 316)" in str(raised.value)

    def test_every_refusal_is_the_members_vocabulary(self) -> None:
        # The sentence names the ``client_order_id`` refusal, and that is
        # RouterClientOrderIdError — a RouterError, so one ``except``
        # catches every way the ask can be malformed, and one grep token
        # finds every refusal this module lets through.
        assert issubclass(RouterClientOrderIdError, RouterError)
        assert CLIENT_ORDER_ID_CODE == "client_order_id"


class TestPurity:
    """Stage 0's own law — a pure function that sends nothing."""

    def test_the_module_imports_no_network_or_signing_machinery(self) -> None:
        # The addition's constraint is static and pinned statically: the
        # module may not import a connection, a TLS stack, a signer or an
        # HTTP client, because nothing in Stage 0 sends anything.  Pinned
        # on the parsed source — the same shape feature 316's suite uses
        # for its no-clock law — so an import added to a path this suite
        # never walks still fails here.
        import router.bingx_client_order_id as module

        forbidden = {
            "socket",
            "ssl",
            "http",
            "urllib",
            "hmac",
            "ccxt",
            "httpx",
            "requests",
            "aiohttp",
        }
        imported: set[str] = set()
        for node in ast.walk(ast.parse(inspect.getsource(module))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not (imported & forbidden)

    def test_the_module_adds_no_builder_and_no_error_class(self) -> None:
        # The member still registers exactly one component (feature 310's
        # store) and this addition's refusals are the vocabulary
        # router.errors already owns: nothing here to compose, nothing to
        # catch by a new name.
        import router.bingx_client_order_id as module

        assert module.__all__ == [
            "BINGX_CLIENT_ORDER_ID_LENGTH",
            "project_bingx_client_order_id",
        ]
        assert not [name for name in vars(module) if name.startswith("build_")]
        assert not [
            name
            for name, value in vars(module).items()
            if inspect.isclass(value)
            and issubclass(value, Exception)
            and value.__module__ == module.__name__
        ]

    def test_projecting_needs_no_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A pure function of the identifier: no store is opened, consulted
        # or required, so no DATABASE_URL is a non-event — the same shape
        # the derivation's own suite pins for itself.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert _project_key() == PINNED_PROJECTION
