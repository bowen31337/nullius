"""The plugin seam: composition via the module loader.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands
in the composed application as the ``tripwires`` component. No registry,
router or factory was edited to make that true; this test exists to keep it
true.

Placement is the risky part of a plugin-shaped feature, and it is *especially*
risky for this one: the member shipped with its submodules importable but no
``__init__.py``, so ``packages/tripwires/src`` sat in the declared scan roots
while the loader — which only imports directories that are packages — skipped
it in silence. Every one of the probe's own tests passed throughout. The
assertions below are the ones that would have caught it, and they deliberately
go through the factory's public discovery functions rather than importing the
package directly, because importing it would bypass the very mechanism under
test.

Two properties of the loader shape these tests:

* It imports each member under a synthetic module name
  (``_nullius_scanned_tripwires``), so a package this suite also imported
  canonically as ``tripwires`` exists in the process twice, with two distinct
  class objects. ``isinstance`` across the copies cannot hold, so the composed
  component is pinned by class name and by behaviour.
* It re-executes a package's ``__init__`` on **every** ``create_app()`` but
  does not re-execute an already-cached submodule. So a ``@register`` that
  lived in a submodule would fire on the first composition of a process and
  silently drop out of every later one —
  :func:`test_the_component_survives_a_second_composition` is what catches
  that, and it must assert on the *second* application or it passes vacuously.

After the second test below, the memory note this suite once carried — that
``@register`` belongs in ``__init__`` and never in a submodule — is enforced
here rather than merely remembered.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tripwires
from _panels import gaussian_panel, lookahead_panel, monday

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_members,
    workspace_scan_roots,
)

#: The member's ``src/`` — the package-parent the loader scans. Derived from
#: the imported package rather than from this file's position, so the suite
#: gives the same answer wherever pytest is invoked from.
MEMBER_SRC = Path(tripwires.__file__).resolve().parent.parent


def _assert_is_the_tripwire_component(component: object) -> None:
    assert type(component).__name__ == "TimeShuffleTripwire"
    assert type(component).__module__.endswith("tripwires")
    # The probe's five verbs, duck-checked across the loader's module copy
    # seam: feature 125's run, the pairing and threshold a reader auditing a
    # persisted rejection rebuilds from the record's own terms, and the two
    # perturbation re-runs the family reaches through the same component —
    # feature 127's ``rerun`` and feature 129's ``subsample``, each a method
    # here rather than a component of its own because a re-run is this probe
    # taken twice.
    for operation in ("run", "pairing", "threshold", "rerun", "subsample"):
        assert callable(getattr(component, operation)), operation
    # The probe's own name, not the component's: a persisted failure names
    # which tripwire fired (feature 131).
    assert component.name == "time-shuffle"


def test_the_member_is_declared_in_the_scanned_workspace() -> None:
    # The registration chain starts here: the member's own pyproject.toml is
    # what makes it a workspace member and therefore scannable.
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()
    assert "tripwires" in {member.name for member in workspace_members()}
    # ...and the package the loader will look for actually exists. This is
    # the assertion the missing __init__.py failed.
    assert (MEMBER_SRC / "tripwires" / "__init__.py").is_file()


def test_scanning_the_member_registers_exactly_the_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called
    # a bare ``create_app()`` has already imported every workspace member into
    # the current registry, so reading it back here would assert accumulated
    # process state, not this package's contribution.
    #
    # The member contributes four components since feature 129: the probe
    # (``tripwires``, feature 125, stateless and ready the instant it is built),
    # the store a failure is persisted to (``tripwires-poison``, feature 131,
    # which resolves ``DATABASE_URL`` and may legitimately not exist), the pool a
    # poisoned branch is excised from (``tripwires-excise``, feature 132, which
    # resolves the same variable to *read* what the store wrote), and the store
    # a stability figure is persisted to (``tripwires-stability``, feature 129,
    # which resolves the same variable again into a different table with a
    # different refusal). The list is pinned exactly rather than by membership,
    # so a *fifth* component arriving unnoticed fails here the way the fourth
    # one would have — which is the property this test has always been for.
    #
    # The fourth arriving is why the stability store is spelled here rather
    # than folded into ``tripwires-poison``: both resolve ``DATABASE_URL``, and
    # a member that answered the two questions with one component would have
    # made this list a list of three and left the distinction untested.
    components = scan_components(MEMBER_SRC, registry=Registration())
    assert sorted(component.name for component in components) == [
        "tripwires",
        "tripwires-excise",
        "tripwires-poison",
        "tripwires-stability",
    ]


def test_the_stability_store_is_its_own_component() -> None:
    # Feature 129's store is composed *beside* feature 131's, not inside it.
    # Both resolve ``DATABASE_URL``, so in a bare process both are ``None`` and
    # a wiring test that only asked whether the component exists could not see
    # them collapsed into one builder under two names — the two names would
    # both be present and both ``None``.  So the two are asked for through
    # their composed types: the builders registered under them must be two
    # functions, and a ``DATABASE_URL`` in the environment must produce two
    # *different* classes of store.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["tripwires-stability"] is not builders["tripwires-poison"]
    assert builders["tripwires-stability"].__name__ == "build_stability_store"

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        app = create_app(MEMBER_SRC, registry=Registration())
        stability = app.get("tripwires-stability")
        poison = app.get("tripwires-poison")
        assert type(stability).__name__ == "StabilityStore"
        assert type(poison).__name__ == "PoisonStore"
        assert stability is not poison
    finally:
        monkeypatch.undo()


def test_the_composed_application_carries_the_tripwire_component() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    _assert_is_the_tripwire_component(app.get("tripwires"))
    assert "tripwires" in app
    assert "tripwires" in app.order


def test_an_unconfigured_environment_still_composes() -> None:
    # The load-bearing property for a member that reads no environment at all:
    # the factory builds every registered component on every create_app(), so
    # the builder must not require a store, a lake or a pinned image. This one
    # resolves nothing, so a bare process composes it — and the other members
    # are still composed alongside it.
    app = create_app()
    _assert_is_the_tripwire_component(app.get("tripwires"))
    for component in ("snapshot", "universe", "ingest"):
        assert component in app, component


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish. Asserting on the first application would pass either
    # way — the second is the test.
    create_app()
    second = create_app()
    _assert_is_the_tripwire_component(second.get("tripwires"))
    assert "tripwires" in second


def test_the_composed_probe_detects_a_planted_leak() -> None:
    # Feature 125 through the composed application: the path an assembled
    # system actually takes. A composition that carried a component whose
    # `run` did nothing would pass every wiring assertion above and fail here.
    dates = monday(120)
    symbols = [f"S{index:02d}" for index in range(30)]
    targets = {1: gaussian_panel(dates, symbols, seed=17)}
    scores = lookahead_panel(targets, horizon=1)

    probe = create_app(MEMBER_SRC, registry=Registration()).get("tripwires")
    verdict = probe.run(scores, targets, node_id="node-1")
    assert verdict.rejected is True
    assert verdict.outcome == "tripwire_fail"
    assert verdict.horizon == 1
    assert verdict.dates == len(dates)


def test_the_composed_probe_exposes_the_audit_seam() -> None:
    # `pairing` and `threshold` are on the component because a reader checking
    # a persisted rejection rebuilds both from the verdict's own seed and
    # level — and the recomputation must agree with what the verdict carried,
    # or the audit path is not the probe path.
    dates = monday(40)
    symbols = ["A", "B", "C"]
    targets = {1: gaussian_panel(dates, symbols, seed=2)}
    scores = gaussian_panel(dates, symbols, seed=3)

    probe = create_app(MEMBER_SRC, registry=Registration()).get("tripwires")
    verdict = probe.run(scores, targets, node_id="node-1", seed=13)
    assert dict(probe.pairing(dates, seed=verdict.seed)) == dict(verdict.pairing)
    assert probe.threshold(verdict.dates, level=verdict.level) == verdict.threshold


def test_the_seat_exposes_the_composed_component() -> None:
    # src/app/modules/tripwires is the member's seat in the app namespace: it
    # names the component and asks the factory for it without the app package
    # depending on any member at import time.
    from app.modules.tripwires import COMPONENT_NAME, tripwires_component

    assert COMPONENT_NAME == "tripwires"
    app = create_app(MEMBER_SRC, registry=Registration())
    _assert_is_the_tripwire_component(tripwires_component(app))


def test_the_seat_returns_none_when_nothing_registered() -> None:
    # An application with no component registered is a discoverable state, not
    # an exception — mirroring the factory's stance. And for this member
    # ``None`` means exactly one thing: nothing registered, never "registered
    # but not yet configured", because the probe resolves no environment.
    from app.modules.tripwires import tripwires_component

    assert tripwires_component(Application(components={}, order=())) is None


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.tripwires import tripwires_component

    application = Application(
        components={"tripwires": "sentinel"}, order=("tripwires",)
    )
    assert tripwires_component(application) == "sentinel"
