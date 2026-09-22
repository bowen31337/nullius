"""Feature 227, the threshold schedule — every threshold routed through one mapping.

The invariants these tests pin are the ones the "single mapping, derived from
beta" guarantee depends on:

* **it returns *all* thresholds, as one mapping** — :func:`schedule` returns a
  single mapping carrying exactly :data:`SCHEDULE_KEYS` on every call, never a
  subset; a schedule that forgot a threshold would be a threshold reached by no
  path, so the tests assert the whole set is always present;
* **there is no other way to a threshold** — :func:`schedule` is the only
  derivation point, so the mapping is the single source of truth and "every
  threshold moves together" is a fact about the code; the tests pin that the
  four named thresholds are always the same four keys;
* **it is a pure function of beta, and nothing else** — the same scalar returns
  the identical mapping however it is asked, so two cycles opened at one scalar
  explore under identical thresholds, which is the cross-cycle legibility the
  single-scalar discipline exists to protect;
* **the thresholds move together, but not identically** — explore/exploit and
  patience rise with beta, pruning aggressiveness and overfit aversion fall;
  each at its own steepness, so a sweep over beta moves the four in concert
  without collapsing them into one;
* **the returned mapping is frozen** — a threshold is a recorded fact a caller
  holds and compares, and a caller cannot reassign one; the mapping is read-only
  and a fresh dict per call, so two calls never alias and neither can move a
  threshold;
* **a finite scalar always derives finite thresholds** — the numerically stable
  sigmoid saturates rather than overflowing, so a beta of ``1e9`` (a legitimate
  grid point, since feature 226 imposes no band) derives finite thresholds.

The headline case is the feature's own sentence: every threshold is routed
through one mapping derived from beta, and that mapping is the only way to a
threshold.
"""

from __future__ import annotations

import math
from types import MappingProxyType

import pytest
from policy_runtime import (
    EXPLORE_EXPLOIT,
    OVERFIT_AVERSION,
    PATIENCE,
    PRUNE_AGGRESSIVENESS,
    SCHEDULE_KEYS,
    schedule,
)

# ---------------------------------------------------------------------------
# One mapping, carrying all thresholds
# ---------------------------------------------------------------------------


def test_schedule_returns_a_single_mapping_of_all_thresholds() -> None:
    # The feature's verb: every threshold is routed through one mapping, and that
    # mapping carries all of them.  Never a subset — a schedule that forgot a
    # threshold would be a threshold reached by no path.
    thresholds = schedule(0.7)
    assert set(thresholds) == set(SCHEDULE_KEYS)
    assert len(thresholds) == len(SCHEDULE_KEYS)
    for key in SCHEDULE_KEYS:
        assert key in thresholds


def test_schedule_always_carries_the_four_named_thresholds() -> None:
    # The four the paper names (docs §7.4), always present and always the same
    # four keys, whatever the scalar is — so "all thresholds" has exactly one
    # spelling and a caller cannot be surprised by a missing one.
    thresholds = schedule(0.0)
    assert set(thresholds) == {
        EXPLORE_EXPLOIT,
        PATIENCE,
        PRUNE_AGGRESSIVENESS,
        OVERFIT_AVERSION,
    }


def test_schedule_returns_the_mapping_itself_not_a_wrapper() -> None:
    # A read-only mapping, so a caller that holds it holds the thresholds as they
    # were derived.  It is a MappingProxyType over a fresh dict — the value-type
    # stance feature 226 takes on the scalar, restated for the thresholds.
    thresholds = schedule(0.7)
    assert isinstance(thresholds, MappingProxyType)


# ---------------------------------------------------------------------------
# A pure function of beta, and nothing else
# ---------------------------------------------------------------------------


def test_the_same_beta_returns_the_identical_mapping() -> None:
    # The schedule is a pure function of beta: the same scalar returns the
    # identical mapping however it is asked, so a caller reading it twice sees
    # the same thresholds, and two cycles opened at one scalar are comparable.
    first = schedule(0.7)
    second = schedule(0.7)
    assert first == second
    assert first is not second  # a fresh mapping per call — the two never alias


def test_schedule_is_deterministic_across_many_calls() -> None:
    # Not just twice: a pure function of beta answers identically every time, so
    # no call order, no caching, no ambient state can make one reading differ.
    readings = [schedule(0.35) for _ in range(50)]
    for reading in readings[1:]:
        assert reading == readings[0]


def test_two_cycles_opened_at_one_scalar_explore_under_identical_thresholds() -> None:
    # The cross-cycle legibility §609 says the single-scalar discipline exists to
    # protect: two episodes opened at the same beta derive the same thresholds,
    # so a score earned under one is scored under the same bar as the other.
    cycle_a = schedule(0.6)
    cycle_b = schedule(0.6)
    assert cycle_a[EXPLORE_EXPLOIT] == cycle_b[EXPLORE_EXPLOIT]
    assert cycle_a[PATIENCE] == cycle_b[PATIENCE]
    assert cycle_a[PRUNE_AGGRESSIVENESS] == cycle_b[PRUNE_AGGRESSIVENESS]
    assert cycle_a[OVERFIT_AVERSION] == cycle_b[OVERFIT_AVERSION]


# ---------------------------------------------------------------------------
# The thresholds move together, but not identically
# ---------------------------------------------------------------------------


def test_explore_exploit_rises_with_beta() -> None:
    # A higher scalar devotes more of the search budget to exploration — the
    # paper's explore/exploit knob.  Strictly monotonic, so a sweep over beta
    # moves it.
    low = schedule(0.2)[EXPLORE_EXPLOIT]
    high = schedule(1.8)[EXPLORE_EXPLOIT]
    assert high > low


def test_patience_rises_with_beta() -> None:
    # A higher scalar grants a branch more refinement steps before it must show
    # out-of-sample progress.  Strictly monotonic, so a sweep over beta moves it.
    low = schedule(0.2)[PATIENCE]
    high = schedule(1.8)[PATIENCE]
    assert high > low


def test_prune_aggressiveness_falls_with_beta() -> None:
    # A higher scalar prunes less readily — it tolerates a longer branch before
    # demanding confirmation (docs §7.4).  Strictly monotonic the other way.
    low = schedule(0.2)[PRUNE_AGGRESSIVENESS]
    high = schedule(1.8)[PRUNE_AGGRESSIVENESS]
    assert high < low


def test_overfit_aversion_falls_with_beta() -> None:
    # A higher scalar is slower to demand confirmation of the §4.5 signature —
    # high beta tolerates longer branches before demanding out-of-sample
    # confirmation (docs §7.4).  Strictly monotonic the other way.
    low = schedule(0.2)[OVERFIT_AVERSION]
    high = schedule(1.8)[OVERFIT_AVERSION]
    assert high < low


def test_the_falling_thresholds_are_two_curves_not_one() -> None:
    # Pruning and overfit aversion both fall with beta, but at different
    # steepness — pruning sharply, overfit aversion gently — so a sweep over beta
    # discriminates them rather than collapsing them into one.  They move
    # together (both are functions of beta) but not identically.
    low = schedule(0.2)
    high = schedule(1.8)
    prune_ratio = high[PRUNE_AGGRESSIVENESS] / low[PRUNE_AGGRESSIVENESS]
    overfit_ratio = high[OVERFIT_AVERSION] / low[OVERFIT_AVERSION]
    assert prune_ratio != pytest.approx(overfit_ratio)


def test_every_threshold_moves_when_beta_changes() -> None:
    # "So every threshold moves together" — the whole mapping shifts with beta,
    # none left fixed.  A schedule that left one threshold constant would be a
    # threshold not routed through beta.
    low = schedule(0.1)
    high = schedule(2.0)
    assert low[EXPLORE_EXPLOIT] != high[EXPLORE_EXPLOIT]
    assert low[PATIENCE] != high[PATIENCE]
    assert low[PRUNE_AGGRESSIVENESS] != high[PRUNE_AGGRESSIVENESS]
    assert low[OVERFIT_AVERSION] != high[OVERFIT_AVERSION]


# ---------------------------------------------------------------------------
# The thresholds are bounded and finite
# ---------------------------------------------------------------------------


def test_explore_exploit_is_a_fraction() -> None:
    # A fraction in (0, 1): it is the explore/exploit split of the search budget,
    # never all and never none.
    for beta in (0.0, 0.5, 1.0, 5.0):
        value = schedule(beta)[EXPLORE_EXPLOIT]
        assert 0.0 < value < 1.0


def test_patience_is_within_its_band() -> None:
    # A refinement budget in (1, 10): at least one step (explore-only is not the
    # default) and at most ten.  The band is the sweep's, but the mapping is
    # always within it.
    for beta in (0.0, 0.5, 1.0, 5.0):
        value = schedule(beta)[PATIENCE]
        assert 1.0 < value < 10.0


def test_prune_aggressiveness_is_a_fraction() -> None:
    # A fraction in (0, 1): how readily a branch is pruned, never all and never
    # none.
    for beta in (0.0, 0.5, 1.0, 5.0):
        value = schedule(beta)[PRUNE_AGGRESSIVENESS]
        assert 0.0 < value < 1.0


def test_overfit_aversion_is_a_fraction() -> None:
    # A fraction in (0, 1): how strongly the §4.5 signature must be confirmed,
    # never all and never none.
    for beta in (0.0, 0.5, 1.0, 5.0):
        value = schedule(beta)[OVERFIT_AVERSION]
        assert 0.0 < value < 1.0


# ---------------------------------------------------------------------------
# A finite scalar always derives finite thresholds
# ---------------------------------------------------------------------------


def test_a_large_beta_saturates_the_sigmoid_instead_of_overflowing() -> None:
    # A beta of 1e9 is a legitimate grid point — feature 226 imposes no band, and
    # the naive 1 / (1 + exp(-z)) would overflow on it.  The stable form
    # saturates to 0 or 1 instead, so a finite scalar always derives finite
    # thresholds.
    thresholds = schedule(1e9)
    for value in thresholds.values():
        assert math.isfinite(value)
    assert thresholds[EXPLORE_EXPLOIT] == pytest.approx(1.0)
    assert thresholds[PATIENCE] == pytest.approx(10.0)
    assert thresholds[PRUNE_AGGRESSIVENESS] == pytest.approx(0.0)
    assert thresholds[OVERFIT_AVERSION] == pytest.approx(0.0)


def test_a_large_negative_beta_saturates_the_other_way() -> None:
    # The same guarantee from the other side: a large negative scalar saturates
    # explore/exploit to 0 and patience to its floor, and the falling thresholds
    # to 1, all finite.
    thresholds = schedule(-1e9)
    for value in thresholds.values():
        assert math.isfinite(value)
    assert thresholds[EXPLORE_EXPLOIT] == pytest.approx(0.0)
    assert thresholds[PATIENCE] == pytest.approx(1.0)
    assert thresholds[PRUNE_AGGRESSIVENESS] == pytest.approx(1.0)
    assert thresholds[OVERFIT_AVERSION] == pytest.approx(1.0)


def test_the_stable_sigmoid_never_raises_on_a_finite_scalar() -> None:
    # A finite scalar, however large, derives finite thresholds — the arithmetic
    # is honest for the whole of 226's un-banded domain.
    for beta in (1e9, -1e9, 1e308, -1e308):
        thresholds = schedule(beta)
        assert all(math.isfinite(value) for value in thresholds.values())


# ---------------------------------------------------------------------------
# The returned mapping is frozen
# ---------------------------------------------------------------------------


def test_a_threshold_cannot_be_reassigned() -> None:
    # A threshold is a recorded fact, and a caller that holds the mapping must not
    # be able to move one.  The mapping is read-only, so an assignment raises.
    thresholds = schedule(0.7)
    with pytest.raises(TypeError):
        thresholds[EXPLORE_EXPLOIT] = 0.9


def test_a_threshold_cannot_be_deleted() -> None:
    # The same guarantee from the other side: a threshold cannot be removed from
    # the mapping a caller holds.
    thresholds = schedule(0.7)
    with pytest.raises(TypeError):
        del thresholds[PATIENCE]


def test_two_calls_never_alias() -> None:
    # A fresh dict per call, never a shared one — mutating one reading (if it
    # could be mutated) would not move the other.  The mapping is a value, not a
    # shared buffer.
    first = schedule(0.7)
    second = schedule(0.7)
    assert first is not second


# ---------------------------------------------------------------------------
# The scalar reaches here already validated
# ---------------------------------------------------------------------------


def test_schedule_reads_the_scalar_as_the_float_it_is() -> None:
    # The scalar reaches the schedule already validated by read_beta (feature
    # 226), so the schedule is pure arithmetic over it: it reads beta as the
    # float it is, and an integer grid point (beta = 1) derives the same mapping
    # its 1.0 spelling does.
    assert schedule(1) == schedule(1.0)


def test_schedule_accepts_a_zero_scalar() -> None:
    # A beta of 0.0 is a legitimate grid point (226 imposes no band), and the
    # schedule derives finite thresholds from it — the symmetric point where the
    # sigmoid is 0.5.
    thresholds = schedule(0.0)
    assert thresholds[EXPLORE_EXPLOIT] == pytest.approx(0.5)
    assert thresholds[PATIENCE] == pytest.approx(5.5)
    assert thresholds[PRUNE_AGGRESSIVENESS] == pytest.approx(0.5)
    assert thresholds[OVERFIT_AVERSION] == pytest.approx(0.5)


def test_schedule_accepts_a_negative_scalar() -> None:
    # A negative beta is a legitimate grid point too, and the schedule derives
    # finite thresholds from it — explore/exploit below 0.5, patience below its
    # midpoint, the falling thresholds above 0.5.
    thresholds = schedule(-0.5)
    assert thresholds[EXPLORE_EXPLOIT] < 0.5
    assert thresholds[PATIENCE] < 5.5
    assert thresholds[PRUNE_AGGRESSIVENESS] > 0.5
    assert thresholds[OVERFIT_AVERSION] > 0.5
