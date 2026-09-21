"""The ported world adapter — feature 190's external ground-truth environment.

app_spec.xml, "Bootstrap Worlds", feature 190: *System exposes a ported
world adapter presenting an external ground-truth environment through the
identical policy question interface, which returns scores comparable with an
authored bootstrap world.*  docs/nullius-tech-architecture.md §10.6 opens the
phase this feature closes — *"A replay world need not be a crypto campaign"*,
and an *external* domain can supply the held-out score a paired comparison
needs — and §10.6.1's provenance rule (*"An upstream that changes is a
different world, not an updated one"*) is the whole of what a ported world
must carry, because unlike an authored world it has an upstream to check.

**A ported world is a client of feature 184's seam, not a modification of
it.**  Feature 184 (:mod:`bootstrap._question`) built the one object a policy
is handed — a :class:`~bootstrap.BootstrapQuestion`, made by
:func:`~bootstrap.question_for` — and made its factory *duck-type* rather than
``isinstance`` the world it wraps (the module loader hands out a second copy
of the world class under a synthetic name, so an ``isinstance`` gate would
refuse the very world ``create_app()`` serves).  That duck-typing is the seam
this feature rides: a ported world is just another object that exposes the
answer surface :func:`question_for` calls through — ``label``,
``legal_moves``, ``legal_roots``, ``canonical_node``, ``steps``, ``world_id``
— so :func:`question_for` wraps it in the *identical* ``BootstrapQuestion``
with no change to that module.  The ported world is the second spelling of
"one policy, both pools": the authored world is one client of the interface,
the ported world is another, and the interface between them is unchanged.

**What a ported world has that an authored world cannot: an upstream.**  An
authored bootstrap world *is* its seed — :func:`~bootstrap.generate_dataset`
is a pure function of it, so there is nothing upstream to name and the
world's identity is total.  A ported world's labels are read from an
environment this member does not generate, so its identity cannot be a seed;
it is the pair of digests that pinned those labels — the source commit the
upstream code was at, and the dataset manifest the label-bearing data was
taken from — and that pair is :class:`Provenance`.  It is the record feature
191 persists and checks: two ported worlds with different provenance are
different worlds, and a re-port of the same provenance is the same upstream,
which is §10.6.1's rule seen from the ported side.

**The label is the external score, carried unchanged.**  A ported world's
whole contribution is that its labels are the external environment's ground
truth, so the adapter does not rescore, narrow or re-derive them — a label
that answered a different number than the environment's would be the exact
corruption the identical interface exists to prevent, the one a policy
comparing a ported node with an authored one must never see.  The adapter
takes one thing from the external environment — a pure callable mapping a node
id to the honest held-out ``R²`` the environment assigns it — and returns it
as the ``r2_holdout`` of a :class:`~bootstrap._fit.FitResult`, so the score a
policy reads off a ported node is the score the environment earned, on the
same scale the authored pool reports.  The fit-pair fields that are an
authored-fit artifact (``r2_train``, ``overfit_gap``, the fitted
``coefficients`` and ``n_columns``) are the score-only defaults: a pure
external score carries the held-out ``R²`` and nothing beside it, and a port
that invented a training score it never measured would be reporting a fact it
did not have.

**The lattice is shared, so the cells are the same cells.**  A ported node is
addressed on the authored world's lattice — the same codec, the same four
axes, the same canonical root — so ``d+1.i+1.s+0.a+0`` is the same cell
whether the label on it was generated or ported, and two policies walking the
authored world and the ported world walk the same space and are scored on the
same ``R²`` scale.  That is what "returns scores comparable with an authored
bootstrap world" has to mean: not that the numbers agree, but that they are
earned on one lattice and measured by one interface.  The adapter defaults its
lattice to the committed authored world, so ``ported_world(label_fn=...)``
with no lattice names exactly the cells the authored pool walks; a caller that
ports a *different* lattice passes one in, and the adapter checks it for the
addressing surface before it trusts it.

Stdlib only, and import-cheap: the adapter is a value and a callable over the
world's own lattice, so the factory's scan — which imports this package to
fire its ``@register`` — pays nothing for the seam, and nothing here is a
component: a ported world needs an external label function and provenance that
cannot be built at composition time, so it is exposed as constructors and a
factory, the way :data:`~bootstrap.build_hyperparameter_world` is, and not as
a ``@register`` builder.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._fit import FitResult
from ._question import question_for
from ._world import PRICED_SEED, HyperparameterWorld
from .errors import BootstrapWorldError

__all__ = [
    "DEFAULT_PORTED_WORLD_ID",
    "PortedWorld",
    "Provenance",
    "ported_question_for",
    "ported_world",
]

#: The world id a ported world carries when a caller names none — a stable,
#: human-readable id in the committed world's own convention
#: (:data:`~bootstrap.HYPERPARAMETER_WORLD_ID` is the date the authored world
#: was authored; this is the ported domain's name), because §10.6's pool is
#: *reported per pool* and a ported replay score wants an id that says which
#: world it was earned on.  Deliberately distinct from the authored
#: ``bootstrap-hpo-...`` ids, so a report reading the two pools apart sees a
#: ported node as a member of the ported domain rather than a family-less
#: exception.
DEFAULT_PORTED_WORLD_ID = "bootstrap-ported"


@dataclass(frozen=True)
class Provenance:
    """Where a ported world's labels came from — the ported world's identity.

    A frozen value, because a ported world's provenance is a *recorded* fact —
    the source commit the upstream code was pinned to when the labels were
    read, and the dataset manifest the label-bearing data was taken from — and
    a caller must not be able to move either: two callers holding one
    provenance must hold the same upstream.  It is the ported world's answer
    to an authored world's seed — the thing that makes the world *this* world
    rather than another — and the record feature 191 persists and checks.

    ``source_commit`` is the upstream code's commit; ``dataset_manifest`` is
    the hash of the data the labels were ported from.  Both are digests of an
    upstream this member does not generate, and both are the whole of what
    lets a reader tell "the same upstream, re-ported" from "an upstream that
    changed" — §10.6.1's provenance rule, which for an authored world has
    nothing to check because the world has no upstream, here has exactly these
    two fields to hold to.  A blank digest names no upstream, so a provenance
    with one is refused at construction, before it can pin a ported world to a
    source it cannot name.
    """

    source_commit: str
    dataset_manifest: str

    def __post_init__(self) -> None:
        for field in ("source_commit", "dataset_manifest"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise BootstrapWorldError(
                    f"a ported world's {field} is a non-empty digest — got "
                    f"{value!r} ({type(value).__name__}); the digest pins the "
                    "labels to an upstream this member does not generate, and "
                    "a blank one names no source a re-port could be checked "
                    "against (§10.6.1: an upstream that changes is a different "
                    "world)"
                )

    def row(self) -> dict[str, Any]:
        """The provenance as a store-shaped mapping — a fresh dict per call.

        The two digests a persistence layer writes down, keyed by the column
        names feature 191 records them under, so the record and the row cannot
        drift.  A fresh dict per call, never a shared one, for the reason a
        frozen value's ``row`` is always fresh.
        """
        return {
            "source_commit": self.source_commit,
            "dataset_manifest": self.dataset_manifest,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Provenance(source_commit={self.source_commit!r}, "
            f"dataset_manifest={self.dataset_manifest!r})"
        )


class PortedWorld:
    """Feature 190's adapter: an external ground-truth environment, ported in.

    Built from a *label function* — a pure callable mapping a node id to the
    honest held-out ``R²`` the external environment assigns that node — plus
    the lattice a node is addressed on (the authored world's lattice by
    default, so the ported cells are the same cells the authored pool walks),
    a world id, and the :class:`Provenance` the labels were pinned to.  It
    owns the answer surface feature 184's :func:`~bootstrap.question_for`
    calls through — :meth:`label`, :meth:`legal_moves`, :meth:`legal_roots`,
    :meth:`canonical_node`, :meth:`setting`, :meth:`steps`, :meth:`node_id`,
    :meth:`depth` and :meth:`world_id` — so ``question_for(ported_world)``
    returns the *identical* :class:`~bootstrap.BootstrapQuestion`, and one
    policy written against a financial campaign runs unmodified against a
    ported world.

    **The world is otherwise stateless with respect to asks**, the way the
    authored :class:`~bootstrap.HyperparameterWorld` is: no method mutates
    anything, no answer depends on which ask came before it, and the label of
    a node is a pure function of the label function and the node — so a replay
    may reveal ported cells in any order and every label is still the same
    number, which is what "ground truth" has to mean for a world the authored
    pool is calibrated against.  The one state the ported world carries that an
    authored one cannot is the :class:`Provenance` — not a reveal history or a
    runtime, but the record of where the labels came from, which is the fact
    feature 191 checks and the identity the ported world is named by.

    **The label is the environment's, the lattice is shared.**  :meth:`label`
    returns the external score as the ``r2_holdout`` of a
    :class:`~bootstrap._fit.FitResult`, carried unchanged — the score a policy
    reads off a ported node is the score the environment earned, on the same
    scale the authored pool reports.  The fit-pair fields that are an
    authored-fit artifact are the score-only defaults: a pure external score
    carries the held-out ``R²`` and nothing beside it.  Every addressing method
    delegates to the shared lattice, so a ported node is addressed by the same
    codec as an authored one, and the two are comparable on one lattice through
    one interface.
    """

    __slots__ = ("_label_fn", "_lattice", "_provenance", "_world_id")

    def __init__(
        self,
        *,
        label_fn: Callable[[str], float],
        lattice: Any = None,
        world_id: str = DEFAULT_PORTED_WORLD_ID,
        provenance: Provenance,
    ) -> None:
        if not callable(label_fn):
            raise BootstrapWorldError(
                f"a ported world's label source is a callable — got "
                f"{label_fn!r} ({type(label_fn).__name__}); the label function "
                "is the one thing the ported world takes from the external "
                "environment, and a source that cannot be called cannot answer "
                "the honest score a node is labelled with"
            )
        if not isinstance(world_id, str) or not world_id.strip():
            raise BootstrapWorldError(
                f"a ported world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how a ported label is "
                "attributed to a world in the pool, and an unnamed world's "
                "scores could not be reported per pool as §10.6 requires"
            )
        if not isinstance(provenance, Provenance):
            raise BootstrapWorldError(
                f"a ported world carries its provenance — got {provenance!r} "
                f"({type(provenance).__name__}); a ported world's labels come "
                "from an upstream this member does not generate, and a world "
                "with no provenance has no source a re-port could be checked "
                "against (§10.6.1: an upstream that changes is a different "
                "world)"
            )
        # The lattice is the authored world's by default, so a ported node is
        # the same cell an authored one is.  A caller-supplied lattice is
        # checked for the addressing surface the ported world reaches through,
        # duck-typed like the question's own constructor (the loader's
        # synthetic-name copy makes isinstance across the two world classes
        # meaningless — see test_component.py): a lattice that cannot name its
        # root or address a node cannot front a walk.
        if lattice is None:
            # Resolved here rather than at import: the committed world's id
            # lives in the package __init__, and this module is imported by
            # that same __init__, so reaching it lazily keeps the import
            # acyclic while still defaulting to the committed authored world.
            from . import HYPERPARAMETER_WORLD_ID

            lattice = HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)
        required = ("canonical_node", "legal_moves", "legal_roots", "setting", "steps")
        missing = [name for name in required if not hasattr(lattice, name)]
        if missing:
            raise BootstrapWorldError(
                f"a ported world's lattice addresses a node — got {lattice!r} "
                f"({type(lattice).__name__}), which has no {', '.join(missing)}; "
                "the lattice is the space a ported node is addressed on, and a "
                "lattice that cannot address a node cannot front a walk"
            )
        self._label_fn = label_fn
        self._lattice = lattice
        self._world_id = world_id
        self._provenance = provenance

    # -- The identity -----------------------------------------------------------

    @property
    def world_id(self) -> str:
        """This world's id — the name its labels are attributed to."""
        return self._world_id

    @property
    def provenance(self) -> Provenance:
        """The provenance the labels were pinned to — read-only."""
        return self._provenance

    # -- The shared lattice, fronted --------------------------------------------

    def canonical_node(self) -> str:
        """The root's node id — where a policy's walk starts.

        The shared lattice's canonical root, so a ported walk begins where an
        authored one does and two policies compared on the two worlds begin
        from the same place.
        """
        return self._lattice.canonical_node()

    def legal_roots(self) -> tuple[str, ...]:
        """The node a walk may start from — the single canonical root."""
        return self._lattice.legal_roots()

    def legal_moves(self, node_id: str | None = None) -> tuple[str, ...]:
        """The neighbours of ``node_id`` — one legal step along one axis.

        The shared lattice's neighbours, so a ported walk that only ever takes
        returned moves stays inside the same space an authored walk does, and
        a ported node's neighbours are the same cells an authored node's are.
        """
        return self._lattice.legal_moves(node_id)

    def setting(self, node_id: str) -> Any:
        """The setting a node id addresses, or the shared lattice's refusal.

        Delegates to the shared lattice, so a ported node that addresses a
        cell outside the lattice is refused by the same bound an authored node
        is — the space a ported world answers for is the lattice's, not the
        port's.
        """
        return self._lattice.setting(node_id)

    def steps(self, node_id: str) -> tuple[int, ...]:
        """The step vector a node id addresses, refused if out of lattice.

        The address before it is turned into a setting — the shared lattice's
        own spelling, so a ported node's step vector is the authored lattice's.
        """
        return self._lattice.steps(node_id)

    def node_id(self, setting: Any) -> str:
        """The node id addressing ``setting`` on the shared lattice."""
        return self._lattice.node_id(setting)

    def depth(self, node_id: str) -> int:
        """How many legal moves the node is from the root — ``Σ|step|``."""
        return self._lattice.depth(node_id)

    def cells(self) -> tuple[str, ...]:
        """Every node id of the lattice, ascending — the ported world's space."""
        return self._lattice.cells()

    # -- The label --------------------------------------------------------------

    def label(self, node_id: str) -> FitResult:
        """The node's ground-truth score — the external environment's, unchanged.

        The external environment's honest held-out ``R²`` for the node,
        returned as the ``r2_holdout`` of a :class:`~bootstrap._fit.FitResult`
        so the identical :func:`question_for` path — which reads the fit's
        fields into the observation — carries the ported score unchanged.  The
        score is the environment's, verbatim: the adapter does not rescore,
        narrow or re-derive it, because a ported label that answered a
        different number than the environment's would be the corruption the
        identical interface exists to prevent.

        The fit-pair fields are the score-only defaults — ``r2_train`` and
        ``overfit_gap`` at ``0.0``, ``coefficients`` empty, ``n_columns``
        ``0`` — because a pure external score carries the held-out ``R²`` and
        nothing beside it, and a port that invented a training score it never
        measured would be reporting a fact it did not have.  A caller
        comparing a ported node with an authored one compares on ``r2_holdout``
        — the score the environment earned — which is the comparability the
        feature promises.

        Refuses with :class:`~bootstrap.errors.BootstrapWorldError` for a node
        outside the lattice, naming the node and the world — the shared
        lattice's bound, so a ported policy cannot label a node it was never
        shown.
        """
        self.steps(node_id)  # refuses a node outside the shared lattice
        return FitResult(
            coefficients=(),
            r2_train=0.0,
            r2_holdout=float(self._label_fn(node_id)),
            n_columns=0,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PortedWorld(world_id={self._world_id!r}, provenance={self._provenance!r})"
        )


def ported_world(
    *,
    label_fn: Callable[[str], float],
    lattice: Any = None,
    world_id: str = DEFAULT_PORTED_WORLD_ID,
    provenance: Provenance,
) -> PortedWorld:
    """Turn an external environment into the ported world it fronts.

    The one constructor call site for a ported world — a label function, a
    lattice, an id and a :class:`Provenance` in, a :class:`PortedWorld` out —
    so the ported-world construction is a single call a caller cannot get
    wrong, the way :func:`~bootstrap.question_for` is the one call site for
    the question interface.  The adapter it builds is bound to the identical
    :func:`~bootstrap.question_for` path: its ``legal_actions``, its labels,
    its ``CellMeta`` are the ported world's, and :func:`ported_question_for`
    wraps it in the same :class:`~bootstrap.BootstrapQuestion` an authored
    world is wrapped in, so one policy runs unmodified against a ported world
    and returns scores comparable with an authored bootstrap world.

    Refuses a non-callable label source, a blank id or a missing provenance at
    construction, naming what was wrong — the same guards the ported world's
    own constructor applies, surfaced at the call site.
    """
    return PortedWorld(
        label_fn=label_fn,
        lattice=lattice,
        world_id=world_id,
        provenance=provenance,
    )


def ported_question_for(world: PortedWorld) -> Any:
    """Turn a ported world into the identical question.* adapter a policy expects.

    A thin wrapper over :func:`~bootstrap.question_for` — a
    :class:`PortedWorld` in, the :class:`~bootstrap.BootstrapQuestion` every
    bootstrap world fronts out — named so the ported path is legible at the
    call site while returning the *identical* interface feature 184 built.  The
    adapter is the ported world's policy-facing side: its ``legal_actions``,
    its labels, its ``CellMeta`` are the ported world's, and a ported world and
    an authored world of one lattice expose the identical interface but their
    own labels, so one policy is scored on each world's ground truth, on the
    same ``R²`` scale.

    Inherits :func:`~bootstrap.question_for`'s construction-time refusals — a
    non-world or a blank id is refused before it can hand a policy an
    interface that would answer differently from the world it claims to front —
    for free, and the ported world's duck-typed answer surface means no
    ``isinstance`` gate refuses the very world a policy receives.
    """
    return question_for(world)
