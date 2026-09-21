"""The policy-facing question interface — feature 184's identical seam.

app_spec.xml, "Bootstrap Worlds", feature 184: *System exposes the
identical policy question interface from every bootstrap world, so one
policy runs unmodified and returns comparable scores across both pools.*
docs/nullius-tech-architecture.md §10.6 states what every bootstrap world
is for — *"Each exposes the **same** ``question.*`` API as a financial
campaign, so a policy is portable without modification"* — and §11 names
that API in full:

    question.observed()        -> dict[node_id, Observation]
    question.legal_actions()   -> list[node_id]
    question.legal_roots()     -> list[node_id]
    question.meta(node_id)     -> CellMeta          # structural: branch, depth, parent, theme_root
    question.probe_batch(cells, on_reveal=...)
    question.budget_remaining()                     # statistical, not compute
    question.commit(node_id)                        # REQUIRED; omitting scores −inf

**A world is not a question, and the split is the feature.**  The world
(:mod:`bootstrap._world`) owns the *answer surface*: it can name its root,
enumerate a node's neighbours, and label a node with its honest
held-out ``R²`` — and it deliberately carries no reveal history, no policy
runtime and no budget, because a world whose answers depended on how often
it had been asked would not be a ground truth (see that module's
*"The interface is the question interface"*). Feature 184 is the wrapper
that turns that answer surface into the *policy-facing* object a replay
hands a policy: the thing that remembers which cells have been revealed,
that answers ``legal_actions`` from the committed frontier rather than from
an arbitrary node, that records the terminal ``commit``, and that reports
the budget the world never charged. The world answers *what is true here?*;
the question answers *what has this policy seen, and what may it do next?* —
two facts that should not share one object, and the reason the category's
later features (189's ground-truth labelling, 190's ported adapter) build
on *this* seam rather than on the world's.

**The adapter is a pure function of (world, node_id), with no state of its
own beyond the revealed set.**  Every answer the question gives is a call
through to the world it wraps — ``world.label``, ``world.legal_moves``,
``world.setting`` — so the question cannot drift from the world: change the
world's lattice and the question's ``legal_actions`` and ``meta`` change
with it, to the same cells. The only thing the question adds is the *reveal
bookkeeping* — the set of cells a policy has committed to look at — and that
is the one piece of state a replay needs and a world must not hold. A
:func:`label` is computed from ``(world, node_id)`` alone, so the same node
revealed twice, or revealed after any other nodes, answers the identical
Observation — which is what "ground truth" has to mean for a pool the
financial worlds are calibrated against.

**The label is honest, and unchanged.**  The Observation a reveal returns
carries the world's own :class:`~bootstrap._fit.FitResult` — its
``r2_holdout``, its ``r2_train``, its ``overfit_gap``, its fitted
coefficients and column width — not a rescored or narrowed copy. A bootstrap
world's whole contribution to the pool is that its labels are perfect
(§10.6), and a question that answered a different number than the world's
``label`` would be the exact corruption the interface exists to prevent: a
policy would be comparing a bootstrap node against a financial one on a
score that meant two different things. The Observation is the fit's ``row()``
plus the world id it was earned on, so §10.6's *"report the two pools
separately"* is a fact the payload carries rather than a rule the scorer
has to re-derive.

**The budget is reported, not kept.**  §10.6's *"zero statistical-budget
cost"* is a fact about bootstrap worlds — a probe of one charges no
statistical degrees of freedom — and the adapter reports it as
``budget_remaining()`` returning the whole budget, always. It is *not* a
counter the question decrements: a counter would be a budget, and a budget
is the trial's fact (feature 185's ``charges_budget`` is a statement about
what the trial records), not the world's. The question therefore never
tracks a budget; it states the world's stance.

**``theme_root`` is the family, and it is the domain.**  docs §11.1 exposes
``theme_root`` in ``meta()`` because the overfit signature is only partly
family-invariant, and the policy writes family-conditional thresholds. A
bootstrap world belongs to one family — the authored hyperparameter world to
``"hpo"`` — and the adapter reports that family on every ``meta()`` so a
policy that reasons about families sees a bootstrap node as a member of its
domain rather than as a family-less exception. The theme root is a fact
about the world the question wraps, so two worlds of different domains
report different roots through the identical interface — which is the whole
point of §10.6's *"one policy, both pools"*.

Stdlib only, and import-cheap: the question wraps the world's own primitives
and adds a reveal set. No third-party import at module scope, so the
factory's scan — which imports this package to fire its ``@register`` — pays
nothing for the seam.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ._fit import FitResult
from ._world import (
    AXIS_ORDER,
    HyperparameterAxis,
    HyperparameterWorld,
    encode_node_id,
)
from .errors import BootstrapWorldError

__all__ = [
    "BootstrapQuestion",
    "CellMeta",
    "Observation",
    "question_for",
]

#: The structural theme a node's family belongs to.  A bootstrap world's
#: domain — ``"hpo"`` for the authored hyperparameter world — reported on
#: every :class:`CellMeta` so the family-conditional overfit signature
#: docs/nullius-tech-architecture.md §11.1 routes through ``meta()`` has a
#: family to route.  The root is a fact about the *world* the question wraps
#: (the pool domain every world of it is authored into), so two worlds of
#: different domains report different roots through the identical interface.
BOOTSTRAP_THEME_ROOT = "hpo"


@dataclass(frozen=True)
class CellMeta:
    """The structural metadata a node carries — docs §11's ``CellMeta``.

    A frozen value, because a node's structure is a fact about where it sits
    in the lattice and not something a reveal changes: two callers holding
    the meta of one node must not be able to move each other's, and a policy
    reading ``meta()`` twice gets the same structure. Its four fields are the
    ones the architecture names — ``branch``, ``depth``, ``parent``,
    ``theme_root`` — and each is read off the world's lattice rather than
    stored, so the meta cannot drift from the node it describes:

    * **``branch``** — the axis the node's last legal step from its parent
      moved, as a :class:`~bootstrap.HyperparameterAxis`, or ``None`` at the
      root where there is no parent and therefore no step that reached it.
      The branch is *derived* from the step vector (the highest-axis the node
      differs from its parent on), not recorded, so a meta computed here and
      one computed by any other adapter of the same world agree to the last
      field — the property that makes "one policy, both pools" legible.
    * **``depth``** — ``Σ|step|`` from the root, the world's own structural
      depth (:meth:`HyperparameterWorld.depth`), so the number a policy reads
      off a bootstrap node is the number the financial node's meta carries,
      on the same scale.
    * **``parent``** — the node id one legal step toward the root, or ``None``
      at the root. The parent is the neighbour that is *closer* to the root
      than the node itself, so a walk from any cell to the root is a monotone
      descent through parents, and a policy reasoning about the tree has the
      edge it needs.
    * **``theme_root``** — the domain family the world belongs to, the same
      value on every meta of one world.
    """

    branch: HyperparameterAxis | None
    depth: int
    parent: str | None
    theme_root: str

    def row(self) -> dict[str, Any]:
        """The meta as a store-shaped mapping — a fresh dict per call.

        The structural fields a replay or a report writes down, with the
        branch rendered as its wire spelling (``None`` at the root) so the
        row is text-stable and a report ordering by it orders by axis name
        rather than by enum accident.
        """
        return {
            "branch": self.branch.value if self.branch is not None else None,
            "depth": self.depth,
            "parent": self.parent,
            "theme_root": self.theme_root,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        branch = self.branch.value if self.branch is not None else None
        return (
            f"CellMeta(branch={branch!r}, depth={self.depth}, "
            f"parent={self.parent!r}, theme_root={self.theme_root!r})"
        )


@dataclass(frozen=True)
class Observation:
    """The payload a revealed node carries — the node's honest label.

    A frozen value, because an observation is a *recorded* fact — what a
    policy saw when it revealed a cell — and a policy comparing two cells
    must not be able to move either. It carries the world's own
    :class:`~bootstrap._fit.FitResult` unchanged: ``r2_holdout`` is the
    ground-truth score, ``r2_train`` and ``overfit_gap`` ride beside it so
    the overfit signal is answerable, and the fitted ``coefficients`` and
    ``n_columns`` are the design the score was earned on — nothing narrowed
    or rescored, because a bootstrap world's whole contribution is that its
    labels are perfect (§10.6), and a payload that answered a different
    number than the world's ``label`` would be the corruption this interface
    exists to prevent.

    ``world_id`` is the world the label was earned on, carried because
    §10.6's pool is *reported per pool* and a policy comparing a bootstrap
    node with a financial one reads which world the score came from. The
    observation is therefore self-attributing: it is not a bare score but a
    *(score, world)* pair, the shape the scorer needs to report the two
    pools separately.
    """

    node_id: str
    world_id: str
    r2_holdout: float
    r2_train: float
    overfit_gap: float
    n_columns: int
    coefficients: tuple[float, ...]

    @classmethod
    def from_fit(cls, node_id: str, world_id: str, fit: FitResult) -> Observation:
        """Build the observation a node's label makes — the fit, attributed.

        The one place the fit's fields are read into the payload, so the
        observation and the fit cannot drift: every observation is made here,
        and "a node's observation" has exactly one implementation. The
        coefficients are taken as the fit's own tuple, never copied, so the
        payload holds the fitted model the score was earned on.
        """
        return cls(
            node_id=node_id,
            world_id=world_id,
            r2_holdout=fit.r2_holdout,
            r2_train=fit.r2_train,
            overfit_gap=fit.overfit_gap,
            n_columns=fit.n_columns,
            coefficients=fit.coefficients,
        )

    def row(self) -> dict[str, Any]:
        """The observation as a store-shaped mapping — a fresh dict per call.

        The payload a replay writes down: the node, the world it was earned
        on, and the score. A fresh dict per call, never a shared one, for the
        reason :meth:`CellMeta.row` states.
        """
        return {
            "node_id": self.node_id,
            "world_id": self.world_id,
            "world_score": self.r2_holdout,
            "train_score": self.r2_train,
            "overfit_gap": self.overfit_gap,
            "n_columns": self.n_columns,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Observation(node_id={self.node_id!r}, world_id={self.world_id!r}, "
            f"r2_holdout={self.r2_holdout!r})"
        )


class BootstrapQuestion:
    """The policy-facing question interface over one bootstrap world — feature 184.

    Wraps a :class:`~bootstrap.HyperparameterWorld` and answers the
    identical ``question.*`` API docs/nullius-tech-architecture.md §11 names
    — :meth:`observed`, :meth:`legal_actions`, :meth:`legal_roots`,
    :meth:`meta`, :meth:`probe_batch`, :meth:`budget_remaining`,
    :meth:`commit` — so one policy written against a financial campaign runs
    unmodified against a bootstrap world. The question is bound to the world
    it wraps: its ``legal_actions`` are the world's neighbours, its labels
    are the world's honest ``R²``, and its ``meta`` is read off the world's
    lattice, so the two cannot drift — change the world and the question's
    answers change with it, to the same cells.

    The only state the question adds to the world is the *reveal set* — the
    cells a policy has committed to look at — and that is the one fact a
    replay needs and a world must not hold (a world holding a reveal history
    would be a world whose answers depended on how often it had been asked,
    which is not a ground truth). Every other answer is a pure function of
    ``(world, node_id)``, computed afresh each call, so the same node
    revealed twice answers the identical observation whatever order the
    reveals came in.

    Constructed from the world it wraps; the world is validated at
    construction, so a question built over a non-world or an unnamed world is
    refused before it can hand a policy an interface that would answer
    differently from the world it claims to front.
    """

    __slots__ = ("_committed", "_revealed", "_world")

    def __init__(self, world: HyperparameterWorld) -> None:
        # Duck-typed, not ``isinstance``: the module loader imports the member
        # under a synthetic name and re-executes it, so the composed world is
        # a *second* HyperparameterWorld class object, distinct from this
        # module's (see test_component.py / test_app_module.py). An
        # ``isinstance`` here would refuse the very world ``create_app()``
        # hands out — breaking "one policy, both pools" at the composition
        # seam. Instead the world is checked for the answer-surface it must
        # front: the attributes the question calls through — the four methods
        # it reaches for (``label``, ``legal_moves``, ``legal_roots``,
        # ``canonical_node``, ``steps``) and the ``world_id`` it reads. A
        # string or a bare object has none of them and is refused, naming
        # what was wrong.
        required = ("label", "legal_moves", "legal_roots", "canonical_node",
                    "steps", "world_id")
        missing = [name for name in required if not hasattr(world, name)]
        if missing:
            raise BootstrapWorldError(
                f"a question wraps a bootstrap world — got {world!r} "
                f"({type(world).__name__}), which has no {', '.join(missing)}; "
                "the question is the world's policy-facing side, and an object "
                "that is not a world names no interface a policy can be handed"
            )
        # Touches the id, not the dataset: the world's identity is its id,
        # and a question over an unnamed world would attribute its labels to
        # no world, which §10.6's "report per pool" forbids. The dataset is
        # still first-label lazy, so binding the question costs nothing.
        if not isinstance(world.world_id, str) or not world.world_id.strip():
            raise BootstrapWorldError(
                f"a question wraps a named world — got id {world.world_id!r}; "
                "the observation a reveal returns carries the world it was "
                "earned on, and a world with no id could not attribute its "
                "score to a pool as §10.6 requires"
            )
        self._world = world
        self._revealed: set[str] = set()

    @property
    def world(self) -> HyperparameterWorld:
        """The world this question fronts — read-only."""
        return self._world

    # -- The reveal bookkeeping -------------------------------------------------

    def observed(self) -> dict[str, Observation]:
        """The revealed cells and their observations — ``{node_id: Observation}``.

        The cells a policy has revealed so far, each mapped to the
        observation its label made, ascending by node id — an explicit sort
        before the reduction, the ordering rule docs §12 states for a search
        frontier, so two reads of one question agree whatever order the
        reveals came in. Each observation is the world's honest label of the
        cell, so the map is a pure function of the revealed set: the same
        cells revealed in any order return the same observations.
        """
        return {node_id: self._observe(node_id) for node_id in sorted(self._revealed)}

    def _observe(self, node_id: str) -> Observation:
        """The observation a revealed cell holds — the label, attributed.

        The one spelling of "a node's observation": :meth:`observed` and
        :meth:`probe_batch` both route through it, so an observation made by
        a sweep and one made by a single reveal cannot drift. The label is
        the world's honest ``FitResult``; :func:`Observation.from_fit`
        attributes it to the world.
        """
        return Observation.from_fit(node_id, self._world.world_id, self._world.label(node_id))

    # -- The walk ---------------------------------------------------------------

    def legal_roots(self) -> list[str]:
        """The node a walk may start from — §10.6.1's ``legal_roots()``.

        The world's single canonical root, as a one-entry list: the shape
        §11's API names. A single-root lattice is the point of rooting the
        space at a declared default, so a policy needs no external hint about
        where to begin and two policies compared on this world begin from the
        same place.
        """
        return [self._world.canonical_node()]

    def legal_actions(self, node_id: str | None = None) -> list[str]:
        """The neighbours a policy may take next — §11's ``legal_actions()``.

        The neighbours of ``node_id`` — one legal step along one axis — as an
        ascending list. ``None`` answers the root's neighbours, so a policy
        that has not yet committed may still enumerate its first moves from
        the frontier's start. Each move is *one* axis by *one* position, in
        either direction, filtered to the moves the lattice actually holds,
        so a walk that only ever takes returned moves stays inside the world
        by construction. Ascending, so a policy that enumerates without
        sorting still sees a deterministic order.
        """
        return list(self._world.legal_moves(node_id))

    def meta(self, node_id: str) -> CellMeta:
        """The structural metadata of ``node_id`` — §11's ``meta(node_id)``.

        Read off the world's lattice: the depth is the node's ``Σ|step|``
        from the root, the parent is the neighbour one step toward the root
        (``None`` at the root), the branch is the highest axis the node
        differs from its parent on (``None`` at the root), and the theme root
        is the world's domain family. Refuses with
        :class:`~bootstrap.errors.BootstrapWorldError` a node outside the
        lattice, naming the node and the world — a node id a policy hands to
        ``meta`` is one it was shown, and a meta computed for a cell the world
        does not hold would let a policy reason about a node it never saw.
        """
        steps = self._world.steps(node_id)
        depth = sum(abs(step) for step in steps)
        if depth == 0:
            # The root: no parent, no step that reached it, no axis moved.
            return CellMeta(branch=None, depth=0, parent=None, theme_root=BOOTSTRAP_THEME_ROOT)
        # The parent is the neighbour one legal step toward the root, and the
        # branch is the axis that step moved. The step toward the root pulls
        # the axis the node is *furthest* out on back by one; ties break on
        # the later axis (the highest index), so two adapters of one world
        # name the same parent and branch. The parent's node id is the parent
        # step vector encoded by the world's own codec — the same encoder
        # every node is addressed by, so the parent is a node the world holds.
        max_distance = max(abs(step) for step in steps)
        parent_steps = list(steps)
        branch_axis: HyperparameterAxis | None = None
        for index in range(len(AXIS_ORDER) - 1, -1, -1):
            if abs(steps[index]) == max_distance:
                parent_steps[index] = steps[index] - (1 if steps[index] > 0 else -1)
                branch_axis = AXIS_ORDER[index]
                break
        return CellMeta(
            branch=branch_axis,
            depth=depth,
            parent=encode_node_id(tuple(parent_steps)),
            theme_root=BOOTSTRAP_THEME_ROOT,
        )

    # -- The reveal ---------------------------------------------------------------

    def probe_batch(
        self,
        cells: Iterable[str],
        on_reveal: Callable[[str], None] | None = None,
    ) -> dict[str, Observation]:
        """Reveal a batch of cells at once — §11's ``probe_batch``.

        Reveals each cell of ``cells``, returning ``{node_id: Observation}``
        for the cells revealed *by this call* (an already-revealed cell is
        not re-returned — the call is idempotent on the revealed set, so a
        policy that re-probes a cell it holds does not see it as new), and
        calling ``on_reveal`` once per newly revealed cell, in ascending node
        id order. Each cell is validated against the world's lattice before
        it is revealed, so a batch that names a cell the world does not hold
        is refused naming the cell and the world — a policy cannot reveal a
        node it was never shown, and a reveal that silently skipped a bad
        cell would let the policy think it had seen one.
        """
        # Validated up front, so a bad cell refuses before any cell is
        # revealed: a half-applied batch would leave the reveal set in a
        # state the policy did not ask for, and a probe is all-or-nothing.
        cells = sorted(set(cells))
        for node_id in cells:
            self._world.steps(node_id)  # refuses a node outside the lattice
        revealed_this_call: list[str] = []
        for node_id in cells:
            if node_id not in self._revealed:
                self._revealed.add(node_id)
                revealed_this_call.append(node_id)
        for node_id in revealed_this_call:
            if on_reveal is not None:
                on_reveal(node_id)
        return {node_id: self._observe(node_id) for node_id in revealed_this_call}

    def budget_remaining(self) -> float:
        """The statistical budget left — §11's ``budget_remaining()``.

        The whole budget, always. §10.6's *"zero statistical-budget cost"*
        is a fact about bootstrap worlds — a probe of one charges no
        statistical degrees of freedom — and the adapter reports it as the
        budget untouched, rather than a counter it decrements: a counter
        would be a budget, and a budget is the trial's fact (feature 185's
        ``charges_budget`` is a statement about what the trial records,
        persisted by the trial ledger, :mod:`bootstrap._trial`), not
        the world's. The question therefore never tracks a budget; it states
        the world's stance, and a policy reading it sees a bootstrap world as
        a world whose probing is free.
        """
        return float("inf")

    # -- The terminal act ---------------------------------------------------------

    def commit(self, node_id: str) -> str:
        """Record the committed cell — §11's ``commit(node_id)``, the terminal act.

        Records ``node_id`` as the committed cell and returns it. Refuses
        with :class:`~bootstrap.errors.BootstrapWorldError` a node outside
        the lattice, naming the node and the world — ``commit`` is the cell a
        replay scores the policy's pick on, and a commit that named a cell
        the world does not hold would score the policy on a node it was never
        shown. The committed cell is recorded so a replay can read back the
        policy's final choice; it is not added to the revealed set, because
        committing is the terminal act, not a reveal, and a policy's score is
        a fact about its commit and its reveals, kept apart.
        """
        self._world.steps(node_id)  # refuses a node outside the lattice
        self._committed = node_id
        return node_id

    @property
    def committed(self) -> str | None:
        """The committed cell, or ``None`` if none has been committed — read-only."""
        return getattr(self, "_committed", None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"BootstrapQuestion(world_id={self._world.world_id!r}, "
            f"revealed={len(self._revealed)})"
        )


def question_for(world: HyperparameterWorld) -> BootstrapQuestion:
    """Turn a bootstrap world into the policy-facing question it fronts.

    The one factory for the identical interface: a :class:`HyperparameterWorld`
    in, the :class:`BootstrapQuestion` a policy expects out. The adapter is
    bound to the world it wraps — its ``legal_actions``, its labels, its
    ``meta`` are the world's — so the identical-interface requirement is a
    single call site rather than a construction a caller could get wrong.
    Refuses a non-world or an unnamed world at construction, naming what was
    wrong, and two adapters of one world answer identical observations and
    cell meta to the last field — the property that makes "one policy, both
    pools" a fact about the adapter rather than a promise in a docstring.
    """
    return BootstrapQuestion(world)
