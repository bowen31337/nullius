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

**A panel is not one series, and a time shuffle inside one leaks.**
:func:`block_permute_cross_section` applies feature 115 to a null node's
*targets* rather than to a bare series — ``{date: {symbol: forward
return}}`` — and the grain matters, because a signal's lookback and a
null's target live on the same date axis.  Shuffling *within* one symbol's
own series across time (what this function did before this fix) can hand
date d a value the symbol carried on some earlier date inside the signal's
own lookback window — a 20-day momentum score at d already read every price
in ``[d-20, d]``, so a block landing one slot early serves, as d's "forward
return", a number the signal had already seen.  The null then correlates
with the signal not by chance but by literally repeating a value the
signal's own computation used, which is look-ahead read backwards.  The fix
shuffles *within* one date instead: every value served for date d is drawn
from date d's own cross-section, so no value from any other date — inside
the lookback or outside it — can ever reach d.  See
:func:`block_permute_cross_section` for the mechanism (a derangement of
each date's row, held constant across a block's unchanged membership so the
donor's autocorrelation and volatility clustering still carry across, the
way §7.3 asks).

**Stdlib only, and import-cheap.**  ``math``, ``random`` and ``hashlib``
(the latter two deferred to first use, the way :mod:`nulloracle.flipdepth`
defers ``random``), no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays nothing
for this module, the same discipline every store in this member states.  The
module imports :data:`~nulloracle.assignment.DEFAULT_BLOCK_DAYS` rather than
re-spelling the number, so the block length the permutation defaults to and
the block length the sidecar seals are one value.
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
    date*: ``{date: {symbol: forward return}}``. This function is the
    mechanism that turns one such panel into the permuted one a null node
    reports, and it moves values *within* a date, never *across* dates.

    **Why a value may never cross a date.** A null target is served beside
    a request whose ``depth`` names a signal computed from that same
    symbol's own past — a 20-day momentum score at date d, say, is a
    function of prices on ``[d-20, d]``. Earlier revisions of this function
    (and the whole-row swap before it) moved a date's *target* from
    somewhere else in time: a block landing one slot early served, as date
    d's "forward return", a value the signal's own lookback had already
    read on some day inside ``[d-20, d]``. That is look-ahead in reverse —
    the null target correlates with the signal not because either carries
    real information, but because they are, some of the time, literally the
    same number read twice. A 20-day momentum signal scored against such a
    null showed ``|t|>1.96`` on 34% of seeds (bug_spec, this fix). Shuffling
    *within* one date closes that channel completely: the permuted value
    served for date d is always one of date d's own real values, so nothing
    the signal read before d can ever be the number arriving as d's target.

    **The mechanism: a derangement of each date's own row.** For a date
    whose cross-section carries two or more symbols, this function draws a
    *derangement* — a bijection from symbol to symbol with no fixed point —
    and reports, for each symbol, the value the derangement's partner symbol
    carried on that same date. No symbol ever keeps its own value (a
    derangement has none), and every served value is a value that date's own
    row actually carried (the derangement draws only from that row) — so
    the permuted cross-section is neither invented nor zero-filled, and its
    membership is exactly the real row's, which is what lets
    :func:`evaluator.gate_targets`'s support rule accept it. A date with
    fewer than two symbols cannot be deranged (there is no bijection with no
    fixed point on 0 or 1 elements) and passes through unchanged.

    **The block, read as the mapping's own lifetime.** §7.3's claim —
    *"preserving return autocorrelation and volatility clustering"* —
    survives a per-date derangement only if the *same* derangement serves
    every date in one ``block_days``-long run: drawing a fresh, independent
    mapping for every date would hand each symbol a new, unrelated donor
    every day, destroying the donor's own serial structure rather than
    carrying it across. So the derangement is drawn once per contiguous
    block of ``block_days`` dates (the same partition :func:`block_permute`
    cuts a bare series into) and reused for every date in that block whose
    cross-section has the *identical* membership — which means a symbol's
    assigned series, across one block, is literally another symbol's own
    contiguous run of real values, carrying that donor's autocorrelation and
    volatility clustering intact, just under a different label.

    **Where membership changes inside a block.** A listing or delisting
    changes a date's row shape mid-block (feature 72's point-in-time
    admission rule), and the block's mapping, drawn for the block's other
    membership, may not even be a valid bijection on the changed row. So a
    date whose membership differs from what the block's cached mapping was
    drawn for gets its own derangement, drawn for its own membership — still
    deterministically, still from the same ``seed`` and block index, and
    still shared with any other date in the block carrying that same
    (different) membership.

    **Deterministic without being order-dependent.** Each derangement is
    drawn from a generator seeded by hashing ``seed``, the block index and
    the sorted tuple of the membership it is for — never by hashing a
    Python object (whose hash is randomised per process) and never by the
    order dates happen to be walked in. Two dates anywhere in one block that
    share a membership therefore always draw the identical mapping, two
    calls with the same panel, seed and block length always return the
    identical result (§12's determinism contract), and nothing about the
    panel's own dict ordering can perturb either property.

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
    mappings: dict[tuple[int, tuple[str, ...]], tuple[int, ...]] = {}
    permuted: dict[Any, dict[str, float]] = {}
    for position, day in enumerate(days):
        row = rows[day]
        symbols = tuple(sorted(row))
        count = len(symbols)
        if count < 2:
            # Nothing to derange: a bijection with no fixed point does not
            # exist on 0 or 1 elements, so the date's own row is the only
            # answer that is neither invented nor a self-match.
            permuted[day] = dict(row)
            continue
        block_index = position // block
        key = (block_index, symbols)
        mapping = mappings.get(key)
        if mapping is None:
            mapping = _derangement(count, _cross_section_rng(drawn_seed, block_index, symbols))
            mappings[key] = mapping
        permuted[day] = {
            symbols[slot]: row[symbols[source]] for slot, source in enumerate(mapping)
        }
    return permuted


def _cross_section_rng(seed: int, block_index: int, symbols: tuple[str, ...]):
    """A :class:`random.Random` seeded from ``(seed, block_index, symbols)``.

    One cross-sectional derangement is drawn per block per distinct
    membership (:func:`block_permute_cross_section`), and this is the
    generator that draw comes from. The sub-seed is derived with
    :func:`hashlib.sha256` over the three values rather than through
    Python's built-in :func:`hash`, deliberately: ``hash`` of a ``str`` is
    salted per *process* (`PYTHONHASHSEED`), so two campaign replays — or
    two pytest-xdist workers evaluating the same seed — would draw two
    different mappings for what §12 promises is one reproducible
    permutation. A digest of the UTF-8 bytes has no such salt, so the same
    three inputs always hash to the same sub-seed everywhere this runs.
    """
    import hashlib
    import random

    digest = hashlib.sha256(
        f"{seed}:{block_index}:{len(symbols)}:{'|'.join(symbols)}".encode()
    ).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _derangement(count: int, rng: Any) -> tuple[int, ...]:
    """A uniformly random derangement of ``range(count)`` — no index maps to itself.

    Drawn by the standard reject-and-retry construction: shuffle, and keep
    the result only if no position mapped to itself. The probability of
    landing a derangement on one shuffle approaches ``1/e`` as ``count``
    grows, so the expected number of attempts stays near ``e`` (about 2.7)
    for every ``count`` this module is ever called with — ``count`` is a
    panel's cross-section size, not an adversarial input. Called only for
    ``count >= 2``, where a derangement always exists.
    """
    positions = list(range(count))
    while True:
        rng.shuffle(positions)
        if all(positions[i] != i for i in range(count)):
            return tuple(positions)


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
