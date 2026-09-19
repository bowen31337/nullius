"""The evaluator module — app-level entrypoint for the evaluator workspace member.

The implementation lives in the ``evaluator`` workspace member
(``packages/evaluator``, import name ``evaluator``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME` —
scanning the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` builds an :class:`~evaluator.EvaluatorService` bound to the
image ``NULLIUS_EVALUATOR_IMAGE`` names and the store ``DATABASE_URL`` names.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/evaluator/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

One thing to be careful about, because this seat differs from its siblings:
the composed evaluator service is *lazily* configured. The factory builds
every registered component on every ``create_app()``, so a builder that
insisted on a pinned image and a database would take composition down for
every unrelated feature in a bare test process — which is why
:func:`~evaluator.build_evaluator_service` constructs a service that
resolves both on first use. The consequence for this seat is that a
non-``None`` component is not by itself proof the environment is complete:
``service.identity()`` and ``service.record()`` raise
:class:`~evaluator.EvaluatorImageError` or
:class:`~evaluator.EvaluatorStoreError` when ``NULLIUS_EVALUATOR_IMAGE`` or
``DATABASE_URL`` is missing, and those refusals are the feature rather than
a defect — a tag-only image must never be accepted (canary feature 135), and
"persists" needs somewhere to persist to. A caller that wants the check at
startup instead builds strictly:
``EvaluatorService.from_env(strict=True)``.

This seat answers exactly one question — *what is the composed evaluator
component?* — and does not re-export the identity surface: a caller who has
the service can reach ``service.record()`` for feature 70's compute-and-
persist, ``service.identity()`` for the hash without the write, and
``service.image`` / ``service.resolved_config()`` for the two terms, and a
second spelling of those APIs here would be a second thing to keep in sync.
The identity vocabulary itself (``evaluator_digest``, ``EvaluatorIdentity``,
``normalize_evaluator_hash``) is imported from the member, which is where
the formula lives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from evaluator import EvaluatorService

__all__ = ["COMPONENT_NAME", "evaluator_component"]

#: The component name the evaluator member registers under. Kept here so
#: anything asking the composed application for the evaluator component — by
#: way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "evaluator"


def evaluator_component(app: Application | None = None) -> EvaluatorService | Any:
    """Return the composed evaluator component (the identity service).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``evaluator`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory. A returned service may still be missing its
    image or its store: see the module docstring on why that refusal is
    deferred to first use rather than raised here.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
