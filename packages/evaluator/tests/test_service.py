"""The composed evaluator service (app_spec.xml feature 70).

The service is where the feature's two verbs are joined: ``record()``
computes the identity and persists it in one call. Most of what these tests
guard is not the happy path but the *lazy* resolution the application
factory depends on.

That dependency is easy to miss and expensive to get wrong. The factory
builds every registered component on every ``create_app()`` — in a bare test
process, in a factory scan, and on the replay path, which architecture §1
forbids from reaching the evaluator at all ("Replay must never invoke the
evaluator"). So the builder must construct a service without a pinned image
and without a database. An eager refusal would take down composition for
every unrelated feature in the workspace, which is exactly the coupling the
factory's one-way dependency exists to prevent.

But the refusal itself is the feature (canary feature 135: "rejects a
tag-only reference"), so it has to happen *somewhere* — at the first call
that needs the image, or at construction for a caller that asks for the
check with ``strict=True``. Both spellings are pinned below, because the
tempting "fix" for a lazy refusal is an eager one, and an eager one breaks
composition.
"""

from __future__ import annotations

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    OTHER_PINNED_DIGEST,
    OTHER_PINNED_IMAGE,
    PINNED_DIGEST,
    PINNED_IMAGE,
)

from evaluator import (
    DEFAULT_CONFIG,
    ENV_CONFIG,
    EvaluatorConfigError,
    EvaluatorImageError,
    EvaluatorService,
    EvaluatorStoreError,
    build_evaluator_service,
)


# -- The composed component survives composition -----------------------------


def test_the_service_is_constructible_without_an_image_or_a_store() -> None:
    # The factory's contract. This is not a degenerate case to be tightened
    # later; it is what keeps create_app() working for every other feature.
    service = build_evaluator_service({})
    assert isinstance(service, EvaluatorService)
    assert "unresolved" in repr(service)


def test_composition_does_not_touch_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Composition-time work must perform no I/O: the factory builds this
    # component in any environment, including a bare scan.
    target = tmp_path / "never-created" / "evaluator.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target}")
    service = build_evaluator_service({})
    assert not target.parent.exists()
    assert service is not None


def test_the_env_mapping_is_honoured_for_both_terms(
    evaluator_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A service handed an explicit mapping must read *both* the image and the
    # store from it. A seam that read one from the mapping and the other from
    # the process would pass alone and fail in a suite.
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", "ghcr.io/other/wrong@sha256:" + "99" * 32)
    service = EvaluatorService.from_env(evaluator_env)
    assert service.image.digest == PINNED_DIGEST


# -- The strict spelling -----------------------------------------------------


def test_strict_refuses_an_unset_image() -> None:
    with pytest.raises(EvaluatorImageError, match="is not set"):
        EvaluatorService.from_env({}, strict=True)


def test_strict_refuses_a_tag_only_image() -> None:
    env = {"NULLIUS_EVALUATOR_IMAGE": "nullius-evaluator:latest"}
    with pytest.raises(EvaluatorImageError, match="not digest-pinned"):
        EvaluatorService.from_env(env, strict=True)


def test_strict_refuses_a_missing_store(evaluator_env: dict[str, str]) -> None:
    env = {k: v for k, v in evaluator_env.items() if k != "DATABASE_URL"}
    with pytest.raises(EvaluatorStoreError, match="not set"):
        EvaluatorService.from_env(env, strict=True)


def test_strict_succeeds_on_a_complete_environment(
    evaluator_env: dict[str, str],
) -> None:
    service = EvaluatorService.from_env(evaluator_env, strict=True)
    assert service.image.digest == PINNED_DIGEST
    assert service.store is not None


# -- The lazy spelling -------------------------------------------------------


def test_a_lazy_service_refuses_at_first_use_not_at_construction() -> None:
    # The same refusal, moved to where it is informative: naming the
    # deployment's own misconfiguration rather than looking like a data-path
    # fault.
    service = build_evaluator_service({})
    with pytest.raises(EvaluatorImageError, match="is not set"):
        service.identity()


def test_a_lazy_service_refuses_a_tag_only_image_at_first_use() -> None:
    service = build_evaluator_service({"NULLIUS_EVALUATOR_IMAGE": "evaluator:latest"})
    with pytest.raises(EvaluatorImageError, match="not digest-pinned"):
        service.identity()


def test_the_store_refusal_names_the_feature(
    evaluator_env: dict[str, str],
) -> None:
    env = {k: v for k, v in evaluator_env.items() if k != "DATABASE_URL"}
    service = build_evaluator_service(env)
    with pytest.raises(EvaluatorStoreError, match="feature 70"):
        service.record()


# -- Recording ---------------------------------------------------------------


def test_record_computes_and_persists_in_one_call(
    evaluator_env: dict[str, str],
) -> None:
    service = EvaluatorService.from_env(evaluator_env)
    identity = service.record()

    assert len(identity.evaluator_hash) == 64
    assert identity.image_digest == PINNED_DIGEST
    # Persisted: the same hash resolves to a row.
    assert service.recorded().evaluator_hash == identity.evaluator_hash


def test_record_is_idempotent(evaluator_env: dict[str, str]) -> None:
    # What makes it safe to call on the evaluation path with no "have I done
    # this already?" branch.
    service = EvaluatorService.from_env(evaluator_env)
    first = service.record()
    second = service.record()
    assert first.evaluator_hash == second.evaluator_hash
    assert len(service.recorded_identities()) == 1


def test_recorded_is_none_before_anything_is_recorded(
    evaluator_env: dict[str, str],
) -> None:
    service = EvaluatorService.from_env(evaluator_env)
    assert service.recorded() is None


def test_identity_computes_without_persisting(evaluator_env: dict[str, str]) -> None:
    # The hash-only question: comparing an incoming score's provenance, or
    # rendering a report, must not write a row.
    service = EvaluatorService.from_env(evaluator_env)
    identity = service.identity()
    assert identity.evaluator_hash
    assert service.recorded() is None


def test_the_service_reports_every_recorded_evaluator(
    evaluator_env: dict[str, str],
) -> None:
    first = EvaluatorService.from_env(evaluator_env)
    first.record()

    moved = dict(evaluator_env, NULLIUS_EVALUATOR_IMAGE=OTHER_PINNED_IMAGE)
    EvaluatorService.from_env(moved).record()

    identities = first.recorded_identities()
    assert {identity.image_digest for identity in identities} == {
        PINNED_DIGEST,
        OTHER_PINNED_DIGEST,
    }


def test_an_ad_hoc_config_is_layered_over_the_service_config(
    evaluator_env: dict[str, str],
) -> None:
    # An ad-hoc run with one setting changed must not disturb the service's
    # own configuration — the identity it records is still the deployment's.
    service = EvaluatorService.from_env(evaluator_env)
    ad_hoc = service.identity({"purge_periods": 3})
    assert ad_hoc.config["purge_periods"] == 3
    assert service.identity().config["purge_periods"] == DEFAULT_CONFIG["purge_periods"]


# -- The environment's configuration -----------------------------------------


def test_the_operator_override_is_read_from_the_environment() -> None:
    env = {
        "NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE,
        ENV_CONFIG: '{"purge_periods": 4}',
    }
    service = EvaluatorService.from_env(env)
    assert service.resolved_config()["purge_periods"] == 4


def test_the_operator_override_merges_over_the_defaults() -> None:
    # The override is layered over the defaults, not swapped in for them: a
    # setting the operator does not mention keeps its default.
    env = {
        "NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE,
        ENV_CONFIG: '{"purge_periods": 4}',
    }
    resolved = EvaluatorService.from_env(env).resolved_config()
    assert resolved["purge_periods"] == 4
    assert resolved["horizons"] == DEFAULT_CONFIG["horizons"]


def test_the_operator_override_changes_the_identity() -> None:
    # The reason the override is folded rather than applied afterwards: a
    # deployment that changes a knob has a different evaluator, and §15
    # treats exactly that as an evaluator change.
    base = EvaluatorService.from_env({"NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE})
    overridden = EvaluatorService.from_env(
        {
            "NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE,
            ENV_CONFIG: '{"purge_periods": 4}',
        }
    )
    assert base.identity().evaluator_hash != overridden.identity().evaluator_hash


def test_a_malformed_override_does_not_break_composition() -> None:
    # The same laziness argument as the image and the store, and the one with
    # the widest blast radius: create_app() calls every registered builder, so
    # an eager parse here would take composition down for every unrelated
    # feature in the workspace because one member's override was mistyped.
    service = build_evaluator_service(
        {"NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE, ENV_CONFIG: "{not json"}
    )
    assert isinstance(service, EvaluatorService)


def test_a_malformed_override_is_refused_at_first_use() -> None:
    service = build_evaluator_service(
        {"NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE, ENV_CONFIG: "{not json"}
    )
    with pytest.raises(EvaluatorConfigError, match="not valid JSON"):
        service.identity()


def test_an_override_that_is_not_an_object_is_refused() -> None:
    service = build_evaluator_service(
        {"NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE, ENV_CONFIG: "[1, 2]"}
    )
    with pytest.raises(EvaluatorConfigError, match="must be a JSON object"):
        service.resolved_config()


def test_strict_refuses_a_malformed_override_at_construction(
    evaluator_env: dict[str, str],
) -> None:
    # Everything else complete, so the *only* thing wrong is the override —
    # otherwise the store refusal would fire first and this would pass for
    # the wrong reason.
    env = dict(evaluator_env, **{ENV_CONFIG: "{not json"})
    with pytest.raises(EvaluatorConfigError, match="not valid JSON"):
        EvaluatorService.from_env(env, strict=True)


def test_the_environment_override_beats_an_explicit_override() -> None:
    # The deployment's environment states what the process is actually
    # pointed at, so it must not be silently beaten by a value captured
    # somewhere else.
    from evaluator import EvaluatorConfig

    config = EvaluatorConfig(
        overrides={"purge_periods": 1},
        env={ENV_CONFIG: '{"purge_periods": 9}'},
    )
    assert config.resolved()["purge_periods"] == 9
    assert EvaluatorConfig(overrides={"purge_periods": 1}, env={}).resolved()[
        "purge_periods"
    ] == 1
