"""``python -m orchestrator.shadow_eval`` — score the forward VST shadow.

additions_spec_shadow_eval.xml, "Forward Shadow" feature 2: *System scores
the forward VST shadow against its pre-registered primary outcome from the
book history and the shadow lake, so that the test's verdict is computed by
fixed code rather than by hand.*

The primary outcome P is pinned in ``docs/preregistration/2026-10-15-shadow-v1.md``
and its ``.ADDENDUM.md``: for each window day d, ``r_d`` is a price term, a
funding term and a cost term over the book in force on d, and the pass rule
is ``Σ r_d > 0`` and ``mean(r)/sd(r)·√n ≥ 1.0``. This module reads that
formula's three inputs — the history books under ``--history``, the sealed
shadow lake under ``--snapshot``, and (optionally) ``vst.db`` for when a book
actually started trading and how the venue executed it — and answers one
JSON report, never by hand.

**The book schedule is read, never rebuilt.** Every ``history/shadow-*.json``
file is one book :mod:`orchestrator.shadow` wrote and a human or a cron job
copied in — this module trusts the file's own ``rebalance_ts`` for the
decision date and only cross-checks it against the ``book_id`` the writer
derived from the same date, so a corrupted or hand-edited history is refused
rather than silently rescored (see :func:`_read_history_books`). It never
calls :func:`orchestrator._shadow.shadow_weights` or touches a node's code:
the weights it scores are exactly the weights that were traded, a pure
replay of what the book history already states.

**A book is "in force" from the day after it starts trading, not the day it
was decided.** With ``vst.db`` the first full UTC day comes from
``router_bingx_slot_completion``'s earliest ``finished_at`` for that
``book_id``; without it (or a book the bot never completed a slot for) the
nominal ``decision_date + 2`` stands in, and the report says so
(``in_force_rule``). Scoring walks the window day by day, re-deriving the
book in force on every day and the day before it, so a switch between two
books charges its turnover exactly once, on the day the switch actually took
effect.

**Validity is a separate question from the pass/fail verdict**, and it is
only ever answered from ``vst.db``: the grid of decision dates actually
produced books the bot started and finished slots for, the venue placed at
least 90% of the target legs (a position carried unchanged from an earlier
book counts as placed), and no two consecutive 4-hour slots both failed.
Without ``vst.db`` the report says ``validity: "unchecked"`` rather than
guessing from the lake alone, which carries no execution facts.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from snapshot import (
    SnapshotError,
    SnapshotMount,
    SnapshotNameError,
    parse_snapshot_name,
)

from ._context import FUTBARS_STREAM, _read_close, _read_funding_rate_sum

__all__ = ["ShadowEvalError", "main"]

#: The greppable code word every :class:`ShadowEvalError` opens with.
SHADOW_EVAL_CODE = "shadow_eval"

DATABASE_URL_ENV = "DATABASE_URL"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_MISSING = 2

#: The lake quote suffix every BingX USDT-margined contract shares, and the
#: "larger-denomination" prefix a handful of symbols carry — the same two
#: constants :mod:`orchestrator.shadow`'s own ``_map_to_bingx`` uses, local
#: here because this module runs the mapping in the other direction and
#: reaches for neither that function nor its module.
_LAKE_QUOTE_SUFFIX = "USDT"
_THOUSAND_PREFIX = "1000"

#: A history book's own filename stem, and the shape every ``book_id`` the
#: writer (:mod:`orchestrator.shadow`) derives must take: ``shadow-<decision
#: date>-<12 hex of the sorted node ids' sha256>``.
_BOOK_ID_RE = re.compile(r"^shadow-(\d{4}-\d{2}-\d{2})-([0-9a-f]{12})$")

_DEFAULT_HISTORY_DIR = Path.home() / ".local/share/nullius/shadow/history"
_DEFAULT_LAKE_SNAPSHOTS_DIR = Path.home() / ".local/share/nullius/lake-shadow/snapshots"
_DEFAULT_WINDOW_START = dt.datetime(2026, 10, 20, 12, 5, tzinfo=dt.UTC)
_DEFAULT_WINDOW_END = dt.datetime(2027, 1, 18, 12, 5, tzinfo=dt.UTC)
_DEFAULT_FIRST_DECISION = dt.date(2026, 10, 19)
_DEFAULT_GRID_ANCHOR = dt.date(2022, 1, 3)
_DEFAULT_GRID_DAYS = 14
_DEFAULT_COST_BPS = 5.0

#: The nominal in-force lag when no ``vst.db`` completion row exists for a
#: book — the pre-registration's own "D+1" build lag plus one day for the
#: first full UTC day traded (see the ADDENDUM's "first traded slot").
_NOMINAL_IN_FORCE_LAG_DAYS = 2

#: ``in_force_rule``'s two values.
_IN_FORCE_TRADED = "traded"
_IN_FORCE_NOMINAL = "nominal"

#: The forward horizon ``forward_ic_10d`` measures — ten calendar days,
#: pinned by the pre-registration's own secondary outcome ("forward IC per
#: decision date and per node, against the next 10 days' perp returns").
_FORWARD_IC_HORIZON_DAYS = 10

#: The benchmark the realised beta regresses against, and leg coverage's
#: minimum fraction — both the pre-registration's own figures.
_BENCHMARK_SYMBOL = "BTCUSDT"
_MIN_LEG_COVERAGE = 0.9

#: The tables this module reads from ``vst.db``, restated here as plain
#: strings: :mod:`orchestrator` does not depend on :mod:`router` or
#: :mod:`risk` (the research and the trading sides of this workspace are
#: separate workspace members on purpose), so the table names and column
#: shapes are duplicated from their owning modules rather than imported —
#: the same "every store restates its own URL translation and table name"
#: idiom :mod:`orchestrator.shadow` already takes for the node table.
_SLOT_COMPLETION_TABLE = "router_bingx_slot_completion"
_ORDER_RECORD_TABLE = "router_order_record"
_DAILY_OPENING_EQUITY_TABLE = "router_daily_opening_equity"
_DAILY_LOSS_HALT_TABLE = "risk_daily_loss_halt"

#: A rebalance slot's width — :mod:`router.bingx_rebalance`'s own
#: ``REBALANCE_SLOT_HOURS``, restated for the same reason as the table names.
_SLOT_HOURS = 4


class ShadowEvalError(Exception):
    """This command's own refusal — the ask's fault, not a collaborator's.

    Raised, and only raised, by this module: a history file that will not
    read or parse, a ``book_id`` that disagrees with its own ``rebalance_ts``
    or with a sibling book's, a deviation in the traded nodes (two books
    carrying different node-hash suffixes), a BingX symbol this module
    cannot invert to a lake symbol, or a window with no book yet in force.
    Every message opens with :data:`SHADOW_EVAL_CODE`, and :func:`main`
    prints it as the one stderr line and exits :data:`EXIT_REFUSED` — never
    a traceback.
    """


# -- the history books ---------------------------------------------------------


class _HistoryBook:
    """One ``history/shadow-*.json`` file, read and internally validated.

    ``decision_date`` is read from ``rebalance_ts`` (the pre-registration's
    own rule — *"the decision date comes from rebalance_ts"*), and checked
    against the date ``book_id`` itself carries; ``weights`` is the document's
    own BingX-symbol-keyed mapping, coerced to ``float``.
    """

    __slots__ = ("book_id", "decision_date", "node_hash", "path", "weights")

    def __init__(
        self,
        *,
        book_id: str,
        decision_date: dt.date,
        node_hash: str,
        weights: Mapping[str, float],
        path: Path,
    ) -> None:
        self.book_id = book_id
        self.decision_date = decision_date
        self.node_hash = node_hash
        self.weights = weights
        self.path = path


def _read_json(path: Path, what: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: {what} at {str(path)!r} cannot be read: {exc}"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: {what} at {str(path)!r} is not JSON: {exc}"
        ) from exc


def _parse_history_book(path: Path) -> _HistoryBook:
    document = _read_json(path, "a history book")
    if not isinstance(document, Mapping):
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: the history book at {str(path)!r} is not a "
            "JSON object"
        )
    raw_book_id = document.get("book_id")
    if not isinstance(raw_book_id, str):
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: the history book at {str(path)!r} states "
            f"book_id={raw_book_id!r}, not a string"
        )
    match = _BOOK_ID_RE.match(raw_book_id)
    if match is None:
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: book_id {raw_book_id!r} at {str(path)!r} "
            "is not shadow-<decision date>-<12 hex node hash>"
        )
    id_date = dt.date.fromisoformat(match.group(1))
    node_hash = match.group(2)

    raw_ts = document.get("rebalance_ts")
    if not isinstance(raw_ts, str):
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: book {raw_book_id!r} at {str(path)!r} "
            f"states rebalance_ts={raw_ts!r}, not a string"
        )
    try:
        rebalance_ts = dt.datetime.fromisoformat(raw_ts)
    except ValueError as exc:
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: book {raw_book_id!r} at {str(path)!r} "
            f"states rebalance_ts={raw_ts!r}, which is not ISO 8601: {exc}"
        ) from exc
    if rebalance_ts.tzinfo is None:
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: book {raw_book_id!r} at {str(path)!r} "
            f"states rebalance_ts={raw_ts!r}, which names no timezone"
        )
    decision_date = rebalance_ts.astimezone(dt.UTC).date()
    if decision_date != id_date:
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: book {raw_book_id!r} at {str(path)!r} "
            f"names decision date {id_date.isoformat()} in its own id, but "
            f"rebalance_ts {raw_ts!r} is {decision_date.isoformat()} — the "
            "decision date comes from rebalance_ts, and must agree with "
            "book_id"
        )

    raw_weights = document.get("weights")
    if not isinstance(raw_weights, Mapping):
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: book {raw_book_id!r} at {str(path)!r} "
            f"states weights={raw_weights!r}, not a JSON object"
        )
    weights: dict[str, float] = {}
    for symbol, value in raw_weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ShadowEvalError(
                f"{SHADOW_EVAL_CODE}: book {raw_book_id!r} at {str(path)!r} "
                f"gives {symbol!r} a non-numeric weight {value!r}"
            )
        weights[symbol] = float(value)

    return _HistoryBook(
        book_id=raw_book_id,
        decision_date=decision_date,
        node_hash=node_hash,
        weights=weights,
        path=path,
    )


def _read_history_books(history_dir: Path, first_decision: dt.date) -> list[_HistoryBook]:
    """Every qualifying history book, refusing a deviation or a conflict.

    Reads every ``shadow-*.json`` file, keeps those with a decision date at
    or after ``first_decision``, and refuses (see :class:`ShadowEvalError`)
    when two books name the same decision date under different ``book_id``s,
    or when any two qualifying books carry different node-hash suffixes —
    *"changing the nodes is a deviation, not an input."*
    """
    paths = sorted(history_dir.glob("shadow-*.json"))
    books = [_parse_history_book(path) for path in paths]
    qualifying = [book for book in books if book.decision_date >= first_decision]

    by_date: dict[dt.date, list[_HistoryBook]] = defaultdict(list)
    for book in qualifying:
        by_date[book.decision_date].append(book)
    for decision_date, group in sorted(by_date.items()):
        distinct_ids = {book.book_id for book in group}
        if len(distinct_ids) > 1:
            raise ShadowEvalError(
                f"{SHADOW_EVAL_CODE}: decision date {decision_date.isoformat()} "
                f"has {len(distinct_ids)} different book_ids in {str(history_dir)!r}: "
                f"{sorted(distinct_ids)!r}"
            )

    distinct_hashes = {book.node_hash for book in qualifying}
    if len(distinct_hashes) > 1:
        by_hash: dict[str, list[str]] = defaultdict(list)
        for book in qualifying:
            by_hash[book.node_hash].append(book.book_id)
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: the history carries {len(distinct_hashes)} "
            f"different node-hash suffixes since {first_decision.isoformat()}: "
            f"{dict(sorted(by_hash.items()))!r}; changing the nodes is a "
            "deviation, not an input"
        )

    return sorted(
        {book.decision_date: book for book in qualifying}.values(),
        key=lambda book: book.decision_date,
    )


# -- BingX symbol -> lake symbol, inverting orchestrator.shadow._map_to_bingx --


def _invert_to_lake_symbol(bingx_symbol: str, futbars_partitions: Collection[str]) -> str:
    """The lake (futbars) symbol a BingX symbol was derived from.

    Inverts :func:`orchestrator.shadow._map_to_bingx`: ``"X-USDT"`` always
    comes from ``"XUSDT"``; a ``"1000"``-prefixed symbol like
    ``"1000X-USDT"`` comes from ``"1000XUSDT"`` when that partition exists in
    the snapshot's futbars, else from the plain ``"XUSDT"`` the forward
    mapping fell back to. Refuses, naming the symbol, when the symbol is not
    shaped ``BASE-USDT`` at all (an ambiguous inverse — there is no base/quote
    split to invert), or when a ``"1000"``-prefixed symbol inverts to neither
    candidate the snapshot carries (a missing inverse).
    """
    if bingx_symbol.count("-") != 1 or not bingx_symbol.endswith(
        f"-{_LAKE_QUOTE_SUFFIX}"
    ):
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: {bingx_symbol!r} is not a BASE-USDT BingX "
            "symbol; its lake symbol is ambiguous"
        )
    base = bingx_symbol[: -len(f"-{_LAKE_QUOTE_SUFFIX}")]
    if base.startswith(_THOUSAND_PREFIX) and len(base) > len(_THOUSAND_PREFIX):
        thousand_candidate = f"{base}{_LAKE_QUOTE_SUFFIX}"
        stripped_candidate = f"{base[len(_THOUSAND_PREFIX):]}{_LAKE_QUOTE_SUFFIX}"
        if thousand_candidate in futbars_partitions:
            return thousand_candidate
        if stripped_candidate in futbars_partitions:
            return stripped_candidate
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: {bingx_symbol!r} inverts to neither "
            f"{thousand_candidate!r} nor {stripped_candidate!r}, and the "
            "snapshot's futbars carries neither partition"
        )
    return f"{base}{_LAKE_QUOTE_SUFFIX}"


def _build_symbol_map(
    books: Sequence[_HistoryBook], futbars_partitions: Collection[str]
) -> dict[str, str]:
    """Every BingX symbol any qualifying book names, mapped to its lake symbol."""
    mapping: dict[str, str] = {}
    for book in books:
        for symbol in book.weights:
            if symbol not in mapping:
                mapping[symbol] = _invert_to_lake_symbol(symbol, futbars_partitions)
    return mapping


# -- sqlite: vst.db ------------------------------------------------------------


def _sqlite_path_from_url(database_url: str) -> Path | None:
    """The filesystem path a ``sqlite:///`` ``DATABASE_URL`` names, or ``None``."""
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        return None
    path = unquote(parsed.path).removeprefix("/")
    return Path(path) if path else None


def _resolve_vst_db_path(explicit: Path | None, source: Mapping[str, str]) -> Path | None:
    if explicit is not None:
        return explicit
    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        return None
    return _sqlite_path_from_url(database_url)


def _connect_vst_db(path: Path | None) -> sqlite3.Connection | None:
    """A read connection to ``vst.db``, or ``None`` when there is nothing to read.

    A ``path`` that does not exist is treated the same as no path at all —
    every caller already degrades to the "no vst.db" answer (the nominal
    in-force rule, ``validity: "unchecked"``) for that case, and connecting
    would otherwise create an empty database file as a side effect of a
    read-only report.
    """
    if path is None or not path.is_file():
        return None
    return sqlite3.connect(str(path))


def _query(connection: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[Any]:
    """Run ``sql``, answering ``[]`` when the table it names does not exist yet."""
    try:
        return connection.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _earliest_finished_at(connection: sqlite3.Connection, book_id: str) -> dt.datetime | None:
    rows = _query(
        connection,
        f"SELECT finished_at FROM {_SLOT_COMPLETION_TABLE} WHERE book_id = ? "
        "ORDER BY finished_at ASC LIMIT 1",
        (book_id,),
    )
    if not rows:
        return None
    return dt.datetime.fromisoformat(rows[0][0])


# -- in-force schedule ----------------------------------------------------------


class _ScheduledBook:
    """One history book, dated for in-force scheduling and output.

    ``lake_weights`` is :attr:`_HistoryBook.weights` re-keyed to lake
    symbols through the snapshot's own inverse mapping — the series the
    daily r_d walk and :func:`_forward_ic` read closes and funding for.
    """

    __slots__ = ("book", "in_force_from", "in_force_rule", "lake_weights")

    def __init__(
        self,
        *,
        book: _HistoryBook,
        in_force_from: dt.date,
        in_force_rule: str,
        lake_weights: Mapping[str, float],
    ) -> None:
        self.book = book
        self.in_force_from = in_force_from
        self.in_force_rule = in_force_rule
        self.lake_weights = lake_weights


def _schedule_books(
    books: Sequence[_HistoryBook],
    symbol_map: Mapping[str, str],
    connection: sqlite3.Connection | None,
) -> list[_ScheduledBook]:
    scheduled = []
    for book in books:
        in_force_rule = _IN_FORCE_NOMINAL
        in_force_from = book.decision_date + dt.timedelta(days=_NOMINAL_IN_FORCE_LAG_DAYS)
        if connection is not None:
            earliest = _earliest_finished_at(connection, book.book_id)
            if earliest is not None:
                in_force_from = earliest.astimezone(dt.UTC).date() + dt.timedelta(days=1)
                in_force_rule = _IN_FORCE_TRADED
        lake_weights = {symbol_map[symbol]: weight for symbol, weight in book.weights.items()}
        scheduled.append(
            _ScheduledBook(
                book=book,
                in_force_from=in_force_from,
                in_force_rule=in_force_rule,
                lake_weights=lake_weights,
            )
        )
    return scheduled


def _book_in_force(scheduled: Sequence[_ScheduledBook], day: dt.date) -> _ScheduledBook | None:
    """The book in force on ``day`` — the latest whose ``in_force_from`` <= day."""
    candidate: _ScheduledBook | None = None
    for entry in sorted(scheduled, key=lambda s: s.in_force_from):
        if entry.in_force_from <= day:
            candidate = entry
        else:
            break
    return candidate


# -- window days -----------------------------------------------------------------


def _window_days(window_start: dt.datetime, window_end: dt.datetime) -> list[dt.date]:
    """Every whole UTC day d with ``window_start < d 00:00`` and ``d+1 00:00 <= window_end``."""
    days: list[dt.date] = []
    cursor = window_start.astimezone(dt.UTC).date()
    last_possible = window_end.astimezone(dt.UTC).date() + dt.timedelta(days=1)
    while cursor <= last_possible:
        midnight = dt.datetime.combine(cursor, dt.time(0), tzinfo=dt.UTC)
        next_midnight = midnight + dt.timedelta(days=1)
        if window_start < midnight and next_midnight <= window_end:
            days.append(cursor)
        cursor += dt.timedelta(days=1)
    return days


# -- rank correlation and OLS slope, restated locally ----------------------------
#
# Both are the same arithmetic evaluator._decay._rank_correlation and
# compute_node_metrics already pin for their own coefficients — restated here
# because orchestrator.shadow_eval reads a persisted book's weights, never a
# RawScoreVector or a PostCostReturns, so there is no shared value to call
# that private module with; duplicating the formula is cheaper than reaching
# into another member's private module for it.


def _average_ranks(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted((value, key) for key, value in values.items())
    ranks: dict[str, float] = {}
    index = 0
    n = len(ordered)
    while index < n:
        stop = index
        while stop + 1 < n and ordered[stop + 1][0] == ordered[index][0]:
            stop += 1
        shared = (index + 1 + stop + 1) / 2.0
        for position in range(index, stop + 1):
            ranks[ordered[position][1]] = shared
        index = stop + 1
    return ranks


def _spearman(a: Mapping[str, float], b: Mapping[str, float]) -> float | None:
    """The Spearman rank correlation of ``a`` and ``b`` over their shared keys.

    ``None`` when fewer than two keys are shared, or either side has zero
    rank spread (constant) — the coefficient is undefined there, and ``None``
    is the honest answer the caller already treats as "not available".
    """
    symbols = sorted(set(a) & set(b))
    if len(symbols) < 2:
        return None
    a_ranks = _average_ranks({symbol: a[symbol] for symbol in symbols})
    b_ranks = _average_ranks({symbol: b[symbol] for symbol in symbols})
    n = float(len(symbols))
    a_mean = math.fsum(a_ranks.values()) / n
    b_mean = math.fsum(b_ranks.values()) / n
    covariance = math.fsum(
        (a_ranks[symbol] - a_mean) * (b_ranks[symbol] - b_mean) for symbol in symbols
    )
    a_spread = math.fsum((a_ranks[symbol] - a_mean) ** 2 for symbol in symbols)
    b_spread = math.fsum((b_ranks[symbol] - b_mean) ** 2 for symbol in symbols)
    if a_spread == 0.0 or b_spread == 0.0:
        return None
    return covariance / math.sqrt(a_spread * b_spread)


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """The slope of ``ys`` regressed on ``xs`` — ``None`` when ``xs`` has no spread."""
    n = len(xs)
    if n < 2:
        return None
    x_mean = math.fsum(xs) / n
    y_mean = math.fsum(ys) / n
    covariance = math.fsum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    variance = math.fsum((x - x_mean) ** 2 for x in xs)
    if variance == 0.0:
        return None
    return covariance / variance


# -- closes and funding, read from the mount and memoized ------------------------


class _LakeReader:
    """Cached, crash-free reads of one symbol's futbars close and funding."""

    def __init__(self, mount: SnapshotMount) -> None:
        self._mount = mount
        self._close_cache: dict[tuple[str, dt.date], float | None] = {}
        self._funding_cache: dict[tuple[str, dt.date], float | None] = {}

    def close(self, symbol: str, day: dt.date) -> float | None:
        key = (symbol, day)
        if key not in self._close_cache:
            try:
                self._close_cache[key] = _read_close(
                    self._mount,
                    symbol,
                    day,
                    stream=FUTBARS_STREAM,
                    day_column="date",
                    close_column="fut_close",
                )
            except KeyError:
                self._close_cache[key] = None
        return self._close_cache[key]

    def funding(self, symbol: str, day: dt.date) -> float | None:
        key = (symbol, day)
        if key not in self._funding_cache:
            try:
                self._funding_cache[key] = _read_funding_rate_sum(self._mount, symbol, day)
            except KeyError:
                self._funding_cache[key] = None
        return self._funding_cache[key]


# -- the daily r_d walk -----------------------------------------------------------


class _MissingTracker:
    """One entry per (symbol, day) missing a close or a funding row, first 20 kept."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, dt.date], set[str]] = {}

    def mark(self, symbol: str, day: dt.date, what: str) -> None:
        self._by_key.setdefault((symbol, day), set()).add(what)

    def count(self) -> int:
        return len(self._by_key)

    def sample(self, limit: int = 20) -> list[dict[str, Any]]:
        ordered = sorted(self._by_key.items(), key=lambda kv: (kv[0][1], kv[0][0]))
        return [
            {"symbol": symbol, "date": day.isoformat(), "missing": sorted(whats)}
            for (symbol, day), whats in ordered[:limit]
        ]


class _DailyResult:
    __slots__ = ("book_id", "cost", "cum", "date", "funding", "price", "r", "turnover")

    def __init__(
        self,
        *,
        date: dt.date,
        book_id: str,
        price: float,
        funding: float,
        cost: float,
        turnover: float,
        r: float,
        cum: float,
    ) -> None:
        self.date = date
        self.book_id = book_id
        self.price = price
        self.funding = funding
        self.cost = cost
        self.turnover = turnover
        self.r = r
        self.cum = cum


def _score_day(
    reader: _LakeReader,
    today: _ScheduledBook,
    yesterday: _ScheduledBook | None,
    day: dt.date,
    cost_rate: float,
    missing: _MissingTracker,
) -> tuple[float, float, float, float]:
    """One day's ``(price_term, funding_term, cost_term, turnover)``."""
    yesterday_weights: Mapping[str, float] = yesterday.lake_weights if yesterday else {}
    price_term = 0.0
    funding_term = 0.0
    for symbol, weight in today.lake_weights.items():
        close_today = reader.close(symbol, day)
        close_yesterday = reader.close(symbol, day - dt.timedelta(days=1))
        if close_today is None or close_yesterday is None:
            missing.mark(symbol, day, "close")
        else:
            price_term += weight * (close_today / close_yesterday - 1.0)
        funding_rate = reader.funding(symbol, day)
        if funding_rate is None:
            missing.mark(symbol, day, "funding")
        else:
            funding_term += -weight * funding_rate

    turnover = 0.0
    for symbol in set(today.lake_weights) | set(yesterday_weights):
        turnover += abs(today.lake_weights.get(symbol, 0.0) - yesterday_weights.get(symbol, 0.0))
    cost_term = cost_rate * turnover
    return price_term, funding_term, cost_term, turnover


def _run_daily_walk(
    reader: _LakeReader,
    scheduled: Sequence[_ScheduledBook],
    window_days: Sequence[dt.date],
    cost_rate: float,
) -> tuple[str, list[_DailyResult], _MissingTracker]:
    """Walk ``window_days`` in order, stopping at the first unscorable day.

    A day is scorable when :data:`_BENCHMARK_SYMBOL` has both a futbars
    close and a funding row for it. Returns the status (``"interim"`` or
    ``"final"``), the scored days' results, and the missing-leg tracker.
    """
    missing = _MissingTracker()
    results: list[_DailyResult] = []
    cumulative = 0.0
    status = "final"
    for day in window_days:
        if reader.close(_BENCHMARK_SYMBOL, day) is None or reader.funding(_BENCHMARK_SYMBOL, day) is None:
            status = "interim"
            break
        today = _book_in_force(scheduled, day)
        assert today is not None  # window_days is already trimmed to >= the first book's F
        yesterday = _book_in_force(scheduled, day - dt.timedelta(days=1))
        price, funding, cost, turnover = _score_day(reader, today, yesterday, day, cost_rate, missing)
        r = price + funding - cost
        cumulative += r
        results.append(
            _DailyResult(
                date=day,
                book_id=today.book.book_id,
                price=price,
                funding=funding,
                cost=cost,
                turnover=turnover,
                r=r,
                cum=cumulative,
            )
        )
    return status, results, missing


def _population_mean_sd(values: Sequence[float]) -> tuple[float, float]:
    n = len(values)
    mean = math.fsum(values) / n
    variance = math.fsum((value - mean) ** 2 for value in values) / n
    return mean, math.sqrt(variance)


def _realised_beta(results: Sequence[_DailyResult], reader: _LakeReader) -> float | None:
    if len(results) < 10:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for entry in results:
        close_today = reader.close(_BENCHMARK_SYMBOL, entry.date)
        close_yesterday = reader.close(_BENCHMARK_SYMBOL, entry.date - dt.timedelta(days=1))
        if close_today is None or close_yesterday is None:
            continue
        xs.append(close_today / close_yesterday - 1.0)
        ys.append(entry.r)
    return _ols_slope(xs, ys)


def _max_drawdown(results: Sequence[_DailyResult]) -> float:
    peak = 0.0
    worst = 0.0
    for entry in results:
        peak = max(peak, entry.cum)
        worst = min(worst, entry.cum - peak)
    return worst


def _forward_ic(scheduled_book: _ScheduledBook, reader: _LakeReader) -> float | None:
    start = scheduled_book.in_force_from - dt.timedelta(days=1)
    end = scheduled_book.in_force_from + dt.timedelta(days=_FORWARD_IC_HORIZON_DAYS - 1)
    returns: dict[str, float] = {}
    for symbol in scheduled_book.lake_weights:
        close_start = reader.close(symbol, start)
        close_end = reader.close(symbol, end)
        if close_start is None or close_end is None:
            return None
        returns[symbol] = close_end / close_start - 1.0
    return _spearman(scheduled_book.lake_weights, returns)


# -- validity, from vst.db only ---------------------------------------------------


def _slot_boundaries(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    boundaries = []
    cursor = start
    step = dt.timedelta(hours=_SLOT_HOURS)
    while cursor < end:
        boundaries.append(cursor)
        cursor += step
    return boundaries


def _consecutive_slot_failure(
    connection: sqlite3.Connection, start: dt.datetime, end: dt.datetime
) -> bool:
    """Whether two consecutive 4-hour slots in ``[start, end)`` both failed.

    A slot "failed" when it has no completion row at all, or its newest
    (by ``finished_at``) completion carries a nonzero ``exit_code`` — a
    re-run that later succeeded clears an earlier failure in the same slot,
    which is why the newest row per slot is the one read.
    """
    rows = _query(
        connection,
        f"SELECT slot, finished_at, exit_code FROM {_SLOT_COMPLETION_TABLE} "
        "WHERE slot >= ? AND slot < ? ORDER BY finished_at ASC",
        (start.isoformat(), end.isoformat()),
    )
    outcomes: dict[str, int] = {}
    for slot, _finished_at, exit_code in rows:
        outcomes[slot] = exit_code
    consecutive_failures = 0
    for boundary in _slot_boundaries(start, end):
        ok = outcomes.get(boundary.isoformat()) == 0
        consecutive_failures = 0 if ok else consecutive_failures + 1
        if consecutive_failures >= 2:
            return True
    return False


def _leg_coverage(
    connection: sqlite3.Connection, books: Sequence[_HistoryBook]
) -> tuple[float, int, int]:
    """The fraction of (book, target symbol) pairs the venue is known to hold.

    A pair is covered when ``router_order_record`` holds a row for that
    symbol under this book's own ``book_id``, or under any earlier shadow
    book's ``book_id`` — a position carried, unchanged, from that earlier
    book, which never needed a fresh order.
    """
    rows = _query(connection, f"SELECT DISTINCT book_id, symbol FROM {_ORDER_RECORD_TABLE}")
    symbols_by_book: dict[str, set[str]] = defaultdict(set)
    for book_id, symbol in rows:
        symbols_by_book[book_id].add(symbol)

    total = 0
    covered = 0
    earlier_ids: list[str] = []
    for book in books:
        candidate_ids = (*earlier_ids, book.book_id)
        for symbol in book.weights:
            total += 1
            if any(symbol in symbols_by_book.get(book_id, ()) for book_id in candidate_ids):
                covered += 1
        earlier_ids.append(book.book_id)
    coverage = covered / total if total else 1.0
    return coverage, covered, total


def _grid_coverage_gaps(
    connection: sqlite3.Connection,
    books: Sequence[_HistoryBook],
    anchor: dt.date,
    grid_days: int,
    first_decision: dt.date,
    last_scored_day: dt.date | None,
) -> list[str]:
    """Grid decision dates whose book is missing, or never ran a clean slot."""
    if last_scored_day is None:
        return []
    by_date = {book.decision_date: book for book in books}
    succeeded = {row[0] for row in _query(
        connection, f"SELECT DISTINCT book_id FROM {_SLOT_COMPLETION_TABLE} WHERE exit_code = 0"
    )}
    offset = (first_decision - anchor).days
    steps = -(-offset // grid_days) if offset > 0 else 0
    cursor = anchor + dt.timedelta(days=steps * grid_days)
    reasons: list[str] = []
    while cursor + dt.timedelta(days=_NOMINAL_IN_FORCE_LAG_DAYS) <= last_scored_day:
        if cursor >= first_decision:
            book = by_date.get(cursor)
            if book is None:
                reasons.append(f"no history book for grid decision date {cursor.isoformat()}")
            elif book.book_id not in succeeded:
                reasons.append(f"book {book.book_id!r} has no completion with exit_code 0")
        cursor += dt.timedelta(days=grid_days)
    return reasons


def _daily_loss_halt_count(
    connection: sqlite3.Connection, window_start: dt.datetime, window_end: dt.datetime
) -> int:
    rows = _query(connection, f"SELECT breached_at FROM {_DAILY_LOSS_HALT_TABLE}")
    count = 0
    for (raw,) in rows:
        moment = dt.datetime.fromisoformat(raw)
        if window_start <= moment < window_end:
            count += 1
    return count


def _opening_equity(connection: sqlite3.Connection, day: dt.date) -> float | None:
    rows = _query(
        connection,
        f"SELECT opening_equity FROM {_DAILY_OPENING_EQUITY_TABLE} WHERE day = ?",
        (day.isoformat(),),
    )
    if not rows:
        return None
    try:
        return float(rows[0][0])
    except (TypeError, ValueError):
        return None


def _vst_equity_return(
    connection: sqlite3.Connection, results: Sequence[_DailyResult]
) -> float | None:
    if not results:
        return None
    first = _opening_equity(connection, results[0].date)
    last = _opening_equity(connection, results[-1].date + dt.timedelta(days=1))
    if first is None or last is None or first == 0.0:
        return None
    return last / first - 1.0


def _compute_validity(
    connection: sqlite3.Connection | None,
    books: Sequence[_HistoryBook],
    scheduled: Sequence[_ScheduledBook],
    results: Sequence[_DailyResult],
    window_start: dt.datetime,
    window_end: dt.datetime,
    anchor: dt.date,
    grid_days: int,
    first_decision: dt.date,
) -> tuple[str, list[str], int | None, float | None]:
    if connection is None:
        return "unchecked", [], None, None

    reasons: list[str] = []
    last_scored_day = results[-1].date if results else None
    reasons.extend(
        _grid_coverage_gaps(connection, books, anchor, grid_days, first_decision, last_scored_day)
    )

    coverage, _covered, _total = _leg_coverage(connection, books)
    if coverage < _MIN_LEG_COVERAGE:
        reasons.append(f"leg coverage {coverage:.4f} is below {_MIN_LEG_COVERAGE}")

    if results:
        period_start = dt.datetime.combine(results[0].date, dt.time(0), tzinfo=dt.UTC)
        period_end = dt.datetime.combine(
            results[-1].date + dt.timedelta(days=1), dt.time(0), tzinfo=dt.UTC
        )
        if _consecutive_slot_failure(connection, period_start, period_end):
            reasons.append("two consecutive 4-hour slots failed inside the scored period")

    validity = "invalid" if reasons else "valid"
    n_halts = _daily_loss_halt_count(connection, window_start, window_end)
    equity_return = _vst_equity_return(connection, results)
    return validity, reasons, n_halts, equity_return


# -- assembling the report --------------------------------------------------------


def _default_snapshot(lake_snapshots_dir: Path) -> Path | None:
    if not lake_snapshots_dir.is_dir():
        return None
    candidates = []
    for entry in lake_snapshots_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            parse_snapshot_name(entry.name)
        except SnapshotNameError:
            continue
        candidates.append(entry)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.name)


def _books_report(
    scheduled: Sequence[_ScheduledBook], reader: _LakeReader
) -> list[dict[str, Any]]:
    rows = []
    for entry in scheduled:
        gross = math.fsum(abs(value) for value in entry.book.weights.values())
        rows.append(
            {
                "book_id": entry.book.book_id,
                "decision_date": entry.book.decision_date.isoformat(),
                "in_force_from": entry.in_force_from.isoformat(),
                "in_force_rule": entry.in_force_rule,
                "n_legs": len(entry.book.weights),
                "gross": gross,
                "forward_ic_10d": _forward_ic(entry, reader),
            }
        )
    return rows


def _run(arguments: argparse.Namespace, source: Mapping[str, str]) -> dict[str, Any]:
    if not arguments.history.is_dir():
        raise _MissingPathError(f"{SHADOW_EVAL_CODE}: --history {str(arguments.history)!r} is not a directory")

    snapshot_path = arguments.snapshot
    if snapshot_path is None:
        snapshot_path = _default_snapshot(_DEFAULT_LAKE_SNAPSHOTS_DIR)
        if snapshot_path is None:
            raise _MissingPathError(
                f"{SHADOW_EVAL_CODE}: no sealed snapshot under "
                f"{str(_DEFAULT_LAKE_SNAPSHOTS_DIR)!r}"
            )
    elif not snapshot_path.is_dir():
        raise _MissingPathError(f"{SHADOW_EVAL_CODE}: --snapshot {str(snapshot_path)!r} is not a directory")

    books = _read_history_books(arguments.history, arguments.first_decision)
    if not books:
        raise ShadowEvalError(
            f"{SHADOW_EVAL_CODE}: no history book has a decision date on or "
            f"after {arguments.first_decision.isoformat()} — no book in the "
            "window yet"
        )

    mount = SnapshotMount.for_directory(snapshot_path)
    futbars_partitions = set(mount.partitions(FUTBARS_STREAM))
    symbol_map = _build_symbol_map(books, futbars_partitions)

    vst_db_path = _resolve_vst_db_path(arguments.vst_db, source)
    connection = _connect_vst_db(vst_db_path)
    try:
        scheduled = _schedule_books(books, symbol_map, connection)

        nominal_days = _window_days(arguments.window_start, arguments.window_end)
        first_in_force = min(entry.in_force_from for entry in scheduled)
        effective_days = [day for day in nominal_days if day >= first_in_force]
        if not effective_days:
            raise ShadowEvalError(
                f"{SHADOW_EVAL_CODE}: the first book is not in force until "
                f"{first_in_force.isoformat()}, which is outside the scored "
                f"window {arguments.window_start.isoformat()}.."
                f"{arguments.window_end.isoformat()} — no book in the window yet"
            )

        reader = _LakeReader(mount)
        cost_rate = arguments.cost_bps / 1e4
        status, results, missing = _run_daily_walk(reader, scheduled, effective_days, cost_rate)

        n_days = len(results)
        if n_days:
            r_series = [entry.r for entry in results]
            mean, sd = _population_mean_sd(r_series)
            ir_t = (mean / sd) * math.sqrt(n_days) if sd > 0.0 else None
            cum_return = math.fsum(r_series)
            price_return = math.fsum(entry.price for entry in results)
            funding_return = math.fsum(entry.funding for entry in results)
            cost_return = math.fsum(entry.cost for entry in results)
            funding_share = funding_return / cum_return if cum_return != 0.0 else None
            mean_daily_turnover = math.fsum(entry.turnover for entry in results) / n_days
            max_drawdown = _max_drawdown(results)
            realised_beta = _realised_beta(results, reader)
        else:
            mean = sd = 0.0
            ir_t = None
            cum_return = price_return = funding_return = cost_return = 0.0
            funding_share = None
            mean_daily_turnover = 0.0
            max_drawdown = 0.0
            realised_beta = None

        if status == "interim":
            verdict = "pending"
        elif cum_return > 0.0 and ir_t is not None and ir_t >= 1.0:
            verdict = "pass"
        else:
            verdict = "fail"

        validity, validity_reasons, n_halts, equity_return = (
            _compute_validity(
                connection,
                books,
                scheduled,
                results,
                arguments.window_start,
                arguments.window_end,
                arguments.grid_anchor,
                arguments.grid_days,
                arguments.first_decision,
            )
        )

        if arguments.daily_out is not None:
            _write_daily_csv(arguments.daily_out, results)

        return {
            "status": status,
            "verdict": verdict,
            "n_days": n_days,
            "cum_return": cum_return,
            "mean": mean,
            "sd": sd,
            "ir_t": ir_t,
            "price_return": price_return,
            "funding_return": funding_return,
            "cost_return": cost_return,
            "funding_share": funding_share,
            "realised_beta": realised_beta,
            "mean_daily_turnover": mean_daily_turnover,
            "max_drawdown": max_drawdown,
            "books": _books_report(scheduled, reader),
            "n_missing_legdays": missing.count(),
            "missing_legdays": missing.sample(),
            "validity": validity,
            "validity_reasons": validity_reasons,
            "n_daily_loss_halts": n_halts,
            "vst_equity_return": equity_return,
        }
    finally:
        if connection is not None:
            connection.close()


def _write_daily_csv(path: Path, results: Sequence[_DailyResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "book_id", "price", "funding", "cost", "r", "cum"])
        for entry in results:
            writer.writerow(
                [
                    entry.date.isoformat(),
                    entry.book_id,
                    entry.price,
                    entry.funding,
                    entry.cost,
                    entry.r,
                    entry.cum,
                ]
            )


class _MissingPathError(Exception):
    """Raised only by :func:`_run`, for :data:`EXIT_MISSING`'s two causes."""


# -- the command ------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.shadow_eval",
        description=(
            "Score the forward VST shadow against its pre-registered primary "
            "outcome, from the book history and the shadow lake."
        ),
    )
    parser.add_argument("--history", type=Path, default=_DEFAULT_HISTORY_DIR)
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--vst-db", dest="vst_db", type=Path, default=None)
    parser.add_argument(
        "--window-start", type=dt.datetime.fromisoformat, default=_DEFAULT_WINDOW_START
    )
    parser.add_argument(
        "--window-end", type=dt.datetime.fromisoformat, default=_DEFAULT_WINDOW_END
    )
    parser.add_argument(
        "--first-decision", type=dt.date.fromisoformat, default=_DEFAULT_FIRST_DECISION
    )
    parser.add_argument(
        "--grid-anchor", type=dt.date.fromisoformat, default=_DEFAULT_GRID_ANCHOR
    )
    parser.add_argument("--grid-days", type=int, default=_DEFAULT_GRID_DAYS)
    parser.add_argument("--cost-bps", type=float, default=_DEFAULT_COST_BPS)
    parser.add_argument("--daily-out", type=Path, default=None)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Any = print,
) -> int:
    """``python -m orchestrator.shadow_eval`` — see the module docstring.

    Exits :data:`EXIT_MISSING` when ``--history`` or the resolved
    ``--snapshot`` directory does not exist, :data:`EXIT_REFUSED` (one
    stderr line, no traceback) for every other refusal — conflicting books,
    an unmappable symbol, or no book in the window yet — and
    :data:`EXIT_OK` with one JSON line on stdout once a report (of any
    verdict) was produced.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    try:
        result = _run(arguments, source)
    except _MissingPathError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_MISSING
    except (ShadowEvalError, SnapshotError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(result))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
