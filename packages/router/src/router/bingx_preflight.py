"""Stage 1's preflight: the door between a plan and any placement.

``additions_spec_bingx_vst_mirror.xml``, "BingX VST Mirror", feature 2,
under the correction ``bug_spec_bingx_vst_smoke.xml`` bug 2 won from the
first live VST run:
*System runs a VST preflight before any placement and returns a
PreflightReport, or the first refusal, in this order: orders_killed while
risk.kill.require_orders_allowed refuses; clock_skew when the venue's
server time differs from the local clock by more than 1000 ms; hedge_mode
when the account's own position-mode answer is hedge, with the repair
"switch the VST account to one-way mode"; insufficient_balance when
available USDT is below the book's equity_usdt.  For each symbol the plan
will order, it then sets margin type ISOLATED and leverage 1, treating an
already-set answer as success.  The report records the measured skew, the
available balance and the symbols prepared.*

**Why the hedge question is asked of the account, not its rows.**  The
Stage 1 spec prescribed inferring the mode from any position reporting
``positionSide`` ``LONG`` or ``SHORT``, and the live smoke test caught
that inference wrong in both directions: a flat hedge-mode account holds
no rows to inspect (it passed, and the placement failed at the venue's
leverage step with BingX code 109400 "In the Hedge mode, the 'Side'
field can only be set to LONG, SHORT or ALL"), and BingX labels a
one-way account's positions ``LONG`` and ``SHORT`` as well (a one-way
DOGE short was refused here).  The mode is therefore a fact the account
answers about itself — the client's ``position_mode()``, the boolean
``dualSidePosition`` of ``GET /openApi/swap/v1/positionSide/dual`` — and
this module never reads it out of a position's ``positionSide``.

**Why the refusals are raised, and why they are ordered.**  The four are
answers a preflight exists to give *before* a single order leaves, so
each is a typed refusal whose message opens with its own greppable code
word and names the one repair, the convention every module in this
member keeps.  They run in the sentence's own order because that order is
a safety lattice, not a style: the kill switch outranks everything
because a killed order layer must not even *ask* the venue a question;
the clock outranks the account reads because a skewed clock invalidates
the signatures the remaining reads depend on; the account's position mode
outranks its balance because a hedge-mode account is wrong about *how*
it holds money before it is wrong about *how much* it holds; and the
balance outranks the preparation writes because preparing symbols on an
account that cannot fund the plan would leave the venue holding margin
arrangements for orders that will never arrive.  A caller therefore
always learns the first refusal in this order and never a later fact
about an account an earlier refusal already closed.

**The kill guard is the risk member's own verb, translated here.**  The
first check calls :func:`risk.kill.require_orders_allowed` — deferred
past module scope, the way every cross-member import in this workspace
is — with the ``database_url``/``env`` pair the caller handed in, so the
preflight consults the same channel the order layer's own submission
path consults rather than growing a second spelling of feature 322's
state.  Its refusal arrives as the risk member's
:class:`risk.errors.RiskOrdersKilledError`; this module re-raises it as
its own :class:`RouterBingXOrdersKilledError` carrying the standing
instruction verbatim, because a caller that has chosen to catch the
router's vocabulary (``except RouterError``) must not have a kill
silently escape it — the seam is where error classes are translated, the
discipline every member boundary here keeps.  A deployment that names no
store passes vacuously, inheriting the guard's own *"no store, no
status"* stance: with no channel there is no supervisor that sent a kill
through one.

**Money is decimal, built from the venue's strings.**  The available
balance is read from the venue's balance rows as an exact
:class:`~decimal.Decimal` — ``availableMargin``, the field BingX's swap
account document spells, with ``availableBalance`` accepted as the older
spelling of the same fact — and compared strictly against the book's
``equity_usdt``, itself decimalized under the same law
:func:`router.sizing.size_contract_deltas` holds the equity to: a string
or a ``Decimal``, never a ``float``, because a term read approximately
would compare approximately.  "Below" is strict — an account holding
exactly the book's equity passes, since the book asks for no more than
the account has.

**The already-set answer is absorbed, and only that.**  A venue asked to
make true what is already true answers in its own way — some answers are
a plain success, some are a non-zero code whose message says the
arrangement is already in force — and feature 1's client raises the
latter as :class:`~router.bingx_client.RouterBingXRefusedError`, leaving
the judgement to this module by design.  :func:`is_already_set_answer`
is that judgement, exposed so feature 4's stand-in serves an answer this
preflight demonstrably absorbs: a refusal counts as success only when
its own message names the state as already set.  Any other refusal — a
symbol the venue does not know, a permission the key lacks — propagates
unchanged, in the client's own vocabulary, because swallowing it would
report a prepared symbol the venue never agreed to hold.

**Nothing here reaches the network itself.**  The module holds no
transport, no credentials and no host: every venue fact is read through
the client it is handed, and the client's own host guard has already
confined that conversation to the VST venue.  The suite proves it with a
client double and a socket patched to raise — the same proof Stage 0's
command pins for itself.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .bingx_client import BINGX_MARGIN_TYPE_ISOLATED, RouterBingXRefusedError
from .errors import RouterError

__all__ = [
    "ALREADY_SET_MSG_MARKERS",
    "BALANCE_ASSET",
    "BINGX_PREFLIGHT_CODE",
    "CLOCK_SKEW_CODE",
    "HEDGE_MODE_CODE",
    "INSUFFICIENT_BALANCE_CODE",
    "MAX_CLOCK_SKEW_MILLISECONDS",
    "ONE_WAY_REPAIR",
    "ORDERS_KILLED_CODE",
    "PREFLIGHT_LEVERAGE",
    "PreflightReport",
    "RouterBingXClockSkewError",
    "RouterBingXHedgeModeError",
    "RouterBingXInsufficientBalanceError",
    "RouterBingXOrdersKilledError",
    "RouterBingXPreflightError",
    "is_already_set_answer",
    "run_bingx_preflight",
]

#: The greppable token for the faults of *this module's own ask* — a
#: client double missing an endpoint, an equity or a symbol that is not
#: the shape this member's money discipline reads, a venue payload this
#: module cannot judge, a kill channel that will not open.  Coined on the
#: module's own name, the convention :data:`router.bingx_dry_run.
#: BINGX_DRY_RUN_CODE` states: the word names where to look.  These are
#: not one of the four placement refusals the feature orders — they are
#: repairs to make before any preflight answer is worth reading.
BINGX_PREFLIGHT_CODE = "bingx_preflight"

#: The four code words the feature's own sentence spells, restated here
#: so this module states its own contract and imports no sibling's —
#: the discipline :mod:`risk.kill` states for ``DATABASE_URL_ENV``.  A
#: caller greps the word to learn *why nothing was placed*.
ORDERS_KILLED_CODE = "orders_killed"
CLOCK_SKEW_CODE = "clock_skew"
HEDGE_MODE_CODE = "hedge_mode"
INSUFFICIENT_BALANCE_CODE = "insufficient_balance"

#: The largest venue-to-local clock difference a signed request can
#: tolerate, in whole milliseconds.  Feature 1's client signs every
#: request with ``timestamp`` and a 5000 ms receive window; a host more
#: than this far from the venue is refusing requests near the middle of
#: that window and must be repaired, not retried.  The comparison is
#: strict — a difference of exactly this many milliseconds passes — the
#: same edge feature 329's clock-skew halt takes.
MAX_CLOCK_SKEW_MILLISECONDS = 1000

#: The leverage the preflight sets on every symbol it prepares.  One,
#: because the mirror's sizing assumes no leverage: equity times weight
#: is the notional the account itself funds.
PREFLIGHT_LEVERAGE = 1

#: The repair the feature's own sentence quotes for ``hedge_mode``,
#: held as a constant so the refusal's message and any caller rendering
#: it say the same words the spec wrote.
ONE_WAY_REPAIR = "switch the VST account to one-way mode"

#: The settlement asset whose available balance the preflight reads.
#: The VST swap account is USDT-margined — every symbol the book holds
#: is a ``-USDT`` pair — so the USDT row is the account this mirror
#: funds, and a balance document naming no USDT row names no account the
#: plan could draw on.
BALANCE_ASSET = "USDT"

#: The message markers a venue refusal must carry to count as the
#: already-set answer, matched case-insensitively as substrings.  BingX
#: documents no dedicated code for "the arrangement you asked for is
#: already in force" (its published error list carries no such row), so
#: the judgement reads the venue's own words for that fact — "already
#: isolated", "no need to change" — rather than inventing a code number
#: the venue never sent.  The markers are only ever applied to refusals
#: from the two preparation calls, so an unrelated "already" (the
#: duplicate-clientOrderID refusal, say, whose message also carries the
#: word) can never reach this test.
ALREADY_SET_MSG_MARKERS = ("already", "no need to change")


# -- Errors -------------------------------------------------------------------


class RouterBingXPreflightError(RouterError):
    """The shared stem of every refusal this preflight raises.

    One class so a caller reaches the module's whole vocabulary through
    a single ``except``, split below into the four placement refusals
    the feature orders — each carrying the measurement it refused on —
    while the stem itself is raised directly for the faults of *this
    module's own ask*: a client face missing an endpoint, an equity or a
    symbol outside the shape this member reads money and legs in, a
    venue payload this module cannot judge, a kill channel that will not
    open.  Every message opens with :data:`BINGX_PREFLIGHT_CODE` or one
    of the four code words, and names the one repair.
    """


class RouterBingXOrdersKilledError(RouterBingXPreflightError):
    """A kill instruction stands; the preflight refuses before anything else.

    The first of the four, and the only one that is a *translation*:
    :func:`risk.kill.require_orders_allowed` raised the risk member's
    own :class:`~risk.errors.RiskOrdersKilledError`, and this module
    re-raises it in the router's vocabulary so a caller catching
    ``RouterError`` cannot have a kill pass it by.  The order of the
    checks is the feature's own first sentence — the kill outranks the
    clock, the account and the balance, so this refusal is raised
    before a single venue request is made.

    :attr:`instruction` carries the standing
    :class:`~risk.kill.KillInstruction` the guard read, verbatim, so the
    operator paging on a refused mirror learns which process killed the
    order layer and when — the two questions the risk member's own
    refusal exists to answer — without a second query.
    """

    def __init__(self, refusal: BaseException) -> None:
        self.instruction = getattr(refusal, "instruction", None)
        summary = getattr(self.instruction, "summary", None)
        detail = (
            summary
            if isinstance(summary, str) and summary.strip()
            else str(refusal)
        )
        super().__init__(
            f"{ORDERS_KILLED_CODE}: {detail}; the risk kill switch "
            "refuses while a kill instruction stands, and the preflight "
            "is the door before any placement — clear the kill through "
            "the door that owns a reset (feature 323's halt, 325's "
            "manual reset) and run again"
        )


class RouterBingXClockSkewError(RouterBingXPreflightError):
    """The venue's clock and this host's disagree beyond the signing window.

    The second of the four.  The skew is measured as the venue's server
    time minus the local clock, both in whole milliseconds, and refused
    when its absolute value exceeds :data:`MAX_CLOCK_SKEW_MILLISECONDS`
    — strictly, so a host exactly at the limit passes.  :attr:`skew_ms`
    carries the signed measurement (server ahead of local is positive)
    together with the two readings it was taken between, because an
    operator repairing a clock asks *which way and by how much* before
    asking anything else.
    """

    def __init__(
        self, skew_ms: int, server_ms: int, local_ms: int
    ) -> None:
        self.skew_ms = skew_ms
        self.server_ms = server_ms
        self.local_ms = local_ms
        super().__init__(
            f"{CLOCK_SKEW_CODE}: the venue's server time differs from this "
            f"host's clock by {skew_ms} ms (server {server_ms}, local "
            f"{local_ms}), more than the {MAX_CLOCK_SKEW_MILLISECONDS} ms a "
            "signed request's receive window tolerates; synchronize this "
            "host's clock against a trusted source and run the preflight "
            "again"
        )


class RouterBingXHedgeModeError(RouterBingXPreflightError):
    """The VST account is in hedge mode; the mirror places one-way orders.

    The third of the four.  The mode is asked of the account itself —
    the client's ``position_mode()``, the boolean ``dualSidePosition``
    the venue's position-mode document answers — never inferred from
    the positions the account happens to hold, because both inferences
    the live smoke test caught were wrong: a flat hedge-mode account
    holds no rows to inspect, and BingX labels a one-way account's
    positions ``LONG`` and ``SHORT`` as well.  Every order the plan
    carries states ``positionSide`` ``BOTH`` — feature 3's own
    parameters, the one-way spelling — and the venue refuses that
    combination outright.  The repair is the one the feature's sentence
    quotes verbatim: :data:`ONE_WAY_REPAIR`.  :attr:`dual_side_position`
    carries the account's own answer.
    """

    def __init__(self, dual_side_position: bool) -> None:
        self.dual_side_position = dual_side_position
        super().__init__(
            f"{HEDGE_MODE_CODE}: the VST account answers dualSidePosition "
            f"{'true' if dual_side_position else 'false'}, and the mirror "
            f"places one-way orders only; {ONE_WAY_REPAIR}"
        )


class RouterBingXInsufficientBalanceError(RouterBingXPreflightError):
    """Available USDT is below the book's equity; the plan cannot be funded.

    The fourth of the four.  The available balance is the venue's own
    row read as an exact decimal; the equity is the book's own
    ``equity_usdt`` under the same law.  "Below" is strict — an account
    holding exactly the equity passes — because the book asks for no
    more than the account has.  :attr:`available_usdt` and
    :attr:`equity_usdt` carry both decimals so the operator sees the gap
    without re-deriving either side of it.
    """

    def __init__(
        self, available_usdt: Decimal, equity_usdt: Decimal
    ) -> None:
        self.available_usdt = available_usdt
        self.equity_usdt = equity_usdt
        super().__init__(
            f"{INSUFFICIENT_BALANCE_CODE}: available USDT {available_usdt} "
            f"is below the book's equity_usdt {equity_usdt}; fund the VST "
            "account or republish the book with a smaller equity, and run "
            "the preflight again"
        )


# -- The report -----------------------------------------------------------------


@dataclass(frozen=True)
class PreflightReport:
    """The three facts a passing preflight measured, frozen at the door.

    Feature 2's last sentence names exactly what the report records —
    *"the measured skew, the available balance and the symbols
    prepared"* — and nothing else is carried: no timestamps (the report
    is an answer, not a log row; feature 4's mirror prints it or its
    refusal and the placement store records what was placed), no
    credential echoes (none may be rendered anywhere), no margin or
    leverage answers (the preparation is a door the preflight walked
    through, not a fact downstream code reads).

    * ``skew_ms`` — the signed measurement, venue server time minus
      local clock, in whole milliseconds; within
      :data:`MAX_CLOCK_SKEW_MILLISECONDS` in absolute value, or the
      preflight would have refused.  The sign is the direction an
      operator repairing a clock needs: positive, the venue is ahead.
    * ``available_usdt`` — the account's available USDT as an exact
      :class:`~decimal.Decimal`, read from the venue's own balance row;
      at or above the book's equity, for the same reason.
    * ``symbols`` — the symbols prepared, as a tuple in the sorted order
      the preparation walked; empty for a flat plan, which prepares
      nothing because it places nothing.
    """

    skew_ms: int
    available_usdt: Decimal
    symbols: tuple[str, ...]


# -- Helpers --------------------------------------------------------------------


def _system_clock_millis() -> int:
    """Wall-clock milliseconds since the epoch — this host's own reading.

    The same arithmetic feature 1's client signs ``timestamp`` with,
    stated here rather than imported from there because the client's own
    spelling is private and the preflight measures independently: it
    compares the venue's clock against the host's, and a seam that
    borrowed the very clock it is checking would report its own bias.
    """
    return int(time.time() * 1000)


def _require_client_face(client: Any) -> None:
    """Refuse a client that lacks one of the five endpoints the preflight reads.

    The preflight holds no transport of its own — every venue fact
    arrives through the client it is handed, which is what makes the
    suite's double a complete stand-in.  ``position_mode`` is among the
    five since the corrected hedge law: the mode is a fact the account
    answers, and a client that cannot ask it cannot preflight at all.
    A client missing an endpoint is a fault of the ask named here, up
    front, rather than an :class:`AttributeError` from the middle of
    the ordered checks.
    """
    for name in (
        "server_time",
        "position_mode",
        "balance",
        "set_margin_type",
        "set_leverage",
    ):
        if not callable(getattr(client, name, None)):
            raise RouterBingXPreflightError(
                f"{BINGX_PREFLIGHT_CODE}: the client must carry a callable "
                f"{name!r} — feature 1's BingXClient face, which the "
                "preflight reads the venue through and re-implements none "
                f"of — got {getattr(client, name, None)!r}; hand the "
                "preflight feature 1's client (or a double carrying its "
                "five endpoints)"
            )


def _as_decimal(value: Any, term: str, ground: str) -> Decimal:
    """Return ``value`` as an exact decimal, or refuse it by name.

    The two spellings this module reads are the speaker's own string and
    an exact :class:`~decimal.Decimal`, and nothing is read
    approximately — the rule :func:`router.rounding._as_decimal` states
    for a submission's terms and :func:`router.sizing._as_decimal` holds
    the book's, held here for the one comparison this module makes
    between two money values: a :class:`float` is a binary approximation
    of a decimal no venue ever sent, and a term read approximately would
    compare approximately.  ``NaN`` and the two infinities *parse* as
    decimals and are refused separately, because a balance that is not a
    number cannot fund anything.
    """
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterBingXPreflightError(
                f"{BINGX_PREFLIGHT_CODE}: {term} {value!r} is not a decimal "
                f"the preflight can compare; {ground} (feature 2)"
            ) from exc
    else:
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: {term} must be a decimal string or a "
            f"Decimal, got {value!r} ({type(value).__name__}); a float is a "
            "binary approximation of a decimal no venue ever sent, and a "
            f"term read approximately would compare approximately; {ground} "
            "(feature 2)"
        )
    if not number.is_finite():
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: {term} must be a finite decimal, got "
            f"{number!r}; a value that is not a number cannot fund a plan, "
            f"and {ground} (feature 2)"
        )
    return number


def _venue_decimal(value: Any, term: str) -> Decimal:
    """Return one of the venue's own money values as an exact decimal.

    The venue spells money as strings in its documents, and those are
    read through :func:`_as_decimal`; a whole ``int`` is also accepted
    here — and only here, for the venue's side of the comparison —
    because an integer JSON number is exact (no venue ever sent ``0.1``
    as an integer), while the book's own spelling stays answerable to
    the stricter law the sizer holds it to.  A ``bool`` is refused: it
    is the one ``int`` subclass that names a fact about a gate rather
    than an amount of money.
    """
    if isinstance(value, bool):
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: {term} must be the venue's decimal "
            f"spelling of an amount, got {value!r} (bool); a boolean names "
            "a fact about a gate, not a quantity of money the account "
            "holds (feature 2)"
        )
    if isinstance(value, int):
        number = Decimal(value)
        if number.is_finite():  # an int is always finite; stated for symmetry
            return number
    return _as_decimal(
        value,
        term,
        "the value is the venue's own answer for what the account holds",
    )


def _require_symbols(symbols: Any) -> tuple[str, ...]:
    """Normalize the symbols the plan will order into the sorted, unique tuple.

    The plan holds at most one leg per symbol, so duplicates cannot
    arrive from it — but the preflight is a door, not a parser of its
    callers, and a repeated symbol is normalized away (the venue holds
    one margin arrangement per symbol; a second identical write is the
    already-set answer by definition) while a symbol that is not
    non-empty text is refused as a fault of the ask: the preparation
    would only forward it to the venue to be refused there, and a local
    refusal names the caller's own value.  Sorted, because the whole
    member walks legs in the book's sorted symbol order and two runs of
    the same preflight must prepare in the same order.
    """
    if isinstance(symbols, (str, bytes)) or not isinstance(
        symbols, Iterable
    ):
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the symbols the plan will order are "
            f"an iterable of symbol names, got {symbols!r} "
            f"({type(symbols).__name__}); the preflight prepares one "
            "margin arrangement per ordered symbol, and a single value "
            "names no plan at all (feature 2)"
        )
    prepared: set[str] = set()
    for symbol in symbols:
        if not isinstance(symbol, str) or not symbol.strip():
            raise RouterBingXPreflightError(
                f"{BINGX_PREFLIGHT_CODE}: the symbols the plan will order "
                f"must be non-empty text, got {symbol!r} "
                f"({type(symbol).__name__}); the preparation forwards each "
                "symbol to the venue, and a value naming no symbol "
                "prepares nothing (feature 2)"
            )
        prepared.add(symbol)
    return tuple(sorted(prepared))


def _kill_guard() -> tuple[Any, Any, Any]:
    """Import the risk member's kill guard, deferred past module scope.

    The same door :func:`router.bingx_dry_run._require_publisher` opens
    for the book member, for the same reason: the factory's workspace
    scan imports one member's ``src/`` at a time, so a module-scope
    ``import risk`` here would make the router member's importability
    depend on scan order.  Deferred, the module is import-safe
    everywhere, while a caller that genuinely cannot reach the risk
    member is told which wheel is missing rather than shown a bare
    :class:`ImportError` — the kill check is first among the four, so a
    workspace that cannot ask it cannot preflight at all.

    Returns the guard callable and the two error classes the translation
    below branches on: the orders-killed refusal and the risk stem every
    risk-side failure subclasses.
    """
    try:
        from risk.errors import RiskError, RiskOrdersKilledError
        from risk.kill import require_orders_allowed
    except ModuleNotFoundError as exc:
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the preflight consults the risk "
            "member's own require_orders_allowed — feature 322's guard, the "
            "first of the four checks — and that member is not importable "
            "in this environment; run `uv sync --all-packages` in the "
            "workspace root (or put packages/risk/src on sys.path) so the "
            "kill channel this door must ask can be imported"
        ) from exc
    return require_orders_allowed, RiskOrdersKilledError, RiskError


def _available_usdt(payload: Any) -> Decimal:
    """Read the account's available USDT out of the venue's balance payload.

    The venue has spelled this one account read two ways across the
    endpoint's versions, and both are read rather than one guessed at:
    the v2 document the client's own ``BALANCE_PATH`` pins answers
    ``data`` as an object carrying the account's one row under
    ``balance``, while the v3 document answers ``data`` as an array of
    rows keyed by ``asset``.  Within the row, the available amount is
    ``availableMargin`` — the field both versions' documents spell —
    with ``availableBalance`` accepted as the older spelling of the same
    fact.  A payload naming no USDT row, or a row naming no available
    amount, is refused: it describes no account the plan could draw on,
    and a zero read invented for it would pass an empty account off as a
    funded one.
    """
    row: Mapping[str, Any] | None = None
    if isinstance(payload, Mapping):
        candidate = payload.get("balance")
        if isinstance(candidate, Mapping):
            row = candidate
    elif isinstance(payload, Sequence) and not isinstance(
        payload, (str, bytes)
    ):
        labelled = [
            entry
            for entry in payload
            if isinstance(entry, Mapping)
            and entry.get("asset") == BALANCE_ASSET
        ]
        if labelled:
            row = labelled[0]
        elif (
            len(payload) == 1
            and isinstance(payload[0], Mapping)
            and not str(payload[0].get("asset", "")).strip()
        ):
            # The venue's one unlabelled row is the swap account's own —
            # the array spelling with the asset field left empty, the
            # answer the v3 document gives an account settled in the one
            # asset the endpoint is about.
            row = payload[0]
    if row is None:
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the balance payload carries the "
            f"account's {BALANCE_ASSET} row — the object under 'balance' or "
            f"the array entry whose asset is {BALANCE_ASSET!r} — got "
            f"{payload!r} ({type(payload).__name__}); a document naming no "
            f"{BALANCE_ASSET} row names no account the plan could draw on, "
            "and the preflight will not read a funded account into it "
            "(feature 2)"
        )
    for field in ("availableMargin", "availableBalance"):
        if field in row and row[field] is not None:
            return _venue_decimal(
                row[field], f"the balance row's {field}"
            )
    raise RouterBingXPreflightError(
        f"{BINGX_PREFLIGHT_CODE}: the balance row names no available "
        f"amount — neither 'availableMargin' nor 'availableBalance' — got "
        f"{dict(row)!r}; the sufficiency question compares two amounts of "
        "money, and a row carrying none cannot answer it (feature 2)"
    )


def is_already_set_answer(refusal: Any) -> bool:
    """Whether a preparation refusal says the requested state already stands.

    Feature 2's own clause — *"treating an already-set answer as
    success"* — needs a judgement, because the venue makes no such
    answer easy to recognize: its published error list carries no
    dedicated code for "the arrangement you asked for is already in
    force", and different versions of the endpoint have answered the
    same no-op both as a plain success and as a non-zero code.  The
    judgement therefore reads the refusal's own message for the fact,
    through :data:`ALREADY_SET_MSG_MARKERS` matched
    case-insensitively — and it is only ever applied to refusals raised
    by the two preparation calls, so the word "already" in an unrelated
    refusal (the duplicate-clientOrderID answer, whose message also
    carries it) can never be mistaken for this one.

    Anything that is not a refusal carrying a textual ``msg`` answers
    ``False``: a value this cannot judge is not an answer the preflight
    absorbs, and the caller lets it propagate in the client's own
    vocabulary.
    """
    msg = getattr(refusal, "msg", None)
    if not isinstance(msg, str):
        return False
    lowered = msg.lower()
    return any(marker in lowered for marker in ALREADY_SET_MSG_MARKERS)


def _prepare(call: Callable[[], Any]) -> None:
    """Make one preparation write, absorbing only the already-set answer.

    The margin-type and leverage writes are the preflight's only side
    effects on the venue, and each is wrapped here so the one answer the
    feature names as success — the venue replying that the requested
    arrangement already stands — is absorbed by
    :func:`is_already_set_answer` while every other refusal propagates
    unchanged, in the client's own vocabulary with its ``code`` and
    ``msg`` still on it: a caller deciding what a refused preparation
    means (feature 4's mirror, printing a leg as refused with its code)
    reads those off the venue's own refusal, and a wrapper would bury
    them.  A swallowed refusal that did not say "already set" would
    report a prepared symbol the venue never agreed to hold, which is
    the failure this wrapper exists to not have.
    """
    try:
        call()
    except RouterBingXRefusedError as refusal:
        if is_already_set_answer(refusal):
            return
        raise


# -- The verb -------------------------------------------------------------------


def run_bingx_preflight(
    client: Any,
    *,
    equity_usdt: Any,
    symbols: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    clock: Callable[[], int] = _system_clock_millis,
) -> PreflightReport:
    """Feature 2's verb: run the preflight, answer the report or the first refusal.

    A pure ordering over one client and one clock — the same client, the
    same venue state and the same terms answer the same report or the
    same first refusal in any process, which is what makes this the door
    feature 4's mirror consults before its first placement.  The ask is
    validated up front (a client missing an endpoint, an equity or a
    symbol outside the shapes this member reads), then the four checks
    run in the feature's own order, then the preparation walks the
    sorted symbols, and only then is the report answered:

    1. ``orders_killed`` — :func:`risk.kill.require_orders_allowed`
       with this call's ``database_url``/``env`` pair, translated at
       the seam.  First, so a killed order layer asks the venue
       nothing.  A deployment naming no store passes vacuously — the
       guard's own *"no store, no status"* stance, inherited rather
       than re-decided.
    2. ``clock_skew`` — the venue's server time against the local
       clock, refused strictly beyond
       :data:`MAX_CLOCK_SKEW_MILLISECONDS`.
    3. ``hedge_mode`` — the account's own ``position_mode()`` answer,
       refused when ``dualSidePosition`` is true — never inferred from
       the positions the account happens to hold — repaired by
       :data:`ONE_WAY_REPAIR`.
    4. ``insufficient_balance`` — available USDT strictly below
       ``equity_usdt``.

    Each argument is a keyword:

    * ``client`` — feature 1's :class:`~router.bingx_client.BingXClient`,
      or a double carrying its five endpoints (``position_mode`` among
      them since the corrected hedge law).  Every venue fact is
      read through it; this module opens nothing itself.
    * ``equity_usdt`` — the book's own scalar, as the book spelled it
      (a decimal string or a :class:`~decimal.Decimal`; a ``float`` is
      refused by name, the law :func:`router.sizing.size_contract_deltas`
      holds the same term to).
    * ``symbols`` — the symbols the plan will order, any iterable;
      normalized to the sorted unique tuple and prepared one margin
      arrangement each (``ISOLATED``, leverage
      :data:`PREFLIGHT_LEVERAGE`, one-way).
    * ``database_url`` / ``env`` — handed to the kill guard unchanged;
      ``env`` defaults to the process environment, the default the
      guard itself takes.
    * ``clock`` — the local clock the skew is measured against, whole
      milliseconds; injectable so a test pins the measurement, and
      stated separately from the client's own signing clock because the
      preflight measures the host, not the signature.
    """
    _require_client_face(client)
    equity = _as_decimal(
        equity_usdt,
        "equity_usdt",
        "the equity is the one scalar the available balance is judged "
        "against",
    )
    prepared = _require_symbols(symbols)
    if not callable(clock):
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the clock must be callable answering "
            f"whole milliseconds, got {clock!r} ({type(clock).__name__}); "
            "the skew is measured between the venue's server time and this "
            "host's clock, and a value that is not a callable names no "
            "clock to measure against (feature 2)"
        )

    # 1 — orders_killed: the kill switch outranks every venue question.
    guard, orders_killed, risk_stem = _kill_guard()
    try:
        guard(database_url=database_url, env=env)
    except orders_killed as refusal:
        raise RouterBingXOrdersKilledError(refusal) from refusal
    except risk_stem as refusal:
        # The channel itself failed to answer — not "no kill", and never
        # read as one: a store that cannot be asked cannot clear the
        # order layer to trade.
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the kill channel could not be read — "
            f"{refusal}; a channel that cannot be asked whether a kill "
            "stands must not read as a channel that answered no, so "
            "nothing is placed until the store does answer (feature 2)"
        ) from refusal

    # 2 — clock_skew: the signatures every later read depends on.
    server_ms = client.server_time()
    if isinstance(server_ms, bool) or not isinstance(server_ms, int):
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the client's server_time must answer "
            f"whole milliseconds since the epoch, got {server_ms!r} "
            f"({type(server_ms).__name__}); the skew is a difference "
            "between two clock readings, and a value that is not one has "
            "no difference in it (feature 2)"
        )
    local_ms = clock()
    if isinstance(local_ms, bool) or not isinstance(local_ms, int):
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the clock must answer whole "
            f"milliseconds since the epoch, got {local_ms!r} "
            f"({type(local_ms).__name__}); the skew is a difference "
            "between two clock readings, and a value that is not one has "
            "no difference in it (feature 2)"
        )
    skew_ms = server_ms - local_ms
    if abs(skew_ms) > MAX_CLOCK_SKEW_MILLISECONDS:
        raise RouterBingXClockSkewError(skew_ms, server_ms, local_ms)

    # 3 — hedge_mode: the account's shape, before its size.
    dual_side = client.position_mode()
    if not isinstance(dual_side, bool):
        raise RouterBingXPreflightError(
            f"{BINGX_PREFLIGHT_CODE}: the client's position_mode must answer "
            f"the boolean dualSidePosition the venue's position-mode "
            f"document carries, got {dual_side!r} "
            f"({type(dual_side).__name__}); the hedge-mode question is "
            "asked of the account's own answer — never inferred from the "
            "positions it happens to hold — and a value that is not the "
            "boolean names no mode to read (feature 2)"
        )
    if dual_side:
        raise RouterBingXHedgeModeError(dual_side)

    # 4 — insufficient_balance: the plan's funding, before its writes.
    available = _available_usdt(client.balance())
    if available < equity:
        raise RouterBingXInsufficientBalanceError(available, equity)

    # The preparation: one margin arrangement per ordered symbol, in the
    # book's sorted order, each write absorbing only the already-set
    # answer.  The leverage rides the client's one-way default side —
    # the hedge check above has proved the account answers one-way.
    for symbol in prepared:
        _prepare(
            lambda symbol=symbol: client.set_margin_type(
                symbol, BINGX_MARGIN_TYPE_ISOLATED
            )
        )
        _prepare(
            lambda symbol=symbol: client.set_leverage(
                symbol, PREFLIGHT_LEVERAGE
            )
        )

    return PreflightReport(
        skew_ms=skew_ms, available_usdt=available, symbols=prepared
    )
