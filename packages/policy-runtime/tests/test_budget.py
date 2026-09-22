"""Feature 221, the statistical budget — never the compute budget.

app_spec.xml, "Exploration Policy Runtime", feature 221: *System exposes
budget_remaining, which returns statistical budget rather than compute budget.*
docs/nullius-tech-architecture.md §597's line in the identical ``question.*``
interface — ``question.budget_remaining()  # statistical, not compute`` — and
prd §422's repeat of it.

The sentence has two halves and the tests are split the same way: the *verb*
(a policy can read how much statistical budget an episode has left, and the
reading terminates a policy's loop) and the *resource* (what is returned is
degrees of freedom — counted from §8's ``charges_budget`` directive — and not
the machine).  The second half is the feature, so most of what follows pins it:

* **the spend is a count of directives, never a sum of weights** — §8's
  ``charge_units``, which the ledger member's own module states *"prices
  compute"*, is deliberately not consulted, and a cross-validated evaluation
  charged once costs this budget exactly one.  This is the substitution prd
  §705 records the system as having already made once (``β₁ N (agent calls)`` →
  ``β₁ · trials charged``), so it is pinned rather than left to the arithmetic;
* **a null node is not learnable here** — §7.2's directive is *"a directive,
  not a label… the only bit that crosses the barrier"*, so the account reports
  *uncharged* rows and never claims to know which of them were planted nulls;
* **the compute denominations are refused by name** — a row that says what the
  evaluation *cost* and not whether it charged budget is refused with §705 in
  the message, and :data:`COMPUTE_UNITS` names the other resource
  (wall clock, cgroup plane, agent calls, §10.1's rounds) so a caller who
  handed over the wrong number learns what it handed over;
* **the reading is the policy's, the account is the runtime's** — feature 224's
  law (§10.2 withholds ``budget_spent``) is kept one seam beneath the surface
  that refuses the name: what a policy is handed carries one number and no
  attribute walk reaches an allowance, a charge list or a spend;
* **an unstated ceiling is unbounded, not zero** — a deployment that configured
  no statistical allowance answers ``inf``, the same statement
  :meth:`bootstrap.BootstrapQuestion.budget_remaining` makes for §10.6's *"zero
  statistical-budget cost"*, so "one policy, both pools" holds for this verb.

The headline case is the feature's own sentence, read as a contradiction to be
avoided: an episode whose evaluations cost a great deal of compute and charged
no statistical budget reads an *undiminished* remaining budget.
"""

from __future__ import annotations

import copy
import json
import pickle
from types import SimpleNamespace
from typing import Any

import pytest
from policy_runtime import (
    COMPUTE_UNITS,
    STATISTICAL_UNIT,
    UNBOUNDED_BUDGET,
    BudgetAccount,
    CampaignTree,
    PolicyBudgetError,
    PolicyQuestion,
    PolicyRuntimeError,
    StatisticalBudget,
    budget_account,
    policy_question,
)


def _trial(charges_budget: Any = True, **extra: Any) -> SimpleNamespace:
    """One charge row — §8's directive, spelled the way the ledger hands it over.

    A duck-typed row rather than the ledger member's own record type: this
    member never imports a sibling, and the seam the account reads is the
    attribute, so the *shape* is what a test should exercise.  ``extra`` is how
    a test says what a row carries *besides* the directive — §8's
    ``charge_units``, an epoch, a node — which is how "read for its directive
    and nothing else" is pinned.
    """
    return SimpleNamespace(charges_budget=charges_budget, **extra)


class _Recharging:
    """A live account: the spend a replay records as its rounds charge budget.

    Not :class:`BudgetAccount` — that is a *value*, a pure function of the rows
    it was handed, and it deliberately does not mutate: a mutable account would
    make a reading depend on when it was taken, in a way nothing could
    reproduce (§10.1's determinism requirement, restated for the budget).  What
    a replay actually holds is the state the reading is *live* against, which is
    the seam :meth:`PolicyQuestion.budget_remaining` documents — it reads
    ``remaining`` afresh on every call.  This is the smallest object with that
    shape, and it is why the question takes an *account* rather than a number:
    a pre-read float could not fall.
    """

    def __init__(self, allowance: float) -> None:
        self._allowance = allowance
        self._charged = 0

    @property
    def remaining(self) -> float:
        return self._allowance - self._charged

    def charge(self) -> None:
        """Record one more trial that consumed statistical budget."""
        self._charged += 1


# ---------------------------------------------------------------------------
# The verb: a policy can read how much statistical budget is left.
# ---------------------------------------------------------------------------


def test_budget_remaining_answers_the_allowance_less_the_charges() -> None:
    # The plain reading, and the one a policy's termination test is written
    # against: an allowance of ten trials with three charged leaves seven.
    account = budget_account(10.0, [_trial(), _trial(), _trial()])
    assert account.remaining == 7.0


def test_a_campaign_that_charged_nothing_reads_its_whole_allowance() -> None:
    # The zero case, and it is the one the feature's *other* half turns on: a
    # campaign of evaluations that consumed compute and no degrees of freedom
    # has spent none of the statistical budget. prd §123: "it consumes agent
    # calls and CPU but **not** degrees of freedom".
    account = budget_account(10.0, [_trial(False) for _ in range(25)])
    assert account.remaining == 10.0
    assert account.charged == 0
    assert account.evaluations == 25


def test_an_overspent_campaign_reads_a_negative_number_rather_than_zero() -> None:
    # Not floored. §15 makes an exhausted budget an operational stop ("Stop."),
    # and a reading floored at zero hides the state that fires it: a campaign
    # four trials past its allowance must read *minus* four, so the operator
    # surface and the replay both see how far past it went.
    account = budget_account(2.0, [_trial() for _ in range(6)])
    assert account.remaining == -4.0
    assert account.exhausted is True


def test_exhausted_is_exactly_at_zero_too() -> None:
    # Exactly-at-zero is exhausted: the *next* charged trial overspends, so
    # there is no budget left to spend. A policy that read this as "one more is
    # affordable" would overspend by exactly one every time.
    account = budget_account(3.0, [_trial() for _ in range(3)])
    assert account.remaining == 0
    assert account.exhausted is True
    assert budget_account(3.0, [_trial(), _trial()]).exhausted is False


def test_the_reading_is_what_the_question_answers() -> None:
    # The seam itself: the account is the runtime's, and the *question* is the
    # object a policy is handed. One implementation — the question returns the
    # account's own reading — so the two cannot disagree about the campaign.
    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    account = budget_account(5.0, [_trial(), _trial(False), _trial()])
    question = policy_question(tree, account)
    assert question.budget_remaining() == 3.0


def test_a_question_with_no_account_answers_unbounded_but_does_not_refuse() -> None:
    # A deployment that stated no statistical ceiling, and the reading is the
    # honest one rather than a refusal: a budgetless question is exactly what
    # feature 217's existing call sites construct, and refusing those would
    # break "one policy, both pools" rather than protect anything.
    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    assert policy_question(tree).budget_remaining() == UNBOUNDED_BUDGET
    assert policy_question(tree, None).budget_remaining() == UNBOUNDED_BUDGET
    assert PolicyQuestion(tree).budget_remaining() == UNBOUNDED_BUDGET


def test_an_unbounded_allowance_is_not_a_budget_of_zero() -> None:
    # The dangerous substitution: `0` would make a policy stop before spending
    # anything, on a deployment that stated no ceiling at all. `inf` is what
    # bootstrap's own `budget_remaining()` answers for §10.6's zero statistical
    # cost, so the two pools read the same statement of no constraint.
    account = budget_account(UNBOUNDED_BUDGET, [_trial() for _ in range(50)])
    assert account.remaining == UNBOUNDED_BUDGET
    assert account.remaining > 1_000_000
    assert account.exhausted is False


def test_a_policy_style_loop_terminates_on_the_reading() -> None:
    # The reason the verb exists: a policy's own mandate must let it terminate
    # (§11: "must terminate when no batch is selected"). A replay in miniature
    # — reveal one cell per round until the budget is spent — driven only by
    # the reading, which is what authored policy code writes.
    tree = CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": ("n0", 1, {"parent_id": "n0", "depth": 1, "r2_insample": 0.2}),
            "n2": ("n0", 1, {"parent_id": "n0", "depth": 1, "r2_insample": 0.3}),
            "n3": ("n0", 1, {"parent_id": "n0", "depth": 1, "r2_insample": 0.4}),
        }
    )
    live = _Recharging(2.0)
    question = policy_question(tree, live)

    rounds = 0
    while question.budget_remaining() > 0 and rounds < 10:
        rounds += 1
        question.reveal(f"n{rounds}")  # a round's work…
        live.charge()  # …which the replay records as a trial that charged
    assert rounds == 2  # the loop stopped on the budget, not the guard
    assert question.budget_remaining() == 0


def test_the_reading_is_live_and_a_reading_already_taken_is_not() -> None:
    # The two halves of one fact. The *account* is read afresh on every call,
    # so a policy watching its budget across rounds sees the figure fall — the
    # whole point of the verb. A *reading* already taken does not move, so the
    # number in the policy's hand is what the campaign's charges said when it
    # was read. Feature 226's fixed scalar is the contrast, not the precedent:
    # beta is fixed by the deployment, while this is a measurement of a spend
    # that keeps happening.
    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    live = _Recharging(4.0)
    question = policy_question(tree, live)

    held = question.budget_remaining()
    live.charge()
    live.charge()
    assert question.budget_remaining() == 2.0  # the account fell
    assert held == 4.0  # the reading taken did not
    assert held is not question.budget_remaining()  # nor are they one object


# ---------------------------------------------------------------------------
# The resource: it is statistical budget, not compute budget.
# ---------------------------------------------------------------------------


def test_the_spend_counts_directives_and_never_sums_units() -> None:
    # **The feature.** A cross-validated evaluation that runs five folds is one
    # hypothesis tested against the same forward returns: §8's `charge_units`
    # says what it cost to run ("1.0 default; CV folds may cost more") and the
    # directive says whether it spent degrees of freedom. Five expensive
    # evaluations, two of which charged, spend exactly two.
    expensive = [_trial(True, charge_units=5.0), _trial(True, charge_units=9.5)]
    cheap = [_trial(False, charge_units=0.5), _trial(False, charge_units=1.0)]
    account = budget_account(10.0, expensive + cheap + [_trial(False, charge_units=4.0)])

    assert account.evaluations == 5
    assert account.charged == 2
    assert account.remaining == 8.0
    # Not 20.0 (the sum of the units), not 1.0 — the arithmetic a compute
    # budget would have produced, in either direction.
    assert account.remaining != 10.0 - sum(
        row.charge_units for row in expensive + cheap + [_trial(False, charge_units=4.0)]
    )


def test_one_evaluation_charged_twice_still_spends_one() -> None:
    # The same law from the row side: the account keeps one directive per trial
    # and counts charges, so a campaign whose rows are one-per-evaluation
    # cannot have a single evaluation counted as two degrees of freedom however
    # much it cost. (The dual — one *hypothesis* recorded across two epochs —
    # is feature 93's `K_effective`, which sums repeats per epoch on purpose;
    # the difference is the key, and this account is not keyed by epoch.)
    account = budget_account(10.0, [_trial(True, charge_units=12.0)])
    assert account.charged == 1
    assert account.remaining == 9.0


def test_the_compute_denominations_are_named_and_the_statistical_one_is_too() -> None:
    # The contrast the feature's sentence draws, available to a caller rather
    # than living only in a docstring: the account answers what it meters, and
    # the module names the resource it does *not*. Every member of
    # COMPUTE_UNITS is one the system genuinely meters somewhere — the cgroup
    # plane (feature 162), wall clock (163), agent calls (the meter prd §705
    # retired), §10.1's rounds, and §8's per-row unit — and none of them is
    # what budget_remaining() answers in.
    assert budget_account(1.0).unit == STATISTICAL_UNIT
    assert STATISTICAL_UNIT == "trials_charged"
    assert STATISTICAL_UNIT not in COMPUTE_UNITS
    assert {"wall_s", "cpu_s", "mem_mb", "pids", "agent_calls", "rounds", "charge_units"} == (
        COMPUTE_UNITS
    )


def test_a_row_carrying_units_and_no_directive_is_refused_by_name() -> None:
    # **The mistake the feature exists to catch.** A caller holding a compute
    # measurement — §8's per-row cost — and asking for a statistical spend.
    # Refused rather than read as uncharged: silently counting it as "did not
    # charge" would *understate* the spend, the one direction an honest count
    # must never move by accident.
    with pytest.raises(PolicyBudgetError) as raised:
        budget_account(10.0, [SimpleNamespace(charge_units=3.0)])
    message = str(raised.value)
    assert "charge_units" in message
    assert "charges_budget" in message
    assert "prices compute" in message
    assert "§705" in message or "705" in message


def test_a_row_carrying_neither_is_refused_naming_the_directive() -> None:
    # The other half: a row that simply cannot say. Absent is not False.
    with pytest.raises(PolicyBudgetError) as raised:
        budget_account(10.0, [SimpleNamespace(epoch="e1", node_id="n2")])
    message = str(raised.value)
    assert "charges_budget" in message
    assert "understate" in message


def test_a_row_that_says_something_that_is_not_a_directive_is_refused() -> None:
    # A 2, a string, None — read as uncharged they would silently understate the
    # spend, and read as charged they would invent a degree of freedom the
    # campaign never spent. Both directions are wrong, so neither is taken.
    for value in (2, -1, "true", None, 3.0, [True]):
        with pytest.raises(PolicyBudgetError) as raised:
            budget_account(10.0, [SimpleNamespace(charges_budget=value)])
        assert "charges_budget" in str(raised.value)


def test_the_sqlite_spelling_of_a_directive_is_read() -> None:
    # A SQLite BOOLEAN column stores 0/1 (memory: "SQLite DBAPI affinity
    # traps"), and a directive read back as an int is the column's own spelling
    # rather than a drifted value — so it is coerced, while every other int is
    # refused above. The same read-path rule `validated_charges_budget` states
    # on the ledger's side of this column.
    account = budget_account(4.0, [_trial(1), _trial(0), _trial(1), _trial(0)])
    assert account.charged == 2
    assert account.remaining == 2.0
    assert account.charges == (True, False, True, False)


def test_a_genuine_bool_is_never_confused_with_an_int() -> None:
    # `True` is an `int` in Python, so the directive check tests `bool` first —
    # otherwise the coercion branch above would be doing the work and a drifted
    # `1` and a real `True` would be indistinguishable at exactly the seam
    # where the difference matters.
    assert budget_account(1.0, [_trial(True)]).charges == (True,)
    assert budget_account(1.0, [_trial(1)]).charges == (True,)
    assert budget_account(1.0, [_trial(False)]).charges == (False,)


def test_the_account_reads_the_directive_and_nothing_else_of_a_row() -> None:
    # A row carrying the whole of §8 — epoch, node, units, outcome — is read
    # for one field. The epoch is feature 93's key, the unit is feature 89's
    # cost, the node is the tree's; copying any of them here would be a second
    # ledger free to drift from the first. Pinned structurally: two rows that
    # differ in everything but the directive produce equal accounts.
    rich = _trial(
        True,
        epoch="e1",
        charge_units=7.5,
        node_id="n2",
        ts="2026-01-01T00:00:00Z",
        world_id="w1",
        r2_holdout=0.41,
    )
    assert budget_account(10.0, [rich]) == budget_account(10.0, [_trial(True)])
    # …and the row itself is not held: mutating it after the read moves nothing.
    rich.charges_budget = False
    assert budget_account(10.0, [rich]).charged == 0


def test_the_account_does_not_claim_to_know_which_rows_were_nulls() -> None:
    # §7.2's barrier: the directive is "a directive, not a label: the caller
    # learns whether to debit statistical budget without learning why". So the
    # account reports *uncharged* as a count and exposes no classification —
    # there is no `nulls`, no `null_fraction`, no per-row reason. What it knows
    # is what the rows did not spend, which is exactly what the honest name
    # says.
    account = budget_account(10.0, [_trial(True), _trial(False), _trial(False)])
    assert account.uncharged == 2
    assert account.charged + account.uncharged == account.evaluations
    for invented in ("nulls", "null_count", "null_fraction", "reasons", "labels"):
        assert not hasattr(account, invented)


def test_the_two_budgets_are_reported_as_a_contrast() -> None:
    # prd §123's sentence, as arithmetic: a campaign of planted nulls consumes
    # compute and no degrees of freedom, so the two figures diverge by exactly
    # the number of rows that charged nothing. A module that could only report
    # one of them could not show it is reporting the right one.
    rows = [_trial(True)] + [_trial(False) for _ in range(19)]
    account = budget_account(100.0, rows)
    assert account.evaluations == 20  # the compute the campaign spent
    assert account.charged == 1  # the degrees of freedom it spent
    assert account.remaining == 99.0


# ---------------------------------------------------------------------------
# The value: a reading carries its denomination and nothing else.
# ---------------------------------------------------------------------------


def test_the_reading_is_the_number_it_is() -> None:
    # A float subclass rather than a wrapper (feature 226's choice for the beta
    # scalar): authored policy code compares it against a threshold, prints it,
    # serializes it and adds to it, and a wrapper would put an unwrap at every
    # one of those seams.
    reading = StatisticalBudget(7.5)
    assert isinstance(reading, float)
    assert reading == 7.5
    assert reading < 8
    assert reading + 1 == 8.5
    assert sorted([StatisticalBudget(2), 1.0]) == [1.0, 2.0]
    assert json.dumps({"remaining": StatisticalBudget(2.5)}) == '{"remaining": 2.5}'


def test_the_reading_holds_no_allowance_and_no_spend() -> None:
    # Feature 224's law, one seam beneath the surface that refuses the *name*
    # `budget_spent` (docs §10.2): a policy handed the reading holds one number
    # and cannot walk to what it has already cost. Structural, not conventional
    # — `__slots__ = ()` means there is no attribute to find, however the
    # policy spells the ask.
    reading = budget_account(10.0, [_trial(), _trial()]).remaining
    assert type(reading).__slots__ == ()
    assert not hasattr(reading, "__dict__")
    for withheld in ("allowance", "charges", "spent", "charged", "evaluations", "account"):
        assert not hasattr(reading, withheld)
    # A *read* of the withheld name is an ordinary AttributeError — the name is
    # not there — while a *write* is this feature's own refusal, so a policy's
    # defensive `try/except AttributeError` around an attribute read behaves
    # normally and a scribble is refused in the member's vocabulary.
    assert getattr(reading, "spent", None) is None
    with pytest.raises(PolicyBudgetError):
        reading.spent = 4  # type: ignore[attr-defined]


def test_the_reading_normalises_to_a_float() -> None:
    # An int allowance reads as a float, so the denomination and the type agree
    # however the deployment spelled its number.
    assert isinstance(StatisticalBudget(5), float)
    assert isinstance(budget_account(5, ()).remaining, float)


def test_a_reading_once_taken_cannot_be_moved() -> None:
    # Feature 226's guard (BetaFixedError) restated for the budget: the figure
    # is what the campaign's charges said when it was read. Every path a caller
    # could move it by is refused — the value, an underscored spelling, a
    # shadow attribute, deletion — and `object.__setattr__` finds no slot to
    # rebind, so the guarantee is a fact about the type.
    reading = StatisticalBudget(7.0)
    with pytest.raises(PolicyBudgetError):
        reading.value = 99  # type: ignore[attr-defined]
    with pytest.raises(PolicyBudgetError):
        reading._value = 99  # type: ignore[attr-defined]
    with pytest.raises(PolicyBudgetError):
        reading.allowance = 99  # type: ignore[attr-defined]
    with pytest.raises(PolicyBudgetError):
        del reading.value  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        object.__setattr__(reading, "value", 99)
    assert reading == 7.0


def test_the_refusal_names_the_law_and_the_reading() -> None:
    # A refusal an author can act on: it says what was refused, that the number
    # is a reading, and which feature's law it is.
    with pytest.raises(PolicyBudgetError) as raised:
        StatisticalBudget(1.0).value = 2  # type: ignore[attr-defined]
    assert "feature 221" in str(raised.value)
    assert "reading" in str(raised.value)


def test_a_reading_survives_the_round_trips_a_replay_performs() -> None:
    # The same guarantee feature 226's scalar carries: a reading crosses a
    # replay worker, a cached episode and a copied round, and each round trip
    # must answer the same number in the same denomination — not a bare float
    # that lost the fact it was a budget.
    reading = budget_account(10.0, [_trial(), _trial()]).remaining
    for rebuilt in (copy.copy(reading), copy.deepcopy(reading), pickle.loads(pickle.dumps(reading))):
        assert rebuilt == reading
        assert isinstance(rebuilt, StatisticalBudget)
        assert type(rebuilt).__slots__ == ()


# ---------------------------------------------------------------------------
# The refusals: a value that names no budget is not a budget.
# ---------------------------------------------------------------------------


def test_a_bool_is_refused_rather_than_read_as_a_number() -> None:
    # `True` is an `int`. A budget that arrived as a truth value is a flag that
    # wandered into a numeric column, and reading it as 1 would be the member
    # inventing the figure it is only meant to report.
    for value in (True, False):
        with pytest.raises(PolicyBudgetError):
            StatisticalBudget(value)


def test_text_none_and_objects_are_refused() -> None:
    for value in ("5", None, object(), [5], {"remaining": 5}, b"5"):
        with pytest.raises(PolicyBudgetError):
            StatisticalBudget(value)


def test_a_nan_reading_is_refused() -> None:
    # A NaN compares false against every threshold, so a policy's
    # `while budget_remaining() > 0` would never see it and the loop would not
    # terminate on the resource it was watching — the same refusal feature 222
    # makes against a NaN score.
    with pytest.raises(PolicyBudgetError) as raised:
        StatisticalBudget(float("nan"))
    assert "NaN" in str(raised.value)
    with pytest.raises(PolicyBudgetError):
        StatisticalBudget(float("-inf"))


def test_a_negative_reading_is_read_not_refused() -> None:
    # Deliberately legal: it is what an overspent episode honestly reads, and
    # flooring it is the one direction that hides §15's stop.
    assert StatisticalBudget(-4.0) == -4.0
    assert StatisticalBudget(-4.0) < 0


def test_a_bare_number_is_refused_where_a_question_s_budget_belongs() -> None:
    # The substitution at the seam, refused by name: a float names no resource,
    # and "is this five trials or five seconds?" is the question feature 221
    # exists to answer. Refused rather than wrapped through budget_account() —
    # which would make the bare number look like a budget.
    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    with pytest.raises(PolicyBudgetError) as raised:
        policy_question(tree, 5.0)  # type: ignore[arg-type]
    message = str(raised.value)
    assert "budget_account" in message
    assert "bare number" in message


def test_an_object_without_a_remaining_is_refused() -> None:
    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    for value in (SimpleNamespace(allowance=5.0), object(), "account"):
        with pytest.raises(PolicyBudgetError):
            policy_question(tree, value)  # type: ignore[arg-type]


def test_an_allowance_below_zero_is_refused() -> None:
    # An allowance is how much there *is*; a negative one is a spend wearing an
    # allowance's name. An overspent campaign is what the *reading* reports (a
    # negative remaining), never what the allowance says.
    with pytest.raises(PolicyBudgetError) as raised:
        budget_account(-1.0, ())
    assert "negative" in str(raised.value)


def test_an_allowance_that_is_not_an_amount_is_refused() -> None:
    for value in ("10", None, True, float("nan"), object(), [10]):
        with pytest.raises(PolicyBudgetError):
            budget_account(value, ())


def test_an_allowance_of_zero_is_stated_and_read() -> None:
    # Zero is a stated ceiling ("no statistical budget at all"), which is a
    # different fact from a deployment that stated none — and both are legal.
    account = budget_account(0, ())
    assert account.remaining == 0
    assert account.exhausted is True
    assert account.remaining != UNBOUNDED_BUDGET


def test_an_infinite_allowance_is_the_unbounded_statement() -> None:
    # `inf` is not a mistake here: it *is* how "no ceiling configured" is
    # spelled, and it is the value bootstrap's own budget_remaining() answers,
    # so the two pools agree on the open-ended case.
    assert budget_account(float("inf"), ()).remaining == UNBOUNDED_BUDGET
    assert UNBOUNDED_BUDGET == float("inf")


def test_every_refusal_is_catchable_as_the_members_one_base_class() -> None:
    # The single-except discipline the member keeps: every budget failure is a
    # PolicyRuntimeError, so a caller that catches the read-side path's base
    # class catches a refused budget read too — and PolicyBudgetError is not an
    # AttributeError, because a budget that names no number is not a surface
    # refusing a name (feature 224's class is the one that doubles that).
    assert issubclass(PolicyBudgetError, PolicyRuntimeError)
    assert not issubclass(PolicyBudgetError, AttributeError)
    for refused in (
        lambda: StatisticalBudget("x"),
        lambda: budget_account(-1.0, ()),
        lambda: budget_account(1.0, [SimpleNamespace()]),
    ):
        with pytest.raises(PolicyRuntimeError):
            refused()


# ---------------------------------------------------------------------------
# Purity: the account is a function of what it was handed.
# ---------------------------------------------------------------------------


def test_the_account_is_a_value_and_reads_nothing_ambient() -> None:
    # No store, no clock, no environment, no interpreter state: two accounts of
    # one campaign's charges are equal values, so a replay can compare readings
    # and a test can pin one.
    rows = [_trial(True), _trial(False), _trial(True)]
    assert budget_account(10.0, rows) == budget_account(10.0, rows)
    assert budget_account(10.0, rows) != budget_account(11.0, rows)
    assert budget_account(10.0, rows) != budget_account(10.0, rows[:2])
    assert hash(budget_account(10.0, rows)) == hash(budget_account(10.0, tuple(rows)))


def test_an_account_cannot_be_moved_after_it_is_built() -> None:
    # Frozen: an account that a caller could rebind would be a budget the
    # runtime could be talked out of, and the reading a policy was handed would
    # stop agreeing with the spend it was taken from. The refusal is the
    # dataclass's own `FrozenInstanceError` — an `AttributeError`, so an
    # attribute-protocol handler sees it as any other unsettable name — rather
    # than this member's error, because a *well-formed* account being scribbled
    # on is a different failure from a budget that names no number.
    import dataclasses

    account = budget_account(10.0, [_trial()])
    with pytest.raises(dataclasses.FrozenInstanceError):
        account.allowance = 99.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        account.charges = ()  # type: ignore[misc]
    assert account.remaining == 9.0


def test_a_magnitude_beyond_floating_point_is_refused_in_the_members_own_error() -> None:
    # ``numbers.Real`` is not the same guarantee as "a float can carry it": an
    # int of arbitrary precision is a Real, and ``float(10**400)`` raises
    # OverflowError. Letting the conversion's own exception escape would hand a
    # caller catching the member's one base class an exception it does not
    # catch — the error-vocabulary leak a member seam must not have
    # ([[error-vocabulary-at-member-seams]]). Feature 226's ``read_beta``
    # translates the same failure atits own seam.
    for refused in (lambda: StatisticalBudget(10**400), lambda: budget_account(10**400, ())):
        with pytest.raises(PolicyBudgetError):
            refused()
        with pytest.raises(PolicyRuntimeError):  # the caller's side of the same rule
            refused()


def test_a_row_whose_directive_raises_is_refused_rather_than_escaping() -> None:
    # A row is a *caller's* object and `charges_budget` may be a property whose
    # backing store is gone. A bare RuntimeError escaping here would be an
    # exception the member's one base class does not catch, thrown from a seam
    # this member owns — and it would escape from a *set* of rows, where one
    # bad row must be neither silently skipped nor silently counted.
    class Unreadable:
        @property
        def charges_budget(self) -> bool:
            raise RuntimeError("backing store gone")

    with pytest.raises(PolicyBudgetError) as raised:
        budget_account(1.0, [Unreadable()])
    assert "could not be read" in str(raised.value)


def test_a_row_whose_units_also_raise_is_still_refused_as_a_budget_error() -> None:
    # The row *without* a directive is re-read for `charge_units`, to make the
    # refusal say more. If that diagnostic read raises too, the failure is
    # still this law's: reporting the second problem instead of the first (or
    # discarding it in a blind catch) would both be wrong.
    class Unreadable:
        @property
        def charges_budget(self) -> bool:
            raise RuntimeError("gone")

        @property
        def charge_units(self) -> float:
            raise RuntimeError("also gone")

    with pytest.raises(PolicyBudgetError):
        budget_account(1.0, [Unreadable()])


def test_an_account_that_cannot_answer_at_all_is_refused_at_construction() -> None:
    # The seam is checked *eagerly*, by reading `remaining` once — so a budget
    # that cannot answer is refused where the wiring is done rather than on the
    # first round of an episode. The refusal is this law's, and it names the
    # account, so the caller that attached the wrong object finds out in the
    # replay's setup and not in a policy's loop.
    class Unreadable:
        @property
        def remaining(self) -> float:
            raise RuntimeError("ledger unreachable")

    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    with pytest.raises(PolicyBudgetError) as raised:
        policy_question(tree, Unreadable())
    assert "budget_account" in str(raised.value)


def test_an_account_that_fails_mid_episode_answers_the_members_own_error() -> None:
    # The realistic live failure, and the reason the *call* needs its own
    # translation as well as the constructor: an account that answers at setup
    # and loses its backing store mid-episode. The read happens during the
    # episode against an object the replay owns, so a bare exception would
    # reach authored policy code naming no contract, and the policy's own
    # ``except PolicyRuntimeError`` would not catch it.
    class Flaky:
        def __init__(self) -> None:
            self.broken = False

        @property
        def remaining(self) -> float:
            if self.broken:
                raise RuntimeError("ledger unreachable")
            return 3.0

    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    account = Flaky()
    question = policy_question(tree, account)
    assert question.budget_remaining() == 3.0  # fine at setup
    account.broken = True
    with pytest.raises(PolicyBudgetError):
        question.budget_remaining()
    with pytest.raises(PolicyRuntimeError):  # the caller's side of the same rule
        question.budget_remaining()


def test_a_budget_error_from_a_live_account_passes_through_unnamed() -> None:
    # The other side of the same seam: a refusal that is *already* this law's is
    # not re-wrapped, so the specific message a caller needs survives the
    # translation rather than being buried under a general one.
    class Refusing:
        @property
        def remaining(self) -> float:
            raise PolicyBudgetError("the ledger's own refusal")

    tree = CampaignTree.freeze({"n0": (None, 0, {"depth": 0})})
    with pytest.raises(PolicyBudgetError, match="the ledger's own refusal"):
        policy_question(tree, Refusing()).budget_remaining()


def test_an_integer_allowance_reads_as_a_float() -> None:
    # The denomination and the type agree however the deployment spelled its
    # number, and the subtraction stays float arithmetic on a validated
    # magnitude.
    reading = budget_account(10, [_trial()]).remaining
    assert reading == 9.0
    assert isinstance(reading, float)


def test_an_unbounded_allowance_stays_unbounded_however_many_trials_charged() -> None:
    # ``inf`` less any finite count is still ``inf``, so a deployment that
    # stated no ceiling cannot be brought to a stop by arithmetic it never
    # agreed to — the failure mode where a long campaign silently acquires a
    # limit it was never given.
    account = budget_account(UNBOUNDED_BUDGET, [_trial() for _ in range(1_000)])
    assert account.remaining == UNBOUNDED_BUDGET
    assert account.exhausted is False


def test_an_account_accepts_any_iterable_of_rows() -> None:
    # The seam is duck-typed and lazily iterated: a ledger cursor, a tuple, a
    # generator and a list of rows all read the same, and the account is the
    # same value — so a replay can hand over a store's iterator without
    # materialising it first.
    rows = [_trial(True), _trial(False)]
    made = (
        budget_account(5.0, rows),
        budget_account(5.0, tuple(rows)),
        budget_account(5.0, (row for row in rows)),
        budget_account(5.0, iter(rows)),
    )
    assert len({(account.allowance, account.charges) for account in made}) == 1
    assert made[0].remaining == 4.0


def test_an_empty_campaign_reads_its_whole_allowance() -> None:
    # No rows is not an error: a campaign before its first evaluation is a
    # campaign that has spent nothing, which is the state a replay opens in.
    account = budget_account(10.0)
    assert account.evaluations == 0
    assert account.charged == 0
    assert account.uncharged == 0
    assert account.remaining == 10.0
    assert account.exhausted is False


def test_the_account_is_repr_able_and_the_reading_debugs_as_itself() -> None:
    # Both objects show up in a replay's logs, and the reading's spelling says
    # the denomination rather than pretending to be a bare float.
    account = budget_account(10.0, [_trial(), _trial(False)])
    assert "BudgetAccount" in repr(account)
    assert repr(StatisticalBudget(7.0)) == "StatisticalBudget(7.0)"
    assert "BudgetAccount" in repr(BudgetAccount(allowance=3.0, charges=(True,)))
