"""The tripwires module — app-level entrypoint for the tripwires workspace member.

The implementation lives in the ``tripwires`` workspace member
(``packages/tripwires``, import name ``tripwires``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME` —
scanning the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` composes feature 125's probe, the value the rest of the
"Leakage Tripwires" category (app_spec.xml, ``plugin="tripwires"``) builds on.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/tripwires/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

The component is a *stateless facade* rather than a configured service, and
that is worth naming here because it shapes the seat: feature 125's probe is a
pure function of its inputs, so the composed value needs no store, no lake and
no pinned image, and a caller reaching it through this seat gets a working
probe in any environment — including a bare test process.  The consequence for
a caller is that ``None`` means exactly one thing (no tripwires component was
registered), never "registered but not yet configured": there is no lazy
environment resolution behind this seat, unlike the evaluator's, and so no
deferred refusal to be surprised by on first use.

This seat answers exactly one question — *what is the composed tripwire
component?* — and does not re-export the probe's vocabulary.  The verdict
records, the default seeds and levels, the horizon set and the probes' own names
live in the member, which is where they are pinned; a caller who has the
component calls its verbs — step 10's two probes (feature 125's ``run`` and
feature 126's ``label``), the ``pairing`` and ``threshold`` a reader auditing a
persisted rejection rebuilds from the record's own terms, and the four
perturbation re-runs (features 127 through 130) — and each returns the member's
type.  A second spelling of any of that here would be a second thing to keep in
sync, and the member's one-provenance rule is the reason the category restates
its vocabularies rather than sharing them by import.  This list is illustrative
of the seam and deliberately not exhaustive: the member is where the verbs are
enumerated, and an enumeration kept here as well would go stale the next time
the category adds one.

**The member's other components have their own seats beside this one.**  Feature
131 makes a tripwire failure a fact about the discovery tree, and the store that
persists it arrives as a second component on its own lifecycle
(``"tripwires-poison"``); feature 132 makes the poisoned branch a refusal the
replay pool applies, and the pool arrives as a third (``"tripwires-excise"``).
Each is reached through its own module beside this one —
:mod:`app.modules.tripwires.poison` and :mod:`app.modules.tripwires.excise` —
rather than through a second accessor here.  The split is not tidiness: **this**
seat's ``None`` means exactly one thing (no tripwires component was registered)
because a stateless probe has no unconfigured state, while **those** seats'
``None``\\ s mean nothing named a relational store.  Three accessors in one
module would put three different ``None``\\ s behind one docstring, which is the
kind of ambiguity a caller reading only this file would resolve wrongly and
once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from tripwires import TimeShuffleTripwire

__all__ = ["COMPONENT_NAME", "tripwires_component"]

#: The component name the tripwires member registers under. Kept here so
#: anything asking the composed application for the tripwire component — by
#: way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "tripwires"


def tripwires_component(app: Application | None = None) -> TimeShuffleTripwire | Any:
    """Return the composed tripwire component (feature 125's probe).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``tripwires`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.

    The returned probe is usable immediately: feature 125's tripwire resolves
    nothing from the environment, so — unlike the evaluator's lazily-configured
    service — a non-``None`` component here is proof the probe is ready, and
    the only refusals a caller meets come from the panels they hand it.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
