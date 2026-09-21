"""The world's seeded stream — one integer hash, and the two draws on it.

Every number a bootstrap world contains is a pure function of one world
seed and one *cell* — an integer address derived from the world's id and
the coordinates of the thing being drawn.  There is no generator object,
no stream state, and no draw order: the value at a cell is computable
without having computed any other cell, which is the whole reason a world
can be *generated* rather than found and shipped.

**Why a content-addressed hash and not :class:`random.Random`.**  The
member's sibling for this job is
:mod:`nulloracle.blockpermute`, which is right to use
``random.Random(seed)``: a block permutation is a *sequence* of draws on a
series, so a stream is the natural shape and the seed is the whole of its
reproducibility.  A world's dataset is the opposite shape — it is indexed,
not sequenced.  Feature 181's world must answer a score for *one node*
without having computed the nodes before it, because a replay reveals
cells in an order the policy chooses (docs/nullius-tech-architecture.md
§10.1), and a stream-based generator would make a label depend on how many
cells the policy happened to reveal first.  That dependence is exactly the
"the same node scores differently depending on the path a policy took to
reach it" property §9.2 *permits* for financial worlds and which a
bootstrap world, whose labels are ground truth, must not have: if the
label moved with the path, it would not be a ground truth.

So the draw is a hash.  :func:`mix64` is the SplitMix64 finalizer — the
mixed-increment construction the JDK's ``SplittableRandom`` and
``java.util.Random``'s stream use, and a standard choice for exactly this
job: a 64-bit avalanche over an integer address, cheap, stdlib-pure, and
with no state to carry.  :func:`uniform` takes the top 53 bits into
``[0, 1)``, the widest interval a float64 holds exactly; :func:`normal`
sums twelve of them and recentres, the Irwin-Hall construction, so a
"gaussian" draw here is a pure ``+``, ``-`` and ``*`` composition of
uniforms with no ``log``, no ``sqrt`` and no rejection loop.

**The composition is the determinism argument.**  §12's determinism
contract and §10.4's 50 ms replay target both live on the same two facts:
the arithmetic must be a fixed sequence of exactly-rounded operations, and
it must not depend on a batch shape.  A composition of ``+``, ``-``, ``*``
on float64 is exactly rounded — each one operation has one correctly
rounded result, whatever the platform — so two runs of one world answer
bit-identical labels, and the nightly canary's 1e-12 tolerance is met by
construction rather than by luck.  ``log``, ``exp`` and ``erf`` are in
neither the world's dataset nor its score for the same reason: they are
libm calls whose last bit is platform-dependent, and a ground-truth label
that moved with the C library would be a ground truth about the machine.
Everything downstream of this module inherits the guarantee: the dataset,
the fit, and the score are one closed arithmetic over :func:`mix64`'s
integers.

**The seed-isolation guarantee.**  A generator object carries its position
in itself, so two independent draws asking the same object return
different numbers.  A hash carries nothing, so two independent draws
asking the same *cell* return the same number — which is what makes the
world's parameters, dataset and targets independently addressable.  The
member's other guarantee is the mirror image and is enforced in
:mod:`bootstrap._world`: the *addresses* are mixed before they are hashed,
so two different things in the same world — a parameter and an
observation, a row and a target — never collide onto one value even when
their coordinates coincide.
"""

from __future__ import annotations

__all__ = [
    "GOLDEN_GAMMA",
    "MASK64",
    "mix64",
    "normal",
    "uniform",
]

#: The 64-bit width every value in :func:`mix64` is held to.  Spelled once
#: so the multiplicative constants below cannot drift out of the ring they
#: are defined over — a product that escaped the mask would still be an
#: integer, and would still look like a hash, while quietly ceasing to be
#: a permutation of the 64-bit words.
MASK64 = (1 << 64) - 1

#: ``floor(2^64 / φ)``, the odd golden-ratio increment SplitMix uses to
#: break the symmetry between neighbouring addresses.  Two addresses that
#: differ by one would otherwise mix through the same multipliers with a
#: one-bit difference; the increment is what turns "adjacent" into
#: "uncorrelated" before the finalizer runs.
GOLDEN_GAMMA = 0x9E3779B97F4A7C15

#: The finalizer's two multipliers (Stafford variant 13, the SplitMix64
#: constants).  Both are odd, so the multiplication is a bijection on the
#: 64-bit words and two distinct mixed addresses can never land on one
#: value — the property :func:`mix64` is relied on for.
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB

#: ``2^-53``: the scale taking the top 53 bits of a mixed word into
#: ``[0, 1)``.  A float64 has 53 bits of mantissa, so this is the widest
#: interval on which ``uniform`` is *exact* — every representable value in
#: ``[0, 1)`` with a 53-bit denominator is hit, and no rounding enters the
#: conversion.
_TWO_POW_NEG_53 = 2.0**-53

#: How many uniforms :func:`normal` sums.  Twelve is the smallest count
#: whose sum of uniforms has an integer variance — ``12 · (1/12) = 1`` —
#: so the centring below is a plain subtraction of 6 rather than a scale
#: by an irrational ``sqrt``.  A scale factor would be one more rounding
#: per draw for no gain: the world's truncation is exact either way, and
#: the parameter grid's conditioning is what the *count of features* and
#: the ridge floor control.
_IRWIN_HALL_DRAWS = 12


def mix64(cell: int) -> int:
    """Mix one integer cell into a well-distributed unsigned 64-bit word.

    The SplitMix64 finalizer: add the golden-gamma increment, then two
    rounds of ``x ^= x >> shift; x *= odd-constant``.  The result is a
    bijection on the 64-bit words, so distinct cells get distinct mixed
    words, and neighbouring cells get uncorrelated ones.

    Pure integer arithmetic, stdlib only, no state: the same cell answers
    the same word in any process, on any machine, in any order.  Negative
    cells are accepted and folded into the ring by the mask, so an address
    arithmetic that went below zero quietly addresses a different cell
    rather than raising — the caller's address derivation is where that is
    made meaningful (:mod:`bootstrap._world` mixes before it hashes).
    """
    state = (cell + GOLDEN_GAMMA) & MASK64
    state = ((state ^ (state >> 30)) * _MIX_A) & MASK64
    state = ((state ^ (state >> 27)) * _MIX_B) & MASK64
    return state ^ (state >> 31)


def uniform(cell: int) -> float:
    """A reproducible draw on ``[0, 1)``, addressed by ``cell``.

    The top 53 bits of :func:`mix64`, scaled exactly.  ``[0, 1)`` rather
    than ``(0, 1)`` is deliberate and is what makes :func:`normal`
    — and therefore every value in a world — total: every cell has a
    draw, no cell can produce an infinity, and no rejection loop is needed
    to re-draw one that could.
    """
    return (mix64(cell) >> 11) * _TWO_POW_NEG_53


def normal(cell: int) -> float:
    """A reproducible, centred, unit-variance draw, addressed by ``cell``.

    The Irwin-Hall sum of :data:`_IRWIN_HALL_DRAWS` uniforms drawn on the
    *consecutive* cells ``12·cell + k``, recentred on zero.  Mean 0,
    variance 1, support ``[-6, 6]`` — bounded, which the world's feature
    scaling turns into a bounded feature range, and which is the reason a
    generated dataset cannot contain a wild leverage point that would make
    the fit's conditioning depend on the seed's luck.

    The consecutive-cell addressing is what keeps the draws independent of
    each other *and* of every other draw in the world: two different
    ``cell`` values name disjoint blocks of the underlying hash, so the
    twelve uniforms behind one normal are never shared with another, and
    the sub-addresses are mixed by :func:`mix64` exactly like the top-level
    ones.  Not a true gaussian — an Irwin-Hall draw has no tails — and
    deliberately so: a true gaussian needs an inverse-erf or a rejection
    loop, both of which are either platform-dependent in their last bit or
    order-dependent, and neither property is acceptable in a label the
    pool's calibration rests on (see this module's docstring).
    """
    total = 0.0
    base = cell * _IRWIN_HALL_DRAWS
    for offset in range(_IRWIN_HALL_DRAWS):
        total += uniform(base + offset)
    return total - (_IRWIN_HALL_DRAWS / 2.0)
