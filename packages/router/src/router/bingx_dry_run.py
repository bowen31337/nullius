"""Stage 0's command: the book, the documents, and the plan — no network.

additions_spec_bingx_dry_run.xml, "BingX VST Dry Run", feature 4, second
half: *It prints a dry-run plan from* ``python -m router.bingx_dry_run
--book BOOK --contracts CONTRACTS --marks MARKS``, *writing one JSON
object per would-send order and one per refused leg to stdout, and
exiting 0 while sending nothing.*  This module is that command: it reads
the three recorded documents from the paths it is handed, mirrors the
book onto BingX's VST venue through the pieces features 1-3 built, and
prints the plan — five orders and two refused legs for the recorded
fixtures and the synthetic book — without opening a socket, signing a
request, reading an API key, an environment variable or a credential.
Stage 1 — a signed VST client and the live-submission gate — is a
separate, later spec, and this module is deliberately nothing of it.

**The chain, each link its own module's verb.**  The contracts document
is translated by feature 1
(:func:`router.bingx_documents.resolve_bingx_filters`), which answers a
contract the venue closed as a ``not_tradable`` refusal rather than a
filter — the plan's first kind of refused leg, recorded where the
document was read.  The premiumIndex document is read by feature 1's own
mark reader (:func:`router.bingx_documents.resolve_bingx_mark_prices`),
whose ``missing_mark_price`` refusal is the plan's second.  What remains
is published through the book member's own
:func:`book.final_target_weights` — feature 305's seam, *"the only
output consumed by the order layer"*, so the weights arrive as a
published record rather than a bare dict, exactly as the addition's
integration points state — sized by feature 2
(:func:`router.sizing.size_contract_deltas`), named by feature 316
(:func:`router.client_order_id.derive_client_order_id`) and projected by
feature 3, and assembled leg by leg by feature 4's own
:func:`router.bingx_order.assemble_bingx_order`, which runs the gates in
their fixed order and answers an order or a gate's code word.  Nothing
here re-implements any of those steps; this module is only the wiring
that reads three documents and prints what the chain answers.

**Why the refusals are gathered before the sizing.**  The synthetic book
holds a leg the venue's own documents close — NCFXUSD2ARS-USDT, status
25 and no mark price — and a plan is a *whole breath*: one object per
leg, orders and refusals side by side, not a run that unwinds at the
first leg the venue refuses.  So the document refusals are recorded
first and the legs they close are simply not published, not sized: what
reaches feature 305's seam and the sizer is the book the venue's own
documents make tradeable, and the refused legs reach the plan through
the codes those documents themselves answered.  A symbol the documents
never named at all is different — not a leg the venue closed but a book
and a document that disagree about what exists — and that is a fault of
the ask, refused naming the symbol, because a silently dropped weight
would be indistinguishable from a weight the book never held.

**One line per leg, in the book's own order.**  Every leg the plan
carries — order or refusal — is printed as one JSON object on one line,
in sorted symbol order, so two operators running the same command on the
same documents read byte-identical plans.  An order's object is the
request's own parameters
(:meth:`router.bingx_order.BingXOrder.parameters`) — ``symbol``,
``side``, ``positionSide``, ``type``, ``quantity``, ``price``,
``timeInForce``, ``clientOrderID``, every value a string, a ``MARKET``
leg carrying no ``price`` and no ``timeInForce`` at all.  A refusal's
object is the two facts the spec names — *its router code word and the
symbol* — under ``refusal`` and ``symbol``, because a reader of the plan
must be able to tell a leg that would send from a leg that would not
without parsing prose.  A leg already at its target produces no line at
all: a zero delta produces no order, in feature 2's own words.

**Exit 0, always, on a plan.**  The command's success is *the plan was
printed*, not *every leg would send*: the refused legs are answers, not
failures, so the exit code is 0 with two refusals on stdout exactly as
it is 0 with five orders.  Non-zero is reserved for a fault of the ask
— a path that will not read, a document that is not JSON, a book that
names a symbol the documents never mentioned — which is reported on
stderr with the refusing module's own code word, because that is a
repair to make before any plan is worth reading.

**No environment, no credential, no socket — and that is testable, not
promised.**  Stage 0's law is stated as a proof, not a hope: *with
socket creation patched to raise the command still exits 0, proving no
connection is opened and no environment variable or credential is read.*
The module imports :mod:`argparse`, :mod:`json`, :mod:`sys` and its own
siblings — no ``socket``, ``ssl``, ``http.client`` or ``hmac`` anywhere
in the addition — reads only the three files it is handed on the command
line, and consults no store: the rebalance store is never written (the
dry run publishes through feature 305's seam, which persists nothing),
and the router's rate limiter, retry, placement store and submission
health are not called, because nothing is placed.  The three ``--``
paths are the module's entire interface with the world.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .bingx_documents import (
    RouterMarkPriceError,
    RouterNotTradableError,
    resolve_bingx_filters,
    resolve_bingx_mark_prices,
)
from .bingx_order import BingXOrder, BingXRefusedLeg, assemble_bingx_order
from .client_order_id import derive_client_order_id
from .errors import RouterError
from .exchange_info import RouterSymbolFilters
from .sizing import size_contract_deltas

__all__ = [
    "BINGX_DRY_RUN_CODE",
    "RouterBingXDryRunError",
    "dry_run_plan",
    "main",
]

#: The greppable token for the faults of *this command's own ask* — a
#: path that will not read, a document that is not JSON, a book that
#: states no book_id or no equity, a weight with no decay horizon, a
#: held symbol the contracts document never named.  These are not legs
#: the venue refused (those are :class:`BingXRefusedLeg` values on
#: stdout) — they are repairs to make before any plan is worth reading,
#: reported on stderr with the exit code 1.  Coined on the module's own
#: name, the convention :mod:`router.submission_health`'s
#: ``order_submission_unhealthy`` sets: the word names where to look.
BINGX_DRY_RUN_CODE = "bingx_dry_run"


class RouterBingXDryRunError(RouterError):
    """The dry run cannot be asked for a plan at all.

    Raised for a fault of the ask rather than a fact about a leg: the
    book document is not the Stage 0 shape (not JSON, no ``book_id``, a
    naive ``rebalance_ts``, no equity, a held weight with no decay
    horizon), a venue document is unreadable, or the book holds a symbol
    the contracts document never named — which is a disagreement between
    two documents about what exists, not a leg the venue closed.  The
    plan's own refusals (a gate's code word, a document's ``not_tradable``
    or ``missing_mark_price``) are answers on stdout, never this error:
    an operator greps this token to repair the *ask*, and greps a gate's
    or a document's own token to learn *why one leg would not send*.

    Every message opens with :data:`BINGX_DRY_RUN_CODE` and names the one
    repair, the discipline every class in this member's vocabulary keeps.
    """


@dataclass(frozen=True)
class _BookTerms:
    """The synthetic book's own terms, read once and validated.

    The hand-written Stage 0 book is one JSON object, and the plan reads
    every field of it: the identity feature 316 folds (``book_id``,
    ``rebalance_ts``), the margin arrangement feature 315 judges
    (``account``, ``margin_mode``), the one scalar feature 2 sizes by
    (``equity_usdt``), the durations feature 314 compares
    (``expected_fill_seconds``, ``decay_horizon_seconds`` per symbol),
    the weights feature 305 publishes and the positions feature 2
    subtracts.  Reading them once, up front, is what keeps the plan
    deterministic — the same book answers the same terms whatever the
    documents say — and validation here is the ask's own shape: a book
    that states no equity or a naive instant is refused before any leg
    is assembled, rather than unwinding a half-printed plan.
    """

    book_id: str
    rebalance_ts: datetime
    account: str
    margin_mode: str
    equity: Any
    expected_fill_time: timedelta
    weights: Mapping[str, Any]
    decay_horizons: Mapping[str, timedelta]
    positions: Mapping[str, Any]


def _read_document(path: Path, what: str) -> Any:
    """Read and decode one JSON document from ``path``, or refuse it.

    The three ``--`` paths are the command's entire interface with the
    filesystem, and a path that will not read or a file that is not JSON
    is a fault of the ask — refused here, with the path named, rather
    than surfacing as a bare :class:`OSError` from the middle of the
    chain.  Nothing is fetched: the documents are the recorded VST
    responses, read exactly as captured.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: {what} at {str(path)!r} cannot be read: "
            f"{exc}; the dry run reads the three documents it is handed and "
            "opens nothing else"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: {what} at {str(path)!r} is not JSON: "
            f"{exc}; the plan reads the venue's responses exactly as they "
            "were captured, and a document that will not parse has no plan "
            "in it"
        ) from exc


def _text_term(document: Mapping, field: str) -> str:
    """One of the book's text terms — non-empty, stripped, verbatim."""
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states {field}="
            f"{value!r} ({type(value).__name__}); the term is the book's "
            "own identity — stripped and otherwise verbatim, never defaulted "
            "— and a book that states none of it names nothing for the plan "
            "to answer for"
        )
    return value.strip()


def _rebalance_term(document: Mapping) -> datetime:
    """The book's ``rebalance_ts``, a timezone-aware instant.

    The rebalance is an instant, not a moment of writing: feature 316
    folds it into the order's own name, so a naive spelling would fold
    an offset nobody agreed on into a key the venue would book twice.
    Read through :meth:`datetime.datetime.fromisoformat` — the spelling
    the recorded book writes — and refused when naive, the same rule
    :func:`router.client_order_id._validated_rebalance_ts` holds the
    same term to one module over.
    """
    raw = document.get("rebalance_ts")
    if not isinstance(raw, str):
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states "
            f"rebalance_ts={raw!r} ({type(raw).__name__}); the rebalance is "
            "an instant spelled as ISO 8601 text, and it is folded into "
            "every order's own name"
        )
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states "
            f"rebalance_ts={raw!r}, which is not an ISO 8601 instant"
        ) from exc
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states "
            f"rebalance_ts={raw!r}, which names no timezone; a naive instant "
            "folds into the orders' keys an offset nobody agreed on, and one "
            "rebalance would answer two names (feature 316)"
        )
    return moment


def _seconds_term(value: Any, term: str, symbol: str | None) -> Any:
    """One of the book's durations, as a non-negative number of seconds.

    The two durations feature 314 compares arrive in the book's own
    spelling — seconds — and are converted to the
    :class:`~datetime.timedelta` the posture gate reads.  A duration is
    the one place a number is legitimate in this member's arithmetic:
    it is a length of time, not money and not a quantity, and zero is
    admissible because zero is a measurement (an edge already gone; a
    queue expected to clear instantly).  Negative is refused, as the
    posture gate itself refuses it: no measurement of a length of time
    runs backwards.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: {term} for "
            f"{symbol if symbol is not None else 'the book'} must be a "
            f"number of seconds, got {value!r} ({type(value).__name__}); the "
            "posture gate compares two lengths of time and the book states "
            "them in seconds"
        )
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: {term} for "
            f"{symbol if symbol is not None else 'the book'} must be a "
            f"finite number of seconds, got {value!r}; a duration that is "
            "not a number cannot be compared against a queue's wait"
        )
    if value < 0:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: {term} for "
            f"{symbol if symbol is not None else 'the book'} must not be "
            f"negative, got {value!r}; the horizon names how long the "
            "signal's edge survives and the fill time how long the queue "
            "waits, and neither runs backwards"
        )
    return timedelta(seconds=value)


def _book_terms(document: Any) -> _BookTerms:
    """Read the synthetic book's own terms, refusing the ask's own faults.

    Every field the plan reads is read here, once, in the document's own
    spelling — the equity and the positions are handed downstream
    verbatim for their own modules to decimalize and refuse, because the
    vocabulary for *a float equity* is feature 2's, not this command's;
    the identity, the margin labels and the durations are the plan's own
    to read, because no module downstream of the wiring holds them all.
    """
    if not isinstance(document, Mapping):
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document is a JSON object — "
            f"got {type(document).__name__}; the Stage 0 book states its "
            "identity, its equity, its weights, its decay horizons and its "
            "positions as one object"
        )
    weights = document.get("weights")
    if not isinstance(weights, Mapping) or not weights:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states no weights "
            f"mapping (got {weights!r}); an empty instruction is the absence "
            "of a book rather than a book held flat, and a flat book is "
            "every symbol weighted zero — a decision publication is entitled "
            "to make"
        )
    for symbol in weights:
        if not isinstance(symbol, str) or not symbol.strip():
            raise RouterBingXDryRunError(
                f"{BINGX_DRY_RUN_CODE}: the book's weights must be keyed by "
                f"non-empty symbol names — got {symbol!r}; the plan routes "
                "an instruction to a symbol, and a weight keyed by no name "
                "routes nowhere"
            )
    if "equity_usdt" not in document:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states no "
            "equity_usdt; equity is the one scalar every target quantity "
            "is sized by, and a book that states none of it cannot be "
            "sized (feature 2 reads it exactly and refuses a float by name)"
        )
    decay = document.get("decay_horizon_seconds")
    if not isinstance(decay, Mapping):
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states no "
            "decay_horizon_seconds mapping; the posture gate reads the "
            "signal's decay horizon per symbol, and a leg with no horizon "
            "is a leg whose crossing nobody can decide (feature 314)"
        )
    horizons = {
        symbol: _seconds_term(
            decay.get(symbol), "the decay horizon", symbol
        )
        for symbol in sorted(weights)
    }
    fill = _seconds_term(
        document.get("expected_fill_seconds"), "the expected fill time", None
    )
    positions = document.get("positions", {})
    if not isinstance(positions, Mapping):
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the book document states positions="
            f"{positions!r} ({type(positions).__name__}); the positions are "
            "the signed contract quantities the account already holds, "
            "keyed by symbol, and a value that is not a mapping names "
            "nothing held"
        )
    return _BookTerms(
        book_id=_text_term(document, "book_id"),
        rebalance_ts=_rebalance_term(document),
        account=_text_term(document, "account"),
        # The margin mode is the book's own label, judged by feature 315's
        # gate verbatim — a cross book is refused by that gate, in that
        # gate's vocabulary, never re-stated here.
        margin_mode=document.get("margin_mode"),
        equity=document["equity_usdt"],
        expected_fill_time=fill,
        weights=weights,
        decay_horizons=horizons,
        positions=positions,
    )


def _require_publisher() -> Any:
    """Import and return :func:`book.final_target_weights`, or raise loudly.

    Called from inside the plan rather than at module scope, for the
    reason :func:`router.exchange_info.require_ingest` gives for its own
    cross-member import: the factory's workspace scan imports one
    member's ``src/`` at a time, so a module-scope ``import book`` here
    would make the router member's importability depend on scan order.
    Deferring keeps this module import-safe everywhere, while a caller
    that genuinely cannot reach the book member is told which wheel is
    missing rather than shown a bare :class:`ImportError` — the seam is
    the point, not a convenience: the weights are published through
    feature 305's act or the plan refuses to size them at all.
    """
    try:
        from book import final_target_weights
    except ModuleNotFoundError as exc:
        raise RouterBingXDryRunError(
            f"{BINGX_DRY_RUN_CODE}: the dry run publishes the book through "
            "the book member's own final_target_weights — feature 305's "
            "seam, the only output the order layer consumes — and that "
            "member is not importable in this environment; run "
            "`uv sync --all-packages` in the workspace root (or put "
            "packages/book/src on sys.path) so the seam this plan sizes "
            "through can be imported"
        ) from exc
    return final_target_weights


def _marks_over(
    document: Any, symbols: Sequence[str], legs: dict[str, BingXRefusedLeg]
) -> dict[str, Any]:
    """Read the mark prices for ``symbols``, refusing each unpriced leg.

    Feature 1's own reader is the check — the plan never re-implements
    it — so the document is read over the symbols that remain tradeable,
    and each :class:`~router.bingx_documents.RouterMarkPriceError` it
    raises is folded into one refused leg and the symbol removed, until
    the read succeeds over what is left.  The iteration is the sorted
    order the reader was handed, so the same book and the same document
    always name the same symbol first, and a symbol the document prices
    but the book does not hold is simply carried and ignored downstream
    — one mark per priced symbol is that reader's own contract.
    """
    pending = list(symbols)
    while True:
        try:
            return resolve_bingx_mark_prices(document, pending)
        except RouterMarkPriceError as exc:
            legs[exc.symbol] = BingXRefusedLeg(
                symbol=exc.symbol, code=exc.code
            )
            pending = [symbol for symbol in pending if symbol != exc.symbol]


def dry_run_plan(
    *,
    book: Any,
    contracts: Any,
    marks: Any,
) -> list[BingXOrder | BingXRefusedLeg]:
    """Answer the plan: one leg per symbol the book holds, order or refusal.

    A pure function over three decoded documents — the same book, the
    same contracts and the same premiumIndex answer the same plan in any
    process, on any machine, on any day, with no clock read, no state
    consulted, no store written and no socket opened.  The rebalance
    store is never touched: the book is published through feature 305's
    seam, which persists nothing, and the router's rate limiter, retry,
    placement store and submission health are not called, because
    nothing is placed.

    The legs are answered in the book's sorted symbol order — the same
    order :func:`router.sizing.size_contract_deltas` answers and feature
    316's keys are derived in — so the plan printed from them is
    byte-identical between two runs of the same command.  A leg already
    at its target answers no leg at all (a zero delta produces no
    order), a leg the venue's documents close answers their own code
    word (``not_tradable``, ``missing_mark_price``), and a leg the gates
    close answers the refusing gate's code word, in
    :func:`router.bingx_order.assemble_bingx_order`'s fixed order.

    Refuses :class:`RouterBingXDryRunError` — the ask's own faults, on
    stderr, never a leg on stdout — for a book that is not the Stage 0
    shape and for a held symbol the contracts document never named.
    """
    terms = _book_terms(book)

    # The venue's own contracts, translated once: a filter per contract
    # the venue will trade, a not_tradable refusal per contract it lists
    # but will not — both in the document's own order, both keyed by
    # BingX's hyphenated spelling end to end.
    translated = resolve_bingx_filters(contracts)

    legs: dict[str, BingXOrder | BingXRefusedLeg] = {}
    tradable: dict[str, RouterSymbolFilters] = {}
    for symbol in sorted(terms.weights):
        try:
            answer = translated[symbol]
        except KeyError:
            raise RouterBingXDryRunError(
                f"{BINGX_DRY_RUN_CODE}: the book holds {symbol!r} but the "
                "contracts document never names it; a symbol the venue's "
                "own document does not list is not a leg the venue closed "
                "(that is not_tradable) but a book and a document that "
                "disagree about what exists — and a weight silently "
                "dropped would be indistinguishable from a weight the book "
                "never held; cover the symbol in the contracts document or "
                "republish the book without it"
            ) from None
        if isinstance(answer, RouterSymbolFilters):
            tradable[symbol] = answer
        else:
            # A contract the venue lists but will not book: the document's
            # own refusal, carried by its own code word, recorded as a leg
            # of the plan rather than a dropped weight.
            assert isinstance(answer, RouterNotTradableError)
            legs[symbol] = BingXRefusedLeg(
                symbol=symbol, code=answer.code
            )

    # The marks over what remains tradeable, each unpriced held symbol
    # refused by feature 1's own reader.
    marks_for_sizing = _marks_over(marks, sorted(tradable), legs)

    # The tradeable, priced book — published through feature 305's seam,
    # never sized as a bare dict — and sized into signed deltas.
    publish = _require_publisher()
    published = publish(
        SimpleNamespace(
            weights={
                symbol: terms.weights[symbol]
                for symbol in sorted(marks_for_sizing)
                if symbol in terms.weights
            }
        )
    )
    deltas = size_contract_deltas(
        weights=published,
        equity=terms.equity,
        marks=marks_for_sizing,
        filters=tradable,
        positions=terms.positions,
    )

    for symbol, delta in deltas.items():
        # The order's own name, derived from the record's identity, and
        # the leg assembled through the gates in their fixed order under
        # the book's own margin arrangement.
        legs[symbol] = assemble_bingx_order(
            symbol=symbol,
            delta=delta,
            mark=marks_for_sizing[symbol],
            filters=tradable[symbol],
            signal_decay_horizon=terms.decay_horizons[symbol],
            expected_fill_time=terms.expected_fill_time,
            client_order_id=derive_client_order_id(
                book_id=terms.book_id,
                rebalance_ts=terms.rebalance_ts,
                symbol=symbol,
            ),
            book_id=terms.book_id,
            account=terms.account,
            mode=terms.margin_mode,
        )
    return [legs[symbol] for symbol in sorted(legs)]


def main(argv: Sequence[str] | None = None) -> int:
    """The command: read three documents, print one JSON object per leg.

    ``python -m router.bingx_dry_run --book BOOK --contracts CONTRACTS
    --marks MARKS`` — one JSON object per would-send order and one per
    refused leg, on stdout, one per line, in the book's sorted symbol
    order, and exit code 0: the refused legs are answers the plan
    states, not failures of the command.  Exit code 1 and a message on
    stderr are reserved for a fault of the ask, carrying the refusing
    module's own code word.  Nothing is sent, nothing is persisted, no
    environment variable is consulted and no credential is read — see
    the module docstring for the socket-patched proof the suite pins.
    """
    parser = argparse.ArgumentParser(
        prog="python -m router.bingx_dry_run",
        description=(
            "Print the BingX VST orders a Stage 0 book would send and the "
            "legs its gates refused, as one JSON object per leg. Sends "
            "nothing."
        ),
    )
    parser.add_argument(
        "--book",
        required=True,
        type=Path,
        help="the book document (JSON): book_id, rebalance_ts, account, "
        "margin_mode, equity_usdt, expected_fill_seconds, weights, "
        "decay_horizon_seconds, positions",
    )
    parser.add_argument(
        "--contracts",
        required=True,
        type=Path,
        help="the BingX swap contracts document (JSON), as captured from "
        "GET /openApi/swap/v2/quote/contracts",
    )
    parser.add_argument(
        "--marks",
        required=True,
        type=Path,
        help="the BingX premiumIndex document (JSON), as captured from "
        "GET /openApi/swap/v2/quote/premiumIndex",
    )
    arguments = parser.parse_args(argv)

    try:
        plan = dry_run_plan(
            book=_read_document(arguments.book, "the book document"),
            contracts=_read_document(arguments.contracts, "the contracts document"),
            marks=_read_document(arguments.marks, "the premiumIndex document"),
        )
    except RouterError as exc:
        # This command's own refusals already open with its code word;
        # the router's other refusals open with theirs. Name the program
        # once either way.
        message = str(exc)
        prefix = f"{BINGX_DRY_RUN_CODE}: "
        if not message.startswith(prefix):
            message = prefix + message
        print(message, file=sys.stderr)
        return 1

    for leg in plan:
        if isinstance(leg, BingXRefusedLeg):
            print(
                json.dumps({"symbol": leg.symbol, "refusal": leg.code})
            )
        else:
            print(json.dumps(leg.parameters()))
    return 0


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
