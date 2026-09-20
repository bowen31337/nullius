"""The tripwires member's error vocabulary.

Every refusal in this package raises one of three errors, and each names a
*reason* rather than a bare fact, because a tripwire suite runs unattended
inside a frozen evaluator (docs/nullius-tech-architecture.md §5) whose
failures travel as trial outcomes (§8's ``ok | timeout | error |
tripwire_fail``): an ``error`` outcome is only actionable if the exception
behind it says what was wrong with the panel, the shuffle or the statistic
rather than "value error".

The split is by *where* the refusal happens, which is the split the
pipeline's own step boundaries already draw:

* :class:`TripwirePanelError` — the inputs are not a panel a tripwire can
  probe.  Malformed scores or targets (wrong container shapes, non-finite
  values, keys that are not dates), a candidate and a target bundle that
  share no horizon, or a join with fewer than the two dates a shuffle
  needs.  The analogue of the alignment and window refusals upstream
  (features 72 through 75): nothing was measured, and dressing an absent
  measurement up as a verdict is exactly the failure mode this category
  exists to prevent — a tripwire that "passed" a node it never probed.
* :class:`TripwireStatisticError` — the panel is well-formed but the
  statistic is undefined on it.  The surviving Sharpe divides by a
  dispersion, and a candidate whose per-date probe returns never varied
  has a zero denominator: refusing rather than fabricating an infinity is
  the same stance the metrics step takes on a constant book (feature 80)
  and the coefficient takes on a constant side (feature 81).
* :class:`TripwirePoisonError` — the *store* half's refusals (feature 131).
  Both of the errors above are about a probe that runs on panels and never
  touches a database; this one is about the persistence feature that
  consumes a probe's verdict, so it is a different kind of refusal in a
  different place — the split this module's first paragraph draws, applied
  to the feature that arrives three members later.  A malformed node id, a
  ``DATABASE_URL`` whose scheme the store cannot speak, a subtree that is
  its own ancestor, a mark that does not survive being read back: each is
  a failure of *the record about the node*, not of the panel handed to a
  tripwire, and a caller that caught the panel error for one of these
  would be looking in the wrong module for the cause.
* :class:`TripwireExcisionError` — the *pool's* refusals (feature 132).
  Feature 131's error is about writing the record; this one is about reading
  it back and refusing the scores it condemns, and the two are separate for
  the reason the first two are: a caller running the replay path catches the
  pool's refusal and lets the store's write failures surface elsewhere.  A
  ``DATABASE_URL`` this member cannot speak, a pool query this member cannot
  run, an excision asked for over a branch that was never poisoned: each is a
  failure of *the pool read*, and the last one especially — "excise this
  branch" and "this branch was never poisoned" are different sentences, and
  collapsing them into a silent no-op is the failure §C6 exists to prevent.

There is deliberately no ``TripwireVerdictError``.  A verdict is stated,
not raised: the two things a tripwire can say about a node are *pass* and
*leakage indicated*, and both are values (:class:`~tripwires.time_shuffle.
TimeShuffleVerdict.rejected`).  A tripwire that raised on detection would
be indistinguishable, at the trial-ledger layer, from a tripwire that
crashed — and feature 91's outcome vocabulary exists precisely so those
two futures do not collapse into one word.  Feature 131's refusal is not an
exception to that rule and does not smuggle one back in: ``poison_node``
raises only when it could not *persist* the poisoning the verdict already
stated, and a detected leak handed to it in good order is still a value.
"""

from __future__ import annotations

__all__ = [
    "TripwireError",
    "TripwireExcisionError",
    "TripwirePanelError",
    "TripwirePoisonError",
    "TripwireStatisticError",
]


class TripwireError(Exception):
    """The base of every refusal this member raises.

    The tripwires are step 10 of the evaluator pipeline (§6.1), but they
    are *not* the evaluator: this member imports no other workspace
    member, so its errors share no hierarchy with the evaluator's — a
    caller catching :class:`~evaluator.EvaluatorError` will not
    accidentally swallow a tripwire's refusal, and vice versa.  Catch this
    base only when the reason does not matter.
    """


class TripwirePanelError(TripwireError):
    """The candidate or the targets are not a panel a tripwire can probe."""


class TripwireStatisticError(TripwireError):
    """The panel is well-formed but the statistic is undefined on it."""


class TripwirePoisonError(TripwireError):
    """Feature 131's refusals — the poisoning could not be persisted.

    Raised by the persistence half of this member: a node id that cannot join
    the tree store's key, a relational store whose URL this member cannot
    speak, a subtree whose recursion came back to where it started, or a mark
    that did not survive being read back.  Distinct from the two above by
    *where* it happens rather than by severity: those describe panels handed
    to a probe, this describes the record written about the node a probe
    judged.  A caller that catches :class:`TripwirePanelError` when the
    database is unreachable has caught the wrong error and will not find out
    until it reads the message.
    """


class TripwireStabilityError(TripwireError):
    """Feature 129's refusals — the stability figure could not be persisted.

    The third sibling of :class:`TripwirePoisonError`, alongside
    :class:`TripwireExcisionError`, and deliberately not a subclass of either.
    The three describe three different moments around one node: 131 *writes* the
    record of a failure, 132 *reads* it to refuse the condemned scores, and 129
    writes a *measurement* that is taken whether or not anything failed.  A
    caller in the evaluation loop catches this one because the figure is what it
    asked to persist, and folding them together would make "the perturbation
    figure was not stored" and "the poisoning could not be written"
    indistinguishable at exactly the point where the difference is the whole
    question — one is a candidate's stability unrecorded, the other is a leak
    gone unexcluded.

    Raised for a store nothing names, a ``DATABASE_URL`` this member cannot
    speak, a producer whose terms the store cannot read, a verdict whose outcome
    word disagrees with its own decision, and — the one worth naming — a
    single-axis read of a node that has no figure on that axis.  That last
    refusal is this error's reason to exist beside :meth:`figures`: "this node's
    stability is X" and "this node was never re-run on this perturbation" are
    different sentences, and a store that answered the second with a default
    would record a measurement nobody took.
    """


class TripwireExcisionError(TripwireError):
    """Feature 132's refusals — the pool could not be read, or the branch was clean.

    The sibling of :class:`TripwirePoisonError`, and deliberately not a
    subclass of it.  Feature 131 *writes* the record of a failure; feature 132
    *reads* it and refuses the scores the record condemns, and a caller in the
    replay path catches this one because the pool is what it asked.  Folding
    them together would make a caller that wanted to distinguish "the pool
    refused a poisoned branch" from "the poisoning could not be written"
    unable to — and those are the two halves of §C6 that a stuck deployment
    most needs told apart, because one is the feature working and the other is
    the feature never having run.

    Raised for a ``DATABASE_URL`` this member cannot speak, for a pool read
    that could not be completed, and — the one worth naming — for an excision
    asked over a branch no poisoning ever marked.  That last refusal is the
    point of the error's existence: "these scores are excised" and "nothing
    here was ever excised" are different sentences, and a store that answered
    the second with an empty success would let a caller report an excision it
    never performed.
    """
