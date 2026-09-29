"""Feature 245 — the replay transition: a stored tree reveals only recorded children.

app_spec.xml, "Replay Engine", feature 245: *System rejects any attempt to
generate a new child during replay, because a stored tree reveals only
recorded children.*  It is the category's root — features 246, 247, 248 and
251 all declare ``depends_on=245`` — and it is docs/nullius-tech-architecture.md
§10.1's own line:

    def replay(policy, tree, book, epoch) -> ReplayResult:
        revealed = {tree.root}
        rounds = 0
        while rounds < K2:
            batch = policy.select(prefix_view(revealed))       # prefix-only
            if not batch:
                break
            for v in batch:
                child = tree.child_of(v)                       # DETERMINISTIC
                if child:
                    revealed.add(child)
            rounds += 1
        pick = policy.commit()                                  # MANDATORY
        return score(pick, book, epoch, revealed, rounds)

**This module is one iteration of that loop's inner ``for``** — the
transition, ``child = tree.child_of(v)`` and ``revealed.add(child)`` — and it
is a module of its own rather than three lines inside a driver because the
sentence those two lines carry is the whole cost argument of the system:

    Online transition is stochastic (the agent may generate a different child
    from the same workspace). Replay transition is deterministic: it reveals
    the child already recorded. That asymmetry is the source of the cost
    advantage.  (docs §10.1, line 482)

The online half is feature 239's ``CONTINUE(v)`` — resume a node's workspace,
ask the agent for one refined signal, persist it as a child (features 239, 240,
in the discovery member's loop).  It costs an agent call and an evaluation.  The
replay half is this module: the same node is reached by *reading the child that
expansion already wrote*.  It costs a lookup into the tree's recorded edges —
derived once per transition (:func:`child_map`) and then a dict read per step,
which is the sense in which a replay is cheap and the reason a step must not
re-derive the edge list (see :func:`child_map`: per-step derivation is
quadratic, and the sibling feature 252 budgets a *whole* replay at 50 ms).
Everything the Replay Engine category then forbids — 246's evaluator, 247's
sandbox, 251's Parquet reads — is a consequence of that one substitution being
kept honest, and feature 245 is the substitution itself.

**The refusal is the feature, and it sits on the one verb a generation could
enter through.**  A module that merely *documented* "we reveal the recorded
child" would guard nothing: the next driver could call an agent for one node and
nothing would stop it — which is exactly the failure the category's cost model
collapses under, since *"if replay can trigger evaluation, the cost model of the
entire system collapses"* (docs §1).  So :meth:`ReplayTransition.transition`
carries the seam: it accepts a ``generator`` argument — the callable shape of
the online act, a function that would mint the child from the parent's workspace
— and **refuses it**.  There is one verb and one seam, so there is exactly one
place a generation could enter a replay, and it refuses there rather than
somewhere a driver would have to remember to look.  The shape is feature 146's
(``canary.model_inference``): the seam is the call, the refusal fires before
anything is read or spent, and the message names the law and the repair.

**The child is read off the recorded edges — the same seam feature 218 reads.**
A node's recorded child is the node that names it as its parent; the tree's
``(node_id, parent_id, depth, payload)`` model is the one fact this pool shares
with the policy-runtime member's ``CampaignTree``, and it is the same derivation
feature 218's ``legal_actions`` performs for the *policy's* view of the same
document.  Both read the edges the tree already holds; neither invents one.
Feature 218 says so in as many words — *"it is deliberately not feature 239's
expansion: nothing here generates a child. A stored tree reveals only recorded
children (app_spec.xml:885), and this verb reads the edges the tree already
holds"* — and this module is that sentence read on the **runtime's** side: 218
is what a policy may *ask*, 245 is what the replay may *do*, and the two agree
because they read one set of edges.

So the tree is duck-typed and validated as it is read, never ``isinstance``-ed:
the module loader imports a member under a synthetic name and re-executes it, so
the tree ``create_app()`` hands out may be a *second* ``CampaignTree`` class
object, and an ``isinstance`` would refuse the very tree composition produces.
The seam validates what it *reads* — the tree's ``nodes``, a node's ``node_id``
and ``parent_id``, the tree's ``node`` — and translates each failure into this
member's own vocabulary, so a caller's single ``except ReplayError`` catches
every way a transition can fail rather than being handed an
:class:`AttributeError` the member never named.

**Exactly one recorded child, or none — and the cardinality is the online
loop's, not this module's choice.**  §10.1 writes ``child = tree.child_of(v)``
in the singular, and it is singular because the act that *writes* those edges
creates exactly one child: feature 239 — *"System expands a selected node by
resuming its workspace, which creates exactly one refined signal for
evaluation"*.  A stored campaign tree therefore records at most one child per
node, and the two honest answers are *the one recorded child* and *no child*
(a leaf, §10.1's ``if child:`` falling through).  A node recording **two or
more** children is a tree §10.1's line cannot walk — *"it reveals the child
already recorded"* names no node when two were recorded — and it is refused
naming the node rather than resolved by picking one.  A pick would be a
decision the replay has no rule for: whichever rule it used (first by id, last
written, most recently scored) would be an undeclared tie-break, and two
replays of one tree would be free to disagree about which child a prefix
contains — the one thing §12's determinism contract forbids.

**The prefix is seeded at the roots, and the transition is idempotent.**  §10.1
opens with ``revealed = {tree.root}``; on this pool that is the tree's
**parentless nodes**, plural, because a themed campaign has one root per planted
theme (prd §215, *"Root = a fresh research theme"*) rather than the single
canonical root a bootstrap lattice has — the same plurality feature 218's
``legal_roots`` answers for the policy.  Each transition adds the recorded child
(``revealed.add(child)``, §10.1's own line), so the walk is idempotent: the same
tree re-walked lands in the same prefix, which is what makes *"a replay of a
fixed policy on a fixed tree"* produce one answer (§12, cq-15).

**What this module deliberately does not do.**  It does not select — the batch
is the *policy's*, through ``prefix_view(revealed)`` (§10.2, feature 223) and
the answer surface (feature 224), and a transition that chose what to reveal
would be a runtime making the policy's decision.  It does not loop, cap the
rounds or test termination — that is feature 248, and the "no batch selected"
signal is the *emptiness of the policy's answer*, not anything this verb can
see.  It does not score, commit or persist — features 249, 250 and 255 — and it
does not read an artifact: the payload a node carries is read by whoever scores,
and a transition that opened a store would be reading at a moment §10.1 puts no
read at.  It walks the tree it is handed and answers where the prefix went.

Stdlib only — a dataclass and the typing that names it — so importing this
member on every factory scan (including the replay path §1 keeps away from
anything that could perturb it) costs composition nothing, and the transition
itself is one pass over a tuple of nodes at construction plus a dict read per
step.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from .errors import ChildGenerationRefused, ReplayTreeError
from .returns import ReplayReturns, resident_returns

if TYPE_CHECKING:  # pragma: no cover - typing only; the facade imports the
    # verb itself inside the method body, the same seam `run` takes, so this
    # module stays import-cheap and free of a hard dependency at composition.
    from .dependencies import ReplayPathDependencies
    from .pick import TerminalPick

__all__ = [
    "ReplayEngine",
    "ReplayTransition",
    "child_map",
    "recorded_child",
    "replay_roots",
]


def replay_roots(tree: Any) -> tuple[str, ...]:
    """The nodes a replay's prefix starts from — §10.1's ``{tree.root}``.

    docs/nullius-tech-architecture.md §10.1 opens its ``replay()`` with
    ``revealed = {tree.root}``, and on this pool that is the tree's
    **parentless nodes**: a themed campaign plants one root per theme
    (§11.1's ``plan.theme_roots``, prd §215 *"Root = a fresh research theme"*),
    so the set is a plurality rather than the one canonical root a bootstrap
    lattice has.  This is the same answer feature 218's ``legal_roots`` gives
    the *policy* — the nodes a walk may begin from — read here for the
    *runtime*, which must seed its prefix at exactly those nodes.

    Ascending by node id, §12's ordering rule restated for a search frontier,
    so two replays of one tree begin from the same nodes in the same sequence.
    A tuple rather than a list because the initial prefix is a *set's* initial
    content, not a sequence a caller should append to.

    Refuses with :class:`~replay.ReplayTreeError` a tree whose nodes cannot be
    read — see :func:`_edges` — naming what arrived rather than letting an
    :class:`AttributeError` escape, and a tree **with no parentless node**,
    which is a structure every one of whose nodes sits on a cycle: no walk over
    it could begin anywhere, and a prefix seeded empty would hand the replay a
    campaign it silently cannot walk.
    """
    edges = _edges(tree)
    roots = [node_id for node_id, parent_id in edges if parent_id is None]
    if not roots:
        raise ReplayTreeError(
            f"the stored tree holds no root: {tree!r} "
            f"({type(tree).__name__}) has {len(edges)} node(s) and "
            "every one of them names a parent, so no node is parentless. A "
            "replay's prefix begins at the tree's roots (§10.1's "
            "`revealed = {tree.root}`, read on a themed campaign as its "
            "parentless nodes) — a tree with none is one whose every walk "
            "begins nowhere, and seeding an empty prefix would hand the "
            "replay a campaign it silently cannot walk (feature 245)"
        )
    return tuple(sorted(roots))


def child_map(tree: Any) -> dict[str, str]:
    """Every recorded edge, indexed parent -> child — one pass over the tree.

    The derivation :func:`recorded_child` performs, done once and kept: a
    replay takes one transition per selected node, and a verb that re-derived
    the whole edge list per step would make a walk **quadratic in the campaign's
    nodes** (measured: 166 µs per step on a 500-node tree, 717 µs on a
    2 000-node one — a 500-node campaign's transition cost alone reaching 76 ms,
    against the 50 ms a whole replay is budgeted at by the sibling feature 252).
    This module's cost argument is that a replay *reads* what the online loop
    already wrote; a read that re-walks the tree per step is a different thing
    wearing its name.

    A node recording several children is refused here, naming the node and all
    of them — §10.1's ``child = tree.child_of(v)`` is singular, and feature 239
    writes exactly one child per expansion, so several is a tree no
    deterministic transition can walk.  Resolving it by picking one would be an
    undeclared tie-break two replays of one tree could disagree about.

    Every value is therefore a *single* node id, which is what lets
    :meth:`ReplayTransition.transition` answer the recorded child with a dict
    lookup rather than a scan.
    """
    collected: dict[str, list[str]] = {}
    for node_id, parent_id in _edges(tree):
        if parent_id is not None:
            collected.setdefault(parent_id, []).append(node_id)
    children: dict[str, str] = {}
    for parent_id, recorded in collected.items():
        if len(recorded) == 1:
            children[parent_id] = recorded[0]
            continue
        # Several children: refused naming the node and *every* child the tree
        # recorded for it, not merely the pair the walk happened to meet first —
        # an operator repairing the tree needs the whole frontier, and a message
        # naming two of three would send them looking for a third that is not
        # there.
        raise ReplayTreeError(
            f"the stored tree records {len(recorded)} children for node "
            f"{parent_id!r} ({', '.join(repr(child) for child in sorted(recorded))}): "
            "§10.1's replay transition is `child = tree.child_of(v)` — the "
            "singular child already recorded — and it is singular because the "
            "act that wrote these edges creates exactly one (feature 239: "
            "'creates exactly one refined signal for evaluation'). A node "
            "recording several children is one no deterministic transition can "
            "walk: whichever child the replay revealed would be an undeclared "
            "tie-break, and two replays of one tree would be free to disagree "
            "about which nodes their prefix contains (feature 245)"
        )
    return children


def recorded_child(tree: Any, selected: Any) -> str | None:
    """The child a stored tree recorded for ``selected`` — or ``None`` at a leaf.

    app_spec.xml feature 245's *"a stored tree reveals only recorded
    children"* as one call: the node the tree recorded as ``selected``'s
    child, or ``None`` when the tree recorded none.  docs §10.1 spells it
    ``child = tree.child_of(v)`` and reads the two answers as *the recorded
    child* and *no child* — the ``if child:`` that falls through at a leaf.

    The child is derived from the tree's own edges, exactly as feature 218's
    ``legal_actions`` derives a node's open frontier for the policy: a node's
    child is the node that names it as its parent, one recorded edge, no
    invention.  Nothing is generated here and nothing could be — this function
    has no seam a generator could arrive through, which is why the refusal
    feature 245 is made of lives on :meth:`ReplayTransition.transition`, where
    a caller *can* hand one in.

    **Exactly one, or none.**  A node recording two or more children is
    refused, naming the node: §10.1's line is singular because the act that
    writes these edges creates exactly one child — feature 239, *"creates
    exactly one refined signal"* — so a node with several is a tree no
    deterministic transition can walk, and resolving it by picking one would
    be an undeclared tie-break that two replays of one tree could disagree
    about.  A **selected node the tree does not hold** is refused by the tree
    itself through its ``node`` seam, and that refusal — whatever class the
    tree raises — is translated here into a :class:`~replay.ReplayTreeError`
    naming the node, because a caller catching this member's base class must
    catch a position the replay cannot stand at.

    ``selected`` must be a node id — a non-empty string.  Anything else names
    no position, and is refused in the same vocabulary: a value that is not an
    id cannot be looked up, and answering ``None`` for it would report a
    malformed call as a leaf.

    The one-shot spelling of :func:`child_map`, for a caller that wants a
    single answer and holds no transition.  A replay takes one transition per
    selected node, which is why :class:`ReplayTransition` builds the map once
    and looks up into it per step: this function re-derives the tree's edges on
    every call (O(N)), and a walk built out of *these* would be quadratic in the
    campaign's nodes — see :func:`child_map`.
    """
    position = _node_id_of(selected, what="the selected node")
    _addressed(tree, position)
    return child_map(tree).get(position)


@dataclass
class ReplayTransition:
    """One replay's deterministic transition over one stored tree — feature 245.

    The runtime's half of §10.1's asymmetry: constructed over the tree a replay
    walks, holding the prefix it has revealed so far, and advancing that prefix
    by **the child the tree recorded** and never by one it generates.

    The object is the *episode's*, not the deployment's: ``revealed`` is
    per-replay state (a second replay starts from the roots again), and it is
    deliberately mutable in place — §10.1's loop calls ``revealed.add(child)``
    once per selected node, and a transition that returned a fresh copy per
    step would make a two-hundred-round replay quadratic in the nodes it
    revealed.

    The tree is held, not copied, and its recorded edges are derived **once** at
    construction (:func:`child_map`) — both the seed (:func:`replay_roots`) and
    the parent -> child map are read there, so two transitions opened over one
    tree agree about it, and a replay of a fixed policy on a fixed tree is one
    answer rather than a family of them (§12, cq-15).  Deriving per step instead
    would re-walk the campaign on every selected node, which is the quadratic
    cost :func:`child_map` measures.

    The consequence is that a tree edited *after* a transition is opened does
    not move a walk already in flight: the edges are frozen with the seed.  That
    is the honest reading of a *stored* tree — a replay walks a campaign that
    the online loop finished writing, and one whose edges moved underneath it
    would be a second tree wearing the first's identity, against §12's
    determinism contract.  A caller that wants the moved tree opens a new
    transition over it.

    **What is and is not defended.**  ``children`` is exposed as a read-only
    mapping (:class:`types.MappingProxyType`), because it is *the tree's own
    recorded edges* and nothing needs to write into it — a mapping a caller
    could edit would be a second, unvalidated statement of the tree's edges
    sitting beside the tree, and the obvious way to mint a child by hand.  The
    mapping is not rebindable either, for the same reason.

    Beyond that this is **not** an object defended against a caller that holds
    it, and it is worth being exact rather than gesturing at safety:
    ``revealed`` is a plain mutable set *by design* (§10.1's loop calls
    ``revealed.add(child)`` once per selected node, and the per-step copy that
    would make it immutable is the quadratic cost this class avoids), so a
    caller that writes into it can put a node the tree never recorded into the
    prefix.  That is not a gap in feature 245, which is a law about the
    *replay path* — its refusal sits on the verb a generator would arrive
    through (:meth:`transition`), and its claim is that no replay *act* mints a
    child.  A caller that reaches into a transition's own state and edits the
    answer it is building is not taking a transition, it is corrupting one; the
    defence against that is that the object is per-episode and constructed from
    the tree, not that every field is frozen.  The property that matters is
    enforced where a driver actually arrives, and pinned in the tests.

    Not a component and not ``@register``-ed: it belongs to the round a replay
    opens, not to the composed application, the same stance the policy-runtime
    member takes for its prefix view (223), its answer surface (224) and its
    commit record (222).  The component this member registers is the *driver's*
    view of a replay's tree, in :mod:`replay`.
    """

    #: The stored tree the replay walks — duck-typed, validated as it is read.
    tree: Any
    #: The nodes revealed so far, seeded at the tree's roots.  Normalised to
    #: a :class:`set` of node ids at construction, and mutated in place by
    #: :meth:`transition` — §10.1's ``revealed.add(child)``.
    revealed: set[str]
    #: The tree's recorded edges indexed parent -> child, derived **once** at
    #: construction (:func:`child_map`) and reused by every step.  This is what
    #: makes a step a lookup rather than a re-walk: without it a replay would be
    #: quadratic in the campaign's nodes, which the 50 ms-per-replay budget of
    #: the sibling feature 252 does not admit.  Not a constructor argument —
    #: always derived, so a hand-built transition cannot carry a map that
    #: disagrees with its tree.
    #:
    #: **Read-only once derived**, and that is feature 245's law rather than
    #: tidiness: this map *is* "the children the stored tree recorded", so a
    #: caller able to write into it could put a node the tree never recorded
    #: into the prefix — generating a child by hand, which is precisely what
    #: this module exists to make impossible.  ``revealed`` stays mutable
    #: because §10.1's loop mutates it; nothing needs to write here after
    #: construction, so nothing may.  See :meth:`__setattr__`.
    children: Mapping[str, str] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        roots = replay_roots(self.tree)
        revealed = set(self.revealed) if self.revealed else set(roots)
        for node_id in revealed:
            _node_id_of(node_id, what="a revealed node")
        self.revealed = revealed
        # Derived before the prefix is validated: both read the same edges, and
        # building the map is also what refuses a node recording several
        # children — a tree no transition here could walk however the prefix
        # was seeded.  Derived through the ordinary attribute write (the freeze
        # in `__setattr__` allows the first binding and refuses a rebind), then
        # wrapped so the mapping itself cannot be written through.
        self.children = MappingProxyType(dict(child_map(self.tree)))
        # Every revealed node must be one the tree holds: a prefix carrying a
        # node outside the tree is a prefix the policy would be shown a
        # frontier for that the tree cannot answer — the same class of failure
        # feature 218 refuses as a dangling edge, here on the seed the caller
        # handed in.
        known = {node_id for node_id, _ in _edges(self.tree)}
        unknown = sorted(revealed - known)
        if unknown:
            raise ReplayTreeError(
                f"the replay prefix names node(s) the stored tree does not "
                f"hold: {', '.join(repr(node) for node in unknown)}. A prefix "
                "is the set of nodes a replay has revealed out of the tree it "
                "walks, so a node the tree does not hold is one the policy "
                "would be shown a reading for that no stored campaign can "
                "answer (feature 245)"
            )

    @classmethod
    def over(cls, tree: Any) -> ReplayTransition:
        """A transition over ``tree``, seeded at its roots — §10.1's opening.

        The ordinary construction, and the one a replay driver uses:
        ``revealed = {tree.root}`` becomes the tree's parentless nodes
        (:func:`replay_roots`), so a caller does not have to spell the seed
        itself and cannot spell it wrongly.  The direct constructor remains
        available for the caller that holds a prefix from somewhere else — a
        resumed replay, a report over a walk already taken — and validates it
        the same way.
        """
        return cls(tree=tree, revealed=set(replay_roots(tree)))

    # -- the transition ---------------------------------------------------

    def transition(
        self, selected: Any, *, generator: Any = None
    ) -> str | None:
        """Advance the prefix by ``selected``'s recorded child — feature 245.

        §10.1's inner loop, one step: ``child = tree.child_of(v)`` then
        ``revealed.add(child)``.  The answer is the node id that was newly
        revealed, or ``None`` when the tree recorded no child for ``selected``
        — a leaf, and §10.1's ``if child:`` falling through rather than an
        error, because *"a stored tree reveals only recorded children"* and a
        node with none reveals none.

        **The refusal, and it fires first.**  ``generator`` is the callable
        shape of the online act — a function that would mint the child from
        the selected node's workspace (feature 239's agent seam).  Handing one
        in is *the attempt to generate a new child during replay* that
        app_spec.xml feature 245 rejects, and it is rejected with
        :class:`~replay.ChildGenerationRefused` **before the tree is read and
        before the generator is called**.  The order is the feature: a child
        generated inside a replay would already be the drift the refusal
        exists to prevent — the prefix would carry a node no stored campaign
        contributed, and two replays of one tree would be free to differ — so
        a refusal that generated first and raised afterwards would have spent
        the thing it was refusing to spend.  It is the same ordering
        :func:`canary.model_inference` states for its own seam.

        The parameter rather than a missing one is the design point.  The
        replay path's driver never passes one, so the refusal's *shape* is
        what a caller meets: a runtime that wanted to generate would have to
        write ``generator=...`` at a call site whose keyword is the refusal's
        name, and there is no second verb, no ``generate`` spelling and no
        flag that turns the seam off — one verb, one seam, one place to look.

        Idempotent in the prefix: ``revealed.add`` is a set add, so
        transitioning over a node whose child is already revealed reveals
        nothing new and the answer is still the child's id.  A replay
        re-walked over one tree lands in the same prefix — §12's determinism,
        read on the walk itself.

        ``selected`` must be a node id the tree holds.  A value that is not a
        node id, or an id outside the tree, is refused in this member's
        vocabulary naming the node, because a position a replay cannot stand
        at names no transition — the same rule feature 218 states for the
        policy's frontier read, so the two halves of one document cannot
        disagree about which positions exist.
        """
        if generator is not None:
            raise ChildGenerationRefused(_generation_message(selected, generator))
        position = _node_id_of(selected, what="the selected node")
        _addressed(self.tree, position)
        child = self.children.get(position)
        if child is None:
            return None
        self.revealed.add(child)
        return child

    # -- the prefix -------------------------------------------------------

    def prefix(self) -> tuple[str, ...]:
        """The nodes revealed so far, ascending — the walk's state.

        The set §10.1's loop builds, reported in a stable order: §12's
        ordering rule (an explicit sort before every reduction) restated for a
        search frontier, so two replays of one tree hand the policy the same
        sequence however the reveals arrived.  A tuple, because this is a
        *reading* of the prefix rather than the prefix itself — the mutable
        set stays on the object, and the caller cannot edit the walk by
        holding its report.

        Deliberately a plain reading and not the policy's prefix view: feature
        223's :func:`policy_runtime.prefix_view` is the *object a policy is
        handed* (a fresh snapshot holding only the prefix, closed over
        everything else, cq-16), and it is built from a question's own
        ``observed()``.  This method answers the runtime's question — *which
        nodes has this walk revealed?* — and a second spelling of the policy's
        object here would be a second place the barrier would have to hold.
        """
        return tuple(sorted(self.revealed))

    def __len__(self) -> int:
        """How many nodes the walk has revealed — the prefix's size."""
        return len(self.revealed)

    def __contains__(self, node_id: object) -> bool:
        """Whether the walk has revealed ``node_id``."""
        return node_id in self.revealed

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Deliberately reads no tree: a repr is a debugging aid, and one that
        # re-walked the nodes would raise a *second* refusal while an operator
        # was already looking at the first, which is the worst moment for it.
        return f"ReplayTransition(revealed={len(self.revealed)})"


class ReplayEngine:
    """The composed replay component — a *stateless* facade that opens transitions.

    The value this member registers under :data:`replay.COMPONENT_NAME`, and
    the one object a composed application carries for the replay path.  It
    holds **nothing**: no tree, no store, no deployment state — ``__slots__``
    is empty — and its verbs open a :class:`ReplayTransition` over the tree
    it is handed and a :class:`~replay.ReplayReturns` over a resident pin
    arena (feature 251).  This is the shape :class:`canary.ModelInference`
    takes for the same reason on the same kind of seam: a component that is
    a *fact about the path* rather than a thing a deployment configures, so
    two callers can never observe each other through it and there is
    nothing to misset.

    **Why the component does not hold the deployment's tree.**  A store-bound
    builder that resolved the tree at build time would be reaching the
    composed application *from inside* composition: the tree lives in the
    policy-runtime member's component, whose own builder resolves it through
    the artifact store's seat, whose builder composes the application again.
    That call chain is a cycle — and it is one this member must not widen,
    because the factory builds every registered component on every
    ``create_app()``, so a builder that walked into it would make composition
    recurse rather than return.  The tree a replay walks is therefore resolved
    by the *caller* that needs one, at the moment it needs it, where a missing
    campaign is an answerable refusal rather than a recursion; :meth:`tree`
    is the one spelling of that resolution.

    The `replay` component is still a real contribution to the composed
    application — the member registers one component under the spec's plugin
    name, it appears in ``app.order``, and the app seat fronts it — and the
    statelessness is what makes it safe to compose in every deployment, which
    is the property the factory's "degrade, don't break" stance is protecting.
    """

    __slots__ = ()

    def transition(
        self, tree: Any, revealed: Iterable[str] | None = None
    ) -> ReplayTransition:
        """Open a replay's transition over ``tree`` — the member's entry point.

        The same construction as :func:`replay.replay_transition`, reached
        through the composed component so a caller holding the application
        needs no import of this member.  The tree is duck-typed and validated
        as it is read; a tree this member cannot walk is refused with
        :class:`~replay.ReplayTreeError` naming what arrived.
        """
        return replay_transition(tree, revealed)

    def tree(self) -> Any:
        """The campaign tree the deployment's artifact store holds.

        Resolved *at call time*, through the composed application's
        ``policy-runtime`` component (the one feature 217 ships) —
        never at composition, for the recursion reason this class's docstring
        states.  Refuses with :class:`~replay.ReplayTreeError` naming the
        absence when the deployment's store holds no committed campaign,
        because a caller that asked for a tree is a caller about to walk one
        and must not be handed ``None`` in place of a campaign.

        A separate verb rather than an argument default, so the two facts stay
        distinguishable at the call site: a deployment with **no campaign** is
        this refusal, while a caller that **has** a tree hands it to
        :meth:`transition` directly — the same distinction the policy-runtime
        seat draws between an absent component and an empty campaign.
        """
        return resolve_tree()

    def over(self) -> ReplayTransition:
        """Open a transition over the deployment's own stored campaign.

        The composed spelling of :func:`ReplayTransition.over`: resolve the
        deployment's tree, then open at its roots.  The two calls are one
        verb here because they are one act — *replay the campaign this
        process is pointed at* — and keeping them separate at the seam does
        not make a caller's life better than a single verb whose refusal names
        the missing campaign.
        """
        return self.transition(self.tree())

    def run(
        self,
        select: Any,
        question: Any,
        *,
        round_cap: int,
    ) -> tuple[str, ...]:
        """Loop policy selection until no batch or the round cap — feature 248.

        The composed spelling of :func:`replay.run_replay`: resolve the
        deployment's tree via :meth:`tree` (the call-time resolution this
        class's docstring argues — never at composition, for the recursion
        reason), then drive feature 245's transition until the policy returns
        no batch or ``round_cap`` rounds are reached, and hand back the
        revealed set.  The two calls are one verb here because they are one
        act — *replay the campaign this process is pointed at, round by round*
        — and a caller that has a tree of its own hands it to
        :func:`replay.run_replay` directly.

        ``select`` and ``question`` arrive duck-typed, exactly as the free
        function takes them: ``select`` is the caller's closure over the policy
        and the prefix view (``lambda q: policy.select(prefix_view(q))``), and
        ``question`` is the read-side question, read through its
        ``probe_batch``.  A non-callable ``select``, a non-positive
        ``round_cap`` (a ``bool``, a zero, a negative, a non-``int``) or a
        carrier with no callable ``probe_batch`` is refused as
        :class:`~replay.ReplayRoundError` before the tree is resolved; a
        deployment with no committed campaign is feature 245's
        :class:`~replay.ReplayTreeError` from :meth:`tree`, and a malformed
        tree surfaces the same way.

        Returns the revealed set ascending — :func:`replay.run_replay`'s
        return — and nothing else: no count, no score, no commit.
        """
        from .rounds import run_replay

        return run_replay(select, question, self.tree(), round_cap=round_cap)

    def pick(self, record: Any, scorer: Any) -> TerminalPick:
        """Require the committed pick at termination — feature 249.

        The composed spelling of :func:`replay.committed_pick`: §10.1's last
        two lines after :meth:`run` has returned its revealed set —
        ``pick = policy.commit()  # MANDATORY``, then the miss-arm of
        ``score(pick, book, epoch, revealed, rounds)``.  The record and the
        scorer arrive duck-typed, exactly as the free function takes them:
        ``record`` is feature 222's episode commit record (the door the
        policy's ``question.commit(node_id)`` went through, read through its
        one ``terminate()`` verb), and ``scorer`` is the replay's own
        arithmetic curried to the pick — the book, the epoch, the rounds and
        the revealed set :meth:`run` returns.

        A policy that emitted no pick is **scored**
        :data:`~replay.NON_COMMITTING_SCORE` here, never refused, with the
        scorer never called on the miss; the refusals are the ask (a
        non-callable scorer, a carrier that is not an episode's commit
        record, a termination read that cannot say), as
        :class:`~replay.ReplayPickError`, and the two argument checks fire
        before the record is touched so a refused ask terminates nothing.

        Returns the frozen :class:`~replay.TerminalPick` — the pick
        (absent-able) and the score (always present), the pair the
        ``replay_score`` row is shaped around — and resolves nothing: the
        requirement is pure over what it is handed, so unlike :meth:`run`
        there is no tree to resolve and no call-time resolution argument to
        make.
        """
        # Imported inside the function rather than at module top, the same
        # seam `run` takes: the facade's module stays import-cheap at
        # composition, and the verb is reached only by a caller taking the
        # terminal act.
        from .pick import committed_pick

        return committed_pick(record, scorer)

    def persist_replay_score(
        self,
        pick: Any,
        policy_version: Any,
        world_id: Any,
        beta: Any,
        *,
        is_holdout: bool = False,
        database_url: str | None = None,
    ) -> Any:
        """Persist one replay_score row per run — feature 255.

        The composed spelling of :func:`replay.persist_replay_score`: one row
        per ``(policy, world)`` replay, carrying the policy version under
        test, the world it was replayed against, the beta it was scored at,
        the resulting score, and the committed pick — written into the
        relational store ``DATABASE_URL`` names.  The ``pick`` is feature
        249's :class:`~replay.TerminalPick` (the pick absent-able, the score
        always present), read duck-typed exactly as the free function takes
        it, so a caller holding the composed component needs no import of this
        member.

        The ask is validated before the store is touched — the pick is a
        readable carrier, the score a real number or ``-inf`` (a NaN is
        refused), the policy version and world id non-empty strings, the beta
        a finite number — and a low or ``-inf`` score is persisted, never
        refused: the row is the record of a completed scoring.  A store that
        cannot take the write (unconfigured, an unsupported scheme, a locked
        or unwritable database) refuses as
        :class:`~replay.ReplayScoreError`, chained to the store's own
        refusal.
        """
        # Imported inside the function rather than at module top, the same
        # seam `run` and `pick` take: the facade's module stays import-cheap
        # at composition, and the verb is reached only by a caller taking the
        # persistence act.
        from .score import persist_replay_score

        return persist_replay_score(
            pick,
            policy_version,
            world_id,
            beta,
            is_holdout=is_holdout,
            database_url=database_url,
        )

    def returns(
        self,
        pins: Any,
        campaign_id: Any,
        *,
        horizon: int | None = None,
        load: Any = None,
    ) -> ReplayReturns:
        """Open a replay's resident read of one campaign axis — feature 251.

        The same act as :func:`replay.resident_returns`, reached through
        the composed component so a caller holding the application needs no
        import of this member: the campaign's ``(campaign_id, horizon)``
        axis is pinned through the resident pin arena (handed in duck-typed
        — the arena is per-replay state feature 175 deliberately never
        composed, so there is nothing here to resolve and the caller that
        built the arena hands it over, exactly as it hands a tree to
        :meth:`transition`), and the resident array the arena holds is the
        answer for the read's lifetime.

        A caller that hands the read a ``loader`` meets the same
        :class:`~replay.ParquetReadRefused` the free function raises — the
        component is a spelling of the member's verb, not a second
        implementation, so there is no route to a Parquet read by holding
        the component.
        """
        return resident_returns(
            pins, campaign_id, horizon=horizon, load=load
        )

    @property
    def dependencies(self) -> ReplayPathDependencies:
        """§1's dependency wall — features 246 and 247, as a value.

        The composed spelling of :mod:`replay.dependencies`: *"The replay
        engine has read access to the artifact store and zero access to the
        evaluator or sandbox."*  A caller holding the composed component
        refuses a forbidden reach through this value
        (:meth:`~replay.ReplayPathDependencies.evaluator`,
        :meth:`~replay.ReplayPathDependencies.sandbox`,
        :meth:`~replay.ReplayPathDependencies.reach`) without importing the
        member's submodules by name — the role
        :class:`canary.ModelInference` plays for feature 146's inference
        refusal, on the same kind of seam and for the same reason.

        A **property returning a fresh stateless facade** rather than a
        composed component of its own, and the choice is the member's
        one-component rule stated for this feature: the wall is a fact about
        where a call sits (§1, §12), not a thing a deployment configures, so
        there is nothing to misset, nothing to resolve and no second
        ``replay-``prefixed name the spec does not ask for — and returning a
        fresh value each time costs nothing
        (:class:`~replay.ReplayPathDependencies` has empty ``__slots__`` and
        holds nothing), while a cached one would be one more piece of state on
        a facade whose whole property is that it holds none.

        Imported inside the method rather than at module top, the same seam
        :meth:`run`, :meth:`pick` and :meth:`returns` take: the facade's module
        stays import-cheap at composition, and the wall is reached only by a
        caller about to span a replay path.
        """
        from .dependencies import ReplayPathDependencies

        return ReplayPathDependencies()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "ReplayEngine()"


def replay_transition(
    tree: Any, revealed: Iterable[str] | None = None
) -> ReplayTransition:
    """Open a replay's transition over ``tree`` — the module-level spelling.

    Feature 245's transition as one call, for a caller that wants the act
    without holding the composed component: a stored tree in, a
    :class:`~replay.ReplayTransition` out, seeded at the tree's roots
    (``revealed = {tree.root}``, §10.1's opening line, read on a themed
    campaign as the tree's parentless nodes) unless the caller holds a prefix
    already — a resumed replay, or a report over a walk taken elsewhere.

    Pure: no store, no clock, no environment — the transition reads the tree
    it is handed and nothing else.  A tree this member cannot walk is refused
    with :class:`~replay.ReplayTreeError` naming what arrived.
    """
    if revealed is None:
        return ReplayTransition.over(tree)
    return ReplayTransition(tree=tree, revealed=set(revealed))


def resolve_tree() -> Any:
    """The campaign tree the deployment's artifact store holds, or a refusal.

    Read by name from the composed application
    (``create_app().get("policy-runtime")``), and resolved
    **lazily at call time** — never from a component builder, because the
    read composes the application and a builder that called it would recurse
    inside ``create_app()`` (see :class:`ReplayEngine`).

    The loader is imported inside the function so this module stays
    import-cheap and free of a hard dependency at composition time.

    Refuses *by name* when there is no tree: a deployment whose store holds no
    committed campaign, or one where the policy-runtime member was not
    scanned.  This is the honest refusal for a caller that asked for the
    deployment's campaign — as against the composed component, which is
    stateless precisely so that composing an application with no campaign is
    not an error.
    """
    from app.module_loader import create_app

    # "policy-runtime" is the policy-runtime member's campaign-tree component.
    tree = create_app().get("policy-runtime")
    if tree is None:
        raise ReplayTreeError(
            "no campaign tree is composed: the deployment's artifact store "
            "holds no committed campaign (or the policy-runtime member was not "
            "scanned), so there is no stored tree to replay. A replay walks a "
            "tree the online discovery loop already wrote — a stored tree "
            "reveals only recorded children — and a deployment with no campaign "
            "has nothing for a replay to walk (feature 245)"
        )
    return tree


# -- the reads ------------------------------------------------------------


def _edges(tree: Any) -> tuple[tuple[str, str | None], ...]:
    """The tree's recorded edges — ``(node_id, parent_id)`` per node, validated.

    The one read every verb in this module derives from, so the root set, the
    child lookup and the prefix validation cannot disagree about what edges a
    tree records.  Each node is rendered as its id and its parent reference,
    with both validated as they are read — and the whole tuple is checked for
    edges that land nowhere, which is this module's never-silently-drop stance
    stated once:

    * a node whose ``parent_id`` names **no node in the tree** is a dangling
      reference.  It is not a root (its parent is not absent) and it is no
      position's child (no node names it), so every verb here would omit it in
      silence — and a frontier that quietly left a node out is precisely what
      feature 218 refuses one member over, because a caller cannot tell *this
      tree cannot be walked* from *that node has no child*.  Feature 217's
      constructor refuses a dangling reference at build time; this is the
      duck-typed seam's copy of that law, since a foreign or composed tree
      reaches these verbs without passing through 217's validation;
    * a node that names **its own id** as its parent is an edge reaching only
      itself.  Its parent is present, so the check above does not catch it, and
      it would make the node its own recorded child — a transition that
      "revealed" the node it started from, a step that does not advance.  A
      replay taking it would loop forever on one node while its prefix still
      read as growing.

    Both are refused naming the node.
    """
    raw = _read_nodes(tree)
    edges: list[tuple[str, str | None]] = []
    for node in raw:
        node_id = _node_id_of(getattr(node, "node_id", None), what="a campaign node")
        parent_id = getattr(node, "parent_id", None)
        if parent_id is not None and (
            not isinstance(parent_id, str) or not parent_id.strip()
        ):
            raise ReplayTreeError(
                f"campaign node {node_id!r} carries parent_id={parent_id!r} "
                f"({type(parent_id).__name__}): a parent reference is either "
                "absent (a root) or names a node, and a replay's child lookup "
                "is derived from exactly that distinction — a blank string is "
                "neither, so a node wearing one would sit at a root it does "
                "not sit at and would be handed to the walk as a place to "
                "begin (feature 245)"
            )
        edges.append((node_id, parent_id))
    known = {node_id for node_id, _ in edges}
    for node_id, parent_id in edges:
        if parent_id is None:
            continue
        if parent_id == node_id:
            raise ReplayTreeError(
                f"campaign node {node_id!r} names itself as its own parent: "
                "that is an edge reaching only itself, so the node's recorded "
                "child would be the node itself — a transition that reveals "
                "the position it started from, which advances nothing and "
                "would loop a replay forever while its prefix still read as "
                "growing. A stored discovery tree is a tree: every branch is "
                "planted at a root whose parent is absent, and a node sitting "
                "on a cycle has no origin to be reached from (feature 245)"
            )
        if parent_id not in known:
            raise ReplayTreeError(
                f"campaign node {node_id!r} names a parent {parent_id!r} that "
                "is not a node in the tree: it is therefore neither a root "
                "(its parent is not absent) nor any position's recorded child "
                "(no node names it), so a walk over this tree would omit it in "
                "silence — and a replay that quietly left a node out is one "
                "nothing could tell from a node whose expansion recorded no "
                "child (feature 245)"
            )
    return tuple(edges)


def _read_nodes(tree: Any) -> tuple[Any, ...]:
    """The tree's own ``nodes`` read into a tuple — the raw seam read.

    Refused here in this member's vocabulary when it cannot be read at all, so
    a tree that is not a tree names the read it failed rather than escaping as
    a bare :class:`AttributeError` or :class:`TypeError` a caller catching
    :class:`~replay.ReplayError` would miss.  The check is the same one feature
    218 performs on the policy's side of the same document, restated rather
    than imported: a member never imports another member.
    """
    try:
        sequence = tuple(tree.nodes)
    except Exception as exc:  # a tree whose nodes cannot be read is this law's
        raise ReplayTreeError(
            f"the stored tree's nodes could not be read: {tree!r} "
            f"({type(tree).__name__}) raised {exc!r} reading `nodes`. A replay "
            "transition is derived from the tree's own recorded edges — a "
            "node's recorded child is the node that names it as its parent — "
            "so a tree whose nodes cannot be walked names no transition a "
            "replay could take, and a stored tree reveals only recorded "
            "children rather than ones the replay could compute (feature 245)"
        ) from exc
    if isinstance(sequence, (str, bytes)) or not isinstance(sequence, Sequence):
        raise ReplayTreeError(
            f"a stored tree's nodes are a sequence of nodes — got {tree!r} "
            f"({type(tree).__name__}), whose `nodes` is {sequence!r} "
            f"({type(sequence).__name__}). A transition is derived by reading "
            "a node's id and its parent's id, and a value that carries neither "
            "names no recorded child (feature 245)"
        )
    return sequence


def _node_id_of(value: Any, *, what: str) -> str:
    """A node id, validated — or refused naming what carried it.

    A non-empty string and nothing else: the id is the address the tree's
    ``node`` seam is read through and the value the parent comparison is keyed
    on, so a value that cannot be an id is refused here rather than being
    looked up and silently answering nothing.
    """
    if not isinstance(value, str) or not value.strip():
        raise ReplayTreeError(
            f"{what} is a node id — got {value!r} ({type(value).__name__}), "
            "which names no cell in the stored tree. A replay's transition is "
            "read off the tree's recorded edges, and a value that is not an id "
            "names no position to read them from (feature 245)"
        )
    return value


def _addressed(tree: Any, node_id: str) -> Any:
    """The tree's own node for ``node_id`` — the address seam, validated.

    Reads ``tree.node(node_id)``, the one place a node id becomes a node, and
    refuses a tree with no such verb in this member's vocabulary rather than
    letting an :class:`AttributeError` escape.  A node id the tree does not
    hold is refused by the tree itself and translated here — whatever class the
    tree raised — into a :class:`~replay.ReplayTreeError` naming the node,
    because the tree's refusal belongs to the tree's member and a caller
    catching *this* member's base class must still catch a position the replay
    cannot stand at.  A replay that walked on past an unknown node would report
    a malformed call as a leaf.
    """
    address = getattr(tree, "node", None)
    if not callable(address):
        raise ReplayTreeError(
            f"a replay's transition is read off a stored tree — got {tree!r} "
            f"({type(tree).__name__}), which has no node(); a node's recorded "
            "child is the node that names it as its parent, and an object that "
            "cannot address a node names no position to read them from "
            "(feature 245)"
        )
    try:
        return address(node_id)
    except ReplayTreeError:
        raise
    except Exception as exc:
        raise ReplayTreeError(
            f"the stored tree could not address the node {node_id!r}: its "
            f"node() raised {exc!r}. A transition begins at a position the "
            "tree holds, so an address verb that fails names a node this walk "
            "cannot stand at — and a replay that treated it as a leaf would "
            "report a malformed call as a node whose expansion recorded "
            "nothing (feature 245)"
        ) from exc


def _generation_message(selected: Any, generator: Any) -> str:
    """The refusal for a handed-in generator — feature 245's one sentence.

    Spelled once, so the seam's refusal and any later reading of it agree.
    Names §10.1's asymmetry and the repair, because the caller who reached for
    a generator is the caller who has to move the act rather than retry it: the
    online loop (feature 239's ``CONTINUE(v)``, persisted by feature 240) is
    what writes a child, and a replay reads the child that loop already wrote.
    """
    name = getattr(generator, "__name__", None)
    if not isinstance(name, str) or not name.strip():
        name = type(generator).__name__
    return (
        f"a replay was asked to generate a new child for node {selected!r}: it "
        f"was handed a generator ({name}). A stored tree reveals only recorded "
        "children — docs §10.1's replay transition is `child = "
        "tree.child_of(v)`, the child already recorded, and `child = "
        "generate(v)`, the child computed from the workspace, is the *online* "
        "transition (feature 239's CONTINUE(v)); that asymmetry is the source "
        "of the replay's cost advantage, and a replay that generated a child "
        "would cost an agent call and an evaluation rather than a lookup "
        "(architecture §1, P5: replay must never invoke evaluation). Run the "
        "expansion online where the tree is written and replay the tree it "
        "recorded (feature 245)"
    )
