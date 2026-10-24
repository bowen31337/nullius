"""``python -m orchestrator.shadow`` — write the BingX VST book from nodes.

additions_spec_forward_shadow.xml, "Forward Shadow" feature 3: *System
writes the BingX VST book file from one or more research nodes, so that the
rebalance bot trades a research book instead of the synthetic fixture.*
Today the VST bot (``router.bingx_rebalance``) trades only the hand-written
fixture at ``packages/router/tests/fixtures/bingx_vst/synthetic_book.json``;
this command is the first thing that writes a book a stored signal actually
produced.

**The decision date is found on the snapshot, before the context is even
built.** :func:`orchestrator._context.load_evaluation_context` needs
``evaluation_dates`` up front, so the command cannot ask it for the date to
evaluate. Instead it mounts ``--snapshot`` directly
(:meth:`snapshot.SnapshotMount.for_directory`, the same call
``load_evaluation_context`` makes internally) purely to list ``BTCUSDT``'s
own ``bars``/``futbars`` partition dates, walks the research grid
(``--grid-anchor`` every ``--grid-days``) to the latest grid date at or
before the last one both streams carry, and only then builds the real
:class:`~orchestrator._context.EvaluationContext` — over a *new* temp
config file copied from the deployment's own ``NULLIUS_EVALUATION_CONFIG``
document with ``snapshot_mount`` and ``evaluation_dates`` replaced. The
original file is never opened for writing.

**The hold rule is cheap on purpose.** ``book_id`` is ``shadow-D-HASH``,
where ``D`` is the decision date and ``HASH`` is the sorted node ids'
sha256, truncated — both answerable from the command line and a directory
listing alone, with no node's code read, no store queried and no sandbox
started. So the hold check runs first: when ``--out`` already holds that
exact ``book_id``, the command answers ``held: true`` and returns, "the
research book holds its weights between rebalance dates" made literal.

**Every node is re-keyed through the venue before it is scored.** A node's
``ShadowWeights.weights`` is keyed by lake symbol
(:mod:`orchestrator._shadow`'s own choice); the book this command writes is
keyed by BingX's hyphenated spelling, and a lake symbol the ``--contracts``
document does not list under either candidate hyphenation is excluded
*before* scoring (through ``allowed_symbols``), not dropped after — the
same ordering :mod:`orchestrator._shadow` itself holds for its own
``allowed_symbols`` restriction, and for the identical reason: a book that
is dollar- and beta-neutral over symbols it cannot trade is not the book
that gets traded.

**The per-node book's weighting comes from the evaluation config; the cap
and the node weighting come from a flag.** additions_spec_shadow_book_construction.xml,
"Forward Shadow": :func:`orchestrator._shadow.shadow_weights` already builds
every node's own book under ``context.book.weighting`` (see that module's
own docstring) — this command never chooses a weighting itself, because the
evaluation config is the one place that construction is registered, and a
forward shadow that quietly rebuilt the book under a different weighting
than the research measured would no longer be trading what was found.
``--max-name-weight`` (:func:`_cap_name_weights`) and ``--node-weighting``
(:func:`_node_book_sigma`) are different in kind: neither is a research
setting any registration names, both are execution-side risk controls this
command's own operator chooses at run time, so both are flags.
docs/preregistration/2026-10-22-m2-h10-lowvol.RESULT.md and the two RESULTs
before it are why the cap exists at all — a short-tail book's losses sat on
a handful of squeeze dates in a few names, so capping any one name's share
of the combined book bounds that concentration directly. With a config
whose book carries no weighting key and neither new flag given, this
command writes the identical bytes and prints the identical JSON line
(plus three keys at their defaults) it always has.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
from collections.abc import Collection, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from artifacts import (
    SOURCE_FILENAME,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
    source_code_hash,
)
from snapshot import SnapshotError, SnapshotMount

from ._context import (
    BARS_STREAM,
    DEFAULT_BOOK_WEIGHTING,
    EVALUATION_CONFIG_ENV,
    FUTBARS_STREAM,
    EvaluationConfigError,
    EvaluationContext,
    _beta_window_dates,
    _close_to_close_returns,
    _population_std,
    load_evaluation_context,
)
from ._shadow import ShadowError, shadow_weights

__all__ = ["ShadowCliError", "main"]

#: The greppable code word every :class:`ShadowCliError` opens with.
SHADOW_CLI_CODE = "shadow_cli"

DATABASE_URL_ENV = "DATABASE_URL"

#: Restated locally rather than imported — the same "every store restates
#: its own URL translation and table name" idiom ``closeout.py`` and
#: ``_evaluate.py`` already take for the ``node`` table.
_NODE_TABLE = "node"

_ACCOUNT = "bingx-vst"
_MARGIN_MODE = "isolated"
_EXPECTED_FILL_SECONDS = 120
#: "weights below 1e-6 of equity are dropped" — a book's weights are
#: already signed fractions of equity (the router's own schema), so this
#: threshold applies to the weight fraction directly.
_MIN_WEIGHT_FRACTION = 1e-6
_DEFAULT_GRID_ANCHOR = dt.date(2022, 1, 3)
_DEFAULT_GRID_DAYS = 14
_DEFAULT_EQUITY_USDT = 10000.0
_DEFAULT_GROSS = 1.0
#: The grid's own benchmark — fixed, independent of whatever symbol a
#: beta-neutral book's own ``beta_benchmark`` names.
_GRID_BENCHMARK_SYMBOL = "BTCUSDT"
#: The lake symbols' own trailing spelling every BingX USDT-margined
#: contract shares.
_LAKE_QUOTE_SUFFIX = "USDT"
_THOUSAND_PREFIX = "1000"

#: ``--node-weighting``'s closed vocabulary and its default — "equal" is
#: today's plain mean, unchanged; "inverse_vol" is opt-in.
NODE_WEIGHTINGS = ("equal", "inverse_vol")
_DEFAULT_NODE_WEIGHTING = "equal"
#: The trailing window a node's own realised book volatility is measured
#: over, under ``--node-weighting inverse_vol`` — fixed at 60 calendar days
#: anchored at the decision date, independent of the evaluation config's own
#: ``book.vol_window_days`` (which scales a *per-name* vol inside one node's
#: book, not a node's own book-level vol across nodes).
_NODE_VOL_WINDOW_DAYS = 60
#: A node's trailing book-return window must carry at least this many priced
#: dates before its volatility is trusted enough to divide by — the same
#: "noise dressed as a scale" concern :data:`orchestrator._context.MIN_VOL_WINDOW_DAYS`
#: already states for a per-name vol, applied here to the node's own book.
_MIN_NODE_VOL_PRICED_DATES = 20
#: ``--max-name-weight``'s clip-and-renormalise loop runs at most this many
#: passes before refusing — a cap under ``gross / n`` names can never be met,
#: so a loop that has not settled by here never will.
_MAX_CAP_PASSES = 20
#: Float slack the cap loop's own convergence check and its ``n_capped``
#: count use, well under a cap any caller would set and well over a
#: ``fsum``/``float`` division's own rounding.
_CAP_TOLERANCE = 1e-9

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIG = 2


class ShadowCliError(Exception):
    """This command's own refusal — the ask's fault, not a collaborator's.

    Raised, and only raised, by this module: a malformed ``--node``, a
    document that will not read or parse, a missing or mismatched node,
    a snapshot with no decision date on the grid, or a combined book with
    nothing left to trade. Every message opens with
    :data:`SHADOW_CLI_CODE`. A collaborator's own refusal
    (:class:`~orchestrator._shadow.ShadowError`,
    :class:`~orchestrator._context.EvaluationConfigError`, an
    :mod:`artifacts` or :mod:`snapshot` error) is never wrapped in this
    class — it already opens with its own code word, and :func:`main`
    prints it unchanged.
    """


# -- sqlite: the node table's own code_hash ----------------------------------


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path."""
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: the shadow book reads the node table "
            "through sqlite:///"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: {DATABASE_URL_ENV} carries no database path"
        )
    return Path(path)


def _stored_code_hash(database_url: str, campaign_id: str, node_id: str) -> str:
    """The node row's own ``code_hash`` — refused when the row is missing."""
    path = _sqlite_path(database_url)
    try:
        with closing(sqlite3.connect(path)) as connection:
            row = connection.execute(
                f"SELECT code_hash FROM {_NODE_TABLE} WHERE id = ? "
                "AND campaign_id = ?",
                (node_id, campaign_id),
            ).fetchone()
    except sqlite3.Error as exc:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: could not read node {node_id!r} of "
            f"campaign {campaign_id!r} from {database_url!r}: {exc}"
        ) from exc
    if row is None:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: no node {node_id!r} of campaign "
            f"{campaign_id!r} in {database_url!r}"
        )
    return row[0]


def _node_code(context: EvaluationContext, campaign_id: str, node_id: str) -> str:
    """The node's own persisted source, decoded — refused when absent."""
    try:
        raw = ArtifactStore(context.artifact_dir).read(
            campaign_id, node_id, SOURCE_FILENAME
        )
    except (ArtifactNotFoundError, ArtifactStoreError) as exc:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: could not read node {node_id!r} of "
            f"campaign {campaign_id!r}'s artifact: {exc}"
        ) from exc
    return raw.decode("utf-8")


def _verified_node_code(
    context: EvaluationContext, database_url: str, campaign_id: str, node_id: str
) -> str:
    """The node's code, refused unless its sha256 matches the store's row."""
    code = _node_code(context, campaign_id, node_id)
    computed = source_code_hash(code)
    stored = _stored_code_hash(database_url, campaign_id, node_id)
    if computed != stored:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: node {node_id!r} of campaign "
            f"{campaign_id!r} carries code_hash {stored!r} in the store, "
            f"but its artifact hashes to {computed!r}"
        )
    return code


# -- --node CAMPAIGN_ID/NODE_ID -----------------------------------------------


def _split_node_arg(raw: str) -> tuple[str, str]:
    campaign_id, separator, node_id = raw.partition("/")
    if not separator or not campaign_id or not node_id:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: --node {raw!r} must be CAMPAIGN_ID/NODE_ID"
        )
    return campaign_id, node_id


# -- lake symbol -> BingX symbol ----------------------------------------------


def _read_json(path: Path, what: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: {what} at {str(path)!r} cannot be read: {exc}"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: {what} at {str(path)!r} is not JSON: {exc}"
        ) from exc


def _listed_bingx_symbols(contracts_document: Any) -> frozenset[str]:
    """Every symbol the contracts document names, tradable or not."""
    if not isinstance(contracts_document, Mapping):
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: the contracts document is a JSON object"
        )
    data = contracts_document.get("data")
    if not isinstance(data, list):
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: the contracts document states no data list"
        )
    return frozenset(
        row["symbol"]
        for row in data
        if isinstance(row, Mapping) and isinstance(row.get("symbol"), str)
    )


def _map_to_bingx(symbol: str, listed: Collection[str]) -> str | None:
    """One lake symbol's BingX spelling, or ``None`` when unlisted.

    ``"XUSDT"`` -> ``"X-USDT"``. A ``"1000"``-prefixed symbol tries
    ``"1000X-USDT"`` first and falls back to ``"X-USDT"`` — either is
    accepted, whichever the contracts document actually lists.
    """
    if not symbol.endswith(_LAKE_QUOTE_SUFFIX):
        return None
    base = symbol[: -len(_LAKE_QUOTE_SUFFIX)]
    candidates = [f"{base}-{_LAKE_QUOTE_SUFFIX}"]
    if base.startswith(_THOUSAND_PREFIX) and len(base) > len(_THOUSAND_PREFIX):
        candidates.append(f"{base[len(_THOUSAND_PREFIX):]}-{_LAKE_QUOTE_SUFFIX}")
    for candidate in candidates:
        if candidate in listed:
            return candidate
    return None


def _symbol_map(
    lake_symbols: Collection[str], listed: Collection[str]
) -> tuple[dict[str, str], int]:
    """Every lake symbol's BingX mapping, and how many symbols had none."""
    mapped = {
        symbol: bingx
        for symbol in lake_symbols
        if (bingx := _map_to_bingx(symbol, listed)) is not None
    }
    return mapped, len(lake_symbols) - len(mapped)


def _ticker_prices(ticker_document: Any) -> dict[str, float]:
    """``{BingX symbol: lastPrice}`` from the public swap ticker document."""
    if not isinstance(ticker_document, Mapping) or not isinstance(
        ticker_document.get("data"), list
    ):
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: the ticker document is a JSON object with a "
            "data list"
        )
    prices: dict[str, float] = {}
    for row in ticker_document["data"]:
        if not isinstance(row, Mapping):
            continue
        try:
            price = float(row.get("lastPrice"))
        except (TypeError, ValueError):
            continue
        if isinstance(row.get("symbol"), str) and price > 0.0:
            prices[row["symbol"]] = price
    return prices


#: A mapped symbol whose BingX price is further than this factor from the
#: lake's latest perp close names a different asset under the same ticker
#: (a venue name collision), not a day's move.
_PRICE_MISMATCH_FACTOR = 2.0


def _price_mismatches(
    symbol_map: Mapping[str, str],
    prices: Mapping[str, float],
    closes: Mapping[str, Mapping[dt.date, float]],
) -> set[str]:
    """Lake symbols whose BingX contract does not price like the lake's perp.

    The lake's fut_close is on the spot scale; a "1000X-USDT" contract
    mapped from a lake symbol without the prefix quotes 1000x that scale.
    A symbol with no ticker price or no lake close is left alone.
    """
    mismatched: set[str] = set()
    for lake_symbol, bingx_symbol in symbol_map.items():
        price = prices.get(bingx_symbol)
        if price is None or lake_symbol not in closes:
            continue
        symbol_closes = closes[lake_symbol]
        days = list(symbol_closes)
        if not days:
            continue
        close = symbol_closes[max(days)]
        if bingx_symbol.startswith(_THOUSAND_PREFIX) and not lake_symbol.startswith(
            _THOUSAND_PREFIX
        ):
            price /= 1000.0
        ratio = price / close
        if not (1.0 / _PRICE_MISMATCH_FACTOR <= ratio <= _PRICE_MISMATCH_FACTOR):
            mismatched.add(lake_symbol)
    return mismatched


# -- the decision date ---------------------------------------------------------


def _decision_date(
    mount: SnapshotMount,
    anchor: dt.date,
    grid_days: int,
    required_streams: Sequence[str] = (),
) -> dt.date:
    """The latest grid date at or before the snapshot's last common date.

    "The snapshot's last date carrying both a bars close and a perp close
    for BTCUSDT" — the grid is walked from ``anchor`` every ``grid_days``,
    and this answers the latest step that does not run past it.

    Each of ``required_streams`` (``--require-stream``) must also carry the
    date for BTCUSDT. A stream published later than the others (Binance's
    daily metrics land around 07:30 UTC the next day) then holds the
    previous decision date instead of freezing a book scored on a missing
    day: the hold rule never rebuilds a book once written.
    """
    bars_dates = {
        dt.date.fromisoformat(iso)
        for iso in mount.dates(BARS_STREAM, _GRID_BENCHMARK_SYMBOL)
    }
    futbars_dates = {
        dt.date.fromisoformat(iso)
        for iso in mount.dates(FUTBARS_STREAM, _GRID_BENCHMARK_SYMBOL)
    }
    common = bars_dates & futbars_dates
    for stream in required_streams:
        common &= {
            dt.date.fromisoformat(iso)
            for iso in mount.dates(stream, _GRID_BENCHMARK_SYMBOL)
        }
    if not common:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: the snapshot carries no date with both a "
            f"bars and a perp close for {_GRID_BENCHMARK_SYMBOL}"
            + (f" (and {', '.join(required_streams)})" if required_streams else "")
        )
    last = max(common)
    if last < anchor:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: the grid anchored at {anchor.isoformat()} "
            f"starts after the snapshot's last {_GRID_BENCHMARK_SYMBOL} "
            f"date {last.isoformat()}"
        )
    steps = (last - anchor).days // grid_days
    return anchor + dt.timedelta(days=steps * grid_days)


# -- book_id ---------------------------------------------------------------


def _nodes_hash(node_ids: Sequence[str]) -> str:
    joined = "\n".join(sorted(node_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def _book_id(decision_date: dt.date, node_ids: Sequence[str]) -> str:
    return f"shadow-{decision_date.isoformat()}-{_nodes_hash(node_ids)}"


# -- the held book, read without recomputing anything ------------------------


def _book_stats(weights: Mapping[str, Any]) -> tuple[int, int, float]:
    numeric = [
        value
        for value in weights.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    n_long = sum(1 for value in numeric if value > 0)
    n_short = sum(1 for value in numeric if value < 0)
    gross = sum(abs(value) for value in numeric)
    return n_long, n_short, gross


def _held_book(out: Path, book_id: str) -> Mapping[str, Any] | None:
    """``--out``'s current document, when its ``book_id`` already matches."""
    if not out.is_file():
        return None
    try:
        document = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, Mapping) or document.get("book_id") != book_id:
        return None
    return document


# -- combining the nodes' books -----------------------------------------------


def _mean_weights(weights_by_node: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """The equal-weight mean of the nodes' weights — before any rescale.

    Symbols any node did not score stand in at 0 for that node, so a
    symbol only one node scores is not punished for the others' silence.
    Symbols come out sorted, so the same nodes' weights give a
    byte-identical mean in every process: a plain ``set`` iterates in the
    process's own string-hash order.
    """
    symbols: set[str] = set()
    for weights in weights_by_node:
        symbols.update(weights)
    node_count = len(weights_by_node)
    return {
        symbol: sum(weights.get(symbol, 0.0) for weights in weights_by_node)
        / node_count
        for symbol in sorted(symbols)
    }


def _rescale_to_gross(
    combined: Mapping[str, float], *, gross: float
) -> dict[str, float]:
    """``combined`` rescaled to ``gross``, dropping any below-dust weight.

    Refuses a book with nothing to renormalise (every node answered flat).
    The gross is an exact ``fsum``, so the same input gives a byte-identical
    answer in every process.
    """
    total = math.fsum(abs(value) for value in combined.values())
    if total <= 0.0:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: the combined book is flat across every "
            "node — there is nothing to renormalise to gross"
        )
    scale = gross / total
    return {
        symbol: value * scale
        for symbol, value in combined.items()
        if abs(value * scale) >= _MIN_WEIGHT_FRACTION
    }


def _combine(
    weights_by_node: Sequence[Mapping[str, float]], *, gross: float
) -> dict[str, float]:
    """The equal-weight mean of the nodes' weights, renormalised to ``gross``.

    additions_spec_shadow_book_construction.xml, "Forward Shadow": unchanged
    by that addition — :func:`_mean_weights` then :func:`_rescale_to_gross`,
    exactly the two steps this function has always taken, so a caller who
    never sets ``--max-name-weight`` gets back the identical book it always
    has. The per-name cap (:func:`_cap_name_weights`) runs *instead* of this
    function, over the same :func:`_mean_weights` output, because the cap is
    an execution-side choice a flag names, never the evaluation config's.
    """
    return _rescale_to_gross(_mean_weights(weights_by_node), gross=gross)


def _cap_name_weights(
    combined: Mapping[str, float], *, cap: float, gross: float
) -> tuple[dict[str, float], int]:
    """Clip every name's ``|weight|`` to ``cap``, renormalised to ``gross``.

    additions_spec_shadow_book_construction.xml, "Forward Shadow": runs on
    :func:`_mean_weights`'s own output — *after* the nodes' mean, *before*
    the plain gross rescale :func:`_rescale_to_gross` would otherwise do —
    because docs/preregistration/2026-10-22-m2-h10-lowvol.RESULT.md and the
    two RESULTs before it show a short-tail book's losses concentrated on a
    handful of squeeze dates in a few names: a cap on any one name's share of
    the combined book is a trade-level risk control, not a research setting,
    which is why it is a flag rather than a config key.

    Each pass clips every ``|w_i|`` exceeding ``cap`` to ``cap`` (keeping its
    sign) and rescales the whole, now-clipped book back to ``gross`` —
    clipping first can push a previously clean name over the cap once the
    freed-up gross is redistributed, so the two steps repeat until a pass
    leaves nothing over the cap or :data:`_MAX_CAP_PASSES` passes have run.
    A cap under ``gross`` divided by the number of names can never be met by
    any number of passes, so that case is refused by name rather than spun
    forever.

    Returns the converged book (the same below-dust filter
    :func:`_rescale_to_gross` applies) and how many names are sitting
    exactly at the cap — ``0`` is impossible once this function returns
    normally only when ``cap`` was never actually binding.
    """
    weights: dict[str, float] = dict(combined)
    for _pass in range(_MAX_CAP_PASSES):
        clipped = {
            symbol: math.copysign(cap, value) if abs(value) > cap else value
            for symbol, value in weights.items()
        }
        total = math.fsum(abs(value) for value in clipped.values())
        if total <= 0.0:
            raise ShadowCliError(
                f"{SHADOW_CLI_CODE}: the combined book is flat across every "
                "node — there is nothing to renormalise to gross"
            )
        scale = gross / total
        weights = {symbol: value * scale for symbol, value in clipped.items()}
        if all(abs(value) <= cap + _CAP_TOLERANCE for value in weights.values()):
            n_capped = sum(
                1 for value in weights.values() if abs(abs(value) - cap) <= _CAP_TOLERANCE
            )
            return (
                {
                    symbol: value
                    for symbol, value in weights.items()
                    if abs(value) >= _MIN_WEIGHT_FRACTION
                },
                n_capped,
            )
    raise ShadowCliError(
        f"{SHADOW_CLI_CODE}: no book honours --max-name-weight {cap!r} at "
        f"--gross {gross!r} across {len(weights)} name(s) after "
        f"{_MAX_CAP_PASSES} passes — a cap this far under gross/n cannot be met"
    )


# -- --node-weighting inverse_vol: each node's own trailing book volatility ---


def _node_book_returns(
    weights: Mapping[str, float],
    closes: Mapping[str, Mapping[dt.date, float]],
    as_of: dt.date,
) -> dict[dt.date, float]:
    """One node's own dollar-neutral book, applied to its trailing returns.

    For each of the trailing :data:`_NODE_VOL_WINDOW_DAYS` calendar dates
    ending at ``as_of`` (:func:`orchestrator._context._beta_window_dates`'s
    own window), the book's return is ``Σ w_i · r_i`` over ``weights``' own
    symbols, where ``r_i`` is that symbol's close-to-close return
    (:func:`orchestrator._context._close_to_close_returns`) — the same
    ``closes`` the shadow's own weights were priced from. A date is in the
    answer only when *every* symbol the book weights has a return for it; a
    thin date (one symbol's gap) is left out entirely rather than priced on
    a partial book that is not the book actually held.
    """
    window = _beta_window_dates(as_of, _NODE_VOL_WINDOW_DAYS)
    symbol_returns = {
        symbol: _close_to_close_returns(closes.get(symbol, {}), window)
        for symbol in weights
    }
    book_returns: dict[dt.date, float] = {}
    for day in window:
        if all(day in returns for returns in symbol_returns.values()):
            book_returns[day] = math.fsum(
                weights[symbol] * symbol_returns[symbol][day] for symbol in weights
            )
    return book_returns


def _node_book_sigma(
    weights: Mapping[str, float],
    closes: Mapping[str, Mapping[dt.date, float]],
    as_of: dt.date,
    *,
    node_id: str,
) -> float:
    """A node's own trailing realised book volatility — refused by name.

    additions_spec_shadow_book_construction.xml, "Forward Shadow": the
    population standard deviation (:func:`orchestrator._context._population_std`,
    the same ``ddof=0`` the per-name vol panel uses) of
    :func:`_node_book_returns`' own answer. Refused by name, rather than
    silently skipped, when fewer than :data:`_MIN_NODE_VOL_PRICED_DATES`
    dates are priced (too thin a history to trust) or the priced dates carry
    exactly zero variance (a flat book has no "unit of risk" to equalise
    against another node's).
    """
    returns = _node_book_returns(weights, closes, as_of)
    if len(returns) < _MIN_NODE_VOL_PRICED_DATES:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: node {node_id!r} carries only "
            f"{len(returns)} priced date(s) of its own trailing "
            f"{_NODE_VOL_WINDOW_DAYS}-day book return, fewer than the "
            f"{_MIN_NODE_VOL_PRICED_DATES} --node-weighting inverse_vol "
            "needs to trust its realised volatility"
        )
    sigma = _population_std(returns.values())
    if sigma == 0.0:
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: node {node_id!r}'s trailing book returns "
            "carry zero variance; --node-weighting inverse_vol cannot scale "
            "its weight vector by a 1/sigma of infinity"
        )
    return sigma


# -- writing the book ----------------------------------------------------------


def _atomic_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# -- building the context over a temp, overridden config ---------------------


def _shadow_context(
    source: Mapping[str, str],
    named: str,
    snapshot: Path,
    decision_date: dt.date,
    tmp_dir: str,
) -> EvaluationContext:
    """The real deployment's context, read-only over ``snapshot``/``decision_date``.

    Reads the deployment's own ``NULLIUS_EVALUATION_CONFIG`` document (for
    ``instrument``, ``book``, ``horizon``, ``seed``, ``sandbox_runtime``
    and the rest) and writes a *new* document, in ``tmp_dir``, that is
    that same document with ``snapshot_mount`` replaced by ``snapshot``
    and ``evaluation_dates`` replaced by ``[decision_date]`` — the
    original file is opened only for reading.
    """
    document = _read_json(Path(named), "the evaluation config")
    if not isinstance(document, Mapping):
        raise ShadowCliError(
            f"{SHADOW_CLI_CODE}: the evaluation config at {named!r} is a "
            "JSON object"
        )
    overridden = {
        **document,
        "snapshot_mount": str(snapshot),
        "evaluation_dates": [decision_date.isoformat()],
    }
    # The shadow never evaluates out of sample, and the research config's
    # oos_dates precede a forward decision date, so they would fail the
    # embargo check. lake_roots must name the shadow snapshot's own lake,
    # not the research archive's.
    overridden.pop("oos_dates", None)
    if "lake_roots" in overridden:
        overridden["lake_roots"] = [str(Path(snapshot).parent.parent)]
    config_path = Path(tmp_dir) / "shadow-evaluation-config.json"
    config_path.write_text(json.dumps(overridden), encoding="utf-8")
    context = load_evaluation_context(
        {**source, EVALUATION_CONFIG_ENV: str(config_path)}
    )
    assert context is not None  # EVALUATION_CONFIG_ENV is set in the override
    return context


# -- the command ---------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.shadow",
        description=(
            "Write the BingX VST book one or more research nodes would "
            "trade forward, from the latest sealed data."
        ),
    )
    parser.add_argument("--snapshot", required=True, type=Path, metavar="PATH")
    parser.add_argument(
        "--node",
        dest="nodes",
        action="append",
        required=True,
        metavar="CAMPAIGN_ID/NODE_ID",
    )
    parser.add_argument("--out", required=True, type=Path, metavar="PATH")
    parser.add_argument("--contracts", required=True, type=Path, metavar="PATH")
    parser.add_argument(
        "--ticker",
        type=Path,
        default=None,
        metavar="PATH",
        help="the public BingX swap ticker document; drops a mapped symbol "
        "whose price is more than 2x from the lake's latest perp close",
    )
    parser.add_argument(
        "--equity-usdt", type=float, default=_DEFAULT_EQUITY_USDT
    )
    parser.add_argument("--gross", type=float, default=_DEFAULT_GROSS)
    parser.add_argument(
        "--grid-anchor",
        type=dt.date.fromisoformat,
        default=_DEFAULT_GRID_ANCHOR,
    )
    parser.add_argument("--grid-days", type=int, default=_DEFAULT_GRID_DAYS)
    parser.add_argument(
        "--require-stream",
        dest="require_streams",
        action="append",
        default=[],
        metavar="STREAM",
        help="a stream (e.g. metrics) that must also carry the decision "
        "date for BTCUSDT; repeatable",
    )
    parser.add_argument(
        "--max-name-weight",
        type=float,
        default=None,
        metavar="FLOAT",
        help="cap any single name's |weight| in the combined book at this "
        "fraction of gross, renormalising iteratively back to --gross; "
        "unset (the default) applies no cap",
    )
    parser.add_argument(
        "--node-weighting",
        choices=NODE_WEIGHTINGS,
        default=_DEFAULT_NODE_WEIGHTING,
        help="'equal' (the default) averages the nodes' weight vectors "
        "as-is; 'inverse_vol' scales each node's vector by the inverse of "
        "its own trailing realised book volatility first",
    )
    return parser


def _run(arguments: argparse.Namespace, source: Mapping[str, str], database_url: str, named: str) -> dict[str, Any]:
    parsed_nodes = [_split_node_arg(raw) for raw in arguments.nodes]
    node_ids = [node_id for _campaign_id, node_id in parsed_nodes]

    mount = SnapshotMount.for_directory(arguments.snapshot)
    decision_date = _decision_date(
        mount, arguments.grid_anchor, arguments.grid_days, arguments.require_streams
    )
    book_id = _book_id(decision_date, node_ids)

    contracts_document = _read_json(arguments.contracts, "the contracts document")
    listed = _listed_bingx_symbols(contracts_document)
    lake_symbols = mount.partitions(BARS_STREAM)
    symbol_map, n_dropped_unmapped = _symbol_map(lake_symbols, listed)

    held = _held_book(arguments.out, book_id)
    if held is not None:
        n_long, n_short, gross = _book_stats(held.get("weights", {}))
        return {
            "as_of": decision_date.isoformat(),
            "decision_date": decision_date.isoformat(),
            "held": True,
            "book_path": str(arguments.out),
            "nodes": node_ids,
            "n_long": n_long,
            "n_short": n_short,
            "gross": gross,
            "book_beta": None,
            "n_dropped_unmapped": n_dropped_unmapped,
            "max_name_weight": arguments.max_name_weight,
            "node_weighting": arguments.node_weighting,
            "n_capped": 0,
        }

    allowed_lake_symbols = set(symbol_map)
    with tempfile.TemporaryDirectory() as tmp_dir:
        context = _shadow_context(
            source, named, arguments.snapshot, decision_date, tmp_dir
        )
        n_dropped_price_mismatch = 0
        if arguments.ticker is not None:
            mismatched = _price_mismatches(
                symbol_map,
                _ticker_prices(_read_json(arguments.ticker, "the ticker document")),
                context.closes,
            )
            for lake_symbol in mismatched:
                del symbol_map[lake_symbol]
            n_dropped_price_mismatch = len(mismatched)
            allowed_lake_symbols = set(symbol_map)
        node_weights = []
        node_betas = []
        for campaign_id, node_id in parsed_nodes:
            code = _verified_node_code(context, database_url, campaign_id, node_id)
            result = shadow_weights(
                context,
                code,
                as_of=decision_date,
                allowed_symbols=allowed_lake_symbols,
            )
            weights = result.weights
            if arguments.node_weighting == "inverse_vol":
                sigma = _node_book_sigma(
                    weights, context.closes, decision_date, node_id=node_id
                )
                weights = {symbol: value / sigma for symbol, value in weights.items()}
            node_weights.append(weights)
            node_betas.append(result.book_beta)

        if arguments.max_name_weight is None:
            combined = _combine(node_weights, gross=arguments.gross)
            n_capped = 0
        else:
            combined, n_capped = _cap_name_weights(
                _mean_weights(node_weights),
                cap=arguments.max_name_weight,
                gross=arguments.gross,
            )
        # Sorted by the BingX spelling the file carries, so the same book is
        # the same bytes (``_combine`` sorts by the lake spelling).
        bingx_weights = dict(
            sorted((symbol_map[symbol], weight) for symbol, weight in combined.items())
        )

        book_document = {
            "book_id": book_id,
            "rebalance_ts": dt.datetime.combine(
                decision_date, dt.time(0), tzinfo=dt.UTC
            ).isoformat(),
            "account": _ACCOUNT,
            "margin_mode": _MARGIN_MODE,
            # The router's own sizer refuses a float equity by name (an
            # exact Decimal or its string spelling only) — see
            # router.sizing.size_contract_deltas's own docstring.
            "equity_usdt": str(arguments.equity_usdt),
            "weights": bingx_weights,
            "decay_horizon_seconds": {
                symbol: context.horizon * 86400 for symbol in bingx_weights
            },
            "expected_fill_seconds": _EXPECTED_FILL_SECONDS,
            "positions": {},
            "originating_signal_ids": node_ids,
        }
        # Two purely informational keys, added only when a non-default
        # construction is actually in force — additions_spec_shadow_book_construction.xml,
        # "Forward Shadow": a config whose book carries no weighting key (or
        # names the default) and a command with no --max-name-weight write
        # exactly today's key set, so the byte-identical-default promise
        # holds with no caller needing to know these keys exist.
        if context.book.weighting != DEFAULT_BOOK_WEIGHTING:
            book_document["construction"] = context.book.weighting
        if arguments.max_name_weight is not None:
            book_document["max_name_weight"] = arguments.max_name_weight
        _atomic_write(arguments.out, book_document)

    n_long, n_short, gross = _book_stats(bingx_weights)
    measured_betas = [beta for beta in node_betas if beta is not None]
    book_beta = sum(measured_betas) / len(measured_betas) if measured_betas else None

    return {
        "as_of": decision_date.isoformat(),
        "decision_date": decision_date.isoformat(),
        "held": False,
        "book_path": str(arguments.out),
        "nodes": node_ids,
        "n_long": n_long,
        "n_short": n_short,
        "gross": gross,
        "book_beta": book_beta,
        "n_dropped_unmapped": n_dropped_unmapped,
        "n_dropped_price_mismatch": n_dropped_price_mismatch,
        "max_name_weight": arguments.max_name_weight,
        "node_weighting": arguments.node_weighting,
        "n_capped": n_capped,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Any = print,
) -> int:
    """``python -m orchestrator.shadow`` — see the module docstring.

    Checks ``DATABASE_URL`` and ``NULLIUS_EVALUATION_CONFIG`` before
    anything is read — each absence exits :data:`EXIT_CONFIG`. Every other
    refusal (a malformed ``--node``, a code_hash mismatch, a document that
    will not parse, a collaborator's own error) is printed to stderr and
    answered :data:`EXIT_REFUSED`. Prints one JSON line and exits
    :data:`EXIT_OK` when the book was written or already held.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{SHADOW_CLI_CODE}: {DATABASE_URL_ENV} must name the research "
            "database the shadow book reads node identity from",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    named = source.get(EVALUATION_CONFIG_ENV, "").strip()
    if not named:
        print(
            f"{SHADOW_CLI_CODE}: {EVALUATION_CONFIG_ENV} must name the "
            "deployment's evaluation config",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        result = _run(arguments, source, database_url, named)
    except (
        ShadowCliError,
        ShadowError,
        EvaluationConfigError,
        SnapshotError,
        ArtifactNotFoundError,
        ArtifactStoreError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(result))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
