"""The frozen evaluator, as a workspace component.

Features (app_spec.xml, "Frozen Evaluator Pipeline", feature 70):
persist ``evaluator_hash`` computed as a sha256 over the container image
digest plus the resolved configuration.
docs/nullius-tech-architecture.md §6 fixes the formula in one line —
``evaluator_hash = sha256(image_digest + config)`` — §12's determinism table
pins what it is for ("Pinned evaluator: container digest in
``evaluator_hash``; refuse cross-hash comparison"), and §16 states the
runtime constraint that makes the first term possible ("Docker,
digest-pinned, because ``evaluator_hash`` requires digests not tags"). The
module docstrings in this package record the mechanics; this one records the
three decisions a reader of the package's surface most needs.

*One identity, two terms, one spelling.* :func:`evaluator_digest` is the
formula; :class:`EvaluatorIdentity` is the formula's result together with
the terms it folded. The terms are carried beside the hash because a hash is
one-way — a row holding only the hash can say *that* two scores came from
different evaluators, never *how*, and feature 71's refusal is only
actionable when it can name the digest or the setting that moved. Both terms
have exactly one canonical spelling (the ``sha256:<64 hex>`` digest; compact,
key-sorted JSON), so two callers who mean the same evaluator compute the same
hash however they happened to write it down.

*The image must be pinned.* A tag-only reference is refused, not resolved:
resolving one would need a registry call at hash time and would fold
different digests on different days with no record that it had. A caller
holding a tag resolves it to a digest out of band, where the resolution can
be recorded. Canary feature 135 states the same refusal as its own feature.

*The row is assigned once.* :class:`EvaluatorIdentityStore` keys on the
hash and never updates a row in place — the hash is a pure function of its
terms, so a rewritten row could keep pointing at one evaluator while
describing another, and every score compared against it afterwards would be
wrong in the direction the system cannot detect. Rows are *read back* rather
than trusted, so a row edited outside this package fails to reconstruct
instead of loading as a plausible-looking lie.

*Nothing is resolved at construction.* The factory builds every registered
component on every ``create_app()`` — in a bare test process, in a factory
scan, and on the replay path, which architecture §1 forbids from reaching
the evaluator at all. So this package's builder must construct its service
without a pinned image, a database, or a parseable ``NULLIUS_EVALUATOR_CONFIG``:
each is resolved on first use, or at construction for a caller that asks for
the check with ``EvaluatorService.from_env(strict=True)``. The refusals are
unchanged — a tag-only image is still rejected, "persists" still needs
somewhere to persist to — they simply happen where the message is
informative instead of taking down composition for every unrelated feature
in the workspace.

Two contract notes for anyone composing or extending this component:

*Registration.* This package opts into the application factory by decorating
a zero-argument builder with :func:`app.module_loader.register` — in this
module, deliberately, not in a submodule: the loader re-executes a package's
``__init__`` on every composition but does not re-execute an already-cached
submodule, so a builder that lived in one would fire on the first
``create_app()`` of a process and silently drop out of every later one. The
factory discovers this package by scanning the declared workspace members —
no central file names it, and none may. All intra-package imports are
relative, so the package imports identically under its own name and under
the loader's scan-time name.

*Nothing here evaluates anything.* This member owns the evaluator's
*identity* — the thing §14.1 calls the first third of the provenance triple
— and nothing else. The pipeline (window resolution, sandboxed execution,
normalization, alignment, the null gate, purge and embargo, costs, metrics)
is the rest of this category's features, and each layers on this identity
rather than beside it: a score that cannot name its evaluator cannot be
compared, so the identity is what those features address. Keeping the import
this cheap also keeps the replay path importable — architecture §1 forbids
replay from reaching the evaluator at all, so the less this package does at
import time, the less there is to accidentally invoke.
"""

from app.module_loader import register

from ._config import (
    DEFAULT_CONFIG,
    ENV_CONFIG,
    EvaluatorConfig,
    canonical_config,
    resolve_config,
)
from ._errors import (
    EvaluatorConfigError,
    EvaluatorError,
    EvaluatorIdentityError,
    EvaluatorImageError,
    EvaluatorStoreError,
)
from ._identity import (
    EVALUATOR_HASH_LENGTH,
    EvaluatorIdentity,
    evaluator_digest,
    evaluator_identity,
    normalize_evaluator_hash,
)
from ._image import (
    DIGEST_ALGORITHM,
    DIGEST_HEX_LENGTH,
    ImageRef,
    coerce_image_ref,
    image_digest,
    parse_image_ref,
)
from ._service import ENV_IMAGE, EvaluatorService, build_evaluator_service
from ._store import (
    DATABASE_URL_ENV,
    IDENTITY_TABLE,
    EvaluatorIdentityStore,
    identity_from_row,
)

__all__ = [
    # Feature 70 — the identity
    "EVALUATOR_HASH_LENGTH",
    "EvaluatorIdentity",
    "evaluator_digest",
    "evaluator_identity",
    "normalize_evaluator_hash",
    # Feature 70 — the first term: the pinned container image
    "DIGEST_ALGORITHM",
    "DIGEST_HEX_LENGTH",
    "ImageRef",
    "coerce_image_ref",
    "image_digest",
    "parse_image_ref",
    # Feature 70 — the second term: the resolved configuration
    "DEFAULT_CONFIG",
    "ENV_CONFIG",
    "EvaluatorConfig",
    "canonical_config",
    "resolve_config",
    # Feature 70 — persistence
    "DATABASE_URL_ENV",
    "IDENTITY_TABLE",
    "EvaluatorIdentityStore",
    "identity_from_row",
    # The composed component
    "ENV_IMAGE",
    "EvaluatorService",
    "build_evaluator_service",
    # Errors
    "EvaluatorConfigError",
    "EvaluatorError",
    "EvaluatorIdentityError",
    "EvaluatorImageError",
    "EvaluatorStoreError",
]

__version__ = "0.1.0"


@register("evaluator")
def _registered_evaluator_service() -> EvaluatorService:
    """Component builder: the evaluator service, configured from the environment.

    Constructs without touching the environment's *values*: the image, the
    store and the configuration override are all resolved on first use, so
    this builder cannot fail composition (see the module docstring). The
    refusals they carry are unchanged — an unpinned or tag-only image is
    rejected, as is a missing store — they simply land at the first call that
    needs them, where the message names the deployment's own
    misconfiguration. A caller that wants the check at startup uses
    ``EvaluatorService.from_env(strict=True)``.
    """
    return build_evaluator_service()
