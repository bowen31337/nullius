"""The member's composition seam: its component as the loader composes it.

Feature 270 contributes exactly one component, and this suite holds its wiring —
the registration contract every member's component suite states for its own
component, and what the composed application answers for it.

The loader's two properties shape the composition half exactly as they shape
every sibling member's: the scan imports each member under a synthetic name, so
the composed freeze is pinned by class name, module suffix and behaviour rather
than by ``isinstance``; and it re-executes a package's ``__init__`` on every
``create_app()`` but not an already-cached submodule, so the member's
``@register`` — like every sibling's — must live in ``__init__.py`` to fire on
*every* composition rather than the first.

**This component's own composition property: it holds nothing.**  A pool bound
to a deployment may legitimately compose to ``None``, which every store in this
workspace states for its own builder; what is particular to *this* one is that
the thing it composes is a *hold*, and §C5's hold is **per outer iteration**.
So composition must not acquire one — an application that held the pool from
composition time would hold it for as long as the process lived, which is a
dreaming cycle that never ends.  The test below holds the database file absent
after composition and asserts no hold row exists in it, which is the closest a
single process can come to proving a negative across a composition seam.

**The composed ``None`` is not "the pool is free".**  The application answers
``None`` when the component resolved no database — a statement about the
*deployment*.  A pool that is free is a database that exists with no open hold,
which is ``freeze.open_hold() is None`` against a freeze it *did* hand back.  The
tests keep the two apart by constructing each state deliberately: a scanned
application without ``DATABASE_URL`` composes the component as ``None``, while
an empty ``Application()`` — no scan at all — is the state where nothing was
registered.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import dreaming as member

from app.module_loader import Application, Registration, create_app, scan_components


def _assert_is_the_cycle_freeze(component: object) -> None:
    """The composed component is the freeze, pinned across the loader's copies.

    Name, module suffix, then behaviour — the ladder every sibling member's
    component suite climbs, because the loader's synthetic-name copies make
    ``isinstance`` unusable and behaviour is what matters anyway: the composed
    freeze carries the deployment's URL and answers the store's own reads.
    """
    assert type(component).__name__ == "CycleFreeze"
    assert type(component).__module__.endswith("dreaming.cycle")
    for question in ("open", "release", "verify", "guard", "open_hold", "holds"):
        assert callable(getattr(component, question)), question
    for fact in ("database_url", "path"):
        assert getattr(component, fact) is not None, fact


# -- The registration ------------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    # Unprefixed, following the ledger / artifacts / discovery precedent for a
    # member's first and only component.  The member and the spec's plugin
    # vocabulary both spell the one name.
    assert member.COMPONENT_NAME == "dreaming"


def test_the_scanned_application_carries_the_freeze(
    monkeypatch, tmp_path: Path
) -> None:
    # The factory scans the members, this package's ``@register`` fires, and
    # the composed application carries the freeze for the deployment the
    # process is actually running in.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()

    assert member.COMPONENT_NAME in app
    assert member.COMPONENT_NAME in app.order
    _assert_is_the_cycle_freeze(app.get(member.COMPONENT_NAME))


def test_the_name_sorts_between_discovery_and_evaluator(
    monkeypatch, tmp_path: Path
) -> None:
    # ``app.order`` is name-sorted and the existing suite asserts adjacencies
    # over it, so a new member's name is a claim about a shared ordering.  This
    # one lands between the two it belongs between — the campaign the cycle is
    # run over, and the evaluation §C5 runs inside it — and asserts the
    # neighbourhood rather than the whole list, so a *later* member landing
    # elsewhere does not fail this test for a reason that is not about this
    # member.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    order = create_app().order

    assert "dreaming" in order
    assert order.index("discovery") < order.index("dreaming") < order.index("evaluator")


def test_the_component_survives_a_second_composition(
    monkeypatch, tmp_path: Path
) -> None:
    # The submodule-registration hazard, and the reason the builder lives in
    # ``__init__.py``: the loader caches imported submodules, so a
    # ``@register`` in one fires on the first composition of a process and
    # quietly drops out of every later one.  Asserts on the second and third
    # applications specifically — a test that only looked at the first would
    # pass wherever the builder lived and would have caught nothing.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")

    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_cycle_freeze(app.get(member.COMPONENT_NAME))
        assert member.COMPONENT_NAME in app.order


def test_the_builder_degrades_to_none_without_a_database(monkeypatch) -> None:
    # An absent ``DATABASE_URL`` composes no freeze — a discoverable deployment
    # state, not an exception, because a builder that raised would take
    # composition down for every unrelated feature in the workspace.  The
    # *refusal* belongs to the caller who needs a hold and finds none, not to
    # the factory.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert create_app().get(member.COMPONENT_NAME) is None


def test_the_builder_never_raises_and_takes_no_arguments(monkeypatch) -> None:
    # The registration protocol passes nothing, and the factory builds every
    # component on every composition — the builder honours both, and resolves
    # the environment itself.  Checked against a URL the member cannot speak,
    # which is the input a raising builder would trip over.
    assert list(inspect.signature(member.build_cycle_freeze).parameters) == []
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/nullius")
    assert isinstance(member.build_cycle_freeze(), member.CycleFreeze)


def test_composition_acquires_no_hold_and_touches_no_database(
    monkeypatch, tmp_path: Path
) -> None:
    """§C5's hold is *per outer iteration* — composing must not take one.

    Composing an application over a database that does not exist yet neither
    creates it nor fails, which is the closest a single process comes to
    proving no I/O happened — and the freeze the application then carries has
    no hold of its own, because the path it will read is still unresolved.

    An application that held the pool from composition time would hold it for
    as long as the process lived, and every other cycle in the system would be
    refused by a hold nobody could release.

    The un-held *state* is asserted against a pool that exists rather than
    against this absent one, deliberately: asking whether an absent pool is
    held is a question this member refuses
    (:meth:`~dreaming.cycle.CycleFreeze.open_hold` reaches the store, and the
    store refuses a database with no pool in it), which is a different claim
    from the one under test here.  ``test_a_hold_is_free_before_it_is_open``
    in ``test_cycle.py`` states that claim.
    """
    database = tmp_path / "composed.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")

    app = create_app()
    freeze = app.get(member.COMPONENT_NAME)

    assert not database.exists()  # composition created nothing
    assert freeze.path == database  # ...and the path was only ever computed


def test_scanning_registers_the_component_exactly_once() -> None:
    # A duplicate registration of one name is silently overridden by the
    # registry, so a second ``@register`` for this name would be invisible
    # everywhere except here.
    registry = Registration()
    scan_components(registry=registry)

    names = [component.name for component in registry.components()]
    assert names.count(member.COMPONENT_NAME) == 1


# -- The composed application ---------------------------------------------------


def test_an_application_without_the_component_answers_none() -> None:
    # No scan at all — nothing was registered — which is a statement about
    # *composition*, and deliberately not the same fact as a deployment that
    # named no database.
    assert Application().get(member.COMPONENT_NAME) is None


def test_the_default_composition_answers_the_freeze(monkeypatch, tmp_path: Path) -> None:
    # With no explicit roots the factory scans the declared workspace — the
    # production path.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'default.db'}")

    _assert_is_the_cycle_freeze(create_app().get(member.COMPONENT_NAME))


def test_the_composed_freeze_degrades_to_none_without_a_database(monkeypatch) -> None:
    # The composed ``None`` is a statement about the deployment: the component
    # *was* registered and resolved nothing.  A caller holding it must refuse
    # to run §C5's loop rather than run it while believing its history was
    # fixed — §12.1's *"the dreaming loop overfits its own replay pool"* is
    # exactly why a cycle that held nothing would compare its ``M`` revisions
    # across a pool free to move under them, with nothing in the result looking
    # wrong.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert create_app().get(member.COMPONENT_NAME) is None
