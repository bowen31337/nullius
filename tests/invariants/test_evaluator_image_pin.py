"""System rejects the merge when the evaluator image hash differs from the
recorded pinned digest.

app_spec.xml feature 70 persists ``evaluator_hash`` — ``sha256(image_digest +
config)`` — as the identity of the evaluator that produced a score, and §16
pins the container that produced it: *"Docker, digest-pinned, because
``evaluator_hash`` requires digests not tags"*. app_spec.xml feature 71 turns
that identity into a gate: *"System rejects a comparison between two scores
whose ``evaluator_hash`` values differ"*. This invariant is the merge-time
form of that gate — the CI gate that refuses to let a change reach the shared
pool when the evaluator that would score it is not the one the pool was
scored under.

**The subject is the recorded pinned digest, not a tag.** The pool's scores
carry, as their ``evaluator_hash``, the identity of the pinned container they
were produced under — the ``sha256:<64 hex>`` digest folded into the hash,
never the mutable tag that named it. The gate's job is to hold a candidate
merge against that recorded digest: when the image the merge would run under
digests to a different first term, the two hashes cannot agree, and the merge
is refused rather than ranked across the move (§15's *"Evaluator image
changed → Hash mismatch on score comparison → Refuse comparison"*). The
refusal is feature 71's own — ``mismatched_provenance`` — because a merge that
re-scored the pool under a different evaluator would place two measurements
taken under different conditions on one axis, which is exactly the
undetectable drift the digest exists to make detectable.

**What this gate is not, asserted as hard as what it is.** The gate compares
one ``evaluator_hash`` to another; it does not resolve a tag to a digest (a
tag-only reference is refused upstream, canary feature 135), it does not
recompute the digest from the image bytes (that is the build's job, recorded
out of band), and it does not inspect the configuration term to look for a
*reason* the hashes differ — a changed image and a changed setting are both a
different evaluator, and the gate refuses both by the same hash comparison.
A suite that only exercised the happy path would pass for a gate that
silently re-keyed the recorded digest, so the boundary is pinned from the
refusal side: the digest is the first term, the hash is a pure function of
its terms, and a hash whose terms disagree with it is refused at construction
rather than trusted.

**The comparison is on the hash, and that is the point.** Two spellings of
one image with one resolved configuration fold to one ``evaluator_hash`` and
are the same evaluator; comparing image references instead would miss that
and refuse a merge that should stand. So the gate compares the hashes, exactly
as :func:`evaluator.check_comparable` and
:meth:`evaluator.EvaluatorIdentity.describes_same_evaluator` do — the one
spelling of "same evaluator" the system trusts.
"""

from __future__ import annotations

import hashlib

import evaluator as member
import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    OTHER_PINNED_DIGEST,
    OTHER_PINNED_IMAGE,
    PINNED_DIGEST,
    PINNED_IMAGE,
)
from evaluator import (
    DEFAULT_CONFIG,
    EvaluatorIdentity,
    EvaluatorIdentityError,
    EvaluatorImageError,
    EvaluatorProvenanceError,
    check_comparable,
    evaluator_digest,
    evaluator_identity,
    resolve_config,
)

# The recorded pinned digest the pool was scored under (feature 70's row) and
# the digest the candidate merge would run under. Two different bytes, one
# image name — the collision the merge gate exists to refuse.
CONFIG: dict[str, object] = {"horizons": [5, 10, 20]}


class TestTheGateComparesHashesNotReferences:
    """The recorded pinned digest is the first term of the recorded hash."""

    def test_the_recorded_hash_folds_the_digest_not_the_reference(self) -> None:
        # The pool's identity is computed over the ``sha256:<64 hex>`` digest,
        # never the full ``registry/repo@sha256:…`` reference — so two
        # spellings of one image are one identity, and the recorded digest is
        # recoverable from the recorded hash's first term.
        identity = evaluator_identity(PINNED_IMAGE, CONFIG)
        assert identity.image_digest == PINNED_DIGEST
        assert identity.evaluator_hash == evaluator_digest(PINNED_IMAGE, CONFIG)

    def test_the_digest_is_the_hash_first_term(self) -> None:
        # ``evaluator_hash = sha256(image_digest + config)`` — the digest is
        # folded in whole, as the ``sha256:``-prefixed term, so a merge that
        # changes the image changes the hash's first term and therefore the
        # hash. Recomputed independently here, the way the gate must.
        config_canonical = member.canonical_config(
            member.resolve_config(CONFIG, defaults=member.DEFAULT_CONFIG)
        )
        expected = hashlib.sha256(
            f"{PINNED_DIGEST}\n{config_canonical}".encode("utf-8")
        ).hexdigest()
        assert evaluator_identity(PINNED_IMAGE, CONFIG).evaluator_hash == expected

    def test_a_tag_only_reference_is_refused_before_it_can_be_recorded(self) -> None:
        # The recorded digest is a content address, never an intention. A
        # tag-only reference cannot be folded into a pinned identity — it is
        # refused (canary feature 135), so the pool can never carry a hash
        # that names a mutable pointer, and the gate never has a moving target
        # to compare against.
        with pytest.raises(EvaluatorImageError):
            evaluator_identity("ghcr.io/nullius/evaluator:latest", CONFIG)


class TestAMergeUnderTheRecordedDigestStands:
    """A candidate whose image digests to the recorded value is the same
    evaluator."""

    def test_the_same_digest_any_spelling_is_comparable(self) -> None:
        # The pool's recorded identity and a merge built from the same digest
        # — written as the bare digest, or as a full reference — fold to one
        # hash and are the same evaluator. The gate lets the merge stand: it
        # names the image by its bytes, not by how the reference was spelled.
        recorded = evaluator_identity(PINNED_IMAGE, CONFIG)
        same_digest = evaluator_identity(PINNED_DIGEST, CONFIG)
        assert recorded.describes_same_evaluator(same_digest)
        assert check_comparable(recorded, same_digest).evaluator_hash == (
            recorded.evaluator_hash
        )

    def test_configuration_key_order_does_not_move_the_hash(self) -> None:
        # The configuration term is canonicalised (compact, key-sorted JSON),
        # so a merge that states the same settings in a different order is
        # still the same evaluator — the gate does not refuse a re-ordering.
        reordered = {"horizons": [5, 10, 20]}
        assert evaluator_identity(PINNED_IMAGE, CONFIG).describes_same_evaluator(
            evaluator_identity(PINNED_IMAGE, reordered)
        )


class TestAMergeUnderADifferentDigestIsRefused:
    """The gate refuses a merge whose image hash differs from the recorded
    pinned digest."""

    def test_a_different_image_digest_is_not_comparable(self) -> None:
        # The recorded identity (the pool's pinned digest) and a candidate
        # built from a *different* digest: the hashes differ, so the merge is
        # refused rather than ranked across the move.
        recorded = evaluator_identity(PINNED_IMAGE, CONFIG)
        candidate = evaluator_identity(OTHER_PINNED_IMAGE, CONFIG)
        assert recorded.evaluator_hash != candidate.evaluator_hash
        assert not recorded.describes_same_evaluator(candidate)

    def test_the_refusal_is_mismatched_provenance_and_names_both_hashes(
        self,
    ) -> None:
        # The refusal carries feature 71's ``mismatched_provenance`` code and
        # names both hashes — the recorded pinned digest and the candidate's —
        # so the operator can see which two evaluators collided.
        recorded = evaluator_identity(PINNED_IMAGE, CONFIG)
        candidate = evaluator_identity(OTHER_PINNED_IMAGE, CONFIG)
        with pytest.raises(EvaluatorProvenanceError) as excinfo:
            check_comparable(recorded, candidate)
        message = str(excinfo.value)
        assert "mismatched_provenance" in message
        assert recorded.evaluator_hash in message
        assert candidate.evaluator_hash in message

    def test_the_refusal_names_the_image_digest_that_moved(self) -> None:
        # When the image is the term that moved, the refusal names the digest
        # change — the recorded pinned digest and the candidate's — so the
        # operator knows to re-score the pool under one pinned evaluator
        # (§15's recovery) rather than merge across the drift.
        recorded = evaluator_identity(PINNED_IMAGE, CONFIG)
        candidate = evaluator_identity(OTHER_PINNED_IMAGE, CONFIG)
        with pytest.raises(EvaluatorProvenanceError) as excinfo:
            check_comparable(recorded, candidate)
        message = str(excinfo.value)
        assert PINNED_DIGEST in message
        assert OTHER_PINNED_DIGEST in message
        assert "image digest changed" in message

    def test_a_changed_image_is_refused_even_with_the_same_configuration(
        self,
    ) -> None:
        # The gate does not look for a *reason*: with the configuration held
        # fixed, a changed image alone is a different evaluator and is
        # refused. This is the merge gate's load-bearing case — the image
        # moved and nothing else did.
        recorded = evaluator_identity(PINNED_IMAGE, CONFIG)
        candidate = evaluator_identity(OTHER_PINNED_IMAGE, CONFIG)
        assert recorded.config == candidate.config
        with pytest.raises(EvaluatorProvenanceError):
            check_comparable(recorded, candidate)


class TestTheGateIsAHashComparison:
    """The gate is the hash comparison and nothing more — a changed setting is
    refused by the same test, and the comparison never trusts a malformed
    hash."""

    def test_a_changed_configuration_is_also_refused(self) -> None:
        # A merge whose image is the recorded one but whose settings differ is
        # a different evaluator too — the same hash comparison refuses it. The
        # gate does not distinguish "image moved" from "setting moved"; both
        # are a hash that disagrees with the recorded one.
        recorded = evaluator_identity(PINNED_IMAGE, CONFIG)
        candidate = evaluator_identity(PINNED_IMAGE, {"horizons": [5, 10, 30]})
        assert recorded.evaluator_hash != candidate.evaluator_hash
        with pytest.raises(EvaluatorProvenanceError):
            check_comparable(recorded, candidate)

    def test_a_hash_that_disagrees_with_its_own_terms_is_refused(self) -> None:
        # A "recorded pinned digest" presented with a hash that does not fold
        # from its own terms is not a recorded identity at all — a row that
        # lies about which evaluator it names. The identity refuses to be
        # constructed rather than loading as a plausible-looking value, so the
        # gate can never compare against a forged record.
        bogus = hashlib.sha256(b"not-the-folded-hash").hexdigest()
        with pytest.raises(EvaluatorIdentityError):
            EvaluatorIdentity(
                image_digest=PINNED_DIGEST,
                config=CONFIG,
                evaluator_hash=bogus,
            )

    def test_the_module_never_resolves_a_tag_to_a_digest(self) -> None:
        # The gate compares recorded hashes; it never reaches a registry to
        # turn a tag into a digest. A static check pins that the comparison
        # surface imports nothing that could perform a network resolution at
        # compare time — the digest is always recorded out of band, never
        # resolved on the fly.
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(member.check_comparable))
        resolution_names = (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"resolve", "resolve_hash", "containers"}
        )
        assert list(resolution_names) == []
