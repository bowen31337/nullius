"""The feature selection world — feature 182's labeled benchmarks.

app_spec.xml, "Bootstrap Worlds", feature 182: *System exposes a feature
selection world over labeled machine-learning benchmarks, which returns a
ground-truth objective per node.*  docs/nullius-tech-architecture.md §10.6
names the domain in its own tree — ``featsel/  # feature selection on
labeled ML benchmarks`` — second of the three authored branches, and
states the constraint every one of them answers to: *"Each exposes the
**same** ``question.*`` API as a financial campaign, so a policy is
portable without modification."*

**Feature selection, and what makes this world one.**  Feature selection
searches the space of *subsets*: given a labeled benchmark — features and
a label for each row — it asks which features a fixed model should be fit
on, because the features a model is *given* are as much a modelling
decision as any coefficient.  So a node of this world is a **subset**,
addressed as a point of a lattice exactly the way a hyperparameter
setting is in :mod:`bootstrap._world` and a candidate structure is in
:mod:`bootstrap._symreg`.  The subset is chosen block by block, four
axes of three levels each, and the blocks are the honest anatomy of a
labeled benchmark's columns:

* **``strong``** — the decisive feature, a *choice*: none, ``x0``, or
  ``x1``.  The benchmark's label is drawn from exactly one of the two,
  and which one is the world's own draw (see :func:`support_for_seed`),
  so the axis carries a *wrong middle value* exactly the way the
  symbolic lattice's do: level 1 is a real feature of the benchmark
  that a world whose truth chose level 2 does not carry, and a policy
  that walks one step up the axis and stops at the first thing that
  sounds like progress has added a column and recovered nothing.
* **``weak``** — the weakly relevant block, a *growth*: none, ``x2``, or
  ``x2+x3``, small published magnitudes that explain a fraction of the
  label's variance far below the evidential bar on their own.
* **``proxy``** — the redundant block: none, ``x4``, or ``x4+x5``, where
  ``x4`` is a correlation-:data:`PROXY_CORRELATION` copy of ``x0`` and
  ``x5`` of ``x1`` — features that *correlate* with the label through
  the strong candidate they copy while carrying no signal of their own
  beside it.  This is the axis the domain exists to teach: **marginal
  correlation is not conditional relevance**, the trap every feature
  selection procedure is judged by.  A proxy looks good — it genuinely
  improves a training fit when the feature it copies is missing, and it
  is the *only* block of the lattice with that property — and it is
  worth nothing beside the feature it copies, because the copy adds to
  the design only the independent noise it was blended with.
* **``noise``** — the distractor block: none, ``x6``, or ``x6+x7``,
  features drawn independently of everything.  Pure width, the
  direction a subset grows *away* from the label, priced by the held-out
  split the training split does not see.

**The benchmark is labeled, and it is generated.**  The feature's own
clause is *"over labeled machine-learning benchmarks"*, and a benchmark
is labels plus features — no generative formula is part of what a caller
is handed when they download one.  The world draws its benchmark from
its seed in the same discipline as every other authored world
(:mod:`bootstrap._stream`'s content addressing), and it *publishes* the
sparse linear truth the labels were drawn from — the
:class:`FeatureSupport`, the support of the label's non-zero
coefficients, named for the vocabulary sparse modelling uses — because a
bootstrap world's answer is *supposed* to be known (§10.6: the worlds
*"give perfect labels"*) and the support is the part of that answer a
policy's commits can be audited against: :meth:`LabeledBenchmark.truth_for`
hands the noise-free value the noise was hiding, the way the symbolic
world's dataset does against its target.  A caller that wants a
*specific* support may plant one instead, and the world refuses a
support its lattice cannot express — see :class:`FeatureSupport`.
That the benchmark is generated rather than fetched is a property of the
feature, not a shortcut, and for the reason :mod:`bootstrap._world`
states: §10.6 needs 40-50 bootstrap worlds *on demand*, and a world that
had to be fetched could not be authored at that rate.

**The label is the objective, and the word is the feature's own.**  The
sibling features return a ground-truth *score*; this one returns a
ground-truth *objective*, and the difference is the point.  A score is
what a world hands back; an objective is what a search defines itself as
optimizing, and feature selection defines itself as optimizing the fixed
model's out-of-sample performance over the chosen subset.  On this world
those are one number: :meth:`FeatureSelectionWorld.label` fits the
subset's columns by least squares on the training split and answers the
held-out ``R²`` — the same :class:`~bootstrap._fit.FitResult`, computed
by the same :func:`~bootstrap._fit.fit_and_score` in the same
exactly-rounded arithmetic, as the hyperparameter and symbolic worlds
return — so a featsel node's objective and an hpo node's score are the
same *kind* of number, one scale across the pools, and the objective is
*ground truth* because nothing in it is estimated: the benchmark is
fixed by the seed, the split is fixed by the row count, the fit is
honest, and two policies reaching one cell read the identical number
whatever path they took.

**The lattice is deceptive on purpose.**  The ``strong`` axis carries
the wrong middle, as above.  The ``proxy`` axis carries the subtler
deception — the only block of the lattice whose features correlate with
the label at all while the truth carries none of them — so a greedy
procedure that ranks columns by their marginal association with the
label, the first instinct of every feature selection pipeline, is *told*
by that ranking to spend its width on copies rather than on finding the
feature being copied.  And the ``noise`` axis is deliberately the
quietest of the four, for the same reason the hyperparameter world's
``standardize`` axis and the symbolic world's ``spurious`` axis are: a
lattice where every axis paid equally would be a lattice where search
policy does not matter (see :mod:`bootstrap._world`'s *"the axes are
not independent"*).

**The seams are the category's, ridden not rebuilt.**  The world owns
the same answer surface :func:`~bootstrap.question_for` duck-types over
— ``label``, ``legal_moves``, ``legal_roots``, ``canonical_node``,
``steps``, ``world_id`` — so the identical
:class:`~bootstrap.BootstrapQuestion` wraps it with no change to
feature 184's module, and :func:`~bootstrap.ground_truth` labels every
cell through the same ``cells()`` / ``label()`` / ``world_id`` surface
it reads off every other bootstrap world.  The one thing the shared
adapter cannot answer for this domain is the *family*: §11.1 exposes
``theme_root`` in ``meta()`` because the overfit signature is only
partly family-invariant, and a feature selection node is a member of
the ``featsel`` family, not the ``hpo`` one — so
:class:`FeatureSelectionQuestion` inherits feature 184's adapter whole
and re-answers exactly the one method whose content is per-domain,
:meth:`meta`.  Everything a policy calls — ``observed``,
``legal_actions``, ``legal_roots``, ``probe_batch``,
``budget_remaining``, ``commit`` — is the inherited, unmodified
interface.

**What this module deliberately does not ship.**  It draws no pool and
seats no rows: feature 188's writer authors the replay pool, and the
``domain`` column its table already carries is where a ``featsel`` row
will join it (:data:`FEATSEL_DOMAIN` is the value, spelled by §10.6's
own tree).  It charges no budget and consults no clock (§10.6's
zero-cost, market-time-free clauses, statements about the category).
It holds no reveal history — a world whose answers depended on how often
it had been asked would not be a ground truth, which is why the reveal
bookkeeping lives in the question and the *one* thing this world adds
to the hyperparameter world's shape is the published support its labels
are audited against.

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
    "FEATSEL_COMPONENT_NAME",
    "FEATSEL_DOMAIN",
    "FEATSEL_FEATURE_COUNT",
    "FEATSEL_INTERCEPT",
    "FEATSEL_NOISE_SCALE",
    "FEATSEL_RIDGE",
    "FEATSEL_ROWS",
    "FEATSEL_SEED",
    "FEATSEL_THEME_ROOT",
    "FEATSEL_WORLD_ID",
    "FEATURE_AXES",
    "FEATURE_AXIS_ORDER",
    "NOISE_TERMS",
    "PROXY_CORRELATION",
    "PROXY_TERMS",
    "STRONG_MAGNITUDE",
    "STRONG_TERMS",
    "WEAK_MAGNITUDES",
    "WEAK_TERMS",
    "FeatureAxis",
    "FeatureQuestion",
    "FeatureSelectionWorld",
    "FeatureSetting",
    "FeatureSupport",
    "LabeledBenchmark",
    "canonical_featsel_node_id",
    "decode_featsel_node_id",
    "encode_featsel_node_id",
    "featsel_question_for",
    "featsel_setting_dimensions",
    "generate_benchmark",
    "support_for_seed",
]

#: How many features the world's fixed benchmark has.  Eight, two per
#: axis of the lattice, because the vocabulary above spans exactly
#: eight: the two strong candidates, the two weakly relevant columns,
#: the two proxies copying the candidates, and the two distractors —
#: every feature is load-bearing to some axis, and a ninth would be a
#: column no block of the lattice can reach.
FEATSEL_FEATURE_COUNT = 8

#: How many observations the fixed benchmark holds.  The hyperparameter
#: world's own row count, for the same reason it is fixed there: the
#: benchmark is the world's *fixed* half, and the interleaved
#: two-thirds split (:func:`~bootstrap._world.split_indices`, shared)
#: seats 64 train rows against 32 held-out — the same holdout precision
#: on every domain of the category, so a sensitivity read off one pool
#: and a sensitivity read off another carry the same sampling error.
FEATSEL_ROWS = 96

#: The standard deviation of the label noise, in units of the label's
#: own spread.  Sized against :data:`STRONG_MAGNITUDE` and
#: :data:`PROXY_CORRELATION` so the world's difficulty sits where the
#: domain's question is: a subset carrying the drawn support clears the
#: published evidential bar (:data:`~bootstrap.DISCOVERY_BAR`) with
#: margin on every seed of the pool band, while a subset that has found
#: only the proxies — the copies, the marginal correlation without the
#: conditional relevance — sits *near* the bar and straddles it from
#: seed to seed, so where the class boundary falls is a fact about the
#: world's drawn coefficients rather than a constant of the domain
#: (pinned by this member's tests over that band, the way
#: :data:`~bootstrap._symreg.SYMREG_NOISE_SCALE` is).
FEATSEL_NOISE_SCALE = 1.3

#: The intercept every drawn support carries.  A constant rather than a
#: drawn one: the intercept is completed by the least-squares fit like
#: every other coefficient, so varying it would vary nothing a policy
#: can observe, and a published constant keeps the drawn support's
#: *membership* the only thing the seed chooses.
FEATSEL_INTERCEPT = 1.0

#: The magnitude of the drawn support's strong coefficient — the one
#: load-bearing weight, on exactly one of the two strong candidates.
#: Dominant by design: feature selection's honest shape is a problem
#: where finding the decisive column is the discovery and everything
#: else is refinement, and a support whose weight were spread evenly
#: would be a problem where the subset mattered less than the fit.
#: Dominant *enough* that the decisive column alone clears the bar on
#: every seed of the pool band — finding it is the discovery, the whole
#: of it, and the rest of the lattice is what a policy does after.
STRONG_MAGNITUDE = 2.8

#: The magnitudes of the drawn support's weak coefficients, in the weak
#: block's own order.  Small by design: the weak block alone explains a
#: fraction of the label's variance far below the bar, so a subset that
#: has recovered only the weakly relevant columns is a null and the
#: axis is refinement rather than a second road to a discovery.
WEAK_MAGNITUDES = (0.5, 0.35)

#: The correlation each proxy shares with the strong candidate it
#: copies — the one number that makes the proxy axis what it is.  A
#: proxy carries ``ρ²`` of the candidate's variance marginally, so at
#: ``0.5`` a subset standing on the copies alone recovers a quarter of
#: what the feature being copied recovers: enough to look like a lead —
#: enough to *be* one, on the training split — and not enough to reach
#: the bar without the feature itself, which is exactly the marginal-
#: versus-conditional gap the axis exists to price.  The blend is
#: ``ρ·x + √(1−ρ²)·e`` with ``e`` a fresh draw, so a proxy is
#: marginally standard (unit variance) and conditionally pure noise
#: beside its original.
PROXY_CORRELATION = 0.5

#: The ridge every featsel fit is solved with — a constant of the world,
#: not an axis of the lattice.  The search object is the subset, and the
#: ridge is the numerical floor that keeps every subset answerable: a
#: positive constant on the diagonal makes the completed fit total
#: whatever the subset's columns, the same guarantee
#: :data:`~bootstrap._symreg.SYMREG_RIDGE` makes for that lattice, held
#: fixed so two subsets' objectives differ by the subsets alone.
FEATSEL_RIDGE = 0.01

#: The seed of the committed world — the one the component builder
#: composes.  A stable integer in the committed world's own convention
#: (the date the domain was authored), so the committed world and the
#: committed tests describe one world.  The calendar date it spells is
#: shared with the symbolic world's seed and deliberately so: the two
#: domains' draws live in disjoint address blocks (:data:`
#: _PREFIX_FEATSEL_FEATURE` and friends), so the equality is a
#: coincidence of the calendar and not a coupling of the draws.
FEATSEL_SEED = 20260922

#: The world id of the committed feature selection world — the
#: ``bootstrap-<domain>-<date>`` convention the hyperparameter world's
#: own id (:data:`~bootstrap.HYPERPARAMETER_WORLD_ID`) sets, with the
#: domain spelled by §10.6's tree so a report reading the two pools
#: apart sees a featsel node as a member of its domain.
FEATSEL_WORLD_ID = "bootstrap-featsel-20260922"

#: The domain this world belongs to, in §10.6's own tree vocabulary
#: (``featsel/  # feature selection on labeled ML benchmarks``).  A
#: value this member publishes and a later pool authoring seats under
#: the ``domain`` column the bootstrap world table already carries — the
#: column exists so this domain could join it (see :mod:`bootstrap.
#: _pool`'s "What this module deliberately does not ship").
FEATSEL_DOMAIN = "featsel"

#: The structural family a featsel node belongs to, reported on every
#: :class:`~bootstrap.CellMeta` this domain's question hands a policy.
#: §11.1's family conditioning is the reason the value exists: the
#: overfit signature is only partly family-invariant, a policy writes
#: family-conditional thresholds, and a feature selection node must be
#: legible to that policy as ``featsel`` — not folded into the
#: hyperparameter domain's family, which is the mistake a shared adapter
#: that hardcoded one root would make (see :class:`FeatureQuestion`).
FEATSEL_THEME_ROOT = "featsel"

#: The component name this domain registers under — its own name rather
#: than a second face on ``"bootstrap"``, the convention the pool's own
#: seat (:data:`~bootstrap.POOL_COMPONENT_NAME`) states: the world seat
#: answers *what is the composed bootstrap world?*, the pool seat *what
#: is the composed bootstrap pool?*, the symbolic seat *what is the
#: composed symbolic regression world?*, and this one *what is the
#: composed feature selection world?* — four facts on different
#: lifecycles that a caller asks for by name, and a registry key is a
#: name.
FEATSEL_COMPONENT_NAME = "bootstrap-featsel"


class FeatureAxis(enum.StrEnum):
    """The four axes of the feature lattice, in the order steps compose.

    A :class:`~enum.StrEnum` for the reason
    :class:`~bootstrap.HyperparameterAxis` is: the axis a step moved is
    *read* — by a policy reasoning about which block to widen next, by a
    test asserting the lattice's shape — and a bare ``str`` would let a
    typo address an axis that does not exist while comparing equal to
    the one that does.  The declaration order is load-bearing and is
    :data:`FEATURE_AXIS_ORDER`'s: the step vector that addresses a node
    is spelled in this order, so the addressing is stable and a reader
    can see at a glance which dimension the third entry moves.
    """

    #: The decisive feature — a choice between the two candidates.
    STRONG = "strong"

    #: The weakly relevant block, entered one column at a time.
    WEAK = "weak"

    #: The redundant block — copies of the strong candidates.
    PROXY = "proxy"

    #: The distractor block — features the label never touches.
    NOISE = "noise"


#: The axes in declaration order — the one spelling of the vector's layout.
FEATURE_AXIS_ORDER: tuple[FeatureAxis, ...] = (
    FeatureAxis.STRONG,
    FeatureAxis.WEAK,
    FeatureAxis.PROXY,
    FeatureAxis.NOISE,
)

#: The legal levels of each axis, in ascending order.  Every axis
#: declares the same three — ``0`` selects nothing, ``1`` and ``2``
#: carry the two selections the axis names — and the levels *mean* the
#: blocks the tables below spell: a growth block's level 2 strictly
#: contains its level 1 (a walk up the axis is a widening subset), and
#: a choice block's levels are two different columns (so the axis
#: teaches *which* candidate the truth carries, and level 1 is a real
#: feature that a world whose support chose level 2 does not carry).
FEATURE_AXES: dict[FeatureAxis, tuple[int, ...]] = {
    FeatureAxis.STRONG: (0, 1, 2),
    FeatureAxis.WEAK: (0, 1, 2),
    FeatureAxis.PROXY: (0, 1, 2),
    FeatureAxis.NOISE: (0, 1, 2),
}

#: What each ``strong`` level selects: nothing, ``x0``, or ``x1`` — a
#: *choice*, not a growth, and the wrong-middle axis of this lattice for
#: the same reason the symbolic world's ``curvature`` is: a policy that
#: stops at level 1 on a world whose support chose level 2 has added a
#: column and recovered nothing.
STRONG_TERMS: tuple[tuple[int, ...], ...] = ((), (0,), (1,))

#: What each ``weak`` level selects: nothing, ``x2``, or ``x2`` and
#: ``x3`` — a growing block, ordered by its own meaning (level 2
#: strictly contains level 1), so a walk up the axis is a widening
#: subset rather than a different one.
WEAK_TERMS: tuple[tuple[int, ...], ...] = ((), (2,), (2, 3))

#: What each ``proxy`` level selects: nothing, ``x4``, or ``x4`` and
#: ``x5`` — the copies.  No drawn support ever carries these columns:
#: they correlate with the label through the strong candidate they copy
#: and carry nothing beside it, which is the marginal-versus-conditional
#: gap the axis exists to price.
PROXY_TERMS: tuple[tuple[int, ...], ...] = ((), (4,), (4, 5))

#: What each ``noise`` level selects: nothing, ``x6``, or ``x6`` and
#: ``x7``.  Features drawn independently of everything — pure width,
#: the direction a subset grows away from the label, and the one the
#: held-out split prices while the training split rewards it.
NOISE_TERMS: tuple[tuple[int, ...], ...] = ((), (6,), (6, 7))

#: Every column the lattice can select, mapped to the axis whose level
#: carries it — the universe a support's terms must live in for the
#: world to hold a cell that recovers them.  Built from the tables
#: rather than spelled again, so a table edit cannot leave the map
#: behind.
_FEATURE_AXIS: dict[int, FeatureAxis] = {
    feature: axis
    for axis, table in (
        (FeatureAxis.STRONG, STRONG_TERMS),
        (FeatureAxis.WEAK, WEAK_TERMS),
        (FeatureAxis.PROXY, PROXY_TERMS),
        (FeatureAxis.NOISE, NOISE_TERMS),
    )
    for level in table
    for feature in level
}


def _render_feature(feature: int) -> str:
    """Render one feature as the text a report and a refusal speak.

    ``x0``, ``x4`` — the one spelling of a column, used by the
    setting's text, the support's text and the refusals below, so the
    three cannot name one feature three ways.
    """
    return f"x{feature}"


def _validated_feature(value: Any, *, owner: str) -> int:
    """Check a feature index and return it as a plain int.

    The one spelling of what a support's term must be — an integer
    index of the benchmark's columns — shared by
    :class:`FeatureSupport`'s validation so a column the setting tables
    hold and a column a support holds are checked by the same rule.  A
    ``bool`` is refused where an index belongs for the reason
    :class:`~bootstrap.HyperparameterSetting` refuses one on an axis:
    ``True`` is ``1`` in Python, and a flag would silently name the
    second candidate rather than failing.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise BootstrapWorldError(
            f"{owner} names its features by index — got {value!r} "
            f"({type(value).__name__}); a support weights whole columns, "
            "and a value that is not an integer names no column of any "
            "benchmark"
        )
    if not 0 <= value < FEATSEL_FEATURE_COUNT:
        raise BootstrapWorldError(
            f"{owner} names a feature of this world's benchmark — got "
            f"{value!r}, and the benchmark holds "
            f"{FEATSEL_FEATURE_COUNT} features "
            f"(x0..x{FEATSEL_FEATURE_COUNT - 1})"
        )
    return value


@dataclass(frozen=True)
class FeatureSupport:
    """The world's known truth — a sparse linear support, spelled in full.

    A frozen value, because the support is the *recorded fact* a world's
    every label is audited against: two callers holding one support must
    hold the same truth, and a subset's objective is checkable against
    it (:meth:`evaluate` is the truth's own arithmetic, the thing
    :meth:`LabeledBenchmark.truth_for` hands a caller who wants to see
    what the noise was hiding).

    ``terms`` is a tuple of ``(feature, coefficient)`` pairs, sorted
    into a canonical order at construction, so a support is equal by its
    terms as a *set* — the same order-freedom a declaration and a
    labeling are built with — and ``intercept`` is the constant the
    truth adds.  The features are the lattice's own vocabulary, and
    construction enforces that: every term must be a column some axis's
    level selects, and within each axis the terms must fit inside one
    level, because a support the lattice cannot express is a support no
    cell can recover — the world would hold no oracle and the answer key
    would name a cell outside the space, which is the one configuration
    a ground-truth world must refuse rather than score around.  A
    support with no terms at all is refused for the plainer reason that
    it names no structure to find: every cell would explain nothing,
    every objective would sit at the noise floor, and the world would be
    a lottery rather than a search problem.
    """

    intercept: float
    terms: tuple[tuple[int, float], ...]

    def __post_init__(self) -> None:
        if isinstance(self.intercept, bool) or not isinstance(
            self.intercept, (int, float)
        ):
            raise BootstrapWorldError(
                f"a support's intercept is a real constant — got "
                f"{self.intercept!r} ({type(self.intercept).__name__}); the "
                "intercept is part of the truth a subset is scored "
                "against, and a value that is not a number is not part "
                "of any expression"
            )
        if not math.isfinite(float(self.intercept)):
            raise BootstrapWorldError(
                f"a support's intercept is a finite constant — got "
                f"{self.intercept!r}; a non-finite truth scores no "
                "subset honestly"
            )
        if not self.terms:
            raise BootstrapWorldError(
                "a support carries at least one term — an intercept "
                "alone names no structure to find, and a world whose "
                "truth is a constant would hold no search problem and "
                "no class boundary, only noise"
            )
        checked: list[tuple[int, float]] = []
        seen: set[int] = set()
        for feature, coefficient in self.terms:
            owner = "a support"
            column = _validated_feature(feature, owner=owner)
            if isinstance(coefficient, bool) or not isinstance(
                coefficient, (int, float)
            ):
                raise BootstrapWorldError(
                    f"{owner} weights {_render_feature(column)!r} with a "
                    f"real coefficient — got {coefficient!r} "
                    f"({type(coefficient).__name__}); the weight is part "
                    "of the truth the fit recovers, and a value that is "
                    "not a number weighs nothing"
                )
            if not math.isfinite(float(coefficient)):
                raise BootstrapWorldError(
                    f"{owner} weights {_render_feature(column)!r} with a "
                    f"finite coefficient — got {coefficient!r}; a "
                    "non-finite weight makes every objective a fact "
                    "about the arithmetic rather than about the subset"
                )
            if float(coefficient) == 0.0:
                raise BootstrapWorldError(
                    f"{owner} carries {_render_feature(column)!r} at "
                    "weight 0 — a column weighted nothing names no term, "
                    "and a support that held one would be spelled longer "
                    "than the truth it is"
                )
            if column in seen:
                raise BootstrapWorldError(
                    f"{owner} carries {_render_feature(column)!r} twice — "
                    "two weights on one column are one term of the truth "
                    "and must be spelled as one"
                )
            seen.add(column)
            checked.append((column, float(coefficient)))
        # The lattice-expressibility check: every term must be a column
        # one of the axis tables selects, and per axis the terms must
        # fit inside a single level — the oracle cell is the cell at
        # those levels, so a support that failed this would be a truth
        # the space cannot reach and no policy could ever recover.
        per_axis: dict[FeatureAxis, set[int]] = {}
        for column, _ in checked:
            axis = _FEATURE_AXIS.get(column)
            if axis is None:
                raise BootstrapWorldError(
                    f"the lattice cannot express the term "
                    f"{_render_feature(column)!r} — this world's vocabulary "
                    f"is the four axis tables (strong over x0/x1, weak "
                    f"over x2/x3, proxy over x4/x5, noise over x6/x7); a "
                    "support outside it names a truth no cell can "
                    "recover, so the world would hold no oracle and its "
                    "answer key would point outside its own space"
                )
            per_axis.setdefault(axis, set()).add(column)
        for axis, columns in per_axis.items():
            table = {
                FeatureAxis.STRONG: STRONG_TERMS,
                FeatureAxis.WEAK: WEAK_TERMS,
                FeatureAxis.PROXY: PROXY_TERMS,
                FeatureAxis.NOISE: NOISE_TERMS,
            }[axis]
            if not any(columns <= set(level) for level in table):
                spelled = ", ".join(_render_feature(c) for c in sorted(columns))
                raise BootstrapWorldError(
                    f"the lattice cannot carry {spelled!r} together on "
                    f"its {axis.value!r} axis — the axis declares one "
                    "level per selection, and a support asking for two "
                    "of them names a truth no single cell can recover"
                )
        object.__setattr__(
            self, "terms", tuple(sorted(checked, key=lambda term: term[0]))
        )
        object.__setattr__(self, "intercept", float(self.intercept))

    @property
    def features(self) -> tuple[int, ...]:
        """The columns the truth carries, ascending — the support itself.

        The set a feature selection procedure is asked to find, read off
        the terms rather than stored beside them, so the support and its
        weights cannot drift.
        """
        return tuple(feature for feature, _ in self.terms)

    def evaluate(self, features: tuple[float, ...]) -> float:
        """The truth's value at one feature vector — in ``fsum``.

        The label's own arithmetic, spelled once: the benchmark's
        generation and its auditable ``truth_for`` both call this rather
        than restating the truth, so the generated labels and the
        published answer cannot drift (:meth:`SymbolicRegressionWorld`
        spells the same discipline for its target, and
        :func:`bootstrap._world._model_at` for the hyperparameter
        world's model).
        """
        return math.fsum(
            (
                self.intercept,
                *(
                    coefficient * features[feature]
                    for feature, coefficient in self.terms
                ),
            )
        )

    @property
    def text(self) -> str:
        """The truth as a policy or an operator reads it.

        ``1 + 2.6*x1 + 0.5*x2`` — the known support, spelled in the same
        column vocabulary the settings and the lattice tables speak,
        because a truth a caller cannot read is not a *known* one in the
        sense the category's published constants stand on.
        """
        parts = [f"{self.intercept:g}"]
        for feature, coefficient in self.terms:
            sign = "-" if coefficient < 0 else "+"
            parts.append(f"{sign} {abs(coefficient):g}*{_render_feature(feature)}")
        return " ".join(parts)

    def row(self) -> dict[str, Any]:
        """The support as a store-shaped mapping — a fresh dict per call.

        What a report or a pool row writes down for a world's truth: the
        intercept, and each column with its weight.  Fresh per call,
        never shared, for the reason a frozen value's ``row()`` is
        always fresh.
        """
        return {
            "intercept": self.intercept,
            "terms": tuple(
                (_render_feature(feature), coefficient)
                for feature, coefficient in self.terms
            ),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"FeatureSupport({self.text!r})"


# --------------------------------------------------------------------------
# The lattice's addressing
# --------------------------------------------------------------------------


def featsel_setting_dimensions() -> tuple[str, ...]:
    """The feature lattice's axes as wire spellings, in declaration order."""
    return tuple(axis.value for axis in FEATURE_AXIS_ORDER)


class FeatureSetting:
    """One point of the feature lattice: a level for each of the four axes.

    Immutable and *ordered* — the levels are held in
    :data:`FEATURE_AXIS_ORDER`, so two settings that name one point are
    equal and hash alike whatever keyword order built them, and a set of
    them is a set of cells.  Levels are validated at construction
    against :data:`FEATURE_AXES`, so a setting that holds is a setting
    the world has agreed to score; a ``bool`` is refused where a level
    is expected because ``True`` is ``1`` in Python and would silently
    ask for the lattice's first selection instead of failing.

    The columns a level *means* are read through the axis tables
    (:attr:`features`), never stored beside the levels, so the setting
    and the vocabulary cannot disagree.
    """

    __slots__ = ("_values",)

    #: The four axis tables, keyed by axis — a read-only class fact,
    #: held at class scope so every setting reads the one vocabulary.
    _TABLES: ClassVar[dict[FeatureAxis, tuple[tuple[int, ...], ...]]] = {
        FeatureAxis.STRONG: STRONG_TERMS,
        FeatureAxis.WEAK: WEAK_TERMS,
        FeatureAxis.PROXY: PROXY_TERMS,
        FeatureAxis.NOISE: NOISE_TERMS,
    }

    def __init__(
        self,
        *,
        strong: Any = 0,
        weak: Any = 0,
        proxy: Any = 0,
        noise: Any = 0,
    ) -> None:
        requested = {
            FeatureAxis.STRONG: strong,
            FeatureAxis.WEAK: weak,
            FeatureAxis.PROXY: proxy,
            FeatureAxis.NOISE: noise,
        }
        resolved: list[Any] = []
        for axis in FEATURE_AXIS_ORDER:
            legal = FEATURE_AXES[axis]
            value = requested[axis]
            if isinstance(value, bool):
                raise BootstrapWorldError(
                    f"the {axis.value!r} axis is a level — got {value!r}, "
                    "which is a flag; True is 1 in Python, so a flag "
                    "would silently ask for the axis's first selection "
                    "instead of failing"
                )
            if value not in legal:
                raise BootstrapWorldError(
                    f"{value!r} is not a level of the {axis.value!r} axis "
                    f"— this lattice declares {', '.join(str(level) for level in legal)}"
                    f", level per selection; a level outside the "
                    "declaration names a subset nobody agreed to score"
                )
            resolved.append(value)
        self._values = tuple(resolved)

    @property
    def values(self) -> tuple[Any, ...]:
        """The node's coordinates, in :data:`FEATURE_AXIS_ORDER` — read-only."""
        return self._values

    def value(self, axis: FeatureAxis) -> int:
        """This setting's level on ``axis``."""
        return self._values[FEATURE_AXIS_ORDER.index(axis)]

    @property
    def features(self) -> tuple[int, ...]:
        """The columns this setting's subset holds, in axis order.

        Read off the tables rather than stored, so the vocabulary and
        the setting cannot drift; the design's intercept column is not a
        feature and is not listed.
        """
        columns: list[int] = []
        for axis, level in zip(FEATURE_AXIS_ORDER, self._values):
            columns.extend(self._TABLES[axis][level])
        return tuple(columns)

    def steps(self) -> tuple[int, ...]:
        """How far each axis has moved from the canonical setting.

        One signed integer per axis, in :data:`FEATURE_AXIS_ORDER` —
        the node's address, the vector a node id encodes.
        """
        return tuple(
            level - FEATURE_AXES[axis][0]
            for axis, level in zip(FEATURE_AXIS_ORDER, self._values)
        )

    @property
    def depth(self) -> int:
        """``Σ|step|`` — how many legal moves the setting is from the root."""
        return sum(abs(step) for step in self.steps())

    @property
    def text(self) -> str:
        """The subset as it reads: ``x0 + x2``.

        The columns and nothing else — the coefficients are the fit's to
        complete, and a setting that spelled weights would be spelling a
        model rather than a subset.
        """
        columns = self.features
        if not columns:
            return "intercept-only"
        return " + ".join(_render_feature(feature) for feature in columns)

    def row(self) -> dict[str, Any]:
        """The setting as a store-shaped mapping — a fresh dict per call.

        The constructor's own keywords, so a row round-trips into a
        setting the way the hyperparameter setting's row does.
        """
        return {
            axis.value: value for axis, value in zip(FEATURE_AXIS_ORDER, self._values)
        }

    def with_value(self, axis: FeatureAxis, value: Any) -> FeatureSetting:
        """A copy of this setting with one axis moved to ``value``.

        A fresh setting per call, never a mutated one, validated by the
        constructor like any other — a move to an out-of-lattice level
        is refused here rather than held and refused later.
        """
        values = self.row()
        values[axis.value] = value
        return FeatureSetting(**values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FeatureSetting):
            return NotImplemented
        return self._values == other._values

    def __hash__(self) -> int:
        return hash(self._values)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        fields = [
            f"{axis.value}={value!r}"
            for axis, value in zip(FEATURE_AXIS_ORDER, self._values)
        ]
        return f"FeatureSetting({', '.join(fields)})"


def canonical_featsel_node_id() -> str:
    """The root's node id — the all-zero step vector, derived not spelled.

    A function rather than a constant so the root's address is derived
    from the same encoder every other node's is, and the root cannot
    drift away from the lattice it roots.
    """
    return encode_featsel_node_id((0,) * len(FEATURE_AXIS_ORDER))


def encode_featsel_node_id(steps: tuple[int, ...]) -> str:
    """Encode a step vector as the node id that addresses it.

    ``"s+2.w+1.p+0.n+0"`` — one ``<initial><sign><magnitude>`` field per
    axis in :data:`FEATURE_AXIS_ORDER`, joined by dots: the same codec
    shape :func:`bootstrap.encode_node_id` spells for the hyperparameter
    lattice, with this lattice's own initials, so a featsel node id, an
    hpo node id and a symreg node id are textually distinct kinds of
    address and no world decodes another's.
    """
    return ".".join(
        f"{axis.value[0]}{'+' if step >= 0 else '-'}{abs(step)}"
        for axis, step in zip(FEATURE_AXIS_ORDER, steps)
    )


def decode_featsel_node_id(node_id: str) -> tuple[int, ...]:
    """Read a featsel node id back into the step vector it encodes.

    The inverse of :func:`encode_featsel_node_id` and as strict as it:
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
    if len(fields) != len(FEATURE_AXIS_ORDER):
        raise BootstrapWorldError(
            f"the node id {node_id!r} carries {len(fields)} field(s) where "
            f"this world's lattice has {len(FEATURE_AXIS_ORDER)} axes "
            f"({', '.join(axis.value for axis in FEATURE_AXIS_ORDER)}); a "
            "node id is one field per axis, in that order"
        )
    steps: list[int] = []
    for axis, field in zip(FEATURE_AXIS_ORDER, fields):
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

#: Address-space prefixes keeping the featsel world's draws in blocks of
#: the 64-bit cell space disjoint from each other and from the
#: hyperparameter and symbolic worlds' (five prefixes between them).
#: Spelled as large odd constants for the reason those are: two
#: prefixes differing in one bit would be mixed by the same multipliers
#: with a one-bit difference, and the finalizer's avalanche would be
#: the only thing standing between a policy and a detectable
#: correlation between two quantities.
_PREFIX_FEATSEL_FEATURE = 0x51C4A7_E39B2F860D
_PREFIX_FEATSEL_PROXY = 0x2F8D63_B5A17C4E9B
_PREFIX_FEATSEL_NOISE = 0x64A0F1_8C3E59D2A7
_PREFIX_FEATSEL_SUPPORT = 0x1B7E29_D48A6C0F73

#: The multiplier spreading ``(row, column)`` pairs across the feature
#: block, as in the hyperparameter world: a row-major stride larger than
#: any column count, so two pairs collide only if they are literally
#: equal.
_ROW_STRIDE = 1 << 32


def _feature_cell(token: int, row: int, column: int) -> int:
    """The cell one column's own draw is read from — ``token`` and ``(row, column)``.

    The same construction as the hyperparameter world's
    ``_feature_cell``, against this domain's own prefix: within one
    world the address arithmetic is untouched, and across worlds the
    block translates by the whole token, so two worlds of one lattice
    draw independently — and a featsel world, an hpo world and a symreg
    world sharing a seed draw from disjoint blocks, so the committed
    ids of the three domains never quietly share data.
    """
    address = row * _ROW_STRIDE + column
    return _PREFIX_FEATSEL_FEATURE ^ token ^ (address ^ mix64(address))


def _proxy_cell(token: int, row: int, column: int) -> int:
    """The cell one proxy's *independent* component is drawn from.

    A proxy is a blend — ``ρ`` of the candidate it copies plus
    ``√(1−ρ²)`` of a fresh draw — and this is the fresh half's address,
    in its own block so a proxy's noise and a column's own draw can
    never be the same word twice.  The copied half is not drawn again:
    it is the candidate's own already-addressed value, read where the
    blend needs it, so the proxy is a pure function of cells that
    already exist and the blend is reproducible from the seed alone.
    """
    address = row * _ROW_STRIDE + column
    return _PREFIX_FEATSEL_PROXY ^ token ^ (address ^ mix64(address))


def _noise_cell(token: int, row: int) -> int:
    """The cell one label's noise is drawn from — ``token`` and ``row``."""
    return _PREFIX_FEATSEL_NOISE ^ token ^ (row ^ mix64(row))


def _choice_cell(token: int, which: int) -> int:
    """The cell one support-choice draw is read from — ``token`` and ``which``.

    The support's membership is drawn from the same content-addressed
    hash as the benchmark it will label, each choice from its own cell,
    so the support is a pure function of the seed like every other fact
    of the world — reproducible from the seed alone, independent of the
    order the choices were taken in, and disjoint from the feature and
    noise blocks.
    """
    address = which + 1
    return _PREFIX_FEATSEL_SUPPORT ^ token ^ (address ^ mix64(address))


def support_for_seed(seed: int) -> FeatureSupport:
    """Draw the known support a seed names — the world's truth, from its seed.

    A pure function of the seed, in the same discipline as
    :func:`bootstrap.generate_dataset`: the strong axis's choice (which
    candidate carries the decisive weight — never level 0, so every
    drawn support has an oracle to find), the weak block's width
    (``x2`` alone or with ``x3`` — never level 0, for the same reason),
    and each coefficient's sign, and nothing else.  Two seeds may draw
    one support and two supports may share a column — the *world* is
    still the seed's, because the benchmark the support labels is drawn
    from the seed too — and the family of supports across a pool is the
    "benchmarks" of the feature's own plural, every one of them
    lattice-expressible by construction because each is *built from*
    the lattice's own tables.
    """
    token = mix64(seed)

    def level(which: int) -> int:
        """A structural level in {1, 2} — drawn, never the empty 0."""
        return 1 + int(uniform(_choice_cell(token, which)) * 2)

    def sign(which: int) -> float:
        """A term's sign, drawn — the one degree of freedom left."""
        return -1.0 if uniform(_choice_cell(token, which)) < 0.5 else 1.0

    strong_level = level(0)
    weak_level = level(1)
    terms = [
        (
            feature,
            sign(3 + offset) * WEAK_MAGNITUDES[offset],
        )
        for offset, feature in enumerate(WEAK_TERMS[weak_level])
    ]
    terms.append((STRONG_TERMS[strong_level][0], sign(2) * STRONG_MAGNITUDE))
    return FeatureSupport(intercept=FEATSEL_INTERCEPT, terms=tuple(terms))


# --------------------------------------------------------------------------
# The fixed benchmark
# --------------------------------------------------------------------------


class LabeledBenchmark:
    """The world's fixed benchmark: features, and labels drawn from the truth.

    Rows are held as tuples in priced row order, the same shape
    :class:`bootstrap._world.Dataset` and
    :class:`bootstrap._symreg.SymbolicDataset` hold, and the train and
    holdout splits are indices into it through the shared
    :func:`~bootstrap.split_indices`.  ``labels`` are the observed
    values — truth plus noise — and the *truth* is available separately
    (:meth:`truth_for`), which is what makes the world's objectives
    auditable: a caller can see exactly what the noise was hiding, and
    a fit's residuals against the truth are the support's own
    expression evaluated where the benchmark drew its rows.
    """

    __slots__ = ("_features", "_labels", "_support", "_targets", "seed")

    def __init__(
        self,
        *,
        features: tuple[tuple[float, ...], ...],
        labels: tuple[float, ...],
        support: FeatureSupport,
        seed: int,
    ) -> None:
        self._features = features
        self._labels = labels
        self._support = support
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
    def labels(self) -> tuple[float, ...]:
        """Every row's observed label, in priced row order."""
        return self._labels

    @property
    def support(self) -> FeatureSupport:
        """The known truth the labels were drawn from."""
        return self._support

    def feature(self, row: int, column: int) -> float:
        """One cell of the design, by priced row and feature index."""
        return self._features[row][column]

    def truth_for(self, row: int) -> float:
        """The noise-free value of the known truth at ``row``.

        The answer key in the literal sense: the support evaluated at
        the row's own features, so a caller auditing the pool's honesty
        compares a subset's predictions against the truth its labels
        were drawn from.
        """
        return self._support.evaluate(self._features[row])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"LabeledBenchmark(rows={self.rows}, "
            f"features={FEATSEL_FEATURE_COUNT}, seed={self.seed})"
        )


def generate_benchmark(
    seed: int, *, support: FeatureSupport
) -> LabeledBenchmark:
    """Generate the fixed benchmark a seed labels a support with.

    A pure function of ``(seed, support)``: same seed and support, same
    benchmark, to the last bit, in any process and in any order of
    calls — the totality that lets the world's identity *be* its seed
    and support (:mod:`bootstrap._stream`'s whole argument, restated
    for this domain), and one sweep rather than a lazy per-cell draw for
    the reason the sibling worlds' are: a fit needs the whole design,
    so there is no order a policy could reveal cells in that would
    change what is drawn.

    The columns are drawn block by block, the lattice's own anatomy:
    the candidates, the weak block and the distractors as fresh
    standard draws, and each proxy as the blend
    ``ρ·(the candidate it copies) + √(1−ρ²)·(a fresh draw)`` — unit
    variance marginally, correlated with its candidate by
    :data:`PROXY_CORRELATION`, and conditionally nothing but its fresh
    half beside the candidate itself.
    """
    rows: list[tuple[float, ...]] = []
    labels: list[float] = []
    token = mix64(seed)
    independent = math.sqrt(1.0 - PROXY_CORRELATION * PROXY_CORRELATION)
    for row in range(FEATSEL_ROWS):
        features = [
            normal(_feature_cell(token, row, column))
            for column in range(FEATSEL_FEATURE_COUNT)
        ]
        for proxy, candidate in ((4, 0), (5, 1)):
            features[proxy] = math.fsum(
                (
                    PROXY_CORRELATION * features[candidate],
                    independent * normal(_proxy_cell(token, row, proxy)),
                )
            )
        vector = tuple(features)
        noise = FEATSEL_NOISE_SCALE * normal(_noise_cell(token, row))
        rows.append(vector)
        labels.append(math.fsum((support.evaluate(vector), noise)))
    return LabeledBenchmark(
        features=tuple(rows), labels=tuple(labels), support=support, seed=seed
    )


def _design_row(features: tuple[float, ...], setting: FeatureSetting) -> list[float]:
    """One row of a subset's design: the intercept, then its columns.

    The column order is fixed — intercept first, then the setting's
    features in :data:`FEATURE_AXIS_ORDER` — because it is the order a
    fitted coefficient vector is read in and the order two subsets must
    agree on to be compared at all.  The columns are the setting's own,
    so a design is a subset made numeric, nothing more.
    """
    return [1.0, *(features[feature] for feature in setting.features)]


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------


class FeatureSelectionWorld:
    """Feature 182's world: a labeled benchmark, a lattice of subsets, honest objectives.

    Constructed from a world id and a seed — the support is drawn from
    the seed by :func:`support_for_seed` — or from an explicit
    ``support`` a caller plants, which is the *known* taken literally:
    the caller names the truth, the world labels a benchmark from it
    and scores every subset against that benchmark.  The benchmark is
    generated on first use, once, and held; no method mutates anything
    and no answer depends on which ask came before it, so two worlds
    built from one ``(world_id, seed, support)`` are interchangeable to
    the last bit — the same statelessness the hyperparameter world
    states for itself, and the reason a replay may reveal cells in any
    order and still score a policy on the same numbers.

    **The interface is the question interface.**  This class owns the
    answer surface — :meth:`node_id` and :meth:`setting` address a cell,
    :meth:`legal_moves` enumerates the neighbours, :meth:`canonical_node`
    roots a walk, :meth:`label` reveals a cell's truth — and carries no
    policy runtime, no reveal bookkeeping and no budget, all three of
    which belong to the question (:class:`FeatureQuestion`), the replay
    engine and feature 185's ledger rather than to a world.  The surface
    is the one :func:`~bootstrap.question_for` duck-types over, so the
    identical :class:`~bootstrap.BootstrapQuestion` wraps this world
    with no change to feature 184's module.
    """

    __slots__ = ("_benchmark", "_support", "_world_id", "seed")

    def __init__(
        self,
        world_id: str,
        *,
        seed: int = FEATSEL_SEED,
        support: FeatureSupport | None = None,
    ) -> None:
        if not isinstance(world_id, str) or not world_id.strip():
            raise BootstrapWorldError(
                f"a world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how an objective "
                "is attributed to a world in the pool, and an unnamed "
                "world's scores could not be reported per pool as §10.6 "
                "requires"
            )
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise BootstrapWorldError(
                f"a world seed is an integer — got {seed!r} "
                f"({type(seed).__name__}); the seed names the benchmark "
                "the support labels, and a seed that is not an integer "
                "names no world this member can reproduce"
            )
        if support is None:
            # Drawn here rather than lazily: the draw is one pure hash
            # read, and a world whose *published* support had to wait on
            # its benchmark would be a world that could not say what it
            # was scoring against until the first label — which is
            # backwards, the support is the reason the benchmark exists.
            support = support_for_seed(seed)
        if not isinstance(support, FeatureSupport):
            raise BootstrapWorldError(
                f"a feature selection world is scored against a "
                f"FeatureSupport — got {support!r} "
                f"({type(support).__name__}); the support is the known "
                "truth every objective is measured against, and a value "
                "that is not one names no truth a subset could recover"
            )
        self._world_id = world_id
        self.seed = seed
        self._support = support
        self._benchmark: LabeledBenchmark | None = None

    @property
    def world_id(self) -> str:
        """This world's id — the name its objectives are attributed to."""
        return self._world_id

    @property
    def support(self) -> FeatureSupport:
        """The known support every objective is measured against."""
        return self._support

    @property
    def theme_root(self) -> str:
        """The structural family this world's nodes belong to — ``featsel``.

        A fact about the *domain* rather than the world, read by this
        domain's question adapter for every :class:`~bootstrap.CellMeta`
        it hands a policy: §11.1's family conditioning needs the family
        named, and a feature selection node is not a member of the
        hyperparameter family.
        """
        return FEATSEL_THEME_ROOT

    @property
    def benchmark(self) -> LabeledBenchmark:
        """The fixed benchmark, generated once from ``(seed, support)`` and held.

        Lazy for the reason the sibling worlds' datasets are: a pool
        holds many worlds and pays for a benchmark only when an
        objective is asked of it.
        """
        if self._benchmark is None:
            self._benchmark = generate_benchmark(self.seed, support=self._support)
        return self._benchmark

    # -- The lattice --------------------------------------------------------

    @property
    def axes(self) -> tuple[FeatureAxis, ...]:
        """The world's axes, in :data:`FEATURE_AXIS_ORDER`."""
        return FEATURE_AXIS_ORDER

    @property
    def canonical_setting(self) -> FeatureSetting:
        """The world's root — the setting a caller gets by naming nothing."""
        return FeatureSetting()

    def canonical_node(self) -> str:
        """The root's node id — where a policy's walk starts."""
        return canonical_featsel_node_id()

    def setting(self, node_id: str) -> FeatureSetting:
        """The setting a node id addresses, or the world's refusal.

        The decode is strict and the lattice bound is separate, as in
        the hyperparameter world: a well-formed address may still step
        past the end of an axis, and that refusal reads differently
        from a malformed one.
        """
        return _setting_from_steps(
            decode_featsel_node_id(node_id), node_id=node_id
        )

    def steps(self, node_id: str) -> tuple[int, ...]:
        """The step vector a node id addresses, refused if out of lattice."""
        return self.setting(node_id).steps()

    def node_id(self, setting: FeatureSetting) -> str:
        """The node id addressing ``setting`` in this world.

        Validates the setting's type before encoding, so a caller that
        hands a hyperparameter setting — or anything else — is refused
        rather than answered from its accidental shape.
        """
        if not isinstance(setting, FeatureSetting):
            raise BootstrapWorldError(
                f"a node id addresses a FeatureSetting — got "
                f"{setting!r} ({type(setting).__name__}); a node is a "
                "point of this world's lattice, not a bare value"
            )
        return encode_featsel_node_id(setting.steps())

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
        for index, axis in enumerate(FEATURE_AXIS_ORDER):
            legal = FEATURE_AXES[axis]
            for delta in (-1, 1):
                position = legal.index(current.value(axis)) + delta
                if 0 <= position < len(legal):
                    neighbour = list(steps)
                    neighbour[index] = position - legal.index(legal[0])
                    moves.append(encode_featsel_node_id(tuple(neighbour)))
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
        fit total whatever the subset's columns.
        """
        settings: list[FeatureSetting] = [FeatureSetting()]
        for axis in FEATURE_AXIS_ORDER:
            legal = FEATURE_AXES[axis]
            grown: list[FeatureSetting] = []
            for setting in settings:
                for value in legal:
                    grown.append(setting.with_value(axis, value))
            settings = grown
        return tuple(sorted(self.node_id(setting) for setting in settings))

    # -- The label ----------------------------------------------------------

    def label(self, node_id: str) -> FitResult:
        """The node's ground-truth objective — the feature's headline.

        Completes the subset with least-squares coefficients over the
        training split and answers the held-out ``R²``
        (:attr:`~bootstrap._fit.FitResult.r2_holdout`) beside the
        training score and the fitted coefficients — the value of the
        objective feature selection defines itself as optimizing, the
        fixed model's out-of-sample performance over the chosen subset.
        Every input is the world's own fixed state or the node's
        address, so the answer is a pure function of ``(world, node)``:
        the same node labelled twice, or after any number of other
        nodes, answers the identical number — which is what makes it a
        ground truth rather than a measurement, and what makes the
        objective a fact about the subset rather than about the path
        that reached it.

        Refuses with :class:`~bootstrap.errors.BootstrapWorldError` for
        a node outside the lattice or a missing address — the root is
        spelled, not defaulted, because a defaulted argument would let a
        missing one answer the same objective as a deliberate root ask
        — and would refuse with
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
                "objective as a deliberate root ask"
            )
        return self.label_setting(self.setting(node_id), node_id=node_id)

    def label_setting(
        self, setting: FeatureSetting, *, node_id: str | None = None
    ) -> FitResult:
        """The objective for a setting already in hand — the label, spelled once.

        Both callers — :meth:`label` for a node id, :meth:`label_all`
        for a sweep — route through this, so a node's objective has
        exactly one implementation and a sweep cannot drift from a
        single ask.
        """
        subject = (
            f"node {node_id!r} of world {self._world_id!r}"
            if node_id is not None
            else f"setting {setting.text!r} of world {self._world_id!r}"
        )
        benchmark = self.benchmark
        train, holdout = split_indices(benchmark.rows)
        return fit_and_score(
            design_train=[
                _design_row(benchmark.features[row], setting) for row in train
            ],
            targets_train=[benchmark.labels[row] for row in train],
            design_holdout=[
                _design_row(benchmark.features[row], setting) for row in holdout
            ],
            targets_holdout=[benchmark.labels[row] for row in holdout],
            ridge=FEATSEL_RIDGE,
            subject=subject,
        )

    def label_all(self) -> Iterator[tuple[str, FitResult | BootstrapScoringError]]:
        """Every cell of the lattice, labelled — the world's ground truth.

        Ascending by node id and total, exactly as the sibling worlds'
        sweeps are: a cell whose fit refuses yields the refusal rather
        than aborting the sweep, so a caller auditing the whole space
        sees the full landscape rather than a prefix of it.
        """
        for node_id in self.cells():
            try:
                yield node_id, self.label(node_id)
            except BootstrapScoringError as refusal:
                yield node_id, refusal

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FeatureSelectionWorld(world_id={self._world_id!r}, "
            f"seed={self.seed!r}, support={self._support.text!r})"
        )


def _setting_from_steps(
    steps: tuple[int, ...], *, node_id: str
) -> FeatureSetting:
    """Turn a decoded step vector into a setting, or refuse it as out of lattice.

    The one place the lattice bound is enforced on the way in from a
    node id, so :meth:`FeatureSelectionWorld.setting` and
    :meth:`FeatureSelectionWorld.steps` cannot disagree about which
    cells the world holds — the same split of labours the
    hyperparameter world's own ``setting_from_steps`` makes.
    """
    values: dict[str, int] = {}
    for axis, step in zip(FEATURE_AXIS_ORDER, steps):
        legal = FEATURE_AXES[axis]
        position = step + legal.index(legal[0])
        if not 0 <= position < len(legal):
            raise BootstrapWorldError(
                f"the node id {node_id!r} addresses {axis.value}={step:+d} "
                f"step(s) from this world's root, which is past the end of "
                f"the {axis.value!r} axis — the lattice declares "
                f"{', '.join(str(level) for level in legal)} level(s) per "
                "selection; the space is bounded because an axis is a "
                "declaration of what the world answers for, and a level "
                "outside it names a subset nobody agreed to score"
            )
        values[axis.value] = legal[position]
    return FeatureSetting(**values)


# --------------------------------------------------------------------------
# The question the world fronts
# --------------------------------------------------------------------------


class FeatureQuestion(BootstrapQuestion):
    """The policy-facing question over a feature selection world — 184's adapter, featsel's family.

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
    the node's *own* domain — a feature selection node is ``featsel``,
    not ``hpo`` — and the branch axis of a featsel cell's structure is
    one of this lattice's four axes, not the hyperparameter lattice's.
    The parent's ``meta`` reads the hyperparameter tables because every
    world it was built to front shared them; this world does not, so the
    one method whose *content* is per-domain is re-answered here while
    everything whose *shape* is the interface stays inherited.

    Constructed through :func:`featsel_question_for`; the constructor
    adds one check to the parent's duck-typing — the world must declare
    its ``theme_root``, because the family is a fact the adapter
    reports and a world without one would leave the meta silently
    answering a family the world never claimed.
    """

    def __init__(self, world: FeatureSelectionWorld) -> None:
        super().__init__(world)
        if not hasattr(world, "theme_root"):
            raise BootstrapWorldError(
                f"a feature selection question fronts a world that "
                f"declares its family — got {world!r} "
                f"({type(world).__name__}), which has no theme_root; "
                "§11.1's family conditioning routes through meta(), and "
                "a world with no family to report would leave the meta "
                "answering one it never claimed"
            )

    def meta(self, node_id: str) -> CellMeta:
        """The structural metadata of ``node_id`` — §11's ``meta(node_id)``.

        The parent's derivation over *this* lattice's axes: the depth is
        the node's ``Σ|step|`` from the root, the parent is the
        neighbour one step toward the root (``None`` at the root), the
        branch is the highest axis the node differs from its parent on
        (``None`` at the root), and the theme root is the world's own
        declared family — ``featsel`` — so a policy's
        family-conditional thresholds see this node as a member of its
        domain.
        """
        steps = self._world.steps(node_id)
        depth = sum(abs(step) for step in steps)
        if depth == 0:
            # The root: no parent, no step that reached it, no axis moved.
            return CellMeta(
                branch=None, depth=0, parent=None, theme_root=FEATSEL_THEME_ROOT
            )
        # The parent is the neighbour one legal step toward the root, and
        # the branch is the axis that step moved — the parent's own rule,
        # tie-broken on the later axis so two adapters of one world name
        # the same parent and branch, re-answered over this lattice's
        # axis order and codec.
        max_distance = max(abs(step) for step in steps)
        parent_steps = list(steps)
        branch_axis: FeatureAxis | None = None
        for index in range(len(FEATURE_AXIS_ORDER) - 1, -1, -1):
            if abs(steps[index]) == max_distance:
                parent_steps[index] = steps[index] - (
                    1 if steps[index] > 0 else -1
                )
                branch_axis = FEATURE_AXIS_ORDER[index]
                break
        return CellMeta(
            branch=branch_axis,  # type: ignore[arg-type]  # this lattice's axis
            depth=depth,
            parent=encode_featsel_node_id(tuple(parent_steps)),
            theme_root=self._world.theme_root,
        )


def featsel_question_for(world: FeatureSelectionWorld) -> FeatureQuestion:
    """Turn a feature selection world into the policy-facing question it fronts.

    The domain's one factory, the way :func:`~bootstrap.question_for`
    is the hpo domain's, :func:`~bootstrap.symreg_question_for` the
    symbolic domain's and :func:`~bootstrap.ported_question_for` the
    ported domain's: a world in, the question a policy expects out,
    built so the construction cannot be gotten wrong at the call site.
    The adapter is bound to the world it wraps — its
    ``legal_actions``, its labels, its ``meta`` are the world's — so
    one policy written against a financial campaign runs unmodified
    against a feature selection world, which is §10.6's *"a policy is
    portable without modification"* and feature 184's
    identical-interface requirement, answered for this domain.

    Inherits the parent constructor's refusals — a non-world or an
    unnamed world is refused before it can hand a policy an interface —
    and adds the one this domain needs, the declared family (see
    :class:`FeatureQuestion`).
    """
    return FeatureQuestion(world)
