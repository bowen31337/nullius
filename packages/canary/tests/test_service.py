"""The service: one answer to "is this deployment pinned?".

These tests pin :mod:`canary._service` — the laziness that keeps
composition alive, the sweep that the laziness eventually runs, and the
seams (explicit declaration, environment mapping) that decide which
spelling of the deployment the sweep reads. The refusal cases are the
feature arriving through the surface a nightly runner would actually
hold.
"""

from __future__ import annotations

import pytest
from canary import (
    CanaryImageError,
    CanaryLockfileError,
    CanaryService,
    build_canary_service,
    lockfile_from_env,
    pin_containers,
)
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    OTHER_PINNED_IMAGE,
    PINNED_EVALUATOR_DIGEST,
    PINNED_EVALUATOR_IMAGE,
    PINNED_RUNNER_IMAGE,
)

# -- Laziness: composition must never need a pin ------------------------------


def test_a_service_constructs_without_an_environment() -> None:
    # The factory builds every registered component on every
    # create_app(); a builder that needed a pinned environment would
    # take composition down for every unrelated feature in the
    # workspace. A bare environment therefore constructs, and the
    # service is a perfectly good object that simply has not swept.
    service = CanaryService()
    assert service._pins is None


def test_build_canary_service_is_the_lenient_spelling() -> None:
    assert build_canary_service()._pins is None


def test_the_sweep_lands_on_first_use_where_it_is_informative() -> None:
    # No environment: the refusal names the variable, not a composition
    # fault — the deployment's own misconfiguration.
    service = CanaryService()
    with pytest.raises(CanaryImageError, match="NULLIUS_EVALUATOR_IMAGE is not set"):
        service.containers


def test_a_tag_only_environment_is_refused_on_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", "nullius-evaluator:latest")
    service = CanaryService()
    with pytest.raises(CanaryImageError, match="not pinned by digest") as raised:
        service.containers
    assert "the evaluator container" in str(raised.value)


def test_the_sweep_resolves_and_caches(canary_env: dict[str, str]) -> None:
    service = CanaryService()
    containers = service.containers
    # Resolved once: a deployment that re-read its pins mid-run could
    # observe two different truths about the same night.
    assert service.containers is containers
    assert containers.roles == ("evaluator",)
    assert containers["evaluator"].digest == PINNED_EVALUATOR_DIGEST


# -- The environment seam ------------------------------------------------------


def test_the_env_mapping_is_the_single_seam() -> None:
    # A service handed an explicit mapping resolves through it alone:
    # the mapping is the whole environment as far as the service is
    # concerned, so a refused spelling in it is the refusal the sweep
    # raises, with no process values to fall through to.
    service = CanaryService(env={"NULLIUS_EVALUATOR_IMAGE": "declared-tag:latest"})
    resolved = CanaryService(env={"NULLIUS_EVALUATOR_IMAGE": PINNED_EVALUATOR_IMAGE})
    with pytest.raises(CanaryImageError, match="declared-tag"):
        service.containers
    assert resolved.containers["evaluator"].digest == PINNED_EVALUATOR_DIGEST


def test_a_moved_image_is_followed_by_a_new_service() -> None:
    # The pin is read per-service at first use, so a deployment that
    # moves its image constructs a new service rather than the old
    # service quietly changing its mind mid-run.
    first = CanaryService(env={"NULLIUS_EVALUATOR_IMAGE": PINNED_EVALUATOR_IMAGE})
    second = CanaryService(env={"NULLIUS_EVALUATOR_IMAGE": OTHER_PINNED_IMAGE})
    assert first.containers["evaluator"].digest == PINNED_EVALUATOR_DIGEST
    assert second.containers["evaluator"].digest == "sha256:" + "cd" * 32


# -- The explicit declaration ---------------------------------------------------


def test_an_explicit_declaration_is_swept_at_the_call_site() -> None:
    # A tag-only reference handed in by a caller fails at construction,
    # not on first use: the mistake is the caller's own spelling, and
    # the refusal should name it where it was made.
    with pytest.raises(CanaryImageError, match="the runner container"):
        CanaryService(images={"runner": "nullius-runner:latest"})


def test_an_explicit_declaration_wins_over_the_environment() -> None:
    service = CanaryService(
        {"runner": PINNED_RUNNER_IMAGE},
        env={"NULLIUS_EVALUATOR_IMAGE": PINNED_EVALUATOR_IMAGE},
    )
    # An explicit declaration is swept at construction and is the whole
    # sweep from then on — the environment is not read at all.
    assert service.containers.roles == ("runner",)


def test_an_explicit_declaration_still_refuses_vacuity() -> None:
    with pytest.raises(CanaryImageError, match="vacuous"):
        CanaryService(images={})


# -- Strict construction ---------------------------------------------------------


def test_strict_construction_refuses_an_incomplete_environment() -> None:
    with pytest.raises(CanaryImageError, match="NULLIUS_EVALUATOR_IMAGE is not set"):
        CanaryService.from_env({}, strict=True)


def test_strict_construction_refuses_a_tag_only_environment() -> None:
    with pytest.raises(CanaryImageError, match="not digest-pinned"):
        CanaryService.from_env(
            {"NULLIUS_EVALUATOR_IMAGE": "nullius-evaluator"}, strict=True
        )


def test_strict_construction_accepts_a_pinned_environment() -> None:
    service = CanaryService.from_env(
        {"NULLIUS_EVALUATOR_IMAGE": PINNED_EVALUATOR_IMAGE}, strict=True
    )
    assert service.containers["evaluator"].digest == PINNED_EVALUATOR_DIGEST


def test_lenient_construction_defers_the_same_refusal() -> None:
    service = CanaryService.from_env(
        {"NULLIUS_EVALUATOR_IMAGE": "nullius-evaluator"}, strict=False
    )
    assert service._pins is None
    with pytest.raises(CanaryImageError, match="not digest-pinned"):
        service.containers


# -- Composition with the sweep's own vocabulary ---------------------------------


def test_the_service_sweep_agrees_with_the_module_level_sweep() -> None:
    # One answer to "is this deployment pinned?": the service delegates
    # to the same sweep a caller would run by hand, so the two can
    # never disagree about the same declaration.
    env = {"NULLIUS_EVALUATOR_IMAGE": PINNED_EVALUATOR_IMAGE}
    assert CanaryService(env=env).containers == pin_containers(
        {"evaluator": PINNED_EVALUATOR_IMAGE}
    )


# -- Feature 136: the library lock, carried beside the pin sweep ----------------


def test_the_service_resolves_the_library_lock() -> None:
    # Feature 136 through the composed surface: the lock resolves to the
    # default when the deployment declared nothing, the same way the
    # container sweep resolves to the declared image.
    service = CanaryService()
    assert service.lockfile.names == lockfile_from_env({}).names


def test_the_service_lock_is_cached() -> None:
    # Resolved once: a deployment that re-read its lock mid-run could
    # audit two different library sets on the same night.
    service = CanaryService()
    assert service.lockfile is service.lockfile


def test_the_service_lock_refuses_a_version_pin_on_first_use() -> None:
    # The refusal lands at the first call that asks whether the
    # deployment's libraries are pinned — a version is a mutable pointer,
    # and a mutable pointer is not a pin.
    service = CanaryService(env={"NULLIUS_LIBRARY_LOCKFILE": "numpy==2.1.3"})
    with pytest.raises(CanaryLockfileError, match="mutable pointer"):
        service.lockfile


def test_the_service_lock_reads_the_environment_it_is_built_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The lock is read per-service at first use, so a deployment that
    # re-pins a library constructs a new service rather than the old one
    # quietly changing its mind mid-run.
    first = CanaryService(env={"NULLIUS_LIBRARY_LOCKFILE": f"numpy@sha256:{'a1' * 32}"})
    monkeypatch.setenv("NULLIUS_LIBRARY_LOCKFILE", f"numpy@sha256:{'cd' * 32}")
    second = CanaryService()
    assert first.lockfile.digests["numpy"] == "sha256:" + "a1" * 32
    assert second.lockfile.digests["numpy"] == "sha256:" + "cd" * 32


def test_the_service_lock_agrees_with_the_module_level_resolution() -> None:
    # One answer to "are this deployment's libraries pinned?": the
    # service delegates to the same resolution a caller would run by
    # hand, so the two can never disagree about the same declaration.
    env = {"NULLIUS_LIBRARY_LOCKFILE": f"numpy@sha256:{'a1' * 32}"}
    assert CanaryService(env=env).lockfile == lockfile_from_env(env)
