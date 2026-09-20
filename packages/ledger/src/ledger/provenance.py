"""Feature 87's stamp: the provenance triple on every trial row.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 87: *System
stamps every trial_ledger row with evaluator_hash, snapshot_hash and
cost_model_hash.*  docs/nullius-tech-architecture.md §8 declares the
three columns together, between the identities and the booking, all in
one breath — ``evaluator_hash CHAR(64) NOT NULL``, ``snapshot_hash
CHAR(64) NOT NULL``, ``cost_model_hash CHAR(64) NOT NULL`` — and §9.1
declares the same triple on the node table, because it is one fact
stated twice: the row that was charged and the node that was evaluated
must be able to name the same three terms without drift.

**Each hash names one term of the evaluation's provenance.**  A trial is
not just a node debited; it is a node debited *by a particular evaluator,
against a particular snapshot, under a particular cost model*, and the
triple is what makes the charge reproducible:

* ``evaluator_hash`` — feature 70's sha256 over the container image
  digest plus the resolved configuration: *which frozen evaluator scored
  the trial*.  §14.1's infrastructure note states the discipline it
  carries — digest-pinned containers, *"because evaluator_hash requires
  digests not tags"* — and feature 71 refuses a comparison between two
  scores whose evaluator hashes differ, a refusal that can only mean
  what it says when every row names its hash.
* ``snapshot_hash`` — §4.2's sha256 over the sorted file hashes, the
  universe definition and the schema version: *which sealed snapshot the
  trial was scored against*.  The point-in-time slice feature 72 serves
  is cut from the snapshot this hash names, and replay (§15) re-cuts it
  by the same name.
* ``cost_model_hash`` — feature 60's sha256 over the loaded §6.2
  cost-model document: *which fee-and-fill regime priced the trial*.
  The score a trial carries is post-cost, so a charge that could not
  name its cost model would be a number nobody could recompute, on a
  row nobody could correct.

A charge that cannot name its triple is a charge no replay can
reproduce — the score it booked might as well have come from a different
system — and this module exists to keep such a row out of the ledger
rather than in it.

**The write is refused when the triple is absent, and there is no honest
default.**  §8 declares all three columns ``NOT NULL`` with no
``DEFAULT``, and the stance is the one the outcome (feature 91), the
budget directive (feature 90) and the epoch (feature 88) take rather
than the one the charge unit (feature 89) takes: ``charge_units`` got a
default because one unit is an ordinary trial's honest weight, while
the evaluator that ran, the snapshot it sliced and the cost model that
priced the run are three *facts about the evaluation* that nothing else
on the row states and no presumption could name.  Defaulting them would
fabricate provenance — stamping every epoch-less charge with a hash no
feature ever computed — which is the one error direction the whole
category exists to make impossible: a wrong count wearing a right one's
clothes.  (The three terms were computed before the charge is debited:
feature 70 folds the evaluator's, §4.1's seal computes the snapshot's,
feature 60 loads the cost model's.  The evaluator that reaches step 11
of §6.1 already holds all three; this seam only refuses to believe it
ran without them.)

**One shape for all three: the sha256 hexdigest's own spelling.**  Each
column holds the 64-lowercase-hex digest its owning feature computed,
and this module holds the three columns to that one shape:

* either case is accepted and uppercasing is normalised away — a hash
  pasted from a database, a log line or a report is commonly uppercase,
  means the same value, and is folded rather than refused, the same
  treatment ``evaluator.normalize_evaluator_hash`` and
  ``snapshot.normalize_snapshot_hash`` give the sibling columns on the
  tables this row joins against;
* surrounding whitespace is stripped — the same pasted-from-a-report
  courtesy the evaluator member extends;
* a ``sha256:``-prefixed digest is refused on its own ground: that
  spelling belongs to an *image reference*, and accepting it here would
  let a caller compare a digest against a hash and get "different" for
  the wrong reason;
* a short hash, a truncated value or a non-hex token is refused — it
  names no evaluator, snapshot or cost model this system recorded;
* a non-string is refused rather than strung, because a hash that
  arrives as another type is a caller bug at the write, and coercing it
  would bless it.

**``None`` is the read's spelling for a row that predates the stamp.**
The record layer (:mod:`ledger.record`) and the read paths validate
through this same function *without* ``required``, so ``None`` passes
there: a row written before feature 87's columns landed — on a table
the store's legacy upgrade brings forward — honestly names no
provenance, and reads back as ``None`` for all three.  That is a
statement about the ledger's history, not a hash a feature computed,
and it is why the pre-stamp spelling is ``None`` rather than a
placeholder digest: it cannot be mistaken for provenance this system
recorded.  The write seams — the append, the debit, the debit request —
pass ``required=True``, and that is where the feature's refusal lives:
at the write, before the database is touched, so a refused charge
spends no sequence number.

Stdlib-only, like the rest of the member, and imported by every layer
that touches the columns — the record (:mod:`ledger.record`), the store
(:mod:`ledger.store`), the debit endpoint (:mod:`ledger.debit`) — so
the row, the write and the wire cannot drift apart on what provenance
a charged trial may name.
"""

from __future__ import annotations

from typing import Any, Optional

from .errors import TrialRecordError

__all__ = ["PROVENANCE_COLUMNS", "PROVENANCE_HASH_LENGTH", "validated_provenance_hash"]

#: The one shape all three of §8's provenance columns hold: the
#: ``CHAR(64)`` the DDL declares, which is the sha256 hexdigest's own
#: 64-character lowercase-hex spelling.  Spelled once here so the
#: validator, the store's DDL and the tests cannot drift apart on how
#: long a provenance hash is.
PROVENANCE_HASH_LENGTH = 64

#: The three columns feature 87 stamps, in the order §8 declares them
#: and the order the table's columns land in.  One spelling shared by
#: the schema, the legacy upgrade and the validator's callers, so the
#: row, the write and the wire cannot drift apart on what the triple is
#: called — the same single-spelling rule :data:`TRIAL_LEDGER_TABLE`
#: states for the table's own name.
PROVENANCE_COLUMNS = ("evaluator_hash", "snapshot_hash", "cost_model_hash")

#: The hexdigest's alphabet, lowercase — the case every accepted
#: spelling is folded to before it is compared against this set.
_HEX = frozenset("0123456789abcdef")


def validated_provenance_hash(
    value: Any, column: str, *, required: bool = False
) -> Optional[str]:
    """Validate one term of the provenance triple, in canonical lowercase hex.

    The one spelling the record, the store and the debit endpoint share
    for all three of §8's ``CHAR(64)`` columns, so a term is validated
    identically wherever it enters the member; ``column`` names which of
    the three is being asked about, and reaches the error text so a
    refused write says which term of its provenance it could not state.
    A :class:`str` of exactly :data:`PROVENANCE_HASH_LENGTH` hexadecimal
    characters is returned in lowercase — the hexdigest's own spelling,
    however the caller came by the value.

    ``None`` is the read's spelling for a row that predates feature 87's
    stamp (the legacy upgrade's NULL columns) and passes unless
    ``required`` is set.  The write seams set it — the append, the
    debit, the debit request — and an absent term is refused there with
    :class:`~ledger.errors.TrialRecordError` *before* the database is
    touched, so a refused charge spends no sequence number: the triple
    is what makes a charge reproducible, and a charge that cannot name
    its evaluator, its snapshot and its cost model is a charge no replay
    can reproduce.  Any other value that is not 64 hex characters — a
    ``sha256:``-prefixed image reference, a git-style short hash, a
    truncated digest, a non-hex token, a non-string — is refused on both
    paths alike, because a term that names nothing is not made
    acceptable by arriving on a read.
    """
    if value is None:
        if required:
            raise TrialRecordError(
                f"{column} is required — §8's column is CHAR(64) NOT NULL, one "
                "of the provenance triple feature 87 stamps on every row "
                "(evaluator_hash, snapshot_hash, cost_model_hash), and the "
                "evaluator that scored the trial, the snapshot it was scored "
                "against and the cost model that priced it are three facts "
                "about the evaluation that nothing else on the row states: "
                "feature 70 computed the evaluator's hash, §4.2's seal "
                "computed the snapshot's, feature 60 loaded the cost "
                "model's, and a write that cannot name them is a charge no "
                "replay can reproduce. Pass the triple the evaluation ran "
                "under; got None. The refusal happens before the ledger is "
                "touched, so no sequence number is spent on it."
            )
        return None
    if isinstance(value, str):
        text = value.strip()
        if ":" in text:
            raise TrialRecordError(
                f"{column} {value!r} carries an algorithm prefix; a "
                "sha256:<hex> digest is an *image reference*, not the hash "
                "computed over it — pass the 64 hex characters themselves. "
                "A row stamped with a reference would name no evaluator, "
                "snapshot or cost model this system recorded, and feature "
                "71's mismatched-provenance refusal would answer a question "
                "nobody asked."
            )
        if len(text) == PROVENANCE_HASH_LENGTH and set(text.lower()) <= _HEX:
            return text.lower()
    raise TrialRecordError(
        f"{column} must be {PROVENANCE_HASH_LENGTH} hexadecimal characters — "
        "the sha256 digest of one term of the trial's provenance (feature "
        "87's stamp: §8's evaluator_hash, snapshot_hash and cost_model_hash "
        "CHAR(64) columns), got "
        f"{value!r} ({type(value).__name__}). A short hash, a truncated "
        "value or a non-hex token names no evaluator, snapshot or cost "
        "model this system recorded, and a row stamped with it would be "
        "provenance no audit can replay."
    )
