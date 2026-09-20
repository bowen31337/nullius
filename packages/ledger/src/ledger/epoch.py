"""Feature 88's stamp: the sequestered epoch a trial charged.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 88: *System
records epoch_id naming which sequestered epoch a trial charged, which
rejects a write whose epoch_id is absent.*  docs/nullius-tech-
architecture.md §8 declares the column with its reason in the comment
beside it — ``epoch_id TEXT NOT NULL, -- which sequestered epoch was
charged`` — and the versioned migration that writes the production DDL
(``migrations/versions/0112_trial_ledger.py``, feature 103) restates the
sentence's second half in its own words: *a write whose epoch is absent
is refused (feature 88) because the epoch is a depleting resource
counted in* ``epoch_ledger``.

**A sequestered epoch is a holdout the loop has never shown a policy.**
docs/alpha-engine-prd.md §"Change A" fixes what the word means: a
committed pick *"is scored on a sequestered epoch it has never observed
in any world"*, and §13 item 4 fixes what it costs — *"Sequestered
epochs are retired permanently after 3 promotion decisions.  Track in a
ledger."*  So the epoch a trial charged is not an annotation on the
row; it is the identity of a depleting resource.  Two of §8's derived
views key on it: ``K_effective`` *per epoch* (feature 93, counting the
budget-charging trials of each epoch separately) and the epoch-usage
counts (feature 96, reading the ``epoch_ledger`` table feature 105
seals one row per epoch into).  A trial row that cannot name its epoch
is a charge those views cannot place — degrees of freedom spent against
a holdout nobody can identify — and this module exists to keep such a
row out of the ledger rather than in it.

**The write is refused when the epoch is absent, and there is no honest
default.**  This is the feature's own second clause, and the stance is
the one the outcome (feature 91) and the budget directive (feature 90)
take rather than the one the charge unit (feature 89) takes: §8 gives
``charge_units`` a ``DEFAULT 1.0`` because one unit is an ordinary
trial's honest weight, and gives ``epoch_id`` none because the epoch a
trial charged is a fact about the evaluation's booking, not a weight
the table may presume.  It is also not derivable: nothing else on the
row says it (the node and the campaign identify *what* was charged, not
*against which holdout*), and the sealing process — not this member —
coined the name.  Defaulting would silently book every epoch-less
charge into an epoch the sealing process never sealed, which is the
one error direction the whole category exists to make impossible: a
wrong count wearing a right one's clothes.

**The name is carried in its own spelling, never coined or folded.**
The epoch namespace belongs to the sealing process and is shared with
``epoch_ledger``'s ``TEXT NOT NULL PRIMARY KEY`` (feature 105), so this
module's whole contract on it is that it *names an epoch*: a
non-empty, non-blank :class:`str`, stored and returned exactly as the
caller spelled it.  There is nothing to canonicalise *to* — no closed
vocabulary to hold it against (the outcome's four) and no normal form
to fold it into (the identities' UUID spellings) — and inventing one
here would make this member the arbiter of a namespace it does not
own.  An empty or whitespace-only text names no epoch and is refused
on the same ground as an absent one: it would become a bucket of its
own that every later per-epoch read reported as a real, separate
epoch.  A non-string — an ``int``, a ``UUID``, a list — is refused
rather than strung, because a name that arrives as another type is a
caller bug at the write, and coercing it would bless it.

**``None`` is the read's spelling for a row that predates the stamp.**
The record layer (:mod:`ledger.record`) and the read paths validate
through this same function *without* ``required``, so ``None`` passes
there: a row written before feature 88's column landed — on a table
the store's legacy upgrade brings forward — honestly names no epoch,
and reads back as ``None``, the un-named epoch
(:data:`ledger.keffective.UNNAMED_EPOCH`) that feature 93's derivation
groups such rows under.  That is a statement about the ledger's
history, not an epoch a caller named, and it is why the un-named
bucket is spelled ``None`` rather than a placeholder string: it cannot
be mistaken for an epoch the sealing process sealed.  The write seams —
the append, the debit, the debit request — pass ``required=True``, and
that is where the feature's refusal lives: at the write, before the
database is touched, so a refused charge spends no sequence number.

Stdlib-only, like the rest of the member, and imported by every layer
that touches the column — the record (:mod:`ledger.record`), the store
(:mod:`ledger.store`), the debit endpoint (:mod:`ledger.debit`) — so
the row, the write and the wire cannot drift apart on what a charged
epoch may be.
"""

from __future__ import annotations

from typing import Any, Optional

from .errors import TrialRecordError

__all__ = ["validated_epoch_id"]


def validated_epoch_id(value: Any, *, required: bool = False) -> Optional[str]:
    """Validate a charged epoch's name, returning it as the caller spelled it.

    The one spelling the record, the store and the debit endpoint share,
    so a row's epoch is validated identically wherever it enters the
    member.  A non-empty, non-blank :class:`str` is returned as-is — the
    epoch namespace is the sealing process's own (shared with
    ``epoch_ledger``'s primary key), so there is no canonical spelling to
    normalise to and this function coins none.

    ``None`` is the read's spelling for a row that predates feature 88's
    stamp (the legacy upgrade's NULL column) and passes unless
    ``required`` is set.  The write seams set it — the append, the debit,
    the debit request — and an absent epoch is refused there with
    :class:`~ledger.errors.TrialRecordError` *before* the database is
    touched, so a refused charge spends no sequence number: the epoch is
    a depleting resource counted in ``epoch_ledger``, and a charge that
    cannot name the holdout it spent is a charge no audit can place.
    Any other value that is not a non-blank string — an empty text, a
    whitespace-only one, a non-string — is refused on both paths alike,
    because a name that names no epoch is not made acceptable by
    arriving on a read.
    """
    if value is None:
        if required:
            raise TrialRecordError(
                "epoch_id is required — §8's column is TEXT NOT NULL ('which "
                "sequestered epoch was charged'), and the epoch a trial "
                "charged is not something the ledger may presume: it is a "
                "depleting resource counted in epoch_ledger (feature 105 "
                "seals one row per epoch, and §13 item 4 retires an epoch "
                "after 3 promotion decisions) and the grouping key "
                "K_effective is derived by (feature 93), so a write whose "
                "epoch is absent is a charge no audit can attribute to a "
                "holdout. Pass the epoch the evaluation charged (feature "
                "88); got None. The refusal happens before the ledger is "
                "touched, so no sequence number is spent on it."
            )
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise TrialRecordError(
        f"epoch_id must be a non-empty string naming the sequestered epoch "
        f"the trial charged — §8's own comment on the column ('which "
        f"sequestered epoch was charged'), a name the sealing process "
        f"coined and epoch_ledger keys on — got {value!r} "
        f"({type(value).__name__}). A name that names no epoch would "
        f"become a bucket of its own that every later per-epoch read "
        f"(feature 93's K_effective among them) reported as a real, "
        f"separate epoch, and it is refused here, before the ledger is "
        f"touched."
    )
