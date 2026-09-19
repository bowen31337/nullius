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

from .audit import WindowAudit, render_report, survivorship_audit
from .bars import DailyBar
from .config import UniverseConfig
from .gate import SurvivorshipGap, reject_survivorship_gaps, survivorship_gaps
from .history import PriceBar, PriceHistoryStore
from .membership import MembershipInterval
from .monthly import (
    MonthlyUniverse,
    UniverseBuildResult,
    build_monthly_universe,
    build_monthly_universes,
    month_key,
)
from .store import (
    DATABASE_URL_ENV,
    load_all_monthly_universes,
    load_monthly_universe,
    load_survivorship_audit,
    load_universe_membership,
    persist_monthly_universe,
    persist_price_history,
    persist_survivorship_audit,
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
        """Persist a build to this service's store (or an explicit one).

        Refuses the build — :class:`~universe.gate.UniverseBuildRejected`,
        nothing written — when its own trailing window is known to contain
        delistings, is populated in the retained price history, and would
        count ``delisted=0``: that window is on pruned history, and the
        store declines to persist a universe built on it (feature 45).
        """
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

    @property
    def price_history(self) -> PriceHistoryStore:
        """The retained price history bound to this service's store (feature 43).

        A fresh :class:`~universe.history.PriceHistoryStore` each access, routed
        at the same database the builds and membership use, so a window query
        and a build read one history. Thin facade: the store owns the queries.
        """
        return PriceHistoryStore(self.database_url)

    def resolve(
        self, when: str | date | datetime, database_url: Optional[str] = None
    ) -> tuple[str, ...]:
        """The symbols tradable as of ``when`` — membership resolved at a decision time.

        Reads the point-in-time membership table and returns every interval
        that covers ``when``, sorted. This is feature 43's "resolves membership
        as of a decision time" and feature 42's intent, surfaced through the
        same facade: a window built at ``t`` asks this, not the current roster,
        so a symbol that has since left still answers when ``t`` was inside its
        interval.
        """
        intervals = load_universe_membership(
            database_url if database_url is not None else self.database_url
        )
        return tuple(
            interval.symbol
            for interval in intervals
            if interval.covers(when)
        )

    def ingest_prices(
        self, bars: Iterable[PriceBar], database_url: Optional[str] = None
    ) -> int:
        """Retain daily price bars for every symbol (feature 43); returns the count.

        Re-ingesting a restated ``(symbol, date)`` replaces its close in place.
        After the prices land, the survivorship audit is re-derived from the
        full history and every build, so the audit never lags the prices it
        summarises — the same in-transaction coupling :meth:`persist` gives
        membership.
        """
        url = database_url if database_url is not None else self.database_url
        count = persist_price_history(bars, url)
        self._rederive_audit(url)
        return count

    def _rederive_audit(self, database_url: Optional[str]) -> int:
        """Re-derive and persist the survivorship audit from builds + history."""
        from .audit import survivorship_audit

        universes = load_all_monthly_universes(database_url)
        intervals = load_universe_membership(database_url)
        return persist_survivorship_audit(
            universes, intervals, database_url
        )

    def survivorship_audit(
        self,
        months: Optional[Iterable[str | date | datetime]] = None,
        database_url: Optional[str] = None,
    ) -> tuple[WindowAudit, ...]:
        """The survivorship audit, one window per month (feature 44).

        Reads the builds (which supply each window's bounds) and the membership
        table (which supplies the delisted set) and crosses them with the
        retained price history. With ``months`` given, only those months are
        audited; omitted, it audits every persisted build, oldest first.
        """
        url = database_url if database_url is not None else self.database_url
        universes = load_all_monthly_universes(url)
        intervals = load_universe_membership(url)
        return survivorship_audit(
            self.price_history, intervals, _months_only(universes, months), url
        )

    def render_survivorship_report(
        self,
        months: Optional[Iterable[str | date | datetime]] = None,
        database_url: Optional[str] = None,
    ) -> tuple[str, ...]:
        """The survivorship audit rendered as one line per window."""
        return render_report(self.survivorship_audit(months, database_url))

    def survivorship_gaps(
        self,
        months: Optional[Iterable[str | date | datetime]] = None,
        database_url: Optional[str] = None,
    ) -> tuple[SurvivorshipGap, ...]:
        """The windows whose delisted count is 0 but must not be (feature 45).

        Every persisted build whose trailing window the membership table
        says contained delistings, whose price history is populated, and
        whose audit therefore under-reports — the pruning signature the
        gate exists to catch. Reading the gaps does not reject anything:
        this is the operator's inspection, the same facts
        :meth:`reject_survivorship_gaps` would raise on.
        """
        url = database_url if database_url is not None else self.database_url
        universes = load_all_monthly_universes(url)
        intervals = load_universe_membership(url)
        return survivorship_gaps(
            self.price_history, intervals, _months_only(universes, months), url
        )

    def reject_survivorship_gaps(
        self,
        months: Optional[Iterable[str | date | datetime]] = None,
        database_url: Optional[str] = None,
    ) -> None:
        """Raise for every under-reporting window, or return when none.

        The sweep form of the persist path's gate: one
        :class:`~universe.gate.UniverseBuildRejected` naming every month
        whose window is populated, known to contain delistings, and yet
        counts ``delisted=0``. Quiet when every window's zero is honest —
        a clean period, or a period whose history has not landed yet.
        """
        reject_survivorship_gaps(self.survivorship_gaps(months, database_url))


def _months_only(
    universes: tuple[MonthlyUniverse, ...],
    months: Optional[Iterable[str | date | datetime]],
) -> tuple[MonthlyUniverse, ...]:
    """Filter builds to ``months`` (each spelled any way :func:`month_key`
    accepts); no filter means every build.

    One spelling of "only these months" for the audit and the gate, so
    the two cannot disagree about which windows a caller asked for.
    """
    if months is None:
        return universes
    wanted = {month_key(month) for month in months}
    return tuple(universe for universe in universes if universe.month in wanted)


def build_universe_service() -> UniverseService:
    """Zero-argument builder registered with the application factory.

    Kept as a named module-level function (rather than passing
    ``UniverseService.from_env`` directly) so the registry shows an
    intention rather than a classmethod, and so tests can assert on the
    builder independently of construction.
    """
    return UniverseService.from_env()
