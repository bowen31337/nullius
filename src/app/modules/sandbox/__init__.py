"""The sandbox module — app-level entrypoint for the sandbox workspace member.

The implementation lives in the ``sandbox`` workspace member
(``packages/sandbox``, import name ``sandbox``), which self-registers with the
application factory under the component name :data:`COMPONENT_NAME` — scanning
the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` composes feature 157's isolation law, the value the rest of
the "Untrusted Code Sandbox" category (app_spec.xml, ``plugin="sandbox"``)
builds on: the network namespace (158), the payload-only channel (159), the
seccomp allowlist (160), the cgroup limits (162), the timeout (163), the
thread-pinning check (164), the seed (165), the Arrow payload (166), the
import allowlist (167) and the fail-class vocabulary (168).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/sandbox/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

**This seat answers exactly one question — *what is the composed isolation
law?* — and does not re-export the law's vocabulary.**  The run decision, the
reason codes, the policy and the component type live in the member, which is
where they are pinned; a caller who has the component calls its verbs —
``admits`` for a decision, ``require`` for the exception a launcher wants on
the last line before it forks, and ``isolation_of`` for the read side — and
each returns or raises the member's own type.  A second spelling of any of
that here would be a second thing to keep in sync, and the member's
one-provenance rule is the reason the category restates its vocabularies
rather than sharing them by import.

**Unlike the tripwires' seat, this one's ``None`` is a real absence.**  The
tripwires component is a stateless facade over a pure function with no
unconfigured state, so its ``None`` means exactly one thing; this component is
the same *shape* but not the same *fact* — it carries the compiled committed
policy, so an application that composed it holds a policy that was read from
disk and checked.  ``None`` therefore still means only "no sandbox component
was registered" — never "registered but not yet configured", because the
member's builder never returns ``None`` and never defers — but a caller
reading a non-``None`` component here is entitled to the stronger conclusion
that the deployment's isolation artifact compiled, which is a property worth
being able to check at the seat rather than inferring from the builder's
docstring.

**Feature 167's law has its own seat here, beside the isolation law's.**  The
import allowlist — *System rejects a submitted module importing anything
outside the configured allowlist, which returns a disallowed_import error
message* — is the category's second control to land, and it composes as its
own component (``sandbox-imports``) rather than a wider ``sandbox`` one, so
this module answers two questions now: *what is the composed isolation law?*
and *what is the composed import allowlist?*  The second accessor below
(:func:`sandbox_imports_component`) mirrors the first in every respect —
``None`` means "no such component was registered", and a non-``None`` value
is proof the committed allowlist artifact compiled — and re-exports nothing
of the law's vocabulary for the same reason the first does: a caller who has
the component calls its verbs (``screen`` for the decision a submission
earns, ``require`` for the exception a launcher wants), and each returns the
member's own type.

**Feature 166's law has its own seat here too, and it is the third.**  The
payload channel — *System transfers the materialized window as Arrow IPC,
which returns the resulting score vector over the same channel* — composes as
``sandbox-transfer``, so this module now answers three questions: *what is the
composed isolation law?*, *what is the composed import allowlist?* and *what is
the composed payload channel?*  :func:`sandbox_transfer_component` mirrors the
other two in shape, and re-exports nothing of the law's vocabulary for the same
reason they do not — a caller who has the component calls ``send`` to validate
the window leg, ``channel()`` for the per-run seam, or ``round_trip`` to run
the feature's sentence end to end with its own producer.

It differs from the other two in exactly one respect, and the difference is
the feature rather than a gap: there is **no committed artifact** behind it.
Features 157 and 167 are laws about a configuration, and a configuration is
written down before it can be checked — which is why a non-``None`` component
at their seats proves a file compiled.  Feature 166 is a format, a direction
and an alignment, none of which a deployment could set differently, so there
is nothing for a committed file to say and no knob nobody turns. A caller
should not read the missing artifact as an unconfigured state.

**Feature 165's law has its own seat here too, and it is the fourth.**  The
node seed — *System passes the node seed into every sandboxed invocation,
persisting that seed on the node record* — composes as ``sandbox-seed``, so
this module now answers four questions, and :func:`sandbox_seed_component`
mirrors the other three in shape and re-exports nothing of the law's
vocabulary for the same reason they do not: a caller who has the component
calls ``require`` to get the integer to hand the box (or the refusal, on the
last line before it would have spawned), ``check`` for the answer as a value,
and ``seeded`` to audit a batch of invocations that already ran.

It has the missing-artifact property in common with feature 166, and for the
same class of reason: its subject is a value a run is *handed* rather than a
configuration a deployment writes down, so there is no file here to compile
and no unconfigured state for a ``None`` to describe.  What it does *not*
share with the transfer is the shape of its refusal — the seed is law about
the *node*, so its record half is reachable through the member's module-level
verbs as well, and a caller that only holds a record reaches
``sandbox.resolve_seed`` directly, without the component.

**Feature 164's law has its own seat here too, and it is the fifth.**  The
thread-pinning environment — *System rejects a sandbox invocation missing the
thread-pinning environment* — composes as ``sandbox-threads``, so this module
now answers five questions, and :func:`sandbox_threads_component` mirrors the
other four in shape and re-exports nothing of the law's vocabulary for the same
reason they do not: a caller who has the component calls ``require`` to get the
environment to dispatch with (or the refusal, on the last line before it would
have spawned), ``check`` for the answer as a value, and ``required``,
``pins`` and ``pool_floors`` for the read side a deployment audits with.

It is the third of the five seats whose component is backed by a **committed
artifact**, and the first where that is worth stating in the other direction:
features 165 and 166 argued their subjects are a value a run is handed and a
format, neither of which a deployment could set differently, while this one's
subject is the environment a deployment *configures* a run with — so a
non-``None`` component here proves the committed pinning policy compiled, the
same conclusion feature 157's and 167's seats entitle a caller to draw.

**Feature 163's law has its own seat here too, and it is the sixth.**  The
wall-clock budget — *System persists a timeout fail class after hard-killing a
sandboxed run that exceeded its 30 second wall clock budget* — composes as
``sandbox-timeout``, so this module now answers six questions, and
:func:`sandbox_timeout_component` mirrors the other five in shape and
re-exports nothing of the law's vocabulary for the same reason they do not.

It is the fourth of the six seats whose component is backed by a **committed
artifact**, and its subject is the same class as feature 164's: the feature's
sentence fixes a number — §5.2's ``limits=Limits(wall_s=30, …)`` — and a number
a watchdog hard-kills at is a deployment's configuration rather than a value a
run carries, so the artifact ships and the compiler holds it to the thirty.  A
non-``None`` component here therefore proves the committed budget compiled, the
same conclusion the other three artifacts' seats entitle a caller to draw.

What makes this seat's *refusal shape* different from the other five is worth
knowing before calling it.  Features 157, 164, 165 and 167 answer a run offered
*before* anything executes, so ``require`` raises on a refusal; a timeout is an
event *after* the box was admitted and spawned, and §5.2's control table records
it as an outcome ("Timeout | Hard kill, recorded as ``fail_class=timeout``", §8's
ledger carrying the same class, §6.1 step 11 charging the trial regardless).  So
``require`` here returns ``None`` for a run inside its budget, a ``TimeoutKill``
for a run that outran it, and raises only when the run it was handed is
unreadable.  A caller that wants every kill raised re-raises on ``not None``.

**Feature 168's law has its own seat here too, and it is the seventh — and the
category's last.**  The fail-class vocabulary — *System returns a structured fail
class of ok, timeout, error or tripwire_fail from every sandboxed run* — composes
as ``sandbox-failclass``, so this module now answers seven questions, and
:func:`sandbox_fail_class_component` mirrors the other six in shape and re-exports
nothing of the law's vocabulary for the same reason they do not: a caller who has
the component calls ``check`` for the answer as a decision, ``require`` for the
class on the line after the spawn, and ``classes``/``sources`` for the read side
a deployment audits with.

**It is the third seat here with no committed artifact, and its missing file is
the same class of absence features 165's and 166's have.**  Features 157, 167, 164
and 163 are laws about a *configuration* — which isolation, which imports, which
pins, how long — and a configuration is written down before it can be checked, so
a non-``None`` component at their seats proves a file compiled.  Feature 168's
subject is a *vocabulary* §9.1 declares and a *mapping* §8's definitions of its
four words fix; a deployment cannot set either differently, so there is no file
for one to drift to and no knob nobody turns.  A caller should not read the
missing artifact as an unconfigured state, and a non-``None`` component here is
proof only that the law is loaded.

**What makes this seat's verb shape different from all six others is worth knowing
before calling it.**  Feature 163's ``require`` has a pass-through — ``None`` for
a run inside its budget — because its subject is a failure and a run that was fine
has nothing to persist.  Here ``ok`` is *one of the four the feature's sentence
names*, a member of the vocabulary rather than the absence of one, so ``require``
returns a ``FailClass`` for **every** run it classifies, ``ok`` included: "from
every sandboxed run" enforced on the line after the spawn.  What it refuses is the
*classification*, not the fate — a record naming nothing about how a run ended, or
a class outside the vocabulary — and those two raise rather than return a value.

**Feature 162's law has its own seat here too, and it is the eighth.**  The
cgroup limits — *System rejects a sandboxed run exceeding the cgroup limits for
cpu, memory of 2048 MB or a process count of 32* — composes as
``sandbox-budget``, so this module answers eight questions, and
:func:`sandbox_budget_component` mirrors the other seven in shape and re-exports
nothing of the law's vocabulary for the same reason they do not: a caller who has
the component calls ``check`` for the answer as a decision, ``require`` for the
refusal on the line after the spawn, and ``cpu_s``/``mem_mb``/``pids``/``limits``
for the read side a deployment audits with.

**It is the fifth seat here backed by a committed artifact, and it shares its
subject with feature 163's.**  §5.2 describes a run with one call —
``limits=Limits(wall_s=30, cpu_s=30, mem_mb=2048, network=False,
filesystem=False, pids=32)`` — whose five arguments three different features own:
``wall_s`` is feature 163's wall-clock law, ``network`` and ``filesystem`` are
structural denials inside feature 157's isolation, and ``cpu_s``/``mem_mb``/
``pids`` are the cgroup limits this law enforces.  Three of those are *numbers a
deployment writes down* — a watchdog's budget and three ``cgroup v2`` values —
which is why the artifacts ship and their compilers hold each file to §5.2's own
number: a non-``None`` component here is proof the committed budget compiled and
this deployment confines untrusted code to §5.2's cpu, memory and process count,
the same conclusion features 157's, 167's, 164's and 163's seats entitle a caller
to draw.

**This seat's refusal shape matches the other configuration laws', not feature
163's, and the difference is worth knowing before calling it.**  Feature 163's
``require`` passes ``None`` through for a run inside its budget, because a
timeout is the pipeline's *recorded outcome* (§5.2's "Timeout | Hard kill,
recorded as ``fail_class=timeout``") and a run that was fine has nothing to
persist.  Here a run that outran its limits is a *violation of the box* rather
than a bad candidate — §3's zone map makes the cgroup limits a property of Z1, so
reaching one is something an operator has to look at — and ``require`` therefore
returns ``None`` only for a run measured inside every limit and raises
:class:`~sandbox.errors.CgroupBudgetExceeded` for a breach exactly as it does for
a run it cannot measure.  The gate still *answers* with the readings
(``check`` returns a decision carrying the per-limit ``BudgetOverrun`` values, so
the pipeline can record what was consumed), which is what keeps a breach from
becoming a crashed evaluator over thousands of unattended candidates.

**Feature 160's law has its own seat here too, and it is the ninth.**  The
seccomp syscall allowlist — *System applies a seccomp syscall allowlist, which
rejects a process attempting a disallowed syscall* — composes as
``sandbox-syscalls``, so this module now answers nine questions, and
:func:`sandbox_syscalls_component` mirrors the other eight in shape and
re-exports nothing of the law's vocabulary for the same reason they do not: a
caller who has the component calls ``check`` for the answer as a decision
(``allows`` for the bare boolean, ``filter`` for the specification a launcher
arms), and ``require`` for the refusal on the line after the filter is armed.

**It is the sixth seat here backed by a committed artifact, and its artifact is
the one §5.2 leaves its content to the deployment.**  §5.2's table is ``Syscalls
| seccomp allowlist`` — the row names the *mechanism* and no names — so unlike
feature 162's three numbers, feature 163's thirty seconds and feature 164's two
pins, there is no spec value for a compiler to hold the file to.  What the
compiler holds instead is the posture: the document's ``default_action`` must be
a **denying** action, its terms must be well-formed syscall names listed once,
and the ceiling must admit a way for the process to end.  That first check is the
one this seat exists for — an artifact drifted to ``allow``, or to ``log``,
``trace`` or ``notify`` (each of which observes a syscall and lets it through),
is a *widened* box that still looks configured, and it is refused before any
component is handed out.  So a non-``None`` component here is proof the committed
ceiling compiled *and* that it denies by default, while *which* syscalls are
admitted is read from ``allowed()`` rather than promised by this docstring.

**This seat's refusal shape matches feature 162's, and §15 is what decides it.**
``require`` passes ``None`` through for an attempt inside the ceiling, because a
timeout's shape (§5.2's "Timeout | Hard kill, recorded as ``fail_class=timeout``")
does not apply here: a syscall outside the ceiling is §15's *"Sandbox escape
attempt | seccomp violation"*, a violation of the box rather than a bad
candidate, so ``require`` raises for it exactly as it does for an attempt this
law cannot read.  The gate still *answers* — ``check`` returns a decision whose
``violation`` carries the syscall, the action it met and §15's ``sandbox_escape``
class, which is the value feature 161 quarantines a node and its subtree for —
and that class is deliberately **not** one of §9.1's four, so feature 168's table
is what translates it to ``error`` at the seat one law above this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from sandbox import (
        SandboxBudget,
        SandboxFailClass,
        SandboxImports,
        SandboxIsolation,
        SandboxQuarantine,
        SandboxSeed,
        SandboxSyscalls,
        SandboxThreads,
        SandboxTimeout,
        SandboxTransfer,
    )

__all__ = [
    "BUDGET_COMPONENT_NAME",
    "COMPONENT_NAME",
    "FAIL_CLASS_COMPONENT_NAME",
    "IMPORTS_COMPONENT_NAME",
    "QUARANTINE_COMPONENT_NAME",
    "SEED_COMPONENT_NAME",
    "SYSCALLS_COMPONENT_NAME",
    "THREADS_COMPONENT_NAME",
    "TIMEOUT_COMPONENT_NAME",
    "TRANSFER_COMPONENT_NAME",
    "sandbox_budget_component",
    "sandbox_fail_class_component",
    "sandbox_imports_component",
    "sandbox_isolation_component",
    "sandbox_quarantine_component",
    "sandbox_seed_component",
    "sandbox_syscalls_component",
    "sandbox_threads_component",
    "sandbox_timeout_component",
    "sandbox_transfer_component",
]

#: The component name the sandbox member registers under. Kept here so
#: anything asking the composed application for the isolation law — by way of
#: the app package, not the member — shares one spelling.
COMPONENT_NAME = "sandbox"

#: The component name the member's import allowlist registers under — the
#: category's second control, kept beside feature 157's rather than over it,
#: because the factory's registry replaces a name's earlier registration.
#: Kept here for the same reason ``COMPONENT_NAME`` is: one spelling shared
#: by everything that asks for the law through the app package.
IMPORTS_COMPONENT_NAME = "sandbox-imports"

#: The component name the member's payload channel registers under — the
#: category's third control, kept beside the other two rather than over
#: either, because the factory's registry replaces a name's earlier
#: registration.  Kept here for the same reason the other two are: one
#: spelling shared by everything that asks for the law through the app
#: package.
TRANSFER_COMPONENT_NAME = "sandbox-transfer"

#: The component name the member's node seed registers under — the category's
#: fourth control, kept beside the other three rather than over any of them,
#: because the factory's registry replaces a name's earlier registration.
#: Kept here for the same reason the other three are: one spelling shared by
#: everything that asks for the law through the app package.
SEED_COMPONENT_NAME = "sandbox-seed"

#: The component name the member's thread-pinning law registers under — the
#: category's fifth control, kept beside the other four rather than over any of
#: them, because the factory's registry replaces a name's earlier registration.
#: Kept here for the same reason the other four are: one spelling shared by
#: everything that asks for the law through the app package.
THREADS_COMPONENT_NAME = "sandbox-threads"

#: The component name the member's wall-clock-budget law registers under — the
#: category's sixth control, kept beside the other five rather than over any of
#: them, because the factory's registry replaces a name's earlier registration.
#: Kept here for the same reason the other five are: one spelling shared by
#: everything that asks for the law through the app package.
TIMEOUT_COMPONENT_NAME = "sandbox-timeout"

#: The component name the member's fail-class law registers under — the
#: category's seventh and last control, kept beside the other six rather than
#: over any of them, because the factory's registry replaces a name's earlier
#: registration.  Kept here for the same reason the other six are: one spelling
#: shared by everything that asks for the law through the app package.
FAIL_CLASS_COMPONENT_NAME = "sandbox-failclass"

#: The component name the member's cgroup-limits law registers under — the
#: category's eighth control, kept beside the other seven rather than over any
#: of them, because the factory's registry replaces a name's earlier
#: registration.  Kept here for the same reason the other seven are: one
#: spelling shared by everything that asks for the law through the app package.
#:
#: Named rather than respelled from the member for the reason features 167's,
#: 166's, 165's, 164's, 163's and 168's constants above are: the member's own
#: ``sandbox.BUDGET_COMPONENT_NAME`` is the spelling the builder registers
#: under, and this one is the spelling the app namespace reads it back with.
#: ``packages/sandbox/tests/test_budget_component.py`` pins the two equal, so
#: the pair cannot drift into a silent ``None`` at this seat.
BUDGET_COMPONENT_NAME = "sandbox-budget"

#: The component name the member's seccomp-allowlist law registers under — the
#: category's ninth control, kept beside the other eight rather than over any of
#: them, because the factory's registry replaces a name's earlier registration.
#: Kept here for the same reason the other eight are: one spelling shared by
#: everything that asks for the law through the app package.
#:
#: Named rather than respelled from the member for the reason the eight
#: constants above are: the member's own ``sandbox.SYSCALLS_COMPONENT_NAME`` is
#: the spelling the builder registers under, and this one is the spelling the app
#: namespace reads it back with.
#: ``packages/sandbox/tests/test_syscalls_component.py`` pins the two equal, so
#: the pair cannot drift into a silent ``None`` at this seat.
SYSCALLS_COMPONENT_NAME = "sandbox-syscalls"

#: Feature 161's quarantine law: ``sandbox-quarantine``. The tenth component this
#: member contributes, and the seat beside the other nine — distinct from each of
#: them because the factory's registry replaces a name's earlier registration.
#: Kept here for the same reason the other nine are: one spelling shared by
#: everything that asks for the law through the app package.
#:
#: Named rather than respelled from the member for the reason the nine constants
#: above are: the member's own ``sandbox.QUARANTINE_COMPONENT_NAME`` is the
#: spelling the builder registers under, and this one is the spelling the app
#: namespace reads it back with.
#: ``packages/sandbox/tests/test_quarantine_component.py`` pins the two equal, so
#: the pair cannot drift into a silent ``None`` at this seat.
QUARANTINE_COMPONENT_NAME = "sandbox-quarantine"


def sandbox_isolation_component(
    app: Application | None = None,
) -> SandboxIsolation | Any:
    """Return the composed sandbox isolation law (feature 157).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``sandbox`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.

    The returned law is usable immediately: the member's builder compiles the
    committed isolation artifact at build time and resolves nothing from the
    environment, so a non-``None`` component here is proof the policy loaded
    and the deployment's boxes are held to gVisor.  The only refusals a caller
    meets afterwards come from the runs it asks about.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)


def sandbox_imports_component(
    app: Application | None = None,
) -> SandboxImports | Any:
    """Return the composed sandbox import allowlist (feature 167).

    The same contract :func:`sandbox_isolation_component` gives the isolation
    law, for the control that screens a *submitted module's* imports against
    the configured ceiling: with ``app`` given the component is read from
    that application, without it the application is composed first, and
    ``None`` means no ``sandbox-imports`` component was registered — never
    "registered but not yet configured", for the same reason the isolation
    seat's ``None`` cannot mean that either.

    A non-``None`` component here is proof the committed allowlist artifact
    compiled: the member's builder reads it at build time and resolves
    nothing from the environment, so a caller holding the component holds a
    validated ceiling — ``screen(source)`` for the decision a submission
    earns, whose refusal detail is the ``disallowed_import`` message the
    feature's own sentence names.
    """
    application = app if app is not None else create_app()
    return application.get(IMPORTS_COMPONENT_NAME)


def sandbox_transfer_component(
    app: Application | None = None,
) -> SandboxTransfer | Any:
    """Return the composed sandbox payload channel (feature 166).

    The same contract the other two accessors give their laws, for the
    control that moves the materialized window into the box and the score
    vector back out: with ``app`` given the component is read from that
    application, without it the application is composed first, and ``None``
    means no ``sandbox-transfer`` component was registered.

    **One thing this accessor cannot mean, and it is worth stating rather
    than inferring.**  The other two seats' ``None`` is *"no such component
    was registered"* and a non-``None`` value is proof the committed
    artifact compiled; here there is no committed artifact to compile — the
    feature is a format and an alignment, not a configuration — so a
    non-``None`` component is proof only that the law is loaded, which is
    all there is for it to be.  The value carries no channel either, so a
    caller does not get a transfer from this accessor: it gets the law, and
    calls ``channel()`` for the per-run seam.
    """
    application = app if app is not None else create_app()
    return application.get(TRANSFER_COMPONENT_NAME)


def sandbox_seed_component(
    app: Application | None = None,
) -> SandboxSeed | Any:
    """Return the composed sandbox node seed (feature 165).

    The same contract the other three accessors give their laws, for the
    control that carries the node's seed into every sandboxed invocation and
    persists it on the node record: with ``app`` given the component is read
    from that application, without it the application is composed first, and
    ``None`` means no ``sandbox-seed`` component was registered.

    **Like the transfer seat and unlike the two laws', there is no committed
    artifact behind this one.**  Features 157 and 167 are laws about a
    *configuration* — which isolation a box declares, which imports a
    submission may reach — and a configuration is written down before it can
    be checked, which is why a non-``None`` component at their seats proves a
    file compiled.  Feature 165's subject is a value a run is *handed*: the
    seed §5.2's call site passes as ``seed=node.seed``, which §12 stores on the
    node.  There is no file for a deployment to drift to another seed and no
    knob nobody turns, so a non-``None`` component here is proof only that the
    law is loaded.

    The value carries no seed, so a caller does not get one from this
    accessor: it gets the law, and calls ``require(invocation)`` for the
    integer to hand the box — or for the refusal, on the last line before it
    would have spawned.
    """
    application = app if app is not None else create_app()
    return application.get(SEED_COMPONENT_NAME)


def sandbox_threads_component(
    app: Application | None = None,
) -> SandboxThreads | Any:
    """Return the composed sandbox thread-pinning law (feature 164).

    The same contract the other four accessors give their laws, for the control
    that decides whether an invocation's environment carries §12's two caps:
    with ``app`` given the component is read from that application, without it
    the application is composed first, and ``None`` means no ``sandbox-threads``
    component was registered.

    **Here the artifact-backed reading is available again, unlike the last two
    seats.**  Features 166's and 165's accesses each state that their ``None``
    cannot mean "registered but unconfigured" and that a non-``None`` value
    proves only that the law is loaded, because neither has a committed file
    behind it.  This one does — the pinning policy ships inside the member and
    the builder compiles it at build time and resolves nothing from the
    environment — so a non-``None`` component here is proof the committed
    document compiled and the deployment's caps are pinned at §12's value,
    exactly the conclusion feature 157's and 167's seats entitle a caller to
    draw.  There is still no unconfigured state for a ``None`` to describe: it
    means *no such component was registered*, and nothing else.

    The value carries no environment, so a caller does not get one from this
    accessor: it gets the law, and calls ``require(subject)`` for the
    environment to dispatch with — or for the refusal, on the last line before
    it would have spawned.
    """
    application = app if app is not None else create_app()
    return application.get(THREADS_COMPONENT_NAME)


def sandbox_timeout_component(
    app: Application | None = None,
) -> SandboxTimeout | Any:
    """Return the composed sandbox wall-clock-budget law (feature 163).

    The same contract the other five accessors give their laws, for the control
    that decides whether a run that outran §5.2's thirty-second wall budget is
    hard-killed and recorded as §8's ``timeout`` fail class: with ``app`` given
    the component is read from that application, without it the application is
    composed first, and ``None`` means no ``sandbox-timeout`` component was
    registered.

    **The artifact-backed reading is available here too.**  The committed budget
    ships inside the member (:data:`sandbox.timeout.COMMITTED_TIMEOUT_POLICY`)
    and the builder compiles it at build time, resolving nothing from the
    environment — so a non-``None`` component is proof the committed document
    compiled and this deployment hard-kills past §5.2's thirty seconds, exactly
    the conclusion feature 157's, 167's and 164's seats entitle a caller to
    draw.  There is no unconfigured state for a ``None`` to describe: it means
    *no such component was registered*, and nothing else.

    The value carries no clock and no watchdog, so a caller does not get a
    deadline from this accessor: it gets the law, and calls
    ``check(subject)``/``killed(subject)`` for the answer as a value or
    ``require(subject)`` for the kill on the line after the spawn.  Note that
    ``require`` here has three outcomes rather than the other five laws' two —
    ``None`` for a run inside its budget, a ``TimeoutKill`` for one that
    outran it, and a raise only for a run this law cannot read — because a
    timeout is the pipeline's *recorded outcome* rather than a refusal (§5.2's
    "Timeout | Hard kill, recorded as ``fail_class=timeout``"; §6.1 step 11).
    """
    application = app if app is not None else create_app()
    return application.get(TIMEOUT_COMPONENT_NAME)


def sandbox_fail_class_component(
    app: Application | None = None,
) -> SandboxFailClass | Any:
    """Return the composed sandbox fail-class law (feature 168).

    The same contract the other six accessors give their laws, for the control
    that answers *what is this sandboxed run's fail class?* — one of §9.1's
    ``ok | timeout | error | tripwire_fail``, from every run: with ``app`` given
    the component is read from that application, without it the application is
    composed first, and ``None`` means no ``sandbox-failclass`` component was
    registered.

    **This is the third seat whose missing artifact is the honest state rather
    than a gap.**  Features 166's and 165's accesses state theirs: a format and a
    value a run is handed are not things a deployment could set differently.  So
    is this law's subject — the four words §9.1 declares and the mapping §8's
    definitions fix — so a non-``None`` component here is proof only that the law
    is loaded, not that a file compiled, and there is nothing for a ``None`` to
    describe beyond "no such component was registered".

    The value carries no run and no record, so a caller does not get a class from
    this accessor: it gets the law, and calls ``check(subject)`` for the answer as
    a decision or ``require(subject)`` for the class itself.  Note that
    ``require`` here returns a value for **every** run it classifies, ``ok``
    included — unlike feature 163's, which passes ``None`` through — because
    ``ok`` is one of the four the feature's sentence names, and it raises only
    for a subject this law cannot read or a class outside the vocabulary.
    """
    application = app if app is not None else create_app()
    return application.get(FAIL_CLASS_COMPONENT_NAME)


def sandbox_budget_component(app: Application | None = None) -> SandboxBudget | Any:
    """Return the composed sandbox cgroup-limits law (feature 162).

    The same contract the other seven accessors give their laws, for the control
    that decides whether a run's measured consumption — cpu seconds, memory
    peak, process count — outran §5.2's ``cpu.max``/``memory.max``/``pids.max``:
    with ``app`` given the component is read from that application, without it
    the application is composed first, and ``None`` means no ``sandbox-budget``
    component was registered.

    **The artifact-backed reading is available here too, and this is the fifth
    seat it applies to.**  The committed budget ships inside the member
    (:data:`sandbox.budget.COMMITTED_BUDGET_POLICY`) and the builder compiles it
    at build time, resolving nothing from the environment — so a non-``None``
    component is proof the committed document compiled and this deployment
    confines untrusted code at §5.2's ``cpu_s=30``, ``mem_mb=2048`` and
    ``pids=32``, exactly the conclusion features 157's, 167's, 164's and 163's
    seats entitle a caller to draw.  There is no unconfigured state for a
    ``None`` to describe: it means *no such component was registered*, and
    nothing else.

    The value carries no cgroup, no counter and no probe, so a caller does not
    get a measurement from this accessor: it gets the law, and calls
    ``check(subject)``/``over_limits(subject)`` for the answer as a value or
    ``require(subject)`` for the refusal on the line after the spawn.  Note that
    ``require`` here has the other configuration laws' two outcomes rather than
    feature 163's three — ``None`` for a run measured inside every limit, and a
    raise for a breach *and* for a run this law cannot measure — because a run
    that outran a cgroup limit is a violation of the box rather than a bad
    candidate; the readings it was rejected on come back from ``check`` as the
    decision's per-limit overruns.
    """
    application = app if app is not None else create_app()
    return application.get(BUDGET_COMPONENT_NAME)


def sandbox_syscalls_component(
    app: Application | None = None,
) -> SandboxSyscalls | Any:
    """Return the composed sandbox seccomp-allowlist law (feature 160).

    The same contract the other eight accessors give their laws, for the control
    that answers *may a process in this box make this call?* — §5.2's row
    ``Syscalls | seccomp allowlist``: with ``app`` given the component is read
    from that application, without it the application is composed first, and
    ``None`` means no ``sandbox-syscalls`` component was registered.

    **The artifact-backed reading is available here too, and this is the sixth
    seat it applies to.**  The committed ceiling ships inside the member
    (:data:`sandbox.syscalls.COMMITTED_SYSCALLS_POLICY`) and the builder compiles
    it at build time, resolving nothing from the environment — so a non-``None``
    component is proof the committed document compiled and this deployment's
    boxes run under a seccomp allowlist whose default action *denies*, exactly
    the conclusion features 157's, 167's, 164's, 163's and 162's seats entitle a
    caller to draw.  There is no unconfigured state for a ``None`` to describe:
    it means *no such component was registered*, and nothing else.  Note what the
    proof is *not*: the compiler holds the default action and the well-formedness
    of every term, not a pinned term list, because §5.2 fixes no syscall names —
    so a reviewer reads *which* syscalls are admitted from ``allowed()`` rather
    than from this docstring.

    The value carries no process and no armed filter, so a caller does not get a
    verdict from this accessor: it gets the law, and calls ``check(subject)`` /
    ``allows(name)`` for the answer as a value, ``require(subject)`` for the
    refusal on the line after the filter is armed, or ``filter()`` for the
    specification a launcher hands its runtime.  Note that ``require`` here has
    the other configuration laws' two outcomes rather than feature 163's three —
    ``None`` for an attempt inside the ceiling, and a raise for a call outside it
    *and* for an attempt this law cannot read — because a disallowed syscall is
    §15's sandbox escape attempt rather than a bad candidate; the syscall, the
    action it met and §15's ``sandbox_escape`` class come back from ``check`` as
    the decision's ``violation``, which is what feature 161 quarantines for.
    """
    application = app if app is not None else create_app()
    return application.get(SYSCALLS_COMPONENT_NAME)


def sandbox_quarantine_component(
    app: Application | None = None,
) -> SandboxQuarantine | Any:
    """Return the composed sandbox quarantine law (feature 161).

    The same contract the other nine accessors give their laws, for the control
    that answers *which nodes stop being evaluated because of a seccomp
    violation?* — §15's recovery column: with ``app`` given the component is read
    from that application, without it the application is composed first, and
    ``None`` means no ``sandbox-quarantine`` component was registered.

    **This is the second seat where a non-``None`` component proves only that the
    law is loaded, and the reason is feature 168's own.**  There is no committed
    artifact behind it: §15 fixes the trigger, the recovery and the class, and
    §9.1 fixes the vocabulary the class is read against, so this law's subject is
    a *rule* rather than a deployment's setting, the builder has nothing to
    compile, and there is no file whose drift a ``None`` could report.  So the
    artifact-backed reading features 157's, 167's, 164's, 163's, 162's and 160's
    seats entitle a caller to draw is *not* available here, and nothing is lost:
    what a reviewer would want to read — which class halts a branch, and which
    column the halt is written to — comes back from ``fail_class()`` and
    ``mark_column()`` rather than from a document.

    The value carries no violation and no tree, so a caller does not get a halt
    from this accessor: it gets the law, and calls ``check(subject, tree)`` /
    ``quarantines(subject, tree)`` for the answer as a value, ``require(subject,
    tree)`` for the refusal on the line after feature 160's own ``require``, or
    ``tree(rows)`` to build the closure from the node rows the caller fetched.
    The subtree is *handed in* rather than opened here because the member's
    one-provenance rule keeps the box stdlib-only and store-free — the caller
    owns the fetch, the transaction and the commit — and the handoff from the
    gate is a value: feature 160's decision publishes the ``sandbox_escape``
    commitment, and that is the only subject this law halts a branch for.  A
    timeout, an ``error`` or a tripwire verdict comes back as a refusal rather
    than as a halt, and feature 160's ``None`` — an attempt nobody could read as
    a syscall — comes back as the run continuing, which is what the gate says it
    is.
    """
    application = app if app is not None else create_app()
    return application.get(QUARANTINE_COMPONENT_NAME)
