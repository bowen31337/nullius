"""Feature 248 — the replay round loop: loop policy selection until no batch is
selected or the round cap is reached, which returns the revealed set.

app_spec.xml, "Replay Engine", feature 248: *System loops policy selection
until no batch is selected or the round cap is reached, which returns the
revealed set.*  It is docs/nullius-tech-architecture.md §10.1's own
``replay()``, the outer half of it — the ``while rounds < K2`` loop and the
``if not batch: break`` and the ``return revealed`` — and it is a module of
its own rather than the tail of feature 245 because 245's plan says so in as
many words: *"The loop, the round cap and the 'no batch selected' termination
are feature 248's; this module owns one step."*  Feature 248 declares
``depends_on=245``, and the dependency is the shape of this module: 245 is one
transition (``child = tree.child_of(v)``), and this is the loop that takes
those transitions until the policy stops selecting or the round cap is hit,
then hands back the revealed set.

The skeleton this module completes is §10.1's own (docs §464):

    revealed = {tree.root}
    rounds = 0
    while rounds < K2:                         # the cap is this module's
        batch = policy.select(prefix_view(revealed))   # prefix-only
        if not batch:                          # no batch → terminate
            break
        for v in batch:
            child = tree.child_of(v)           # 245's transition
            if child:
                revealed.add(child)
        rounds += 1
    return revealed                            # the revealed set

**One verb, and it drives 245's transition rather than re-deriving it.**
:func:`run_replay` opens :func:`replay.transition.ReplayTransition.over` at
the tree's roots — ``revealed = {tree.root}`` becomes the tree's parentless
nodes, exactly 245's seed — and then repeats: it asks the caller-supplied
``select(question)`` for a batch, and when a batch comes back it advances the
transition by each selected node's recorded child, one
:meth:`ReplayTransition.transition` per element, until either the policy
returns no batch or ``rounds`` reaches the cap.  It returns
:meth:`ReplayTransition.prefix` — the revealed set, ascending, §12's ordering
rule — and nothing else: no count, no score, no commit.  The sentence names
one return, "the revealed set", and a loop that returned more would be
wearing feature 249's ``commit`` or feature 250/255's ``score`` — acts this
module does not own and does not perform.  Termination is the disjunction the
sentence states: ``if not batch: break`` (no batch selected — feature 3/242's
"the policy has selected no batch", the empty list ``legal_actions`` hands a
leaf) **or** ``rounds >= round_cap`` (the cap).  A loop that honored only one
would either run forever on a policy that always selects, or stop one round
short of a policy that would have selected again.

**The two collaborators arrive duck-typed, because a member never imports
another member** — not even its own past, and not the policy-runtime member
whose ``PolicyQuestion`` and authored-policy ``select`` the loop drives.  The
seam therefore reads what each collaborator *is*, never ``isinstance``-s it
(the module loader imports a member under a synthetic name and re-executes it,
so the composed ``PolicyQuestion`` this process hands out is a second class
object of the same name — an ``isinstance`` would refuse the very question
composition produces):

* **``select``** — the callable shape of ``policy.select(prefix_view(...))``.
  The loop never names ``prefix_view`` or a ``Policy`` (it owns neither and
  may not import them); the caller wires the closure — ``lambda q:
  policy.select(prefix_view(q))`` — and hands the callable in.  The loop calls
  ``select(question)`` once per round and treats a falsy answer as
  termination.  ``select`` is validated callable **before the tree is opened
  and before the first round runs**: a non-callable is refused, because a loop
  that opened a transition and read a tree and then discovered it had no
  policy to call would have spent the walk it was meant to guard against
  spending — the same ordering 245's generator refusal and 251's loader
  refusal hold (a refusal that ran first would have spent the thing it was
  refusing to spend).

* **``question``** — the read-side question (feature 217's ``PolicyQuestion``,
  the object ``prefix_view`` is built over).  The loop reads exactly one verb
  off it — :meth:`probe_batch` — and nothing else.  It does not build a prefix
  view (223's), does not read ``observed``/``legal_actions``/``meta``/
  ``budget`` (the policy's, through the surface the caller supplies), and does
  not reveal on the policy's behalf (220's).  It syncs the question's reveal
  set to the transition's revealed set, and that is the whole of its demand on
  the question.  A carrier with no callable ``probe_batch`` is refused in the
  member's vocabulary, naming what arrived.

**The reveal-set reconciliation — the load-bearing detail, and the reason the
loop touches the question at all.**  The transition and the question are two
objects over one tree, each holding its own reveal set: 245's transition grows
``revealed`` by the recorded child; 217's question grows its reveal set by
``probe_batch``.  ``prefix_view(question)`` exposes only
:meth:`PolicyQuestion.observed` — the question's reveal set — so the policy
sees the prefix the question has revealed, not the prefix the transition has.
If the two sets drift, the policy is shown a frontier the walk is not standing
on.  The loop is the reconciler: it seeds the question with the roots once
(``question.probe_batch(transition.prefix())``, so the policy's first view is
the seeded prefix), and after each round it reveals into the question
**exactly the children the transition newly revealed** — the non-``None``
returns of that round's ``transition(v)`` calls — by one
``probe_batch(newly)``.  It does not re-probe the whole prefix each round:
``probe_batch`` is idempotent and all-or-nothing (a duplicate is one cell, the
whole call runs ascending, a batch naming a node the tree does not hold
reveals none of them), so re-probing would be correct but quadratic in the
campaign's nodes across the rounds — the very cost 245 refuses on its side
(per-step re-derivation measured at 76 ms for a 500-node campaign against
252's 50 ms budget).  Revealing only the new children keeps the question's
reveal set equal to the transition's revealed set at every ``select``, in
O(N) over the whole walk rather than O(rounds × N).  The reconciliation reads
``probe_batch``'s contract; it does not restate it: a node the transition
revealed is a node the tree holds (245 adds only recorded children, and
refuses a tree that records several at construction), so the sync never hands
``probe_batch`` a node outside the tree, and ``probe_batch``'s own
all-or-nothing validation is the second statement of a fact the transition
already guarantees.

**The round cap — ``K2``, and it is a required argument, validated as a
positive integer, with no default and no module constant.**  docs §10.1 writes
``while rounds < K2`` with ``K2`` a symbolic bound, never a number, and the
repository's recorded hard constraints forbid an absolute target (prd §436:
"no absolute score targets"; the admission gate 230 refuses a policy with a
hardcoded cap).  So the cap is the caller's policy decision — a deployment
chooses how many selection rounds a replay may take — and this module spells
no number for it.  ``round_cap`` is refused when it is not a positive integer
(a ``bool``, a zero, a negative, a non-``int``) **before the transition is
opened**, because a cap that is not a positive count names no loop: zero or
negative would terminate before a single round (a silent no-op that reads as a
completed replay), and a non-``int`` would break the ``rounds < round_cap``
comparison.  The refusal names the value and that the cap is a positive round
count.  This module is deliberately the *only* place a round count is compared,
so the cap cannot be restated at a second ``while`` elsewhere in the member.

**One new error sibling under ``ReplayError``, split by the repair the caller
must make:** :class:`~replay.ReplayRoundError` — the round loop's ask is
malformed, and the repair is on the caller's side of the call (pass a callable
``select``, a positive ``round_cap``, a question that fronts the campaign).  It
carries the three refusals the loop owns — the non-callable ``select``, the
non-positive ``round_cap``, the carrier with no ``probe_batch`` — because they
share one repair (fix the argument handed to :func:`run_replay`) and a caller's
single ``except ReplayError`` must catch every way the loop's ask can fail, the
discipline ``replay.errors`` states for the tree, the residence and the report.
It is **not** a child of :class:`~replay.ReplayTreeError`: a malformed ask to
the loop is a different repair from a stored tree no transition can walk, and a
caller skipping a bad tree must not silently skip the refusal that says the
loop was handed no callable policy.  A malformed *tree*, by contrast, still
surfaces as 245's :class:`~replay.ReplayTreeError` — the loop opens the
transition and lets its refusal propagate, because the tree's unfitness is a
statement about the tree, repaired at the store, not a statement about the
loop's arguments.

**What this module deliberately is not.**  It is not the selector: ``select``
is the caller's closure over the policy and ``prefix_view``, and a loop that
chose the batch would be a runtime making the policy's decision — the exact
overreach 245's docstring refuses ("a transition that chose what to reveal
would be a runtime making the policy's decision").  It is not feature 249's
commit — the loop returns the revealed set and stops; the committed pick
``policy.commit()`` and the negative-infinity-on-none are 249's, over this
loop's return.  It is not feature 250's scoring, not feature 222's score, not
feature 255's ``replay_score`` row — the loop measures no score and persists
nothing.  It is not 245's transition — it drives it, one step per selected
node, and does not re-derive a recorded child.  It is not the prefix-only
barrier (223's view, 224's answer surface, 225's armed guard): the loop trusts
that ``select`` returns a prefix-only batch — the barrier enforces that, at
the surface and the guard, not here — and does not re-police which nodes the
batch names; a batch element the tree does not hold is refused by 245's
``transition(v)``, not by a second barrier minted in the loop.  It holds no
store, opens no database, consults no clock, and is pure over the tree and the
two collaborators it is handed — the §12 determinism contract, restated for
the loop: two replays of one policy on one tree are one revealed set.

The composed spelling is :meth:`replay.ReplayEngine.run` on 245's stateless
facade.  No second ``replay`` component, no ``replay``-prefixed sibling — the
loop's behaviour is added to the facade, the law the package ``__init__``
states (one component per member name).

Stdlib only — ``collections.abc`` and ``typing`` — so importing this member on
every factory scan costs composition nothing, and the loop itself is one pass
over the selected nodes per round plus a dict read per step.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .errors import ReplayRoundError

__all__ = ["run_replay"]


def run_replay(
    select: Callable[[Any], Any],
    question: Any,
    tree: Any,
    *,
    round_cap: int,
) -> tuple[str, ...]:
    """Loop policy selection until no batch is selected or the round cap.

    app_spec.xml feature 248's ``while rounds < K2`` made to run: open
    feature 245's transition at the tree's roots, then repeat — build the
    policy's prefix from the transition's revealed set, ask the caller-supplied
    ``select(question)`` for a batch, and when a batch comes back advance the
    transition by each selected node's recorded child — until either the policy
    returns no batch or ``rounds`` reaches ``round_cap``, then hand back the
    revealed set.

    The three collaborators are duck-typed (a member never imports another
    member):

    * ``select`` — the callable shape of ``policy.select(prefix_view(...))``;
      the caller wires the closure over the policy and the prefix view and
      hands the callable in.  The loop calls it once per round and treats a
      falsy answer as termination.  Validated callable **before the tree is
      opened and before the first round runs**.
    * ``question`` — feature 217's read-side question, read through exactly one
      verb, :meth:`probe_batch`, which keeps the question's reveal set equal to
      the transition's revealed set so the policy is always shown the frontier
      the walk is standing on.
    * ``tree`` — feature 245's stored tree, duck-typed and validated as it is
      read by the transition this loop drives.

    The round cap ``round_cap`` is a required positive integer with no default
    and no module constant (docs §10.1's ``K2`` is a symbolic bound and the
    repository forbids an absolute target, prd §436); it is refused when it is
    not a positive integer (a ``bool``, a zero, a negative, a non-``int``),
    before the transition is opened.

    Returns the revealed set ascending — :meth:`replay.ReplayTransition.prefix`
    — and nothing else: no count, no score, no commit.  Pure over the tree and
    the two collaborators: two replays of one policy on one tree are one
    revealed set (§12, cq-15).

    Raises :class:`~replay.ReplayRoundError` for the loop's malformed ask (a
    non-callable ``select``, a non-positive ``round_cap``, a carrier with no
    callable ``probe_batch``), and lets feature 245's
    :class:`~replay.ReplayTreeError` propagate for a tree the transition cannot
    walk.
    """
    # The round cap is refused first, before the tree is opened: a cap that is
    # not a positive count names no loop, and a loop that opened a transition
    # and read a tree and then discovered its cap was zero would have spent the
    # walk it was meant to guard against spending — the same ordering 245's
    # generator refusal and 251's loader refusal hold.
    cap = _round_cap_of(round_cap)
    # The policy is refused next, before the tree is opened: a loop with no
    # callable to call has no act to take, and opening the transition first
    # would spend the walk the missing policy makes pointless.
    if not callable(select):
        raise ReplayRoundError(
            f"the round loop's select is a callable the loop calls once per "
            f"round — the caller's closure over the policy and the prefix view "
            f"(policy.select(prefix_view(question))) — got {select!r} "
            f"({type(select).__name__}), which cannot be called; the loop has "
            f"no batch to select without it, and a loop that opened a "
            f"transition and read a tree and then found it had no policy would "
            f"have spent the walk it was meant to guard against spending "
            f"(feature 248)"
        )
    # The question is refused next, before the tree is opened: the loop keeps
    # the question's reveal set equal to the transition's revealed set through
    # one verb, and a carrier with no such verb cannot be reconciled to the
    # walk — a mismatch the policy would see as a frontier the walk is not
    # standing on.
    probe = _probe_batch_of(question)
    # Only now is the tree opened: the cap, the policy and the question are the
    # loop's arguments, and a malformed one is refused before the transition
    # spends a read.  A malformed tree, by contrast, is feature 245's
    # ReplayTreeError — the loop opens the transition and lets its refusal
    # propagate, because the tree's unfitness is a statement about the tree,
    # repaired at the store, not about the loop's arguments.
    #
    # Imported inside the function rather than at module top: rounds.py needs
    # ReplayTransition, so a top-level `from .rounds import run_replay` in
    # transition.py would close an import cycle.  Deferring it here keeps both
    # modules import-cheap at composition, the same seam resolve_tree takes
    # (importlib inside the function).
    from .transition import ReplayTransition

    transition = ReplayTransition.over(tree)
    # Seed the question's reveal set with the roots once, so the policy's first
    # view is the seeded prefix rather than an empty one.  probe_batch is
    # idempotent and all-or-nothing, so seeding the roots is a reveal, and a
    # later re-probe of a root would reveal nothing new.
    probe(transition.prefix())
    rounds = 0
    while rounds < cap:
        batch = select(question)
        # Termination arm one: no batch selected.  Feature 3/242's "the policy
        # has selected no batch" — the empty list legal_actions hands a leaf —
        # is the emptiness of the policy's answer, not anything the transition
        # can see.
        if not batch:
            break
        # Advance the transition by each selected node's recorded child, one
        # step per element.  A node the tree does not hold is refused by the
        # transition itself (245's ReplayTreeError), not by a barrier minted
        # here: the loop trusts that select returns a prefix-only batch, and
        # the prefix-only law is enforced at the surface and the guard, not at
        # the loop.
        newly_revealed: list[str] = []
        for node_id in batch:
            child = transition.transition(node_id)
            if child is not None:
                newly_revealed.append(child)
        # Reveal into the question exactly the children this round newly
        # revealed — never re-probing the whole prefix: probe_batch is
        # idempotent, so re-probing would be correct but quadratic in the
        # campaign's nodes across the rounds (the per-step re-derivation cost
        # 245 refuses on its side).  Revealing only the new children keeps the
        # question's reveal set equal to the transition's revealed set at every
        # select, in O(N) over the whole walk rather than O(rounds × N).
        if newly_revealed:
            probe(newly_revealed)
        rounds += 1
    # The revealed set, ascending — §12's ordering rule restated for the walk's
    # state — and nothing else: no count, no score, no commit.  The sentence
    # names one return, "the revealed set", and this module returns exactly
    # that.
    return transition.prefix()


def _round_cap_of(round_cap: Any) -> int:
    """The round cap, validated a positive integer — refused otherwise.

    ``K2`` is a required argument with no default and no module constant: docs
    §10.1's ``K2`` is a symbolic bound and the repository forbids an absolute
    target (prd §436), so the cap is the caller's policy decision — a
    deployment chooses how many selection rounds a replay may take — and this
    module spells no number for it.  A ``bool``, a zero, a negative or a
    non-``int`` names no loop: zero or negative would terminate before a single
    round (a silent no-op that reads as a completed replay), and a non-``int``
    would break the ``rounds < round_cap`` comparison.  Refused before the
    transition is opened, naming the value.
    """
    # A bool is an int in Python (True == 1, False == 0), but a boolean is not
    # a round count: it names no loop, and answering 1 or 0 for it would report
    # a malformed cap as a completed or a single-round replay.
    if isinstance(round_cap, bool) or not isinstance(round_cap, int):
        raise ReplayRoundError(
            f"the round loop's round_cap is a positive integer — the number of "
            f"selection rounds a replay may take (docs §10.1's `while rounds < "
            f"K2`, a symbolic bound this loop does not spell) — got "
            f"{round_cap!r} ({type(round_cap).__name__}), which is not a "
            f"positive integer. The cap is the caller's policy decision, and a "
            f"deployment chooses it; this loop refuses one it cannot count "
            f"rounds against (feature 248)"
        )
    if round_cap <= 0:
        raise ReplayRoundError(
            f"the round loop's round_cap is a positive integer — got "
            f"{round_cap!r}, which is not greater than zero. A cap of zero or "
            f"less would terminate the loop before a single round (a silent "
            f"no-op that reads as a completed replay), and a replay that never "
            f"selected is one whose revealed set is only the seeded roots. Pass "
            f"a positive count — the deployment's choice of how many selection "
            f"rounds a replay may take (feature 248)"
        )
    return round_cap


def _probe_batch_of(question: Any) -> Callable[[Iterable[str]], Any]:
    """The question's ``probe_batch`` verb, validated — refused otherwise.

    The loop keeps the question's reveal set equal to the transition's revealed
    set through exactly one verb — feature 217's :meth:`probe_batch`
    (idempotent, all-or-nothing, ascending, returning only the cells newly
    revealed) — and a carrier with no such verb cannot be reconciled to the
    walk: a mismatch the policy would see as a frontier the walk is not standing
    on.  Refused before the transition is opened, naming what arrived.
    """
    probe = getattr(question, "probe_batch", None)
    if not callable(probe):
        raise ReplayRoundError(
            f"the round loop's question is feature 217's read-side question, "
            f"read through one verb — probe_batch, which keeps the question's "
            f"reveal set equal to the transition's revealed set so the policy "
            f"is always shown the frontier the walk is standing on — got "
            f"{question!r} ({type(question).__name__}), which has no callable "
            f"probe_batch. The loop drives the transition and the question, and "
            f"without a reveal verb it cannot reconcile the two (feature 248)"
        )
    return probe

