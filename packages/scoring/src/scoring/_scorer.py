"""Feature 265, the scorer process — the null pick rate computed inside
the one process that may read a label, with the number let out and the
labels kept in.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 265: *System
computes null pick rate inside a scorer process holding the sidecar key,
which returns the rate while labels stay in.*  docs/nullius-tech-
architecture.md §10.3 states the same law in one line (line 507):

    ``null_pick_rate`` is computed by a scorer process holding the sidecar
    key.  The number flows out; the labels do not.

This module is that process.  :class:`NullPickScorer` holds the sidecar,
:meth:`NullPickScorer.null_pick_rate` answers prd §4.4's figure — the
*"fraction of committed picks that are planted nulls"* (line 173) — and
everything else about the labels stops at the process boundary.

**Where this sits in the feature graph, and why the arrow runs one way.**
app_spec.xml gives feature 265 ``depends_on="258"`` and gives features 266
and 269 ``depends_on="265"``: the β₂ term (:mod:`scoring._nullpicks`)
charges on the rate this process answers, and the calibration figures that
follow (sensitivity and specificity, the Type-A/Type-B split) are further
answers off the same held labels.  So the computation is upstream of every
consumer, and the direction is not a preference — 258's docstring states
it as the barrier's own shape: the term *"cannot derive the rate itself,
because deriving it means reading ``is_null``, the bit §4.2 grants to
exactly one component."*  This module is where that grant lands inside the
scoring member.  prd §4.2 (line 155) and docs line 636 both spell the
grant: *"``is_null`` is visible to **exactly one component**: the replay
scorer"*; docs line 299 spells what the grant protects: *"There is no
``is_null`` column anywhere in the tree store.  Not hidden, not nulled
out, not ``SELECT``-excluded.  Absent.  The only way to learn a node's
status is to hold the sidecar key."*  Docs §16's layout gives this member
the process (line 973): ``scoring/  # objective, CVaR aggregation,
FDR_deploy (holds sidecar key)`` — the member's arithmetic half never
sees a label, and its scorer half is the one place that may.

**The barrier is the answer's type, not a promise in a docstring.**
prd §4.2 closes with the instruction *"Enforce it with a type-level
barrier, not a code review"*, and docs §10.3's line is enforced here the
only way a type can enforce it: :meth:`NullPickScorer.null_pick_rate`
answers one bare ``float``.  Not a mapping of picks to labels, not a
value carrying the count of nulls beside the rate, not an object a caller
could introspect — a number, the one number §10.3 lets out.  The process
exposes no accessor for the sidecar it holds, no ``assignment`` passthrough
and no label cache (the sidecar's own class states why the labels do not
live in a cache, and this process does not defeat it), its ``repr`` names
the class and nothing else, and its refusals name the *pick* and never the
*branch* — the discipline :mod:`nulloracle.target` states for the oracle's
own messages, and the reason a refusal may say *"the sidecar holds no
entry for node X"* (X being the caller's own committed pick) and may never
say anything about any other node.  The precedent is the oracle's KS
value (:mod:`nulloracle.ks`): it carries the *sizes* of the two samples
and not a single node id, so a caller can audit what the test saw without
the value it hands on ever naming which node was null.  A bare float is
that stance taken to its smallest expression.

**The sidecar is duck-read by the one seam the oracle already documents.**
A workspace member never imports another workspace member, and the sidecar
is the null oracle's — the AES-GCM envelope, the ``0o600`` file, the
access gate and the key reference grammar are :mod:`nulloracle`'s laws,
and a second spelling of any of them here would be a second, disagreeing
implementation of the credential path this member has no business
owning.  So the process reads the sidecar through the contract the
oracle's own target route documents (:mod:`nulloracle.target`): *"The
contract is the per-node assignment seam"* — any object with a callable
``assignment(node_id)`` answering the entry or ``None``.  The member's
suite drives that seam with a stand-in carrying exactly one ``is_null``
bit; the cross-member suite pins that the real
:class:`nulloracle.NullSidecar` satisfies it, sealed bytes and all.

**Composition reaches the sibling member at call time, never at import.**
:meth:`NullPickScorer.resolve` composes the process for the environment
it is handed by delegating to the null oracle's own
``NullSidecar.resolve`` — reached through ``importlib.import_module`` at
call time, the seam :mod:`replay.dependencies` documents for the canary
mark and :mod:`dreaming.select` for this member's own blend, for the same
two reasons both state: a member never imports another member, and the
loader imports members under synthetic names, so the *callable* is what
is wanted, never a module identity.  A workspace without the sibling, or
a deployment that names no sidecar, resolves ``None`` — the
degrade-don't-break stance every store-bound builder in this workspace
takes — and the process that *requires* a sidecar constructs one directly
or refuses to proceed, never silently scoring a world whose labels it
never read.

**The join is by canonical node id, and an unlabelled pick is refused —
never read as real.**  §7.1's sidecar schema is keyed by ``node_id``, and
the oracle canonicalizes every key to UUID text at the write; a committed
pick joins it the same way, so the seam takes the address in any text
spelling that parses as a UUID and canonicalizes to the same form —
mixed case, braces and the ``urn:`` form all join, restated here rather
than imported (a member never restates a member's *law*, but a UUID's
canonical text is :mod:`uuid`'s, and the cross-member suite pins the
agreement against the oracle's own normalizer).  A pick whose id cannot
parse is refused: it could not join the tree store's ``node.id UUID``
either, and a rate over an address no store holds is a rate over nothing.
A pick that parses but that the sidecar holds no entry for is refused
too, and the refusal is the point: the oracle's own Type-R selection
refuses a node outside the campaign's wells rather than answering
``False``, because ``False`` there means *"drawn, and left real"* — and
the rate has the same stake in the same direction.  Reading an unknown
pick as real would deflate the denominator's numerator exactly where prd
§7.1 line 327 says the calibration cannot afford it, which is the one
direction that lets a false discovery through (the same argument
:mod:`scoring._deflation` makes for refusing an understated ``K``).
Resolving a *deep* pick's label — a Type-R descendant's walk to its root,
a Type-D branch's depth against its flip — is the oracle's verb, not this
member's, and is deliberately not restated: the caller hands this process
picks whose labels the held sidecar answers, and a pick that needs the
tree to be labelled is a pick the caller resolves through the member that
may read the tree.

**The denominator is the committed picks, whole and as a multiset.**
prd §4.4's figure is a fraction *of committed picks*, so the seam takes
the committed picks themselves: feature 222's value (anything exposing
``node_id``) or the address text, the two spellings the objective's own
pick seam accepts.  A policy that emitted no pick is not in the
denominator at all — the miss is a score (−∞, feature 222's
``NON_COMMITTING_SCORE``, feature 249's floor), not a pick, and feature
255's nullable ``committed_pick`` column keeps the two distinguishable —
so the caller hands the picks that were committed and this seam counts
them.  Two worlds may commit to one node; both picks count, because the
figure is per pick and not per distinct node.  An ask with no picks at
all is refused: a rate over an empty denominator is undefined, not
``0.0`` — the same law the bootstrap member's ground-truth rates take
toward an empty class and :mod:`scoring._switches` takes toward an
unlabelled horizon, and the opposite of a clean campaign's honest
``0.0``, which is a *measurement* this seam answers when there are picks
and none of them null.

**Deterministic, and pure in everything but the one read.**  The same
sidecar and the same picks answer the same rate to the last bit — one
count, one division, no clock, no store, no environment inside the verb —
and the fixtures that pin the law are dyadic so the quotients are exact
in binary.  The one thing the verb does beyond arithmetic is read the
sidecar, per pick, through the seam above; that read is the process's
whole reason to exist, and everything it touches stays inside the call.

**What this law deliberately does not do.**  It does not reweight the
rate to a deployment base rate — ``FDR_deploy`` at π₀ ≈ 0.9 is feature
267's arithmetic over figures feature 266 computes, and the raw rate is
what β₂ charges on (docs §10.3 lines 509-515).  It does not compute
sensitivity or specificity (feature 266) or the Type-A/Type-B split
(feature 269); those are later answers off the same held labels and will
land as their own verbs on this process or beside it.  It persists
nothing — the ``replay_score`` row is the replay plugin's (feature 255),
and it already carries the score and the β the rate moved.  It does not
void anything: §7.4's ``halt_dreaming()`` belongs to the detectability
guard's verdict, and a rate is a measurement, not a verdict.  And it does
not *stop* anything — the process answers numbers; what the loop does
with them is the loop's law.

Stdlib only, and import-cheap: :mod:`uuid` for the join, :mod:`importlib`
at call time for the sibling, :mod:`collections.abc` and :mod:`typing`
for the shapes, and the member's own error — no third-party import at
module scope, so the factory's scan (which imports this package to fire
its ``@register`` builders) pays nothing for the law.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from .errors import NullPickRateError

__all__ = [
    "SCORER_COMPONENT_NAME",
    "NullPickScorer",
]

#: The component name this member's scorer process registers under — the
#: key a composed :class:`~app.module_loader.Application` carries the
#: process at, and the name the sibling seat in the app namespace
#: (``src/app/modules/scoring/scorer.py``) asks for.  A second name rather
#: than a second component under ``"scoring"`` because the two are
#: different things on different lifecycles: the objective is arithmetic
#: that never degrades, the scorer process is deployment state that
#: composes only where a sidecar is configured — the same split the
#: bootstrap member took for its pool (``bootstrap-pool`` beside
#: ``bootstrap``) and the null oracle for every store after its sidecar.
SCORER_COMPONENT_NAME = "scoring-null-pick-rate"


class NullPickScorer:
    """§10.3's scorer process: it holds the sidecar, and it answers the
    rate.

    Constructed with the sidecar-holding object — duck-read by its one
    ``assignment(node_id)`` seam, the contract :mod:`nulloracle.target`
    documents for the same object — and answering
    :meth:`null_pick_rate` for the committed picks a caller hands over.
    The class carries no other public surface, and that is the feature's
    own sentence made structural: *which returns the rate while labels
    stay in*.  A second method that handed back a label, a count of
    nulls, or the sidecar itself would be a second place the barrier
    leaks, and the process that grew one would be the process §4.2 was
    written to contain.

    Hand-written with ``__slots__`` and no ``__dict__``, so there is no
    shadow state beside the held sidecar for a caller (or a subclass) to
    park a label in — the same guarantee the runtime's own records make
    for the state they front.  Not frozen: the process is a holder, not a
    value, and the sidecar it holds is live deployment state whose file
    is read per ask, never cached (the sidecar's own class states the
    law, and this process does not defeat it).
    """

    __slots__ = ("_sidecar",)

    def __init__(self, sidecar: object) -> None:
        # Duck-checked rather than isinstance-guarded, for the reason the
        # oracle's own target route states: the loader imports members
        # under synthetic names, so the *composed* sidecar component is
        # structurally a NullSidecar but never the same class object a
        # direct import yields — an isinstance here would refuse the very
        # component the factory hands out.  The contract is the per-node
        # assignment seam, and that is what is checked.
        assignment = getattr(sidecar, "assignment", None)
        if not callable(assignment):
            raise NullPickRateError(
                f"the scorer process holds a sidecar — something with an "
                f"assignment(node_id) seam — and this carrier exposes no "
                f"callable one (got {assignment!r} on a "
                f"{type(sidecar).__name__}): hand the null oracle's "
                f"NullSidecar, or any object that answers its per-node "
                f"assignment seam, and the rate is computed inside it "
                f"(feature 265, docs §10.3)"
            )
        self._sidecar = sidecar

    # -- The verb -----------------------------------------------------------

    def null_pick_rate(self, picks: object) -> float:
        """Answer prd §4.4's fraction — the committed picks that were
        planted nulls, over all the committed picks.

        ``picks`` is the collection of committed picks the rate is taken
        over — each one feature 222's value (any object exposing a
        non-empty ``node_id``) or the address text itself, the two
        spellings the objective's own pick seam accepts, and a multiset:
        two worlds committing to one node are two picks, both counted.
        A mapping is refused (its keys are not its picks), and so is a
        bare string (one pick spelled where the collection belongs).  The
        miss is not a member of this collection at all — it is a score
        (−∞, feature 222's), not a pick — so the caller hands the picks
        that were committed and the seam counts what it is handed.

        The labels are read inside, per pick, through the held sidecar's
        ``assignment`` seam; the answer is one bare ``float`` and nothing
        label-shaped crosses the boundary in either direction.  Refuses,
        with :class:`~scoring.NullPickRateError` and nothing partial, in
        this order — each refusal a different fact with a different
        repair, which is why the order is stated:

        1. an ask that is not the picks themselves (a mapping, a bare
           string, or nothing iterable at all) — wiring faults at the
           caller;
        2. an ask with no picks at all — a rate over an empty
           denominator is undefined, not ``0.0``;
        3. a pick that names no node, or whose node id is not a UUID —
           an address that cannot join the sidecar's keys cannot join the
           tree store's ``node.id`` either;
        4. a committed pick the sidecar holds no entry for — its null
           status is unknown, and reading it as real would deflate the
           one figure the term exists to charge (the direction
           :mod:`scoring._deflation` refuses an understated ``K`` for);
        5. an entry whose ``is_null`` is not a genuine bool — the same
           refusal the oracle's assignment layer makes at the write and
           its target route makes at the read, because ``bool("false")``
           is ``True``;
        6. the sidecar's own failure while being read — absent, locked,
           or undecryptable — translated into this member's vocabulary
           with the original chained, so a caller's single
           ``except ScoringError`` catches the whole member and the
           oracle's refusals never escape wearing this seam's name.

        Deterministic and pure in everything but the one read: the same
        sidecar and the same picks answer the same rate to the last bit —
        one count, one division — and the read touches nothing but the
        picks it was asked about.
        """
        asked = _the_committed_picks(picks)
        if not asked:
            raise NullPickRateError(
                "null_pick_rate is a fraction of committed picks, and this "
                "ask carried none: a rate over an empty denominator is "
                "undefined, not 0.0 — a campaign that committed to no null "
                "anywhere answers 0.0, but only because there were picks "
                "and none of them were null, which is a measurement this "
                "seam cannot invent for a set it was not handed (feature "
                "265, prd §4.4)"
            )
        # The ask is validated whole before the first label is read: a
        # refusal below names what was handed in, and the labels are
        # touched only for an ask that could be answered.
        nodes = [_canonical_node_id(_pick_node_id(pick), pick) for pick in asked]
        nulls = 0
        for node in nodes:
            if _label_of(self._sidecar, node):
                nulls += 1
        return nulls / len(nodes)

    # -- Composition --------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> NullPickScorer | None:
        """The scorer process this environment names, or ``None`` when it
        names no sidecar.

        Delegates the whole question to the null oracle's own
        ``NullSidecar.resolve`` — the path (``NULL_SIDECAR_PATH`` or the
        lake), the key (``NULL_SIDECAR_KEY_REF``) and the service account
        (``NULL_SIDECAR_SERVICE_ACCOUNT``) are that member's laws, and
        restating any of them here would be a second, disagreeing
        implementation of the credential path — reached through
        ``importlib`` at call time because a member never imports another
        member (the seam :mod:`replay.dependencies` documents for the
        canary mark), and never at module scope because the factory's
        scan imports this package in every process, including the ones
        with no sidecar to hold.

        **Never raises.**  A workspace without the sibling member, and a
        deployment that names no usable location and key, both resolve
        ``None`` — the degrade-don't-break stance every store-bound
        builder in this workspace takes, and the reason the member's
        builder can call this on every ``create_app()`` without putting
        its environment under every unrelated feature's composition.  The
        consequence is the one the null oracle's own sidecar builder
        states: *no sidecar is configured* and *the sidecar is broken*
        are different facts, and only the second may ever be quiet.  A
        process that requires the labels asks directly — constructs the
        scorer over a sidecar it resolved itself, where the oracle's
        named :class:`~nulloracle.errors.SidecarKeyError` is the right
        answer — rather than proceeding rateless on a ``None`` this
        method honestly reported.
        """
        sidecar = _held_sidecar(env)
        return None if sidecar is None else cls(sidecar)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Names the process and nothing it holds: the sidecar's path is
        # the oracle's to log (it is not a secret), but a repr that
        # reached into the held object would be a surface on the process
        # this feature exists to keep closed.
        return f"{type(self).__name__}(<sidecar held>)"


# -- the seam's private vocabulary ------------------------------------------


def _the_committed_picks(picks: object) -> tuple[Any, ...]:
    """The ask as a tuple of picks, refusing the shapes that are not one.

    A mapping is refused because iterating one yields its keys, and a
    caller's mapping is keyed by worlds or by nodes — either way, the
    keys are not the picks, and silently rating them would compute a
    fraction over the wrong denominator with no error any test could
    see.  A bare string (and bytes, its encoding-shaped sibling) is
    refused because it is *one* pick spelled where the collection
    belongs — the same refusal the objective's pick seam makes in the
    other direction — and iterating it would rate its characters.
    Everything else must simply be iterable; the per-pick shapes are
    validated one by one after this, so a generator is consumed exactly
    once, here, into a tuple the count and the label pass share.
    """
    if isinstance(picks, (str, bytes, Mapping)):
        raise NullPickRateError(
            f"null_pick_rate is computed over the committed picks "
            f"themselves, and this ask carried "
            f"{_shape_of(picks)}: hand the picks as a collection — "
            f"feature 222's values or their node-id texts — not a "
            f"mapping (whose keys are not its picks) and not a bare "
            f"string (one pick spelled where the collection belongs) "
            f"(feature 265, prd §4.4)"
        )
    if not isinstance(picks, Iterable):
        raise NullPickRateError(
            f"null_pick_rate is computed over the committed picks "
            f"themselves, and this ask carried {_shape_of(picks)}, which "
            f"is not a collection of them: hand the picks as a collection "
            f"— feature 222's values or their node-id texts (feature 265, "
            f"prd §4.4)"
        )
    return tuple(picks)


def _shape_of(value: object) -> str:
    """What the refusal calls the ask's carrier, without repr'ing it.

    A repr may be enormous, and a mapping's repr would print its keys —
    node ids a caller handed in good faith — into an error message a log
    will keep.  The shape names the repair; the contents are the ledger
    of nobody's business but the caller's.
    """
    if isinstance(value, Mapping):
        return "a mapping"
    if isinstance(value, str):
        return "a bare string"
    if isinstance(value, bytes):
        return "bare bytes"
    return f"a {type(value).__name__} that is not iterable"


def _pick_node_id(pick: object) -> str:
    """One pick's node id, from either of the two spellings.

    The same acceptance the objective's own pick seam states, restated in
    this module's vocabulary because the refusals differ in what they
    repair: a non-empty string is the address itself; anything else must
    expose a ``node_id`` that is one — feature 222's ``CommittedPick``
    being the intended object, duck-typed because the loader's
    synthetic-name re-execution means an ``isinstance`` would refuse the
    very objects composition produces.  ``None`` is refused rather than
    skipped: a miss is not a committed pick, and a caller that lets one
    into the collection has handed the wrong collection — silently
    dropping it would silently shrink the denominator, the one direction
    the rate cannot afford (see :func:`_the_committed_picks`).
    """
    if isinstance(pick, bool):
        raise NullPickRateError(_not_a_pick_message(pick, "a bool"))
    if isinstance(pick, str):
        if not pick.strip():
            raise NullPickRateError(_not_a_pick_message(pick, "the empty string"))
        return pick
    node_id = getattr(pick, "node_id", None)
    if isinstance(node_id, bool) or not isinstance(node_id, str) or not node_id.strip():
        raise NullPickRateError(_not_a_pick_message(pick))
    return node_id


def _not_a_pick_message(pick: object, carried: str | None = None) -> str:
    """The refusal for a pick that names no node, naming what was carried.

    Both accepted spellings are named because the repair is at the
    caller's seam, not this one — and the miss is named too, because the
    likeliest wrong collection is the one that still holds its misses:
    a policy that emitted no pick is a score (−∞), not a denominator
    member, and the caller that filters them is the caller that knows
    which terminations committed.
    """
    described = (
        f"carried {carried}"
        if carried is not None
        else "exposes no node_id a pick could be read from"
    )
    return (
        f"the null pick rate is a fraction of committed picks, and this "
        f"element of the ask {described}: got {pick!r} "
        f"({type(pick).__name__}). Name each pick either by its address "
        f"(a non-empty node-id string) or by the committed value itself "
        f"(any object exposing node_id, feature 222's CommittedPick among "
        f"them); a miss is not a committed pick — it is the −∞ the "
        f"termination already scored — so hand the picks that were "
        f"committed, not every termination (feature 265, prd §4.4)"
    )


def _canonical_node_id(node_id: str, pick: object) -> str:
    """The pick's address in the sidecar's key spelling: canonical UUID
    text.

    §7.1's map is keyed by ``node_id`` and the oracle canonicalizes every
    key through :func:`uuid.UUID` at the write, so the join is honest only
    if the pick's address is canonicalized by the same rule — restated
    here (:mod:`uuid` is the standard library's law, not a member's), and
    pinned against the oracle's own normalizer by the cross-member suite.
    Mixed case, braces and the ``urn:`` form all join.  An id that will
    not parse is refused rather than skipped: it could not join the tree
    store's ``node.id UUID`` either, so a sidecar entry for it cannot
    exist, and a rate silently computed over fewer picks than were handed
    would be a fraction of a denominator nobody chose.
    """
    try:
        return str(uuid.UUID(node_id))
    except (ValueError, AttributeError, TypeError):
        raise NullPickRateError(
            f"the committed pick {pick!r} names node {node_id!r}, which is "
            f"not a UUID: the sidecar's entries are keyed by canonical "
            f"node-id text (docs §7.1), and an address that cannot join "
            f"the tree store's node.id cannot join the labels either — a "
            f"pick with no UUID address names no node this process could "
            f"read a label for, and skipping it would silently shrink the "
            f"denominator (feature 265, docs §7.1)"
        ) from None


def _label_of(sidecar: object, node: str) -> bool:
    """One committed pick's null status, read inside and validated.

    The single place the labels are touched: the held sidecar's per-node
    seam is asked, its answer's ``is_null`` bit is validated as a genuine
    bool (the refusal the oracle's assignment layer makes at the write
    and its target route makes at the read — ``bool("false")`` is
    ``True``, and a coerced bit here would count the wrong world), and
    the bit is returned to the count and dropped.  The entry itself —
    its seed, its block length, everything but the one bit — is never
    read, and nothing about any other node is asked.

    A foreign failure while reading (the oracle's store, access and
    decryption refusals, or a stand-in's) is translated into this
    member's vocabulary with the original chained: the caller's single
    ``except ScoringError`` must catch the whole member, and the oracle's
    error types escaping through this seam would defeat it — the
    translation law every cross-member seam in this workspace states.
    The message names the node (the caller's own pick) and never the
    branch, entry, or any label the file holds.
    """
    try:
        entry = sidecar.assignment(node)
    except NullPickRateError:
        raise
    except Exception as exc:
        # member's, and its failure vocabulary is not this seam's to
        # leak: whatever it raised (a sealed file that will not open, a
        # key that does not decrypt, permissions that admit a second
        # account, a stand-in's assertion), the fact for the caller is
        # one thing — the label could not be read — and the repair is in
        # the deployment's sidecar, not in this arithmetic.  Chained, so
        # the operator keeps the original; translated, so the caller's
        # single except keeps working.
        raise NullPickRateError(
            f"the sidecar could not be read for the committed pick "
            f"{node!r}: {exc!r} ({type(exc).__name__}). The labels live in "
            f"the null oracle's sealed file and the scorer process only "
            f"holds the key that opens it — a read that failed there is a "
            f"fact about the sidecar, not about the picks, and no rate is "
            f"invented over labels nobody could read (feature 265, "
            f"docs §10.3)"
        ) from exc
    if entry is None:
        raise NullPickRateError(
            f"the sidecar holds no entry for the committed pick {node!r}: "
            f"its null status is unknown, not real — a pick no label "
            f"answers cannot be counted in either side of the fraction, "
            f"and reading it as real would deflate the very figure prd "
            f"§7.4's calibration depends on. Hand picks whose labels the "
            f"held sidecar answers — a pick that needs the tree walked to "
            f"be labelled is the null oracle's verb, not this member's "
            f"(feature 265, prd §4.4)"
        )
    is_null = getattr(entry, "is_null", None)
    if not isinstance(is_null, bool):
        raise NullPickRateError(
            f"the sidecar's entry for the committed pick {node!r} carries "
            f"an is_null of {is_null!r} ({type(is_null).__name__}): the "
            f"bit decides which side of the fraction the pick counts on, "
            f"and a value that merely looks true or false would count it "
            f"without saying so (feature 265, docs §7.1)"
        )
    return is_null


def _held_sidecar(env: Mapping[str, str] | None) -> object | None:
    """The sidecar the environment names, through the sibling member's own
    resolution — or ``None`` when there is nothing to hold.

    ``importlib`` at call time, not an import statement, for the two
    reasons :mod:`replay.dependencies` states for the same reach: a
    member never imports another member, and the loader imports members
    under synthetic names, so what is wanted is the *object* the sibling
    resolves, never a module identity this process could pin.  A sibling
    that is absent, unimportable, or carries no ``NullSidecar`` is the
    same absence here — no sidecar to hold — and a resolution that
    answers ``None`` (a deployment that names no location and key) is
    too: both compose no scorer process, and the caller that requires
    one refuses to proceed rather than score rateless.  The sibling's
    own never-raise contract is trusted rather than re-wrapped, exactly
    as the null oracle's sidecar builder trusts the resolve it calls.
    """
    import importlib

    try:
        oracle = importlib.import_module("nulloracle")
    except Exception:  # noqa: BLE001 - a member that is not scanned, or
        # cannot be imported, is the same absence for this process: no
        # sidecar to hold.  Caught broadly because the import may fail
        # for reasons this member cannot enumerate, and none of them is
        # a reason a deployment without the oracle should fail to
        # compose.
        return None
    resolved = getattr(oracle, "NullSidecar", None)
    if resolved is None:
        return None
    return resolved.resolve(env)
