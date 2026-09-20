"""Refusing a cross-evaluator comparison — feature 71.

app_spec.xml feature 71: *"System rejects a comparison between two scores
whose ``evaluator_hash`` values differ, which returns a ``mismatched_provenance``
error message."* docs/nullius-tech-architecture.md §12's determinism table
pins what it is *for* — "Pinned evaluator: container digest in
``evaluator_hash``; refuse cross-hash comparison" — and §15's failure table
supplies the recovery when the image moves: "Evaluator image changed → Hash
mismatch on score comparison → Refuse comparison; re-score the pool
(budgeted) or fork the pool".

**The comparison is on the hash, and that is the point.** Two scores are
compared only when they were produced by the *same* evaluator — the same
container image and the same resolved configuration, the two terms feature
70 folds into one ``evaluator_hash``. A score carries that hash as its
provenance; to compare two scores the caller resolves each hash to the
:class:`~evaluator.EvaluatorIdentity` that produced it (the store's
:meth:`~evaluator.EvaluatorIdentityStore.resolve_hash`, which this package's
own docstring names as "the lookup feature 71's comparison … use[s]") and
hands the two identities here. The verdict is ``left.evaluator_hash ==
right.evaluator_hash`` — nothing else. Comparing the terms instead would be
a second, subtly different test: two spellings of one image with one
resolved configuration fold to one hash and are the same evaluator, which
comparing references would miss. So the hash is compared, exactly as
:func:`~evaluator.EvaluatorIdentity.describes_same_evaluator` compares two
identities, and this function is that question with a message attached.

**The refusal is actionable, not just loud.** A bare "the hashes differ"
tells a caller *that* two evaluators collided but not *which* or *how*, and
the hash is one-way — it cannot say which term moved. So when the hashes
differ this module names both, and names the term that moved: the image
digest, when the container changed, and the configuration keys, when a
setting did. That is the whole reason feature 70 carries the terms beside
the hash — a comparison refusal is only useful when it can point back at the
stored row (or the operator's record of the run) and say which evaluator to
re-score the pool under. The recovery is §15's: a changed evaluator is a
*different measurement wearing the same name*, so the pool is re-scored under
one pinned evaluator rather than ranked across the move.

**A mismatch is not a missing record.** This function is called with two
identities the store already holds. A score whose ``evaluator_hash`` was
never persisted is a *missing* record — :meth:`~evaluator.EvaluatorIdentityStore.resolve_hash`
returns ``None`` for it, a discoverable state the comparison layer decides
how to handle — not a mismatch between two present ones, and so it is
deliberately not this function's error. What feature 71 refuses is the
comparison of two scores that *both* have a provenance and whose provenances
disagree.

**The layering note.** This module is stdlib-only — two hashes, two
mappings, a set difference — no polars, no pyarrow, no lake, no environment,
no numerics. The values in and out are identities and a plain verdict
record, because a provenance check is a statement about which evaluator a
score belongs to, not a computation over a frame. Importing this member
therefore costs composition — and the replay path §1 forbids from reaching
the evaluator — nothing at all, matching the import-cheap discipline the
rest of this package holds to. It imports one sibling, :mod:`._identity`,
for the type it compares and the canonicalisation that type already applies,
so the hashes it compares are the same ones feature 70 persisted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._errors import EvaluatorProvenanceError
from ._identity import EvaluatorIdentity

__all__ = [
    "ProvenanceCheck",
    "check_comparable",
]


def _config_diff(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> tuple[str, ...]:
    """The configuration keys on which two resolved configurations disagree.

    The sorted union of keys whose value differs between the two sides, or
    that one side lacks — the settings an operator would inspect to learn
    *how* the configuration term moved. Both mappings are the record's
    already-resolved configuration, so the comparison is over effective
    settings rather than the documents that produced them. A key absent on
    one side is a difference: a setting that was added or dropped is as much
    a different evaluator as one whose value changed.
    """
    differing: set[str] = set()
    for key in set(left) | set(right):
        if left.get(key) != right.get(key):
            differing.add(key)
    return tuple(sorted(differing))


@dataclass(frozen=True)
class ProvenanceCheck:
    """The verdict of a single cross-evaluator comparability check.

    What :func:`check_comparable` returns when two scores *are* comparable —
    when their ``evaluator_hash`` values agree and they were therefore
    produced by the same evaluator. It carries the one hash both scores
    share, the fact that lets a downstream ranking or difference treat them
    as one measurement. Carried beside the scores it certifies, filed in a
    report, or compared across checks without recomputing (frozen, hashable).
    """

    #: The ``evaluator_hash`` both scores carry — the identity they share.
    evaluator_hash: str

    def __post_init__(self) -> None:
        # A verdict that reports a shared hash must hold a well-formed one:
        # the same canonicalisation every other path applies, so the record
        # cannot name a hash that no reader could look up.
        if not isinstance(self.evaluator_hash, str) or len(self.evaluator_hash) != 64:
            raise EvaluatorProvenanceError(
                f"a ProvenanceCheck must carry a 64-character evaluator_hash, "
                f"got {self.evaluator_hash!r}"
            )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ProvenanceCheck(evaluator_hash={self.evaluator_hash!r})"


def check_comparable(left: EvaluatorIdentity, right: EvaluatorIdentity) -> ProvenanceCheck:
    """Certify that two scores can be compared — the refusal.

    Feature 71's sentence: *system rejects a comparison between two scores
    whose ``evaluator_hash`` values differ*. ``left`` and ``right`` are the
    two identities the scores carry as provenance — each resolved from its
    ``evaluator_hash`` by the store (see the module docstring). The check
    compares the two hashes: when they agree the scores came from the same
    evaluator and a :class:`ProvenanceCheck` naming the shared hash is
    returned; when they differ the comparison is **refused** with an
    :class:`~evaluator.EvaluatorProvenanceError` whose ``mismatched_provenance``
    message names both hashes and the term that moved.

    The refusal is not a value to branch around — it is raised, so a
    cross-evaluator comparison can never silently reach a ranking or a
    difference and place two measurements taken under different conditions on
    one axis. The message is actionable rather than merely loud: it names the
    left and right hashes, and — because the identities carry their terms —
    names the image digest when the container changed and the configuration
    keys when a setting did, pointing the operator at the evaluator to
    re-score the pool under (§15's recovery) rather than leaving them to
    reverse a one-way hash.
    """
    if not isinstance(left, EvaluatorIdentity):
        raise EvaluatorProvenanceError(
            "check_comparable certifies two scores' provenance — an "
            f"EvaluatorIdentity each — got {type(left).__name__} for the left; "
            "resolve each score's evaluator_hash to its identity before "
            "comparing"
        )
    if not isinstance(right, EvaluatorIdentity):
        raise EvaluatorProvenanceError(
            "check_comparable certifies two scores' provenance — an "
            f"EvaluatorIdentity each — got {type(right).__name__} for the "
            f"right; resolve each score's evaluator_hash to its identity "
            "before comparing"
        )

    left_hash = left.evaluator_hash
    right_hash = right.evaluator_hash
    if left_hash == right_hash:
        # Same evaluator: the two scores share one identity, and the shared
        # hash is what lets a downstream comparison treat them as one
        # measurement. (The hashes are already canonical — the record
        # normalises them at construction — so this is a plain equality.)
        return ProvenanceCheck(evaluator_hash=left_hash)

    # The hashes differ: the scores are different evaluators and cannot be
    # compared. Name both, then name the term that moved so the refusal is
    # actionable.
    image_moved = left.image_digest != right.image_digest
    config_diff = _config_diff(left.config, right.config)
    terms = []
    if image_moved:
        terms.append(
            f"the image digest changed ({left.image_digest} → {right.image_digest})"
        )
    if config_diff:
        terms.append(
            "the resolved configuration differs (keys: "
            f"{', '.join(config_diff)})"
        )
    if not terms:
        # The terms as read agree but the hashes do not — not reachable
        # through this package's own API (the hash is a pure function of the
        # terms, so equal terms fold to an equal hash), but stated rather
        # than left to imply a cause it does not have.
        moved = "an unstated term"
    else:
        moved = " and ".join(terms)
    raise EvaluatorProvenanceError(
        "mismatched_provenance: these two scores were produced by different "
        f"evaluators and cannot be compared — the left carries evaluator_hash "
        f"{left_hash} and the right {right_hash}; {moved}. app_spec.xml "
        "feature 71 refuses a comparison whose evaluator_hash values differ, "
        "and §15's recovery is to refuse the cross-hash comparison: a changed "
        "evaluator is a different measurement wearing the same name, so "
        "re-score the pool under one pinned evaluator rather than ranking "
        "across the move"
    )
