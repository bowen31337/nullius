"""The ledger module — app-level entrypoint for the ledger workspace member.

The implementation lives in the ``ledger`` workspace member
(``packages/ledger``, import name ``ledger``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME`
— scanning the workspace imports it, its ``@register`` decorator fires,
and ``create_app()`` builds a :class:`~ledger.store.TrialLedger` bound
to the database ``DATABASE_URL`` names (feature 86: one trial_ledger row
per evaluation under a monotonically increasing sequence number).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/ledger/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the
factory for the component, and a module that cannot reach it (member
not scanned, no ``DATABASE_URL`` configured) returns ``None`` rather
than failing import, mirroring the factory's own "degrade, don't break"
stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing
more.  It does not re-export the append or the read paths: a caller who
has the ledger can reach ``ledger.append(node_id, campaign_id)`` for the
debit of feature 86 and ``ledger.rows()`` for the ordered read, and a
second spelling of those APIs here would be a second thing to keep in
sync.  This module answers exactly one question — *what is the composed
ledger component?* — so the evaluator-facing features of this category
can ask it without importing the member directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from ledger import TrialLedger

__all__ = ["COMPONENT_NAME", "ledger_component"]

#: The component name the ledger member registers under.  Kept here so
#: anything asking the composed application for the trial ledger — by way
#: of the app package, not the member — shares one spelling.
COMPONENT_NAME = "ledger"


def ledger_component(app: Application | None = None) -> "TrialLedger | Any":
    """Return the composed ledger component (the append-only trial ledger).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``ledger`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory and an
    unset ``DATABASE_URL`` is for the member's own builder.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
