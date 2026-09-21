"""The hyperparameter search world — feature 181's fixed model and dataset.

app_spec.xml, "Bootstrap Worlds", feature 181: *System exposes a
hyperparameter search world over a fixed model and dataset, which returns
a ground-truth score per node.*  docs/nullius-tech-architecture.md §10.6
places it as the first of the three authored domains — *"hpo/  #
hyperparameter search over a fixed model+dataset"* — and states what every
bootstrap world is for:

    Each exposes the **same** ``question.*`` API as a financial campaign,
    so a policy is portable without modification.  They give perfect
    labels, zero statistical-budget cost, and no dependence on market time.

    This converts the §10.3.1 pool-size precondition from a calendar
    problem into a compute problem.

**A world is a fit, and the answer key is the held-out score.**  §10.3's
per-world objective is dominated by a model's out-of-sample performance,
and §10.6's whole point is that an external domain can supply that
component with an honest label.  So this world's label is exactly that
component, computed from a fixed model and a fixed dataset: the node
proposes *hyperparameters*, the world fits the model with them, and the
node's ground truth is the fit's coefficient of determination on data it
was not fitted on.  Nothing here scores a policy, charges a budget or
consults a clock — those are the replay engine's, feature 185's and
§10.6's own statements — so the label is a pure function of ``(world,
node)`` and nothing else.

**What is fixed, and why it is generated rather than shipped.**  The
*fixed model* is the truth the dataset was drawn from, spelled as an
expression over the features: an intercept, linear terms, one pairwise
interaction and one square.  The *fixed dataset* is
:data:`~bootstrap.PRICED_ROWS` observations of that model, generated from
the world's seed by :mod:`bootstrap._stream`.  That the dataset is
generated is a property of the feature rather than a shortcut: §10.6 needs
40-50 bootstrap worlds *on demand* (feature 188) precisely because the
precondition "is a compute problem" rather than a calendar problem, and a
world that had to be fetched could not be authored at that rate.  It also
makes the world's identity total — the world *is* its seed, so §10.6.1's
provenance rule (*"An upstream that changes is a different world, not an
updated one"*) has nothing to check and nothing to drift: there is no
upstream.  The ported-world adapter that *does* have an upstream to check
is feature 190's, in this same category.

**The lattice: what a node is, and why it is a lattice and not a box.**
A node's setting is a point in the hyperparameter space, and the space is
a *lattice* rooted at the world's canonical default — the setting a
caller gets by naming nothing, which is what makes the world addressable
from a bare root.  Each axis declares a small ordered tuple of legal
values, and a legal step moves **one** axis by one position.  Two
consequences follow, and both are the feature's rather than a
convenience:

* the space is *connected* from the root — every cell is reachable by a
  monotone sequence of legal steps, so a policy that only ever moves along
  edges (docs/nullius-tech-architecture.md §10.1's ``policy.select`` over
  revealed nodes) can reach the whole space from the root it starts at;
* the space is *bounded* — a step past the first or last value of an axis
  is refused rather than extrapolated, because the axis is a declaration
  of what the world answers for and a hyperparameter outside it names a
  model nobody has agreed to score.

This is the structural vocabulary §10.6.1's ``question.meta(node_id)``
calls ``CellMeta`` — *"structural: branch, depth, parent, theme_root"* —
seen from the world's side: the axes are the dimensions a policy reasons
about, the canonical setting is the root, and the step count is the depth.

**One label, computed one way.**  :meth:`HyperparameterWorld.label`
returns the :class:`~bootstrap._fit.FitResult` for a node: the held-out
``R²`` is the ground-truth score, and the training ``R²`` rides beside it
so the overfit gap is answerable too.  Nothing about the score depends on
which node was labelled before it or on how many (the addressing in
:mod:`bootstrap._stream` is content-addressed), so a replay may reveal
cells in any order a policy chooses and every label is still the same
number — which is what "ground truth" has to mean for a pool the
financial worlds are calibrated against.

**The ridge is the ``alpha`` axis, not a constant under it.**  A node's
``alpha`` *is* the ridge its fit is solved with
(:func:`~bootstrap._fit.fit_and_score` is called with ``setting.alpha``),
so the axis is a real hyperparameter the policy searches rather than a
label on a fixed penalty.  ``alpha`` is a multiplier on the *penalty
term*, not a divisor of it: a larger ``alpha`` is a stronger ridge, which
is the ``sklearn`` convention and the one a policy trained on either will
already assume.

**The conditioning is engineered, and the ridge floor is part of it.**
The features are bounded (an Irwin-Hall draw lives on ``[-6, 6]``, scaled
by :data:`FEATURE_SCALES`) and the design is optionally column-standardised
before the fit, so no generated row is a leverage point and no column's
scale can wreck the system.  On top of that the lattice's *smallest*
``alpha`` — :data:`DEFAULT_RIDGE`, the root's value — puts a positive
floor under every non-intercept diagonal of every cell, which is what
makes the world's fits *total*: ``XᵀX`` is positive semidefinite, so
adding a positive ridge makes the system positive definite whatever the
degree — including the widest cell of this lattice, ``degree=3`` with
interactions at 34 columns against a 64-row training split, and including
cells whose design is wider than the split once features are added.  A
world that could not answer some of its own cells would be a world whose
lattice over-promised, and §10.6's pool wants worlds that answer
everywhere a policy can walk.  That floor is small enough (1e-2) to leave
the lightest cells' scores essentially unpenalised and large enough to
keep every pivot comfortably positive; the refusals
:mod:`bootstrap._fit` carries are its guarantee for a caller who
configures a lattice reaching zero, not this world's routine path.

**``standardize`` is the quiet axis, and how quiet it is depends on
``alpha``.**  A linear rescaling of a design's inputs does not change the
*span* of the polynomial design built from them, so the two
standardisations fit models from the same family, and the *unpenalised*
least-squares optimum is literally the same point.  Read alone, that
suggests the axis is inert.  It is not, and the reason is the ridge: a
penalty applied to unstandardised columns is applied in those columns'
own units, so a feature drawn at a large scale is shrunk by a small
fraction of what the same feature standardised would be.  The axis
therefore starts flat and grows with the penalty on top of it — measured
across this world's five declared ``alpha`` values, the largest
``standardize`` flip is worth ~4e-5 at the lightest ridge, ~4e-4 at 0.1,
~3e-3 at 1, ~2e-2 at 10 and ~1e-1 at the harshest 100.

Two consequences, and both are the point.  First, the axes are **not
independent**: the sign and size of the ``standardize`` move at a cell
depends on where that cell sits on ``alpha``, so neither "always
standardise" nor "never standardise" is a rule that finds the optimum —
a policy has to learn the interaction, and the member's tests pin the
curve rather than a single gap.  Second, the effect stays an order of
magnitude below what the ``interaction`` axis is worth at every cell, so
the *ranking* of which axes repay probing is never in doubt.  A policy
that has to discover which coordinates are worth its budget is being
taught exactly the structure §10.6's category exists to teach; a world
where every axis paid equally would be a world where search policy does
not matter.

The ``alpha`` axis is loud by comparison, and the contrast is worth
stating because the two are easy to conflate.  ``standardize`` changes
the design's span, which the fit's family absorbs — until the penalty
gives the span a price.  ``alpha`` *is* that price, which nothing
absorbs.  The harshest declared value (100) does large damage, shrinking
genuine signal, and across the declared range the axis moves the honest
score by a wide margin, which is what makes it a dimension worth probing.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Iterator
from typing import Any

from ._fit import FitResult, fit_and_score
from ._stream import mix64, normal
from .errors import BootstrapScoringError, BootstrapWorldError

__all__ = [
    "AXIS_ORDER",
    "DEFAULT_ALPHA",
    "DEFAULT_DEGREE",
    "DEFAULT_INTERACTIONS",
    "DEFAULT_RIDGE",
    "DEFAULT_STANDARDIZE",
    "FEATURE_COUNT",
    "FEATURE_SCALES",
    "HOLDOUT_STRIDE",
    "HYPERPARAMETER_AXES",
    "INTERACTION_COEFFICIENTS",
    "INTERCEPT",
    "LINEAR_COEFFICIENTS",
    "NOISE_SCALE",
    "PRICED_ROWS",
    "PRICED_SEED",
    "SQUARE_COEFFICIENTS",
    "Dataset",
    "HyperparameterAxis",
    "HyperparameterSetting",
    "HyperparameterWorld",
    "canonical_node_id",
    "column_statistics",
    "decode_node_id",
    "design_columns",
    "encode_node_id",
    "generate_dataset",
    "node_steps",
    "setting_dimensions",
    "setting_from_steps",
    "split_indices",
]

#: How many features the world's fixed dataset has.  Six is enough for a
#: pairwise-interaction design at ``degree=3`` to overrun a 64-row
#: training split — 6 linear + 6 quadratic + 6 cubic + 15 pairwise + 1
#: intercept = 34 columns against 64 rows is fine, but the *saturation*
#: refusal stays reachable on a narrower split — and small enough that a
#: policy can hold the whole space in mind, which is what §10.6 means by
#: short, self-contained histories.
FEATURE_COUNT = 6

#: How many observations the fixed dataset holds.  Fixed rather than a
#: parameter: the dataset is the world's *fixed* half, and a caller who
#: could resize it could move every label in the world.
PRICED_ROWS = 96

#: The holdout predicate's stride.  Every third row (index ≡ 2 mod 3) is
#: held out, so :data:`PRICED_ROWS` splits 64/32 — a two-thirds split, the
#: ordinary proportion, and one that is *interleaved* rather than a
#: trailing block so the holdout spans the whole feature range instead of
#: the last third of it.  Spelled as a stride rather than a ratio so the
#: split is a fact about the row index and not about a float comparison.
HOLDOUT_STRIDE = 3

#: The per-feature standard deviations of the fixed dataset's draw.  All
#: one: a heterogeneous spread (one feature 100× another) makes the
#: problem *easy* rather than hard — a polynomial design then fits the
#: dominant feature first and the optimum collapses onto whichever cell
#: reaches it, which erases the gradient the score is supposed to show.
#: Homogeneous scales keep the interaction terms load-bearing, so the
#: optimum has to be *found* rather than stumbled into.  Kept as a tuple
#: rather than deleted so a world that wants a different spread changes one
#: line and the addressing below is unaffected.
FEATURE_SCALES = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

#: The fixed model's intercept and linear coefficients — the truth the
#: dataset was drawn from, spelled once.  Publishing the truth is
#: deliberate: §10.6's bootstrap worlds *are* the ones whose answer is
#: known, which is what makes them the calibration reference the financial
#: pool is measured against.  The feature underneath is the *fit*: knowing
#: the truth does not tell a policy which hyperparameters recover it, which
#: is the search problem the world poses.
INTERCEPT = 1.0
LINEAR_COEFFICIENTS = (0.4, -0.5, 0.0, -0.3, 0.0, 0.0)

#: The single pairwise interaction the truth carries, keyed by the feature
#: index pair.  One interaction and one square, not several: the design
#: needs the ``interactions`` axis to be *load-bearing* (a policy that
#: leaves it off must measurably lose) while the truth stays simple enough
#: that the optimum is a fact about the model rather than about the noise.
INTERACTION_COEFFICIENTS = {(0, 2): 2.0}

#: The single square term, keyed by feature index.  The two curvature
#: terms are what make the ``degree`` axis load-bearing, and their weight
#: relative to :data:`LINEAR_COEFFICIENTS` is what makes the *shallowest*
#: design that can express them the optimum: a linear design cannot reach
#: them at all, while a cubic one pays variance for columns the truth does
#: not use.  The linear part is therefore deliberately *small* — with the
#: curvature terms outweighed by a strong linear signal, the optimum
#: collapses onto degree 1 with interactions and the ``degree`` axis stops
#: paying, which would leave two thirds of the lattice uninformative.
SQUARE_COEFFICIENTS = {2: 2.5}

#: The standard deviation of the observation noise added to the truth, in
#: units of the model's own spread.  Large enough that the optimum is a
#: genuine bias-variance trade-off — the *wider* designs do worse on the
#: holdout, which is the overfitting signal a policy has to learn — and
#: small enough that the signal is not buried.  Tuned against a sweep of
#: seeds rather than one: the optimum's *identity* is stable across the
#: pool (the world's tests pin the two axes it depends on, over many
#: seeds), so no single world's difficulty is a lottery.
NOISE_SCALE = 1.0

#: The world's dataset seed.  Every world draws its own; this is the seed
#: :data:`~bootstrap.HYPERPARAMETER_WORLD_ID` names, so the committed world
#: and the committed tests describe one world rather than two.
PRICED_SEED = 20260921

#: The world's canonical setting — the root, and the value each axis of a
#: node's setting is measured against when the step count is taken.  Each
#: is the *first* value of its axis by construction
#: (:data:`HYPERPARAMETER_AXES`), which is what makes the root reachable
#: from every cell by a monotone walk and the space a lattice rather than
#: a set.
#:
#: This is an invariant, not a coincidence: :func:`canonical_node_id`
#: addresses the root as the all-zero step vector, so a default that was
#: not its axis's first value would make ``HyperparameterSetting()`` and
#: ``"d+0.i+0.s+0.a+0"`` two different cells — and a policy told it stood
#: at the root would be standing somewhere else.  The defaults are the
#: lattice's *own* first values rather than a separate set of constants
#: that must be kept in step with it, and a test pins that.
#:
#: ``DEFAULT_RIDGE`` is defined as ``DEFAULT_ALPHA`` for the same reason
#: from the other side: the ridge a node is fitted at *is* its ``alpha``,
#: so the floor the world advertises and the value the root carries are
#: one number rather than two that could drift apart.
DEFAULT_DEGREE = 1
DEFAULT_INTERACTIONS = False
DEFAULT_STANDARDIZE = False
DEFAULT_ALPHA = 0.01

#: The smallest ridge any cell of the lattice applies, in the standardised
#: design's units.  This is the ``alpha`` axis's *root* value rather than a
#: separate constant applied under the fit: a node's ``alpha`` **is** the
#: ridge :func:`~bootstrap._fit.fit_and_score` is called with, so this
#: figure reaches the arithmetic only through the canonical setting.
#:
#: Named and exported because a caller reasoning about the fits needs the
#: floor in hand — it is the value below which no cell of this world ever
#: goes, and therefore the guarantee that no cell is solved near-singular.
#: Zero is admissible in principle and is not in this lattice: with a
#: polynomial design and a 64-row split, an unpenalised solve at a wide
#: degree can land on a system whose pivot is positive but tiny, where the
#: answer is dominated by rounding rather than by data.  This value is
#: small enough that it changes no reported score at any cell the lattice
#: reaches and large enough to keep every pivot comfortably positive.
DEFAULT_RIDGE = DEFAULT_ALPHA


class HyperparameterAxis(enum.StrEnum):
    """The four axes of the world's lattice, in the order steps compose.

    A :class:`~enum.StrEnum` rather than bare strings, the discipline
    :class:`sandbox.failclass.FailClassReason` and
    :class:`nulloracle.assignment.NullType` state for their own
    vocabularies: the axis a step moved is *read* by a caller — a policy
    reasoning about which dimension to try next, a test asserting the
    lattice's shape — and a bare ``str`` would let a typo address an axis
    that does not exist while comparing equal to the one that does.

    The declaration order is load-bearing and is :data:`AXIS_ORDER`'s:
    the step vector that addresses a node is spelled in this order, so the
    addressing is stable and a reader can see at a glance which dimension
    the third entry moves.
    """

    #: The polynomial degree of the model — the width of the design.
    DEGREE = "degree"

    #: Whether the design carries the pairwise cross terms.
    INTERACTIONS = "interactions"

    #: Whether the design is built on column-standardised inputs.
    STANDARDIZE = "standardize"

    #: The ridge penalty's strength, on the standardised design.
    ALPHA = "alpha"


#: The axes in declaration order — the one spelling of the vector's layout.
AXIS_ORDER: tuple[HyperparameterAxis, ...] = (
    HyperparameterAxis.DEGREE,
    HyperparameterAxis.INTERACTIONS,
    HyperparameterAxis.STANDARDIZE,
    HyperparameterAxis.ALPHA,
)

#: The legal values of each axis, in ascending order.  Every tuple's
#: **first** entry is the canonical default (the constants above), which is
#: what makes the root a point of the lattice rather than a special case
#: beside it.
HYPERPARAMETER_AXES: dict[HyperparameterAxis, tuple[Any, ...]] = {
    HyperparameterAxis.DEGREE: (1, 2, 3),
    HyperparameterAxis.INTERACTIONS: (False, True),
    HyperparameterAxis.STANDARDIZE: (False, True),
    HyperparameterAxis.ALPHA: (0.01, 0.1, 1.0, 10.0, 100.0),
}


def setting_dimensions() -> tuple[str, ...]:
    """The world's axes as their wire spellings, in declaration order.

    The lattice's *shape* as data, for a caller that wants to enumerate
    the space or render it without importing the enum — the same
    ``row()``-shaped service :meth:`~bootstrap.HyperparameterSetting.row`
    does for one setting.  Returns a fresh tuple per call.
    """
    return tuple(axis.value for axis in AXIS_ORDER)


class HyperparameterSetting:
    """One point of the lattice: a value for each of the four axes.

    Immutable and *ordered* — the values are held in :data:`AXIS_ORDER`,
    so two settings that name the same point are equal and hash alike
    whatever keyword order they were built with, and a set of them is a
    set of cells.  Values are validated at construction against
    :data:`HYPERPARAMETER_AXES`, so a setting that holds is a setting the
    world has agreed to score: an out-of-lattice value is refused here,
    before it can reach a fit, rather than answered from the nearest
    legal cell.

    ``alpha`` is compared by *value* rather than by identity, and a
    ``bool`` is refused where a degree or a penalty is expected for the
    reason :func:`artifacts._daily._validated_horizon` refuses one:
    ``True`` is ``1`` in Python, so a flag where a degree belongs would
    silently ask for the world's shallowest model instead of failing.
    """

    __slots__ = ("_values",)

    def __init__(
        self,
        *,
        degree: Any = DEFAULT_DEGREE,
        interactions: Any = DEFAULT_INTERACTIONS,
        standardize: Any = DEFAULT_STANDARDIZE,
        alpha: Any = DEFAULT_ALPHA,
    ) -> None:
        # The defaults above are the lattice's own first values by
        # construction, which is what makes the canonical setting a point
        # of the space rather than a special case beside it.  ``alpha``'s
        # default is that axis's first value like the others — it is *also*
        # the ridge floor the world advertises (``DEFAULT_RIDGE``), because
        # a node's ``alpha`` is the ridge it is fitted at; there is one
        # number rather than two that could disagree.
        requested = {
            HyperparameterAxis.DEGREE: degree,
            HyperparameterAxis.INTERACTIONS: interactions,
            HyperparameterAxis.STANDARDIZE: standardize,
            HyperparameterAxis.ALPHA: alpha,
        }
        resolved: list[Any] = []
        for axis in AXIS_ORDER:
            legal = HYPERPARAMETER_AXES[axis]
            value = requested[axis]
            if isinstance(value, bool) and not isinstance(legal[0], bool):
                raise BootstrapWorldError(
                    f"the {axis.value!r} axis is {_kind_of(legal)}, and "
                    f"{value!r} is a flag — True is 1 in Python, so a flag "
                    "where this axis belongs would silently ask for the "
                    f"world's shallowest {axis.value} instead of failing"
                )
            if value not in legal:
                raise BootstrapWorldError(
                    f"{value!r} is not a value of the {axis.value!r} axis — "
                    f"this world's lattice declares {_render(legal)}; a "
                    "hyperparameter outside the declaration names a model "
                    "the world has not agreed to score"
                )
            resolved.append(value)
        self._values = tuple(resolved)

    @property
    def values(self) -> tuple[Any, ...]:
        """The node's coordinates, in :data:`AXIS_ORDER` — read-only."""
        return self._values

    def value(self, axis: HyperparameterAxis) -> Any:
        """This setting's coordinate on ``axis``."""
        return self._values[AXIS_ORDER.index(axis)]

    @property
    def degree(self) -> int:
        """The polynomial degree this setting asks the model to be."""
        return self.value(HyperparameterAxis.DEGREE)

    @property
    def interactions(self) -> bool:
        """Whether this setting's design carries the pairwise cross terms."""
        return self.value(HyperparameterAxis.INTERACTIONS)

    @property
    def standardize(self) -> bool:
        """Whether this setting's design is built on standardised columns."""
        return self.value(HyperparameterAxis.STANDARDIZE)

    @property
    def alpha(self) -> float:
        """The ridge strength this setting applies, in standardised units."""
        return self.value(HyperparameterAxis.ALPHA)

    def steps(self) -> tuple[int, ...]:
        """How far each axis has moved from the world's canonical setting.

        One signed integer per axis, in :data:`AXIS_ORDER`: negative below
        the root, zero at it, positive above.  This *is* the node's
        address — the vector a node id encodes — so it is a method on the
        value rather than a property of the world, and the world's
        :meth:`~bootstrap.HyperparameterWorld.steps` is the one spelling
        of "where is this setting relative to the root".
        """
        return tuple(
            HYPERPARAMETER_AXES[axis].index(value)
            - HYPERPARAMETER_AXES[axis].index(HYPERPARAMETER_AXES[axis][0])
            for axis, value in zip(AXIS_ORDER, self._values)
        )

    @property
    def depth(self) -> int:
        """``Σ|step|`` — how many legal moves the setting is from the root.

        The structural depth §10.6.1's ``CellMeta`` reports, read off the
        lattice rather than stored: a node's depth is a fact about where it
        sits, and a stored copy could disagree with the coordinates it was
        taken from.
        """
        return sum(abs(step) for step in self.steps())

    def row(self) -> dict[str, Any]:
        """The setting as a store-shaped mapping — a fresh dict per call."""
        return {axis.value: value for axis, value in zip(AXIS_ORDER, self._values)}

    def with_value(self, axis: HyperparameterAxis, value: Any) -> HyperparameterSetting:
        """A copy of this setting with one axis moved to ``value``.

        A fresh setting per call, never a mutated one: a setting is a
        *cell*, so two callers holding one must not be able to move each
        other's.  The copy is validated by the constructor like any other
        setting, so a move to an out-of-lattice value is refused here
        rather than held and refused later.
        """
        values = self.row()
        values[axis.value] = value
        return HyperparameterSetting(**values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HyperparameterSetting):
            return NotImplemented
        return self._values == other._values

    def __hash__(self) -> int:
        return hash(self._values)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"HyperparameterSetting({', '.join(
            f'{axis.value}={value!r}' for axis, value in zip(AXIS_ORDER, self._values)
        )})"


def _kind_of(legal: tuple[Any, ...]) -> str:
    """A readable noun for what an axis's values are, for the refusals."""
    first = legal[0]
    if isinstance(first, bool):
        return "a flag"
    if isinstance(first, int):
        return "an integer count"
    if isinstance(first, float):
        return "a real value"
    return "a value"


def _render(legal: tuple[Any, ...]) -> str:
    """The axis's declared values, rendered for a refusal message."""
    return ", ".join(repr(value) for value in legal)


def canonical_node_id() -> str:
    """The node id of the world's root — the all-zero step vector.

    A small named function rather than a constant so the root's address is
    *derived* from the same encoder every other node's is
    (:meth:`HyperparameterWorld.node_id` over the canonical setting), and
    the root cannot drift away from the lattice it roots.
    """
    return encode_node_id((0,) * len(AXIS_ORDER))


def encode_node_id(steps: tuple[int, ...]) -> str:
    """Encode a step vector as the node id that addresses it.

    ``"d+2.i+1.s0.a-1"`` — one ``<axis><sign><magnitude>`` field per axis
    in :data:`AXIS_ORDER`, joined by dots.  Text rather than a packed
    integer for the reason the artifact store's keys are text
    (:mod:`artifacts._keys`): a node id is *read* — by a log line, a test,
    an operator looking at a revealed tree — and a reader who can see
    which axis moved does not need this module open beside them.

    The magnitude is spelled in decimal and a sign is always written, so
    the encoding is injective in the obvious way and the root is
    ``"d+0.i+0.s+0.a+0"`` rather than a special case.  Every field is
    parsed back by :func:`decode_node_id`, which refuses anything this
    function cannot have produced — so the two are one codec in two
    directions rather than two spellings of an address.
    """
    return ".".join(
        f"{axis.value[0]}{'+' if step >= 0 else '-'}{abs(step)}"
        for axis, step in zip(AXIS_ORDER, steps)
    )


def decode_node_id(node_id: str) -> tuple[int, ...]:
    """Read a node id back into the step vector it encodes.

    The inverse of :func:`encode_node_id` and as strict as it: a node id
    whose field count, axis initials, sign or magnitude this module's
    encoder cannot have produced is refused with
    :class:`~bootstrap.errors.BootstrapWorldError`, naming what was wrong.
    Strict because a node id is *the* address a policy is handed and hands
    back (§10.6.1's ``question.commit(node_id)``), so a value that decoded
    leniently — a missing axis treated as zero, an unknown initial skipped
    — would let a commit name a cell the policy was never shown.
    """
    if not isinstance(node_id, str) or not node_id:
        raise BootstrapWorldError(
            f"a node id is a non-empty string — got {node_id!r} "
            f"({type(node_id).__name__}); the node id is the address a "
            "policy hands back when it commits, and an address it cannot "
            "have been given is not one this world can resolve"
        )
    fields = node_id.split(".")
    if len(fields) != len(AXIS_ORDER):
        raise BootstrapWorldError(
            f"the node id {node_id!r} carries {len(fields)} field(s) where "
            f"this world's lattice has {len(AXIS_ORDER)} axes "
            f"({', '.join(axis.value for axis in AXIS_ORDER)}); a node id "
            "is one field per axis, in that order"
        )
    steps: list[int] = []
    for axis, field in zip(AXIS_ORDER, fields):
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


def node_steps(node_id: str) -> tuple[int, ...]:
    """The step vector a node id addresses, refusing a malformed one."""
    return decode_node_id(node_id)


# --------------------------------------------------------------------------
# The fixed dataset
# --------------------------------------------------------------------------

#: Address-space prefixes keeping one world's draws from colliding.  Each
#: drawn quantity in a world gets a disjoint block of the 64-bit cell
#: space, so a feature value and an observation's noise term never share a
#: cell even when their row and column indices coincide.  Spelled as large
#: odd constants rather than small integers for the reason
#: :data:`bootstrap._stream.GOLDEN_GAMMA` is: two prefixes differing in
#: one bit would be mixed by the same multipliers with a one-bit
#: difference between them, and the finalizer's avalanche would be the only
#: thing standing between a policy and a detectable correlation between
#: two quantities.
_PREFIX_FEATURE = 0x51ED27_0C4B3F1A9D
_PREFIX_TARGET = 0x2B7F41_D9E05C6387

#: The multiplier spreading ``(row, column)`` pairs across the feature
#: block.  A row-major stride larger than any column count the world could
#: have, so two pairs collide only if they are literally equal.
_ROW_STRIDE = 1 << 32


def _feature_cell(token: int, row: int, column: int) -> int:
    """The cell one feature value is drawn from — ``token`` and ``(row, column)``.

    ``token`` (:func:`~bootstrap._stream.mix64` of the world's seed) is
    xored into the *prefix* rather than into the address, which is what
    gives the two properties this needs at once.  Within one world the
    address arithmetic is untouched, so two ``(row, column)`` pairs share a
    cell only if they are literally equal.  Across worlds the whole block
    translates by ``token``, so two worlds of one lattice get independently
    drawn feature matrices — which is the *point* of §10.6's 40-50 worlds:
    the space a policy walks is shared, the data is not.

    Because :func:`~bootstrap._stream.mix64` is a bijection (§12.1's
    reason for using a hash rather than a generator), two worlds whose
    seeds differ have different tokens and therefore disjoint feature
    blocks — the guarantee is exact rather than probabilistic, and it is
    the reason the token is mixed *outside* the address below instead of
    being folded into it, where a seed could be chosen to cancel a row.
    """
    address = row * _ROW_STRIDE + column
    return _PREFIX_FEATURE ^ token ^ (address ^ mix64(address))


def _target_cell(token: int, row: int) -> int:
    """The cell one observation's noise is drawn from — ``token`` and ``row``.

    The same construction as :func:`_feature_cell`, against the target
    prefix, so a world's noise is drawn from a block disjoint from its own
    features and from every other world's noise.  The whole 64-bit token
    enters, not a slice of it: taking the low bits would let two seeds
    that agree there share a noise sequence while their features differed,
    which is exactly the kind of partial independence the pool must not
    have.
    """
    return _PREFIX_TARGET ^ token ^ (row ^ mix64(row))


class Dataset:
    """The world's fixed dataset: a design of features and the targets.

    Rows are held as tuples in a fixed order — the *priced row order*, which
    is the dataset's own address space and never changes — and the train
    and holdout splits are *indices* into it (:func:`split_indices`).  Held
    as plain tuples of floats rather than a packed array: this is the
    world's truth and it is read once per label, not once per replay, so
    there is no residency to shrink — the ``float32`` narrowing §9.3
    specifies belongs to the artifact member's resident campaign arrays,
    which are a different object with a different lifetime.

    ``targets`` are the observed values, truth plus noise, generated by
    the same content-addressed draws as the features.  The *truth* is
    available separately (:meth:`truth_for`) so a caller can see what the
    noise was hiding, which is what makes a bootstrap world's labels
    auditable rather than merely asserted.
    """

    __slots__ = ("_features", "_targets", "seed")

    def __init__(
        self,
        *,
        features: tuple[tuple[float, ...], ...],
        targets: tuple[float, ...],
        seed: int,
    ) -> None:
        self._features = features
        self._targets = targets
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

    def feature(self, row: int, column: int) -> float:
        """One cell of the design, by priced row and feature index."""
        return self._features[row][column]

    def truth_for(self, row: int) -> float:
        """The noise-free value of the fixed model at ``row``.

        The target before :data:`NOISE_SCALE` was applied — the world's
        answer key in the literal sense, and what a caller auditing the
        pool's honesty compares a fit's residuals against.
        """
        return _model_at(self._features[row])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Dataset(rows={self.rows}, features={FEATURE_COUNT}, "
            f"seed={self.seed})"
        )


def _model_at(features: tuple[float, ...]) -> float:
    """The fixed model evaluated at one feature vector — the truth.

    Spelled once, here, so the dataset's generation and its auditable
    truth cannot drift: :meth:`Dataset.truth_for` calls this rather than
    restating the expression.
    """
    value = INTERCEPT + math.fsum(
        coefficient * feature
        for coefficient, feature in zip(LINEAR_COEFFICIENTS, features)
    )
    value += math.fsum(
        coefficient * features[left] * features[right]
        for (left, right), coefficient in INTERACTION_COEFFICIENTS.items()
    )
    value += math.fsum(
        coefficient * features[index] * features[index]
        for index, coefficient in SQUARE_COEFFICIENTS.items()
    )
    return value


def generate_dataset(seed: int) -> Dataset:
    """Generate the fixed dataset a world seed names.

    A pure function of the seed: same seed, same dataset, to the last bit,
    in any process and in any order of calls.  That totality is what lets
    the world's identity *be* its seed (§10.6.1's provenance rule has
    nothing to check) and what lets feature 188 author a pool of worlds by
    drawing seeds.

    The dataset is generated in one sweep rather than lazily per cell
    because it is the world's *fixed* half: a fit needs the whole design
    anyway, and the score is a function of the whole split, so there is no
    order a policy could reveal cells in that would change what is drawn.
    """
    rows: list[tuple[float, ...]] = []
    targets: list[float] = []
    token = mix64(seed)
    for row in range(PRICED_ROWS):
        features = []
        for column in range(FEATURE_COUNT):
            draw = normal(_feature_cell(token, row, column))
            features.append(FEATURE_SCALES[column] * draw)
        features_tuple = tuple(features)
        noise = NOISE_SCALE * normal(_target_cell(token, row))
        rows.append(features_tuple)
        targets.append(math.fsum((_model_at(features_tuple), noise)))
    return Dataset(features=tuple(rows), targets=tuple(targets), seed=seed)


def split_indices(rows: int = PRICED_ROWS) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """The world's train and holdout row indices, in priced row order.

    ``(train, holdout)``: every row whose index is not ``≡ 2 (mod 3)`` is
    trained on, every row whose index is is held out.  Interleaved rather
    than a trailing block so the holdout spans the whole feature range —
    a trailing block would score every fit on the region of the design the
    training split never saw, which measures extrapolation rather than the
    generalisation the feature is about.

    Both tuples are ascending, so a fit's ``fsum`` reductions visit rows in
    the dataset's own order and the label does not depend on how the split
    was enumerated.
    """
    train = tuple(row for row in range(rows) if row % HOLDOUT_STRIDE != HOLDOUT_STRIDE - 1)
    holdout = tuple(row for row in range(rows) if row % HOLDOUT_STRIDE == HOLDOUT_STRIDE - 1)
    return train, holdout


# --------------------------------------------------------------------------
# The design
# --------------------------------------------------------------------------


def design_columns(
    features: tuple[float, ...],
    *,
    degree: int,
    interactions: bool,
    standardize: bool,
    statistics: tuple[tuple[float, float], ...],
) -> list[float]:
    """One row's design vector: the intercept, then the model's terms.

    The column order is *fixed and documented* rather than incidental,
    because it is the order a fitted coefficient vector is read in and the
    order two designs must agree on to be compared at all:

    1. the intercept, unpenalised and always first;
    2. the ``FEATURE_COUNT`` linear terms;
    3. the ``degree``-order powers of each linear term, in feature order,
       for every power from 2 to ``degree``;
    4. when ``interactions``, every pairwise product of two *linear* terms,
       in ``(left, right)`` lexicographic order.

    The powers are taken of the *linear term* — already standardised when
    ``standardize`` — rather than of the raw feature, so a standardised
    design's columns stay on comparable scales all the way up its degree.
    That is what makes the single ``alpha`` axis meaningful across the
    whole lattice instead of only at the columns whose raw scale happened
    to suit it.

    ``statistics`` is the *training split's* per-column mean and population
    standard deviation, passed in rather than recomputed, so a holdout row
    is standardised in the training split's scale.  A holdout standardised
    against its own statistics would be measuring a different model than
    the one that was fitted — the classic leak, and the reason this
    function takes the statistics as an argument rather than deriving them.
    """
    linear: list[float] = []
    for column in range(len(features)):
        value = features[column]
        if standardize:
            mean, deviation = statistics[column]
            value = (value - mean) / deviation
        linear.append(value)

    columns: list[float] = [1.0]
    columns.extend(linear)
    for value in linear:
        for power in range(2, degree + 1):
            columns.append(value**power)
    if interactions:
        for left in range(len(linear)):
            for right in range(left + 1, len(linear)):
                columns.append(linear[left] * linear[right])
    return columns


def column_statistics(
    dataset: Dataset, train: tuple[int, ...]
) -> tuple[tuple[float, float], ...]:
    """The training split's per-column mean and population deviation.

    Population (``1/N``), not sample (``1/(N-1)``): the split is the whole
    population the model is being fitted *for*, and the two conventions
    differ by a factor that would enter every standardised column and
    therefore every coefficient — a difference with no meaning that would
    still move the numbers.  ``fsum`` throughout, so the statistics are as
    reproducible as the fit they feed.
    """
    statistics = []
    for column in range(FEATURE_COUNT):
        values = [dataset.feature(row, column) for row in train]
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        statistics.append((mean, math.sqrt(variance)))
    return tuple(statistics)


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------


class HyperparameterWorld:
    """Feature 181's world: a fixed model, a fixed dataset, honest labels.

    Constructed from a world id and a seed; the dataset is generated from
    the seed on first use, once, and held.  The world is otherwise
    *stateless with respect to asks*: no method mutates anything, no
    answer depends on which ask came before it, and two worlds built from
    one ``(world_id, seed)`` pair are interchangeable to the last bit.
    That is what §10.6's *"no dependence on market time"* means when the
    domain has no clock to depend on, and it is the reason a replay may
    reveal cells in any order and still score a policy on the same
    numbers.

    **The interface is the question interface.**  §10.6 states the
    constraint that makes a bootstrap pool worth having — *"Each exposes
    the **same** ``question.*`` API as a financial campaign, so a policy
    is portable without modification"* — and this class is the world's
    *answer surface* for it: :meth:`node_id` and :meth:`setting` address a
    cell the way §10.6.1's ``question.meta(node_id)`` does,
    :meth:`legal_moves` enumerates the neighbours the way
    ``question.legal_actions()`` does, :meth:`canonical_node` roots a walk
    the way ``question.legal_roots()`` does, and :meth:`label` reveals a
    cell's truth the way a probe does.  Feature 184 — the later feature in
    this category that states the identical-interface requirement *as* a
    feature — is where the shared policy-facing seam over *all* the
    bootstrap worlds is built; this class is the hyperparameter world's
    side of it, and deliberately carries no policy runtime, no reveal
    bookkeeping and no budget, all three of which belong to the replay
    engine and to features 184-185 rather than to a world.

    A *label* is the only thing this class answers.  Feature 185 states
    the other half of that division from the other side — *"System
    charges no statistical budget for a bootstrap world, persisting
    charges_budget as false on those trials"* — which is a statement about
    what the *trial* records, not about what the world computes, and a
    world that indexed its own budget would be a world whose labels
    depended on how often it had been asked.
    """

    __slots__ = ("_dataset", "_world_id", "seed")

    def __init__(self, world_id: str, *, seed: int = PRICED_SEED) -> None:
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
                f"({type(seed).__name__}); the seed *is* the world's "
                "identity (§10.6.1: a changed upstream is a different "
                "world), so a seed that is not an integer names no world "
                "this member can reproduce"
            )
        self._world_id = world_id
        self.seed = seed
        self._dataset: Dataset | None = None

    @property
    def world_id(self) -> str:
        """This world's id — the name its labels are attributed to."""
        return self._world_id

    @property
    def dataset(self) -> Dataset:
        """The fixed dataset, generated once from the seed and held.

        Generated lazily rather than at construction so building a world
        is free — the discipline feature 169's store and the null
        sidecar both take for their own construction, and the reason a
        pool builder can hold 40-50 worlds without paying for 40-50
        datasets it may never label against.
        """
        if self._dataset is None:
            self._dataset = generate_dataset(self.seed)
        return self._dataset

    # -- The lattice --------------------------------------------------------

    @property
    def axes(self) -> tuple[HyperparameterAxis, ...]:
        """The world's axes, in :data:`AXIS_ORDER`."""
        return AXIS_ORDER

    @property
    def canonical_setting(self) -> HyperparameterSetting:
        """The world's root — the setting a caller gets by naming nothing."""
        return HyperparameterSetting()

    def canonical_node(self) -> str:
        """The root's node id — where a policy's walk starts."""
        return canonical_node_id()

    def setting(self, node_id: str) -> HyperparameterSetting:
        """The setting a node id addresses, or the world's refusal.

        The decode is strict and the *lattice check is separate*: a node
        id that decodes cleanly may still address a cell this world does
        not hold — a step past the end of an axis — and that is the
        refusal this method adds on top of the codec's.  Kept apart so the
        two failures read differently: ``"d+9.i+0.s+0.a+0"`` is a
        well-formed address for a degree this lattice does not declare,
        while ``"junk"`` is not an address at all.
        """
        return setting_from_steps(self, decode_node_id(node_id), node_id=node_id)

    def steps(self, node_id: str) -> tuple[int, ...]:
        """The step vector a node id addresses, refused if out of lattice.

        The address *before* it is turned into a setting — which is what a
        caller composes a step onto, and what
        :meth:`~bootstrap.HyperparameterSetting.steps` reads off a setting
        it already holds.
        """
        return self.setting(node_id).steps()

    def node_id(self, setting: HyperparameterSetting) -> str:
        """The node id addressing ``setting`` in this world.

        Validates the setting against *this* world's lattice before
        encoding, so a setting built for another world — or built and then
        mutated by a caller who reached past the properties — cannot be
        handed a node id this world would answer differently from the one
        it names.
        """
        if not isinstance(setting, HyperparameterSetting):
            raise BootstrapWorldError(
                f"a node id addresses a HyperparameterSetting — got "
                f"{setting!r} ({type(setting).__name__}); a node is a point "
                "of this world's lattice, not a bare value"
            )
        return encode_node_id(setting.steps())

    def legal_moves(self, node_id: str | None = None) -> tuple[str, ...]:
        """The neighbours of ``node_id`` — one legal step along one axis.

        ``None`` (or the root's own id) answers the root's neighbours, so a
        caller can start a walk without spelling the root first.  Each
        move is *one* axis by *one* position, in either direction, filtered
        to the moves the lattice actually holds — so the answer is
        non-empty for every cell but a fully saturated corner, and a walk
        that only ever takes returned moves stays inside the world by
        construction.

        Ascending by node id, so a policy that enumerates without
        sorting still sees a deterministic order and two replays of one
        world explore identically (§12's ordering rule: explicit sorts
        before every reduction, restated for a search frontier).
        """
        origin = self.canonical_node() if node_id is None else node_id
        current = self.setting(origin)
        steps = list(current.steps())
        moves: list[str] = []
        for index, axis in enumerate(AXIS_ORDER):
            legal = HYPERPARAMETER_AXES[axis]
            for delta in (-1, 1):
                position = legal.index(current.value(axis)) + delta
                if 0 <= position < len(legal):
                    neighbour = list(steps)
                    neighbour[index] = position - legal.index(legal[0])
                    moves.append(encode_node_id(tuple(neighbour)))
        return tuple(sorted(moves))

    def legal_roots(self) -> tuple[str, ...]:
        """The node a walk may start from — §10.6.1's ``legal_roots()``.

        One entry, the canonical setting.  A single-root lattice rather
        than an empty or a multi-root answer is the *point* of rooting the
        space at a declared default: every cell is reachable from it by
        legal moves, so a policy needs no external hint about where to
        begin and two policies compared on this world begin from the same
        place.
        """
        return (self.canonical_node(),)

    def depth(self, node_id: str) -> int:
        """How many legal moves the node is from the root — ``Σ|step|``."""
        return self.setting(node_id).depth

    # -- The label ----------------------------------------------------------

    def label(self, node_id: str) -> FitResult:
        """The node's ground-truth score — the feature's headline.

        Fits the world's fixed model to the world's fixed dataset with the
        node's hyperparameters, and answers the held-out ``R²``
        (:attr:`~bootstrap._fit.FitResult.r2_holdout`) beside the training
        ``R²`` and the fitted coefficients.  Every input is either the
        world's own fixed state or the node's address, so the answer is a
        pure function of ``(world, node)``: the same node labelled twice,
        or labelled after any number of other nodes, answers the identical
        number — which is what makes it a *ground truth* rather than a
        measurement.

        Refuses with :class:`~bootstrap.errors.BootstrapWorldError` for a
        node outside the lattice, and would refuse with
        :class:`~bootstrap.errors.BootstrapScoringError` for a cell the
        dataset could not support a fit at — unreachable on a world built
        with the default ridge, which keeps every cell of the lattice
        answerable, but carried through from :mod:`bootstrap._fit` so a
        caller's ``except`` is not written against a promise the
        arithmetic does not keep.  Both name the world and the node, so a
        refusal read off a replay's log says which pool entry had no label
        rather than merely that something did not fit.
        """
        if not isinstance(node_id, str) or not node_id:
            # The root is *spelled*, not defaulted: a caller that wants the
            # canonical setting asks for it by name, the same discipline
            # §10.6.1 applies to ``commit``.  A default here would make a
            # missing argument look like a deliberate root ask, and a
            # replay's scores would silently all come from one cell.
            raise BootstrapWorldError(
                f"label() needs the node id to label — got {node_id!r}; the "
                "world's root is a node like any other and is asked for by "
                f"name ({self.canonical_node()!r} on this world), because a "
                "defaulted argument would let a missing one answer the same "
                "label as a deliberate root ask"
            )
        return self.label_setting(self.setting(node_id), node_id=node_id)

    def label_setting(
        self, setting: HyperparameterSetting, *, node_id: str | None = None
    ) -> FitResult:
        """The label for a setting already in hand — the fit, spelled once.

        Answers the world's truth when the address is one this world
        holds, and the design must be built identically however the
        address arrived.  Both callers — :meth:`label` for a node id,
        :meth:`label_all` for a sweep of the lattice — route through this,
        so "a node's label" has exactly one implementation and a sweep
        cannot drift from a single ask.

        The design's ``standardize`` statistics are taken from the
        *training split* whichever way the model is built — so a setting
        with ``standardize=False`` is still fitted in the raw scale while
        a setting with it on is fitted in the training split's, and the
        difference between the two cells is the hyperparameter rather than
        a leak.
        """
        subject = (
            f"node {node_id!r} of world {self._world_id!r}"
            if node_id is not None
            else f"setting {setting.row()!r} of world {self._world_id!r}"
        )
        dataset = self.dataset
        train, holdout = split_indices(dataset.rows)
        statistics = column_statistics(dataset, train)
        design_train = [
            design_columns(
                dataset.features[row],
                degree=setting.degree,
                interactions=setting.interactions,
                standardize=setting.standardize,
                statistics=statistics,
            )
            for row in train
        ]
        design_holdout = [
            design_columns(
                dataset.features[row],
                degree=setting.degree,
                interactions=setting.interactions,
                standardize=setting.standardize,
                statistics=statistics,
            )
            for row in holdout
        ]
        return fit_and_score(
            design_train=design_train,
            targets_train=[dataset.targets[row] for row in train],
            design_holdout=design_holdout,
            targets_holdout=[dataset.targets[row] for row in holdout],
            ridge=setting.alpha,
            subject=subject,
        )

    def label_all(self) -> Iterator[tuple[str, FitResult | BootstrapScoringError]]:
        """Every cell of the lattice, labelled — the world's ground truth.

        Ascending by node id, and *total*: a cell whose fit refuses yields
        the refusal rather than aborting the sweep, so a caller auditing
        the whole space (a pool report, a test pinning the optimum, the
        calibration reference §10.6 makes the bootstrap pool) sees the
        world's full landscape rather than a prefix of it, and a world
        configured with a ridge that does leave a corner unanswerable
        still reports that corner instead of silently stopping there.

        Yields ``(node_id, label)`` pairs where the label is either a
        :class:`~bootstrap._fit.FitResult` or the
        :class:`~bootstrap.errors.BootstrapScoringError` that cell raised.
        A generator rather than a dict so the caller chooses what to keep
        — labelling the whole space is the world's most expensive
        operation, and a caller that wants only the argmax should not have
        to hold every cell's coefficients.
        """
        for node_id in self.cells():
            try:
                yield node_id, self.label(node_id)
            except BootstrapScoringError as refusal:
                yield node_id, refusal

    def cells(self) -> tuple[str, ...]:
        """Every node id of the lattice, ascending — the world's whole space.

        The product of the axes' legal values, addressed by the same codec
        every other node is, sorted so two enumerations of one world
        agree.  Includes the root, and every cell of the lattice — the
        lattice is what the world *answers for*, so the enumeration is the
        space rather than the subset a particular ridge happens to make
        fit.
        """
        settings: list[HyperparameterSetting] = [HyperparameterSetting()]
        for axis in AXIS_ORDER:
            legal = HYPERPARAMETER_AXES[axis]
            if len(legal) == 1:
                continue
            grown: list[HyperparameterSetting] = []
            for setting in settings:
                for value in legal:
                    grown.append(setting.with_value(axis, value))
            settings = grown
        return tuple(sorted(self.node_id(setting) for setting in settings))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"HyperparameterWorld(world_id={self._world_id!r}, "
            f"seed={self.seed!r}, cells={len(self.cells())})"
        )


def setting_from_steps(
    world: HyperparameterWorld,
    steps: tuple[int, ...],
    *,
    node_id: str,
) -> HyperparameterSetting:
    """Turn a decoded step vector into a setting, or refuse it as out of lattice.

    The one place the lattice bound is enforced on the way *in* from a
    node id, so :meth:`HyperparameterWorld.setting` and
    :meth:`HyperparameterWorld.steps` cannot disagree about which cells
    the world holds.  A step that walks past either end of its axis is
    refused with the axis and the attempted position named.
    """
    values: dict[HyperparameterAxis, Any] = {}
    for axis, step in zip(AXIS_ORDER, steps):
        legal = HYPERPARAMETER_AXES[axis]
        position = step + legal.index(legal[0])
        if not 0 <= position < len(legal):
            raise BootstrapWorldError(
                f"the node id {node_id!r} addresses {axis.value}={step:+d} "
                f"step(s) from this world's root, which is past the end of "
                f"the {axis.value!r} axis — the lattice declares "
                f"{_render(legal)}; the space is bounded because an axis is "
                "a declaration of what the world answers for, and a "
                "hyperparameter outside it names a model nobody has agreed "
                "to score"
            )
        values[axis] = legal[position]
    return HyperparameterSetting(
        degree=values[HyperparameterAxis.DEGREE],
        interactions=values[HyperparameterAxis.INTERACTIONS],
        standardize=values[HyperparameterAxis.STANDARDIZE],
        alpha=values[HyperparameterAxis.ALPHA],
    )
