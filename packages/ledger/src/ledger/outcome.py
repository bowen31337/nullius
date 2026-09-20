"""Feature 91's vocabulary: the four ways a trial can end.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 91: *System
persists an outcome of ok, timeout, error or tripwire_fail on every
appended trial row.*  docs/nullius-tech-architecture.md §8 fixes the
column and its vocabulary in one DDL comment — ``outcome TEXT NOT NULL
-- ok | timeout | error | tripwire_fail`` — and the four are not labels
to choose among freely; each names a specific way the evaluation ended:

* ``ok`` — the pipeline ran to its persist step; the node was scored.
* ``timeout`` — the sandbox's hard kill (§5: "Timeout | Hard kill,
  recorded as ``fail_class=timeout``"); the node ran out of its cgroup
  budget mid-evaluation.
* ``error`` — the evaluation failed any other way: a crash, a refused
  contract, an unraisable in the sandbox.
* ``tripwire_fail`` — step 10's leakage tripwires (time-shuffle,
  label-permute, perturbation stability) rejected the node; a failure
  that poisons the node and its subtree rather than ending one run.

The node table carries the same four as ``fail_class`` (§9.1); the
ledger's column is the same fact stated where the charge is counted, so
the honest ``K`` counter can say not only *that* a hypothesis was
consumed but *how* it ended.  That is feature 84's sentence from the
store's side — *System persists an irreversible trial charge with its
failure outcome even when the evaluation failed, because a failed
evaluation still consumed a hypothesis* — and it is why the outcome is
a required stamp, not an optional annotation: §6.1 runs
``debit_ledger`` as step 11 *even when the node fails*, so the debit
path must be able to record the failure it is charged for, and a row
that could not say which of the four it ended in would be a charge no
audit could classify — counted, but meaningless.

**The vocabulary is closed and its spelling is canonical.**  Exactly
the four text values §8 names, lowercase, no padding: anything else —
an absent ``None``, a case variant, a synonym like ``"crashed"``, a
non-string — is refused at the write with
:class:`~ledger.errors.TrialRecordError`, naming the four accepted
spellings, before the database is touched.  Unlike the identity columns
there is nothing to canonicalise *to*: a ``"Timeout"`` folded to
``"timeout"`` would silently bless a caller whose vocabulary had
drifted from the contract, and a fifth value stored as-is would split
every later "how did the trials end?" query into fragments the spec
never named.  The refusal is the feature: the outcome is a fact about
the evaluation, and facts are stated exactly or not at all.

Stdlib-only, like the rest of the member, and imported by every layer
that touches the column — the record (:mod:`ledger.record`), the store
(:mod:`ledger.store`), the debit endpoint (:mod:`ledger.debit`) — so
the row, the write and the wire cannot drift apart on what a trial's
outcome may be.
"""

from __future__ import annotations

from typing import Any

from .errors import TrialRecordError

__all__ = ["OUTCOMES", "validated_outcome"]

#: The outcomes a trial can end in, in §8's declaration order — the
#: order the DDL comment spells them in and the order the refusal
#: message names them in.  A tuple, not a set, because the order is the
#: spec's own and the membership test over four elements has nothing to
#: gain from hashing.
OUTCOMES: tuple[str, ...] = ("ok", "timeout", "error", "tripwire_fail")


def validated_outcome(value: Any) -> str:
    """Validate a trial's outcome, returning its canonical spelling.

    The one spelling the record, the store and the debit endpoint share,
    so a row's outcome is validated identically wherever it enters the
    member.  A value that is one of :data:`OUTCOMES` is returned as-is —
    the vocabulary is already canonical, so there is nothing to
    normalise.  Anything else — ``None`` (the caller that debits a trial
    without saying how it ended), a case variant, a synonym, a
    non-string — is refused with :class:`~ledger.errors.TrialRecordError`
    naming the four accepted spellings, at the write, before any
    sequence number is spent on it: an unclassifiable charge is a hole
    in the account, not a row to append and sort out later.
    """
    if value not in OUTCOMES:
        accepted = ", ".join(repr(outcome) for outcome in OUTCOMES)
        raise TrialRecordError(
            f"outcome must be one of {accepted} — the four outcomes a "
            f"trial can end in, as docs/nullius-tech-architecture.md §8 "
            f"declares the column ('ok | timeout | error | "
            f"tripwire_fail'); got {value!r}. Every appended trial row "
            f"persists its outcome (feature 91) because a failed "
            f"evaluation still consumed a hypothesis — a charge that "
            f"cannot say how it ended is a charge no audit can classify, "
            f"and it is refused here, before the ledger is touched."
        )
    return value
