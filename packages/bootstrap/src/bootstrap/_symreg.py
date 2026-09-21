"""The symbolic regression world — feature 183's known target expressions.

app_spec.xml, "Bootstrap Worlds", feature 183: *System exposes a symbolic
regression world, which returns a ground-truth score against known target
expressions.*  docs/nullius-tech-architecture.md §10.6 names the domain in
its own tree — ``symreg/  # symbolic regression against known target
expressions`` — third of the three authored branches, and states the
constraint every one of them answers to: *"Each exposes the **same**
``question.*`` API as a financial campaign, so a policy is portable
without modification."*

**Symbolic regression, and what makes this world one.**  Symbolic
regression searches the space of *expressions* for one that fits data —
the object of the search is structure, not coefficients.  So a node of
this world is a candidate **expression structure**: a small sum of terms
over the world's features, addressed as a point of a lattice exactly the
way a hyperparameter setting is in :mod:`bootstrap._world`.  A term is a
monomial — one feature (``x0``), the square of one feature (``x2^2``),
or the product of two (``x2*x3``) — and the four axes of the lattice
choose which monomials the candidate carries:

* **``linear``** — the block of leading features entering on their own:
  none, ``x0``, or ``x0+x1``;
* **``curvature``** — the one square term: none, ``x2^2``, or ``x4^2``;
* **``product``** — the one pairwise term: none, ``x0*x1``, or ``x2*x3``;
* **``spurious``** — terms the truth never carries: none, ``x5``, or
  ``x5+x5^2``.

One monomial representation spells all four: a term is a tuple of feature
indices to multiply, ``()``-free and rendered by one function, so the
setting, the target and the design matrix all speak one vocabulary and
cannot drift into three.

**The target is known because it is published.**  The feature's own
clause is *"against known target expressions"*, plural, and the world
answers it twice over.  Each world *draws* its target from its seed — a
deterministic, content-addressed choice of one square feature, one pair,
one linear block and each term's sign, in the same integer-hash discipline
as every other number a bootstrap world contains (:mod:`bootstrap.
_stream`), so a pool of worlds carries a *family* of targets, no two
alike in address, every one reproducible from its seed alone.  And each
world *publishes* the one it drew: :attr:`SymbolicRegressionWorld.target`
is the whole truth, spelled as a :class:`TargetExpression` a caller can
read, evaluate and audit — the exact stance the hyperparameter world
takes for its own model (:data:`~bootstrap.LINEAR_COEFFICIENTS` and
friends are published because §10.6's bootstrap worlds *"are the ones
whose answer is known"*).  A caller that wants a *specific* expression
may plant one instead, and the world refuses a target its lattice cannot
express — see :class:`TargetExpression`.

**The label is the score of the structure, honestly completed.**  What a
policy proposes is structure; what the world adds to make the structure a
*model* is the affine coefficients, fitted by ordinary least squares on
the training split — the standard linear-scaling completion of a symbolic
candidate, and the one that keeps the label a function of the structure
alone: two policies reaching one cell hold the same completed model
whatever path they took.  The ground-truth score is that model's held-out
``R²`` on data drawn from the target with noise — :meth:`SymbolicRegression
World.label` returns the same :class:`~bootstrap._fit.FitResult` shape
the hyperparameter world returns, computed by the same
:func:`~bootstrap._fit.fit_and_score` in the same exactly-rounded
arithmetic, so a symreg node's score and an hpo node's score are the same
*kind* of number and a policy compared across both pools is compared on
one scale.

**The lattice is deceptive on purpose.**  Two of the three structural
axes carry a *wrong* middle value — ``x2^2`` sits between none and the
``x4^2`` a world whose target squares x4 is waiting for, ``x0*x1``
between none and ``x2*x3`` — so a policy that walks one step up an axis
and stops at the first thing that sounds like progress lands on a term
the truth does not carry, and the world answers the score of a structure
that added variance and recovered nothing.  That is the honest shape of
symbolic regression as a search problem: the expression that *reads*
right is not the expression that *predicts* right, and the held-out score
is the only witness.  The ``spurious`` axis is the mirror lesson — terms
no target carries, priced in variance the holdout sees and the training
split does not — and is deliberately the quietest of the four, for the
same reason the hyperparameter world's ``standardize`` axis is: a lattice
where every axis paid equally would be a lattice where search policy does
not matter (see that module's *"the axes are not independent"*).

**The seams are the category's, ridden not rebuilt.**  The world owns the
same answer surface :func:`~bootstrap.question_for` duck-types over —
``label``, ``legal_moves``, ``legal_roots``, ``canonical_node``,
``steps``, ``world_id`` — so the identical :class:`~bootstrap.
BootstrapQuestion` wraps it with no change to feature 184's module, and
:func:`~bootstrap.ground_truth` labels every cell through the same
``cells()`` / ``label()`` / ``world_id`` surface it reads off every other
bootstrap world.  The one thing the shared adapter cannot answer for this
domain is the *family*: §11.1 exposes ``theme_root`` in ``meta()`` because
the overfit signature is only partly family-invariant, and a symbolic
regression node is a member of the ``symreg`` family, not the ``hpo`` one
— so :class:`SymbolicQuestion` inherits feature 184's adapter whole and
re-answers exactly the one method whose content is per-domain, :meth:`.
meta`.  Everything a policy calls — ``observed``, ``legal_actions``,
``legal_roots``, ``probe_batch``, ``budget_remaining``, ``commit`` — is
the inherited, unmodified interface.

**What this module deliberately does not ship.**  It draws no pool and
seats no rows: feature 188's writer authors the replay pool, and the
``domain`` column its table already carries is where a ``symreg`` row
will join it (:data:`SYMREG_DOMAIN` is the value, spelled by §10.6's own
tree).  It charges no budget and consults no clock (§10.6's zero-cost,
market-time-free clauses, statements about the category).  It holds no
reveal history — a world whose answers depended on how often it had been
asked would not be a ground truth, which is why the reveal bookkeeping
lives in the question and the *one* thing this world adds to the
hyperparameter world's shape is the published target it is scored
against.

Stdlib only, and import-cheap: :mod:`enum`, :mod:`math` and the member's
own stream, fit and split primitives, so the factory's scan — which
imports this package to fire its ``@register`` — pays nothing for the
domain.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, ClassVar

from ._fit import FitResult, fit_and_score
from ._question import BootstrapQuestion, CellMeta
from ._stream import mix64, normal, uniform
from ._world import split_indices
from .errors import BootstrapScoringError, BootstrapWorldError

__all__ = [
    "CURVATURE_MAGNITUDE",
    "CURVATURE_TERMS",
    "LINEAR_MAGNITUDES",
    "LINEAR_TERMS",
    "PRODUCT_MAGNITUDE",
    "PRODUCT_TERMS",
    "SPURIOUS_TERMS",
    "SYMBOLIC_AXES",
    "SYMBOLIC_AXIS_ORDER",
    "SYMREG_COMPONENT_NAME",
    "SYMREG_DOMAIN",
    "SYMREG_FEATURE_COUNT",
    "SYMREG_INTERCEPT",
    "SYMREG_NOISE_SCALE",
    "SYMREG_RIDGE",
    "SYMREG_ROWS",
    "SYMREG_SEED",
    "SYMREG_THEME_ROOT",
    "SYMREG_WORLD_ID",
    "ExpressionSetting",
    "SymbolicAxis",
    "SymbolicDataset",
    "SymbolicQuestion",
    "SymbolicRegressionWorld",
    "TargetExpression",
    "canonical_symbolic_node_id",
    "decode_symbolic_node_id",
    "encode_symbolic_node_id",
    "generate_symbolic_dataset",
    "symbolic_setting_dimensions",
    "symreg_question_for",
    "target_for_seed",
]

#: How many features the world's fixed dataset has.  Six, the same width
#: as the hyperparameter world's, because the vocabulary above spans
#: exactly six: the pairs use ``x0..x3``, the squares ``x2`` and ``x4``,
#: the spurious axis ``x5`` — every feature is load-bearing to some axis,
#: and a seventh would be a column no term of the lattice can reach.
SYMREG_FEATURE_COUNT = 6

#: How many observations the fixed dataset holds.  The hyperparameter
#: world's own row count, for the same reason it is fixed there: the
#: dataset is the world's *fixed* half, and the interleaved two-thirds
#: split (:func:`~bootstrap._world.split_indices`, shared) seats 64 train
#: rows against 32 held-out — the same holdout precision on both domains,
#: so a sensitivity read off one pool and a sensitivity read off the
#: other carry the same sampling error.
SYMREG_ROWS = 96

#: The standard deviation of the observation noise, in units of the
#: target's own spread.  Large enough that the *partial* structures —
#: the cells that recover one load-bearing term and miss the other — sit
#: near the published evidential bar (:data:`~bootstrap.DISCOVERY_BAR`)
#: rather than safely above it, so where the class boundary falls is a
#: fact about the world's drawn coefficients rather than a constant of
#: the domain; small enough that the cell carrying the target's whole
#: structure clears the bar on every seed of the pool band (pinned by
#: this member's tests over that band, the way :data:`~bootstrap.
#: _world.NOISE_SCALE` is pinned).
SYMREG_NOISE_SCALE = 1.2

#: The intercept every drawn target carries.  A constant rather than a
#: drawn one: the intercept is completed by the least-squares fit like
#: every other coefficient, so varying it would vary nothing a policy can
#: observe, and a published constant keeps the drawn target's *structure*
#: the only thing the seed chooses.
SYMREG_INTERCEPT = 1.0

#: The magnitudes of the drawn target's linear coefficients, in feature
#: order.  Small by design: the linear block alone explains a fraction of
#: the target's variance far below the bar, so a cell that has recovered
#: only the linear terms is a null and the two structural axes carry the
#: world's difficulty between them.
LINEAR_MAGNITUDES = (0.5, 0.35)

#: The magnitude of the drawn target's square term — one of the two
#: load-bearing coefficients, sized against :data:`PRODUCT_MAGNITUDE` so
#: that missing *either* structural term costs roughly half the variance
#: and neither axis can be skipped on the way to the optimum.
CURVATURE_MAGNITUDE = 1.8

#: The magnitude of the drawn target's pairwise term — the other
#: load-bearing coefficient, same sizing argument.
PRODUCT_MAGNITUDE = 2.6

#: The ridge every symreg fit is solved with — a constant of the world,
#: not an axis of the lattice.  The hyperparameter world makes the ridge
#: a *searched* dimension because a ridge penalty is a modelling choice
#: there; here the search object is structure and the ridge is the
#: numerical floor that keeps every structure answerable — a positive
#: constant on the diagonal makes the completed fit total whatever the
#: candidate's columns, the same guarantee :data:`~bootstrap.
#: DEFAULT_RIDGE` makes for that lattice, held fixed so two structures'
#: scores differ by structure alone and nothing else.
SYMREG_RIDGE = 0.01

#: The seed of the committed world — the one the component builder
#: composes.  A stable integer in the committed world's own convention
#: (the date the domain was authored), so the committed world and the
#: committed tests describe one world.
SYMREG_SEED = 20260922

#: The world id of the committed symbolic regression world — the
#: ``bootstrap-<domain>-<date>`` convention the hyperparameter world's
#: own id (:data:`~bootstrap.HYPERPARAMETER_WORLD_ID`) sets, with the
#: domain spelled by §10.6's tree so a report reading the two pools apart
#: sees a symreg node as a member of its domain.
SYMREG_WORLD_ID = "bootstrap-symreg-20260922"

#: The domain this world belongs to, in §10.6's own tree vocabulary
#: (``symreg/  # symbolic regression against known target expressions``).
#: A value this member publishes and a later pool authoring seats under
#: the ``domain`` column the bootstrap world table already carries — the
#: column exists so this domain could join it (see :mod:`bootstrap._pool`'s
#: "What this module deliberately does not ship").
SYMREG_DOMAIN = "symreg"

#: The structural family a symreg node belongs to, reported on every
#: :class:`~bootstrap.CellMeta` this domain's question hands a policy.
#: §11.1's family conditioning is the reason the value exists: the
#: overfit signature is only partly family-invariant, a policy writes
#: family-conditional thresholds, and a symbolic regression node must be
#: legible to that policy as ``symreg`` — not folded into the
#: hyperparameter domain's family, which is the mistake a shared adapter
#: that hardcoded one root would make (see :class:`SymbolicQuestion`).
SYMREG_THEME_ROOT = "symreg"

#: The component name this domain registers under — its own name rather
#: than a second face on ``"bootstrap"``, the convention the pool's own
#: seat (:data:`~bootstrap.POOL_COMPONENT_NAME`) states: the world seat
#: answers *what is the composed bootstrap world?*, the pool seat *what
#: is the composed bootstrap pool?*, and this one *what is the composed
#: symbolic regression world?* — three facts on different lifecycles that
#: a caller asks for by name, and a registry key is a name.
SYMREG_COMPONENT_NAME = "bootstrap-symreg"


class SymbolicAxis(enum.StrEnum):
    """The four axes of the symbolic lattice, in the order steps compose.

    A :class:`~enum.StrEnum` for the reason
    :class:`~bootstrap.HyperparameterAxis` is: the axis a step moved is
    *read* — by a policy reasoning about which term to try next, by a
    test asserting the lattice's shape — and a bare ``str`` would let a
    typo address an axis that does not exist while comparing equal to the
    one that does.  The declaration order is load-bearing and is
    :data:`SYMBOLIC_AXIS_ORDER`'s: the step vector that addresses a node
    is spelled in this order, so the addressing is stable and a reader
    can see at a glance which dimension the third entry moves.
    """

    #: The block of leading features entering the expression on their own.
    LINEAR = "linear"

    #: The one square term the expression may carry.
    CURVATURE = "curvature"

    #: The one pairwise product term the expression may carry.
    PRODUCT = "product"

    #: The terms the truth never carries — the overfitting direction.
    SPURIOUS = "spurious"


#: The axes in declaration order — the one spelling of the vector's layout.
SYMBOLIC_AXIS_ORDER: tuple[SymbolicAxis, ...] = (
    SymbolicAxis.LINEAR,
    SymbolicAxis.CURVATURE,
    SymbolicAxis.PRODUCT,
    SymbolicAxis.SPURIOUS,
)

#: The legal levels of each axis, in ascending order.  Every axis declares
#: the same three — ``0`` carries nothing, ``1`` and ``2`` carry the two
#: structural choices the axis names — which is what makes each axis's
#: *middle* value a wrong answer sitting between two honest ones: level 1
#: is a real term, spelled in the vocabulary, that a world whose target
#: chose level 2 does not carry.  Levels rather than the terms themselves
#: so the value type stays a small ordered tuple of integers, the shape
#: the hyperparameter lattice proved; the term each level *means* is the
#: tables below, and a setting renders them through one function.
SYMBOLIC_AXES: dict[SymbolicAxis, tuple[int, ...]] = {
    SymbolicAxis.LINEAR: (0, 1, 2),
    SymbolicAxis.CURVATURE: (0, 1, 2),
    SymbolicAxis.PRODUCT: (0, 1, 2),
    SymbolicAxis.SPURIOUS: (0, 1, 2),
}

#: What each ``linear`` level carries: no lone features, ``x0``, or
#: ``x0`` and ``x1``.  A growing block rather than a choice of blocks so
#: the axis is *ordered by its own meaning* — level 2 strictly contains
#: level 1 — and a walk up the axis is a widening expression rather than
#: a different one.
LINEAR_TERMS: tuple[tuple[tuple[int, ...], ...], ...] = (
    (),
    ((0,),),
    ((0,), (1,)),
)

#: What each ``curvature`` level carries: no square, ``x2^2``, or
#: ``x4^2``.  Two different features, not a size — the axis teaches
#: *which* curvature the truth carries, and a policy that stops at level
#: 1 on a world whose target squares ``x4`` has added a column and
#: recovered nothing.
CURVATURE_TERMS: tuple[tuple[tuple[int, ...], ...], ...] = (
    (),
    ((2, 2),),
    ((4, 4),),
)

#: What each ``product`` level carries: no pair, ``x0*x1``, or
#: ``x2*x3`` — the same wrong-middle structure as the curvature axis, on
#: the interaction term.
PRODUCT_TERMS: tuple[tuple[tuple[int, ...], ...], ...] = (
    (),
    ((0, 1),),
    ((2, 3),),
)

#: What each ``spurious`` level carries: nothing, ``x5``, or ``x5`` and
#: ``x5^2``.  No drawn target ever carries these terms — the axis is pure
#: width, the direction a candidate grows *away* from the truth, and the
#: one the held-out split prices while the training split rewards it.
SPURIOUS_TERMS: tuple[tuple[tuple[int, ...], ...], ...] = (
    (),
    ((5,),),
    ((5,), (5, 5)),
)

#: Every monomial the lattice can express, mapped to the axis whose level
#: carries it — the universe a target's terms must live in for the world
#: to hold a cell that recovers them.  Built from the tables rather than
#: spelled again, so a table edit cannot leave the map behind.
_MONOMIAL_AXIS: dict[tuple[int, ...], SymbolicAxis] = {
    monomial: axis
    for axis, table in (
        (SymbolicAxis.LINEAR, LINEAR_TERMS),
        (SymbolicAxis.CURVATURE, CURVATURE_TERMS),
        (SymbolicAxis.PRODUCT, PRODUCT_TERMS),
        (SymbolicAxis.SPURIOUS, SPURIOUS_TERMS),
    )
    for level in table
    for monomial in level
}


def _render_monomial(monomial: tuple[int, ...]) -> str:
    """Render one monomial as the text a report and a refusal speak.

    ``x0``, ``x2^2``, ``x0*x1`` — the one spelling of a term, used by the
    setting's text, the target's text and the refusals below, so the
    three cannot name one term three ways.
    """
    factors = []
    for feature in monomial:
        factors.append(f"x{feature}")
    if len(factors) == 2 and factors[0] == factors[1]:
        return f"{factors[0]}^2"
    return "*".join(factors)


def _validated_monomial(value: Any, *, owner: str) -> tuple[int, ...]:
    """Check a monomial and return it as a canonical tuple of indices.

    The one spelling of what a term must be — one or two features of the
    dataset, a pair either square (equal) or ordered (strictly ascending)
    — shared by :class:`TargetExpression`'s validation so a term the
    setting tables hold and a term a target holds are checked by the same
    rule.  A ``bool`` is refused where a feature index belongs for the
    reason :class:`~bootstrap.HyperparameterSetting` refuses one on an
    axis: ``True`` is ``1`` in Python, and a flag would silently name a
    feature rather than failing.
    """
    if not isinstance(value, tuple) or not 1 <= len(value) <= 2:
        raise BootstrapWorldError(
            f"{owner} carries a term of one or two features — got "
            f"{value!r}; a term of this world's vocabulary is a lone "
            "feature (x0), a square (x2^2) or a pairwise product "
            "(x0*x1), and anything else names an expression no cell of "
            "the lattice can carry"
        )
    for feature in value:
        if isinstance(feature, bool) or not isinstance(feature, int):
            raise BootstrapWorldError(
                f"{owner} names its features by index — got {value!r}, "
                "whose entry is not an integer; a flag where an index "
                "belongs would silently name a feature rather than "
                "failing, for the reason a flag on a lattice axis is"
            )
        if not 0 <= feature < SYMREG_FEATURE_COUNT:
            raise BootstrapWorldError(
                f"{owner} names a feature of this world's dataset — got "
                f"{feature!r}, and the dataset holds "
                f"{SYMREG_FEATURE_COUNT} features (x0..x{SYMREG_FEATURE_COUNT - 1})"
            )
    if len(value) == 2 and value[0] > value[1]:
        raise BootstrapWorldError(
            f"{owner} spells a pair in ascending order (or as a square, "
            f"equal) — got {value!r}; the order is the term's canonical "
            "spelling, and two orderings of one product are one term "
            "that must not count twice"
        )
    return tuple(value)


@dataclass(frozen=True)
class TargetExpression:
    """The world's known truth — a target expression, spelled in full.

    A frozen value, because the target is the *recorded fact* a world's
    every label is measured against: two callers holding one target must
    hold the same expression, and the score of a candidate is auditable
    against it (:meth:`evaluate` is the target's own arithmetic, the
    thing :meth:`SymbolicDataset.truth_for` hands a caller who wants to
    see what the noise was hiding).

    ``terms`` is a tuple of ``(monomial, coefficient)`` pairs, sorted
    into a canonical order at construction, so a target is equal by its
    terms as a *set* — the same order-freedom a declaration and a
    labeling are built with — and ``intercept`` is the constant the
    expression adds.  The monomials are the lattice's own vocabulary,
    and construction enforces that: every term must be a monomial some
    axis's level carries, and within each axis the terms must fit inside
    one level, because a target the lattice cannot express is a target
    no cell can recover — the world would hold no oracle and the answer
    key would name a cell outside the space, which is the one
    configuration a ground-truth world must refuse rather than score
    around.  A target with no terms at all is refused for the plainer
    reason that it names no structure to find: every cell would explain
    nothing, every label would sit at the noise floor, and the world
    would be a lottery rather than a search problem.
    """

    intercept: float
    terms: tuple[tuple[tuple[int, ...], float], ...]

    def __post_init__(self) -> None:
        if isinstance(self.intercept, bool) or not isinstance(
            self.intercept, (int, float)
        ):
            raise BootstrapWorldError(
                f"a target's intercept is a real constant — got "
                f"{self.intercept!r} ({type(self.intercept).__name__}); the "
                "intercept is part of the truth a candidate is scored "
                "against, and a value that is not a number is not part "
                "of any expression"
            )
        if not math.isfinite(float(self.intercept)):
            raise BootstrapWorldError(
                f"a target's intercept is a finite constant — got "
                f"{self.intercept!r}; a non-finite truth scores no "
                "candidate honestly"
            )
        if not self.terms:
            raise BootstrapWorldError(
                "a target expression carries at least one term — an "
                "intercept alone names no structure to find, and a world "
                "whose truth is a constant would hold no search problem "
                "and no class boundary, only noise"
            )
        checked: list[tuple[tuple[int, ...], float]] = []
        seen: set[tuple[int, ...]] = set()
        for monomial, coefficient in self.terms:
            owner = "a target expression"
            term = _validated_monomial(monomial, owner=owner)
            if isinstance(coefficient, bool) or not isinstance(
                coefficient, (int, float)
            ):
                raise BootstrapWorldError(
                    f"{owner} weights {term!r} with a real coefficient — "
                    f"got {coefficient!r} ({type(coefficient).__name__}); "
                    "the weight is part of the truth the fit recovers, "
                    "and a value that is not a number weighs nothing"
                )
            if not math.isfinite(float(coefficient)):
                raise BootstrapWorldError(
                    f"{owner} weights {term!r} with a finite coefficient "
                    f"— got {coefficient!r}; a non-finite weight makes "
                    "every score a fact about the arithmetic rather than "
                    "about the structure"
                )
            if float(coefficient) == 0.0:
                raise BootstrapWorldError(
                    f"{owner} carries {_render_monomial(term)!r} at "
                    "weight 0 — a term weighted nothing names no term, "
                    "and a target that held one would be spelled longer "
                    "than the expression it is"
                )
            if term in seen:
                raise BootstrapWorldError(
                    f"{owner} carries {_render_monomial(term)!r} twice — "
                    "two weights on one monomial are one term of the "
                    "expression and must be spelled as one"
                )
            seen.add(term)
            checked.append((term, float(coefficient)))
        # The lattice-expressibility check: every term must be a monomial
        # one of the axis tables carries, and per axis the terms must fit
        # inside a single level — the oracle cell is the cell at those
        # levels, so a target that failed this would be a truth the space
        # cannot reach and no policy could ever recover.
        per_axis: dict[SymbolicAxis, set[tuple[int, ...]]] = {}
        for term, _ in checked:
            axis = _MONOMIAL_AXIS.get(term)
            if axis is None:
                raise BootstrapWorldError(
                    f"the lattice cannot express the term "
                    f"{_render_monomial(term)!r} — this world's vocabulary "
                    f"is the four axis tables (linear over x0/x1, "
                    "curvature over x2^2/x4^2, product over x0*x1/x2*x3, "
                    "spurious over x5); a target outside it names an "
                    "expression no cell can recover, so the world would "
                    "hold no oracle and its answer key would point "
                    "outside its own space"
                )
            per_axis.setdefault(axis, set()).add(term)
        for axis, terms in per_axis.items():
            table = {
                SymbolicAxis.LINEAR: LINEAR_TERMS,
                SymbolicAxis.CURVATURE: CURVATURE_TERMS,
                SymbolicAxis.PRODUCT: PRODUCT_TERMS,
                SymbolicAxis.SPURIOUS: SPURIOUS_TERMS,
            }[axis]
            if not any(terms <= set(level) for level in table):
                spelled = ", ".join(_render_monomial(term) for term in sorted(terms))
                raise BootstrapWorldError(
                    f"the lattice cannot carry {spelled!r} together on its "
                    f"{axis.value!r} axis — the axis declares one level per "
                    "structural choice, and a target asking for two of "
                    "them names an expression no single cell can recover"
                )
        object.__setattr__(
            self, "terms", tuple(sorted(checked, key=lambda term: term[0]))
        )
        object.__setattr__(self, "intercept", float(self.intercept))

    def evaluate(self, features: tuple[float, ...]) -> float:
        """The expression's value at one feature vector — in ``fsum``.

        The truth's own arithmetic, spelled once: the dataset's
        generation and its auditable ``truth_for`` both call this rather
        than restating the expression, so the generated data and the
        published answer cannot drift (:func:`bootstrap._world.
        _model_at` is the hyperparameter world's spelling of the same
        discipline).
        """
        return math.fsum(
            (self.intercept, *(coefficient * _monomial_value(monomial, features)
                              for monomial, coefficient in self.terms))
        )

    @property
    def text(self) -> str:
        """The expression as a policy or an operator reads it.

        ``1.0 + 0.5*x0 - 0.35*x1 + 1.8*x2^2 + 2.6*x2*x3`` — the known
        target, spelled in the same monomial vocabulary the settings and
        the lattice tables speak, because a target a caller cannot read
        is not a *known* one in the feature's own sense.
        """
        parts = [f"{self.intercept:g}"]
        for monomial, coefficient in self.terms:
            sign = "-" if coefficient < 0 else "+"
            parts.append(f"{sign} {abs(coefficient):g}*{_render_monomial(monomial)}")
        return " ".join(parts)

    def row(self) -> dict[str, Any]:
        """The target as a store-shaped mapping — a fresh dict per call.

        What a report or a pool row writes down for a world's truth: the
        intercept, and each term as its rendered monomial with its
        weight.  Fresh per call, never shared, for the reason a frozen
        value's ``row()`` is always fresh.
        """
        return {
            "intercept": self.intercept,
            "terms": tuple(
                (_render_monomial(monomial), coefficient)
                for monomial, coefficient in self.terms
            ),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"TargetExpression({self.text!r})"


def _monomial_value(monomial: tuple[int, ...], features: tuple[float, ...]) -> float:
    """One monomial's value at a row — a product of its features."""
    value = 1.0
    for feature in monomial:
        value *= features[feature]
    return value


# --------------------------------------------------------------------------
# The lattice's addressing
# --------------------------------------------------------------------------


def symbolic_setting_dimensions() -> tuple[str, ...]:
    """The symbolic lattice's axes as wire spellings, in declaration order."""
    return tuple(axis.value for axis in SYMBOLIC_AXIS_ORDER)


class ExpressionSetting:
    """One point of the symbolic lattice: a level for each of the four axes.

    Immutable and *ordered* — the levels are held in
    :data:`SYMBOLIC_AXIS_ORDER`, so two settings that name one point are
    equal and hash alike whatever keyword order built them, and a set of
    them is a set of cells.  Levels are validated at construction against
    :data:`SYMBOLIC_AXES`, so a setting that holds is a setting the world
    has agreed to score; a ``bool`` is refused where a level is expected
    because ``True`` is ``1`` in Python and would silently ask for the
    lattice's first structural choice instead of failing.

    The terms a level *means* are read through the axis tables
    (:attr:`monomials`), never stored beside the levels, so the setting
    and the vocabulary cannot disagree.
    """

    __slots__ = ("_values",)

    #: The four axis tables, keyed by axis — a read-only class fact, held
    #: at class scope so every setting reads the one vocabulary.
    _TABLES: ClassVar[
        dict[SymbolicAxis, tuple[tuple[tuple[int, ...], ...], ...]]
    ] = {
        SymbolicAxis.LINEAR: LINEAR_TERMS,
        SymbolicAxis.CURVATURE: CURVATURE_TERMS,
        SymbolicAxis.PRODUCT: PRODUCT_TERMS,
        SymbolicAxis.SPURIOUS: SPURIOUS_TERMS,
    }

    def __init__(
        self,
        *,
        linear: Any = 0,
        curvature: Any = 0,
        product: Any = 0,
        spurious: Any = 0,
    ) -> None:
        requested = {
            SymbolicAxis.LINEAR: linear,
            SymbolicAxis.CURVATURE: curvature,
            SymbolicAxis.PRODUCT: product,
            SymbolicAxis.SPURIOUS: spurious,
        }
        resolved: list[Any] = []
        for axis in SYMBOLIC_AXIS_ORDER:
            legal = SYMBOLIC_AXES[axis]
            value = requested[axis]
            if isinstance(value, bool):
                raise BootstrapWorldError(
                    f"the {axis.value!r} axis is a level — got {value!r}, "
                    "which is a flag; True is 1 in Python, so a flag "
                    "would silently ask for the axis's first structural "
                    "choice instead of failing"
                )
            if value not in legal:
                raise BootstrapWorldError(
                    f"{value!r} is not a level of the {axis.value!r} axis "
                    f"— this lattice declares {', '.join(str(level) for level in legal)}"
                    f", level per structural choice; a level outside the "
                    "declaration names a term nobody agreed to score"
                )
            resolved.append(value)
        self._values = tuple(resolved)

    @property
    def values(self) -> tuple[Any, ...]:
        """The node's coordinates, in :data:`SYMBOLIC_AXIS_ORDER` — read-only."""
        return self._values

    def value(self, axis: SymbolicAxis) -> int:
        """This setting's level on ``axis``."""
        return self._values[SYMBOLIC_AXIS_ORDER.index(axis)]

    @property
    def monomials(self) -> tuple[tuple[int, ...], ...]:
        """The terms this setting's expression carries, in axis order.

        Read off the tables rather than stored, so the vocabulary and
        the setting cannot drift; the design's intercept column is not a
        monomial and is not listed.
        """
        terms: list[tuple[int, ...]] = []
        for axis, level in zip(SYMBOLIC_AXIS_ORDER, self._values):
            terms.extend(self._TABLES[axis][level])
        return tuple(terms)

    def steps(self) -> tuple[int, ...]:
        """How far each axis has moved from the canonical setting.

        One signed integer per axis, in :data:`SYMBOLIC_AXIS_ORDER` —
        the node's address, the vector a node id encodes.
        """
        return tuple(
            level - SYMBOLIC_AXES[axis][0]
            for axis, level in zip(SYMBOLIC_AXIS_ORDER, self._values)
        )

    @property
    def depth(self) -> int:
        """``Σ|step|`` — how many legal moves the setting is from the root."""
        return sum(abs(step) for step in self.steps())

    @property
    def text(self) -> str:
        """The candidate's structure as it reads: ``x0 + x1 + x2^2``.

        The terms and nothing else — the coefficients are the fit's to
        complete, and a setting that spelled weights would be spelling a
        model rather than a structure.
        """
        terms = self.monomials
        if not terms:
            return "intercept-only"
        return " + ".join(_render_monomial(monomial) for monomial in terms)

    def row(self) -> dict[str, Any]:
        """The setting as a store-shaped mapping — a fresh dict per call.

        The constructor's own keywords, so a row round-trips into a
        setting the way the hyperparameter setting's row does.
        """
        return {
            axis.value: value for axis, value in zip(SYMBOLIC_AXIS_ORDER, self._values)
        }

    def with_value(self, axis: SymbolicAxis, value: Any) -> ExpressionSetting:
        """A copy of this setting with one axis moved to ``value``.

        A fresh setting per call, never a mutated one, validated by the
        constructor like any other — a move to an out-of-lattice level
        is refused here rather than held and refused later.
        """
        values = self.row()
        values[axis.value] = value
        return ExpressionSetting(**values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExpressionSetting):
            return NotImplemented
        return self._values == other._values

    def __hash__(self) -> int:
        return hash(self._values)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        fields = [
            f"{axis.value}={value!r}"
            for axis, value in zip(SYMBOLIC_AXIS_ORDER, self._values)
        ]
        return f"ExpressionSetting({', '.join(fields)})"


def canonical_symbolic_node_id() -> str:
    """The root's node id — the all-zero step vector, derived not spelled.

    A function rather than a constant so the root's address is derived
    from the same encoder every other node's is, and the root cannot
    drift away from the lattice it roots.
    """
    return encode_symbolic_node_id((0,) * len(SYMBOLIC_AXIS_ORDER))


def encode_symbolic_node_id(steps: tuple[int, ...]) -> str:
    """Encode a step vector as the node id that addresses it.

    ``"l+2.c+1.p+0.s+0"`` — one ``<initial><sign><magnitude>`` field per
    axis in :data:`SYMBOLIC_AXIS_ORDER`, joined by dots: the same codec
    shape :func:`bootstrap.encode_node_id` spells for the hyperparameter
    lattice, with this lattice's own initials, so a symreg node id and an
    hpo node id are textually distinct kinds of address and neither
    world decodes the other's.
    """
    return ".".join(
        f"{axis.value[0]}{'+' if step >= 0 else '-'}{abs(step)}"
        for axis, step in zip(SYMBOLIC_AXIS_ORDER, steps)
    )


def decode_symbolic_node_id(node_id: str) -> tuple[int, ...]:
    """Read a symreg node id back into the step vector it encodes.

    The inverse of :func:`encode_symbolic_node_id` and as strict as it:
    a node id whose field count, axis initials, sign or magnitude this
    module's encoder cannot have produced is refused with
    :class:`~bootstrap.errors.BootstrapWorldError`, naming what was
    wrong — strict because a node id is the address a policy hands back
    at ``commit``, and a value that decoded leniently would let a commit
    name a cell the policy was never shown.
    """
    if not isinstance(node_id, str) or not node_id:
        raise BootstrapWorldError(
            f"a node id is a non-empty string — got {node_id!r} "
            f"({type(node_id).__name__}); the node id is the address a "
            "policy hands back when it commits, and an address it cannot "
            "have been given is not one this world can resolve"
        )
    fields = node_id.split(".")
    if len(fields) != len(SYMBOLIC_AXIS_ORDER):
        raise BootstrapWorldError(
            f"the node id {node_id!r} carries {len(fields)} field(s) where "
            f"this world's lattice has {len(SYMBOLIC_AXIS_ORDER)} axes "
            f"({', '.join(axis.value for axis in SYMBOLIC_AXIS_ORDER)}); a "
            "node id is one field per axis, in that order"
        )
    steps: list[int] = []
    for axis, field in zip(SYMBOLIC_AXIS_ORDER, fields):
        initial = axis.value[0]
        if len(field) < 3 or field[0] != initial or field[1] not in "+-":
            raise BootstrapWorldError(
                f"the node id {node_id!r} has a malformed field {field!r} "
                f"for the {axis.value!r} axis — a field is the axis's "
                f"initial, a sign and a magnitude, like {initial}+1"
            )
        magnitude = field[2:]
        if not magnitude.isdigit():
            raise BootstrapWorldError(
                f"the node id {node_id!r} has a non-numeric magnitude "
                f"{magnitude!r} in the {axis.value!r} field; a step is a "
                "signed integer count of positions along one axis"
            )
        step = int(magnitude)
        steps.append(-step if field[1] == "-" else step)
    return tuple(steps)


# --------------------------------------------------------------------------
# The seeded draws
# --------------------------------------------------------------------------

#: Address-space prefixes keeping the symreg world's draws in blocks of
#: the 64-bit cell space disjoint from each other and from the
#: hyperparameter world's (:mod:`bootstrap._world`'s two prefixes).
#: Spelled as large odd constants for the reason those are: two prefixes
#: differing in one bit would be mixed by the same multipliers with a
#: one-bit difference, and the finalizer's avalanche would be the only
#: thing standing between a policy and a detectable correlation between
#: two quantities.
_PREFIX_SYMREG_FEATURE = 0x6C1F55_A2D974E03B
_PREFIX_SYMREG_NOISE = 0x3E9C81_5F0B2A6D47
_PREFIX_SYMREG_TARGET = 0x77A3D9_1C6E4B0F53

#: The multiplier spreading ``(row, column)`` pairs across the feature
#: block, as in the hyperparameter world: a row-major stride larger than
#: any column count, so two pairs collide only if they are literally
#: equal.
_ROW_STRIDE = 1 << 32


def _feature_cell(token: int, row: int, column: int) -> int:
    """The cell one feature value is drawn from — ``token`` and ``(row, column)``.

    The same construction as the hyperparameter world's
    ``_feature_cell``, against this domain's own prefix: within one
    world the address arithmetic is untouched, and across worlds the
    block translates by the whole token, so two worlds of one lattice
    draw independently — and a symreg world and an hpo world sharing a
    seed draw from disjoint blocks, so the committed ids of the two
    domains never quietly share data.
    """
    address = row * _ROW_STRIDE + column
    return _PREFIX_SYMREG_FEATURE ^ token ^ (address ^ mix64(address))


def _noise_cell(token: int, row: int) -> int:
    """The cell one observation's noise is drawn from — ``token`` and ``row``."""
    return _PREFIX_SYMREG_NOISE ^ token ^ (row ^ mix64(row))


def _choice_cell(token: int, which: int) -> int:
    """The cell one target-choice draw is read from — ``token`` and ``which``.

    The target's structure is drawn from the same content-addressed
    hash as the data it will price, each choice from its own cell, so
    the target is a pure function of the seed like every other fact of
    the world — reproducible from the seed alone, independent of the
    order the choices were taken in, and disjoint from the feature and
    noise blocks.
    """
    address = which + 1
    return _PREFIX_SYMREG_TARGET ^ token ^ (address ^ mix64(address))


def target_for_seed(seed: int) -> TargetExpression:
    """Draw the known target a seed names — the world's truth, from its seed.

    A pure function of the seed, in the same discipline as
    :func:`bootstrap.generate_dataset`: the levels of the three
    structural axes (which linear block, which square, which pair —
    never level 0, so every drawn target carries both load-bearing
    terms and the oracle is a real cell), each coefficient's sign, and
    nothing else.  Two seeds may draw one target and two targets may
    share an address — the *world* is still the seed's, because the
    dataset the target is priced against is drawn from the seed too —
    and the family of targets across a pool is the "expressions" of the
    feature's own plural, every one of them lattice-expressible by
    construction because each is *built from* the lattice's own tables.
    """
    token = mix64(seed)

    def level(which: int) -> int:
        """A structural level in {1, 2} — drawn, never the empty 0."""
        return 1 + int(uniform(_choice_cell(token, which)) * 2)

    def sign(which: int) -> float:
        """A term's sign, drawn — the one degree of freedom left."""
        return -1.0 if uniform(_choice_cell(token, which)) < 0.5 else 1.0

    linear_level = level(0)
    curvature_level = level(1)
    product_level = level(2)
    terms = [
        ((feature,), sign(3 + offset) * LINEAR_MAGNITUDES[feature])
        for offset, (feature,) in enumerate(LINEAR_TERMS[linear_level])
    ]
    terms.append(
        (
            CURVATURE_TERMS[curvature_level][0],
            sign(6) * CURVATURE_MAGNITUDE,
        )
    )
    terms.append(
        (
            PRODUCT_TERMS[product_level][0],
            sign(7) * PRODUCT_MAGNITUDE,
        )
    )
    return TargetExpression(intercept=SYMREG_INTERCEPT, terms=tuple(terms))


# --------------------------------------------------------------------------
# The fixed dataset
# --------------------------------------------------------------------------


class SymbolicDataset:
    """The world's fixed dataset: features, and targets drawn from the truth.

    Rows are held as tuples in priced row order, the same shape
    :class:`bootstrap._world.Dataset` holds, and the train and holdout
    splits are indices into it through the shared
    :func:`~bootstrap.split_indices`.  ``targets`` are the observed
    values — truth plus noise — and the *truth* is available separately
    (:meth:`truth_for`), which is what makes the world's labels
    auditable: a caller can see exactly what the noise was hiding, and
    a fit's residuals against the truth are the target's own
    expression evaluated where the dataset drew its rows.
    """

    __slots__ = ("_features", "_target", "_targets", "seed")

    def __init__(
        self,
        *,
        features: tuple[tuple[float, ...], ...],
        targets: tuple[float, ...],
        target: TargetExpression,
        seed: int,
    ) -> None:
        self._features = features
        self._targets = targets
        self._target = target
        self.seed = seed

    @property
    def rows(self) -> int:
        """How many observations the world priced."""
        return len(self._features)

    @property
    def features(self) -> tuple[tuple[float, ...], ...]:
        """Every row's feature vector, in priced row order."""
        return self._features

    @property
    def targets(self) -> tuple[float, ...]:
        """Every row's observed target, in priced row order."""
        return self._targets

    @property
    def target(self) -> TargetExpression:
        """The known expression the targets were drawn from."""
        return self._target

    def feature(self, row: int, column: int) -> float:
        """One cell of the design, by priced row and feature index."""
        return self._features[row][column]

    def truth_for(self, row: int) -> float:
        """The noise-free value of the known target at ``row``.

        The answer key in the literal sense: the target evaluated at the
        row's own features, so a caller auditing the pool's honesty
        compares a candidate's predictions against the expression they
        were drawn from.
        """
        return self._target.evaluate(self._features[row])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SymbolicDataset(rows={self.rows}, "
            f"features={SYMREG_FEATURE_COUNT}, seed={self.seed})"
        )


def generate_symbolic_dataset(
    seed: int, *, target: TargetExpression
) -> SymbolicDataset:
    """Generate the fixed dataset a seed prices a target with.

    A pure function of ``(seed, target)``: same seed and target, same
    dataset, to the last bit, in any process and in any order of calls
    — the totality that lets the world's identity *be* its seed and
    target (:mod:`bootstrap._stream`'s whole argument, restated for
    this domain), and one sweep rather than a lazy per-cell draw for
    the reason the hyperparameter world's is: a fit needs the whole
    design, so there is no order a policy could reveal cells in that
    would change what is drawn.
    """
    rows: list[tuple[float, ...]] = []
    targets: list[float] = []
    token = mix64(seed)
    for row in range(SYMREG_ROWS):
        features = tuple(
            normal(_feature_cell(token, row, column))
            for column in range(SYMREG_FEATURE_COUNT)
        )
        noise = SYMREG_NOISE_SCALE * normal(_noise_cell(token, row))
        rows.append(features)
        targets.append(math.fsum((target.evaluate(features), noise)))
    return SymbolicDataset(
        features=tuple(rows), targets=tuple(targets), target=target, seed=seed
    )


def _design_row(features: tuple[float, ...], setting: ExpressionSetting) -> list[float]:
    """One row of a candidate's design: the intercept, then its monomials.

    The column order is fixed — intercept first, then the setting's
    terms in :data:`SYMBOLIC_AXIS_ORDER` — because it is the order a
    fitted coefficient vector is read in and the order two candidates
    must agree on to be compared at all.  The terms are the setting's
    own, so a design is a structure made numeric, nothing more.
    """
    columns = [_monomial_value(monomial, features) for monomial in setting.monomials]
    return [1.0, *columns]


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------


class SymbolicRegressionWorld:
    """Feature 183's world: a known target, a lattice of candidates, honest scores.

    Constructed from a world id and a seed — the target is drawn from
    the seed by :func:`target_for_seed` — or from an explicit
    ``target`` a caller plants, which is the *known* of the feature's
    own sentence taken literally: the caller names the expression, the
    world prices it and scores every candidate against it.  The dataset
    is generated on first use, once, and held; no method mutates
    anything and no answer depends on which ask came before it, so two
    worlds built from one ``(world_id, seed, target)`` are
    interchangeable to the last bit — the same statelessness the
    hyperparameter world states for itself, and the reason a replay may
    reveal cells in any order and still score a policy on the same
    numbers.

    **The interface is the question interface.**  This class owns the
    answer surface — :meth:`node_id` and :meth:`setting` address a cell,
    :meth:`legal_moves` enumerates the neighbours, :meth:`canonical_node`
    roots a walk, :meth:`label` reveals a cell's truth — and carries no
    policy runtime, no reveal bookkeeping and no budget, all three of
    which belong to the question (:class:`SymbolicQuestion`), the replay
    engine and feature 185's ledger rather than to a world.  The surface
    is the one :func:`~bootstrap.question_for` duck-types over, so the
    identical :class:`~bootstrap.BootstrapQuestion` wraps this world
    with no change to feature 184's module.
    """

    __slots__ = ("_dataset", "_target", "_world_id", "seed")

    def __init__(
        self,
        world_id: str,
        *,
        seed: int = SYMREG_SEED,
        target: TargetExpression | None = None,
    ) -> None:
        if not isinstance(world_id, str) or not world_id.strip():
            raise BootstrapWorldError(
                f"a world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how a label is "
                "attributed to a world in the pool, and an unnamed world's "
                "scores could not be reported per pool as §10.6 requires"
            )
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise BootstrapWorldError(
                f"a world seed is an integer — got {seed!r} "
                f"({type(seed).__name__}); the seed names the dataset the "
                "target is priced against, and a seed that is not an "
                "integer names no world this member can reproduce"
            )
        if target is None:
            # Drawn here rather than lazily: the draw is one pure hash
            # read, and a world whose *published* target had to wait on
            # its dataset would be a world that could not say what it
            # was scoring against until the first label — which is
            # backwards, the target is the reason the dataset exists.
            target = target_for_seed(seed)
        if not isinstance(target, TargetExpression):
            raise BootstrapWorldError(
                f"a symbolic world is scored against a TargetExpression — "
                f"got {target!r} ({type(target).__name__}); the target is "
                "the known truth every label is measured against, and a "
                "value that is not one names no expression a candidate "
                "could recover"
            )
        self._world_id = world_id
        self.seed = seed
        self._target = target
        self._dataset: SymbolicDataset | None = None

    @property
    def world_id(self) -> str:
        """This world's id — the name its labels are attributed to."""
        return self._world_id

    @property
    def target(self) -> TargetExpression:
        """The known target expression every label is measured against."""
        return self._target

    @property
    def theme_root(self) -> str:
        """The structural family this world's nodes belong to — ``symreg``.

        A fact about the *domain* rather than the world, read by this
        domain's question adapter for every :class:`~bootstrap.CellMeta`
        it hands a policy: §11.1's family conditioning needs the family
        named, and a symbolic regression node is not a member of the
        hyperparameter family.
        """
        return SYMREG_THEME_ROOT

    @property
    def dataset(self) -> SymbolicDataset:
        """The fixed dataset, generated once from ``(seed, target)`` and held.

        Lazy for the reason the hyperparameter world's dataset is: a
        pool holds many worlds and pays for a dataset only when a label
        is asked of it.
        """
        if self._dataset is None:
            self._dataset = generate_symbolic_dataset(self.seed, target=self._target)
        return self._dataset

    # -- The lattice --------------------------------------------------------

    @property
    def axes(self) -> tuple[SymbolicAxis, ...]:
        """The world's axes, in :data:`SYMBOLIC_AXIS_ORDER`."""
        return SYMBOLIC_AXIS_ORDER

    @property
    def canonical_setting(self) -> ExpressionSetting:
        """The world's root — the setting a caller gets by naming nothing."""
        return ExpressionSetting()

    def canonical_node(self) -> str:
        """The root's node id — where a policy's walk starts."""
        return canonical_symbolic_node_id()

    def setting(self, node_id: str) -> ExpressionSetting:
        """The setting a node id addresses, or the world's refusal.

        The decode is strict and the lattice bound is separate, as in
        the hyperparameter world: a well-formed address may still step
        past the end of an axis, and that refusal reads differently
        from a malformed one.
        """
        return _setting_from_steps(
            decode_symbolic_node_id(node_id), node_id=node_id
        )

    def steps(self, node_id: str) -> tuple[int, ...]:
        """The step vector a node id addresses, refused if out of lattice."""
        return self.setting(node_id).steps()

    def node_id(self, setting: ExpressionSetting) -> str:
        """The node id addressing ``setting`` in this world.

        Validates the setting's type before encoding, so a caller that
        hands a hyperparameter setting — or anything else — is refused
        rather than answered from its accidental shape.
        """
        if not isinstance(setting, ExpressionSetting):
            raise BootstrapWorldError(
                f"a node id addresses an ExpressionSetting — got "
                f"{setting!r} ({type(setting).__name__}); a node is a "
                "point of this world's lattice, not a bare value"
            )
        return encode_symbolic_node_id(setting.steps())

    def legal_moves(self, node_id: str | None = None) -> tuple[str, ...]:
        """The neighbours of ``node_id`` — one legal step along one axis.

        ``None`` (or the root's own id) answers the root's neighbours,
        so a caller can start a walk without spelling the root first.
        Each move is one axis by one position in either direction,
        filtered to the levels the lattice holds; ascending by node id,
        so two enumerations agree and a policy that does not sort still
        sees a deterministic order (§12's ordering rule, restated for a
        frontier).
        """
        origin = self.canonical_node() if node_id is None else node_id
        current = self.setting(origin)
        steps = list(current.steps())
        moves: list[str] = []
        for index, axis in enumerate(SYMBOLIC_AXIS_ORDER):
            legal = SYMBOLIC_AXES[axis]
            for delta in (-1, 1):
                position = legal.index(current.value(axis)) + delta
                if 0 <= position < len(legal):
                    neighbour = list(steps)
                    neighbour[index] = position - legal.index(legal[0])
                    moves.append(encode_symbolic_node_id(tuple(neighbour)))
        return tuple(sorted(moves))

    def legal_roots(self) -> tuple[str, ...]:
        """The node a walk may start from — the single canonical root."""
        return (self.canonical_node(),)

    def depth(self, node_id: str) -> int:
        """How many legal moves the node is from the root — ``Σ|step|``."""
        return self.setting(node_id).depth

    def cells(self) -> tuple[str, ...]:
        """Every node id of the lattice, ascending — the world's whole space.

        The product of the axes' levels, addressed by the same codec
        every other node is, sorted so two enumerations of one world
        agree.  Eighty-one cells — three levels on each of four axes —
        and every one answerable: the ridge floor keeps the completed
        fit total whatever the candidate's columns.
        """
        settings: list[ExpressionSetting] = [ExpressionSetting()]
        for axis in SYMBOLIC_AXIS_ORDER:
            legal = SYMBOLIC_AXES[axis]
            grown: list[ExpressionSetting] = []
            for setting in settings:
                for value in legal:
                    grown.append(setting.with_value(axis, value))
            settings = grown
        return tuple(sorted(self.node_id(setting) for setting in settings))

    # -- The label ----------------------------------------------------------

    def label(self, node_id: str) -> FitResult:
        """The node's ground-truth score — the feature's headline.

        Completes the candidate's structure with least-squares
        coefficients over the training split and answers the held-out
        ``R²`` (:attr:`~bootstrap._fit.FitResult.r2_holdout`) beside the
        training score and the fitted coefficients.  Every input is the
        world's own fixed state or the node's address, so the answer is
        a pure function of ``(world, node)``: the same node labelled
        twice, or after any number of other nodes, answers the identical
        number — which is what makes it a ground truth rather than a
        measurement, and what makes the score *against the known target*
        a fact about the structure rather than about the path that
        reached it.

        Refuses with :class:`~bootstrap.errors.BootstrapWorldError` for
        a node outside the lattice or a missing address — the root is
        spelled, not defaulted, because a defaulted argument would let a
        missing one answer the same label as a deliberate root ask —
        and would refuse with
        :class:`~bootstrap.errors.BootstrapScoringError` for a split the
        arithmetic could not answer, unreachable on this world's
        constants (the ridge floor keeps every fit total and the noise
        gives every split variance) but carried through from
        :mod:`bootstrap._fit` so a caller's ``except`` is not written
        against a promise the arithmetic does not keep.
        """
        if not isinstance(node_id, str) or not node_id:
            raise BootstrapWorldError(
                f"label() needs the node id to label — got {node_id!r}; the "
                "world's root is a node like any other and is asked for by "
                f"name ({self.canonical_node()!r} on this world), because a "
                "defaulted argument would let a missing one answer the same "
                "label as a deliberate root ask"
            )
        return self.label_setting(self.setting(node_id), node_id=node_id)

    def label_setting(
        self, setting: ExpressionSetting, *, node_id: str | None = None
    ) -> FitResult:
        """The label for a setting already in hand — the score, spelled once.

        Both callers — :meth:`label` for a node id, :meth:`label_all`
        for a sweep — route through this, so a node's label has exactly
        one implementation and a sweep cannot drift from a single ask.
        """
        subject = (
            f"node {node_id!r} of world {self._world_id!r}"
            if node_id is not None
            else f"setting {setting.text!r} of world {self._world_id!r}"
        )
        dataset = self.dataset
        train, holdout = split_indices(dataset.rows)
        return fit_and_score(
            design_train=[
                _design_row(dataset.features[row], setting) for row in train
            ],
            targets_train=[dataset.targets[row] for row in train],
            design_holdout=[
                _design_row(dataset.features[row], setting) for row in holdout
            ],
            targets_holdout=[dataset.targets[row] for row in holdout],
            ridge=SYMREG_RIDGE,
            subject=subject,
        )

    def label_all(self) -> Iterator[tuple[str, FitResult | BootstrapScoringError]]:
        """Every cell of the lattice, labelled — the world's ground truth.

        Ascending by node id and total, exactly as the hyperparameter
        world's sweep is: a cell whose fit refuses yields the refusal
        rather than aborting the sweep, so a caller auditing the whole
        space sees the full landscape rather than a prefix of it.
        """
        for node_id in self.cells():
            try:
                yield node_id, self.label(node_id)
            except BootstrapScoringError as refusal:
                yield node_id, refusal

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SymbolicRegressionWorld(world_id={self._world_id!r}, "
            f"seed={self.seed!r}, target={self._target.text!r})"
        )


def _setting_from_steps(
    steps: tuple[int, ...], *, node_id: str
) -> ExpressionSetting:
    """Turn a decoded step vector into a setting, or refuse it as out of lattice.

    The one place the lattice bound is enforced on the way in from a
    node id, so :meth:`SymbolicRegressionWorld.setting` and
    :meth:`SymbolicRegressionWorld.steps` cannot disagree about which
    cells the world holds — the same split of labours the hyperparameter
    world's own ``setting_from_steps`` makes.
    """
    values: dict[str, int] = {}
    for axis, step in zip(SYMBOLIC_AXIS_ORDER, steps):
        legal = SYMBOLIC_AXES[axis]
        position = step + legal.index(legal[0])
        if not 0 <= position < len(legal):
            raise BootstrapWorldError(
                f"the node id {node_id!r} addresses {axis.value}={step:+d} "
                f"step(s) from this world's root, which is past the end of "
                f"the {axis.value!r} axis — the lattice declares "
                f"{', '.join(str(level) for level in legal)} level(s) per "
                "structural choice; the space is bounded because an axis "
                "is a declaration of what the world answers for, and a "
                "level outside it names a term nobody agreed to score"
            )
        values[axis.value] = legal[position]
    return ExpressionSetting(**values)


# --------------------------------------------------------------------------
# The question the world fronts
# --------------------------------------------------------------------------


class SymbolicQuestion(BootstrapQuestion):
    """The policy-facing question over a symbolic world — 184's adapter, symreg's family.

    Feature 184's :class:`~bootstrap.BootstrapQuestion` is the one
    object a policy is handed, and this class *is* that object: it is
    inherited whole, not rebuilt — ``observed``, ``legal_actions``,
    ``legal_roots``, ``probe_batch``, ``budget_remaining`` and
    ``commit`` are the inherited implementations, answering through the
    world this adapter wraps — because the identical-interface
    requirement of §10.6 is a requirement about the *methods a policy
    calls*, and inheriting them is the one way two domains cannot drift
    apart in what those methods do.

    The single override is :meth:`meta`, and the reason is §11.1's:
    ``theme_root`` is exposed in ``meta()`` because the overfit
    signature is only partly family-invariant and a policy writes
    family-conditional thresholds, so the family a node reports must be
    the node's *own* domain — a symbolic regression node is ``symreg``,
    not ``hpo`` — and the branch axis of a symreg cell's structure is
    one of this lattice's four axes, not the hyperparameter lattice's.
    The parent's ``meta`` reads the hyperparameter tables because every
    world it was built to front shared them; this world does not, so the
    one method whose *content* is per-domain is re-answered here while
    everything whose *shape* is the interface stays inherited.

    Constructed through :func:`symreg_question_for`; the constructor
    adds one check to the parent's duck-typing — the world must declare
    its ``theme_root``, because the family is a fact the adapter
    reports and a world without one would leave the meta silently
    answering a family the world never claimed.
    """

    def __init__(self, world: SymbolicRegressionWorld) -> None:
        super().__init__(world)
        if not hasattr(world, "theme_root"):
            raise BootstrapWorldError(
                f"a symbolic question fronts a world that declares its "
                f"family — got {world!r} ({type(world).__name__}), which "
                "has no theme_root; §11.1's family conditioning routes "
                "through meta(), and a world with no family to report "
                "would leave the meta answering one it never claimed"
            )

    def meta(self, node_id: str) -> CellMeta:
        """The structural metadata of ``node_id`` — §11's ``meta(node_id)``.

        The parent's derivation over *this* lattice's axes: the depth is
        the node's ``Σ|step|`` from the root, the parent is the
        neighbour one step toward the root (``None`` at the root), the
        branch is the highest axis the node differs from its parent on
        (``None`` at the root), and the theme root is the world's own
        declared family — ``symreg`` — so a policy's family-conditional
        thresholds see this node as a member of its domain.
        """
        steps = self._world.steps(node_id)
        depth = sum(abs(step) for step in steps)
        if depth == 0:
            # The root: no parent, no step that reached it, no axis moved.
            return CellMeta(
                branch=None, depth=0, parent=None, theme_root=SYMREG_THEME_ROOT
            )
        # The parent is the neighbour one legal step toward the root, and
        # the branch is the axis that step moved — the parent's own rule,
        # tie-broken on the later axis so two adapters of one world name
        # the same parent and branch, re-answered over this lattice's
        # axis order and codec.
        max_distance = max(abs(step) for step in steps)
        parent_steps = list(steps)
        branch_axis: SymbolicAxis | None = None
        for index in range(len(SYMBOLIC_AXIS_ORDER) - 1, -1, -1):
            if abs(steps[index]) == max_distance:
                parent_steps[index] = steps[index] - (
                    1 if steps[index] > 0 else -1
                )
                branch_axis = SYMBOLIC_AXIS_ORDER[index]
                break
        return CellMeta(
            branch=branch_axis,  # type: ignore[arg-type]  # this lattice's axis
            depth=depth,
            parent=encode_symbolic_node_id(tuple(parent_steps)),
            theme_root=self._world.theme_root,
        )


def symreg_question_for(world: SymbolicRegressionWorld) -> SymbolicQuestion:
    """Turn a symbolic world into the policy-facing question it fronts.

    The domain's one factory, the way :func:`~bootstrap.question_for`
    is the hpo domain's and :func:`~bootstrap.ported_question_for` the
    ported domain's: a world in, the question a policy expects out,
    built so the construction cannot be gotten wrong at the call site.
    The adapter is bound to the world it wraps — its
    ``legal_actions``, its labels, its ``meta`` are the world's — so
    one policy written against a financial campaign runs unmodified
    against a symbolic regression world, which is §10.6's
    *"a policy is portable without modification"* and feature 184's
    identical-interface requirement, answered for this domain.

    Inherits the parent constructor's refusals — a non-world or an
    unnamed world is refused before it can hand a policy an interface —
    and adds the one this domain needs, the declared family (see
    :class:`SymbolicQuestion`).
    """
    return SymbolicQuestion(world)
