"""The sandbox member's error vocabulary.

Every refusal this member raises names a *reason* rather than a bare fact,
because a sandboxed run happens inside the frozen evaluator's pipeline
(docs/nullius-tech-architecture.md §5.2, §6.1 step 2) where a failure travels
out as a trial outcome rather than a traceback an operator reads live: §8's
``ok | timeout | error | tripwire_fail`` is only actionable if the exception
behind the ``error`` says *what about the run* was refused.

The split is by *which contract* was violated, never by which line of code
failed — the discipline :mod:`infra.security.sandbox_egress`'s and
:mod:`tripwires.errors` state for their own trees:

* :class:`SandboxIsolationError` — the isolation contract, and feature 157's
  whole subject.  The run's configuration does not carry gVisor isolation: the
  isolation block is absent, it names a mechanism or runtime that is not
  gVisor's, or a component's compiled policy was not gVisor's to begin with.
  This is the one refusal in the member that exists to keep *agent-authored
  code* from executing outside the isolation §5.2's table requires, so its
  subclass :class:`GVisorIsolationRequired` is what a caller sees when the
  feature fires — and every message it carries begins with the greppable code
  :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`
  (``gvisor_isolation_required``), so an operator grepping a log for the
  rejection finds it by the feature's own words, the same discipline
  :class:`nulloracle.errors.IsNullColumnError` applies to ``is_null_column``.

* :class:`IsolationDocumentError` — the *document* contract, a sibling of the
  isolation contract rather than a subclass of it.  The isolation declaration
  is not a document this member can read at all: not a mapping, a missing or
  non-string mechanism, a document that does not say what it is.  Kept apart
  from :class:`SandboxIsolationError` for the reason
  :class:`infra.security.sandbox_egress.EgressPolicyDocumentError` is kept
  apart from its own law: *the document could not be read* and *the document
  grants what the law forbids* are different facts about different things, and
  a caller that conflated them would "fix" a well-formed document that had
  already named the wrong runtime, or go looking for a runtime that was never
  named because a key was misspelled.

* :class:`SandboxImportError` — the import-allowlist contract, and feature
  167's whole subject.  A submitted module imports a term the configured
  allowlist does not cover, or the allowlist document itself could not be
  read.  Its subclass :class:`DisallowedImportError` is the refusal itself,
  and every message it carries begins with the greppable code
  :data:`sandbox.imports.DISALLOWED_IMPORT_CODE` (``disallowed_import``) —
  the feature's own sentence, written as a token, the same discipline
  :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` applies to feature 157's.
  The gate's *returned* refusal carries the same code and the same sentence,
  which is the shape the feature's own sentence asks for: it *returns* a
  ``disallowed_import`` error message.

* :class:`AllowlistDocumentError` — the *document* contract of the import
  law, kept beside :class:`IsolationDocumentError` and apart from
  :class:`DisallowedImportError` for the reason that pair is split: the
  allowlist document is written by trusted code, and one that cannot be read
  — a missing marker, a term that is not a dotted name, one term listed
  twice — is a fact about the *configuration*, not about any module
  submitted against it.

* :class:`SandboxSeedError` — the seed contract, and feature 165's whole
  subject.  A sandboxed invocation that carries no seed, carries one that is
  not a seed, or whose node record disagrees with the seed the invocation
  would carry.  Its subclass :class:`InvocationSeedError` is the refusal of a
  *seedless run* — every message begins with the greppable code
  :data:`sandbox.seed.SEED_REQUIRED_CODE` (``node_seed_required``), the
  discipline :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` applies to
  feature 157's — and :class:`NodeSeedDocumentError` is the refusal of a
  *stored record that contradicts itself*, whose messages begin with
  :data:`sandbox.seed.SEED_MISMATCH_CODE` (``node_seed_mismatch``).

* :class:`SandboxThreadPinningError` — the thread-pinning contract, and
  feature 164's whole subject.  A sandbox invocation was dispatched *without*
  the environment §5.2's call site names — ``OMP_NUM_THREADS=1``,
  ``MKL_NUM_THREADS=1`` — or with one of those variables declared at something
  other than the pin.  Its subclass :class:`ThreadPinningRequired` is the
  refusal itself, every message beginning with the greppable code
  :data:`sandbox.threads.THREAD_PINNING_CODE`
  (``thread_pinning_required``) — the discipline
  :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` applies to feature 157's —
  and :class:`ThreadPinningDocumentError` is the *document* half of the pair:
  the committed pinning policy could not be read as a policy at all.

  **Why a thread count earns an error when nothing about it fails loudly.**
  §5.2 closes its sandbox section with the sentence that makes this a refusal
  rather than a warning — *"Thread-count pinning is not a performance setting.
  Multi-threaded BLAS reductions are non-deterministic in float, which breaks
  P3."* — and a threaded reduction produces neither an exception nor an obviously
  wrong number: it produces a *different last bit*, so a score vector from a
  worker whose OMP cap went missing is a plausible answer that no replay
  reproduces.  That is the same class of invisible failure
  :class:`SandboxSeedError` guards for the run's randomness, one variable over,
  and it is why the two features both refuse at the seam rather than trusting a
  deployment to have exported its environment.

* :class:`SandboxBudgetError` — the cgroup-limits contract, and feature 162's
  whole subject.  A sandboxed run was measured against §5.2's
  ``cpu.max``/``memory.max``/``pids.max`` — ``cpu_s=30``, ``mem_mb=2048``,
  ``pids=32`` — and the measurement could not be taken or could not be
  compared.  Its subclass :class:`CgroupBudgetExceeded` is the refusal the
  feature's own word *rejects* names, every message beginning with the
  greppable code :data:`sandbox.budget.CGROUP_BUDGET_CODE`
  (``cgroup_budget_exceeded``) when a run outran a limit and
  :data:`sandbox.budget.CGROUP_LIMITS_REQUIRED_CODE`
  (``cgroup_limits_required``) when the law could not measure it at all — the
  discipline :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` applies to
  feature 157's — and :class:`CgroupBudgetDocumentError` is the *document*
  half: the committed budget could not be read as one.

  **Why the breach is an error here when feature 163's kill is deliberately
  not one.**  The two features share §5.2's call site and split its five
  arguments between them, and they split the *outcome* the same way: dying at
  the wall clock is an ordinary fate of a bad candidate (the pipeline records
  ``fail_class=timeout`` and moves on), while a run that held the core past
  its budget, allocated past ``memory.max`` or forked past ``pids.max`` is a
  *violation of the box* rather than a property of the hypothesis.  A node that
  gets there is not a candidate that failed; it is a candidate whose
  consumption has to be looked at, which is why the gate still *answers* with
  the readings (so the pipeline can record them) and the raise lives on
  :meth:`sandbox.budget.BudgetDecision.require`, the launcher's last line.

* :class:`SandboxTimeoutError` — the wall-clock-budget contract, and feature
  163's whole subject.  The committed *budget* could not be read as a budget
  (the document half), or a caller asked this law to record a run whose
  elapsed time it cannot describe.  **There is deliberately no error for the
  kill itself**, which is the one thing a reader may expect to find here and
  the absence is the feature: §5.2's table says the timeout is *"Hard kill,
  **recorded** as ``fail_class=timeout``"*, the pipeline persists a failed
  run as a value (feature 79's "a failed evaluation still consumed a
  hypothesis"), and :mod:`evaluator._sandbox` already returns its kills as
  :class:`~evaluator.SandboxResult` values rather than raising them.  So the
  kill has no exception to be, and a timeout that arrives at this member as a
  *raised* error is a host-side failure wearing a familiar name — the reading
  :func:`evaluator.failure_outcome` states for its own seam.  What can fail
  loudly here is the *recording*: an elapsed time that is not a number, a
  budget that is not a positive number of seconds, a record this law cannot
  write the class onto.

* :class:`SandboxFailClassError` — the fail-class contract, and feature 168's
  whole subject.  A sandboxed run's outcome could not be stated as one of
  §9.1's four (``ok | timeout | error | tripwire_fail``): the subject named no
  class at all, or it named one this deployment's box is not known to report.
  **There is deliberately no error for the run's fate**, which is the third
  time this docstring states that absence and the last: a run that timed out,
  crashed, escaped a seccomp filter or was scored is a *value* — §6.1 step 11's
  charge, feature 79's "a failed evaluation still consumed a hypothesis" — and
  feature 168's verb is *returns*.  What can fail loudly here is the
  *classification*: :class:`UnclassifiedRunError` for a record that says
  nothing about how the run ended (``fail_class_required``),
  :class:`UnknownFailClassError` for a class outside the vocabulary
  (``fail_class_unknown``).  Two refusals rather than one because the repairs
  are on opposite sides of the seam — the caller's record is short a column, or
  the box has begun reporting a spelling this law has never seen — and a caller
  that conflated them would go looking at its own writer when the drift is in
  the runner, or the reverse.

* :class:`SandboxSyscallError` — the seccomp-allowlist contract, and feature
  160's whole subject.  A process inside the box attempted a syscall the
  committed ceiling does not name, or an attempt was offered that this law
  cannot read: a syscall that is absent, not a string, blank, or spelled in
  something that is not a syscall name at all.  §5.2's control table is
  ``Syscalls | seccomp allowlist`` and §15's failure table entries the first
  case as a sandbox escape attempt.  **The gate still *answers*** — the
  rejection reaches a caller as a :class:`sandbox.syscalls.SyscallDecision`
  carrying the syscall, the action it met and §15's ``sandbox_escape`` class, so
  the pipeline can record the violation and hand its node to feature 161 — and
  the raise lives on :meth:`sandbox.syscalls.SyscallDecision.require`, the
  launcher's last line after the filter is armed.  The document half
  (:class:`SyscallsDocumentError`) is the committed allowlist failing to
  compile, which is the *widening* drift this law exists to catch: an artifact
  whose ``default_action`` no longer denies is a box that admits everything it
  does not name.

There is deliberately no error for *"the run was not admitted"* beyond
:class:`GVisorIsolationRequired`.  Feature 157's failure mode is one thing —
a run configuration that is not gVisor's — and splitting it into an error per
spelling (absent block, ``runc``, a micro-VM, an empty string) would let a
caller catch the spellings it happened to think of and miss the one the
deployment actually configured.  The same restraint shapes
:class:`SandboxSeedError`: *"this run carries no seed this law can pass"* is
one fact with several spellings (absent, ``None``, a string, a ``bool``, a
negative integer), and a caller that had to catch each spelling would miss the
one its deployment actually produced.  Feature 160's rejection follows it too:
a syscall outside the ceiling and an attempt this law cannot read are one
caller-side fact — *this call is not admitted* — and splitting them would make
a launcher catch the spelling its runtime happened to report and miss the one
its kernel actually produced.
"""

from __future__ import annotations

__all__ = [
    "AllowlistDocumentError",
    "CgroupBudgetDocumentError",
    "CgroupBudgetExceeded",
    "DisallowedImportError",
    "DisallowedSyscall",
    "GVisorIsolationRequired",
    "InvocationSeedError",
    "IsolationDocumentError",
    "NodeSeedDocumentError",
    "QuarantineTreeError",
    "SandboxBudgetError",
    "SandboxError",
    "SandboxEscapeQuarantine",
    "SandboxFailClassError",
    "SandboxImportError",
    "SandboxIsolationError",
    "SandboxQuarantineError",
    "SandboxSeedError",
    "SandboxSyscallError",
    "SandboxThreadPinningError",
    "SandboxTimeoutError",
    "SandboxTransferError",
    "ScoreChannelError",
    "SyscallsDocumentError",
    "ThreadPinningDocumentError",
    "ThreadPinningRequired",
    "TimeoutBudgetDocumentError",
    "UnclassifiedRunError",
    "UnknownFailClassError",
    "WindowTransferError",
]


class SandboxError(Exception):
    """The base of every refusal this member raises.

    One base class so a caller — the pipeline step that executes a signal, a
    campaign driver, a CI check that recompiles the committed isolation
    artifact — can catch every failure of the sandbox path with a single
    ``except``.  The member imports no other workspace member (the sandbox is
    the thing untrusted code is put inside, so its own vocabulary must not
    depend on anything that could be handed to it), and its errors therefore
    share no hierarchy with the evaluator's or the tripwires': a caller
    catching :class:`tripwires.errors.TripwireError` will not accidentally
    swallow a sandbox refusal, and vice versa.
    """


class SandboxIsolationError(SandboxError):
    """The isolation contract: a run was configured without gVisor isolation.

    app_spec.xml, "Untrusted Code Sandbox", feature 157: *System rejects a run
    of agent-authored code configured without gVisor isolation.*  The two
    moments this class covers are the two the feature's own sentence draws
    between — a *configuration* proposed as a document (compile time, fail
    closed, nothing applied) and a *run* offered to the launcher (answer time,
    refused before anything executes).

    Raised rather than returned, for the reason
    :class:`infra.security.loop_credentials.ZoneWritePermissionRejected` is:
    the configuration is written by *trusted* code — an operator, a campaign
    driver, a deployment manifest — not by the untrusted code inside the box,
    so a caller that got the isolation wrong gets an exception it cannot
    ignore.  The alternative shape would be worse than a bug: a launcher that
    answered a bad configuration with a *value* would need a caller to check
    it, and the failure mode this feature exists to prevent is agent-authored
    code running with nothing under it while the pipeline reports an ordinary
    trial outcome.
    """


class GVisorIsolationRequired(SandboxIsolationError):
    """The refusal itself: this run is not configured with gVisor isolation.

    Every message begins with ``gvisor_isolation_required``
    (:data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`), the one spelling a
    log-grepping operator or CI check looks for, and names the offending value
    — the mechanism and runtime that were configured instead, or the key that
    was absent — so the drift is findable rather than merely refused.  The
    spelling is the feature's own subject written as a code: §5.2's table row
    is ``Isolation | gVisor (runsc)``, §18's stack table chose ``gVisor
    runsc`` for the deployment, and a message that said only "isolation
    refused" would hide which of the two a drifted configuration was missing.

    Deliberately not a :class:`PermissionError`, unlike feature 147's zone
    write refusal.  That refusal stands where the operating system would have
    produced an ``EACCES``, so it is *shaped* like a permission error to be
    caught by the same ``except``; this one stands where no kernel is
    consulted at all — the run is refused before a process exists — and
    dressing it as a filesystem accident would send an operator looking for a
    permissions problem in a deployment that has none.
    """


class IsolationDocumentError(SandboxIsolationError):
    """The isolation declaration is not a document this member can read.

    A policy document that does not declare itself (the marker feature 149's
    and 148's committed artifacts carry), an ``isolation`` block that is
    absent, is not a mapping, or whose ``mechanism``/``runtime`` are not
    strings.  Refused, fail closed — the whole document, not the unreadable
    key skipped — because a configuration compiled from a partially-read
    document is one whose file and whose run disagree, and that disagreement
    is where the next drift lives.

    Kept outside the isolation contract proper, and stated here so a caller can
    tell the two apart: this error is about a document *nobody can read*, where
    :class:`GVisorIsolationRequired` is about a document that read perfectly
    well and named the wrong isolation.  The second is the feature working; the
    first is the feature unable to say what it found.
    """


class SandboxImportError(SandboxError):
    """The import-allowlist contract: a submission outside what is configured.

    app_spec.xml, "Untrusted Code Sandbox", feature 167: *System rejects a
    submitted module importing anything outside the configured allowlist,
    which returns a disallowed_import error message.*  The subject has moved
    from feature 157's *run* to the *module a run would execute* — §5.2's
    ``code=node.code``, checked statically at the moment it is offered, before
    anything executes — and from the isolation a box declares to the modules a
    submission may import: §10.2's "any import outside an allowlist" and
    §11.1's "no imports outside the allowlist", the row §12 states from the
    determinism side ("blocked by the import allowlist").

    Raised rather than returned only at the bridge
    (:meth:`sandbox.imports.ModuleDecision.require`) and for the document
    contract below — the gate itself *answers* a submission with a decision,
    for the reason feature 157's gate does: the pipeline offers thousands of
    submissions unattended, and a screen that raised per module would turn one
    bad candidate into a crashed evaluator.
    """


class DisallowedImportError(SandboxImportError):
    """The refusal itself: this module imports outside the configured allowlist.

    Every message begins with ``disallowed_import``
    (:data:`sandbox.imports.DISALLOWED_IMPORT_CODE`), the one spelling the
    feature's own sentence gives the rejection, so a log-grepping operator or
    CI check finds it by the feature's words.  The message the gate *returns*
    carries the same code and the same sentence — the sentence says the system
    "returns" it — and this class is that message in the exception shape a
    launcher that must not proceed asks for with ``require()``.

    The refusal names every offending term with its line, never only the
    first: the reader of the refusal is the author of the submission (the
    loop, or the operator debugging it), and a screen that reported one
    offender at a time would be resubmitted to learn the rest — the same
    discipline :mod:`canary._allowlist` states for its own collective
    refusal, stated here rather than shared by import because the sandbox is
    the box untrusted code is put inside and its vocabulary must not depend
    on anything that could be handed to it.
    """


class AllowlistDocumentError(SandboxImportError):
    """The configured allowlist is not a document this member can read.

    A document that does not declare itself (the marker feature 157's
    committed policy and feature 149's committed egress artifact carry), an
    ``allow`` list that is not a list, a term that is not a dotted Python
    name (a leading dot, a star, an empty segment), or one term listed twice.
    Refused, fail closed — the whole document, not the unreadable term
    skipped — because an allowlist compiled from a partially-read document is
    one whose file and whose ceiling disagree, and that disagreement is where
    the next drift lives.

    The counterpart of :class:`IsolationDocumentError`, and kept apart from
    :class:`DisallowedImportError` for the reason that pair is split: the
    allowlist is written by *trusted* code, and its refusals are facts about
    a deployment's configuration; the submissions screened against it are
    untrusted, and their refusals are the feature working.
    """


class SandboxTransferError(SandboxError):
    """The payload-channel contract: what crosses the channel did not.

    app_spec.xml, "Untrusted Code Sandbox", feature 166: *System transfers the
    materialized window as Arrow IPC, which returns the resulting score vector
    over the same channel.*  The subject is the *channel* — §5.2's payload
    channel, the one path into and out of a box that has no mounts
    (``Filesystem | No mounts. Data arrives over IPC only.``) — and this class
    is its refusals.

    **Why the transfer has refusals at all, when the box holds the bytes.**
    The sandbox never reads a window or a score off disk; it reads them off a
    buffer that arrived over the channel.  So a transfer can fail in ways no
    computation can: bytes that are not a window payload, a payload whose
    frames cannot be read, a score vector that is not a score vector, a channel
    that was already spent.  Each of those is a fact about *the bytes that
    crossed* rather than about the signal, and a caller that caught them as
    :class:`SandboxIsolationError` would go looking for a misconfigured box
    when the fault is in what it sent.

    **Raised rather than returned, unlike the two laws' gates.**  Features
    157's and 167's refusals are *answers* — a run and a submission are offered
    unattended, thousands of them, so their gates return decisions and the
    pipeline reads a value rather than surviving a traceback.  A transfer is
    not offered in that sense: it is one dispatch by trusted host code
    (§5.2's own call site), and there is exactly one sensible response to "the
    bytes you sent are not a window" — do not run, fix the dispatch.  So the
    channel raises, and the *score* half of feature 166 is where a per-run
    failure stays a value: see :meth:`sandbox.transfer.ScoreVector.require`.
    """


class WindowTransferError(SandboxTransferError):
    """The bytes that arrived are not a materialized window.

    The inbound half of :class:`SandboxTransferError`.  A payload that is
    empty, is not a serialized window at all, was built by a window that holds
    no frames, or whose frames glued out of frames cannot be read.

    Deliberately not a subclass of the contract's own
    :class:`contract.payload.PayloadFormatError`, and deliberately not caught
    from it either: the sandbox is the box agent-authored code is put inside,
    and its vocabulary must not depend on the contract's — a caller that
    catches :class:`SandboxError` gets every refusal of this member without
    also being subscribed to the contract's.  The translation happens once, at
    the seam, so the member's caller never sees a foreign type: the reason
    :class:`infra.security.sandbox_egress` states for its own translation, and
    the reason a shared helper raising another feature's error defeats the
    caller's ``except``.
    """


class ScoreChannelError(SandboxTransferError):
    """The bytes that arrived are not a score vector for the window sent.

    The outbound half of :class:`SandboxTransferError` — the ``which returns
    the resulting score vector over the same channel`` clause, when what came
    back cannot be read as one.  A return that is empty, is not one of the
    channel's messages, carries no scores, or whose scores disagree with the
    window they are supposed to score: a different length, a non-finite value,
    a dtype that cannot be ranked.

    **The length check is the load-bearing one.**  A score vector is
    positional against the window's universe (feature 11's "indexed by symbol"
    is a positional correspondence, and :func:`contract.signal.validate_signal_return`
    says so), so a return of the right shape but the wrong length is a
    misalignment that would travel silently into the cross-sectional reduction
    downstream and poison every number after it.  It is refused here, at the
    seam, naming both lengths — the same "misaligned before any per-symbol
    check could mean anything" judgement the contract's validator makes for a
    live return, applied to one that crossed a channel.

    Every message begins with ``score_channel``
    (:data:`sandbox.transfer.SCORE_CHANNEL_CODE`) so an operator grepping a log
    for the rejection finds it, the discipline feature 157's and 167's codes
    take.  Kept apart from :class:`WindowTransferError` because the two name
    opposite directions of one channel, and a caller reading a failure wants to
    know which leg it was on before it wants the detail.
    """


class SandboxThreadPinningError(SandboxError):
    """The thread-pinning contract: a run went out without §12's two caps.

    app_spec.xml, "Untrusted Code Sandbox", feature 164: *System rejects a
    sandbox invocation missing the thread-pinning environment.*  The subject is
    the *environment* §5.2's call site names — one of the three clauses of the
    call, beside the code and the seed — and this class is its refusals.

    **The feature's own verb is *missing*, and the spelling is checked from
    both sides.**  A variable that is *absent* is missing; so is one that is
    present and *blank* (``""``, ``"   "``), which looks configured and names no
    count, so the library reading it applies its own default of one worker per
    core — a threaded worker wearing the shape of a pinned one.  And so is a
    variable declared at a value that is not the pin, because §12's row names
    one value and ``2`` is a *choice* the libraries admit and the row does not:
    a law that read only for presence would certify every worker that exported
    ``OMP_NUM_THREADS=16``.  The pool floor the sandbox member knows by name
    (:data:`sandbox.threads.POOL_FLOOR_VARIABLE`) is refused on the same terms
    when it is declared wider than the pin, since it outranks the caps inside
    the library that reads it.

    **Raised rather than returned, like the seed's law and unlike the two
    gates'.**  The environment is §5.2's own call site — one dispatch by trusted
    host code — and not a subject untrusted code offers thousands of times, so
    there is exactly one sensible response to "this invocation is unpinned": do
    not spawn, because the run that proceeded would report an ordinary trial
    outcome for a score no replay reproduces.  The gate still *answers* as a
    value for a caller that wants to branch or to audit a batch
    (:meth:`sandbox.threads.SandboxThreads.check`), and both shapes reach one
    implementation, so a decision and an exception cannot disagree.
    """


class ThreadPinningRequired(SandboxThreadPinningError):
    """The refusal itself: this invocation is missing the pinning environment.

    Every message begins with ``thread_pinning_required``
    (:data:`sandbox.threads.THREAD_PINNING_CODE`), the one spelling a
    log-grepping operator or CI check looks for, and names the offending
    variable *and the library layer it governs* — the layer is the word an
    operator can act on, the same reason
    :data:`canary._threads.THREAD_ENV_CAPS` carries it for the worker-side
    sweep.  The four spellings are kept apart because the repairs differ:
    a variable that was never exported is looked for in the launcher, a blank
    one in whatever templated the environment, a numeric count wider than one in
    the deployment's own configuration, and a value no parser resolves to a
    count in the manifest that wrote it.
    """


class ThreadPinningDocumentError(SandboxThreadPinningError):
    """The committed pinning policy could not be read as a policy.

    The counterpart of :class:`IsolationDocumentError` and
    :class:`AllowlistDocumentError`, kept apart from
    :class:`ThreadPinningRequired` for the reason that pair is split: *the
    document could not be read* and *this run is missing its pins* are
    different facts about different things, and a caller that conflated them
    would go looking for a launcher that dropped an environment variable when
    the fault is a policy file that does not say what it is — or, worse, would
    treat a well-formed document that had already drifted to another pin as a
    launcher bug.
    """


class SandboxBudgetError(SandboxError):
    """The cgroup-limits contract: a run's resource consumption could not be held to the box.

    app_spec.xml, "Untrusted Code Sandbox", feature 162: *System rejects a
    sandboxed run exceeding the cgroup limits for cpu, memory of 2048 MB or a
    process count of 32.*  The subject is the run's *consumption* — §5.2's
    ``limits=Limits(wall_s=30, cpu_s=30, mem_mb=2048, network=False,
    filesystem=False, pids=32)`` clause and the control table's row
    ``Resources | cgroup v2: cpu.max, memory.max, pids.max`` — and this class is
    that clause's refusals.

    **The three quantities are told apart from the fourth argument on purpose.**
    §5.2's call site carries five arguments and the feature sentence names three
    of them; ``wall_s`` belongs to feature 163's wall-clock law and
    :class:`SandboxTimeoutError` answers for it, while ``network`` and
    ``filesystem`` are structural denials of the *isolation* rather than
    budgets of a *count* and feature 157's class answers for them.  A member
    that folded all five into one refusal would report a run that exhausted its
    cpu budget and a run that was handed a socket as the same failure, and the
    operator — or the quarantine decision — needs them apart.

    **Why an exceeded limit is an error here.**  Feature 163's docstring argues
    at length that a wall-clock kill is deliberately *not* one of its refusals:
    the run died at the wall, the pipeline records the class, and feature 79's
    "a failed evaluation still consumed a hypothesis" says the failure is a
    value.  This class's headline refusal reads the other way, and the
    difference is what the two facts *mean*.  A run that ran out of wall clock
    is a bad candidate; a run that held a core past its budget, allocated past
    ``memory.max`` or forked past ``pids.max`` is a *box violation* — §3's zone
    map puts it in Z1 ("Mutated by the loop … Sandboxed: no network, no FS,
    seccomp, cgroup limits"), and a candidate that reached a cgroup limit is one
    whose consumption an operator has to look at rather than one to score and
    drop.  So the gate answers with the readings (the pipeline must still record
    them) and the raise lives on :meth:`sandbox.budget.BudgetDecision.require`,
    the line after the spawn — the split
    :class:`SandboxIsolationError` draws for feature 157's own configuration.

    What this class covers is therefore two facts: a *run* whose measured
    consumption outran a deployed limit, or which this law could not measure at
    all, and a *document* whose limits are not §5.2's.
    """


class CgroupBudgetExceeded(SandboxBudgetError):
    """The refusal itself: this run is rejected, or the budget is not §5.2's.

    Every message begins with a greppable code — ``cgroup_budget_exceeded``
    (:data:`sandbox.budget.CGROUP_BUDGET_CODE`) when a run outran a limit,
    ``cgroup_limits_required``
    (:data:`sandbox.budget.CGROUP_LIMITS_REQUIRED_CODE`) when the law could not
    measure it or when the committed document declares a limit other than the
    call site's — so an operator grepping a log finds the rejection by the
    feature's own words, the discipline feature 157's
    ``gvisor_isolation_required`` and feature 167's ``disallowed_import`` set
    for theirs.

    **The two codes are one class because they are one repair.**  A run refused
    on a reading and a deployment refused on its own file both end at the same
    operator question — *what is this box allowed to consume?* — and the
    caller's action is identical in both: do not dispatch, go look at the
    budget.  Splitting them would make a caller catch two spellings and miss the
    one its deployment produced, which is the restraint
    :class:`GVisorIsolationRequired`'s docstring states for feature 157's
    several spellings of one fact.

    Raised rather than returned only at the bridge
    (:meth:`sandbox.budget.BudgetDecision.require`): the gate *answers* a run
    with a decision, because the pipeline dispatches thousands of unattended
    candidates and "this one outran a cgroup" must reach an operator as a fact
    about a run rather than a crashed evaluator.  A launcher on the last line
    after the spawn calls ``require`` and takes the raise, because a run that
    proceeded would report an ordinary trial outcome for a candidate that was
    never confined.
    """


class CgroupBudgetDocumentError(SandboxBudgetError):
    """The committed cgroup budget could not be read as a budget.

    The counterpart of :class:`IsolationDocumentError`,
    :class:`AllowlistDocumentError`, :class:`ThreadPinningDocumentError` and
    :class:`TimeoutBudgetDocumentError`, kept apart from
    :class:`CgroupBudgetExceeded` for the reason that pair is always split: *the
    document could not be read* and *this run outran its limits* are different
    facts about different things, and a caller that conflated them would go
    looking at a runner's counters when the fault is a policy file that does not
    say what it is — or, worse, would treat a well-formed budget that had
    drifted to another number as a runner bug.

    A document that does not declare itself (:data:`sandbox.budget.BUDGET_POLICY_KIND`,
    the marker feature 157's isolation policy, feature 167's allowlist, feature
    164's pinning policy and feature 163's budget carry), a ``cpu_s``,
    ``mem_mb`` or ``pids`` that is absent, is not a number, is text or bytes, is
    a ``bool``, is a fractional count, or is negative: refused whole, fail
    closed, because a budget compiled from a partially-read document is one
    whose file and whose cgroup disagree — and that disagreement is a box
    confining untrusted code at a number nobody wrote down.
    """


class SandboxTimeoutError(SandboxError):
    """The wall-clock-budget contract: the budget could not be read, or the
    timeout could not be recorded.

    app_spec.xml, "Untrusted Code Sandbox", feature 163: *System persists a
    timeout fail class after hard-killing a sandboxed run that exceeded its 30
    second wall clock budget.*  The subject is the run's *wall clock* — §5.2's
    ``limits=Limits(wall_s=30, …)`` clause and the control table's row
    ``Timeout | Hard kill, recorded as fail_class=timeout`` — and this class is
    that clause's refusals.

    **The kill is not one of them, and that is the feature rather than a gap.**
    A timeout is the member's *one* terminal state that is deliberately not a
    refusal: the sandbox hard-kills the child and the pipeline records the
    outcome, because §6.1 step 11 writes the trial charge "even if the node
    fails. A failed evaluation still consumed a hypothesis."  So
    :func:`sandbox.timeout.kill_timeout` returns a
    :class:`~sandbox.timeout.TimeoutKill` value — the fail class, the budget,
    the elapsed time — and never raises for the kill itself, mirroring
    :meth:`evaluator._sandbox.SignalSandbox.run`.  A caller that *does* see a
    :class:`TimeoutError` from the box has a host-side failure, not this law's
    subject, which is the distinction :func:`evaluator.failure_outcome` draws
    from the other side of the same seam.

    What this class is for is the two things that can genuinely go wrong
    around that kill: a *committed budget* that cannot be read as a budget
    (:class:`TimeoutBudgetDocumentError`), and the **recording** half of the
    feature — an elapsed time that is not a number of seconds, a budget that
    is not a positive number of seconds, or a node record this law cannot
    write the class onto.  The feature's verb is *persists*, so a persistence
    this law could not perform is reported rather than silently skipped: the
    failure mode the whole feature exists to prevent is a run that died at the
    wall and left no row saying so.
    """


class TimeoutBudgetDocumentError(SandboxTimeoutError):
    """The committed wall-clock budget could not be read as a budget.

    The counterpart of :class:`IsolationDocumentError`,
    :class:`AllowlistDocumentError` and :class:`ThreadPinningDocumentError`,
    and kept apart from the recording refusals for the reason that pair is
    always split: *the document could not be read* and *this run's timeout
    could not be written down* are different facts about different things, and
    a caller that conflated them would go looking at a launcher's watchdog
    when the fault is a policy file that does not say what it is — or, worse,
    would treat a well-formed budget that had drifted to another number as a
    runner bug.

    A document that does not declare itself (the marker feature 157's
    isolation policy, feature 167's allowlist and feature 164's pinning policy
    carry), a ``wall_s`` that is absent, is not a number, is a ``bool``, or is
    not a positive number of seconds: refused whole, fail closed, because a
    budget compiled from a partially-read document is one whose file and whose
    watchdog disagree — and the disagreement is a run killed at a number
    nobody wrote down.
    """


class SandboxFailClassError(SandboxError):
    """The fail-class contract: a run's outcome could not be stated as §9.1's.

    app_spec.xml, "Untrusted Code Sandbox", feature 168 — the category's last:
    *System returns a structured fail class of ok, timeout, error or
    tripwire_fail from every sandboxed run.*  The subject is every run the box
    hands back, and this class is the refusals around classifying one — not the
    run's fate.

    **The absences are the feature, and this is the last of them.**  The kill is
    not an error here (:class:`SandboxTimeoutError` says why at length), a
    refused contract is not one (:class:`SandboxImportError`), a seccomp
    violation is not one, and a scored run is obviously not one: all four are
    §9.1's stored vocabulary, and a law that raised for any of them would turn a
    recorded outcome into a crashed evaluator over thousands of unattended
    candidates.  Feature 168's verb is *returns*.  So what this class covers is
    the two ways the *classification* fails:

    * :class:`UnclassifiedRunError` — the subject says nothing about how the run
      ended.  A record naming no class field and no ``problems`` field (an
      unevaluated §9.1 row, a bare object, a writer that forgot the column).
      Refused rather than read as ``ok``, because reading it as a scored run
      would be the absence that reads as a result — the failure
      :mod:`sandbox.transfer` states for its own missing vector — and a failed
      node counted as a successful one is the one error this feature's word
      *every* exists to prevent.
    * :class:`UnknownFailClassError` — the subject names a class outside the
      vocabulary this deployment's box is known to report.  Refused rather than
      folded into ``error``, on :func:`evaluator._debit.failure_outcome`'s rule
      that "a drifted vocabulary must not become a fabricated outcome": a
      misspelt ``"TimeOut"`` becoming ``error`` would read every wall-clock kill
      as a generic crash and send an operator after a fault that is not there.

    Its two subclasses are siblings rather than one subclass of the other, for
    the reason :class:`IsolationDocumentError` and :class:`GVisorIsolationRequired`
    are: the repairs are on **opposite sides of the seam**.  The first is the
    caller's record — a column was never written — and the second is the box's
    vocabulary, which has drifted past what this law accepts.  A caller that
    conflated them would go looking at its own writer when the fault is the
    runner, or repair the runner when the fault is a store row assembled by
    hand.

    Both carry a greppable code — ``fail_class_required``
    (:data:`sandbox.failclass.FAIL_CLASS_REQUIRED_CODE`) and
    ``fail_class_unknown`` (:data:`sandbox.failclass.FAIL_CLASS_UNKNOWN_CODE`)
    — so an operator grepping a log finds the refusal by the feature's own
    words, the discipline feature 157's ``gvisor_isolation_required`` and
    feature 167's ``disallowed_import`` set for theirs.
    """


class UnclassifiedRunError(SandboxFailClassError):
    """A sandboxed run was offered with nothing saying how it ended.

    The subject named no class under any of the fields a class is persisted
    under — §9.1's ``fail_class``, §8's ``outcome``, the store rows'
    ``terminal_class`` — and no sequence of contract problems either, which is
    the evaluator's own way of saying a run was scored.

    Raised rather than returned only at the bridge
    (:meth:`sandbox.failclass.FailClassDecision.require`): the gate *answers* a
    run with a decision carrying this reason, for the reason feature 157's gate
    does — the pipeline classifies thousands of runs unattended, and a law that
    raised per record would turn one short row into a crashed evaluation.  A
    caller on the last line after the spawn calls ``require`` and takes the
    raise, because a run whose outcome cannot be stated is one the pipeline
    cannot honestly record.

    Every message begins with ``fail_class_required``
    (:data:`sandbox.failclass.FAIL_CLASS_REQUIRED_CODE`), the one spelling a
    log-grepping operator looks for, and names the fields it looked under so
    the missing column is findable rather than merely refused.
    """


class UnknownFailClassError(SandboxFailClassError):
    """A sandboxed run was reported with a class outside the vocabulary.

    The subject named a class — so the *record* is fine — and it is not one
    this deployment's box is known to report: neither §9.1's four, nor one of
    the six the runner records, nor feature 161's ``sandbox_escape``.  Either
    the box has begun reporting a class this law has never seen, or the record
    was written by something that is not the runner.

    Deliberately **not** folded into ``error``, and the reason is the same one
    that makes this a separate class rather than a message on the last one:
    ``error`` is a *claim* about how a run failed — §8's "failed any other
    way" — and asserting it for a class this law cannot read would fabricate
    the very fact the column exists to record.  Folding a misspelt ``"TimeOut"``
    in here would read every wall-clock kill as a generic crash, and the
    operator would go looking for a fault that is not there while the real
    repair — a spelling in whatever wrote the record — went unnoticed.  The
    vocabulary is closed, and a member that is not in it is refused by name.

    Every message begins with ``fail_class_unknown``
    (:data:`sandbox.failclass.FAIL_CLASS_UNKNOWN_CODE`) and names the offending
    class *and* the accepted vocabulary, so a reader sees which side drifted.
    """


class SandboxSeedError(SandboxError):
    """The seed contract: the node seed did not reach the invocation.

    app_spec.xml, "Untrusted Code Sandbox", feature 165: *System passes the
    node seed into every sandboxed invocation, persisting that seed on the node
    record.*  The subject is the run's *one source of randomness* — §5.2's
    ``seed=node.seed`` in the call site whose other arguments are the code, the
    payload and the limits — and this class is the refusals that keep it from
    silently going missing.

    **Why a seed deserves its own error when nothing about it can fail.**  The
    seed is not a value the box computes; it is a value the box is *handed*,
    and the failure mode is not a wrong answer but an *absent* one: a launcher
    that spawned a child without the seed would produce a score vector that
    looks exactly like a correct one, from a signal whose ``random.Random(seed)``
    drew from a different stream (or from the interpreter's own entropy) than
    the one the node record says it drew from.  §12's row — "Seeded RNG |
    ``seed`` passed into ``signal()``; stored on the node" — is the whole of the
    determinism contract's randomness clause, and P3 is explicit that a replay
    that is not bit-reproducible makes the replay pool *quietly worthless*:
    "Non-determinism does not announce itself; it just slowly makes every
    conclusion wrong."  So the two places the seed could go missing — the
    invocation that must carry it, and the record that must store it — are
    refusals rather than silent defaults, which is the same stance
    :class:`~sandbox.isolation.GVisorIsolationRequired` takes toward a run's
    declared isolation.

    **Raised rather than returned, unlike the two laws' gates.**  Features
    157's and 167's gates answer *untrusted subjects* — a run, a submission —
    offered thousands of times by an unattended pipeline, so they return
    decisions.  A seed is not offered by untrusted code: it is §5.2's own call
    site, one dispatch by trusted host code, and there is exactly one sensible
    response to "this invocation carries no seed" — do not run, because the run
    that proceeded would be unjustifiable afterwards.  The same split
    :class:`SandboxTransferError` draws for the channel, and for the same
    reason.  The *constructor* of a seedless invocation is therefore not an
    error at all — a caller must be able to build one to be told what is wrong
    with it — and the refusal fires at :meth:`sandbox.seed.SeededInvocation.require`,
    the last line before the spawn.
    """


class InvocationSeedError(SandboxSeedError):
    """The refusal itself: this invocation carries no seed this law can pass.

    Every message begins with ``node_seed_required``
    (:data:`sandbox.seed.SEED_REQUIRED_CODE`), the one spelling a log-grepping
    operator or CI check looks for, and names the offending value *and which
    spelling it was*: absent (the keyword never passed), ``None``, a string
    (``"42"`` — the seed as an environment variable carries it, which is a
    different type in a different place), a ``bool`` (``True`` is not a seed
    anyone meant to write), a negative integer, or one too large for the signed
    64-bit column it is about to be stored in.  The distinction is the point of
    naming them: an operator who sees "absent" looks at the call site, and one
    who sees "negative" looks at whatever minted the seed.

    Deliberately **not** a ``ValueError``, unlike the null oracle's own seed
    refusals.  That member's seed checks guard a *derivation* inside trusted
    arithmetic, where the standard exception is what the surrounding code
    expects; this one guards a value about to be carried into a subprocess by a
    launcher and written to a node row, and a caller that caught the standard
    exception would be subscribing to every other library's value errors along
    with it.  The member's vocabulary is its own for the reason
    :mod:`sandbox.errors`' module docstring gives: the box untrusted code is put
    inside must not carry a dependency whose refusals a caller could confuse
    with its own.
    """


class NodeSeedDocumentError(SandboxSeedError):
    """A stored node record contradicts the seed the invocation would carry.

    The second half of feature 165's sentence — *persisting that seed on the
    node record* — when the record and the run disagree.  A node record whose
    ``seed`` is not a seed at all, and a record whose stored seed is a genuine
    integer that is **not** the seed the invocation carries.

    **The second case is the feature, not a technicality.**  The whole value of
    writing a seed down is that a later reader can re-run the node and get the
    same vector; a record that names a seed other than the one the signal
    actually drew from is worse than no record, because it is a *plausible*
    answer to "what seed was this run?" that no replay would reproduce — the
    §12 failure mode stated as a row rather than as a crash.  So the writer
    refuses rather than overwriting: a record and an invocation are two
    statements about one run, and this law will not write the second while the
    first says something else.

    Messages begin with ``node_seed_mismatch``
    (:data:`sandbox.seed.SEED_MISMATCH_CODE`) and name both values, so the
    reader sees which of the two the disagreement is about rather than being
    told only that they differ.
    """


class SandboxSyscallError(SandboxError):
    """The seccomp-allowlist contract: a call outside what the box is configured to admit.

    app_spec.xml, "Untrusted Code Sandbox", feature 160: *System applies a
    seccomp syscall allowlist, which rejects a process attempting a disallowed
    syscall.*  §5.2's control table gives the posture its own row —
    ``Syscalls | seccomp allowlist`` — §3's zone map states what it serves
    (*"Z1 — Mutated by the loop … Sandboxed: no network, no FS, seccomp, cgroup
    limits"*), and §15's failure table names both the event and its consequence:
    *"Sandbox escape attempt | seccomp violation | Kill, record ``fail_class``,
    quarantine the node and its subtree"*.  This class is the refusal for both
    halves of that row.

    **The violation is not raised by the gate, and that is the feature rather
    than a gap.**  A process inside the box attempting ``openat`` is §15's escape
    attempt, so it is the *most* serious thing this member sees — and it still
    arrives at a caller as a :class:`sandbox.syscalls.SyscallDecision`, because
    §6.1 runs the sandbox unattended over thousands of candidates and an
    evaluator that died on the tenth would take the run with it, and because the
    event has an owner: feature 161 quarantines the node and its subtree, which
    it can only do if it is *handed* something.  So the gate *answers*, the
    decision's :meth:`~sandbox.syscalls.SyscallDecision.violation` publishes the
    ``sandbox_escape`` class the handoff is written from, and the raise lives on
    :meth:`sandbox.syscalls.SyscallDecision.require` — the launcher's last line,
    after the filter is armed and before the process is spawned.  This is the
    split :class:`SandboxBudgetError` draws for feature 162's breach, for the
    same reason: both are *violations of the box* rather than properties of a
    hypothesis, and both end at an operator question rather than a retry.

    What this class covers is therefore two facts: a *call* whose syscall the
    configured ceiling does not name, or which this law cannot read as a syscall
    name at all, and a *document* whose ceiling is not §5.2's.
    """


class DisallowedSyscall(SandboxSyscallError):
    """The refusal itself: this call is not admitted by the configured ceiling.

    Every message begins with a greppable code — ``disallowed_syscall``
    (:data:`sandbox.syscalls.DISALLOWED_SYSCALL_CODE`) when a process reached for
    a syscall the allowlist does not name, ``syscalls_required``
    (:data:`sandbox.syscalls.SYSCALLS_REQUIRED_CODE`) when an attempt was offered
    that this law cannot read as a syscall at all — so an operator grepping a log
    finds the rejection by the feature's own words, the discipline feature 157's
    ``gvisor_isolation_required``, feature 167's ``disallowed_import``, feature
    164's ``thread_pinning_required``, feature 165's ``node_seed_required``,
    feature 162's ``cgroup_budget_exceeded``, feature 163's ``timeout_required``
    and feature 168's ``fail_class_required`` set for theirs.

    **The two codes are one class because they are one repair.**  A box that
    called a syscall nobody configured and a caller that offered a name no filter
    could match both end at the same operator question — *what is this box
    permitted to call, and who told it otherwise?* — and the caller's action is
    identical in both: do not proceed, go read the ceiling.
    :class:`GVisorIsolationRequired`'s docstring states the same restraint for
    feature 157's several spellings of one fact, and a caller that had to catch
    two classes would miss the one its runtime actually produced.

    Deliberately *not* a ``PermissionError`` or an ``OSError``, though the event
    is about permissions a kernel would enforce.  Those are the classes a
    subprocess or ``os`` call raises, and the box this member puts untrusted code
    inside must not carry a refusal a caller could confuse with its own — the
    reason :mod:`sandbox.errors`' module docstring gives for the member's
    vocabulary being its own.  Note also what this class does **not** claim: it
    says a *name* was not admitted, never that an argument was judged.  Seccomp
    filters can match argument values; this law names syscalls, and a refusal
    that implied it had inspected ``openat``'s path would be asserting a decision
    this seam did not make.
    """


class SyscallsDocumentError(SandboxSyscallError):
    """The committed seccomp allowlist could not be read as an allowlist.

    The counterpart of :class:`IsolationDocumentError`,
    :class:`AllowlistDocumentError`, :class:`ThreadPinningDocumentError`,
    :class:`TimeoutBudgetDocumentError`, :class:`CgroupBudgetDocumentError` and
    :class:`NodeSeedDocumentError`, kept apart from :class:`DisallowedSyscall`
    for the reason that pair is always split: *the document could not be read*
    and *this call is outside the ceiling* are different facts about different
    things, and a caller that conflated them would go looking at a candidate's
    syscall trace when the fault is a policy file that no longer says what it is.

    A document that does not declare itself
    (:data:`sandbox.syscalls.SYSCALLS_POLICY_KIND`, the marker feature 157's
    isolation policy, feature 167's allowlist, feature 164's pinning policy,
    feature 163's budget, feature 162's cgroup budget and feature 165's node
    record carry); a ``default_action`` that is **not a denying action** — the
    drift this class exists for, because a filter whose default is ``allow``,
    ``log``, ``trace`` or ``notify`` admits every syscall it does not name, and a
    box running under it would be an ordinary container that believes it is
    sandboxed; a ``default_action`` this law has never heard of, which leaves the
    deployment's entire posture to be guessed from a string; an ``allow`` that is
    not a list; a term that is not a ``lower_snake_case`` syscall name, or that
    appears twice; or a ceiling that admits no way for the process to end (no
    ``exit`` and no ``exit_group``), which kills every candidate at its first
    instruction and leaves nobody to record that it did.  Refused whole, fail
    closed, because a ceiling compiled from a partially-read document is one
    whose file and whose box disagree — and that disagreement is a sandbox
    confining agent-authored code under a filter nobody wrote down.
    """


class SandboxQuarantineError(SandboxError):
    """The quarantine contract: a branch of the discovery tree halted behind a violation.

    app_spec.xml, "Untrusted Code Sandbox", feature 161: *System quarantines a
    node together with its subtree after a seccomp violation, persisting a
    ``sandbox_escape`` fail class.*  §15's failure table gives the row this class
    is the refusal half of — *"Sandbox escape attempt | seccomp violation | Kill,
    record ``fail_class``, quarantine the node and its subtree"* — and §9.1's
    ``fail_class`` column is the vocabulary the recorded half is read against.

    **The three refusals are one class because they are one question.**  The
    trigger is not the ``sandbox_escape`` violation this law exists for
    (``quarantine_required``, :data:`sandbox.quarantine.QUARANTINE_REQUIRED_CODE`);
    the branch cannot be read as a tree at all
    (``quarantine_tree_invalid``,
    :data:`sandbox.quarantine.QUARANTINE_TREE_CODE`); or the nodes the quarantine
    would mark are not the ones the caller holds records for
    (``quarantine_mismatch``,
    :data:`sandbox.quarantine.QUARANTINE_MISMATCH_CODE`).  Each ends at the same
    operator question — *which nodes are halted, and on whose authority?* — and
    each is answered by the same repair: go read the violation, or go read the
    tree.  :class:`SandboxSyscallError`'s docstring makes the same argument for
    feature 160's two spellings of one fact.

    **Why this is a refusal rather than an action.**  Halting a subtree is the
    most consequential thing this member does: every node under the violating one
    stops being evaluated, and §6.1 runs the sandbox unattended over thousands of
    candidates, so a law that quarantined on a guess would silently retire a
    branch of the search on evidence nobody checked.  So
    :func:`sandbox.quarantine.quarantine_violation` *answers* — it returns a
    :class:`~sandbox.quarantine.QuarantineDecision` naming both the class it
    found and the class §15 requires — and the raise lives on
    :meth:`sandbox.quarantine.QuarantineDecision.require` for the caller that
    wants the halt to be fatal.  That is the same split
    :class:`SandboxSyscallError` and :class:`SandboxBudgetError` draw, for the
    same reason: these are violations of the box rather than properties of a
    hypothesis, and all three end at an operator question rather than a retry.

    Deliberately *not* a subclass of any other member's error.  Quarantine
    consumes feature 160's violation handoff, but it does not consume feature
    160's vocabulary of refusal: a caller catching :class:`SandboxSyscallError`
    has caught the *gate's* decision about a syscall, and a caller catching this
    has caught a decision about a *branch* of the discovery tree.  The two
    arrive at different moments in a run and are repaired by reading different
    things, so a caller that had to catch one for the other would be repairing
    the wrong one.
    """


class SandboxEscapeQuarantine(SandboxQuarantineError):
    """The refusal itself: this branch will not be quarantined, and here is why.

    Every message begins with a greppable code — ``quarantine_required``,
    ``quarantine_tree_invalid`` or ``quarantine_mismatch`` (the three constants
    named on :class:`SandboxQuarantineError`) — so an operator grepping a log
    finds the refusal by the feature's own words, the discipline feature 157's
    ``gvisor_isolation_required``, feature 167's ``disallowed_import``, feature
    164's ``thread_pinning_required``, feature 165's ``node_seed_required``,
    feature 162's ``cgroup_budget_exceeded``, feature 163's ``timeout_required``,
    feature 160's ``disallowed_syscall`` and feature 168's
    ``fail_class_required`` set for theirs.

    Note what this class does **not** claim: it never says the seccomp violation
    did not happen.  A subject whose ``fail_class`` reads ``timeout`` or ``error``
    is refused here *because* feature 160's gate and feature 163's clock have
    their own owners and their own records — this law declining to halt a branch
    for them is not this law doubting them.  The one case that is a genuine "no",
    :data:`~sandbox.quarantine.QuarantineReason.NOTHING_TO_QUARANTINE`, is not a
    refusal at all and does not raise: feature 160 documents that an unreadable
    attempt is deliberately not called an escape attempt, so there is no branch
    to halt and the run continues.
    """


class QuarantineTreeError(SandboxQuarantineError):
    """The nodes handed in could not be read as one campaign's discovery tree.

    The counterpart of :class:`IsolationDocumentError`,
    :class:`AllowlistDocumentError`, :class:`ThreadPinningDocumentError`,
    :class:`TimeoutBudgetDocumentError`, :class:`CgroupBudgetDocumentError`,
    :class:`NodeSeedDocumentError` and :class:`SyscallsDocumentError`, kept
    apart from :class:`SandboxEscapeQuarantine` for the reason that pair is
    always split: *the tree could not be read* and *this branch will not be
    quarantined* are different facts about different things, and a caller that
    conflated them would go looking at a syscall trace when the fault is a
    ``node`` table that no longer says what it is.

    Raised for a row that is not a mapping, a node with no id, a node id that
    appears twice, two rows for one node agreeing on nothing, or — the case this
    class exists for — a ``parent_id`` chain that closes on itself.  The last is
    the one worth naming: a ``UNION ALL`` recursion over a ``parent_id`` cycle
    never terminates, so a closure walked in SQL does not *fail* on a cyclic tree,
    it *hangs*, and the guard that would have refused never runs.  This member
    walks the closure in Python over edges the caller hands it, precisely so that
    the cycle arrives here as a refusal a caller can act on.
    """
