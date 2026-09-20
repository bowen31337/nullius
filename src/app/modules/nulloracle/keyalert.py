"""The alert journal's seat in the ``app`` package namespace — feature 111.

app_spec.xml, "Null Oracle & Planted Nulls", feature 111: *System resolves the
sidecar decryption key from KMS or sops, which emits an unrecoverable_state
alert when decryption fails.*  The backends live in :mod:`nulloracle.backends`
and the alert in :mod:`nulloracle.keyalert`; this module is how the app package
reaches the composed journal without importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the composed
null sidecar?*, feature 123's (:mod:`app.modules.nulloracle.ksguard`) answers
*what is the composed guard journal?*, and this one answers the same shape of
question for the member's eleventh component: *what is the composed alert
journal?*

**A seat beside the others, not a fold into one.**  ``src/app/modules/
nulloracle/`` was a single ``__init__.py`` while the member contributed one
component; it now carries eleven, and §7's *Unrecoverable* row is a different
thing on a different lifecycle from §7.1's sealed file and from feature 123's
store — a deployment can hold the sidecar without ever writing an alert, and a
monitor sweeping for the state holds the journal without holding the labels.  A
caller that only wants the sidecar or the guard never imports this file, and the
older seats' promises are untouched: ``app.modules.nulloracle`` still exports
exactly :data:`COMPONENT_NAME` and :func:`null_sidecar_component`.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the record, the error, the
backends or the emission helpers: a caller who needs to emit an alert imports
:mod:`nulloracle` directly — resolution is a startup act, not a composition
read — and a second spelling here would be a second thing to keep in sync.  The
one question this module answers is *what is the composed alert journal?*

Where the composed journal is ``None``, that is a statement about the
deployment, not an error: nothing named ``DATABASE_URL``, so there is no
relational store to compose.  A caller that needs one must not read ``None`` as
*this deployment has never failed to decrypt* — those are different facts, and
§7's row is precisely the one that must not be mistaken for the quiet one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import KeyAlertJournal

__all__ = ["COMPONENT_NAME", "key_alert_component"]

#: The component name the nulloracle member registers its alert journal under.
#: Kept here as well as in the member — the other seats spell their own
#: :data:`COMPONENT_NAME` twice for the same reason — so the two cannot drift
#: apart silently, and ``test_key_alert_component.py`` asserts they agree.
COMPONENT_NAME = "nulloracle-sidecar-key-alert"


def key_alert_component(app: Application | None = None) -> KeyAlertJournal | Any:
    """Return the composed alert journal (feature 111's journal).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-sidecar-key-alert`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the journal resolves its path on first
    use, so asking for the component is always safe and the first
    ``record()`` or ``latest()`` is where the file is actually opened.  Note
    that the *alert itself* does not need this component: a deployment whose
    database is broken still emits ``unrecoverable_state``, because
    :func:`nulloracle.emit_unrecoverable_state` works with no journal at all.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
