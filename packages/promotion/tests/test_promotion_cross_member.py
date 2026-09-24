"""The cross-member spellings this member restates — pinned as data.

The workspace contract is that **no member imports another**.  Every spelling
that has to be shared is *restated* in the member that needs it, and a suite
like this one is what keeps a restatement honest (``packages/regime/tests/
test_cross_member.py`` and ``packages/discovery/tests/test_cross_member.py``
state the discipline; both demonstrate the in-function import that costs one
test where a sibling is absent rather than the collection of the whole suite).

Feature 291 restates a handful, and they are of two kinds.

**Three are *table names* this member's one ``INSERT`` joins on.**  A
``promotion_registry`` row carries ``node_id`` and ``epoch_id``, and both are
foreign keys — to ``node``, which feature 232's campaign writer creates and the
discovery member spells :data:`discovery.NODE_TABLE`, and to ``epoch_ledger``,
which feature 105's sealing process creates and the ledger member spells
:data:`ledger.EPOCH_LEDGER_TABLE`.  This member spells both itself (in
``promotion.schema``'s ``MIGRATION_ORDER`` and in the two parent probes), so a
sibling that renamed either would leave this member probing a table nobody
writes, or — worse — declaring the *migrations'* own spelling here while
probing a name of its own, which would pass every test in this suite and fail
in production.  The tests below drive the real siblings and pin the names from
the data side.

**The rest are *conventions* the whole workspace shares**, each with a
different reason to be pinned: the ``DATABASE_URL`` spelling (the one ambient
every store reads, so a caller's deployment points every member at one
database or at none), the UUID canonical spelling (a node identity written one
way here and another way by the ledger would be two rows for one hypothesis),
the clock's resolution (the stamp is compared against the decision's, and two
members' clocks that disagreed could invert §13 item 7's inequality), and the
``sqlite:///`` URL convention (``sqlite:///foo.db`` is relative, an absolute
path keeps its leading slash after the triple).

**What is deliberately *not* pinned: any of this member's refusal classes.**
The ledger's ``validated_epoch_id`` and this member's own validator are two
implementations of one idea, and the seam between them is not a shared
exception — it is the *behaviour*, which is what the tests below drive.  A
member that raised another's error type would defeat the caller's ``except``,
which is the trap the workspace states at every seam of this shape; the
positive assertion is that a malformed epoch is refused in *this* member's
vocabulary whatever sibling sits beside it.

**Why the imports are inside the tests.**  A module-scope ``import ledger``
would make this member's suite fail to collect wherever the sibling is absent,
which is the outcome the remedy exists to avoid.  Inside a function the
absence costs one test, and that test says exactly what is missing.  The
``pytest.importorskip`` is that stance spelled for the path bootstrap — these
tests need the sibling's ``src/`` on ``sys.path``, which the workspace's member
suites do not otherwise do for each other.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from conftest import DEFAULT_CRITERIA_DOCUMENT, EPOCH_ID, NODE_ID, code_of
from promotion import (
    DATABASE_URL_ENV,
    MIGRATION_ORDER,
    PROMOTION_REGISTRY_TABLE,
    PreRegistrations,
    PromotionCriteria,
    PromotionError,
    criteria_hash,
    utc_now,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES = REPO_ROOT / "packages"

#: The two tables this member's ``INSERT`` joins to, in the spelling this
#: member uses — asserted below against the members that own each name rather
#: than against a literal restated twice in this file.
NODE_TABLE = "node"
EPOCH_LEDGER_TABLE = "epoch_ledger"


def _sibling(member: str):
    """A sibling member's package, imported in-function.

    ``importorskip`` rather than a bare import, and the path insert is the
    same bootstrap every member suite performs for *itself* applied to a
    sibling: the workspace's members are not installed into each other's
    environments, the acceptance gate does not put them there either, and a
    workspace that does not carry the sibling should lose this one test.
    """
    src = PACKAGES / member / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return pytest.importorskip(
        member.replace("-", "_"), reason=f"the {member} member is not in this workspace"
    )


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for a raw read."""
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


# -- The two table names the foreign keys point at ---------------------------------


class TestTheParentsAreNamedWhatTheirOwnersCallThem:
    """``node`` and ``epoch_ledger``, each pinned against its owner."""

    def test_the_node_table_is_the_discovery_members(self) -> None:
        # Feature 232's campaign writer is ``node``'s creator, and the member
        # spells it.  A rename on either side would leave this member's probe
        # reading a table no writer fills — so the refusal that is supposed to
        # name an absent node would name a node the campaign loop cannot
        # create.
        discovery = _sibling("discovery")
        assert discovery.NODE_TABLE == NODE_TABLE
        # ...and the name this member bootstraps from is that same spelling,
        # not a private one that happens to sit beside it in the order table.
        assert MIGRATION_ORDER[0][0] == NODE_TABLE

    def test_the_epoch_ledger_is_the_ledger_members(self) -> None:
        # Feature 105's sealing process creates ``epoch_ledger``; the ledger
        # member is where a reader learns the name.  The hazard is the same
        # one, and it is the worse of the two: the epoch is the depleting
        # resource (prd §13 item 4), and a registration that booked an epoch
        # held in a table nobody counts would spend it twice.
        ledger = _sibling("ledger")
        assert ledger.EPOCH_LEDGER_TABLE == EPOCH_LEDGER_TABLE
        assert MIGRATION_ORDER[1][0] == EPOCH_LEDGER_TABLE

    def test_the_registry_table_is_the_specs_own_name(self) -> None:
        # The third name is this member's table and not an owner's — but it is
        # named by ``app_spec.xml``'s schema block, so its owner is the spec,
        # and the assertion is that this member spells it as the spec does
        # rather than tucked inside a format string somewhere.
        from promotion import schema as schema_module

        assert PROMOTION_REGISTRY_TABLE == "promotion_registry"
        assert PROMOTION_REGISTRY_TABLE in code_of(schema_module)
        assert MIGRATION_ORDER[-1][0] == PROMOTION_REGISTRY_TABLE

    def test_the_two_parent_probes_name_the_tables_the_migrations_declare(
        self, database_url: str
    ) -> None:
        # The names driven rather than quoted: bring the database up through
        # the store, then ask ``sqlite_master`` which tables exist.  A probe
        # written against a name the migrations do not declare fails here,
        # on a real database, instead of at an operator's first attempt to
        # pre-register against production.
        PreRegistrations(database_url)._connect().close()
        with closing(sqlite3.connect(_path_of(database_url))) as connection:
            names = {
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert {NODE_TABLE, EPOCH_LEDGER_TABLE, PROMOTION_REGISTRY_TABLE} <= names


# -- The conventions -----------------------------------------------------------------


class TestTheDatabaseUrlIsTheWorkspacesOne:
    """``DATABASE_URL``, spelled once per member and one spelling in fact."""

    def test_every_store_reads_the_same_variable(self) -> None:
        # The ambient a deployment sets.  Members restate the *string*
        # rather than importing it — that is the contract — so the test is
        # that the restatements agree, across the three stores this feature's
        # path can meet: the ledger's, the regime coverage ledger's and this
        # one's.
        ledger = _sibling("ledger")
        regime = _sibling("regime")
        assert DATABASE_URL_ENV == "DATABASE_URL"
        assert ledger.DATABASE_URL_ENV == DATABASE_URL_ENV
        assert regime.DATABASE_URL_ENV == DATABASE_URL_ENV


class TestTheUuidSpellingIsCanonical:
    """One hypothesis, one identity — whichever member writes it down."""

    def test_an_identity_canonicalises_the_way_the_ledger_canonicalises_it(
        self, database_url: str, seeded_database: PreRegistrations
    ) -> None:
        # The ledger's record layer and this member's both hold ``node_id``
        # to one spelling, hyphenated lowercase, because a registration
        # written in another case would name a node the ledger's rows cannot
        # be joined to.  Driven through *both* members' real seams rather
        # than by restating the rule: the ledger's own validator is imported
        # (the contract forbids the module doing it, not a test observing the
        # agreement) and the two answers are compared.
        record = _sibling("ledger").record
        loud = NODE_ID.upper().replace("-", "")
        theirs = record._validated_uuid(loud, "node_id")
        assert theirs == NODE_ID
        # ...and this member writes that same spelling to the table.
        from promotion import PreRegisterEndpoint, PreRegistrationRequest

        PreRegisterEndpoint(seeded_database).post(
            PreRegistrationRequest(
                node_id=loud, epoch_id=EPOCH_ID, criteria=DEFAULT_CRITERIA_DOCUMENT
            )
        )
        with closing(sqlite3.connect(_path_of(database_url))) as connection:
            stored = connection.execute(
                "SELECT node_id FROM promotion_registry"
            ).fetchone()
        assert stored is not None and stored[0] == theirs == NODE_ID

    def test_a_malformed_identity_is_refused_in_this_members_vocabulary(self) -> None:
        # The seam's error rule: the *behaviour* is shared, the class is not.
        # A caller's ``except PromotionError`` must catch a bad node id even
        # though a sibling owns a validator for the same idea.
        from promotion import PreRegistrationRequest

        with pytest.raises(PromotionError):
            PreRegistrationRequest(
                node_id="not-a-uuid", epoch_id=EPOCH_ID, criteria=DEFAULT_CRITERIA_DOCUMENT
            )


class TestTheClockIsTheWorkspacesClock:
    """Second-resolution aware UTC, the stamp the ledger's clock mints."""

    def test_the_two_clocks_agree_on_resolution_and_awareness(self) -> None:
        # §13 item 7's inequality is between this member's stamp and the
        # decision's, so two clocks that disagreed on sub-second precision
        # could invert the ordering for two events in the same second.  The
        # ledger's ``utc_now`` is the member that established the convention;
        # both are driven and compared field by field rather than read.
        ledger_now = _sibling("ledger").utc_now
        for stamp in (utc_now(), ledger_now()):
            assert stamp.tzinfo is not None
            assert stamp.utcoffset() is not None
            assert stamp.utcoffset().total_seconds() == 0
            assert stamp.microsecond == 0


class TestTheSqliteUrlConvention:
    """``sqlite:///relative.db``, absolute keeps its slash — one convention."""

    def test_the_two_stores_read_one_url_to_one_path(
        self, database_url: str
    ) -> None:
        # The workspace's URL grammar, pinned by driving both translations on
        # the same URL: a convention is only shared if the two members that
        # follow it land on the same file.  A divergence here is the quietest
        # failure in this member — two members, one deployment, two databases.
        ledger_store = _sibling("ledger").store
        from promotion.pre_register import _sqlite_path

        assert ledger_store._sqlite_path(database_url) == _sqlite_path(database_url)
        assert _path_of(database_url) == _sqlite_path(database_url)

    def test_a_scheme_this_member_cannot_speak_is_refused_in_its_own_words(
        self,
    ) -> None:
        # The same seam rule as the identity above: the ledger refuses
        # ``postgresql://`` with ``TrialStoreError`` and this member with
        # ``PromotionStoreError``, and neither caller's ``except`` is
        # defeated by the other's class.
        from promotion import PromotionStoreError
        from promotion.pre_register import _sqlite_path

        ledger_store = _sibling("ledger").store
        with pytest.raises(ledger_store.TrialStoreError):
            ledger_store._sqlite_path("postgresql://host/db")
        with pytest.raises(PromotionStoreError):
            _sqlite_path("postgresql://host/db")


class TestTheDigestIsTheWorkspacesDigest:
    """sha256, lowercase hex, 64 characters — ``CHAR(64)``'s spelling."""

    def test_the_hash_fills_the_column_the_migration_declares(self) -> None:
        # ``0108`` declares ``criteria_hash CHAR(64) NOT NULL``, so the width
        # is not this member's to choose: a digest of another width would be
        # truncated by a strict backend or padded by a lenient one, and either
        # way the stored value would stop being the hash a reader recomputes.
        # The column is read from the migration's own statement rather than
        # restated, so the assertion is against the owner.
        from conftest import MIGRATION_REVISIONS, _load_migration

        statements = " ".join(
            _load_migration(MIGRATION_REVISIONS[-1]).statements("sqlite")
        )
        assert "criteria_hash CHAR(64) NOT NULL" in " ".join(statements.split())
        digest = criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))
        assert len(digest) == 64
        assert digest == digest.lower()
        assert set(digest) <= set("0123456789abcdef")
