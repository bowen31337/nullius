"""The regime plugin: §C7's coverage ledger, one count per named stratum.

Implements app_spec.xml, "Regime Coverage Strata", feature 283 — *"System
persists a regime_coverage count per stratum such as high-volatility trend,
low-volatility chop and crash"* — against docs/alpha-engine-prd.md §C7's
coverage ledger and the three-column table feature 107's migration
(``migrations/versions/0107_regime_coverage.py``) already declares.

The member's surface is seven modules.  :mod:`regime.coverage` is the
ledger's act itself: :class:`~regime.coverage.RegimeCoverage`, the store
that persists one stratum's stored-world count into ``regime_coverage``,
names a stratum without asserting a count, and reads one stratum's row
back; :data:`~regime.coverage.DEFAULT_STRATA`, the three names the
feature's own sentence spells; and
:func:`~regime.coverage.persist_coverage`, the module-level spelling of
the persist for the caller that holds no store.  :mod:`regime.ledger`
is feature 284's act, the ledger's *reader*:
:class:`~regime.ledger.CoverageLedger` is §C7's ledger as a whole — every
named stratum's row, read in one pass in name order, with the counts, the
named-empty set, the covered set and the vocabulary holes as views derived
on demand; :class:`~regime.ledger.CoverageHole` is the *never named* fact,
kept a distinct type from the named-empty one ``0107`` detail 1 keeps
distinct, and :func:`~regime.ledger.read_ledger` is the module-level
spelling for a caller that holds a URL rather than a store.  The read is
also the store's own verb
(:meth:`~regime.coverage.RegimeCoverage.ledger`), which is the form every
composed reader uses.  :mod:`regime.promotion` is feature 285's act, the
category's *block*: :func:`~regime.promotion.rejects_undercovered_promotion`
refuses a promotion when the target deployment regime's stored-world count
falls below the deployment's own configured threshold — a free function
over the ledger the read answers with, raising
:class:`~regime.errors.PromotionCoverageError` (opening
``coverage_below_threshold``) rather than counting, persisting or
re-reading anything, so the deployment is stopped before the promotion is
published.  Its figure is one named stratum's count, deliberately *not*
:mod:`regime.diversity`'s: a pool covered across the whole default
vocabulary with the target regime holding none passes that sibling's claim
and is exactly the deployment §C7 says to block.
:mod:`regime.diversity` is feature 289's act, the
reading's *verdict*: :func:`~regime.diversity.rejects_regime_diverse_claim`
refuses a regime-diverse claim while fewer than three strata hold stored
worlds — a free function over the ledger the read answers with, raising
:class:`~regime.errors.DiversityClaimError` (opening
``not_regime_diverse``) rather than counting, persisting or re-reading
anything, so the claim is stopped before it is published.
:mod:`regime.warning` is feature 286's act, the category's *report*:
:func:`~regime.warning.emit_empty_stratum_warning` emits the
``empty_stratum`` warning through :func:`warnings.warn` when any named
stratum holds 0 stored worlds — the spec's one emission that is a
*warning* rather than an *alert*, over §C7's own ``crash: 0`` state the
census writes on purpose, so it is visible, greppable and non-fatal
where its refusing siblings halt; :class:`~regime.warning.EmptyStratumWarning`
is both the category the machinery dispatches on and the record that
carries the names, and :func:`~regime.warning.empty_stratum_warning` is
the same finding as a value (or ``None``) for the caller that renders
it itself.  It fires on the named-empty row and never on the
never-named absence, the law ``0107`` detail 1 makes this module's own.
:mod:`regime.census`
is feature 290's act, the one that makes the numbers the ledger holds:
:func:`~regime.census.assign_strata` assigns each stored world a
stratum through the causal rolling-window labeler (duck-read at the
seam, refusing a full-history fit in this member's own vocabulary), and
:func:`~regime.census.census_coverage` writes the counts through the
coverage store, zeros included.  :mod:`regime.origins` is features
287/288's: :func:`~regime.origins.split_world_id` reads a synthesized
world's originating campaign and epoch back out of the
``<campaign_id>@<epoch_id>`` identity feature 287 spelled, and
:class:`~regime.origins.WorldBackfill` records that origin — one
row per world, in this member's own table in the same database, created
idempotently so no migration is needed — so that *backfill never
masquerades as fresh history*.
:mod:`regime.errors` is the member's error vocabulary —
:class:`~regime.errors.RegimeError`,
:class:`~regime.errors.CoverageError` (the persist's three faces: the
ask, the row, the address), :class:`~regime.errors.StratumAssignmentError`
(feature 290's fit refusal),
:class:`~regime.errors.BackfillProvenanceError` (feature 288's
``no_origin`` refusal), :class:`~regime.errors.DiversityClaimError`
(feature 289's ``not_regime_diverse`` verdict),
:class:`~regime.errors.PromotionCoverageError` (feature 285's
``coverage_below_threshold`` block — the category's first judgement, its
faces gathered in one class because its caller is a gate, whose one
failure mode is silence) and
:class:`~regime.errors.EmptyStratumWarningError` (feature 286's refusal
of an ``empty_stratum`` warning that could not be read off a reading —
the finding itself is *warned*, never raised, which is why its class
carries only the ask), each a sibling rather
than a child for the reason
that module states, with the argument for why the category's *judgement*
refusals sit beside them as siblings rather than under them.  This module
re-exports all of them and registers the one component; it carries no
logic of its own, which is the same shape every member in this workspace
takes.

**Why the ledger's writer is a component at all — and why nothing else in
this category will be.**  The factory's registration protocol is for
*state a deployment holds* — a store, a device, a materialised pool — and
the ledger is exactly that: a table in the database ``DATABASE_URL``
names, written by the census or the backfill that counts the pool and
read by the endpoint and the gates, from other processes, between this
process's calls.  Everything the category's later features add is a
judgement *over* these rows rather than a second thing that persists:
feature 284's ``GET /metrics/regime-coverage`` is a read the composed
store serves; feature 285's promotion block and feature 289's diversity
refusal are thresholds applied to counts the caller read through this
store — and both have now landed as exactly that, free functions over the
reading rather than a second thing to compose; feature 286's
``empty_stratum`` warning is a fact about a row this
store already holds (``world_count == 0`` is what
:meth:`~regime.coverage.CoverageCount.empty` answers); feature 290's
causal labeler *writes* through this store rather than beside it; and
features 287 and 288's backfill adds a **second member-owned table in the
same database** — :mod:`regime.origins`, the store that records a
synthesized world with the campaign it came from — reached directly
rather than through a component, because a store addressed by
``DATABASE_URL`` is never composed.  A builder takes no arguments and is built
on every ``create_app()`` call, while each of those acts is a function of
evidence the factory does not hold — the pool's census, a manifest, a
price panel — so registering one would be a component pointed at state no
composition can supply.  The member's registered surface is therefore
this feature's single store, and the sibling seams will reach it the only
way the spec allows: by asking the composed store, or by writing through
it.

**Registration is the entire wiring story.**  The module loader
(``app.module_loader``) scans the members the root ``pyproject.toml``
declares, imports each package, and composes whatever each package's
``@register`` builder contributes — so the decorator at the foot of this
module is all that makes the plugin exist.  Nothing edits a registry,
router table, entry-points list or app factory to wire this package in,
and nothing here reaches back and mutates the factory: the factory is the
composition root and the sole author of the object it returns.

**The registration lives here and not in a submodule.**  ``@register``
fires at import time, and importing a *submodule* of this package is not
the same act as importing the package: a submodule's registration would
fire only on the first ``create_app()`` of a process, and only if that
process happened to load it.  Keeping the decorator in ``__init__.py`` —
spelled against names imported from ``.coverage`` rather than beside it —
is what makes the component present from the moment the workspace scan
touches this package.

**One component, and it may be ``None``.**  ``"regime"`` is the member's
first component, registered unprefixed, following the ``ledger`` /
``artifacts`` / ``canary`` / ``discovery`` precedent for a member's first
and only component: the prefix families (``nulloracle-*``,
``tripwires-*``) exist to disambiguate many components inside one
member, and this member has one.  The name sorts between ``providers``
and the feature-store member's ``regime-labeler`` / ``regime-metrics``,
so every existing adjacency assertion over the name-sorted ``app.order``
is untouched.  The builder returns ``None`` when nothing names a
relational store, on the degrade-don't-break stance every store in this
workspace takes toward an absent ``DATABASE_URL`` — an unconfigured
ledger is a discoverable state, and the census that must persist a count
before the promotion gate reads it is the caller that must not find
itself in it.  It never raises, including for a URL whose scheme this
member cannot speak: the factory builds every registered component on
every ``create_app()`` call, so a raising builder would take composition
down for every unrelated feature in the workspace.
"""

from __future__ import annotations

from app.module_loader import register

from .census import (
    FULL_HISTORY_FIT_CODE,
    StratumAssignment,
    assign_strata,
    census_coverage,
)
from .coverage import (
    COVERAGE_TABLE,
    DATABASE_URL_ENV,
    DEFAULT_STRATA,
    STRATUM_COLUMN,
    UPDATED_AT_COLUMN,
    WORLD_COUNT_COLUMN,
    CoverageCount,
    RegimeCoverage,
    persist_coverage,
)
from .diversity import (
    NOT_REGIME_DIVERSE_CODE,
    REGIME_DIVERSITY_FLOOR,
    rejects_regime_diverse_claim,
)
from .errors import (
    BackfillProvenanceError,
    CoverageError,
    DiversityClaimError,
    EmptyStratumWarningError,
    PromotionCoverageError,
    RegimeError,
    StratumAssignmentError,
)
from .ledger import CoverageHole, CoverageLedger, read_ledger
from .origins import (
    BACKFILLED_WORLD_TABLE,
    CAMPAIGN_ID_COLUMN,
    EPOCH_ID_COLUMN,
    NO_ORIGIN_CODE,
    RECORDED_AT_COLUMN,
    WORLD_ID_COLUMN,
    WORLD_ID_SEPARATOR,
    BackfilledWorldRecord,
    BackfillProvenance,
    WorldBackfill,
    record_backfilled_world,
    split_world_id,
)
from .promotion import (
    COVERAGE_BELOW_THRESHOLD_CODE,
    rejects_undercovered_promotion,
)
from .warning import (
    EMPTY_STRATUM_CODE,
    EmptyStratumWarning,
    emit_empty_stratum_warning,
    empty_stratum_warning,
)

__all__ = [
    "BACKFILLED_WORLD_TABLE",
    "CAMPAIGN_ID_COLUMN",
    "COMPONENT_NAME",
    "COVERAGE_BELOW_THRESHOLD_CODE",
    "COVERAGE_TABLE",
    "DATABASE_URL_ENV",
    "DEFAULT_STRATA",
    "EMPTY_STRATUM_CODE",
    "EPOCH_ID_COLUMN",
    "FULL_HISTORY_FIT_CODE",
    "NOT_REGIME_DIVERSE_CODE",
    "NO_ORIGIN_CODE",
    "RECORDED_AT_COLUMN",
    "REGIME_DIVERSITY_FLOOR",
    "STRATUM_COLUMN",
    "UPDATED_AT_COLUMN",
    "WORLD_COUNT_COLUMN",
    "WORLD_ID_COLUMN",
    "WORLD_ID_SEPARATOR",
    "BackfillProvenance",
    "BackfillProvenanceError",
    "BackfilledWorldRecord",
    "CoverageCount",
    "CoverageError",
    "CoverageHole",
    "CoverageLedger",
    "DiversityClaimError",
    "EmptyStratumWarning",
    "EmptyStratumWarningError",
    "PromotionCoverageError",
    "RegimeCoverage",
    "RegimeError",
    "StratumAssignment",
    "StratumAssignmentError",
    "WorldBackfill",
    "assign_strata",
    "build_regime_coverage",
    "census_coverage",
    "emit_empty_stratum_warning",
    "empty_stratum_warning",
    "persist_coverage",
    "read_ledger",
    "record_backfilled_world",
    "rejects_regime_diverse_claim",
    "rejects_undercovered_promotion",
    "split_world_id",
]

#: The name the regime member registers its coverage ledger under.
#: Unprefixed, following the ``ledger`` / ``artifacts`` / ``canary`` /
#: ``discovery`` precedent for a member's first and only component, and
#: spelled here once so the seat (``src/app/modules/regime``) and the
#: composed application agree on the key — the seat repeats the literal
#: and its suite asserts the two match, so the pair cannot drift apart
#: silently.  ``regime`` sorts after ``providers`` and before the
#: feature-store member's ``regime-labeler``, clear of both.
COMPONENT_NAME = "regime"


@register(COMPONENT_NAME)
def build_regime_coverage() -> RegimeCoverage | None:
    """Component builder: the coverage ledger this deployment writes into.

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application
    carries the ledger for the deployment the process is actually running
    in.  The member's other spelling of the same act,
    :func:`~regime.coverage.persist_coverage`, resolves the same variable
    when it is called without a URL, so a census script and a composed
    application reach the same table.

    Returns ``None`` when nothing names a relational store.  That is
    deliberately not an empty store: an empty store answers *no world is
    stored in this stratum* about every name, while this ``None`` says
    there is no database to have persisted a count in — the distinction
    ``0107`` draws between a named-empty row and an absent one, at the
    level of the whole ledger.  A caller that must persist a count has to
    treat the ``None`` as a refusal to proceed rather than as a store
    that happened to find nothing, exactly as the campaign store's
    ``None`` is a refusal to plan a campaign.

    Never raises — including for a URL whose scheme the store cannot
    speak, which is refused by name the first time an operation needs the
    path rather than here.  Construction performs no I/O: the path is
    resolved on first use, so composing the application never opens a
    database, and nothing is written until a caller persists a count.
    """
    return RegimeCoverage.resolve()
