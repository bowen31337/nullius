"""Feature 157's law: a run without gVisor isolation is refused.

app_spec.xml, "Untrusted Code Sandbox", feature 157: *System rejects a run of
agent-authored code configured without gVisor isolation.*
docs/nullius-tech-architecture.md §5.2 opens the section with the sentence
that gives the feature its weight — *"LLM-authored code is untrusted code.
Treat it that way."* — and its control table fixes the isolation row in two
words: ``Isolation | gVisor (runsc) or Firecracker microVM``.  §18's stack
table chose one of the two for this deployment (``Sandbox | gVisor runsc |
container-native, far lighter than a VM per call``), and §17 restates the
posture from the other side (``Z1 sandboxes: egress denied by default``,
feature 149's law).  The sentence decomposes into three claims, each owned
here as a seam rather than a comment:

* **a run of agent-authored code** — the subject, and the reason the refusal
  is where it is.  The thing being configured is not a service, a store or a
  policy: it is *one execution* of a signal an LLM wrote
  (:class:`SandboxRun`), the same unit §5.2's own call site names
  (``sandbox.run(entrypoint="signal", code=node.code, …)``) and the same unit
  the evaluator's host-side runner takes.  So the law is checked at the two
  moments a run has: when its configuration is *compiled* from a document
  (:func:`compile_isolation_policy`, fail closed, nothing applied) and when a
  run is *admitted* to the launcher
  (:func:`authorize_run`, answer time, refused before anything executes).

* **without gVisor isolation** — the configuration term, held by *membership
  and by name*.  A run names the component it belongs to
  (``SandboxRun.component``), and the component's compiled isolation is looked
  up in the policy the way feature 148's grant and feature 149's egress surface
  are — a third Z1 box inherits the law by being *listed*, not by someone
  remembering to copy a stanza onto it.  The mechanism must be ``gvisor`` and
  the runtime ``runsc``, both spelled once as
  :data:`GVISOR_MECHANISM` and :data:`GVISOR_RUNTIME`; the comparison is
  casefolded, because ``gVisor`` and ``Runsc`` are the same deployment written
  by two people, and a law that refused a capitalization would be a law about
  typography rather than about isolation.

* **rejects** — the consequent, and the shape of the answer.  *Compile time:*
  :func:`compile_isolation_policy` refuses — the whole document, not the one
  component skipped — any component whose isolation is not gVisor's, and any
  document that cannot be read as a policy at all
  (:class:`~sandbox.errors.IsolationDocumentError`).  *Answer time:*
  :func:`authorize_run` answers every run with a
  :class:`RunDecision`, and the answer is *computed* rather than assumed: it
  consults the component's compiled isolation
  (:meth:`IsolationPolicy.isolation_of`), which the compiler holds to gVisor,
  so the admission is the policy arriving at its answer — the same "written,
  not deleted" consultation :mod:`infra.security.sandbox_egress`'s gate makes,
  and for the same reason: a reader can see the run is admitted *because the
  compiled mechanism is gVisor's*, and a decision reading
  :attr:`RunReason.BY_ISOLATION` on a run whose document drifted is itself the
  audit finding.

**Why the refusal is raised at the compile and returned at the gate.**  Two
audiences, two shapes, one law — the split
:mod:`infra.security.sandbox_egress` draws and states: a policy document is
written by *trusted* code (an operator, a CI check that recompiles the
committed artifact), so a document that drifts to another runtime is refused
with an exception the caller cannot ignore
(:class:`~sandbox.errors.GVisorIsolationRequired`).  A *run* is offered by the
pipeline, which §6.1 runs unattended over thousands of candidates, and a
launcher that raised per run would turn a configuration mistake into a crashed
evaluator — so the gate *answers* the run: a decision, raised for none, whose
:attr:`RunDecision.admitted` is ``False`` and whose reason says why.  The
caller that must not proceed checks one boolean; the caller that must not
deploy at all gets an exception.

**The committed artifact is the default, and that is what makes "without"
checkable.**  :data:`COMMITTED_ISOLATION_POLICY` is the document the deployment
runs with before anyone writes a stanza — the same posture feature 149's
committed egress policy and feature 148's committed grant take, and the same
membership (the signal sandbox and the policy runtime, §3's two Z1 boxes).  A
component the policy does not list is not a wider configuration: it is a box
this policy vouches for nothing, and the gate answers it with
:attr:`RunReason.UNKNOWN_COMPONENT` — because an unlisted component's
isolation is *unknown*, and "unknown" is not "gVisor's".

**Honest limits.**  This module is the policy-time law, not the runtime
enforcement: at runtime gVisor's ``runsc`` is the OCI runtime Docker is told to
use, and the kernel-level isolation is gVisor's, not this module's — a Python
object graph can always be assembled by hand with a mechanism no compiler would
issue, exactly as a rogue egress allowance can.  What holds is that the
committed document cannot drift to another runtime without the compile failing,
that the gate derives its answer from the compiled isolation rather than a
hardcoded admission, and that *which* mechanism a component was configured with
is a value the policy carries and a caller can read
(:meth:`IsolationPolicy.isolation_of`) — so "we are running under gVisor" is a
fact about the deployment rather than a line in a README.  The evaluator's
host-side runner (``evaluator._sandbox``) deliberately does *not* reach for
``runsc`` itself and says so in its own docstring: the namespace and seccomp
layers are what a production runner provides underneath that process protocol,
and this module is the law that production runner is written against.

Stdlib-only, like the rest of the zone-guarding trees.  Nothing here spawns a
process, dials a network or reads a container runtime: the module is the law
and the committed artifact is what an operator applies.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from .errors import (
    GVisorIsolationRequired,
    IsolationDocumentError,
)

__all__ = [
    "COMMITTED_ISOLATION_POLICY",
    "GVISOR_MECHANISM",
    "GVISOR_RUNTIME",
    "ISOLATION_REQUIRED_CODE",
    "POLICY_KIND",
    "ComponentIsolation",
    "IsolationPolicy",
    "RunDecision",
    "RunReason",
    "SandboxRun",
    "authorize_run",
    "committed_isolation_policy",
    "compile_isolation_policy",
    "load_isolation_policy",
]

#: The marker a document declares itself with — the same discipline feature
#: 149's committed egress artifact and feature 148's committed grant take, so
#: a stray JSON file carrying a ``components`` key cannot be read as this
#: policy.
POLICY_KIND: Final[str] = "sandbox-isolation"

#: The committed artifact, shipped beside the law that checks it, so a
#: checkout cannot hold one without the other.
COMMITTED_ISOLATION_POLICY: Final[Path] = Path(__file__).with_name(
    "isolation_policy.json"
)

#: §5.2's isolation row, first option: the mechanism.  Keyed as a constant
#: rather than written as a literal at each seam, so the string the compiler
#: accepts and the string the refusal names cannot drift into two spellings.
GVISOR_MECHANISM: Final[str] = "gvisor"

#: §18's stack choice, and §5.2's parenthesized runtime: the OCI runtime
#: gVisor ships.  ``runsc`` is what Docker is told to use
#: (``--runtime=runsc``), and it is the half a deployment is most likely to
#: get wrong while still believing it is "sandboxed" — which is why the
#: policy carries the runtime beside the mechanism rather than deriving one
#: from the other.
GVISOR_RUNTIME: Final[str] = "runsc"

#: The greppable code every isolation refusal carries — feature 157's own
#: subject written as a token, the discipline
#: :data:`nulloracle.schemaguard.NULL_COLUMN` (``is_null_column``) and
#: :data:`nulloracle.plan.HETEROGENEOUS_WORLD` apply to theirs.  An operator
#: grepping a log for the rejection finds it by the feature's own words.
ISOLATION_REQUIRED_CODE: Final[str] = "gvisor_isolation_required"


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise IsolationDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: "
            f"{value!r}. An isolation policy is a structured document, and a "
            f"compiler that guessed at the meaning of a stray list or string "
            f"would be writing policy rather than reading it — refused, fail "
            f"closed (feature 157)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise IsolationDocumentError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). The isolation a component runs under "
            f"is named, not inferred: a mechanism or runtime that is absent, "
            f"blank or not a string is one this policy cannot hold a "
            f"component to, and 'unnamed' is not 'gVisor's' (feature 157, "
            f"refused fail closed)."
        )
    return value


def _is_gvisor(mechanism: Any, runtime: Any) -> bool:
    """Whether a declared pair is gVisor's, compared casefolded.

    The comparison is deliberately forgiving about *case* and unforgiving
    about *substance*: ``gVisor``/``Runsc`` is the same deployment written by
    two people and refusing it would be a law about typography, while
    ``runc``, ``firecracker`` or an empty string is a genuinely different
    isolation story that §5.2's table does not cover for this deployment.
    """
    if not isinstance(mechanism, str) or not isinstance(runtime, str):
        return False
    return (
        mechanism.strip().casefold() == GVISOR_MECHANISM
        and runtime.strip().casefold() == GVISOR_RUNTIME
    )


class ComponentIsolation:
    """One component's compiled isolation: the mechanism and its runtime.

    What :func:`compile_isolation_policy` hands out per component, and the
    object the gate consults, so a run's admission is *derived* from the
    compiled declaration rather than hardcoded to "yes, gVisor" — the same
    "computed, never assumed" stance
    :meth:`infra.security.sandbox_egress.SandboxEgress.admits` takes for an
    egress attempt.

    Under every compiled policy :attr:`mechanism` is ``gvisor`` and
    :attr:`runtime` is ``runsc``, because the compiler refuses anything else.
    The type exists anyway — rather than a bare ``True`` — so that a caller
    asking *what* a component runs under reads a value rather than inferring
    it, and so a hand-assembled policy can carry another pair (which the
    gate's answer would then report, itself the audit finding).
    """

    __slots__ = ("mechanism", "name", "runtime")

    def __init__(self, *, name: str, mechanism: str, runtime: str) -> None:
        self.name = name
        self.mechanism = mechanism
        self.runtime = runtime

    @property
    def is_gvisor(self) -> bool:
        """Whether this declaration is gVisor's, by the same comparison the
        compiler applies — so a caller never has to re-implement the law."""
        return _is_gvisor(self.mechanism, self.runtime)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ComponentIsolation(name={self.name!r}, "
            f"mechanism={self.mechanism!r}, runtime={self.runtime!r})"
        )


class IsolationPolicy:
    """A compiled policy: every listed component runs under gVisor.

    What :func:`compile_isolation_policy` returns is not the document — it is
    the document *plus* the guarantee that no component in it declares an
    isolation other than gVisor's.  Holders (the gate, an operator script, a
    CI check that recompiles the committed artifact) cite that guarantee
    rather than re-derive it, which is why the gate's refusal can say "the
    compiled isolation is not gVisor's" and mean it.
    """

    __slots__ = ("_components", "kind")

    def __init__(self, *, kind: str, components: Mapping[str, ComponentIsolation]) -> None:
        self.kind = kind
        self._components = dict(components)

    def isolation_of(self, name: str) -> ComponentIsolation | None:
        """The named component's isolation, or ``None``.

        The lookup decides nothing: an unknown component is answered by the
        *gate* (:attr:`RunReason.UNKNOWN_COMPONENT`), not by this method
        returning a default — an unlisted component is not a component with a
        permissive isolation, it is one this policy cannot speak about.
        """
        return self._components.get(name)

    def components(self) -> tuple[ComponentIsolation, ...]:
        """Every component the policy covers, in document order."""
        return tuple(self._components.values())

    def names(self) -> tuple[str, ...]:
        """The names of the components the policy covers, in document order."""
        return tuple(self._components)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"IsolationPolicy(kind={self.kind!r}, components={list(self._components)!r})"


def compile_isolation_policy(document: Any) -> IsolationPolicy:
    """Compile an isolation policy, refusing one that is not gVisor's.

    The seam the whole feature turns on.  The document is read whole — marker,
    components — and each component's isolation block is held to the law
    (written, and gVisor's) before a :class:`IsolationPolicy` is handed out.  A
    refusal propagates as an exception, so a caller cannot accidentally
    continue with a half-trusted policy: the document that would have run
    agent-authored code under another mechanism is never applied, which is the
    compile-time half of "System rejects" (feature 157).

    The law is checked over the *raw* block, so its totality does not depend on
    which spelling a drift was written in, and the refusal names the offending
    mechanism and runtime rather than merely the component — a message saying
    only "isolation refused" would hide which of the two a drifted
    configuration got wrong.
    """
    doc = _require_mapping(document, "sandbox isolation policy document")
    marker = _require_str(doc.get("policy"), "sandbox isolation policy 'policy'")
    if marker != POLICY_KIND:
        raise IsolationDocumentError(
            f"a sandbox isolation policy must declare itself {POLICY_KIND!r}, "
            f"got {marker!r}. A document that does not say what it is cannot "
            f"be trusted to say how untrusted code runs under it, and a stray "
            f"JSON file carrying a 'components' key is not this policy — "
            f"refused, fail closed (feature 157)."
        )

    raw_components = doc.get("components")
    if not isinstance(raw_components, Sequence) or isinstance(
        raw_components, (str, bytes)
    ):
        raise IsolationDocumentError(
            f"a sandbox isolation policy's 'components' must be a list of "
            f"component blocks, got {raw_components!r}. The components list is "
            f"the law's whole subject — the Z1 boxes agent-authored code runs "
            f"in — and a document that cannot enumerate them cannot be "
            f"compiled (feature 157)."
        )

    components: dict[str, ComponentIsolation] = {}
    for index, raw_component in enumerate(raw_components):
        block = _require_mapping(raw_component, f"component #{index + 1}")
        name = _require_str(block.get("name"), f"component #{index + 1} 'name'")
        what = f"component {name!r}"
        if name in components:
            raise IsolationDocumentError(
                f"{what} appears twice in the policy. Two blocks with one name "
                f"is not two components, it is one component described twice — "
                f"and the applied policy would be whichever block came last, "
                f"which is drift with extra steps. Refused (feature 157)."
            )

        raw_isolation = block.get("isolation")
        if raw_isolation is None:
            raise IsolationDocumentError(
                f"{what} 'isolation' is absent. §5.2's control table gives "
                f"every sandboxed box its isolation on a named row, and a "
                f"compiler that read an absent block as gVisor's would be "
                f"turning silence into the strongest promise the document "
                f"makes — 'absent' and 'held to gVisor by law' are different "
                f"promises, and only the second is feature 157's (refused, "
                f"fail closed)."
            )
        isolation = _require_mapping(raw_isolation, f"{what} 'isolation'")
        mechanism = _require_str(
            isolation.get("mechanism"), f"{what} isolation 'mechanism'"
        )
        runtime = _require_str(isolation.get("runtime"), f"{what} isolation 'runtime'")

        if not _is_gvisor(mechanism, runtime):
            raise GVisorIsolationRequired(
                f"{ISOLATION_REQUIRED_CODE}: {what} is configured with "
                f"isolation mechanism {mechanism!r} and runtime {runtime!r}, "
                f"which is not gVisor's. §5.2 fixes the isolation of every box "
                f"LLM-authored code runs in — 'LLM-authored code is untrusted "
                f"code. Treat it that way.' — and names gVisor (runsc) for it; "
                f"§18's stack table chose gVisor runsc for this deployment "
                f"(container-native, far lighter than a VM per call). The "
                f"whole document is refused, not the component skipped: a "
                f"policy applied with a component silently dropped is one "
                f"whose file and whose sandbox disagree, and that disagreement "
                f"is where the next drift lives. A run of agent-authored code "
                f"without gVisor isolation is refused (feature 157)."
            )

        components[name] = ComponentIsolation(
            name=name,
            mechanism=GVISOR_MECHANISM,
            runtime=GVISOR_RUNTIME,
        )

    if not components:
        raise IsolationDocumentError(
            "a sandbox isolation policy lists no components, so it vouches "
            "for nothing. Feature 157's subject is the boxes agent-authored "
            "code runs in; a policy that names none would admit every run "
            "with :attr:`RunReason.UNKNOWN_COMPONENT` and claim to be the "
            "law — refused, fail closed."
        )

    return IsolationPolicy(kind=POLICY_KIND, components=components)


def load_isolation_policy(path: Path = COMMITTED_ISOLATION_POLICY) -> IsolationPolicy:
    """Read and compile a policy from disk, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly
    as a drift compiled in memory (feature 157).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise IsolationDocumentError(
            f"could not read the sandbox isolation policy at {path}: {exc}. "
            f"An isolation policy that cannot be read is not a policy that "
            f"admits nothing gracefully — it is one whose deployment has no "
            f"law at all, and a caller that carried on would be running "
            f"agent-authored code while believing it was configured from this "
            f"file (feature 157)."
        ) from exc
    except ValueError as exc:
        raise IsolationDocumentError(
            f"the sandbox isolation policy at {path} is not valid JSON: {exc}. "
            f"Refused rather than read partially: a policy compiled from a "
            f"partially-parsed document is one whose file and whose sandbox "
            f"disagree (feature 157)."
        ) from exc
    return compile_isolation_policy(document)


def committed_isolation_policy() -> IsolationPolicy:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 157's own tests hold to gVisor, so "the deployment is configured
    with gVisor isolation" is a checked fact about a file in the repository
    rather than a claim in a runbook.
    """
    return load_isolation_policy(COMMITTED_ISOLATION_POLICY)


class RunReason(enum.StrEnum):
    """Why a run was admitted or refused — the audit vocabulary.

    One enumeration carries the acceptance and the refusals, because a
    decision's reason is one fact with two polarities and the audit line
    should read the same either way: ``by-isolation`` names the mechanism the
    run was admitted on, and the refusals name what the policy found instead.
    """

    #: Admitted: the component's compiled isolation is gVisor's, both the
    #: mechanism and the runtime.  Reading the string is proof the compiled
    #: declaration was consulted and found to be gVisor's — a hand-assembled
    #: policy carrying another pair can never produce it.
    BY_ISOLATION = "by-isolation"

    #: Refused: the component is listed, and its compiled isolation is not
    #: gVisor's.  Feature 157's headline, and the reason a run rather than a
    #: document is refused at the gate — the pipeline offers thousands of
    #: runs against one policy.
    WITHOUT_GVISOR = "without-gvisor-isolation"

    #: Refused: the run's component is not one this policy covers.  An
    #: unlisted component is not a component with a permissive isolation; it
    #: is one the policy cannot speak about, and "unknown" is not "gVisor's".
    UNKNOWN_COMPONENT = "unknown-component"

    #: Refused: the run does not name a component at all, or names something
    #: that is not a name.  A run that cannot say which box it belongs to
    #: cannot be held to that box's isolation, and the check is not something
    #: a caller may skip by leaving a field out.
    UNNAMED_COMPONENT = "unnamed-component"


class SandboxRun:
    """One run of agent-authored code, as presented to the launcher.

    The unit feature 157's sentence is about — §5.2's
    ``sandbox.run(entrypoint="signal", code=node.code, …)`` — modelled as the
    one thing the isolation law needs to read: which *component* the run
    belongs to, so the component's compiled isolation can be consulted.  It is
    deliberately not the whole call: the limits, the seed, the payload and the
    env of §5.2 belong to the runner that performs the run, and a boundary
    that also modelled them would be a second, divergent copy of
    ``evaluator._sandbox``'s call shape.

    ``payload`` is carried and never inspected — the same stance
    :class:`infra.security.provider_boundary.CodeChannel` takes toward the code
    it carries: this object is a *subject of the law*, not a content filter,
    and a run's admission does not depend on what its payload says.
    """

    __slots__ = ("component", "payload")

    def __init__(self, *, component: str, payload: object = None) -> None:
        self.component = component
        self.payload = payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"SandboxRun(component={self.component!r})"


class RunDecision:
    """The gate's whole answer: admitted or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed*
    from the consulted declaration rather than set by a constant: the gate
    reads the component's compiled isolation and admits only when it is
    gVisor's.  ``detail`` carries the operator-facing sentence — the one place
    the mechanism explains itself at refusal time, naming the component, the
    isolation consulted and the policy.
    """

    __slots__ = ("admitted", "detail", "reason")

    def __init__(self, *, admitted: bool, reason: RunReason, detail: str) -> None:
        self.admitted = admitted
        self.reason = reason
        self.detail = detail

    def require(self) -> None:
        """Raise :class:`~sandbox.errors.GVisorIsolationRequired` if refused.

        The bridge between the gate's returned answer and the compile's raised
        one: a launcher that must not proceed *at any cost* calls ``require()``
        on the decision it was handed and turns a refusal into the same
        exception the compiler raises, so the two halves of feature 157 carry
        one error type and a caller never has to catch two.  A decision that
        admitted the run is a no-op, so a caller can use it unconditionally as
        the last thing before spawning a process.
        """
        if not self.admitted:
            raise GVisorIsolationRequired(self.detail)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"RunDecision(admitted={self.admitted}, reason={self.reason!r})"


def authorize_run(run: SandboxRun, policy: IsolationPolicy) -> RunDecision:
    """Answer one run: admitted only when its component's isolation is gVisor's.

    The order of the checks is the order of the sentence.  The run's subject is
    settled first — a run that cannot name its component has no isolation to be
    evaluated against — then the membership, then the declaration itself, which
    is the only thing that can admit.  Every answer is a value; nothing is
    raised here, because the pipeline runs this over every candidate and a
    configuration mistake must not crash an unattended evaluator.  A caller
    that must not proceed turns the answer into an exception with
    :meth:`RunDecision.require`.
    """
    component = run.component
    if not isinstance(component, str) or not component.strip():
        return RunDecision(
            admitted=False,
            reason=RunReason.UNNAMED_COMPONENT,
            detail=(
                f"{ISOLATION_REQUIRED_CODE}: a run was offered without naming "
                f"the component it belongs to (got {component!r}). Feature "
                f"157's law is held per component — the policy lists the Z1 "
                f"boxes and gives each its isolation — so a run that cannot "
                f"say which box it is cannot be held to one, and 'unnamed' is "
                f"not 'gVisor's'. The run is refused before anything executes."
            ),
        )

    isolation = policy.isolation_of(component)
    if isolation is None:
        return RunDecision(
            admitted=False,
            reason=RunReason.UNKNOWN_COMPONENT,
            detail=(
                f"{ISOLATION_REQUIRED_CODE}: a run claims component "
                f"{component!r}, which is not a component of policy "
                f"{policy.kind!r} (it covers {list(policy.names())!r}). The "
                f"gate answers for the compiled policy and nothing else; an "
                f"unlisted component has no declared isolation to be evaluated "
                f"against and is refused — an unlisted box is not a box with a "
                f"permissive isolation, it is one this policy vouches for "
                f"nothing, and 'unknown' is not 'gVisor's' (feature 157)."
            ),
        )

    if not isolation.is_gvisor:
        return RunDecision(
            admitted=False,
            reason=RunReason.WITHOUT_GVISOR,
            detail=(
                f"{ISOLATION_REQUIRED_CODE}: a run of agent-authored code in "
                f"component {component!r} is configured with isolation "
                f"mechanism {isolation.mechanism!r} and runtime "
                f"{isolation.runtime!r}, which is not gVisor's. §5.2: "
                f"'LLM-authored code is untrusted code. Treat it that way.' — "
                f"and the isolation row of that section's control table is "
                f"'gVisor (runsc) or Firecracker microVM', with §18 choosing "
                f"gVisor runsc for this deployment. The run is refused rather "
                f"than executed: agent-authored code running without gVisor "
                f"underneath it is the failure this feature exists to prevent, "
                f"and a run that proceeded would report an ordinary trial "
                f"outcome for a candidate that was never isolated (feature "
                f"157)."
            ),
        )

    return RunDecision(
        admitted=True,
        reason=RunReason.BY_ISOLATION,
        detail=(
            f"run of component {component!r} admitted: its compiled isolation "
            f"is {isolation.mechanism!r} on {isolation.runtime!r}, which is "
            f"gVisor's — §5.2's isolation row and §18's stack choice for this "
            f"deployment (feature 157)."
        ),
    )
