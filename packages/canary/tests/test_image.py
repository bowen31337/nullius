"""The pin vocabulary: one role, one digest, one reference.

These tests pin :mod:`canary._image` from the outside — the parser's
acceptances, its refusals, and the value it returns — because the
parser is the seam between everything a deployment writes down and
everything this plugin asserts. The refusal cases are the feature:
app_spec.xml feature 135's own clause is "rejects a tag-only
reference", and each malformed spelling below is that clause arriving
in a different costume.
"""

from __future__ import annotations

import dataclasses

import pytest

from canary import (
    DIGEST_ALGORITHM,
    DIGEST_HEX_LENGTH,
    CanaryError,
    CanaryImageError,
    PinnedImage,
    image_digest,
    parse_pinned_image,
)

#: A bare 64-hex digest of the right width, for the cases that must not
#: be accepted *without* the repository part.
_BARE_DIGEST = "ab" * 32

#: A digest spelled in uppercase — the `docker inspect` paste case.
_UPPER_DIGEST = "AB" * 32


# -- Acceptances -------------------------------------------------------------


def test_a_digest_pinned_reference_parses_into_role_digest_and_reference() -> None:
    pin = parse_pinned_image(
        "ghcr.io/nullius/evaluator@sha256:" + _BARE_DIGEST, role="evaluator"
    )
    assert isinstance(pin, PinnedImage)
    assert pin.role == "evaluator"
    assert pin.digest == f"sha256:{_BARE_DIGEST}"
    # The reference survives as written, for diagnostics: the digest is
    # the pin, the reference is what the operator recognises.
    assert pin.reference == "ghcr.io/nullius/evaluator@sha256:" + _BARE_DIGEST


def test_a_registry_with_a_port_and_a_path_parses() -> None:
    reference = f"registry.local:5000/nullius/evaluator@sha256:{_BARE_DIGEST}"
    pin = parse_pinned_image(reference, role="evaluator")
    assert pin.digest == f"sha256:{_BARE_DIGEST}"
    assert pin.reference == reference


def test_a_tag_beside_a_digest_is_decoration_the_digest_wins() -> None:
    # ``repo:tag@sha256:...`` is valid Docker syntax; the registry
    # resolves it by digest, and so does the pin — a tag beside a
    # digest cannot move the bytes the digest names.
    pin = parse_pinned_image(
        f"ghcr.io/nullius/evaluator:v3@sha256:{_BARE_DIGEST}", role="evaluator"
    )
    assert pin.digest == f"sha256:{_BARE_DIGEST}"


def test_uppercase_hex_is_normalized_to_lowercase() -> None:
    pin = parse_pinned_image(
        f"ghcr.io/nullius/evaluator@sha256:{_UPPER_DIGEST}", role="evaluator"
    )
    assert pin.digest == f"sha256:{_BARE_DIGEST}"


def test_surrounding_whitespace_is_stripped() -> None:
    # A reference read from a YAML block scalar often arrives with it.
    pin = parse_pinned_image(
        f"  ghcr.io/nullius/evaluator@sha256:{_BARE_DIGEST}\n", role="evaluator"
    )
    assert pin.digest == f"sha256:{_BARE_DIGEST}"
    assert pin.reference == f"ghcr.io/nullius/evaluator@sha256:{_BARE_DIGEST}"


def test_the_digest_term_is_reachable_in_one_line() -> None:
    assert (
        image_digest("ghcr.io/nullius/evaluator@sha256:" + _BARE_DIGEST, role="evaluator")
        == f"sha256:{_BARE_DIGEST}"
    )


# -- The feature's own refusal: a tag-only reference -------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "ghcr.io/nullius/evaluator:latest",
        "nullius-evaluator:latest",
        "nullius-evaluator:v3",
        "nullius-evaluator",
    ],
    ids=["tagged-registry", "tagged", "tagged-version", "bare-name"],
)
def test_a_tag_only_reference_is_rejected(reference: str) -> None:
    # The feature's own clause: "rejects a tag-only reference". A bare
    # name is included because it carries the implicit :latest — a tag
    # nobody wrote is still a tag.
    with pytest.raises(CanaryImageError, match="not digest-pinned") as raised:
        parse_pinned_image(reference, role="evaluator")
    assert isinstance(raised.value, CanaryError)
    # The refusal names the reference as written and the remedy, so an
    # operator reading it knows both what to fix and how.
    message = str(raised.value)
    assert reference in message
    assert "mutable pointer" in message
    assert "out of band" in message


def test_the_tag_only_refusal_names_the_role() -> None:
    with pytest.raises(CanaryImageError, match="the runner container"):
        parse_pinned_image("nullius-runner:latest", role="runner")


def test_a_digest_under_another_algorithm_is_rejected() -> None:
    # sha512 of the sha256 width: the regex matches (the algorithm
    # grammar is registry-shaped), and the algorithm check refuses it —
    # the system's provenance vocabulary is sha256 throughout.
    with pytest.raises(CanaryImageError, match="algorithm 'sha512'"):
        parse_pinned_image("ghcr.io/nullius/evaluator@sha512:" + _BARE_DIGEST, role="evaluator")


def test_an_uppercase_algorithm_is_not_a_digest_pin() -> None:
    # The registry protocol defines algorithm names lowercase; an
    # uppercase spelling matches no pin and is refused as tag-only
    # rather than quietly accepted as sha256.
    with pytest.raises(CanaryImageError, match="not digest-pinned"):
        parse_pinned_image("ghcr.io/nullius/evaluator@SHA256:" + _BARE_DIGEST, role="evaluator")


@pytest.mark.parametrize(
    "digest",
    [
        "a" * 63,  # one short
        "a" * 65,  # one long
        "z" * 64,  # not hex
        "a" * 32 + "G" * 32,  # uppercase G is not hex either
    ],
    ids=["short", "long", "non-hex", "non-hex-uppercase"],
)
def test_a_malformed_digest_is_rejected(digest: str) -> None:
    with pytest.raises(CanaryImageError, match="not digest-pinned"):
        parse_pinned_image(f"ghcr.io/nullius/evaluator@sha256:{digest}", role="evaluator")


@pytest.mark.parametrize("reference", [None, "", "   ", 5], ids=["none", "empty", "blank", "non-string"])
def test_an_absent_reference_is_rejected(reference: object) -> None:
    with pytest.raises(CanaryImageError, match="non-empty"):
        parse_pinned_image(reference, role="evaluator")  # type: ignore[arg-type]


# -- The value ----------------------------------------------------------------


def test_a_pin_exposes_algorithm_hex_and_short() -> None:
    pin = parse_pinned_image(
        "ghcr.io/nullius/evaluator@sha256:" + _BARE_DIGEST, role="evaluator"
    )
    assert pin.algorithm == DIGEST_ALGORITHM
    assert pin.hex == _BARE_DIGEST
    assert len(pin.hex) == DIGEST_HEX_LENGTH
    # Prefixed with the algorithm so bare hex cannot be misread as an
    # evaluator_hash prefix — a different value entirely.
    assert pin.short == "sha256:" + "ab" * 6


def test_a_pin_is_immutable() -> None:
    pin = parse_pinned_image(
        "ghcr.io/nullius/evaluator@sha256:" + _BARE_DIGEST, role="evaluator"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        pin.digest = "sha256:" + "cd" * 32  # type: ignore[misc]


def test_two_spellings_of_one_image_share_a_digest_but_not_a_value() -> None:
    # The pin is the digest; the value is the record of what was
    # declared. Two spellings of the same bytes therefore compare as
    # different values while carrying the same term — a caller that
    # wants "same image?" compares digests, and a caller that wants
    # "same declaration?" compares values.
    long_form = parse_pinned_image(
        "ghcr.io/nullius/evaluator@sha256:" + _BARE_DIGEST, role="evaluator"
    )
    short_form = parse_pinned_image(
        "nullius/evaluator@sha256:" + _BARE_DIGEST, role="evaluator"
    )
    assert long_form.digest == short_form.digest
    assert long_form != short_form


def test_a_hand_built_pin_normalizes_its_digest() -> None:
    # The dataclass validates and canonicalizes directly, so a record
    # assembled outside the parser still carries one spelling.
    pin = PinnedImage(
        role="evaluator",
        digest=f"sha256:{_UPPER_DIGEST}",
        reference="ghcr.io/nullius/evaluator@sha256:" + _UPPER_DIGEST,
    )
    assert pin.digest == f"sha256:{_BARE_DIGEST}"


def test_a_hand_built_digest_without_an_algorithm_is_rejected() -> None:
    # A bare 64-hex string could be a digest, but could equally be an
    # evaluator_hash or a code_hash — accepting it would let a caller
    # pin the wrong value and never learn.
    with pytest.raises(CanaryImageError, match="carries no algorithm"):
        PinnedImage(role="evaluator", digest=_BARE_DIGEST, reference="anything")


def test_a_hand_built_digest_under_another_algorithm_is_rejected() -> None:
    with pytest.raises(CanaryImageError, match="algorithm 'sha512'"):
        PinnedImage(role="evaluator", digest="sha512:" + "a" * 128, reference="anything")


@pytest.mark.parametrize("role", [None, "", "  "], ids=["none", "empty", "blank"])
def test_an_unnameable_role_is_rejected(role: object) -> None:
    # The role is the word a refusal names; a role that cannot be named
    # cannot be swept — refused at value construction, before any code
    # path can carry it into a message.
    with pytest.raises(CanaryImageError, match="non-empty string"):
        parse_pinned_image("ghcr.io/nullius/evaluator@sha256:" + _BARE_DIGEST, role=role)  # type: ignore[arg-type]
