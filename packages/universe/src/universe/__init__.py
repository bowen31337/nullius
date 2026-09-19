"""The tradable universe, as a workspace component.

Feature (app_spec.xml, "Universe & Survivorship Integrity", feature 40):
persist a monthly tradable universe computed as top-N by trailing 30-day
median dollar volume. docs/nullius-tech-architecture.md §4.3 fixes the
definition; the module docstrings in this package record the mechanics.

Two contract notes for anyone composing or extending this component:

*Registration.* This package opts into the application factory by
decorating a zero-argument builder with :func:`app.module_loader.register`.
The factory discovers it by scanning the declared workspace members — no
central file names this package, and none may. All intra-package imports
are relative so the package imports identically under its own name and
under the loader's scan-time name.

*Point-in-time honesty.* The universe for a month is computed only from
bars dated before that month begins, and what was computed is persisted
with the window and config that produced it. Downstream members derive
the interval-form membership table and the survivorship audit from these
builds; nothing here may quietly rebuild history with today's data.
"""

from app.module_loader import register

from .bars import DailyBar, coerce_date
from .config import UniverseConfig
from .monthly import (
    MonthlyUniverse,
    SkippedMonth,
    UniverseBuildResult,
    UniverseMember,
    build_monthly_universes,
    build_monthly_universe,
    median_dollar_volumes,
    month_key,
    month_start,
)
from .service import UniverseService, build_universe_service
from .store import load_monthly_universe, persist_monthly_universe

__all__ = [
    "DailyBar",
    "UniverseConfig",
    "UniverseMember",
    "MonthlyUniverse",
    "UniverseBuildResult",
    "SkippedMonth",
    "UniverseService",
    "build_universe_service",
    "build_monthly_universe",
    "build_monthly_universes",
    "median_dollar_volumes",
    "month_key",
    "month_start",
    "coerce_date",
    "persist_monthly_universe",
    "load_monthly_universe",
]

__version__ = "0.1.0"


@register("universe")
def _registered_universe_service() -> UniverseService:
    """Component builder: the universe service, configured from the environment."""
    return build_universe_service()
