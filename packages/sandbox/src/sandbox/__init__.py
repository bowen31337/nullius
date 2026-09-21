"""The sandbox member — §5.2's untrusted-code box, and feature 157's seat.

app_spec.xml, "Untrusted Code Sandbox" is a plugin (``plugin="sandbox"``) of
twelve features; this package is the member that carries them, and
docs/nullius-tech-architecture.md §5.2 gives the category its seat in the
pipeline — step 2 of §6.1, ``execute_signal (sandbox) → raw score vector per
rebalance date`` — inside the frozen evaluator whose determinism contract §12
pins.  The module loader (``app.module_loader``) scans the members the root
``pyproject.toml`` declares, imports each package, and composes whatever that
package's ``@register`` builder contributes, so the ``@register`` at the foot
of this file is the entire wiring story: nothing edits a registry, router or
factory to make the sandbox plugin exist.

**What this member contributes today, and why it is a facade over a policy.**
Feature 157 is the category's root — every sibling feature depends on it
(``depends_on="157"``) and each adds a control to the same box — and its
sentence is *"System rejects a run of agent-authored code configured without
gVisor isolation"*.  That is a **configuration law**: it is about the isolation
a run declares, checked before untrusted code executes.  So the composed value
is :class:`SandboxIsolation` — a stateless facade over
:mod:`sandbox.isolation` and the committed policy compiled from
:data:`~sandbox.isolation.COMMITTED_ISOLATION_POLICY` — rather than a runner or
a service.  The distinction matters to every later feature in the category:
network namespace (158), the payload-only channel (159), seccomp (160),
cgroups (162) and the timeout (163) are each *further* controls on the same run,
and each attaches to this member's law rather than replacing it.  A facade that
already resolved a store, a pinned image or a runtime would take composition
down for all of them.

**Why the builder resolves the committed artifact rather than a live runtime.**
:func:`build_sandbox_isolation` compiles the committed policy at build time and
holds no handle to Docker, ``runsc`` or a container.  That is a deliberate
reading of the feature's own word *configured*: the law is about what the run
declares, not about whether a daemon is reachable — and the factory builds
every registered component on every ``create_app()`` call, including the bare
test process and the factory scan, so a builder that dialled a runtime would
make composition depend on a daemon being up.  What the composed component can
do honestly is answer *given this run and this policy, is it configured with
gVisor isolation?* — which is exactly what the pipeline's launcher asks before
it forks.

**Why it cannot return ``None``.**  Every other member's store-shaped
components degrade to ``None`` when nothing names a ``DATABASE_URL``, because a
deployment without a relational store is a discoverable state.  This one has an
artifact in the repository — the committed policy ships with the package — so
there is no unconfigured state to be in: the policy compiles or the member is
broken.  That is the honest shape for a *law* rather than a store, and it is
what lets a caller read a non-``None`` component as proof the isolation law is
loaded.  The one thing the builder must not do is raise for a *drifted*
artifact — the factory builds every component on every composition — so a
compilation failure is reported the way the member's other ambient failures
are: the component is built around the refusal-free path, and the compile
itself is reached by a caller that asks
(:func:`sandbox.isolation.committed_isolation_policy`), where a named
:class:`~sandbox.errors.GVisorIsolationRequired` is the right answer.

**The member's error vocabulary is its own.**  :mod:`sandbox.errors` shares no
hierarchy with the evaluator's or the tripwires': the box untrusted code is put
inside must not carry a dependency whose refusals a caller could confuse with
its own, and a caller catching a tripwire's error will not swallow an isolation
refusal.  ``py.typed`` ships beside this file, so the annotations are the
caller's problem to type-check as well as mine.

**Feature 167 rides the same seat, as a second component.**  The category's
later features each add a control to the same box, and the import allowlist is
the first to arrive: *System rejects a submitted module importing anything
outside the configured allowlist, which returns a disallowed_import error
message.*  Its law lives in :mod:`sandbox.imports` — a screen over a
*submitted module's* imports against a *configured* ceiling, the committed
:data:`sandbox.imports.COMMITTED_IMPORTS_ALLOWLIST` — and its component
(:class:`SandboxImports`, a facade of the same stateless shape as
:class:`SandboxIsolation`) registers beside the isolation law under
:data:`sandbox.imports.IMPORTS_COMPONENT_NAME` (``sandbox-imports``) rather
than replacing it: the factory's registry is keyed by name, a second
registration of ``sandbox`` would overwrite feature 157's law, and one member
carrying two controls means two components, each answering its own feature's
question — the shape the tripwires' and the canary's members already give
their later features.  The builder below is the entire wiring story for both.

**Feature 166 rides the seat a third time.**  *System transfers the materialized
window as Arrow IPC, which returns the resulting score vector over the same
channel* is the category's payload-channel control, and its law lives in
:mod:`sandbox.transfer`: one channel, two legs, each leg a self-describing
framed container, with the return validated positionally against the universe
the window carried.  It composes as :class:`SandboxTransfer` under
:data:`sandbox.transfer.TRANSFER_COMPONENT_NAME` (``sandbox-transfer``) — a
third seat beside the other two, for the same registry-replacement reason —
and it is the first control in the category with **no committed artifact**,
deliberately: the other two are laws about a *configuration* (which isolation a
box declares, which imports a submission may reach) and a configuration has to
be written down before it can be checked, while this one is about a *format*
and an alignment, neither of which a deployment could set differently.
Inventing a ``transfer_policy.json`` here would be inventing a knob nobody
turns.

It carries nothing at all — no channel, no buffer, no handle — a sharper
version of the same choice the other two make by carrying no runtime: a
transfer is a thing that *happens*, and a component shared across runs that
held a channel would be a component letting two runs share a window.  The
channel is therefore handed out per call (:meth:`SandboxTransfer.channel`), and
:meth:`SandboxTransfer.round_trip` takes the run's producer as a *callable* so
the box's execution stays where §6.1 step 2 puts it — the evaluator's
host-side runner — and this member never grows one.  It is also the first
control whose law is asymmetric in its error shape: the inbound leg raises
(a dispatch by trusted host code, where "these are not a window" has one
sensible response), while the *score* half keeps the category's habit of
turning a per-run failure into a value rather than a traceback.

**Feature 165 rides the seat a fourth time.**  *System passes the node seed
into every sandboxed invocation, persisting that seed on the node record* is
the category's randomness control, and its law lives in :mod:`sandbox.seed`:
one non-negative integer, inside the signed 64-bit range §12's ``node`` row
can hold, carried by the envelope every invocation is described by
(:class:`SandboxInvocation`) and written onto the node record
(:func:`seed_record`).  It composes as :class:`SandboxSeed` under
:data:`sandbox.seed.SEED_COMPONENT_NAME` (``sandbox-seed``) — a fourth seat
beside the other three, for the same registry-replacement reason — and it is
the second control with **no committed artifact**, on the same terms feature
166 states its own: the seed is a value a run is *handed*, not a configuration
a deployment writes down, so there is no file here to drift and no unconfigured
state for a ``None`` to describe.

**It is the category's first law whose subject is a *value* rather than a
gate, and the shape of its refusal follows from that.**  Features 157, 167 and
166 each answer a *subject offered* — a run, a submission, a window — and the
first two answer it as a decision because the pipeline offers thousands of
them unattended.  The seed is §5.2's own call site, one dispatch by trusted
host code, so the refusal is an exception at the last line before the spawn —
and because the caller that most needs to be told its invocation is seedless
is the caller holding the seedless invocation, the *constructor* refuses
nothing and every check lives at
:meth:`SandboxSeed.require`/:meth:`SandboxSeed.check`.  The one silence worth
naming is that a component shared across runs carries no seed: a seed belongs
to one node, and a value held on the component would let two nodes share a
stream — the property :class:`SandboxTransfer` states for its channel, in a
different quantity.

**Feature 164 rides the seat a fifth time.**  *System rejects a sandbox
invocation missing the thread-pinning environment* is the category's
single-threaded-numerics control, and its law lives in :mod:`sandbox.threads`:
§12's two caps — ``OMP_NUM_THREADS`` and ``MKL_NUM_THREADS``, each named with
the library layer it governs — classified in the environment an invocation is
dispatched with, so *missing* covers absent *and* present-at-something-other-
than-the-pin, the second being the one that looks configured.  It composes as
:class:`SandboxThreads` under
:data:`sandbox.threads.THREADS_COMPONENT_NAME` (``sandbox-threads``) — a fifth
seat beside the other four, for the same registry-replacement reason — and it is
the **third control with a committed artifact**, beside feature 157's isolation
policy and feature 167's allowlist: features 165 and 166 shipped none because
their subjects are a value a run is handed and a format, while this one's
subject is an *environment the deployment configures a run with*, which is
written down before it can be checked.  :data:`sandbox.threads.COMMITTED_PINNING_POLICY`
ships beside the law, and the compiler holds it to §12's row: every required
variable present, every one pinned at ``1``, every watched floor declared
nowhere wider than the pin.

**It is feature 137's fact on the other side of the seam, and the two are
deliberately independent.**  ``canary._threads`` is the *worker* law — it reads
a worker's environment and, where a numerics library is loaded, the pool that
library actually resolved — while this one is the *dispatch* law: the ``env=``
clause §5.2 hands into the box.  The cap names and the pin are restated here
with their provenance rather than imported, the discipline feature 165 applies
to :data:`sandbox.seed.ENV_SIGNAL_SEED` against ``evaluator._sandbox``: the box
agent-authored code is put inside must not acquire a dependency on the member
that drives it, and this suite pins the spelling as data.  Like feature 165's
refusal and unlike the two gates', this law's launcher verb *returns* something
— the environment to dispatch with, pins written in the policy's own spelling —
so a caller writes one line and cannot read the environment twice.

**Feature 163 rides the seat a sixth time.**  *System persists a timeout fail
class after hard-killing a sandboxed run that exceeded its 30 second wall clock
budget* is the category's wall-clock control, and its law lives in
:mod:`sandbox.timeout`: the committed budget — §5.2's ``limits=Limits(wall_s=30,
…)``, which the compiler holds the artifact to — compared against the duration a
runner's watchdog measured, with the outcome persisted as §8's ``timeout`` fail
class on the node record.  It composes as :class:`SandboxTimeout` under
:data:`sandbox.timeout.TIMEOUT_COMPONENT_NAME` (``sandbox-timeout``) — a sixth
seat beside the other five, for the same registry-replacement reason — and it is
the **fourth control with a committed artifact**, on the same terms feature 164
states its own: the feature's sentence fixes a number, and a number a watchdog
hard-kills at is a deployment's configuration rather than a value a run carries,
so it is written down before it can be audited.  What that artifact deliberately
does *not* carry is the other three fields of the same ``Limits(...)`` call —
``cpu_s``, ``mem_mb`` and ``pids`` belong to feature 162's cgroup law.

**It is the one law in this member whose subject is a failure rather than a
run, and that inverts its refusal shape.**  Features 157, 164, 165 and 167 each
refuse a run *before* anything executes, so their launcher verbs raise on a
refusal and return on success.  A timeout happens *after* the box was admitted
and spawned, and the pipeline's contract for it is a **recorded outcome**: §5.2's
control table is "Timeout | Hard kill, recorded as ``fail_class=timeout``", §8's
ledger carries ``timeout`` among its four ``outcome`` spellings, §6.1 step 11
charges the trial "even if the node fails.  A failed evaluation still consumed a
hypothesis", and :class:`evaluator.SandboxResult` already returns its kills as
values.  So :func:`sandbox.timeout.kill_timeout` answers with a
:class:`~sandbox.timeout.TimeoutKill` and :meth:`SandboxTimeout.require` returns
it — a kill is never raised, because a raise here would turn one hung signal
into a crashed evaluator over thousands of unattended candidates and would make
the recorded class the runner already wrote a second, disagreeing spelling.  What
*is* refused, loudly, is the *recording* and the *budget*: an elapsed time that
is not a number of seconds, a committed artifact that does not declare §5.2's
thirty, a node record this law cannot write the class onto.  A caller that wants
every kill raised re-raises on ``not None``, and that stays the caller's choice.

**Feature 168 rides the seat a seventh time, and it is the category's last.**
*System returns a structured fail class of ok, timeout, error or tripwire_fail
from every sandboxed run* is the law that **owns §9.1's four-word vocabulary from
the sandbox side**, and its law lives in :mod:`sandbox.failclass`: the table
mapping every class the box can report onto one of §9.1's four, the structured
value carrying the class *and* the class it was translated from, and a gate that
classifies a run rather than raising for it.  It composes as
:class:`SandboxFailClass` under
:data:`sandbox.failclass.FAIL_CLASS_COMPONENT_NAME` (``sandbox-failclass``) — a
seventh seat beside the other six, for the same registry-replacement reason.

**It is the two handoffs the earlier laws already wrote down, collected into one
place.**  Feature 163 restates the four in
:data:`sandbox.timeout.NODE_FAIL_CLASSES` and says why in its own comment —
*"Feature 168 is the law that owns this vocabulary from the sandbox side; this
module knows it in order to leave the other three values alone"* — and its
:func:`sandbox.timeout.timed_out_record` refuses to write its class over a record
naming a different one, *"a quarantined seccomp violation that reads as a timeout,
a crash that reads as a hang"*, with its suite naming the owner: *"re-labelling it
is feature 168's job."*  Feature 161's ``sandbox_escape`` is **not** one of
§9.1's four, so someone has to translate the box's finer vocabulary into the
column's closed one — the runner's ``oom``, ``crash``, ``violation``, ``payload``
and ``empty`` collapse to ``error``, ``sandbox_escape`` becomes ``error`` with its
own spelling kept as the translation's provenance, and ``timeout`` is left exactly
where feature 163 put it.

**It ships no committed artifact, and it is the second law in this member that
can say that.**  Features 165's and 166's seats argue theirs: a *value a run is
handed* and a *format* are not things a deployment could set differently, so a
file would hold a knob nobody turns.  Feature 168's subject is the third of that
kind — a vocabulary §9.1 declares and a mapping §8's definitions of the four words
fix — so a ``failclass_policy.json`` would be the same invented knob, and a
non-``None`` component at this seat is proof only that the law is loaded.

**And it inverts the member's verb shape one last time, in the opposite direction
from feature 163.**  163 is the law whose subject is a failure, so its ``require``
has a pass-through that returns ``None``.  Here ``ok`` is *one of the four the
feature's sentence names* — a member of the vocabulary rather than the absence of
one — so :meth:`SandboxFailClass.require` returns a
:class:`~sandbox.failclass.FailClass` for **every** run it classifies, ``ok``
included: "from every sandboxed run", enforced on the line after the spawn rather
than remembered.  What it refuses is the *classification* — a record that says
nothing about how a run ended, or a class outside the vocabulary — and those two
are refused by name rather than folded into ``error``, because a fabricated
outcome would split every later "how did the trials end?" query into fragments the
spec never named.
"""

from __future__ import annotations

from app.module_loader import register

from .budget import (
    BUDGET_COMPONENT_NAME,
    BUDGET_POLICY_KIND,
    CGROUP_BUDGET_CODE,
    CGROUP_LIMITS_REQUIRED_CODE,
    COMMITTED_BUDGET_POLICY,
    DEFAULT_CPU_S,
    DEFAULT_MEM_MB,
    DEFAULT_PIDS,
    MEASURED_FIELDS,
    MEM_DRIFT_REASON,
    MEMORY_FAIL_CLASS,
    RUNNER_MEM_MB,
    BudgetBreach,
    BudgetDecision,
    BudgetOverrun,
    BudgetReason,
    BudgetRun,
    CgroupLimit,
    CgroupPolicy,
    SandboxBudget,
    check_cgroup_budget,
    classify_amount,
    classify_count,
    classify_seconds,
    committed_budget_policy,
    compile_budget_policy,
    load_budget_policy,
    over_limits,
    sandbox_budget,
)
from .errors import (
    AllowlistDocumentError,
    CgroupBudgetDocumentError,
    CgroupBudgetExceeded,
    DisallowedImportError,
    GVisorIsolationRequired,
    InvocationSeedError,
    IsolationDocumentError,
    NodeSeedDocumentError,
    SandboxBudgetError,
    SandboxError,
    SandboxFailClassError,
    SandboxImportError,
    SandboxIsolationError,
    SandboxSeedError,
    SandboxThreadPinningError,
    SandboxTimeoutError,
    SandboxTransferError,
    ScoreChannelError,
    ThreadPinningDocumentError,
    ThreadPinningRequired,
    TimeoutBudgetDocumentError,
    UnclassifiedRunError,
    UnknownFailClassError,
    WindowTransferError,
)
from .failclass import (
    ERROR_FAIL_CLASS,
    FAIL_CLASS_COMPONENT_NAME,
    FAIL_CLASS_REQUIRED_CODE,
    FAIL_CLASS_TABLE,
    FAIL_CLASS_UNKNOWN_CODE,
    OK_FAIL_CLASS,
    SANDBOX_ESCAPE_CLASS,
    SANDBOX_RUNNER_CLASSES,
    SOURCE_CLASSES,
    TRIPWIRE_FAIL_CLASS,
    FailClass,
    FailClassDecision,
    FailClassReason,
    SandboxFailClass,
    classify_fail_class,
    classify_run,
    sandbox_fail_class,
)

# ``NODE_FAIL_CLASSES`` and ``TIMEOUT_FAIL_CLASS`` are deliberately *not*
# re-imported from :mod:`sandbox.failclass`, even though that module owns the
# vocabulary: both names are already bound above from :mod:`sandbox.timeout`,
# and a second import here would silently rebind them to a different module's
# object — one name, two provenances, and the suite's
# ``NODE_FAIL_CLASSES == SECTION_9_1_VOCABULARY`` assertion would stop saying
# which module it was reading.  The law-side spellings stay reachable as
# :data:`sandbox.failclass.NODE_FAIL_CLASSES` for a caller who wants the owner's
# own constant.
from .imports import (
    COMMITTED_IMPORTS_ALLOWLIST,
    DISALLOWED_IMPORT_CODE,
    IMPORTS_COMPONENT_NAME,
    IMPORTS_POLICY_KIND,
    ImportsAllowlist,
    ModuleDecision,
    ModuleReason,
    SandboxImports,
    committed_imports_allowlist,
    compile_imports_allowlist,
    load_imports_allowlist,
    sandbox_imports,
    screen_module,
)
from .isolation import (
    COMMITTED_ISOLATION_POLICY,
    GVISOR_MECHANISM,
    GVISOR_RUNTIME,
    ISOLATION_REQUIRED_CODE,
    POLICY_KIND,
    ComponentIsolation,
    IsolationPolicy,
    RunDecision,
    RunReason,
    SandboxRun,
    authorize_run,
    committed_isolation_policy,
    compile_isolation_policy,
    load_isolation_policy,
)
from .seed import (
    ENV_SIGNAL_SEED,
    MINT_SALT,
    SEED_COMPONENT_NAME,
    SEED_MAX,
    SEED_MISMATCH_CODE,
    SEED_REQUIRED_CODE,
    SandboxInvocation,
    SandboxSeed,
    SeedDecision,
    SeedReason,
    SeedRecord,
    check_invocation,
    mint_node_seed,
    resolve_seed,
    sandbox_seed,
    seed_record,
)
from .threads import (
    ABSENT,
    COMMITTED_PINNING_POLICY,
    ENV_MKL,
    ENV_OMP,
    PINNED,
    PINNING_POLICY_KIND,
    POOL_FLOOR_VARIABLE,
    REQUIRED_CAPS,
    SINGLE_THREADED,
    THREAD_PINNING_CODE,
    THREADS_COMPONENT_NAME,
    UNPINNED,
    SandboxThreads,
    ThreadCap,
    ThreadDecision,
    ThreadPinningPolicy,
    ThreadReason,
    check_thread_pinning,
    classify_cap,
    committed_thread_pinning_policy,
    compile_thread_pinning_policy,
    load_thread_pinning_policy,
    sandbox_threads,
)
from .timeout import (
    COMMITTED_TIMEOUT_POLICY,
    DEFAULT_WALL_S,
    NODE_FAIL_CLASSES,
    TIMEOUT_COMPONENT_NAME,
    TIMEOUT_FAIL_CLASS,
    TIMEOUT_POLICY_KIND,
    SandboxTimeout,
    TimeoutDecision,
    TimeoutKill,
    TimeoutPolicy,
    TimeoutReason,
    TimeoutRecord,
    TimeoutRun,
    classify_duration,
    committed_timeout_policy,
    compile_timeout_policy,
    exceeded_budget,
    kill_timeout,
    load_timeout_policy,
    sandbox_timeout,
    timed_out_record,
)
from .transfer import (
    SCORE_CHANNEL_CODE,
    SCORE_FRAME_NAME,
    SCORE_MAGIC,
    SCORE_VERSION,
    TRANSFER_COMPONENT_NAME,
    WINDOW_TRANSFER_CODE,
    SandboxTransfer,
    ScoreVector,
    TransferChannel,
    TransferLeg,
    WindowFacts,
    decode_scores,
    encode_scores,
    inspect_window_payload,
    sandbox_transfer,
    scores_alias_payload,
)

__all__ = [
    "ABSENT",
    "BUDGET_COMPONENT_NAME",
    "BUDGET_POLICY_KIND",
    "CGROUP_BUDGET_CODE",
    "CGROUP_LIMITS_REQUIRED_CODE",
    "COMMITTED_BUDGET_POLICY",
    "COMMITTED_IMPORTS_ALLOWLIST",
    "COMMITTED_ISOLATION_POLICY",
    "COMMITTED_PINNING_POLICY",
    "COMMITTED_TIMEOUT_POLICY",
    "COMPONENT_NAME",
    "DEFAULT_CPU_S",
    "DEFAULT_MEM_MB",
    "DEFAULT_PIDS",
    "DEFAULT_WALL_S",
    "DISALLOWED_IMPORT_CODE",
    "ENV_MKL",
    "ENV_OMP",
    "ENV_SIGNAL_SEED",
    "ERROR_FAIL_CLASS",
    "FAIL_CLASS_COMPONENT_NAME",
    "FAIL_CLASS_REQUIRED_CODE",
    "FAIL_CLASS_TABLE",
    "FAIL_CLASS_UNKNOWN_CODE",
    "GVISOR_MECHANISM",
    "GVISOR_RUNTIME",
    "IMPORTS_COMPONENT_NAME",
    "IMPORTS_POLICY_KIND",
    "ISOLATION_REQUIRED_CODE",
    "MEASURED_FIELDS",
    "MEMORY_FAIL_CLASS",
    "MEM_DRIFT_REASON",
    "MINT_SALT",
    "NODE_FAIL_CLASSES",
    "OK_FAIL_CLASS",
    "PINNED",
    "PINNING_POLICY_KIND",
    "POLICY_KIND",
    "POOL_FLOOR_VARIABLE",
    "REQUIRED_CAPS",
    "RUNNER_MEM_MB",
    "SANDBOX_ESCAPE_CLASS",
    "SANDBOX_RUNNER_CLASSES",
    "SCORE_CHANNEL_CODE",
    "SCORE_FRAME_NAME",
    "SCORE_MAGIC",
    "SCORE_VERSION",
    "SEED_COMPONENT_NAME",
    "SEED_MAX",
    "SEED_MISMATCH_CODE",
    "SEED_REQUIRED_CODE",
    "SINGLE_THREADED",
    "SOURCE_CLASSES",
    "THREADS_COMPONENT_NAME",
    "THREAD_PINNING_CODE",
    "TIMEOUT_COMPONENT_NAME",
    "TIMEOUT_FAIL_CLASS",
    "TIMEOUT_POLICY_KIND",
    "TRANSFER_COMPONENT_NAME",
    "TRIPWIRE_FAIL_CLASS",
    "UNPINNED",
    "WINDOW_TRANSFER_CODE",
    "AllowlistDocumentError",
    "BudgetBreach",
    "BudgetDecision",
    "BudgetOverrun",
    "BudgetReason",
    "BudgetRun",
    "CgroupBudgetDocumentError",
    "CgroupBudgetExceeded",
    "CgroupLimit",
    "CgroupPolicy",
    "ComponentIsolation",
    "DisallowedImportError",
    "FailClass",
    "FailClassDecision",
    "FailClassReason",
    "GVisorIsolationRequired",
    "ImportsAllowlist",
    "InvocationSeedError",
    "IsolationDocumentError",
    "IsolationPolicy",
    "ModuleDecision",
    "ModuleReason",
    "NodeSeedDocumentError",
    "RunDecision",
    "RunReason",
    "SandboxBudget",
    "SandboxBudgetError",
    "SandboxError",
    "SandboxFailClass",
    "SandboxFailClassError",
    "SandboxImportError",
    "SandboxImports",
    "SandboxInvocation",
    "SandboxIsolation",
    "SandboxIsolationError",
    "SandboxRun",
    "SandboxSeed",
    "SandboxSeedError",
    "SandboxThreadPinningError",
    "SandboxThreads",
    "SandboxTimeout",
    "SandboxTimeoutError",
    "SandboxTransfer",
    "SandboxTransferError",
    "ScoreChannelError",
    "ScoreVector",
    "SeedDecision",
    "SeedReason",
    "SeedRecord",
    "ThreadCap",
    "ThreadDecision",
    "ThreadPinningDocumentError",
    "ThreadPinningPolicy",
    "ThreadPinningRequired",
    "ThreadReason",
    "TimeoutBudgetDocumentError",
    "TimeoutDecision",
    "TimeoutKill",
    "TimeoutPolicy",
    "TimeoutReason",
    "TimeoutRecord",
    "TimeoutRun",
    "TransferChannel",
    "TransferLeg",
    "UnclassifiedRunError",
    "UnknownFailClassError",
    "WindowFacts",
    "WindowTransferError",
    "authorize_run",
    "check_cgroup_budget",
    "check_invocation",
    "check_thread_pinning",
    "classify_amount",
    "classify_cap",
    "classify_count",
    "classify_duration",
    "classify_fail_class",
    "classify_run",
    "classify_seconds",
    "committed_budget_policy",
    "committed_imports_allowlist",
    "committed_isolation_policy",
    "committed_thread_pinning_policy",
    "committed_timeout_policy",
    "compile_budget_policy",
    "compile_imports_allowlist",
    "compile_isolation_policy",
    "compile_thread_pinning_policy",
    "compile_timeout_policy",
    "decode_scores",
    "encode_scores",
    "exceeded_budget",
    "inspect_window_payload",
    "kill_timeout",
    "load_budget_policy",
    "load_imports_allowlist",
    "load_isolation_policy",
    "load_thread_pinning_policy",
    "load_timeout_policy",
    "mint_node_seed",
    "over_limits",
    "resolve_seed",
    "sandbox_budget",
    "sandbox_fail_class",
    "sandbox_imports",
    "sandbox_isolation",
    "sandbox_seed",
    "sandbox_threads",
    "sandbox_timeout",
    "sandbox_transfer",
    "scores_alias_payload",
    "screen_module",
    "seed_record",
    "timed_out_record",
]

__version__ = "0.1.0"

#: The component name this member registers under — the plugin name
#: app_spec.xml gives the category (``plugin="sandbox"``) and the name of the
#: member's seat in the app namespace (``src/app/modules/sandbox``).  Kept here
#: so anything asking the composed application for the isolation law — by way
#: of the member, not by a hard-coded string — shares one spelling.
COMPONENT_NAME: str = "sandbox"

#: The other five component names — ``IMPORTS_COMPONENT_NAME``,
#: ``TRANSFER_COMPONENT_NAME``, ``SEED_COMPONENT_NAME``,
#: ``THREADS_COMPONENT_NAME`` and ``TIMEOUT_COMPONENT_NAME`` — are not respelled
#: here.  Each is its own law's constant, read out of :mod:`sandbox.imports`,
#: :mod:`sandbox.transfer`, :mod:`sandbox.seed`, :mod:`sandbox.threads` and
#: :mod:`sandbox.timeout` at the top of this module, and the member re-exports
#: them rather than shadowing them: the six component names are each owned by
#: the law that registers under them, and a second assignment here would be a
#: second place for one to drift.


class SandboxIsolation:
    """Feature 157's law, as the value a composed application carries.

    A stateless facade over :mod:`sandbox.isolation` and the committed policy
    it compiled, so a caller holding the composed component can ask the
    feature's question — *may this run of agent-authored code execute, given
    its declared isolation?* — without importing the member's submodules by
    name or re-reading the artifact.  It carries the compiled policy and
    nothing else: no store, no runtime handle, no process, because the feature
    is a law about configuration rather than a mechanism that executes
    anything.

    **``require`` is the verb the launcher wants.**  :meth:`admits` returns the
    gate's decision as a value, for a caller that wants to branch; and
    :meth:`require` turns a refusal into the exception
    (:class:`~sandbox.errors.GVisorIsolationRequired`) a launcher that must not
    proceed calls immediately before forking.  Both reach the same law — one
    shapes the answer as a decision and one as an exception, exactly as the
    compile and the gate do — so a caller never chooses which *law* it checks,
    only which *shape* it wants the refusal in.

    **The delegation is deliberately thin** — each method is one call into
    :mod:`sandbox.isolation` — because a second implementation of the
    comparison, the compile or the membership is exactly what this member's
    one-provenance rule forbids.  What the class adds is discoverability (the
    factory's scan composes it) and a single duck-checkable seam for the app
    seat and the twelve features that follow, not arithmetic.  A second
    spelling of ``is_gvisor`` here would be a second thing to keep in sync
    with §5.2's table.
    """

    __slots__ = ("_policy",)

    def __init__(self, policy: IsolationPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> IsolationPolicy:
        """The compiled isolation policy this component carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator script asking which boxes the deployment covers — reads the
        policy rather than re-deriving it.  Reading it does not widen anything:
        the policy holds no capability, which is the point of the component
        being a facade rather than a runner.
        """
        return self._policy

    def admits(self, component: str, *, payload: object = None) -> RunDecision:
        """Answer whether a run of ``component`` may execute.

        Builds the run from the component name and hands it to the gate, which
        consults the compiled policy.  The keyword is named ``component``
        rather than ``origin`` on purpose: feature 149's gate answers an
        *egress attempt* whose origin is a sandbox, and this one answers a
        *run* whose component is a box — the two features share a membership
        and a word for it, so the composition root spells it once here.
        """
        return authorize_run(
            SandboxRun(component=component, payload=payload), self._policy
        )

    def require(self, component: str, *, payload: object = None) -> None:
        """Refuse unless a run of ``component`` is configured with gVisor.

        The launcher's verb: raises
        :class:`~sandbox.errors.GVisorIsolationRequired` — carrying the gate's
        own operator-facing sentence — when the run is refused, and returns
        ``None`` when it is admitted, so a caller can put it on the last line
        before it spawns a process and have the law enforced there rather than
        remembered.
        """
        self.admits(component, payload=payload).require()

    def isolation_of(self, component: str) -> ComponentIsolation | None:
        """The isolation a component is configured with, or ``None``.

        The read side of the law: *what mechanism does this box run under?* is
        a question a deployment should be able to answer, and answering it from
        the policy is what makes "we run under gVisor" a fact about the
        compiled artifact rather than a claim in a runbook.  ``None`` means the
        policy does not list the component — a statement about the policy, not
        an admission, which is why :meth:`admits` refuses an unlisted component
        rather than reading ``None`` as permission.
        """
        return self._policy.isolation_of(component)

    def components(self) -> tuple[str, ...]:
        """The components this deployment holds to gVisor, in policy order."""
        return self._policy.names()

    def is_gvisor(self, component: str) -> bool:
        """Whether a listed component's compiled isolation is gVisor's.

        ``False`` for a component the policy does not list, which is the
        conservative reading: "unknown" is not "gVisor's", the same answer the
        gate gives.
        """
        isolation = self._policy.isolation_of(component)
        return isolation is not None and isolation.is_gvisor


@register(COMPONENT_NAME)
def build_sandbox_isolation() -> SandboxIsolation:
    """Component builder: feature 157's isolation law (app_spec.xml §5.2).

    Takes no arguments — that is the factory's registration protocol — and
    compiles the committed artifact
    (:data:`~sandbox.isolation.COMMITTED_ISOLATION_POLICY`) at build time.
    Unlike the member-shaped stores elsewhere in this workspace it never
    returns ``None``, and it never raises: the artifact ships inside this
    package, so there is no unconfigured state for a ``None`` to describe, and
    the factory builds every registered component on every ``create_app()``
    call — so a builder that raised on a drifted artifact would take
    composition down for every unrelated feature in the workspace.

    A drifted artifact is therefore *reported*, not swallowed, and the report
    is the member's own: the component is built over the refusal-free path, and
    a caller that must know the artifact is still gVisor's asks
    :func:`sandbox.isolation.committed_isolation_policy` (or, equivalently,
    :meth:`SandboxIsolation.is_gvisor` against its own manifest), where a named
    :class:`~sandbox.errors.GVisorIsolationRequired` is the right answer.  The
    division is the same one every store in this workspace draws between what
    composition may raise and what a caller that *requires* something must
    hear.

    It returns a :class:`SandboxIsolation` rather than the bare policy so the
    composed component is duck-checkable and extensible: the category's eleven
    later features attach to this member — the network namespace, the
    payload-only channel, the seccomp allowlist, the cgroup limits, the
    timeout — and a caller that has the component has the seam they arrive on.
    """
    return SandboxIsolation(committed_isolation_policy())


def sandbox_isolation() -> SandboxIsolation:
    """The isolation law, compiled fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs a run to answer for.
    This is the module-level convenience the member's own tests and any
    operator script reach, and it is the same call
    :func:`build_sandbox_isolation` makes minus the composition.
    """
    return SandboxIsolation(committed_isolation_policy())


@register(IMPORTS_COMPONENT_NAME)
def build_sandbox_imports() -> SandboxImports:
    """Component builder: feature 167's import allowlist (app_spec.xml §5.2).

    The second component this member contributes, beside feature 157's
    isolation law under its own name — the registry is keyed by name and a
    second registration of ``sandbox`` would *replace* the isolation law, so
    a member carrying two controls carries two components, each answering
    its own feature's question.  Like :func:`build_sandbox_isolation`, it
    takes no arguments (the factory's registration protocol), compiles the
    committed artifact
    (:data:`~sandbox.imports.COMMITTED_IMPORTS_ALLOWLIST`) at build time,
    never returns ``None`` and never raises: the artifact ships inside this
    package, so there is no unconfigured state for a ``None`` to describe,
    and the factory builds every registered component on every
    ``create_app()`` call, so a builder that raised on a drifted artifact
    would take composition down for every unrelated feature in the
    workspace.  A drifted artifact is reported the same way the isolation
    law's is: the component is built over the refusal-free path, and a
    caller that must know the ceiling compiled asks
    :func:`sandbox.imports.committed_imports_allowlist` or
    :meth:`SandboxImports.covers` against its own manifest, where a named
    :class:`~sandbox.errors.AllowlistDocumentError` is the right answer.

    It returns a :class:`SandboxImports` rather than the bare allowlist for
    the same reason :func:`build_sandbox_isolation` returns a
    :class:`SandboxIsolation`: the composed component is duck-checkable and
    extensible, and a caller that has it — ``screen`` for the decision,
    ``require`` for the exception a launcher wants on the last line before
    it would have run the module — has the seam the box's remaining
    controls arrive on.
    """
    return SandboxImports(committed_imports_allowlist())


@register(TRANSFER_COMPONENT_NAME)
def build_sandbox_transfer() -> SandboxTransfer:
    """Component builder: feature 166's payload channel (app_spec.xml §5.2).

    The third component this member contributes, beside feature 157's
    isolation law and feature 167's import allowlist, under its own name —
    the registry is keyed by name and a later registration of ``sandbox``
    would *replace* the isolation law, so one member carrying three controls
    carries three components, each answering its own feature's question.

    Unlike the other two builders it compiles **no artifact**, and that
    difference is the feature rather than an omission: features 157 and 167
    are laws about a *configuration* and a configuration must be written
    down before it can be checked, while feature 166's sentence names a
    format, a direction and an alignment — none of which a deployment could
    set differently.  There is nothing here for a committed file to say, so
    there is no committed file, and a caller reading the absence as an
    unconfigured state has it backwards: the transfer is fully specified by
    the contract between this member and feature 14's serializer.

    Like the other two it takes no arguments (the factory's registration
    protocol), never returns ``None`` and never raises — the factory builds
    every registered component on every ``create_app()`` call, so a builder
    that raised would take composition down for every unrelated feature in
    the workspace, and a bare test process with no ``DATABASE_URL`` and no
    lake still composes this one.  Importing this module is likewise free of
    the payload stack: ``pyarrow`` and ``polars`` are reached lazily inside
    the functions that need them, so a composition scan — including §1's
    replay path — pays nothing for a channel it may never open.

    It returns a :class:`SandboxTransfer` rather than a channel, necessarily
    rather than by preference: a channel belongs to one run, and a component
    held across runs that owned one would let two runs share a window.  What
    the composed value gives a caller is the law — ``send`` to validate the
    window leg, ``channel()`` for the per-run seam, ``round_trip`` to execute
    the feature's sentence end to end with the run's producer supplied from
    outside.
    """
    return sandbox_transfer()


@register(SEED_COMPONENT_NAME)
def build_sandbox_seed() -> SandboxSeed:
    """Component builder: feature 165's node seed (app_spec.xml §5.2).

    The fourth component this member contributes, beside feature 157's
    isolation law, feature 167's import allowlist and feature 166's payload
    channel, under its own name — the registry is keyed by name and a later
    registration of ``sandbox`` would *replace* the isolation law, so one
    member carrying four controls carries four components.

    Like :func:`build_sandbox_transfer` it compiles **no artifact**, and for
    the same reason: features 157 and 167 are laws about a *configuration* —
    which isolation a box declares, which imports a submission may reach — and
    a configuration has to be written down before it can be checked, while
    feature 165's subject is *the value a run is handed*: the seed §5.2's call
    site passes as ``seed=node.seed``.  There is no file for a deployment to
    drift to another seed, and a committed ``seed_policy.json`` would be a knob
    nobody turns — the seed comes from the node, which is where §12 stores it.

    Like the other three it takes no arguments (the factory's registration
    protocol), never returns ``None`` and never raises: the factory builds
    every registered component on every ``create_app()`` call, so a builder
    that raised would take composition down for every unrelated feature in the
    workspace, and a bare test process with no ``DATABASE_URL`` and no lake
    still composes this one.  It reads no environment either — the seed law's
    only inputs are an invocation and a node record, both supplied by the
    caller.

    It returns a :class:`SandboxSeed` rather than a seed, necessarily rather
    than by preference: a seed belongs to one node, and a component held across
    runs that carried one would let two nodes share a stream — the same
    property :func:`build_sandbox_transfer` states for its channel.  What the
    composed value gives a caller is the law — ``require`` to hand a launcher
    the integer or the refusal on its last line before the spawn, ``check`` for
    the answer as a value, ``mint``-free by design for a caller that has a node
    identity and needs the seed `:func:`mint_node_seed` derives, and
    :meth:`SandboxSeed.seeded` to audit a batch of invocations that already
    ran.
    """
    return sandbox_seed()


@register(THREADS_COMPONENT_NAME)
def build_sandbox_threads() -> SandboxThreads:
    """Component builder: feature 164's thread-pinning law (app_spec.xml §5.2).

    The fifth component this member contributes, beside feature 157's isolation
    law, feature 167's import allowlist, feature 166's payload channel and
    feature 165's node seed, under its own name — the registry is keyed by name
    and a later registration of ``sandbox`` would *replace* the isolation law,
    so one member carrying five controls carries five components.

    Like :func:`build_sandbox_isolation` and unlike the two builders before it,
    it compiles a **committed artifact** at build time
    (:data:`~sandbox.threads.COMMITTED_PINNING_POLICY`), and that is the third
    control in this category to ship one.  Features 165 and 166 state their
    reason for having none — their subjects are a value a run is *handed* and a
    format, neither of which a deployment could set differently — and this
    feature's subject is neither: it is the environment a deployment
    *configures* a run with, which has to be written down before it can be
    checked.  So the file ships, and the compiler holds it to §12's row: every
    cap the table requires is named, every one is pinned at ``1``, and no
    watched floor is declared wider.

    Like the other four it takes no arguments (the factory's registration
    protocol), never returns ``None`` and never raises: the factory builds every
    registered component on every ``create_app()`` call, so a builder that
    raised on a drifted artifact would take composition down for every unrelated
    feature in the workspace, and a bare test process with no ``DATABASE_URL``
    and no lake still composes this one.  Unlike them it reads no *ambient*
    environment either — the law's subject is the environment an invocation
    carries, never ``os.environ`` — so composition cannot depend on the shell
    that started the process.  A drifted artifact is reported the way the other
    two artifacts' are: the component is built over the refusal-free path, and a
    caller that must know the file still pins §12's row asks
    :func:`sandbox.threads.committed_thread_pinning_policy`, where a named
    :class:`~sandbox.errors.ThreadPinningRequired` is the right answer.

    It returns a :class:`SandboxThreads` rather than a policy, necessarily
    rather than by preference — and the reason is sharper here than for any of
    the four: a component held across runs that carried an *environment* would
    be one letting two invocations share a description, and the concrete failure
    is a run dispatched under another run's environment.  What the composed
    value gives a caller is the law — ``require`` for the environment to
    dispatch with or the refusal on the last line before the spawn, ``check``
    for the answer as a decision, and ``required``/``pins``/``pool_floors`` for
    the read side a deployment audits with.
    """
    return sandbox_threads()


@register(TIMEOUT_COMPONENT_NAME)
def build_sandbox_timeout() -> SandboxTimeout:
    """Component builder: feature 163's wall-clock-budget law (app_spec.xml §5.2).

    The sixth component this member contributes, beside feature 157's isolation
    law, feature 167's import allowlist, feature 166's payload channel, feature
    165's node seed and feature 164's thread-pinning law, under its own name —
    the registry is keyed by name and a later registration of ``sandbox`` would
    *replace* the isolation law, so one member carrying six controls carries six
    components.

    Like :func:`build_sandbox_isolation` and :func:`build_sandbox_threads` it
    compiles a **committed artifact** at build time
    (:data:`~sandbox.timeout.COMMITTED_TIMEOUT_POLICY`) — the fourth in this
    category, and for the same reason the third one ships: the feature's
    sentence fixes a number (*"exceeded its 30 second wall clock budget"*) that
    a deployment enforces with a watchdog, and a number a watchdog kills at has
    to be written down before it can be audited.  The compiler holds the file to
    §5.2's ``wall_s=30`` exactly, so the artifact cannot drift to a budget
    nobody wrote down.  Features 165 and 166 state their reason for having no
    artifact; this is not it.

    Like the other five it takes no arguments (the factory's registration
    protocol), never returns ``None`` and never raises: the factory builds every
    registered component on every ``create_app()`` call, so a builder that
    raised on a drifted artifact would take composition down for every unrelated
    feature in the workspace, and a bare test process with no ``DATABASE_URL``
    and no lake still composes this one.  It reads nothing ambient either — the
    law's subject is a run's *measured* duration, never a clock and never
    ``os.environ`` — so composition cannot depend on the shell that started the
    process, and the component it hands out holds no timer.  A drifted artifact
    is reported the way the other three artifacts' are: the component is built
    over the refusal-free path, and a caller that must know the file still
    declares §5.2's budget asks
    :func:`sandbox.timeout.committed_timeout_policy`, where a named
    :class:`~sandbox.errors.SandboxTimeoutError` is the right answer.

    It returns a :class:`SandboxTimeout` rather than a policy, necessarily
    rather than by preference — and this one's reason is the sharpest of the
    six: a component held across runs that carried a *watchdog* would be one
    measuring a duration that belongs to a single run, so two dispatches would
    share a deadline and the second would be killed for the first's elapsed
    time.  What the composed value gives a caller is the law —
    ``check``/``killed`` for the answer as a value, ``require`` for the kill or
    the refusal on the line after the spawn, ``record`` for feature 163's own
    verb of persisting the fail class onto a node record, and ``wall_s`` for the
    read side a deployment audits with.
    """
    return sandbox_timeout()


@register(FAIL_CLASS_COMPONENT_NAME)
def build_sandbox_fail_class() -> SandboxFailClass:
    """Component builder: feature 168's fail-class law (app_spec.xml, category's last).

    The seventh component this member contributes, beside feature 157's isolation
    law, feature 167's import allowlist, feature 166's payload channel, feature
    165's node seed, feature 164's thread-pinning law and feature 163's
    wall-clock law, under its own name — the registry is keyed by name and a
    later registration of ``sandbox`` would *replace* the isolation law, so one
    member carrying seven controls carries seven components.

    **It compiles nothing, and it is the second builder here that can say that.**
    :func:`build_sandbox_transfer` and :func:`build_sandbox_seed` state the reason
    for their own missing artifacts — a format and a value a run is handed are
    not things a deployment could set differently — and this law is the third of
    that kind: §9.1 declares the four classes and §8's definitions of the words
    fix the mapping into them, so there is no file to compile and no number a
    deployment could drift.  A ``failclass_policy.json`` would hold a knob nobody
    turns, which is the objection :func:`build_sandbox_transfer` raises against
    inventing one.

    Like the other six it takes no arguments (the factory's registration
    protocol), never returns ``None`` and never raises: the factory builds every
    registered component on every ``create_app()`` call, so a builder that raised
    would take composition down for every unrelated feature in the workspace, and
    a bare test process with no ``DATABASE_URL`` and no lake still composes this
    one.  It reads nothing ambient either — the law's subject is a run's
    *reported* outcome, never a clock and never ``os.environ`` — so composition
    cannot depend on the shell that started the process, and the component it
    hands out holds no state at all.

    It returns a :class:`SandboxFailClass` rather than the four classes as a bare
    tuple, necessarily rather than by preference, and this one's reason is the
    plainest of the seven: the law is not a value a caller could read off a
    constant — it is the *table* and the gate that reads a run through it.  What
    the composed value gives a caller is the law — ``check`` for the answer as a
    decision, ``require`` for the class on the line after the spawn (**returning
    a value for ``ok`` too**, which is the one place this verb differs from the
    other six), and ``classes``/``sources`` for the read side a deployment audits
    with.
    """
    return sandbox_fail_class()


@register(BUDGET_COMPONENT_NAME)
def build_sandbox_budget() -> SandboxBudget:
    """Component builder: feature 162's cgroup-limits law (app_spec.xml §5.2).

    The eighth component this member contributes, beside feature 157's isolation
    law, feature 167's import allowlist, feature 166's payload channel, feature
    165's node seed, feature 164's thread-pinning law, feature 163's wall-clock
    law and feature 168's fail-class law — under its own name, because the
    registry is keyed by name and a later registration of ``sandbox`` would
    *replace* the isolation law, so one member carrying eight controls carries
    eight components.  With it the category's twelve features (157–168) each
    have their law in place.

    Like :func:`build_sandbox_isolation`, :func:`build_sandbox_threads` and
    :func:`build_sandbox_timeout` it compiles a **committed artifact** at build
    time (:data:`~sandbox.budget.COMMITTED_BUDGET_POLICY`) — the fifth in this
    category, and for the same reason the fourth one ships: the feature's
    sentence fixes three numbers (*"the cgroup limits for cpu, memory of 2048 MB
    or a process count of 32"*) that a deployment enforces by writing
    ``cpu.max``/``memory.max``/``pids.max``, and a limit a kernel is written
    from has to be written down before it can be audited.  The compiler holds
    the file to §5.2's ``cpu_s=30``/``mem_mb=2048``/``pids=32`` exactly, so the
    artifact cannot drift to a box nobody sized.

    Like the other seven it takes no arguments (the factory's registration
    protocol), never returns ``None`` and never raises: the factory builds every
    registered component on every ``create_app()`` call, so a builder that
    raised on a drifted artifact would take composition down for every unrelated
    feature in the workspace, and a bare test process with no ``DATABASE_URL``
    and no lake still composes this one.  It reads nothing ambient either — the
    law's subject is a run's *measured* cpu time, memory peak and process count,
    never a probe and never ``os.environ`` — so composition cannot depend on the
    shell that started the process, and the component it hands out holds no
    cgroup, no counter and no file descriptor.  A drifted artifact is reported
    the way the other four artifacts' are: the component is built over the
    refusal-free path, and a caller that must know the file still declares
    §5.2's limits asks :func:`sandbox.budget.committed_budget_policy`, where a
    named :class:`~sandbox.errors.SandboxBudgetError` is the right answer.

    It returns a :class:`SandboxBudget` rather than a policy, necessarily rather
    than by preference, and this one's reason is the same as
    :func:`build_sandbox_timeout`'s one law over: a component held across runs
    that carried a *cgroup* — or a probe that read one — would be reading
    counters that belong to a single run, so two dispatches would share a box
    and the second would be rejected for the first's consumption.  What the
    composed value gives a caller is the law — ``check``/``over_limits`` for the
    answer as a value, ``require`` for the refusal on the line after the spawn,
    and ``cpu_s``/``mem_mb``/``pids``/``described`` for the read side a
    deployment audits with.
    """
    return sandbox_budget()
