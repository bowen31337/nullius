"""The plugin seam: composition via the module loader.

This is the registration contract from the other side — the factory scans
the workspace members, imports this package, and the ``@register`` builder
lands in the composed application as the ``evaluator`` component. No
registry, router or factory was edited to make that true; this test exists to
keep it true.

Two properties of the loader shape these tests:

* It imports each member under a synthetic module name
  (``_nullius_scanned_evaluator``), so a package this suite also imported
  canonically as ``evaluator`` exists in the process twice, with two distinct
  class objects. ``isinstance`` across the copies cannot hold, so the
  composed component is pinned by class name and by behaviour.
* It re-executes a package's ``__init__`` on **every** ``create_app()`` but
  does not re-execute an already-cached submodule. So a ``@register`` that
  lived in a submodule would fire on the first composition of a process and
  silently drop out of every later one —
  :func:`test_the_component_survives_a_second_composition` is what catches
  that, and it must assert on the *second* application or it passes
  vacuously.
"""

from __future__ import annotations

import pytest

from app.module_loader import create_app


def _assert_is_the_evaluator_service(component: object) -> None:
    assert type(component).__name__ == "EvaluatorService"
    assert type(component).__module__.endswith("evaluator._service")
    # The identity side and the persistence side both hang off the composed
    # component: a composition that carried one but not the other would be a
    # plugin half-wired, and feature 70 needs both verbs.
    for operation in ("identity", "record", "recorded", "resolved_config"):
        assert callable(getattr(component, operation)), operation


def test_the_composed_application_carries_the_evaluator_component(
    evaluator_env: dict[str, str],
) -> None:
    app = create_app()
    component = app.get("evaluator")
    _assert_is_the_evaluator_service(component)
    assert "evaluator" in app


def test_an_environment_with_no_pinned_image_still_composes() -> None:
    # The load-bearing property: the factory builds every registered
    # component on every create_app(), so the evaluator builder must not
    # require a pinned image or a database. If it did, one member's
    # unconfigured environment would take down composition for every
    # unrelated feature in the workspace.
    app = create_app()
    _assert_is_the_evaluator_service(app.get("evaluator"))


def test_a_broken_evaluator_environment_does_not_break_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The widest-blast-radius version of the laziness property. Every input
    # this member reads from the environment — the image, the store, the
    # configuration override — is resolved on first use rather than at
    # construction, because create_app() calls every registered builder. If
    # any of them were eager, one member's mistyped variable would take
    # composition down for every unrelated feature in the workspace.
    monkeypatch.setenv("NULLIUS_EVALUATOR_CONFIG", "{not json")
    monkeypatch.delenv("NULLIUS_EVALUATOR_IMAGE", raising=False)

    app = create_app()
    _assert_is_the_evaluator_service(app.get("evaluator"))
    # The other members are still composed alongside it.
    for component in ("snapshot", "universe", "ingest"):
        assert component in app, component


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a
    # submodule: the loader re-executes ``__init__`` on every composition but
    # not an already-cached submodule, so a builder that drifted into one
    # would fire once and vanish. Asserting on the first application would
    # pass either way — the second is the test.
    create_app()
    second = create_app()
    _assert_is_the_evaluator_service(second.get("evaluator"))
    assert "evaluator" in second


def test_recording_through_the_composed_service(
    evaluator_env: dict[str, str],
) -> None:
    # Feature 70 through the composed application: the path an assembled
    # system actually takes.
    service = create_app().get("evaluator")
    _assert_is_the_evaluator_service(service)

    identity = service.record()
    assert len(identity.evaluator_hash) == 64
    assert identity.image_digest.startswith("sha256:")
    assert service.recorded().evaluator_hash == identity.evaluator_hash


def test_the_composed_service_reads_the_environment_it_is_composed_in(
    evaluator_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The builder resolves from the environment at build time, so a
    # recomposed application follows a moved image rather than holding the
    # one the first composition saw.
    first = create_app().get("evaluator").record()
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", "ghcr.io/nullius/evaluator@sha256:" + "cd" * 32)
    second = create_app().get("evaluator").identity()
    assert first.evaluator_hash != second.evaluator_hash
