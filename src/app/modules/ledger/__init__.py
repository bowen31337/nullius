"""The ledger module — app-level entrypoint for the ledger workspace member.

The implementation lives in the ``ledger`` workspace member
(``packages/ledger``, import name ``ledger``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME`
— scanning the workspace imports it, its ``@register`` decorator fires,
and ``create_app()`` builds a :class:`~ledger.store.TrialLedger` bound
to the database ``DATABASE_URL`` names (feature 86: one trial_ledger row
per evaluation under a monotonically increasing sequence number).  The
member also registers feature 95's endpoint under
:data:`DEBIT_COMPONENT_NAME` — the POST /ledger/debit charge, appending
one trial row idempotently keyed by ``node_id`` and returning the prior
sequence on a retry — over that same store.  Feature 96's per-epoch
promotion-decision counts ride on the store itself, as
``ledger.epoch_usage()``: they read the ``epoch_ledger`` table (feature
105) rather than this member's own, so no second component is needed to
reach them.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/ledger/``): it exposes the composed components without
making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the
factory for the components, and a module that cannot reach them (member
not scanned, no ``DATABASE_URL`` configured) gets ``None`` rather
than failing import, mirroring the factory's own "degrade, don't break"
stance toward absent components.

The helpers below are deliberately the *composition* accessors and
nothing more.  They do not re-export the append or the read paths: a
caller who has the ledger can reach ``ledger.append(node_id,
campaign_id, outcome)`` for the raw debit of feature 86 carrying
feature 91's outcome stamp, ``ledger.rows()`` for the ordered read, and
``ledger.epoch_usage()`` for feature 96's promotion-decision counts per
sequestered epoch — and a second spelling of those APIs here would be a
second thing to keep in sync.  This module answers exactly two questions
— *what is the composed ledger component?* and *what is the composed
debit endpoint?* — so the evaluator-facing features of this category can
ask them without importing the member directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from ledger import DebitEndpoint, TrialLedger

__all__ = [
    "COMPONENT_NAME",
    "DEBIT_COMPONENT_NAME",
    "debit_component",
    "ledger_component",
]

#: The component name the ledger member registers under.  Kept here so
#: anything asking the composed application for the trial ledger — by way
#: of the app package, not the member — shares one spelling.
COMPONENT_NAME = "ledger"

#: The component name the member's debit endpoint registers under
#: (feature 95: POST /ledger/debit, idempotent by ``node_id``).  The same
#: single-spelling rule: the member, the factory's registry and this seat
#: cannot drift apart.
DEBIT_COMPONENT_NAME = "ledger-debit"


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


def debit_component(app: Application | None = None) -> "DebitEndpoint | Any":
    """Return the composed debit endpoint (POST /ledger/debit, feature 95).

    Reads the ``ledger-debit`` component the member registers — the
    idempotent charge over the composed ledger — with the same
    composition rules as :func:`ledger_component`: an explicit
    application is read as given, an absent one is composed first, and a
    composition without the component (member not scanned, no
    ``DATABASE_URL`` configured) returns ``None`` rather than raising.
    """
    application = app if app is not None else create_app()
    return application.get(DEBIT_COMPONENT_NAME)
