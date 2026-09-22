"""The providers module — app-level entrypoint for the providers workspace member.

The implementation lives in the ``providers`` workspace member
(``packages/providers``, import name ``providers``), which self-registers with
the application factory under the component names
:data:`COMPONENT_NAME`, :data:`DEPTH_RUN_WINDOWS_NAME`,
:data:`DEPTH_CACHE_RATES_NAME`, :data:`ROOT_SERVING_PROVIDER_NAME` and
:data:`ROOT_ROTATION_NAME` — scanning the workspace imports it, its
``@register`` decorators fire, and ``create_app()`` composes feature 203's
:class:`~providers.AgentModelPins` store (bound to the
``DATABASE_URL`` the tree store lives at), feature 202's
:class:`~providers.DepthRunWindows` store, feature 200's
:class:`~providers.DepthCacheRates` store, feature 196's
:class:`~providers.RootProviderRotation` store and feature 197's
:class:`~providers.RootRotation` store (each bound to the same URL
the campaign and node tables live at).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/providers/``): it exposes the composed components without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for the
components, and a module that cannot reach one (member not scanned, workspace
empty) returns ``None`` rather than failing import, mirroring the factory's own
"degrade, don't break" stance toward absent components.

The seat answers exactly five questions — *what is the composed
authoring-model pin store?*, *what is the composed depth-run scheduler?*,
*what is the composed cache-rate store?*, *what is the composed
root-serving-provider store?* and *what is the composed root-rotation store?*
— one per
registered component that is a service, and deliberately re-exports none of
those features' records or their error vocabularies.  The distinction is worth
stating plainly here, because this member registers **six** components and
the seat exposes the five that are services: feature 192's provider interface
(``providers``) is a contract and a set of records whose builder contributes
``None``, so there is nothing composed to hand back and a caller holding the
interface imports it from the member directly.  A seat that re-exported
:class:`~providers.ModelPin`, :class:`~providers.PeakPricing`,
:class:`~providers.Provider`, :class:`~providers.RootCallProvider` or
:class:`~providers.RootAssignment` would be
a second spelling of the member's
surface that has to be kept in sync with the first, and it would invite a
caller to reach the *interface* by way of the application, where the only
things the application actually holds are the stores.

The last two questions are the pair's, and the seat keeps them apart on
purpose: *what served this root call* (feature 196's store, the row of
provenance) and *what was this campaign's rotation* (feature 197's store, the
assignment the provenance was supposed to follow) are different facts about
different subjects — one call, one campaign — and a seat that answered both
with one accessor would be handing back whichever happened to be composed.

Like the ``cost-model``, ``feature-store`` and ``signal-agent`` seats, this
directory's name is also a valid dotted import path, so it is reached either as
``importlib.import_module("app.modules.providers")`` (the shape the factory uses
for every seat) or as a plain ``from app.modules.providers import
agent_model_pins_component`` — the way ``app.modules.contract`` and
``app.modules.bootstrap`` are reached.  Both spellings name this module and
nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from providers import (
        AgentModelPins,
        DepthCacheRates,
        DepthRunWindows,
        RootProviderRotation,
        RootRotation,
    )

__all__ = [
    "COMPONENT_NAME",
    "DEPTH_CACHE_RATES_NAME",
    "DEPTH_RUN_WINDOWS_NAME",
    "ROOT_ROTATION_NAME",
    "ROOT_SERVING_PROVIDER_NAME",
    "agent_model_pins_component",
    "depth_cache_rates_component",
    "depth_run_windows_component",
    "root_rotation_component",
    "root_serving_providers_component",
]

#: The component name the providers member registers its pin store under.
#: Kept here so anything asking the composed application for feature 203's
#: store — by way of the app package, not the member — shares one spelling.
#: The two are pinned against each other by the member's own suite rather than
#: by a shared constant, because a constant the seat imports from the member
#: would be the import this seat exists to avoid.
COMPONENT_NAME = "agent-model-pins"

#: The component name the providers member registers feature 202's run-window
#: store under, kept here for the same reason as :data:`COMPONENT_NAME`: one
#: spelling shared with the member, pinned against it by the member's own
#: suite rather than by an import that would defeat the seat.
DEPTH_RUN_WINDOWS_NAME = "depth-run-windows"

#: The component name the providers member registers feature 200's cache-rate
#: store under, kept here for the same reason as :data:`COMPONENT_NAME`: one
#: spelling shared with the member, pinned against it by the member's own
#: suite rather than by an import that would defeat the seat.
DEPTH_CACHE_RATES_NAME = "depth-cache-rates"


def agent_model_pins_component(app: Application | None = None) -> AgentModelPins | Any:
    """Return the composed authoring-model pin store (feature 203's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``agent-model-pins`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory.

    A composed application carries this component as ``None`` whenever nothing
    names a relational store, and **that ``None`` is not the same fact as this
    function's**.  The component's ``None`` says *a store was built and there
    was no ``DATABASE_URL`` to point it at*; this function's says *no
    ``agent-model-pins`` component was registered at all*.  Both are refusals to
    persist — a caller that must record feature 203's triple has to treat either
    as one — but they name different repairs (configure the store, or scan the
    member), so a caller that needs them apart reads the application's
    components rather than this one call.  What this function must never be read
    as is *"this node has no authoring model"*: that is a question about a node,
    and the store answers it.

    Construction touches no file and no database: asking for the component is
    always safe, and the path is resolved at the first ``persist`` or ``load``.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)


def depth_run_windows_component(
    app: Application | None = None,
) -> DepthRunWindows | Any:
    """Return the composed depth-run scheduler (feature 202's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``depth-run-windows`` component is registered —
    the same discoverable-absent state :func:`agent_model_pins_component`
    describes for its own name.

    The two ``None``s this function's callers meet are the two the pin
    seat documents, transposed onto this store: the component's ``None``
    says *a store was built and there was no ``DATABASE_URL`` to point it
    at*, this function's says *no ``depth-run-windows`` component was
    registered at all* — both refusals to schedule, naming different
    repairs (configure the store, or scan the member).  What this function
    must never be read as is *"this campaign's runs are unscheduled"*:
    that is a question about a campaign, and the store answers it — with
    ``None`` from its ``get``, or a refusal naming the campaign.

    Construction touches no file and no database: asking for the component
    is always safe, the path is resolved on first use, and the member-owned
    ``depth_run_window`` table is created by the store's first
    ``schedule`` — never by composing the application.
    """
    application = app if app is not None else create_app()
    return application.get(DEPTH_RUN_WINDOWS_NAME)


def depth_cache_rates_component(
    app: Application | None = None,
) -> DepthCacheRates | Any:
    """Return the composed cache-rate store (feature 200's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``depth-cache-rates`` component is registered —
    the same discoverable-absent state :func:`agent_model_pins_component`
    describes for its own name.

    The two ``None``s this function's callers meet are the two the pin
    seat documents, transposed onto this store: the component's ``None``
    says *a store was built and there was no ``DATABASE_URL`` to point it
    at*, this function's says *no ``depth-cache-rates`` component was
    registered at all* — both refusals to measure, naming different
    repairs (configure the store, or scan the member).  What this function
    must never be read as is *"this campaign's rate was never measured"*:
    that is a question about a campaign, and the store answers it — with
    ``None`` from its ``get``, or a record carrying the two counts the
    rate is the quotient of.

    Construction touches no file and no database: asking for the component
    is always safe, the path is resolved on first use, and the member-owned
    ``depth_cache_rate`` table is created by the store's first
    ``measure`` — never by composing the application.
    """
    application = app if app is not None else create_app()
    return application.get(DEPTH_CACHE_RATES_NAME)

#: The component name the providers member registers feature 196's
#: root-serving-provider store under, kept here for the same reason as
#: :data:`COMPONENT_NAME`: one spelling shared with the member, pinned against
#: it by the member's own suite rather than by an import that would defeat the
#: seat.  *root-serving-provider* and not *root-rotation*: this is the store of
#: **what served** each root call, which is feature 196's fact; what a campaign
#: may rotate across is feature 197's, and the seat should not be the place a
#: reader has to disambiguate the two.
ROOT_SERVING_PROVIDER_NAME = "root-serving-provider"


def root_serving_providers_component(
    app: Application | None = None,
) -> RootProviderRotation | Any:
    """Return the composed root-serving-provider store (feature 196's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``root-serving-provider`` component is registered
    — the same discoverable-absent state :func:`agent_model_pins_component`
    describes for its own name.

    The two ``None``s this function's callers meet are the two the pin
    seat documents, transposed onto this store: the component's ``None``
    says *a store was built and there was no ``DATABASE_URL`` to point it
    at*, this function's says *no ``root-serving-provider`` component was
    registered at all* — both refusals to record, naming different
    repairs (configure the store, or scan the member).  What this function
    must never be read as is *"this root call has no serving provider"*:
    that is a question about a call, and the store answers it — with
    ``None`` from its ``get``, or a refusal naming the node.

    Construction touches no file and no database: asking for the component
    is always safe, the path is resolved on first use, and the member-owned
    ``root_serving_provider`` table is created by the store's first
    ``record`` — never by composing the application, and never by a
    ``get``, which reads ``sqlite_master`` and answers ``None`` rather than
    bringing a schema into being.
    """
    application = app if app is not None else create_app()
    return application.get(ROOT_SERVING_PROVIDER_NAME)


#: The component name the providers member registers feature 197's
#: root-rotation store under, kept here for the same reason as
#: :data:`COMPONENT_NAME`: one spelling shared with the member, pinned against
#: it by the member's own suite rather than by an import that would defeat the
#: seat.  *root-rotation* and not *root-serving-provider*: this is the store of
#: **what was assigned** to each of a campaign's roots, which is feature 197's
#: fact; feature 196's store records **what served** each call, and the member's
#: own constant for that one predicted this name — *"a reader scanning the
#: composed application's keys should be able to tell which of the three it is
#: looking at without opening a docstring."*
ROOT_ROTATION_NAME = "root-rotation"


def root_rotation_component(app: Application | None = None) -> RootRotation | Any:
    """Return the composed root-rotation store (feature 197's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``root-rotation`` component is registered — the
    same discoverable-absent state :func:`agent_model_pins_component` describes
    for its own name.

    The two ``None``s this function's callers meet are the two the pin seat
    documents, transposed onto this store: the component's ``None`` says *a
    store was built and there was no ``DATABASE_URL`` to point it at*, this
    function's says *no ``root-rotation`` component was registered at all* —
    both refusals to assign, naming different repairs (configure the store, or
    scan the member).  What this function must never be read as is *"this
    campaign's roots were never assigned a family"*: that is a question about a
    campaign, and the store answers it — with ``None`` from its ``get``, an
    empty mapping from its ``rotation``, or a refusal naming the campaign.

    Construction touches no file and no database: asking for the component is
    always safe, the path is resolved on first use, and the member-owned
    ``root_provider_rotation`` table is created by the store's first ``assign``
    — never by composing the application, and never by a read, which looks for
    the table and answers ``None``/``{}`` rather than bringing a schema into
    being.
    """
    application = app if app is not None else create_app()
    return application.get(ROOT_ROTATION_NAME)
