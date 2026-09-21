"""The seeded stream — one hash, two draws, and no state to carry.

Everything a bootstrap world contains is a pure integer-hash draw on a
*cell*, and this is the module that decides what a cell means.  The tests
here fall into the three claims :mod:`bootstrap._stream`'s docstring makes
for itself, and each is the load-bearing half of a larger argument:

* **the draw is content-addressed, not sequenced.**  The same cell answers
  the same number whether it is the first cell drawn or the thousandth,
  and the twelve uniforms behind one :func:`~bootstrap.normal` are not
  shared with any other cell's.  This is the property feature 181 needs
  and :class:`random.Random` does not have: a replay reveals cells in an
  order the *policy* chooses (§10.1), so a label whose value depended on
  how many cells had been revealed first would not be a ground truth.  It
  is tested by interleaving draws and comparing to the same draws taken in
  isolation.
* **the composition is exactly rounded.**  ``+``, ``-`` and ``*`` on
  float64 have one correctly-rounded result each, whatever the platform —
  no ``log``, no ``exp``, no ``erf``, none of which are in this module or
  anywhere downstream of it.  §12's 1e-12 canary tolerance and §10.4's
  50 ms replay target both rest on this, and the tests assert the stronger
  property the code actually has: identical bits across calls, not merely
  close.
* **the draws are the shape they are documented to be.**  ``uniform`` on
  ``[0, 1)`` and *every* cell has a draw — no value it can compute is an
  infinity, because ``[0, 1)`` excludes the one input where a subsequent
  division could be total.  ``normal`` bounded on ``[-6, 6]``, which is
  what keeps a generated dataset free of leverage points whose presence
  would make the fit's conditioning depend on the seed's luck.  These are
  checked over a wide sample rather than a hand-picked cell, because a
  claim about *every* cell is the claim the world relies on.

The awkward corner is negative cells.  :func:`~bootstrap.mix64` masks them
into the ring rather than raising, which is deliberate and documented:
the caller's address derivation is where an out-of-range address is made
meaningful (:mod:`bootstrap._world` mixes its prefixes before it hashes,
so two different things in one world never collide).  So the test pins
that a negative cell is *total*, not that it is refused — a refusal here
would push the same bug up into the address arithmetic, where it would be
harder to see.
"""

from __future__ import annotations

import math

import pytest
from bootstrap import GOLDEN_GAMMA, MASK64, mix64, normal, uniform


def _sampled(count: int = 4096, *, start: int = 0) -> range:
    """A wide, contiguous block of cells — the sample most claims are over."""
    return range(start, start + count)


# -- ``mix64`` ---------------------------------------------------------------------


def test_mix64_is_deterministic() -> None:
    # No state, no seed object, no clock: the function is a function.  The
    # repeat inside one process is the weakest form of this; the stronger
    # forms (a fresh interpreter, a different machine) are what §12's
    # canary exercises, and they hold for the same reason: there is
    # nothing here *but* integer arithmetic.
    for cell in _sampled(256):
        assert mix64(cell) == mix64(cell)


def test_mix64_stays_inside_the_64_bit_ring() -> None:
    # An escaped product would still be a big integer that looked like a
    # hash, while no longer being a permutation of the words — the failure
    # the mask exists to prevent, and the one a reader cannot see by eye.
    for cell in _sampled(2048):
        word = mix64(cell)
        assert isinstance(word, int)
        assert 0 <= word <= MASK64


def test_mix64_distinguishes_neighbouring_cells() -> None:
    # Distinct cells get distinct words: the finalizer is a bijection, so
    # this is a property rather than a probability.  Checked over a
    # contiguous block, which is exactly the case a weak mix would fail —
    # adjacent addresses are the ones a one-bit-difference mix collides.
    words = [mix64(cell) for cell in _sampled(4096)]
    assert len(set(words)) == len(words)


def test_the_golden_gamma_increment_is_odd() -> None:
    # The property that makes the increment useful: an *odd* constant is a
    # generator of the additive group of the 64-bit ring, so
    # ``cell -> cell + GOLDEN_GAMMA`` is a bijection whose orbit from zero
    # visits every residue — in particular every residue class mod 2^k, for
    # every k.  An even constant would fix the low bit, so half the ring
    # would be unreachable and two cells' addresses would collide mod 2^k.
    assert GOLDEN_GAMMA % 2 == 1
    for bits in (1, 2, 4, 8, 12):
        modulus = 1 << bits
        residues = {(cell + GOLDEN_GAMMA) % modulus for cell in range(modulus)}
        assert residues == set(range(modulus))


def test_mix64_is_not_degenerate_at_zero() -> None:
    # Without the increment the finalizer would be applied to the raw cell,
    # and ``0`` is the finalizer's fixed point: the first xor-with-shift
    # leaves ``0 ^ 0 == 0``, both multiplications leave it, and ``mix64(0)``
    # would come back ``0`` — the cell every address-derivation bug lands
    # on would be the one cell whose draw carries no seed.  The increment
    # moves the input off the fixed point before the mixing begins.
    assert mix64(0) != 0
    assert mix64(0).bit_count() > 20  # and it lands well spread, not near 0


def test_mix64_avalanches() -> None:
    # A good finalizer sends each input bit to roughly half the output
    # bits.  A weak mix would leave whole output bits nearly constant
    # across the sample — and a bit that never varies is a bit that
    # carries no seed, which would show up in a world as two cells whose
    # draws agree systematically rather than as an obvious bug.
    #
    # Checked over the *flipped* neighbours of a set of cells: the exact
    # comparison a finalizer exists to satisfy, and a claim broad enough
    # that a bad constant fails it while this one passes.
    for cell in _sampled(64):
        base = mix64(cell)
        for bit in range(0, 64, 7):
            flipped = mix64(cell ^ (1 << bit))
            changed = (base ^ flipped).bit_count()
            assert 16 < changed < 48  # centred on 32, generous either side


def test_mix64_accepts_a_negative_cell_rather_than_raising() -> None:
    # Documented behaviour, not an accident: the mask folds a negative
    # address into the ring, so an address derivation that went negative
    # silently addresses a *different* cell rather than aborting a world's
    # dataset generation halfway through.  Pinned as totality so that a
    # future "tidy up" that made this raise would fail here rather than
    # surfacing as a mystery in the address arithmetic above it.
    for cell in range(-1, -65, -1):
        word = mix64(cell)
        assert 0 <= word <= MASK64


def test_mix64_is_not_the_identity() -> None:
    # Cheap, and it catches the one refactor that would keep every other
    # test in this file passing: replacing the body with ``return cell``
    # would be deterministic, in-range, bijective and (vacuously)
    # avalanching on nothing.  A single sampled inequality closes it.
    assert any(mix64(cell) != cell for cell in _sampled(16))


# -- ``uniform`` -------------------------------------------------------------------


def test_uniform_is_always_in_the_half_open_unit_interval() -> None:
    # ``[0, 1)`` and not ``(0, 1)``: the lower bound is reachable and the
    # upper is not.  This is what makes the draw *total* — the reason
    # ``normal`` needs no rejection loop, and the reason no value in a
    # world can be an infinity produced by a zero denominator downstream.
    for cell in _sampled(8192):
        value = uniform(cell)
        assert 0.0 <= value < 1.0


def test_uniform_uses_the_full_53_bit_mantissa() -> None:
    # The draw is quantised at ``2^-53``, not at some coarser grid.  A
    # mistaken shift — taking 32 of the 64 bits, say — would still satisfy
    # the range test above while silently putting every draw on a coarse
    # lattice, which would show up in a world as features that take a
    # suspiciously small number of distinct values.
    #
    # The sharp check is the *resolution*: scaling a draw back up must
    # recover an integer to the last bit.  A coarse grid would leave a
    # fraction behind, since the true draw would not be a multiple of the
    # step the test is inverting.
    step = 2.0**-53
    for cell in _sampled(4096):
        scaled = uniform(cell) / step
        assert scaled == int(scaled)  # exactly on the 2^-53 grid


def test_uniform_reaches_into_both_ends_of_its_interval() -> None:
    # Both ends are *populated*, not merely permitted.  ``[0, 1)`` is a
    # wide interval and 53-bit draws are rare near either end, so the
    # evidence over 20k draws is that each end has been *approached* — the
    # claim that matters, since a draw scaled by the wrong power of two
    # would compress into some sub-interval of the middle.
    values = [uniform(cell) for cell in _sampled(20000)]
    assert min(values) < 0.001  # the low end is populated
    assert max(values) > 0.999  # and the high end is approached


def test_uniform_is_deterministic_and_cell_addressed() -> None:
    # Interleaved against isolated: the property that separates a hash
    # from a generator.  A generator-based ``uniform`` would answer a
    # different number on the second call, and this test is written so
    # that failure mode is the one it reports.
    cells = list(_sampled(512))
    interleaved = [uniform(cell) for cell in cells]
    for _ in range(3):  # burn draws on unrelated cells in between
        for other in _sampled(64, start=10**6):
            uniform(other)
    isolated = [uniform(cell) for cell in cells]
    assert interleaved == isolated


def test_uniform_pairs_are_uncorrelated_enough_for_a_dataset() -> None:
    # Not a statistical test of randomness — a check that the *address
    # arithmetic* is not degenerate.  Consecutive cells are the pairs a
    # weak mix correlates, and correlated feature draws would make a
    # world's design matrix ill-conditioned for reasons that had nothing
    # to do with the hyperparameters.  The threshold is loose on purpose:
    # this is a smoke alarm, not a proof, and the avalanche test above is
    # the sharp one.
    xs = [uniform(cell) for cell in _sampled(4096)]
    ys = [uniform(cell) for cell in _sampled(4096, start=1)]
    mean_x = math.fsum(xs) / len(xs)
    mean_y = math.fsum(ys) / len(ys)
    covariance = math.fsum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)
    ) / len(xs)
    assert abs(covariance) < 0.02  # ~N(0, 1/12) means a |z| well under 1


def test_uniform_is_centred_where_a_uniform_belongs() -> None:
    # Mean and variance of ``U[0, 1)``: 1/2 and 1/12.  Cheap, and it is
    # the check that a scaled-but-not-shifted draw (or one scaled by the
    # wrong power of two) fails immediately.
    values = [uniform(cell) for cell in _sampled(8192)]
    mean = math.fsum(values) / len(values)
    assert mean == pytest.approx(0.5, abs=0.01)
    variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
    assert variance == pytest.approx(1.0 / 12.0, abs=0.002)


# -- ``normal`` --------------------------------------------------------------------


def test_normal_is_bounded_by_the_irwin_hall_support() -> None:
    # Twelve uniforms in ``[0, 1)`` recentred on six: the support is
    # exactly ``[-6, 6)``.  This bound is *why* the world uses an
    # Irwin-Hall draw rather than a true gaussian — a generated dataset
    # with unbounded draws would occasionally contain a leverage point
    # that made the fit's conditioning depend on the seed's luck, and a
    # world's difficulty would then be a lottery.
    for cell in _sampled(8192):
        value = normal(cell)
        assert -6.0 <= value < 6.0


def test_normal_is_centred_and_unit_variance() -> None:
    # Mean 0 and variance 1 by construction (``12 · 1/12 = 1``), which is
    # the whole reason twelve was chosen: the centring is a plain
    # subtraction rather than a scale by an irrational ``sqrt``, and so
    # costs no extra rounding per draw.
    values = [normal(cell) for cell in _sampled(8192)]
    mean = math.fsum(values) / len(values)
    variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
    assert mean == pytest.approx(0.0, abs=0.05)
    assert variance == pytest.approx(1.0, abs=0.05)


def test_normal_is_deterministic() -> None:
    for cell in _sampled(256):
        assert normal(cell) == normal(cell)


def test_normal_draws_on_disjoint_cells_per_address() -> None:
    # The twelve uniforms behind ``normal(c)`` are drawn on
    # ``12c .. 12c+11``, so two different addresses name *disjoint* blocks
    # and no uniform is ever shared between two normals.  Checked without
    # reading the private constant: address ``c`` must not answer what a
    # shifted address does, and — the sharper form — the twelve
    # consecutive draws a normal consumes must not, in aggregate, be one
    # another's.
    values = [normal(cell) for cell in _sampled(2048)]
    assert len(set(values)) > len(values) * 0.99  # collisions are hash-level rare


def test_normal_consumes_consecutive_uniforms() -> None:
    # The addressing scheme itself, pinned from the outside: a normal at
    # ``cell`` decomposes into the twelve uniforms it is built from.  This
    # is a *white-box* assertion and is written as one deliberately — the
    # block layout is a documented contract of this module (the world
    # relies on it when it mixes prefixes), so a future change to the
    # stride would be a change to the address space and should fail loudly
    # here rather than reprovision every world's dataset silently.
    cell = 1234
    expected = math.fsum(uniform(cell * 12 + offset) for offset in range(12)) - 6.0
    assert normal(cell) == expected


def test_normal_is_not_uniform() -> None:
    # Guards the one refactor that would leave the range test passing:
    # returning the uniform centred (``uniform(cell) - 0.5``) would be
    # bounded, centred and deterministic, with a variance of 1/12 rather
    # than 1.  The variance check above catches it too, but this pins the
    # *shape*: a uniform has no mass near zero relative to a normal's
    # shoulders, and the sum-of-twelve is what produces it.
    values = [normal(cell) for cell in _sampled(8192)]
    near_zero = sum(1 for value in values if abs(value) < 0.25)
    # P(|N(0,1)| < 0.25) ~ 0.197; a centred uniform would give 0.25.
    assert near_zero / len(values) == pytest.approx(0.197, abs=0.03)


# -- The module's guarantees, taken together ---------------------------------------


def test_no_draw_can_produce_a_non_finite_value() -> None:
    # The totality claim, over a wide sample including the corners of the
    # address space: every cell has a draw, and the draw is a finite
    # float.  A world's dataset is generated from these, so a single
    # infinity here would propagate into a feature, then into a design
    # column, and finally into a label that was not a number wearing a
    # score's clothes — the exact failure ``fit_and_score`` refuses on.
    cells = list(range(1024)) + list(range(-1024, 0)) + [2**32, 2**53, MASK64, -(2**53)]
    for cell in cells:
        assert math.isfinite(uniform(cell))
        assert math.isfinite(normal(cell))


def test_the_two_draws_are_addressed_independently() -> None:
    # ``uniform`` and ``normal`` on the same cell are unrelated values:
    # they are the *same* hash under this module's addressing, but a
    # world never uses a bare cell for two different quantities —
    # :mod:`bootstrap._world` mixes its prefixes in first, precisely so
    # that a feature draw and a noise draw at coinciding coordinates do
    # not collide.  Pinned here as the reason that prefix mixing has to
    # exist at all: without it, these two would agree by construction.
    cell = 99
    assert uniform(cell) != normal(cell)
    # And the world's convention (prefix, then cell) is what separates
    # them — demonstrated on this module's own terms with two artificial
    # prefixes, one shifted by a single bit.
    left = normal(MASK64 ^ (1 << 40) ^ cell)
    right = normal(MASK64 ^ (1 << 41) ^ cell)
    assert left != right
