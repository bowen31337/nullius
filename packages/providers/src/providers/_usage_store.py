"""Feature 3 of additions_spec_llm_usage_tracking.xml: every call's usage, saved.

*System saves every provider call's usage to an append-only
``provider_call_usage`` table, so that each call returns one stored row with
its tokens, attribution and estimated cost.*  Features 1 and 2 gave a
completion a fourth token class (cache writes) and gave the package a dated
price table (:func:`providers._prices.estimate_cost`); this module is where
those two facts become a row that outlives the process that made the call —
the addition's own opening complaint is that nothing does, today, so "how
much has this campaign spent?" has no local answer.

Two objects, one for each half of the sentence
------------------------------------------------

* :class:`UsageStore` — the append-only table itself: :meth:`UsageStore.record`
  writes one row, priced from feature 2's table at write time;
  :meth:`UsageStore.rows` and :meth:`UsageStore.totals` are its two reads.  A
  store is constructed over a ``DATABASE_URL`` and resolves its path lazily,
  so composing an application never touches a disk — the contract every store
  in this workspace states — and its table is created idempotently **on every
  connect** (``CREATE TABLE IF NOT EXISTS``), the lighter convention the ops
  member's stores use rather than the write-only ``_ensure_schema`` split
  :mod:`providers._cache` and :mod:`providers._pin_store` draw: this table has
  no prerequisite column on a core migration to probe for, so a read is as
  entitled to find its own table as a write is.

* :class:`UsageRecordingProvider` — the :class:`~providers.Provider` wrapper
  that calls :meth:`UsageStore.record` as a side effect of a normal
  :meth:`~providers.Provider.complete`, on :class:`~providers.RecordingProvider`'s
  own design: it is drop-in for what it wraps, so a caller holding the
  interface cannot tell the recorder from the provider underneath.  Every
  completed call records one ``ok`` row and returns the completion unchanged;
  every exception from the wrapped provider records one row of zero tokens —
  ``refused_budget`` for a :class:`~providers.BudgetExhaustedError`, ``error``
  for anything else — and then re-raises the *same* exception, unwrapped and
  unchanged.  ``check_model`` is a bare pass-through to the wrapped provider,
  by design: it is not a completion, and wrapping it would make "every other
  Provider method pass through" untrue the moment a configuration refusal
  started leaving a row no completion produced.

Why the store prices the row, not the caller
---------------------------------------------

:meth:`UsageRecordingProvider._complete` hands :meth:`UsageStore.record` the
served model and the four raw token counts — never a precomputed cost — so
feature 2's price table is consulted in exactly one place for every row this
feature ever writes, whichever caller is doing the writing (the recorder here,
a direct call from a test, or a future backfill tool).  A model the table does
not map exactly prices as ``None`` (feature 2's own contract: *"a USD figure
or None, never a guessed price"*), and this store records that honestly as a
``NULL`` ``est_cost_usd`` beside the ``price_table_version`` that was
consulted — never a zero, which would read as a free call rather than an
unpriced one.

Why a store failure can never touch the call
-----------------------------------------------

The addition's sentence is explicit: *"A store write failure never breaks or
alters the call."*  :meth:`UsageRecordingProvider._complete` therefore wraps
its one call to :meth:`UsageStore.record` in a bare ``except Exception`` that
swallows **anything** — a malformed argument this module would otherwise
refuse, a locked database, a disk full — and the swallowed failure is logged
once per process as a warning (:func:`logging.Logger.warning`, never a retry,
never a second attempt at the same row) so an operator can still learn the
campaign's spend went unrecorded, without the signal agent's authoring loop
ever seeing a different completion or a different exception than the one the
wrapped provider actually produced.  The dedup is a module-level flag rather
than a per-store one, on the addition's own word: a deployment that has
learned its store is unreachable does not need to be told again on every
subsequent call of a long campaign.

Stdlib-only, like the rest of this package: :mod:`sqlite3` for the store,
:mod:`decimal` for the cost, :mod:`logging` for the one warning, nothing else.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import unquote, urlparse

from ._budget import BudgetExhaustedError
from ._completion import Completion
from ._errors import ProviderError
from ._prices import PRICE_TABLE_VERSION, estimate_cost
from ._provider import Provider
from ._request import Request

__all__ = [
    "DATABASE_URL_ENV",
    "OUTCOME_ERROR",
    "OUTCOME_OK",
    "OUTCOME_REFUSED_BUDGET",
    "PROVIDER_CALL_USAGE_TABLE",
    "UsageRecordingProvider",
    "UsageRow",
    "UsageStore",
    "UsageStoreError",
    "UsageTotal",
]

_logger = logging.getLogger("providers.usage_store")

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses.
DATABASE_URL_ENV = "DATABASE_URL"

#: This member's own table, created lazily on every connect (see the module
#: docstring) — no migration declares it and none needs to.
PROVIDER_CALL_USAGE_TABLE = "provider_call_usage"

#: The three outcomes a recorded row may carry — a closed set, because a
#: fourth spelling here is a row a reporter has no bucket for.
OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_REFUSED_BUDGET = "refused_budget"
_OUTCOMES = frozenset({OUTCOME_OK, OUTCOME_ERROR, OUTCOME_REFUSED_BUDGET})

#: The columns a group-by total may be asked for — the attribution half of
#: the row, deliberately excluding every measured figure: a total grouped by
#: ``input_tokens`` would make "one row per distinct count" a group, which
#: answers no question an operator asks of a spend report.
_GROUP_COLUMNS: tuple[str, ...] = ("campaign_id", "node_id", "role", "pin")

#: Every column, in the row's own order — the one spelling the INSERT, the
#: SELECT and :func:`_row_from_raw` all share, so the three cannot drift.
_COLUMNS: tuple[str, ...] = (
    "id",
    "recorded_at",
    "campaign_id",
    "node_id",
    "role",
    "pin",
    "served_model",
    "input_tokens",
    "cache_write_tokens",
    "cache_read_tokens",
    "output_tokens",
    "est_cost_usd",
    "price_table_version",
    "outcome",
    "duration_ms",
)
_COLUMNS_SQL = ", ".join(_COLUMNS)

#: The table, in one idempotent statement — created on every connect (the
#: ops stores' convention; see the module docstring for why this table does
#: not draw the write-only ``_ensure_schema`` split some of this package's
#: other stores do).  Every measured column is ``NOT NULL``: a call either
#: completed or did not, and either way every one of its token counts is
#: known (zero, for a call that never reached a provider) — a row with a
#: count missing is half a measurement no auditor could act on.  Only
#: ``node_id`` (a call may precede the node it will be attributed to) and
#: ``est_cost_usd`` (an unpriced model) are nullable.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {PROVIDER_CALL_USAGE_TABLE} (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at         TEXT NOT NULL,
    campaign_id         TEXT NOT NULL,
    node_id             TEXT,
    role                TEXT NOT NULL,
    pin                 TEXT NOT NULL,
    served_model        TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL,
    cache_write_tokens  INTEGER NOT NULL,
    cache_read_tokens   INTEGER NOT NULL,
    output_tokens       INTEGER NOT NULL,
    est_cost_usd        TEXT,
    price_table_version TEXT NOT NULL,
    outcome             TEXT NOT NULL,
    duration_ms         INTEGER NOT NULL
)
"""

#: Set the first time a store write fails, so the warning :func:`_warn_store_failure`
#: logs is the only one this process ever emits (the addition's own word: "logged
#: once per process").  Module-level by design, not per-store or per-provider —
#: a deployment that has learned its store is unreachable does not need telling
#: twice over the rest of a long campaign.
_STORE_FAILURE_WARNED = False


class UsageStoreError(Exception):
    """This module's one refusal: a usage row, or an ask about one, is malformed.

    One base for every refusal :class:`UsageStore` raises directly — a
    malformed attribution, an unknown outcome, a ``group_by`` naming a column
    this store does not key on — and for the store's own failures (a scheme it
    cannot speak, a locked database), chained to the original.  A single base
    on the grounds every sibling store in this package states: a caller
    catching this module's question — *can this row be written or read?* —
    has one exception to catch.
    """


def _require_text(value: object, field: str) -> str:
    """Return ``value`` as a non-blank string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise UsageStoreError(
            f"a provider call's {field} must be a non-empty string, got "
            f"{value!r} ({type(value).__name__}). A usage row's attribution "
            f"is read by the campaign, node, role and pin a call was made "
            f"for, and a value that is not a name cannot be one."
        )
    return value


def _require_optional_text(value: object, field: str) -> str | None:
    """Return ``value`` as ``None`` or a non-blank string.

    ``node_id`` is the one attribution column this table carries as nullable
    (a call may be made before the node it will be attributed to is minted),
    so ``None`` is a legal ask here and nowhere else in the record.
    """
    if value is None:
        return None
    return _require_text(value, field)


def _require_pin(value: object) -> str:
    """Return ``value`` rendered as the row's ``pin`` text, refusing ``None``.

    Rendered with ``str()`` rather than imported and parsed: this module does
    not need to know a pin is a provider/model/version triple, only that it
    has a canonical text form, and :class:`providers.ModelPin` already
    guarantees ``str(pin)`` is that form. A plain string is accepted
    unchanged, so a caller that already holds the rendered triple (or a
    test's stub) need not build a :class:`~providers.ModelPin` to record one.
    """
    if value is None:
        raise UsageStoreError(
            "a provider call's pin must be given: it is the "
            "provider/model/version a usage row is attributed to, and a "
            "call recorded with no pin is a call this store cannot "
            "attribute to any model."
        )
    return _require_text(str(value), "pin")


def _require_count(value: object, field: str) -> int:
    """Return ``value`` as a non-negative token count, refusing anything else.

    ``bool`` is refused beside the integers, on this package's own rule
    (:mod:`providers._completion`, :mod:`providers._prices`): ``True`` is an
    ``int`` in Python, and a flag read as a token count would silently record
    a call that used one token it never spent.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise UsageStoreError(
            f"a provider call's {field} must be an int, got {value!r} "
            f"({type(value).__name__})."
        )
    if value < 0:
        raise UsageStoreError(
            f"a provider call's {field} must be non-negative, got {value:,}."
        )
    return value


def _require_outcome(value: object) -> str:
    """Return ``value`` as one of :data:`_OUTCOMES`, refusing anything else."""
    if value not in _OUTCOMES:
        raise UsageStoreError(
            f"a provider call's outcome must be one of "
            f"{sorted(_OUTCOMES)!r}, got {value!r}."
        )
    return value  # type: ignore[return-value]


def _require_duration_ms(value: object) -> int:
    """Return ``value`` as a non-negative duration in whole milliseconds.

    A number, not only an int: the wrapper measures with
    :func:`time.perf_counter`, whose difference is a ``float`` of seconds, and
    this is the one place that float becomes the integer the column stores —
    rounded rather than truncated, so a 0.4ms call does not round down to a
    duration indistinguishable from "not measured".
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UsageStoreError(
            f"a provider call's duration_ms must be a number, got {value!r} "
            f"({type(value).__name__})."
        )
    if value < 0:
        raise UsageStoreError(
            f"a provider call's duration_ms must be non-negative, got "
            f"{value!r}."
        )
    return round(value)


def _require_group_by(value: object) -> tuple[str, ...]:
    """Return ``value`` as a tuple of distinct columns from :data:`_GROUP_COLUMNS`."""
    if isinstance(value, (str, bytes)):
        raise UsageStoreError(
            f"totals' group_by must be an iterable of column names, got "
            f"{value!r} (a {type(value).__name__}). A single string is "
            f"iterable but is not a collection of columns — pass a tuple "
            f"such as {_GROUP_COLUMNS!r}."
        )
    try:
        columns = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise UsageStoreError(
            f"totals' group_by must be an iterable of column names, got "
            f"{value!r} ({type(value).__name__})."
        ) from None
    if not columns:
        raise UsageStoreError(
            "totals' group_by must name at least one column; an empty "
            "group_by groups every row into one bucket with no key to read "
            "it back by."
        )
    seen: set[str] = set()
    for column in columns:
        if column not in _GROUP_COLUMNS:
            raise UsageStoreError(
                f"totals' group_by names {column!r}, which is not one of "
                f"{_GROUP_COLUMNS!r} — the columns a usage row can be "
                f"grouped by."
            )
        if column in seen:
            raise UsageStoreError(
                f"totals' group_by names {column!r} more than once."
            )
        seen.add(column)
    return columns


def _format_instant(moment: datetime) -> str:
    """An instant as this row's UTC ISO-8601 text, millisecond precision."""
    utc = moment.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def _parse_cost(value: object) -> Decimal:
    """Read a stored ``est_cost_usd`` back as a :class:`~decimal.Decimal`."""
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise UsageStoreError(
            f"a stored est_cost_usd of {value!r} does not parse as a decimal."
        ) from exc


@dataclass(frozen=True)
class _UsageCounts:
    """The four token counts :func:`providers._prices.estimate_cost` reads.

    A plain carrier for the already-validated counts :meth:`UsageStore.record`
    is about to persist — not :class:`providers.Usage`, because that record
    is feature 192's completion shape and this module has no completion in
    hand on the error and refused-budget paths, only four counts (zero, on
    those paths). Recognised by :func:`providers._prices.estimate_cost`'s own
    duck-typed reader, which asks for exactly these four attributes by name.
    """

    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int


@dataclass(frozen=True, slots=True)
class UsageRow:
    """One stored ``provider_call_usage`` row, as the table holds it.

    Every column the table carries, under one name each — the shape
    :meth:`UsageStore.record` returns after a write and :meth:`UsageStore.rows`
    rebuilds on a read, so a caller reading either path holds one record
    shape. ``node_id`` is ``None`` for a call made before the node it is
    attributed to exists; ``est_cost_usd`` is ``None`` for a model feature 2's
    price table does not map exactly — never a zero, which would read as a
    free call rather than an unpriced one.
    """

    id: int
    recorded_at: str
    campaign_id: str
    node_id: str | None
    role: str
    pin: str
    served_model: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    est_cost_usd: Decimal | None
    price_table_version: str
    outcome: str
    duration_ms: int

    def row(self) -> dict[str, object]:
        """The record as a fresh mapping, ``est_cost_usd`` rendered as text.

        The shape a later reporter (feature 5's CLI) reads the row through —
        one JSON-safe value per column, with the decimal spelled as the exact
        text it was computed to rather than a ``float`` that could round it.
        """
        return {
            "id": self.id,
            "recorded_at": self.recorded_at,
            "campaign_id": self.campaign_id,
            "node_id": self.node_id,
            "role": self.role,
            "pin": self.pin,
            "served_model": self.served_model,
            "input_tokens": self.input_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "output_tokens": self.output_tokens,
            "est_cost_usd": (
                None if self.est_cost_usd is None else str(self.est_cost_usd)
            ),
            "price_table_version": self.price_table_version,
            "outcome": self.outcome,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class UsageTotal:
    """One group's summed usage — :meth:`UsageStore.totals`' answer, per group.

    ``group`` carries the group-by columns and their values for this bucket
    (e.g. ``{"campaign_id": "...", "pin": "..."}``); the four token counts and
    ``calls`` are plain sums; ``est_cost_usd`` sums only the rows this group
    could price and is ``None`` when the group priced none of its calls —
    the same "a real figure or nothing, never a guessed zero" discipline
    feature 2's own :func:`~providers._prices.estimate_cost` states, carried
    through the aggregation rather than lost in it.  ``unpriced_calls`` is
    the count a priced total alone cannot show: how many of this group's
    calls are missing from the dollar figure above it.
    """

    group: dict[str, str | None]
    calls: int
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    est_cost_usd: Decimal | None
    unpriced_calls: int

    def row(self) -> dict[str, object]:
        """The group's key and figures as one fresh mapping."""
        data: dict[str, object] = dict(self.group)
        data.update(
            {
                "calls": self.calls,
                "input_tokens": self.input_tokens,
                "cache_write_tokens": self.cache_write_tokens,
                "cache_read_tokens": self.cache_read_tokens,
                "output_tokens": self.output_tokens,
                "est_cost_usd": (
                    None if self.est_cost_usd is None else str(self.est_cost_usd)
                ),
                "unpriced_calls": self.unpriced_calls,
            }
        )
        return data


def _row_from_raw(raw: Any) -> UsageRow:
    """Rebuild one :class:`UsageRow` from a positional DBAPI row.

    Positional against :data:`_COLUMNS`' own order — the one spelling the
    INSERT, every SELECT and this function share, so the three cannot drift.
    """
    cost_text = raw[11]
    return UsageRow(
        id=raw[0],
        recorded_at=raw[1],
        campaign_id=raw[2],
        node_id=raw[3],
        role=raw[4],
        pin=raw[5],
        served_model=raw[6],
        input_tokens=raw[7],
        cache_write_tokens=raw[8],
        cache_read_tokens=raw[9],
        output_tokens=raw[10],
        est_cost_usd=None if cost_text is None else _parse_cost(cost_text),
        price_table_version=raw[12],
        outcome=raw[13],
        duration_ms=raw[14],
    )


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The convention every store in this workspace restates for itself: a
    non-``sqlite`` scheme and an in-memory or pathless URL are both refused
    by name — a usage row must outlive the call that wrote it, and an
    in-memory database dies with the connection that opened it.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise UsageStoreError(
            f"{DATABASE_URL_ENV} must be a non-empty database URL"
        )
    parsed = urlparse(database_url.strip())
    if parsed.scheme != "sqlite":
        raise UsageStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            f"store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database this "
            f"deployment already uses"
        )
    if parsed.netloc not in ("", "localhost"):
        raise UsageStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise UsageStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            f"in-memory database would die with the connection that opened "
            f"it, and a usage row must outlive the call that wrote it"
        )
    return Path(path)


class UsageStore:
    """The append-only ``provider_call_usage`` table, in the store a deployment names.

    Constructed with the database URL it persists into; :meth:`record` writes
    one row (priced from feature 2's table at write time) and answers it back;
    :meth:`rows` and :meth:`totals` are its two reads.  The class resolves its
    path lazily, so constructing one performs no I/O — composition-time work
    must not touch the disk — and the table is created idempotently on every
    connect, so no migration step is needed and a read is as entitled to find
    its own table as a write is.

    The store holds no cache of the rows it wrote: a usage row is the only
    record of what a call cost, so it is the only thing an answer is drawn
    from, the same stance every other store in this package takes.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise UsageStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> UsageStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset. Absent is not an
        error: it is a deployment with no relational store, which composes no
        usage-recording component — a discoverable state, not an exception —
        and :class:`UsageRecordingProvider` is simply never wrapped around an
        authoring call in that deployment (feature 4).
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store persists into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use."""
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The schema is created idempotently (``CREATE TABLE IF NOT EXISTS``)
        on every connect, before the caller does anything else with the
        connection — the ops stores' own convention (see the module
        docstring), so a fresh database answers an empty :meth:`rows` rather
        than an ``OperationalError`` about a table nobody has written yet.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.execute(_SCHEMA)
        return connection

    # -- The write --------------------------------------------------------------

    def record(
        self,
        *,
        campaign_id: Any,
        node_id: Any = None,
        role: Any,
        pin: Any,
        served_model: Any,
        input_tokens: Any = 0,
        cache_write_tokens: Any = 0,
        cache_read_tokens: Any = 0,
        output_tokens: Any = 0,
        outcome: Any,
        duration_ms: Any,
    ) -> UsageRow:
        """Persist one provider call's usage; answer the row the table holds.

        ``served_model`` and the four token counts are priced here, from
        feature 2's :func:`~providers._prices.estimate_cost`, exactly once —
        never accepted as a precomputed cost — so every row this store ever
        writes is priced by the same table lookup, whichever caller made the
        call. A model the table does not map exactly prices as ``None``,
        recorded as a ``NULL`` ``est_cost_usd`` beside the
        :data:`~providers._prices.PRICE_TABLE_VERSION` that was consulted.

        The ask is validated whole — every field — before a connection is
        opened, so a malformed call never reaches the store and never leaves
        a half-written row. The row returned is read back inside the write's
        own transaction, so its ``id`` and ``recorded_at`` are the table's own
        rather than guessed at by the caller.
        """
        campaign = _require_text(campaign_id, "campaign_id")
        node = _require_optional_text(node_id, "node_id")
        role_value = _require_text(role, "role")
        pin_value = _require_pin(pin)
        served = _require_text(served_model, "served_model")
        input_count = _require_count(input_tokens, "input_tokens")
        cache_write_count = _require_count(cache_write_tokens, "cache_write_tokens")
        cache_read_count = _require_count(cache_read_tokens, "cache_read_tokens")
        output_count = _require_count(output_tokens, "output_tokens")
        outcome_value = _require_outcome(outcome)
        duration = _require_duration_ms(duration_ms)
        cost = estimate_cost(
            served,
            _UsageCounts(
                input_tokens=input_count,
                output_tokens=output_count,
                cache_write_tokens=cache_write_count,
                cache_read_tokens=cache_read_count,
            ),
        )
        recorded_at = _format_instant(datetime.now(UTC))
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"INSERT INTO {PROVIDER_CALL_USAGE_TABLE} ("
                    f"recorded_at, campaign_id, node_id, role, pin, "
                    f"served_model, input_tokens, cache_write_tokens, "
                    f"cache_read_tokens, output_tokens, est_cost_usd, "
                    f"price_table_version, outcome, duration_ms"
                    f") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        recorded_at,
                        campaign,
                        node,
                        role_value,
                        pin_value,
                        served,
                        input_count,
                        cache_write_count,
                        cache_read_count,
                        output_count,
                        None if cost is None else str(cost),
                        PRICE_TABLE_VERSION,
                        outcome_value,
                        duration,
                    ),
                )
                row_id = cursor.lastrowid
                raw = connection.execute(
                    f"SELECT {_COLUMNS_SQL} FROM {PROVIDER_CALL_USAGE_TABLE} "
                    f"WHERE id = ?",
                    (row_id,),
                ).fetchone()
        except UsageStoreError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise UsageStoreError(
                f"could not record provider call usage for campaign "
                f"{campaign!r}: {exc!r}"
            ) from exc
        if raw is None:  # pragma: no cover - the write landed in this transaction
            raise UsageStoreError(
                f"the usage row just inserted for campaign {campaign!r} "
                f"could not be read back; the row is the record, and a row "
                f"this store cannot vouch for is a call nobody can audit"
            )
        return _row_from_raw(raw)

    # -- The reads --------------------------------------------------------------

    def rows(self, campaign_id: Any = None) -> tuple[UsageRow, ...]:
        """Every stored row, oldest first — or one campaign's, when named.

        ``campaign_id=None`` (the default) answers every row this store
        holds; a caller naming a campaign gets only its rows. An empty tuple
        is the honest answer for a fresh store or a campaign with no recorded
        calls — a discoverable state, not an exception.
        """
        filter_campaign = (
            None if campaign_id is None else _require_text(campaign_id, "campaign_id")
        )
        try:
            with closing(self._connect()) as connection:
                if filter_campaign is None:
                    raw_rows = connection.execute(
                        f"SELECT {_COLUMNS_SQL} FROM {PROVIDER_CALL_USAGE_TABLE} "
                        f"ORDER BY id ASC"
                    ).fetchall()
                else:
                    raw_rows = connection.execute(
                        f"SELECT {_COLUMNS_SQL} FROM {PROVIDER_CALL_USAGE_TABLE} "
                        f"WHERE campaign_id = ? ORDER BY id ASC",
                        (filter_campaign,),
                    ).fetchall()
        except UsageStoreError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise UsageStoreError(
                f"could not read provider call usage rows: {exc!r}"
            ) from exc
        return tuple(_row_from_raw(raw) for raw in raw_rows)

    def totals(
        self, *, group_by: tuple[str, ...] = ("campaign_id", "pin")
    ) -> tuple[UsageTotal, ...]:
        """Every row, summed into groups keyed by ``group_by``.

        ``group_by`` names which of :data:`_GROUP_COLUMNS` to key the buckets
        by — the default groups by campaign and pin, the figure "how much has
        this campaign spent, on which model?" reads directly. Each bucket
        sums the four token counts and ``calls``, sums ``est_cost_usd`` over
        only the rows it could price, and counts the rest as
        ``unpriced_calls`` rather than folding them into a lower total that
        would look complete. Groups are answered in the order their first row
        was recorded — the same order :meth:`rows` reads in — rather than
        sorted, because a group's key may hold ``None`` (an unattributed
        ``node_id``), which no total order compares against a string.
        """
        columns = _require_group_by(group_by)
        order: list[tuple[object, ...]] = []
        buckets: dict[tuple[object, ...], dict[str, object]] = {}
        for record in self.rows():
            key = tuple(getattr(record, column) for column in columns)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "calls": 0,
                    "input_tokens": 0,
                    "cache_write_tokens": 0,
                    "cache_read_tokens": 0,
                    "output_tokens": 0,
                    "priced_total": Decimal(0),
                    "priced_calls": 0,
                    "unpriced_calls": 0,
                }
                buckets[key] = bucket
                order.append(key)
            bucket["calls"] = bucket["calls"] + 1
            bucket["input_tokens"] = bucket["input_tokens"] + record.input_tokens
            bucket["cache_write_tokens"] = (
                bucket["cache_write_tokens"] + record.cache_write_tokens
            )
            bucket["cache_read_tokens"] = (
                bucket["cache_read_tokens"] + record.cache_read_tokens
            )
            bucket["output_tokens"] = bucket["output_tokens"] + record.output_tokens
            if record.est_cost_usd is None:
                bucket["unpriced_calls"] = bucket["unpriced_calls"] + 1
            else:
                bucket["priced_calls"] = bucket["priced_calls"] + 1
                bucket["priced_total"] = bucket["priced_total"] + record.est_cost_usd
        totals: list[UsageTotal] = []
        for key in order:
            bucket = buckets[key]
            totals.append(
                UsageTotal(
                    group=dict(zip(columns, key, strict=True)),
                    calls=bucket["calls"],  # type: ignore[arg-type]
                    input_tokens=bucket["input_tokens"],  # type: ignore[arg-type]
                    cache_write_tokens=bucket["cache_write_tokens"],  # type: ignore[arg-type]
                    cache_read_tokens=bucket["cache_read_tokens"],  # type: ignore[arg-type]
                    output_tokens=bucket["output_tokens"],  # type: ignore[arg-type]
                    est_cost_usd=(
                        bucket["priced_total"] if bucket["priced_calls"] else None  # type: ignore[arg-type]
                    ),
                    unpriced_calls=bucket["unpriced_calls"],  # type: ignore[arg-type]
                )
            )
        return tuple(totals)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}({self._database_url!r})"


def _warn_store_failure(exc: BaseException) -> None:
    """Log one process-wide warning for a swallowed store failure.

    The first call logs; every later call, in this process, from any
    :class:`UsageRecordingProvider` over any :class:`UsageStore`, is silent —
    the addition's own word, *"logged once per process"*. A deployment that
    has already learned its usage store is unreachable does not need to be
    told again on every remaining call of a long campaign.
    """
    global _STORE_FAILURE_WARNED
    if _STORE_FAILURE_WARNED:
        return
    _STORE_FAILURE_WARNED = True
    _logger.warning(
        "providers.usage_store: recording a provider call's usage failed "
        "and will not be retried this process (%s: %s). The call itself "
        "was not affected; this campaign's spend will be missing this row "
        "and any after it until the store is reachable again.",
        type(exc).__name__,
        exc,
    )


def _elapsed_ms(start: float) -> int:
    """Milliseconds since ``start`` (a :func:`time.perf_counter` reading)."""
    return max(0, round((perf_counter() - start) * 1000))


class UsageRecordingProvider(Provider):
    """A provider that records every call's usage as a side effect of completing it.

    Wraps any :class:`~providers.Provider` and, on :class:`~providers.RecordingProvider`'s
    own design, is drop-in for what it wraps: a caller holding the interface
    cannot tell the recorder from the provider underneath. A completed call
    records one ``ok`` row (:data:`OUTCOME_OK`) — the served model and the
    completion's own four token counts — and returns the completion
    unchanged. An exception from the wrapped provider records one row of zero
    tokens against the model the request asked for (nothing served, so
    nothing else is known) — ``refused_budget``
    (:data:`OUTCOME_REFUSED_BUDGET`) for a
    :class:`~providers.BudgetExhaustedError`, ``error`` (:data:`OUTCOME_ERROR`)
    for anything else — and then re-raises the *same* exception object,
    unwrapped: a caller catching the wrapped provider's own refusals sees
    exactly the ones it would have seen with no recorder in front.

    ``check_model`` is a bare pass-through to the wrapped provider — not a
    completion, so wrapping it would record a row for a call that never
    happened. Every other :class:`~providers.Provider` method is the base
    class's own (the batch half is untouched, on
    :class:`~providers.BudgetedProvider`'s own precedent: a caller that wants
    the batched path binds a batch-capable provider underneath, and this
    wrapper adds no ``_complete_batch`` of its own).

    A store write failure — this wrapper's own call to
    :meth:`UsageStore.record`, whatever the reason it failed — never breaks
    or alters the call: see :func:`_warn_store_failure`.
    """

    def __init__(
        self,
        inner: Provider,
        *,
        store: Any,
        campaign_id: Any,
        node_id: Any,
        role: Any,
        pin: Any,
    ) -> None:
        # Held by type, on providers.BudgetedProvider's and
        # providers.RecordingProvider's own grounds: a recorder around
        # anything that is not a provider has no complete() to forward
        # through and no usage to record.
        if not isinstance(inner, Provider):
            raise ProviderError(
                f"a UsageRecordingProvider must wrap a Provider, got "
                f"{inner!r} ({type(inner).__name__}). The recorder forwards "
                f"every call to the provider interface's own complete(); "
                f"something that is not a provider is not that interface."
            )
        self._inner = inner
        # The store is held as given, not type-checked: a store write
        # failure of any kind — including a value with no record() to call —
        # is swallowed by _safe_record below rather than refused here, which
        # is what lets "a store write failure never breaks or alters the
        # call" hold even for a misconfigured store.
        self._store = store
        self._campaign_id = campaign_id
        self._node_id = node_id
        self._role = role
        self._pin = pin

    def check_model(self, model: str) -> str:
        """Delegate to the wrapped provider's own served-model check.

        Not a completion, and not recorded: a caller holding this wrapper
        must see the same served set the provider underneath declares, and a
        configuration refusal here is not a call this feature's row describes.
        """
        return self._inner.check_model(model)

    def _complete(self, request: Request) -> Completion:
        start = perf_counter()
        try:
            completion = self._inner.complete(request)
        except Exception as exc:
            outcome = (
                OUTCOME_REFUSED_BUDGET
                if isinstance(exc, BudgetExhaustedError)
                else OUTCOME_ERROR
            )
            self._safe_record(
                served_model=request.model,
                input_tokens=0,
                cache_write_tokens=0,
                cache_read_tokens=0,
                output_tokens=0,
                outcome=outcome,
                duration_ms=_elapsed_ms(start),
            )
            # The same exception, unwrapped and unchanged: a caller catching
            # the wrapped provider's own refusals must see exactly what it
            # would have seen with no recorder in front.
            raise
        self._safe_record(
            served_model=completion.model,
            input_tokens=completion.usage.input_tokens,
            cache_write_tokens=completion.usage.cache_write_tokens,
            cache_read_tokens=completion.usage.cache_read_tokens,
            output_tokens=completion.usage.output_tokens,
            outcome=OUTCOME_OK,
            duration_ms=_elapsed_ms(start),
        )
        return completion

    def _safe_record(
        self,
        *,
        served_model: str,
        input_tokens: int,
        cache_write_tokens: int,
        cache_read_tokens: int,
        output_tokens: int,
        outcome: str,
        duration_ms: int,
    ) -> None:
        """Record one row, swallowing — and warning once about — any failure.

        The one place this wrapper's "never breaks or alters the call"
        promise is kept: whatever :meth:`UsageStore.record` raises (a
        malformed ask this module would refuse, a locked database, a store
        with no ``record`` at all) is caught here, after the inner provider
        has already answered or raised, so the swallow can never change what
        the call returns or throws.
        """
        try:
            self._store.record(
                campaign_id=self._campaign_id,
                node_id=self._node_id,
                role=self._role,
                pin=self._pin,
                served_model=served_model,
                input_tokens=input_tokens,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
                output_tokens=output_tokens,
                outcome=outcome,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001 - deliberately unbounded, see docstring
            _warn_store_failure(exc)
