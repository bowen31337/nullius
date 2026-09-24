"""The book combiner, its volatility target, its position and concentration
limits, its publication of the final target weights, its authorship guard, its
changelog companion, its leverage cap and its rebalance record — eight features:
301, 303, 304, 305, 306, 307, 308 and 309.

app_spec.xml, "Portfolio Book Construction", feature 301: *System combines
promoted signals by information-ratio weighting, which returns a single
composite target score per symbol.*  :func:`combine` is that act: it takes
the promoted signals — each a :class:`PromotedSignal` carrying its
out-of-sample information ratio and one target score per symbol — weights
signal *i* by ``w_i = IR_i`` and returns a single :class:`CompositeBook`
holding one composite target score per symbol, the weighted average of that
symbol's scores across the signals.

app_spec.xml, feature 303 is the category's second act and the one this
package carries beside the combiner: *System applies volatility targeting to
the combined book, which returns weights scaled to a configured annualized
volatility.*  :func:`apply_volatility_target` is its verb: it takes the
composite 301 answers and the book's own annualized volatility, normalizes the
composite into a book at one unit of gross exposure (a target *score* carries
free sign and scale — PRD §3 — and a weight does not), scales it by the one
factor ``target_volatility / volatility``, and answers a frozen
:class:`TargetWeights` whose construction re-checks that every weight is its
own gross weight times that factor.  It arrives as a free function beside the
combiner, in the same shape the guard and the cap do, because its whole input
is a value and two figures the caller already holds.  Its one knob — the
configured annualized volatility — is a **required** keyword with no default:
§C8's chain names the step and docs/alpha-engine-prd.md states no figure for
it, so a module-chosen fallback would be a risk level no document states,
silently applied to every deployment that never configured one.

app_spec.xml, feature 304 is §C8's next link, one step after the target and
one step before the orders: *System applies per-position and concentration
limits, which rejects a target weight breaching either bound.*
:func:`rejects_breaching_target_weights` is its verb: it takes the target
weights feature 303 answers and the deployment's two limits, and raises when a
target weight breaches either bound.  The two bounds are genuinely different
facts about the same book — a *position's size* (``|w_s| ≤
per_position_limit``) and the book's *shape* (``max_s |w_s| / Σ_t |w_t| ≤
concentration_limit``, the largest position's share of gross exposure) — and
neither subsumes the other: feature 303's scaling multiplies every weight by
one factor, so it sets the first and leaves the second exactly where feature
301's ranking put it.  Both figures are the deployment's (the documents name
the step and state no figure for either) and arrive as **required** keywords
with no default, feature 303's own boundary read one step later.
:func:`concentration` is the figure the second bound is stated over, answered
as a pure function of the weights; :func:`is_breaching_limits` is the fact
without the refusal.  The act arrives beside the combiner in the same shape the
cap and the guard do — free functions, no second component — because its whole
input is a value and two figures the caller already holds.

app_spec.xml, feature 305 is §C8's own last arrow, one step after the limits
and the step the orders consume: *System returns final target weights as the
only output consumed by the order layer.*  :func:`final_target_weights` is its
verb: it takes the bounded book feature 304's verdict let through and answers a
frozen :class:`FinalTargetWeights` carrying the weights the order layer holds
*unchanged* — this act re-runs no arithmetic, because feature 301 already
combined, feature 303 already scaled and feature 304 already bounded, and a
second answer to a question an earlier step answered is exactly the drift the
sentence's *only* forecloses.  :func:`is_only_output` reads that *only* over
the construction's whole surface — the value meant for the orders and
everything else the caller holds — answering ``True`` exactly when one value
declares itself a published final weight set and no second one does; the
construction's *working* (the composite, the gross book, the scale, the target
weights) is not a second output and may be held beside it.
:func:`assert_only_output` is the same judgment as a verdict.  It arrives as
free functions beside the combiner in the same shape the cap and the limits do,
because its whole input is a value the caller already holds.  Absence is not
zero here as everywhere else in the member: a value carrying no ``weights``, a
set covering no symbols and a non-finite weight are the *absence* of a book and
are refused, while a book held flat (every weight ``0.0``, feature 303's
zero-target answer) is a decision and is published.

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

app_spec.xml, feature 307 is the category's companion sentence, building on
feature 306's record: *System requires a changelog entry accompanying every
book construction change, which returns a validation failure when absent.*
It is §C8's remaining clause — *"Changing it is a human decision **with a
changelog entry**, not a discovery"* — made structural beside the guard.
:class:`ChangelogEntry` is the entry as its carrier states it (the subject the
entry documents, the body the entry's prose — a frozen record of exactly two
fields, the human's own document, never a projection of the change's four
fields); :func:`is_missing_changelog_entry` is the fact without the refusal;
:func:`requires_changelog_entry` is the sentence's *requires*, the verdict a
caller runs on the write path so a change never lands without the entry §C8
demands.  The companion arrives beside the combiner in the same shape the guard
and the cap do — free functions, no second component — because its whole input
is two records the caller already holds, and the boundary is presence rather
than content: an entry is admitted as present when it is well stated and
refused as absent when it is not there, because this package validates no
changelog prose.

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

app_spec.xml, feature 309 is this category's last sentence, and the only one in
it that keeps state: *System persists each rebalance target weight set with its
originating promoted signal identifiers.*  :meth:`RebalanceTargetWeightsStore.record`
is its verb.  The provenance it pairs with the set is on **no value the chain
hands downstream** — feature 301's :class:`CompositeBook` is keyed by
``signal_id``, but feature 303's :class:`TargetWeights` and feature 305's
:class:`FinalTargetWeights` are keyed by symbol only, deliberately, because
feature 305's *only* is what keeps the construction's working out of the order
layer's instruction — so writing it down is the only way the chain's output can
ever be audited back to the views that produced it.  The act reads the set off
the value the caller already holds (duck-typed, feature 305's own ``weights``
surface) and the identifiers off the **promoted signals themselves** rather than
a list of names, because provenance nothing checks is the one thing an audit
table exists to avoid.  The record is keyed by the rebalance —
``(book_id, rebalance_ts)``, §13.2's own triple read at its head — with one row
per rebalance, so a re-issue of the same set and provenance answers the standing
row untouched while a *different* set for the same instant is refused: the row
is the only record there is, and nothing downstream re-derives it.

Feature 309 is also where this package stops being environment-free, and the
docstring below says so rather than leaving the claim standing: it is the
member's first feature that opens the deployment's relational store.  It is
reached the way :meth:`regime.coverage.RegimeCoverage.resolve` is — a class
beside the combiner with a ``resolve`` classmethod that answers ``None`` for a
deployment that named no database — and not through a second component, because
a builder runs with no arguments and must not fail composition while this
store's address is a deployment's.  One component remains.

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
features — covariance shrinkage, position limits — take this composite and
rescale it; they do not re-open this weight.  Feature 303 is the rescaling
that does happen here, and it rescales the *composite's exposure* without
touching the weighting: the normalized weights it derives are IR_i / Σ_j IR_j
read through one factor, so the ranking 301 fixed is exactly the ranking the
target weights carry.  Feature 304's limits are the same stance one step
further on: they read the weights feature 303 answered and bound them, and
they re-weight nothing — a breaching book is refused rather than scaled down
or spread out, because reshaping a caller's book would be this member sizing
it rather than bounding it.  Feature 308's cap is the same stance on the sizing
step's own figure: the quarter is the document's, not a deployment's, because
it is the discount against a Sharpe the document itself calls a noisy
estimate (their one knob, the configured volatility target, is feature 303's
— and this package is where that figure arrives, as a required keyword of
:func:`apply_volatility_target`; the two figures feature 304's bounds are
stated over arrive the same way, as required keywords of
:func:`rejects_breaching_target_weights`).

Absence is not zero, three times over: a signal with a non-positive or
non-finite information ratio is refused (its standing to weight the book is
undefined, not zero); a signal that carries no score for a symbol the book
covers is refused (it expresses no view — zero-filling would counterfeit
one); and a composite whose scores are *all* zero is refused by feature 303's
act (its gross score is exactly nothing, so the normalization to a book is a
division by nothing — answering an all-zero weight set would counterfeit a
book from no view).  None is defaulted; a refused combine or scaling forms no
value.  The cap draws the same line where it applies and not where it does
not: a non-positive Sharpe is answered (a losing book's fraction is a measured
fact whose consequence is *no admissible leverage*, not an error), while a
volatility of zero is refused (a book with no scale has no fraction at all).
Feature 303 draws it in the same place for the same reason: a *zero
configured target* is answered — *take no risk* is a level, whose honest
consequence is a flat book — while a book volatility of zero is refused, the
divisor being exactly nothing there.  Feature 304 draws it in the same place
once more: a *zero limit* is answered (it admits exactly the flat book, which
is the appetite's own consequence), while a target weight that is not a finite
real is refused — and the flat book's *concentration* is answered as ``0.0``
rather than refused, because a book that holds nothing is genuinely not
concentrated: that figure is a description of a book already decided, where
feature 303's ``flat_book`` is a division by exactly nothing standing in for a
book nobody built.

This module is stdlib-only — dataclasses, mappings and square-free
arithmetic; no polars, no pyarrow, no lake, no HTTP, and no import of any other
member — so importing this member costs composition nothing and the combiner is
import-cheap on the replay path.  **One qualification, stated here rather than
left implied: feature 309's store is the member's first code that reads the
environment and touches a database.**  :mod:`book._rebalance` imports ``json``,
``math``, ``os``, ``sqlite3``, ``collections``, ``contextlib``, ``dataclasses``,
``datetime``, ``pathlib``, ``types``, ``typing`` and ``urllib.parse`` — all
stdlib — and it reads ``DATABASE_URL`` at the *call* and never at composition,
so the factory's scan still pays only the imports it already paid and a builder
still takes no arguments.  That is the same boundary features 303, 304 and 305
state for their own figures, read on an address instead: a deployment knob
reaches the call, and never the composition.  The leverage
cap adds nothing to that bill: :mod:`book._leverage` imports ``math`` and the
member's own error vocabulary and nothing else, so the cap costs the
factory's scan no more than the combiner does.  Neither does the guard:
:mod:`book._authorship` imports ``dataclasses``, ``typing`` and the same
error vocabulary, and judges records it is handed rather than state it
would have to go looking for.  Nor the volatility target:
:mod:`book._volatility` imports ``math``, ``dataclasses``, ``collections``,
``types``, ``typing`` and that same vocabulary, and reads a value the caller
holds rather than measuring one — a configured volatility target is handed to
the *call* and never to the composition, so the factory's registration
protocol, which takes no arguments, cannot express one and no component
reasons about it.  Nor the limits: :mod:`book._limits` imports ``math``,
``collections``, ``dataclasses``, ``typing`` and that same vocabulary, and its
two figures reach the call the same way the target does — the same structural
argument, read on the two bounds one step after it.  Nor the publication:
:mod:`book._publish` imports ``math``, ``collections``, ``dataclasses``,
``types``, ``typing`` and that same vocabulary, and it reads a value the caller
holds rather than computing one — the chain's last step adds no arithmetic, so
it costs the factory's scan no more than the combiner does, and there is
nothing for a deployment to configure because nothing about it is a figure.
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
from ._changelog import (
    MISSING_CHANGELOG_ENTRY_CODE,
    ChangelogEntry,
    is_missing_changelog_entry,
    requires_changelog_entry,
)
from ._combine import CompositeBook, PromotedSignal, combine
from ._leverage import (
    KELLY_FRACTION,
    OVERLEVERAGE_CODE,
    kelly_fraction,
    leverage_cap,
    rejects_overleveraged_target,
)
from ._limits import (
    CONCENTRATION_LIMIT_CODE,
    PER_POSITION_LIMIT_CODE,
    concentration,
    is_breaching_limits,
    rejects_breaching_target_weights,
)
from ._publish import (
    ANNEXED_RECORD_CODE,
    NO_BOOK_CODE,
    PUBLISHED_KIND,
    FinalTargetWeights,
    assert_only_output,
    final_target_weights,
    is_only_output,
)
from ._rebalance import (
    DATABASE_URL_ENV,
    NO_ORIGINATING_SIGNALS_CODE,
    REBALANCE_RECORDED_CODE,
    REBALANCE_TARGET_WEIGHTS_TABLE,
    RebalanceTargetWeights,
    RebalanceTargetWeightsStore,
)
from ._volatility import (
    FLAT_BOOK_CODE,
    TargetWeights,
    apply_volatility_target,
)
from .errors import (
    AgentAuthoredModificationError,
    BookChangeRequestError,
    BookConstructionError,
    ChangelogEntryRequestError,
    FinalWeightsRequestError,
    LeverageRequestError,
    LeverageTargetError,
    LimitBreachError,
    LimitRequestError,
    MissingChangelogEntryError,
    OrderLayerOutputError,
    RebalanceRequestError,
    RebalanceRewriteError,
    RebalanceStoreError,
    VolatilityTargetError,
    VolatilityTargetRequestError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from collections.abc import Callable, Iterable

__all__ = [
    "AGENT_AUTHOR_KINDS",
    "AGENT_MODIFICATION_CODE",
    "ANNEXED_RECORD_CODE",
    "AUTHOR_KINDS",
    "COMPONENT_NAME",
    "CONCENTRATION_LIMIT_CODE",
    "DATABASE_URL_ENV",
    "FLAT_BOOK_CODE",
    "HUMAN_AUTHOR_KIND",
    "KELLY_FRACTION",
    "MISSING_CHANGELOG_ENTRY_CODE",
    "NO_BOOK_CODE",
    "NO_ORIGINATING_SIGNALS_CODE",
    "OVERLEVERAGE_CODE",
    "PER_POSITION_LIMIT_CODE",
    "PUBLISHED_KIND",
    "REBALANCE_RECORDED_CODE",
    "REBALANCE_TARGET_WEIGHTS_TABLE",
    "REVISION_HEX_LENGTH",
    "AgentAuthoredModificationError",
    "BookChangeRequestError",
    "BookConstructionChange",
    "BookConstructionError",
    "ChangelogEntry",
    "ChangelogEntryRequestError",
    "CompositeBook",
    "FinalTargetWeights",
    "FinalWeightsRequestError",
    "LeverageRequestError",
    "LeverageTargetError",
    "LimitBreachError",
    "LimitRequestError",
    "MissingChangelogEntryError",
    "OrderLayerOutputError",
    "PromotedSignal",
    "RebalanceRequestError",
    "RebalanceRewriteError",
    "RebalanceStoreError",
    "RebalanceTargetWeights",
    "RebalanceTargetWeightsStore",
    "TargetWeights",
    "VolatilityTargetError",
    "VolatilityTargetRequestError",
    "apply_volatility_target",
    "assert_only_output",
    "build_book_combiner",
    "combine",
    "concentration",
    "final_target_weights",
    "is_agent_authored",
    "is_breaching_limits",
    "is_missing_changelog_entry",
    "is_only_output",
    "kelly_fraction",
    "leverage_cap",
    "rejects_agent_authored_modification",
    "rejects_breaching_target_weights",
    "rejects_overleveraged_target",
    "requires_changelog_entry",
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
