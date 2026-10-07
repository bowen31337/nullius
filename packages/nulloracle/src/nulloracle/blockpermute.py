"""Feature 115's block permutation: shuffle contiguous blocks of a series.

app_spec.xml, "Null Oracle & Planted Nulls", feature 115: *System
block-permutes forward returns for a null node using a stored permutation
seed with a 20 day block length.*  This module is that permutation — the
mechanism the rest of the member has been pointing at as a *seam* since the
sidecar schema was first sealed.  Feature 109's sidecar stores, beside the
null bit, a ``perm_seed`` and a ``block_days`` for every null node, and the
load-bearing word there is **stored**: the parameters that make a null
node's series what it is are sealed at the moment the assignment is made so
that the same campaign replayed reproduces the same series.  This module is
the thing the stored seed and block length are *for* — it turns a real
forward-return series into the permuted one a null node reports.

**What block permutation is, and the one property the sentence carries.**
The permutation shuffles *contiguous blocks* of the series rather than its
individual points: the series is cut into runs of ``block_days`` consecutive
observations, those runs are shuffled as units, and the shuffled runs are
concatenated back into a series of the same length.  docs/nullius-tech-
architecture.md §7.3 names the reason in one line — *"Block permutation
shuffles contiguous 20-day blocks, preserving return autocorrelation and
volatility clustering while destroying the signal-to-target relationship"* —
and the mechanism is the whole of it.  A pointwise shuffle would tear a
return series apart observation by observation and destroy the serial
dependence the series carries; a block shuffle moves *runs* of the series
intact, so the autocorrelation and volatility clustering *within* a run
survive — only the order the runs appear in is scrambled.  That is exactly
the asymmetry a planted null needs: the null branch must *look* like a real
return series (so feature 123's KS guard cannot tell it apart) while carrying
none of the signal-to-target relationship a real branch carries.  The
expected true out-of-sample edge of a null branch is zero by construction,
because the targets the signal was measured against have been moved to a
different block.

**The block length, and why it is an argument and not a constant.**  The
permutation takes ``block_days`` from its caller rather than hard-coding 20,
and the split is deliberate.  Feature 115 fixes the *default* — *"a 20 day
block length"* — and :data:`~nulloracle.assignment.DEFAULT_BLOCK_DAYS` is
that default, imported here so the value the permutation reads and the value
the sidecar seals are one value and cannot drift apart.  But the block length
is a stored *per-assignment* field (feature 109's schema) precisely because
§7.4's detectability guard treats it as the knob an operator turns when the
nulls start to look detectable — *"investigate the block length"* — and an
assignment that recorded only "the block length we happen to use now" would
become unreproducible the first time it changed.  So the permutation reads
the block length the assignment sealed, defaulting to 20 when a caller names
none, and a campaign replayed from the same seed and the same stored block
length reproduces the same series.

**The seed, and why it is the whole of the permutation's reproducibility.**
The shuffle is driven by a :class:`random.Random` seeded from ``seed`` — the
same ``perm_seed`` the sidecar stores beside the bit.  The seed is what makes
the permutation reproducible: a campaign replayed from the same seed shuffles
the same blocks into the same order, which is §12's determinism contract and
the reason the seed is *stored* rather than re-drawn.  A seed that is not a
genuine non-negative integer is refused, for the same reason feature 109's
schema refuses one at the write — a seed the generator cannot seed with would
make the "same campaign, same series" promise unenforceable, and a seed that
was a truthy-looking ``True`` would shuffle from a different distribution than
the one the assignment sealed.  The refusal here and the refusal at the write
are the same value seen from the two ends of the feature.

**The permutation is a fact about a series, so it is a pure function.**  The
grain is the series — one node's forward returns — and the permutation maps a
series to a series of the same length, carrying no node id, no campaign, no
store.  It opens no database and reads no file: it is the *mechanism* feature
115 names, and the mechanism is a function of the series, the seed and the
block length alone.  The store that holds the seed (feature 109's sidecar)
and the resolution that decides *which* branch to serve (feature 121) are the
callers that supply those three; this module supplies the shuffle.  It is the
same seam feature 121's resolution already observes — :mod:`nulloracle.
resolution` takes the permutation as a callable ``permute(targets)`` precisely
because the *which branch* decision is feature 121's and the *permutation* is
this module's — so a caller composes the two: it reads the seed and block
length from §7.1's sidecar and hands ``block_permute(series, seed=...,
block_days=...)`` to the resolution as its ``permute``.

**Two spellings, and why they are one module.**  :func:`block_indices` is the
permutation as a rearrangement of positions — it returns, for each output
slot, the index of the input it draws from — and :func:`block_permute` is the
permutation applied to a series of values.  They are the same shuffle seen
from the two sides: ``block_permute(series, ...)`` is
``series[block_indices(range(len(series)), ...)]``.  The index form is
exposed on its own because it is the permutation answerable *without a series
in hand* — a test that wants to assert the shuffle moves whole blocks, or a
caller that wants to permute something other than a float series, composes
against the indices directly — and because the two are separately arguable
(the index form carries no claim about the values being finite reals).  Both
share the one seeded shuffle, so the two can never disagree about what the
permutation did.

**Stdlib only, and import-cheap.**  ``math`` and ``random`` (the latter
deferred to first use, the way :mod:`nulloracle.flipdepth` defers it), no
third-party import at module scope, so the factory's scan — which imports this
package to fire its ``@register`` — pays nothing for this module, the same
discipline every store in this member states.  The module imports
:data:`~nulloracle.assignment.DEFAULT_BLOCK_DAYS` rather than re-spelling the
number, so the block length the permutation defaults to and the block length
the sidecar seals are one value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .assignment import DEFAULT_BLOCK_DAYS
from .errors import KsGuardError

__all__ = [
    "DEFAULT_BLOCK_DAYS",
    "block_indices",
    "block_permute",
    "block_permute_cross_section",
]


def block_permute(
    series: Any,
    *,
    seed: Any,
    block_days: Any = DEFAULT_BLOCK_DAYS,
) -> tuple[float, ...]:
    """Feature 115's block permutation of a forward-return series.

    The whole of feature 115 in one call: cut ``series`` into contiguous runs
    of ``block_days`` observations, shuffle those runs as units with a
    generator seeded from ``seed``, and concatenate the shuffled runs back into
    a series of the same length.  The permutation preserves the autocorrelation
    and volatility clustering *within* each block while destroying the
    relationship between the series and the targets measured against it — which
    is why a null branch built from it looks like a real return series to
    feature 123's KS guard yet carries an expected true out-of-sample edge of
    exactly zero.

    The returned series is always the same length as the input — a block
    permutation moves observations, it never adds or drops them — which is the
    property feature 121's resolution re-checks after calling this: a permuted
    series of a different length would mark the null branch as plainly as an
    ``is_null`` column would, and §7.2 forbids the caller distinguishing the
    two branches from the response.

    The permutation is reproducible from ``seed`` alone: a series permuted next
    year from the same seed and the same block length returns the same series,
    which is §12's determinism contract and the reason feature 109 stores the
    seed beside the bit rather than re-drawing it.

    Refuses, in this order, and each refusal names what it is about:

    1. a ``block_days`` that is not a genuine positive integer
       (:class:`~nulloracle.errors.KsGuardError`) — a block length of zero or
       less cuts the series into no blocks, and a block length that is a
       truthy-looking ``True`` would cut it into one observation per block and
       so degenerate to a pointwise shuffle, which preserves no autocorrelation
       at all;
    2. a ``seed`` that is not a genuine non-negative integer
       (:class:`~nulloracle.errors.KsGuardError`) — the seed is the whole of
       the permutation's reproducibility, and a seed the generator cannot seed
       with would make a replayed campaign shuffle a different series;
    3. a ``series`` that is not a non-empty sequence of finite reals
       (:class:`~nulloracle.errors.KsGuardError`) — a forward-return series is
       what the permutation acts on, and an empty, non-finite or non-numeric
       series is no series a null node could report.
    """
    block = _validated_block_days(block_days)
    drawn_seed = _validated_seed(seed)
    items = _validated_series(series)
    blocks = [items[i : i + block] for i in range(0, len(items), block)]
    _seeded_rng(drawn_seed).shuffle(blocks)
    return tuple(element for block in blocks for element in block)


def block_indices(
    indices: Any,
    *,
    seed: Any,
    block_days: Any = DEFAULT_BLOCK_DAYS,
) -> tuple[int, ...]:
    """The permutation as a rearrangement of positions — feature 115 without a series.

    The same shuffle :func:`block_permute` applies, expressed as *which input
    position each output slot draws from* rather than applied to a series of
    values.  Cut ``indices`` into contiguous runs of ``block_days`` positions,
    shuffle those runs with a generator seeded from ``seed``, and flatten: the
    result is, for each output slot in order, the index of the input it came
    from.  ``block_permute(series, seed=s, block_days=b)`` is therefore exactly
    ``tuple(indices[i] for i in block_indices(range(len(indices)), seed=s,
    block_days=b))`` — the two are one permutation seen from opposite sides,
    sharing the one seeded shuffle so they can never disagree.

    Exposed on its own because it answers *how the permutation rearranges*
    without a series in hand: a test asserting the shuffle moves whole blocks
    (and preserves the members of each block) composes against the indices
    directly, and a caller that wants to permute something other than a float
    series permutes its own positions and gathers.  It carries no claim that
    the permuted thing is a finite real — that is :func:`block_permute`'s, and
    keeping the two apart is why the index form validates only the permutation
    parameters and the block structure.

    Refuses, in this order, and each refusal names what it is about:

    1. a ``block_days`` that is not a genuine positive integer
       (:class:`~nulloracle.errors.KsGuardError`) — the same reason
       :func:`block_permute` refuses one: a block length that cuts no blocks,
       or that degenerates to one observation per block;
    2. a ``seed`` that is not a genuine non-negative integer
       (:class:`~nulloracle.errors.KsGuardError`) — the seed is the whole of
       the permutation's reproducibility;
    3. an ``indices`` that is not a non-empty sequence
       (:class:`~nulloracle.errors.KsGuardError`) — the permutation rearranges
       positions, and there are no positions to rearrange in an empty or
       non-sequential input.
    """
    block = _validated_block_days(block_days)
    drawn_seed = _validated_seed(seed)
    items = _validated_positions(indices)
    blocks = [items[i : i + block] for i in range(0, len(items), block)]
    _seeded_rng(drawn_seed).shuffle(blocks)
    return tuple(position for block in blocks for position in block)


def block_permute_cross_section(
    panel: Any,
    *,
    seed: Any,
    block_days: Any = DEFAULT_BLOCK_DAYS,
) -> dict[Any, dict[str, float]]:
    """Feature 115's block permutation, applied to a symbol-by-date panel.

    §7.2 writes the permutation over ``forward_returns`` — one series — but
    a Type-R or Type-D node's targets are a *cross-section per rebalance
    date*: ``{date: {symbol: forward return}}``, and the universe a snapshot
    carries is not fixed over the window — a symbol lists partway through
    (feature 72's point-in-time admission rule) or delists before the end.
    Treating the panel as one series and swapping whole date-rows between
    blocks — the reading every caller of :func:`block_indices` over a panel
    had reached for — moves a row's symbols onto a date where some of them
    never had a bar: a symbol listed in the last block, shuffled onto a date
    in the first, is a target for a bar that does not exist, and
    :func:`evaluator.gate_targets`'s support rule refuses it by name (every
    date's answer must name *exactly* that date's own cross-section, no
    wider and no narrower). This function is the mechanism that does not
    make that move.

    **Per symbol, not per row.** Rather than permuting rows of dates, this
    function permutes each symbol's *own* run of observations: a symbol's
    series is the values it carries on the dates it is actually present —
    the same contiguous-block shuffle :func:`block_permute` applies to a
    bare series, here applied to the compacted sequence of dates *that
    symbol* has a value on. A date d's permuted row therefore carries a
    symbol if and only if the unpermuted panel carries that symbol on d —
    membership never moves, only the value does — which is exactly what
    keeps every date's permuted cross-section equal to that date's real one:
    a symbol listed in the last block draws its shuffled value from one of
    its own later dates and never lands before its listing, and a symbol
    delisted mid-window never lands after it, because the positions it is
    ever gathered from or written to are its own.

    **Unchanged for a symbol present throughout.** A symbol with a value on
    every date in ``panel`` is, in this function's terms, a symbol whose own
    "dates it is present on" is the panel's whole date axis — so its local
    permutation is :func:`block_indices` called over ``range(len(panel))``
    with this call's own ``seed`` and ``block_days``, the identical call a
    whole-row swap would have made. For a panel where every symbol is
    present throughout, this function's answer is therefore bit-identical
    to the whole-row algorithm it replaces; the two differ only where the
    universe actually varies, which is the one place the whole-row algorithm
    was wrong.

    **Still one shuffle, still reproducible.** Every symbol's local
    permutation is read from the same ``seed`` and ``block_days`` — the
    entry's own stored ``perm_seed``/``block_days`` (§7.1), never a
    per-symbol derivative — so two calls with the same panel, seed and block
    length return the same result (§12's determinism contract), and a
    symbol's own run is still cut into contiguous runs of ``block_days``
    observations and shuffled as units, preserving the autocorrelation and
    volatility clustering within a run while destroying the pairing between
    a date and the value it used to carry (§7.3).

    Refuses, in this order, and each refusal names what it is about:

    1. a ``block_days`` or ``seed`` that :func:`block_permute` would refuse
       (:class:`~nulloracle.errors.KsGuardError`) — the same contract, read
       once before the panel is walked;
    2. a ``panel`` that is not a non-empty mapping of date to a mapping of
       symbol to finite real (:class:`~nulloracle.errors.KsGuardError`) — a
       cross-section the permutation cannot act on is no panel a null node
       could report.

    Returns a plain ``dict`` keyed by the exact dates ``panel`` carried, each
    row a plain ``dict`` of the symbols that date's unpermuted row carried —
    never zero-filled, never invented, and never carrying a symbol the date
    did not already have.
    """
    block = _validated_block_days(block_days)
    drawn_seed = _validated_seed(seed)
    rows = _validated_panel(panel)
    days = list(rows)
    # Every position a symbol is actually present at, in the panel's own
    # date order — the compacted "series" this function permutes for that
    # symbol, so a gap in its history (a delisting, a late listing) is
    # simply absent from its own positions and never a position the
    # permutation reads from or writes to.
    positions_by_symbol: dict[str, list[int]] = {}
    for position, day in enumerate(days):
        for symbol in rows[day]:
            positions_by_symbol.setdefault(symbol, []).append(position)
    permuted: dict[Any, dict[str, float]] = {day: {} for day in days}
    for symbol, positions in positions_by_symbol.items():
        values = [rows[days[position]][symbol] for position in positions]
        order = block_indices(
            range(len(positions)), seed=drawn_seed, block_days=block
        )
        for slot, source_index in enumerate(order):
            permuted[days[positions[slot]]][symbol] = values[source_index]
    return permuted


def _validated_panel(value: Any) -> dict[Any, dict[str, float]]:
    """Refuse a cross-sectional panel that is not ``{date: {symbol: return}}``.

    The read-side twin of :func:`_validated_series` for the panel grain:
    :func:`block_permute_cross_section` acts on one node's whole
    cross-section, not one symbol's series, so the value it is handed must be
    a genuine panel — a non-empty mapping whose every row is itself a mapping
    of non-empty symbol names to finite reals. A row may be empty (a date
    with no scored symbols is still a date), but the panel as a whole must
    carry at least one date, and every value present must be a real number a
    target could be measured from.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        raise KsGuardError(
            f"panel must be a mapping of date to {{symbol: forward return}}, "
            f"got {type(value).__name__}; feature 115's cross-sectional "
            "permutation shuffles a node's whole panel, and a value that is "
            "not a mapping of dates to rows is no panel a null node could "
            "report"
        )
    if not value:
        raise KsGuardError(
            "panel must be non-empty; a cross-sectional permutation shuffles "
            "the dates a panel carries, and an empty panel has no dates to "
            "shuffle and no null node it could be the panel of"
        )
    captured: dict[Any, dict[str, float]] = {}
    for day, row in value.items():
        if not isinstance(row, Mapping):
            raise KsGuardError(
                f"the panel row for {day!r} must map symbol to forward "
                f"return, got {type(row).__name__}; a date's cross-section "
                "is a mapping of symbol to value, and a row that is not one "
                "is no cross-section the permutation can read"
            )
        inner: dict[str, float] = {}
        for symbol, element in row.items():
            if not isinstance(symbol, str) or not symbol:
                raise KsGuardError(
                    f"the panel's symbols for {day!r} must be non-empty "
                    f"strings, found {symbol!r} ({type(symbol).__name__})"
                )
            if isinstance(element, bool) or not isinstance(element, (int, float)):
                raise KsGuardError(
                    f"the panel's target for {symbol!r} on {day!r} must be a "
                    f"finite real, found {element!r} ({type(element).__name__})"
                )
            number = float(element)
            if not math.isfinite(number):
                raise KsGuardError(
                    f"the panel's target for {symbol!r} on {day!r} is not "
                    f"finite ({element!r}); a non-finite forward return would "
                    "be served to the caller as a target nobody measured"
                )
            inner[symbol] = number
        captured[day] = inner
    return captured


def _validated_seed(seed: Any) -> int:
    """Refuse a permutation seed that is not a non-negative integer.

    The seed drives the shuffle that feature 115 reproduces a null node's
    series from, so it must be storable as one integer with one meaning.  The
    refusal is the read-side twin of :func:`~nulloracle.assignment.
    _validated_perm_seed`, which refuses the same value at the write — a seed
    that is a ``bool`` (``True`` is not a seed anyone meant to write), a
    negative integer, or not an integer at all is a seed no replay could
    rebuild, and a seed the generator cannot seed with would make the "same
    campaign, same series" promise unenforceable.  Re-raised here as
    :class:`~nulloracle.errors.KsGuardError` rather than borrowed as
    :class:`~nulloracle.errors.SidecarError`: a malformed seed handed to the
    *permutation* is a computation-contract failure, not a sidecar-schema one,
    and a caller reading ``SidecarError`` out of a permutation would look in
    the wrong module for the cause — the same seam discipline that keeps the
    fraction's and the flip depth's stores on the guard's error.
    """
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise KsGuardError(
            f"seed must be a non-negative integer, got {type(seed).__name__} "
            f"({seed!r}); feature 115 reproduces a null node's block "
            "permutation from this stored seed, so a seed that is not a "
            "non-negative integer is a permutation no replay could rebuild"
        )
    return seed


def _validated_block_days(block_days: Any) -> int:
    """Refuse a block length that is not a positive integer.

    The block length is the run the series is cut into before the shuffle, so
    it must be a genuine positive integer: a block length of zero or less cuts
    the series into no blocks, and a block length that is a truthy-looking
    ``True`` (which is ``1``) would cut it into one observation per block and
    so degenerate to a pointwise shuffle — the exact thing block permutation
    exists to avoid, since a pointwise shuffle preserves no autocorrelation.
    The refusal is the read-side twin of
    :func:`~nulloracle.assignment._validated_block_days`, re-raised here as
    :class:`~nulloracle.errors.KsGuardError` for the same seam reason the seed
    refusal is: *the permutation's block length is malformed* is a
    computation-contract failure, not a sidecar-schema one.
    """
    if (
        isinstance(block_days, bool)
        or not isinstance(block_days, int)
        or block_days < 1
    ):
        raise KsGuardError(
            f"block_days must be a positive integer, got "
            f"{type(block_days).__name__} ({block_days!r}); feature 115's "
            "block permutation shuffles contiguous runs of this many days, and "
            "a block length that is not a positive integer cuts the series "
            "into runs it cannot shuffle — a zero-length block permutes "
            "nothing, and a one-day block is a pointwise shuffle that "
            "preserves no autocorrelation at all"
        )
    return block_days


def _validated_series(value: Any) -> list[float]:
    """Refuse a series that is not a non-empty sequence of finite reals.

    The permutation acts on one node's forward returns, so the value it is
    handed must be a genuine series: a non-empty sequence of finite reals.  A
    ``str`` or ``bytes`` is a sequence but not a series (it would shuffle
    characters), so it is refused; an empty input has nothing to permute; and a
    non-finite or non-numeric element would be served to the caller as a
    target nobody measured.  Each element is coerced to ``float`` and checked
    finite, so an integer series is accepted but a ``nan`` or ``inf`` is not.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KsGuardError(
            f"series must be a sequence of forward returns, got "
            f"{type(value).__name__}; feature 115's block permutation shuffles "
            "the blocks of a null node's forward-return series, and a value "
            "that is not a sequence of returns — a string, a mapping, a "
            "generator with no length — is no series a null node could report"
        )
    items: list[float] = []
    for element in value:
        if isinstance(element, bool) or not isinstance(element, (int, float)):
            raise KsGuardError(
                f"series must be finite reals, found {element!r} "
                f"({type(element).__name__}); a forward return is a real "
                "number, and a non-numeric element would be served to the "
                "caller as a target nobody measured"
            )
        number = float(element)
        if not math.isfinite(number):
            raise KsGuardError(
                f"series must be finite reals, found {element!r}; a "
                "non-finite forward return would be served to the caller as a "
                "target nobody measured"
            )
        items.append(number)
    if not items:
        raise KsGuardError(
            "series must be non-empty; feature 115's block permutation shuffles "
            "the blocks of a forward-return series, and an empty series has no "
            "blocks to shuffle and no null node it could be the series of"
        )
    return items


def _validated_positions(value: Any) -> list[Any]:
    """Refuse an ``indices`` input that is not a non-empty sequence.

    The index form of the permutation rearranges positions, so its input must
    be a genuine sequence with a length — a :class:`~collections.abc.Sequence`
    that is not text.  A ``str`` or ``bytes`` is refused (it would shuffle
    characters, not positions); an empty input has no positions to rearrange.
    Unlike :func:`_validated_series`, the members are not checked for being
    finite reals: the index form carries no claim about what is being
    permuted, only that there is something with positions to rearrange.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KsGuardError(
            f"indices must be a sequence of positions, got "
            f"{type(value).__name__}; feature 115's block permutation "
            "rearranges the positions of a series, and a value that is not a "
            "sequence — a string, a mapping, a generator with no length — has "
            "no positions to rearrange"
        )
    items = list(value)
    if not items:
        raise KsGuardError(
            "indices must be non-empty; feature 115's block permutation "
            "rearranges the positions of a series, and an empty sequence has no "
            "positions to rearrange"
        )
    return items


def _seeded_rng(seed: int):
    """A :class:`random.Random` seeded from ``seed`` — the permutation's engine.

    Imported lazily, the way :mod:`nulloracle.flipdepth` defers ``random``, so
    the factory's scan pays nothing for this module at import time.  The
    generator is seeded from the validated ``seed`` — the same ``perm_seed``
    feature 109 stores beside the null bit — so a series permuted from the same
    seed shuffles the same blocks into the same order, which is the whole of
    the permutation's reproducibility and §12's determinism contract.
    """
    import random

    return random.Random(seed)
