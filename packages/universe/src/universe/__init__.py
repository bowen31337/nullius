"""The tradable universe, as a workspace component.

Features (app_spec.xml, "Universe & Survivorship Integrity", features 40,
41, 42, 43, 44, 45, 46 and 47): persist a monthly tradable universe computed as top-N by
trailing 30-day median dollar volume, exclude symbols whose median falls
below a configured liquidity floor — persisting each exclusion with its
reason — persist the point-in-time ``universe_membership`` rows
``(symbol, valid_from, valid_to, delist_reason)`` those builds imply,
resolve a requested decision time against that table so the answer is the
symbols tradable *then* rather than now
(:func:`universe.membership.resolve_membership`), retain
every symbol's daily price history so a delisted name still answers to any
window covering its listed period, audit each historical window for the
delisted symbols still present in it, reject a build whose window is
known to contain delistings yet counts ``delisted=0`` — the pruning
signature the gate (:mod:`universe.gate`) refuses to persist — and return
every one of those answers in the one stable symbol ordering
(:mod:`universe.ordering`, feature 46), so downstream reductions stay
bit-reproducible.
docs/nullius-tech-architecture.md §4.3
fixes the definition; the module docstrings in this package record the mechanics.

Two contract notes for anyone composing or extending this component:

*Registration.* This package opts into the application factory by
decorating a zero-argument builder with :func:`app.module_loader.register`.
The factory discovers it by scanning the declared workspace members — no
central file names this package, and none may. All intra-package imports
are relative so the package imports identically under its own name and
under the loader's scan-time name.

*Point-in-time honesty.* The universe for a month is computed only from
bars dated before that month begins, and what was computed is persisted
with the window and config that produced it — including the floor-excluded
symbols, whose absence is a recorded decision rather than a silence. The
interval-form ``universe_membership`` table is derived from those persisted
builds (see :mod:`universe.membership`) and re-derived on every persist, so
the interval form can never disagree with the monthly facts; the
survivorship audit reads both. Nothing here may quietly rebuild history
with today's data.
"""

from app.module_loader import register

from .audit import (
    WindowAudit,
    delisted_symbols,
    render_report,
    survivorship_audit,
)
from .bars import DailyBar, coerce_date
from .config import UniverseConfig
from .gate import (
    SurvivorshipGap,
    UniverseBuildRejected,
    known_delistings,
    reject_survivorship_gaps,
    survivorship_gaps,
)
from .history import PriceBar, PriceHistoryStore
from .monthly import (
    MonthlyUniverse,
    SkippedMonth,
    UniverseBuildResult,
    UniverseExclusion,
    UniverseMember,
    build_monthly_universes,
    build_monthly_universe,
    floor_exclusion_reason,
    median_dollar_volumes,
    month_key,
    month_start,
    next_month_start,
)
from .membership import MembershipInterval, membership_intervals, resolve_membership
from .ordering import (
    UnstableSymbolOrder,
    assert_stable_symbol_order,
    canonical_symbol_order,
    is_stable_symbol_order,
)
from .service import UniverseService, build_universe_service
from .store import (
    load_all_monthly_universes,
    load_monthly_universe,
    load_survivorship_audit,
    load_universe_membership,
    persist_monthly_universe,
    persist_price_history,
    persist_survivorship_audit,
    persist_universe_membership,
)

__all__ = [
    "DailyBar",
    "UniverseConfig",
    "UniverseMember",
    "UniverseExclusion",
    "MonthlyUniverse",
    "UniverseBuildResult",
    "SkippedMonth",
    "MembershipInterval",
    "UniverseService",
    "build_universe_service",
    "build_monthly_universe",
    "build_monthly_universes",
    "median_dollar_volumes",
    "floor_exclusion_reason",
    "month_key",
    "month_start",
    "next_month_start",
    "coerce_date",
    "membership_intervals",
    # Feature 42 — resolve membership as of a requested decision time
    "resolve_membership",
    # Feature 46 — the stable symbol ordering every resolution returns
    "UnstableSymbolOrder",
    "canonical_symbol_order",
    "is_stable_symbol_order",
    "assert_stable_symbol_order",
    "persist_monthly_universe",
    "persist_universe_membership",
    "load_monthly_universe",
    "load_all_monthly_universes",
    "load_universe_membership",
    # Feature 43 — retain delisted symbols with their full price history
    "PriceBar",
    "PriceHistoryStore",
    "persist_price_history",
    # Feature 44 — the survivorship audit
    "WindowAudit",
    "delisted_symbols",
    "survivorship_audit",
    "render_report",
    "persist_survivorship_audit",
    "load_survivorship_audit",
    # Feature 45 — the survivorship gate
    "SurvivorshipGap",
    "UniverseBuildRejected",
    "known_delistings",
    "survivorship_gaps",
    "reject_survivorship_gaps",
]

__version__ = "0.1.0"


@register("universe")
def _registered_universe_service() -> UniverseService:
    """Component builder: the universe service, configured from the environment."""
    return build_universe_service()
