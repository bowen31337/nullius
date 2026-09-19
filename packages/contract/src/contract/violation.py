"""The absent-symbol rejection and the ``contract_violation`` outcome.

Feature 12 of app_spec.xml: "System rejects a signal return value whose index
contains a symbol absent from the window universe, which emits a
contract_violation outcome."  :mod:`contract.signal` declares the entrypoint
and what a *conforming* return is (feature 11); this module is the consumer
that names the *rejection* and the outcome a run records because of it.

**What an "index" is, given Polars has none.**  Feature 11 fixes the pairing
as positional — the *i*-th value is the score for the *i*-th symbol of
``ctx.universe`` — because a :class:`polars.Series` has no ``index``
attribute, no ``index=`` constructor keyword, and ``series["A"]`` raises (see
that module's docstring).  That is a statement about a *bare* series, and it
is the conforming shape: a bare series carries no labels, so it misattributes
nothing and this module has nothing to reject.

But a return can carry labels anyway, and agents do it — the docstring every
signal is written against says *"Returns index=symbol, value=float score"*
(architecture §5.1), which is pandas vocabulary, and an LLM translating it
into Polars reaches for whichever carrier Polars does offer:

* a :class:`polars.DataFrame` with a ``symbol`` column — the most common
  shape, and the direct pandas reading;
* a :class:`polars.Series` of ``Struct`` dtype with a ``symbol`` field;
* a plain ``dict`` mapping symbol to score;
* a bare series *named* after a symbol (``pl.Series("DOGEUSDT", [0.3])``).

:func:`return_index` reads the labels out of every one of those, so "the
index contains a symbol absent from the window universe" is a question with a
single answer regardless of which carrier the agent chose.

**Why this is worth rejecting rather than tolerating.**  A return naming a
symbol the window does not contain is not a cosmetic labelling mismatch; it
is *silent misattribution*.  The window's universe is what the evaluator
aligns scores against, so a one-symbol universe scored with
``pl.Series("DOGEUSDT", [0.3])`` is length-conforming, finite, float — and
attributes DOGE's score to BTCUSDT.  Nothing downstream could notice: the
evaluation succeeds and the number is wrong.  Feature 11's checks cannot see
it because they are checks on *values*; this is a check on the *claim* the
return makes about which symbol each value belongs to.  Rejecting it is the
only place the mistake is still visible.

**The one rule for reading a name as an index claim.**  A bare series' name
is not an index — it is a column name, and a series named ``"score"`` is
exactly the conforming return feature 11 accepts.  So a name is read as an
index claim only when it is *ticker-shaped* (:func:`is_symbol_label`): upper
case, alphanumeric, ending in a known quote asset.  ``"DOGEUSDT"`` is a
claim; ``"score"``, ``"VOL"``, ``"S1"`` and ``"momentum"`` are names.  The
distinction is deliberately a shape test rather than a blocklist of words
that *look* like names, because a name nobody anticipated must default to
"not a claim" — a false rejection of a conforming return would be a
correctness failure in the other direction, and a worse one: it would refuse
to score a correct signal.

**The outcome, and where the line to feature 11 is drawn.**
:func:`check_signal_return` composes the two halves — this module's index
check and feature 11's :func:`~contract.signal.validate_signal_return` — into
one :class:`SignalReturnOutcome` whose :attr:`~SignalReturnOutcome.outcome`
is ``"ok"`` or :data:`CONTRACT_VIOLATION`.  That string is the recordable
value the spec names, and it is emitted as a *value*, never as a raise: a
non-conforming return is a hypothesis that produced a bad artifact, not a
programming error, and the caller — the evaluator, the authoring loop — is
the one that knows whether that costs a retry, a charge or a discard (the
trial ledger's ``outcome`` column is feature 91's, and this module
deliberately does not define that vocabulary).  The line to
:mod:`contract.signal` stays where feature 11 drew it: that module answers
*what is a conforming return*, this one answers *which symbol does this
return claim, and what outcome follows when the claim is false*.  Neither
module imports the other's behavior — this one only reads its types and calls
its validator.

**The layering note.**  ``polars`` is imported lazily, on the same seam
:func:`contract.signal.validate_signal_return` opens: the ``contract``
package is imported during the application factory's workspace scan, so a
module-scope ``import polars`` here would make polars a precondition for
*composing the application*.  Nothing at module scope below needs it — the
label rule is pure string work — so only the paths that genuinely inspect a
Polars return reach for it, and they name the missing dependency when reached
without it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .signal import SignalReturnProblem, validate_signal_return

if TYPE_CHECKING:  # pragma: no cover - typing only; polars is deferred to runtime
    import polars as pl

__all__ = [
    "CONTRACT_VIOLATION",
    "INDEX_LABEL_FIELD",
    "OUTCOME_OK",
    "QUOTE_ASSETS",
    "SignalReturnOutcome",
    "absent_symbol_problems",
    "check_signal_return",
    "is_symbol_label",
    "return_index",
    "universe_symbols",
]

#: The outcome a run records when a return's index names a symbol the window
#: does not contain.  Spelled once, here, because two writers spelling it
#: differently would persist two outcomes for one failure — the same reason
#: :data:`contract.signal.SIGNAL_ENTRYPOINT` is a constant rather than a
#: convention.
CONTRACT_VIOLATION = "contract_violation"

#: The outcome of a return that conforms.  The partner of
#: :data:`CONTRACT_VIOLATION` in :class:`SignalReturnOutcome.outcome`, so a
#: caller branches on two constants rather than on string literals it typed
#: itself.
OUTCOME_OK = "ok"

#: The name of the field a labelled return carries its symbols under.  One
#: spelling for all three carriers that can name it — a ``DataFrame`` column,
#: a ``Struct`` series' field — because a signal that labels its symbols one
#: way in a frame and another way in a struct would be two vocabularies for
#: one fact, and this module could only check the one it guessed.
INDEX_LABEL_FIELD = "symbol"

#: The quote assets that make a bare series' name read as a ticker pair.  A
#: market symbol in this system is always a base asset against a quote asset
#: (``BTCUSDT``, ``ETHBTC``, ``SOLUSDC``), so a label ending in one of these —
#: upper case, alphanumeric — is shaped like a symbol and read as an index
#: claim; anything else is a series *name*.  Kept as an explicit, inspectable
#: tuple rather than folded into the regex so a venue or a new quote currency
#: is a one-line edit at a clearly-symbolic place.
QUOTE_ASSETS: tuple[str, ...] = (
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "BUSD",
    "DAI",
    "USD",
    "BTC",
    "ETH",
    "BNB",
    "EUR",
    "TRY",
    "BRL",
)

# ``<base><quote>``: at least one base character (upper case, alphanumeric,
# and the base may itself contain digits — ``1INCHUSDT``), then a quote asset.
# Anchored with \A/\Z rather than ^/$ so a trailing newline cannot smuggle a
# non-symbol past the test — the same reasoning ``universe.keys`` uses for its
# hash pattern.
_SYMBOL_LABEL = re.compile(
    r"\A[A-Z0-9]+(?:" + "|".join(QUOTE_ASSETS) + r")\Z"
)


def is_symbol_label(label: object) -> bool:
    """Whether ``label`` is shaped like a market symbol rather than a name.

    The rule :func:`return_index` applies to a bare series' name, exposed so a
    caller can see and test the boundary rather than infer it from behavior.
    True for an upper-case alphanumeric token ending in a known quote asset
    (:data:`QUOTE_ASSETS`): ``BTCUSDT``, ``ETHBTC``, ``1INCHUSDT``.  False for
    anything that is not a string, and for every name a score series would
    plausibly carry — ``score``, ``VOL``, ``S1``, ``momentum``, ``signal_1``.

    Nothing about case is folded: the universe's own canonical casing is
    authoritative (the same stance ``universe.keys`` takes toward symbol
    casing), so a lower-cased ``btcusdt`` is not silently accepted as the
    symbol ``BTCUSDT`` — it is not read as a symbol *claim* at all.
    """
    return isinstance(label, str) and _SYMBOL_LABEL.match(label) is not None


def _require_polars() -> Any:
    """Import polars, naming the missing dependency if it is not installed.

    Deferred rather than module-scope for the reason in the module docstring:
    the factory's workspace scan imports this package, and polars must not be
    a precondition for composing the application.
    """
    try:
        import polars as pl
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "check_signal_return requires polars, which the nullius-contract "
            "member declares for the signal return type; run `uv sync` "
            "(or `pip install polars`) in the workspace root"
        ) from exc
    return pl


def universe_symbols(universe: Any) -> tuple[str, ...]:
    """The symbols a window (or a plain collection) makes tradable.

    Accepts a :class:`~contract.window.MarketWindow` by duck-typing its
    ``universe`` attribute rather than by ``isinstance``, and that is
    load-bearing rather than defensive: the module loader imports a scanned
    package under a synthetic name, so a window composed by the factory is not
    an instance of ``contract.MarketWindow`` as imported normally — an
    ``isinstance`` check across that seam silently returns False (the reason
    ``MARKET_WINDOW_ABI`` is advertised by name).  ``.universe`` is the window
    contract's own accessor and holds across the seam.

    A bare string is refused, exactly as :func:`contract.window._as_universe`
    refuses one: iterating ``"BTCUSDT"`` yields one "symbol" per character,
    which would look plausible and be silently wrong.
    """
    source = getattr(universe, "universe", universe)
    if isinstance(source, str):
        raise TypeError(
            "universe must be a MarketWindow or a collection of symbols, not a "
            f"single string; pass ({source!r},) for one symbol"
        )
    try:
        return tuple(source)
    except TypeError as exc:
        raise TypeError(
            "universe must be a MarketWindow or an iterable of symbols, got "
            f"{type(source).__name__}"
        ) from exc


def _struct_symbol_field(pl: Any, series: "pl.Series") -> "pl.Series | None":
    """The ``symbol`` field of a struct series, or ``None`` if it has none.

    Only the *top-level* field is read.  A symbol nested one level down is a
    label the return did not put where the contract says labels go, and
    digging for it would make "which field is the index" a search this module
    performs rather than a shape the return declares.
    """
    dtype = series.dtype
    if dtype != pl.Struct:
        return None
    if INDEX_LABEL_FIELD not in tuple(f.name for f in dtype.fields):
        return None
    return series.struct.field(INDEX_LABEL_FIELD)


def return_index(result: Any) -> tuple[Any, ...]:
    """The symbols ``result`` claims its values belong to.

    Empty for a return that claims nothing — the conforming bare series of
    feature 11, whose pairing is positional — and otherwise the labels the
    return carries, in the order it carries them:

    * a :class:`polars.DataFrame` with a ``symbol`` column → that column;
    * a struct :class:`polars.Series` with a ``symbol`` field → that field
      (which *wins* over the series' name: an explicit field is a declaration,
      a column name is a name);
    * a mapping → its keys;
    * a bare series whose name is ticker-shaped (:func:`is_symbol_label`) →
      that one name, since a single label is the only index a series can
      carry;
    * anything else → nothing.

    Labels are returned *unvalidated* — a value here may be ``None``, an
    integer, or an empty string, and it is :func:`absent_symbol_problems` that
    decides which of those is a malformed claim and which is an absent symbol.
    Splitting the two keeps the reading of a carrier (this function, pure and
    polars-shape-only) separate from the verdict on its labels, so a caller
    can ask what a return claims without also being told whether it is legal.

    Subtlety worth stating: an *empty* series name is Polars' "unnamed"
    (``pl.Series([1.0]).name == ""``), which is not a claim — so it is skipped
    here rather than reported as a malformed label.  An explicitly empty
    ``symbol`` field or dict key *is* a claim the agent wrote, and is
    reported.
    """
    pl = _require_polars()

    if isinstance(result, pl.DataFrame):
        if INDEX_LABEL_FIELD not in result.columns:
            return ()
        return tuple(result.get_column(INDEX_LABEL_FIELD).to_list())

    if isinstance(result, pl.Series):
        field = _struct_symbol_field(pl, result)
        if field is not None:
            return tuple(field.to_list())
        name = result.name
        if is_symbol_label(name):
            return (name,)
        return ()

    if isinstance(result, Mapping):
        return tuple(result.keys())

    return ()


def absent_symbol_problems(
    result: Any,
    universe: Any,
) -> list[SignalReturnProblem]:
    """The index problems in ``result`` against ``universe``, in return order.

    One problem per offending label, so an agent learns *which* label was
    wrong rather than that something was — the same per-position reporting
    feature 11 uses for a non-finite score.  Two kinds are reported:

    ``absent_symbol``
        A label that is a non-empty string and is not in the universe.  The
        spec's headline case: a return claiming to score ``DOGEUSDT`` against
        a window whose universe is ``("BTCUSDT",)``.  The message names the
        symbol and its position, because the position is what lets an author
        find the line that produced it.
    ``non_string_symbol_label``
        A label that is not a non-empty string — ``None`` (a null in a
        ``symbol`` column), an integer, ``""``.  It cannot name any symbol, so
        it is reported as malformed rather than as absent; conflating the two
        would send an author looking for a spelling mistake that is not there.

    A label that *is* in the universe produces nothing: the claim is true, and
    the evaluation proceeds.  The universe is compared by exact string
    equality — no case folding, no trimming — because the universe's own
    canonical casing is authoritative (``universe.ordering``), and accepting a
    near-miss spelling would align a score to a symbol the window never
    listed.
    """
    labels = return_index(result)
    if not labels:
        return []

    symbols = universe_symbols(universe)
    known = set(symbols)
    problems: list[SignalReturnProblem] = []

    for position, label in enumerate(labels):
        if not isinstance(label, str) or not label:
            problems.append(
                SignalReturnProblem(
                    kind="non_string_symbol_label",
                    message=(
                        f"signal return index at position {position} is "
                        f"{label!r}, which names no symbol; a label must be a "
                        "non-empty symbol string"
                    ),
                    symbol=None,
                )
            )
            continue
        if label in known:
            continue
        problems.append(
            SignalReturnProblem(
                kind="absent_symbol",
                message=(
                    f"signal return index names {label!r} at position "
                    f"{position}, which is absent from the window universe of "
                    f"{len(symbols)} symbol(s); a score may only be attributed "
                    "to a symbol the window makes tradable at its decision time"
                ),
                symbol=label,
            )
        )

    return problems


@dataclass(frozen=True)
class SignalReturnOutcome:
    """What a run records about one signal return: conforming, or a violation.

    The recordable half of feature 12 — "emits a contract_violation outcome"
    is this value, whose :attr:`outcome` is :data:`CONTRACT_VIOLATION` whenever
    anything at all was wrong with the return.  A value rather than an
    exception, for the reason every refusal in this package is a value: the
    caller knows what a bad return costs (a retry, a trial charge, a
    discarded hypothesis) and a raise would steal that decision.

    Attributes
    ----------
    outcome:
        :data:`OUTCOME_OK` or :data:`CONTRACT_VIOLATION` — the string a run
        persists.  One field rather than a boolean because the ledger's
        ``outcome`` column is a text vocabulary (feature 91) and a bool would
        have to be translated at every write site.
    index:
        The labels the return carried, in order.  Empty for the positional,
        bare-series case, which is what makes "this return made no symbol
        claim" readable off the record rather than inferred from an empty
        problem list.
    absent_symbols:
        The symbols the return claimed and the window does not list, sorted
        and de-duplicated.  Sorted — unlike :attr:`problems`, which is in
        return order — because this is the field a human reads to see the
        extent of the mistake at a glance, and because a set comparison
        (``outcome.absent_symbols == ("DOGEUSDT",)``) should not depend on
        where in the frame the symbols happened to appear.
    problems:
        Every problem found, feature 12's index problems first and then
        feature 11's shape problems.  The order is deliberate: an
        absent-symbol problem identifies *which* score is misattributed, which
        is the more concrete thing an author can act on, so it leads.  A
        tuple, and frozen with the rest of the record.
    """

    outcome: str
    index: tuple[str, ...] = ()
    absent_symbols: tuple[str, ...] = ()
    problems: tuple[SignalReturnProblem, ...] = field(default=())

    @property
    def ok(self) -> bool:
        """Whether the return conforms.  The inverse of :attr:`violated`."""
        return self.outcome == OUTCOME_OK

    @property
    def violated(self) -> bool:
        """Whether a ``contract_violation`` outcome was emitted."""
        return self.outcome == CONTRACT_VIOLATION

    def as_record(self) -> dict[str, Any]:
        """The outcome as a JSON-serializable record.

        The shape a run persists or logs: the outcome string, the claimed
        index, the absent symbols, and every problem flattened to its three
        fields.  Frozen objects are not serializable, and a caller reaching
        for ``dataclasses.asdict`` would have to flatten :class:`SignalReturnProblem`
        itself — so the flattening lives here, once, next to the fields whose
        meaning it is documenting.
        """
        return {
            "outcome": self.outcome,
            "index": list(self.index),
            "absent_symbols": list(self.absent_symbols),
            "problems": [
                {"kind": p.kind, "message": p.message, "symbol": p.symbol}
                for p in self.problems
            ],
        }


def check_signal_return(result: Any, universe: Any) -> SignalReturnOutcome:
    """Check a signal's return against a window and emit its outcome.

    The evaluator-side entry point feature 12 describes: hand it what the
    sandbox returned and the window it ran against (or just the window's
    universe), and read back one :class:`SignalReturnOutcome` whose
    :attr:`~SignalReturnOutcome.outcome` is :data:`CONTRACT_VIOLATION` — the
    outcome the run records — or :data:`OUTCOME_OK`.

    This composes rather than re-implements.  Feature 11's
    :func:`~contract.signal.validate_signal_return` remains the authority on
    *value* conformance (is it a Polars series, is the dtype floating, does
    the length match, is every value finite) and
    :func:`absent_symbol_problems` is the authority on *label* conformance
    (does every symbol the return claims exist in the window), and both run
    here so a caller cannot check one half and forget the other.  Composition
    is why feature 12 depends on feature 11 instead of editing it: neither
    module's checks moved, and a future feature that adds a third class of
    check extends this function without touching either.

    Both halves always run, even when the first already failed — a return can
    be a mislabeled ``DataFrame`` (an index violation *and* a
    ``not_a_series`` violation), and reporting both is what tells the author
    that fixing the carrier alone will not make it conform.

    Ordering, and one consequence of it: the index problems come first.  A
    length-mismatched return can also carry an index, and feature 11's
    validator short-circuits its per-value checks on a length mismatch but
    not its other checks — so a return that is both mislabeled *and*
    malformed reports both, and the reader sees the symbol claim before the
    shape complaint.  Nothing about the outcome's truth depends on the order;
    :attr:`~SignalReturnOutcome.absent_symbols` is sorted precisely so it does
    not.
    """
    symbols = universe_symbols(universe)
    index = return_index(result)
    index_problems = absent_symbol_problems(result, symbols)
    shape_problems = [
        problem
        for problem in validate_signal_return(result, symbols)
    ]
    problems = (*index_problems, *shape_problems)

    absent = tuple(
        sorted({p.symbol for p in index_problems if p.symbol is not None})
    )

    return SignalReturnOutcome(
        outcome=CONTRACT_VIOLATION if problems else OUTCOME_OK,
        index=tuple(label for label in index if isinstance(label, str)),
        absent_symbols=absent,
        problems=problems,
    )
