"""The forward records' seat in the ``app`` package namespace — feature 332.

app_spec.xml, "Forward-Test Tracking", feature 332: *System exposes POST
/forward/promote, which creates a forward_record carrying the promotion
timestamp.*  The store that opens those records lives in
:mod:`forward.record`; this module is how the app package reaches the composed
store without importing the member at module scope.

Feature 291's promotion seat (:mod:`app.modules.promotion`) answers *what is
the composed pre-registration registry?*; feature 283's coverage seat
(:mod:`app.modules.regime`) and feature 232's campaign seat
(:mod:`app.modules.discovery`) answer the same shape of question for their own
members.  This one answers it for the forward member's first and only
component: *what is the composed forward-record store?*  The category's later
features reach the same store through this seat rather than through a second
component — feature 334's ``GET /forward/decay`` reads the curve from the rows
it holds, feature 337's retention ratio divides two of them, and feature 340's
reconciliations land in the same database beside them, priced per rebalance
(a grain the record's own table does not name, in a table the reconciliation
module authors) — so the one question this module answers is the one every
reader of §5's Loop 3 record starts from.

**The route is not a second component, and that is the decision this seat
records.**  ``POST /forward/promote`` is the member's one endpoint, and it is
deliberately *not* registered: the ledger member registers ``ledger-debit``
beside its store, but that endpoint's object graph is a ledger plus nothing,
whereas this endpoint holds no state at all — it is a thin seam over
:meth:`~forward.record.ForwardRecords.open_record` that a caller can build from
the store at any moment with :meth:`~forward.record.PromoteEndpoint.from_env`.
Composing it would put two entries in ``app.order`` pointing at one database
and give a deployment two things to keep consistent; the store is the state,
and the endpoint is a function of it.  A caller that wants the route asks this
seat for the store and constructs the endpoint, or calls
``PromoteEndpoint.from_env()`` directly, which resolves the *same*
``DATABASE_URL`` this seat's component was built from.

**The seat's ``None`` is about the deployment, not about the member.**  ``None``
means *nothing named a database* — ``DATABASE_URL`` is unset, so there is no
table for a forward record to land in.  It does **not** mean the member was not
scanned (that would be a different fact, and it would have left no component
registered at all), and it is not a store over an empty table: a fresh database
answers *this signal holds no forward record* about every identity it is asked
for, while this ``None`` says there is nowhere a record could have been
written.  §5's loop leaves nothing to fall back on — a promotion whose record
never opened is a signal whose boundary between backtest and out-of-sample was
never drawn, and 0108's own docstring calls a row that lost its promotion
timestamp *"an observation with no vintage"* — so a caller that must open a
record has to treat this ``None`` as a refusal to proceed rather than as a
store that happened to find nothing, exactly as the promotion seat's ``None``
is a refusal to pre-register.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export
:data:`~forward.record.FORWARD_PROMOTE_ROUTE`,
:class:`~forward.record.ForwardRecordRequest` or
:class:`~forward.record.ForwardRecord`: a caller who has the store reaches
``open_record()`` on it, and a second spelling here would be a second thing to
keep in sync.  The one question this module answers is *what is the composed
forward-record store?*

**Construction touches no database and reads no promotion.**  The store
resolves its path on first use and opens nothing until an operation needs it,
and the promotion member is reached for the first time when a record is
actually being opened — so asking for the component is always safe, the same
promise the member's own builder makes.  Composing an application never opens a
forward record, and it must not: the row is a fact about a promotion, written
when a caller asks for the boundary to be drawn, after the deciding evaluation
has run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from forward import ForwardRecords

__all__ = ["COMPONENT_NAME", "forward_records_component"]

#: The component name the forward member registers its record store under.
#: Kept here as well as in the member — every seat in this workspace spells its
#: own name twice for the same reason — so the two cannot drift apart silently,
#: and the member's component suite asserts they agree.  Unprefixed, following
#: the ``ledger`` / ``artifacts`` / ``canary`` / ``discovery`` / ``regime`` /
#: ``promotion`` precedent for a member's first and only component: the prefix
#: families (``nulloracle-*``, ``tripwires-*``, ``sandbox-*``) exist to
#: disambiguate many components inside one member, and this member has one.
#: ``forward`` sorts after ``fixture-store`` and before ``ingest`` — those are
#: the two names it lands between in the composed application's name-sorted
#: ``app.order``, verified against the composed order rather than guessed at —
#: so every existing adjacency assertion there is untouched.
COMPONENT_NAME = "forward"


def forward_records_component(app: Application | None = None) -> ForwardRecords | Any:
    """Return the composed forward-record store (feature 332's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``forward`` component is registered — either
    because the member was not scanned, or because its builder found no
    ``DATABASE_URL`` to resolve.

    That ``None`` is a statement about the deployment, and the caller that must
    open a record has to read it as one.  There is deliberately no fallback
    here that opens a default database or fabricates a store: a forward record
    written into a database nobody named would be invisible to feature 334's
    decay endpoint, to feature 337's retention ratio and to every operator
    auditing which signals are out of sample — §5's whole loop is that the
    record *is* the measurement, and a sensible default is precisely the way to
    make it silently not that.  A process that needs the act passes a URL to
    :class:`~forward.record.ForwardRecords` directly, or calls the
    module-level :func:`~forward.record.forward_record`, where a named
    :class:`~forward.errors.ForwardStoreError` is the right answer rather than
    a ``None``.

    The store the component returns is only useful once a caller asks it to
    open something: reading the component opens no database and reads no
    promotion, so a composed application that never promotes a signal never
    touches disk.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
