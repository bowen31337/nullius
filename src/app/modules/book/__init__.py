"""The book combiner's seat in the ``app`` package namespace — feature 301.

app_spec.xml, "Portfolio Book Construction", feature 301: *System combines
promoted signals by information-ratio weighting, which returns a single
composite target score per symbol.*  The combiner that does it lives in the
``book`` workspace member (``packages/book``, import name ``book``); this
module is how the ``app`` package reaches the composed combiner without
importing the member at module scope.

Feature 256's per-world objective seat (:mod:`app.modules.scoring`) answers
*what is the composed objective?*; this one answers the same shape of
question for the book member's combiner: *what is the composed book
combiner?*  The member self-registers with the application factory under the
component name :data:`COMPONENT_NAME`; this module asks the factory for that
component and answers the combiner itself — the callable a caller invokes as
``combine(promoted_signals)`` to turn the promoted signals into a single
composite target score per symbol.

**The seat's ``None`` is about composition, not about the deployment.**
``None`` means *nothing named a book combiner* — the ``book`` member was not
scanned, or the workspace is empty — so there is no combiner composed into
*this* application.  It is not a statement about the deployment — unlike the
store-bound components whose ``None`` means "nothing named a database", this
member's builder cannot fail and reads no environment, so a ``None`` here can
only mean the member itself was absent from the scan.  A caller that needs
the combiner and finds ``None`` must not proceed to rank anything: a
composite computed over an absent combiner is a ranking nothing wrote down,
and the honest move is to refuse loudly at the caller, not to re-derive the
arithmetic beside it.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export :class:`book.PromotedSignal`,
:class:`book.CompositeBook` or :class:`book.BookConstructionError`: a caller
who has the combiner calls it and gets the value, and a second spelling of
the member's surface here would be a second thing to keep in sync — the
discipline every seat in this workspace states, and the reason the member's
suite pins this module to exactly two names.  A caller that wants the value
types or the refusal vocabulary reaches the member's own namespace.

**Construction touches no signals.**  The combiner is a pure function of the
signals it is handed; asking for the component is always safe, and combining
begins at the call, not the composition.  Composing an application never
weights a signal, and it must not: the composite is a fact about the
promoted signals, formed when the caller that holds them calls the combiner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from collections.abc import Callable

    from book import CompositeBook

    #: The combiner's callable shape, for the annotation only — the member's
    #: own docstring is the authoritative spelling of the seam.
    Combiner = Callable[..., CompositeBook]

__all__ = ["COMPONENT_NAME", "book_combiner_component"]

#: The component name the book member registers under.  Kept here so
#: anything asking the composed application for the book combiner — by way
#: of the app package, not the member — shares one spelling, and so the
#: seat, the member and the spec's ``plugin="book"`` cannot drift apart
#: silently; the member's suite asserts the two agree.
COMPONENT_NAME = "book"


def book_combiner_component(app: Application | None = None) -> Combiner | Any:
    """Return the composed book combiner (feature 301's callable).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via :func:`app.module_loader.create_app`
    (scanning the declared workspace).  Returns ``None`` when no ``book``
    component is registered — an absent component is a discoverable state,
    not an exception, exactly as an empty workspace is for the factory; see
    the module docstring for why that ``None`` is a statement about
    composition and never about the deployment.

    The returned object is the combiner itself — call it as
    ``combine(promoted_signals)`` and it answers a :class:`book.CompositeBook`
    holding one composite target score per symbol — and it composes to the
    same callable in every process, because the builder holds no state, reads
    no environment and cannot fail.  Asking is always safe; combining begins
    at the call, not the composition.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
