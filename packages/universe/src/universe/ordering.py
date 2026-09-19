"""The stable symbol ordering — feature 46.

Feature 46 (app_spec.xml, "Universe & Survivorship Integrity"): "System
returns a stable symbol ordering from every universe resolution, so
downstream reductions stay bit-reproducible." Architecture §12 states the
determinism contract that sentence serves: *stable iteration order —
``PYTHONHASHSEED=0``; explicit sorts before every reduction.* This module
is the universe's explicit sort. A cross-sectional reduction — a mean, a
z-score, a covariance — sums floats in the order the symbols arrive, and
floating-point addition is not associative, so two runs handed the same
symbols in different orders produce answers that differ in the last bits:
answers the nightly canary (§12) would then flag as a determinism break
nobody caused. The ordering a resolution hands downstream is therefore
not a presentation choice but part of the computation's contract, and it
is spelled exactly once, here.

*The order.* Symbols ascend by code point — Python's plain ``str``
comparison, deliberately not a locale- or case-folded collation, because
those vary by environment and this order may not. Code-point order is a
total order on every platform Python runs on, and it is byte-identical to
SQLite's default ``BINARY`` collation over UTF-8 text, so the SQL
``ORDER BY symbol`` behind the window query (feature 43) and the Python
sort behind the resolution (feature 42) cannot disagree about which name
comes next. Each symbol appears once: a resolution is an index, and an
index that listed a name twice would misalign every ``zip`` downstream —
a symbol is in the answer or out of it, never in it twice.

*Three faces, one rule.* :func:`canonical_symbol_order` *produces* the
order — every resolution path in this package routes its answer through
it, which is what makes "every universe resolution" true by construction
rather than by convention. :func:`is_stable_symbol_order` *asks* whether
a sequence already is in the order. :func:`assert_stable_symbol_order`
*refuses* one that is not: a consumer that has been handed a universe —
an evaluator slicing a snapshot, a replay harness reading one back —
asserts before reducing, so a corrupted or mis-routed ordering fails
loudly at the boundary instead of silently producing floats no later run
can reproduce. The refusal is :class:`UnstableSymbolOrder`, named for the
same reason every refusal in this package is named: an operator catching
it must be able to tell "the ordering was unstable" apart from any other
loud failure.

*Why sorting beats freezing.* The order could instead be pinned by
constructing every intermediate structure in sorted order, never letting
a set or dict iterate. That is fragile — one ``set`` comprehension
anywhere in the path and the hash seed reaches the output — and it is
also unnecessary: :func:`canonical_symbol_order` may build whatever
intermediate structure it likes, because the final ``sorted()`` dominates
whatever iteration order preceded it. Sorting at the boundary is the one
design whose correctness does not depend on the absence of sets
everywhere else.

One distinction this module fixes in writing: the *canonical symbol
order* is not the monthly build's *rank order*.
``MonthlyUniverse.symbols`` returns members by liquidity rank — a fact
about the market, deterministic in its own right (median descending,
symbol ascending on ties) and consumed as such. A rank is an answer to
"who was most liquid"; the canonical order is the index reductions align
against. Downstream code that needs both resolves the universe in
canonical order and looks ranks up by name — never consumes rank order
as an alignment, because rank order is only stable *for one build*.

Everything here is a pure function of the symbols given: no clock, no
seed, no environment, no store. The same input yields the same tuple on
every run, every platform, every hash seed — which is the whole point,
and what this feature's acceptance test pins by resolving the same
universe in subprocesses under different ``PYTHONHASHSEED`` values and
comparing the answers byte for byte.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

__all__ = [
    "UnstableSymbolOrder",
    "canonical_symbol_order",
    "is_stable_symbol_order",
    "assert_stable_symbol_order",
]


class UnstableSymbolOrder(ValueError):
    """A symbol sequence that is not in the stable ordering (feature 46).

    Subclasses :class:`ValueError` because an unstable ordering is a
    refusal of bad input — the same class of failure as a malformed bar
    or a mistyped knob — but named, so a consumer catching it can tell
    "the ordering a reduction was about to align against is not the one
    every run would have produced" apart from any other loud failure.
    The message names where the sequence came from and the first way it
    violates the order, followed by the instruction that clears it.
    """


def canonical_symbol_order(symbols: Iterable[str]) -> tuple[str, ...]:
    """The one ordering every universe resolution returns.

    ``symbols`` may be any iterable — a set, a generator, a tuple in
    whatever order a query or a caller produced — and the result is the
    same tuple regardless: the distinct symbols, ascending by code
    point. Intermediate iteration order cannot reach the output because
    the sort dominates it, which is the property that keeps a resolution
    bit-identical across processes with different hash seeds.

    Each symbol must be a non-empty, non-blank string; anything else is
    refused loudly (``TypeError`` for a non-string, ``ValueError`` for a
    blank), matching the validation every symbol-carrying record in this
    package performs — a resolution that indexed a name nobody could
    vouch for would be a wrong answer wearing the shape of a right one.
    An empty input yields an empty tuple: a decision time before any
    membership is the empty resolution, and it is as stable as any other.
    """
    materialized = tuple(symbols)
    for symbol in materialized:
        if not isinstance(symbol, str):
            raise TypeError(
                "a symbol ordering is a sequence of strings, got "
                f"{type(symbol).__name__} ({symbol!r})"
            )
        if not symbol.strip():
            raise ValueError(
                "a symbol ordering may not carry a blank symbol "
                f"(got {symbol!r}); a blank name is not a symbol any build vouched for"
            )
    return tuple(sorted(set(materialized)))


def is_stable_symbol_order(symbols: Iterable[str]) -> bool:
    """Whether ``symbols`` is already in the canonical order.

    True exactly when the sequence is composed of valid symbols and
    strictly increasing — which is to say, sorted *and* free of
    duplicates, the two ways a sequence can fail to be a usable index.
    Strictly increasing rather than merely non-decreasing is deliberate:
    a repeated symbol misaligns every ``zip`` downstream just as an
    unsorted one does. The empty sequence is stable, vacuously and
    honestly: nothing is in no particular order. Total on purpose — a
    non-string or blank member makes the sequence not a symbol ordering
    at all, which is ``False`` here and a loud refusal in
    :func:`assert_stable_symbol_order`; the predicate never raises.
    """
    previous: Optional[str] = None
    for symbol in symbols:
        if not isinstance(symbol, str) or not symbol.strip():
            return False
        if previous is not None and symbol <= previous:
            return False
        previous = symbol
    return True


def assert_stable_symbol_order(
    symbols: Iterable[str],
    *,
    origin: str = "universe resolution",
) -> tuple[str, ...]:
    """Return ``symbols`` as a tuple when they are in the canonical order.

    The downstream half of feature 46: a consumer handed a universe — by
    a resolution, a window query, a snapshot slice — asserts before
    reducing, so an ordering that is not the one every run would produce
    fails loudly here rather than silently in the last bits of every
    float computed over it. ``origin`` names where the sequence came
    from, so the refusal reads "``<origin>`` is not in the stable symbol
    ordering" — an operator reading the message learns which boundary
    leaked the unstable order, not merely that one did.

    Returns the symbols materialized as a tuple, unchanged: this
    function judges the order, it never repairs it. Repairing here —
    quietly sorting what it was handed — would hide exactly the defect
    it exists to catch, the way a typo-swallowed ``None`` hides a lookup
    bug. The fix is always upstream: route the producing path through
    :func:`canonical_symbol_order`, and let this assert prove it stayed
    routed.
    """
    if not isinstance(origin, str) or not origin.strip():
        raise ValueError(
            "origin must be a non-empty, non-blank string naming where the "
            f"symbols came from, got {origin!r}"
        )
    materialized = tuple(symbols)
    for index, symbol in enumerate(materialized):
        if not isinstance(symbol, str):
            raise TypeError(
                f"{origin} returned {type(symbol).__name__} at position "
                f"{index} ({symbol!r}); a symbol ordering is a sequence of "
                "strings"
            )
        if not symbol.strip():
            raise UnstableSymbolOrder(
                f"{origin} returned a blank symbol at position {index}; a "
                "blank name is not a symbol any build vouched for, and a "
                "reduction over it could never be reproduced"
            )
    for index in range(1, len(materialized)):
        previous, current = materialized[index - 1], materialized[index]
        if current == previous:
            raise UnstableSymbolOrder(
                f"{origin} repeats the symbol {previous!r} at positions "
                f"{index - 1} and {index}; a symbol is in a resolution once "
                "or not at all, and a repeated index misaligns every "
                "zip against it"
            )
        if current < previous:
            raise UnstableSymbolOrder(
                f"{origin} is not in the stable symbol ordering: "
                f"{current!r} follows {previous!r} at positions {index - 1} "
                f"and {index}; a downstream reduction over an unstable "
                "ordering is not bit-reproducible — route it through "
                "canonical_symbol_order() at the source, then assert again"
            )
    return materialized
