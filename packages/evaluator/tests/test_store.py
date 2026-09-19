"""Persistence of ``evaluator_hash`` (app_spec.xml feature 70).

The feature's sentence has two verbs — *computes* and *persists* — and the
formula tests cover the first. These cover the second, and the property that
gives it meaning: the row is **assign-once**.

That property is what the features *depending* on this one actually need.
Feature 71 refuses a comparison between two scores whose ``evaluator_hash``
values differ, and feature 87 stamps the same column on every
``trial_ledger`` row. Both read a stored value and trust it. A store that
let a row be rewritten could keep a hash pointing at one evaluator while the
row described another — and every comparison against it afterwards would be
wrong in the direction the system cannot detect. So the tests below pin the
refusal of a contradictory rewrite as carefully as they pin the happy path.

The suite runs against a per-test SQLite file (see ``conftest``), not
``sqlite://`` — an in-memory database is per-connection, so a row written by
one connection would be invisible to the next and idempotency would pass or
fail depending on pooling rather than on the store.
"""

from __future__ import annotations

import sqlite3

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    OTHER_PINNED_IMAGE,
    PINNED_DIGEST,
    PINNED_IMAGE,
)

from evaluator import (
    DATABASE_URL_ENV,
    IDENTITY_TABLE,
    EvaluatorIdentity,
    EvaluatorIdentityError,
    EvaluatorIdentityStore,
    EvaluatorStoreError,
    evaluator_identity,
    identity_from_row,
)


def _store() -> EvaluatorIdentityStore:
    return EvaluatorIdentityStore.resolve()


def _rows(url: str) -> list[tuple]:
    """Read the table directly, bypassing the store's own reader.

    A test that asserted through ``store.identities()`` would be asking the
    store to check its own work. Reading the raw table is how these tests
    catch a writer that stored a value the reader happens to tolerate.
    """
    path = url.removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        return connection.execute(
            f"SELECT evaluator_hash, image_digest, config_canonical, image_reference "
            f"FROM {IDENTITY_TABLE} ORDER BY evaluator_hash"
        ).fetchall()


# -- The happy path ----------------------------------------------------------


def test_persisting_stores_the_hash_and_both_terms(evaluator_env: dict[str, str]) -> None:
    store = _store()
    identity = evaluator_identity(PINNED_IMAGE, {"purge_periods": 5}, defaults={})
    store.persist(identity)

    (row,) = _rows(evaluator_env[DATABASE_URL_ENV])
    assert row[0] == identity.evaluator_hash
    assert row[1] == PINNED_DIGEST
    # The configuration is stored canonically, so two equal configurations
    # cannot become two different rows.
    assert row[2] == identity.config_canonical
    assert row[3] == PINNED_IMAGE


def test_the_stored_hash_is_the_one_the_formula_computes(
    evaluator_env: dict[str, str],
) -> None:
    store = _store()
    identity = evaluator_identity(PINNED_IMAGE, {"horizons": [1, 5]}, defaults={})
    stored = store.persist(identity)
    assert stored.evaluator_hash == identity.evaluator_hash
    assert store.resolve_hash(identity.evaluator_hash).evaluator_hash == identity.evaluator_hash


def test_re_persisting_the_same_identity_is_a_no_op(
    evaluator_env: dict[str, str],
) -> None:
    # The idempotency the evaluation path relies on: no "have I done this
    # already?" branch at the call site.
    store = _store()
    identity = evaluator_identity(PINNED_IMAGE)
    store.persist(identity)
    store.persist(identity)
    store.persist(identity)
    assert len(_rows(evaluator_env[DATABASE_URL_ENV])) == 1


def test_re_persisting_with_a_different_key_order_is_still_a_no_op(
    evaluator_env: dict[str, str],
) -> None:
    # Not a conflict: two spellings of one configuration are one evaluator.
    # Comparing raw fields rather than canonical forms would make the
    # refusal depend on formatting.
    store = _store()
    store.persist(evaluator_identity(PINNED_IMAGE, {"a": 1, "b": 2}, defaults={}))
    store.persist(evaluator_identity(PINNED_IMAGE, {"b": 2, "a": 1}, defaults={}))
    assert len(_rows(evaluator_env[DATABASE_URL_ENV])) == 1


def test_re_persisting_with_a_different_reference_spelling_is_still_a_no_op(
    evaluator_env: dict[str, str],
) -> None:
    # The reference is deliberately not part of the identity — it is not in
    # the primary key and not folded into the hash.
    store = _store()
    first = evaluator_identity("evaluator@sha256:" + "ab" * 32)
    second = evaluator_identity("ghcr.io/nullius/evaluator@sha256:" + "ab" * 32)
    assert first.evaluator_hash == second.evaluator_hash
    store.persist(first)
    store.persist(second)
    assert len(_rows(evaluator_env[DATABASE_URL_ENV])) == 1


def test_two_different_evaluators_are_two_rows(evaluator_env: dict[str, str]) -> None:
    store = _store()
    store.persist(evaluator_identity(PINNED_IMAGE))
    store.persist(evaluator_identity(OTHER_PINNED_IMAGE))
    assert len(_rows(evaluator_env[DATABASE_URL_ENV])) == 2
    assert len(store.identities()) == 2


# -- Assign-once: the integrity property -------------------------------------


def test_a_contradictory_rewrite_of_the_image_is_refused(
    evaluator_env: dict[str, str],
) -> None:
    # A note on how this state is reached, because it is not obvious and it
    # is the reason the guard exists. The hash is a *pure function* of its
    # two terms, so "same hash, different terms" cannot be produced through
    # this package's own API — an :class:`EvaluatorIdentity` refuses to
    # construct that way (see ``test_identity``). So the only way a stored
    # row can contradict itself is an edit *outside* this package, which is
    # exactly the tamper the assign-once rule exists to catch: the row is
    # edited to name a different image, and the next legitimate persist of
    # the real evaluator finds the row already occupied by terms that are
    # not its own.
    store = _store()
    identity = evaluator_identity(PINNED_IMAGE)
    store.persist(identity)

    path = evaluator_env[DATABASE_URL_ENV].removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE {IDENTITY_TABLE} SET image_digest = ? WHERE evaluator_hash = ?",
            ("sha256:" + "ef" * 32, identity.evaluator_hash),
        )

    # The rewrite is caught when the row is read back, so the caller learns
    # the table does not hold what it believes it just recorded rather than
    # being told the write succeeded.
    with pytest.raises(EvaluatorStoreError, match="does not describe"):
        store.persist(identity)


def test_a_contradictory_rewrite_of_the_configuration_is_refused(
    evaluator_env: dict[str, str],
) -> None:
    store = _store()
    identity = evaluator_identity(PINNED_IMAGE, {"purge_periods": 20}, defaults={})
    store.persist(identity)

    path = evaluator_env[DATABASE_URL_ENV].removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE {IDENTITY_TABLE} SET config_canonical = ? WHERE evaluator_hash = ?",
            ('{"purge_periods":999}', identity.evaluator_hash),
        )

    with pytest.raises(EvaluatorStoreError, match="does not describe"):
        store.persist(identity)


def test_the_record_refuses_to_be_built_into_a_contradiction() -> None:
    # The first line of defence, and the reason the store's guard is only
    # reachable through an outside edit: an identity whose hash disagrees
    # with its own terms cannot be constructed in the first place.
    identity = evaluator_identity(PINNED_IMAGE)
    with pytest.raises(EvaluatorIdentityError, match="does not match"):
        EvaluatorIdentity(
            image_digest="sha256:" + "ef" * 32,
            config=identity.config,
            evaluator_hash=identity.evaluator_hash,
        )


def test_a_tampered_row_fails_to_load_rather_than_loading_as_a_lie(
    evaluator_env: dict[str, str],
) -> None:
    # The read path goes through the record type, and the record refuses a
    # hash that disagrees with its own terms. So a row edited directly in
    # the database — the digest swapped while the hash was left alone —
    # cannot be laundered through this store.
    store = _store()
    identity = evaluator_identity(PINNED_IMAGE)
    store.persist(identity)

    path = evaluator_env[DATABASE_URL_ENV].removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE {IDENTITY_TABLE} SET image_digest = ? WHERE evaluator_hash = ?",
            ("sha256:" + "ef" * 32, identity.evaluator_hash),
        )

    with pytest.raises(EvaluatorStoreError, match="does not describe"):
        store.resolve_hash(identity.evaluator_hash)


def test_a_non_canonical_stored_configuration_is_a_store_error(
    evaluator_env: dict[str, str],
) -> None:
    store = _store()
    identity = evaluator_identity(PINNED_IMAGE)
    store.persist(identity)

    path = evaluator_env[DATABASE_URL_ENV].removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE {IDENTITY_TABLE} SET config_canonical = ? WHERE evaluator_hash = ?",
            ("{not json", identity.evaluator_hash),
        )

    with pytest.raises(EvaluatorStoreError, match="not valid JSON"):
        store.resolve_hash(identity.evaluator_hash)


def test_identity_from_row_round_trips() -> None:
    identity = evaluator_identity(PINNED_IMAGE, {"purge_periods": 9}, defaults={})
    row = (
        identity.evaluator_hash,
        identity.image_digest,
        identity.config_canonical,
        identity.image_reference,
    )
    restored = identity_from_row(row)
    assert restored.evaluator_hash == identity.evaluator_hash
    assert restored.image_digest == identity.image_digest
    assert restored.config_canonical == identity.config_canonical


# -- Reading -----------------------------------------------------------------


def test_resolve_hash_returns_none_for_an_unpersisted_hash() -> None:
    # A discoverable absent state, not an exception — the same stance the
    # factory takes toward an absent component.
    store = _store()
    assert store.resolve_hash("ab" * 32) is None


def test_resolve_hash_refuses_a_malformed_key() -> None:
    # A malformed key would silently answer None for a row that exists.
    store = _store()
    with pytest.raises(EvaluatorIdentityError):
        store.resolve_hash("nope")


def test_identities_is_ordered_by_a_stored_column() -> None:
    # Ordered by data, not by insertion, so two readers agree without either
    # depending on rowid.
    store = _store()
    store.persist(evaluator_identity(OTHER_PINNED_IMAGE))
    store.persist(evaluator_identity(PINNED_IMAGE))
    digests = [identity.image_digest for identity in store.identities()]
    assert digests == sorted(digests)


# -- The store's own contract ------------------------------------------------


def test_an_unconfigured_store_is_refused_rather_than_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Unlike the snapshot member — where the sealed directory remains a
    # complete record without its row — there is nothing beside the row
    # here. Feature 70 says "persists"; a service reporting success for a
    # write it did not perform would be worse than one that refused.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(EvaluatorStoreError, match="DATABASE_URL is not set"):
        EvaluatorIdentityStore.resolve()


def test_an_empty_database_url_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    with pytest.raises(EvaluatorStoreError, match="not set"):
        EvaluatorIdentityStore.resolve()


def test_a_non_sqlite_scheme_is_refused(
    monkeypatch: pytest.MonkeyPatch, evaluator_env: dict[str, str]
) -> None:
    store = EvaluatorIdentityStore("postgresql://localhost/nullius")
    identity = evaluator_identity(PINNED_IMAGE)
    with pytest.raises(EvaluatorStoreError, match="unsupported"):
        store.persist(identity)


def test_construction_performs_no_io(tmp_path) -> None:
    # Composition-time work must not touch the disk: the factory builds this
    # component on every create_app(), in any environment.
    target = tmp_path / "never-created" / "evaluator.db"
    EvaluatorIdentityStore(f"sqlite:///{target}")
    assert not target.parent.exists()
