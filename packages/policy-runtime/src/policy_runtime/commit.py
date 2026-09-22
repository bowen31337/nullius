"""Feature 222, the terminal commit — one call naming one node, and the score
a policy earns that never makes it.

app_spec.xml, "Exploration Policy Runtime", feature 222 (``depends_on=217``):
*System requires a commit call naming one node at termination, which returns
negative infinity for a non-committing policy.*  docs/nullius-tech-architecture.md
§598 states the law where the API lists it — ``question.commit(node_id)  #
REQUIRED; omitting scores −inf`` — §478 shows the one call site it exists for,
the replay loop's last act after the rounds have run (``pick = policy.commit()
# MANDATORY``), and docs/alpha-engine-prd.md §438 gives the sentence the whole
feature hangs on: *"``commit()`` is mandatory. A policy that terminates without
committing scores ``−∞``."*

**The commit is the terminal act, and this module is its runtime half.**
Everything else in the ``question.*`` surface is *during*: observed (217) reads
the prefix, the frontier and meta (218/219) shape it, probe_batch (220) spends
budget to extend it, budget_remaining (221) meters it.  The commit is *after*:
the policy has stopped selecting batches, the episode is closing, and once it
names the node it would deploy — the pick prd §318 scores as
``IR_oos(π^m.commit() | book_t)`` — the exploration is over and the answer is
in.  Exploration is the means; the commit is the answer, and the replay's score
is a function of that answer and nothing else (§478: ``score(pick, book,
epoch, revealed, rounds)`` names the pick first).

**−∞, not a refusal — the load-bearing choice.**  A policy that terminates
without committing is *scored*, not rejected, and the number is the total
order's floor.  Three designs were available and only one ranks the miss
honestly:

* **−∞, as built** — the non-committing policy stays *in* the comparison,
  deterministically last: below every committing policy's score however bad
  that pick was, and equal to every other non-committing one.  The dreaming
  loop's argmax over ``M`` revisions (prd §C5) then reads the miss as the
  verdict it is — this revision is worse than committing badly — and feeds the
  revision prompt that says so;
* **an exception** — would take the policy *out* of the comparison, which is
  the same slot a crashed policy occupies: the revision loop cannot tell a
  policy that would not commit from one that faulted, and a caller that did
  not wrap the termination in a try/except loses the whole cycle.  The
  documents refuse this spelling twice — "omitting *scores* −inf" (§598), "a
  policy that terminates without committing *scores* ``−∞``" (prd §438) — the
  miss is a score, and the sentence is the feature;
* **``None`` or NaN** — a null score is not a score (the store's own law:
  ``replay_score.score`` is ``NOT NULL`` because "a row in this table is the
  record of a completed scoring", migration 0109), and a NaN compares false
  against everything, so it would silently drop out of every argmax and sort
  arbitrarily beneath the ones it dropped — an unordered miss is a miss the
  loop cannot learn from.

The store already agrees about the shape of the miss: ``replay_score.
committed_pick`` is nullable precisely because "a candidate that was scored but
not selected has no committed pick to record… The column is the policy's
*decision*, and a decision that was never made must stay distinguishable from
one that was" (migration 0109).  :class:`Termination` is that shape as a value
— the pick absent, the score present at :data:`NON_COMMITTING_SCORE`.

**One commit, naming one node, and then the door is closed.**  The feature's
own words carry the cardinality — *a commit call naming one node* — and the
record enforces it as a one-way door, the same shape :class:`EpisodeBeta`
(feature 226) draws around the scalar and :class:`contract.MarketWindow`
(feature 10) around a decision time:

* **a call that names no node, or several** — ``None``, a blank string, a
  list or tuple of ids, a ``bool`` — is refused with
  :class:`~policy_runtime.PolicyCommitError`, naming what the call carried;
* **a second commit** is refused, naming the pick already made: the score is
  earned under the pick as it stood at termination, and a policy that could
  re-commit would be re-deciding after the fact — the terminal act is one act;
* **a commit after** :meth:`EpisodeCommit.terminate` **has read the episode**
  is refused: termination is the moment the requirement is *read*, and a pick
  landing after it would be a pick the score never saw.  A refused attempt
  commits nothing — the record is left exactly as it was, so a policy that
  fumbles one commit (a misspelled id, a batch) may still make its one call.

**A record over the question, not a method on it.**  The question (feature
217) deliberately holds one piece of episode state — the reveal set, and
nothing else — because everything else it answers is a pure function of
``(tree, node_id)``.  The commit protocol is a different state machine: one
write, ever, then a freeze, then a read that scores.  Putting it on the
question would give the object whose whole design is "the runtime's read
side" a terminal mutation it cannot validate half of (it has no notion of
termination), so it lives here as :class:`EpisodeCommit`, composed over the
question's public address seam — and the record *may* hold the question for
the same reason the question may hold the tree: it is the runtime's object,
never the policy's.  What a policy is handed is the prefix view (223) or the
answer surface (224); this record is what the runtime holds on the other side
of that hand-off, and the one act it accepts is the act those objects exist
to precede.

**The address seam is the tree's, unchanged.**  A commit names a node the
episode's tree holds, and the refusal for a node it does not hold is the
tree's own :class:`~policy_runtime.PolicyAddressError` — raised by the same
seam ``reveal`` refuses through (``tree.node``), propagated unchanged, because
it is one contract read at two verbs: a policy reveals cells it was shown and
commits to a node the tree holds, and the tree is the one place that knows.
The seam is duck-typed for the reason every seam in this member is: the module
loader imports the member under a synthetic name and re-executes it, so a
question this process composed may be a second
:class:`~policy_runtime.PolicyQuestion` class object, and an ``isinstance``
would refuse the very objects composition produces.

**What this law deliberately does not do.**  It does not require the committed
node be *revealed*: a commit names a node, it does not read one, and a policy
that commits to a cell it never probed has gained no information the barrier
withholds — it has only made a pick the out-of-sample score will punish, which
is the honest outcome rather than a refusal this member invented (the barrier
governs reads — 217's accessor, 223's view, 224's surface — and the docs'
replay scores whatever node the pick names, §478).  It does not *score*: the
IR of the committed pick is the replay engine's arithmetic (§10.3), so
:meth:`Termination.score` takes the scorer as an argument and never calls it
on a pick that was never made — the property admission.py states as the
repair for an unreachable commit ("a policy that can score on a pick it never
made"), enforced here from the other side.  And it does not *screen*: whether
a policy's authored source reaches ``commit()`` on every terminating path is
feature 230's static check, run before an episode begins; this is the runtime
moment — the same before/during split the guard pair (225) draws against the
admission gate, and the reason a source can pass 230 and still terminate
without committing (a runtime branch the analysis could not prove), which is
exactly the case the −∞ exists to score.

**Honest limits, stated as this member states every other one.**  How a
policy's authored code *reaches* the commit verb is the deployment's wiring —
a surface configured with a commit answer, a callable the runner holds out for
the terminal act — and this member owns the protocol, not the wiring:
whatever route lands on :meth:`EpisodeCommit.commit` lands on the same
cardinality, the same one-way door and the same −∞.  :meth:`terminate` is
idempotent and pure — it freezes the record's door and snapshots the pick, and
two calls answer equal values — so the freeze bites the commit verb and
nothing else; a runtime that never calls it has still enforced every law the
commit itself carries (the second-commit refusal is not conditional on
termination).  And the record is Python state, not a persisted row: the
``replay_score`` row the miss produces is written by the replay, from this
value, exactly as migration 0109 shapes it.

Stdlib only, and import-cheap: :mod:`dataclasses`, :mod:`collections.abc` and
the member's own error — no third-party import at module scope, so the
factory's scan (which imports this package to fire its ``@register`` builder)
pays nothing for the law.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import PolicyCommitError

__all__ = [
    "NON_COMMITTING_SCORE",
    "CommittedPick",
    "EpisodeCommit",
    "Termination",
    "episode_commit",
]

#: The score a policy earns by terminating without committing — the total
#: order's floor, and the one number docs §598 and prd §438 both spell the
#: same way ("omitting scores −inf"; "a policy that terminates without
#: committing scores ``−∞``").  Named because it is *shared*: the termination
#: answers it, the replay writes it into ``replay_score.score``, and a caller
#: comparing revisions compares against it — one spelling, so the miss is one
#: value everywhere and not a fresh ``float("-inf")`` at every seam that could
#: drift into a ``None`` or a NaN on a refactor.
#:
#: Deliberately ``-inf`` rather than a sentinel object: it must compare
#: against real scores (below every one of them, whatever the epoch's IR
#: arithmetic produced) and survive the store's ``REAL`` column, and Python's
#: own infinity is the only value that does both without a conversion at
#: either seam.
NON_COMMITTING_SCORE: float = float("-inf")


@dataclass(frozen=True)
class CommittedPick:
    """The one node an episode committed to — the policy's terminal answer.

    A frozen value, because the pick is a *decision* — the node the policy
    would deploy, made once at termination — and a pick a caller could move
    after the fact would not be the pick the score was earned under, the same
    guarantee :class:`~policy_runtime.GridPlan` makes for the plan a policy
    authored before a campaign.  It carries the node id and nothing else: not
    the node's in-sample observation (the score is out-of-sample by
    construction — prd §313's Change A, "scored on a sequestered epoch it has
    never observed in any world" — so an in-sample reading beside the pick
    would be a number the barrier froze, decorating the one act that must not
    read it), not the round it was made on, not the reveal set it was chosen
    from.  The pick is an address; the score it earns is a fact the scorer
    computes elsewhere.

    The id is validated at construction — a non-empty string, refused
    otherwise — so a pick that exists is a pick that names a node, whatever
    route constructed it.  Address validity (the node being *in a tree*) is
    not checked here and belongs to the seam that made the pick:
    :meth:`EpisodeCommit.commit` refuses an unknown node through the tree's
    own :class:`~policy_runtime.PolicyAddressError`, and a bare
    :class:`CommittedPick` constructed by a test or a caller is a value, not
    an episode's act.
    """

    #: The node the episode committed to — the id the commit call named.  The
    #: one address the score is earned on and the one field the store's
    #: ``committed_pick`` column persists (migration 0109).
    node_id: str

    def __post_init__(self) -> None:
        # ``bool`` is not a name, and neither is a blank: the id is the one
        # address a pick carries, and a pick without one names nothing to
        # score.  The same validation :class:`~policy_runtime.CampaignNode`
        # applies to its own id, for the same reason.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise PolicyCommitError(
                f"a committed pick must name one node by a non-empty node_id, "
                f"got {self.node_id!r} ({type(self.node_id).__name__}): the id "
                f"is the address the out-of-sample score is computed on and "
                f"the one field the store's committed_pick column persists, so "
                f"a pick that carries none names nothing to score (feature "
                f"222, docs §598)"
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"CommittedPick(node_id={self.node_id!r})"


@dataclass(frozen=True)
class Termination:
    """The episode's commit as it stood at termination — the frozen read that
    scores.

    What :meth:`EpisodeCommit.terminate` hands the runtime: the pick, or its
    absence.  Frozen, because a termination that could move would be a score
    that changed after it was read — the replay writes one row from one
    termination, and the row and the value must not drift.  The two fields the
    store's law shapes (migration 0109) are both here and both deliberate:
    ``score`` is always answerable — the miss answers
    :data:`NON_COMMITTING_SCORE` rather than nothing, because "a row in this
    table is the record of a completed scoring" — and the pick is *absent*
    rather than fabricated, because "a decision that was never made must stay
    distinguishable from one that was".

    :attr:`pick` is ``None`` for the non-committing policy and a
    :class:`CommittedPick` for the committing one, and :attr:`committed` is
    the boolean a caller wants when it is not going to read the pick itself.
    The scorer is *handed to* :meth:`score` rather than imported: the IR of
    the committed pick is the replay engine's arithmetic (§10.3's
    ``score(pick, book, epoch, revealed, rounds)``), and this value routes it
    — calling it once, with the pick, when there is one, and never at all when
    there is not.
    """

    #: The episode's committed pick, or ``None`` for a policy that terminated
    #: without committing.  Absent rather than nil-valued: the miss is a
    #: decision that was never made, and it stays distinguishable from one
    #: that was (migration 0109's nullable ``committed_pick``).
    pick: CommittedPick | None = None

    @property
    def committed(self) -> bool:
        """Whether the episode's policy made its one commit — computed, never
        stored.

        ``pick is not None``, spelled for the caller that wants the fact and
        not the value: a replay loop logging ``(score, committed_pick)`` per
        run (§913) reads the flag and the pick separately, and a caller that
        only branches on "did this revision commit" should not have to spell
        the sentinel comparison this member already owns.
        """
        return self.pick is not None

    def score(self, scorer: Callable[[CommittedPick], float]) -> float:
        """The episode's score — the scorer's answer, or −∞ for the miss.

        The feature's second clause, as one method: a policy that committed
        is scored by handing its pick to ``scorer`` — the replay engine's
        ``score(pick, book, epoch, revealed, rounds)``, curried to the pick a
        termination carries — and a policy that terminated without committing
        answers :data:`NON_COMMITTING_SCORE` *without the scorer being called
        at all*.  That last property is the point of taking a callable rather
        than a number: a caller cannot accidentally score a pick that was
        never made, because there is no value to pass and no call to make —
        the miss path has no seam through which a fabricated pick could
        reach the scorer.

        A ``scorer`` that is not callable is refused with
        :class:`~policy_runtime.PolicyCommitError` rather than escaping as a
        bare :class:`TypeError` from inside the call — a wiring fault the
        caller should hear named, on every path, the error-vocabulary
        discipline every member seam keeps
        ([[error-vocabulary-at-member-seams]]).  A scorer that *raises* is
        the replay engine's own failure and propagates unchanged: it is not
        this member's vocabulary to translate, exactly as the question lets
        the tree's :class:`~policy_runtime.PolicyAddressError` speak for
        itself.
        """
        if not callable(scorer):
            raise PolicyCommitError(
                f"a termination is scored by handing it the scorer that "
                f"computes the committed pick's score, got {scorer!r} "
                f"({type(scorer).__name__}), which is not callable: the "
                f"scorer is the replay engine's own arithmetic (docs §10.1's "
                f"score(pick, book, epoch, revealed, rounds)) routed through "
                f"this seam, and a scorer that cannot be called is a wiring "
                f"fault — refused here, naming it, rather than escaping as a "
                f"bare TypeError the member's one base class does not catch "
                f"(feature 222, docs §598)"
            )
        if self.pick is None:
            # The headline case: the policy terminated without committing, and
            # the system *scores* it — −∞, the floor every committing policy's
            # score sits above — rather than refusing, so the dreaming loop's
            # argmax ranks the miss last instead of dropping it from the
            # comparison (prd §438, docs §598).
            return NON_COMMITTING_SCORE
        return scorer(self.pick)


class EpisodeCommit:
    """The runtime-side record of an episode's terminal commit — the door the
    one call goes through.

    Holds the question it fronts (the runtime's object, never the policy's —
    the same audience split that lets the question hold the tree), the pick
    once one is made, and the closed door after termination.  Everything the
    feature requires is enforced *here*, at the act:

    * :meth:`commit` takes exactly one node id — a call that names no node or
      several is refused, naming what it carried;
    * a node the episode's tree does not hold is refused by the tree's own
      :class:`~policy_runtime.PolicyAddressError`, through the same seam
      ``reveal`` refuses through;
    * a second commit is refused, naming the pick already made — the terminal
      act is one act, and the score is earned under the pick as it stood;
    * after :meth:`terminate` has read the episode, the door is closed: a
      commit landing later would be a pick the score never saw.

    A refused attempt commits nothing — the record is left exactly as it was
    — so a policy that fumbles its one call (a misspelled id, a batch) may
    still make it.  The *absence* of a call is not the record's business at
    all: an episode that reaches termination uncommitted is a
    :class:`Termination` with no pick, scored −∞ by :meth:`Termination.score`
    — the miss is a score, not an error, which is the feature's whole point.

    Hand-written with ``__slots__``, like :class:`~policy_runtime.PolicyQuestion`
    (the runtime-side precedent): the record carries no ``__dict__``, so there
    is no shadow state beside the door, and no attribute protocol guard — the
    runtime may trust itself with its own record exactly as it may with its
    own question.
    """

    __slots__ = ("_pick", "_question", "_terminated")

    def __init__(self, question: Any) -> None:
        # Duck-typed, not ``isinstance``: the module loader imports the member
        # under a synthetic name and re-executes it, so a question this process
        # composed may be a second PolicyQuestion class object, and an
        # ``isinstance`` would refuse the very objects composition produces —
        # the same stance the question's own tree check and prefix.py's
        # observed check take.  The demand is the address seam the commit
        # refuses through: a public ``tree`` carrying a callable ``node``.  A
        # bare CampaignTree has ``node`` but no ``tree`` of its own, so handing
        # the tree where the question belongs is refused as what it is.
        tree = getattr(question, "tree", None)
        node_of = getattr(tree, "node", None)
        if not callable(node_of):
            raise PolicyCommitError(
                f"a terminal commit fronts a question — got {question!r} "
                f"({type(question).__name__}), which exposes no address seam "
                f"(a tree, readable as question.tree, carrying a callable "
                f"node()): the commit names a node the episode's tree holds "
                f"and is refused through the same seam reveal refuses "
                f"through, so an object that cannot address a node names no "
                f"node a policy could commit to (feature 222, docs §598)"
            )
        self._question = question
        self._pick: CommittedPick | None = None
        self._terminated = False

    # -- the one write -----------------------------------------------------

    def commit(self, node_id: str) -> CommittedPick:
        """Make the episode's one commit — name one node, and close the door.

        The feature's verb, and the only write this record accepts.  The
        checks are ordered by what the caller needs to hear:

        * **the door first** — a commit after :meth:`terminate` has read the
          episode is refused as such, whatever it names, because the score
          was already read without it;
        * **one act** — a second commit is refused naming the pick already
          made: the pick is what the out-of-sample score is computed on, and
          a policy that could re-commit would be re-deciding after the fact;
        * **one node** — a call that names no node or several (``None``, a
          blank, a list or tuple of ids, a ``bool``) is refused, naming what
          it carried, because the feature's own sentence is *"a commit call
          naming one node"*;
        * **an address the tree knows** — the node is resolved through the
          question's tree, and an id the tree does not hold is refused by the
          tree's own :class:`~policy_runtime.PolicyAddressError`, the same
          refusal from the same seam ``reveal`` raises it from.

        Returns the :class:`CommittedPick` the call made — the value the
        termination will score — and a refused call returns nothing and
        changes nothing: the record is left exactly as it stood, so the one
        call a policy has is still there to make after a fumbled attempt.
        """
        if self._terminated:
            raise PolicyCommitError(
                "the episode has terminated and its commit door is closed: a "
                "commit landing now would be a pick the score never saw, "
                "because terminate() has already read the episode's commit "
                "into the termination the scorer consumes (feature 222, docs "
                "§598). Termination is the moment the requirement is read — "
                "commit before it"
            )
        if self._pick is not None:
            raise PolicyCommitError(
                f"an episode commits once, naming one node, and this episode "
                f"has already committed to {self._pick.node_id!r}: the "
                f"out-of-sample score is computed on the pick as it stood at "
                f"termination, and a second commit would be the pick "
                f"re-decided after the fact — the terminal act is one act "
                f"(feature 222, docs §598)"
            )
        if not isinstance(node_id, str) or not node_id.strip():
            raise PolicyCommitError(_not_one_node_message(node_id))
        # The address seam — the tree's own refusal, from the same place
        # reveal() raises it.  Not caught and not translated: it is one
        # contract read at two verbs, and the tree is the one place that
        # knows (the same stance PolicyQuestion.reveal takes unchanged).
        self._question.tree.node(node_id)
        pick = CommittedPick(node_id=node_id)
        self._pick = pick
        return pick

    # -- the reads ---------------------------------------------------------

    @property
    def pick(self) -> CommittedPick | None:
        """The pick the episode has made so far — ``None`` until the one
        commit lands.

        The live read, for the runtime that wants the pick before it
        terminates the episode (a log line, a progress report): ``None`` is
        the honest answer until the call is made, and the frozen snapshot the
        score is computed from is :meth:`terminate`'s, not this one.
        """
        return self._pick

    @property
    def committed(self) -> bool:
        """Whether the episode's one commit has been made — the flag, not the
        pick.

        ``pick is not None``, spelled for the caller that branches on the
        fact.  Deliberately not a *requirement* read: an uncommitted episode
        is not an error state, and this property answers ``False`` for one
        the same way :class:`Termination` does — the miss is a score, not a
        refusal.
        """
        return self._pick is not None

    def terminate(self) -> Termination:
        """Read the episode's commit at termination — the moment the feature
        names.

        The last act of the replay after the policy has returned (§10.1's
        ``pick = policy.commit()`` standing where this read stands): freezes
        the record's door and snapshots the pick — or its absence — into a
        frozen :class:`Termination` the scorer consumes.  Idempotent and pure
        in its answer: calling it twice returns equal values, because the
        snapshot is taken from state the closed door can no longer change.

        Refuses nothing, on purpose.  Termination itself is always allowed —
        a non-committing policy terminates like any other; what its
        termination carries is no pick and a score of −∞, which is the
        feature's answer to that policy rather than this method's refusal.
        The commit door closes here and only here; every law the commit
        itself carries (cardinality, one act, the address seam) was already
        in force from construction.
        """
        self._terminated = True
        return Termination(pick=self._pick)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"EpisodeCommit(committed={self._pick is not None}, "
            f"terminated={self._terminated})"
        )


def _not_one_node_message(node_id: object) -> str:
    """The refusal for a commit call that did not name exactly one node.

    Names what the call carried — no node at all, a collection of N node ids,
    or a value that is not a name — because the repair is different in each
    case: a blank or a ``None`` is a missing argument, a collection is a
    batch spelled where one id belongs (probe_batch is the batch verb, and a
    commit is not one), and a bare object is not an address at all.  The
    feature's own sentence carries the cardinality — *"a commit call naming
    one node"* — so the refusal quotes it rather than paraphrasing it into a
    generic type error.
    """
    if isinstance(node_id, str) or node_id is None:
        carried = "no node at all"
    else:
        try:
            length = len(node_id)  # type: ignore[arg-type]
        except TypeError:
            carried = (
                f"not a node's name at all but a {type(node_id).__name__}"
            )
        else:
            if length == 0:
                carried = "no node at all"
            elif length == 1:
                carried = (
                    "a collection holding one node id, and a commit is "
                    "spelled commit(node_id) — the id itself, not a sequence "
                    "containing it"
                )
            else:
                carried = f"a collection of {length} node ids"
    return (
        f"a commit call names exactly one node, and this one carried "
        f"{carried} — got {node_id!r}: docs §598 spells the call "
        f"question.commit(node_id), one id as the call's one argument, "
        f"because the pick is one node the out-of-sample score is computed "
        f"on and a call that names several (or none) names no such node — "
        f"probe_batch is the batch verb, and a commit is not one (feature "
        f"222, docs §598)"
    )


def episode_commit(question: Any) -> EpisodeCommit:
    """Open an episode's commit record over a question — the feature's verb.

    The one factory, and the whole construction: the record fronts the
    question's address seam, accepts the episode's one commit, and is read
    once at termination. ::

        record = episode_commit(question)
        record.commit(node_id)          # the policy's terminal act
        termination = record.terminate()
        score = termination.score(ir_of_pick)

    The seam is duck-typed — a public ``tree`` carrying a callable ``node``
    is the whole of the demand — so the question this process composed under
    the module loader's synthetic name fronts a record as readily as the
    member's own, while a bare tree (which has ``node`` but no ``tree``), a
    string or a mapping is refused, naming what was wrong: the record fronts
    the *question*, because the commit is an episode's act and the question
    is where an episode's tree lives.

    Pure otherwise: no store, no clock, no interpreter state — the protocol
    is plain Python state over the question it was handed, which is why the
    record needs neither feature 225's guard extent nor feature 223's view to
    be in force.  No component and no seat: like :func:`policy_runtime.read_beta`
    (226) and :func:`policy_runtime.prefix_view` (223), the record belongs to
    the episode a replay opens, not to the composed application, so it is
    reached directly from the member.
    """
    return EpisodeCommit(question)
