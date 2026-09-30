"""Charging the trial ledger — pipeline step 11, the irreversible write.

app_spec.xml feature 84: *"System persists an irreversible trial charge with
its failure outcome even when the evaluation failed, because a failed
evaluation still consumed a hypothesis."*  docs/nullius-tech-architecture.md
§6.1 names the step — ``11. debit_ledger   append trial record
(irreversible)`` — and the note under the pipeline fixes the exception that
*is* the feature: *"step 11 happens even if the node fails.  A failed
evaluation still consumed a hypothesis."*  Every step before this one
computes what a successful evaluation measures; this step is what every
evaluation owes the honest ``K`` counter §8 makes the ledger, however it
ended.

**The charge happens on the failure path, and that is the feature.**  Every
other step's input is some earlier step's *output* — a window, an execution,
an alignment, a priced bundle — so a failure anywhere upstream leaves a
step-shaped-like-that with nothing to consume, and it would simply never run
for a failed node.  This step's inputs are deliberately not outputs of the
pipeline: the node's identity, the outcome it ended in, and the budget
directive the null oracle returned at step 5.  So the failure path has a
first-class spelling — :func:`failure_outcome` classifies the pipeline's
own failure vocabulary into §8's four outcomes, and :func:`charge_failure`
builds the charge straight from the failure — and a debit constructed from
a timeout, a crash or a refused contract is as direct as one constructed
from a completed run.  The feature is not "the charge may survive a
failure"; it is that the charge is *for* the evaluation however it ended,
which is why a :class:`SandboxResult` whose run conformed is *refused* by
the classifier: a completed run is not a failure, and the outcome it charges
is ``'ok'``, stated by the caller that watched it complete.

**The outcome is §8's four, classified into — never invented.**  ``ok |
timeout | error | tripwire_fail`` is the closed vocabulary §8's own DDL
comment fixes, and the mapping this module owns is the spec's: ``timeout``
is the sandbox's hard kill (:class:`SandboxResult`'s ``fail_class
'timeout'``, the wall-clock watchdog and the SIGXCPU handler alike);
``error`` is every other way the evaluation failed — an oom, a crash, a
refused contract, a channel failure, or an exception a pipeline step
raised; ``tripwire_fail`` is step 10's verdict, which is the tripwires
member's to state (features 125 on) and is in the vocabulary so the charge
can carry the verdict the moment it arrives.  A raised ``TimeoutError`` is
an ``error``, not a ``timeout``: the sandbox records its kills as values,
never exceptions (``_sandbox``), so a timeout that arrives raised is a
host-side failure wearing a familiar name.  A failure class outside the
sandbox's own six is refused rather than folded — a drifted vocabulary
must not become a fabricated fifth outcome — the same stance the ledger
member's ``outcome`` layer takes on its side of the same column.

**The directive is required, and never derived.**  ``charges_budget`` is
§7.2's opaque directive, the one bit that crosses the sidecar barrier, and
feature 90's rule is that it is *supplied*, never computed.  The charge
accepts the bit itself or the record that carries it — step 5's
:class:`~evaluator.GatedTargets` or step 7's
:class:`~evaluator.PostCostReturns` — because the failure path cannot
re-ask the gate: the oracle answered once, at step 5, and an evaluation
that failed after that answer has only the record to read the bit from.
For a failure *before* the gate answered — a sandbox timeout at step 2 —
no directive exists to forward, and the charge still must be written: the
caller states the bit, and the conservative spelling is ``True``, the same
statement the ledger makes for rows that predate the directive (a
hypothesis was consumed either way, and understating ``K`` is the one
error direction that lets a false discovery through).  This module
supplies no default for the bit anywhere — a default would be the
derivation feature 90 forbids.

**The ledger is an injected structural seam.**  The workspace contract
keeps members dependency-free, so this module does not import the ledger
member and owns no table: ``trial_ledger`` is the ledger member's (features
86 on).  The seam is an object exposing ``debit(node_id, campaign_id,
outcome, charges_budget, charge_units, epoch_id, evaluator_hash,
snapshot_hash, cost_model_hash)`` that answers ``(record, appended)`` — the
shape the ledger member's ``TrialLedger`` already speaks, satisfied
structurally with no adapter, the same way feature 73's sandbox and feature
76's oracle are injected.  The seam's failures propagate as its own (a
store error is the ledger's to report), but its *answer* is read back, not
trusted: the landed row is rebuilt through :class:`TrialCharge`'s
constructor, so a seam whose answer drifted outside the vocabulary, whose
directive is not a genuine bool, or whose ``seq`` is not a number a ledger
could assign is refused here rather than laundered — the read-back defence
the identity store states for its own rows.

**The charge names its full row, because a partial charge is refused.**
The four terms this module started with — two identities, an outcome and
the directive — are the terms §8's *row* needs that the pipeline's own
compute does not produce; they were never the whole of what the ledger
*requires*.  Features 87 and 88 (and 89's unit) added four more columns to
``trial_ledger`` — the sequestered ``epoch_id`` the charge is booked
against, and the provenance triple (``evaluator_hash``, ``snapshot_hash``,
``cost_model_hash``) that makes the charge reproducible — and the ledger's
``debit`` validates every one of them with ``required=True``: a charge that
cannot name its holdout is a charge no audit can place, and a charge that
cannot name its provenance is a charge no replay can reproduce.  So the
charge carries those terms too, and the step hands them across: this is the
evaluator *supplying* what the ledger demands, not the ledger relaxing it,
because the evaluator that reaches step 11 already holds the frozen image
digest (feature 70), the sealed snapshot's hash (§4.2) and the loaded cost
model's hash (feature 60) — the triple is a fact about the evaluation, and
:func:`debit_trial` refuses a charge missing any term of it *before* the
seam is touched, with this member's own error, so a refused charge spends
no sequence number.  The unit is held to a positive finite real, the same
one the ledger's column takes; its default here (``1.0``, an ordinary
evaluation) mirrors the column's own ``DEFAULT``, which is why omitting it
is legal where omitting the epoch or a provenance term is not.

**The debit is idempotent, because the workers it runs on are reclaimed.**
§14 runs evaluations on spot-eligible workers and states the contract:
*"Failures retry; ledger debits are idempotent by ``node_id``."*  So step
11 speaks the idempotent spelling, and a retried evaluation never
double-charges one hypothesis.  On a retry the append-only ledger answers
with the prior row: the returned :class:`DebitedTrial` carries the
*landed* charge — the outcome and directive the first debit wrote — and
the terms a retry handed it are the losers, exactly as the ledger member
documents.  That is deliberately not an error: the worker whose failed
run charged ``'timeout'`` and whose retry completed ``'ok'`` has one row
saying ``'timeout'``, the retry is answered by that row's sequence, and
the disagreement is visible by comparing the landed charge with the one
asked for — the §14 contract working, not a fault to raise through it.

**What this module does not do.**  It persists no artifact and no scalar
(step 12, feature 85), decides no tripwire verdict (step 10, features 125
on), and reads nothing back for anyone — ``K_effective`` and the derived
views are the ledger member's reads.  It answers exactly one question the
pipeline puts in scope: *what charge did this evaluation leave in the
ledger, under which sequence number, and did this call write it?*

Stdlib-only, like the rest of the member: the charge is a value over
names, an outcome and a bit, and the import must stay cheap enough that
the factory's scan — and the replay path §1 forbids from reaching the
evaluator at all — never pays for it.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from ._costs import PostCostReturns
from ._errors import EvaluatorDebitError
from ._gate import GatedTargets
from ._identity import EVALUATOR_HASH_LENGTH
from ._sandbox import SandboxResult

__all__ = [
    "DEBIT_STEP",
    "DEFAULT_CHARGE_UNITS",
    "PROVENANCE_HASH_LENGTH",
    "TRIAL_OUTCOMES",
    "DebitedTrial",
    "TrialCharge",
    "charge_failure",
    "debit_trial",
    "failure_outcome",
]

#: The pipeline-step name, in §6.1's own spelling — ``11. debit_ledger
#: append trial record  (irreversible)``.  Shared vocabulary: the step's
#: feature sentence, the refusals below and the callers that name where a
#: charge comes from all spell the one step, and they spell it once.
DEBIT_STEP: str = "debit_ledger"

#: The outcomes a trial can end in — §8's closed vocabulary, in its
#: declaration order (``outcome TEXT NOT NULL -- ok | timeout | error |
#: tripwire_fail``), restated here because this member cannot import the
#: ledger member that owns the column: both spell the four against the one
#: spec line, the way ``_costs`` restates feature 59's ``(venue, version)``
#: pair, and the composition test runs the real ledger under this debit to
#: keep the two spellings honest.  A tuple, not a set, because the order is
#: the spec's own and the refusal message names the four in it.
TRIAL_OUTCOMES: tuple[str, ...] = ("ok", "timeout", "error", "tripwire_fail")

#: The sandbox's own failure classes — :class:`SandboxResult`'s vocabulary,
#: from its own docstring: ``timeout``, ``oom``, ``crash``, ``violation``,
#: ``payload``, ``empty``.  Restated rather than imported as a constant
#: because the sandbox publishes no such name (its classifier is inline in
#: the parent-side reader), and the classifier below must be total over
#: exactly these or refuse.
_SANDBOX_FAIL_CLASSES: tuple[str, ...] = (
    "timeout",
    "oom",
    "crash",
    "violation",
    "payload",
    "empty",
)

#: §8's cost of one trial — ``charge_units REAL NOT NULL DEFAULT 1.0`` —
#: restated here for the same reason :data:`TRIAL_OUTCOMES` is: this member
#: imports no sibling, so the one number a plain evaluation is worth is
#: spelled once on each side against the spec line, and the composition
#: test runs the real ledger under this charge to keep the two honest.  A
#: default here is not the derivation feature 90 forbids: the directive is
#: a *fact about the evaluation* the oracle stated, while the unit is what
#: an ordinary evaluation costs, and §8 itself supplies ``1.0`` for the
#: column.  A cross-validated evaluation states its folds' count instead.
DEFAULT_CHARGE_UNITS: float = 1.0

#: The one shape all three of §8's provenance columns hold — the
#: ``CHAR(64)`` the DDL declares, which is the sha256 hexdigest's own
#: 64-character lowercase-hex spelling.  It *is* feature 70's
#: :data:`~evaluator.EVALUATOR_HASH_LENGTH` — the evaluator's hash is the
#: first term of the triple, the three columns are one shape, and stating
#: the width in terms of that name is what keeps this module's validation
#: from drifting if the evaluator ever re-cut its own width.  Kept under
#: its own name so a failure text about a ``snapshot_hash`` or a
#: ``cost_model_hash`` does not read as if it were about an evaluator.
PROVENANCE_HASH_LENGTH: int = EVALUATOR_HASH_LENGTH

#: The hexadecimal alphabet a hash's spelling lives in.  Lowercase; a
#: caller's uppercase spelling is folded rather than refused, the treatment
#: every term of the triple gets on both sides of the seam.
_HEX: frozenset[str] = frozenset("0123456789abcdef")

# The sentinel a seam-answer read uses to tell "the record carries no such
# attribute" from "the attribute is None" — a missing field is a seam that
# did not answer the question the step asked, and the refusal must name it.
_MISSING: Any = object()

# The sentinel a required charge term uses as its "not stated" default, so
# that omitting the term — not merely passing ``None`` — raises this
# member's own error naming the field, rather than Python's ``TypeError``
# about argument arity.  The ledger's ``required=True`` refuses an absent
# epoch or provenance term; stating the same refusal on this side of the
# seam, before the charge is even built, is what keeps a partial charge
# from existing to forward.  It is deliberately not a legal value: no
# ``str`` path in the validators accepts it, so it falls to the refusal.
_ABSENT: Any = object()


# -- The charge, as a value -----------------------------------------------------


def _as_name(value: object, field: str) -> str:
    """A charge identity field — a non-empty string, checked by name.

    ``node_id`` and ``campaign_id`` are how the ledger's row joins to the
    tree store's node, so an identity that is not a name would make the
    charge unattributable — refused rather than trimmed, the same terms the
    gate's request layer holds its identities to.  Not canonicalised here:
    the ledger canonicalises UUID spellings at its own write, and this
    member's convention (``PostCostReturns``, ``OracleRequest``) is that a
    node identity is the caller's own spelling of a name.
    """
    if not isinstance(value, str) or not value.strip():
        raise EvaluatorDebitError(
            f"{field} must be a non-empty string — the evaluation the charge "
            f"names — got {value!r}"
        )
    return value


def _validated_outcome(value: object) -> str:
    """An outcome in §8's closed vocabulary, checked at the write.

    The one spelling the charge and the read-back share, so an outcome is
    validated identically wherever it enters the step.  A value that is one
    of :data:`TRIAL_OUTCOMES` is returned as-is — the vocabulary is already
    canonical, so there is nothing to normalise, and folding ``"Timeout"``
    to ``"timeout"`` would silently bless a caller whose vocabulary had
    drifted from the contract.  Anything else — an absent ``None``, a case
    variant, a synonym like ``"crashed"``, a non-string — is refused naming
    the four accepted spellings, before the ledger is touched: an
    unclassifiable charge is a hole in the account, not a row to append and
    sort out later.
    """
    if value not in TRIAL_OUTCOMES:
        accepted = ", ".join(repr(outcome) for outcome in TRIAL_OUTCOMES)
        raise EvaluatorDebitError(
            f"outcome must be one of {accepted} — the four outcomes a trial "
            f"can end in, as docs/nullius-tech-architecture.md §8 declares "
            f"the column ('ok | timeout | error | tripwire_fail'); got "
            f"{value!r}. The charge carries its failure outcome because a "
            "failed evaluation still consumed a hypothesis (feature 84), so "
            "a charge that cannot say how its trial ended is a charge no "
            "audit can classify, and it is refused here, before the "
            "ledger's sequence is spent on it."
        )
    return value


def _directive(value: object) -> bool:
    """§7.2's opaque budget directive — the bit, or the record carrying it.

    A genuine :class:`bool` is carried through untouched (the directive is
    canonical, so there is nothing to normalise, and anything else is the
    derivation feature 90 forbids).  A :class:`~evaluator.GatedTargets` or a
    :class:`~evaluator.PostCostReturns` — step 5's and step 7's own records,
    the two the pipeline holds between the ask and the charge — answers
    with the bit it carries, both constructors having already held it to a
    genuine bool.  Anything else is refused: a ``1`` or a ``0`` or an
    absent ``None`` is not the oracle's directive, and an arbitrary object
    that happens to spell the attribute is not a record this pipeline
    produced.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (GatedTargets, PostCostReturns)):
        # Both records' constructors already validated the bit as a genuine
        # bool, so reading it back needs no second check — the coercion is
        # over the records this member itself produces, not over shapes.
        return value.charges_budget
    raise EvaluatorDebitError(
        "charges_budget must be a bool — §7.2's opaque directive, the only "
        f"bit that crosses the barrier — or the GatedTargets or "
        f"PostCostReturns record that carries it; got {value!r} "
        f"({type(value).__name__}). The bit is supplied, never derived "
        "(feature 90): a 1 or a 0 or an absent None is not the oracle's "
        "directive, and this step will not invent one."
    )


def _validated_epoch_id(value: object) -> str:
    """Feature 88's epoch — the sequestered holdout the charge is booked against.

    A non-empty, non-blank :class:`str` is returned as the caller spelled
    it: the epoch namespace belongs to the sealing process (it is shared
    with ``epoch_ledger``'s primary key), so there is no canonical
    spelling to normalise to and this module coins none.  The epoch is
    *required* — §8's column is ``TEXT NOT NULL`` ("which sequestered
    epoch was charged"), because the epoch is a depleting resource and a
    charge that cannot name its holdout is a charge no audit can place —
    so an absent ``None`` is refused here rather than forwarded to a
    ledger that would refuse it anyway, which keeps the refusal on this
    side of the seam and spends no sequence number on it.
    """
    if isinstance(value, str) and value.strip():
        return value
    raise EvaluatorDebitError(
        "epoch_id must be a non-empty string naming the sequestered epoch "
        "the trial charged — §8's column is TEXT NOT NULL ('which "
        "sequestered epoch was charged'), the holdout feature 88 books the "
        f"spend against; got {value!r} ({type(value).__name__}). The epoch "
        "is a fact about the evaluation the ledger's K_effective is grouped "
        "by (feature 93), and this step will not presume one: a charge that "
        "cannot name its holdout is a charge no audit can place. The refusal "
        "happens before the seam is touched, so no sequence number is spent "
        "on it."
    )


def _validated_provenance_hash(value: object, field: str) -> str:
    """One term of feature 87's triple, in canonical lowercase hex.

    The shape is the one the ledger validates against — §8's ``CHAR(64)``
    columns — and the same shape
    :func:`~evaluator.normalize_evaluator_hash` gives the sibling
    ``evaluator_hash`` column on the node table: 64 hex characters, either
    case accepted, surrounding whitespace stripped, folded to lowercase.
    A ``sha256:``-prefixed digest, a short or truncated hash, a non-hex
    token or a non-string names nothing this system recorded and is
    refused.  *Required*: a charge that cannot name the evaluator that
    scored it, the snapshot it was sliced from and the cost model that
    priced it is a charge no replay can reproduce, and refusing here — the
    evaluator already holds all three at step 11 — keeps the refusal on
    this side of the seam.  ``field`` names which term moved so the error
    text is actionable about the one that did.
    """
    if isinstance(value, str):
        text = value.strip()
        if ":" in text:
            raise EvaluatorDebitError(
                f"{field} {value!r} carries an algorithm prefix; a "
                "sha256:<hex> digest is an *image reference*, not the hash "
                "computed over it — pass the 64 hex characters themselves. "
                "A row stamped with a reference would name no evaluator, "
                "snapshot or cost model this system recorded, and the "
                "provenance comparison (feature 71) would answer a question "
                "nobody asked."
            )
        if len(text) == PROVENANCE_HASH_LENGTH and set(text.lower()) <= _HEX:
            return text.lower()
    raise EvaluatorDebitError(
        f"{field} must be {PROVENANCE_HASH_LENGTH} hexadecimal characters — "
        "the sha256 digest of one term of the trial's provenance (§8's "
        "provenance triple feature 87 stamps on every trial_ledger row: the "
        "frozen evaluator that scored the trial, the sealed snapshot it was "
        f"scored against and the cost model that priced it), got {value!r} "
        f"({type(value).__name__}). A short hash, a truncated value or a "
        "non-hex token names no evaluator, snapshot or cost model this "
        "system recorded, and a row stamped with it would be provenance no "
        "audit can replay. The refusal happens before the seam is touched, "
        "so no sequence number is spent on it."
    )


def _validated_charge_units(value: object) -> float:
    """Feature 89's unit — what the trial cost, a positive finite real.

    ``1.0`` is an ordinary evaluation (:data:`DEFAULT_CHARGE_UNITS`); a
    cross-validated one whose folds each compare a fit against the same
    forward returns states the folds' count instead.  An ``int`` or a
    ``float`` — the two forms a caller states a cost in — normalises to
    :class:`float`, the form the ``REAL`` column holds, provided it is
    finite, positive and not a :class:`bool`.  A ``NaN`` is refused rather
    than passed: SQLite persists a ``NaN`` as ``NULL``, so it would land as
    the *absence* of a unit on a row this append-only ledger can never
    correct; an infinity would poison every later sum of the column; and a
    unit at or below zero is the spelling of "this evaluation was free",
    which no row this ledger records is (a trial that should not count
    against ``K_effective`` states ``charges_budget=False``, not a
    zero-cost charge).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluatorDebitError(
            f"charge_units must be a real number — §8's cost of one trial, "
            f"1.0 for an ordinary evaluation and more for a cross-validated "
            f"one whose folds each compare a fit against the same forward "
            f"returns (feature 89); got {value!r} "
            f"({type(value).__name__}). Every appended trial row is stamped "
            "with its unit, and a unit that is not a number is a cost no "
            "audit can sum."
        )
    units = float(value)
    if math.isnan(units) or math.isinf(units):
        raise EvaluatorDebitError(
            f"charge_units must be finite; got {value!r}. A non-finite unit "
            "is refused rather than forwarded: SQLite persists a NaN as "
            "NULL, so a NaN that reached the append would land as the "
            "*absence* of a unit on a row this ledger can never correct, and "
            "an infinity would poison every later sum of the column."
        )
    if units <= 0.0:
        raise EvaluatorDebitError(
            f"charge_units must be greater than zero; got {value!r}. A trial "
            "that cost nothing is not a charge — §6.1's step 11 debits even "
            "when the node fails — and 0.0 is the spelling of 'this "
            "evaluation was free', which no row this ledger records is. A "
            "trial that should not count against K_effective states "
            "charges_budget=False (feature 90), not a zero-cost charge."
        )
    return units


@dataclass(frozen=True)
class TrialCharge:
    """One trial's charge, as a value — what step 11 hands the ledger.

    The terms §8's ``trial_ledger`` row needs from the evaluator: the
    evaluation's two identities, the outcome it ended in, the budget
    directive the null oracle returned, the sequestered epoch the charge is
    booked against (feature 88), and the provenance triple that makes it
    reproducible (feature 87) — plus the unit that prices the trial
    (feature 89), which §8 gives a ``DEFAULT`` so omitting it states the
    ordinary ``1.0``.  Nothing here is an output of the pipeline's compute —
    which is the point, and the reason the charge is buildable on the
    failure path: a timeout, a crash or a refused contract leaves no priced
    bundle to reduce, but it always leaves a node, a campaign, an outcome
    and (from step 5 on, or the caller's conservative statement before it)
    a directive.  The epoch and the triple are the same kind of fact: the
    evaluator that reaches step 11 already holds the frozen image digest
    (feature 70), the sealed snapshot's hash (§4.2) and the loaded cost
    model's hash (feature 60), so they are supplied, never derived here.

    Construction validates and canonicalises, so an instance is
    trustworthy by construction — and the read-back in :func:`debit_trial`
    rebuilds the landed row through this same constructor, which is how a
    seam answer that drifted outside the vocabulary is refused rather than
    served.  Frozen, because the charge is append-only accounting's unit:
    a record of what an evaluation consumed is a fact, superseded by new
    rows, never edited.
    """

    #: The evaluated node — the identity the charge is keyed by and the
    #: ledger's idempotency key (§14: debits are idempotent by node_id).
    node_id: str
    #: The campaign the node belongs to — the other identity §8's row
    #: carries, so the charge joins to the campaign it was run under.
    campaign_id: str
    #: How the evaluation ended — one of :data:`TRIAL_OUTCOMES`, §8's
    #: closed vocabulary.  Required with no default for the same reason the
    #: ledger's own column is: the failure the charge is *for* is the fact
    #: the row exists to record, and there is no honest presumption.
    outcome: str
    #: §7.2's opaque budget directive — ``True`` when the trial consumed
    #: statistical budget, ``False`` for a null node — supplied as the bit
    #: itself or as the step-5/step-7 record that carries it, and never
    #: derived here (feature 90).  Normalised to the genuine bool at
    #: construction.
    charges_budget: bool | GatedTargets | PostCostReturns
    #: The sequestered epoch the charge is booked against — §8's
    #: ``epoch_id TEXT NOT NULL`` ("which sequestered epoch was charged"),
    #: feature 88's stamp and the grouping key ``K_effective`` is derived by
    #: (feature 93).  Required: the holdout is a depleting resource the
    #: sealing process has already chosen by the time the evaluator runs
    #: this step, and a charge that cannot name it is a charge no audit can
    #: place.
    #:
    #: Declared with :data:`_ABSENT` as its default — not because the epoch
    #: is optional (it is not), but so that *omitting* it raises this
    #: member's own :class:`~evaluator.EvaluatorDebitError` naming the
    #: field, rather than Python's arity ``TypeError``: the refusal is the
    #: point, and it must name what was not stated.  No legal value reaches
    #: the sentinel, so a defaulted omission and an explicit ``None`` are
    #: refused identically.
    epoch_id: str = _ABSENT
    #: The frozen evaluator that scored the trial — feature 70's sha256
    #: over the container image digest and the resolved configuration.  The
    #: first term of feature 87's provenance triple; 64 lowercase hex
    #: characters.  Required; nothing else on the row names *which*
    #: evaluator produced the charge.
    evaluator_hash: str = _ABSENT
    #: The sealed snapshot the trial was scored against — §4.2's sha256
    #: over the sorted file hashes, the universe definition and the schema
    #: version.  The second term of the triple, same shape and same reason
    #: for being required.
    snapshot_hash: str = _ABSENT
    #: The cost model that priced the trial — feature 60's sha256 over the
    #: loaded §6.2 cost-model document.  The third term of the triple, same
    #: shape and same reason for being required.
    cost_model_hash: str = _ABSENT
    #: What the trial cost — ``1.0`` for an ordinary evaluation, the folds'
    #: count for a cross-validated one (feature 89).  The only term here
    #: with a default, and the only one §8 gives a ``DEFAULT``
    #: (``charge_units REAL NOT NULL DEFAULT 1.0``): one unit is an ordinary
    #: trial's honest weight, so omitting it states the ordinary trial
    #: rather than presuming a fact.  Normalised to a positive finite float
    #: at construction, so a ``5`` and a ``5.0`` are one unit and a ``NaN``,
    #: ``inf``, ``0`` or negative unit is refused.  Declared last because a
    #: defaulted field may not precede the required ones above.
    charge_units: float = DEFAULT_CHARGE_UNITS

    def __post_init__(self) -> None:
        # frozen forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction.
        object.__setattr__(self, "node_id", _as_name(self.node_id, "node_id"))
        object.__setattr__(
            self, "campaign_id", _as_name(self.campaign_id, "campaign_id")
        )
        object.__setattr__(self, "outcome", _validated_outcome(self.outcome))
        object.__setattr__(
            self, "charges_budget", _directive(self.charges_budget)
        )
        object.__setattr__(
            self, "charge_units", _validated_charge_units(self.charge_units)
        )
        object.__setattr__(
            self, "epoch_id", _validated_epoch_id(self.epoch_id)
        )
        object.__setattr__(
            self,
            "evaluator_hash",
            _validated_provenance_hash(self.evaluator_hash, "evaluator_hash"),
        )
        object.__setattr__(
            self,
            "snapshot_hash",
            _validated_provenance_hash(self.snapshot_hash, "snapshot_hash"),
        )
        object.__setattr__(
            self,
            "cost_model_hash",
            _validated_provenance_hash(
                self.cost_model_hash, "cost_model_hash"
            ),
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"TrialCharge(node={self.node_id!r}, "
            f"campaign={self.campaign_id!r}, outcome={self.outcome!r}, "
            f"charges_budget={self.charges_budget}, "
            f"charge_units={self.charge_units!r}, epoch_id={self.epoch_id!r})"
        )


# -- The failure classification -------------------------------------------------


def _fail_class_outcome(fail_class: object) -> str:
    """One sandbox failure class, as §8 spells the outcome it names.

    ``'timeout'`` is its own outcome — the sandbox's hard kill, §8's own
    words — and every other class the sandbox records is an ``'error'``,
    §8's "failed any other way".  A class outside the sandbox's six is
    refused rather than guessed: the classifier must be total over the
    vocabulary it owns or say nothing, because a fabricated outcome would
    split every later "how did the trials end?" query into fragments the
    spec never named.
    """
    if fail_class == "timeout":
        return "timeout"
    if fail_class in _SANDBOX_FAIL_CLASSES:
        return "error"
    known = ", ".join(repr(cls) for cls in _SANDBOX_FAIL_CLASSES)
    raise EvaluatorDebitError(
        f"{fail_class!r} is not a failure class the sandbox records "
        f"({known}); a drifted vocabulary must not become a fabricated "
        "outcome. Pass the SandboxResult itself, its fail_class text, or "
        "the exception the pipeline raised — or state the outcome directly "
        "when the caller knows it (a tripwire verdict, a completed run)."
    )


def failure_outcome(failure: object) -> str:
    """Classify how an evaluation failed, as §8's four-way outcome.

    The failure path's other half: the charge carries its failure outcome
    (the feature's own words), and this function is where the pipeline's
    own failure vocabulary — the sandbox's recorded classes, the exceptions
    the host-side steps raise — becomes the one closed vocabulary the
    ledger's column speaks.  Accepted shapes:

    * a :class:`~evaluator.SandboxResult` — classified by its
      ``fail_class``; a run that *conformed* (``.ok``) is refused, because
      a completed run is not a failure and its outcome is ``'ok'``,
      stated by the caller that watched it complete, not classified from
      a failure it did not have;
    * the ``fail_class`` text — the vocabulary's own spelling, for a
      caller holding the recorded class rather than the result;
    * a raised exception — ``'error'``, including a raised
      :class:`TimeoutError`: the sandbox records its kills as values,
      never exceptions, so a timeout that arrives raised is a host-side
      failure wearing a familiar name.

    Never returns ``'ok'`` (nothing here completed) and never returns
    ``'tripwire_fail'`` (that verdict is step 10's to state, and lands
    with the tripwires member); both are statable on the charge directly.
    Anything else is refused, naming the accepted shapes.
    """
    if isinstance(failure, SandboxResult):
        if failure.ok:
            raise EvaluatorDebitError(
                "a conforming sandbox run is not a failure — its trial "
                "charges outcome 'ok', stated on the charge by the caller "
                "that watched the pipeline complete; failure_outcome "
                "classifies failures, and a completed run has none to "
                "classify (the charge would silently understate a "
                "successful evaluation as a failed one)"
            )
        if failure.fail_class is None:
            # Problems without a fail class: the signal ran, returned, and
            # the contract refused the return — §8's "a refused contract"
            # under 'error', the failed-any-other-way outcome.
            return "error"
        return _fail_class_outcome(failure.fail_class)
    if isinstance(failure, str):
        return _fail_class_outcome(failure)
    if isinstance(failure, BaseException):
        # Every raised failure is an 'error' — the timeout distinction is
        # the sandbox's recorded hard kill, and the sandbox never raises.
        return "error"
    raise EvaluatorDebitError(
        "failure_outcome classifies a SandboxResult, its fail_class text, "
        "or the exception the pipeline raised; got "
        f"{failure!r} ({type(failure).__name__}). An unrecognised shape "
        "has no outcome to classify, and guessing one would fabricate the "
        "very fact the charge exists to record."
    )


def charge_failure(
    node_id: str,
    campaign_id: str,
    failure: object,
    *,
    charges_budget: bool | GatedTargets | PostCostReturns,
    epoch_id: str = _ABSENT,
    evaluator_hash: str = _ABSENT,
    snapshot_hash: str = _ABSENT,
    cost_model_hash: str = _ABSENT,
    charge_units: float = DEFAULT_CHARGE_UNITS,
) -> TrialCharge:
    """Build the charge a failed evaluation leaves — the failure path's spelling.

    Feature 84's sentence as one call: the failed evaluation still consumed
    a hypothesis, so it is charged — with the outcome :func:`failure_outcome`
    classifies from the failure itself, and the budget directive the caller
    supplies (the step-5 or step-7 record when the failure happened after
    the gate answered; ``True`` — the conservative charge, the ledger's own
    statement for rows that predate the directive — when it did not).  The
    failure is accepted in every shape the classifier owns: a timed-out,
    crashed or contract-refusing :class:`~evaluator.SandboxResult`, a
    recorded ``fail_class`` text, or the exception a host-side step raised.

    The row's remaining terms are the same on the failure path as on the
    completed path, and are named for the same reason: the sequestered
    ``epoch_id`` the charge is booked against (feature 88) and the
    provenance triple — ``evaluator_hash``, ``snapshot_hash``,
    ``cost_model_hash`` (feature 87) — are facts about the *evaluation*
    that the failure does not unmake, and a charge that cannot name its
    holdout or its provenance is a charge no audit can place and no replay
    can reproduce.  ``charge_units`` may be stated when the failed
    evaluation was a cross-validated one whose folds were partly spent, and
    otherwise defaults to §8's ``1.0`` for an ordinary evaluation.

    Returns the :class:`TrialCharge` unpersisted — :func:`debit_trial` is
    the write — so a caller (or a test, or an audit) can inspect exactly
    what a failure is about to be charged for before it becomes
    irreversible.
    """
    return TrialCharge(
        node_id=node_id,
        campaign_id=campaign_id,
        outcome=failure_outcome(failure),
        charges_budget=charges_budget,
        epoch_id=epoch_id,
        evaluator_hash=evaluator_hash,
        snapshot_hash=snapshot_hash,
        cost_model_hash=cost_model_hash,
        charge_units=charge_units,
    )


# -- The debit ------------------------------------------------------------------


def _seam_field(record: object, name: str) -> Any:
    """One field of the seam's landed record, refusing its absence by name.

    The seam answers with the landed row, and the row must *say* every
    thing this step reads — ``seq``, ``node_id``, ``campaign_id``,
    ``outcome``, ``charges_budget``, ``charge_units``, ``epoch_id`` and the
    provenance triple.  A missing attribute is a seam that
    did not answer the question it was asked (a record of another shape,
    a half-built stub), and the refusal names the field so the seam's
    author learns which half is missing rather than meeting an opaque
    ``AttributeError`` from inside the step.
    """
    value = getattr(record, name, _MISSING)
    if value is _MISSING:
        raise EvaluatorDebitError(
            f"the ledger seam's landed record carries no {name!r}; the "
            "debit answers (record, appended), and the record must name "
            "the row it landed — seq, node_id, campaign_id, outcome and "
            "charges_budget — because the charge handed back is rebuilt "
            "from exactly those fields"
        )
    return value


def _names_same_identity(asked: str, landed: str) -> bool:
    """Whether two identity spellings name the same node or campaign.

    The ledger canonicalises UUID spellings at its write (uppercase,
    brace-wrapped and hyphen-less inputs all land as the one hyphenated
    lowercase form), so a raw text comparison would refuse a perfectly
    good debit over a spelling difference.  When both sides parse as
    UUIDs the comparison is by the identity they name; otherwise it is by
    text — an opaque spelling this member passed through unchanged, which
    only a non-UUID ledger could echo, and there the text *is* the
    identity.
    """
    try:
        return uuid.UUID(asked) == uuid.UUID(landed)
    except (ValueError, TypeError, AttributeError):
        return asked == landed


@dataclass(frozen=True)
class DebitedTrial:
    """The charge as the ledger now holds it — step 11's answer.

    ``charge`` is the *landed* row as a :class:`TrialCharge` — on an
    append, the charge this call asked for; on a retry, the prior row the
    idempotent debit was answered by, standing exactly as first written.
    ``seq`` is the sequence number the ledger assigned that row — the
    irreversible fact, the number that only ever moves forward.  ``appended``
    is whether *this* call wrote the row: ``False`` means this debit was a
    retry (§14's spot-reclaimed worker), answered by the prior sequence
    with nothing written, and the terms the retry handed it are visible
    only by comparison with the landed charge — deliberately so, because a
    retry must be answered, never refused.

    Construction validates, so a hand-built answer is held to the same
    terms the seam's is: the sequence is a number a ledger could assign,
    and the charge is a charge.
    """

    #: The landed row as a charge — what the ledger holds for the node.
    charge: TrialCharge
    #: The sequence number the ledger assigned the landed row — 1, 2, 3, …
    #: strictly increasing for the life of the table, never reused.
    seq: int
    #: Whether this call appended the row; ``False`` on an idempotent
    #: retry answered by the prior row.
    appended: bool

    def __post_init__(self) -> None:
        if not isinstance(self.charge, TrialCharge):
            raise EvaluatorDebitError(
                "a debited trial carries the landed row as a TrialCharge, "
                f"got {type(self.charge).__name__}"
            )
        if (
            isinstance(self.seq, bool)
            or not isinstance(self.seq, int)
            or self.seq < 1
        ):
            raise EvaluatorDebitError(
                f"seq must be an integer the ledger assigned (1 or greater); "
                f"got {self.seq!r}. The sequence is the charge's irreversible "
                "fact — the number the honest K counter moves forward by — "
                "and a value the ledger could not have assigned is a seam "
                "answer this step refuses to believe."
            )
        if not isinstance(self.appended, bool):
            raise EvaluatorDebitError(
                f"appended must be a bool — whether this call wrote the row "
                f"— got {self.appended!r} ({type(self.appended).__name__}); "
                "a bit is not an int that happens to be 0 or 1"
            )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"DebitedTrial(seq={self.seq}, appended={self.appended}, "
            f"outcome={self.charge.outcome!r})"
        )


def debit_trial(charge: TrialCharge, ledger: object) -> DebitedTrial:
    """Charge the ledger for one evaluation — pipeline step 11.

    The whole of the feature at its seam: the ``charge`` (built directly
    for a completed evaluation, or through :func:`charge_failure` for a
    failed one) is handed to the injected ``ledger`` — an object exposing
    ``debit(node_id, campaign_id, outcome, charges_budget, charge_units,
    epoch_id, evaluator_hash, snapshot_hash, cost_model_hash)`` that answers
    ``(record, appended)``, the shape the ledger member's ``TrialLedger``
    speaks structurally, with no adapter, and carrying the full row the
    ledger requires rather than the four terms the evaluator alone produced
    — and the answer comes back as a
    :class:`DebitedTrial`: the landed charge, its sequence, and whether
    this call wrote it.  The debit is idempotent by the node (§14: workers
    retry; a hypothesis is charged once), and nothing here offers — or
    could offer — a spelling that un-charges a row: reversal is a new row
    in a ledger this step can only append through.

    The step runs *after* the evaluation however it ended, and its
    failures are the charge's own, not the pipeline's: a ``charge`` that
    is not this step's record, a ``ledger`` without a callable ``debit``,
    an answer that is not the ``(record, appended)`` shape, a record
    missing a field, a sequence no ledger could assign, a landed row
    rebuilt outside the vocabulary by the constructor's read-back, an
    answer that names another node, or an appended row that disagrees
    with the charge it was just asked to write — each refused with
    :class:`~evaluator.EvaluatorDebitError`.  A charge missing a required
    term never reaches the seam at all: the constructor refuses an absent
    epoch or provenance term when the charge is stated, so this member's
    own error names the missing term and the ledger's sequence is never
    touched.  The seam's own failures, by contrast, propagate as the
    ledger member's, unwrapped: a store error is the ledger's to report,
    the same stance the oracle and cost-schedule seams take, and dressing
    it as a debit error would hide which side of the seam failed.

    On a retry nothing is written and nothing is refused: the landed
    charge is the prior row's, ``appended`` is ``False``, and the outcome
    a retry asked for is the loser the append-only ledger already
    documents — visible by comparing the landed charge with the asked-for
    one, and deliberately not an error, because the retry is the §14
    contract working.
    """
    if not isinstance(charge, TrialCharge):
        raise EvaluatorDebitError(
            "debit_trial charges step 11's own record — a TrialCharge, "
            "built directly for a completed evaluation or through "
            f"charge_failure for a failed one — got {type(charge).__name__}; "
            "the charge's terms are validated where they are stated, and a "
            "debit of anything else would bypass that validation"
        )
    debit = getattr(ledger, "debit", None)
    if not callable(debit):
        raise EvaluatorDebitError(
            "the ledger must be an object exposing "
            "debit(node_id, campaign_id, outcome, charges_budget) that "
            "answers (record, appended) — the trial ledger the workspace's "
            "ledger member speaks, injected here because this member "
            f"imports no sibling — got {type(ledger).__name__}"
        )
    # The seam's failures are its own and propagate unwrapped; only the
    # answer's shape is this step's to check.  Every term §8's row needs
    # crosses the seam, because the ledger validates the epoch and the
    # provenance triple with required=True and refuses a charge that cannot
    # name them — a four-term debit is answered by a refusal, not a row.
    answer = debit(
        charge.node_id,
        charge.campaign_id,
        charge.outcome,
        charge.charges_budget,
        charge.charge_units,
        charge.epoch_id,
        charge.evaluator_hash,
        charge.snapshot_hash,
        charge.cost_model_hash,
    )
    if not isinstance(answer, tuple) or len(answer) != 2:
        raise EvaluatorDebitError(
            "the ledger seam must answer a debit with (record, appended) — "
            f"the landed row and whether this call wrote it — got {answer!r} "
            f"({type(answer).__name__}); the idempotent debit's two-part "
            "answer is what makes a retry distinguishable from an append, "
            "and a seam that cannot say both cannot be charged through"
        )
    record, appended = answer
    if not isinstance(appended, bool):
        raise EvaluatorDebitError(
            "the ledger seam's appended flag must be a genuine bool — "
            f"whether this call wrote the row — got {appended!r} "
            f"({type(appended).__name__}); a bit is not an int that "
            "happens to be 0 or 1"
        )
    seq = _seam_field(record, "seq")
    # Read back through the constructors rather than trusted: the landed
    # row is rebuilt as a charge (outcome, directive and names revalidated
    # where they are stated), and the sequence is held to what a ledger
    # could assign — the same defence the identity store's read path
    # applies to its own rows, for the same reason.
    landed = TrialCharge(
        node_id=_seam_field(record, "node_id"),
        campaign_id=_seam_field(record, "campaign_id"),
        outcome=_seam_field(record, "outcome"),
        charges_budget=_seam_field(record, "charges_budget"),
        epoch_id=_seam_field(record, "epoch_id"),
        evaluator_hash=_seam_field(record, "evaluator_hash"),
        snapshot_hash=_seam_field(record, "snapshot_hash"),
        cost_model_hash=_seam_field(record, "cost_model_hash"),
        charge_units=_seam_field(record, "charge_units"),
    )
    debited = DebitedTrial(charge=landed, seq=seq, appended=appended)
    if not _names_same_identity(charge.node_id, landed.node_id):
        raise EvaluatorDebitError(
            f"the ledger seam answered a debit for node {charge.node_id!r} "
            f"with a row for node {landed.node_id!r}; a charge for one "
            "evaluation cannot be answered by another's row, and a seam "
            "that does is miswired at the node it debits"
        )
    if appended and (
        not _names_same_identity(charge.campaign_id, landed.campaign_id)
        or (
            landed.outcome,
            landed.charges_budget,
            landed.charge_units,
            landed.epoch_id,
            landed.evaluator_hash,
            landed.snapshot_hash,
            landed.cost_model_hash,
        )
        != (
            charge.outcome,
            charge.charges_budget,
            charge.charge_units,
            charge.epoch_id,
            charge.evaluator_hash,
            charge.snapshot_hash,
            charge.cost_model_hash,
        )
    ):
        raise EvaluatorDebitError(
            f"the ledger seam appended a row that disagrees with the charge "
            f"it was asked to write (asked outcome {charge.outcome!r}, "
            f"directive {charge.charges_budget!r}, units "
            f"{charge.charge_units!r}, epoch {charge.epoch_id!r}, provenance "
            f"({charge.evaluator_hash!r}, {charge.snapshot_hash!r}, "
            f"{charge.cost_model_hash!r}), campaign {charge.campaign_id!r}; "
            f"landed {landed.outcome!r}, {landed.charges_budget!r}, "
            f"{landed.charge_units!r}, {landed.epoch_id!r}, "
            f"({landed.evaluator_hash!r}, {landed.snapshot_hash!r}, "
            f"{landed.cost_model_hash!r}), {landed.campaign_id!r}); an "
            "appended row is written from this call's own terms, so a "
            "disagreement is a seam that did not write what it was handed"
        )
    return debited
