"""Feature 310: the fetched exchangeInfo version, resolved and value-shaped.

app_spec.xml, "Order Routing & Venue Filters", feature 310: *System persists
the fetched exchangeInfo version carrying lot size, notional, price filter,
step size and tick size.*  ``docs/alpha-engine-prd.md`` C9 states why the
order path needs it at all: *"Read ``LOT_SIZE``, ``NOTIONAL``,
``PRICE_FILTER``, ``stepSize``, ``tickSize`` from ``exchangeInfo`` at
startup and daily. Never hardcode."*  A rule that says *never hardcode* is
only enforceable if the fetched constants are somewhere for the order path
to read, which is what this member exists to be.

**Parsing is not reinvented here.**  ``docs/nullius-tech-architecture.md``
§6.2 states the rule this workspace already applies to the cost model —
*"they must be the same code, not two implementations of the same
document"* — and the same reasoning holds for a venue's exchangeInfo
response: the ingest member (feature 24) already owns a strict parser for
it (:mod:`nullius_ingest.exchange_info`), and a second, router-owned parser
of the identical wire format would be exactly the divergence risk that rule
exists to rule out.  This module therefore parses every fetch through
:func:`nullius_ingest.exchange_info.parse_exchange_info` (see
:func:`require_ingest`) and only *narrows* the result to the fields the
order path actually reads — the five feature 310 names.

**The router keeps its own version log, distinct from the ingest one.**
Feature 24's version store is the research lake's append-only history,
written by the daily ingest worker into the staging area §4.2 seals into a
snapshot.  Feature 311's daily refresh is a different cadence, driven by a
different process — the live order router — and the order path needs a
fast, synchronous, symbol-keyed read (the last thing before an order is
built), not a walk over JSON files in a staging directory.  So this member
persists its own sequence of versions into the workspace's relational
store (:mod:`router.store`), narrowed to what an order needs to check
before it is submitted, while trusting the ingest member's parser for what
"a well-formed exchangeInfo document" means.

Only the three filter types feature 310 (and PRD C9) name are narrowed:
``LOT_SIZE`` (:attr:`RouterSymbolFilters.step_size`,
:attr:`RouterSymbolFilters.min_qty`, :attr:`RouterSymbolFilters.max_qty`),
``PRICE_FILTER`` (:attr:`RouterSymbolFilters.tick_size`,
:attr:`RouterSymbolFilters.min_price`, :attr:`RouterSymbolFilters.max_price`)
and ``NOTIONAL``/``MIN_NOTIONAL`` (:attr:`RouterSymbolFilters.min_notional`).
A symbol's other filters (``PERCENT_PRICE``, ``MARKET_LOT_SIZE``, ...) are
not this member's concern — a later feature that needs one reaches the full
document through the ingest member directly, rather than this member
growing a field for every filter type a venue happens to send.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .errors import RouterFilterError

__all__ = [
    "RouterSymbolFilters",
    "require_ingest",
    "resolve_router_filters",
]


def require_ingest():
    """Import and return :mod:`nullius_ingest.exchange_info`, or raise loudly.

    Called from inside the functions that need it rather than at module
    scope, for the reason :func:`signal_agent._authoring.require_contract`
    gives for its own cross-member import: the factory's workspace scan
    imports this package to fire its ``@register``, and the scan puts one
    member's ``src/`` on ``sys.path`` at a time, so a module-scope
    ``import nullius_ingest`` here would make this component's presence in
    the composed application depend on scan order.  Deferring the import
    keeps this member import-safe in every environment the workspace
    contract promises one will be (factory scan, test sandbox, replay
    path), while a caller that genuinely needs to parse a fetch and cannot
    reach the ingest member is told which wheel is missing rather than shown
    a bare :class:`ImportError`.
    """
    try:
        from nullius_ingest import exchange_info
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise ModuleNotFoundError(
            "the router member parses every fetched exchangeInfo document "
            "through the nullius-ingest member's parser "
            "(nullius_ingest.exchange_info) rather than growing a second "
            "one, and that member is not importable in this environment; "
            "run `uv sync --all-packages` in the workspace root (or put "
            "packages/ingest/src on sys.path) so the parser this member "
            "narrows can be read"
        ) from exc
    return exchange_info


@dataclass(frozen=True)
class RouterSymbolFilters:
    """One symbol's order-relevant filters, narrowed from an exchangeInfo fetch.

    Every field is the venue's own string spelling, verbatim — exactly the
    discipline :class:`nullius_ingest.exchange_info.SymbolFilters` already
    keeps, and for the same reason: decimalisation and rounding are the
    order path's business (features 312-313), and a value rewritten here
    would let a rounding bug hide behind "that's what the venue said".

    ``None`` on any field means the venue's document did not carry that
    filter (or that specific field) for this symbol — a fact the order path
    must be able to tell apart from a value of ``"0"``, so no field is
    defaulted.
    """

    symbol: str
    step_size: str | None
    min_qty: str | None
    max_qty: str | None
    tick_size: str | None
    min_price: str | None
    max_price: str | None
    min_notional: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise RouterFilterError(
                f"a symbol must be a non-empty string, got {self.symbol!r}"
            )

    @classmethod
    def from_symbol_filters(cls, symbol_filters: object) -> RouterSymbolFilters:
        """Narrow an ingest ``SymbolFilters`` down to feature 310's five fields.

        ``symbol_filters`` is
        :class:`nullius_ingest.exchange_info.SymbolFilters` — accepted as
        ``object`` here rather than imported at module scope, per
        :func:`require_ingest`.  ``step_size``, ``min_qty`` and
        ``min_notional`` are read off its own convenience properties, so
        this member's notion of "the step size" cannot silently diverge
        from the ingest member's; ``max_qty``, ``min_price`` and
        ``max_price`` are read the same way those properties are built
        (``.value(filter_type, field)``), because the ingest member does
        not itself expose a convenience name for the bound the order path
        never needs to round to, only to refuse against.
        """
        exchange_info = require_ingest()
        filter_type = exchange_info.FilterType
        return cls(
            symbol=symbol_filters.symbol,
            step_size=symbol_filters.step_size,
            min_qty=symbol_filters.min_qty,
            max_qty=symbol_filters.value(filter_type.LOT_SIZE, "maxQty"),
            tick_size=symbol_filters.tick_size,
            min_price=symbol_filters.value(filter_type.PRICE_FILTER, "minPrice"),
            max_price=symbol_filters.value(filter_type.PRICE_FILTER, "maxPrice"),
            min_notional=symbol_filters.min_notional,
        )


def resolve_router_filters(
    document: bytes | str | Mapping | object,
) -> dict[str, RouterSymbolFilters]:
    """Parse a fetched exchangeInfo payload into per-symbol router filters.

    ``document`` is whatever a fetch returned — JSON bytes, a JSON string, a
    decoded mapping, or an already-parsed
    :class:`nullius_ingest.exchange_info.ExchangeInfoDocument` — the same
    shape :data:`nullius_ingest.exchange_info.ExchangeInfoFetch` accepts,
    because this member's fetch seam mirrors that one (see
    :mod:`router.service`).

    Parsing is delegated whole to
    :func:`nullius_ingest.exchange_info.parse_exchange_info`; every defect
    it refuses (not JSON, no ``symbols`` list, a symbol with no filters, a
    duplicated symbol, a filter with no type) is translated to
    :class:`~router.errors.RouterFilterError` rather than let through as the
    ingest member's own error type, so a caller of this package catches one
    vocabulary for a bad document and a failed persist alike.
    """
    exchange_info = require_ingest()
    try:
        parsed = exchange_info.parse_exchange_info(document)
    except exchange_info.ExchangeInfoParseError as exc:
        raise RouterFilterError(str(exc)) from exc
    return {
        symbol: RouterSymbolFilters.from_symbol_filters(filters)
        for symbol, filters in parsed.symbols.items()
    }
