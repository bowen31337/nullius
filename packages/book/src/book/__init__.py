"""The book combiner, its authorship guard and its leverage cap — three
features: 301, 306 and 308.

app_spec.xml, "Portfolio Book Construction", feature 301: *System combines
promoted signals by information-ratio weighting, which returns a single
composite target score per symbol.*  :func:`combine` is that act: it takes
the promoted signals — each a :class:`PromotedSignal` carrying its
out-of-sample information ratio and one target score per symbol — weights
signal *i* by ``w_i = IR_i`` and returns a single :class:`CompositeBook`
holding one composite target score per symbol, the weighted average of that
symbol's scores across the signals.

app_spec.xml, feature 306 is the category's boundary sentence:
*System keeps book construction human-authored and version-controlled,
which rejects any agent-authored modification to it.*  It is
docs/alpha-engine-prd.md §C8's own closing rule — *"Version-controlled,
human-authored, explicitly outside the search space.  Changing it is a
human decision with a changelog entry, not a discovery"* — and this
package is the construction that rule protects.  :class:`BookConstructionChange`
is a modification to it as its carrier states it (the subject, the
author, the author kind, the commit — and a change that names no commit
cannot be stated at all, which is the sentence's *version-controlled*
half made structural); :func:`is_agent_authored` is the fact without the
refusal; :func:`rejects_agent_authored_modification` is the sentence's
*rejects*, the verdict a caller runs on the write path so an agent's edit
to the construction never lands.  The guard arrives beside the combiner
in the same shape the cap does — free functions, no second component —
because its whole input is a record the caller already holds, and the
one human kind (:data:`HUMAN_AUTHOR_KIND`) is a constant rather than a
parameter for the same reason the weighting and the quarter are: a
deployment that could widen the admitted set could opt an agent in.

app_spec.xml, feature 308 is this category's third sentence and a further
act this package carries: *System rejects a leverage target above one quarter
of the Kelly fraction implied by the book Sharpe and volatility.*
:func:`leverage_cap` is the figure the sentence turns on — one quarter of
Appendix B's ``f* = S/σ`` — and :func:`rejects_overleveraged_target` is its
*rejects*, the verdict a caller runs on its last line before handing a sized
book to the order layer.  The pair arrives as free functions beside the
combiner rather than as a second component, the way feature 276's ceiling
arrives beside feature 270's freeze in the dreaming member: the sentence's
whole input is figures the caller already holds (the book's Sharpe, its
volatility and the target), so there is nothing for the factory to compose
and nothing for a deployment to configure.  One component remains, and the
member's suite pins that.

This package is a workspace member: it self-registers with the application
factory under the component name :data:`COMPONENT_NAME` — scanning the
workspace imports it, its ``@register`` builder fires, and
``create_app()`` composes the combiner the order layer reaches through the
app package.  Joins the uv workspace by convention — ``packages/book`` with
its own ``pyproject.toml`` — so the module loader (``src/app/module_loader.py``)
discovers it by scanning the members the root ``pyproject.toml`` declares.
No edit to any central registry, router table or app factory is needed or
wanted to wire this package in; importing this module *is* joining the
application.  All intra-package imports are relative so the package imports
identically under its own name and under the synthetic name the loader gives
it.

The combiner is a callable component, the scoring precedent: the ``book``
component is the combiner itself (:func:`combine`), not a store or a
service.  It has no ``DATABASE_URL`` to be absent and no environment to
read; its whole configuration is the arithmetic — the information-ratio
weighting (weight signal *i* by ``IR_i``, composite the weighted average),
restated here rather than imported from the evaluator or scoring member,
because a workspace member never imports another workspace member and
reaches shared shapes through ``app.*``.  The builder
:func:`build_book_combiner` takes no arguments, reads no environment and
never raises, and returns :func:`combine` unchanged, so a composed
application carries the one callable every world's book ranking is computed
through, and the members that need it reach it through the app package
rather than importing this member.  A member that needs the combiner — the
order layer's ranking step, routing the promoted signals into a composite
target per symbol — reaches it here, through the app package, because a
workspace member never imports another workspace member.  The callable is
the component the way the scoring member's objective is.

The information-ratio weighting is a convention, not a knob: a weight is a
portfolio decision the combiner applies rather than accepts, so two
deployments report the same composite for the same signals.  Downstream
features — covariance shrinkage, volatility targeting, position limits —
take this composite and rescale it; they do not re-open this weight.  Feature
308's cap is the same stance on the sizing step's own figure: the quarter is
the document's, not a deployment's, because it is the discount against a
Sharpe the document itself calls a noisy estimate (their one knob, the
configured volatility target, is feature 303's).

Absence is not zero, twice over: a signal with a non-positive or
non-finite information ratio is refused (its standing to weight the book is
undefined, not zero), and a signal that carries no score for a symbol the
book covers is refused (it expresses no view — zero-filling would
counterfeit one).  Neither is defaulted; a refused combine forms no value.
The cap draws the same line where it applies and not where it does not: a
non-positive Sharpe is answered (a losing book's fraction is a measured fact
whose consequence is *no admissible leverage*, not an error), while a
volatility of zero is refused (a book with no scale has no fraction at all).

This module is stdlib-only — dataclasses, mappings and square-free
arithmetic; no polars, no pyarrow, no lake, no environment, no HTTP, and no
import of any other member — so importing this member costs composition
nothing and the combiner is import-cheap on the replay path.  The leverage
cap adds nothing to that bill: :mod:`book._leverage` imports ``math`` and the
member's own error vocabulary and nothing else, so the cap costs the
factory's scan no more than the combiner does.  Neither does the guard:
:mod:`book._authorship` imports ``dataclasses``, ``typing`` and the same
error vocabulary, and judges records it is handed rather than state it
would have to go looking for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.module_loader import register

from ._authorship import (
    AGENT_AUTHOR_KINDS,
    AGENT_MODIFICATION_CODE,
    AUTHOR_KINDS,
    HUMAN_AUTHOR_KIND,
    REVISION_HEX_LENGTH,
    BookConstructionChange,
    is_agent_authored,
    rejects_agent_authored_modification,
)
from ._combine import CompositeBook, PromotedSignal, combine
from ._leverage import (
    KELLY_FRACTION,
    OVERLEVERAGE_CODE,
    kelly_fraction,
    leverage_cap,
    rejects_overleveraged_target,
)
from .errors import (
    AgentAuthoredModificationError,
    BookChangeRequestError,
    BookConstructionError,
    LeverageRequestError,
    LeverageTargetError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from collections.abc import Callable, Iterable

__all__ = [
    "AGENT_AUTHOR_KINDS",
    "AGENT_MODIFICATION_CODE",
    "AUTHOR_KINDS",
    "COMPONENT_NAME",
    "HUMAN_AUTHOR_KIND",
    "KELLY_FRACTION",
    "OVERLEVERAGE_CODE",
    "REVISION_HEX_LENGTH",
    "AgentAuthoredModificationError",
    "BookChangeRequestError",
    "BookConstructionChange",
    "BookConstructionError",
    "CompositeBook",
    "LeverageRequestError",
    "LeverageTargetError",
    "PromotedSignal",
    "build_book_combiner",
    "combine",
    "is_agent_authored",
    "kelly_fraction",
    "leverage_cap",
    "rejects_agent_authored_modification",
    "rejects_overleveraged_target",
]

#: The component name the book member registers under.  Kept here so
#: anything asking the composed application for the book combiner — by way
#: of the app package, not the member — shares one spelling, and so the
#: seat, the member and the spec's ``plugin="book"`` cannot drift apart
#: silently; the member's suite asserts the two agree.
COMPONENT_NAME = "book"


@register(COMPONENT_NAME)
def build_book_combiner() -> Callable[[Iterable[object]], CompositeBook]:
    """Component builder: the book combiner itself (feature 301).

    Takes no arguments — that is the factory's registration protocol — and
    contributes :func:`~book.combine` unchanged, so a composed application
    carries the one callable every book ranking is computed through and the
    members that need it reach it through the app package rather than
    importing this member.

    Never raises and reads no environment — the combiner's whole
    configuration is the arithmetic; a deployment cannot misconfigure it, an
    empty workspace cannot degrade it, and the factory building this
    component on every ``create_app()`` call costs one attribute lookup.
    That is not a boast about this feature but the property the combiner must
    have to be the ranking's floor: a composite that could fail to compose
    would be a ranking that silently drops the signals it was asked to
    combine.  A ``None`` from the composed application therefore means only
    that this member was absent from the scan, never that the combiner itself
    failed.
    """
    return combine
