"""Refusing a cross-evaluator comparison (app_spec.xml feature 71).

Feature 71's sentence — *"System rejects a comparison between two scores
whose ``evaluator_hash`` values differ, which returns a ``mismatched_provenance``
error message"* — is the refusal the determinism contract (§12) and the
failure table (§15) both depend on: "Pinned evaluator … refuse cross-hash
comparison", and "Evaluator image changed → Hash mismatch on score comparison
→ Refuse comparison; re-score the pool (budgeted) or fork the pool".

The comparison is on the *hash*, not the terms: two spellings of one image
with one resolved configuration fold to one hash and are the same evaluator,
which comparing references would miss. So the tests below pin the refusal on
``evaluator_hash`` equality, and the message on naming both hashes and the
term that moved — the refusal is only actionable when it can say *which*
evaluator to re-score the pool under, which is the whole reason feature 70
carries the terms beside the hash.

Two things the tests are careful *not* to assert:

* A mismatch is not a missing record. A score whose ``evaluator_hash`` was
  never persisted is a ``None`` from the store, not a mismatch between two
  present ones; the service's end-to-end path refuses it, but the pure
  :func:`check_comparable` is called with two identities the store already
  holds and so never sees it. Both spellings are pinned below, because the
  tempting "fix" for a missing record is to fold it into the mismatch, and
  the two are different failures.
* The comparison is not a value to branch around. The refusal is *raised*,
  so a cross-evaluator comparison can never silently reach a ranking or a
  difference. A test that expected a ``False`` return would be testing a
  feature this one deliberately does not have.
"""

from __future__ import annotations

import dataclasses

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    OTHER_PINNED_DIGEST,
    OTHER_PINNED_IMAGE,
    PINNED_DIGEST,
    PINNED_IMAGE,
)

from evaluator import (
    EvaluatorIdentity,
    EvaluatorIdentityStore,
    EvaluatorProvenanceError,
    EvaluatorService,
    ProvenanceCheck,
    check_comparable,
    evaluator_identity,
)


def _identity(image: str, config: dict | None = None) -> EvaluatorIdentity:
    """One score's provenance — the identity a score's hash resolves to."""
    return evaluator_identity(image, config, defaults={})


# -- The happy path: same evaluator is comparable ----------------------------


def test_two_scores_from_one_evaluator_are_comparable() -> None:
    # The feature's whole sentence, on its positive side: two scores produced
    # by the same evaluator share a hash, and the check certifies the shared
    # one.
    left = _identity(PINNED_IMAGE, {"purge_periods": 5})
    right = _identity(PINNED_IMAGE, {"purge_periods": 5})
    verdict = check_comparable(left, right)
    assert isinstance(verdict, ProvenanceCheck)
    assert verdict.evaluator_hash == left.evaluator_hash
    assert verdict.evaluator_hash == right.evaluator_hash


def test_two_spellings_of_one_image_are_one_evaluator() -> None:
    # The comparison is on the hash, not the reference: two spellings of one
    # image with one resolved configuration fold to one hash, so a score
    # written by a caller who spelled the image one way compares clean against
    # one who spelled it another.
    spelled_out = _identity("ghcr.io/nullius/evaluator@sha256:" + "ab" * 32)
    bare_digest = _identity("sha256:" + "ab" * 32)
    assert spelled_out.evaluator_hash == bare_digest.evaluator_hash
    verdict = check_comparable(spelled_out, bare_digest)
    assert verdict.evaluator_hash == spelled_out.evaluator_hash


def test_the_verdict_is_frozen_and_hashable() -> None:
    # A value to file beside the evaluation or compare across checks without
    # recomputing — the same contract the purge and gate verdicts hold to.
    left = _identity(PINNED_IMAGE)
    verdict = check_comparable(left, _identity(PINNED_IMAGE))
    assert hash(verdict) == hash(ProvenanceCheck(evaluator_hash=left.evaluator_hash))
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.evaluator_hash = "x" * 64  # type: ignore[misc]


# -- The refusal: different evaluators cannot be compared --------------------


def test_two_scores_from_different_images_are_refused() -> None:
    # §15's "Evaluator image changed" case: the container moved between the
    # two scores, so they are different measurements wearing the same name.
    left = _identity(PINNED_IMAGE)
    right = _identity(OTHER_PINNED_IMAGE)
    with pytest.raises(EvaluatorProvenanceError, match="mismatched_provenance") as excinfo:
        check_comparable(left, right)
    # The message names both hashes, so the refusal says which two collided.
    message = str(excinfo.value)
    assert left.evaluator_hash in message
    assert right.evaluator_hash in message
    # And it names the term that moved — the image digest here.
    assert "image digest changed" in message
    assert PINNED_DIGEST in message
    assert OTHER_PINNED_DIGEST in message


def test_two_scores_with_different_configurations_are_refused() -> None:
    # The second term moved: one evaluator, same image, but a different
    # resolved configuration is a different evaluator (§15: "a deployment
    # that changes a knob"). The refusal names the knob rather than the image.
    left = _identity(PINNED_IMAGE, {"purge_periods": 5})
    right = _identity(PINNED_IMAGE, {"purge_periods": 9})
    with pytest.raises(EvaluatorProvenanceError, match="mismatched_provenance") as excinfo:
        check_comparable(left, right)
    message = str(excinfo.value)
    assert "the resolved configuration differs" in message
    assert "purge_periods" in message
    # The image did not move, so the refusal does not claim it did.
    assert "image digest changed" not in message


def test_the_refusal_names_the_moved_configuration_key_not_the_unchanged_ones() -> None:
    # When several settings differ, only the ones that moved are named — the
    # operator is pointed at the knob, not handed the whole configuration.
    left = _identity(PINNED_IMAGE, {"purge_periods": 5, "embargo_periods": 2})
    right = _identity(PINNED_IMAGE, {"purge_periods": 9, "embargo_periods": 2})
    with pytest.raises(EvaluatorProvenanceError, match="mismatched_provenance") as excinfo:
        check_comparable(left, right)
    message = str(excinfo.value)
    assert "purge_periods" in message
    assert "embargo_periods" not in message


def test_both_image_and_configuration_moved_are_both_named() -> None:
    # When both terms move, the refusal names both — the recovery (§15) needs
    # to know which of the two axes the pool must be re-scored back onto.
    left = _identity(PINNED_IMAGE, {"purge_periods": 5})
    right = _identity(OTHER_PINNED_IMAGE, {"purge_periods": 9})
    with pytest.raises(EvaluatorProvenanceError, match="mismatched_provenance") as excinfo:
        check_comparable(left, right)
    message = str(excinfo.value)
    assert "image digest changed" in message
    assert "the resolved configuration differs" in message


def test_the_refusal_message_names_the_feature_and_the_recovery() -> None:
    # A refusal that only said "the hashes differ" would tell a caller *that*
    # two evaluators collided, not *why it matters*. The message ties the
    # refusal back to the feature and to §15's recovery.
    with pytest.raises(EvaluatorProvenanceError, match="feature 71") as excinfo:
        check_comparable(_identity(PINNED_IMAGE), _identity(OTHER_PINNED_IMAGE))
    assert "re-score the pool" in str(excinfo.value)


def test_a_mismatch_is_raised_not_returned() -> None:
    # The refusal is not a value to branch around: a cross-evaluator
    # comparison must never silently reach a ranking or a difference.
    with pytest.raises(EvaluatorProvenanceError):
        check_comparable(_identity(PINNED_IMAGE), _identity(OTHER_PINNED_IMAGE))


# -- The comparison is on the hash, not the terms ----------------------------


def test_the_comparison_is_on_the_hash_not_the_reference_spelling() -> None:
    # The decisive property: a caller comparing a score's hash against the
    # current image by reference would agree by construction and never detect
    # that the image moved. Comparing the hashes — the persisted values — is
    # what catches the move.
    original = _identity(PINNED_IMAGE)
    moved = _identity(OTHER_PINNED_IMAGE)
    assert original.evaluator_hash != moved.evaluator_hash
    with pytest.raises(EvaluatorProvenanceError):
        check_comparable(original, moved)


# -- The inputs are identities, not raw values -------------------------------


def test_a_non_identity_left_is_refused() -> None:
    with pytest.raises(EvaluatorProvenanceError, match="EvaluatorIdentity"):
        check_comparable("not-an-identity", _identity(PINNED_IMAGE))  # type: ignore[arg-type]


def test_a_non_identity_right_is_refused() -> None:
    with pytest.raises(EvaluatorProvenanceError, match="EvaluatorIdentity"):
        check_comparable(_identity(PINNED_IMAGE), object())  # type: ignore[arg-type]


# -- End to end: the service compares two scores by their stored hashes ------


def test_the_service_compares_two_persisted_scores(evaluator_env: dict[str, str]) -> None:
    # Feature 71's full path: two scores each carry an ``evaluator_hash``; the
    # service resolves each to the identity the store persisted under it and
    # refuses when the two differ. A comparison against a *stored* value — not
    # a recomputed one — is what detects that the image moved between the two
    # scores (§15).
    store = EvaluatorIdentityStore.resolve()
    original = store.persist(_identity(PINNED_IMAGE))

    service = EvaluatorService.from_env(evaluator_env)
    verdict = service.comparable(original.evaluator_hash, original.evaluator_hash)
    assert verdict.evaluator_hash == original.evaluator_hash


def test_the_service_refuses_a_cross_evaluator_comparison(evaluator_env: dict[str, str]) -> None:
    store = EvaluatorIdentityStore.resolve()
    original = store.persist(_identity(PINNED_IMAGE))
    other = store.persist(_identity(OTHER_PINNED_IMAGE))

    service = EvaluatorService.from_env(evaluator_env)
    with pytest.raises(EvaluatorProvenanceError, match="mismatched_provenance"):
        service.comparable(original.evaluator_hash, other.evaluator_hash)


def test_the_service_refuses_a_score_whose_provenance_was_never_persisted(
    evaluator_env: dict[str, str],
) -> None:
    # A mismatch is not a missing record — but a score whose identity was
    # never persisted is one the system cannot place on an axis with another,
    # so the end-to-end path refuses it too, with the same code.
    store = EvaluatorIdentityStore.resolve()
    original = store.persist(_identity(PINNED_IMAGE))

    service = EvaluatorService.from_env(evaluator_env)
    never_recorded = _identity(OTHER_PINNED_IMAGE).evaluator_hash
    assert store.resolve_hash(never_recorded) is None
    with pytest.raises(EvaluatorProvenanceError, match="never persisted"):
        service.comparable(original.evaluator_hash, never_recorded)


def test_the_service_refuses_when_the_second_score_was_never_persisted(
    evaluator_env: dict[str, str],
) -> None:
    store = EvaluatorIdentityStore.resolve()
    original = store.persist(_identity(PINNED_IMAGE))

    service = EvaluatorService.from_env(evaluator_env)
    never_recorded = _identity(OTHER_PINNED_IMAGE).evaluator_hash
    with pytest.raises(EvaluatorProvenanceError, match="never persisted"):
        service.comparable(never_recorded, original.evaluator_hash)


# -- The verdict record's own contract ---------------------------------------


def test_a_verdict_with_a_malformed_hash_is_refused() -> None:
    # A ProvenanceCheck must carry a well-formed hash — the same canonicalisa-
    # tion every other path applies — so a hand-built record cannot name a
    # hash no reader could look up.
    with pytest.raises(EvaluatorProvenanceError, match="64-character"):
        ProvenanceCheck(evaluator_hash="not-a-hash")
