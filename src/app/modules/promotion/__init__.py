"""The promotion registry's seat in the ``app`` package namespace — feature 291.

app_spec.xml, "Promotion & Epoch Governance", feature 291: *System exposes
POST /promotion/pre-register, which returns a criteria hash recorded before
the deciding evaluation runs.*  The store that records those hashes lives in
:mod:`promotion.pre_register`; this module is how the app package reaches the
composed store without importing the member at module scope.

Feature 232's campaign seat (:mod:`app.modules.discovery`) answers *what is
the composed campaign store?*; feature 283's coverage seat
(:mod:`app.modules.regime`) answers *what is the composed coverage ledger?*;
this one answers the same shape of question for the promotion member's first
and only component: *what is the composed pre-registration registry?*  The
category's later features reach the same store through this seat rather than
through a second component — feature 292's ``criteria_mismatch`` verdict
compares a promotion against the hash a caller read out of it, feature 293's
decision closes the row it opened, features 295-297's exhaustion machinery
reads the ``epoch_ledger`` column the decision advanced, and feature 360's CI
invariant reads the two timestamps of the row itself — so the one question
this module answers is the one every reader of §13 item 7's record starts
from.

**The route is not a second component, and that is the decision this seat
records.**  ``POST /promotion/pre-register`` is the member's one endpoint,
and it is deliberately *not* registered: the ledger member registers
``ledger-debit`` beside its store, but that endpoint's object graph is a
ledger plus nothing, whereas this endpoint holds no state at all — it is a
thin seam over :meth:`~promotion.pre_register.PreRegistrations.pre_register`
that a caller can build from the store at any moment with
:meth:`~promotion.pre_register.PreRegisterEndpoint.from_env`.  Composing it
would put two entries in ``app.order`` pointing at one database and give a
deployment two things to keep consistent; the store is the state, and the
endpoint is a function of it.  A caller that wants the route asks this seat
for the registry and constructs the endpoint, or calls
``PreRegisterEndpoint.from_env()`` directly, which resolves the *same*
``DATABASE_URL`` this seat's component was built from.

**The seat's ``None`` is about the deployment, not about the member.**
``None`` means *nothing named a database* — ``DATABASE_URL`` is unset, so
there is no table for a criteria hash to land in.  It does **not** mean the
member was not scanned (that would be a different fact, and it would have
left no component registered at all), and it is not a registry that happens
to hold no rows: an empty registry answers *this node holds no
pre-registration* about every identity it is asked for, while this ``None``
says there is nowhere a hash could have been recorded.  §13 item 7 leaves
nothing to fall back on — criteria recorded nowhere are criteria the deciding
evaluation is not measured against — so a caller that must pre-register has
to treat this ``None`` as a refusal to proceed rather than as an empty
registry, exactly as the campaign seat's ``None`` is a refusal to plan.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export
:class:`~promotion.criteria.PromotionCriteria`,
:func:`~promotion.criteria.criteria_hash` or
:data:`~promotion.pre_register.PRE_REGISTER_ROUTE`: a caller who has the
store reaches ``pre_register()`` on it, and a second spelling here would be a
second thing to keep in sync.  The one question this module answers is *what
is the composed pre-registration registry?*

**Construction touches no database.**  The store resolves its path on first
use and opens nothing until an operation needs it, so asking for the
component is always safe — the same promise the member's own builder makes —
and the first :meth:`~promotion.pre_register.PreRegistrations.pre_register`
is where the schema is brought up and the row is written.  Composing an
application never records a pre-registration, and it must not: the row is a
fact about a hypothesis, written when a caller asks for its criteria to be
fixed, before the evaluation that decides it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from promotion import PreRegistrations

__all__ = ["COMPONENT_NAME", "promotion_registry_component"]

#: The component name the promotion member registers its pre-registration
#: registry under.  Kept here as well as in the member — every seat in this
#: workspace spells its own name twice for the same reason — so the two
#: cannot drift apart silently, and the member's component suite asserts they
#: agree.  Unprefixed, following the ``ledger`` / ``artifacts`` / ``canary``
#: / ``discovery`` / ``regime`` precedent for a member's first and only
#: component: the prefix families (``nulloracle-*``, ``tripwires-*``) exist
#: to disambiguate many components inside one member, and this member has
#: one.  ``promotion`` sorts after ``policy-runtime`` and before
#: ``providers`` — those are the two names it lands between in the composed
#: application's name-sorted ``app.order``, verified against the composed
#: order rather than guessed at — so every existing adjacency assertion there
#: is untouched.
COMPONENT_NAME = "promotion"


def promotion_registry_component(
    app: Application | None = None,
) -> PreRegistrations | Any:
    """Return the composed pre-registration registry (feature 291's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``promotion`` component is registered — either
    because the member was not scanned, or because its builder found no
    ``DATABASE_URL`` to resolve.

    That ``None`` is a statement about the deployment, and the caller that
    must record a criteria hash has to read it as one.  There is deliberately
    no fallback here that opens a default database or fabricates a store: a
    pre-registration written into a database nobody named would be invisible
    to the deciding evaluation, to feature 292's comparison and to feature
    360's CI invariant — §13 item 7's whole promise is that the record is
    what the decision is checked against, and a sensible default is precisely
    the way to make it silently not that.  A process that needs the act
    passes a URL to :class:`~promotion.pre_register.PreRegistrations`
    directly, where a named
    :class:`~promotion.errors.PromotionStoreError` is the right answer rather
    than a ``None``.

    The store the component returns is only useful once a caller asks it to
    record something: reading the component opens no database, so a composed
    application that never pre-registers a promotion never touches disk.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
