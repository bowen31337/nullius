"""The ``evaluator_hash`` formula: one identity over image digest and config.

docs/nullius-tech-architecture.md §6 states it in one line::

    evaluator_hash = sha256(image_digest + config)

and app_spec.xml feature 70 makes it the identity the system persists:
"System persists ``evaluator_hash`` computed as a sha256 over the container
image digest plus the resolved configuration". §12's determinism table pins
what it is *for* — "Refuse cross-hash comparison" — and §15's failure table
supplies the recovery when the image moves: "Evaluator image changed → Hash
mismatch on score comparison → Refuse comparison; re-score the pool
(budgeted) or fork the pool".

**What each term earns.** Together they pin everything about an evaluation
except the data it read (that is ``snapshot_hash``) and the fees it paid
(that is ``cost_model_hash``) — the other two thirds of the provenance
triple §14.1 ranks against. Each term names one axis on which
otherwise-identical scores are *not* the same measurement:

* **The container image digest** — *what program ran*. §16: "Docker,
  digest-pinned, because ``evaluator_hash`` requires digests not tags". A
  score computed by a patched evaluator is a different measurement even if
  every setting matches, and the digest is the only term that can say so.
  Folded as the ``sha256:<64 hex>`` term alone, so two spellings of one
  image are one identity (see ``_image``).
* **The resolved configuration** — *how it was told to run*. The horizons,
  the purge and embargo, the normalization: settings that change what a
  score means. Folded through its canonical JSON spelling, so key order and
  whitespace cannot leak in, and folded *after* resolution, so the identity
  follows the effective settings rather than the documents that produced
  them (see ``_config``).

**What the configuration term must not absorb.** §6.1 step 7 applies the
cost model inside this pipeline, and §6.2's ``cost_model`` block sits in the
evaluator's own section of the architecture — which makes it tempting to
fold the fee schedule into this hash. It belongs to a different axis: §14.1
pins ``evaluator_hash``, ``snapshot_hash`` and ``cost_model_hash`` as three
separate values, and the cost model is its own plugin (features 59-69) with
its own configuration and its own hash (feature 60). Folding fees here would
make a re-priced venue look like a changed evaluator — every stored score
reported as cross-evaluator incomparable when only the cost axis moved — and
the two hashes §15 relies on to tell those cases apart would stop disagreeing
in the way they are meant to. The pipeline consumes the cost model; the
identity must not absorb it. See :data:`~evaluator.DEFAULT_CONFIG`.

**The byte-level spelling is the format.** Pin the preimage exactly or the
hash names nothing: the two terms are joined by a single newline and hashed
once, as UTF-8. Both terms are provably newline-free by construction — the
image term is ``sha256:`` plus hex digits, and canonical JSON escapes
control characters rather than emitting them — so the joined preimage can be
split back into exactly the two terms that produced it. The framing is a
separability guarantee, not punctuation: without it, a configuration
spelling ending where a following term begins could be re-split two ways and
two different evaluators would share an identity. (The snapshot member's
``_identity`` makes the same argument for its three terms; the framing is
the same shape so a reader who has met one has met both.)

The fold is deterministic the way an evaluation requires: the same image
digest and resolved configuration produce the same hash on any machine, any
day, in any process. That is what lets a comparison notice that two scores
came from different evaluators — the property feature 71 builds on — and
what makes the persisted row a statement about the program that produced a
score rather than a note about when it was written.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from ._config import EvaluatorConfig, canonical_config, resolve_config
from ._errors import EvaluatorIdentityError
from ._image import ImageRef, coerce_image_ref

__all__ = [
    "EVALUATOR_HASH_LENGTH",
    "EvaluatorIdentity",
    "evaluator_digest",
    "normalize_evaluator_hash",
]

#: Length of the persisted ``evaluator_hash`` — a sha256 hex digest, matching
#: the spec's ``evaluator_hash CHAR(64) NOT NULL`` column on ``node`` and
#: ``trial_ledger``.
EVALUATOR_HASH_LENGTH = 64

_HEX = frozenset("0123456789abcdef")


def evaluator_digest(
    image: "str | ImageRef",
    config: Optional[Mapping[str, Any]] = None,
    *,
    defaults: Optional[Mapping[str, Any]] = None,
) -> str:
    """Compute the §6 ``evaluator_hash`` over image digest and configuration.

    ``image`` is a digest-pinned reference (``repo@sha256:…``) or an already
    parsed :class:`~evaluator.ImageRef`; a tag-only reference is refused —
    see ``_image`` for why that refusal is the feature rather than an
    inconvenience. ``config`` is the configuration document to fold; it is
    *resolved* against ``defaults`` (:data:`~evaluator.DEFAULT_CONFIG` when
    omitted) before hashing, so the term is the effective settings rather
    than the ones a caller happened to state. A caller holding a fully
    resolved mapping should wrap it with ``defaults={}`` or pass it through
    :func:`evaluator_identity`, which records the distinction.

    Returns 64 lowercase hex characters — the value feature 70 persists.
    """
    reference = coerce_image_ref(image)
    configuration = resolve_config(config, defaults=defaults)
    return _fold(reference.digest, canonical_config(configuration))


def _fold(digest: str, canonical: str) -> str:
    """Hash the two framed terms once, as UTF-8.

    The single place the formula's byte-level spelling lives, so the
    digest-computing path and the verifying path cannot drift — a
    verification that reassembled the preimage its own way would recompute a
    different value from the same inputs and report a match as a mismatch.
    """
    payload = "\n".join((digest, canonical)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_evaluator_hash(value: str) -> str:
    """Validate an ``evaluator_hash``, returning it in canonical lowercase hex.

    Accepts 64 hexadecimal characters in either case — a hash pasted from a
    database, a log line or a report is commonly uppercase, means the same
    value, and uppercasing is normalized away rather than refused — matching
    the treatment ``snapshot.normalize_snapshot_hash`` gives the sibling
    column. Rejects a ``sha256:``-prefixed digest (that spelling belongs to
    an image reference, and accepting it here would let a caller compare a
    digest against a hash and get "different" for the wrong reason), a
    ``git``-style short hash, and anything of the wrong length or alphabet.
    """
    if not isinstance(value, str):
        raise EvaluatorIdentityError(
            f"evaluator_hash must be a {EVALUATOR_HASH_LENGTH}-character hex "
            f"string, got {type(value).__name__}"
        )
    text = value.strip()
    if ":" in text:
        raise EvaluatorIdentityError(
            f"evaluator_hash {value!r} carries an algorithm prefix; a "
            "sha256:<hex> digest is an *image reference*, not the hash "
            "computed over it — pass the 64 hex characters themselves"
        )
    if len(text) != EVALUATOR_HASH_LENGTH or not set(text.lower()) <= _HEX:
        raise EvaluatorIdentityError(
            f"evaluator_hash {value!r} is not {EVALUATOR_HASH_LENGTH} hex "
            "characters; a short hash, a truncated value or a non-hex token "
            "names no evaluator this system recorded"
        )
    return text.lower()


@dataclass(frozen=True)
class EvaluatorIdentity:
    """One evaluator, named: the two terms and the hash they fold to.

    The value feature 70 persists, together with the inputs it was computed
    over. Carrying the terms beside the hash is not redundancy — the hash is
    one-way, so a row holding only the hash can say *that* two scores came
    from different evaluators but never *how*; a comparison refusal (§15's
    recovery, feature 71's error message) is only actionable when it can
    name the digest or the setting that moved.

    The record is frozen and its configuration is a read-only proxy, not
    because a determined process cannot violate that, but because
    immutability here is the API contract matching the claim: an identity
    that could be edited after the fact would let the same object stand for
    two evaluators — the exact defect the hash exists to detect.

    Build with :func:`evaluator_identity`, or from a persisted row with
    :func:`evaluator.identity_from_row`.
    """

    #: The full lowercase ``sha256:<64 hex>`` image digest — term one.
    image_digest: str
    #: The resolved configuration, read-only — term two.
    config: Mapping[str, Any]
    #: The 64-hex sha256 over the two terms, canonically framed.
    evaluator_hash: str
    #: The image reference as written, when the caller had one. Diagnostics
    #: only: it is *not* a hash term, so two spellings of one image carry
    #: different references and the same :attr:`evaluator_hash`.
    image_reference: Optional[str] = None

    def __post_init__(self) -> None:
        # Normalize rather than trust: a record built by hand in a test or
        # reconstructed from a row gets the same canonicalisation the
        # formula applies, and a hash that disagrees with its own terms is
        # refused here rather than persisting as a row that lies.
        ref = ImageRef(
            digest=self.image_digest, reference=self.image_reference or self.image_digest
        )
        resolved = resolve_config(self.config, defaults={})
        canonical = canonical_config(resolved)
        expected = _fold(ref.digest, canonical)
        object.__setattr__(self, "image_digest", ref.digest)
        object.__setattr__(self, "config", resolved)
        if not self.evaluator_hash:
            object.__setattr__(self, "evaluator_hash", expected)
            return
        normalized = normalize_evaluator_hash(self.evaluator_hash)
        object.__setattr__(self, "evaluator_hash", normalized)
        if normalized != expected:
            raise EvaluatorIdentityError(
                f"evaluator_hash {normalized} does not match the value "
                f"computed over image digest {ref.digest} and the resolved "
                f"configuration ({expected}); an identity whose hash "
                "disagrees with its own terms would persist a row that "
                "names an evaluator it does not describe"
            )

    @property
    def image(self) -> ImageRef:
        """The parsed image reference for this identity."""
        return ImageRef(
            digest=self.image_digest,
            reference=self.image_reference or self.image_digest,
        )

    @property
    def config_canonical(self) -> str:
        """The canonical JSON spelling of the term that was folded."""
        return canonical_config(self.config)

    @property
    def hash_prefix(self) -> str:
        """The first six characters of the hash — a human-checkable shorthand."""
        return self.evaluator_hash[:6]

    def describes_same_evaluator(self, other: "EvaluatorIdentity") -> bool:
        """Whether two identities name the same evaluator.

        Compares the *hash*, not the terms: that is the point of computing
        one. Two spellings of one image with one resolved configuration fold
        to one value and are the same evaluator, which comparing references
        would miss. Not named ``__eq__``: the dataclass equality below
        compares :attr:`image_reference` too, which is deliberately not part
        of "same evaluator" (see that field's docstring) — so a caller asking
        the question of interest asks this method.
        """
        if not isinstance(other, EvaluatorIdentity):
            return NotImplemented
        return self.evaluator_hash == other.evaluator_hash

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"EvaluatorIdentity(evaluator_hash={self.evaluator_hash!r}, "
            f"image={self.image.short!r})"
        )


def evaluator_identity(
    image: "str | ImageRef",
    config: Optional[Mapping[str, Any]] = None,
    *,
    defaults: Optional[Mapping[str, Any]] = None,
    base: Optional[Mapping[str, Any]] = None,
) -> EvaluatorIdentity:
    """Resolve one evaluator's identity — the entry point the service uses.

    The layers stack bottom-up: ``defaults`` (or
    :data:`~evaluator.DEFAULT_CONFIG` when omitted), then ``base``, then
    ``config`` on top. The two named layers exist because callers hold two
    different things and the order between them matters:

    * ``base`` is what the evaluator *is* — the deployment's resolved
      configuration, which a service passes so its own settings sit under
      any ad-hoc adjustment.
    * ``config`` is what this particular call asks for — an ad-hoc run with
      one knob changed — and being the top layer, it wins.

    Getting that order backwards is silent: the hash is still well-formed
    and the identity still deterministic, it just describes a configuration
    nobody asked for. So the direction is spelled in the parameter names
    rather than left to the call site to remember.

    A caller holding a mapping that is already fully resolved passes it as
    ``config`` with ``defaults={}`` and gets exactly it — which is what
    :class:`~evaluator.EvaluatorConfig` does.
    """
    reference = coerce_image_ref(image)
    configuration = resolve_config(base, config, defaults=defaults)
    return EvaluatorIdentity(
        image_digest=reference.digest,
        config=configuration,
        evaluator_hash="",  # computed from the terms in __post_init__
        image_reference=reference.reference,
    )
