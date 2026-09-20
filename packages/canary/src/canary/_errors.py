"""The canary plugin's error taxonomy.

One base class (:class:`CanaryError`) so a caller — the nightly runner, an
operator's health check, the determinism suite §19 files under
``tests/determinism`` — can catch every failure of the determinism
canary's assertions with a single ``except``. The subclasses split by
*which contract* was violated, not by which line of code failed:

* :class:`CanaryImageError` — the container-pinning contract (app_spec.xml
  feature 135, the plugin's root feature). Architecture §12's determinism
  table opens with "Pinned evaluator | Container digest in
  ``evaluator_hash``; refuse cross-hash comparison", and §16's runtime row
  is "Docker, digest-pinned, because ``evaluator_hash`` requires digest
  pinning, not tags". A tag is a mutable pointer — the same tag resolves
  to different bytes next week — so a tag-only reference is refused here
  rather than swept past, and the refusal is raised once for the whole
  declaration, naming every offender, because a sweep that reported only
  the first would be re-run N times to learn what one run should have
  said. The same error covers the declaration that names no containers at
  all (a sweep over an empty set passes vacuously, and vacuous green is
  the one reading the nightly canary must never allow) and an environment
  variable that names no reference (an evaluation container nobody named
  is an evaluation container nobody pinned).

Later features in this category add the rest of §12's table — the
lockfile, the thread caps, ``PYTHONHASHSEED``, the import allowlist, the
GPU refusal, the inference refusal — and each brings its own subclass
rather than folding into this one: a caller halting dreaming (§15's
"Replay non-determinism" recovery) needs to know *which* line of the
contract broke, because the recovery differs (bisect the image diff is
not reinstall-from-lockfile). :class:`CanaryDeviceError` is that GPU
refusal, feature 140 — a GPU (or an unrecognized device) declared in the
eval or replay path — and it follows the rule rather than extending the
second: a deployment can be perfectly pinned and still run on a GPU,
which is the failure §12 names directly ("no GPU in the eval path"),
because a GPU kernel's reduction order is fixed by its block and grid
shape rather than by the input, so two runs of one seeded signal can
diverge in float. The repair for a moved pin is to re-pin; the repair
for a GPU in the path is to remove it and run on the CPU; and the class
split is what makes the difference legible at the ``except``.

:class:`CanaryReproducibilityError` is the third such subclass, and it
follows that rule rather than extending the second.  Feature 145
(app_spec.xml) asserts that "output [is] bit-identical across two runs of
the same seeded signal", which is §12's *last* row, "Float
reproducibility | Fixed reduction order; no ``fastmath``; no GPU in the
eval path" — and it is a strictly wider statement than the pin. A digest
can be perfectly pinned while the bytes a container emits still differ
run to run (a threaded reduction reassociating, a dict-ordered reduction
seeing a different insertion order, a ``fastmath`` contract collapsing a
sum): that is exactly the failure §12 calls out as invisible, because
non-determinism "does not announce itself". So a caller holding both
failures needs to tell them apart — the repair for a moved pin is to
re-pin, the repair for divergent bytes is bisect-the-image-diff — and the
class split is what makes the difference legible at the ``except``.

:class:`CanaryInferenceError` is the fourth such subclass — feature 146,
the table's closing row ("No inference in the replay path") — and it is
the one refusal in this taxonomy that is raised against a *call at
runtime* rather than a declaration a deployment wrote: the pin, the
device and the byte-comparison failures are read off strings or bytes
that already exist, while this one fires at the moment a learned
component reaches for a model from inside a replay. Its repair is
likewise the only one that points *forward* in the pipeline: materialize
the learned output at evaluation time and read back the stored floats
(§11.2), rather than fixing anything in the replay itself.
"""

from __future__ import annotations

__all__ = [
    "CanaryError",
    "CanaryDeviceError",
    "CanaryImageError",
    "CanaryImportError",
    "CanaryInferenceError",
    "CanaryReproducibilityError",
]


class CanaryError(Exception):
    """Base class for every failure of the determinism canary's assertions."""


class CanaryDeviceError(CanaryError):
    """A GPU (or an unrecognized device) is declared in the eval or replay path.

    Raised by :func:`~canary.reject_gpus` and :func:`~canary.reject_gpus_from_env`
    when the evaluation path or the replay path declares a GPU — or a device
    the sweep cannot place — rather than the CPU. This is app_spec.xml feature
    140: "System rejects any GPU device in the evaluation path and in the
    replay path, because float reproducibility requires a fixed reduction
    order", which is §12's "Float reproducibility | Fixed reduction order; no
    ``fastmath``; no GPU in the eval path" row made into something a run can
    fail.

    Deliberately its own subclass rather than folded into
    :class:`CanaryImageError` (a moved pin) or :class:`CanaryReproducibilityError`
    (divergent bytes): the three are three different breaks of §12's contract
    with three different repairs. A moved pin is re-pinned; divergent bytes are
    bisected; a GPU in the path is removed and the path re-run on the CPU. A
    caller halting dreaming (§15's "Replay non-determinism" recovery) needs to
    know *which* line of the contract broke, because the recovery differs, and
    the class split is what makes that legible at the ``except``. A caller
    catching :class:`CanaryError` still gets all of them.

    The refusal is collective: one error names every path that declared a GPU,
    with the variable behind it and the value as written, because a sweep that
    reported only the first would be re-run to learn the rest, and the operator
    of a nightly assertion reads the whole deployment's device state in one
    message.
    """


class CanaryImageError(CanaryError):
    """An evaluation container is not pinned by image digest.

    Raised for a tag-only or bare reference (never a digest), for a digest
    that is not ``sha256:<64 lowercase hex>``, for a declaration naming no
    containers at all, and for an environment that names no reference for
    a declared container. The refusal names the role — and the environment
    variable, when the declaration came from one — for every offender at
    once, because the feature's word is *every*.
    """


class CanaryImportError(CanaryError):
    """Searched code reaches for the wall clock or the unseeded stream.

    Raised by :func:`~canary.screen_imports` (and the allowlist's own
    :meth:`~canary.ImportAllowlist.screen`) when a submission imports
    ``time``, resolves a call onto a ``datetime`` clock constructor, or
    draws from the module-level ``random`` stream — and by
    :func:`~canary.allowlist_from_env` and :class:`~canary.ImportAllowlist`
    construction when a *configured* allowlist tries to admit one of
    those terms. This is app_spec.xml feature 139: "System rejects a
    searched-code import of time, datetime.now or unseeded random
    through the import allowlist", which is §12's "No wall clock in
    searched code | ``time``, ``datetime.now``, ``random`` without seed
    blocked by the import allowlist" row made into something a
    submission fails at admission, before it ever runs.

    Deliberately its own subclass rather than folded into
    :class:`CanaryImageError` (a moved pin), :class:`CanaryDeviceError`
    (a GPU in the path) or :class:`CanaryInferenceError` (a model call
    from the replay path): those three refuse a *deployment's* state or
    a *runtime* call, while this one refuses *the code the search wrote*
    — a different author (the loop, not the operator), a different
    repair (fix the submission: read time as an argument, draw
    randomness through a seeded ``random.Random``), and a different
    moment (admission, before anything executes). §15's failure table
    files the drift this refusal prevents as the same canary drift the
    whole category exists to catch, because a score that read the clock
    is a score no frozen pair can reproduce. A caller catching
    :class:`CanaryError` still gets all of them.

    The refusal is collective: one error names every refused import and
    call with its line and the reason the term is refused, because a
    screen that reported only the first would be resubmitted to learn
    the rest. Unparseable source raises this class too — a screen that
    silently passed what it could not read would be the vacuous green
    the nightly canary must never allow.
    """


class CanaryInferenceError(CanaryError):
    """A model inference call was made from the replay path.

    Raised by :func:`~canary.model_inference` when the call arrives inside
    the dynamic extent :func:`~canary.replaying` marks — the replay path —
    and by anything that runs under it, which includes feature 142's
    :func:`~canary.replay_pair` (it enters the extent around its whole
    computation, so a call attempted anywhere in the replay is refused).
    This is app_spec.xml feature 146: "System rejects a model inference
    call made from the replay path, because replay reads materialized
    values rather than computing them" — §12's closing table row, "No
    inference in the replay path | Replay calls no model of any kind.
    Learned outputs, if ever adopted, are materialized at evaluation time
    and read back as stored floats". The refusal fires *before* the model
    runs: a learned output computed inside the replay would be a value no
    frozen pair ever contributed, and the ``1e-12`` comparison would then
    faithfully compare a number nothing had frozen.

    Deliberately its own subclass rather than folded into
    :class:`CanaryImageError` (a moved pin), :class:`CanaryDeviceError` (a
    GPU in the path) or :class:`CanaryReproducibilityError` (divergent
    bytes): the four are four different breaks of §12's contract with four
    different repairs. §15's failure table files this one as "Learned
    component reached the replay path un-materialized" — canary drift, a
    replay score that varies with batch shape or thread count — and its
    recovery is to halt dreaming and revert to stored-float artifacts
    (§11.2), which is neither re-pinning an image, nor removing a GPU, nor
    bisecting a byte diff. A caller catching :class:`CanaryError` still
    gets all of them.

    The message names the model and states the repair — materialize the
    output where it is evaluated and read back the stored floats — because
    §15's recovery is an operator's decision, and an operator reads the
    message.
    """


class CanaryReproducibilityError(CanaryError):
    """Two runs of one seeded signal did not produce the same bytes.

    Raised by :func:`~canary.assert_bit_identical` when the byte-level
    comparison of a seeded signal's two runs comes back unequal — and
    only then. A byte-level comparison that *returns* a result is the
    feature (app_spec.xml feature 145: "which returns a byte-level
    comparison result"), so the verdict is a value the caller can record,
    file against a run, or branch on; this error is the spelling for the
    caller who asked the check to raise instead.

    Deliberately not :class:`CanaryImageError`. A deployment can be
    perfectly pinned — every container at a frozen digest, every library
    in the lockfile — and still emit different bytes twice, which is the
    failure mode §12 names directly: threaded reductions reassociating, a
    ``fastmath`` contraction, a reduction over an unordered container.
    The two failures share a category (both are §12's determinism
    contract breaking) but not a repair: a moved pin is re-pinned,
    divergent bytes are bisected. A caller catching :class:`CanaryError`
    gets both; one catching this class gets exactly the one it can act
    on.

    The message carries the field names, the two digests and the offset
    of the first differing byte — enough for an operator to decide
    whether the divergence is a reassociated reduction (a low byte of one
    float) or a different result set entirely — without carrying the
    bytes themselves, which for a score panel are far too large to paste
    into a log line.
    """


# :class:`CanaryDeterminismBrokenError` is the taxonomy's fifth subclass, and
# it does not live in this module: it is defined in :mod:`canary._halt` beside
# the :class:`~canary.DreamHalt` record it carries on its ``halt`` attribute —
# the placement rule :mod:`snapshot` states for its own corruption error, an
# exception meaningless without the record's type beside it.  The paragraph
# above anticipated it: "a caller halting dreaming (§15's 'Replay
# non-determinism' recovery) needs to know *which* line of the contract broke",
# and a nightly canary whose score drifted from its recorded constant is that
# fifth break — not a moved pin (re-pin it), not a GPU in the path (remove it),
# not a model inference call from the replay path (materialize it, §11.2), not
# an unscorable tree (re-freeze the reference), not divergent bytes from two
# runs of one signal (bisect the runs' diff), but §12's closing assertion, the
# one whose repair is §15's *halt dreaming; bisect the image diff* and a fresh
# frozen pair.  Exported from the package root beside the other four, so the
# single ``except`` :class:`CanaryError` this module promises still catches it.
