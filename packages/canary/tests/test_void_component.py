"""Feature 144, the void marker, through the composed application.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 144: *System
persists a void marker on every score produced after a detected determinism
break, rather than letting bad data age into good data.*  :mod:`canary._void` is
the mechanism in isolation; this suite pins it the way a deployment actually
reaches it — composed by the application factory from the member's
``@register`` builder, and reached from the ``app`` package namespace through
its seat.

A member that voided the affected window correctly against a bare store while
the composed application carried no void-marker store at all would satisfy every
test in ``test_void`` and none of these.  The claims here are the composition
contract:

* the factory composes a void-marker store for a deployment that names a
  ``DATABASE_URL`` — the store the nightly sweep's markers land in;
* the store it composes is the same store the seat exposes, and it points at
  the deployment's ``DATABASE_URL``;
* the whole of feature 144, end to end, through the composed store: the nightly
  canary breaks against the recorded constant (feature 143, through the same
  composed graph), the pool is swept, every score produced after the break is
  marked void, and the guard refuses it afterwards — while a score from before
  the break still passes;
* a deployment without a ``DATABASE_URL`` composes no void-marker store —
  degrade, don't break — while every other component still composes;
* composing the store creates no database file, because the store resolves its
  path lazily and construction must not touch the disk;
* the four stores are four components under four names, and the three older
  seats keep exactly the surfaces they promised.

The store is pinned by class name and by behaviour, not by ``isinstance``
across the two copies the loader makes — the loader imports this member under a
synthetic module name (``_nullius_scanned_canary``), so a
``CanaryVoidMarkerStore`` composed by the factory is a distinct class object
from the one this suite also imports as ``canary.CanaryVoidMarkerStore``.  The
pair and the replay result are built from the composed store's own copy for the
same reason: feature 143's ``halt`` checks ``isinstance`` against *its* copy's
``CanaryReferencePair`` and ``CanaryReplayResult``.  The store's class lives in
that copy's ``._void`` submodule, which does not carry every name the tests
need, so the helper below resolves the *package root* of the copy — where the
member's ``__init__`` exports the whole surface — rather than the submodule the
class object names.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path

import pytest

from app.module_loader import create_app

VOID_COMPONENT_NAME = "canary-void-marker"
HALT_COMPONENT_NAME = "canary-dream-halt"
POLICY_VERSION = "composed-v1"

#: The break's instant — the edge of every window in this suite.
DETECTED_AT = datetime(2025, 6, 1, 3, 0, 0, tzinfo=timezone.utc)
#: A score produced two hours before the break: not in any window.
BEFORE_BREAK = DETECTED_AT - timedelta(hours=2)
#: A score produced one second after the break: the first one voided.
AFTER_BREAK = DETECTED_AT + timedelta(seconds=1)

#: The score the fixture tree replays to — ``test_replay`` and ``test_halt``
#: spell the same expectation — with the root contributing ``0.0``.
EXPECTED_SCORE = 0.8 * 0.3 + 0.6 * 0.7


def _member_package(composed_store) -> object:
    """The composed store's own copy of the member, as a package module.

    The store's class lives in the ``._void`` submodule of the synthetic copy
    the loader imported it under, so the class's ``__module__`` names the
    submodule — which imports only what ``_void`` itself needs.  The package
    root of that copy exports the member's whole surface (``CanaryPolicy``,
    ``CanaryTree``, ``CanaryReferencePair``, ``replay_pair``, ``CanaryError``),
    and every value the tests build or catch must come from there, the same copy
    that composed the store.
    """
    void_submodule = import_module(type(composed_store).__module__)
    return import_module(void_submodule.__package__)


def _broken_pair(composed_store) -> object:
    """A broken reference pair built from the composed store's own copy.

    The loader imports this member under a synthetic module name
    (``_nullius_scanned_canary``), so a ``CanaryReferencePair`` from the
    ``canary`` package this suite also imports is a distinct class object from
    the one the composed halt store's ``halt`` checks ``isinstance`` against —
    and ``isinstance`` across the two copies cannot hold.
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


def _seed_score(
    composed_store, *, produced_at: datetime, score: float = 0.42
) -> str:
    """Insert one ``replay_score`` row through the composed store's schema.

    Seeded after :meth:`ensure_schema`, so the suite writes exactly the pool the
    composed store will read — the shape feature 144 sweeps — rather than a
    table the store merely tolerates.
    """
    composed_store.ensure_schema()
    identity = str(uuid.uuid4())
    with sqlite3.connect(composed_store.path) as connection:
        connection.execute(
            "INSERT INTO replay_score "
            "(id, policy_version, world_id, beta, score, committed_pick, "
            " is_holdout, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity,
                POLICY_VERSION,
                str(uuid.uuid4()),
                0.5,
                score,
                None,
                0,
                produced_at.isoformat(),
            ),
        )
    return identity


@pytest.fixture
def composed_store(test_database_url: str):
    """The void-marker store the *composed application* carries.

    Read out of the application the factory builds — not constructed directly —
    because the claim under test is about the assembled system: a deployment
    sets ``DATABASE_URL`` and the composed application must carry a usable
    void-marker store pointed at it, the one the nightly sweep's markers land
    in.
    """
    return create_app().get(VOID_COMPONENT_NAME)


@pytest.fixture
def composed_halts(test_database_url: str):
    """Feature 143's composed store — where the break that opens the window goes."""
    return create_app().get(HALT_COMPONENT_NAME)


class TestTheComposedSystemCarriesTheVoidMarkerStore:
    def test_the_factory_composes_a_void_marker_store_for_the_environment(
        self, composed_store, test_database_url: str
    ) -> None:
        assert composed_store is not None
        assert composed_store.database_url == test_database_url

    def test_the_app_namespace_seat_reaches_the_same_component(
        self, composed_store, test_database_url: str
    ) -> None:
        # The seat is how a replay or dreaming path reaches the refusal, so it
        # must resolve to the component the factory composed.
        from app.modules.canary.void import COMPONENT_NAME as SEAT_NAME
        from app.modules.canary.void import void_marker_component

        assert SEAT_NAME == VOID_COMPONENT_NAME
        seat = void_marker_component()
        assert seat is not None
        assert seat.database_url == composed_store.database_url

    def test_an_unconfigured_deployment_composes_no_void_marker_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Degrade, don't break: an absent relational store is a discoverable
        # state, and this member's unset variable must not take composition
        # down for every other feature in the workspace.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        app = create_app()
        assert app.get(VOID_COMPONENT_NAME) is None
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
        assert app.get(VOID_COMPONENT_NAME) is not None
        assert not path.exists()

    def test_the_four_stores_are_four_components(self, test_database_url: str) -> None:
        # Four names, four components: a deployment configured with a relational
        # store composes each independently, and none answers to another's name.
        app = create_app()
        components = [
            app.get("canary-reference-store"),
            app.get(HALT_COMPONENT_NAME),
            app.get(VOID_COMPONENT_NAME),
        ]
        assert all(component is not None for component in components)
        assert len({id(component) for component in components}) == 3

    def test_the_void_store_reads_through_the_composed_halt_store(
        self, composed_store, test_database_url: str
    ) -> None:
        # The window's edge is feature 143's fact and is read through feature
        # 143's store — one lifecycle, so "the window opens on the break" is a
        # property of one object graph rather than two readers of one table.
        assert composed_store.halts.database_url == test_database_url


class TestTheVoidingThroughTheAssembledSystem:
    def test_a_break_voids_every_score_produced_after_it(
        self, composed_store, composed_halts
    ) -> None:
        # The whole of feature 144, end to end, through the application: the
        # nightly canary breaks (feature 143), the pool is swept, and every
        # score produced after the break is persisted void.
        store_module = _member_package(composed_store)
        before = _seed_score(composed_store, produced_at=BEFORE_BREAK)
        after_one = _seed_score(composed_store, produced_at=AFTER_BREAK)
        after_two = _seed_score(
            composed_store, produced_at=AFTER_BREAK + timedelta(hours=1)
        )
        pair = _broken_pair(composed_store)
        with pytest.raises(store_module.CanaryDeterminismBrokenError):
            store_module.halt_dreaming(
                pair, store_module.replay_pair(pair), detected_at=DETECTED_AT
            )
        assert composed_halts.halted()
        sweep = composed_store.sweep()
        assert sweep is not None
        assert sweep.refused_score_ids == (after_one, after_two)
        assert [row["id"] for row in composed_store.unvoided_scores()] == [before]

    def test_the_guard_refuses_a_voided_score_through_the_composed_store(
        self, composed_store, composed_halts
    ) -> None:
        # After the sweep, the guard is the door: a replay path that consults it
        # learns which score was voided and by which break.
        store_module = _member_package(composed_store)
        score_id = _seed_score(composed_store, produced_at=AFTER_BREAK)
        pair = _broken_pair(composed_store)
        with pytest.raises(store_module.CanaryDeterminismBrokenError):
            store_module.halt_dreaming(
                pair, store_module.replay_pair(pair), detected_at=DETECTED_AT
            )
        composed_store.sweep()
        with pytest.raises(store_module.CanaryVoidMarkerError):
            composed_store.require_score_usable(score_id)

    def test_a_score_from_before_the_break_still_passes(
        self, composed_store, composed_halts
    ) -> None:
        # The refusal is scoped to the window: the break did not touch the
        # scores produced before it, and refusing them would be this feature
        # destroying good data.
        store_module = _member_package(composed_store)
        before = _seed_score(composed_store, produced_at=BEFORE_BREAK)
        pair = _broken_pair(composed_store)
        with pytest.raises(store_module.CanaryDeterminismBrokenError):
            store_module.halt_dreaming(
                pair, store_module.replay_pair(pair), detected_at=DETECTED_AT
            )
        composed_store.sweep()
        assert composed_store.require_score_usable(before) is None

    def test_a_held_canary_voids_nothing_through_the_composed_store(
        self, composed_store
    ) -> None:
        # The untaken branch through the assembled system: a pair whose constant
        # the replay reaches writes no halt, opens no window, and the sweep is a
        # quiet return — the nightly green path.
        store_module = _member_package(composed_store)
        _seed_score(composed_store, produced_at=AFTER_BREAK)
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
        assert composed_store.sweep() is None
        assert composed_store.markers() == ()

    def test_the_module_level_sweep_reaches_the_composed_database(
        self, composed_store, composed_halts, test_database_url: str
    ) -> None:
        # The nightly runner holds no store object: it has just watched the
        # canary break and wants the feature.  Pointed at the deployment's own
        # URL, it must refuse exactly the scores the composed store does.
        store_module = _member_package(composed_store)
        _seed_score(composed_store, produced_at=AFTER_BREAK)
        pair = _broken_pair(composed_store)
        with pytest.raises(store_module.CanaryDeterminismBrokenError):
            store_module.halt_dreaming(
                pair, store_module.replay_pair(pair), detected_at=DETECTED_AT
            )
        sweep = store_module.void_scores_after_break(database_url=test_database_url)
        assert sweep is not None
        assert len(sweep.refused) == 1
        assert store_module.unvoided_scores(database_url=test_database_url) == ()
