"""Feature 269, the error accounting — Type-A commitment errors and
Type-B depth-past-flip errors, each answered as its own metric and never
as one figure.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 269: *System
accounts Type-A commitment errors separately from Type-B depth-past-flip
errors, which returns each as its own metric.*  docs/alpha-engine-prd.md
§4.1.2 states the instruction as a design law (line 140): *"Separate the
error accounting.  Type-A error is committing to a null; Type-B is
continuing to deepen past the flip."*  docs/nullius-tech-architecture.md
§7.3.1 restates it as a table (lines 342-343) — Type-A *committed to a
null node*, dominant in Type-R worlds; Type-B *kept deepening past the
flip*, dominant in Type-D worlds — and names why the split exists at all
(line 339): *"Two distinct failures, two distinct terms.  Conflating them
was the original design's blind spot."*  This module is the accounting
that keeps them apart: :func:`account_errors` (the verb) and
:class:`ErrorAccounting` (the value, one field per metric).

**Two metrics, one value, never one figure.**  The feature's closing
clause — *"returns each as its own metric"* — is made structural here the
only way a shape can make it: the answer carries the two figures as
separately named fields (:attr:`ErrorAccounting.commitment_error_rate` for
Type-A, :attr:`ErrorAccounting.depth_past_flip_errors` for Type-B) and
exposes no total, no blend, no weighting between them — there is no
third number to conflate into, so a caller cannot average the two
failures into the unattributable result §7.3.1 says mixed accounting
produces.  The two are different *kinds* on purpose, because the two
errors are different kinds of event: Type-A's metric is a fraction of
committed picks (prd §4.4's *"false discovery rate — fraction of
committed picks that are planted nulls"*, line 173), the figure β₂
charges (feature 258's term, over the rate feature 265's process
answers); Type-B's metric is a count of error events — each explored node
that sits at or beyond its branch's flip is one act of *continuing to
deepen past the flip*, and prd §11's secondary metric names the quantity
it trends (line 540): *"Type-B error rate: depth past the flip in
Type-D worlds"*.  A single figure over both would be the conflation
§4.1.2 was written to forbid, and the policy would get a muddled
gradient between revisions exactly where §4.1.2 says it must not.

**Type-A rides the scorer process's one verb — the labels are read only
there.**  app_spec.xml gives this feature ``depends_on="265"``, and 265's
own docstring names what follows from it: the calibration figures that
come after *"are further answers off the same held labels"* — but the
process's own class law is that it carries *"no other public surface"*
than :meth:`~scoring.NullPickScorer.null_pick_rate`, because *"a second
method that handed back a label, a count of nulls, or the sidecar itself
would be a second place the barrier leaks."*  (The process has since
grown exactly one more verb — feature 266's
:meth:`~scoring.NullPickScorer.calibration_figures`, which answers two
figures and nothing label-shaped, the growth that same reservation
named — and nothing here changes: the accounting asks the process for
one number, the rate, and 266's figures are a sibling answer this
module does not consume.)  So the accounting does not
ask for a count of nulls and does not read a label: it asks the process
for the one number §10.3 lets out (docs line 507: *"the number flows
out; the labels do not"*), handing the picks over verbatim, and takes
the figure as Type-A's metric unchanged.  That figure is the campaign's
own realized rate, deliberately not ``FDR_deploy`` — the π₀ ≈ 0.9
reweighting is feature 267's arithmetic and feature 268's headline, and
feature 258's docstring already argues why a term over the reweighted
figure would be a projection rather than a measurement; the accounting
holds the same stance on the same grounds.  A process that answers
nothing usable (absent, uncallable, foreign-failing, or a figure outside
``[0, 1]``) is refused here in this module's own vocabulary, and a
process that refuses the *picks* refuses in its own — the same member's
:class:`~scoring.NullPickRateError`, propagated untranslated so the
repair stays named where the law lives.

**Type-B is a fact of depths, and the depths are handed over already
joined.**  §7.3 fixes the Type-D regime: every root real, a branch
flipping null at a drawn depth, and docs §7.2 states the boundary in one
line (line 311): *"below ``flip_depth`` the real targets are returned,
at or beyond it the permuted ones."*  Null-ness in a Type-D world is
therefore a fact of two integers — the node's ``depth`` and its branch's
``flip_depth`` — *not* a bit the sidecar holds, which is why the oracle's
own target route resolves a Type-D request against the depths and never
the stored bit.  The join that produces those two integers (which branch
a node hangs from, where that branch's flip was drawn) is the null
oracle's verb — feature 265's docstring declines to restate it (*"a
Type-D branch's depth against its flip — is the oracle's verb, not this
member's"*) and this module declines for the same reason: restating the
ancestor walk would be a second, disagreeing implementation of the
oracle's law.  So the seam takes each explored node duck-typed by the
three facts it needs — ``node_id`` (to name refusals after, never to
join), ``depth`` and ``flip_depth`` — which is exactly the shape the
oracle's own :class:`~nulloracle.TypeDResolution` carries on its
oracle-side record, and the cross-member suite pins that the real value
satisfies the seam.  Never ``isinstance``: the loader imports members
under synthetic names and re-executes them, so the resolution a composed
oracle hands out is structurally a ``TypeDResolution`` but never the
class object a direct import yields.

**The boundary is inclusive — the node at the flip is the first null
node.**  §7.2's *"at or beyond it the permuted ones"* makes the node at
exactly ``flip_depth`` the first null node of the branch, not the last
real one, and the oracle's own resolution states the same reading of the
same words (:func:`nulloracle.resolution.past_the_flip` answers
``depth >= flip_depth``).  The comparison is restated here — a member
restates the boundary in its own vocabulary the way feature 265 restates
the UUID canonicalization, never importing the member that owns it — and
the cross-member suite pins the restatement against the oracle's own
predicate, spelling for spelling, over the whole grid of depths and
flips.  An explored node *below* the flip is a real exploration and
counts nowhere: in a Type-D world it is exactly the refinement the
campaign wanted.  An explored node *at or beyond* it is one Type-B error
— a well the policy deepened after the branch had silently gone null.

**An undrawn branch is refused, never read as below the flip.**  The
flip depth is drawn once per branch and persisted (feature 119); a node
whose branch carries no drawn flip presents no ``flip_depth`` at this
seam, and reading such a node as *not past* the flip would silently
deflate the one figure Type-B exists to count — the same direction
feature 265 refuses when it declines to read an unlabelled pick as real,
and the same argument :mod:`scoring._deflation` makes for refusing an
understated ``K``.  Unknown is not zero.  The refusal names the node,
because the repair is at the caller's join, and it is the seam's way of
holding prd §4.1.2's homogeneity law (line 674: the two campaign types
*"never mixed within one tree"*) without ever reading a campaign
declaration: a collection in which every node carries a drawn flip is a
Type-D ask, an empty collection is the ask of a campaign that crossed
nothing (below), and a collection mixing drawn and undrawn branches is
neither and is refused.

**Zero is a measurement — the target one.**  An empty ``explored``
collection answers ``0`` Type-B errors, and the zero is honest twice
over: it is the answer of a Type-R campaign, where §4.1.2 says wasted
depth is *"merely inefficient"* and so not this metric's error at all,
and it is the answer of a Type-D campaign that deepened nothing past any
flip — the state prd §11's *"falling across campaigns"* trends toward.
This is deliberately not the stance the picks ask takes: there, feature
265's own law refuses an empty denominator because a rate over nothing
is undefined, while here the figure is a count of events and none
happened is a fact, not a hole.  A duplicated node is refused rather
than counted twice — the revealed prefix is a set by §10.1's own line
(``revealed.add(child)``), and a collection holding one node twice is
not that set but a wiring fault that would double-charge one error.

**Shapes first, labels last.**  The verb validates the whole ask before
the process is asked anything: the seam, the collection, every node's
three facts, the duplicates.  Only an ask that could be answered touches
a label — through the process, one ask, the picks verbatim — which is
feature 265's own discipline (*"the ask is validated whole before the
first label is read"*) held one feature later, and the suite pins it
with a recording process that must stay unasked through every refusal.

**What this law deliberately does not do.**  It computes no sensitivity
or specificity — feature 266's figures, the sibling answer off the same
held labels — and no ``FDR_deploy`` (267's arithmetic, 268's headline).
It prices nothing: β₂ is feature 258's term and β₁ is feature 257's, and
§4.1.2's *"``β₂`` penalizes the first, ``β₁`` finally earns its keep on
the second"* is a statement about the terms, not this accounting — the
accounting measures the two errors, the terms charge for them, and a
module that did both would be the conflation's third face.  It persists
nothing: the ``replay_score`` row is the replay plugin's (feature 255),
and the cross-campaign Type-B *trend* docs line 909 lists among the
research metrics is the ops member's feature (345's), which will read
this figure per campaign.  It resolves no branch and reads no tree store — the join
is the oracle's verb, argued above.  It halts nothing (§7.4's
``halt_dreaming()`` is the verdict module's) and it takes no component
and no seat: like the blend, the index, the bonus and the five β-terms
it is arithmetic over figures another law owns, reached through the
member's own namespace — the growth pattern every free seam in this
workspace takes.

Stdlib only, and import-cheap: :mod:`math` for the finiteness gate,
:mod:`dataclasses` for the value, :mod:`collections.abc` and
:mod:`numbers` for the shapes, and the member's own error and rate
bound — no third-party import at module scope, so the factory's scan
(which imports this package to fire its ``@register`` builders) pays
nothing for the law.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Any

from ._nullpicks import RATE_BOUND
from .errors import ErrorAccountingError, ScoringError

__all__ = [
    "ErrorAccounting",
    "account_errors",
]


@dataclass(frozen=True)
class ErrorAccounting:
    """The accounting's answer — Type-A's metric and Type-B's, each its
    own field and nothing besides.

    A frozen value, for the same reason :class:`~scoring.WorldScore` and
    :class:`~scoring.AggregatedObjective` are frozen: these are the two
    figures the campaign's error accounting will be read from — β₂'s
    charge off the first, feature 345's trend off the second — and a
    value that could be edited after the fact would be a mutable handle
    to a measurement already made.  The fields:

    * :attr:`commitment_error_rate` — **Type-A's metric**: prd §4.4's
      false discovery rate, the fraction of committed picks that were
      planted nulls, as a finite real in ``[0, 1]``.  The same figure
      feature 265's scorer process answers and feature 258's β₂ charges
      on, accounted here as Type-A's own metric — the rate, never a
      count of nulls, because the process's own law lets exactly one
      number out and this value carries that number.
    * :attr:`depth_past_flip_errors` — **Type-B's metric**: the count of
      explored nodes sitting at or beyond their branch's flip depth,
      each one an act of continuing to deepen past the flip.  A
      non-negative integer; ``0`` is the measurement of a campaign that
      crossed nothing, not an absence.

    Every field is validated at construction — the stance the world
    score takes and every value after it inherits — so a value built by
    the verb and one built by hand answer identically to the law.  There
    is deliberately no third field: no total, no blend, no weighting of
    one error against the other, because the one figure this value must
    never carry is the single number over both failures that prd §4.1.2
    forbids (docs §7.3.1: *"conflating them was the original design's
    blind spot"*).
    """

    #: Type-A's metric — the fraction of committed picks that were
    #: planted nulls (prd §4.4 line 173), a finite real in
    #: ``[0, RATE_BOUND]``.  Both ends are measurements and both are
    #: honored: ``0.0`` is a campaign that committed to no null, ``1.0``
    #: one that committed to nothing else.
    commitment_error_rate: float

    #: Type-B's metric — how many of the explored nodes sit at or beyond
    #: their branch's flip depth (§7.2's inclusive boundary), each one a
    #: well deepened past a silent flip.  ``0`` is the target state prd
    #: §11 trends toward, and the honest answer for a Type-R campaign.
    depth_past_flip_errors: int

    def __post_init__(self) -> None:
        # The rate first, narrowed by the bound its term already states:
        # this is the same quantity feature 258's seam validates against
        # RATE_BOUND — one spelling of "a fraction of committed picks
        # lives in [0, 1]" — so the value and the penalty cannot disagree
        # about what a rate is.
        object.__setattr__(
            self,
            "commitment_error_rate",
            _require_commitment_error_rate(self.commitment_error_rate),
        )
        # The count: a genuine non-negative integer, bool refused before
        # it (a bool is an int in Python's hierarchy and not a count of
        # events), so the figure can be summed, trended and compared but
        # never silently read as a bit.
        object.__setattr__(
            self,
            "depth_past_flip_errors",
            _require_depth_past_flip_errors(self.depth_past_flip_errors),
        )


def account_errors(
    picks: object,
    *,
    explored: object,
    scorer: object,
) -> ErrorAccounting:
    """Account the campaign's two error types separately — Type-A's
    commitment errors as a rate, Type-B's depth-past-flip errors as a
    count — and answer each as its own metric.

    ``picks`` is the collection of committed picks the Type-A rate is
    taken over — the same ask :meth:`~scoring.NullPickScorer.null_pick_rate`
    takes, in the same two spellings (feature 222's values or their
    node-id texts), handed to the process **verbatim**: the pick law is
    feature 265's and a second spelling of it here would be a second
    thing to keep in sync.  ``scorer`` is the process — any object
    exposing a callable ``null_pick_rate``, feature 265's own
    :class:`~scoring.NullPickScorer` among them, duck-read because the
    loader imports members under synthetic names and an ``isinstance``
    would refuse the very process composition produces.  ``explored`` is
    the collection of explored nodes the Type-B count is taken over —
    each one duck-read by its three facts (``node_id``, ``depth``,
    ``flip_depth``), the shape the oracle's own Type-D resolution
    carries, joined upstream by the member that owns the ancestor walk.
    An empty ``explored`` collection answers ``0`` Type-B errors: the
    measurement of a campaign that crossed no flip (or a Type-R
    campaign, where wasted depth is not this metric's error).

    The ask is validated whole — seam, collection, every node's facts —
    before the process is asked anything, and the process is asked
    exactly once.  Refuses, with
    :class:`~scoring.ErrorAccountingError` and nothing partial:

    * a ``scorer`` that exposes no callable ``null_pick_rate`` — a
      wiring fault at the caller, named before anything is read;
    * an ``explored`` collection that is not one (a mapping's keys are
      not its nodes; a bare string is one node spelled where the
      collection belongs; something uniterable is not a prefix);
    * a node that names no node, carries a ``depth`` that is not a
      non-negative integer, or a ``flip_depth`` that is not an integer
      ``>= 1`` — the geometric's support, below which a root would flip
      and retype the campaign (feature 119's own law);
    * a node whose branch carries no drawn flip — its position past the
      flip is *unknown*, and reading it as below would deflate the one
      figure the count exists to charge;
    * a node carried twice — the revealed prefix is a set (§10.1), and a
      duplicate would double-count one error;
    * a process that fails while being asked (a failure this member did
      not name), translated into this vocabulary with the original
      chained;
    * a process that answers a figure outside ``[0, 1]`` — a number that
      has stopped being a rate, the likeliest wearer of its name being a
      count of null picks, which the process's own law refuses to let
      out and this value refuses to receive.

    A process that refuses the picks themselves refuses in its own
    vocabulary — :class:`~scoring.NullPickRateError`, this member's
    sibling class, propagated untranslated so the repair stays named
    where the pick law lives.

    Deterministic and pure in everything but the one composed ask: the
    same process, picks and explorations answer the same value to the
    bit, the count is one comparison per node, and the read the verb
    performs beyond arithmetic is the single ask the barrier already
    grants.
    """
    rate_of = _require_scorer_seam(scorer)
    facts = _the_explored_facts(explored)
    # §7.2's boundary, restated: at or beyond the flip is the permuted
    # regime, and the node at exactly the flip is the first null node of
    # the branch — so the comparison is inclusive, pinned against the
    # oracle's own predicate by the cross-member suite.
    crossed = sum(1 for _node, depth, flip in facts if depth >= flip)
    rate = _ask_the_process(rate_of, picks)
    return ErrorAccounting(
        commitment_error_rate=rate,
        depth_past_flip_errors=crossed,
    )


# -- the seam's private vocabulary ------------------------------------------


def _require_scorer_seam(scorer: object) -> Any:
    """The process's one verb, read duck-typed and checked.

    The contract is the callable ``null_pick_rate`` seam feature 265's
    own class carries — checked up front, before any shape is validated
    and before anything is read, because a carrier without it is a
    wiring fault at the caller and the cheapest fact to learn.  Not an
    ``isinstance`` for the reason every duck seam in this workspace
    states: the loader imports members under synthetic names, so the
    composed process is structurally a ``NullPickScorer`` but never the
    class object a direct import yields, and an ``isinstance`` here
    would refuse the very process composition produces.
    """
    seam = getattr(scorer, "null_pick_rate", None)
    if not callable(seam):
        raise ErrorAccountingError(
            f"the accounting asks the scorer process for Type-A's rate, "
            f"and this carrier exposes no callable null_pick_rate (got "
            f"{seam!r} on a {type(scorer).__name__}): hand feature 265's "
            f"NullPickScorer — composed from the app package's scorer "
            f"seat, or constructed over a sidecar — or any object that "
            f"answers its one verb, and the rate is asked of it inside "
            f"(feature 269, docs §10.3)"
        )
    return seam


def _the_explored_facts(explored: object) -> tuple[tuple[str, int, int], ...]:
    """The ask as validated (node, depth, flip) triples, refusing the
    shapes that are not the revealed prefix's facts.

    A mapping is refused because iterating one yields its keys, and a
    caller's mapping is keyed by nodes or by branches — either way the
    keys are not the explorations, and silently counting them would
    count a denominator nobody chose.  A bare string (and bytes, its
    encoding-shaped sibling) is refused because it is *one* node spelled
    where the collection belongs — the same refusal feature 265 makes of
    a one-pick string, in this seam's own direction.  Everything else
    must be iterable; a generator is consumed exactly once, here, into a
    tuple the count shares.
    """
    if isinstance(explored, (str, bytes, Mapping)):
        raise ErrorAccountingError(
            f"Type-B is counted over the explored nodes themselves, and "
            f"this ask carried {_shape_of(explored)}: hand the campaign's "
            f"Type-D explorations as a collection — each node carrying "
            f"its node_id, depth and the branch's flip_depth — not a "
            f"mapping (whose keys are not its nodes) and not a bare "
            f"string (one node spelled where the collection belongs) "
            f"(feature 269, prd §4.1.2)"
        )
    if not isinstance(explored, Iterable):
        raise ErrorAccountingError(
            f"Type-B is counted over the explored nodes themselves, and "
            f"this ask carried {_shape_of(explored)}, which is not a "
            f"collection of them: hand the campaign's Type-D explorations "
            f"as a collection, each node carrying its node_id, depth and "
            f"the branch's flip_depth (feature 269, prd §4.1.2)"
        )
    facts: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for node in tuple(explored):
        node_id = _node_id_of(node)
        if node_id in seen:
            # The revealed prefix is a set by §10.1's own line, and a
            # collection holding one node twice is not it: counting both
            # would double-charge one error, the one direction a count
            # cannot afford.
            raise ErrorAccountingError(
                f"the explored collection carries node {node_id!r} twice: "
                f"the revealed prefix is a set (docs §10.1's own "
                f"revealed.add), and one node deepened past its flip is "
                f"one Type-B error, not one per spelling — hand each "
                f"explored node once (feature 269, docs §10.1)"
            )
        seen.add(node_id)
        facts.append((node_id, _depth_of(node, node_id), _flip_depth_of(node, node_id)))
    return tuple(facts)


def _shape_of(value: object) -> str:
    """What the refusal calls the ask's carrier, without repr'ing it.

    A repr may be enormous, and a mapping's repr would print its keys —
    node facts a caller handed in good faith — into an error message a
    log will keep.  The shape names the repair; the contents are the
    ledger of nobody's business but the caller's.  The same discipline
    feature 265's seam states for the picks it is handed.
    """
    if isinstance(value, Mapping):
        return "a mapping"
    if isinstance(value, str):
        return "a bare string"
    if isinstance(value, bytes):
        return "bare bytes"
    return f"a {type(value).__name__} that is not iterable"


def _node_id_of(node: object) -> str:
    """One explored node's id — the caller's fact, held for naming.

    Non-empty text, strip-checked and taken as handed: this seam joins
    no keyed store (the branch join happened upstream, in the member
    that owns the ancestor walk), so the id is not canonicalized here —
    restating the oracle's UUID normalization would be a second spelling
    of a law this module never invokes — but it must *name* the node,
    because every refusal below names the node it refuses, and a node
    that cannot be named cannot be repaired.  ``bool`` is refused before
    the string check (a ``bool`` is an ``int`` in Python's hierarchy and
    not an address).
    """
    node_id = getattr(node, "node_id", None)
    if (
        isinstance(node_id, bool)
        or not isinstance(node_id, str)
        or not node_id.strip()
    ):
        raise ErrorAccountingError(
            f"each explored node is named by its node_id, and this one "
            f"exposes no non-empty text to name it by (got {node_id!r} "
            f"on a {type(node).__name__}): the refusals of this seam "
            f"name the node they refuse — the caller's own fact, never "
            f"the branch's — and a node that cannot be named cannot be "
            f"repaired at the join (feature 269, docs §7.2)"
        )
    return node_id


def _depth_of(node: object, node_id: str) -> int:
    """One explored node's depth — the tree's own fact about it.

    A genuine non-negative integer, ``bool`` refused before it: the
    depth is where the tree placed the node, and it is one of the two
    integers §7.2's boundary is resolved against — a value nobody placed
    the node at resolves nothing.  The id is in hand so the refusal can
    name the node it belongs to, the same courtesy feature 119's store
    pays the rows it validates.
    """
    depth = getattr(node, "depth", None)
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise ErrorAccountingError(
            f"the explored node {node_id!r} carries a depth of "
            f"{depth!r} ({type(depth).__name__}): the depth is the "
            f"tree's own fact about the node and half of §7.2's Type-D "
            f"boundary, and a value that is not a non-negative integer "
            f"placed by the tree resolves no boundary (feature 269, "
            f"docs §7.2)"
        )
    return depth


def _flip_depth_of(node: object, node_id: str) -> int:
    """One explored node's branch flip depth — the geometric's draw.

    A genuine integer ``>= 1``, ``bool`` refused before it: the flip is
    drawn from a geometric whose support is ``{1, 2, 3, …}`` (feature
    119's law), the support is what keeps every root real (a flip below
    1 would sit at depth 0 and retype the campaign Type-R), and a
    corrupted ``0`` in the join cannot be allowed to quietly cross every
    root.  Absent — no attribute, or ``None`` — is refused as the
    *undrawn branch*, never read as below the flip: unknown is not zero,
    and reading it the other way would silently deflate the one figure
    this count exists to charge.
    """
    flip = getattr(node, "flip_depth", None)
    if flip is None:
        raise ErrorAccountingError(
            f"the explored node {node_id!r} carries no drawn flip for "
            f"its branch: its position past the flip is unknown, not "
            f"below it — the flip depth is drawn once per branch and "
            f"persisted (feature 119), and a node whose branch never "
            f"drew cannot be counted on either side of the boundary. "
            f"Hand the Type-D explorations with their branches' flips "
            f"joined — an ancestor walk is the null oracle's verb, not "
            f"this member's — or hand none, for a campaign that crossed "
            f"nothing (feature 269, docs §7.2)"
        )
    if isinstance(flip, bool) or not isinstance(flip, int) or flip < 1:
        raise ErrorAccountingError(
            f"the explored node {node_id!r} carries a flip_depth of "
            f"{flip!r} ({type(flip).__name__}): the flip is drawn from a "
            f"geometric whose support is {{1, 2, 3, …}} (§7.3), and a "
            f"flip below 1 would sit at depth 0 — turning a root null "
            f"and retyping the campaign, which §7.3 forbids outright "
            f"(feature 269, docs §7.3)"
        )
    return flip


def _ask_the_process(rate_of: Any, picks: object) -> float:
    """Ask the process for Type-A's rate — once, verbatim, translated.

    The single place the verb crosses the barrier, and it crosses the
    way §10.3 draws it: the process holds the key, the number flows out
    and the labels do not.  The picks are handed over exactly as the
    caller handed them in — no re-validation, no copy — because the pick
    law is feature 265's and its refusals are 265's to raise.  This
    member's own refusals are the two around the ask: a process that
    fails while failing to answer (a stand-in's assertion, a foreign
    process's error) is translated into this vocabulary with the
    original chained — the translation law every cross-member seam in
    this workspace states — while anything already in this member's
    vocabulary (the process's own :class:`~scoring.NullPickRateError`
    among them) passes through untouched, so the caller's single
    ``except ScoringError`` keeps catching the whole member and the
    repair stays named where the law lives.
    """
    try:
        return rate_of(picks)
    except ScoringError:
        raise
    except Exception as exc:
        # Whatever the carrier raised, the fact for the caller is one
        # thing — Type-A's rate could not be asked — and the repair is in
        # the process the caller handed, not in this arithmetic.  Chained,
        # so the operator keeps the original; translated, so no foreign
        # vocabulary escapes through this seam.
        raise ErrorAccountingError(
            f"the scorer process could not be asked for Type-A's rate: "
            f"{exc!r} ({type(exc).__name__}). The labels live in the null "
            f"oracle's sealed file and the process is the one component "
            f"that may read them (docs §10.3) — a process that fails "
            f"while being asked is a fact about the deployment's sidecar "
            f"configuration, not about the accounting, and no rate is "
            f"invented over labels nobody could read (feature 269, "
            f"docs §10.3)"
        ) from exc


def _require_commitment_error_rate(value: object) -> float:
    """Narrow Type-A's metric to a finite ``float`` inside ``[0, 1]``.

    The same quantity, the same bound, one spelling:
    :data:`~scoring.RATE_BOUND` is the fact feature 258's seam states
    for the rate it charges — a fraction of committed picks is a number
    between none and all of them — and the metric this value carries is
    that same figure, so the narrowing is the same.  ``int`` admitted
    and narrowed (``0`` and ``1`` are measurements), ``bool`` refused
    before it, NaN and ±inf refused because a figure that is not a
    measurement cannot be a fraction, and an out-of-bound figure refused
    rather than clamped — the likeliest thing wearing the name being a
    *count* of null picks, which the process's own law refuses to let
    out and which clamped to an endpoint would charge a rate nobody
    measured.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ErrorAccountingError(
            f"commitment_error_rate must be Type-A's metric — the "
            f"fraction of committed picks that were planted nulls — as a "
            f"real number, got {value!r} ({type(value).__name__}): the "
            f"figure is the number feature 265's scorer process answers "
            f"and feature 258's beta-two charges on, and a value that is "
            f"not a real is not a fraction (feature 269, prd §4.4)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ErrorAccountingError(
            f"commitment_error_rate must be finite, got {narrowed!r}: a "
            f"NaN would make Type-A's metric a NaN the dreaming loop's "
            f"argmax silently drops, and an infinity is not a fraction "
            f"of committed picks (feature 269, prd §4.4)"
        )
    if not 0.0 <= narrowed <= RATE_BOUND:
        raise ErrorAccountingError(
            f"commitment_error_rate must be a rate in "
            f"[0.0, {RATE_BOUND!r}], got {narrowed!r}: the metric is prd "
            f"§4.4's false discovery rate — the committed picks that "
            f"were planted nulls over all the committed picks — so it is "
            f"a fraction of a whole and bounded by construction. A value "
            f"outside the bound is not a high rate; it is a number that "
            f"has stopped being one, and the likeliest thing wearing its "
            f"name is a *count* of null picks, which the process's own "
            f"law refuses to let out and this value refuses to receive "
            f"(feature 269, prd §4.4)"
        )
    return narrowed


def _require_depth_past_flip_errors(value: object) -> int:
    """Narrow Type-B's metric to a genuine non-negative ``int``.

    The count of error events: a whole number of explored nodes sat at
    or beyond their branch's flip, and a figure that is not a whole
    number is not a count of events.  ``bool`` is refused before the
    integer check — a ``bool`` is an ``int`` in Python's hierarchy, and
    ``True`` is not one error.  Negative is refused because the count is
    of events that happened; there is no path by which fewer than none
    occurred.  ``0`` is admitted and honored: it is the measurement of a
    campaign that crossed nothing — the state prd §11's Type-B trend is
    driving toward, and the honest answer for a Type-R campaign.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ErrorAccountingError(
            f"depth_past_flip_errors must be Type-B's metric — the count "
            f"of explored nodes at or beyond their branch's flip — as a "
            f"non-negative integer, got {value!r} "
            f"({type(value).__name__}): the figure counts error events, "
            f"each one a well deepened past a silent flip, and a value "
            f"that is not a whole number of them is not a count "
            f"(feature 269, prd §4.1.2)"
        )
    return value
