"""Feature 143, the halt, through the composed application.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 143: *System
halts dreaming when the canary score differs from the recorded constant by more
than 1e-12, which emits a determinism_broken alert.*  :mod:`canary._halt` is
the decision in isolation; this suite pins it the way a deployment actually
reaches it — composed by the application factory from the member's
``@register`` builder, and reached from the ``app`` package namespace through
its seat.

A member that halted dreaming correctly against a bare store while the
composed application carried no halt store at all would satisfy every halt
test and none of these.  The claims here are the composition contract:

* the factory composes a halt store for a deployment that names a
  ``DATABASE_URL`` — the store the nightly runner's halt is written to;
* the store it composes is the same store the seat exposes, and it points at
  the deployment's ``DATABASE_URL``;
* the whole of feature 143, end to end, through the composed store: the
  nightly replay breaks against the recorded constant, dreaming is halted
  (the row is on record), the alert is raised carrying the record, and the
  guard refuses a dreaming attempt afterwards;
* a deployment without a ``DATABASE_URL`` composes no halt store — degrade,
  don't break — while every other component still composes;
* composing the store creates no database file, because the store resolves
  its path lazily and construction must not touch the disk.

The store is pinned by class name and by behaviour, not by ``isinstance``
across the two copies the loader makes — the loader imports this member under
a synthetic module name (``_nullius_scanned_canary``), so a
``CanaryHaltStore`` composed by the factory is a distinct class object from
the one this suite also imports as ``canary.CanaryHaltStore``.  The pair and
the replay result are built from the composed store's own copy for the same
reason: ``halt`` checks ``isinstance`` against its own copy's
``CanaryReferencePair`` and ``CanaryReplayResult``.  The store's class lives
in that copy's ``._halt`` submodule, which does not carry every name the
tests need, so the helper below resolves the *package root* of the copy —
where the member's ``__init__`` exports the whole surface — rather than the
submodule the class object names.
"""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

import pytest

from app.module_loader import create_app

HALT_COMPONENT_NAME = "canary-dream-halt"
POLICY_VERSION = "composed-v1"

#: The score the fixture tree replays to — ``test_replay`` and ``test_halt``
#: spell the same expectation — with the root contributing ``0.0``.
EXPECTED_SCORE = 0.8 * 0.3 + 0.6 * 0.7


def _member_package(composed_store) -> object:
    """The composed store's own copy of the member, as a package module.

    The store's class lives in the ``._halt`` submodule of the synthetic copy
    the loader imported it under, so the class's ``__module__`` names the
    submodule — which imports only what ``_halt`` itself needs.  The package
    root of that copy exports the member's whole surface (``CanaryPolicy``,
    ``CanaryTree``, ``CanaryReferencePair``, ``replay_pair``,
    ``halt_dreaming``, the alert type), and every value the tests build or
    catch must come from there, the same copy that composed the store.
    """
    halt_submodule = import_module(type(composed_store).__module__)
    return import_module(halt_submodule.__package__)


def _broken_pair(composed_store) -> object:
    """A broken reference pair built from the composed store's own copy.

    The loader imports this member under a synthetic module name
    (``_nullius_scanned_canary``), so a ``CanaryReferencePair`` from the
    ``canary`` package this suite also imports is a distinct class object from
    the one the composed store's ``halt`` checks ``isinstance`` against — and
    ``isinstance`` across the two copies cannot hold.  The pair and its replay
    must therefore be built from the composed store's own copy, the same
    copy that composed it.
    """
    store_module = _member_package(composed_store)
    policy = store_module.CanaryPolicy.freeze(
        version=POLICY_VERSION,
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}},
    )
    tree = store_module.CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
            "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
            "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
        }
    )
    # The fixture tree replays to EXPECTED_SCORE; the recorded constant is half
    # a unit away, a deviation §12's 1e-12 cannot forgive.
    return store_module.CanaryReferencePair(
        policy=policy,
        tree=tree,
        recorded_score=EXPECTED_SCORE + 0.5,
        id=None,
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def composed_store(test_database_url: str):
    """The halt store the *composed application* carries for this environment.

    Read out of the application the factory builds — not constructed directly
    — because the claim under test is about the assembled system: a deployment
    sets ``DATABASE_URL`` and the composed application must carry a usable
    halt store pointed at it, the one the nightly runner's break lands in.
    """
    return create_app().get(HALT_COMPONENT_NAME)


class TestTheComposedSystemCarriesTheHaltStore:
    def test_the_factory_composes_a_halt_store_for_the_environment(
        self, composed_store, test_database_url: str
    ) -> None:
        assert composed_store is not None
        assert composed_store.database_url == test_database_url

    def test_the_app_namespace_seat_reaches_the_same_component(
        self, composed_store, test_database_url: str
    ) -> None:
        # The seat is how the dreaming entrypoint reaches the halt state, so
        # it must resolve to the component the factory composed.
        from app.modules.canary.halt import COMPONENT_NAME as SEAT_NAME
        from app.modules.canary.halt import halt_store_component

        assert SEAT_NAME == HALT_COMPONENT_NAME
        seat = halt_store_component()
        assert seat is not None
        assert seat.database_url == composed_store.database_url

    def test_an_unconfigured_deployment_composes_no_halt_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Degrade, don't break: an absent relational store is a discoverable
        # state, and this member's unset variable must not take composition
        # down for every other feature in the workspace.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        app = create_app()
        assert app.get(HALT_COMPONENT_NAME) is None
        assert len(app.order) > 5  # ...and the rest of the workspace is there

    def test_composing_the_store_creates_no_database_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Construction resolves nothing: the factory builds every registered
        # component on every create_app(), and a store that opened a
        # connection at construction would create — and lock — a file in the
        # path of every process that merely composed the app.
        path = tmp_path / "never-created.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
        app = create_app()
        assert app.get(HALT_COMPONENT_NAME) is not None
        assert not path.exists()

    def test_the_reference_store_and_the_halt_store_are_separate_components(
        self, test_database_url: str
    ) -> None:
        # Three names, three components: a deployment configured with a
        # relational store composes the frozen pair's home and the halt's home
        # independently, and neither answers to the other's name.
        app = create_app()
        assert app.get("canary-reference-store") is not app.get(HALT_COMPONENT_NAME)


class TestTheHaltThroughTheAssembledSystem:
    def test_a_break_persists_and_alerts_through_the_composed_store(
        self, composed_store
    ) -> None:
        # The whole of feature 143, end to end, through the application: the
        # replay breaks against the recorded constant, the halt is written to
        # the store the factory composed, and the alert is raised carrying the
        # record.
        store_module = _member_package(composed_store)
        pair = _broken_pair(composed_store)
        result = store_module.replay_pair(pair)
        assert result.broken
        with pytest.raises(store_module.CanaryDeterminismBrokenError) as caught:
            store_module.halt_dreaming(pair, result)
        halt = caught.value.halt
        assert halt.code_hash == pair.policy.code_hash
        assert composed_store.halted()

    def test_the_guard_refuses_dreaming_after_the_break(
        self, composed_store
    ) -> None:
        # After the alert, the guard is the door: a caller that reaches for
        # dreaming learns which pair broke, when, and by how much.
        store_module = _member_package(composed_store)
        pair = _broken_pair(composed_store)
        with pytest.raises(store_module.CanaryDeterminismBrokenError):
            store_module.halt_dreaming(pair, store_module.replay_pair(pair))
        with pytest.raises(store_module.CanaryDeterminismBrokenError) as caught:
            composed_store.require_dreaming_allowed()
        assert caught.value.halt.code_hash == pair.policy.code_hash

    def test_a_held_canary_leaves_dreaming_running(self, composed_store) -> None:
        # The untaken branch through the composed store: a pair whose constant
        # the replay reaches writes no halt, raises nothing, and the guard
        # still passes — the nightly green path.
        store_module = _member_package(composed_store)
        pair = _broken_pair(composed_store)
        held = store_module.CanaryReferencePair(
            policy=pair.policy,
            tree=pair.tree,
            recorded_score=EXPECTED_SCORE,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        result = store_module.replay_pair(held)
        assert not result.broken
        assert store_module.halt_dreaming(held, result) is None
        assert not composed_store.halted()
        composed_store.require_dreaming_allowed()
