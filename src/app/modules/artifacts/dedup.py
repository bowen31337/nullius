"""The dedup gate's seat in the ``app`` package namespace — feature 179.

app_spec.xml, "Tree & Artifact Persistence", feature 179: *System
deduplicates a proposed node against stored ``code_hash`` values, which
rejects an exact duplicate before it charges a trial.*  The comparison, the
probe and the reservation live in :mod:`artifacts._dedup`, and this module
is how the ``app`` package reaches the composed gate without importing the
member at module scope.

**A second seat, beside feature 169's.**  ``src/app/modules/artifacts/``
was a single ``__init__.py`` while the member contributed one component.
It now contributes two — the artifact directory store and this gate — and
they are different things on different lifecycles: the store is bound to a
filesystem root (``ARTIFACT_ROOT``), the gate to the relational store
(``DATABASE_URL``), and a deployment configured for one and not the other
composes one and not the other.  So the gate gets its own module beside
:mod:`app.modules.artifacts` rather than a second accessor crowded into it.
Feature 169's seat is untouched: a caller that only wants the store never
imports this file.

**The seat whose component may legitimately be ``None``.**  Feature 169's
builder always resolves a root — it falls back to ``artifacts/`` beside the
workspace root and refuses only when no root can be named at all — because
composition must carry a store everywhere.  This one's builder answers
``None`` for a deployment with no ``DATABASE_URL``, the stance the null
oracle's seats take for their stores: there is no tree to deduplicate
against, so there is no gate, and a discoverable absence beats an exception
that would take composition down for every unrelated member.

**Where the composed gate is ``None``, that is a statement about the
deployment, not a verdict.**  A caller must not read it as *"no duplicates
exist"* — those are different facts, and the difference is the whole of the
feature: an ungated proposal path and a clean tree look identical until a
repeat is proposed.  The caller that must not find itself holding ``None``
is the proposal path that is about to charge a trial.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none.
It deliberately does **not** re-export the comparison or the gate's
spellings: a caller who has the gate reaches ``gate.holders(...)``,
``gate.check(...)`` and ``gate.probe(...)`` on it, while a caller who only
has a collection of stored hashes reaches ``artifacts.reject_duplicate``
directly — the half of the feature that needs no store at all — and a
second spelling here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed dedup gate?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from artifacts import CodeHashIndex

__all__ = ["COMPONENT_NAME", "code_hash_dedup_component"]

#: The component name the artifacts member registers its dedup gate under.
#: Kept here as well as in the member — feature 169's seat spells its own
#: name twice for the same reason — so the two cannot drift apart silently,
#: and a test can assert they agree.
COMPONENT_NAME = "artifacts-code-hash-dedup"


def code_hash_dedup_component(
    app: Application | None = None,
) -> CodeHashIndex | Any:
    """Return the composed dedup gate (feature 179's pre-trial check).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``artifacts-code-hash-dedup`` component is
    registered — which is both the absent-member case and the
    no-``DATABASE_URL`` case, since the member's builder answers ``None``
    for the latter rather than raising.  An absent component is a
    discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no disk: the gate resolves its path on first use,
    so asking for the component is always safe.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
