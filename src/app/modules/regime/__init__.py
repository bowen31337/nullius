"""The regime coverage ledger's seat in the ``app`` package namespace — feature 283.

app_spec.xml, "Regime Coverage Strata", feature 283: *System persists a
regime_coverage count per stratum such as high-volatility trend,
low-volatility chop and crash.*  The store that persists those counts
lives in :mod:`regime.coverage`; this module is how the app package
reaches the composed store without importing the member at module scope.

Feature 232's campaign seat (:mod:`app.modules.discovery`) answers *what
is the composed campaign store?*; feature 188's pool seat
(:mod:`app.modules.bootstrap.pool`) answers *what is the composed replay
pool?*; this one answers the same shape of question for the regime
member's first and only component: *what is the composed coverage
ledger?*  The category's later features reach the same store through
this seat rather than through a second component — feature 284's
``GET /metrics/regime-coverage`` reads what it holds, feature 285's
promotion block and feature 289's diversity refusal judge counts read
out of it, feature 286's ``empty_stratum`` warning fires on the
named-empty rows it lands, and features 287/288/290's backfill and
labeling write through it — so the one question this module answers is
the one every reader of §C7's ledger starts from.

**The seat's ``None`` is about the deployment, not about the member.**
``None`` means *nothing named a database* — ``DATABASE_URL`` is unset, so
there is no table for a coverage row to land in.  It does **not** mean
the member was not scanned (that would be a different fact, and it would
have left no component registered at all), and it is not a store that
happens to hold no rows: an empty ledger answers *this stratum holds
zero worlds* about every name it was asked for, while this ``None`` says
there is nowhere a count could have been persisted.  §C7's ledger is the
one named remedy for a regime-monotone replay pool, and the promotion
gate that will block on it reads these rows under time pressure — so a
caller that must read coverage (or persist it) has to treat this
``None`` as a refusal to proceed rather than as an empty ledger,
exactly as the campaign seat's ``None`` is a refusal to plan.

**Composition stays the factory's job.**  This module asks the factory
for the component and answers ``None`` — not an exception — when there
is none, mirroring the factory's own "degrade, don't break" stance
toward absent components.  It deliberately does **not** re-export
``CoverageCount``, ``DEFAULT_STRATA`` or the module-level
:func:`regime.coverage.persist_coverage`: a caller who has the store
reaches ``record()``, ``name_stratum()`` and ``get()`` on it, and a
second spelling here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed coverage ledger?*

**Construction touches no database.**  The store resolves its path on
first use and opens nothing until an operation needs it, so asking for
the component is always safe — the same promise the member's own builder
makes — and the first :meth:`~regime.coverage.RegimeCoverage.record` is
where a coverage row is written.  Composing an application never
persists a count, and it must not: the count is a fact about the pool,
written when the census or the backfill counts it, by the caller that
holds the number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from regime import RegimeCoverage

__all__ = ["COMPONENT_NAME", "regime_coverage_component"]

#: The component name the regime member registers its coverage ledger
#: under.  Kept here as well as in the member — every seat in this
#: workspace spells its own name twice for the same reason — so the two
#: cannot drift apart silently, and the member's component suite asserts
#: they agree.  Unprefixed, following the ``ledger`` / ``artifacts`` /
#: ``canary`` / ``discovery`` precedent for a member's first and only
#: component: the prefix families (``nulloracle-*``, ``tripwires-*``)
#: exist to disambiguate many components inside one member, and this
#: member has one.  ``regime`` sorts after ``providers`` and before the
#: feature-store member's ``regime-labeler``, clear of both, so every
#: existing adjacency assertion over the name-sorted ``app.order`` is
#: untouched.
COMPONENT_NAME = "regime"


def regime_coverage_component(app: Application | None = None) -> RegimeCoverage | Any:
    """Return the composed coverage ledger (feature 283's store).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``regime`` component is registered — either
    because the member was not scanned, or because its builder found no
    ``DATABASE_URL`` to resolve.

    That ``None`` is a statement about the deployment, and the caller
    that must read or persist coverage has to read it as one.  There is
    deliberately no fallback here that opens a default database or
    fabricates a store: a coverage row written into a database nobody
    named would be invisible to the endpoint, the promotion block and the
    diversity gate that read it — §C7's ledger exists to make the pool's
    skew *visible*, and a sensible default is precisely the way to make
    it silently not that.  A process that needs the act passes a URL to
    :class:`~regime.coverage.RegimeCoverage` directly (or calls
    :func:`~regime.coverage.persist_coverage`), where a named
    :class:`~regime.errors.CoverageError` is the right answer rather than
    a ``None``.

    The store the component returns is only useful once a caller asks it
    to persist something: reading the component opens no database, so a
    composed application that never persists a count never touches disk.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
