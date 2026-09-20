"""Feature 141, the store, through the composed application.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 141: *System
persists a frozen canary policy together with a frozen canary tree as the
determinism reference pair.*  :mod:`canary._reference_store` is the store in
isolation; this suite pins the store the way a deployment actually reaches it —
composed by the application factory from the member's ``@register`` builder, and
reached from the ``app`` package namespace through its seat.

A member that froze a pair correctly against a bare store while the composed
application carried no store at all would satisfy every store test and none of
these. The claims here are the composition contract:

* the factory composes a reference store for a deployment that names a
  ``DATABASE_URL`` — the path an assembled nightly runner takes;
* the store it composes is the same store the seat exposes, and it points at the
  deployment's ``DATABASE_URL``;
* the composed store freezes and reads back a pair against the deployment's
  database — the whole of feature 141, end to end, through the application;
* a deployment without a ``DATABASE_URL`` composes no store — degrade, don't
  break — while every other component still composes;
* composing the store creates no database file, because the store resolves its
  path lazily and construction must not touch the disk.

The store is pinned by class name and by behaviour, not by ``isinstance`` across
the two copies the loader makes — the loader imports this member under a
synthetic module name (``_nullius_scanned_canary``), so a ``CanaryReferenceStore``
composed by the factory is a distinct class object from the one this suite also
imports as ``canary.CanaryReferenceStore``. ``isinstance`` across the copies
cannot hold; the composed store is pinned by what it does.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

import pytest

from app.module_loader import create_app

REFERENCE_STORE_COMPONENT_NAME = "canary-reference-store"
POLICY_VERSION = "composed-v1"


def _pair(composed_store) -> object:
    """A frozen reference pair built from the composed store's own copy.

    The loader imports this member under a synthetic module name
    (``_nullius_scanned_canary``), so a ``CanaryReferencePair`` from the
    ``canary`` package this suite also imports is a distinct class object from
    the one the composed store's ``freeze`` checks ``isinstance`` against — and
    ``isinstance`` across the two copies cannot hold. The pair must therefore be
    built from the composed store's own module, the same copy that composed it.
    """
    store_module = import_module(type(composed_store).__module__)
    policy = store_module.CanaryPolicy.freeze(
        version=POLICY_VERSION,
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}},
    )
    tree = store_module.CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root"}),
            "leaf": ("root", 1, {"label": "leaf"}),
        }
    )
    return store_module.CanaryReferencePair(
        policy=policy,
        tree=tree,
        recorded_score=None,
        id=None,
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def composed_store(test_database_url: str):
    """The reference store the *composed application* carries for this environment.

    Read out of the application the factory builds — not constructed directly —
    because the claim under test is about the assembled system: a deployment sets
    ``DATABASE_URL`` and the composed application must carry a usable store
    pointed at it. The root conftest points that variable at a per-test SQLite
    file, so every test here is isolated.
    """
    return create_app().get(REFERENCE_STORE_COMPONENT_NAME)


class TestTheComposedSystemCarriesTheStore:
    def test_the_factory_composes_a_store_for_the_environment(
        self, composed_store, test_database_url: str
    ) -> None:
        # The store the factory composed is pointed at the deployment's database.
        assert composed_store is not None
        assert composed_store.database_url == test_database_url

    def test_the_app_namespace_seat_reaches_the_same_component(
        self, composed_store, test_database_url: str
    ) -> None:
        # The seat is how the rest of this category's features reach the store,
        # so it must resolve to the component the factory composed.
        from app.modules.canary.reference_store import (
            COMPONENT_NAME as SEAT_NAME,
        )
        from app.modules.canary.reference_store import reference_store_component

        assert SEAT_NAME == REFERENCE_STORE_COMPONENT_NAME
        seat = reference_store_component()
        assert seat is not None
        assert seat.database_url == composed_store.database_url

    def test_an_unconfigured_deployment_composes_no_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Degrade, don't break: an absent relational store is a discoverable
        # state, and this member's unset variable must not take composition down
        # for every other feature in the workspace.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        app = create_app()
        assert app.get(REFERENCE_STORE_COMPONENT_NAME) is None
        assert len(app.order) > 5  # ...and the rest of the workspace is there

    def test_composing_the_store_creates_no_database_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Construction resolves nothing: the factory builds every registered
        # component on every create_app(), and a store that opened a connection
        # at construction would create — and lock — a file in the path of every
        # process that merely composed the app.
        path = tmp_path / "never-created.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
        app = create_app()
        assert app.get(REFERENCE_STORE_COMPONENT_NAME) is not None
        assert not path.exists()


class TestTheReferencePairIsPersistedThroughTheAssembledSystem:
    def test_the_composed_store_freezes_and_reads_back_a_pair(
        self, composed_store
    ) -> None:
        # The whole of feature 141, end to end, through the application: the
        # composed store freezes the policy and tree together, and reads the same
        # pair back — the bytes the nightly replay (feature 142) will replay.
        frozen = _pair(composed_store)
        record = composed_store.freeze(frozen)
        loaded = composed_store.load(record.reference_id)
        assert loaded.pair.has_same_content_as(frozen)
        assert loaded.pair.policy.code_hash == frozen.policy.code_hash
        assert loaded.pair.tree.tree_hash == frozen.tree.tree_hash

    def test_the_one_shot_helpers_freeze_and_read_back_a_pair(
        self, test_database_url: str
    ) -> None:
        # ``freeze_reference_pair`` / ``load_reference_pair`` are the composition
        # spelling of the same store, pointed at the deployment's database.
        store = create_app().get(REFERENCE_STORE_COMPONENT_NAME)
        store_module = import_module(type(store).__module__)
        record = store_module.freeze_reference_pair(test_database_url, _pair(store))
        loaded = store_module.load_reference_pair(test_database_url, record.reference_id)
        assert loaded.pair.has_same_content_as(_pair(store))

    def test_a_frozen_pair_is_addressable_across_the_composed_store(
        self, composed_store
    ) -> None:
        # The pair is keyed by a minted UUID; a second read by that id returns
        # the same reference, so a nightly runner that froze the pair tonight can
        # read it back tomorrow.
        record = composed_store.freeze(_pair(composed_store))
        again = composed_store.load(record.reference_id)
        assert again.reference_id == record.reference_id
        assert uuid.UUID(again.reference_id)
