"""The nulloracle module — app-level entrypoint for the nulloracle workspace member.

The implementation lives in the ``nulloracle`` workspace member
(``packages/nulloracle``, import name ``nulloracle``), which self-registers
with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its
``@register`` decorator fires, and ``create_app()`` builds a
:class:`~nulloracle.sidecar.NullSidecar` bound to the sidecar location and
key the process is pointed at (feature 109: null assignments persisted in
an AES-GCM encrypted sidecar file readable by exactly one service account).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/nulloracle/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
nothing naming a sidecar location) returns ``None`` rather than failing
import, mirroring the factory's own "degrade, don't break" stance toward
absent components.

The helpers below are deliberately the *composition* accessors and nothing
more.  They do not re-export the seal, the open or the schema: a caller who
has the sidecar can reach ``sidecar.write(assignments)`` to seal a whole
assignment map and ``sidecar.open()`` to read it back, ``sidecar.assignment(
node_id)`` for one node's entry — the read §7.2's resolution path takes —
and ``sidecar.path`` for the file's location, and a second spelling of those
APIs here would be a second thing to keep in sync.  This module answers
exactly one question — *what is the composed null sidecar?* — so the
features in this category that need the labels (the ``POST /target``
resolution of 112-114, the campaign assignment of 117-122, the KS guard of
123) can ask it without importing the member directly.

Where the composed sidecar is ``None``, that is a statement about the
deployment, not an error: nothing named ``NULL_SIDECAR_PATH``, ``LAKE_ROOT``
or a workspace root to locate the file, so there is no sidecar to compose.
A caller that needs one must not treat ``None`` as "no nulls were assigned" —
those are different facts, and the member's own error taxonomy is built
around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import NullSidecar

__all__ = ["COMPONENT_NAME", "null_sidecar_component"]

#: The component name the nulloracle member registers under.  Kept here so
#: anything asking the composed application for the sidecar — by way of the
#: app package, not the member — shares one spelling.
COMPONENT_NAME = "nulloracle"


def null_sidecar_component(app: Application | None = None) -> NullSidecar | Any:
    """Return the composed null sidecar (§7.1's encrypted sidecar file).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``nulloracle`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory and an unset ``NULL_SIDECAR_PATH`` is
    for the member's own builder.

    Construction touches no file: asking for the component is always safe,
    and the sidecar is written at the first ``write()`` and read at the first
    ``open()``.  That laziness is the reason a composed application can carry
    this component in a process that is not the one service account — holding
    the handle opens nothing, and the read that would open it is where §7.1's
    permission rule bites.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
