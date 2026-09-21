"""Feature 164's law: an invocation missing the thread-pinning env is refused.

app_spec.xml, "Untrusted Code Sandbox", feature 164: *System rejects a sandbox
invocation missing the thread-pinning environment.*  docs/nullius-tech-
architecture.md §5.2 gives the feature its call site — the one place a run is
described — and names the environment inside it::

    result = sandbox.run(
        entrypoint="signal",
        code=node.code,
        payload=window.to_arrow(),        # IPC, zero-copy
        limits=Limits(wall_s=30, cpu_s=30, mem_mb=2048,
                      network=False, filesystem=False, pids=32),
        seed=node.seed,
        env={"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
    )

§12's determinism table gives the same pair its own row — ``Single-threaded
numerics | ``OMP_NUM_THREADS=1``, ``MKL_NUM_THREADS=1`` in every eval worker`` —
and §5.2 closes its sandbox section with the sentence that makes the row a
*control* rather than a tuning note: *"Thread-count pinning is not a performance
setting. Multi-threaded BLAS reductions are non-deterministic in float, which
breaks P3."*  The sentence decomposes into three claims, each owned here as a
seam rather than a comment:

* **a sandbox invocation** — the subject, and the reason the refusal sits where
  it does.  Not a service, a store or a policy: *one dispatch* of one signal,
  the same unit :class:`sandbox.isolation.SandboxRun` models for feature 157 and
  the same unit feature 165 describes as an envelope
  (:class:`sandbox.seed.SandboxInvocation`).  What this law reads of that unit
  is its *environment* — the ``env=`` clause of §5.2's call — so the subject
  here is an environment mapping, or any object carrying one under ``.env``,
  which is what lets a launcher hand the *same* invocation to this law and to
  the seed's (``threads.require(invocation)`` beside
  ``seed_law.require(invocation)``) rather than describing the run twice.

* **missing the thread-pinning environment** — the term, and the word that
  decides the reading.  *Missing* is not *unset*: the law classifies every
  variable §12 names into three states — absent, pinned, and declared at
  something other than the pin — because a worker exported with
  ``OMP_NUM_THREADS=16`` is *more* dangerous than one that exported nothing:
  both are threaded, and only the second looks like a mistake.  A blank value
  (``""``, ``"   "``) is refused on the same terms, since it looks configured
  and names no count, so the library reading it applies its own default of one
  worker per core.  The third name this module knows
  (:data:`POOL_FLOOR_VARIABLE`) is a *floor* the deployment's own numerics
  library reads independently of the OMP caps and outranks there; a declared one
  that is wider than the pin is refused even with both caps pinned, because a
  sweep that stopped at the two §12 names would certify a worker whose
  reductions are visibly partitioned.

* **rejects** — the consequent, and the shape of the answer.  *Compile time:*
  :func:`compile_thread_pinning_policy` refuses — the whole document, not the
  offending block skipped — any policy that does not name every cap §12
  requires, names one of them at a value other than the pin, or cannot be read
  as a policy at all (:class:`~sandbox.errors.ThreadPinningDocumentError`).
  *Answer time:* :func:`check_thread_pinning` answers every invocation with a
  :class:`ThreadDecision`, and the answer is *computed* rather than assumed: it
  consults each cap's declared value in the subject's environment and the
  compiled policy's own value, so an admission is the law arriving at its
  answer — a decision reading :attr:`ThreadReason.BY_PINNING` on a run whose
  environment drifted is itself the audit finding.

**Why the refusal is raised at the compile and returned at the gate.**  The
split :mod:`sandbox.isolation` draws and states, for the same two audiences: a
policy document is written by *trusted* code — an operator, a CI check that
recompiles the committed artifact — so a document that drifted to another pin is
refused with an exception the caller cannot ignore
(:class:`~sandbox.errors.ThreadPinningRequired`).  A *run* is offered by the
pipeline, which §6.1 runs unattended over thousands of candidates, so the gate
*answers* it: a decision, raised for none, whose :attr:`ThreadDecision.admitted`
is ``False`` and whose reason says why.  The launcher that must not spawn calls
:meth:`SandboxThreads.require` — one line, the refusal or the environment to
dispatch with.

**A declared non-pin value is refused rather than repaired.**  This is the one
judgement in the module that could reasonably have gone the other way, and it
goes this way for the reason feature 165 refuses to overwrite a node record's
seed: the deployment *wrote something*, and a launcher that silently rewrote
``OMP_NUM_THREADS=16`` to ``1`` on the way past would leave a manifest and a box
disagreeing about the same fact with nothing recording which one ran.  The
repair has a home, and it is where the worker-side sweep put it: the worker is
*started* under the pins (:func:`canary.thread_capped_environment`), and this
law's refusal says so.  What :meth:`SandboxThreads.require` returns for an
admitted invocation is the policy's *spelling* of each pin written onto a copy
of the subject — not a repair, a normalization, so a declaration that classified
as the pin by surrounding whitespace does not reach the child as ``" 1 "``.

**Why this control ships a committed artifact when features 165 and 166 do not.**
:mod:`sandbox.transfer` and :mod:`sandbox.seed` both state their reason for
having none — their subjects are a *format* and a *value a run is handed*, and
neither is a thing a deployment could set differently — and this feature's
subject is neither: it is the *environment the deployment configures a run
with*, which is written down before it can be checked, exactly like feature
157's isolation and feature 167's allowlist.  So
:data:`COMMITTED_PINNING_POLICY` ships beside the law, and it is held to the law
rather than frozen by it: :data:`REQUIRED_CAPS` fixes *which* variables a
pinning policy must speak about — §12's two, each with the library layer it
governs — while the artifact carries the value and the floors, and the compiler
refuses a document that omits a required name or pins one at anything but
:data:`SINGLE_THREADED`.

**Relationship to feature 137, which is this fact on the other side of the
seam.**  ``canary._threads`` is the *worker* law — *"System rejects an
evaluation worker started without OMP_NUM_THREADS and MKL_NUM_THREADS set to
1"* — and it reads a worker's environment and, where a numerics library is
loaded, the pool that library actually resolved.  This module is the *dispatch*
law: the environment §5.2 hands *into* the box.  Two features, two subjects, one
row of §12, and the member's one-provenance rule is the reason the two cap names
are **restated here with this comment** rather than imported: ``packages/sandbox``
owns no dependency on any other member — the box agent-authored code is put
inside must not acquire one on the member that drives it — so the spelling is
pinned as *data* by this suite, the discipline feature 165 applies to
:data:`sandbox.seed.ENV_SIGNAL_SEED` against ``evaluator._sandbox``.

**Honest limits.**  This module is the *law about the environment*, not the
enforcement of it: it reads the mapping it is handed, and it never looks inside
a spawned process's ``/proc`` or asks a library what pool it resolved — the
measured pool is feature 137's reading, taken in the worker that loaded the
numerics.  A launcher that checked a clean environment and then dispatched a
dirty one, or that smuggled a count in through argv, is not visible here, the
same way a rogue egress allowance is not visible to feature 149's gate.  What
holds is that §5.2's call site cannot be dispatched through
:meth:`SandboxThreads.require` without the pins, that the committed artifact
cannot drift to another value without the compile failing, and that *which*
variables a deployment pins is a value the policy carries and a caller can read
(:meth:`ThreadPinningPolicy.pins`) — so "this run was dispatched
single-threaded" is a fact about the invocation rather than a line in a
runbook.

**It reads no ambient environment, and that is deliberate.**  Every other law in
this member is a pure function of its arguments, and this one is too: the
subject is the environment the invocation *carries*, never ``os.environ``.  A
caller that wants to know whether the process it is running in is pinned hands
its own environment in (``threads.check(os.environ)``), and the caller that is
about to dispatch hands the one it is about to dispatch with — which is the
environment the feature's sentence is about, and the one a test can supply
without a fixture clearing the developer's shell.

Stdlib-only, like the rest of the member: ``json`` for the artifact, ``re`` for
the one grammar the pin is read with, and no process, network, container runtime
or environment lookup anywhere.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .errors import (
    ThreadPinningDocumentError,
    ThreadPinningRequired,
)

__all__ = [
    "ABSENT",
    "COMMITTED_PINNING_POLICY",
    "ENV_MKL",
    "ENV_OMP",
    "PINNED",
    "PINNING_POLICY_KIND",
    "POOL_FLOOR_VARIABLE",
    "REQUIRED_CAPS",
    "SINGLE_THREADED",
    "THREADS_COMPONENT_NAME",
    "THREAD_PINNING_CODE",
    "UNPINNED",
    "SandboxThreads",
    "ThreadCap",
    "ThreadDecision",
    "ThreadPinningPolicy",
    "ThreadReason",
    "check_thread_pinning",
    "classify_cap",
    "committed_thread_pinning_policy",
    "compile_thread_pinning_policy",
    "load_thread_pinning_policy",
    "sandbox_threads",
]

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, feature 167's ``sandbox-imports``, feature 166's
#: ``sandbox-transfer`` and feature 165's ``sandbox-seed``, not instead of any
#: of them: the factory's registry is keyed by name and a later registration of
#: the same name *replaces* the earlier one, so a member carrying five controls
#: carries five components, each answering its own feature's question.
THREADS_COMPONENT_NAME: Final[str] = "sandbox-threads"

#: The marker a document declares itself with — the same discipline feature
#: 157's committed isolation artifact and feature 167's committed allowlist
#: take, so a stray JSON file carrying a ``caps`` key cannot be read as this
#: policy.
PINNING_POLICY_KIND: Final[str] = "sandbox-thread-pinning"

#: The committed artifact, shipped beside the law that checks it, so a checkout
#: cannot hold one without the other.
COMMITTED_PINNING_POLICY: Final[Path] = Path(__file__).with_name(
    "pinning_policy.json"
)

#: The greppable code every thread-pinning refusal carries — feature 164's own
#: subject written as a token, the discipline
#: :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`
#: (``gvisor_isolation_required``), :data:`sandbox.imports.DISALLOWED_IMPORT_CODE`
#: (``disallowed_import``) and :data:`sandbox.seed.SEED_REQUIRED_CODE`
#: (``node_seed_required``) apply to theirs.  An operator grepping a log for the
#: rejection finds it by the feature's own words.
THREAD_PINNING_CODE: Final[str] = "thread_pinning_required"

#: §12's value for every cap, spelled once: one thread, so a reduction has a
#: single, reproducible order.  A constant rather than a knob — the row names
#: one value, and ``0`` (let the library pick its conservative default) and
#: ``2`` (a fixed but wider pool) are both *choices*, admitted by the libraries
#: and refused here because neither is the pin.  Restated from feature 137's own
#: :data:`canary._threads.SINGLE_THREADED` rather than imported, for the reason
#: the module docstring gives.
SINGLE_THREADED: Final[str] = "1"

#: §5.2's call site, spelling one: the variable governing the OpenMP-parallel
#: BLAS kernels — the MKL and OpenBLAS reductions a manylinux numerics wheel
#: reaches.  Named as a constant because the artifact, the classifier and every
#: refusal have to spell it the same way.
ENV_OMP: Final[str] = "OMP_NUM_THREADS"

#: §5.2's call site, spelling two: the variable governing Intel MKL's *own*
#: threading layer, which reads it independently of OpenMP and outranks the
#: former there.  A deployment that set one has said nothing about the other,
#: which is why §12's row names both and why this law requires both.
ENV_MKL: Final[str] = "MKL_NUM_THREADS"

#: The cap variables §12's row names, each paired with the library layer that
#: reads it: ``variable → layer``, in the shape feature 137's
#: :data:`canary._threads.THREAD_ENV_CAPS` uses and for the same reason.  The
#: *table* is what a pinned environment must speak about — a policy that omits
#: a name here pins nothing about the layer it governs, and the compiler refuses
#: it by name — while the artifact carries the value and the floors.
REQUIRED_CAPS: Final[Mapping[str, str]] = {
    ENV_OMP: "the OpenMP-parallel BLAS kernels",
    ENV_MKL: "the Intel MKL threading layer",
}

#: The third variable this module knows by name: a library-level pool floor
#: which, unset, is one worker per core, and which outranks the OMP caps inside
#: the library that reads it.  Known by name for the reason feature 137 states
#: for its own — it is the knob an ambient shell tends to carry and every child
#: tends to inherit, and a law that vetted only §12's two names would certify a
#: dispatch this one is about to make threaded.  It is *carried* rather than
#: interpreted: the policy never decides what value a floor should hold, only
#: whether the environment declares one wider than the pin.
POOL_FLOOR_VARIABLE: Final[str] = "POLARS_MAX_THREADS"

#: The variable is not in the subject's environment at all: nothing was
#: declared.  The feature's own word, and a refusal for every cap §12 names —
#: an absent cap is a library's default of one worker per core, so a reduction
#: is partitioned by the machine's core count rather than by anything the
#: deployment wrote.
ABSENT: Final[str] = "absent"

#: The variable is present and is the pin: the invocation was dispatched under
#: §12's row.  The one classification an admission is built from.
PINNED: Final[str] = "pinned"

#: The variable is present and is *not* the pin — another integer, a blank, a
#: token no library reads as a count, a non-string, a ``bool``.  A refusal
#: naming the value as written, and the classification that makes *missing* mean
#: more than *unset*: a worker exported at ``OMP_NUM_THREADS=16`` is threaded
#: too, and only the absent one looks like an accident.
UNPINNED: Final[str] = "unpinned"

#: The types this law refuses *by name* because they look like a declared
#: count without being one — a tuple rather than a frozenset because it is spent
#: as the second argument to :func:`isinstance`.  ``bool`` is listed even though
#: Python's ``bool`` *is* an ``int`` subclass: ``True`` is not a thread count
#: anyone meant to write and no library reads it as one, the same exclusion
#: :func:`sandbox.seed._classify` states for a seed.  The list is not exhaustive
#: on purpose — the classifier also refuses any type that is simply not a
#: ``str`` or an ``int`` — so it names the *near misses*, the ones whose refusal
#: gets its own sentence in :func:`_shape_consequence`.
_NOT_A_COUNT: Final[tuple[type, ...]] = (bool, float, bytes)

#: ``strtol``'s shape with Python's integer grammar behind it: leading
#: ``strtol`` whitespace, an optional sign, then a non-empty run of decimal
#: digits — which under ``re``'s Unicode default is *any* script's decimal
#: digits, matching the integers :func:`int` parses.  Anchored with
#: ``\\A``/``\\Z`` so a trailing newline or space is part of the value rather
#: than silently trimmed: a library comparing the whole string sees it, and a
#: law that accepted it would be more permissive than the readers it vouches
#: for.  Restated from feature 137's own ``_CAP_RE`` — byte for byte, so a
#: spelling the worker sweep admits is a spelling this dispatch law admits, and
#: the two cannot drift into disagreeing about what a declared count is.
_CAP_RE = re.compile(r"\A[ \t\v\f\r]*[+-]?\d+\Z")


def classify_cap(value: object) -> str:
    """Classify a declared thread cap — the one place a value is read.

    :data:`PINNED` when the value names a pool of exactly one, :data:`ABSENT`
    when nothing was declared at all (``None``), and :data:`UNPINNED` for
    everything else a deployment could have written — a wider count, a blank, a
    token no library resolves, a type no library reads as a number.

    The value must be an integer that :func:`int` parses — the ``strtol`` shape
    in :data:`_CAP_RE` — and it must equal one.  An ``int`` handed over directly
    (a caller checking an explicit declaration rather than an environment) is
    classified as the same value, so the two spellings cannot disagree about a
    declaration.  ``bool`` is excluded even though Python makes it an ``int``.

    Deliberately *not* strict the way feature 138's hash-seed reading is:
    ``PYTHONHASHSEED``'s grammar lives in the interpreter and can be measured
    against it to the character, while the caps have no single owner and each
    library parses them its own way.  So there is no "the runtime would refuse
    to start under it" case here, and every unplaceable value is
    :data:`UNPINNED` rather than a fourth state — a classification this module
    could not justify would be one more thing to keep in sync.

    Unset and blank are pulled apart explicitly, which is the distinction a
    caller is most likely to want and least likely to get from a boolean:
    ``None`` is :data:`ABSENT` (no declaration was made) while ``""`` and
    ``"   "`` are :data:`UNPINNED` (a declaration *was* made and names no count,
    so the library reading it applies its own default).  The two are different
    refusals with different repairs, and collapsing them would misdescribe the
    invocation this law exists to refuse.
    """
    if value is None:
        return ABSENT
    if isinstance(value, bool):
        return UNPINNED
    if isinstance(value, int):
        return PINNED if value == 1 else UNPINNED
    if not isinstance(value, str):
        return UNPINNED
    if not _CAP_RE.match(value):
        return UNPINNED
    return PINNED if int(value) == 1 else UNPINNED


def _describes_a_count(value: object) -> bool:
    """Whether a declared value names a *number* at all, pinned or not.

    Used only to word a refusal: ``"4"`` is a deployment that chose a wider pool
    and ``"auto"`` is one whose variable no parser will resolve, and an operator
    repairs those differently.  Kept beside the classifier because the *verdict*
    has no state for it — see :func:`classify_cap` on why an unplaceable value
    is :data:`UNPINNED` rather than its own classification.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and bool(_CAP_RE.match(value))


def _is_blank(value: object) -> bool:
    """Whether a declared value was written and names nothing.

    ``""`` and ``"   "`` — present in the environment, so the variable looks
    configured, and empty to every reader.  The distinction from an *absent*
    variable is the one :func:`classify_cap` exists to keep, and this is where
    the refusal for it is worded.
    """
    return isinstance(value, str) and not value.strip()


def _shape_consequence(value: Any) -> str:
    """The extra sentence for a declared value of a type nothing reads as a count."""
    kind = type(value).__name__
    if kind == "bool":
        return (
            " ``True`` is an ``int`` in Python and is deliberately not a count: "
            "no library reads a flag as a pool size, and accepting it would make "
            "a boolean and a pin indistinguishable."
        )
    if kind == "float":
        return (
            " A float is refused even when integral (``1.0``): the value is "
            "compared against what an environment carries, and an environment "
            "carries text — a deployment that had to tolerate both spellings "
            "would be one where two manifests can pin one worker differently."
        )
    if kind == "bytes":
        return (
            " Bytes are refused because the environment §5.2's call site builds "
            "is a mapping of ``str`` to ``str``, and a value that is not text "
            "would have to be decoded by this law to be read by a library — a "
            "conversion that belongs in whatever built the environment."
        )
    return ""


def _absent_refusal(variable: str, layer: str) -> str:
    """The refusal for a cap the subject's environment never declares."""
    return (
        f"{variable} is not set: this invocation is missing the cap that "
        f"governs {layer}, so the library reading it falls back to its own "
        f"default — one worker per core — and a partition of the reduction "
        f"depends on the core count of whatever machine the box landed on. "
        f"Set {variable}={SINGLE_THREADED} in the environment the run is "
        f"dispatched with"
    )


def _blank_refusal(variable: str, layer: str) -> str:
    """The refusal for a cap that is present and names no count."""
    return (
        f"{variable} is declared blank: the variable is present, so it looks "
        f"configured, and the library reading it ignores the value and applies "
        f"its own default of one worker per core — a threaded worker wearing "
        f"the shape of a pinned one, which is the harder of the two failures to "
        f"notice. Set {variable}={SINGLE_THREADED}"
    )


def _foreign_value_refusal(variable: str, layer: str, raw: Any) -> str:
    """The refusal for a declared value no parser resolves to a thread count."""
    return (
        f"{variable}={raw!r} is not a thread count any library reads: "
        f"architecture §12's row is '``{variable}={SINGLE_THREADED}`` in every "
        f"eval worker' and §5.2 pins the variable to that one value, so a token "
        f"like this is a manifest that meant to configure {layer} and wrote "
        f"something the library will silently default on. Set "
        f"{variable}={SINGLE_THREADED}"
    )


def _wider_count_refusal(variable: str, layer: str, raw: Any) -> str:
    """The refusal for a genuine count that is not the pin."""
    return (
        f"{variable}={raw!r} is not the pin: a thread count other than one "
        f"leaves the reduction partitioned, so its sum depends on how "
        f"{layer} chose to split it, and floating-point addition is not "
        f"associative — the same bytes summed in a different number of "
        f"partitions are a different last bit, which breaks P3 and is invisible "
        f"in the score vector it produces. Set {variable}={SINGLE_THREADED}"
    )


def _cap_refusal(variable: str, layer: str, raw: Any) -> str:
    """The refusal for one cap that is not the pin — the four spellings, worded apart.

    One dispatcher rather than four call sites, so the *message* is chosen in
    the same place the classification is read: an operator repairing a missing
    variable looks in the launcher, one repairing a blank looks at whatever
    templated the environment, one repairing a wider count looks at the
    deployment's own configuration, and one repairing an unplaceable token looks
    at the manifest that wrote it.
    """
    if raw is None:
        return _absent_refusal(variable, layer)
    if _is_blank(raw):
        return _blank_refusal(variable, layer)
    if isinstance(raw, _NOT_A_COUNT) or not isinstance(raw, (str, int)):
        return _foreign_value_refusal(variable, layer, raw) + _shape_consequence(raw)
    if _describes_a_count(raw):
        return _wider_count_refusal(variable, layer, raw)
    return _foreign_value_refusal(variable, layer, raw)


def _policy_mismatch_refusal(cap: ThreadCap, raw: Any) -> str:
    """The refusal for a declaration that is the pin but not the policy's value.

    Reachable only against a *hand-assembled* policy — the compiler refuses a
    document whose caps are not pinned at :data:`SINGLE_THREADED`, so a compiled
    one can never disagree with §12 — and it exists because the gate compares
    the environment against the declaration rather than against a constant.  If
    it ever fires in a deployment, the finding is the policy: something built a
    pinning law that pins a different number, and the environment that satisfies
    §12 is refused by it.
    """
    return (
        f"{cap.name}={raw!r} is the value architecture §12's row names, and this "
        f"policy declares {cap.name}={cap.value!r} — so the environment and the "
        f"compiled pinning policy disagree about what {cap.layer} is pinned to. "
        f"A compiled policy can only carry §12's value (the compiler refuses any "
        f"other), so this is a policy assembled by hand rather than read from "
        f"the committed artifact, and the finding is the policy rather than the "
        f"environment. Recompile from {PINNING_POLICY_KIND!r}"
    )


#: The fourth outcome of :func:`_classify_declaration`: the environment declares
#: a count and names a *different number* from the one the policy pins.  Not a
#: :class:`ThreadReason` — it is an intermediate the sweep turns into one of the
#: published reasons once it knows whether anything else failed.
_MISMATCH: Final[str] = "policy-mismatch"


def _declared_count(value: Any) -> int | None:
    """The number a declared value names, or ``None`` when it names none.

    Used for the *comparison* between an environment and the policy rather than
    for the classification: whether a declaration is a count at all is
    :func:`classify_cap`'s question, and which number it names is this one's.
    Kept apart so the two cannot drift — and so a hand-assembled policy carrying
    a value that is not a count at all (which a compiled one never can) is
    answered with ``None`` rather than a ``ValueError`` raised from inside the
    gate, which raises nothing.
    """
    if classify_cap(value) != PINNED:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):  # pragma: no cover - classify_cap admitted it
        return None


def _classify_declaration(cap: ThreadCap, raw: Any) -> str:
    """Classify one policy cap against the subject's environment — four outcomes.

    The routing the refusal's *reason* hangs on, kept here rather than in the
    sweep so the sentence a caller reads is chosen in the same place the
    classification is.  :data:`PINNED` when the environment declares the count
    the policy pins; :data:`ABSENT` when nothing was declared, or a blank was —
    the feature's own word *missing* covers both, since a blank variable is one
    the library ignores and the pin is therefore absent from the run however
    configured it looks; :data:`UNPINNED` when a count is declared and is not
    the policy's; and :data:`_MISMATCH` for the one case neither names — the
    environment names the policy's number and the *policy* names another, which
    is a finding about the policy.

    **The comparison is numeric and the classification is not.**  Whether a
    declaration is a count is :func:`classify_cap`'s question — so ``" +1"`` and
    ``"01"`` are counts a library reads as one — while *which* number it names
    is decided by this comparison, so a policy pinning ``2`` refuses an
    environment declaring ``1`` even though the latter is a perfectly good
    count.  Splitting the two is what keeps the gate derived from the compiled
    declaration rather than from a constant without making it stricter than the
    readers it vouches for.
    """
    if classify_cap(raw) == ABSENT or _is_blank(raw):
        return ABSENT
    declared = _declared_count(raw)
    if declared is None:
        return UNPINNED
    pinned = _declared_count(cap.value)
    if pinned is None:  # pragma: no cover - a compiled policy cannot reach this
        return _MISMATCH
    return PINNED if declared == pinned else _MISMATCH


def _floor_refusal(variable: str, raw: Any) -> str:
    """The refusal for a declared pool floor wider than the pin.

    The case §12's row does not reach on its own: the library that sizes this
    pool resolves it without consulting the two caps, so the caps can be pinned
    to the letter and the reduction still partitioned — and the floor is
    inherited by every child the worker launches.  Absent is *not* refused
    (:func:`check_thread_pinning` states why); declared and wider than the pin
    is.
    """
    return (
        f"{variable}={raw!r} is declared and is not the pin: this is a "
        f"library-level pool floor, which the library that reads it resolves "
        f"without consulting {', '.join(sorted(REQUIRED_CAPS))}, so a worker "
        f"with both caps pinned and a floor like this is threaded anyway. "
        f"Remove the declaration, or set {variable}={SINGLE_THREADED}"
    )


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise ThreadPinningDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: {value!r}. A "
            f"pinning policy is a structured document, and a compiler that "
            f"guessed at the meaning of a stray list or string would be writing "
            f"policy rather than reading it — refused, fail closed (feature 164)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise ThreadPinningDocumentError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). The variables a pinning policy speaks "
            f"about are named, not inferred: a cap or a floor that is absent, "
            f"blank or not a string is one this policy cannot hold an invocation "
            f"to, and 'unnamed' is not 'pinned' (feature 164, refused fail "
            f"closed)."
        )
    return value


@dataclass(frozen=True)
class ThreadCap:
    """One cap a pinning policy requires: the variable, its value and its layer.

    What :func:`compile_thread_pinning_policy` hands out per cap, and the object
    the gate consults, so an invocation's admission is *derived* from the
    compiled declaration rather than hardcoded to "yes, pinned" — the same
    "computed, never assumed" stance
    :meth:`sandbox.isolation.IsolationPolicy.isolation_of` takes for a run's
    isolation.

    Under every compiled policy :attr:`value` is :data:`SINGLE_THREADED`, because
    the compiler refuses anything else.  The field exists anyway — rather than
    the type being a bare name — for the reason
    :class:`sandbox.isolation.ComponentIsolation` carries its mechanism: a caller
    asking *what is this pinned to?* reads a value rather than inferring it, and
    the gate compares the environment against the declaration rather than
    against a constant, so a hand-assembled policy carrying another value would
    be reported in the refusal (itself the audit finding).

    :attr:`layer` is the library the variable governs — *"the OpenMP-parallel
    BLAS kernels"*, *"the Intel MKL threading layer"* — carried so a refusal can
    say *which* reduction was left threaded.  An operator can act on that word;
    on a variable name alone they cannot.
    """

    name: str
    value: str
    layer: str

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ThreadCap(name={self.name!r}, value={self.value!r}, "
            f"layer={self.layer!r})"
        )


class ThreadPinningPolicy:
    """A compiled pinning policy: every cap it names is pinned at one.

    What :func:`compile_thread_pinning_policy` returns is not the document — it
    is the document *plus* the guarantee that it speaks about every variable §12
    names, and pins each one at :data:`SINGLE_THREADED`.  Holders (the gate, an
    operator script, a CI check that recompiles the committed artifact) cite that
    guarantee rather than re-derive it, which is why a refusal can say "the
    compiled pin is not what this environment declares" and mean it.

    Ordered as the document ordered it, so a nightly report can compare two
    deployments' pinning records field by field — the property feature 137's
    :class:`canary._threads.ThreadCaps` states for its own record.
    """

    __slots__ = ("_caps", "_floors", "kind")

    def __init__(
        self,
        *,
        kind: str,
        caps: Sequence[ThreadCap],
        floors: Sequence[str] = (),
    ) -> None:
        self.kind = kind
        self._caps = tuple(caps)
        self._floors = tuple(floors)

    def caps(self) -> tuple[ThreadCap, ...]:
        """Every cap the policy requires, in document order."""
        return self._caps

    def required_names(self) -> tuple[str, ...]:
        """The names of the caps the policy requires, in document order."""
        return tuple(cap.name for cap in self._caps)

    def cap(self, name: str) -> ThreadCap | None:
        """The cap ``name`` is declared as, or ``None``.

        The lookup decides nothing: a name the policy does not carry is answered
        by the *gate* by being absent from the table it sweeps, not by this
        method returning a default — and the compiler has already refused a
        policy that omitted a name :data:`REQUIRED_CAPS` requires, so a ``None``
        here means a caller asked about a variable outside §12's row.
        """
        for cap in self._caps:
            if cap.name == name:
                return cap
        return None

    def value(self, name: str) -> str | None:
        """The value ``name`` is pinned to, or ``None`` for an unlisted name."""
        cap = self.cap(name)
        return None if cap is None else cap.value

    def layer(self, name: str) -> str | None:
        """The library layer ``name`` governs, or ``None`` for an unlisted name."""
        cap = self.cap(name)
        return None if cap is None else cap.layer

    def pool_floors(self) -> tuple[str, ...]:
        """The library-level floor variables this policy watches, in order."""
        return self._floors

    def pins(self) -> dict[str, str]:
        """The policy's whole declaration as an environment-shaped mapping.

        ``variable → value`` for every cap, in document order — the mapping a
        launcher can hand a run *instead of* the environment it built, and the
        one a refusal is compared against.  A fresh dict per call, so a caller
        cannot mutate the policy's own declaration by writing to the value it
        read — the same copy-then-hand discipline
        :meth:`sandbox.seed.SeedDecision.seed_env` takes.
        """
        return {cap.name: cap.value for cap in self._caps}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ThreadPinningPolicy(kind={self.kind!r}, "
            f"caps={list(self.required_names())!r}, floors={list(self._floors)!r})"
        )


def compile_thread_pinning_policy(document: Any) -> ThreadPinningPolicy:
    """Compile a pinning policy, refusing one that does not pin §12's row.

    The seam the whole feature turns on.  The document is read whole — marker,
    caps, floors — and held to the law before a :class:`ThreadPinningPolicy` is
    handed out: it must speak about *every* variable :data:`REQUIRED_CAPS` names
    (a policy silent about ``MKL_NUM_THREADS`` pins nothing about the MKL
    threading layer, and silence is exactly how a threaded deployment looks
    configured), and every cap it does speak about must carry
    :data:`SINGLE_THREADED` as its value.  A refusal propagates as an exception,
    so a caller cannot continue with a half-trusted policy: the document that
    would have certified a threaded dispatch is never applied, which is the
    compile-time half of "System rejects" (feature 164).

    The value is checked through the *same* classifier the gate reads an
    environment with (:func:`classify_cap`), so the document and the run cannot
    disagree about what a declared count is — one classifier, two seams, the
    member's one-provenance rule.  A cap that is not a string or an integer
    therefore reaches the same refusal an environment's would.
    """
    doc = _require_mapping(document, "sandbox thread-pinning policy document")
    marker = _require_str(
        doc.get("policy"), "sandbox thread-pinning policy 'policy'"
    )
    if marker != PINNING_POLICY_KIND:
        raise ThreadPinningDocumentError(
            f"a sandbox thread-pinning policy must declare itself "
            f"{PINNING_POLICY_KIND!r}, got {marker!r}. A document that does not "
            f"say what it is cannot be trusted to say how an invocation's "
            f"reductions are summed, and a stray JSON file carrying a 'caps' key "
            f"is not this policy — refused, fail closed (feature 164)."
        )

    raw_caps = doc.get("caps")
    if not isinstance(raw_caps, Sequence) or isinstance(raw_caps, (str, bytes)):
        raise ThreadPinningDocumentError(
            f"a sandbox thread-pinning policy's 'caps' must be a list of cap "
            f"blocks, got {raw_caps!r}. The cap list is the law's whole subject "
            f"— the variables §12's row pins in every eval worker — and a "
            f"document that cannot enumerate them cannot be compiled "
            f"(feature 164)."
        )

    caps: dict[str, ThreadCap] = {}
    for index, raw_cap in enumerate(raw_caps):
        block = _require_mapping(raw_cap, f"cap #{index + 1}")
        name = _require_str(block.get("name"), f"cap #{index + 1} 'name'")
        what = f"cap {name!r}"
        if name in caps:
            raise ThreadPinningDocumentError(
                f"{what} appears twice in the policy. Two blocks with one name "
                f"is not two caps, it is one variable described twice — and the "
                f"applied policy would be whichever block came last, which is "
                f"drift with extra steps. Refused (feature 164)."
            )
        layer = _require_str(block.get("layer"), f"{what} 'layer'")

        value = block.get("value")
        if value is None:
            raise ThreadPinningDocumentError(
                f"{what} 'value' is absent. §12's row is '"
                f"``{name}={SINGLE_THREADED}``', and a compiler that read an "
                f"absent value as the pin would be turning silence into the "
                f"strongest promise the document makes — 'unspecified' and "
                f"'pinned to {SINGLE_THREADED} by law' are different promises, "
                f"and only the second is feature 164's (refused, fail closed)."
            )
        if classify_cap(value) != PINNED:
            raise ThreadPinningRequired(
                f"{THREAD_PINNING_CODE}: {what} is declared at {value!r} in the "
                f"committed pinning policy, which is not the pin. "
                f"{_cap_refusal(name, layer, value)}. The whole document is "
                f"refused, not the cap skipped: a policy applied with one "
                f"declaration silently dropped is one whose file and whose "
                f"dispatched runs disagree, and that disagreement is where the "
                f"next thread count comes from (feature 164)."
            )

        caps[name] = ThreadCap(name=name, value=SINGLE_THREADED, layer=layer)

    missing = tuple(name for name in REQUIRED_CAPS if name not in caps)
    if missing:
        raise ThreadPinningDocumentError(
            f"a sandbox thread-pinning policy does not speak about "
            f"{', '.join(repr(name) for name in missing)} — "
            f"{'; '.join(REQUIRED_CAPS[name] for name in missing)}. §12's row "
            f"joins the two variables with *and* because neither layer is bound "
            f"by the other's variable, so a policy that pins one has said "
            f"nothing about the other, and a compiler that treated the omission "
            f"as 'nothing to check' would certify exactly the threaded "
            f"deployment this feature exists to refuse. Refused, fail closed "
            f"(feature 164)."
        )

    raw_floors = doc.get("pool_floors", ())
    if not isinstance(raw_floors, Sequence) or isinstance(raw_floors, (str, bytes)):
        raise ThreadPinningDocumentError(
            f"a sandbox thread-pinning policy's 'pool_floors' must be a list of "
            f"variable names, got {raw_floors!r}. The floors are the "
            f"library-level knobs the policy refuses to see declared wider than "
            f"the pin, and a document that cannot enumerate them cannot be read "
            f"as one (feature 164)."
        )
    floors: list[str] = []
    for index, raw_floor in enumerate(raw_floors):
        floor = _require_str(raw_floor, f"pool floor #{index + 1}")
        if floor in caps:
            raise ThreadPinningDocumentError(
                f"pool floor {floor!r} is also declared as a cap. A variable is "
                f"one knob with one meaning: a cap is a declaration the "
                f"environment must carry at the pin, a floor is one the policy "
                f"refuses to see declared wider — and a document that made one "
                f"variable both would leave a reader unable to say which refusal "
                f"an environment earns. Refused (feature 164)."
            )
        if floor in floors:
            raise ThreadPinningDocumentError(
                f"pool floor {floor!r} appears twice in the policy. One name is "
                f"one knob, and a list that names it twice is a file whose "
                f"intent is not readable from it. Refused (feature 164)."
            )
        floors.append(floor)

    return ThreadPinningPolicy(kind=PINNING_POLICY_KIND, caps=tuple(caps.values()), floors=floors)


def load_thread_pinning_policy(
    path: Path = COMMITTED_PINNING_POLICY,
) -> ThreadPinningPolicy:
    """Read and compile a policy from disk, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly as
    a drift compiled in memory (feature 164).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise ThreadPinningDocumentError(
            f"could not read the sandbox thread-pinning policy at {path}: {exc}. "
            f"A pinning policy that cannot be read is not a policy that refuses "
            f"nothing gracefully — it is one whose deployment has no law at all, "
            f"and a caller that carried on would be dispatching agent-authored "
            f"code into a threaded box while believing it was configured from "
            f"this file (feature 164)."
        ) from exc
    except ValueError as exc:
        raise ThreadPinningDocumentError(
            f"the sandbox thread-pinning policy at {path} is not valid JSON: "
            f"{exc}. Refused rather than read partially: a policy compiled from "
            f"a partially-parsed document is one whose file and whose dispatched "
            f"runs disagree (feature 164)."
        ) from exc
    return compile_thread_pinning_policy(document)


def committed_thread_pinning_policy() -> ThreadPinningPolicy:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 164's own tests hold to the pins, so "the deployment dispatches
    single-threaded" is a checked fact about a file in the repository rather
    than a claim in a runbook.
    """
    return load_thread_pinning_policy(COMMITTED_PINNING_POLICY)


class ThreadReason(enum.StrEnum):
    """Why an invocation was admitted or refused — the audit vocabulary.

    One enumeration carries the acceptance and the refusals, for the reason
    :class:`sandbox.isolation.RunReason` and :class:`sandbox.seed.SeedReason`
    do: a decision's reason is one fact with two polarities and the audit line
    should read the same either way — ``by-pinning`` names the pin the
    invocation was admitted on, and the refusals name what the environment
    declared instead.
    """

    #: Admitted: every cap the policy requires is declared at the pin, and no
    #: watched floor is declared wider than it.  Reading the string is proof the
    #: compiled declaration was consulted and found satisfied — a
    #: hand-assembled policy carrying another value can never produce it.
    BY_PINNING = "by-pinning"

    #: Refused: a cap §12 names is *missing* — absent from the environment, or
    #: present and blank.  The feature's own word, and its own reason: the
    #: repair is in the launcher that built the environment, and the layer the
    #: variable governs is what the refusal names so the operator knows which
    #: reduction was left to the machine's core count.
    WITHOUT_PINNING = "without-thread-pinning"

    #: Refused: a cap is declared, and at something other than the pin — a wider
    #: count, or a token no library resolves to a count.  Split from
    #: :attr:`WITHOUT_PINNING` because the repair is different: an absent
    #: variable is looked for in the launcher, a mis-declared one in whatever
    #: manifest wrote it.
    THREADED_CAP = "threaded-cap"

    #: Refused: every cap is pinned and a *floor* the policy watches is declared
    #: wider than the pin.  Its own reason because it is the one failure the two
    #: §12 names do not reach — the deployment looks compliant to a sweep of the
    #: caps alone, and the library that reads the floor partitions the reduction
    #: anyway.
    THREADED_POOL = "threaded-pool-floor"

    #: Refused: the environment satisfies §12's row and the *policy* declares
    #: another value.  Its own reason because the finding is the policy rather
    #: than the run: a compiled policy always carries §12's value (the compiler
    #: refuses any other), so a mismatch here means something assembled a pinning
    #: law by hand — and an operator sent looking at the launcher would be
    #: reading the wrong file.
    POLICY_MISMATCH = "policy-pin-mismatch"

    #: Refused: the subject is not an environment this law can read — not a
    #: mapping and not an object carrying one.  A refusal rather than a raise,
    #: like the other gates', because the caller that has been handed the wrong
    #: object still needs to be told *which* one it was.
    UNREADABLE_SUBJECT = "unreadable-subject"


class ThreadDecision:
    """The gate's whole answer: admitted or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed* from
    the classified environment rather than set by a constant — the same
    "computed, never assumed" stance :class:`sandbox.isolation.RunDecision`
    takes for a run.  ``detail`` is the operator-facing sentence and names every
    offending variable rather than only the first, because an environment with a
    missing OMP cap *and* a threaded MKL layer has two repairs and a refusal that
    reported one would send the operator away satisfied.

    ``missing`` and ``threaded`` are the offending variable names, in policy
    order: the reason is the headline, and these fields are the whole finding —
    a caller that wants to *act* on the refusal (export the missing names, file
    the declared ones) reads them rather than parsing the sentence.  Both are
    empty on an admission, so a caller reading them after checking ``admitted``
    has the answer rather than a sentinel.

    ``environment`` is the environment to dispatch with, and it exists only on
    an admission: the pins written in the policy's own spelling onto a copy of
    the subject.  It is a *normalization* and not a repair — an admitted
    invocation already declares every cap at the pin, so no value is changed —
    but the spelling is the policy's, so a declaration that classified as the pin
    because of surrounding whitespace does not reach the box as ``" 1 "``.
    """

    __slots__ = ("admitted", "detail", "environment", "missing", "reason", "threaded")

    def __init__(
        self,
        *,
        admitted: bool,
        reason: ThreadReason,
        detail: str,
        missing: Sequence[str] = (),
        threaded: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.admitted = admitted
        self.reason = reason
        self.detail = detail
        self.missing = tuple(missing)
        self.threaded = tuple(threaded)
        self.environment = environment

    def require(self) -> dict[str, str]:
        """Return the environment to dispatch with, or raise the refusal.

        The bridge between the gate's returned answer and the exception a
        launcher wants on its last line before spawning: a decision that admitted
        the invocation returns the environment — pins in the policy's spelling,
        the subject's other variables carried — so a caller writes one line::

            env = threads.require(invocation)
            sandbox.run(code, window, seed=seed, env=env)

        A refusal raises :class:`~sandbox.errors.ThreadPinningRequired` carrying
        the gate's own operator-facing sentence — the same error type the
        compiler raises, so the two halves of feature 164 carry one refusal and a
        caller never has to catch two.  A copy is returned, never the decision's
        own mapping: two callers dispatching from one decision must not fight
        over the environment they pass, the discipline
        :meth:`sandbox.seed.SeedDecision.seed_env` applies to the seed's
        transport.
        """
        if not self.admitted:
            raise ThreadPinningRequired(self.detail)
        return dict(self.environment or {})

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ThreadDecision(admitted={self.admitted}, reason={self.reason!r}, "
            f"missing={self.missing!r}, threaded={self.threaded!r})"
        )


def _subject_environment(subject: object) -> Mapping[str, str] | None:
    """The environment ``subject`` carries, or ``None``.

    Three shapes, each one a caller this law has: a plain mapping (an operator
    or a launcher holding the environment it built), an object carrying one
    under ``.env`` (feature 165's :class:`sandbox.seed.SandboxInvocation`, so
    the same description of a run can be handed to both laws), and the version
    of the first two that is not an environment at all — ``None``, and the gate
    refuses it by name rather than raising, because *"what you handed me is not
    an environment"* is a fact the caller can act on.

    ``SandboxInvocation.env`` is always a mapping (its constructor copies into
    one), but the attribute is read defensively: a caller's own record type may
    carry ``env`` as ``None``, and that is an absent environment rather than a
    crash inside the gate.
    """
    if isinstance(subject, Mapping):
        return subject
    env = getattr(subject, "env", None)
    if isinstance(env, Mapping):
        return env
    return None


def check_thread_pinning(
    subject: object, policy: ThreadPinningPolicy
) -> ThreadDecision:
    """Answer one invocation: admitted only when its environment carries the pins.

    The gate, and the one place the law is actually applied — every other verb
    in this module (:meth:`SandboxThreads.require`, :meth:`ThreadDecision.require`)
    reaches this function rather than re-checking.  Nothing is raised here, for
    the reason features 157's, 167's and 165's gates raise nothing: the pipeline
    offers thousands of invocations and *"this one is unpinned"* must reach an
    operator as a fact about a run rather than as a crashed evaluator, while a
    caller that must not spawn turns the answer into an exception with
    :meth:`ThreadDecision.require`.

    The sweep is over the *policy's* caps, in policy order, and the comparison is
    against the policy's own declared value rather than against
    :data:`SINGLE_THREADED` — so the admission is the compiled declaration
    arriving at its answer, and a hand-assembled policy carrying another value
    would refuse an environment that matched it (itself the audit finding).
    Every cap is classified before anything is decided, so a refusal names all
    of them.

    A watched floor that is *absent* is not a refusal, and that asymmetry is
    deliberate: nothing here can say what value a deployment's own library should
    default to, and a policy that made the floor mandatory would be this member
    inventing a knob for a library it does not own.  A floor that is *declared*
    and not the pin is refused, because it outranks the caps inside the library
    that reads it — the reason :data:`POOL_FLOOR_VARIABLE` is known by name at
    all.
    """
    environment = _subject_environment(subject)
    if environment is None:
        return ThreadDecision(
            admitted=False,
            reason=ThreadReason.UNREADABLE_SUBJECT,
            detail=(
                f"{THREAD_PINNING_CODE}: a sandboxed invocation was offered to "
                f"the thread-pinning gate carrying no environment this law can "
                f"read (got {type(subject).__name__}: {subject!r}). §5.2's call "
                f"site dispatches every run with an ``env=`` clause, and the "
                f"law's whole subject is that environment; an invocation "
                f"described as something else cannot be asked whether it is "
                f"pinned, and 'unreadable' is not 'pinned'. The run is refused "
                f"before anything is spawned (feature 164)."
            ),
        )

    missing: list[str] = []
    threaded: list[str] = []
    offenders: list[str] = []
    for cap in policy.caps():
        raw = environment.get(cap.name, None)
        outcome = _classify_declaration(cap, raw)
        if outcome == PINNED:
            continue
        if outcome == _MISMATCH:
            # The environment satisfies §12 and the policy does not: a finding
            # about the policy, worded as one — the environment is not the thing
            # to repair, so this is not a `missing` or a `threaded` declaration.
            offenders.append(_policy_mismatch_refusal(cap, raw))
            continue
        if outcome == ABSENT:
            # The feature's own word: nothing declared, or declared blank — a
            # blank variable is one the library ignores, so the pin is absent
            # from the run however configured it looks.
            missing.append(cap.name)
            offenders.append(_cap_refusal(cap.name, cap.layer, raw))
            continue
        threaded.append(cap.name)
        offenders.append(_cap_refusal(cap.name, cap.layer, raw))

    for floor in policy.pool_floors():
        raw = environment.get(floor, None)
        if raw is None or classify_cap(raw) == PINNED:
            continue
        threaded.append(floor)
        offenders.append(_floor_refusal(floor, raw))

    if not offenders:
        pins = policy.pins()
        return ThreadDecision(
            admitted=True,
            reason=ThreadReason.BY_PINNING,
            environment={**environment, **pins},
            detail=(
                f"invocation admitted: its environment declares "
                f"{', '.join(f'{name}={value}' for name, value in pins.items())}, "
                f"which is §12's determinism row — 'Single-threaded numerics | "
                f"``{ENV_OMP}={SINGLE_THREADED}``, ``{ENV_MKL}="
                f"{SINGLE_THREADED}`` in every eval worker' — and no watched "
                f"pool floor wider than the pin. §5.2: 'Thread-count pinning is "
                f"not a performance setting. Multi-threaded BLAS reductions are "
                f"non-deterministic in float, which breaks P3.' (feature 164)"
            ),
        )

    if not missing and not threaded:
        # Every cap the environment declares is §12's, and the policy pins
        # another value — the hand-assembled policy case.
        mismatched = tuple(
            cap.name
            for cap in policy.caps()
            if _classify_declaration(cap, environment.get(cap.name, None))
            == _MISMATCH
        )
        return ThreadDecision(
            admitted=False,
            reason=ThreadReason.POLICY_MISMATCH,
            detail=(
                f"{THREAD_PINNING_CODE}: every cap this invocation declares "
                f"matches architecture §12's row, and the pinning policy it was "
                f"checked against declares another value "
                f"({', '.join(mismatched)}). A policy compiled from the "
                f"committed artifact cannot do this — the compiler refuses any "
                f"value but §12's — so the finding is the *policy*, not the run: "
                f"something assembled a pinning law by hand. Recompile from "
                f"{PINNING_POLICY_KIND!r}; the refusal is raised rather than the "
                f"environment repaired, because a run dispatched under a "
                f"non-§12 value is the failure this feature exists to prevent "
                f"(feature 164)."
            ),
        )

    if missing:
        reason = ThreadReason.WITHOUT_PINNING
        headline = (
            f"this sandboxed invocation is missing the thread-pinning "
            f"environment: {', '.join(missing)} "
            f"{'are' if len(missing) > 1 else 'is'} not declared at the pin "
            f"(or not declared at all)"
        )
    elif len(threaded) == 1 and threaded[0] in policy.pool_floors():
        reason = ThreadReason.THREADED_POOL
        headline = (
            f"every cap §12 names is pinned, and the library-level pool floor "
            f"{threaded[0]} is declared wider than the pin"
        )
    else:
        reason = ThreadReason.THREADED_CAP
        headline = (
            f"this sandboxed invocation declares its thread caps at something "
            f"other than the pin: {', '.join(threaded)}"
        )

    return ThreadDecision(
        admitted=False,
        reason=reason,
        missing=missing,
        threaded=threaded,
        detail=(
            f"{THREAD_PINNING_CODE}: {headline}. {len(offenders)} declaration(s) "
            f"refused:\n  " + "\n  ".join(offenders) + (
                f"\n§12's row is 'Single-threaded numerics | "
                f"``{ENV_OMP}={SINGLE_THREADED}``, ``{ENV_MKL}="
                f"{SINGLE_THREADED}`` in every eval worker', and §5.2 makes it a "
                f"control rather than a tuning note: 'Thread-count pinning is "
                f"not a performance setting. Multi-threaded BLAS reductions are "
                f"non-deterministic in float, which breaks P3.' A threaded "
                f"reduction produces neither an exception nor an obviously wrong "
                f"number — it produces a different last bit — so the run is "
                f"refused before it is dispatched rather than reported after "
                f"(feature 164)."
            )
        ),
    )


class SandboxThreads:
    """Feature 164's law, as the value a composed application carries.

    A stateless facade over this module and the committed pinning policy it
    compiled — the same shape :class:`sandbox.SandboxIsolation` gives feature
    157, :class:`sandbox.SandboxImports` 167, :class:`sandbox.SandboxTransfer`
    166 and :class:`sandbox.SandboxSeed` 165 — so a caller holding the composed
    component can ask the feature's question, *will this invocation reach the box
    with §12's caps pinned?*, without importing the member's submodules by name
    or re-reading the artifact.

    **``require`` is the verb the launcher wants, and it returns the
    environment.**  :meth:`check` returns the gate's decision as a value, for a
    caller that wants to branch or to audit a batch; :meth:`require` turns a
    refusal into :class:`~sandbox.errors.ThreadPinningRequired` — while
    *returning* the environment to dispatch with when it does not, which is what
    lets a launcher write one line::

        env = threads.require(invocation)
        sandbox.run(code, window, seed=seed, env=env)

    A verb that returned ``None`` on success would make the caller read the
    environment off the invocation a second time, and the two readings are
    exactly the pair that can drift — the argument
    :class:`sandbox.SandboxSeed` makes for returning its integer.

    **It carries no environment of its own.**  A component shared across runs
    that held one would be a component letting two invocations share a
    description, the property :class:`sandbox.SandboxTransfer` states for its
    channel and :class:`sandbox.SandboxSeed` for its seed — and here it would be
    worse than either, because the concrete failure is a run dispatched under
    another run's environment.  What it carries is the compiled policy: the
    variables it requires, the value they are pinned to, and the floors it
    watches.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the classifier or the sweep here
    would be a second thing to keep in sync, and the member's one-provenance
    rule exists so that cannot happen.
    """

    __slots__ = ("_policy",)

    def __init__(self, policy: ThreadPinningPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> ThreadPinningPolicy:
        """The compiled pinning policy this component carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator script asking which variables the deployment pins — reads the
        policy rather than re-deriving it.  Reading it does not widen anything:
        the policy holds no capability, which is the point of the component
        being a facade rather than a launcher.
        """
        return self._policy

    def required(self) -> tuple[str, ...]:
        """The cap variables this deployment requires, in policy order."""
        return self._policy.required_names()

    def value(self, name: str) -> str | None:
        """The value ``name`` is pinned to, or ``None`` for an unlisted name."""
        return self._policy.value(name)

    def pins(self) -> dict[str, str]:
        """The policy's whole declaration as an environment-shaped mapping."""
        return self._policy.pins()

    def pool_floors(self) -> tuple[str, ...]:
        """The library-level floor variables the policy watches, in order."""
        return self._policy.pool_floors()

    def check(self, subject: object) -> ThreadDecision:
        """Answer whether ``subject``'s environment carries the pins.

        ``subject`` is an environment mapping, or an object carrying one under
        ``.env`` — which is how the *same* invocation feature 165 describes can
        be handed to both laws.  The process's own environment is deliberately
        not a default: a caller that wants to ask about it passes it
        (``check(os.environ)``), so this law stays a pure function of what it was
        handed and a test never depends on the shell that started pytest.
        """
        return check_thread_pinning(subject, self._policy)

    def admits(self, subject: object) -> bool:
        """Whether ``subject``'s environment carries the pins — the one boolean.

        The convenience for the caller that does not want the decision: the same
        computation, read at its headline.  A refusal's *reason* is what
        :meth:`check` is for.
        """
        return self.check(subject).admitted

    def require(self, subject: object) -> dict[str, str]:
        """Return the environment to dispatch with, or raise the refusal.

        The launcher's verb: one call, the invocation (or the environment), and
        either a fresh mapping carrying the pins in the policy's spelling — the
        subject's other variables included — or
        :class:`~sandbox.errors.ThreadPinningRequired` carrying the gate's own
        operator-facing sentence.  Put on the last line before the spawn, it
        makes *"no sandbox invocation is missing the thread-pinning
        environment"* enforced there rather than remembered.
        """
        return self.check(subject).require()


def sandbox_threads() -> SandboxThreads:
    """The thread-pinning law, compiled fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs an environment to
    answer for.  This is the module-level convenience the member's own tests and
    any operator script reach, and it is the same call
    :func:`sandbox.build_sandbox_threads` makes minus the composition.
    """
    return SandboxThreads(committed_thread_pinning_policy())
