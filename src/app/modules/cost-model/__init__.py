"""The cost-model module — app-level entrypoint for the cost-model workspace member.

The implementation lives in the ``cost-model`` workspace member
(``packages/cost-model``, import name ``cost_model``), which self-registers
with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its
``@register`` decorator fires, and ``create_app()`` builds a
:class:`~cost_model.service.CostModelService` bound to
``NULLIUS_COST_MODEL_PATH`` and ``DATABASE_URL`` (feature 59: the resolved
cost model version string and its venue, persisted after loading the YAML
configuration; feature 60: the ``cost_model_hash`` computed over that same
loaded configuration, so every score names its fee assumptions).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/cost-model/``): it exposes the composed component
without making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the
factory for the component, and a module that cannot reach it (member not
scanned, workspace empty) returns ``None`` rather than failing import,
mirroring the factory's own "degrade, don't break" stance toward absent
components.

Like the feature-store seat, this directory's name carries a hyphen and so
is not a valid dotted import path; it is reached the way the factory
reaches such a package — ``importlib.import_module("app.modules.cost-model")``.

The seat answers exactly one question — *what is the composed cost model
service?* — and does not re-export the loading, the persistence or the
resolved value: a caller who has the service can reach
``service.resolved()`` for feature 59's load-then-persist, ``service.load()``
for the configuration alone, ``service.cost_model_hash()`` for feature 60's
stamp over the loaded configuration and ``service.persisted(venue, version)``
for the read-back, and a second spelling of those APIs here would be a second
thing to keep in sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from cost_model import CostModelService

__all__ = ["COMPONENT_NAME", "cost_model_component"]

#: The component name the cost-model member registers under.  Kept here so
#: anything asking the composed application for the cost model — by way of
#: the app package, not the member — shares one spelling.
COMPONENT_NAME = "cost-model"


def cost_model_component(app: Application | None = None) -> CostModelService | Any:
    """Return the composed cost model component (the shared cost library's service).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``cost-model`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as
    an empty workspace is for the factory.

    Construction touches no file and no database: asking for the component
    is always safe, and the document is read at the first ``resolved()`` or
    ``load()``.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
