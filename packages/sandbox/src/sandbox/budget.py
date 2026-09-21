"""Feature 162's law: a run past its cgroup limits is refused.

app_spec.xml, "Untrusted Code Sandbox", feature 162: *System rejects a
sandboxed run exceeding the cgroup limits for cpu, memory of 2048 MB or a
process count of 32.*  docs/nullius-tech-architecture.md §5.2 gives the feature
its call site — the one place a run is described — and the numbers *inside* it::

    result = sandbox.run(
        entrypoint="signal",
        code=node.code,
        payload=window.to_arrow(),        # IPC, zero-copy
        limits=Limits(wall_s=30, cpu_s=30, mem_mb=2048,
                      network=False, filesystem=False, pids=32),
        seed=node.seed,
        env={"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
    )

§5.2's control table gives the three their own row — ``Resources | cgroup v2:
cpu.max, memory.max, pids.max`` — and §3's zone map states the posture that row
serves: *"Z1 — Mutated by the loop | Signal code, exploration policy code |
LLM agents | Sandboxed: no network, no FS, seccomp, **cgroup limits**"*.  The
sentence decomposes into four claims, each owned here as a seam rather than a
comment:

* **a sandboxed run** — the subject, and the reason the law reads what it
  reads.  Not a service, a store or a policy: *one dispatch* of one signal,
  the same unit :class:`sandbox.isolation.SandboxRun` models for feature 157,
  :class:`sandbox.seed.SandboxInvocation` for feature 165,
  :class:`sandbox.threads.SandboxInvocation`'s environment for feature 164 and
  :class:`sandbox.timeout.TimeoutRun` for feature 163.  The three things this
  law needs of that unit are the *measured* cpu time, memory and process count
  — which is why :class:`BudgetRun` models exactly those and deliberately not
  the whole call: the code and the payload belong to features 167's and 166's,
  the seed to 165's, the env to 164's and the wall clock to 163's, and a
  boundary that also modelled them would be a second, divergent copy of
  ``evaluator._sandbox``'s call shape — the mistake
  :class:`sandbox.isolation.SandboxRun` names for itself.

* **the cgroup limits for cpu, memory of 2048 MB or a process count of 32** —
  the term, and the half of §5.2's ``Limits(...)`` this feature owns.  The
  three numbers are *written down*: :data:`COMMITTED_BUDGET_POLICY` ships
  beside this module and the compiler refuses any other, so "this deployment
  confines a run to one core for thirty seconds of cpu, two gigabytes of
  memory and thirty-two processes" is a fact about a file in the repository
  rather than a line in a runbook.  The other three fields of the same call —
  ``wall_s``, ``network``, ``filesystem`` — are deliberately *not* here:
  ``wall_s`` is feature 163's, owned by
  :data:`sandbox.timeout.COMMITTED_TIMEOUT_POLICY` and stated as such in that
  file's own comment, and the two denials are structural (§5.2: "a namespace
  with no interfaces", "no mounts") rather than budgets.

* **rejects** — the consequent, and the member's sharpest shape.  This is the
  one control in the category whose subject is a *measurement of the machine*:
  a run is not refused because of how it was configured — features 157's,
  164's, 165's and 167's subject, each answered before anything executes — but
  because of what it *did* to the core, the memory and the process table while
  it ran.  So :func:`check_cgroup_budget` **answers** with a
  :class:`BudgetDecision` (the pipeline dispatches thousands of unattended
  candidates and a configuration mistake must not crash an evaluator) and
  :meth:`SandboxBudget.require` is where a launcher takes the refusal, as a
  :class:`~sandbox.errors.CgroupBudgetExceeded` whose message begins with
  :data:`CGROUP_BUDGET_CODE` (``cgroup_budget_exceeded``).

* **2048 MB** — the memory number that replaces the runner's own default, and
  the one judgement in this feature worth stating in full.  §5.2's call site
  passes ``mem_mb=2048``; ``packages/evaluator``'s
  :data:`evaluator._sandbox.DEFAULT_MEM_MB` is **4096**, and says why in its
  own comment: *"4 GiB (not the spec's nominal 2 GiB): jemalloc's
  address-space reservation for the interpreter and polars exceeds 2 GiB even
  at ~70 MB resident, so a 2 GiB ``RLIMIT_AS`` is flaky — the child dies
  before it can run the signal."*  Both are true and they are different
  facts.  This deployment's *cgroup* limit is §5.2's 2048, reviewed here in
  the committed artifact; the host runner's portable ``RLIMIT_AS`` fallback is
  4096, and remains what it is for reasons about ``setrlimit`` rather than
  about this law.  So the artifact records both numbers, the compiler refuses
  either drifting, and no edit here reaches into the evaluator to reconcile
  them — the same division :mod:`sandbox.timeout` draws between its budget and
  the watchdog that enforces it.

**Exceeded is read strictly, as the feature's own word.**  A run that used
*exactly* its cpu budget, or held exactly 2048 MB, or ran exactly 32 processes,
did not *exceed* it — and the comparison is therefore ``>`` rather than
``>=`` on all three, the reading :func:`sandbox.timeout.exceeded_budget` gives
feature 163's own boundary.  Nothing here *measures* anything: the cgroup is
the kernel's, the counters are the runtime's, and the law reads the peak
values a watchdog reported — the same division feature 157 states between its
isolation policy and the ``runsc`` runtime that enforces it.

**The limits are a plane, and the cgroup is per cgroup — so a deployment's
process count is bounded and one run's is 32.**  §5.2's ``pids=32`` is the
``pids.max`` of the *run's* cgroup, which is what makes an agent-authored
signal's exponential forking a contained event; §12's own row bounds the
executor at eight for the opposite reason (a node's probes are *its* work and
must not collide with another node's).  Both numbers are thirty-two and eight
in the same section of the same document, and a reader who conflated them
would file a bug against a correct deployment.

**The breach is a value, and the refusal is what a launcher does with it.**
The member's other laws split their answers this way — features 157's, 167's
and 165's gates return decisions and their launcher verbs raise — and this one
keeps both halves because its subject is a *failure* like feature 163's: the
box ran, overran a cgroup, and was killed by the kernel.  So the gate returns,
the kill is a value §8's ledger (``oom``, ``error``) and feature 168's
vocabulary can record, and :meth:`BudgetDecision.require` is the one line that
turns "this run exceeded its limits" into an exception on the far side of a
spawn, where the pipeline has no result object to inspect.  A host-side caller
that persists rather than raises reads :attr:`BudgetDecision.breach` and calls
:meth:`BudgetBreach.row`.

**Honest limits.**  This module is the *law about the limits*, not the limits
themselves: it never writes a ``cgroup.procs``, never reads a counter and
cannot see a run that outran a limit without a measurement being reported to
it.  The enforcement is the deployment's — ``runsc`` on a cgroup v2 hierarchy,
with ``cpu.max``, ``memory.max`` and ``pids.max`` — and the portable
host-side fallback ``evaluator._sandbox`` implements (``RLIMIT_CPU`` for the
cpu budget, ``RLIMIT_AS`` for address space, and a ``pids`` field it
deliberately does *not* apply because ``RLIMIT_NPROC`` is scoped to a real UID
rather than to a process).  What holds is that the committed limits cannot
drift without the compile failing, that a breach cannot be reported without
naming the field, the number and the measurement that earned it, and that
*what this deployment confines a run to* is a value the policy carries and a
caller can read (:meth:`CgroupPolicy.value`).

Stdlib-only, like the rest of the member: ``json`` for the artifact, and no
process, cgroup, clock or container runtime anywhere.  The module is the law
and the caller supplies the measurement it read.
"""

from __future__ import annotations

import enum
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .errors import (
    CgroupBudgetDocumentError,
    CgroupBudgetExceeded,
)

__all__ = [
    "BUDGET_COMPONENT_NAME",
    "BUDGET_POLICY_KIND",
    "CGROUP_BUDGET_CODE",
    "CGROUP_LIMITS_REQUIRED_CODE",
    "COMMITTED_BUDGET_POLICY",
    "DEFAULT_CPU_S",
    "DEFAULT_MEM_MB",
    "DEFAULT_PIDS",
    "MEASURED_FIELDS",
    "MEMORY_FAIL_CLASS",
    "MEM_DRIFT_REASON",
    "RUNNER_MEM_MB",
    "BudgetBreach",
    "BudgetDecision",
    "BudgetOverrun",
    "BudgetReason",
    "BudgetRun",
    "CgroupLimit",
    "CgroupPolicy",
    "SandboxBudget",
    "check_cgroup_budget",
    "classify_amount",
    "classify_count",
    "classify_seconds",
    "committed_budget_policy",
    "compile_budget_policy",
    "load_budget_policy",
    "over_limits",
    "sandbox_budget",
]

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, feature 167's ``sandbox-imports``, feature 166's
#: ``sandbox-transfer``, feature 165's ``sandbox-seed``, feature 164's
#: ``sandbox-threads``, feature 163's ``sandbox-timeout`` and feature 168's
#: ``sandbox-failclass``, not instead of any of them: the factory's registry is
#: keyed by name and a later registration of the same name *replaces* the
#: earlier one, so a member carrying eight controls carries eight components,
#: each answering its own feature's question.
BUDGET_COMPONENT_NAME: Final[str] = "sandbox-budget"

#: The marker a document declares itself with — the same discipline feature
#: 157's committed isolation artifact, feature 167's committed allowlist,
#: feature 164's committed pinning policy and feature 163's committed budget
#: take, so a stray JSON file carrying a ``mem_mb`` key cannot be read as this
#: policy.
BUDGET_POLICY_KIND: Final[str] = "sandbox-cgroup-limits"

#: The committed artifact, shipped beside the law that checks it, so a
#: checkout cannot hold one without the other.
COMMITTED_BUDGET_POLICY: Final[Path] = Path(__file__).with_name("budget_policy.json")

#: §5.2's cpu budget, spelled once: thirty seconds.  A constant *and* the value
#: the committed artifact must carry — the compiler refuses any other — so the
#: number ``cpu.max`` is written from is checked rather than remembered.
#: Restated from :data:`evaluator._sandbox.DEFAULT_CPU_S` rather than imported,
#: for the reason the module docstring gives: the sandbox member owns no
#: dependency on the member that drives it, and this suite pins the two agree.
DEFAULT_CPU_S: Final[float] = 30.0

#: §5.2's memory limit, in megabytes — the number the feature's own sentence
#: names, and the one that *replaces* the runner's portable ``RLIMIT_AS``
#: default rather than restating it.  See :data:`MEM_DRIFT_REASON`.
DEFAULT_MEM_MB: Final[int] = 2048

#: §5.2's process count — the feature's "process count of 32", and the
#: ``pids.max`` of the run's own cgroup.  Not to be confused with §12's
#: eight-task executor bound: see the module docstring.
DEFAULT_PIDS: Final[int] = 32

#: The three fields of §5.2's ``Limits(...)`` this law owns, in the order the
#: call site writes them — the policy's own order, and the order a refusal
#: lists its overruns in, so two deployments' breach records can be compared
#: field by field.
MEASURED_FIELDS: Final[tuple[str, ...]] = ("cpu_s", "mem_mb", "pids")

#: The room between the deployment's committed cgroup limit and the runner's
#: portable ``RLIMIT_AS`` fallback: the one number in this law that is not
#: §5.2's, recorded here because it is a *published* fact about the deployment
#: rather than an implementation detail — see :data:`MEM_DRIFT_REASON`.
RUNNER_MEM_MB: Final[int] = 4096

#: Why the deployment's cgroup memory limit and the runner's address-space
#: default are not the same number, in the words of the code that chose the
#: larger one.  Written down as data because the temptation a reader has — to
#: "reconcile" two numbers that look like a drift — is exactly what this
#: constant exists to answer: they are two enforcement mechanisms with two
#: failure modes, and the smaller one is §5.2's.
MEM_DRIFT_REASON: Final[str] = (
    "the cgroup limit is section 5.2's mem_mb=2048; the host runner's "
    "portable RLIMIT_AS fallback is 4096 because jemalloc's address-space "
    "reservation for the interpreter and polars exceeds 2 GiB even at ~70 MB "
    "resident, so a 2 GiB RLIMIT_AS is flaky (evaluator._sandbox.DEFAULT_MEM_MB)"
)

#: The class the runner records for a memory kill, so a breach sentence can
#: name the outcome a memory overrun becomes rather than leaving an operator to
#: guess.  Restated from the runner's own vocabulary —
#: :class:`evaluator.SandboxResult`'s failure envelopes, spelled as data here
#: for the member's one-provenance reason, and pinned by this suite against
#: :data:`sandbox.failclass.SANDBOX_RUNNER_CLASSES`.  It is one of the
#: *runner's* six and **not** one of §9.1's four, which is feature 168's
#: business rather than this module's: §9.1's column holds ``ok | timeout |
#: error | tripwire_fail``, and feature 168's table is what places this class
#: under ``error``.
MEMORY_FAIL_CLASS: Final[str] = "oom"

#: The greppable code every *breach* refusal carries — feature 162's own words
#: written as a token, the discipline
#: :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` (``gvisor_isolation_required``),
#: :data:`sandbox.imports.DISALLOWED_IMPORT_CODE` (``disallowed_import``),
#: :data:`sandbox.threads.THREAD_PINNING_CODE` (``thread_pinning_required``),
#: :data:`sandbox.seed.SEED_REQUIRED_CODE` (``node_seed_required``),
#: :data:`sandbox.failclass.FAIL_CLASS_REQUIRED_CODE` and
#: :data:`sandbox.timeout.TIMEOUT_FAIL_CLASS` set for theirs.  An operator
#: grepping a log for the rejection finds it by the feature's own words.
CGROUP_BUDGET_CODE: Final[str] = "cgroup_budget_exceeded"

#: The greppable code the *other* half of this law carries: the configured
#: limits could not be read, or a measurement could not be compared against
#: them.  Two codes rather than one because the repairs are on opposite sides
#: of the seam — this one means the caller's numbers are missing or malformed
#: (or the artifact did not compile), the other means the run genuinely
#: outran a limit — the split feature 168's two codes make for its own law.
CGROUP_LIMITS_REQUIRED_CODE: Final[str] = "cgroup_limits_required"

#: The near-miss shapes a count is refused from by name rather than coerced:
#: ``bytes`` because no cgroup counter reports a reading as bytes, and the
#: three types a *JSON document* hands a declared limit over as when the
#: writer put a string where the call site passes a number — ``str``, and the
#: two containers that make the refusal about the *shape* of the document
#: rather than about its values.  A tuple rather than a frozenset because it
#: is spent as the second argument to :func:`isinstance`.
#:
#: ``bool`` is deliberately **not** here, unlike in feature 164's own list: a
#: flag is refused by :func:`classify_count` *after* the integrality check
#: rather than before it, because a boolean that reaches this law from a
#: mapping is, in Python, an integer — and a limit of ``1`` process or ``1``
#: second written as ``True`` is a truthiness of the document rather than a
#: declaration of a budget, which is a judgement worth its own sentence rather
#: than a silent pass-through.  A ``float`` is not here either: a peak read off
#: ``memory.peak`` genuinely arrives as ``2048.0``, so it is admitted and
#: checked for integrality — see :func:`classify_count`.
_NOT_A_COUNT: Final[tuple[type, ...]] = (bytes, str, list, tuple)

#: The same for a duration: nothing here is a reading in seconds.  ``str`` is
#: refused rather than parsed, and ``bool`` though Python makes it an ``int``,
#: for the reasons :func:`sandbox.timeout.classify_duration` gives at its own
#: seam — one member, one reading of "is this a number".
_NOT_A_DURATION: Final[tuple[type, ...]] = (bool, str, bytes)


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise CgroupBudgetDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: {value!r}. "
            f"A cgroup budget is a structured document, and a compiler that "
            f"guessed at the meaning of a stray list or string would be writing "
            f"policy rather than reading it — refused, fail closed (feature "
            f"162)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise CgroupBudgetDocumentError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). The limit a deployment confines a run "
            f"to is named, not inferred: a field name that is absent, blank or "
            f"not a string is one this policy cannot hold a run to, and "
            f"'unnamed' is not 'memory.max' (feature 162, refused fail closed)."
        )
    return value


def _integral_count(value: float) -> int | None:
    """``value`` as an integer count, or ``None`` if it is not whole.

    A peak reading off ``memory.peak`` or ``pids.current`` is a count, but a
    runtime that reports it through a float-typed channel hands over
    ``2048.0`` — the same measurement written two ways, the property
    :func:`sandbox.timeout.classify_duration` states for ``30`` and ``30.0``.
    A *fractional* count is refused instead: ``2048.5`` processes is not a
    measurement any cgroup counter produces, and truncating it here would be
    this law quietly computing a number no kernel reported.
    """
    if not math.isfinite(value) or value != math.floor(value):
        return None
    return int(value)


def classify_seconds(value: Any) -> float | None:
    """Classify a value as a cpu duration in seconds, or ``None``.

    The one place this law reads a *duration*, so the committed artifact's
    ``cpu_s`` and a run's measured cpu time cannot disagree about what a
    number of seconds is — the member's one-provenance rule applied to the one
    quantity shared with feature 163's law.
    """
    if value is None or isinstance(value, _NOT_A_DURATION):
        return None
    if not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    # A non-finite or negative reading is not a duration: ``NaN`` compares
    # false against every bound, so a measurement admitted here would be one no
    # limit could ever be exceeded by, and a negative cpu time is a counter
    # that went backwards rather than a run that used less than nothing.
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def classify_count(value: Any) -> int | None:
    """Classify a value as a non-negative integer count, or ``None``.

    The counterpart of :func:`classify_seconds` for the two quantities that
    are not durations: memory in megabytes and a process count.  ``None`` for
    everything unplaceable — absent, text, bytes, a negative number, a
    fraction — because the *caller* decides which refusal that earns: a limit
    document and a run's measurement are refused with different sentences and
    different repairs.

    **The negative case is refused at an exact zero floor, and that is a
    decision rather than a simplification.**  A limit of ``0`` is representable
    and meaningful — a cgroup whose ``memory.max`` is zero admits no allocation
    at all — so the classifier admits it; a limit of ``-1`` is not a budget
    under any reading, since the comparison ``measured > -1`` would be true of
    every run ever dispatched and the "limit" would refuse everything.  The
    asymmetry is stated here because the alternative (refusing both, as a
    *positive* number) would make this law unable to express a legal cgroup
    configuration for a reason no operator could act on.
    """
    if value is None or isinstance(value, _NOT_A_COUNT):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or value < 0:
            return None
        return _integral_count(value)
    return None


def classify_amount(field: str, value: Any) -> float | int | None:
    """Classify ``value`` against the quantity ``field`` names, or ``None``.

    The one reader of a measurement, so the compiler, the artifact's read side
    and the gate cannot disagree about which of the three fields holds a
    duration and which hold counts.  ``None`` for a field name this law does
    not own, which is a fact about the *policy* rather than about the value —
    the compiler refuses such a document before it can be built.
    """
    if field == "cpu_s":
        return classify_seconds(value)
    if field in ("mem_mb", "pids"):
        return classify_count(value)
    return None


def _shape_consequence(field: str, value: Any) -> str:
    """The extra sentence for a declared amount of a type nothing reads as one."""
    kind = type(value).__name__
    if kind == "bool":
        return (
            " ``True`` is an ``int`` in Python and is deliberately not a "
            "budget: no cgroup is written from a flag, and accepting it would "
            "make a boolean and a limit indistinguishable."
        )
    if kind == "str":
        return (
            " A budget that arrived as text — the spelling a JSON document, an "
            "environment variable or a manifest read off a deployment carries "
            "it in — is a different type in a different place from the number "
            "``cpu.max``/``memory.max``/``pids.max`` is written from, and "
            "coercing it here would hide which side of that boundary the "
            "conversion was missing from."
        )
    if kind == "bytes":
        return (
            " Bytes are refused because no cgroup counter reports its reading "
            "as bytes, and a value that is not a number would have to be "
            "decoded by this law to be compared by a kernel."
        )
    if kind == "float" and field in ("mem_mb", "pids"):
        return (
            " A count is a whole number of megabytes or of processes: a "
            "fractional one is not a measurement any cgroup counter produces, "
            "and truncating it here would be this law computing a number no "
            "kernel reported."
        )
    return ""


@dataclass(frozen=True)
class CgroupLimit:
    """One configured limit: the field it governs, its value, and what it is.

    The unit of the committed artifact and of §5.2's ``Limits(...)``, held as
    a value rather than a bare number for the reason
    :class:`sandbox.isolation.ComponentIsolation` carries its mechanism and
    :class:`sandbox.timeout.TimeoutPolicy` its budget: a caller asking *what is
    this deployment's memory limit?* reads a named, unit-carrying answer rather
    than a number whose meaning depends on which argument of the call it came
    from, and a breach can say "3072 MB against a limit of 2048 MB" because the
    unit travelled with the limit instead of being remembered at each seam.

    ``unit`` is prose for the operator face only — ``"s"``, ``"MB"``, ``"pids"``
    — while ``field`` is §5.2's own argument name (``cpu_s``, ``mem_mb``,
    ``pids``), which is the spelling the gate reads a run's measurement under
    and the spelling a refusal quotes.  The two are kept apart deliberately: a
    message that said ``cpu_s`` three times would be a log line an operator has
    to decode, and one that said ``seconds`` three times would not say which
    argument to repair.
    """

    field: str
    value: float | int
    unit: str

    @property
    def is_duration(self) -> bool:
        """Whether this limit is measured in seconds rather than counted."""
        return self.field == "cpu_s"

    def describe(self) -> str:
        """``cpu_s = 30s`` — the limit as one reviewer-readable phrase."""
        return f"{self.field} = {self.value:g}{self.unit}"

    def exceeds(self, measured: Any) -> bool:
        """Whether a measurement exceeded this limit — strictly, or ``False``.

        The feature's word is *exceeded*, and the comparison is therefore
        ``>`` rather than ``>=``: a run that used exactly its budget did not
        exceed it, and a law that refused at the instant the limit was still
        satisfied would be sharper than §5.2's table.  The boundary is the
        whole reason this is a named method rather than an inline comparison —
        it is the one place the feature's verb is interpreted, on all three
        fields at once, and a reader asking *when exactly do we reject?* should
        be able to read the answer rather than infer it.

        ``False`` for a measurement that is not classifiable as the quantity
        this limit holds: a comparison between two values that are not numbers
        of the same kind has no defensible answer, and
        :func:`check_cgroup_budget` is where such a run is refused by name.
        """
        amount = classify_amount(self.field, measured)
        if amount is None:
            return False
        return amount > self.value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"CgroupLimit(field={self.field!r}, value={self.value!r}, unit={self.unit!r})"


class CgroupPolicy:
    """A compiled budget: every limit it names is §5.2's.

    What :func:`compile_budget_policy` returns is not the document — it is the
    document *plus* the guarantee that the three limits it declares are the
    call site's.  Holders (the gate, a CI check that recompiles the committed
    artifact, an operator asking what untrusted code may consume) cite that
    guarantee rather than re-derive it, which is why a breach sentence can say
    "against this deployment's committed limit" and mean it.

    Ordered as the document ordered it, so two deployments' budget records can
    be compared field by field — the property
    :class:`sandbox.threads.ThreadPinningPolicy` states for its own record.
    """

    __slots__ = ("_limits", "kind")

    def __init__(self, *, kind: str, limits: Sequence[CgroupLimit]) -> None:
        self.kind = kind
        self._limits = tuple(limits)

    def limits(self) -> tuple[CgroupLimit, ...]:
        """Every limit the policy declares, in document order."""
        return self._limits

    def fields(self) -> tuple[str, ...]:
        """The fields the policy declares, in document order."""
        return tuple(limit.field for limit in self._limits)

    def limit(self, field: str) -> CgroupLimit | None:
        """The limit declared for ``field``, or ``None``.

        The lookup decides nothing: a field the policy does not carry is
        answered by the *gate* by being outside the set it sweeps, not by this
        method returning a default — and the compiler has already refused a
        policy that omitted one of :data:`MEASURED_FIELDS`, so a ``None`` here
        means a caller asked about an argument this law does not own.
        """
        for limit in self._limits:
            if limit.field == field:
                return limit
        return None

    def value(self, field: str) -> float | int | None:
        """The value ``field`` is limited to, or ``None`` for an unlisted one."""
        limit = self.limit(field)
        return None if limit is None else limit.value

    def described(self) -> tuple[str, ...]:
        """Every limit as a reviewer-readable phrase, in document order.

        The read side a CI check or a runbook quotes, so a deployment
        describing its own posture transcribes the compiled artifact rather
        than re-typing three numbers beside three unit words.
        """
        return tuple(limit.describe() for limit in self._limits)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"CgroupPolicy(kind={self.kind!r}, "
            f"limits={[limit.describe() for limit in self._limits]!r})"
        )


#: The unit each field is measured in, for the *operator* face only — the
#: spelling :meth:`CgroupLimit.describe` and every breach sentence use.  Keyed
#: by §5.2's own argument name, so the three fields and their three units are
#: declared once rather than remembered at each seam, and a fourth field
#: arriving without a unit is a :class:`KeyError` at the compile rather than a
#: sentence reading ``mem_mb = 2048``.
_UNITS: Final[Mapping[str, str]] = {
    "cpu_s": "s",
    "mem_mb": "MB",
    "pids": "pids",
}

#: The two fields of the artifact that are a *configuration* rather than a
#: limit: things the deployment publishes about itself which a run is not
#: measured against.  ``runner_mem_mb`` is the one such field today — it is the
#: host runner's portable ``RLIMIT_AS`` fallback rather than the cgroup's
#: ``memory.max``, and :data:`MEM_DRIFT_REASON` says why the two differ.  Named
#: here so the compiler's sweep over :data:`MEASURED_FIELDS` and its check of
#: this set are two statements rather than one inference.
_PUBLISHED_FIELDS: Final[tuple[str, ...]] = ("runner_mem_mb",)


def _require_amount(field: str, value: Any) -> float | int:
    """Return ``value`` as the quantity ``field`` names, refusing anything else."""
    if value is None:
        raise CgroupBudgetDocumentError(
            f"a sandbox cgroup budget declares no {field!r}. §5.2's call site "
            f"passes ``limits=Limits(…, cpu_s={DEFAULT_CPU_S:g}, "
            f"mem_mb={DEFAULT_MEM_MB}, …, pids={DEFAULT_PIDS})`` and the "
            f"feature's own sentence names each of the three; a compiler that "
            f"read an absent limit as the default would be turning silence into "
            f"the strongest promise the document makes — 'unspecified' and "
            f"'confined to {field} by law' are different promises, and only the "
            f"second is feature 162's (refused, fail closed)."
        )
    amount = classify_amount(field, value)
    if amount is None:
        raise CgroupBudgetDocumentError(
            f"a sandbox cgroup budget declares {field} = {value!r} "
            f"({type(value).__name__}), which is not a "
            f"{'number of seconds' if field == 'cpu_s' else 'whole count'}. "
            f"§5.2's control table fixes the resource row at "
            f"``cpu.max``/``memory.max``/``pids.max`` over the call site's "
            f"``cpu_s={DEFAULT_CPU_S:g}``, ``mem_mb={DEFAULT_MEM_MB}`` and "
            f"``pids={DEFAULT_PIDS}``, and a limit no kernel can be written "
            f"from is one this policy cannot hold a run to."
            f"{_shape_consequence(field, value)} Refused (feature 162)."
        )
    return amount


def _require_published(field: str, value: Any) -> int:
    """Return ``value`` as a published count, refusing anything else.

    The same reading as :func:`_require_amount`, applied to the fields that are
    not limits.  Kept separate rather than folded in because the *repair* a
    refusal implies is different: a bad ``runner_mem_mb`` is a fact about the
    host runner's fallback that an operator edits for a reason about
    ``RLIMIT_AS``, not a budget a box is confined to.
    """
    if value is None:
        raise CgroupBudgetDocumentError(
            f"a sandbox cgroup budget declares no {field!r}. This deployment "
            f"publishes the host runner's portable address-space fallback "
            f"beside its cgroup limit, precisely so the two numbers cannot be "
            f"mistaken for each other (see the artifact's own comment); a "
            f"document that dropped one would leave a reader reconciling them "
            f"again (feature 162, refused fail closed)."
        )
    amount = classify_count(value)
    if amount is None:
        raise CgroupBudgetDocumentError(
            f"a sandbox cgroup budget declares {field} = {value!r} "
            f"({type(value).__name__}), which is not a whole count of "
            f"megabytes.{_shape_consequence('mem_mb', value)} Refused "
            f"(feature 162)."
        )
    return amount


def compile_budget_policy(document: Any) -> CgroupPolicy:
    """Compile a cgroup budget, refusing one that is not §5.2's.

    The seam the whole feature turns on.  The document is read whole — marker,
    the three limits, the published fallback — and each is held to the law
    before a :class:`CgroupPolicy` is handed out: it must declare itself
    :data:`BUDGET_POLICY_KIND`, ``cpu_s`` must be §5.2's thirty seconds,
    ``mem_mb`` its 2048, and ``pids`` its 32.  A refusal propagates as an
    exception, so a caller cannot continue with a half-trusted budget: the
    document that would have let a run hold a core, allocate a gigabyte past
    the limit or fork without bound is never applied, which is the compile-time
    half of "System rejects" (feature 162).

    Every value is checked through the *same* classifiers the gate reads a
    run's measurements with (:func:`classify_seconds`, :func:`classify_count`),
    so the document and the run cannot disagree about what a number of seconds
    or a whole count is — one reading, two seams, the member's one-provenance
    rule.  The refusal names the offending field *and* its value rather than
    merely the document, because a message saying only "budget refused" would
    hide which of the three a drifted configuration got wrong.

    **The artifact is refused whole, not corrected field by field.**  The same
    reading :func:`sandbox.isolation.compile_isolation_policy` takes of a
    component block and :func:`sandbox.timeout.compile_timeout_policy` of its
    budget: a policy applied with one limit silently replaced is one whose file
    and whose box disagree, and that disagreement is where the next drift lives.
    """
    doc = _require_mapping(document, "sandbox cgroup budget document")
    marker = _require_str(doc.get("policy"), "sandbox cgroup budget 'policy'")
    if marker != BUDGET_POLICY_KIND:
        raise CgroupBudgetDocumentError(
            f"a sandbox cgroup budget must declare itself "
            f"{BUDGET_POLICY_KIND!r}, got {marker!r}. A document that does not "
            f"say what it is cannot be trusted to say what untrusted code may "
            f"consume, and a stray JSON file carrying a 'mem_mb' key is not "
            f"this policy — refused, fail closed (feature 162)."
        )

    limits: list[CgroupLimit] = []
    for field in MEASURED_FIELDS:
        amount = _require_amount(field, doc.get(field, None))
        limits.append(CgroupLimit(field=field, value=amount, unit=_UNITS[field]))

    for field, value in (
        ("cpu_s", DEFAULT_CPU_S),
        ("mem_mb", DEFAULT_MEM_MB),
        ("pids", DEFAULT_PIDS),
    ):
        declared = next(limit.value for limit in limits if limit.field == field)
        if declared != value:
            raise CgroupBudgetExceeded(
                f"{CGROUP_LIMITS_REQUIRED_CODE}: the committed cgroup budget "
                f"declares {field} = {declared!r}, and §5.2's call site passes "
                f"``{field}={value}`` with the feature's own sentence naming "
                f"the limits. A limit other than the committed one is a "
                f"deployment that confines untrusted code at a number nobody "
                f"wrote down, and every stored breach beside it dates a "
                f"rejection to a budget the file does not name. The whole "
                f"document is refused rather than the value quietly applied "
                f"(feature 162)."
            )

    if (
        _require_published("runner_mem_mb", doc.get("runner_mem_mb", None))
        != RUNNER_MEM_MB
    ):
        raise CgroupBudgetExceeded(
            f"{CGROUP_LIMITS_REQUIRED_CODE}: the committed cgroup budget "
            f"publishes runner_mem_mb = {doc.get('runner_mem_mb')!r}, and this "
            f"deployment's host runner falls back to {RUNNER_MEM_MB} MB of "
            f"address space. The two numbers are different facts about "
            f"different mechanisms — {MEM_DRIFT_REASON} — and a document that "
            f"published either one in the other's place would be a reviewer "
            f"reading a cgroup limit out of an RLIMIT_AS default. Refused "
            f"(feature 162)."
        )

    return CgroupPolicy(kind=BUDGET_POLICY_KIND, limits=limits)


def load_budget_policy(path: Path = COMMITTED_BUDGET_POLICY) -> CgroupPolicy:
    """Read and compile a budget from disk, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly
    as a drift compiled in memory (feature 162).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise CgroupBudgetDocumentError(
            f"could not read the sandbox cgroup budget at {path}: {exc}. A "
            f"budget that cannot be read is not a budget that confines nothing "
            f"gracefully — it is one whose deployment has no resource law at "
            f"all, and a caller that carried on would be running agent-authored "
            f"code with no bound on the core, the memory or the process table "
            f"while believing it was configured from this file (feature 162)."
        ) from exc
    except ValueError as exc:
        raise CgroupBudgetDocumentError(
            f"the sandbox cgroup budget at {path} is not valid JSON: {exc}. "
            f"Refused rather than read partially: a policy compiled from a "
            f"partially-parsed document is one whose file and whose cgroup "
            f"disagree (feature 162)."
        ) from exc
    return compile_budget_policy(document)


def committed_budget_policy() -> CgroupPolicy:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 162's own tests hold to §5.2's three numbers, so "the deployment
    confines a run to §5.2's cpu, memory and process count" is a checked fact
    about a file in the repository rather than a claim in a runbook.
    """
    return load_budget_policy(COMMITTED_BUDGET_POLICY)


class BudgetRun:
    """One sandboxed run, as presented to the cgroup law.

    Feature 162's sentence is about *a sandboxed run*, and §5.2 describes one as
    a call: the code, the payload, the limits, the seed, the env.  This models
    exactly the half of that call this law has a claim about — the *measured*
    cpu time, memory peak and process count — and deliberately does not model
    the rest, for the reason :class:`sandbox.isolation.SandboxRun` states for
    its own boundary.

    **What it carries is what a cgroup reported, never a probe.**  Nothing in
    this module reads ``cpu.stat``, ``memory.peak`` or ``pids.current``: the
    runtime that owns the cgroup is the one that knows what the run consumed,
    so the three readings arrive as arguments — the same division that has
    feature 157's law read a run's *declared* isolation rather than dial a
    container runtime and feature 163's read a watchdog's elapsed time rather
    than call a clock.  A law that opened the cgroup hierarchy itself would be a
    second, disagreeing measurement of a fact the runtime already recorded.

    **A field the run does not carry is ``None``, and that is not zero.**  This
    is the one shape difference between this law and feature 163's, and it is
    forced by the subject: a cpu *duration* is always reported (a run that used
    no cpu used ``0.0`` seconds and there is nothing absent about it, so
    feature 163's run requires one), while a *peak* is only knowable if the
    runtime published one.  A deployment whose ``memory.peak`` is unreadable —
    an older kernel, a hierarchy mounted without the controller, a gVisor
    version that does not expose it — reports ``None`` and this law refuses the
    comparison by name rather than reading silence as a comfortable zero.  The
    refusal is the feature: *"'unmeasured' is not 'under the limit'"* is the
    same judgement :func:`sandbox.timeout.kill_timeout` makes about an
    unmeasurable elapsed time.

    ``node_id`` and ``component`` are carried for the breach record and are not
    read by the comparison, the same courtesy
    :class:`sandbox.timeout.TimeoutKill` extends.
    """

    __slots__ = ("component", "cpu_s", "mem_mb", "node_id", "pids")

    def __init__(
        self,
        *,
        cpu_s: Any,
        mem_mb: Any = None,
        pids: Any = None,
        node_id: str = "",
        component: str = "",
    ) -> None:
        self.cpu_s = cpu_s
        self.mem_mb = mem_mb
        self.pids = pids
        self.node_id = node_id
        self.component = component

    def measured(self, field: str) -> Any:
        """The reading this run carries for ``field``, or ``None``.

        The one reader of a run's three quantities, so the gate and the refusal
        sentences cannot disagree about what was found — the counterpart of
        :func:`sandbox.timeout._subject_duration`, and the seam a caller's own
        record type arrives through.
        """
        return getattr(self, field, None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"BudgetRun(cpu_s={self.cpu_s!r}, mem_mb={self.mem_mb!r}, "
            f"pids={self.pids!r}, node_id={self.node_id!r}, "
            f"component={self.component!r})"
        )


class BudgetReason(enum.StrEnum):
    """Why a run was admitted or refused — the audit vocabulary.

    One enumeration carries the acceptance and the refusals, because a
    decision's reason is one fact with two polarities and the audit line should
    read the same either way: ``within-limits`` names the fact the run was
    admitted on, and the refusals name what was found instead — the shape
    :class:`sandbox.isolation.RunReason`, :class:`sandbox.timeout.TimeoutReason`
    and :class:`sandbox.failclass.FailClassReason` give their own laws.
    """

    #: Admitted: every limit the policy declares was measured, and none was
    #: exceeded.  The feature's *negative* case, and the reason it is a reason
    #: rather than a ``None``: a run admitted because it was measured against
    #: three limits is a different fact from one no limit could speak about,
    #: and the audit line should say which happened.
    WITHIN_LIMITS = "within-limits"

    #: Refused: the run exceeded at least one of the deployed cgroup limits.
    #: Feature 162's headline, and the only reason a decision carries a
    #: :class:`BudgetBreach`.
    OVER_LIMITS = "over-cgroup-limits"

    #: Refused: the subject is not a run this law can read — not a
    #: :class:`BudgetRun` and not an object carrying a cpu time.  A refusal
    #: rather than a raise, like the other laws' gates', because the caller
    #: that has been handed the wrong object still needs to be told *which* one
    #: it was.
    UNREADABLE_SUBJECT = "unreadable-subject"

    #: Refused: a measurement the run carries is not a quantity this law can
    #: compare — absent where the limit requires a reading, text, bytes, a
    #: negative number, a fraction.  Its own reason because the repair is
    #: different from the last one: the caller has the right *object* and an
    #: unusable *reading*, and whatever produced that counter is where the
    #: operator has to look.
    UNMEASURED = "unmeasured-resource"


class BudgetOverrun:
    """One limit a run exceeded: the field, the limit, the reading, the excess.

    The unit a breach is composed of, and the reason a breach can be *plural*:
    a signal that allocated 3 GB and forked 200 children has broken two limits,
    and a record carrying only the first would leave an operator repairing the
    memory and re-running into the process table.  So every overrun is collected
    before anything is reported — the discipline
    :func:`sandbox.threads.check_thread_pinning` states for its own sweep —
    and a refusal lists all of them.

    ``excess`` is the subtraction, computed once here rather than re-derived by
    each reader, and it is strictly positive by construction: the gate builds
    an overrun only on a strict ``>``, and the constructor refuses a pair that
    did not exceed, so a record cannot claim a breach that never happened — the
    invariant :class:`sandbox.timeout.TimeoutKill` states for its own
    ``overrun_s``.
    """

    __slots__ = ("field", "limit", "measured", "unit")

    def __init__(
        self,
        *,
        field: str,
        limit: float,
        measured: float,
        unit: str,
    ) -> None:
        self.field = field
        self.limit = limit
        self.measured = measured
        self.unit = unit

    @property
    def excess(self) -> float | int:
        """How far past the limit the run went — strictly positive."""
        return self.measured - self.limit

    def describe(self) -> str:
        """``mem_mb: 3072MB against a limit of 2048MB (+1024MB)``.

        The operator line, and the reason :class:`BudgetOverrun` exists as a
        type rather than as a tuple: a breach sentence lists one of these per
        broken limit, and each names the field, the measurement, the limit and
        the *excess* — the last being what a reviewer sizing a wider budget
        actually reads.
        """
        return (
            f"{self.field}: {self.measured:g}{self.unit} against a limit of "
            f"{self.limit:g}{self.unit} (+{self.excess:g}{self.unit})"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"BudgetOverrun(field={self.field!r}, limit={self.limit!r}, "
            f"measured={self.measured!r}, unit={self.unit!r})"
        )


class BudgetBreach:
    """One rejected run: every limit it exceeded, and the readings that earned it.

    Feature 162's *rejects* half as a value — what a caller hands a ledger row,
    an operator log and a quarantine decision — carrying the field names, the
    compiled limits and the measurements, so *why was this node refused?* is
    answerable from the record rather than from a log line that has since
    rotated.  The shape :class:`sandbox.timeout.TimeoutKill` gives feature 163's
    kill, one law over.

    ``fail_class`` is the runner's spelling for the *worst* thing that happened
    — a memory breach is the runner's ``oom``, an exhausted cpu budget the
    runner's ``timeout``, and a process-count breach the runner's ``crash`` —
    restated as data (:data:`MEMORY_FAIL_CLASS` and the two literals in
    :func:`_breach_fail_class`) for the member's one-provenance reason.  It is
    deliberately **not** one of §9.1's four: the column holds four values and
    feature 168's table is what places each of these under one of them, which is
    why :meth:`row` publishes the runner's class under the runner's own field
    name and leaves the translation to the law that owns it.
    """

    __slots__ = ("component", "detail", "node_id", "overruns")

    def __init__(
        self,
        *,
        overruns: Sequence[BudgetOverrun],
        detail: str,
        node_id: str = "",
        component: str = "",
    ) -> None:
        self.overruns = tuple(overruns)
        self.detail = detail
        self.node_id = node_id
        self.component = component
        # A breach with no overrun is a contradiction, and it is the one this
        # object cannot survive being read back: ``fields`` would be empty, the
        # sentence would name nothing, and *"this run was rejected"* and *"this
        # run was measured and refused for no stated reason"* would be the same
        # record.  ``check_cgroup_budget`` never builds one — it refuses as
        # ``UNMEASURED`` instead — and the check is here rather than only there
        # because this class is exported: a caller assembling a breach by hand,
        # or a store row being rebuilt into one, would otherwise get a
        # ``cgroup_budget_exceeded`` for a run nobody measured, which is exactly
        # the fabricated rejection the whole feature exists to prevent.
        if not self.overruns:
            raise CgroupBudgetExceeded(
                f"{CGROUP_BUDGET_CODE}: a breach was assembled with no overrun "
                f"in it, so it names no limit this run exceeded. This object "
                f"means *a run outran the deployment's cgroup limits* — §5.2's "
                f"control row, 'Resources | cgroup v2: cpu.max, memory.max, "
                f"pids.max' — and one built for a run nobody measured would "
                f"publish a rejection with no reading behind it. Refused rather "
                f"than recorded: a fabricated breach is as wrong as a missing "
                f"one (feature 162)."
            )

    @property
    def fields(self) -> tuple[str, ...]:
        """The limits this run exceeded, in the policy's own order."""
        return tuple(overrun.field for overrun in self.overruns)

    @property
    def fail_class(self) -> str:
        """The runner's spelling for the worst thing that happened."""
        return _breach_fail_class(self.overruns)

    @property
    def exceeded_cpu(self) -> bool:
        """Whether the cpu budget was one of the limits broken."""
        return "cpu_s" in self.fields

    @property
    def exceeded_memory(self) -> bool:
        """Whether the memory limit was one of the limits broken."""
        return "mem_mb" in self.fields

    @property
    def exceeded_pids(self) -> bool:
        """Whether the process count was one of the limits broken."""
        return "pids" in self.fields

    def rows(self) -> list[dict[str, Any]]:
        """The breach as store-shaped mappings — one row per broken limit.

        A list rather than one mapping, because a breach *is* plural: a run that
        allocated past ``memory.max`` and forked past ``pids.max`` broke two
        limits, and a store that flattened them into one row would lose the
        second reading.  Each row carries the field, the limit, the measurement
        and the unit — the four values a later "which limit do we keep
        breaking?" query needs — plus the node and component identity when the
        run carried them.  Fresh dicts per call, never a shared list: the
        copy-then-hand discipline :meth:`sandbox.timeout.TimeoutKill.row` and
        :meth:`sandbox.seed.SeedDecision.seed_env` apply to their own shapes.
        """
        rows: list[dict[str, Any]] = []
        for overrun in self.overruns:
            row: dict[str, Any] = {
                "limit_field": overrun.field,
                "limit_value": overrun.limit,
                "measured": overrun.measured,
                "unit": overrun.unit,
                "excess": overrun.excess,
            }
            if self.node_id:
                row["node_id"] = self.node_id
            if self.component:
                row["component"] = self.component
            rows.append(row)
        return rows

    def row(self) -> dict[str, Any]:
        """The breach as one store-shaped mapping — the summary row.

        The *counting* shape, beside :meth:`rows`' per-limit shape: a caller
        that wants one line per rejected run reads this, and the runner's class
        travels under the runner's own field name (``fail_class``) because that
        is what the box reported — feature 168 is the law that places it in
        §9.1's column, and a second translation here would be a second spelling
        of its table.
        """
        row: dict[str, Any] = {
            "fail_class": self.fail_class,
            "over_limits": list(self.fields),
            "measured": {overrun.field: overrun.measured for overrun in self.overruns},
            "limits": {overrun.field: overrun.limit for overrun in self.overruns},
        }
        if self.node_id:
            row["node_id"] = self.node_id
        if self.component:
            row["component"] = self.component
        return row

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"BudgetBreach(fields={list(self.fields)!r}, "
            f"fail_class={self.fail_class!r}, node_id={self.node_id!r})"
        )


def _breach_fail_class(overruns: Sequence[BudgetOverrun]) -> str:
    """The runner's class for a set of overruns — the *worst* thing that happened.

    The precedence is the cgroup's own, and it is the order in which a kernel
    would have acted: a process that exhausts its cpu budget is killed by
    ``cpu.max``'s throttling and the runner records ``timeout``; one that
    allocates past ``memory.max`` is OOM-killed and the runner records ``oom``;
    a run that forked past ``pids.max`` had its ``fork`` fail outright, which is
    the runner's ``crash``.  A run that did two of these is reported by the one
    that would have killed it first, because that is the class the box will
    actually have written down — the runner's class is *reported*, not chosen by
    this law, and a breach that named a class the box never wrote would be a
    second opinion about an outcome.

    Restated as data rather than imported for the member's one-provenance
    reason; this suite pins the three against feature 168's
    :data:`sandbox.failclass.SANDBOX_RUNNER_CLASSES`.
    """
    fields = {overrun.field for overrun in overruns}
    if "cpu_s" in fields:
        return "timeout"
    if "mem_mb" in fields:
        return MEMORY_FAIL_CLASS
    return "crash"


class BudgetDecision:
    """The gate's whole answer: refused or not, why, and in what words.

    ``breach`` is the one field a caller must check, and it is *computed* from
    the classified measurements rather than set by a constant — the same
    "computed, never assumed" stance :class:`sandbox.isolation.RunDecision`,
    :class:`sandbox.timeout.TimeoutDecision` and
    :class:`sandbox.failclass.FailClassDecision` take.  ``within_limits`` is a
    reason rather than a ``None`` both ways round, because a run admitted after
    being measured against three limits and a run no limit could speak about are
    different facts and the audit line should say which happened — the property
    :attr:`sandbox.timeout.TimeoutDecision.refused` exists to keep.

    :attr:`refused` is deliberately separate from ``not within_limits`` in
    *meaning*, though they coincide: the member's other decisions state a
    refusal as its own property, and a caller that read a bare falsy as "the run
    was fine" would treat an unmeasurable run as an admitted one.
    """

    __slots__ = ("breach", "detail", "reason")

    def __init__(
        self,
        *,
        reason: BudgetReason,
        detail: str,
        breach: BudgetBreach | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.breach = breach

    @property
    def admitted(self) -> bool:
        """Whether the run was measured and stayed inside every limit."""
        return self.reason is BudgetReason.WITHIN_LIMITS

    @property
    def over_limits(self) -> bool:
        """Whether the run exceeded at least one deployed limit — the headline."""
        return self.breach is not None

    @property
    def refused(self) -> bool:
        """Whether this law could not read the run or one of its measurements.

        The two refusal reasons — never :attr:`BudgetReason.OVER_LIMITS
        <sandbox.budget.BudgetReason.OVER_LIMITS>`, which is a genuine rejection
        of a run that ran, and never :attr:`WITHIN_LIMITS
        <sandbox.budget.BudgetReason.WITHIN_LIMITS>`, which is a clean run.
        """
        return self.reason in (
            BudgetReason.UNREADABLE_SUBJECT,
            BudgetReason.UNMEASURED,
        )

    def require(self) -> None:
        """Raise :class:`~sandbox.errors.CgroupBudgetExceeded` unless admitted.

        The bridge between the gate's returned answer and the exception a
        launcher wants on the line after the spawn: a decision that admitted the
        run is a no-op, so a caller can use it unconditionally as the last thing
        before it forks.  An overrun raises the *breach's* own sentence,
        :class:`~sandbox.errors.CgroupBudgetExceeded`; an unreadable subject or
        an unusable reading raises the same class carrying the refusal's
        sentence, because the two halves of feature 162 carry one error type and
        a caller never has to catch two — the division
        :meth:`sandbox.isolation.RunDecision.require` draws for its own pair.

        Unlike :meth:`sandbox.timeout.TimeoutDecision.require`, this verb
        returns nothing on success rather than a value: there is no kill to hand
        back, because a run inside its limits leaves no record to persist — the
        asymmetry the two features' *subjects* force, stated here rather than
        left for a reader to notice.
        """
        if self.breach is not None:
            # The *breach's* sentence rather than this decision's one-line
            # summary: a launcher that raises has nothing to print but the
            # exception, so the listing of every broken limit and both numbers
            # beside each has to be in the message an operator ends up reading.
            raise CgroupBudgetExceeded(self.breach.detail)
        if self.refused:
            raise CgroupBudgetExceeded(self.detail)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"BudgetDecision(reason={self.reason!r}, "
            f"over_limits={self.over_limits}, refused={self.refused})"
        )


def _subject_measurement(subject: object, field: str) -> Any:
    """The raw reading ``subject`` carries for ``field``, or ``None``.

    Reads a :class:`BudgetRun` and any object carrying the attribute, because
    the caller's own record type may describe a run this law should still be
    able to judge — the same tolerance
    :func:`sandbox.timeout._subject_duration` and
    :func:`sandbox.threads._subject_environment` extend to the shapes their own
    subjects arrive in.  ``None`` for an object that does not carry the field at
    all *and* for one that carries an explicit ``None`` — the two are one fact
    here ("no reading"), and the distinction between them is not something a
    cgroup makes: an unreadable ``memory.peak`` and an absent ``memory.peak``
    are the same silence.
    """
    return getattr(subject, field, None)


def _subject_identity(subject: object) -> tuple[str, str]:
    """The ``(node_id, component)`` a subject names — ``("", "")`` when it names none.

    Read while building a sentence, so a subject carrying a non-string identity
    is reported as carrying none rather than crashing the refusal that was about
    to describe it.
    """
    node = getattr(subject, "node_id", "")
    owner = getattr(subject, "component", "")
    return (
        node if isinstance(node, str) else "",
        owner if isinstance(owner, str) else "",
    )


def _malformed_refusal(subject: object, field: str, raw: Any) -> str:
    """The refusal for a run whose reading for ``field`` is not a quantity."""
    unit = _UNITS[field]
    what = "a number of cpu seconds" if field == "cpu_s" else f"a whole count of {unit}"
    return (
        f"{CGROUP_LIMITS_REQUIRED_CODE}: a sandboxed run was offered to the "
        f"cgroup gate with {field} = {raw!r} ({type(raw).__name__}), which is "
        f"not {what}. §5.2 confines the run at "
        f"``Limits(cpu_s={DEFAULT_CPU_S:g}, mem_mb={DEFAULT_MEM_MB}, "
        f"pids={DEFAULT_PIDS})`` and the whole subject of this law is the "
        f"reading a cgroup reported against those three — so a value that is "
        f"text, bytes, a flag, a negative number or a fraction cannot be asked "
        f"whether it outran anything. Refused rather than counted as inside "
        f"the limit: 'unmeasurable' is not 'within limits', and a run whose "
        f"breach went unreported is exactly the failure this feature exists to "
        f"prevent (feature 162)."
    )


def _unreadable_refusal(subject: object) -> str:
    """The refusal for a subject carrying no cpu time at all."""
    return (
        f"{CGROUP_LIMITS_REQUIRED_CODE}: a sandboxed run was offered to the "
        f"cgroup gate carrying no cpu time at all (got "
        f"{type(subject).__name__}: {subject!r}). §5.2 dispatches every run "
        f"under a ``limits=Limits(cpu_s=…, …)`` clause and a cgroup that "
        f"accounts its cpu; the law's subject is the reading that cgroup "
        f"reported, and a run described as anything else cannot be asked "
        f"whether it outran its limits. The run is not rejected on a limit it "
        f"cannot be measured against (feature 162)."
    )


def _breach_refusal(
    overruns: Sequence[BudgetOverrun],
    *,
    fields: tuple[str, ...],
    component: str,
) -> str:
    """The operator-facing sentence for a rejected run."""
    listed = "\n  ".join(overrun.describe() for overrun in overruns)
    return (
        f"{CGROUP_BUDGET_CODE}: the sandboxed run of component {component!r} "
        f"exceeded {len(overruns)} of this deployment's cgroup limits — "
        f"{', '.join(fields)} — and is rejected. §5.2's control table is "
        f"'Resources | cgroup v2: cpu.max, memory.max, pids.max', and §3's zone "
        f"map states the posture it serves: 'Z1 — Mutated by the loop | Signal "
        f"code, exploration policy code | LLM agents | Sandboxed: no network, "
        f"no FS, seccomp, cgroup limits'. The readings:\n  "
        + listed
        + (
            f"\nEach limit is §5.2's call site verbatim — "
            f"``cpu_s={DEFAULT_CPU_S:g}``, ``mem_mb={DEFAULT_MEM_MB}``, "
            f"``pids={DEFAULT_PIDS}`` — compiled from the committed artifact "
            f"rather than remembered at this seam, and the comparison is strict "
            f"the feature's own word 'exceeding' requires: a run that used "
            f"exactly a limit did not exceed it. Rejected rather than reported "
            f"after: a signal that holds a core past its budget or forks "
            f"without bound is the failure this control exists to contain, and "
            f"a run that proceeded would report an ordinary trial outcome for a "
            f"candidate that was never confined (feature 162)."
        )
    )


def check_cgroup_budget(subject: object, policy: CgroupPolicy) -> BudgetDecision:
    """Answer one run: inside every limit, or refused with the readings.

    The gate, and the one place the law is actually applied — every other verb
    in this module (:meth:`SandboxBudget.check`, :meth:`BudgetDecision.require`)
    reaches this function rather than re-deciding.  Nothing is raised here for
    an overrun, for the reason features 157's, 167's, 163's and 168's gates
    raise nothing: the pipeline dispatches thousands of unattended candidates
    and *"this one outran a cgroup"* must reach an operator as a fact about a
    run rather than as a crashed evaluator, while a caller that must not proceed
    turns the answer into an exception with :meth:`BudgetDecision.require`.

    The sweep is over the *policy's* limits, in policy order, and the comparison
    is against the policy's own declared values rather than against module
    constants — so the rejection is the compiled declaration arriving at its
    answer, and a hand-assembled policy carrying other numbers would reject at
    those numbers and say so (itself the audit finding).  Every limit is
    classified before anything is decided, so a refusal lists *all* the limits a
    run broke rather than whichever one the sweep happened to reach first.

    The order of the refusals is the order of the sentence: the subject is
    settled first — a run carrying no cpu time has no reading to compare and is
    not rejected on a limit it cannot be measured against — then each
    measurement, then the comparison, which is the only thing that can reject.
    """
    if _subject_measurement(subject, "cpu_s") is None:
        return BudgetDecision(
            reason=BudgetReason.UNREADABLE_SUBJECT,
            detail=_unreadable_refusal(subject),
        )

    overruns: list[BudgetOverrun] = []
    for limit in policy.limits():
        raw = _subject_measurement(subject, limit.field)
        if raw is None:
            # A limit the run cannot be measured against.  Its own refusal
            # rather than a rejection, and its own *reason* rather than the
            # unreadable-subject one: the object is right and the reading is
            # missing, so the operator looks at whatever published the counter
            # rather than at the caller's record type.
            return BudgetDecision(
                reason=BudgetReason.UNMEASURED,
                detail=(
                    f"{CGROUP_LIMITS_REQUIRED_CODE}: a sandboxed run "
                    f"({_subject_identity(subject)[1]!r}) was offered to the "
                    f"cgroup gate with no reading for {limit.field!r}, and this "
                    f"deployment confines every run at {limit.describe()}. "
                    f"§5.2's control row is 'Resources | cgroup v2: cpu.max, "
                    f"memory.max, pids.max', so the numbers this law compares "
                    f"are the cgroup's own counters — and a counter that was "
                    f"never read (an unreadable ``memory.peak``, a hierarchy "
                    f"mounted without the controller, a caller that assembled a "
                    f"run by hand) leaves this law unable to say whether the "
                    f"limit held. Refused rather than admitted: 'unmeasured' is "
                    f"not 'under the limit', and a run admitted on silence is "
                    f"one whose breach would never be recorded (feature 162)."
                ),
            )
        amount = classify_amount(limit.field, raw)
        if amount is None:
            return BudgetDecision(
                reason=BudgetReason.UNMEASURED,
                detail=_malformed_refusal(subject, limit.field, raw),
            )
        if limit.exceeds(amount):
            overruns.append(
                BudgetOverrun(
                    field=limit.field,
                    limit=limit.value,
                    measured=amount,
                    unit=limit.unit,
                )
            )

    node, owner = _subject_identity(subject)

    if overruns:
        fields = tuple(overrun.field for overrun in overruns)
        return BudgetDecision(
            reason=BudgetReason.OVER_LIMITS,
            breach=BudgetBreach(
                overruns=overruns,
                node_id=node,
                component=owner,
                detail=_breach_refusal(overruns, fields=fields, component=owner),
            ),
            detail=(
                f"{CGROUP_BUDGET_CODE}: the run of component {owner!r} exceeded "
                f"{len(overruns)} cgroup limit(s) — {', '.join(fields)} — and is "
                f"rejected (feature 162)."
            ),
        )

    return BudgetDecision(
        reason=BudgetReason.WITHIN_LIMITS,
        detail=(
            f"run of component {owner!r} admitted: it was measured against "
            f"every cgroup limit this deployment declares — "
            f"{', '.join(policy.described())} — and exceeded none, which is "
            f"§5.2's resource row ('cgroup v2: cpu.max, memory.max, pids.max') "
            f"holding (feature 162)."
        ),
    )


def over_limits(subject: object, policy: CgroupPolicy) -> bool:
    """Whether a run exceeded any of a policy's limits — the one boolean.

    The convenience for a caller that does not want the decision: the same
    computation, read at its headline.  A *refused* run is not over its limits,
    which is what :attr:`BudgetDecision.refused` is for — a caller that branches
    on this alone has asked only the arithmetic question, the same caveat
    :meth:`sandbox.timeout.SandboxTimeout.killed` states for its own.

    Never raises: an unmeasurable run is ``False`` here because the caller that
    must hear about it calls :func:`check_cgroup_budget`.
    """
    return check_cgroup_budget(subject, policy).over_limits


class SandboxBudget:
    """Feature 162's law, as the value a composed application carries.

    A stateless facade over this module and the committed limits it compiled —
    the same shape :class:`sandbox.SandboxIsolation` gives feature 157,
    :class:`sandbox.SandboxImports` 167, :class:`sandbox.SandboxTransfer` 166,
    :class:`sandbox.SandboxSeed` 165, :class:`sandbox.SandboxThreads` 164 and
    :class:`sandbox.SandboxTimeout` 163 — so a caller holding the composed
    component can ask the feature's question, *did this run outrun the cgroup
    limits, and if so with what readings?*, without importing the member's
    submodules by name or re-reading the artifact.

    **It carries no cgroup, no counter and no probe.**  A component shared
    across runs that opened a hierarchy — or that installed a probe when it was
    built — would be one reading counters that belong to a single run's cgroup,
    the property :class:`sandbox.SandboxTimeout` states for its own missing
    watchdog.  What it carries is the compiled limits: three numbers, and the
    guarantee that they are §5.2's.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the comparison or the breach
    sentence here would be a second thing to keep in sync, and the member's
    one-provenance rule exists so that cannot happen.
    """

    __slots__ = ("_policy",)

    def __init__(self, policy: CgroupPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> CgroupPolicy:
        """The compiled limits this component carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator asking what untrusted code may consume — reads the limits
        rather than re-deriving them.  Reading them widens nothing: the policy
        holds no capability, which is the point of the component being a facade
        rather than a cgroup.
        """
        return self._policy

    @property
    def cpu_s(self) -> float | int | None:
        """The cpu budget this deployment confines a run to, in seconds."""
        return self._policy.value("cpu_s")

    @property
    def mem_mb(self) -> float | int | None:
        """The memory limit this deployment confines a run to, in megabytes."""
        return self._policy.value("mem_mb")

    @property
    def pids(self) -> float | int | None:
        """The process count this deployment confines a run to."""
        return self._policy.value("pids")

    def check(self, subject: object) -> BudgetDecision:
        """Answer whether ``subject`` exceeded a limit — the gate, as a value.

        ``subject`` is a :class:`BudgetRun` or any object carrying ``cpu_s``
        (and optionally ``mem_mb`` and ``pids``), which is how a caller's own
        run record can be judged without being re-described.  The cgroup is
        never opened: this law reads what a runtime reported, so a test never
        depends on the machine that started pytest having a cgroup v2 hierarchy
        at all.
        """
        return check_cgroup_budget(subject, self._policy)

    def over_limits(self, subject: object) -> bool:
        """Whether ``subject`` exceeded any limit — the one boolean."""
        return self.check(subject).over_limits

    def require(self, subject: object) -> None:
        """Return ``None`` if the run is inside every limit, else raise.

        The launcher's verb, and the one line that makes *"a run exceeding the
        cgroup limits is rejected"* enforced at the dispatch rather than
        remembered: put it after the spawn and a breach becomes the member's own
        :class:`~sandbox.errors.CgroupBudgetExceeded` rather than an ordinary
        trial outcome for a run nothing confined.
        """
        self.check(subject).require()

    def limits(self) -> tuple[CgroupLimit, ...]:
        """Every limit this deployment declares, in policy order."""
        return self._policy.limits()

    def described(self) -> tuple[str, ...]:
        """The limits as reviewer-readable phrases — the read side."""
        return self._policy.described()


def sandbox_budget() -> SandboxBudget:
    """The cgroup law, compiled fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs a run's measurements
    to answer for.  This is the module-level convenience the member's own tests
    and any operator script reach, and it is the same call
    :func:`sandbox.build_sandbox_budget` makes minus the composition.
    """
    return SandboxBudget(committed_budget_policy())
