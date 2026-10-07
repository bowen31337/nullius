"""Feature 4 of the VST fidelity harness — persisted, per-symbol funding income.

``additions_spec_vst_fidelity.xml``, "Per-Order Capture", feature 4: *System
saves the VST account's funding-fee income to a router_funding_income table,
so that each slot's funding cost returns as a stored, per-symbol figure.*

* :meth:`~router.bingx_client.BingXClient.income` is the signed GET this
  module reads through — one more account read beside balance, positions and
  open orders, narrowed to the ``incomeType`` the caller names.
* :func:`ingest_funding` is the act: ask the client for the account's
  ``FUNDING_FEE`` income since a given instant, and persist every row through
  :class:`RouterFundingIncomeStore`.

**Idempotent on ``tranId``, because a slot must be able to ask twice.**  A
rebalance that re-ingests an overlapping window — the natural way to stay
caught up without tracking a precise watermark — must not double-count a fee
the account was charged once.  BingX's own ``tranId`` is the one field that
already names *this specific ledger entry*, so it is the table's primary
key: ``INSERT OR IGNORE`` lands a new row and silently no-ops a repeat, and
:func:`ingest_funding` reports the *count of rows that actually landed*
rather than the length of what the venue sent, so a caller can tell a
genuinely new window from a window it already recorded.

**``income`` is stored as the venue's own decimal text, never re-rendered.**
The same discipline :mod:`router.store` keeps for a fetched filter grid: the
figure a later reader sums per symbol must be exactly what BingX reported,
not a re-serialization of a :class:`~decimal.Decimal` this module happened
to parse it into.  It is still parsed — to refuse a value that is not an
exact decimal at all — but the *text* that lands in the column is the
venue's own spelling (or, for a JSON number, its shortest spelling, the same
recovery :mod:`router.bingx_reconcile`'s own ``_rate`` reads a fee rate
through).

**No filtering by ``incomeType`` here.**  The caller already asks the venue
for exactly ``FUNDING_FEE`` (:data:`FUNDING_FEE_INCOME_TYPE`), which is the
one parameter :meth:`~router.bingx_client.BingXClient.income` narrows the
read by; a second filter over the answer would be a second, disagreeing
spelling of a question already asked once.

**Storage is the workspace's relational store**, addressed by
``DATABASE_URL`` exactly as this member's other stores are:
``sqlite:///`` on a single machine, the schema created idempotently on
connect, and a URL whose scheme is not ``sqlite`` refused by name rather than
spoken with a dialect this store has never been run against.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import RouterError, RouterStoreError

__all__ = [
    "BINGX_FUNDING_CODE",
    "DATABASE_URL_ENV",
    "FUNDING_FEE_INCOME_TYPE",
    "ROUTER_FUNDING_INCOME_TABLE",
    "FundingIncome",
    "RouterBingXFundingError",
    "RouterFundingIncomeStore",
    "ingest_funding",
]

#: The workspace-wide environment variable naming the relational store.
DATABASE_URL_ENV = "DATABASE_URL"

#: One row per funding-fee income event the venue recorded for the account.
ROUTER_FUNDING_INCOME_TABLE = "router_funding_income"

#: The one ``incomeType`` this module asks the venue for and stores.
FUNDING_FEE_INCOME_TYPE = "FUNDING_FEE"

#: The greppable token every refusal this module raises opens with — coined
#: on the member's own name, the discipline every sibling module in this
#: package keeps for its own faults.
BINGX_FUNDING_CODE = "bingx_funding"

_SCHEMA = f"""
-- Feature 4: one row per funding-fee income event, idempotent on tranId --
-- the venue's own identifier for this specific ledger entry, which is why
-- it is the primary key rather than a surrogate one: a re-ingest of an
-- overlapping window lands no second row for a fee already recorded.
CREATE TABLE IF NOT EXISTS {ROUTER_FUNDING_INCOME_TABLE} (
    tran_id TEXT PRIMARY KEY,
    symbol  TEXT NOT NULL,
    income  TEXT NOT NULL,  -- the venue's own decimal text, never re-rendered
    asset   TEXT NOT NULL,
    time    INTEGER NOT NULL  -- whole milliseconds since the epoch
);
"""


class RouterBingXFundingError(RouterError):
    """A funding-income row this module cannot read, or a fetch it cannot ask.

    Raised for the faults of this act alone: a row the venue sent that names
    no symbol or no tranId, an income figure that is not an exact decimal, a
    client that exposes no callable ``income``, or an income document that
    carries no ``data`` list.  The venue's own refusal of the fetch — a
    non-zero code — keeps :mod:`router.bingx_client`'s own
    :class:`~router.bingx_client.RouterBingXRefusedError` and propagates
    unchanged: this class is only for the faults this module adds on top of
    a well-formed answer.
    """


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    Restated rather than imported from a sibling module's private helper —
    the discipline every store in this package keeps for its own address
    translation (see :mod:`router.submission_health`'s own copy for the
    reason): ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is
    absolute, and any other scheme is refused by name.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "router's funding-income store speaks sqlite:/// (the spec's "
            f"single-machine allowance); point {DATABASE_URL_ENV} at the "
            "sqlite database the account's funding income is recorded in "
            "(feature 4)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 4)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path (feature 4)"
        )
    return Path(path)


def _require_text(value: Any, field: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name."""
    if not isinstance(value, str) or not value.strip():
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: {field} must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); a funding-income row that "
            f"names no {field} cannot be filed against a symbol's own "
            "figure (feature 4)"
        )
    return value.strip()


def _require_decimal_text(value: Any, field: str) -> str:
    """The venue's own decimal spelling for ``field``, or refuse it by name.

    Read the same way :mod:`router.bingx_reconcile`'s own ``_rate`` reads a
    contracts-document rate: a :class:`~decimal.Decimal`, a ``str`` (the
    venue's own spelling), an ``int`` or a JSON ``float`` through its
    shortest spelling.  Parsed only to refuse a value that is not an exact
    decimal at all — the text that is returned, and the text that lands in
    the column, is ``str(value)`` for whichever of those the caller handed
    in, never a re-rendering of the parsed :class:`~decimal.Decimal`.
    """
    if isinstance(value, bool) or value is None:
        text = None
    elif isinstance(value, (Decimal, str, int, float)):
        text = str(value)
    else:
        text = None
    if text is None:
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: {field} must be a decimal, got "
            f"{value!r} ({type(value).__name__}); a funding fee this module "
            "could not read is never stored as an invented figure "
            "(feature 4)"
        )
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: {field}={value!r} is not a decimal "
            "(feature 4)"
        ) from exc
    if not parsed.is_finite():
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: {field}={value!r} is not a finite "
            "decimal (feature 4)"
        )
    return text


def _require_millis(value: Any, field: str) -> int:
    """Return ``value`` as whole, positive milliseconds, or refuse it by name."""
    if isinstance(value, int) and not isinstance(value, bool):
        number = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        number = int(value.strip())
    else:
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: {field} must be whole milliseconds "
            f"since the epoch, got {value!r} ({type(value).__name__}) "
            "(feature 4)"
        )
    if number <= 0:
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: {field}={number} is not a positive "
            "instant (feature 4)"
        )
    return number


@dataclass(frozen=True)
class FundingIncome:
    """One persisted funding-fee row — feature 4's own shape.

    ``income`` is held, and stored, as the venue's own decimal text — see
    :func:`_require_decimal_text` — so a reader summing it per symbol gets
    exactly the figure BingX reported.  ``tran_id`` is the venue's own
    identifier for this ledger entry and the table's primary key, which is
    what makes a repeated ingest of an overlapping window land no second row.
    """

    tran_id: str
    symbol: str
    income: str
    asset: str
    time: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "tran_id", _require_text(self.tran_id, "tranId"))
        object.__setattr__(self, "symbol", _require_text(self.symbol, "symbol"))
        object.__setattr__(self, "asset", _require_text(self.asset, "asset"))
        object.__setattr__(
            self, "income", _require_decimal_text(self.income, "income")
        )
        object.__setattr__(self, "time", _require_millis(self.time, "time"))


def _funding_row(payload: Any) -> FundingIncome:
    """One venue income row as a :class:`FundingIncome`, or refuse it by name."""
    if not isinstance(payload, Mapping):
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: a funding-income row must be an object, "
            f"got {payload!r} ({type(payload).__name__}) (feature 4)"
        )
    return FundingIncome(
        tran_id=payload.get("tranId"),
        symbol=payload.get("symbol"),
        income=payload.get("income"),
        asset=payload.get("asset"),
        time=payload.get("time"),
    )


def _require_callable(client: Any, name: str) -> Any:
    """Return ``client``'s callable ``name``, or refuse a client lacking it."""
    method = getattr(client, name, None)
    if not callable(method):
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: the injected client exposes no callable "
            f"{name}(); funding income is fetched through feature 1's "
            "client, and a client without this method cannot be asked "
            "(feature 4)"
        )
    return method


class RouterFundingIncomeStore:
    """Appends and reads the account's own funding-income log.

    Bound to a database URL at construction; construction performs no I/O,
    the discipline every store in this package follows. Each operation
    opens its own connection (creating the schema idempotently if absent),
    so the log is readable from a different process than the one that wrote
    it.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RouterFundingIncomeStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — the same
        no-store-configured-is-a-supported-state stance every store in this
        package takes.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store reads and writes."""
        return self._database_url

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    # -- Writing ----------------------------------------------------------------

    def ingest(self, rows: Iterable[FundingIncome]) -> int:
        """Persist every row, idempotent on ``tranId``; return the new count.

        A row whose ``tran_id`` is already stored is silently skipped — not
        an error, and not a second row — so a caller that re-ingests an
        overlapping window learns only how many rows actually landed.
        """
        inserted = 0
        try:
            with closing(self._connect()) as connection, connection:
                for row in rows:
                    cursor = connection.execute(
                        f"""
                        INSERT OR IGNORE INTO {ROUTER_FUNDING_INCOME_TABLE}
                            (tran_id, symbol, income, asset, time)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (row.tran_id, row.symbol, row.income, row.asset, row.time),
                    )
                    if cursor.rowcount == 1:
                        inserted += 1
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not persist the account's funding income: {exc}"
            ) from exc
        return inserted

    # -- Reading ------------------------------------------------------------

    def rows(self, *, symbol: str | None = None) -> tuple[FundingIncome, ...]:
        """Every stored row, oldest first, optionally narrowed to one symbol.

        The read a per-symbol figure is built from: a slot's funding cost is
        the sum of :attr:`FundingIncome.income` over the rows whose ``time``
        falls in that slot, which this module leaves to its own reader
        (feature 5) rather than pre-aggregating here.
        """
        clause = ""
        parameters: list[Any] = []
        if symbol is not None:
            clause = " WHERE symbol = ?"
            parameters.append(_require_text(symbol, "symbol"))
        try:
            with closing(self._connect()) as connection:
                fetched = connection.execute(
                    f"""
                    SELECT tran_id, symbol, income, asset, time
                    FROM {ROUTER_FUNDING_INCOME_TABLE}{clause}
                    ORDER BY time, tran_id
                    """,
                    parameters,
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read the account's funding income: {exc}"
            ) from exc
        return tuple(
            FundingIncome(
                tran_id=entry[0],
                symbol=entry[1],
                income=entry[2],
                asset=entry[3],
                time=entry[4],
            )
            for entry in fetched
        )


def ingest_funding(
    client: Any, store: RouterFundingIncomeStore, *, since_ms: int
) -> int:
    """Fetch the account's ``FUNDING_FEE`` income since ``since_ms`` and store it.

    Feature 4's one act: ask ``client`` for the account's funding-fee income
    through :meth:`~router.bingx_client.BingXClient.income`, narrowed to
    :data:`FUNDING_FEE_INCOME_TYPE` and to ``start_ms=since_ms``, and persist
    every row through :meth:`RouterFundingIncomeStore.ingest` — idempotent on
    ``tranId``, so a caller that re-ingests an overlapping window lands no
    duplicate.  Returns the count of rows that were actually new.

    The venue's own refusal of the fetch — a non-zero code — is
    :mod:`router.bingx_client`'s existing
    :class:`~router.bingx_client.RouterBingXRefusedError`, raised by
    ``client.income`` itself and propagated unchanged: this function adds no
    translation of its own.
    """
    income = _require_callable(client, "income")
    data = income(FUNDING_FEE_INCOME_TYPE, start_ms=since_ms)
    if not isinstance(data, list):
        raise RouterBingXFundingError(
            f"{BINGX_FUNDING_CODE}: the venue's income document carries no "
            f"data list (got {type(data).__name__}); a fetch this module "
            "cannot read has no rows to store (feature 4)"
        )
    # The request already narrows the venue's answer to FUNDING_FEE, but the
    # sentence's own noun is "each FUNDING_FEE row" — so a row stamped with
    # any other incomeType (a venue quirk, a future caller narrowing by
    # something else) is skipped here rather than trusted in on the strength
    # of the request alone.  Skipped, not refused: a different event type is
    # a fact about the account, not a malformed answer — but a row that is
    # not an object at all still cannot be judged either way, and stays a
    # refusal.
    rows: list[FundingIncome] = []
    for payload in data:
        if not isinstance(payload, Mapping):
            raise RouterBingXFundingError(
                f"{BINGX_FUNDING_CODE}: a funding-income row must be an "
                f"object, got {payload!r} ({type(payload).__name__}) "
                "(feature 4)"
            )
        if payload.get("incomeType") != FUNDING_FEE_INCOME_TYPE:
            continue
        rows.append(_funding_row(payload))
    return store.ingest(rows)
