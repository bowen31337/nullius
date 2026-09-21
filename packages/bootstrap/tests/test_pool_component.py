"""The pool's two seams: composition via the loader, and the app seat.

Feature 188 adds this member's *second* component, and this suite holds
both halves of its wiring — the registration contract
``test_component.py`` states for the world, restated for the pool, and
the seat contract ``test_app_module.py`` states for the world's seat,
restated for the pool's (:mod:`app.modules.bootstrap.pool`).

The loader's two properties shape the composition half exactly as they
shaped the world's (see ``test_component.py``'s docstring): the scan
imports each member under a synthetic name, so the composed pool is
pinned by class name, module suffix and behaviour rather than by
``isinstance``; and it re-executes a package's ``__init__`` on every
``create_app()`` but not an already-cached submodule, so the pool's
``@register`` — like the world's — must live in ``__init__.py`` to fire
on *every* composition rather than the first.

**The pool's own composition property: on demand, or not at all.**  The
world's builder needs no environment; the pool's resolves
``DATABASE_URL`` and may legitimately compose to ``None`` — the
degrade-don't-break stance every store in this workspace takes.  And
where the world's composition is *always safe because it computes
nothing*, the pool's composition must be always safe because it *writes*
nothing: the feature's sentence says "on demand", and the test below
holds the database file absent after composition and present only after
the authoring call — the composition seam is where a pool that helped
itself to the database would be hardest to see.

**The seat's ``None`` is not the world seat's ``None``.**  The world
seat answers ``None`` when no component was registered — a statement
about composition.  The pool seat answers ``None`` when the component
*was* registered and resolved no database — a statement about the
deployment.  A caller holding the first cannot label a node at all; a
caller holding the second must refuse to author, not silently author
nothing.  The tests keep the two apart by constructing each state
deliberately: a scanned application without ``DATABASE_URL`` composes
the pool component as ``None``, while an empty ``Application()`` — no
scan at all — is the state where nothing was registered.
"""

from __future__ import annotations

from pathlib import Path

import bootstrap as member
import pytest

from app.module_loader import Application, Registration, create_app, scan_components
from app.modules import bootstrap as world_seat
from app.modules.bootstrap import pool as pool_seat

#: The pool seat's whole public surface, asserted as an exact set for the
#: same reason the world seat's is (see ``test_app_module.py``): the
#: failure this guards against is the seat *growing* a re-export, and a
#: membership check cannot see that.
EXPECTED_EXPORTS = {"COMPONENT_NAME", "bootstrap_pool_component"}


def _assert_is_the_bootstrap_pool(component: object) -> None:
    """The composed component is the pool, pinned across the loader's copies.

    Name, module suffix, then behaviour — the same ladder
    ``test_component.py`` climbs for the world, because the loader's
    synthetic-name copies make ``isinstance`` unusable and behaviour is
    what matters anyway: the composed pool carries the deployment's URL
    and answers the store's own reads.
    """
    assert type(component).__name__ == "BootstrapPool"
    assert type(component).__module__.endswith("bootstrap._pool")
    for question in ("persist_worlds", "worlds", "world_count", "world"):
        assert callable(getattr(component, question)), question
    for fact in ("database_url", "path"):
        assert getattr(component, fact) is not None, fact


# -- The registration -------------------------------------------------------------


def test_the_member_registers_the_pool_under_its_own_name() -> None:
    # A second component under a second name — not a second face of the
    # world's — because the world is ready the instant it is built while
    # the pool is a deployment state that may legitimately be ``None``,
    # and a caller holding one ``None`` wants a fact the other never
    # meant.  The member, the seat and the spec's plugin vocabulary all
    # spell the one name.
    assert member.POOL_COMPONENT_NAME == pool_seat.COMPONENT_NAME == "bootstrap-pool"
    assert member.POOL_COMPONENT_NAME != member.COMPONENT_NAME


def test_the_scanned_application_carries_the_pool(
    monkeypatch, tmp_path: Path
) -> None:
    # The factory scans the members, this package's ``@register`` fires,
    # and the composed application carries the pool for the deployment
    # the process is running in — here, the database the test names.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.POOL_COMPONENT_NAME in app
    assert member.POOL_COMPONENT_NAME in app.order
    _assert_is_the_bootstrap_pool(app.get(member.POOL_COMPONENT_NAME))
    # And the world's component is untouched by the growth: two
    # components, two questions.
    assert app.get(member.COMPONENT_NAME) is not None
    assert app.get(member.COMPONENT_NAME) is not app.get(member.POOL_COMPONENT_NAME)


def test_the_pool_component_survives_a_second_composition(
    monkeypatch, tmp_path: Path
) -> None:
    # The submodule-registration hazard, and the reason *both* of this
    # member's builders live in ``__init__.py``: the loader caches
    # imported submodules, so a ``@register`` in one fires on the first
    # composition of a process and quietly drops out of every later one.
    # Asserts on the second and third applications specifically — a test
    # that only looked at the first would pass wherever the builder
    # lived and would have caught nothing.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    first = create_app()
    second = create_app()
    third = create_app()
    for app in (first, second, third):
        _assert_is_the_bootstrap_pool(app.get(member.POOL_COMPONENT_NAME))
        assert member.POOL_COMPONENT_NAME in app.order


def test_the_builder_degrades_to_none_without_a_database(monkeypatch) -> None:
    # An absent ``DATABASE_URL`` composes no pool — a discoverable
    # deployment state, not an exception, because a builder that raised
    # would take composition down for every unrelated feature in the
    # workspace.  The *refusal* belongs to the caller who needs to
    # author and finds no pool, not to the factory.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    assert app.get(member.POOL_COMPONENT_NAME) is None


def test_the_builder_never_raises_and_takes_no_arguments() -> None:
    # The registration protocol passes nothing, and the factory builds
    # every component on every composition — the pool's builder honours
    # both, and resolves the environment itself.
    import inspect

    assert list(inspect.signature(member.build_bootstrap_pool).parameters) == []
    assert member.build_bootstrap_pool() is None or isinstance(
        member.build_bootstrap_pool(), member.BootstrapPool
    )


def test_scanning_registers_the_pool_exactly_once() -> None:
    # A duplicate registration of one name is silently overridden by
    # whichever import landed later, so it would be invisible at runtime
    # and would make the composed pool depend on scan order.  Counted
    # against a fresh registry, so the assertion is about this member's
    # contribution.
    registry = Registration()
    scan_components(registry=registry)
    named = [
        component
        for component in registry.components()
        if component.name == member.POOL_COMPONENT_NAME
    ]
    assert len(named) == 1
    # And the two components of this member are the only bootstrap ones.
    assert sorted(
        component.name
        for component in registry.components()
        if component.name.startswith("bootstrap")
    ) == ["bootstrap", "bootstrap-pool"]


# -- On demand --------------------------------------------------------------------


def test_composing_writes_nothing_and_authoring_is_on_demand(
    monkeypatch, tmp_path: Path
) -> None:
    # The feature's own adverb, held at the composition seam: an
    # application composed *for* a database-deployed process writes
    # nothing into it, and the forty-five worlds appear only when the
    # authoring is demanded.  A composition that helped itself to the
    # database would persist worlds into a deployment an operator
    # pointed the process at for an unrelated reason.
    database = tmp_path / "on-demand.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    app = create_app()
    assert not database.exists()  # composition touched nothing
    pool = app.get(member.POOL_COMPONENT_NAME)
    assert pool is not None
    assert not database.exists()  # asking for the component touched nothing
    report = pool.persist_worlds()
    assert database.exists()  # the demand is what wrote
    assert report.count == member.DEFAULT_POOL_SIZE
    assert pool.world_count() == member.DEFAULT_POOL_SIZE


# -- The seat ---------------------------------------------------------------------


def test_the_pool_seat_exposes_nothing_but_the_composition_accessor() -> None:
    # See the world seat's twin test: the seat's job is to answer one
    # question, and every extra name is a second thing to keep in sync
    # with the member — the size band, the committed pool seed and the
    # authoring entry point are the specific names a well-meaning
    # re-export would add first.
    assert set(pool_seat.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(pool_seat, name), name
    for leaked in ("BootstrapPool", "persist_worlds", "POOL_SEED", "MIN_POOL_SIZE"):
        assert leaked not in pool_seat.__all__


def test_the_pool_seat_returns_the_composed_pool(
    monkeypatch, tmp_path: Path
) -> None:
    # The composition-level contract, checked by behaviour across the
    # loader's synthetic-name copy.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    pool = pool_seat.bootstrap_pool_component()
    assert pool is not None
    assert type(pool).__name__ == "BootstrapPool"
    assert pool.database_url == f"sqlite:///{tmp_path / 'seated.db'}"


def test_the_pool_seat_reads_the_application_it_is_handed(
    monkeypatch, tmp_path: Path
) -> None:
    # A caller that already holds an application gets *that*
    # application's pool — the seat must not compose its own behind the
    # caller's back, for the same reason the world seat must not.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'handed.db'}")
    app = create_app()
    assert pool_seat.bootstrap_pool_component(app) is app.get(member.POOL_COMPONENT_NAME)


def test_an_absent_component_reads_as_none_rather_than_raising() -> None:
    # ``Application`` is a plain dataclass, so the absent case is
    # constructible without depending on a scan having failed — and the
    # seat answers ``None`` rather than raising, which is what makes it
    # safe to import in a workspace that does not carry this member.
    assert pool_seat.bootstrap_pool_component(Application()) is None


def test_the_pool_seat_composes_nothing_of_its_own() -> None:
    # Reading the component must not *create* one: a seat that built a
    # pool behind the caller's back would report a pool where the
    # deployment holds none — and would have opened a database the
    # process never asked for.
    empty = Application()
    assert pool_seat.bootstrap_pool_component(empty) is None
    assert empty.components == {}


def test_an_empty_workspace_still_composes_only_the_absent_pool(tmp_path) -> None:
    # The same fact through the real factory: a composition whose scan
    # contributes nothing still builds, and the seat still answers
    # ``None``.  Both halves of "contributed nothing" are needed — an
    # empty root *and* a fresh registry (the default registry is
    # module-level and persists across calls, so a second ``create_app``
    # would inherit everything the first one's scan registered).
    empty = create_app(tmp_path, registry=Registration())
    assert empty.components == {}
    assert pool_seat.bootstrap_pool_component(empty) is None


def test_the_two_seats_answer_different_questions(
    monkeypatch, tmp_path: Path
) -> None:
    # The world seat's ``None`` means no component was registered; the
    # pool seat's means the component ran and resolved no database.  A
    # deployment *with* a database and *without* one are pinned side by
    # side here so the two ``None``s cannot be conflated by accident.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'deployed.db'}")
    deployed = create_app()
    assert world_seat.hyperparameter_world_component(deployed) is not None
    assert pool_seat.bootstrap_pool_component(deployed) is not None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    bare = create_app()
    # The world composes whatever the deployment; the pool is the half
    # the deployment owns.
    assert world_seat.hyperparameter_world_component(bare) is not None
    assert pool_seat.bootstrap_pool_component(bare) is None


@pytest.mark.parametrize("absent", ["", "bootstrap-hpo", "bootstrap-pool-typo", "pool"])
def test_a_misspelled_component_key_is_absent_not_a_near_match(
    monkeypatch, tmp_path: Path, absent: str
) -> None:
    # The component key is exact.  The specific plausible misses are the
    # world-id prefix and the component name minus its prefix — someone
    # reading the pool's reports rather than the code would reach for
    # either — and none may fuzzy-match onto the pool.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
    app = create_app()
    assert app.get(absent) is None
    # The real key works, and the member's *other* key is the world —
    # not a pool the near-miss could be handed instead.
    assert pool_seat.COMPONENT_NAME in app
    assert type(app.get(member.COMPONENT_NAME)).__name__ == "HyperparameterWorld"
    assert pool_seat.bootstrap_pool_component(app) is not None
