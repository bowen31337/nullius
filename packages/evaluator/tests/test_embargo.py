"""Feature 78 — embargoing the lookback length after every split boundary.

app_spec.xml feature 78: *"System embargoes the lookback length after every
split boundary, which rejects a fold configuration whose embargo is 0
periods."* docs/nullius-tech-architecture.md §6.1 names the step — ``6.
purge_and_embargo  purge H, embargo L around every CV split`` — and §C2 of
the PRD states the rule: *"Apply purged k-fold with embargo — purge ``H``
(holding period), embargo ``L`` (lookback) around every split."*

This suite tests the embargo check — the *refusal* half of the feature
sentence — separately from the purge it pairs with (``test_purge.py``,
whose module docstring explains why the purge is checked against dates and
the embargo against the configuration: within the one-split fold the purge
check certifies, training is already strictly before the split, so the
embargo's promise is the thing left to certify). The tests assert:

* **the rule** — the configuration is embargoed exactly when the embargo
  covers the lookback (``embargo ≥ lookback``), an embargo wider than the
  lookback included, because caution on top of the leak line is not a
  leak;
* **the 0-periods refusal** — a fold configuration whose embargo is 0
  periods is rejected, the feature's own named refusal, as is a negative;
* **the short refusal** — an embargo short of the lookback is refused,
  naming how many periods it falls short;
* **the input contract** — a non-integer embargo or lookback (a float, a
  bool) and a non-positive lookback are refused by name;
* **the record** — the verdict carries the configuration and the
  shortfall, is a hashable value, and a hand-built one must cohere with
  the configuration it claims to describe.

The embargo and the lookback are plain bar counts, so these tests assert
the check — the covering rule, the shortfall, the refusals — without a
grid, an execution, a sandbox or a window.
"""

from __future__ import annotations

import pytest

from evaluator import (
    DEFAULT_CONFIG,
    EvaluatorEmbargoError,
    EmbargoCheck,
    check_fold_embargoed,
)

# -- the rule ------------------------------------------------------------------


def test_an_embargo_of_exactly_the_lookback_passes() -> None:
    # The feature's first clause: the system embargoes the lookback length
    # after every split boundary.  An embargo of exactly the lookback is
    # that clause made a configuration — the first training bar after the
    # embargo reaches exactly the boundary, no further — so it passes, and
    # the verdict records the configuration with a zero shortfall.
    check = check_fold_embargoed(embargo=6, lookback=6)
    assert isinstance(check, EmbargoCheck)
    assert check.embargo == 6
    assert check.lookback == 6
    assert check.shortfall == 0


def test_an_embargo_wider_than_the_lookback_passes() -> None:
    # The leak line is a floor, not a target: an embargo wider than the
    # lookback keeps the first training bar's window clear with room to
    # spare, and refusing it would refuse caution.  The shortfall is zero,
    # because the check asks only whether the lookback is covered, not how
    # much more than it is embargoed.
    check = check_fold_embargoed(embargo=10, lookback=6)
    assert check.shortfall == 0


def test_the_default_configuration_covers_a_twenty_bar_lookback() -> None:
    # The shipped default (``embargo_periods: 20``) is a configuration the
    # check certifies for a lookback of its own size — the default fold
    # configuration and the check agree on what a period of embargo is
    # for.
    check = check_fold_embargoed(DEFAULT_CONFIG["embargo_periods"], lookback=20)
    assert check.shortfall == 0


def test_the_boundary_is_exactly_the_lookback() -> None:
    # "Covers the lookback" is inclusive of the boundary: an embargo equal
    # to the lookback passes, and one period less fails — the first
    # training bar after the embargo would reach one bar across the
    # boundary into the test half.
    assert check_fold_embargoed(embargo=5, lookback=5).shortfall == 0
    with pytest.raises(EvaluatorEmbargoError):
        check_fold_embargoed(embargo=4, lookback=5)


# -- the 0-periods refusal -----------------------------------------------------


def test_an_embargo_of_zero_periods_is_refused() -> None:
    # The feature's own named refusal: a fold configuration whose embargo
    # is 0 periods is a driver that resumes training on the bar after
    # every split boundary, and that bar's window is built from test-half
    # bars.  The refusal names the zero and says what it means.
    with pytest.raises(EvaluatorEmbargoError, match="0 periods"):
        check_fold_embargoed(embargo=0, lookback=5)


def test_a_negative_embargo_is_refused() -> None:
    # A negative embargo is a zero embargo with a sign error — training
    # would resume *inside* the test half — refused by the same rule, at
    # least one grid period.
    with pytest.raises(EvaluatorEmbargoError, match="at least one grid period"):
        check_fold_embargoed(embargo=-3, lookback=5)


# -- the short refusal ---------------------------------------------------------


def test_one_period_short_is_refused_and_names_the_shortfall() -> None:
    # The embargo is 4 periods, the lookback is 6 bars: the first training
    # bar after the embargo reaches two bars past the boundary into the
    # test half, so the refusal says two periods.  The singular is spelled
    # for a shortfall of one.
    with pytest.raises(EvaluatorEmbargoError, match="2 periods"):
        check_fold_embargoed(embargo=4, lookback=6)
    with pytest.raises(EvaluatorEmbargoError, match="1 period"):
        check_fold_embargoed(embargo=4, lookback=5)


def test_an_unembargoed_configuration_is_refused_naming_the_lookback() -> None:
    # The refusal states both terms of the comparison it failed — the
    # embargo the configuration promised and the lookback it had to cover
    # — so the caller knows which one to move: raise the embargo to the
    # lookback length, or shorten the lookback.
    with pytest.raises(EvaluatorEmbargoError, match="the lookback is 7 bars"):
        check_fold_embargoed(embargo=5, lookback=7)


# -- the input contract --------------------------------------------------------


def test_the_embargo_must_be_a_positive_integer() -> None:
    # The embargo is a count of grid periods — a float and a bool are each
    # refused by name; a bool especially, because ``True`` is an ``int`` to
    # Python and one period of embargo to nobody.
    with pytest.raises(EvaluatorEmbargoError, match="positive integer"):
        check_fold_embargoed(embargo=6.0, lookback=6)
    with pytest.raises(EvaluatorEmbargoError, match="positive integer"):
        check_fold_embargoed(embargo=True, lookback=6)


def test_the_lookback_must_be_a_positive_integer() -> None:
    # The lookback is a count of grid bars — zero is no lookback at all (a
    # window with nothing in it), a negative is a sign error, and a float
    # and a bool are refused by name like the embargo's own non-integers.
    with pytest.raises(EvaluatorEmbargoError, match="at least one grid bar"):
        check_fold_embargoed(embargo=6, lookback=0)
    with pytest.raises(EvaluatorEmbargoError, match="at least one grid bar"):
        check_fold_embargoed(embargo=6, lookback=-1)
    with pytest.raises(EvaluatorEmbargoError, match="positive integer"):
        check_fold_embargoed(embargo=6, lookback=6.0)
    with pytest.raises(EvaluatorEmbargoError, match="positive integer"):
        check_fold_embargoed(embargo=6, lookback=True)


# -- the record ----------------------------------------------------------------


def test_the_record_carries_the_configuration_and_the_verdict() -> None:
    # The verdict is a value beside the configuration it describes: the
    # embargo, the lookback, and the shortfall (zero on a returned record
    # — an un-embargoed configuration is raised, not returned).
    check = check_fold_embargoed(embargo=8, lookback=6)
    assert check.embargo == 8
    assert check.lookback == 6
    assert check.shortfall == 0


def test_the_record_is_a_hashable_value() -> None:
    # A check can be carried beside the fold configuration, filed in a
    # report, or compared across configurations without recomputing — so
    # it is a frozen, hashable value, and two checks of the same
    # configuration are interchangeable as dict keys.
    a = check_fold_embargoed(embargo=6, lookback=6)
    b = check_fold_embargoed(embargo=6, lookback=6)
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_a_hand_built_record_must_describe_its_configuration() -> None:
    # The shortfall is closed-form in the record's own fields, so a
    # hand-built verdict is checked against the configuration it carries:
    # one claiming zero shortfall while its embargo falls short is a lie,
    # and so is one claiming a shortfall it does not have.  A record that
    # coheres — shortfall naming exactly the gap — is a value a caller can
    # use to describe a configuration it is inspecting.
    with pytest.raises(EvaluatorEmbargoError, match="falls 2 periods short"):
        EmbargoCheck(embargo=3, lookback=5, shortfall=0)
    with pytest.raises(EvaluatorEmbargoError, match="must describe"):
        EmbargoCheck(embargo=5, lookback=3, shortfall=2)
    inspecting = EmbargoCheck(embargo=3, lookback=5, shortfall=2)
    assert inspecting.shortfall == 2


def test_a_hand_built_record_honours_the_field_contract() -> None:
    # The record's fields are bar counts like the function's arguments: a
    # float or bool, a non-positive embargo or lookback, and a negative
    # shortfall are each refused, so a verdict cannot be built out of
    # values the check itself would have rejected.
    with pytest.raises(EvaluatorEmbargoError, match="integer count"):
        EmbargoCheck(embargo=6.0, lookback=6, shortfall=0)
    with pytest.raises(EvaluatorEmbargoError, match="integer count"):
        EmbargoCheck(embargo=True, lookback=6, shortfall=0)
    with pytest.raises(EvaluatorEmbargoError, match="at least one grid bar"):
        EmbargoCheck(embargo=0, lookback=6, shortfall=6)
    with pytest.raises(EvaluatorEmbargoError, match="at least one grid bar"):
        EmbargoCheck(embargo=6, lookback=0, shortfall=0)
    with pytest.raises(EvaluatorEmbargoError, match="negative"):
        EmbargoCheck(embargo=6, lookback=6, shortfall=-1)
