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
"""

from __future__ import annotations

from app.module_loader import register

from .errors import (
    AllowlistDocumentError,
    DisallowedImportError,
    GVisorIsolationRequired,
    IsolationDocumentError,
    SandboxError,
    SandboxImportError,
    SandboxIsolationError,
    SandboxTransferError,
    ScoreChannelError,
    WindowTransferError,
)
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
    "COMMITTED_IMPORTS_ALLOWLIST",
    "COMMITTED_ISOLATION_POLICY",
    "COMPONENT_NAME",
    "DISALLOWED_IMPORT_CODE",
    "GVISOR_MECHANISM",
    "GVISOR_RUNTIME",
    "IMPORTS_COMPONENT_NAME",
    "IMPORTS_POLICY_KIND",
    "ISOLATION_REQUIRED_CODE",
    "POLICY_KIND",
    "SCORE_CHANNEL_CODE",
    "SCORE_FRAME_NAME",
    "SCORE_MAGIC",
    "SCORE_VERSION",
    "TRANSFER_COMPONENT_NAME",
    "WINDOW_TRANSFER_CODE",
    "AllowlistDocumentError",
    "ComponentIsolation",
    "DisallowedImportError",
    "GVisorIsolationRequired",
    "ImportsAllowlist",
    "IsolationDocumentError",
    "IsolationPolicy",
    "ModuleDecision",
    "ModuleReason",
    "RunDecision",
    "RunReason",
    "SandboxError",
    "SandboxImportError",
    "SandboxImports",
    "SandboxIsolation",
    "SandboxIsolationError",
    "SandboxRun",
    "SandboxTransfer",
    "SandboxTransferError",
    "ScoreChannelError",
    "ScoreVector",
    "TransferChannel",
    "TransferLeg",
    "WindowFacts",
    "WindowTransferError",
    "authorize_run",
    "committed_imports_allowlist",
    "committed_isolation_policy",
    "compile_imports_allowlist",
    "compile_isolation_policy",
    "decode_scores",
    "encode_scores",
    "inspect_window_payload",
    "load_imports_allowlist",
    "load_isolation_policy",
    "sandbox_imports",
    "sandbox_isolation",
    "sandbox_transfer",
    "scores_alias_payload",
    "screen_module",
]

__version__ = "0.1.0"

#: The component name this member registers under — the plugin name
#: app_spec.xml gives the category (``plugin="sandbox"``) and the name of the
#: member's seat in the app namespace (``src/app/modules/sandbox``).  Kept here
#: so anything asking the composed application for the isolation law — by way
#: of the member, not by a hard-coded string — shares one spelling.
COMPONENT_NAME: str = "sandbox"


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
