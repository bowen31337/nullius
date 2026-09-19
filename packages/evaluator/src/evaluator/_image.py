"""The container image digest — the first term of ``evaluator_hash``.

docs/nullius-tech-architecture.md §6 states the evaluator's identity in one
line::

    evaluator_hash = sha256(image_digest + config)

and §16 (``containers``) states the same fact from the other side: the stack
uses "Docker, digest-pinned, because ``evaluator_hash`` requires digests not
tags". app_spec.xml feature 70 makes it the thing the system persists.
§12's determinism table pins the consequence — "Pinned evaluator: container
digest in ``evaluator_hash``; refuse cross-hash comparison" — and §15's
failure-mode table names the recovery when the image moves: "Evaluator image
changed → Hash mismatch on score comparison → Refuse comparison".

**Why the digest and not the reference.** A tag is a mutable pointer. The
same tag resolves to different bytes next week, so a hash computed over
"``nullius-evaluator:latest``" names an *intention*, not an artifact, and
two scores carrying it could have been produced by two different programs
with no way to tell. A digest names content. That is the whole reason the
term exists: it is what makes the evaluator frozen in the only sense the
system needs — the bytes that produced a score are recoverable from the
score itself.

**The whole reference is not the term.** ``registry/repo@sha256:...`` and
``repo@sha256:...`` can name the same bytes. Folding the full reference
would give one image two identities depending on how a caller happened to
spell it, and two systems that agree about the artifact would disagree about
the hash — the failure mode §15's "feature definition changed" row calls
"the sneakiest one", arriving by a different road. So :func:`image_digest`
extracts the ``sha256:<64 hex>`` and the formula folds *that*: one image,
one term, however it was written down. The human-facing reference survives
on :class:`ImageRef` for diagnostics and stays out of the hash.

**A tag-only reference is refused, not up-converted.** One could resolve a
tag to a digest by asking a registry. That would make the identity depend on
a network call at hash time, and — worse — make it depend on *when* the call
happened: the same code path would fold different digests on different days
with no record that it had. The refusal is the feature's guarantee (canary
feature 135 states it as its own: "rejects a tag-only reference"). A caller
who has a tag must resolve it to a digest themselves, out of band, where the
resolution can be recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._errors import EvaluatorImageError

__all__ = [
    "DIGEST_ALGORITHM",
    "DIGEST_HEX_LENGTH",
    "ImageRef",
    "coerce_image_ref",
    "image_digest",
    "parse_image_ref",
]

#: The digest algorithm the image term is spelled with. sha256 is not a
#: preference: app_spec.xml feature 70 and architecture §6 both name it, and
#: the ``node.evaluator_hash`` column is ``CHAR(64)`` — a 64-character hex
#: digest, which is exactly this algorithm's output width. A digest under any
#: other algorithm is refused rather than truncated or re-hashed, because
#: re-hashing a sha512 to fit the column would name the byte-string
#: ``"sha512:..."`` instead of the image.
DIGEST_ALGORITHM = "sha256"

#: Length of a sha256 hex digest, matching the ``CHAR(64)`` column.
DIGEST_HEX_LENGTH = 64

_HEX = frozenset("0123456789abcdef")

# A digest-pinned reference, anywhere inside the reference string:
# ``@sha256:<64 hex>``. Anchored on the ``@`` so a repository that merely
# *contains* the text cannot be mistaken for a pin, and case-insensitive on
# the hex so a digest pasted from `docker inspect` is accepted while the
# algorithm name — which the registry protocol defines lowercase — is not.
_DIGEST_RE = re.compile(
    r"@(?P<algorithm>[a-z0-9]+(?:[.+_-][a-z0-9]+)*)"
    rf":(?P<digest>[0-9a-fA-F]{{{DIGEST_HEX_LENGTH}}})$"
)


@dataclass(frozen=True)
class ImageRef:
    """A digest-pinned container image, as a value.

    ``digest`` is the identity term — ``sha256:<64 lowercase hex>`` — and
    ``reference`` is the string the caller wrote, kept for diagnostics and
    for a human reading a failure message. The two are deliberately separate
    fields rather than one: :attr:`reference` may legitimately vary between
    two spellings of the same image while :attr:`digest` may not, and a
    record that conflated them would leak that variation into comparisons.
    """

    #: The full lowercase ``sha256:<64 hex>`` digest — the identity term.
    digest: str
    #: The reference as written (e.g. ``ghcr.io/nullius/evaluator@sha256:…``).
    reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", _normalize_digest(self.digest))

    @property
    def algorithm(self) -> str:
        """The digest's algorithm name (always :data:`DIGEST_ALGORITHM`)."""
        return self.digest.split(":", 1)[0]

    @property
    def hex(self) -> str:
        """The 64 hex characters, without the ``sha256:`` prefix."""
        return self.digest.split(":", 1)[1]

    @property
    def short(self) -> str:
        """The first twelve hex characters — a human-checkable shorthand.

        Prefixed with the algorithm so it cannot be confused with the
        ``evaluator_hash`` it contributes to; the two are different values
        and a report that showed bare hex would invite the reading that the
        short digest *is* a hash prefix.
        """
        return f"{self.algorithm}:{self.hex[:12]}"

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ImageRef(digest={self.digest!r}, reference={self.reference!r})"


def _normalize_digest(value: str) -> str:
    """Validate a digest, returning it as lowercase ``sha256:<64 hex>``.

    Accepts the ``sha256:``-prefixed form with hex in either case — a digest
    pasted from `docker inspect` or a CI variable is commonly uppercase but
    means the same bytes, so uppercasing is normalized away rather than
    refused. Rejects a bare 64-hex string (which *could* be a digest but
    could equally be an ``evaluator_hash`` or a ``code_hash`` — accepting it
    would let a caller fold the wrong value into the identity and never
    learn), any other algorithm, and anything of the wrong width.
    """
    if not isinstance(value, str) or not value:
        raise EvaluatorImageError(
            f"image digest must be a non-empty string, got {value!r}; the "
            f"expected shape is {DIGEST_ALGORITHM}:<{DIGEST_HEX_LENGTH} hex>"
        )
    algorithm, separator, hex_part = value.partition(":")
    if not separator:
        raise EvaluatorImageError(
            f"image digest {value!r} carries no algorithm; the expected "
            f"shape is {DIGEST_ALGORITHM}:<{DIGEST_HEX_LENGTH} hex> — a bare "
            "hex string is ambiguous with the other CHAR(64) provenance "
            "columns (evaluator_hash, snapshot_hash, code_hash), so it is "
            "refused rather than guessed at"
        )
    if algorithm != DIGEST_ALGORITHM:
        raise EvaluatorImageError(
            f"image digest {value!r} uses algorithm {algorithm!r}; this "
            f"system pins images with {DIGEST_ALGORITHM} only, matching the "
            f"CHAR({DIGEST_HEX_LENGTH}) evaluator_hash column"
        )
    if len(hex_part) != DIGEST_HEX_LENGTH or not set(hex_part.lower()) <= _HEX:
        raise EvaluatorImageError(
            f"image digest {value!r} is not {DIGEST_HEX_LENGTH} hex "
            f"characters after the {DIGEST_ALGORITHM}: prefix"
        )
    return f"{DIGEST_ALGORITHM}:{hex_part.lower()}"


def parse_image_ref(reference: str) -> ImageRef:
    """Parse a digest-pinned image reference into its identity term.

    The reference may carry a registry, a repository path, a port and a tag;
    only the ``@sha256:`` digest is extracted. Extra surrounding whitespace
    is stripped (a reference read from a YAML block scalar often arrives with
    it), but nothing else is repaired: a reference whose digest is malformed
    is refused with the reason, because a reference this function cannot
    parse is one whose image cannot be pinned.

    A tag-only reference — ``nullius-evaluator:latest``, or a bare
    ``nullius-evaluator`` — is an :class:`~evaluator.EvaluatorImageError`.
    See the module docstring for why it is refused rather than resolved.
    """
    if not isinstance(reference, str) or not reference.strip():
        raise EvaluatorImageError(
            f"image reference must be a non-empty string, got {reference!r}"
        )
    text = reference.strip()
    match = _DIGEST_RE.search(text)
    if match is None:
        raise EvaluatorImageError(
            f"image reference {text!r} is not digest-pinned; expected "
            f"<name>@{DIGEST_ALGORITHM}:<{DIGEST_HEX_LENGTH} hex> (for "
            "example ghcr.io/nullius/evaluator@" + DIGEST_ALGORITHM + ":"
            + "0" * DIGEST_HEX_LENGTH + "). A tag or bare name is a mutable "
            "pointer — the same reference resolves to different bytes over "
            "time — so it cannot serve as an identity term; resolve the tag "
            "to a digest out of band and pin that"
        )
    if match.group("algorithm") != DIGEST_ALGORITHM:
        raise EvaluatorImageError(
            f"image reference {text!r} is pinned with algorithm "
            f"{match.group('algorithm')!r}; this system pins images with "
            f"{DIGEST_ALGORITHM} only, matching the CHAR({DIGEST_HEX_LENGTH}) "
            "evaluator_hash column"
        )
    return ImageRef(
        digest=f"{DIGEST_ALGORITHM}:{match.group('digest').lower()}",
        reference=text,
    )


def coerce_image_ref(value: "str | ImageRef") -> ImageRef:
    """Accept an image as an :class:`ImageRef`, a reference, or a bare digest.

    The three spellings a caller legitimately holds. An :class:`ImageRef`
    passes through. A reference is parsed by :func:`parse_image_ref`. A bare
    ``sha256:<64 hex>`` digest — which :func:`parse_image_ref` refuses in its
    *reference* form, on purpose, because a reference and a digest are
    different things — is accepted here as the digest it unambiguously is.

    The distinction matters for round-tripping: an
    :class:`~evaluator.EvaluatorIdentity` exposes its first term as
    :attr:`~evaluator.EvaluatorIdentity.image_digest`, so
    ``evaluator_digest(identity.image_digest, identity.config)`` has to
    recompute the same hash. Without this coercion that natural call would
    refuse a value the system itself produced.
    """
    if isinstance(value, ImageRef):
        return value
    if isinstance(value, str) and "@" not in value and value.startswith(f"{DIGEST_ALGORITHM}:"):
        # A bare digest: no repository part, so nothing to parse a reference
        # out of. ``ImageRef`` validates and canonicalizes it.
        return ImageRef(digest=value, reference=value)
    return parse_image_ref(value)


def image_digest(reference: str) -> str:
    """The identity term for an image reference — one line, one term.

    The convenience form of :func:`parse_image_ref` for callers that only
    want the term to fold: returns ``sha256:<64 lowercase hex>`` or raises
    :class:`~evaluator.EvaluatorImageError`. Kept next to the parser rather
    than reimplemented in the formula so the two cannot drift — a formula
    that extracted the digest its own way would be a second, divergent
    answer to "which bytes is this image?".
    """
    return parse_image_ref(reference).digest
