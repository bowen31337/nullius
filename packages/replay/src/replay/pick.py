"""Feature 249 — the committed pick at termination: the requirement that takes
it, and the score a policy earns that never emits one.

app_spec.xml, "Replay Engine", feature 249 (``depends_on=248``): *System
requires the committed pick from the policy at termination, which returns
negative infinity when none is emitted.*  docs/nullius-tech-architecture.md
§10.1 shows the two lines this module is — the replay's last act and the answer
it hands back:

    pick = policy.commit()                                  # MANDATORY
    return score(pick, book, epoch, revealed, rounds)

Feature 248 owns the loop above those lines and stops at its edge — *"the loop
returns the revealed set and stops; the committed pick ``policy.commit()`` and
the negative-infinity-on-none are 249's, over this loop's return"*
(additions_spec_248).  Feature 222 owns the *protocol* those lines stand on —
the commit call naming one node, the one-way door, the frozen read — in the
policy-runtime member.  This module owns the replay's half of the same moment:
the runtime's terminal requirement, the read that takes the pick the policy
emitted, and the score answered for a policy that emitted none.

**The pick is required from the policy, through the door the policy committed
through.**  In the wired runtime ``pick = policy.commit()`` is not a method
this member may call — a member never imports another member, so the authored
policy's own object is unnamed here — it is the episode's commit record
(feature 222's :class:`~policy_runtime.EpisodeCommit`, the door
``question.commit(node_id)`` closes) read **at termination**, which is the
moment the feature names.  So :func:`committed_pick` takes the record
duck-typed and performs the termination read itself, through exactly one verb
— ``terminate()``, the record's idempotent freeze-and-snapshot — the same
one-verb stance the round loop takes toward the question (its ``probe_batch``)
and the transition toward the tree (its recorded edges).  The frozen read is
then read through exactly one attribute: ``pick``, absent-or-present, and a
read that *cannot say* is refused rather than scored — see below.  An
``isinstance`` against the policy-runtime record is impossible for the reason
every seam in this member ducks: the module loader imports a member under a
synthetic name and re-executes it, so the record ``create_app()``'s wiring
produces may be a second class object of the same name.

**The answer is the pair the store already shaped.**  :class:`TerminalPick`
carries the pick (absent-able) and the score (always present) — the two
columns migration 0109 legislates for ``replay_score``: ``score REAL NOT
NULL`` because *"a row in this table is the record of a completed scoring,
and a null score would be a scoring that did not happen"*, and
``committed_pick UUID`` nullable because *"a candidate that was scored but
not selected has no committed pick to record… The column is the policy's
decision, and a decision that was never made must stay distinguishable from
one that was."*  The answer is that law as a value, which is why feature 255's
writer and §913's log record (*"every replay emits ``(policy_version,
world_id, beta, score, committed_pick)``"*) consume this object rather than
re-deriving the pair.  Frozen, because an answer that could move would be a
score that changed after it was read.

**−∞, not a refusal — the load-bearing choice, and not this module's to
re-decide.**  A policy that terminates without committing is *scored*, not
rejected, and the number is the total order's floor.  The documents state the
sentence twice on the policy side (docs §598: ``question.commit(node_id)  #
REQUIRED; omitting scores −inf``; prd §438: *"``commit()`` is mandatory. A
policy that terminates without committing scores ``−∞``"*), feature 222 built
the policy-runtime half on it, and this module is the replay's half of the
same stance: an exception would take the policy *out of the comparison — the
same slot a crashed policy occupies, so the revision loop (prd §C5's argmax
over ``M`` revisions) could not tell a policy that would not commit from one
that faulted — and ``None`` or NaN is not a score (a null score is a scoring
that did not happen, migration 0109's own words, and a NaN compares false
against everything, silently dropping out of every argmax).  The miss stays
*in* the comparison: below every committing policy's score however bad that
pick was, and equal to every other miss.

**The scorer is handed in, and never called on the miss.**  The score of a
made pick is the replay's arithmetic — §10.3's ``score(pick, book, epoch,
revealed, rounds)`` — none of which this module owns: the caller curries the
book, the epoch and the rounds it holds, and the revealed set feature 248's
loop returns *for exactly this currying*.  Taking a *callable* rather than a
number is the design point feature 222 stated for its side of the seam and
this module keeps for its own: on the miss there is no value to pass and no
call to make, so there is no seam through which a fabricated pick could reach
the scorer — the miss path calls nothing, spends nothing and answers
:data:`NON_COMMITTING_SCORE`.  A scorer that *raises* is the arithmetic's own
failure and propagates unchanged, exactly as 222 lets a raising scorer speak
for itself: it is not this member's vocabulary to translate.

**The refusals are the ask, never the miss.**  :class:`~replay.ReplayPickError`
(the member's eighth sibling) carries the malformed *ask*, and the repair is
on the caller's side of the call:

* a **non-callable scorer** — the answer's wiring; refused rather than
  escaping as a bare :class:`TypeError` from inside the call;
* a **carrier with no callable ``terminate``** — not an episode's commit
  record, so the termination read cannot be performed through it (a frozen
  read handed where the record belongs is this refusal: the requirement is
  the *act* that takes the read, and a value someone else froze answers
  itself);
* a **termination read that carried no ``pick`` at all** — the dangerous one:
  a read that cannot say whether a pick was made must not be scored as a
  miss, because ``-inf`` for a broken wiring would hide a broken caller from
  every world in the pool — the same argument the member's other non-nestings
  make for their refusals;
* a **``terminate()`` that raised** — translated into this member's
  vocabulary and chained to the carrier's own refusal, so a caller catching
  the replay's base class still catches a record that could not be read.

The two argument checks fire **before the record is touched**, and the order
is load-bearing rather than tidy: the requirement's one act spends a one-way
door (the record's termination close, feature 222's), and a refusal that had
terminated first would freeze the episode with no score and no retry — the
caller could not fix the scorer and ask again, because the door only closes.
A refused ask terminates nothing.  The read's own failures (no ``pick``, a
raising ``terminate``) fire where they are found, inside the act, because
that is where they exist.

**What this module deliberately does not do.**  It does not *score*: the
arithmetic is the caller's curried scorer (features 250 and 256's), and this
module routes it — calling it once, with the pick, when there is one, and
never at all when there is not.  It does not validate the pick's ``node_id``
— feature 222's :class:`~policy_runtime.CommittedPick` validates at
construction, the address seam refused the pick through the tree's own
vocabulary, and a second statement here would be a second place the same law
could drift (the stance :mod:`replay.returns` takes toward feature 174's
array arithmetic).  It does not validate the scorer's *return*: the scorer is
the replay's own arithmetic and the fitness of its output for the store is
feature 255's writer's read — each seam validates what it reads, and
:mod:`policy_runtime.commit` returns its scorer's answer whole for the same
reason.  It does not require the committed node be *revealed* — a commit
names a node, it does not read one (feature 222's deliberate non-law, pinned
there by test), and this requirement consults no prefix at all: the walk's
revealed set is the scorer's business, curried by the caller.  It does not
*screen*: whether an authored policy reaches ``commit()`` on every
terminating path is feature 230's static admission check, run before an
episode begins; this is the runtime moment — a source can pass 230 and still
terminate uncommitted (a runtime branch the analysis could not prove), which
is exactly the case the −∞ exists to score.  And it does not *persist*:
``replay_score`` is feature 255's row, written from this value.

The read is idempotent because the record's ``terminate()`` is (feature
222's law: two calls answer equal values), so requiring twice over one
record answers equal :class:`TerminalPick` values — the scorer runs per call,
and a pure scorer makes the whole act pure, §12's determinism contract read
on the terminal act: two requirements of one terminated episode are one
answer.

The composed spelling is :meth:`replay.ReplayEngine.pick` on 245's stateless
facade.  No second ``replay`` component, no ``replay``-prefixed sibling —
the member's one ``@register`` contribution stays the facade, and this
feature adds a verb to it, the law the package ``__init__`` states.  No
store, no clock, no environment: the module is pure Python state over the
record and the scorer it is handed.

Stdlib only — ``collections.abc``, ``dataclasses`` and ``typing`` beside the
member's own error — so importing this member on every factory scan costs
composition nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import ReplayPickError

__all__ = [
    "NON_COMMITTING_SCORE",
    "TerminalPick",
    "committed_pick",
]

#: The score a policy earns by terminating without committing — the total
#: order's floor, and the one number docs §598 and prd §438 both spell the
#: same way ("omitting scores −inf"; "a policy that terminates without
#: committing scores ``−∞``").  The same floor, the same *name* and the same
#: value, feature 222 spells in the policy-runtime member
#: (``policy_runtime.NON_COMMITTING_SCORE``); it is spelled again here because
#: a member never imports another member, and the two spellings are pinned
#: equal by the wiring suite — one fact, two members, one value everywhere,
#: and not a fresh ``float("-inf")`` at every seam that could drift into a
#: ``None`` or a NaN on a refactor.
#:
#: Deliberately ``-inf`` rather than a sentinel object: it must compare
#: against real scores (below every one of them, whatever the epoch's IR
#: arithmetic produced), tie with every other miss (so the argmax reads two
#: non-committers as equally last rather than ordering them by accident), and
#: survive the store's ``REAL`` column, and Python's own infinity is the only
#: value that does all three without a conversion at any seam.
NON_COMMITTING_SCORE: float = float("-inf")

#: Sentinel distinguishing *the read carried no ``pick`` attribute at all*
#: from *the read carried ``pick = None``* — the miss.  The two facts have
#: different repairs (fix the carrier, versus score the miss), and a seam that
#: answered one for the other would score broken wiring as a policy's honest
#: refusal to commit.
_ABSENT = object()


@dataclass(frozen=True)
class TerminalPick:
    """The replay's answer at termination — the pick, and the score it earned.

    What :func:`committed_pick` hands the runtime: the committed pick as the
    record emitted it, or its absence, beside the score that absence earns.
    Frozen, because an answer that could move would be a score that changed
    after it was read — the replay writes one row (feature 255) and one log
    record (§913) from one answer, and the row, the record and the value must
    not drift.

    The two fields are the two columns migration 0109 legislates for
    ``replay_score``, with the same polarity: ``score`` is always answerable
    — the miss answers :data:`NON_COMMITTING_SCORE` rather than nothing,
    because *"a row in this table is the record of a completed scoring"* —
    and ``pick`` is *absent* rather than fabricated, because *"a decision
    that was never made must stay distinguishable from one that was"*.

    :attr:`pick` is ``None`` for the policy that emitted no pick and the
    emitted pick whole (feature 222's :class:`~policy_runtime.CommittedPick`
    in the wired runtime — duck-typed here, never ``isinstance``-ed) for the
    policy that did.  :attr:`committed` is the boolean a caller wants when it
    is not going to read the pick itself: the log record's
    ``committed_pick`` field is written from the pick, and a caller that only
    branches on "did this revision commit" should not have to spell the
    sentinel comparison this module already owns.
    """

    #: The committed pick as the episode's record emitted it — the value the
    #: scorer was handed — or ``None`` for a policy that terminated without
    #: committing.  Absent rather than nil-valued: the miss is a decision that
    #: was never made, and it stays distinguishable from one that was
    #: (migration 0109's nullable ``committed_pick``).
    pick: Any | None

    #: The termination's score — the scorer's answer for a made pick, or
    #: :data:`NON_COMMITTING_SCORE` for the miss.  Always present, never
    #: ``None`` and never NaN: the miss is a score, which is the feature's
    #: whole point.
    score: float

    @property
    def committed(self) -> bool:
        """Whether the episode's policy emitted a pick — computed, never stored.

        ``pick is not None``, spelled for the caller that wants the fact and
        not the value: a dreaming loop logging ``(score, committed_pick)``
        per run (§913) reads the flag and the pick separately, and a caller
        that only branches on "did this revision commit" should not have to
        spell the sentinel comparison this module already owns.  Deliberately
        not a *requirement* read — an uncommitted termination is not an error
        state, and this property answers ``False`` for one the same way the
        miss answers a score: the miss is a score, not a refusal.
        """
        return self.pick is not None


def committed_pick(record: Any, scorer: Callable[[Any], float]) -> TerminalPick:
    """Require the committed pick at termination — §10.1's last lines, made to
    run.

    app_spec.xml feature 249's act as one call: perform the termination read
    on the episode's commit record, take the pick it emitted (or its absence),
    and answer the termination's score — the scorer's answer for a made pick,
    :data:`NON_COMMITTING_SCORE` for a miss, with the scorer **never called**
    on the miss.

    The two collaborators are duck-typed (a member never imports another
    member):

    * ``record`` — feature 222's episode commit record, the door the policy's
      ``question.commit(node_id)`` went through, read through exactly one
      verb: ``terminate()``, the idempotent freeze-and-snapshot whose answer
      carries the pick.  *At termination* is this call's own moment — the
      requirement is the act that takes the read, and a frozen read handed
      in where the record belongs is refused as what it is (the value someone
      else froze already answers itself).
    * ``scorer`` — the replay's own arithmetic, §10.3's
      ``score(pick, book, epoch, revealed, rounds)`` curried by the caller to
      the pick (the book, the epoch and the rounds it holds, and the revealed
      set feature 248's loop returns for exactly this currying).  Called
      once, with the pick, when there is one; never at all when there is not.

    Returns the frozen :class:`TerminalPick` — the pair migration 0109 shapes
    the ``replay_score`` row around — and nothing else: no revealed set, no
    round count (248 answered those), no persisted row (255's).  Pure over
    the record and the scorer it is handed, and idempotent in its answer
    because the record's ``terminate()`` is: two requirements of one
    terminated episode are one answer.

    Raises :class:`~replay.ReplayPickError` for the malformed ask — a
    non-callable ``scorer``, a carrier with no callable ``terminate``, a
    termination read that carried no ``pick`` at all (refused, never scored
    as a miss), a ``terminate()`` that raised (translated and chained) — with
    the two argument checks firing **before the record is touched**: a
    refused ask terminates nothing, because the door the act spends closes
    one way and a caller that fixes its wiring must still be able to ask.
    The *absence* of a pick is never refused: it is the score
    :data:`NON_COMMITTING_SCORE`, which is the feature's whole point.
    """
    # The scorer is refused first, before the record is touched: the answer's
    # wiring names the act's other half, and a requirement that terminated
    # the episode and then discovered it had no scorer to route would have
    # spent the one-way door on an ask it could not answer — the caller could
    # not fix the wiring and ask again, because the door only closes.  The
    # same ordering the round loop holds for its arguments (feature 248): a
    # refusal that ran the act first would have spent the thing it was
    # refusing to spend.
    if not callable(scorer):
        raise ReplayPickError(
            f"a termination's pick is scored by handing the requirement the "
            f"scorer that computes the committed pick's score, got {scorer!r} "
            f"({type(scorer).__name__}), which is not callable: the scorer is "
            f"the replay engine's own arithmetic (docs §10.1's score(pick, "
            f"book, epoch, revealed, rounds)) curried to the pick — the "
            f"caller closes over the book, the epoch, the rounds and the "
            f"revealed set feature 248's loop returns — and a scorer that "
            f"cannot be called is a wiring fault, refused here naming it "
            f"rather than escaping as a bare TypeError the member's one base "
            f"class does not catch (feature 249, docs §10.1)"
        )
    # The carrier is refused next, still before the record is touched: the
    # requirement performs the termination read through exactly one verb, and
    # a carrier with no such verb is not an episode's commit record — there
    # is no act to take through it.  A frozen read (feature 222's
    # Termination) handed in here meets this refusal too, deliberately: the
    # requirement is the act that takes the read, and a value already frozen
    # answers itself.
    terminate = getattr(record, "terminate", None)
    if not callable(terminate):
        raise ReplayPickError(
            f"the committed pick is required at termination from the "
            f"episode's commit record — feature 222's door the policy's "
            f"question.commit(node_id) went through — got {record!r} "
            f"({type(record).__name__}), which has no callable terminate(). "
            f"The requirement performs the termination read itself (docs "
            f"§10.1's `pick = policy.commit()` is the runtime's terminal "
            f"act), and it reads the record through exactly that one verb; "
            f"a frozen read already taken is a value that answers itself, "
            f"not the record the act is performed on — hand the record "
            f"(feature 249, docs §10.1)"
        )
    # The act: one termination read, then the pick it carries.  A terminate()
    # that raises is translated into this member's vocabulary and chained —
    # whatever class the record raised belongs to the record's member, and a
    # caller catching *this* member's base class must still catch an episode
    # whose termination could not be read.  The attribute read is inside the
    # same guard so a read whose `pick` explodes is named the same way rather
    # than escaping as a bare AttributeError.
    try:
        read = terminate()
        pick = getattr(read, "pick", _ABSENT)
    except ReplayPickError:
        raise
    except Exception as exc:
        raise ReplayPickError(
            f"the episode's commit record could not be read at termination: "
            f"its terminate() raised {exc!r}. The requirement takes the pick "
            f"the record emitted through that one verb (docs §10.1's "
            f"`pick = policy.commit()`), and a record whose termination read "
            f"fails names no pick a replay could require — a replay that "
            f"scored past it would be reporting an episode it never read "
            f"(feature 249, docs §10.1)"
        ) from exc
    # A read that cannot say is refused, never scored as a miss: `pick` absent
    # entirely is a different fact from `pick is None` (the miss), and the two
    # have different repairs — fix the carrier, versus score the miss.  A seam
    # that answered one for the other would hand broken wiring -inf, and a
    # caller skipping "the non-committing policy" would be silently skipping
    # every record it failed to read — the same argument the member's other
    # non-nestings make for keeping their refusals out from under broader
    # classes.
    if pick is _ABSENT:
        raise ReplayPickError(
            f"the termination read carried no pick at all: {read!r} "
            f"({type(read).__name__}) has no `pick`, so it cannot say "
            f"whether the policy emitted one. The miss this feature scores "
            f"-inf is a read that says `pick is None` — a decision that was "
            f"never made — and a read that cannot say is broken wiring, not "
            f"a policy's refusal to commit; scoring it would hide a broken "
            f"caller from every world in the pool (feature 249, docs §10.1)"
        )
    # The miss: a score, not a refusal — the total order's floor, answered
    # without the scorer being called at all.  That last property is the
    # point of taking a callable rather than a number: no value to pass, no
    # call to make, no seam through which a fabricated pick could reach the
    # scorer.  The miss stays in the comparison — below every committing
    # policy's score however bad that pick was, and equal to every other
    # miss — so the revision loop's argmax reads it as the verdict it is
    # (prd §438, docs §598).
    if pick is None:
        return TerminalPick(pick=None, score=NON_COMMITTING_SCORE)
    # The made pick: the scorer's answer, routed once with the pick as it was
    # emitted.  A scorer that raises is the arithmetic's own failure and
    # propagates unchanged — it is not this member's vocabulary to translate,
    # the same stance feature 222 takes for a raising scorer on its side of
    # the seam.
    return TerminalPick(pick=pick, score=scorer(pick))
