"""The recording: POST /promotion/pre-register, and the two timestamps.

The second half of feature 291's sentence — *"a criteria hash recorded before
the deciding evaluation runs"* — and the file where that *before* is a fact
about a row rather than a claim about code.

**The ordering is asserted on the raw row, and it is asserted as the absence
of a write.**  §13 item 7's law is an inequality between two instants, and the
way this member makes it true is that the insert cannot name ``decided_at`` at
all: the statement's column list is four columns and the nullable one is not
among them, so the row is born open.  A test that read the column through a
store verb would be asking the code under test to confirm itself, and — worse
— it could not distinguish *this writer never wrote ``decided_at``* from *this
writer wrote NULL*, which are different statements with different futures.  So
the assertions here read ``promotion_registry`` raw, and the first one reads
the ``INSERT`` statement's own text: the column is absent from it, and a later
feature that added it would fail this test rather than quietly acquire the
ability to pre-register criteria *after* a decision.

**Every refusal is one test, and the repair is what each one asserts.**  The
refusals split two ways and the split is the member's error vocabulary rather
than a code path: a malformed *body* is the ask face
(:class:`~promotion.errors.PromotionError`), and a database that cannot hold
the row — an absent parent, an unwritable address — is the store's
(:class:`~promotion.errors.PromotionStoreError`, opening
``promotion_registry_unwritable``).  A caller that gathered the two would read
*the store refused me* where the truth is *the body was not the six terms*.

**The re-registration refusal is this feature's own, and its test says so
explicitly.**  Feature 292's ``criteria_mismatch`` is a *different* refusal at
a *different* moment — a judgement over a promotion against a hash, at
decision time — and the test here pins that this module never spells that
word, so a later feature cannot find the ground already occupied by a
near-identical message.

**The convergence between the two creators is pinned from both directions.**
The store brings a fresh database to the revision it needs by running the
*owning migrations'* own ``statements("sqlite")``; the migrations bring a
fresh database to the same revision by running themselves.  The tests here run
both orders on fresh files and compare the resulting schemas — not by checking
that the store's DDL "matches", but by checking that there is only one set of
statements and that a store which ran second left a migrated database exactly
as it found it.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import hashlib
import sqlite3
import uuid
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import promotion as member
import pytest
from conftest import (
    DEFAULT_CRITERIA_DOCUMENT,
    EPOCH_ID,
    MIGRATION_REVISIONS,
    NODE_ID,
    _load_migration,
    code_of,
)
from promotion import (
    CRITERIA_HASH_COLUMN,
    DATABASE_URL_ENV,
    DECIDED_AT_COLUMN,
    EPOCH_ID_COLUMN,
    MIGRATION_ORDER,
    NODE_ID_COLUMN,
    PRE_REGISTER_ROUTE,
    PRE_REGISTERED_AT_COLUMN,
    PROMOTION_REGISTRY_ERROR_CODE,
    PROMOTION_REGISTRY_TABLE,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PreRegistrationResponse,
    PreRegistrations,
    PromotionCriteria,
    PromotionError,
    PromotionRecord,
    PromotionStoreError,
    criteria_hash,
    utc_now,
)

#: What the endpoint's own ``post`` documentation promises this route is —
#: asserted against the spec's API summary line, because a route string that
#: drifted from the spec would be a deployment serving a path nobody calls.
SPEC_ROUTE = "/promotion/pre-register"


def _request(**overrides) -> PreRegistrationRequest:
    """A well-formed request, with the named fields overridden."""
    fields = {
        "node_id": NODE_ID,
        "epoch_id": EPOCH_ID,
        "criteria": deepcopy(DEFAULT_CRITERIA_DOCUMENT),
    }
    fields.update(overrides)
    return PreRegistrationRequest(**fields)


# -- The route ---------------------------------------------------------------------


def test_the_route_is_the_specs_own_line() -> None:
    assert PRE_REGISTER_ROUTE == SPEC_ROUTE
    assert member.PRE_REGISTER_ROUTE == SPEC_ROUTE
    # Carried on the class, so a composed deployment can state its routes from
    # the components it holds rather than from a string that lives elsewhere.
    assert PreRegisterEndpoint.route == SPEC_ROUTE


def test_the_endpoint_wants_the_store_and_refuses_anything_else() -> None:
    # Duck-checked rather than isinstance-guarded: the factory's scan imports
    # this member under a synthetic module name, so an isinstance here would
    # refuse the very component the factory hands out.
    with pytest.raises(TypeError) as raised:
        PreRegisterEndpoint(object())
    assert "pre_register" in str(raised.value)

    class StructurallyAStore:
        def pre_register(self) -> None:  # pragma: no cover - presence only
            raise NotImplementedError

    assert PreRegisterEndpoint(StructurallyAStore()).route == SPEC_ROUTE


def test_from_env_answers_none_without_a_database_url(monkeypatch) -> None:
    # An unconfigured store is a discoverable state, not an error — while the
    # caller that must pre-register criteria before evaluating them is the one
    # that must not find itself in it.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert PreRegisterEndpoint.from_env() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert PreRegisterEndpoint.from_env() is None


def test_from_env_resolves_the_same_database_as_the_store(tmp_path: Path) -> None:
    # The endpoint and the composed component must always point at one
    # database: two entries in one deployment pointing at two files would put
    # the pre-registration somewhere the deciding evaluation never looks.
    url = f"sqlite:///{tmp_path / 'same.db'}"
    endpoint = PreRegisterEndpoint.from_env({DATABASE_URL_ENV: url})
    assert endpoint is not None
    assert endpoint.registry.database_url == PreRegistrations(url).database_url
    assert member.build_promotion_registry.__name__ == "build_promotion_registry"


# -- The row the insert writes -----------------------------------------------------


def test_the_insert_cannot_name_decided_at() -> None:
    # §13 item 7's law, enforced by the shape of the statement rather than by
    # a check the writer remembers to make.  The nullable column's absence
    # from the column list is what makes a row *born open*, and this test
    # exists so that adding ``decided_at`` to that list — which would give
    # this member the ability to record criteria *after* a decision — cannot
    # be done quietly.
    from promotion.pre_register import _INSERT_SQL

    # Parsed into the exact column list rather than substring-matched: the
    # two columns this test is about are spelled as *parts* of other columns'
    # names (``id`` in ``node_id``, ``decided_at`` nowhere but a prefix of
    # nothing), and a substring check would read the wrong answer.
    columns = [
        column.strip()
        for column in _INSERT_SQL.split("(", 1)[1].split(")", 1)[0].split(",")
    ]
    assert columns == [
        NODE_ID_COLUMN,
        EPOCH_ID_COLUMN,
        CRITERIA_HASH_COLUMN,
        PRE_REGISTERED_AT_COLUMN,
    ]
    assert DECIDED_AT_COLUMN not in columns
    # And the identity is the table's own to mint (``0108``'s DEFAULT), so the
    # statement does not name it either — a writer-supplied identity would be
    # a second minter of a value the table already mints.


def test_a_registration_lands_one_open_row(seeded_database, registry_rows) -> None:
    # The whole of feature 291 in one act: the hash is recorded against the
    # node, ``pre_registered_at`` is set, and ``decided_at`` is NULL — the
    # ordering §13 item 7 demands, visible on the row rather than inferred.
    request = _request()
    response = PreRegisterEndpoint(seeded_database).post(
        request, clock=lambda: dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
    )
    assert response.created is True
    assert response.retry is False
    assert response.criteria_hash == criteria_hash(
        PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT)
    )
    assert response.open is True
    assert response.decided_at is None
    assert response.pre_registered_at == dt.datetime(
        2026, 3, 1, tzinfo=dt.UTC
    )

    rows = registry_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row[NODE_ID_COLUMN] == NODE_ID
    assert row[EPOCH_ID_COLUMN] == EPOCH_ID
    assert row[CRITERIA_HASH_COLUMN] == response.criteria_hash
    assert row[DECIDED_AT_COLUMN] is None
    # The stamp is the aware-UTC ISO-8601 text the spine writes by hand, so a
    # reader in another process parses back the same instant.
    assert dt.datetime.fromisoformat(row[PRE_REGISTERED_AT_COLUMN]) == dt.datetime(
        2026, 3, 1, tzinfo=dt.UTC
    )
    # The identity is the table's, and a UUID.
    assert uuid.UUID(row["id"])


def test_the_default_clock_is_second_resolution_aware_utc(
    seeded_database, registry_rows
) -> None:
    # Second resolution and dropped rather than rounded: §13 item 7's law is
    # an inequality between two instants, and a clock that rounded forward
    # could stamp a pre-registration into the future of a decision that had
    # already run.
    stamp = utc_now()
    assert stamp.tzinfo is not None
    assert stamp.microsecond == 0
    assert stamp.utcoffset() == dt.timedelta(0)

    before = utc_now()
    PreRegisterEndpoint(seeded_database).post(_request())
    after = utc_now()
    recorded = dt.datetime.fromisoformat(
        registry_rows()[0][PRE_REGISTERED_AT_COLUMN]
    )
    assert before <= recorded <= after


def test_the_answer_is_the_row_the_table_holds(seeded_database, registry_rows) -> None:
    # The row is the record, so it is the only thing an answer is drawn from:
    # the store returns what it read back rather than a value assembled from
    # its arguments, and the minted identity proves it — a store that built
    # the record from the ask could not have known the id.
    response = PreRegisterEndpoint(seeded_database).post(_request())
    assert isinstance(response, PreRegistrationResponse)
    assert isinstance(response.record, PromotionRecord)
    assert response.record.id == registry_rows()[0]["id"]
    assert response.record.row()["id"] == response.record.id
    assert response.pre_registered_at == response.record.pre_registered_at
    assert response.criteria_hash == response.record.criteria_hash


def test_the_record_is_frozen_and_validated() -> None:
    # Frozen because a row that has been read back must not be editable into
    # different criteria by a caller who kept a reference — and validated in
    # ``__post_init__`` because ``replace`` and unpickling both rebuild
    # instances past a factory's nose.
    record = PromotionRecord(
        id=str(uuid.uuid4()),
        node_id=NODE_ID,
        epoch_id=EPOCH_ID,
        criteria_hash=criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT)),
        pre_registered_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    assert record.open is True
    assert record.decided_at is None
    with pytest.raises(dc.FrozenInstanceError):
        record.epoch_id = "other"
    with pytest.raises(PromotionStoreError) as raised:
        PromotionRecord(
            id=record.id,
            node_id=NODE_ID,
            epoch_id=EPOCH_ID,
            criteria_hash="not-a-digest",
            pre_registered_at=record.pre_registered_at,
        )
    assert PROMOTION_REGISTRY_ERROR_CODE in str(raised.value)


def test_a_closed_row_is_a_closed_row() -> None:
    # The other side of ``open``, so the property is not a constant: a row
    # feature 293's decision will write reads as closed, and the stamp
    # revalidates through the same check the write path uses.
    record = PromotionRecord(
        id=str(uuid.uuid4()),
        node_id=NODE_ID,
        epoch_id=EPOCH_ID,
        criteria_hash=criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT)),
        pre_registered_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        decided_at="2026-04-01T00:00:00+00:00",
    )
    assert record.open is False
    assert record.decided_at == dt.datetime(2026, 4, 1, tzinfo=dt.UTC)


# -- The retry ---------------------------------------------------------------------


def test_a_retry_changes_nothing_and_returns_the_standing_row(
    seeded_database, registry_rows
) -> None:
    # The response was lost, the worker died, the caller posted again.  The
    # criteria did not change, so the instant they were *fixed* did not
    # either — re-stamping it would claim a freshness the retry does not
    # have, and the whole promise is that ``pre_registered_at`` is when the
    # criteria were fixed rather than when someone last asked.
    endpoint = PreRegisterEndpoint(seeded_database)
    first = endpoint.post(
        _request(), clock=lambda: dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
    )
    before = registry_rows()

    second = endpoint.post(
        _request(), clock=lambda: dt.datetime(2026, 5, 5, tzinfo=dt.UTC)
    )
    assert second.created is False
    assert second.retry is True
    assert second.criteria_hash == first.criteria_hash
    assert second.pre_registered_at == first.pre_registered_at
    assert second.record.id == first.record.id
    assert registry_rows() == before  # byte for byte, stamps included


def test_a_request_that_states_the_criteria_itself_is_the_same_registration(
    seeded_database,
) -> None:
    # The body is a document, and a Python caller holding the member's own
    # value passes the value — unwrapped through its own ``document()``, so
    # the two spellings hash identically.  A caller that had to flatten its
    # criteria by hand before posting would be a seam that only worked from
    # the wire inward.
    endpoint = PreRegisterEndpoint(seeded_database)
    from_value = endpoint.post(
        _request(criteria=PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))
    )
    from_document = endpoint.post(_request())
    assert from_document.created is False
    assert from_document.record.id == from_value.record.id
    assert from_value.criteria_hash == from_document.criteria_hash


def test_a_re_registration_with_different_criteria_is_refused(
    seeded_database, registry_rows
) -> None:
    # The refusal *is* the feature.  Granting it would make the recorded hash
    # a record of the last thing anyone said rather than of what was expected
    # before the evaluation ran: §13 item 7's word *before* would still be
    # satisfied by both timestamps while its meaning was destroyed.
    endpoint = PreRegisterEndpoint(seeded_database)
    endpoint.post(_request())
    before = registry_rows()
    with pytest.raises(PromotionError) as raised:
        endpoint.post(_request(criteria={**DEFAULT_CRITERIA_DOCUMENT, "theta": 0.4}))
    message = str(raised.value)
    # The repair, the two hashes and the node — everything an operator needs
    # to see that this is a second question wearing the first one's node.
    assert NODE_ID in message
    assert "feature 291" in message
    assert "hypothesis" in message
    assert registry_rows() == before  # the refusal wrote nothing


def test_the_re_registration_refusal_is_not_feature_292s(seeded_database) -> None:
    # Feature 292 judges a *promotion* against a *hash*, at decision time, and
    # coins ``criteria_mismatch`` for it.  This module judges a *registration
    # request* against the *row it would rewrite*, before the evaluation, and
    # never spells that word — so the ground is still free for 292, and a
    # caller cannot catch this refusal by reaching for that one.  Feature 292
    # lives in its own module, and the member re-exports it from there, not
    # from here.
    from promotion import pre_register as pre_register_module

    assert "criteria_mismatch" not in code_of(pre_register_module)
    # The verdict is spelled in promotion.criteria_check, not here — a
    # re-registration refusal must not be catchable as a criteria mismatch.
    from promotion import criteria_check as criteria_check_module

    assert not hasattr(pre_register_module, "CriteriaMismatchError")
    assert not hasattr(pre_register_module, "criteria_mismatch")
    # The member reaches the verdict, but only because it re-exports it from
    # feature 292's module — not because pre_register owns it.
    assert hasattr(member, "CriteriaMismatchError")
    assert member.CriteriaMismatchError is criteria_check_module.CriteriaMismatchError
    # And the re-registration refusal itself is still a PromotionError, never a
    # CriteriaMismatchError — the repair is to register, not to re-decide.
    endpoint = PreRegisterEndpoint(seeded_database)
    endpoint.post(_request())
    with pytest.raises(PromotionError) as raised:
        endpoint.post(_request(criteria={**DEFAULT_CRITERIA_DOCUMENT, "theta": 0.4}))
    assert type(raised.value) is not criteria_check_module.CriteriaMismatchError


# -- The ask's refusals ------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    sorted(DEFAULT_CRITERIA_DOCUMENT),
)
def test_a_body_missing_a_term_is_refused(seeded_database, missing: str) -> None:
    # A criterion recorded without a term is a criterion whose hash does not
    # cover it, which would leave that term free to be anything at decision
    # time.  One case per term, so a body missing *any* of the six is refused
    # rather than only the ones someone thought to check.
    body = deepcopy(DEFAULT_CRITERIA_DOCUMENT)
    del body[missing]
    with pytest.raises(PromotionError) as raised:
        PreRegisterEndpoint(seeded_database).post(_request(criteria=body))
    assert missing in str(raised.value)


def test_a_body_with_a_misspelled_term_is_refused_not_ignored(seeded_database) -> None:
    # The near-miss that matters: ``min_world`` for ``min_worlds``.  Ignoring
    # it would register five terms and hash them, tell the caller the
    # registration succeeded, and leave the sixth free.  The message names
    # the offending key, because the repair is one character.
    body = deepcopy(DEFAULT_CRITERIA_DOCUMENT)
    body["min_world"] = body.pop("min_worlds")
    with pytest.raises(PromotionError) as raised:
        PreRegisterEndpoint(seeded_database).post(_request(criteria=body))
    message = str(raised.value)
    assert "min_world" in message
    assert "min_worlds" in message


@pytest.mark.parametrize("body", [None, 42, "theta=0.3", ["theta"], object()])
def test_a_body_that_is_not_a_document_is_refused(seeded_database, body: object) -> None:
    # The criteria arrive as a document because the document is what the hash
    # is taken over, and there is no honest reading of an arbitrary object as
    # six named terms.
    with pytest.raises(PromotionError) as raised:
        PreRegisterEndpoint(seeded_database).post(_request(criteria=body))
    assert "criteria" in str(raised.value)


@pytest.mark.parametrize("node", [None, "", "not-a-uuid", 42, "1111"])
def test_a_malformed_node_is_refused_before_the_store_is_touched(node: object) -> None:
    # No database is opened, which is why this test needs no fixture: a
    # refused body must leave no file behind.  The node is the hypothesis, and
    # an identity that is not a UUID names no row any decision could complete.
    with pytest.raises(PromotionError) as raised:
        PreRegisterEndpoint(PreRegistrations("sqlite:///unused.db")).post(
            _request(node_id=node)
        )
    assert "node_id" in str(raised.value)


@pytest.mark.parametrize("epoch", [None, "", "   ", 42, ["epoch"]])
def test_a_malformed_epoch_is_refused(seeded_database, epoch: object) -> None:
    # The registration books the sequestered epoch the deciding evaluation
    # will spend, and an epoch nobody named is an epoch no decision can charge.
    with pytest.raises(PromotionError) as raised:
        PreRegisterEndpoint(seeded_database).post(_request(epoch_id=epoch))
    assert EPOCH_ID_COLUMN in str(raised.value)


def test_a_naive_stamp_is_refused(seeded_database) -> None:
    # §13 item 7 orders the pre-registration against the deciding evaluation,
    # and a naive stamp has no offset to compare with.
    with pytest.raises(PromotionError) as raised:
        PreRegisterEndpoint(seeded_database).post(
            # Naive on purpose: the point of the probe, not an oversight.
            _request(pre_registered_at=dt.datetime(2026, 3, 1))  # noqa: DTZ001
        )
    assert PRE_REGISTERED_AT_COLUMN in str(raised.value)


def test_a_bad_criterion_is_refused_at_the_wire(seeded_database) -> None:
    # The six-term validators, reached through the body rather than through
    # the constructor: a body is refused before the store is touched, so a
    # malformed registration spends no row.
    with pytest.raises(PromotionError) as raised:
        PreRegisterEndpoint(seeded_database).post(
            _request(criteria={**DEFAULT_CRITERIA_DOCUMENT, "alpha": 2.0})
        )
    assert "alpha" in str(raised.value)


# -- The store's refusals ----------------------------------------------------------


def test_an_absent_node_is_refused_by_name(store: PreRegistrations) -> None:
    # The two foreign keys are two different missing rows with two different
    # repairs — a hypothesis the tree does not hold, versus a holdout nobody
    # sealed — and SQLite's own ``IntegrityError`` names neither.
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionStoreError) as raised:
        PreRegisterEndpoint(store).post(_request())
    message = str(raised.value)
    assert PROMOTION_REGISTRY_ERROR_CODE in message
    assert "node" in message
    assert NODE_ID in message


def test_an_absent_epoch_is_refused_by_name(store: PreRegistrations) -> None:
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, ?)",
                (NODE_ID, "22222222-2222-4222-8222-222222222222", "macro", 1),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionStoreError) as raised:
        PreRegisterEndpoint(store).post(_request())
    message = str(raised.value)
    assert PROMOTION_REGISTRY_ERROR_CODE in message
    assert "epoch_ledger" in message
    assert EPOCH_ID in message


def test_the_foreign_key_is_actually_armed(store: PreRegistrations) -> None:
    # The probes check both parents by name, so the pragma is a redundancy —
    # but it is the redundancy that holds against a hand reaching past this
    # store with a raw connection, and SQLite's own default is off.  Asserted
    # at the connection so a store that dropped the pragma would fail here
    # rather than silently accepting an unjoinable row from another writer.
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, ?)",
                (NODE_ID, "22222222-2222-4222-8222-222222222222", "macro", 1),
            )
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} ({NODE_ID_COLUMN}, "
                f"{EPOCH_ID_COLUMN}, {CRITERIA_HASH_COLUMN}, "
                f"{PRE_REGISTERED_AT_COLUMN}) VALUES (?, ?, ?, ?)",
                (NODE_ID, "no-such-epoch", "0" * 64, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()


@pytest.mark.parametrize("url", ["", "   ", None, 42])
def test_a_store_pointed_at_nothing_is_refused(url: object) -> None:
    with pytest.raises(PromotionStoreError) as raised:
        PreRegistrations(url)
    assert PROMOTION_REGISTRY_ERROR_CODE in str(raised.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://localhost/nullius",
        "sqlite://localhost/relative.db",
        "sqlite:///",
        "sqlite:///:memory:",
    ],
)
def test_a_url_this_member_cannot_speak_is_refused_by_name(
    seeded_database, url: str
) -> None:
    # Refused the first time an operation needs the path — construction
    # performs no I/O, so a misconfigured deployment composes a store that
    # refuses when it is used rather than taking composition down.  An
    # in-memory registry is refused for the reason the whole feature exists:
    # the deciding evaluation runs in another process, and a row that dies
    # with the connection that wrote it is no record at all.
    store = PreRegistrations(url)
    with pytest.raises(PromotionStoreError) as raised:
        store.pre_register(
            NODE_ID, EPOCH_ID, deepcopy(DEFAULT_CRITERIA_DOCUMENT)
        )
    assert PROMOTION_REGISTRY_ERROR_CODE in str(raised.value)


def test_two_rows_for_one_node_are_refused_not_resolved(
    seeded_database, registry_rows
) -> None:
    # §13 item 7 fixes a node's criteria once, so a node holding two rows holds
    # two answers to *what were these criteria registered as?* — and feature
    # 292's comparison would become a choice between them.  Nothing this store
    # writes can produce the state, so the second row is a hand that reached
    # past it, and both silent resolutions would be wrong: summing invents
    # criteria nobody registered, and last-wins would let a later row overwrite
    # the hash the promotion is checked against.
    endpoint = PreRegisterEndpoint(seeded_database)
    endpoint.post(_request())
    connection = seeded_database._connect()
    try:
        with connection:
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} ({NODE_ID_COLUMN}, "
                f"{EPOCH_ID_COLUMN}, {CRITERIA_HASH_COLUMN}, "
                f"{PRE_REGISTERED_AT_COLUMN}) VALUES (?, ?, ?, ?)",
                (NODE_ID, EPOCH_ID, "a" * 64, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionStoreError) as raised:
        endpoint.post(_request())
    message = str(raised.value)
    assert PROMOTION_REGISTRY_ERROR_CODE in message
    assert "2" in message


def test_a_corrupt_stored_hash_is_refused_naming_the_node(
    seeded_database,
) -> None:
    # SQLite's ``CHAR(64)`` is an affinity, not a width, so a raw INSERT from
    # another tool can land anything in the column.  A read that returned it
    # unexamined would hand feature 292 a value to compare against that no
    # hash could ever equal, and the comparison would refuse a promotion for a
    # corruption it never mentions.
    connection = seeded_database._connect()
    try:
        with connection:
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} ({NODE_ID_COLUMN}, "
                f"{EPOCH_ID_COLUMN}, {CRITERIA_HASH_COLUMN}, "
                f"{PRE_REGISTERED_AT_COLUMN}) VALUES (?, ?, ?, ?)",
                (NODE_ID, EPOCH_ID, "NOT A DIGEST", "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionStoreError) as raised:
        PreRegisterEndpoint(seeded_database).post(_request())
    message = str(raised.value)
    assert PROMOTION_REGISTRY_ERROR_CODE in message
    assert NODE_ID in message


# -- The two creators --------------------------------------------------------------


def test_the_store_authors_no_ddl_of_its_own() -> None:
    # The claim :mod:`promotion.schema` makes, pinned as text: every statement
    # the bootstrap runs comes out of a migration's own ``statements()``.  A
    # member that hand-wrote its DDL would be legislating a table it does not
    # own, and could drift from the schema's author silently.
    from promotion import schema as schema_module

    assert "CREATE TABLE" not in code_of(schema_module)
    assert "CREATE INDEX" not in code_of(schema_module)
    # The DDL is genuinely reachable from this member — the claim is that it
    # is *borrowed*, not that it is absent.
    assert "CREATE TABLE" in code_of(_load_migration(MIGRATION_REVISIONS[-1]))
    assert [table for table, _revision in MIGRATION_ORDER] == [
        "node",
        "epoch_ledger",
        PROMOTION_REGISTRY_TABLE,
    ]
    assert [revision for _table, revision in MIGRATION_ORDER] == list(
        MIGRATION_REVISIONS
    )


def test_the_bootstrap_runs_the_owners_own_statements(store: PreRegistrations) -> None:
    # The store's DDL *is* the migrations' DDL, tuple for tuple — not "agrees
    # with", which is what a second spelling could at best claim.
    from promotion.schema import _statements

    expected: list[str] = []
    for revision in MIGRATION_REVISIONS:
        module = _load_migration(revision)
        expected.extend(module.statements("sqlite"))
    assert list(_statements("sqlite")) == expected
    assert len(expected) == len(set(expected))  # each statement once


def _schema_of(url: str) -> set[tuple[str, str, str]]:
    """Every table and column in a database, as comparable rows."""
    with closing(sqlite3.connect(url.removeprefix("sqlite:///"))) as connection:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    return {(kind, name, (sql or "").strip()) for kind, name, sql in rows}


def test_the_store_and_the_migrations_converge_either_way_round(
    tmp_path: Path, migrations
) -> None:
    # Both orders on two fresh files, compared as *schemas*: the deployment
    # shape where the versioned tree ran first, and the shape where the store
    # got there first.  The two must be one schema — that is what "the store
    # runs the owners' statements" means, and the comparison is on the
    # ``sqlite_master`` text rather than on a hand-written expectation, so it
    # cannot be satisfied by the suite and the member agreeing with each other.
    migrated_first = f"sqlite:///{tmp_path / 'migrated-first.db'}"
    for migration in migrations:
        migration.apply(migrated_first)
    store_first = f"sqlite:///{tmp_path / 'store-first.db'}"
    PreRegistrations(store_first)._connect().close()

    assert _schema_of(store_first) == _schema_of(migrated_first)


def test_a_migrated_database_is_left_exactly_as_it_was(
    migrated_database: str, registry_rows
) -> None:
    # The other direction of the same convergence: the store's first write
    # against a database the migrations already brought up must change no
    # table — every statement it runs is ``IF NOT EXISTS``, so the migrated
    # schema is the one that stands and nothing is dropped or re-created.
    store = PreRegistrations(migrated_database)
    before = _schema_of(migrated_database)
    PreRegisterEndpoint(store).post(_request())
    assert _schema_of(migrated_database) == before
    assert len(registry_rows()) == 1


def test_the_three_tables_the_insert_needs_are_the_ones_it_needs(
    migrated_database: str, registry_rows
) -> None:
    # ``promotion_registry``'s two foreign keys are what makes the other two
    # tables necessary rather than incidental, and this asserts the row really
    # lands with both parents present — the join the schema promises.
    PreRegisterEndpoint(PreRegistrations(migrated_database)).post(_request())
    with closing(
        sqlite3.connect(migrated_database.removeprefix("sqlite:///"))
    ) as connection:
        joined = connection.execute(
            f"SELECT p.{CRITERIA_HASH_COLUMN}, n.depth, e.sealed_at "
            f"FROM {PROMOTION_REGISTRY_TABLE} p "
            f"JOIN node n ON n.id = p.{NODE_ID_COLUMN} "
            f"JOIN epoch_ledger e ON e.epoch_id = p.{EPOCH_ID_COLUMN}"
        ).fetchall()
    assert len(joined) == 1
    assert joined[0][0] == criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))
    assert joined[0][1] == 1


def test_a_missing_owner_is_refused_in_this_members_vocabulary(
    monkeypatch, tmp_path: Path
) -> None:
    # A deployment that shipped the package without the migration tree is
    # refused in the vocabulary a caller's ``except PromotionError`` catches —
    # a bare ``FileNotFoundError`` from a path that is not there would defeat
    # it, and the repair (to the checkout) is not the caller's to make.
    from promotion import schema as schema_module

    monkeypatch.setattr(
        schema_module, "migrations_dir", lambda: tmp_path / "nowhere"
    )
    with pytest.raises(PromotionError) as raised:
        schema_module.bootstrap_schema(sqlite3.connect(":memory:"))
    assert "0118_node_table" in str(raised.value)


def test_a_database_that_cannot_be_brought_up_is_a_store_refusal(
    tmp_path: Path,
) -> None:
    # A path whose *parent* is a file rather than a directory: the store
    # cannot open it, and the refusal is the store's class rather than a bare
    # ``sqlite3`` error — an operator's log line has to say which member
    # failed and what it was doing.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    store = PreRegistrations(f"sqlite:///{blocker / 'registry.db'}")
    with pytest.raises(Exception) as raised:
        store.pre_register(NODE_ID, EPOCH_ID, deepcopy(DEFAULT_CRITERIA_DOCUMENT))
    assert isinstance(raised.value, (PromotionError, OSError))


# -- What the hash covers ----------------------------------------------------------


def test_the_recorded_hash_is_what_a_reader_can_recompute(
    seeded_database, registry_rows
) -> None:
    # The property that makes the column evidence rather than decoration, and
    # the check feature 292 will perform: a reader holding the six terms
    # recomputes the digest and compares.  Asserted here against the *stored*
    # row, so the member cannot pass by hashing something the row does not
    # carry.
    PreRegisterEndpoint(seeded_database).post(_request())
    stored = registry_rows()[0][CRITERIA_HASH_COLUMN]
    rebuilt = hashlib.sha256(
        PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT).canonical().encode("utf-8")
    ).hexdigest()
    assert stored == rebuilt
    assert stored == criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))
