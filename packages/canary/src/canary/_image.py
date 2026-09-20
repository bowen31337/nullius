"""A pinned evaluation container — one role, one digest, one reference.

app_spec.xml feature 135 (this plugin's root feature) states the contract
in one sentence: "System pins every evaluation container by image digest
rather than by tag, which rejects a tag-only reference."
docs/nullius-tech-architecture.md states the same fact twice from the
runtime side — §12's determinism table opens with "Pinned evaluator |
Container digest in ``evaluator_hash``; refuse cross-hash comparison",
and §16's stack row for containers is "Docker, digest-pinned, because
``evaluator_hash`` requires digest pinning, not tags". §1 folds it into
the replay guarantee itself ("Pinned images, pinned seeds,
single-threaded BLAS in eval workers"), and cq-15 carries the
consequence: a replay that cannot name its bytes cannot be asserted
identical to the run that recorded them.

**Why this package keeps its own parser.** The evaluator member
(``packages/evaluator``, feature 70) parses digest-pinned references too
— it folds one image's digest into one ``evaluator_hash`` — and its
docstrings already point here: "canary feature 135 states it as its own".
The two parsers stay deliberately independent because they answer
different questions with different blast radii. The evaluator's parser
produces an *identity term*: one image, one hash, and a divergence there
corrupts one provenance stamp. This parser produces a *pin*: the
assertion that a container some role runs in is the bytes the digest
names, and a divergence here lets an unpinned container onto the
evaluation path — which is §12's whole table quietly void, because every
other line ("single-threaded numerics", "no wall clock", "stable
iteration order") is an environment *inside* the container this line
freezes. A shared parser would couple the auditor to the audited: a
future evaluator change (say, accepting a second algorithm to ease a
migration) would silently widen what the canary accepts, which is the
direction the dependency must never run. The vocabulary is still one
spelling — ``sha256:<64 lowercase hex>`` — so the two parsers agree on
every reference either accepts, and disagree only in *why* they refuse.

**A tag-only reference is refused, not up-converted.** One could resolve
a tag to a digest by asking a registry. That would make the pin depend
on a network call at sweep time and — worse — on *when* the call
happened: the same declaration would pin different bytes on different
days with no record that it had moved, which is precisely the drift the
pin exists to make impossible. The refusal is the feature's guarantee
("rejects a tag-only reference" is the feature's own clause). A caller
holding a tag resolves it to a digest out of band — ``docker manifest
inspect``, a CI step, a registry UI — where the resolution is recorded,
and pins *that*.

**The whole reference is not the pin.** ``registry/repo@sha256:...`` and
``repo@sha256:...`` can name the same bytes. A pin keyed on the full
string would give one image two pins depending on how a caller happened
to spell it, and two declarations that agree about the artifact would
disagree about the sweep. So :func:`parse_pinned_image` extracts the
``sha256:<64 hex>`` digest and the *sweep* compares digests; the
human-facing reference survives on :class:`PinnedImage` for diagnostics
and stays out of the comparison. The value still carries the reference
(equality is over the spelling, term included), because a pin is a
record of what was declared, not merely of what it resolved to — the
digest says which bytes, the reference says what the operator wrote, and
a report that conflated them could not say which of the two moved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._errors import CanaryImageError

__all__ = [
    "DIGEST_ALGORITHM",
    "DIGEST_HEX_LENGTH",
    "PinnedImage",
    "image_digest",
    "parse_pinned_image",
]

#: The digest algorithm a pin is spelled with. sha256 is not a preference:
#: architecture §16 names the runtime "Docker, digest-pinned", and the
#: identity vocabulary this contract guards (``evaluator_hash``, the
#: ``CHAR(64)`` provenance columns beside it) is sha256 throughout — a
#: digest under any other algorithm is refused rather than re-hashed,
#: because re-hashing a sha512 to 64 hex would name the byte-string
#: ``"sha512:..."`` instead of the image.
DIGEST_ALGORITHM = "sha256"

#: Length of a sha256 hex digest — the width every ``CHAR(64)`` provenance
#: column in the data model already carries.
DIGEST_HEX_LENGTH = 64

_HEX = frozenset("0123456789abcdef")

# A digest-pinned reference, anywhere inside the reference string:
# ``@sha256:<64 hex>``. Anchored on the ``@`` so a repository that merely
# *contains* the text cannot be mistaken for a pin, and case-insensitive
# on the hex so a digest pasted from `docker inspect` is accepted while
# the algorithm name — which the registry protocol defines lowercase —
# is not.
_DIGEST_RE = re.compile(
    r"@(?P<algorithm>[a-z0-9]+(?:[.+_-][a-z0-9]+)*)"
    rf":(?P<digest>[0-9a-fA-F]{{{DIGEST_HEX_LENGTH}}})$"
)


@dataclass(frozen=True)
class PinnedImage:
    """One evaluation container's pin, as a value.

    ``role`` says what the container *is for* ("the evaluator", "the
    nightly runner") — the sweep's reason to care, and the word its
    refusal names. ``digest`` is the pin itself — ``sha256:<64 lowercase
    hex>`` — and ``reference`` is the string the caller wrote, kept for
    diagnostics and for a human reading a report. The three are separate
    fields deliberately: the digest is what comparisons run over, the
    role is what the refusal addresses, and the reference is what an
    operator recognises — a record that conflated them would leak the
    spelling of a reference into the question of whether two containers
    are the same bytes.
    """

    #: What this container is for — the sweep's key, e.g. ``"evaluator"``.
    role: str
    #: The full lowercase ``sha256:<64 hex>`` digest — the pin.
    digest: str
    #: The reference as written (e.g. ``ghcr.io/nullius/evaluator@sha256:…``).
    reference: str

    def __post_init__(self) -> None:
        _require_role(self.role)
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
        ``evaluator_hash`` the digest feeds on the evaluator's side; the
        two are different values, and a report that showed bare hex would
        invite the reading that the short digest *is* a hash prefix.
        """
        return f"{self.algorithm}:{self.hex[:12]}"

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"PinnedImage(role={self.role!r}, digest={self.digest!r}, "
            f"reference={self.reference!r})"
        )


def _require_role(role: str) -> None:
    """Validate a pin's role — the word the sweep's refusal addresses.

    A role that is not a non-empty string cannot be named in a refusal,
    so a sweep keyed on one would fail *silently* in the one place the
    feature is a refusal: the error message. Refused here, at value
    construction, so no code path can carry an unnameable role.
    """
    if not isinstance(role, str) or not role.strip():
        raise CanaryImageError(
            f"a container role must be a non-empty string, got {role!r}; "
            "the role is the word a pin sweep's refusal names, so a role "
            "that cannot be named cannot be swept"
        )


def _normalize_digest(value: str) -> str:
    """Validate a digest, returning it as lowercase ``sha256:<64 hex>``.

    Accepts the ``sha256:``-prefixed form with hex in either case — a
    digest pasted from `docker inspect` or a CI variable is commonly
    uppercase but means the same bytes, so uppercasing is normalized away
    rather than refused. Rejects a bare 64-hex string (which *could* be a
    digest but could equally be an ``evaluator_hash`` or a ``code_hash``
    — accepting it would let a caller pin the wrong value and never
    learn), any other algorithm, and anything of the wrong width.
    """
    if not isinstance(value, str) or not value:
        raise CanaryImageError(
            f"image digest must be a non-empty string, got {value!r}; the "
            f"expected shape is {DIGEST_ALGORITHM}:<{DIGEST_HEX_LENGTH} hex>"
        )
    algorithm, separator, hex_part = value.partition(":")
    if not separator:
        raise CanaryImageError(
            f"image digest {value!r} carries no algorithm; the expected "
            f"shape is {DIGEST_ALGORITHM}:<{DIGEST_HEX_LENGTH} hex> — a bare "
            "hex string is ambiguous with the other CHAR(64) provenance "
            "columns (evaluator_hash, snapshot_hash, code_hash), so it is "
            "refused rather than guessed at"
        )
    if algorithm != DIGEST_ALGORITHM:
        raise CanaryImageError(
            f"image digest {value!r} uses algorithm {algorithm!r}; this "
            f"system pins images with {DIGEST_ALGORITHM} only, matching the "
            "sha256 vocabulary the provenance columns carry"
        )
    if len(hex_part) != DIGEST_HEX_LENGTH or not set(hex_part.lower()) <= _HEX:
        raise CanaryImageError(
            f"image digest {value!r} is not {DIGEST_HEX_LENGTH} hex "
            f"characters after the {DIGEST_ALGORITHM}: prefix"
        )
    return f"{DIGEST_ALGORITHM}:{hex_part.lower()}"


def parse_pinned_image(reference: str, *, role: str) -> PinnedImage:
    """Parse a digest-pinned image reference into one role's pin.

    The reference may carry a registry, a repository path, a port and a
    tag; only the ``@sha256:`` digest is extracted — where a reference
    carries both a tag and a digest (``repo:tag@sha256:…``, valid Docker
    syntax) the digest wins, because a tag beside a digest is decoration
    the registry ignores and the pin does too. Extra surrounding
    whitespace is stripped (a reference read from a YAML block scalar
    often arrives with it), but nothing else is repaired: a reference
    whose digest is malformed is refused with the reason, because a
    reference this function cannot parse is one whose container cannot
    be pinned.

    A tag-only reference — ``nullius-evaluator:latest``, or a bare
    ``nullius-evaluator`` — is a :class:`~canary.CanaryImageError`. See
    the module docstring for why it is refused rather than resolved.
    """
    _require_role(role)
    if not isinstance(reference, str) or not reference.strip():
        raise CanaryImageError(
            f"the {role} container's image reference must be a non-empty "
            f"string, got {reference!r}"
        )
    text = reference.strip()
    match = _DIGEST_RE.search(text)
    if match is None:
        raise CanaryImageError(
            f"the {role} container's image reference {text!r} is not "
            f"digest-pinned; expected <name>@{DIGEST_ALGORITHM}:"
            f"<{DIGEST_HEX_LENGTH} hex> (for example ghcr.io/nullius/"
            "evaluator@" + DIGEST_ALGORITHM + ":" + "0" * DIGEST_HEX_LENGTH
            + "). A tag or bare name is a mutable pointer — the same "
            "reference resolves to different bytes over time — so it "
            "cannot serve as a pin; resolve the tag to a digest out of "
            "band, where the resolution can be recorded, and pin that"
        )
    if match.group("algorithm") != DIGEST_ALGORITHM:
        raise CanaryImageError(
            f"the {role} container's image reference {text!r} is pinned "
            f"with algorithm {match.group('algorithm')!r}; this system "
            f"pins images with {DIGEST_ALGORITHM} only, matching the "
            "sha256 vocabulary the provenance columns carry"
        )
    return PinnedImage(
        role=role,
        digest=f"{DIGEST_ALGORITHM}:{match.group('digest').lower()}",
        reference=text,
    )


def image_digest(reference: str, *, role: str) -> str:
    """The digest term for a reference — one line, one pin.

    The convenience form of :func:`parse_pinned_image` for callers that
    only want the term to compare or report: returns ``sha256:<64
    lowercase hex>`` or raises :class:`~canary.CanaryImageError`. Kept
    beside the parser rather than reimplemented at the call site so the
    two cannot drift — a caller that extracted the digest its own way
    would be a second, divergent answer to "which bytes is this
    container?".
    """
    return parse_pinned_image(reference, role=role).digest
