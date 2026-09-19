"""The ``evaluator_hash`` formula (app_spec.xml feature 70).

docs/nullius-tech-architecture.md §6 states it in one line —
``evaluator_hash = sha256(image_digest + config)`` — and feature 70 states
what the system does with it. These tests pin the formula's *byte-level*
spelling, because that is the part a future edit can silently break while
every high-level assertion still passes: a change to the separator, to the
encoding, or to which spelling of a term is folded leaves a function that
still returns 64 hex characters and still differs when its inputs differ, and
would invalidate every score in the pool.

So the tests below recompute the documented preimage independently — string
concatenation with ``"\n"``, ``.encode("utf-8")``, ``hashlib.sha256`` — and
assert the function agrees. A test that called the function twice and
compared would prove only that it is deterministic.
"""

from __future__ import annotations

import hashlib

import pytest

from evaluator import (
    DEFAULT_CONFIG,
    EVALUATOR_HASH_LENGTH,
    EvaluatorIdentity,
    EvaluatorIdentityError,
    EvaluatorConfigError,
    EvaluatorImageError,
    canonical_config,
    evaluator_digest,
    evaluator_identity,
    normalize_evaluator_hash,
    resolve_config,
)
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    OTHER_PINNED_DIGEST,
    OTHER_PINNED_IMAGE,
    PINNED_DIGEST,
    PINNED_IMAGE,
)


def _expected(digest: str, config: dict) -> str:
    """The §6 formula, recomputed the way the docstring spells it."""
    preimage = "\n".join((digest, canonical_config(config))).encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()


# -- The formula -------------------------------------------------------------


def test_the_hash_is_the_documented_sha256_over_the_two_terms() -> None:
    config = resolve_config({"purge_periods": 7}, defaults={})
    digest = evaluator_digest(PINNED_IMAGE, config, defaults={})
    assert digest == _expected(PINNED_DIGEST, config)
    assert len(digest) == EVALUATOR_HASH_LENGTH
    assert digest == digest.lower()


def test_the_hash_is_64_lowercase_hex_matching_the_spec_column() -> None:
    # The spec declares evaluator_hash CHAR(64) on node and trial_ledger, so
    # the width is a storage contract, not a coincidence.
    digest = evaluator_digest(PINNED_IMAGE)
    assert len(digest) == EVALUATOR_HASH_LENGTH
    assert set(digest) <= set("0123456789abcdef")


def test_the_two_terms_are_newline_framed_and_therefore_separable() -> None:
    # The framing is a separability guarantee: without a separator, a
    # configuration spelling ending where a following term begins could be
    # re-split two ways and two different evaluators share an identity. The
    # observable consequence is that moving a character across the seam
    # changes the hash.
    config_a = {"a": "x"}
    config_b = {"a": "x\n"}
    # "x\n" is not JSON-carryable as a raw newline, but canonical JSON escapes
    # it, so both fold without ambiguity and produce different hashes.
    digest_a = evaluator_digest(PINNED_IMAGE, config_a, defaults={})
    digest_b = evaluator_digest(PINNED_IMAGE, config_b, defaults={})
    assert digest_a != digest_b


def test_the_image_term_is_the_digest_not_the_reference() -> None:
    # One image, two spellings. If the reference were folded, a caller in one
    # registry and a caller in another would disagree about the same artifact
    # — §15's "sneakiest" failure mode arriving by a different road.
    short = "evaluator@sha256:" + "ab" * 32
    long = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32
    assert evaluator_digest(short) == evaluator_digest(long)


def test_the_config_term_is_folded_after_resolution() -> None:
    # "the resolved configuration" is the feature's word. Two callers who
    # reach the same effective settings by different documents are one
    # evaluator; one who reaches different settings is not.
    declared_only = evaluator_digest(PINNED_IMAGE, {"purge_periods": 20}, defaults={})
    via_defaults = evaluator_digest(PINNED_IMAGE, {}, defaults={"purge_periods": 20})
    assert declared_only == via_defaults

    different = evaluator_digest(PINNED_IMAGE, {"purge_periods": 21}, defaults={})
    assert different != declared_only


def test_key_order_and_whitespace_do_not_leak_into_the_identity() -> None:
    # The canonical spelling's whole job. A mapping has no natural byte
    # spelling, so without it two callers meaning the same evaluator would
    # compute different hashes for reasons that are not about the evaluator.
    one = evaluator_digest(PINNED_IMAGE, {"a": 1, "b": 2}, defaults={})
    other = evaluator_digest(PINNED_IMAGE, {"b": 2, "a": 1}, defaults={})
    assert one == other


def test_a_different_image_digest_is_a_different_evaluator() -> None:
    # §15's first row: the evaluator image changed. The hash is what lets a
    # comparison notice, so this is the property feature 71 is built on.
    assert evaluator_digest(PINNED_IMAGE) != evaluator_digest(OTHER_PINNED_IMAGE)


def test_a_different_configuration_is_a_different_evaluator() -> None:
    assert evaluator_digest(PINNED_IMAGE, {"horizons": [1, 5]}) != evaluator_digest(
        PINNED_IMAGE, {"horizons": [1, 2, 5, 10, 20]}
    )


def test_uppercase_digest_hex_normalizes_to_one_identity() -> None:
    upper = "evaluator@sha256:" + "AB" * 32
    lower = "evaluator@sha256:" + "ab" * 32
    assert evaluator_digest(upper) == evaluator_digest(lower)


def test_the_fold_is_stable_across_repeated_calls() -> None:
    # Determinism: the same inputs, the same value, every call and every
    # process. Nothing here may depend on dict iteration order or a clock.
    values = {evaluator_digest(PINNED_IMAGE, {"x": [1, 2, 3]}) for _ in range(8)}
    assert len(values) == 1


# -- The first term: the pinned image ----------------------------------------


def test_a_tag_only_reference_is_refused() -> None:
    # Canary feature 135 states this as its own feature, and architecture §16
    # gives the reason: a tag is a mutable pointer, so the same reference
    # resolves to different bytes over time and cannot name an evaluator.
    with pytest.raises(EvaluatorImageError, match="not digest-pinned"):
        evaluator_digest("nullius-evaluator:latest")


def test_a_bare_image_name_is_refused() -> None:
    with pytest.raises(EvaluatorImageError, match="not digest-pinned"):
        evaluator_digest("nullius-evaluator")


def test_a_tag_beside_a_digest_is_allowed_because_the_digest_wins() -> None:
    # A reference may carry both; the digest is the identity term, and the
    # tag is decoration that cannot change the bytes it names.
    with_tag = "ghcr.io/nullius/evaluator:v1@sha256:" + "ab" * 32
    assert evaluator_digest(with_tag) == evaluator_digest(PINNED_IMAGE)


def test_a_digest_of_the_wrong_width_is_refused() -> None:
    with pytest.raises(EvaluatorImageError):
        evaluator_digest("evaluator@sha256:" + "ab" * 31)


def test_a_digest_using_another_algorithm_is_refused() -> None:
    # Re-hashing a sha512 to fit CHAR(64) would name the byte-string
    # "sha512:..." instead of the image.
    with pytest.raises(EvaluatorImageError, match="sha512"):
        evaluator_digest("evaluator@sha512:" + "ab" * 32)


# -- The second term: the resolved configuration -----------------------------


def test_a_non_object_configuration_is_refused() -> None:
    with pytest.raises(EvaluatorConfigError, match="must be a JSON object"):
        evaluator_digest(PINNED_IMAGE, ["not", "a", "mapping"])


def test_a_configuration_json_cannot_carry_is_refused() -> None:
    with pytest.raises(EvaluatorConfigError, match="not JSON-serializable"):
        evaluator_digest(PINNED_IMAGE, {"callback": object()})


def test_a_non_finite_float_is_refused() -> None:
    # NaN is not equal to itself, so folding one would make two identical
    # configurations compare unequal — the failure the hash exists to prevent.
    with pytest.raises(EvaluatorConfigError, match="non-finite"):
        evaluator_digest(PINNED_IMAGE, {"floor": float("nan")})
    with pytest.raises(EvaluatorConfigError, match="non-finite"):
        evaluator_digest(PINNED_IMAGE, {"ceiling": float("inf")})


def test_a_non_string_key_is_refused() -> None:
    with pytest.raises(EvaluatorConfigError, match="non-empty strings"):
        evaluator_digest(PINNED_IMAGE, {None: 1})


def test_none_configuration_is_refused_rather_than_folded_as_null() -> None:
    # Unlike the snapshot formula's universe definition, an evaluator always
    # has a configuration (its defaults are one), so None means a caller
    # skipped resolution rather than that there are no settings.
    with pytest.raises(EvaluatorConfigError, match="got None"):
        canonical_config(None)


def test_resolution_layers_nested_mappings_rather_than_replacing_them() -> None:
    resolved = resolve_config(
        {"outer": {"inner": 2}},
        defaults={"outer": {"sibling": 1, "inner": 0}},
    )
    assert resolved["outer"] == {"sibling": 1, "inner": 2}


# -- The axis boundary: what the configuration term must not absorb ----------


def test_the_fee_schedule_is_not_part_of_the_evaluator_identity() -> None:
    # §14.1 pins evaluator_hash, snapshot_hash and cost_model_hash as three
    # separate values, and the cost model is its own plugin (features 59-69)
    # with its own hash (feature 60: "persists cost_model_hash computed over
    # the loaded configuration, so every score names its fee assumptions").
    #
    # The consequence that matters is about the *defaults*: a venue that
    # re-prices its fees without touching the evaluator must not shift
    # evaluator_hash, or every stored score would be reported as
    # cross-evaluator incomparable when only the cost axis moved. So the
    # default key set is pinned exactly — a future edit that folds a fee
    # schedule back in fails here rather than silently re-keying the pool.
    assert set(DEFAULT_CONFIG) == {
        "horizons",
        "normalization",
        "purge_periods",
        "embargo_periods",
    }
    assert "cost_model" not in DEFAULT_CONFIG
    assert "venue" not in DEFAULT_CONFIG
    assert "taker_bps" not in DEFAULT_CONFIG

    # What the identity DOES cover: a setting the evaluator owns.
    base = evaluator_identity(PINNED_IMAGE, {})
    retuned = evaluator_identity(PINNED_IMAGE, {"purge_periods": 5})
    assert retuned.evaluator_hash != base.evaluator_hash


def test_the_defaults_cover_the_settings_the_pipeline_owns() -> None:
    # The three the architecture states for this pipeline: §6.1 step 4's
    # horizons, step 3's normalization, and steps 6-7's purge and embargo.
    assert DEFAULT_CONFIG["horizons"] == [1, 2, 5, 10, 20]
    assert DEFAULT_CONFIG["normalization"] == "rank_zscore"
    assert DEFAULT_CONFIG["purge_periods"] > 0
    assert DEFAULT_CONFIG["embargo_periods"] > 0


def test_the_ad_hoc_layer_wins_over_the_base_layer() -> None:
    # The layering direction, which is silent when wrong: a reversed order
    # still produces a well-formed, deterministic hash — it just describes a
    # configuration nobody asked for. ``base`` is what the evaluator is;
    # ``config`` is what this call asks for, and it wins.
    identity = evaluator_identity(
        PINNED_IMAGE, {"purge_periods": 3}, defaults={}, base={"purge_periods": 20}
    )
    assert identity.config["purge_periods"] == 3


def test_the_base_layer_survives_where_the_ad_hoc_layer_is_silent() -> None:
    identity = evaluator_identity(
        PINNED_IMAGE, {"embargo_periods": 7}, defaults={}, base={"purge_periods": 20}
    )
    assert identity.config["purge_periods"] == 20
    assert identity.config["embargo_periods"] == 7


def test_resolution_replaces_lists_rather_than_merging_them() -> None:
    # An operator who configures [1,5,20] means exactly those horizons; an
    # element-wise merge would make the effective set depend on the
    # default's length.
    resolved = resolve_config({"horizons": [1, 5, 20]}, defaults={"horizons": [1, 2, 5, 10, 20]})
    assert resolved["horizons"] == [1, 5, 20]


# -- The record --------------------------------------------------------------


def test_the_identity_carries_the_terms_beside_the_hash() -> None:
    # A hash is one-way: a row holding only the hash can say *that* two
    # scores came from different evaluators, never *how*. Feature 71's
    # refusal is only actionable when it can name what moved.
    identity = evaluator_identity(PINNED_IMAGE, {"purge_periods": 3}, defaults={})
    assert identity.image_digest == PINNED_DIGEST
    assert identity.config["purge_periods"] == 3
    assert identity.evaluator_hash == _expected(
        PINNED_DIGEST, resolve_config({"purge_periods": 3}, defaults={})
    )
    assert len(identity.hash_prefix) == 6


def test_the_record_refuses_a_hash_that_contradicts_its_own_terms() -> None:
    # A row whose hash disagrees with its terms would name an evaluator it
    # does not describe — which is the tamper the hash exists to detect.
    with pytest.raises(EvaluatorIdentityError, match="does not match"):
        EvaluatorIdentity(
            image_digest=PINNED_DIGEST,
            config={"a": 1},
            evaluator_hash="f" * 64,
        )


def test_the_record_computes_its_hash_when_none_is_given() -> None:
    identity = EvaluatorIdentity(
        image_digest=PINNED_DIGEST, config={"a": 1}, evaluator_hash=""
    )
    assert identity.evaluator_hash == evaluator_digest(
        PINNED_DIGEST, {"a": 1}, defaults={}
    )


def test_the_record_compares_by_hash_not_by_reference_spelling() -> None:
    one = evaluator_identity("evaluator@sha256:" + "ab" * 32)
    other = evaluator_identity("ghcr.io/nullius/evaluator@sha256:" + "ab" * 32)
    assert one.image_reference != other.image_reference
    assert one.describes_same_evaluator(other)


def test_the_record_is_immutable_after_construction() -> None:
    identity = evaluator_identity(PINNED_IMAGE)
    with pytest.raises(Exception):
        identity.evaluator_hash = "0" * 64  # type: ignore[misc]
    with pytest.raises(TypeError):
        identity.config["injected"] = True  # type: ignore[index]


# -- The hash as a value -----------------------------------------------------


def test_normalize_accepts_either_case() -> None:
    assert normalize_evaluator_hash("AB" * 32) == "ab" * 32
    assert normalize_evaluator_hash("ab" * 32) == "ab" * 32


def test_normalize_refuses_a_digest_spelling() -> None:
    # sha256:<hex> is an image reference; accepting it here would let a
    # caller compare a digest against a hash and get "different" for the
    # wrong reason.
    with pytest.raises(EvaluatorIdentityError, match="algorithm prefix"):
        normalize_evaluator_hash(PINNED_DIGEST)


def test_normalize_refuses_a_truncated_value() -> None:
    with pytest.raises(EvaluatorIdentityError, match="not 64 hex"):
        normalize_evaluator_hash("ab" * 6)
