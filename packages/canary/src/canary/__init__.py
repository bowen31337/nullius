"""The determinism canary, as a workspace component.

Features (app_spec.xml, "Determinism Guarantees & Nightly Canary",
feature 135): pin every evaluation container by image digest rather
than by tag, which rejects a tag-only reference.
docs/nullius-tech-architecture.md §12 opens the determinism contract's
table with exactly this line ("Pinned evaluator | Container digest in
``evaluator_hash``; refuse cross-hash comparison"), §16 states the
runtime that makes it possible ("Docker, digest-pinned, because
``evaluator_hash`` requires digest pinning, not tags"), and §19 files
the canary under ``ops/`` beside the alerting it will one day feed.
The module docstrings in this package record the mechanics; this one
records the decisions a reader of the package's surface most needs.

*The canary is the auditor, not the owner.* The evaluator member
(feature 70) folds one image's digest into one ``evaluator_hash`` — an
identity, answering "which bytes produced this score?". This package
answers the wider question the category is named for: is *every*
container the evaluation path runs in pinned, today, as deployed? The
distinction matters because the two can disagree in exactly the
direction that voids §12's table: an evaluator whose own image is
pinned, running beside a helper container that is not, computes
provenance-stamped scores inside an environment nobody froze — every
other line of the table ("single-threaded numerics", "no wall clock",
"stable iteration order") is an environment *inside* the container
this line pins. The sweep here is therefore over a *set* of declared
roles (:data:`IMAGE_ENV_VARS`), complete in one refusal, and the
evaluator's own variable — ``NULLIUS_EVALUATOR_IMAGE`` — is one entry
in it rather than a special case, so a deployment states a pin once
and both the identity and the audit read the same spelling.

*A tag is refused, never resolved.* Resolving one would need a
registry call at sweep time and would pin different bytes on different
days with no record that it had moved — the drift the pin exists to
make impossible. A caller holding a tag resolves it to a digest out of
band, where the resolution can be recorded, and pins that. The
evaluator member's ``_image`` records the same refusal for its own
term and points here: this feature states it independently, for every
container at once.

*Nothing is resolved at construction.* The factory builds every
registered component on every ``create_app()`` — in a bare test
process, in a factory scan, and on paths with no evaluation containers
to guard — so this package's builder constructs its service without a
complete environment and lets the sweep land on first use, where the
refusal names the deployment's own misconfiguration instead of taking
composition down for every unrelated feature in the workspace. A
caller that wants the check at startup instead builds strictly:
``CanaryService.from_env(strict=True)``.

*Registration.* This package opts into the application factory by
decorating a zero-argument builder with :func:`app.module_loader.register`
— in this module, deliberately, not in a submodule: the loader
re-executes a package's ``__init__`` on every composition but does not
re-execute an already-cached submodule, so a builder that lived in one
would fire on the first ``create_app()`` of a process and silently
drop out of every later one. The factory discovers this package by
scanning the declared workspace members — no central file names it,
and none may. All intra-package imports are relative, so the package
imports identically under its own name and under the loader's
scan-time name.

*Feature 145 sits beside the pin, not inside it.* The category's
fifteenth feature asserts "bit-identical output across two runs of the
same seeded signal, which returns a byte-level comparison result" — §12's
*last* table row ("Float reproducibility | Fixed reduction order; no
``fastmath``; no GPU in the eval path") rather than its first, which the
pin sweep above owns. The two are deliberately separate surfaces: a
deployment can be perfectly pinned and still emit different bytes twice,
and a caller must be able to tell those apart because the repairs differ.
So :mod:`canary._reproducibility` is a set of pure functions
(:func:`compare_runs`, :func:`compare_bytes`, :func:`require_identical`,
:func:`assert_bit_identical`) that read no environment and can refuse
nothing — there is nothing to configure and so no second *component* here.
The composed service nevertheless carries them, through
:class:`BitReproducibility` at ``service.reproducibility``, because a check
reachable only by import is a check the factory's scan cannot discover: the
tripwires member's probe and the evaluator's service take the same stance
for their own pure functions.

*What this package deliberately does not do.* It does not resolve
tags, consult a registry, or write anything down: feature 135 is an
assertion, not a persistence step, so the member is a pure parser over
strings a deployment already wrote, stdlib-only and import-cheap — the
factory's scan (and the replay path §1 keeps away from anything that
could perturb it) pays nothing for importing it. Feature 145 holds the
same line: the comparison is over bytes the caller already holds, so it
serializes nothing itself (the layers that own the encodings — the
sandbox's Arrow IPC channel, the artifact renderer, the feature store's
payload — are the ones that must produce canonical bytes) and reads no
environment, which is what lets a recorded payload and a replayed one be
compared by the same code that compares two fresh runs. The later
features of this category layer onto the pin this package keeps: the
lockfile, thread, hash-seed, allowlist and GPU refusals of features
136-140
assert into the same frozen container from the same sweep, the frozen
pair and nightly replay of features 141-144 turn the pin into the
reference the recorded constant is compared under, and the
bit-reproducibility check of feature 145 reads that pair back — a
caller's run output and a recorded one, compared byte for byte by the
same function that compares two fresh runs. A canary that could not say
which bytes it ran in could not honestly say any of those things
either.
"""

from app.module_loader import register

from ._errors import (
    CanaryError,
    CanaryImageError,
    CanaryReproducibilityError,
)
from ._image import (
    DIGEST_ALGORITHM,
    DIGEST_HEX_LENGTH,
    PinnedImage,
    image_digest,
    parse_pinned_image,
)
from ._containers import (
    EVALUATOR_ROLE,
    IMAGE_ENV_VARS,
    PinnedContainers,
    pin_containers,
    pinned_containers_from_env,
)
from ._reproducibility import (
    BitReproducibility,
    ByteComparison,
    SeededSignal,
    assert_bit_identical,
    compare_bytes,
    compare_runs,
    require_identical,
)
from ._service import CanaryService, build_canary_service

__all__ = [
    # Feature 135 — the pin vocabulary
    "DIGEST_ALGORITHM",
    "DIGEST_HEX_LENGTH",
    "PinnedImage",
    "image_digest",
    "parse_pinned_image",
    # Feature 135 — the sweep over every evaluation container
    "EVALUATOR_ROLE",
    "IMAGE_ENV_VARS",
    "PinnedContainers",
    "pin_containers",
    "pinned_containers_from_env",
    # Feature 145 — bit-identity across two runs of one seeded signal
    "BitReproducibility",
    "ByteComparison",
    "SeededSignal",
    "assert_bit_identical",
    "compare_bytes",
    "compare_runs",
    "require_identical",
    # The composed component
    "CanaryService",
    "build_canary_service",
    # Errors
    "CanaryError",
    "CanaryImageError",
    "CanaryReproducibilityError",
]

__version__ = "0.1.0"


@register("canary")
def _registered_canary_service() -> CanaryService:
    """Component builder: the canary service, configured from the environment.

    Constructs without resolving anything: the pin sweep runs on first
    use, so this builder cannot fail composition (see the module
    docstring) — in a bare test process, in a factory scan, and on paths
    with no evaluation containers at all. The refusal the sweep carries
    is unchanged — an unset, blank or tag-only reference behind any
    declared variable is rejected, naming every offender — it simply
    lands at the first call that asks whether the deployment is pinned,
    where the message is informative. A caller that wants the check at
    startup uses ``CanaryService.from_env(strict=True)``.
    """
    return build_canary_service()
