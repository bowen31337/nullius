"""Feature 218, the legal moves — where a walk may begin, and where it may go next.

app_spec.xml, "Exploration Policy Runtime", feature 218 (``depends_on=217``):
*System exposes legal_actions which returns open frontier nodes plus legal_roots
which returns available research themes.*  docs/nullius-tech-architecture.md
§593–594 spells the pair as the third and fourth lines of the identical
``question.*`` interface an exploration policy is handed during replay::

    question.legal_actions()   -> list[node_id]
    question.legal_roots()     -> list[node_id]

and docs/alpha-engine-prd.md §419–420 repeats both verbatim, with the one
comment that fixes the semantics — ``# roots + open frontiers``.

**The two verbs are one question asked at two moments.**  ``observed()`` (217)
answers *what have I seen?*; these answer *where may I move?* — and a policy
that cannot ask the second cannot take a step at all.  At round 0 the reveal
set is empty and ``observed()`` is an empty mapping: nothing in it names a
cell, and nothing in it says where to begin.  Feature 218 is the pair that
makes a walk a walk: :func:`legal_roots` names the nodes a walk may **begin**
from, :func:`legal_actions` names the nodes **one legal step on** from where
the policy stands, and the *emptiness* of the second is the signal prd §436
makes the termination test (*"must terminate when no batch is selected"*) —
which is why a position with no move answers ``[]`` rather than refusing.

**Roots, themes, and why the answer is a node id.**  The feature sentence's
second half says ``legal_roots()`` returns *"available research themes"*, and
docs/alpha-engine-prd.md §215 says what a root *is* in four words — *"Root = a
fresh research theme (§9)"*, restated as the table row *"Root | Research theme
(§9.3)"* (§699).  So the roots a walk may open *are* the available research
themes, and the node id is how a node is addressed: §11 spells the return as
``list[node_id]``, the sibling pool's ``legal_roots()`` returns the canonical
root's *id*, and the member's own canonical policy immediately hands the answer
to ``probe_batch([root])``, which accepts node ids and nothing else.  The two
readings are not in tension — the id is the spelling, the theme is the meaning
— and this module answers the id, with :func:`cell_meta`'s ``theme_root``
(feature 219) the accessor that names which theme a given root opens.  *Which*
themes are legal is feature 241's committed config and is not restated here;
discovery/themes.py:83 names this accessor as a *different act* from that
ceiling — *"feature 218's ``legal_roots()`` is the policy-facing runtime's
accessor — the themes a policy may open a walk in — and answering a policy is a
different act from refusing a planner."*

**A pure function of the tree — the reveal set is never consulted.**  The
answer is a list of node ids, and an id carries no reading: no score, no
``is_null`` (prd §4.2, cq-8), no absolute target, and no unrevealed node's
*value*.  What it carries is **structure** — that a node exists, and sits one
step on — the same class of fact feature 219 established is deliberately open
(*"structure is the tree's shape, not the reading §10.2's barrier withholds —
scores are"*), and the sibling pool's refusal is likewise a node *"outside the
lattice"* rather than an unrevealed one.  Two independent reasons it must not
depend on the reveal set:

* **the identical-interface law.**  ``BootstrapQuestion.legal_actions`` reads
  the world's lattice and never consults ``_revealed``.  A reveal-dependent
  campaign answer would break portability in the *walk* itself: a policy that
  re-read its frontier — stable on a bootstrap world — would see it collapse to
  ``[]`` on a campaign tree and terminate early, and feature 184's one-policy-
  both-pools claim would hold for every verb but the one that moves.  The
  interface's statefulness lives in ``observed()``, and a second stateful verb
  is how two pools stop being one interface;
* **purity.**  This member states it as a property of the question — *"every
  other answer is a pure function of ``(tree, node_id)``, computed afresh each
  call"* — and it is what makes a frontier reproducible across replays of one
  tree.

Neither verb grows the reveal set: reading where you may go is not going.

**What a "legal move" is, on this pool.**  The tree records
``(node_id, parent_id, depth, payload)``, so a node's legal moves are exactly
the nodes that name it as their parent — one recorded edge, no invention, and
the whole set of them is the batch a policy may select next.  That is the
sibling pool's law read on this pool's structure (``world.legal_moves``:
*"the neighbours of ``node_id`` — one legal step"*), and it is deliberately
*not* feature 239's expansion: nothing here generates a child.  A stored tree
reveals only recorded children (app_spec.xml:885), and this verb reads the
edges the tree already holds.

**The no-argument form, and where the pair diverges from the sibling pool.**
``legal_actions(None)`` answers the **roots** — *where a walk may begin* —
because prd §419's comment reads the no-arg call as ``roots + open frontiers``:
the roots when no position is named, the open frontier when one is.  So
``legal_actions(None) == legal_roots()``, and one spelling of "the nodes a walk
may begin from" serves both verbs.  This is the one place the pair deliberately
differs in *shape* from the bootstrap pool, and it is a fact about the campaign
pool rather than a drift: ``world.legal_moves(None)`` answers the root's
*neighbours*, because a bootstrap lattice has one canonical root that is not
itself a choice — the start is fixed, so the only moves "from the start" are
its neighbours.  A themed campaign has **several** roots, one per theme planted
(§11.1's ``plan.theme_roots``, prd §215), and *which theme to open* **is** the
policy's first action; the campaign's moves from the start are therefore the
roots themselves.  Every *positional* call — every call the member's canonical
policy and the sibling pool's own greedy walk actually make — answers the
identical kind of thing on both pools, so the divergence is confined to the
form whose meaning is a choice of starting point, and it is stated here rather
than glossed.

**Ascending everywhere**, so a policy that enumerates without sorting sees a
deterministic order and two replays of one tree explore identically — §12's
ordering rule (an explicit sort before every reduction), restated for a search
frontier, exactly as :meth:`PolicyQuestion.observed` and ``legal_moves`` state
it.

**A free function per verb, and a thin delegation from the question.**  This
module holds the derivations; :meth:`PolicyQuestion.legal_roots` and
:meth:`PolicyQuestion.legal_actions` are delegations to them, the split
:mod:`.meta` keeps for ``cell_meta`` and :mod:`.surface` for
``policy_surface``.  A report, a test, or a later feature in this category that
wants a frontier over a tree reads it through one derivation rather than
reconstructing the walk.  The functions carry §11's own vocabulary because
``discovery.planner`` and ``signal_agent._guidance`` already name
``legal_roots`` as *"feature 218's own vocabulary"*.

**Duck-typed, and every failure in this member's vocabulary.**  The module
loader imports the package under a synthetic name and re-executes it, so the
tree ``create_app()`` hands out may be a *second* ``CampaignTree`` class object
and an ``isinstance`` would refuse the very tree composition produces.  So the
seam validates what it *reads* — the tree's ``nodes``, a node's ``node_id`` and
``parent_id``, the tree's ``node`` — and translates each failure into
:class:`PolicyRuntimeError`'s own subclasses ([[error-vocabulary-at-member-
seams]]): a node the tree does not hold is :class:`PolicyAddressError`, raised
by the tree's own address seam and **passed through unchanged** so the sentence
naming the node and the tree survives; a value that is not a node id at all is
refused in :meth:`PolicyQuestion.meta`'s exact vocabulary; a malformed tree is
:class:`PolicyTreeError`.  No new error class: 218 refuses nothing feature 217's
vocabulary cannot already name.

**A broken edge is refused, not quietly absorbed** — in either of the two ways
an edge can fail to be one.  A node naming a parent the tree does not hold is
neither a root (its parent is not absent) nor any position's legal move (no node
names *it*), so both verbs would omit it **in silence**.  A node naming *its
own* id is worse rather than gentler: its parent is present, so it is not a
root, and it appears in exactly one frontier — its own — so
:func:`legal_actions` would answer ``legal_actions("a") == ["a"]``, handing a
policy a legal step from a position to the same position.  That step advances
nothing, and a walk taking it would loop forever on one node while its frontier
still read as non-empty.  Both are refused, naming the node: an omission
nothing is said about is precisely what this module refuses, because a policy
handed such a tree has no way to tell *I cannot walk this* from *there is no
move there*.  Feature 217's constructor refuses a dangling reference when it
builds a tree, so this is the same law restated for the **duck-typed** seam: a
foreign or composed tree reaches these verbs without passing 217's validation,
and the module validates what it reads rather than trusting a carrier it cannot
``isinstance``.  The cycle half is deliberately the law feature 219's walk
enforces, so the two accessors of one member cannot disagree about whether such
a tree is readable.

Pure: nothing here consults a store, a clock, an environment variable or a
reveal set, so it is import-cheap and two trees holding the same nodes answer
the same frontier.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .errors import PolicyAddressError, PolicyTreeError

__all__ = [
    "legal_actions",
    "legal_roots",
]


def legal_roots(tree: Any) -> list[str]:
    """The nodes a walk may begin from — §11's ``legal_roots()``, feature 218.

    docs/nullius-tech-architecture.md §594's line in the identical
    ``question.*`` interface — ``question.legal_roots() -> list[node_id]`` —
    which prd §420 repeats verbatim.  The nodes a policy may start a walk from:
    the tree's **parentless nodes**, the same test :mod:`discovery.manifest`
    uses for a branch (*"A branch is a root (``parent_id IS NULL``)"*), and in a
    themed campaign each one is a research theme's opening node (prd §215:
    *"Root = a fresh research theme"*).

    **Ascending by node id**, so a policy that enumerates without sorting sees a
    deterministic order and two replays of one tree begin from the same place in
    the same sequence — §12's ordering rule, restated for a search frontier.

    The set is derived from ``parent_id`` and **not** from
    :func:`~policy_runtime.cell_meta`'s ``theme_root``, deliberately: two
    parentless nodes in one theme are two roots a policy may start from, and
    collapsing them to one-node-per-theme would answer a question about the
    *theme set* through an accessor whose subject is *nodes*, silently dropping
    a legal starting point.  Which themes are *legal* is feature 241's committed
    config; which node opens a given theme is read where docs §634 confines it —
    ``meta(root).theme_root``.

    A pure function of the tree: the reveal set is not consulted, so an
    unrevealed root is still a root a policy may open, exactly as the sibling
    pool answers a node the world holds but the policy has not revealed.  This
    verb reads; it never grows the reveal set.

    Refuses with :class:`PolicyTreeError` a tree whose ``nodes`` cannot be read
    or whose nodes carry no usable ``node_id`` — a tree no walk could be planned
    over — naming what arrived rather than letting an :class:`AttributeError`
    escape.
    """
    roots: list[str] = []
    for node in _nodes(tree):
        if _parent_id_of(node) is None:
            roots.append(_node_id_of(node))
    return sorted(roots)


def legal_actions(tree: Any, node_id: Any = None) -> list[str]:
    """The nodes one legal step on from ``node_id`` — §11's ``legal_actions()``.

    docs/nullius-tech-architecture.md §593's line in the identical
    ``question.*`` interface — ``question.legal_actions() -> list[node_id]`` —
    which prd §419 repeats with the comment that fixes its reading::

        question.legal_actions()   -> list[node_id]                # roots + open frontiers

    Two answers, one verb, discriminated by whether a position was named:

    * **``node_id`` given** — the node's **open frontier**: the nodes that name
      it as their parent, one recorded edge each.  This is the batch a policy
      standing at ``node_id`` may select next.
    * **``node_id`` is ``None``** — the **roots**, *where a walk may begin*,
      which is prd §419's ``roots +`` half.  The answer is :func:`legal_roots`
      over the same tree, so the two verbs cannot drift on where a walk starts.

    **A position with no recorded child answers ``[]``** — and that is the
    load-bearing answer rather than a gap.  prd §436's *"must terminate when no
    batch is selected"* and feature 3/242's *"the policy has selected no
    batch"* are exactly this empty list: a leaf is a position with no move, and
    a verb that refused there would leave a policy unable to tell *nowhere left
    to go* from *you asked wrongly*.  Terminating is a decision, and this verb
    hands the policy the fact it decides on.

    **Ascending by node id**, so an enumerating policy sees a deterministic
    order (§12's ordering rule).

    **A pure function of the tree.**  The reveal set is not consulted, which is
    the identical-interface law rather than an omission:
    ``BootstrapQuestion.legal_actions`` reads the world's lattice and never its
    ``_revealed``, so a campaign answer that grew as cells were probed would
    break portability in the walk — a policy that re-read its frontier, stable
    on a bootstrap world, would see it collapse on a campaign tree and stop
    early.  An unrevealed node the tree holds is a legal move; a node the tree
    does not hold never is.

    Refuses with :class:`PolicyAddressError` a ``node_id`` that is not a node id
    (a number, an empty or whitespace string) or one the tree does not hold —
    the address seam :meth:`PolicyQuestion.meta` and :meth:`PolicyQuestion.reveal`
    route through, so a position a policy asks its moves from is one it was
    shown.
    """
    if node_id is None:
        return legal_roots(tree)
    node = _addressed_node(tree, node_id)
    position = _node_id_of(node)
    moves = [
        _node_id_of(candidate)
        for candidate in _nodes(tree)
        if _parent_id_of(candidate) == position
    ]
    return sorted(moves)


def _nodes(tree: Any) -> tuple[Any, ...]:
    """The tree's nodes, as a tuple — the one read both verbs walk.

    Read once per call from the tree's own ``nodes``, and refused here in this
    module's vocabulary when it cannot be read at all, so a tree that is not a
    tree names the frontier read it failed rather than escaping as a bare
    :class:`AttributeError` or :class:`TypeError` a caller catching
    :class:`PolicyRuntimeError` would miss.

    The nodes are also checked for **edges that reach nowhere**, and that check
    is the same law :func:`meta._walk_to_origin` enforces one accessor over.  A
    node naming a parent the tree does not hold is neither a root (its parent is
    not absent) nor any position's legal move (no node names *it*), so both
    verbs would silently omit it — and an omission with nothing said about it is
    exactly what this module's never-silently-drop stance refuses: a frontier
    that quietly left a node out is one a policy could not walk, and the policy
    would have no way to tell a tree it cannot walk from a tree that simply has
    no move there.  Feature 217's own constructor refuses a dangling edge at
    build time, so this is the *duck-typed* seam's copy of that law for a tree
    this member did not build — a foreign or composed tree reaches the frontier
    verbs without passing through 217's validation, and the accessor validates
    what it reads rather than trusting a carrier it cannot ``isinstance``.
    """
    return _edges_land_somewhere(tree, _read_nodes(tree))


def _read_nodes(tree: Any) -> tuple[Any, ...]:
    """The tree's own ``nodes`` read into a tuple — the raw seam read."""
    try:
        sequence = tuple(tree.nodes)
    except Exception as exc:  # a tree whose nodes cannot be read is this law's
        raise PolicyTreeError(
            f"a campaign tree's nodes could not be read: {tree!r} "
            f"({type(tree).__name__}) raised {exc!r} reading `nodes`. A "
            "frontier is derived from the tree's own edges — a node's legal "
            "moves are the nodes that name it as their parent — so a tree whose "
            "nodes cannot be walked names no frontier a policy could select a "
            "batch from (feature 218)"
        ) from exc
    if isinstance(sequence, (str, bytes)) or not isinstance(sequence, Sequence):
        raise PolicyTreeError(
            f"a campaign tree's nodes are a sequence of nodes — got {tree!r} "
            f"({type(tree).__name__}), whose `nodes` is "
            f"{sequence!r} ({type(sequence).__name__}). A frontier is derived "
            "by reading a node's id and its parent's id, and a value that "
            "carries neither names no move (feature 218)"
        )
    return sequence


def _edges_land_somewhere(tree: Any, nodes: tuple[Any, ...]) -> tuple[Any, ...]:
    """The same nodes, once every parent reference is proved to be a real edge.

    Two ways an edge can fail to be one, and both are refused here rather than
    quietly absorbed — because a frontier is a policy's whole legal vocabulary,
    and a vocabulary that is *wrong* is worse than one that refuses to be read:

    * **an edge that reaches nowhere** — a node whose ``parent_id`` names no
      node in the tree.  It is not a root, so :func:`legal_roots` would not name
      it as a place to begin; and it is no position's child, so
      :func:`legal_actions` would never name it as a move.  Both verbs would
      drop it **in silence**, leaving a policy unable to tell *I cannot walk
      this tree* from *there is no move there*;
    * **an edge that reaches only itself** — a node that names *its own* id as
      its parent.  That parent *is* in the tree, so the check above does not
      catch it, and it is worse than the dangling case rather than gentler: the
      node is not a root (its parent is not absent), and it appears in exactly
      one frontier — **its own**.  :func:`legal_actions` would answer
      ``legal_actions("a") == ["a"]``, offering a policy a legal move from a
      position to itself, which is a step that does not advance.  A walk that
      took it would loop forever on one node, and the loop would look like
      progress to a policy counting its frontier as non-empty.

    Both are refused naming the node — and for the self-edge, the cycle is
    refused as the same law feature 219's walk enforces (*"its parent chain
    revisits 'a', so the cell sits on a cycle with no origin"*), in this
    member's vocabulary, so the two accessors cannot disagree about whether such
    a tree is readable.
    """
    known = {_node_id_of(node) for node in nodes}
    for node in nodes:
        node_id = _node_id_of(node)
        parent_id = _parent_id_of(node)
        if parent_id is None:
            continue
        if parent_id == node_id:
            raise PolicyTreeError(
                f"campaign node {node_id!r} names itself as its own parent: that "
                "is an edge reaching only itself, so the node is not a root and "
                "its one legal move would be itself — a frontier offering a "
                "policy a step from a position to the same position, which "
                "advances nothing and would loop a walk forever while its "
                "frontier still read as non-empty. A campaign tree is a tree: "
                "every branch is planted at a root whose parent is absent, and a "
                "node sitting on a cycle has no origin to be reached from "
                "(feature 218)"
            )
        if parent_id not in known:
            raise PolicyTreeError(
                f"campaign node {node_id!r} names a parent "
                f"{parent_id!r} that is not a node in the tree: it is therefore "
                "neither a root (its parent is not absent) nor any position's "
                "legal move (no node names it), so a frontier over this tree "
                "would omit it in silence. A tree with a dangling edge is not a "
                "surface the policy could walk — and a frontier that quietly "
                "left a node out is one a policy could not tell from a tree "
                "that simply has no move there (feature 218)"
            )
    return nodes


def _node_id_of(node: Any) -> str:
    """A node's own id — read by name, validated, or refused naming the node.

    The id is what both verbs return and what the parent comparison is keyed
    on, so a node that cannot be named is refused here rather than silently
    dropped from a frontier: a frontier that quietly omitted a node would be a
    frontier a policy could not walk, and the omission would be invisible.
    """
    node_id = getattr(node, "node_id", None)
    if not isinstance(node_id, str) or not node_id.strip():
        raise PolicyTreeError(
            f"a campaign tree holds {node!r} ({type(node).__name__}), which "
            "carries no node_id: a frontier is a list of node ids — the ids a "
            "policy selects a batch from and reveals — and a node that cannot "
            "be named is a move a policy could not take (feature 218)"
        )
    return node_id


def _parent_id_of(node: Any) -> str | None:
    """A node's parent reference — ``None`` at a root, or refused if malformed.

    Three outcomes, and the distinctions matter to both verbs: absent (a
    :class:`~policy_runtime.CampaignNode` at a root) makes the node a **root**
    and gives it no parent to be a move of; a non-empty string makes it a move
    of exactly that node and keeps it out of :func:`legal_roots`; anything else
    — a blank string, a number, a nested object — is a **corrupt edge** rather
    than a silent absence, and is refused naming the node, because a frontier
    built over an edge that cannot be read is a frontier that would place the
    node at a root it does not sit at (the member's never-coerce stance,
    :func:`meta._theme_root_of`).
    """
    parent_id = getattr(node, "parent_id", None)
    if parent_id is None:
        return None
    if isinstance(parent_id, str) and parent_id.strip():
        return parent_id
    raise PolicyTreeError(
        f"campaign node {_node_id_of(node)!r} carries "
        f"parent_id={parent_id!r} ({type(parent_id).__name__}): a parent "
        "reference is either absent (a root) or names a node, and a frontier is "
        "derived from exactly that distinction — a blank string is neither, so "
        "a node wearing one would sit at a root it does not sit at and would be "
        "handed to a policy as a place to begin (feature 218)"
    )


def _addressed_node(tree: Any, node_id: Any) -> Any:
    """The tree's own node for ``node_id`` — the address seam, validated.

    Reads ``tree.node(node_id)``, the one place a node id becomes a node, and
    refuses a tree that has no such verb in this module's vocabulary rather
    than letting an :class:`AttributeError` escape.  A node id the tree does
    not hold is refused by the tree itself, with :class:`PolicyAddressError` —
    the refusal feature 217's tree already owns, propagated unchanged so the
    specific sentence naming the node and the tree survives rather than being
    re-spelled here.

    A value that is not a node id *at all* is refused before the walk reaches
    the tree, in the same vocabulary :meth:`PolicyQuestion.meta` uses: an
    unhashable or exotic value reaching a tree's comparison is a caller mistake
    this member states rather than lets escape, and a value that is not an id
    names no position to ask the moves of.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise PolicyAddressError(
            f"legal moves are read for a node id — got {node_id!r} "
            f"({type(node_id).__name__}), which names no cell: the nodes one "
            "legal step on from a position are the nodes that name it as their "
            "parent, and a value that is not an id names no position to ask "
            "the moves of (feature 218)"
        )
    address = getattr(tree, "node", None)
    if not callable(address):
        raise PolicyTreeError(
            f"a frontier is read off a campaign tree — got {tree!r} "
            f"({type(tree).__name__}), which has no node(); a node's legal "
            "moves are the nodes that name it as their parent, and an object "
            "that cannot address a node names no position to ask them of "
            "(feature 218)"
        )
    try:
        return address(node_id)
    except PolicyAddressError:
        # The tree's own refusal, passed through: it already names the node and
        # the tree, and a second spelling here would be a second sentence for
        # one law — the rule every seam in this member keeps.
        raise
    except Exception as exc:  # a non-tree address verb is this law's to refuse
        raise PolicyTreeError(
            f"the campaign tree could not address the node {node_id!r}: its "
            f"node() raised {exc!r}. A position's legal moves are read from the "
            "tree that holds it, so an address verb that fails is a tree this "
            "accessor cannot read rather than a position without moves "
            "(feature 218)"
        ) from exc
