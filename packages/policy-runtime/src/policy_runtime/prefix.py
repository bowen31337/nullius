"""Feature 223, the prefix view — the fresh object a policy is handed, holding
only the cells it has revealed.

app_spec.xml, "Exploration Policy Runtime", feature 223 (``covers="cq-16"``,
``depends_on=217``): *System constructs the prefix view as a fresh object,
which returns only revealed nodes so unrevealed nodes are absent rather than
filtered.*  docs/nullius-tech-architecture.md §10.2 states the law verbatim:

    ``prefix_view()`` constructs a fresh object exposing only revealed
    nodes. It is not a filtered view over the full tree; unrevealed nodes
    are not present in the returned structure at all. A policy cannot
    reach them by introspection, attribute walking, or a stray ``__dict__``
    access.

and §10.1 shows the one call site the law exists for — ``batch =
policy.select(prefix_view(revealed))``, the moment a replay hands authored
policy code its world for the round.

**217 made one *return value* prefix-only; 223 makes the object the policy
holds prefix-only.**  The question (feature 217) fronts the tree *because the
runtime needs it to*: ``reveal`` refuses a node outside the tree by looking
the node up in it, and every observation is the tree's honest payload-derived
reading.  The runtime may hold that seam; authored policy code may not — a
caller holding the question could walk ``question._tree`` to every node the
campaign holds, and the barrier would be a promise about what it chose to
call.  :func:`prefix_view` is the hand-off between the two audiences: it reads
the question's own :meth:`~policy_runtime.PolicyQuestion.observed` — the one
implementation of the reading there is, so the view's cells *are* the
question's, never a second spelling over the raw tree that could drift — and
copies the frozen observations out into a fresh :class:`PrefixView` that
holds the prefix and nothing else.  No tree behind it, not even under an
underscore; no question; no reveal set; no address verb.

**Absent rather than filtered — the distinction the sentence turns on.**  A
filtered view would hold the tree and screen it, and then the barrier would
be a *predicate* — one more function to get right on one more path, and a
policy that reached the filter's subject would hold the whole campaign.
The view is the other design: it holds prefix data and only prefix data, so
an unrevealed node is absent because **there is nowhere in the object it
could be** — not a key, not a value, not behind an attribute, not in a
``__dict__`` (the class carries slots and no dictionary at all, so the stray
access of docs §10.2 finds nothing to read), not in the object graph a
policy can walk from the view.  And where the question *refuses* a node
outside the tree, the view has no verb for asking at all: no ``node``, no
``meta``, no ``reveal`` — the refusal is structural, one seam weaker than a
guard.  The barrier is a fact about what the object is made of, which is why
cq-16 is answered by a construction and not by a check.

**Fresh object, snapshot semantics — both halves of "fresh".**  Every call to
:func:`prefix_view` constructs a new view over the reveal set as it stands,
so two calls over one reveal set are equal but distinct — freshness is a
fact about identity, not content.  And a view already held does not grow
when the question reveals more: the observations were copied out at
construction, not aliased to live state, so a policy watching a view it
holds sees the prefix it earned and nothing later.  The contrary design — a
live view over the question — would let a policy read the prefix extending
without revealing, which is a reveal by other means and precisely the leak
§10.2 exists to close.

**Why the factory takes the question, not the bare reveal set.**  §10.1's
spelling is ``prefix_view(revealed)``; in this member the reveal set and the
honest readings over it live behind the question, and reading them there is
what makes the view's readings the question's — one implementation of the
reading, shared, instead of a second derivation from the raw tree.  The
seam is duck-typed and validates what it reads, for the reason the tree
seam already states: the module loader imports the member under a synthetic
name and re-executes it, so a question this process composed may be a
*second* :class:`~policy_runtime.PolicyQuestion` class object, and an
``isinstance`` would refuse the very objects composition produces.  What the
seam demands is the read side — a callable ``observed()`` — and what it
refuses (a non-question, a non-mapping answer, a mapping whose keys
disagree with the observations they carry) is refused in this module's own
vocabulary, so nothing escapes as a bare :class:`AttributeError` a caller
catching the member's one base class would miss
([[error-vocabulary-at-member-seams]]).

**A hand-written slots class, not a frozen dataclass.**  The value's
guarantees — no ``__dict__``, one read-only field, a setter that refuses
every name — are the member's own :class:`~policy_runtime.PolicyQuestion`
construction (``__slots__``, a private store, read-only accessors) rather
than ``dataclass(frozen=True, slots=True)``: the dataclass route rebuilds
the class behind a compiled ``__setattr__`` closure bound to the pre-rebuild
one, and a non-field assignment on the rebuilt class then dies inside
``super()`` with a bare :class:`TypeError` — an unnamed failure, in no
vocabulary at all, where this member refuses *and names*.  Hand-written, the
guard is one method every spelling of the act lands in, and the refusal is
an :class:`AttributeError` — the attribute protocol's own error, so a caller
catching what ``hasattr`` catches catches it — whose message states the law.

**No component, no seat, no new error.**  The view is a pure construction
over a question — no store, no deployment state, no registration — so it is
reached directly from the member exactly as :func:`policy_runtime.plan_grid`
(feature 229), :func:`policy_runtime.screen_policy` (230/231) and
:func:`policy_runtime.read_beta` (226) are.  The refusals reuse
:class:`~policy_runtime.PolicyTreeError`: they are the answer surface's own
contract — the thing handed in did not front the read side, or the mapping
it returned was not a mapping of cells keyed by the id they were earned on —
the same family the question's own construction refusals belong to, and a
sixth error class would split one contract across two names.  Stdlib only,
and import-cheap: :mod:`collections.abc` plus the member's own error, so
the factory's scan pays nothing for the law.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from .errors import PolicyTreeError

if TYPE_CHECKING:  # pragma: no cover - typing only; the package imports this module
    from policy_runtime import PolicyObservation, PolicyQuestion

__all__ = [
    "PrefixView",
    "prefix_view",
]

#: The fields an observation carries — the read side of feature 217's
#: :class:`~policy_runtime.PolicyObservation`.  The view checks a cell for
#: these *by name* rather than with an ``isinstance``, for the reason the
#: question's own tree check states: the module loader imports the member
#: under a synthetic name and re-executes it, so an observation built by the
#: composed member may be a second class object, and the view must front it
#: as readily as its own.
_OBSERVATION_FIELDS = (
    "node_id",
    "r2_insample",
    "ic_insample",
    "n_periods",
    "n_features",
)


class PrefixView:
    """The prefix a policy has earned — a fresh snapshot of revealed cells.

    The object a replay hands authored policy code (docs §10.1), holding the
    observations of the cells the policy has revealed and *nothing else*: no
    tree to filter, no question to walk back to, no reveal set, no address
    verb.  Constructed fresh by :func:`prefix_view` per call; two views of
    one reveal set are equal but distinct, and a view held while the
    question reveals more answers the prefix it was built over — the
    observations were copied out, never aliased to live state.

    Hand-written with ``__slots__``, a read-only :attr:`cells` and a setter
    that refuses every name, deliberately: the class carries no ``__dict__``
    at all, so the stray access docs §10.2 names finds nothing to read, and
    no attribute — public, private or shadow — can be attached or rebound on
    a held view.  A policy cannot hand itself a longer prefix it did not
    earn, and the read-only guarantee is only as strong as the object's
    inability to grow or move attributes, the same stance
    :class:`policy_runtime.EpisodeBeta` takes on the scalar and
    :class:`contract.MarketWindow` takes on a decision time.  Every
    attribute, every cell, and every value inside a cell is prefix data: an
    unrevealed node is absent from this object because there is nowhere in
    it the node could be.

    :attr:`cells` is the whole of the state — a tuple of observations
    ascending by node id, normalised in :meth:`__init__` — and it is public
    on purpose, the way :attr:`policy_runtime.CampaignTree.nodes` is: a
    policy that walks it finds revealed cells, which is exactly what it is
    allowed to find.  The read-side surface is :meth:`observed`, the shape
    feature 217 fixed for the mapping (``{node_id: Observation}``,
    ascending); a fresh dict per call, so a policy cannot move the view
    through the mapping it read, the same guarantee
    :meth:`policy_runtime.PolicyObservation.row` makes.
    """

    #: One slot, private: the cells tuple.  No ``__dict__`` beside it, so
    #: there is no shadow state a caller could attach and no dictionary a
    #: stray access could read.
    __slots__ = ("_cells",)

    def __init__(self, cells: Iterable[PolicyObservation] = ()) -> None:
        collected = tuple(cells)
        seen: set[str] = set()
        for cell in collected:
            node_id = _cell_node_id(cell)
            if node_id in seen:
                raise PolicyTreeError(
                    f"the prefix view carries the node {node_id!r} twice: a node id "
                    "names one cell, the mapping the view is built from keys one "
                    "observation by it, and two cells wearing one id is a prefix "
                    "the policy could not read (feature 223, docs §10.2)"
                )
            seen.add(node_id)
        object.__setattr__(
            self, "_cells", tuple(sorted(collected, key=_cell_node_id))
        )

    @property
    def cells(self) -> tuple[PolicyObservation, ...]:
        """The revealed cells' observations, ascending by node id — read-only.

        Prefix data only, by construction, and public on purpose: a policy
        that walks it finds the cells it has revealed, which is exactly what
        it is allowed to find.  Sorted in :meth:`__init__`, so two views of
        one reveal set render identically whatever order the reveals came
        in.
        """
        return self._cells

    def observed(self) -> dict[str, PolicyObservation]:
        """The revealed cells and their observations — ``{node_id: Observation}``.

        The shape feature 217 fixed for the read side, over the cells this
        view holds: ascending by node id, so two views of one reveal set
        render identically whatever order the reveals came in, and a report
        built from a view is reproducible.  A fresh dict per call, never a
        shared one, so a policy that writes into the mapping it read moves
        its own copy and not the prefix — reading is not revealing, and a
        mapping that grew or moved on a read would be a prefix the policy
        could shape without a reveal.
        """
        return {_cell_node_id(cell): cell for cell in self._cells}

    def __len__(self) -> int:
        """How many cells the policy has revealed — the prefix's size."""
        return len(self._cells)

    def __contains__(self, node_id: object) -> bool:
        """Whether ``node_id`` names a revealed cell — absence, not filtering.

        ``False`` for an unrevealed node is a fact about what the view is
        made of: the node is not present in it at all, and the answer is
        computed over the cells the view holds, never against a tree that
        could name the node back.  There is nothing to filter *over* — the
        distinction docs §10.2 draws and the reason the check is a scan of
        prefix data rather than a lookup into anything larger.
        """
        return any(_cell_node_id(cell) == node_id for cell in self._cells)

    def __setattr__(self, name: str, value: object) -> None:
        """Refuse every assignment — the prefix cannot be moved or extended.

        Not just ``cells``: *any* name, public, private or shadow, because a
        view whose attributes could move would be a prefix the policy could
        reshape — hand itself cells it did not reveal, or attach state beside
        the earned ones.  An :class:`AttributeError`, the attribute
        protocol's own error, naming the act and the law: the refusal meets
        the caller at the spelling they tried, the same boundary
        :class:`policy_runtime.EpisodeBeta`'s setter draws around the
        scalar.
        """
        raise AttributeError(
            f"a prefix view is a snapshot of the cells a policy has revealed and "
            f"cannot be reassigned or extended (attempted `view.{name} = {value!r}`): "
            "the object holds only what was earned, and a view whose attributes "
            "moved would be a prefix the policy shaped rather than earned "
            "(feature 223, docs §10.2)"
        )

    def __delattr__(self, name: str) -> None:
        """Refuse deletion — there is nothing here to remove.

        The same law from the other side: ``del view.cells`` reaching for
        the earned prefix is the reassignment it is not allowed to make,
        and a view with no removable attributes cannot be hollowed into a
        shape the reveals do not justify.
        """
        raise AttributeError(
            f"a prefix view carries only the cells a policy has revealed and "
            f"nothing to delete (attempted `del view.{name}`): the snapshot is "
            "what it was built from and cannot be reshaped after the fact "
            "(feature 223, docs §10.2)"
        )

    def __eq__(self, other: object) -> bool:
        """Content equality — two views of one reveal set are one prefix.

        Equality is the cells, so freshness never turns into identity: a
        replay handing a policy a new view per round (docs §10.1) hands it
        an equal one whenever the prefix has not moved, and a different one
        the moment it has.  A foreign type answers ``NotImplemented``, the
        honest reflex of a value that compares only with its own.
        """
        if not isinstance(other, PrefixView):
            return NotImplemented
        return self._cells == other._cells

    def __hash__(self) -> int:
        """The hash of the cells — equal views hash equally, so a replay can
        key a ledger by the object it handed a policy without a wrapper."""
        return hash(self._cells)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"PrefixView(cells={len(self._cells)})"


def _cell_node_id(cell: Any) -> str:
    """The node id a cell is earned on — validating the cell on the way out.

    The one place a cell becomes an addressable id, shared by every guard in
    this module so "validated twice" is one rule read twice, not two rules.
    Demands the read side of an observation — the id plus the metric fields
    feature 217 froze — *by name*, not by ``isinstance``, because the
    module loader re-executes this member under a synthetic name and the
    composed member's observations are a second class object the view must
    front as readily as its own.  Refused here, in this module's vocabulary,
    rather than escaping as an ``AttributeError`` from wherever the caller
    first touched the field.
    """
    if not all(hasattr(cell, field) for field in _OBSERVATION_FIELDS):
        raise PolicyTreeError(
            f"a prefix view is built of observations, got {cell!r} "
            f"({type(cell).__name__}), which carries none of an observation's "
            "fields; the view holds the observations the question's observed "
            "accessor made, and a value carrying none is not a cell a policy "
            "revealed (feature 223, docs §10.2)"
        )
    node_id = cell.node_id
    if not isinstance(node_id, str) or not node_id.strip():
        raise PolicyTreeError(
            f"a prefix view cell must carry a non-empty node_id, got "
            f"{node_id!r}: the id is the key the observed mapping is keyed by "
            "and the one address a revealed cell has, and a cell with none "
            "cannot be keyed or named (feature 223, docs §10.2)"
        )
    return node_id


def prefix_view(question: PolicyQuestion) -> PrefixView:
    """Construct the prefix view over a question — the fresh object of §10.2.

    The one factory, and the whole verb of feature 223: reads the question's
    own :meth:`~policy_runtime.PolicyQuestion.observed` — the one
    implementation of the reading, so the view's cells are the question's —
    and copies the frozen observations out into a fresh
    :class:`PrefixView`.  The returned object holds no reference to the
    question or the tree it fronts: not under an attribute, not in a slot,
    not anywhere a policy could walk to, so the prefix a policy reads is the
    prefix it earned and no path leads further (docs §10.1–§10.2, cq-16).

    The seam is duck-typed and validates what it reads: a callable
    ``observed()`` is the whole of the demand, so the question this process
    composed under the module loader's synthetic name — a second class
    object an ``isinstance`` would refuse — fronts a view as readily as the
    member's own, while a string, a mapping or a bare object is refused,
    naming what was wrong.  A returned value that is not a mapping, or a
    mapping whose keys disagree with the observations they carry (two names
    for one cell), is refused here in this module's vocabulary rather than
    escaping as the ``AttributeError``/``ValueError`` the traversal would
    raise — the error-vocabulary discipline every member seam keeps.

    Pure: it consults nothing but the question it is handed — no store, no
    clock, no configuration — and every call constructs a new view, so a
    replay's rounds hand a policy a fresh object per round, exactly the
    construction docs §10.1's ``policy.select(prefix_view(...))`` names.
    """
    observed = getattr(question, "observed", None)
    if not callable(observed):
        raise PolicyTreeError(
            f"a prefix view fronts a question — got {question!r} "
            f"({type(question).__name__}), which has no observed(); the view is "
            "the object a replay hands authored policy code (docs §10.1), built "
            "from the read side that accessor owns, and an object without it "
            "names no prefix a policy could be shown (feature 223, docs §10.2)"
        )
    mapping = observed()
    if not isinstance(mapping, Mapping):
        raise PolicyTreeError(
            f"a question's observed accessor returns a mapping of revealed node "
            f"ids to observations, got {mapping!r} ({type(mapping).__name__}); the "
            "prefix view is built by copying that mapping's cells out, and a "
            "value that cannot be walked by key names no prefix (feature 223, "
            "docs §10.2)"
        )
    for node_id, observation in mapping.items():
        if _cell_node_id(observation) != node_id:
            raise PolicyTreeError(
                f"the observed mapping keys the node {node_id!r} against an "
                f"observation earned on {_cell_node_id(observation)!r}: a prefix "
                "view keys an observation by the id it was earned on, and a "
                "mapping that disagrees with its own cells is two names for one "
                "cell — the view refuses to pick one (feature 223, docs §10.2)"
            )
    return PrefixView(cells=tuple(mapping.values()))
