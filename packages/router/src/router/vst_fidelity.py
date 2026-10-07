"""Feature 6 of ``additions_spec_vst_fidelity.xml`` — the fidelity report.

*System reports the fidelity distributions from* ``python -m
router.vst_fidelity [--since YYYY-MM-DD] [--book ID]`` *and displays one
JSON object.*  PRD §11.1 is M4's bar: live fills, latency, partial fills,
rounding and funding must match the simulator to within a few basis
points, over *months* of accumulated slots — not one. So this module reads
no plan and places nothing; it is a pure aggregate over what feature 5
already reconciled and feature 2's placements already recorded, across
however much of the store ``--since`` and ``--book`` leave in scope.

**Four tables, one report, no new schema.**  Every figure here is read
straight out of tables this package already owns and already creates:

* :data:`router.fidelity.ORDER_FIDELITY_TABLE` (``router_order_fidelity``)
  — one row per reconciled leg — is the primary index.  :data:`n_orders`
  is its row count in scope, and ``gap_bps``, ``realized_cost_bps``,
  ``expected_cost_bps``, ``maker`` and ``place_to_fill_ms`` all come from
  it directly.
* :data:`router.fidelity.SLOT_FIDELITY_TABLE` (``router_slot_fidelity``)
  — one row per reconciled slot — gives ``n_slots`` and, alongside its own
  ``notional_total``, the weights :func:`_funding_bps_per_day` folds
  ``funding_bps`` over.
* :data:`router.bingx_reconcile.ORDER_FILL_TABLE` (``router_order_fill``)
  carries ``fill_ratio``, a figure feature 5's own per-order table never
  copied.  It is joined to the fidelity table on ``client_order_id`` —
  the venue's own 40-character projection, the one key both tables share
  — rather than read on its own, because it carries no ``book_id`` or
  ``rebalance_ts`` of its own to scope by.
* :data:`router.submission_result.ORDER_RECORD_TABLE`
  (``router_order_record``) carries ``quantity`` (what was sent) and
  ``target_quantity`` (what the plan asked for before step/tick rounding).
  **Rounding drift is read from this table alone, on its own ``book_id``
  and ``rebalance_ts`` — never joined to the fidelity table above.**  A
  leg's rounding is a fact about what was *placed*, settled before the
  venue ever answered, so it is in scope whether or not that slot has been
  reconciled yet; joining it to the fidelity table would silently drop
  every not-yet-reconciled order from the drift figure while leaving it in
  ``n_orders`` for nothing, since ``n_orders`` does not count this table at
  all. So :attr:`FidelityReport.rounding_drift_bps` is the one figure in
  this report with its own, wider, denominator — stated once here rather
  than left for a reader to discover by comparing row counts.

No row from any of the four is ever written by this module: it opens its
own connection, checks each table's existence with ``sqlite_master`` (a
store this report is pointed at before any slot has ever reconciled has
none of them, which is exactly the *empty store* the spec names, not a
fault), and reads.  A table that already exists but holds no row in scope
is the same *empty* as a table that does not exist at all — both read back
as the empty list every aggregate below already treats as "unmeasured".

**The order-level figures are a plain, unweighted sample over legs.**
Feature 5's own per-slot row is the *notional-weighted* mean over a slot's
priced legs — the right figure for "what did this slot cost"; this
report's question is different — "how is the live venue drifting from the
simulator, order by order" — so :func:`_mean` and :func:`_percentile`
below treat every priced leg as one draw, exactly as a PRD bar asking "is
the gap within 3 bps" means "across orders", not "across notional-dollars
once more".

**The bootstrap is seeded so a re-run never relitigates the same number.**
:data:`GAP_BPS_BOOTSTRAP_SEED` and :data:`GAP_BPS_BOOTSTRAP_RESAMPLES` are
module constants precisely so two reports over identical data print
identical intervals — an operator diffing two runs must see the *data*
move, never the dice. The per-order ``gap_bps`` sample is read in one
fixed order (``ORDER BY rebalance_ts, client_order_id``) before a single
resample is drawn, so the determinism holds regardless of what order
SQLite would otherwise hand rows back in.

**``within_tolerance`` is PRD §11.1's own bar, named once.**
:data:`GAP_BPS_TOLERANCE_BPS` is the documented module constant the spec
asks for; the flag is ``None`` exactly when there is no ``gap_bps`` mean
to judge (no priced leg in scope at all) — *unmeasured*, never a false
"in tolerance".

**Exit codes.**  :data:`EXIT_OK` (0) for every report this command could
build, including the empty one.  :data:`EXIT_CONFIG` (2) when
``DATABASE_URL`` names nothing — a configuration fault, not a fidelity
finding, the same split :mod:`canary.run` draws for its own
``EXIT_CONFIG``.  :data:`EXIT_REFUSED` (1) for a fault of the *ask* itself
(an address this module cannot open, a stored row no longer shaped like
one of its own tables) — the store's own failures stay
:class:`~router.errors.RouterStoreError`, exactly as every reader in this
package keeps them.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .bingx_reconcile import ORDER_FILL_TABLE
from .errors import RouterError, RouterStoreError
from .fidelity import FIDELITY_LEG_REJECTED, ORDER_FIDELITY_TABLE, SLOT_FIDELITY_TABLE
from .submission_result import DATABASE_URL_ENV, ORDER_RECORD_TABLE

__all__ = [
    "DATABASE_URL_ENV",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "GAP_BPS_BOOTSTRAP_RESAMPLES",
    "GAP_BPS_BOOTSTRAP_SEED",
    "GAP_BPS_TOLERANCE_BPS",
    "SLOT_WIDTH_HOURS",
    "VST_FIDELITY_CODE",
    "FidelityReport",
    "RouterVstFidelityError",
    "build_report",
    "main",
]

#: The greppable token every refusal this module raises opens with — coined
#: on the module's own name, the convention every sibling in this package
#: keeps.
VST_FIDELITY_CODE = "vst_fidelity"

#: The spec's own three exits: a report (even an empty one), a fault of the
#: ask, and no store to read at all.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIG = 2

#: PRD §11.1's own bar: live fills must match the simulator to within this
#: many basis points of mean gap, or the harness is not yet fit to certify
#: M4's deliverable against. Named once, here, so the flag and the number
#: it is judged against cannot drift apart.
GAP_BPS_TOLERANCE_BPS = 3.0

#: The bootstrap's own seed and resample count — module constants so a
#: second report over the same data prints the same interval.  The count is
#: generous because the whole resample is pure arithmetic over a small
#: in-memory list; nothing here is I/O-bound.
GAP_BPS_BOOTSTRAP_SEED = 0
GAP_BPS_BOOTSTRAP_RESAMPLES = 10_000

#: The scheduled rebalance's own slot width
#: (``additions_spec_bingx_vst_stage2.xml``'s ``REBALANCE_SLOT_HOURS``),
#: restated rather than imported — the same stance
#: :mod:`router.fidelity` takes for this very constant, for the same
#: reason: the unit ``funding_bps_per_day`` annualizes a slot's own
#: ``funding_bps`` over is this module's own law, not a cross-module
#: dependency on a sibling that could change its slot width independently.
SLOT_WIDTH_HOURS = 4.0

#: Basis points per unit of rate or price — the unit every cost figure in
#: this module is spoken in, restated as every sibling in this package
#: restates it.
_BPS_PER_UNIT = Decimal(10_000)


class RouterVstFidelityError(RouterError):
    """A fidelity report this command cannot build.

    Raised for a fault of the *ask* — a blank ``database_url``, a ``since``
    that is not a timezone-aware instant — never for a store with nothing
    reconciled in it yet: an empty scope is :func:`build_report`'s ordinary
    answer (every figure ``None``, both counts ``0``), not a refusal.  The
    store's own read failures and a row shaped like something other than
    this package's own schema stay :class:`~router.errors.RouterStoreError`,
    the split every reader in this package keeps.
    """


def _require_database_url(value: Any) -> str:
    """Return ``value`` as a non-empty database URL, or refuse it by name."""
    if not isinstance(value, str) or not value.strip():
        raise RouterVstFidelityError(
            f"{VST_FIDELITY_CODE}: database_url must be a non-empty string, "
            f"got {value!r} ({type(value).__name__}); the fidelity report "
            "reads the per-order and per-slot tables feature 5 reconciled "
            "into, and a value that names no store names nothing to report "
            "on (feature 6)"
        )
    return value.strip()


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation every store in this package restates in its own
    words: a reader reaches into no sibling's private helper.
    ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is absolute, and
    any other scheme is refused by name.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "VST fidelity report speaks sqlite:/// (the spec's "
            "single-machine allowance); point it at the sqlite database "
            "the BingX VST bot's fidelity reconciliation is stored in "
            "(feature 6)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 6)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path (feature 6)"
        )
    return Path(path)


def _require_aware(moment: Any, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name."""
    if not isinstance(moment, datetime):
        raise RouterVstFidelityError(
            f"{VST_FIDELITY_CODE}: {what} must be a datetime, got {moment!r} "
            f"({type(moment).__name__}) (feature 6)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterVstFidelityError(
            f"{VST_FIDELITY_CODE}: {what}={moment!r} names no timezone; "
            "every rebalance_ts this report compares against is stored in "
            "UTC, and a naive instant cannot be compared to it (feature 6)"
        )
    return moment


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form every sibling table stores."""
    return moment.astimezone(UTC).isoformat()


def _decimal(raw: str, *, what: str) -> Decimal:
    """``raw`` read as an exact :class:`~decimal.Decimal`, or refuse it."""
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise RouterStoreError(
            f"a stored {what}={raw!r} is not a decimal this report can "
            "read (feature 6)"
        ) from exc


# -- Reading the store ---------------------------------------------------


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    """Whether ``table`` exists in this connection's database.

    A store this report is pointed at before any slot has been reconciled
    carries none of this module's four tables; this is what lets every
    read below answer the empty list for it rather than raising on a
    missing table, which is the *empty store* the spec names, not a fault.
    """
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _scope_where(*, book: str | None, since: datetime | None) -> tuple[str, list[Any]]:
    """The ``WHERE`` clause and its bound parameters for ``--book``/``--since``.

    Every query below aliases its scoped table as ``o``, so this clause —
    built once — reads the same whether the query joins a second table or
    not.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if book is not None:
        clauses.append("o.book_id = ?")
        params.append(book)
    if since is not None:
        clauses.append("o.rebalance_ts >= ?")
        params.append(_isoformat_utc(since))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _read_order_fidelity(
    connection: sqlite3.Connection, *, book: str | None, since: datetime | None
) -> list[tuple[Any, ...]]:
    """Every reconciled leg in scope: the report's primary index."""
    if not _table_exists(connection, ORDER_FIDELITY_TABLE):
        return []
    where, params = _scope_where(book=book, since=since)
    return connection.execute(
        "SELECT leg_state, expected_cost_bps, realized_cost_bps, gap_bps, "
        f"maker, place_to_fill_ms, client_order_id FROM {ORDER_FIDELITY_TABLE} "
        f"AS o{where} ORDER BY o.rebalance_ts, o.client_order_id",
        params,
    ).fetchall()


def _read_slot_fidelity(
    connection: sqlite3.Connection, *, book: str | None, since: datetime | None
) -> list[tuple[Any, ...]]:
    """Every reconciled slot in scope: ``n_slots`` and the funding weights."""
    if not _table_exists(connection, SLOT_FIDELITY_TABLE):
        return []
    where, params = _scope_where(book=book, since=since)
    return connection.execute(
        f"SELECT notional_total, funding_bps FROM {SLOT_FIDELITY_TABLE} AS o"
        f"{where} ORDER BY o.rebalance_ts",
        params,
    ).fetchall()


def _read_fill_ratios(
    connection: sqlite3.Connection, *, book: str | None, since: datetime | None
) -> list[float]:
    """Every reconciled leg's ``fill_ratio`` in scope, joined by the venue's
    own 40-character projection — the one key both tables share, and the
    only one :data:`ORDER_FILL_TABLE` carries at all."""
    if not (
        _table_exists(connection, ORDER_FIDELITY_TABLE)
        and _table_exists(connection, ORDER_FILL_TABLE)
    ):
        return []
    where, params = _scope_where(book=book, since=since)
    rows = connection.execute(
        f"SELECT f.fill_ratio FROM {ORDER_FIDELITY_TABLE} AS o "
        f"JOIN {ORDER_FILL_TABLE} AS f ON f.client_order_id = o.client_order_id"
        f"{where} ORDER BY o.rebalance_ts, o.client_order_id",
        params,
    ).fetchall()
    return [row[0] for row in rows if row[0] is not None]


def _read_order_records(
    connection: sqlite3.Connection, *, book: str | None, since: datetime | None
) -> list[tuple[Any, ...]]:
    """Every placed order's own terms in scope — rounding drift's own,
    wider, universe (see the module docstring)."""
    if not _table_exists(connection, ORDER_RECORD_TABLE):
        return []
    where, params = _scope_where(book=book, since=since)
    return connection.execute(
        "SELECT quantity, target_quantity, reference_price FROM "
        f"{ORDER_RECORD_TABLE} AS o{where} ORDER BY o.rebalance_ts, "
        "o.client_order_id",
        params,
    ).fetchall()


# -- Statistics ------------------------------------------------------------


def _mean(values: Sequence[float]) -> float | None:
    """The plain arithmetic mean, or ``None`` over an empty sample."""
    return (sum(values) / len(values)) if values else None


def _interpolated_percentile(ordered: Sequence[float], pct: float) -> float:
    """The ``pct``-th percentile of an already-sorted, non-empty ``ordered``,
    by linear interpolation between the two nearest ranks — the
    conventional ("linear") method."""
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    fraction = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _percentile(values: Sequence[float], pct: float) -> float | None:
    """The ``pct``-th percentile of ``values``, or ``None`` over an empty
    sample — the report's own face of :func:`_interpolated_percentile`."""
    return _interpolated_percentile(sorted(values), pct) if values else None


def _bootstrap_mean_ci(
    values: Sequence[float], *, seed: int, resamples: int
) -> tuple[float, float]:
    """A seeded 95% percentile-bootstrap interval for the mean of ``values``.

    ``values`` must be non-empty and already in a fixed, deterministic
    order (every caller here reads its sample with an explicit ``ORDER
    BY`` before this runs) — the resample draws depend on both the seed
    *and* the input order, and a sample built from an unordered read would
    make the "seeded, so it is deterministic" promise hollow.
    """
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(resamples))
    return (
        _interpolated_percentile(means, 2.5),
        _interpolated_percentile(means, 97.5),
    )


# -- The report -------------------------------------------------------------


@dataclass(frozen=True)
class FidelityReport:
    """One answer to ``python -m router.vst_fidelity`` — the whole of
    :meth:`to_json`'s object, held as a value so a caller that wants the
    figures rather than the JSON need not re-parse its own output."""

    n_orders: int
    n_slots: int
    gap_bps_mean: float | None
    gap_bps_ci_low: float | None
    gap_bps_ci_high: float | None
    realized_cost_bps_p50: float | None
    realized_cost_bps_p95: float | None
    expected_cost_bps_p50: float | None
    expected_cost_bps_p95: float | None
    place_to_fill_ms_p50: float | None
    place_to_fill_ms_p95: float | None
    place_to_fill_ms_p99: float | None
    fill_ratio_mean: float | None
    maker_share: float | None
    reject_rate: float | None
    rounding_drift_bps: float | None
    funding_bps_per_day: float | None
    within_tolerance: bool | None

    def to_json(self) -> dict[str, Any]:
        """The one JSON object ``main`` prints — every field of this
        value, nested the way the spec groups them: a distribution with
        more than one statistic gets its own object, a single figure
        stays a bare key."""
        return {
            "n_orders": self.n_orders,
            "n_slots": self.n_slots,
            "gap_bps": {
                "mean": self.gap_bps_mean,
                "ci_low": self.gap_bps_ci_low,
                "ci_high": self.gap_bps_ci_high,
            },
            "realized_cost_bps": {
                "p50": self.realized_cost_bps_p50,
                "p95": self.realized_cost_bps_p95,
            },
            "expected_cost_bps": {
                "p50": self.expected_cost_bps_p50,
                "p95": self.expected_cost_bps_p95,
            },
            "place_to_fill_ms": {
                "p50": self.place_to_fill_ms_p50,
                "p95": self.place_to_fill_ms_p95,
                "p99": self.place_to_fill_ms_p99,
            },
            "fill_ratio_mean": self.fill_ratio_mean,
            "maker_share": self.maker_share,
            "reject_rate": self.reject_rate,
            "rounding_drift_bps": self.rounding_drift_bps,
            "funding_bps_per_day": self.funding_bps_per_day,
            "within_tolerance": self.within_tolerance,
        }


def _rounding_drift_bps(record_rows: Sequence[tuple[Any, ...]]) -> float | None:
    """The notional-weighted drift of sent quantity against target quantity,
    in bps of target notional — ``None`` when no row in scope ever
    recorded a ``target_quantity`` (an upgraded store's pre-feature-2 rows,
    or an empty scope)."""
    weighted_drift = Decimal(0)
    weighted_notional = Decimal(0)
    for quantity_raw, target_raw, reference_raw in record_rows:
        if target_raw is None:
            continue
        quantity = _decimal(quantity_raw, what="quantity")
        target = _decimal(target_raw, what="target_quantity")
        reference = _decimal(reference_raw, what="reference_price")
        weighted_drift += (quantity - target) * reference
        weighted_notional += target * reference
    if weighted_notional <= 0:
        return None
    return float(weighted_drift / weighted_notional * _BPS_PER_UNIT)


def _funding_bps_per_day(slot_rows: Sequence[tuple[Any, ...]]) -> float | None:
    """The notional-weighted mean slot ``funding_bps``, annualized to a day
    over :data:`SLOT_WIDTH_HOURS` — ``None`` when no slot in scope ever
    measured funding (every slot's own ``notional_total`` was zero)."""
    weighted_funding = 0.0
    weighted_notional = 0.0
    for notional_raw, funding_bps in slot_rows:
        if funding_bps is None:
            continue
        notional = float(_decimal(notional_raw, what="notional_total"))
        weighted_funding += funding_bps * notional
        weighted_notional += notional
    if weighted_notional <= 0:
        return None
    per_slot = weighted_funding / weighted_notional
    return per_slot * (24.0 / SLOT_WIDTH_HOURS)


def build_report(
    database_url: str, *, since: datetime | None = None, book: str | None = None
) -> FidelityReport:
    """Read the store and answer the whole fidelity report.

    ``since`` (when given) must be a timezone-aware instant — the CLI
    builds it from ``--since YYYY-MM-DD`` at UTC midnight. ``book`` (when
    given) narrows every read to that exact ``book_id``.  Neither argument
    narrowing to nothing is a fault: it is this function's ordinary,
    documented *empty* answer (see the module docstring).

    Opens its own connection and never writes: a report pointed at a store
    that has never reconciled a single slot reads back four empty lists,
    not a missing-table error.  Fails with
    :class:`~router.errors.RouterStoreError` when the address cannot be
    opened or a stored row is no longer shaped like this package's own
    schema.
    """
    url = _require_database_url(database_url)
    if since is not None:
        since = _require_aware(since, "since")

    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = sqlite3.connect(path)
    except sqlite3.OperationalError as exc:
        raise RouterStoreError(
            f"could not open the fidelity store at {path}: {exc}"
        ) from exc
    try:
        with closing(connection):
            order_rows = _read_order_fidelity(connection, book=book, since=since)
            slot_rows = _read_slot_fidelity(connection, book=book, since=since)
            fill_ratios = _read_fill_ratios(connection, book=book, since=since)
            record_rows = _read_order_records(connection, book=book, since=since)
    except sqlite3.Error as exc:
        raise RouterStoreError(
            f"could not read the fidelity store at {path}: {exc}"
        ) from exc

    n_orders = len(order_rows)
    leg_states = [row[0] for row in order_rows]
    expected_values = [row[1] for row in order_rows if row[1] is not None]
    realized_values = [row[2] for row in order_rows if row[2] is not None]
    gap_values = [row[3] for row in order_rows if row[3] is not None]
    maker_values = [row[4] for row in order_rows if row[4] is not None]
    place_to_fill_values = [row[5] for row in order_rows if row[5] is not None]

    gap_bps_mean = _mean(gap_values)
    if gap_values:
        gap_bps_ci_low, gap_bps_ci_high = _bootstrap_mean_ci(
            gap_values, seed=GAP_BPS_BOOTSTRAP_SEED, resamples=GAP_BPS_BOOTSTRAP_RESAMPLES
        )
    else:
        gap_bps_ci_low = gap_bps_ci_high = None

    return FidelityReport(
        n_orders=n_orders,
        n_slots=len(slot_rows),
        gap_bps_mean=gap_bps_mean,
        gap_bps_ci_low=gap_bps_ci_low,
        gap_bps_ci_high=gap_bps_ci_high,
        realized_cost_bps_p50=_percentile(realized_values, 50),
        realized_cost_bps_p95=_percentile(realized_values, 95),
        expected_cost_bps_p50=_percentile(expected_values, 50),
        expected_cost_bps_p95=_percentile(expected_values, 95),
        place_to_fill_ms_p50=_percentile(place_to_fill_values, 50),
        place_to_fill_ms_p95=_percentile(place_to_fill_values, 95),
        place_to_fill_ms_p99=_percentile(place_to_fill_values, 99),
        fill_ratio_mean=_mean(fill_ratios),
        maker_share=_mean([float(value) for value in maker_values]),
        reject_rate=(
            leg_states.count(FIDELITY_LEG_REJECTED) / n_orders if n_orders else None
        ),
        rounding_drift_bps=_rounding_drift_bps(record_rows),
        funding_bps_per_day=_funding_bps_per_day(slot_rows),
        within_tolerance=(
            None if gap_bps_mean is None else abs(gap_bps_mean) <= GAP_BPS_TOLERANCE_BPS
        ),
    )


# -- The CLI ------------------------------------------------------------


def _since_date(value: str) -> date:
    """``--since``'s own ``type=``: a bare ``YYYY-MM-DD``, nothing wider."""
    return date.fromisoformat(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m router.vst_fidelity",
        description=(
            "Report the VST fidelity harness's distributions: gap_bps "
            "(mean, 95% bootstrap interval), realized and expected cost "
            "(p50/p95), place-to-fill latency (p50/p95/p99), fill ratio, "
            "maker share, reject rate, rounding drift and funding, over "
            "every slot router.fidelity.reconcile_fidelity has reconciled. "
            "Prints one JSON object to stdout. Exits 2 when DATABASE_URL "
            "names no store."
        ),
    )
    parser.add_argument(
        "--since",
        type=_since_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="only include slots at or after this UTC date",
    )
    parser.add_argument(
        "--book",
        type=str,
        default=None,
        metavar="ID",
        help="only include this book_id",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    database_url: str | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m router.vst_fidelity [--since YYYY-MM-DD] [--book ID]``.

    Checks ``DATABASE_URL`` before anything else — absent, this prints one
    line to stderr and returns :data:`EXIT_CONFIG`, because an unconfigured
    deployment is a configuration fault, not a fidelity finding, exactly
    the split :mod:`canary.run` draws for its own ``EXIT_CONFIG``. With a
    store named, builds the report (:func:`build_report`) and prints its
    :meth:`FidelityReport.to_json` as one JSON line, returning
    :data:`EXIT_OK` — including for the empty store the spec names, whose
    report is every count zero and every distribution ``None`` rather than
    a refusal.

    A :class:`~router.errors.RouterError` raised while building the report
    — an address this module cannot open, a stored row no longer shaped
    like this package's own schema — is printed to stderr with no
    traceback and answered :data:`EXIT_REFUSED`.

    ``env``, ``database_url`` and ``emit`` are this command's seams, read
    and written exactly as the other operator CLIs in this workspace take
    them.
    """
    arguments = _build_parser().parse_args(argv)
    source = os.environ if env is None else env
    url = (database_url if database_url is not None else source.get(DATABASE_URL_ENV, ""))
    url = (url or "").strip()
    if not url:
        print(
            f"{DATABASE_URL_ENV} must name the sqlite database the BingX "
            "VST bot's per-order and per-slot fidelity reconciliation is "
            "stored in; set it and run again",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    since = (
        datetime.combine(arguments.since, time.min, tzinfo=UTC)
        if arguments.since is not None
        else None
    )

    try:
        report = build_report(url, since=since, book=arguments.book)
    except RouterError as exc:
        message = str(exc)
        prefix = f"{VST_FIDELITY_CODE}: "
        if not message.startswith(prefix):
            message = prefix + message
        print(message, file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(report.to_json()))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
