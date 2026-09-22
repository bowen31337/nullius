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
that remembers which cells have been revealed, and the thing a policy
*extends* that set through (feature 220's ``probe_batch``, the verb the read
side is read over).  The tree answers *what is true here?*; the question
answers *what has this policy seen?* — two facts that should not share one
object, and the reason the category's later features (218's frontier, 219's
meta, 222's commit) build on *this* seam rather than on the tree's.

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

**The prefix grows through one verb, and a batch is what a policy selects
(feature 220).**  §11's next line is the *write* side of the read side 217
built — ``question.probe_batch(cells, on_reveal=...)`` (docs §596, prd §421) —
and it is the verb a policy's whole exploration is made of: prd §436's
*"must terminate when no batch is selected"* names the batch as the unit of
decision, so a probe is how a policy spends a round and how the prefix it is
prefix-only *over* comes to exist.  :meth:`PolicyQuestion.probe_batch` reveals
a batch at once — deduplicated and in ascending node-id order (docs §12's
ordering rule, already fixed for ``observed()``), validated in full against
the tree **before** any cell is revealed so a bad cell refuses the whole batch
and leaves the reveal set half-applied never, and returning
``{node_id: Observation}`` for the cells revealed *by this call*, so a
re-probe of a cell the question already holds returns nothing new and the call
is idempotent on the revealed set.  ``on_reveal`` is the reveal callback the
sentence names: called **once per newly revealed cell**, in the same ascending
order, and never for a cell already held — the hook a replay uses to record
what a policy looked at, with the batch already applied by the time it fires,
and refused up front in this member's own vocabulary when it is not a
callable.  It is the *same signature* feature 184's
:meth:`bootstrap.BootstrapQuestion.probe_batch` answers, which is what makes
"one policy, both pools" a fact about the seam: the canonical policy the
admission suite screens and the trial recorder (feature 185) duck-types on
both spell this verb, and neither knows which pool it is running against.
:meth:`PolicyQuestion.reveal_many` remains the name feature 217 shipped this
act under, now a delegation to :meth:`PolicyQuestion.probe_batch` rather than
a second implementation, so the two names cannot drift; :meth:`PolicyQuestion.reveal`
is the one-cell verb beside them, and the split is the one feature 222's
commit draws from the other side.  Nothing is charged: what a probe costs is
the ledger's accounting, not a counter this object keeps.

**The budget a policy reads is statistical, and the other one is not
reported (feature 221).**  §11's interface has a second read verb —
``question.budget_remaining()  # statistical, not compute`` — and the eight
words after the hash are the feature: the system meters two things and calls
both of them budgets.  The **statistical** budget is degrees of freedom, what
§10.3's score subtracts (``− β₁ · trials_charged``) and what §8's
``charges_budget`` column stamps a trial with; the **compute** budget is the
machine — §5.2's cgroup plane (features 162/163), the agent's calls, §10.1's
``K2`` rounds — and prd §123 records that it is *not* the binding resource
(*"compute is cheap and degrees of freedom are the binding resource"*).  The
distinction is not ours to invent: prd §705 is a table of the paper's Equation
1 as it was changed, and its first row replaces ``β₁ N (agent calls)`` — a
compute quantity — with ``β₁ · trials charged (statistical budget)``.
:mod:`.budget` therefore reads §8's directive and **only** the directive:
:func:`budget_account` counts the rows whose ``charges_budget`` is true and
never sums §8's ``charge_units``, which the ledger member's own module states
*"prices compute"*.  The account is the runtime's object — it holds the
allowance and the charges, so it can answer how much has been *spent* — while
what :meth:`PolicyQuestion.budget_remaining` hands a policy is a
:class:`StatisticalBudget`: one number, carrying its denomination and nothing
else, which is feature 224's law (§10.2 withholds ``budget_spent``) kept
structurally one seam beneath the surface that refuses the name.

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

**The structure a cell carries, read beside its reading (feature 219).**  §11's
fourth line is ``question.meta(node_id) -> CellMeta`` (docs §595), commented
with the four fields it carries — *"structural: branch, depth, parent,
theme_root"* — and it lives in :mod:`.meta` as :class:`CellMeta` and
:func:`cell_meta`, with :meth:`PolicyQuestion.meta` the accessor a policy is
handed.  It is the *structural* read beside ``observed()``'s scored one, and the
one road to a cell's ``theme_root``: docs §634's static check — *"``theme_root``
used only via ``meta()``"* — is what feature 230's admission gate screens for,
and it is the slug feature 228's family-conditional thresholds are keyed on, so
the accessor is the seam the conditioning is allowed to read rather than a
convenience beside it.  All four fields are *derived from the tree or read from
the node's own record* rather than stored: ``parent`` is the tree's validated
edge, ``depth`` is the number of parent steps to the branch's origin and
``branch`` is that origin's id (grouping the cells feature 236's per-branch
difficulty census is taken over), and ``theme_root`` is §9.1's ``theme_root``
column as the node froze it — absent when the record states none, refused when
the record states something that is not a name.  Structure is the tree's
*shape* — not the scores §10.2's barrier withholds and not the ``is_null`` cq-8
confines to the replay scorer — so the accessor answers for any node the tree
holds, revealed or not, which is the stance the sibling pool takes and what
lets family-conditional thresholds be authored before the cells they condition
are seen; it refuses only a node the tree does not hold, through the same
address seam ``reveal`` and ``probe_batch`` route through.  No new error class
and no component: every refusal is one the member already owns
(:class:`PolicyAddressError` for the address, :class:`PolicyTreeError` for a
corrupt structural record), and the accessor closes over no deployment state at
all.

**The terminal commit: one call, one node, and −∞ for the policy that never
makes it.**  Feature 222 (docs §598: ``question.commit(node_id)  # REQUIRED;
omitting scores −inf``; prd §438: *"``commit()`` is mandatory. A policy that
terminates without committing scores ``−∞``."*) lives in :mod:`.commit` as
:class:`EpisodeCommit` and :func:`episode_commit` over the question's address
seam, :class:`CommittedPick` (the one node the episode named) and
:class:`Termination` (the frozen read at termination, whose
:meth:`~policy_runtime.Termination.score` answers
:data:`NON_COMMITTING_SCORE` for the non-committing policy and never calls the
scorer it was handed on a pick that was never made).  Where the rest of the
``question.*`` surface is *during* — reads, probes, budget — the commit is the
terminal act, and the two halves of its law are asymmetric on purpose: the
malformed acts around the call are refused (:class:`PolicyCommitError` — a
call naming zero or several nodes, a second commit, a commit after
termination), while the *absence* of the call is not an error at all but the
worst score, so the dreaming loop's argmax ranks a non-committing revision
last instead of dropping it from the comparison.  The address refusal is the
tree's own (:class:`PolicyAddressError`, the same seam ``reveal`` refuses
through), and the static half of the same law — ``commit()`` reachable on
every terminating path — is feature 230's screen over the authored source,
the before/during split this member already draws between the admission gate
and the runtime guard.

Stdlib only, and import-cheap: no third-party import at module scope, so the
factory's scan — which imports this package to fire its ``@register`` — pays
nothing for the seam.
"""

from __future__ import annotations

import json
import numbers
from collections.abc import Callable, Iterable, Mapping
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
from .budget import (
    COMPUTE_UNITS,
    STATISTICAL_UNIT,
    UNBOUNDED_BUDGET,
    BudgetAccount,
    StatisticalBudget,
    budget_account,
)
from .commit import (
    NON_COMMITTING_SCORE,
    CommittedPick,
    EpisodeCommit,
    Termination,
    episode_commit,
)
from .errors import (
    BetaFixedError,
    FamilyThresholdError,
    PolicyAddressError,
    PolicyAnswerSurfaceError,
    PolicyAdmissionRefusal,
    PolicyBudgetError,
    PolicyCommitError,
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
from .meta import (
    THEME_ROOT_KEY,
    CellMeta,
    cell_meta,
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
    "BudgetAccount",
    "COMPUTE_UNITS",
    "CampaignNode",
    "CampaignTree",
    "CellMeta",
    "CommittedPick",
    "EpisodeBeta",
    "EpisodeCommit",
    "EXPLORE_EXPLOIT",
    "FamilyConditional",
    "FamilySchedule",
    "FamilyThresholdError",
    "DEFAULT_ANSWERS",
    "FORBIDDEN_ANSWERS",
    "GUARD_ACTIVE",
    "GridPlan",
    "GridPlanningContext",
    "NON_COMMITTING_SCORE",
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
    "PolicyBudgetError",
    "PolicyCeiling",
    "PolicyCommitError",
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
    "STATISTICAL_UNIT",
    "StatisticalBudget",
    "THEME_ROOT_KEY",
    "Termination",
    "UNBOUNDED_BUDGET",
    "budget_account",
    "cell_meta",
    "episode_commit",
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

    The reveal set grows through the write side of the same interface:
    :meth:`probe_batch` (feature 220) reveals a batch of cells at once and
    returns the observations it newly revealed, calling an optional
    ``on_reveal`` hook once per new cell; :meth:`reveal` is the one-cell verb
    beside it, and :meth:`reveal_many` the name feature 217 shipped the batch
    under, kept as a delegation so the two spellings of one act cannot drift.
    ``probe_batch`` carries the signature §11 states and the sibling pool
    answers, which is what makes the identical-interface claim a fact about
    the seam rather than a promise.

    Constructed from the tree it fronts; the tree is validated at construction,
    so a question built over a non-tree or an empty tree is refused before it
    can hand a policy an interface that would answer differently from the tree
    it claims to front.

    The question also answers **the other half of §11's read side** —
    :meth:`budget_remaining`, feature 221's statistical budget — and it is
    configured at construction, out of the same one-factory discipline: a
    caller passes the :class:`BudgetAccount` its campaign's charges make, and
    the question answers :attr:`BudgetAccount.remaining`.  The *account* is the
    runtime's object and the *reading* is what the policy is handed, which is
    the audience split :meth:`budget_remaining` documents at length; a question
    built with no account is a question over a deployment that stated no
    statistical ceiling, and answers :data:`UNBOUNDED_BUDGET` — the same
    statement :meth:`bootstrap.BootstrapQuestion.budget_remaining` makes for a
    bootstrap world's zero statistical cost, so "one policy, both pools" holds
    for this verb as it does for :meth:`observed`.
    """

    __slots__ = ("_budget", "_revealed", "_tree")

    def __init__(self, tree: CampaignTree, budget: BudgetAccount | None = None) -> None:
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
        if budget is not None:
            # Duck-typed for the same reason the tree is: a composed account is
            # a *second* BudgetAccount class object, so ``isinstance`` would
            # refuse the very account ``budget_account()`` handed a sibling
            # caller.  The seam is checked for the one answer the question
            # reads off it — ``remaining``, a *property* rather than a verb,
            # which is why the check is a read and not ``callable()``: a bound
            # method here would be a different shape answering the same name.
            # Everything else is refused naming what arrived — neither skipped
            # (a question answering an arbitrary number) nor coerced back
            # through ``budget_account()``, which would make a *bare float*
            # look like a budget: the substitution feature 221's sentence is
            # written against. ``5.0`` names no resource, and "is this five
            # trials or five seconds?" is the question the feature answers.
            try:
                remaining: Any = budget.remaining
            except Exception as exc:  # any failure to read the answer is this law's
                raise PolicyBudgetError(
                    f"a question's budget is an object answering `remaining` — "
                    f"the statistical budget left, the reading a policy is "
                    f"handed — and a bare number is refused rather than "
                    f"wrapped, because a float names no resource and 'is this "
                    f"five trials or five seconds?' is the question feature "
                    f"221 exists to answer. Build one with "
                    f"budget_account(allowance, rows), whose own `remaining` is "
                    f"that reading, or pass a live account the replay updates "
                    f"as trials charge — or pass no budget at all for a "
                    f"deployment that stated no statistical ceiling. Got "
                    f"{budget!r} ({type(budget).__name__}), which answers none: "
                    f"reading `remaining` raised {exc!r} (feature 221)"
                ) from exc
            if isinstance(remaining, bool) or not isinstance(remaining, numbers.Real):
                raise PolicyBudgetError(
                    f"a question's budget must answer `remaining` as a real "
                    f"number of remaining trials charged — the runtime's "
                    f"BudgetAccount does, so the reading a policy is handed is "
                    f"the campaign's own; got {budget!r} "
                    f"({type(budget).__name__}), whose `remaining` is "
                    f"{remaining!r} ({type(remaining).__name__}). A bare number "
                    f"is refused here rather than wrapped: a float names no "
                    f"resource, and 'is this five trials or five seconds?' is "
                    f"the question feature 221 exists to answer. Build one with "
                    f"budget_account(allowance, rows) — or pass no budget at "
                    f"all for a deployment that stated no statistical ceiling"
                )
        self._tree = tree
        self._budget = budget
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
        return {node_id: self._observe(node_id) for node_id in sorted(self._revealed)}

    def _observe(self, node_id: str) -> PolicyObservation:
        """The observation a revealed cell holds — the tree's reading, attributed.

        The one spelling of "a node's observation": :meth:`observed`,
        :meth:`reveal` and :meth:`probe_batch` all route through it, so an
        observation made by a batch sweep and one made by a single reveal
        cannot drift — the discipline
        :meth:`bootstrap.BootstrapQuestion._observe` keeps on the other pool's
        side of the identical interface.  The reading is the tree's honest
        payload-derived one, read through the address seam, so an observation
        and the node it was earned on are one act.
        """
        return PolicyObservation.from_node(self._tree.node(node_id))

    def meta(self, node_id: str) -> CellMeta:
        """The structural metadata of a cell — ``question.meta(node_id)``, feature 219.

        The fourth line of §11's identical ``question.*`` interface
        (docs/nullius-tech-architecture.md §595)::

            question.meta(node_id)     -> CellMeta          # structural: branch, depth, parent, theme_root

        — the *structural* read beside :meth:`observed`'s scored one, and the
        one road to a cell's ``theme_root`` (docs §634's static check: *"used
        only via ``meta()``"*).  It answers the four fields the architecture
        names — the branch the cell sits in, its depth below that branch's
        origin, its parent, and the research theme the branch was planted in —
        and it answers them for **any** node the tree holds, revealed or not:
        structure is the tree's shape, not the reading §10.2's barrier
        withholds (feature 184's own accessor refuses only a node *"outside the
        lattice"*, and the identical-interface claim needs the barrier's edge in
        the same place on both sides).  That openness is the point rather than a
        concession: §11.1 exposes ``theme_root`` here precisely so
        family-conditional thresholds can be authored *before* the cells they
        condition are revealed.

        A **delegation** to :func:`cell_meta`, not a second derivation — the
        same discipline :meth:`_observe` keeps for the reading beside it, so
        the campaign question and any later caller in this category read one
        spelling of "a cell's structure" over one tree.

        Refuses with :class:`PolicyAddressError` a node the tree does not hold
        — the address seam :meth:`reveal` and :meth:`probe_batch` route through,
        so a node id a policy hands to ``meta`` is one it was shown, and
        structure computed for a cell outside the tree would let a policy reason
        about a campaign it never saw.  The reveal set is not consulted, not
        read and not grown: a meta is a structure and a reveal is an act, and
        this verb is the former.

        A node id that is not a string at all is refused in the same vocabulary
        rather than by a bare :class:`TypeError` from the tree's comparison — an
        unhashable or exotic id reaching the store's address verb is a caller
        mistake this member states rather than lets escape, so a caller's own
        ``except PolicyRuntimeError`` catches every way a structural read can
        fail.
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise PolicyAddressError(
                f"a cell's meta is read for a node id — got {node_id!r} "
                f"({type(node_id).__name__}), which names no cell: the four "
                "structural fields of docs §595 — branch, depth, parent, "
                "theme_root — are facts about a node the tree holds, and a value "
                "that is not an id names none of them (feature 219)"
            )
        return cell_meta(self._tree, node_id)

    def reveal(self, node_id: str) -> PolicyObservation:
        """Reveal one cell, returning its observation — the write side of the set.

        Adds ``node_id`` to the reveal set and returns the observation its
        payload made.  Refuses with :class:`PolicyAddressError` a node outside
        the tree, naming the node and the tree — a policy reveals only cells it
        was shown, and a reveal that named a cell the tree does not hold would
        let the policy think it had seen one.  The observation is the tree's
        honest payload-derived reading, so the reveal and the record are one
        act and cannot drift apart.

        One cell is the whole of what this verb reveals; a batch is
        :meth:`probe_batch`'s, and the split is the one feature 222's commit
        draws from the other side (a commit names one node and refuses a
        collection — *"probe_batch is the batch verb"*).
        """
        node = self._tree.node(node_id)  # refuses a node outside the tree
        self._revealed.add(node_id)
        return PolicyObservation.from_node(node)

    def probe_batch(
        self,
        cells: Iterable[str],
        on_reveal: Callable[[str], None] | None = None,
    ) -> dict[str, PolicyObservation]:
        """Reveal a batch of cells at once — §11's ``probe_batch``.

        docs/nullius-tech-architecture.md §596's line in the identical
        ``question.*`` interface — ``question.probe_batch(cells, on_reveal=...)``
        — which prd §421 repeats verbatim in §C4's listing.  The batch is the
        unit a policy selects (prd §436: *"must terminate when no batch is
        selected"*), so this is the verb that extends the prefix, and it is
        the *same verb* on both pools: feature 184's
        :meth:`bootstrap.BootstrapQuestion.probe_batch` answers this exact
        signature, which is what makes "one policy, both pools" a fact about
        the seam rather than a promise in a docstring.

        Reveals each cell of ``cells``, returning ``{node_id:
        PolicyObservation}`` for the cells revealed **by this call** — an
        already-revealed cell is not re-returned, so a policy that re-probes a
        cell it holds does not see it as new, and the call is idempotent on
        the revealed set.  ``on_reveal``, when given, is called **once per
        newly revealed cell**, and never for a cell the question already held:
        it is the hook a replay uses to record what a policy looked at
        (feature 185's trial recorder reads this verb's return value; a
        deployment watching a walk in flight reads the callback), so a
        re-probe is not a double-count.  Passing ``None`` — the default —
        means no hook, and a policy that wants only the readings pays nothing
        for it.

        **Ascending, deduplicated, and all-or-nothing.**  The batch is
        reduced to ``sorted(set(cells))`` before anything happens, so a
        duplicate in the batch is one cell and the whole call — the reveal
        set's growth, the callbacks, the returned mapping — runs in ascending
        node-id order, the ordering rule docs §12 states for a search frontier
        and the one feature 217 already fixed for :meth:`observed`.  Every
        cell is then validated against the tree **before** any is revealed, so
        a batch naming a cell the tree does not hold is refused with
        :class:`PolicyAddressError` — naming the node and the tree, the same
        class :meth:`reveal` refuses through — and **reveals none of them**: a
        policy cannot slip one invalid reveal past a batch of valid ones, and
        the reveal set is never left half-applied.

        **The acts are ordered, and the order is load-bearing.**  The cells
        are revealed, *then* the callbacks fire, *then* the mapping is
        returned — so a hook that reads :meth:`observed` inside ``on_reveal``
        sees the batch already applied rather than the prefix as it stood
        before, and a hook that raises leaves the reveal set correct rather
        than half-written.  The callback receives the **node id**, not the
        observation: the id is the address the reveal set is keyed by and the
        one fact a hook needs to act on, while the readings are what the
        return value is for — and it is what the other pool's ``on_reveal``
        passes, so a hook written against one pool runs unmodified against the
        other.

        ``on_reveal`` is validated **before** any cell is revealed, so a hook
        that is not a callable refuses the call in this member's own
        vocabulary rather than as a bare :class:`TypeError` escaping the loop
        after the reveal set had already grown — the error-vocabulary
        discipline every seam in this member keeps, and the reason a caller's
        own ``except PolicyRuntimeError`` catches it.

        Nothing is charged here.  §11's ``probe_batch`` is the batch *verb*;
        what a probe costs is the ledger's accounting (feature 185's
        ``charges_budget`` row, feature 221's :meth:`budget_remaining` reading
        it against the allowance), and the two are deliberately apart —
        ``commit.py``'s own text has probe_batch *"spend budget to extend"* the
        prefix, which is a fact about the campaign's charges rather than a
        counter this object keeps.  A question holding no account answers
        :data:`UNBOUNDED_BUDGET` before and after a probe.
        """
        if on_reveal is not None and not callable(on_reveal):
            raise PolicyTreeError(
                f"a probe's on_reveal hook is a callable the question calls "
                f"once per newly revealed cell — got {on_reveal!r} "
                f"({type(on_reveal).__name__}), which cannot be called; the "
                f"hook is how a replay records what a policy looked at, and a "
                f"value the question cannot call would be a reveal the caller "
                f"never heard about (feature 220, docs §596). Pass a callable, "
                f"or pass nothing at all for a probe that only returns its "
                f"readings"
            )
        # Reduced and ordered first: a duplicate in the batch is one cell, and
        # every act below — the validation, the reveal set's growth, the
        # callbacks, the returned mapping — runs in ascending node id order,
        # the ordering rule docs §12 states for a search frontier.
        ordered = sorted(set(cells))
        # Validated up front, so a bad cell refuses before any cell is
        # revealed: a half-applied batch would leave the reveal set in a
        # state the policy did not ask for, and a probe is all-or-nothing.
        nodes = [self._tree.node(candidate) for candidate in ordered]
        newly = [node for node in nodes if node.node_id not in self._revealed]
        for node in newly:
            self._revealed.add(node.node_id)
        # The hook fires after the reveal set has grown, so a callback reading
        # ``observed()`` sees the batch already applied.
        if on_reveal is not None:
            for node in newly:
                on_reveal(node.node_id)
        return {node.node_id: self._observe(node.node_id) for node in newly}

    def reveal_many(self, node_ids: Iterable[str]) -> dict[str, PolicyObservation]:
        """Reveal a batch of cells at once, returning their observations.

        The batch verb under the name feature 217 shipped it with, kept as a
        **delegation** to :meth:`probe_batch` rather than as a second
        implementation: ``probe_batch`` is what §11 calls this act
        (docs §596, prd §421) and what the sibling pool, the trial recorder
        and the planning boundary all spell, so the two names must front one
        behaviour — and a second body here would be a second set of
        guarantees free to drift from the first.  Every property below is
        :meth:`probe_batch`'s, read through the same code: the batch is
        deduplicated and handled in ascending node-id order, it is validated
        against the tree before any cell is revealed so a bad cell refuses the
        whole batch and leaves the reveal set untouched, and only the cells
        revealed *by this call* are returned — an already-revealed cell is not
        re-returned, so the call is idempotent on the revealed set.

        It takes no ``on_reveal``: a caller that wants the hook — the replay
        recording what a policy looked at — calls :meth:`probe_batch`, which
        is the spelling the spec and the other pool use.
        """
        return self.probe_batch(node_ids)

    def budget_remaining(self) -> StatisticalBudget:
        """The episode's statistical budget — feature 221, and not the compute one.

        docs/nullius-tech-architecture.md §597's line in the identical
        ``question.*`` interface — ``question.budget_remaining()  # statistical,
        not compute`` — which prd §422 repeats verbatim.  The answer is the
        campaign's charge account read against its allowance:
        :attr:`BudgetAccount.remaining`, one :data:`STATISTICAL_UNIT` per trial
        whose §8 ``charges_budget`` directive says it consumed degrees of
        freedom.

        **What it is not is the feature.**  §8's ``charge_units`` (*"1.0
        default; CV folds may cost more"*, feature 89 — the column the ledger
        member's own module states *"prices compute"*), §5.2's cgroup plane
        (``cpu_s``, ``mem_mb``, ``pids``, feature 162), feature 163's wall-clock
        budget, the agent's calls and §10.1's ``K2`` rounds are all budgets this
        verb does **not** report — and prd §705 records why the distinction is
        load-bearing rather than tidy: the paper's penalty counted
        ``β₁ N (agent calls)``, a compute quantity, and was replaced by
        ``β₁ · trials charged`` precisely because *"backtests are embarrassingly
        parallel and cheap. Parallelism is not the bottleneck. Data is."*
        (§315).  A caller that wants the machine's budget has features 162 and
        163; a policy that got one here would be metering the resource the
        system already decided was not binding.

        **The value carries its denomination and nothing else.**  What is
        returned is a :class:`StatisticalBudget` — a number, in the unit prd
        §705 names — and not the account: no allowance, no charge list, no
        :attr:`BudgetAccount.spent`.  That last omission is feature 224's law,
        one seam beneath the surface that enforces it (§10.2 withholds
        ``budget_spent``; :mod:`policy_runtime.surface` refuses the *name*),
        and it is kept structurally rather than by convention: a policy holding
        the reading holds one float, so there is no attribute to walk to the
        number the law withholds.

        **The reading is live, and that is not the same as the reading being
        movable.**  The account is read afresh on every call, so a policy that
        spends its budget across rounds watches the figure fall — which is the
        whole point of the verb (a policy's own mandate must let it terminate,
        and a frozen figure could not tell it when).  What cannot move is a
        *reading already taken*: :class:`StatisticalBudget` refuses every
        reassignment path, so the number in a policy's hand is what the
        campaign's charges said at the moment it was read.  The two rules are
        the two halves of one fact — the budget changes, a reading of it does
        not — and feature 226's fixed scalar is the contrast rather than the
        precedent: beta is fixed *by the deployment*, while this figure is a
        *measurement* of a spend that keeps happening.

        A question built with no account answers :data:`UNBOUNDED_BUDGET` —
        the deployment stated no statistical ceiling, which is not a ceiling of
        zero.
        """
        account = self._budget
        if account is None:
            return StatisticalBudget(UNBOUNDED_BUDGET)
        try:
            remaining = account.remaining
        except PolicyBudgetError:
            raise
        except Exception as exc:  # a live account that cannot answer is this law's
            # The account is read *live*, so unlike the construction-time seam
            # this read happens during the episode, against an object a replay
            # owns. A bare exception escaping here would reach authored policy
            # code as a failure of no named law — and the policy's own
            # ``except PolicyRuntimeError`` (the member's one base class) would
            # not catch it. Translated rather than propagated, the rule every
            # seam in this member keeps; a refusal that is *already* this law's
            # passes through unchanged so the specific message survives.
            raise PolicyBudgetError(
                f"the episode's statistical budget could not be read: the "
                f"account answered `remaining` with {exc!r}. The reading is "
                f"one trials-charged figure and a policy's termination test "
                f"depends on it, so an account that cannot answer leaves the "
                f"policy no way to stop on its budget (feature 221). Got "
                f"{account!r} ({type(account).__name__})"
            ) from exc
        return StatisticalBudget(remaining)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"PolicyQuestion(tree_id={self._tree.tree_id!r}, revealed={len(self._revealed)})"


def policy_question(
    tree: CampaignTree, budget: BudgetAccount | None = None
) -> PolicyQuestion:
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

    ``budget`` is the campaign's :class:`BudgetAccount` — feature 221's other
    half of the read side, passed through to :meth:`PolicyQuestion.budget_remaining`
    so a replay hands the policy one adapter answering both verbs rather than
    two objects it must keep together.  It stays optional and defaults to
    ``None`` because a deployment that stated no statistical ceiling is the
    ordinary case for a campaign tree fronted out of a store, and a factory
    that *demanded* an account would make every existing construction of a
    question a refusal — the call sites feature 217 already has.  A question
    built without one answers :data:`UNBOUNDED_BUDGET`.

    The two are separate arguments rather than one nested object — the
    deployment's allowance, which is a campaign fact, and the charges, which
    are read from the ledger — because the seam this factory serves is the
    *read side*, and a factory that resolved the charges itself would have to
    reach a store and would stop being a pure function of what it was handed.
    The account is built by :func:`budget_account` at the call site that owns
    the rows; this factory's job is to hand what it was given to the adapter,
    unchanged.
    """
    return PolicyQuestion(tree, budget)


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
