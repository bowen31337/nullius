"""Feature 219, cell meta — the structural metadata a cell carries.

app_spec.xml, "Exploration Policy Runtime", feature 219: *System exposes a meta
accessor which returns structural cell metadata including branch, depth, parent
and theme_root.*  docs/nullius-tech-architecture.md §595 spells the accessor as
the fourth line of the identical ``question.*`` interface an exploration policy
is handed during replay, and names all four fields in its own comment::

    question.meta(node_id)     -> CellMeta          # structural: branch, depth, parent, theme_root

The reason the accessor exists at all is stated by §11.1, and it is not
curiosity about the tree's shape: ``theme_root`` *"is exposed in ``meta()``
because the overfit signature is only partly family-invariant"*.  Contribution
concentration inverts across families, and so does rolling-IC non-stationarity,
so a single global threshold averages the inverted features into uselessness —
"the policy writes family-conditional thresholds routed through the same
``_schedule(beta)`` dict".  docs/alpha-engine-prd.md §195 draws the consequence
from the other end of the same fact — *"``theme_root`` is already in ``meta()``,
so expose it to the policy and let the policy-development agent write
family-conditional thresholds"* — and §634 makes the accessor the **only** road
to that slug: *"``theme_root`` used only via ``meta()``"* is one of the static
checks a policy must pass before it is admitted (feature 230's gate).  So this
module is not a convenience accessor beside feature 228's conditioning; it is
the one seam the conditioning is allowed to read.

**The four fields, and where each one comes from.**  A cell's structure is a
fact about where it sits in the campaign tree, so every field is *read off the
tree* rather than stored beside it — which is what makes a meta and the tree it
describes unable to drift:

* **``parent``** — the id of the node one step toward the branch's origin
  (:attr:`CampaignNode.parent_id`), or ``None`` at a root.  Read from the tree's
  node, which validated the reference when the tree was built, so a parent
  named here is always a node the tree holds.
* **``depth``** — how many steps that walk takes, zero at the origin.  It is
  **derived from the tree's edges rather than read from the node's ``depth``
  field**, and the reason is not stylistic: feature 217's composed tree is
  rebuilt from the artifact store, where a node's payload may carry no ``depth``
  key at all and the reader defaults it to ``0`` (``_resolve_tree``) — so a
  node's declared depth is a fact some writers state and others do not, while
  the edges are the tree.  Deriving it is also the stance the sibling pool
  takes: feature 184's :class:`bootstrap.CellMeta` reports ``Σ|step|`` from the
  root and describes it as *"the world's own structural depth"*, computed rather
  than recorded, so a policy reading this number on a campaign cell and on a
  bootstrap cell reads the same kind of number computed the same way.
* **``branch``** — the id of the **origin** of the branch the cell sits in: the
  node at the top of the same parent walk, the one whose own ``parent_id`` is
  ``None``.  ``None`` when the cell *is* that origin.  This is the campaign's own
  notion of a branch, stated by :mod:`discovery.manifest` — *"A branch is a root
  (``parent_id`` ``IS NULL``), a refine is a non-root"* — and it is the grouping
  feature 236's difficulty census is taken over (§434's per-branch success rate
  is *"computable entirely from prefix information"*, and a policy groups its
  revealed refinements by exactly this).  ``None`` at the origin rather than the
  origin's own id is deliberate and it is the identical-interface law: the
  sibling pool answers ``None`` for a root — *"no parent and therefore no step
  that reached it"* — so ``meta.branch is None`` means *this cell is a branch
  origin* in both pools, and a policy written against one runs unmodified
  against the other (feature 184, feature 190, docs §10.6).
* **``theme_root``** — the research theme the cell's branch was planted in: the
  slug §11.1 conditions on and §634 confines to this accessor.  Read by name
  from the cell's own payload, which is §9.1's ``theme_root TEXT NOT NULL``
  column as the node froze it (``discovery.expansion`` inherits it unchanged
  through a refinement: *"refinement never changes families"*).

**Absent is not the same as malformed, and the two answer differently.**  A
payload that carries no ``theme_root`` answers ``None`` — the honest null this
member already states for a structural node: :meth:`PolicyObservation.from_node`
reads the in-sample metrics *"by name, defaulting to ``None`` when the payload
carries no such metric — a node that carries no in-sample reading is a
structural node, not a scored leaf, and its observation says so rather than
inventing a number"*.  The same discipline one field over: a cell whose record
states no family reports no family, and the accessor never invents one.  A
payload that *does* carry the key but holds something that is not a name — a
blank string, a number, a nested object — is a different fact and is refused
naming the node and the value, because that is a corrupt structural record
rather than a silent absence, and the member's never-coerce stance
(:func:`families._theme_key`, :class:`bootstrap.CellMeta`'s own key check)
refuses a theme that cannot be named rather than reporting it as a family.

**Derived, never recorded, and therefore never drifting.**  ``depth`` and
``branch`` are computed from the parent chain; ``parent`` is the tree's own
validated edge; ``theme_root`` is the payload's own field.  Nothing here is
cached, stored on the question, or remembered from a previous read, so
:func:`cell_meta` is a pure function of ``(tree, node_id)``: two questions over
one tree answer the same four fields to the last value, and a policy that reads
one cell's meta twice holds two equal frozen values rather than one that moved.
That is the property §10.6's *"a policy is portable without modification"*
needs, and the reason :class:`CellMeta` is a frozen value: a node's structure is
a fact about where it sits and not something a reveal changes, so a policy
comparing two cells must not be able to move either one's structure.

**The barrier, and what is deliberately not read here.**  §10.2's prefix-only
law withholds the *scores* of unrevealed cells — the observation's subject —
and cq-8 withholds ``is_null`` altogether, readable by exactly one component,
the replay scorer.  None of the four fields is any of those: they are the
tree's *shape*, and the shape is the thing §11.1 requires exposed so that
family-conditional thresholds can be authored at all.  So
:meth:`PolicyQuestion.meta` refuses a node the tree does not hold (the tree's own
address seam, :class:`PolicyAddressError` — the same refusal :meth:`reveal` and
:meth:`probe_batch` route through) and answers structure for any node it does
hold, exactly as feature 184's accessor *"refus[es] a node outside the lattice"*
and no more — the identical-interface law read from the barrier's side.  What
is *not* carried is equally deliberate and is checked rather than asserted: a
payload full of in-sample metrics and ``is_null`` yields exactly four fields,
because the accessor reads four keys and nothing else, so a structural read is
never a back door to a reading the barrier withholds.

**No new error class, and no component.**  Every refusal here is the tree's: a
node outside the tree is :class:`PolicyAddressError` (the address seam's), a
parent chain that does not reach an origin or that revisits a node is
:class:`PolicyTreeError` (a malformed tree, refused naming the cell), and a
present-but-unnamable ``theme_root`` is :class:`PolicyTreeError` too (a corrupt
structural record).  All three are the member's one base class, so a caller
catching :class:`PolicyRuntimeError` catches every way a structural read can
fail — the split-by-repair discipline feature 236 states for its own refusals
rather than a second vocabulary for one sentence.  There is no ``@register``
either: a component is *state a deployment holds*, while this accessor closes
over no deployment state at all — no store, no file, no clock, no environment —
so the member's registered surface stays feature 217's single campaign tree.

Stdlib only, and import-cheap: :mod:`dataclasses`, :mod:`collections.abc` and
the member's own errors, so the factory's scan — which imports this package to
fire its ``@register`` — pays nothing for a module it never composes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import PolicyAddressError, PolicyTreeError

__all__ = [
    "THEME_ROOT_KEY",
    "CellMeta",
    "cell_meta",
]

#: The payload key a cell's family is read from — §9.1's ``theme_root`` column
#: and docs §595's fourth field, spelled once so the accessor and the schema
#: cannot drift apart on what the structural family field is called.  Spelled
#: here rather than imported: a workspace member never imports another member,
#: and the discovery member spells its own column constant for its own reason.
THEME_ROOT_KEY = "theme_root"


@dataclass(frozen=True)
class CellMeta:
    """A cell's structural metadata — docs §595's ``CellMeta``.

    Frozen, because a node's structure is a fact about where it sits in the
    tree and not something a reveal changes: two callers holding the meta of one
    cell must not be able to move each other's, and a policy reading ``meta()``
    twice gets the same structure.  Its four fields are the ones the
    architecture names — ``branch``, ``depth``, ``parent``, ``theme_root`` — in
    the order §595 names them, and each is *derived from the tree or read from
    the node's own record* rather than stored beside either, so a meta and the
    cell it describes cannot drift:

    * **``branch``** — the id of the origin of the branch this cell sits in (the
      node at the top of its parent walk, the one with no parent of its own), or
      ``None`` when the cell *is* that origin.  The grouping feature 236's
      per-branch difficulty census is taken over, and ``None`` at the origin
      matches the sibling pool's root answer, so one policy reads both pools.
    * **``depth``** — the number of parent steps to that origin, zero at the
      origin.  Extracted from the tree's edges rather than from the node's
      ``depth`` field, because a composed tree rebuilt from the artifact store
      may hold nodes whose payload states no depth at all — see the module
      docstring — and the edges are always the tree.
    * **``parent``** — the id of the node one step toward the origin, or
      ``None`` at the origin.  Read from the tree's own node, whose parent
      reference the tree validated when it was built.
    * **``theme_root``** — the research theme this cell's branch was planted in,
      read from the cell's own payload, or ``None`` when the payload states no
      family.  This is the slug docs §11.1's family-conditional thresholds are
      keyed on and docs §634 confines to this accessor, so a policy that reads
      it anywhere else fails feature 230's admission gate.

    The value is validated at construction, the stance every value type in this
    member takes (:class:`CampaignNode`, :class:`GridPlan`,
    :class:`FamilyConditional`): ``depth`` is a genuine non-negative integer — a
    ``bool`` is not a level — and the three text fields are each ``None`` or a
    non-empty string, because a branch, a parent and a family that cannot be
    named are not structural facts about a cell but holes where one should be.
    A refusal here is :class:`PolicyTreeError`, the member's structural
    vocabulary, and it names the field and the value rather than the line.
    """

    branch: str | None
    depth: int
    parent: str | None
    theme_root: str | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.depth, bool)
            or not isinstance(self.depth, int)
            or self.depth < 0
        ):
            raise PolicyTreeError(
                f"a cell's depth must be a non-negative integer, got "
                f"{self.depth!r} ({type(self.depth).__name__}): depth is how many "
                "parent steps separate a cell from the origin of its branch, zero "
                "at that origin, and a negative one is a level no walk could reach "
                "(feature 219, docs §595)"
            )
        for field_name, value in (
            ("branch", self.branch),
            ("parent", self.parent),
            ("theme_root", self.theme_root),
        ):
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise PolicyTreeError(
                    f"a cell's {field_name} must be None or a non-empty name, got "
                    f"{value!r} ({type(value).__name__}): the four fields of "
                    f"docs §595's CellMeta are structural facts about where a cell "
                    f"sits — a branch origin, a parent, a research theme — and a "
                    f"{field_name} that cannot be named is a hole where one should "
                    f"be rather than a fact (feature 219)"
                )

    def row(self) -> dict[str, Any]:
        """The meta as a store-shaped mapping — a fresh dict per call.

        The four structural fields a replay or a report writes down, spelled
        with the same key names the architecture uses (docs §595), so a row
        reads back as the meta it came from.  ``branch`` and ``parent`` and
        ``theme_root`` are ``None`` at a root, at a branch origin and for a cell
        whose record states no family respectively — the honest null rather than
        an empty string, which would be a name that names nothing.

        A fresh dict per call, never a shared one: a caller that scribbles on
        what it read moves its own copy rather than the meta's, the same
        guarantee :meth:`PolicyObservation.row` states for the observation
        beside it.
        """
        return {
            "branch": self.branch,
            "depth": self.depth,
            "parent": self.parent,
            "theme_root": self.theme_root,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"CellMeta(branch={self.branch!r}, depth={self.depth}, "
            f"parent={self.parent!r}, theme_root={self.theme_root!r})"
        )


def cell_meta(tree: Any, node_id: str) -> CellMeta:
    """The structural metadata of ``node_id`` — docs §595's ``meta()``, one call.

    The one spelling of "a cell's structure": :meth:`PolicyQuestion.meta` is a
    delegation to it, so the campaign question, a report over a tree and any
    later feature in this category all read structure through one derivation,
    exactly the discipline :meth:`PolicyQuestion._observe` keeps for the reading
    beside it.

    The node is addressed through the tree's own seam — ``tree.node(node_id)``,
    the address verb :meth:`reveal` and :meth:`probe_batch` route through — so a
    node the tree does not hold is refused with :class:`PolicyAddressError`,
    naming the node and the tree: a node id a policy hands to ``meta`` is one it
    was shown, and structure computed for a cell outside the tree would let a
    policy reason about a campaign it never saw.  An unrevealed node the tree
    *does* hold answers its structure, which is the sibling pool's law (feature
    184 refuses only a node *"outside the lattice"*) and the point of the
    accessor: docs §11.1 exposes ``theme_root`` here so family-conditional
    thresholds can be authored over the cells a policy may select from, and
    structure is not the fact §10.2's barrier withholds — scores are.

    The walk from the cell to the origin of its branch is what fixes both
    ``depth`` and ``branch``, and it is bounded rather than trusted: a campaign
    tree whose parent references form a cycle (feature 217's constructor refuses
    a *dangling* reference but has no reason to walk, so it does not refuse a
    closed one) leaves a cell with no origin, and a walk that followed it would
    never return.  Such a cell is refused here with :class:`PolicyTreeError`
    naming the cell and the cycle, because a cell with no branch origin has no
    structure to report — the honest answer for a malformed tree rather than a
    hang or an invented root.

    The seam is duck-typed, for the reason every seam in this member is: the
    module loader imports the package under a synthetic name and re-executes it,
    so the tree ``create_app()`` hands out may be a *second*
    :class:`CampaignTree` class object, and an ``isinstance`` would refuse the
    very tree composition produces.  What the seam *reads* it validates — the
    two attributes the walk calls through (``nodes`` and ``node``), the node's
    own id, parent and payload — and every failure is translated into this
    module's vocabulary rather than escaping as a bare :class:`AttributeError`
    or :class:`ValueError` a caller catching :class:`PolicyRuntimeError` would
    miss ([[error-vocabulary-at-member-seams]]).

    Pure: it consults nothing but the tree it is handed — no store, no clock, no
    configuration, no reveal set — so two calls for one cell answer equal frozen
    values, and two trees holding the same nodes answer the same meta.
    """
    node = _addressed_node(tree, node_id)
    nodes = _nodes_by_id(tree)
    origin, depth = _walk_to_origin(nodes, node)
    return CellMeta(
        branch=None if origin.node_id == node.node_id else origin.node_id,
        depth=depth,
        parent=node.parent_id,
        theme_root=_theme_root_of(node),
    )


def _addressed_node(tree: Any, node_id: Any) -> Any:
    """The tree's own node for ``node_id`` — the address seam, validated.

    Reads ``tree.node(node_id)``, the one place a node id becomes a node, and
    refuses a tree that has no such verb in this module's vocabulary rather than
    letting an :class:`AttributeError` escape.  A node id the tree does not hold
    is refused by the tree itself, with :class:`PolicyAddressError` — the
    refusal feature 217's tree already owns, propagated unchanged so the
    specific sentence naming the node and the tree survives rather than being
    re-spelled here.
    """
    address = getattr(tree, "node", None)
    if not callable(address):
        raise PolicyTreeError(
            f"a cell's meta is read off a campaign tree — got {tree!r} "
            f"({type(tree).__name__}), which has no node(); the four structural "
            "fields docs §595 names are facts about where a cell sits in the "
            "tree, and an object that cannot address a node names no structure "
            "to report (feature 219)"
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
            f"node() raised {exc!r}. A cell's meta is the structure the tree "
            "holds for a node it carries, so an address verb that fails is a "
            "tree this accessor cannot read rather than a node without "
            "structure (feature 219)"
        ) from exc


def _nodes_by_id(tree: Any) -> dict[str, Any]:
    """The tree's nodes, keyed by node id — the parent walk's index.

    Built once per read from the tree's own ``nodes``, so the walk from a cell
    to the origin of its branch is a lookup per step rather than a scan per
    step.  A tree whose ``nodes`` is not a sequence of nodes carrying a
    ``node_id`` is refused here, in this module's vocabulary, naming what
    arrived — the seam's own read validation.
    """
    try:
        sequence = tuple(tree.nodes)
    except Exception as exc:  # a tree whose nodes cannot be read is this law's
        raise PolicyTreeError(
            f"a campaign tree's nodes could not be read: {tree!r} "
            f"({type(tree).__name__}) raised {exc!r} reading `nodes`. The four "
            "fields of docs §595's CellMeta are derived from the tree's own "
            "nodes — a cell's parent chain is what fixes its depth and its "
            "branch — so a tree whose nodes cannot be walked names no structure "
            "(feature 219)"
        ) from exc
    index: dict[str, Any] = {}
    for node in sequence:
        node_id = getattr(node, "node_id", None)
        if not isinstance(node_id, str) or not node_id.strip():
            raise PolicyTreeError(
                f"a campaign tree holds {node!r} ({type(node).__name__}), which "
                "carries no node_id: the walk that fixes a cell's depth and "
                "branch is keyed by node id, and a node that cannot be named "
                "cannot be placed in the tree it belongs to (feature 219)"
            )
        index[node_id] = node
    return index


def _walk_to_origin(nodes: Mapping[str, Any], node: Any) -> tuple[Any, int]:
    """Walk a cell's parent chain to the origin of its branch.

    Returns the origin node — the one whose ``parent_id`` is ``None`` — and the
    number of steps the walk took, which is the cell's structural depth.  The
    walk is *bounded*: a parent the tree's index does not hold, or a chain that
    revisits a node, is refused with :class:`PolicyTreeError` naming the cell
    and the offending reference.  Feature 217's constructor validates that every
    parent reference resolves, so a dangling one reaching here means the tree
    was mutated past it or was built by another implementation, while a *cycle*
    is a shape the constructor has no reason to reject and this walk cannot
    survive — both are malformed trees, and both are refused rather than
    followed.
    """
    seen = {node.node_id}
    current = node
    steps = 0
    while current.parent_id is not None:
        parent_id = current.parent_id
        parent = nodes.get(parent_id)
        if parent is None:
            raise PolicyTreeError(
                f"the branch of cell {node.node_id!r} cannot be resolved: it "
                f"names a parent {parent_id!r} that is not a node in the tree. A "
                "cell's depth and branch are derived by walking to the origin of "
                "its branch, and a chain with a missing link reaches no origin — "
                "so the cell has no structure to report rather than a depth "
                "guessed at (feature 219)"
            )
        if parent_id in seen:
            raise PolicyTreeError(
                f"the branch of cell {node.node_id!r} cannot be resolved: its "
                f"parent chain revisits {parent_id!r}, so the cell sits on a "
                "cycle with no origin and no depth. A campaign tree is a tree — "
                "one node per id, every branch planted at a root whose parent is "
                "absent — and a closed chain is a shape this walk refuses rather "
                "than follows forever (feature 219)"
            )
        seen.add(parent_id)
        steps += 1
        current = parent
    return current, steps


def _theme_root_of(node: Any) -> str | None:
    """The family a cell's own record states — or ``None`` when it states none.

    Read by name from the node's payload, which is §9.1's ``theme_root TEXT NOT
    NULL`` column as the node froze it.  Three outcomes, and the distinctions
    between them are the point:

    * the payload states no such key, or states ``None`` — the family is
      **absent**, and the answer is ``None``.  This is the honest null
      :meth:`PolicyObservation.from_node` states one field over (a node that
      carries no in-sample reading is a structural node, and its observation
      says so rather than inventing a number); a cell whose record declares no
      family reports no family rather than being refused, because a tree the
      deployment's own store can hold must be readable;
    * the payload states a non-empty string — the research theme, carried
      verbatim.  Nothing is normalised, lowercased or matched against a legal
      set: *which* themes may exist is feature 241's committed config, and
      restating that ceiling here would be a second spelling of a config-bound
      law, the drift feature 228's own key check refuses for the same reason;
    * the payload states anything else — a blank string, a number, a nested
      object — and the cell is **refused** naming it, because that is a corrupt
      structural record rather than a silent absence, and a family that cannot
      be named cannot be conditioned (the member's never-coerce stance,
      :func:`families._theme_key`).

    The payload itself is read through the node's own ``content`` — the one
    implementation of "the metric mapping this node froze" — with a fallback to
    the node's canonical ``payload`` text for a foreign carrier, and a payload
    that cannot be read at all is refused in this module's vocabulary rather
    than escaping as a :class:`ValueError` from :func:`json.loads`.
    """
    payload: Any = getattr(node, "content", None)
    if not isinstance(payload, Mapping):
        payload = _parsed_payload(node)
    if not isinstance(payload, Mapping):
        raise PolicyTreeError(
            f"campaign node {node.node_id!r} carries a payload that is not a "
            f"mapping of structural fields: got {payload!r} "
            f"({type(payload).__name__}). A cell's theme_root is read by name "
            "from the record the node froze — §9.1's own column — so a payload "
            "that is not a mapping of fields names no family and no structure "
            "(feature 219)"
        )
    if THEME_ROOT_KEY not in payload:
        return None
    value = payload[THEME_ROOT_KEY]
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise PolicyTreeError(
        f"campaign node {node.node_id!r} carries {THEME_ROOT_KEY}="
        f"{value!r} ({type(value).__name__}): a cell's theme_root is the "
        "research theme its branch was planted in — the slug docs §11.1's "
        "family-conditional thresholds are keyed on — so a record that states "
        "the field and states nothing nameable in it is corrupt rather than "
        "absent, and the accessor refuses to report a family it cannot name "
        "(feature 219)"
    )


def _parsed_payload(node: Any) -> Any:
    """A foreign node's canonical payload text, parsed — or ``None``.

    The fallback behind :func:`_theme_root_of`'s ``content`` read: a node that
    is not this member's :class:`CampaignNode` still carries the frozen bytes,
    so the accessor parses them rather than demanding a class it cannot
    ``isinstance`` (the loader's double-import makes the seam duck-typed).  A
    payload that does not parse answers ``None`` — the malformed-payload refusal
    belongs to :func:`_theme_root_of`, which knows the node's id and can name
    it, and raising here would name the JSON error instead of the cell.
    """
    payload = getattr(node, "payload", None)
    if not isinstance(payload, str):
        return None
    try:
        import json

        return json.loads(payload)
    except (TypeError, ValueError):
        return None
