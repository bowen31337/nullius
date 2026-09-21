"""Feature 163's law: a run past its wall budget is killed and recorded.

app_spec.xml, "Untrusted Code Sandbox", feature 163: *System persists a
timeout fail class after hard-killing a sandboxed run that exceeded its 30
second wall clock budget.*  docs/nullius-tech-architecture.md §5.2 gives the
feature its call site — the one place a run is described — and names the
budget inside it::

    result = sandbox.run(
        entrypoint="signal",
        code=node.code,
        payload=window.to_arrow(),        # IPC, zero-copy
        limits=Limits(wall_s=30, cpu_s=30, mem_mb=2048,
                      network=False, filesystem=False, pids=32),
        seed=node.seed,
        env={"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
    )

§5.2's control table gives the budget its own row — ``Timeout | Hard kill,
recorded as ``fail_class=timeout`` `` — and the *recording* half is what the
same table's other rows do not have: §9.1's ``node`` column is
``fail_class TEXT -- ok | timeout | error | tripwire_fail``, §8's ledger
carries the same four as ``outcome TEXT NOT NULL``, and §6.1 step 11 writes
the trial charge *"even if the node fails.  A failed evaluation still
consumed a hypothesis."*  The sentence decomposes into three claims, each
owned here as a seam rather than a comment:

* **a sandboxed run** — the subject, and the reason the law reads what it
  reads.  Not a service, a store or a policy: *one dispatch* of one signal,
  the same unit :class:`sandbox.isolation.SandboxRun` models for feature 157,
  :class:`sandbox.seed.SandboxInvocation` for feature 165 and the thread law's
  subject for feature 164.  The two things this law needs of that unit are its
  *elapsed wall time* and the *budget it was dispatched under* — which is why
  :class:`TimeoutRun` models exactly those two and deliberately not the whole
  call: the code, the payload, the seed and the env belong to other features,
  and a boundary that also modelled them would be a second, divergent copy of
  ``evaluator._sandbox``'s call shape — the mistake
  :class:`sandbox.isolation.SandboxRun` names for itself.

* **exceeded its 30 second wall clock budget** — the term, and the word that
  decides the reading.  The budget is §5.2's ``wall_s=30`` and it is
  *written down*: :data:`COMMITTED_TIMEOUT_POLICY` ships beside this module
  and the compiler refuses any other number, so "this deployment hard-kills at
  thirty seconds" is a fact about a file in the repository rather than a line
  in a runbook.  *Exceeded* is read strictly: a run that took exactly the
  budget did not exceed it, and the comparison is ``>`` rather than ``>=``
  because a boundary that killed a run at the instant it was still within its
  budget would be a law sharper than the one §5.2 states.  Nothing here
  *measures* time — the watchdog belongs to the runner that owns a process
  (``evaluator._sandbox``, whose ``subprocess.Popen(..., timeout=wall_s)`` and
  ``proc.kill()`` are the hard kill) — and the honest limit is stated below.

* **persists a timeout fail class** — the consequent, and the half §5.2's
  other control rows do not have.  A kill that left no row is a run nobody can
  account for: §6.1 step 11 charges the trial whether or not the node
  succeeded, and a charge that could not say how its trial ended is a hole in
  the honest ``K`` counter §8 makes the ledger.  So :func:`kill_timeout`
  answers with a :class:`TimeoutKill` — the fail class, the budget, the
  elapsed time, the sentence — and :func:`timed_out_record` writes that class
  onto a node record, refusing a record that already names a *different*
  terminal class rather than overwriting it (§9.1's column holds one value,
  and a kill recorded over an earlier crash would erase the first failure).

**The kill is a value, not a raise, and that is the feature.**  This is the
member's one law whose subject is *already a failure*: features 157, 164, 165
and 167 each refuse a run *before* anything executes, so their gates return
decisions and their launcher verbs raise.  A timeout happens *after* the box
was admitted and spawned, and the pipeline's contract for it is a recorded
outcome — §6.1 step 11's charge, feature 79's "a failed evaluation still
consumed a hypothesis", and :class:`evaluator.SandboxResult`, which returns
``fail_class="timeout"`` as a value and says in its own docstring that a
failed run "is a value, not an exception".  So :func:`kill_timeout` returns,
:meth:`SandboxTimeout.require` returns the kill, and the only refusals this
module raises are about the *recording*: an elapsed time that is not a number
of seconds, a budget that is not a positive number of seconds, a budget
document that cannot be read, a record this law cannot write onto.  A caller
that must not proceed re-raises the *sandbox's* own error, which is a fact
about the box rather than about this law — the argument
:mod:`sandbox.errors` states at length.

**The fail class this law persists is §8's ``timeout`` and never a synonym.**
The vocabulary the feature's sentence names is *"a timeout fail class"*, §9.1
spells it ``timeout`` in the column comment, and §8's ledger carries the same
four spellings — so :data:`TIMEOUT_FAIL_CLASS` is ``"timeout"`` and it is
restated here as *data* rather than imported from the ledger or the evaluator,
for the reason the member's whole error vocabulary is its own: the box
untrusted code is put inside must not depend on the member that drives it, and
a suite that imported the spelling would follow a rename rather than catch it.
The two spellings must agree, and this module's tests pin that they do.

**Why this control ships a committed artifact when features 165 and 166 do
not.**  :mod:`sandbox.transfer` and :mod:`sandbox.seed` state their reason for
having none — their subjects are a *format* and a *value a run is handed*, and
neither is a thing a deployment could set differently.  A wall budget is
neither: it is a number a deployment *writes down* and a watchdog enforces, so
there is a file, and the compiler holds it to §5.2's 30 seconds the way
feature 157's compiler holds every component to gVisor and feature 164's holds
every cap to one.  What the artifact does *not* carry is the other three
fields of the same ``Limits(...)`` call — ``cpu_s``, ``mem_mb``, ``pids`` —
because those are feature 162's cgroup law and the wall clock is this one's.

**Honest limits.**  This module is the *law about the budget*, not the
enforcement of it: it never spawns a process, never reads a clock, and cannot
see a child that outran its watchdog without a kill being reported to it.  The
hard kill itself is the runner's — ``evaluator._sandbox``'s wall-clock
watchdog (``communicate(timeout=wall_s)``, then ``proc.kill()``) and, beneath
it, the deployment's gVisor box — the same division feature 157 states between
its isolation policy and the ``runsc`` runtime that enforces it.  What holds
is that the committed budget cannot drift to another number without the
compile failing, that a reported kill cannot be recorded without naming §8's
class and the elapsed time that earned it, and that *what this deployment
kills at* is a value the policy carries and a caller can read
(:meth:`TimeoutPolicy.wall_s`) — so "we kill at thirty seconds" is a fact
about the deployment rather than a claim.

Stdlib-only, like the rest of the member: ``json`` for the artifact, and no
process, clock, network or container runtime anywhere.  The module is the law
and the caller supplies the elapsed time it measured.
"""

from __future__ import annotations

import enum
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .errors import (
    SandboxTimeoutError,
    TimeoutBudgetDocumentError,
)

__all__ = [
    "COMMITTED_TIMEOUT_POLICY",
    "DEFAULT_WALL_S",
    "NODE_FAIL_CLASSES",
    "TIMEOUT_COMPONENT_NAME",
    "TIMEOUT_FAIL_CLASS",
    "TIMEOUT_POLICY_KIND",
    "SandboxTimeout",
    "TimeoutDecision",
    "TimeoutKill",
    "TimeoutPolicy",
    "TimeoutReason",
    "TimeoutRecord",
    "TimeoutRun",
    "classify_duration",
    "committed_timeout_policy",
    "compile_timeout_policy",
    "exceeded_budget",
    "kill_timeout",
    "load_timeout_policy",
    "sandbox_timeout",
    "timed_out_record",
]

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, feature 167's ``sandbox-imports``, feature 166's
#: ``sandbox-transfer``, feature 165's ``sandbox-seed`` and feature 164's
#: ``sandbox-threads``, not instead of any of them: the factory's registry is
#: keyed by name and a later registration of the same name *replaces* the
#: earlier one, so a member carrying six controls carries six components, each
#: answering its own feature's question.
TIMEOUT_COMPONENT_NAME: Final[str] = "sandbox-timeout"

#: The marker a document declares itself with — the same discipline feature
#: 157's committed isolation artifact, feature 167's committed allowlist and
#: feature 164's committed pinning policy take, so a stray JSON file carrying
#: a ``wall_s`` key cannot be read as this policy.
TIMEOUT_POLICY_KIND: Final[str] = "sandbox-timeout"

#: The committed artifact, shipped beside the law that checks it, so a
#: checkout cannot hold one without the other.
COMMITTED_TIMEOUT_POLICY: Final[Path] = Path(__file__).with_name(
    "timeout_policy.json"
)

#: §5.2's budget, spelled once: thirty seconds.  A constant *and* the value the
#: committed artifact must carry — the compiler refuses any other — so the
#: number a watchdog kills at is checked rather than remembered.  Restated from
#: :data:`evaluator._sandbox.DEFAULT_WALL_S` rather than imported, for the
#: reason the module docstring gives: the sandbox member owns no dependency on
#: the member that drives it, and this suite pins the two agree.
DEFAULT_WALL_S: Final[float] = 30.0

#: The fail class this law persists — feature 163's own subject written as §9.1
#: spells it in the column comment and §8 spells it in the ledger's, and the
#: one spelling :mod:`evaluator._debit` maps to its own outcome.  Restated as
#: data rather than imported, and pinned by this suite, for the same
#: one-provenance reason :data:`DEFAULT_WALL_S` is.
TIMEOUT_FAIL_CLASS: Final[str] = "timeout"

#: The terminal classes a node record's ``fail_class`` column may hold, in
#: §9.1's declaration order: ``ok | timeout | error | tripwire_fail``.  Known
#: here for one reason — :func:`timed_out_record` refuses to write its class
#: over a record naming a *different* terminal class, and a refusal that could
#: not name the vocabulary it is protecting would send an operator looking for
#: a drift that is not there.  Feature 168 is the law that owns this
#: vocabulary from the sandbox side; this module knows it in order to leave the
#: other three values alone.
NODE_FAIL_CLASSES: Final[tuple[str, ...]] = (
    "ok",
    "timeout",
    "error",
    "tripwire_fail",
)

#: The names a node record may carry the terminal class under — the *name* the
#: class is persisted under, in the shapes §9.1's ``node`` row and the members'
#: own record objects both spell it.  ``fail_class`` first because that is
#: §9.1's column; the other two are the spellings the evaluator's and the
#: ledger's records use for the same fact.  A record naming the class under
#: none of these is one this law cannot write onto, which is a refusal rather
#: than a silent no-op: the feature's verb is *persists*.
_FAIL_CLASS_FIELDS: Final[tuple[str, ...]] = ("fail_class", "outcome", "terminal_class")

#: The types this law refuses *by name* because they look like a duration
#: without being one — a tuple rather than a frozenset because it is spent as
#: the second argument to :func:`isinstance`.  ``bool`` is listed even though
#: Python's ``bool`` *is* an ``int`` subclass: ``True`` is not a number of
#: seconds anyone meant to write, and accepting it would make a flag and a
#: duration indistinguishable — the exclusion :func:`sandbox.seed._classify`
#: and :func:`sandbox.threads.classify_cap` state for their own quantities.
#: The list is not exhaustive on purpose — the classifier also refuses any type
#: that is simply not a number — so it names the *near misses*, the ones whose
#: refusal gets its own sentence in :func:`_shape_consequence`.
_NOT_A_DURATION: Final[tuple[type, ...]] = (bool, str, bytes)


def _shape_consequence(value: Any) -> str:
    """The extra sentence for a declared duration of a type nothing reads as one."""
    kind = type(value).__name__
    if kind == "bool":
        return (
            " ``True`` is an ``int`` in Python and is deliberately not a "
            "duration: no watchdog reads a flag as a number of seconds, and "
            "accepting it would make a boolean and a budget indistinguishable."
        )
    if kind == "str":
        return (
            " A duration that arrived as text — the spelling an environment "
            "variable, a JSON document or a ``Limits`` field read off a "
            "manifest carries it in — is a different type in a different place "
            "from the float a watchdog compares against, and coercing it here "
            "would hide which side of that boundary the conversion was missing "
            "from."
        )
    if kind == "bytes":
        return (
            " Bytes are refused because no clock this law is written against "
            "reports its reading as bytes, and a value that is not a number "
            "would have to be decoded by this law to be compared by a "
            "watchdog — a conversion that belongs in whatever built the run."
        )
    return ""


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise TimeoutBudgetDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: {value!r}. "
            f"A wall-clock budget is a structured document, and a compiler "
            f"that guessed at the meaning of a stray list or string would be "
            f"writing policy rather than reading it — refused, fail closed "
            f"(feature 163)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise TimeoutBudgetDocumentError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). The budget a deployment kills at is "
            f"named, not inferred: a marker that is absent, blank or not a "
            f"string is one this policy cannot hold a run to, and 'unnamed' is "
            f"not 'thirty seconds' (feature 163, refused fail closed)."
        )
    return value


def classify_duration(value: Any) -> float | None:
    """Classify a value as a duration in seconds, or ``None``.

    The one place a duration is read — the compiler reads the committed
    artifact's budget through it, and :class:`TimeoutRun`'s elapsed time is
    checked through it — so a policy and a run cannot disagree about what a
    number of seconds is, the member's one-provenance rule applied to the one
    quantity this law owns.

    A genuine number is admitted whether it arrived as an ``int`` or a
    ``float``, because the two are the same measurement written two ways and
    refusing ``30`` while admitting ``30.0`` would be a law about typography.
    ``bool`` is excluded even though Python makes it an ``int``.  A text
    duration is refused rather than parsed: §5.2's ``Limits(wall_s=30, …)``
    passes a *number*, the watchdog compares against a number, and a
    ``"30s"`` that this law silently parsed would be this member inventing a
    grammar no runner reads.

    ``None`` for everything unplaceable — including a negative or non-finite
    value, which is a number and not a duration — because the *caller* decides
    which refusal that earns: a budget and an elapsed time are refused with
    different sentences and different repairs.
    """
    if value is None or isinstance(value, _NOT_A_DURATION):
        return None
    if not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    # A non-finite or negative reading is not a duration: ``NaN`` compares
    # false against every bound, so a budget admitted here would be one no run
    # could ever exceed, and a negative elapsed time is a clock that went
    # backwards rather than a run that finished early.  ``math.isfinite`` covers
    # ``NaN`` and both infinities in one test — and says the reason in words,
    # where ``x != x`` would be the same trick done quietly.
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


@dataclass(frozen=True)
class TimeoutPolicy:
    """A compiled wall-clock budget: the one number a run is killed past.

    What :func:`compile_timeout_policy` returns is not the document — it is the
    document *plus* the guarantee that the budget it declares is §5.2's thirty
    seconds.  Holders (the gate, a CI check that recompiles the committed
    artifact, an operator asking how long untrusted code may hold a core) cite
    that guarantee rather than re-derive it, which is why a kill's sentence can
    say "this deployment kills at the committed budget" and mean it.

    Under every compiled policy :attr:`wall_s` is :data:`DEFAULT_WALL_S`,
    because the compiler refuses anything else.  The field exists anyway —
    rather than the type being a bare constant — for the reason
    :class:`sandbox.isolation.ComponentIsolation` carries its mechanism and
    :class:`sandbox.threads.ThreadCap` carries its value: a caller asking *what
    does this deployment kill at?* reads a value rather than inferring it, and
    the gate compares a run against the declaration rather than against a
    module constant, so a hand-assembled policy carrying another number would
    be reported in the kill (itself the audit finding).
    """

    wall_s: float
    kind: str = TIMEOUT_POLICY_KIND

    def __post_init__(self) -> None:
        """Hold the one invariant the gate's sentences depend on: a duration.

        :func:`compile_timeout_policy` already refuses a bad number, so a
        policy built through the documented path cannot fail here.  This exists
        for the *undocumented* one the class's own docstring contemplates: the
        type is exported, its fields are public, and a hand-assembled policy is
        a path this member supports because "what does this deployment kill at?"
        should be readable rather than inferred from a constant.

        A caller that assembles one out of a string or a negative number is
        making the same mistake the compiler refuses, and the gate would
        otherwise fail *later* and *differently* — an ``f"{...:g}"`` on a
        string raises a bare ``ValueError`` from inside a refusal sentence,
        which is neither this member's greppable vocabulary nor a sentence an
        operator can act on.  So the shape is checked where the object is
        built, and the same :func:`classify_duration` the compiler and the gate
        read durations with is what checks it — one classifier, three seams.

        The *value* is deliberately not pinned to :data:`DEFAULT_WALL_S` here.
        A policy carrying another number is a legitimate hand-assembled object
        (the gate kills at whatever it was handed and says so — the audit
        finding), and it is the compiler's job, not the constructor's, to hold
        the committed artifact to §5.2's thirty.
        """
        if classify_duration(self.wall_s) is None:
            raise TimeoutBudgetDocumentError(
                f"{TIMEOUT_FAIL_CLASS}: a wall-clock policy was assembled with "
                f"wall_s = {self.wall_s!r} ({type(self.wall_s).__name__}), "
                f"which is not a number of seconds. §5.2's budget is a duration "
                f"a watchdog compares a run against "
                f"(``limits=Limits(wall_s={DEFAULT_WALL_S:g}, …)``), and a "
                f"policy holding anything else cannot answer *did this run "
                f"outrun its wall?* — the comparison has no defensible result "
                f"and the kill sentence has no number to name. The committed "
                f"artifact goes through :func:`compile_timeout_policy`, which "
                f"refuses this earlier and by name; this is the same refusal at "
                f"the seam a hand-built policy takes (feature 163)."
            )

    @property
    def milliseconds(self) -> float:
        """The same budget in milliseconds — for a caller sizing a watchdog."""
        return self.wall_s * 1000.0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"TimeoutPolicy(wall_s={self.wall_s!r}, kind={self.kind!r})"


def compile_timeout_policy(document: Any) -> TimeoutPolicy:
    """Compile a wall-clock budget, refusing one that is not §5.2's.

    The seam the whole feature turns on.  The document is read whole — marker,
    budget — and held to the law before a :class:`TimeoutPolicy` is handed
    out: it must declare itself :data:`TIMEOUT_POLICY_KIND`, and its ``wall_s``
    must be a genuine positive number of seconds equal to
    :data:`DEFAULT_WALL_S`.  A refusal propagates as an exception, so a caller
    cannot continue with a half-trusted budget: the document that would have
    let a run hold a core past thirty seconds is never applied, which is the
    compile-time half of "System persists a timeout fail class" — a kill at a
    number nobody wrote down is a kill an auditor cannot date.

    The value is checked through the *same* classifier the gate reads an
    elapsed time with (:func:`classify_duration`), so the document and the run
    cannot disagree about what a number of seconds is.  An absent ``wall_s`` is
    refused rather than defaulted: a compiler that read an absent budget as
    thirty seconds would be turning silence into the strongest promise the
    document makes, and §5.2's number is a *statement* a deployment makes, not
    a fallback it inherits.
    """
    doc = _require_mapping(document, "sandbox timeout policy document")
    marker = _require_str(doc.get("policy"), "sandbox timeout policy 'policy'")
    if marker != TIMEOUT_POLICY_KIND:
        raise TimeoutBudgetDocumentError(
            f"a sandbox timeout policy must declare itself "
            f"{TIMEOUT_POLICY_KIND!r}, got {marker!r}. A document that does not "
            f"say what it is cannot be trusted to say how long untrusted code "
            f"may hold a core, and a stray JSON file carrying a 'wall_s' key is "
            f"not this policy — refused, fail closed (feature 163)."
        )

    wall_s = doc.get("wall_s")
    if wall_s is None:
        raise TimeoutBudgetDocumentError(
            f"a sandbox timeout policy declares no 'wall_s'. §5.2's call site "
            f"passes ``limits=Limits(wall_s={DEFAULT_WALL_S:g}, …)`` and the "
            f"feature's own sentence names the budget; a compiler that read an "
            f"absent value as the default would be turning silence into the "
            f"strongest promise the document makes — 'unspecified' and 'killed "
            f"at {DEFAULT_WALL_S:g}s by law' are different promises, and only "
            f"the second is feature 163's (refused, fail closed)."
        )
    seconds = classify_duration(wall_s)
    if seconds is None:
        raise TimeoutBudgetDocumentError(
            f"a sandbox timeout policy declares wall_s = {wall_s!r} "
            f"({type(wall_s).__name__}), which is not a number of seconds. "
            f"§5.2's control table fixes the budget at "
            f"``wall_s={DEFAULT_WALL_S:g}`` — 'Timeout | Hard kill, recorded as "
            f"fail_class=timeout' — and a budget that is absent, blank, a "
            f"string, a flag or a negative number is one no watchdog can "
            f"compare a run against.{_shape_consequence(wall_s)} Refused "
            f"(feature 163)."
        )
    if seconds != DEFAULT_WALL_S:
        raise SandboxTimeoutError(
            f"{TIMEOUT_FAIL_CLASS}: the committed timeout policy declares "
            f"wall_s = {seconds!r}, and §5.2's call site passes "
            f"``wall_s={DEFAULT_WALL_S:g}`` with the feature's own sentence "
            f"naming the '30 second wall clock budget'. A budget other than "
            f"the committed one is a deployment that hard-kills a run at a "
            f"number nobody wrote down, and every stored ``fail_class=timeout`` "
            f"beside it dates a kill to a budget the file does not name. The "
            f"whole document is refused rather than the number quietly applied "
            f"(feature 163)."
        )
    return TimeoutPolicy(wall_s=seconds)


def load_timeout_policy(path: Path = COMMITTED_TIMEOUT_POLICY) -> TimeoutPolicy:
    """Read and compile a budget from disk, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly
    as a drift compiled in memory (feature 163).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise TimeoutBudgetDocumentError(
            f"could not read the sandbox timeout policy at {path}: {exc}. A "
            f"wall-clock budget that cannot be read is not a budget that kills "
            f"nothing gracefully — it is one whose deployment has no watchdog "
            f"law at all, and a caller that carried on would be running "
            f"agent-authored code with no bound on how long it may hold a core "
            f"while believing it was configured from this file (feature 163)."
        ) from exc
    except ValueError as exc:
        raise TimeoutBudgetDocumentError(
            f"the sandbox timeout policy at {path} is not valid JSON: {exc}. "
            f"Refused rather than read partially: a policy compiled from a "
            f"partially-parsed document is one whose file and whose watchdog "
            f"disagree (feature 163)."
        ) from exc
    return compile_timeout_policy(document)


def committed_timeout_policy() -> TimeoutPolicy:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 163's own tests hold to §5.2's budget, so "the deployment kills at
    thirty seconds" is a checked fact about a file in the repository rather
    than a claim in a runbook.
    """
    return load_timeout_policy(COMMITTED_TIMEOUT_POLICY)


class TimeoutRun:
    """One sandboxed run, as presented to the wall-clock law.

    Feature 163's sentence is about *a sandboxed run*, and §5.2 describes one
    as a call: the code, the payload, the limits, the seed, the env.  This
    models exactly the half of that call this law has a claim about — the
    elapsed wall time and the budget it was dispatched under — and deliberately
    does not model the rest: the code and payload are features 167's and 166's,
    the seed is 165's, the env is 164's, and a boundary that also modelled them
    would be a second, divergent copy of ``evaluator._sandbox``'s call shape,
    the mistake :class:`sandbox.isolation.SandboxRun` names for itself.

    **What it carries is what a watchdog measured, never a clock.**  Nothing in
    this module reads the time: the runner that owns the child process is the
    one that knows when it spawned and when it killed, so the elapsed seconds
    arrive as an argument — the same division that has feature 157's law read a
    run's *declared* isolation rather than dial a container runtime.  A law
    that called ``time.monotonic()`` here would be a second, disagreeing
    measurement of a duration the runner already measured.

    ``elapsed_s`` is taken as given and is *not* required to exceed the budget:
    a caller describing a run that finished inside it is the case
    :meth:`SandboxTimeout.check` admits, and the refusal for a malformed
    duration fires there rather than at construction — the shape the member's
    other laws take, so the caller that most needs to be told its run is
    undescribable can hold the run to be told.

    **``budget_s`` is a record, not a leash.**  A run may say which budget it
    was dispatched under, and :func:`kill_timeout` reports a disagreement with
    the committed number — but the number that *kills* is always the compiled
    policy's (:meth:`SandboxTimeout.wall_s`).  Passing ``budget_s`` here is how
    a runner records what it believed; it is not a way to widen the bound the
    watchdog enforces, and passing a huge one changes nothing about the verdict.
    A run with nothing to record leaves it at :data:`DEFAULT_WALL_S`.
    """

    __slots__ = ("budget_s", "component", "elapsed_s", "node_id")

    def __init__(
        self,
        *,
        elapsed_s: Any,
        budget_s: Any = DEFAULT_WALL_S,
        node_id: str = "",
        component: str = "",
    ) -> None:
        self.elapsed_s = elapsed_s
        self.budget_s = budget_s
        self.node_id = node_id
        self.component = component

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TimeoutRun(elapsed_s={self.elapsed_s!r}, "
            f"budget_s={self.budget_s!r}, node_id={self.node_id!r}, "
            f"component={self.component!r})"
        )


def exceeded_budget(elapsed_s: Any, budget_s: Any) -> bool:
    """Whether an elapsed time exceeded a budget — strictly, or ``False``.

    The feature's word is *exceeded*, and the comparison is therefore ``>``
    rather than ``>=``: a run that took exactly its budget did not exceed it,
    and a law that killed at the instant the budget was still satisfied would
    be sharper than §5.2's row.  The boundary is the whole reason this is a
    named function rather than an inline comparison — it is the one place the
    feature's verb is interpreted, and a reader asking *when exactly do we
    kill?* should be able to read the answer rather than infer it.

    ``False`` for anything not classifiable as a duration, on both sides: a
    comparison between two values that are not numbers of seconds has no
    defensible answer, and :meth:`SandboxTimeout.check` is where such a run is
    refused by name.  This function answers the arithmetic question only, so a
    caller using it directly is never surprised by a raise.
    """
    elapsed = classify_duration(elapsed_s)
    budget = classify_duration(budget_s)
    if elapsed is None or budget is None:
        return False
    return elapsed > budget


class TimeoutReason(enum.StrEnum):
    """Why a run was killed or spared — the audit vocabulary.

    One enumeration carries the kill and the pass-through, for the reason
    :class:`sandbox.isolation.RunReason`, :class:`sandbox.seed.SeedReason` and
    :class:`sandbox.threads.ThreadReason` do: a decision's reason is one fact
    with two polarities and the audit line should read the same either way —
    ``within-budget`` names the fact the run was admitted on, and the refusals
    name what was found instead.
    """

    #: The run finished inside its budget: nothing to kill and nothing to
    #: record.  The pass-through, and the reason a caller that only wants the
    #: kill reads ``.killed`` rather than parsing a sentence.
    WITHIN_BUDGET = "within-budget"

    #: Killed: the run exceeded the budget it was dispatched under, and the
    #: fail class §8 names for that is :data:`TIMEOUT_FAIL_CLASS`.  The
    #: feature's headline, and the one reason here that is *not* a refusal in
    #: the member's other laws' sense — nothing was rejected before it ran;
    #: the box ran, outran its wall, and was hard-killed.
    EXCEEDED_BUDGET = "exceeded-wall-budget"

    #: Refused: the subject is not a run this law can read — not a
    #: :class:`TimeoutRun` and not an object carrying an elapsed time and a
    #: budget.  A refusal rather than a raise, like the other laws' gates',
    #: because the caller that has been handed the wrong object still needs to
    #: be told *which* one it was.
    UNREADABLE_SUBJECT = "unreadable-subject"

    #: Refused: the elapsed time (or the budget) is not a number of seconds —
    #: absent, text, bytes, a flag, negative, non-finite.  Its own reason
    #: because the repair is different from the last one: the caller has the
    #: right *object* and the wrong *measurement*, and what produced that
    #: number is where the operator has to look.
    MALFORMED_DURATION = "malformed-duration"


class TimeoutKill:
    """One hard-killed run: the fail class, the budget, and the time that earned it.

    Feature 163's *persists a timeout fail class* half as a value — what a
    caller hands the tree store's ``fail_class`` column (§9.1) and the trial
    ledger's ``outcome`` (§8), and what an operator reads a month later to ask
    *why did this node die?*

    **Returned rather than raised**, necessarily rather than by preference:
    §5.2's kill has no exception to be, because the pipeline persists a failed
    run as an outcome (feature 79: "a failed evaluation still consumed a
    hypothesis") and :class:`evaluator.SandboxResult` already returns its kills
    as values.  So this object *is* the answer to "did the run time out?" and a
    raise here would be a second, disagreeing spelling of a fact the runner
    already recorded.

    ``elapsed_s`` and ``budget_s`` are carried beside the class for the reason
    §9.1's row is not the only place the failure lands: a bare ``"timeout"``
    says a run died at the wall, and *by how much* is what tells an operator
    whether the budget is wrong or the signal is — the two repairs a reader
    cannot choose between from the class alone.
    """

    __slots__ = ("budget_s", "component", "detail", "elapsed_s", "node_id")

    def __init__(
        self,
        *,
        elapsed_s: float,
        budget_s: float,
        detail: str,
        node_id: str = "",
        component: str = "",
    ) -> None:
        self.elapsed_s = elapsed_s
        self.budget_s = budget_s
        self.detail = detail
        self.node_id = node_id
        self.component = component
        # A kill that did not outrun its budget is a contradiction, and it is
        # the one this object cannot survive being read back: ``overrun_s``
        # would be negative, so *"this run died at the wall"* and *"this run
        # finished early"* would be the same record.  ``kill_timeout`` never
        # builds one — it kills on a strict ``>`` — and the check is here rather
        # than only there because this class is exported: a caller assembling a
        # kill by hand, or a store row being rebuilt into one, would otherwise
        # get a `fail_class=timeout` for a run that was never hard-killed, which
        # is exactly the fabricated outcome the whole feature exists to prevent.
        if classify_duration(elapsed_s) is None or classify_duration(budget_s) is None:
            raise SandboxTimeoutError(
                f"{TIMEOUT_FAIL_CLASS}: a kill was assembled with "
                f"elapsed_s = {elapsed_s!r} and budget_s = {budget_s!r} "
                f"({type(elapsed_s).__name__}, {type(budget_s).__name__}), at "
                f"least one of which is not a number of seconds. A kill is a "
                f"*record of a measurement* — §5.2's hard kill and the time that "
                f"earned it — so it can no more be built from a value no "
                f"watchdog could have produced than a run can outrun a budget it "
                f"cannot compare against (feature 163)."
            )
        if elapsed_s <= budget_s:
            raise SandboxTimeoutError(
                f"{TIMEOUT_FAIL_CLASS}: a kill was assembled for a run that did "
                f"not exceed its budget (elapsed_s = {elapsed_s!r}, "
                f"budget_s = {budget_s!r}). This object means *a run died at the "
                f"wall* — §5.2's 'Timeout | Hard kill, recorded as "
                f"fail_class={TIMEOUT_FAIL_CLASS}' — and one built for a run "
                f"that finished within its budget would persist that class for a "
                f"kill nobody performed, with a negative overrun beside it. "
                f"Refused rather than recorded: a fabricated timeout is as wrong "
                f"as a missing one (feature 163)."
            )

    @property
    def fail_class(self) -> str:
        """The class this kill persists — §8's ``timeout``, always."""
        return TIMEOUT_FAIL_CLASS

    @property
    def overrun_s(self) -> float:
        """How far past its budget the run went, in seconds.

        Strictly positive, and that is now an invariant of the object rather
        than a statement about how it is usually built: the constructor refuses
        a pair that does not exceed, so this subtraction is exact and its sign
        is known — the one thing a reader of a persisted kill can rely on
        without re-deriving the comparison.
        """
        return self.elapsed_s - self.budget_s

    def row(self) -> dict[str, Any]:
        """The kill as a store-shaped mapping — what a caller writes down.

        ``fail_class`` under §9.1's own column name, with the two durations
        beside it and the node identity when one was given, so a caller that
        wants to persist the outcome reads the mapping rather than assembling
        the same three keys itself — the same "hand out the shape the store
        wants" discipline :meth:`sandbox.seed.SeedDecision.seed_env` applies to
        the seed's transport.  A fresh dict per call, never a shared one.
        """
        row: dict[str, Any] = {
            "fail_class": TIMEOUT_FAIL_CLASS,
            "elapsed_s": self.elapsed_s,
            "budget_s": self.budget_s,
        }
        if self.node_id:
            row["node_id"] = self.node_id
        return row

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TimeoutKill(fail_class={TIMEOUT_FAIL_CLASS!r}, "
            f"elapsed_s={self.elapsed_s!r}, budget_s={self.budget_s!r}, "
            f"node_id={self.node_id!r})"
        )


class TimeoutDecision:
    """The gate's whole answer: killed or not, why, and in what words.

    ``killed`` is the one field a caller must check, and it is *computed* from
    the classified durations rather than set by a constant — the same
    "computed, never assumed" stance :class:`sandbox.isolation.RunDecision`,
    :class:`sandbox.seed.SeedDecision` and
    :class:`sandbox.threads.ThreadDecision` take.  ``kill`` is the
    :class:`TimeoutKill` for a run that exceeded its budget and ``None``
    otherwise, so a caller reading ``decision.kill`` after checking ``killed``
    has the object rather than a sentinel.

    ``refused`` is deliberately separate from ``killed``, and the distinction
    is the feature: a run that finished inside its budget and a run this law
    could not *read* are both ``killed=False``, and only the second is a
    failure of this member.  A caller that read ``not decision.killed`` as
    "the run was fine" would treat an unreadable subject as a clean run — the
    "absence that reads as a result" failure this member's transfer law states
    for its own missing vector.
    """

    __slots__ = ("detail", "kill", "reason")

    def __init__(
        self,
        *,
        reason: TimeoutReason,
        detail: str,
        kill: TimeoutKill | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.kill = kill

    @property
    def killed(self) -> bool:
        """Whether the run exceeded its budget and was killed.

        The gate's headline, and true only for
        :attr:`TimeoutReason.EXCEEDED_BUDGET` — a refusal is not a kill, which
        is the property :meth:`require` and :attr:`refused` are built on.
        """
        return self.kill is not None

    @property
    def refused(self) -> bool:
        """Whether this law could not read the run at all.

        The reasons the subject or its measurement was unreadable — never
        :attr:`EXCEEDED_BUDGET
        <sandbox.timeout.TimeoutReason.EXCEEDED_BUDGET>`, which is a kill rather
        than a refusal, and never :attr:`WITHIN_BUDGET
        <sandbox.timeout.TimeoutReason.WITHIN_BUDGET>`, which is a clean run.
        """
        return self.reason in (
            TimeoutReason.UNREADABLE_SUBJECT,
            TimeoutReason.MALFORMED_DURATION,
        )

    def require(self) -> TimeoutKill | None:
        """Return the kill, or raise the refusal; ``None`` if the run was fine.

        The bridge between the gate's returned answer and the exception a
        caller wants on the line after the spawn.  Its shape is the one place
        this member's launcher verbs differ, and the difference is the feature:
        the other laws' ``require`` returns a value on success and raises on
        refusal, while this one has *three* outcomes, because a timeout law's
        commonest answer is neither.  So a run inside its budget returns
        ``None`` — nothing was killed, nothing to persist — and only an
        *unreadable* run raises :class:`~sandbox.errors.SandboxTimeoutError`.

        A kill is returned rather than raised, necessarily: §5.2's kill is the
        pipeline's recorded outcome (feature 79), and a law that raised it
        would make every timed-out node a crashed evaluator.  A caller that
        wants the refusal for a kill too calls ``require()`` and then re-raises
        on ``not None`` — the caller's choice, made explicitly, rather than a
        shape this law imposes on every dispatch.
        """
        if self.refused:
            raise SandboxTimeoutError(self.detail)
        return self.kill

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TimeoutDecision(reason={self.reason!r}, killed={self.killed}, "
            f"refused={self.refused})"
        )


class TimeoutRecord:
    """One node's terminal class as it was persisted — the write's receipt.

    ``node_id`` is the node written to; ``superseded`` is the class the record
    named before, or ``None`` for a first write.  The history is carried for
    the reason :class:`sandbox.seed.SeedRecord` carries its own: a *record*
    holds one terminal class — that is what §9.1's column is — so the receipt
    is where the fact "this record already said something else" survives.
    Writing the *same* class over itself is not a supersession and reports
    ``None``, because an idempotent write — a retried kill, a re-persisted
    outcome — is not news, and reporting it as a change would make every retry
    look like a rewritten history.
    """

    __slots__ = ("field", "node_id", "superseded", "written")

    def __init__(
        self,
        *,
        node_id: str,
        written: str = TIMEOUT_FAIL_CLASS,
        superseded: str | None = None,
        field: str = _FAIL_CLASS_FIELDS[0],
    ) -> None:
        self.node_id = node_id
        self.written = written
        self.superseded = superseded
        self.field = field

    @property
    def overwrote(self) -> bool:
        """Whether this write replaced a different terminal class."""
        return self.superseded is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TimeoutRecord(node_id={self.node_id!r}, field={self.field!r}, "
            f"written={self.written!r}, superseded={self.superseded!r})"
        )


def kill_timeout(run: object, policy: TimeoutPolicy) -> TimeoutDecision:
    """Answer one run: killed with §8's class, or within its budget.

    The gate, and the one place the law is actually applied — every other verb
    in this module (:meth:`SandboxTimeout.check`, :meth:`TimeoutDecision.require`)
    reaches this function rather than re-deciding.  Nothing is raised for a
    *kill*: the box ran and outran its wall, which is an outcome the pipeline
    persists (§6.1 step 11, feature 79), and a gate that raised would turn one
    hung signal into a crashed evaluator over thousands of unattended
    candidates.  What it does refuse — as a decision, worded by reason — is a
    subject it cannot read.

    The comparison is against the *policy's* declared budget rather than
    against :data:`DEFAULT_WALL_S`, so a kill is the compiled declaration
    arriving at its answer and a hand-assembled policy carrying another number
    would kill at that number and say so in the sentence (itself the audit
    finding).

    **The run's own ``budget_s``, when it carries one, never decides.**  It is
    read as a *record* — what the dispatch believed it was sent under — and
    reported in the sentence when it disagrees with the committed number, which
    means this dispatch did not go through this law.  It is deliberately not the
    number compared against: a run judged by its own declared budget could
    widen its own leash (``budget_s=1e9`` would put the watchdog's kill out of
    reach while every line of the configuration still looked enforced), and
    that is the one way this feature could be turned against itself.  A subject
    carrying **no** ``budget_s`` is the ordinary case and says nothing — there
    is no record to disagree with.
    """
    # Two refusals, told apart by *what was found*, not by what type the
    # subject happens to be: an object naming no elapsed time at all is a
    # different failure from one naming a time that is not a number of seconds,
    # and the two have different repairs (look at the caller's record type;
    # look at whatever produced the number).  Keying this on ``isinstance(...)``
    # would classify every duck-typed subject's *malformed* duration as an
    # unreadable one — the wrong diagnosis, and the wrong sentence to an
    # operator.
    if not hasattr(run, "elapsed_s"):
        return TimeoutDecision(
            reason=TimeoutReason.UNREADABLE_SUBJECT,
            detail=(
                f"{TIMEOUT_FAIL_CLASS}: a sandboxed run was offered to the "
                f"wall-clock gate carrying no elapsed time at all "
                f"(got {type(run).__name__}: {run!r}). §5.2 dispatches every run "
                f"with a ``limits=Limits(wall_s=…, …)`` clause and a watchdog "
                f"that measures against it, and the law's whole subject is the "
                f"duration that watchdog measured; a run described as anything "
                f"else cannot be asked whether it outran its budget, and "
                f"'unreadable' is not 'within budget'. The run is not killed "
                f"(feature 163)."
            ),
        )

    elapsed = _subject_duration(run, "elapsed_s")
    if elapsed is None:
        return TimeoutDecision(
            reason=TimeoutReason.MALFORMED_DURATION,
            detail=_malformed_duration_refusal(run),
        )

    # **The budget is the policy's, never the run's.**  This is the one place
    # feature 163 could be turned against itself: §5.2's `Limits(wall_s=30)` is
    # a *declaration*, and a run that carried its own budget and were judged by
    # it could widen its own leash — `budget_s=1e9` would make the watchdog's
    # hard kill unreachable while every line of the law still looked enforced.
    # So the number that kills is the compiled declaration, and what the run
    # says it was dispatched under is a *record* — reported below when it
    # disagrees, because a run dispatched past the committed budget is a
    # dispatch that did not go through this law, which is an audit finding
    # rather than grounds to re-judge the run by the caller's own number.
    budget = policy.wall_s
    declared = _subject_duration(run, "budget_s")
    mismatch = (
        ""
        if declared is None or declared == budget
        else (
            f" Note that the run records being dispatched under a "
            f"{declared:g}s budget while this deployment's committed budget is "
            f"{budget:g}s — the law judges against the committed number, and the "
            f"disagreement means this dispatch did not go through it."
        )
    )

    if elapsed <= budget:
        return TimeoutDecision(
            reason=TimeoutReason.WITHIN_BUDGET,
            detail=(
                f"run of component {getattr(run, 'component', '')!r} finished "
                f"in {elapsed:g}s, inside its {budget:g}s wall-clock budget: "
                f"nothing was killed and no fail class is persisted. §5.2's "
                f"control table kills only a run that *exceeded* its budget "
                f"('Timeout | Hard kill, recorded as fail_class="
                f"{TIMEOUT_FAIL_CLASS}'), and a run that took exactly its "
                f"budget did not exceed it (feature 163).{mismatch}"
            ),
        )

    node = getattr(run, "node_id", "")
    return TimeoutDecision(
        reason=TimeoutReason.EXCEEDED_BUDGET,
        kill=TimeoutKill(
            elapsed_s=elapsed,
            budget_s=budget,
            node_id=node if isinstance(node, str) else "",
            component=_subject_component(run),
            detail=(
                f"{TIMEOUT_FAIL_CLASS}: the sandboxed run of component "
                f"{_subject_component(run)!r} ran {elapsed:g}s against a "
                f"{budget:g}s wall-clock budget and was hard-killed, "
                f"{elapsed - budget:g}s past it. §5.2's control table is "
                f"'Timeout | Hard kill, recorded as fail_class="
                f"{TIMEOUT_FAIL_CLASS}', §9.1's node column is 'fail_class TEXT "
                f"-- ok | timeout | error | tripwire_fail', and §6.1 step 11 "
                f"charges the trial even so ('A failed evaluation still "
                f"consumed a hypothesis') — so this kill is an outcome to "
                f"persist rather than an exception to raise (feature 163)."
                f"{mismatch}"
            ),
        ),
        detail=(
            f"{TIMEOUT_FAIL_CLASS}: the run of component "
            f"{_subject_component(run)!r} exceeded its {budget:g}s wall-clock "
            f"budget ({elapsed:g}s elapsed); it is hard-killed and recorded "
            f"with the fail class {TIMEOUT_FAIL_CLASS!r} (feature 163)."
            f"{mismatch}"
        ),
    )


def _malformed_duration_refusal(run: object) -> str:
    """The refusal for a run whose elapsed time is not a number of seconds."""
    return (
        f"{TIMEOUT_FAIL_CLASS}: a sandboxed run "
        f"({_subject_component(run)!r}) was offered to the wall-clock gate with "
        f"an elapsed time of {_subject_raw(run, 'elapsed_s')!r}, which is not a "
        f"number of seconds. The budget feature 163 kills against is a duration "
        f"from a watchdog's own measurement — §5.2's "
        f"``limits=Limits(wall_s={DEFAULT_WALL_S:g}, …)`` — and a run whose "
        f"elapsed time is absent, text, a flag or a negative number cannot be "
        f"asked whether it outran anything. Refused rather than killed and "
        f"rather than counted as within budget: 'unmeasurable' is not 'within "
        f"budget', and a node whose timeout went unrecorded is exactly the "
        f"failure this feature exists to prevent (feature 163)."
    )


def _subject_raw(subject: object, field: str) -> Any:
    """The value ``subject`` carries under ``field``, or ``None``."""
    if isinstance(subject, TimeoutRun):
        return getattr(subject, field, None)
    return getattr(subject, field, None)


def _subject_duration(subject: object, field: str) -> float | None:
    """The duration ``subject`` carries under ``field``, or ``None``.

    The one reader of a run's two quantities, so the gate and the refusal
    sentences cannot disagree about what was found.  Reads a
    :class:`TimeoutRun` and any object carrying the attribute, because the
    caller's own record type may describe a run this law should still be able
    to judge — the same tolerance :func:`sandbox.threads._subject_environment`
    extends to the shapes an invocation arrives in.  ``None`` for anything not
    classifiable as a duration; the *gate* decides which refusal that earns.
    """
    return classify_duration(getattr(subject, field, None))


def _subject_component(subject: object) -> str:
    """The component name ``subject`` names, or ``""`` — for a refusal's prose."""
    component = getattr(subject, "component", "")
    return component if isinstance(component, str) else ""


def _record_fail_class(record: Any, node_id: str) -> tuple[str | None, str | None]:
    """Read what terminal class a record names — ``(value, field)``.

    Two answers travel back, and the second is not decoration: ``field`` is the
    name the class was found *under* (or the name a null one sits under), and
    :func:`_write_fail_class` writes back to that same field so a record keeps
    its own shape.  ``(None, None)`` means the record names no such field at
    all — a fresh row — and the write then uses §9.1's canonical name.

    Reads a mapping or an object, because the two shapes both occur in this
    repository: §9.1's ``node`` row arrives from a relational driver as a
    mapping, while the members' own record objects carry the field as an
    attribute.  A record of neither shape names no class, which is the honest
    answer rather than a type error: the caller asked *what does this record
    already say?* and "nothing" answers it.

    **A field present but ``None`` is not the same as an absent one.**  §9.1's
    column is declared ``fail_class TEXT,`` — nullable — so a row straight from
    a driver carries the *key* with a null value on every unevaluated node.
    That is the ordinary case this verb exists for, and it must be reported as
    "nothing yet, under ``fail_class``" rather than as "no such field", or the
    receipt would tell an auditor the write landed nowhere.

    A value under one of :data:`_FAIL_CLASS_FIELDS` that is **not** one of
    §9.1's four terminal classes is refused by name rather than passed over:
    the column holds one closed vocabulary, and a record carrying something
    else is one this law cannot honestly compare against — a caller told "no
    class" would write ``timeout`` over whatever was there.  That refusal is
    right for feature 161's ``sandbox_escape`` too, which is a genuine seccomp
    verdict and is *not* one of §9.1's four: this law refuses to overwrite it
    rather than translating one failure into another.
    """
    first_present: str | None = None
    for field in _FAIL_CLASS_FIELDS:
        if isinstance(record, Mapping):
            present = field in record
            value = record.get(field, None)
        else:
            present = hasattr(record, field)
            value = getattr(record, field, None) if present else None
        if not present:
            continue
        if first_present is None:
            first_present = field
        if value is None:
            # Null, not absent: keep looking in case a sibling spelling carries
            # the real class, but remember where a null one sits.
            continue
        if value not in NODE_FAIL_CLASSES:
            known = ", ".join(repr(cls) for cls in NODE_FAIL_CLASSES)
            raise SandboxTimeoutError(
                f"{TIMEOUT_FAIL_CLASS}: the node record for {node_id!r} carries "
                f"{field} = {value!r} ({type(value).__name__}), which is not "
                f"one of the terminal classes §9.1's column declares ({known}). "
                f"A timeout is about to be recorded beside it, and a record "
                f"whose existing class this law cannot read is one it cannot "
                f"honestly compare against — writing over an unreadable value "
                f"would erase a failure nobody can now name. Refused rather "
                f"than compared (feature 163)."
            )
        return value, field
    return None, first_present


def timed_out_record(
    record: Any, *, node_id: str | None = None
) -> TimeoutRecord:
    """Persist the timeout class onto a node record — feature 163's verb.

    Given a mutable mapping or object — §9.1's ``node`` row, a member's own
    record — this writes :data:`TIMEOUT_FAIL_CLASS` under the field the record
    already names (§9.1's ``fail_class`` for a fresh record) and returns the
    :class:`TimeoutRecord` saying what was written and what it replaced.

    **A record naming a different terminal class is refused, not overwritten.**
    This is the one judgement in the module that could reasonably have gone the
    other way, and it goes this way for the reason
    :func:`sandbox.seed.seed_record` refuses to overwrite a node's seed: a
    record holds *one* value — that is what §9.1's column is — and the two
    statements it could carry are about two different failures.  A node that
    died a ``tripwire_fail`` at step 10 and is later recorded as a ``timeout``
    is a node whose subtree quarantine (§17's row) has been erased by a
    timestamp, and a node that *crashed* and is rewritten as a timeout is one
    whose real fault is now unfindable.  So the write refuses and names both
    classes.  Re-persisting the *same* class is not a contradiction and is
    idempotent — it reports ``superseded=None``, because a retried kill is not
    news.

    A record naming *no* class at all is not a contradiction either: an
    unevaluated node has no outcome yet, and filling it in is exactly what this
    verb is for.
    """
    node = node_id if node_id is not None else _record_node_id(record)
    existing, field = _record_fail_class(record, node)

    if existing is not None and existing != TIMEOUT_FAIL_CLASS:
        raise SandboxTimeoutError(
            f"{TIMEOUT_FAIL_CLASS}: the node record for {node!r} already names "
            f"{field} = {existing!r}, and the run to be recorded was hard-killed "
            f"at its wall-clock budget. §9.1's column holds one terminal class "
            f"per node — 'ok | timeout | error | tripwire_fail' — and a record "
            f"rewritten from {existing!r} to {TIMEOUT_FAIL_CLASS!r} erases the "
            f"failure it already described: a quarantined seccomp violation "
            f"that reads as a timeout, a crash that reads as a hang. Refused "
            f"rather than overwritten; re-persist the same class, or record "
            f"this kill on the run it belongs to (feature 163)."
        )

    _write_fail_class(record, field)
    return TimeoutRecord(
        node_id=node,
        written=TIMEOUT_FAIL_CLASS,
        superseded=(
            existing
            if existing is not None and existing != TIMEOUT_FAIL_CLASS
            else None
        ),
        field=_fail_class_target(field),
    )


def _fail_class_target(field: str | None) -> str:
    """The field name the class is written to — the one place that decides.

    ``field`` is what :func:`_record_fail_class` found the record naming, and
    ``None`` means it named none of them at all.  Both the write
    (:func:`_write_fail_class`) and the receipt (:func:`timed_out_record`) read
    the target through *this* function rather than each doing its own
    ``field or _FAIL_CLASS_FIELDS[0]``: two spellings of one decision is how a
    receipt comes to report a field the write never touched, which is exactly
    the bug this exists to prevent — a fresh §9.1 row is written
    ``fail_class`` while an unaudited receipt says ``None``.
    """
    return field if field is not None else _FAIL_CLASS_FIELDS[0]


def _write_fail_class(record: Any, field: str | None) -> None:
    """Write the timeout class onto a record under §9.1's own column name.

    The field is the one the record already names — ``outcome`` on the
    ledger's own row shape, ``fail_class`` on a §9.1 node row — and a fresh
    record takes :data:`_FAIL_CLASS_FIELDS`\\ [0], both decided by
    :func:`_fail_class_target` so the receipt cannot name a different field
    from the one this wrote.  A mapping takes the key; an object with the
    attribute is set the way the object allows — ``setattr`` for the plain
    dataclasses this repository's stores return, and a refusal by name for
    anything else, since a record this law cannot write is a record whose
    timeout will not be persisted and a caller has to hear that rather than
    infer it from a silent no-op.
    """
    target = _fail_class_target(field)
    if isinstance(record, dict):
        record[target] = TIMEOUT_FAIL_CLASS
        return
    if isinstance(record, Mapping):
        try:
            record[target] = TIMEOUT_FAIL_CLASS  # type: ignore[index]
            return
        except TypeError as exc:
            raise SandboxTimeoutError(
                f"{TIMEOUT_FAIL_CLASS}: the node record is an immutable mapping "
                f"({type(record).__name__}), so the class "
                f"{TIMEOUT_FAIL_CLASS!r} cannot be persisted on it. Feature "
                f"163's verb is *persists*; a record that refuses the write "
                f"would report a persistence that never happened (feature "
                f"163)."
            ) from exc
    try:
        setattr(record, target, TIMEOUT_FAIL_CLASS)
    except (AttributeError, TypeError) as exc:
        raise SandboxTimeoutError(
            f"{TIMEOUT_FAIL_CLASS}: the node record ({type(record).__name__}) "
            f"cannot carry a persisted fail class — it takes neither a "
            f"{target!r} key nor a {target!r} attribute. §9.1's column is where "
            f"the timeout has to land for the kill to be accountable, and this "
            f"law refuses to report a persistence it could not perform "
            f"(feature 163)."
        ) from exc


def _record_node_id(record: Any) -> str:
    """The node id a record names — for a refusal's message, not for a key.

    Best-effort by design: this is read while building an error message, and a
    record that names no id must still produce a readable refusal rather than a
    second failure inside the first.  Every identifier field the repository's
    node shapes use is tried, and an unidentified record is reported as such.
    """
    for field in ("node_id", "id", "node"):
        if isinstance(record, Mapping):
            value = record.get(field, None)
        else:
            value = getattr(record, field, None)
        if isinstance(value, str) and value.strip():
            return value
    return "<unidentified node>"


class SandboxTimeout:
    """Feature 163's law, as the value a composed application carries.

    A stateless facade over this module and the committed budget it compiled —
    the same shape :class:`sandbox.SandboxIsolation` gives feature 157,
    :class:`sandbox.SandboxImports` 167, :class:`sandbox.SandboxTransfer` 166,
    :class:`sandbox.SandboxSeed` 165 and :class:`sandbox.SandboxThreads` 164 —
    so a caller holding the composed component can ask the feature's question,
    *did this run outrun its wall-clock budget, and if so what do I persist?*,
    without importing the member's submodules by name or re-reading the
    artifact.

    **It carries no clock, no process and no deadline.**  A component shared
    across runs that held a watchdog — or that started a timer when it was
    built — would be one measuring a duration that belongs to a single run, the
    property :class:`sandbox.SandboxTransfer` states for its channel and
    :class:`sandbox.SandboxSeed` for its seed, in a quantity measured in
    seconds.  What it carries is the compiled budget: one number, and the
    guarantee that it is §5.2's.

    **``require`` returns the kill, and that is deliberately not the shape the
    other five laws' launcher verbs take.**  Those return a value on success
    and raise on refusal, because their subjects are refused *before* they run.
    A timeout law's commonest answer is neither: the run finished, or it was
    killed — and the kill is an outcome the pipeline persists, not an exception
    it survives.  So :meth:`require` returns ``None`` for a run inside its
    budget, a :class:`TimeoutKill` for a run that outran it, and raises only
    when the *run it was handed* is unreadable.  A caller that wants every kill
    raised re-raises on ``not None``, and that choice stays the caller's.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the comparison or the record
    write here would be a second thing to keep in sync, and the member's
    one-provenance rule exists so that cannot happen.
    """

    __slots__ = ("_policy",)

    def __init__(self, policy: TimeoutPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> TimeoutPolicy:
        """The compiled wall-clock budget this component carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator asking how long untrusted code may hold a core — reads the
        budget rather than re-deriving it.  Reading it does not widen anything:
        the policy holds no capability, which is the point of the component
        being a facade rather than a watchdog.
        """
        return self._policy

    @property
    def wall_s(self) -> float:
        """The budget this deployment hard-kills past, in seconds."""
        return self._policy.wall_s

    def check(self, subject: object) -> TimeoutDecision:
        """Answer whether ``subject`` outran its budget — the gate, as a value.

        ``subject`` is a :class:`TimeoutRun` or any object carrying
        ``elapsed_s`` (and optionally ``budget_s``), which is how a caller's
        own run record can be judged without being re-described.  The process's
        own clock is deliberately not consulted: this law reads what a watchdog
        measured, so a test never depends on how fast the machine that started
        pytest is.
        """
        return kill_timeout(subject, self._policy)

    def killed(self, subject: object) -> bool:
        """Whether ``subject`` was killed at its wall — the one boolean.

        The convenience for the caller that does not want the decision: the
        same computation, read at its headline.  A *refused* run is not killed,
        which is what :attr:`TimeoutDecision.refused` is for — a caller that
        branches on this alone has asked only the arithmetic question.
        """
        return self.check(subject).killed

    def require(self, subject: object) -> TimeoutKill | None:
        """Return the kill, raise on an unreadable run, ``None`` if it was fine.

        The launcher's verb, and the one shape in this member that is not
        "value on success, raise on refusal" — see the class docstring for why
        a timeout law cannot have that shape.  Put on the line after the spawn,
        it makes *"a run that outran its wall is hard-killed and recorded with
        the timeout fail class"* enforced there rather than remembered.
        """
        return self.check(subject).require()

    def record(self, record: Any, *, node_id: str | None = None) -> TimeoutRecord:
        """Persist the timeout class onto a node record — ``timed_out_record``.

        The second half of the feature's sentence, reachable from the composed
        component: a caller that has a kill calls this with the node record it
        is about to write and gets back what landed, or the refusal for a
        record that already names a different terminal class.
        """
        return timed_out_record(record, node_id=node_id)

    def exceeds(self, elapsed_s: Any) -> bool:
        """Whether an elapsed time outran this deployment's committed budget.

        The read side, for a caller holding only a duration — a runner that
        wants the boundary question answered against the compiled policy rather
        than against a constant it re-spelled.  Never raises: an unclassifiable
        duration is ``False``, because the caller that must hear about it calls
        :meth:`check`.
        """
        return exceeded_budget(elapsed_s, self._policy.wall_s)


def sandbox_timeout() -> SandboxTimeout:
    """The wall-clock law, compiled fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs a run's measured
    duration to answer for.  This is the module-level convenience the member's
    own tests and any operator script reach, and it is the same call
    :func:`sandbox.build_sandbox_timeout` makes minus the composition.
    """
    return SandboxTimeout(committed_timeout_policy())
