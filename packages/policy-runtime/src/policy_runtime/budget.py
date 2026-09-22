"""Feature 221, the episode's budget — statistical, not compute.

app_spec.xml, "Exploration Policy Runtime", feature 221 (``depends_on=217``):
*System exposes budget_remaining, which returns statistical budget rather than
compute budget.*  The sentence is docs/nullius-tech-architecture.md §597's line
in the ``question.*`` interface — ``question.budget_remaining()  # statistical,
not compute`` — which docs/alpha-engine-prd.md §422 repeats verbatim in §C4's
listing of what an exploration policy is handed.  The eight words after the
hash are the whole feature: the *verb* is easy (any number satisfies "returns a
budget") and the *resource* is the feature.

**Two resources, and this document spends a paragraph separating them.**  The
system meters two different things and calls both of them budgets:

* **the statistical budget** is statistical degrees of freedom — *"hypotheses I
  implicitly tested"* (prd §363).  It is what §10.3's score subtracts
  (``− β₁ · trials_charged   # statistical budget consumed``), what §8's
  ``charges_budget`` column stamps a trial with, what feature 93's
  ``K_effective`` counts, and what prd §345's null bar grows with
  (``≈ √(2 ln K)``).  It is the *binding* resource — *"compute is cheap and
  degrees of freedom are the binding resource"* (prd §123) — and it is what an
  epoch's sequestration is spent against;
* **the compute budget** is the machine: the wall clock and memory prd §83
  names (``"Deterministic under a fixed seed, with wall-clock and memory
  budgets"``), §5.2's ``Limits(wall_s=30, cpu_s=30, mem_mb=2048, …, pids=32)``
  behind features 162 and 163, the agent's token spend, and §10.1's fixed round
  count ``K2``.

**The prd records the substitution this feature protects.**  §705 is a table
whose first two rows are the change the paper's Equation 1 underwent:
``| β₁ N (agent calls) | β₁ · trials charged (statistical budget) |`` and
``| Parallelism bonus | Removed; replaced by budget and overfit penalties |``.
The paper's penalty counted **agent calls** — a compute quantity, embarrassingly
parallel and cheap — and §315 states why it was replaced: *"Backtests are
embarrassingly parallel and cheap. Parallelism is not the bottleneck. Data
is."*  ``trials_charged`` counts the other resource.  So ``budget_remaining()``
answering "how many agent calls are left", "how much wall clock is left" or
"how many rounds of §10.1's loop remain" is not a near miss: it is the meter
§705 retired, reported under the name of the meter that replaced it.

**The discriminator is §8's directive, and the unit is what is *not* read.**
A charge row carries two budget-shaped fields and only one of them is this
feature's resource:

* ``charges_budget`` — *"the opaque budget directive"* (§7.2) — says **whether
  the trial consumed statistical degrees of freedom**.  This is the column the
  account reads, and the only one it reads;
* ``charge_units`` — *"1.0 default; CV folds may cost more"* (§8, feature 89)
  — says **what the evaluation cost**, and the ledger member's own module says
  in its own words that it *"prices* **compute**"*.  It is deliberately not
  summed here: a cross-validated evaluation that runs five folds is one
  hypothesis tested against the same forward returns, and feature 93 counts
  *rows* for exactly that reason.  Summing units would be the compute budget
  arriving through the arithmetic rather than through the verb.

So the spend is a **count of directives, never a sum of weights**, and a
five-fold evaluation charged once costs this budget exactly one unit.  The two
numbers are pinned apart by the tests beside this module: a campaign of five
evaluations of which two charged spends *two* of the statistical budget,
whatever the five cost to run.

**What is not read is also what may not be learned.**  ``charges_budget=False``
is the null oracle's opaque directive, and §7.2 is explicit that it is *"a
directive, not a label: the caller learns whether to debit statistical budget
without learning why"* — *"the only bit that crosses the barrier, and it is one
the agent never sees"*.  So a row that charged nothing is an **uncharged** row
and never a *null* one: this module does not know, cannot compute, and must not
name which rows were planted nulls.  prd §123's *"a null node's signal was
never compared to real forward returns, so it consumes agent calls and CPU but
**not degrees of freedom**"* is the fact the account reports — as two counts,
never as a classification — and :attr:`BudgetAccount.uncharged` is spelled for
it rather than around it.

**The reading is the policy's; the account is the runtime's.**  Feature 224 is
the sibling law on the same sentence — *"The policy runtime additionally
blocks: ``question.best_so_far``, ``question.budget_spent``…"* — and this
module's hand-off respects it to the letter.  :class:`BudgetAccount` is the
*accounting*: it holds the allowance and the charges, and it can therefore
answer **how much has been spent**, which is the one number §10.2 withholds
from a policy (224's module states the reason: *"``budget_remaining()`` is
offered; ``budget_spent`` — what it has already cost — is not"*).  What
``question.budget_remaining()`` answers is a :class:`StatisticalBudget` — the
*reading*, a bare number carrying nothing but itself — so a policy that walks
everything reachable from the answer it was handed finds no allowance, no
charge list and no spend.  The audience split is the question/view split
(feature 217/223) and the episode/surface split (224) applied to the budget:
the account is a fact about the campaign, the reading is what the policy earned
the right to see.

**The value is the number, in this member's own idiom.**  :class:`StatisticalBudget`
is a :class:`float` subclass, not a wrapper — the construction feature 226's
:class:`~policy_runtime.EpisodeBeta` chose for the beta scalar and for the same
reason: the figure is compared against a threshold in authored policy code
(``if question.budget_remaining() < patience:``), reported by the replay, and
carried into the score, and a wrapper would put an unwrap at every one of those
seams.  What the type adds is **the denomination** — *this number is degrees of
freedom* — which a bare float cannot state and which is precisely the thing the
feature's sentence is about.  It carries ``__slots__ = ()``, so the reading has
no place to hold an allowance or a spend, and it refuses every reassignment
path (226's guard, restated) so a reading once taken cannot be moved into a
different number.

**Bare numbers are refused as budgets, and that refusal is the sentence.**  A
caller may not hand :class:`~policy_runtime.PolicyQuestion` a ``float`` where
its budget belongs: ``5.0`` names no resource, and "is this five trials or five
seconds?" is the question the feature exists to answer.  The refusal is
:class:`~policy_runtime.PolicyBudgetError`, and it names the compute
denominations this module will not answer in (:data:`COMPUTE_UNITS`) rather
than merely reporting a type error.

**No allowance configured is unbounded, not zero.**  A deployment that states
no statistical ceiling has stated no ceiling: :data:`UNBOUNDED_BUDGET` is what
:meth:`PolicyQuestion.budget_remaining` answers then, which is the same value
:meth:`bootstrap.BootstrapQuestion.budget_remaining` answers for a bootstrap
world's *"zero statistical-budget cost"* (docs §10.6) — so a policy written
against one pool reads the same statement of no constraint in the other, which
is the identical-interface requirement of feature 184.  Answering ``0`` would
be a lie in the dangerous direction (the policy would stop before spending
anything) and refusing would make a budgetless question unconstructible, which
feature 217's own call sites are.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers`, :mod:`dataclasses`
and the member's own error — no third-party import at module scope, so the
factory's scan (which imports this package to fire its ``@register``) pays
nothing for the law.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Self

from .errors import PolicyBudgetError

__all__ = [
    "COMPUTE_UNITS",
    "STATISTICAL_UNIT",
    "UNBOUNDED_BUDGET",
    "BudgetAccount",
    "StatisticalBudget",
    "budget_account",
]

#: The one unit a statistical budget is denominated in — degrees of freedom,
#: spent one per budget-charging trial.  Spelled after the prd's own
#: replacement table (§705: ``β₁ N (agent calls)`` → ``β₁ · trials charged
#: (statistical budget)``), so the unit this module answers in and the unit the
#: prd names as the statistical one cannot drift apart.  It is a *name* rather
#: than a conversion factor because there is nothing to convert: the resource
#: is counted in trials, exactly as feature 93 counts ``K_effective``.
STATISTICAL_UNIT = "trials_charged"

#: The compute denominations this module will not answer a budget in.  Every
#: one is a resource the system genuinely meters somewhere — they are not
#: invented to be refused — and every one is the *other* budget:
#:
#: * ``wall_s`` — feature 163's wall-clock budget (§5.2's ``Limits(wall_s=30…)``;
#:   prd §390's *"under a wall-clock budget"*);
#: * ``cpu_s``, ``mem_mb``, ``pids`` — feature 162's cgroup plane (§5.2's
#:   ``cpu_s=30, mem_mb=2048, pids=32``; prd §83's *"wall-clock and memory
#:   budgets"*);
#: * ``agent_calls`` — the meter the prd retired when it replaced the paper's
#:   ``β₁ N`` with ``β₁ · trials charged`` (prd §705, §315);
#: * ``rounds`` — §10.1's ``while rounds < K2``: how many rounds of *replay* the
#:   loop has left, which is work the loop does and not a hypothesis tested;
#: * ``charge_units`` — §8's per-row cost (feature 89), which the ledger
#:   member's own module states *"prices compute"*.
#:
#: The failure this constant exists for is a caller handing over the *wrong
#: number* with no way for a reader to tell, so the set is used twice: to refuse
#: a budget that names one (there is no parameter by which one could arrive —
#: see :func:`budget_account`'s row check) and to name them in the refusals, so
#: a caller who passed seconds learns what it passed seconds *instead of*.
COMPUTE_UNITS: frozenset[str] = frozenset(
    {"wall_s", "cpu_s", "mem_mb", "pids", "agent_calls", "rounds", "charge_units"}
)

#: What ``budget_remaining()`` answers for a deployment that configured no
#: statistical allowance.  ``inf`` rather than ``0`` or a refusal, and the
#: reading is not this module's invention: the bootstrap member's
#: :meth:`bootstrap.BootstrapQuestion.budget_remaining` answers exactly this
#: for §10.6's *"zero statistical-budget cost"* (its own docstring: *"the whole
#: budget, always"*), so the identical-interface law of feature 184 holds
#: across both pools for this verb as it does for ``observed()``.  A ceiling
#: nobody stated is not a ceiling of zero: the honest report is that nothing
#: constrains the policy's statistical spend, and the policy's termination
#: condition must then come from §11's other rule — *"must terminate when no
#: batch is selected"* (prd §436) — which is the rule that binds a bootstrap
#: policy today for the same reason.
UNBOUNDED_BUDGET: float = float("inf")

#: The attribute §8's directive rides on — the one field a charge row must
#: carry for this module to read it.  Named once so the row check, the factory
#: and the refusals agree on the spelling, the discipline
#: :data:`ledger.record`'s column tuple and :data:`bootstrap._trial`'s own
#: ``_TRIAL_COLUMNS`` follow on their side of the same column.
_DIRECTIVE_FIELD = "charges_budget"

#: The compute field that is *not* the directive, named so the refusal for a
#: row carrying it can say what the row actually said: §8's ``charge_units``
#: prices what a trial cost to run (feature 89), and a caller holding a record
#: that carries only that has a compute measurement in hand — not a statement
#: about degrees of freedom.
_UNIT_FIELD = "charge_units"

#: A sentinel for "the row does not carry the field at all", distinct from a
#: row carrying ``None`` — which is a *present* directive that is not a bool,
#: a different refusal from an absent one.
_MISSING = object()


class StatisticalBudget(float):
    """The statistical budget an episode has left — degrees of freedom, not compute.

    Feature 221's reading: the value ``question.budget_remaining()`` answers,
    and the thing the feature's sentence is about.  A :class:`float` subclass
    rather than a wrapper (feature 226's choice for :class:`EpisodeBeta`), so
    the figure compares against a threshold, prints, serializes and binds like
    the number it is — authored policy code writes
    ``if question.budget_remaining() < patience:`` and needs no unwrap.

    **The type is the denomination.**  A bare :class:`float` cannot say *which*
    resource it meters, and "returns statistical budget rather than compute
    budget" is entirely a statement about which one.  The class therefore
    carries that statement in its type and its docstring and nowhere else: it
    holds ``__slots__ = ()``, so it has no attribute for an allowance, a charge
    list or a spend — which is also what keeps feature 224's law true of the
    *answer* and not only of the surface that hands it over (a reading from
    which ``budget_spent`` could be walked would be the withheld number
    arriving one seam late).

    **What it accepts.**  Any real number, positive or negative, plus
    :data:`UNBOUNDED_BUDGET` for "no allowance configured".  A *negative*
    reading is deliberately legal: it is what an overspent episode honestly
    reads (``allowance - charged`` with the charges past the allowance), and
    refusing it would force the account to floor the figure — which is the
    one direction that hides a stop condition §15 makes an operational alarm
    (*"Sequestered epochs exhausted | … | **Stop.**"*).  A NaN is refused: it
    compares false against everything, so a policy's ``while
    budget_remaining() > 0`` would never see it and the loop would not
    terminate on the resource it was watching — the same argument feature 222
    makes against a NaN score.  ``-inf`` is refused as a quantity no reading
    names, and a non-number (text, ``None``, a :class:`bool`) is refused rather
    than coerced, because coercion is how a mistyped configuration becomes a
    silent episode (feature 226 states the same rule for the same reason).

    **It does not move.**  Every reassignment path — ``budget.x = …``,
    ``budget._x = …``, a shadow attribute, ``del budget.x`` — raises
    :class:`~policy_runtime.PolicyBudgetError`, the guard feature 226 draws
    around the beta scalar: a reading is what the episode's spend *was* when it
    was taken, and a reading a caller could move would be a budget the policy
    shaped rather than the one it earned.
    """

    #: Empty, deliberately, and doubly so: a float has no ``__dict__`` to attach
    #: shadow state to, and no slot here means the reading has nowhere to keep
    #: an allowance or a spend beside itself — the structural half of the
    #: audience split this module keeps with feature 224.
    __slots__ = ()

    def __new__(cls, value: object) -> Self:
        """Read a budget figure into the type that names its denomination.

        The one place a number becomes a statistical budget, so "which resource
        is this?" is answered once, at construction, and every reader of the
        value reads the answer.  Accepts a real number (of either sign, plus
        :data:`UNBOUNDED_BUDGET`) and refuses everything else with
        :class:`~policy_runtime.PolicyBudgetError`, naming what arrived.
        """
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            # ``bool`` first: ``True`` is an ``int`` in Python, and a budget
            # that arrived as a truth value is a flag that wandered into a
            # numeric column — the same explicit refusal feature 226 applies to
            # its own scalar's ``__new__``.
            raise PolicyBudgetError(
                f"a statistical budget is a real number of remaining trials "
                f"charged — feature 221's reading, the resource docs §10.3 "
                f"subtracts as 'β₁ · trials_charged  # statistical budget "
                f"consumed' and prd §705 names as the statistical budget; got "
                f"{value!r} ({type(value).__name__}). A value that is not a "
                f"real number names no quantity of that resource, and "
                f"coercing one would be this member inventing the figure it is "
                f"only meant to report"
            )
        try:
            reading = float(value)
        except (OverflowError, ValueError, TypeError) as unconvertible:
            # ``numbers.Real`` is not the same guarantee as "a float can carry
            # it": an ``int`` of arbitrary precision is a ``Real``, and
            # ``float(10**400)`` raises :class:`OverflowError`.  Letting that
            # escape would hand a caller catching this member's one base class
            # an exception it does not catch — the error-vocabulary leak a
            # member seam must not have ([[error-vocabulary-at-member-seams]]).
            # The conversion's own failures are translated rather than
            # propagated; the same translation feature 226's ``read_beta``
            # performs at its own seam.
            raise PolicyBudgetError(
                f"a statistical budget must be a magnitude a float can carry — "
                f"got {value!r} ({type(value).__name__}), which float() cannot "
                f"convert ({unconvertible!r}). The reading is a count of "
                f"remaining trials charged and is compared against thresholds "
                f"by authored policy code, so a magnitude beyond floating point "
                f"is a reading no policy could test (feature 221)"
            ) from unconvertible
        if math.isnan(reading):
            raise PolicyBudgetError(
                "a statistical budget cannot be NaN: a NaN compares false "
                "against every threshold, so authored policy code watching "
                "this resource — 'while question.budget_remaining() > 0' — "
                "would never see it and the policy would not terminate on the "
                "budget it was watching. A reading that cannot be compared is "
                "not a reading the policy mandate can use (feature 221; the "
                "same refusal feature 222 makes against a NaN score)"
            )
        if reading == -math.inf:
            raise PolicyBudgetError(
                f"a statistical budget cannot be -inf: -∞ names no quantity a "
                f"reading takes (an overspent episode reads a finite negative "
                f"number, which this type does accept). Got {value!r} — a "
                f"budget of negative infinity is a configuration fault rather "
                f"than a spend (feature 221)"
            )
        return super().__new__(cls, reading)

    def __setattr__(self, name: str, value: object) -> None:
        """Refuse every assignment — a reading once taken does not move.

        The guard feature 226 draws around the beta scalar, restated for the
        budget: what the episode's statistical spend was when the reading was
        taken is what it was, and a reading a caller could reassign would be a
        budget the policy shaped rather than the one it earned.
        """
        raise PolicyBudgetError(
            f"a statistical budget is a reading of how much of the episode's "
            f"statistical budget remains and cannot be reassigned or extended "
            f"(attempted `budget.{name} = {value!r}`): the figure is what the "
            f"campaign's charges said at the moment it was read, and a value "
            f"that moved would be a budget the policy shaped rather than the "
            f"one it earned (feature 221; the boundary feature 226 draws "
            f"around the beta scalar)"
        )

    def __delattr__(self, name: str) -> None:
        """Refuse deletion — there is nothing here to remove (feature 221)."""
        raise PolicyBudgetError(
            f"a statistical budget carries its figure and nothing to delete "
            f"(attempted `del budget.{name}`): the reading is what it was and "
            f"cannot be hollowed out after the fact (feature 221)"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"StatisticalBudget({float(self)!r})"


@dataclass(frozen=True, slots=True)
class BudgetAccount:
    """A campaign's statistical budget as it stands — the allowance and the charges.

    The **runtime's** object, and deliberately not the policy's: it holds the
    allowance *and* the charges, so it answers :attr:`spent` — the one number
    docs §10.2 withholds from a policy (feature 224).  What
    ``question.budget_remaining()`` hands over is :attr:`remaining`, a
    :class:`StatisticalBudget` carrying nothing but the figure; the audience
    split this module keeps is the one feature 217/223 draw between the question
    and the prefix view, applied to the budget.

    **It reads the directive and only the directive.**  :attr:`charges` is the
    sequence of §8's ``charges_budget`` values, one per trial, in the order the
    charges were read — and nothing else is kept from the rows.  The epoch, the
    outcome, the node, the units and the provenance triple are other features'
    facts (§8's ``K_effective`` per epoch is feature 93's; §8's unit is feature
    89's), and copying them here would be a second ledger free to drift from
    the first.  This is also why :attr:`charged` is a *count* and never a sum
    of units: a five-fold evaluation is one hypothesis tested against the same
    forward returns, so it charges this budget exactly one — the arithmetic
    feature 93 already uses, restated rather than reinvented.

    **It knows which rows charged and not which rows were null.**  The
    directive is opaque by construction (§7.2: *"the caller learns whether to
    debit statistical budget without learning why"*), so an uncharged row is
    spelled :attr:`uncharged` and never "null": this module cannot tell a
    planted null from a real trial that happened not to charge, and naming one
    would be inventing the label the barrier exists to withhold.

    Frozen and validated at construction, so an account that exists is one the
    doctrine could have produced: the allowance is a non-negative real or
    :data:`UNBOUNDED_BUDGET`, and every charge is a genuine :class:`bool` (or
    the ``0``/``1`` a SQLite ``BOOLEAN`` column stores — the read-path spelling
    :func:`ledger.budget.validated_charges_budget` accepts, restated here
    because a workspace member never imports a sibling's module).
    """

    #: The statistical budget the episode may spend — degrees of freedom, in
    #: :data:`STATISTICAL_UNIT`.  A non-negative real, or
    #: :data:`UNBOUNDED_BUDGET` for a deployment that configured no ceiling.
    allowance: float
    #: One §8 directive per trial the campaign charged, in read order: ``True``
    #: for a trial that consumed statistical budget, ``False`` for one that
    #: consumed compute and no degrees of freedom.  Validated and normalised in
    #: :meth:`__post_init__`, so every element is a genuine :class:`bool`.
    charges: tuple[bool, ...] = ()

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: what follows
        # is normalisation — the SQLite spelling of a directive becoming its
        # bool, and the sequence becoming a tuple — not mutation of the
        # caller's values, and it is the only write this object ever takes
        # (the discipline :class:`policy_runtime.CampaignTree` follows for its
        # own normalised fields).
        object.__setattr__(self, "allowance", _validated_allowance(self.allowance))
        object.__setattr__(
            self,
            "charges",
            tuple(_validated_directive(charge) for charge in tuple(self.charges)),
        )

    # -- the two spends, kept apart ---------------------------------------

    @property
    def charged(self) -> int:
        """How many trials spent statistical budget — the count, never a sum.

        The feature's arithmetic, in one line: §8's directive decides, one
        charged trial is one degree of freedom, and §8's ``charge_units``
        (which the ledger member's own module states *"prices compute"*) is
        deliberately not consulted.  A cross-validated evaluation that ran five
        folds and charged budget spends **one** — the reading feature 93
        already takes of the same column, restated for the budget a policy is
        handed rather than reinvented as a weighted sum.
        """
        return sum(1 for charge in self.charges if charge)

    @property
    def evaluations(self) -> int:
        """How many trials the charges record — the compute side of the plane.

        Every row here is an evaluation that ran, and every one consumed the
        machine (§5.2's cgroup plane, feature 162/163's budgets, the agent's
        calls).  It is reported because the feature's sentence is a *contrast*
        and a contrast needs both terms visible: prd §123's *"a null node's
        signal was never compared to real forward returns, so it consumes agent
        calls and CPU but **not** degrees of freedom"* is the difference between
        this figure and :attr:`charged`, and a module that could only report one
        of them could not show it is reporting the right one.
        """
        return len(self.charges)

    @property
    def uncharged(self) -> int:
        """Trials that consumed compute and no statistical budget.

        The difference prd §123 names, as a count — and spelled *uncharged*
        rather than *null* on purpose.  The directive says a row did not spend
        degrees of freedom and never says why (§7.2: it is *"a directive, not a
        label… the only bit that crosses the barrier"*), so this module is not
        entitled to call those rows nulls: it knows what they did not spend,
        which is exactly what the honest name says.
        """
        return self.evaluations - self.charged

    # -- the reading -------------------------------------------------------

    @property
    def remaining(self) -> StatisticalBudget:
        """The statistical budget left — feature 221's reading, as a value.

        ``allowance - charged``, in :data:`STATISTICAL_UNIT`: the allowance the
        deployment stated, less one per trial whose §8 directive says it spent
        statistical budget.  A negative result is returned as it falls rather
        than floored at zero — an overspent campaign reads a negative number,
        and flooring it would hide the one state §15 makes an operational alarm
        (*"Sequestered epochs exhausted | Ledger usage count ≥ 3 | **Stop.**"*).

        The value is a :class:`StatisticalBudget`, so the figure arrives
        carrying its denomination — the whole of "statistical rather than
        compute" — and carrying nothing else: no allowance, no charge list, no
        spend, which is what makes it safe to hand a policy under feature 224.

        An ``int`` allowance is read as the float it equals (``10`` and ``10.0``
        are one budget), and the reading of an :data:`UNBOUNDED_BUDGET`
        allowance stays infinite however many trials charged — ``inf`` less any
        finite count is still ``inf``, so a deployment that stated no ceiling
        cannot be brought to a stop by arithmetic it never agreed to.
        """
        # No conversion and no guard: ``allowance`` was normalised to a float by
        # ``_validated_allowance`` and ``charged`` is a non-negative int, so the
        # subtraction is already float arithmetic on a validated magnitude. The
        # ``inf`` case falls out of it — ``inf`` less any finite count is still
        # ``inf`` — which is why an unstated ceiling cannot be brought to a stop
        # by arithmetic the deployment never agreed to.
        return StatisticalBudget(self.allowance - self.charged)

    @property
    def exhausted(self) -> bool:
        """Whether the statistical budget is spent — the reading as a flag.

        ``remaining <= 0``, spelled for the caller that wants the fact and not
        the number — a replay loop deciding whether to open another round, an
        operator surface rendering §15's stop, and the caller that would
        otherwise compare a :class:`StatisticalBudget` against zero in its own
        words.  Exactly-at-zero is exhausted: the next charged trial would
        overspend, so there is no budget left to spend.
        """
        return self.remaining <= 0

    @property
    def unit(self) -> str:
        """The resource this account meters — :data:`STATISTICAL_UNIT`.

        The denomination as a readable fact, so a caller (or an operator audit)
        can ask *"what is this figure in?"* of the object rather than of a
        docstring, and get the one answer this member gives.  It is a constant
        rather than a parameter: an account that could be denominated in
        something else would be an account that could be a compute budget, and
        the feature's sentence is that this verb is not one.
        """
        return STATISTICAL_UNIT


def budget_account(allowance: Any, rows: Iterable[Any] = ()) -> BudgetAccount:
    """Read a campaign's charge rows into its statistical budget account.

    The one factory, and the whole of feature 221's read: an allowance and the
    trials the campaign charged, as a :class:`BudgetAccount` that answers
    :attr:`~BudgetAccount.remaining`.  Duck-typed like every seam in this
    member — a row is any object carrying §8's directive as a
    ``charges_budget`` attribute, which is the shape
    :class:`ledger.record.TrialLedgerRecord`, :class:`ledger.debit`'s request
    body and :class:`evaluator`'s own charge records all already speak, so the
    seam is satisfied with no adapter and this member imports no sibling to
    name it.  A row is read for its directive **and nothing else**: the epoch
    is feature 93's key, the unit is feature 89's cost, and copying either here
    would be a second ledger.

    ``allowance`` is the statistical budget the deployment states for the
    episode.  It is *stated* rather than derived because no document fixes a
    number: the system's statistical allowance is a deployment fact of the same
    kind as the import ceiling (feature 167), the cgroup plane (feature 162)
    and the legal theme set (feature 241) — a claim a reviewer can read, not a
    literal in a launcher.  A caller that has not stated one passes
    :data:`UNBOUNDED_BUDGET` and gets an account that answers it.

    Two refusals guard the read, and both are aimed at the way this feature is
    defeated rather than at a caller's convenience:

    * **a row that cannot say whether it charged budget is refused**, naming
      the row — the stance :func:`ledger.budget.validated_charges_budget` takes
      on its side of the same column, for the same reason: a row ``K_effective``
      could not classify is a row no audit can classify, and skipping it is the
      one error direction that *understates* the spend.  A row carrying §8's
      ``charge_units`` but not the directive is refused with that stated
      explicitly, because it is the mistake this feature exists to catch — the
      caller is holding a **compute** measurement (*"1.0 default; CV folds may
      cost more"*, feature 89) and asking for a statistical one;
    * **an allowance that is not an amount of budget is refused** — a negative
      number, a NaN, a non-number — because an allowance below zero names no
      budget and a mistyped configuration that becomes a silent episode is what
      the check exists for (feature 226's rule for its own scalar).

    Every refusal is :class:`~policy_runtime.PolicyBudgetError`, so "the
    allowance is not an amount", "the row cannot say" and "a bare number names
    no resource" are one law read at three moments, and a caller catches the
    read's failure with the same ``except`` it catches the reading's.

    Pure: no store, no clock, no configuration beyond the arguments, and no
    interpreter state — the account is a function of the allowance and the rows
    it was handed, so two reads of one campaign's charges are equal values.
    """
    return BudgetAccount(
        allowance=allowance,
        charges=tuple(_directive_of(row) for row in rows),
    )


def _validated_allowance(value: Any) -> float:
    """Validate a stated allowance, returning it as the float the account holds.

    A non-negative real number, or :data:`UNBOUNDED_BUDGET`.  ``bool`` is
    refused explicitly (it is an ``int``, and an allowance that arrived as a
    truth value is a flag in a numeric field — the discipline feature 89
    applies to its own unit), a non-number is refused rather than coerced, a
    NaN is refused because it compares false against every threshold, and a
    negative number is refused because an allowance below zero is not an
    allowance.  ``+inf`` passes: it *is* the statement "no ceiling configured".
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise PolicyBudgetError(
            f"a statistical allowance is a real number of trials the episode "
            f"may charge — feature 221's budget, in the unit prd §705 names as "
            f"the statistical one; got {value!r} ({type(value).__name__}). An "
            f"allowance that is not a real number names no amount to spend, "
            f"and the number a deployment states is the whole of what this "
            f"account can report against"
        )
    try:
        allowance = float(value)
    except (OverflowError, ValueError, TypeError) as unconvertible:
        # ``numbers.Real`` does not promise a float can carry the value — an
        # ``int`` of arbitrary precision is a ``Real`` and ``float(10**400)``
        # raises :class:`OverflowError`. Translated rather than propagated, for
        # the reason :meth:`StatisticalBudget.__new__` states: a bare
        # ``OverflowError`` escaping this member is an exception a caller
        # holding the member's one base class does not catch.
        raise PolicyBudgetError(
            f"a statistical allowance must be a magnitude a float can carry — "
            f"got {value!r} ({type(value).__name__}), which float() cannot "
            f"convert ({unconvertible!r}). The allowance is how many trials the "
            f"episode may charge and is compared against a running count, so a "
            f"magnitude beyond floating point is a ceiling no account could "
            f"report against (feature 221)"
        ) from unconvertible
    if math.isnan(allowance):
        raise PolicyBudgetError(
            f"a statistical allowance cannot be NaN: it compares false against "
            f"every threshold, so an account built on it would answer a "
            f"remaining budget no policy could test and no operator could "
            f"render (feature 221). Got {value!r}"
        )
    if allowance < 0:
        raise PolicyBudgetError(
            f"a statistical allowance cannot be negative: an allowance is how "
            f"much of the episode's statistical budget there is, and a "
            f"negative one is a spend wearing an allowance's name — an "
            f"overspent campaign is what the *reading* reports (a negative "
            f"remaining), never what the allowance says (feature 221). Got "
            f"{value!r}"
        )
    return allowance


def _validated_directive(value: Any) -> bool:
    """Validate one §8 directive, returning it as the :class:`bool` it stores.

    A genuine :class:`bool` — the form a live read hands over — is returned
    as-is.  The ``0``/``1`` a SQLite ``BOOLEAN`` column stores is coerced, since
    a stored directive read back as an ``int`` is the column's own spelling and
    not a drifted value.  Anything else — a ``2``, ``None``, text — is refused,
    because a row that cannot say whether it charged budget is a row no audit
    can classify, and the safe-looking default (count it as uncharged) is the
    one that *understates* the spend — the single direction an honest counter
    must not move by accident.

    Restated here rather than imported: the check is
    :func:`ledger.budget.validated_charges_budget`'s, on the same column, for
    the same reason — and a workspace member never imports a sibling member, so
    the two members state the one rule each owns the read of.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise PolicyBudgetError(
        f"a charge row's {_DIRECTIVE_FIELD!r} must be a bool — §8's opaque "
        f"budget directive, True when the trial consumed statistical budget "
        f"and False when it did not; got {value!r} ({type(value).__name__}). "
        f"A row that cannot say whether it charged statistical budget is a row "
        f"no audit can classify, and reading it as uncharged would understate "
        f"the spend — the one direction an honest count must never move by "
        f"accident (feature 221, §7.2)"
    )


def _directive_of(row: Any) -> bool:
    """Read one charge row's §8 directive — the account's one read of a row.

    The one place a row becomes a directive, so the rule that a row must *say*
    whether it charged budget has one implementation.  A row that carries
    §8's ``charge_units`` — the column the ledger member's own module states
    *"prices compute"* — but not the directive is refused with that stated
    explicitly: the caller has a compute measurement in hand, and reporting it
    as a statistical spend is the substitution prd §705 records the system as
    having already made once.

    Both reads are guarded, because a *row* is a caller's object and either
    attribute may be a property that raises — a lazy record whose backing store
    is gone, a computed field over state that is now absent.  A bare exception
    escaping here would hand a caller catching the member's one base class an
    exception it does not catch, and worse, it would escape from a *set* of rows
    where one bad row must not be silently skipped or silently counted.  Each
    read's own failure is translated, naming which attribute failed, so the
    caller learns whether the row could not say or could not be asked.
    """
    # Both reads sit under one handler, and the second only happens when the
    # first came back absent — so there is no path here that swallows a
    # failure.  Reading ``charge_units`` separately *after* the refusal would
    # mean either catching a second exception and discarding it (a blind catch
    # whose failure would replace the real refusal) or letting it escape as a
    # bare exception from a seam this member owns.  One handler, translating
    # whichever read failed, is the honest shape.
    try:
        directive = getattr(row, _DIRECTIVE_FIELD, _MISSING)
        units = (
            getattr(row, _UNIT_FIELD, _MISSING) if directive is _MISSING else _MISSING
        )
    except Exception as unreadable:  # any failure to read a row is this law's
        raise PolicyBudgetError(
            f"a charge row could not be read: got {row!r} "
            f"({type(row).__name__}), one of whose budget attributes raised "
            f"{unreadable!r}. §8's {_DIRECTIVE_FIELD!r} says whether the trial "
            f"consumed statistical budget, and a row that cannot be asked is a "
            f"row no audit can classify — counting it as uncharged would "
            f"understate the spend and counting it as charged would invent a "
            f"degree of freedom the campaign never spent, so neither is taken "
            f"(feature 221, §7.2)"
        ) from unreadable
    if directive is _MISSING:
        carries_units = units is not _MISSING
        if carries_units:
            raise PolicyBudgetError(
                f"a charge row carries {_UNIT_FIELD!r} and no "
                f"{_DIRECTIVE_FIELD!r}: got {row!r} "
                f"({type(row).__name__}). §8's {_UNIT_FIELD!r} prices what the "
                f"evaluation cost to run — '1.0 default; CV folds may cost "
                f"more' — and the ledger member's own module states that it "
                f"prices compute; it does not say whether the trial consumed "
                f"statistical budget, which is the one thing "
                f"budget_remaining() reports (feature 221). prd §705 records "
                f"this substitution being made once already: the paper's "
                f"'β₁ N (agent calls)' was replaced by 'β₁ · trials charged "
                f"(statistical budget)'. Hand over rows carrying §8's "
                f"{_DIRECTIVE_FIELD!r} directive, or state a "
                f"{STATISTICAL_UNIT!r} figure directly"
            )
        raise PolicyBudgetError(
            f"a charge row must carry §8's {_DIRECTIVE_FIELD!r} directive — "
            f"the opaque bit the null oracle returns alongside the target "
            f"series, True when the trial consumed statistical budget and "
            f"False when it did not — got {row!r} ({type(row).__name__}), "
            f"which carries none. A row that cannot say whether it charged "
            f"budget is a row no audit can classify: counting it as uncharged "
            f"would understate the spend, and counting it as charged would "
            f"invent a degree of freedom the campaign never spent "
            f"(feature 221, §7.2)"
        )
    return _validated_directive(directive)
