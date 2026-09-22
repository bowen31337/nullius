"""The policy-runtime plugin: the read side of the identical question.* interface.

app_spec.xml, "Exploration Policy Runtime", feature 217: *System exposes an
observed accessor which returns a mapping of revealed node ids to
observations.*  docs/nullius-tech-architecture.md §11 names the API an
exploration policy is handed during replay — the identical ``question.*``
surface a financial campaign exposes, so one policy runs unmodified across
both pools — and §10.2 makes that surface *prefix-only*: a policy sees only
the cells it has already revealed, never an unrevealed node by any path.
Feature 217 is the read side of that surface — the ``observed()`` accessor:
the revealed cells and their honest observations, as a mapping
``{node_id: Observation}``.

This package is a workspace member discovered by convention.  The module
loader (``app.module_loader``) scans the members the root ``pyproject.toml``
declares, imports each package, and composes whatever the package's
``@register`` builder contributes — so the registration at the foot of this
module is the entire wiring story.  Nothing edits a registry, router or
factory to make the policy-runtime plugin exist; importing this module *is*
joining the application.  All intra-package imports are relative so the
package imports identically under its own name and under the loader's
scan-time name.

**A member never imports another member.**  The campaign tree this plugin
fronts is the same ``(node_id -> parent_id, depth, payload)`` node model the
frozen evaluator and the nightly canary already address
(:mod:`canary._reference`'s ``CanaryTree``), but this member owns its own
``CampaignTree`` / ``CampaignTreeNode`` value types rather than importing
canary's — a workspace member reaches shared shapes through ``app.*``, never
through a sibling package's import name, so the two cannot drift into a
cyclic dependency.  The node model is the one fact they share, and it is
small enough to restate: a node id, a parent id (or ``None`` at a root), a
non-negative depth, and the node's canonical JSON payload — the frozen bytes
the replay reads back.

**A tree is not a question, and the split is the feature.**  The tree owns
the *answer surface*: it can name a node, give its depth and parent, and read
the in-sample metrics a node's payload carries — and it deliberately carries
no reveal history, no policy runtime and no budget, because a tree whose
answers depended on how often it had been asked would not be a ground truth.
Feature 217's :class:`PolicyQuestion` is the wrapper that turns that answer
surface into the *policy-facing* object a replay hands a policy: the thing
that remembers which cells have been revealed.  The tree answers *what is
true here?*; the question answers *what has this policy seen?* — two facts
that should not share one object, and the reason the category's later
features (218's frontier, 219's meta, 220's probe, 222's commit) build on
*this* seam rather than on the tree's.

**The observation is the node's honest payload-derived reading, unchanged.**
The :class:`PolicyObservation` a reveal returns carries the in-sample metrics
and diagnostics the node's payload carries — the honest reading the tree
exists to give — attributed to the node id it was earned on.  Nothing is
rescored or narrowed, and nothing the information barrier forbids is carried:
never ``is_null`` (readable by exactly one component, the replay scorer —
prd §4.2, cq-8), never an absolute score target, never an unrevealed node's
score, never a hardcoded node id.  A policy that could read any of those
would be reading past the prefix the barrier promises it.  The observation is
a frozen value, validated at construction, so a policy comparing two revealed
cells reads each cell's honest in-sample reading and cannot move either.

**``observed()`` is prefix-only by construction.**  The accessor iterates the
question's own reveal set — the private state the question alone holds — and
builds one observation per revealed node.  An unrevealed node is therefore
*absent* from the returned mapping rather than filtered out of it: it is never
a key, never a value, never reachable by introspection, attribute walking, or
a stray ``__dict__`` access (docs §10.2, cq-16).  The reveal set is read
read-only, so a policy holding the mapping holds only what it has already
seen, and the accessor answers no node outside that set however it is asked —
which is the whole of "returns a mapping of revealed node ids to
observations", and the property that makes the information barrier a fact
about the accessor rather than a promise in a docstring.

**The object a policy is *handed* is the prefix view — fresh, and holding
only the prefix (feature 223, cq-16).**  The question is the *runtime's*
object: it fronts the tree because the runtime's own reveals need the
address seam, and a caller holding the question could walk
``question._tree`` to every node the campaign holds.  The thing authored
policy code is handed is different by law (docs/nullius-tech-architecture.md
§10.1–§10.2): :func:`prefix_view` reads the question's own ``observed()`` —
the one implementation of the reading — and copies the observations out
into a fresh :class:`PrefixView`, a frozen snapshot with no tree behind it,
no question, no reveal set and no address verb.  An unrevealed node is
absent from it rather than filtered out: there is no attribute, no slot, no
``__dict__`` (the class carries slots and none at all) and no object
reachable from the view that names a cell the policy has not revealed, so
the barrier is a fact about the object graph the policy holds.  Feature 217
made one *return value* prefix-only; feature 223 makes the object the
policy holds prefix-only, and lives in :mod:`.prefix` beside the question
it projects.

**The object an episode *hands* a policy answers a configured set and nothing
else (feature 224).**  The prefix view closes the object; the surface closes
the world around it.  docs §10.2's next sentence — *"The policy runtime
additionally blocks: ``question.best_so_far``, ``question.budget_spent``,
filesystem access, and any import outside an allowlist"* — names two facts
that are not nodes and not reaches: the best score the replay has seen so far,
and the statistical budget already debited.  Both are facts about **the
episode**, so a deployment that hands authored policy code its own episode
object has handed it both behind one attribute walk.  :func:`policy_surface`
lives in :mod:`.surface` and wraps an episode in a :class:`PolicySurface` that
answers the names the deployment configured and refuses **every other name** —
not only the two the document names, because the feature's sentence rejects an
*attribute walk*, and a walk is stopped by enumerating what is admitted rather
than what is forbidden.  The episode is read out **once, at construction**, and
never stored: an answer that arrived as a bound method would carry the episode
inside it (``__self__``), so the answers are called and copied, and an
attribute walk from the surface reaches the values a policy was configured to
receive and no object behind them.  It is one seam weaker than a guard in the
same way the view is: there is no verb for asking for a blocked answer at all,
and the refusal it is met with — :class:`PolicyAnswerSurfaceError` — is an
:class:`AttributeError` as well as a :class:`PolicyRuntimeError`, so
``hasattr``, ``getattr`` with a default and a ``dir()``-driven walk all behave
over the surface exactly as they do over any other object.

**The episode's beta is one number, read once and fixed.**  Feature 226
(docs/nullius-tech-architecture.md §609: *"``beta`` is read once in ``__init__``,
fixed for the episode"*) lives in :mod:`.beta` as :class:`EpisodeBeta` and
:func:`read_beta` — a scalar that is *the* number every threshold in the episode
is derived from (feature 227's ``_schedule(beta) -> dict``) and that refuses
every path by which a caller could move it, so the thresholds a policy explored
under are the thresholds its score was earned under.  It is a value type in the
same sense the tree's node model is: it is not part of the ``question.*`` surface
a policy is handed, and no policy reads or moves it — the runtime reads it once,
before the policy runs, and the policy sees only the thresholds that follow from
it.  The immutability shape is feature 10's :class:`contract.MarketWindow`
restated for a scalar rather than a window.

**Every threshold is derived from that scalar, together.**  Feature 227
(docs/nullius-tech-architecture.md §609: *"routed through a single
``_schedule(beta) -> dict`` so every threshold moves together"*) lives in
:mod:`.schedule` as :func:`schedule` — the one derivation point that returns
*all* the thresholds as a single frozen mapping, keyed by :data:`SCHEDULE_KEYS`
(the four the paper names — explore/exploit, patience, pruning aggressiveness,
overfit aversion — always present, never a subset).  It is the counterpart of
226's scalar, and the two share one derivation point: there is no
``explore_threshold(beta)`` and no ``patience(beta)`` — a caller that needs a
threshold reads it from the mapping :func:`schedule` returns, so a threshold
reached anywhere else would be a second beta, the drift the single-scalar
discipline exists to prevent.  A pure function of beta and nothing else — no
store, no clock, no configuration — so two cycles opened at one scalar explore
under identical thresholds, which is the cross-cycle legibility §609 names.  It
is a value type in the same sense the scalar is: the mapping is read-only, so a
threshold once derived cannot be moved, and it is not part of the ``question.*``
surface a policy is handed.

**Family-conditional thresholds, keyed on ``theme_root``.**  Feature 228
(docs/nullius-tech-architecture.md §11.1: the overfit signature is only partly
family-invariant, and a single global threshold averages the inverted features
into uselessness) lives in :mod:`.families` as :class:`FamilyConditional`,
:class:`FamilySchedule` and :func:`family_schedule` — the family dimension
*over* the one mapping, and the third half of the beta knob: 226 the scalar,
227 the mapping, 228 the families.  A conditional authors, per theme, an
additive adjustment per threshold plus the evidence the theme has accumulated,
and the composition anchors every family threshold at ``schedule(beta)``'s
value, shrunk by the partial-pooling weight
``evidence / (evidence + PRIOR_STRENGTH)`` — empirical-Bayes shrinkage without
the machinery.  A theme carrying no evidence yet answers the global default
itself, so a new theme starts at the prior and differentiates only as evidence
accumulates; an adjustment naming a key outside the one mapping is refused as a
second beta; and the key is the slug ``meta()`` exposes, while which themes may
exist stays feature 241's config rather than a second spelling here.  Authored,
not fitted: the conditional is plain floats the policy-development agent wrote
— the positive half of feature 231's refusal — and the composition is
arithmetic, with no model class, no checkpoint and no inference anywhere in it.

Stdlib only, and import-cheap: no third-party import at module scope, so the
factory's scan — which imports this package to fire its ``@register`` — pays
nothing for the seam.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.module_loader import register

from .admission import (
    AdmissionReason,
    PolicyAdmissionDecision,
    screen_policy,
)
from .beta import (
    EpisodeBeta,
    read_beta,
)
from .errors import (
    BetaFixedError,
    FamilyThresholdError,
    PolicyAddressError,
    PolicyAnswerSurfaceError,
    PolicyAdmissionRefusal,
    PolicyFilesystemError,
    PolicyImportError,
    PolicyRuntimeError,
    PolicyTreeError,
)
from .families import (
    PRIOR_STRENGTH,
    FamilyConditional,
    FamilySchedule,
    family_schedule,
)
from .guard import (
    GUARD_ACTIVE,
    POLICY_MODULE_NAME,
    PolicyCeiling,
    PolicyGuard,
    guard_policy,
)
from .learned import (
    find_learned_component,
)
from .planning import (
    GridPlan,
    GridPlanningContext,
    PlanGridDecision,
    PlanGridReason,
    PlanGridRefusal,
    plan_grid,
)
from .prefix import (
    PrefixView,
    prefix_view,
)
from .surface import (
    DEFAULT_ANSWERS,
    FORBIDDEN_ANSWERS,
    PolicySurface,
    policy_surface,
)
from .schedule import (
    EXPLORE_EXPLOIT,
    OVERFIT_AVERSION,
    PATIENCE,
    PRUNE_AGGRESSIVENESS,
    SCHEDULE_KEYS,
    schedule,
)

__all__ = [
    "CAMPAIGN_TREE_COMPONENT",
    "AdmissionReason",
    "BetaFixedError",
    "CampaignNode",
    "CampaignTree",
    "EpisodeBeta",
    "EXPLORE_EXPLOIT",
    "FamilyConditional",
    "FamilySchedule",
    "FamilyThresholdError",
    "DEFAULT_ANSWERS",
    "FORBIDDEN_ANSWERS",
    "GUARD_ACTIVE",
    "GridPlan",
    "GridPlanningContext",
    "OVERFIT_AVERSION",
    "PATIENCE",
    "POLICY_MODULE_NAME",
    "PRIOR_STRENGTH",
    "PRUNE_AGGRESSIVENESS",
    "PlanGridDecision",
    "PlanGridReason",
    "PlanGridRefusal",
    "PolicyAdmissionDecision",
    "PolicyAdmissionRefusal",
    "PolicyAddressError",
    "PolicyAnswerSurfaceError",
    "PolicyCeiling",
    "PolicyFilesystemError",
    "PolicyGuard",
    "PolicyImportError",
    "PolicyObservation",
    "PolicyQuestion",
    "PolicyRuntimeError",
    "PolicySurface",
    "PolicyTreeError",
    "PrefixView",
    "SCHEDULE_KEYS",
    "family_schedule",
    "find_learned_component",
    "guard_policy",
    "plan_grid",
    "policy_question",
    "policy_surface",
    "prefix_view",
    "read_beta",
    "schedule",
    "screen_policy",
]

#: The component name this member registers under — the plugin name the
#: spec's features carry (``plugin="policy-runtime"``), so the component key,
#: the app-namespace seat (``src/app/modules/policy-runtime``) and the spec
#: cannot drift apart.
CAMPAIGN_TREE_COMPONENT = "policy-runtime"


@dataclass(frozen=True)
class CampaignNode:
    """One node of a campaign tree — the smallest addressable cell.

    The node model the frozen evaluator and the nightly canary already
    address, restated here because a member never imports another member.  A
    node is ``(node_id, parent_id, depth, payload)``:

    * **``node_id``** — the node's identity within the tree, a non-empty
      string.  It is the id the store's uniqueness key is on, the id a parent
      reference names, and the one address a node is revealed on.
    * **``parent_id``** — the parent node's id, or ``None`` for a root.  A
      parent reference names one of the tree's nodes; a dangling reference is
      refused by :class:`CampaignTree`, not here — a node alone cannot know
      its siblings.
    * **``depth``** — how deep the node sits in the tree, zero at a root.  A
      non-negative integer, because a negative level is a level no walk could
      reach.
    * **``payload``** — the node's canonical JSON rendering — the frozen bytes
      the replay reads back.  It is the in-sample metrics and diagnostics the
      node carries, and the only thing a reveal reads from the node.

    Frozen and validated in :meth:`__post_init__`, so a node whose id is
    empty, whose depth is negative, or whose payload is not canonical JSON
    fails to construct rather than loading as a plausible-looking node — the
    same defence a :class:`canary._reference.CanaryTreeNode` applies to its
    own bytes, for the same reason.
    """

    node_id: str
    parent_id: str | None
    depth: int
    payload: str

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise PolicyTreeError(
                "a campaign node must carry a non-empty node_id: it is the id a "
                "parent reference and the store's uniqueness key are on, and a node "
                "with none cannot be addressed or revealed"
            )
        if self.parent_id is not None and (
            not isinstance(self.parent_id, str) or not self.parent_id.strip()
        ):
            raise PolicyTreeError(
                f"campaign node {self.node_id!r} carries an empty parent_id: a parent "
                "reference is either absent (a root) or names a node, and an empty "
                "string is neither"
            )
        if (
            isinstance(self.depth, bool)
            or not isinstance(self.depth, int)
            or self.depth < 0
        ):
            raise PolicyTreeError(
                f"campaign node {self.node_id!r} carries a depth of {self.depth!r}: "
                "depth is a non-negative integer, zero at a root, and a negative one is "
                "a level no walk could reach"
            )
        if not isinstance(self.payload, str) or not self.payload.strip():
            raise PolicyTreeError(
                f"campaign node {self.node_id!r} carries no payload: the frozen bytes "
                "the replay reads back, and a node with none froze nothing"
            )
        try:
            json.loads(self.payload)
        except (TypeError, ValueError) as exc:
            raise PolicyTreeError(
                f"campaign node {self.node_id!r} carries a payload that is not "
                f"canonical JSON: {exc}"
            ) from exc

    @property
    def content(self) -> dict[str, Any]:
        """The frozen payload, rebuilt as the mapping it came from."""
        return json.loads(self.payload)

    @classmethod
    def freeze(
        cls,
        node_id: str,
        payload: Mapping[str, Any],
        *,
        parent_id: str | None = None,
        depth: int,
    ) -> "CampaignNode":
        """Freeze a node's payload mapping into a :class:`CampaignNode`.

        Canonicalises the payload before constructing, so the node carries the
        one rendering it is frozen to — the same move
        :meth:`canary._reference.CanaryTreeNode.freeze` makes, for the same
        reason.
        """
        return cls(
            node_id=node_id,
            parent_id=parent_id,
            depth=depth,
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )


@dataclass(frozen=True)
class CampaignTree:
    """A campaign tree — a set of nodes in a stable order, one hash.

    The answer surface a :class:`PolicyQuestion` fronts.  Built from
    :class:`CampaignNode` values, sorted by ``node_id`` in
    :meth:`__post_init__` before anything is hashed or walked — a tree is its
    nodes, not the order a walk visits them.  :attr:`tree_id` is the tree's
    identity: a stable hash over the sorted nodes, so two trees holding the
    same nodes are one tree and two differing in one node are two.

    A tree is a *set*, not a filtered view: an unrevealed node is a node the
    tree holds but the question has not shown, and the tree answers it only
    when the question reveals it.  The tree itself carries no reveal history —
    that is the question's, the one fact a replay needs and a tree must not
    hold.
    """

    #: The nodes, sorted by ``node_id``.  Normalised in :meth:`__post_init__`.
    nodes: tuple[CampaignNode, ...]
    #: The tree's identity — a stable hash over the sorted nodes.  Optional in
    #: the constructor and always derived in :meth:`__post_init__` from the
    #: nodes, so a tree's identity is never trusted from input — it is the hash
    #: of exactly the nodes it holds.
    tree_id: str | None = None

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        if not nodes:
            raise PolicyTreeError(
                "a campaign tree must carry at least one node: the replay fronts a "
                "policy *over a tree*, and a tree with no nodes is a surface the "
                "policy could not walk — vacuous, the one reading the read-side "
                "question must never allow"
            )
        seen: set[str] = set()
        for node in nodes:
            if not isinstance(node, CampaignNode):
                raise PolicyTreeError(
                    f"a campaign tree is built of CampaignNode values, got {node!r}; "
                    "the tree identity is taken over node ids and payloads, and a bare "
                    "value carries neither"
                )
            if node.node_id in seen:
                raise PolicyTreeError(
                    f"the campaign tree node {node.node_id!r} appears twice: a node id "
                    "names one node, and two nodes wearing one id is a tree the policy "
                    "could not walk"
                )
            seen.add(node.node_id)
        nodes = tuple(sorted(nodes, key=lambda node: node.node_id))
        ids = {node.node_id for node in nodes}
        for node in nodes:
            if node.parent_id is not None and node.parent_id not in ids:
                raise PolicyTreeError(
                    f"campaign tree node {node.node_id!r} names a parent "
                    f"{node.parent_id!r} that is not a node in the tree: a tree with a "
                    "dangling edge is not a surface the policy could walk, and the "
                    "refusal belongs at the moment the tree is built"
                )
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "tree_id", self._hash(nodes))

    @staticmethod
    def _hash(nodes: tuple[CampaignNode, ...]) -> str:
        """The tree's identity — a stable hash over the sorted nodes.

        Over the nodes sorted by id, each rendered as ``node_id``,
        ``parent_id``, ``depth`` and the canonical payload — so two trees
        holding the same nodes are one hash and two differing in one node are
        two, whatever order the nodes were handed in.
        """
        rendered = "\n".join(
            f"{node.node_id}\x1f{node.parent_id or ''}\x1f{node.depth}\x1f{node.payload}"
            for node in nodes
        )
        return f"ctree-{len(rendered.encode())}-{abs(hash(rendered)) & 0xFFFFFFFFFFFFFFFF:016x}"

    @classmethod
    def freeze(
        cls, node_specs: Mapping[str, tuple[str | None, int, Mapping[str, Any]]]
    ) -> "CampaignTree":
        """Freeze a mapping of ``node_id -> (parent_id, depth, payload)`` into a tree.

        Builds each node through :meth:`CampaignNode.freeze` — canonicalising
        each payload — then lets :meth:`__post_init__` sort, validate the
        parent references and take the tree identity, so the caller hands over
        raw specs and gets back a tree whose every node is already frozen and
        whose identity is the identity of exactly those bytes.
        """
        nodes = tuple(
            CampaignNode.freeze(node_id, payload, parent_id=parent_id, depth=depth)
            for node_id, (parent_id, depth, payload) in node_specs.items()
        )
        return cls(nodes=nodes)

    def node(self, node_id: str) -> CampaignNode:
        """The node a node id names, or refuse it — the address seam.

        The one place a node id becomes a node: :meth:`CampaignTree.node`
        reads the node's payload, and the question reads the node's metrics
        off it, so an observation and a node cannot drift.  Refuses with
        :class:`PolicyAddressError` a node id the tree does not hold, naming
        the node and the tree — a node id a policy hands to the question is
        one it was shown, and a node outside the tree names a cell the policy
        never saw.
        """
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise PolicyAddressError(
            f"the tree holds no node {node_id!r}: a node id a policy hands to the "
            "question is one it was shown, and a node outside the tree names a cell "
            "the policy never saw"
        )


@dataclass(frozen=True)
class PolicyObservation:
    """The payload a revealed node carries — the node's honest in-sample reading.

    A frozen value, because an observation is a *recorded* fact — what a policy
    saw when it revealed a cell — and a policy comparing two cells must not be
    able to move either.  It carries the in-sample metrics and diagnostics the
    node's payload carries — the honest reading the tree exists to give —
    attributed to the node id it was earned on.  Nothing is rescored or
    narrowed, and nothing the information barrier forbids is carried: never
    ``is_null`` (readable by exactly one component, the replay scorer — prd
    §4.2, cq-8), never an absolute score target, never an unrevealed node's
    score, never a hardcoded node id.

    The metrics are read from the node's payload by name, defaulting to
    ``None`` when the payload carries no such metric — a node that carries no
    in-sample reading is a structural node, not a scored leaf, and its
    observation says so rather than inventing a number.  The observation is
    therefore self-attributing: it is not a bare score but a ``(node_id,
    metrics)`` pair, the shape the read-side question needs to report what a
    policy has seen.
    """

    node_id: str
    r2_insample: float | None
    ic_insample: float | None
    n_periods: int | None
    n_features: int | None

    @classmethod
    def from_node(cls, node: CampaignNode) -> "PolicyObservation":
        """Build the observation a node's payload makes — the metrics, attributed.

        The one place the payload's metrics are read into the payload, so the
        observation and the node cannot drift: every observation is made here,
        and "a node's observation" has exactly one implementation.  The metrics
        are read by name from the node's canonical JSON, so a node that carries
        no metric answers ``None`` rather than a number the barrier never
        froze.
        """
        payload = node.content
        return cls(
            node_id=node.node_id,
            r2_insample=payload.get("r2_insample"),
            ic_insample=payload.get("ic_insample"),
            n_periods=payload.get("n_periods"),
            n_features=payload.get("n_features"),
        )

    def row(self) -> dict[str, Any]:
        """The observation as a store-shaped mapping — a fresh dict per call.

        The payload a replay writes down: the node, and the in-sample metrics
        it carried.  A fresh dict per call, never a shared one, for the reason
        a frozen observation cannot be moved.
        """
        return {
            "node_id": self.node_id,
            "r2_insample": self.r2_insample,
            "ic_insample": self.ic_insample,
            "n_periods": self.n_periods,
            "n_features": self.n_features,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PolicyObservation(node_id={self.node_id!r}, "
            f"r2_insample={self.r2_insample!r})"
        )


class PolicyQuestion:
    """The policy-facing read side of the identical question.* interface — feature 217.

    Wraps a :class:`CampaignTree` and answers the read side of the identical
    ``question.*`` API docs/nullius-tech-architecture.md §11 names —
    :meth:`observed` (the revealed cells and their honest observations) — so
    one policy written against a financial campaign runs unmodified against a
    campaign tree.  The question is bound to the tree it fronts: its
    observations are the tree's honest payload-derived readings, so the two
    cannot drift — change the tree and the question's answers change with it,
    to the same cells.

    The only state the question adds to the tree is the *reveal set* — the
    cells a policy has committed to look at — and that is the one fact a replay
    needs and a tree must not hold (a tree holding a reveal history would be a
    tree whose answers depended on how often it had been asked, which is not a
    ground truth).  Every other answer is a pure function of ``(tree,
    node_id)``, computed afresh each call, so the same node revealed twice
    answers the identical observation whatever order the reveals came in.

    Constructed from the tree it fronts; the tree is validated at construction,
    so a question built over a non-tree or an empty tree is refused before it
    can hand a policy an interface that would answer differently from the tree
    it claims to front.
    """

    __slots__ = ("_revealed", "_tree")

    def __init__(self, tree: CampaignTree) -> None:
        # Duck-typed, not ``isinstance``: the module loader imports the member
        # under a synthetic name and re-executes it, so the composed tree is a
        # *second* CampaignTree class object, distinct from this module's.  An
        # ``isinstance`` here would refuse the very tree ``create_app()`` hands
        # out — breaking "one policy, both pools" at the composition seam.
        # Instead the tree is checked for the answer-surface it must front: the
        # attributes the question calls through — ``nodes`` and ``node`` — and
        # a string or a bare object has none of them and is refused, naming
        # what was wrong.
        if not hasattr(tree, "nodes") or not hasattr(tree, "node"):
            raise PolicyTreeError(
                f"a question fronts a campaign tree — got {tree!r} "
                f"({type(tree).__name__}), which has no nodes/node; the question is "
                "the tree's policy-facing side, and an object that is not a tree "
                "names no surface a policy can be handed"
            )
        if not tuple(getattr(tree, "nodes", ())):
            raise PolicyTreeError(
                "a question fronts a tree that carries at least one node: the policy "
                "fronts a policy over a tree, and a tree with no nodes is a surface "
                "the policy could not walk"
            )
        self._tree = tree
        self._revealed: set[str] = set()

    @property
    def tree(self) -> CampaignTree:
        """The tree this question fronts — read-only."""
        return self._tree

    @property
    def revealed(self) -> frozenset[str]:
        """The node ids revealed so far — the question's private reveal set."""
        return frozenset(self._revealed)

    def observed(self) -> dict[str, PolicyObservation]:
        """The revealed cells and their observations — ``{node_id: Observation}``.

        The cells a policy has revealed so far, each mapped to the observation
        its payload made, ascending by node id — an explicit sort before the
        reduction, the ordering rule docs §12 states for a search frontier, so
        two reads of one question agree whatever order the reveals came in.
        Each observation is the tree's honest payload-derived reading of the
        cell, so the map is a pure function of the revealed set: the same cells
        revealed in any order return the same observations.

        Prefix-only by construction: the accessor iterates the question's own
        reveal set and builds one observation per revealed node, so an
        unrevealed node is *absent* from the returned mapping rather than
        filtered out of it — never a key, never a value, never reachable by
        introspection, attribute walking, or a stray ``__dict__`` access (docs
        §10.2, cq-16).  A policy holding the mapping holds only what it has
        already seen.
        """
        return {
            node_id: PolicyObservation.from_node(self._tree.node(node_id))
            for node_id in sorted(self._revealed)
        }

    def reveal(self, node_id: str) -> PolicyObservation:
        """Reveal one cell, returning its observation — the write side of the set.

        Adds ``node_id`` to the reveal set and returns the observation its
        payload made.  Refuses with :class:`PolicyAddressError` a node outside
        the tree, naming the node and the tree — a policy reveals only cells it
        was shown, and a reveal that named a cell the tree does not hold would
        let the policy think it had seen one.  The observation is the tree's
        honest payload-derived reading, so the reveal and the record are one
        act and cannot drift apart.
        """
        node = self._tree.node(node_id)  # refuses a node outside the tree
        self._revealed.add(node_id)
        return PolicyObservation.from_node(node)

    def reveal_many(self, node_ids: Iterable[str]) -> dict[str, PolicyObservation]:
        """Reveal a batch of cells at once, returning their observations.

        Reveals a batch of cells at once, returning ``{node_id:
        PolicyObservation}`` for the cells revealed *by this call* (an
        already-revealed cell is not re-returned — the call is idempotent on
        the revealed set, so a policy that re-reveals a cell it holds does not
        see it as new).  The whole batch is validated against the tree before
        any cell is revealed, so a batch that names a cell the tree does not
        hold is refused naming the cell and the tree and reveals none of them —
        a policy cannot slip one invalid reveal past a batch of valid ones, and
        the reveal set is never left half-applied.
        """
        nodes = [self._tree.node(candidate) for candidate in node_ids]
        newly = [node for node in nodes if node.node_id not in self._revealed]
        for node in newly:
            self._revealed.add(node.node_id)
        return {node.node_id: PolicyObservation.from_node(node) for node in newly}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"PolicyQuestion(tree_id={self._tree.tree_id!r}, revealed={len(self._revealed)})"


def policy_question(tree: CampaignTree) -> PolicyQuestion:
    """Turn a campaign tree into the read-side question.* adapter a policy expects.

    The one factory for the identical interface: a :class:`CampaignTree` in,
    the :class:`PolicyQuestion` a policy expects out.  The adapter is bound to
    the tree it fronts — its observations are the tree's — so the
    identical-interface requirement is a single call site rather than a
    construction a caller could get wrong.  Refuses a non-tree or an empty tree
    at construction, naming what was wrong, and two adapters of one tree answer
    identical observations to the last field — the property that makes "one
    policy, both pools" a fact about the adapter rather than a promise in a
    docstring.
    """
    return PolicyQuestion(tree)


@register(CAMPAIGN_TREE_COMPONENT)
def build_campaign_tree() -> CampaignTree | None:
    """Component builder: the campaign tree the deployment's artifact store holds.

    Takes no arguments — that is the factory's registration protocol — and
    resolves the tree from the deployment's artifact store at build time, so a
    composed application carries the read-side question for the tree the
    process is actually pointed at.  Returns ``None`` for a deployment that
    names no store rather than raising — the degrade-don't-break stance every
    store-bound builder in this workspace takes (:func:`artifacts.build_dedup_gate`,
    :func:`canary._registered_reference_store`), because the factory builds
    every registered component on every ``create_app()`` call and a builder
    that raised would take composition down for every unrelated feature.
    ``None`` is a discoverable state, not an error: it is a deployment with no
    campaign tree to front — while a replay that *must* have one is the caller
    that must not find itself in it.

    Construction performs no I/O: the store is resolved on first use, so
    composing an application that carries this component touches no disk, and
    the tree is read only when a caller demands it.  The tree is the same
    ``(node_id -> parent_id, depth, payload)`` node model the frozen evaluator
    and the nightly canary address, owned by this member rather than imported
    from canary because a member never imports another member.
    """
    return _resolve_tree()


#: A second spelling of the builder, for a caller that wants the tree without
#: reaching for the composed application.  Not a component and not registered —
#: registering it would put two components of the same name in the registry and
#: the later import would silently win, the hazard ``app.module_loader``
#: documents — so this is an ordinary function a script or a sibling suite
#: calls directly.
build_campaign_tree_component = build_campaign_tree


def _resolve_tree() -> CampaignTree | None:
    """The campaign tree the deployment's artifact store holds, or ``None``.

    Resolved lazily so construction performs no I/O — the store is imported
    inside the function, not at module scope, keeping this module
    import-cheap and free of a hard dependency on the store's availability at
    composition time.  A deployment that names no store, or a store that holds
    no committed campaign, composes ``None`` — a discoverable state — rather
    than raising, and the replay that must have a tree is the caller that
    resolves it explicitly and refuses against it.
    """
    try:  # pragma: no cover - exercised through the composed component
        from app.modules.artifacts import artifact_store_component

        store = artifact_store_component()
        if store is None:
            return None
        # Read the store's committed nodes into this member's own tree model.
        # A member never imports another member, so the store's node listing is
        # read as raw specs and rebuilt here — the one fact they share is the
        # node model, and it is small enough to restate.
        specs: dict[str, tuple[str | None, int, dict[str, Any]]] = {}
        for campaign_id in store.campaign_ids():
            for node_id in store.node_ids(campaign_id):
                # The store holds the node's canonical payload bytes; rebuild the
                # (parent_id, depth, payload) spec the tree freezes from.
                files = store.files(campaign_id, node_id)
                if not files:
                    continue
                payload_bytes = store.read(campaign_id, node_id, files[0])
                payload = json.loads(payload_bytes.decode("utf-8"))
                specs[node_id] = (
                    payload.get("parent_id"),
                    int(payload.get("depth", 0)),
                    payload,
                )
        if not specs:
            return None
        return CampaignTree.freeze(specs)
    except Exception:  # noqa: BLE001 - a missing store must not break composition
        return None
