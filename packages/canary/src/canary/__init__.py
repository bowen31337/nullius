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

*Feature 140 is the GPU refusal, over both paths, as the sweep's own
assertion.* The category's sixteenth feature states §12's "Float
reproducibility | Fixed reduction order; no ``fastmath``; no GPU in the eval
path" row and the prerequisites' "No GPU anywhere; GPU is prohibited in both
the evaluation and replay paths" — the correction §12.1 applies, that the
prohibition reaches the replay path too, a separate deployment (§13) that
reads materialized floats. A GPU kernel sums in an order fixed by its block
and grid shape rather than by the input, so two runs of one seeded signal
over the same bytes can diverge in float — the divergence the ``1e-12``
canary exists to catch — and this feature refuses the GPU before it can run.
Like the pin sweep it is a pure parser over strings a deployment already
wrote — :mod:`canary._device` is :func:`classify_device` (a device string to
:attr:`~canary.CPU` or :attr:`~canary.GPU`, refusing an unrecognized value),
:func:`reject_gpus` (the explicit declaration) and :func:`reject_gpus_from_env`
(the environment spelling) — and, like the pin sweep, it reads no environment
at import and resolves nothing. But it differs from the pin sweep in one
load-bearing way: the image sweep refuses an *empty* declaration (a sweep over
zero containers is vacuously green, the one reading the nightly canary must
never allow), while the device sweep refuses a *GPU* and accepts an *empty*
declaration — the contract is "no GPU", and a deployment satisfies it by
running on the CPU, which is the default reached by declaring nothing. So an
unset device variable is the passing case, classified and recorded as the CPU,
and the sweep is never vacuous because it always checks the same two fixed
paths — :data:`EVAL_PATH` and :data:`REPLAY_PATH`, each read from its own
variable in :data:`DEVICE_ENV_VARS` — and asserts neither names a GPU. The
refusal is collective: one :class:`~canary.CanaryDeviceError` names every path
that declared a GPU, with the variable behind it and the value as written. The
composed service carries the sweep at ``service.devices``, beside
``service.containers`` — the same seam, the same laziness (resolved on first
use, so composition never fails on a deployment's device configuration) — for
the same reason the pin sweep and feature 145's check are carried there.

*Feature 141 sits beside the pin, as the persistence half of the frozen
pair.* The category's fourteenth-through-seventeenth features turn the pin
into the reference the nightly replay compares under: feature 141 persists
"a frozen canary policy together with a frozen canary tree as the
determinism reference pair", and the nightly replay (feature 142) replays
that frozen pair and asserts its score matches a recorded constant to
``1e-12`` (§12, line 677).  The frozen pair is a thing with its own identity
— a policy ``π_canary`` and a tree ``T_canary``, each reduced to canonical
bytes and a content hash — so :mod:`canary._reference` is the set of value
types (:class:`CanaryPolicy`, :class:`CanaryTree`, :class:`CanaryTreeNode`,
:class:`CanaryReferencePair`, plus :func:`canonical_json`, :func:`content_hash`
and :func:`tree_hash`) that make the pair a thing that can be frozen, hashed
and told apart from a pair that is not the same pair.  Like feature 145's
functions, these read no environment and refuse nothing — there is nothing to
configure — but unlike them they are *persisted*, so feature 141 has a second
component: the reference store, :mod:`canary._reference_store`, registered
under :data:`REFERENCE_STORE_COMPONENT_NAME` beside the pin sweep's
:data:`canary.CANARY_COMPONENT_NAME`.  The two are different things on
different lifecycles — one asserts the deployment's pins, the other persists
the frozen pair — and a deployment configured for the pin but not the store
composes one and not the other.  The store writes the canonical bytes and the
hashes, never the rendered walk; the recorded score the replay compares
against is left ``Nullable`` and filled by the replay (feature 142), not by
the freeze — this feature *freezes*, the next one *replays and decides*, and a
store that also decided would be a threshold nobody could audit.

*Feature 142 is the replay itself, beside the frozen pair, not inside it.*
The category's fifteenth-through-sixteenth features turn the frozen pair into
the nightly assertion §12's line 677 spells — *"replay a frozen policy
``π_canary`` over a frozen tree ``T_canary`` and assert the score matches a
recorded constant to ``1e-12``"*.  Feature 141 made the pair a thing that can
be frozen and read back; feature 142 is the verb that runs it — :mod:`canary._replay`
is the pure function (:func:`replay_pair`) that takes the frozen pair and runs
the policy over the tree, once, in a stable order, to a single float, and
returns the :class:`CanaryReplayResult` — the score, the recorded constant it
is compared against, the deviation and the ``1e-12`` tolerance band.  Like
feature 141's value types it reads no environment and resolves nothing — the
pair is handed in, already frozen and read back — but unlike them it *computes*
rather than merely holds, and the computation is the one §12's table must be
invariant to.  It deliberately computes the score and reports the comparison
without deciding it: :attr:`CanaryReplayResult.within_tolerance` is the four
terms of line 677's ``abs(score - CANARY_EXPECTED) > 1e-12`` carried as a
value, and the halt-dreaming and the ``determinism_broken`` alert are feature
143's, which owns the ``1e-12`` decision so it sits in exactly one place an
operator can audit.  The composed service carries the replay through
:attr:`CanaryService.replay`, for the same reason it carries the pin sweep and
feature 145's check: a replay reachable only by import is a replay the
factory's scan cannot discover.

*Feature 143 is the decision the replay left open, and the halt is a store.*
app_spec.xml gives the category its cq-15 feature: *"System halts dreaming
when the canary score differs from the recorded constant by more than 1e-12,
which emits a determinism_broken alert"* — §12 line 677's two statements
under the ``if``, ``halt_dreaming()`` and ``alert(...)``.  :mod:`canary._halt`
is that decision: :func:`halt_dreaming` takes the pair and the replay's
result, and when the result broke under the one threshold this package spells
once (:data:`DEFAULT_TOLERANCE`), writes one row — the break, its arithmetic,
its instant, keyed by the pair's content fingerprint — and then raises
:class:`CanaryDeterminismBrokenError` carrying that record on its ``halt``
attribute; when the result did not break, the ``if`` was not taken, nothing
is written and the call quietly returns.  Raising is the emission and the
record is the payload, the stance :mod:`snapshot` takes for its corruption
alert, and the row is written before the raise so a monitor that catches the
alert to keep reporting still leaves the halt on record.  Like feature 141's
store this is a *persistence* step, so it is a third registered component —
:data:`HALT_STORE_COMPONENT_NAME`, ``canary-dream-halt`` — beside the pin
sweep and the reference store: the sweep asserts the deployment's pins, the
reference store holds the frozen pair, and this one answers *"is dreaming
halted?"* — a different question on a different lifecycle, composed
independently of either other.  The halt is monotone — no code path writes a
row away; §15's recovery (*halt dreaming; bisect the image diff*) is the
operator's — and the *first* break is the fact on record, because feature
144's void markers key on the break's ``detected_at`` ("every score produced
after a detected determinism break"), and a refresh that moved the instant
forward would quietly shrink the window that feature exists to widen.

*A break costs the data it was measured over, and that is a
persistence step of its own.* Feature 144 (app_spec.xml) answers the
closing clause of §12's canary paragraph — "halts dreaming and marks
scores produced in the affected window as void" — and it is the one
feature of this package that *reads another member's table*. Feature
143 detects and records; feature 144 takes what the detection cost:
every ``replay_score`` row produced after the break is persisted with a
void marker, so the pool stops serving it. The reach is the one
``tripwires.excise`` makes for feature 132 and for the same reason —
the pool is a table this member does not own, and members here do not
import each other (the canary is imported on every factory scan and on
the replay path §1 keeps free of moving parts), so the shape is
restated once with a provenance comment rather than imported. Nothing
is ever written *to* the pool: the score rows are evidence, the marker
is a row in this member's own ``canary_void_marker`` table, and the
refusal is *derived* from the marker plus the window, so a score
written after the break is refused even before a sweep has run over it
— no lag in which bad data is served, which is the "does not age into
good data" half of the sentence made structural. The window's edge is
the **earliest** break on record (:meth:`CanaryHaltStore.first_halt`,
added here for this feature rather than a second reader of the halt
table), strictly compared, so a later break on another pair can only
widen the affected window and a score once void stays void. Voiding a
score whose canary held is refused outright: the feature is about bad
data, not about its absence. Like features 141 and 143 this is a
*persistence* step, so it is a fourth registered component —
:data:`VOID_MARKER_COMPONENT_NAME`, ``canary-void-marker`` — beside the
pin sweep, the reference store and the halt store: the pin sweep
answers *is the deployment pinned?*, the reference store *what is the
frozen pair?*, the halt store *is dreaming halted?*, and this one *may
this score still be used?* — a fourth question on a fourth lifecycle,
composed independently of the other three.

*What this package deliberately does not do.* It does not resolve
tags or consult a registry: feature 135 is an assertion, not a
resolution, so the pin sweep is a pure parser over strings a deployment
already wrote, stdlib-only and import-cheap — the factory's scan (and
the replay path §1 keeps away from anything that could perturb it) pays
nothing for importing it.  Feature 145 holds the same line: the
comparison is over bytes the caller already holds, so it serializes
nothing itself (the layers that own the encodings — the sandbox's Arrow
IPC channel, the artifact renderer, the feature store's payload — are
the ones that must produce canonical bytes) and reads no environment,
which is what lets a recorded payload and a replayed one be compared by
the same code that compares two fresh runs.  Feature 141 is the one
place the package writes down: it persists the frozen pair the nightly
replay reads back, through the store and the four tables
``migrations/versions/0119_canary_reference_pair.py`` creates — the one
persistence step in a category that is otherwise assertions over bytes a
deployment already wrote.  The later features of this category layer
onto the pin this package keeps: the lockfile, thread, hash-seed,
allowlist and GPU refusals of features 136-140 assert into the same
frozen container from the same sweep, the frozen pair and nightly replay
of features 141-144 turn the pin into the reference the recorded
constant is compared under, and the bit-reproducibility check of feature
145 reads that pair back — a caller's run output and a recorded one,
compared byte for byte by the same function that compares two fresh
runs.  A canary that could not say which bytes it ran in could not
honestly say any of those things either.
"""

from typing import Optional

from app.module_loader import register

from ._containers import (
    EVALUATOR_ROLE,
    IMAGE_ENV_VARS,
    PinnedContainers,
    pin_containers,
    pinned_containers_from_env,
)
from ._device import (
    CPU,
    DEVICE_ENV_VARS,
    EVAL_PATH,
    GPU,
    REPLAY_PATH,
    CanaryDeviceError,
    DevicePaths,
    reject_gpus,
    reject_gpus_from_env,
)
from ._errors import (
    CanaryError,
    CanaryImageError,
    CanaryReproducibilityError,
)
from ._halt import (
    DETERMINISM_BROKEN,
    HALT_MESSAGE,
    HALT_STORE_COMPONENT_NAME,
    HALT_TABLE,
    CanaryDeterminismBrokenError,
    CanaryHaltStore,
    DreamHalt,
    build_halt_store,
    determinism_broken_error,
    halt_dreaming,
    require_dreaming_allowed,
)
from ._image import (
    DIGEST_ALGORITHM,
    DIGEST_HEX_LENGTH,
    PinnedImage,
    image_digest,
    parse_pinned_image,
)
from ._reference import (
    CanaryPolicy,
    CanaryReferencePair,
    CanaryTree,
    CanaryTreeNode,
    canonical_json,
    content_hash,
    tree_hash,
)
from ._reference_store import (
    POLICY_TABLE,
    REFERENCE_STORE_COMPONENT_NAME,
    REFERENCE_TABLE,
    TREE_NODE_TABLE,
    TREE_TABLE,
    CanaryReferenceStore,
    CanaryReferenceStoreRecord,
    build_reference_store,
    freeze_reference_pair,
    load_reference_pair,
)
from ._replay import (
    DEFAULT_TOLERANCE,
    CanaryReplay,
    CanaryReplayResult,
    CanaryReplayScoreError,
    replay_pair,
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
from ._void import (
    VOID_MARKER_COMPONENT_NAME,
    VOID_STATUS,
    VOID_TABLE,
    CanaryVoidMarkerError,
    CanaryVoidMarkerStore,
    VoidMarker,
    VoidSweep,
    VoidWindow,
    build_void_marker_store,
    mark_void_score,
    require_score_usable,
    unvoided_scores,
    void_scores_after_break,
)

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
    # Feature 140 — no GPU in the eval or replay path
    "CPU",
    "DEVICE_ENV_VARS",
    "EVAL_PATH",
    "GPU",
    "REPLAY_PATH",
    "CanaryDeviceError",
    "DevicePaths",
    "reject_gpus",
    "reject_gpus_from_env",
    # Feature 145 — bit-identity across two runs of one seeded signal
    "BitReproducibility",
    "ByteComparison",
    "SeededSignal",
    "assert_bit_identical",
    "compare_bytes",
    "compare_runs",
    "require_identical",
    # Feature 141 — the frozen determinism reference pair
    "CanaryPolicy",
    "CanaryReferencePair",
    "CanaryTree",
    "CanaryTreeNode",
    "canonical_json",
    "content_hash",
    "tree_hash",
    "CanaryReferenceStore",
    "CanaryReferenceStoreRecord",
    "POLICY_TABLE",
    "REFERENCE_TABLE",
    "TREE_NODE_TABLE",
    "TREE_TABLE",
    "build_reference_store",
    "freeze_reference_pair",
    "load_reference_pair",
    # Feature 142 — the nightly replay of the frozen pair to a score
    "DEFAULT_TOLERANCE",
    "CanaryReplay",
    "CanaryReplayResult",
    "replay_pair",
    # Feature 143 — the halt of dreaming and its determinism_broken alert
    "DETERMINISM_BROKEN",
    "HALT_MESSAGE",
    "HALT_STORE_COMPONENT_NAME",
    "HALT_TABLE",
    "CanaryDeterminismBrokenError",
    "CanaryHaltStore",
    "DreamHalt",
    "build_halt_store",
    "determinism_broken_error",
    "halt_dreaming",
    "require_dreaming_allowed",
    # Feature 144 — the void marker on every score after a break
    "VOID_MARKER_COMPONENT_NAME",
    "VOID_STATUS",
    "VOID_TABLE",
    "CanaryVoidMarkerError",
    "CanaryVoidMarkerStore",
    "VoidMarker",
    "VoidSweep",
    "VoidWindow",
    "build_void_marker_store",
    "mark_void_score",
    "require_score_usable",
    "unvoided_scores",
    "void_scores_after_break",
    # The composed component
    "CanaryService",
    "build_canary_service",
    # Errors
    "CanaryError",
    "CanaryImageError",
    "CanaryReproducibilityError",
    "CanaryReplayScoreError",
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


@register(REFERENCE_STORE_COMPONENT_NAME)
def _registered_reference_store() -> Optional[CanaryReferenceStore]:
    """Component builder: the frozen reference-pair store, from the environment.

    Feature 141's store half, composed under a second name rather than a second
    component under :data:`canary.CANARY_COMPONENT_NAME` — the pin sweep and the
    reference store are different things on different lifecycles, and a deployment
    configured for the pin but not the store composes one and not the other.
    Resolves rather than strict: the factory builds every component on every
    ``create_app()``, so a deployment with no ``DATABASE_URL`` composes ``None`` —
    a discoverable state, not an exception — rather than taking composition down.
    A caller that wants the store pointed at a URL uses :class:`CanaryReferenceStore`.
    """
    return build_reference_store()


@register(HALT_STORE_COMPONENT_NAME)
def _registered_halt_store() -> Optional[CanaryHaltStore]:
    """Component builder: the dream-halt store, from the environment.

    Feature 143's store half, composed under a third name for the same reason
    the reference store took a second: the pin sweep, the reference store and
    the halt store are three different things on three different lifecycles —
    one asserts the deployment's pins, one persists the frozen pair, one holds
    the halt of dreaming — and a deployment configured for any two composes
    the third independently.  Resolves rather than strict, exactly as
    :func:`_registered_reference_store` does: the factory builds every
    component on every ``create_app()``, so a deployment with no
    ``DATABASE_URL`` composes ``None`` — a discoverable state, not an
    exception — and the nightly runner that must halt dreaming is the caller
    :func:`canary.halt_dreaming` refuses by name, not the factory.  A caller
    that wants the store pointed at a URL uses :class:`CanaryHaltStore`.
    """
    return build_halt_store()


@register(VOID_MARKER_COMPONENT_NAME)
def _registered_void_marker_store() -> Optional[CanaryVoidMarkerStore]:
    """Component builder: the void-marker store, from the environment.

    Feature 144's store half, composed under a fourth name for the same reason
    the halt store took a third: the pin sweep, the reference store, the halt
    store and this one are four different things on four different lifecycles —
    one asserts the deployment's pins, one persists the frozen pair, one holds
    the halt of dreaming, and this one holds which scores the break voided —
    and a deployment configured for any three composes the fourth
    independently.  Resolves rather than strict, exactly as the other two
    stores do: the factory builds every component on every ``create_app()``, so
    a deployment with no ``DATABASE_URL`` composes ``None`` — a discoverable
    state, not an exception — and the nightly runner that must void the affected
    window is the caller :func:`canary.void_scores_after_break` refuses by name,
    not the factory.  A caller that wants the store pointed at a URL uses
    :class:`CanaryVoidMarkerStore`.
    """
    return build_void_marker_store()
