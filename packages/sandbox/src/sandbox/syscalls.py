"""Feature 160's law: a process attempting a disallowed syscall is rejected.

app_spec.xml, "Untrusted Code Sandbox", feature 160: *System applies a seccomp
syscall allowlist, which rejects a process attempting a disallowed syscall.*
docs/nullius-tech-architecture.md §5.2 gives the control its own row —
``Syscalls | seccomp allowlist`` — and §3's zone map states the posture that row
serves: *"Z1 — Mutated by the loop | Signal code, exploration policy code |
LLM agents | Sandboxed: no network, no FS, seccomp, cgroup limits"*.  §15's
failure table supplies the consequence a violation earns (*"Sandbox escape
attempt | seccomp violation | Kill, record ``fail_class``, quarantine the node
and its subtree"*), and features 161 and 168 are the two laws that act on it.
The sentence decomposes into four claims, each owned here as a seam rather than
a comment:

* **a seccomp syscall allowlist** — the configuration term, and the reason this
  law is a *ceiling* rather than a policy about a run's shape.  It is written
  down: :data:`COMMITTED_SYSCALLS_POLICY` ships beside this module and the
  compiler refuses any other, so "this deployment's box may read, write and
  allocate, and may not open a file, dial a socket, fork or draw kernel
  entropy" is a fact about a file in the repository rather than a line in a
  runbook.  The artifact carries **two** keys rather than one, and the second is
  the load-bearing half: ``default_action`` states the action everything
  *unlisted* meets, because a filter whose default is an allowing action is not
  a narrower box but no box at all — see :func:`compile_syscalls_policy`.

* **applies** — the tense, and the half of this feature that is a *mechanism*
  rather than a gate.  The member's other laws answer a future: features 157's,
  164's, 165's and 167's subjects are offered *before* anything executes, and
  their verbs return explanations rather than acting.  seccomp is the kernel's,
  installed on a process that then runs under it, so what this law produces is
  a **filter specification** — :class:`SyscallFilter`, the pair of a default
  action and the allowed set — which is what a launcher hands the runtime that
  arms ``SECCOMP_SET_MODE_FILTER``.  Nothing here installs anything: a Python
  object graph cannot arm a filter on a process it has not spawned, and the
  division is the one feature 157 states between its isolation policy and the
  ``runsc`` runtime that enforces it.

* **rejects a process attempting a disallowed syscall** — the consequent, and
  the only claim in this law that is about *a process* rather than about a run.
  So the subject is a single attempt: one syscall named by a process inside the
  box, presented as :class:`SyscallAttempt`, and answered by
  :func:`reject_syscall` with a :class:`SyscallDecision` whose refusal names the
  syscall, the ceiling it met and the action it met it with.  The refusal
  **answers** rather than raises — the pipeline §6.1 runs unattended over
  thousands of candidates and *"this candidate called ``openat``"* must reach an
  operator as a fact about a run rather than as a crashed evaluator — and
  :meth:`SyscallDecision.require` is where a launcher takes it as a
  :class:`~sandbox.errors.DisallowedSyscall`.

* **seccomp violation** — the term §15's failure table uses for the same event,
  and the handoff this law writes down rather than performs.  A rejected
  attempt is feature 161's subject (*"System quarantines a node together with
  its subtree after a seccomp violation, persisting a ``sandbox_escape`` fail
  class"*) and feature 168's (*the ``sandbox_escape`` class is not one of
  §9.1's four and is translated to ``error``*).  So
  :data:`VIOLATION_CLASS` is restated here as data beside the two other laws
  that own those spellings, and :meth:`SyscallDecision.violation` is the one
  line that hands the event on — a caller persisting a violation reads a value
  rather than re-deriving a class name from a failure table's prose.

**Why the ceiling is per deployment and not per box.**  §5.2's table gives the
isolation row one mechanism per box because isolation is a property *of a box*,
while the syscall row is one line for both Z1 boxes — the signal sandbox and the
policy runtime run the same interpreter, load the same payload stack and are
denied the same world.  A per-component syscall table here would be a knob
nobody turns, the reading :data:`sandbox.timeout.COMMITTED_TIMEOUT_POLICY`'s own
comment gives for its single wall budget.

**The default action admits two legal spellings and refuses three.**  ``kill``
and ``errno`` both *reject*, and they differ in what a box does next — the
process dies on ``SIGSYS``, or it receives ``EPERM`` and keeps running.  Both
are seccomp allowlists; ``allow``, ``log``, ``trace`` and ``notify`` are not,
because each of them lets the disallowed syscall through (``notify`` hands it to
a supervisor that may, and by default does, allow it).  The committed artifact
takes ``kill`` — §15's row — and the compiler refuses the other five by name
rather than comparing a string, so a document naming an action this law has
never heard of is refused as a *document* error rather than silently treated as
denying.

**Honest limits.**  This module is the *law about the ceiling*, not the filter:
it never calls ``prctl``, never writes a BPF program, never spawns a process and
cannot see a syscall a kernel has already refused.  The enforcement is the
runtime's — ``runsc`` on the OCI ``seccomp`` specification, with the filter this
law compiles — and what holds is that the committed ceiling cannot drift to a
wider action without the compile failing, that an attempt cannot be rejected
without naming the syscall and the action that refused it, and that *what this
deployment's box may call* is a value the compiled policy carries and a caller
can read (:meth:`SyscallPolicy.allowed`).  A seccomp filter matches on syscall
*number* and argument *values*; this law names syscalls, because a name is what
a deployment reviews and what a refusal can print, and the number table is the
runtime's to hold — the same division feature 167 draws between a dotted module
term and an importer's module object.

Stdlib-only, like the rest of the member: ``json`` for the artifact, ``re`` for
the term grammar, and no process, kernel, container runtime or BPF program
anywhere.  The module is the law and the committed artifact is what an operator
applies.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from .errors import (
    DisallowedSyscall,
    SyscallsDocumentError,
)

__all__ = [
    "ALLOWING_ACTIONS",
    "COMMITTED_SYSCALLS_POLICY",
    "DENYING_ACTIONS",
    "DISALLOWED_SYSCALL_CODE",
    "KILL_ACTION",
    "SANDBOX_ESCAPE_CLASS",
    "SYSCALLS_COMPONENT_NAME",
    "SYSCALLS_POLICY_KIND",
    "SYSCALLS_REQUIRED_CODE",
    "TERMINATION_SYSCALLS",
    "VIOLATION_CLASS",
    "Commitment",
    "SandboxSyscalls",
    "SyscallAttempt",
    "SyscallDecision",
    "SyscallFilter",
    "SyscallPolicy",
    "SyscallReason",
    "committed_syscalls_policy",
    "compile_syscalls_policy",
    "disallowed_syscall",
    "load_syscalls_policy",
    "reject_syscall",
    "sandbox_syscalls",
]

#: The marker a document declares itself with — the same discipline feature
#: 157's committed isolation policy, feature 167's committed import allowlist,
#: feature 164's committed pinning policy, feature 163's committed wall budget
#: and feature 162's committed cgroup budget take, so a stray JSON file carrying
#: an ``allow`` key cannot be read as this configuration.
SYSCALLS_POLICY_KIND: Final[str] = "sandbox-syscalls"

#: The committed artifact, shipped beside the law that checks it, so a checkout
#: cannot hold one without the other.
COMMITTED_SYSCALLS_POLICY: Final[Path] = Path(__file__).with_name(
    "syscalls_allowlist.json"
)

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, feature 167's ``sandbox-imports``, feature 166's
#: ``sandbox-transfer``, feature 165's ``sandbox-seed``, feature 164's
#: ``sandbox-threads``, feature 163's ``sandbox-timeout``, feature 168's
#: ``sandbox-failclass`` and feature 162's ``sandbox-budget``, not instead of
#: any of them: the factory's registry is keyed by name and a later registration
#: of the same name *replaces* the earlier one, so a member carrying nine
#: controls carries nine components, each answering its own feature's question.
#: Note what this name is *not*: ``sandbox-seccomp`` would name the mechanism
#: rather than the law, and this member names its components after their
#: subject — the isolation, the imports, the transfer, the seed, the threads,
#: the timeout, the fail class, the budget.  The subject here is the syscalls.
SYSCALLS_COMPONENT_NAME: Final[str] = "sandbox-syscalls"

#: The greppable code every syscall refusal carries — feature 160's own subject
#: written as a token, the discipline
#: :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`
#: (``gvisor_isolation_required``), :data:`sandbox.imports.DISALLOWED_IMPORT_CODE`
#: (``disallowed_import``), :data:`sandbox.threads.THREAD_PINNING_CODE`
#: (``thread_pinning_required``), :data:`sandbox.seed.SEED_REQUIRED_CODE`
#: (``node_seed_required``), :data:`sandbox.budget.CGROUP_BUDGET_CODE`
#: (``cgroup_budget_exceeded``) and :data:`sandbox.failclass.FAIL_CLASS_REQUIRED_CODE`
#: set for theirs — and deliberately the *parallel* of feature 167's, because the
#: two features are the same sentence applied to two different namespaces: 167
#: refuses an import term, this one refuses a syscall name.  An operator
#: grepping a log for the rejection finds it by the feature's own words.
DISALLOWED_SYSCALL_CODE: Final[str] = "disallowed_syscall"

#: The greppable code the *other* half of this law carries: the configured
#: ceiling could not be read, or an attempt could not be compared against it.
#: Two codes rather than one because the repairs are on opposite sides of the
#: seam — this one means the caller's document or attempt is malformed (or the
#: artifact did not compile), the other means a process genuinely called
#: something the box does not admit — the split feature 162's two codes make
#: for its own law.
SYSCALLS_REQUIRED_CODE: Final[str] = "syscalls_required"

#: §15's failing row, first of its consequence: the process is killed.  Written
#: as a constant because it is the one action this deployment commits to, and
#: the compiler refuses any other non-denying spelling rather than tolerating
#: one — see :data:`DENYING_ACTIONS`.
KILL_ACTION: Final[str] = "kill"

#: The actions that *reject* the syscall they are reached for, in the order the
#: committed artifact's own comment explains them.  Two spellings rather than
#: one because both are genuinely denying filters and they are different facts
#: about a box: ``kill`` terminates the process on ``SIGSYS``, ``errno``
#: completes the offending call by returning the error the box declared (by
#: seccomp's own default, ``EPERM``) and lets the process continue.  A compiler
#: that admitted only one of them would be a law about a deployment's taste
#: rather than about whether the ceiling denies.
DENYING_ACTIONS: Final[frozenset[str]] = frozenset({"kill", "errno"})

#: The actions that do **not** reject, and whose presence is therefore a
#: document that is not this configuration at all.  Named rather than inferred
#: as "anything not in :data:`DENYING_ACTIONS`" so a refusal can tell a *widened*
#: artifact from an *unreadable* one: ``allow`` is the drift section 5.2's
#: posture is most likely to suffer (it is the spelling a launcher's default
#: takes), while ``log``, ``trace`` and ``notify`` are the three that *look*
#: like controls — each observes the syscall and, by seccomp's own defaults, lets
#: it through.  A deployment that ran under ``notify`` and believed it was
#: sandboxed is the near-miss this constant exists to name.
ALLOWING_ACTIONS: Final[tuple[str, ...]] = ("allow", "log", "trace", "notify")

#: The syscalls whose presence the compiler requires, by behaviour rather than
#: by name: at least one of these must be listed, because a filter that admits
#: nothing terminates the box at its first instruction and a deployment in that
#: state learns nothing about what it refused.  See the committed artifact's own
#: comment, which states this as the deliberate opposite of feature 167's empty
#: ceiling.  A set rather than a single name so a document may list either the
#: BSD spelling (``exit``) or the Linux one (``exit_group``) — the kernel
#: registers both and a signal's interpreter calls whichever its libc chose.
TERMINATION_SYSCALLS: Final[frozenset[str]] = frozenset({"exit", "exit_group"})

#: The class §15's failure table records for a violation, and feature 161's own
#: subject — *"System quarantines a node together with its subtree after a
#: seccomp violation, persisting a sandbox_escape fail class"*.  Restated here
#: as data rather than imported from :data:`sandbox.failclass.SANDBOX_ESCAPE_CLASS`
#: for the member's one-provenance reason: this suite pins the two equal, and
#: :data:`sandbox.failclass` is where the spelling is *owned* (its own comment
#: says so).  It is deliberately **not** one of §9.1's four: it is a genuine
#: seccomp verdict rather than a terminal class of the column, which is why
#: feature 168's table is what translates it to ``error``.
VIOLATION_CLASS: Final[str] = "sandbox_escape"

#: The same spelling under the name the handoff reads better by — §15's prose
#: says "seccomp violation" and feature 168's table calls the class by it, so
#: both names are exported rather than one being derived from the other at each
#: reader's discretion.
SANDBOX_ESCAPE_CLASS: Final[str] = VIOLATION_CLASS

#: A well-formed syscall term.  Syscall names are ``lower_snake_case`` — the
#: kernel's own spelling (``clock_gettime``, ``rt_sigaction``, ``openat2``) —
#: and the grammar is anchored at both ends so a name with a leading or trailing
#: separator, an empty segment, a padding space or an upper-case letter is
#: refused rather than silently matched.  The last character must be a letter or
#: a digit rather than an underscore, which is what the kernel's own table looks
#: like: ``openat2`` ends in a digit and no syscall ends in a separator, so a
#: trailing underscore is a spelling nothing registers rather than a name this
#: law should quietly match.  Spelled here rather than shared with feature 167's
#: dotted-module grammar by import: the two grammars are different languages
#: about different namespaces, and a syscall name with a dot in it (``foo.bar``)
#: is a term from another law's ceiling arriving in this one.
_TERM_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z](?:[a-z0-9_]*[a-z0-9])?$")


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise SyscallsDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: {value!r}. "
            f"A seccomp policy is a structured document — an action and a "
            f"ceiling — and a compiler that guessed at the meaning of a stray "
            f"list or string would be writing policy rather than reading it: "
            f"refused, fail closed (feature 160)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise SyscallsDocumentError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). The action a filter takes on an "
            f"unlisted syscall is named, not inferred: an action that is "
            f"absent, blank or not a string is one this policy cannot hold a "
            f"box to, and 'unnamed' is not 'kill' (feature 160, refused fail "
            f"closed)."
        )
    return value


class SyscallPolicy:
    """A compiled ceiling: a denying default action and the syscalls it admits.

    What :func:`compile_syscalls_policy` returns is not the document — it is the
    document *plus* the guarantee that its default action denies and that every
    term it lists is a well-formed syscall name, listed once.  Holders (the
    filter builder, an operator script, a CI check that recompiles the committed
    artifact) cite that guarantee rather than re-derive it, which is why a
    refusal can say "outside the configured allowlist" and mean a set that was
    validated.

    **The default action is a field of the policy and not a constant of this
    module**, for the reason feature 162's three limits are the policy's rather
    than module constants: the rejection is the compiled declaration arriving at
    its answer, and a hand-assembled policy carrying ``errno`` would reject at
    ``errno`` and say so — itself the audit finding.  What the *compiler* holds
    is that whichever of the two actions a document names, it denies.

    Coverage is by exact name and not by prefix, deliberately unlike feature
    167's ceiling: a syscall name is an atom, not a namespace — there is no
    ``openat2`` "under" ``openat``, and the two are separately listed or
    separately absent for exactly that reason.
    """

    __slots__ = ("_allowed", "_allowed_set", "default_action", "kind")

    def __init__(
        self,
        *,
        kind: str,
        default_action: str,
        allowed: tuple[str, ...],
    ) -> None:
        self.kind = kind
        self.default_action = default_action
        self._allowed = allowed
        # The membership probe in ``admits`` is a set lookup per attempt, so one
        # scan of the document's terms answers every call at once.  Built once
        # here — a compiled policy is immutable — rather than per probe: a box
        # calls this on the refusal's clock, and a ceiling that re-derived
        # itself per attempt would be doing the compile's work there.
        self._allowed_set = frozenset(allowed)

    def allowed(self) -> tuple[str, ...]:
        """Every syscall the ceiling admits, in document order.

        The read side: *what may this deployment's box call?* is a question an
        operator or a CI check answers from the compiled artifact rather than by
        watching a process.
        """
        return self._allowed

    def admits(self, name: object) -> bool:
        """Whether the ceiling admits a syscall name.

        A name that is not a string names no syscall and is admitted by
        nothing — the conservative answer, the same one the gate's refusal gives
        it.  Note that this asks only the membership question: whether a
        deployment's *default action* denies is a separate fact the compiler has
        already settled (`default_action`), and a caller asking "is this box
        denied everything else?" reads that field rather than this method.
        """
        if not isinstance(name, str):
            return False
        return name in self._allowed_set

    def filter(self) -> SyscallFilter:
        """This policy as the filter specification a runtime arms.

        The bridge from the *law about the ceiling* to the thing a launcher
        needs, and the reason this class exists rather than the law holding a
        bare set: a launcher handed a policy has to write a filter, and the two
        facts a filter is written from — the action unlisted syscalls meet and
        the names that bypass it — are exactly this object's two fields.
        """
        return SyscallFilter(
            kind=self.kind,
            default_action=self.default_action,
            allowed=self._allowed,
        )

    def __contains__(self, name: object) -> bool:
        # The duck-checkable spelling of ``admits`` — "may the box call this?"
        # is the question a caller holding the ceiling asks.
        return self.admits(name)

    def __len__(self) -> int:
        return len(self._allowed)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SyscallPolicy(kind={self.kind!r}, "
            f"default_action={self.default_action!r}, "
            f"allowed={list(self._allowed)!r})"
        )


class SyscallFilter:
    """The compiled ceiling as a filter specification — what a runtime arms.

    Feature 160's word is *applies*, and this is the object "applies" is carried
    by: a default action and the set of syscalls exempt from it, written the way
    the OCI ``seccomp`` specification is written (``defaultAction`` plus
    ``syscalls[].names``).  It is a **value**, not an armed filter — nothing in
    this module has called ``prctl``, and the class holds no process to call it
    on — which is the division feature 157 states between its isolation policy
    and the ``runsc`` runtime that enforces it.

    **Why the filter is a separate type from the policy rather than the policy
    itself.**  The two answer different questions and a deployment audits them
    differently: the *policy* answers "what does this deployment admit, and what
    happens to everything else?", which is what a reviewer reads, while the
    *filter* answers "what exactly do we hand the runtime?", which is what a
    launcher reads and what a second implementation of the launcher would have
    to reproduce byte for byte.  Keeping them one object would make the
    specification's shape a property of the law's — so a runtime needing a third
    field (a flag set, an argument clause) would edit the law to get it.

    ``names`` is returned as a tuple in the policy's own document order rather
    than as a set: two deployments' filters can then be compared field by field,
    the property :class:`sandbox.budget.CgroupPolicy` states for its limits.
    """

    __slots__ = ("_allowed", "default_action", "kind")

    def __init__(
        self,
        *,
        kind: str,
        default_action: str,
        allowed: tuple[str, ...],
    ) -> None:
        self.kind = kind
        self.default_action = default_action
        self._allowed = allowed

    @property
    def denies_by_default(self) -> bool:
        """Whether everything unlisted meets a denying action.

        The one field a reviewer checks first, exposed as a boolean because it is
        the difference between a ceiling and a wishlist and a reader should not
        have to know the two denying spellings to ask.  ``False`` can only be
        reached by a hand-assembled filter: the compiler refuses a document
        whose action does not deny.
        """
        return self.default_action in DENYING_ACTIONS

    @property
    def kills(self) -> bool:
        """Whether an unlisted syscall terminates the process rather than failing it.

        The distinction §15's recovery column turns on: this deployment commits
        ``kill``, so a violation is a process the kernel destroyed on ``SIGSYS``
        — which is why the class recorded beside it is
        :data:`VIOLATION_CLASS` and why feature 161 quarantines rather than
        retries.  An ``errno`` filter is a legal ceiling and a different fact
        about a box, so a caller that needs to know which one it holds asks here
        rather than parsing the action string.
        """
        return self.default_action == KILL_ACTION

    def names(self) -> tuple[str, ...]:
        """The syscalls the filter exempts from its default action."""
        return self._allowed

    def admits(self, name: object) -> bool:
        """Whether this filter exempts a syscall name — the same answer the policy gave."""
        if not isinstance(name, str):
            return False
        return name in frozenset(self._allowed)

    def specification(self) -> dict[str, Any]:
        """The filter as the OCI/runtime mapping a launcher writes.

        The shape a deployment hands its runtime, in the specification's own
        spelling (``defaultAction``, ``syscalls``, ``names``) rather than this
        member's — because the runtime's vocabulary is not this law's to rename,
        and a filter translated by each launcher would be a second place for the
        two spellings to diverge.  A fresh dict per call, never a shared one: the
        copy-then-hand discipline every other read side in this member applies,
        so a caller that mutated what it was handed cannot widen the ceiling for
        the next one.
        """
        return {
            "defaultAction": self.default_action,
            "syscalls": [{"names": list(self._allowed), "action": "SCMP_ACT_ALLOW"}],
        }

    def __len__(self) -> int:
        return len(self._allowed)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SyscallFilter(kind={self.kind!r}, "
            f"default_action={self.default_action!r}, "
            f"allowed={len(self._allowed)} names)"
        )


def compile_syscalls_policy(document: Any) -> SyscallPolicy:
    """Compile a seccomp policy, refusing one that is not a denying ceiling.

    The seam the whole feature turns on.  The document is read whole — marker,
    default action, terms — and each is held to the law before a
    :class:`SyscallPolicy` is handed out: it must declare itself
    :data:`SYSCALLS_POLICY_KIND`, its ``default_action`` must be one of
    :data:`DENYING_ACTIONS`, no term may be malformed or listed twice, and at
    least one :data:`TERMINATION_SYSCALLS` spelling must be present.  A refusal
    propagates as an exception, so a caller cannot continue with a half-trusted
    ceiling: the document that would have admitted a syscall section 5.2's
    posture denies is never applied, which is the compile-time half of "System
    applies" (feature 160).

    **The default action is checked by name, and the *widening* drift is the one
    this law exists for.**  A seccomp filter is an allowlist only when
    everything unlisted meets a denying action, so ``default_action: "allow"``
    is a document that looks like a control and is not one — every syscall the
    list omits would be admitted, and a box running under it would be an
    ordinary container that believes it is sandboxed.  That refusal
    (:class:`~sandbox.errors.SyscallsDocumentError`, named by
    :data:`ALLOWING_ACTIONS`) is deliberately a *document* error rather than a
    violation: the artifact is written by trusted code and cannot be read as this
    configuration, while a *process* attempting a disallowed syscall is
    :func:`reject_syscall`'s subject and the feature's own sentence.

    **A ceiling that admits nothing is refused, and that is the opposite reading
    from feature 167's.**  An import allowlist listing no terms is the strictest
    ceiling there is: the screen refuses the module statically, nothing runs, and
    the refusal is returned as a value the pipeline records.  A *syscall* filter
    over an empty set is not a control at all — the box is terminated at its
    first instruction, so there is no run to refuse and nobody left to record
    anything, and a deployment in that state would see every candidate die
    identically and conclude the candidates were bad.  So the compiler requires
    the box to be able to end itself, on the grounds that ``we admitted nothing''
    and ``we safely refused everything'' are different facts and only the second
    is a ceiling.
    """
    doc = _require_mapping(document, "sandbox syscalls policy document")
    marker = _require_str(doc.get("policy"), "sandbox syscalls policy 'policy'")
    if marker != SYSCALLS_POLICY_KIND:
        raise SyscallsDocumentError(
            f"a sandbox syscalls policy must declare itself "
            f"{SYSCALLS_POLICY_KIND!r}, got {marker!r}. A document that does "
            f"not say what it is cannot be trusted to say what untrusted code "
            f"may call, and a stray JSON file carrying an 'allow' key is not "
            f"this policy — refused, fail closed (feature 160)."
        )

    default_action = _require_str(
        doc.get("default_action"), "sandbox syscalls policy 'default_action'"
    )
    action = default_action.strip().casefold()
    if action in ALLOWING_ACTIONS:
        raise SyscallsDocumentError(
            f"a sandbox syscalls policy declares default_action "
            f"{default_action!r}, which does not reject the syscalls the "
            f"ceiling does not name. §5.2's control row is 'Syscalls | seccomp "
            f"allowlist' and an allowlist is an allowlist only when everything "
            f"unlisted meets a denying action: {action!r} observes an attempt "
            f"and lets it through, so a box running under this document would "
            f"be an ordinary container that believes it is sandboxed — the "
            f"near-miss this control exists to prevent. Only "
            f"{sorted(DENYING_ACTIONS)} deny; the whole document is refused "
            f"rather than the action quietly replaced (feature 160)."
        )
    if action not in DENYING_ACTIONS:
        raise SyscallsDocumentError(
            f"a sandbox syscalls policy declares default_action "
            f"{default_action!r}, which is not a seccomp action this law "
            f"knows. A filter's default is the action *every* unlisted syscall "
            f"meets, so an unrecognised spelling is not an unknown detail — it "
            f"is the deployment's whole posture left undecided, and a compiler "
            f"that read it as denying would be inventing a kernel behaviour "
            f"from a string. This deployment's two legal spellings are "
            f"{sorted(DENYING_ACTIONS)}; refused rather than assumed (feature "
            f"160)."
        )

    raw_terms = doc.get("allow")
    if not isinstance(raw_terms, list):
        raise SyscallsDocumentError(
            f"a sandbox syscalls policy's 'allow' must be a list of syscall "
            f"names, got {type(raw_terms).__name__}: {raw_terms!r}. The list is "
            f"the ceiling's whole content — the syscalls a process in the box "
            f"may make — and a document that cannot enumerate them cannot be "
            f"compiled (feature 160)."
        )

    terms: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_terms):
        if not isinstance(raw, str) or not _TERM_RE.match(raw):
            raise SyscallsDocumentError(
                f"a sandbox syscalls policy's term #{index + 1} must be a "
                f"lower_snake_case syscall name, got {raw!r}. A term that is "
                f"not one — a padded spelling, an upper-case letter, a dotted "
                f"module term from another law's ceiling, an empty segment — "
                f"names no syscall a kernel can be asked about, and a ceiling "
                f"compiled with it would be a ceiling with a hole no attempt "
                f"could match (feature 160, refused fail closed)."
            )
        term = raw
        if term in seen:
            raise SyscallsDocumentError(
                f"{term!r} appears twice in the syscalls policy. One syscall "
                f"listed twice is not a wider ceiling, it is one term described "
                f"twice — and the applied policy would be whichever spelling "
                f"came last, which is drift with extra steps. Refused (feature "
                f"160)."
            )
        seen.add(term)
        terms.append(term)

    if not TERMINATION_SYSCALLS.intersection(seen):
        raise SyscallsDocumentError(
            f"a sandbox syscalls policy admits no way for the process to end: "
            f"it lists {len(terms)} syscalls and none of "
            f"{sorted(TERMINATION_SYSCALLS)}. A filter whose default denies and "
            f"which exempts nothing that terminates the box kills every "
            f"candidate at its first instruction, so there is no run to refuse, "
            f"no outcome to record and no way to tell 'this deployment "
            f"confines untrusted code' from 'this deployment kills everything "
            f"it dispatches'. Deliberately the opposite reading from feature "
            f"167's empty ceiling, which refuses a module *before* it runs and "
            f"returns that refusal as a value: a static screen that admits "
            f"nothing still has somebody to do the recording (feature 160)."
        )

    return SyscallPolicy(
        kind=SYSCALLS_POLICY_KIND,
        default_action=action,
        allowed=tuple(terms),
    )


def load_syscalls_policy(path: Path = COMMITTED_SYSCALLS_POLICY) -> SyscallPolicy:
    """Read and compile a policy from disk, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly as
    a drift compiled in memory (feature 160).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise SyscallsDocumentError(
            f"could not read the sandbox syscalls policy at {path}: {exc}. A "
            f"policy that cannot be read is not a filter that refuses "
            f"everything gracefully — it is a deployment whose box has no "
            f"syscall law at all, and a caller that carried on would be running "
            f"agent-authored code under no seccomp ceiling while believing it "
            f"was configured from this file (feature 160)."
        ) from exc
    except ValueError as exc:
        raise SyscallsDocumentError(
            f"the sandbox syscalls policy at {path} is not valid JSON: {exc}. "
            f"Refused rather than read partially: a policy compiled from a "
            f"partially-parsed document is one whose file and whose box "
            f"disagree (feature 160)."
        ) from exc
    return compile_syscalls_policy(document)


def committed_syscalls_policy() -> SyscallPolicy:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 160's own tests hold to §5.2's row, so "this deployment's box runs
    under a seccomp allowlist that denies everything it does not name" is a
    checked fact about a file in the repository rather than a claim in a
    runbook.
    """
    return load_syscalls_policy(COMMITTED_SYSCALLS_POLICY)


class SyscallReason(enum.StrEnum):
    """Why an attempt was admitted or rejected — the audit vocabulary.

    One enumeration carries the acceptance and the rejections, because a
    decision's reason is one fact with two polarities and the audit line should
    read the same either way: ``by-allowlist`` names the ceiling the attempt was
    admitted against, and the rejections name what the filter found instead —
    the shape :class:`sandbox.imports.ModuleReason`,
    :class:`sandbox.isolation.RunReason` and :class:`sandbox.budget.BudgetReason`
    give their own laws.
    """

    #: Admitted: the attempt names a syscall the ceiling lists, so the default
    #: action is never reached.  Reading the string is proof the compiled
    #: ceiling was consulted — a gate hardcoded to "allow" could never produce
    #: the refusal that shares its enum.
    BY_ALLOWLIST = "by-allowlist"

    #: Rejected: the attempt names a syscall outside the configured ceiling, and
    #: the filter's default action is what it meets.  Feature 160's headline,
    #: and the only reason a decision carries a :class:`Commitment`.
    OUTSIDE_ALLOWLIST = "outside-allowlist"

    #: Rejected: the attempt does not name a syscall this law can read — absent,
    #: not a string, blank, or a spelling that is not a syscall name at all.  Its
    #: own reason because the repair is different from the last one: the caller
    #: has the right *shape* of subject and an unusable name, and whatever
    #: produced it is where the operator looks.  Refused rather than read as
    #: admitted, because *"unknown" is not "allowed"* — the reading feature 167's
    #: :attr:`~sandbox.imports.ModuleReason.UNPARSABLE_SOURCE` gives an
    #: unreadable submission.
    UNNAMED_SYSCALL = "unnamed-syscall"


class Commitment:
    """One rejected attempt: the syscall, the ceiling, and what met it.

    Feature 160's *rejects* half as a value — what a caller hands a ledger row, an
    operator log and feature 161's quarantine decision — carrying the syscall
    name, the action the filter reached for it and the compiled ceiling it
    missed, so *what did this candidate call?* is answerable from the record
    rather than from a log line that has since rotated.

    **Why the action travels with the refusal rather than being looked up by the
    reader.**  The two denying actions are different fates — a ``kill`` is a
    process the kernel destroyed and a violation feature 161 quarantines for,
    while an ``errno`` is a call that failed and a process that kept running —
    and a persisted row that recorded only "disallowed" would leave an operator
    unable to tell a box that was breached from a box that behaved.  So the
    action is written into the record by the gate that saw it, in the compiled
    policy's own spelling.

    ``fail_class`` is §15's ``sandbox_escape``, restated as data
    (:data:`VIOLATION_CLASS`) for the member's one-provenance reason, and it is
    deliberately **not** one of §9.1's four: the column holds ``ok | timeout |
    error | tripwire_fail``, and feature 168's table is what places this class
    under ``error``, which is why :meth:`row` publishes the class under its own
    name and leaves the translation to the law that owns it — the same division
    :meth:`sandbox.budget.BudgetBreach.row` draws for the runner's six.
    """

    __slots__ = ("action", "ceiling_terms", "component", "node_id", "syscall")

    def __init__(
        self,
        *,
        syscall: str,
        action: str,
        ceiling_terms: int,
        node_id: str = "",
        component: str = "",
    ) -> None:
        self.syscall = syscall
        self.action = action
        self.ceiling_terms = ceiling_terms
        self.node_id = node_id
        self.component = component

    @property
    def killed(self) -> bool:
        """Whether this attempt's fate was the process's death.

        The whole reason the action is carried: §15's recovery column is "Kill,
        record ``fail_class``, quarantine the node and its subtree", so a
        violation whose action was ``kill`` is one the box no longer exists to
        describe — feature 161's subject — while an ``errno`` violation is a
        candidate that kept running and produced a plausible answer out of a
        refused call.
        """
        return self.action == KILL_ACTION

    @property
    def fail_class(self) -> str:
        """§15's class for this event — ``sandbox_escape``, feature 161's."""
        return VIOLATION_CLASS

    def describe(self) -> str:
        """``openat → kill`` — the attempt as one reviewer-readable phrase.

        The operator line, and the reason this class exists as a type rather
        than as the syscall name alone: a violation record's whole content is
        *which* syscall a process tried and *what happened when it did*, and a
        line naming only the first would read identically for a box that died
        and a box that was allowed to carry on.
        """
        return f"{self.syscall} → {self.action}"

    def row(self) -> dict[str, Any]:
        """The violation as one store-shaped mapping.

        The shape a ledger row, a §9.1 record or feature 161's quarantine
        decision is written from: the syscall, the action, the class, and the
        node and component identity when the attempt carried them.  Fresh dict
        per call, never a shared one — the copy-then-hand discipline
        :meth:`sandbox.budget.BudgetBreach.row` and
        :meth:`sandbox.timeout.TimeoutKill.row` apply to their own shapes.
        """
        row: dict[str, Any] = {
            "syscall": self.syscall,
            "action": self.action,
            "fail_class": self.fail_class,
            "killed": self.killed,
            "ceiling_terms": self.ceiling_terms,
        }
        if self.node_id:
            row["node_id"] = self.node_id
        if self.component:
            row["component"] = self.component
        return row

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Commitment(syscall={self.syscall!r}, action={self.action!r}, "
            f"node_id={self.node_id!r})"
        )


class SyscallAttempt:
    """One syscall a process inside the box attempted.

    Feature 160's sentence is about *a process attempting a disallowed syscall*,
    so the subject is one attempt rather than a whole run — the narrower unit
    :class:`sandbox.budget.BudgetRun` models for a measurement and
    :class:`sandbox.seed.SandboxInvocation` for a dispatch, and narrower than
    either: this is one call, which is what a kernel's filter actually sees.

    **What it carries is what the kernel reported, never a probe.**  Nothing in
    this module watches a process: the runtime that owns the filter is the one
    that knows a syscall was reached for, so the name arrives as an argument —
    the same division that has feature 157's law read a run's *declared*
    isolation rather than dial a container runtime and feature 162's read a
    cgroup's counters rather than open a hierarchy.  A law that instrumented a
    process itself would be a second, disagreeing observer of an event the
    kernel already refused.

    ``node_id`` and ``component`` are carried for the violation record and are
    not read by the comparison, the same courtesy
    :class:`sandbox.seed.SandboxInvocation` and
    :class:`sandbox.budget.BudgetRun` extend.
    """

    __slots__ = ("component", "node_id", "syscall")

    def __init__(
        self,
        *,
        syscall: Any,
        node_id: str = "",
        component: str = "",
    ) -> None:
        self.syscall = syscall
        self.node_id = node_id
        self.component = component

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SyscallAttempt(syscall={self.syscall!r}, "
            f"node_id={self.node_id!r}, component={self.component!r})"
        )


class SyscallDecision:
    """The gate's whole answer: rejected or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed* from
    the compiled ceiling rather than set by a constant: the gate reads the
    attempt's name and admits only when the ceiling lists it.  ``detail``
    carries the ``disallowed_syscall`` message the feature's own words name — the
    one place the law explains itself at rejection time, naming the syscall, the
    action it met and the ceiling it was checked against.

    :attr:`rejected` is deliberately separate from ``not admitted`` in *meaning*,
    though they coincide: the member's other decisions state a refusal as its own
    property, and a caller that read a bare falsy as "the box was fine" would
    treat an unreadable attempt as an admitted one — the distinction
    :attr:`sandbox.budget.BudgetDecision.refused` exists to keep.
    """

    __slots__ = ("admitted", "commitment", "detail", "reason")

    def __init__(
        self,
        *,
        admitted: bool,
        reason: SyscallReason,
        detail: str,
        commitment: Commitment | None = None,
    ) -> None:
        self.admitted = admitted
        self.reason = reason
        self.detail = detail
        self.commitment = commitment

    @property
    def rejected(self) -> bool:
        """Whether the ceiling refused this attempt — the headline.

        Both rejection reasons, and never the acceptance: a syscall outside the
        ceiling and an attempt this law could not read are both "the box did not
        get to make this call", which is the fact a caller branches on.
        """
        return not self.admitted

    @property
    def violation(self) -> Commitment | None:
        """The event feature 161 quarantines for, or ``None``.

        The handoff this law writes down rather than performs: a *rejection* of a
        named syscall by the ceiling's default action is a seccomp violation in
        §15's terms, and the caller that owns the node and its subtree is feature
        161's.  ``None`` for an admitted attempt *and* for an unreadable one —
        the second deliberately, because an attempt no ceiling could be compared
        against is not an escape attempt, it is a caller that offered a name this
        law cannot read, and quarantining a node for that would be acting on a
        fabricated violation.  A caller that wants every rejection raised
        re-raises on :meth:`require`.
        """
        return self.commitment

    def require(self) -> None:
        """Raise :class:`~sandbox.errors.DisallowedSyscall` unless admitted.

        The bridge between the gate's returned answer and the exception a
        launcher wants on the line after the filter is armed: a decision that
        admitted the attempt is a no-op, so a caller can use it unconditionally.
        Both rejection reasons raise the one class, because the two halves of
        feature 160 carry one error type and a caller never has to catch two —
        the division :meth:`sandbox.isolation.RunDecision.require` draws for its
        own pair.
        """
        if not self.admitted:
            raise DisallowedSyscall(self.detail)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SyscallDecision(admitted={self.admitted}, reason={self.reason!r}, "
            f"commitment={self.commitment!r})"
        )


def _subject_syscall(subject: object) -> Any:
    """The syscall name ``subject`` carries, or ``None``.

    Reads a :class:`SyscallAttempt` and any object carrying a ``syscall``
    attribute, because the caller's own attempt record may describe a call this
    law should still be able to judge — the same tolerance
    :func:`sandbox.budget._subject_measurement` and
    :func:`sandbox.threads._subject_environment` extend to the shapes their own
    subjects arrive in.  ``None`` for an object that does not carry the field at
    all *and* for one that carries an explicit ``None``: the two are one fact
    here ("no name"), which is what a filter reports when it cannot say.
    """
    return getattr(subject, "syscall", None)


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


def _unnamed_refusal(subject: object, raw: Any) -> str:
    """The rejection for an attempt that does not name a syscall this law can read."""
    return (
        f"{SYSCALLS_REQUIRED_CODE}: a syscall attempt was offered to the "
        f"seccomp gate naming {raw!r} ({type(raw).__name__}), which is not a "
        f"syscall name. §5.2's control row is 'Syscalls | seccomp allowlist', "
        f"and the whole subject of this law is the name a kernel's filter "
        f"matches against its exempt list — so an attempt described by nothing, "
        f"by a number, by text that is not a syscall spelling or by a blank "
        f"cannot be asked whether the ceiling admits it. Refused rather than "
        f"admitted: 'unknown' is not 'allowed', and a call waved through on a "
        f"name nothing could match is exactly the escape this control exists "
        f"to prevent (feature 160)."
    )


def _outside_refusal(
    name: str,
    policy: SyscallPolicy,
    *,
    component: str,
) -> str:
    """The operator-facing sentence for a rejected attempt."""
    listed = ", ".join(policy.allowed())
    return (
        f"{DISALLOWED_SYSCALL_CODE}: a process in the sandbox of component "
        f"{component!r} attempted the syscall {name!r}, which is not in the "
        f"configured allowlist ({policy.kind}, {len(policy.allowed())} names), "
        f"and is rejected with the filter's default action {policy.default_action!r}. "
        f"§5.2's control table is 'Syscalls | seccomp allowlist' and §3's zone "
        f"map states the posture it serves: 'Z1 — Mutated by the loop | Signal "
        f"code, exploration policy code | LLM agents | Sandboxed: no network, "
        f"no FS, seccomp, cgroup limits'. The ceiling this attempt met is:\n  "
        f"{listed}\n"
        f"A syscall this deployment does not name is one it never vouched for — "
        f"§15's failure table entries it as a sandbox escape attempt, whose "
        f"recovery is 'Kill, record fail_class, quarantine the node and its "
        f"subtree' — and the attempt is rejected rather than allowed through: "
        f"the whole point of listing the ceiling is that the syscalls it omits "
        f"(opening a file, dialling a socket, forking, drawing kernel entropy) "
        f"are the ones that reach the world this box refuses (feature 160)."
    )


def reject_syscall(subject: object, policy: SyscallPolicy) -> SyscallDecision:
    """Answer one attempt: admitted only when the ceiling names its syscall.

    The gate, and the one place the law is actually applied — every other verb
    in this module (:meth:`SandboxSyscalls.check`, :meth:`SyscallDecision.require`)
    reaches this function rather than re-deciding.  Nothing is raised here for a
    rejection, for the reason features 157's, 167's, 162's and 168's gates raise
    nothing: the pipeline §6.1 runs unattended over thousands of candidates and
    *"this one called ``openat``"* must reach an operator as a fact about a run
    rather than as a crashed evaluator, while a caller that must not proceed
    turns the answer into an exception with :meth:`SyscallDecision.require`.

    The order of the checks is the order of the sentence.  The attempt's
    *readability* is settled first — an attempt naming nothing has no name to
    look up and is not rejected on a ceiling it cannot be compared against —
    then the membership, which is the only thing that can reject.  Everything is
    answered; the *subject is settled first* is the same shape
    :func:`sandbox.budget.check_cgroup_budget` gives its own refusals.

    The answer is about the *name* and the compiled ceiling, never about the
    arguments a call carried: seccomp filters can match argument values, this law
    names syscalls, and a refusal that implied it had judged ``openat``'s path
    would be claiming a decision this seam did not make.
    """
    if not isinstance(policy, SyscallPolicy):
        raise SyscallsDocumentError(
            f"the ceiling to judge a syscall against must be a compiled "
            f"SyscallPolicy, got {type(policy).__name__}; the ceiling is a "
            f"validated value, not a loose sequence a gate would have to "
            f"re-validate mid-refusal (feature 160)."
        )

    raw = _subject_syscall(subject)
    node, owner = _subject_identity(subject)

    if not isinstance(raw, str) or not _TERM_RE.match(raw.strip()):
        return SyscallDecision(
            admitted=False,
            reason=SyscallReason.UNNAMED_SYSCALL,
            detail=_unnamed_refusal(subject, raw),
        )

    name = raw.strip()
    if not policy.admits(name):
        return SyscallDecision(
            admitted=False,
            reason=SyscallReason.OUTSIDE_ALLOWLIST,
            detail=_outside_refusal(name, policy, component=owner),
            commitment=Commitment(
                syscall=name,
                action=policy.default_action,
                ceiling_terms=len(policy.allowed()),
                node_id=node,
                component=owner,
            ),
        )

    return SyscallDecision(
        admitted=True,
        reason=SyscallReason.BY_ALLOWLIST,
        detail=(
            f"a process in the sandbox of component {owner!r} attempted the "
            f"syscall {name!r}, which the configured allowlist names "
            f"({policy.kind}, {len(policy.allowed())} names), so the filter's "
            f"default action {policy.default_action!r} is never reached and the "
            f"call proceeds — §5.2's row 'Syscalls | seccomp allowlist' holding "
            f"(feature 160)."
        ),
    )


def disallowed_syscall(subject: object, policy: SyscallPolicy) -> bool:
    """Whether an attempt fell outside a policy's ceiling — the one boolean.

    The convenience for a caller that does not want the decision: the same
    computation, read at its headline.  An *unreadable* attempt is ``False``
    here, which is what :attr:`SyscallDecision.rejected` is for — a caller that
    branches on this alone has asked only the membership question, the same
    caveat :meth:`sandbox.budget.over_limits` states for its own.

    Never raises: a caller that must hear about an unreadable attempt calls
    :func:`reject_syscall`.
    """
    return reject_syscall(subject, policy).commitment is not None


class SandboxSyscalls:
    """Feature 160's law, as the value a composed application carries.

    A stateless facade over this module and the committed ceiling it compiled —
    the same shape :class:`sandbox.SandboxIsolation` gives feature 157,
    :class:`sandbox.SandboxImports` 167, :class:`sandbox.SandboxTransfer` 166,
    :class:`sandbox.SandboxSeed` 165, :class:`sandbox.SandboxThreads` 164,
    :class:`sandbox.SandboxTimeout` 163, :class:`sandbox.SandboxFailClass` 168 and
    :class:`sandbox.SandboxBudget` 162 — so a caller holding the composed
    component can ask the feature's question, *may a process in this box make
    this call?*, without importing the member's submodules by name or re-reading
    the artifact.

    **It carries no process and no armed filter.**  A component shared across
    runs that had installed a filter — or that held a ``prctl`` handle — would be
    one box's ceiling applied to another's process, the property
    :class:`sandbox.SandboxIsolation` states for its own missing runtime handle
    and :class:`sandbox.SandboxBudget` for its missing cgroup.  What it carries is
    the compiled ceiling, and the filter specification a launcher arms is built
    per call by :meth:`filter`.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the membership rule or the
    refusal sentence here would be a second thing to keep in sync, and the
    member's one-provenance rule exists so that cannot happen.
    """

    __slots__ = ("_policy",)

    def __init__(self, policy: SyscallPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> SyscallPolicy:
        """The compiled ceiling this component carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator asking what untrusted code may call — reads the ceiling rather
        than re-deriving it.  Reading it widens nothing: the policy holds no
        capability, which is the point of the component being a facade rather
        than an armed filter.
        """
        return self._policy

    @property
    def default_action(self) -> str:
        """The action everything the ceiling does not name meets."""
        return self._policy.default_action

    def filter(self) -> SyscallFilter:
        """The filter specification a launcher arms for this deployment's box.

        Feature 160's word is *applies*, and this is the verb that carries it:
        the caller hands the result to whatever spawns the box, and the runtime
        writes the BPF program.  Nothing is applied by calling it — the division
        feature 157 states between its isolation policy and the ``runsc`` runtime
        that enforces it.
        """
        return self._policy.filter()

    def check(self, subject: object) -> SyscallDecision:
        """Answer whether ``subject`` fell outside the ceiling — the gate, as a value.

        ``subject`` is a :class:`SyscallAttempt` or any object carrying a
        ``syscall`` attribute, which is how a caller's own record type can be
        judged without being re-described.  No process is watched: this law reads
        what a runtime reported, so a test never depends on the machine that
        started pytest having seccomp compiled into its kernel.
        """
        return reject_syscall(subject, self._policy)

    def allows(self, name: object) -> bool:
        """Whether the configured ceiling names one syscall.

        The read side of the law: *may the box call this?* is a question a
        deployment should be able to answer without running a candidate to find
        out, and answering it from the compiled artifact is what makes the
        ceiling a fact about the deployment rather than a claim in a runbook.
        """
        return self._policy.admits(name)

    def allowed(self) -> tuple[str, ...]:
        """The syscalls this deployment admits, in document order."""
        return self._policy.allowed()

    def require(self, subject: object) -> None:
        """Return ``None`` if the attempt is inside the ceiling, else raise.

        The launcher's verb, and the one line that makes *"a process attempting
        a disallowed syscall is rejected"* enforced at the call rather than
        remembered: put it after the filter is armed and a violation becomes the
        member's own :class:`~sandbox.errors.DisallowedSyscall` rather than an
        ordinary trial outcome for a run nothing confined.
        """
        self.check(subject).require()


def sandbox_syscalls() -> SandboxSyscalls:
    """The syscall law, compiled fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs an attempt to answer
    for.  This is the module-level convenience the member's own tests and any
    operator script reach, and it is the same call
    :func:`sandbox.build_sandbox_syscalls` makes minus the composition.
    """
    return SandboxSyscalls(committed_syscalls_policy())
