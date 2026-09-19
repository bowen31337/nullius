"""The universe as a composed application component.

The factory's contract is one-way: a component knows how to build itself
from nothing, and the factory asks exactly that. :meth:`UniverseService.from_env`
is that self-construction — configuration from environment variables with
spec defaults, store address from ``DATABASE_URL``. The factory never
passes anything in, so nothing here may require a parameter it will not
receive.

Environment overrides (all optional, all validated loudly — a mistyped
``NULLIUS_UNIVERSE_TOP_N`` must fail the build, not quietly rank a
hundred-and-nothing symbols):

* ``NULLIUS_UNIVERSE_TOP_N`` — symbols admitted per month (default 100)
* ``NULLIUS_UNIVERSE_WINDOW_DAYS`` — trailing window length (default 30)
* ``NULLIUS_UNIVERSE_MIN_OBSERVATIONS`` — eligibility minimum (default 1)
* ``NULLIUS_UNIVERSE_MIN_DOLLAR_VOLUME`` — the liquidity floor below
  which a symbol is excluded with a persisted reason (default 0, no floor)
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Iterable, Optional

from .bars import DailyBar
from .config import UniverseConfig
from .membership import MembershipInterval
from .monthly import (
    MonthlyUniverse,
    UniverseBuildResult,
    build_monthly_universe,
    build_monthly_universes,
)
from .store import (
    DATABASE_URL_ENV,
    load_all_monthly_universes,
    load_monthly_universe,
    load_universe_membership,
    persist_monthly_universe,
    persist_universe_membership,
)

__all__ = ["UniverseService", "build_universe_service"]

_ENV_PREFIX = "NULLIUS_UNIVERSE_"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


class UniverseService:
    """Build and persist monthly universes under one configuration.

    Thin by design: every method delegates to the pure computation or the
    store, so the service adds configuration binding and nothing else. The
    database address is captured at construction (from ``DATABASE_URL``)
    and every method still accepts an explicit override, so tests and
    tools can route the same service at a scratch store.
    """

    def __init__(
        self,
        config: Optional[UniverseConfig] = None,
        database_url: Optional[str] = None,
    ) -> None:
        self.config = config if config is not None else UniverseConfig()
        self.database_url = database_url if database_url is not None else os.environ.get(DATABASE_URL_ENV)

    @classmethod
    def from_env(cls) -> "UniverseService":
        """Construct the component the application factory composes."""
        config = UniverseConfig(
            top_n=_env_int(_ENV_PREFIX + "TOP_N", 100),
            window_days=_env_int(_ENV_PREFIX + "WINDOW_DAYS", 30),
            min_observations=_env_int(_ENV_PREFIX + "MIN_OBSERVATIONS", 1),
            # float() accepts "nan" and "-inf"; the config's own validation
            # rejects them, so a bad floor fails the build loudly here.
            min_dollar_volume=_env_float(_ENV_PREFIX + "MIN_DOLLAR_VOLUME", 0.0),
        )
        return cls(config=config)

    def build(
        self,
        bars: Iterable[DailyBar],
        month: str | date | datetime,
        config: Optional[UniverseConfig] = None,
    ) -> MonthlyUniverse:
        """Build the universe effective for one month (see :func:`build_monthly_universe`)."""
        return build_monthly_universe(bars, month, config if config is not None else self.config)

    def build_all(
        self,
        bars: Iterable[DailyBar],
        months: Optional[Iterable[str | date | datetime]] = None,
        config: Optional[UniverseConfig] = None,
    ) -> UniverseBuildResult:
        """Sweep months (see :func:`build_monthly_universes`)."""
        return build_monthly_universes(
            bars, config if config is not None else self.config, months
        )

    def persist(
        self, universe: MonthlyUniverse, database_url: Optional[str] = None
    ) -> int:
        """Persist a build to this service's store (or an explicit one)."""
        return persist_monthly_universe(
            universe, database_url if database_url is not None else self.database_url
        )

    def load(
        self,
        month: str | date | datetime,
        database_url: Optional[str] = None,
    ) -> Optional[MonthlyUniverse]:
        """Load a persisted build from this service's store (or an explicit one)."""
        return load_monthly_universe(
            month, database_url if database_url is not None else self.database_url
        )

    def load_all(self, database_url: Optional[str] = None) -> tuple[MonthlyUniverse, ...]:
        """Load every persisted build, oldest first."""
        return load_all_monthly_universes(
            database_url if database_url is not None else self.database_url
        )

    def membership(
        self, database_url: Optional[str] = None
    ) -> tuple[MembershipInterval, ...]:
        """Read the persisted point-in-time membership table (feature 41).

        The rows are derived from the persisted builds, so reading the
        table and re-deriving it from :meth:`load_all` give the same
        answer — which is the property that makes the table safe for a
        downstream replay to resolve against.
        """
        return load_universe_membership(
            database_url if database_url is not None else self.database_url
        )

    def rebuild_membership(self, database_url: Optional[str] = None) -> int:
        """Re-derive the membership table from the store's builds.

        Every :meth:`persist` already does this; the method exists to
        repair a store whose table was dropped or written by an older
        version, and it is idempotent — running it twice leaves the same
        rows.
        """
        return persist_universe_membership(
            database_url if database_url is not None else self.database_url
        )


def build_universe_service() -> UniverseService:
    """Zero-argument builder registered with the application factory.

    Kept as a named module-level function (rather than passing
    ``UniverseService.from_env`` directly) so the registry shows an
    intention rather than a classmethod, and so tests can assert on the
    builder independently of construction.
    """
    return UniverseService.from_env()
