"""The plugin seam: composition via the module loader.

This is the registration contract from the other side — the factory
scans the workspace members, imports this package, and the
``@register`` builder lands in the composed application as the
``canary`` component. No registry, router or factory was edited to
make that true; this test exists to keep it true.

Two properties of the loader shape these tests:

* It imports each member under a synthetic module name
  (``_nullius_scanned_canary``), so a package this suite also imported
  canonically as ``canary`` exists in the process twice, with two
  distinct class objects. ``isinstance`` across the copies cannot
  hold, so the composed component is pinned by class name and by
  behaviour.
* It re-executes a package's ``__init__`` on **every** ``create_app()``
  but does not re-execute an already-cached submodule. So a
  ``@register`` that lived in a submodule would fire on the first
  composition of a process and silently drop out of every later one —
  ``test_the_component_survives_a_second_composition`` is what catches
  that, and it must assert on the *second* application or it passes
  vacuously.
"""

from __future__ import annotations

import pytest

from app.module_loader import create_app


def _assert_is_the_canary_service(component: object) -> None:
    assert type(component).__name__ == "CanaryService"
    assert type(component).__module__.endswith("canary._service")
    # The sweep is the component's one verb: a composition that carried
    # a canary which could not sweep would be a plugin half-wired, and
    # feature 135 is exactly that verb. Asserted on the *class*, not on
    # ``getattr(component, ...)``: ``containers`` is a property, so
    # reading it off the instance would run the sweep — and this helper
    # is called on composed services over deliberately unpinned
    # environments, where the sweep's refusal is the point rather than a
    # composition failure.
    assert isinstance(vars(type(component)).get("containers"), property)


def test_the_composed_application_carries_the_canary_component(
    canary_env: dict[str, str],
) -> None:
    app = create_app()
    component = app.get("canary")
    _assert_is_the_canary_service(component)
    assert "canary" in app


def test_an_environment_with_no_pinned_image_still_composes() -> None:
    # The load-bearing property: the factory builds every registered
    # component on every create_app(), so the canary builder must not
    # require a pinned environment. If it did, one member's
    # unconfigured environment would take down composition for every
    # unrelated feature in the workspace.
    app = create_app()
    _assert_is_the_canary_service(app.get("canary"))


def test_a_tag_only_environment_does_not_break_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The widest-blast-radius version of the laziness property: the
    # misconfiguration this member exists to refuse must not take the
    # factory down on its way to being refused.
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", "nullius-evaluator:latest")
    app = create_app()
    _assert_is_the_canary_service(app.get("canary"))
    with pytest.raises(Exception, match="not pinned by digest"):
        _ = app.get("canary").containers
    # The other members are still composed alongside it.
    for component in ("snapshot", "universe", "ingest", "evaluator"):
        assert component in app, component


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a
    # submodule: the loader re-executes ``__init__`` on every
    # composition but not an already-cached submodule, so a builder
    # that drifted into one would fire once and vanish. Asserting on
    # the first application would pass either way — the second is the
    # test.
    create_app()
    second = create_app()
    _assert_is_the_canary_service(second.get("canary"))
    assert "canary" in second


def test_the_sweep_through_the_composed_service(canary_env: dict[str, str]) -> None:
    # Feature 135 through the composed application: the path an
    # assembled system actually takes.
    service = create_app().get("canary")
    _assert_is_the_canary_service(service)
    containers = service.containers
    assert containers["evaluator"].digest == "sha256:" + "ab" * 32
    assert "evaluator" in containers


def test_the_composed_service_reads_the_environment_it_is_composed_in(
    canary_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The builder resolves from the environment at build time, so a
    # recomposed application follows a moved image rather than holding
    # the one the first composition saw — the audit-side face of §15's
    # "Evaluator image changed" failure row.
    first = create_app().get("canary").containers
    monkeypatch.setenv(
        "NULLIUS_EVALUATOR_IMAGE", "ghcr.io/nullius/evaluator@sha256:" + "cd" * 32
    )
    second = create_app().get("canary").containers
    assert first["evaluator"].digest != second["evaluator"].digest
